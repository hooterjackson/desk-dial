#include "cc_lights.h"
#include <string.h>

// Contract-v4 LED model, section 5. Each function names its twin in
// control_center/preview_lights.py; the integer formulas are identical.

namespace {
constexpr int kRingSize = CC_RING_LEDS;
constexpr int kVolumeStart = 35;            // k = 0 of the volume arc
constexpr int kVolumeEnd = 25;              // (35 + 50) mod 60, the upper bound mark
constexpr int kListPitch = 3;               // segments between list entries
constexpr int kWindow = CC_RING_WINDOW;     // transmitted entries at most (section 4)
constexpr int kTracksNeutral = 0;
constexpr int kTracksPrev0 = 52, kTracksPrev1 = 53;
constexpr int kTracksNext0 = 7, kTracksNext1 = 8;
constexpr uint8_t kPressBlend = 36;         // cc4 press highlight: blend(shown, W, 36)
constexpr uint32_t kSeqMax = 0x7FFFFFFF;    // feedback.seq is 1..0x7FFFFFFF

uint8_t channel(uint32_t color, uint8_t shift) {
    return static_cast<uint8_t>((color >> shift) & 255);
}

uint32_t rgb(uint32_t r, uint32_t g, uint32_t b) {
    return (r << 16) | (g << 8) | b;
}

CCLedCell cell(uint32_t color, uint8_t level) {
    CCLedCell out;
    out.rgb = color;
    out.level = level;
    return out;
}

// preview_lights.blend (press highlight only): (a*(255-t) + b*t + 127) / 255.
uint32_t blend(uint32_t a, uint32_t b, uint8_t amount) {
    const uint32_t inverse = 255u - amount;
    return rgb((channel(a, 16) * inverse + channel(b, 16) * amount + 127u) / 255u,
               (channel(a, 8) * inverse + channel(b, 8) * amount + 127u) / 255u,
               (channel(a, 0) * inverse + channel(b, 0) * amount + 127u) / 255u);
}

// preview_lights.peak: the damping comparison key (section 5.7).
uint8_t peak(uint32_t color) {
    const uint8_t r = channel(color, 16), g = channel(color, 8), b = channel(color, 0);
    const uint8_t rg = r > g ? r : g;
    return rg > b ? rg : b;
}

uint8_t address(int index, uint8_t orientation) {
    // Logical positions run clockwise from twelve o'clock; the ring's wired
    // addresses run counterclockwise. Reflect before applying the original
    // mounting rotation, map(orientation, 0, 3, 0, 135), so the top anchor and
    // left / neutral / right semantics stay aligned with the upright display.
    const int clockwise = (index % kRingSize + kRingSize) % kRingSize;
    return static_cast<uint8_t>((kRingSize - clockwise + (orientation & 3) * 45) % kRingSize);
}

// put(i, c, l) OVERWRITES ring[i mod 60] (section 5.1; never max-combines).
void put(CCLedCell (&cells)[CC_RING_LEDS], int i, uint32_t color, uint8_t level) {
    CCLedCell& target = cells[((i % kRingSize) + kRingSize) % kRingSize];
    target.rgb = color;
    target.level = level;
}

// preview_lights.volume_color: volc(k) = W, or in colour mode VRED from k >= 45,
// AMBER from k >= 40.
uint32_t volume_color(int k, bool colored) {
    if (!colored) return CCLed::white;
    return k >= 45 ? CCLed::volumeRed : (k >= 40 ? CCLed::amber : CCLed::white);
}

// preview_lights._draw_volume (section 5.2). n = (v+1)/2; vseg(x) = (35 + (x+1)/2) mod 60.
int draw_volume(const CCFrame& f, CCLedCell (&cells)[CC_RING_LEDS]) {
    const int v = f.ringValue <= 100 ? f.ringValue : 0;
    const int c = f.confirmedVolume <= 100 ? f.confirmedVolume : v;
    const int n = (v + 1) / 2, nc = (c + 1) / 2;
    const bool colored = f.coloredLeds;
    if (f.activity == CC_OFFLINE) {                      // Home offline: confirmed endpoint only
        put(cells, kVolumeStart + nc, CCLed::white, CCLed::L1);
        return (kVolumeStart + nc) % kRingSize;
    }
    put(cells, kVolumeStart, CCLed::white, CCLed::L1);   // 1. bound marks (35 then 25)
    put(cells, kVolumeEnd, CCLed::white, CCLed::L1);
    for (int k = 0; k <= n; ++k)                         // 2. body; span above confirmed at L1
        put(cells, kVolumeStart + k, volume_color(k, colored), k <= nc ? CCLed::L2 : CCLed::L1);
    for (int k = n + 1; k <= nc; ++k)                    // 3. pending decrease span
        put(cells, kVolumeStart + k, volume_color(k, colored), CCLed::L1);
    if ((v & 1) && n >= 1)                               // 4. odd-v shoulder (deviation 1)
        put(cells, kVolumeStart + n - 1, volume_color(n - 1, colored), CCLed::shoulder);
    put(cells, kVolumeStart + n, volume_color(n, colored),   // 5. endpoint
        f.ringExternal ? CCLed::L4 : CCLed::L3);
    return (kVolumeStart + n) % kRingSize;
}

// preview_lights._ring_window + _draw_list (sections 4 and 5.3, Recent and Windows).
// The parser has already enforced the window rule; the same rules are applied
// again defensively: an invalid first is replaced by the host window and its
// relative colours/mask are dropped; a too-long or out-of-range colour list
// drops every colour; mask bits beyond the window drop the mask.
class ListDraw {
public:
    ListDraw(const CCFrame& f, int first, int width, int colorCount, uint32_t mask, int more)
        : f_(&f), first_(first), width_(width), colorCount_(colorCount), mask_(mask), more_(more),
          c0_((f.ringCount - 1) / 2) {}

    int slot(int j) const { return (((j - c0_) * kListPitch) % kRingSize + kRingSize) % kRingSize; }

    uint32_t accent(int j) const {
        const int k = j - first_;
        if (!f_->coloredLeds || j == more_ || k < 0 || k >= colorCount_ || f_->ringColors[k] == 0)
            return CCLed::white;
        return f_->ringColors[k];
    }

    bool unavailable(int j) const {
        const int k = j - first_;
        return k >= 0 && k < width_ && ((mask_ >> k) & 1u) != 0;
    }

private:
    const CCFrame* f_;
    int first_, width_, colorCount_;
    uint32_t mask_;
    int more_, c0_;
};

int draw_list(const CCFrame& f, uint32_t pendingMs, uint32_t loadingMs,
              CCLedCell (&cells)[CC_RING_LEDS]) {
    if (f.activity == CC_LOADING) {                      // only segment 0, nothing else
        put(cells, 0, CCLed::white, cc_led_loading_level(loadingMs));
        return 0;
    }
    const int count = f.ringCount, index = f.ringIndex;
    if (!(index < count)) return 0;                      // parsers reject this; draw nothing
    const int given = f.ringFirst;
    int first = given;
    bool relative = true;
    if (!(given <= index && index < given + kWindow && (count > kWindow || given == 0))) {
        first = cc_window_first(f.ringIndex, f.ringCount);
        relative = false;
    }
    int width = count - first;
    if (width > kWindow) width = kWindow;
    if (width < 0) width = 0;
    int colorCount = relative ? f.ringColorCount : 0;
    if (colorCount > width) colorCount = 0;
    for (int k = 0; k < colorCount; ++k)
        if (f.ringColors[k] > 0xFFFFFFu) colorCount = 0;
    const uint32_t mask = relative && f.ringUnavailable < (1u << width) ? f.ringUnavailable : 0u;
    const int more = f.ringMoreIndex >= -1 && f.ringMoreIndex <= count - 1 ?
        static_cast<int>(f.ringMoreIndex) : -1;
    const ListDraw list(f, first, width, colorCount, mask, more);

    for (int j = first; j < first + width; ++j)          // 1. landmarks; unavailable = gap
        if (!list.unavailable(j)) put(cells, list.slot(j), list.accent(j), CCLed::L1);
    if (more >= 0)                                       // 2. More double landmark
        put(cells, list.slot(more) + 1, CCLed::white, CCLed::L1);
    const int cursor = list.slot(index);
    if (index == more) {
        put(cells, cursor, CCLed::white, CCLed::L3);
        put(cells, cursor + 1, CCLed::white, CCLed::L3);
    } else if (list.unavailable(index)) {
        const bool windows = !strcmp(f.mode, "WINDOWS") || f.layoutId == CC_LAYOUT_WINDOWS;
        put(cells, cursor, windows ? list.accent(index) : CCLed::white, CCLed::L2);
    } else {
        put(cells, cursor, list.accent(index), CCLed::L3);
    }
    if (f.activity == CC_PENDING)                        // white pulse (deviations 3, 4)
        put(cells, cursor, CCLed::white, cc_led_pending_level(pendingMs));
    return cursor;
}

// preview_lights._draw_transport (section 5.4, always white). index 0 Prev,
// 1 Neutral, 2 Next; mask bit0 = no Prev (bit2 = no Next still draws Next).
int draw_transport(const CCFrame& f, uint32_t pendingMs, CCLedCell (&cells)[CC_RING_LEDS]) {
    if (f.ringCount != 3 || f.ringIndex > 2) return 0;
    const uint32_t mask = f.ringUnavailable <= 7u ? f.ringUnavailable : 0u;
    const bool noPrev = (mask & 1u) != 0;
    if (!noPrev) {
        put(cells, kTracksPrev0, CCLed::white, CCLed::L1);
        put(cells, kTracksPrev1, CCLed::white, CCLed::L1);
    }
    put(cells, kTracksNeutral, CCLed::white, CCLed::L1);
    put(cells, kTracksNext0, CCLed::white, CCLed::L1);
    put(cells, kTracksNext1, CCLed::white, CCLed::L1);
    int pair[2] = {kTracksNeutral, kTracksNeutral};
    int pairSize = 1, cursor = kTracksNeutral;
    if (f.ringIndex == 0) {
        pair[0] = kTracksPrev0; pair[1] = kTracksPrev1; pairSize = 2; cursor = kTracksPrev0;
        if (!noPrev) {
            put(cells, kTracksPrev0, CCLed::white, CCLed::L3);
            put(cells, kTracksPrev1, CCLed::white, CCLed::L3);
        }
    } else if (f.ringIndex == 2) {
        pair[0] = kTracksNext0; pair[1] = kTracksNext1; pairSize = 2; cursor = kTracksNext1;
        put(cells, kTracksNext0, CCLed::white, CCLed::L3);
        put(cells, kTracksNext1, CCLed::white, CCLed::L3);
    } else {
        put(cells, kTracksNeutral, CCLed::white, CCLed::L2);
    }
    if (f.activity == CC_PENDING) {                      // the selected pair pulses (even without Prev)
        const uint8_t level = cc_led_pending_level(pendingMs);
        for (int k = 0; k < pairSize; ++k) put(cells, pair[k], CCLed::white, level);
    }
    return cursor;
}

bool pressable(uint8_t tone) {
    return tone == CC_TONE_NAV || tone == CC_TONE_GO || tone == CC_TONE_STOP;
}

// preview_lights._press: blend toward white while held, enabled buttons with an icon only.
uint32_t press(const CCFrame& f, uint8_t slot, uint8_t pressedMask, uint32_t shown) {
    const bool held = (pressedMask & (1u << slot)) != 0;
    return held && pressable(cc_button_tone_v4(f, slot)) ? blend(shown, CCLed::white, kPressBlend) : shown;
}
} // namespace

// presentation.button_tone (PRESENTATION_V4 5.9), verbatim from 1.0.0-cc5.3's cc_button_tone.
uint8_t cc_button_tone_v4(const CCFrame& frame, uint8_t slot) {
    if (slot >= 4) return CC_TONE_NONE;
    const CCButton& button = frame.buttons[slot];
    const uint8_t icon = cc_button_icon(button);
    if (icon == CC_ICON_NONE) return CC_TONE_NONE;
    if (!button.enabled) return CC_TONE_DIM;
    if (slot == 0 && icon == CC_ICON_CANCEL) return CC_TONE_STOP;
    if (slot == 3 && (icon == CC_ICON_PLAY || icon == CC_ICON_PREV ||
                      icon == CC_ICON_NEXT || icon == CC_ICON_SWITCH)) return CC_TONE_GO;
    return CC_TONE_NAV;
}

uint32_t cc_led_drive(uint32_t color, uint8_t level) {
    return rgb((channel(color, 16) * level + 127u) / 255u,
               (channel(color, 8) * level + 127u) / 255u,
               (channel(color, 0) * level + 127u) / 255u);
}

uint8_t cc_led_ease(uint32_t elapsed, uint32_t duration) {
    if (elapsed >= duration) return 255;
    const uint32_t x = elapsed * 16u, i = x / duration, r = x % duration;
    const uint32_t low = CCLed::easeLut[i], high = CCLed::easeLut[i + 1];  // LUT is non-decreasing
    return static_cast<uint8_t>(low + (high - low) * r / duration);
}

uint32_t cc_led_toward(uint32_t from, uint32_t to, uint8_t e) {
    uint32_t out = 0;
    for (uint8_t shift = 0; shift <= 16; shift = static_cast<uint8_t>(shift + 8)) {
        const int a = channel(from, shift), b = channel(to, shift);
        const int d = b - a;
        const int value = a + d * static_cast<int>(e) / 255;  // C++11: truncates toward zero
        out |= static_cast<uint32_t>(value) << shift;
    }
    return out;
}

uint8_t cc_led_pending_level(uint32_t elapsedMs) {
    if (elapsedMs >= CCLed::pendingHoldMs) return CCLed::L1;
    return ((elapsedMs / CCLed::pulseMs) & 1u) ? CCLed::L1 : CCLed::L3;
}

uint8_t cc_led_loading_level(uint32_t elapsedMs) {
    return ((elapsedMs / CCLed::pulseMs) & 1u) ? CCLed::L1 : CCLed::L2;
}

uint8_t cc_ring_target(const CCFrame& frame, uint32_t pendingMs, uint32_t loadingMs,
                       uint8_t flash, CCLedCell (&cells)[CC_RING_LEDS]) {
    for (int i = 0; i < kRingSize; ++i) cells[i] = cell(0, CCLed::L0);
    int cursor = 0;
    if (frame.ringStyle == CC_RING_LEVEL) cursor = draw_volume(frame, cells);
    else if (frame.ringStyle == CC_RING_SELECTION) cursor = draw_list(frame, pendingMs, loadingMs, cells);
    else if (frame.ringStyle == CC_RING_TRANSPORT) cursor = draw_transport(frame, pendingMs, cells);
    // CC_RING_OFF (or anything unknown): all dark, cursor 0 (section 5.5).
    if (flash == CC_FLASH_OK || flash == CC_FLASH_ERR) {  // section 5.8: drawn last, ignores ledStyle
        const uint32_t color = flash == CC_FLASH_OK ? CCLed::green : CCLed::red;
        const uint8_t level = flash == CC_FLASH_OK ? CCLed::L4 : CCLed::L3;
        for (int d = -1; d <= 1; ++d) put(cells, cursor + d, color, level);
    }
    return static_cast<uint8_t>(cursor);
}

CCLedCell cc_button_light(const CCFrame& frame, uint8_t slot) {
    switch (cc_button_tone_v4(frame, slot)) {
        case CC_TONE_DIM: return cell(CCLed::white, CCLed::L1);
        case CC_TONE_STOP: return cell(CCLed::red, CCLed::L2);
        case CC_TONE_GO: return cell(CCLed::green, CCLed::L3);
        case CC_TONE_NAV: return cell(CCLed::white, CCLed::L2);
        default: return cell(0, CCLed::L0);
    }
}

void cc_render_buttons(const CCFrame& frame, uint8_t pressedMask, uint32_t (&out)[4]) {
    for (uint8_t i = 0; i < 4; ++i) {
        const CCLedCell light = cc_button_light(frame, i);
        out[i] = press(frame, i, pressedMask, cc_led_drive(light.rgb, light.level));
    }
}

uint8_t cc_ring_address(int logical, uint8_t orientation) {
    return address(logical, orientation);
}

void cc_ring_physical(const uint32_t (&logical)[CC_RING_LEDS], uint8_t orientation,
                      uint32_t (&physical)[CC_RING_LEDS]) {
    for (int i = 0; i < kRingSize; ++i) physical[address(i, orientation)] = logical[i];
}

CCLightRenderer::CCLightRenderer() {
    reset();
}

void CCLightRenderer::reset() {
    memset(cells_, 0, sizeof(cells_));
    memset(targets_, 0, sizeof(targets_));
    memset(shown_, 0, sizeof(shown_));
    memset(from_, 0, sizeof(from_));
    memset(to_, 0, sizeof(to_));
    memset(start_, 0, sizeof(start_));
    memset(decaying_, 0, sizeof(decaying_));
    memset(buttonShown_, 0, sizeof(buttonShown_));
    memset(buttonFrom_, 0, sizeof(buttonFrom_));
    memset(buttonTo_, 0, sizeof(buttonTo_));
    memset(buttonStart_, 0, sizeof(buttonStart_));
    memset(buttonFading_, 0, sizeof(buttonFading_));
    lastSeq_ = 0;                                        // 0 = none (seq is 1..0x7FFFFFFF)
    flashStart_ = pendingStart_ = loadingStart_ = 0;
    flash_ = CC_FLASH_NONE;
    cursor_ = 0;
    snap_ = true;                                        // the next render snaps everything
    seeded_ = false;                                     // ... and seeds lastSeq without flashing
    pendingOn_ = loadingOn_ = false;
}

// PreviewLights._feedback (section 5.8): seq != lastSeq flashes regardless of
// control id or layout; the first frame after reset only seeds lastSeq.
uint8_t CCLightRenderer::feedback(const CCFrame& f, uint32_t now) {
    const bool valid = f.feedbackPresent &&
        (f.feedbackKind == CC_FEEDBACK_OK || f.feedbackKind == CC_FEEDBACK_ERR) &&
        f.feedbackSeq >= 1 && f.feedbackSeq <= kSeqMax;
    if (!seeded_) {
        seeded_ = true;
        if (valid) lastSeq_ = f.feedbackSeq;
    } else if (valid && f.feedbackSeq != lastSeq_) {
        lastSeq_ = f.feedbackSeq;
        flash_ = f.feedbackKind == CC_FEEDBACK_OK ? CC_FLASH_OK : CC_FLASH_ERR;
        flashStart_ = now;
    }
    if (flash_ != CC_FLASH_NONE) {
        const uint32_t duration = flash_ == CC_FLASH_OK ? CCLed::flashOkMs : CCLed::flashErrMs;
        if (static_cast<uint32_t>(now - flashStart_) >= duration) flash_ = CC_FLASH_NONE;
    }
    return flash_;
}

// PreviewLights._onsets (section 5.6): each onset is taken on the rising edge of
// its condition. pending = activity pending on a selection/transport ring;
// loading = activity loading on a selection ring.
void CCLightRenderer::onsets(const CCFrame& f, uint32_t now, uint32_t& pendingMs, uint32_t& loadingMs) {
    const bool pending = f.activity == CC_PENDING &&
        (f.ringStyle == CC_RING_SELECTION || f.ringStyle == CC_RING_TRANSPORT);
    const bool loading = f.activity == CC_LOADING && f.ringStyle == CC_RING_SELECTION;
    if (pending && !pendingOn_) pendingStart_ = now;
    if (loading && !loadingOn_) loadingStart_ = now;
    pendingOn_ = pending;
    loadingOn_ = loading;
    pendingMs = pending ? static_cast<uint32_t>(now - pendingStart_) : 0u;
    loadingMs = loading ? static_cast<uint32_t>(now - loadingStart_) : 0u;
}

// PreviewLights._damp (section 5.7): a target that is not lower (peak channel)
// than what is shown snaps; a lower one decays from the shown colour over 260 ms.
uint32_t CCLightRenderer::damp(uint8_t i, uint32_t target, uint32_t now) {
    if (target != to_[i]) {
        if (peak(target) >= peak(shown_[i])) {
            from_[i] = to_[i] = shown_[i] = target;
            decaying_[i] = false;
        } else {
            from_[i] = shown_[i];
            to_[i] = target;
            start_[i] = now;
            decaying_[i] = true;
        }
    }
    if (decaying_[i]) {
        const uint32_t elapsed = now - start_[i];
        if (elapsed >= CCLed::decayMs) {
            shown_[i] = to_[i];
            decaying_[i] = false;
        } else {
            shown_[i] = cc_led_toward(from_[i], to_[i], cc_led_ease(elapsed, CCLed::decayMs));
        }
    }
    return shown_[i];
}

// PreviewLights._fade (section 5.7): buttons fade both ways over 220 ms. The
// fading flag keeps a finished fade from replaying after a 2^32 ms wrap.
void CCLightRenderer::fade(uint8_t i, uint32_t target, uint32_t now) {
    if (target != buttonTo_[i]) {
        buttonFrom_[i] = buttonShown_[i];
        buttonTo_[i] = target;
        buttonStart_[i] = now;
        buttonFading_[i] = true;
    }
    if (buttonFading_[i]) {
        const uint32_t elapsed = now - buttonStart_[i];
        if (elapsed >= CCLed::buttonFadeMs) {
            buttonShown_[i] = buttonTo_[i];
            buttonFading_[i] = false;
        } else {
            buttonShown_[i] = cc_led_toward(buttonFrom_[i], buttonTo_[i],
                                            cc_led_ease(elapsed, CCLed::buttonFadeMs));
        }
    }
}

// PreviewLights.render: feedback -> onsets -> target (with flash) -> ring
// damping -> button fade -> press highlight.
void CCLightRenderer::render(const CCFrame& frame, uint32_t /*controlId*/, uint32_t nowMs,
                             uint8_t pressedMask, uint32_t (&ring)[CC_RING_LEDS], uint32_t (&buttons)[4]) {
    const uint8_t flash = feedback(frame, nowMs);
    uint32_t pendingMs = 0, loadingMs = 0;
    onsets(frame, nowMs, pendingMs, loadingMs);
    cursor_ = cc_ring_target(frame, pendingMs, loadingMs, flash, cells_);
    for (uint8_t b = 0; b < 4; ++b) {
        const CCLedCell light = cc_button_light(frame, b);
        targets_[b] = cc_led_drive(light.rgb, light.level);
    }
    if (snap_) {                                         // renderer reset: everything snaps
        snap_ = false;
        for (uint8_t i = 0; i < kRingSize; ++i) {
            const uint32_t target = cc_led_drive(cells_[i].rgb, cells_[i].level);
            shown_[i] = from_[i] = to_[i] = target;
            start_[i] = nowMs;
            decaying_[i] = false;
            ring[i] = target;
        }
        for (uint8_t b = 0; b < 4; ++b) {
            buttonShown_[b] = buttonFrom_[b] = buttonTo_[b] = targets_[b];
            buttonStart_[b] = nowMs;
            buttonFading_[b] = false;
        }
    } else {
        for (uint8_t i = 0; i < kRingSize; ++i)
            ring[i] = damp(i, cc_led_drive(cells_[i].rgb, cells_[i].level), nowMs);
        for (uint8_t b = 0; b < 4; ++b) fade(b, targets_[b], nowMs);
    }
    for (uint8_t b = 0; b < 4; ++b) buttons[b] = press(frame, b, pressedMask, buttonShown_[b]);
}
