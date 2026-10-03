#pragma once
// App canvas (A2, 1.0.0-cc5.6): the display-side description of an app profile -- the command wheel's
// rings, commands, their animated cards (scene data) and parameter-mode visuals. Pure C data (the
// scene tables use C99 compound literals), read by the C++ drawing code (cc_app_*.cpp).
//
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/app_profiles/app_profile.h. Trimmed to what the knob draws: the input side (slots,
// HID key codes, search macro timing, parameter keys) lives in Desk Dial (control_center/onshape_app.py),
// which drives the wheel and parameter mode and sends their state in the frame's `app` object
// (CONTROL_CENTER.md "App canvas"). Shortcut chords here are display only, already Windows-translated.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// --- Scene elements (Karl's app_profile.h "Command wheel", unchanged semantics) ---
typedef enum {
    APP_EL_BOX = 0,  // filled rect, corners cut (x, y, w, h)
    APP_EL_FRAME,    // 1px outline, corners cut
    APP_EL_DASH,     // dashed 1px outline
    APP_EL_DISC,     // filled circle, top-left (x, y), diameter w
    APP_EL_SEL,      // selection: 1px box + 3x3 corner handles
    APP_EL_LABEL,    // canvas label: glyph `arg` + a name bar `w` long
    APP_EL_LINE,     // (x, y) -> (w, h)
    APP_EL_CLIPBOARD,
    APP_EL_PLAY,
    APP_EL_ROW,      // layers row: y = row index, x = depth, glyph `arg`, name bar `w`, flags `h`, `d` offset
    APP_EL_ISO,      // isometric 2:1 box: (x, y) corner, w = a, h = b, d = height, arg = fillet, flags APP_ISO_*
    APP_EL_MODES,    // selection-mode strip, arg = active bits
    APP_EL_ARC,      // centre (x, y), radius w, from arg/10 to d/10 rad, flags APP_ARC_*
    APP_EL_NUM,      // the number `arg`, centred on x, top at y
    APP_EL_ROLLBACK  // Onshape's rollback bar under feature-list row y - 1
} app_el_op_t;
#define APP_ARC_ROUND 0x01
#define APP_ARC_NO_HEAD 0x02
#define APP_ARC_DOTTED 0x04
#define APP_ISO_SOLID 0x01
#define APP_ISO_FACE 0x02
#define APP_ISO_EDGE 0x04
#define APP_ISO_POINTS 0x08
#define APP_ISO_GHOST 0x10
#define APP_ISO_NO_BOTTOM 0x20
#define APP_ISO_GRIPS 0x40
#define APP_ISO_HOLLOW 0x80
#define APP_ISO_ARG_CUT 0x40
#define APP_ISO_ARG_CHAMFER 0x80
#define APP_LINE_HEAD 0x01
#define APP_LINE_DASHED 0x02
typedef enum { APP_C_BLACK = 0, APP_C_DARK, APP_C_GREY, APP_C_WHITE, APP_C_AMBER } app_el_color_t;
typedef enum {
    APP_GLYPH_RECT = 0, APP_GLYPH_CIRCLE, APP_GLYPH_FRAME, APP_GLYPH_AUTO, APP_GLYPH_GROUP,
    APP_GLYPH_COMP, APP_GLYPH_INST, APP_GLYPH_TEXT, APP_GLYPH_SOLID, APP_GLYPH_SHEET, APP_GLYPH_SKETCH
} app_glyph_t;
#define APP_ROW_SEL 0x01
#define APP_ROW_DOT 0x02
#define APP_ROW_FIELD 0x04
#define APP_ROW_ALL 0x08
#define APP_ROW_CURSOR 0x10

typedef struct {
    uint8_t op;    // app_el_op_t
    uint8_t color; // app_el_color_t
    int8_t x, y;
    uint8_t w, h;
    uint8_t arg;
    uint8_t d;
    uint8_t flags;
} app_el_t;

typedef struct {
    uint16_t ms;
    uint8_t n;
    const app_el_t *el;
} app_keyframe_t;

typedef struct {
    uint8_t n_base;
    const app_el_t *base;
    uint8_t n_frames;
    const app_keyframe_t *frames;
} app_scene_t;

#define K_B APP_C_BLACK
#define K_D APP_C_DARK
#define K_G APP_C_GREY
#define K_W APP_C_WHITE
#define K_A APP_C_AMBER
#define EL_BOX(x, y, w, h, c) {APP_EL_BOX, c, x, y, w, h, 0, 0, 0}
#define EL_FRAME(x, y, w, h, c) {APP_EL_FRAME, c, x, y, w, h, 0, 0, 0}
#define EL_DASH(x, y, w, h, c) {APP_EL_DASH, c, x, y, w, h, 0, 0, 0}
#define EL_LINE(x0, y0, x1, y1, c) {APP_EL_LINE, c, x0, y0, x1, y1, 0, 0, 0}
#define EL_ISO(x, y, a, b, h, flags) {APP_EL_ISO, K_W, x, y, a, b, 0, h, flags}
#define EL_ISO_FILLET(x, y, a, b, h, r, flags) {APP_EL_ISO, K_W, x, y, a, b, r, h, flags}
#define EL_ELLIPSE(x, y, r, t0, t1, c, flags) {APP_EL_ARC, c, x, y, r, 0, t0, t1, (APP_ARC_NO_HEAD | (flags))}
#define EL_CIRCLE(x, y, r, c) {APP_EL_ARC, c, x, y, r, 0, 0, 63, (APP_ARC_ROUND | APP_ARC_NO_HEAD)}
#define EL_CARC(x, y, r, t0, t1, c) {APP_EL_ARC, c, x, y, r, 0, t0, t1, (APP_ARC_ROUND | APP_ARC_NO_HEAD)}
#define EL_NUM(x, y, n, c) {APP_EL_NUM, c, x, y, 0, 0, n, 0, 0}
#define EL_FROW(i, glyph, len, c, flags) {APP_EL_ROW, c, 0, i, len, flags, glyph, 2, 0}
#define EL_ROLLBACK(i) {APP_EL_ROLLBACK, K_G, 0, i, 0, 0, 0, 2, 0}
#define EL_ARROW(x0, y0, x1, y1, c) {APP_EL_LINE, c, x0, y0, x1, y1, APP_LINE_HEAD, 0, 0}
#define EL_DLINE(x0, y0, x1, y1, c) {APP_EL_LINE, c, x0, y0, x1, y1, APP_LINE_DASHED, 0, 0}
#define EL_LIST(...) (const app_el_t[]){__VA_ARGS__}
#define EL_COUNT(...) (uint8_t)(sizeof((const app_el_t[]){__VA_ARGS__}) / sizeof(app_el_t))
#define KEYFRAME(ms, ...) {ms, EL_COUNT(__VA_ARGS__), EL_LIST(__VA_ARGS__)}

// --- Parameter mode (display side) ---
typedef enum {
    APP_PV_NONE = 0, APP_PV_FILLET, APP_PV_EXTRUDE, APP_PV_OFFSET, APP_PV_HOLLOW,
    APP_PV_MOVE, APP_PV_ROTATE, APP_PV_SCALE, APP_PV_CHAMFER, APP_PV_SLIDE
} app_param_visual_t;

typedef struct {
    const char *label;      // "DEPTH"
    float steps[3];         // F1 held / knob alone / F4 held (Onshape: 0.01 / 0.1 / 1.0)
    float start;            // B (type) starts here; A (scroll) draws start + the change
    uint8_t decimals;
    uint8_t visual;         // app_param_visual_t
    // App profiles (APP_PROFILES.md, wire 1): the rest of Karl's app_param_t. Zero in the built-in Onshape.
    const char *label_neg;  // shown below zero, NULL = label
    float free_step;        // knob alone: value change per fine click
    float min, max;
    uint8_t flags;          // APP_PARAM_*
    uint8_t modes;          // selection-mode strip bits on the card
    uint8_t axis_default;   // 0-2 = X / Y / Z, APP_AXIS_UNIFORM
    bool field;             // number field (Onshape A/B) rather than a handle
} app_param_t;
#define APP_PARAM_DEG 0x01
#define APP_PARAM_AXES 0x02
#define APP_PARAM_PLANES 0x04
#define APP_PARAM_UNIFORM 0x08
#define APP_AXIS_UNIFORM 3

// Display chord modifiers (Windows keycaps): the wheel shows them as CTRL / ALT / shift-arrow caps.
#define APP_MOD_CTRL 0x01
#define APP_MOD_SHIFT 0x02
#define APP_MOD_ALT 0x04
#define APP_MOD_WIN 0x08

typedef struct {
    const char *name;         // "EXTRUDE"
    bool search;              // runs through the app's tool search (the chord is the search key)
    uint8_t modifier;         // APP_MOD_* of the shortcut
    const char *key;          // its key ("E"); NULL with `search`
    const app_scene_t *scene; // the card, or NULL
    const app_param_t *param; // parameter mode after it runs, or NULL
    uint8_t flags;            // APP_CMD_* (app profiles)
} app_cmd_t;
#define APP_CMD_DISABLED 0x01 // not available on Windows: drawn grey, refused
#define APP_CMD_MACRO 0x02    // runs a macro (no chord drawn)

typedef struct {
    const char *name;         // "MODEL"
    const char *tab;          // ring tab, <= 6 chars
    uint8_t count;
    const app_cmd_t *cmds;    // entry 0 of the wheel is "cancel"; entry n is cmds[n - 1]
    uint8_t slot;             // app profiles: Karl's app_slot_t of the F key that jumps here
} app_ring_t;

// --- App profiles (APP_PROFILES.md): Karl's app_profile_t display fields ---
typedef enum { APP_VISUAL_LABEL = 0, APP_VISUAL_SHAPE } app_visual_t;
typedef enum { APP_SHAPE_CUBE = 0, APP_SHAPE_PYRAMID, APP_SHAPE_OCTA } app_shape_t;
typedef enum { APP_STYLE_FACE = 0, APP_STYLE_GRIPS, APP_STYLE_THICK } app_shape_style_t;
typedef enum { APP_FX_NONE = 0, APP_FX_ZOOM, APP_FX_ORBIT, APP_FX_PAN, APP_FX_FLASH } app_fx_t;
typedef enum { APP_KIND_NONE = 0, APP_KIND_DRAG, APP_KIND_WHEEL, APP_KIND_KEYS, APP_KIND_TAP,
               APP_KIND_COMMANDS } app_slot_kind_t;
#define APP_SLOTS 5 // knob, f1, f2, f3, f4 (Karl's app_slot_t)
typedef struct {
    uint8_t kind;      // app_slot_kind_t
    uint8_t fx;        // app_fx_t
    uint8_t button;    // physical button 0-3 that selects it, 0xFF = knob alone / none
    const char *label; // shown large while live ("ZOOM"), "" = none
} cc_app_slot_t;

// Wire feature bits (APP_PROFILES.md section 4).
#define CC_APP_FEAT_SHAPE 0x01u
#define CC_APP_FEAT_SHAPE_EXT 0x02u
#define CC_APP_FEAT_LABEL_VISUAL 0x04u
#define CC_APP_FEAT_PARAM_CONSTRAINTS 0x08u
#define CC_APP_FEAT_DISABLED_CMDS 0x10u
#define CC_APP_FEATURES_SUPPORTED 0x1Fu

typedef struct {
    const char *id;            // "onshape" (the frame's app.id)
    const char *name;          // "ONSHAPE"
    const uint8_t *icon24;     // 24x24 RGB565 big-endian, or NULL
    const uint8_t *icon48;     // 48x48 RGB565 big-endian, or NULL (the idle plasma)
    const char *legend[4];     // under the keycaps, physical left to right
    uint32_t plasma_heat[3];   // RGB888, cool -> hottest
    uint8_t search_modifier;   // the tool-search chord (display)
    const char *search_key;
    uint8_t ring_count;
    const app_ring_t *rings;
    // App profiles (APP_PROFILES.md). `has_slots` false = the built-in Onshape's legacy slot model.
    bool has_slots;
    cc_app_slot_t slots[APP_SLOTS];
    uint8_t visual;            // app_visual_t
    uint8_t shape;             // app_shape_t
    uint8_t shape_style;       // app_shape_style_t
    bool stepped;
    uint32_t crc;              // wire CRC-32 (0 = built-in)
    uint32_t features;         // CC_APP_FEAT_*
} cc_app_profile_t;

extern const cc_app_profile_t cc_app_profile_onshape;
extern const uint8_t cc_app_icon_onshape_24[24 * 24 * 2];
extern const uint8_t cc_app_icon_onshape_48[48 * 48 * 2];

// App ids of the frame's app.id (cc_presentation.h CCAppState::id).
#define CC_APP_ID_NONE 0
#define CC_APP_ID_ONSHAPE 1

// The profile for a frame's app id, or NULL.
const cc_app_profile_t *cc_app_profile(uint8_t id);

#ifdef __cplusplus
}
#endif
