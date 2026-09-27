#pragma once
#include <stdint.h>
#include "cc_presentation.h"

// Contract-v4 LED model (PRESENTATION_V4.md section 5): the firmware twin of the
// companion's control_center/preview_lights.py. Every formula is integer-only
// and reproduces the Python model bit-exactly; harness/light_tests.py
// replays Python-generated sequences through this unit and compares every step
// (logical ring, physical ring in all four orientations, buttons). FROZEN: the
// v4 model is what the companion's floating knob draws for presentation-4
// knobs (cc5.3 and older, ALIVE.md 1); 1.0.0-cc5.4 draws its LEDs with the
// alive engine (cc_alive.h) and keeps only the geometry helpers from here.
//
// Platform-neutral (no Arduino/FastLED): compiled unchanged by the firmware, by
// light_tests (MSVC /W4 /WX) and by cpp11_gate.py (gnu++11).
//
// Conventions:
// - A colour is 0xRRGGBB. A cell is (rgb, level); drive = per channel
//   (c * level + 127) / 255, computed BEFORE the global FastLED brightness cap
//   (hmi_thread keeps min(51, led_max_brightness)). Dithering stays at the
//   FastLED default.
// - Ring arrays produced here are LOGICAL: segment 0 is twelve o'clock,
//   increasing clockwise. cc_ring_address()/cc_ring_physical() map them to
//   the wired addresses (reflection + mounting orientation, unchanged from cc4).
// - Buttons are the frame's slots, physical left-to-right (frame.buttons order);
//   the pressed mask uses the same slot bits.
// - Times are uint32 milliseconds; every elapsed time is (uint32_t)(now - start),
//   so millis() wrap is harmless.

constexpr uint8_t CC_RING_LEDS = 60;

enum CCFlashKind : uint8_t { CC_FLASH_NONE, CC_FLASH_OK, CC_FLASH_ERR };

// One ring or button light before drive scaling. Plain aggregate (C++11).
struct CCLedCell {
    uint32_t rgb;
    uint8_t level;
};

// Drive colour of a cell: per channel (c * level + 127) / 255.
uint32_t cc_led_drive(uint32_t rgb, uint8_t level);
// easeOutQuint LUT value 0..255 at elapsed/duration (section 5.7): 1/16 steps,
// linear between CCLed::easeLut entries; 255 once elapsed >= duration.
uint8_t cc_led_ease(uint32_t elapsed, uint32_t duration);
// Per channel from + (to - from) * e / 255 with C truncation toward zero.
uint32_t cc_led_toward(uint32_t from, uint32_t to, uint8_t e);
// Section 5.6 pulses for the time since the condition's onset: pending is L3/L1
// per 260 ms phase starting HIGH and holds L1 from 3000 ms; loading is L2/L1.
uint8_t cc_led_pending_level(uint32_t elapsedMs);
uint8_t cc_led_loading_level(uint32_t elapsedMs);

// Pure ring target (preview_lights.ring_target): fills the 60 logical cells for
// one frame and returns the cursor segment. pendingMs/loadingMs are the times
// since the pending/loading onsets; flash is a CCFlashKind drawn last.
uint8_t cc_ring_target(const CCFrame& frame, uint32_t pendingMs, uint32_t loadingMs,
                       uint8_t flash, CCLedCell (&cells)[CC_RING_LEDS]);

// Section 5.9 tone of button `slot`, FROZEN at contract v4 (= cc5.3's cc_button_tone and
// presentation.button_tone, which preview_lights._tone calls): none (icon ""), dim (!enabled),
// stop (slot 0 cancel), go (slot 3 play/prev/next/switch), else nav. It ignores every
// presentation-5 input (`lit`, `color`, PRESENTATION_V5 5.2's Home paused-Play go row, and the v5
// icon tokens are plain nav), so this model stays bit-identical to PreviewLights for cc5.3 knobs.
// cc_button_tone() (cc_presentation.h) is the v5 table the LCD and the alive engine follow.
uint8_t cc_button_tone_v4(const CCFrame& frame, uint8_t slot);

// Section 5.9 light of button `slot` from cc_button_tone_v4(): none (0, L0),
// dim (W, L1), stop (R, L2), go (G, L3), nav (W, L2).
CCLedCell cc_button_light(const CCFrame& frame, uint8_t slot);

// Stateless button drive colours with the press highlight (no fade); the
// equivalent of preview_lights.button_pixels(). V4 model only (light_tests): on
// 1.0.0-cc5.4 the alive engine draws the buttons from the first claimed frame on,
// including a claim that starts between two HMI passes (hmi_thread updateKeyLeds).
void cc_render_buttons(const CCFrame& frame, uint8_t pressedMask, uint32_t (&out)[4]);

// Wired LED address of logical segment `logical` for a mounting orientation
// 0..3 (only the low two bits are used).
uint8_t cc_ring_address(int logical, uint8_t orientation);
// physical[cc_ring_address(i, orientation)] = logical[i] for every segment.
void cc_ring_physical(const uint32_t (&logical)[CC_RING_LEDS], uint8_t orientation,
                      uint32_t (&physical)[CC_RING_LEDS]);

// Sections 5.6-5.8 state machine (preview_lights.PreviewLights): feedback flash,
// pulse onsets, per-segment damping (instant rise, 260 ms decay) and the 220 ms
// button fade. One instance owns the LEDs while a host frame is active.
//
// reset() is the renderer reset: the next render() snaps every LED to its target
// and seeds lastSeq from that frame's feedback without flashing. hmi_thread calls
// it when a claim starts (unclaimed -> claimed) and on an orientation change.
class CCLightRenderer {
public:
    CCLightRenderer();
    void reset();
    // Renders one pass. `controlId` is accepted for the caller's bookkeeping;
    // by contract nothing here depends on it (flashes trigger on seq alone).
    // ring: 60 LOGICAL drive colours; buttons: 4 slot drive colours (pre-cap).
    void render(const CCFrame& frame, uint32_t controlId, uint32_t nowMs, uint8_t pressedMask,
                uint32_t (&ring)[CC_RING_LEDS], uint32_t (&buttons)[4]);

    uint8_t cursor() const { return cursor_; }
    uint8_t flash() const { return flash_; }    // CCFlashKind of the active flash
    uint32_t lastSeq() const { return lastSeq_; }

private:
    uint8_t feedback(const CCFrame& frame, uint32_t now);
    void onsets(const CCFrame& frame, uint32_t now, uint32_t& pendingMs, uint32_t& loadingMs);
    uint32_t damp(uint8_t i, uint32_t target, uint32_t now);
    void fade(uint8_t i, uint32_t target, uint32_t now);

    CCLedCell cells_[CC_RING_LEDS];            // target scratch: kept off the HMI stack
    uint32_t targets_[4];                      // button target scratch: likewise
    uint32_t shown_[CC_RING_LEDS], from_[CC_RING_LEDS], to_[CC_RING_LEDS], start_[CC_RING_LEDS];
    bool decaying_[CC_RING_LEDS];
    uint32_t buttonShown_[4], buttonFrom_[4], buttonTo_[4], buttonStart_[4];
    bool buttonFading_[4];
    uint32_t lastSeq_, flashStart_, pendingStart_, loadingStart_;
    uint8_t flash_, cursor_;
    bool snap_, seeded_, pendingOn_, loadingOn_;
};
