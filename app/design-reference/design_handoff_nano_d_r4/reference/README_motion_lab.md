# Handoff: Nano_D++ motion lab (exploration)

An exploration pass on motion for the knob, built on the r3.1 screens. Nothing here changes the visual design (colours, icons, Montserrat, layouts). It proposes how things move.

## Files
| File | What it is |
|---|---|
| `prototypes/Nano D Motion Lab.dc.html` | The lab: 21 playable prototypes in 4 areas + a Compare & shortlist page |
| `prototypes/motion-lab.js` | Every prototype as a pure function of time (`render({t, trig, reduced})`), plus the easing/spring library and the knob renderer. Read this for exact values |
| `prototypes/support.js`, `_ds/`, `assets/covers/` | Runtime, page styling and sample covers |

Serve `prototypes/` over HTTP and open the lab. Per prototype: **Trigger** (fires the event and restarts), **Play/Pause**, **Replay**, **Loop**, speed **0.25× / 0.5× / 1×**, **Today / Proposed**, **1× / 2×** size, and a **scrubber** (red ticks = haptic motor clicks; tall ticks = stronger bumps). Variants play in sync on one clock. **Reduced motion** (top right) switches every stage to its fallback. 

The lab is a design reference, not firmware. Timings and springs are the spec; the drawing code is not.

## Review r2 (Apple-style pass)
The first pass read as busy. A senior-UX review found five systemic problems; all are fixed in this version.
1. **Underdamped springs.** Several tokens had a damping ratio of 0.34–0.5 (up to ≈ 30 % overshoot, wobbling for 700 ms). Every spring is now specified as *response / damping* and sits at 0.78–1.0: text and screens are critically damped, only icons keep a 1–2 % settle.
2. **Travel 2–4× too long.** Screens pushed 24–30 px, icons 5–14 px, statuses 64 px. Now: screens 8–14 px, text 3–5 px, icons 1.5–2 px, scale 0.97–1.05.
3. **Motion without meaning.** Removed the idle breathing and floating, the 28° twist, the 90° sparkle spin, the white flash at the ring sweep's head, and exit drifts on status lines (exits are plain fades).
4. **Too many staggers.** Staggers of 40–60 ms made single events feel like sequences. Now 24–30 ms and only where there's a reading order (title → artist).
5. **Stutter in the lab itself.** Springs that follow the knob were re-simulated from t = 0 on every frame. They're now simulated once per trigger and sampled, so playback is smooth at 60 fps.

## Review r3 (flicker pass)
1. **No haptic halo.** The lab stage used to draw a flashing circle outside the LED ring to show motor clicks. It is not part of the design and has been removed; motor clicks are shown only as ticks on the scrubber.
2. **LEDs never step.** Every ring and button LED eases towards its target on the LED task (exponential, τ ≈ 50 ms, 60 fps). This is a firmware rule, not per-animation: it removes every hard edge when a value, marker or state changes.
3. **No flashes.** Every "flash" (press LEDs, landing washes, status ticks, list end, detent pulse, wake) is now a **bloom**: 90–180 ms rise on E.out, 420–700 ms fall on E.io. Nothing appears or disappears on a single frame.
4. **Bounce where it means something.** Icon landings (Play/Pause, hold 4, press, sparkles, idle drop) use `SP.pop` (response 0.38 s, damping 0.72, ≈ 4 % overshoot) from a small dip (0.94), so they feel alive without jitter. Text and screens stay critically damped.

A frame-by-frame scan (16 ms steps) of every proposed variant finds no LED changing by more than 0.31 of full brightness between frames; the largest remaining steps are the arc head travelling past an LED, which ramps over 3–4 frames.

## Motion principles
1. **Calm by default.** Motion is short (≤ 350 ms), small (≤ 14 px) and critically damped. Overshoot is reserved for icons acknowledging a press.
2. **Input first.** Every action fires on the press or detent frame; motion only acknowledges it. Nothing waits for an animation, and a fast spin retargets the running motion (springs/followers) instead of queueing steps.
3. **Icons respond, text settles, screens push, the ring leads.** Icons get the only (1–2 %) overshoot. Text arrives with soft springs and never overshoots visibly. Screen changes are short directional pushes. The ring is the gauge, so it starts first or together with the screen, never after.
4. **One vocabulary.** Six springs and four beziers cover everything (below). Same property, same curve, everywhere.
5. **Cheap by default.** Opacity and position for text and screens; frame strips only for icon morphs; nothing that scales, rotates or blurs full-screen content per frame.
6. **Buttons never move under your fingers.** Footer icons crossfade in place; only their own press feedback moves them, by 2 px.
7. **LEDs are always eased** (τ ≈ 50 ms on the LED task) and change through blooms, never flashes.
8. **Every animation has a reduced-motion fallback**: a 160 ms opacity crossfade (E.out), no translate, scale, rotation or overshoot. Ring colour changes stay (they're information), ring sweeps become blends.

## Motion tokens
| Token | Value | Used for |
|---|---|---|
| `SP.snap` | response 0.30 s, damping 0.90 · k 438.6, c 37.7 · ≈ 268 ms | Screen pushes, glyph swaps, most arrivals |
| `SP.soft` | response 0.45 s, damping 1.0 · k 195, c 27.9 · ≈ 552 ms | Text settling, artwork, idle row, wake |
| `SP.pop` | response 0.38 s, damping 0.72 · k 273.4, c 23.8 · ≈ 470 ms | Icon landings only: ≈ 4 % overshoot from a 0.94 dip |
| `bloom` | rise 90–180 ms E.out, fall 420–700 ms E.io | Every LED emphasis (replaces flashes) |
| `SP.crit` | response 0.28 s, damping 1.0 · k 503.6, c 44.9 · ≈ 344 ms | Values that follow the knob (odometer, ring flow) |
| `SP.roll` | response 0.30 s, damping 0.88 · k 438.6, c 36.9 · ≈ 252 ms | Slot-machine digit columns |
| `SP.list` | response 0.28 s, damping 0.92 · k 503.6, c 41.3 · ≈ 268 ms | List rail and ring marker |

Conversion (mass 1): k = (2π / response)², c = 4π · damping / response. `SP.bouncy` is kept in the code for old references but no recommended variant uses it.
| `E.out` | cubic-bezier(0.22, 1, 0.36, 1) | Fades in |
| `E.in` | cubic-bezier(0.4, 0, 1, 1) | Fades out |
| `E.io` | cubic-bezier(0.65, 0, 0.35, 1) | Ring sweeps, dimming |
| `E.spr` | cubic-bezier(0.34, 1.45, 0.64, 1) | r3.1 today (kept for comparison) |

LVGL 9 has no spring animator. Implement springs as a per-frame semi-implicit Euler step (`a = k·(target − x) − c·v; v += a·dt; x += v·dt`) in the 30 fps UI timer. This is also what makes retargeting free: a new detent just changes `target`.

## Recommended shortlist
★ in the lab. 17 cheap, 4 medium, 0 costly.
| Area | Prototype | Pick | Cost | Why |
|---|---|---|---|---|
| Icons | Play ⇄ Pause | **A Melt** | Medium (12-frame strips) | The morph the brief asked for, at ≈ 10 KB |
| Icons | Press feedback | **D Nudge** | Cheap | Enough acknowledgement without 60+ extra frames; A Squash is the upgrade |
| Icons | Bulb / Power / Thermo / Wand | **A Expressive** | Medium (≈ 36 KB) | Each icon shows what it changed; mercury is a live rect |
| Icons | Idle row | **A Stagger rise** | Cheap | Closest to today, calmer; still at rest |
| Icons | Hold-4 | **A Fill-up + pop** | Medium | Pressure you can see, a clear "landed" |
| Icons | Pause ⇄ Power | **A Bar → stem** | Medium | Shows the key changing job |
| Text | Rolling digits | **A Odometer** | Cheap | Continuous, never queues, handles 99 → 100 |
| Text | Track change | **A Stagger slide** | Cheap | Title then artist |
| Text | Long titles | **B Fade-truncate** | Cheap | The knob is glanced at; no motion needed |
| Text | Status lines | **A Rise · hold · sink** | Cheap | |
| Text | Arc breadcrumb | **A Radial crossfade** | Cheap | Works with the pre-rendered bitmaps |
| Text | Big value | **A Choreographed** | Cheap | |
| Screens | Lists | **A Rail + focus** | Cheap | Inertia and end-stretch without scaling text |
| Screens | Artwork | **A Colour bleed** | Cheap* | *Full-screen blends: keep ≤ 300 ms at 30 fps |
| Screens | Ring + screen | **A Flow** | Cheap | One value drives both |
| Screens | Haptics | **A Detent-locked** | Cheap | |
| Transitions | Depth | **C Anchored art** | Cheap | The cover is the shared element for free |
| Transitions | Domain swap | **A Ring sweep** | Cheap | The special one: the ring changes job first |
| Transitions | Recent ⇄ Playlists | **B Shuffle** | Cheap | Sideways, not deeper |
| Transitions | Sleep / wake | **A Breathe down** | Cheap | Backlight PWM is free |
| Transitions | Window picker | **A Hand-off** | Cheap | Knob and monitor as one gesture |

## Frame budget (recommended set)
Play/Pause 12 × 2 · Pause⇄Power 12 × 2 · Hold fill 12 + pop 6 per glyph (3 glyphs) · Bulb 14 + 8 · Power 16 · Wand 14. ≈ 140 frames at 20–26 px, **≈ 80 KB of flash**, A8.

## Haptics
Clicks land on the **input frame** (press or detent), never on an animation's end. Two exceptions, both marked as tall ticks: the list end-stop bump fires at the rail's stretch peak (+60 ms), and the hold-4 landing is a stronger click on the pop frame. Variant B of Haptic pairing adds a soft "landed" tick 260 ms after a fast spin; it needs a third, softer motor waveform.

## Frame rate
30 fps for everything on the LCD. 60 fps matters for: odometer and list during a fast spin, spring pops with visible overshoot, the domain-swap sweep (the ring runs on the 60 fps LED task anyway).

## Open questions
1. **Spring integration on device.** Is a per-frame Euler step in the UI timer acceptable CPU-wise alongside LVGL rendering, or should springs be pre-baked to lookup tables (e.g. 32 samples per token)?
2. **Artwork blends.** Colour bleed and pause dim redraw the full screen for up to 300 ms. Confirm the S3 holds 30 fps doing that with the scrim; if not, fade the scrim only and swap the cover under it.
3. **Odometer font.** Needs 48 px tabular digits 0–9 as a separate glyph set (≈ 10 × 2 KB). OK in flash?
4. **Rest state.** The idle row is now completely still. If you want a sign of life, it should be on the ring (warm rest level), not the icons.
5. **Arc breadcrumb B** (slide along the arc) looked best in review sessions for depth, but costs ≈ 30 KB per crumb path. Worth it for the 3–4 most-used paths only?
6. **Third haptic waveform** for the landing tick (Haptic pairing B).
7. **Reduced motion trigger.** A setting in the companion, or follow Windows' "Show animations" setting automatically?
