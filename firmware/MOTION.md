# MOTION: r4 screen motion, LED choreography and render speed (plan stage F4)

Source: `app/design-reference/design_handoff_nano_d_r4/README.md` (§2, §3.1–3.6, §7, §8, §9)
and `prototypes/motion-lab.js` / `Knob IA Prototype r3.1.dc.html` (the build reference). This page is the summary;
the details are in `src/cc_display.cpp` (LCD), `src/cc_alive.cpp` (LEDs, ALIVE.md §16), `PRESENTATION_V5.md` §20
and the harness (`harness`).

## 1. Tokens (README 3.1)

| Token | response · damping | k · c | settles | overshoot | firmware |
|---|---|---|---|---|---|
| `SPRING.snap` | 0.36 s · 0.72 | 304.6 · 25.1 | 416 ms | 3.8 % | `SPRING_SNAP` |
| `SPRING.soft` | 0.46 s · 0.82 | 186.6 · 22.4 | 544 ms | 1.1 % | `SPRING_SOFT` |
| `SPRING.pop` | 0.42 s · 0.52 | 223.8 · 15.6 | 624 ms | 14.7 % | `SPRING_POP` |
| `SPRING.wall` | 0.34 s · 0.42 | 341.5 · 15.5 | 648 ms | 23.2 % | `SPRING_WALL` |
| `E.out` / `E.in` / `E.io` | cubic-bezier (0.22,1,0.36,1) / (0.4,0,1,1) / (0.65,0,0.35,1) | | | | `EASE_OUT/IN/IO` |

- **Fire-and-forget** moments run as LVGL anims on a baked path: `kSpringLut` (41 samples × 4096 of the step response
  over the settle time, exactly the prototype's `cssSpring()` / CSS `linear()`), generated and checked by
  `harness/make_motion.py [--check]`.
- **What follows the knob** (M4 list glide, M5 track change, M13 wall stretch) runs on a small stepper (`Glide`):
  semi-implicit Euler at 4 ms steps on LVGL's clock, one anim for all of them. A new detent or wall **retargets**
  the running motion (position replaced, velocity kept); nothing ever queues. The desktop's Navigator uses the same
  analytic spring (`stage/curves.py` `"SNAP"`).

## 2. Moments (README 3.2) as built

| # | Moment | Knob (cc_display.cpp) | Reduced motion |
|---|---|---|---|
| M1 | Screen push | content from ±28 px (deeper = from the right), `SPRING.snap`; opacity 0→1 240 ms E.out; old content replaced on the frame. **The 97 % scale is not drawn**: an LVGL transform renders the content box through an ARGB8888 layer (130 KB > the 64 KB heap) | 160 ms fade |
| M2 | Big value in | text layer out 130 ms E.in, 12 px up (160 ms); big layer from 14 px below, fade 180 ms OUT after 40 ms, `SPRING.snap` from 40 ms. Scale 94 % not drawn (as M1) | 160 ms fades |
| M3 | Big value out | big layer out 130 ms E.in (14 px by 160 ms); text back after 90 ms: fade 260 ms, `SPRING.soft` | 160 ms fades |
| M4 | List glide | recent / explorer / up next / tracks / windows / scenes rows: on a detent of an index ring (the selected entry moved on the same screen) the layer jumps 14 px in the turn direction and springs back (`SPRING.snap`); the labels already show the new item; a fast spin re-jumps | none |
| M5 | Track change | Home text (title + artist) rises 14 px into place on a new song at rest | none |
| M6 | Status line | the status (Home) and meta lines (lists) rise 10 px (`SPRING.soft`) and fade in 240 ms; the Home status leaves with a plain fade (its words kept until the next text); a detent that glides (M4) does not also rise its meta | 160 ms fade |
| M7 | Press squash | `cc_display_input(keys)`: the footer icon of a pressed button → scale (0.8, 0.86) + 2 px down in 70 ms E.in; release springs back `SPRING.pop` (live `lv_image` scale on the 20 px icon: a transformed draw of that image only) | icon dims to 60 %, 160 ms back |
| M8 | Landing pop | the Play/Pause icon on a playing change, the button-4 icon on a hold landing: 1.28× on the frame, `SPRING.pop` back | none |
| M9 | Play ⇄ Pause | 12 A8 frames (`cc_icon_morph.cpp`, `export_morph_strip.cjs`) over 300 ms E.out on the same screen only; the ink (paused green) follows 120 ms later over 220 ms | instant glyph + ink fade |
| M10 | Hold-4 fill | while physical slot 3 is held on a `holdMarker` screen: a warm (#FFBE69) copy of the icon's own mask fills a bottom-anchored clip box linearly over 1000 ms on the dimmed (#6A6A6A) icon; an early release drains it in 180 ms E.in; the landing (first new ok feedback within 1.5 s of maturity) pops (M8). **No frame strips** (the icon's mask is reused: −14 KB against README 3.5) | the warm copy fades in over the hold |
| M11 | Idle row | icons from 16 px below at 85 % scale, 40 ms stagger from 140 ms, fade 260 ms, `SPRING.pop` | 160 ms fades, stagger kept |
| M12 | Domain swap | screen: M1 lateral (Home ↔ Lights by depth); ring: LEDs (§3) | ring blends |
| M13 | Wall stretch | `cc_display_wall(dir)` per new `cc_wall_count()` hit: content 9 px towards the wall (up past the end) in 90 ms E.out, then `SPRING.wall` (visible overshoot); a new push retargets | none |
| M14 | Navigator | Desk Dial: the content container from ±28 u, `"SNAP"` 416 ms + 240 ms opacity (`stage/scenes/navigator.py`) | 160 ms fade |
| M15 | Crumb | two crumb slots crossfade with the content (240 ms OUT; reduced 160 ms) | 160 ms |

Layout rules (README 3.6): the arc breadcrumb keeps at most two named levels (`… › TRACKS › UP NEXT`) within 190 px of
arc, else `‹ CURRENT` (`control_center/crumb_arc.display`, regenerated by `make_crumbs.py`: 50,223 → 32,644 B);
scenes rows previous ≤ 104 / current ≤ 160 / next ≤ 150 / meta ≤ 176 px, Tracks meta ≤ 176 px (list titles keep
170: their first line already takes the r104 chord ≤ 160, their second lies below the crumb's ends); the big value
is `number | 4 px | unit` around the computed centre. `lcd_preview.py` (the floating knob's static mirror) follows
every static rule.

## 3. LEDs (README 3.3 / 3.4; ALIVE.md §16)

After the animator (`CCAlive::r4Layer`, twin `AliveLights._r4_layer`):
- **Easing everywhere**: every ring and button LED eases towards the animator's e with τ = 50 ms, integrated with a
  first-order hold (exact for an e that moves linearly across the frame, so 60 Hz and 360 Hz agree on smooth
  curves); tails below 1e-6 land on the target. Per 16 ms frame an LED moves at most 1 − e^(−16/50) = 27 % of its
  gap: nothing steps.
- **Wall**: a limit glows the cursor ±2 (the 5 LEDs at that end of the arc) warm white 255,232,205 at L 0.9, rise
  90 ms E.out, fall 420 ms E.io, blended over what they show (the existing bound comet stays under it).
- **Deny glow**: an unavailable press (err + `refused`) lights LEDs 26–34 in 255,60,40 at 0.9 for **480 ms**
  (was 320 ms RED), risen and fallen by the damping + easer (a bloom, never a flash).
- **M12 domain swap**: a plain-ok hold-4 landing starts the sweep instead of the r3.1 whole-ring wash: LED i starts
  easing to the new ring i × 8.7 ms after the landing (clockwise from 12 o'clock), 200 ms each (the easer).
- Unchanged by r4 (user rulings): warm-white rest, green Play while paused, below-floor off (F-T floor).

## 4. Render speed (README 9: ≥ 30 fps during M1, M4, M13 with artwork)

Measured on the knob 2026-09-30: `lcdRefrUsAvg` ≈ 43 ms, 8.5–10 fps during transitions. The host profile
(`harness/perf.py`, `perf.cpp`: the firmware renderer + LVGL 9.0.0 + lv_conf, the knob's 16 ms period and
11,520 B draw buffer, per-refresh host µs, pixels, chunks, layered objects, A8 copies, per-draw-task time):

| scenario (host µs / refresh, median; `perf/*.json`) | before r4 | r4 code | r4 + `LV_OBJ_STYLE_CACHE 1` | + 48-row buffers |
|---|---|---|---|---|
| M1 push, the lcd_bench pair (no covers) | 150 | 154 | 56 | 46 |
| M1 push with covers | 236 | 230 | 81 | 68 |
| M4 glide with covers (r4: the rows move) | (24: no motion) | 127 | 44 | 38 |
| M13 wall with covers | – | 171 | 60 | 50 |

Scaling the knob's measured 43 ms by the host ratio, the M1-with-covers refresh drops to about 15 ms with the style
cache (about 12 ms with 48-row buffers): 30 fps and more, the rest of the pass permitting. The lead confirms on the knob.

Findings:
1. **Container opacity is not the cost.** LVGL 9.0.0 applies `opa` by multiplication (`lv_obj_get_style_opa_recursive`);
   only transforms, `opa_layered`, blend modes and `clip_corner` with children make a layer. The profile counts **0
   layered objects** in every scenario. The fades stay as they are; M1/M2's scale is left out because it WOULD make one.
2. **Style lookups dominate.** Of a 224 µs content refresh only ~86 µs is draw tasks (labels 65, images 16, fills 5);
   the rest is the object walk: every object meeting a chunk resolves its styles through the style list and the
   parent chain, on every one of the 6–8 chunks. `LV_OBJ_STYLE_CACHE 1` (lv_conf.h) cuts refresh time 2.4–3.1×;
   the whole harness (1,658 renders) is **pixel-identical** with it. Needs the FEEL job (include/lv_conf.h).
3. A8 masks (crumbs, icons, morph frames) were `lv_malloc`'ed and copied in full on every draw of every chunk by
   LVGL's bin decoder (no image cache): ~9 copies / 11 KB per refresh. The renderer's own decoder now draws them
   from flash (`a8Direct`).
4. The text-shadow twins are hidden while no cover can be under them (black over black: pixel-identical); a quarter
   of the text work of an art-less screen (they come back at once with a cover).
5. Taller draw buffers cut the per-chunk re-walk ~20 % (`CC_LCD_DRAW_ROWS`, default 24; 48 = +23 KB internal RAM).
6. LVGL-only `-O2` is expected to help the blend loops on the device (not measurable on the host): a per-library
   flag (Needs from FEEL).

The acceptance number is the knob's: the lead re-measures with `tools/lcd_bench.py` (`lcdFps`, `lcdRefrUsAvg`).

## 5. Verification

- `harness/build.py` + `cc54_report.py` (40 checks incl. `r4_moments`: M1, M15, M2, M4 retarget, M5, M6
  rise/leave, M7, M8, M9, M10 fill/landing/drain, M13 and the reduced-motion timeline; `slides`, `motion`,
  `reduced_motion` restated for r4; `v5_bounded` proves every enlarged layer box).
- `alive_tests.py` (direct `r4Checks`: easing bound, wall glow, 480 ms deny, M12 order; twin replay with the r4 layer).
- `r4_tour_sheet.py` → `design-reference/r4-motion-tour-sheet.png`: the README 8 tour, the M1–M15 timeline and the LED
  moments, for review by eye.
- `perf.py <label> [--rows 24,48] [--conf DIR]` for the render profile.
