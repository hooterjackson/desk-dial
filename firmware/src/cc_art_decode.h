#pragma once
#include <stdint.h>
#include "cc_display.h"   // CCDisplayDecodeResult (CC_DECODE_*)
#include "cc_jpeg.h"      // CCJpegResult (CC_JPEG_*)

// R5 (PRESENTATION_V5.md section 12.5; binary A, CC_ART_ASYNC 1): the 240 px cover JPEG decode off the
// LCD render path. One task, "ArtDecode", on core 0 at priority 1 (the LCD, COM and HMI priority),
// with a static 4,096 B stack and TCB (counted in .bss) and a 32 KB PSRAM staging copy of the JPEG
// being decoded. The platform-neutral renderer reaches it through CCDisplayMedia::requestCover /
// pollCover / cancelCover (cc_display.h); lcd_thread.cpp re-renders when cc_art_decode_version()
// moves. Single request, newest wins (the renderer posts the frame's current key again after a
// result); the request is copied into the staging buffer, so the store's payload need not stay
// pinned while the task reads it (12.5.6's decode pin is satisfied by the copy). 12.5.4 step 2
// (lead ruling R-f): the task decodes with cc_jpeg_decode_240(stage, bytes, dst, &cancelled), whose
// output callback reads the flag between MCU rows, so a cancelled decode stops at the next MCU band
// (at most 16 of 240 rows) with CC_JPEG_ABORTED and its part-written pixels are discarded.

// The task's result for one decode (12.5.4 steps 2 and 5), pure so that the harness's fake decoder
// (harness/main.cpp) completes through the same mapping. `decoded` is what
// cc_jpeg_decode_240 returned; `cancelledAtEnd` is the flag as the task reads it afterwards.
//  - CC_JPEG_ABORTED -> aborted, ALWAYS: the decoder saw `cancel`, even if a spin back cleared it
//    since (step 5 then posts the key again). It must never become `failed`, which would hide the
//    cover and mark the key failed (8.4).
//  - CC_JPEG_FAILED -> failed (the LCD hides it only when it is the frame's current key).
//  - CC_JPEG_OK -> aborted when `cancel` was set after the decoder's last poll (superseded during
//    the last band), else ok.
inline uint8_t cc_art_decode_result(CCJpegResult decoded, bool cancelledAtEnd) {
    return decoded == CC_JPEG_ABORTED ? static_cast<uint8_t>(CC_DECODE_ABORTED)
         : decoded == CC_JPEG_FAILED  ? static_cast<uint8_t>(CC_DECODE_FAILED)
         : cancelledAtEnd             ? static_cast<uint8_t>(CC_DECODE_ABORTED)
                                      : static_cast<uint8_t>(CC_DECODE_OK);
}

// Creates the task and the staging buffer once. False when either cannot be created (R5 then stays
// off: the renderer decodes synchronously). LCD thread.
bool cc_art_decode_start();

// CCDisplayMedia hooks (LCD thread). request: false when a decode is in flight, the task is not
// running or the JPEG exceeds the staging buffer.
bool cc_art_decode_request(const char* key, const uint8_t* jpeg, uint32_t bytes, uint16_t* dst);
bool cc_art_decode_poll(char* key, uint32_t keyCap, uint8_t* result);
void cc_art_decode_cancel(bool cancel);

// Moves on every completion (any thread).
uint32_t cc_art_decode_version();

// True once the task runs (diag artAsync together with the renderer hooks).
bool cc_art_decode_running();

// Free bytes of the task's stack high-water mark (diag stackArtDec; 0 when not running).
uint32_t cc_art_decode_stack_free();
