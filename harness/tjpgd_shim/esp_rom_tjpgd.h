#pragma once
// Host shim for the ESP32-S3 ROM TJpgDec API (esp_rom/include/esp_rom_tjpgd.h, ESP-IDF 4.4,
// TJpgDec R0.01b in ROM) over LVGL's bundled TJpgDec R0.03 (lvgl/src/libs/tjpgd/tjpgd.c,
// compiled read-only from NanoD_RatchetH1/.pio/libdeps). It lets src/cc_jpeg.cpp compile
// unchanged in harness (jpeg_tests.py, media_tests.py). C++ only.
//
// Mapped: esp_rom_tjpgd_result_t (JRESULT, same values JDR_OK..JDR_FMT3),
// esp_rom_tjpgd_rect_t (JRECT, same fields), esp_rom_tjpgd_dec_t with the members cc_jpeg.cpp
// reads (device, width, height), the input/output function types and esp_rom_tjpgd_prepare /
// esp_rom_tjpgd_decomp. R0.03 takes size_t/int callbacks, so the user callbacks are called
// through two trampolines that recover the wrapper from the R0.03 object (its first member).
// Both versions output 24-bit pixels (JD_FORMAT 0); LVGL's copy emits them as B, G, R, so the
// output trampoline restores the ROM's R, G, B order. R0.03 is built with LVGL's tjpgdcnf.h
// (JD_USE_SCALE 0: only scale 0, which is all cc_jpeg.cpp uses). Where the two decoders
// differ in what they accept (R0.03 also takes grayscale and skips bytes before SOI),
// cc_jpeg.cpp's own marker pre-scan decides first, exactly as the ROM would.
#include <stddef.h>
#include <stdint.h>
#include "tjpgd.h"

typedef JRESULT esp_rom_tjpgd_result_t;
typedef JRECT esp_rom_tjpgd_rect_t;
typedef struct esp_rom_tjpgd_dec_s esp_rom_tjpgd_dec_t;
typedef uint32_t (*esp_rom_tjpgd_input_function_t)(esp_rom_tjpgd_dec_t* dec, uint8_t* buffer, uint32_t ndata);
typedef uint32_t (*esp_rom_tjpgd_output_function_t)(esp_rom_tjpgd_dec_t* dec, void* bitmap,
                                                    esp_rom_tjpgd_rect_t* rect);

struct esp_rom_tjpgd_dec_s {
    JDEC jd;                                  // first: the trampolines cast back from it
    uint32_t width, height;                   // the ROM object's fields, mirrored after prepare
    void* device;                             // the ROM object's I/O device pointer
    esp_rom_tjpgd_input_function_t infunc;
    esp_rom_tjpgd_output_function_t outfunc;
};

inline size_t cc_tjpgd_shim_input(JDEC* jd, uint8_t* buffer, size_t ndata) {
    esp_rom_tjpgd_dec_t* dec = reinterpret_cast<esp_rom_tjpgd_dec_t*>(jd);
    return dec->infunc(dec, buffer, static_cast<uint32_t>(ndata));
}

// LVGL's copy of R0.03 was modified to emit B, G, R per pixel (its mcu_output: "*pix++ = /*B*/"),
// while the ROM's R0.01b (ChaN's original, as ESP-IDF's own TJpgDec examples read it) emits
// R, G, B. The block is swapped back in place (it is the decoder's work buffer, rewritten for
// every MCU) before the user output function sees it.
inline int cc_tjpgd_shim_output(JDEC* jd, void* bitmap, JRECT* rect) {
    esp_rom_tjpgd_dec_t* dec = reinterpret_cast<esp_rom_tjpgd_dec_t*>(jd);
    uint8_t* pixel = static_cast<uint8_t*>(bitmap);
    const size_t count = static_cast<size_t>(rect->right - rect->left + 1) * (rect->bottom - rect->top + 1);
    for (size_t i = 0; i < count; ++i, pixel += 3) {
        const uint8_t blue = pixel[0];
        pixel[0] = pixel[2];
        pixel[2] = blue;
    }
    return dec->outfunc(dec, bitmap, rect) ? 1 : 0;
}

inline esp_rom_tjpgd_result_t esp_rom_tjpgd_prepare(esp_rom_tjpgd_dec_t* dec, esp_rom_tjpgd_input_function_t infunc,
                                                    void* work, uint32_t sz_work, void* dev) {
    dec->infunc = infunc;
    dec->outfunc = nullptr;
    dec->device = dev;
    dec->width = dec->height = 0;
    const JRESULT result = jd_prepare(&dec->jd, cc_tjpgd_shim_input, work, sz_work, dev);
    dec->width = dec->jd.width;
    dec->height = dec->jd.height;
    return result;
}

inline esp_rom_tjpgd_result_t esp_rom_tjpgd_decomp(esp_rom_tjpgd_dec_t* dec, esp_rom_tjpgd_output_function_t outfunc,
                                                   uint8_t scale) {
    dec->outfunc = outfunc;
    return jd_decomp(&dec->jd, cc_tjpgd_shim_output, scale);
}
