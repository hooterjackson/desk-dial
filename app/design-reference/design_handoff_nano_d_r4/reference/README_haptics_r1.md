# Handoff: Nano_D++ haptic map (r1)

Maps the motor firmware's haptic toolkit onto every r3.1 screen and interaction. Nothing visual changes; this pass is about how the knob feels. Pairs with the motion lab (`design_handoff_nano_d_motion_lab/`): every haptic moment below names the motion and LED moment it lands with.

## Files
| File | What it is |
|---|---|
| `prototypes/Nano D Haptic Map.dc.html` | Playable spec. 30 contexts in 7 groups, plus **Tokens & principles** and **Full map** tabs |
| `prototypes/haptic-lab.js` | All contexts as data (feel, density, snap, damping, click, ends, events, sound, pairing, reduced fallback) + the scripted simulation, force curves, waveforms and Web Audio proxy |
| `prototypes/motion-lab.js` | Knob renderer shared with the motion lab |
| `prototypes/support.js`, `_ds/`, `assets/` | Runtime, page styling, covers |

Serve `prototypes/` over HTTP and open the map. Each card: **Play / Replay** and a scrubber; the knob screen and ring; a **torque-vs-angle curve** whose window follows the knob (red dot = where the finger is); a **pulse timeline** (spikes = clicks, rounded = soft SINE notches, wide = thump, triple = buzz, grey bands = wall / free spin); an **approximate sound** via Web Audio. Header: **Reduced haptics** and **Sound proxy** toggles. The sound is a proxy for motor feel, not a sound design.

## Principles
1. **Clicks for choices, soft steps for values, fluid for time and space.** Lists and scenes click (SAW + electrical click). Volume, brightness and zoom step softly (SINE, silent). Seek, orbit and pan are fluid (VISCOSE).
2. **Walls at every end, and walls never buzz.** Every list and range ends in a spring wall with no click, so pushing it repeatedly never becomes noise.
3. **One confirmation per action.** A tap or a landed hold gets exactly one event haptic. Motion and LED blooms carry the rest.
4. **Thump for "landed", tick for "toggled", buzz only for "no".**
5. **Quiet while you move fast.** Above 720°/s the knob coasts and every event is skipped.
6. **Never change the feel under the finger.** Every context change re-anchors the new detent grid at the current angle and fades its snap in over 120 ms (`feel.fade`).
7. **Everything degrades to quiet.** Reduced haptics: clicks → soft steps, thumps → ticks, buzzes → one nudge, coasting off. Walls stay; they carry information.

## Haptic tokens
| Token | Kind | Parameters | Reduced |
|---|---|---|---|
| `detent.value` | Feel | SINE · 36–50 / turn · snap 0.2–0.35 · damping 0.1 · click off | fluid.light |
| `detent.list` | Feel | SAW · 20 / turn · snap 0.5–0.6 · damping 0.15 · click on (4 ms) | SINE 20, click off |
| `detent.coarse` | Feel | SAW · 8–12 / turn · snap 0.75–0.9 · damping 0.2 · click on | SINE, snap 0.5, click off |
| `detent.fine` | Feel | SAW · 43–67 / turn · snap 0.15–0.25 · fine click | SINE, click off |
| `fluid.scrub` | Feel | VISCOSE · damping 0.45–0.6 | same |
| `fluid.orbit` | Feel | VISCOSE · damping 0.15–0.25 · free spin on | free spin off |
| `free.spin` | Modifier | release > 720°/s, recapture < 180°/s, events suppressed | off |
| `wall` / `wall.soft` | Boundary | spring wall, stiffness high / medium, no click | same |
| `feel.fade` | Modifier | snap 0 → target over 120 ms, grid re-anchored at current angle | same |
| `nudge.left` / `nudge.right` | Event | signed bump, 1 × 6 ms | unsigned tick |
| `confirm.tick` | Event | 1 × 4 ms click + ring-down | 50 % |
| `confirm.thump` | Event | 25–40 ms deep pulse | confirm.tick |
| `refuse.buzz` | Event | 3 × 5 ms, 30 ms apart | single nudge |
| `error.buzz` | Event | 3 × 8 ms, 70 ms apart | single nudge |

Snap and damping are normalised 0–1 of the firmware's range; tune on hardware and keep the ratios.

## Haptic map (summary)
The full table with ends, events, sound, LED pairing and fallbacks is the **Full map** tab.
| Context | Build | Feel | Density | Events |
|---|---|---|---|---|
| Home volume | v1 | detent.value | 36 / turn | wall.soft at 0 / 100 |
| Home tap 4 | v1 | — | — | confirm.tick |
| Home hold 4 swap | v1 | detent.value → detent.value | 36 → 50 | confirm.thump + feel.fade |
| Recently Added / Playlists | v1 | detent.list + free.spin | 20 | click per item, wall, tick on source switch |
| Tracks (queue) | v1 | detent.list | 20 | click, wall, nudge on jump, buzz at playing row |
| Seek | v1 | fluid.scrub | — | wall at 0:00 / end, thump on Set |
| Up next | v1 | detent.list | 20 | tick on shuffle / like, buzz on re-like |
| Queued / Play next | v1 | — | — | confirm.thump on hold landing |
| Window picker | v1 | detent.coarse | 12 | click (tick-thud), wall |
| Snap left / right, Switch | v1 | — | — | nudge.left / nudge.right, thump |
| Brightness | v1 | detent.value | 50 | wall.soft at 1 / 100 |
| Colour temperature | v1 | detent.fine | 43 (100 K) | fine click, wall |
| All off / Turn on | v1 | — | — | soft thump / thump |
| Scenes | v1 | detent.coarse | 12 | click, wall, thump on Run |
| Hold 1 → Home | v1 | → volume | — | thump + feel.fade |
| Screen changes | v1 | per context | — | feel.fade only |
| List ends | v1 | — | — | wall, silent |
| Sleep / wake | v1 | fluid.light → context | — | first touch wakes only; detents fade in 150 ms |
| Moments (skip, started, liked, shuffle, refused, error, snapped, queued, swapped) | v1 | — | — | see Moments tab |
| Onshape zoom / orbit / pan / undo | later | detent.value / fluid.orbit / fluid.scrub | 24 / — / — | feel.fade on hold, tick / buzz on undo |

**Later (not v1):** Seek return magnet; brightness 50 % landmark; common-white landmarks (2700 / 4000 / 5000 K); Like "heartbeat"; all Onshape contexts.

## Open questions
1. **Snap and damping units.** The map uses 0–1 of the firmware range. Please confirm the firmware's actual ranges so the tokens can carry real values.
2. **Free-spin thresholds** (720°/s release, 180°/s recapture) are guesses; tune on hardware, and confirm free spin never engages on value contexts (volume, brightness).
3. **Brightness density.** 50 / turn means two full turns for 1–100 %. Is that too slow for daily use? The alternative is 36 / turn with a 2 % step above 20 %.
4. **Click sound.** Should the audible click follow the haptic click, or only play in a "desk" mode? Motor clicks are already audible at high snap.
5. **Power.** How many thumps per minute are safe on USB power before we should rate-limit confirmations?
6. **Reduced haptics** as a companion setting, a knob gesture, or both?
7. **Onshape bindings.** Holding 2 / 3 to orbit / pan conflicts with the r3.1 meaning of buttons 2 / 3 inside spaces; Onshape would need to be its own space (a fourth launcher slot?).
