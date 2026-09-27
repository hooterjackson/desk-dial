#include "control_center.h"
#include "HapticProfileManager.h"
#include "cc_alive.h"
#include "cc_artwork.h"
#include "cc_diag.h"
#include "cc_frame_parse.h"
#include "cc_media.h"
#include "cc_serial_out.h"
#include "foc_thread.h"
#include <esp_heap_caps.h>
#include <cmath>
#include <cstring>

namespace {
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
// phase: idle, entering, ready, releasing. One mailbox; frames never touch FOC.
uint8_t phase = 0, windowsButton = 2;
bool windowsHidEnabled = true;
uint8_t buttonOrder[4] = {0,1,2,3}; // Physical left-to-right -> raw input/LED index.
uint32_t id = 0, version = 0, lease = 0, motorId = 0, hmiId = 0, lcdId = 0;
uint16_t appliedPosition = 0;
bool requestPending = false, expired = false, readyReply = false;
bool timeoutNotice = false;
// Presentation-change counter for the LCD's cheap peek (cc_presentation_state).
// Every change that cc_snapshot()/cc_timeout_notice() can observe goes through
// the helpers below, always under `lock`, so a peek never misses one.
uint32_t presentation = 0;
// Release robustness (1.0.0-cc5.2). A release completes when the motor, the LEDs (HMI)
// and the LCD have all acknowledged it. In 1.0.0-cc5.1 a hung HMI never acknowledged, the
// session stayed "releasing" for good and every new control was refused. Now, once the
// motor has restored the native profile (request taken and motorId 0), a presentation
// acknowledgement (HMI or LCD) still missing kReleaseAckMs after the release started is
// no longer waited for: the release completes with reason "forced" and names the
// subsystems that did not acknowledge. The motor acknowledgement is never overridden,
// so "released" always means the native haptics are back.
constexpr uint32_t kReleaseAckMs = 1000;
constexpr uint8_t kForcedHmi = 1, kForcedLcd = 2;
uint32_t releaseAt = 0;          // millis() when the current release started (phase 3)
uint32_t forcedReleases = 0;     // since boot ({"diag":"?"} forcedReleases)
uint8_t lastForced = 0;          // kForced* of the last forced release
CCControl request;
CCFrame frame;
// COM-thread parse target for control/frame commands (cc_handle_command runs
// only on the COM thread): a CCFrame never sits on the COM stack.
CCFrame incoming;
// artwork2 (1.0.0-cc5.3): the control ID the media upload context is bound to (COM thread).
// Whenever the active ID (entering/ready, else 0) differs, the upload is cancelled: a new
// control, a release and a lease expiry (which the FOC thread starts) all end it.
uint32_t mediaBoundId = 0;

// Resource margins for {"diag":"?"}. LVGL is not thread-safe, so the LCD
// thread samples its heap and its own stack; the HMI thread publishes its
// stack; the COM thread only reads these copies.
portMUX_TYPE diagLock = portMUX_INITIALIZER_UNLOCKED;
uint32_t diagLvglFree = 0, diagLvglMinFree = 0, diagStackLcd = 0, diagStackHmi = 0;

// "Warm · alive" LEDs (1.0.0-cc5.4, ALIVE.md). capabilities.alive (section 1): version 1, the
// HMI's render cadence (16 ms, hmi_thread.cpp) and the effective default drive, which the HMI
// task publishes (cc_alive_default_drive(): it owns ledMaxBrightness), so this unit needs no
// settings or engine code (media_tests.py links it on the host with stubs).
constexpr uint8_t kAliveVersion = 1;
constexpr uint8_t kAliveFps = 60;
volatile uint8_t aliveDefaultDrive = CCAliveSpec::defaultDrive;   // one byte: atomic
// Latched section 3 fields, under `lock` (control_center.h, CCAliveLatch).
CCAliveLatch aliveLatch;
// The knob -> host end-stop event (section 3): the HMI posts into this slot under `lock`, the
// COM task sends it from cc_service(). The spacing state is COM-only.
constexpr uint32_t kLimitSpacingMs = 150;
uint32_t limitId = 0;
int8_t limitDir = 0;
bool limitPending = false;
uint32_t limitSentAt = 0;        // COM: millis() of the last {"lim"} sent
bool limitSent = false;          // COM: one was sent since boot

// Presentation 5 input (PRESENTATION_V5 section 11; 1.0.0-cc5.4). The HMI publishes its key state
// on every change (cc_publish_key_state()); the ready line reads it as "ks" (11.3). One byte: atomic.
volatile uint8_t hmiKeyState = 0;
// COM only: the one deferred-hold slot (11.2 step 5; -1 = empty) and the diag counters (12.3):
// holdEvents = kh lines sent, holdDeferred = of which sent after a ready line.
int8_t pendingHold = -1;
uint32_t holdEvents = 0, holdDeferred = 0;
// COM only: enterMsLast / enterMsMax (12.3), a control accepted -> its ready line sent.
uint32_t enterAt = 0, enterMsLast = 0, enterMsMax = 0;
// Native button edges since boot (8.10; cc_native_button_edge()): written by the HMI task only,
// read by the LCD thread. One aligned word: atomic.
volatile uint32_t nativeButtonSeq = 0;

void set_phase(uint8_t next) { if (phase != next) { phase = next; ++presentation; } }
void set_timeout_notice(bool next) { if (timeoutNotice != next) { timeoutNotice = next; ++presentation; } }
void next_version() { ++version; ++presentation; }
// Called with `lock` held when a control or frame command is accepted (ALIVE.md section 3:
// latched on acceptance, stamped with the knob's millis()). Fields absent from the frame keep
// their latch; a frame without any of them changes nothing. `claim` (a control accepted while
// idle): reducedMotion first resets to false (PRESENTATION_V5 7.1, P5-R15), then the claiming
// frame's own value latches; ledPink / ledVolFull survive claims until reboot (7.3, P5-R27).
void latch_locked(const CCFrame& f, uint32_t now, bool claim) {
    const bool tuning = f.ledPinkPresent || f.ledVolFullPresent;
    if (!claim && !f.clockPresent && !f.progressPresent && !f.ledDrivePresent && !f.ledDitherPresent &&
        !f.reducedMotionPresent && !tuning) return;
    if (++aliveLatch.seq == 0) aliveLatch.seq = 1;           // 0 means "never latched"
    const uint32_t seq = aliveLatch.seq;
    if (f.clockPresent) {
        aliveLatch.clockSeq = seq; aliveLatch.clockMinute = f.clockMinute; aliveLatch.clockAt = now;
    }
    if (f.progressPresent) {
        aliveLatch.progressSeq = seq; aliveLatch.progressPos = f.progressPos; aliveLatch.progressDur = f.progressDur;
        aliveLatch.progressAt = now;
    }
    if (f.ledDrivePresent) { aliveLatch.ledDrivePresent = true; aliveLatch.ledDrive = f.ledDrive; }
    if (f.ledDitherPresent) { aliveLatch.ledDitherPresent = true; aliveLatch.ledDither = f.ledDither; }
    if (claim || f.reducedMotionPresent) {
        aliveLatch.motionSeq = seq; aliveLatch.reducedMotion = f.reducedMotionPresent && f.reducedMotion;
    }
    if (tuning) {
        aliveLatch.tuningSeq = seq;
        if (f.ledPinkPresent) { aliveLatch.ledPinkPresent = true; aliveLatch.ledPink = f.ledPink; }
        if (f.ledVolFullPresent) { aliveLatch.ledVolFullPresent = true; aliveLatch.ledVolFull = f.ledVolFull; }
    }
}
// With `lock` held, right after `frame = incoming`: the session frame carries the effective
// latched reducedMotion (control_center.h, cc_snapshot()), so the LCD and the LEDs read one value.
void apply_latched_locked() { frame.reducedMotion = aliveLatch.reducedMotion; }

// COM only: {"id":<id>,"ks":<mask>,"kh":<raw>} for a deferred hold (11.2 step 5).
void send_deferred_hold(uint32_t controlId, uint8_t mask, uint8_t raw) {
    JsonDocument out;
    out["id"] = controlId; out["ks"] = mask; out["kh"] = raw;
    cc_send_json(out);
    ++holdEvents; ++holdDeferred;
}

void reply_error(const char* message) {
    JsonDocument out;
    out["error"] = message;
    cc_send_json(out);
}

// Free stack of another task in bytes (ESP-IDF high-water mark), or -1.
int32_t stack_free(TaskHandle_t task) {
    return task ? static_cast<int32_t>(uxTaskGetStackHighWaterMark(task)) : -1;
}
void release_locked(bool timeout) {
    if (phase == 0 || phase == 3) return;
    if (timeout) set_timeout_notice(true);
    set_phase(3); expired = timeout; readyReply = false; request.release = true; request.id = 0;
    requestPending = true; next_version(); releaseAt = millis();
}
// The active control ID for media requests: the current ID while a session is entering or
// ready, otherwise 0. COM thread; takes the session lock.
uint32_t media_active_id() {
    portENTER_CRITICAL(&lock);
    const uint32_t active = (phase == 1 || phase == 2) ? id : 0;
    portEXIT_CRITICAL(&lock);
    return active;
}
// Cancels the media upload when the active control ID moved since the last check (never
// under the session spinlock: the media store has a mutex).
void media_sync(uint32_t active) {
    if (active == mediaBoundId) return;
    mediaBoundId = active;
    cc_media_cancel_upload();
}
void add_forced(JsonArray list, uint8_t forced) {
    if (forced & kForcedHmi) list.add("hmi");
    if (forced & kForcedLcd) list.add("lcd");
}
const char* phase_name(uint8_t value) {
    static constexpr const char* kPhases[] = {"idle", "entering", "ready", "releasing"};
    return value < 4 ? kPhases[value] : "?";
}
}

bool cc_handle_command(JsonDocument& doc) {
    if (doc["capabilities"].is<const char*>() && !strcmp(doc["capabilities"],"?")) {
        cc_crumb_com(CC_COM_OP_CAPABILITIES, CC_COM_STAGE_LINE, 0);
        JsonDocument out; auto c = out["capabilities"].to<JsonObject>();
        c["controlCenter"] = 1; c["leaseMs"] = 2000; c["hostFrame"] = 1;
        c["runtimeProfileBounds"] = 1; c["taggedInput"] = 1; c["windowsHidKey"] = "F24";
        c["buttonOrder"] = 1;
        c["windowsHidControl"] = 1;
        // 1.0.0-cc5.4: contract v5 (PRESENTATION_V5.md sections 1-2). presentation 5 implies the v5
        // frame fields and tokens, kh, ks in ready, hid on kd, the F24 icon gate and reducedMotion,
        // with no further key (no keyHoldMs, VOC-R17). A presentation-4 host (v6, tests >= 4) keeps
        // working: every presentation-4 frame is still accepted (2.3).
        c["presentation"] = 5;
        c["glyphs"] = "latin-ext-a";
        // 1.0.0-cc5.4 (ALIVE.md section 1): the "Warm · alive" LED engine; every other key is
        // unchanged (artwork2 stays right after artwork and right before diag). drive: the drive
        // the engine uses without a latched ledDrive, min(150, ledMaxBrightness) (section 9).
        auto alive = c["alive"].to<JsonObject>();
        alive["version"] = static_cast<unsigned>(kAliveVersion); alive["fps"] = static_cast<unsigned>(kAliveFps);
        alive["drive"] = static_cast<unsigned>(aliveDefaultDrive);
        auto art = c["artwork"].to<JsonObject>();
        art["version"] = 1; art["width"] = 120; art["height"] = 120;
        art["format"] = "RGB565_LE"; art["chunkBytes"] = 384; art["cacheEntries"] = 8;
        art["available"] = cc_art_available();
        art["composited"] = "scrim80";
        // 1.0.0-cc5.3 (ARTWORK2.md section 1): the sibling artwork2 object; every other key
        // above and below is unchanged. rxBytes is the receive queue only while it is in
        // internal RAM (0 when it landed in PSRAM, which keeps the host paced).
        cc_media_capability(c["artwork2"].to<JsonObject>(), cc_boot_rx_queue_internal_bytes());
        c["diag"] = 1;
        cc_send_json(out); return true;
    }
    if (doc["diag"].is<const char*>() && !strcmp(doc["diag"],"?")) {
        // Read-only; never renews the lease or touches the session.
        cc_crumb_com(CC_COM_OP_DIAG, CC_COM_STAGE_LINE, 0);
        uint32_t lvglFree, lvglMinFree, stackLcd, stackHmi;
        portENTER_CRITICAL(&diagLock);
        lvglFree = diagLvglFree; lvglMinFree = diagLvglMinFree; stackLcd = diagStackLcd; stackHmi = diagStackHmi;
        portEXIT_CRITICAL(&diagLock);
        JsonDocument out; auto d = out["diag"].to<JsonObject>();
        d["lvglFree"] = lvglFree; d["lvglMinFree"] = lvglMinFree;
        d["heapMinFree"] = static_cast<uint32_t>(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL));
        d["stackLcd"] = stackLcd;
        d["stackCom"] = static_cast<uint32_t>(uxTaskGetStackHighWaterMark(nullptr)); // bytes (ESP-IDF)
        d["stackHmi"] = stackHmi;
        // 1.0.0-cc5.1 (additive): FOC and TinyUSB task stacks, heaps, bounded
        // serial writes, then reboot detection and reset attribution (cc_diag.h).
        d["stackFoc"] = stack_free(foc_thread.getHandle());
        d["stackUsbd"] = stack_free(xTaskGetHandle("usbd"));
        d["heapFree"] = static_cast<uint32_t>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
        d["psramFree"] = static_cast<uint32_t>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        d["txStalls"] = cc_tx_stalls();
        d["txDroppedBytes"] = cc_tx_dropped_bytes();
        cc_diag_boot(d);
        // 1.0.0-cc5.2 (additive): per-task liveness and the task watchdog (cc_diag.h), the
        // session and release state, forced releases, and the LED transport (cc_led_rmt.h).
        cc_diag_live(d);
        uint8_t sessionPhase, forced; uint32_t pendingMs = 0, forcedCount;
        portENTER_CRITICAL(&lock);
        sessionPhase = phase; forced = lastForced; forcedCount = forcedReleases;
        if (phase == 3) pendingMs = static_cast<uint32_t>(millis() - releaseAt);
        portEXIT_CRITICAL(&lock);
        d["sessionPhase"] = phase_name(sessionPhase);
        d["releasePendingMs"] = pendingMs;
        d["forcedReleases"] = forcedCount;
        add_forced(d["lastForced"].to<JsonArray>(), forced);
        cc_led_diag(d);
        // 1.0.0-cc5.3 (additive, ARTWORK2.md section 8): receive queue size, media store
        // counters and the LCD's JPEG decode statistics.
        cc_diag_media(d);
        // 1.0.0-cc5.4 (additive, PRESENTATION_V5 12.3; COM-only values): control accepted -> ready
        // sent (ms), and the kh lines sent / of which deferred to just after a ready line (11.2).
        d["enterMsLast"] = enterMsLast; d["enterMsMax"] = enterMsMax;
        d["holdEvents"] = holdEvents; d["holdDeferred"] = holdDeferred;
        // The other twenty 12.3 fields (lcdFps ... stackArtDec): the LCD thread's counters, one
        // copy per reply (cc_diag.h). lcdDma / lcdPeriodMs / artAsync identify binary A, B or C (12.6).
        cc_diag_lcd_pipeline(d);
        cc_send_json(out); return true;
    }
    if (!doc["art"].isNull()) {
        uint32_t artId; char key[sizeof(frame.artKey)];
        portENTER_CRITICAL(&lock);
        artId = (phase == 1 || phase == 2) ? id : 0;
        memcpy(key,frame.artKey,sizeof(key));
        portEXIT_CRITICAL(&lock);
        cc_art_command(doc["art"],artId,key); return true;
    }
    if (doc.containsKey("media")) {
        // artwork2 (ARTWORK2.md section 4): exactly one mediaAck per media line, whatever the
        // value. Bound to the active control ID; never renews the lease.
        const uint32_t active = media_active_id();
        media_sync(active);
        cc_media_command(doc["media"], active); return true;
    }
    if (doc["release"].is<bool>() && doc["release"].as<bool>()) {
        cc_crumb_com(CC_COM_OP_RELEASE, CC_COM_STAGE_LINE, 0);
        portENTER_CRITICAL(&lock); bool idle = phase == 0; set_timeout_notice(false); release_locked(false); portEXIT_CRITICAL(&lock);
        media_sync(0);               // a release ends any media upload (ARTWORK2.md 4.4)
        pendingHold = -1;            // ... and clears a deferred hold (PRESENTATION_V5 11.2 step 5)
        if (idle) cc_send_line("{\"released\":true}");
        return true;
    }
    if (!doc["control"].isNull()) {
        JsonVariant c = doc["control"]; uint32_t newId = 0, lo = 0, hi = 0, pos = 0, wb = 0;
        cc_crumb_com(CC_COM_OP_CONTROL, CC_COM_STAGE_LINE, c["id"] | 0U);
        if (c.as<JsonObject>().containsKey("windowsHidEnabled") && !c["windowsHidEnabled"].is<bool>()) {
            reply_error("Windows HID enable must be a boolean"); return true;
        }
        const bool hidEnabled = c["windowsHidEnabled"] | true;
        uint8_t order[4] = {0,1,2,3};
        if (!c["buttonOrder"].isNull()) {
            JsonArray values = c["buttonOrder"].as<JsonArray>(); uint8_t seen = 0;
            if (values.size() != 4) { reply_error("Invalid button order"); return true; }
            for (size_t i = 0; i < 4; ++i) {
                uint32_t raw = 0;
                if (!cc_json_uint(values[i],0,3,raw) || (seen & (1 << raw))) { reply_error("Invalid button order"); return true; }
                order[i] = raw; seen |= 1 << raw;
            }
        }
        const char* name = c["profile"] | "";
        HapticProfile* preset = HapticProfileManager::getInstance()[String(name)];
        if (!cc_json_uint(c["id"],1,0x7FFFFFFF,newId) || !cc_json_uint(c["min"],0,0,lo) ||
            !cc_json_uint(c["max"],0,65535,hi) || !cc_json_uint(c["position"],lo,hi,pos) ||
            !cc_json_uint(c["windowsButton"],0,3,wb) || !preset || preset->hmi_config.knob.num == 0 ||
            !cc_parse_frame(c["frame"], incoming)) { reply_error("Invalid control or unknown existing profile"); return true; }
        DetentProfile selected = preset->hmi_config.knob.values[0].haptic;
        if (selected.mode != REGULAR || selected.kxForce || !selected.detent_count || !std::isfinite(selected.output_ramp)) {
            reply_error("Control center requires an existing regular non-progressive preset"); return true;
        }
        selected.start_pos = lo; selected.end_pos = hi;
        portENTER_CRITICAL(&lock);
        bool busy = phase == 3 || (phase && newId <= id);
        const bool claim = phase == 0;         // unclaimed -> claimed (not a re-entry)
        if (!busy) {
            set_timeout_notice(false);
            id = newId; windowsButton = wb; windowsHidEnabled = hidEnabled; frame = incoming; next_version();
            memcpy(buttonOrder,order,sizeof(buttonOrder));
            set_phase(1); readyReply = false; lease = millis(); motorId = hmiId = lcdId = 0;
            latch_locked(incoming, lease, claim);   // ALIVE.md section 3: latched on acceptance
            apply_latched_locked();
            request.release = false; request.id = id; request.profile = selected; request.position = pos; requestPending = true;
        }
        portEXIT_CRITICAL(&lock);
        if (busy) { reply_error("Control ID must advance; wait for release before reconnecting"); return true; }
        enterAt = millis();                  // PRESENTATION_V5 12.3 enterMs: accepted -> ready sent
        if (claim) pendingHold = -1;         // a new claim clears a deferred hold (11.2 step 5)
        // artwork2: a new control ends any media upload, and its frame's keys pin their slots.
        cc_media_cancel_upload();
        mediaBoundId = newId;
        cc_media_frame_keys(incoming.artKey, incoming.iconKey);
        return true;
    }
    if (!doc["frame"].isNull()) {
        JsonVariant f = doc["frame"]; uint32_t frameId = 0;
        cc_crumb_com(CC_COM_OP_FRAME, CC_COM_STAGE_LINE, f["id"] | 0U);
        if (!cc_json_uint(f["id"],1,0x7FFFFFFF,frameId) || !cc_parse_frame(f,incoming)) {
            reply_error("Invalid control frame"); return true;
        }
        portENTER_CRITICAL(&lock);
        bool accepted = (phase == 1 || phase == 2) && frameId == id;
        if (accepted) {
            frame = incoming; next_version(); lease = millis(); latch_locked(incoming, lease, false);
            apply_latched_locked();
        }
        portEXIT_CRITICAL(&lock);
        if (!accepted) { reply_error("Stale control frame"); return true; }
        cc_media_frame_keys(incoming.artKey, incoming.iconKey);   // artwork2 pins (ARTWORK2.md 4.4)
        return true;
    }
    // Read-only inventory remains available; prohibit persistent/native mutation during a claim.
    if (cc_claimed() && (!doc["updates"].isNull() || !doc["current"].isNull() || !doc["save"].isNull() ||
        !doc["load"].isNull() || !doc["R"].isNull() || !doc["recalibrate"].isNull() ||
        doc["profiles"].is<JsonArray>() || doc["settings"].is<JsonObject>())) {
        reply_error("Release control center before changing device configuration"); return true;
    }
    return false;
}
bool cc_claimed() { portENTER_CRITICAL(&lock); bool v = phase != 0; portEXIT_CRITICAL(&lock); return v; }
bool cc_timeout_notice() { portENTER_CRITICAL(&lock); bool v = phase == 0 && timeoutNotice; portEXIT_CRITICAL(&lock); return v; }
uint32_t cc_input_id() { portENTER_CRITICAL(&lock); uint32_t v = phase == 2 && !readyReply ? id : 0; portEXIT_CRITICAL(&lock); return v; }
bool cc_snapshot(CCFrame& f, uint32_t& outId, uint32_t& outVersion, uint8_t& wb) {
    portENTER_CRITICAL(&lock); bool active = phase == 1 || phase == 2;
    if (active) { f = frame; outId = id; outVersion = version; wb = windowsButton; }
    portEXIT_CRITICAL(&lock); return active;
}
uint32_t cc_presentation_state() {
    portENTER_CRITICAL(&lock); uint32_t v = presentation; portEXIT_CRITICAL(&lock);
    // The counters only increase, so their sum changes whenever any of them does
    // (artwork2 commits included, 1.0.0-cc5.3).
    return v + cc_art_version() + cc_media_version();
}
bool cc_take_request(CCControl& result) {
    cc_live_foc();   // FOC calls this once per loop: its liveness stamp (focAgeMs)
    portENTER_CRITICAL(&lock);
    if ((phase == 1 || phase == 2) && (uint32_t)(millis() - lease) >= 2000) release_locked(true);
    bool available = requestPending;
    if (available) { result = request; requestPending = false; }
    portEXIT_CRITICAL(&lock); return available;
}
void cc_motor_applied(uint32_t v, uint16_t p) { portENTER_CRITICAL(&lock); motorId = v; appliedPosition = p; portEXIT_CRITICAL(&lock); }
bool cc_can_arm(uint32_t v) {
    portENTER_CRITICAL(&lock); bool result = phase == 1 && id == v && motorId == v && hmiId == v && lcdId == v;
    portEXIT_CRITICAL(&lock); return result;
}
void cc_motor_ready(uint32_t v, uint16_t p) {
    portENTER_CRITICAL(&lock);
    if (phase == 1 && id == v && motorId == v && hmiId == v && lcdId == v) {
        set_phase(2); appliedPosition = p; readyReply = true;
    }
    portEXIT_CRITICAL(&lock);
}
void cc_hmi_applied(uint32_t v) { portENTER_CRITICAL(&lock); hmiId = v; portEXIT_CRITICAL(&lock); }
void cc_lcd_applied(uint32_t v) { portENTER_CRITICAL(&lock); lcdId = v; portEXIT_CRITICAL(&lock); }
uint8_t cc_physical_button(uint8_t raw) {
    portENTER_CRITICAL(&lock); uint8_t physical = 0;
    for (uint8_t i = 0; i < 4; ++i) if (buttonOrder[i] == raw) physical = i;
    portEXIT_CRITICAL(&lock); return physical;
}
bool cc_is_windows_button(uint8_t i) {
    portENTER_CRITICAL(&lock); uint8_t physical = 0;
    for (uint8_t p = 0; p < 4; ++p) if (buttonOrder[p] == i) physical = p;
    // PRESENTATION_V5 11.4: cc5.4 adds the icon gate (F24 only while that slot shows `win`; a
    // legacy frame without icons derives it from the label, cc_button_icon()).
    bool v = phase == 2 && !readyReply && windowsHidEnabled && i == windowsButton && frame.buttons[physical].enabled &&
             cc_button_icon(frame.buttons[physical]) == CC_ICON_WIN;
    portEXIT_CRITICAL(&lock); return v;
}
void cc_service() {
    uint32_t ready = 0; uint16_t position = 0; bool released = false, timeout = false; uint8_t forced = 0;
    uint32_t limit = 0; int8_t limitDirection = 0;
    // A lease expiry (FOC thread) or a completed release changed the active control ID:
    // end the media upload before the next line is handled (COM thread).
    media_sync(media_active_id());
    portENTER_CRITICAL(&lock);
    // PRESENTATION_V5 11.2 step 5: a release (a release command, or a lease expiry the FOC thread
    // started) clears a deferred hold; so does a session that is no longer claimed.
    if (phase == 0 || phase == 3) pendingHold = -1;
    if (readyReply && phase == 2) { readyReply = false; ready = id; position = appliedPosition; }
    // ALIVE.md section 3: an end-stop push is sent only while its control is the ready one (the
    // ready reply, if due, goes out first, below); any other posted push is dropped.
    if (limitPending) {
        limitPending = false;
        if (phase == 2 && limitId == id) { limit = limitId; limitDirection = limitDir; }
    }
    // The motor's acknowledgement is always required (the native profile is restored).
    if (phase == 3 && !requestPending && motorId == 0) {
        if (hmiId == 0 && lcdId == 0) {
            set_phase(0); id = 0; released = true; timeout = expired;
        } else if (static_cast<uint32_t>(millis() - releaseAt) >= kReleaseAckMs) {
            forced = (hmiId ? kForcedHmi : 0) | (lcdId ? kForcedLcd : 0);
            hmiId = lcdId = 0;   // a new control zeroes them too; cc_can_arm needs fresh acks
            set_phase(0); id = 0; released = true; timeout = expired;
            ++forcedReleases; lastForced = forced;
        }
    }
    portEXIT_CRITICAL(&lock);
    if (ready) {
        // PRESENTATION_V5 11.1 / 11.3: "ks", the raw buttons down as the line is built.
        const uint8_t mask = hmiKeyState;
        JsonDocument out; out["ready"] = ready; out["p"] = position; out["ks"] = mask; cc_send_json(out);
        const uint32_t took = static_cast<uint32_t>(millis() - enterAt);       // 12.3 enterMs
        enterMsLast = took;
        if (took > enterMsMax) enterMsMax = took;
        // 11.2 step 5: a hold that matured while entering follows the ready line with its id, if
        // that raw is still down; the slot clears either way (at most one kh per press).
        if (pendingHold >= 0) {
            const uint8_t raw = static_cast<uint8_t>(pendingHold);
            pendingHold = -1;
            if (mask & (1u << raw)) send_deferred_hold(ready, mask, raw);
        }
    }
    if (limit) {
        const uint32_t now = millis();
        if (!limitSent || static_cast<uint32_t>(now - limitSentAt) >= kLimitSpacingMs) {
            JsonDocument out; out["id"] = limit; out["lim"] = static_cast<int>(limitDirection); cc_send_json(out);
            limitSent = true; limitSentAt = now;
        }
    }
    if (released) {
        JsonDocument out; out["released"] = true;
        if (forced) {
            out["reason"] = "forced";
            add_forced(out["unacked"].to<JsonArray>(), forced);
            if (timeout) out["leaseExpired"] = true;
        } else if (timeout) {
            out["reason"] = "lease-expired";
        }
        cc_send_json(out);
    }
}
void cc_diag_lcd(uint32_t lvglFree, uint32_t lvglMinFree, uint32_t stackLcd) {
    portENTER_CRITICAL(&diagLock);
    diagLvglFree = lvglFree; diagLvglMinFree = lvglMinFree; diagStackLcd = stackLcd;
    portEXIT_CRITICAL(&diagLock);
}
void cc_diag_hmi(uint32_t stackHmi) {
    portENTER_CRITICAL(&diagLock); diagStackHmi = stackHmi; portEXIT_CRITICAL(&diagLock);
}
void cc_alive_default_drive(uint8_t drive) { aliveDefaultDrive = drive; }
bool cc_alive_latch(CCAliveLatch& out, uint32_t seen) {
    portENTER_CRITICAL(&lock);
    const bool moved = aliveLatch.seq != seen;
    if (moved) out = aliveLatch;
    portEXIT_CRITICAL(&lock);
    return moved;
}
void cc_post_limit(uint32_t v, int8_t dir) {
    if (!v || (dir != 1 && dir != -1)) return;
    portENTER_CRITICAL(&lock); limitId = v; limitDir = dir; limitPending = true; portEXIT_CRITICAL(&lock);
}
void cc_publish_key_state(uint8_t mask) { hmiKeyState = static_cast<uint8_t>(mask & 0x0F); }
void cc_hold_deferred(uint8_t raw) {
    if (raw > 3) return;
    portENTER_CRITICAL(&lock);
    const uint8_t phaseNow = phase; const bool due = readyReply; const uint32_t current = id;
    portEXIT_CRITICAL(&lock);
    // Entering, or ready with the ready line still due: the next ready line carries it (cc_service).
    if (phaseNow == 1 || (phaseNow == 2 && due)) { pendingHold = static_cast<int8_t>(raw); return; }
    // The ready line already went (it was sent between the long press and this COM pass): the hold
    // follows it now, with that ready's id, if the raw is still down.
    if (phaseNow == 2 && current) {
        const uint8_t mask = hmiKeyState;
        if (mask & (1u << raw)) send_deferred_hold(current, mask, raw);
    }
    // Idle or releasing: dropped.
}
void cc_hold_key_up(uint8_t raw) { if (pendingHold == static_cast<int8_t>(raw)) pendingHold = -1; }
void cc_hold_sent() { ++holdEvents; }
void cc_native_button_edge() { nativeButtonSeq = nativeButtonSeq + 1u; }   // single writer (HMI)
uint32_t cc_native_button_seq() { return nativeButtonSeq; }
