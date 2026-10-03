# Refresh 03: physical knob refresh limits (LCD + LEDs)

This note covers the user's request that "all of the animations ... on the knob" run at the maximum refresh rate. It deals with the **physical** knob only: the ESP32-S3, the 240 × 240 GC9A01 LCD, the 60-LED ring and the 8 button LEDs. The desktop surfaces (the Music explorer, Up next, the window picker and the floating on-screen knob) are covered by the other refresh notes.

All work here was offline and read-only. Nothing was built or flashed, no COM port was opened, and no window was shown. The numbers come from three places: the firmware source, the diag snapshots the cc5/cc5.3 check tools already recorded, and an arithmetic model (`<scratch>/refresh-study/knob_model.py`, output in `knob_model.out.txt`).

**Path prefixes used below** (all relative to `<repo>\`):
- `FW/` = `firmware/`
- `LIB/` = `firmware/.pio/libdeps/nanofoc_d/`
- `DIAG/` = `app/diagnostics/`
- `HO/` = `app/design-reference/design_handoff_nano_d_master/`

---

## 0. Bottom line

1. **240 Hz is physically impossible on the knob.**
   - The LCD is fed over one SPI data line at 80 MHz. A full 240 × 240 RGB565 frame takes **11.5 ms** on the wire, so the ceiling is **87 fps**, and that is before any rendering.
   - 240 full frames per second would need 221 Mbit/s, which is 2.8 times what the link can carry.
   - The panel also scans its own GRAM at a fixed internal rate. The datasheet gives no formula for it; its only frame-rate figure is "20~40 Hz" in the tearing-effect timing table. Nothing faster than the panel's scan can ever be seen.
2. **LCD today: 30 fps at best, and nearly every animation redraws the full screen.**
   - `LV_DEF_REFR_PERIOD` is 33 ms, and it drives both LVGL's refresh timer and its animation timer. That caps animation at **30 fps**.
   - Every animated layer is a 240 × 240 box. As a result, the slide, the volume reveal, the footer fade and the art fades all repaint **100 % of the screen** on every frame.
   - The flush is **blocking CPU-FIFO SPI**: a single 11,520 B buffer and no DMA. For about 12 ms per full frame the CPU does nothing but wait.
   - A new cover's JPEG decode **freezes the LCD thread for 46–154 ms** (measured).
3. **LEDs today: 49 fps measured, not the 60 fps the design assumes.**
   - HMI shows only when at least 16 ms have passed, but its loop sleeps 10 ms per pass. So it shows on every second pass, which is about every 20.4 ms.
   - Recorded diag data confirms this: **49.1 fps** across the cc5.3 check run, **48.0 fps** across the lease check, and a 49.7 fps lifetime average.
4. **Realistic targets:**
   - **LCD: 60 fps (16 ms)** on every animated transition, with **≥ 45 fps** as the floor for the heaviest frames (full-screen opacity blends over the cover).
   - **LEDs: a steady 60 fps**, with an optional **120 Hz output-only dither pass**, adopted only if the hands-on A/B shows shimmer at rest.
5. **What it takes, in order:**
   1. Fix the LED cadence. This is already specified in ALIVE §10.1.
   2. Shrink the invalidated areas: layer boxes instead of full-screen layers.
   3. Add DMA with two partial buffers (+11.5 KB of internal RAM).
   4. Move the refresh and animation timers to 16 ms.
   5. Take the JPEG decode off the render path.
   6. Optionally, compile LVGL at `-O2`, and raise HMI to priority 2.

   Raising the period to 16 ms **alone** gets only 38–58 fps on full-screen animations, and it pins core 0 at about 99 % during them.

---

## 1. The pipeline as built (facts)

| Item | Value | Source |
|---|---|---|
| MCU | ESP32-S3 at 240 MHz; flash QIO 80 MHz; quad PSRAM 80 MHz; 32 KB data cache | `FW/boards/nanofoc_d.json:13-15`; framework `sdkconfig.h:290,298,304,309` (`pio-knob/packages/framework-arduinoespressif32/tools/sdk/esp32s3/qio_qspi/include/`) |
| RTOS tick | 1000 Hz (1 ms) | same `sdkconfig.h:458` |
| Tasks on core 0 | HMI, LCD and COM, **all priority 1** (1 ms round-robin time slicing). FOC is on core 1 | `FW/src/main.cpp:20-23`; `com_thread.cpp:18`, `hmi_thread.cpp:106`, `lcd_thread.cpp:32`, `foc_thread.cpp:25`; `FW/CONTROL_CENTER.md:584` |
| Display driver | TFT_eSPI 2.5.43 through LVGL's `lv_tft_espi` driver; GC9A01 | `FW/platformio.ini:25,39`; `FW/include/lv_conf.h:881` |
| SPI | 80 MHz (`SPI_FREQUENCY=80000000`). MOSI GPIO 4 and SCLK GPIO 3 go through the **GPIO matrix**: SPI2's IO_MUX pins are 11 and 12. MISO is not wired (−1) | `FW/platformio.ini:40-49`; [ESP-IDF SPI master, ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/spi_master.html) |
| TE (tearing) line | Enabled in the panel init (`0x35`), but **no TE GPIO exists** in the firmware or build flags | `LIB/TFT_eSPI/TFT_Drivers/GC9A01_Init.h:225`; `FW/include/nanofoc_d.h:47-63` |
| Panel "Frame Rate" register E8h | Init writes `0x34`; the default is `0x14`. The datasheet documents only `DINV[3:0]` (the inversion mode) in the high nibble. The low nibble (4 in both values) is undocumented "XX" | `LIB/TFT_eSPI/TFT_Drivers/GC9A01_Init.h:148-149`; GC9A01A datasheet V1.0 §6.4.1 p.164–165 |
| Panel write-clock limit | t<sub>wc</sub> ≥ 10 ns, so ≤ 100 MHz. **80 MHz is within spec** | GC9A01A datasheet §7.3.4 Table 48, p.190 |
| Panel frame rate | Not specified. The only mention is the TE timing note "Idle Mode Off (Frame Rate = 20~40 Hz)" | GC9A01A datasheet §5.4.2 Table 38, p.79 |
| Flush path | `pushColors(px, w*h, swap=true)`, done by the CPU in 64-byte FIFO chunks with busy-wait (`while (SPI_USR)`); no DMA | `LIB/lvgl/src/drivers/display/tft_espi/lv_tft_espi.cpp:67-81`; `LIB/TFT_eSPI/TFT_eSPI.cpp:3864-3873`; `LIB/TFT_eSPI/Processors/TFT_eSPI_ESP32_S3.c:285-325` |
| Draw buffers | **One** partial buffer of 11,520 B (5,760 px = 24 full rows, 1/10 of the screen); `LV_DISPLAY_RENDER_MODE_PARTIAL` | `FW/src/lcd_thread.cpp:23-24,384`; `lv_tft_espi.cpp:59` |
| LVGL | 9.0.0, SW renderer, 1 draw unit, no ASM blend, `LV_OS_NONE`, 64 KB heap, `LV_ATTRIBUTE_FAST_MEM` empty | `FW/platformio.ini:24`; `FW/include/lv_conf.h:45,81,102,132,348` |
| Refresh and animation period | `LV_DEF_REFR_PERIOD 33` ms. It is used for the display refresh timer **and** the animation timer | `FW/include/lv_conf.h:64`; `LIB/lvgl/src/display/lv_display.c:94`; `LIB/lvgl/src/misc/lv_anim.c:64` |
| Timer semantics | `last_run` is stamped before the callback, so the period runs start-to-start. The refresh timer pauses itself when nothing is invalid | `LIB/lvgl/src/misc/lv_timer.c:297`; `LIB/lvgl/src/core/lv_refr.c:335` |
| Timer order | New timers go to the list head (`lv_timer.c:165`). The refresh timer (created by `lv_display_create`) therefore runs **before** the animation timer (created in `lv_init`), so each frame shows the previous animation step. That adds up to one period of latency | `LIB/lvgl/src/misc/lv_timer.c:165` |
| LVGL tick | `lv_tick_set_cb(millis)`, 1 ms resolution | `FW/src/lcd_thread.cpp:363-366` |
| LCD loop | `render_host_frame()`, then `lv_timer_handler()`, then `vTaskDelay(1)`. That is about 1 kHz when idle | `FW/src/lcd_thread.cpp:414-443` |
| Non-animated changes | Presented at once with `lv_refr_now`. Animated ones wait for the refresh timer | `FW/src/lcd_thread.cpp:336-345` |
| Animated layers | `makeFullLayer()` = a 240 × 240 box for stage, content, home, track, volume, list, tracks, windows and footer | `FW/src/cc_display.cpp:1074-1076,1139-1223` |
| Style change → invalidation | `lv_obj_refresh_style()` invalidates the **whole object** on every opacity or translate step | `LIB/lvgl/src/core/lv_obj_style.c:278` |
| Cover | A 240 × 240 RGB565 image in **PSRAM** (front and back buffers). It is blitted with `memcpy` at opa 255, or with a per-pixel `lv_color_16_16_mix` at opa < 255 | `FW/src/lcd_thread.cpp:372`; `LIB/lvgl/src/draw/sw/blend/lv_draw_sw_blend_to_rgb565.c:340-354` |
| JPEG decode | Synchronous, on the LCD thread, inside the render: **46–154 ms** (`jpegDecodeMsLast` 46–96, `jpegDecodeMsMax` 154) | `FW/src/lcd_thread.cpp:260-267`; `FW/src/cc_display.cpp:1016-1025`; `DIAG/cc5.3-device-checks.json` |
| Compiler | `-Os` for LVGL, TFT_eSPI and the app (`CONFIG_COMPILER_OPTIMIZATION_SIZE`) | `FW/compile_commands.json`; framework `sdkconfig.h` |
| Internal RAM headroom | `heapFree` 65,744 B, `heapMinFree` 57,072 B; LVGL heap low-water 36,584 B free | `DIAG/cc5.3-device-checks.json` → `sections.diag.after` |
| Flash headroom | 1,023,648 B used of 1,310,720 B (app0 `0x140000`) | `app/firmware/BUILD-cc5.3.md:96-100,170` |
| LED loop | HMI pass, then `FastLED.show()` if `now − previous ≥ 16`, then `vTaskDelay(10)` | `FW/src/hmi_thread.cpp:299-307,322` |
| LED wire | WS2811 timing: 1.25 µs per bit (25/25 and 12/38 ticks at 40 MHz). RMT, two memory blocks per channel. `FastLED.show()` enforces a minimum spacing of 2.5 ms (a 400 fps cap) | `FW/src/cc_led_wire.h:10-24`; `FW/src/cc_led_rmt.h:90`; `FW/src/cc_led_rmt.cpp:8-16` |

### Motion the knob animates today (cc5.3 `cc_display.cpp`)

| Animation | Tweens (duration, delay) | Layer size | Area per frame today |
|---|---|---|---|
| Screen change (design: HO `README.md:126`, `specs/03-SCREEN-and-state.md:161`) | content translateX ±20 px over 380 ms; stage opacity 0→255 over 220 ms. The stage fades art and content together | full / full | **100 %**. For the first 220 ms every pixel is opacity-blended, including the cover |
| Volume reveal (HO `README.md:110`, `03-…:88-89`) | track opa 150 ms and translateY 190 ms; volume opa 180 ms after 50 ms; volume translateY 340 ms spring after 50 ms (`cc_display.cpp:797-798,821-822`) | full / full | **100 %** for about 390 ms |
| Footer fade | 160 or 280 ms (`cc_display.cpp:934`) | full | **100 %** |
| Art late arrival and idle | art opa 420 ms after 60 ms; idle fade 560 ms (`cc_display.cpp:1067-1071`) | 240 × 240 | **100 %**, blended |
| Idle row | 4 columns: opa and translateY with a 460 ms spring, staggered (`cc_display.cpp:836-837`) | 60 × 47 each | small |
| List, Tracks and Windows detent | text swap, no animation, `lv_refr_now` | label boxes | about 30 % |
| New cover key | synchronous JPEG decode, then an instant swap | — | 100 %, **after a 46–154 ms freeze** |

---

## 2. Budgets (computed)

### 2.1 SPI

| Quantity | Value |
|---|---|
| Full frame | 115,200 B = 921,600 bits |
| Wire time at 80 / 60 / 40 MHz | **11.52** / 15.36 / 23.04 ms |
| TFT_eSPI CPU-FIFO path | 64 B per refill (6.4 µs), with a register-write gap each time: **12.0–12.7 ms**. The firmware's own note says "a full 240x240 flush is about 12 ms" (`FW/src/lcd_thread.cpp:357`), which only 80 MHz can give |
| Wire-limited ceiling for full frames | **86.8 fps** |
| 240 fps full-frame demand | 221 Mbit/s = 2.8 × the link |

**The SPI clock cannot go higher.**
- 80 MHz is the ESP32-S3 SPI maximum: the APB clock of 80 MHz with a divider of 1.
- Espressif quotes 80 MHz only for the IO_MUX pins. These pins go through the GPIO matrix, which is why the "80 MHz write-only through the matrix" setup works but has no documented margin.
- The GC9A01 itself would take up to 100 MHz.
- The panel's 2-data-line mode (datasheet §4.5.3 and E9h) would need a second data wire, which a 4-wire module does not have.

### 2.2 Render and flush per animation frame (model)

**Model assumptions** (see `knob_model.py`):
- Cover pixels are read from quad PSRAM at 25–35 MB/s.
- An RGB565 opacity mix costs 12–24 cycles per pixel (`-Os`, no SIMD).
- Glyph and icon blending costs 15–30 cycles per pixel on 25 % of the area, or 45 % for a text swap.
- Tree walk and draw-task setup cost 60–120 µs per partial chunk.
- Each chunk is 5,760 px.
- DMA costs 30–60 µs of setup per chunk.

These are estimates, to be replaced by the counters in §7.

| Animation frame | Area | Chunks | Render | **Today** (33 ms, 1 buffer, blocking) | 16 ms, 1 buffer, blocking | **16 ms, 2 buffers + DMA** |
|---|---|---|---|---|---|---|
| Slide 0–220 ms (stage opa + content tx) | 100 % | 10 | 7.8–13.7 ms | 19.8–26.3 ms → **30 fps**, core 0 59–79 % | → 38–50 fps, core 0 **99 %** | 12.6–14.9 ms → **60 fps**, core 0 52–88 % |
| Slide 220–380 ms (content tx) | 100 % | 10 | 4.9–7.9 | 16.9–20.6 → 30 fps, 50–61 % | → 48–58 fps, 99 % | 12.3–12.9 → **60 fps**, 35–53 % |
| … with a content box y 31–177 | 61 % | 7 | 3.1–4.9 | → 30 fps, 31–38 % | → 60 fps, 63–76 % | → **60 fps**, 22–33 % |
| Volume reveal (full layers today) | 100 % | 10 | 4.9–7.9 | → 30 fps, 50–61 % | → 48–58 fps, 99 % | → **60 fps**, 35–53 % |
| … with a layer box 180 × 85 | 27 % | 3 | 1.3–2.1 | → 30 fps, 13–16 % | → 60 fps, 27–33 % | → **60 fps**, 9–14 % |
| Art fade (art opa < 255) | 100 % | 10 | 7.8–13.7 | → 30 fps, 59–79 % | → 38–50 fps, 99 % | → **60 fps**, 52–88 % |
| Two-cover crossfade (V2 idea, not built) | 100 % | 10 | 14–24 | → 27–30 fps, 78–99 % | → 27–38 fps, 99 % | → **39–60 fps**, 90–98 % |
| Footer fade (full layer today) | 100 % | 10 | 4.9–7.9 | → 30 fps, 50–61 % | → 48–58 fps, 99 % | → 60 fps, 35–53 % |
| … with a box 160 × 24 | 7 % | 1 | 0.3–0.6 | → 30 fps, 3–4 % | → 60 fps, 7–9 % | → 60 fps, 2–4 % |
| List detent text swap (4 labels) | 30 % | 3 | 1.7–2.8 | 5.2–6.5 ms, once | same | 4.1–4.5 ms, once |

**What the table says:**
- **The period is today's binding limit.** A full-screen frame costs 17–26 ms, which fits inside 33 ms. So today's animations run at close to 30 fps, except while a JPEG decode or a busy COM pass takes the core.
- **At 16 ms, the blocking flush becomes the limit.** Render and flush happen in series and total 17–26 ms, which gives 38–58 fps. Core 0 is then about 99 % busy for the whole transition. COM and HMI still get their round-robin slices (equal priority, 1 ms ticks), but COM ingests media more slowly and LED frames jitter by up to about 1–2 ms.
- **DMA with double buffering overlaps render and wire.** The frame time becomes about max(render, 12.4 ms), and the task sleeps during the transfer instead of spinning. The result is **60 fps at the same or lower CPU cost than today's 30 fps**.
- **Bounding the invalidated area** (layer boxes) cuts both render and wire time roughly in proportion to the area: 27 % for the volume reveal and 7 % for the footer. It is the cheapest win.
- **A two-cover crossfade stays the heaviest frame** by a margin. Keep the knob's instant swap, or accept about 40 fps for it.

### 2.3 LED budget

| Quantity | Value |
|---|---|
| Ring frame on the wire | 60 × 24 bits × 1.25 µs = **1.80 ms** |
| Button frame | 8 × 24 × 1.25 µs = 0.24 ms (its own RMT channel, in parallel) |
| Reset/latch | ≥ 50 µs (WS2811 datasheet p.3). The firmware waits 60 µs only when a previous frame is still running (`cc_led_rmt.cpp:15`) |
| Wire ceiling | about 480 fps. The `FastLED.show()` spacing caps it at 400 fps (`cc_led_rmt.h:90`) |
| WS2811 PWM | "scan frequency not less than 400Hz" ([WS2811 datasheet p.1](https://cdn-shop.adafruit.com/datasheets/WS2811.pdf)) |
| CPU per frame | Encoding 204 bytes into 1,632 RMT items is trivial. There are 30 + 4 refill interrupts per frame at level 3 in IRAM, which is about 2,000 per second at 60 fps and negligible. The ALIVE engine budget is `ledRenderUsMax ≤ 3000` µs per frame (`FW/ALIVE.md:469`), up to 18 % of core 0 at 60 fps in the worst case |

---

## 3. What the knob achieves today

**LCD.**
- There are no frame counters, so nothing about the LCD has been measured.
- The diag output reports only LVGL heap and stack margins (`lcd_thread.cpp:425-438`), liveness (`lcdAgeMs` 0–15 ms in the recorded checks) and the JPEG timings.
- From the pipeline, the expected behaviour is:
  - **About 29–30 fps** on every animation. The timer fires 33–34 ms apart (1 ms tick, `vTaskDelay(1)`).
  - Each refresh repaints the full screen for about 17–26 ms, so roughly 55–80 % of core 0 goes to the LCD during a transition.
  - A single-frame update (a detent's text swap) reaches the panel within about 5–7 ms, because `lv_refr_now` skips the period.
  - Any render that meets a new cover key **freezes the LCD for 46–154 ms**. That is 3–9 lost frames at 60 fps and 2–5 at 30 fps. Running animations stall, then jump. 04-firmware-gaps.md:645 already flags this for Up next spins.
  - Animation latency runs up to one period plus the frame time (§1, timer order): about 33 + 20 ms today.

**LEDs.**
- Measured directly from the ring's `frames` counter in the recorded diag snapshots:

  | Run | Frames | Uptime | Rate |
  |---|---|---|---|
  | `DIAG/cc5.3-device-checks.json` (`diagStart` → `sections.diag.after`) | 517,876 → 584,839 | 10,397,125 → 11,761,910 ms | **49.06 fps** |
  | `DIAG/cc5.3-lease-checks.json` (`diagStart` → `diagEnd`) | 316,770 → 318,396 | over 33.9 s | **47.97 fps** |
  | Lifetime | 584,839 | 11,761.9 s | 49.72 fps |
  | cc5 run (`DIAG/cc5-device-checks.json`) | — | — | 49.17 fps |

- **Cause:** the 16 ms gate is sampled by a loop that sleeps 10 ms per pass (`hmi_thread.cpp:301,322`). The first pass that satisfies the gate is the second one, so the show interval is about 2 × 10.2 ms ≈ 20.4 ms.
- The design wants a 60 fps LED task (`HO/README.md:37`; ALIVE capability `"fps": 60`, `FW/ALIVE.md:25`).
- **Dithering:** FastLED's own dither is off below 100 fps (`LIB/FastLED/src/FastLED.cpp:67`), so today's bytes are plain `scale8` values (`FW/CONTROL_CENTER.md:641-648`).

---

## 4. What can be raised safely (ordered by value and risk)

| # | Change | Gain | Cost and risk | Verify with |
|---|---|---|---|---|
| **R1** | **LED cadence** as specified in ALIVE §10.1 (`FW/ALIVE.md:371-373`): the loop delay becomes `clamp(nextShowDue − now, 1, 10)`, and `nextShowDue += 16`, or alternates 16/17/17 ms for exactly 60.0 fps, instead of `previous = now`, which drifts | 49 → **60 fps**, a 22 % finer temporal step for every damping and dither | Low. It adds HMI passes (buttons are polled more often, which is harmless). Takes effect with cc5.4 | `ledFps`, `ledShowGapMsMax` (§7) |
| **R2** | **Bound the invalidated areas** in `cc_display.cpp`: size `trackLayer`, `volumeLayer`, `footerLayer` and the list, tracks and windows layers to their content boxes instead of `makeFullLayer` (label geometry is already absolute, `cc_display.cpp:46-83`). Keep `content` at 240 × 240 only if the slide really needs it (content spans y 31–177) | The volume reveal repaints 27 % instead of 100 %, and the footer fade 7 % instead of 100 %. Every tween frame gets 2–10 × cheaper | Low to medium. Pixel output must stay identical: prove it in the `harness` harness (the unit is platform-neutral, `cc_display.h:6-9`) with frame-by-frame compares. The platform-neutral rules and the gnu++11 gate stay unchanged | Harness pixel diff; `lcdPxPerRefr` (§7) |
| **R2b** | **Design option** (needs the contract owner): during a screen change, fade the **content** instead of the whole **stage** when the cover key is unchanged (Home ↔ Tracks keep the same cover). Today every screen change dips the cover to black and back over 220 ms (`cc_display.cpp:12-14,1268`) | Removes 220 ms of full-screen cover blends per slide, the costliest frames in the table | A visual change: the cover would no longer blink. Deviation 7 already keeps the art from translating | Hands-on |
| **R3** | **DMA + two partial buffers.** Copy the tiny `lv_tft_espi.cpp` into `src/` (never edit `.pio/libdeps`, ALIVE §10.1 "not touched") and use one `TFT_eSPI` instance. Today there are two: the global `tft` at `lcd_thread.cpp:13`, used for `setRotation`, and the driver's own at `lv_tft_espi.cpp:54`. Details in §4.1 | Render overlaps the wire; the frame is about max(render, 12.4 ms); the task sleeps during DMA | Medium: **+11,520 B of internal RAM** (65.7 KB free today). There is SPI bus ownership to handle: every other TFT access (`setRotation`, `lv_refr_now` paths) must `dmaWait()` first. On ESP32-S3 + Arduino SPI, TFT_eSPI DMA needs a bring-up test | `lcdRefrUsMax`, `lcdFlushWaitUs`; image correctness (byte order) |
| **R4** | **Refresh and animation period 33 → 16 ms.** Set `LV_DEF_REFR_PERIOD 16` in `lv_conf.h:64`, or at runtime `lv_timer_set_period(lv_display_get_refr_timer(disp), 16)` plus `lv_timer_set_period(lv_anim_get_timer(), 16)` (`LIB/lvgl/src/display/lv_display.h:525`, `LIB/lvgl/src/misc/lv_anim.h:485`). **Ship it with or after R2+R3**, not alone | 30 → 60 fps on animated frames. The 1 ms tick makes that 16–17 ms intervals, about 59–62 fps. Latency halves | Low after R2+R3. Alone it means 99 % core 0 during transitions and only 38–58 fps | `lcdFps`, `lcdFpsAnimMin` |
| **R5** | **Take the JPEG decode off the render path**: decode into the back buffer in COM, or in a helper task on core 0 at priority 1, then hand the key to LCD, which only swaps pointers. Alternatively, slice the TJpgDec output callback into MCU-row slices across passes | Removes the 46–154 ms freezes, the most visible hitch on a fast Up next spin | Medium: buffer ownership between tasks (the back buffer must never be the one LVGL is drawing), and the cc5.3 ordering guarantee (decode before the tweens start, `cc_display.cpp:1016-1025`) has to be re-expressed | `jpegDecodeMsMax` no longer shows up in `lcdRefrUsMax` or `lcdLateRefrs` |
| **R6** | **`-O2` for LVGL's draw and blend code** (a PlatformIO `extra_scripts` per-library flag; the last `-O` wins) | Faster blend loops. Expect roughly 10–30 % less render time (to be measured) | More flash: flash headroom is about 287 KB today, before ALIVE lands. Measure the size delta | Build size; `lcdRenderUs` |
| **R7** | **HMI priority 1 → 2** (`hmi_thread.cpp:106`) | LED frames stay punctual while LCD and COM saturate core 0. HMI blocks between frames, so it cannot starve them | Medium: `FW/CONTROL_CENTER.md:663-665` records that the equal priorities are "as tested". The lease, ack and stress checks must be re-run | `ledShowGapMsMax` during transitions and cover uploads |

**Not recommended:**
- **An SPI clock above 80 MHz.** The S3 cannot do it, and the pins are on the GPIO matrix anyway.
- **Draw buffers larger than 2 × 1/10.** 2 × 1/5 would take 34.6 KB of extra internal RAM against 57 KB of low-water headroom. Espressif reports no gain beyond 25 % of the screen: see [esp_lvgl_port performance](https://github.com/espressif/esp-bsp/blob/master/components/esp_lvgl_port/docs/performance.md).
- **Draw buffers in PSRAM.** Both render writes and DMA are slower there.
- **`opa_layered` or snapshot layers.** They need a 64 KB LVGL heap and cost a full-layer composite.
- **Going below 16 ms.** The panel rate is unknown and probably no higher than 60 Hz.

### 4.1 DMA flush pattern (for R3)

This relies on three facts:
- TFT_eSPI DMA is available on the S3 (`ESP32_DMA`, `LIB/TFT_eSPI/Processors/TFT_eSPI_ESP32_S3.h:134-137`).
- `pushPixelsDMA()` queues one transaction and returns at once (`TFT_eSPI_ESP32_S3.c:633-670`).
- `dmaWait()` blocks on `spi_device_get_trans_result(…, portMAX_DELAY)`, so the task **sleeps** instead of spinning (`:614-626`).

A two-buffer pipeline that never renders into a buffer still on the wire:

```cpp
// init: tft.begin(); tft.initDMA(); tft.startWrite();   // CS stays asserted
// lv_display_set_buffers(disp, bufA, bufB, 11520, LV_DISPLAY_RENDER_MODE_PARTIAL);  // both internal, DMA-capable
static void flush_cb(lv_display_t* d, const lv_area_t* a, uint8_t* px) {
    const uint32_t w = lv_area_get_width(a), h = lv_area_get_height(a);
    lv_draw_sw_rgb565_swap(px, w * h);   // GC9A01 wants big-endian RGB565 (LIB/lvgl/src/draw/sw/lv_draw_sw.c:185)
    tft.dmaWait();                       // the other buffer's transfer has ended (normally already true)
    tft.setAddrWindow(a->x1, a->y1, w, h);
    tft.pushPixelsDMA(reinterpret_cast<uint16_t*>(px), w * h);
    lv_display_flush_ready(d);           // LVGL now renders into the OTHER buffer
}
```

Caveats:
- Before any other panel access (orientation `setRotation` in `lcd_manager`, `lcd_thread.cpp:66-80`), call `dmaWait()` first.
- In PARTIAL mode, `lv_refr_now()` returns **before** the last chunk leaves the wire. LVGL waits at the end of a refresh only in DIRECT mode (`LIB/lvgl/src/core/lv_refr.c:381-386`). If `cc_lcd_applied()` (`lcd_thread.cpp:346`) must mean "on glass", call `tft.dmaWait()` just before it. The difference is at most about 1.2 ms.
- `CONFIG_SPI_MASTER_ISR_IN_IRAM` is off in the prebuilt SDK. The DMA completion interrupt is therefore deferred during flash writes (SPIFFS `save`), which only stretches that frame.
- The fallback is ESP-IDF `esp_lcd` (`esp_lcd_new_panel_io_spi` with `on_color_trans_done`), which is present in this SDK (`sdkconfig.h:353`). It is the standard esp_lvgl_port route, but the change is bigger: the init sequence and orientation move off TFT_eSPI.

---

## 5. Risks

**Tearing without TE sync.**
- GRAM writes race the panel's own scan. A frame that spans the scan position shows part of the old and part of the new content.
- A full frame takes about 12 ms to send, which is comparable to one panel scan at 60–80 Hz. Most full-screen animated frames will therefore contain a tear somewhere, at a drifting position.
- **The design keeps motion small.** A slide moves ≤ 20 px, about 1–4 px per frame at 60 fps with ease-out. The volume lift is ≤ 8 px, and the rest are opacity changes. So a tear shows as a faint horizontal step, not a torn object.
- The visible cases are a **full cover swap** (one scan with half old and half new cover) and, if built, a crossfade.
- Rotation (`setRotation`, `lcd_thread.cpp:66-80`) can make the write order perpendicular to the scan, which turns the tear into a diagonal.
- Mitigations:
  - Keep the motion small (already done).
  - Never render faster than the panel rate (16 ms is the floor).
  - If the Binaris PCB routes the panel's TE pad to a free GPIO, start each full-frame refresh on the TE edge. That locks LVGL to the panel rate, and an 11.5 ms transfer fits any panel period above about 12 ms.
  - Whether TE is routed cannot be learned from the firmware. Ask Binaris or check the schematic.

**CPU starvation on core 0.**
- HMI, LCD and COM share priority 1, with 1 ms time slicing. A busy LCD delays COM and HMI by at most a tick each time they become ready, but it takes CPU share.
- R4 alone leaves 99 % of core 0 busy during transitions: slower media ingest and about 1–2 ms of LED jitter. Transitions are short (≤ 560 ms), so nothing breaks.
- IDLE0 still runs on the LCD's `vTaskDelay(1)` per pass, so the 10 s task watchdog is safe.
- With R3, the LCD sleeps during DMA and the budget improves. The table shows 35–88 % during a full-screen 60 fps transition.
- Worst stack-up: an opacity-blended slide, the ALIVE engine at its 3 ms ceiling, and a cover upload in COM at the same time. LCD fps then degrades gracefully. The animations are time-based (`lv_anim` uses `act_time`), so a dropped frame shortens nothing.
- R7 keeps the LEDs punctual under exactly this load.

**LED task cadence.**
- Without R1 the LEDs stay at about 49 fps whatever the LCD does.
- The alive engine's fastest time constant is the awake cursor rise: τ = 10 ms (`FW/src/cc_alive.h:82`). That is shorter than one frame at any feasible rate: 81 % of the step lands in one 60 fps frame, and 87 % at 49 fps. The cursor is effectively instant either way, as designed.
- Frame gaps above 50 ms are clamped (`maxFrameGapMs`, `cc_alive.h:59`). Watch for them during JPEG decodes only if HMI loses its slice, which it does not, because of time slicing.

**The FOC core.**
- FOC runs on core 1 and is untouched.
- The two cores share the cache and PSRAM bus, though, and 60 fps full-screen cover blits double the PSRAM read rate (115 KB per full frame, about 7 MB/s at 60 fps).
- Check `focAgeMs` and the haptic feel during transitions. This is speculative, but cheap to rule out.

**RAM and flash.**
- R3: +11.5 KB of internal RAM. If needed, `LV_MEM_SIZE` 64 KB could give back about 16 KB, since the low-water mark is 36.6 KB free.
- R6: flash grows. It must stay below `0x140000` together with ALIVE.

**Ack timing.** With DMA, `lv_refr_now` returns about 1 ms before the last chunk lands (see §4.1). Harmless for the lease, but noted so that no test assumes an exact "on glass" time.

---

## 6. Should the LED engine run faster than 60 fps?

The design's damping is time-based: `a = 1 − e^(−dt/τ)` with dt from `millis()` (`FW/ALIVE.md:372`; `cc_alive.h:59,80-87`). The **curves are identical at any frame rate**. Only the sampling changes.

**Pros of more than 60 fps (for example 120 Hz):**
- **Dither flicker moves up.**
  - ALIVE's error-diffusion dither (`FW/ALIVE.md:361`) turns a fractional level into a toggle pattern. For a constant level with fractional part f, the slowest component is f × fps.
  - At the resting "Warm · alive" levels, many channels sit at 0.x–3 LED counts, because the curve leaves "most segments below one LED count" (`FW/ALIVE.md:480`). There, an alternation between 1 and 2 is a 2:1 brightness step.

  | Fractional part | 49 fps | 60 fps | 120 fps |
  |---|---|---|---|
  | 0.50 | 24.5 Hz | 30 Hz | 60 Hz |
  | 0.25 | 12.2 Hz | 15 Hz | 30 Hz |
  | 0.10 | 4.9 Hz | 6 Hz | 12 Hz |

  In a dim room these low-frequency toggles can read as **twinkle**. 120 Hz doubles every frequency.
- A fast spin's cursor trail is sampled at twice the positions, which is marginal. At 3 turns per second (about 200 detents per second) the cursor moves about 3 LEDs per 60 fps frame.
- It matches the desktop twin's higher refresh a little more closely. Parity is defined in `e` at the same `t`, not per frame, so this is not required.

**Cons:**
- **CPU.** Running the whole engine at 120 fps doubles its cost, up to 36 % of core 0 at the 3 ms ceiling, on the same core as LCD and COM.
- **FastLED's own dither turns itself on at ≥ 100 fps.**
  - `FastLED.show()` suppresses dithering only while `m_nFPS < 100` (`LIB/FastLED/src/FastLED.cpp:67`). HMI re-asserts `BINARY_DITHER` on every claim transition (`hmi_thread.cpp:284`).
  - At brightness 255, FastLED's binary dither still adds +1 to non-zero bytes on alternate pixels and frames (`LIB/FastLED/src/controller.h:412-421,464-466,493,522`).
  - That would break ALIVE's "wire bytes equal `q`" rule (`FW/ALIVE.md:363`). The alive path would have to call `FastLED.setDither(DISABLE_DITHER)`.
- **PWM beat.** WS2811 PWM refresh is only "≥ 400 Hz". Update rates close to that beat against the PWM phase. Stay at or below about 1/3 of it, so ≤ 133 Hz.
- More HMI wake-ups, and tighter punctuality needs (R7).

**Recommendation.**
1. First make it a **true 60 fps** (R1), which the design and the capability already promise.
2. Keep the engine (targets, events, animator) at 60 fps.
3. If the hands-on A/B with `ledDither` shows twinkle at the resting levels, add an **output-only 120 Hz pass**. It re-runs just §9 (EOTF, drive, power limit, quantise with dither) on the last `e` or `v` values, which costs about 20 µs per pass. Disable FastLED's dither at the same time.
4. Never exceed about 133 Hz.

---

## 7. Recommended targets

| Surface | Today | Target | Condition |
|---|---|---|---|
| LCD animated transitions (slide, volume reveal, fades) | ≤ 30 fps, 100 % area | **60 fps** (16 ms period) | R2 + R3 + R4 |
| LCD heaviest frame (opacity-blended full screen: first 220 ms of a slide, art fades) | 30 fps | **≥ 45 fps**, 60 expected | R3 + R4 (R2b removes most of these frames) |
| LCD two-cover crossfade (if the knob ever gets one) | not built (instant swap) | keep the instant swap, or accept a short fade at 40–60 fps | R3 |
| LCD single-frame changes (detent text) | about 5–7 ms to the panel | ≤ 5 ms | R2/R3 |
| LCD JPEG hitch | 46–154 ms freeze | **0 ms** on the render path | R5 |
| LED ring and buttons | 49 fps measured | **60 fps**, gap ≤ 18 ms | R1 (+ R7 under load) |
| LED output dither (optional) | 49 Hz | 120 Hz output-only pass | only after the A/B; FastLED dither off |
| Anything on the knob at 240 Hz | — | **not possible** | SPI 87 fps ceiling; panel rate ≤ 60 Hz likely |

---

## 8. Measurement plan (hardware window, with the user's go-ahead)

### 8.1 Diag counters to add

All counters are additive in `{"diag":"?"}`. They are sampled by the LCD and HMI threads and published like `cc_diag_lcd` (`lcd_thread.cpp:425-438`), because LVGL is not thread-safe.

| Field | Where | Definition |
|---|---|---|
| `lcdFps` | LCD, `LV_EVENT_REFR_READY` with ≥ 1 flushed area | Refreshes that reached the panel in the last full second |
| `lcdFpsAnimMin` | LCD | Lowest 1 s `lcdFps` while `lv_anim_count_running() > 0`, reset on read |
| `lcdRefrUsMax` / `lcdRefrUsAvg` | `LV_EVENT_REFR_START` → `REFR_READY` (+ the final `dmaWait` with R3) | Frame time |
| `lcdFlushUs` / `lcdRenderUs` | Time inside `flush_cb` and waiting for DMA vs the rest | Shows which side binds |
| `lcdPxPerRefr` / `lcdFullRefrs` | Σ w·h per refresh; count of refreshes ≥ 57,600 px | Proves R2 |
| `lcdLateRefrs` / `lcdMaxGapMs` | Interval between refreshes while animating > 1.5 × period | Jank count, including JPEG stalls |
| `lcdBusyPct` | Σ pass time minus the `vTaskDelay`, per second | LCD share of core 0 |
| `core0IdlePct` | `esp_register_freertos_idle_hook_for_cpu(…, 0)` counter, calibrated at rest | Core 0 headroom (run-time stats are off in the prebuilt SDK) |
| `lcdSpiHz` | `spiClockDivToFrequency` or a read of the SPI2 clock register at boot | Confirms 80 MHz |
| `ledFps`, `ledRenderUsMax`, `ledRenderUsAvg` | HMI (already in ALIVE, `FW/ALIVE.md:383-385`) | — |
| `ledShowGapMsMax`, `ledLateShows` | HMI | Max interval between `show()` calls; count of intervals > 20 ms |

Keep the existing counters: `jpegDecodeMsMax`/`Last`, `led.ring.frames`, `lcdAgeMs`/`hmiAgeMs`/`comAgeMs`/`focAgeMs`.

### 8.2 Procedure

The same flash discipline as cc5.3 applies: the app-only procedure with backup, verify and rollback, and nothing done without the user's go-ahead.

1. **Baseline build** (cc5.3 or cc5.4 plus counters only, no behaviour change):
   - A scripted tour with the companion quit, using the existing check tooling: 20 screen changes, 20 volume reveals, 10 cover arrivals, a 5 s fast spin through an Up next playlist, and a 60 s idle.
   - Record the §8.1 fields every second.
2. **A/B builds**, one variable at a time, each with the same tour:
   - (a) R1
   - (b) R2
   - (c) R3
   - (d) R4
   - (e) R5
   - (f) R6
   - The lease and stress checks (`check_nanod_cc5.py` and the lease check) must still pass on each.
3. **Panel rate and tearing:**
   - A diagnostic screen that alternates two full-screen colours on every refresh at the maximum rate, filmed with the phone's 240 fps slow-motion mode. Count the distinct panel states per second (that is the panel rate), and note tear lines during a slide and a cover swap.
   - If a TE pad is reachable, a scope on it gives the rate directly.
4. **FOC check:** watch `focAgeMs` and the detent feel during the R3/R4 tour.

### 8.3 Acceptance

| Field | Required |
|---|---|
| `lcdFpsAnimMin` | ≥ 55 on opaque-cover transitions; ≥ 45 on blended ones |
| `lcdLateRefrs` | 0 outside cover arrivals, and 0 with R5 |
| `lcdFullRefrs` | Only slides and art fades (R2) |
| `ledFps` | ≥ 58 at idle; ≥ 55 during transitions and cover transfers. This tightens ALIVE's 55/45 (`FW/ALIVE.md:468`) once R1 + R7 are in |
| `ledShowGapMsMax` | ≤ 20 ms |
| `ledTxTimeouts` | 0 |
| `heapMinFree` | ≥ 40 KB |
| Check suites | No regressions in the lease, ack and stress checks |
| Hands-on | The user judges the slide, the volume reveal and resting LED twinkle, with `ledDither` A/B |

---

## 9. Sources

**Firmware** (`FW/` = `firmware/`):
- `platformio.ini:16,24-25,39-49`
- `boards/nanofoc_d.json:9-15`
- `include/lv_conf.h:45,64,81,102,132,348,727,734,881`
- `include/nanofoc_d.h:24-29,47-63`
- `src/main.cpp:20-23`
- `src/lcd_thread.cpp:13,23-24,30,32,66-80,260-267,336-346,357,363-372,384,390-392,414-443`
- `src/cc_display.cpp:12-14,37-39,86-87,797-798,821-822,836-837,934,1016-1025,1043,1067-1076,1139-1223,1264-1273`
- `src/cc_display.h:6-9`
- `src/hmi_thread.cpp:106,276-284,299-307,322`
- `src/com_thread.cpp:18,196-202`
- `src/cc_led_rmt.h:90`
- `src/cc_led_rmt.cpp:8-16`
- `src/cc_led_wire.h:10-24`
- `src/cc_alive.h:59,80-87`
- `ALIVE.md:25,361-363,369-385,468-469,480`
- `CONTROL_CENTER.md:584,641-648,663-665`

**Libraries** (`LIB/` = `.pio/libdeps/nanofoc_d/`):
- `lvgl/src/drivers/display/tft_espi/lv_tft_espi.cpp:54-59,67-81`
- `lvgl/src/display/lv_display.c:94`
- `lvgl/src/misc/lv_anim.c:64`
- `lvgl/src/misc/lv_timer.c:165,297`
- `lvgl/src/core/lv_refr.c:335,381-386,994-1023,1053-1063`
- `lvgl/src/core/lv_obj_style.c:278`
- `lvgl/src/draw/sw/blend/lv_draw_sw_blend_to_rgb565.c:340-354`
- `lvgl/src/draw/sw/lv_draw_sw.c:185`
- `TFT_eSPI/TFT_eSPI.cpp:74-83,3827-3833,3864-3873`
- `TFT_eSPI/Processors/TFT_eSPI_ESP32_S3.c:285-325,374-426,586-670,835-880`
- `TFT_eSPI/Processors/TFT_eSPI_ESP32_S3.h:134-137`
- `TFT_eSPI/TFT_Drivers/GC9A01_Init.h:148-149,225`
- `FastLED/src/FastLED.cpp:67,221-235`
- `FastLED/src/controller.h:372-421,461-467,493,522`

**Recorded device data:**
- `app/diagnostics/cc5.3-device-checks.json` (`diagStart`, `diagBefore`, `sections.diag.after`)
- `cc5.3-lease-checks.json` (`diagStart`, `diagEnd`)
- `cc5-device-checks.json`
- `app/firmware/BUILD-cc5.3.md:96-100,170`

**Design:**
- `HO/README.md:37,110,126,192`
- `HO/specs/03-SCREEN-and-state.md:57-66,88-89,98,113-117,161`
- Earlier analysis: `ui-v2-analysis/04-firmware-gaps.md:289-290,645`

**External:**
- GC9A01A datasheet V1.0 (GalaxyCore, 2019): §5.4 TE p.78–79, §6.3.2 B5h p.156–157, §6.4.1 E8h p.164–165, §7.3.4 4-line SPI timing p.190. <https://github.com/fbiego/dt78/blob/master/datasheets/GC9A01A.pdf> (local copy for reading: `<scratch>/refresh-study/GC9A01A.pdf`)
- ESP-IDF SPI master, ESP32-S3: IO_MUX pins, 80 MHz vs GPIO-matrix limits. <https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/spi_master.html>
- Espressif esp_lvgl_port performance notes: buffer size, double buffering, refresh period. <https://github.com/espressif/esp-bsp/blob/master/components/esp_lvgl_port/docs/performance.md>
- WS2811 datasheet (Worldsemi): PWM ≥ 400 Hz, 800 kbps, reset ≥ 50 µs. <https://cdn-shop.adafruit.com/datasheets/WS2811.pdf>

**Model:** `<scratch>` (output `knob_model.out.txt`). Pure arithmetic, with its assumptions stated in §2.2; replace them with the §8 measurements.
