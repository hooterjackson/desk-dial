#pragma once
#include <stdint.h>
#include <ArduinoJson.h>

// Reboot detection and reset attribution for {"diag":"?"} (1.0.0-cc5.1).
// Firmware-only (ESP-IDF APIs); not a shared platform-neutral unit.
//
// Why: the 1.0.0-cc5 knob reset once during the stress check without a panic
// and without a core dump, and nothing on the device recorded why. These
// fields make the next reset identify itself:
//   * resetReason / resetCode: esp_reset_reason() of this boot, and the ROM's
//     per-CPU reason (rtcReset) that separates brownout (15) from an interrupt
//     watchdog system reset (TG1WDT_SYS_RESET, 8) and a power-on (1);
//   * bootCount / uptimeMs: a boot counter in RTC memory (with a magic), so a
//     host sees a reboot as a changed bootCount or a smaller uptime;
//   * previous: where each task was just before the reset (breadcrumbs below);
//   * coredump: whether the coredump partition holds an image (read-only check;
//     nothing here ever erases it).
//
// Breadcrumbs. Each task writes only its own 32-bit word in RTC slow memory,
// (code << 24) | (millis() & 0xFFFFFF), one store per step. RTC slow memory
// keeps its content through software, panic and watchdog resets (not a loss of
// power), so the next boot reports the last step of COM, LCD and HMI plus the
// last HMI heartbeat (uptime). Nothing is flushed or waited for.
//
// 1.0.0-cc5.2: LCD and COM also store a full millis() heartbeat at their wait step
// (HMI's is the uptime word), so previous.{hmi,lcd,com}.aliveMs say when each task last
// completed a pass, previous.lastAliveMs is the newest of them, and each breadcrumb time
// is resolved against its own task's heartbeat (a task hung for hours no longer shifts
// the others). The RTC layout changed, so the magic changed with it: the first boot of
// cc5.2 after another firmware reports rtcRetained false.

// COM breadcrumb: operation (5 bits) and stage (3 bits). 1.0.0-cc5.3 appends the media
// operations (ARTWORK2.md section 8); the older values keep their numbers. They no longer fit
// the 4-bit operation field of cc5.2, so the RTC layout (and its magic) changed.
enum CCComOp : uint8_t {
    CC_COM_OP_NONE = 0, CC_COM_OP_CAPABILITIES, CC_COM_OP_DIAG, CC_COM_OP_ART_BEGIN, CC_COM_OP_ART_DATA,
    CC_COM_OP_ART_COMMIT, CC_COM_OP_ART_OTHER, CC_COM_OP_RELEASE, CC_COM_OP_CONTROL, CC_COM_OP_FRAME,
    CC_COM_OP_NATIVE, CC_COM_OP_PARSE_ERROR, CC_COM_OP_OVERSIZE,
    CC_COM_OP_MEDIA_BEGIN, CC_COM_OP_MEDIA_DATA, CC_COM_OP_MEDIA_COMMIT, CC_COM_OP_MEDIA_HAVE, CC_COM_OP_MEDIA_OTHER
};
enum CCComStage : uint8_t {
    CC_COM_STAGE_WAIT = 0,   // vTaskDelay between passes
    CC_COM_STAGE_READ,       // draining Serial into the line buffer
    CC_COM_STAGE_LINE,       // handling one complete line (arg: its length, then op-specific)
    CC_COM_STAGE_SERVICE,    // cc_service(): ready / released replies
    CC_COM_STAGE_EVENTS      // queued messages, knob and key events, idle notice
};
// 1.0.0-cc5.3 appends CC_LCD_STEP_DECODE: an artwork2 cover JPEG decode (ROM TJpgDec) inside
// a render, so a stall in the decoder shows as "decode", not "render". The older values keep
// their numbers.
enum CCLcdStep : uint8_t {
    CC_LCD_STEP_WAIT = 0, CC_LCD_STEP_HOST, CC_LCD_STEP_RENDER, CC_LCD_STEP_REFRESH, CC_LCD_STEP_TIMERS,
    CC_LCD_STEP_DIAG, CC_LCD_STEP_DECODE
};
// 1.0.0-cc5.2 appends the LED transport steps (cc_led_rmt.h): a frame on the ring, a
// frame on the buttons, and a channel recovery. The older values keep their numbers.
enum CCHmiStep : uint8_t {
    CC_HMI_STEP_WAIT = 0, CC_HMI_STEP_CONFIG, CC_HMI_STEP_BUTTONS, CC_HMI_STEP_HID, CC_HMI_STEP_LEDS,
    CC_HMI_STEP_SHOW, CC_HMI_STEP_SHOW_RING, CC_HMI_STEP_SHOW_BUTTONS, CC_HMI_STEP_LED_RECOVER
};
// Where Serial's receive queue (8 KB since 1.0.0-cc5.3) was allocated (main.cpp).
enum CCRxQueue : uint8_t { CC_RX_QUEUE_UNKNOWN = 0, CC_RX_QUEUE_INTERNAL, CC_RX_QUEUE_PSRAM, CC_RX_QUEUE_DEFAULT };

// First statement of setup(): reads the reset reasons and the previous boot's
// RTC breadcrumbs, then starts this boot's (bootCount + 1). Idempotent.
void cc_boot_begin();
// setup(), before the threads start: read-only core dump presence check.
void cc_boot_check_coredump();
void cc_boot_rx_queue(uint8_t where, uint32_t bytes);   // CCRxQueue and the size actually configured
// capabilities artwork2.rxBytes (1.0.0-cc5.3): the queue size while the queue is in internal
// RAM (ours, or the core's default 256-byte one), 0 when it landed in PSRAM. ARTWORK2.md
// section 1 defines rxBytes as the internal-RAM queue, and the host negotiates unpaced
// transport only for 8192, so a PSRAM-resident queue keeps the host paced (v1 art).
uint32_t cc_boot_rx_queue_internal_bytes();

// 1.0.0-cc5.5 (F1, safety and measurement; ideas from Karl Malota's idf_upgrade branch). All read only
// and additive to {"diag":"?"} (cc_diag_live() appends them; the capabilities are unchanged):
//   * setup(), HmiThread::init_usb(): whether TinyUSB accepted the MIDI and HID interfaces
//     ("usbMidiOk", "usbHidOk"; booleans). A refusal never stops or loops the boot.
//   * setup(), HmiThread::init_pd(), before the threads start: the STUSB4500 RDO_STATUS read (I2C 0x28,
//     register 0x91, four bytes LSB first). "pdRead" (boolean: the transfer succeeded), "pdPdo" (bits
//     30:28 of the RDO: the requested source PDO's position 1..7; 0 = no explicit contract, i.e. Type-C
//     5 V, or the read failed), "pdVolts" (the voltage of our sink PDO at that position, read from the
//     chip's DPM_SNK_PDO table and rounded to whole volts: 5 or 9 as init_pd() programs it; 0 = unknown:
//     no contract, a position past the three sink PDOs or a failed read) and, when the read worked,
//     "pdRdo" (the 32-bit word). The motor driver runs from VBUS: the FOC task scales voltage_power_supply
//     with the contract (cc_supply_volts(), FW-BUG-022: it fails safe high when the voltage is unknown).
//   * HMI task: a HID report TinyUSB refused and that is retried on the next pass ("hidRetries", since
//     boot; hmi_thread.cpp handleHid()).
//   * FOC task, once per loop pass (cc_diag_foc_pass(); single writer, plain 32-bit stores, no lock):
//     "focLoopHz" (loop passes in the last completed second; 0 when none completed for 2 s),
//     "focLoopUsMax" (the longest pass-to-pass interval since the previous diag read, µs, reset on read),
//     "uqAbsMax" (the largest |motor.voltage.q| since the previous diag read, in millivolts, reset on
//     read), "uqCapMs" (milliseconds since boot with |Uq| at the motor voltage cap) and "uqCapMv" (that
//     cap, motor.voltage_limit, in millivolts: 2200).
void cc_boot_usb(bool midiOk, bool hidOk);
void cc_boot_pd(bool readOk, uint32_t rdo, uint32_t sinkMillivolts);
// 1.0.0-cc5.7 (plan F2): the PD contract's voltage in whole volts as diag pdVolts reports it (0 = no contract,
// a failed read, a position past the sink table, or before init_pd()).
uint32_t cc_boot_pd_volts();
// FW-BUG-022: the contract as the FOC task needs it to pick the driver supply (cc_supply_volts()). Returns whether
// init_pd() ran and its RDO read succeeded; position = RDO bits 30:28 (0 = no explicit contract), millivolts = our
// sink PDO at that position (0 = unknown), nvmRewritten = init_pd() rewrote the sink PDO table this boot (then the
// read may predate the new table, so any contract is assumed to be 20 V; no contract stays 5 V).
bool cc_boot_pd_contract(uint32_t& position, uint32_t& millivolts, bool& nvmRewritten);
// FW-BUG-022: init_pd() calls it right after it rewrites the STUSB4500 sink PDO table (setup(), before the threads).
void cc_boot_pd_nvm_rewritten();
// 1.0.0-cc5.7 (r4 FEEL + SOUND, HAPTICS.md "Diag"; additive, read only), appended by cc_diag_live():
//   "supplyVolts" (the supply the driver scales with, whole volts: 5 with no contract, the contract's voltage when
//   it is known, else assumed high: the highest sink PDO, 9, or 20 after a sink table rewrite), "supplyAssumed"
//   (true when that voltage was assumed, FW-BUG-022), "feel" (the claim's token, "" = legacy),
//   "reducedHaptics", "soundLevel" (0..3), "fxPlayed" / "fxPulses" / "fxDropped" (effect player counters),
//   "wallHits" / "wallDir" (cc_wall.h), "foldbackPct" (wall force now, 50..100) / "foldbackEvents",
//   "tripLatched" / "spinTrips" (the self-spin trip), "offlineVolume" (the Consumer volume mode runs),
//   "calState" / "calOutcome" (recalibration), "audioReady", "audioPlayed", "audioUnderruns", "audioDropped",
//   "audioSuperseded" (waiting sound requests outranked by a louder one, or by a newer one of equal gain,
//   FW-BUG-021).
void cc_diag_hid_retry();                       // HMI task only
void cc_diag_foc_pass(uint32_t nowUs, float uq, float capV);   // FOC task only

// Breadcrumbs (each called only by its own task).
void cc_crumb_com(uint8_t op, uint8_t stage, uint32_t arg);
void cc_crumb_com_stage(uint8_t stage);   // keeps the last op and arg
void cc_crumb_com_line();                 // one more complete line handled this boot
void cc_crumb_lcd(uint8_t step);
void cc_crumb_hmi(uint8_t step);          // CC_HMI_STEP_WAIT also stores the uptime heartbeat

// Adds resetReason, resetCode, rtcReset, bootCount, rtcRetained, uptimeMs,
// previous{...} (only when the RTC state survived), coredump{...}, rxQueue and lvglLayout
// ("ok", or "mixed" when LVGL and src/ were compiled with different lv_conf.h files; FW-BUG-017)
// and firmwareBuild (FW-PUB-004: the internal build id, cc_fw_build(), since settings "firmwareVersion"
// carries the public version).
void cc_diag_boot(JsonObject diag);

// ---------------------------------------------------------------------------
// Task liveness and the task watchdog (1.0.0-cc5.2).
//
// Why: in 1.0.0-cc5.1 the HMI task blocked for good inside FastLED.show() while LCD,
// COM and FOC kept running. Nothing noticed: the task watchdog watched only IDLE0 (which
// kept running), and diag had no per-task liveness, so the host saw a working knob with
// frozen LEDs, dead buttons and releases that never completed.
//
// Liveness: every breadcrumb stores millis() in a RAM word of its task, and every FOC
// cc_take_request() pass stores the RTOS tick count (1 ms): one aligned 32-bit store, no
// lock. {"diag":"?"} reports each task's age (now minus that store): hmiAgeMs, lcdAgeMs,
// comAgeMs (about 0: COM answers diag) and focAgeMs, with each task's current step.
enum CCLiveTask : uint8_t { CC_LIVE_HMI = 0, CC_LIVE_LCD, CC_LIVE_COM, CC_LIVE_FOC, CC_LIVE_COUNT };
void cc_live_foc();                        // FOC thread, once per loop (through cc_take_request)
// Adds hmiAgeMs, lcdAgeMs, comAgeMs, focAgeMs, hmiStep, lcdStep, comOp, comStage, taskWdtS
// and wdtTasks (the tasks subscribed to the task watchdog now); since 1.0.0-cc5.4 also the LED
// frame fields ledFps, ledRenderUsMax (reset by this call), ledRenderUsAvg, ledMode,
// ledShowGapMsMax (reset by this call) and ledLateShows (cc_diag_led_frame() below); since
// 1.0.0-cc5.5 the F1 fields above (usbMidiOk ... uqCapMv; focLoopUsMax and uqAbsMax reset by this call).
void cc_diag_live(JsonObject diag);

// artwork2 (1.0.0-cc5.3, ARTWORK2.md section 8; COM task): rxQueueBytes, mediaCommits,
// mediaErrors, mediaEvictions (cc_media), jpegDecodes, jpegDecodeErrors, jpegDecodeMsMax and
// jpegDecodeMsLast (cc_jpeg, counted by the LCD thread's decodes).
void cc_diag_media(JsonObject diag);

// LCD pipeline (1.0.0-cc5.4, PRESENTATION_V5 12.3, VOC-K1c; COM task): one cc_lcd_perf_read()
// copy of the LCD thread's counters (cc_display.h CCLcdPerf; the read resets lcdFpsAnimMin),
// written by cc_diag_lcd_perf_fields() below. The other four 12.3 fields (enterMsLast,
// enterMsMax, holdEvents, holdDeferred) are control_center.cpp's.
void cc_diag_lcd_pipeline(JsonObject diag);
// The LCD fields of one CCLcdPerf copy: lcdFps, lcdFpsAnimMin, lcdRefrUsMax, lcdRefrUsAvg,
// lcdRenderUsMax, lcdFlushUs, lcdPxPerRefr, lcdFullRefrs, lcdLateRefrs, lcdMaxGapMs, lcdBusyPct,
// core0IdlePct, lcdSpiHz, lcdDma, lcdPeriodMs, artAsync, artDecodeRequests, artDecodeAborts,
// artDecodeStale and stackArtDec (0 when artAsync is false), then (12.6 errata E-lcd) lcdMosiSig
// (an integer: 103 = the LCD data line is FSPID, 102 = binary A's defect) and "build" (the ladder
// letter "A".."F" of CC_BUILD_BINARY; absent when the image has no ladder id). lcdDma and artAsync
// are JSON booleans: with lcdPeriodMs they identify the pipeline of binary A, B or C (12.6), and
// the host tooling (nanod_cc5_tooling.lcd_binary) accepts binary A at a period other than 16 ms
// only for `true`; "build" tells D from A and E from C. A template so that the host wiring build
// (media_tests.py), which has no LVGL and so no cc_display.h, runs this same code on a stand-in of
// the struct.
inline const char* cc_diag_build_letter(uint32_t binary) {
    static const char* const kLetters[] = {"A", "B", "C", "D", "E", "F"};   // F: 1.0.0-cc5.5 (12 ms)
    return binary >= 1u && binary <= 6u ? kLetters[binary - 1u] : nullptr;
}
template <typename Perf> void cc_diag_lcd_perf_fields(JsonObject d, const Perf& p) {
    d["lcdFps"] = p.lcdFps; d["lcdFpsAnimMin"] = p.lcdFpsAnimMin;
    d["lcdRefrUsMax"] = p.lcdRefrUsMax; d["lcdRefrUsAvg"] = p.lcdRefrUsAvg;
    d["lcdRenderUsMax"] = p.lcdRenderUsMax; d["lcdFlushUs"] = p.lcdFlushUs;
    d["lcdPxPerRefr"] = p.lcdPxPerRefr; d["lcdFullRefrs"] = p.lcdFullRefrs;
    d["lcdLateRefrs"] = p.lcdLateRefrs; d["lcdMaxGapMs"] = p.lcdMaxGapMs;
    d["lcdBusyPct"] = p.lcdBusyPct; d["core0IdlePct"] = p.core0IdlePct; d["lcdSpiHz"] = p.lcdSpiHz;
    d["lcdDma"] = p.lcdDma != 0; d["lcdPeriodMs"] = p.lcdPeriodMs; d["artAsync"] = p.artAsync != 0;
    d["artDecodeRequests"] = p.artDecodeRequests; d["artDecodeAborts"] = p.artDecodeAborts;
    d["artDecodeStale"] = p.artDecodeStale; d["stackArtDec"] = p.artAsync ? p.stackArtDec : 0u;
    d["lcdMosiSig"] = p.lcdMosiSig;
    if (const char* build = cc_diag_build_letter(p.buildBinary)) d["build"] = build;
}

// LED transport counters (cc_led_rmt.cpp; COM task): "ledTxTimeouts" and "ledWriteErrors"
// (both strips), and "led":{"ring":{...},"buttons":{...}} with frames, txTimeouts,
// writeErrors, recoveries, skipped, maxWaitUs, lastErr and installed per strip.
void cc_led_diag(JsonObject diag);

// "Warm · alive" LEDs (1.0.0-cc5.4, ALIVE.md 10.1): who drives the LEDs and what the engine
// costs. Modes: OFFLINE = the engine's offline state (unclaimed, section 8.1), ALIVE = the
// engine on a claimed control, NATIVE = the native handover (the profile's own LED path).
enum CCLedMode : uint8_t { CC_LED_MODE_OFFLINE = 0, CC_LED_MODE_ALIVE, CC_LED_MODE_NATIVE };
// HMI task, once per FastLED.show(): the mode the frame was drawn in, and (rendered true) the
// microseconds of engine render + section 9 output + the write into the LED buffers.
// cc_diag_live() reports them (so control_center.cpp calls nothing new): "ledFps" (frames
// shown in the last full second; 0 when no frame closed a second within the last 2 s),
// "ledRenderUsMax" (the longest engine frame since the previous diag read, then reset),
// "ledRenderUsAvg" (the mean over the engine frames of the last full second; 0 when the native
// path showed all of them) and "ledMode" ("alive", "offline" or "native"; since [M29] "native"
// lasts until the next claim). [r2] ALIVE.md 10.1: nowMs is the show's own time, and
// "ledShowGapMsMax" (the longest interval between two shows since the previous diag read, then
// reset) and "ledLateShows" (intervals over 20 ms since boot) come from it.
void cc_diag_led_frame(uint32_t nowMs, uint8_t mode, bool rendered, uint32_t renderUs);

// Task watchdog: HMI, LCD and COM subscribe and feed it once per loop pass (COM also
// after every command line it handles), so a task that stops making progress for
// CC_TASK_WDT_SECONDS panics (resetReason task_wdt, a core dump in flash, the RTC
// breadcrumbs of the hung task) instead of freezing silently. IDLE0 stays subscribed
// with the same timeout. FOC is not subscribed (a busy loop next to the haptic code);
// focAgeMs covers it. COM unsubscribes around the SPIFFS/NVS `save` and `load`
// commands, the only flash writes these tasks make (a SPIFFS garbage collection may take
// seconds); HMI and LCD never write flash, and a flash write elsewhere only stalls them
// for single erase/program operations (well under a second each).
constexpr uint32_t CC_TASK_WDT_SECONDS = 10;
void cc_wdt_begin();                       // setup(), before the threads start
void cc_wdt_watch(uint8_t task);           // CC_LIVE_HMI/LCD/COM: subscribe the calling task
void cc_wdt_unwatch(uint8_t task);         // unsubscribe the calling task (COM, around save/load)
void cc_wdt_feed();                        // the calling task made progress
