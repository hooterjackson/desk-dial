// App canvas: the main app screen and the idle plasma (cc_app_ui.h).
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/ui_screens.cpp (draw_app_top, app_badge, draw_legend: the APP-mode main screen, with its
// shape and label visuals), ui_fx.cpp (fx_attract's plasma rippling out of the profile's 48 px icon) and
// app_colors.c (app_accents: the plasma colours sampled from the icon). The plasma's tables live in a
// caller-owned PlasmaTables (PSRAM on the knob) instead of static arrays.
#include "cc_app_ui.h"
#include <math.h>
#include <string.h>

namespace ccui {

namespace {
// 24x24 app icon + name, centred on (cx, cy).
void app_badge(const char* name, const uint8_t* icon, float cx, float cy, uint32_t c) {
    const int tw = text_width(name), total = (icon ? 24 + 6 : 0) + tw;
    const int x0 = static_cast<int>(lroundf(cx - total / 2.0f));
    if (icon) image565(x0, static_cast<int>(lroundf(cy - 12)), 24, 24, icon);
    text(name, static_cast<float>(x0 + (icon ? 30 : 0)), cy - 3, c);
}

const char* refusal(const AppView& v) {
    if (v.generic) return v.refusedFocus ? "CLICK THE APP FIRST" : "POINT AT THE APP";
    return v.refusedFocus ? "CLICK MODEL FIRST" : "POINT AT MODEL";
}

float luma(uint32_t c) {
    return 0.30f * ((c >> 16) & 0xFF) + 0.59f * ((c >> 8) & 0xFF) + 0.11f * (c & 0xFF);
}

void legend(const AppView& v) {
    static const char* const keys[4] = {"F1", "F2", "F3", "F4"};
    static const int xs[4] = {60, 100, 140, 180};
    static const int ys[4] = {146, 154, 154, 146};
    for (int i = 0; i < 4; i++) {
        const char* act = v.legend[i] ? v.legend[i] : "";
        const bool disabled = act[0] == '\0';
        keycap(xs[i] - KEY_W / 2, ys[i], keys[i], ((v.buttons_held >> i) & 1) != 0, disabled);
        text(disabled ? "--" : act, static_cast<float>(xs[i]), static_cast<float>(ys[i] + KEY_H + 5),
             disabled ? GREY : WHITE, 1, CENTER);
    }
}
} // namespace

void draw_app_main(const AppView& v) {
    app_badge(v.name, v.icon24, CX, 36, WHITE);
    fill(56, 52, 128, 1, DARK);
    if (v.echo) {
        if (v.echo_scene != nullptr) {
            draw_card(v.echo_scene, CX - CARD_W / 2, 56, v.echo_ms);
            text(v.echo_name, CX, 124, AMBER, 1, CENTER);
        } else {
            text(v.echo_name, CX, 92, AMBER, fit_scale(v.echo_name, 176, 2), CENTER);
        }
    } else if (v.shape != nullptr) {
        // The shape follows the knob; under it, key (grey) + action.
        shape_scene(*v.shape);
        if (v.refused) {
            text(refusal(v), CX, 131, AMBER, 1, CENTER);
        } else {
            const int kw = text_width(v.action_key), aw = text_width(v.action);
            const float lx = static_cast<float>(lroundf(CX - (kw + 7 + aw) / 2.0f));
            text(v.action_key, lx, 131, GREY);
            text(v.action, lx + kw + 7, 131, v.flash ? AMBER : WHITE);
        }
    } else if (v.action != nullptr && v.action[0] != '\0') {
        // The label visual (Figma): how (grey) over what the knob does now, large.
        text(v.action_via ? v.action_via : "", CX, 82, GREY, 1, CENTER);
        text(v.action, CX, 98, v.flash ? AMBER : WHITE, fit_scale(v.action, 176, 3), CENTER);
        if (v.refused) text(refusal(v), CX, 131, AMBER, 1, CENTER);
    } else {
        // The label visual with nothing live to name: the app itself, its 48 px icon over its name, large.
        if (v.icon48 != nullptr) image565(CX - 24, 60, 48, 48, v.icon48);
        text(v.name, CX, v.icon48 != nullptr ? 114.0f : 86.0f, WHITE, fit_scale(v.name, 176, 2), CENTER);
        if (v.refused) text(refusal(v), CX, 131, AMBER, 1, CENTER);
    }
    legend(v);
}

void draw_loading() {
    // Neutral: nothing of the profile (it is not here yet), the same rule as the app screen's status bar.
    fill(56, 52, 128, 1, DARK);
    text("LOADING...", CX, 112, GREY, 2, CENTER);
}

void app_accents(const uint8_t* icon, const uint32_t* heat, uint32_t out[3]) {
    if (heat && (heat[0] | heat[1] | heat[2])) {
        for (int i = 0; i < 3; i++) out[i] = heat[i];
        return;
    }
    for (int i = 0; i < 3; i++) out[i] = AMBER;
    if (icon == nullptr) return;
    // The icon's three most common colours, dark to bright, exactly as sampled. Pixels are binned coarsely (3 bits
    // per channel) so the shading of one colour counts as one; near-black (outlines) is skipped.
    struct Bin { uint16_t key; uint16_t n; uint32_t r, g, b; } bins[32];   // pixel art has few colours
    int nb = 0;
    for (int i = 0; i < 48 * 48; i++) {
        const uint16_t v = static_cast<uint16_t>(icon[i * 2] << 8 | icon[i * 2 + 1]);
        const uint32_t r = ((v >> 11) & 31) * 255 / 31, g = ((v >> 5) & 63) * 255 / 63, b = (v & 31) * 255 / 31;
        if (r + g + b < 90) continue;   // black / outline
        const uint16_t key = static_cast<uint16_t>((r >> 5) << 6 | (g >> 5) << 3 | (b >> 5));
        int k = 0;
        while (k < nb && bins[k].key != key) k++;
        if (k == nb) {
            if (nb == 32) continue;     // overflow pixels are simply not counted
            bins[nb].key = key; bins[nb].n = 0; bins[nb].r = bins[nb].g = bins[nb].b = 0;
            nb++;
        }
        bins[k].n++; bins[k].r += r; bins[k].g += g; bins[k].b += b;
    }
    uint32_t pick[3];
    int np = 0;
    for (; np < 3; np++) {
        int best = -1;
        for (int k = 0; k < nb; k++)
            if (bins[k].n && (best < 0 || bins[k].n > bins[best].n)) best = k;
        if (best < 0) break;
        pick[np] = (bins[best].r / bins[best].n) << 16 | (bins[best].g / bins[best].n) << 8 | (bins[best].b / bins[best].n);
        bins[best].n = 0;
    }
    if (np == 0) return;
    for (; np < 3; np++) pick[np] = pick[np - 1];   // fewer colours: repeat the last
    for (int i = 1; i < 3; i++)
        for (int j = i; j > 0 && luma(pick[j]) < luma(pick[j - 1]); j--) {
            const uint32_t t = pick[j];
            pick[j] = pick[j - 1];
            pick[j - 1] = t;
        }
    for (int i = 0; i < 3; i++) out[i] = pick[i];
}

// --- idle plasma ---

namespace {
const float kPi = 3.14159265358979f;
const int SIN_LUT = 256;
const float TO_UNITS = SIN_LUT / (2.0f * kPi);
const int ICON = 48, ICON_SCALE = 2;
const int ICON_X = CX - ICON * ICON_SCALE / 2, ICON_Y = CY - ICON * ICON_SCALE / 2;
const uint32_t BODY[4] = {BLACK, DARK, GREY, WHITE};
const float HEAT_AT[3] = {0.54f, 0.62f, 0.71f};
const float HEAT_BODY_GAIN = 6.0f;

inline float lut(const PlasmaTables& t, float units) { return t.sine[static_cast<int>(units) & (SIN_LUT - 1)]; }
inline bool seed_at(const PlasmaTables& t, int idx) { return (t.seed[idx >> 3] & (1 << (idx & 7))) != 0; }

// Distance field from the icon's cells: only outline seeds are measured against (a few ms, once per icon).
void build_field(PlasmaTables& t, const uint8_t* icon) {
    memset(t.seed, 0, sizeof(t.seed));
    for (int j = 0; j < ICON; j++) {
        for (int i = 0; i < ICON; i++) {
            const uint8_t* px = icon + (j * ICON + i) * 2;
            if (px[0] == 0 && px[1] == 0) continue; // black = transparent
            const int sx = ICON_X + i * ICON_SCALE, sy = ICON_Y + j * ICON_SCALE;
            const int idx = (sy / PLASMA_CELL) * PLASMA_N + sx / PLASMA_CELL;
            t.seed[idx >> 3] |= static_cast<uint8_t>(1 << (idx & 7));
        }
    }
    int ne = 0;
    for (int gy = 0; gy < PLASMA_N; gy++) {
        for (int gx = 0; gx < PLASMA_N; gx++) {
            const int idx = gy * PLASMA_N + gx;
            if (!seed_at(t, idx)) continue;
            const bool outline = gx == 0 || gy == 0 || gx == PLASMA_N - 1 || gy == PLASMA_N - 1 || !seed_at(t, idx - 1) ||
                                 !seed_at(t, idx + 1) || !seed_at(t, idx - PLASMA_N) || !seed_at(t, idx + PLASMA_N);
            if (outline && ne < PLASMA_MAX_EDGE) t.edge[ne++] = static_cast<int16_t>(idx);
        }
    }
    for (int idx = 0; idx < PLASMA_CELLS; idx++) {
        if (seed_at(t, idx) || ne == 0) {
            t.dist[idx] = seed_at(t, idx) ? 0 : 255;
            continue;
        }
        const int gx = idx % PLASMA_N, gy = idx / PLASMA_N;
        int best = 1 << 30;
        for (int k = 0; k < ne; k++) {
            const int dx = gx - t.edge[k] % PLASMA_N, dy = gy - t.edge[k] / PLASMA_N;
            const int d2 = dx * dx + dy * dy;
            if (d2 < best) best = d2;
        }
        const float d = sqrtf(static_cast<float>(best)) * PLASMA_CELL;
        t.dist[idx] = static_cast<uint8_t>(d > 255 ? 255 : d);
    }
    t.dist_for = icon;
}
} // namespace

void plasma_init(PlasmaTables& t) {
    memset(&t, 0, sizeof(t));
    for (int i = 0; i < SIN_LUT; i++) t.sine[i] = sinf(i * 2.0f * kPi / SIN_LUT);
    for (int d = 0; d < 256; d++) t.glow[d] = 1.25f * expf(-d / 34.0f) + 0.15f;
    for (int gy = 0; gy < PLASMA_N; gy++) {
        for (int gx = 0; gx < PLASMA_N; gx++) {
            const int idx = gy * PLASMA_N + gx;
            const float x = gx * PLASMA_CELL + 2.0f, y = gy * PLASMA_CELL + 2.0f;
            if ((x - CX) * (x - CX) + (y - CY) * (y - CY) <= 118.0f * 118.0f)
                t.mask[idx >> 3] |= static_cast<uint8_t>(1 << (idx & 7));
        }
    }
    t.ready = true;
}

void draw_plasma(PlasmaTables& t, uint32_t t_ms, const uint8_t* icon48, const uint32_t* heat_in, uint32_t key) {
    if (!t.ready) plasma_init(t);
    if (icon48 == nullptr) return;
    if (t.dist_for != icon48 || t.key != key) {
        build_field(t, icon48);
        app_accents(icon48, heat_in, t.accents);
        t.key = key;
    }
    const uint32_t* heat = t.accents;
    static const uint8_t bayer[4] = {0, 2, 3, 1};
    const float T = t_ms / 1000.0f;
    const float p1 = T * 0.6f * TO_UNITS, p2 = -T * 0.8f * TO_UNITS, p4 = -T * 2.4f * TO_UNITS;
    for (int gy = 0; gy < PLASMA_N; gy++) {
        const float y = gy * PLASMA_CELL + 2.0f;
        const float sy = lut(t, y / 17.0f * TO_UNITS + p2 + 1024);
        for (int gx = 0; gx < PLASMA_N; gx++) {
            const int idx = gy * PLASMA_N + gx;
            if (!(t.mask[idx >> 3] & (1 << (idx & 7)))) continue;
            const uint8_t d = t.dist[idx];
            if (d < 5) continue; // black halo keeps the icon readable
            const float x = gx * PLASMA_CELL + 2.0f;
            const float ripple = lut(t, d / 9.0f * TO_UNITS + p4 + 1024);
            const float drift = 0.5f * (lut(t, x / 23.0f * TO_UNITS + p1) + sy);
            float v = (ripple + drift + 2.0f) / 4.0f;
            v = v * v;
            v = v * v * t.glow[d];
            const float f = v * HEAT_BODY_GAIN;
            int li = static_cast<int>(f);
            if (f - li > (bayer[(gx & 1) + 2 * (gy & 1)] + 0.5f) / 4.0f) li++;
            if (li > 3) li = 3;
            uint32_t c = BODY[li];
            for (int h = 0; h < 3; h++) if (v >= HEAT_AT[h]) c = heat[h];
            if (c != BLACK) fill(gx * PLASMA_CELL, gy * PLASMA_CELL, PLASMA_CELL, PLASMA_CELL, c);
        }
    }
    image565(ICON_X, ICON_Y, ICON, ICON, icon48, 1.0f, ICON_SCALE);
}

} // namespace ccui
