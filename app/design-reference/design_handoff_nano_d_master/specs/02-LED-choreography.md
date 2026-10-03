# Handoff: Nano_D++ — LED colours and ring choreography ("Warm · alive")

## Overview
New LED behaviour for the Nano_D++ knob's 60-segment RGB ring and its four backlit buttons.
- **At rest** the ring and buttons glow dim and warm, and breathe slowly.
- **On touch** everything rises smoothly to full warm.
- **Colour** appears only where it means something (confirm, fail, near max, changed elsewhere, app or album). When it does, it is at full brightness and full saturation.
- **Motion:** every state change is choreographed from four primitives, Spark, Wave, Wash and Breath.

This spec supersedes the white and "targeted colour" LED specs. Screens, haptics and button meanings are unchanged.

## About the design files
These are **design references built in HTML**. They are not production code. To open them, serve the folder over HTTP (`python -m http.server`) and open `Ring Choreography v2.dc.html`. The page is a live, interactive knob: drag or scroll it, ←/→ turn it, and 1–4 press the buttons. Every moment is listed on the right and can be replayed, at 1×, ½× or ¼× speed.

Implement it in the **firmware** (C, on the existing LED driver), not in HTML. The logic to port lives in two places:
- `knob-model.js` → `finishAlive()`: the per-state **targets** (colour and level per segment and per button).
- `Ring Choreography v2.dc.html` → the logic class: `draw()` handles damping, the effect queue, tone mapping and rendering; `detect()` maps events to moments. Treat the canvas drawing as a stand-in for writing the LED buffer.

## Fidelity
**High-fidelity.** Colours, levels, curves and durations are final targets. Tune brightness on real hardware only by adjusting the global drive scale, not the relative levels.

---

## 1. Architecture (firmware)
```
state machine ──targets──▶ LED task (60 fps) ──▶ WS2812/driver
      │                        ▲
      └──events (push)─────────┘  effect queue (≤ 8)
```
- **LED task:** owns `float seg[60].{r,g,b,a}` and `btn[4].{r,g,b,a}`.
- **Every frame:**
  1. Read targets from the state machine.
  2. Damp each segment toward its target.
  3. Compute masks and overlays from the active effects.
  4. Compose: `out = tone(base × mask × duck + overlay)`.
  5. Apply gamma and the global drive scale.
  6. Write the buffer.
- **The state machine never animates.** It sets targets and pushes events (`TICK`, `BOUND`, `WAKE`, `OK`, `FAIL`, `SKIP`, `PLAY`, `PAUSE`, `EXT`, `MODE`, `SWITCHED(color)`, `OFFLINE`, `ONLINE`).
- **Easing:** use a 64-entry lookup table per curve:
  | Name | Formula |
  |---|---|
  | `eo` (ease-out cubic) | `1 − (1 − u)³` |
  | `eio` (ease-in-out cubic) | standard |
  | `gs(x, w)` (gaussian) | `exp(−x² / 2w²)` |
  | `bump(t, a, b)` | `sin(π·(t − a)/(b − a))` on [a, b], else 0 |
- **Geometry:** segment 0 is at 12 o'clock and indices run clockwise. The volume arc runs from segment **35** (7 o'clock) clockwise for **50** segments to 25 (5 o'clock), at 2 % per segment. `cd(i, j)` is the signed circular distance in −30…29.

## 2. Palette (sRGB, before gamma)
| Role | RGB | Use |
|---|---|---|
| Warm (base) | **follows time of day** (see §6); 20:00 ≈ `255,158,76` | all non-semantic light |
| Hot | warm mixed 50 % toward white | spark heads, detent sparks |
| Confirm green | `0,255,98` | Play / Switch buttons, success, paused Play breath |
| Fail red | `255,24,0` | Cancel, failure, volume ≥ 90 % |
| Amber | `255,118,0` | volume 80–90 %, offline marks |
| Elsewhere blue | `40,140,255` | volume changed from Sonos |
| App / album | dominant colour, re-saturated | Windows and Recently Added landmarks, cursor, tint, wash |

**Re-saturation** (app and album colours):
1. Let `mn` be the smallest channel.
2. For each channel: `c' = max(0, c − 0.75·mn) / (max − 0.75·mn) · 255`.
3. If `max − min < 30` (grey or black icons), fall back to warm.

Dominant-colour extraction is `dominant()` in `knob-model.js`, computed on the companion side and sent with the list.

## 3. Levels (0–1 of the drive scale)
| | Landmark (L1) | Body (L2) | Cursor (L3+) | Lit button | Disabled button |
|---|---|---|---|---|---|
| **Awake, warm** | 0.30 | 0.62 | 1.00 | 0.70 | 0.14 |
| **Awake, semantic colour** | 0.45 | 1.00 | 1.00 | 1.00 | — |
| **Resting** (all warm) | 0.05 | 0.10 | 0.16 | 0.12 | 0.04 |

Resting values are then multiplied by the **time-of-day brightness factor** (§6) and the **breath** (§5).

**State targets** (`finishAlive`):
- **Volume:** below 80 % is warm; 80–90 % amber; ≥ 90 % red. The endpoint takes the colour of its position.
- **Paused on Home:** button 1 (Play) turns green.
- **Windows:** landmarks and cursor take the app colour. Cancel is red, Switch green, the rest warm.
- **Recently Added:** landmarks and cursor take the album colour; Play is green.
- **Tracks:** all warm.
- **Offline:** 12 amber marks, every 5th segment, at 0.12 (0.15–0.5 pulsing while reconnecting). Buttons are off.

## 4. Damping (per segment, first-order: `a += (target − a)·(1 − e^(−dt/τ))`)
| Situation | Rising τ | Falling τ |
|---|---|---|
| Awake, target ≥ 0.9 (cursor) | 10 ms | 140 ms |
| Awake, other | 55 ms | 140 ms |
| Resting | 400 ms | 700 ms |
| Buttons, awake | 40 ms | 160 ms |

- **Colour** follows at τ = 70 ms. It snaps if the segment was dark (a < 0.02).
- **Sleep:** 5 s after the last input, or 3.2 s after an external volume change. Sleep never starts while an action is pending or a flash is showing; re-check every 1 s.
- **Wake:** the first detent or press wakes the knob **and** performs its action.

## 5. Composition rules
- **Tone map (soft knee):** let `mx = max(r, g, b)`. If `mx > 0.78`, scale all three channels by `(0.78 + 0.22·(1 − e^(−(mx − 0.78)/0.22))) / mx`. This keeps hue and saturation instead of clipping to white.
- **One voice at a time:** when a new **foreground** effect starts, each running one fades out linearly over **120 ms**.
  - Foreground: boot, offline, confirm, fail, skip, play, pause, elsewhere, wash.
  - Touch effects (tick, bound, wake, reveal, press) are not foreground and can stack.
- **Duck:** while a foreground effect (other than boot or offline) runs, multiply the base by `1 − 0.35·sin(π·u)·amp`.
- **Breath:**
  | Condition | Multiplier |
  |---|---|
  | Resting | `1 + 0.40·sin(2π·t / 5200 ms)` |
  | Offline | `0.60 + 0.40·sin(2π·t / 2600 ms)` |
  | Paused Play button (awake) | `0.55 + 0.45·(0.5 + 0.5·cos(2π·t / 2600 ms))` |
- **No brightness modulation above 3 Hz, anywhere.**

## 6. Time of day
Interpolate linearly between these keyframes on the local clock (hour → RGB, resting-brightness factor):
| Hour | RGB | Brightness |
|---|---|---|
| 00:00 | 255,118,34 | 0.55 |
| 05:00 | 255,128,44 | 0.60 |
| 08:00 | 255,192,134 | 0.95 |
| 13:00 | 255,204,156 | 1.00 |
| 17:00 | 255,180,110 | 1.00 |
| 20:00 | 255,158,76 | 0.85 |
| 22:30 | 255,132,46 | 0.65 |
| 24:00 | 255,118,34 | 0.55 |

The companion sends the local time on connect and every 10 minutes. The brightness factor applies only while resting.

## 7. Moments
Notation: `u` = progress 0–1, `ms` = elapsed time, `at` = cursor segment at trigger. `comet(head, dir, len, c0, c1, a)` places gaussian dots of width 0.7 at `head − dir·k` for k = 0…len, with alpha `a·(1 − k/(len+1))^1.7`; the head uses c0 and the tail c1.

| Moment | Trigger | Dur | Recipe |
|---|---|---|---|
| **Coming online** | `ONLINE` / power-up | 2800 | See steps below |
| **Going offline** | `OFFLINE` | 1800 | See steps below |
| **Wake** | first input while resting | 520 | Hot, both ways from `at`: front `d = eo(u)·30`, alpha `0.32·(1−u)·gs(\|cd\| − d, 3)` |
| **Spin trail** | `TICK` | 180 | Hot spark `0.45·(1−u)²` at `at`, plus a warm tail of `len` segments behind (see below) |
| **End stop** | `BOUND` (cursor didn't move) | 460 | Cursor flare `0.8·(1−u)²` in the cursor colour; for k = 1…4, segment `at − dir·k` flares `0.5·(1 − k/5)·bump(ms, (4−k)·30, (4−k)·30 + 260)`, so the light compresses into the bound |
| **Working** | while any action is pending | 1.4 s/lap | `comet(t/1400·60, +1, 8, hot, warm, 0.5)`, stopping the instant the answer arrives |
| **Confirmed** | `OK` without an app/album colour | 900 | Green fronts from `at`: `d = eo(u/0.8)·30`, alpha `0.9·(1 − 0.5u)·gs(\|cd\| − d, 1.5)`, trail `0.16·(1−u)^1.5` inside the front; a spark at `at + 30` (green mixed 30 % toward white) `0.8·bump(ms, 560, 900)` |
| **Head shake** | `FAIL` | 700 | See below |
| **Play** | playback confirmed | 760 | Arc mask `clamp((u·1.15·(n+1) − k)/2.5)` for arc index k; hot spark at the leading edge `0.75`, fading over the last 15 % |
| **Pause** | pause confirmed | 860 | Arc mask `1 − 0.8·gs(k − pos, 3.5)`, with `pos = n − eio(u)·(n+6)`. Then the Play button breathes green |
| **Skip** | `SKIP(dir)` | 640 | `comet(at + dir·60·eo(u), dir, 10, hot, warm, 0.85·(1 − u³))`: clockwise for Next, anticlockwise for Previous |
| **Changed elsewhere** | `EXT(from, to)` | 1000 | Blue gaussian (w 1.2) travels `from → to` by `eio(u/0.7)`, alpha 0.9, fading after u 0.7; then settles at `to`, `0.5·bump(ms, 600, 1000)` |
| **Near max** | continuous, Home, awake, vol ≥ 90 % | — | Each red segment × `0.72 + 0.28·(0.5 + 0.5·sin(t/(380 + (i·97 mod 260)) + 1.9i))`, i.e. independent slow ember cycles |
| **Song hand** | continuous, resting, Home, playing | 1 lap/song | One hot mote (w 0.75), alpha `0.26 × ToD brightness`, at segment `progress·60`, starting from 12 o'clock |
| **Mode change** | `MODE` | 450 | Mask `clamp((ms − \|cd(i,0)\|·8)/130)`: landmarks unfold from the top |
| **Ambient tint** | continuous, Windows/Recent, awake | — | Unlit segments get +0.06 of the cursor's app/album colour, smoothed τ 220 ms as you turn |
| **Switched · now playing** | `SWITCHED(color)`: Windows switch or album start | 1100 | See below |
| **Button press** | any press | 220 | That button's strip +0.6·(1−u)² hot |

Spin trail detail: `len = round(clamp((vel − 4)/14)·7)`, where `vel` is detents/s smoothed as `0.55·old + 0.45·new` and reset after a 400 ms gap. Each tail segment has alpha `0.38·(1 − k/(len+1))^1.5·(1−u)`.

**Coming online** (2800 ms):
1. **0–1000 ms:** `comet(60·eio(ms/900), +1, 14, hot, warm, 0.95)`, one lap, fading over 900–1000 ms.
2. **850–1450 ms:** the whole ring gets +0.22 warm × `bump`.
3. **From 1250 ms:** the state draws in along its path. On Home the order is `md(i − 35)`; otherwise it is `2·|cd(i, 0)|`. The mask is `clamp((ms − 1250 − order·11)/160)`.
4. **Buttons:** they light left to right at 1850 + 100·j ms, each with a 0.45 hot kick.
5. **Screen:** the LCD fades up from black over 1600–2200 ms.

**Going offline** (1800 ms):
1. Freeze a snapshot of the ring at the trigger.
2. Each segment fades out over 110 ms, starting at `80 + (60 − md(i − at))·10` ms, so the light drains anticlockwise into the cursor.
3. The cursor holds as an ember: it fades over 700–1200 ms, with a +0.35 warm `bump` over 500–1250 ms.
4. Buttons go dark right to left, at 120 + (3 − j)·80 ms.
5. The amber offline marks then fade in from the top, from 1250 ms, 12 ms per segment of distance.

**Head shake** (700 ms):
- A red gaussian (w 0.9) sits at `at + 1.6·sin(2π·3.2·t)·(1 − eo(u))`, with alpha `0.95·(1 − u²)`.
- The base within ±3 of the cursor dims by `0.6·sin(πu)`.
- The shake is movement, not brightness flashing.

**Switched · now playing** (1100 ms):
- The colour floods out from `at`, reaching the far side at 420 ms: `d = eo(ms/420)·31`, alpha 0.65 inside the front, plus a 0.45 gaussian edge that fades as the flood completes.
- It holds until 520 ms, then fades back to warm (`eo`, 580 ms).
- The base dims 55 % during the wash, and button 4 is tinted 0.55.

## 8. Event mapping (from `detect()`)
- **Turning:**
  - Rotation that doesn't move the cursor gives `BOUND`; otherwise `TICK`.
  - The first input while resting also fires `WAKE`.
- **Mode:** any mode change fires `MODE`.
- **Success flash:** fires `SWITCHED(cursor colour)` if the previous mode was Windows or Recently Added and the cursor wasn't warm; otherwise `OK`.
- **Failure flash:** fires `FAIL`.
- **Playback:** a queue index change fires `SKIP(sign)`. A confirmed change of `playing` on Home fires `PLAY` or `PAUSE`.
- **External:** `ext` rising fires `EXT(prev cursor, new cursor)`.
- **Connection:** `conn` leaving ok fires `OFFLINE`; returning to ok fires `ONLINE`.

## 9. Performance budget
- **Frame rate:** 60 fps, at most 8 effects in the queue.
- **Per-frame cost:** about 60 × (damping + masks + a few gaussians). A gaussian splat covers only ±3w segments.
- **Memory:** 60 × 4 floats for the ring plus 4 × 4 for the buttons, and the effect structs (type, t0, at, dir, colour, n, len, kill time). The offline effect also keeps a 60 × 3 snapshot.
- **Output:** apply gamma 2.2 (or the driver's LUT) and a global drive scale after tone mapping. The hardware current limit must cover all 60 segments at full warm.

## Files
- `Ring Choreography v2.dc.html` — the interactive choreography reference (primary).
- `knob-model.js` — the state machine plus `finishAlive()` (LED targets) and `dominant()` (colour extraction).
- `Knob Face.dc.html` — the LCD renderer used inside the reference.
- `support.js`, `_ds/…`, `assets/…` — needed only to open the reference; covers and icons are placeholders.
