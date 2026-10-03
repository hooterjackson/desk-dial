// Onshape on the app canvas (A2, 1.0.0-cc5.6): the command wheel's rings, commands and animated cards,
// and parameter mode's visuals. Display data only (cc_app_profile.h); Desk Dial sends the shortcuts.
//
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/app_profiles/onshape.c. The scenes, rings, command names and parameter visuals are his;
// the chords are the Windows ones (Onshape's "Keyboard shortcuts" page: Ctrl for Cmd, Alt for Option;
// tool search Alt+C), and the legend is Karl's with F1 TILT for his ZOOM (1 Tilt, 2 Orbit, 3 Wheel / Undo, 4 Pan;
// Desk Dial 7.2.2.0: hold 1 + turn tilts, the knob alone zooms; Home is all four buttons held 1 s, not drawn).
#include "cc_app_profile.h"

#define SHIFT APP_MOD_SHIFT

// Cards: Plasticity's iso wireframe viewport on the left, Onshape's feature list on the right -- the
// new feature amber above the rollback bar.
#define BOX(f) EL_ISO(32, 30, 16, 16, 12, f)
#define FLASH EL_FRAME(5, 5, 55, 54, K_A)
#define TREE EL_FROW(0, APP_GLYPH_SKETCH, 14, K_G, 0), EL_FROW(1, APP_GLYPH_SOLID, 18, K_G, 0)
#define TREE0 TREE, EL_ROLLBACK(2)
#define TREE_NEW(glyph, len) TREE, EL_FROW(2, glyph, len, K_A, 0), EL_ROLLBACK(3)
#define TREE_ADD(len) TREE_NEW(APP_GLYPH_SOLID, len)
#define TREE_SK EL_FROW(0, APP_GLYPH_SHEET, 10, K_G, 0), EL_FROW(1, APP_GLYPH_SKETCH, 14, K_W, APP_ROW_SEL), EL_ROLLBACK(2)
#define TREE_PICK EL_FROW(0, APP_GLYPH_SKETCH, 14, K_W, APP_ROW_SEL), EL_ROLLBACK(1)
#define TREE_MADE EL_FROW(0, APP_GLYPH_SKETCH, 14, K_G, 0), EL_FROW(1, APP_GLYPH_SOLID, 18, K_A, 0), EL_ROLLBACK(2)
#define PLANE EL_DASH(8, 8, 48, 48, K_D)
#define VTX(x, y, c) EL_BOX((x) - 1, (y) - 1, 3, 3, c)
#define SCENE(name, ...)                                                                              \
    static const app_scene_t name = {                                                                 \
        .n_frames = (uint8_t)(sizeof((const app_keyframe_t[]){__VA_ARGS__}) / sizeof(app_keyframe_t)), \
        .frames = (const app_keyframe_t[]){__VA_ARGS__},                                              \
    }

// MODEL
SCENE(SC_SKETCH,
      KEYFRAME(650, BOX(APP_ISO_FACE), TREE0),
      KEYFRAME(90, BOX(APP_ISO_FACE), FLASH, TREE0),
      KEYFRAME(500, EL_FRAME(16, 16, 32, 32, K_W), TREE_NEW(APP_GLYPH_SKETCH, 12)),
      KEYFRAME(1300, EL_FRAME(16, 16, 32, 32, K_W), EL_FRAME(22, 22, 20, 14, K_A), TREE_NEW(APP_GLYPH_SKETCH, 12)));
SCENE(SC_EXTRUDE,
      KEYFRAME(600, EL_ISO(32, 40, 16, 16, 0, APP_ISO_FACE), TREE_PICK),
      KEYFRAME(80, EL_ISO(32, 38, 16, 16, 5, APP_ISO_FACE), TREE_PICK),
      KEYFRAME(80, EL_ISO(32, 36, 16, 16, 10, APP_ISO_FACE), TREE_PICK),
      KEYFRAME(1300, EL_ISO(32, 35, 16, 16, 14, APP_ISO_FACE), TREE_MADE));
#define AXIS(c) EL_DLINE(32, 8, 32, 56, c)
#define PROFILE EL_FRAME(34, 20, 10, 24, K_W)
SCENE(SC_REVOLVE,
      KEYFRAME(650, AXIS(K_A), PROFILE, TREE_PICK),
      KEYFRAME(90, AXIS(K_A), PROFILE, EL_ELLIPSE(32, 44, 12, 0, 31, K_A, 0), TREE_PICK),
      KEYFRAME(1300, AXIS(K_D), EL_ELLIPSE(32, 20, 12, 0, 63, K_W, 0), EL_ELLIPSE(32, 44, 12, 0, 31, K_W, 0),
               EL_ELLIPSE(32, 44, 12, 31, 63, K_D, APP_ARC_DOTTED), EL_LINE(20, 20, 20, 44, K_W),
               EL_LINE(44, 20, 44, 44, K_W), TREE_MADE));
SCENE(SC_FILLET,
      KEYFRAME(650, BOX(APP_ISO_EDGE), TREE0),
      KEYFRAME(90, EL_ISO_FILLET(32, 30, 16, 16, 12, 3, 0), TREE_ADD(14)),
      KEYFRAME(1300, EL_ISO_FILLET(32, 30, 16, 16, 12, 6, 0), TREE_ADD(14)));
SCENE(SC_CHAMFER,
      KEYFRAME(650, BOX(APP_ISO_EDGE), TREE0),
      KEYFRAME(90, EL_ISO_FILLET(32, 30, 16, 16, 12, 3 | APP_ISO_ARG_CHAMFER, 0), TREE_ADD(16)),
      KEYFRAME(1300, EL_ISO_FILLET(32, 30, 16, 16, 12, 6 | APP_ISO_ARG_CHAMFER, 0), TREE_ADD(16)));
SCENE(SC_SHELL,
      KEYFRAME(650, BOX(APP_ISO_FACE), TREE0),
      KEYFRAME(1300, EL_ISO_FILLET(32, 30, 16, 16, 12, 3, APP_ISO_HOLLOW), TREE_ADD(12)));

// MODIFY
SCENE(SC_BOOLEAN,
      KEYFRAME(650, EL_ISO(30, 38, 20, 20, 8, 0), EL_ISO(30, 20, 10, 10, 8, APP_ISO_SOLID), TREE0),
      KEYFRAME(90, EL_ISO(30, 38, 20, 20, 8, 0), EL_ISO(30, 25, 10, 10, 8, APP_ISO_SOLID), TREE0),
      KEYFRAME(1300, EL_ISO(30, 38, 20, 20, 8, APP_ISO_SOLID), EL_ISO(30, 30, 10, 10, 8, APP_ISO_SOLID | APP_ISO_NO_BOTTOM),
               TREE_ADD(16)));
SCENE(SC_SPLIT,
      KEYFRAME(650, BOX(0), EL_DLINE(20, 14, 46, 46, K_A), TREE0),
      KEYFRAME(1300, EL_ISO(28, 32, 8, 16, 12, 0), EL_ISO(40, 30, 8, 16, 12, APP_ISO_SOLID), TREE_ADD(10)));
SCENE(SC_TRANSFORM,
      KEYFRAME(650, EL_ISO(24, 28, 12, 12, 10, APP_ISO_SOLID), TREE0),
      KEYFRAME(90, EL_ISO(24, 28, 12, 12, 10, APP_ISO_GHOST), EL_ISO(31, 31, 12, 12, 10, APP_ISO_SOLID), TREE0),
      KEYFRAME(1300, EL_ISO(24, 28, 12, 12, 10, APP_ISO_GHOST), EL_ISO(38, 34, 12, 12, 10, APP_ISO_SOLID),
               EL_ARROW(28, 42, 42, 49, K_A), TREE_ADD(20)));
SCENE(SC_PATTERN,
      KEYFRAME(650, EL_ISO(16, 22, 8, 8, 8, APP_ISO_SOLID), TREE0),
      KEYFRAME(90, EL_ISO(16, 22, 8, 8, 8, APP_ISO_SOLID), EL_ISO(30, 29, 8, 8, 8, APP_ISO_GHOST),
               EL_ISO(44, 36, 8, 8, 8, APP_ISO_GHOST), TREE0),
      KEYFRAME(1300, EL_ISO(16, 22, 8, 8, 8, 0), EL_ISO(30, 29, 8, 8, 8, APP_ISO_SOLID), EL_ISO(44, 36, 8, 8, 8, APP_ISO_SOLID),
               TREE_ADD(16)));
SCENE(SC_MIRROR,
      KEYFRAME(650, EL_ISO(22, 26, 10, 12, 12, APP_ISO_SOLID), EL_DLINE(33, 10, 33, 54, K_A), TREE0),
      KEYFRAME(1300, EL_ISO(22, 26, 10, 12, 12, 0), EL_DLINE(33, 10, 33, 54, K_A), EL_ISO(46, 26, 12, 10, 12, APP_ISO_SOLID),
               TREE_ADD(14)));
SCENE(SC_MOVE_FACE,
      KEYFRAME(650, BOX(APP_ISO_FACE), TREE0),
      KEYFRAME(80, EL_ISO(32, 30, 16, 16, 15, APP_ISO_FACE), TREE0),
      KEYFRAME(1300, EL_ISO(32, 30, 16, 16, 18, APP_ISO_FACE), EL_ARROW(52, 26, 52, 14, K_A), TREE_ADD(18)));

// SKETCH: flat 2D views; the new entity amber, placed vertices white.
SCENE(SC_LINE,
      KEYFRAME(500, PLANE, VTX(16, 46, K_A), TREE_SK),
      KEYFRAME(90, PLANE, EL_LINE(16, 46, 30, 34, K_A), VTX(16, 46, K_W), TREE_SK),
      KEYFRAME(1300, PLANE, EL_LINE(16, 46, 46, 20, K_A), VTX(16, 46, K_W), VTX(46, 20, K_W), TREE_SK));
SCENE(SC_RECT,
      KEYFRAME(500, PLANE, VTX(16, 18, K_A), TREE_SK),
      KEYFRAME(90, PLANE, EL_FRAME(16, 18, 16, 12, K_A), VTX(16, 18, K_W), TREE_SK),
      KEYFRAME(1300, PLANE, EL_FRAME(16, 18, 32, 26, K_A), VTX(16, 18, K_W), VTX(47, 43, K_W), TREE_SK));
SCENE(SC_CIRCLE,
      KEYFRAME(500, PLANE, VTX(32, 32, K_A), TREE_SK),
      KEYFRAME(90, PLANE, EL_CIRCLE(32, 32, 8, K_A), VTX(32, 32, K_W), TREE_SK),
      KEYFRAME(1300, PLANE, EL_CIRCLE(32, 32, 16, K_A), VTX(32, 32, K_W), TREE_SK));
SCENE(SC_ARC,
      KEYFRAME(500, PLANE, VTX(14, 40, K_A), VTX(50, 40, K_A), TREE_SK),
      KEYFRAME(1300, PLANE, EL_CARC(32, 44, 18, 2, 29, K_A), VTX(14, 40, K_W), VTX(50, 40, K_W), TREE_SK));
#define DIM_LINE EL_LINE(14, 40, 50, 40, K_W), VTX(14, 40, K_W), VTX(50, 40, K_W)
SCENE(SC_DIMENSION,
      KEYFRAME(500, PLANE, DIM_LINE, TREE_SK),
      KEYFRAME(1300, PLANE, DIM_LINE, EL_LINE(14, 36, 14, 22, K_A), EL_LINE(50, 36, 50, 22, K_A),
               EL_LINE(14, 26, 50, 26, K_A), EL_NUM(32, 14, 20, K_A), TREE_SK));
SCENE(SC_TRIM,
      KEYFRAME(500, PLANE, EL_LINE(12, 32, 52, 32, K_W), EL_LINE(32, 12, 32, 52, K_W), TREE_SK),
      KEYFRAME(120, PLANE, EL_LINE(12, 32, 52, 32, K_W), EL_LINE(32, 12, 32, 31, K_W), EL_DLINE(32, 33, 32, 52, K_A), TREE_SK),
      KEYFRAME(1300, PLANE, EL_LINE(12, 32, 52, 32, K_W), EL_LINE(32, 12, 32, 32, K_W), VTX(32, 32, K_W), TREE_SK));
SCENE(SC_CONSTRUCTION,
      KEYFRAME(650, PLANE, EL_LINE(14, 44, 50, 20, K_W), VTX(14, 44, K_W), VTX(50, 20, K_W), TREE_SK),
      KEYFRAME(1300, PLANE, EL_DLINE(14, 44, 50, 20, K_A), VTX(14, 44, K_W), VTX(50, 20, K_W), TREE_SK));

// VIEW: the model, a flash as the camera snaps, then the new view.
#define VIEW_SCENE(name, before, ...) \
    SCENE(name, KEYFRAME(650, before, TREE0), KEYFRAME(90, before, FLASH, TREE0), KEYFRAME(1300, __VA_ARGS__, TREE0))
VIEW_SCENE(SC_FRONT, BOX(0), EL_FRAME(16, 20, 32, 24, K_W));
VIEW_SCENE(SC_RIGHT, BOX(0), EL_FRAME(20, 20, 24, 24, K_W));
VIEW_SCENE(SC_TOP, BOX(0), EL_FRAME(16, 16, 32, 32, K_W));
VIEW_SCENE(SC_ISO, EL_FRAME(16, 20, 32, 24, K_W), BOX(0));
VIEW_SCENE(SC_NORMAL, BOX(APP_ISO_FACE), EL_FRAME(16, 16, 32, 32, K_A));
VIEW_SCENE(SC_FIT, EL_ISO(46, 42, 6, 6, 5, 0), EL_ISO(32, 22, 20, 20, 16, 0));
SCENE(SC_SECTION,
      KEYFRAME(650, BOX(0), TREE0),
      KEYFRAME(90, BOX(0), EL_DLINE(28, 12, 28, 58, K_A), TREE0),
      KEYFRAME(1300, EL_ISO_FILLET(32, 30, 8, 16, 12, APP_ISO_ARG_CUT, 0), TREE0));

// Parameter mode: Onshape's number fields step 0.1 per scroll notch, 0.01 with Ctrl, 1.0 with Shift
// (Onshape help "Numeric fields"). steps = F1 / knob alone / F4. `start` is only used by B (type).
#define STEPS_FIELD {0.01f, 0.10f, 1.00f}
static const app_param_t P_EXTRUDE = {"DEPTH", STEPS_FIELD, 25.0f, 2, APP_PV_EXTRUDE, NULL, 0.0f, 0.0f, 0.0f, 0, 0, 0, true};
static const app_param_t P_FILLET = {"RADIUS", STEPS_FIELD, 1.0f, 2, APP_PV_FILLET, NULL, 0.0f, 0.0f, 0.0f, 0, 0, 0, true};
static const app_param_t P_CHAMFER = {"DISTANCE", STEPS_FIELD, 1.0f, 2, APP_PV_CHAMFER, NULL, 0.0f, 0.0f, 0.0f, 0, 0, 0, true};
static const app_param_t P_SHELL = {"THICKNESS", STEPS_FIELD, 1.0f, 2, APP_PV_HOLLOW, NULL, 0.0f, 0.0f, 0.0f, 0, 0, 0, true};
static const app_param_t P_MOVE_FACE = {"DISTANCE", STEPS_FIELD, 0.0f, 2, APP_PV_OFFSET, NULL, 0.0f, 0.0f, 0.0f, 0, 0, 0, true};
static const app_param_t P_TRANSFORM = {"DISTANCE", STEPS_FIELD, 0.0f, 2, APP_PV_SLIDE, NULL, 0.0f, 0.0f, 0.0f, 0, 0, 0, true};

// Chords as shown on the wheel (Windows). The same table, with the phrases typed into tool search, is
// control_center/onshape_app.py COMMANDS (tests/test_onshape_app.py checks the two agree).
static const app_cmd_t MODEL[] = {
    {"SKETCH", false, SHIFT, "S", &SC_SKETCH, NULL, 0},
    {"EXTRUDE", false, SHIFT, "E", &SC_EXTRUDE, &P_EXTRUDE, 0},
    {"REVOLVE", false, SHIFT, "W", &SC_REVOLVE, NULL, 0},
    {"FILLET", false, SHIFT, "F", &SC_FILLET, &P_FILLET, 0},
    {"CHAMFER", true, 0, NULL, &SC_CHAMFER, &P_CHAMFER, 0},
    {"SHELL", true, 0, NULL, &SC_SHELL, &P_SHELL, 0},
};
static const app_cmd_t MODIFY[] = {
    {"BOOLEAN", true, 0, NULL, &SC_BOOLEAN, NULL, 0},
    {"SPLIT", true, 0, NULL, &SC_SPLIT, NULL, 0},
    {"TRANSFORM", true, 0, NULL, &SC_TRANSFORM, &P_TRANSFORM, 0},
    {"PATTERN", true, 0, NULL, &SC_PATTERN, NULL, 0},
    {"MIRROR", true, 0, NULL, &SC_MIRROR, NULL, 0},
    {"MOVE FACE", true, 0, NULL, &SC_MOVE_FACE, &P_MOVE_FACE, 0},
};
// Single-letter sketch tools: only active while a sketch is open.
static const app_cmd_t SKETCH[] = {
    {"LINE", false, 0, "L", &SC_LINE, NULL, 0},
    {"RECTANGLE", false, 0, "G", &SC_RECT, NULL, 0},
    {"CIRCLE", false, 0, "C", &SC_CIRCLE, NULL, 0},
    {"ARC", false, 0, "A", &SC_ARC, NULL, 0},
    {"DIMENSION", false, 0, "D", &SC_DIMENSION, NULL, 0},
    {"TRIM", false, 0, "M", &SC_TRIM, NULL, 0},
    {"CONSTRUCTION", false, 0, "Q", &SC_CONSTRUCTION, NULL, 0},
};
static const app_cmd_t VIEW[] = {
    {"FRONT", false, SHIFT, "1", &SC_FRONT, NULL, 0},
    {"RIGHT", false, SHIFT, "4", &SC_RIGHT, NULL, 0},
    {"TOP", false, SHIFT, "5", &SC_TOP, NULL, 0},
    {"ISOMETRIC", false, SHIFT, "7", &SC_ISO, NULL, 0},
    {"NORMAL TO", false, 0, "N", &SC_NORMAL, NULL, 0},
    {"ZOOM TO FIT", false, 0, "F", &SC_FIT, NULL, 0},
    {"SECTION", false, SHIFT, "X", &SC_SECTION, NULL, 0},
};
// Button 1 steps MODEL <-> MODIFY, 2 SKETCH, 4 VIEW (while 3 holds the wheel open).
static const app_ring_t RINGS[] = {
    {"MODEL", "MODEL", 6, MODEL, 1},
    {"MODIFY", "MODIFY", 6, MODIFY, 1},
    {"SKETCH", "SKETCH", 7, SKETCH, 2},
    {"VIEW", "VIEW", 7, VIEW, 4},
};

const cc_app_profile_t cc_app_profile_onshape = {
    "onshape", "ONSHAPE", cc_app_icon_onshape_24, cc_app_icon_onshape_48,
    {"TILT", "ORBIT", "WHEEL", "PAN"},
    // The icon is only green + white, too few colours to sample: teal -> Onshape green -> lime.
    {0x0F9D8A, 0x64BC4F, 0xB5E35A},
    APP_MOD_ALT, "C",   // tool search: Alt+C (Onshape help, Windows), type, Enter
    4, RINGS,
    // App profiles: the legacy slot model (has_slots false), Karl's Onshape shape (cube, thick, stepped).
    false, {{0, 0, 0, NULL}, {0, 0, 0, NULL}, {0, 0, 0, NULL}, {0, 0, 0, NULL}, {0, 0, 0, NULL}},
    APP_VISUAL_SHAPE, APP_SHAPE_CUBE, APP_STYLE_THICK, true,
    0, CC_APP_FEAT_SHAPE,
};

const cc_app_profile_t *cc_app_profile(uint8_t id) {
    return id == CC_APP_ID_ONSHAPE ? &cc_app_profile_onshape : NULL;
}
