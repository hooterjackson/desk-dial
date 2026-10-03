# Nano_D r3 design: gap audit against the build

Audited 2026-09-29, 00:30–00:40. This audit only read the code; it changed nothing. Item IDs refer to `r3-design-spec-checklist.md`.

**What was compared**
- App: `app/control_center/`.
  - `controller.py` changed during the audit: line numbers moved about 10 lines between 00:30 and 00:35. **The line numbers here are from 00:35. Search for the function name if a line has moved.**
  - `navigator_model.py` was created at 00:31:44 by the Navigator job.
- Firmware: `firmware/src/` (cc_display.cpp and cc_frame_parse.cpp 09-28 17:54–17:55; cc_alive.cpp/h 09-28 21:27; cc_icons 09-28 17:57).
- Harness: `harness/r3-handoff/` (contact sheet and r3_screens.json, 09-28 21:28).
- Specs: `CONTROL_CENTER_V5.md` Appendix B, `PRESENTATION_V5.md` §19 (§19.8 lists what was deferred), `ALIVE.md` §15.

**Release plan versus what the user expects.** Appendix B, 1835 says release 1 left out two groups of work:
- **R2**: arc breadcrumbs, the new Music/Tracks/Seek maps, the overshoot guard and the unavailable-press flash.
- **R3**: the Navigator.

`PRESENTATION_V5` §19.8 also defers the amber line tone, the active-mode footer ink, and the hold-1 progress ring.

The user expects the **full r3 experience in the first delivery**. Every R2 and R3 item is therefore graded below as a gap, not as "deferred". Only items the user switched off by decision are "Deferred-by-decision":
- the 1b/1c Home options, the 1d Lights option, and the v1 path, pips and ring breadcrumb variants;
- the 0.08 / 0.12 unfilled arcs (ruled OFF).

Status key: **Impl** Implemented · **Partial** · **Missing** · **Wrong** · **DbD** Deferred-by-decision.

---

## A. Broken or missing core flows the user will hit

| # | Items | Status | Evidence | What is wrong or missing | Owner |
|---|---|---|---|---|---|
| A1 | NV-1…NV-24, MO-7…MO-9, ST-5 | **Missing** (only the model exists) | `control_center/navigator_model.py` (453 lines, new at 00:31) holds the content and `Visibility`. Nothing imports it: a grep of `control_center/` and `tests/` finds no `navigator` outside the file itself. There is no window, renderer, glass, animation or Settings entry. `ui.py:44`, `:132` and `runtime.py:2189` still summon the **floating knob** for every knob. | The Navigator is wholesale absent on screen. The floating knob still shows for a presentation-6 knob (NV-1). Still to build: the DirectComposition acrylic surface (NV-7…NV-12), Archivo type (NV-13), every card (NV-15…NV-20), the keys grid (NV-21), the show/hide and content-swap motion (MO-7…MO-9), and the Settings choice Auto-hide / Pinned / Off, persisted (NV-6, ST-5). | Navigator job |
| A2 | G-8, CP-5, ST-4 | **Missing** | `controller.py` `_press_launcher` (2039): `logical == 0` → `_new_screen("home", …)` with no time check. There is no `homeArrivedAt`: a grep for "again for", "overshoot" and "home_arrived" finds nothing. | Mashing 1 from Tracks goes Tracks → Music → Home → **Music**. Needed: record the arrival time on every arrival at the launcher (1 from Music, Windows or Lights; hold; picker Back or Switch). Ignore a 1 within 700 ms and set the transient `Home · press 1 again for Music` (status line, secondary, 1.4 s). | controller job |
| A3 | G-5, G-4 | **Wrong** (grammar) | Firmware `hmi_thread.cpp:455–501`: button 1 emits `kd` on `kEventPressed`. `kh` follows at 600 ms (`kHoldMs`, :63) with "no suppression" (:335). Controller `hold` (1352) runs after the press has already acted. | r3 acts on 1 **on release** and a hold **suppresses** the tap (P `bDown`/`bUp` L495–507). Today, holding 1 on Home jumps to Music and then back to Home (a visible flicker plus a slide pair). Holding in Lights, Windows or Music acts on Back/Home first. Fix one of two ways: (a) firmware sends a click for slot 0 on release when no `kh` fired (protocol change, presentation 6); or (b) the host defers slot-0 `kd` until `ks` shows the release, and drops it if `kh` arrives. Either way, the overshoot guard (A2) must also cover arrivals by hold. | firmware + controller |
| A4 | G-7, LED-7, ST-4 | **Missing** | `PRESENTATION_V5.md` §19.8 ("the hold-1 progress ring: release 2"). No hold progress in `cc_alive.cpp` (the only "hold" there is the moment-sleep hold, `holdMs_`). `hmi_thread.cpp` has no progress output. | While 1 is held away from Home, the ring must fill a warm arc 0 → 100 % over 600 ms on the 45-segment arc (38 → 22), visible after 12 %. It must be firmware-local, because the host sees nothing until `kh`. On maturing: a warm full-ring flash, 400 ms (G-6). Also missing. | firmware (cc_alive) |
| A5 | BM-6, CP-2, CP-4, CP-10, R22-4, ST-3 | **Wrong** | `_press_seek` (3043): 1 **and** 3 both `_leave_seek(flush=True)`, so 1 *keeps* the scrubbed position. `_send_seek` fires 250 ms after each detent (the r2.2 live scrub). There is no `seekFrom` restore. `_buttons_seek` (1933) labels 1 Back and 3 Seek (lit). | r3 Seek: 1 = **Cancel**, restoring the position from before Seek (`Seek cancelled`, 1.4 s). 3 = **Set** (`Seek set` `#7EE0A2` + green flash). 4 disabled with the reason. Because Sonos needs 2.7–5 s to land, the clean build defers the `seek` request until Set (or sends a restore seek on Cancel if a scrub was already sent). The labels, the Navigator keys (`Exit seek · Up next · Set · Skip`) and the LCD status (S-9) follow from this. | controller job |
| A6 | G-9, CP-1, CP-2 | **Wrong** | `_reason` (1666–1669): the codes `neutral` and `seeking` return `None`, so the press is **ignored silently**. | Skip at Now must say `Turn to pick previous or next` (`#FF8474`, 2 s). Skip in Seek must say `Set or cancel seek first`. Both flash red. These are the design's own examples of the global unavailable rule. | controller job |
| A7 | G-9, LED-8 | **Wrong** | `cc_alive.cpp:638–642`: `CC_FLASH_ERR` = red on 5 segments **around the cursor** (±2, edges 0.5) for `flashErrMs` = **900 ms** (`cc_presentation.h:209`). §19.8 defers "the unavailable-press bottom flash". | r3: bottom segments **26–34** red `255,60,40` at L 0.9 for **320 ms** on every unavailable press. It replaces the r2.2 flash and head shake. Needed: a flash kind (or a family-independent rule for `err` from a refused press), mirrored in `alive_lights.py`. Note that the host sends the same `err` for real failures. Decide whether those keep the cursor flash; the design only defines the refused press. | firmware + alive_lights |
| A8 | BC-1…BC-6 | **Missing** | No arc or path rendering in `cc_display.cpp`: only the flat `HEADING` box at y 31, 138 px (:60), and `showHeading` (:743). No arc bitmap assets in `cc_icons`. The controller sends flat single-level headings: `MUSIC`, `RECENTLY ADDED`, `TRACKS`, `SEEK`, `LIGHTS`, `SCENES` (`_frame_home` 4126+, `_frame_tracks` 4306, `_frame_seek` 4363, `_frame_lights` 4483, `_frame_scenes` 4545). | The user chose the Arc, pre-rendered. Needed:<br>• Pre-rendered A8 arc bitmaps for the nine paths (BC-5): r 94, path `M26 120 A94 94 0 0 1 214 120`, Montserrat 500 12 px caps, 0.96 px tracking, ancestors `#7C7C7C` + ` › `, current `#E6E6E6`, centred at the apex.<br>• A wire token for which path to show.<br>• Hidden on Home and in idle; 200 ms fade.<br>Heading changes that come with it: Seek keeps `MUSIC › TRACKS` (not `SEEK`); explorer is `MUSIC › RECENT › ON SCREEN` / `MUSIC › PLAYLISTS › ON SCREEN`; Up next is `MUSIC › TRACKS › UP NEXT`. Two-colour rendering needs either two masks or a two-tone bitmap. | firmware + controller |
| A9 | S-7, S-8, CP-9 | **Wrong** | `_frame_tracks` (4306–4360):<br>• At Now: title `Turn to choose` (`knob.title.tracks.choose`, COPY:215), sub `Now: {title}`, meta `{i} / {n}`.<br>• Turned: titles `Previous track` / `Next track` (COPY:216–217), sub `Next: {neighbour}` / `Prev: …`.<br>• The firmware draws the r2.2 `tracks` layout (position row at 88).<br>The contact sheet has no Tracks screen. | r3 Tracks is a **text layout**.<br>• At rest: title = **current song**, sub = artist, meta `Turn for previous or next` `#7C7C7C`.<br>• Turned: title `Previous` / `Next`, sub `Now: {song}`, meta `Press 4 to skip`.<br>The user sees it on every Tracks visit. The Navigator rows card also shows the wrong status: it reads `frame.meta`, so it would show `3 / 12`. | controller (+ firmware if the layout changes) |
| A10 | NV-18 | **Partial** | `navigator_model.py` `NEIGHBOURS_NOTE`: the controller keeps only P±1 titles (`_neighbours`, private). Rows ±2 render `—`. | The Tracks card needs 5 titles with wrap-around. It needs the accessor `Controller.queue_titles(rows)` that the model asks for, filled from the queue read. | controller job |

## B. Visual and copy mismatches

| # | Items | Status | Evidence | What is wrong |
|---|---|---|---|---|
| B1 | LED-12, LED-13, G-2 | **Wrong** (confirm against the rulings) | ALIVE.md §15.4: "Button 4 `power` is tone nav (**WARM 0.70**)". Nav buttons elsewhere are r2.2 warm 0.70, disabled warm 0.14. The contact sheet shows orange strips on every nav button. | r3 button LEDs are nav **white L 0.34**, disabled 0.12, commit green 0.68, active warm 0.9. `HOT = WARM` / "steady warm rest" may be meant to override this. If not, nav and disabled should be white at 0.34 / 0.12, and green should be 0.68 (`110,217,150`), not 1.0 (`0,255,98`). **Ask the user; do not change silently.** |
| B2 | G-2, L-8 | **Wrong** | `presentation.button_tone_v5` (~line 333): slot 3 `play` → `go`, so Home and Music 4 are **green while paused**, in the LED and the footer. The idle row `Play` is green on the contact sheet (`home-idle`). | The prototype keeps Play/Pause **nav** on Home and Music (bc `w2`, P L634/L644/L660). The idle row is all nav (P L762). Green is for commits only (README §1). |
| B3 | S-12, TK-2, CP-6, S-9 | **Wrong** (deferred in §19.8) | `_frame_lights` (4534): `Knob: temperature` is sent as `secondary` (`#A6A6A6`). The wire has no warm line tone (Appendix B.4). | `Knob: temperature`, the Seek status, `Shuffle on/off` and 1d's `Runs in 1 s` use **`#FFBE69`**. Needed: an append-only `warm` line tone in firmware, `lcd_preview` and `device.py` validation. |
| B4 | L-9 | **Wrong** (deferred in §19.8) | The firmware's lit-on footer ink is `#FFFFFF` (PRESENTATION_V5 §19.4). | The active-mode icon (Temperature on, the active explorer tab, Seek, Shuffle on) should be **act `#FFBE69`**. |
| B5 | IC-7, BM-8 | **Wrong** | `_buttons_windows` (2002): `_btn("back", "Back")`. | Windows 1 is **Home** (a space root): icon `house`, label `Home`. It already goes to the launcher. |
| B6 | IC-1 | **Wrong** | `_buttons_explorer` (~1877): tab 2 icon `clock`. | r3 replaces it with **album** (square + disc) for Recently Added / explorer tab 2, matching Music 2. |
| B7 | S-9 | **Wrong** | `_frame_seek` (4363–4382): meta `of {m:ss}` (`knob.line.seek.length`, COPY:222). Heading `SEEK`. Ring `lap`. | Needs `of {dur} · 3 sets · 1 cancels` in amber, the heading/arc `MUSIC › TRACKS`, and an LED warm arc of pos/dur on the 45-segment arc (P L680). The r2.2 lap is acceptable if the rule is kept, but it is not the r3 look. |
| B8 | LED-9 | **Wrong** | `_frame_windows`: `_selection_ring(…, "window")` gives r2.2 app-colour landmarks and a cursor. | r3 §3: a **white** marker at the window's position and the rest **warm L 0.1**, on the arc. |
| B9 | LED-10 | **Partial** | Recently Added and explorer use r2.2 landmarks (3 apart, item colours 0.45) and a cursor at 1.0. | r3: a ±1 marker in the album's dominant colour at 1.0, the rest of the arc in that colour at 0.1. The list colour rule is kept, so this is a look difference. |
| B10 | MO-1 | **Wrong** | `cc_display.cpp` `groupOf` / `depthOf` (988–1016): the launcher and Music are both `GROUP_HOME`, depth 0 (same `nowPlaying` layout). Windows is 5, Recent 1, explorer and Up next 30. | Home → Music (depth 0 → 1) must **slide in from the right**. Today only the heading pops in. Needed: a depth hint on the wire (for example `depth` or the arc path id) instead of inferring it from the layout. Windows should be depth 1. |
| B11 | BM-8, CP-8 | **Partial** | Windows copy is r2.2's: `Left: {App} · pick right`, toasts `{App} · {Title}`, `Side by side · …` (COPY:198–284). | r3 copy: `Snapped left` / `Snapped right` / `Switched to {app}`. The picker overlay itself is unchanged r2.2, so this only concerns the knob and Navigator lines. |
| B12 | NV-17 | **Wrong** | `navigator_model._keys` takes the labels from the frame: Recently Added 2 = `Open`. | The keys should read `Back · Full screen · Play next · Play`. |
| B13 | NV-19 | **Wrong** | The Seek keys come from `_buttons_seek` labels: `Back · Up next · Seek · Skip`. | The keys should read `Exit seek · Up next · Set · Skip(40 %)`. Fixing A5 fixes this. |
| B14 | NV-16 | **Partial** | `navigator_model.build_content` "lights" adds `status = frame.meta`. The offline state has caption = title and big `—`. | The prototype's Lights card has no status line (P L103–120). Harmless, but the offline card is not designed. Keep it minimal. |
| B15 | S-1, BC-4 | **Impl** (check) | The launcher sends no heading. Music sends `MUSIC` (`_frame_home`, 4164). | Correct for the flat heading. With the Arc (A8), the launcher still shows none. |
| B16 | BM-3 | **Partial** | The Recently Added Play lands on Music (`_press_recent`) with r2.2 `Starting…` and moments. | The prototype says `Queue replaced`. r2.2's start copy is fine (the README keeps r2.2 copy). Note only. |
| B17 | LED-12 (Scenes 2/3) | **Impl** | `_buttons_scenes` (1825): icon "" → tone none. The contact sheet shows the strips dark. | Matches `o` (no LED, no icon). |

## C. Polish

| # | Items | Status | Evidence | Note |
|---|---|---|---|---|
| C1 | LED-16 | **Partial** | Tracks ring = r2.2 `transport` (Prev 52+53 / Neutral 0 / Next 7+8). | The prototype shows the half ring green 0.9 while turned. It is not in the README §3 table, so it is optional. |
| C2 | LED-15 | **Impl** (r2.2) | The Home/Music volume ring is r2.2 `level` (from 35, amber/red). | The prototype uses the warm 45-segment arc. README §0 keeps the r2.2 LEDs, so no change. |
| C3 | LED-19 | **Impl** (r2.2 moments) | Skip, start, snap and like use r2.2 moments. | The prototype's full-ring flashes are placeholders. r2.2 wins. |
| C4 | CP-7 | **Partial** | `toast.scene.ok` `Lights · {scene}` and `toast.scene.failed` (controller:325, `_scene_run_result` 2266+). | The design has no toast for scenes. README §12.5 leans to the Navigator only. With the Navigator on screen, this toast duplicates it; consider dropping it. |
| C5 | LED-11 | **Impl** | `cc_kelvin_rgb`, `presentation.kelvin_rgb`, `navigator_model.kelvin_rgb`: exact formula (3200 K = 255,184,123 against the README's approximate 255,183,112). | Fine. `CC_KELVIN_GAIN` calibration is still a by-eye step. |
| C6 | NV-12 | **n/a** | The model computes no ambient fill. | Correct: the prototype's `nav.amb` is never drawn. |
| C7 | MO-4, L-8 | **Impl** | The idle row with the bulb at 26 px is on the contact sheet. | Only the Play ink is wrong (B2). |
| C8 | G-13 | **Unverified** | Picker entry index from the launcher was not checked (r2.2 logic). | The prototype preselects index 1 from Home. |

## Implemented (checked, no action)

| Items | Evidence |
|---|---|
| H-1, BM-1 launcher map and volume knob | `_buttons_launcher` 1805, `_press_launcher` 2039, `VOLUME_MODES`, `PROFILES["launcher"]` BINARIS BEER |
| BM-2 Music map | `_buttons_home` 1793 (house / album / tracks / play-pause), `_press_home` 2018 |
| BM-3, BM-4, BM-7 Back targets | Recently Added → Music (`_press_recent` `_go_home`); explorer → knob list, same album (`_close_explorer`); Up next → Tracks (`_close_upnext`) |
| BM-8 Windows 1 / Switch → Home | `_close_windows` 1588 → `_root()` (icon wrong: B5) |
| BM-9 Lights map | `_buttons_lights` 1813: house / wand / thermo lit / power |
| BM-10 Scenes map | `_press_scenes` 2089; 2/3 refused with `Turn to choose · 4 runs it` in error tone |
| BM-12 knob modes | `_press_lights` 2065, lit on |
| G-11 brightness on entry | `_enter_lights` 2050 |
| BM-13, HA-4, HA-5 All off / Turn on snapshot | `home_assistant.power` (474–497): `scene.create desk_dial_snapshot` → `turn_off`; Turn on = `scene.turn_on` snapshot |
| BM-14, BM-15 turning while off; 1..100; 100 K | `_lights_turn` 2116, `bounds()`, `set_light(on_bri=…)` |
| HA-1…HA-3, HA-6, HA-7 | `home_assistant.py` allowlist `_guard`, WebSocket `subscribe_events`, ≤ 10 Hz (`LIGHTS_WRITE_INTERVAL` 0.1), external reveal 2.6 s, profiles (`LIGHTS_TEMP_PROFILE` MIDI SKIPPER) |
| S-12…S-15 Lights and Scenes screens | `_frame_lights`, `_frame_scenes`; the contact sheet matches the layouts and copy (except the amber tone, B3) |
| LED-1…LED-6 Lights rings | ALIVE §15.2 and `cc_alive`; unfilled OFF per the user ruling (**DbD**); wash 700 ms 0.68 (§15.5) |
| LED-12 active mode warm 0.9 | ALIVE §15.4 (Lights only) |
| IC-1…IC-5, IC-8…IC-10 r3 icons | `cc_icons.cpp` bulb, thermo, power, wand, house, album; `list` = music notes; `switch` = check |
| Navigator model rules NV-3…NV-6, NV-14, NV-15, NV-20…NV-23 | `navigator_model.py` (content and visibility only; not rendered: A1) |

## Deferred by decision (not gaps)

- H-2, H-3, H-4 (Home 1b and 1c).
- BM-11, S-16 and the 1d copy (Lights 1d selector).
- BC-7, BC-8 (the v1 path, pips and ring breadcrumbs).
- The 0.08 / 0.12 unfilled Lights tracks in LED-2 and LED-3 (user ruling 2026-09-29).
- LED-14: the prototype's rest at warm 0.12 is replaced by the standing steady-warm-rest ruling.
