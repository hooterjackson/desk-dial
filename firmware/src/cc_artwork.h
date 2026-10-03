#pragma once
#include <ArduinoJson.h>
#include <stdint.h>
#include <ctype.h>
#include <string.h>
// Call once from setup() before the LCD/COM threads start. Allocates the
// PSRAM cover cache and its mutex; on failure artwork stays unavailable and
// text controls are unaffected. Never panics; idempotent.
void cc_art_init();
bool cc_art_available(); // read-only; never initialises
void cc_art_command(JsonVariant command, uint32_t currentId, const char* currentKey);
// The cached cover for a content key (adoption is by key only; the control ID
// binds uploads, not display), or nullptr. LCD thread only.
const uint8_t* cc_art_pixels(const char* key);
uint32_t cc_art_version();

// A content key: 1-64 bytes of [A-Za-z0-9_-] (the only key an upload accepts).
inline bool cc_art_valid_key(const char* key) {
    if (!key) return false;
    const size_t size = strlen(key);
    if (!size || size > 64) return false;
    for (size_t i = 0; i < size; ++i)
        if (!isalnum(static_cast<unsigned char>(key[i])) && key[i] != '_' && key[i] != '-') return false;
    return true;
}
// Fills the artAck object. The reply echoes only what was validated (as mediaAck does): op only
// when it is begin/data/commit and key only when it is a valid content key, else "" - so a line
// with control bytes, invalid UTF-8 or an oversized op/key never reaches the reply verbatim.
inline void cc_art_ack(JsonObject ack, uint32_t id, const char* key, const char* op, uint32_t offset,
                       const char* error) {
    const bool knownOp = op && (!strcmp(op, "begin") || !strcmp(op, "data") || !strcmp(op, "commit"));
    ack["id"] = id;
    ack["key"] = cc_art_valid_key(key) ? key : "";
    ack["op"] = knownOp ? op : "";
    ack["offset"] = offset;
    if (error) ack["error"] = error;
}
