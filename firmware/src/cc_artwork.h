#pragma once
#include <ArduinoJson.h>
#include <stdint.h>
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
