# Nano_D++ next build — recommended experience (r4)

One document for the next firmware + companion build. It combines the r3.1 IA, the motion lab (after two review passes) and the haptic map (now grounded in the `feat/firmware-esp-idf-quadra` firmware), and closes with a final adversarial review of both.

## Package
| Path | What |
|---|---|
| `prototypes/Knob IA Prototype r3.1.dc.html` | **The build reference.** IA, button maps, knob screens, Navigator, Settings, now with the r4 motion and haptics: 8 px screen pushes, big-value choreography, status rise, list glide per detent, Play⇄Pause morph, hold-4 fill, calm idle row, domain-swap ring sweep, LED easing, wall bounce on every limit (screen + end LEDs), and a sound proxy for every haptic event (toggle in the header) |
| `prototypes/Nano D Motion Lab.dc.html` | Motion: 21 prototypes, Today vs A/B/C, reduced motion |
| `prototypes/Nano D Haptic Map.dc.html` | **The combined preview**: 36 contexts with the recommended motion built in (screen pushes, domain-swap ring sweep, big-value reveal, wake, status rise, rail glide, LED easing, Play⇄Pause Melt, Hold-4 fill, Track change), haptics, sound proxy, reduced haptics |
| `reference/` | README deltas from r3, r3.1, motion lab and haptic map |

Serve `prototypes/` over HTTP. All three pages share `support.js`, `motion-lab.js`, `_ds/` and `assets/`.

---

## 1. What the firmware can do (read from `NanoDepsidf/src`)
| Capability | Firmware fact | How we use it |
|---|---|---|
| Feels | `HAPTIC_TYPE_SAW` (nearest-grid snap, 15 % hysteresis), `SINE` (smooth bump), `VISCOSE` (Kp forced 0, pure damping) | Clicks for choices, soft steps for values, fluid for time/space |
| Density | 3–36 detents / turn (`HAPTIC_NUM_DETENTS_MIN/MAX`); app mode 16 step / 48 fine | **Nothing in the knob UI exceeds 36.** Brightness uses 2 % steps; temperature 100 K at 36 / turn |
| Strength | Kp 0–20 V/rad (default 6); Kd 0–0.15 V/(rad/s) (default 0.01) | Tokens specify real Kp/Kd (§3) |
| End stops | Next detent becomes a wall: spring ramps 0 → 3 × Kp (`HAPTIC_WALL_GAIN`), no click, no step; release returns to the committed detent. App mode counts end-stop hits so the card can nudge | **Every bounded list and range uses it** (`wall.bounce`) |
| Coasting | Zero spring above 30 rad/s filtered velocity; click pulses disarmed while coasting | `free.spin` only on lists > 20 items |
| Pulse | One shape: 4 ms impact @ 100 Hz, 6 V (clipped) + 20 ms tail @ 70 Hz, 1 V | Tick = 1 pulse · Thump = 2 pulses 12 ms apart · Buzz = 3 pulses · Nudge = 1 phase-signed pulse |
| Sound | Detent timbres WOOD_TOCK / TICK_THUD, FINE (2× pitch), BUTTON_THUMP 110 Hz 40 ms; pitch 0.5–2×, amp 0–100 % in 5 % steps; 16-deep click queue | Value feels silent; list clicks 20–35 %; thump only with thumps |
| Held-key feel | App profiles switch feel/density per held key (Onshape orbit/pan = VISCOSE) | `hold.tension` and the "hold 3 = temperature" idea |
| Timings | Tap ≤ 400 ms, menu hold 700 ms, param cancel hold 600 ms, debounce 15 ms | Keep r3.1: hold 1 = 600 ms, hold 4 = 1000 ms |

## 2. Principles (motion + haptics + LEDs as one)
1. **Input first.** Every action fires on its press, release or detent. Motion, LEDs and haptics acknowledge; none of them delay or queue.
2. **Clicks for choices, soft steps for values, fluid for time and space.**
3. **Every limit bounces.** Physical wall + the screen stretching with it (≤ 6 px, following the spring, not a timed animation) + the end LEDs brightening; all three let go together.
4. **You can feel which job the knob has.** Volume is light (Kd 0.01), brightness is heavier (Kd 0.04), lists click, fine values click higher.
5. **Calm motion, alive icons.** Screens and text are critically damped and travel ≤ 14 px; only icons settle with a ≈ 4 % overshoot.
6. **LEDs never step.** Every LED eases on the LED task (τ ≈ 50 ms); emphasis is a bloom (rise 90–180 ms, fall 420–700 ms), never a flash.
7. **One confirmation per action; thumps are rare; holds charge silently.**

## 2b. Layout rules added in r4
- **Arc breadcrumb budget.** At most two named levels: deeper ancestors collapse to "…" (`… › TRACKS › UP NEXT`). The pre-rendered crumb must be ≤ 190 px of arc (≈ ±58° from 12 o'clock); if it still doesn't fit, show `‹ CURRENT`.
- **List row budgets** (so rows never reach the crumb's ends): previous row ≤ 104 px, current row ≤ 160 px, next row ≤ 150 px, meta ≤ 176 px, each truncated with an ellipsis.

## 3. Haptic tokens (firmware units)
| Token | Params | Sound | Reduced |
|---|---|---|---|
| `detent.value` | SINE · 36 · Kp 3 · Kd 0.01 | — | VISCOSE Kd 0.02 |
| `detent.dimmer` | SINE · 36 · 2 %/step (1 % < 10 %) · Kp 3 · Kd 0.04 | — | VISCOSE Kd 0.05 |
| `detent.list` | SAW · 20 · Kp 6 · Kd 0.01 · pulse | tock 30 % | SINE, no pulse |
| `detent.coarse` | SAW · 12 · Kp 11 · Kd 0.02 · pulse | tick-thud 35 % | SINE Kp 6 |
| `detent.fine` | SAW · 36 · Kp 2.5 · Kd 0.01 · fine pulse | fine 20 % | SINE, silent |
| `fluid.scrub` | VISCOSE · Kd 0.08 | — | same |
| `fluid.light` | VISCOSE · Kd 0.02 | — | same |
| `free.spin` | firmware coast > 30 rad/s; lists > 20 items only | silent | off |
| `wall.bounce` | firmware end stop (0 → 3 × Kp), no click | — | same |
| `feel.fade` | Kp 0 → target over 120 ms, grid re-anchored | — | same |
| `hold.tension` | Kd 0.01 → 0.12 over the hold | — | off |
| `nudge.left/right` | 1 signed pulse | tick-thud 30 % | unsigned tick |
| `confirm.tick` | 1 pulse @ 60 % | tock 30 % | 50 % |
| `confirm.thump` | 2 pulses, 12 ms apart | BUTTON_THUMP | tick |
| `refuse.buzz` | 3 pulses, 30 ms apart, 60 %; ≤ 1 / s | 3 tocks 20 % | 1 nudge |
| `error.buzz` | 3 pulses, 70 ms apart, 100 % | 3 tick-thuds 30 % | 1 nudge |

## 4. The experience, screen by screen
| Screen | Knob feel | Ends | Buttons / events | Motion (lab pick) | LEDs |
|---|---|---|---|---|---|
| Home (music) | detent.value | wall.bounce 0 / 100 | 4 tap = tick; hold 4 = tension → thump → swap | Big value A; Play⇄Pause A Melt | Arc flow (Ring A) |
| Home (lights) | detent.dimmer | wall.bounce 1 / 100 | 4 = soft thump off / thump on | Domain swap A (ring sweep) | Kelvin arc |
| Music | detent.value | wall.bounce | 2 Recent · 3 Tracks · 4 tick | Depth C (anchored art), Track change A | — |
| Recently Added / Playlists | detent.list (+ free.spin if > 20) | wall.bounce first/last | 3 source = tick + feel.fade; 4 Play = thump; hold 4 Queue = tension → thump | Lists A (rail), Source B (shuffle) | Marker in album colour |
| Tracks (queue) | detent.list | wall.bounce | 4 jump = nudge in direction; at playing row = refuse.buzz | Lists A, digits A | Queue ring |
| Seek | fluid.scrub | wall.bounce 0:00 / end | 3 Set = tick; 1 Cancel = none | Big value A | Warm arc |
| Up next | detent.list | wall.bounce | shuffle / like = tick; re-like = refuse; hold 4 = thump | Lists A | — |
| Windows picker | detent.coarse | wall.bounce | snap = nudge left/right; 4 Switch = tick | Window picker A | App-colour LEDs |
| Lights | detent.dimmer (3 lit: detent.fine) | wall.bounce | 3 = feel.fade; 4 = off/on thumps | Big value A, Lights icons A | Kelvin arc / white marker |
| Scenes | detent.coarse | wall.bounce | 4 Run = thump | Lists A | Scene clusters, green bloom |
| Any screen | — | — | hold 1 = tension → thump → Home | Depth pop | Warm hold arc |
| Sleep / wake | fluid.light → context | — | first touch wakes only; detents fade in 150 ms | Sleep A | Breath-free rest |

**Creative, for the build after (marked "later" in the map):** volume heavier above 80 %; push past 1 % to switch lights off; hold 3 + turn = temperature (spring-loaded mode); seek magnet at the start position; scenes as a heavy rotary switch.

---

## 5. Final adversarial review (motion + haptics together)
Findings, and what this build does about them.

1. **The map asked for densities the firmware can't do.** Brightness 50 / turn and temperature 43 / turn exceed `HAPTIC_NUM_DETENTS_MAX 36`. → Both are 36 now; brightness steps 2 % (1 % below 10 %).
2. **Walls were inconsistent.** Some lists had a soft wall, some none, some a red flash. → One rule: every bound is the firmware wall, silent, with the screen stretching with it and settling back. The red "end" flash is gone.
3. **Visual bounce was scripted, the physical bounce isn't.** A timed rubber-band animation drifts out of sync with the real spring. → The screen offset is a live function of wall penetration (`6 px × (1 − e^(−pen / 0.6 pitch))`), and it returns on the same spring as the knob.
4. **Too many thumps.** Started, Queued, Swapped, Scene, Home, Set seek, Switch window and Turn on all thumped, so none felt special. → Thumps only for hold landings, Play (replaces queue), Turn on and Scene run. Set seek, Switch window and toggles tick.
5. **Holds had no feel.** For 1 s nothing happened under the finger. → `hold.tension`: damping rises over the hold, so the knob stiffens as it charges, silently. Released on landing.
6. **Domains felt identical.** After hold 4 the knob felt the same, so only the screen said volume vs brightness. → Brightness is heavier (Kd 0.04 vs 0.01).
7. **Audible clicks everywhere would be tiring at a desk.** → Value feels are always silent; list and coarse clicks default to 20–35 % amplitude; the thump sound only plays with thump haptics.
8. **Coasting thresholds were guessed.** Firmware coasts at 30 rad/s (≈ 1,700°/s), much faster than assumed. → Keep the firmware value; enable only on lists longer than 20 items so short lists never slip.
9. **Refuse could machine-gun.** Repeated presses on a dead button would buzz every time. → Rate-limit refuse.buzz to once per second; the status text and red bloom still update.
10. **LED easing vs detent precision.** τ 50 ms LED easing lags a detent click by about a frame. → Acceptable at 60 fps; if the marker feels late on hardware, drop the marker's τ to 30 ms while turning.
11. **Motion leftovers.** Full-screen art blends are the one expensive motion; keep them ≤ 300 ms at 30 fps and fall back to fading only the scrim if the S3 drops frames. Everything else in the shortlist is opacity/position or ≤ 36 KB of icon strips.
12. **Reduced modes must be one switch each.** → Reduced motion (opacity only) and reduced haptics (pulses → soft steps, thumps → ticks, buzz → nudge, no coasting; walls stay) are separate companion settings.

## 6. Build list
**v1 (this build):** all tokens in §3; every context in §4; wall.bounce everywhere; hold.tension; thump budget; sound defaults; motion shortlist (motion lab README); LED easing + blooms; reduced motion and reduced haptics.
**Later:** the five creative ideas; Onshape space (needs its own launcher slot; hold 2 / 3 conflict with in-space buttons); Like "heartbeat"; brightness 50 % and common-white landmark notches (need per-detent strength in firmware).

## 7. Open questions
1. Can the control loop blend a single SINE well with VISCOSE (seek magnet), and vary Kp per detent (landmark notches)? Both are small additions to `control_task.c`.
2. Is ramping Kd per tick for `hold.tension` safe with the 200 V/s haptic slew limit, or should it step in 4 stages?
3. Confirm 2-pulse thump spacing (12 ms) reads as one deep hit rather than two ticks on the real motor.
4. Where does "reduced haptics" live: the companion only, or also a knob menu entry next to the existing Haptic Configurator?
5. Should the firmware's end-stop bump counter (`app_param_state_t.bump`) be exposed to the knob UI generally, so the screen stretch is driven by the firmware rather than recomputed?
