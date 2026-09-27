# refresh-00: Recommendation for running every animation at the display's refresh rate

This is an analysis only, dated 2026-09-25. Nothing was built, shown on screen, flashed, or sent over the network.

It pulls together three studies in this folder:
- **R1** = `refresh-01-current-pipelines.md`: the desktop pipelines as built.
- **R2** = `refresh-02-gpu-options.md`: the GPU composition options.
- **R3** = `refresh-03-knob.md`: the physical knob.

It adds one new headless check (§2.0, blurred layers). It also reconciles the three studies with the UI V2 plan in `00-summary.md` (**S00**).

The user's request, verbatim:

> "my screen is 240hz -- we should ensure all of the animations both on the knob on the screen and the fullscreen swipes through album artwork, tracks, app windows is at maximum refresh rate so it looks super smooth"

**Path prefixes.** All are relative to `<repo>\`.

| Prefix | Path |
|---|---|
| `ND/` | `app/` |
| `CC/` | `ND/control_center/` |
| `FW/` | `firmware/` |
| `HO/` | `ND/design-reference/design_handoff_nano_d_master/` |
| `BS` | `HO/prototypes/Browse and Snap.dc.html` |
| `SCR/` | `<scratchpad>\refresh-study\` |

---

## 1. In plain words

**Your screen.** It is a Samsung Odyssey G93SC OLED: 5120 × 1440 at 240 Hz and 100 % scaling. Windows draws a new frame every **4.17 ms**, and the rate was measured at exactly 240.0 Hz (R2 §2.1). OLED pixels switch almost instantly, so no smear hides a skipped frame: one missed frame shows as a small stutter. That is why the targets in §4 limit the *worst* frames, not only the average.

### Everything on the PC can run at 240 Hz

| What you see | Today | After this plan |
|---|---|---|
| **Music explorer** swipes through album art | Not built yet. Drawn the way the v6 window picker draws, it would reach about **40 fps** (R1 §4) | **240 fps** |
| **Up next** track list | Not built yet. About **80 fps** the v6 way (R1 §4) | **240 fps** |
| **Window picker** (app windows) | About **120 fps**, with a visible hitch on each step of a fast spin (R1 §1) | A steady **120 fps** with no hitches after a small fix (step 1). **240 fps** once its decorations move to the GPU (step 3) |
| **On-screen knob**, slide in and out | **240 fps** already, apart from a rare 16 ms stall (R1 §3.6) | **240 fps**, stall fixed |
| **On-screen knob**, ring lights | About **30 updates/s**, tied to the app's 25 ms UI tick (R1 §1) | **240 fps** (step 0) |
| **On-screen knob**, its small LCD | Changes are instant | Still instant. Its slide and fade transitions can run at 240 later (step 4, optional) |
| **Toasts** | **240 fps** already (R1 §3.1) | **240 fps** |

### The knob itself cannot, and why

| What you see | Today | Physical ceiling | Target |
|---|---|---|---|
| **Knob screen** (LCD) | About **30 fps**. It freezes for **46–154 ms** whenever a new cover arrives | About **87 fps** is the most the wire can carry. The panel itself probably refreshes at 60 Hz or less | **60 fps**, no freezes |
| **Knob light ring** (LEDs) | **49 fps**, because of a timing bug. It was designed for 60 | The wire could carry about 400 fps. But the LEDs' own flicker rate (≥ 400 Hz) and the CPU they share with the screen make anything above about 130 fps harmful | A steady **60 fps**. Optionally, 120 Hz smoothing of dim levels |

**Why the knob is limited.** The knob's screen is fed through one serial data line at 80 MHz, the chip's maximum.
- One full 240 × 240 picture takes **11.5 ms** to send. Even if drawing took no time at all, that allows only about 87 pictures a second.
- The panel then shows its memory at its own internal rate. The datasheet only mentions "20~40 Hz", in its tearing-signal table. Updates faster than the panel's own rate can never be seen (R3 §0, §2.1).

**Why the PC's surfaces were slow.** The problem is different: the graphics card sits idle.
- Today's overlays are drawn pixel by pixel in Python, on one CPU core. At 5120 × 1440 there isn't time in 4.17 ms to draw a full-screen scene: the explorer needs 23–26 ms per frame and the window picker 5–10 ms (R1 §1, §4).
- Python threads also take turns (the GIL). Any loop that must wake every 4.17 ms can be made late by other work in the app. In one measurement, a single busy thread turned a 240 Hz loop into a 44 Hz one (R2 §2.2).

### What we'll do

1. **Let Windows' compositor do the moving.** For the explorer and Up next, Python draws each picture once: covers, labels, shadows and the blurred background. It hands them to **DirectComposition**, which is part of Windows, so nothing new is installed. Python then describes each swipe as a curve, and Windows animates it on the GPU at 240 Hz by itself. Python does nothing per frame, so nothing else in the app can make these animations stutter (R2 §1, §4a).
2. **Keep per-frame Python small and on time.** Where Python must still step every frame (the picker's live window thumbnails, the on-screen knob's lights), keep that work under about 2 ms. Also fix the scheduling: the timer resolution, the GIL switch interval, and a pacing bug.
3. **On the knob:**
   - fix the LED timing to a true 60 fps;
   - redraw only what moves on the LCD, send it with DMA, and refresh at 60 fps;
   - take cover decoding off the screen's drawing path.
4. **Measure everything.** Add frame counters to every animated surface. Accept each step only when the numbers in §4 are met on your screen and on the knob. Each on-screen check and each flash needs your go-ahead first.

**One change to the plan already under way.** `FW/ALIVE.md:423` caps the on-screen knob at "up to 60 fps". It should become "every display refresh (240 Hz here)" before desktop v7 is built (§5, K2).

---

## 2. Recommended architecture per surface

| Surface | Mechanism | Python per frame | Python per event | Target on this screen |
|---|---|---|---|---|
| Music explorer | New DirectComposition "stage" (§2.0). DWM runs the animations | **0** | ≈ 1 ms per detent (0.94 ms measured, R2 §2.3) | 240 fps |
| Up next | The same stage, another scene | **0** | ≈ 1 ms per detent | 240 fps |
| Window picker | v6 host and DWM thumbnails kept. Chrome: CPU fixes first, then DirectComposition, stepped per frame in lockstep with the thumbnails | 0.5–1 ms (after step 3) | + 1.1 ms re-registration per detent | 120 fps steady (step 1), then 240 fps (step 3) |
| Floating knob | v5 layered window kept. The LED engine moves onto the overlay thread and draws once per vblank | ≈ 1.5 ms at 100 % scale | — | 240 fps (slide and ring) |
| Toasts | v6 toast kept (layered window, spring re-scale). It may move onto the stage later | 0.67 ms (R1 §3.1) | — | 240 fps |
| Knob LCD | LVGL: bounded layers, DMA with two buffers, a 16 ms period, JPEG decode off the render path | — | — | 60 fps (≥ 45 on the heaviest frames) |
| Knob LEDs | HMI task on a deadline cadence | — | — | 60 fps. Optional 120 Hz output-only dither |

### 2.0 The shared "stage" engine (new; used by the explorer, Up next and later the picker chrome)

**Thread and window.** It follows the pattern of `CC/overlay.py` and `CC/carousel.py` (R2 §4a):
- A native thread, `NanoD-stage`, fed by the existing newest-wins mailbox and `PostMessageW`. It never touches Tk.
- A full-monitor host window with these styles: `WS_POPUP`; `WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP`; `MA_NOACTIVATE`; shown with `SW_SHOWNA`. This is the floating knob's recipe, and that window has never taken focus since v5 (`CC/overlay.py:205-219`).
- `WDA_EXCLUDEFROMCAPTURE` during the backdrop capture, the v6 rule.

**Devices.**
- `D3D11CreateDevice` on the RTX 4090. It is the adapter that owns the display: the iGPU has no outputs (R2 §2.1).
- `DCompositionCreateDevice3` as `IDCompositionDesktopDevice`, then `CreateTargetForHwnd(hwnd, TRUE)`.
- Device creation costs 134 ms once, so do it off the Tk thread, at startup or on first use, and keep the device.
- It costs **+53.5 MB private** (R2 §2.3) and **+0 MB** of packaging: the DLLs are in System32.

**Content.** Every picture is prepared once with PIL, reusing the carousel's text engine, then uploaded with `BeginDraw` / `UpdateSubresource` / `EndDraw`. A 680 px cover takes **0.29 ms** (R2 §2.4). Nothing is ever re-drawn per frame.

**Motion.**
- DirectComposition animations are built from the CSS curves, fitted as 8 cubic segments. The worst error measured was **0.24 px** over a 640 px move (R2 §2.3). Springs (Play grow, the heart pop, the snap tray) are fitted the same way, with more segments.
- Each animation gets an absolute begin time.
- On each detent, the new curve starts from the exact current value, computed by a Python twin of the curve (`CubicBezier` / `Tween`, `CC/carousel.py:104-174`). Reversals therefore never jump.
- DWM evaluates the curves at every composed frame, whether or not Python is running. See [DirectComposition animation](https://learn.microsoft.com/en-us/windows/win32/directcomp/animation).

**Scene model.**
- The model is pure Python and platform-neutral: a list of visuals, each with a sprite, transform, opacity and clip.
- It is tested on a fake clock, like `CarouselMachine`.
- A small **PIL reference renderer** of the same visual list gives golden-image tests without a GPU.

**COM calls.**
- Short, non-blocking calls on the hot path go through `ctypes.PYFUNCTYPE` prototypes, built once. These keep the GIL: **0.03 ms** under contention, against **229 ms** with `WINFUNCTYPE` (R2 §2.3).
- Waits, `GetMessageW`, and anything that can send a message to another thread stay on `WinDLL`, which releases the GIL.

**Device loss.** After a driver update or a GPU reset (TDR), check `GetDeviceRemovedReason`, rebuild both devices, and re-upload the sprites (R2 §4a, "Risks").

**Blurred layers are tiny.** A heavily blurred picture has no fine detail, so it can be stored small and stretched by the GPU. New headless check: `SCR/lowres_blur_check.py` → `lowres_blur_check.json`. It compares a PIL blur at low resolution, upscaled bilinearly (standing in for the compositor's linear scale), against a full-resolution blur of a 5120 × 1440 source:

| Layer (k = 2) | σ | Surface | Bytes | Build in PIL | Error in 8-bit levels: mean / p99.9 / max |
|---|---|---|---|---|---|
| Ambient cover, `blur(90px) saturate(1.5)` | 180 px | **1/8: 640 × 180** | 460,800 | 4.5 ms | **0.18 / 2 / 3** |
| | | 1/16: 320 × 90 | 115,200 | 2.7 ms | 0.29 / 4 / 5 |
| | | 1/32: 160 × 45 | 28,800 | 2.3 ms | 0.48 / 6 / 7 |
| Backdrop, `blur(36px)` (synthetic desktop with text-like rows) | 72 px | 1/4: 1280 × 360 | 1,843,200 | 11.1 ms | 0.17 / 2 / 3 |
| | | **1/8: 640 × 180** | 460,800 | 4.5 ms | **0.22 / 3 / 6** |
| | | 1/16: 320 × 90 | 115,200 | 2.6 ms | 0.36 / 7 / 11 |

- For comparison, the full-resolution blur costs 144 ms per layer.
- The largest errors sit at the image edges, where the two blurs treat borders differently. The ambient layer extends 160 px past the screen anyway (`BS:105`).
- The v6 frost already uses reduce(8) + GaussianBlur + a bilinear upscale, validated on this screen (`ND/CAROUSEL.md:100`). What changes is that the **GPU** now does the upscale. The upload is a 0.46 MB surface (0.02 ms, R2 §2.4) instead of 29.5 MB (≈ 5.8 ms, R1 §3.5).
- **Use 1/8 for both layers.**

### 2.1 Music explorer

**Visual tree:**
1. Backdrop: the frost surface at 1/8, scaled ×8.
2. Tint: a solid visual at 0.5.
3. Two ambient visuals at 1/8, crossfaded by opacity over 600 ms.
4. Per card, a container with offset and scale, holding four children:
   - a shadow sprite: one shared surface each for the centre shadow (`0 40 80 .55`) and the side shadow (`0 16 36 .4`), crossfaded by distance;
   - the cover surface, 680 px. Playlists get a pre-composed 2 × 2 mosaic;
   - the dark overlay;
   - the 1 px inset.
5. Label, tabs and dots, then the button hints.

**What happens on each event:**

| Event | Stage work |
|---|---|
| Each detent | About 45 animations (9 cards × offset, scale, opacity and overlay, plus the label, dots and ambient crossfades) and one `Commit`. Measured: 0.94 ms median, 1.20 ms p95 for 48 animations (R2 §2.3) |
| Label change | The label is **prefetched ±3 on a worker** (render_label costs ≈ 6 ms at k = 2, R1 §3.2). The previous label stays up until the new one is ready (R1 B1) |
| Ambient change | Built from the cover at 640 × 180 on the worker, in about 2–5 ms. Newest wins: during a fast spin, intermediate covers are skipped |
| Tab underline, active dot | Animated as `scaleX` of a solid bar, not as a width change (§6) |
| Open stagger, source switch, Play grow, 14 px end bump | More segments on the same animations |

**Minification.** Side cards are scaled 0.60 and 0.42, so a 680 px cover is drawn at 408 and 286 px. The compositor's bilinear filter has no mipmaps, and minifying 2.4× can shimmer in motion on detailed covers.
- The spike (§5, step 2) must look for this.
- The fallback is a second 340 px surface per cover, crossfaded by scale. That is cheap on this GPU.
- The source artwork is 1200 px (S00 G5, `research-artwork-resolution.md`), so the 680 px surface is always a downscale.

**Input.** When Python holds the detent, DWM picks up the commit about one frame later (median 4.15 ms, R2 §2.3). The motion is therefore on screen within 1–2 frames.

### 2.2 Up next

- **Same stage window, a different scene.**
- **Rows:** one sprite per row, holding the title, artist, tag and heart. Each is rendered once at k = 2 at the focused size. Row covers are 112 px surfaces.
- **Motion:** offset Y, scale and opacity per row, as in the table in `HO/specs/01-FEATURES-explorers-snap-seek.md:201-208`.
- **Focused row:** the 14 % fill, the inset and the `0 20 50` shadow form one sprite, crossfaded in by opacity (§6: the prototype animates `box-shadow` instead, `BS:174`).
- **Big cover:** the 760 px cover crossfade is two visuals crossfading their opacity over 420 ms.
- **Springs and stagger:** the heart pop spring (`cubic-bezier(.34,1.6,.64,1)`, 380 ms) and the shuffle fade-and-stagger are fitted segments.
- **Cost:** the same as the explorer, about 1 ms per detent. Row sprites are prefetched ±4 on the worker.

### 2.3 Window picker

The picker keeps the **v6 host and its DWM thumbnails**. They are the only documented way to show live windows, and DirectComposition cannot animate a thumbnail (R2 §4a). So the thumbnails must be stepped from Python every frame (`DwmUpdateThumbnailProperties`: 7 calls, 0.36 ms, R1 §2.2). The CPU-drawn chrome of shadows, shades, badges, outline, label and dots is the bottleneck: 5–10 ms per frame, of which the shadows are 69–73 % (R1 §3.2).

**Step 1: CPU fixes (steady 120 fps, no hitches).** Apply A1–A5 (§3) and R1 B1 + B2:
- B1: labels are prefetched on a worker, with more than 6 kept in the cache;
- B2: the label and dots get their own layered window.

Add B3a (NEAREST shadow bands while animating) and B4 (badge scales quantised to 1/64) only if step 3 is more than a release away, because step 3 replaces them. Measured together: compose + present **5.1 / 5.6 ms** (median / p95) in fast turns, against 6.7 / 10 ms today. The per-detent hitches and the 16 ms stalls disappear (R1 §5.2).

**Step 3: chrome on the stage engine (240 fps).**
- **A new chrome window.** It keeps the same z-order and styles, but uses `WS_EX_NOREDIRECTIONBITMAP` and a DirectComposition target instead of `UpdateLayeredWindow`. The shades, badges, outline, shadows, label and dots become visuals.
- **The frost** becomes a 640 × 180 surface (§2.0).
- **Lockstep stepping.** The chrome is **stepped per frame from the same values as the thumbnail rects**, not run by DWM, so a shade and its thumbnail can never drift apart.
- **Per-frame cost.** About 0.36 ms of thumbnails, plus about 100 visual property calls (0.07 ms per 65 calls, R2 §2.3), plus the commit: **≈ 0.5–0.6 ms**. Detent frames add the 1.1 ms re-registration (z-order is registration order, R1 B6).
- **The catch.** Today's compose clears or attenuates the shadows of farther cards inside nearer cards' rects, because those cards' thumbnails sit in the window *below* the chrome (`_under_keep` / `_under`, `CC/carousel_render.py:1513-1558`).
  - The first fix to try is to give each shadow up to three visuals clipped to the rectangles outside the nearer cards, with a fourth, partial-opacity piece during fades. All the clips are computed per frame.
  - A cheaper variant must be tried in the spike: a DirectComposition target on the host with `topmost = FALSE`, so the shadows would sit under the thumbnails. The order between DirectComposition content and thumbnails is undocumented (R2 §4a).
  - Parity with `compose_chrome` is proven through the PIL reference renderer and the existing preview goldens (`ND/CAROUSEL.md:274`).
- **Why not WebView2 or Qt.** Never move the picker to either: its focus contract depends on an activatable in-process host (`ND/CAROUSEL.md` §1), and they offer no thumbnail visuals (R2 §6.4).

### 2.4 Floating knob

**Step 0: the existing layered window (R1 C1 + C2).**
- **The LED engine moves.** `AliveLights` (0.06–0.17 ms per render) and the ring mapping move onto `NanoD-overlay`. The Tk thread only posts inputs (frames, `detent`, `limit`, `press`, clock, progress) and LCD scenes.
- **The render loop.** While the knob is visible and the engine is animating (breathing is continuous), the loop stays in `pace()` and composes once per vblank.
- **C2: compose straight into the DIB.** This removes the inset box, the BGRa conversion and the 434 per-row `memmove` calls.
- **Result:** about **1.5 ms per frame at 100 %**, with about 2.5 ms of slack (R1 §5.3). The slide is already a per-vblank, content-free `UpdateLayeredWindow` (R1 §2.3).
- **When it runs.** The knob wakes at 240 Hz only while visible: `HIDE_SECONDS = 2.5` after the last touch (`CC/overlay.py:85`), plus the slides.
- **Glow.** The glow is specified as `blur (5 + 13·mx)·k` (`FW/ALIVE.md:419`). It must come from the **cached glow masks** (64 levels, `CC/knob_face.py:400-414`) and never be blurred per frame.
- **LCD mirror.** It stays a change-driven picture: `render_lcd`, 2.29 ms per change on Tk (R1 §3.3).
- **Why this rather than moving the knob to DirectComposition first** (R2 §6.3 suggested that): the ring changes every frame, so Python must step it either way. C1 + C2 is smaller, and it lands in the same place desktop v7 is already wiring `AliveLights` (`FW/ALIVE.md:409-425`).

**Step 4 (optional): the knob on the stage engine.**
- The slide becomes a DWM offset and opacity animation.
- The ring becomes a surface updated per vblank: 0.8 MB, about 0.1–0.3 ms to upload.
- The LCD mirror becomes layers (art, content, volume, footer), animated with the firmware's own tween table at 240 Hz.
- It is worth doing for the LCD transitions, or if the supervised check shows the layered-window path missing frames under load.

### 2.5 Toasts

- **Today.** The v6 toast re-scales its pill per frame in 0.67 ms (p95 0.81), so it already runs at 240 (R1 §3.1). Its glass is a snapshot taken at show time, at σ = 24·k/4 (`ND/CAROUSEL.md:100`, `:243`).
- **Plan.** Route every toast through this one presenter, with the §3 pacing fixes: "Queued next", "Side by side", Switch and Cancel. Keep the design rule: never over an open overlay, and none for Play/Pause (HO README §7.1).
- **Later (optional).** Once the stage exists, the spring can become a DWM-run animation, costing 0 ms per frame.

### 2.6 Knob LCD (firmware; the ESP32-S3 stays at 60 fps)

Do these in R3's order. **Each gets its own A/B build and tour** (R3 §8.2).

| # | Change | Where | Effect |
|---|---|---|---|
| **R2** | Bound the invalidated areas: size the track, volume, footer, list, tracks and windows layers to their content boxes instead of `makeFullLayer` | `FW/src/cc_display.cpp:1074-1076`, `:1139-1223` | The volume reveal repaints 27 % of the screen instead of 100 %, and the footer fade 7 % |
| **R2b** (design decision) | On a screen change, fade the **content** only, not art and content together | Today `FW/src/cc_display.cpp:12`, `:1268` fades both | Removes the costliest frames, 220 ms of full-screen blends over the cover. The primary prototype already does this: `flipLcd` fades only the content layer (`BS:209`, `:649`), and the art is a separate element (`BS:207`) |
| **R3** | DMA with two partial buffers of 11,520 B | A copy of `lv_tft_espi.cpp` in `src/` (R3 §4.1) | Rendering overlaps the wire. The frame costs about max(render, 12.4 ms), and the task sleeps during DMA. Costs +11.5 KB of internal RAM |
| **R4** | Refresh and animation period 33 → 16 ms, **with or after R2 + R3, never alone** | `FW/include/lv_conf.h:64` | 30 → 60 fps. Alone, it pins core 0 at 99 % and still gets only 38–58 fps |
| **R5** | JPEG decode off the render path: decode into the back buffer, then swap pointers | `FW/src/lcd_thread.cpp:260-267`, `FW/src/cc_display.cpp:1016-1025` | Removes the 46–154 ms freezes |
| R6 / R7 | `-O2` for LVGL's blend code; HMI task at priority 2 | — | Optional. Measure first |

- **Tearing.** No TE (tearing) signal is wired (`FW/include/nanofoc_d.h:47-63`). Keep moves small (≤ 20 px) and never refresh faster than 16 ms.
- **Question for Binaris.** Is the panel's TE pad routed to a free GPIO? If so, refreshes can be locked to the panel (R3 §5).

### 2.7 Knob LEDs (firmware)

- **R1:** move to a deadline cadence, `nextShowDue += 16/17/17` with a loop delay of `clamp(nextShowDue − now, 1, 10)`. This replaces the drifting `previous = now` gate (`FW/src/hmi_thread.cpp:299-322`) and is already specified in `FW/ALIVE.md:371-373`. It takes the LEDs from 49 to 60 fps.
- **R7:** raise the HMI priority only if LED gaps show up under LCD load.
- **Optional 120 Hz pass.** Re-run only the output stage (EOTF, drive, power limit, dithered quantisation) at 120 Hz, about 20 µs per pass. Adopt it only if the hands-on A/B shows twinkle at the resting levels. With it, turn FastLED's own dither off: it switches itself on at ≥ 100 fps (`FastLED.cpp:67`). **Never go above ~133 Hz** (the WS2811 PWM beat, R3 §6).

### 2.8 Considered and not recommended

**README §7.1's PySide6 / WebView2 fallback.** The README frames it around the backdrop blur (`HO/README.md:38`). At 240 Hz, what decides the matter is who composes each frame, not the blur. DirectComposition gives compositor-run animation without a second toolkit or process, and the blur becomes a static texture (§2.0).
- **WebView2** costs about 200 MB for its process group, has known focus-stealing issues, and cannot let `backdrop-filter` see the desktop.
- **PySide6 / Qt Quick** needs a main thread that Tk already owns, and adds about 80–120 MB to the package.

See R2 §4c–d.

**Other desktop approaches:**

| Rejected | Why |
|---|---|
| S00 G1's proposal: explorer and Up next sprites as **DWM thumbnails of hidden source windows** | Python would step every frame (GIL-fragile). About 21 re-registrations per detent (≈ 3.4 ms). The alpha of cloaked layered sources is unvalidated (R1 §5.2) |
| A Python-driven flip-model swap chain | Python every 4.17 ms: 44–46 Hz with one busy thread (R2 §4b) |
| pyglet / moderngl | No DirectComposition path |

**Firmware:**

| Rejected | Why (R3 §4) |
|---|---|
| SPI above 80 MHz | The S3's maximum, and the pins go through the GPIO matrix |
| Draw buffers larger than 2 × 1/10 of the screen | Needs 34.6 KB more internal RAM against about 57 KB of headroom, for no gain past 25 % of the screen |
| Buffers in PSRAM | Slower |
| LVGL layer snapshots | They need the 64 KB LVGL heap |
| Refresh periods under 16 ms | The panel probably can't show them |

---

## 3. Frame-pacing rules for all desktop animation code

These apply to `CC/carousel.py`, `CC/overlay.py`, the new stage modules, and any future animated surface. Each rule cites the current code it fixes.

1. **Motion is a function of time, never of frame count.**
   - Every animated value is `f(t)` from a curve with an absolute start time. Nothing "advances by one step per frame".
   - A reversal or retarget starts from the curve's value at the new start time, so there is never a jump.
   - Today's state machines already follow this rule (R1 §2.5). Keep it.
2. **Sample at the predicted display time.** Use the vblank the frame will appear at: the next `qpcVBlank + n × qpcRefreshPeriod`, from `DwmGetCompositionTimingInfo`, where n is 1 within budget. Do not use "now" at compose start: that causes 1–3 vblanks of jitter (R1 A5; fix at `CC/carousel.py:930` and `CC/overlay.py:745`).
3. **Pace on the compositor, never on a timer.**
   - Per-frame loops wait on `DCompositionWaitForCompositorClock` (Windows 11 build 22000+, resolved with `GetProcAddress`), with `DwmFlush` as the fallback.
   - Never use `root.after(16)`, `SetTimer`, `time.sleep(1/60)` or a `QTimer` in a frame path. Never hard-code 16.7, 8.3 or 4.17 ms.
   - Read the period from `DwmGetCompositionTimingInfo` at start and on `WM_DISPLAYCHANGE` or a monitor change, and cope with a new period (for example, if the user sets 120 Hz). References: [compositor clock](https://learn.microsoft.com/en-us/windows/win32/directcomp/compositor-clock/compositor-clock), [DwmGetCompositionTimingInfo](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmgetcompositiontiminginfo).
4. **Judge pacing by the interval between wake-ups.**
   - "At least half a period since the last return" means the wait is pacing.
   - Today's rule, "two flushes under 0.5 ms → wait 8 ms", stalls **16 ms** at the default timer resolution (`CC/carousel.py:476-520`, `CC/overlay.py:93-94`, `:1205-1218`; R1 A1, §3.6).
   - A fallback wait lasts exactly one period, on a high-resolution waitable timer.
5. **Prefer compositor-run animation.** Anything that is a translate, scale, opacity or clip of fixed pictures is handed to DirectComposition as an animation, and Python runs on input only. Per-frame Python loops are allowed only where the content itself changes every frame: thumbnail rects and ring lights.
6. **Per-frame Python budget at 240 Hz: ≤ 2.5 ms median and ≤ 3.0 ms p95** on the frame thread, leaving at least 1 ms for GIL and scheduler jitter.
   - Heavier work stays off the frame path: text and labels, JPEG decode, blur, capture, colour extraction.
   - It goes to a worker or to idle time, and the previous picture stays up until the new one is ready (R1 B1).
7. **No per-frame allocation of large buffers.**
   - No per-frame full-surface upload larger than the knob window (0.8 MB).
   - Compose straight into the mapped DIB or surface (R1 C2).
   - Use dirty rects where a layered window must be re-uploaded (R1 B5).
8. **Run only while something moves.** When idle, block without a timeout (`GetMessageW`, or `MsgWaitForMultipleObjectsEx(INFINITE)`). No polling timers in animation threads.
9. **Scheduling hygiene** (one-time, at startup):
   - `timeBeginPeriod(1)` at startup and `timeEndPeriod(1)` at exit. Per-process on Windows 11: [timeBeginPeriod](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod).
   - **`sys.setswitchinterval(0.0005)`** process-wide. 0.5 ms and 0.2 ms both measured well (R2 §2.2, R1 §3.6); 1 ms without 1 ms timers did not help. Re-verify on each Python upgrade.
   - Hot, non-blocking Win32 and COM calls on the frame path go through prebuilt `PYFUNCTYPE` prototypes (R2 §7.1).
   - `THREAD_PRIORITY_ABOVE_NORMAL` on frame threads is optional (R1 A4).
   - None of these calls exists in the project today (grep: `setswitchinterval`, `timeBeginPeriod` and `SetThreadPriority` have no matches in `CC/`).
10. **Keep Tk out of frame paths.**
    - No animation is stepped by a Tk `after()` tick (`CC/ui.py:99`, `:1839`).
    - Tk posts events and immutable scenes, newest wins.
    - Knob input for the overlays should reach the animation threads without waiting up to 25 ms for the poll (R2 §7.2; step 2).
11. **One clock.** Use QPC everywhere. `time.perf_counter` is QPC-based, and so is `time.monotonic` since Python 3.13 on Windows ([time.monotonic](https://docs.python.org/3/library/time.html#time.monotonic)). DirectComposition begin times are QPC as well. Convert explicitly, never mix.
12. **Pictures at physical resolution.** Sprites are prepared at k = 2 here and never upscaled on the fly. Blurred layers are the exception: they are low resolution by design (§2.0).
13. **Every animated surface counts its frames (`FrameStats`), and every state machine has fake-clock tests** at 60, 120, 144, 240 and 360 Hz.

### FrameStats: frame counters, one per animated surface

**Per frame** (Python-stepped loops):
- `t_wake`, the QPC time after the pace wait;
- `t_target`, the display time the frame was sampled for;
- `work_ms` and `present_ms`;
- the DWM refresh count (`cRefresh`) at present time.

**Per episode** (motion start → settle):
- frames and vblanks elapsed;
- fps, as frames divided by duration;
- frame interval at p50, p95, p99 and max;
- `missed`: intervals > 1.5 periods;
- `double_missed`: intervals > 2.5 periods;
- `work_ms` at p95 and max;
- the thread's CPU time from `GetThreadTimes`, as a % of one core.

**DWM-run episodes** (the stage) have no per-frame hook. At episode end, read the DWM counter deltas (`cRefresh`, `cFrame`) and the DirectComposition frame statistics (`DCompositionGetStatistics`, as R2 §2.1 already does) into the same fields.

**Export and logging:**
- Keep the last episode, the worst episode since start, and the totals. Export them through `presenter.metrics()`, `overlay.metrics()` (`CC/overlay.py:1645`) and the stage's `metrics()` into `status.json`, next to today's `compose_ms_max` and `glass_upload_ms` (`CC/carousel.py:611-620`).
- Log one rate-limited line when an episode misses §4.

**Optional HUD.** `NANOD_FPS_HUD=1` shows a small text sprite in a corner of the surface, updated 4 times a second, never per frame. It is off by default.

**Firmware counterparts:** `lcdFps`, `lcdFpsAnimMin`, `lcdRefrUsMax`, `lcdPxPerRefr`, `lcdLateRefrs`, `lcdMaxGapMs`, `core0IdlePct`, `ledFps`, `ledShowGapMsMax` (R3 §8.1).

---

## 4. Acceptance criteria

This monitor's period is **P = 4.1667 ms**. The thresholds are:

| Term | Condition |
|---|---|
| On time | interval ≤ 1.1 P = **4.6 ms** |
| Missed | interval > 1.5 P |
| One missed vblank | 8.33 ms, so "≤ 8.4 ms" |
| Two missed | 12.5 ms |

CPU is given as a % of **one core**. Task Manager shows the 16-thread Ryzen 7 9800X3D (R1 §0) as a total, so one core = 6.25 % of that total.

### 4.1 Test tours (supervised on this screen, with your go-ahead; driven by a scripted detent replay so no hands are needed)

| Tour | Script |
|---|---|
| **E** (explorer, the "20-card swipe") | Open on Recently Added with ≥ 25 albums. **20 detents at 10/s**, then a 1 s pause, then **20 detents at 20/s**. Switch to Favourite playlists and back, 10 detents, then Play (grow and close). Run it 3 times |
| **U** (Up next) | A playlist of ≥ 25 tracks, so row covers are drawn and the big cover crossfades on each detent. The same detent pattern, then Shuffle on and off, Like, Play |
| **W** (picker) | ≥ 8 windows. 20 detents back and forth at 10/s and 20 at 20/s. Snap left, snap right (auto-close). Reopen, then Cancel. Both backgrounds (Frosted and No background) |
| **K** (floating knob) | 10 summon and slide-out cycles; a 5 s spin at 20 detents/s (spin trail); a volume sweep into amber and red (embers); Play/Pause fill and drain; 5 s of visible breathing |
| **T** (toasts) | 5 toasts from different sources |
| **Stress** | Each tour once more, with a test hook that runs a pure-Python burst of **10 ms every 25 ms** on another thread. That is the Tk tick's worst case in R1 §3.6 |

The physical-knob tour is separate: R3 §8.2, with the companion quit, the cc5.3 flash discipline, and beep cues only for the turning test.

### 4.2 Desktop criteria

| Surface / tour | Frames/s during motion | Frame interval | Frame-thread work | CPU while moving | Stress run |
|---|---|---|---|---|---|
| **Explorer, E** | **≥ 235** | **p95 ≤ 4.6 ms**, p99 ≤ 8.4, max ≤ 8.4 | **0 per frame** (≤ 1 stage wake per detent, plus housekeeping). Per detent ≤ 1.5 ms p95 | Companion ≤ **30 % of one core** above idle at 20 detents/s (≈ 1.9 % of the machine), ≤ 15 % at 10/s. Expected: commits ≈ 2 %, label prefetch ≈ 12 %, ambient builds ≤ 10 % | **Same thresholds.** DWM runs the motion, so Python load must not matter |
| **Up next, U** | ≥ 235 | p95 ≤ 4.6, p99 ≤ 8.4, max ≤ 8.4 | as the explorer | as the explorer | same thresholds |
| **Picker, W, step 1** (interim) | ≥ 118 (steady 120) | p95 ≤ 8.4, max ≤ 12.5, **no stall ≥ 16 ms** | compose + present ≤ 5.6 ms p95 (R1 §5.2) | carousel thread ≤ 70 % of one core | ≥ 110 |
| **Picker, W, step 3** | **≥ 235** | p95 ≤ 4.6, p99 ≤ 8.4, max ≤ 8.4 | ≤ 1.5 ms p95 on normal frames, ≤ 3.0 ms on detent frames | carousel thread ≤ 35 % of one core; companion ≤ 50 % (≈ 3.1 % of the machine) | ≥ 228, max ≤ 12.5 |
| **Knob slide, K** | ≥ 235 | p95 ≤ 4.6, max ≤ 8.4, no 16 ms stall | ≤ 0.2 ms | — | ≥ 228 |
| **Knob ring, K** (visible and animating) | **≥ 235 new ring frames/s** | p95 ≤ 4.6, p99 ≤ 8.4 | ≤ 2.5 ms p95 at 100 % (measured 1.74–2.32 before C2, R1 §3.3) | overlay thread ≤ 50 % of one core while visible, **0 while hidden** | ≥ 228, max ≤ 12.5 |
| **Toasts, T** | ≥ 235 | p95 ≤ 4.6 | ≤ 1.0 ms p95 | — | ≥ 228 |

**Latency, all surfaces.** From the detent reaching the animation thread to the first frame showing the new target: **≤ 2 vblanks (8.4 ms) p95**. After the step 2 input fast path: from the serial read to that frame, ≤ 3 vblanks + 2 ms p95.

**Independence checks:**
- The ring's frame rate is unchanged when a test build slows the Tk tick (`POLL_MS`) to 100 ms. That proves the tick is off the ring path.
- The stage's episode fps is unchanged in the stress run.

**Guards** (recorded; investigate if exceeded):

| Guard | Limit |
|---|---|
| dwm.exe CPU during tour E | ≤ +15 % of one core over its idle baseline |
| GPU 3D utilisation of dwm.exe | ≤ 20 % |
| Companion private bytes with the stage device warm | ≤ +80 MB (device measured at +53.5 MB). This updates the K4 memory budget, which is 80 MB *while open* today (`ND/CAROUSEL.md:167`) |
| dwm.exe commit | Before an open and after its hide, as `ND/CAROUSEL.md:279` does |

**Cross-check (optional).** PresentMon (needs your OK to download), or a 240 fps phone slow-motion video of one swipe.

### 4.3 Knob criteria (from R3 §8.3; firmware diag, hardware window with your go-ahead)

| Field | Required |
|---|---|
| `lcdFpsAnimMin` | ≥ 55 on opaque-cover transitions; ≥ 45 on blended ones |
| `lcdLateRefrs` | 0 outside cover arrivals, and 0 with R5 |
| `lcdFullRefrs` | Only slides and art fades (R2), and none on a same-cover screen change once R2b is in |
| `ledFps` | ≥ 58 at idle; ≥ 55 during transitions and cover transfers. This tightens `FW/ALIVE.md:468`'s 55 / 45 once R1 (+ R7) is in |
| `ledShowGapMsMax` / `ledTxTimeouts` | ≤ 20 ms / 0 |
| `heapMinFree` | ≥ 40 KB (R3 adds 11.5 KB of buffers) |
| `core0IdlePct` (guard) | Record it. Investigate below 10 % during any transition |
| `focAgeMs`, detent feel | Unchanged during the R3 / R4 tour |
| Check suites | No regressions in the lease, ack and stress checks |
| Hands-on | You judge the slide, the volume reveal and the resting LED twinkle, with an `ledDither` A/B |

### 4.4 Headless gates (every build; nothing on screen)

1. **Frame-rate independence.** Every state machine (carousel, slide, toast, stage scenes, `AliveLights`) is sampled on fake clocks at 60, 120, 144, 240 and 360 Hz. It must give the same value at the same `t`, and a skip of 1–3 vblanks must resume on the curve, with no catch-up burst.
2. **No timers in frame paths.** A static scan of the animation modules for `after(`, `SetTimer(` and `sleep(` outside an idle-path allowlist.
3. **Curve fit.** Every design curve, springs included, is fitted as cubic segments with **≤ 0.5 px** error over its largest travel. 0.24 px was measured (R2 §2.3).
4. **Golden images.** The stage's PIL reference renderer against the prototype layouts, and (step 3) against `compose_chrome`.
5. **Budget benches** (report only, since the PC is shared). Knob frame ≤ 2.5 ms p95; picker per-frame Python ≤ 1.5 ms p95; stage ≤ 1.5 ms per detent. The scripts are in `SCR/` (`bench_knob.py`, `bench_variants.py`, `gpu_bench.py`).

---

## 5. Effort, risk and order of work

Effort is in engineering days, excluding supervised checks:

| Size | Days |
|---|---|
| **S** | ≤ 1 |
| **M** | 2–5 |
| **L** | 1–3 weeks, comparable to the v6 carousel build |

The release in progress is cc5.4 / desktop v7 ("Warm · alive", `FW/ALIVE.md`). UI V2 is queued after it (S00 §4).

| Step | Items | Effort | Risk | Gate | Ships with / owner |
|---|---|---|---|---|---|
| **K2** (docs, now) | Amend `FW/ALIVE.md:423` from "up to 60 fps" to "once per display refresh while visible and animating (FrameStats; §3)". Decide **U10** (S00:233): 240 Hz everywhere on the PC as the goal, with the gate split described below this table. Update the K4 memory budget (§4.2 guards) | S | none | Review | Contracts (WP0) |
| **0** | **Desktop:** A1 (pacing by interval), A2 (`timeBeginPeriod`), A3 (switch interval), A5 (predicted display time), FrameStats in both loops; floating knob C1 + C2. **Firmware:** R1 (already in ALIVE §10.1) plus the R3 §8.1 counters | M (≈ 3–5 days) | Low. C1 moves the LED engine's thread ownership; it is covered by the fake-clock tests | Supervised check 1: slide and ring ≥ 235; picker metrics before and after A; `ledFps` ≥ 58 | v7 / cc5.4. Desktop: WP10 (`overlay.py`, `knob_face.py`); the engine side is WP2 |
| **1** | Picker B1 + B2 (+ B3a + B4). Firmware R2, R3, R4, R5, one at a time with A/B tours; R2b if the design agrees | M (picker ≈ 2 days). Firmware ≈ 1–2 weeks with tours | Low for the picker. Medium for the firmware: DMA bring-up, SPI ownership (`dmaWait` before `setRotation`), the JPEG buffer hand-off | Tour W at step-1 thresholds; §4.3 LCD fields | WP7 (picker); WP1 (R2, R2b in `cc_display.cpp`); WP4 (R3–R5: it already owns `lcd_thread.cpp`, and `lv_conf.h` plus the copied driver go with it) |
| **2** | **Supervised DirectComposition spike** (your go-ahead; this replaces S00 G1's thumbnail-sprite spike): one full-screen no-activate window, an explorer-like tree, DWM-run turns, capture exclusion, minification shimmer, frame stats, focus unchanged. Then the stage engine (WP7a becomes this), explorer + Up next (WP8), and the input fast path (serial → animation threads) | Spike M. Stage + scenes **L** | Medium: hand-written COM vtables (slots already verified S_OK, R2 §2.3), COM lifetime, device loss, minification quality | Tours E and U at §4.2 thresholds, normal and stress; S00 gates S1 and S2 | UI V2 (WP7a, WP8) |
| **3** | Picker chrome on the stage, with a spike first (shadow clipping, or DirectComposition under the thumbnails) | M–L (≈ 1–1.5 weeks) | Medium: occlusion parity, and shade and thumbnail landing in the same DWM frame | Tour W at step-3 thresholds | UI V2 (WP7b) or the next release |
| **4** (optional) | Floating knob on the stage: DWM-run slide, LCD mirror transitions at 240; firmware R6 / R7; the 120 Hz LED dither pass after the A/B | M each | Low to medium | §4.2 / §4.3 | Later |

**Why this order:**
- Step 0 is cheap and touches code v7 is changing anyway. It gives the most visible early gain: the on-screen ring goes from about 30 to 240 fps.
- Step 1 removes the only hitches you can see today.
- Step 2 must settle before the music scenes are written (S00 §4.3: "they cannot start until the spike settles the rendering approach").
- Step 3 reuses step 2's engine.

**Where this changes S00's recommendation** on U10 (S00:233 recommended "(b) as the release gate"):
- With DirectComposition, the explorer and Up next become the *easiest* surfaces to hold at 240, because they need no per-frame Python.
- The picker is the one that needs extra work.
- Recommended gate: explorer, Up next, knob and toasts at 240; the picker at a steady 120 until step 3 lands, then 240.

---

## 6. Implications for the Claude Design handoff

The prototypes run in a browser that composites on the GPU. The implementation reproduces **CSS `transform` and `opacity` exactly**, and re-expresses everything else. These are also the only two properties browsers animate on the compositor ([web.dev](https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count)).

### 6.1 What runs at 240 Hz at no per-frame cost

- **Transforms and opacity of pictures prepared in advance:** translate, scale, opacity, rectangular clips (animated too).
- **Crossfades between two prepared pictures.**
- **Timing:** any `cubic-bezier`, springs with overshoot (fixed per event), delays, staggers, and reversals mid-flight.
- **Live window thumbnails:** position, size and opacity only. A DWM thumbnail is an axis-aligned rectangle ([DWM_THUMBNAIL_PROPERTIES](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ns-dwmapi-dwm_thumbnail_properties)).

### 6.2 Avoid on the desktop (each forces per-frame pixel work at 5120 × 1440)

| # | Avoid | Where the prototypes do it | Specify instead |
|---|---|---|---|
| 1 | **Animating a blur or filter value** (radius, saturate, brightness), or anything moving *behind* a blur while it animates | The blurs are static radii today (`BS:44`, `:104-105`, `:155-156`, `:199`). Keep them static | A fixed blur recipe per surface; fades by opacity |
| 2 | **Relying on a live blur.** The companion blurs a **snapshot** taken when the overlay opens, as v6 does. A video or a moving window behind it will not move in the blur. Toast glass is a snapshot too | CSS `backdrop-filter` is live in the prototypes | "Frosted snapshot of the desktop at open" |
| 3 | **Animating layout properties:** width, height, left, top, padding, font size | Tab underline `width` 320 ms (`BS:115`); dots `width` 320 ms (`BS:93`, `:141`); snap fly `left/top/width/height` (`BS:28`, `:1051`) | `scaleX` or translate of a fixed bar or picture. **Anything that changes width must stay a square-cornered solid bar** (as now), or rounded ends will stretch |
| 4 | **Animating shadow parameters** | Up next row `transition: box-shadow 300ms` (`BS:174`); the explorer card's shadow switches between centre and side values (`BS:929`); the fly shadow (`BS:99`) | Shadows as fixed sprites that move, scale and fade with their element. A shadow change is a crossfade between two fixed shadows |
| 5 | **Animating the colour or background of large areas** | Ambient `transition: background 600ms` under `filter: blur(90px)` (`BS:105`, `:156`); big cover `background 420ms` (`BS:158`); row background (`BS:174`) | A crossfade of two prepared images or fills. This is how it will be built, so say it in the spec |
| 6 | **Text that changes while moving**: counting numbers, marquees, re-wrapping titles. A label costs about 6 ms to render at k = 2 (R1 §3.2) | — (the label already swaps with a 180 ms opacity fade, `BS:134`, which is ideal) | Change text at rest points (when a detent lands) and fade it by opacity |
| 7 | **Generative or per-frame effects on big areas**: animated gradients, noise or grain, particles, shimmer sweeps, video backgrounds, parallax of the blurred backdrop | none today | Transforms of prepared pictures only |
| 8 | **Animating real app windows** with per-frame `SetWindowPos`: the other app repaints, so it can never be smooth | The desktop windows in the prototype animate `left/top/width/height` (`BS:28`) | Animate the thumbnail. Move the real window once, while it is covered (the snap flow already does this: 01 §7 step 2) |
| 9 | **Rounded corners, rotation, perspective or effects on live window thumbnails** | `perspective:1400px` is set on the picker group, but no rotation is used (`BS:65`). Corner radius is 0 (`ND/CAROUSEL.md:256`) | Keep live thumbnails flat, square, and opacity-only |
| 10 | **Scaling pictures below about 40 % of their prepared size while visible**: bilinear minification shimmers in motion | Today: explorer d = 2 at 0.42 and 55 % opacity; smaller scales only at 0 opacity; Up next rows 0.52 at 0 | Keep the current tables. Don't make far items smaller while they are still visible |
| 11 | **On-screen ring glow that changes shape continuously** | `FW/ALIVE.md:419`: glow blur `(5 + 13·mx)·k` | Accept 64 quantised glow sizes (the cached masks, `CC/knob_face.py:400-414`). Specify the on-screen ring look per level, since the alive → floating-knob optical mapping is not specified yet (R1 §3.3) |

### 6.3 Avoid on the knob LCD (60 fps is the target; 240 is impossible)

| # | Avoid | Evidence | Specify instead |
|---|---|---|---|
| 1 | **Full-screen opacity blends over the cover** | The firmware fades art and content on every screen change (`FW/src/cc_display.cpp:12`, `:1268`); the prototype fades only the content (`BS:209`, `:649`) | Confirm **content-only** fades (R2b) |
| 2 | **Two-cover crossfades** | About 40 fps at best (R3 §2.2) | An instant cover swap (as built) |
| 3 | **Scale transforms on LCD layers** | The prototype scales the volume reveal (0.98 / 0.93, `BS:1086-1087`) and the art in Windows mode (1.06, `BS:1089`). The firmware does translate + opacity only (`FW/src/cc_display.cpp:37-39`), because LVGL's software transforms need layer buffers the 64 KB heap can't hold | Make **translate + opacity** the official LCD vocabulary |
| 4 | **Large animated boxes** | A full-screen layer repaints 100 %; the volume reveal box repaints 27 %, the footer 7 % (R3 §2.2) | Animate the smallest box that holds the content |
| 5 | **Big moves** | No TE sync, so large moves and full-cover changes tear | Slides ≤ 20 px, as now |
| 6 | **Very short fades** | Under 50 ms is fewer than 3 frames at 60 fps, which reads as a pop | ≥ 120 ms, as the current designs already use |

- **Review the LCD at 60 fps.** A browser on this 240 Hz monitor shows the LCD prototype four times smoother than the knob can ever be. A 60 fps preview toggle in the prototype would set the right expectation.
- **LEDs.** Design for 60 fps. Recipes stay time-based, and nothing flashes faster than 3 Hz (`HO/README.md:176`). The 120 Hz dither pass is an implementation detail, not a design parameter.

### 6.4 Prefer: how to write motion in the handoff

- **Every motion as a tuple:** (element, property ∈ {translate, scale, opacity, clip}, from, to, duration in ms, delay, curve). Durations are in milliseconds, never frames.
- **Every look change** (focus fill, shadow, colour, ambient, big cover) as two states plus a crossfade duration.
- **Every blur** as a fixed recipe per surface: σ, saturate and tint. Say "snapshot at open".
- **Springs** as a `cubic-bezier` with overshoot (as now), or as stiffness and damping with a fixed duration.
- **Name the events that change assets.** For example: "the label changes when a detent lands"; "the ambient follows the focused cover, newest wins during a spin".

**The design already gets most of this right.** All card and row motion is transform + opacity (`BS:903`, `:923`, `:1035`). Blurs are static. Corners are square. Labels swap with a fade. Real windows move only under cover. The LED rules forbid flashes above 3 Hz.

---

## 7. Where the three studies disagree, and what this file decides

1. **Is the picker already at 240?**
   - R2 §1.5 and §2.5 say "median interval 4.2 ms". That figure is the v6 *spike*, with a rectangle-only compose (0.64 ms; R1 §7 on `ND/CAROUSEL.md:159`).
   - The shipped v6 presenter composes 5–10 ms at k = 2, which gives 120 fps (R1 §3.1).
   - **Decision:** use R1's figure. The picker needs step 3 to reach 240.
2. **Floating knob: DirectComposition first, or the layered window first?**
   - R2 §6.3 moves the knob to DirectComposition second.
   - R1 §5.3 keeps the layered window with C1 + C2.
   - **Decision:** C1 + C2 in step 0; DirectComposition in step 4, optional. The ring must be stepped from Python every frame either way.
3. **GIL switch interval.**
   - R1 measured 0.2 ms (0 % of frames more than 2 ms late).
   - R2 measured 0.5 ms (240 Hz wake-ups restored).
   - **Decision:** 0.5 ms, verified in supervised check 1, with 0.2 ms as the fallback. Also apply R2's `PYFUNCTYPE` fix: the two remedies are complementary.
4. **The Tk tick.**
   - R1 estimates about 30 Hz: `after(25)` at the default timer resolution, not measured with a window.
   - R2 says ≤ 40 Hz, the nominal rate.
   - **Same conclusion:** the tick must leave the ring path (C1).
5. **S00 G1's mechanism** (thumbnails of hidden sprite windows) **against R2's DirectComposition.**
   - **Decision:** DirectComposition (§2.8). G1's intent stands: a spike before WP8, with S1 recording the p95 frame interval.

---

## 8. Sources

**This folder:**
- `refresh-01-current-pipelines.md`
- `refresh-02-gpu-options.md`
- `refresh-03-knob.md`
- `00-summary.md`: G1 (`:92`), G11 (`:102`), U10 (`:233`), §4.2–4.4 (`:290-349`)

**New headless check.** `SCR/lowres_blur_check.py` → `SCR/lowres_blur_check.json`.
- It uses PIL only: no windows, no devices, no network.
- It was run with `ND/.venv/Scripts/python.exe -I`.
- Its sources are `HO/prototypes/assets/covers/moon-safari.png` and a synthetic desktop built from the prototype covers.

**Companion code** (verified for this file):
- `CC/ui.py:99`, `:1839`
- `CC/overlay.py:85-87`, `:93-94`, `:205-219`, `:745`, `:1205-1218`, `:1645`
- `CC/carousel.py:104-174`, `:214`, `:476-520`, `:611-620`, `:930`
- `CC/carousel_render.py:1513-1558`, `:1577-1664`
- `CC/knob_face.py:400-414`
- No match anywhere in `CC/` for `setswitchinterval`, `timeBeginPeriod` or `SetThreadPriority`.

**Companion docs:**
- `ND/CAROUSEL.md:100`, `:134`, `:159`, `:167`, `:243`, `:256`, `:274`, `:279`
- `ND/FLOATING_KNOB.md:119-122`, `:144`

**Firmware:**
- `FW/include/lv_conf.h:64`
- `FW/src/hmi_thread.cpp:299-322`
- `FW/src/lcd_thread.cpp:23-24`, `:384`, `:442`
- `FW/src/cc_display.cpp:12-14`, `:37-39`, `:1074-1076`, `:1139-1157`, `:1260-1274`
- `FW/platformio.ini:39-49`
- `FW/ALIVE.md:25`, `:367-386`, `:409-425`, `:468`

**Design:**
- `HO/README.md:36-38`, `:176`, `:178-210`
- `HO/specs/01-FEATURES-explorers-snap-seek.md:170-222`
- `BS:28`, `:44`, `:65`, `:93`, `:99`, `:104-105`, `:115`, `:134`, `:141`, `:155-158`, `:174`, `:199`, `:207-209`, `:649`, `:903`, `:923`, `:929`, `:1035`, `:1051`, `:1086-1089`

**Microsoft, Python and web references:**
- DirectComposition animation: https://learn.microsoft.com/en-us/windows/win32/directcomp/animation
- Compositor clock: https://learn.microsoft.com/en-us/windows/win32/directcomp/compositor-clock/compositor-clock
- `DCompositionWaitForCompositorClock`: https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-dcompositionwaitforcompositorclock
- `CreateTargetForHwnd`: https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-idcompositiondesktopdevice-createtargetforhwnd
- `IDCompositionAnimation::SetAbsoluteBeginTime`: https://learn.microsoft.com/en-us/windows/win32/api/dcompanimation/nf-dcompanimation-idcompositionanimation-setabsolutebegintime
- `DwmFlush`: https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmflush
- `DwmGetCompositionTimingInfo`: https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmgetcompositiontiminginfo
- `DWM_THUMBNAIL_PROPERTIES`: https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ns-dwmapi-dwm_thumbnail_properties
- `UpdateLayeredWindowIndirect`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-updatelayeredwindowindirect
- `timeBeginPeriod`: https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod
- `sys.setswitchinterval`: https://docs.python.org/3/library/sys.html#sys.setswitchinterval
- `time.monotonic` (QPC on Windows since 3.13): https://docs.python.org/3/library/time.html#time.monotonic
- Compositor-only CSS properties: https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count

**Hardware references** (via R3):
- GC9A01A datasheet V1.0: https://github.com/fbiego/dt78/blob/master/datasheets/GC9A01A.pdf
- ESP-IDF SPI master on the ESP32-S3: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/spi_master.html
- esp_lvgl_port performance: https://github.com/espressif/esp-bsp/blob/master/components/esp_lvgl_port/docs/performance.md
- WS2811 datasheet: https://cdn-shop.adafruit.com/datasheets/WS2811.pdf

---

## Adversarial review

Reviewer pass, 2026-09-25. Project files were read only; the only edit is this section. Three new headless scripts were run in `SCR/` with `ND/.venv/Scripts/python.exe -I` (Python 3.14.5, x64, GIL build; Pillow 12.3). They create no window, open no device or port and make no network call.

**Severity.**
- **High:** the 240 Hz goal fails or regresses in practice unless this is fixed.
- **Medium:** a likely visible defect, or a decision that rests on an unsupported number.
- **Low:** accuracy, wording or a secondary option.

### Verdict

The direction holds: DWM-run DirectComposition for the explorer and Up next, a smaller per-frame path for the floating knob, and 60 fps on the physical knob. But four things would make the 240 Hz goal fail in practice:
- The scheduling safety net for every Python-stepped surface does not work the way §3 rule 9 assumes (AR-1, AR-2).
- The only on-screen measurement contradicts the "240 already" rows (AR-3).
- The stage's window recipe has no input contract (AR-4).
- Several DirectComposition defaults, and input that still arrives on the Tk tick, would undo the smoothness at the first run (AR-8, AR-9).

**Suggested handling:**
- Fix AR-1, AR-2 and AR-9 before step 0 ships.
- Add AR-4, AR-8 and AR-11 to AR-14 to the step 2 spike checklist.
- Fold AR-5 and AR-6 into the WP8 and v7 plans.

### Spot checks of key claims

| Claim in this file | Result | Evidence |
|---|---|---|
| `FW/ALIVE.md:423` caps the on-screen knob at "up to 60 fps" | Confirmed | `FW/ALIVE.md:423` |
| LEDs run at about 49 fps because a 16 ms gate is sampled by a 10 ms loop | Confirmed | `FW/src/hmi_thread.cpp:301` (`>= 16`), `:308`, `:322` (`vTaskDelay(10)`) |
| `LV_DEF_REFR_PERIOD` is 33 ms | Confirmed | `FW/include/lv_conf.h:64` |
| FastLED dither is off below 100 fps | Confirmed | `FastLED.cpp:67` (`if(m_nFPS < 100) { pCur->setDither(0); }`) |
| The pacer's "two fast flushes → 8 ms wait"; compose samples `now` at its start | Confirmed | `CC/carousel.py:512-517`, `:930`; `CC/overlay.py:93-94`, `:745`, `:1211-1218` |
| No `setswitchinterval`, `timeBeginPeriod` or `SetThreadPriority` in `CC/` | Confirmed by grep | There is no `SetProcessInformation` either (AR-2) |
| The monitor is a Samsung Odyssey G93SC | Confirmed | `WmiMonitorID` gives `Odyssey G93SC`. The string is not in `SCR/gpu_bench_results.json`, although R2 §2.1 cites that file |
| `timeBeginPeriod` has been per-process since Windows 10 2004 | Confirmed, but incomplete | The same page has a Windows 11 clause that this file omits (AR-2) |
| `time.monotonic` is QPC-based | Confirmed here | `time.get_clock_info('monotonic').implementation == 'QueryPerformanceCounter()'` on this venv |
| DirectComposition targets are allowed on layered windows (R2 §6.3) | Confirmed | [CreateTargetForHwnd remarks](https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-idcompositiondesktopdevice-createtargetforhwnd): "the window can be a layered window" |
| "DirectComposition begin times are QPC" (§3 rule 11) | **Not documented** | `SetAbsoluteBeginTime` gives no unit. Frame statistics report QPC with an explicit `timeFrequency` (AR-14) |
| The glow comes from "64 cached glow masks" (`CC/knob_face.py:400-414`) | **Wrong** | There are 4 glow shapes; 64 is the number of alpha steps (AR-6) |
| The stage host is "the floating knob's recipe" (`CC/overlay.py:205-219`) | **Partly wrong** | The knob window is also `WS_EX_LAYERED \| WS_EX_TRANSPARENT` (`CC/overlay.py:206`), so it never receives input (AR-4) |
| The §2.0 low-resolution blur table | Confirmed | `SCR/lowres_blur_check.json` matches. The method compares PIL with PIL and assumes a *linear* GPU upscale (AR-8) |
| `BS:105`, `:115`, `:174`; `HO/README.md:38` | Confirmed | Read directly |

### Issue summary

| # | Sev. | Issue | Affects |
|---|---|---|---|
| AR-1 | High | A switch interval under 1 ms turns into a busy spin on Windows and does nothing against GIL-holding C calls | §3 rule 9, step 0 |
| AR-2 | High | Windows 11 may ignore `timeBeginPeriod` for this tray process, and its never-focused overlays get Medium or Low QoS | §3 rule 9, step 0 |
| AR-3 | High | The "240 already" rows and the ≥ 235 thresholds for Python-paced layered windows have no on-screen support; the one on-screen run missed 7.5–12 % of frames | §1, §4.2, step 0 gate |
| AR-4 | High | The stage recipe drops the knob's click-through styles. A full-monitor window would swallow every click while keys go to the hidden foreground app | §2.0, §2.3 step 3, spike |
| AR-5 | Medium | Some PIL operations hold the GIL for their whole run, so "move heavy work to a worker" (rule 6) is not enough | §3 rule 6 |
| AR-6 | Medium | Cover sprite builds (17.7 ms each) are missing from the explorer's CPU budget and from its open latency | §2.1, §4.2 tour E |
| AR-7 | Medium | "64 glow levels" is wrong: there are 4 shapes. ALIVE's continuous glow has no budget at 240 Hz | §2.4, §6.2 #11, step 0 |
| AR-8 | Medium | DirectComposition defaults to nearest-neighbour sampling and aliased edges. The plan assumes bilinear and never sets it | §2.0, §2.1, spike |
| AR-9 | Medium | Step 0 still feeds the ring from the 25 ms Tk tick, so the turning cursor steps at about 30 Hz inside a 240 fps ring | §2.4, §4.2 latency |
| AR-10 | Medium | Step 1's "steady 120 fps" has no mechanism; frames near budget alternate between 240 and 120 | §2.3 step 1, §4.2 |
| AR-11 | Medium | VRR, G-SYNC windowed mode and Dynamic Refresh Rate are not considered; the compositor clock is never boosted | §3 rule 3, §4 |
| AR-12 | Medium | Step 3's "a shade and its thumbnail can never drift apart" is unsupported | §2.3 step 3 |
| AR-13 | Medium | The acceptance measurements cannot prove 240 Hz as written | §3 FrameStats, §4.2 |
| AR-14 | Medium | The retarget time is not specified, and the begin-time unit is inferred | §2.0 Motion, rule 11 |
| AR-15 | Medium | The firmware moves to a 16 ms period before the panel's scan rate is known | §2.6 R4, §5 step 1 |
| AR-16 | Low | `PYFUNCTYPE` on COM calls that may block would freeze the whole app | §2.0 COM calls |
| AR-17 | Low | Up next text sprites are minified bilinearly at rest | §2.2 |
| AR-18 | Low | The free-threaded Python 3.14 build was not evaluated | §2.8 |
| AR-19 | Low | Device lifetime and first-use latency | §2.0 Devices |
| AR-20 | Low | Several numbers are presented as measured but are estimates or proxies | §1, §2.6, §2.8 |
| AR-21 | Low | Side effects of a full-monitor window, and multi-monitor pacing | §2.0, spike |
| AR-22 | Low | The ring criterion "≥ 235 new ring frames/s" rewards redundant frames and CPU use | §4.2 knob ring |

### AR-1 (High). A switch interval under 1 ms busy-spins on Windows and does not help against C calls

**Evidence**
- **How CPython waits for the GIL.** CPython 3.14 converts the GIL wait to whole milliseconds: `SleepConditionVariableSRW(cv, cs, (DWORD)(us/1000), 0)` in [`Python/condvar.h`](https://raw.githubusercontent.com/python/cpython/3.14/Python/condvar.h). This is the native condition-variable branch, the default (`_PY_EMULATED_WIN_CV 0`, [`pycore_condvar.h`](https://raw.githubusercontent.com/python/cpython/3.14/Include/internal/pycore_condvar.h)). `take_gil` loops on that wait ([`ceval_gil.c`](https://raw.githubusercontent.com/python/cpython/3.14/Python/ceval_gil.c)). So any interval below 1 ms becomes a **0 ms wait**, and a thread that is waiting for the GIL polls it in a loop.
- **New measurement:** `SCR/gil_spin_cost.py` → `gil_spin_cost.json`. One thread holds the GIL inside PIL `alpha_composite` (about 16 ms); a 4 ms-sleep thread then waits for the GIL.

  | Switch interval | Waiter's CPU (% of one core) | Waiter's wakes per second |
  |---|---|---|
  | 5 ms | 0.0 | 61–67 |
  | 1 ms | 0.0 | 61–67 |
  | **0.5 ms** | **74.4** | 61–67 |
  | **0.2 ms** | **70.3** | 61–67 |

  So the sub-millisecond setting buys no wake-ups here and costs most of a core. Each thread that waits for the GIL spins the same way: Tk, the serial reader, tray, the workers, the overlay and the carousel.
- **This explains the earlier results.** 0.5 ms and 0.2 ms "measured well" (R2 §2.2, R1 §3.6) because they poll, and their tests only used **pure-Python** busy threads. 1 ms "did not help" without `timeBeginPeriod` because a 1 ms wait rounds up to the 15.6 ms default tick.

**Fix**
- Use `sys.setswitchinterval(0.001)` **together with** `timeBeginPeriod(1)`. R1 §3.6 measured that pair at a maximum of 2.7 ms lateness, with 1.1 % of frames more than 2 ms late.
- Make sure the process actually gets 1 ms timers (AR-2).
- Never set the interval below 1 ms.
- Keep GIL-holding C calls away from every thread while a frame loop runs (AR-5).
- Change §3 rule 9, §5 step 0 (A3) and §7 item 3 to match. Re-run `SCR/gil_spin_cost.py` after every Python upgrade.

### AR-2 (High). Windows 11 may ignore this process's timer resolution; its overlays are never "in focus"

**Evidence**
- **Timer resolution.** The [timeBeginPeriod](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod) page says: "Starting with Windows 11, if a window-owning process becomes fully occluded, minimized, or otherwise invisible or inaudible to the end user, Windows does not guarantee a higher resolution than the default system resolution."
- **The companion is such a process.** It owns only hidden windows most of the time: "The Tk root stays withdrawn" (`ND/standalone.py:4`, `:1751`), there is a pystray tray window, and the overlays are hidden.
- **QoS.** When the overlays are shown they are `WS_EX_NOACTIVATE`, so they are never in focus. The [Quality of Service](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service) page classifies such processes as **Medium** when visible and **Low** when not.
- **The earlier timer measurements do not transfer.** R1's `timer_granularity.py` and `gil_latency.py --period1` ran in a console process that owns no window.

**Fix**
- At startup, opt out of both throttles with `SetProcessInformation(ProcessPowerThrottling)`: `ControlMask = PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION | PROCESS_POWER_THROTTLING_EXECUTION_SPEED`, `StateMask = 0`. This is the documented "always honor timer resolution requests" setting plus HighQoS ([SetProcessInformation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation)).
- Alternatively, set HighQoS per frame thread only, with `SetThreadInformation(ThreadPowerThrottling)`.
- Add a supervised check-1 item: time `MsgWaitForMultipleObjectsEx(8 ms)` inside the running frozen app with the overlay hidden and shown. Expect about 8 ms, not about 16 ms.

### AR-3 (High). The "240 already" rows have no on-screen support

**Evidence**
- **The only on-screen data** for a Python-paced `UpdateLayeredWindow` + `DwmFlush` loop is the v6 spike. It used 1.44 ms of work per frame, less than the knob's planned 1.5 ms. It delivered **221.6 fps with 7.5 % of frames missed** (p4), and **210 fps with 12 % missed, p95 8.7 ms** (p4b) (R1 §3.6).
- **What this file says instead.** §1 says the knob slide and the toasts are "240 fps already", and §4.2 requires ≥ 235 fps and p95 ≤ 4.6 ms. Those numbers come from headless compose timings (R1 §3.1, §3.3).
- **The misses are unexplained.** The spike's misses were attributed to its screenshot thread, a hypothesis that was never tested.
- **No v6 frame metrics exist from the installed app.** `%LOCALAPPDATA%\NanoDControlCenter\logs\status.json` has an `overlay` block (`frames_presented: 0`) and no carousel block. `app.log` records only the focus timings (`Picker open focus granted after 2.0–5.1 ms`).

**Fix**
- Label these rows "expected".
- Make supervised check 1 a go/no-go gate *before* the step 0 thresholds are fixed. Run it with AR-1 and AR-2 applied, the real Tk tick, and the serial reader live.
- If the knob cannot hold ≥ 235 fps, bring step 4 (the DWM-run slide) forward, and give Python-paced surfaces the 120 lock from AR-10.

### AR-4 (High). The stage host has no input contract

**Evidence**
- **The knob's recipe includes click-through.** `CC/overlay.py:206` is `WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT`. The knob "never took focus" partly because it never receives mouse input at all.
- **§2.0 drops both click-through styles.** Its stage host would be a non-layered, full-monitor, hit-testable window.
- **Mouse.** Every click lands on it, with no activation, and nothing is specified for it.
- **Keyboard.** The spec says the explorer "never takes focus" (`HO/specs/01-FEATURES-explorers-snap-seek.md:171`), so Esc and any typing go to the app hidden under the frost.
- **How v6 solved this.** The picker was made activatable for exactly this reason (`ND/CAROUSEL.md:34-35`, `:158`).
- **Step 3 has the same trap.** Its new chrome window is described as "same styles, but `WS_EX_NOREDIRECTIONBITMAP`". If it loses `WS_EX_LAYERED | WS_EX_TRANSPARENT`, it eats the centre-card click that the host must receive (`ND/CAROUSEL.md:158`).

**Fix.** Decide the contract in the spike.
- **Option (a), click-through.** Use `WS_EX_LAYERED | WS_EX_TRANSPARENT` with a DirectComposition target, which the docs allow, and verify that it renders. Clicks would then reach apps the user cannot see.
- **Option (b), keep the current recipe and handle input.** Map a click to Back, map `WM_MOUSEWHEEL` to a turn, and document that keys stay with the foreground app.
- **Spike items to add:**
  - the foreground window is unchanged after a click, a wheel turn and key presses;
  - the step 3 chrome window stays click-through.

### AR-5 (Medium). Some PIL operations hold the GIL for their whole run (rule 6)

**Evidence.** New measurement: `SCR/gil_pil_hold.py` → `gil_pil_hold.json`.
- **Setup.** A 240 Hz frame thread waits on a high-resolution waitable timer while a worker repeats one operation. Rule 9's settings are applied: 0.5 ms switch interval and `timeBeginPeriod(1)`.
- **Results:**

  | Worker operation | Time per call | Frame thread late: max | Frames late |
  |---|---|---|---|
  | `alpha_composite`, 2560 × 1440 | 15.8 ms | **16.5 ms** (p50 5.2) | **66 %** more than 2 ms late |
  | `alpha_composite`, a 680 px sprite | 2.1 ms | 3.8 ms | 20 % more than 1 ms late |
  | `render_label` at k = 2 | 6.7 ms | 2.8 ms | — |
  | JPEG decode, LANCZOS resize, `GaussianBlur`, `reduce`, `tobytes`, masked `paste` | — | ≤ 3.3 ms | ≥ 99.5 % on time (these release the GIL) |

- **Where `alpha_composite` is used:** the knob face, every frame (`CC/knob_face.py:451`, `:454`); `render_label` (`CC/carousel_render.py:1253-1377`); `CC/lcd_preview.py:892`.
- A switch interval cannot preempt a C call.

**Fix**
- Add to rule 6: code that may run while a Python-stepped surface animates must use GIL-releasing operations.
- A masked `paste` was measured GIL-releasing. C2's compose through masks also removes the knob's own `alpha_composite`.
- Keep large `alpha_composite` calls out of the process while any Python frame loop is active.
- Add `SCR/gil_pil_hold.py` to the §4.4 budget benches.
- Rule 6's 1 ms jitter allowance is too small while `render_label` runs on a worker.

### AR-6 (Medium). Cover sprites are missing from the explorer's CPU budget and open latency

**Evidence**
- **Cost per cover** (`SCR/gil_pil_hold.json`, this PC): decoding a 1200 px JPEG takes 3.6 ms, and a LANCZOS resize to 680 px takes 14.1 ms, so **17.7 ms per cover**. §2.0's "0.29 ms" per cover is the upload only (R2 §2.4), about 60 times less.
- **CPU during a spin.** At 20 detents/s a new card enters every 50 ms, which adds about **35 % of one core**. §4.2 tour E then totals about 60 % (commits 2 %, labels 20 × 6.7 ms ≈ 13 %, ambient ≤ 10 %), twice its 30 % target.
- **Open latency.** 7 cards × 17.7 ms, plus the 41 ms capture (`ND/CAROUSEL.md:300`), frost and label, is about **175 ms** before the first frame on one worker. Add 134 ms if the device is created on first use. §4 has no open-latency criterion.
- **What the user would see.** The motion itself stays smooth, because DWM keeps animating. Late covers show as pop-in or placeholder cards during fast spins.

**Fix**
- Build the 680 px sprites (and §2.1's 340 px minification level) once per album, when artwork is fetched.
- Keep them in a disk cache, since decoding a 680 px image is cheap.
- Use `reduce()` or `reducing_gap` before LANCZOS.
- Spread builds over two or more workers; these operations release the GIL.
- Keep the library's GPU surfaces resident while the device is warm (1.85 MB of VRAM each).
- Add a criterion: knob press → first open frame ≤ 100 ms p95 with a warm device and cached sprites.

### AR-7 (Medium). "64 glow levels" is wrong; ALIVE's continuous glow has no budget at 240 Hz

**Evidence**
- **What the code has.** `CC/knob_face.py:182` defines `GLOW_BLUR = {1: 5, 2: 8, 3: 11, 4: 14}`: four glow **shapes**. `GLOW_STEPS = 64` at `:188` is alpha quantisation only. `_level_index` picks shape 1–4 (`:217-219`), and the mask LRU holds 512 entries (`:191`).
- **What ALIVE asks for.** `FW/ALIVE.md:419` specifies a blur of `(5 + 13·mx)·k`: 5–18 design px, continuous. That is wider than the largest cached shape.
- **What R1 measured.** R1's 1.43–1.92 ms knob frame used an assumed optical mapping with these four shapes (R1 §3.3).
- **What more shapes cost** (new measurement, `SCR/glow_sizes_cost.py` → `glow_sizes_cost.json`, spanning 5–18 px at scale 1.2587):

  | Glow shapes | Face build per DPI | Glow masks |
  |---|---|---|
  | 4 (today) | 63 ms | 0.36 MB |
  | 16 | 75 ms | 1.8 MB |
  | 32 | 134 ms | 3.6 MB |
  | 64 | 253 ms | 7.3 MB |

- **What goes wrong at 240 Hz.** With four shapes, breathing makes the glow size jump in visible steps. With 64 shapes and 64 alpha steps across 60 segments there are 245,760 cache keys, against a 512-entry LRU.

**Fix**
- Correct §2.4 and §6.2 #11.
- In v7, choose the glow model: for example 16–32 shapes, built off-thread on a DPI change, with the alpha steps pre-built or coarsened so the cache fits.
- Re-run `bench_knob.py` with the real ALIVE mapping at 240 Hz before fixing the 2.5 ms budget.

### AR-8 (Medium). DirectComposition defaults to nearest-neighbour sampling and aliased edges

**Evidence**
- **Sampling.** "If all visuals in a visual tree specify this mode, the default for all visuals is nearest neighbor sampling" ([DCOMPOSITION_BITMAP_INTERPOLATION_MODE](https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ne-dcomptypes-dcomposition_bitmap_interpolation_mode)).
- **Edges.** The default border mode is "aliased rendering" ([DCOMPOSITION_BORDER_MODE](https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ne-dcomptypes-dcomposition_border_mode)).
- **The bench never checked either.** `SCR/gpu_bench.py` never calls `SetBitmapInterpolationMode` or `SetBorderMode`, and never binds content to a target. Those vtable slots are not among R2 §2.3's verified slots.
- **What the defaults would do.** Left unset, the 1/8 blurred layers scaled ×8 (§2.0) become 8 px blocks, and scaled covers shimmer, with crawling edges, at 240 Hz.

**Fix**
- Set LINEAR sampling and SOFT borders on the root visual.
- Add both slots to the vtable tests.
- Make the PIL reference renderer model the same filters.
- Re-judge §2.1's minification with LINEAR. There are still no mipmaps.

### AR-9 (Medium). Step 0 still feeds the ring from the Tk tick

**Evidence**
- **Where the lights are rendered.** `preview_lights.render(frame, …, int(time.monotonic() * 1000))` runs inside the Tk tick (`CC/ui.py:1195-1196`). The tick is `POLL_MS = 25` (`CC/ui.py:99`), rescheduled after the tick finishes (`:1839`). Inputs are stamped with the tick's time, not the serial read time.
- **Step 0 keeps that path.** C1 has "the Tk thread only posts inputs" (§2.4); the input fast path waits until step 2.
- **What the user would see.** The cursor's rise has τ = 10 ms (R3 §5), shorter than one tick. So each batch of detents, about 31 ms apart, shows as a rise and then a hold: a 30 Hz staircase inside a 240 fps ring.
- **The latency criterion hides it.** §4.2 measures latency "from the detent reaching the animation thread", which leaves out the tick.

**Fix**
- Move the input fast path into step 0: the serial reader posts to the overlay mailbox, and each event carries its QPC timestamp.
- The engine applies each event at that timestamp.
- Measure latency from the serial read.

### AR-10 (Medium). Step 1's "steady 120 fps" has no mechanism

**Evidence**
- **Frame times after the fixes.** After A + B1–B4, slow turns take 4.4 ms (compose + present), "120 with some 240" (R1 §5.2). Fast turns take 5.1 ms median and 5.6 ms p95.
- **Pacing.** `DwmFlush` pacing presents each frame at the next vblank. Frames near the 4.17 ms budget therefore alternate between one and two vblanks, and the motion judders between 240 and 120 cadence.
- **The criterion.** §4.2's "≥ 118 (steady 120)" has nothing that produces it.

**Fix**
- Add an explicit rate lock with hysteresis:
  - Present every second vblank when the work's p95 over about 0.5 s exceeds 0.8 P. Sample the curves 2 P ahead.
  - Unlock when p95 falls below 0.6 P.
- Count cadence switches in FrameStats.
- Apply the same lock as the fallback for the floating knob (AR-3).

### AR-11 (Medium). VRR, G-SYNC and Dynamic Refresh Rate are not considered

**Evidence**
- **The panel supports VRR.** The Odyssey G93SC is a VRR panel: AMD FreeSync Premium Pro and 0.03 ms response ([Samsung](https://www.samsung.com/ca/monitors/gaming/odyssey-oled-g9-g93sc-49-inch-240hz-curved-dual-qhd-ls49cg932snxza/)).
- **Dynamic Refresh Rate.** The [compositor clock](https://learn.microsoft.com/en-us/windows/win32/directcomp/compositor-clock/compositor-clock) page says that with Dynamic Refresh Rate on there is "an unboosted mode, which will typically be 60Hz". Apps raise the rate with `DCompositionBoostCompositorClock`, and "boosting calls are completely compatible, even if the system isn't in Dynamic Refresh Rate mode".
- **This file never boosts.** R2 §2.1's 240.0 Hz reading shows that Dynamic Refresh Rate is off *today*.
- **G-SYNC is unknown.** Whether NVIDIA G-SYNC windowed mode is enabled is not known. If it is, the refresh can follow a foreground windowed app, and OLED gamma flicker under VRR can read as a flash when overlays open.

**Fix**
- Call `DCompositionBoostCompositorClock(TRUE)` from the start to the end of every animation episode. It is harmless when unneeded.
- In supervised check 1, record `rateRefresh` and FrameStats with a 60 fps windowed video in the foreground, with G-SYNC windowed mode both on and off.
- Record the NVIDIA and Windows display settings in the acceptance record.

### AR-12 (Medium). Step 3's lockstep claim is unsupported

**Evidence**
- **§2.3 claims too much.** It says the chrome, stepped from the same values as the thumbnails, means "a shade and its thumbnail can never drift apart".
- **They take different paths.** `DwmUpdateThumbnailProperties` and a DirectComposition `Commit` reach DWM separately.
- **Commit timing.** R2 measured a commit being picked up one full compositor frame later (4.145 ms median, R2 §2.3).
- **What v6 validated.** Its alignment result (21 of 22 frames aligned, `ND/CAROUSEL.md:163`) covered thumbnails together with an `UpdateLayeredWindow` chrome, not a DirectComposition one.
- **This file already knows.** §5 lists "landing in the same DWM frame" as a risk.

**Fix**
- Reword §2.3.
- Make frame alignment a pass/fail item in the step 3 spike.
- If DirectComposition lands a frame late, either lead the thumbnail rects by one period or keep the shadows in `UpdateLayeredWindow`.

### AR-13 (Medium). The acceptance measurements cannot prove 240 Hz as written

**Evidence**
- **DWM counters.** R2 §2.1 set DirectComposition frame-id gaps aside as ambiguous. Yet FrameStats for DWM-run episodes relies on `cRefresh` and `cFrame` deltas, and `cFrame` counts compositions of the whole desktop, not of this app.
- **Phone video.** A 240 fps phone video (§4.2 cross-check) samples at the display rate, so it cannot tell a dropped frame from exposure phase drift.
- **In-app timing.** For `UpdateLayeredWindow` loops, FrameStats times Python's wake-ups, not what reaches the screen.

**Fix**
- For the stage, use `DCompositionGetTargetStatistics` for every frame id, counting frames whose `presentTime` is non-zero for this app's target (the compositor-clock page's sample).
- Use PresentMon (download only with the user's OK) for dwm.exe's display cadence.
- Use a camera burst of 960 fps or more for layered windows.
- Define "missed" on displayed frames.

### AR-14 (Medium). The retarget time is not specified

**Evidence**
- **What the docs say.** Per [SetAbsoluteBeginTime](https://learn.microsoft.com/en-us/windows/win32/api/dcompanimation/nf-dcompanimation-idcompositionanimation-setabsolutebegintime), sampling starts at the first frame that includes the commit. An earlier begin time drops the start of the curve; a later one delays it.
- **What §2.0 leaves open.** It says the new curve starts "from the exact current value" but not *at what time*.
- **The resulting jump.** A commit takes effect about one frame later (R2 §2.3). If the begin time is the detent's time, the new curve starts from a stale value: a one-frame step of a few px at a turn's peak speed.
- **Rule 11 is inferred, not documented.** The docs give no unit for the begin time. [DCOMPOSITION_FRAME_STATISTICS](https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ns-dcomptypes-dcomposition_frame_statistics) reports `currentTime` as QPC, with an explicit `timeFrequency`.

**Fix**
- Set t1 to `nextEstimatedFrameTime` from `IDCompositionDevice::GetFrameStatistics`, plus P if the build will miss it.
- Start the new curve from the old curve's value at t1, converting times with `timeFrequency`.
- Add a fake-clock continuity test at t1.
- Optional: match the old curve's velocity in the first Hermite segment. That departs from CSS transition semantics, so it needs design sign-off.

### AR-15 (Medium). The firmware moves to a 16 ms period before the panel's rate is known

**Evidence**
- **The panel's rate is unknown.** The datasheet's only figure is "20~40 Hz", in the tearing-signal table (R3 §1).
- **The measurement comes last.** Filming the panel rate is R3 §8.2 step 3, after the A/B builds.
- **What happens if the scan is slower.** If the panel scans at about 40–50 Hz, a 16 ms refresh beats against it: uneven updates and rolling tears, with no visible gain.
- **R4's figures are modelled.** "Pins core 0 at 99 %, 38–58 fps" (§2.6) comes from `knob_model.py` (R3 §2.2: "estimates, to be replaced").

**Fix**
- Film the panel rate on the counters-only baseline build.
- Choose the R4 period from the measured scan period, or from TE if it is routed.
- Label the model's figures as estimates.

### AR-16 (Low). `PYFUNCTYPE` on COM calls that may block

**Evidence**
- §2.0 keeps only waits, `GetMessageW` and cross-thread sends on `WinDLL`.
- `Commit`, `BeginDraw` / `EndDraw`, `UpdateSubresource` and device creation may wait on DWM or the GPU: when the device is busy, during a TDR, or during a session lock.
- If one of them waits while holding the GIL, Tk, the serial reader and the tray all stop. Under AR-1's setting they would also spin.

**Fix**
- Use `PYFUNCTYPE` only for pure setters: the offset and opacity setters, `AddCubic`, `SetAbsoluteBeginTime`.
- Keep `Commit` and GPU-bound calls GIL-releasing. They run once per detent, so this costs nothing measurable.
- Log any `Commit` that takes more than 2 ms.

### AR-17 (Low). Up next text is minified bilinearly at rest

**Evidence**
- **How rows are drawn.** Row sprites are rendered once at the focused size (§2.2), but rest at scales 0.78, 0.66 and 0.58 (`HO/specs/01-FEATURES-explorers-snap-seek.md:205-207`).
- **The result.** Bilinear minification without mipmaps makes that text soft at rest.
- **Compare v6.** It re-renders at-rest frames with LANCZOS (R1 §3.1).

**Fix**
- Prefetch a row sprite for each table scale. That is 4 renders of about 6.7 ms each (measured), on a worker.
- Swap to the exact-scale sprite at settle, or crossfade by scale.
- Add this to the spike's visual checks.

### AR-18 (Low). The free-threaded Python build was not evaluated

**Evidence**
- This file names the GIL as the blocker (§1).
- Python 3.14 officially supports the free-threaded build: PEP 779; "ctypes now supports free-threading builds"; a 5–10 % single-thread penalty ([What's New 3.14](https://docs.python.org/3/whatsnew/3.14.html)).
- It would remove the GIL convoy (R2 §2.3), the spin (AR-1) and the C-call stalls (AR-5) from the picker and knob frame loops.

**Fix.** Run a half-day headless check of `python3.14t` with Pillow, pystray, tkinter and PyInstaller. It is not a blocker, but it could replace the `PYFUNCTYPE` tables and switch-interval tuning.

### AR-19 (Low). Device lifetime and first-use latency

**Evidence**
- Creating the device "at startup or on first use" (§2.0) keeps +53.5 MB private all day in a tray app that starts at sign-in. That figure was measured on the default adapter (`SCR/mem_bench_results.json`: `after_d3d11_hw_default_adapter`).
- Creating it on first use adds 134 ms to the first open.

**Fix**
- Create the device on the first knob touch: a touch always precedes an overlay.
- Release it after about 10 minutes idle.
- Treat a driver update's device removal as routine.

### AR-20 (Low). Several numbers are presented as measured but are estimates or proxies

| Number | What it really is | Source |
|---|---|---|
| The picker's "about 120 fps with a visible hitch" | Headless compose on a fake clock; never observed on screen | R1 §3.1 |
| The knob ring's "about 30 updates/s" | Estimate | R1 §3.6: "Confirm it … on the supervised run" |
| The 16 ms stall | Modelled | R1 §3.6: "a modelled risk, not a measured one" |
| WebView2 "about 200 MB" | Measured on SearchHost's WebView2 group, not on a minimal host | R2 §2.5 |
| PySide6 "+80–120 MB" | Estimate | R2 §4d |
| Springs "fitted the same way" | Only one curve's fit was measured | R2 §2.3 |

None of these changes a decision. Tag each figure as *measured* or *estimated* in §1 and §2.8.

### AR-21 (Low). Side effects of a full-monitor window, and multi-monitor pacing

**Evidence**
- **The stage would be new.** It would be the first non-layered, full-monitor topmost window in the app.
- **Shell reactions are unchecked.** Nobody has checked how Focus Assist, the taskbar and `SHQueryUserNotificationState` react to it. The knob already reads that state: `CC/overlay.py:105`.
- **Z-order is unspecified** against other topmost windows and the toast.
- **Monitor choice is unspecified.** The picker uses the origin window's monitor (`ND/CAROUSEL.md:53`); the stage has no rule.
- **Multi-monitor pacing.** DXGI waits follow the primary monitor's cadence (compositor clock page). If a 60 Hz primary monitor is ever added, a `DwmFlush` fallback could pace the 240 Hz panel at 60.

**Fix**
- Add the notification state before and after, and the z-order, to the spike.
- Specify how the stage picks its monitor.
- Prefer the compositor clock over `DwmFlush` for pacing.

### AR-22 (Low). The ring criterion rewards redundant frames

**Evidence**
- §4.2 requires "≥ 235 new ring frames/s" while the knob is visible.
- At rest, breathing changes by less than one output level per frame, yet each frame costs about 1.5 ms: about 36 % of a core while visible.

**Fix**
- Skip frames whose quantised ring is unchanged.
- Measure "late frames among changed frames" instead.

### Sources for this review

**New headless scripts** (in `SCR/`):
- `gil_spin_cost.py` → `gil_spin_cost.json` (AR-1)
- `gil_pil_hold.py` → `gil_pil_hold.json` (AR-5, AR-6)
- `glow_sizes_cost.py` → `glow_sizes_cost.json` (AR-7)

**Code:**
- `CC/overlay.py:85`, `:93-94`, `:105`, `:206`, `:745`, `:1205-1218`
- `CC/carousel.py:512-517`, `:930`, `:2300`, `:2325-2345`
- `CC/knob_face.py:182`, `:188-191`, `:217-219`, `:357-361`, `:400-414`, `:428-456`
- `CC/carousel_render.py:1253-1377`
- `CC/lcd_preview.py:892`
- `CC/ui.py:99`, `:1195-1196`, `:1839`
- `ND/standalone.py:4`, `:1751`
- `FW/ALIVE.md:419`, `:423`
- `FW/include/lv_conf.h:64`
- `FW/src/hmi_thread.cpp:301`, `:308`, `:322`
- `FW/.pio/libdeps/nanofoc_d/FastLED/src/FastLED.cpp:67`

**Docs:**
- `ND/CAROUSEL.md:34-35`, `:53`, `:152`, `:158`, `:163`, `:300`
- `HO/specs/01-FEATURES-explorers-snap-seek.md:171`, `:205-207`

**Microsoft:**
- timeBeginPeriod: https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod
- SetProcessInformation: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation
- Quality of Service: https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service
- Compositor clock: https://learn.microsoft.com/en-us/windows/win32/directcomp/compositor-clock/compositor-clock
- SetAbsoluteBeginTime: https://learn.microsoft.com/en-us/windows/win32/api/dcompanimation/nf-dcompanimation-idcompositionanimation-setabsolutebegintime
- DCOMPOSITION_FRAME_STATISTICS: https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ns-dcomptypes-dcomposition_frame_statistics
- DCOMPOSITION_BITMAP_INTERPOLATION_MODE: https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ne-dcomptypes-dcomposition_bitmap_interpolation_mode
- DCOMPOSITION_BORDER_MODE: https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ne-dcomptypes-dcomposition_border_mode
- CreateTargetForHwnd: https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-idcompositiondesktopdevice-createtargetforhwnd

**CPython:**
- `Python/condvar.h`: https://raw.githubusercontent.com/python/cpython/3.14/Python/condvar.h
- `Include/internal/pycore_condvar.h`: https://raw.githubusercontent.com/python/cpython/3.14/Include/internal/pycore_condvar.h
- `Python/ceval_gil.c`: https://raw.githubusercontent.com/python/cpython/3.14/Python/ceval_gil.c
- What's New in Python 3.14: https://docs.python.org/3/whatsnew/3.14.html

**Monitor:** Samsung Odyssey OLED G9 G93SC specifications: https://www.samsung.com/ca/monitors/gaming/odyssey-oled-g9-g93sc-49-inch-240hz-curved-dual-qhd-ls49cg932snxza/
