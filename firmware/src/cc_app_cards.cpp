// App canvas: command-wheel cards, the wheel, parameter mode and the shortcut chord (cc_app_ui.h).
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/ui_cards.cpp. The card renderer (all 15 element kinds), the wheel, the parameter screen (the
// number field and the handle with its axis / plane / uniform chips) are his. The chord shows Windows keycaps
// (WIN, CTRL, ALT, the shift arrow) instead of the macOS glyphs; parameter labels read F1 / KNOB / F4 for the
// number field. App profiles (plan section 1e): up to 8 rings x 32 commands (the dots and tabs fit the glass),
// commands not on Windows drawn grey, a macro's name without a chord.
#include "cc_app_ui.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace ccui {

namespace {
// 7x7 layer-type glyphs (index = app_glyph_t).
const Sprite GLYPHS[] = {
    {7, 7, ".#####." "#.....#" "#.....#" "#.....#" "#.....#" "#.....#" ".#####."},
    {7, 7, "..###.." ".#...#." "#.....#" "#.....#" "#.....#" ".#...#." "..###.."},
    {7, 7, ".#...#." "#######" ".#...#." ".#...#." ".#...#." "#######" ".#...#."},
    {7, 7, "#.....#" "#.###.#" "#.###.#" "#.###.#" "#.###.#" "#.###.#" "#.....#"},
    {7, 7, "##.#.##" "#.....#" "......." "#.....#" "......." "#.....#" "##.#.##"},
    {7, 7, "...#..." "..###.." "#..#..#" "##...##" "#..#..#" "..###.." "...#..."},
    {7, 7, "...#..." "..#.#.." ".#...#." "#.....#" ".#...#." "..#.#.." "...#..."},
    {7, 7, "#######" "...#..." "...#..." "...#..." "...#..." "...#..." "...#..."},
    {7, 7, "..###.." ".#...#." "#######" "#.....#" "#.....#" "#.....#" "#######"},
    {7, 7, "......." "..#####" ".#...#." "#####.." "......." "......." "......."},
    {7, 7, ".....##" "....#.#" "...#.#." "..#.#.." ".#.#..." "##....." "#......"},
};
const int kGlyphCount = static_cast<int>(sizeof(GLYPHS) / sizeof(GLYPHS[0]));
// Plasticity's selection modes: control point, edge, face, solid (5x5, in 11x9 chips).
const Sprite MODE_GLYPHS[4] = {
    {5, 5, "....." ".###." ".###." ".###." "....."},
    {5, 5, "....#" "...#." "..#.." ".#..." "#...."},
    {5, 5, "..###" ".####" "#####" "####." "###.."},
    {5, 5, ".###." "#####" "#####" "#####" ".###."},
};
// The shift arrow (Karl's G_SHIFT); Ctrl and Alt are text caps on Windows.
const Sprite SPR_TRI_L_M = {4, 7, "...#" "..##" ".###" "####" ".###" "..##" "...#"};
const Sprite SPR_TRI_R_M = {4, 7, "#..." "##.." "###." "####" "###." "##.." "#..."};
const Sprite G_SHIFT = {7, 7, "...#..." "..#.#.." ".#...#." "###.###" "..#.#.." "..#.#.." "..###.."};

uint32_t color(uint8_t c) {
    switch (c) {
        case APP_C_DARK: return DARK;
        case APP_C_GREY: return GREY;
        case APP_C_WHITE: return WHITE;
        case APP_C_AMBER: return AMBER;
        default: return BLACK;
    }
}

// pattern: 0 solid, 1 dotted (1 on 1 off), 2 dashed (2 on 2 off)
// S3 review FW-1: a profile's elements may reach far past the clip (every byte but op and colour is any value), so
// a line wholly outside it returns at once and the per-pixel fill is skipped outside it (the same pixels).
void line(int x0, int y0, int x1, int y1, uint32_t c, int pattern = 0) {
    int cx0, cy0, cx1, cy1;
    clip_bounds(&cx0, &cy0, &cx1, &cy1);
    if ((x0 < cx0 && x1 < cx0) || (x0 >= cx1 && x1 >= cx1) || (y0 < cy0 && y1 < cy0) || (y0 >= cy1 && y1 >= cy1))
        return;
    const int dx = abs(x1 - x0), dy = -abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    for (int n = 0;; n++) {
        if ((pattern == 0 || (pattern == 1 ? (n & 1) == 0 : (n & 3) < 2)) && x0 >= cx0 && x0 < cx1 && y0 >= cy0 &&
            y0 < cy1)
            fill(x0, y0, 1, 1, c);
        if (x0 == x1 && y0 == y1) break;
        const int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

void dash_box(int x, int y, int w, int h, uint32_t c) {
    int n = 0;
    for (int i = 0; i < w; i++, n++) if ((n & 3) < 2) fill(x + i, y, 1, 1, c);
    for (int j = 1; j < h; j++, n++) if ((n & 3) < 2) fill(x + w - 1, y + j, 1, 1, c);
    for (int i = w - 2; i >= 0; i--, n++) if ((n & 3) < 2) fill(x + i, y + h - 1, 1, 1, c);
    for (int j = h - 2; j > 0; j--, n++) if ((n & 3) < 2) fill(x, y + j, 1, 1, c);
}

// 1px outline with 2px-rounded corners (the card edge).
void round_frame(int x, int y, int w, int h, uint32_t c) {
    fill(x + 3, y, w - 6, 1, c);
    fill(x + 3, y + h - 1, w - 6, 1, c);
    fill(x, y + 3, 1, h - 6, c);
    fill(x + w - 1, y + 3, 1, h - 6, c);
    const int d[2][2] = {{1, 2}, {2, 1}};
    for (int k = 0; k < 2; k++) {
        fill(x + d[k][0], y + d[k][1], 1, 1, c);
        fill(x + w - 1 - d[k][0], y + d[k][1], 1, 1, c);
        fill(x + d[k][0], y + h - 1 - d[k][1], 1, 1, c);
        fill(x + w - 1 - d[k][0], y + h - 1 - d[k][1], 1, 1, c);
    }
}

// Convex polygon at pixel centres; `dots` = every other pixel (a selected face). S3 review FW-1: rows and columns
// outside the clip are never visited (the same pixels; the cost follows the clip, not the polygon).
void poly(const int (*p)[2], int n, uint32_t c, bool dots) {
    int cx0, cy0, cx1, cy1;
    clip_bounds(&cx0, &cy0, &cx1, &cy1);
    int y0 = p[0][1], y1 = p[0][1];
    for (int i = 1; i < n; i++) { if (p[i][1] < y0) y0 = p[i][1]; if (p[i][1] > y1) y1 = p[i][1]; }
    if (y0 < cy0) y0 = cy0;
    if (y1 > cy1 - 1) y1 = cy1 - 1;
    for (int y = y0; y <= y1; y++) {
        const float py = y + 0.5f;
        float lo = 1e9f, hi = -1e9f;
        for (int i = 0; i < n; i++) {
            const float ax = static_cast<float>(p[i][0]), ay = static_cast<float>(p[i][1]);
            const float bx = static_cast<float>(p[(i + 1) % n][0]), by = static_cast<float>(p[(i + 1) % n][1]);
            if ((ay <= py && by > py) || (by <= py && ay > py)) {
                const float x = ax + (py - ay) / (by - ay) * (bx - ax);
                if (x < lo) lo = x;
                if (x > hi) hi = x;
            }
        }
        if (lo > hi) continue;
        int xa = static_cast<int>(ceilf(lo - 0.5f)), xb = static_cast<int>(floorf(hi - 0.5f));
        if (xa < cx0) xa = cx0;
        if (xb > cx1 - 1) xb = cx1 - 1;
        for (int x = xa; x <= xb; x++) {
            if (dots && ((x + y) & 1)) continue;
            fill(x, y, 1, 1, c);
        }
    }
}

// Isometric 2:1 wireframe box (APP_EL_ISO), viewed from +x +y +z.
struct Iso {
    int ox, oy;
    void P(int X, int Y, int Z, int* o) const { o[0] = ox + X - Y; o[1] = oy + ((X + Y + 1) >> 1) - Z; }
    void E(int X0, int Y0, int Z0, int X1, int Y1, int Z1, uint32_t c, int pat) const {
        int p0[2], p1[2];
        P(X0, Y0, Z0, p0);
        P(X1, Y1, Z1, p1);
        line(p0[0], p0[1], p1[0], p1[1], c, pat);
    }
};

void iso_box(const app_el_t& e, int x0, int y0) {
    const Iso I = {x0 + e.x, y0 + e.y};
    const int a = e.w, b = e.h, h = e.d, f = e.flags;
    const int r = (f & APP_ISO_HOLLOW) ? 0 : (e.arg & 0x3F);
    const bool chamfer = (e.arg & APP_ISO_ARG_CHAMFER) != 0;
    const bool ghost = (f & APP_ISO_GHOST) != 0;
    const uint32_t edge = ghost ? DARK : (f & APP_ISO_SOLID) ? AMBER : color(e.color);
    const int pat = ghost ? 2 : 0;
    if (!ghost && (e.arg & APP_ISO_ARG_CUT) && !(f & APP_ISO_HOLLOW)) {
        int s[4][2];
        I.P(a, 0, 0, s[0]); I.P(a, b, 0, s[1]); I.P(a, b, h, s[2]); I.P(a, 0, h, s[3]);
        poly(s, 4, AMBER, true);
    }
    if (!ghost) {
        I.E(0, 0, 0, a, 0, 0, DARK, 1);
        I.E(0, 0, 0, 0, b, 0, DARK, 1);
        if (h > 0) I.E(0, 0, 0, 0, 0, h, DARK, 1);
    }
    int top[5][2];
    int nt = 0;
    I.P(0, 0, h, top[nt++]);
    I.P(a, 0, h, top[nt++]);
    if (r) { I.P(a, b - r, h, top[nt++]); I.P(a - r, b, h, top[nt++]); } else I.P(a, b, h, top[nt++]);
    I.P(0, b, h, top[nt++]);
    if (r && !ghost) {
        int s[4][2];
        I.P(a, b - r, 0, s[0]); I.P(a - r, b, 0, s[1]); I.P(a - r, b, h, s[2]); I.P(a, b - r, h, s[3]);
        if (chamfer) for (int i = 0; i < 4; i++) line(s[i][0], s[i][1], s[(i + 1) % 4][0], s[(i + 1) % 4][1], AMBER);
        else poly(s, 4, AMBER, true);
    }
    const bool face = (f & APP_ISO_FACE) != 0;
    if (face && !ghost) poly(top, nt, AMBER, true);
    for (int i = 0; i < nt; i++) {
        const int *p0 = top[i], *p1 = top[(i + 1) % nt];
        line(p0[0], p0[1], p1[0], p1[1], face ? AMBER : edge, pat);
    }
    if (h > 0) {
        I.E(a, 0, 0, a, 0, h, edge, pat);
        I.E(0, b, 0, 0, b, h, edge, pat);
        if (!(f & APP_ISO_NO_BOTTOM)) {
            I.E(a, 0, 0, a, b - r, 0, edge, pat);
            I.E(0, b, 0, a - r, b, 0, edge, pat);
        }
        if (r) {
            I.E(a, b - r, 0, a, b - r, h, edge, pat);
            I.E(a - r, b, 0, a - r, b, h, edge, pat);
            if (!(f & APP_ISO_NO_BOTTOM)) I.E(a, b - r, 0, a - r, b, 0, edge, pat);
        } else {
            const bool sel = (f & APP_ISO_EDGE) != 0;
            I.E(a, b, 0, a, b, h, sel ? AMBER : edge, pat);
            if (sel) {
                int p0[2], p1[2];
                I.P(a, b, 0, p0);
                I.P(a, b, h, p1);
                line(p0[0] + 1, p0[1], p1[0] + 1, p1[1], AMBER);
            }
        }
    }
    if (f & APP_ISO_HOLLOW) {
        const int in = r ? r : (e.arg ? e.arg : 3);
        int q[4][2];
        I.P(in, in, h, q[0]); I.P(a - in, in, h, q[1]); I.P(a - in, b - in, h, q[2]); I.P(in, b - in, h, q[3]);
        for (int i = 0; i < 4; i++) line(q[i][0], q[i][1], q[(i + 1) % 4][0], q[(i + 1) % 4][1], AMBER);
        I.E(in, in, h, in, in, h > 6 ? h - 6 : 0, DARK, 0);
    }
}

// Arc (APP_EL_ARC): an iso ellipse or, with APP_ARC_ROUND, a circle; a 3x3 head unless APP_ARC_NO_HEAD.
void iso_arc(int cx, int cy, int r, float t0, float t1, uint32_t c, uint8_t flags) {
    const bool round = (flags & APP_ARC_ROUND) != 0;
    int lx = 0, ly = 0;
    bool have = false;
    const float step = t1 > t0 ? 0.04f : -0.04f;
    for (float t = t0; step > 0 ? t <= t1 + 1e-4f : t >= t1 - 1e-4f; t += step) {
        const int x = static_cast<int>(lroundf(cx + r * cosf(t)));
        const int y = static_cast<int>(lroundf(round ? cy - r * sinf(t) : cy + r / 2.0f * sinf(t)));
        if (have && (x != lx || y != ly)) line(lx, ly, x, y, c, (flags & APP_ARC_DOTTED) ? 1 : 0);
        lx = x;
        ly = y;
        have = true;
    }
    if (have && !(flags & APP_ARC_NO_HEAD)) fill(lx - 1, ly - 1, 3, 3, c);
}

// A feature-list row. `x0, y0` = the card's top-left.
void row(const app_el_t& e, int x0, int y0) {
    const int ry = y0 + 5 + e.d + e.y * 11, rx = x0 + 68 + e.x * 6;
    const uint32_t c = color(e.color);
    if (e.h & APP_ROW_SEL) cut(x0 + 66, ry - 2, 51, 11, DARK);
    if (e.arg < kGlyphCount) sprite(GLYPHS[e.arg], static_cast<float>(rx), static_cast<float>(ry), c);
    const int bx = rx + 10;
    if (e.h & APP_ROW_ALL) {
        fill(bx - 1, ry, e.w + 2, 7, AMBER);
        fill(bx, ry + 3, e.w, 2, BLACK);
    } else if (e.w) {
        fill(bx, ry + 3, e.w, 2, c);
    }
    if (e.h & APP_ROW_FIELD) frame_box(bx - 2, ry - 2, x0 + 116 - (bx - 2), 11, AMBER);
    if (e.h & APP_ROW_CURSOR) fill(bx + e.w + 1, ry, 1, 7, AMBER);
    if (e.h & APP_ROW_DOT) cut(bx + e.w + 3, ry + 2, 3, 3, AMBER);
}

void rollback(int x0, int y0, int index, int offset) {
    const int ry = y0 + 5 + offset + index * 11 - 2;
    fill(x0 + 67, ry, 49, 1, GREY);
    fill(x0 + 67, ry - 1, 3, 3, GREY);
}

// Plasticity's selection-mode strip, top of the right pane; `bits` = active modes.
void modes(uint8_t bits, int x0, int y0) {
    for (int i = 0; i < 4; i++) {
        const bool on = (bits & (1 << i)) != 0;
        const int x = x0 + 67 + i * 13;
        cut(x, y0 + 5, 11, 9, on ? AMBER : DARK);
        sprite(MODE_GLYPHS[i], static_cast<float>(x + 3), static_cast<float>(y0 + 7), on ? BLACK : GREY);
    }
}

void element(const app_el_t& e, int x0, int y0) {
    if (e.op == APP_EL_ROW) { row(e, x0, y0); return; }
    if (e.op == APP_EL_MODES) { modes(e.arg, x0, y0); return; }
    if (e.op == APP_EL_ROLLBACK) { rollback(x0, y0, e.y, e.d); return; }
    const uint32_t c = color(e.color);
    const int x = x0 + e.x, y = y0 + e.y;
    clip(x0 + 4, y0 + 4, 57, 56); // canvas pane
    switch (e.op) {
        case APP_EL_BOX:
            if (e.w >= 4 && e.h >= 4) cut(x, y, e.w, e.h, c); else fill(x, y, e.w, e.h, c);
            break;
        case APP_EL_FRAME: frame_box(x, y, e.w, e.h, c); break;
        case APP_EL_DASH: dash_box(x, y, e.w, e.h, c); break;
        case APP_EL_DISC: disc(x + e.w / 2.0f, y + e.w / 2.0f, e.w / 2.0f, c); break;
        case APP_EL_SEL: {
            fill(x, y, e.w, 1, c);
            fill(x, y + e.h - 1, e.w, 1, c);
            fill(x, y, 1, e.h, c);
            fill(x + e.w - 1, y, 1, e.h, c);
            const int hx[2] = {x - 1, x + e.w - 2}, hy[2] = {y - 1, y + e.h - 2};
            for (int i = 0; i < 2; i++)
                for (int j = 0; j < 2; j++) fill(hx[i], hy[j], 3, 3, c);
            break;
        }
        case APP_EL_LABEL:
            if (e.arg < kGlyphCount) sprite(GLYPHS[e.arg], static_cast<float>(x), static_cast<float>(y), c);
            fill(x + 10, y + 3, e.w, 2, c);
            break;
        case APP_EL_CLIPBOARD:
            frame_box(x, y + 3, 13, 14, c);
            cut(x + 3, y, 7, 5, GREY);
            break;
        case APP_EL_PLAY: {
            const float r = e.w / 2.0f;
            disc(x + r, y + r, r, c);
            const int th = e.w / 2 | 1, tx = x + static_cast<int>(r) - th / 4 - 1;   // odd height, nudged right
            for (int i = 0; i <= th / 2; i++) fill(tx + i, y + static_cast<int>(r) - th / 2 + i, 1, th - 2 * i, BLACK);
            break;
        }
        case APP_EL_LINE: {
            const int x1 = x0 + static_cast<int8_t>(e.w), y1 = y0 + static_cast<int8_t>(e.h);
            line(x, y, x1, y1, c, (e.arg & APP_LINE_DASHED) ? 2 : 0);
            if (e.arg & APP_LINE_HEAD) fill(x1 - 1, y1 - 1, 3, 3, c);
            break;
        }
        case APP_EL_ISO: iso_box(e, x0, y0); break;
        case APP_EL_ARC: iso_arc(x, y, e.w, e.arg / 10.0f, e.d / 10.0f, c, e.flags); break;
        case APP_EL_NUM: {
            char n[4];
            snprintf(n, sizeof(n), "%u", static_cast<unsigned>(e.arg));
            text(n, static_cast<float>(x), static_cast<float>(y), c, 1, CENTER);
            break;
        }
        default: break;
    }
    unclip();
}

app_el_t iso_el(int x, int y, int a, int b, int h, uint8_t flags, uint8_t arg) {
    app_el_t e;
    memset(&e, 0, sizeof(e));
    e.op = APP_EL_ISO;
    e.color = APP_C_WHITE;
    e.x = static_cast<int8_t>(x); e.y = static_cast<int8_t>(y);
    e.w = static_cast<uint8_t>(a); e.h = static_cast<uint8_t>(b); e.d = static_cast<uint8_t>(h < 0 ? 0 : h);
    e.arg = arg; e.flags = flags;
    return e;
}

float clampf(float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; }
int clampi(long v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : static_cast<int>(v); }

// A box from its 8 corners so it can move / rotate / scale on any axis. Extents x +-a/2, y +-b/2, z 0..h;
// transforms about its centre. The farthest corner's edges dotted dark.
struct Box3 {
    float scale[3], move[3];
    int axis;
    float angle;
    bool ghost, grips;
};
Box3 box3_plain() {
    Box3 o;
    for (int i = 0; i < 3; i++) { o.scale[i] = 1; o.move[i] = 0; }
    o.axis = 2;
    o.angle = 0;
    o.ghost = o.grips = false;
    return o;
}
void box3(int ox, int oy, float a, float b, float h, const Box3& o) {
    float pts[8][3];
    const float c = cosf(o.angle), s = sinf(o.angle), zc = h / 2;
    for (int k = 0; k < 8; k++) {
        float x = ((k & 1) ? 1 : -1) * a * o.scale[0] / 2, y = ((k & 2) ? 1 : -1) * b * o.scale[1] / 2,
              z = ((k & 4) ? 1 : -1) * h * o.scale[2] / 2;
        float t;
        if (o.axis == 0) { t = y * c - z * s; z = y * s + z * c; y = t; }
        else if (o.axis == 1) { t = x * c + z * s; z = -x * s + z * c; x = t; }
        else { t = x * c - y * s; y = x * s + y * c; x = t; }
        pts[k][0] = x + o.move[0];
        pts[k][1] = y + o.move[1];
        pts[k][2] = z + zc + o.move[2];
    }
    int far = 0;
    for (int k = 1; k < 8; k++)
        if (pts[k][0] + pts[k][1] + 1.2f * pts[k][2] < pts[far][0] + pts[far][1] + 1.2f * pts[far][2]) far = k;
    int sp[8][2];
    for (int k = 0; k < 8; k++) {
        sp[k][0] = ox + static_cast<int>(lroundf(pts[k][0] - pts[k][1]));
        sp[k][1] = oy + static_cast<int>(lroundf((pts[k][0] + pts[k][1]) / 2 - pts[k][2]));
    }
    for (int i = 0; i < 8; i++) {
        for (int bit = 1; bit <= 4; bit <<= 1) {
            const int j = i | bit;
            if (j == i) continue;
            const bool hidden = i == far || j == far;
            if (o.ghost) line(sp[i][0], sp[i][1], sp[j][0], sp[j][1], DARK, 2);
            else line(sp[i][0], sp[i][1], sp[j][0], sp[j][1], hidden ? DARK : AMBER, hidden ? 1 : 0);
        }
    }
    if (o.grips && !o.ghost) {
        for (int k = 4; k < 8; k++) {
            fill(sp[k][0] - 2, sp[k][1] - 2, 5, 5, AMBER);
            fill(sp[k][0] - 1, sp[k][1] - 1, 3, 3, BLACK);
        }
    }
}

// Axis marker, bottom-left of the viewport: lit axes amber.
void tripod(int x0, int y0, uint8_t bits) {
    const int ox = x0 + 15, oy = y0 + 50;
    line(ox, oy, ox + 8, oy + 4, (bits & 1) ? AMBER : DARK);
    line(ox, oy, ox - 8, oy + 4, (bits & 2) ? AMBER : DARK);
    line(ox, oy, ox, oy - 8, (bits & 4) ? AMBER : DARK);
    fill(ox - 1, oy - 1, 3, 3, WHITE);
}

void param_visual(const ParamView& v, int x0, int y0) {
    const float val = v.drawn;
    const int bits = v.axis_bits;
    switch (v.visual) {
        case APP_PV_FILLET: {
            const int r = clampi(lroundf(fabsf(val) * 4), 0, 12);
            const app_el_t e = r ? iso_el(32, 30, 16, 16, 12, 0, static_cast<uint8_t>(r | (val < 0 ? APP_ISO_ARG_CHAMFER : 0)))
                                 : iso_el(32, 30, 16, 16, 12, APP_ISO_EDGE, 0);
            iso_box(e, x0, y0);
            break;
        }
        case APP_PV_CHAMFER: {
            const int r = clampi(lroundf(fabsf(val) * 2), 0, 12);
            const app_el_t e = r ? iso_el(32, 30, 16, 16, 12, 0, static_cast<uint8_t>(r | APP_ISO_ARG_CHAMFER))
                                 : iso_el(32, 30, 16, 16, 12, APP_ISO_EDGE, 0);
            iso_box(e, x0, y0);
            break;
        }
        case APP_PV_SLIDE: {
            const int d = clampi(lroundf(val), -14, 14);
            iso_box(iso_el(26, 26, 12, 12, 10, APP_ISO_GHOST, 0), x0, y0);
            iso_box(iso_el(26 + d, 26 + d / 2, 12, 12, 10, APP_ISO_SOLID, 0), x0, y0);
            break;
        }
        case APP_PV_EXTRUDE: {
            const int h = static_cast<int>(lroundf(fabsf(val) * 2));
            if (val >= 0) {
                iso_box(iso_el(32, 40, 16, 16, clampi(h, 0, 22), APP_ISO_FACE, 0), x0, y0);
            } else {
                iso_box(iso_el(32, 36, 16, 16, 12, APP_ISO_GHOST, 0), x0, y0);
                iso_box(iso_el(32, 36, 16, 16, clampi(12 - h, 0, 12), APP_ISO_FACE, 0), x0, y0);
            }
            break;
        }
        case APP_PV_OFFSET:
            if (val != 0) iso_box(iso_el(32, 30, 16, 16, 12, APP_ISO_GHOST, 0), x0, y0);
            iso_box(iso_el(32, 30, 16, 16, clampi(12 + lroundf(val * 2), 2, 24), APP_ISO_FACE, 0), x0, y0);
            break;
        case APP_PV_HOLLOW:
            iso_box(iso_el(32, 30, 16, 16, 12, APP_ISO_HOLLOW, static_cast<uint8_t>(clampi(1 + lroundf(val * 1.2f), 1, 7))), x0, y0);
            break;
        case APP_PV_MOVE: {
            Box3 g = box3_plain(), m = box3_plain();
            g.ghost = true;
            const float d = clampf(val * 1.5f, -16, 16);
            const int n = (bits & 1) + ((bits >> 1) & 1) + ((bits >> 2) & 1);
            for (int i = 0; i < 3; i++)
                if (bits & (1 << i)) m.move[i] = d * (i == 2 ? 0.8f : 1.0f) / sqrtf(static_cast<float>(n ? n : 1));
            box3(x0 + 32, y0 + 26, 12, 12, 10, g);
            box3(x0 + 32, y0 + 26, 12, 12, 10, m);
            tripod(x0, y0, static_cast<uint8_t>(bits));
            break;
        }
        case APP_PV_ROTATE: {
            Box3 r = box3_plain();
            r.axis = v.axis;
            r.angle = val * 3.14159265358979f / 180.0f;
            box3(x0 + 32, y0 + 24, 20, 12, 10, r);
            tripod(x0, y0, static_cast<uint8_t>(bits));
            break;
        }
        case APP_PV_SCALE: {
            Box3 g = box3_plain(), sc = box3_plain();
            g.ghost = true;
            sc.grips = true;
            const float f = clampf(val, 0.2f, 2.2f);
            for (int i = 0; i < 3; i++)
                if (bits & (1 << i)) sc.scale[i] = f;
            if (val != 1) box3(x0 + 32, y0 + 30, 12, 12, 10, g);
            box3(x0 + 32, y0 + 30, 12, 12, 10, sc);
            tripod(x0, y0, static_cast<uint8_t>(bits));
            break;
        }
        default: break;
    }
}

// "1.25", ".85", "-.85", "35".
void format_value(char* buf, size_t n, float v, int decimals) {
    char tmp[32];
    if (decimals < 0) decimals = 0;
    if (decimals > 3) decimals = 3;
    snprintf(tmp, sizeof(tmp), "%.*f", decimals, static_cast<double>(clampf(fabsf(v), 0, 99999)));
    const char* s = (decimals > 0 && tmp[0] == '0' && tmp[1] == '.') ? tmp + 1 : tmp;
    snprintf(buf, n, "%s%s", v < 0 && strcmp(s, decimals ? ".00" : "0") ? "-" : "", s);
}
} // namespace

void draw_card(const app_scene_t* scene, int x, int y, uint32_t t_ms) {
    round_frame(x, y, CARD_W, CARD_H, DARK);
    if (scene == nullptr) {
        // Cancel: a plain X.
        for (int i = 0; i < 17; i++) {
            fill(x + 52 + i, y + 24 + i, 2, 1, GREY);
            fill(x + 67 - i, y + 24 + i, 2, 1, GREY);
        }
        return;
    }
    fill(x + 63, y + 6, 1, 52, DARK); // canvas | feature list
    for (int i = 0; i < scene->n_base; i++) element(scene->base[i], x, y);
    if (scene->n_frames == 0) return;
    uint32_t total = 0;
    for (int i = 0; i < scene->n_frames; i++) total += scene->frames[i].ms;
    uint32_t m = total ? t_ms % total : 0;
    const app_keyframe_t* kf = &scene->frames[scene->n_frames - 1];
    for (int i = 0; i < scene->n_frames; i++) {
        if (m < scene->frames[i].ms) { kf = &scene->frames[i]; break; }
        m -= scene->frames[i].ms;
    }
    for (int i = 0; i < kf->n; i++) element(kf->el[i], x, y);
}

void draw_param(const ParamView& v) {
    text(v.name, CX, 24, GREY, 1, CENTER);
    fill(60, 40, 120, 1, DARK);
    const int x0 = CX - CARD_W / 2 + v.nudge, y0 = 46;
    round_frame(x0, y0, CARD_W, CARD_H, DARK);
    fill(x0 + 63, y0 + 6, 1, 52, DARK);
    clip(x0 + 4, y0 + 4, 57, 56);
    param_visual(v, x0, y0);
    unclip();
    if (v.field) {
        // Onshape: the feature list, the new feature amber above the rollback bar.
        static const uint8_t G[3] = {APP_GLYPH_SKETCH, APP_GLYPH_SOLID, APP_GLYPH_SOLID};
        static const uint8_t LEN[3] = {14, 18, 16};
        for (int i = 0; i < 3; i++) {
            app_el_t r;
            memset(&r, 0, sizeof(r));
            r.op = APP_EL_ROW; r.y = static_cast<int8_t>(i); r.arg = G[i]; r.w = LEN[i]; r.d = 2;
            r.color = static_cast<uint8_t>(i == 2 ? APP_C_AMBER : APP_C_GREY);
            row(r, x0, y0);
        }
        rollback(x0, y0, 3, 2);
    } else if (v.axes) {
        // Plasticity: the selection modes, then X / Y / Z chips (lit: the axis, a plane's two, all three).
        modes(v.modes, x0, y0);
        static const char* const XYZ[3] = {"X", "Y", "Z"};
        for (int i = 0; i < 3; i++) {
            const bool on = (v.axis_bits & (1 << i)) != 0;
            const int x = x0 + 68 + i * 16;
            cut(x, y0 + 20, 14, 11, on ? AMBER : DARK);
            text(XYZ[i], x + 7.0f, static_cast<float>(y0 + 22), on ? BLACK : GREY, 1, CENTER);
        }
    } else {
        modes(v.modes, x0, y0);
        app_el_t r;
        memset(&r, 0, sizeof(r));
        r.op = APP_EL_ROW; r.color = APP_C_WHITE; r.w = 18; r.h = APP_ROW_SEL; r.arg = APP_GLYPH_SOLID; r.d = 14;
        row(r, x0, y0);
    }

    text(v.label, CX, 114, AMBER, 1, CENTER);
    char val[40];
    format_value(val, sizeof(val), v.value, v.decimals);
    if (v.field && !v.typed && v.value > 0) { // A shows the change: +0.30
        char plus[44];
        snprintf(plus, sizeof(plus), "+%s", val);
        memcpy(val, plus, sizeof(val) - 1);
        val[sizeof(val) - 1] = 0;
    }
    const int vw = text(val, CX, 126, WHITE, 3, CENTER);
    if (v.degrees) frame_box(static_cast<int>(lroundf(CX + vw / 2.0f)) + 3, 126, 5, 5, WHITE);

    // Number field: F1 .01 / KNOB .10 / F4 1.0. A handle: FREE / F1 / F2 / F4 (the knob alone is free). The live
    // one amber.
    char labels[4][24];
    int n = 0;
    if (!v.field) snprintf(labels[n++], sizeof(labels[0]), "FREE");
    static const char* const KEYS[3] = {"F1", "KNOB", "F4"};
    static const char* const HANDLE_KEYS[3] = {"F1", "F2", "F4"};
    for (int i = 0; i < 3; i++) {
        char st[16];
        if (v.degrees) snprintf(st, sizeof(st), "%d", static_cast<int>(lroundf(v.steps[i])));
        else if (v.steps[i] < 1) format_value(st, sizeof(st), v.steps[i], 2);
        else snprintf(st, sizeof(st), "%.1f", static_cast<double>(v.steps[i]));
        snprintf(labels[n++], sizeof(labels[0]), "%s %s", v.field ? KEYS[i] : HANDLE_KEYS[i], st);
    }
    // The frame's step: 0 button 1 held, 1 the knob alone, 2 button 4 held (a handle: the knob alone is FREE).
    static const int HANDLE_LIT[3] = {1, 0, 3};
    const int lit = v.field ? v.step : (v.step >= 0 && v.step <= 2 ? HANDLE_LIT[v.step] : -1);
    const int GAP = 10;
    int tw = -GAP;
    for (int i = 0; i < n; i++) tw += text_width(labels[i]) + GAP;
    float tx = static_cast<float>(lroundf(CX - tw / 2.0f));
    for (int i = 0; i < n; i++) {
        text(labels[i], tx, 157, i == lit ? AMBER : DARK);
        tx += text_width(labels[i]) + GAP;
    }
    if (v.f3 >= 0) {
        text(v.f3 >= 1 ? "RELEASE: CANCEL" : "RELEASE: OK", CX, 175, AMBER, 1, CENTER);
        fill(80, 189, 80, 2, DARK);
        fill(80, 189, static_cast<int>(lroundf(80 * clampf(v.f3, 0, 1))), 2, AMBER);
    } else {
        text("F3 OK  HOLD F3 CANCEL", CX, 175, GREY, 1, CENTER);
        if (v.field) text(v.typed ? "F2  B: TYPE" : "F2  A: SCROLL", CX, 189, GREY, 1, CENTER);
        else if (v.axes) text("TAP F1 F2 F4: X Y Z", CX, 189, GREY, 1, CENTER);
    }
}

namespace {
void chord(uint8_t modifier, const char* key, float cx, int y, const char* tail, uint32_t ink) {
    // Windows order: Win, Ctrl, Alt, Shift, then the key.
    const char* caps[4];
    int n = 0;
    if (modifier & APP_MOD_WIN) caps[n++] = "WIN";
    if (modifier & APP_MOD_CTRL) caps[n++] = "CTRL";
    if (modifier & APP_MOD_ALT) caps[n++] = "ALT";
    if (modifier & APP_MOD_SHIFT) caps[n++] = nullptr;   // the shift arrow
    const int cap = 13, gap = 3;
    int widths[4];
    int total = 0;
    for (int i = 0; i < n; i++) {
        widths[i] = caps[i] ? text_width(caps[i]) + 6 : cap;
        total += widths[i] + gap;
    }
    int kw = key ? text_width(key) + 6 : 0;
    if (key && kw < cap) kw = cap;
    const int tw = tail ? 6 + text_width(tail) : 0;
    total += kw + tw - (key ? 0 : gap);
    int x = static_cast<int>(lroundf(cx - total / 2.0f));
    for (int i = 0; i < n; i++) {
        cut(x, y, widths[i], cap, DARK);
        if (caps[i]) text(caps[i], x + widths[i] / 2.0f, static_cast<float>(y + 3), ink, 1, CENTER);
        else sprite(G_SHIFT, static_cast<float>(x + (cap - G_SHIFT.w) / 2), static_cast<float>(y + 3), ink);
        x += widths[i] + gap;
    }
    if (key) {
        cut(x, y, kw, cap, DARK);
        text(key, x + kw / 2.0f, static_cast<float>(y + 3), ink, 1, CENTER);
        x += kw;
    }
    if (tail) text(tail, static_cast<float>(x + 6), static_cast<float>(y + 3), GREY);
}
} // namespace

void draw_chord(uint8_t modifier, const char* key, float cx, int y, const char* tail) {
    chord(modifier, key, cx, y, tail, WHITE);
}

void draw_wheel(const WheelView& v) {
    text(v.ring_name, CX, 24, GREY, 1, CENTER);
    fill(60, 40, 120, 1, DARK);
    // The card slides like a carousel: the old one leaves, the new one comes in.
    const int CARD_Y = 50, TRAVEL = 128;
    const int off = static_cast<int>(lroundf((1 - v.slide) * v.slide_dir * TRAVEL));
    if (v.prev_valid && v.slide < 1) draw_card(v.prev, CX - CARD_W / 2 + off - v.slide_dir * TRAVEL, CARD_Y, 100000);
    draw_card(v.scene, CX - CARD_W / 2 + off, CARD_Y, v.t_ms);
    if (v.entry > 0) sprite(SPR_TRI_L_M, 22, static_cast<float>(CARD_Y + 28), AMBER);
    if (v.entry < v.count - 1) sprite(SPR_TRI_R_M, 214, static_cast<float>(CARD_Y + 28), AMBER);

    text(v.name, CX, 122, v.disabled ? GREY : WHITE, fit_scale(v.name, 170, 2), CENTER);
    if (v.entry == 0) text("RELEASE TO CLOSE", CX, 148, GREY, 1, CENTER);
    else if (!v.macro) chord(v.modifier, v.key, CX, 145, v.search ? "SEARCH" : nullptr, v.disabled ? GREY : WHITE);

    // Entry dots: 8 px apart while they fit 160 px (Onshape's rings), else 5 px (a 32-command ring: 33 dots).
    const int pitch = v.count * 8 - 4 <= 160 ? 8 : 5, dot = pitch == 8 ? 4 : 3;
    const int dots_w = v.count * pitch - (pitch - dot);
    for (int i = 0; i < v.count; i++)
        fill(static_cast<int>(lroundf(CX - dots_w / 2.0f)) + i * pitch, 170, dot, dot, i == v.entry ? AMBER : DARK);
    // Ring tabs: all of them while they fit 176 px, else the open ring's neighbours that fit around it.
    const int TAB_GAP = 9, TABS_MAX = 176;
    int lo = 0, hi = v.ring_count - 1;
    int tabs_w = -TAB_GAP;
    for (int i = 0; i < v.ring_count; i++) tabs_w += text_width(v.ring_tabs[i]) + TAB_GAP;
    if (tabs_w > TABS_MAX && v.ring >= 0 && v.ring < v.ring_count) {
        lo = hi = v.ring;
        tabs_w = text_width(v.ring_tabs[v.ring]);
        for (bool grew = true; grew;) {
            grew = false;
            if (hi + 1 < v.ring_count && tabs_w + TAB_GAP + text_width(v.ring_tabs[hi + 1]) <= TABS_MAX) {
                tabs_w += TAB_GAP + text_width(v.ring_tabs[++hi]);
                grew = true;
            }
            if (lo > 0 && tabs_w + TAB_GAP + text_width(v.ring_tabs[lo - 1]) <= TABS_MAX) {
                tabs_w += TAB_GAP + text_width(v.ring_tabs[--lo]);
                grew = true;
            }
        }
    }
    float tx = static_cast<float>(lroundf(CX - tabs_w / 2.0f));
    for (int i = lo; i <= hi; i++) {
        text(v.ring_tabs[i], tx, 188, i == v.ring ? AMBER : DARK);
        tx += text_width(v.ring_tabs[i]) + TAB_GAP;
    }
}

} // namespace ccui
