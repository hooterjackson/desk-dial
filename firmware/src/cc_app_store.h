#pragma once
// App profiles (plan §1b-§1d; APP_PROFILES.md, wire 1): the DDAP wire-profile decoder and the knob's RAM-only
// profile store. Pure C99 and platform-neutral: compiled unchanged by the firmware (cc_app_store_device.cpp gives it
// PSRAM and a FreeRTOS mutex), by harness/app_store_tests.py (MSVC /W4 /WX, plus an /fsanitize=address
// fuzz build) and by cpp11_gate.py's C unit gate (gnu99).
//
// The profile model, element set, parameter model and limits are adapted from Karl Malota's (katbinaris) app
// profiles, feat/firmware-esp-idf-quadra NanoDepsidf/src/app_profiles/ (app_profile.h, profile_json.c for the range
// checks, host_link.c for the upload state machine), with his permission. The knob takes a compact binary that
// Desk Dial compiles from his profile JSON, never the JSON itself.
//
// Threads: the COM task is the only writer (cc_app_upload_*, cc_app_store_init); the LCD task reads through
// cc_app_store_acquire / cc_app_store_release. Every store access goes through the lock hooks.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "cc_app_profile.h"

#ifdef __cplusplus
extern "C" {
#endif

// --- Limits (APP_PROFILES.md sections 3 and 7) ---
#define CC_APP_WIRE_VERSION 1u
#define CC_APP_WIRE_MAX_BYTES 32768u   // a whole blob, header and trailer included (capability appProfileMaxBytes)
#define CC_APP_STORE_SLOTS 4u          // capability appProfileSlots
#define CC_APP_STORE_BUDGET (128u * 1024u) // decoded bytes of live entries plus those whose free waits for a release
#define CC_APP_UPLOAD_STALL_MS 2000u   // a partial upload is dropped after this long without data
#define CC_APP_B64_MAX 3000u           // characters in one data line's b64
#define CC_APP_ID_MAX 11u              // [a-z0-9_-], 1..11 characters

// --- Decoder result codes (APP_PROFILES.md section 6) ---
enum {
    CC_APP_OK = 0, CC_APP_E_SHORT = 1, CC_APP_E_MAGIC = 2, CC_APP_E_WIRE = 3, CC_APP_E_TOTAL = 4, CC_APP_E_CRC = 5,
    CC_APP_E_FEATURE = 6, CC_APP_E_STRING = 7, CC_APP_E_RANGE = 8, CC_APP_E_COUNT = 9, CC_APP_E_INDEX = 10,
    CC_APP_E_ID = 11, CC_APP_E_TRAILING = 12, CC_APP_E_MEMORY = 13, CC_APP_E_FLOAT = 14
};

// The allocator hook: one call per decoded profile (PSRAM on the knob). `free` gets exactly what `alloc` returned.
typedef struct {
    void *(*alloc)(void *ctx, size_t bytes);
    void (*free)(void *ctx, void *memory);
    void *ctx;
} cc_app_alloc_t;

// zlib CRC-32 (polynomial 0xEDB88320, initial and final xor 0xFFFFFFFF) of `len` bytes, continuing from `crc`
// (0 to start).
uint32_t cc_app_crc32(uint32_t crc, const uint8_t *data, size_t len);

// True when `id` (NUL-terminated) is 1..11 characters of [a-z0-9_-]: the wire profile id and the frame's app.id.
bool cc_app_id_valid(const char *id);

// Decodes one DDAP blob into a fully populated profile (rings, commands, scenes, keyframes, elements, params, the
// NUL-terminated strings and the icons) in ONE allocation from `alloc`; *out is that allocation, freed with
// alloc->free. Pass 1 checks every rule of APP_PROFILES.md sections 2-4 and sizes the allocation; pass 2 fills it,
// so nothing is ever partly loaded. Returns a CC_APP_* code; on failure *out is NULL and *fail_offset (optional)
// is the blob offset of the field that failed (a string's length byte, a count, the first byte of a short read;
// header: magic 0, wire 4, reserved 5/6, total 8, features 12; crc: the trailer; trailing: the first extra byte;
// memory: 0). Never reads outside blob[0..len).
int cc_app_decode(const uint8_t *blob, size_t len, const cc_app_alloc_t *alloc, cc_app_profile_t **out,
                  size_t *fail_offset);

// --- The store (RAM only: nothing is ever written to flash) ---
typedef struct {
    cc_app_alloc_t mem;            // profiles and the upload staging buffer (PSRAM)
    void (*lock)(void *ctx);       // a mutex around every store access (no-op hooks are allowed: NULL)
    void (*unlock)(void *ctx);
    void *lock_ctx;
} cc_app_store_hooks_t;

// Sets the hooks and empties the store (any upload is dropped; entries still acquired are kept until released
// and then freed with the hooks they were allocated with -- only tests re-init). COM task, before uploads.
void cc_app_store_init(const cc_app_store_hooks_t *hooks);

// The profile to draw for a frame's app.id / app.crc, or NULL when that id is not loaded or its crc differs (the
// renderer then shows "Loading..."). "onshape" with crc 0 is the built-in cc_app_profile_onshape unless an uploaded
// "onshape" with crc 0 exists. An uploaded entry is pinned (it is never freed while acquired: eviction and
// replacement defer the free to the last release) and becomes the most recently drawn. LCD task.
const cc_app_profile_t *cc_app_store_acquire(const char *id, uint32_t crc);
// Ends one acquire. NULL and the built-in are ignored. LCD task.
void cc_app_store_release(const cc_app_profile_t *p);

typedef struct {
    char id[CC_APP_ID_MAX + 1];
    uint32_t crc;
} cc_app_store_item_t;
// The uploaded profiles (never the built-in), most recently drawn first; returns how many were written (<= max).
size_t cc_app_store_list(cc_app_store_item_t *items, size_t max);

// --- The upload state machine (APP_PROFILES.md section 7) ---
typedef enum {
    CC_APP_UP_OK = 0,
    CC_APP_UP_CRC,     // "crc": the received bytes' CRC-32 (trailer excluded) differs from begin's crc
    CC_APP_UP_SIZE,    // "size": bytes 0 or > 32768, b64 empty / > 3000 chars / not base64, a chunk past bytes, end short
    CC_APP_UP_ORDER,   // "order": data or end without an upload (none begun, already ended, dropped after a stall),
                       // an offset other than the next byte, a malformed field
    CC_APP_UP_BUSY,    // "busy": no staging memory, or the store cannot make room (slots held by acquired profiles)
    CC_APP_UP_WIRE,    // "wire": begin's wire is not 1
    CC_APP_UP_DECODE   // "decode:<code>@<offset>": the blob failed cc_app_decode (or names another id: code 11)
} cc_app_up_result_t;
// The error token of a result ("crc", "size", ... "decode"); NULL for CC_APP_UP_OK.
const char *cc_app_up_error_name(cc_app_up_result_t result);

typedef struct {
    int decode;          // with CC_APP_UP_DECODE: the CC_APP_E_* code
    size_t offset;       // ... and its offset
    char id[CC_APP_ID_MAX + 1]; // with CC_APP_UP_OK: the stored profile's id and crc
    uint32_t crc;
} cc_app_up_end_t;

// begin: drops any upload in progress first (one upload at a time), then checks wire, bytes (1..32768) and id, and
// takes a staging buffer of `bytes` from the allocator. Every failure leaves no upload in progress.
cc_app_up_result_t cc_app_upload_begin(const char *id, uint32_t bytes, uint32_t crc, uint32_t wire, uint32_t now_ms);
// data: `off` must be the next byte; `b64` (standard alphabet, padded, 1..3000 chars) is decoded straight into the
// staging buffer. *next (optional) = the next expected offset (the ack). A failure drops the upload.
cc_app_up_result_t cc_app_upload_data(uint32_t off, const char *b64, size_t b64_len, uint32_t now_ms, uint32_t *next);
// end: every byte received, the crc, then the decode into the store (replacing an older copy with the same id; the
// LRU evicts the least recently drawn when 4 are loaded or the budget would be exceeded). The upload ends either way.
cc_app_up_result_t cc_app_upload_end(uint32_t now_ms, cc_app_up_end_t *result);
// Drops an upload that has had no begin or data for CC_APP_UPLOAD_STALL_MS (also checked by data and end).
void cc_app_upload_poll(uint32_t now_ms);
// True while an upload is in progress (the COM task then polls its line fast).
bool cc_app_upload_active(void);

#ifdef __cplusplus
}
#endif
