#include "cc_led_rmt.h"
#include "cc_diag.h"
#include <esp_err.h>
#include <esp_intr_alloc.h>
#include <string.h>

namespace {
// The previous frame on a channel started at least 2.5 ms ago (FastLED.show() spacing;
// HMI shows every 16 ms or more) and lasts at most 1.8 ms (the 60-LED ring, 1440 bits of
// 1.25 us), so it has normally ended long before the next one. A frame still in flight
// this long after it was due lost its end-of-transmission interrupt.
constexpr uint32_t kIdleGraceUs = 5000;
// WS2811 latch: the line stays low at least 50 us between frames. Only needed when the
// previous frame ended while this one waited for it.
constexpr uint32_t kLatchUs = 60;
constexpr uint8_t kHoldoffFailures = 3;       // consecutive failures on one strip ...
constexpr uint32_t kHoldoffMs = 1000;         // ... skip it this long (HMI never spins on it)
constexpr uint8_t kMemBlocks = 2;             // 96 items per channel, 48-item refills, as FastLED
// Level 3 like FastLED's own RMT interrupt, in IRAM: the refill keeps running while flash
// is written (rmt_driver_isr_default and rmt_fill_memory are IRAM in this SDK, and
// CONFIG_RINGBUF_PLACE_ISR_FUNCTIONS_INTO_FLASH is off).
constexpr int kInterruptFlags = ESP_INTR_FLAG_IRAM | ESP_INTR_FLAG_LEVEL3;

constexpr uint8_t kMaxStrips = 2;
CCRmtStrip* strips[kMaxStrips] = {nullptr, nullptr};   // registered at static initialisation
uint8_t stripCount = 0;
}

CCRmtStrip::CCRmtStrip(const char* name, rmt_channel_t channel, gpio_num_t pin, uint8_t crumb)
    : name_(name), channel_(channel), pin_(pin), crumb_(crumb) {
    if (stripCount < kMaxStrips) strips[stripCount++] = this;
}

bool CCRmtStrip::install() {
    if (stats_.installed) return true;
    rmt_config_t config;
    memset(&config, 0, sizeof(config));
    config.rmt_mode = RMT_MODE_TX;
    config.channel = channel_;
    config.gpio_num = pin_;
    config.clk_div = static_cast<uint8_t>(CC_LED_RMT_CLK_DIV);
    config.mem_block_num = kMemBlocks;
    config.tx_config.loop_en = false;
    config.tx_config.carrier_en = false;
    config.tx_config.carrier_level = RMT_CARRIER_LEVEL_LOW;
    config.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;
    config.tx_config.idle_output_en = true;
    esp_err_t err = rmt_config(&config);
    if (err == ESP_OK) err = rmt_driver_install(channel_, 0, kInterruptFlags);
    if (err != ESP_OK) {
        ++stats_.writeErrors;
        stats_.lastErr = err;
        return false;
    }
    stats_.installed = true;
    return true;
}

bool CCRmtStrip::waitIdle() {
    // rmt_wait_tx_done() with a zero wait only polls the driver semaphore (and logs nothing).
    if (rmt_wait_tx_done(channel_, 0) == ESP_OK) return true;
    const uint32_t started = micros();
    for (;;) {
        vTaskDelay(1);
        const uint32_t waited = micros() - started;
        if (waited > stats_.maxWaitUs) stats_.maxWaitUs = waited;
        if (rmt_wait_tx_done(channel_, 0) == ESP_OK) {
            delayMicroseconds(kLatchUs);
            return true;
        }
        if (waited >= kIdleGraceUs) return false;
    }
}

void CCRmtStrip::recover() {
    cc_crumb_hmi(CC_HMI_STEP_LED_RECOVER);
    ++stats_.recoveries;
    if (stats_.installed) {
        rmt_tx_stop(channel_);
        // Never waits here: every write used wait_tx_done = false, so the driver's
        // wait_done flag is clear and uninstall skips its portMAX_DELAY take.
        const esp_err_t err = rmt_driver_uninstall(channel_);
        if (err != ESP_OK) stats_.lastErr = err;
        stats_.installed = false;
    }
    install();
}

void CCRmtStrip::failed() {
    if (++consecutive_ < kHoldoffFailures) return;
    consecutive_ = 0;
    holdoff_ = true;
    holdoffUntil_ = millis() + kHoldoffMs;
}

void CCRmtStrip::send(const uint8_t* bytes, size_t count, uint32_t* items, size_t capacity) {
    cc_crumb_hmi(crumb_);
    if (holdoff_) {
        if (static_cast<int32_t>(millis() - holdoffUntil_) < 0) {
            ++stats_.skipped;
            return;
        }
        holdoff_ = false;
    }
    if (!stats_.installed && !install()) {
        failed();
        return;
    }
    if (!waitIdle()) {
        ++stats_.txTimeouts;
        stats_.lastErr = ESP_ERR_TIMEOUT;
        recover();
        failed();
        return;
    }
    // The channel is idle, so the driver no longer reads `items`: encode the new frame.
    const size_t written = cc_led_encode(bytes, count, items, capacity);
    if (!written) return;
    const esp_err_t err = rmt_write_items(channel_, reinterpret_cast<const rmt_item32_t*>(items),
                                          static_cast<int>(written), false);
    if (err != ESP_OK) {
        ++stats_.writeErrors;
        stats_.lastErr = err;
        recover();
        failed();
        return;
    }
    ++stats_.frames;
    consecutive_ = 0;
}

void cc_led_diag(JsonObject diag) {
    uint32_t timeouts = 0, errors = 0;
    JsonObject led = diag["led"].to<JsonObject>();
    for (uint8_t i = 0; i < stripCount; ++i) {
        const CCLedStripStats& s = strips[i]->stats();
        const uint32_t stripTimeouts = s.txTimeouts, stripErrors = s.writeErrors;
        const int32_t lastErr = s.lastErr;
        JsonObject o = led[strips[i]->name()].to<JsonObject>();
        o["frames"] = static_cast<uint32_t>(s.frames);
        o["txTimeouts"] = stripTimeouts;
        o["writeErrors"] = stripErrors;
        o["recoveries"] = static_cast<uint32_t>(s.recoveries);
        o["skipped"] = static_cast<uint32_t>(s.skipped);
        o["maxWaitUs"] = static_cast<uint32_t>(s.maxWaitUs);
        o["lastErr"] = lastErr ? esp_err_to_name(static_cast<esp_err_t>(lastErr)) : "none";
        o["installed"] = static_cast<bool>(s.installed);
        timeouts += stripTimeouts;
        errors += stripErrors;
    }
    diag["ledTxTimeouts"] = timeouts;
    diag["ledWriteErrors"] = errors;
}
