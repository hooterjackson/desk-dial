// r4 SOUND (1.0.0-cc5.7, plan stage F3; HAPTICS.md "Sound"): the knob's click sounds, header-only and platform-
// neutral (harness/haptic_fx_tests.py runs it with MSVC; cpp11_gate.py checks it in gnu++11).
//
// Synthesis adapted, with his permission, from Karl Malota's NanoD_RatchetH1 feat/firmware-esp-idf-quadra
// NanoDepsidf/src/i2s_task.c (itself modelled on his Lucu-Kind haptics): the WOOD_TOCK timbre (a downward chirp
// from 1.6 x 2400 Hz with a fast exponential decay, 5 ms), TICK_THUD (an 1800 Hz tick over a 100 Hz body, 50 ms),
// the FINE click (WOOD_TOCK at 2 x pitch) and the button THUMP (110 Hz, 40 ms). Differences: 22.05 kHz mono, and
// every sound is rendered ONCE into RAM at start-up (CCSoundBank; no WAV in flash), then mixed by a single voice
// with a per-request gain (the r4 section 6 level times the host's master level) and a repeat count.
//
// The voice: a new request cuts the current sound and restarts (after the current one has played at least
// CC_SOUND_RETRIGGER_SAMPLES, Karl's 4 ms MIN_CLICK_RETRIGGER, so a fast spin still plays distinct clicks); when
// several requests wait, the ring hands over the loudest (newest among equals) and counts the others as superseded,
// so a press thump is never lost to a tock that followed it in the same HMI pass. Producers: the FOC task only (every sound follows its
// haptic, so the FOC task posts it when the pulse or detent starts); consumer: the HMI task (audio.cpp).
#pragma once

#include <math.h>
#include <stdint.h>
#include <string.h>

#include "../cc_haptic_fx.h"

constexpr uint32_t CC_SOUND_RATE = 22050;
constexpr uint16_t CC_SOUND_WOOD_LEN = 110;     // 5 ms
constexpr uint16_t CC_SOUND_FINE_LEN = 110;     // 5 ms
constexpr uint16_t CC_SOUND_THUD_LEN = 1103;    // 50 ms
constexpr uint16_t CC_SOUND_THUMP_LEN = 882;    // 40 ms
constexpr uint32_t CC_SOUND_BANK_SAMPLES =
    static_cast<uint32_t>(CC_SOUND_WOOD_LEN) + CC_SOUND_FINE_LEN + CC_SOUND_THUD_LEN + CC_SOUND_THUMP_LEN;
constexpr uint16_t CC_SOUND_RETRIGGER_SAMPLES = 88;   // 4 ms
constexpr float CC_SOUND_CLIP = 32000.0f;

// The master volume: a percent 0..100 of full scale for the loudest sound (the thump). A host sends it as control
// `soundVolume` (capability knobVolume 1, added 2026-09-30), or the older `sound` level (capability knobSound 1: 0 off,
// 1 Low, 2 Medium, 3 High), which maps through CC_SOUND_MASTER_PCT. The FOC task keeps only the percent.
constexpr uint8_t CC_SOUND_MASTER_MAX = static_cast<uint8_t>(CC_SOUND_MASTER_LEVEL_MAX);
constexpr uint8_t CC_SOUND_MASTER_PCT[4] = {0, 40, 70, 100};
inline uint8_t cc_sound_volume_of_level(uint32_t level) {
    return level <= CC_SOUND_MASTER_MAX ? CC_SOUND_MASTER_PCT[level] : 0;
}
// The nearest `sound` level of a volume (diag soundLevel): 0 silent, else the lowest level at or above it.
inline uint8_t cc_sound_level_of_volume(uint8_t volume) {
    for (uint8_t level = 0; level <= CC_SOUND_MASTER_MAX; ++level)
        if (volume <= CC_SOUND_MASTER_PCT[level]) return level;
    return CC_SOUND_MASTER_MAX;
}
// The gain (0..100 %) of a cue at master volume `volume` (percent): the cue's level x the volume.
inline uint8_t cc_sound_gain(const CCSoundCue& cue, uint8_t volume) {
    if (cue.sound == CC_SOUND_NONE || cue.sound >= CC_SOUND_COUNT || volume == 0) return 0;
    const uint32_t v = volume > CC_SOUND_VOLUME_MAX ? CC_SOUND_VOLUME_MAX : volume;
    return static_cast<uint8_t>((static_cast<uint32_t>(cue.level) * v + 50u) / 100u);
}

// The click bank: every sound rendered once at full scale into caller memory (CC_SOUND_BANK_SAMPLES int16s;
// audio.cpp puts it in PSRAM when there is some).
class CCSoundBank {
public:
    CCSoundBank() : mem_(nullptr) {}
    void render(int16_t* mem) {
        mem_ = mem;
        if (!mem_) return;
        int16_t* wood = mem_;
        int16_t* fine = wood + CC_SOUND_WOOD_LEN;
        int16_t* thud = fine + CC_SOUND_FINE_LEN;
        int16_t* thump = thud + CC_SOUND_THUD_LEN;
        renderTock(wood, CC_SOUND_WOOD_LEN, 1.0f);
        renderTock(fine, CC_SOUND_FINE_LEN, 2.0f);
        renderThud(thud, CC_SOUND_THUD_LEN);
        renderThump(thump, CC_SOUND_THUMP_LEN);
    }
    const int16_t* data(uint8_t sound, uint16_t& length) const {
        length = 0;
        if (!mem_) return nullptr;
        switch (sound) {
            case CC_SOUND_WOOD: length = CC_SOUND_WOOD_LEN; return mem_;
            case CC_SOUND_FINE: length = CC_SOUND_FINE_LEN; return mem_ + CC_SOUND_WOOD_LEN;
            case CC_SOUND_THUD: length = CC_SOUND_THUD_LEN; return mem_ + CC_SOUND_WOOD_LEN + CC_SOUND_FINE_LEN;
            case CC_SOUND_THUMP:
                length = CC_SOUND_THUMP_LEN;
                return mem_ + CC_SOUND_WOOD_LEN + CC_SOUND_FINE_LEN + CC_SOUND_THUD_LEN;
            default: return nullptr;
        }
    }

private:
    static int16_t clip(float s) {
        return static_cast<int16_t>(s > CC_SOUND_CLIP ? CC_SOUND_CLIP : (s < -CC_SOUND_CLIP ? -CC_SOUND_CLIP : s));
    }
    // WOOD_TOCK (Karl: 2400 Hz base, chirp 1.6 -> 1.0 over 1/400 s, decay 1080/s, amplitude 32000).
    static void renderTock(int16_t* out, uint16_t n, float pitch) {
        const float dt = 1.0f / static_cast<float>(CC_SOUND_RATE), twoPi = 2.0f * CC_HAPTIC_PI;
        float phase = 0.0f;
        for (uint16_t i = 0; i < n; ++i) {
            const float t = static_cast<float>(i) * dt;
            const float glide = t * 400.0f > 1.0f ? 1.0f : t * 400.0f;
            const float f = 2400.0f * pitch * (1.6f - 0.6f * glide);
            phase += twoPi * f * dt;
            if (phase > twoPi) phase -= twoPi;
            out[i] = clip(sinf(phase) * expf(-1080.0f * t) * 32000.0f);
        }
    }
    // TICK_THUD (Karl: 1800 Hz tick, decay 900/s, x0.5 + a body, decay 150/s, x1.0, amplitude 32000, clipped).
    // 2026-09-30 by ear on the knob: the knob's small speaker does not reproduce Karl's 100 Hz body (only the tick
    // came through), so the body is 330 Hz, the lowest it plays with some weight.
    static void renderThud(int16_t* out, uint16_t n) {
        const float dt = 1.0f / static_cast<float>(CC_SOUND_RATE), twoPi = 2.0f * CC_HAPTIC_PI;
        for (uint16_t i = 0; i < n; ++i) {
            const float t = static_cast<float>(i) * dt;
            const float s = sinf(twoPi * 1800.0f * t) * expf(-900.0f * t) * 0.5f + sinf(twoPi * 330.0f * t) * expf(-150.0f * t);
            out[i] = clip(s * 32000.0f);
        }
    }
    // BUTTON_THUMP, small-speaker version (2026-09-30: Karl's pure 110 Hz tone, decay 140/s, was silent on the
    // knob's speaker even at High). The 110 Hz fundamental is left out and implied by its harmonics 2..6 (220..660
    // Hz, weights 1/(n-1)), so the ear still hears a low thump, over a 1.2 kHz attack of 4 ms; decay 140/s as
    // before, normalised to a 30000 peak.
    static float thumpAt(float t) {
        const float twoPi = 2.0f * CC_HAPTIC_PI;
        float s = 0.0f;
        for (int h = 2; h <= 6; ++h) s += sinf(twoPi * 110.0f * static_cast<float>(h) * t) / static_cast<float>(h - 1);
        s *= expf(-140.0f * t);
        s += sinf(twoPi * 1200.0f * t) * expf(-250.0f * t) * 0.6f;
        return s;
    }
    static void renderThump(int16_t* out, uint16_t n) {
        const float dt = 1.0f / static_cast<float>(CC_SOUND_RATE);
        float peak = 0.0f;
        for (uint16_t i = 0; i < n; ++i) {
            const float a = fabsf(thumpAt(static_cast<float>(i) * dt));
            if (a > peak) peak = a;
        }
        const float scale = peak > 0.0f ? 30000.0f / peak : 0.0f;
        for (uint16_t i = 0; i < n; ++i) out[i] = clip(thumpAt(static_cast<float>(i) * dt) * scale);
    }
    int16_t* mem_;
};

// One request: the sound, its final gain (0..100 %, cc_sound_gain()), plays and the start-to-start gap.
struct CCSoundRequest {
    uint8_t sound;
    uint8_t gain;
    uint8_t repeats;
    uint8_t gapMs;
};

// Single-producer (FOC) / single-consumer (HMI) ring of requests. Lock-free: the producer writes the slot then
// moves head; the consumer reads up to head then moves tail. A full ring drops the new request (counted).
constexpr uint8_t CC_SOUND_RING = 16;
class CCSoundRing {
public:
    CCSoundRing() : head_(0), tail_(0), dropped_(0), superseded_(0) { memset(slots_, 0, sizeof(slots_)); }
    bool push(const CCSoundRequest& r) {
        const uint32_t head = head_;
        if (static_cast<uint32_t>(head - tail_) >= CC_SOUND_RING) { dropped_ = dropped_ + 1u; return false; }
        slots_[head % CC_SOUND_RING] = r;
        head_ = head + 1u;
        return true;
    }
    // Takes every waiting request and returns the one to play: the highest gain (the gain is the cue's level x the
    // master, so a press thump outranks a tock and a wall thud), the newest among equal gains (a spin keeps playing
    // its latest tock). The others are stale by the time the voice is free; they are counted (superseded()).
    // FW-BUG-021: the newest alone used to win, so a thump followed by a tock in one HMI wait was never heard.
    bool popNext(CCSoundRequest& out) {
        const uint32_t head = head_;
        const uint32_t tail = tail_;
        if (head == tail) return false;
        uint32_t best = tail;
        for (uint32_t i = tail + 1u; i != head; ++i)
            if (slots_[i % CC_SOUND_RING].gain >= slots_[best % CC_SOUND_RING].gain) best = i;
        out = slots_[best % CC_SOUND_RING];
        superseded_ = superseded_ + (head - tail - 1u);
        tail_ = head;
        return true;
    }
    bool empty() const { return head_ == tail_; }
    uint32_t dropped() const { return dropped_; }
    uint32_t superseded() const { return superseded_; }   // waiting requests another one outranked (HMI side)

private:
    volatile uint32_t head_, tail_, dropped_, superseded_;
    CCSoundRequest slots_[CC_SOUND_RING];
};

// The voice (HMI task).
class CCSoundVoice {
public:
    CCSoundVoice() : data_(nullptr), len_(0), pos_(0), gainQ15_(0), repeatsLeft_(0), gapSamples_(0), sinceStart_(0),
                     played_(0) {}
    // Cuts whatever plays and starts `r` (a silent or unknown request only stops the voice).
    void start(const CCSoundRequest& r, const CCSoundBank& bank) {
        uint16_t len = 0;
        const int16_t* data = bank.data(r.sound, len);
        if (!data || !len || !r.gain || !r.repeats) { stop(); return; }
        data_ = data; len_ = len; pos_ = 0; sinceStart_ = 0;
        gainQ15_ = static_cast<int32_t>((static_cast<uint32_t>(r.gain > 100 ? 100 : r.gain) * 32768u) / 100u);
        repeatsLeft_ = static_cast<uint8_t>(r.repeats - 1u);
        gapSamples_ = static_cast<uint32_t>(r.gapMs) * CC_SOUND_RATE / 1000u;
        ++played_;
    }
    void stop() { data_ = nullptr; len_ = 0; pos_ = 0; repeatsLeft_ = 0; }
    bool active() const { return data_ != nullptr; }
    // A new request may cut the current sound now (Karl's 4 ms minimum).
    bool canRetrigger() const { return !active() || sinceStart_ >= CC_SOUND_RETRIGGER_SAMPLES; }
    // Renders `frames` mono samples (zeros where silent). Returns true while anything was audible.
    bool render(int16_t* out, uint32_t frames) {
        bool audible = false;
        for (uint32_t i = 0; i < frames; ++i) {
            int16_t s = 0;
            if (data_) {
                if (pos_ < len_) {
                    s = static_cast<int16_t>((static_cast<int32_t>(data_[pos_]) * gainQ15_) >> 15);
                    ++pos_;
                    audible = true;
                }
                ++sinceStart_;
                if (pos_ >= len_) {
                    if (repeatsLeft_ == 0) stop();
                    else if (sinceStart_ >= gapSamples_) { pos_ = 0; sinceStart_ = 0; --repeatsLeft_; }
                }
            }
            out[i] = s;
        }
        return audible;
    }
    uint32_t played() const { return played_; }

private:
    const int16_t* data_;
    uint16_t len_, pos_;
    int32_t gainQ15_;
    uint8_t repeatsLeft_;
    uint32_t gapSamples_, sinceStart_;
    uint32_t played_;
};

// The I2S DMA (plan F3: 6 x 64 frames at 22.05 kHz, 17.4 ms) and the writer's underrun rule: a non-blocking write
// that finds the whole writable DMA free while a sound was already playing means the DMA ran dry mid-sound (the
// driver's auto-clear filled the gap with zeros): one underrun.
// FW-BUG-018: the IDF 4.4 driver's free-buffer queue holds dma_buf_count - 1 buffers (one is always the one the DMA
// is sending), so a write after the DMA ran dry takes at most 5 x 64 = 320 frames (14.5 ms), never the 384 of the
// whole ring; the rule counts against that writable depth.
constexpr uint32_t CC_SOUND_DMA_BUFFERS = 6;
constexpr uint32_t CC_SOUND_DMA_FRAMES = 64;
constexpr uint32_t CC_SOUND_DMA_CAPACITY = CC_SOUND_DMA_BUFFERS * CC_SOUND_DMA_FRAMES;
constexpr uint32_t CC_SOUND_DMA_WRITABLE = (CC_SOUND_DMA_BUFFERS - 1u) * CC_SOUND_DMA_FRAMES;
inline bool cc_sound_underrun(bool playingBefore, uint32_t acceptedFrames) {
    return playingBefore && acceptedFrames >= CC_SOUND_DMA_WRITABLE;
}
