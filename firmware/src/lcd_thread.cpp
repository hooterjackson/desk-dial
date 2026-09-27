#include <Arduino.h>
#include "lcd_thread.h"
#include "control_center.h"
#include "cc_display.h"
#include "cc_artwork.h"
#include "cc_media.h"
#include "cc_jpeg.h"
#include "cc_diag.h"
#include "cc_art_decode.h"
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <esp_freertos_hooks.h>
#include <driver/spi_master.h>
#include <esp_rom_gpio.h>
#include <soc/soc.h>
#include <soc/gpio_reg.h>
#include <soc/gpio_sig_map.h>
#include <soc/spi_periph.h>

// The HMI's native button edge counter for the offline sub-line (PRESENTATION_V5.md 8.10; AL 8.1 "a
// button state change while unclaimed") is control_center.h cc_native_button_seq(): +1 for every
// debounced press and release its unclaimed (native) button branch handles (hmi_thread.cpp calls
// cc_native_button_edge() there), since boot, wrapping; one aligned 32-bit word that only the HMI
// task writes, read from this thread.

// 1.0.0-cc5.4 LCD pipeline (PRESENTATION_V5.md section 12.1; the build ladder of 12.6). The three
// flags select the pipeline of binary A (the defaults, also D), B or C (also E); {"diag":"?"}
// reports which (lcdDma, lcdPeriodMs, artAsync):
//   CC_LCD_DMA        R3: 1 = two static 11,520 B partial buffers flushed by TFT_eSPI DMA; 0 = cc5.3's
//                     single blocking buffer, flushed as lv_tft_espi did (call for call). Both pipelines
//                     use the one TFT_eSPI instance below and its one begin().
//   CC_LCD_PERIOD_MS  R4: LVGL refresh and animation period (16 in A; 33 in B and C). Only with R2+R3.
//   CC_ART_ASYNC      R5: cover JPEG decode in the ArtDecode task (cc_art_decode.h) (1 in A only).
//   CC_BUILD_BINARY   the ladder binary this image is (12.6 errata E-lcd): 0 = no ladder id (the
//                     source default), 1..5 = A..E. Reported as diag "build" ("A".."E"; absent at 0)
//                     and kept in the image as the marker "cc-build-binary:<n>" (cc_build_binary_marker
//                     below). build_nanod_cc5.py passes it for D (4) and E (5); A, B and C were built
//                     before it existed and carry neither.
#ifndef CC_LCD_DMA
#define CC_LCD_DMA 1
#endif
#ifndef CC_LCD_PERIOD_MS
#define CC_LCD_PERIOD_MS 16
#endif
#ifndef CC_ART_ASYNC
#define CC_ART_ASYNC 1
#endif
#ifndef CC_BUILD_BINARY
#define CC_BUILD_BINARY 0
#endif
#if CC_BUILD_BINARY < 0 || CC_BUILD_BINARY > 5
#error "CC_BUILD_BINARY must be 0 (no ladder id) or 1..5 (binary A..E)"
#endif
// A letter (-DCC_BUILD_BINARY=D) reads as 0 in #if; as C++ it is an unknown name and fails here.
static_assert(CC_BUILD_BINARY >= 0 && CC_BUILD_BINARY <= 5, "CC_BUILD_BINARY: a number 0..5");

// TODO: See if can do it more elegantly from LVGL tfteSPI driver
#include <TFT_eSPI.h>
// The panel's only TFT_eSPI instance, in both pipelines: it flushes LVGL and handles rotation, with one
// begin() (LcdThread::run). The blocking build (CC_LCD_DMA 0, binaries C and E) reproduces lv_tft_espi's
// flush call for call (startWrite / setAddrWindow / pushColors / endWrite, cc_flush) but not its second
// instance: lv_tft_espi_create() is not called, so nothing else re-attaches the SPI pins.
TFT_eSPI tft;

// The LCD's SPI host. TFT_eSPI drives the panel on FSPI (SPI2_HOST, TFT_eSPI_ESP32_S3.c) unless
// USE_HSPI_PORT moves it to SPI3, which the encoder already owns (foc_thread.cpp). The MOSI
// re-attach below and the lcdMosiSig reading assume SPI2.
#ifdef USE_HSPI_PORT
#error "USE_HSPI_PORT: HSPI (SPI3) belongs to the encoder (foc_thread.cpp); the LCD stays on FSPI (SPI2)"
#endif
// GPIO matrix output signals of SPI2's data lines (gpio_sig_map.h): diag lcdMosiSig reads the one
// routed to TFT_MOSI. FSPID (103) is MOSI; FSPIQ (102) is MISO, what binary A's initDMA left there.
static_assert(FSPID_OUT_IDX == 103, "ESP32-S3 FSPID output signal (diag lcdMosiSig 103 = good)");
static_assert(FSPIQ_OUT_IDX == 102, "ESP32-S3 FSPIQ output signal (diag lcdMosiSig 102 = binary A's defect)");

// Binary A's dark panel (PRESENTATION_V5.md 12.6 errata E-lcd). platformio.ini sets TFT_MISO -1 (the
// panel has no MISO wire); on the ESP32-S3 TFT_eSPI_ESP32_S3.h then redefines TFT_MISO as TFT_MOSI
// (GPIO 4), and tft.initDMA() passes mosi = miso = 4 to spi_bus_initialize(). IDF 4.4 routes the pin's
// output to FSPID (MOSI) first and then, in its MISO step, to FSPIQ (MISO), which the controller does
// not drive in one-bit mode: from initDMA on, no command and no pixel reached the GC9A01, while every
// ESP32-side counter looked healthy. Arduino's SPI.begin() (cc5.3 and the blocking build) attaches
// MOSI last, so it never had the problem. This puts FSPID back on TFT_MOSI right after initDMA, with
// the signal IDF itself used for MOSI (spi_periph_signal[SPI2_HOST].spid_out, 103). It is called in
// every DMA build (a no-op when MISO is a separate pin). The name is what the build gate looks for in
// the ELF (nanod_cc5_tooling lcd_mosi_gate_problems: a DMA build whose effective MISO equals MOSI
// must link it), hence C linkage and never inlined.
#if CC_LCD_DMA
extern "C" __attribute__((noinline)) void cc_lcd_mosi_reattach() {
    esp_rom_gpio_connect_out_signal(TFT_MOSI, spi_periph_signal[SPI2_HOST].spid_out, false, false);
}
#endif

// diag lcdMosiSig: the GPIO matrix output signal routed to TFT_MOSI now (GPIO_FUNCn_OUT_SEL_CFG_REG
// bits 8:0, read only). 103 (FSPID) is a working data line; 102 (FSPIQ) is binary A's defect; 256
// would be a plain GPIO output.
static uint32_t cc_lcd_mosi_sig() {
    return static_cast<uint32_t>(REG_GET_FIELD(GPIO_FUNC0_OUT_SEL_CFG_REG + 4u * TFT_MOSI, GPIO_FUNC0_OUT_SEL));
}

// The build id marker (CC_BUILD_BINARY above), in flash (.rodata). The tooling finds its bytes in
// the image (binary_image_problems); cc_build_binary() reads the digit back through a volatile
// pointer, so the compiler cannot fold it away and --gc-sections keeps the marker.
#define CC_BUILD_STR_(x) #x
#define CC_BUILD_STR(x) CC_BUILD_STR_(x)
extern "C" {
extern const char cc_build_binary_marker[];
const char cc_build_binary_marker[] = "cc-build-binary:" CC_BUILD_STR(CC_BUILD_BINARY);
}
static_assert(sizeof(cc_build_binary_marker) == sizeof("cc-build-binary:") + 1,
              "CC_BUILD_BINARY: one digit (\"cc-build-binary:<n>\")");
static uint32_t cc_build_binary() {
    const char* volatile marker = cc_build_binary_marker;
    const char digit = marker[sizeof("cc-build-binary:") - 1];
    return digit >= '1' && digit <= '5' ? static_cast<uint32_t>(digit - '0') : 0u;
}


// TODO: Move to PIO Build Flags
static const uint8_t LEDC_CH_LCD_BKL = 0; // LEDC Channel for LCD Backlight
static uint16_t LEDC_MAX_BLK = 3200; // Maximum Brightness for Active Mode
static uint16_t LEDC_MIN_BLK = LEDC_MAX_BLK / 10; // Minimum Brightness for Idle Mode

static uint8_t last_orientation = -1;

#define DRAW_BUF_SIZE (TFT_WIDTH * TFT_HEIGHT / 10 * (LV_COLOR_DEPTH / 8)) // 240*240/10*2 = 11520 bytes for 1/10 screen size
uint32_t draw_buf[DRAW_BUF_SIZE / 4];   // Declare a buffer for drawing
#if CC_LCD_DMA
// R3: LVGL renders into one buffer while DMA sends the other (both static .bss, internal RAM, 12.4).
uint32_t draw_buf2[DRAW_BUF_SIZE / 4];
#endif

// Waits for the panel DMA to finish (R3): before any other panel access and before an
// acknowledgement that must mean "on glass". A no-op in the blocking build.
static inline void cc_panel_wait() {
#if CC_LCD_DMA
    tft.dmaWait();
#endif
}


// LCD task stack (1.0.0-cc5.1): 5,588 B were used after the cc5 stress (2,604 B
// free of 8192): LVGL refresh through six nested object levels, label drawing
// and blending, plus slides and layers. 12288 B is 2.2x that measured peak.
static constexpr uint32_t kLcdStackBytes = 12288;

LcdThread::LcdThread(const uint8_t task_core) : Thread("LCD", kLcdStackBytes, 1, task_core) {
    _q_lcd_in = xQueueCreate(2, sizeof( LcdCommand ));
    last_command.type = LCD_LAYOUT_DEFAULT;
    last_command.title = nullptr;
    last_command.data1 = nullptr;
    last_command.data2 = nullptr;
    last_command.data3 = nullptr;
    last_command.data4 = nullptr;
};

LcdThread::~LcdThread() {}


void LcdThread::put_lcd_command(LcdCommand& cmd) {
    xQueueSend(_q_lcd_in, &cmd, (TickType_t)0);
};


void LcdThread::handleLcdCommand() {
    LcdCommand cmd;
    if (xQueueReceive(_q_lcd_in, &cmd, (TickType_t)0)) {
        // TODO Implement LCD Command Handling
        last_command = cmd;
    }
};

/* 
    Tasker for Profile data update - updates every 200ms (5Hz)
    Screen: ui_valueScreen
    Checks for last_command and updates Profile Name and Description
*/
static void lcd_manager(lv_timer_t * lcd_cmd_timer) {
    
    /* 
    Listen for Orientation change 
    */
    
    uint8_t device_orientation = DeviceSettings::getInstance().deviceOrientation;
    if (last_orientation != device_orientation) {
        cc_panel_wait();   // R3: no rotation while a DMA flush is on the wire
        if (device_orientation == 0) {
            tft.setRotation(2);
        } else if (device_orientation == 1) {
            tft.setRotation(3);   
        } else if (device_orientation == 2) {
            tft.setRotation(0);
        } else if (device_orientation == 3) {
            tft.setRotation(1);
        }
    last_orientation = device_orientation;
    lv_obj_invalidate(lv_scr_act());
    };

    /*
        Handle LCD Command 
    */

    lcd_thread.handleLcdCommand();

    if (lv_scr_act()==ui_valueScreen){

        if (lcd_thread.last_command.type == LCD_LAYOUT_DEFAULT){
            if (lcd_thread.last_command.title==nullptr || lcd_thread.last_command.title->length()==0) {
                lv_obj_add_flag(ui_profileName, LV_OBJ_FLAG_HIDDEN); // Hide Profile Name
            } else {
                lv_obj_remove_flag(ui_profileName, LV_OBJ_FLAG_HIDDEN); // Show Profile Name
                lv_label_set_text_fmt(ui_profileName, "%s", lcd_thread.last_command.title->c_str()); // Set Profile Name
            }
            if (lcd_thread.last_command.data1==nullptr  || lcd_thread.last_command.data1->length()==0) {
                lv_obj_add_flag(ui_profileDesc, LV_OBJ_FLAG_HIDDEN);    // Hide Profile Description
            } else {
                lv_obj_remove_flag(ui_profileDesc, LV_OBJ_FLAG_HIDDEN); // Show Profile Description
                lv_label_set_text_fmt(ui_profileDesc, "%s", lcd_thread.last_command.data1->c_str()); // Set Profile Description
            }
            if (lcd_thread.last_command.data3==nullptr || lcd_thread.last_command.data3->length()==0) {
                lv_obj_add_flag(ui_msgModal2, LV_OBJ_FLAG_HIDDEN); // Hide Modal
            } else {
                static uint32_t startTime = 0;
                static const uint32_t interval = 5000; // 5 seconds

                if (startTime == 0) {
                    startTime = millis();
                    
                    lv_obj_remove_flag(ui_msgModal2, LV_OBJ_FLAG_HIDDEN); // Show Modal
                } else {
                    if (millis() - startTime >= interval) {
                        lv_obj_add_flag(ui_msgModal2, LV_OBJ_FLAG_HIDDEN); // Hide Modal
                        lcd_thread.last_command.data3 = nullptr; // Reset Command
                        startTime = 0; // Reset the start time
                    }
                }
            }
        }    
    }
}

/* 
    Tasker for sprite-sheet animation update - updates every 2 seconds - 0.5Hz
    Screen: ui_valueScreen
    Screen: ui_profSelectScreen
    Updates Idle Cat Animation and Profile Selection Arrow Animation
*/
static void idle_anim_handler(lv_timer_t * animtimer) {
    if(com_thread.global_sleep_flag) { // Dont run animation rendering in background if in sleep mode
    if (lv_scr_act()==ui_valueScreen) // Value Screen  
        {
    static uint8_t fps = 0;
    switch(fps) {
        case 0:
            lv_label_set_text(ui_IdleCat, "A");
            lv_label_set_text(ui_IdleCatShadow, "E");
            break;
        case 1:
            lv_label_set_text(ui_IdleCat, "B");
            lv_label_set_text(ui_IdleCatShadow, "E");
            break;
        case 2:
            lv_label_set_text(ui_IdleCat, "C");
            lv_label_set_text(ui_IdleCatShadow, "D");
            lv_obj_set_x(ui_IdleCatShadow, -4);
            break;
        case 3:
            lv_label_set_text(ui_IdleCat, "B");
            lv_label_set_text(ui_IdleCatShadow, "E");
            lv_obj_set_x(ui_IdleCatShadow, 0);
            break;
    }
    fps = (fps + 1) % 4; // 4 Frames every 2 seconds
}
if (lv_scr_act()==ui_profSelectScreen) // Profile Selection Screen
{
    static uint8_t fps = 0;
    switch(fps) {
        case 0:
            lv_obj_set_x( ui_arrInd, 17 );
            break;
        case 1:
            lv_obj_set_x( ui_arrInd, 12 );
            break;
        
    }
    fps = (fps + 1) % 2; // 2 Frames every 2 seconds
}
    }
}

/*
    Tasker for Knob Position tracking - Updates every 16ms (60Hz)
    Screen: ui_valueScreen
    Screen: ui_profSelectScreen
*/


static void counter_handler(lv_timer_t * postimer) {
    static uint16_t last_pos = -1; // Default Last Position
    static bool overlay_toggle = false; // Default Overlay Toggle
    uint16_t pos = foc_thread.pass_cur_pos(); // Get Current Position from FOC Thread
    uint16_t end_pos = foc_thread.pass_end_pos(); // Get End Position from FOC Thread
    static uint16_t last_end_pos = 0xFFFF;
    
    if (pos != last_pos) {
       
       if (lv_scr_act()==ui_valueScreen){
           lv_label_set_text_fmt(ui_posind, "%d", pos);
           lv_label_set_text_fmt(ui_posindSha, "%d", pos);
           if (end_pos != last_end_pos) {
               lv_arc_set_range(ui_Arc1, 0, end_pos);
               last_end_pos = end_pos;
               // Don't update arc range if end_pos is same as last_end_pos
           }
           lv_arc_set_value(ui_Arc1, pos);
           last_pos = pos; // Update Last Position
       }
       if (lv_scr_act()==ui_profSelectScreen){
           lv_label_set_text_fmt(ui_pCount, "%d", pos); // Set Position Indicator
           if(last_pos != pos){
           lv_roller_set_selected(ui_profList, pos, LV_ANIM_ON); // Set Roller to Current Position - Animate ON
           last_pos = pos; // Update Last Position
           }
       }
    }
        
    if (com_thread.global_sleep_flag && overlay_toggle) {
        
        lv_obj_remove_flag( ui_IdleCat, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag( ui_IdleCatShadow, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag( ui_dataScreen, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag( ui_msgModal2, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_arc_color(ui_Arc1, lv_color_hex(0x565656), LV_PART_INDICATOR | LV_STATE_DEFAULT );
        ledcWrite(0, LEDC_MIN_BLK); // Set Backlight to Min Brightness
        overlay_toggle = !overlay_toggle;
    }
    if (!com_thread.global_sleep_flag && !overlay_toggle){
        
        lv_obj_add_flag( ui_IdleCat, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag( ui_IdleCatShadow, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag( ui_dataScreen, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_arc_color(ui_Arc1, lv_color_hex(0xFF7D00), LV_PART_INDICATOR | LV_STATE_DEFAULT );
        ledcWrite(0, LEDC_MAX_BLK); // Set Backlight to Max Brightness
        overlay_toggle = !overlay_toggle;          
    }
}


namespace {
lv_obj_t* cc_screen = nullptr;
lv_obj_t* cc_previous_screen = nullptr;
uint32_t cc_display_version = 0;
uint32_t cc_display_id = 0;
bool cc_display_visible = false;
// Two 240x240 RGB565 artwork display buffers (PSRAM, front and back; ARTWORK2.md section 7),
// allocated once in run(). With one of them the renderer writes new covers in place (and R5 stays
// off); with none the host screen renders text only.
uint8_t* cc_art240[2] = {nullptr, nullptr};
bool cc_art_async = false;           // R5 wired into the renderer at run time (diag artAsync)
// The offline layer (PRESENTATION_V5.md 8.10): the FOC position and the native button edge
// counter when it appeared; a change of either is the first native input (AL 8.1: an FOC position
// change or a button state change while unclaimed). Reset on every claim and handback.
CCOfflineInput cc_offline_in = {};
// lcdLateRefrs / lcdMaxGapMs on the animation cadence (cc_display.h CCAnimCadence), sampled after
// every lv_timer_handler() pass of this thread.
CCAnimCadence cc_cadence = {};

// ------------------------------------------------------------- diag (12.3) --
// Written by this thread under perfLock, read (copied) by the COM thread in cc_lcd_perf_read().
portMUX_TYPE perfLock = portMUX_INITIALIZER_UNLOCKED;
CCLcdPerf perf = {};
// Accumulators of the current 1 s window (this thread only).
uint32_t winStartMs = 0, winFrames = 0, winFlushUs = 0, winBusyUs = 0;
bool winAnimated = false;
uint32_t refrStartUs = 0, refrPx = 0, refrCount = 0;
uint64_t refrUsSum = 0;
// core0IdlePct: the idle hook on core 0 counts the time between its calls while they are close
// together (the idle task looping between ticks); a gap longer than kIdleGapUs means another task
// ran. An approximation: time a task spends inside a short gap is counted as idle.
constexpr uint32_t kIdleGapUs = 1500;
volatile uint32_t idleAccumUs = 0;
volatile int64_t idleLastUs = 0;
uint32_t idleSeenUs = 0;

bool IRAM_ATTR cc_idle_hook() {
    const int64_t now = esp_timer_get_time();
    const int64_t gap = now - idleLastUs;
    if (gap > 0 && gap < kIdleGapUs) idleAccumUs += static_cast<uint32_t>(gap);
    idleLastUs = now;
    return true;   // the idle task may wait for the next interrupt
}

void perfRefrStart(lv_event_t*) {
    refrStartUs = micros();
    refrPx = 0;
}

void perfRefrReady(lv_event_t*) {
    // "+ the final dmaWait": a refresh counts as drawn once its last chunk is on glass.
    cc_panel_wait();
    const uint32_t us = micros() - refrStartUs;
    if (refrPx == 0) return;                  // nothing was invalid: no panel refresh
    ++winFrames;
    ++refrCount;
    refrUsSum += us;
    winAnimated = winAnimated || lv_anim_count_running() > 0;
    portENTER_CRITICAL(&perfLock);
    if (us > perf.lcdRefrUsMax) perf.lcdRefrUsMax = us;
    perf.lcdRefrUsAvg = static_cast<uint32_t>(refrUsSum / refrCount);
    perf.lcdPxPerRefr = refrPx;
    if (refrPx >= 240u * 240u) ++perf.lcdFullRefrs;
    portEXIT_CRITICAL(&perfLock);
    // lcdLateRefrs / lcdMaxGapMs are not taken here: an eased tween's value plateaus flush nothing,
    // so flush-to-flush intervals count them as late (cc_display.h CCAnimCadence; perfCadence()).
}

// After every lv_timer_handler() pass: the animation cadence (lcdLateRefrs, lcdMaxGapMs).
void perfCadence() {
    if (!cc_anim_cadence_poll(cc_cadence)) return;
    portENTER_CRITICAL(&perfLock);
    perf.lcdLateRefrs = cc_cadence.lateRuns;
    perf.lcdMaxGapMs = cc_cadence.maxGapMs;
    portEXIT_CRITICAL(&perfLock);
}

// Once per second (this thread): fps, the animated minimum, the flush and busy shares, idle share.
void perfWindow(uint32_t nowMs) {
    if (!winStartMs) { winStartMs = nowMs; return; }
    const uint32_t span = nowMs - winStartMs;
    if (span < 1000) return;
    const uint32_t idle = idleAccumUs;
    const uint32_t idleUs = idle - idleSeenUs;
    idleSeenUs = idle;
    // Taken before the critical section, which masks interrupts on this core (the LED RMT one among
    // them): the decode task's stack high-water scan walks its stack (about 64-128 us), and the
    // render counters are this thread's own, so the values are the same as read inside it.
    const CCDisplayStats& s = cc_display_stats();
    const uint32_t decodeRequests = s.artDecodeRequests, decodeAborts = s.artDecodeAborts,
                   decodeStale = s.artDecodeStale;
    const uint32_t stackArtDec = cc_art_async ? cc_art_decode_stack_free() : 0u;
    const uint32_t mosiSig = cc_lcd_mosi_sig();
    portENTER_CRITICAL(&perfLock);
    perf.lcdFps = winFrames * 1000u / span;
    if (winAnimated && (perf.lcdFpsAnimMin == 0 || perf.lcdFps < perf.lcdFpsAnimMin)) perf.lcdFpsAnimMin = perf.lcdFps;
    perf.lcdFlushUs = winFlushUs;
    perf.lcdBusyPct = winBusyUs / (span * 10u);
    perf.core0IdlePct = idleUs / (span * 10u) > 100u ? 100u : idleUs / (span * 10u);
    perf.artDecodeRequests = decodeRequests;
    perf.artDecodeAborts = decodeAborts;
    perf.artDecodeStale = decodeStale;
    perf.artAsync = cc_art_async ? 1u : 0u;
    perf.stackArtDec = stackArtDec;
    perf.lcdMosiSig = mosiSig;
    portEXIT_CRITICAL(&perfLock);
    winStartMs = nowMs;
    winFrames = winFlushUs = winBusyUs = 0;
    winAnimated = false;
}

// Flush of one LVGL chunk.
// R3 (CC_LCD_DMA 1): LVGL renders the next chunk into the other draw buffer while this one is on the
// wire. pushImageDMA waits for the previous transfer first (dmaWait) and swaps the bytes in place
// (setSwapBytes(true): LVGL's RGB565 is little endian, the panel's big endian), so flush_ready can be
// signalled at once.
// Blocking (CC_LCD_DMA 0, binaries C and E): cc5.3's lv_tft_espi flush, call for call, through this one
// instance (so the diag counters see it).
void cc_flush(lv_display_t* disp, const lv_area_t* area, uint8_t* px) {
    const uint32_t t0 = micros();
    const int32_t w = area->x2 - area->x1 + 1, h = area->y2 - area->y1 + 1;
#if CC_LCD_DMA
    tft.pushImageDMA(area->x1, area->y1, w, h, reinterpret_cast<uint16_t*>(px));
#else
    tft.startWrite();
    tft.setAddrWindow(area->x1, area->y1, w, h);
    tft.pushColors(reinterpret_cast<uint16_t*>(px), static_cast<uint32_t>(w * h), true);
    tft.endWrite();
#endif
    refrPx += static_cast<uint32_t>(w * h);
    winFlushUs += micros() - t0;
    lv_display_flush_ready(disp);
}

// artwork2 lookups for the platform-neutral renderer (cc_display.h). They run on this (LCD) thread
// inside cc_display_render(); the store reports misses when its PSRAM is unavailable. The JPEG
// decode keeps its own counters and timing for {"diag":"?"} (cc_jpeg_stats()).
CCMediaKind cc_media_kind_of(uint8_t kind) { return kind == CC_DISPLAY_MEDIA_ICON ? CC_MEDIA_ICON : CC_MEDIA_COVER; }
bool cc_lcd_media_adopt(uint8_t kind, const char* key, const uint8_t** data, uint32_t* bytes) {
    const CCMediaKind k = cc_media_kind_of(kind);
    return cc_media_available(k) && cc_media_adopt(k, key, data, bytes);
}
void cc_lcd_media_release(uint8_t kind) {
    const CCMediaKind k = cc_media_kind_of(kind);
    if (cc_media_available(k)) cc_media_release_display(k);
}
bool cc_lcd_jpeg_decode(const uint8_t* jpeg, uint32_t bytes, uint16_t* dst) {
    // Its own breadcrumb around the ROM decoder (up to about 150 ms), then back to the render step
    // that called it. With R5 this runs only when the decode task refused a request.
    cc_crumb_lcd(CC_LCD_STEP_DECODE);
    const bool decoded = cc_jpeg_decode_240(jpeg, bytes, dst);
    cc_crumb_lcd(CC_LCD_STEP_RENDER);
    return decoded;
}

// cc_display_render() timed for lcdRenderUsMax.
void timed_render(const CCFrame& frame, const uint8_t* artwork120) {
    const uint32_t t0 = micros();
    cc_display_render(frame, artwork120);
    const uint32_t us = micros() - t0;
    portENTER_CRITICAL(&perfLock);
    if (us > perf.lcdRenderUsMax) perf.lcdRenderUsMax = us;
    portEXIT_CRITICAL(&perfLock);
}

// Native handback: the previous (native) screen, the pins released (cc_display.h).
void hand_back() {
    lv_screen_load(cc_previous_screen ? cc_previous_screen : ui_valueScreen);
    lv_refr_now(nullptr);
    cc_panel_wait();
    cc_display_visible = false; cc_display_version = 0; cc_display_id = 0;
    cc_offline_input_reset(cc_offline_in);
    cc_display_release_media();
}

void render_host_frame() {
    static uint32_t artworkVersion = 0, mediaVersion = 0, decodeVersion = 0;
    // The snapshot lives in static storage (CCFrame is ~1.1 KB; the LCD stack is kLcdStackBytes). It
    // is refreshed only when the presentation state moved: the counter changes on every frame/art
    // version, every phase transition (including releasing -> idle) and every timeout-notice change,
    // and it is read before the copy, so an unchanged value means this cached snapshot is still
    // exactly what cc_snapshot() would return. Everything below still runs every pass: the handback,
    // the offline layer and cc_lcd_applied(). cc_presentation_state() already folds in
    // cc_art_version() and cc_media_version() (control_center.cpp).
    static CCFrame frame;
    static uint32_t id = 0, version = 0;
    static uint8_t wb = 0;
    static bool active = false, primed = false;
    static uint32_t seenState = 0;
    const uint32_t state = cc_presentation_state();
    if (!primed || state != seenState) {
        active = cc_snapshot(frame,id,version,wb);
        seenState = state; primed = true;
    }
    if (!active) {
        if (cc_display_visible) {
            if (cc_claimed()) {
                // Releasing (PRESENTATION_V5.md 8.10): the host screen stays until the release completes,
                // so a lease expiry reaches the offline layer without a native frame in between (the
                // cc5.3 flash, LT:293-309). The acknowledgement is immediate: nothing new is presented.
                cc_lcd_applied(0);
                return;
            }
            if (cc_timeout_notice()) {
                // Host lost: "Waiting for PC" as a layer of the host tree (P5-R13); native controls stay
                // active underneath and nothing is claimed. Re-applied every pass (inert) for the pin
                // release after the cover fade and the native-input swap.
                const uint32_t keyEdges = cc_native_button_seq();
                cc_display_offline(cc_offline_input_update(cc_offline_in, foc_thread.pass_cur_pos(), keyEdges));
                if (cc_display_stats().lastChanged) lv_refr_now(nullptr);
                cc_lcd_applied(0);
                return;
            }
            // An intentional release (P5-11), also from the offline screen: the native screen, as in cc5.3.
            hand_back();
        }
        cc_lcd_applied(0);
        return;
    }
    if (!cc_screen) cc_screen = cc_display_create(cc_art240[0], cc_art240[1]);
    bool entering = !cc_display_visible;
    bool newControl = entering || cc_display_id != id;
    if (entering) {
        cc_previous_screen = lv_screen_active();
        lv_screen_load(cc_screen); cc_display_visible = true;
    }
    cc_offline_input_reset(cc_offline_in);   // a claim leaves the offline layer (its first render fades back in)
    bool presentNow = false;
    // Store and decode versions are read before the render's lookups, so a commit (or a finished R5
    // decode) that lands during the render is seen on the next pass.
    const uint32_t artNow = cc_art_version(), mediaNow = cc_media_version(), decodeNow = cc_art_decode_version();
    if (entering || version != cc_display_version || artworkVersion != artNow || mediaVersion != mediaNow ||
        decodeVersion != decodeNow || cc_display_offline_shown()) {
        cc_crumb_lcd(CC_LCD_STEP_RENDER);
        timed_render(frame, cc_art_pixels(frame.artKey));
        artworkVersion = artNow;
        mediaVersion = mediaNow;
        decodeVersion = decodeNow;
        cc_display_version = version;
        ledcWrite(0,LEDC_MAX_BLK);
        // Every changed render reaches the panel in this pass (section 12.2: a detent's text swap
        // <= 5 ms), animated or not: v5 detents start a meta fade, and waiting for the refresh timer
        // would delay the new title by up to one period. The animation continues on the timer.
        presentNow = cc_display_stats().lastChanged;
    }
    if (newControl || presentNow) {
        cc_crumb_lcd(CC_LCD_STEP_REFRESH);
        lv_refr_now(nullptr);
    }
    if (newControl) {
        cc_panel_wait();                 // cc_lcd_applied(id) means "on glass" (R3)
        cc_display_id = id;
    }
    cc_lcd_applied(id);
}
}

CCLcdPerf cc_lcd_perf_read() {
    portENTER_CRITICAL(&perfLock);
    const CCLcdPerf copy = perf;
    perf.lcdFpsAnimMin = 0;              // reset on read (section 12.3)
    portEXIT_CRITICAL(&perfLock);
    return copy;
}

// LVGL time source: the real millisecond clock. The previous loop added a fixed 10 ms per pass while
// each pass only slept one RTOS tick, so LVGL time ran several times faster than real time.
static uint32_t cc_tick_ms(void) { return (uint32_t)millis(); }

void LcdThread::run() {
    // Task watchdog (1.0.0-cc5.2, cc_diag.h): fed once per pass at the wait step below. A pass is
    // usually tens of milliseconds; with R5 no cover decode runs on this thread (binaries A and D), in
    // B, C and E a pass whose render meets a new artwork2 cover key decodes it inside cc_display_render() (up
    // to about 150 ms, breadcrumb CC_LCD_STEP_DECODE), still far below CC_TASK_WDT_SECONDS.
    cc_wdt_watch(CC_LIVE_LCD);
    // Setup LedC
    ledcSetup(0, 5000, 12); // 4096 steps @ 5Khz
    ledcAttachPin(5, 0); // LEDC on Pin 5
    lv_init(); // Initialize LVGL
    lv_tick_set_cb(cc_tick_ms); // Must follow lv_init(), which resets LVGL globals.

    // Artwork display buffers: two 240x240 RGB565 (2 x 115,200 B) in PSRAM, front and back, owned for
    // the lifetime of the thread. Fail-soft: with one buffer new covers are written in place, with
    // none only artwork is disabled.
    for (uint8_t i = 0; i < 2; ++i)
        cc_art240[i] = static_cast<uint8_t*>(heap_caps_malloc(CC_ART240_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    CCDisplayMedia lookups = {};
    lookups.adopt = cc_lcd_media_adopt;
    lookups.release = cc_lcd_media_release;
    lookups.decodeCover = cc_lcd_jpeg_decode;
#if CC_ART_ASYNC
    // R5 only with both art buffers (12.5.1): the decoder owns the back buffer while it decodes.
    if (cc_art240[0] && cc_art240[1] && cc_art_decode_start()) {
        lookups.requestCover = cc_art_decode_request;
        lookups.pollCover = cc_art_decode_poll;
        lookups.cancelCover = cc_art_decode_cancel;
        cc_art_async = true;
    }
#endif
    cc_display_set_media(lookups);

    /*
        Create Display Object
    */

    // The panel's one TFT_eSPI instance (R3): lv_tft_espi_create()'s setup (begin, rotation 3) without
    // its second instance; lcd_manager applies the device orientation to this same instance.
    tft.begin();
    tft.setRotation(3);
#if CC_LCD_DMA
    tft.setSwapBytes(true);        // LVGL RGB565 (little endian) -> the panel's byte order
    tft.initDMA();
    cc_lcd_mosi_reattach();        // initDMA left TFT_MOSI on FSPIQ (MISO = MOSI): FSPID back first
    tft.startWrite();              // one transaction for the DMA flushes (TFT_eSPI DMA pattern)
#endif
    // diag lcdMosiSig at init (again in every perfWindow): 103 once the data line is FSPID, in both
    // pipelines (the blocking build's SPI.begin() attaches it so).
    perf.lcdMosiSig = cc_lcd_mosi_sig();
    lv_display_t * disp = lv_display_create(TFT_WIDTH, TFT_HEIGHT);
    lv_display_set_flush_cb(disp, cc_flush);
#if CC_LCD_DMA
    lv_display_set_buffers(disp, draw_buf, draw_buf2, sizeof(draw_buf), LV_DISPLAY_RENDER_MODE_PARTIAL);
#else
    lv_display_set_buffers(disp, draw_buf, nullptr, sizeof(draw_buf), LV_DISPLAY_RENDER_MODE_PARTIAL);
#endif
    // R4: the refresh and animation period (LV_DEF_REFR_PERIOD is 33 in lv_conf.h).
    lv_timer_set_period(lv_display_get_refr_timer(disp), CC_LCD_PERIOD_MS);
    lv_timer_set_period(lv_anim_get_timer(), CC_LCD_PERIOD_MS);
    lv_display_add_event_cb(disp, perfRefrStart, LV_EVENT_REFR_START, nullptr);
    lv_display_add_event_cb(disp, perfRefrReady, LV_EVENT_REFR_READY, nullptr);
    perf.lcdDma = CC_LCD_DMA;
    perf.lcdPeriodMs = CC_LCD_PERIOD_MS;
    perf.buildBinary = cc_build_binary();
    perf.lcdSpiHz = static_cast<uint32_t>(spi_get_actual_clock(APB_CLK_FREQ, SPI_FREQUENCY, 128));
    esp_register_freertos_idle_hook_for_cpu(cc_idle_hook, 0);

    /*
        Set timers for LCD Data Handler, Idle Animation Handler and Counter Handler
    */

    lv_timer_t * animtimer = lv_timer_create(idle_anim_handler, 1500, NULL); // 0.5Hz
    lv_timer_t * postimer = lv_timer_create(counter_handler, 33, NULL); // ~30Hz
    lv_timer_t * lcd_cmd_timer = lv_timer_create(lcd_manager, 1000, NULL); // 1Hz

    /*
        Start Timers
    */

    lv_timer_ready(animtimer);
    lv_timer_ready(postimer);
    lv_timer_ready(lcd_cmd_timer);


    ui_init(); // Initialize UI
    ledcWrite(0, LEDC_MAX_BLK); // Initialize Backlight to Max Brightness

    /*
        Main Loop for LVGL
        Host-frame presentation plus the LVGL timer handler; LVGL time comes from cc_tick_ms()
        (lv_tick_set_cb), so there is no lv_tick_inc() here.
    */

    // { "settings": { "deviceOrientation": 2 }}

    uint32_t diagSampledAt = 0;
    bool diagSampled = false;
    uint32_t lvglLowestFree = UINT32_MAX;
    while (1) {
        const uint32_t passStart = micros();
        cc_crumb_lcd(CC_LCD_STEP_HOST);
        render_host_frame();

        cc_crumb_lcd(CC_LCD_STEP_TIMERS);
        lv_timer_handler();
        perfCadence();
        // {"diag":"?"} margins, sampled here because LVGL is not thread-safe.
        const uint32_t now = millis();
        if (!diagSampled || now - diagSampledAt >= 1000) {
            cc_crumb_lcd(CC_LCD_STEP_DIAG);
            lv_mem_monitor_t mon;
            lv_mem_monitor(&mon);
            // lvglMinFree is the lower of two views of the low-water mark: the lowest free size
            // sampled (it counts TLSF block overhead but can miss a peak between samples) and total
            // minus LVGL's peak-use counter (it sees every peak but not the overhead).
            if (mon.free_size < lvglLowestFree) lvglLowestFree = mon.free_size;
            const uint32_t peakView = mon.total_size > mon.max_used ? mon.total_size - mon.max_used : 0;
            cc_diag_lcd(mon.free_size, lvglLowestFree < peakView ? lvglLowestFree : peakView,
                        static_cast<uint32_t>(uxTaskGetStackHighWaterMark(nullptr)));
            diagSampledAt = now; diagSampled = true;
        }
        winBusyUs += micros() - passStart;
        perfWindow(now);
        cc_crumb_lcd(CC_LCD_STEP_WAIT);
        cc_wdt_feed();                    // one full pass completed
        vTaskDelay(1 / portTICK_PERIOD_MS);
    }
};
