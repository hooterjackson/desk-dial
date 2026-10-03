#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Recovery is based on the endpoint that was actually hit, not the midpoint
// of the already-updated position (which is ambiguous for a two-position range).
constexpr uint16_t inward_from_boundary(uint16_t start, uint16_t end, uint16_t boundary) {
    return start >= end ? start : (boundary == start ? start + 1 : end - 1);
}
static_assert(inward_from_boundary(0,1,0) == 1, "Lower stop must retain inward step in a two-item list");
static_assert(inward_from_boundary(0,1,1) == 0, "Upper stop must retain inward step in a two-item list");
static_assert(inward_from_boundary(0,0,0) == 0, "Single item cannot generate a step");
static_assert(inward_from_boundary(0,2,0) == 1 && inward_from_boundary(0,2,2) == 1, "Transport returns to neutral");
static_assert(inward_from_boundary(10,20,10) == 11 && inward_from_boundary(10,20,20) == 19, "Nonzero native bounds remain valid");

// FW-BUG-034: the position HapticState::load_profile() loads. With a position (every constructor: a host control, a
// native profile, a restored one) it is that position, 65535 included; without one, the current position clamped to
// the profile's bounds `lo`..`hi` (already scaled in VERNIER mode, as detent_handler() counts). The "no position"
// case used to be the in-band 0xFFFF, so a control at 65535 (or a native profile restored there) loaded as 0.
inline uint16_t haptic_load_position(bool hasPosition, uint16_t position, uint16_t current, uint16_t lo, uint16_t hi) {
    if (hasPosition) return position;
    return current < lo ? lo : (current > hi ? hi : current);
}

// 1.0.0-cc5.5 (F1): a detent profile the haptic code can run. detent_width is 2*pi / detent_count (and
// divided by vernier in VERNIER mode), num_detents is end_pos - start_pos (unsigned), so a stored or sent
// profile with detentCount 0, vernier 0 or endPos < startPos divided by zero or wrapped the range. Brought
// to detent_count >= 1, vernier >= 1 and end_pos >= start_pos (end_pos raised to start_pos); every valid
// profile is left exactly as it was. Returns true when a field had to change. A template on the profile
// type, so this header stays free of SimpleFOC (haptic_api.h); applied in HapticState::load_profile()
// (every profile the FOC loads: stored, native, host control) and in HapticProfile's JSON load/update.
template <typename Profile> bool haptic_profile_sanitize(Profile& profile) {
    bool changed = false;
    if (profile.detent_count < 1) { profile.detent_count = 1; changed = true; }
    if (profile.vernier < 1) { profile.vernier = 1; changed = true; }
    if (profile.end_pos < profile.start_pos) { profile.end_pos = profile.start_pos; changed = true; }
    return changed;
}

// FW-SEC-001: profile slots. An empty name marks a FREE slot (HapticProfileManager), never a profile: looking up ""
// used to return the first free slot, so {"current":""} (or deleting / renaming away the current profile) made a
// blank slot current, {"save":true} stored "" and every boot selected the blank slot again. Templates on the profile
// and string types (Arduino String on the knob, std::string in harness/haptic_fx_tests.cpp).
// A usable profile name: 1..16 bytes (ComThread::isProfileNameOk's rule, FW-BUG-005): the name becomes the SPIFFS
// path "/profiles/<name>.json", and SPIFFS paths hold at most 31 characters. FW-BUG-027: also no '/' (it would make
// "/profiles/<a>/<b>.json") and no control byte (< 0x20 or 0x7F; an embedded NUL cuts the path short), the same rule
// as ComThread::isProfileNameOk, so a rename path that does not come through the COM command is held to it too.
template <typename Str> bool haptic_profile_name_ok(const Str& name) {
    if (name.length() < 1 || name.length() > 16) return false;
    for (unsigned i = 0; i < static_cast<unsigned>(name.length()); ++i) {
        const unsigned char c = static_cast<unsigned char>(name[i]);
        if (c < 0x20 || c == 0x7F || c == '/') return false;
    }
    return true;
}
// FW-BUG-027: a profile's description and tag are capped (HapticProfileManager.h: desc 50, tag 20 bytes; the COM
// command refuses longer ones), so a profile loaded from an older file or updated by any other path cannot exceed
// them either. The number of bytes of `text` to keep: all of it when it fits, else at most `max_bytes`, backed off to
// a UTF-8 character boundary so a multi-byte character is never cut in half.
static const unsigned kHapticProfileDescMaxBytes = 50;
static const unsigned kHapticProfileTagMaxBytes = 20;
template <typename Str> unsigned haptic_profile_text_keep(const Str& text, unsigned max_bytes) {
    const unsigned len = static_cast<unsigned>(text.length());
    if (len <= max_bytes) return len;
    unsigned n = max_bytes;
    while (n > 0 && (static_cast<unsigned char>(text[n]) & 0xC0) == 0x80) --n;
    return n;
}
// The slot named `name`, or -1 (none, or an empty name).
template <typename Profile, typename Str> int haptic_profile_find(const Profile* profiles, int count, const Str& name) {
    if (name.length() == 0) return -1;
    for (int i = 0; i < count; ++i)
        if (profiles[i].profile_name == name) return i;
    return -1;
}
// The first named slot after `index`, wrapping round (index itself last), or -1 when no slot is named.
template <typename Profile> int haptic_profile_next_named(const Profile* profiles, int count, int index) {
    for (int k = 1; k <= count; ++k) {
        const int i = ((index < 0 ? -1 : index) + k) % count;
        if (profiles[i].profile_name.length() != 0) return i;
    }
    return -1;
}

// FW-BUG-038: the profile a stored file belongs to. toSPIFFS() kept a file when its name merely ENDED with a live
// profile's "<name>.json", so a deleted "Master Volume" (or one renamed away) survived next to a live "Volume" and came
// back on the next boot. A file is a profile's only when its base name (after any path) is exactly "<name>.json".
inline bool haptic_profile_file_is(const char* filename, const char* name) {
    if (filename == nullptr || name == nullptr || name[0] == '\0') return false;
    const char* base = strrchr(filename, '/');
    base = base ? base + 1 : filename;
    const size_t n = strlen(name);
    return strncmp(base, name, n) == 0 && strcmp(base + n, ".json") == 0;
}
// Whether a stored file belongs to one of the named (live) slots.
template <typename Profile> bool haptic_profile_file_kept(const Profile* profiles, int count, const char* filename) {
    for (int i = 0; i < count; ++i)
        if (profiles[i].profile_name.length() != 0 && haptic_profile_file_is(filename, profiles[i].profile_name.c_str()))
            return true;
    return false;
}
