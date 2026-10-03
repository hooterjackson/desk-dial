#pragma once
// FW-BUG-028: the motor calibration as ONE NVS entry ("cal"), so a power cut during a save keeps either the old or
// the new pair, never the new direction with the old zero. Before this, "direction" and "zero_angle" were two
// separate NVS writes: a torn pair skipped the alignment with a wrong electrical angle and the knob ran away.
// A blob that fails its length, version or CRC check, or holds a direction other than +-1 or a zero outside the
// electrical turn (NaN and infinities included), loads as uncalibrated, so initFOC() aligns again.
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define CC_CAL_BLOB_VERSION 1
#define CC_CAL_ZERO_MAX 6.2832f   // SimpleFOC's zero electric angle is _normalizeAngle()d: [0, 2 pi]

struct CcCalBlob {
    uint8_t version;       // CC_CAL_BLOB_VERSION
    int8_t direction;      // +1 CW, -1 CCW
    uint8_t reserved[2];   // 0
    float zero;            // zero electric angle, rad
    uint32_t crc;          // CRC-32 (IEEE) of the 8 bytes above
};
static_assert(sizeof(CcCalBlob) == 12, "CcCalBlob is the 12-byte NVS layout");

inline uint32_t cc_cal_crc32(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

// A calibration the FOC task may skip the alignment with (comparisons are false for NaN; infinities are out of range).
inline bool cc_cal_values_ok(int direction, float zero) {
    return (direction == 1 || direction == -1) && zero >= 0.0f && zero <= CC_CAL_ZERO_MAX;
}

inline CcCalBlob cc_cal_encode(int8_t direction, float zero) {
    CcCalBlob blob;
    memset(&blob, 0, sizeof blob);
    blob.version = CC_CAL_BLOB_VERSION;
    blob.direction = direction;
    blob.zero = zero;
    blob.crc = cc_cal_crc32(reinterpret_cast<const uint8_t*>(&blob), offsetof(CcCalBlob, crc));
    return blob;
}

// True and the values when `bytes` (len bytes read back from NVS) is a whole, intact, plausible calibration.
inline bool cc_cal_decode(const void* bytes, size_t len, int8_t& direction, float& zero) {
    if (!bytes || len != sizeof(CcCalBlob)) return false;
    CcCalBlob blob;
    memcpy(&blob, bytes, sizeof blob);
    if (blob.version != CC_CAL_BLOB_VERSION) return false;
    if (blob.crc != cc_cal_crc32(reinterpret_cast<const uint8_t*>(&blob), offsetof(CcCalBlob, crc))) return false;
    if (!cc_cal_values_ok(blob.direction, blob.zero)) return false;
    direction = blob.direction;
    zero = blob.zero;
    return true;
}
