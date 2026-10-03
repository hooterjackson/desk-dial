# refresh-01 — Current desktop pipelines at 240 Hz

Analysis only (read-only pass, 2026-09-25). The user asked for every animation to run at the monitor's
full refresh rate: *"my screen is 240hz -- we should ensure all of the animations both on the knob on
the screen and the fullscreen swipes through album artwork, tracks, app windows is at maximum refresh
rate so it looks super smooth"*. This file covers the **desktop pipelines as built** (desktop v6: the
window carousel and the floating knob), plus the `alive_lights` twin. It answers four questions:

1. What work runs per frame?
2. What does that work cost on this PC?
3. Can the new explorer and Up next overlays reach 240 fps on the same CPU path?
4. What low-risk changes get the existing pipelines to 240 Hz, or close?

Firmware (LVGL LCD, LED task) is out of scope here.

## 0. Conventions and setup

- **Code references** are `control_center/<file>.py:<line>`, relative to `app/`.
  Docs are `CAROUSEL.md §n` and `FLOATING_KNOB.md §n`.
- **"Spike"** means the v6 carousel visual spike. It ran **on the user's screen** on 2026-09-24. Its data is
  under `<scratch>/carousel-spike/` (`spike.py`, `results_p4.json`, `p4_frames.json`, `p4b_frames.json`).
  It is the only on-screen timing data available. Everything new in this file was measured **headless**:
  - PIL images;
  - DIB sections in memory DCs;
  - the real `CarouselPresenter` running inline on a fake clock with the preview backend of
    `tests/tools/render_carousel_previews.py`.

  No window was created or shown, no serial port was opened, and there was no network traffic.
- **Machine** (measured):
  - CPU: AMD Ryzen 7 9800X3D, 8 cores / 16 threads, 96 MB L3.
  - GPU and RAM: RTX 4090; 64 GB DDR5-5600.
  - Display: one 5120 × 1440 monitor. `Win32_VideoController` reports 240 Hz.
    `DwmGetCompositionTimingInfo` reports `rateRefresh = rateCompose = 10000000/41667`, a
    **4.1667 ms** period (`dwm_timing.json`).
  - Scaling: 100 %. So the carousel's k = 2, and the floating knob's scale is 360/286 = 1.2587
    (ring 360 px, face 434 px, window 458 × 434).
- **Software:** Python 3.14.5 (GIL build: `sys._is_gil_enabled()` is True), Pillow 12.3.0,
  `sys.getswitchinterval()` = 5 ms. No `timeBeginPeriod`, `setswitchinterval` or thread-priority
  call exists anywhere in the project (grep).
- **Budget:** 4.17 ms per frame, single-threaded Python. A frame that misses a vblank is shown for
  2 or 3 vblanks (8.33 / 12.5 ms). With DwmFlush pacing, the frame rate is quantised to
  240 / 120 / 80 / 60 fps.
- **Run-to-run spread.** The PC was in use, with CPU load between 7 % and 42 % at run start.
  The carousel benchmark ran four times; its numbers are given as ranges over those runs.

## 1. Answer first

### Where each pipeline stands

| Pipeline | Work per frame | CPU per frame on its thread (median; p95) | Upload per frame | Paced result on this PC |
|---|---|---|---|---|
| **Carousel, Frosted**, slow turns | chrome compose + ≤ 7 thumbnail updates + chrome ULW | compose **5.0–6.3 ms** (p95 6.2–8.8) + present ≈ 0.8 → **5.8–7.1 ms** | 11.1 MB | **120 fps** (p95: 120–80) |
| Carousel, Frosted, fast turns (20 detents/s) | same, plus on each detent a re-registration (+1.1 ms) and a synchronous label render (+6.0 ms) | compose 5.8–8.6 (p95 8.6–12.4) + 0.8; detent frames 11–17 ms | 11.1 MB | 120–80 fps, with a 3–4 vblank hitch on each detent |
| Carousel, No background | heavier shadows; label with text shadows | compose 6.3–9.6 (p95 7.3–11.5) + 0.8; label on a detent 14.8 ms (fast-turn max 22–33 ms) | 11.1 MB | 120–80 fps, dips to 60 |
| Carousel open / exit | chrome; the frost fades by constant alpha only | open 5.1 (p95 5.5–5.8), exit 5.5–7.0 (p95 6.4–9.9), each + 0.8; the frost upload once ≈ 5.8 ms | 11.1 MB (frost: 29.5 MB once) | 120 fps; one extra lost frame at the frost upload |
| Carousel toast | pill re-scaled (spring) | 0.67 (p95 0.81) | 0.42 MB | 240 fps |
| **Floating knob slide** | ULW with a new `ptSrc.x` and alpha; the frame is unchanged | ≈ 0.05 ms (a 0.8 MB copy takes 0.011–0.015 ms) | 0.8 MB | **240 fps**, subject to the §3.6 hazards |
| **Floating knob content** (ring + LCD) | a new scene from the Tk tick | Tk: lights 0.04 + `ring_colors` 0.07. Overlay: compose 1.4–1.9 | 0.8 MB | **≤ ~32 Hz**: the 25 ms `after()` tick (§3.6), presented without vsync alignment |
| Floating knob content, if driven per vsync on the overlay thread (not built) | `alive` render + face compose + copy + ULW | **1.4–1.9 (p95 1.7–2.3)** + `alive` 0.06–0.17 | 0.8 MB | **240 fps feasible** |
| `alive_lights.render` | 60 cells + effect queue | rest 0.058, turning 0.094, busy 0.170 (p95 ≤ 0.215) | — | negligible |

### Key findings

1. **Every animation is time-based.** A higher refresh rate means more frames of the same curve, never
   faster motion (§2.5). No animation loop has a frame cap: the carousel and overlay loops are paced by
   `DwmFlush` alone. The only fixed cadence in an animation path is the **Tk tick** (`POLL_MS = 25`,
   `ui.py:99`). It feeds the floating knob's ring and LCD.
2. **The carousel cannot reach 240 Hz today.** The chrome compose at k = 2 costs 5–10 ms per frame.
   **Card shadows are 69–73 % of it** (`ShadowCache.paint`, 3.9 / 5.8 ms per frame). The masked paste
   (≈ 2.9 ns/px) dominates, ahead of the band resize. In fast turns, `render_label` (6.0 / 14.8 ms) also
   runs inside the frame on every detent, because `_prefetch` only runs when idle
   (`carousel.py:977`, `:1325-1333`).
3. **The knob slide is already 240 Hz-capable.** The knob's **content** is capped by the Tk tick at about
   30 Hz. At the user's 100 % scale, the face compose is cheap enough for 240 Hz once it is driven on
   the overlay thread.
4. **Three hidden 240 Hz hazards affect both pipelines** (§3.6):
   - **GIL.** After `DwmFlush`, the animation thread waits for the Tk thread's whole pure-Python burst:
     up to 10.5 ms for a 10 ms burst, and 11–24 % of frames are more than 2 ms late under 5–10 ms
     bursts. `setswitchinterval(0.001)` alone does not help at the default timer resolution.
   - **Pacer heuristic.** "Two DwmFlush calls under 0.5 ms in a row" triggers an "8 ms" wait.
   - **Timer resolution.** That "8 ms" wait really lasts **16 ms** at the default per-process timer
     resolution.
5. **The new explorer and Up next cannot reach 240 fps on the CPU/ULW path** (§4):
   - explorer ≈ 23–26 ms per frame;
   - Up next ≈ 8.5 ms per frame;
   - a monitor-sized ambient crossfade 15–23 ms per frame;
   - uploads of 3.5 GB/s (stage) or 7.1 GB/s (monitor) at 240 Hz before any compose.

   They need GPU composition. The CPU then only sets per-frame properties.
6. **Low-risk changes** (§5, measured on the real engine where possible):
   - Pacing and GIL fixes, plus the knob's LED engine on its own thread: **floating knob at 240 Hz**.
   - Label off the frame path, label and dots in their own layer, NEAREST shadow bands and cached badge
     scales: **carousel Frosted compose from 5.9 to 4.3 ms** in fast turns (median). That is still
     120 fps. p95 drops from 9.2 to 4.8 ms, and the detent hitches disappear.
   - **240 Hz for the carousel needs the shadows off the CPU** (DirectComposition, or DWM-scaled
     sprites). Compose then measures **2.1–2.4 ms** in fast turns (median), 2.9–3.4 ms with present.

## 2. What runs per frame (code reading)

### 2.1 Threads, loops and pacing

| | Carousel (v6 window picker) | Floating knob |
|---|---|---|
| Thread | `NanoD-carousel` (`carousel.py:2771-2819`) | `NanoD-overlay` (`overlay.py:1467-1513`) |
| Loop | `pump` → `engine.advance()` (the compose) → `backend.pace()` (DwmFlush) → `engine.present()` (thumbnails + ULW) (`carousel.py:2806-2819`) | `pump` → `engine.advance()` (the compose **and** present) → `pace()` while animating, else `GetMessageW` (`overlay.py:1501-1513`) |
| Pacing | `Pacer` (`carousel.py:476-520`): `DwmFlush`. A flush over 50 ms, or a failed one, switches to 10 frames of `MsgWaitForMultipleObjectsEx(8 ms)`. **Two flushes in a row that return in under 0.5 ms (`FAST_S`) → an 8 ms wait.** | `Win32Backend.pace` (`overlay.py:1205-1218`): the same heuristic (`FAST_FLUSH_SECONDS = 0.0005`, `PACE_FALLBACK_MS = 8`, `overlay.py:93-94`) |
| Idle waits | `SetTimer`, at least `USER_TIMER_MINIMUM_MS = 10` (`carousel.py:1805`, `:2208-2226`): capture timeout, toast hold. Not in the frame path. | `SetTimer` (`overlay.py:98`, `:1182-1203`): hide deadline, first-frame wait |
| Frame cap | none | none for the slide. Content: at most one scene per Tk tick (`FLOATING_KNOB.md §4`, "Frame rate"; `ui.py:1165-1209`) |

- **The Tk thread** runs `poll()` every `root.after(POLL_MS=25)` after the previous tick ends
  (`ui.py:1831-1839`). Each tick runs `runtime.poll()`, then `render()`. For the knob that means:
  - `preview_lights.render` (`ui.py:1195-1196`);
  - `ring_colors`, plus `render_lcd` when the LCD key changes (`ui.py:1292-1331`);
  - `overlay.submit()` → `WM_APP+1` (`overlay.py:1566-1586`).

  The overlay thread composes and presents **at once** on arrival, not at a vblank
  (`overlay.py:757-773`, `:939-968`). While shown and not sliding, it sleeps in `GetMessageW`
  (`overlay.py:561-569`).
- **Other Python threads compete for the GIL:**
  - `NanoD-capture`: the frost pipeline, about 34 ms of PIL work at every open, which overlaps the open's
    card fade (`CAROUSEL.md §11`);
  - IconWorker;
  - the serial reader;
  - the Tk thread.

  Every ctypes call (`DwmFlush`, `UpdateLayeredWindow`, `DwmUpdateThumbnailProperties`) and most
  heavy Pillow operations release the GIL and must take it back afterwards.

### 2.2 Carousel: one animated frame (Frosted default)

The surfaces at k = 2:

| Surface | Size | Bytes |
|---|---|---|
| Chrome (pane 2280 × 1120 + 32 px margin) | 2344 × 1184 | **11,101,184** |
| Frost | 5120 × 1440 | 29,491,200 (uploaded once, then constant alpha only) |
| Host | 2280 × 1120 | none: DWM thumbnails, no redirection bitmap |

References: `carousel_render.py:74`, `:198-202`, `:221-229`.

1. **`advance`** (`carousel.py:927-978`). `CarouselMachine.values(now)` evaluates up to 5 tweens × 9
   cards plus the dots (`:382-407`). The CSS cubic-bezier curves use a 2048-sample table and `bisect`
   (`:104-128`).
2. **`_prepare`** (`carousel.py:1363-1410`) builds the frame's inputs:
   - integer card rects, computed once per frame (`carousel_render.py:276-283`);
   - the thumbnail plan;
   - badge sprites from an LRU (`:1266-1287`);
   - the **label sprite** (`:1302-1323`). It is rendered synchronously on a cache miss. `LABEL_CACHE = 6`
     (`:201`), and the ±1 prefetch runs only when a turn of the loop has no work (`:977`);
   - the dots sprite, rebuilt whenever a dot width changes by 0.1 px (`:1335-1345`);
   - then `compose_chrome` into the chrome DIB (`:1398-1401`).
3. **`compose_chrome`** (`carousel_render.py:1577-1664`):
   1. `canvas.clear()` of the whole 11.1 MB.
   2. For each card, far to near:
      - `ShadowCache.paint` (`:742-779`): on every animating frame, 4 bands are BILINEAR-resized
        from a 1/4-resolution base, then pasted black through the mask;
      - the read-back of what farther cards left under this card, and `fade_lut` (`:1629-1646`);
      - the shade fill;
      - the badge `over_sprite` (scaled per frame through `_SpriteScaler`, BILINEAR);
      - the outline.
   3. The label and dots `over_sprite`.
4. **`pace`**: `DwmFlush`.
5. **`present`** (`carousel.py:980-1002` → `_present_session` `:1412-1493`):
   - releases;
   - **on a detent**: unregister every thumbnail, then `DwmRegisterThumbnail` far to near for
     |d| ≤ 3 plus the cards still fading (`:1421-1457`). The spike measured **1.1 ms**;
   - `DwmUpdateThumbnailProperties` with all five flags for every registered thumbnail
     (`:1458-1470`, `:2580-2589`). The spike measured **0.36 ms for 7**;
   - `GdiFlush` + `UpdateLayeredWindow` of the **whole** chrome DIB, with no `prcDirty`
     (`:2435-2437`, `:2399-2416`);
   - frost and dim: a constant-alpha-only ULW (`:2485-2486`, `:2460-2461`). No bytes move.
6. **Once per open:** `glass_upload` (`:2463-2483`), run from `_glass_ready` (`:1232`) during the card
   fade. It allocates and zeroes a 29.5 MB DIB, copies the frost into it, runs the ULW and frees it.
7. **Toast:** `_prepare_toast` (`:1662-1676`) re-scales the pill (premultiplied BILINEAR), clears,
   draws it over, then runs the toast ULW.

### 2.3 Floating knob

- **Slide** (220 ms in, 260 ms out, `overlay.py:86-87`). On each vblank: `SlideMachine.visible(now)` →
  `src_x`, alpha → `present()` with the **same** frame bytes. The copy is skipped when unchanged; only
  the ULW with a new `ptSrc.x` runs (`overlay.py:947-968`, `:1221-1252`). The DIB is 2W × H
  (`:1081-1111`). The ULW extent is W × H: 458 × 434 = 0.8 MB at 100 %.
- **Content** (on a scene):
  1. `KnobFace.compose` (`knob_face.py:428-456`):
     - a copy of the static base with the LCD (cached by LCD identity, `:365-398`);
     - per lit segment: a cached glow mask (64 levels, `:400-414`), then a **new solid RGBA image**
       (`_solid`, `:299-303`) alpha-composited;
     - a body sprite, cached by exact RGB in a 2048-entry LRU (`:416-425`). Continuous breathing
       fills this LRU (measured: 2048 entries).
  2. `_compose` (`overlay.py:892-937`): a new window-sized box and a paste for the inset, then
     `tobytes('raw','BGRa')` and `bytes()`.
  3. `present`: `GdiFlush` + one `memmove` **per row** (434 ctypes calls at 100 %,
     `overlay.py:1236-1241`) + ULW.

### 2.4 `alive_lights`

- The engine is pure Python floats. `render(now)` takes **uint32 integer ms** (`alive_lights.py:22`,
  `:1223-1280`), and dt is clamped to 50 ms (`:111`).
- At 240 Hz the integer-ms clock gives dt = 4 / 4 / 4 / 5 ms. That is still time-based: a comet moves
  0.04 segment per ms, so the quantisation cannot be seen.
- It is **not wired into the app yet**: the floating knob still uses `PreviewLights` (`ui.py:1195`).

### 2.5 Time-based motion

- **Carousel:** `Tween.value(now)` on `time.monotonic` (`carousel.py:135-174`).
- **Knob:** `SlideMachine.progress(now)` on the injected clock (`overlay.py:480-497`).
- **Toast:** `ToastMachine` (`carousel.py:427-473`).
- **LEDs:** `AliveLights` on ms timestamps.

All of them sample curves by time. At 240 Hz, the same motion gets more samples.

The one flaw: the carousel samples `now` when the compose **starts** (`carousel.py:930`), not when the
frame will be shown. With a compose of 5–10 ms, the delay to display varies by 1–3 vblanks from frame
to frame. Motion then judders on top of the lower frame rate. Change A5 fixes this.

## 3. Measurements (headless, this PC)

The scripts are in `<scratch>/refresh-study/` (list in §7).

### 3.1 Carousel compose at k = 2, 5120 × 1440 (`bench_carousel.py`, 4 runs)

The real presenter runs inline at 240 Hz fake-clock steps with the design's 10 sample windows:

1. a cold open, then hide;
2. a warm open (its label and sprite caches were cleared by hide);
3. 8 slow turns, 500 ms apart;
4. 16 fast turns, 50 ms apart;
5. settle, the Switch exit and the toast.

`compose_ms` is `CarouselEngine._prepare`: values, rects, plan, sprites, label, dots and
`compose_chrome`.

| Phase | Frosted: median ms | Frosted: p95 | Frosted: max | No background: median | No background: p95 | No background: max |
|---|---|---|---|---|---|---|
| Open (warm) | 5.06–5.14 | 5.47–5.78 | 15.3–21.7 | 6.17–8.93 | 6.56–9.90 | 25.1–27.7 |
| Slow turns | 5.03–6.29 | 6.20–8.78 | 8.7–10.4 | 6.32–9.56 | 7.31–11.46 | 11.5–14.9 |
| Fast turns | 5.76–8.64 | 8.61–12.41 | 11.3–17.0 | 6.90–10.48 | 10.55–15.60 | 22.5–32.6 |
| Settle | 4.66–7.02 | 5.73–9.59 | 5.8–9.8 | 5.90–9.58 | 7.04–11.05 | 7.7–11.7 |
| Switch exit | 5.52–7.03 | 6.35–9.91 | 6.6–10.3 | 6.80–10.05 | 7.90–12.15 | 10.3–12.7 |

- In every run, 1223–1224 of 1252 animated frames were over 4.17 ms.
- The open's max comes from the cold label render and the final at-rest frame (LANCZOS sprites).
  The fast-turn max comes from the synchronous `render_label` (§3.2).

### 3.2 Where the compose time goes

**Timers around `carousel_render` primitives** (`profile_carousel.py`; 677 frames of open, slow and
fast turns):

| ms per frame | Frosted | No background |
|---|---|---|
| `compose_chrome` total | 5.61 | 7.99 |
| **`ShadowCache.paint`** (6.2 calls) | **3.86 (69 %)** | **5.82 (73 %)** |
| `over_sprite` (badges, label, dots) | 0.48 | 0.70 |
| `_SpriteScaler.get` (badge re-scale) | 0.35 | 0.38 |
| `clear`, `_under`, `fade_lut`, outline, fill | 0.43 | 0.51 |
| `_prepare` minus compose (values, rects, plan) | 0.40 | 0.65 |

**Shadow internals** (`bench_shadow_explorer.py`, k = 2, centre card):

| Quantity | Value |
|---|---|
| Shadow box | 1276 × 916 px, 592,816 band pixels |
| Band resize, BILINEAR | 0.59–0.69 ms |
| Band resize, NEAREST | 0.11 ms |
| Paste only (cached bands, s = 1) | **1.70 ms** (≈ 2.9 ns/px) |
| Five cards animating | 3.58 ms (p95 3.96–4.11) |

Caching the bands cannot fix this: the masked paste dominates.

**Label render at k = 2** (`bench_label.py`):

| | Frosted | No background |
|---|---|---|
| `render_label` | 6.0 ms | 14.8 ms (two blurred text shadows) |

It is paid inside a frame whenever a detent lands on a label that was not prefetched. That is every
detent while the knob keeps turning.

### 3.3 Floating knob (`bench_knob.py`)

The ring comes from `AliveLights.render` at 240 Hz integer-ms steps, over three scenes:

- **rest:** asleep and breathing, all 60 cells lit;
- **turn:** 20 detents/s;
- **busy:** 6 effects plus the song hand.

It is mapped to `(r, g, b, level)` with an assumed Knob Face optical mix. The alive → floating-knob
mapping is not specified yet.

"Total" covers the mapping, `KnobFace.compose`, the inset box and BGRa conversion, and the DIB row
copy. The copy is replayed into a real 2W-wide DIB section in a memory DC.

| Scale | Window / ULW | Scene | Compose | Inset + BGRa | Row copy | **Total** median (p95) |
|---|---|---|---|---|---|---|
| **100 %** (1.2587, the user's) | 458 × 434, 0.80 MB | rest / turn / busy | 0.67 / 0.90 / 1.35 | 0.55 / 0.48 / 0.40 | 0.15 | **1.43 / 1.60 / 1.92** (1.74 / 2.01 / 2.32) |
| 2.0 ("k = 2", ring 572 px) | 726 × 688, 2.00 MB | rest / turn / busy | 1.40 / 2.02 / 3.33 | 1.94 / 1.69 / 1.82 | 0.45 | 3.85 / 4.21 / 5.58 (4.25 / 5.07 / 6.08) |
| 200 % (2.5175) | 916 × 868, 3.18 MB | rest / turn / busy | 1.72 / 2.58 / 4.41 | 3.10 / 2.90 / 2.75 | 0.59 | 5.46 / 5.99 / 7.81 (6.04 / 6.89 / 8.54) |

Other knob costs:

| Cost | 100 % | Scale 2.0 | 200 % |
|---|---|---|---|
| Compose with a **new LCD every frame** (an LCD transition mirrored per vblank) | 1.82 ms | 4.26 ms | 6.27 ms |
| `render_lcd` on the Tk thread, per LCD change (302 px) | 2.29 ms | — | — |
| `KnobFace` build, once per DPI | 28 ms | — | — |

### 3.4 LED engines

| Engine | Where | Cost per call |
|---|---|---|
| `AliveLights.render` at 240 Hz | — | rest 0.058, turn 0.094, busy 0.170 ms (p99 ≤ 0.28; one 0.70 ms outlier) |
| `PreviewLights.render` (v4, today) | Tk tick | 0.043 ms |
| `ring_colors` (today) | Tk tick | 0.068 ms |

Neither engine is a bottleneck.

### 3.5 Upload cost per extent (`bench_blit.py`, offscreen)

A ULW-equivalent copy between two DIB sections in memory DCs. "Hot" reuses one pair; "cold" rotates
pairs past the L3.

| Extent | Bytes per frame | ×240 | `memmove` hot / cold median | `BitBlt` hot / cold median |
|---|---|---|---|---|
| Knob window, 100 % (458 × 434) | 0.80 MB | 0.19 GB/s | 0.011 / 0.012 ms | 0.015 / 0.015 ms |
| Knob window, scale 2.0 (726 × 688) | 2.00 MB | 0.48 GB/s | 0.080 / 0.077 | 0.088 / 0.089 |
| Spike chrome = pane (2280 × 1120) | 10.21 MB | 2.45 GB/s | 0.393 / 0.427 | 0.350 / 0.527 |
| **v6 chrome (2344 × 1184)** | 11.10 MB | 2.66 GB/s | **0.427 / 0.482** | 0.388 / 0.614 |
| V2 stage, 1280 × 720 × k2 (2560 × 1440) | 14.75 MB | **3.54 GB/s** | 0.570 / 0.670 | 0.532 / 0.882 |
| Monitor (5120 × 1440) | 29.49 MB | **7.08 GB/s** | 1.150 / 1.341 | 1.222 / 1.849 |

- **Cross-check against the screen.** The spike's real `UpdateLayeredWindow` of a 2280 × 1120 surface
  on this PC took **0.413 ms median** (p95 0.482), against 0.393 ms for the offscreen `memmove`. So a
  ULW costs the calling thread about **one memcpy at ~25 GB/s**.
- `dwm.exe`'s own upload of each updated layered surface to the GPU comes on top of that and was not
  measured.
- **The Frosted open's one-off frost upload** (`bench_glass_upload.py`):

  | Step | Time |
  |---|---|
  | DIB alloc and zero | 2.84 ms |
  | Frost paste | 1.07 ms |
  | Free | 0.64 ms |
  | Total, without the ULW | 4.51 ms |
  | Estimated ULW | ≈ 1.3 ms |

  About 5.8 ms in total on the carousel thread: one lost 240 Hz frame during the open. This is
  `glass_upload_ms`, which `CAROUSEL.md §11` lists as never measured.

### 3.6 Pacing, GIL and timers on this PC

**The spike is the on-screen evidence** (`spike_intervals.py` over `p4_frames.json` and
`p4b_frames.json`):

| Run | Frame interval | Frames over 1.448 s | Work per frame | `DwmFlush` wait |
|---|---|---|---|---|
| p4 | median **4.20 ms** | 322 against 348 vsyncs: **221.6 fps, 7.5 % missed** | median 1.44 ms | median 2.84 ms |
| p4b | p95 8.7 ms, p99 13.7 ms | 306 frames: 210 fps, 12 % missed | — | — |

- `DwmFlush` does pace at 240 Hz here.
- A trivial 1.4 ms frame still dropped frames. A concurrently running Python thread (the spike's
  screenshot thread) polled `time.sleep(0.5 ms)` and contended for the GIL. The p4b run took more
  screenshots and missed more frames.

**GIL reacquire lateness** (`gil_latency.py`). A 240 Hz thread waits on a high-resolution waitable timer
(the stand-in for `DwmFlush`: both are ctypes calls that release the GIL). Another thread runs
pure-Python bursts every 25 ms, like the Tk tick.

| Switch interval | Timer resolution | Tk-like burst | Lateness p95 | Lateness max | Frames > 2 ms late |
|---|---|---|---|---|---|
| **5 ms (today)** | default | 2 ms | 0.85 ms | 2.49 ms | 2.3 % |
| 5 ms | default | 5 ms | 3.72 | 5.53 | 10.9 % |
| 5 ms | default | 10 ms | 8.10 | **10.49** | **23.8 %** |
| 1 ms | default | 5 / 10 ms | 3.19 / 7.28 | 5.28 / 10.13 | 10.1 / 21.3 % (**no better**) |
| 1 ms | `timeBeginPeriod(1)` | 5 / 10 ms | 1.48 / 1.72 | 2.43 / 2.70 | 0.6 / 1.1 % |
| 5 ms | `timeBeginPeriod(1)` | 5 / 10 ms | 3.84 / 5.51 | 4.98 / 6.02 | 10.1 / 11.8 % |
| **0.2 ms** | default | 2 / 5 / 10 ms | ≤ 0.51 | **≤ 0.93** | **0 %** |

At the default per-process timer resolution, the waiting thread cannot force a switch before the Tk
burst ends. It only can with a sub-millisecond switch interval, or with 1 ms timer resolution plus a
1 ms switch interval.

**Timer granularity** (`timer_granularity.py`, no windows):

| Wait | Default per-process resolution | With `timeBeginPeriod(1)` |
|---|---|---|
| `MsgWaitForMultipleObjectsEx(8 ms)` (the Pacer and overlay fallback) | **15.95 ms** | 8.25 ms |
| Thread-queue `SetTimer(25 ms)` | 31.5 ms | 31.5 ms |
| `SetTimer(10 ms)` | 15.9 ms | 16.0 ms |
| `time.sleep(4 ms)` | 4.5 ms | 4.5 ms |

- `NtQueryTimerResolution` reports a system-wide 1.0 ms: another process asked for it. On Windows 11
  that does not apply to this process's waits.
- **The Tk tick's real period** was not measured here, because it needs a Tk window. If Tcl's Windows
  notifier waits at the default resolution, as the USER timer above does, `after(25)` fires about every
  31 ms plus the tick's work: **about 30 Hz** of knob content. Confirm it from tick timestamps on the
  supervised run.

**The "fast flush" heuristic** (`carousel.py:512-517`, `overlay.py:1211-1218`) is a modelled risk, not a
measured one:

- When the frame work is longer than a vblank (5–10 ms today), where a frame ends relative to the next
  vblank varies from frame to frame.
- A flush that starts less than 0.5 ms before a vblank can return in under 0.5 ms. Under a
  uniform-phase model that is up to ≈ 12 % of flushes.
- Two in a row (up to ≈ 1.4 % of frames) trigger the "8 ms" wait, which really lasts 16 ms. The counter
  only resets on a slow flush.
- The spike's short frames hit it once in 322 flushes.

### 3.7 Maximum sustainable frame rate on this PC

"Unpaced" is 1000 / (median work). "Paced" is what `DwmFlush` quantises it to.

| Pipeline | Median work per frame | Unpaced | Paced (median; p95) | What dominates |
|---|---|---|---|---|
| Carousel, Frosted, slow turns | 5.8–7.1 ms | 140–170 fps | 120; 120–80 | card shadows (masked paste), then label/badge sprites |
| Carousel, Frosted, fast turns | 6.6–9.4 ms (+ detent frames 11–17) | 105–150 | 120–80; 80–60 | shadows; `render_label` 6 ms and re-registration 1.1 ms per detent |
| Carousel, No background | 7.1–10.4 ms | 95–140 | 120–80; 80–60 | shadows 5.8 ms; `render_label` 14.8 ms per detent |
| Carousel toast | 0.7 ms | > 1000 | 240 | — |
| Knob slide | ≈ 0.05 ms | > 1000 | 240 | GIL and pacer hazards only |
| Knob content today | Tk tick | — | ≈ 30 Hz, unaligned | the 25 ms `after()` tick |
| Knob content per vblank (100 %) | 1.5–2.1 ms | ~500 | 240 | the compose (`_solid` allocations, LRU thrash), the BGRa conversion |

## 4. The new overlays on the same CPU path (explorer, Up next)

`bench_shadow_explorer.py` estimates them with the v6 primitives (premultiplied `Canvas`,
`ShadowCache`, `Sprite`, `TextEngine`) on the 2560 × 1440 stage (1280 × 720 × k2). Card geometry,
shadows and timing follow `03-desktop.md §2.3-2.6` and §3.

**Music explorer.** One 420 ms turn is about 100 frames at 240 Hz. Per frame: 5–6 visible
cover cards re-scaled from a 680 px master, explorer shadows (`0 40 80 .55` centre, `0 16 36 .4` sides),
shade, a 1 px border, label, tabs and dots.

| Variant | Median | p95 |
|---|---|---|
| Premultiplied sprite resize | 26.0 ms | 28.7 ms |
| Opaque RGBX resize | 23.5 ms | 25.8 ms |

Its parts, per frame:

| Part | Time |
|---|---|
| Cover resize | 11.3–11.5 ms |
| Shadows | 5.2–5.3 ms |
| Cover paste + shade + border | 5.4 ms |
| Label, tabs and dots | 0.46 ms |

That is **≈ 40 fps**.

**Up next.** Per frame: the 760 px big-cover crossfade (`Image.blend`), 10 rows (text sprite + 112 px
cover) scrolling, and the focused row scaled 1.06 with its shadow. **8.45 ms median (p95 9.44)** →
80 fps paced.

**Ambient layer at monitor size** (blur 90, 600 ms crossfade):

| Method | Per frame |
|---|---|
| Blend two pre-blurred layers | 15.4 ms |
| Blend small, then upscale to the monitor | 23.3 ms |
| Paste over the frost | 21.5 ms |

**The upload alone:**

| Surface | Per frame | At 240 Hz | Share of the 4.17 ms budget |
|---|---|---|---|
| Stage | 14.75 MB | **3.54 GB/s** | 0.57–0.67 ms (14–16 %) |
| Monitor | 29.49 MB | **7.08 GB/s** | 1.15–1.34 ms (28–32 %) |

`dwm.exe` then uploads the same bytes to the GPU on every frame.

- **Verdict: 240 fps is not feasible on the CPU/ULW path.**
  - The explorer is about 6× over budget before its upload.
  - Even with mip-mapped cover masters and NEAREST shadow bands, it stays above 10 ms: the 5–6 covers
    and their shadows are roughly 3 M px of masked writes per frame, against a single-threaded rate of
    about 3 ns/px.
- **The two parts that must move to the GPU:**
  - card and cover scaling and opacity;
  - the ambient crossfade.

  In either case the CPU then only updates properties each frame.
- **Crossfading two monitor-sized layered windows by constant alpha costs no per-frame upload**, as the
  frost fade does today. But each focus change still has to pre-compose and upload 29.5 MB
  (≈ 21 ms of PIL off-thread, plus ≈ 5.8 ms on the animation thread; §3.5). At 20 detents/s that is a
  hitch on every detent.
- `README §7.1`'s fallback ("If Tk can't do the backdrop blur, host just the overlays in a small PySide6 or
  WebView2 window") was framed around the blur. **At 240 Hz the deciding factor is per-frame
  composition, not the blur.** GPU scene graphs (DirectComposition, WebView2's compositor, Qt Quick)
  animate transforms and opacity at the display rate, with the captured frost as a static texture.
  Choosing between them is outside this file.

## 5. Low-risk improvements to the existing pipelines, quantified

`bench_variants.py` applied each carousel change as a patch to `carousel_render` in the benchmark
process, then re-ran the real engine. The medians below come from that run, which fell in the "fast"
regime: its base is at the low end of §3.1's ranges, and the savings are relative to that base.
"Present" adds about 0.8 ms (0.36 thumbnails + 0.45 ULW) to every compose figure.

### 5.1 A — Pacing and scheduling (both pipelines; no visual change)

| # | Change | Where | Effect (measured or derived) |
|---|---|---|---|
| A1 | Judge pacing by the **interval between flush returns** (at least half a period means it is pacing), not by the call's duration. Read the period from `DwmGetCompositionTimingInfo`; make the fallback wait one period. | `carousel.py:476-520`, `overlay.py:1205-1218` | Removes the 16 ms "fast flush" stalls (§3.6) |
| A2 | `timeBeginPeriod(1)` at startup, `timeEndPeriod` at exit (per process on Windows 10 2004+ and 11). | `standalone.py` | Fallback waits: 15.95 → **8.25 ms**. A prerequisite for A3's 1 ms option. |
| A3 | `sys.setswitchinterval(0.0002)`, or 0.001 together with A2 | at startup | GIL lateness under 2–10 ms Tk bursts: max **10.5 → 0.93 ms**, frames more than 2 ms late **24 % → 0 %**. With A2 + 1 ms: max 2.7 ms, 1.1 %. Cost: more GIL hand-offs. Check the Tk tick time and serial latency. |
| A4 | `SetThreadPriority(ABOVE_NORMAL)` on `NanoD-carousel` and `NanoD-overlay` | thread start | Helps against other processes, not against the GIL. Optional. |
| A5 | Sample the animation clock at the **predicted display time** (the next vblank from `qpcVBlank` and `qpcRefreshPeriod`, plus the frames the compose will take), not at compose start | `carousel.py:930`, `overlay.py:745` | Removes the 1–3 vblank latency jitter (§2.5). Uniform motion at any frame rate. |

### 5.2 B — Carousel compose

| # | Change | Median / p95 compose, Frosted fast turns | No background, fast turns | Risk |
|---|---|---|---|---|
| base | as built | 5.87 / 9.20 (max 11.7) | 6.87 / 10.57 (p99 20.8, max 23.2) | — |
| **B1** | Labels off the frame path: pre-render ±3 at open and after each detent on a worker (or in idle time slices), keep more than 6 cached, and draw the previous label until the new one is ready | 5.67 / **6.27** (max 9.0) | 6.80 / **7.37** (max 9.1) | low: the label may swap a frame or two late |
| **B2** | Label and dots in their **own layered window** above the chrome. The group fade uses `SourceConstantAlpha`; ULW only on a change (per detent, about 1 MB) | 5.50 / 6.45 (−0.27 on slow turns) | 6.46 / 6.97 (−0.41 on slow turns) | low: the same pattern as dim and glass |
| **B3a** | Shadow bands resized with **NEAREST while animating**; the rest frame keeps BILINEAR | 4.49 / 5.06 (−1.1) | 5.27 / 6.18 (−1.4) | low code risk. Needs a visual check: 4× nearest of a 1/4-resolution blur, in motion only. |
| **B4** | Badge sprites at quantised scales (1/64), cached | **4.25 / 4.83** (−0.24) | **4.99 / 5.71** | low |
| **B3b** (instead of B3a) | **No CPU shadows**: shadows drawn by the GPU (a DirectComposition visual per card, or DWM-scaled pre-rendered shadow sprites) | **2.13 / 2.62** with B1 + B2 + B4 | **2.18 / 2.70** | medium: a new mechanism; see below |
| B5 | Dirty-rect ULW (`UpdateLayeredWindowIndirect` + `prcDirty` = the union of this frame's and the last frame's card and shadow footprints) | upload 0.45 → about 0.35–0.4 ms in turns; the card row covers most of the chrome | same | low, low value |
| B6 | Keep the thumbnail path as is: 0.05 ms per update; re-registration 1.1 ms per detent, needed because z-order is registration order | — | — | — |

**What that buys:**

| Change set | Frosted fast turns, compose + present | Frame rate |
|---|---|---|
| Today | 6.7 ms median, 10 ms p95, detent hitches | 120–80 fps |
| A + B1 + B2 + B3a + B4 | 5.1 / 5.6 ms | **still 120 fps**, but with no detent hitches and no 16 ms stalls. Slow turns: 3.6 + 0.8 = 4.4 ms, 120 with some 240. |
| A + B1 + B2 + B4 + **B3b** | ≈ **2.9–3.4 ms** median, ≈ 3.4–4 ms p95 | **240 fps**. Detent frames add re-registration (1.1 ms) and stay borderline. |

No background ends at about the same numbers.

**The catch in B3b.** Today the shadows live in the chrome, above the thumbnails. The chrome clips each
shadow out of its own card and dims it under nearer cards (`_under_keep`, `carousel_render.py:1513-1522`).

- **DWM thumbnails of shadow sprites.** The sprites would sit in cloaked, off-screen layered source
  windows, two per card (side and selected, crossfaded by `DWM_TNP_OPACITY`). Costs:
  - thumbnail updates: 10 more per frame, about 0.5 ms;
  - re-registration: about 21 thumbnails per detent, about 3.4 ms at the spike's 0.16 ms each;
  - unvalidated: whether thumbnails of cloaked layered sources keep their alpha.
- **DirectComposition.** Explicit visual z-order and no re-registration. It needs COM vtables through
  ctypes, or a small native helper.

Either way, B3b needs a spike on the user's screen. **Only B3b (or a full GPU chrome) gets the carousel to
240 Hz.** A through B4 get the carousel's worst cases under control.

### 5.3 C — Floating knob

| # | Change | Where | Effect |
|---|---|---|---|
| **C1** | **Drive the LEDs on the overlay thread.** `AliveLights` (0.06–0.17 ms) and the ring mapping move into `NanoD-overlay`. The Tk thread only posts frames and inputs. While the knob is visible and `alive.animating()` (breathing is continuous), the loop stays in `pace()` and composes once per vblank. | `overlay.py:742-784`, `:561-569`; `ui.py:1165-1209` | Knob content from **≈ 30 Hz to 240 Hz**. Measured per frame at 100 %: 1.43–1.92 ms median, ≤ 2.32 ms p95, plus the render. That leaves about 2 ms of headroom. |
| **C2** | **Compose straight into the DIB.** Map a premultiplied RGBX canvas over the DIB's left half: PIL `frombuffer` with a row stride of 2W × 4 bytes (the chrome's `Canvas.over_buffer` is the same idea, without a stride). Paste solid colours through the segment and glow masks: in RGBX that is an exact premultiplied "over", so neither the per-segment `Image.new` + `putalpha` nor the 2048-entry colour LRU is needed. | `knob_face.py:299-303`, `:416-456`; `overlay.py:892-937`, `:1236-1241` | Removes the inset box, the BGRa conversion, `bytes()` and 434 `memmove` calls: **−0.55–0.70 ms at 100 %**, −2.1–2.4 ms at scale 2.0, −3.3–3.7 ms at 200 %. Compose itself falls with the allocations. |
| C3 | The slide: nothing to change beyond A1–A3. It is already a per-vblank, 0.8 MB, content-free ULW. | — | 240 fps |
| C4 | The LCD mirror stays at content-change rate (`render_lcd` 2.29 ms at 100 % on Tk). The knob's own LCD animates on the device. Mirroring LCD transitions per vblank would mean C1 for the LCD too: 1.8 ms per frame at 100 % with a new LCD image every frame. | — | Optional |

With A + C1 + C2, the floating knob runs at 240 Hz at the user's 100 % scale, with about 2.5 ms of
slack per frame. Larger scales, from the measured parts:

| Scale | Today | After C2 | Frame rate after C2 |
|---|---|---|---|
| 2.0 | 3.9–5.6 ms | ≈ 1.5–3.3 ms | 240 |
| 200 % | 5.5–7.8 ms | ≈ 1.8–4.5 ms | 240 at rest and while turning; about 120 in busy moments |

## 6. What to confirm on hardware (the supervised check)

1. **Carousel frame intervals** on the real desktop during slow and fast turns: flush-return timestamps,
   or `DWM_TIMING_INFO.cFramesMissed` deltas. Record them with `presenter.metrics()`
   (`compose_ms_max`, `glass_upload_ms`), before and after A.
2. **The Tk tick's real period** (tick timestamps in `status.json`) and its per-tick pure-Python time,
   which is the GIL burst length. Check again with A2 and A3 applied.
3. **The GIL lateness in the running app**, after `DwmFlush` on the overlay thread during a slide,
   against A3.
4. **B3a's look in motion.** The B3b spike: shadow sprites through DWM thumbnails (cloaked-source alpha,
   re-registration cost) or DirectComposition.
5. **C1:** confirm 240 Hz content on the knob. The overlay thread stays awake at 240 Hz for 2.5 s after
   each touch. Measure its CPU cost.

## 7. Sources

**Scratch scripts** (`<scratch>`):

| Script | Output | Measures |
|---|---|---|
| `bench_carousel.py` | `bench_carousel*.json`, 4 runs; `show_runs.py` | the real presenter, inline |
| `profile_carousel.py` | `profile_carousel_*.json` | the compose breakdown |
| `bench_variants.py` | `bench_variants.json` | the B changes |
| `bench_label.py`, `bench_toast.py` | `.json` | label render, toast frames |
| `bench_knob.py` | `bench_knob.json` | `KnobFace`, `alive`, the DIB row copy, `render_lcd` |
| `bench_blit.py`, `bench_glass_upload.py` | `.json` | ULW-equivalent copies, the frost upload |
| `bench_shadow_explorer.py` | `.json` | shadow internals, explorer, Up next, ambient |
| `gil_latency.py` | `gil_latency*.json` | GIL reacquire lateness |
| `timer_granularity.py` | `.json` | wait granularity |
| `dwm_timing.py` | `.json` | the DWM refresh period |
| `spike_intervals.py` | stdout | the on-screen spike logs |

**Spike (on-screen, 2026-09-24):**

- `<scratch>/carousel-spike/spike.py`: `Layer.present` timing, `:756-763`; frame loop, `:999-1032`;
  geometry, `:207-215`.
- `results_p4.json`, `p4_frames.json`, `p4b_frames.json`.

**Project docs:**

- `CAROUSEL.md`: §4 (pacing, `:134`), §5 (the chrome row's "0.64 ms compose + 0.41 ms ULW" is the
  spike's rectangle-only compose, `:159`; frame order, `:163`), §11 (upload cost never measured, `:327`).
- `FLOATING_KNOB.md`: §4 (slide, `:119-122`; "at most one submit per UI tick (25 ms)", `:144`).
- `design_handoff_nano_d_master/README.md` §7.1 and §1 (build targets, `:36-39`).
- `03-desktop.md` §2.3-2.6 and §10.

**Microsoft and Python documentation:**

- DwmFlush: https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmflush
- DwmGetCompositionTimingInfo: https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmgetcompositiontiminginfo
- UpdateLayeredWindow: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-updatelayeredwindow
- UpdateLayeredWindowIndirect and `prcDirty`:
  - https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-updatelayeredwindowindirect
  - https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-updatelayeredwindowinfo
- DwmUpdateThumbnailProperties: https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmupdatethumbnailproperties
- timeBeginPeriod (per-process behaviour since Windows 10 2004): https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod
- SetTimer (`USER_TIMER_MINIMUM`, resolution): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-settimer
- `sys.setswitchinterval`: https://docs.python.org/3/library/sys.html#sys.setswitchinterval
- DirectComposition:
  - https://learn.microsoft.com/en-us/windows/win32/directcomp/directcomposition-portal
  - `IDCompositionAnimation`: https://learn.microsoft.com/en-us/windows/win32/api/dcompanimation/nn-dcompanimation-idcompositionanimation
  - `DCompositionWaitForCompositorClock`: https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-dcompositionwaitforcompositorclock
