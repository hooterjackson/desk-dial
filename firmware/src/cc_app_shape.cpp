// App canvas: the isometric shape that follows the knob (cc_app_ui.h shape_scene).
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/ui_shape.cpp -- same projection (orthographic, 30 deg down, 2:1 isometric at 45 deg yaw),
// same meshes (cube, pyramid, octahedron), styles (R3C "selected face", R2C "CAD grips", R4A "Thick"), scenes
// and numbers. Ours adds the view's pitch (Desk Dial 7.2.2.0's tilt; SHAPE_REST_PITCH is Karl's fixed 30 deg)
// and the tilt scene. App profiles (plan section 1e): the mesh and the style come from the profile; the built-in
// Onshape is the cube in R4A "Thick", drawn exactly as before (goldens/app_canvas).
#include "cc_app_ui.h"
#include <math.h>
#include <stdlib.h>

namespace ccui {

namespace {
const float kPi = 3.14159265358979f;

// --- meshes: vertices + faces (up to 4 corners; -1 = unused) + their edges ---
struct Edge {
    uint8_t a, b;
    int8_t f0, f1;   // the (up to two) faces sharing the edge
};
struct Mesh {
    const float (*v)[3];
    int nv;
    const int8_t (*f)[4];
    int nf;
    const Edge* e;   // derived from the faces in Karl's order (edges_of()), kept as constant data
    int ne;
};
const float CUBE_V[8][3] = {{-1, -1, -1}, {1, -1, -1}, {1, 1, -1}, {-1, 1, -1},
                            {-1, -1, 1},  {1, -1, 1},  {1, 1, 1},  {-1, 1, 1}};
const int8_t CUBE_F[6][4] = {{0, 1, 2, 3}, {4, 5, 6, 7}, {0, 1, 5, 4}, {2, 3, 7, 6}, {1, 2, 6, 5}, {0, 3, 7, 4}};
const Edge CUBE_E[12] = {{0, 1, 0, 2}, {1, 2, 0, 4}, {2, 3, 0, 3}, {0, 3, 0, 5}, {4, 5, 1, 2}, {5, 6, 1, 4},
                         {6, 7, 1, 3}, {4, 7, 1, 5}, {1, 5, 2, 4}, {0, 4, 2, 5}, {3, 7, 3, 5}, {2, 6, 3, 4}};
const float PYR_V[5][3] = {{-1, -0.8f, -1}, {1, -0.8f, -1}, {1, -0.8f, 1}, {-1, -0.8f, 1}, {0, 1.2f, 0}};
const int8_t PYR_F[5][4] = {{0, 1, 2, 3}, {0, 1, 4, -1}, {1, 2, 4, -1}, {2, 3, 4, -1}, {3, 0, 4, -1}};
const Edge PYR_E[8] = {{0, 1, 0, 1}, {1, 2, 0, 2}, {2, 3, 0, 3}, {0, 3, 0, 4},
                       {1, 4, 1, 2}, {0, 4, 1, 4}, {2, 4, 2, 3}, {3, 4, 3, 4}};
const float OCTA_V[6][3] = {{1.3f, 0, 0}, {-1.3f, 0, 0}, {0, 1.3f, 0}, {0, -1.3f, 0}, {0, 0, 1.3f}, {0, 0, -1.3f}};
const int8_t OCTA_F[8][4] = {{0, 2, 4, -1}, {0, 4, 3, -1}, {0, 3, 5, -1}, {0, 5, 2, -1},
                             {1, 4, 2, -1}, {1, 3, 4, -1}, {1, 5, 3, -1}, {1, 2, 5, -1}};
const Edge OCTA_E[12] = {{0, 2, 0, 3}, {2, 4, 0, 4}, {0, 4, 0, 1}, {3, 4, 1, 5}, {0, 3, 1, 2}, {3, 5, 2, 6},
                         {0, 5, 2, 3}, {2, 5, 3, 7}, {1, 4, 4, 5}, {1, 2, 4, 7}, {1, 3, 5, 6}, {1, 5, 6, 7}};
const Mesh MESHES[3] = {{CUBE_V, 8, CUBE_F, 6, CUBE_E, 12}, {PYR_V, 5, PYR_F, 5, PYR_E, 8},
                        {OCTA_V, 6, OCTA_F, 8, OCTA_E, 12}};
const int MAX_V = 8, MAX_F = 8;

inline int corners(const int8_t* f) { return f[3] < 0 ? 3 : 4; }

inline void put(float x, float y, uint32_t c) {
    fill(static_cast<int>(x), static_cast<int>(y), 1, 1, c);   // truncate, like the preview's `x | 0`
}

// dashed: 2 pixels on, 2 off. pen: an even 2 px line (a vertical pair on shallow lines, a horizontal pair on
// steep ones).
void line(float fx0, float fy0, float fx1, float fy1, uint32_t c, bool dashed, bool pen) {
    int x0 = static_cast<int>(lroundf(fx0)), y0 = static_cast<int>(lroundf(fy0));
    const int x1 = static_cast<int>(lroundf(fx1)), y1 = static_cast<int>(lroundf(fy1));
    const int dx = abs(x1 - x0), dy = -abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    const bool shallow = dx >= -dy;
    int err = dx + dy;
    for (int n = 0;; n++) {
        if (!dashed || (n & 3) < 2) {
            if (pen) fill(x0, y0, shallow ? 1 : 2, shallow ? 2 : 1, c);
            else fill(x0, y0, 1, 1, c);
        }
        if (x0 == x1 && y0 == y1) break;
        const int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

// Convex polygon fill: SPARSE = one GREY pixel in four (even x, even y), CHECKER = GREY checkerboard ((x + y)
// even), SOLID = plain DARK (one fill per row).
enum FillMode { FILL_SPARSE, FILL_CHECKER, FILL_SOLID };
void fill_pattern(const float (*p)[2], int n, FillMode mode) {
    const bool sparse = mode == FILL_SPARSE;
    float y0 = 1e9f, y1 = -1e9f;
    for (int i = 0; i < n; i++) {
        if (p[i][1] < y0) y0 = p[i][1];
        if (p[i][1] > y1) y1 = p[i][1];
    }
    for (int y = static_cast<int>(floorf(y0)); y <= static_cast<int>(ceilf(y1)); y++) {
        const float py = y + 0.5f;
        float lo = 1e9f, hi = -1e9f;
        for (int i = 0; i < n; i++) {
            const float ax = p[i][0], ay = p[i][1], bx = p[(i + 1) % n][0], by = p[(i + 1) % n][1];
            if ((ay <= py && by > py) || (by <= py && ay > py)) {
                const float x = ax + (py - ay) / (by - ay) * (bx - ax);
                if (x < lo) lo = x;
                if (x > hi) hi = x;
            }
        }
        if (lo > hi || (sparse && (y & 1))) continue;
        const int xa = static_cast<int>(ceilf(lo - 0.5f)), xb = static_cast<int>(floorf(hi - 0.5f));
        if (mode == FILL_SOLID) {
            fill(xa, y, xb - xa + 1, 1, DARK);
            continue;
        }
        for (int x = xa; x <= xb; x++)
            if (sparse ? !(x & 1) : !((x + y) & 1)) fill(x, y, 1, 1, GREY);
    }
}

const float ISO_K = 0.86f;

uint32_t tone_color(float t) { return t >= 0.85f ? WHITE : t >= 0.5f ? GREY : DARK; }

void face_poly(const Mesh& m, int fi, const float (*scr)[2], float (*poly)[2]) {
    for (int i = 0; i < corners(m.f[fi]); i++) {
        poly[i][0] = scr[m.f[fi][i]][0];
        poly[i][1] = scr[m.f[fi][i]][1];
    }
}

// `detail` (the main copy only) adds the face fill, hidden edges and grips.
void draw_shape(uint8_t kind, uint8_t style, float cx, float cy, float size, float yaw, float pitch, float tone,
                bool detail, bool amber) {
    const Mesh& m = MESHES[kind <= APP_SHAPE_OCTA ? kind : 0];
    const float cyw = cosf(yaw), syw = sinf(yaw), cp = cosf(pitch), sp = sinf(pitch);
    float view[MAX_V][3], scr[MAX_V][2];
    for (int i = 0; i < m.nv; i++) {
        const float x = m.v[i][0], y = m.v[i][1], z = m.v[i][2];
        const float x1 = x * cyw + z * syw, z1 = -x * syw + z * cyw;
        view[i][0] = x1;
        view[i][1] = y * cp - z1 * sp;
        view[i][2] = y * sp + z1 * cp;
        scr[i][0] = cx + view[i][0] * ISO_K * size;
        scr[i][1] = cy - view[i][1] * ISO_K * size;
    }
    bool vis[MAX_F];
    float fy[MAX_F], fz[MAX_F];
    int top = -1, nearest = -1;
    for (int fi = 0; fi < m.nf; fi++) {
        const int8_t* f = m.f[fi];
        const int c = corners(f);
        const float *p0 = view[f[0]], *p1 = view[f[1]], *p2 = view[f[2]];
        const float u[3] = {p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]};
        const float w[3] = {p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]};
        float n[3] = {u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]};
        float fc[3] = {0, 0, 0};
        for (int i = 0; i < c; i++)
            for (int j = 0; j < 3; j++) fc[j] += view[f[i]][j] / c;
        if (n[0] * fc[0] + n[1] * fc[1] + n[2] * fc[2] < 0) { n[0] = -n[0]; n[1] = -n[1]; n[2] = -n[2]; }
        const float len = sqrtf(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
        vis[fi] = len > 0 && n[2] / len > 1e-6f;   // orthographic: faces the viewer
        fy[fi] = fc[1];
        fz[fi] = fc[2];
        if (vis[fi] && (top < 0 || fy[fi] > fy[top])) top = fi;
        if (vis[fi] && (nearest < 0 || fz[fi] > fz[nearest])) nearest = fi;
    }
    const Edge* e = m.e;
    const int ne = m.ne;
    const uint32_t edge_c = amber ? AMBER : tone_color(tone);
    float poly[4][2];

    if (style == APP_STYLE_GRIPS || style == APP_STYLE_THICK) {
        // R2C: checkered nearest face + dashed hidden edges, white edges, hollow grips on every visible corner.
        // R4A (thick): solid dark face and hidden edges, a 2 px pen, 6x6 grips.
        const bool thick = style == APP_STYLE_THICK;
        if (detail) {
            if (nearest >= 0) {
                face_poly(m, nearest, scr, poly);
                fill_pattern(poly, corners(m.f[nearest]), thick ? FILL_SOLID : FILL_CHECKER);
            }
            for (int k = 0; k < ne; k++)
                if (!(vis[e[k].f0] || (e[k].f1 >= 0 && vis[e[k].f1])))
                    line(scr[e[k].a][0], scr[e[k].a][1], scr[e[k].b][0], scr[e[k].b][1], DARK, !thick, false);
        }
        bool front_v[MAX_V] = {};
        for (int k = 0; k < ne; k++) {
            if (vis[e[k].f0] || (e[k].f1 >= 0 && vis[e[k].f1])) {
                line(scr[e[k].a][0], scr[e[k].a][1], scr[e[k].b][0], scr[e[k].b][1], edge_c, false, thick && detail);
                front_v[e[k].a] = front_v[e[k].b] = true;
            }
        }
        if (detail) {
            for (int i = 0; i < m.nv; i++) {
                if (!front_v[i]) continue;
                if (thick) {
                    rect(scr[i][0] - 3, scr[i][1] - 3, 6, 6, edge_c);
                    rect(scr[i][0] - 1, scr[i][1] - 1, 2, 2, BLACK);
                } else {
                    rect(scr[i][0] - 2, scr[i][1] - 2, 5, 5, edge_c);
                    rect(scr[i][0] - 1, scr[i][1] - 1, 3, 3, BLACK);
                }
            }
        }
        return;
    }
    // R3C "selected face": grey edges; the top face gets a sparse fill and white edges; hidden edges a faint dash.
    const uint32_t quiet = amber ? AMBER : tone >= 0.85f ? GREY : DARK;
    if (detail) {
        for (int k = 0; k < ne; k++) {
            if (vis[e[k].f0] || (e[k].f1 >= 0 && vis[e[k].f1])) continue;
            // a very faint dash: one pixel every 4 along the longer axis
            const float ax = scr[e[k].a][0], ay = scr[e[k].a][1], bx = scr[e[k].b][0], by = scr[e[k].b][1];
            const int n = static_cast<int>(fmaxf(fabsf(bx - ax), fabsf(by - ay)));
            const float dn = static_cast<float>(n ? n : 1);
            for (int s = 0; s <= n; s += 4) put(ax + (bx - ax) * s / dn, ay + (by - ay) * s / dn, DARK);
        }
        if (top >= 0) {
            face_poly(m, top, scr, poly);
            fill_pattern(poly, corners(m.f[top]), FILL_SPARSE);
        }
    }
    for (int k = 0; k < ne; k++)
        if (vis[e[k].f0] || (e[k].f1 >= 0 && vis[e[k].f1]))
            line(scr[e[k].a][0], scr[e[k].a][1], scr[e[k].b][0], scr[e[k].b][1], quiet, false, false);
    if (top >= 0 && detail) {
        const int8_t* f = m.f[top];
        const int c = corners(f);
        for (int i = 0; i < c; i++) {
            const int a = f[i], b = f[(i + 1) % c];
            line(scr[a][0], scr[a][1], scr[b][0], scr[b][1], edge_c, false, false);
        }
    }
}

const float SX = 120, SY = 90; // shape centre in the band

void scene_zoom(const ShapeView& v) {
    // Nested copies, each twice the last; the zoom phase slides them along (a seamless loop).
    const float frac = v.zoom - floorf(v.zoom);
    for (int i = -3; i <= 3; i++) {
        const float s = 7.0f * powf(2.0f, i + frac);
        if (s < 3 || s > 70) continue;
        const float tone = s < 6 ? 0.3f : s < 11 ? 0.6f : s <= 30 ? 1.0f : s <= 48 ? 0.6f : 0.3f;
        draw_shape(v.shape, v.style, SX, SY, s, v.yaw, v.pitch, tone, tone == 1.0f, v.flash);
    }
}

void scene_orbit(const ShapeView& v) {
    // A dotted ground ring with a marker chained to the knob.
    const float rx = 36, ry = 9, gy = SY + 26;
    for (int k = 0; k < 48; k++) {
        const float a = k * kPi / 24;
        put(SX + rx * cosf(a), gy + ry * sinf(a), GREY);
    }
    const float ma = v.yaw + kPi / 2;
    rect(SX + rx * cosf(ma) - 1, gy + ry * sinf(ma) - 1, 3, 3, AMBER);
    draw_shape(v.shape, v.style, SX, SY - 4, 19, v.yaw, v.pitch, 1.0f, true, v.flash);
}

void scene_tilt(const ShapeView& v) {
    // Orbit's ground ring stood on end beside the shape: the marker rides it at the view's pitch (rest 30 deg).
    const float rx = 9, ry = 30, gx = SX + 46, gy = SY - 4;
    for (int k = 0; k < 48; k++) {
        const float a = k * kPi / 24;
        put(gx + rx * cosf(a), gy + ry * sinf(a), GREY);
    }
    rect(gx + rx * cosf(v.pitch) - 1, gy - ry * sinf(v.pitch) - 1, 3, 3, AMBER);
    draw_shape(v.shape, v.style, SX, SY - 4, 19, v.yaw, v.pitch, 1.0f, true, v.flash);
}

void scene_pan(const ShapeView& v) {
    // Three rows of floor dots, farther rows slower (parallax); a row of shapes; all wrap.
    struct Row { float y, sp, par; uint32_t c; };
    static const Row rows[3] = {{112, 12, 0.5f, DARK}, {118, 16, 0.75f, GREY}, {125, 22, 1.0f, GREY}};
    for (int r = 0; r < 3; r++) {
        const float off = fmodf(fmodf(v.pan * rows[r].par, rows[r].sp) + rows[r].sp, rows[r].sp);
        for (float x = off - rows[r].sp; x < 240; x += rows[r].sp) put(x, rows[r].y, rows[r].c);
    }
    const float SP = 64;
    const float off = fmodf(fmodf(v.pan, SP) + SP, SP);
    for (float x = off - SP * 2; x < 240 + SP; x += SP) {
        const float d = fabsf(x - SX);
        if (d > 110) continue;
        const float tone = d < 26 ? 1.0f : d < 70 ? 0.6f : 0.3f;
        draw_shape(v.shape, v.style, x, SY, 14, v.yaw, v.pitch, tone, tone == 1.0f, v.flash);
    }
}
} // namespace

void shape_scene(const ShapeView& v) {
    clip(0, 55, 240, 73);
    switch (v.scene) {
        case SCENE_ORBIT: scene_orbit(v); break;
        case SCENE_PAN: scene_pan(v); break;
        case SCENE_TILT: scene_tilt(v); break;
        default: scene_zoom(v); break;
    }
    unclip();
}

} // namespace ccui
