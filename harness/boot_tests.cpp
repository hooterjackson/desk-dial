// Host tests for the HMI boot / input paths (boot_pins_tests.py builds and runs this, MSVC /W4 /WX).
// The firmware statements under test are cut verbatim from src/hmi_thread.cpp into build/boot-tests/stubs/*.inc
// and compiled here against fakes of what they call; nothing below re-implements them.
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <vector>

#include "Arduino.h"
#include "hmi_api.h"
#include "led_api.h"

// ---- fakes: TinyUSB CDC, session, FOC words, NVS ---------------------------------------------------------------
static bool fake_cdc_open = false;
static bool fake_claimed = false;
static bool fake_wanted = false;
static int32_t fake_steps = 0;
static int fake_store_calls = 0;
static bool tud_cdc_n_connected(uint8_t) { return fake_cdc_open; }
static bool cc_claimed() { return fake_claimed; }
static int32_t cc_offline_steps() { return fake_steps; }
static void cc_offline_wanted_set(bool on) { fake_wanted = on; }
struct DeviceSettings {
    static DeviceSettings& getInstance() { static DeviceSettings s; return s; }
    void storeHostSeen() { ++fake_store_calls; }
    uint16_t deviceOrientation = 1;
};
#define CC_OFFLINE_VOLUME 1

// ---- the HMI's offline volume state and functions (verbatim) ----------------------------------------------------
#include "offline_state.inc"
static void offline_update(uint32_t now)
#include "offline_update.inc"
static void offline_arm_on_claim()
#include "offline_arm_on_claim.inc"

// ---- fakes: AceButton events, TinyUSB HID, MIDI, the COM task ----------------------------------------------------
struct AceButton {
    static const uint8_t kEventPressed = 0;
    static const uint8_t kEventReleased = 1;
    static const uint8_t kEventLongPressed = 4;
};
enum { RID_KEYBOARD = 1, RID_MOUSE = 2, RID_GAMEPAD = 3, RID_CONSUMER = 4 };
struct hid_gamepad_report_t { int8_t x, y, z, rz, rx, ry; uint8_t hat; uint32_t buttons; };
struct FakeUsbDevice {
    bool is_suspended = false;
    int wakeups = 0;
    bool suspended() { return is_suspended; }
    void remoteWakeup() { ++wakeups; }
} TinyUSBDevice;
struct FakeHid {
    int keyboard_reports = 0;
    uint8_t last_codes[6] = {0};
    bool last_was_release = false;
    uint8_t last_mouse = 0;
    uint32_t last_pad = 0;
    bool is_ready = true;
    std::vector<uint16_t> consumer;   // every Consumer report TinyUSB accepted (0 = release)
    int fail_consumer = 0;            // refuse the next N Consumer reports
    bool ready() { return is_ready; }
    bool sendReport16(uint8_t, uint16_t usage) {
        if (fail_consumer > 0) { --fail_consumer; return false; }
        consumer.push_back(usage); return true;
    }
    bool keyboardReport(uint8_t, uint8_t, const uint8_t codes[6]) {
        ++keyboard_reports; memcpy(last_codes, codes, 6); last_was_release = false; return true;
    }
    bool keyboardRelease(uint8_t) { ++keyboard_reports; memset(last_codes, 0, 6); last_was_release = true; return true; }
    bool mouseButtonPress(uint8_t, uint8_t buttons) { last_mouse = buttons; return true; }
    bool sendReport(uint8_t, const void* report, size_t) {
        last_pad = static_cast<const hid_gamepad_report_t*>(report)->buttons; return true;
    }
} usb_hid;
static int fake_hid_retries = 0;
static void cc_diag_hid_retry() { ++fake_hid_retries; }
struct FakeMidi {
    int sends = 0;
    uint8_t last_value = 0;
    void sendControlChange(uint8_t, uint8_t value, uint8_t) { ++sends; last_value = value; }
} midiu, midi2;
enum StringMessageType { STRING_MESSAGE_DEBUG, STRING_MESSAGE_ERROR, STRING_MESSAGE_MOTOR, STRING_MESSAGE_PROFILE,
                         STRING_MESSAGE_NEXT_PROFILE, STRING_MESSAGE_PREV_PROFILE };
struct StringMessage {
    StringMessage(String* m = nullptr, StringMessageType t = STRING_MESSAGE_DEBUG) : message(m), type(t) {}
    String* message;
    StringMessageType type;
};
static int fake_profile_requests = 0;
struct FakeCom {
    bool global_sleep_flag = false;
    void put_string_message(StringMessage& msg) { ++fake_profile_requests; delete msg.message; }
} com_thread;
// FastLED / Arduino / FOC: what nativeLeds() reads and the brightness it sets.
#define NANO_LED_A_NUM 60
struct CRGB {
    enum { Black = 0x000000, Red = 0xFF0000, Green = 0x00FF00, Blue = 0x0000FF };
    uint32_t rgb = 0;
    CRGB(uint32_t c = 0) : rgb(c) {}
};
struct FakeFastLED {
    int sets = 0;
    uint8_t brightness = 255;
    void setBrightness(uint8_t b) { brightness = b; ++sets; }
} FastLED;
static long map(long x, long in_min, long in_max, long out_min, long out_max) {
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}
template <typename T> static T min(T a, T b) { return b < a ? b : a; }
// SimpleFOC's foc_utils.h macro, as updateValue() uses it.
#ifndef _constrain
#define _constrain(amt,low,high) ((amt)<(low)?(low):((amt)>(high)?(high):(amt)))
#endif
struct FakeFoc {
    uint16_t cur_pos = 10;
    float get_motor_angle() { return 0.0f; }
    uint16_t pass_cur_pos() { return cur_pos; }
    uint16_t pass_start_pos() { return 0; }
    uint16_t pass_end_pos() { return 66; }
} foc_thread;
struct midiSettings { bool in = true, out = true, thru = false, route = false, nano = true; };
// FreeRTOS mutex: never contended in this single-threaded test.
typedef int SemaphoreHandle_t;
const int pdTRUE = 1;
static int xSemaphoreTake(SemaphoreHandle_t, int) { return pdTRUE; }
static void xSemaphoreGive(SemaphoreHandle_t) {}

// ---- a stand-in of HmiThread: its members, with the firmware's methods cut in verbatim ---------------------------
class HmiThread {
public:
    uint8_t num_key_codes = 0;
    uint8_t last_num_key_codes = 0;
    uint8_t current_key_codes[6] = {0};
    uint8_t last_key_codes[6] = {0};
    uint8_t keyState = 0;
    uint8_t current_mouse_buttons = 0;
    uint8_t last_mouse_buttons = 0;
    uint8_t current_pad_buttons = 0;
    uint8_t last_pad_buttons = 0;
    uint32_t cc_f24_release_at = 0;
    bool cc_was_claimed = false;
    hmiConfig hmi_config;
    midiSettings midiUsbSettings, midi2Settings;
    void handleKeyAction(keyAction& action, uint8_t eventType);
    void handleHid();
    void handleConsumer();
    float lastValue = -1;
    float currentValue = 0;
    void updateValue();
    void offlineTick(uint32_t now);
    void releaseHeldHid();
    SemaphoreHandle_t _hmi_config_mutex = 0;
    hmiConfig _pending_hmi_config;
    volatile bool _hmi_config_pending = false;
    void receiveHmiConfig();
    uint8_t led_max_brightness = 100;
    ledConfig led_config;
    int idle_frames = 0;
    CRGB leds[NANO_LED_A_NUM];   // the native ring (hmi_thread.h)
    int key_led_passes = 0;
    void nativeLeds();
    void nativeKeyLeds() { ++key_led_passes; }
    void halvesPointer(int, int, int, int, const CRGB&, const CRGB&, const CRGB&) {}
    void IdleLeds(int, const CRGB&, const CRGB&, const CRGB&) { ++idle_frames; }
    // run()'s claim / release edge, verbatim.
    void claimEdge(bool claimed) {
        if (claimed != cc_was_claimed)
#include "claim_edge.inc"
    }
} hmi_thread;
void HmiThread::handleKeyAction(keyAction& action, uint8_t eventType)
#include "handle_key_action.inc"
void HmiThread::handleHid()
#include "handle_hid.inc"
void HmiThread::offlineTick(uint32_t now)
#include "offline_tick.inc"
void HmiThread::handleConsumer()
#include "handle_consumer.inc"
void HmiThread::releaseHeldHid()
#include "release_held_hid.inc"
void HmiThread::receiveHmiConfig()
#include "receive_hmi_config.inc"
void HmiThread::nativeLeds()
#include "native_leds.inc"
// updateValue() clamps the knob's angle with expression statements whose result it does not use (C4552 / C4555).
#pragma warning(push)
#pragma warning(disable: 4552 4555)
void HmiThread::updateValue()
#include "update_value.inc"
#pragma warning(pop)

// The native (unclaimed) branch of HmiThreadButtonHandler::handleEvent: its key-action switch, verbatim.
static void native_event(uint8_t index, uint8_t eventType) {
#include "native_switch.inc"
}

static int failures = 0;
static void check(bool condition, const char* what) {
    printf("%s %s\n", condition ? "PASS" : "FAIL", what);
    if (!condition) ++failures;
}

// Every HMI pass for `ms` milliseconds (10 ms passes), the port closed.
static void passes(uint32_t& now, uint32_t ms) {
    for (uint32_t end = now + ms; now < end; now += 10) offline_update(now);
}

// FW-BUG-013 offline_volume_respects_setting: never claimed -> CDC closed 10 s, the mode stays off (the native
// profile's updateValue() and key actions run: both are gated on offline_now alone, pinned as source rules).
static void offline_volume_respects_setting() {
    offline_armed = false; offline_now = false; cdc_primed = false; fake_store_calls = 0;
    fake_cdc_open = false; fake_claimed = false;
    uint32_t now = 1000;
    passes(now, 10000);
    check(!offline_now && !fake_wanted, "FW-BUG-013: never claimed, port closed 10 s: offline volume stays off");

    // Desk Dial claims once: armed (one NVS write), and after the release + 2 s closed the mode runs.
    HmiThread hmi;
    fake_cdc_open = true; fake_claimed = true;
    offline_update(now); hmi.claimEdge(true);
    check(offline_armed && fake_store_calls == 1, "FW-BUG-013: the first claim arms it and writes host_seen once");
    fake_claimed = false; hmi.claimEdge(false);
    fake_claimed = true; hmi.claimEdge(true);
    fake_claimed = false; hmi.claimEdge(false);
    check(fake_store_calls == 1, "FW-BUG-013: later claims write nothing");
    fake_cdc_open = false;
    passes(now, 1990);
    check(!offline_now, "FW-BUG-013: armed, closed < 2 s: still off");
    passes(now, 30);
    check(offline_now && fake_wanted, "FW-BUG-013: armed, closed >= 2 s: offline volume on");

    // A reboot of an armed knob (host_seen loaded true): on after 2 s closed with no claim this boot.
    offline_armed = true; offline_now = false; cdc_primed = false; fake_store_calls = 0;
    passes(now, 2100);
    check(offline_now && fake_store_calls == 0, "FW-BUG-013: host_seen from NVS arms it at boot, no write");
}

// Up to six passes of handleHid() (one report per pass), as the HMI loop runs them.
static void hid_passes() { for (int i = 0; i < 6; ++i) hmi_thread.handleHid(); }

static keyAction key_action(uint8_t code) {
    keyAction a; a.type = KA_KEY; a.hid.num = 1; memset(a.hid.key_codes, 0, sizeof(a.hid.key_codes));
    a.hid.key_codes[0] = code; return a;
}

// FW-BUG-014 offline_edge_releases_held_key: a KA_KEY held while a host had the port open, the port closes, 2 s
// later the offline volume starts with the key still held: the PC gets the empty keyboard report (no auto-repeat),
// and the release that follows changes nothing.
static void offline_edge_releases_held_key() {
    hmi_thread = HmiThread();
    usb_hid = FakeHid();
    hmi_thread.hmi_config.keys[1].num_pressed_actions = 1;
    hmi_thread.hmi_config.keys[1].pressed[0] = key_action(0x2A);
    hmi_thread.hmi_config.keys[2].num_pressed_actions = 1;
    hmi_thread.hmi_config.keys[2].pressed[0].type = KA_MOUSE;
    hmi_thread.hmi_config.keys[2].pressed[0].mouse.buttons = 0x1;
    offline_armed = true; offline_now = false; cdc_primed = false;
    fake_cdc_open = true; fake_claimed = false;
    uint32_t now = 50000;
    hmi_thread.offlineTick(now);
    native_event(1, AceButton::kEventPressed);
    native_event(2, AceButton::kEventPressed);
    hid_passes();
    check(usb_hid.last_codes[0] == 0x2A && usb_hid.last_mouse == 0x1, "FW-BUG-014: key and mouse button down on the PC");
    fake_cdc_open = false;
    for (uint32_t end = now + 2100; now < end; now += 10) { hmi_thread.offlineTick(now); hmi_thread.handleHid(); }
    check(offline_now, "FW-BUG-014: offline volume on with the buttons still held");
    check(hmi_thread.num_key_codes == 0 && usb_hid.last_was_release && usb_hid.last_codes[0] == 0,
          "FW-BUG-014: entering it sent the empty keyboard report");
    check(usb_hid.last_mouse == 0, "FW-BUG-014: and the mouse button up");
    const int reports = usb_hid.keyboard_reports;
    native_event(1, AceButton::kEventReleased);
    native_event(2, AceButton::kEventReleased);
    hid_passes();
    check(usb_hid.keyboard_reports == reports && hmi_thread.keyState == 0,
          "FW-BUG-014: the release offline sends nothing more");
}

static keyAction typed_action(keyActionType type, uint8_t buttons) {
    keyAction a; a.type = type;
    if (type == KA_MOUSE) a.mouse.buttons = buttons; else a.pad.buttons = buttons;
    return a;
}

// FW-BUG-015 release_after_profile_switch_clears_pressed_codes: hold B (Backspace, 42), C (mouse 0x2) and D
// (gamepad 0x1), tap A (next profile); the new profile maps B to code 4, C to mouse 0x4 and D to pad 0x8. Letting go
// of B, C, D after the switch leaves nothing down on the PC.
static void release_after_profile_switch_clears_pressed_codes() {
    hmi_thread = HmiThread();
    usb_hid = FakeHid();
    offline_armed = false; offline_now = false;
    hmiConfig& old_cfg = hmi_thread.hmi_config;
    old_cfg.keys[0].num_pressed_actions = 1;
    old_cfg.keys[0].pressed[0].type = KA_PROFILE_NEXT;
    old_cfg.keys[1].num_pressed_actions = 1;
    old_cfg.keys[1].pressed[0] = key_action(42);
    old_cfg.keys[2].num_pressed_actions = 1;
    old_cfg.keys[2].pressed[0] = typed_action(KA_MOUSE, 0x2);
    old_cfg.keys[3].num_pressed_actions = 1;
    old_cfg.keys[3].pressed[0] = typed_action(KA_GAMEPAD, 0x1);
    fake_profile_requests = 0;
    native_event(1, AceButton::kEventPressed);
    native_event(2, AceButton::kEventPressed);
    native_event(3, AceButton::kEventPressed);
    native_event(0, AceButton::kEventPressed);
    native_event(0, AceButton::kEventReleased);
    hid_passes();
    check(usb_hid.last_codes[0] == 42 && usb_hid.last_mouse == 0x2 && usb_hid.last_pad == 0x1 &&
          fake_profile_requests == 1, "FW-BUG-015: B, C, D held on the PC, next profile requested");
    // The COM task hands over the next profile (put_hmi_config()); the HMI takes it on its next pass.
    hmiConfig next;
    next.keys[1].num_pressed_actions = 1;
    next.keys[1].pressed[0] = key_action(4);
    next.keys[2].num_pressed_actions = 1;
    next.keys[2].pressed[0] = typed_action(KA_MOUSE, 0x4);
    next.keys[3].num_pressed_actions = 1;
    next.keys[3].pressed[0] = typed_action(KA_GAMEPAD, 0x8);
    hmi_thread._pending_hmi_config = next;
    hmi_thread._hmi_config_pending = true;
    hmi_thread.receiveHmiConfig();
    check(!hmi_thread._hmi_config_pending && hmi_thread.hmi_config.keys[1].pressed[0].hid.key_codes[0] == 4,
          "FW-BUG-015: the new profile is taken");
    native_event(1, AceButton::kEventReleased);
    native_event(2, AceButton::kEventReleased);
    native_event(3, AceButton::kEventReleased);
    hid_passes();
    check(hmi_thread.num_key_codes == 0 && hmi_thread.current_key_codes[0] == 0 && usb_hid.last_was_release,
          "FW-BUG-015: release after the switch: no key code held, the PC got the empty keyboard report");
    check(hmi_thread.current_mouse_buttons == 0 && usb_hid.last_mouse == 0, "FW-BUG-015: no mouse button held");
    check(hmi_thread.current_pad_buttons == 0 && usb_hid.last_pad == 0, "FW-BUG-015: no gamepad button held");
    // The new profile works from a clean slate: B now presses code 4 and lets it go.
    native_event(1, AceButton::kEventPressed);
    hid_passes();
    check(usb_hid.last_codes[0] == 4 && hmi_thread.num_key_codes == 1, "FW-BUG-015: the new B presses code 4");
    native_event(1, AceButton::kEventReleased);
    hid_passes();
    check(hmi_thread.num_key_codes == 0 && usb_hid.last_was_release, "FW-BUG-015: and releases it");
}

// FW-BUG-040 empty_keycodes_sends_nothing: a configurator clears button 1's binding (keyCodes []): the profile
// parser sets hid.num 0 and leaves key_codes[0] (the old key). A press then sends nothing; a combo binding presses
// and releases every one of its hid.num codes.
static void empty_keycodes_sends_nothing() {
    hmi_thread = HmiThread();
    usb_hid = FakeHid();
    offline_armed = false; offline_now = false;
    hmi_thread.hmi_config.keys[1].num_pressed_actions = 1;
    hmi_thread.hmi_config.keys[1].pressed[0] = key_action(0x2A);
    native_event(1, AceButton::kEventPressed);
    hid_passes();
    check(usb_hid.last_codes[0] == 0x2A && hmi_thread.num_key_codes == 1, "FW-BUG-040: control: the bound key presses");
    native_event(1, AceButton::kEventReleased);
    hid_passes();
    check(hmi_thread.num_key_codes == 0 && usb_hid.last_was_release, "FW-BUG-040: control: and releases");
    // keyCodes [] as keyActionFromJSON stores it: num 0, the stale code still in key_codes[0].
    hmi_thread.hmi_config.keys[1].pressed[0].hid.num = 0;
    const int reports = usb_hid.keyboard_reports;
    native_event(1, AceButton::kEventPressed);
    hid_passes();
    check(hmi_thread.num_key_codes == 0 && hmi_thread.current_key_codes[0] == 0 && usb_hid.keyboard_reports == reports,
          "FW-BUG-040: emptied keyCodes: the press holds no key code and sends no report");
    native_event(1, AceButton::kEventReleased);
    hid_passes();
    check(hmi_thread.num_key_codes == 0 && usb_hid.keyboard_reports == reports, "FW-BUG-040: and the release none");
    // A combo (Left Ctrl + C): both codes down in one report, both up on release.
    keyAction combo = key_action(0xE0);
    combo.hid.num = 2; combo.hid.key_codes[1] = 0x06;
    hmi_thread.hmi_config.keys[2].num_pressed_actions = 1;
    hmi_thread.hmi_config.keys[2].pressed[0] = combo;
    native_event(2, AceButton::kEventPressed);
    hid_passes();
    check(hmi_thread.num_key_codes == 2 && usb_hid.last_codes[0] == 0xE0 && usb_hid.last_codes[1] == 0x06,
          "FW-BUG-040: a two-code binding presses both codes");
    native_event(2, AceButton::kEventReleased);
    hid_passes();
    check(hmi_thread.num_key_codes == 0 && usb_hid.last_was_release, "FW-BUG-040: and releases both");
    // A count beyond MAX_KEY_KEYCODES (a stale union byte) reads at most MAX_KEY_KEYCODES codes; code 0 is skipped.
    keyAction wide = key_action(0x04);
    wide.hid.num = 200;
    hmi_thread.hmi_config.keys[2].pressed[0] = wide;
    native_event(2, AceButton::kEventPressed);
    check(hmi_thread.num_key_codes == 1 && hmi_thread.current_key_codes[0] == 0x04,
          "FW-BUG-040: an oversized count reads only the codes array, zero codes skipped");
    native_event(2, AceButton::kEventReleased);
    check(hmi_thread.num_key_codes == 0, "FW-BUG-040: and releases it");
}

// FW-BUG-041 midi_value_is_monotonic_over_full_range: a native MIDI profile in VERNIER mode (endPos 127, vernier 5)
// reports positions 0..635. The CC value never decreases while turning up and ends at 127 (it used to wrap to 0
// every 256 positions); turning back down from the top brings it down again.
static void midi_value_is_monotonic_over_full_range() {
    hmi_thread = HmiThread();
    midiu = FakeMidi(); midi2 = FakeMidi();
    hmi_thread.keyState = 0;
    hmi_thread.hmi_config.knob.num = 1;
    knobValue& v = hmi_thread.hmi_config.knob.values[0];
    v.key_state = 0; v.type = KV_MIDI; v.value_min = 0; v.value_max = 127; v.angle_min = 0; v.angle_max = 1;
    v.step = 0; v.midi.channel = 1; v.midi.cc = 7; v.midi.val = 0;
    bool monotonic = true, in_range = true;
    int previous = -1;
    for (uint16_t pos = 0; pos <= 635; ++pos) {
        foc_thread.cur_pos = pos;
        hmi_thread.updateValue();
        const int sent = midiu.last_value;
        if (sent < previous) monotonic = false;
        if (sent > 127) in_range = false;
        previous = sent;
    }
    check(monotonic, "FW-BUG-041: positions 0..635: the MIDI value never decreases while turning up");
    check(in_range && midiu.last_value == 127 && midi2.last_value == 127, "FW-BUG-041: it ends at 127 (USB and DIN)");
    foc_thread.cur_pos = 300; hmi_thread.updateValue();
    check(midiu.last_value == 127, "FW-BUG-041: position 300 (wrapped to 44 before) sends 127");
    foc_thread.cur_pos = 64; hmi_thread.updateValue();
    check(midiu.last_value == 64, "FW-BUG-041: back to position 64 sends 64");
    foc_thread.cur_pos = 0; hmi_thread.updateValue();
    check(midiu.last_value == 0, "FW-BUG-041: position 0 sends 0");
    foc_thread.cur_pos = 10;
}

// FW-TST-012 offline_volume_tests: handleConsumer() (verbatim) over the HMI loop's passes: every Volume Up / Down
// report is followed by exactly one 0 report, also across a USB suspend / resume and an offline -> online edge;
// steps queued beyond 20 are dropped; a refused report is retried on the next pass and sent once; never a wake.
static bool consumer_paired(const std::vector<uint16_t>& reports) {
    for (size_t i = 0; i < reports.size(); ++i) {
        if (reports[i] != 0 && (i + 1 >= reports.size() || reports[i + 1] != 0)) return false;   // press, then 0
        if (reports[i] == 0 && (i == 0 || reports[i - 1] == 0)) return false;                    // 0 only after a press
    }
    return true;
}
static int consumer_count(const std::vector<uint16_t>& reports, uint16_t usage) {
    int n = 0;
    for (uint16_t r : reports) n += r == usage;
    return n;
}
static void consumer_passes(int n) { for (int i = 0; i < n; ++i) hmi_thread.handleHid(); }

static void offline_volume_tests() {
    hmi_thread = HmiThread();
    usb_hid = FakeHid();
    TinyUSBDevice = FakeUsbDevice();
    fake_hid_retries = 0;
    offline_now = true; consumer_down = false; fake_steps = 100; offline_steps_seen = 100;
    const uint16_t up = kUsageVolumeUp, down = kUsageVolumeDown;

    fake_steps += 3;
    consumer_passes(10);
    check(usb_hid.consumer == std::vector<uint16_t>({up, 0, up, 0, up, 0}),
          "FW-TST-012: three steps up: Volume Up, 0, three times");
    fake_steps -= 2;
    consumer_passes(10);
    check(consumer_count(usb_hid.consumer, down) == 2 && consumer_paired(usb_hid.consumer),
          "FW-TST-012: two steps down: two Volume Down presses, each released");

    // A press goes out, the PC suspends before the next pass: the release is the first report after the resume,
    // the steps turned while suspended are dropped, and nothing wakes the PC.
    usb_hid.consumer.clear();
    fake_steps += 1;
    consumer_passes(1);
    check(usb_hid.consumer == std::vector<uint16_t>({up}) && consumer_down, "FW-TST-012: Volume Up sent, release due");
    TinyUSBDevice.is_suspended = true;
    fake_steps += 5;
    consumer_passes(5);
    check(usb_hid.consumer.size() == 1 && consumer_down, "FW-TST-012: suspended: nothing sent, the release kept");
    TinyUSBDevice.is_suspended = false;
    consumer_passes(1);
    check(usb_hid.consumer == std::vector<uint16_t>({up, 0}), "FW-TST-012: resumed: the 0 report goes out first");
    consumer_passes(10);
    check(usb_hid.consumer == std::vector<uint16_t>({up, 0}) && !consumer_down,
          "FW-TST-012: and the steps turned while suspended were dropped");

    // Offline -> online with a press out: the release still goes out, later steps send nothing.
    usb_hid.consumer.clear();
    fake_steps -= 1;
    consumer_passes(1);
    offline_now = false;
    fake_steps -= 4;
    consumer_passes(5);
    check(usb_hid.consumer == std::vector<uint16_t>({down, 0}) && !consumer_down,
          "FW-TST-012: going online releases the pending press and sends no more steps");
    offline_now = true;
    consumer_passes(5);
    check(usb_hid.consumer.size() == 2, "FW-TST-012: back offline: steps from the online time are not replayed");

    // A stalled poll: 50 steps queued, at most 20 are sent (either direction).
    usb_hid.consumer.clear();
    fake_steps += 50;
    consumer_passes(200);
    check(consumer_count(usb_hid.consumer, up) == 20 && consumer_paired(usb_hid.consumer),
          "FW-TST-012: +50 pending: clamped to 20 Volume Up presses, each released");
    usb_hid.consumer.clear();
    fake_steps -= 50;
    consumer_passes(200);
    check(consumer_count(usb_hid.consumer, down) == 20 && consumer_paired(usb_hid.consumer),
          "FW-TST-012: -50 pending: clamped to 20 Volume Down presses");

    // Refused sends (endpoint busy at the TinyUSB level): retried on the next pass, never duplicated.
    usb_hid.consumer.clear();
    fake_hid_retries = 0;
    fake_steps += 2;
    usb_hid.fail_consumer = 1;
    consumer_passes(1);
    check(usb_hid.consumer.empty() && fake_hid_retries == 1 && !consumer_down, "FW-TST-012: a refused press is counted");
    usb_hid.fail_consumer = 0;
    consumer_passes(1);
    usb_hid.fail_consumer = 1;
    consumer_passes(1);
    check(usb_hid.consumer == std::vector<uint16_t>({up}) && consumer_down && fake_hid_retries == 2,
          "FW-TST-012: retried press sent once; a refused release keeps it due");
    consumer_passes(10);
    check(usb_hid.consumer == std::vector<uint16_t>({up, 0, up, 0}), "FW-TST-012: the release and the second step follow");
    // Endpoint not ready: nothing is sent or lost.
    usb_hid.is_ready = false;
    fake_steps += 1;
    consumer_passes(3);
    check(usb_hid.consumer.size() == 4, "FW-TST-012: not ready: nothing sent");
    usb_hid.is_ready = true;
    consumer_passes(3);
    check(usb_hid.consumer.size() == 6 && consumer_paired(usb_hid.consumer), "FW-TST-012: ready again: the step goes out");
    check(TinyUSBDevice.wakeups == 0, "FW-TST-012: Consumer reports never wake the PC");
    offline_now = false; consumer_down = false;
}

// FW-BUG-012 native_brightness_follows_ledMaxBrightness: the native path's brightness never exceeds ledMaxBrightness,
// a settings-only change (handleSettings() stores led_max_brightness, the profile stays) lowers it on the next pass,
// and with a limit of 0 the idle animation stays dark.
static void native_brightness_follows_ledMaxBrightness() {
    hmi_thread = HmiThread();
    com_thread.global_sleep_flag = false;
    hmi_thread.led_config.led_brightness = 100;
    hmi_thread.led_max_brightness = 150;
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 100, "FW-BUG-012: profile 100 under limit 150: 100");
    hmi_thread.led_max_brightness = 20;   // settings only: same profile
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 20, "FW-BUG-012: limit lowered to 20: the next native pass shows 20");
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 20, "FW-BUG-012: and stays 20 (no reset to the profile's 100)");
    hmi_thread.led_max_brightness = 255;
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 100, "FW-BUG-012: limit raised: back to the profile's 100");
    com_thread.global_sleep_flag = true;
    hmi_thread.led_max_brightness = 150;
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 25 && hmi_thread.idle_frames == 1, "FW-BUG-012: idle animation at 25 under limit 150");
    hmi_thread.led_max_brightness = 10;
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 10, "FW-BUG-012: idle animation clamped to limit 10");
    hmi_thread.led_max_brightness = 0;
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 0, "FW-BUG-012: limit 0: the idle animation is dark");
    com_thread.global_sleep_flag = false;
    hmi_thread.nativeLeds();
    check(FastLED.brightness == 0, "FW-BUG-012: limit 0: the native pointer is dark");
}

// FW-BUG-039 native_leds_dark_when_ledEnable_false: the profile's ledEnable:false blanks the whole native ring and
// still runs the button-LED pass (which paints them black), awake or in the idle animation.
static void native_leds_dark_when_ledEnable_false() {
    for (int sleeping = 0; sleeping < 2; ++sleeping) {
        hmi_thread = HmiThread();
        com_thread.global_sleep_flag = sleeping != 0;
        for (int i = 0; i < NANO_LED_A_NUM; i++) hmi_thread.leds[i] = CRGB(CRGB::Red);
        hmi_thread.led_config.led_enable = false;
        hmi_thread.nativeLeds();
        bool dark = true;
        for (int i = 0; i < NANO_LED_A_NUM; i++) dark &= hmi_thread.leds[i].rgb == 0;
        check(dark, sleeping ? "FW-BUG-039: ledEnable false, idle: every ring LED is black"
                             : "FW-BUG-039: ledEnable false: every ring LED is black");
        check(hmi_thread.key_led_passes == 1 && hmi_thread.idle_frames == 0,
              "FW-BUG-039: ledEnable false: the button LED pass runs, no idle animation");
    }
    com_thread.global_sleep_flag = false;
}

// ---- FW-PUB-004: the reported firmware version (src/cc_fw_version.h, included as shipped) -------------------------
#define NANO_FIRMWARE_PUBLIC "2.0.0"
#define NANO_FIRMWARE_VERSION "1.0.0-cc5.8"
#define CC_BUILD_BINARY 6
#include "cc_fw_version.h"

static void firmware_version_is_public_and_names_the_binary() {
    char text[48];
    cc_fw_public_version(text, sizeof text, "2.0.0", "1.0.0-cc5.8", 6);
    check(strcmp(text, "2.0.0+cc5.8.F") == 0, "FW-PUB-004: public 2.0.0, build 1.0.0-cc5.8, binary F -> 2.0.0+cc5.8.F");
    cc_fw_public_version(text, sizeof text, "2.0.0", "1.0.0-cc5.8", 4);
    check(strcmp(text, "2.0.0+cc5.8.D") == 0, "FW-PUB-004: binary D reads differently from F (2.0.0+cc5.8.D)");
    cc_fw_public_version(text, sizeof text, "2.0.0", "1.0.0-cc5.8", 0);
    check(strcmp(text, "2.0.0+cc5.8") == 0, "FW-PUB-004: no ladder id: no letter");
    cc_fw_public_version(text, sizeof text, "2.0.0", "1.0.0-cc5.8", 7);
    check(strcmp(text, "2.0.0+cc5.8") == 0, "FW-PUB-004: an out-of-range binary adds no letter");
    check(strncmp(text, "2.0.0", 5) == 0 && strncmp(text, "cc", 2) != 0,
          "FW-PUB-004: the reported string starts with the public version, never an internal cc id");
    char small[8];
    cc_fw_public_version(small, sizeof small, "2.0.0", "1.0.0-cc5.8", 6);
    check(strcmp(small, "2.0.0+c") == 0, "FW-PUB-004: truncated, always terminated");
    check(strcmp(cc_fw_version(), "2.0.0+cc5.8.F") == 0 && cc_fw_version() == cc_fw_version(),
          "FW-PUB-004: cc_fw_version() composes the build macros once");
    check(strlen(cc_fw_version()) <= 40, "FW-PUB-004: fits Desk Dial's 40-character version field");
}

int main() {
    offline_volume_respects_setting();
    offline_edge_releases_held_key();
    release_after_profile_switch_clears_pressed_codes();
    native_brightness_follows_ledMaxBrightness();
    native_leds_dark_when_ledEnable_false();
    empty_keycodes_sends_nothing();
    midi_value_is_monotonic_over_full_range();
    offline_volume_tests();
    firmware_version_is_public_and_names_the_binary();
    printf("%s: boot_tests (%d failure%s)\n", failures ? "FAIL" : "PASS", failures, failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
