#include "cc_diag.h"
#include "cc_display.h"   // CCLcdPerf, cc_lcd_perf_read() (lcd_thread.cpp)
#include "cc_jpeg.h"
#include "cc_media.h"
#include <Arduino.h>
#include <esp_attr.h>
#include <esp_err.h>
#include <esp_system.h>
#include <esp_core_dump.h>
#include <esp_partition.h>
#include <esp_task_wdt.h>
#include <esp32s3/rom/rtc.h>   // rtc_get_reset_reason(cpu): the ROM's per-CPU reason

namespace {
// "ND" boot; stored with its complement. 1.0.0-cc5.2 (B008) added the LCD and COM
// heartbeat words, so a cc5.1 (B007) layout is never read as this one. 1.0.0-cc5.3 (B009)
// widened the COM operation field to 5 bits (the media operations), so a cc5.2 crumb is never
// decoded with the new field widths: the first cc5.3 boot after cc5.2 reports rtcRetained false.
constexpr uint32_t kMagic = 0x4E44B009u;
constexpr uint32_t kLow24 = 0x00FFFFFFu;
constexpr uint32_t kHalf24 = 0x00800000u;

// RTC slow memory, one 32-bit word per field (word stores only). Survives every
// reset except a loss of power; garbage after power-on fails the magic check.
enum : uint8_t { W_MAGIC, W_BOOTS, W_UPTIME, W_COM, W_COM_ARG, W_COM_LINES, W_LCD, W_HMI,
                 W_LCD_ALIVE, W_COM_ALIVE, W_CHECK, W_COUNT };
RTC_NOINIT_ATTR volatile uint32_t rtc_words[W_COUNT];

// This boot's liveness (RAM): millis() of each task's latest breadcrumb (HMI, LCD, COM).
volatile uint32_t live_ms[CC_LIVE_COUNT];
// FOC's pass stamp is the RTOS tick count instead (1 ms ticks): a plain 32-bit load, so the
// haptic loop pays nothing for it (millis() divides a 64-bit timer value).
volatile uint32_t live_foc_ticks;
// Task watchdog subscription per task (one flag each: only that task writes it).
volatile bool wdt_watched[CC_LIVE_COUNT];
int32_t wdt_init_err = ESP_ERR_INVALID_STATE;   // until cc_wdt_begin() ran

struct Boot {
    bool recorded = false, retained = false, coredumpChecked = false, coredumpBlank = false;
    uint8_t reason = 0, rtc0 = 0, rtc1 = 0, rxQueue = CC_RX_QUEUE_UNKNOWN;
    uint32_t bootCount = 0, rxQueueBytes = 0;
    uint32_t previous[W_COUNT] = {};          // this boot's view of the previous boot
    int32_t coredumpStatus = 0;               // esp_err_t
    uint32_t coredumpBytes = 0;
};
Boot boot;

constexpr const char* kResetNames[] = {"unknown", "poweron", "external", "software", "panic", "int_wdt",
                                       "task_wdt", "wdt", "deepsleep", "brownout", "sdio"};
constexpr const char* kComOps[] = {"none", "capabilities", "diag", "art-begin", "art-data", "art-commit",
                                   "art-other", "release", "control", "frame", "native", "parse-error", "oversize",
                                   "media-begin", "media-data", "media-commit", "media-have", "media-other"};
// COM crumb code (8 bits): operation in the top 5 bits, stage in the low 3.
constexpr uint32_t kComOpShift = 3, kComOpMask = 31, kComStageMask = 7;
constexpr const char* kComStages[] = {"wait", "read", "line", "service", "events"};
constexpr const char* kLcdSteps[] = {"wait", "host", "render", "refresh", "timers", "diag", "decode"};
constexpr const char* kHmiSteps[] = {"wait", "config", "buttons", "hid", "leds", "show",
                                     "show-ring", "show-buttons", "led-recover"};
constexpr const char* kLiveNames[] = {"hmi", "lcd", "com", "foc"};

template <size_t N>
const char* name_of(const char* const (&names)[N], uint32_t index) {
    return index < N ? names[index] : "?";
}

// ROM reset reason names (esp32s3/rom/rtc.h RESET_REASON).
const char* rtc_reason_name(uint32_t code) {
    switch (code) {
        case POWERON_RESET: return "POWERON_RESET";
        case RTC_SW_SYS_RESET: return "RTC_SW_SYS_RESET";
        case DEEPSLEEP_RESET: return "DEEPSLEEP_RESET";
        case TG0WDT_SYS_RESET: return "TG0WDT_SYS_RESET";
        case TG1WDT_SYS_RESET: return "TG1WDT_SYS_RESET";
        case RTCWDT_SYS_RESET: return "RTCWDT_SYS_RESET";
        case INTRUSION_RESET: return "INTRUSION_RESET";
        case TG0WDT_CPU_RESET: return "TG0WDT_CPU_RESET";
        case RTC_SW_CPU_RESET: return "RTC_SW_CPU_RESET";
        case RTCWDT_CPU_RESET: return "RTCWDT_CPU_RESET";
        case RTCWDT_BROWN_OUT_RESET: return "RTCWDT_BROWN_OUT_RESET";
        case RTCWDT_RTC_RESET: return "RTCWDT_RTC_RESET";
        case TG1WDT_CPU_RESET: return "TG1WDT_CPU_RESET";
        case SUPER_WDT_RESET: return "SUPER_WDT_RESET";
        case GLITCH_RTC_RESET: return "GLITCH_RTC_RESET";
        case EFUSE_RESET: return "EFUSE_RESET";
        case USB_UART_CHIP_RESET: return "USB_UART_CHIP_RESET";
        case USB_JTAG_CHIP_RESET: return "USB_JTAG_CHIP_RESET";
        case POWER_GLITCH_RESET: return "POWER_GLITCH_RESET";
        default: return "?";
    }
}

inline uint32_t stamp(uint32_t code, uint32_t now) {
    return (code << 24) | (now & kLow24);
}
inline uint32_t com_code(uint32_t op, uint32_t stage) {
    return (op & kComOpMask) << kComOpShift | (stage & kComStageMask);
}
inline uint32_t com_op(uint32_t word) { return (word >> (24 + kComOpShift)) & kComOpMask; }
inline uint32_t com_stage(uint32_t word) { return (word >> 24) & kComStageMask; }

// Full millis() of a 24-bit breadcrumb stamp, relative to a full heartbeat of the same
// boot (the crumb is at most a few ms before or after it, or older when the task hung).
uint32_t full_ms(uint32_t reference, uint32_t low24) {
    if (!reference) return low24;
    const uint32_t delta = (low24 - (reference & kLow24)) & kLow24;
    return delta < kHalf24 ? reference + delta : reference - (kLow24 + 1 - delta);
}

// Milliseconds since `last`, never negative (another core may store a newer `last`
// between the two reads).
uint32_t age_ms(uint32_t now, uint32_t last) {
    const int32_t age = static_cast<int32_t>(now - last);
    return age > 0 ? static_cast<uint32_t>(age) : 0;
}
}

void cc_boot_begin() {
    if (boot.recorded) return;
    boot.recorded = true;
    boot.reason = static_cast<uint8_t>(esp_reset_reason());
    boot.rtc0 = static_cast<uint8_t>(rtc_get_reset_reason(0));
    boot.rtc1 = static_cast<uint8_t>(rtc_get_reset_reason(1));
    boot.retained = rtc_words[W_MAGIC] == kMagic && rtc_words[W_CHECK] == ~kMagic;
    for (uint8_t i = 0; i < W_COUNT; ++i) boot.previous[i] = boot.retained ? rtc_words[i] : 0;
    boot.bootCount = boot.retained ? boot.previous[W_BOOTS] + 1 : 1;
    for (uint8_t i = 0; i < W_COUNT; ++i) rtc_words[i] = 0;
    rtc_words[W_BOOTS] = boot.bootCount;
    rtc_words[W_MAGIC] = kMagic;
    rtc_words[W_CHECK] = ~kMagic;
}

void cc_boot_check_coredump() {
    // Read-only: the first word tells a blank (erased) partition from any
    // write, and esp_core_dump_image_get() validates a complete image. Nothing
    // here erases the partition; it is evidence for esptool read_flash.
    const esp_partition_t* part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                                           ESP_PARTITION_SUBTYPE_DATA_COREDUMP, nullptr);
    uint32_t first = 0;
    boot.coredumpBlank = part && esp_partition_read(part, 0, &first, sizeof(first)) == ESP_OK && first == 0xFFFFFFFFu;
    size_t address = 0, size = 0;
    const esp_err_t status = esp_core_dump_image_get(&address, &size);
    boot.coredumpStatus = status;
    boot.coredumpBytes = status == ESP_OK ? static_cast<uint32_t>(size) : 0;
    boot.coredumpChecked = true;
}

void cc_boot_rx_queue(uint8_t where, uint32_t bytes) { boot.rxQueue = where; boot.rxQueueBytes = bytes; }
uint32_t cc_boot_rx_queue_internal_bytes() {
    return boot.rxQueue == CC_RX_QUEUE_INTERNAL || boot.rxQueue == CC_RX_QUEUE_DEFAULT ? boot.rxQueueBytes : 0;
}

void cc_crumb_com(uint8_t op, uint8_t stage, uint32_t arg) {
    const uint32_t now = static_cast<uint32_t>(millis());
    live_ms[CC_LIVE_COM] = now;
    rtc_words[W_COM_ARG] = arg;
    rtc_words[W_COM] = stamp(com_code(op, stage), now);
    if (stage == CC_COM_STAGE_WAIT) rtc_words[W_COM_ALIVE] = now;
}
void cc_crumb_com_stage(uint8_t stage) {
    const uint32_t now = static_cast<uint32_t>(millis());
    live_ms[CC_LIVE_COM] = now;
    rtc_words[W_COM] = stamp(com_code(com_op(rtc_words[W_COM]), stage), now);
    if (stage == CC_COM_STAGE_WAIT) rtc_words[W_COM_ALIVE] = now;
}
void cc_crumb_com_line() { rtc_words[W_COM_LINES] = rtc_words[W_COM_LINES] + 1; }
void cc_crumb_lcd(uint8_t step) {
    const uint32_t now = static_cast<uint32_t>(millis());
    live_ms[CC_LIVE_LCD] = now;
    rtc_words[W_LCD] = stamp(step, now);
    if (step == CC_LCD_STEP_WAIT) rtc_words[W_LCD_ALIVE] = now;
}
void cc_crumb_hmi(uint8_t step) {
    const uint32_t now = static_cast<uint32_t>(millis());
    live_ms[CC_LIVE_HMI] = now;
    if (step == CC_HMI_STEP_WAIT) rtc_words[W_UPTIME] = now;
    rtc_words[W_HMI] = stamp(step, now);
}
void cc_live_foc() { live_foc_ticks = static_cast<uint32_t>(xTaskGetTickCount()); }

void cc_diag_boot(JsonObject d) {
    d["resetReason"] = name_of(kResetNames, boot.reason);
    d["resetCode"] = boot.reason;
    JsonArray rtc = d["rtcReset"].to<JsonArray>();
    rtc.add(boot.rtc0); rtc.add(boot.rtc1);
    JsonArray rtcNames = d["rtcResetNames"].to<JsonArray>();
    rtcNames.add(rtc_reason_name(boot.rtc0)); rtcNames.add(rtc_reason_name(boot.rtc1));
    d["bootCount"] = boot.bootCount;
    d["rtcRetained"] = boot.retained;
    d["uptimeMs"] = static_cast<uint32_t>(millis());
    if (boot.retained) {
        const uint32_t* p = boot.previous;
        const uint32_t uptime = p[W_UPTIME];
        // Each task's crumb is resolved against its own heartbeat; before its first
        // heartbeat (or for an older layout) against HMI's, as in 1.0.0-cc5.1.
        const uint32_t lcdAlive = p[W_LCD_ALIVE] ? p[W_LCD_ALIVE] : uptime;
        const uint32_t comAlive = p[W_COM_ALIVE] ? p[W_COM_ALIVE] : uptime;
        uint32_t last = uptime;
        if (p[W_LCD_ALIVE] > last) last = p[W_LCD_ALIVE];
        if (p[W_COM_ALIVE] > last) last = p[W_COM_ALIVE];
        JsonObject prev = d["previous"].to<JsonObject>();
        prev["uptimeMs"] = uptime;
        prev["lastAliveMs"] = last;
        prev["comLines"] = p[W_COM_LINES];
        JsonObject com = prev["com"].to<JsonObject>();
        com["op"] = name_of(kComOps, com_op(p[W_COM]));
        com["stage"] = name_of(kComStages, com_stage(p[W_COM]));
        com["arg"] = p[W_COM_ARG];
        com["atMs"] = full_ms(comAlive, p[W_COM] & kLow24);
        com["aliveMs"] = p[W_COM_ALIVE];
        JsonObject lcd = prev["lcd"].to<JsonObject>();
        lcd["step"] = name_of(kLcdSteps, p[W_LCD] >> 24);
        lcd["atMs"] = full_ms(lcdAlive, p[W_LCD] & kLow24);
        lcd["aliveMs"] = p[W_LCD_ALIVE];
        JsonObject hmi = prev["hmi"].to<JsonObject>();
        hmi["step"] = name_of(kHmiSteps, p[W_HMI] >> 24);
        hmi["atMs"] = full_ms(uptime, p[W_HMI] & kLow24);
        hmi["aliveMs"] = uptime;
    }
    JsonObject core = d["coredump"].to<JsonObject>();
    if (boot.coredumpChecked) {
        core["blank"] = boot.coredumpBlank;
        core["present"] = boot.coredumpStatus == ESP_OK;
        core["status"] = esp_err_to_name(static_cast<esp_err_t>(boot.coredumpStatus));
        core["bytes"] = boot.coredumpBytes;
    } else {
        core["status"] = "unchecked";
    }
    static constexpr const char* kRxQueue[] = {"unknown", "internal", "psram", "default"};
    d["rxQueue"] = name_of(kRxQueue, boot.rxQueue);
}

namespace {
// LED frame statistics (1.0.0-cc5.4): written by the HMI task once per shown frame, read (and
// the max reset) by the COM task; a short spinlock keeps each reply consistent.
portMUX_TYPE led_lock = portMUX_INITIALIZER_UNLOCKED;
constexpr uint32_t kLedWindowMs = 1000;
constexpr const char* kLedModes[] = {"offline", "alive", "native"};
struct LedStats {
    bool started = false;
    uint32_t windowStart = 0;          // millis() the current one-second window began
    uint32_t windowFrames = 0;         // frames shown in the current window
    uint32_t windowRendered = 0;       // ... of which the engine rendered
    uint32_t windowUs = 0;             // their summed render time (µs)
    uint32_t fps = 0;                  // frames of the last completed window
    uint32_t avgUs = 0;                // mean render time over the last completed window
    uint32_t maxUs = 0;                // longest render since the last diag read
    uint8_t mode = CC_LED_MODE_OFFLINE;
    // [r2] ALIVE.md 10.1: show-to-show intervals (RF3 8.1; the case for R7).
    uint32_t lastShow = 0;             // millis() of the previous show
    uint32_t gapMaxMs = 0;             // longest interval since the last diag read
    uint32_t lateShows = 0;            // intervals > kLedLateGapMs since boot
};
LedStats led_stats;
constexpr uint32_t kLedLateGapMs = 20;
}

void cc_diag_led_frame(uint32_t nowMs, uint8_t mode, bool rendered, uint32_t renderUs) {
    portENTER_CRITICAL(&led_lock);
    LedStats& s = led_stats;
    if (s.started) {
        const uint32_t gap = static_cast<uint32_t>(nowMs - s.lastShow);
        if (gap > s.gapMaxMs) s.gapMaxMs = gap;
        if (gap > kLedLateGapMs) ++s.lateShows;
    }
    s.lastShow = nowMs;
    if (!s.started) {
        s.started = true;
        s.windowStart = nowMs;
    } else if (static_cast<uint32_t>(nowMs - s.windowStart) >= kLedWindowMs) {
        s.fps = s.windowFrames;
        s.avgUs = s.windowRendered ? s.windowUs / s.windowRendered : 0;
        s.windowFrames = s.windowRendered = s.windowUs = 0;
        s.windowStart += kLedWindowMs;
        if (static_cast<uint32_t>(nowMs - s.windowStart) >= kLedWindowMs) s.windowStart = nowMs;   // a gap
    }
    ++s.windowFrames;
    if (rendered) {
        ++s.windowRendered;
        s.windowUs += renderUs;
        if (renderUs > s.maxUs) s.maxUs = renderUs;
    }
    s.mode = mode;
    portEXIT_CRITICAL(&led_lock);
}

namespace {
// The LED frame fields of cc_diag_live() (1.0.0-cc5.4).
void diag_leds(JsonObject d) {
    const uint32_t now = static_cast<uint32_t>(millis());
    portENTER_CRITICAL(&led_lock);
    const LedStats s = led_stats;
    led_stats.maxUs = 0;                                   // reset on read
    led_stats.gapMaxMs = 0;                                // reset on read
    portEXIT_CRITICAL(&led_lock);
    // No frame has closed a window for 2 s: the LED loop is not showing (hmiAgeMs says why).
    const bool current = s.started && static_cast<uint32_t>(now - s.windowStart) < 2 * kLedWindowMs;
    d["ledFps"] = current ? s.fps : 0;
    d["ledRenderUsMax"] = s.maxUs;
    d["ledRenderUsAvg"] = current ? s.avgUs : 0;
    d["ledMode"] = name_of(kLedModes, s.mode);
    // [r2] ALIVE.md 10.1 (VOC 6.1): the longest interval between two FastLED.show() calls since the
    // previous read (reset on read; a stopped loop shows as ledFps 0 and hmiAgeMs), and the
    // intervals over 20 ms since boot.
    d["ledShowGapMsMax"] = s.gapMaxMs;
    d["ledLateShows"] = s.lateShows;
}
}

void cc_diag_live(JsonObject d) {
    const uint32_t now = static_cast<uint32_t>(millis());
    d["hmiAgeMs"] = age_ms(now, live_ms[CC_LIVE_HMI]);
    d["lcdAgeMs"] = age_ms(now, live_ms[CC_LIVE_LCD]);
    d["comAgeMs"] = age_ms(now, live_ms[CC_LIVE_COM]);
    d["focAgeMs"] = age_ms(static_cast<uint32_t>(xTaskGetTickCount()), live_foc_ticks) * portTICK_PERIOD_MS;
    d["hmiStep"] = name_of(kHmiSteps, rtc_words[W_HMI] >> 24);
    d["lcdStep"] = name_of(kLcdSteps, rtc_words[W_LCD] >> 24);
    const uint32_t com = rtc_words[W_COM];
    d["comOp"] = name_of(kComOps, com_op(com));
    d["comStage"] = name_of(kComStages, com_stage(com));
    d["taskWdtS"] = wdt_init_err == ESP_OK ? CC_TASK_WDT_SECONDS : 0;
    JsonArray watched = d["wdtTasks"].to<JsonArray>();
    for (uint8_t i = 0; i < CC_LIVE_COUNT; ++i)
        if (wdt_watched[i]) watched.add(kLiveNames[i]);
    diag_leds(d);
}

void cc_diag_media(JsonObject d) {
    d["rxQueueBytes"] = boot.rxQueueBytes;
    const CCMediaCounters media = cc_media_counters();
    d["mediaCommits"] = media.commits;
    d["mediaErrors"] = media.errors;
    d["mediaEvictions"] = media.evictions;
    const CCJpegStats jpeg = cc_jpeg_stats();
    d["jpegDecodes"] = jpeg.decodes;
    d["jpegDecodeErrors"] = jpeg.errors;
    d["jpegDecodeMsMax"] = jpeg.msMax;
    d["jpegDecodeMsLast"] = jpeg.msLast;
}

void cc_diag_lcd_pipeline(JsonObject d) { cc_diag_lcd_perf_fields(d, cc_lcd_perf_read()); }

void cc_wdt_begin() {
    // IDF 4.4: on an initialised TWDT (Arduino starts it with IDLE0 subscribed, 5 s,
    // panic) this only updates the timeout and the panic flag.
    wdt_init_err = esp_task_wdt_init(CC_TASK_WDT_SECONDS, true);
}
void cc_wdt_watch(uint8_t task) {
    if (task < CC_LIVE_COUNT && !wdt_watched[task] && esp_task_wdt_add(nullptr) == ESP_OK) wdt_watched[task] = true;
}
void cc_wdt_unwatch(uint8_t task) {
    if (task < CC_LIVE_COUNT && wdt_watched[task] && esp_task_wdt_delete(nullptr) == ESP_OK) wdt_watched[task] = false;
}
void cc_wdt_feed() { esp_task_wdt_reset(); }
