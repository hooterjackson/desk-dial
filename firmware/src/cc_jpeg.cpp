#include "cc_jpeg.h"
#include <esp_rom_tjpgd.h>   // ROM TJpgDec R0.01b (IDF 4.4); tjpgd_shim/ on the host
#include <esp_timer.h>
#include <stddef.h>
#include <string.h>

// ROM TJpgDec glue for artwork2 covers (1.0.0-cc5.3, ARTWORK2.md sections 4.3, 5 and 7).
// Compiled unchanged by the firmware and by harness (jpeg_tests.py, media_tests.py)
// against tjpgd_shim/, which maps this API onto LVGL's TJpgDec R0.03.

namespace {
constexpr uint32_t kSize = 240;            // covers are exactly 240 x 240
constexpr uint32_t kMaxBytes = 32768;      // ARTWORK2.md section 1 cover.maxBytes
// TJpgDec work area. The ROM decoder needs up to about 3.1 KB for a 4:2:0 image with the
// standard tables (512 B stream buffer, Huffman and quantisation tables, IDCT and MCU
// buffers); 4 KB leaves room for larger optimised tables. A JPEG that needs more fails to
// prepare (JDR_MEM1) and is rejected. One area per thread, in static storage (never on a
// task stack), word aligned as the decoder requires.
constexpr size_t kWorkWords = 1024;

struct Source {
    const uint8_t* data;
    uint32_t size, at;
    uint16_t* dst;
    // Abort hook (cc_jpeg.h; PRESENTATION_V5 12.5.4 step 2), polled between MCU rows. All null
    // for validation and the 3-argument decode.
    const volatile bool* cancel;
    CCJpegAbort abort;
    void* context;
    bool aborted;                          // the output function stopped the decode
};

// COM thread (cc_jpeg_validate) and LCD thread (cc_jpeg_decode_240) each own one decoder.
esp_rom_tjpgd_dec_t comDecoder, lcdDecoder;
uint32_t comWork[kWorkWords], lcdWork[kWorkWords];
volatile uint32_t statDecodes = 0, statErrors = 0, statMsMax = 0, statMsLast = 0;

// Marker segments from SOI up to SOS, checked the way the ROM decoder will read them, so the
// host shim (R0.03 also takes grayscale and skips bytes before SOI) decides exactly like the
// ROM: SOI first; every segment 0xFF, marker, length > 2 inside the data; one SOF0 with 8-bit
// samples and three components before SOS; any other SOF type (progressive, extended,
// lossless, arithmetic) or EOI before SOS rejects. Other segments (APPn, COM, DQT, DHT, DRI)
// are left to the decoder. The data must also end with EOI (FF D9) as its last two bytes, as
// a complete JPEG file does and as the companion's FakeKnob requires (jpeg_baseline_240): a
// cover cut short, or followed by trailing bytes, is refused at commit. The scan itself is
// not decoded here, so a scan damaged in the middle but still ending with EOI passes and
// fails later on the LCD (jpegDecodeErrors); CRC-32 over the whole payload rules that out
// for anything the host encoder produced.
bool prescan(const uint8_t* data, uint32_t size) {
    if (size < 4 || data[0] != 0xFF || data[1] != 0xD8) return false;
    if (data[size - 2] != 0xFF || data[size - 1] != 0xD9) return false;
    bool sof0 = false;
    uint32_t at = 2;
    for (;;) {
        if (size - at < 4 || data[at] != 0xFF) return false;
        const uint8_t marker = data[at + 1];
        const uint32_t length = static_cast<uint32_t>(data[at + 2]) << 8 | data[at + 3];
        if (length <= 2 || length > size - at - 2) return false;
        const uint8_t* segment = data + at + 4;
        switch (marker) {
            case 0xC0:
                if (sof0 || length < 2 + 6 || segment[0] != 8 || segment[5] != 3) return false;
                sof0 = true;
                break;
            case 0xDA:
                return sof0;
            case 0xC1: case 0xC2: case 0xC3: case 0xC5: case 0xC6: case 0xC7:
            case 0xC9: case 0xCA: case 0xCB: case 0xCD: case 0xCE: case 0xCF: case 0xD9:
                return false;
            default:
                break;
        }
        at += 2 + length;
    }
}

uint32_t input(esp_rom_tjpgd_dec_t* decoder, uint8_t* buffer, uint32_t count) {
    Source* source = static_cast<Source*>(decoder->device);
    const uint32_t left = source->size - source->at;
    if (count > left) count = left;
    if (buffer && count) memcpy(buffer, source->data + source->at, count);
    source->at += count;
    return count;
}

inline uint16_t rgb565(uint32_t r, uint32_t g, uint32_t b) {
    return static_cast<uint16_t>((((r * 31 + 127) / 255) << 11) | (((g * 63 + 127) / 255) << 5) |
                                 ((b * 31 + 127) / 255));
}

// RGB888 blocks (at most 16x16) into the 240x240 RGB565 destination, clipped.
// Between two MCU rows (the first MCU of a row, rect->left == 0, before any of its pixels is
// written) it asks the abort hook; returning 0 makes TJpgDec return JDR_INTR at once (ROM
// R0.01b and the host's R0.03 alike: mcu_output returns `outfunc(...) ? JDR_OK : JDR_INTR`
// and jd_decomp returns any rc != JDR_OK).
uint32_t output(esp_rom_tjpgd_dec_t* decoder, void* bitmap, esp_rom_tjpgd_rect_t* rect) {
    Source* source = static_cast<Source*>(decoder->device);
    if (rect->left == 0 && ((source->cancel && *source->cancel) ||
                            (source->abort && source->abort(source->context, rect->top)))) {
        source->aborted = true;
        return 0;
    }
    const uint8_t* rgb = static_cast<const uint8_t*>(bitmap);
    for (uint32_t y = rect->top; y <= rect->bottom; ++y) {
        for (uint32_t x = rect->left; x <= rect->right; ++x, rgb += 3)
            if (x < kSize && y < kSize) source->dst[y * kSize + x] = rgb565(rgb[0], rgb[1], rgb[2]);
    }
    return 1;
}

bool prepared(esp_rom_tjpgd_dec_t& decoder, uint32_t* work, Source& source) {
    return source.data && source.size && source.size <= kMaxBytes && prescan(source.data, source.size) &&
           esp_rom_tjpgd_prepare(&decoder, input, work, kWorkWords * sizeof(uint32_t), &source) == JDR_OK;
}

// The LCD decode behind every cc_jpeg_decode_240 form. Every call prepares the decoder afresh
// (esp_rom_tjpgd_prepare re-initialises the object and its tables in lcdWork), so an earlier
// JDR_INTR leaves nothing behind.
CCJpegResult decode(Source& source) {
    const int64_t started = esp_timer_get_time();
    CCJpegResult result = CC_JPEG_FAILED;
    if (source.dst && prepared(lcdDecoder, lcdWork, source) && lcdDecoder.width == kSize &&
        lcdDecoder.height == kSize) {
        const esp_rom_tjpgd_result_t rc = esp_rom_tjpgd_decomp(&lcdDecoder, output, 0);
        result = rc == JDR_OK ? CC_JPEG_OK : (rc == JDR_INTR && source.aborted) ? CC_JPEG_ABORTED : CC_JPEG_FAILED;
    }
    statDecodes = statDecodes + 1;
    if (result == CC_JPEG_FAILED) statErrors = statErrors + 1;
    if (result != CC_JPEG_ABORTED) {       // a part decode is not a decode time
        const int64_t elapsed = esp_timer_get_time() - started;
        const uint32_t ms = elapsed > 0 ? static_cast<uint32_t>((elapsed + 999) / 1000) : 0;
        statMsLast = ms;
        if (ms > statMsMax) statMsMax = ms;
    }
    return result;
}
}  // namespace

bool cc_jpeg_validate(const uint8_t* data, uint32_t bytes, uint16_t* w, uint16_t* h) {
    if (w) *w = 0;
    if (h) *h = 0;
    Source source = {data, bytes, 0, nullptr, nullptr, nullptr, nullptr, false};
    if (!prepared(comDecoder, comWork, source)) return false;
    if (w) *w = static_cast<uint16_t>(comDecoder.width);
    if (h) *h = static_cast<uint16_t>(comDecoder.height);
    return comDecoder.width == kSize && comDecoder.height == kSize;
}

bool cc_jpeg_decode_240(const uint8_t* data, uint32_t bytes, uint16_t* dst) {
    Source source = {data, bytes, 0, dst, nullptr, nullptr, nullptr, false};
    return decode(source) == CC_JPEG_OK;
}

CCJpegResult cc_jpeg_decode_240(const uint8_t* data, uint32_t bytes, uint16_t* dst, const volatile bool* cancel) {
    Source source = {data, bytes, 0, dst, cancel, nullptr, nullptr, false};
    return decode(source);
}

CCJpegResult cc_jpeg_decode_240(const uint8_t* data, uint32_t bytes, uint16_t* dst, CCJpegAbort abort,
                                void* context) {
    Source source = {data, bytes, 0, dst, nullptr, abort, context, false};
    return decode(source);
}

CCJpegStats cc_jpeg_stats() {
    CCJpegStats stats;
    stats.decodes = statDecodes;
    stats.errors = statErrors;
    stats.msMax = statMsMax;
    stats.msLast = statMsLast;
    return stats;
}
