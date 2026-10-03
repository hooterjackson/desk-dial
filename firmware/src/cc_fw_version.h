#pragma once
// FW-PUB-004: the version the knob reports (settings "firmwareVersion", the boot banner) is the public version of
// the Desk Dial + knob pair with the internal build id and the binary letter as semver build metadata:
//   NANO_FIRMWARE_PUBLIC "2.0.0", NANO_FIRMWARE_VERSION "1.0.0-cc5.8" (internal id), CC_BUILD_BINARY 6 -> "2.0.0+cc5.8.F"
// so a bug report names exactly one image (D and F differ), and semver orders it by the public part alone.
// NANO_FIRMWARE_VERSION stays the internal id the build tooling and manifests key on. Both come from platformio.ini;
// CC_BUILD_BINARY (1..6 = ladder binary A..F, 0/absent = no letter) from the build script.
#include <stddef.h>

// "<pub>+<internal after its first '-'>[.<letter>]" into out (always terminated, truncated to size - 1).
inline void cc_fw_public_version(char* out, size_t size, const char* pub, const char* internal, int binary) {
    if (!out || size == 0) return;
    size_t n = 0;
    auto put = [&](char c) { if (n + 1 < size) out[n++] = c; };
    for (const char* p = pub ? pub : ""; *p; ++p) put(*p);
    const char* build = internal ? internal : "";
    for (const char* p = build; *p; ++p) {
        if (*p == '-') { build = p + 1; break; }
    }
    if (*build) {
        put('+');
        for (const char* p = build; *p; ++p) put(*p);
        if (binary >= 1 && binary <= 6) { put('.'); put(static_cast<char>('A' + binary - 1)); }
    }
    out[n] = '\0';
}

#if defined(NANO_FIRMWARE_PUBLIC) && defined(NANO_FIRMWARE_VERSION)
#ifdef CC_BUILD_BINARY
#define CC_FW_VERSION_BINARY CC_BUILD_BINARY
#else
#define CC_FW_VERSION_BINARY 0
#endif
// The reported version, built once (first call from setup(), before any thread starts).
inline const char* cc_fw_version() {
    static char text[48] = {0};
    if (!text[0]) cc_fw_public_version(text, sizeof text, NANO_FIRMWARE_PUBLIC, NANO_FIRMWARE_VERSION,
                                       CC_FW_VERSION_BINARY);
    return text;
}
#endif

#ifdef NANO_FIRMWARE_VERSION
// The internal build id ("1.0.0-cc5.7") the tooling and manifests key on: the diag reports it as "firmwareBuild",
// since settings "firmwareVersion" carries the public version above. The one sanctioned reader of the define.
inline const char* cc_fw_build() { return NANO_FIRMWARE_VERSION; }
#endif
