#include "cc_media.h"
#include "cc_diag.h"
#include "cc_jpeg.h"
#include "cc_media_store.h"
#include "cc_serial_out.h"
#include <Arduino.h>
#include <esp_heap_caps.h>

// artwork2 media (1.0.0-cc5.3, ARTWORK2.md): the ESP wrapper around the platform-neutral
// CCMediaStore (cc_media_store.h). PSRAM holds the pixels (25 x 32768 B covers, 49 x 2048 B
// icons); the slot tables, the decoded-chunk buffer and the mutex are internal RAM. The COM
// thread runs the media command (and owns the upload); the LCD thread adopts and reads
// displayed slots, which the store never evicts or writes, so the LCD decodes a cover
// straight from PSRAM without holding the mutex.

namespace {
CCMediaStore store;
CCMediaSlot coverSlots[CC_MEDIA_COVER_ENTRIES + 1];
CCMediaSlot iconSlots[CC_MEDIA_ICON_ENTRIES + 1];
uint8_t scratch[CC_MEDIA_CHUNK_BYTES];   // one decoded data chunk (COM thread; never on the stack)
SemaphoreHandle_t mutex = nullptr;
bool attempted = false;
volatile uint32_t mediaVersion = 0;      // mirror of store.version() for any thread

// The commit-time cover check (COM thread): cc_jpeg_validate's own static work area.
bool cover_check(const uint8_t* data, uint32_t bytes) {
    uint16_t width = 0, height = 0;
    return cc_jpeg_validate(data, bytes, &width, &height);
}

// Store state shared by COM (requests, frame keys) and LCD (adoption). Short sections only:
// a data chunk copy, a have scan, a JPEG header check at commit.
class Lock {
public:
    Lock() { if (mutex) xSemaphoreTake(mutex, portMAX_DELAY); }
    ~Lock() { if (mutex) xSemaphoreGive(mutex); }
};

uint8_t crumb_op(JsonVariantConst media) {
    const char* op = media["op"] | "";
    if (!strcmp(op, "begin")) return CC_COM_OP_MEDIA_BEGIN;
    if (!strcmp(op, "data")) return CC_COM_OP_MEDIA_DATA;
    if (!strcmp(op, "commit")) return CC_COM_OP_MEDIA_COMMIT;
    if (!strcmp(op, "have")) return CC_COM_OP_MEDIA_HAVE;
    return CC_COM_OP_MEDIA_OTHER;
}
}  // namespace

void cc_media_init() {
    if (attempted) return;
    attempted = true;
    mutex = xSemaphoreCreateMutex();
    // PSRAM only: never the internal RAM that USB, the RX queue and the tasks need.
    const size_t coverBytes = static_cast<size_t>(CC_MEDIA_COVER_ENTRIES + 1) * CC_MEDIA_COVER_MAX_BYTES;
    const size_t iconBytes = static_cast<size_t>(CC_MEDIA_ICON_ENTRIES + 1) * CC_MEDIA_ICON_BYTES;
    uint8_t* cover = static_cast<uint8_t*>(heap_caps_malloc(coverBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    uint8_t* icon = static_cast<uint8_t*>(heap_caps_malloc(iconBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!mutex || !cover || !icon) {
        // Fail-soft: artwork2 is off as a whole (capability available false), v1 art and text
        // controls are unaffected. The host then uses v1 art, or none.
        if (cover) heap_caps_free(cover);
        if (icon) heap_caps_free(icon);
        cover = icon = nullptr;
    }
    store.init(cc_media_device_config(), cover, cover ? coverSlots : nullptr, icon, icon ? iconSlots : nullptr,
               scratch, cover_check);
}

bool cc_media_available(CCMediaKind kind) { return store.available(static_cast<uint8_t>(kind)); }

void cc_media_capability(JsonObject a, uint32_t rxBytes) {
    // ARTWORK2.md section 1, in its field order (media_tests.py compares it with the host's
    // presentation.ARTWORK2_CAPABILITY).
    cc_media_capability_fields(a, cc_media_available(CC_MEDIA_COVER) && cc_media_available(CC_MEDIA_ICON),
                               rxBytes);
}

void cc_media_command(JsonVariantConst media, uint32_t activeId) {
    cc_crumb_com(crumb_op(media), CC_COM_STAGE_LINE, media["offset"] | 0U);
    JsonDocument out;
    JsonObject ack = out["mediaAck"].to<JsonObject>();
    {
        Lock lock;
        store.handle(media, activeId, ack);
        mediaVersion = store.version();
    }
    cc_send_json(out);   // the reply's strings point into `media`, which the caller keeps alive
}

void cc_media_parse_reply(const char* line, size_t length) {
    char key[CC_MEDIA_KEY_CHARS + 1];   // outlives serialisation below
    JsonDocument out;
    cc_media_parse_ack(line, length, out["mediaAck"].to<JsonObject>(), key);
    {
        Lock lock;
        store.noteParseError();
    }
    cc_send_json(out);
}

void cc_media_frame_keys(const char* artKey, const char* iconKey) {
    Lock lock;
    store.setFrameKey(CC_MEDIA_COVER, artKey);
    store.setFrameKey(CC_MEDIA_ICON, iconKey);
}

void cc_media_cancel_upload() {
    Lock lock;
    store.cancelUpload();
}

bool cc_media_receiving() { return store.receiving(); }   // COM thread: the only writer

bool cc_media_adopt(CCMediaKind kind, const char* key, const uint8_t** data, uint32_t* bytes) {
    if (!cc_media_available(kind)) return false;
    Lock lock;
    return store.adopt(static_cast<uint8_t>(kind), key, data, bytes);
}

void cc_media_release_display(CCMediaKind kind) {
    if (!cc_media_available(kind)) return;
    Lock lock;
    store.releaseDisplay(static_cast<uint8_t>(kind));
}

uint32_t cc_media_version() { return mediaVersion; }

CCMediaCounters cc_media_counters() {
    CCMediaCounters counters;   // COM thread: the only writer
    counters.commits = store.commits();
    counters.errors = store.errors();
    counters.evictions = store.evictions();
    return counters;
}
