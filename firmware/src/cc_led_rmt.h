#pragma once
#include <Arduino.h>
#include <FastLED.h>
#include <driver/rmt.h>
#include "cc_led_wire.h"

// Hang-proof LED transport (1.0.0-cc5.2). Firmware-only (ESP-IDF 4.4 legacy RMT driver).
//
// Why: in 1.0.0-cc5.1 the HMI task hung for good inside FastLED.show(). FastLED 3.6.0's
// own ESP32 RMT driver (clockless_rmt_esp32.cpp) starts the two strips from the task and
// restarts controllers from its interrupt, sharing unlocked counters (gNext, gNumDone)
// with a binary semaphore that is given only when gNumDone == 2 and taken with
// portMAX_DELAY. A task switch of 0.24-1.8 ms between the buttons strip's tx_start and
// gNext++ lets the interrupt restart a strip, the counters desync and every later show()
// waits forever (CONTROL_CENTER.md, "LED transport").
//
// What replaces it: FastLED keeps everything up to the wire (FastLED.show(), the
// controller list, brightness, colour correction, the dither gate and PixelController),
// and only the clockless transport is swapped. CCLedController<ORDER, LEDS> is a
// CPixelLEDController whose showPixels() produces the bytes exactly like FastLED's own
// ClocklessController::loadPixelData() (loadAndScale0/1/2, advanceData, stepDithering),
// encodes them with cc_led_encode() (the same 25/25 and 12/38 tick bits at 40 MHz) and
// hands them to one CCRmtStrip. Each strip owns one RMT channel with two memory blocks
// (ring: channel 0, blocks 0-1; buttons: channel 2, blocks 2-3, as FastLED used them) and
// its own driver semaphore. Nothing is started from an interrupt, no counter is shared,
// and every wait is bounded:
//   * rmt_wait_tx_done(channel, 0) is only ever polled (never a blocking wait), for at
//     most kIdleGraceUs (5 ms) when the previous frame on that channel has not ended yet;
//   * rmt_write_items(..., wait_tx_done = false) runs only after that poll succeeded, so
//     its own portMAX_DELAY take of the driver semaphore never waits;
//   * a frame still in flight after the grace, or a driver error, is recovered: the channel
//     is stopped, its driver uninstalled (never blocks: no write ever set wait_tx_done) and
//     installed again; three consecutive failures on a strip skip it for kHoldoffMs.
// So FastLED.show() returns within a few milliseconds whatever the hardware or the
// scheduler does, and HMI keeps polling the buttons and acknowledging controls.
//
// Ownership rules: the RMT peripheral belongs to these two strips. No FastLED clockless
// controller may be instantiated anywhere (FastLED.addLeds<CHIPSET, PIN, ...>): its own
// RMT interrupt would take the peripheral's interrupt source next to this driver's.
// harness/cpp11_gate.py fails the gate when `addLeds<` appears in src/.

// Transport counters of one strip. Written only by the HMI task (32-bit aligned fields);
// the COM task reads them one by one for {"diag":"?"}, so a reply may mix two passes.
struct CCLedStripStats {
    volatile uint32_t frames = 0;       // frames handed to the RMT driver
    volatile uint32_t txTimeouts = 0;   // the previous frame had not ended kIdleGraceUs after it was due
    volatile uint32_t writeErrors = 0;  // rmt_config / rmt_driver_install / rmt_write_items failed
    volatile uint32_t recoveries = 0;   // stop + driver uninstall + install after a failure
    volatile uint32_t skipped = 0;      // frames dropped while the strip is held off
    volatile uint32_t maxWaitUs = 0;    // longest wait for the previous frame to end
    volatile int32_t lastErr = 0;       // last esp_err_t (ESP_ERR_TIMEOUT for a timeout), 0 = none
    volatile bool installed = false;
};

class CCRmtStrip {
public:
    // `crumb` is the HMI breadcrumb (CCHmiStep) written when a frame starts on this strip.
    CCRmtStrip(const char* name, rmt_channel_t channel, gpio_num_t pin, uint8_t crumb);
    // HMI task only. The driver's interrupt is allocated on the calling core (core 0).
    bool install();
    // HMI task only: one frame. Returns within a few milliseconds in every case.
    void send(const uint8_t* bytes, size_t count, uint32_t* items, size_t capacity);
    const char* name() const { return name_; }
    const CCLedStripStats& stats() const { return stats_; }

private:
    bool waitIdle();
    void recover();
    void failed();

    const char* name_;
    const rmt_channel_t channel_;
    const gpio_num_t pin_;
    const uint8_t crumb_;
    uint8_t consecutive_ = 0;
    bool holdoff_ = false;
    uint32_t holdoffUntil_ = 0;
    CCLedStripStats stats_;
};

// A FastLED controller that sends through one CCRmtStrip. `LEDS` fixes the static byte and
// RMT item buffers (internal RAM .bss, as the IRAM interrupt requires: 24 items per LED).
template <EOrder ORDER, int LEDS>
class CCLedController : public CPixelLEDController<ORDER> {
public:
    explicit CCLedController(CCRmtStrip& strip) : strip_(strip) {}
    // FastLED.addLeds(&controller, ...) calls this; HmiThread::run() does that on core 0.
    void init() override { strip_.install(); }
    // As FastLED's ClocklessController: FastLED.show() keeps its 2.5 ms minimum spacing.
    uint16_t getMaxRefreshRate() const override { return 400; }

protected:
    void showPixels(PixelController<ORDER>& pixels) override {
        // FastLED 3.6.0 ClocklessController::loadPixelData(), step for step.
        size_t count = 0;
        while (pixels.has(1) && count + 3 <= sizeof(bytes_)) {
            bytes_[count++] = pixels.loadAndScale0();
            bytes_[count++] = pixels.loadAndScale1();
            bytes_[count++] = pixels.loadAndScale2();
            pixels.advanceData();
            pixels.stepDithering();
        }
        strip_.send(bytes_, count, items_, sizeof(items_) / sizeof(items_[0]));
    }

private:
    CCRmtStrip& strip_;
    uint8_t bytes_[LEDS * 3];
    uint32_t items_[LEDS * 3 * CC_LED_ITEMS_PER_BYTE];
};

// cc_led_diag() (declared in cc_diag.h, defined in cc_led_rmt.cpp) reports these counters.
