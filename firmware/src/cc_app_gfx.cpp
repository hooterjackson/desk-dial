// App canvas pixel toolkit (cc_app_gfx.h).
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/ui_gfx.cpp (primitives, text, keycap), drawing into our RGB565 buffer instead of an
// LGFX_Sprite. Only the pieces the app screens use are kept (no boot / menu / haptics-orbit helpers).
#include "cc_app_gfx.h"
#include <math.h>

namespace ccui {

namespace {
uint16_t* g_buf = nullptr;
int g_cx = 0, g_cy = 0, g_cw = W, g_ch = H;
uint32_t g_fills = 0, g_calls = 0;

inline int iround(float v) { return static_cast<int>(lroundf(v)); }
} // namespace

void bind(uint16_t* buffer) {
    g_buf = buffer;
    unclip();
}

uint16_t* bound() { return g_buf; }

void clip(int x, int y, int w, int h) {
    g_cx = x < 0 ? 0 : x;
    g_cy = y < 0 ? 0 : y;
    const int x1 = x + w > W ? W : x + w, y1 = y + h > H ? H : y + h;
    g_cw = x1 - g_cx;
    g_ch = y1 - g_cy;
}

void unclip() {
    g_cx = 0; g_cy = 0; g_cw = W; g_ch = H;
}

void clip_bounds(int* x0, int* y0, int* x1, int* y1) {
    *x0 = g_cx; *y0 = g_cy; *x1 = g_cx + g_cw; *y1 = g_cy + g_ch;
}

uint32_t take_fill_count() {
    const uint32_t n = g_fills;
    g_fills = 0;
    return n;
}

uint32_t take_fill_calls() {
    const uint32_t n = g_calls;
    g_calls = 0;
    return n;
}

void fill(int x, int y, int w, int h, uint32_t c) {
    ++g_calls;
    if (g_buf == nullptr || w <= 0 || h <= 0) return;
    int x0 = x < g_cx ? g_cx : x, y0 = y < g_cy ? g_cy : y;
    int x1 = x + w > g_cx + g_cw ? g_cx + g_cw : x + w, y1 = y + h > g_cy + g_ch ? g_cy + g_ch : y + h;
    if (x0 >= x1 || y0 >= y1) return;
    const uint16_t v = rgb565(c);
    for (int yy = y0; yy < y1; ++yy) {
        uint16_t* p = g_buf + yy * W + x0;
        for (int xx = x0; xx < x1; ++xx) *p++ = v;
    }
    g_fills += static_cast<uint32_t>((x1 - x0) * (y1 - y0));
}

void clear(uint32_t c) {
    const int cx = g_cx, cy = g_cy, cw = g_cw, ch = g_ch;
    unclip();
    fill(0, 0, W, H, c);
    g_cx = cx; g_cy = cy; g_cw = cw; g_ch = ch;
}

void rect(float x, float y, int w, int h, uint32_t c) {
    if (w <= 0 || h <= 0) return;
    fill(iround(x), iround(y), w, h, c);
}

void cut(int x, int y, int w, int h, uint32_t c) {
    rect(static_cast<float>(x + 1), static_cast<float>(y), w - 2, h, c);
    rect(static_cast<float>(x), static_cast<float>(y + 1), w, h - 2, c);
}

void frame_box(int x, int y, int w, int h, uint32_t c) {
    fill(x + 1, y, w - 2, 1, c);
    fill(x + 1, y + h - 1, w - 2, 1, c);
    fill(x, y + 1, 1, h - 2, c);
    fill(x + w - 1, y + 1, 1, h - 2, c);
}

void disc(float cx, float cy, float r, uint32_t c) {
    const int rows = static_cast<int>(2 * r);
    for (int yy = 0; yy < rows; yy++) {
        const float dy = yy - r + 0.5f;
        const float hw = sqrtf(fmaxf(0.0f, r * r - dy * dy));
        const int x0 = iround(cx - hw), x1 = iround(cx + hw);
        fill(x0, iround(cy - r) + yy, x1 - x0, 1, c);
    }
}

void sprite(const Sprite& s, float x, float y, uint32_t c, int scale) {
    const int x0 = iround(x), y0 = iround(y);
    for (int j = 0; j < s.h; j++)
        for (int i = 0; i < s.w; i++)
            if (s.rows[j * s.w + i] == '#') fill(x0 + i * scale, y0 + j * scale, scale, scale, c);
}

void image565(int x, int y, int w, int h, const uint8_t* be, float brightness, int scale) {
    for (int j = 0; j < h; j++) {
        const uint8_t* row = be + j * w * 2;
        int i = 0;
        while (i < w) { // one fill per horizontal run of equal pixels
            int run = 1;
            while (i + run < w && row[(i + run) * 2] == row[i * 2] && row[(i + run) * 2 + 1] == row[i * 2 + 1]) run++;
            const uint16_t v = static_cast<uint16_t>(row[i * 2] << 8 | row[i * 2 + 1]);
            if (v != 0) {
                uint32_t r = (v >> 11) & 0x1F, g = (v >> 5) & 0x3F, b = v & 0x1F;
                r = r << 3 | r >> 2;
                g = g << 2 | g >> 4;
                b = b << 3 | b >> 2;
                if (brightness < 1.0f) {
                    r = static_cast<uint32_t>(r * brightness);
                    g = static_cast<uint32_t>(g * brightness);
                    b = static_cast<uint32_t>(b * brightness);
                }
                fill(x + i * scale, y + j * scale, run * scale, scale, (r << 16) | (g << 8) | b);
            }
            i += run;
        }
    }
}

// --- text ---

namespace {
struct FontPick {
    const Font* font;
    int px;
};
FontPick font_for(int scale) {
    FontPick pick = {&font_10(), 1};
    if (scale > 1) { pick.font = &font_8(); pick.px = scale; }
    return pick;
}

const Glyph& glyph(const Font& f, char ch) {
    uint8_t code = static_cast<uint8_t>(ch);
    if (code < f.first || code > f.last) code = static_cast<uint8_t>(f.first);
    return f.glyph[code - f.first];
}

void measure(const Font& f, const char* s, int* left, int* width) {
    int pen = 0, min_x = 1 << 30, max_x = -(1 << 30);
    for (const char* p = s; *p; p++) {
        const Glyph& g = glyph(f, *p);
        if (*p != ' ') {
            if (pen + g.xOffset < min_x) min_x = pen + g.xOffset;
            if (pen + g.xOffset + g.width > max_x) max_x = pen + g.xOffset + g.width;
        }
        pen += g.xAdvance;
    }
    if (min_x > max_x) { *left = 0; *width = 0; }
    else { *left = min_x; *width = max_x - min_x; }
}

int pen_start(const Font& f, int px, const char* s, float x, Align align) {
    int l, w;
    measure(f, s, &l, &w);
    const float x0 = (align == CENTER) ? x - (w * px) / 2.0f - l * px
                   : (align == RIGHT) ? x - w * px - l * px
                   : x - l * px;
    return iround(x0);
}
} // namespace

int cap_height(int scale) { return scale <= 1 ? 7 : 5 * scale; }

int text_width(const char* s, int scale) {
    const FontPick fp = font_for(scale);
    int l, w;
    measure(*fp.font, s, &l, &w);
    return w * fp.px;
}

int fit_scale(const char* s, int max_w, int max_scale) {
    int sc = max_scale;
    while (sc > 1 && text_width(s, sc) > max_w) sc--;
    return sc;
}

int text(const char* s, float x, float y, uint32_t c, int scale, Align align) {
    const FontPick fp = font_for(scale);
    const Font& f = *fp.font;
    const int x0 = pen_start(f, fp.px, s, x, align);
    const int base = iround(y) + cap_height(scale);
    int pen = 0;
    for (const char* p = s; *p; p++) {
        const Glyph& g = glyph(f, *p);
        const uint8_t* bits = f.bitmap + g.bitmapOffset;
        for (int i = 0; i < g.width * g.height; i++) {
            if (bits[i >> 3] & (0x80 >> (i & 7)))
                fill(x0 + (pen + g.xOffset + (i % g.width)) * fp.px, base + (g.yOffset + i / g.width) * fp.px, fp.px, fp.px, c);
        }
        pen += g.xAdvance;
    }
    return text_width(s, scale);
}

void keycap(int x, int y, const char* label, bool pressed, bool disabled) {
    const int face_h = KEY_H - 5;
    const int fy = pressed ? 3 : 0;
    cut(x, y + 4, KEY_W, KEY_H - 4, disabled ? KEY_OFF_SIDE : KEY_SIDE);
    cut(x, y + fy, KEY_W, face_h, pressed ? AMBER : disabled ? KEY_OFF_FACE : KEY_FACE);
    text(label, x + KEY_W / 2.0f, static_cast<float>(y + fy + (face_h - cap_height(1)) / 2), BLACK, 1, CENTER);
}

} // namespace ccui
