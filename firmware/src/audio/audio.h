
#pragma once

#include <inttypes.h>
#include <Arduino.h>
#include "./audio_api.h"
#include "./cc_sound.h"

// 1.0.0-cc5.7 (plan F3; HAPTICS.md "Sound"): the knob's click player. MAX98357A on I2S0, DIN 9 / BCLK 10 / LRC 11
// (nanofoc_d.h; confirmed on Karl Malota's board, no shutdown pin), 22.05 kHz, 16-bit, the same sample in both slots.
// The clicks (cc_sound.h) are rendered into RAM once by audio_init(); the FOC task posts a request with every
// haptic that has a sound (cc_sound_post), the HMI task plays it (audio_loop, non-blocking writes). Silent unless
// the host's claim asked for sounds (control `sound` 1..3); nothing plays at boot, on a key or on a native detent.
struct CCSoundCounters {
    uint32_t played;      // sounds started
    uint32_t underruns;   // the DMA ran dry mid-sound (cc_sound_underrun)
    uint32_t dropped;     // requests the ring could not take
    uint32_t superseded;  // waiting requests a louder (or newer, equal) one outranked (CCSoundRing::popNext)
    bool ready;           // bank rendered and I2S installed
};

class BinarisAudioPlayer {
public:
    BinarisAudioPlayer();
    void audio_init();
    // Kept for the profile code (dispatchAudioConfig): stored, never played.
    void put_audio_config(audioConfig& config);
    void audio_loop();           // HMI task, every pass
    bool playing() const;        // a sound is playing or waiting (the HMI shortens its wait meanwhile)
    CCSoundCounters counters() const;
    audioConfig audio_config;

private:
    bool ready_ = false;
    bool pending_ = false;             // `stereo_` holds frames the DMA has not taken yet
    uint32_t pendingFrames_ = 0, pendingOffset_ = 0;
    int16_t stereo_[CC_SOUND_DMA_FRAMES * 2];
    uint32_t underruns_ = 0;
};

extern BinarisAudioPlayer audioPlayer;

// FOC task: a haptic with a sound started. `master` is the claim's sound level (0 off .. 3 High).
void cc_sound_post(const CCSoundCue& cue, uint8_t master);
