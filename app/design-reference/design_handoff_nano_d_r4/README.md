# Handoff: Nano_D++ r4 — motion, haptics and sound

**Read this first, top to bottom.** It walks you (Claude Code) through every change since the last build you implemented (r3.1: spaces IA, Home Assistant, arc breadcrumbs, Navigator). r4 changes **how the knob moves, feels and sounds**. Screens, button maps and copy are the r3.1 ones unless listed here.

Targets:
- **Firmware** (`katbinaris/NanoD_RatchetH1`, branch `feat/firmware-esp-idf-quadra`, `NanoDepsidf/src`): LVGL screen motion, LED task easing, haptic contexts in `control_task.c`, click sounds in `i2s_task.c`.
- **Companion** (Windows): Navigator motion, settings for reduced motion / reduced haptics / sound.

The HTML files are **design references**, not code to ship. Recreate the behaviour in LVGL / C / the companion stack. All numbers below are the spec; the prototypes show them running.

---

## 0. Files and how to look at them
| File | Use it for |
|---|---|
| `prototypes/Knob IA Prototype r3.1.dc.html` | **The build reference.** Every screen with the r4 motion, walls and sound proxy. Press **Play motion tour** (red, header) for a 30 s scripted walk through everything below |
| `prototypes/Nano D Haptic Map.dc.html` | Per-context haptic spec: force-vs-angle curve, pulse timeline, sound proxy, reduced haptics. **Full map** tab = the table in §5 |
| `prototypes/Nano D Motion Lab.dc.html` | Every animation with its Today / A / B / C variants, scrubber and spec cards. Recommended variants are marked ★ |
| `prototypes/motion-lab.js` | Exact motion maths: springs, easings, ring helpers, every animation as a pure function of time |
| `prototypes/haptic-lab.js` | Exact haptic contexts as data: feel, density, Kp/Kd, ends, events, sound, reduced fallback |
| `reference/` | Earlier READMEs (r3, r3.1, motion lab, haptics r1, r4 overview) for context |

Run: `cd prototypes && python -m http.server`, open the `.dc.html` files. Controls: drag around the knob / mouse wheel / ←→ turn; keys 1–4 press the buttons; hold 1 (0.6 s) = Home; hold 4 (1.0 s) = secondary action. **Sound proxy** toggle = approximate audio for every haptic event.

---

## 1. Implementation order (suggested)
1. **LED easing + blooms** (§3.4). Small, global, removes every flicker.
2. **Haptic tokens** (§4) as named presets in `control_task.c`; context switching with `feel.fade`.
3. **Walls everywhere** (§4.3) + the screen stretch (§3.3).
4. **Sound mapping** (§6) through `audio_trigger_click()`.
5. **Screen motion** (§3.1–3.2) in LVGL.
6. **Icon motion** (§3.2) — the only part needing new assets (frame strips, §3.5).
7. **Settings**: reduced motion, reduced haptics, sound (§7).
8. Verify against the **acceptance checklist** (§9).

---

## 2. Principles (what every change serves)
1. **Input first.** Every action fires on its press / release / detent. Motion, LEDs, haptics and sound acknowledge; none of them delay input or queue behind each other. A fast spin retargets motion, it never stacks it.
2. **Clicks for choices, soft steps for values, fluid for time and space.**
3. **Every limit bounces.** Physical wall + screen stretch + end LEDs, released together.
4. **You can feel which job the knob has.** Volume is light, brightness is heavier, lists click, fine values click higher.
5. **Screens push, text settles, icons bounce, the ring leads.**
6. **LEDs never step.** Eased on the LED task; emphasis is a bloom, never a flash.
7. **One confirmation per action; thumps are rare; holds charge silently.**

---

## 3. Motion

### 3.1 Motion tokens (springs)
Mass 1. `k = (2π / response)²`, `c = 4π · damping / response`. Settle = within 0.4 %.

| Token | response · damping | k · c | Settles | Overshoot | Used for |
|---|---|---|---|---|---|
| `SPRING.snap` | 0.36 s · 0.72 | 304.6 · 25.1 | 416 ms | 3.8 % | Screen push, big value in, list glide, crumb |
| `SPRING.soft` | 0.46 s · 0.82 | 186.6 · 22.4 | 544 ms | 1.1 % | Text settling (title/artist back after a reveal), status lines |
| `SPRING.pop` | 0.42 s · 0.52 | 223.8 · 15.6 | 624 ms | 14.8 % | Icons only: press spring-back, landing pop, idle row |
| `SPRING.wall` | 0.34 s · 0.42 | 341.5 · 15.5 | 648 ms | 23.4 % | The screen's rebound after a wall push |
| `E.out` | cubic-bezier(0.22, 1, 0.36, 1) | — | — | — | All fades in |
| `E.in` | cubic-bezier(0.4, 0, 1, 1) | — | — | — | All fades out, press-down |
| `E.io` | cubic-bezier(0.65, 0, 0.35, 1) | — | — | — | Ring sweeps, dimming, bloom fall |

**LVGL implementation.** LVGL 9 has no spring animator. Either (a) run a semi-implicit Euler step per UI tick (`a = k·(target − x) − c·v; v += a·dt; x += v·dt`), which also makes retargeting free, or (b) bake each token into a 32–64-sample lookup table and use it as a custom `lv_anim_path_cb_t`. (a) is preferred for anything that follows the knob (list glide, values); (b) is fine for fire-and-forget transitions. The prototype uses CSS `linear()` curves sampled from these exact springs.

### 3.2 Animation catalogue (what moves, by how much, on what curve)
All distances are LCD pixels on the 240 × 240 screen.

| # | Moment | Trigger | Choreography | Curve | Where to see it |
|---|---|---|---|---|---|
| M1 | **Screen push** (depth) | Any space / level change (buttons 1–3, hold 1) | Content layer enters from **28 px** in the depth direction (deeper = from the right) at **97 %** scale, springs to 0 / 100 %; opacity 0 → 1 in 240 ms. Old content is replaced on the same frame | `SPRING.snap` · fade `E.out` | Tour: "Push into Music" |
| M2 | **Big value reveal** | First detent on a value (volume, brightness, temperature, seek) | Text layer: out 130 ms `E.in`, 12 px up. Big layer: from **14 px** below at **94 %** scale, 40 ms delay, fade 180 ms | `SPRING.snap` | Tour: "Turn: volume reveal" |
| M3 | **Big value exit** | 1.4 s after the last detent | Big layer out 130 ms `E.in`; text layer back from 12 px above, 90 ms delay, fade 260 ms | `SPRING.soft` | Wait after any turn |
| M4 | **List glide** | Each detent in a list (albums, playlists, queue, up next, windows, scenes) | The three rows jump **14 px** in the turn direction on the detent frame, then spring back to 0 while the labels already show the new item | `SPRING.snap` | Tour: "List glides one row per notch" |
| M5 | **Track change** | New song (skip, jump, auto-advance) | Same as M4 on the text layer (title + artist rise 14 px into place) | `SPRING.snap` | Tour: "Jump to the track" |
| M6 | **Status line** | Any new status (`Paused`, `Queued · …`, `Knob sets brightness`, deny reasons) | Rises **10 px** into place, fades in 240 ms; leaves with a plain fade | `SPRING.soft` | Tour: "Hold 4 … Queued" |
| M7 | **Footer icon press** | Button down | Icon squashes to **scale(0.8, 0.86)** and drops 2 px in **70 ms** `E.in`; on release springs back with the pop overshoot | `SPRING.pop` | Press any button |
| M8 | **Icon landing pop** | Hold 4 lands; Play/Pause state changes | Button-4 icon jumps to **1.28×** on the frame, springs back to 1 | `SPRING.pop` | Tour: "Hold 4 … lands with a pop" |
| M9 | **Play ⇄ Pause morph** | Play/Pause toggles | The two bars' 8 corners interpolate into the triangle (and back) over 300 ms; colour → `#6ED996` 120 ms later when paused | `E.out` 300 ms · colour 220 ms | Tour: "Pause: bars melt into the triangle" |
| M10 | **Hold-4 fill** | Button 4 held on Home, lists, explorer, Up next | A warm (`#FFBE69`) copy of the icon fills it bottom-to-top, linear over **1000 ms**; the base icon dims to `#6a6a6a`. Early release drains in 180 ms `E.in` | linear / `E.in` | Tour: "Hold 4" |
| M11 | **Idle row entrance** | Nothing loaded (Home / Music) | Each icon rises from **16 px** below at **85 %** scale, **40 ms** stagger (start 140 ms), fade 260 ms. Still at rest (no breathing) | `SPRING.pop` | Reset → Music state "Nothing loaded" |
| M12 | **Domain swap** | Hold 4 lands on Home | Ring: each LED changes to the new domain's colour with a delay of **i × 8.7 ms** (clockwise sweep from 12 o'clock, ≈ 520 ms round), each LED easing 200 ms. Screen: M1 with a lateral direction (to Lights = from the right) | LED `E.out` | Tour: "Hold 4 on Home: ring sweeps to lights" |
| M13 | **Wall stretch** | A turn that would pass a limit (§4.3) | Content layer moves **9 px** towards the wall in **90 ms** `E.out`, then rebounds on `SPRING.wall` (visible overshoot). End LEDs brighten (§3.4) | `E.out` → `SPRING.wall` | Tour: "Turn past the start: wall bounce", "Past 100 %" |
| M14 | **Navigator** (companion) | As r3.1 | Content slides with M1 timing, in sync with the knob | `SPRING.snap` | Monitor above the knob |
| M15 | **Breadcrumb** | Depth change | Crossfade with the content layer (M1). Layout rule §3.6 | — | Any push |

Kept from r3.1 unchanged: artwork fade (300 ms), pause dim (0.8 → 0.45), full-screen overlays (explorer, Up next, window picker), hold-1 / hold-4 ring arcs.

### 3.3 Walls on screen (pairs with §4.3)
When the firmware refuses a detent at a limit:
- Screen: M13 (9 px towards the wall, `SPRING.wall` back). Direction: the way you were turning (up for "past the end", down for "past the start").
- Ring: the **5 LEDs** at that end of the arc (arc index 0 or 44 ± 2) go to warm white `255,232,205` at L 0.9, then ease back with the normal LED easing.
- No click, no sound, no status text. Repeated pushes re-trigger the same thing.

Firmware note: the prototype triggers M13 when a clamp happens. On device, drive it from the end-stop event (the control loop already knows `at_wall`; `app_mode` already counts end-stop hits in `app_param_state_t.bump`). Expose a monotonically increasing wall counter + direction to the UI task.

### 3.4 LEDs
- **Easing everywhere:** every ring and button LED eases towards its target, exponential τ ≈ **50 ms** on the 60 fps LED task. Nothing on the ring ever steps.
- **Blooms, not flashes:** any emphasis (landing, deny, snap, scene run) rises 90–180 ms `E.out` and falls 420–700 ms `E.io`.
- **Deny glow:** bottom 9 LEDs (26–34) red `255,60,40` L 0.9, **480 ms**.
- Ring colours / levels are r3.1 (warm rest, Kelvin arcs, album-colour markers, green `110,217,150` confirmations).

### 3.5 Assets needed for icon motion
| Motion | Frames | Size |
|---|---|---|
| M9 Play ⇄ Pause morph | 12 per direction | 20 px A8 (≈ 0.4 KB each) |
| M10 hold fill | 12 per glyph (Pause, Play, Power) | 20 px |
| M7 / M8 press / pop | Scale is costly live. Pre-render **8 frames** per footer glyph (0.8 → 1.28), or accept a live `lv_img` zoom on the 20 px icon only | 20 px |
Total ≈ 60–80 KB flash. Everything else is opacity + position only.

### 3.6 Layout rules added in r4
- **Arc breadcrumb:** at most two named levels; deeper ancestors collapse to `…` (`… › TRACKS › UP NEXT`). The pre-rendered crumb must be ≤ **190 px** of arc (≈ ±58° from 12 o'clock); otherwise show `‹ CURRENT`.
- **List row widths:** previous ≤ 104 px, current ≤ 160 px, next ≤ 150 px, meta ≤ 176 px, ellipsis. These keep rows clear of the crumb's ends.
- **Big value:** number and unit are laid out as `number (right-aligned) · 4 px gap · unit (left-aligned)` around a computed centre, so they can never overlap when the digit count changes.

---

## 4. Haptics (firmware: `NanoDepsidf/src`)

### 4.1 What the firmware already has (don't rebuild)
| Capability | Where | Values |
|---|---|---|
| Feels `SAW` / `SINE` / `VISCOSE` | `haptic_params.h` `haptic_type_t` | VISCOSE forces Kp = 0 |
| Density | `HAPTIC_NUM_DETENTS_MIN/MAX` | **3–36** per turn |
| Kp (sharpness) | `HAPTIC_KP_*` | 0–20 V/rad, default 6 |
| Kd (damping) | `HAPTIC_KD_*` | 0–0.15 V/(rad/s), default 0.01 |
| Detent hysteresis | `HAPTIC_DETENT_HYSTERESIS_FRAC` | 15 % |
| End stops | `control_task.c` | next detent becomes a wall; spring 0 → `HAPTIC_WALL_GAIN` 3 × Kp; no click, no step |
| Coasting | `HAPTIC_COAST_VELOCITY_RAD_S` | zero spring above 30 rad/s; pulses disarmed |
| Click pulse | `HAPTIC_PULSE_*` | impact 4 ms @ 100 Hz (6 V, clipped) + tail 20 ms @ 70 Hz (1 V) |

### 4.2 New: haptic tokens (implement once as presets)
| Token | Params | Reduced haptics |
|---|---|---|
| `detent.value` | SINE · 36 / turn · Kp 3 · Kd 0.01 · no pulse | VISCOSE Kd 0.02 |
| `detent.dimmer` | SINE · 36 / turn · 2 % steps (1 % below 10 %) · Kp 3 · **Kd 0.04** | VISCOSE Kd 0.05 |
| `detent.list` | SAW · 20 / turn · Kp 6 · Kd 0.01 · pulse | SINE, no pulse |
| `detent.coarse` | SAW · 12 / turn · Kp 11 · Kd 0.02 · pulse | SINE Kp 6 |
| `detent.fine` | SAW · 36 / turn · Kp 2.5 · Kd 0.01 · pulse, fine sound | SINE, silent |
| `fluid.scrub` | VISCOSE · Kd 0.08 | same |
| `fluid.light` | VISCOSE · Kd 0.02 | same |
| `free.spin` | existing coast, enabled only for lists > 20 items | off |
| `wall.bounce` | existing end stop | same |
| `feel.fade` | on every context change: Kp ramps 0 → target over **120 ms**, detent grid re-anchored at the current angle | same |
| `hold.tension` | while button 1 / 4 is held for its secondary action: Kd ramps 0.01 → **0.12** over the hold (600 / 1000 ms); snaps back on release or landing | off |
| `nudge.left` / `nudge.right` | 1 pulse, phase-signed | unsigned 1 pulse |
| `confirm.tick` | 1 pulse at 60 % | 50 % |
| `confirm.thump` | **2 pulses 12 ms apart** (reads as one deep hit) | 1 pulse |
| `refuse.buzz` | 3 pulses 30 ms apart, 60 %; **≤ 1 per second** | 1 nudge |
| `error.buzz` | 3 pulses 70 ms apart, 100 % | 1 nudge |

### 4.3 Walls on every bounded screen
Every list and range must set its bounds so the firmware end stop fires: volume 0 / 100, brightness 1 / 100, temperature 2200 / 6500 K, seek 0:00 / end, every list's first and last item (albums, playlists, queue, Up next, windows, scenes). **No wrap-around anywhere.** Pair with §3.3.

### 4.4 Context map (turn feel · ends · events)
| Screen | Feel | Ends | Button events |
|---|---|---|---|
| Home (music) | detent.value | wall | 4 tap = tick · hold 4 = tension → thump → swap |
| Home (lights) | detent.dimmer | wall | 4 = off: 1 pulse · on: thump · hold 4 = tension → thump → swap |
| Music | detent.value | wall | 4 = tick |
| Recently Added / Playlists | detent.list (+ free.spin if > 20) | wall | 3 source = tick + feel.fade · 4 Play = thump · hold 4 Queue = tension → thump |
| Tracks | detent.list | wall | 4 jump = nudge in the jump direction · at the playing row = refuse |
| Seek | fluid.scrub | wall | 3 Set = tick · 1 Cancel = none |
| Up next | detent.list | wall | 2 shuffle / 3 like = tick · re-like = refuse · hold 4 = thump |
| Windows | detent.coarse | wall | 2 / 3 snap = nudge left / right · 4 Switch = tick |
| Lights | detent.dimmer; 3 lit → detent.fine | wall | 3 = feel.fade · 4 off / on as Home |
| Scenes | detent.coarse | wall | 4 Run = thump |
| Anywhere | — | — | hold 1 = tension → thump → Home (feel.fade to volume) |
| Sleep | fluid.light | — | first touch wakes only; detents fade in over 150 ms |

**Thump budget:** only hold landings, Play (replaces queue), Turn on and Scene run. Everything else is a tick.

---

## 5. Where to verify haptics
Open `Nano D Haptic Map.dc.html`. Each card plays a scripted turn/press and shows the force curve under the finger, pulses over time, walls (grey bands) and coasting (red band). **Full map** tab = every context in one table. **Creative** tab = five ideas marked *later* (don't build now).

---

## 6. Sound (firmware: `audio_trigger.h`, `i2s_task.c`)
Every sound follows its haptic; there are no sounds without a haptic. Use the existing `audio_trigger_click(type)` queue.

| Haptic | Sound | Amplitude (`AUDIO_CLICK_AMP`) |
|---|---|---|
| detent.list | `AUDIO_CLICK_NORMAL`, timbre WOOD_TOCK | 30 % |
| detent.coarse (windows, scenes) | `AUDIO_CLICK_NORMAL`, timbre TICK_THUD | 35 % |
| detent.fine (temperature) | `AUDIO_CLICK_FINE` (2× pitch) | 20 % |
| detent.value / dimmer / fluid | **silent** | — |
| confirm.tick | NORMAL, WOOD_TOCK | 30 % |
| confirm.thump | `AUDIO_CLICK_BUTTON_THUMP` (110 Hz, 40 ms) | 50 % |
| lights off | BUTTON_THUMP at lower amplitude | 35 % |
| nudge left / right | NORMAL, TICK_THUD | 30 % |
| refuse.buzz | 3 × NORMAL WOOD_TOCK, 30 ms apart | 20 % |
| error.buzz | 3 × NORMAL TICK_THUD, 70 ms apart | 30 % |
| wall | **silent** | — |
| coasting | **silent** (firmware already disarms pulses) | — |

Needs from firmware: per-event amplitude (today AMP is global) and per-event timbre override (today timbre is global for NORMAL). Both are small changes to the queue entry (`audio_click_type_t` + amp byte).

The prototype's **Sound proxy** is Web Audio and only approximates the motor; don't copy its synthesis.

---

## 7. Settings (companion + knob menu)
| Setting | Default | Effect |
|---|---|---|
| Reduced motion | Off (follow Windows "Show animations" if possible) | Every animation becomes a 160 ms opacity crossfade: no translate, scale, rotation, overshoot or icon morph. LED easing and colour changes stay; ring sweeps become blends |
| Reduced haptics | Off | Token fallbacks in §4.2: pulses → soft steps, thumps → 1 pulse, buzzes → 1 nudge, no coasting, no hold tension. **Walls stay** |
| Knob sounds | On | All §6 sounds; master amplitude slider (the existing AMP) |

---

## 8. The motion tour (what the prototype's red button plays)
Use it as a visual test script; each step names what should be seen.
| t (s) | Step | Shows |
|---|---|---|
| 0.6 | Turn: volume reveal | M2, soft steps, arc flow |
| 2.6 / 3.5 | Push into Music / Recently Added | M1, crumb |
| 4.4 | List glides one row per notch | M4, list clicks |
| 5.7 | Turn past the start | M13, end LEDs, wall |
| 7.0 | Hold 4 → Queued | M10, hold.tension, M8, thump, M6 |
| 9.2 / 10.2 | Tap 3 Playlists / back | tick, feel.fade |
| 11.2 | Back to Music | M1 (reverse) |
| 12.1 / 13.3 | Pause / Play | M9, M8, tick |
| 14.4–16.3 | Tracks, browse, jump | M4, nudge, M5 |
| 17.4 | Hold 1 → Home | hold arc, thump |
| 18.8 | Hold 4 on Home | M12, thump, feel.fade to dimmer |
| 20.6 / 21.8 | Brightness, past 100 % | heavier steps, M13 |
| 23.6 | Hold 4 back to volume | M12 |
| 25.2–27.9 | Windows: open, turn, snap left, switch | coarse clicks, nudge, tick |

---

## 9. Acceptance checklist
- [ ] No action waits for an animation; a fast spin never queues motion.
- [ ] No LED ever changes brightness in a single frame (except by the user's own detent on a value, which still eases).
- [ ] Every bounded list/range has a wall; pushing it moves the screen 9 px and bounces back; no sound, no click.
- [ ] Only four things thump (§4.4); refuse never buzzes twice within a second.
- [ ] Brightness feels heavier than volume with eyes closed.
- [ ] Changing context never drops a notch under the finger (feel.fade).
- [ ] Holding 1 or 4 stiffens the knob; releasing early relaxes it with no event.
- [ ] Value turns are silent; list clicks are quiet enough for a shared desk.
- [ ] Breadcrumb never overlaps a list row; big number and unit never overlap.
- [ ] Reduced motion: opacity only. Reduced haptics: walls still work.
- [ ] 30 fps holds during M1, M4 and M13 with artwork on screen.

## 10. Open questions for firmware
1. `hold.tension` ramps Kd per tick. Is that safe with the 200 V/s haptic slew limit, or should it step in 4 stages?
2. Does a 2-pulse thump (12 ms apart) read as one deep hit on the real motor?
3. Can `audio_trigger_click()` carry a per-event amplitude and timbre (§6)?
4. Expose a wall counter + direction to the UI task (§3.3) rather than recomputing it from clamps.
5. Live `lv_img` zoom on 20 px icons vs. pre-rendered strips for M7/M8: which is cheaper on the S3 with the current heap?
6. Later (not r4): seek magnet (a single SINE well blended with VISCOSE) and per-detent Kp (landmark notches).
