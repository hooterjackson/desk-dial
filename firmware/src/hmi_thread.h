#pragma once

#include <Arduino.h>
#include <AceButton.h>
#include <FastLED.h>
#include "thread_crtp.h"
#include "nanofoc_d.h"
#include "./led_api.h"
#include "./hmi_api.h"
#include "./DeviceSettings.h"

using namespace ace_button;


typedef enum {
    POWER_5V_USB = 0,
    POWER_5V_PD = 1,
    POWER_9V_PD = 2
} PowerType;

// KeyEvt.type values the HMI queues for the COM task (1.0.0-cc5.4, PRESENTATION_V5 section 11;
// hmi_api.h's KeyEvt layout is unchanged): AceButton's kEventPressed (0) and kEventReleased (1)
// as before, and kKeyEvtHold (AceButton's kEventLongPressed, 4) for a hold (kh), queued only on the
// claimed path ([r3.1] for every raw: 600 ms at physical slot 0, 1000 ms elsewhere). A claimed key down that also sent F24 carries
// kKeyEvtHid in bit 7 ("hid":1 on its kd, 11.4); the COM task masks the type with kKeyEvtTypeMask.
constexpr uint8_t kKeyEvtHold = AceButton::kEventLongPressed;
constexpr uint8_t kKeyEvtHid = 0x80;
constexpr uint8_t kKeyEvtTypeMask = 0x7F;


class HmiThreadButtonHandler : public IEventHandler  {
public:
    HmiThreadButtonHandler(uint8_t _index = 0);
    uint8_t index;
    void handleEvent(AceButton* button, uint8_t eventType, uint8_t buttonState) override;
};



class HmiThread : public Thread<HmiThread> {
    friend class Thread<HmiThread>; //Allow Base Thread to invoke protected run()
    friend class HmiThreadButtonHandler;
    friend class ComThread;


    public:
        HmiThread(const uint8_t task_core);
        ~HmiThread();
       
        void init_usb();
        PowerType init_pd();
        void init(ledConfig& initial_led_config, hmiConfig& initial_hmi_config);
    
        // queues
        void put_led_config(ledConfig& new_config);
        bool get_key_event(KeyEvt* keyEvt);
        void put_hmi_config(hmiConfig& new_config);
        void put_settings(HmiDeviceSettings& new_settings);

        // Light Effects
        void halvesPointer(int indicator, int startpos, int endpos, int orientation, const struct CRGB& pointerCol, const struct CRGB& preCol, const struct CRGB& postCol);
        void IdleLeds(int fps, const struct CRGB& idleColStart, const struct CRGB& idleColMid, const struct CRGB& idleColEnd);

        void handleSysex(byte* array, unsigned size);

    protected:
        void run();
        
        QueueHandle_t _q_config_in;
        QueueHandle_t _q_settings_in;
        QueueHandle_t _q_keyevt_out;

        // hmiConfig handoff from COM. hmiConfig holds Strings (keyAction::profile), so
        // it never goes through a queue: the queue's bitwise copy let the receiving
        // local's destructor free the profile's heap buffers (names of 11+ chars).
        // put_hmi_config() deep-copies into this slot and receiveHmiConfig() copies
        // it out, both under _hmi_config_mutex. One slot: the newest config wins.
        SemaphoreHandle_t _hmi_config_mutex;
        hmiConfig _pending_hmi_config;
        volatile bool _hmi_config_pending = false;

        // internal queue handler
        void handleConfig();
        void handleSettings();
        // handleConfig()'s receivers, kept out of line so their locals and copy
        // call chains exist only while a config is actually waiting.
        __attribute__((noinline)) void receiveLedConfig();
        __attribute__((noinline)) void receiveHmiConfig();


        // LEDs
        uint8_t led_max_brightness = 100;
        ledConfig led_config;
        CRGB leds[NANO_LED_A_NUM];
        CRGB ledsp[NANO_LED_B_NUM];
        unsigned long lastCheck = 0;
        uint16_t last_pos = -1;
        bool isIdle = false;
        void updateKeyLeds();   // returns early while host-claimed (the alive engine renders)
        void nativeKeyLeds();
        // Every pass (ALIVE.md 8.1, 10.1): claim/release of the alive engine, the local input of
        // the ready control ([Q1] push detector), and the native handover (until the next claim,
        // [M29]); runs nativeLeds() while it is active.
        void updateLeds();
        // The native (profile) LED path of 1.0.0-cc5.3, unchanged: halvesPointer or the
        // global_sleep_flag idle animation, nativeKeyLeds() and the profile brightness.
        void nativeLeds();
        // Show time (the 16/17/17 ms deadline cadence, ALIVE.md 10.1) while the engine owns the
        // LEDs: the latched fields, render, section 9 output, the write into leds/ledsp; returns
        // the microseconds it took.
        uint32_t renderAlive(uint32_t now);
        bool cc_was_claimed = false;
        uint32_t cc_f24_release_at = 0;
        uint32_t cc_led_id = 0;

        // buttons
        hmiConfig hmi_config;
        HmiThreadButtonHandler button_handler[4];
        ace_button::AceButton* buttons[4];
        uint8_t num_key_codes = 0;
        uint8_t last_num_key_codes = 0;
        uint8_t current_key_codes[6] = { 0 };
        uint8_t last_key_codes[6] = { 0 };      // the key codes of the last keyboard report TinyUSB accepted
        uint8_t keyState = 0;
        uint8_t current_mouse_buttons = 0;
        uint8_t last_mouse_buttons = 0;
        uint8_t current_pad_buttons = 0;
        uint8_t last_pad_buttons = 0;

        // button handler
        void handleKeyAction(keyAction& action, uint8_t eventType);
        // Every pass: the offline system volume decision (offline_update()); entering the mode releases what the
        // PC still holds, since the profile's release actions are suppressed while it runs (FW-BUG-014).
        void offlineTick(uint32_t now);
        // Every key code, mouse button and gamepad button marked down is let go (handleHid() sends the empty
        // reports on the next passes) and a pending F24 release is dropped with it. Also when a new hmiConfig is
        // taken, whose release actions no longer match what the old one pressed (FW-BUG-015).
        void releaseHeldHid();
        void handleHid();
        void handleConsumer();   // 1.0.0-cc5.7 (plan F3): the offline system volume's Consumer reports

        // knob
        float lastValue;
        float currentValue;
        void updateValue();

        // midi config
        void handleMidi();
        midiSettings midiUsbSettings;
        midiSettings midi2Settings;
        uint8_t midi_sysex_id = 0x00;

        // animations
        bool gReverseDirection = false;
        int brightness = 0;
        int fadeAmount = 10;

};

extern HmiThread hmi_thread;
