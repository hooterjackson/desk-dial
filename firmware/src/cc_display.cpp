#include "cc_display.h"
#include "cc_crumbs.h"
#include "cc_icons.h"
#include "cc_icon_morph.h"
#include "fonts/cc_fonts.h"
#include <stdio.h>
#include <string.h>

#ifndef CC_TEXT_TWINS
#define CC_TEXT_TWINS 1
#endif
#ifndef CC_DISPLAY_FULL_LAYERS
#define CC_DISPLAY_FULL_LAYERS 0
#endif

// cc5.4 LCD renderer: presentation 5 (PRESENTATION_V5.md section 8; r2.1 S01 section 3 and App A,
// the Browse and Snap knob markup BS:279-335 and renderVals BS:1232-1297; [r2.2] tone `liked`).
//
// Tree (created once, never rebuilt; section 8.2):
//   screen (black)
//   `- stage            no animation (V4's stage fade is gone, RF3 R2b)
//      |- art           240 px cover; never translates; fades only on show/hide (240 ms)
//      |- content       translate_x +-20 and opacity of a screen change; bounded y 28..163
//      |  |- heading (+twin)
//      |  |- home       track{title, artist} volume{caption, digits, percent} status idle[4]
//      |  |- list       recent, explorer, upnext, notice: title, sub, meta
//      |  |- tracks     title, prev/dotfill/next, sub, meta
//      |  |- seek       caption, 48 px tabular time, 14 px line
//      |  |- windows    tile{letter, 32 px app icon}, app, title, meta
//      |  |- scenes     [presentation 6] prev, title, next, meta (the Lights scenes list, section 19.4)
//      |  `- offline    title, sub (firmware-local "Waiting for PC", section 8.10)
//      |- crumb[2]      [presentation 6] the arc breadcrumb (ancestors, current): A8 masks from flash, recoloured;
//      |                never slides, fades 200 ms (section 19.9; replaces the flat heading when sent)
//      `- footer[4]     20 px icons; never slides or fades on a screen change
//         `- hold tick  [r3.1] 16 x 2 px #A6A6A6 bar under the button-4 icon when the frame sends holdMarker
//
// Every animated layer is bounded to its content box (section 8.2 R2); the harness compiles the
// same unit with CC_DISPLAY_FULL_LAYERS=1 and proves identical pixels (`v5_bounded`). Twelve labels
// carry a text-shadow twin (section 8.5.3): a black copy at text_opa 204, one pixel lower, created
// first so it draws below its label. Motion is translate and opacity only (no transforms, no
// opa_layered: the LVGL heap is 64 KB). SPR overshoot drives translate only; opacity uses the
// OUT/IN curves and is clamped to 0..255.
//
// Presentation 6 (section 19.4, Desk Dial r3 release 1): `lights` and `lightsbig` are drawn by the home layer
// (title / sub-line / 12 px line, and the reveal's caption + 48 px digits + unit), so a lights <-> lightsbig
// change is the Home reveal; their 12 px line is `meta` (metaTone), never `status`. `scenes` has its own layer.
// Both are their own display groups (Lights depth 1, Scenes depth 2) and draw no art.
//
// Artwork (ARTWORK2.md section 7; section 8.4): the art image shows the front of two 240 px
// buffers; a new key is decoded (JPEG) or upscaled (v1) into the back buffer and the two swap
// (instant over a visible cover; 240 ms fades only on show/hide). With the R5 hooks
// (CCDisplayMedia::requestCover/pollCover/cancelCover, section 12.5) the decode runs in another
// task: the render posts it and keeps the previous cover until a later render consumes the result.
//
// r4 motion (design_handoff_nano_d_r4 README section 3; MOTION.md): the springs SPRING.snap / soft / pop / wall
// are baked step responses (kSpringLut, make_motion.py) used as LVGL anim paths for fire-and-forget moments, and a
// small semi-implicit Euler stepper (Glide, 4 ms substeps) drives what follows the knob: the list glide (M4), the
// track change (M5) and the wall stretch (M13). A new detent or wall retargets the running motion; nothing queues.
// Moments: M1 push (content from 28 px, SPRING.snap, fade 240 ms OUT; the 97 % scale is not drawn: an LVGL
// transform renders the content through an ARGB8888 layer of its whole box), M2 / M3 the big value in / out, M4,
// M5, M6 the status / meta line (10 px, SPRING.soft), M7 the footer press squash and M8 the landing pop (live
// lv_image scale on the 20 px icon: the image widget transforms only its own 20 x 20 draw), M9 the Play <-> Pause
// morph (cc_icon_morph.cpp, 12 A8 frames), M10 the hold-4 fill (the icon's own mask, recoloured warm, in a clip box
// that grows bottom-up), M11 the idle row entrance, M13 the wall stretch (cc_display_wall), M15 the crumb crossfade.
// Reduced motion: every moment is a 160 ms opacity crossfade (no translate, scale or morph).
//
// Render speed (r4 section 9, "30 fps during M1, M4 and M13 with artwork"; harness/perf.py): LVGL 9.0.0
// renders `opa` by multiplication, never through a layer (only transforms, opa_layered, blend modes and clip_corner
// with children allocate one: perf.cpp counts 0), so the container fades stay. Two costs are cut here: A8 masks
// (crumbs, icons, morph frames) are drawn straight from flash by a decoder of their own (LVGL's bin decoder
// lv_malloc'ed and copied the whole mask on every draw of every chunk), and the text-shadow twins are hidden while
// no cover can be under them (a black shadow over black draws nothing; pixel-identical, a quarter of the text work
// of an art-less screen).

namespace {

// ---------------------------------------------------------------- geometry --
constexpr int32_t SAFE_R = 104;          // optical safe circle around (120,120)
constexpr int32_t HEADING_R = 112;       // headings may reach r112 (section 8.3; the bezel hides r112..120)
constexpr int32_t CENTER = 120;

struct Box { int16_t x, y, w, h; };
// Label boxes, absolute {x, y = LVGL label top, w, h} (section 8.5.1). y puts the baseline on the
// design's CSS baseline: y = round(CSS top + CSS baseline offset) - ascent.
constexpr Box HEADING = {51, 31, 138, CC_FONT_12_LINE_HEIGHT};
constexpr Box HOME_TITLE = {35, 61, 170, 2 * CC_FONT_22_LINE_HEIGHT + 2};
constexpr Box HOME_ARTIST = {35, 115, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box STATUS = {30, 133, 180, CC_FONT_12_LINE_HEIGHT};   // r3 (README 2, L-6): x 30 w 180
constexpr Box VOL_CAPTION = {35, 53, 170, CC_FONT_14_LINE_HEIGHT};
constexpr int16_t DIGITS_Y = 73;         // 48 px digits: baseline 116
constexpr int16_t PERCENT_Y = 96;        // 22 px '%': baseline 116
// r4 README 3.6: number right-aligned, a 4 px gap, unit left-aligned around the computed centre (never overlap).
constexpr int16_t DIGIT_GAP = 4;
// r4 README 3.6 row widths (clear of the crumb's ends): the scenes rows and the meta lines below. A list title
// keeps 170: its first line (rows 53..77) takes the r104 chord, <= 160 px, and also the crumb's clearance
// (FW-DES-001: the long crumbs, MUSIC > RECENTLY ADDED and ON SCREEN > RECENT, reach down to row 67 at their
// ends; crumbClearHalf), and its second lies below the crumb's ends.
constexpr Box LIST_TITLE = {35, 53, 170, 2 * CC_FONT_22_LINE_HEIGHT + 2};
constexpr Box LIST_SUB = {35, 107, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box LIST_META = {35, 126, 170, CC_FONT_12_LINE_HEIGHT};
constexpr Box TRACKS_TITLE = {35, 55, 170, CC_FONT_22_LINE_HEIGHT};   // one line: the r104 chord (r4 3.6)
constexpr Box TRACKS_SUB = {35, 111, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box TRACKS_META = {32, 129, 176, CC_FONT_12_LINE_HEIGHT};   // r3 x 30 w 180 (L-6); r4 3.6 meta <= 176
constexpr int16_t TRACKS_POS_X[3] = {72, 112, 152};
constexpr int16_t TRACKS_POS_Y = 88;
constexpr Box SEEK_CAPTION = {35, 53, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box SEEK_TIME = {0, 73, 240, CC_FONT_48T_LINE_HEIGHT};
constexpr Box SEEK_LINE = {25, 129, 190, CC_FONT_14_LINE_HEIGHT};   // r3: "of {dur} · 3 sets · 1 cancels" (README 2.2)
constexpr Box TILE = {104, 42, 32, 32};
// 16 px initial on the tile's CSS 16/16 line, centred in the 32 px tile: line top 42 + 8 = 50,
// baseline 50 + 13.74 = 64 (label top 42 + 7, ascent 15).
constexpr int16_t TILE_LETTER_Y = 7;
constexpr Box WIN_APP = {35, 81, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box WIN_TITLE = {35, 99, 170, 2 * CC_FONT_16_LINE_HEIGHT + 2};
constexpr Box WIN_META = {35, 139, 170, CC_FONT_12_LINE_HEIGHT};
// Presentation 6 scenes list (README r3 section 2.2): prev 14 px #7C7C7C CSS top 56, current 22 px top 78
// (x 30..210), next 14 px top 108, meta 12 px top 134 (x 30..210) -> LVGL tops +1 / +1 / +1 / -1.
// r4 README 3.6: previous <= 104, current <= 160, next <= 150, meta <= 176 (centred).
constexpr Box SCENE_PREV = {68, 57, 104, CC_FONT_14_LINE_HEIGHT};
constexpr Box SCENE_TITLE = {40, 79, 160, CC_FONT_22_LINE_HEIGHT};
constexpr Box SCENE_NEXT = {45, 109, 150, CC_FONT_14_LINE_HEIGHT};
constexpr Box SCENE_META = {32, 133, 176, CC_FONT_12_LINE_HEIGHT};
constexpr Box OFF_TITLE = {35, 71, 170, CC_FONT_22_LINE_HEIGHT};
constexpr Box OFF_SUB = {35, 105, 170, 2 * CC_FONT_14_LINE_HEIGHT + 2};
constexpr int16_t FOOTER_CX[4] = {56, 99, 141, 184};
constexpr int16_t FOOTER_Y = 154;
constexpr int16_t FOOTER_ICON = 20;
// [r3.1] (section 19.10; r3.1 prototype L349): the hold tick, 16 x 2 px, radius 1, #A6A6A6, at (176, 180), centred
// under the button-4 footer icon (x 184); fades 200 ms.
constexpr Box HOLD_TICK = {176, 180, 16, 2};
constexpr uint32_t HOLD_TICK_FADE_MS = 200;
constexpr int16_t IDLE_CX[4] = {51, 97, 143, 189};
constexpr int16_t IDLE_Y = 100;
constexpr int16_t IDLE_ICON = 26;
constexpr int16_t IDLE_COLUMN_W = 60;
constexpr int16_t IDLE_WORD_DY = 33;     // words at y 133 (CSS top 134, 12/14)
constexpr int16_t POS_ICON = 16;
constexpr int16_t LINE_SPACE = 2;        // two-line labels: 22/26, 16/20 and 14/18 pitches
constexpr int8_t HEADING_TRACKING = 1;   // 0.04 em is not representable: 1 px (P5-1)
constexpr int8_t DIGITS_TRACKING = -1;   // letter-spacing -0.02em at 48 px (volume and Seek)
constexpr uint8_t TILE_CLOSED_OPA = 89;  // 0.35
// r4 M1: the content enters from 28 px in the depth direction (deeper = from the right).
constexpr int32_t SLIDE_PX = 28;
constexpr uint8_t TWIN_OPA = 204;        // text shadow 0 1px 0 at 80 % (section 8.5.3)

// Layer boxes (absolute). Bounded (section 8.2 R2): each animated layer covers only what it draws
// at every point of its motion. content: the heading row (y 31) to the idle row's +16 px start
// (148 + 16 = 164, r4 M11). home: the content box (it holds the translating track/volume/idle layers).
// r4 M6: a meta line rises 10 px into place inside its layer, so each list-like layer reaches 10 px below its meta.
#if CC_DISPLAY_FULL_LAYERS
constexpr Box FULL = {0, 0, 240, 240};
constexpr Box CONTENT_BOX = FULL, TRACK_BOX = FULL, VOLUME_BOX = FULL, LIST_BOX = FULL, TRACKS_BOX = FULL,
              SEEK_BOX = FULL, WINDOWS_BOX = FULL, OFFLINE_BOX = FULL, FOOTER_BOX = FULL, HOME_BOX = FULL,
              SCENES_BOX = FULL;
#else
constexpr Box CONTENT_BOX = {0, 28, 240, 137};   // r4 M11: the idle row enters from +16 px (148 + 16 = 164)
constexpr Box HOME_BOX = CONTENT_BOX;
constexpr Box TRACK_BOX = {35, 61, 170, 71};     // title, artist and their twins: rows 61..131
constexpr Box VOLUME_BOX = {0, 53, 240, 74};     // caption, digits, percent and twins: rows 53..126
constexpr Box LIST_BOX = {35, 53, 170, 98};      // rows 53..150 (meta 126..140, + 10 px M6)
constexpr Box TRACKS_BOX = {30, 55, 180, 99};    // rows 55..153 (meta + 10 px M6); x 30..209 (r3 meta, L-6)
constexpr Box SEEK_BOX = {0, 53, 240, 92};       // rows 53..144
constexpr Box WINDOWS_BOX = {35, 42, 170, 123};  // rows 42..164 (meta 140..153, + 10 px M6)
constexpr Box OFFLINE_BOX = {35, 71, 170, 68};   // rows 71..138
constexpr Box SCENES_BOX = {32, 57, 176, 101};   // rows 57..157 (prev 57, title 79 + twin, next 109, meta 133 + 10 px
                                                 // M6); x 32..207
constexpr Box FOOTER_BOX = {42, 150, 156, 32};   // icons x 46..193, rows 154..173 (r4 M8 pop 1.28x: 43..197,
                                                 // 151..177); [r3.1] hold tick rows 180..181
#endif

// Firmware-local copy (section 8.10; VOC knob.title.offline, knob.sub.offline(_native)).
const char OFFLINE_TITLE[] = "Waiting for PC";
// Desk Dial (the rename, rename-desk-dial.md C1): "Desk Dial" is held together by a no-break space
// (U+00A0, UTF-8 C2 A0; cc_font_14 draws it 4 px wide, like a space). fitTwoLines breaks only at
// ASCII spaces, so the two balanced lines are "Open Desk Dial" / "on your PC", never "Open Desk" /
// "Dial on your PC" (5.2, 11.5). The literal is split because "\xA0Dial" would read \xA0D as one
// hex escape.
const char OFFLINE_SUB[] = "Open Desk\xC2\xA0" "Dial on your PC";
const char OFFLINE_NATIVE[] = "Knob controls still work";
// K1 8.10 erratum (lead ruling R-c): the native sub-line is one line, and with the knob font it is
// 171 px (LVGL sums whole-pixel kerned advances; 167.5 px in the design's metrics) against the
// 170 px line. Rather than wrap it or change the approved words, it is drawn at -1 px tracking
// (148 px) whenever it does not fit at 0; the two-line "Open Desk Dial on your PC" keeps 0.
constexpr int8_t OFFLINE_NATIVE_TRACKING = -1;

// ------------------------------------------------------------------ motion --
// Curves (r4 README 3.1): the cubic-bezier fades E.out / E.in / E.io, the v5 SPR (kept for nothing new), linear,
// and the four springs (a baked step response over the spring's settle time; overshoot included).
enum Ease : uint8_t {
    EASE_OUT, EASE_IN, EASE_SPR, EASE_IO, EASE_LINEAR,
    SPRING_SNAP, SPRING_SOFT, SPRING_POP, SPRING_WALL
};
struct Curve { int16_t x1, y1, x2, y2; };
constexpr Curve CURVES[4] = {
    {static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.22)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0)),
     static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.36)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0))},
    {static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.4)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.0)),
     static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0))},
    {static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.34)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.45)),
     static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.64)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0))},
    {static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.65)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.0)),
     static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.35)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0))},
};
struct SpringLut {
    uint16_t settleMs;
    int16_t y[41];
};
// Generated by harness/make_motion.py (r4 README 3.1 springs, the r3.1 prototype's cssSpring()):
// {settle ms, 41 samples of the step response x 4096 over the settle time}. Order: snap, soft, pop, wall.
constexpr SpringLut kSpringLut[4] = {
    // snap: response 0.36 s, damping 0.72; k 304.6, c 25.1; overshoot 3.8%
    {416, {0, 62, 226, 464, 753, 1072, 1405, 1739, 2064, 2374, 2662, 2925, 3161, 3371, 3553, 3708, 3840, 3948, 4036, 4105, 4158, 4197, 4225, 4242, 4251, 4253, 4251, 4244, 4235, 4224, 4211, 4199, 4186, 4173, 4161, 4150, 4140, 4131, 4123, 4116, 4096}},
    // soft: response 0.46 s, damping 0.82; k 186.6, c 22.4; overshoot 1.1%
    {544, {0, 64, 230, 468, 751, 1059, 1376, 1690, 1993, 2279, 2544, 2785, 3002, 3194, 3363, 3509, 3634, 3740, 3829, 3902, 3962, 4010, 4048, 4077, 4100, 4116, 4127, 4135, 4139, 4141, 4141, 4140, 4138, 4135, 4132, 4128, 4125, 4121, 4118, 4115, 4096}},
    // pop: response 0.42 s, damping 0.52; k 223.8, c 15.6; overshoot 14.7%
    {624, {0, 103, 375, 768, 1237, 1742, 2252, 2740, 3189, 3584, 3919, 4191, 4399, 4548, 4643, 4691, 4700, 4678, 4633, 4572, 4501, 4426, 4351, 4280, 4215, 4159, 4112, 4074, 4045, 4025, 4013, 4007, 4007, 4011, 4019, 4028, 4039, 4050, 4061, 4071, 4096}},
    // wall: response 0.34 s, damping 0.42; k 341.5, c 15.5; overshoot 23.2%
    {648, {0, 168, 607, 1224, 1929, 2647, 3320, 3905, 4374, 4717, 4935, 5039, 5045, 4975, 4852, 4697, 4529, 4364, 4215, 4089, 3992, 3925, 3886, 3873, 3879, 3902, 3935, 3973, 4012, 4049, 4082, 4108, 4128, 4141, 4147, 4148, 4145, 4138, 4130, 4121, 4096}},
};
constexpr int32_t SPRING_ONE = 4096;
// Spring constants for the stepper (k = (2 pi / response)^2, c = 4 pi damping / response; mass 1).
struct SpringKc { float k, c; };
constexpr SpringKc kSpringKc[4] = {{304.6f, 25.13f}, {186.6f, 22.40f}, {223.8f, 15.62f}, {341.5f, 15.52f}};
uint32_t springMs(uint8_t ease) { return kSpringLut[ease - SPRING_SNAP].settleMs; }

// Section 8.8 durations (VOC-K1d) not already named above, and the r4 ones (README 3.2).
constexpr uint32_t ART_FADE_MS = 240;
constexpr uint32_t INK_FADE_MS = 160;
constexpr uint32_t LINE_FADE_MS = 160;
constexpr uint32_t CONTENT_FADE_MS = 240;       // r4 M1: opacity 0 -> 1 in 240 ms E.out (v5: 220)
constexpr uint32_t REDUCED_FADE_MS = 160;       // r4 section 7: every animation a 160 ms opacity crossfade
constexpr uint32_t OFFLINE_FADE_MS = 220;       // section 8.10 (unchanged by r4)
constexpr int32_t GLIDE_PX = 14;                // M4 / M5: rows jump 14 px in the turn direction, spring back
constexpr int32_t STATUS_RISE_PX = 10;          // M6
constexpr int32_t WALL_PX = 9;                  // M13
constexpr uint32_t WALL_PUSH_MS = 90;           // M13: 9 px in 90 ms E.out, then SPRING.wall back
constexpr uint32_t PRESS_MS = 70;               // M7: squash in 70 ms E.in
constexpr int32_t PRESS_SCALE_X = 205, PRESS_SCALE_Y = 220;   // M7: scale(0.8, 0.86) of 256
constexpr int32_t PRESS_DROP_PX = 2;
constexpr int32_t POP_SCALE = 328;              // M8: 1.28 x 256
constexpr uint32_t MORPH_MS = 300;              // M9: E.out 300 ms; colour 220 ms, 120 ms later
constexpr uint32_t MORPH_INK_DELAY_MS = 120, MORPH_INK_MS = 220;
constexpr uint32_t HOLD_FILL_MS = 1000;         // M10: linear 1000 ms, early release drains 180 ms E.in
constexpr uint32_t HOLD_DRAIN_MS = 180;
constexpr uint32_t HOLD_LANDING_WINDOW_MS = 1500;   // a landing (new feedback) within 1.5 s of the maturity pops
constexpr uint32_t HOLD_DIM_INK = 0x6A6A6A;     // M10: the base icon while the fill runs
constexpr uint32_t HOLD_FILL_INK = 0xFFBE69;
constexpr int32_t IDLE_RISE_PX = 16;            // M11: from 16 px below at 85 % scale, 40 ms stagger from 140 ms
constexpr int32_t IDLE_SCALE = 218;

// Wire icon tokens by CCIcon value (section 9.1; append-only, VOC section 1.2).
const char* const ICON_NAMES[] = {"", "play", "pause", "list", "win", "tracks", "back", "home", "more",
                                  "prev", "next", "switch", "cancel", "expand", "clock", "playlists",
                                  "playnext", "seek", "shuffle", "heart", "snapleft", "snapright",
                                  // Presentation 6 (22..27, section 19.5).
                                  "bulb", "thermo", "power", "wand", "house", "album"};
constexpr uint8_t ICON_COUNT = sizeof(ICON_NAMES) / sizeof(ICON_NAMES[0]);
// Internal masks: the Tracks position-row centre and, [r2.2], the liked heart (tone liked).
const char DOT_GLYPH[] = "dotfill";
const char LIKED_GLYPH[] = "heartfill";

// Display groups (section 8.7; VOC section 1.2 plus VOC-K1b offline).
enum Group : uint8_t {
    GROUP_HOME, GROUP_RECENT, GROUP_TRACKS, GROUP_WINDOWS, GROUP_EXPLORER, GROUP_UPNEXT, GROUP_OFFLINE,
    GROUP_LIGHTS, GROUP_SCENES             // presentation 6 (section 19.4)
};

// ------------------------------------------------------------------- state --
constexpr size_t SRC_CAP = 100;          // wire text <= 96 bytes + NUL
constexpr size_t TEXT_CAP = 112;         // fitted: line1 '\n' line2 U+2026 NUL

struct Layer {
    lv_obj_t* obj;
    int16_t x, y;                        // absolute origin
};

struct Label {
    lv_obj_t* obj;
    lv_obj_t* twin;                      // text-shadow twin, or nullptr
    const lv_font_t* font;
    int16_t x, y, w;                     // absolute rest box (safe-circle fitting)
    int16_t centerX;                     // absolute horizontal centre of the text
    int16_t radius;                      // fitting radius: 104, or 112 for the heading
    int8_t tracking;                     // letter space applied
    uint8_t lines;                       // 1 or 2
    bool inkSet;
    uint32_t ink;                        // target ink
    uint32_t shownInk;                   // ink on screen (differs during an ink crossfade)
    uint32_t fadeFrom;
    char src[SRC_CAP];                   // source text of the current fit
    bool crumbClear;                     // FW-DES-001: line 1 also clears the crumb's ink (list title)
    uint8_t fitCrumb;                    // the crumb the current fit cleared (crumbClear only)
};

struct Icon {
    lv_obj_t* obj;
    const lv_image_dsc_t* src;           // glyph shown, nullptr = hidden
    int16_t size;
    bool inkSet;
    uint32_t ink, shownInk, fadeFrom;
};

enum Prop : uint8_t { PROP_OPA, PROP_TX, PROP_TY, PROP_SCALE_X, PROP_SCALE_Y, PROP_HEIGHT, PROP_SCALE };
struct Tween {
    lv_obj_t* obj;
    uint8_t prop;
    bool set;
    int32_t target;
};

struct View {
    bool rendered;
    uint8_t group, page, layout;
    uint8_t crumb;                       // presentation 6: the frame's crumb (part of the screen identity)
    bool homeish;                        // the home layer was shown (Home, or presentation 6 lights/lightsbig)
    bool row;                            // the idle row was shown (idle base, no volume reveal)
    bool footerShown;                    // footer target 255
    // r4 detent detection (M4 / M5 / M8): the previous frame's selected entry, song and playing state.
    uint8_t ringStyle;
    uint16_t ringIndex;
    int8_t playing;
    bool holdMarker;
    uint32_t feedbackSeq;
};

lv_obj_t* screen = nullptr;
lv_obj_t* stage = nullptr;
lv_obj_t* art = nullptr;
Layer content, homeLayer, trackLayer, volumeLayer, listLayer, tracksLayer, seekLayer, windowsLayer,
    offlineLayer, footerLayer, scenesLayer;
lv_obj_t* idleColumn[4] = {};
lv_obj_t* tile = nullptr;

Label heading, homeTitle, homeArtist, status, volumeCaption, digits, percent;
Label idleWord[4];
Label listTitle, listSub, listMeta;
Label tracksTitle, tracksSub, tracksMeta;
Label seekCaption, seekTime, seekLine;
Label tileLetter, winApp, winTitle, winMeta;
Label offTitle, offSub;
Label scenePrev, sceneTitle, sceneNext, sceneMeta;     // presentation 6
Icon idleIcon[4], footerIcon[4], positionIcon[3];

Tween trackOpa, trackTy, volumeOpa, volumeTy, statusOpa, footerOpa, artOpa, contentTx, contentOpa;
lv_obj_t* holdTick = nullptr;            // [r3.1] the hold tick (footer layer)
Tween holdTickOpa;
Tween idleOpa[4], idleTy[4];
// Presentation 6 arc breadcrumb (section 19.9): [slot * 2 + 0] ancestors #7C7C7C, [slot * 2 + 1] current #E6E6E6.
// r4 M15: two slots, so a new crumb crossfades with the one it replaces (crumbSlot holds the newest).
lv_obj_t* crumbImg[4] = {nullptr, nullptr, nullptr, nullptr};
lv_image_dsc_t crumbDsc[4];
Tween crumbOpa[4];
uint8_t crumbSlot = 0;
uint8_t crumbShown = CC_CRUMB_NONE;      // the crumb whose masks the images hold (NONE: faded out / hidden)
Tween listMetaOpa, tracksMetaOpa, winMetaOpa, offSubOpa, sceneMetaOpa;
// r4 M6: the status / meta lines rise 10 px into place (SPRING.soft) when their text changes at rest.
Tween statusTy, listMetaTy, tracksMetaTy, winMetaTy, sceneMetaTy;
bool statusLeaving = false;              // M6: the status line fades out with its old text
// r4 M11: the idle icons' own scale (85 % -> 100 %, SPRING.pop).
Tween idleScale[4];

// r4 footer icon motion (M7 press squash, M8 landing pop, M9 morph, M10 hold fill), per physical slot.
struct FooterMotion {
    Tween sx, sy, ty, opa;               // M7 squash (x / y), drop, reduced-motion dim
    Tween scale;                         // M8 pop (uniform)
    bool down;                           // the slot's button is down (cc_display_input)
    uint32_t downAt;
};
FooterMotion footerMotion[4];
uint8_t keysDown = 0;                    // cc_display_input(): the physical buttons down now
// M10: the warm copy of the button-4 icon in a bottom-anchored clip box that grows over the 1 s hold.
lv_obj_t* holdClip = nullptr;
lv_obj_t* holdFill = nullptr;
Tween holdH, holdOpa;                    // the fill's height (full motion) / opacity (reduced motion)
bool holdFilling = false;                // the fill runs (slot 3 down on a holdMarker screen)
bool holdMatured = false;                // the fill completed (1000 ms); a landing within the window pops
uint32_t holdMaturedAt = 0;
// M9: the morph in flight (slot, direction); frames come from cc_icon_morph().
struct Morph { int8_t slot; bool toPlay; uint32_t startedAt; };
Morph morph = {-1, false, 0};

// r4 stepper (M4 list glide, M5 track change, M13 wall stretch): one translate per slot, semi-implicit Euler at
// 4 ms steps on the knob's clock, retargeted by each new detent / wall (never queued).
enum GlideSlot : uint8_t { GLIDE_CONTENT, GLIDE_TRACK, GLIDE_LIST, GLIDE_TRACKS, GLIDE_SCENES, GLIDE_WINDOWS, GLIDE_COUNT };
struct Glide {
    lv_obj_t* obj;
    uint8_t prop;                        // PROP_TX / PROP_TY
    bool active;
    uint8_t spring;                      // SPRING_*
    float x, v, target;                  // px, px / s
    int32_t shown;                       // the value last applied
    bool leg;                            // M13: a lead-in leg (E.out) before the spring takes over
    uint32_t legAt, legMs;
    float legFrom, legTo;
};
Glide glides[GLIDE_COUNT];
int glideClockVar = 0;                   // the var of the one stepper anim
uint32_t glideLastMs = 0;
uint32_t glideAccMs = 0;

// Text-shadow twins drawn only while a cover can be under them (render speed; pixel-identical over black).
bool twinsOn = true;
// A8 masks drawn from flash (render speed): the decoder of cc_display_create().
lv_image_decoder_t* a8Decoder = nullptr;

View view = {};
CCDisplayStats stats = {};
bool changed = false;                    // this render changed something
bool animated = false;                   // this render started an animation
int32_t digitsWidth = -1, percentWidth = -1;
uint8_t tileOpa = 255;
uint32_t tileBg = CCInk::tile;
bool reducedMotion = false;              // latched (section 7.1): reset by release/offline (claims)

// Offline layer (section 8.10).
bool offline = false;
bool offlineNative = false;
bool offlinePinsHeld = false;
uint32_t offlineAt = 0;

// Caller-owned 240x240 RGB565 artwork buffers (PSRAM on the device). The art image shows
// artBuffer[artFront]; a new cover is written into the other one (when there are two) and they
// swap. artKeyOf[i] names the pixels of buffer i ("" while it holds none, or partly written ones,
// or while the R5 decoder owns it).
uint8_t* artBuffer[2] = {nullptr, nullptr};
lv_image_dsc_t artDsc[2];
char artKeyOf[2][sizeof(CCFrame::artKey)] = {};
uint8_t artFront = 0;
char artFailedKey[sizeof(CCFrame::artKey)] = {};   // decode failed: no art until the key changes
uint8_t artImageOpa = 255;

// R5 (section 12.5.2): the one decode in flight and whether this renderer cancelled it.
struct Decode {
    bool inFlight;
    bool cancelled;
    char key[sizeof(CCFrame::artKey)];
};
Decode decode = {};

// artwork2 app icon on the Windows tile: 32x32 RGB565 (the wire's little endian bytes are the
// native layout), static like the tile it belongs to.
alignas(4) uint8_t iconPixels[CC_ICON_BYTES];
lv_image_dsc_t iconDsc;
lv_obj_t* tileIcon = nullptr;
char iconLoadedKey[sizeof(CCFrame::iconKey)] = {};  // pixels in iconPixels
bool tileIconShown = false;

// artwork2 store lookups (cc_display_set_media) and whether this renderer holds the store's
// display pin of each kind (CCDisplayMediaKind).
CCDisplayMedia media = {};
bool mediaHeld[2] = {false, false};

char scratch[TEXT_CAP + 8];              // measuring buffer (LVGL runs on one thread)

// -------------------------------------------------------------- utilities --
void copyText(char* out, size_t cap, const char* text) {
    size_t n = strlen(text);
    if (n >= cap) n = cap - 1;
    memcpy(out, text, n);
    out[n] = '\0';
}

// Next code point of valid UTF-8 (the frame parser validated it); advances i.
uint32_t utf8Next(const char* s, size_t& i) {
    const uint8_t c = static_cast<uint8_t>(s[i]);
    size_t n = 1;
    uint32_t cp = c;
    if (c >= 0xF0) { n = 4; cp = c & 0x07u; }
    else if (c >= 0xE0) { n = 3; cp = c & 0x0Fu; }
    else if (c >= 0xC0) { n = 2; cp = c & 0x1Fu; }
    for (size_t k = 1; k < n; ++k) {
        const uint8_t next = static_cast<uint8_t>(s[i + k]);
        if ((next & 0xC0u) != 0x80u) { i += k; return 0xFFFD; }
        cp = (cp << 6) | (next & 0x3Fu);
    }
    i += n;
    return cp;
}

int32_t isqrt(int32_t v) {
    int32_t r = 0;
    while ((r + 1) * (r + 1) <= v) ++r;
    return r;
}

// Half-width of the radius-r circle's chord over pixel rows [top, bottom].
int32_t safeHalf(int32_t top, int32_t bottom, int32_t radius) {
    int32_t half = CENTER;
    for (int32_t y = top; y <= bottom; ++y) {
        const int32_t d = y < CENTER ? CENTER - y : y + 1 - CENTER;
        const int32_t h = d >= radius ? 0 : isqrt(radius * radius - d * d);
        if (h < half) half = h;
    }
    return half;
}

// FW-DES-001: half-width around `centerX` clear of the ink of `crumb` (both masks, alpha >= CRUMB_INK_ALPHA, plus
// CRUMB_GAP px) over pixel rows [top, bottom]; CENTER when the crumb has no ink on those rows. A centred line of
// width 2 * half then shares no pixel with the crumb.
constexpr uint8_t CRUMB_INK_ALPHA = 32;
constexpr int32_t CRUMB_GAP = 2;
int32_t crumbClearHalf(uint8_t crumb, int32_t centerX, int32_t top, int32_t bottom) {
    int32_t half = CENTER;
    for (uint8_t part = 0; part < 2; ++part) {
        const CCCrumbMask* mask = crumb == CC_CRUMB_NONE ? nullptr : cc_crumb_mask(crumb, part == 1);
        if (!mask || !mask->w || !mask->data) continue;
        const int32_t y0 = top > mask->y ? top : mask->y;
        const int32_t y1 = bottom < mask->y + mask->h - 1 ? bottom : mask->y + mask->h - 1;
        for (int32_t y = y0; y <= y1; ++y) {
            const uint8_t* row = mask->data + static_cast<size_t>(y - mask->y) * mask->w;
            for (int32_t x = 0; x < mask->w; ++x) {
                if (row[x] < CRUMB_INK_ALPHA) continue;
                const int32_t px = mask->x + x;
                const int32_t room = (px < centerX ? centerX - px - 1 : px - centerX) - CRUMB_GAP;
                if (room < half) half = room;
            }
        }
    }
    return half > 0 ? half : 0;
}

int32_t ascentOf(const lv_font_t* font) { return font->line_height - font->base_line; }

// Ink rows of a text relative to its line top (every glyph, fallback included).
void inkRows(const char* text, const lv_font_t* font, int32_t& top, int32_t& bottom) {
    const int32_t ascent = ascentOf(font);
    top = ascent;
    bottom = ascent - 1;
    for (size_t i = 0; text[i];) {
        const uint32_t letter = utf8Next(text, i);
        lv_font_glyph_dsc_t g;
        if (!lv_font_get_glyph_dsc(font, &g, letter, 0) || g.box_h == 0 || g.box_w == 0) continue;
        const int32_t glyphTop = ascent - g.box_h - g.ofs_y;
        const int32_t glyphBottom = ascent - g.ofs_y - 1;
        if (glyphTop < top) top = glyphTop;
        if (glyphBottom > bottom) bottom = glyphBottom;
    }
}

int32_t widthOf(const char* text, size_t length, const lv_font_t* font, int32_t tracking) {
    if (length >= sizeof(scratch)) length = sizeof(scratch) - 1;
    memcpy(scratch, text, length);
    scratch[length] = '\0';
    return lv_text_get_width(scratch, static_cast<uint32_t>(length), font, tracking);
}

int32_t widthOf(const char* text, const lv_font_t* font, int32_t tracking) {
    return widthOf(text, strlen(text), font, tracking);
}

const char ELLIPSIS[] = "\xE2\x80\xA6";  // U+2026, in every cc_font_<N>

size_t trimRight(const char* text, size_t length) {
    while (length && text[length - 1] == ' ') --length;
    return length;
}

// Width of text[0:length] (trailing spaces trimmed) followed by an ellipsis.
int32_t ellipsizedWidth(const char* text, size_t length, const lv_font_t* font, int32_t tracking) {
    char buffer[TEXT_CAP];
    length = trimRight(text, length);
    if (length > TEXT_CAP - sizeof(ELLIPSIS)) length = TEXT_CAP - sizeof(ELLIPSIS);
    memcpy(buffer, text, length);
    memcpy(buffer + length, ELLIPSIS, sizeof(ELLIPSIS));
    return widthOf(buffer, length + sizeof(ELLIPSIS) - 1, font, tracking);
}

// Appends text (<= maxWidth) to out: whole, or cut at a code point with U+2026 (CSS
// text-overflow: ellipsis). forceEllipsis marks a clamped line whose remainder was dropped: the
// U+2026 is appended even when the text fits.
void appendLine(char* out, size_t cap, const char* text, const lv_font_t* font, int32_t tracking,
                int32_t maxWidth, bool forceEllipsis = false) {
    const size_t used = strlen(out);
    const size_t length = strlen(text);
    if (!forceEllipsis && widthOf(text, length, font, tracking) <= maxWidth) {
        copyText(out + used, cap - used, text);
        return;
    }
    // bounds[k]: byte offset where code point k starts; a prefix of k code points ends at
    // bounds[k] (or at length when k == count). Static: LVGL runs on one thread and this keeps
    // the LCD task stack free.
    static size_t bounds[TEXT_CAP];
    size_t count = 0;
    for (size_t i = 0; text[i] && count < TEXT_CAP;) { bounds[count++] = i; utf8Next(text, i); }
    // Largest kept prefix (in code points) whose ellipsized width fits.
    size_t lo = 0, hi = count, keep = 0;
    while (lo < hi) {
        const size_t mid = (lo + hi + 1) / 2;
        const size_t prefix = mid < count ? bounds[mid] : length;
        if (ellipsizedWidth(text, prefix, font, tracking) <= maxWidth) {
            keep = mid;
            lo = mid;
        } else {
            hi = mid - 1;
        }
    }
    size_t cut = trimRight(text, keep < count ? bounds[keep] : length);
    if (used + sizeof(ELLIPSIS) > cap) return;
    if (used + cut + sizeof(ELLIPSIS) > cap) cut = cap - used - sizeof(ELLIPSIS);
    memcpy(out + used, text, cut);
    memcpy(out + used + cut, ELLIPSIS, sizeof(ELLIPSIS));
}

// Longest code-point prefix of text that fits maxWidth (no ellipsis).
size_t fittingPrefix(const char* text, const lv_font_t* font, int32_t tracking, int32_t maxWidth) {
    size_t end = 0;
    for (size_t i = 0; text[i];) {
        size_t next = i;
        utf8Next(text, next);
        if (widthOf(text, next, font, tracking) > maxWidth) break;
        end = i = next;
    }
    return end;
}

// The last line of a paragraph: the whole text when it fits; otherwise it is clamped
// (-webkit-line-clamp) to the whole words that fit together with U+2026, and characters are cut
// only when no whole word fits.
void appendLastLine(char* out, size_t cap, const char* text, const lv_font_t* font, int32_t tracking,
                    int32_t maxWidth) {
    if (widthOf(text, font, tracking) <= maxWidth) {
        appendLine(out, cap, text, font, tracking, maxWidth);
        return;
    }
    size_t words = 0;
    for (size_t i = 1; text[i]; ++i) {
        if (text[i] != ' ') continue;
        const size_t end = trimRight(text, i);
        if (end == 0) continue;
        if (ellipsizedWidth(text, end, font, tracking) > maxWidth) break;
        words = end;
    }
    if (words == 0) {
        appendLine(out, cap, text, font, tracking, maxWidth, true);
        return;
    }
    char kept[TEXT_CAP];
    memcpy(kept, text, words);
    kept[words] = '\0';
    appendLine(out, cap, kept, font, tracking, maxWidth, true);
}

// Preferred break points inside an over-wide word: after a separator of file names and paths
// ("CLAUDE_CODE_" / "HANDOFF.md", "cc5-stage6-" / "lcd-...").
bool isWordSeparator(char c) { return c == '-' || c == '_' || c == '/' || c == '\\' || c == '.'; }

// Balanced two-line split (line 1 = text[0:end1], line 2 = text[start2:]).
struct Split {
    size_t end1, start2;
    int32_t score;                          // the wider line; lower is better
    bool found;
};

void consider(Split& best, size_t end1, size_t start2, int32_t w1, int32_t w2) {
    const int32_t score = w1 > w2 ? w1 : w2;
    if (!best.found || score <= best.score) {   // ties keep the longer first line
        best.end1 = end1;
        best.start2 = start2;
        best.score = score;
        best.found = true;
    }
}

// Two lines, CSS "text-wrap: balance" + line-clamp 2. U+2026 appears only when the whole text
// cannot be shown in the two lines:
// 1. a split at a space where both lines fit, minimising the wider line;
// 2. otherwise a split inside a word wider than a line (overflow-wrap), again balanced,
//    preferring a break after - _ / \ . over any code point;
// 3. otherwise the text does not fit: a full first line (the words that fit, or the first word
//    cut by characters) and a clamped second line.
void fitTwoLines(char* out, size_t cap, const char* text, const lv_font_t* font, int32_t tracking,
                 int32_t width1, int32_t width2) {
    out[0] = '\0';
    const size_t length = strlen(text);
    if (widthOf(text, length, font, tracking) <= width1) { copyText(out, cap, text); return; }
    Split best = {0, 0, 0, false};
    size_t greedyEnd1 = 0, greedyStart2 = 0;
    for (size_t i = 1; i < length; ++i) {
        if (text[i] != ' ') continue;
        const size_t end1 = trimRight(text, i);
        size_t start2 = i;
        while (text[start2] == ' ') ++start2;
        if (end1 == 0 || text[start2] == '\0') continue;
        const int32_t w1 = widthOf(text, end1, font, tracking);
        if (w1 > width1) break;                      // later splits only widen line 1
        greedyEnd1 = end1;
        greedyStart2 = start2;
        const int32_t w2 = widthOf(text + start2, length - start2, font, tracking);
        if (w2 <= width2) consider(best, end1, start2, w1, w2);
    }
    if (!best.found) {
        const int32_t narrow = width1 < width2 ? width1 : width2;
        Split separated = {0, 0, 0, false};
        bool stop = false;
        for (size_t start = 0; start < length && !stop;) {
            while (start < length && text[start] == ' ') ++start;
            size_t end = start;
            while (end < length && text[end] != ' ') ++end;
            if (end > start && widthOf(text + start, end - start, font, tracking) > narrow) {
                size_t p = start;
                utf8Next(text, p);
                while (p < end) {
                    const int32_t w1 = widthOf(text, p, font, tracking);
                    if (w1 > width1) { stop = true; break; }
                    const int32_t w2 = widthOf(text + p, length - p, font, tracking);
                    if (w2 <= width2) {
                        consider(best, p, p, w1, w2);
                        if (isWordSeparator(text[p - 1])) consider(separated, p, p, w1, w2);
                    }
                    utf8Next(text, p);
                }
            }
            start = end;
        }
        if (separated.found) best = separated;
    }
    size_t end1, start2;
    if (best.found) {
        end1 = best.end1;
        start2 = best.start2;
    } else if (greedyEnd1) {
        end1 = greedyEnd1;
        start2 = greedyStart2;
    } else {
        // The first word alone is wider than line 1: cut it by characters.
        end1 = fittingPrefix(text, font, tracking, width1);
        if (end1 == 0) { size_t one = 0; utf8Next(text, one); end1 = one; }
        start2 = end1;
        while (text[start2] == ' ') ++start2;
    }
    char line1[TEXT_CAP];
    if (end1 >= sizeof(line1)) end1 = sizeof(line1) - 1;
    memcpy(line1, text, end1);
    line1[end1] = '\0';
    copyText(out, cap, line1);
    const char* rest = text + start2;
    if (*rest) {
        const size_t used = strlen(out);
        if (used + 1 < cap) { out[used] = '\n'; out[used + 1] = '\0'; }
        appendLastLine(out, cap, rest, font, tracking, width2);   // whole when it fits (steps 1-2)
    }
}

// Usable width of a label's line k: design width clamped to the chord of the label's own radius
// (104; 112 for headings) over the ink rows of that line.
int32_t lineWidth(const Label& l, uint8_t k, int32_t inkTop, int32_t inkBottom) {
    const int32_t pitch = l.font->line_height + LINE_SPACE;
    const int32_t top = l.y + k * pitch;
    const int32_t half = safeHalf(top + inkTop, top + inkBottom, l.radius);
    const int32_t offset = l.centerX > CENTER ? l.centerX - CENTER : CENTER - l.centerX;
    int32_t width = 2 * (half - offset);
    if (k == 0 && l.crumbClear && crumbShown != CC_CRUMB_NONE) {
        const int32_t clear = 2 * crumbClearHalf(crumbShown, l.centerX, top + inkTop, top + inkBottom);
        if (clear < width) width = clear;
    }
    if (width < 0) width = 0;
    return width < l.w ? width : l.w;
}

void markChanged() { changed = true; }

void setVisible(lv_obj_t* obj, bool visible) {
    if (lv_obj_has_flag(obj, LV_OBJ_FLAG_HIDDEN) != !visible) {
        if (visible) lv_obj_remove_flag(obj, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
        markChanged();
    }
}

// A twin shows with its label, and only while a cover can be under it (twinsOn; refreshTwins()).
void setLabelVisible(Label& l, bool visible) {
    setVisible(l.obj, visible);
    if (l.twin) setVisible(l.twin, visible && twinsOn);
}

// visible false keeps the text set but hides the label (the tile letter under an app icon), so
// a later return costs no text set. The label's own LVGL copy is the comparison (LONG_CLIP never
// rewrites it).
void applyText(Label& l, const char* text, bool visible = true) {
    if (strcmp(lv_label_get_text(l.obj), text) != 0) {
        lv_label_set_text(l.obj, text);
        if (l.twin) lv_label_set_text(l.twin, text);
        ++stats.textSets;
        markChanged();
    }
    setLabelVisible(l, visible && text[0] != '\0');
}

uint32_t mixInk(uint32_t from, uint32_t to, int32_t v) {
    if (v <= 0) return from;
    if (v >= 255) return to;
    uint32_t out = 0;
    for (int shift = 16; shift >= 0; shift -= 8) {
        const uint32_t a = (from >> shift) & 255u, b = (to >> shift) & 255u;
        const uint32_t c = (a * static_cast<uint32_t>(255 - v) + b * static_cast<uint32_t>(v) + 127u) / 255u;
        out |= c << shift;
    }
    return out;
}

void execLabelInk(void* var, int32_t v) {
    Label* l = static_cast<Label*>(var);
    l->shownInk = mixInk(l->fadeFrom, l->ink, v);
    lv_obj_set_style_text_color(l->obj, lv_color_hex(l->shownInk), 0);
}

void execIconInk(void* var, int32_t v) {
    Icon* ic = static_cast<Icon*>(var);
    ic->shownInk = mixInk(ic->fadeFrom, ic->ink, v);
    lv_obj_set_style_image_recolor(ic->obj, lv_color_hex(ic->shownInk), 0);
}

// A baked spring (kSpringLut) as an LVGL anim path; the token index rides in the bezier3 parameter.
int32_t springPath(const lv_anim_t* a) {
    const SpringLut& lut = kSpringLut[a->parameter.bezier3.x1 & 3];
    if (a->act_time <= 0) return a->start_value;
    if (a->act_time >= a->duration) return a->end_value;
    const int32_t pos = static_cast<int32_t>((static_cast<int64_t>(a->act_time) * 40 * 256) / a->duration);
    const int32_t i = pos >> 8, f = pos & 255;
    const int32_t y = lut.y[i] + (((lut.y[i + 1] - lut.y[i]) * f) >> 8);
    return a->start_value + static_cast<int32_t>((static_cast<int64_t>(a->end_value - a->start_value) * y) / SPRING_ONE);
}

// duration 0 with a spring = the spring's own settle time.
void startAnim(void* var, lv_anim_exec_xcb_t exec, int32_t from, int32_t to, uint32_t duration, uint32_t delay,
               uint8_t ease) {
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, var);
    lv_anim_set_exec_cb(&a, exec);
    lv_anim_set_values(&a, from, to);
    lv_anim_set_delay(&a, delay);
    if (ease >= SPRING_SNAP) {
        lv_anim_set_duration(&a, duration ? duration : springMs(ease));
        lv_anim_set_path_cb(&a, springPath);
        a.parameter.bezier3.x1 = static_cast<int16_t>(ease - SPRING_SNAP);
    } else if (ease == EASE_LINEAR) {
        lv_anim_set_duration(&a, duration);
        lv_anim_set_path_cb(&a, lv_anim_path_linear);
    } else {
        const Curve& curve = CURVES[ease];
        lv_anim_set_duration(&a, duration);
        lv_anim_set_path_cb(&a, lv_anim_path_custom_bezier3);
        lv_anim_set_bezier3_param(&a, curve.x1, curve.y1, curve.x2, curve.y2);
    }
    lv_anim_start(&a);
    ++stats.animations;
    animated = true;
    markChanged();
}

// Instant ink (text lines; the twin keeps its black).
void applyInk(Label& l, uint32_t ink) {
    if (lv_anim_delete(&l, execLabelInk)) markChanged();
    if (!l.inkSet || l.ink != ink || l.shownInk != ink) {
        l.ink = l.shownInk = ink;
        l.inkSet = true;
        lv_obj_set_style_text_color(l.obj, lv_color_hex(ink), 0);
        markChanged();
    }
}

// Section 5.2 ink crossfade (idle words): 160 ms OUT, per 8-bit channel, from the ink shown.
void fadeLabelInk(Label& l, uint32_t ink, bool fade) {
    if (l.inkSet && l.ink == ink) return;
    if (!fade || !l.inkSet) {
        applyInk(l, ink);
        return;
    }
    lv_anim_delete(&l, execLabelInk);
    l.fadeFrom = l.shownInk;
    l.ink = ink;
    ++stats.inkFades;
    startAnim(&l, execLabelInk, 0, 255, INK_FADE_MS, 0, EASE_OUT);
}

void setIconInk(Icon& ic, uint32_t ink, bool fade) {
    if (ic.inkSet && ic.ink == ink) return;
    const bool running = lv_anim_delete(&ic, execIconInk);
    if (!fade || !ic.inkSet || ic.shownInk == ink) {
        ic.ink = ic.shownInk = ink;
        ic.inkSet = true;
        lv_obj_set_style_image_recolor(ic.obj, lv_color_hex(ink), 0);
        markChanged();
        return;
    }
    (void)running;
    ic.fadeFrom = ic.shownInk;
    ic.ink = ink;
    ++stats.inkFades;
    startAnim(&ic, execIconInk, 0, 255, INK_FADE_MS, 0, EASE_OUT);
}

void applyTracking(Label& l, int8_t tracking) {
    if (l.tracking != tracking) {
        l.tracking = tracking;
        lv_obj_set_style_text_letter_space(l.obj, tracking, 0);
        if (l.twin) lv_obj_set_style_text_letter_space(l.twin, tracking, 0);
        markChanged();
    }
}

// Fits and shows text unless the source is unchanged since the last fit. True when the source
// text changed (a meta or status line then fades in at rest, section 8.5.4).
bool showText(Label& l, const char* text) {
    const bool srcChanged = strcmp(l.src, text) != 0;
    if (!srcChanged && (!l.crumbClear || l.fitCrumb == crumbShown)) {
        setLabelVisible(l, lv_label_get_text(l.obj)[0] != '\0');
        return false;
    }
    copyText(l.src, sizeof(l.src), text);
    l.fitCrumb = crumbShown;                 // a crumb change refits a crumbClear label (FW-DES-001)
    char fitted[TEXT_CAP] = {};
    if (text[0]) {
        int32_t inkTop, inkBottom;
        inkRows(text, l.font, inkTop, inkBottom);
        const int32_t width1 = lineWidth(l, 0, inkTop, inkBottom);
        if (l.lines > 1) fitTwoLines(fitted, sizeof(fitted), text, l.font, l.tracking, width1,
                                     lineWidth(l, 1, inkTop, inkBottom));
        else appendLine(fitted, sizeof(fitted), text, l.font, l.tracking, width1);
    }
    applyText(l, fitted);
    return srcChanged;
}

// Section 8.10 offline sub-line (K1 erratum, lead ruling R-c): the native line is one line, so when
// it does not fit its line at 0 tracking it takes OFFLINE_NATIVE_TRACKING before the fit (the
// words stay whole: no wrap, no ellipsis); every other sub-line is fitted at 0.
void showOfflineSub(const char* text, bool native) {
    int8_t tracking = 0;
    if (native) {
        int32_t inkTop, inkBottom;
        inkRows(text, offSub.font, inkTop, inkBottom);
        if (widthOf(text, offSub.font, 0) > lineWidth(offSub, 0, inkTop, inkBottom))
            tracking = OFFLINE_NATIVE_TRACKING;
    }
    if (offSub.tracking != tracking) {
        applyTracking(offSub, tracking);
        offSub.src[0] = '\0';                // refit at the new tracking
    }
    showText(offSub, text);
}

// Section 8.5.2: 12 px caps at 1 px tracking in {51, 31, 138}, fitted against min(138, the r112
// chord of its ink rows). Every v5 heading fits as is; a legacy heading drops the tracking, then
// "RECENTLY ADDED · P{n}" shortens to "RECENT · P{n}", and only then is it ellipsized.
void showHeading(Label& l, const char* text) {
    if (strcmp(l.src, text) == 0) {
        setLabelVisible(l, lv_label_get_text(l.obj)[0] != '\0');
        return;
    }
    copyText(l.src, sizeof(l.src), text);
    char fitted[TEXT_CAP] = {};
    int8_t tracking = HEADING_TRACKING;
    if (text[0]) {
        int32_t inkTop, inkBottom;
        inkRows(text, l.font, inkTop, inkBottom);
        const int32_t width = lineWidth(l, 0, inkTop, inkBottom);
        static const char RECENT_LONG[] = "RECENTLY ADDED \xC2\xB7 P";
        static const char RECENT_SHORT[] = "RECENT \xC2\xB7 P";
        if (widthOf(text, l.font, HEADING_TRACKING) <= width) {
            copyText(fitted, sizeof(fitted), text);
        } else if (widthOf(text, l.font, 0) <= width) {
            copyText(fitted, sizeof(fitted), text);
            tracking = 0;
        } else if (strncmp(text, RECENT_LONG, sizeof(RECENT_LONG) - 1) == 0) {
            char shorter[TEXT_CAP];
            snprintf(shorter, sizeof(shorter), "%s%s", RECENT_SHORT, text + sizeof(RECENT_LONG) - 1);
            if (widthOf(shorter, l.font, HEADING_TRACKING) > width) {
                tracking = 0;
                appendLine(fitted, sizeof(fitted), shorter, l.font, 0, width);
            } else {
                copyText(fitted, sizeof(fitted), shorter);
            }
        } else {
            tracking = 0;
            appendLine(fitted, sizeof(fitted), text, l.font, 0, width);
        }
    }
    applyTracking(l, tracking);
    applyText(l, fitted);
}

// ------------------------------------------------------------------ tweens --
void execOpa(void* obj, int32_t v) {
    if (v < 0) v = 0;
    if (v > 255) v = 255;
    lv_obj_set_style_opa(static_cast<lv_obj_t*>(obj), static_cast<lv_opa_t>(v), 0);
}
void execTx(void* obj, int32_t v) { lv_obj_set_style_translate_x(static_cast<lv_obj_t*>(obj), v, 0); }
void execTy(void* obj, int32_t v) { lv_obj_set_style_translate_y(static_cast<lv_obj_t*>(obj), v, 0); }
// r4 M7 / M8 / M11: the image widget's own scale (a transformed draw of that 20 / 26 px image only, never a layer).
void execScaleX(void* obj, int32_t v) {
    lv_image_set_scale_x(static_cast<lv_obj_t*>(obj), static_cast<uint32_t>(v < 1 ? 1 : v));
}
void execScaleY(void* obj, int32_t v) {
    lv_image_set_scale_y(static_cast<lv_obj_t*>(obj), static_cast<uint32_t>(v < 1 ? 1 : v));
}
void execScale(void* obj, int32_t v) {
    lv_image_set_scale(static_cast<lv_obj_t*>(obj), static_cast<uint32_t>(v < 1 ? 1 : v));
}
// r4 M10: the visible height of a hold-fill clip box (bottom-anchored, holdFillHeight()).
void execHeight(void* obj, int32_t v);

lv_anim_exec_xcb_t execOf(uint8_t prop) {
    switch (prop) {
        case PROP_OPA: return execOpa;
        case PROP_TX: return execTx;
        case PROP_TY: return execTy;
        case PROP_SCALE_X: return execScaleX;
        case PROP_SCALE_Y: return execScaleY;
        case PROP_SCALE: return execScale;
        default: return execHeight;
    }
}

int32_t currentValue(const Tween& t) {
    switch (t.prop) {
        case PROP_OPA: return lv_obj_get_style_opa(t.obj, 0);
        case PROP_TX: return lv_obj_get_style_translate_x(t.obj, 0);
        case PROP_TY: return lv_obj_get_style_translate_y(t.obj, 0);
        case PROP_SCALE_X: return lv_image_get_scale_x(t.obj);
        case PROP_SCALE_Y: return lv_image_get_scale_y(t.obj);
        case PROP_SCALE: return lv_image_get_scale_x(t.obj);
        default: return lv_obj_get_height(t.obj);
    }
}

void initTween(Tween& t, lv_obj_t* obj, uint8_t prop, int32_t target) {
    t.obj = obj;
    t.prop = prop;
    t.set = false;
    t.target = target;
}

// CSS-transition semantics: when the target changes, move from the current value to the new
// target with the new state's timing; an unchanged target (heartbeat) does nothing. snap applies
// the target at once (and ends a running transition).
void glideStop(lv_obj_t* obj, uint8_t prop);

void tween(Tween& t, int32_t target, uint32_t duration, uint32_t delay, uint8_t ease, bool snap) {
    if (t.set && t.target == target && !snap) return;
    t.set = true;
    t.target = target;
    if (ease >= SPRING_SNAP && duration == 0) duration = springMs(ease);
    glideStop(t.obj, t.prop);                // a tween takes the property back from the stepper
    lv_anim_exec_xcb_t exec = execOf(t.prop);
    const bool running = lv_anim_get(t.obj, exec) != nullptr;
    if (running) { lv_anim_delete(t.obj, exec); markChanged(); }
    const int32_t current = currentValue(t);
    if (current == target) return;
    if (snap || duration == 0) {
        exec(t.obj, target);
        markChanged();
        return;
    }
    startAnim(t.obj, exec, current, target, duration, delay, ease);
}

// A fresh transition that starts from an explicit value (screen change, text at rest).
void tweenFrom(Tween& t, int32_t from, int32_t target, uint32_t duration, uint32_t delay, uint8_t ease) {
    if (ease >= SPRING_SNAP && duration == 0) duration = springMs(ease);
    glideStop(t.obj, t.prop);
    lv_anim_exec_xcb_t exec = execOf(t.prop);
    lv_anim_delete(t.obj, exec);
    t.set = true;
    t.target = target;
    exec(t.obj, from);
    markChanged();
    if (from != target) startAnim(t.obj, exec, from, target, duration, delay, ease);
}

// Section 8.5.4 + r4 M6: a meta or status line whose text changed at rest snaps to 0 and fades in (240 ms OUT)
// while it rises 10 px into place (SPRING.soft; reduced motion: the 160 ms fade only); otherwise (a screen
// change, a layer that just appeared, a detent that glides the rows, M4) it is at 255 / 0 at once.
void riseLine(Tween& opa, Tween& ty) {
    if (reducedMotion) {
        tweenFrom(opa, 0, 255, REDUCED_FADE_MS, 0, EASE_OUT);
        tween(ty, 0, 0, 0, EASE_OUT, true);
    } else {
        tweenFrom(opa, 0, 255, CONTENT_FADE_MS, 0, EASE_OUT);
        tweenFrom(ty, STATUS_RISE_PX, 0, 0, 0, SPRING_SOFT);
    }
    ++stats.lineFades;
}

void fadeLine(const Label& l, Tween& t, Tween& ty, bool textChanged, bool atRest) {
    if (textChanged && atRest && l.src[0]) {
        riseLine(t, ty);
    } else if (textChanged || !atRest) {
        tween(t, 255, 0, 0, EASE_OUT, true);
        tween(ty, 0, 0, 0, EASE_OUT, true);
    }
}

// --------------------------------------------------------------- r4 stepper --
void glideClock(void*, int32_t);

void glideEnsureClock() {
    if (lv_anim_get(&glideClockVar, glideClock)) return;
    glideLastMs = lv_tick_get();
    glideAccMs = 0;
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, &glideClockVar);
    lv_anim_set_exec_cb(&a, glideClock);
    lv_anim_set_values(&a, 0, 1000);
    lv_anim_set_duration(&a, 1000);
    lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
    lv_anim_start(&a);
}

void glideApply(Glide& g) {
    const float r = g.x < 0.0f ? g.x - 0.5f : g.x + 0.5f;
    const int32_t v = static_cast<int32_t>(r);
    if (v == g.shown) return;
    g.shown = v;
    execOf(g.prop)(g.obj, v);
}

// One 4 ms step of every active glide: the E.out lead-in leg (M13) or semi-implicit Euler on its spring.
void glideStep(uint32_t now) {
    for (uint8_t i = 0; i < GLIDE_COUNT; ++i) {
        Glide& g = glides[i];
        if (!g.active) continue;
        if (g.leg) {
            const int32_t since = static_cast<int32_t>(now - g.legAt);
            const uint32_t t = since < 0 ? 0u : static_cast<uint32_t>(since);
            if (t < g.legMs) {
                // E.out(u) sampled through LVGL's own bezier (the same curve as every other E.out).
                const int32_t u = static_cast<int32_t>((t * LV_BEZIER_VAL_MAX) / g.legMs);
                const int32_t y = lv_cubic_bezier(u, CURVES[EASE_OUT].x1, CURVES[EASE_OUT].y1, CURVES[EASE_OUT].x2,
                                                  CURVES[EASE_OUT].y2);
                g.x = g.legFrom + (g.legTo - g.legFrom) * static_cast<float>(y) / static_cast<float>(LV_BEZIER_VAL_MAX);
                g.v = 0.0f;
                continue;
            }
            g.leg = false;
            g.x = g.legTo;
            g.v = 0.0f;
        }
        const SpringKc& kc = kSpringKc[g.spring - SPRING_SNAP];
        const float dt = 0.004f;
        const float a = kc.k * (g.target - g.x) - kc.c * g.v;
        g.v += a * dt;
        g.x += g.v * dt;
        const float d = g.x - g.target;
        if (d < 0.25f && d > -0.25f && g.v < 4.0f && g.v > -4.0f) {
            g.x = g.target;
            g.v = 0.0f;
            g.active = false;
        }
    }
}

// Integrates every glide up to now (4 ms steps; a stalled pass never integrates more than 100 ms).
void glideCatchUp() {
    const uint32_t now = lv_tick_get();
    uint32_t dt = now - glideLastMs;
    glideLastMs = now;
    if (dt > 100) dt = 100;
    glideAccMs += dt;
    while (glideAccMs >= 4) {
        glideAccMs -= 4;
        glideStep(now - glideAccMs);
    }
}

// The one stepper anim's exec (every animation-timer run): 4 ms steps up to now, then the rounded values.
void glideClock(void*, int32_t) {
    glideCatchUp();
    bool active = false;
    for (uint8_t i = 0; i < GLIDE_COUNT; ++i) {
        if (glides[i].obj) glideApply(glides[i]);
        active = active || glides[i].active;
    }
    if (!active) lv_anim_delete(&glideClockVar, glideClock);
}

void initGlide(uint8_t slot, lv_obj_t* obj, uint8_t prop) {
    Glide& g = glides[slot];
    memset(&g, 0, sizeof(g));
    g.obj = obj;
    g.prop = prop;
    g.spring = SPRING_SNAP;
}

void glideStop(lv_obj_t* obj, uint8_t prop) {
    for (uint8_t i = 0; i < GLIDE_COUNT; ++i) {
        Glide& g = glides[i];
        if (g.active && g.obj == obj && g.prop == prop) {
            g.active = false;
            g.leg = false;
        }
    }
}

// M4 / M5: jump to `from` on this frame (retargets a running glide: position replaced, velocity kept), then
// the spring back to 0.
void glideJump(uint8_t slot, int32_t from, uint8_t spring) {
    if (lv_anim_get(&glideClockVar, glideClock)) glideCatchUp();   // the others up to now; this one starts now
    Glide& g = glides[slot];
    lv_anim_delete(g.obj, execOf(g.prop));   // the stepper owns the property now
    if (!g.active) g.v = 0.0f;
    g.x = static_cast<float>(from);
    g.target = 0.0f;
    g.spring = spring;
    g.leg = false;
    g.active = true;
    g.shown = -32768;                        // never a real value: apply now
    glideApply(g);
    glideEnsureClock();
    ++stats.glides;
    animated = true;
    markChanged();
}

// M13: from where it is, `to` in legMs E.out, then the spring back to 0.
void glidePush(uint8_t slot, int32_t to, uint32_t legMs, uint8_t spring) {
    if (lv_anim_get(&glideClockVar, glideClock)) glideCatchUp();
    Glide& g = glides[slot];
    lv_anim_delete(g.obj, execOf(g.prop));
    const int32_t current = currentValue(Tween{g.obj, g.prop, true, 0});
    g.legFrom = g.active ? g.x : static_cast<float>(current);
    g.legTo = static_cast<float>(to);
    g.legAt = lv_tick_get();
    g.legMs = legMs;
    g.leg = true;
    g.x = g.legFrom;
    g.v = 0.0f;
    g.target = 0.0f;
    g.spring = spring;
    g.active = true;
    g.shown = current;
    glideEnsureClock();
    animated = true;
    markChanged();
}

// Snap every glide to rest (a claim's first render, the offline layer).
void glideRest() {
    for (uint8_t i = 0; i < GLIDE_COUNT; ++i) {
        Glide& g = glides[i];
        if (!g.obj) continue;
        g.active = false;
        g.leg = false;
        g.x = g.v = g.target = 0.0f;
        glideApply(g);
    }
    lv_anim_delete(&glideClockVar, glideClock);
}

// ------------------------------------------------------------ A8 from flash --
// LVGL 9.0.0's bin decoder copies an A8 variable image (decode_alpha_only(): lv_malloc + memcpy of the whole
// mask) on every draw, i.e. on every draw-buffer chunk the image touches (no image cache, LV_CACHE_DEF_SIZE 0).
// Every A8 image of this renderer is a constant table with stride == width, so it is drawn from where it lies.
lv_draw_buf_t a8Bufs[4];
uint8_t a8Next = 0;

lv_result_t a8Info(lv_image_decoder_t*, const void* src, lv_image_header_t* header) {
    if (lv_image_src_get_type(src) != LV_IMAGE_SRC_VARIABLE) return LV_RESULT_INVALID;
    const lv_image_dsc_t* d = static_cast<const lv_image_dsc_t*>(src);
    if (d->header.cf != LV_COLOR_FORMAT_A8 || d->header.stride != d->header.w || !d->data) return LV_RESULT_INVALID;
    *header = d->header;
    return LV_RESULT_OK;
}

lv_result_t a8Open(lv_image_decoder_t*, lv_image_decoder_dsc_t* dsc) {
    lv_draw_buf_t* b = &a8Bufs[a8Next++ & 3];
    lv_draw_buf_from_image(b, static_cast<const lv_image_dsc_t*>(dsc->src));
    dsc->decoded = b;
    ++stats.a8Direct;
    return LV_RESULT_OK;
}

void a8Close(lv_image_decoder_t*, lv_image_decoder_dsc_t*) {}

// ---------------------------------------------------------------- creation --
void tag(lv_obj_t* obj, const char* role) { lv_obj_set_user_data(obj, const_cast<char*>(role)); }

lv_obj_t* makeBox(lv_obj_t* parent, int32_t x, int32_t y, int32_t w, int32_t h, const char* role) {
    lv_obj_t* obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, w, h);
    lv_obj_remove_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
    tag(obj, role);
    return obj;
}

// A layer at absolute box b inside parent (absolute origin parentX/Y).
void makeLayer(Layer& layer, lv_obj_t* parent, int16_t parentX, int16_t parentY, const Box& b, const char* role) {
    layer.obj = makeBox(parent, b.x - parentX, b.y - parentY, b.w, b.h, role);
    layer.x = b.x;
    layer.y = b.y;
}

void makeLayer(Layer& layer, const Layer& parent, const Box& b, const char* role) {
    makeLayer(layer, parent.obj, parent.x, parent.y, b, role);
}

lv_obj_t* newLabel(lv_obj_t* parent, int32_t x, int32_t y, const Box& box, const lv_font_t* font,
                   lv_text_align_t align, const char* role) {
    lv_obj_t* obj = lv_label_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, box.w, box.h);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_align(obj, align, 0);
    lv_obj_set_style_text_line_space(obj, LINE_SPACE, 0);
    // Fitting happens before LVGL (U+2026 placed by showText); CLIP never rewrites the text, so the
    // label's own copy is the heartbeat comparison.
    lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
    lv_label_set_text(obj, "");
    lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
    tag(obj, role);
    return obj;
}

// box: absolute. twinRole non-null: a text-shadow twin (section 8.5.3) is created first (below).
void makeLabel(Label& l, const Layer& parent, const Box& box, const lv_font_t* font, uint8_t lines,
               lv_text_align_t align, const char* role, const char* twinRole = nullptr,
               int16_t radius = SAFE_R, int8_t tracking = 0) {
    memset(&l, 0, sizeof(l));
    l.font = font;
    l.x = box.x;
    l.y = box.y;
    l.w = box.w;
    l.centerX = static_cast<int16_t>(box.x + box.w / 2);
    l.radius = radius;
    l.lines = lines;
    l.tracking = tracking;
    const int32_t x = box.x - parent.x, y = box.y - parent.y;
#if CC_TEXT_TWINS
    if (twinRole) {
        l.twin = newLabel(parent.obj, x, y + 1, box, font, align, twinRole);
        lv_obj_set_style_text_color(l.twin, lv_color_hex(CCInk::shadow), 0);
        lv_obj_set_style_text_opa(l.twin, TWIN_OPA, 0);
        if (tracking) lv_obj_set_style_text_letter_space(l.twin, tracking, 0);
    }
#else
    (void)twinRole;
#endif
    l.obj = newLabel(parent.obj, x, y, box, font, align, role);
    if (tracking) lv_obj_set_style_text_letter_space(l.obj, tracking, 0);
}

void makeIcon(Icon& icon, const Layer& parent, int32_t x, int32_t y, int16_t size, const char* role) {
    memset(&icon, 0, sizeof(icon));
    icon.obj = lv_image_create(parent.obj);
    icon.size = size;
    lv_obj_remove_style_all(icon.obj);
    lv_obj_set_pos(icon.obj, x - parent.x, y - parent.y);
    lv_obj_set_size(icon.obj, size, size);
    lv_obj_set_style_image_recolor_opa(icon.obj, LV_OPA_COVER, 0);
    lv_obj_add_flag(icon.obj, LV_OBJ_FLAG_HIDDEN);
    tag(icon.obj, role);
}

// A8 mask recoloured to ink (the sw renderer draws A8 in the recolor colour). dsc nullptr hides
// the icon. A glyph change is instant; with `fade`, an ink change of an icon that stays shown
// crossfades from the ink on screen (section 5.2).
void showIcon(Icon& ic, const lv_image_dsc_t* dsc, uint32_t ink, bool fade) {
    const bool wasShown = ic.src != nullptr;
    if (dsc != ic.src) {
        ic.src = dsc;
        if (dsc) lv_image_set_src(ic.obj, dsc);
        markChanged();
    }
    if (dsc) setIconInk(ic, ink, fade && wasShown);
    setVisible(ic.obj, dsc != nullptr);
}

// The glyph a button draws: tone liked is the filled heart ([r2.2], section 5.2 row 4 / 9.1), any
// other tone the token's own mask; nullptr hides (tone none, or no mask at this size).
const lv_image_dsc_t* buttonGlyph(const CCFrame& f, uint8_t slot, uint8_t tone, int size) {
    if (tone == CC_TONE_NONE) return nullptr;
    if (tone == CC_TONE_LIKED) return cc_icon(LIKED_GLYPH, size);
    uint8_t icon = cc_button_icon(f.buttons[slot]);
    if (icon >= ICON_COUNT) icon = CC_ICON_NONE;
    return icon == CC_ICON_NONE ? nullptr : cc_icon(ICON_NAMES[icon], size);
}

// ------------------------------------------------------------------- media --
// ARTWORK2.md 4.4 "Display adoption": the store pins the slot the LCD draws (adopt) and is told
// when the LCD draws no media of a kind (release).
void releaseMedia(uint8_t kind) {
    if (!mediaHeld[kind]) return;
    mediaHeld[kind] = false;
    if (media.release) media.release(kind);
}

// The committed payload for key, pinned as displayed; a miss (or no key) releases the kind's
// pin. Cheap and idempotent: the store touches a slot only when its displayed slot changes.
bool adoptMedia(uint8_t kind, const char* key, const uint8_t** data, uint32_t* bytes) {
    *data = nullptr;
    *bytes = 0;
    if (media.adopt && key[0] && strlen(key) <= CC_DISPLAY_MEDIA_KEY_MAX && media.adopt(kind, key, data, bytes)) {
        mediaHeld[kind] = true;
        if (*data && *bytes) return true;
    }
    releaseMedia(kind);
    *data = nullptr;
    *bytes = 0;
    return false;
}

bool asyncArt() { return media.requestCover && media.pollCover && media.cancelCover && artBuffer[1]; }

void cancelDecode(bool cancel) {
    if (!decode.inFlight || decode.cancelled == cancel) return;
    decode.cancelled = cancel;
    media.cancelCover(cancel);
}

// ------------------------------------------------------------------ render --
uint8_t groupOf(uint8_t layout) {
    switch (layout) {
        case CC_LAYOUT_RECENT: return GROUP_RECENT;
        case CC_LAYOUT_TRACKS:
        case CC_LAYOUT_SEEK: return GROUP_TRACKS;           // entering/leaving Seek never slides
        case CC_LAYOUT_WINDOWS: return GROUP_WINDOWS;
        case CC_LAYOUT_EXPLORER: return GROUP_EXPLORER;
        case CC_LAYOUT_UPNEXT: return GROUP_UPNEXT;
        case CC_LAYOUT_LIGHTS:
        case CC_LAYOUT_LIGHTSBIG: return GROUP_LIGHTS;      // the reveal never slides (like Home's)
        case CC_LAYOUT_SCENES: return GROUP_SCENES;
        default: return GROUP_HOME;
    }
}

// Section 8.7: home 0, recent 1 + page', tracks 1, windows 5, explorer 30 + page', upnext 30; presentation 6
// (section 19.4): lights 1, scenes 2 (Home -> Lights -> Scenes slide in from the right, back from the left).
int32_t depthOf(uint8_t group, uint8_t page) {
    switch (group) {
        case GROUP_TRACKS: return 1;
        case GROUP_RECENT: return 1 + page;
        case GROUP_WINDOWS: return 5;
        case GROUP_EXPLORER: return 30 + page;
        case GROUP_UPNEXT: return 30;
        case GROUP_LIGHTS: return 1;
        case GROUP_SCENES: return 2;
        default: return 0;
    }
}

// Presentation 6 (section 19.9): with a crumb the screen's depth is the breadcrumb's (README r3 section 4:
// home 0; music, windows, lights 1; albums, tracks, scenes 2; explorer, upnext 3), in steps of 64 so a page'
// (the explorer tabs, the Recent pages) still orders within one depth. Without one: section 8.7 / 19.4.
int32_t screenDepth(uint8_t group, uint8_t page, uint8_t crumb) {
    if (crumb == CC_CRUMB_NONE) return depthOf(group, page);
    return static_cast<int32_t>(cc_crumb_depth(crumb)) * 64 + page;
}

// Section 19.9: the arc breadcrumb. A new crumb swaps both masks at once and fades them in (200 ms OUT); none
// fades the shown ones out. Hidden on the launcher (no crumb), in the idle icon view and offline.
void showCrumb(uint8_t crumb, bool snap) {
    if (crumb == crumbShown) return;
    crumbShown = crumb;
    // r4 M15: the crumb crossfades with the content (M1): the outgoing slot fades out while the incoming one
    // fades in, both over the content's fade (240 ms OUT; reduced motion 160 ms).
    const uint32_t fade = reducedMotion ? REDUCED_FADE_MS : CONTENT_FADE_MS;
    const uint8_t old = crumbSlot, next = static_cast<uint8_t>(1 - crumbSlot);
    for (uint8_t part = 0; part < 2; ++part) tween(crumbOpa[old * 2 + part], 0, fade, 0, EASE_OUT, snap);
    crumbSlot = next;
    for (uint8_t part = 0; part < 2; ++part) {
        const uint8_t k = static_cast<uint8_t>(next * 2 + part);
        const CCCrumbMask* mask = crumb == CC_CRUMB_NONE ? nullptr : cc_crumb_mask(crumb, part == 1);
        if (!mask) {
            tween(crumbOpa[k], 0, 0, 0, EASE_OUT, true);
            continue;
        }
        lv_image_dsc_t& dsc = crumbDsc[k];
        memset(&dsc, 0, sizeof(dsc));
        dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
        dsc.header.cf = LV_COLOR_FORMAT_A8;
        dsc.header.w = mask->w;
        dsc.header.h = mask->h;
        dsc.header.stride = mask->w;
        dsc.data_size = static_cast<uint32_t>(mask->w) * mask->h;
        dsc.data = mask->data;
        lv_obj_set_pos(crumbImg[k], mask->x, mask->y);
        lv_obj_set_size(crumbImg[k], mask->w, mask->h);
        lv_image_set_src(crumbImg[k], &dsc);
        lv_obj_invalidate(crumbImg[k]);
        setVisible(crumbImg[k], true);
        if (snap) tween(crumbOpa[k], 255, 0, 0, EASE_OUT, true);
        else tweenFrom(crumbOpa[k], 0, 255, fade, 0, EASE_OUT);
        markChanged();
    }
}

// lights (presentation 6, section 19.4): the frame is lights / lightsbig. Its 12 px line is `meta` (metaTone)
// and the reveal's unit is valueUnit ("%" or "K"); everything else is the Home drawing.
// r4 (README 3.2): M2 the big value in (text out 130 ms E.in 12 px up; big layer from 14 px below, fade 180 ms
// OUT after 40 ms, SPRING.snap), M3 the big value out (big out 130 ms E.in; text back from 12 px above after 90 ms,
// fade 260 ms, SPRING.soft), M5 the track change (the text rises 14 px into place, SPRING.snap), M6 the status line
// (rises 10 px, fades in 240 ms; leaves with a plain fade), M11 the idle row (each icon from 16 px below at 85 %,
// 40 ms stagger from 140 ms, fade 260 ms, SPRING.pop). Reduced motion: 160 ms opacity crossfades only.
// textAtRest: the text layer was on screen at rest before this render (a song change there is M5).
void renderHome(const CCFrame& f, bool volume, bool idle, bool snap, bool statusAtRest, bool inkFade, bool lights,
                bool textAtRest) {
    const bool away = volume || idle;
    const bool titleChanged = showText(homeTitle, f.title);
    applyInk(homeTitle, CCInk::text);
    const bool artistChanged = showText(homeArtist, f.subtitle);
    applyInk(homeArtist, CCInk::context);
    const bool rm = reducedMotion;
    if (rm) {
        tween(trackOpa, away ? 0 : 255, REDUCED_FADE_MS, 0, EASE_OUT, snap);
        tween(trackTy, 0, 0, 0, EASE_OUT, true);
    } else {
        tween(trackOpa, away ? 0 : 255, away ? 130 : 260, away ? 0 : 90, away ? EASE_IN : EASE_OUT, snap);
        if (away) tween(trackTy, -12, 160, 0, EASE_IN, snap);
        else tween(trackTy, 0, 0, 90, SPRING_SOFT, snap);
    }
    // M5: a new song while the text shows at rest (not a reveal, not the Lights text) rises 14 px into place.
    if (!rm && !snap && !away && !lights && textAtRest && (titleChanged || artistChanged) && f.title[0]) {
        glideJump(GLIDE_TRACK, GLIDE_PX, SPRING_SNAP);
        ++stats.trackChanges;
    }

    showText(volumeCaption, f.volumeCaption[0] ? f.volumeCaption : f.title);
    applyInk(volumeCaption, CCInk::context);
    // 48 px digits (value without its '%') and a 22 px unit on one baseline. The unit is '%' except on a lightsbig
    // frame with valueUnit "K" (presentation 6, section 19.2); it is drawn with the 22 px face in #A6A6A6 like '%'
    // (README r3 section 2.2), cc_font_48 also carries 'K'. r4 README 3.6: the number right-aligned and the unit
    // left-aligned around a computed centre, 4 px apart, so they never overlap when the digit count changes.
    char number[8] = {};
    size_t n = 0;
    for (const char* c = f.value; *c && *c != '%' && n + 1 < sizeof(number); ++c)
        if ((*c >= '0' && *c <= '9') || *c == '-') number[n++] = *c;
    const char* unit = lights && f.layoutId == CC_LAYOUT_LIGHTSBIG && f.valueUnit == CC_UNIT_KELVIN ? "K" : "%";
    applyText(digits, number);
    applyText(percent, n ? unit : "");
    const int32_t wd = n ? widthOf(number, digits.font, DIGITS_TRACKING) : 0;
    const int32_t wp = n ? widthOf(unit, percent.font, 0) : 0;
    if (wd != digitsWidth || wp != percentWidth) {
        digitsWidth = wd;
        percentWidth = wp;
        // The pair [number][4 px][unit] centred on the screen: the number ends DIGIT_GAP / 2 left of the centre
        // between them, the unit starts DIGIT_GAP / 2 right of it.
        const int32_t left = CENTER - (wd + DIGIT_GAP + wp + 1) / 2 - volumeLayer.x;
        const int32_t unitX = left + wd + DIGIT_GAP;
        const int32_t dy = DIGITS_Y - volumeLayer.y, py = PERCENT_Y - volumeLayer.y;
        lv_obj_set_pos(digits.obj, left, dy);
        lv_obj_set_width(digits.obj, wd + 2);
        lv_obj_set_pos(percent.obj, unitX, py);
        lv_obj_set_width(percent.obj, wp + 2);
        if (digits.twin) {
            lv_obj_set_pos(digits.twin, left, dy + 1);
            lv_obj_set_width(digits.twin, wd + 2);
        }
        if (percent.twin) {
            lv_obj_set_pos(percent.twin, unitX, py + 1);
            lv_obj_set_width(percent.twin, wp + 2);
        }
        markChanged();
    }
    // A hidden layer keeps its offset under reduced motion (no invisible retarget, so a frame that only latches
    // reducedMotion stays inert); the reveal then snaps it to 0 (opacity only).
    if (rm) {
        tween(volumeOpa, volume ? 255 : 0, REDUCED_FADE_MS, 0, EASE_OUT, snap);
        tween(volumeTy, volume ? 0 : volumeTy.target, 0, 0, EASE_OUT, true);
    } else {
        tween(volumeOpa, volume ? 255 : 0, volume ? 180 : 130, volume ? 40 : 0, volume ? EASE_OUT : EASE_IN, snap);
        if (volume) tween(volumeTy, 0, 0, 40, SPRING_SNAP, snap);
        else tween(volumeTy, GLIDE_PX, 160, 0, EASE_IN, snap);
    }

    const char* line = lights ? f.meta : f.status;
    const bool row = idle && !volume;
    bool statusChanged = false;
    if (!row && !line[0] && status.src[0] && statusAtRest) {
        // M6: the line leaves with a plain fade, its words kept until the next text replaces them.
        if (!statusLeaving) {
            statusLeaving = true;
            tween(statusOpa, 0, rm ? REDUCED_FADE_MS : CONTENT_FADE_MS, 0, EASE_OUT, false);
        }
    } else {
        statusLeaving = false;
        statusChanged = showText(status, line);
    }
    applyInk(status, cc_line_ink(lights ? f.metaTone : f.statusTone));
    if (row) {
        tween(statusOpa, 0, rm ? REDUCED_FADE_MS : 240, 0, EASE_OUT, snap);   // the idle hide wins
    } else if (statusLeaving) {
        // fading out (above)
    } else if (statusChanged && statusAtRest && status.src[0]) {
        riseLine(statusOpa, statusTy);                                        // M6
    } else {
        tween(statusOpa, 255, rm ? REDUCED_FADE_MS : 240, 0, EASE_OUT, snap);   // FW-DES-003: r4 section 7
        tween(statusTy, 0, 0, 0, EASE_OUT, true);
    }

    for (uint8_t i = 0; i < 4; ++i) {
        const uint8_t tone = cc_button_tone(f, i);
        const uint32_t ink = cc_button_ink(f, i);
        showIcon(idleIcon[i], buttonGlyph(f, i, tone, IDLE_ICON), ink, inkFade);
        showText(idleWord[i], tone != CC_TONE_NONE ? f.buttons[i].label : "");
        fadeLabelInk(idleWord[i], ink, inkFade);
        // M11 (r4 README 3.2): 40 ms stagger from 140 ms, fade 260 ms OUT, from 16 px below at 85 %, SPRING.pop.
        const uint32_t stagger = 140u + 40u * i;
        if (rm) {
            // A hidden item keeps its offset and scale (no invisible retarget: a frame that only latches
            // reducedMotion stays inert); the entrance then snaps them to rest (opacity only).
            tween(idleOpa[i], row ? 255 : 0, REDUCED_FADE_MS, row ? stagger : 0, EASE_OUT, snap);
            tween(idleTy[i], row ? 0 : idleTy[i].target, 0, 0, EASE_OUT, true);
            tween(idleScale[i], row ? 256 : idleScale[i].target, 0, 0, EASE_OUT, true);
        } else {
            tween(idleOpa[i], row ? 255 : 0, row ? 260 : 120, row ? stagger : 0, row ? EASE_OUT : EASE_IN, snap);
            if (row) {
                tween(idleTy[i], 0, 0, stagger, SPRING_POP, snap);
                tween(idleScale[i], 256, 0, stagger, SPRING_POP, snap);
            } else {
                tween(idleTy[i], IDLE_RISE_PX, 140, 0, EASE_IN, snap);
                tween(idleScale[i], IDLE_SCALE, 140, 0, EASE_IN, snap);
            }
        }
    }
}

void renderList(const CCFrame& f, bool metaAtRest) {
    showText(listTitle, f.title);
    applyInk(listTitle, cc_title_ink(f.titleTone));
    showText(listSub, f.subtitle);
    applyInk(listSub, CCInk::context);
    // Lists draw meta (metaTone); the status line is Home-only.
    const bool metaChanged = showText(listMeta, f.meta);
    applyInk(listMeta, cc_line_ink(f.metaTone));
    fadeLine(listMeta, listMetaOpa, listMetaTy, metaChanged, metaAtRest);
}

void renderTracks(const CCFrame& f, bool metaAtRest) {
    showText(tracksTitle, f.title);
    applyInk(tracksTitle, cc_title_ink(f.titleTone));
    const uint16_t selected = f.ringIndex <= 2 ? f.ringIndex : 1;
    const bool noPrevious = (f.ringUnavailable & 1u) != 0;
    // Desk Dial r3.1: the prev / dot / next position row belongs to the 3-position transport ring only;
    // any other ring (the whole-queue Tracks sends a selection ring) hides it.
    const bool transport = f.ringStyle == CC_RING_TRANSPORT;
    static const char* const names[3] = {"prev", DOT_GLYPH, "next"};
    for (uint16_t i = 0; i < 3; ++i) {
        uint32_t ink = selected == i ? CCInk::text : CCInk::meta;
        if (i == 0 && noPrevious) ink = CCInk::disabledGlyph;
        showIcon(positionIcon[i], transport ? cc_icon(names[i], POS_ICON) : nullptr, ink, false);
    }
    showText(tracksSub, f.subtitle);
    applyInk(tracksSub, CCInk::context);
    const bool metaChanged = showText(tracksMeta, f.meta);
    applyInk(tracksMeta, cc_line_ink(f.metaTone));
    fadeLine(tracksMeta, tracksMetaOpa, tracksMetaTy, metaChanged, metaAtRest);
}

// Section 8.6.8: the 14 px caption is the song (`title`), the 48 px tabular time mmss(ring.index)
// of a lap ring (redrawn per frame, never animated), the 14 px line the `meta` (#A6A6A6 for tone
// meta, P5-R2). None of them fades (section 8.5.4).
void renderSeek(const CCFrame& f) {
    showText(seekCaption, f.title);
    applyInk(seekCaption, CCInk::context);
    char time[12] = {};
    if (f.ringStyle == CC_RING_LAP) cc_mmss(f.ringIndex, time, sizeof(time));
    showText(seekTime, time);
    applyInk(seekTime, CCInk::text);
    showText(seekLine, f.meta);
    applyInk(seekLine, f.metaTone == CC_LINE_META ? CCInk::context : cc_line_ink(f.metaTone));
}

// Presentation 6 (section 19.4; README r3 section 2.2): the scenes list. prevTitle / nextTitle 14 px #7C7C7C
// (one line each), the current scene `title` 22 px (one line, titleTone), `meta` 12 px (metaTone), which
// fades at rest like the other lists' meta (section 8.5.4).
void renderScenes(const CCFrame& f, bool metaAtRest) {
    showText(scenePrev, f.prevTitle);
    applyInk(scenePrev, CCInk::meta);
    showText(sceneTitle, f.title);
    applyInk(sceneTitle, cc_title_ink(f.titleTone));
    showText(sceneNext, f.nextTitle);
    applyInk(sceneNext, CCInk::meta);
    const bool metaChanged = showText(sceneMeta, f.meta);
    applyInk(sceneMeta, cc_line_ink(f.metaTone));
    fadeLine(sceneMeta, sceneMetaOpa, sceneMetaTy, metaChanged, metaAtRest);
}

bool selectedUnavailable(const CCFrame& f) {
    if (f.ringIndex < f.ringFirst) return false;
    const uint32_t k = static_cast<uint32_t>(f.ringIndex - f.ringFirst);
    return k < CC_RING_WINDOW && ((f.ringUnavailable >> k) & 1u) != 0;
}

// ARTWORK2.md section 7 icons: the selected window's 32x32 icon fills the tile (transparent tile
// background, letter hidden) when the store has iconKey. It is copied into the tile buffer only
// when the key changes and appears at once (no fade). Otherwise the letter tile is drawn.
bool renderTileIcon(const CCFrame& f) {
    const uint8_t* data = nullptr;
    uint32_t bytes = 0;
    bool shown = adoptMedia(CC_DISPLAY_MEDIA_ICON, f.iconKey, &data, &bytes);
    if (shown && bytes != CC_ICON_BYTES) {
        releaseMedia(CC_DISPLAY_MEDIA_ICON);
        shown = false;
    }
    if (shown && strcmp(iconLoadedKey, f.iconKey) != 0) {
        memcpy(iconPixels, data, CC_ICON_BYTES);
        copyText(iconLoadedKey, sizeof(iconLoadedKey), f.iconKey);
        lv_obj_invalidate(tileIcon);
        ++stats.iconLoads;
        markChanged();
    }
    setVisible(tileIcon, shown);
    if (shown != tileIconShown) {
        tileIconShown = shown;
        lv_obj_set_style_bg_opa(tile, static_cast<lv_opa_t>(shown ? LV_OPA_TRANSP : LV_OPA_COVER), 0);
        markChanged();
    }
    return shown;
}

void renderWindows(const CCFrame& f, bool metaAtRest) {
    const bool icon = renderTileIcon(f);
    // Letter tile: the subtitle's first code point, upper-cased when it is ASCII a-z (other code
    // points as-is; lcd_preview.py does the same).
    char letter[5] = {};
    size_t end = 0;
    if (f.subtitle[0]) utf8Next(f.subtitle, end);
    memcpy(letter, f.subtitle, end < sizeof(letter) ? end : sizeof(letter) - 1);
    if (end == 1 && letter[0] >= 'a' && letter[0] <= 'z') letter[0] = static_cast<char>(letter[0] - 'a' + 'A');
    // Section 5.3 tile fallback: sat() of the selected entry's accent with a #FFFFFF initial, else
    // V4's #444 tile with a #F2F2F2 initial.
    uint32_t bg = CCInk::tile, initial = CCInk::tileInitial, accent = 0, s = 0;
    if (f.ringIndex >= f.ringFirst && static_cast<uint32_t>(f.ringIndex - f.ringFirst) < f.ringColorCount)
        accent = f.ringColors[f.ringIndex - f.ringFirst];
    if (accent != 0 && cc_sat(accent, s)) {
        bg = s;
        initial = CCInk::accentInitial;
    }
    if (bg != tileBg) {
        tileBg = bg;
        lv_obj_set_style_bg_color(tile, lv_color_hex(bg), 0);
        markChanged();
    }
    applyText(tileLetter, letter, !icon);
    applyInk(tileLetter, initial);
    setVisible(tile, icon || f.subtitle[0] != '\0');
    // The closed entry dims the whole tile group (icon or letter) to 0.35.
    const uint8_t opa = selectedUnavailable(f) ? TILE_CLOSED_OPA : 255;
    if (opa != tileOpa) {
        tileOpa = opa;
        lv_obj_set_style_opa(tile, opa, 0);
        markChanged();
    }
    showText(winApp, f.subtitle);
    applyInk(winApp, CCInk::context);
    showText(winTitle, f.title);
    applyInk(winTitle, cc_title_ink(f.titleTone));
    const bool metaChanged = showText(winMeta, f.meta);
    applyInk(winMeta, cc_line_ink(f.metaTone));
    fadeLine(winMeta, winMetaOpa, winMetaTy, metaChanged, metaAtRest);
}

// r4 M10: the hold-fill clip box keeps its bottom on the icon's bottom row; the warm copy inside stays aligned with
// the base icon (it moves up inside the box by the part not yet shown).
void execHeight(void* obj, int32_t v) {
    lv_obj_t* clip = static_cast<lv_obj_t*>(obj);
    if (v < 0) v = 0;
    if (v > FOOTER_ICON) v = FOOTER_ICON;
    lv_obj_set_height(clip, v);
    lv_obj_set_y(clip, FOOTER_Y - footerLayer.y + (FOOTER_ICON - v));
    if (holdFill) lv_obj_set_y(holdFill, -(FOOTER_ICON - v));
}

// The slot showing the Play / Pause glyph (M8 / M9), or -1.
int8_t playSlot(const CCFrame& f) {
    for (int8_t i = 3; i >= 0; --i) {
        const uint8_t icon = cc_button_icon(f.buttons[i]);
        if (icon == CC_ICON_PLAY || icon == CC_ICON_PAUSE) return i;
    }
    return -1;
}

// M8: the icon jumps to 1.28 x on this frame and springs back (SPRING.pop). Reduced motion: nothing.
void popIcon(uint8_t slot) {
    if (reducedMotion || !footerIcon[slot].src) return;
    FooterMotion& m = footerMotion[slot];
    lv_anim_delete(m.sx.obj, execScaleX);    // the pop replaces a squash still springing back
    lv_anim_delete(m.sy.obj, execScaleY);
    m.sx.target = m.sy.target = 256;
    tweenFrom(m.scale, POP_SCALE, 256, 0, 0, SPRING_POP);
    tween(m.ty, 0, 0, 0, SPRING_POP, false);
    ++stats.pops;
}

// M9 (r4 README 3.2): the bars' corners melt into the triangle (and back) over 300 ms E.out, 12 A8 frames.
void execMorph(void* var, int32_t v) {
    Morph* mo = static_cast<Morph*>(var);
    if (mo->slot < 0) return;
    Icon& ic = footerIcon[mo->slot];
    // v: 0..CC_ICON_MORPH_FRAMES + 1 along pause -> play; the end values are the glyphs themselves.
    const int32_t k = mo->toPlay ? v : CC_ICON_MORPH_FRAMES + 1 - v;
    const lv_image_dsc_t* frame = k <= 0 ? cc_icon("pause", FOOTER_ICON)
                                  : k > CC_ICON_MORPH_FRAMES ? cc_icon("play", FOOTER_ICON)
                                                              : cc_icon_morph(static_cast<uint8_t>(k));
    if (v >= CC_ICON_MORPH_FRAMES + 1) frame = ic.src;       // the end: the glyph the frame asked for
    if (frame && lv_image_get_src(ic.obj) != frame) lv_image_set_src(ic.obj, frame);
}

void startMorph(uint8_t slot, bool toPlay) {
    if (morph.slot >= 0 && morph.slot != static_cast<int8_t>(slot)) {
        lv_anim_delete(&morph, execMorph);
        if (footerIcon[morph.slot].src) lv_image_set_src(footerIcon[morph.slot].obj, footerIcon[morph.slot].src);
    }
    morph.slot = static_cast<int8_t>(slot);
    morph.toPlay = toPlay;
    morph.startedAt = lv_tick_get();
    lv_anim_delete(&morph, execMorph);
    startAnim(&morph, execMorph, 0, CC_ICON_MORPH_FRAMES + 1, MORPH_MS, 0, EASE_OUT);
    ++stats.morphs;
}

// M10: the fill of the button-4 icon (slot 3) over the 1 s hold; the base icon dims meanwhile.
void holdFillStart() {
    Icon& ic = footerIcon[3];
    if (!ic.src || !holdClip) return;
    lv_image_set_src(holdFill, ic.src);
    setVisible(holdClip, true);
    holdFilling = true;
    holdMatured = false;
    if (reducedMotion) {                     // opacity only: the warm copy fades in over the hold
        tween(holdH, FOOTER_ICON, 0, 0, EASE_LINEAR, true);
        tweenFrom(holdOpa, 0, 255, HOLD_FILL_MS, 0, EASE_LINEAR);
    } else {
        tween(holdOpa, 255, 0, 0, EASE_LINEAR, true);
        tweenFrom(holdH, 0, FOOTER_ICON, HOLD_FILL_MS, 0, EASE_LINEAR);
    }
    lv_obj_set_style_image_recolor(ic.obj, lv_color_hex(HOLD_DIM_INK), 0);
    ++stats.holdFills;
}

// Early release: the fill drains in 180 ms E.in and the icon takes its ink back.
void holdFillEnd(bool drain) {
    if (!holdFilling && !holdMatured) return;
    holdFilling = false;
    holdMatured = false;
    if (reducedMotion) {
        if (drain) tween(holdOpa, 0, REDUCED_FADE_MS, 0, EASE_OUT, false);
        else tween(holdOpa, 0, 0, 0, EASE_OUT, true);
    } else if (drain) {
        tween(holdH, 0, HOLD_DRAIN_MS, 0, EASE_IN, false);
    } else {
        tween(holdH, 0, 0, 0, EASE_IN, true);
    }
    Icon& ic = footerIcon[3];
    if (ic.inkSet) lv_obj_set_style_image_recolor(ic.obj, lv_color_hex(ic.shownInk), 0);
}

// M7: the press squash (scale 0.8 x 0.86, 2 px down, 70 ms E.in); the release springs back (SPRING.pop).
// Reduced motion: the icon dims to 60 % and fades back over 160 ms.
void pressIcon(uint8_t slot, bool down) {
    FooterMotion& m = footerMotion[slot];
    if (!footerIcon[slot].src) return;
    if (reducedMotion) {
        if (down) tween(m.opa, 153, 0, 0, EASE_OUT, true);
        else tween(m.opa, 255, REDUCED_FADE_MS, 0, EASE_OUT, false);
        return;
    }
    if (down) {
        if (lv_anim_delete(m.scale.obj, execScale)) m.scale.target = 256;   // a press ends a pop in flight
        tween(m.sx, PRESS_SCALE_X, PRESS_MS, 0, EASE_IN, false);
        tween(m.sy, PRESS_SCALE_Y, PRESS_MS, 0, EASE_IN, false);
        tween(m.ty, PRESS_DROP_PX, PRESS_MS, 0, EASE_IN, false);
        ++stats.presses;
    } else {
        tween(m.sx, 256, 0, 0, SPRING_POP, false);
        tween(m.sy, 256, 0, 0, SPRING_POP, false);
        tween(m.ty, 0, 0, 0, SPRING_POP, false);
    }
}

bool playOrPause(const lv_image_dsc_t* dsc) {
    return dsc && (dsc == cc_icon("play", FOOTER_ICON) || dsc == cc_icon("pause", FOOTER_ICON));
}

// morph: a Pause <-> Play glyph change on this render is a play-state change (the same screen), not a new screen.
void renderFooter(const CCFrame& f, bool hidden, bool snap, bool inkFade, bool morphOk) {
    for (uint8_t i = 0; i < 4; ++i) {
        Icon& ic = footerIcon[i];
        const uint8_t tone = cc_button_tone(f, i);
        const lv_image_dsc_t* glyph = buttonGlyph(f, i, tone, FOOTER_ICON);
        const uint32_t ink = cc_button_ink(f, i);
        // M9: Pause <-> Play on a shown footer morphs (300 ms E.out); the ink (the paused Play's green) follows
        // 120 ms later over 220 ms. Reduced motion: the glyph swaps and the ink crossfades as before.
        if (morphOk && inkFade && !snap && !reducedMotion && ic.src && glyph != ic.src && playOrPause(ic.src) &&
            playOrPause(glyph)) {
            ic.src = glyph;
            startMorph(i, glyph == cc_icon("play", FOOTER_ICON));
            if (ic.ink != ink) {
                lv_anim_delete(&ic, execIconInk);
                ic.fadeFrom = ic.shownInk;
                ic.ink = ink;
                ++stats.inkFades;
                startAnim(&ic, execIconInk, 0, 255, MORPH_INK_MS, MORPH_INK_DELAY_MS, EASE_OUT);
            }
            markChanged();
            continue;
        }
        if (glyph != ic.src && morph.slot == static_cast<int8_t>(i)) {   // another glyph ends a morph
            lv_anim_delete(&morph, execMorph);
            morph.slot = -1;
        }
        showIcon(ic, glyph, ink, inkFade);
    }
    // M10: while the fill runs (or waits for its landing) the base button-4 icon stays dimmed.
    if ((holdFilling || holdMatured) && footerIcon[3].src) {
        lv_anim_delete(&footerIcon[3], execIconInk);
        lv_obj_set_style_image_recolor(footerIcon[3].obj, lv_color_hex(HOLD_DIM_INK), 0);
    }
    // FW-DES-003: reduced motion (r4 section 7) fades the footer and the hold tick in REDUCED_FADE_MS, no delay.
    const bool rm = reducedMotion;
    tween(footerOpa, hidden ? 0 : 255, rm ? REDUCED_FADE_MS : hidden ? 160 : 280, rm || hidden ? 0 : 140,
          hidden ? EASE_IN : EASE_OUT, snap);
    // [r3.1] the hold tick: shown with holdMarker outside the idle icon view (the footer layer fades it too).
    tween(holdTickOpa, f.holdMarker && !hidden ? 255 : 0, rm ? REDUCED_FADE_MS : HOLD_TICK_FADE_MS, 0, EASE_OUT, snap);
}

// Bilinear 2x (weights 9/3/3/1 over 16): 120 px RGB565 LE -> 240 px native RGB565.
void upscaleArt(const uint8_t* src, uint8_t* dst) {
    for (int32_t y = 0; y < 240; ++y) {
        const int32_t sy = y >> 1;
        const int32_t fy = (y & 1) ? (sy < 119 ? sy + 1 : sy) : (sy > 0 ? sy - 1 : sy);
        for (int32_t x = 0; x < 240; ++x) {
            const int32_t sx = x >> 1;
            const int32_t fx = (x & 1) ? (sx < 119 ? sx + 1 : sx) : (sx > 0 ? sx - 1 : sx);
            const uint8_t* p[4] = {src + 2 * (sy * 120 + sx), src + 2 * (sy * 120 + fx),
                                   src + 2 * (fy * 120 + sx), src + 2 * (fy * 120 + fx)};
            static const uint32_t weight[4] = {9, 3, 3, 1};
            uint32_t r = 8, g = 8, b = 8;
            for (int k = 0; k < 4; ++k) {
                const uint32_t v = static_cast<uint32_t>(p[k][0]) | (static_cast<uint32_t>(p[k][1]) << 8);
                r += weight[k] * ((v >> 11) & 31u);
                g += weight[k] * ((v >> 5) & 63u);
                b += weight[k] * (v & 31u);
            }
            const uint16_t out = static_cast<uint16_t>(((r >> 4) << 11) | ((g >> 4) << 5) | (b >> 4));
            memcpy(dst + 2 * (y * 240 + x), &out, sizeof(out));
        }
    }
}

// Re-points the image at buffer i (now the front).
void showBuffer(uint8_t i) {
    if (i != artFront) {
        artFront = i;
        lv_image_set_src(art, &artDsc[artFront]);  // re-points and invalidates the image
    } else {
        lv_obj_invalidate(art);
    }
    markChanged();
}

// Synchronous load (binaries B/C, one buffer, v1 covers): key's pixels into the front buffer --
// the back buffer when it still holds them, else the JPEG decoded into the back buffer, else the
// v1 cover upscaled into it; then front and back swap. With one buffer the shown buffer is
// written in place. False when there are no pixels for key, or when the decode failed (then
// artFailedKey is set and the store's pin released).
bool loadArt(const char* key, const uint8_t* jpeg, uint32_t jpegBytes, const uint8_t* artwork120) {
    const uint8_t back = artBuffer[1] ? static_cast<uint8_t>(1 - artFront) : artFront;
    if (back != artFront && strcmp(artKeyOf[back], key) == 0) {
        ++stats.artReuses;                       // e.g. Recent: back to the previous item
    } else if (jpeg && media.decodeCover) {
        artKeyOf[back][0] = '\0';                // partly written until the decode succeeds
        ++stats.artDecodes;
        if (!media.decodeCover(jpeg, jpegBytes, reinterpret_cast<uint16_t*>(artBuffer[back]))) {
            ++stats.artDecodeErrors;
            copyText(artFailedKey, sizeof(artFailedKey), key);
            releaseMedia(CC_DISPLAY_MEDIA_COVER);
            return false;
        }
        copyText(artKeyOf[back], sizeof(artKeyOf[back]), key);
    } else if (artwork120) {
        artKeyOf[back][0] = '\0';
        upscaleArt(artwork120, artBuffer[back]);
        ++stats.artUpscales;
        copyText(artKeyOf[back], sizeof(artKeyOf[back]), key);
    } else {
        return false;
    }
    showBuffer(back);
    return true;
}

// What the art layer can show for this frame (prepareArt -> renderArt).
enum ArtPixels : uint8_t {
    ART_OFF = 0,   // no art wanted: a layout without art, no key, no buffer (fades out, 240 ms)
    ART_MISSING,   // the key has no pixels in any store yet (hidden at once; shows when they arrive)
    ART_FAILED,    // the key's decode failed (hidden at once, no retry until the key changes)
    ART_PENDING,   // R5: the key is decoding (or waits behind another decode): nothing changes
    ART_READY      // the front buffer holds the key's pixels
};

// R5 step 5 (section 12.5.4): consume a finished decode. Only an `ok` for the frame's current key
// is swapped in; stale and aborted results are discarded; a failure of the current key hides it.
void consumeDecode(const CCFrame& f, bool wantArt) {
    if (!decode.inFlight) return;
    char key[sizeof(CCFrame::artKey)] = {};
    uint8_t result = CC_DECODE_FAILED;
    if (!media.pollCover(key, sizeof(key), &result)) return;
    decode.inFlight = false;
    decode.cancelled = false;
    const bool current = wantArt && strcmp(key, f.artKey) == 0;
    const uint8_t back = static_cast<uint8_t>(1 - artFront);
    if (result == CC_DECODE_OK && current) {
        copyText(artKeyOf[back], sizeof(artKeyOf[back]), key);
        showBuffer(back);
    } else if (result == CC_DECODE_OK) {
        ++stats.artDecodeStale;                  // artKeyOf[back] stays ""
    } else if (result == CC_DECODE_ABORTED) {
        ++stats.artDecodeAborts;
    } else {
        ++stats.artDecodeErrors;
        if (current) {
            copyText(artFailedKey, sizeof(artFailedKey), key);
            releaseMedia(CC_DISPLAY_MEDIA_COVER);
        }
    }
}

// Section 8.4 lookups: the artwork2 store before the v1 cover; a failed decode shows no art for
// that key until the frame's artKey changes (no retry loop). Runs first in cc_display_render(),
// before any animation of the render starts: a synchronous decode (up to about 150 ms on the
// knob) after a screen-change tween would cut that much off the slide (LVGL times an animation
// from lv_anim_start()). With R5 the render never decodes: it posts the request (step 1).
uint8_t prepareArt(const CCFrame& f, const uint8_t* artwork120, bool wantArt) {
    const bool async = asyncArt();
    if (async) consumeDecode(f, wantArt);
    if (artFailedKey[0] && strcmp(artFailedKey, f.artKey) != 0) artFailedKey[0] = '\0';
    if (!artBuffer[0] || !wantArt || !f.artKey[0]) {
        if (async) cancelDecode(true);           // step 6: no art wanted, nothing posted after it
        releaseMedia(CC_DISPLAY_MEDIA_COVER);
        return ART_OFF;
    }
    if (artFailedKey[0]) {
        if (async) cancelDecode(true);
        releaseMedia(CC_DISPLAY_MEDIA_COVER);
        return ART_FAILED;
    }
    // The store pins the cover while it is drawn, loaded or not.
    const uint8_t* jpeg = nullptr;
    uint32_t jpegBytes = 0;
    if (media.decodeCover || async) adoptMedia(CC_DISPLAY_MEDIA_COVER, f.artKey, &jpeg, &jpegBytes);
    // Pixels already in the front buffer are shown as they are, whether or not a store still holds
    // the key: keys are content hashes, so they are exact.
    if (strcmp(artKeyOf[artFront], f.artKey) == 0) {
        if (async && decode.inFlight) cancelDecode(strcmp(decode.key, f.artKey) != 0);
        return ART_READY;
    }
    if (!async) {
        if (loadArt(f.artKey, jpeg, jpegBytes, artwork120)) return ART_READY;
        return artFailedKey[0] ? ART_FAILED : ART_MISSING;
    }
    if (decode.inFlight) {
        // Step 4: the running key is the frame's again (a spin back) -> it continues; another key
        // waits as the frame's current key (newest wins: nothing is queued) and is posted when the
        // running decode's result has been consumed.
        const bool same = strcmp(decode.key, f.artKey) == 0;
        cancelDecode(!same);
        return same || jpeg || artwork120 ? ART_PENDING : ART_MISSING;
    }
    const uint8_t back = static_cast<uint8_t>(1 - artFront);
    if (strcmp(artKeyOf[back], f.artKey) == 0) {
        ++stats.artReuses;
        showBuffer(back);
        return ART_READY;
    }
    if (jpeg) {
        // Step 1: post; the back buffer belongs to the decoder until its result is consumed.
        artKeyOf[back][0] = '\0';
        if (media.requestCover(f.artKey, jpeg, jpegBytes, reinterpret_cast<uint16_t*>(artBuffer[back]))) {
            decode.inFlight = true;
            decode.cancelled = false;
            copyText(decode.key, sizeof(decode.key), f.artKey);
            ++stats.artDecodeRequests;
            return ART_PENDING;
        }
    }
    if (loadArt(f.artKey, jpeg, jpegBytes, artwork120)) return ART_READY;   // v1 upscale (or a refused post)
    return artFailedKey[0] ? ART_FAILED : ART_MISSING;
}

void artHideNow() {
    if (lv_anim_delete(art, execOpa)) markChanged();
    artOpa.set = true;
    artOpa.target = 0;
    if (lv_obj_get_style_opa(art, 0) != 0) {
        execOpa(art, 0);
        markChanged();
    }
    setVisible(art, false);
}

// Section 8.4 motion: a key change over a visible cover swaps instantly (prepareArt re-pointed the
// image; the opacity target stays 255); show and hide fade over 240 ms OUT; a key without pixels
// (or whose decode failed) hides at once and never shows the previous cover; a pending decode
// keeps whatever is shown. snap: the first render after the host screen appears.
void renderArt(const CCFrame& f, uint8_t pixels, bool snap) {
    switch (pixels) {
        case ART_OFF:
            tween(artOpa, 0, ART_FADE_MS, 0, EASE_OUT, snap);
            return;
        case ART_MISSING:
        case ART_FAILED:
            artHideNow();
            return;
        case ART_PENDING:
            return;
        default:
            break;
    }
    const uint8_t imageOpa = cc_art_image_opa(f);        // artDim 112, [r3.1] paused Home / Music 143, else 255
    if (imageOpa != artImageOpa) {
        artImageOpa = imageOpa;
        lv_obj_set_style_image_opa(art, imageOpa, 0);
        markChanged();
    }
    setVisible(art, true);
    tween(artOpa, 255, ART_FADE_MS, 0, EASE_OUT, snap);
}

// An RGB565 image descriptor over caller or static pixels.
void describeImage(lv_image_dsc_t& dsc, const uint8_t* pixels, uint32_t side) {
    memset(&dsc, 0, sizeof(dsc));
    dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
    dsc.header.cf = LV_COLOR_FORMAT_RGB565;
    dsc.header.w = side;
    dsc.header.h = side;
    dsc.header.stride = 2 * side;
    dsc.data_size = 2 * side * side;
    dsc.data = pixels;
}

void describeArt(uint8_t i) {
    describeImage(artDsc[i], artBuffer[i], 240);
    artKeyOf[i][0] = '\0';
}

// Points the art image at the front buffer (cleared to black).
void attachArt() {
    for (uint8_t i = 0; i < 2; ++i)
        if (artBuffer[i]) describeArt(i);
    artFront = 0;
    memset(artBuffer[0], 0, CC_ART240_BYTES);
    lv_image_set_src(art, &artDsc[0]);
}

// Every label with a twin: the twin follows its label's visibility while twinsOn, hidden otherwise.
void refreshTwins() {
    Label* const withTwin[] = {&heading, &homeTitle, &homeArtist, &volumeCaption, &digits, &percent, &listTitle,
                               &listSub, &tracksTitle, &tracksSub, &seekCaption, &seekTime, &sceneTitle};
    for (size_t i = 0; i < sizeof(withTwin) / sizeof(withTwin[0]); ++i) {
        Label& l = *withTwin[i];
        if (l.twin) setVisible(l.twin, twinsOn && !lv_obj_has_flag(l.obj, LV_OBJ_FLAG_HIDDEN));
    }
}

// Shows exactly one content layer (the offline layer included).
void showLayers(uint8_t layout, bool homeish, bool off) {
    setVisible(homeLayer.obj, !off && homeish);          // homeish: Home, or presentation 6 lights / lightsbig
    setVisible(listLayer.obj, !off && (layout == CC_LAYOUT_RECENT || layout == CC_LAYOUT_NOTICE ||
                                       layout == CC_LAYOUT_EXPLORER || layout == CC_LAYOUT_UPNEXT));
    setVisible(tracksLayer.obj, !off && layout == CC_LAYOUT_TRACKS);
    setVisible(seekLayer.obj, !off && layout == CC_LAYOUT_SEEK);
    setVisible(windowsLayer.obj, !off && layout == CC_LAYOUT_WINDOWS);
    setVisible(scenesLayer.obj, !off && layout == CC_LAYOUT_SCENES);
    setVisible(offlineLayer.obj, off);
}

bool layerVisible(const Layer& layer) { return !lv_obj_has_flag(layer.obj, LV_OBJ_FLAG_HIDDEN); }

}  // namespace

void cc_display_set_media(const CCDisplayMedia& lookups) { media = lookups; }

void cc_display_release_media() {
    releaseMedia(CC_DISPLAY_MEDIA_COVER);
    releaseMedia(CC_DISPLAY_MEDIA_ICON);
    if (media.cancelCover) cancelDecode(true);
    // The next claim starts from rest: its first render snaps, without the latched reduced motion.
    view.rendered = false;
    reducedMotion = false;
    if (offline && screen) {
        offline = false;
        offlinePinsHeld = false;
        setVisible(offlineLayer.obj, false);
    }
}

lv_obj_t* cc_display_create(uint8_t* art240Front, uint8_t* art240Back) {
    if (!art240Front) {                      // one buffer: it is the front
        art240Front = art240Back;
        art240Back = nullptr;
    }
    if (art240Back == art240Front) art240Back = nullptr;
    const bool attach = art240Front && !artBuffer[0];
    if (attach) {
        artBuffer[0] = art240Front;
        artBuffer[1] = art240Back;
    } else if (artBuffer[0] && !artBuffer[1] && art240Back && art240Back != artBuffer[0]) {
        artBuffer[1] = art240Back;           // a back buffer that became available later
        describeArt(1);
    }
    if (screen) {
        if (attach) attachArt();  // buffers that became available after the tree
        return screen;
    }
    screen = lv_obj_create(nullptr);
    lv_obj_remove_style_all(screen);
    lv_obj_set_size(screen, 240, 240);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_hex(CCInk::background), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    tag(screen, "screen");

    stage = makeBox(screen, 0, 0, 240, 240, "stage");
    art = lv_image_create(stage);
    lv_obj_remove_style_all(art);
    lv_obj_set_pos(art, 0, 0);
    lv_obj_set_size(art, 240, 240);
    lv_obj_add_flag(art, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_opa(art, 0, 0);
    tag(art, "art");
    if (artBuffer[0]) attachArt();

    makeLayer(content, stage, 0, 0, CONTENT_BOX, "content");
    makeLabel(heading, content, HEADING, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "heading", "heading.twin",
              static_cast<int16_t>(HEADING_R), HEADING_TRACKING);
    applyInk(heading, CCInk::context);

    makeLayer(homeLayer, content, HOME_BOX, "home");
    makeLayer(trackLayer, homeLayer, TRACK_BOX, "track");
    makeLabel(homeTitle, trackLayer, HOME_TITLE, &cc_font_22, 2, LV_TEXT_ALIGN_CENTER, "home.title", "home.title.twin");
    makeLabel(homeArtist, trackLayer, HOME_ARTIST, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "home.artist",
              "home.artist.twin");
    makeLayer(volumeLayer, homeLayer, VOLUME_BOX, "volume");
    makeLabel(volumeCaption, volumeLayer, VOL_CAPTION, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "volume.caption",
              "volume.caption.twin");
    const Box digitsBox = {0, DIGITS_Y, 120, CC_FONT_48_LINE_HEIGHT};
    makeLabel(digits, volumeLayer, digitsBox, &cc_font_48, 1, LV_TEXT_ALIGN_LEFT, "volume.digits",
              "volume.digits.twin", static_cast<int16_t>(SAFE_R), DIGITS_TRACKING);
    const Box percentBox = {0, PERCENT_Y, 40, CC_FONT_22_LINE_HEIGHT};
    makeLabel(percent, volumeLayer, percentBox, &cc_font_22, 1, LV_TEXT_ALIGN_LEFT, "volume.percent",
              "volume.percent.twin");
    applyInk(digits, CCInk::text);
    applyInk(percent, CCInk::context);
    lv_obj_set_style_opa(volumeLayer.obj, 0, 0);
    lv_obj_set_style_translate_y(volumeLayer.obj, GLIDE_PX, 0);   // r4 M2: the big value enters from 14 px below
    makeLabel(status, homeLayer, STATUS, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "status");
    for (uint8_t i = 0; i < 4; ++i) {
        const Box column = {static_cast<int16_t>(IDLE_CX[i] - IDLE_COLUMN_W / 2), IDLE_Y, IDLE_COLUMN_W,
                            static_cast<int16_t>(IDLE_WORD_DY + CC_FONT_12_LINE_HEIGHT)};
        Layer col;
        makeLayer(col, homeLayer, column, "idle.item");
        idleColumn[i] = col.obj;
        makeIcon(idleIcon[i], col, column.x + (IDLE_COLUMN_W - IDLE_ICON) / 2, IDLE_Y, IDLE_ICON, "idle.icon");
        const Box word = {column.x, static_cast<int16_t>(IDLE_Y + IDLE_WORD_DY), IDLE_COLUMN_W, CC_FONT_12_LINE_HEIGHT};
        makeLabel(idleWord[i], col, word, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "idle.word");
        lv_obj_set_style_opa(col.obj, 0, 0);
        lv_obj_set_style_translate_y(col.obj, IDLE_RISE_PX, 0);
        initTween(idleOpa[i], col.obj, PROP_OPA, 0);
        initTween(idleTy[i], col.obj, PROP_TY, IDLE_RISE_PX);
        // r4 M11: the icon's own scale (85 % at rest outside the idle view), pivot at its centre.
        lv_image_set_pivot(idleIcon[i].obj, IDLE_ICON / 2, IDLE_ICON / 2);
        lv_image_set_scale(idleIcon[i].obj, IDLE_SCALE);
        initTween(idleScale[i], idleIcon[i].obj, PROP_SCALE, IDLE_SCALE);
    }

    makeLayer(listLayer, content, LIST_BOX, "list");
    makeLabel(listTitle, listLayer, LIST_TITLE, &cc_font_22, 2, LV_TEXT_ALIGN_CENTER, "list.title", "list.title.twin");
    listTitle.crumbClear = true;             // FW-DES-001
    makeLabel(listSub, listLayer, LIST_SUB, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "list.subtitle",
              "list.subtitle.twin");
    makeLabel(listMeta, listLayer, LIST_META, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "list.meta");

    makeLayer(tracksLayer, content, TRACKS_BOX, "tracks");
    makeLabel(tracksTitle, tracksLayer, TRACKS_TITLE, &cc_font_22, 1, LV_TEXT_ALIGN_CENTER, "tracks.title",
              "tracks.title.twin");
    for (uint8_t i = 0; i < 3; ++i)
        makeIcon(positionIcon[i], tracksLayer, TRACKS_POS_X[i], TRACKS_POS_Y, POS_ICON, "tracks.position");
    makeLabel(tracksSub, tracksLayer, TRACKS_SUB, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "tracks.subtitle",
              "tracks.subtitle.twin");
    makeLabel(tracksMeta, tracksLayer, TRACKS_META, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "tracks.meta");

    makeLayer(seekLayer, content, SEEK_BOX, "seek");
    makeLabel(seekCaption, seekLayer, SEEK_CAPTION, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "seek.caption",
              "seek.caption.twin");
    makeLabel(seekTime, seekLayer, SEEK_TIME, &cc_font_48t, 1, LV_TEXT_ALIGN_CENTER, "seek.time", "seek.time.twin",
              static_cast<int16_t>(SAFE_R), DIGITS_TRACKING);
    makeLabel(seekLine, seekLayer, SEEK_LINE, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "seek.line");

    makeLayer(windowsLayer, content, WINDOWS_BOX, "windows");
    Layer tileLayer;
    makeLayer(tileLayer, windowsLayer, TILE, "windows.tile");
    tile = tileLayer.obj;
    lv_obj_set_style_bg_color(tile, lv_color_hex(CCInk::tile), 0);
    lv_obj_set_style_bg_opa(tile, LV_OPA_COVER, 0);
    const Box letterBox = {TILE.x, static_cast<int16_t>(TILE.y + TILE_LETTER_Y), TILE.w, CC_FONT_16_LINE_HEIGHT};
    makeLabel(tileLetter, tileLayer, letterBox, &cc_font_16, 1, LV_TEXT_ALIGN_CENTER, "windows.letter");
    // artwork2 app icon: a 32x32 RGB565 image filling the tile, drawn as is (no recolour), above
    // the letter; hidden until the store has the key.
    tileIcon = lv_image_create(tile);
    lv_obj_remove_style_all(tileIcon);
    lv_obj_set_pos(tileIcon, 0, 0);
    lv_obj_set_size(tileIcon, TILE.w, TILE.h);
    lv_obj_set_style_image_recolor_opa(tileIcon, LV_OPA_TRANSP, 0);
    describeImage(iconDsc, iconPixels, 32);
    lv_image_set_src(tileIcon, &iconDsc);
    lv_obj_add_flag(tileIcon, LV_OBJ_FLAG_HIDDEN);
    tag(tileIcon, "windows.icon");
    makeLabel(winApp, windowsLayer, WIN_APP, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "windows.app");
    makeLabel(winTitle, windowsLayer, WIN_TITLE, &cc_font_16, 2, LV_TEXT_ALIGN_CENTER, "windows.title");
    makeLabel(winMeta, windowsLayer, WIN_META, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "windows.meta");

    // Presentation 6 scenes list (section 19.4): one twin, on the current scene (like the lists' title).
    makeLayer(scenesLayer, content, SCENES_BOX, "scenes");
    makeLabel(scenePrev, scenesLayer, SCENE_PREV, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "scenes.prev");
    makeLabel(sceneTitle, scenesLayer, SCENE_TITLE, &cc_font_22, 1, LV_TEXT_ALIGN_CENTER, "scenes.title",
              "scenes.title.twin");
    makeLabel(sceneNext, scenesLayer, SCENE_NEXT, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "scenes.next");
    makeLabel(sceneMeta, scenesLayer, SCENE_META, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "scenes.meta");

    makeLayer(offlineLayer, content, OFFLINE_BOX, "offline");
    makeLabel(offTitle, offlineLayer, OFF_TITLE, &cc_font_22, 1, LV_TEXT_ALIGN_CENTER, "offline.title");
    makeLabel(offSub, offlineLayer, OFF_SUB, &cc_font_14, 2, LV_TEXT_ALIGN_CENTER, "offline.subtitle");

    // Presentation 6 (section 19.9): the arc breadcrumb, above the content and never sliding.
    // r4 M15: two slots (an outgoing and an incoming crumb crossfade).
    static const char* const crumbRoles[2] = {"crumb.ancestors", "crumb.current"};
    for (uint8_t k = 0; k < 4; ++k) {
        const uint8_t part = static_cast<uint8_t>(k & 1);
        crumbImg[k] = lv_image_create(stage);
        lv_obj_remove_style_all(crumbImg[k]);
        lv_obj_set_style_image_recolor_opa(crumbImg[k], LV_OPA_COVER, 0);
        lv_obj_set_style_image_recolor(crumbImg[k], lv_color_hex(part ? CC_CRUMB_CURRENT_INK : CC_CRUMB_ANCESTOR_INK), 0);
        lv_obj_set_style_opa(crumbImg[k], 0, 0);
        lv_obj_add_flag(crumbImg[k], LV_OBJ_FLAG_HIDDEN);
        tag(crumbImg[k], crumbRoles[part]);
    }

    makeLayer(footerLayer, stage, 0, 0, FOOTER_BOX, "footer");
    for (uint8_t i = 0; i < 4; ++i)
        makeIcon(footerIcon[i], footerLayer, FOOTER_CX[i] - FOOTER_ICON / 2, FOOTER_Y, FOOTER_ICON, "footer.icon");
    // r4 M10: the hold fill over the button-4 icon: a clip box (bottom-anchored, height 0 at rest) holding a warm
    // copy of the icon's own mask; drawn above the base icon.
    holdClip = makeBox(footerLayer.obj, FOOTER_CX[3] - FOOTER_ICON / 2 - footerLayer.x, FOOTER_Y + FOOTER_ICON - footerLayer.y,
                       FOOTER_ICON, 0, "footer.holdfill");
    lv_obj_add_flag(holdClip, LV_OBJ_FLAG_HIDDEN);
    holdFill = lv_image_create(holdClip);
    lv_obj_remove_style_all(holdFill);
    lv_obj_set_pos(holdFill, 0, -FOOTER_ICON);
    lv_obj_set_size(holdFill, FOOTER_ICON, FOOTER_ICON);
    lv_obj_set_style_image_recolor_opa(holdFill, LV_OPA_COVER, 0);
    lv_obj_set_style_image_recolor(holdFill, lv_color_hex(HOLD_FILL_INK), 0);
    tag(holdFill, "footer.holdfill.icon");
    for (uint8_t i = 0; i < 4; ++i) {
        // r4 M7 / M8: the icon's own scale about its centre, and a 2 px drop.
        lv_image_set_pivot(footerIcon[i].obj, FOOTER_ICON / 2, FOOTER_ICON / 2);
        FooterMotion& m = footerMotion[i];
        memset(&m, 0, sizeof(m));
        initTween(m.sx, footerIcon[i].obj, PROP_SCALE_X, 256);
        initTween(m.scale, footerIcon[i].obj, PROP_SCALE, 256);
        initTween(m.sy, footerIcon[i].obj, PROP_SCALE_Y, 256);
        initTween(m.ty, footerIcon[i].obj, PROP_TY, 0);
        initTween(m.opa, footerIcon[i].obj, PROP_OPA, 255);
    }
    holdTick = makeBox(footerLayer.obj, HOLD_TICK.x - footerLayer.x, HOLD_TICK.y - footerLayer.y, HOLD_TICK.w,
                       HOLD_TICK.h, "footer.tick");
    lv_obj_set_style_bg_color(holdTick, lv_color_hex(CCInk::context), 0);
    lv_obj_set_style_bg_opa(holdTick, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(holdTick, 1, 0);
    lv_obj_set_style_opa(holdTick, 0, 0);

    const Layer* const layers[] = {&homeLayer, &listLayer, &tracksLayer, &seekLayer, &windowsLayer, &scenesLayer,
                                   &offlineLayer};
    for (size_t i = 0; i < sizeof(layers) / sizeof(layers[0]); ++i) lv_obj_add_flag(layers[i]->obj, LV_OBJ_FLAG_HIDDEN);

    initTween(trackOpa, trackLayer.obj, PROP_OPA, 255);
    initTween(trackTy, trackLayer.obj, PROP_TY, 0);
    initTween(volumeOpa, volumeLayer.obj, PROP_OPA, 0);
    initTween(volumeTy, volumeLayer.obj, PROP_TY, GLIDE_PX);
    initTween(statusOpa, status.obj, PROP_OPA, 255);
    initTween(footerOpa, footerLayer.obj, PROP_OPA, 255);
    initTween(holdTickOpa, holdTick, PROP_OPA, 0);
    initTween(artOpa, art, PROP_OPA, 0);
    initTween(contentTx, content.obj, PROP_TX, 0);
    initTween(contentOpa, content.obj, PROP_OPA, 255);
    initTween(listMetaOpa, listMeta.obj, PROP_OPA, 255);
    initTween(tracksMetaOpa, tracksMeta.obj, PROP_OPA, 255);
    initTween(winMetaOpa, winMeta.obj, PROP_OPA, 255);
    initTween(offSubOpa, offSub.obj, PROP_OPA, 255);
    initTween(sceneMetaOpa, sceneMeta.obj, PROP_OPA, 255);
    for (uint8_t k = 0; k < 4; ++k) initTween(crumbOpa[k], crumbImg[k], PROP_OPA, 0);
    initTween(statusTy, status.obj, PROP_TY, 0);
    initTween(listMetaTy, listMeta.obj, PROP_TY, 0);
    initTween(tracksMetaTy, tracksMeta.obj, PROP_TY, 0);
    initTween(winMetaTy, winMeta.obj, PROP_TY, 0);
    initTween(sceneMetaTy, sceneMeta.obj, PROP_TY, 0);
    initTween(holdH, holdClip, PROP_HEIGHT, 0);
    initTween(holdOpa, holdClip, PROP_OPA, 255);
    initGlide(GLIDE_CONTENT, content.obj, PROP_TY);
    initGlide(GLIDE_TRACK, trackLayer.obj, PROP_TY);
    initGlide(GLIDE_LIST, listLayer.obj, PROP_TY);
    initGlide(GLIDE_TRACKS, tracksLayer.obj, PROP_TY);
    initGlide(GLIDE_SCENES, scenesLayer.obj, PROP_TY);
    initGlide(GLIDE_WINDOWS, windowsLayer.obj, PROP_TY);
    // Render speed: A8 masks straight from flash (a decoder at the head of LVGL's list, tried first).
    if (!a8Decoder) {
        a8Decoder = lv_image_decoder_create();
        lv_image_decoder_set_info_cb(a8Decoder, a8Info);
        lv_image_decoder_set_open_cb(a8Decoder, a8Open);
        lv_image_decoder_set_close_cb(a8Decoder, a8Close);
    }
    return screen;
}

void cc_display_render(const CCFrame& frame, const uint8_t* artwork120) {
    if (!screen) cc_display_create(artBuffer[0], artBuffer[1]);
    ++stats.renders;
    changed = false;
    animated = false;
    stats.lastSlide = 0;
    stats.lastScreenChange = false;
    // Section 7.1: latched on acceptance; reset at every claim (release/offline, above). A frame
    // without the field keeps the latch. Every animation started from here on follows it.
    if (frame.reducedMotionPresent) reducedMotion = frame.reducedMotion;

    const uint8_t layout = frame.layoutId <= CC_LAYOUT_SCENES ? frame.layoutId
                                                              : static_cast<uint8_t>(CC_LAYOUT_NOW_PLAYING);
    // Presentation 6: lights / lightsbig use the home layer (lightsbig is its reveal); never the idle row.
    const bool lights = layout == CC_LAYOUT_LIGHTS || layout == CC_LAYOUT_LIGHTSBIG;
    const bool volume = layout == CC_LAYOUT_VOLUME || layout == CC_LAYOUT_LIGHTSBIG;
    const bool homeish = layout == CC_LAYOUT_NOW_PLAYING || volume || layout == CC_LAYOUT_IDLE || lights;
    const bool idle = homeish && !lights &&
                      (layout == CC_LAYOUT_IDLE || (volume && frame.restLayout == CC_LAYOUT_IDLE));
    const bool row = idle && !volume;
    const uint8_t group = groupOf(layout);
    const uint8_t page = group == GROUP_RECENT || group == GROUP_EXPLORER ? frame.page : 0;
    const bool first = !view.rendered;
    const bool fromOffline = offline;
    if (fromOffline) {
        offline = false;
        offlinePinsHeld = false;
    }
    // Section 8.4 "where art shows" (idle and a reveal over idle fade it out).
    const bool wantArt = !idle && (layout == CC_LAYOUT_NOW_PLAYING || layout == CC_LAYOUT_VOLUME ||
                                   layout == CC_LAYOUT_RECENT ||
                                   layout == CC_LAYOUT_TRACKS || layout == CC_LAYOUT_SEEK ||
                                   layout == CC_LAYOUT_EXPLORER || layout == CC_LAYOUT_UPNEXT);
    // Cover lookup (and a synchronous decode) first, before this render starts any animation.
    const uint8_t artPixels = prepareArt(frame, artwork120, wantArt);

    // Screen change (section 8.7): only when (group, page') changes -- never on a control-id
    // change, a Home layout change, a detent, Seek on/off or a heartbeat. From the offline layer:
    // a fade, never a slide.
    bool screenChange = false;
    // FW-DES-004: Recently Added's source toggle (button 3: Recent <-> Playlists, same group and page) is not a
    // screen change: the crumb crossfades (showCrumb, M15) and the labels change in place, as the r4 tour
    // (tick + feel.fade) and the r3.1 prototype (M1 keyed on the space / depth only) show. Not a detent either.
    const bool sourceToggle = !first && group == view.group && page == view.page && frame.crumb != view.crumb &&
                              (frame.crumb == CC_CRUMB_RECENT || frame.crumb == CC_CRUMB_PLAYLISTS) &&
                              (view.crumb == CC_CRUMB_RECENT || view.crumb == CC_CRUMB_PLAYLISTS);
    if (first || fromOffline) {
        glideRest();                         // a claim or a return starts from rest (no bounce carried over)
        for (uint8_t i = 0; i < 4; ++i) {
            tween(footerMotion[i].scale, 256, 0, 0, EASE_OUT, true);
            tween(footerMotion[i].sx, 256, 0, 0, EASE_OUT, true);
            tween(footerMotion[i].sy, 256, 0, 0, EASE_OUT, true);
            tween(footerMotion[i].ty, 0, 0, 0, EASE_OUT, true);
            tween(footerMotion[i].opa, 255, 0, 0, EASE_OUT, true);
        }
        holdFillEnd(false);
    }
    if (first) {
        tween(contentTx, 0, 0, 0, EASE_OUT, true);
        tween(contentOpa, 255, 0, 0, EASE_OUT, true);
    } else if (fromOffline) {
        tween(contentTx, 0, 0, 0, EASE_OUT, true);
        tweenFrom(contentOpa, 0, 255, OFFLINE_FADE_MS, 0, EASE_OUT);
        screenChange = true;
    } else if (group != view.group || page != view.page || (frame.crumb != view.crumb && !sourceToggle)) {
        // Presentation 6: a crumb change is a screen change too (the launcher -> Music slides, README r3 4).
        // r4 M1: the new content enters from 28 px in the depth direction (deeper = from the right) and springs to
        // 0 (SPRING.snap, 416 ms); opacity 0 -> 1 in 240 ms E.out; the old content is replaced on this frame.
        // Reduced motion: a 160 ms opacity crossfade only.
        const int32_t dir = screenDepth(group, page, frame.crumb) >= screenDepth(view.group, view.page, view.crumb)
                                ? SLIDE_PX : -SLIDE_PX;
        if (reducedMotion) {
            tween(contentTx, 0, 0, 0, EASE_OUT, true);
            tweenFrom(contentOpa, 0, 255, REDUCED_FADE_MS, 0, EASE_OUT);
        } else {
            tweenFrom(contentTx, dir, 0, 0, 0, SPRING_SNAP);
            tweenFrom(contentOpa, 0, 255, CONTENT_FADE_MS, 0, EASE_OUT);
        }
        glideStop(content.obj, PROP_TY);     // a wall bounce in flight ends with the old screen
        execTy(content.obj, 0);
        glides[GLIDE_CONTENT].shown = 0;
        ++stats.slides;
        stats.lastSlide = reducedMotion ? 0 : dir;
        screenChange = true;
    }
    stats.lastScreenChange = screenChange;

    // Presentation 6 (section 19.9): a crumb replaces the flat heading. r3.1 (2026-09-29): the crumb shows in
    // the idle icon view too (Music idle keeps MUSIC; Home idle is sent without one), as the r3.1 prototype.
    showHeading(heading, frame.crumb != CC_CRUMB_NONE ? "" : frame.heading);
    showCrumb(frame.crumb, first || fromOffline);
    const bool wasVisible[6] = {layerVisible(homeLayer), layerVisible(listLayer), layerVisible(tracksLayer),
                                layerVisible(seekLayer), layerVisible(windowsLayer), layerVisible(scenesLayer)};
    showLayers(layout, homeish, false);
    // A line fades at rest only when its layer was already on screen and the screen did not change.
    const bool rest = !first && !screenChange;
    const bool inkFade = !first && !fromOffline;
    // r4 M4: a detent on the same list screen (the selected entry of an index ring moved): the rows jump 14 px in
    // the turn direction on this frame and spring back (SPRING.snap) while the labels already show the new item.
    // A fast spin re-jumps the running glide (never queued). Reduced motion: nothing moves.
    int8_t glideSlot = -1;
    if (layout == CC_LAYOUT_SCENES) glideSlot = GLIDE_SCENES;
    else if (layout == CC_LAYOUT_TRACKS) glideSlot = GLIDE_TRACKS;
    else if (layout == CC_LAYOUT_WINDOWS) glideSlot = GLIDE_WINDOWS;
    else if (layout == CC_LAYOUT_RECENT || layout == CC_LAYOUT_EXPLORER || layout == CC_LAYOUT_UPNEXT) glideSlot = GLIDE_LIST;
    const bool indexRing = frame.ringStyle == CC_RING_SELECTION || frame.ringStyle == CC_RING_QUEUE ||
                           frame.ringStyle == CC_RING_MARKER || frame.ringStyle == CC_RING_CLUSTERS ||
                           frame.ringStyle == CC_RING_TRANSPORT;
    const bool glide = rest && !sourceToggle && glideSlot >= 0 && layout == view.layout && indexRing &&
                       frame.ringStyle == view.ringStyle && frame.ringIndex != view.ringIndex;
    if (glide && !reducedMotion)
        glideJump(static_cast<uint8_t>(glideSlot), frame.ringIndex > view.ringIndex ? GLIDE_PX : -GLIDE_PX, SPRING_SNAP);
    // Layers that were not on screen appear at their final state (the screen change provides the
    // motion), exactly like freshly created design nodes.
    if (homeish) {
        // A Home <-> Lights screen change (same layer, another group) snaps the layer's own tweens: the
        // content slide is the motion, as for a layer that just appeared.
        const bool textWasAtRest = rest && wasVisible[0] && view.homeish && !view.row && view.layout != CC_LAYOUT_VOLUME &&
                                   view.layout != CC_LAYOUT_LIGHTSBIG;
        renderHome(frame, volume, idle, first || !view.homeish || fromOffline || screenChange,
                   rest && wasVisible[0] && !view.row, inkFade && view.row && row, lights, textWasAtRest);
    } else if (layout == CC_LAYOUT_SCENES) {
        renderScenes(frame, rest && wasVisible[5] && !glide);
    } else if (layout == CC_LAYOUT_TRACKS) {
        renderTracks(frame, rest && wasVisible[2] && !glide);
    } else if (layout == CC_LAYOUT_SEEK) {
        renderSeek(frame);
    } else if (layout == CC_LAYOUT_WINDOWS) {
        renderWindows(frame, rest && wasVisible[4] && !glide);
    } else {
        renderList(frame, rest && wasVisible[1] && !glide);
    }
    if (layout != CC_LAYOUT_WINDOWS) releaseMedia(CC_DISPLAY_MEDIA_ICON);  // icons: Windows tile only
    renderFooter(frame, idle, first, inkFade && view.footerShown && !idle, rest);
    renderArt(frame, artPixels, first);
    // Render speed: the shadow twins only while the cover's target is on (over black they draw nothing). The switch
    // happens in the render that shows or hides the cover, so it follows the frame and identical frames stay inert;
    // during a 240 ms cover fade-out the labels lose their 1 px shadow at its start.
    const bool artShows = !lv_obj_has_flag(art, LV_OBJ_FLAG_HIDDEN) && artOpa.target > 0;
    if (artShows != twinsOn) {
        twinsOn = artShows;
        refreshTwins();
    }

    // r4 M8: the landing pop. A Play / Pause state change (playing flips on the same Home / Music screen) pops the
    // Play / Pause icon; a hold of button 4 that matured lands with the first new feedback (ok) within 1.5 s.
    if (rest && frame.playing >= 0 && view.playing >= 0 && frame.playing != view.playing && !idle) {
        const int8_t slot = playSlot(frame);
        if (slot >= 0) popIcon(static_cast<uint8_t>(slot));
    }
    const bool newFeedback = frame.feedbackPresent && frame.feedbackSeq != view.feedbackSeq;
    if (newFeedback && frame.feedbackKind == CC_FEEDBACK_OK && (holdMatured || holdFilling)) {
        const uint32_t now = lv_tick_get();
        const bool matured = holdMatured ? now - holdMaturedAt <= HOLD_LANDING_WINDOW_MS
                                         : footerMotion[3].down && now - footerMotion[3].downAt >= HOLD_FILL_MS;
        if (matured) {
            holdFillEnd(false);
            if (!idle) popIcon(3);
            ++stats.landings;
        }
    }

    view.rendered = true;
    view.group = group;
    view.page = page;
    view.crumb = frame.crumb;
    view.layout = layout;
    view.homeish = homeish;
    view.row = row;
    view.footerShown = !idle;
    view.ringStyle = frame.ringStyle;
    view.ringIndex = frame.ringIndex;
    view.playing = frame.playing;
    view.holdMarker = frame.holdMarker;
    if (frame.feedbackPresent) view.feedbackSeq = frame.feedbackSeq;
    stats.lastChanged = changed;
    stats.lastAnimated = animated;
}

void cc_display_offline(bool nativeInput) {
    if (!screen) return;
    changed = false;
    animated = false;
    stats.lastSlide = 0;
    stats.lastScreenChange = false;
    if (!offline) {
        offline = true;
        offlineNative = nativeInput;
        offlinePinsHeld = true;
        offlineAt = lv_tick_get();
        reducedMotion = false;               // the session ended (lease expiry); the next claim sets it
        if (media.cancelCover) cancelDecode(true);
        setLabelVisible(heading, false);
        showCrumb(CC_CRUMB_NONE, true);
        showLayers(CC_LAYOUT_NOW_PLAYING, false, true);
        showText(offTitle, OFFLINE_TITLE);
        applyInk(offTitle, CCInk::text);
        showOfflineSub(nativeInput ? OFFLINE_NATIVE : OFFLINE_SUB, nativeInput);
        applyInk(offSub, CCInk::context);
        tween(offSubOpa, 255, 0, 0, EASE_OUT, true);
        tween(contentTx, 0, 0, 0, EASE_OUT, true);
        glideRest();
        holdFillEnd(false);
        tweenFrom(contentOpa, 0, 255, OFFLINE_FADE_MS, 0, EASE_OUT);
        tween(footerOpa, 0, 160, 0, EASE_IN, false);
        tween(artOpa, 0, ART_FADE_MS, 0, EASE_OUT, false);
        // The next render sees a group change from offline (never a slide).
        view.group = GROUP_OFFLINE;
        view.page = 0;
        view.crumb = CC_CRUMB_NONE;
        view.homeish = false;
        view.row = false;
        view.footerShown = false;
        stats.lastScreenChange = true;
    } else if (nativeInput && !offlineNative) {
        offlineNative = true;
        showOfflineSub(OFFLINE_NATIVE, true);
        tweenFrom(offSubOpa, 0, 255, LINE_FADE_MS, 0, EASE_OUT);
        ++stats.lineFades;
    }
    // AW2 4.4: both display pins are released once the cover has faded out.
    if (offlinePinsHeld && lv_tick_elaps(offlineAt) >= ART_FADE_MS) {
        offlinePinsHeld = false;
        releaseMedia(CC_DISPLAY_MEDIA_COVER);
        releaseMedia(CC_DISPLAY_MEDIA_ICON);
    }
    stats.lastChanged = changed;
    stats.lastAnimated = animated;
}

bool cc_display_offline_shown() { return offline; }

void cc_display_input(uint8_t keys) {
    if (!screen) return;
    keys &= 0x0F;
    const uint32_t now = lv_tick_get();
    const bool footerUp = view.rendered && !offline && view.footerShown;
    const uint8_t edges = static_cast<uint8_t>(keys ^ keysDown);
    for (uint8_t i = 0; i < 4 && edges; ++i) {
        if (!(edges & (1u << i))) continue;
        FooterMotion& m = footerMotion[i];
        const bool down = (keys & (1u << i)) != 0;
        m.down = down;
        if (down) m.downAt = now;
        if (footerUp) pressIcon(i, down);                       // M7 (the release springs back)
        if (i == 3) {
            if (down && footerUp && view.holdMarker && footerIcon[3].src) holdFillStart();   // M10
            else if (!down && holdFilling && now - m.downAt < HOLD_FILL_MS) holdFillEnd(true);   // early release
        }
    }
    keysDown = keys;
    // M10: the fill completes at 1000 ms and waits for its landing (a new feedback, cc_display_render) at most
    // HOLD_LANDING_WINDOW_MS; without one it drains.
    if (holdFilling && footerMotion[3].down && now - footerMotion[3].downAt >= HOLD_FILL_MS) {
        holdFilling = false;
        holdMatured = true;
        holdMaturedAt = now;
    } else if (holdFilling && !footerMotion[3].down) {
        holdFilling = false;
        holdMatured = true;
        holdMaturedAt = now;
    }
    if (holdMatured && now - holdMaturedAt > HOLD_LANDING_WINDOW_MS) holdFillEnd(true);
}

void cc_display_wall(int8_t dir) {
    ++stats.walls;
    if (!screen || !view.rendered || offline || reducedMotion || dir == 0) return;
    // M13: the content moves 9 px towards the wall (up past the end, down past the start) in 90 ms E.out, then
    // rebounds on SPRING.wall; a new push retargets from where it is.
    glidePush(GLIDE_CONTENT, dir > 0 ? -WALL_PX : WALL_PX, WALL_PUSH_MS, SPRING_WALL);
    ++stats.wallBounces;
}

void cc_anim_cadence_sample(CCAnimCadence& cadence, uint32_t animTimerLastRunMs, bool animating, uint32_t periodMs) {
    if (!animating) {                     // episode over: the timer is paused until the next one
        cadence.primed = false;
        return;
    }
    if (!cadence.primed) {
        cadence.primed = true;
        cadence.lastRunMs = animTimerLastRunMs;
        return;
    }
    if (animTimerLastRunMs == cadence.lastRunMs) return;   // the timer did not run this pass
    const uint32_t gap = animTimerLastRunMs - cadence.lastRunMs;
    cadence.lastRunMs = animTimerLastRunMs;
    if (gap > cadence.maxGapMs) cadence.maxGapMs = gap;
    if (gap * 2u > 3u * periodMs) ++cadence.lateRuns;
}

bool cc_anim_cadence_poll(CCAnimCadence& cadence, bool lvglPaused) {
    const lv_timer_t* timer = lv_anim_get_timer();
    if (!timer) return false;
    const uint32_t late = cadence.lateRuns, gap = cadence.maxGapMs;
    // FW-BUG-044: LVGL paused (the app canvas) ends the episode, as no animation does.
    cc_anim_cadence_sample(cadence, timer->last_run, !lvglPaused && lv_anim_count_running() > 0, timer->period);
    return cadence.lateRuns != late || cadence.maxGapMs != gap;
}

const CCDisplayStats& cc_display_stats() { return stats; }

// ---------------------------------------------------------------------------------------------------------------
// FW-DES-007: the native value screen while the offline PC volume runs (no Desk Dial; the knob sends HID Consumer
// volume keys and cannot read the PC's level). The FOC re-centres its offline profile after every step, so the
// native number and half arc showed a fixed "100" that said nothing. While the mode is active this hides them and
// shows a fixed "PC volume" label, with a brief "+" or "-" tick above it on each step (user ruling 2026-10-03).
// Firmware-local copy, the knob's existing fonts and the native screen's colours; no other screen changes.
// Bound once by ui_valueScreen.c (ui_dataScreen, ui_posIndicator, ui_Arc1, hmi_thread.cpp's
// hmi_pc_volume_source); the harness (harness/main.cpp, kind "native") binds a stand-in value screen.
// The box is a child of the data group, so the native sleep overlay (which hides ui_dataScreen) hides it too.
// The box floats (out of the group's flex flow) and the group's other children are muted while the mode is up.
// Polled by its own LVGL timer (the LCD thread); it touches LVGL only when the mode or the tick changes.
// C linkage: ui_valueScreen.c (C) calls the attach; the callers declare these three themselves.
extern "C" {
void cc_native_pc_volume_attach(lv_obj_t* group, lv_obj_t* number, lv_obj_t* arc, bool (*source)(int32_t* steps));
void cc_native_pc_volume_poll(void);   // one pass now (the timer's body)
bool cc_native_pc_volume_shown(void);  // the PC volume view is up (the mode active, the view bound)
}
namespace {
const uint32_t PCVOL_POLL_MS = 16;
const uint32_t PCVOL_TICK_MS = 300;   // "a brief tick": hidden this long after the last step
const int32_t PCVOL_BOX_W = 200, PCVOL_BOX_H = 80;
struct CCPcVolume {
    lv_obj_t* box;
    lv_obj_t* title;
    lv_obj_t* tick;    // the tick: a "-" bar, plus a vertical bar that makes it a "+"
    lv_obj_t* tickV;
    lv_obj_t* number;
    lv_obj_t* arc;
    lv_timer_t* timer;
    bool (*source)(int32_t* steps);
    bool active;
    bool tickShown;
    int32_t steps;
    uint32_t tickAt;
};
CCPcVolume pcvol = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, false, false, 0, 0};
// The tick is drawn as two bars, not a glyph: no knob font has '+', and a built-in LVGL font would link in ~46 KB for
// one character. 24 x 24 box, 4 px bars, radius 2.
const int32_t PCVOL_TICK_SIZE = 24, PCVOL_TICK_BAR = 4;

lv_obj_t* pcvolBar(lv_obj_t* parent, int32_t w, int32_t h, const char* role) {
    lv_obj_t* bar = lv_obj_create(parent);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, w, h);
    lv_obj_set_align(bar, LV_ALIGN_CENTER);
    lv_obj_set_style_bg_color(bar, lv_color_hex(0xFF7D00), 0);   // the native accent (arc, profile name)
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(bar, PCVOL_TICK_BAR / 2, 0);
    lv_obj_remove_flag(bar, static_cast<lv_obj_flag_t>(LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE));
    lv_obj_set_user_data(bar, const_cast<char*>(role));
    return bar;
}

void pcvolShow(lv_obj_t* obj, bool visible) {
    if (!obj || lv_obj_has_flag(obj, LV_OBJ_FLAG_HIDDEN) == !visible) return;
    if (visible) lv_obj_remove_flag(obj, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
}

// The data group's other children (on the firmware, ui_profileName and ui_profileDesc: the native profile's title
// and a description such as "MIDI CC 7", a number and the wrong text while the knob sends volume keys) are muted
// with a local style opacity, not the HIDDEN flag: lcd_thread.cpp owns their HIDDEN flags (it re-shows them only
// when a new command arrives), so removing the local opacity on exit gives back exactly the state it set.
void pcvolMuteSiblings(bool mute) {
    lv_obj_t* group = pcvol.box ? lv_obj_get_parent(pcvol.box) : nullptr;
    if (!group) return;
    const uint32_t n = lv_obj_get_child_count(group);
    for (uint32_t i = 0; i < n; ++i) {
        lv_obj_t* child = lv_obj_get_child(group, static_cast<int32_t>(i));
        if (child == pcvol.box || child == pcvol.number) continue;
        if (mute) lv_obj_set_style_opa(child, LV_OPA_TRANSP, 0);
        else lv_obj_remove_local_style_prop(child, LV_STYLE_OPA, 0);
    }
}

void pcvolPoll(lv_timer_t*) { cc_native_pc_volume_poll(); }

void pcvolDeleted(lv_event_t*) {
    if (pcvol.timer) lv_timer_delete(pcvol.timer);
    pcvol = CCPcVolume();
}
}  // namespace

void cc_native_pc_volume_poll(void) {
    if (!pcvol.box || !pcvol.source) return;
    int32_t steps = 0;
    const bool active = pcvol.source(&steps);
    if (active != pcvol.active) {
        pcvol.active = active;
        pcvol.steps = steps;                 // a step from before the mode never ticks
        pcvol.tickShown = false;
        pcvolShow(pcvol.tick, false);
        pcvolShow(pcvol.number, !active);
        pcvolShow(pcvol.arc, !active);
        pcvolMuteSiblings(active);
        pcvolShow(pcvol.box, active);
        return;
    }
    if (!active) return;
    const uint32_t now = lv_tick_get();
    if (steps != pcvol.steps) {
        pcvolShow(pcvol.tickV, steps > pcvol.steps);   // "+" up, "-" down
        pcvol.steps = steps;
        pcvol.tickAt = now;
        pcvol.tickShown = true;
        pcvolShow(pcvol.tick, true);
    } else if (pcvol.tickShown && now - pcvol.tickAt >= PCVOL_TICK_MS) {
        pcvol.tickShown = false;
        pcvolShow(pcvol.tick, false);
    }
}

void cc_native_pc_volume_attach(lv_obj_t* group, lv_obj_t* number, lv_obj_t* arc, bool (*source)(int32_t* steps)) {
    if (pcvol.box && pcvol.active) pcvolMuteSiblings(false);   // a re-bind gives the old group's labels back
    if (pcvol.box) lv_obj_delete(pcvol.box);   // its delete event clears the state and the timer
    lv_obj_t* box = lv_obj_create(group);
    lv_obj_remove_style_all(box);
    lv_obj_set_size(box, PCVOL_BOX_W, PCVOL_BOX_H);
    lv_obj_set_align(box, LV_ALIGN_CENTER);
    lv_obj_remove_flag(box, static_cast<lv_obj_flag_t>(LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE));
    // Out of the group's flex column (its align would be ignored there and the box stacked under the profile
    // labels): floating, it is centred in the group, which is centred on the screen.
    lv_obj_add_flag(box, static_cast<lv_obj_flag_t>(LV_OBJ_FLAG_HIDDEN | LV_OBJ_FLAG_FLOATING));
    lv_obj_set_user_data(box, const_cast<char*>("pcvol"));
    lv_obj_t* tick = lv_obj_create(box);
    lv_obj_remove_style_all(tick);
    lv_obj_set_size(tick, PCVOL_TICK_SIZE, PCVOL_TICK_SIZE);
    lv_obj_set_align(tick, LV_ALIGN_TOP_MID);
    lv_obj_set_y(tick, 6);
    lv_obj_remove_flag(tick, static_cast<lv_obj_flag_t>(LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE));
    lv_obj_add_flag(tick, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_user_data(tick, const_cast<char*>("pcvol.tick"));
    pcvolBar(tick, PCVOL_TICK_SIZE, PCVOL_TICK_BAR, "pcvol.tick.h");
    lv_obj_t* tickV = pcvolBar(tick, PCVOL_TICK_BAR, PCVOL_TICK_SIZE, "pcvol.tick.v");
    lv_obj_t* title = lv_label_create(box);
    lv_obj_set_style_text_font(title, &cc_font_22, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(0xFFFFFF), 0);  // the native number's white
    lv_obj_set_align(title, LV_ALIGN_BOTTOM_MID);
    lv_label_set_text(title, "PC volume");
    lv_obj_set_user_data(title, const_cast<char*>("pcvol.title"));
    lv_obj_add_event_cb(box, pcvolDeleted, LV_EVENT_DELETE, nullptr);
    pcvol.box = box;
    pcvol.title = title;
    pcvol.tick = tick;
    pcvol.tickV = tickV;
    pcvol.number = number;
    pcvol.arc = arc;
    pcvol.source = source;
    pcvol.timer = lv_timer_create(pcvolPoll, PCVOL_POLL_MS, nullptr);
    cc_native_pc_volume_poll();
}

bool cc_native_pc_volume_shown(void) { return pcvol.box && pcvol.active; }
