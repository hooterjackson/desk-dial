// Harness-only stand-in for the firmware's cc_jpeg_decode_240() (src/cc_jpeg.cpp,
// fw-core), compiled by CMakeLists.txt ONLY while cc_jpeg.cpp or tjpgd_shim/ is
// missing, so that the renderer's artwork2 path can be exercised meanwhile.
// It is not evidence for the JPEG glue: render-index.json then records
// jpeg_glue "standin" and cc5_report.py fails its jpeg_glue check.
//
// Same decoder family as the knob (ChaN TJpgDec R0.03, LVGL's bundled copy,
// 24-bit output) and the contract's conversion (ARTWORK2.md section 7): each
// channel rounded to RGB565 as (c * 31 + 127) / 255 and (g * 63 + 127) / 255.
#include "src/libs/tjpgd/tjpgd.h"

#include <cstdint>
#include <cstring>

namespace {

struct Session {
    const uint8_t* data;
    size_t size, pos;
    uint16_t* dst;
};

size_t input(JDEC* jd, uint8_t* buffer, size_t n) {
    Session* s = static_cast<Session*>(jd->device);
    if (n > s->size - s->pos) n = s->size - s->pos;
    if (buffer) std::memcpy(buffer, s->data + s->pos, n);
    s->pos += n;
    return n;
}

// LVGL's copy of TJpgDec writes each RGB888 pixel as B, G, R (lvgl/src/libs/tjpgd/tjpgd.c,
// its LVGL modification); ChaN's original and the ESP ROM decoder write R, G, B.
int output(JDEC* jd, void* bitmap, JRECT* rect) {
    Session* s = static_cast<Session*>(jd->device);
    const uint8_t* bgr = static_cast<const uint8_t*>(bitmap);
    for (unsigned y = rect->top; y <= rect->bottom; ++y) {
        for (unsigned x = rect->left; x <= rect->right; ++x, bgr += 3) {
            const unsigned r = (bgr[2] * 31u + 127u) / 255u;
            const unsigned g = (bgr[1] * 63u + 127u) / 255u;
            const unsigned b = (bgr[0] * 31u + 127u) / 255u;
            s->dst[y * 240u + x] = static_cast<uint16_t>((r << 11) | (g << 5) | b);
        }
    }
    return 1;
}

alignas(8) uint8_t pool[8192];  // TJpgDec work area (static, as on the knob)

}  // namespace

bool harness_jpeg_decode_240(const uint8_t* jpeg, uint32_t bytes, uint16_t* dst) {
    if (!jpeg || !bytes || !dst) return false;
    Session session = {jpeg, bytes, 0, dst};
    JDEC jd;
    if (jd_prepare(&jd, input, pool, sizeof(pool), &session) != JDR_OK) return false;
    if (jd.width != 240 || jd.height != 240) return false;
    return jd_decomp(&jd, output, 0) == JDR_OK;
}
