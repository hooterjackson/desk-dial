
#pragma once

#include <inttypes.h>
#include <Arduino.h>

typedef struct {


    uint8_t audio_feedback_lvl;

    /*
        Audio File (UI: Audio Magnitude) set pre-uploaded audio file which can be stored as PROGMEM or in SPIFS
        Audio files are very small, in most of cases way under 500ms, stored as mono 16bit 24Khz samples, 
        Audio Files: 'faint' [0], 'soft' [1], 'default' [2], 'medium' [3], 'hard' [4],
        Note: It is not intended or for user to be able to upload or tune these pre-defined sound files. 
        Some documentation on sound design will be provided in User Documentation, 
        this however could be modified only by advanced users who want to play with source.

        TODO: In future to consider generative sound approach with virtual oscillator (sine, sqare, saw)?

    */

    /* 
        Toggles between USB (slave) or MIDI (standalone) operation, 
        In UI -> Profile Settings -> Connection Type
        If is_midi = 1, midi_thread is enabled and listens for 
        buttons or knob state update that contains CC message, else midi_thread is disabled

    */
   const uint8_t* audio_file; // valid values are 'loud', 'soft', 'none', 'hard', 'clack'

   const uint8_t* key_audio_file; // valid values are 'loud', 'soft', 'none', 'hard', 'clack'

} audioConfig;


// 1.0.0-cc5.4 (PRESENTATION_V5 12.4 F1): the sample arrays are const, so they link into flash
// .rodata instead of internal .data (53,964 B of internal RAM). They are read only in task
// context: check_file() at init, start_play() and audio_loop()'s i2s_write(), which copies them
// into the I2S driver's own DMA buffers (internal RAM); no DMA descriptor and no ISR ever points
// at them. Profiles keep the sound by name (get_audio_file / get_audio_filename).
extern const uint8_t soft_wav[];
extern const uint8_t hard_wav[];
extern const uint8_t loud_wav[];
extern const uint8_t clack_wav[];
extern const uint8_t chime_wav[];

const uint8_t* get_audio_file(String fName);
String get_audio_filename(const uint8_t* audio_file);