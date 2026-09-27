#include "cc_artwork.h"
#include "cc_art_store.h"
#include "cc_diag.h"
#include "cc_serial_out.h"
#include <Arduino.h>
#include <esp_heap_caps.h>
#include <mbedtls/base64.h>

namespace {
CCArtStore store;
SemaphoreHandle_t mutex = nullptr;
bool attempted = false;
uint32_t version = 0;
}
void cc_art_init() {
    if (attempted) return;
    attempted = true;
    mutex = xSemaphoreCreateMutex();
    // Never consume the internal RAM needed for control/USB if PSRAM is absent.
    auto* memory = static_cast<uint8_t*>(heap_caps_malloc(CCArtStore::bytes * CCArtStore::slots, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!memory || !mutex) { if (memory) free(memory); return; }
    store.init(memory);
}
namespace {
bool validKey(const char* key) {
    const size_t size = strlen(key);
    if (!size || size > 64) return false;
    for (size_t i = 0; i < size; ++i)
        if (!isalnum(static_cast<unsigned char>(key[i])) && key[i] != '_' && key[i] != '-') return false;
    return true;
}
bool uintValue(JsonVariant v) { return v.is<uint32_t>() && !v.is<bool>(); }
}
bool cc_art_available() { return store.available(); }
uint32_t cc_art_version() { return version; }
void cc_art_command(JsonVariant c, uint32_t currentId, const char* currentKey) {
    const char* key = c["key"] | "";
    const char* op = c["op"] | "";
    const uint32_t id = c["id"] | 0U;
    const char* error = nullptr;
    uint32_t offset = 0;
    cc_crumb_com(!strcmp(op, "begin") ? CC_COM_OP_ART_BEGIN : !strcmp(op, "data") ? CC_COM_OP_ART_DATA
                 : !strcmp(op, "commit") ? CC_COM_OP_ART_COMMIT : CC_COM_OP_ART_OTHER,
                 CC_COM_STAGE_LINE, c["offset"] | 0U);
    if (!uintValue(c["id"]) || !id || id != currentId || !validKey(key) || strcmp(key, currentKey)) error = "Stale artwork selection";
    else if (!store.available()) error = "Artwork memory unavailable";
    else {
        xSemaphoreTake(mutex, portMAX_DELAY);
        if (!strcmp(op, "begin")) {
            if (!uintValue(c["bytes"]) || !uintValue(c["crc32"])) error = "Artwork size and CRC required";
            else error = store.begin(id, key, c["bytes"], c["crc32"]);
        } else if (!strcmp(op, "data")) {
            uint8_t decoded[CCArtStore::chunkBytes]; size_t written = 0;
            const char* encoded = c["data"] | "";
            if (!uintValue(c["offset"]) || strlen(encoded) > 512 ||
                mbedtls_base64_decode(decoded, sizeof(decoded), &written,
                    reinterpret_cast<const unsigned char*>(encoded), strlen(encoded))) error = "Invalid artwork chunk";
            else error = store.data(id, key, c["offset"], decoded, written);
        } else if (!strcmp(op, "commit")) {
            error = store.commit(id, key); if (!error) ++version;
        } else error = "Unknown artwork operation";
        offset = store.offset();
        xSemaphoreGive(mutex);
    }
    JsonDocument out; auto ack = out["artAck"].to<JsonObject>();
    ack["id"] = id; ack["key"] = key; ack["op"] = op; ack["offset"] = offset;
    if (error) ack["error"] = error;
    cc_send_json(out);
}
const uint8_t* cc_art_pixels(const char* key) {
    if (!mutex || !store.available()) return nullptr;
    xSemaphoreTake(mutex, portMAX_DELAY);
    const uint8_t* pixels = store.adopt(key);
    xSemaphoreGive(mutex);
    return pixels;
}
