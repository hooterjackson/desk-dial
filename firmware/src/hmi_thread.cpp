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
// Host-frame snapshot for updateLeds()/updateKeyLeds(). Both run only on the
// HMI thread and never nest.
CCFrame cc_hmi_frame;
uint32_t cc_hmi_frame_id = 0;
// Inactivity sleep (cc_sleep.h): the presses that woke the knob, swallowed with their long press
// and release. HMI thread only (AceButton calls the handlers from check() on this thread).
CCSleepButtons sleep_buttons;

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

using namespace ace_button;

Adafruit_USBD_MIDI usb_midi(1);

MIDI_CREATE_INSTANCE(Adafruit_USBD_MIDI, usb_midi, midiu);
MIDI_CREATE_INSTANCE(HardwareSerial, Serial2, midi2)

enum {
  RID_KEYBOARD = 1,
  RID_MOUSE = 2,
  RID_GAMEPAD = 3,
};


uint8_t const desc_hid_report[] = {
  TUD_HID_REPORT_DESC_KEYBOARD( HID_REPORT_ID(RID_KEYBOARD) ),
  TUD_HID_REPORT_DESC_MOUSE   ( HID_REPORT_ID(RID_MOUSE) ),
  TUD_HID_REPORT_DESC_GAMEPAD( HID_REPORT_ID(RID_GAMEPAD) )
};

// USB HID object
Adafruit_USBD_HID usb_hid;

#define ARRAY_SIZE(arr) (sizeof(arr) / sizeof((arr)[0]))

// Hmi thread controls LED via FastLed and buttons via AceButton

HmiThread::HmiThread(const uint8_t task_core ) : Thread("HMI", kHmiStackBytes, 1, task_core) {
    _q_config_in = xQueueCreate(2, sizeof( ledConfig ));
    _hmi_config_mutex = xSemaphoreCreateMutex();
    _q_settings_in = xQueueCreate(2, sizeof( HmiDeviceSettings ));
    _q_keyevt_out = xQueueCreate(5, sizeof( KeyEvt ));
}

HmiThread::~HmiThread() {}



void midi_sysex_handler(byte* array, unsigned size) {
    hmi_thread.handleSysex(array, size);
};


// init_usb() must be called before the thread is started
void HmiThread::init_usb() {
  usb_midi.setStringDescriptor("Nano_D MIDI");
  midiu.setHandleSystemExclusive(midi_sysex_handler);
  usb_midi.begin();
  midiu.begin();

  usb_hid.setBootProtocol(HID_ITF_PROTOCOL_NONE);
  usb_hid.setPollInterval(2);
  usb_hid.setReportDescriptor(desc_hid_report, sizeof(desc_hid_report));
  usb_hid.setStringDescriptor("Nano_D HID");
  usb_hid.begin();
};


// init must be called before the thread is started
void HmiThread::init(ledConfig& initial_led_config, hmiConfig& initial_hmi_config) {
    led_config = initial_led_config;
    hmi_config = initial_hmi_config;
    led_max_brightness =  DeviceSettings::getInstance().ledMaxBrightness;
    uint8_t b = min(led_max_brightness, led_config.led_brightness);
    FastLED.setBrightness(b);
    midi_sysex_id = DeviceSettings::getInstance().midi_sysex_id;
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
    if (_hmi_config_pending) {
        hmi_config = _pending_hmi_config;
        _hmi_config_pending = false;
    }
    xSemaphoreGive(_hmi_config_mutex);
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
        // and no repeat. The claimed branch turns it into a kh for physical slot 0 only; the
        // native branch ignores it.
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

    audioPlayer.play_audio(chime_wav, 80);
    while (1) {
        cc_crumb_hmi(CC_HMI_STEP_CONFIG);
        handleSettings();
        handleConfig();
        cc_sleep_tick();                  // inactivity timer: awake -> dim -> asleep (cc_sleep.h)
        bool claimed = cc_claimed();
        if (claimed != cc_was_claimed) {
            num_key_codes = 0; memset(current_key_codes, 0, sizeof(current_key_codes));
            current_mouse_buttons = 0; current_pad_buttons = 0; cc_f24_release_at = 0;
            // 1.0.0-cc5.4: FastLED's dither mode is chosen per frame below (engine frames:
            // DISABLE_DITHER; native frames: BINARY_DITHER as before).
            cc_was_claimed = claimed;
        }
        if (!claimed) handleMidi();
        cc_crumb_hmi(CC_HMI_STEP_BUTTONS);
        for (int i = 0; i < 4; i++)
            buttons[i]->check();
        if (!claimed) updateValue();
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
            // PRESENTATION_V5 11.2 step 2 (VOC 2.5): a hold only for the raw at physical slot 0 (the
            // buttonOrder in force now); the other raws' long presses are ignored. It changes no key
            // state and plays nothing on the LEDs (ALIVE.md 6.2). While the session is entering its
            // KeyEvt carries id 0 and the COM task defers it to just after the ready line (step 5).
            if (cc_physical_button(index) != 0) return;
            KeyEvt evt = {kKeyEvtHold, index, hmi_thread.keyState, cc_input_id()};
            xQueueSend(hmi_thread._q_keyevt_out, &evt, (TickType_t)0);
            return;
        }
        bool hid = false;
        if (eventType == AceButton::kEventPressed) {
            hmi_thread.keyState |= (1 << index);
            alive.press(millis(), cc_physical_button(index));   // ALIVE.md 6.2: press on that slot
            // PRESENTATION_V5 11.4: F24 only for the raw at windowsButton while its slot shows an
            // enabled `win` on a ready control; that press's kd is tagged "hid":1.
            hid = cc_is_windows_button(index);
            if (hid) {
                hmi_thread.current_key_codes[0] = 0x73; // USB HID F24, one press/release per button press.
                hmi_thread.num_key_codes = 1;
                hmi_thread.cc_f24_release_at = millis() + 60;
            }
        } else if (eventType == AceButton::kEventReleased) hmi_thread.keyState &= ~(1 << index);
        else return;
        cc_publish_key_state(hmi_thread.keyState);          // 11.3: ks in ready
        KeyEvt evt = {static_cast<uint8_t>(eventType | (hid ? kKeyEvtHid : 0)), index, hmi_thread.keyState, cc_input_id()};
        xQueueSend(hmi_thread._q_keyevt_out, &evt, (TickType_t)0);
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
        case AceButton::kEventPressed:
            hmi_thread.keyState |= (1<<index);
            for (int i=0; i<hmi_thread.hmi_config.keys[index].num_pressed_actions; i++) {
                hmi_thread.handleKeyAction(hmi_thread.hmi_config.keys[index].pressed[i], eventType);
            }
            if (audioPlayer.audio_config.key_audio_file!=nullptr)
                audioPlayer.play_audio(audioPlayer.audio_config.key_audio_file, audioPlayer.audio_config.audio_feedback_lvl);
        break;
        case AceButton::kEventReleased:
            hmi_thread.keyState &= ~(1<<index);
            for (int i=0; i<hmi_thread.hmi_config.keys[index].num_pressed_actions; i++) {
                hmi_thread.handleKeyAction(hmi_thread.hmi_config.keys[index].pressed[i], eventType);
            }            
            for (int i=0; i<hmi_thread.hmi_config.keys[index].num_released_actions; i++) {
                hmi_thread.handleKeyAction(hmi_thread.hmi_config.keys[index].released[i], eventType);
            }
        break;
    }
    cc_publish_key_state(hmi_thread.keyState);   // PRESENTATION_V5 11.3: a claim's ready reads it
    KeyEvt keyEvt = { .type=eventType, .keyNum=(uint8_t)index, .keyState=hmi_thread.keyState };
    xQueueSend(hmi_thread._q_keyevt_out, &keyEvt, (TickType_t)0);
    hmi_thread.lastCheck = millis();
    hmi_thread.isIdle = false;
    hmi_thread.last_pos = -1;
    hmi_thread.updateKeyLeds();
};




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
        case keyActionType::KA_KEY:
            if (num_key_codes<6 && eventType==AceButton::kEventPressed)
                current_key_codes[num_key_codes++] = action.hid.key_codes[0];
            else if (num_key_codes>0 && eventType==AceButton::kEventReleased) {
                for (int i=0; i<num_key_codes; i++) {
                    if (current_key_codes[i]==action.hid.key_codes[0]) {
                        for (int j=i; j<num_key_codes-1; j++)
                            current_key_codes[j] = current_key_codes[j+1];
                        num_key_codes--;
                        current_key_codes[num_key_codes] = 0;
                        break;
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
                        uint8_t midi_value = (uint8_t)(currentValue);
                        midi_value = _constrain(midi_value, 0, 127);
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



void HmiThread::handleHid() {

    bool keys_changed = (num_key_codes!=last_num_key_codes);
    bool mouse_changed = (current_mouse_buttons!=last_mouse_buttons);
    bool pad_changed = (current_pad_buttons!=last_pad_buttons);

    if ( TinyUSBDevice.suspended() && (keys_changed||mouse_changed||pad_changed) ) {
        TinyUSBDevice.remoteWakeup();
    }

    if (usb_hid.ready()) {
        if (keys_changed) {
            if (num_key_codes>0)
                usb_hid.keyboardReport(RID_KEYBOARD, 0, current_key_codes);
            else
                usb_hid.keyboardRelease(RID_KEYBOARD);
            last_num_key_codes = num_key_codes;
        }
        if (mouse_changed) {
            usb_hid.mouseButtonPress(RID_MOUSE, current_mouse_buttons);
            last_mouse_buttons = current_mouse_buttons;
        }
        if (pad_changed) {
            hid_gamepad_report_t report = {
                .x = 0,
                .y = 0,
                .z = 0,
                .rz = 0,
                .rx = 0,
                .ry = 0,
                .hat = 0,
                .buttons = current_pad_buttons
            };
            usb_hid.sendReport(RID_GAMEPAD, &report, sizeof(report));
            last_pad_buttons = current_pad_buttons;
        }
    }
};



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

    for (int i = 0; i < 4; i++) {
        CRGB color = (keyState & kKeyBits[i]) ? colors[i][0] : colors[i][1];
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


     if (com_thread.global_sleep_flag) {
        hmi_thread.IdleLeds(25, CRGB::Red, CRGB::Green, CRGB::Blue);
        FastLED.setBrightness(25);
    } else {
        halvesPointer(point, start, end, led_orientation, (led_config.pointer_col), CRGB(led_config.primary_col), CRGB(led_config.secondary_col));
        // Direct, not updateKeyLeds() (which returns early while claimed).
        nativeKeyLeds();
        FastLED.setBrightness(led_config.led_brightness);
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

PowerType HmiThread::init_pd() {
  Wire.begin(PIN_NANO_I2C_SDA, PIN_NANO_I2C_SCL);
  if (!usb_pd.begin()) {
    Serial.println("STUSB4500 not found");
  } else {
    Serial.println("STUSB4500 found");
  }
  if (usb_pd.getPdoNumber()!=2) {
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

    // TODO: read status register to determine selected PDO

  return POWER_5V_USB;
}
