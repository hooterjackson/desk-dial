#pragma once
#include <ArduinoJson.h>
#include <stddef.h>
#include <stdint.h>

// artwork2 media (1.0.0-cc5.3, ARTWORK2.md): 240x240 baseline JPEG covers and 32x32
// RGB565 app icons, pushed by the host with the `media` command into two PSRAM stores
// (cc_media_store.h holds the platform-neutral store and request handler; cc_media.cpp
// is the ESP wrapper: PSRAM, the mutex, replies, breadcrumbs and counters).
//
// These declarations are platform-neutral (no ESP headers), so shared units and host
// tools may include this header. C++11 rules: namespace-scope constexpr only.

enum CCMediaKind { CC_MEDIA_COVER = 0, CC_MEDIA_ICON = 1 };

// Capability values (ARTWORK2.md section 1).
constexpr uint32_t CC_MEDIA_VERSION = 1;
constexpr uint32_t CC_MEDIA_RX_BYTES = 8192;          // CDC receive queue (main.cpp)
constexpr uint32_t CC_MEDIA_CHUNK_BYTES = 2048;       // decoded bytes per data line
constexpr uint32_t CC_MEDIA_HAVE_KEYS = 24;           // keys per have query
constexpr uint32_t CC_MEDIA_KEY_CHARS = 24;           // [A-Za-z0-9_-]{1,24}
constexpr uint32_t CC_MEDIA_COVER_SIZE = 240;
constexpr uint32_t CC_MEDIA_COVER_MAX_BYTES = 32768;
constexpr uint32_t CC_MEDIA_COVER_ENTRIES = 24;       // plus one staging slot
constexpr uint32_t CC_MEDIA_ICON_SIZE = 32;
constexpr uint32_t CC_MEDIA_ICON_BYTES = 2048;        // 32x32 RGB565 little-endian
constexpr uint32_t CC_MEDIA_ICON_ENTRIES = 48;        // plus one staging slot

// ---------------------------------------------------------------------------
// Setup (main.cpp), before any thread starts. Allocates both PSRAM stores
// (25 x 32768 B and 49 x 2048 B) and the mutex. Fail-soft: when either store or
// the mutex cannot be allocated, neither kind is available (capability
// artwork2.available false, every media request "Media unavailable"). Idempotent.
void cc_media_init();
bool cc_media_available(CCMediaKind kind);   // read-only; never initialises

// COM thread only.
// Adds the artwork2 capability object's fields, in ARTWORK2.md section 1 order.
// rxBytes: the CDC receive queue while it is in internal RAM (8192; 256 when the core's
// default queue was kept; 0 when the queue landed in PSRAM). Anything but 8192 fails the
// host's gating on purpose, so the host stays paced.
void cc_media_capability(JsonObject artwork2, uint32_t rxBytes);
// One {"media":{...}} request: exactly one {"mediaAck":{...}} reply. activeId is the
// active control ID while a session is entering or ready, otherwise 0. Never renews
// the lease. Sets the COM breadcrumb (media-begin/-data/-commit/-have/-other).
void cc_media_command(JsonVariantConst media, uint32_t activeId);
// The parse reply for a media line that is not JSON or is oversize (ARTWORK2.md 4.3
// step 1): {"mediaAck":{"op":"parse","error":"parse"[,"id":N][,"key":"..."]}}, id and
// key from a bounded 192-byte prefix scan. Counts as a media error. The COM thread picks
// the lines that get it with cc_bad_line_reply (cc_media_store.h).
void cc_media_parse_reply(const char* line, size_t length);
// A frame (or a control's embedded frame) was accepted: the stores' frame keys
// (pins) become its artKey (covers) and iconKey (icons). Either may be empty.
void cc_media_frame_keys(const char* artKey, const char* iconKey);
// The control ID changed (a new control, a release or a lease expiry): the upload
// context, if any, ends. Committed slots survive.
void cc_media_cancel_upload();
// A miss upload is receiving data (COM idle sleep rule, ARTWORK2.md section 3).
bool cc_media_receiving();

// LCD thread only.
// The valid slot holding `key` becomes the displayed slot (touched when displayed
// changes to it) and its bytes are returned: the pointer stays valid while that slot
// is the displayed slot (displayed slots are never evicted or written). On a miss the
// kind shows no media (displayed = -1) and false is returned.
bool cc_media_adopt(CCMediaKind kind, const char* key, const uint8_t** data, uint32_t* bytes);
// The LCD draws no media of this kind (displayed = -1).
void cc_media_release_display(CCMediaKind kind);

// Any thread. Bumped by every successful (miss) commit.
uint32_t cc_media_version();

// {"diag":"?"} (COM thread): mediaCommits, mediaErrors, mediaEvictions.
struct CCMediaCounters { uint32_t commits, errors, evictions; };
CCMediaCounters cc_media_counters();
