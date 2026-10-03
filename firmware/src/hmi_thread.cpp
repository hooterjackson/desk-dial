#include "hmi_thread.h"
#include "com_thread.h"
#include "foc_thread.h"
#include <Adafruit_TinyUSB.h>
#include "MIDI.h"
#include "audio/audio.h"
#include <SparkFun_STUSB4500.h>
#include "control_center.h"
#include "cc_lights.h"
#include "cc_alive.h"
#include "cc_diag.h"
#include "cc_led_rmt.h"
#include "cc_sleep.h"
#include "cc_haptic_fx.h"

// TinyUSB (Arduino-ESP32 core): the DTR test USBCDC::write() itself uses.
extern "C" bool tud_cdc_n_connected(uint8_t itf);

namespace {
// HMI task stack (1.0.0-cc5.1). The static worst case was the queued-config
// path: run -> receiveHmiConfig (a ~2.9 KB hmiConfig local) -> hmiConfig copy
// -> String -> realloc -> heap lock, about 3.7 KB of calls, 4.25 KB with the
// task entry, coprocessor save area and one interrupt frame. 1.0.0-cc5 had
// 4608 B (628 B free measured). 9216 B keeps more than 2x that worst case.
// The hmiConfig handoff no longer uses a queue (put_hmi_config()), so that
// local is gone and the worst case only got smaller; the size is unchanged.
constexpr uint32_t kHmiStackBytes = 9216;
// Key bit and LED pair of raw button i (native colours and host slots alike).
constexpr uint8_t kKeyBits[4] = {0x1, 0x2, 0x4, 0x8};
constexpr uint8_t kKeyLedPairs[4][2] = {{3, 4}, {2, 5}, {1, 6}, {0, 7}};
// LED state. All of this is HMI-thread state, static so it never sits on the HMI stack.
// 1.0.0-cc5.4: the "Warm - alive" engine (cc_alive.h, ALIVE.md) draws the LEDs while a control
// is claimed and in the unclaimed offline state. The contract-v4 renderer (CCLightRenderer,
// cc_render_buttons) is no longer used here: cc_lights.cpp stays compiled, frozen at v4, for its
// geometry helpers (cc_ring_address) and light_tests.py; every button LED of a claim, the pass
// it starts in included (updateKeyLeds()), is the engine's.
CCAlive alive;                          // the engine: ~12 KB of .bss, never on the stack
uint32_t cc_light_ring[CC_RING_LEDS];   // section 9 output 0xRRGGBB per logical segment (0 = twelve o'clock, clockwise)
uint32_t cc_light_buttons[4];           // section 9 output per slot (physical left-to-right)
bool cc_lights_active = false;          // a claimed control's frame owned the LEDs on the previous pass
uint8_t alive_mode = CC_LED_MODE_OFFLINE;   // CCLedMode (cc_diag.h): who draws the LEDs now
// Cadence (ALIVE.md 10.1, revision 2): render and show on a deadline, nextShowDue += 16, 17, 17
// repeating (exactly 60.0 fps), with dt from the real millis(); a frame more than one period late
// resynchronises (nextShowDue = now) instead of catching up. The loop sleeps
// clamp(next show - now, 1, 10) ms, so every other step still runs at least every 10 ms.
constexpr uint8_t kAliveFrameSteps[3] = {16, 17, 17};
constexpr uint32_t kLoopDelayMaxMs = 10;
uint32_t alive_next_show = 0;           // millis() the next frame is due
uint8_t alive_frame_step = 0;           // index into kAliveFrameSteps of the next advance
// Native handover (8.1, [M29]): native input while unclaimed hands the LEDs to the native path
// until the next claim; the engine never takes them back on its own (no 5 s return, no reveal).
bool native_button = false;             // the unclaimed button handler saw a press or a release
bool native_primed = false;             // native_pos holds a position read while idle
uint16_t native_pos = 0;
// Local input of the ready control (6.2, 6.3), sampled every pass while claimed (cc_alive.h).
// Reset on every claim and release and whenever a pass has no ready control, so its first
// sample after any of those only seeds (a control id reused across sessions is never compared).
CCAliveKnob alive_knob;
// Latched host fields (section 3), copied from control_center.cpp when their seq moves; [r2]
// reducedMotion (PRESENTATION_V5 7.1, reset at every claim) and the LED tuning (7.3, until reboot).
CCAliveLatch alive_latch;
uint32_t latch_seen = 0, latch_clock = 0, latch_progress = 0, latch_motion = 0, latch_tuning = 0;
// PRESENTATION_V5 11.2 (VOC 2.5 hold_ms): AceButton's long-press delay, the firmware-only hold timer.
constexpr uint16_t kHoldMs = 600;
// Desk Dial r3.1: every other physical slot's hold (kh) matures after 1000 ms (hold 4 = the secondary action;
// buttons 2 and 3 alike). Each raw's delay is set from its physical slot at its press (the buttonOrder in force
// then), so slot 0 keeps kHoldMs.
constexpr uint16_t kHoldOtherMs = 1000;
// Host-frame snapshot for updateLeds()/updateKeyLeds(). Both run only on the
// HMI thread and never nest.
CCFrame cc_hmi_frame;
uint32_t cc_hmi_frame_id = 0;
// Inactivity sleep (cc_sleep.h): the presses that woke the knob, swallowed with their long press
// and release. HMI thread only (AceButton calls the handlers from check() on this thread).
CCSleepButtons sleep_buttons;
// r4 hold.tension (1.0.0-cc5.7, plan F2; cc_haptic_fx.h): the raw whose press started the tension (-1 = none).
int8_t hold_tension_raw = -1;
// r4 offline system volume (1.0.0-cc5.7, plan F3; HAPTICS.md "Offline volume"): the CDC port's state and since
// when it has been closed, the FOC step count already reported, and a Consumer usage down that needs its release.
bool cdc_primed = false, cdc_was_open = false;
uint32_t cdc_closed_at = 0;
int32_t offline_steps_seen = 0;
bool consumer_down = false;
constexpr uint32_t kOfflineAfterMs = 2000;     // "active only after the CDC port has been closed >= 2 s"
constexpr int32_t kOfflinePendingMax = 20;      // steps queued beyond this are dropped (a stalled host poll)
constexpr uint16_t kUsageVolumeUp = 0x00E9, kUsageVolumeDown = 0x00EA;   // HID Consumer page
bool offline_now = false;                       // the mode as the HMI last decided it (key / value suppression)
// FW-BUG-013: the offline volume arms only on a knob a Desk Dial host has claimed at least once (NVS "host_seen",
// loaded in init(), set at the first claim). Until then the native profile (MIDI CC, keys) keeps the knob and the
// buttons with the port closed, exactly as before the offline volume existed.
bool offline_armed = false;

// Every HMI pass: the offline volume mode is wanted while no host has the CDC port open (DTR) for 2 s and no
// control is claimed, on an armed knob; the FOC task switches its profile, this task sends the Consumer reports
// (handleHid()).
void offline_update(uint32_t now) {
    const bool open = tud_cdc_n_connected(0);
    if (!cdc_primed || open != cdc_was_open) {
        cdc_primed = true; cdc_was_open = open;
        if (!open) cdc_closed_at = now;
    }
    const bool wanted = CC_OFFLINE_VOLUME && offline_armed && !open && !cc_claimed() &&
                        static_cast<uint32_t>(now - cdc_closed_at) >= kOfflineAfterMs;
    if (wanted && !offline_now) offline_steps_seen = cc_offline_steps();   // nothing from before counts
    offline_now = wanted;
    cc_offline_wanted_set(wanted);
}

// FW-BUG-013: a claim proves a Desk Dial host; the first one on this knob arms the offline volume for good (one
// NVS write per knob, never again once the flag is set).
void offline_arm_on_claim() {
    if (offline_armed) return;
    offline_armed = true;
    DeviceSettings::getInstance().storeHostSeen();
}

// Refreshes cc_hmi_frame only when the presentation state moved (1.0.0-cc5.2), exactly
// like the LCD thread's render_host_frame(): the counter changes with every frame, control
// and artwork version and every phase transition, and is read before the copy, so an
// unchanged value means the cached snapshot is what cc_snapshot() would return. Before,
// the 1040-byte CCFrame was copied under the session spinlock (interrupts masked on this
// core, FOC spinning on the other) on every 10 ms pass. What the LEDs render is unchanged.
bool hmi_snapshot(uint32_t& id) {
    static uint32_t seen = 0, version = 0;
    static uint8_t windowsButton = 0;
    static bool primed = false, active = false;
    const uint32_t state = cc_presentation_state();
    if (!primed || state != seen) {
        active = cc_snapshot(cc_hmi_frame, cc_hmi_frame_id, version, windowsButton);
        seen = state; primed = true;
    }
    id = cc_hmi_frame_id;
    return active;
}

// LED transport (1.0.0-cc5.2, cc_led_rmt.h): FastLED keeps show(), brightness and the
// pixel pipeline; these controllers replace only FastLED's clockless RMT driver, whose
// unbounded wait hung this task in 1.0.0-cc5.1. Same pins, colour orders and RMT channels
// (ring: channel 0, buttons: channel 2, two memory blocks each) as FastLED used.
CCRmtStrip ringStrip("ring", RMT_CHANNEL_0, static_cast<gpio_num_t>(PIN_LED_A), CC_HMI_STEP_SHOW_RING);
CCRmtStrip buttonStrip("buttons", RMT_CHANNEL_2, static_cast<gpio_num_t>(PIN_LED_B), CC_HMI_STEP_SHOW_BUTTONS);
CCLedController<RGB, NANO_LED_A_NUM> ringLeds(ringStrip);
CCLedController<LED_COL_ORDER, NANO_LED_B_NUM> buttonLeds(buttonStrip);

// ALIVE.md 6.2 / 6.3, every pass while claimed: the FOC position of the READY control
// (cc_input_id(), the id the p events carry). A detent is a position change of the same control
// between two passes of one ready interval; a new id (a host re-enter), and any sample after a
// pass without a ready control, a claim or a release, only seeds (CCAliveKnob). [Q1] (12.5) A
// limit fires on EVERY push into a bound: the pass samples `pushing` through the read-only FOC
// accessor pass_limit_push() (atLimit && the attractor moved past the bound), and CCAliveKnob
// applies the rising edge, the lim_rearm_ms (75 ms) hold-off and the 150 ms gap; dir -1 at
// position 0 and +1 at max. It goes to the engine and, as {"id","lim"}, to the COM task
// (cc_post_limit()).
void alive_sample_knob(uint32_t now) {
    const uint32_t input = cc_input_id();
    if (!input) { alive_knob.reset(); return; }
    const uint16_t pos = foc_thread.pass_cur_pos();
    const bool pushing = foc_thread.pass_limit_push();
    const uint16_t max = foc_thread.pass_end_pos();
    // A new control or a release that began during the reads may have rebased the FOC (it
    // takes the request only after the phase left ready): the samples are this control's only
    // if it is still the ready one after them.
    if (cc_input_id() != input) { alive_knob.reset(); return; }
    const CCAliveKnobEvents events = alive_knob.sample(now, input, pos, pushing, max);
    if (events.delta) alive.detent(now, events.delta);
    if (events.limit) {
        alive.limit(now, events.limit);
        cc_post_limit(input, events.limit);
    }
}

// ALIVE.md 8.1 native input while unclaimed: an FOC position change between two idle passes,
// or a button press/release seen by the unclaimed handler. Positions are compared only between
// passes that saw the session idle before and after the read: a claim's FOC rebase happens only
// after the phase left idle, and a release's rebase completes before the phase returns to idle.
bool alive_native_input() {
    const bool button = native_button;
    native_button = false;
    if (cc_claimed()) { native_primed = false; return false; }
    const uint16_t pos = foc_thread.pass_cur_pos();
    if (cc_claimed()) { native_primed = false; return false; }
    const bool moved = native_primed && pos != native_pos;
    native_pos = pos;
    native_primed = true;
    return moved || button;
}

// Best-effort text line from the HMI task (1.0.0-cc5.2): written only when the USB
// transmit buffer has room for all of it now, otherwise dropped. USBCDC::write() spins
// while that buffer is full, which would freeze the LEDs and buttons (and trip the task
// watchdog) behind a host that keeps the port open but stops reading.
void hmi_note(const char* text) {
    const size_t length = strlen(text);
    if (tud_cdc_n_connected(0) && Serial.availableForWrite() >= static_cast<int>(length + 2)) Serial.println(text);
}
}

// FW-DES-007: the native value screen's PC volume view (cc_display.cpp cc_native_pc_volume_attach(), bound by
// ui_valueScreen.c) polls this from the LCD thread: the offline volume mode as this task last decided it (the
// cross-task word offline_update() writes) and the FOC's running step count (+ up / - down), both single-writer
// 32-bit words, so the LCD thread reads them without a lock.
extern "C" bool hmi_pc_volume_source(int32_t* steps) {
    *steps = cc_offline_steps();
    return cc_offline_wanted();
}

using namespace ace_button;

Adafruit_USBD_MIDI usb_midi(1);

MIDI_CREATE_INSTANCE(Adafruit_USBD_MIDI, usb_midi, midiu);
MIDI_CREATE_INSTANCE(HardwareSerial, Serial2, midi2)

enum {
  RID_KEYBOARD = 1,
  RID_MOUSE = 2,
  RID_GAMEPAD = 3,
  RID_CONSUMER = 4,   // 1.0.0-cc5.7 (plan F3): the offline system volume, appended (report IDs 1..3 unchanged)
};


uint8_t const desc_hid_report[] = {
  TUD_HID_REPORT_DESC_KEYBOARD( HID_REPORT_ID(RID_KEYBOARD) ),
  TUD_HID_REPORT_DESC_MOUSE   ( HID_REPORT_ID(RID_MOUSE) ),
  TUD_HID_REPORT_DESC_GAMEPAD( HID_REPORT_ID(RID_GAMEPAD) ),
#if CC_OFFLINE_VOLUME
  TUD_HID_REPORT_DESC_CONSUMER( HID_REPORT_ID(RID_CONSUMER) )
#endif
};

// USB HID object
Adafruit_USBD_HID usb_hid;

#define ARRAY_SIZE(arr) (sizeof(arr) / sizeof((arr)[0]))

// Hmi thread controls LED via FastLed and buttons via AceButton

HmiThread::HmiThread(const uint8_t task_core ) : Thread("HMI", kHmiStackBytes, 1, task_core) {
    _q_config_in = xQueueCreate(2, sizeof( ledConfig ));
    _hmi_config_mutex = xSemaphoreCreateMutex();
    _q_settings_in = xQueueCreate(2, sizeof( HmiDeviceSettings ));
    // 1.0.0-cc5.5 (F1): 16 key events (was 5), so a burst of presses, releases and holds while the COM
    // task is busy (a media upload, a flash write) is not dropped. A dropped key-up is still healed on the
    // host by the clear-only `ks` of the next position line (com_thread.cpp handleEvents()).
    _q_keyevt_out = xQueueCreate(16, sizeof( KeyEvt ));
}

HmiThread::~HmiThread() {}



void midi_sysex_handler(byte* array, unsigned size) {
    hmi_thread.handleSysex(array, size);
};


// init_usb() must be called before the thread is started
// 1.0.0-cc5.5 (F1, after Karl Malota's idf_upgrade branch): the MIDI and HID interfaces report whether
// TinyUSB accepted them. A refusal is recorded for {"diag":"?"} (usbMidiOk / usbHidOk, cc_diag.h) and
// boot continues: nothing here retries or waits, so a USB setup failure never hangs setup().
void HmiThread::init_usb() {
  usb_midi.setStringDescriptor("Nano_D MIDI");
  midiu.setHandleSystemExclusive(midi_sysex_handler);
  const bool midiOk = usb_midi.begin();
  midiu.begin();

  usb_hid.setBootProtocol(HID_ITF_PROTOCOL_NONE);
  usb_hid.setPollInterval(2);
  usb_hid.setReportDescriptor(desc_hid_report, sizeof(desc_hid_report));
  usb_hid.setStringDescriptor("Nano_D HID");
  const bool hidOk = usb_hid.begin();
  cc_boot_usb(midiOk, hidOk);
};


// init must be called before the thread is started
void HmiThread::init(ledConfig& initial_led_config, hmiConfig& initial_hmi_config) {
    led_config = initial_led_config;
    hmi_config = initial_hmi_config;
    led_max_brightness =  DeviceSettings::getInstance().ledMaxBrightness;
    uint8_t b = min(led_max_brightness, led_config.led_brightness);
    FastLED.setBrightness(b);
    midi_sysex_id = DeviceSettings::getInstance().midi_sysex_id;
    offline_armed = DeviceSettings::getInstance().loadHostSeen();   // FW-BUG-013 (setup(), before the threads)
    midiUsbSettings = DeviceSettings::getInstance().midiUsb;
    midi2Settings = DeviceSettings::getInstance().midi2;
    Serial2.begin(31250, SERIAL_8N1, PIN_SERIAL2_RX, PIN_SERIAL2_TX);
    midi2.setHandleSystemExclusive(midi_sysex_handler);  
    midi2.begin();
    audioPlayer.audio_init();
};



void HmiThread::put_led_config(ledConfig& new_config) {
    xQueueSend(_q_config_in, &new_config, (TickType_t)0);
};


// Runs on the COM thread. A real String copy, so the slot owns its buffers and
// the profile keeps its own. Replaces a config the HMI has not taken yet.
void HmiThread::put_hmi_config(hmiConfig& new_config){
    xSemaphoreTake(_hmi_config_mutex, portMAX_DELAY);
    _pending_hmi_config = new_config;
    _hmi_config_pending = true;
    xSemaphoreGive(_hmi_config_mutex);
};


void HmiThread::put_settings(HmiDeviceSettings& new_settings){
    xQueueSend(_q_settings_in, &new_settings, (TickType_t)0);
};


// Runs every 10 ms pass. Only this thread takes from the LED config queue and
// the hmiConfig slot, so a waiting config is always taken below (the slot on a
// later pass if COM is mid-copy). The receivers are out of line: before
// 1.0.0-cc5.1 this function default-constructed a ledConfig and an hmiConfig
// (a String per key action, ~2.9 KB of frame) on every pass.
void HmiThread::handleConfig() {
    if (uxQueueMessagesWaiting(_q_config_in)) receiveLedConfig();
    if (_hmi_config_pending) receiveHmiConfig();
};


void HmiThread::receiveLedConfig() {
    ledConfig newConfig;
    if (xQueueReceive(_q_config_in, &newConfig, (TickType_t)0)) {
        led_config = newConfig;
        uint8_t newBrightness = min(led_max_brightness, led_config.led_brightness);
        if (FastLED.getBrightness() != newBrightness) {
            FastLED.setBrightness(newBrightness);
        }
        updateKeyLeds();
    }
};


// Never waits: if COM holds the mutex mid-copy, the next pass takes the config.
void HmiThread::receiveHmiConfig() {
    if (xSemaphoreTake(_hmi_config_mutex, 0) != pdTRUE) return;
    const bool taken = _hmi_config_pending;
    if (taken) {
        hmi_config = _pending_hmi_config;
        _hmi_config_pending = false;
    }
    xSemaphoreGive(_hmi_config_mutex);
    // FW-BUG-015: a button's release walks the NEW config's actions, which never remove what the old config's press
    // added (hold B = Backspace, tap A = next profile, let go of B: Backspace stays down and the PC auto-repeats it).
    // Whatever the old config holds down is let go now; the new one starts with nothing pressed.
    if (taken) releaseHeldHid();
};


void HmiThread::handleSettings() {
    HmiDeviceSettings newSettings;
    if (xQueueReceive(_q_settings_in, &newSettings, (TickType_t)0)) {
        midiUsbSettings = newSettings.midiUsb;
        midi2Settings = newSettings.midi2;
        midiu.setThruFilterMode(midiUsbSettings.thru? midi::Thru::Full : midi::Thru::Off);
        midiu.setInputChannel(midiUsbSettings.in? MIDI_CHANNEL_OMNI : MIDI_CHANNEL_OFF);
        midi2.setThruFilterMode(midi2Settings.thru? midi::Thru::Full : midi::Thru::Off);
        midi2.setInputChannel(midi2Settings.in? MIDI_CHANNEL_OMNI : MIDI_CHANNEL_OFF);
        led_max_brightness = newSettings.ledMaxBrightness;
        uint8_t newBrightness = min(newSettings.ledMaxBrightness, led_config.led_brightness);
        if (FastLED.getBrightness() != newBrightness) {
            FastLED.setBrightness(newBrightness);
            updateKeyLeds();
        }
        midi_sysex_id = newSettings.midi_sysex_id;
        hmi_note("Hmi settings updated from global settings");
    }
};


bool HmiThread::get_key_event(KeyEvt* keyEvt){
    return xQueueReceive(_q_keyevt_out, keyEvt, (TickType_t)0);
};




void HmiThread::run() {
    // Task watchdog (1.0.0-cc5.2, cc_diag.h): fed once per pass at the wait step below.
    cc_wdt_watch(CC_LIVE_HMI);
    // Was FastLED.addLeds<LED_CHIPSET (WS2811), PIN, ORDER>(...): the same strips, pins,
    // orders and LED counts, sent by the bounded RMT transport. Registering them here
    // installs both RMT channels from this task, so the driver's interrupt is on core 0.
    FastLED.addLeds(&ringLeds, leds, NANO_LED_A_NUM);
    FastLED.addLeds(&buttonLeds, ledsp, NANO_LED_B_NUM);
    FastLED.setBrightness( DEFAULT_LED_MAX_BRIGHTNESS );
    pinMode(PIN_BTN_A, INPUT_PULLUP);
    pinMode(PIN_BTN_B, INPUT_PULLUP);
    pinMode(PIN_BTN_C, INPUT_PULLUP);
    pinMode(PIN_BTN_D, INPUT_PULLUP);
    buttons[0] = new AceButton(new ButtonConfig(), PIN_BTN_A);
    buttons[1] = new AceButton(new ButtonConfig(), PIN_BTN_B);
    buttons[2] = new AceButton(new ButtonConfig(), PIN_BTN_C);
    buttons[3] = new AceButton(new ButtonConfig(), PIN_BTN_D);
    for (int i = 0; i < 4; i++) {
        button_handler[i] = HmiThreadButtonHandler(i);
        buttons[i]->getButtonConfig()->setIEventHandler(&button_handler[i]);
        buttons[i]->getButtonConfig()->setClickDelay(50);
        buttons[i]->getButtonConfig()->clearFeature(ButtonConfig::kFeatureDoubleClick);
        // 1.0.0-cc5.4, PRESENTATION_V5 11.2 step 1: kEventLongPressed 600 ms after the debounced press,
        // once per press. No suppression (kEventReleased still follows, so keyState stays right)
        // and no repeat. The claimed branch turns it into a kh; the native branch ignores it.
        // [r3.1] handleEvent re-sets the delay at every press: kHoldMs on physical slot 0, else kHoldOtherMs.
        buttons[i]->getButtonConfig()->setFeature(ButtonConfig::kFeatureLongPress);
        buttons[i]->getButtonConfig()->setLongPressDelay(kHoldMs);
    }
    nativeKeyLeds();
    // ALIVE.md 8.1: power-up is the engine's offline state with a reveal (the static engine was
    // built with reset(0); this restarts it on the real clock, so its first frame has dt 0).
    alive.reset(millis());
    alive_mode = CC_LED_MODE_OFFLINE;
    alive_next_show = millis();
    alive_frame_step = 0;

    unsigned long total = 0;
    unsigned long updates = 0;
    unsigned long ts = micros();

    // 1.0.0-cc5.7 (plan F3): no boot chime (the knob is silent until a host asks for sounds).
    while (1) {
        cc_crumb_hmi(CC_HMI_STEP_CONFIG);
        handleSettings();
        handleConfig();
        cc_sleep_tick();                  // inactivity timer: awake -> dim -> asleep (cc_sleep.h)
        offlineTick(static_cast<uint32_t>(millis()));   // r4: the offline system volume mode (plan F3)
        bool claimed = cc_claimed();
        if (claimed != cc_was_claimed) {
            releaseHeldHid();
            if (claimed) offline_arm_on_claim();   // FW-BUG-013: a Desk Dial host has run on this knob
            // 1.0.0-cc5.4: FastLED's dither mode is chosen per frame below (engine frames:
            // DISABLE_DITHER; native frames: BINARY_DITHER as before).
            cc_was_claimed = claimed;
        }
        if (!claimed) handleMidi();
        cc_crumb_hmi(CC_HMI_STEP_BUTTONS);
        for (int i = 0; i < 4; i++)
            buttons[i]->check();
        if (!claimed && !offline_now) updateValue();   // r4 offline volume: the profile's knob value is suppressed
        cc_crumb_hmi(CC_HMI_STEP_HID);
        if (cc_f24_release_at && (int32_t)(millis() - cc_f24_release_at) >= 0) {
            num_key_codes = 0; memset(current_key_codes,0,sizeof(current_key_codes)); cc_f24_release_at = 0;
        }
        handleHid();       
        cc_crumb_hmi(CC_HMI_STEP_LEDS);
        updateLeds();
        unsigned long currentMillis = millis();
        const int32_t late = static_cast<int32_t>(static_cast<uint32_t>(currentMillis) - alive_next_show);
        if (late >= 0) {
            // A frame is due (ALIVE.md 10.1 deadline cadence). More than one period late (a long
            // pass): resynchronise instead of catching up. While the engine owns the LEDs it
            // renders now, with dt from the real millis(); the native path drew during updateLeds().
            if (late > static_cast<int32_t>(kAliveFrameSteps[alive_frame_step])) alive_next_show = static_cast<uint32_t>(currentMillis);
            const bool engine = alive_mode != CC_LED_MODE_NATIVE;
            uint32_t renderUs = 0;
            if (engine) {
                renderUs = renderAlive(static_cast<uint32_t>(currentMillis));
                // Section 9 step 5: leds/ledsp hold the final bytes q. At brightness 255, with the
                // colour correction and temperature at FastLED's uncorrected defaults, FastLED
                // 3.6.0 scales each byte by scale8(q, 255) == q (FASTLED_SCALE8_FIXED), and with
                // its binary dithering disabled nothing is added, so the wire carries q exactly
                // (harness/led_wire_tests.py). The engine's own quantisation (section 9
                // step 4: dither off with the F-T floor by default, its temporal dither only on a
                // latched ledDither:true) replaces FastLED's.
                FastLED.setBrightness(255);
                FastLED.setDither(DISABLE_DITHER);
            } else {
                cc_led_id = 0;
                FastLED.setDither(BINARY_DITHER);   // the native path's frames as in 1.0.0-cc5.3
            }
            // Inactivity sleep (cc_sleep.h): every ring and button LED off. The engine (or the
            // native path) keeps running underneath, so a wake shows its current frame again.
            if (cc_sleep_state() == CC_SLEEP_ASLEEP) {
                fill_solid(leds, NANO_LED_A_NUM, CRGB::Black);
                fill_solid(ledsp, NANO_LED_B_NUM, CRGB::Black);
            }
            // Bounded since 1.0.0-cc5.2 (cc_led_rmt.h): the strips' crumbs (show-ring,
            // show-buttons, led-recover) follow this one, and a failed transmit is recovered
            // and counted, never waited for.
            cc_crumb_hmi(CC_HMI_STEP_SHOW);
            FastLED.show();
            // The show's own time: cc_diag's ledShowGapMsMax / ledLateShows measure show to show.
            const uint32_t shownAt = static_cast<uint32_t>(millis());
            cc_hmi_applied(cc_led_id);
            cc_diag_led_frame(shownAt, alive_mode, engine, renderUs);
            alive_next_show += kAliveFrameSteps[alive_frame_step];
            alive_frame_step = static_cast<uint8_t>((alive_frame_step + 1) % 3);
        }
        static unsigned long diagMillis = 0;
        static bool diagPublished = false;
        if (!diagPublished || currentMillis - diagMillis >= 1000) {
            // {"diag":"?"}: this task's stack high-water mark (bytes).
            cc_diag_hmi(static_cast<uint32_t>(uxTaskGetStackHighWaterMark(nullptr)));
            diagMillis = currentMillis; diagPublished = true;
        }
        #ifdef AUDIO_EN
        audioPlayer.audio_loop();
        #endif
        cc_crumb_hmi(CC_HMI_STEP_WAIT);   // also the uptime heartbeat
        cc_wdt_feed();                    // one full pass completed
        // ALIVE.md 10.1: sleep until the next frame is due, at least 1 and at most 10 ms.
        int32_t waitMs = static_cast<int32_t>(alive_next_show - static_cast<uint32_t>(millis()));
        if (waitMs < 1) waitMs = 1;
        if (waitMs > static_cast<int32_t>(kLoopDelayMaxMs)) waitMs = static_cast<int32_t>(kLoopDelayMaxMs);
        // 1.0.0-cc5.7 (plan F3): while a click plays, pass at least every 3 ms so its 14.5 ms of writable DMA (5 x 64 frames) never runs dry.
        if (audioPlayer.playing() && waitMs > 3) waitMs = 3;
        const TickType_t waitTicks = pdMS_TO_TICKS(static_cast<uint32_t>(waitMs));
        vTaskDelay(waitTicks ? waitTicks : 1);
    }
    
};




HmiThreadButtonHandler::HmiThreadButtonHandler(uint8_t _index) : index(_index) {};



void HmiThreadButtonHandler::handleEvent(AceButton* button, uint8_t eventType, uint8_t buttonState) {
    // Inactivity sleep (cc_sleep.h): every press and release is physical input (it restarts the
    // dim/sleep timer). A press that wakes the knob from asleep only wakes it: that press, its long
    // press and its release are dropped here, before any key state, KeyEvt, HID, audio, LED or
    // native-edge effect, in every mode. The next press acts normally.
    const bool pressed = eventType == AceButton::kEventPressed;
    const bool released = eventType == AceButton::kEventReleased;
    const bool woke = (pressed || released) && cc_sleep_input() && pressed;
    if (sleep_buttons.filter(index, pressed ? CC_SLEEP_KEY_PRESS : released ? CC_SLEEP_KEY_RELEASE : CC_SLEEP_KEY_OTHER,
                             woke)) return;
    if (cc_claimed()) {
        if (eventType == AceButton::kEventLongPressed) {
            // PRESENTATION_V5 11.2 step 2 (VOC 2.5), [r3.1] every raw: a kh when its press's delay matured
            // (600 ms at physical slot 0, 1000 ms elsewhere; one per press). It changes no key state and
            // plays nothing on the LEDs (ALIVE.md 6.2; the hold rings are the engine's, from press/keyUp).
            // While the session is entering its KeyEvt carries id 0 and the COM task defers it to just
            // after the ready line (step 5).
            KeyEvt evt = {kKeyEvtHold, index, hmi_thread.keyState, cc_input_id()};
            xQueueSend(hmi_thread._q_keyevt_out, &evt, (TickType_t)0);
            // r4 hold.tension: the hold landed (the host thump follows); the knob relaxes now.
            if (hold_tension_raw == static_cast<int8_t>(index)) { hold_tension_raw = -1; cc_hold_tension_post(0, 0); }
            return;
        }
        bool hid = false;
        if (eventType == AceButton::kEventPressed) {
            // [r3.1] this press's hold delay (AceButton reads it on every later check of this press): the
            // raw at physical slot 0 keeps kHoldMs (600 ms), every other raw kHoldOtherMs (1000 ms).
            button->getButtonConfig()->setLongPressDelay(cc_physical_button(index) == 0 ? kHoldMs : kHoldOtherMs);
            hmi_thread.keyState |= (1 << index);
            alive.press(millis(), cc_physical_button(index));   // ALIVE.md 6.2: press on that slot
            // r4 hold.tension (plan F2): button 1 on a crumb screen (hold = Home, 600 ms) or button 4 on a screen
            // with holdMarker (1000 ms), never the app canvas; hold 1 wins over a held button 4.
            {
                uint32_t frameId = 0;
                const bool framed = hmi_snapshot(frameId);
                const uint8_t slot = cc_physical_button(index);
                const uint32_t ms = framed ? cc_hold_tension_ms(slot, cc_hmi_frame.crumb != CC_CRUMB_NONE,
                                                                cc_hmi_frame.holdMarker, cc_app_present(cc_hmi_frame.app)) : 0u;
                const bool held1 = hold_tension_raw >= 0 && cc_physical_button(static_cast<uint8_t>(hold_tension_raw)) == 0;
                if (ms && !(held1 && slot != 0)) {
                    hold_tension_raw = static_cast<int8_t>(index);
                    cc_hold_tension_post(static_cast<uint32_t>(millis()), ms);
                }
            }
            // PRESENTATION_V5 11.4: F24 only for the raw at windowsButton while its slot shows an
            // enabled `win` on a ready control; that press's kd is tagged "hid":1.
            hid = cc_is_windows_button(index);
            if (hid) {
                hmi_thread.current_key_codes[0] = 0x73; // USB HID F24, one press/release per button press.
                hmi_thread.num_key_codes = 1;
                hmi_thread.cc_f24_release_at = millis() + 60;
            }
        } else if (eventType == AceButton::kEventReleased) {
            hmi_thread.keyState &= ~(1 << index);
            alive.keyUp(millis(), cc_physical_button(index));   // ALIVE.md 15.7: ends the hold-1 progress ring
            // r4 hold.tension: released early, the knob relaxes with no event.
            if (hold_tension_raw == static_cast<int8_t>(index)) { hold_tension_raw = -1; cc_hold_tension_post(0, 0); }
        } else return;
        // 11.3: ks in ready. 1.0.0-cc5.5 (F1): a press is published before its kd is queued (as before); a
        // release only after its ku is queued, so the COM task never sees a cleared bit in the live mask
        // while that ku is still on its way to the queue (the clear-only `ks` of position lines).
        const bool press = eventType == AceButton::kEventPressed;
        if (press) cc_publish_key_state(hmi_thread.keyState);
        KeyEvt evt = {static_cast<uint8_t>(eventType | (hid ? kKeyEvtHid : 0)), index, hmi_thread.keyState, cc_input_id()};
        xQueueSend(hmi_thread._q_keyevt_out, &evt, (TickType_t)0);
        if (!press) cc_publish_key_state(hmi_thread.keyState);
        hmi_thread.updateKeyLeds();
        return;
    }
    // PRESENTATION_V5 11.2 step 3: the native branch ignores the long press entirely (no KeyEvt, no
    // LED handover input, no idle reset), so native behaviour stays that of 1.0.0-cc5.3.
    if (eventType == AceButton::kEventLongPressed) return;
    // ALIVE.md 8.1: a button state change while unclaimed is native input: the LED handover, and
    // (PRESENTATION_V5 8.10) the offline screen's sub-line swap, which the LCD thread reads.
    if (eventType == AceButton::kEventPressed || eventType == AceButton::kEventReleased) {
        native_button = true;
        cc_native_button_edge();
    }
    switch (eventType) {
        // 1.0.0-cc5.7: no key clack (plan F3), and while the offline system volume runs (plan F3) the profile's own
        // key actions are suppressed: the knob is only the PC's volume then.
        case AceButton::kEventPressed:
            hmi_thread.keyState |= (1<<index);
            if (!offline_now) {
                for (int i=0; i<hmi_thread.hmi_config.keys[index].num_pressed_actions; i++) {
                    hmi_thread.handleKeyAction(hmi_thread.hmi_config.keys[index].pressed[i], eventType);
                }
            }
        break;
        case AceButton::kEventReleased:
            hmi_thread.keyState &= ~(1<<index);
            if (!offline_now) {
                for (int i=0; i<hmi_thread.hmi_config.keys[index].num_pressed_actions; i++) {
                    hmi_thread.handleKeyAction(hmi_thread.hmi_config.keys[index].pressed[i], eventType);
                }
                for (int i=0; i<hmi_thread.hmi_config.keys[index].num_released_actions; i++) {
                    hmi_thread.handleKeyAction(hmi_thread.hmi_config.keys[index].released[i], eventType);
                }
            }
        break;
    }
    // PRESENTATION_V5 11.3: a claim's ready reads it. 1.0.0-cc5.5 (F1): a release is published only after
    // its event is queued (the claimed branch above explains why).
    const bool nativePress = eventType == AceButton::kEventPressed;
    if (nativePress) cc_publish_key_state(hmi_thread.keyState);
    KeyEvt keyEvt = { .type=eventType, .keyNum=(uint8_t)index, .keyState=hmi_thread.keyState };
    xQueueSend(hmi_thread._q_keyevt_out, &keyEvt, (TickType_t)0);
    if (!nativePress) cc_publish_key_state(hmi_thread.keyState);
    hmi_thread.lastCheck = millis();
    hmi_thread.isIdle = false;
    hmi_thread.last_pos = -1;
    hmi_thread.updateKeyLeds();
};




void HmiThread::releaseHeldHid() {
    num_key_codes = 0; memset(current_key_codes, 0, sizeof(current_key_codes));
    current_mouse_buttons = 0; current_pad_buttons = 0; cc_f24_release_at = 0;
}


// FW-BUG-014: while the offline volume runs the profile's release actions are skipped, so a key, mouse or gamepad
// button pressed before it started (port closed with the button held) would stay down on the PC. Entering the
// mode lets go of all of it, as a claim does.
void HmiThread::offlineTick(uint32_t now) {
    const bool was_offline = offline_now;
    offline_update(now);
    if (offline_now && !was_offline) releaseHeldHid();
}


void HmiThread::handleKeyAction(keyAction& action, uint8_t eventType) {
    StringMessage msg;
    switch (action.type) {
        case keyActionType::KA_MIDI:
            if (eventType==AceButton::kEventPressed) {
                if (midiUsbSettings.nano)
                    midiu.sendControlChange(action.midi.cc, action.midi.val, action.midi.channel);
                if (midi2Settings.nano)
                    midi2.sendControlChange(action.midi.cc, action.midi.val, action.midi.channel);
            }
        break;
        // FW-BUG-040: the action's own hid.num key codes (a combo presses and releases all of them); an emptied
        // binding (keyCodes []) has num 0 and sends nothing, never a stale key_codes[0]. Code 0 is "no key".
        case keyActionType::KA_KEY: {
            const int codes = action.hid.num < MAX_KEY_KEYCODES ? action.hid.num : MAX_KEY_KEYCODES;
            for (int k=0; k<codes; k++) {
                const uint8_t code = action.hid.key_codes[k];
                if (code==0) continue;
                if (eventType==AceButton::kEventPressed) {
                    if (num_key_codes<6) current_key_codes[num_key_codes++] = code;
                }
                else if (eventType==AceButton::kEventReleased) {
                    for (int i=0; i<num_key_codes; i++) {
                        if (current_key_codes[i]==code) {
                            for (int j=i; j<num_key_codes-1; j++)
                                current_key_codes[j] = current_key_codes[j+1];
                            num_key_codes--;
                            current_key_codes[num_key_codes] = 0;
                            break;
                        }
                    }
                }
            }
        }
        break;
        case keyActionType::KA_MOUSE:
            if (eventType==AceButton::kEventPressed)
                current_mouse_buttons |= action.mouse.buttons;
            else
                current_mouse_buttons &= ~action.mouse.buttons;
        break;
        case keyActionType::KA_GAMEPAD:
            if (eventType==AceButton::kEventPressed)
                current_pad_buttons |= action.pad.buttons;
            else
                current_pad_buttons &= ~action.pad.buttons;
        break;
        case keyActionType::KA_PROFILE_CHANGE:
            if (action.profile!="" && eventType==AceButton::kEventPressed) {
                StringMessage msg(new String(action.profile), STRING_MESSAGE_PROFILE);
                com_thread.put_string_message(msg);
            }
        break;
        case keyActionType::KA_PROFILE_NEXT:
            msg = StringMessage(nullptr, STRING_MESSAGE_NEXT_PROFILE);
            if (eventType==AceButton::kEventPressed)
                com_thread.put_string_message(msg);
        break;
        case keyActionType::KA_PROFILE_PREV:
            msg = StringMessage(nullptr, STRING_MESSAGE_PREV_PROFILE);
            if (eventType==AceButton::kEventPressed)
                com_thread.put_string_message(msg);
        break;
    }
};



void HmiThread::updateValue() {
    if (hmi_config.knob.num>0) {
        float angle = foc_thread.get_motor_angle();
        for (int i=0;i<hmi_config.knob.num;i++) {
            knobValue& v = hmi_config.knob.values[i];
            if (v.key_state==keyState) {
                float value = 0;
                if (v.angle_min<v.angle_max) {
                    _constrain(angle, v.angle_min, v.angle_max);
                }
                else {
                    _constrain(angle, v.angle_max, v.angle_min);
                }
                if (v.angle_max == v.angle_min) {
                    value = v.value_min;
                }
                else {
                    value = (angle - v.angle_min) * (v.value_max - v.value_min) / (v.angle_max - v.angle_min) + v.value_min;
                }
                if (v.step!=0) {
                    value = round(value / v.step) * v.step;
                }
                currentValue = value;
                currentValue = foc_thread.pass_cur_pos(); // TODO fix and remove this in future
                if (currentValue!=lastValue) {
                    if (v.type==knobValueType::KV_MIDI) {
                        // FW-BUG-041: clamp to 0..127 before narrowing; a uint8_t cast first wrapped every 256
                        // positions (VERNIER, wide ranges), so turning up jumped the CC back to 0.
                        const int32_t raw_value = static_cast<int32_t>(currentValue);
                        const uint8_t midi_value = static_cast<uint8_t>(_constrain(raw_value, 0, 127));
                        if (midiUsbSettings.nano)
                            midiu.sendControlChange(v.midi.cc, midi_value, v.midi.channel);
                        if (midi2Settings.nano)
                            midi2.sendControlChange(v.midi.cc, midi_value, v.midi.channel);
                    }
                    lastValue = currentValue;
                }
            }
        } // for over values
    }
};



// 1.0.0-cc5.5 (F1, stuck keys): the keyboard, mouse and gamepad reports share the one HID IN endpoint
// (report IDs 1..3). After one report the endpoint stays busy until the host polls it (every 2 ms), so
// the old code's second and third sends in the same pass were refused by TinyUSB while their state was
// already marked sent: a key-up could be lost and the key stayed down on the PC. Now:
//   * at most one report per pass, and only while the endpoint is ready (keyboard first, then mouse,
//     then gamepad; a pending one goes out on the next pass, <= 10 ms later);
//   * a report is marked sent only when TinyUSB accepted it (a refusal is retried next pass and
//     counted in diag hidRetries);
//   * the keyboard compares the actual key codes, not only their count (a different key with the same
//     count used to send nothing).
void HmiThread::handleHid() {

    const bool keys_changed = num_key_codes != last_num_key_codes ||
                              memcmp(current_key_codes, last_key_codes, sizeof(current_key_codes)) != 0;
    const bool mouse_changed = (current_mouse_buttons!=last_mouse_buttons);
    const bool pad_changed = (current_pad_buttons!=last_pad_buttons);
    if (!(keys_changed || mouse_changed || pad_changed)) {
        handleConsumer();   // r4 offline volume: only when no keyboard / mouse / gamepad report is due
        return;
    }

    if ( TinyUSBDevice.suspended() ) {
        TinyUSBDevice.remoteWakeup();
    }

    if (!usb_hid.ready()) return;
    if (keys_changed) {
        uint8_t codes[sizeof(current_key_codes)];
        memcpy(codes, current_key_codes, sizeof(codes));
        const uint8_t count = num_key_codes;
        const bool sent = count > 0 ? usb_hid.keyboardReport(RID_KEYBOARD, 0, codes)
                                    : usb_hid.keyboardRelease(RID_KEYBOARD);
        if (sent) {
            memcpy(last_key_codes, codes, sizeof(last_key_codes));
            last_num_key_codes = count;
        } else {
            cc_diag_hid_retry();
        }
        return;
    }
    if (mouse_changed) {
        const uint8_t buttons = current_mouse_buttons;
        if (usb_hid.mouseButtonPress(RID_MOUSE, buttons)) last_mouse_buttons = buttons;
        else cc_diag_hid_retry();
        return;
    }
    // pad_changed
    const uint8_t pad = current_pad_buttons;
    hid_gamepad_report_t report = {
        .x = 0,
        .y = 0,
        .z = 0,
        .rz = 0,
        .rx = 0,
        .ry = 0,
        .hat = 0,
        .buttons = pad
    };
    if (usb_hid.sendReport(RID_GAMEPAD, &report, sizeof(report))) last_pad_buttons = pad;
    else cc_diag_hid_retry();
};



// 1.0.0-cc5.7 (plan F3; HAPTICS.md "Offline volume"): the FOC task's volume steps as HID Consumer Control usages
// (report ID 4): one Volume Increment / Decrement press, then its release, one report per pass like the others.
// Consumer usages never wake the PC: while the bus is suspended every pending step is dropped.
// FW-TST-012: a press already sent keeps consumer_down across the suspend, so its 0 report is the first thing sent
// after the resume (the host's last Consumer report is never left at Volume Up / Down).
void HmiThread::handleConsumer() {
#if CC_OFFLINE_VOLUME
    const int32_t steps = cc_offline_steps();
    int32_t pending = steps - offline_steps_seen;
    if (!offline_now && !consumer_down) { offline_steps_seen = steps; return; }
    if (TinyUSBDevice.suspended()) { offline_steps_seen = steps; return; }
    if (pending > kOfflinePendingMax || pending < -kOfflinePendingMax) {
        offline_steps_seen = steps - (pending > 0 ? kOfflinePendingMax : -kOfflinePendingMax);
        pending = steps - offline_steps_seen;
    }
    if (!usb_hid.ready()) return;
    if (consumer_down) {
        if (usb_hid.sendReport16(RID_CONSUMER, 0)) consumer_down = false;
        else cc_diag_hid_retry();
        return;
    }
    if (pending == 0) return;
    if (usb_hid.sendReport16(RID_CONSUMER, pending > 0 ? kUsageVolumeUp : kUsageVolumeDown)) {
        offline_steps_seen += pending > 0 ? 1 : -1;
        consumer_down = true;
    } else {
        cc_diag_hid_retry();
    }
#endif
}


void HmiThread::handleMidi() {
    if (midiu.read()) {
        midi::MidiType t = midiu.getType();
        uint8_t d1 = midiu.getData1();
        uint8_t d2 = midiu.getData2();
        uint8_t c = midiu.getChannel();
        if (midiUsbSettings.route && midi2Settings.out) {
            midi2.send(t, d1, d2, c);        
        }
    }
    if (midi2.read()) {
        midi::MidiType t = midi2.getType();
        uint8_t d1 = midi2.getData1();
        uint8_t d2 = midi2.getData2();
        uint8_t c = midi2.getChannel();
        if (midi2Settings.route && midiUsbSettings.out) {
            midiu.send(t, d1, d2, c);        
        }
    }
};



void HmiThread::handleSysex(byte* array, unsigned size){
    if (array[0]==SYSEX_BINARIS_ID && array[1]==SYSEX_NANO_ID && array[2]==hmi_thread.midi_sysex_id) {
        hmi_note("Received a sysex message");
        // TODO handle sysex messages
    }
};




// The alive engine's button output (cc_light_buttons: section 9, per slot, the last renderAlive())
// on the four LED pairs, mapped exactly as renderAlive() writes them.
static void engineKeyLeds(CRGB (&ledsp)[NANO_LED_B_NUM]) {
    for (uint8_t i = 0; i < 4; ++i) {
        const CRGB color(cc_light_buttons[cc_physical_button(i)]);
        ledsp[kKeyLedPairs[i][0]] = ledsp[kKeyLedPairs[i][1]] = color;
    }
}


void HmiThread::updateKeyLeds() {
    // While host-claimed, the alive engine draws every button LED at each frame
    // (renderAlive()), releasing included. Nothing to do here.
    if (cc_claimed()) return;
    uint32_t id;
    if (hmi_snapshot(id)) { // a claim that started after the check above
        // 1.0.0-cc5.4 (lead ruling R-a): the button LEDs belong to the alive engine from the
        // claim's first frame on, never to the contract-v4 renderer (cc_lights.cpp is frozen at
        // v4 and knows no on / off / liked tone). Every caller runs before this pass's
        // updateLeds(), which sees the same snapshot, makes the claim transition (alive.claim,
        // ALIVE mode), so renderAlive() draws the claimed frame's v5 button targets
        // (cc_alive_targets, K2 5.3) before the next FastLED.show(). Until then the pairs carry
        // the engine's own last output, never a v4 colour.
        engineKeyLeds(ledsp);
        return;
    }
    nativeKeyLeds();
};


// Native (profile) button colours: led_config idle/press colour per key.
void HmiThread::nativeKeyLeds() {
    CRGB colors[4][2] = {
        {led_config.button_A_col_press, led_config.button_A_col_idle},
        {led_config.button_B_col_press, led_config.button_B_col_idle},
        {led_config.button_C_col_press, led_config.button_C_col_idle},
        {led_config.button_D_col_press, led_config.button_D_col_idle}
    };

    // FW-BUG-039: the profile's ledEnable:false keeps the native button LEDs dark.
    for (int i = 0; i < 4; i++) {
        CRGB color = !led_config.led_enable ? CRGB(CRGB::Black)
                     : (keyState & kKeyBits[i]) ? colors[i][0] : colors[i][1];
        ledsp[kKeyLedPairs[i][0]] = color;
        ledsp[kKeyLedPairs[i][1]] = color;
    }
    
};


// ALIVE.md 8.1 and 10.1, every HMI pass. The engine owns the LEDs while a control's frame is
// active (ALIVE) and in the unclaimed offline state (OFFLINE); native input while unclaimed
// hands them to the unchanged native path (NATIVE) until the next claim ([M29]).
void HmiThread::updateLeds() {
    static_assert(NANO_LED_A_NUM == CC_RING_LEDS, "Control center ring renderer expects 60 LEDs");
    uint32_t id;
    const bool active = hmi_snapshot(id);
    const uint32_t now = millis();
    // capabilities.alive.drive (section 1): the default drive this task uses (it owns the
    // ledMaxBrightness copy).
    cc_alive_default_drive(cc_alive_drive(false, 0, led_max_brightness));
    if (active != cc_lights_active) {
        // Claim / release: the cc_lights_active transition (unclaimed or releasing <-> a
        // control's frame active). A control-id change within a claim is not a transition:
        // the engine's section 6.4 memory and running effects carry across it. A claim from
        // the native handover runs claim() like one from the offline state.
        if (active) alive.claim(now);
        else alive.release(now);
        alive_knob.reset();             // 6.2: the first ready sample of a claim only seeds
        cc_lights_active = active;
        alive_mode = active ? CC_LED_MODE_ALIVE : CC_LED_MODE_OFFLINE;
    }
    if (active) {
        alive_sample_knob(now);
        native_button = false;
        native_primed = false;
        return;                         // the engine renders at the next frame (renderAlive())
    }
    alive_knob.reset();
    // [M29] native input hands the LEDs to the native path until the next claim (the transition
    // above): no 5 s return of the amber marks, no reveal.
    if (alive_native_input()) alive_mode = CC_LED_MODE_NATIVE;
    if (alive_mode == CC_LED_MODE_NATIVE) nativeLeds();
};


uint32_t HmiThread::renderAlive(uint32_t now) {
    const uint32_t started = micros();
    // Latched host fields (section 3), each applied once when its own seq moves, with the
    // millis() of the acceptance that latched it. The COM task (other core) may have accepted it
    // after `now` was read: a stamp in the future of this render is taken as `now`, so no
    // elapsed time (now - at) ever wraps (a wrapped progress would freeze the song hand at the end).
    if (cc_alive_latch(alive_latch, latch_seen)) {
        latch_seen = alive_latch.seq;
        if (alive_latch.clockSeq != latch_clock) {
            latch_clock = alive_latch.clockSeq;
            const uint32_t at = static_cast<int32_t>(alive_latch.clockAt - now) > 0 ? now : alive_latch.clockAt;
            alive.setClock(at, alive_latch.clockMinute);
        }
        if (alive_latch.progressSeq != latch_progress) {
            latch_progress = alive_latch.progressSeq;
            const uint32_t at = static_cast<int32_t>(alive_latch.progressAt - now) > 0 ? now : alive_latch.progressAt;
            alive.setProgress(at, alive_latch.progressPos, alive_latch.progressDur);
        }
        // [r2] PRESENTATION_V5 7.1 / 7.3 (ALIVE.md 3, 3.2, 6.5): reducedMotion (false after every
        // claim) and the LED tuning (ledPink 0 = the built-in PINK; kept until reboot), each applied
        // once when its own seq moves, before this render, so a frame that changes both the motion
        // setting and the screen already renders under the new setting.
        if (alive_latch.motionSeq != latch_motion) {
            latch_motion = alive_latch.motionSeq;
            alive.setReducedMotion(now, alive_latch.reducedMotion);
        }
        if (alive_latch.tuningSeq != latch_tuning) {
            latch_tuning = alive_latch.tuningSeq;
            alive.setTuning(now, alive_latch.ledPinkPresent ? alive_latch.ledPink : 0u,
                            alive_latch.ledVolFullPresent && alive_latch.ledVolFull);
        }
    }
    if (alive_mode == CC_LED_MODE_ALIVE) {
        const CCFrame& frame = cc_hmi_frame;
        CCAliveFrameExtra extra;
        extra.playing = frame.playing;
        extra.skip = frame.feedbackSkip;
        // 6.3: the local position stands in for the frame's value/index only while the FOC runs
        // this frame's control, ready.
        const bool local = alive_knob.valid() && alive_knob.id() == cc_hmi_frame_id;
        alive.render(now, &frame, local ? alive_knob.pos() : 0, local ? static_cast<int32_t>(alive_knob.max()) : -1, extra);
        cc_led_id = cc_hmi_frame_id;
    } else {
        alive.render(now, nullptr, 0, -1);
        cc_led_id = 0;
    }
    // Section 9: drive min(150, ledMaxBrightness), or the latched ledDrive clamped to it. [user
    // 2026-09-26] (ALIVE.md 9 step 4, 12.7) the engine's temporal dither is off, with the F-T floor
    // keeping every lit target's dimmest marks visible, unless a latched ledDither:true turns it on.
    const uint8_t drive = cc_alive_drive(alive_latch.ledDrivePresent, alive_latch.ledDrive, led_max_brightness);
    alive.output(drive, alive_latch.ledDitherPresent ? alive_latch.ledDither : CCAliveSpec::defaultDither,
                 cc_light_ring, cc_light_buttons);
    const uint8_t orientation = static_cast<uint8_t>(DeviceSettings::getInstance().deviceOrientation & 3);
    for (uint8_t i = 0; i < CC_RING_LEDS; ++i)
        leds[cc_ring_address(i, orientation)] = CRGB(cc_light_ring[i]);
    for (uint8_t i = 0; i < 4; ++i) {
        const CRGB color(cc_light_buttons[cc_physical_button(i)]);
        ledsp[kKeyLedPairs[i][0]] = ledsp[kKeyLedPairs[i][1]] = color;
    }
    return static_cast<uint32_t>(micros() - started);
}


// The native (profile) LED path, unchanged from 1.0.0-cc5.3 (ALIVE.md 8.1 native handover).
void HmiThread::nativeLeds() {
    // TODO: optimise this
    uint16_t cur_pos = foc_thread.pass_cur_pos();
    uint16_t start_pos = foc_thread.pass_start_pos();
    uint16_t end_pos = foc_thread.pass_end_pos();
    uint8_t device_orientation = DeviceSettings::getInstance().deviceOrientation;
    uint8_t led_orientation = map(device_orientation, 0, 3, 0, 135);
    // A one-position host control can remain visible to this core briefly while
    // FOC restores the native profile on release. Arduino map divides by range.
    uint16_t point = end_pos == start_pos ? NANO_LED_A_NUM / 2 : map(cur_pos, end_pos, start_pos, 0, NANO_LED_A_NUM - 1);
    uint16_t start = end_pos == start_pos ? point : NANO_LED_A_NUM - 1;
    uint16_t end = end_pos == start_pos ? point : 0;


    // FW-BUG-039: the profile's ledEnable:false keeps the native ring and button LEDs dark.
    if (!led_config.led_enable) {
        for (int i = 0; i < NANO_LED_A_NUM; i++) leds[i] = CRGB::Black;
        nativeKeyLeds();
        return;
    }

    // FW-BUG-012: every native brightness is clamped by ledMaxBrightness, read every pass, so a settings-only change
    // (lower limit, same profile) applies on the next pass and a limit of 0 keeps the idle animation dark too.
     if (com_thread.global_sleep_flag) {
        hmi_thread.IdleLeds(25, CRGB::Red, CRGB::Green, CRGB::Blue);
        FastLED.setBrightness(min(led_max_brightness, static_cast<uint8_t>(25)));
    } else {
        halvesPointer(point, start, end, led_orientation, (led_config.pointer_col), CRGB(led_config.primary_col), CRGB(led_config.secondary_col));
        // Direct, not updateKeyLeds() (which returns early while claimed).
        nativeKeyLeds();
        FastLED.setBrightness(min(led_max_brightness, led_config.led_brightness));
    }
};




// Standard Pointer with two halves
void HmiThread::halvesPointer(int indicator, int startpos, int endpos, int orientation, const struct CRGB& pointerCol, const struct CRGB& postCol, const struct CRGB& preCol){ 
    
    for (int i = NANO_LED_A_NUM - 1; i >= 0; i--) {
         if(i > indicator) {
            int index = ( i + orientation) % NANO_LED_A_NUM ;
             leds[index] = postCol;
         }
         if(i < indicator) {
            int index = ( i + orientation) % NANO_LED_A_NUM;
             leds[index] = preCol;
         }
    }
    int index = ( indicator + orientation) % NANO_LED_A_NUM;
    leds[index] = pointerCol;
    return;
};

/*
    IdleLed animation
    Animates the LEDs with a color gradient
*/

static uint8_t colorIndex = 0;
void HmiThread::IdleLeds(int fps, const struct CRGB& idleColStart, const struct CRGB& idleColMid, const struct CRGB& idleColEnd){
    
    CRGB colors[] = {idleColStart ,idleColMid, idleColEnd};
    static unsigned long lastUpdateTime = 0;
    static bool increasing = false;
    static uint8_t darkness = 255;
    static uint8_t progress = 0;
    CRGB beginColor = colors[colorIndex];
    CRGB endColor = colors[(colorIndex + 1) % ARRAY_SIZE(colors)];
    CRGB currentColor = blend(beginColor, endColor, progress);
    // These are separate arrays; writing through leds past its end is undefined.
    fill_solid(leds,NANO_LED_A_NUM,currentColor);
    fill_solid(ledsp,NANO_LED_B_NUM,currentColor);
    progress++;
    if (progress == 0) {  // Overflow, time to move to the next color
    colorIndex = (colorIndex + 1) % ARRAY_SIZE(colors);
    }
    if(!com_thread.global_sleep_flag)
    return;
}

STUSB4500 usb_pd;

namespace {
// 1.0.0-cc5.5 (F1): read-only STUSB4500 register reads for the PD contract (init_pd() below).
constexpr uint8_t kStusbAddress = 0x28;
constexpr uint8_t kStusbRdoStatus = 0x91;      // RDO_STATUS, 4 bytes
constexpr uint8_t kStusbSinkPdo1 = 0x85;       // DPM_SNK_PDO1; PDO2 0x89, PDO3 0x8D (4 bytes each)
// Four bytes at `reg`, least significant first; at most three tries, false on a bus error or short read.
bool stusb_read32(uint8_t reg, uint32_t& value) {
  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    Wire.beginTransmission(kStusbAddress);
    Wire.write(reg);
    bool ok = false;
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(kStusbAddress, static_cast<uint8_t>(4)) == 4) {
      uint8_t bytes[4] = {0, 0, 0, 0};
      uint8_t got = 0;
      while (got < 4 && Wire.available()) bytes[got++] = static_cast<uint8_t>(Wire.read());
      if (got == 4) {
        value = static_cast<uint32_t>(bytes[0]) | (static_cast<uint32_t>(bytes[1]) << 8) |
                (static_cast<uint32_t>(bytes[2]) << 16) | (static_cast<uint32_t>(bytes[3]) << 24);
        ok = true;
      }
    }
    while (Wire.available()) Wire.read();   // never leave bytes of a short or failed read behind
    if (ok) return true;
    delay(2);
  }
  return false;
}
// FW-BUG-022: the sink PDO table init_pd() programs, as the chip reports it: two PDOs, PDO1 5 V, PDO2 and PDO3
// 9 V (DPM_SNK_PDOn bits 19:10, 50 mV units). Only this exact table skips the NVM write; the count alone does not.
// cc_supply_volts() (cc_haptic_fx.h) relies on it: its 9 V fallback for a failed contract read is safe only
// because any other table (a foreign 5 / 20 V one included) always makes a rewrite boot.
constexpr uint32_t kSinkPdo1Units = 5000u / 50u;
constexpr uint32_t kSinkPdo2Units = 9000u / 50u;
constexpr uint32_t kSinkPdo3Units = 9000u / 50u;
bool stusb_sink_table_ours(uint8_t pdoCount, uint32_t pdo1, uint32_t pdo2, uint32_t pdo3) {
  return pdoCount == 2u && ((pdo1 >> 10) & 0x3FFu) == kSinkPdo1Units && ((pdo2 >> 10) & 0x3FFu) == kSinkPdo2Units &&
         ((pdo3 >> 10) & 0x3FFu) == kSinkPdo3Units;
}
}

PowerType HmiThread::init_pd() {
  Wire.begin(PIN_NANO_I2C_SDA, PIN_NANO_I2C_SCL);
  if (!usb_pd.begin()) {
    Serial.println("STUSB4500 not found");
  } else {
    Serial.println("STUSB4500 found");
  }
  // FW-BUG-022: the live sink table and the contract are read FIRST, before any rewrite: SparkFun setVoltage()
  // writes the volatile DPM_SNK_PDO registers directly, so a read after it would report the new table, not the
  // one the running contract was negotiated against (that holds until a power cycle).
  uint32_t sinkPdo[3] = {0, 0, 0};
  bool sinkPdoOk[3] = {false, false, false};
  for (uint8_t i = 0; i < 3u; ++i)
    sinkPdoOk[i] = stusb_read32(static_cast<uint8_t>(kStusbSinkPdo1 + 4u * i), sinkPdo[i]);
  // The negotiated PD contract (see the block comment below for the registers).
  uint32_t rdo = 0;
  const bool rdoOk = stusb_read32(kStusbRdoStatus, rdo);
  const uint8_t position = rdoOk ? static_cast<uint8_t>((rdo >> 28) & 0x7u) : 0;
  uint32_t millivolts = 0;
  if (position >= 1 && position <= 3 && sinkPdoOk[position - 1u])
    millivolts = ((sinkPdo[position - 1u] >> 10) & 0x3FFu) * 50u;
  // Skip the NVM write only when the live sink table is ours (count AND the three voltages); a failed read
  // rewrites it. After a rewrite the contract still follows the old table until a power cycle, so the FOC task
  // is told (cc_boot_pd_nvm_rewritten(), before cc_boot_pd() below) and assumes the high supply until then.
  const bool sinkTableOurs = sinkPdoOk[0] && sinkPdoOk[1] && sinkPdoOk[2] &&
                             stusb_sink_table_ours(usb_pd.getPdoNumber(), sinkPdo[0], sinkPdo[1], sinkPdo[2]);
  const bool nvmRewritten = !sinkTableOurs;
  if (nvmRewritten) {
    Serial.println("Setting USB profiles to NVM");
    usb_pd.setUsbCommCapable(true);
    usb_pd.setVoltage(1,5.0);
    usb_pd.setCurrent(1,3.0);
    usb_pd.setLowerVoltageLimit(1,20);
    usb_pd.setUpperVoltageLimit(1,20);
    usb_pd.setVoltage(2,9.0);
    usb_pd.setCurrent(2,3.0);
    usb_pd.setLowerVoltageLimit(2,20);
    usb_pd.setUpperVoltageLimit(2,10);
    usb_pd.setVoltage(3,9.0);
    usb_pd.setCurrent(3,3.0);
    usb_pd.setLowerVoltageLimit(3,20);
    usb_pd.setUpperVoltageLimit(3,10);
    usb_pd.setPdoNumber(2);
    usb_pd.write();
  }

  // 1.0.0-cc5.5 (F1, after Karl Malota's idf_upgrade branch): the negotiated PD contract, read once (setup(),
  // before any thread starts, so nothing else uses the I2C bus), at the top of init_pd() BEFORE the NVM
  // programming (FW-BUG-022: the 1.0.0-cc5.4 table, its skip check now covers the voltages). Read only.
  //   * RDO_STATUS (register 0x91..0x94, four bytes, least significant first): bits 30:28 are the object
  //     position of the source PDO the STUSB4500 requested (1..7; 0 = no explicit contract, i.e. a plain
  //     Type-C / USB port at the default 5 V).
  //   * the sink PDO table (DPM_SNK_PDO1..3, registers 0x85 / 0x89 / 0x8D, four bytes each, LSB first):
  //     the voltage of sink PDO n is bits 19:10 x 50 mV. As programmed above: PDO1 5 V, PDO2 and PDO3 9 V
  //     (read before that programming, so the voltage is the one the running contract was made against).
  // pdVolts is the sink PDO at the RDO's object position, rounded to whole volts. The object position
  // indexes the SOURCE's capabilities; PD sources list their fixed supplies in ascending voltage from
  // 5 V, so for a charger that offers 9 V the position of our 9 V request is 2, matching the table. It is
  // 0 (unknown) without a contract, for a position past the three sink PDOs, or when a read failed.
  // The motor driver's supply (STSPIN233 VS) is VBUS through a load switch: on a 9 V contract the motor
  // runs from 9 V; foc_thread.cpp scales voltage_power_supply with this read (cc_supply_volts(), FW-BUG-022).
  // Every transfer is tried at most three times; a failure is recorded, never waited on.
  // FW-BUG-022: the store gets the pre-rewrite read (status, RDO word = position, sink PDO millivolts) and the
  // rewrite flag; the flag is set first so cc_boot_pd_contract() never sees a read without it.
  if (nvmRewritten) cc_boot_pd_nvm_rewritten();
  cc_boot_pd(rdoOk, rdo, millivolts);

  return POWER_5V_USB;
}
