// App profiles (plan §1d; APP_PROFILES.md section 7): the knob's hooks for the platform-neutral store
// (cc_app_store.h). Profiles and the upload staging buffer live in PSRAM (never the internal RAM that USB, the RX
// queue and the tasks need), one allocation each, made only while an upload runs or ends; a static FreeRTOS mutex
// (no allocation, cannot fail) guards the records between the COM task (writer) and the LCD task (reader). Nothing
// is written to flash: a reboot empties the store and Desk Dial uploads again.
#include "cc_app_store.h"
#include <Arduino.h>
#include <esp_heap_caps.h>

namespace {
StaticSemaphore_t mutexStorage;
SemaphoreHandle_t mutex = nullptr;

void* psram_alloc(void*, size_t bytes) { return heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT); }
void psram_free(void*, void* memory) { heap_caps_free(memory); }
void lock(void*) { xSemaphoreTake(mutex, portMAX_DELAY); }
void unlock(void*) { xSemaphoreGive(mutex); }
}  // namespace

// Once, from setup(), before any task can draw or upload.
void cc_app_store_device_init() {
    if (mutex != nullptr) return;
    mutex = xSemaphoreCreateMutexStatic(&mutexStorage);
    cc_app_store_hooks_t hooks = {};
    hooks.mem.alloc = psram_alloc;
    hooks.mem.free = psram_free;
    hooks.lock = lock;
    hooks.unlock = unlock;
    cc_app_store_init(&hooks);
}
