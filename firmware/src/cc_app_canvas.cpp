// App canvas timing and animation state (cc_app_canvas.h).
// Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
// NanoDepsidf/src/display_task.cpp (shape_tick, app_view, wheel_tick / wheel_view, param_view, the attract
// idle timer and the pacing rules, app_view's slot -> label / key / fx mapping, turn_slot and shape_stepped).
// Here the wheel, parameter and echo state come from the host's frame (Desk Dial drives the input), while the
// shape, the buttons and the button-3 hold bar are local.
#include "cc_app_canvas.h"
#include <math.h>
#include <string.h>

// FW-A's profile store (cc_app_store.h): acquire(id, crc) -> the profile, NULL = not loaded; release() after use.
#if defined(__has_include)
#if __has_include("cc_app_store.h")
#include "cc_app_store.h"
#define CC_APP_CANVAS_STORE_HEADER 1
#endif
#endif
#ifndef CC_APP_CANVAS_STORE_HEADER
extern "C" {
const cc_app_profile_t* cc_app_store_acquire(const char* id, uint32_t crc);
void cc_app_store_release(const cc_app_profile_t* p);
}
#endif

namespace {
const float kPi = 3.14159265358979f;

inline bool before(uint32_t a, uint32_t b) { return static_cast<int32_t>(a - b) < 0; }

bool same_id(const CCAppState& a, const CCAppState& b) {
    const char *x = cc_app_id_text(a.id), *y = cc_app_id_text(b.id);
    return (x == nullptr || y == nullptr) ? x == y : strcmp(x, y) == 0;
}

// The frame's profile for one pass: acquired here, released when the pass ends (never kept across passes).
class Lease {
public:
    explicit Lease(const CCAppState& s) {
        const char* id = cc_app_id_text(s.id);
        p_ = id != nullptr && id[0] != '\0' ? cc_app_store_acquire(id, cc_app_state_crc(s)) : nullptr;
    }
    ~Lease() {
        if (p_ != nullptr) cc_app_store_release(p_);
    }
    const cc_app_profile_t* get() const { return p_; }

private:
    Lease(const Lease&);
    Lease& operator=(const Lease&);
    const cc_app_profile_t* p_;
};

bool same_state(const CCAppState& a, const CCAppState& b) {
    return same_id(a, b) && cc_app_state_crc(a) == cc_app_state_crc(b) && a.slot == b.slot &&
           a.refused == b.refused && a.refusedFocus == b.refusedFocus &&
           a.flash == b.flash && a.wheel == b.wheel &&
           a.wheelRing == b.wheelRing && a.wheelIndex == b.wheelIndex && a.param == b.param &&
           a.paramRing == b.paramRing && a.paramIndex == b.paramIndex && a.paramTyped == b.paramTyped &&
           a.paramStep == b.paramStep && a.paramValue == b.paramValue && a.paramBump == b.paramBump &&
           a.echoSeq == b.echoSeq && a.echoRing == b.echoRing && a.echoIndex == b.echoIndex &&
           a.paramAxis == b.paramAxis && a.paramPlane == b.paramPlane;   // S3 review FW-2: the live constraint
}

// The command of wheel entry `index` (1..count) of `ring`, or nullptr (cancel / out of range).
const app_cmd_t* command(const cc_app_profile_t* p, uint8_t ring, uint8_t index) {
    if (p == nullptr || ring >= p->ring_count || index < 1 || index > p->rings[ring].count) return nullptr;
    return &p->rings[ring].cmds[index - 1];
}

const app_scene_t* scene_of(const cc_app_profile_t* p, uint8_t ring, uint8_t index) {
    const app_cmd_t* c = command(p, ring, index);
    return c ? c->scene : nullptr;
}

int32_t step_of(float v, float unit) { return static_cast<int32_t>(lroundf(v / unit)); }
const float kYawStep = 2 * kPi / 32;

// --- slots (app profiles) ---
// CCAppSlot: the legacy zoom / orbit / pan / tilt, then knob, f1..f4 (FW-A, APP_PROFILES.md section 8).
const uint8_t kSlotKnob = CC_APP_SLOT_TILT + 1;
// What the knob's turn does to the shape.
enum Motion : uint8_t { MOTION_NONE = 0, MOTION_ZOOM, MOTION_ORBIT, MOTION_PAN, MOTION_TILT };

bool generic(const cc_app_profile_t* p) { return p != nullptr && p->has_slots; }

int slot_with_fx(const cc_app_profile_t* p, uint8_t fx) {
    for (int i = 0; i < APP_SLOTS; i++)
        if (p->slots[i].fx == fx) return i;
    return 0;
}

// A data profile's live slot (0 knob, 1-4 f1..f4) for the frame's slot. A legacy token picks the slot with that
// micro-interaction (tilt has none in Karl's model: the knob).
int live_slot(const cc_app_profile_t* p, uint8_t slot) {
    if (slot >= kSlotKnob && slot < kSlotKnob + APP_SLOTS) return slot - kSlotKnob;
    switch (slot) {
        case CC_APP_SLOT_ORBIT: return slot_with_fx(p, APP_FX_ORBIT);
        case CC_APP_SLOT_PAN: return slot_with_fx(p, APP_FX_PAN);
        case CC_APP_SLOT_ZOOM: return slot_with_fx(p, APP_FX_ZOOM);
        default: return 0;
    }
}

// Karl's turn_slot: a slot with no turn action (a tap, or nothing) leaves the knob's own action live.
int turn_slot(const cc_app_profile_t* p, int slot) {
    const uint8_t k = p->slots[slot].kind;
    return (k == APP_KIND_NONE || k == APP_KIND_TAP) ? 0 : slot;
}

uint8_t motion_of(const cc_app_profile_t* p, uint8_t slot) {
    if (!generic(p)) {   // the built-in Onshape: the slot is the motion
        switch (slot) {
            case CC_APP_SLOT_ORBIT: return MOTION_ORBIT;
            case CC_APP_SLOT_PAN: return MOTION_PAN;
            case CC_APP_SLOT_TILT: return MOTION_TILT;
            default: return MOTION_ZOOM;
        }
    }
    switch (p->slots[turn_slot(p, live_slot(p, slot))].fx) {
        case APP_FX_ZOOM: return MOTION_ZOOM;
        case APP_FX_ORBIT: return MOTION_ORBIT;
        case APP_FX_PAN: return MOTION_PAN;
        default: return MOTION_NONE;
    }
}

// The slot whose tap flashes (Undo): its fx flash, else a tap slot, else the commands slot (tap + hold wheel),
// with a label. -1 = none.
int flash_slot(const cc_app_profile_t* p) {
    static const uint8_t pass[3] = {0, APP_KIND_TAP, APP_KIND_COMMANDS};
    for (int k = 0; k < 3; k++)
        for (int i = 0; i < APP_SLOTS; i++) {
            const cc_app_slot_t& sl = p->slots[i];
            const bool hit = k == 0 ? sl.fx == APP_FX_FLASH : sl.kind == pass[k];
            if (hit && sl.label != nullptr && sl.label[0] != '\0') return i;
        }
    return -1;
}

// The key that selects a data profile's slot: KNOB, or the physical button (F1..F4 left to right).
const char* slot_key(const cc_app_profile_t* p, int slot) {
    static const char* const F[4] = {"F1", "F2", "F3", "F4"};
    if (slot <= 0) return "KNOB";
    const uint8_t b = p->slots[slot].button;
    return F[b < 4 ? b : slot - 1];
}
const char* slot_via(const cc_app_profile_t* p, int slot) {
    static const char* const VIA[4] = {"F1 + KNOB", "F2 + KNOB", "F3 + KNOB", "F4 + KNOB"};
    if (slot <= 0) return "KNOB";
    const uint8_t b = p->slots[slot].button;
    return VIA[b < 4 ? b : slot - 1];
}
const char* slot_label(const cc_app_profile_t* p, int slot) {
    const char* l = slot >= 0 ? p->slots[slot].label : nullptr;
    return l != nullptr ? l : "";
}
} // namespace

void CCAppCanvas::begin(uint16_t* frame, ccui::PlasmaTables* tables, uint32_t minFrameMs) {
    frame_ = frame;
    tables_ = tables;
    minFrameMs_ = minFrameMs ? minFrameMs : 1;
}

void CCAppCanvas::enter(const CCAppState& state, const CCAppInputs& in) {
    active_ = true;
    dirty_ = true;
    drawnOnce_ = false;
    state_ = state;
    buttons_ = in.buttons;
    yaw_ = kPi / 4; zoom_ = 0; pan_ = 0; pitch_ = ccui::SHAPE_REST_PITCH;
    lastAngle_ = in.angle; haveAngle_ = true;
    lastSlot_ = state.slot;
    settling_ = false; pitchSettling_ = false; moved_ = false;
    flashSeen_ = state.flash; flashOn_ = false; flashActive_ = false;
    echoSeen_ = state.echoSeq; echoOn_ = false;
    bumpSeen_ = state.paramBump; nudgeOn_ = false;
    wheelWas_ = state.wheel; wheelRing_ = state.wheelRing; wheelIndex_ = state.wheelIndex;
    wheelEntryMs_ = in.nowMs; wheelSlideMs_ = in.nowMs; wheelSlideActive_ = false; wheelPrevValid_ = false;
    wheelPrevRing_ = state.wheelRing; wheelPrevIndex_ = state.wheelIndex;
    sliding_ = false;
    f3Down_ = (in.buttons & 4) != 0; f3SinceMs_ = in.nowMs;
    activityMs_ = in.nowMs;
    view_ = CC_APP_VIEW_MAIN;
}

void CCAppCanvas::update(const CCAppState& s, uint32_t now) {
    if (!active_ || same_state(s, state_)) return;
    const Lease lease(s);
    const cc_app_profile_t* p = lease.get();
    if (s.flash != flashSeen_) { flashSeen_ = s.flash; flashStartMs_ = now; flashActive_ = true; }
    if (s.echoSeq != echoSeen_) {
        echoSeen_ = s.echoSeq;
        if (s.echoSeq) echoStartMs_ = now;
    }
    if (s.paramBump != bumpSeen_) { bumpSeen_ = s.paramBump; bumpAtMs_ = now; }
    if (s.wheel && !wheelWas_) {
        wheelEntryMs_ = now;
        wheelPrevValid_ = false;
    } else if (s.wheel && (s.wheelRing != wheelRing_ || s.wheelIndex != wheelIndex_)) {
        wheelPrevRing_ = wheelRing_;
        wheelPrevIndex_ = wheelIndex_;
        wheelPrevValid_ = true;
        wheelSlideDir_ = s.wheelRing != wheelRing_ ? (s.wheelRing > wheelRing_ ? 1 : -1)
                                                   : (s.wheelIndex > wheelIndex_ ? 1 : -1);
        wheelSlideMs_ = now;
        wheelSlideActive_ = true;
        wheelEntryMs_ = now;
    }
    wheelWas_ = s.wheel;
    wheelRing_ = s.wheelRing;
    wheelIndex_ = s.wheelIndex;
    // Leaving orbit eases the cube to the nearest clean isometric pose (45 + k*90 deg).
    const uint8_t was = motion_of(p, state_.slot), now_motion = motion_of(p, s.slot);
    if (was == MOTION_ORBIT && now_motion != MOTION_ORBIT) {
        const float q = kPi / 2, rest = kPi / 4;
        settleFrom_ = yaw_;
        settleTo_ = roundf((yaw_ - rest) / q) * q + rest;
        settleStartMs_ = now;
        settling_ = true;
    }
    // Leaving tilt eases the view's pitch back to the isometric rest (the nearest turn of it: no spin back).
    if (was == MOTION_TILT && now_motion != MOTION_TILT) {
        const float turn = 2 * kPi, rest = ccui::SHAPE_REST_PITCH;
        pitchFrom_ = pitch_ - (rest + roundf((pitch_ - rest) / turn) * turn);
        pitch_ = rest + pitchFrom_;
        pitchSettleMs_ = now;
        pitchSettling_ = true;
    }
    state_ = s;
    activityMs_ = now;
    dirty_ = true;
}

void CCAppCanvas::track_angle(const CCAppInputs& in, uint8_t motion) {
    if (!haveAngle_) { lastAngle_ = in.angle; haveAngle_ = true; }
    // FW-BUG-032: the angle word wraps modulo 2^32 (CCAngleWord): the difference in unsigned arithmetic, never a
    // signed subtraction that overflows across the wrap.
    const int32_t diff = static_cast<int32_t>(static_cast<uint32_t>(in.angle) - static_cast<uint32_t>(lastAngle_));
    // FW-BUG-045: the jump guard covers a re-anchor to a new control only. The wake turn (and the post-wake settle)
    // never reaches here: lcd_thread.cpp feeds in.angle through CCAppAngleHold (cc_lcd_logic.h), which removes the
    // travel the FOC swallows while the motor is off, so a wake turn below the guard does not move the cube.
    if (diff > kCCAppJump || diff < -kCCAppJump) {   // a re-anchor (new control): not a turn
        lastAngle_ = in.angle;
        return;
    }
    if (diff >= kCCAppDeadband || diff <= -kCCAppDeadband) {
        lastAngle_ = in.angle;
        activityMs_ = in.nowMs;
        if (view_ == CC_APP_VIEW_IDLE) dirty_ = true;
        // Only the main screen's cube follows the knob (the wheel and parameter mode use the turn).
        if (state_.wheel || state_.param) return;
        const float d = diff * 1e-4f * CC_APP_KNOB_SIGN;
        movedMs_ = in.nowMs;
        moved_ = true;
        switch (motion) {
            case MOTION_ORBIT: yaw_ += d; settling_ = false; break;
            case MOTION_PAN: pan_ += d * 60.0f; break;
            case MOTION_TILT: pitch_ += d; pitchSettling_ = false; break;
            case MOTION_NONE: break;
            default: zoom_ += d / (kPi / 2); break;
        }
    }
    if (settling_) {
        float k = static_cast<float>(in.nowMs - settleStartMs_) / kCCAppSettleMs;
        if (k >= 1) { k = 1; settling_ = false; }
        const float e = 1 - (1 - k) * (1 - k) * (1 - k);
        yaw_ = settleFrom_ + (settleTo_ - settleFrom_) * e;
    }
    if (pitchSettling_) {
        float k = static_cast<float>(in.nowMs - pitchSettleMs_) / kCCAppSettleMs;
        if (k >= 1) { k = 1; pitchSettling_ = false; }
        pitch_ = ccui::SHAPE_REST_PITCH + pitchFrom_ * (1 - k) * (1 - k) * (1 - k);
    }
    if (!pitchSettling_ && (pitch_ > 64 * kPi || pitch_ < -64 * kPi)) pitch_ = fmodf(pitch_, 2 * kPi);
    if (!settling_ && (yaw_ > 64 * kPi || yaw_ < -64 * kPi)) yaw_ = fmodf(yaw_, 2 * kPi);
    if (zoom_ > 4096 || zoom_ < -4096) zoom_ = zoom_ - floorf(zoom_);
    if (pan_ > 1e6f || pan_ < -1e6f) pan_ = fmodf(pan_, 64.0f * 22.0f * 16.0f);
}

bool CCAppCanvas::due(uint32_t now, bool fast) const {
    if (!drawnOnce_) return true;
    const uint32_t gap = fast ? minFrameMs_ : kCCAppLoopMs;
    return now - lastDrawMs_ >= gap;   // elapsed, unsigned: a draw 2^31 ms ago is long due, not ahead
}

bool CCAppCanvas::step(const CCAppInputs& in) {
    if (!active_ || frame_ == nullptr) return false;
    const Lease lease(state_);
    const cc_app_profile_t* p = lease.get();
    const uint32_t now = in.nowMs;
    if (in.buttons != buttons_) { buttons_ = in.buttons; dirty_ = true; activityMs_ = now; }
    const bool f3 = (buttons_ & 4) != 0;
    if (f3 && !f3Down_) f3SinceMs_ = now;
    f3Down_ = f3;
    track_angle(in, motion_of(p, state_.slot));

    // Flash and slide are elapsed-time windows with an active flag (unsigned now - start): a deadline compared
    // with before() reads as "still ahead" once the uptime passes 2^31 ms with no event since (FW-BUG-023).
    if (flashActive_ && now - flashStartMs_ >= kCCAppFlashMs) flashActive_ = false;
    if (wheelSlideActive_ && now - wheelSlideMs_ >= kCCAppWheelSlideMs) wheelSlideActive_ = false;
    const bool flash = flashActive_;
    const bool echo = state_.echoSeq != 0 && echoSeen_ == state_.echoSeq && before(now, echoStartMs_ + kCCAppEchoMs) &&
                      !before(now, echoStartMs_);
    const bool nudge = before(now, bumpAtMs_ + kCCAppNudgeMs) && !before(now, bumpAtMs_);
    const bool sliding = state_.wheel && wheelSlideActive_;
    if (flash != flashOn_ || echo != echoOn_ || nudge != nudgeOn_ || sliding != sliding_) dirty_ = true;
    flashOn_ = flash; echoOn_ = echo; nudgeOn_ = nudge; sliding_ = sliding;

    const app_cmd_t* pcmd = state_.param ? command(p, state_.paramRing, state_.paramIndex) : nullptr;
    CCAppView view = CC_APP_VIEW_MAIN;
    if (p == nullptr) view = CC_APP_VIEW_LOADING;
    else if (pcmd != nullptr && pcmd->param != nullptr) view = CC_APP_VIEW_PARAM;
    else if (state_.wheel) view = CC_APP_VIEW_WHEEL;
    else if (echo) view = CC_APP_VIEW_ECHO;
    else if (now - activityMs_ >= kCCAppIdleMs && p->icon48 != nullptr) view = CC_APP_VIEW_IDLE;   // any input ends it (elapsed: no wrap)
    if (view != view_) {
        if (view == CC_APP_VIEW_IDLE) idleStartMs_ = now;
        view_ = view;
        dirty_ = true;
    }
    if (moved_ && !before(now, movedMs_ + kCCAppActiveMs)) moved_ = false;

    // The stepped pose that would be drawn now: a moving cube draws only when it changes (no sub-step crawl).
    bool poseChanged = false;
    if (view_ == CC_APP_VIEW_MAIN && p->visual == APP_VISUAL_SHAPE && p->stepped) {
        const int32_t ys = step_of(yaw_, kYawStep), zs = step_of(zoom_, 0.125f), ps = step_of(pan_, 2.0f);
        const int32_t ts = step_of(pitch_ - ccui::SHAPE_REST_PITCH, kYawStep);
        poseChanged = ys != drawnYawStep_ || zs != drawnZoomStep_ || ps != drawnPanStep_ || ts != drawnPitchStep_;
    } else if (view_ == CC_APP_VIEW_MAIN && p->visual == APP_VISUAL_SHAPE) {
        poseChanged = yaw_ != drawnYaw_ || zoom_ != drawnZoom_ || pan_ != drawnPan_ || pitch_ != drawnPitch_;
    }
    const bool looping = view_ == CC_APP_VIEW_WHEEL || view_ == CC_APP_VIEW_ECHO || view_ == CC_APP_VIEW_IDLE ||
                         (view_ == CC_APP_VIEW_PARAM && f3Down_);
    const bool fast = dirty_ || poseChanged || sliding || nudge;
    if (!fast && !looping) return false;
    if (!due(now, fast)) return false;
    draw(in, p);
    dirty_ = false;
    drawnOnce_ = true;
    lastDrawMs_ = now;
    return true;
}

void CCAppCanvas::draw(const CCAppInputs& in, const cc_app_profile_t* p) {
    using namespace ccui;
    const uint32_t now = in.nowMs;
    bind(frame_);
    clear(BLACK);
    if (view_ == CC_APP_VIEW_LOADING || p == nullptr) {
        draw_loading();
        return;
    }
    switch (view_) {
        case CC_APP_VIEW_PARAM: {
            const app_cmd_t* c = command(p, state_.paramRing, state_.paramIndex);
            const app_param_t* pr = c->param;
            ParamView v;
            memset(&v, 0, sizeof(v));
            v.name = c->name;
            float value = state_.paramValue / 1000.0f;
            v.typed = state_.paramTyped;
            v.field = pr->field;
            float drawn = v.typed ? value : pr->start + value;
            if (pr->min < pr->max) {   // the profile's range: the card and the number never leave it
                drawn = drawn < pr->min ? pr->min : drawn > pr->max ? pr->max : drawn;
                value = v.typed ? drawn : drawn - pr->start;
            }
            v.value = v.field ? value : drawn;             // field B: the value; field A: the change; a handle: the value
            v.drawn = drawn;
            v.label = drawn < 0 && pr->label_neg != nullptr && pr->label_neg[0] != '\0' ? pr->label_neg : pr->label;
            v.decimals = pr->decimals;
            for (int i = 0; i < 3; i++) v.steps[i] = pr->steps[i];
            v.step = state_.paramStep;
            v.visual = pr->visual;
            v.f3 = f3Down_ ? static_cast<float>(now - f3SinceMs_) / kCCAppCancelMs : -1.0f;
            v.nudge = nudgeOn_ ? 3 : 0;
            v.degrees = (pr->flags & APP_PARAM_DEG) != 0;
            v.modes = pr->modes;
            v.axes = (pr->flags & APP_PARAM_AXES) != 0;
            // S3 review FW-2: the frame's live constraint (APP_PROFILES.md section 8): param.axis 0-2 or 3 (uniform: all
            // three), absent = the profile's axis_default; param.plane (Shift + the axis key) lights the plane normal
            // to that axis (its other two).
            const bool live = state_.paramAxis >= 0 && state_.paramAxis <= APP_AXIS_UNIFORM;
            const int axis = live ? state_.paramAxis : pr->axis_default;
            v.axis = axis < 3 ? axis : 0;
            const bool uniform = axis == APP_AXIS_UNIFORM && (live || (pr->flags & APP_PARAM_UNIFORM));
            v.axis_bits = static_cast<uint8_t>(uniform ? 7 : state_.paramPlane && axis < 3 ? 7 & ~(1 << v.axis)
                                                                                           : 1 << v.axis);
            draw_param(v);
            break;
        }
        case CC_APP_VIEW_WHEEL: {
            WheelView v;
            memset(&v, 0, sizeof(v));
            const uint8_t ring = state_.wheelRing < p->ring_count ? state_.wheelRing : 0;
            if (p->ring_count == 0) {   // a profile without rings: only cancel
                v.ring_name = "";
                v.count = 1;
            } else {
                const app_ring_t& r = p->rings[ring];
                v.ring_name = r.name;
                v.ring_count = p->ring_count < 8 ? p->ring_count : 8;
                for (int i = 0; i < v.ring_count; i++) v.ring_tabs[i] = p->rings[i].tab;
                v.ring = ring;
                v.count = r.count + 1;
                v.entry = state_.wheelIndex <= r.count ? state_.wheelIndex : 0;
            }
            const app_cmd_t* c = command(p, ring, static_cast<uint8_t>(v.entry));
            v.name = c ? c->name : "CANCEL";
            v.scene = c ? c->scene : nullptr;
            if (c) {
                v.search = c->search;
                v.modifier = c->search ? p->search_modifier : c->modifier;
                v.key = c->search ? p->search_key : c->key;
                v.disabled = (c->flags & APP_CMD_DISABLED) != 0;
                v.macro = (c->flags & APP_CMD_MACRO) != 0;
            }
            v.prev = scene_of(p, wheelPrevRing_, wheelPrevIndex_);
            v.prev_valid = wheelPrevValid_;
            const float k = wheelSlideActive_ ? static_cast<float>(now - wheelSlideMs_) / kCCAppWheelSlideMs : 1.0f;
            v.slide = k >= 1 ? 1 : 1 - (1 - k) * (1 - k) * (1 - k);
            v.slide_dir = wheelSlideDir_;
            v.t_ms = now - wheelEntryMs_;
            draw_wheel(v);
            break;
        }
        case CC_APP_VIEW_IDLE:
            if (tables_) draw_plasma(*tables_, (now - idleStartMs_) % 600000u, p->icon48, p->plasma_heat, p->crc);
            break;
        default: {
            const bool data = generic(p);
            const bool shape = p->visual == APP_VISUAL_SHAPE;
            ShapeView sv;
            memset(&sv, 0, sizeof(sv));
            sv.shape = p->shape;
            sv.style = p->shape_style;
            switch (motion_of(p, state_.slot)) {
                case MOTION_ORBIT: sv.scene = SCENE_ORBIT; break;
                case MOTION_PAN: sv.scene = SCENE_PAN; break;
                case MOTION_TILT: sv.scene = SCENE_TILT; break;
                default: sv.scene = SCENE_ZOOM; break;
            }
            if (p->stepped) {
                // Only clean poses: 32 per turn (45 deg is one; pitch about its 30 deg rest), zoom in 1/8
                // doublings, pan in 2 px.
                drawnYawStep_ = step_of(yaw_, kYawStep);
                drawnZoomStep_ = step_of(zoom_, 0.125f);
                drawnPanStep_ = step_of(pan_, 2.0f);
                drawnPitchStep_ = step_of(pitch_ - SHAPE_REST_PITCH, kYawStep);
                sv.yaw = drawnYawStep_ * kYawStep;
                sv.zoom = drawnZoomStep_ * 0.125f;
                sv.pan = drawnPanStep_ * 2.0f;
                sv.pitch = SHAPE_REST_PITCH + drawnPitchStep_ * kYawStep;
            } else {
                sv.yaw = drawnYaw_ = yaw_;
                sv.zoom = drawnZoom_ = zoom_;
                sv.pan = drawnPan_ = pan_;
                sv.pitch = drawnPitch_ = pitch_;
            }
            sv.flash = flashOn_;
            AppView v;
            memset(&v, 0, sizeof(v));
            v.name = p->name;
            v.icon24 = p->icon24;
            v.icon48 = p->icon48;
            v.buttons_held = buttons_;
            v.flash = flashOn_;
            v.refused = state_.refused && !flashOn_;
            v.refusedFocus = state_.refusedFocus;
            v.generic = data;
            v.shape = shape ? &sv : nullptr;
            if (!data) {
                // The built-in Onshape's legacy slot model (Desk Dial 7.2.2.0): hold 1 tilt, 2 orbit, 4 pan, tap 3 undo.
                static const char* const KEY[4] = {"KNOB", "F2", "F4", "F1"};
                static const char* const ACTION[4] = {"ZOOM", "ORBIT", "PAN", "TILT"};
                const uint8_t slot = state_.slot <= CC_APP_SLOT_TILT ? state_.slot : 0;
                for (int i = 0; i < 4; i++) v.legend[i] = p->legend[i];
                v.action_key = flashOn_ ? "F3" : KEY[slot];
                v.action = flashOn_ ? "UNDO" : ACTION[slot];
                v.action_via = v.action_key;
            } else {
                // A data profile: the live slot's key and label; a tap flash names the tapped slot.
                const int live = turn_slot(p, live_slot(p, state_.slot));
                const int tap = flashOn_ ? flash_slot(p) : -1;
                const int shown = tap >= 0 ? tap : live;
                v.action_key = slot_key(p, shown);
                v.action_via = tap >= 0 ? slot_key(p, tap) : slot_via(p, live);
                v.action = slot_label(p, shown);
                // The legend, physical left to right; an empty one names the slot that button selects.
                for (int i = 0; i < 4; i++) {
                    v.legend[i] = p->legend[i];
                    if (v.legend[i] != nullptr && v.legend[i][0] != '\0') continue;
                    for (int k = 1; k < APP_SLOTS; k++)
                        if (p->slots[k].button == i && p->slots[k].label != nullptr) v.legend[i] = p->slots[k].label;
                }
            }
            if (view_ == CC_APP_VIEW_ECHO) {
                const app_cmd_t* c = command(p, state_.echoRing, state_.echoIndex);
                if (c) {
                    v.echo = true;
                    v.echo_scene = c->scene;
                    v.echo_name = c->name;
                    v.echo_ms = now - echoStartMs_;
                }
            }
            draw_app_main(v);
            break;
        }
    }
}
