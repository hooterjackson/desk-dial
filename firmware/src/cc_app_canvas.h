#pragma once
// App canvas (A2, 1.0.0-cc5.6; CONTROL_CENTER.md "App canvas"): the timing and animation state of the app UI
// drawn by cc_app_ui.h. Platform-neutral and pure (no LVGL, no RTOS): the LCD thread (lcd_thread.cpp) feeds
// it the frame's `app` state, the knob's own shaft angle and physical buttons and a millisecond clock, and
// pushes the buffer whenever step() drew a new frame. The host harness (harness/app_canvas_tests.py)
// drives the same class with scripted inputs.
//
// Behaviour and timings follow Karl Malota's display_task.cpp (katbinaris/NanoD_RatchetH1
// feat/firmware-esp-idf-quadra, adapted with permission): the cube follows the knob's continuous travel
// (orbit one-for-one, zoom one doubling per quarter turn, pan ~60 px per radian), shows only stepped poses
// (32 per turn, zoom in 1/8 doublings, pan in 2 px), eases to the nearest 45 + k*90 deg pose over 220 ms when
// orbit ends (Desk Dial 7.2.2.0's tilt, slot `tilt`: the view's pitch follows the knob one-for-one in the same
// 32-per-turn steps about the 30 deg rest, and eases back to that rest over 220 ms when tilt ends); a tap flash lasts 260 ms, a wheel slide 120 ms, an echo 1100 ms, the parameter end-stop nudge
// 90 ms; the idle plasma starts after 5 s without input on the main app screen.
//
// App profiles (plan section 1e, APP_PROFILES.md): the canvas draws any profile of the store (cc_app_store.h). It
// acquires the frame's profile (app.id + app.crc) for each pass and releases it before returning, so no profile
// pointer outlives a pass; a profile not (yet) loaded draws the neutral Loading screen. A data profile
// (has_slots) takes the live slot's label, key and micro-interaction (fx) from its slots; the built-in Onshape
// keeps its legacy slot model and draws as before.

#include <stdint.h>
#include <string.h>
#include "cc_app_ui.h"
#include "cc_presentation.h"

// The frame's app id as text: CCAppState::id is the id string with app profiles (FW-A), the cc5.6 index before.
inline const char* cc_app_id_text(const char* id) { return id; }
inline const char* cc_app_id_text(uint8_t id) { return id == CC_APP_ID_ONSHAPE ? "onshape" : nullptr; }
// The frame's app.crc (0 = the built-in profile; a CCAppState without the field has only the built-in).
template <typename S> auto cc_app_crc_of(const S& s, int) -> decltype(static_cast<uint32_t>(s.crc)) {
    return static_cast<uint32_t>(s.crc);
}
template <typename S> uint32_t cc_app_crc_of(const S&, long) { return 0; }
inline uint32_t cc_app_state_crc(const CCAppState& s) { return cc_app_crc_of(s, 0); }
// The frame has an `app` object (the app canvas is up).
inline bool cc_app_state_present(const CCAppState& s) {
    const char* id = cc_app_id_text(s.id);
    return id != nullptr && id[0] != '\0';
}

#ifndef CC_APP_KNOB_SIGN
#define CC_APP_KNOB_SIGN 1          // flip if the cube turns against the knob
#endif

constexpr uint32_t kCCAppSettleMs = 220;
constexpr uint32_t kCCAppFlashMs = 260;
constexpr uint32_t kCCAppActiveMs = 120;     // keep frames coming this long after the knob last moved
constexpr int32_t kCCAppDeadband = 20;       // 0.002 rad: sensor noise, not a move
constexpr int32_t kCCAppJump = 20000;        // 2 rad between two passes: a re-anchor, not a turn
constexpr uint32_t kCCAppWheelSlideMs = 120;
constexpr uint32_t kCCAppEchoMs = 1100;
constexpr uint32_t kCCAppNudgeMs = 90;
constexpr uint32_t kCCAppCancelMs = 600;     // parameter mode: button 3 held this long, release = cancel
constexpr uint32_t kCCAppIdleMs = 5000;      // Karl's attract delay
constexpr uint32_t kCCAppLoopMs = 33;        // looping animations (cards, plasma): ~30 fps as Karl's

// What the canvas shows (tests, diag).
enum CCAppView : uint8_t { CC_APP_VIEW_MAIN = 0, CC_APP_VIEW_WHEEL, CC_APP_VIEW_PARAM, CC_APP_VIEW_ECHO, CC_APP_VIEW_IDLE,
                           CC_APP_VIEW_LOADING };   // the frame's profile is not in the store (yet)

struct CCAppInputs {
    uint32_t nowMs = 0;
    int32_t angle = 0;          // the knob's total shaft angle, 1e-4 rad (cc_app_angle_read())
    uint8_t buttons = 0;        // bit n = physical button n (left to right) held
};

class CCAppCanvas {
public:
    // `frame`: a W x H RGB565 buffer; `tables`: the plasma's tables (either may be null: nothing is drawn).
    void begin(uint16_t* frame, ccui::PlasmaTables* tables, uint32_t minFrameMs);
    // The app screen appears (the frame's app.id went non-zero): fresh animation state; the sequence
    // counters of `state` count as seen (nothing stale replays).
    void enter(const CCAppState& state, const CCAppInputs& in);
    // A new frame's app state (call whenever the frame version moved; unchanged content is ignored).
    void update(const CCAppState& state, uint32_t nowMs);
    // Every pass. True when a new frame was drawn into the buffer (the caller pushes it).
    bool step(const CCAppInputs& in);
    CCAppView view() const { return view_; }
    bool active() const { return active_; }
    void leave() { active_ = false; }

private:
    bool due(uint32_t now, bool fast) const;
    void draw(const CCAppInputs& in, const cc_app_profile_t* p);
    void track_angle(const CCAppInputs& in, uint8_t motion);

    uint16_t* frame_ = nullptr;
    ccui::PlasmaTables* tables_ = nullptr;
    uint32_t minFrameMs_ = 16;
    bool active_ = false;
    bool dirty_ = true;
    bool drawnOnce_ = false;
    uint32_t lastDrawMs_ = 0;
    CCAppView view_ = CC_APP_VIEW_MAIN;
    CCAppState state_;
    uint8_t buttons_ = 0;
    // cube
    float yaw_ = 0.785398163f, zoom_ = 0, pan_ = 0, pitch_ = ccui::SHAPE_REST_PITCH;
    int32_t lastAngle_ = 0;
    bool haveAngle_ = false;
    uint8_t lastSlot_ = CC_APP_SLOT_ZOOM;
    bool settling_ = false;
    float settleFrom_ = 0, settleTo_ = 0;
    uint32_t settleStartMs_ = 0;
    bool pitchSettling_ = false;
    float pitchFrom_ = 0;          // the pitch's offset from its rest when tilt ended
    uint32_t pitchSettleMs_ = 0;
    uint32_t movedMs_ = 0;
    bool moved_ = false;
    int32_t drawnYawStep_ = 0, drawnZoomStep_ = 0, drawnPanStep_ = 0, drawnPitchStep_ = 0;
    float drawnYaw_ = 0, drawnZoom_ = 0, drawnPan_ = 0, drawnPitch_ = 0;   // a profile without stepped poses
    // flash / echo / nudge
    uint32_t flashSeen_ = 0, flashStartMs_ = 0;
    bool flashActive_ = false, flashOn_ = false;
    uint32_t echoSeen_ = 0, echoStartMs_ = 0;
    bool echoOn_ = false;
    uint32_t bumpSeen_ = 0, bumpAtMs_ = 0;
    bool nudgeOn_ = false;
    // wheel
    bool wheelWas_ = false;
    uint8_t wheelRing_ = 0, wheelIndex_ = 0;
    uint32_t wheelEntryMs_ = 0, wheelSlideMs_ = 0;
    bool wheelSlideActive_ = false;
    int wheelSlideDir_ = 1;
    uint8_t wheelPrevRing_ = 0, wheelPrevIndex_ = 0;   // the entry sliding out (its card is looked up per draw)
    bool wheelPrevValid_ = false;
    bool sliding_ = false;
    // parameter mode: button 3 held since (local)
    bool f3Down_ = false;
    uint32_t f3SinceMs_ = 0;
    // idle
    uint32_t activityMs_ = 0;
    uint32_t idleStartMs_ = 0;
};
