#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Eight cached RGB565 covers plus one staging slot. The active buffer is immutable until the
// LCD thread adopts a fully checked replacement; uploads never touch pixels
// being rendered. No filesystem, persistent profile, or motor state is involved.
//
// Identity: a key names immutable content. The control ID binds an upload to
// the current selection (begin/data/commit must match it); display adoption is
// by content key only, so a cover cached under one control is reused by the
// next. At most one valid slot holds a key: a successful commit invalidates
// every other slot with the same key, so adopt() can never return stale pixels.
//
// Eviction happens at begin(): unless the key+CRC is already cached, begin()
// picks a slot (the first invalid one, else the least recently used) other than
// the active one and invalidates it immediately. Its old cover is gone even if
// the upload is later abandoned or fails its checks; the host simply re-sends.
class CCArtStore {
public:
    static constexpr uint32_t width = 120, slots = 9, bytes = width * width * 2;
    static constexpr uint32_t chunkBytes = 384;
    void init(uint8_t* memory) { for (uint32_t i=0;i<slots;++i) buffers_[i] = memory ? memory + i * bytes : nullptr; }
    bool available() const { return buffers_[0] != nullptr; }
    uint32_t offset() const { return offset_; }
    const char* begin(uint32_t id, const char* key, uint32_t size, uint32_t crc) {
        if (!available()) return "Artwork memory unavailable";
        if (size != bytes) return "Artwork size must be 28800";
        id_ = id; strncpy(key_, key, sizeof(key_) - 1); key_[sizeof(key_)-1] = 0;
        expectedCrc_ = crc; crc_ = 0xFFFFFFFF; offset_ = 0;
        for (uint32_t i=0;i<slots;++i) if (valid_[i] && !strcmp(keys_[i],key) && crcs_[i] == crc) {
            receiving_ = i; ready_ = true; offset_ = bytes; crc_ = crc ^ 0xFFFFFFFFU; return nullptr;
        }
        int oldest = -1;
        for (uint32_t i=0;i<slots;++i) if (static_cast<int>(i) != active_ &&
            (oldest < 0 || !valid_[i] || ages_[i] < ages_[oldest])) {
            oldest = i; if (!valid_[i]) break;
        }
        receiving_ = oldest; ready_ = false; valid_[receiving_] = false;
        return nullptr;
    }
    const char* data(uint32_t id, const char* key, uint32_t offset,
                     const uint8_t* data, size_t length) {
        if (receiving_ < 0 || ready_ || id != id_ || strcmp(key, key_)) return "No matching artwork upload";
        if (!length || length > chunkBytes || offset > bytes || length > bytes - offset) return "Artwork chunk bounds";
        if (offset < offset_ && length <= offset_ - offset &&
            !memcmp(buffers_[receiving_] + offset, data, length)) return nullptr; // lost ACK retry
        if (offset != offset_) return "Artwork offset mismatch";
        memcpy(buffers_[receiving_] + offset, data, length);
        for (size_t i = 0; i < length; ++i) {
            crc_ ^= data[i];
            for (uint8_t bit = 0; bit < 8; ++bit) crc_ = (crc_ >> 1) ^ ((crc_ & 1) ? 0xEDB88320U : 0);
        }
        offset_ += length; return nullptr;
    }
    const char* commit(uint32_t id, const char* key) {
        if (id != id_ || strcmp(key, key_)) return "No matching artwork upload";
        if (offset_ != bytes) return "Artwork upload incomplete";
        if ((crc_ ^ 0xFFFFFFFFU) != expectedCrc_) return "Artwork checksum mismatch";
        if (receiving_ >= 0) {
            // One slot per key. The active slot stays intact (and unevictable)
            // until the LCD adopts; only its validity changes here.
            for (uint32_t i=0;i<slots;++i)
                if (static_cast<int>(i) != receiving_ && valid_[i] && !strcmp(keys_[i],key_)) valid_[i] = false;
            ready_ = true; valid_[receiving_] = true;
            strncpy(keys_[receiving_],key_,sizeof(key_)); crcs_[receiving_] = expectedCrc_;
            ages_[receiving_] = ++clock_;
        }
        return nullptr;
    }
    const uint8_t* adopt(const char* key) {
        if (!key[0]) return nullptr;
        // By content key only: a control or mode change may reuse a cached
        // cover. The protocol still checks every upload against the active ID.
        for (uint32_t i=0;i<slots;++i) if (valid_[i] && !strcmp(keys_[i],key)) {
            active_ = i; ages_[i] = ++clock_; return buffers_[i];
        }
        return nullptr;
    }
private:
    uint8_t* buffers_[slots] = {};
    int active_ = -1, receiving_ = -1;
    bool ready_ = false;
    uint32_t id_ = 0, offset_ = 0, crc_ = 0, expectedCrc_ = 0, clock_ = 0;
    char key_[65] = {}, keys_[slots][65] = {};
    uint32_t crcs_[slots] = {}, ages_[slots] = {};
    bool valid_[slots] = {};
};
