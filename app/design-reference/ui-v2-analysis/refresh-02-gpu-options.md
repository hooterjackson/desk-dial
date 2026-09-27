# refresh-02 — GPU-composited overlay options for 240 Hz (Python companion, Windows 11)

Analysis only (read-only pass, 2026-09-25). User requirement: *"my screen is 240hz -- we should
ensure all of the animations both on the knob on the screen and the fullscreen swipes through
album artwork, tracks, app windows is at maximum refresh rate so it looks super smooth"*.

Subject: which rendering/compositing technology the **desktop** surfaces should use so their
motion runs at 240 fps on the user's single 5120 × 1440 @ 240 Hz monitor (100 % scaling, k = 2):
the new **Music explorer** and **Up next** overlays, the v6 **window picker**, and the v5
**floating knob**. The physical knob's own LCD/LED frame rate (ESP32-S3, LVGL, SPI LCD, 60-LED
ring) is firmware and is not affected by any choice made here; it is out of scope for this file.

## 0. Conventions, method, what was and was not measured

| Key | Meaning |
|---|---|
| `carousel.py:L`, `overlay.py:L`, `ui.py:L` | `app/control_center/<file>:<line>` |
| `CAROUSEL.md:L`, `FLOATING_KNOB.md:L` | `app/<file>:<line>` |
| `README:L`, `01:L` | `design-reference/design_handoff_nano_d_master/README.md`, `.../specs/01-FEATURES-explorers-snap-seek.md` |
| `spike/…` | `scratchpad/carousel-spike/…` (the v6 visual spike that ran on the user's screen, 2026-09-24) |
| `bench/…` | `scratchpad/refresh-study/…` (this study's scripts and JSON results) |

`scratchpad` = `<scratchpad>`.

**Method.** Docs, samples and source (URLs in §9), plus **headless** measurements on this PC
with the project venv (`.venv\Scripts\python.exe -I`, Python 3.14.5). The scripts create **no
window at all** (no HWND; DirectComposition devices with no target, so nothing is ever shown),
open no ports and make no Sonos/Apple calls:

- `bench/gpu_bench.py` → `gpu_bench_results.json`: display mode, DWM and DComp timing, pacing
  loops, DComp COM-call costs, D3D11 + DComp surface uploads, a CPU (PIL) explorer frame.
- `bench/gil_bench.py` → `gil_bench_results.json`: DComp call batches under GIL contention.
- `bench/commit_bench.py` → `commit_bench_results.json`: `Commit` → DWM round trip.
- `bench/mem_bench.py` → `mem_bench_results.json`: memory cost of a D3D11 + DComp device.

**Not measured** (they need a visible window, which the rules forbid while the user works):
on-screen frame delivery of any option, WebView2 and Qt start-up/latency, focus behaviour.
Those are marked *expected* or *estimate* below and listed as supervised-check items in §8.

## 1. TL;DR

1. **Recommendation for the new overlays (Music explorer, Up next): DirectComposition through
   plain `ctypes`**, on a dedicated native thread built exactly like `overlay.py`/`carousel.py`
   (private declaration table, own thread, `WS_EX_NOACTIVATE` topmost host, newest-wins
   mailbox). Every motion in 01 §5–§6 is translate/scale/opacity of pre-rendered bitmaps, which
   DirectComposition animates **inside DWM on the compositor clock** (Microsoft: DComp "runs
   animations on a separate thread … even put threads to sleep"). Python only runs on input:
   **0.94 ms** (median) to build and commit 48 animations × 8 cubic segments per detent; **0 ms
   per frame**. No new dependency, no packaging change (system DLLs), no second GUI toolkit.
2. **The compositor on this PC really runs at 240 Hz**: `DwmGetCompositionTimingInfo` and
   `IDCompositionDevice::GetFrameStatistics` both report 10 000 000 / 41 667 = **240.0 Hz**
   (period 4.1667 ms); `DCompositionWaitForCompositorClock`, `DwmFlush` and
   `IDXGIOutput::WaitForVBlank` all wake at **240.0 Hz** (median 4.15–4.17 ms).
3. **The blocker to 240 Hz from Python is not the GPU, it is the GIL.** Every `WinDLL`/
   `WINFUNCTYPE` call releases the GIL (the whole codebase declares Win32 that way:
   `carousel.py:1891`, `overlay.py:305`). With one other Python thread busy, the default 5 ms
   switch interval turned a 240 Hz wake loop into **44 Hz** (median interval 16 ms, p95 32 ms),
   a 0.03 ms DComp property push into **229 ms**, and a 0.55 ms animation build into **2.06 s**.
   Calling the same COM methods through `ctypes.PYFUNCTYPE` (keeps the GIL; valid on x64, one
   calling convention) kept them at **0.03 ms / 1.06 ms** under the same contention. Any design
   that needs Python to run every 4.17 ms is fragile in this process; DWM-run animations are not.
4. **CPU compositing cannot do the explorer at 240 Hz**: one full-screen explorer frame in PIL
   (backdrop copy + 7 resized covers + premultiplied bytes) took **56.5 ms** before any
   `UpdateLayeredWindow` — about 17 fps. The v6 picker only fits because its per-frame CPU work
   is a 2344 × 1184 chrome DIB (compose 0.64 ms + ULW 0.41 ms, `spike/results_p4b.json`).
5. **Window picker: do not migrate now.** It already paces at 240 Hz median on the user's screen
   (spike: median interval 4.2 ms, p95 6.45–8.7 ms). Its DWM thumbnails must be stepped from
   Python every frame anyway (DComp cannot animate a documented thumbnail), and its focus
   contract depends on an activatable in-process host. Apply two cheap fixes instead (§7): GIL-
   keeping calls on the per-frame path and compositor-clock pacing. Revisit (move frost + chrome
   to DComp surfaces on the existing windows, thumbnails untouched) only if the supervised check
   still shows missed frames.
6. **Floating knob: migrate second**, once the explorer's DComp stage exists (same release train
   or the next): the slide becomes a DWM offset/opacity animation; the ring and LCD become
   surfaces updated only when their content changes. Keep its layered + transparent click-through
   window (DComp targets are allowed on layered windows). Today its ring content can change at
   most every 25 ms (`FLOATING_KNOB.md:144`, `ui.py:99`), i.e. ≤ 40 Hz, whatever the display does.
7. **Not recommended:** WebView2 (separate process tree, ~200 MB private on this PC for one
   instance, known focus-stealing issues, backdrop-filter cannot see the desktop, pywebview wants
   the main thread), PySide6/Qt Quick (technically capable — Animators run on the render thread
   and translucent D3D11 windows use a DComp composition swap chain — but a second GUI event loop
   that must own the main thread Tk already owns, ≈ +80–120 MB packaging), a Python-driven
   flip-model swap chain (per-frame Python, GIL-fragile), pyglet/moderngl (OpenGL, no DComp path).

## 2. Facts measured on this PC

### 2.1 Display, adapters, compositor (`bench/gpu_bench_results.json`)

| Item | Value |
|---|---|
| Mode (`EnumDisplaySettingsW`) | 5120 × 1440, 32 bpp, **240 Hz** |
| `DwmGetCompositionTimingInfo(NULL)` | rateRefresh = rateCompose = 10 000 000 / 41 667 (**240.0 Hz**), qpcRefreshPeriod **4.1667 ms** |
| `DCompositionGetStatistics` (latest completed frame) | framePeriod **4.1667 ms**, 1 target |
| `IDCompositionDevice2::GetFrameStatistics` | currentCompositionRate 10 000 000 / 41 667 |
| Adapters (`IDXGIFactory1::EnumAdapters1`) | 0: **NVIDIA GeForce RTX 4090** (owns `\\.\DISPLAY1`, 0,0–5120,1440); 1: AMD Radeon iGPU (**no outputs**); 2: Microsoft Basic Render Driver |
| Output (`IDXGIOutput6::GetDesc1`) | 10 bpc, colour space 0 (SDR, G2.2/P709), max 400 nits; `CheckHardwareCompositionSupport` = 5 (full-screen + cursor-stretched; **no windowed** hardware composition) |
| Monitor (PnP) | Samsung Odyssey G93SC (OLED) |
| WebView2 Evergreen runtime | 154.0.4258.37 (machine-wide) |
| Build tools | Visual Studio Build Tools 2022 17.14 present (a compiled helper is possible) |
| Current frozen bundle | `desktop-dist-v6` = 63.6 MB |

Consequences: (a) the 4090 is the only adapter that should ever host a D3D device for overlays
(creating it on the iGPU would force cross-adapter copies); (b) every surface here is translucent
over the desktop (per-pixel alpha, fades), so whatever produces it — DComp, a composition swap
chain, Chromium, Qt — is blended **by DWM**; no option gets an "independent flip" latency
advantage, and the hardware reports no windowed hardware composition anyway.

### 2.2 Pacing primitives (2 s each, `bench/gpu_bench_results.json` → `pacing`)

| Loop | Wakes/s | Interval median / p99 / max (ms) |
|---|---|---|
| `DCompositionWaitForCompositorClock(0, NULL, 100)` | **240.0** | 4.165 / 4.283 / 4.353 |
| same + 1.4 ms of pure-Python work per wake (the spike's median `work_ms`) | 239.5 | 4.168 / 4.261 / 6.913 |
| same + a GIL-holding Python thread (switch interval 5 ms, the default) | **44.0** | 16.03 / 32.18 / 32.18 (p95 32.01) |
| same + 1.4 ms work + GIL-holding thread | **46.0** | 16.02 / 32.08 / 32.08 |
| same + 1.4 ms work + GIL-holding thread, `sys.setswitchinterval(0.0005)` | **240.0** | 4.167 / 4.271 / 4.338 |
| `DwmFlush()` with nothing of ours pending | 240.0 | 4.152 / 5.079 / 5.297 |
| `IDXGIOutput::WaitForVBlank` (4090 output) | 240.0 | 4.167 / 4.273 / 4.332 |

(The JSON also records DComp frame-id gaps; they reflect when DWM itself composed, not our
misses, so they are not used here.)

### 2.3 DirectComposition from `ctypes` (`gpu_bench_results.json`, `gil_bench_results.json`, `commit_bench_results.json`)

| Measurement | Result |
|---|---|
| `DCompositionCreateDevice3(NULL, IDCompositionDesktopDevice)` | S_OK, 0.39 ms |
| `D3D11CreateDevice` on the 4090 (BGRA support) / DComp device on it | S_OK, **134 ms** (one-off) / 0.75 ms |
| Memory: D3D11 device + DComp device (private bytes) | 9.6 → 62.9 → 63.1 MB (**+53.5 MB**, driver) |
| vtable slots verified by S_OK (MSVC puts the *later-declared* overload first): Visual `SetOffsetX(float)`=4, `SetOffsetY(float)`=6, `SetEffect`=10; Visual3 `SetOpacity(float)`=30, `SetTransform(4×4)`=32; Device3 `CreateGaussianBlurEffect`=24, `CreateSaturationEffect`=29; blur `SetStandardDeviation(float)`=5; saturation `SetSaturation(float)`=5, `SetInput`=3; animation `SetAbsoluteBeginTime`=4, `AddCubic`=5, `End`=8 | all **S_OK**; 0 failures in 32 640 animation calls |
| Per-frame push from Python: 16 visuals × (offsetX, offsetY, opacity, 4×4 transform) + `Commit` (65 calls) | median **0.070 ms**, p99 0.116, max 0.351 (`Commit` itself 0.003 ms) |
| Per detent: 48 DWM animations (16 cards × offset/scale/opacity), 8 cubic segments each, absolute begin time, applied, `Commit` | median **0.944 ms**, p95 1.198, max 1.248 |
| CSS `cubic-bezier(0.22,1,0.36,1)` fitted as 8 Hermite cubics in time | max error 0.00037 of the travel = **0.24 px** over a 640 px move |
| `Commit` → `WaitForCommitCompletion` (DWM picked the batch up) | median **4.145 ms**, p95 4.625, max 4.702 (= one compositor frame) |

GIL contention (`gil_bench_results.json`, 16 visuals):

| Call style | Contention | Frame push (33 calls) median / p95 | Detent build (32 animations) median / p95 |
|---|---|---|---|
| `WINFUNCTYPE` (GIL released per call — today's pattern) | none | 0.030 / 0.035 ms | 0.553 / 0.792 ms |
| `WINFUNCTYPE` | one busy Python thread | **228.7 / 361.2 ms** | **2 059 / 2 503 ms** |
| `PYFUNCTYPE` (GIL kept for the call) | none | 0.029 / 0.037 ms | 1.011 / 1.494 ms¹ |
| `PYFUNCTYPE` | one busy Python thread | **0.029 / 0.031 ms** | **1.055 / 1.255 ms** |

¹ Slower only because the script rebuilt a `PYFUNCTYPE` prototype class per call (ctypes caches
`WINFUNCTYPE` classes but not `PYFUNCTYPE`); production code builds each prototype once.

### 2.4 Bitmap upload to DComp surfaces (`IDCompositionSurface::BeginDraw` → `ID3D11DeviceContext::UpdateSubresource` → `EndDraw`)

| Surface | Size | CPU submit median | Until GPU done median |
|---|---|---|---|
| Explorer cover, 340 design px at k = 2 | 680 × 680 (1.85 MB) | 0.285 ms | 0.524 ms |
| Up next cover, 380 at k = 2 | 760 × 760 (2.31 MB) | 0.293 ms | 0.568 ms |
| Frost reduced /8 | 640 × 180 | 0.021 ms | 0.175 ms |
| Backdrop reduced /4 | 1280 × 360 | 0.084 ms | 0.190 ms |
| Full-monitor backdrop | 5120 × 1440 (29.5 MB) | 1.156 ms | 2.455 ms |

### 2.5 CPU reference points

| Measurement | Result |
|---|---|
| PIL full-screen explorer frame (copy 5120 × 1440 backdrop, 7 bilinear-resized 680 px covers, `alpha_composite`, `tobytes('raw','BGRa')`), no ULW | median **56.5 ms** |
| PIL frost (reduce 8, GaussianBlur 10, bilinear upscale to 5120 × 1440), synthetic | median 24.1 ms |
| v6 spike on the user's screen (`spike/results_p4.json`, `results_p4b.json`) | interval median 4.2 / 4.2 ms, **p95 6.45 / 8.7 ms**, max 19.5 / 14.7; work 1.44 / 1.41 ms; compose 0.64; ULW 0.41; thumbnails 0.36 / 0.33; DwmFlush 2.84 / 2.83 ms |
| WebView2 group already running on this PC (SearchHost) | 5 processes (browser, GPU, 2 utility, renderer): **196 MB private, 390 MB working set** |

## 3. What the scenes need

All values from the master handoff; k = 2 on this monitor (`CAROUSEL.md:54`).

| Surface | What moves (per 01/README) | Property types | Changes pixels every frame? |
|---|---|---|---|
| **Music explorer** (01:171-192) | 7 visible cards (±300/±470 px offsets, scale 1/0.60/0.42, opacity, dark overlay), 420 ms turn, 14 px end bump, open stagger 45 ms × distance over 440 ms, source switch drop/stagger, Play grow 1.12; tab underline grows 320 ms; dots; label swap; ambient cover (blur 90 px, saturate 1.5, 50 %) crossfades 600 ms; backdrop blur 36 px + saturate 1.3 + tint | translate, scale, opacity, crossfade | **No** — every element is a bitmap that is only moved/scaled/faded; labels change per detent |
| **Up next** (01:195-219) | 9 rows (offset Y ±100/176/236/284, scale, opacity), 420 ms turn, bump, open stagger 40 ms, shuffle fade/stagger, Play grow 1.06; 380 px cover crossfades 420 ms (playlists); heart pop spring | translate, scale, opacity, crossfade, spring | **No** |
| **Window picker** (CAROUSEL.md §2, §4) | 7 DWM thumbnails + chrome (shades, badges, shadows, outline, label, dots), frost fade | thumbnail rects/opacity (DWM API), chrome bitmap | Thumbnails are live; chrome is recomposed per frame today |
| **Floating knob** (FLOATING_KNOB.md:120-122, 144) | slide in 220 ms / out 260 ms (`ptSrc.x` + constant alpha); ring colours and LCD | translate + opacity; content | Ring/LCD content changes at the LED/LCD content rate, not 240 Hz |

At 240 Hz a frame is 4.167 ms. Two ways to be smooth: (A) let a compositor evaluate the motion
every frame and keep Python out of the frame loop, or (B) have Python produce or push every frame
within 4.17 ms **and** be scheduled on time every 4.17 ms. §2.2–§2.3 show (B) holds only while no
other Python thread is busy. Everything in the two new overlays is expressible as (A).

## 4. Options

### a. DirectComposition via ctypes (recommended)

**How it would be built** (a new native "stage" thread, same skeleton as `overlay.py`/`carousel.py`):

- Host: `WS_POPUP`, ex `WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE |
  WS_EX_NOREDIRECTIONBITMAP`, `rcMonitor`, shown with `SWP_NOACTIVATE`/`SW_SHOWNA`,
  `WM_MOUSEACTIVATE → MA_NOACTIVATE` — the floating knob's never-activated recipe
  (`overlay.py:205-219`, `overlay.py:1123`). Per-thread PMv2 as today.
- Devices: `D3D11CreateDevice` on the adapter whose output contains the monitor (the 4090),
  `DCompositionCreateDevice3(dxgiDevice, IID_IDCompositionDesktopDevice)`,
  `CreateTargetForHwnd(hwnd, TRUE)`. Created once at start-up off the Tk thread (134 ms) and kept.
- Visual tree for the explorer: backdrop (reduced capture surface scaled ×4, `IDCompositionGaussianBlurEffect`
  σ = 36·k/4 = 18 and `IDCompositionSaturationEffect` 1.3 — both verified S_OK here — or a PIL
  pre-blurred surface) → tint (1 × 1 surface scaled, opacity 0.5) → two ambient visuals
  (crossfade by opacity) → per card: container with a `ScaleTransform` (centre = card centre),
  children shadow sprite / cover / black overlay / inset line → label, dots, tabs, hints.
  All bitmaps are rendered once with PIL (the carousel's text engine, `carousel_render.py`) and
  uploaded with `BeginDraw`/`UpdateSubresource`/`EndDraw` (0.29 ms per 680 px cover, §2.4).
- Motion: on each detent, for each card, `CreateAnimation` → `SetAbsoluteBeginTime(t0)` →
  `AddCubic` × 8 (the CSS curve fitted in time, 0.24 px max error) → `End(dur, target)` → set it
  on `OffsetX`, `ScaleX/ScaleY`, `Opacity`, overlay opacity → one `Commit`. DWM evaluates the
  curves at every composed frame, i.e. at 240 Hz here, whether or not Python is running
  ([DComp animation](https://learn.microsoft.com/en-us/windows/win32/directcomp/animation)).
  Retargeting mid-flight keeps the carousel's CSS-transition semantics (`CAROUSEL.md` §4): Python
  holds the same analytic model and the absolute begin time, so the value at the new begin time
  is exact and the new curve starts from it — no jump. Stagger = a leading constant segment (the
  docs say a later absolute begin time *delays* the start; a hold segment makes the pre-start
  value explicit). End bump, Play grow, crossfades and the heart spring are more segments.
- Pacing for anything Python must still step (none in the explorer/Up next): Windows 11's
  `DCompositionWaitForCompositorClock` (build 22000+, this PC is 26200; resolve with
  `GetProcAddress`, fall back to the existing `DwmFlush` Pacer). It multiplexes app event
  handles, so a mailbox event can wake the same wait ([compositor clock](https://learn.microsoft.com/en-us/windows/win32/directcomp/compositor-clock/compositor-clock)).
- Hot calls through `PYFUNCTYPE` prototypes built once (§2.3); blocking calls (waits, `DwmFlush`,
  `GetMessageW`, anything that can `SendMessage` to another Python thread such as `SetWindowPos`
  on a cross-thread window) stay on `WinDLL` so the GIL is released and no cross-thread
  `SendMessage` can deadlock against a held GIL.

**Can it hit 240 fps for these scenes?** Yes, with high confidence for the explorer and Up next:
the compositor runs at 240.0 Hz here (§2.1), DComp animations are evaluated by DWM per composed
frame, and the scene is ~20 textured quads plus one full-screen backdrop — trivial for a 4090 at
5120 × 1440. Python's cost is 0.94 ms per detent and nothing per frame. Not yet observed on screen
(no windows allowed): §8 item 1 verifies it with `DCompositionGetTargetStatistics`.

**Input → photon.** From the moment the stage thread has the detent: ~1 ms to build and commit,
DWM picks the batch up at the next frame (commit round trip 4.15 ms median, §2.3), composes and
presents at the following vblank: about **1–2 frames (4–8 ms) + scan-out**, the same order as
today's ULW path. Upstream of that, the Tk poll (up to 25 ms, `ui.py:99`, `ui.py:1839`) dominates
today (§7).

**CPU.** ≈ 1 ms of Python per detent, zero per frame, no per-frame DIB traffic. Compare the v6
picker's ≈ 1.4 ms per frame × 240 frames/s ≈ a third of one core while it moves (spike `work_ms`).

**Integration.** No new package; the host is just another native thread beside `NanoD-overlay`
and `NanoD-carousel`, fed by the same newest-wins mailbox + `PostMessageW` pattern, never touching
Tk. Reuses: `CaptureWorker` + `WDA_EXCLUDEFROMCAPTURE` capture (`carousel.py:2309-2343`), the
frost maths, the PIL text engine, the `CubicBezier`/`Tween` model (`carousel.py:104`) as the
analytic twin of the DWM curves, fake-backend testing. Effort: comparable to the v6 carousel build
(a stage engine + two scenes + tests); the COM surface needed is small (≈ 30 methods).

**Focus.** Fully under our control, identical to the floating knob that has never activated since
v5. Explorer and Up next never take the foreground; the knob drives them over serial.

**Capture exclusion.** `SetWindowDisplayAffinity` acts on our top-level HWND, and DComp content is
that window's content, so the carousel's rule carries over unchanged (expected; §8 item 2).

**Multi-monitor / DPI.** Physical pixels, host sized to `rcMonitor` of the chosen monitor, PMv2 per
thread as today; the compositor clock follows the display the content is on (docs). One monitor
here.

**Packaging.** +0 MB (dcomp.dll, d3d11.dll, dxgi.dll are in System32). Memory: +53.5 MB private
for the D3D11 device (§2.3); bitmaps live in VRAM (24 GB), not in 29.5 MB DIBs.

**Risks.** Hand-written vtables (mitigated: overload order verified by S_OK above; unit tests on
slot tables as `overlay.py` does for structures); COM lifetime (strict Release on the owning
thread); device loss after a driver update/TDR (check `GetDeviceRemovedReason`, rebuild devices
and re-upload — sprites are cheap); curve fidelity (piecewise cubic, measured 0.24 px); DWM's own
missed frames under heavy GPU load (animations stay time-correct, they just drop frames); z-order
between DWM thumbnails and DComp visuals in one window is undocumented (only matters for the
picker — keep them in separate windows).

**Relation to the v6 host.** `carousel.py` creates the picker host with
`WS_EX_NOREDIRECTIONBITMAP` (`carousel.py:1774`, `carousel.py:2029-2047`) purely so it has **no
redirection surface**: its own area is transparent and it serves only as the destination of
`DwmRegisterThumbnail` (`carousel.py:2565-2589`) and as the activatable input window
(`carousel.py:56-61`, `CAROUSEL.md:158`). Nothing draws into it — no DComp target exists today;
the chrome and frost are separate layered windows presented with `UpdateLayeredWindow`
(`carousel.py:2399-2416`). A DComp target could be bound to that host (one target per
(HWND, topmost) layer, [CreateTargetForHwnd](https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-idcompositiondesktopdevice-createtargetforhwnd)),
but the relative order of thumbnails and DComp layers in one window is not documented; the only
documented way to get a thumbnail *as a DComp visual* is none (the private
`DwmpCreateSharedThumbnailVisual` is undocumented). Hence §5's advice: if the picker ever moves,
put DComp content on the **chrome/glass** windows, keep thumbnails on the host.

#### a2. Variant: Windows.UI.Composition (WinRT visual layer) via PyWinRT

Same compositor, nicer animation API: `ScalarKeyFrameAnimation` with `CubicBezierEasingFunction`
(the exact CSS curves) and spring `NaturalMotion` animations; Microsoft recommends it over DComp on
Windows 10+ (note on the DComp animation page). PyWinRT 3.2.x ships cp314 wheels. Costs: a
`DispatcherQueue` must exist on the thread and the window target comes from the COM-only
`ICompositorDesktopInterop::CreateDesktopWindowTarget` ([Win32 visual layer](https://learn.microsoft.com/en-us/windows/uwp/composition/using-the-visual-layer-with-win32));
loading bitmaps needs `ICompositionGraphicsDevice` interop from a D2D device; blur needs
`CompositionEffectBrush` with Win2D-style `IGraphicsEffect` descriptions that PyWinRT does not
provide; `CreateHostBackdropBrush` is reported not to work for Win32 windows
([samples #84](https://github.com/microsoft/Windows.UI.Composition-Win32-Samples/issues/84)). Two
interop layers and a new dependency for easing we can already fit to 0.24 px: keep as a fallback
if springs or exact curves become important.

### b. Direct3D11/Direct2D flip-model composition swap chain driven from Python

**Shape.** `IDXGIFactory2::CreateSwapChainForComposition` (B8G8R8A8, `DXGI_ALPHA_MODE_PREMULTIPLIED`,
`FLIP_DISCARD`/`FLIP_SEQUENTIAL`, `FRAME_LATENCY_WAITABLE_OBJECT`) set as the content of a DComp
visual on a `NOREDIRECTIONBITMAP` window — exactly what Qt does for translucent windows
(`qrhid3d11.cpp` dev L5678-5836: DComp target + visual, `FLIP_DISCARD`, `PREMULTIPLIED`,
`CreateSwapChainForComposition`, `SetContent`) and what the AutoHotkey Alt-Tab replacement
Alt-Tabby does from a scripting language ([Alt-Tabby #177](https://github.com/cwilliams5/Alt-Tabby/issues/177)).
Each frame: wait on the waitable object (or the compositor clock), D2D `BeginDraw`, ~20 ×
`SetTransform` + `DrawBitmap(opacity)`, `EndDraw`, `Present(1, 0)`.

**240 fps?** GPU: easily. Python: ~50–70 COM calls per frame ≈ 0.05–0.1 ms by extrapolation from
the measured 65-call push (0.07 ms), so the budget is fine **in isolation**. The problem is being
scheduled every 4.17 ms: §2.2 shows 240 Hz idle and with 1.4 ms of work, but **44–46 Hz** once any
other Python thread runs pure-Python code, 240 Hz again only with a 0.5 ms switch interval (a
process-wide change that makes every thread pay more GIL hand-offs). GC pauses add to it. A
compiled helper (a small C++ render thread in a `.pyd`, Build Tools present) removes the GIL from
the frame loop, but then we maintain a native renderer to get what DComp animations give for free.

**Latency.** Waitable-object flip model gives ~1 frame queue + DWM composition (a translucent
overlay is always DWM-composed, §2.1): ≈ 2 frames. **CPU:** a Python wake every 4.17 ms plus draw calls while animating.
**Focus/capture/DPI/packaging:** as (a), same HWND control, +0 MB.

**Verdict.** Only for content that must change every frame. None of the new designs need that;
the floating knob's ring at its LED content rate is served by surface updates (§5).

### c. WebView2 (pywebview or direct COM) hosting HTML/CSS versions of the prototypes

**Appeal.** The prototypes are HTML (`README:24-32`); CSS `transform`/`opacity` animations are
compositor-only in Chromium ([web.dev](https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count):
"only two properties for which that is true — transforms and opacity"), so they run off the page's
main thread on the GPU, and `requestAnimationFrame` follows the monitor refresh (the only options
are "the monitor's refresh rate or no limit at all", [WebView2Feedback #3045](https://github.com/MicrosoftEdge/WebView2Feedback/issues/3045)).
On a single 240 Hz monitor it is **expected** to animate at 240 Hz (not measured: needs a window;
§8 item 5). Chromium's mixed-refresh multi-monitor quirks do not apply to one monitor.

**Problems for this app.**
- **Transparency / blur.** `DefaultBackgroundColor` supports alpha 0 or 255 only; per-pixel
  transparency needs visual hosting (`CoreWebView2CompositionController` in a DComp tree on a
  `NOREDIRECTIONBITMAP` window). pywebview's API page still says `transparent` is "Not supported
  on Windows" while its changelog/issue tracker describe EdgeChromium transparency and fixes
  ([#745](https://github.com/r0x0r/pywebview/issues/745), [#1611](https://github.com/r0x0r/pywebview/issues/1611),
  [#1653](https://github.com/r0x0r/pywebview/issues/1653)) — unreliable either way.
  `backdrop-filter` only sees the page, never the desktop, so the frost still needs our capture,
  shipped into the page each open (29.5 MB raw: `CoreWebView2SharedBuffer`, or an encoded image).
- **Focus.** "never takes focus" is a hard requirement for explorer/Up next. Known issues: the
  first navigation steals focus ([#862](https://github.com/MicrosoftEdge/WebView2Feedback/issues/862),
  [#1526](https://github.com/MicrosoftEdge/WebView2Feedback/issues/1526)); a transparent full-screen
  WebView2 still hit-tests and swallows input ([#5668](https://github.com/MicrosoftEdge/WebView2Feedback/issues/5668)).
  pywebview has `focus=False` ("non-focusable window") and `on_top`, but the content HWNDs belong
  to the runtime's processes.
- **Process/threads.** pywebview requires `webview.start()` on the **main thread**
  ([pywebview API](https://pywebview.flowrl.com/api/)) — Tk owns it — so it would run in a second
  process. Direct COM (WebView2Loader + ctypes callback objects) could live on an STA thread in
  process, at the cost of implementing the async COM handler interfaces by hand.
- **Memory / start-up.** Browser + GPU + utility + renderer processes; the one WebView2 group on
  this PC right now (SearchHost) holds **196 MB private / 390 MB working set**. Microsoft calls the
  cold launch a "noticeable delay" and advises against WebView2 for quick UI
  ([performance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/performance)),
  so it must be kept warm all day (≈ 200 MB) to open on a knob press.
- **Latency.** Knob event → host → `PostWebMessageAsJson` (cross-process IPC) → renderer JS →
  commit → GPU process → DComp → DWM: estimate **2–3 frames (8–13 ms)** plus IPC, i.e. ≈ 1 frame
  worse than (a).
- **Capture exclusion.** Affinity is set on our top-level window; with windowed hosting the web
  content is child HWNDs of another process (expected covered, unverified); with visual hosting it
  is inside our DComp tree (covered).
- **Packaging.** pywebview 6.2.1 (Apr 2026) uses pythonnet on Windows; pythonnet **3.1.0** (May 2026)
  is the first release that supports Python 3.14 ([PyPI](https://pypi.org/project/pythonnet/)).
  Roughly +10–20 MB (estimate) plus the .NET Framework already in Windows; the Evergreen runtime
  is present (154.0.4258.37).

**Verdict.** Best design fidelity, worst fit: second process tree, ≈ 200 MB resident, focus risk
on exactly the property the design requires, and no 240 Hz gain over (a). Keep in mind only if
the team wants to ship the HTML prototypes verbatim.

### d. PySide6 / Qt Quick (and briefly pyglet / moderngl)

**Capability.** PySide6 **6.11.2** (Aug 2026) ships `cp310-abi3` wheels, so it runs on 3.14
([PyPI](https://pypi.org/project/PySide6/)). On Windows the threaded render loop is the default
with Direct3D 11, and "the rate is queried from the QScreen … with a 144 Hz screen the interval is
6.94 ms" ([scene graph](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html)) — so 240 Hz
is expected. **Animator** types "can animate on the scene graph's rendering thread even when the
UI thread is blocked" ([Animator](https://doc.qt.io/qt-6/qml-qtquick-animator.html)) — the Qt
equivalent of DWM-run animations, immune to Python stalls (regular QML animations tick on the GUI
thread, i.e. the thread running Python). Translucent windows: the D3D11 RHI binds a DComp target
and a premultiplied `FLIP_DISCARD` composition swap chain when the swap chain has alpha
(`qrhid3d11.cpp` L5678-5836); frameless + alpha makes the window `WS_EX_LAYERED`
(`qwindowswindow.cpp` L491-509). Window flags map to the styles we need:
`WindowDoesNotAcceptFocus → WS_EX_NOACTIVATE` (L814-815), `Tool → WS_EX_TOOLWINDOW`,
`WindowTransparentForInput → WS_EX_TRANSPARENT` (L852-855), show-without-activating →
`SW_SHOWNOACTIVATE` (L2031-2036). `winId()` gives an HWND we can pass to
`SetWindowDisplayAffinity` in-process. Blur: `MultiEffect` on the captured image (backdrop still
needs our capture).

**Problems.** A second GUI toolkit and event loop: `QGuiApplication` belongs on the main thread,
which Tk owns (and the documented Tk thread-state crash, `windows.py:24-30`, shows how fragile
native loops next to Tk already are) → realistically a separate overlay process with IPC, which also complicates the picker's
foreground grant (it would need `AllowSetForegroundWindow` across processes). Qt sets process DPI
awareness itself. Packaging: `PySide6_Essentials` wheel alone is **76.9 MB** compressed; a frozen
Qt Quick app typically adds ≈ 80–120 MB (estimate) to today's 63.6 MB bundle. Latency ≈ 2 frames
(render thread + swap chain + DWM) plus IPC. Effort: rewriting scenes in QML plus a process
boundary.

**Verdict.** The strongest of the "framework" options and a reasonable escape hatch if the UI
grows into something QML is much better at (text-heavy, scrolling lists with inertia); not worth
it for the four surfaces here, where (a) gets the same compositor-thread animation with no second
toolkit.

**pyglet / moderngl.** OpenGL: no DComp composition swap chain, per-pixel transparent top-level GL
windows need blur-behind or readback tricks, frame loop driven from Python (same GIL fragility as
b). Not recommended.

## 5. Comparison

| | a. DComp (ctypes) | a2. WinRT visual layer | b. Python swap chain | c. WebView2 | d. Qt Quick |
|---|---|---|---|---|---|
| 240 fps evidence | Compositor 240.0 Hz measured; DWM-run animations (docs); 0 Python per frame | Same compositor | Python must hit every 4.17 ms: 240 Hz idle, **44–46 Hz** with one busy Python thread | rAF = monitor rate (#3045); CSS transform/opacity compositor-only; not measured | Threaded loop at screen rate (docs); Animators on render thread; not measured |
| Python per frame | 0 | 0 | 0.05–0.1 ms + wake | 0 | 0 (Animators) |
| Python per detent | 0.94 ms measured | similar | small | message post | property sets + IPC |
| Input → photon (after the event reaches the renderer) | 1–2 frames (4–8 ms) | 1–2 frames | ≈ 2 frames | ≈ 2–3 frames + IPC (est.) | ≈ 2 frames + IPC (est.) |
| CPU while animating | ≈ 0 | ≈ 0 | one core share at 240 wakes/s | GPU/renderer processes | render thread |
| Integration with Tk tray app | Native thread, existing patterns | + DispatcherQueue, interop | Native thread | Separate process (main-thread rule) or hand-written COM | Separate process (main-thread rule) |
| Focus risk (explorer/Up next never focus) | Low (own HWND, proven recipe) | Low | Low | **High** (#862, #1526, #5668) | Low–medium (flags map to NOACTIVATE) |
| Picker foreground ownership | Unchanged if picker stays | — | — | Cross-process grant | Cross-process grant |
| Capture exclusion | Own top-level window | Own window | Own window | Own window; child content in other process (verify) | Own window |
| Multi-monitor / DPI | Physical px, PMv2 per thread | Same | Same | Runtime scales | Qt scales; sets process DPI awareness |
| Packaging | **+0 MB** | + winrt wheels (small) | +0 MB (+.pyd if compiled) | + pythonnet/pywebview ≈ 10–20 MB (est.) | **+80–120 MB** (est.) |
| Memory | +53.5 MB (D3D device) | similar | similar | **≈ 200 MB** (measured group) | Qt + D3D, tens of MB (est.) |
| Blur of the desktop | Capture → surface → DComp blur/saturate (S_OK) or PIL | Needs effect interop | D2D effects | Capture → page | Capture → MultiEffect |

## 6. Recommendation and migration order

**New overlays → DirectComposition (option a), one shared "stage" engine for explorer and Up next.**

1. **Before building UI V2's overlays: a supervised DComp spike** (with the user's go-ahead, like the
   v6 spike): one full-screen `NOACTIVATE` topmost window, explorer-like tree (9 card visuals,
   backdrop + ambient, label), DWM-run turns driven by a timer, `WDA_EXCLUDEFROMCAPTURE` during the
   capture. Record frames presented per second during motion (`DCompositionGetTargetStatistics`
   over the animation's frame ids), foreground before/after, GDI/USER baseline, dwm.exe commit.
2. **Build explorer + Up next on it.** Scene model in pure Python (fake clock, CarouselMachine-style
   tests); DWM curve builder with the analytic twin for retargeting; PIL sprites uploaded once;
   capture/frost reused from `carousel.py`; hot COM calls through prebuilt `PYFUNCTYPE`
   prototypes, blocking calls on `WinDLL`.
3. **Floating knob → migrate in the release after the stage lands** (or in the same release if the
   spike is clean). Slide = DWM `OffsetX` + opacity animation (220/260 ms, ease-out/in cubic) instead
   of `ptSrc.x` stepping (`FLOATING_KNOB.md:120-122`); face/ring/LCD as DComp surfaces updated on
   content change (a 458 px face is ≈ 0.8 MB, ≈ 0.1–0.3 ms per upload by §2.4); keep
   `WS_EX_LAYERED | WS_EX_TRANSPARENT` click-through (DComp targets are allowed on layered windows,
   [CreateTargetForHwnd remarks](https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-idcompositiondesktopdevice-createtargetforhwnd));
   feed ring colours from the LED engine at its own rate (60 Hz like the hardware ring, or higher
   if `alive_lights` sampling is cheap) instead of the 25 ms Tk tick.
4. **Window picker → stays v6 native**; ship the two fixes of §7 (small, low risk) and re-measure in
   the picker's supervised check (`CAROUSEL.md` §10 already records `presenter.metrics()`). Move its
   frost + chrome to DComp surfaces on the **existing** glass/chrome windows only if frames are
   still missed; keep DWM thumbnails and the activatable host (`CAROUSEL.md` §1 focus contract)
   exactly as they are. Never move the picker to WebView2 or Qt (foreground grant across processes,
   no thumbnail visuals).

## 7. Cross-cutting findings that cap smoothness regardless of the GPU choice

1. **GIL released on every Win32/COM call.** All native modules declare functions on private
   `WinDLL` instances (`carousel.py:1891`, `overlay.py:305`) and COM vtables with `WINFUNCTYPE`
   (`windows.py:274-275`, `window_facts.py:240-253`); nothing sets `sys.setswitchinterval`. Under
   contention each such call can wait one switch interval (5 ms) to get the GIL back (§2.3: 33 calls
   → 229 ms). The v6 picker's per-frame path makes ~10 such calls (7 × `DwmUpdateThumbnailProperties`,
   ULW, constant-alpha ULWs, `DwmFlush`), which plausibly explains part of the spike's p95 6.45–8.7 ms
   intervals (hypothesis; the spike ran while other threads existed). Fix: prebuilt `PYFUNCTYPE`
   prototypes (x64 only) for short, non-blocking calls on the frame path; keep waits and anything
   that may `SendMessage` to another thread on `WinDLL`. Optional: `sys.setswitchinterval(0.001)`
   while an overlay animates (§2.2: 0.5 ms restored 240 Hz wakes), then restore.
2. **25 ms Tk poll between the knob and every overlay.** `POLL_MS = 25` (`ui.py:99`, rescheduled at
   `ui.py:1839`) sits between serial input and `highlight(...)`: 0–25 ms (mean 12.5 ms) added to
   input → photon, i.e. up to 6 frames at 240 Hz, and the floating knob's ring content is capped at
   one submit per tick (`FLOATING_KNOB.md:144`) → ≤ 40 Hz. Posting knob position events straight
   from the serial reader to the overlay threads (the mailbox/`PostMessageW` pattern already exists)
   would remove it; this is independent of DComp.
3. **Pacing primitive.** `DwmFlush` does pace at 240 Hz here (§2.2), so the existing Pacer
   (`carousel.py:476-520`, `overlay.py:1205-1218`) is not wrong; `DCompositionWaitForCompositorClock`
   is the documented replacement (display-independent, event multiplexing, DRR-aware).

## 8. Verification items (supervised, after the user's go-ahead)

1. DComp stage spike: frames presented per second during a turn and an open (target stats), no
   foreground change, GDI/USER back to baseline, dwm.exe commit before/after.
2. `WDA_EXCLUDEFROMCAPTURE` on a DComp-content window: capture byte-identical to the desktop (the v6
   spike's p7 method, `spike/results_p7.json`).
3. Stage under load: a CPU-busy Python thread in the app while turning — animations must not
   stutter (they are DWM-run), detent latency ≤ 1 frame + 1 ms with `PYFUNCTYPE` calls.
4. Picker after the §7.1 fix: `presenter.metrics()` intervals p95 ≤ 4.6 ms.
5. Only if WebView2 is ever reconsidered: a test page logging `requestAnimationFrame` deltas and a
   focus probe (`GetForegroundWindow` before/after first navigation and show).

## 9. Sources

- DirectComposition animation: https://learn.microsoft.com/en-us/windows/win32/directcomp/animation
- Compositor clock (Win11): https://learn.microsoft.com/en-us/windows/win32/directcomp/compositor-clock/compositor-clock
- `DCompositionWaitForCompositorClock` (build 22000+): https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-dcompositionwaitforcompositorclock
- `DCompositionBoostCompositorClock`: https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-dcompositionboostcompositorclock
- `IDCompositionAnimation::SetAbsoluteBeginTime`: https://learn.microsoft.com/en-us/windows/win32/api/dcompanimation/nf-dcompanimation-idcompositionanimation-setabsolutebegintime
- `IDCompositionGaussianBlurEffect`: https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nn-dcomp-idcompositiongaussianblureffect
- `CreateTargetForHwnd` (layered windows allowed, one target per layer): https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-idcompositiondesktopdevice-createtargetforhwnd
- SDK headers used for vtable order: `C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um\dcomp.h` (L420-L1748), `um\dcompanimation.h`, `shared\dcomptypes.h`, `um\d3d11.h`, `shared\dxgi.h`, `shared\dxgi1_6.h`
- Windows.UI.Composition from Win32: https://learn.microsoft.com/en-us/windows/uwp/composition/using-the-visual-layer-with-win32 ; HostBackdropBrush on Win32: https://github.com/microsoft/Windows.UI.Composition-Win32-Samples/issues/84
- Alt-Tabby (AutoHotkey, D3D11/DXGI/D2D/DComp, compositor clock): https://github.com/cwilliams5/Alt-Tabby , https://github.com/cwilliams5/Alt-Tabby/issues/177
- Qt: https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html , https://doc.qt.io/qt-6/qml-qtquick-animator.html , https://doc.qt.io/qt-6/qquickwindow.html , https://raw.githubusercontent.com/qt/qtbase/dev/src/gui/rhi/qrhid3d11.cpp , https://raw.githubusercontent.com/qt/qtbase/dev/src/plugins/platforms/windows/qwindowswindow.cpp (fetched 2026-09-25; line numbers are of that fetch)
- PySide6 6.11.2 / Essentials 76.9 MB: https://pypi.org/project/PySide6/ , https://pypi.org/project/PySide6-Essentials/
- WebView2: https://github.com/MicrosoftEdge/WebView2Feedback/issues/3045 , /issues/862 , /issues/1526 , /issues/5668 ; process model https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/process-model ; performance https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/performance ; `DefaultBackgroundColor` https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2controller.defaultbackgroundcolor
- Compositor-only CSS properties: https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count
- pywebview: https://pywebview.flowrl.com/api/ , https://pypi.org/project/pywebview/ , https://github.com/r0x0r/pywebview/issues/745 , /issues/1611 , /issues/1653 ; pythonnet 3.1.0: https://pypi.org/project/pythonnet/
- comtypes 1.4.17 (not needed; its methods are `WINFUNCTYPE`-based and release the GIL too): https://pypi.org/project/comtypes/
- PyWinRT (cp314 wheels, 3.2.x): https://pypi.org/project/winrt-runtime/ , https://github.com/pywinrt/pywinrt/releases
