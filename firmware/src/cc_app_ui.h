#pragma once
// App canvas screens (A2, 1.0.0-cc5.6): Karl's app-mode UI as pure draw functions over cc_app_gfx -- the
// isometric cube scenes, the command-wheel cards, the wheel, parameter mode, the echo, the main app screen
// and the idle plasma. Each draws one screen from plain inputs; the timing and animation state live in
// cc_app_canvas.cpp (CCAppCanvas). Platform-neutral (firmware, MSVC harness, gnu++11 gate).
//
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/ui_shape.hpp, ui_cards.hpp, ui_fx.hpp, app_colors.h and the APP parts of ui_screens.hpp.
// App profiles (plan section 1e): every screen draws any cc_app_profile_t; the built-in Onshape is drawn as before.

#include <stdint.h>
#include "cc_app_gfx.h"
#include "cc_app_profile.h"

namespace ccui {

// --- the shape (ui_shape) ---
enum ShapeScene : uint8_t { SCENE_ZOOM = 0, SCENE_ORBIT, SCENE_PAN, SCENE_TILT };
struct ShapeView {
    ShapeScene scene;
    uint8_t shape;    // app_shape_t: the mesh (cube, pyramid, octahedron)
    uint8_t style;    // app_shape_style_t: face / grips / thick
    float yaw;    // radians; 45 deg + k*90 deg is the clean 2:1 isometric pose
    float pitch;  // radians the view looks down; SHAPE_REST_PITCH (30 deg) is the isometric rest
    float zoom;   // nested-copy phase: +1 = one doubling
    float pan;    // px of floor travel
    bool flash;   // amber flash (a tap action)
};
constexpr float SHAPE_REST_PITCH = 0.523598776f;   // pi / 6
// Draws the scene into the band y 55..127 (clipped there). Karl's shipped style: round 4A "Thick", a cube.
void shape_scene(const ShapeView& v);

// --- cards (ui_cards) ---
constexpr int CARD_W = 120;
constexpr int CARD_H = 64;
// The scene's keyframe at t_ms (looping), with the card chrome. scene == nullptr draws the "cancel" card.
void draw_card(const app_scene_t* scene, int x, int y, uint32_t t_ms);

struct WheelView {
    const char* ring_name;
    const char* ring_tabs[8];
    int ring_count, ring;
    int count, entry;             // entries incl. cancel (0) + the chosen one
    const char* name;             // "EXTRUDE" / "CANCEL"
    uint8_t modifier;             // APP_MOD_* of the chord
    const char* key;              // its key ("E"); nullptr for cancel
    bool search;                  // tool search: the chord is the search key, + "SEARCH"
    bool disabled;                // APP_CMD_DISABLED: not on Windows, the name and chord drawn grey
    bool macro;                   // APP_CMD_MACRO: the name only, no chord
    const app_scene_t* scene;     // this entry's card (nullptr = cancel)
    const app_scene_t* prev;      // the card sliding out
    bool prev_valid;
    float slide;                  // 0..1 slide progress, 1 = at rest
    int slide_dir;                // +1: moved to the next entry (cards move left)
    uint32_t t_ms;                // time since this entry was chosen (card animation clock)
};
void draw_wheel(const WheelView& v);

struct ParamView {
    const char* name;             // "FILLET"
    const char* label;            // "RADIUS" (label_neg below zero)
    float value;                  // shown: field B the value, field A the change; a handle param the value
    int decimals;
    float steps[3];
    int step;                     // 0-2 (button 1 / knob alone / button 4)
    uint8_t visual;               // app_param_visual_t
    float f3;                     // button 3 held: 0..1 towards cancel, -1 = up
    int nudge;                    // end-stop nudge, px
    bool typed;                   // B (type) shows the value; A (scroll) the change, signed
    float drawn;                  // the value the card draws (A: start + the change), within min..max
    // App profiles: the rest of Karl's param view (a handle param: field false).
    bool field;                   // Onshape's number field: feature list, F1 / KNOB / F4, A / B
    bool degrees;                 // a degree mark after the value, whole-number steps
    uint8_t modes;                // selection-mode strip bits (a handle param)
    bool axes;                    // X / Y / Z chips + the tripod
    uint8_t axis_bits;            // lit axes: one, a plane's two, or all three (uniform)
    int axis;                     // the constrained axis 0-2 (rotate)
};
void draw_param(const ParamView& v);

// A shortcut as small dark keycaps (Windows: CTRL / ALT text caps, the shift arrow), centred.
void draw_chord(uint8_t modifier, const char* key, float cx, int y, const char* tail);

// --- the main app screen (ui_screens draw_app_top + draw_legend) ---
struct AppView {
    const char* name;             // "ONSHAPE"
    const uint8_t* icon24;        // status-bar icon, or nullptr
    const uint8_t* icon48;        // the label visual's icon, or nullptr
    const char* legend[4];        // under the keycaps, physical left to right
    uint8_t buttons_held;         // bit n = physical button n held (keycap lit)
    const char* action_key;       // "KNOB" / "F2" / "F4" (grey)
    const char* action;           // "ZOOM" / "ORBIT" / "PAN" / "TILT" (white; amber while flashing)
    bool flash;
    bool refused;                 // the action line reads POINT AT MODEL (amber)
    bool refusedFocus;            // DD-SEC-001: with refused, it reads CLICK MODEL FIRST (keyboard focus)
    bool generic;                 // a data profile (has_slots): POINT AT THE APP / CLICK THE APP FIRST
    const char* action_via;       // label visual: how ("KNOB", "F1 + KNOB"), grey over the action
    const ShapeView* shape;       // the shape visual, or nullptr: the label visual
    bool echo;                    // a wheel command just ran: its card replays with its name
    const app_scene_t* echo_scene;
    const char* echo_name;
    uint32_t echo_ms;
};
void draw_app_main(const AppView& v);
// App profiles: the neutral app screen while the frame's profile is not loaded (no profile data at all).
void draw_loading();

// --- idle plasma (ui_fx fx_attract, APP mode: rippling out of the profile's 48 px icon at 2x) ---
constexpr int PLASMA_CELL = 4;
constexpr int PLASMA_N = W / PLASMA_CELL;
constexpr int PLASMA_CELLS = PLASMA_N * PLASMA_N;
constexpr int PLASMA_MAX_EDGE = 1024;
// The plasma's lookup tables and scratch (about 8.6 KB): the firmware puts them in PSRAM next to the canvas.
struct PlasmaTables {
    float sine[256];
    float glow[256];
    uint8_t mask[PLASMA_CELLS / 8 + 1];
    uint8_t seed[PLASMA_CELLS / 8 + 1];
    uint8_t dist[PLASMA_CELLS];
    int16_t edge[PLASMA_MAX_EDGE];
    const uint8_t* dist_for;      // the icon `dist` was built from
    bool ready;
    // App profiles: `dist` and `accents` belong to (dist_for, key): a profile decoded later at the same address
    // has another key (its wire CRC), so nothing stale is reused.
    uint32_t key;
    uint32_t accents[3];          // the plasma's heat colours (app_accents())
};
void plasma_init(PlasmaTables& t);
// `heat`: the three hottest steps (RGB888), all 0 = sampled from the icon (app_accents()); the body is the UI's
// greys. `key`: the profile's wire CRC (0 = built-in).
void draw_plasma(PlasmaTables& t, uint32_t t_ms, const uint8_t* icon48, const uint32_t* heat, uint32_t key = 0);
// Karl's app_colors.c: the profile's own three heat colours when it names them, else the three most common
// colours of its 48 px icon (dark to bright), else AMBER x 3.
void app_accents(const uint8_t* icon48, const uint32_t* heat, uint32_t out[3]);

} // namespace ccui
