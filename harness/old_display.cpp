// Reproduces the host LCD renderer shipped before the instrument redesign.
// Copied from lcd_thread.cpp on 2026-09-22; only device/session plumbing omitted.
#include "lvgl.h"
#include "cc_presentation.h"
#include <cstring>

namespace {
lv_obj_t* screen = nullptr;
lv_obj_t* labels[9] = {};
lv_obj_t* label(int x, int y, int w, int h, const lv_font_t* font) {
    lv_obj_t* obj = lv_label_create(screen);
    lv_obj_set_pos(obj, x, y); lv_obj_set_size(obj, w, h);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(obj, lv_color_hex(0xF2F6F8), 0);
    lv_label_set_long_mode(obj, LV_LABEL_LONG_DOT);
    return obj;
}
}

lv_obj_t* old_display_create() {
    screen = lv_obj_create(nullptr);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x071015), 0);
    labels[0] = label(45, 24, 150, 18, &lv_font_montserrat_12);
    labels[1] = label(32, 45, 176, 22, &lv_font_montserrat_16);
    labels[2] = label(28, 76, 184, 54, &lv_font_montserrat_22);
    labels[3] = label(32, 132, 176, 32, &lv_font_montserrat_14);
    labels[4] = label(42, 161, 156, 16, &lv_font_montserrat_12);
    for (int i = 0; i < 4; ++i) labels[5 + i] = label(30 + i * 45, 178, 45, 25, &lv_font_montserrat_12);
    return screen;
}

void old_display_render(const CCFrame& frame) {
    const char* texts[] = {frame.mode, frame.target, frame.value, frame.detail, frame.status};
    bool numeric = strlen(frame.value) > 0 && strlen(frame.value) <= 6;
    for (const char* p = frame.value; *p; ++p) {
        if ((*p < '0' || *p > '9') && *p != '%' && *p != '.') numeric = false;
    }
    lv_obj_set_style_text_font(labels[2], numeric ? &lv_font_montserrat_32 : &lv_font_montserrat_22, 0);
    for (int i = 0; i < 5; ++i) lv_label_set_text(labels[i], texts[i]);
    for (int i = 0; i < 4; ++i) {
        lv_label_set_text(labels[5 + i], frame.buttons[i].label);
        lv_obj_set_style_text_color(labels[5 + i], lv_color_hex(frame.buttons[i].enabled ? frame.buttons[i].color : 0x72828E), 0);
    }
}
