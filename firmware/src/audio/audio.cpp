
// The knob's click player (1.0.0-cc5.7, plan F3; HAPTICS.md "Sound"). See audio.h and cc_sound.h.
//
// Removed in 1.0.0-cc5.7, before sound was enabled (plan F3 "turn on AUDIO_EN only after removing the old
// triggers"): the boot chime (hmi_thread.cpp), the native key clack (hmi_thread.cpp), the per-detent `hard` sample
// fired from the FOC task (this file's old UserHapticEventCallback), the Serial.println("x") of a busy player, the
// XT_I2S_Audio path and the WAV sample arrays (WavData22m / 22s / 44s). Profiles keep their audio fields by name.

#include "audio.h"
#include "nanofoc_d.h"
#include <driver/i2s.h>
#include <esp_heap_caps.h>

BinarisAudioPlayer audioPlayer;   // global instance

namespace {
CCSoundBank bank;
CCSoundRing ring;         // FOC -> HMI
CCSoundVoice voice;       // HMI only
int16_t mono[CC_SOUND_DMA_FRAMES];
}

// Name tokens (audio_api.h): one byte each, compared by address only.
extern const uint8_t soft_wav[1] = {0};
extern const uint8_t hard_wav[1] = {0};
extern const uint8_t loud_wav[1] = {0};
extern const uint8_t clack_wav[1] = {0};
extern const uint8_t chime_wav[1] = {0};

const uint8_t* get_audio_file(String fName) {
    if (fName == "loud") return loud_wav;
    if (fName == "soft") return soft_wav;
    if (fName == "hard") return hard_wav;
    if (fName == "clack") return clack_wav;
    if (fName == "chime") return chime_wav;
    return nullptr;
}

String get_audio_filename(const uint8_t* audio_file) {
    if (audio_file == loud_wav) return "loud";
    if (audio_file == soft_wav) return "soft";
    if (audio_file == hard_wav) return "hard";
    if (audio_file == clack_wav) return "clack";
    if (audio_file == chime_wav) return "chime";
    return "none";
}

BinarisAudioPlayer::BinarisAudioPlayer() {
    audio_config.audio_feedback_lvl = 100;
    audio_config.audio_file = hard_wav;
    audio_config.key_audio_file = clack_wav;
}

// setup() (HmiThread::init), before the threads start: the bank into RAM (PSRAM when there is some, 4.4 KB), then
// I2S0 at 22.05 kHz, 16-bit, stereo frames, 6 x 64-frame DMA buffers that the driver zeroes when it runs out.
void BinarisAudioPlayer::audio_init() {
#ifdef AUDIO_EN
    int16_t* mem = static_cast<int16_t*>(heap_caps_malloc(CC_SOUND_BANK_SAMPLES * sizeof(int16_t), MALLOC_CAP_SPIRAM));
    if (!mem) mem = static_cast<int16_t*>(heap_caps_malloc(CC_SOUND_BANK_SAMPLES * sizeof(int16_t), MALLOC_CAP_8BIT));
    if (!mem) return;                                        // no sound; everything else runs
    bank.render(mem);

    i2s_driver_config_t cfg = {};
    cfg.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX);
    cfg.sample_rate = CC_SOUND_RATE;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;        // the same sample written into both slots
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = CC_SOUND_DMA_BUFFERS;
    cfg.dma_buf_len = CC_SOUND_DMA_FRAMES;
    cfg.use_apll = false;
    cfg.tx_desc_auto_clear = true;                           // zeros, never a stale buffer, when it runs dry
    cfg.fixed_mclk = -1;
    i2s_pin_config_t pins = {};
    pins.mck_io_num = I2S_PIN_NO_CHANGE;
    pins.bck_io_num = PIN_I2S_BCLK;
    pins.ws_io_num = PIN_I2S_LRC;
    pins.data_out_num = PIN_I2S_DOUT;
    pins.data_in_num = I2S_PIN_NO_CHANGE;
    if (i2s_driver_install(I2S_NUM_0, &cfg, 0, nullptr) != ESP_OK) return;
    if (i2s_set_pin(I2S_NUM_0, &pins) != ESP_OK) { i2s_driver_uninstall(I2S_NUM_0); return; }
    ready_ = true;
#endif
}

void BinarisAudioPlayer::put_audio_config(audioConfig& config) { audio_config = config; }

bool BinarisAudioPlayer::playing() const { return ready_ && (voice.active() || pending_ || !ring.empty()); }

CCSoundCounters BinarisAudioPlayer::counters() const {
    CCSoundCounters c;
    c.played = voice.played();
    c.underruns = underruns_;
    c.dropped = ring.dropped();
    c.superseded = ring.superseded();
    c.ready = ready_;
    return c;
}

// HMI task, every pass: when the voice may retrigger, take the request to play (CCSoundRing::popNext: the loudest,
// newest among equals), then keep the DMA fed while a sound plays. Writes never wait (timeout 0): what the DMA cannot take now stays in stereo_ for the next pass. Idle, the
// player writes nothing (the driver sends zeros), so a new click starts within one DMA buffer (2.9 ms).
void BinarisAudioPlayer::audio_loop() {
#ifdef AUDIO_EN
    if (!ready_) return;
    // Playing since an earlier pass: its frames were already in the DMA, so finding the whole writable DMA free
    // now (CC_SOUND_DMA_WRITABLE, 5 of the 6 buffers) means it ran dry (cc_sound_underrun). A sound that starts
    // from silence finds it free by design.
    const bool playingBefore = voice.active() || pending_;
    if (voice.canRetrigger()) {
        CCSoundRequest request;
        if (ring.popNext(request)) {
            voice.start(request, bank);
            pending_ = false;                                // a cut drops the old sound's queued frames
        }
    }
    uint32_t accepted = 0;
    while (voice.active() || pending_) {
        if (!pending_) {
            voice.render(mono, CC_SOUND_DMA_FRAMES);
            for (uint32_t i = 0; i < CC_SOUND_DMA_FRAMES; ++i) stereo_[2 * i] = stereo_[2 * i + 1] = mono[i];
            pendingFrames_ = CC_SOUND_DMA_FRAMES;
            pendingOffset_ = 0;
            pending_ = true;
        }
        size_t written = 0;
        i2s_write(I2S_NUM_0, reinterpret_cast<const uint8_t*>(stereo_) + pendingOffset_ * 4u, pendingFrames_ * 4u,
                  &written, 0);
        const uint32_t frames = static_cast<uint32_t>(written / 4u);
        accepted += frames;
        pendingFrames_ -= frames;
        pendingOffset_ += frames;
        if (pendingFrames_ == 0) pending_ = false;
        if (frames == 0) break;                              // the DMA is full: next pass
    }
    if (cc_sound_underrun(playingBefore, accepted)) ++underruns_;
#endif
}

// FOC task.
void cc_sound_post(const CCSoundCue& cue, uint8_t master) {
    const uint8_t gain = cc_sound_gain(cue, master);
    if (!gain) return;
    CCSoundRequest request;
    request.sound = cue.sound; request.gain = gain;
    request.repeats = cue.repeats ? cue.repeats : 1; request.gapMs = cue.gapMs;
    ring.push(request);
}
