#pragma once
#include <stdint.h>

// artwork2 cover JPEG glue over the ESP32-S3 ROM TJpgDec (1.0.0-cc5.3, ARTWORK2.md sections
// 4.3, 5 and 7). cc_jpeg.cpp includes only <esp_rom_tjpgd.h> and <esp_timer.h>, so it compiles
// unchanged for the host through harness/tjpgd_shim (LVGL's bundled TJpgDec R0.03
// behind the same API; jpeg_tests.py). C++11.
//
// Accepted covers: a baseline (SOF0) JPEG, 8-bit, three components (YCbCr), exactly 240x240,
// at most 32768 bytes, starting with SOI and ending with EOI (its last two bytes), that the
// ROM decoder prepares with the static work area. Progressive and other SOF types,
// grayscale, other sizes, oversize data, a missing EOI and trailing bytes are rejected. The
// pre-scan of the marker segments makes the host shim (which also accepts grayscale and
// leading garbage) decide exactly as the ROM does. The entropy-coded scan is not decoded at
// validation: a cover whose scan is damaged but still ends with EOI is accepted and then
// fails cc_jpeg_decode_240 on the LCD (the payload CRC-32 keeps that to host bugs).

struct CCJpegStats {
    uint32_t decodes;   // cc_jpeg_decode_240 calls since boot (jpegDecodes)
    uint32_t errors;    // of which failed (jpegDecodeErrors)
    uint32_t msMax;     // longest decode, ms rounded up (jpegDecodeMsMax)
    uint32_t msLast;    // last decode, ms rounded up (jpegDecodeMsLast)
};

// COM thread only (its own static work area). True when `data` is an accepted cover; *w and
// *h receive the image size once the ROM decoder prepared it (0 before that). Never decodes
// pixels: the store runs it at commit ("Media decode failed").
bool cc_jpeg_validate(const uint8_t* data, uint32_t bytes, uint16_t* w, uint16_t* h);

// LCD thread only (its own static work area). Decodes an accepted cover into dst, 240 x 240
// uint16_t pixels, row-major, in the art buffer's LV_COLOR_FORMAT_RGB565 value
// (r5 << 11 | g6 << 5 | b5, native byte order, as cc_display.cpp upscaleArt writes). Each
// RGB888 channel from the decoder is rounded: r5 = (r*31 + 127)/255, g6 = (g*63 + 127)/255,
// b5 = (b*31 + 127)/255. Counts every call and its duration (esp_timer_get_time) and every
// failure in the stats; on a failure dst may hold part of the image.
bool cc_jpeg_decode_240(const uint8_t* data, uint32_t bytes, uint16_t* dst);

// ---- Abort hook (1.0.0-cc5.4, PRESENTATION_V5 12.5.4 step 2; lead ruling R-f) ------------------
// The same decode (same thread rule: the one decoder that owns the LCD work area, i.e. the R5
// ArtDecode task in R5 builds), which can stop BETWEEN TWO ROWS OF MCUs: before the first MCU of
// each MCU row is written (rows of 16 px for 4:2:0, 8 px for 4:4:4; 15 or 30 polls per cover,
// the first at row 0), the hook is asked; once it says stop, the output function returns 0 and
// the ROM TJpgDec R0.01b ends esp_rom_tjpgd_decomp with JDR_INTR at once (its documented
// interrupt: "When a 0 is returned, the esp_rom_tjpgd_decomp function aborts with JDR_INTR").
// Safe with the ROM decoder: an interrupted decode leaves nothing behind. Every decode starts
// with esp_rom_tjpgd_prepare(), which rebuilds the decoder object and re-carves its tables from
// the static work area, so the next decode is byte-identical to a clean one. An aborted decode
// writes every row above the abort row and nothing from it on; its pixels are the caller's to
// discard. It counts in `decodes`, never in `errors`, and leaves msLast / msMax unchanged (a part
// decode is not a decode time).
enum CCJpegResult : uint8_t { CC_JPEG_OK, CC_JPEG_FAILED, CC_JPEG_ABORTED };

// Polled between MCU rows with the top pixel row of the MCU row about to be written (0, 16, ...).
// true stops the decode (CC_JPEG_ABORTED).
typedef bool (*CCJpegAbort)(void* context, uint16_t row);

// K1 12.5.4 step 2's form: cc_jpeg_decode_240(jpeg, bytes, dst, &cancel). `cancel` (may be null:
// never abort) is read once per MCU row; a writer on another task sets it under its own lock
// (cc_art_decode.cpp's spinlock); a single aligned byte read needs none.
CCJpegResult cc_jpeg_decode_240(const uint8_t* data, uint32_t bytes, uint16_t* dst, const volatile bool* cancel);
// The general form (host tests abort at a chosen band); a null `abort` never aborts.
CCJpegResult cc_jpeg_decode_240(const uint8_t* data, uint32_t bytes, uint16_t* dst, CCJpegAbort abort,
                                void* context);

// A copy of the decode statistics (any thread; each field is one aligned 32-bit word).
CCJpegStats cc_jpeg_stats();
