// App canvas harness fixtures (app profiles, plan section 6, S1 FW-B): harness-only profiles that exercise every
// path of the generic renderer the built-in Onshape does not take -- the label visual, the pyramid and the
// octahedron in each style, unstepped poses, a 32-command ring, 8 rings, commands not on Windows, macros, the WIN
// keycap, the handle parameter with axes / planes / uniform, degrees, label_neg, a range, the plasma sampled from
// the icon, and no profile at all (Loading). Not firmware data: compiled as C (/TC) by app_canvas_tests.py only.
// The element kinds and the profile model are Karl Malota's (katbinaris, feat/firmware-esp-idf-quadra
// NanoDepsidf/src/app_profiles/), used with permission; the scenes here are test drawings, not his cards.
#include <stdio.h>
#include <string.h>
#include "cc_app_profile.h"

#define EL_DISC(x, y, d, c) {APP_EL_DISC, c, x, y, d, d, 0, 0, 0}
#define EL_SEL(x, y, w, h, c) {APP_EL_SEL, c, x, y, w, h, 0, 0, 0}
#define EL_LABEL(x, y, glyph, len, c) {APP_EL_LABEL, c, x, y, len, 0, glyph, 0, 0}
#define EL_CLIP(x, y, c) {APP_EL_CLIPBOARD, c, x, y, 0, 0, 0, 0, 0}
#define EL_PLAY(x, y, d, c) {APP_EL_PLAY, c, x, y, d, d, 0, 0, 0}
#define EL_MODES(bits) {APP_EL_MODES, K_W, 0, 0, 0, 0, bits, 0, 0}
#define EL_ROW(i, glyph, len, c, flags) {APP_EL_ROW, c, 0, i, len, flags, glyph, 2, 0}

// --- scenes: one per element family, with keyframes ---
static const app_scene_t SC_FRAME_TOOL = {
    0, NULL, 2,
    (const app_keyframe_t[]){
        KEYFRAME(600, EL_DASH(10, 10, 44, 40, K_D), EL_ROW(0, APP_GLYPH_RECT, 20, K_G, 0)),
        KEYFRAME(900, EL_SEL(10, 10, 44, 40, K_A), EL_LABEL(12, 14, APP_GLYPH_FRAME, 18, K_W),
                 EL_ROW(0, APP_GLYPH_FRAME, 20, K_W, APP_ROW_SEL), EL_ROW(1, APP_GLYPH_RECT, 16, K_G, APP_ROW_DOT)),
    }};
static const app_scene_t SC_PASTE = {
    2, (const app_el_t[]){EL_CLIP(8, 8, K_W), EL_DISC(30, 30, 18, K_A)},
    1, (const app_keyframe_t[]){KEYFRAME(1000, EL_ROW(0, APP_GLYPH_COMP, 20, K_A, APP_ROW_ALL),
                                         EL_ROW(1, APP_GLYPH_INST, 14, K_G, APP_ROW_CURSOR))}};
static const app_scene_t SC_PLAY = {
    3, (const app_el_t[]){EL_PLAY(18, 18, 26, K_W), EL_MODES(0x05), EL_ROW(1, APP_GLYPH_TEXT, 12, K_W, APP_ROW_FIELD)},
    0, NULL};

// --- params ---
// Plasticity-like handles: scale with X / Y / Z and uniform (default uniform), rotate in degrees about Y with
// planes, move with a negative label and a range.
static const app_param_t P_SCALE = {"SCALE", {0.05f, 0.1f, 0.5f}, 1.0f, 2, APP_PV_SCALE, NULL, 0.01f, 0.1f, 4.0f,
                                    APP_PARAM_AXES | APP_PARAM_PLANES | APP_PARAM_UNIFORM, 0x0C, APP_AXIS_UNIFORM, false};
static const app_param_t P_ROTATE = {"ANGLE", {1.0f, 5.0f, 15.0f}, 0.0f, 0, APP_PV_ROTATE, NULL, 1.0f, -180.0f, 180.0f,
                                     APP_PARAM_DEG | APP_PARAM_AXES | APP_PARAM_PLANES, 0x02, 1, false};
static const app_param_t P_MOVE = {"PUSH", {0.1f, 1.0f, 10.0f}, 0.0f, 1, APP_PV_MOVE, "PULL", 0.1f, -20.0f, 20.0f,
                                   APP_PARAM_AXES, 0x04, 2, false};
static const app_param_t P_OFFSET = {"OFFSET", {0.1f, 1.0f, 10.0f}, 2.0f, 1, APP_PV_OFFSET, "INSET", 0.1f, -5.0f, 5.0f,
                                     0, 0x08, 0, false};

// --- rings ---
static const app_cmd_t BUILD[] = {
    {"FRAME", false, 0, "F", &SC_FRAME_TOOL, NULL, 0},
    {"PASTE OVER", false, APP_MOD_CTRL | APP_MOD_SHIFT, "V", &SC_PASTE, NULL, 0},
    {"SNIP", false, APP_MOD_WIN | APP_MOD_SHIFT, "S", &SC_PLAY, NULL, 0},
    {"MAC ONLY", false, APP_MOD_ALT, "M", &SC_PLAY, NULL, APP_CMD_DISABLED},
    {"TIDY UP", false, 0, NULL, &SC_FRAME_TOOL, NULL, APP_CMD_MACRO},
    {"FIND TOOL", true, 0, NULL, NULL, NULL, 0},
};
static const app_cmd_t EDIT[] = {
    {"SCALE", false, 0, "S", &SC_PLAY, &P_SCALE, 0},
    {"ROTATE", false, 0, "R", &SC_PLAY, &P_ROTATE, 0},
    {"MOVE", false, 0, "G", &SC_PLAY, &P_MOVE, 0},
    {"OFFSET", false, APP_MOD_ALT, "O", NULL, &P_OFFSET, 0},
};
// A full 32-command ring and 8 rings (filled by app_canvas_fixtures_init()).
static char g_names[32][12];
static app_cmd_t g_big[32];
static app_ring_t g_rings8[8];
static const char *const kTabs[8] = {"BUILD", "EDIT", "ALIGN", "TEXT", "LAYER", "VIEW", "UTIL", "BIG"};

// A 48 px icon with four colours (no plasma: sampled) and a 24 px one.
static uint8_t g_icon48[48 * 48 * 2];
static uint8_t g_icon24[24 * 24 * 2];

static void put565(uint8_t *icon, int w, int x, int y, uint16_t v) {
    icon[(y * w + x) * 2] = (uint8_t)(v >> 8);
    icon[(y * w + x) * 2 + 1] = (uint8_t)(v & 0xFF);
}

static void make_icon(uint8_t *icon, int w) {
    // Figma-like: five round blobs (red, orange, purple, blue, green) on black; red and purple biggest.
    static const struct { int cx, cy, r; uint16_t c; } blobs[5] = {
        {16, 10, 9, 0xF203}, {32, 10, 7, 0xFC80}, {16, 26, 9, 0x99BF}, {32, 26, 6, 0x0D5F}, {16, 40, 6, 0x0EAA}};
    memset(icon, 0, (size_t)w * w * 2);
    for (int y = 0; y < w; y++)
        for (int x = 0; x < w; x++)
            for (int b = 0; b < 5; b++) {
                const int dx = x * 48 / w - blobs[b].cx, dy = y * 48 / w - blobs[b].cy;
                if (dx * dx + dy * dy <= blobs[b].r * blobs[b].r) put565(icon, w, x, y, blobs[b].c);
            }
}

#define SLOTS_FIGMA                                                                                                    \
    {{APP_KIND_WHEEL, APP_FX_ZOOM, 0xFF, "ZOOM"}, {APP_KIND_DRAG, APP_FX_PAN, 0, "PAN"},                               \
     {APP_KIND_WHEEL, APP_FX_NONE, 1, "LAYERS"}, {APP_KIND_COMMANDS, APP_FX_NONE, 2, "UNDO"},                          \
     {APP_KIND_DRAG, APP_FX_ORBIT, 3, "ROTATE"}}
static const app_ring_t RINGS2[] = {{"BUILD", "BUILD", 6, BUILD, 3}, {"EDIT", "EDIT", 4, EDIT, 3}};

// The label visual (Figma): name + legend from data, plasma sampled from the icon.
cc_app_profile_t fx_label = {
    "fx-label", "FIGMA", g_icon24, g_icon48, {"PAN", "LAYERS", "UNDO", ""}, {0, 0, 0}, APP_MOD_CTRL, "/",
    2, RINGS2, true, SLOTS_FIGMA, APP_VISUAL_LABEL, APP_SHAPE_CUBE, APP_STYLE_FACE, false, 0x1A2B3C4Du,
    CC_APP_FEAT_LABEL_VISUAL | CC_APP_FEAT_DISABLED_CMDS};
// The label visual with an empty knob label: the icon + the name, large.
cc_app_profile_t fx_label_idle;
// 8 rings, ring 7 with 32 commands.
cc_app_profile_t fx_rings8;
// Shapes: [mesh][style] (stepped), plus unstepped pyramid / thick.
cc_app_profile_t fx_shape[3][3];
cc_app_profile_t fx_unstepped;
static char g_shape_ids[3][3][12];
// S3 review FW-1: a card the decoder accepts (op and colour in range, every other byte any value, 48 elements in the
// base and in each of 16 keyframes) whose ISO boxes, arcs and discs reach far outside the 57 x 56 card pane. Its
// draw cost must stay bounded by the pane, not by the elements' unclipped extent.
static app_el_t g_hostile_el[48];
static app_keyframe_t g_hostile_kf[16];
static app_scene_t g_hostile_scene;
static app_cmd_t g_hostile_cmds[2];
static app_ring_t g_hostile_ring;
cc_app_profile_t fx_hostile;

void app_canvas_fixtures_init(void) {
    make_icon(g_icon48, 48);
    make_icon(g_icon24, 24);
    for (int i = 0; i < 32; i++) {
        snprintf(g_names[i], sizeof(g_names[i]), "CMD %02d", i + 1);
        g_big[i].name = g_names[i];
        g_big[i].search = false;
        g_big[i].modifier = (uint8_t)(i % 4 == 0 ? APP_MOD_CTRL : i % 4 == 1 ? APP_MOD_WIN : 0);
        g_big[i].key = (i % 3 == 2) ? NULL : "K";
        g_big[i].scene = (i & 1) ? &SC_PASTE : &SC_FRAME_TOOL;
        g_big[i].param = NULL;
        g_big[i].flags = (uint8_t)(i % 3 == 2 ? APP_CMD_MACRO : i == 5 ? APP_CMD_DISABLED : 0);
    }
    for (int r = 0; r < 8; r++) {
        g_rings8[r].name = kTabs[r];
        g_rings8[r].tab = kTabs[r];
        g_rings8[r].count = r == 7 ? 32 : r == 1 ? 4 : 6;
        g_rings8[r].cmds = r == 7 ? g_big : r == 1 ? EDIT : BUILD;
        g_rings8[r].slot = 3;
    }
    fx_label_idle = fx_label;
    fx_label_idle.id = "fx-lbl-idle";
    fx_label_idle.slots[0].label = "";
    fx_rings8 = fx_label;
    fx_rings8.id = "fx-rings8";
    fx_rings8.ring_count = 8;
    fx_rings8.rings = g_rings8;
    for (int m = 0; m < 3; m++)
        for (int st = 0; st < 3; st++) {
            cc_app_profile_t *p = &fx_shape[m][st];
            *p = fx_label;
            snprintf(g_shape_ids[m][st], sizeof(g_shape_ids[m][st]), "fx-s%d%d", m, st);
            p->id = g_shape_ids[m][st];
            p->name = "SHAPES";
            p->visual = APP_VISUAL_SHAPE;
            p->shape = (uint8_t)m;
            p->shape_style = (uint8_t)st;
            p->stepped = true;
            p->plasma_heat[0] = 0x2040A0;
            p->plasma_heat[1] = 0x4080E0;
            p->plasma_heat[2] = 0xA0E0FF;
        }
    fx_unstepped = fx_shape[APP_SHAPE_PYRAMID][APP_STYLE_THICK];
    fx_unstepped.id = "fx-unstep";
    fx_unstepped.stepped = false;
    for (int i = 0; i < 48; i++) {
        app_el_t *e = &g_hostile_el[i];
        memset(e, 0, sizeof *e);
        e->color = K_W;
        e->x = (int8_t)(i & 1 ? -128 : 127);
        e->y = (int8_t)(i & 2 ? -128 : 127);
        if (i % 8 == 6) {          // a 255 px arc over 25.5 rad
            e->op = APP_EL_ARC; e->w = 255; e->arg = 0; e->d = 255; e->flags = APP_ARC_DOTTED;
        } else if (i % 8 == 7) {   // a 255 px disc
            e->op = APP_EL_DISC; e->w = 255; e->h = 255;
        } else {                   // a 255 x 255 x 255 iso box: face, fillet 63 and the cut face filled
            e->op = APP_EL_ISO; e->w = 255; e->h = 255; e->d = 255;
            e->arg = (uint8_t)(APP_ISO_ARG_CUT | 0x3F); e->flags = APP_ISO_FACE;
        }
    }
    for (int f = 0; f < 16; f++) {
        g_hostile_kf[f].ms = 100;
        g_hostile_kf[f].n = 48;
        g_hostile_kf[f].el = g_hostile_el;
    }
    g_hostile_scene.n_base = 48;
    g_hostile_scene.base = g_hostile_el;
    g_hostile_scene.n_frames = 16;
    g_hostile_scene.frames = g_hostile_kf;
    for (int i = 0; i < 2; i++) {
        g_hostile_cmds[i].name = i ? "HOSTILE 2" : "HOSTILE";
        g_hostile_cmds[i].key = "H";
        g_hostile_cmds[i].scene = &g_hostile_scene;
    }
    g_hostile_ring.name = "HOSTILE";
    g_hostile_ring.tab = "HOST";
    g_hostile_ring.count = 2;
    g_hostile_ring.cmds = g_hostile_cmds;
    fx_hostile = fx_label;
    fx_hostile.id = "fx-hostile";
    fx_hostile.ring_count = 1;
    fx_hostile.rings = &g_hostile_ring;
}

// The fixture of a harness case's "profile" name, or NULL.
const cc_app_profile_t *app_canvas_fixture(const char *name) {
    if (strcmp(name, "label") == 0) return &fx_label;
    if (strcmp(name, "label-idle") == 0) return &fx_label_idle;
    if (strcmp(name, "rings8") == 0) return &fx_rings8;
    if (strcmp(name, "unstepped") == 0) return &fx_unstepped;
    if (strcmp(name, "hostile") == 0) return &fx_hostile;
    if (strncmp(name, "shape-", 6) == 0 && name[6] >= '0' && name[6] <= '2' && name[7] >= '0' && name[7] <= '2' &&
        name[8] == '\0')
        return &fx_shape[name[6] - '0'][name[7] - '0'];
    return NULL;
}
