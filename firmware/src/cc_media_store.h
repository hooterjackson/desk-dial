#pragma once
#include <ArduinoJson.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "cc_media.h"

// artwork2 media store and `media` request handler (1.0.0-cc5.3, ARTWORK2.md sections 4.1-4.4).
// Platform-neutral and header-only, like cc_art_store.h: it depends only on ArduinoJson and
// cc_media.h, and is compiled unchanged by the firmware (cc_media.cpp wraps it with PSRAM,
// a mutex and the serial reply), by harness/media_tests.py (MSVC /W4 /WX, replaying
// media_store_traces.json, the fixture the Python FakeKnob replays too) and by the gnu++11
// syntax gate. C++11 rules: namespace-scope constexpr tables, no odr-used static constexpr
// members, no C++14 features. It also holds the COM thread's line transport (line assembly,
// the reply to an oversize or non-JSON line, the idle sleep rule), so the host tests check it.
//
// Store semantics (ARTWORK2.md 4.4, normative):
// - Each kind has its own store of S = entries + 1 slots of slotBytes. Per slot: valid, key,
//   bytes, crc (the committed image) and stamp. Invalidating a slot changes only `valid`:
//   its key and stamp stay as they were until the slot is committed again.
// - Per store: clock (touch(slot) sets slot.stamp = ++clock), displayed (slot or -1) and
//   frameKey (the current frame's artKey or iconKey; "" when none, or when the key cannot
//   name a media slot).
// - One global upload context covers both kinds: kind, key, bytes, crc, slot, received,
//   hit, lastChunkOffset, lastChunkLen, active.
// - Pinned slots: the displayed slot (whatever its validity) and the valid slot whose key
//   equals frameKey. Pinned slots are never victims and are never written.
// - have: true iff a valid slot holds the key; hits are touched in request order.
// - begin: hit (same key, bytes and crc) -> cancel any other upload, context {hit,
//   received = bytes}, touch; offset = bytes. Miss -> cancel any upload first, then the
//   victim = the lowest-index invalid unpinned slot, else the valid unpinned slot with the
//   smallest stamp (ties: lowest index); the victim becomes invalid at once (eviction happens
//   at begin); offset 0. When every slot is pinned the miss answers "Media unavailable" (the
//   upload it cancelled stays cancelled).
// - data: offset == received copies the chunk; an identical retry of the last chunk
//   (offset == lastChunkOffset, offset + len == received, same bytes) is accepted unchanged.
// - commit: hit -> offset = bytes, the context ends. Miss -> after the checks, every other
//   valid slot of the store with the same key is invalidated, the slot becomes valid and is
//   touched, the media version is bumped.
// - An upload context ends at a new begin (either kind), at a commit (success, checksum or
//   decode failure) and when the control ID changes. Committed slots survive until reboot.
//
// Replies (ARTWORK2.md 4.2): {"mediaAck":{"id","op","kind","key","offset"[,"error"]}} in that
// key order; "have" replies carry "have":[...] instead of key/offset. An error reply echoes
// each of id (an integer 1..0x7FFFFFFF), op, kind and key (never for have) that parsed
// validly, and offset = the upload's received bytes once a data/commit request matched the
// upload context, otherwise 0. Checks run in the order of ARTWORK2.md 4.3; a failed check
// changes no state except the checksum and decode failures, which end the upload.
// Integers: a JSON integer is a number that ArduinoJson stores as an integer, i.e. written
// without fraction or exponent and within -2^63..2^64-1 (a longer one parses as a float);
// never a bool or a string. Every integer follows ARTWORK2.md 4.3 literally:
// - begin `bytes` and `crc32`: missing, not an integer, or outside 0..0xFFFFFFFF -> "Media
//   size and CRC required" (4.3, lead ruling of 2026-09-24: negative and huge sizes
//   included); a `bytes` inside that range but outside 1..maxBytes (covers) or != 2048
//   (icons) -> "Invalid media size";
// - data `offset`: offset + decoded length > bytes -> "Media chunk bounds"; otherwise an
//   offset other than the received count that is not an identical retry (a negative one
//   included) -> "Media offset mismatch".
// Decisions this file makes where ARTWORK2.md is silent (the fixture pins them):
// - a data request whose offset is absent or not an integer fails its bounds check
//   ("Media chunk bounds"), after the data check;
// - a request that is not an object has no valid field ("Unknown media operation").

namespace cc_media_detail {
// CRC-32/IEEE (reflected 0xEDB88320), the zlib.crc32 of the host.
constexpr uint32_t kCrcTable[256] = {
    0x00000000U, 0x77073096U, 0xEE0E612CU, 0x990951BAU, 0x076DC419U, 0x706AF48FU,
    0xE963A535U, 0x9E6495A3U, 0x0EDB8832U, 0x79DCB8A4U, 0xE0D5E91EU, 0x97D2D988U,
    0x09B64C2BU, 0x7EB17CBDU, 0xE7B82D07U, 0x90BF1D91U, 0x1DB71064U, 0x6AB020F2U,
    0xF3B97148U, 0x84BE41DEU, 0x1ADAD47DU, 0x6DDDE4EBU, 0xF4D4B551U, 0x83D385C7U,
    0x136C9856U, 0x646BA8C0U, 0xFD62F97AU, 0x8A65C9ECU, 0x14015C4FU, 0x63066CD9U,
    0xFA0F3D63U, 0x8D080DF5U, 0x3B6E20C8U, 0x4C69105EU, 0xD56041E4U, 0xA2677172U,
    0x3C03E4D1U, 0x4B04D447U, 0xD20D85FDU, 0xA50AB56BU, 0x35B5A8FAU, 0x42B2986CU,
    0xDBBBC9D6U, 0xACBCF940U, 0x32D86CE3U, 0x45DF5C75U, 0xDCD60DCFU, 0xABD13D59U,
    0x26D930ACU, 0x51DE003AU, 0xC8D75180U, 0xBFD06116U, 0x21B4F4B5U, 0x56B3C423U,
    0xCFBA9599U, 0xB8BDA50FU, 0x2802B89EU, 0x5F058808U, 0xC60CD9B2U, 0xB10BE924U,
    0x2F6F7C87U, 0x58684C11U, 0xC1611DABU, 0xB6662D3DU, 0x76DC4190U, 0x01DB7106U,
    0x98D220BCU, 0xEFD5102AU, 0x71B18589U, 0x06B6B51FU, 0x9FBFE4A5U, 0xE8B8D433U,
    0x7807C9A2U, 0x0F00F934U, 0x9609A88EU, 0xE10E9818U, 0x7F6A0DBBU, 0x086D3D2DU,
    0x91646C97U, 0xE6635C01U, 0x6B6B51F4U, 0x1C6C6162U, 0x856530D8U, 0xF262004EU,
    0x6C0695EDU, 0x1B01A57BU, 0x8208F4C1U, 0xF50FC457U, 0x65B0D9C6U, 0x12B7E950U,
    0x8BBEB8EAU, 0xFCB9887CU, 0x62DD1DDFU, 0x15DA2D49U, 0x8CD37CF3U, 0xFBD44C65U,
    0x4DB26158U, 0x3AB551CEU, 0xA3BC0074U, 0xD4BB30E2U, 0x4ADFA541U, 0x3DD895D7U,
    0xA4D1C46DU, 0xD3D6F4FBU, 0x4369E96AU, 0x346ED9FCU, 0xAD678846U, 0xDA60B8D0U,
    0x44042D73U, 0x33031DE5U, 0xAA0A4C5FU, 0xDD0D7CC9U, 0x5005713CU, 0x270241AAU,
    0xBE0B1010U, 0xC90C2086U, 0x5768B525U, 0x206F85B3U, 0xB966D409U, 0xCE61E49FU,
    0x5EDEF90EU, 0x29D9C998U, 0xB0D09822U, 0xC7D7A8B4U, 0x59B33D17U, 0x2EB40D81U,
    0xB7BD5C3BU, 0xC0BA6CADU, 0xEDB88320U, 0x9ABFB3B6U, 0x03B6E20CU, 0x74B1D29AU,
    0xEAD54739U, 0x9DD277AFU, 0x04DB2615U, 0x73DC1683U, 0xE3630B12U, 0x94643B84U,
    0x0D6D6A3EU, 0x7A6A5AA8U, 0xE40ECF0BU, 0x9309FF9DU, 0x0A00AE27U, 0x7D079EB1U,
    0xF00F9344U, 0x8708A3D2U, 0x1E01F268U, 0x6906C2FEU, 0xF762575DU, 0x806567CBU,
    0x196C3671U, 0x6E6B06E7U, 0xFED41B76U, 0x89D32BE0U, 0x10DA7A5AU, 0x67DD4ACCU,
    0xF9B9DF6FU, 0x8EBEEFF9U, 0x17B7BE43U, 0x60B08ED5U, 0xD6D6A3E8U, 0xA1D1937EU,
    0x38D8C2C4U, 0x4FDFF252U, 0xD1BB67F1U, 0xA6BC5767U, 0x3FB506DDU, 0x48B2364BU,
    0xD80D2BDAU, 0xAF0A1B4CU, 0x36034AF6U, 0x41047A60U, 0xDF60EFC3U, 0xA867DF55U,
    0x316E8EEFU, 0x4669BE79U, 0xCB61B38CU, 0xBC66831AU, 0x256FD2A0U, 0x5268E236U,
    0xCC0C7795U, 0xBB0B4703U, 0x220216B9U, 0x5505262FU, 0xC5BA3BBEU, 0xB2BD0B28U,
    0x2BB45A92U, 0x5CB36A04U, 0xC2D7FFA7U, 0xB5D0CF31U, 0x2CD99E8BU, 0x5BDEAE1DU,
    0x9B64C2B0U, 0xEC63F226U, 0x756AA39CU, 0x026D930AU, 0x9C0906A9U, 0xEB0E363FU,
    0x72076785U, 0x05005713U, 0x95BF4A82U, 0xE2B87A14U, 0x7BB12BAEU, 0x0CB61B38U,
    0x92D28E9BU, 0xE5D5BE0DU, 0x7CDCEFB7U, 0x0BDBDF21U, 0x86D3D2D4U, 0xF1D4E242U,
    0x68DDB3F8U, 0x1FDA836EU, 0x81BE16CDU, 0xF6B9265BU, 0x6FB077E1U, 0x18B74777U,
    0x88085AE6U, 0xFF0F6A70U, 0x66063BCAU, 0x11010B5CU, 0x8F659EFFU, 0xF862AE69U,
    0x616BFFD3U, 0x166CCF45U, 0xA00AE278U, 0xD70DD2EEU, 0x4E048354U, 0x3903B3C2U,
    0xA7672661U, 0xD06016F7U, 0x4969474DU, 0x3E6E77DBU, 0xAED16A4AU, 0xD9D65ADCU,
    0x40DF0B66U, 0x37D83BF0U, 0xA9BCAE53U, 0xDEBB9EC5U, 0x47B2CF7FU, 0x30B5FFE9U,
    0xBDBDF21CU, 0xCABAC28AU, 0x53B39330U, 0x24B4A3A6U, 0xBAD03605U, 0xCDD70693U,
    0x54DE5729U, 0x23D967BFU, 0xB3667A2EU, 0xC4614AB8U, 0x5D681B02U, 0x2A6F2B94U,
    0xB40BBE37U, 0xC30C8EA1U, 0x5A05DF1BU, 0x2D02EF8DU
};
constexpr const char* kOpNames[] = {"begin", "data", "commit", "have"};
constexpr const char* kKindNames[] = {"cover", "icon"};
constexpr size_t kParseScanBytes = 192;   // bounded raw prefix scan (as for art)
}  // namespace cc_media_detail

enum CCMediaOp : uint8_t { CC_MEDIA_OP_BEGIN = 0, CC_MEDIA_OP_DATA, CC_MEDIA_OP_COMMIT, CC_MEDIA_OP_HAVE,
                           CC_MEDIA_OP_NONE };

// Running CRC register (start 0xFFFFFFFF, finish with ^ 0xFFFFFFFF).
inline uint32_t cc_media_crc_update(uint32_t crc, const uint8_t* data, size_t size) {
    for (size_t i = 0; i < size; ++i) crc = cc_media_detail::kCrcTable[(crc ^ data[i]) & 0xFFu] ^ (crc >> 8);
    return crc;
}
inline uint32_t cc_media_crc32(const uint8_t* data, size_t size) {
    return cc_media_crc_update(0xFFFFFFFFu, data, size) ^ 0xFFFFFFFFu;
}

// [A-Za-z0-9_-]{1,24} over a sized string (an embedded NUL never passes).
inline bool cc_media_key_valid(const char* key, size_t size) {
    if (!key || !size || size > CC_MEDIA_KEY_CHARS) return false;
    for (size_t i = 0; i < size; ++i) {
        const char c = key[i];
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-'))
            return false;
    }
    return true;
}

inline int cc_media_base64_value(char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}

// Standard base64 alphabet with padding: a non-empty multiple of 4 characters, '=' only as
// the last one or two characters (Python's base64.b64decode(validate=True) accepts exactly
// these; unused low bits of the last character are ignored, as there). Returns the decoded
// size, or 0 when the text is invalid, decodes to nothing or to more than `capacity` bytes.
inline size_t cc_media_base64_decode(const char* text, size_t size, uint8_t* out, size_t capacity) {
    if (!text || !size || size % 4) return 0;
    size_t pad = 0;
    if (text[size - 1] == '=') pad = text[size - 2] == '=' ? 2 : 1;
    const size_t decoded = size / 4 * 3 - pad;
    if (!decoded || decoded > capacity) return 0;
    size_t written = 0;
    for (size_t i = 0; i < size; i += 4) {
        uint32_t word = 0;
        for (size_t j = 0; j < 4; ++j) {
            const char c = text[i + j];
            int value = 0;                                   // a final '=' counts as 0
            if (!(c == '=' && i + 4 == size && j >= 4 - pad)) {
                value = cc_media_base64_value(c);
                if (value < 0) return 0;
            }
            word = (word << 6) | static_cast<uint32_t>(value);
        }
        out[written++] = static_cast<uint8_t>(word >> 16);
        if (written < decoded) out[written++] = static_cast<uint8_t>(word >> 8);
        if (written < decoded) out[written++] = static_cast<uint8_t>(word);
    }
    return decoded;
}

// A raw command line that is a media line: optional spaces, tabs or CRs, then {"media".
inline bool cc_media_is_line(const char* line, size_t length) {
    size_t i = 0;
    while (i < length && (line[i] == ' ' || line[i] == '\t' || line[i] == '\r')) ++i;
    return length - i >= 8 && !memcmp(line + i, "{\"media\"", 8);
}

// Position just after `"name"`, optional spaces, ':' and optional spaces; 0 if absent.
inline size_t cc_media_scan_member(const char* line, size_t limit, const char* name) {
    const size_t size = strlen(name);
    for (size_t i = 0; i + size + 2 < limit; ++i) {
        if (line[i] != '"' || memcmp(line + i + 1, name, size) || line[i + size + 1] != '"') continue;
        size_t j = i + size + 2;
        while (j < limit && line[j] == ' ') ++j;
        if (j >= limit || line[j] != ':') continue;
        ++j;
        while (j < limit && line[j] == ' ') ++j;
        return j < limit ? j : 0;
    }
    return 0;
}

// The parse reply of ARTWORK2.md 4.3 step 1 into `ack` (the mediaAck object):
// {"op":"parse","error":"parse"[,"id":N][,"key":"..."]}. id and key come from the first
// 192 bytes of the raw line and appear only when found intact: id a complete integer
// 1..0x7FFFFFFF (delimited, no leading zero, no fraction), key [A-Za-z0-9_-]{1,24} with
// its closing quote. `key` receives the key text and must outlive the serialisation.
inline void cc_media_parse_ack(const char* line, size_t length, JsonObject ack,
                               char (&key)[CC_MEDIA_KEY_CHARS + 1]) {
    const size_t limit = length < cc_media_detail::kParseScanBytes ? length : cc_media_detail::kParseScanBytes;
    ack["op"] = "parse";
    ack["error"] = "parse";
    size_t at = cc_media_scan_member(line, limit, "id");
    if (at) {
        uint64_t id = 0;
        size_t digits = 0;
        while (at + digits < limit && digits < 11 && line[at + digits] >= '0' && line[at + digits] <= '9') {
            id = id * 10 + static_cast<uint64_t>(line[at + digits] - '0');
            ++digits;
        }
        const char next = at + digits < limit ? line[at + digits] : 0;
        if (digits && digits <= 10 && (next == ',' || next == '}' || next == ' ') && line[at] != '0' &&
            id >= 1 && id <= 0x7FFFFFFFu) ack["id"] = static_cast<uint32_t>(id);
    }
    key[0] = 0;
    at = cc_media_scan_member(line, limit, "key");
    if (at && line[at] == '"') {
        size_t n = 0;
        while (at + 1 + n < limit && n <= CC_MEDIA_KEY_CHARS && cc_media_key_valid(line + at + 1 + n, 1)) ++n;
        if (n >= 1 && n <= CC_MEDIA_KEY_CHARS && at + 1 + n < limit && line[at + 1 + n] == '"') {
            memcpy(key, line + at + 1, n);
            key[n] = 0;
            ack["key"] = key;   // char array: copied into the document
        }
    }
}

// ---------------------------------------------------------------------------
// COM transport (com_thread.cpp). Kept here, platform-neutral, so that media_tests.cpp checks
// the code the COM thread runs: line assembly with the oversize rule, the reply a bad line
// gets (ARTWORK2.md 4.3 step 1) and the idle sleep rule (ARTWORK2.md section 3).

// A raw command line that is an art line: optional spaces, tabs or CRs, then {"art".
inline bool cc_art_is_line(const char* line, size_t length) {
    size_t i = 0;
    while (i < length && (line[i] == ' ' || line[i] == '\t' || line[i] == '\r')) ++i;
    return length - i >= 6 && !memcmp(line + i, "{\"art\"", 6);
}

// The reply to a line that is oversize or not JSON: an art line is answered as art (contract
// section 7: the artAck parse reply), a media line as media (the mediaAck parse reply of
// cc_media_parse_reply, which counts in mediaErrors), any other line with a bare
// {"error":...}. Art is tested first, as in cc5.2.
enum CCBadLineReply : uint8_t { CC_BAD_LINE_ERROR = 0, CC_BAD_LINE_ART, CC_BAD_LINE_MEDIA };
inline CCBadLineReply cc_bad_line_reply(const char* line, size_t length) {
    if (cc_art_is_line(line, length)) return CC_BAD_LINE_ART;
    return cc_media_is_line(line, length) ? CC_BAD_LINE_MEDIA : CC_BAD_LINE_ERROR;
}

// What one received byte did to the line being assembled.
enum CCLineEvent : uint8_t {
    CC_COM_LINE_NONE = 0,    // stored, or dropped while an oversize line runs to its newline
    CC_COM_LINE_COMPLETE,    // a newline: text()/length() is the line without it, NUL-terminated,
                         // until the next feed() or expire()
    CC_COM_LINE_OVERSIZE,    // byte capacity + 1 of a line arrived: send the line's one reply now.
                         // text()/length() hold its first `capacity` bytes (the prefix scan);
                         // the rest of the line is dropped through its newline
    CC_COM_LINE_DISCARDED    // the newline that ends an oversize line: no second reply
};

// Non-blocking line assembly (cc5.2 Stage 2): bytes are fed as they arrive, a partial line
// waits in the buffer for the next pass. `buffer` holds capacity + 1 bytes.
class CCLineAssembler {
public:
    CCLineAssembler(char* buffer, size_t capacity) : buffer_(buffer), capacity_(capacity) {}

    CCLineEvent feed(char c, uint32_t nowMs) {
        if (complete_) { complete_ = false; length_ = 0; }   // the previous line was handled
        lastByteMs_ = nowMs;
        if (c == '\n') {
            if (oversize_) { oversize_ = false; length_ = 0; return CC_COM_LINE_DISCARDED; }
            buffer_[length_] = 0;
            complete_ = true;
            return CC_COM_LINE_COMPLETE;
        }
        if (oversize_) return CC_COM_LINE_NONE;
        if (length_ == capacity_) {
            buffer_[length_] = 0;
            oversize_ = true;
            return CC_COM_LINE_OVERSIZE;
        }
        buffer_[length_++] = c;
        return CC_COM_LINE_NONE;
    }
    const char* text() const { return buffer_; }
    size_t length() const { return length_; }
    // A line is arriving, or an oversize line is being dropped.
    bool partial() const { return oversize_ || (length_ > 0 && !complete_); }
    // Drops a partial line whose last byte is at least abandonMs old: a writer that stalls this
    // long mid-line has gone (the lease is 2 s), and its fragment must never be glued onto the
    // next session's first command.
    void expire(uint32_t nowMs, uint32_t abandonMs) {
        if (partial() && static_cast<uint32_t>(nowMs - lastByteMs_) >= abandonMs) {
            length_ = 0;
            oversize_ = false;
        }
    }

private:
    char* buffer_;
    size_t capacity_;
    size_t length_ = 0;
    bool oversize_ = false, complete_ = false;
    uint32_t lastByteMs_ = 0;
};

// COM idle sleep (ARTWORK2.md section 3), in FreeRTOS ticks: 1 while a line is arriving
// (partial), more bytes are queued, a media upload is receiving, or a complete line was handled
// less than 20 ms ago (lineHandled: a line has been handled since boot; sinceLineMs: how long
// ago the last one was); otherwise 10, as in cc5.2. A stop-and-wait host's next line then waits
// about 1-3 ms instead of about 10 ms.
constexpr uint32_t CC_COM_RECENT_LINE_MS = 20;
constexpr uint32_t CC_COM_BUSY_TICKS = 1;
constexpr uint32_t CC_COM_IDLE_TICKS = 10;
inline uint32_t cc_com_idle_ticks(bool partial, bool queued, bool receiving, bool lineHandled,
                                  uint32_t sinceLineMs) {
    const bool recentLine = lineHandled && sinceLineMs < CC_COM_RECENT_LINE_MS;
    return partial || queued || receiving || recentLine ? CC_COM_BUSY_TICKS : CC_COM_IDLE_TICKS;
}

struct CCMediaSlot {
    bool valid;
    char key[CC_MEDIA_KEY_CHARS + 1];
    uint32_t bytes, crc, stamp;
};

struct CCMediaKindConfig {
    uint32_t entries;     // cached entries: the store has entries + 1 slots
    uint32_t slotBytes;   // bytes per slot (at least maxBytes)
    uint32_t minBytes;    // begin sizes accepted: minBytes..maxBytes
    uint32_t maxBytes;
};

struct CCMediaConfig {
    CCMediaKindConfig kinds[2];   // indexed by CCMediaKind
    uint32_t chunkBytes;          // decoded bytes per data line (at most the scratch buffer)
    uint32_t haveKeys;            // keys per have query
    bool validateCovers;          // run the cover check (cc_jpeg_validate) at commit
};

// The device configuration (ARTWORK2.md section 1).
inline CCMediaConfig cc_media_device_config() {
    CCMediaConfig config;
    config.kinds[CC_MEDIA_COVER].entries = CC_MEDIA_COVER_ENTRIES;
    config.kinds[CC_MEDIA_COVER].slotBytes = CC_MEDIA_COVER_MAX_BYTES;
    config.kinds[CC_MEDIA_COVER].minBytes = 1;
    config.kinds[CC_MEDIA_COVER].maxBytes = CC_MEDIA_COVER_MAX_BYTES;
    config.kinds[CC_MEDIA_ICON].entries = CC_MEDIA_ICON_ENTRIES;
    config.kinds[CC_MEDIA_ICON].slotBytes = CC_MEDIA_ICON_BYTES;
    config.kinds[CC_MEDIA_ICON].minBytes = CC_MEDIA_ICON_BYTES;
    config.kinds[CC_MEDIA_ICON].maxBytes = CC_MEDIA_ICON_BYTES;
    config.chunkBytes = CC_MEDIA_CHUNK_BYTES;
    config.haveKeys = CC_MEDIA_HAVE_KEYS;
    config.validateCovers = true;
    return config;
}

// The capability object {"capabilities":{..., "artwork2":{...}}} in ARTWORK2.md section 1 order
// (the host requires every listed field with exactly this type and value). available: both
// stores allocated; rxBytes: the CDC receive queue actually configured.
inline void cc_media_capability_fields(JsonObject a, bool available, uint32_t rxBytes) {
    a["version"] = CC_MEDIA_VERSION;
    a["available"] = available;
    a["composited"] = "scrim80";
    a["paced"] = false;
    a["rxBytes"] = rxBytes;
    a["chunkBytes"] = CC_MEDIA_CHUNK_BYTES;
    a["haveKeys"] = CC_MEDIA_HAVE_KEYS;
    JsonObject cover = a["cover"].to<JsonObject>();
    cover["width"] = CC_MEDIA_COVER_SIZE;
    cover["height"] = CC_MEDIA_COVER_SIZE;
    cover["format"] = "JPEG";
    cover["maxBytes"] = CC_MEDIA_COVER_MAX_BYTES;
    cover["entries"] = CC_MEDIA_COVER_ENTRIES;
    JsonObject icon = a["icon"].to<JsonObject>();
    icon["width"] = CC_MEDIA_ICON_SIZE;
    icon["height"] = CC_MEDIA_ICON_SIZE;
    icon["format"] = "RGB565_LE";
    icon["bytes"] = CC_MEDIA_ICON_BYTES;
    icon["entries"] = CC_MEDIA_ICON_ENTRIES;
    icon["background"] = "black";
}

// Cover payload check at commit: true when the bytes are a baseline JPEG the LCD can draw.
typedef bool (*CCMediaCoverCheck)(const uint8_t* data, uint32_t bytes);

class CCMediaStore {
public:
    // memory[kind]: (entries + 1) * slotBytes bytes; slots[kind]: entries + 1 slots; nullptr
    // leaves that kind unavailable. scratch: chunkBytes bytes for decoded data (nullptr leaves
    // both kinds unavailable). Resets every slot and counter.
    void init(const CCMediaConfig& config, uint8_t* coverMemory, CCMediaSlot* coverSlots,
              uint8_t* iconMemory, CCMediaSlot* iconSlots, uint8_t* scratch, CCMediaCoverCheck check) {
        config_ = config;
        scratch_ = scratch;
        check_ = check;
        kinds_[CC_MEDIA_COVER].memory = coverMemory;
        kinds_[CC_MEDIA_COVER].slots = coverSlots;
        kinds_[CC_MEDIA_ICON].memory = iconMemory;
        kinds_[CC_MEDIA_ICON].slots = iconSlots;
        for (uint8_t k = 0; k < 2; ++k) {
            Kind& kind = kinds_[k];
            kind.count = config.kinds[k].entries + 1;
            kind.clock = 0;
            kind.displayed = -1;
            kind.frameKey[0] = 0;
            if (kind.slots)
                for (uint32_t i = 0; i < kind.count; ++i) {
                    CCMediaSlot& slot = kind.slots[i];
                    slot.valid = false; slot.key[0] = 0; slot.bytes = slot.crc = slot.stamp = 0;
                }
        }
        upload_ = Upload();
        version_ = commits_ = errors_ = evictions_ = 0;
    }

    bool available(uint8_t kind) const {
        return kind < 2 && kinds_[kind].memory && kinds_[kind].slots && scratch_ && config_.kinds[kind].entries;
    }

    // One media request (the value of "media") into `ack` (the mediaAck object). activeId: the
    // active control ID while a session is entering or ready, otherwise 0. Returns the error,
    // or nullptr on success. Strings in the reply point into `media`: serialise `ack` while the
    // request document is alive.
    const char* handle(JsonVariantConst media, uint32_t activeId, JsonObject ack) {
        JsonObjectConst object = media.as<JsonObjectConst>();
        Request r;
        r.idValid = uint_in(object["id"], 1, 0x7FFFFFFFu, r.id);
        r.op = CC_MEDIA_OP_NONE;
        for (uint8_t i = 0; i < 4; ++i)
            if (token(object["op"], cc_media_detail::kOpNames[i])) r.op = i;
        r.kind = -1;
        for (int8_t i = 0; i < 2; ++i)
            if (token(object["kind"], cc_media_detail::kKindNames[i])) r.kind = i;
        r.keyValid = key_of(object["key"], r.key);

        if (r.op == CC_MEDIA_OP_NONE) return fail(ack, r, "Unknown media operation", 0);
        if (r.kind < 0) return fail(ack, r, "Unknown media kind", 0);
        const uint8_t k = static_cast<uint8_t>(r.kind);
        if (!available(k)) return fail(ack, r, "Media unavailable", 0);
        if (!r.idValid || !activeId || r.id != activeId) return fail(ack, r, "Stale media control", 0);
        switch (r.op) {
            case CC_MEDIA_OP_HAVE: return have(object["keys"], r, k, ack);
            case CC_MEDIA_OP_BEGIN: return begin(object, r, k, ack);
            case CC_MEDIA_OP_DATA: return data(object, r, k, ack);
            default: return commit(r, k, ack);
        }
    }

    // A frame was accepted: its artKey (covers) or iconKey (icons) becomes the kind's frame key.
    // A key that cannot name a media slot (empty, too long, bad characters) pins nothing.
    void setFrameKey(uint8_t kind, const char* key) {
        if (kind >= 2) return;
        char* out = kinds_[kind].frameKey;
        const size_t size = key ? strlen(key) : 0;
        if (cc_media_key_valid(key, size)) { memcpy(out, key, size); out[size] = 0; }
        else out[0] = 0;
    }

    // LCD adoption (ARTWORK2.md 4.4): the valid slot holding `key` becomes displayed and is
    // touched when displayed changes to it; a miss (or an empty key) leaves displayed = -1.
    bool adopt(uint8_t kind, const char* key, const uint8_t** data, uint32_t* bytes) {
        if (!available(kind)) return false;
        Kind& store = kinds_[kind];
        const int32_t slot = find(store, key);
        if (slot < 0) { store.displayed = -1; return false; }
        if (store.displayed != slot) { store.displayed = slot; touch(store, static_cast<uint32_t>(slot)); }
        if (data) *data = slot_data(kind, static_cast<uint32_t>(slot));
        if (bytes) *bytes = store.slots[slot].bytes;
        return true;
    }
    void releaseDisplay(uint8_t kind) { if (kind < 2) kinds_[kind].displayed = -1; }
    void cancelUpload() { upload_.active = false; }
    bool receiving() const { return upload_.active && !upload_.hit; }
    uint32_t version() const { return version_; }
    uint32_t commits() const { return commits_; }
    uint32_t errors() const { return errors_; }
    uint32_t evictions() const { return evictions_; }
    void noteParseError() { ++errors_; }   // a parse reply sent for a media line

    // Inspection (tests and diagnostics).
    uint32_t slotCount(uint8_t kind) const { return kind < 2 ? kinds_[kind].count : 0; }
    const CCMediaSlot& slot(uint8_t kind, uint32_t index) const { return kinds_[kind].slots[index]; }
    const uint8_t* slot_data(uint8_t kind, uint32_t index) const {
        return kinds_[kind].memory + static_cast<size_t>(index) * config_.kinds[kind].slotBytes;
    }
    int32_t displayed(uint8_t kind) const { return kind < 2 ? kinds_[kind].displayed : -1; }
    uint32_t clock(uint8_t kind) const { return kind < 2 ? kinds_[kind].clock : 0; }
    const char* frameKey(uint8_t kind) const { return kind < 2 ? kinds_[kind].frameKey : ""; }
    bool uploadActive() const { return upload_.active; }

private:
    struct Kind {
        uint8_t* memory = nullptr;
        CCMediaSlot* slots = nullptr;
        uint32_t count = 0, clock = 0;
        int32_t displayed = -1;
        char frameKey[CC_MEDIA_KEY_CHARS + 1] = {};
    };
    struct Upload {
        bool active = false, hit = false;
        uint8_t kind = 0;
        char key[CC_MEDIA_KEY_CHARS + 1] = {};
        uint32_t slot = 0, bytes = 0, crc = 0, received = 0, running = 0, lastOffset = 0, lastLength = 0;
    };
    struct Request {
        uint32_t id = 0;
        bool idValid = false, keyValid = false;
        uint8_t op = CC_MEDIA_OP_NONE;
        int8_t kind = -1;
        const char* key = nullptr;
    };

    static bool uint_in(JsonVariantConst value, uint32_t lo, uint32_t hi, uint32_t& out) {
        if (value.is<bool>() || !value.is<uint32_t>()) return false;
        const uint32_t number = value.as<uint32_t>();
        if (number < lo || number > hi) return false;
        out = number;
        return true;
    }
    // A JSON integer (see the header comment): kIntNone when the value is not one, kIntValue
    // with `out` set when it fits int64_t, kIntHuge above INT64_MAX (larger than any size or
    // offset the store can hold).
    enum IntClass : uint8_t { kIntNone = 0, kIntValue, kIntHuge };
    static IntClass int_of(JsonVariantConst value, int64_t& out) {
        if (value.is<bool>()) return kIntNone;
        if (value.is<int64_t>()) { out = value.as<int64_t>(); return kIntValue; }
        return value.is<uint64_t>() ? kIntHuge : kIntNone;
    }
    static bool token(JsonVariantConst value, const char* name) {
        if (!value.is<const char*>()) return false;
        const JsonString text = value.as<JsonString>();
        return strlen(name) == text.size() && !memcmp(name, text.c_str(), text.size());
    }
    static bool key_of(JsonVariantConst value, const char*& key) {
        if (!value.is<const char*>()) return false;
        const JsonString text = value.as<JsonString>();
        if (!cc_media_key_valid(text.c_str(), text.size())) return false;
        key = text.c_str();
        return true;
    }

    void touch(Kind& store, uint32_t slot) { store.slots[slot].stamp = ++store.clock; }
    static int32_t find(const Kind& store, const char* key) {
        if (!key || !cc_media_key_valid(key, strlen(key))) return -1;
        for (uint32_t i = 0; i < store.count; ++i)
            if (store.slots[i].valid && !strcmp(store.slots[i].key, key)) return static_cast<int32_t>(i);
        return -1;
    }
    static bool pinned(const Kind& store, uint32_t slot) {
        if (static_cast<int32_t>(slot) == store.displayed) return true;
        return store.frameKey[0] && store.slots[slot].valid && !strcmp(store.slots[slot].key, store.frameKey);
    }
    static int32_t victim(const Kind& store) {
        for (uint32_t i = 0; i < store.count; ++i)
            if (!store.slots[i].valid && !pinned(store, i)) return static_cast<int32_t>(i);
        int32_t best = -1;
        for (uint32_t i = 0; i < store.count; ++i) {
            if (!store.slots[i].valid || pinned(store, i)) continue;
            if (best < 0 || store.slots[i].stamp < store.slots[best].stamp) best = static_cast<int32_t>(i);
        }
        return best;
    }
    bool upload_matches(const Request& r, uint8_t kind) const {
        return upload_.active && upload_.kind == kind && !strcmp(upload_.key, r.key);
    }

    // id, op, kind, key: each only when it parsed validly (key never for have).
    static void head(JsonObject ack, const Request& r) {
        if (r.idValid) ack["id"] = r.id;
        if (r.op != CC_MEDIA_OP_NONE) ack["op"] = cc_media_detail::kOpNames[r.op];
        if (r.kind >= 0) ack["kind"] = cc_media_detail::kKindNames[r.kind];
        if (r.op != CC_MEDIA_OP_HAVE && r.keyValid) ack["key"] = r.key;
    }
    const char* fail(JsonObject ack, const Request& r, const char* error, uint32_t offset) {
        head(ack, r);
        if (r.op != CC_MEDIA_OP_HAVE) ack["offset"] = offset;
        ack["error"] = error;
        ++errors_;
        return error;
    }
    const char* ok(JsonObject ack, const Request& r, uint32_t offset) {
        head(ack, r);
        ack["offset"] = offset;
        return nullptr;
    }

    const char* have(JsonVariantConst keys, const Request& r, uint8_t kind, JsonObject ack) {
        if (!keys.is<JsonArrayConst>()) return fail(ack, r, "Invalid media keys", 0);
        JsonArrayConst list = keys.as<JsonArrayConst>();
        if (!list.size() || list.size() > config_.haveKeys) return fail(ack, r, "Invalid media keys", 0);
        for (JsonVariantConst item : list) {
            const char* key = nullptr;
            if (!key_of(item, key)) return fail(ack, r, "Invalid media keys", 0);
        }
        head(ack, r);
        JsonArray result = ack["have"].to<JsonArray>();
        Kind& store = kinds_[kind];
        for (JsonVariantConst item : list) {
            const int32_t slot = find(store, item.as<const char*>());
            if (slot >= 0) touch(store, static_cast<uint32_t>(slot));
            result.add(slot >= 0);
        }
        return nullptr;
    }

    const char* begin(JsonObjectConst object, const Request& r, uint8_t kind, JsonObject ack) {
        if (!r.keyValid) return fail(ack, r, "Invalid media key", 0);
        uint32_t bytes = 0, crc = 0;
        if (!uint_in(object["bytes"], 0, 0xFFFFFFFFu, bytes) || !uint_in(object["crc32"], 0, 0xFFFFFFFFu, crc))
            return fail(ack, r, "Media size and CRC required", 0);
        const CCMediaKindConfig& limits = config_.kinds[kind];
        if (bytes < limits.minBytes || bytes > limits.maxBytes || bytes > limits.slotBytes)
            return fail(ack, r, "Invalid media size", 0);
        Kind& store = kinds_[kind];
        for (uint32_t i = 0; i < store.count; ++i) {
            const CCMediaSlot& slot = store.slots[i];
            if (!slot.valid || strcmp(slot.key, r.key) || slot.bytes != bytes || slot.crc != crc) continue;
            start(kind, r.key, i, bytes, crc, true);   // hit: cancels any other upload
            touch(store, i);
            return ok(ack, r, bytes);
        }
        upload_.active = false;                                      // a miss cancels any upload first
        const int32_t slot = victim(store);
        if (slot < 0) return fail(ack, r, "Media unavailable", 0);   // every slot pinned (S < 3 only)
        CCMediaSlot& chosen = store.slots[slot];
        if (chosen.valid) ++evictions_;
        chosen.valid = false;                                        // eviction happens at begin
        start(kind, r.key, static_cast<uint32_t>(slot), bytes, crc, false);
        return ok(ack, r, 0);
    }
    void start(uint8_t kind, const char* key, uint32_t slot, uint32_t bytes, uint32_t crc, bool hit) {
        upload_ = Upload();
        upload_.active = true;
        upload_.hit = hit;
        upload_.kind = kind;
        const size_t size = strlen(key);                 // a validated key: 1..24 characters
        memcpy(upload_.key, key, size);
        upload_.key[size] = 0;
        upload_.slot = slot;
        upload_.bytes = bytes;
        upload_.crc = crc;
        upload_.received = hit ? bytes : 0;
        upload_.running = 0xFFFFFFFFu;
    }

    const char* data(JsonObjectConst object, const Request& r, uint8_t kind, JsonObject ack) {
        if (!r.keyValid) return fail(ack, r, "Invalid media key", 0);
        if (!upload_matches(r, kind) || upload_.hit) return fail(ack, r, "No matching media upload", 0);
        JsonVariantConst encoded = object["data"];
        size_t length = 0;
        if (encoded.is<const char*>()) {
            const JsonString text = encoded.as<JsonString>();
            length = cc_media_base64_decode(text.c_str(), text.size(), scratch_, config_.chunkBytes);
        }
        if (!length) return fail(ack, r, "Invalid media data", upload_.received);
        // offset + length > bytes (an offset above bytes first, so the sum cannot overflow;
        // bytes <= slotBytes and length <= chunkBytes keep it far inside int64_t).
        int64_t offset = 0;
        const int64_t total = static_cast<int64_t>(upload_.bytes);
        if (int_of(object["offset"], offset) != kIntValue || offset > total ||
            offset + static_cast<int64_t>(length) > total)
            return fail(ack, r, "Media chunk bounds", upload_.received);
        uint8_t* target = kinds_[kind].memory + static_cast<size_t>(upload_.slot) * config_.kinds[kind].slotBytes;
        if (offset == static_cast<int64_t>(upload_.received)) {
            memcpy(target + static_cast<size_t>(offset), scratch_, length);
            upload_.running = cc_media_crc_update(upload_.running, scratch_, length);
            upload_.received += static_cast<uint32_t>(length);
            upload_.lastOffset = static_cast<uint32_t>(offset);
            upload_.lastLength = static_cast<uint32_t>(length);
        } else if (!(offset >= 0 && offset == static_cast<int64_t>(upload_.lastOffset) &&
                     offset + static_cast<int64_t>(length) == static_cast<int64_t>(upload_.received) &&
                     !memcmp(target + static_cast<size_t>(offset), scratch_, length))) {
            return fail(ack, r, "Media offset mismatch", upload_.received);   // a negative offset too
        }   // else: an identical retry of the last chunk, accepted with no change
        return ok(ack, r, upload_.received);
    }

    const char* commit(const Request& r, uint8_t kind, JsonObject ack) {
        if (!r.keyValid) return fail(ack, r, "Invalid media key", 0);
        if (!upload_matches(r, kind)) return fail(ack, r, "No matching media upload", 0);
        if (upload_.hit) {
            upload_.active = false;
            ++commits_;
            return ok(ack, r, upload_.bytes);
        }
        if (upload_.received != upload_.bytes) return fail(ack, r, "Media upload incomplete", upload_.received);
        if ((upload_.running ^ 0xFFFFFFFFu) != upload_.crc) {
            upload_.active = false;
            return fail(ack, r, "Media checksum mismatch", upload_.received);
        }
        Kind& store = kinds_[kind];
        if (kind == CC_MEDIA_COVER && config_.validateCovers &&
            (!check_ || !check_(slot_data(kind, upload_.slot), upload_.bytes))) {
            upload_.active = false;
            return fail(ack, r, "Media decode failed", upload_.received);
        }
        for (uint32_t i = 0; i < store.count; ++i)
            if (i != upload_.slot && store.slots[i].valid && !strcmp(store.slots[i].key, upload_.key))
                store.slots[i].valid = false;
        CCMediaSlot& slot = store.slots[upload_.slot];
        memcpy(slot.key, upload_.key, sizeof(slot.key));
        slot.bytes = upload_.bytes;
        slot.crc = upload_.crc;
        slot.valid = true;
        touch(store, upload_.slot);
        ++version_;
        ++commits_;
        upload_.active = false;
        return ok(ack, r, upload_.bytes);
    }

    CCMediaConfig config_ = CCMediaConfig();
    Kind kinds_[2];
    Upload upload_;
    uint8_t* scratch_ = nullptr;
    CCMediaCoverCheck check_ = nullptr;
    uint32_t version_ = 0, commits_ = 0, errors_ = 0, evictions_ = 0;
};
