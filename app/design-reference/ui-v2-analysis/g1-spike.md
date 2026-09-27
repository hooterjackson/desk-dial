# G1 spike: compositor-run motion at 240 Hz, measured on screen

Run on screen on 2026-09-25 at 17:47:37–17:49:19 local time, with the user's go-ahead given at 17:47. It showed four full-screen test overlays, 3 s apart: three pacing passes of 26.0 s of animation each, then an 11.4 s witness pass.

- **Code:** `work\spike_dcomp\` (`dcomp_spike.py`, `curves.py`, `winapi.py`, `run_spike.py`). Source sha256 `56a89f35…db6e`, the same source as the passing selftest `g1-spike-selftest-20260925-173628.json` (53 of 53 gated checks).
- **Raw results:** `app\diagnostics\g1-spike-onscreen-20260925-174737-pacing1.json`, `-pacing2.json`, `-pacing3.json` and `-witness.json`, each with a `.log`. The runner's roll-up is `-summary.json`.
- **Machine:** Samsung Odyssey G93SC, 5120 × 1440 at 240 Hz (the mode was read two ways and both agree), on an RTX 4090. The user has NVIDIA G-SYNC on for windowed and full-screen mode (the JSON records it as `windowed`). Windows 11 build 26200, Python 3.14.5.

---

## In plain words

**The main question is answered yes, for this test.** Once Python hands DirectComposition a set of animations, Windows' compositor draws them by itself at every refresh of the 240 Hz monitor. Three separate runs each tested three kinds of load, and the overlay showed a new frame at every screen refresh:

- **Frames shown:** 14,666 of the 14,670 expected.
- **Skipped refreshes:** none. No two consecutive frames were ever more than one refresh apart. The 4 uncounted frames fall at the edges of the measuring windows.
- **Lost statistics:** none.

**Python stays out of the frame loop.** Python runs only when the (simulated) knob steps. Each time, it takes about 1 ms to build about 50 animations and send them to Windows in one batch, called a commit. The overlay thread used about 1.6 % of one CPU core at 14 steps per second.

**Busy Python code elsewhere does not affect smoothness.** A thread running pure Python for 10 ms of every 25 ms changed nothing on screen. It did make each step's commit slower (95th percentile 2.5–3.1 ms instead of about 1.6 ms). As a result, 4–11 % of steps started one frame later than planned. That is invisible, because the motion continues along the same curve.

**A thread that holds Python's lock for 15 ms at a time does not affect smoothness either, but it hurts responsiveness.** "The lock" here is Python's global interpreter lock (GIL); a C call can keep it and block every other Python thread. The frame rate stayed at 240. The damage was to timing:

- **Late commits:** measured from Python, only 65 %, 84 % and 69 % of steps were committed before the frame they were meant for.
- **Probably an overstatement:** a closer look (§3.4) shows the 15 ms usually landed just after the step had already been handed to Windows. The real delay on screen was therefore probably smaller than these figures suggest.
- **Real delays did happen:** in one run, 5 steps were held up before they could start, by up to 15.9 ms.
- **Knock-on effect:** the spike's own safety margin grew to 14–17 ms, which pushed every step 2–3 frames later than needed.

The rule stands: no thread may hold the lock for long while an overlay can take input.

**The frames really were the overlay's own.** Nothing else on the screen changed while the tests ran: zero other screen updates in the quiet periods. Two small markers were also checked:

- **The moving marker:** it moved 2.33 px per frame. A capture thread photographed it 810 times, and every sample was where the maths says it should be, to within one frame.
- **The reversing marker:** it reverses like a card, 50 times at 20 per second, and stayed on its curve through every reversal.

Scaling is smooth (linear, not blocky) and edges are soft (anti-aliased). Both were checked on screen pixels.

**Animation start times are on the right clock.** An animation scheduled 500 ms ahead started on time, to within about a frame. On this PC the two possible time units (QPC ticks and 100 ns) are both 10 MHz, so they cannot be told apart. The engine must keep converting through the reported frequency.

**One budget was missed.** The contract gives each knob step 1.5 ms (95th percentile) from wake-up to commit. The three runs measured 1.54, 1.63 and 1.64 ms. Smoothness is unaffected, since commits still land about 7 ms before their frame. But the real explorer scene will do more work per step, so the engine must make fewer calls per step.

**Not covered:**

- tour E;
- the input contract with real clicks (P1);
- capture exclusion (P2);
- Up next (P4);
- the user's visual judgement (P5);
- a 60 fps video playing and G-SYNC off (P10);
- memory (P11).

The spike's window was also a click-through layered window, not the click-eating host the contract specifies (§5).

**What it means:** the stage architecture is confirmed for WP7a and WP8. That is: DirectComposition, motion run by the compositor, and one commit per step. The lessons in §6 are now binding implementation notes, in `DESKTOP_STAGE.md` § "[G1] Spike results".

---

## 1. What ran

| Item | Setting |
|---|---|
| Window | Primary monitor, 5120 × 1440. Ex-style `0x082800A8`: topmost, tool window, never activated, **layered + transparent (click-through)**, no redirection bitmap. This is §19.2's P1 fallback host, **not** §2.1's click-eating host `0x08200088` |
| Devices | D3D11 on the adapter that owns the monitor (RTX 4090, feature level 11_1), D2D device, `DCompositionCreateDevice3`. About 140 ms in all |
| Scene | 32:9 explorer table at k = 2. 32 synthetic 680 px covers, each with an X/Y offset visual, a `ScaleTransform` about the card centre, a **shade layer** and opacity on an `IDCompositionEffectGroup` (the spike's default opacity path). Frost from a desktop snapshot taken once at open (1/8, blurred, stretched ×8). A witness band holds W1 (a linear ramp), W2 (retargets like a card), the AR-8 swatch and diamond, and the P7 probe. The root has LINEAR sampling, SOFT borders and LAYER opacity. 608 COM objects in all |
| Motion | App A timings: X and scale 420 ms OUT, opacity 300 ms, shade 320 ms. Curves are fitted Hermite segments (worst error 0.18 px on offsets). Each detent is **one commit** of 42–58 animations and 390–577 COM calls (p50 458). Nothing runs per frame |
| Script per pacing pass | Open (1 s), then a 1 s static baseline, then three conditions of about 6.8 s each. Each condition runs 24 detents at 10/s, 24 back at 20/s, and 50 reversals at 20/s, followed by 0.5 s idle. Then P7 and close. Each condition judges **1,630 vblanks** |
| Conditions | **normal**. **burst**: a pure-Python thread busy 10 ms of every 25 ms (§6.4 stress). **chold**: a C call that holds the GIL, `Sleep(15)` through `PYFUNCTYPE` every 25 ms, standing in for `alpha_composite` on 2560 × 1440 (AR-5 / P8) |
| Witness pass | The normal condition once more. A capture thread grabs the W1/W2 rows. There are three AR-8 grabs during the baseline, and P7 is checked by strip capture. Its pacing is recorded but not judged |
| Measurement | A sampler thread with its own device, every 25 ms. It uses `DCompositionGetFrameId` / `GetStatistics` / `GetTargetStatistics` through **GIL-keeping `PYFUNCTYPE` calls** and walks every completed frame for our monitor. Each displayed frame is mapped to a vblank index from `completedStats.time`, which sits exactly on the vblank grid (R = 1.000; `presentTime` lands about 0.17 P after the grid, R = 0.968). Missed means an index step of 2 or more |
| Preconditions (all passes) | The mode reads 240 Hz from QueryDisplayConfig (signal vsync = virtual rate) and EnumDisplaySettings. `DCompositionBoostCompositorClock` returns S_OK. The baseline and every idle window show at most 5 % presents per vblank. At most 0.5 % of frame ids are lost. Each condition has at least 1,500 vblanks |

## 2. How the tables below were computed

Everything below comes from the four per-pass JSONs, not from the runner's summary text. I recomputed each figure with a separate script and then checked it against the summary.

- **Frame counts:** the pass JSONs do not keep per-frame records, so frame counts come from each pass's condition block. That block covers one continuous window per condition. I cross-checked it against the sum of the condition's three phase blocks (a10, b20, rev20). The phase windows leave small seams, so their sums run 1–5 frames lower, but every phase interval is also a single vblank step.
- **Per-detent figures:** wake → commit, commit-before-t1, t1 lead, where a GIL stall landed, and the spike's t1 margin. All are recomputed from the 98 per-detent records per condition (QPC ticks at 10 MHz).
- **Pickup classes:** the per-phase pickup blocks, summed.
- **Percentiles:** nearest-rank, the same method the spike uses.
- **Check against the summary:** the runner's `-summary.json` agrees with every recomputed total.

Terms:
- **t1**: the frame a detent's new animations begin at: `nextEstimatedFrameTime`, pushed by one period P = 4.1667 ms while it is closer than the margin.
- **Wake → commit**: from the stage thread waking for a detent to `Commit` returning, as Python timestamps it (that is, after Python has the GIL back).
- **Pickup**: the first compositor frame that started after that timestamp, and its target time relative to t1:
  - **at t1**: as planned;
  - **t1 + P**: one frame later. Harmless, because DWM samples the new curve at t1 + P and the path stays continuous (§4.6.5 item 5);
  - **later**: 2 frames or more, which gives a small step at a reversal;
  - **early**: before t1. The new animation has not begun yet, so the property sits at its start value, `old(t1)`, until t1.

## 3. Results

### 3.1 Preconditions per pass

| Pass | Mode (QDC / Enum) | DComp rate | Boost on / off | Presents per vblank in static windows | Lost frame ids | `completedStats.time` / `presentTime` R | `next − current` | Foreground unchanged | Runner |
|---|---|---|---|---|---|---|---|---|---|
| pacing 1 | 240 / 240 Hz | 239.998 Hz | S_OK / S_OK | 0.00 (baseline and 3 idles) | 0 of 6,260 | 1.000 / 0.968 | 8.14 ms | yes | ok, 26.86 s, no window left |
| pacing 2 | 240 / 240 | 239.998 | S_OK / S_OK | 0.00 | 0 of 6,264 | 1.000 / 0.968 | 8.09 ms | yes | ok, 26.86 s, no window left |
| pacing 3 | 240 / 240 | 239.992 | S_OK / S_OK | 0.00 | 0 of 6,260 | 1.000 / 0.968 | 8.25 ms | yes | ok, 26.85 s, no window left |
| witness | 240 / 240 | 239.998 | S_OK / S_OK | 0.00 | 0 of 2,755 | 1.000 / 0.975 | 7.42 ms | yes | ok, 12.24 s, no window left |

- **Refresh rate held under G-SYNC:** no phase had a frame period more than 0.5 % off 4.1667 ms, so DWM ran at a fixed 240 Hz throughout.
- **DWM counters are unusable:** `DwmGetCompositionTimingInfo(NULL).cRefresh` advanced only 0.8–0.9 times per second, even on screen.
- **Counter ratio dropped as evidence:** the present/refresh counter ratio was not used, because VRR is not known to be off.

### 3.2 Frames: did the compositor show a new frame at every refresh?

| Pass | Condition | Expected vblanks | Displayed | fps | Steps of 1 vblank | Steps of 2+ | Largest interval | §6.3 judge |
|---|---|---|---|---|---|---|---|---|
| 1 | normal | 1,630 | 1,630 | 240.0 | 1,629 | 0 | 4.167 ms | pass |
| 1 | burst | 1,630 | 1,630 | 240.0 | 1,629 | 0 | 4.167 ms | pass |
| 1 | chold | 1,630 | 1,629 | 239.9 | 1,628 | 0 | 4.168 ms | pass |
| 2 | normal | 1,630 | 1,629 | 239.9 | 1,628 | 0 | 4.167 ms | pass |
| 2 | burst | 1,630 | 1,630 | 240.0 | 1,629 | 0 | 4.167 ms | pass |
| 2 | chold | 1,630 | 1,630 | 240.0 | 1,629 | 0 | 4.168 ms | pass |
| 3 | normal | 1,630 | 1,629 | 239.9 | 1,628 | 0 | 4.167 ms | pass |
| 3 | burst | 1,630 | 1,630 | 240.0 | 1,629 | 0 | 4.168 ms | pass |
| 3 | chold | 1,630 | 1,629 | 239.9 | 1,628 | 0 | 4.168 ms | pass |
| **all** | normal / burst / chold | 4,890 each | 4,888 / 4,890 / 4,888 | ≥ 239.9 | 4,885 / 4,887 / 4,885 | **0** | 4.168 ms | pass |

- §6.3's gates were fps ≥ 0.979 × 240, p95 ≤ 1.1 P, p99 ≤ 2.02 P and max ≤ 2.02 P. Every condition in every pass passed all four, both on vblank-index steps and on the raw intervals.
- **Open phase:** its `judge.pass` is false (227.4 fps). This phase is not judged. Its 180 frames were consecutive vblanks with no miss, and the rate is low most likely because its 800 ms window is longer than the entry motion.

### 3.3 Input path: per-detent cost and when DWM picked the commit up

| Pass | Condition | Wake → commit p50 / p95 / max | Commit done before t1 | t1 lead p50 / min | Pickup early / at t1 / t1 + P / later | Spike's commit gate |
|---|---|---|---|---|---|---|
| 1 | normal | 1.06 / **1.54** / 1.87 ms | 98 / 98 | 6.99 / 6.21 ms | 0 / 98 / 0 / 0 | fail (p95 limit 1.5 ms) |
| 1 | burst | 2.45 / 3.02 / 3.07 ms | 98 / 98 | 5.70 / 1.15 ms | 0 / 94 / 4 / 0 | pass (limit 2 P = 8.33 ms) |
| 1 | chold | 16.28 / 16.78 / 17.98 ms | **64 / 98** | 0.18 / −8.68 ms | 18 / 9 / 41 / 30 | fail |
| 2 | normal | 1.11 / **1.63** / 2.33 ms | 98 / 98 | 6.91 / 5.87 ms | 0 / 98 / 0 / 0 | fail |
| 2 | burst | 2.03 / 2.54 / 4.04 ms | 98 / 98 | 5.87 / 1.65 ms | 0 / 87 / 11 / 0 | pass |
| 2 | chold | 16.68 / 17.57 / 22.23 ms | **82 / 98** | 3.71 / −9.05 ms | 3 / 35 / 46 / 14 | fail |
| 3 | normal | 1.08 / **1.64** / 2.33 ms | 98 / 98 | 6.95 / 2.48 ms | 0 / 97 / 1 / 0 | fail |
| 3 | burst | 2.51 / 3.07 / 4.53 ms | 98 / 98 | 5.45 / 1.71 ms | 0 / 92 / 6 / 0 | pass |
| 3 | chold | 16.64 / 17.55 / 18.43 ms | **68 / 98** | 2.87 / −8.66 ms | 6 / 18 / 45 / 29 | fail |
| witness | normal | 1.11 / 1.67 / 1.88 ms | 98 / 98 | 6.97 / 5.80 ms | 0 / 98 / 0 / 0 | (recorded only) |

- **Normal, pooled over 294 detents:** p50 1.09 ms, p95 **1.60 ms**, max 2.33 ms. 24 detents (8 %) were over 1.5 ms.
  - **Build:** p50 0.96 ms, p95 1.47 ms, which is about 1.9 µs per COM call.
  - **`Commit`:** p50 0.11 ms.
  - **Frame-statistics read:** about 0.01 ms.
  - **Wake lateness** (not included above): p95 0.54 ms.
  - **Cost by part of the script:** the 10/s and 20/s runs (552–577 calls) cost more than the reversals (458 calls).
- **Pickup:** 293 of 294 normal detents were picked up exactly at t1, and one at t1 + P. A retarget becomes visible about 2 P after the stage wakes: t1 − wake p50 8.04 ms, max 8.33 ms.
- **Burst:** each GIL wait is at most 1 ms (the switch interval), so every commit still landed before t1. The lead was sometimes short (min 1.2–1.7 ms), and 4–11 % of detents were picked up at t1 + P, which is continuous and invisible.

### 3.4 The GIL-hold condition (chold) in detail

The 15 ms holds changed nothing on screen (§3.2). The table below looks at where each hold landed within a detent, from the per-detent timestamps.

| Pass | GIL holds (count, p50) | Detents where the 15 ms landed after `Commit` was entered | before the wake | during the build | not hit | `Commit` entered before t1 | Spike's t1 margin p50 (normal: 1.6 ms) | t1 − wake p50 (normal: 8.0 ms) | Detents committed ≥ 2 P before t1 = "early" pickups |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 278, 15.53 ms | 80 | 0 | 0 | 18 | 98 / 98 | 14.1 ms | 16.5 ms | 18 = 18 |
| 2 | 279, 15.68 ms | 94 | 0 | 1 | 3 | 98 / 98 | 17.0 ms | 20.6 ms | 3 = 3 |
| 3 | 279, 15.63 ms | 91 | 5 (wake up to 15.9 ms late) | 1 | 1 | 98 / 98 | 16.3 ms | 17.6 ms | 6 = 6 |

What this shows:
1. **Most holds landed after the commit was already in Windows' hands.** `Commit` releases the GIL, the hog takes it for 15 ms, and Python's "commit returned" timestamp comes only when the GIL is back. `Commit` itself does not need the GIL, and the call was entered before t1 in all 294 detents. The measured "committed before t1" (65–84 %) and "picked up 2+ frames late" (14–31 %) are therefore **upper bounds** on the real lateness. The spike cannot say how much lower the truth is, and the witness pass did not run under chold.
2. **The hog's timing hid the worst case.** Its 25 ms period is phase-locked to the 50 ms and 100 ms detent grid, which is why it mostly hit after `Commit`. In real use a hold lands at a random moment, before the wake or during the build in most cases (60 % duty). Pass 3 shows that case: 5 detents woke up to 15.9 ms late, and their commits and retargets were late by that much.
3. **The adaptive margin misread GIL waits as build time.** The spike set t1's margin to `max(1.5 ms, EWMA(wake → commit) + 0.5 ms)`. Because that average absorbed the 15 ms GIL waits, the margin grew to 14–17 ms, and every chold retarget was scheduled 4–5 frames after its wake instead of about 2. When a detent then committed quickly, DWM picked it up **before** t1 (18, 3 and 6 detents: exactly the detents committed ≥ 2 P early). Such a card sits at its start value `old(t1)` until t1, a hold of 1–3 frames. The contract's fixed 1.5 ms rule (§4.6.5 item 1) does not have this flaw.
4. **Stage-thread CPU did not rise.** It was 78–85 Mcycles/s (about 1.6 % of a core) in every condition. The 20–23 % "busy" wall time under chold is waiting for the GIL, not work.

### 3.5 Witness pass: are these frames the overlay's own, and is motion on its curve?

| Check | Samples | Visible | Outside one frame of the twin | Other |
|---|---|---|---|---|
| **W1** (linear ramp, 560 px/s = 2.33 px per frame) | 810 | 810 (100 %) | 0 | Offset from the twin: mean −0.43 frame (−1.0 px), all within the capture's own timing bracket |
| **W2**, all samples (retargets like a card) | 810 | 810 | 0 | Offset from the twin: p50 −1.4 px, p95 5.9 px |
| **W2** during the 50 reversals at 20/s | 359 | 359 | 0 | Offset from the twin: p95 1.9 px, max 4.2 px |
| Capture thread | 827 grabs | — | — | Grab p50 6.5 ms, max 10.4 ms |

- **Rule:** every sample inside a judged window must sit within one frame of the twin (± 0.5 px), and at least 95 % must be visible. Both W1 and W2 passed, so the final summary has `motion_phases_pass = true`.
- **Pacing during the witness pass** (recorded, not judged): 1,630 of 1,630 frames displayed, all single-vblank steps. The capture did not disturb pacing (AR-3's worry).
- **AR-8 on screen pixels (three grabs):**
  - the ×8 two-tone swatch's longest flat run is **2 px** over a 140-level range (nearest-neighbour would give 8 px plateaus; the pass needs ≤ 4), so LINEAR is in effect;
  - each edge of the 45° diamond has a pixel **61 levels** away from both black and white, where a HARD edge gives about 0 (the pass needs ≥ 20), so SOFT is in effect;
  - this also settles the slot order of `SetBitmapInterpolationMode` (11) and `SetBorderMode` (12), which the S_OK slot test could not tell apart.

### 3.6 P7: begin-time unit

| Pass | Commit → begin | Presents between commit and begin − P | Presents during the 1 s ramp | Screen capture |
|---|---|---|---|---|
| pacing 1–3 | 499.9 ms | 0 in 118 vblanks | 240, 241, 241 in 240 vblanks | — |
| witness | 499.9 ms | 0 in 118 vblanks | 241 in 240 vblanks | 97 of 97 grabs found the probe, at rest before the begin. The first moved sample is −0.24 ms from the begin; the extrapolated onset is −4.86 ms (spike tolerance 1.5 P + 2 ms) |

- **Verdict:** `qpc_ticks_or_100ns (indistinguishable here: QPF = timeFrequency = 10 MHz)`.
- **What that means:** absolute begin times use the QPC time base, with matching scale and epoch. Nothing moved before the begin time, and motion started within about a frame of it. The extrapolated onset of 1.2 P early carries about a frame of grab-timing uncertainty.
- **What it cannot show:** on this PC a QPC tick and 100 ns are the same size, so the unit itself is still unproven.

### 3.7 Cost

| Item | Measured | Notes |
|---|---|---|
| Stage (main) thread | 78–85 Mcycles/s, handler wall time 1.6–1.7 % (normal) | at 14.4 detents/s averaged over the conditions; ≈ 1.6 % of one core |
| Sampler thread | harvest p95 0.09 ms every 25.7 ms (p50; max gap 43 ms), 31–78 ms CPU per 27 s pass | 0 lost ids in all four passes |
| Not measured | dwm.exe CPU and GPU, private bytes and dwm.exe commit (P11), open latency | the spike builds its whole tree up front: devices 137–146 ms, desktop capture 51–60 ms, scene with synthetic sprite drawing 244–250 ms. That is not §4.9's warm open path |

---

## 4. What is proven

1. **Compositor-run motion at the full 240 Hz.** DirectComposition animations built from Python ctypes, one commit per detent, ran at 240 Hz on the user's monitor with G-SYNC on for windowed mode. Across 14,666 frames, not one refresh was skipped and no frame statistics were lost. This is for the spike's 32-card 32:9 scene at 10 detents/s, at 20/s, and with 50 reversals at 20/s. The scope is **"this G1 script at 240 Hz on this PC"**.
2. **Other threads' Python work cannot disturb frame pacing.** Neither 10 ms pure-Python bursts nor 15 ms GIL-holding C calls changed a single frame.
3. **The frames are the overlay's.** The screen was otherwise quiet (0 presents in every static window), and W1 was visible and on clock in 810 of 810 samples.
4. **The retarget method is continuous on screen.** The start value comes from the twin in float64, and the begin is at `nextEstimatedFrameTime`. W2 stayed within one frame of its twin through 50 reversals at 20/s, and 293 of 294 normal detents were picked up exactly at t1.
5. **LINEAR sampling and SOFT borders are in effect** (pixel check), so their vtable slots are the right ones.
6. **Absolute begin times are on the QPC time base.** Scale and epoch match; the unit itself cannot be told at 10 MHz.
7. **The compositor-clock boost works and the rate held.** `DCompositionBoostCompositorClock` returns S_OK on and off. DWM held a fixed 240 Hz with G-SYNC windowed on (no frame period off by more than 0.5 %).
8. **Safety:**
   - all four overlays closed by themselves (`scenario_end`);
   - the foreground window never changed;
   - no host window or process was left behind;
   - teardown released every COM object (608).

## 5. What is NOT covered

| Check | Status |
|---|---|
| **Tour E** (§6.4) | Not run. That needs a source switch, Play grow and close, a Recently Added list, three runs on 32:9 and one with a forced 16:9 layout. The spike's script is detents and reversals only |
| **P1 input contract** | Not run: no user clicks, wheel or Shift. The spike's host was **layered + click-through** (§19.2's fallback). §2.1's click-eating host (`0x08200088`, no `WS_EX_LAYERED` or `WS_EX_TRANSPARENT`) has not been shown on screen at all, so its pacing is unmeasured too |
| **P2 capture exclusion** | Not run: no `WDA_EXCLUDEFROMCAPTURE` byte diff (the witness capture needed exclusion off) |
| **P3 as specified** | Partly covered. It was not the full explorer tree: no L0/L1 cover levels, no shadows or inset, no label, tab or dot changes during motion, synthetic covers only |
| **P4 Up next** | Not run |
| **P5 visual judgement** | Not done. AR-8 here is a pixel check only. LINEAR/NEAREST and SOFT/HARD A/B, L0/L1 shimmer, the sharpen pass, frost 1/8 against 1/4, and LAYER against MULTIPLY all await the user's eye |
| **P6 by eye** | The pixel witness (W2) is covered; the user's verdict on reversals was not asked |
| **P8 as specified** | A stand-in: a `Sleep(15)` hold, not a real `alpha_composite` worker |
| **P9 statistics history** | Not measured on screen. The spike harvested every 25 ms and never let history age 250, 500 or 1000 ms |
| **P10** | No 60 fps foreground video, no G-SYNC off comparison, no boost-off comparison |
| **P11 memory** | Not measured |
| P0 benches | The sprite build bench, the picker compose bench on the 32:9 table (§22 Q2) and device memory are not in this spike |
| Other | Open latency (§6.3); dwm.exe CPU and GPU; the Desktop Duplication pass (optional, not run); PresentMon; opacity through `IDCompositionVisual3::SetOpacity` (the spike animated an `EffectGroup`) |

---

## 6. Engineering lessons for the stage engine (WP7a, WP8)

1. **Frame-statistics reads must keep the GIL (`PYFUNCTYPE`).**
   - **Offline evidence:** a busy Python thread made walking 24 frames of statistics take 24.8 ms (p50; p95 34.2) when each call released the GIL, against 0.049 ms when it kept it. This is from selftest 173628; the earlier build run measured 9.3 ms against 0.05 ms.
   - **On-screen evidence:** the spike's `PYFUNCTYPE` sampler read every frame in 0.09 ms (p95) per 25 ms, under both hogs, with zero lost ids.
   - **Rule:** `DCompositionGetFrameId`, `DCompositionGetStatistics` and `DCompositionGetTargetStatistics` move from §4.7.1's GIL-releasing list to the `PYFUNCTYPE` list. They are non-blocking reads. `IDCompositionDevice::GetFrameStatistics` on the input path is the same kind of read and should follow; the spike still called it GIL-releasing, so verify it in the H5 bench.
2. **`DCompositionWaitForCompositorClock` busy-returns while the display sleeps.**
   - **Observed:** with the monitor asleep it returns `0xC01E0006` (`STATUS_GRAPHICS_PRESENT_OCCLUDED`) immediately, every time, instead of waiting a frame. On screen it returned `0x0`.
   - **Rule:** any §5 P3 loop must treat a return that is neither a clock tick nor a handle as "no clock". It then waits one P on the high-resolution waitable timer, the existing fallback 2. If the display is off, it stops the loop, because `system(sleep)` closes the overlays anyway. A loop that paces only on this call would spin a core at 100 %.
3. **Frame ids do not track refresh while the display sleeps.**
   - **Observed:** on screen, ids advanced at about 240/s (6,260 per 27 s pass). With the display asleep they ran at about 4,300–4,800/s, and DWM keeps only about 300. In offline runs that lost 1.7–2.7 % of ids at a 25 ms harvest, and 39 % at 100 ms. The 100 ms run did not record the display state, but its id rate says the display was asleep.
   - **Rule:** never count frames or vblanks from frame-id differences. Count displayed frames from the target statistics' running counters (`presentCount`, `refreshCount`), and map each one to a vblank index from `completedStats.time` on the vblank grid. Record lost ids as "unknown", never as "missed", and invalidate an episode above 0.5 % unknown. Harvest at 250 ms (§6.1) only while the display is on; stop harvesting while it is off.
   - **Also:** `DwmGetCompositionTimingInfo(NULL).cRefresh` advanced only 0.8–0.9 times per second on screen. It cannot be §6.2's per-frame `refresh_count`; map presents to vblank indices by time.
4. **The wake-to-commit budget is tight.**
   - **Observed:** §6.3's 1.5 ms p95 was missed in every pass (1.54 / 1.63 / 1.64 ms; pooled 1.60 ms; 8 % of detents over). The step made 390–577 COM calls at about 1.9 µs each. WP8's real tree (L0/L1 crossfades, shadows, labels) adds calls.
   - **Rule:** batch and cut COM calls. The builder:
     - retargets only visible elements whose target changed;
     - fits curves to §4.6.2's bound (0.5 px, not the spike's tighter 0.25 px);
     - reuses cached normalised segment tables;
     - binds scale X and Y to one animation object;
     - creates no objects on the hot path, only pooled ones;
     - makes the whole event one `Commit`.

   The H5 bench keeps the 1.5 ms p95 gate at 20 detents/s on the 32:9 table. Smoothness has slack: normal commits landed about 7 ms before t1.
5. **Never hold the GIL for more than about 2 ms on any thread while an overlay can take input** (the chold result).
   - **Observed:** holds of up to 1 ms (the burst hog, preempted at the switch interval) cost 1–1.5 ms per detent, and every commit still landed before t1. 15 ms holds made measured commits late in 16–35 % of detents, and delayed a detent's wake by up to 15.9 ms when the hold came first.
   - **Rule:** anything that holds the GIL in one C call for longer runs in a **worker process**, or in chunks that each stay under §4.7.3's 1 ms design limit. That covers `alpha_composite` on large images, whole-document JSON and XML parses, and any PIL operation not on §4.7.3's measured GIL-releasing list.
   - **Input path:** keep the GIL through everything before `Commit`, including the statistics read, so that `Commit` is the first GIL-releasing call. A GIL grab can then delay only what comes after the commit. Stamp FrameStats `work_ms` knowing that a timestamp taken after the GIL returns overstates it under contention.
6. **Keep §4.6.5's fixed t1 rule.** t1 = `nextEstimatedFrameTime`, plus P while it is less than 1.5 ms away.
   - **Observed:** the spike's `max(1.5 ms, EWMA(wake → commit) + 0.5 ms)` absorbed GIL waits and grew to 14–17 ms. That pushed retargets 4–5 frames out, and caused "early" pickups where a card holds `old(t1)` for 1–3 frames.
   - **Rule:** an adaptive margin may use only the build's own CPU time, excluding GIL waits, and never exceeds 1 P.
   - **Latency:** on screen, t1 sits about 2 P (8.0 ms p50) after the wake. This belongs to the §6.3 latency budget.
7. **The retarget method is proven; keep it.**
   - **Start value:** the old animation's value at t1, evaluated in Python in float64 from the **same fitted segments** DWM runs (the twin).
   - **New animation:** from that value to the new target, over the full duration, with `SetAbsoluteBeginTime(t1)`.
   - **Animation objects:** two per property, alternated, so a bound animation is never modified. A target equal to the current one is skipped.
   - **Evidence:** on screen, 293 of 294 normal detents were picked up at t1, and W2 stayed within one frame through 50 reversals at 20/s. In the dry run, the largest jump as DWM sees it (float32) was 0.00048 px over 5,173 retargets.
8. **P7 units.** Begin times are on the QPC time base (scale and epoch), but on this PC QPC ticks and 100 ns cannot be told apart, because QPF = `timeFrequency` = 10 MHz.
   - **Rule:** always convert through `timeFrequency`; never hard-code 10 MHz. Assert `timeFrequency == QueryPerformanceFrequency` at device creation, and use §4.6.5 item 7's fallback (no absolute begin, a leading hold instead) if they differ.
9. **The shared shade surface is a deviation from §4.5.**
   - **What the spike did:** it drew every card's shade from **one shared 680 px opaque surface**, not a 1 × 1 surface stretched by the visual's transform. Under LINEAR sampling, a stretched 1 px surface may blend in neighbouring texels of the surface atlas and fringe the edges. The swatch and diamond tests did not examine this.
   - **Rule:** WP7a/WP8 use the proven shared solid (one surface per colour and size class, about 1.8 MB for a 680 px one) until a pixel test shows the 1 × 1 stretch is clean. P5 still decides by eye.
10. **Close the gap between the spike's setup and the contract's.** The spike paced on a layered click-through host and animated opacity through an `EffectGroup`. WP7a's first on-screen check (with the user's go-ahead) repeats one normal pacing pass, with W1, on §2.1's click-eating host with `IDCompositionVisual3::SetOpacity`. Otherwise it adopts the spike's proven pair.
11. **Reuse the spike's measurement in `stage.metrics()`.**
    - a vblank index from `completedStats.time`, which sits on the grid (R = 1.000); `presentTime` lands about 0.17 P after it, with jitter (R = 0.97);
    - missed = an index step of 2 or more, with raw intervals as a cross-check;
    - pickup classes per event;
    - a quiet-baseline gate for any supervised proof, since frame statistics are display-wide;
    - boost S_OK recorded per episode.

## 7. Files

- `app\diagnostics\g1-spike-onscreen-20260925-174737-pacing1.json`, `-pacing2.json`, `-pacing3.json`, `-witness.json` (+ `.log`), `-summary.json`
- `app\diagnostics\g1-spike-selftest-20260925-173628.json` (the gating selftest; the offline GIL bench)
- `app\diagnostics\g1-spike-selftest-20260925-163928.json`, `-dev3.json`, `-dev4.json` (offline runs with the display asleep: compositor-clock return, frame-id rate, lost ids)
- `work\spike_dcomp\dcomp_spike.py`, `curves.py`, `winapi.py`, `run_spike.py`
- `app\DESKTOP_STAGE.md` § "[G1] Spike results" (the binding notes)

---

## Verification

An independent check, made on 2026-09-25. It read the four per-pass JSONs, the runner's `-summary.json`, the offline selftests listed in §7, and the spike source (only to see how each field is computed). Every figure was recomputed from the raw per-detent and per-phase records. Nothing above this section was changed.

**Verdict: proven, within the stated scope.** Compositor-run swipes ran at 240 Hz on the user's screen. DWM showed a new frame at every refresh in all 9 condition runs, under all three loads, and the pixel witness confirms the frames were the overlay's own and on the curve. The proof covers the spike's scene on the spike's host: layered and click-through (`0x082800A8`), with opacity through an `EffectGroup`. It does not extend to:
- the contract's click-eating host or `Visual3` opacity (G1-10 still has to run);
- continuous retargets under the 15 ms GIL hold. Frames stayed at 240 Hz there, but the swipe path was probably not continuous (correction 1);
- anything listed in §5.

### Confirmed

The recomputation found no mismatches against the spike's own per-phase blocks or the runner's summary.

- **Frames:**
  - 4,888 / 4,890 / 4,888 displayed for normal / burst / chold, so 14,666 of 14,670.
  - Every step was 1 vblank, and the largest raw interval was 4.168 ms.
  - The §6.3 judge and its raw cross-check pass in all 9 runs.
  - Phase sums run 1–5 frames lower, as stated.
  - The 1,629 rows have no interior gap. The missing frame sits at a window edge, since each window is 1,630.0 P long.
- **Preconditions:** all as in §3.1.
  - 240 Hz both ways in all four passes, and the boost returned S_OK on and off.
  - 0 presents in every static window, 0 lost ids and 0 read errors.
  - R = 1.000 for `completedStats.time` and 0.968–0.975 for `presentTime`.
  - The foreground never changed, 608 objects were released, and no window was left behind.
- **§3.3 table:** every cell matches, including wake → commit, commit before t1, t1 lead and the pickup classes.
  - **Normal, pooled:** p50 1.09 ms, p95 1.60 ms, max 2.33 ms; 24 of 294 detents over 1.5 ms.
  - **Parts:** build p50 0.96 ms (p95 1.47 ms), `Commit` p50 0.11 ms, statistics read 0.007 ms, wake lateness p95 0.54 ms.
  - **Timing:** t1 − wake p50 8.04 ms, max 8.33 ms.
- **§3.4 table:**
  - Hold placement 80/0/0/18, 94/0/1/3 and 91/5/1/1.
  - `Commit` was entered before t1 in all 294 detents.
  - Margin p50 14.1 / 17.0 / 16.3 ms, recomputed by replaying the spike's EWMA over the detent records.
  - t1 − wake p50 16.5 / 20.6 / 17.6 ms.
  - Early pickups 18 / 3 / 6, each equal to the number of detents committed at least 2 P before t1.
- **Stage CPU:** 78–85 Mcycles/s in every condition. Chold "busy" time was 19.6–23.5 %.
- **Witness pass:**
  - W1: 810 of 810 samples visible, 0 outside the band, mean lag −0.43 frame.
  - W2: 810 of 810, and 359 of 359 during the reversals. 827 grabs in all.
  - AR-8: a 2 px plateau over 140 levels, and 61 levels on the diamond edges, in all three grabs.
- **P7:**
  - 499.9 ms from commit to begin, with 0 presents in the 118 vblanks before it.
  - 240, 241, 241 and 241 presents during the ramp.
  - The probe was found in 97 of 97 grabs, and `timeFrequency` = QPF = 10 MHz.
- **Offline runs:**
  - GIL bench: 24.8 ms (p95 34.2 ms) against 0.049 ms in selftest 173628, and 9.3 ms against 0.051 ms in 163928.
  - Compositor-clock wait: `0xC01E0006` in 163928 and dev4 with the display occluded, `0x0` on screen.
  - Lost ids: 1.7 % (163928), 2.7 % (dev4) and 38.8 % (dev3).
- **Source:** the spike's files still hash to `56a89f35…db6e`, and selftest 173628 passes 53 of 53 gated checks.

### Corrections

1. **Chold: the overstatement cuts both ways** (§3.4 item 1, the plain-words bullets, G1-6).
   - **What the report gets right:** the "late" figures are upper bounds, because the 15 ms hold usually landed after `Commit` was entered.
   - **What follows from the same premise:** `Commit` does not need the GIL and takes about 0.11 ms. So in the 265 detents where the hold landed after it, the commit reached DWM about 6.6–20 ms before t1 (p50 15.3–19.5 ms), not the −9 to +5 ms that was measured. That makes the "early" figures lower bounds.
   - **What the spike's own data say:** in each pass the early count equals the number of detents committed at least 2 P before t1 (18, 3, 6). Normal detents committed 1.4–1.8 P before t1 were all picked up at t1.
   - **Estimate:** applying that rule, about 283 of 294 chold detents (96 %) were probably picked up 2–3 frames early. The card jumps ahead to `old(t1)` and holds there. The measured count was 27 (9 %).
   - **Caveat:** this is an estimate. The spike has no C-side timestamp for when `Commit` returned, and W2 did not run under chold.
   - **What it means:** under a 15 ms hold the damage probably moved from "late" to "early jump and hold" rather than shrinking. The cause is still the EWMA margin, so G1-6 fixes it, and G1-5 still covers holds that land during the build. The "3–18 %" in G1-6 is a lower bound.
2. **Not every chold retarget was 4–5 frames out** (§3.4 item 3; "every step" in the plain words; G1-6).
   - 259 of 294 (88 %) were at least 3.5 P after the wake.
   - The other 35 sat at 2–3 P: 23, 6 and 6 per pass. They include the first 5–6 chold detents of each pass, while the EWMA climbed. Pass 1 has more because detents the hold missed let the EWMA fall again.
3. **The 5 late wakes in pass 3 had their retargets pushed further than their wake** (§3.4 item 2).
   - The wakes were 15.7–15.9 ms late, and the commits landed 16.6–17.4 ms after due, as stated.
   - But t1 landed 33.4–33.5 ms after due, against 8.4 ms in normal, because the inflated margin added about 9 ms. The retargets were therefore about 25 ms (6 frames) late, not 15.9 ms.
   - All 5 were then early pickups, committed 3.85–4.05 P before t1.
4. **The DWM counter does not advance slowly; it advances once per read** (§3.1, §6.3, G1-3).
   - `cRefresh` and `cFrame` went up by exactly 1 in all 56 phases, whether the phase lasted 0.36 s or 3.0 s. The "0.8–0.9 per second" is just 1 divided by the phase length.
   - The struct reads sensibly up to `qpcRefreshPeriod` (10,000,000 / 41,667, or 4.1667 ms). So this looks like how Windows behaves, not a binding error.
   - The conclusion stands: it is not a refresh counter.
5. **Percentiles** (§2): p50 is the median (`statistics.median`, which averages the middle two of 98 values). Only p95 and p99 are nearest-rank. Every table value matches the spike's method; only the description is wrong.
6. **Frame-id rate while the display sleeps** (§6.3, G1-3): the three sleep runs give 4,650–4,810 ids per second, counting known and lost ids over `animation_s`. The "4,300" end of the stated range is not reproduced. This does not change the rule.

### Clarifications

In each of these, the figures are right but the wording claims a little more than they show.

- **Witness tolerance:** "within one frame of the twin" means within the twin's range over the grab's own time bracket, widened by one P on each side.
  - Grabs took 5.8–10.4 ms, so at the median the accepted band is about 3.5 frames wide (about 8 px for W1).
  - This proves the frames were the overlay's own and on the curve. It does not prove per-frame pacing, which rests on the frame statistics.
- **P7:** the frame statistics show no present before begin − P. The strip capture's first moving sample was stamped 0.24 ms before the begin, and the extrapolated onset 4.9 ms before it.
  - Both are within grab-timing error. They also fit a screen grab reading a frame DWM composed ahead of its vblank.
  - The precise statement is "nothing moved before begin − P", not "before the begin".
- **Per-step budget by phase:**
  - The reversal detents (about 458 calls) met the 1.5 ms p95 in every pass (1.32–1.46 ms).
  - The 10/s and 20/s detents (medians of 552 and 577 calls, 390–577 in all) missed it in 7 of 8 phase runs (1.54–1.91 ms). This supports G1-4.
  - "About 1.9 µs per call" is build wall time per call, including the Python-side work, not the cost of the COM call alone.
- **Open phase:** its window ends where the last card tween was scheduled to end: 800 ms, the a = 8 card's 360 ms delay plus its 440 ms entry. All 10 missing frames come at the tail, after 180 consecutive frames. That fits the "window longer than the visible entry" explanation.
- **Not in the raw data:**
  - The monitor model (Odyssey G93SC) and the G-SYNC setting come from the user. The JSON only records `gsync_user_reported: windowed`.
  - The claim that the first 1,437 lines of `DESKTOP_STAGE.md` are byte-identical to before was not checked, because no earlier copy exists.

### Follow-ups for `DESKTOP_STAGE.md` § "[G1] Spike results"

These were not edited here.

- **G1-6 (line 1490):** "3–18 %" is a lower bound. The chold early-pickup share was probably about 96 %.
- **G1-6:** "4–5 frames" holds for 88 % of chold detents, not all of them.
- **G1-3 (line 1474):** `cRefresh` advances once per read, not "under once a second".
