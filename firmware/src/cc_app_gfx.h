#pragma once
// App canvas pixel toolkit (A2, 1.0.0-cc5.6): the drawing primitives Karl's app UI is built from, drawn into
// one bound 240 x 240 RGB565 buffer (the app canvas, cc_app_canvas.h) with plain rect fills -- no
// anti-aliasing anywhere, by design. Platform-neutral: compiled unchanged by the firmware, the host harness
// (harness/app_canvas_tests.py, MSVC) and the gnu++11 gate.
//
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/ui_gfx.hpp / ui_gfx.cpp. The LovyanGFX sprite is replaced by a thin shim over our
// buffer (bind / clip / fill); colours stay RGB888 in the drawing code and are packed to RGB565 at the fill,
// as LovyanGFX did. C++11 (the firmware's gnu++11): namespace-scope constexpr only.

#include <stdint.h>

namespace ccui {

constexpr int W = 240;
constexpr int H = 240;
constexpr int CX = 120;
constexpr int CY = 120;

// Palette rule: black plus four colours (RGB888).
constexpr uint32_t BLACK = 0x000000u;
constexpr uint32_t WHITE = 0xFFFFFFu;
constexpr uint32_t GREY = 0x6E6E6Eu;
constexpr uint32_t DARK = 0x3A3A3Au;
constexpr uint32_t AMBER = 0xFFC94Du;
constexpr uint32_t KEY_FACE = 0xE4E4E4u;
constexpr uint32_t KEY_SIDE = 0x8A8A8Au;
constexpr uint32_t KEY_OFF_FACE = 0x4A4A4Au;
constexpr uint32_t KEY_OFF_SIDE = 0x262626u;

// RGB888 -> RGB565 (truncating, as LovyanGFX's color888 -> 565).
inline uint16_t rgb565(uint32_t c) {
    return static_cast<uint16_t>(((c >> 8) & 0xF800u) | ((c >> 5) & 0x07E0u) | ((c >> 3) & 0x001Fu));
}

enum Align { LEFT, CENTER, RIGHT };

// 1-bit sprite: `rows` is w*h chars, '#' = set.
struct Sprite {
    uint8_t w;
    uint8_t h;
    const char* rows;
};

// GFXfont-compatible glyph / font (cc_app_fonts.cpp).
struct Glyph {
    uint32_t bitmapOffset;
    uint8_t width, height;
    uint8_t xAdvance;
    int8_t xOffset, yOffset;
};
struct Font {
    const uint8_t* bitmap;
    const Glyph* glyph;
    uint16_t first, last;
    uint8_t yAdvance;
};
// The two faces (cc_app_fonts.cpp); accessors, so no unit odr-uses another unit's data (the gnu++11 gate).
const Font& font_8();
const Font& font_10();

// The target: a W x H RGB565 buffer (native byte order). Everything below draws into it.
void bind(uint16_t* buffer);
uint16_t* bound();
void clear(uint32_t c);
void clip(int x, int y, int w, int h);
void unclip();
// The current clip as [x0, x1) x [y0, y1) (empty when x0 >= x1 or y0 >= y1): loops over profile-driven geometry
// bound themselves by it, so their cost follows what can land on the canvas, never the element's own extent.
void clip_bounds(int* x0, int* y0, int* x1, int* y1);
// Pixels written since the last call (the harness's work estimate; cheap counter).
uint32_t take_fill_count();
uint32_t take_fill_calls();   // fill() calls since the last call (the harness's per-call overhead estimate)

void fill(int x, int y, int w, int h, uint32_t c);       // the one primitive (clipped)
void rect(float x, float y, int w, int h, uint32_t c);
void cut(int x, int y, int w, int h, uint32_t c);         // rect with the 4 corner pixels cut
void frame_box(int x, int y, int w, int h, uint32_t c);   // 1px outline, corners cut
void disc(float cx, float cy, float r, uint32_t c);
void sprite(const Sprite& s, float x, float y, uint32_t c, int scale = 1);
// w x h RGB565 big-endian image, 1:1 (x scale); black pixels are left alone; `brightness` < 1 dims it.
void image565(int x, int y, int w, int h, const uint8_t* be, float brightness = 1.0f, int scale = 1);

// Silkscreen: scale 1 = the 10 px face (caps 7 px); 2, 3, 4 = the 8 px face scaled (caps 10/15/20 px).
// `y` is the top of the caps; alignment uses the ink bounds. Both return the ink width.
int cap_height(int scale);
int text_width(const char* s, int scale = 1);
int text(const char* s, float x, float y, uint32_t c, int scale = 1, Align align = LEFT);
int fit_scale(const char* s, int max_w, int max_scale);

// 3D keycap sized for a 10 px label: face + 4 px side, the face drops 3 px when pressed.
constexpr int KEY_W = 26;
constexpr int KEY_H = 22;
void keycap(int x, int y, const char* label, bool pressed, bool disabled);

} // namespace ccui
