#include <Arduino.h>
#include <string.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <esp_heap_caps.h>
#include "cc_art_decode.h"
#include "cc_display.h"
#include "cc_jpeg.h"

// R5 decode task (PRESENTATION_V5.md 12.5.1-12.5.4). Shared state under one spinlock, short sections,
// no allocation after start: the request the task decodes, `inFlight` from the post until the LCD
// consumes the result, `cancel` (set when the frame's key moved on, cleared on a spin back; also read
// by the decoder between MCU rows, 12.5.4 step 2), and the result with its version counter.

namespace {
constexpr uint32_t kStackBytes = 4096;            // 12.5.1; ESP-IDF StackType_t is one byte
constexpr uint32_t kStageBytes = 32768;           // artwork2 cover maxBytes (ARTWORK2.md section 5)
constexpr uint32_t kKeyCap = 65;                  // CCFrame::artKey

StackType_t stack[kStackBytes];
StaticTask_t tcb;
TaskHandle_t task = nullptr;
uint8_t* stage = nullptr;                         // PSRAM copy of the JPEG being decoded
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;

struct Request {
    char key[kKeyCap];
    uint32_t bytes;
    uint16_t* dst;
};
Request request = {};
bool inFlight = false;                            // LCD view: posted and not consumed yet
// Written only under `lock` (cc_art_decode_request / _cancel, LCD thread); cc_jpeg.cpp's output
// callback also reads it without the lock once per MCU row (a single aligned byte: volatile, so every
// poll loads it afresh).
volatile bool cancelled = false;
bool done = false;
char doneKey[kKeyCap] = {};
uint8_t doneResult = CC_DECODE_FAILED;
volatile uint32_t version = 0;

void copyKey(char* out, const char* key) {
    size_t n = strlen(key);
    if (n >= kKeyCap) n = kKeyCap - 1;
    memcpy(out, key, n);
    out[n] = '\0';
}

void run(void*) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        Request job;
        bool skip;
        portENTER_CRITICAL(&lock);
        job = request;
        skip = cancelled;
        portEXIT_CRITICAL(&lock);
        uint8_t result = CC_DECODE_ABORTED;
        if (!skip) {
            // Writes only into job.dst, the back buffer the LCD handed over at the post (12.5.3).
            // Stops at the next MCU band once `cancelled` is set (CC_JPEG_ABORTED, 12.5.4 step 2).
            const CCJpegResult decoded = cc_jpeg_decode_240(stage, job.bytes, job.dst, &cancelled);
            portENTER_CRITICAL(&lock);
            const bool superseded = cancelled;
            portEXIT_CRITICAL(&lock);
            result = cc_art_decode_result(decoded, superseded);
        }
        portENTER_CRITICAL(&lock);
        copyKey(doneKey, job.key);
        doneResult = result;
        done = true;
        ++version;
        portEXIT_CRITICAL(&lock);
    }
}
}  // namespace

bool cc_art_decode_start() {
    if (task) return true;
    if (!stage) stage = static_cast<uint8_t*>(heap_caps_malloc(kStageBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!stage) return false;
    // Core 0, priority 1: FreeRTOS round-robins it with the LCD, COM and HMI tasks at the 1 ms tick,
    // so a running decode delays an LVGL pass by at most one tick per wake. Never on core 1 (FOC).
    // Not subscribed to the task watchdog: it blocks indefinitely while idle (jpegDecodeMsMax
    // bounds a decode).
    task = xTaskCreateStaticPinnedToCore(run, "ArtDecode", kStackBytes, nullptr, 1, stack, &tcb, 0);
    return task != nullptr;
}

bool cc_art_decode_request(const char* key, const uint8_t* jpeg, uint32_t bytes, uint16_t* dst) {
    if (!task || !stage || !key || !jpeg || !dst || bytes == 0 || bytes > kStageBytes) return false;
    portENTER_CRITICAL(&lock);
    const bool busy = inFlight;
    portEXIT_CRITICAL(&lock);
    if (busy) return false;
    // The store payload is valid only during this render: copy it (PSRAM to PSRAM, <= 32 KB). The
    // task is idle (no request in flight), so the staging buffer is free.
    memcpy(stage, jpeg, bytes);
    portENTER_CRITICAL(&lock);
    copyKey(request.key, key);
    request.bytes = bytes;
    request.dst = dst;
    cancelled = false;
    done = false;
    inFlight = true;
    portEXIT_CRITICAL(&lock);
    xTaskNotifyGive(task);
    return true;
}

bool cc_art_decode_poll(char* key, uint32_t keyCap, uint8_t* result) {
    portENTER_CRITICAL(&lock);
    const bool ready = done;
    if (ready) {
        const size_t n = keyCap ? strnlen(doneKey, keyCap - 1) : 0;
        if (keyCap) {
            memcpy(key, doneKey, n);
            key[n] = '\0';
        }
        *result = doneResult;
        done = false;
        inFlight = false;
    }
    portEXIT_CRITICAL(&lock);
    return ready;
}

void cc_art_decode_cancel(bool cancel) {
    portENTER_CRITICAL(&lock);
    cancelled = cancel;
    portEXIT_CRITICAL(&lock);
}

uint32_t cc_art_decode_version() { return version; }

bool cc_art_decode_running() { return task != nullptr; }

uint32_t cc_art_decode_stack_free() {
    return task ? static_cast<uint32_t>(uxTaskGetStackHighWaterMark(task)) : 0;
}
