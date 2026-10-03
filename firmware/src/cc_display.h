#pragma once
#include <lvgl.h>
#include "cc_presentation.h"
#include "cc_lcd_logic.h"

// Host-owned LCD screen (presentation 5: PRESENTATION_V5.md section 8, "K1"; presentation-4
// frames draw with the same v5 geometry and inks, section 2.3). Platform-neutral: compiled
// unchanged by the firmware and by the host LVGL harness (harness), and checked in
// gnu++11 by harness/cpp11_gate.py.
//
// One retained LVGL tree, created once. cc_display_render() diffs the frame against the last
// rendered semantic state: an identical frame (heartbeat, lease renewal) starts no animation
// and re-sets no text; motion follows the section 8.8 table.
//
// Compile flags: CC_TEXT_TWINS (default 1: the twelve text-shadow twins of section 8.5.3);
// CC_DISPLAY_FULL_LAYERS (default 0; harness only: every animated layer 240 x 240, the
// reference of the `v5_bounded` pixel-identity check, section 8.2).

// Bytes of one 240x240 RGB565 artwork display buffer passed to cc_display_create.
constexpr uint32_t CC_ART240_BYTES = 240u * 240u * 2u;
// Bytes of one 120x120 RGB565 little-endian artwork transfer (v1 wire format).
constexpr uint32_t CC_ART120_BYTES = 120u * 120u * 2u;
// Bytes of one 32x32 RGB565 little-endian app icon (artwork2, ARTWORK2.md section 5).
constexpr uint32_t CC_ICON_BYTES = 32u * 32u * 2u;
// Longest artwork2 media key ([A-Za-z0-9_-]{1,24}); longer cover keys are v1-only.
constexpr uint32_t CC_DISPLAY_MEDIA_KEY_MAX = 24u;

// artwork2 media kinds, same values as cc_media.h CCMediaKind.
enum CCDisplayMediaKind : uint8_t { CC_DISPLAY_MEDIA_COVER = 0, CC_DISPLAY_MEDIA_ICON = 1 };

// Result of an asynchronous cover decode (section 12.5.2 `done.result`).
enum CCDisplayDecodeResult : uint8_t { CC_DECODE_OK = 0, CC_DECODE_FAILED = 1, CC_DECODE_ABORTED = 2 };

// artwork2 lookups (ARTWORK2.md section 7), supplied by the caller so that this unit stays
// platform-neutral: lcd_thread.cpp wires them to cc_media.h, cc_jpeg.h and cc_art_decode.h, the
// harness to fixture maps, the harness JPEG glue and a scripted fake decoder. Any member may be
// nullptr: that source is then never used. Value-initialise it (`CCDisplayMedia m = {};`).
struct CCDisplayMedia {
    // cc_media_adopt(): true with the committed payload when a valid slot holds key; the store
    // then pins that slot as displayed. The payload is read only during this render call
    // (decoded, copied or handed to requestCover, which copies it, at once).
    bool (*adopt)(uint8_t kind, const char* key, const uint8_t** data, uint32_t* bytes);
    // cc_media_release_display(): no media of this kind is drawn any more.
    void (*release)(uint8_t kind);
    // cc_jpeg_decode_240(): 240x240 baseline JPEG -> 240*240 native RGB565 in dst (synchronous).
    bool (*decodeCover)(const uint8_t* jpeg, uint32_t bytes, uint16_t* dst);
    // R5 (section 12.5; binary A): the cover decode off the render path. All three set and two
    // art buffers: covers are decoded by a separate task; otherwise decodeCover runs in the render
    // (binaries B and C, one art buffer, the harness default).
    // requestCover: take ONE decode of `jpeg` (copied before returning; the store payload is only
    // valid during the render) for `key` into dst, the back buffer, which then belongs to the
    // decoder until pollCover reports it. False: not taken (the render falls back to decodeCover).
    bool (*requestCover)(const char* key, const uint8_t* jpeg, uint32_t bytes, uint16_t* dst);
    // pollCover: true once per finished request, with its key and a CCDisplayDecodeResult.
    bool (*pollCover)(char* key, uint32_t keyCap, uint8_t* result);
    // cancelCover: the running request was superseded (true) or is wanted again (false, a spin
    // back before the abort landed). A cancelled request completes CC_DECODE_ABORTED (or, when
    // the decoder cannot stop mid-image, as usual; its stale result is then discarded).
    void (*cancelCover)(bool cancel);
};

// Media lookups for the following renders (copied). Call before rendering.
void cc_display_set_media(const CCDisplayMedia& media);

// art240Front, art240Back: caller-owned CC_ART240_BYTES buffers (PSRAM on the device, static in
// the harness). The art image always shows the front buffer; a new cover is decoded (JPEG) or
// upscaled (v1) into the back buffer and the two are swapped. art240Back may be nullptr (one
// buffer: the new cover is written into the shown buffer, as in cc5.2, and R5 stays off); with
// no front buffer artwork is never drawn and text controls stay fully usable. The first call
// creates the screen; later calls return the same screen (buffers that became available after
// the tree are attached then).
lv_obj_t* cc_display_create(uint8_t* art240Front, uint8_t* art240Back);

// artwork120: the current v1 CC_ART120_BYTES cover for frame.artKey, or nullptr. Covers: the
// artwork2 store first (JPEG), then the v1 store (upscaled once per key); a key whose pixels are
// already in a display buffer needs neither and is drawn even when no store holds it any more
// (keys are content hashes; the artwork2 store's displayed slot is then -1). A failed decode
// shows no art for that key until the frame's artKey changes. Synchronous decodes run before
// the render starts any animation (a decode never shortens a screen change); with R5 the render
// only posts the request (section 12.5.4), keeps the previous cover until the decode completes
// and swaps instantly on the render after it (the caller re-renders when the decode finishes).
// Windows layout: frame.iconKey from the artwork2 store on the tile, else the letter tile.
void cc_display_render(const CCFrame& frame, const uint8_t* artwork120);

// The host screen is being left (native handback): releases the artwork2 display pins of both
// kinds and cancels a running R5 decode. The pixels stay loaded for a later return, whose first
// render snaps to its state (no slide, no fade: "the first render after the host screen
// appears", section 8.4). The latched reducedMotion is reset (a new claim starts without it).
void cc_display_release_media();

// Firmware-local offline screen "Waiting for PC" (section 8.10, after a lease expiry): a layer
// of the host tree, drawn without loading the native screen. The first call fades the cover out
// (240 ms OUT) and the footer out (160 ms IN), hides the host content and fades the offline
// content in (220 ms OUT); both media display pins are released once the cover fade is over
// (call it again on later passes: it is inert apart from that release and the sub-line swap).
// nativeInput (the first native input while it shows: an FOC position change or a button state
// change while unclaimed) swaps "Open Desk Dial on your PC" for "Knob controls still work" with the
// 160 ms fade; kept until the next claim. The next cc_display_render() leaves it: content in
// 220 ms, cover 240 ms, footer 280 ms after 140 ms, no slide. The latched reducedMotion is reset.
void cc_display_offline(bool nativeInput);

// True while the offline layer is up (cc_display_offline() since the last render).
bool cc_display_offline_shown();

// r4 input moments (design_handoff_nano_d_r4 README 3.2; MOTION.md). Both run on the LVGL thread.
// The physical buttons down now (bit n = physical slot n, left to right = the footer icons), every LCD pass (a
// changed mask is the edge): M7 the press squash on the footer icon of a pressed button and its spring-back on
// release; M10 the hold fill of the button-4 icon while slot 3 is held on a holdMarker screen (1000 ms; an early
// release drains it; a landing, the first new ok feedback within 1.5 s of its maturity, pops it, M8).
void cc_display_input(uint8_t keysDown);
// A wall hit (cc_wall.h: a detent refused at a bound; dir +1 past the end / max, -1 past the start / min), once per
// new hit: M13 the content moves 9 px towards the wall in 90 ms E.out and rebounds on SPRING.wall (not under
// reduced motion, offline or before the first render).
void cc_display_wall(int8_t dir);

// The offline layer's "first native input" (section 8.10): CCOfflineInput, cc_offline_input_update() and
// cc_offline_input_reset() live in cc_lcd_logic.h (header-only, FW-BUG-042), with the native motion counter the
// LCD thread feeds them.

// lcdLateRefrs / lcdMaxGapMs (section 12.3: "intervals > 1.5 x period while animating; worst
// gap"), measured on the ANIMATION cadence, not between refreshes that flushed pixels. LVGL runs
// the animation timer once per period while any animation exists (a running tween or one still in
// its delay), but an eased tween can hold the same integer value for several periods (the OUT and
// SPR tails, a delay): nothing is invalidated and no refresh runs, so a flush-to-flush interval
// reports those plateaus (and, from a timestamp left by an earlier tween, idle time) as late
// refreshes of a pipeline that kept up. What a hitch lengthens -- a long render, refresh or decode
// on the LCD thread, or the thread not running -- is the interval between two runs of the
// animation timer. An episode ends when no animation exists (LVGL pauses the timer then), so the
// first run of the next one is never an interval.
struct CCAnimCadence {
    bool primed;         // lastRunMs belongs to the current animation episode
    uint32_t lastRunMs;  // the animation timer's last run seen at the previous sample
    uint32_t lateRuns;   // intervals > 1.5 x period (lcdLateRefrs), since reset
    uint32_t maxGapMs;   // worst interval (lcdMaxGapMs), since reset
};
// One sample (pure: the harness feeds it synthetic sequences too). animTimerLastRunMs: the
// animation timer's last_run; animating: lv_anim_count_running() > 0; periodMs: its period.
void cc_anim_cadence_sample(CCAnimCadence& cadence, uint32_t animTimerLastRunMs, bool animating, uint32_t periodMs);
// The sample from LVGL's own state (lv_anim_get_timer(), lv_anim_count_running()): call it after
// every lv_timer_handler() pass, on the LVGL thread. Returns true when a counter moved.
// lvglPaused: lv_timer_handler() did not run this pass (the app canvas is up, lcd_thread's app_on). A paused
// pass ends the episode like "no animation" (FW-BUG-044): the animations stay listed while the timer cannot
// run, so without it the first run after the app session would be one interval as long as the session.
bool cc_anim_cadence_poll(CCAnimCadence& cadence, bool lvglPaused);

// Render diagnostics (counters since boot, plus the last render's outcome). lcd_thread uses
// lastChanged/lastAnimated to present a non-animated change immediately (lv_refr_now) instead of
// waiting for the next refresh period; the harness uses them to prove heartbeat frames inert.
struct CCDisplayStats {
    uint32_t renders;      // cc_display_render() calls
    uint32_t textSets;     // lv_label_set_text() calls (twins not counted separately)
    uint32_t animations;   // animations started
    uint32_t slides;       // screen changes started (content slide and/or fade)
    uint32_t artUpscales;  // 120 -> 240 artwork upscales
    uint32_t artDecodes;   // synchronous artwork2 240 px JPEG cover decodes attempted
    uint32_t artDecodeErrors;  // ... failed (sync or async; no art for that key until it changes)
    uint32_t artReuses;    // cover swaps to the back buffer that already held the key
    uint32_t iconLoads;    // artwork2 app icons copied into the tile buffer
    uint32_t artDecodeRequests;  // R5 decodes posted (diag artDecodeRequests)
    uint32_t artDecodeAborts;    // R5 decodes that completed aborted (artDecodeAborts)
    uint32_t artDecodeStale;     // R5 completions discarded because the key moved on (artDecodeStale)
    uint32_t inkFades;     // footer / idle ink crossfades started (section 5.2, 160 ms)
    uint32_t lineFades;    // meta / status text-at-rest fades started (section 8.5.4; r4 M6: + the 10 px rise)
    // r4 motion (README section 3.2; MOTION.md).
    uint32_t glides;       // M4 / M5 glides started (a detent on a list, a new song)
    uint32_t trackChanges; // M5
    uint32_t presses;      // M7 squashes started
    uint32_t pops;         // M8 landing pops started
    uint32_t morphs;       // M9 Play <-> Pause morphs started
    uint32_t holdFills;    // M10 hold fills started
    uint32_t landings;     // M10 fills that landed (a new feedback within the window)
    uint32_t walls;        // cc_display_wall() calls
    uint32_t wallBounces;  // M13 bounces started (not under reduced motion, offline or before a render)
    uint32_t a8Direct;     // A8 masks drawn straight from flash (the renderer's own decoder)
    int32_t lastSlide;     // last render: +20 (deeper, enters from the right), -20 (back) or 0
    bool lastScreenChange; // last render started a screen change (slide or, from offline / reduced, fade only)
    bool lastChanged;      // last render changed anything on screen
    bool lastAnimated;     // last render started at least one animation
};
const CCDisplayStats& cc_display_stats();

// Device LCD pipeline diagnostics (section 12.3, VOC-K1c; defined by lcd_thread.cpp, not by the
// harness). The COM thread may read them at any time: every field is one aligned 32-bit word
// written by the LCD thread only; cc_lcd_perf_read() also resets the "reset on read" field.
struct CCLcdPerf {
    uint32_t lcdFps;          // refreshes that reached the panel in the last full second
    uint32_t lcdFpsAnimMin;   // lowest 1 s lcdFps while animations ran (reset on read; 0 = none)
    // LV_EVENT_REFR_START -> REFR_READY (+ the final dmaWait), us, of the refreshes that reached the panel in the
    // last full second (FW-PERF-010: windowed like lcdFps; 0 when none did). Before it they were since boot.
    uint32_t lcdRefrUsMax;
    uint32_t lcdRefrUsAvg;
    uint32_t lcdRenderUsMax;  // time inside cc_display_render(), us
    uint32_t lcdFlushUs;      // flush share of the last second, us (SPI transfer or DMA wait)
    uint32_t lcdPxPerRefr;    // sum of w*h flushed per refresh, last refresh
    uint32_t lcdFullRefrs;    // refreshes that flushed >= 57,600 px, since boot
    uint32_t lcdLateRefrs;    // animation-timer intervals > 1.5 x period (CCAnimCadence), since boot
    uint32_t lcdMaxGapMs;     // worst animation-timer interval while animating, since boot
    uint32_t lcdBusyPct;      // LCD task share of core 0 over the last second
    uint32_t core0IdlePct;    // idle-hook share of core 0 over the last second
    uint32_t lcdSpiHz;        // SPI clock at boot
    uint32_t lcdDma;          // CC_LCD_DMA compiled in (1) or not (0)
    uint32_t lcdPeriodMs;     // CC_LCD_PERIOD_MS
    uint32_t artAsync;        // R5 active at run time (CC_ART_ASYNC and two art buffers)
    uint32_t artDecodeRequests, artDecodeAborts, artDecodeStale;
    uint32_t stackArtDec;     // decode-task stack free bytes (0 when artAsync is 0)
    // 12.6 errata E-lcd (binaries D and E): lcdMosiSig read at init and once per second, buildBinary at init.
    uint32_t lcdMosiSig;      // GPIO matrix output signal on TFT_MOSI: 103 FSPID (good), 102 FSPIQ (A's defect)
    uint32_t buildBinary;     // CC_BUILD_BINARY: 1..6 = ladder binary A..F (diag "build"), 0 = none
};
// A copy of the counters; resets lcdFpsAnimMin (section 12.3 "reset on read"). Device only.
CCLcdPerf cc_lcd_perf_read();
