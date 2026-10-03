
#pragma once

#include <inttypes.h>
#include <Arduino.h>

// The profile's audio fields (JSON "audio": clickType, keyClickType, clickLevel). Kept so a stored profile loads
// and saves byte-identically; since 1.0.0-cc5.7 (plan F3) the knob never plays them: the old per-detent sample,
// key clack and boot chime are gone and the WAV data with them (about 54 KB of flash). Every sound the knob makes
// now is an r4 click, synthesized into RAM at start-up and asked for by the host (audio.h, cc_sound.h).
typedef struct {
    uint8_t audio_feedback_lvl;
    const uint8_t* audio_file;      // a name token (get_audio_file); 'loud', 'soft', 'hard', 'clack', 'chime' or none
    const uint8_t* key_audio_file;
} audioConfig;

// Name tokens only (one byte each): the profile code compares and names them, nothing reads them as audio.
extern const uint8_t soft_wav[];
extern const uint8_t hard_wav[];
extern const uint8_t loud_wav[];
extern const uint8_t clack_wav[];
extern const uint8_t chime_wav[];

const uint8_t* get_audio_file(String fName);
String get_audio_filename(const uint8_t* audio_file);
