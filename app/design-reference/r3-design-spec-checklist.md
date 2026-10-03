# Nano_D r3 design: requirement checklist

Source: `Nano D Control Center UI MockupsV3.zip` → `design_handoff_nano_d_r3/`, extracted 2026-09-29 00:30.
- **README** = `design_handoff_nano_d_r3/README.md` (§ numbers).
- **P:Lnnn** = `prototypes/Knob IA Prototype.dc.html`, line nnn. Functions: `tap()` L514–578, `turn()` L472–494, `bDown/bUp` L495–507, `renderVals()` L590–876, the Navigator block L790–837.
- **R22** = `reference_r2.2/` (README, specs/01, specs/03). r3 inherits these where it says "unchanged from r2.2".

The user's decisions narrow the design. Items that the decisions switch off are marked **[OFF]** and kept for completeness:
- Home **1a Launcher**.
- Lights **1e Scenes list**.
- Breadcrumbs **Arc**, pre-rendered.
- Navigator **now**, with Auto-hide as the default.
- One fixed light group, reached through Desk Dial to Home Assistant.
- Standing LED rulings:
  - Unfilled Lights arcs are **OFF** (2026-09-29). This overrides 0.08 and 0.12.
  - The ring rests at a steady warm level.
  - HOT = WARM.
  - Dither is off, with a floor.
  - Sleep follows after 10 or 60 minutes.

---

## 1. Global rules (README §1 "Global rules")

| # | Requirement | Source |
|---|---|---|
| G-1 | **Button 1 goes out**: at a space root it goes Home, deeper it goes Back one level. | README §1; P `tap()` L529, L534, L539, L544, L552, L559, L565, L573 |
| G-2 | **Button 4 acts**: it is the primary action of the screen (Play/Pause, Play, Skip, Switch, Run, All off). It is green only when it *commits* something. Play/Pause and All off/Turn on are **not** green (P bc = `w2` on Home, Music and Lights, L634/L712). | README §1; P L666, L673, L682, L691, L700, L712, L723 |
| G-3 | **Button 2 opens** the next level or a full-screen view where one exists. | README §1 |
| G-4 | **Hold 1 (600 ms)** goes Home from anywhere and closes any overlay. At Home a hold does nothing: the guard is `space !== 'home'`. | README §1; P L499 |
| G-5 | **Button 1 acts on release, not on press.** A press arms a 600 ms timer. On release before 600 ms, `tap(0)` runs. A matured hold **suppresses** the tap (`_held`). Buttons 2–4 act on press. | P `bDown` L495–503, `bUp` L504–507 |
| G-6 | When a hold matures (away from Home), it records `homeArrivedAt = now` and plays a **warm full-ring flash** (`255,190,105`) for **400 ms**. | P L499, L737 (flash without segs = `R.fill(c, 0.68)`) |
| G-7 | **Hold-1 progress ring**: while 1 is held away from Home, a warm arc fills 0 → 100 % over 600 ms on the 45-segment arc. It shows only after 12 % (about 72 ms), at L 1.0 for the filled part and 0.08 for the unfilled part. It replaces the ring while shown. | README §1, §3; P L736 |
| G-8 | **Overshoot guard**: a tap on 1 within **700 ms** of arriving Home, via 1 (from Music, Windows or Lights) or via a hold, is ignored. The status line then reads `Home · press 1 again for Music` (`#A6A6A6`, 1.4 s). | README §1; P L518 (check), L529/L559/L565/L499 (`_homeAt` set) |
| G-9 | **Unavailable buttons** stay in place, dimmed. A press does nothing except show the reason (§6 copy, `#FF8474`, 2 s) and flash **bottom ring segments 26–34 red `255,60,40` at L 0.9 for 320 ms**. This replaces the r2.2 full-ring flash. | README §1, §3; P `deny()` L459 |
| G-10 | A transient message replaces the status/meta line (`v.st`) on every non-"big" layout. The default length is 2000 ms. | P L460, L728 |
| G-11 | Entering Lights from Home always starts in **brightness** mode. | README §1.2; P L467 |
| G-12 | Leaving Tracks for another space turns Seek off (`seek = false`). | P L469 |
| G-13 | Entering Windows from Home preselects index 1, the next window after the focused one. | P L468 |

## 2. Home options (README §1.1)

| # | Requirement | Source |
|---|---|---|
| H-1 | **1a Launcher**: the knob is **volume, always**. The map is 1 Music · 2 Windows · 3 Lights · 4 Play/Pause. | README §1.1, §1.2; P L481, L517–527 |
| H-2 | [OFF] 1b Double-tap 4: a ≤ 300 ms double tap swaps the domain (`Knob sets brightness` / `Knob sets volume`, amber, 1.8 s, flash `255,214,160` / warm). Single taps are delayed 300 ms. | README §1.1; P L521–525 |
| H-3 | [OFF] 1c Follows last: the Home domain is whichever of Music or Lights was entered last. | README §1.1; P L462, L466–467 |
| H-4 | [OFF] The Home Lights domain shows label `LIGHTS`, title = scene, sub `Hall · {bri}% · {K} K`, or `Lights off` / `Tap 4 to turn on`. | README §1.1; P L648–652 |

## 3. Button maps (README §1.2, 1a + 1e rows)

| # | Screen | Knob | 1 | 2 | 3 | 4 | Source |
|---|---|---|---|---|---|---|---|
| BM-1 | Home (1a) | Volume | Music | Windows | Lights | Play/Pause | README §1.2; P L517–527, L644–655 |
| BM-2 | Music | Volume | Home (sets `homeArrivedAt`) | Recently Added (at item 0, source recent) | Tracks (trackPos 0, seek off) | Play/Pause | P L528–532, L657–661 |
| BM-3 | Recently Added (knob list) | Scroll | Back → Music | Full screen (explorer) | Play next (green flash, `Plays next · {album}` `#7EE0A2`) | **Play** (replaces queue) → Music, green flash 600 ms, `Queue replaced` | P L533–537, L663–668 |
| BM-4 | Music explorer (screen) | Scroll covers | Back → knob list, same album | Recently Added tab | Favourite playlists tab | **Play** → Music | P L538–542, L670–675 |
| BM-5 | Tracks | Prev · Now · Next (−1/0/+1, clamped) | Back → Music | Up next (screen, focus = playing) | Seek (enter; stores `seekFrom`) | **Skip** (disabled at Now and in Seek) | P L543–550, L677–685 |
| BM-6 | Seek (a Tracks mode) | Scrub **±5 s per detent**, clamped to 0..dur−1 | **Cancel**: restores `seekFrom`, `Seek cancelled` 1.4 s | Up next | **Set**: `Seek set` `#7EE0A2` 1.4 s + green flash 400 ms | disabled (`Set or cancel seek first`) | README §1.2; P L485, L544, L546–547 |
| BM-7 | Up next (screen) | Scroll queue | Back → Tracks | Shuffle (`Shuffle on/off` amber 1.4 s) | Like (add-only; a liked row gives `Unfavourite in Music app`) | **Play** this track | P L551–557, L687–694 |
| BM-8 | Windows (picker on screen) | Scroll windows | **Home** (restores focus; sets `homeArrivedAt`) | Snap left | Snap right | **Switch** → Home, `Switched to {app}` | README §1.2; P L558–562, L696–703 |
| BM-9 | Lights (1e) | Brightness · Temperature (when 3 is lit) | Home (sets `homeArrivedAt`) | Scenes list (focus = the current scene) | Temperature on/off (toggle; `Knob: temperature` / `Knob: brightness`, amber 1.4 s) | All off / Turn on (`Lights off` / `Lights on` 1.4 s) | README §1.2; P L563–571, L705–718 |
| BM-10 | Scenes list (1e) | Scroll automations | Back → Lights | — (unavailable: `Turn to choose · 4 runs it`) | — (same) | **Run** → Lights, `Scene running` | README §1.2; P L572–576, L720–726 |
| BM-11 | [OFF] Lights 1d | Brightness · Temperature (2 lit) · Scenes (3 lit) | Home (cancels a pending scene first: `Scene cancelled`) | Temperature | Scene selector | All off / Turn on | README §1.2; P L564–569 |
| BM-12 | Lights modes are **knob modes, not menus**. The lit button (warm L 0.9) shows the mode. Tapping it again returns to brightness. | | | | | | README §1.2; P L567 |
| BM-13 | **All off** snapshots the current state. **Turn on** restores that snapshot, not a default scene. | | | | | | README §1.2, §7 |
| BM-14 | **Turning while off** turns the light on at 1 % (brightness), or at the stored level with the new temperature. Any turn clears `adjusted`→true and cancels a pending scene. | | | | | | README §1.2; P L478–479 |
| BM-15 | Brightness is clamped 1..100 while on. Temperature is 2200..6500 in 100 K steps. | | | | | | P L478–479 |
| BM-16 | After a Tracks skip: np ± 1 (wrapping), trackPos → 0, green flash 500 ms, `Skipped · back at neutral` `#7EE0A2`. | | | | | | P L549 |
| BM-17 | Windows snap: that side gets the window. If the other side held it, the sides swap. Flash in the app colour for 600 ms, `Snapped left/right` `#7EE0A2`. | | | | | | P L560–561 |
| BM-18 | Scene run (`applyScene`): scene index set, bri/K = the scene's, on, `adjusted` false, green flash 700 ms, `Scene running` `#7EE0A2` 2.2 s. | | | | | | P L455–458, L575 |

## 4. Knob LCD (README §2; P L298–338)

### 4.1 Shared geometry and layers (R22 specs 03/01 §3, P L298–338)
| # | Requirement | Source |
|---|---|---|
| L-1 | 240 × 240 round, Montserrat 500, ink `#F2F2F2`. Text shadow `0 1px 0 rgba(0,0,0,.8)`. | P L298, L301 |
| L-2 | Art layer at 0.8 opacity. Scrim: black 0.60 / 0.72 / 0.92 / solid at 0 / 45 / 62 / 70 %. Both fade in 300 ms. | P L299–300; R22 01 §3 |
| L-3 | **Text layout**: title 22/26, 2 lines (clamp, balance), x 35 w 170, top 60. Sub 14/18 `#A6A6A6`, top 114. | P L310–311 |
| L-4 | **Big layout**: caption 14/18 `#A6A6A6` top 52. Value 48/46, tabular, −0.02 em, top 76. Unit 22 px `#A6A6A6`, gap 3. | P L313–315 |
| L-5 | **List layout**: prev 14/18 `#7C7C7C` top 56. Current 22/26, one line, x 30 w 180, top 78. Next 14/18 `#7C7C7C` top 108. | P L317–320 |
| L-6 | Status/meta line: 12/14, x 30 w 180, top 134, colour per state. | P L330 |
| L-7 | Footer: 4 slots at x 34 / 77 / 119 / 162, top 152, 44 × 24. Icons 20 px, stroke 2.3, fill for a liked heart. | P L331–336, L751–752 |
| L-8 | Idle icon row: 4 columns of 46 px at x 28..212, top 100. Icons 26 px, stroke 2.1, 12 px labels, all **nav `#E6E6E6`** (Play is not green). | P L322–329, L762 |
| L-9 | Footer icon colours: nav `#E6E6E6`, ok `#6ED996`, no `#FF8474`, dis `#5A5A5A`, **act `#FFBE69`** (the active mode or tab), pink `#A3244A`. | P L607 |

### 4.2 Screens (README §2.2)
| # | Screen | Requirement | Source |
|---|---|---|---|
| S-1 | Home (music) | r2.2 Home: title = song 22/26 top 60, artist 14 top 114, `Paused` status when paused. Art behind. No breadcrumb. | README §2.2; P L645–647 |
| S-2 | Home volume reveal | Big: caption = song or `Paused · {song}`, value = volume, `%`. Status `Minimum` / `Maximum` at the limits. Hides 1.4 s after the last detent. | P L476–477, L635 |
| S-3 | Home idle | Shown when paused, 4 s after the pause, with no message: the icon row `Music · Win · Lights · Play`, no art, ring warm 0.06, status and footer hidden, arc hidden. | README §2.2; P L647, L738, L760, L857 |
| S-4 | Music | Same as Home plus breadcrumb `MUSIC`. Art behind (scrim, full black ≥ 70 %). Footer home / album / list / play-pause. | README §2.2; P L657–661 |
| S-5 | Recently Added | List: prev/current/next album titles. Meta `{i} / {n}` `#7C7C7C`. Art = the focused album. Footer back / expand / listPlus / play (ok). | P L663–668 |
| S-6 | Explorer mirror | List as S-5. Label `ON SCREEN`. Footer back / album (act if the Recent tab) / listMusic (act if Playlists) / play (ok). | P L670–675 |
| S-7 | Tracks at rest | **Text layout**: title = **current song**, sub = artist, meta `Turn for previous or next` `#7C7C7C`. | README §2.2; P L681 |
| S-8 | Tracks turned | Title `Previous` / `Next`. Sub `Now: {song}`. Meta `Press 4 to skip`. Footer 4 = skipB/skipF in ok. | README §2.2; P L681, L683 |
| S-9 | Seek | Big: caption = song, value `m:ss` 48 px, **no unit**. Status `of {dur} · 3 sets · 1 cancels` in `#FFBE69`. Label stays `TRACKS`. Footer 3 = seek in act. | README §2.2; P L680, L683 |
| S-10 | Up next mirror | List of the album's tracks. Meta `{i} / {n}` + ` · playing`. Footer back / shuffle (act) / heart (pink, filled if liked) / play (ok). | P L687–694 |
| S-11 | Windows | Title = window title, sub = app, meta `{i} / {n}` `#7C7C7C`. Footer **home** / snapL / snapR / check (ok). | P L696–703 |
| S-12 | Lights | Text: title = scene name, or `{scene} · adjusted` after a manual change. Sub `{bri}% · {K} K`. Meta `Knob: temperature` **`#FFBE69`** in temperature mode. | README §2.2; P L628, L710 |
| S-13 | Lights turning | Big: caption `Brightness` + value + `%`, or `Colour temperature` + value + `K`. Hides 1.4 s after the last detent. | README §2.2; P L636–637, L711 |
| S-14 | Lights off | `Lights off` / `Tap 4 to turn on`. Ring off. | README §2.2; P L709 |
| S-15 | Scenes (1e) | List: prev 14 `#7C7C7C` top 56, current 22 top 78, next 14 top 108. Meta `{i} / {n} · {bri}% · {K} K`, or `{i} / {n} · running now` when it is the current, unadjusted scene and the light is on. Footer back / — / — / check (ok). | README §2.2; P L721–724 |
| S-16 | [OFF] Scene selector 1d | Label `SCENE i / N`, list, `Runs in 1 s · 1 cancels` amber, or `Running · turn to choose` / `Turn to choose`. | P L708 |
| S-17 | Messages | Every non-big layout: the transient text and colour replace `v.st`. | P L728 |

### 4.3 Breadcrumbs (README §2.1)
| # | Requirement | Source |
|---|---|---|
| BC-1 | **Arc** (chosen): text on the path `M 26 120 A 94 94 0 0 1 214 120` (centre 120,120, r 94, 180° → 0° across the top), centred at the apex (`startOffset 50 %`, `text-anchor middle`). | README §2.1; P L852–856 |
| BC-2 | Type: Montserrat 500, 12 px, caps, letter-spacing 0.96 px (0.08 em). | README §2.1; P L854 |
| BC-3 | Ancestors in `#7C7C7C`, each followed by ` › `. The current level in `#E6E6E6`. | README §2.1; P L856 |
| BC-4 | It replaces the flat top label (`labelOp 0` when Arc is on). No breadcrumb on Home. Hidden in the idle icon view. Fades 200 ms ease-out. | README §2.1; P L307, L857 |
| BC-5 | Paths: `MUSIC` · `MUSIC › RECENTLY ADDED` · `MUSIC › RECENT › ON SCREEN` (or `MUSIC › PLAYLISTS › ON SCREEN`) · `MUSIC › TRACKS` (also in Seek) · `MUSIC › TRACKS › UP NEXT` · `WINDOWS` · `LIGHTS` · `LIGHTS › SCENES` (1e). | README §2.1; P L729 (ANC) + the labels in `renderVals` |
| BC-6 | LVGL route chosen by the user: pre-rendered A8 bitmaps per path. The fallback is v1 flat path + pips. | README §2.1 |
| BC-7 | [OFF] v1 flat path: row top 32, x 30–210, parent `#7C7C7C` + current `#A6A6A6`, gap 5. `RECENTLY ADDED` → `RECENT` when a parent shows. Pips 5 px at top 17, gap 5 (filled `#E6E6E6`, hollow inset `#5A5A5A`; Music 3, Lights 2, Windows 1 levels). | README §2.1; P L302–308, L731–734 |
| BC-8 | [OFF] Ring variant: 1–3 white segments at 30 / 29,31 / 28,30,32, L 0.7. | README §2.1; P L735 |

### 4.4 Icons (README §2.2 table; P L593–605)
| # | Requirement | Source |
|---|---|---|
| IC-1 | Album (square + disc) `M3 3h18v18H3zM12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 11.5v1`: Music 2 (Recently Added) **and explorer tab 2**. | README §2.2; P L598, L660, L674 |
| IC-2 | Wand + sparkles: Scenes (1e button 2). | README; P L598 |
| IC-3 | Thermometer `M14 4v10.5a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0z`: Temperature. | README; P L597 |
| IC-4 | Power `M12 2v10M18.4 6.6a9 9 0 1 1-12.8 0`: Lights 4. Always nav `#E6E6E6`, never red. | README; P L714 |
| IC-5 | Lightbulb (Lucide): Home 3. | README; P L595 |
| IC-6 | Music notes / Window: Home 1 / 2 (r2.2 icons). | README |
| IC-7 | House (Lucide): button 1 **at a space root**: Music, **Windows**, Lights. | README; P L660, L701, L714 |
| IC-8 | Chevron-left: button 1 deeper (Recently Added, explorer, Tracks, Up next, Scenes). | README; P L667, L674, L683, L692, L724 |
| IC-9 | Expand: open full screen (Recently Added 2, Tracks 2). | README; P L667, L683 |
| IC-10 | Explorer tab 3 = listMusic. Tracks 3 = seek scrubber. Play next = listPlus. Windows 4 / Scenes 4 = check. | P L667–724 |

## 5. Ring and LEDs (README §3; P L607–623, L736–750)

| # | Requirement | Source |
|---|---|---|
| LED-1 | The Lights arc is **45 segments clockwise from index 38 (7:30)** through the top to 22. Indices 23–37 stay free for signals. | README §3; P L615 |
| LED-2 | **Brightness**: filled `round(bri% × 45)` in the **Kelvin colour**, at L 0.34 at rest and 1.0 while turning. Unfilled L 0.08 per the design, **OFF per the user ruling of 2026-09-29**. | README §3; P L618, L710 |
| LED-3 | **Colour temperature**: marker at `round(p × 44)` at L 1.0, where p = (K − 2200)/4300. Filled before it at L 0.5 at rest / 1.0 turning. Remainder L 0.12 per the design, **OFF per the ruling**. | README §3; P L619 |
| LED-4 | **Lights off**: all segments off. | README §3; P L709 |
| LED-5 | **Scenes**: N clusters of 3 segments (centre `round(s × 60 / N)` ± 1). The selected one is warm L 1.0, the others warm L 0.18. Everything else is off. | README §3; P L621 |
| LED-6 | **Scene ran**: green `110,217,150` wash, whole ring, L 0.68, 700 ms. | README §3; P L457 |
| LED-7 | **Hold-1 progress**: see G-7. | README §3 |
| LED-8 | **Unavailable press**: bottom 26–34 red `255,60,40` L 0.9, 320 ms (replaces the full-ring flash). | README §3; P L459 |
| LED-9 | **Windows**: a marker (± 1 segment) in **white** at the window's position on the arc, the rest **warm L 0.1**. | README §3; P L620, L699 |
| LED-10 | **Explorer / Recently Added**: a marker (± 1) in the album's dominant colour at 1.0, the rest of the arc in that colour at 0.1. | README §3; P L620, L666 |
| LED-11 | **Kelvin → RGB** (Tanner Helland), clamped. About 255,146,39 at 2200 K and 255,254,250 at 6500 K. Calibrate against the ring's white point. | README §3; P L609–611 |
| LED-12 | **Button LEDs**: nav **white L 0.34**, disabled L 0.12, active mode **warm `255,190,105` L 0.9**, commit green L 0.68, liked pink `255,40,90` L 0.30, snap side = app colour L 1.0, pressed = 1.0. No LED where the slot has no action (Scenes 2/3: `o` = none). | README §3; P L740–750 |
| LED-13 | **Lights button 4 is white, not red** (and not green). | README §3; P L712 |
| LED-14 | Rest ring (prototype): warm L 0.12 on all segments. The **standing user ruling** is a steady warm rest. | P L617 |
| LED-15 | Home/Music volume reveal: arc fill in warm at 1.0 (prototype). r2.2's level ring stands per README §0 ("LED ... unchanged"). | P L635; R22 01 §4 |
| LED-16 | Tracks: turned = the half ring (right 1–14 / left 46–59) green 0.9, the rest warm 0.1. At rest = the rest ring. Seek = warm arc of pos/dur. | P L622, L680–681 |
| LED-17 | Idle: whole ring warm 0.06. | P L738 |
| LED-18 | Segment colour transitions 260 ms `cubic-bezier(.22,1,.36,1)`. Button strips 220 ms. | P L287, L295 |
| LED-19 | Prototype full-ring flashes (L 0.68): Play item green 600 ms; Play next green 500; Seek set green 400; skip green 500; like pink 500; snap app colour 600; switch green 500; hold-Home warm 400. r2.2 moments (sweeps, washes, head shake) govern where r2.2 is "unchanged". | P L499, L512, L536, L546, L549, L555, L560, L562 |

## 6. Motion (README §4; P L754–765, L865)

| # | Requirement | Source |
|---|---|---|
| MO-1 | Screen change: the content layer slides 20 px in the depth direction (deeper = in from the right) and fades. 220 ms opacity / 380 ms transform, `cubic-bezier(.22,1,.36,1)`. Depth: home 0; music, windows, lights 1; albums, tracks, scenes 2; explorer, upnext 3. **Home → Music is a depth change and slides.** | README §4; P L395, L434–442, L865 |
| MO-2 | Value reveal (volume, brightness, temperature) = r2.2's volume reveal. Text layer out: translateY −8, 150/190 ms ease-in. Big layer in: +6 → 0, 340 ms spring `cubic-bezier(.34,1.45,.64,1)`, 180 ms opacity, 50 ms delay. Back: text in after 90 ms, 320/420 ms. Hides 1.4 s after the last detent. | README §4; P L757–758 |
| MO-3 | List layer: 200 ms in / 120 ms out, opacity only. | P L759 |
| MO-4 | Idle icon row: staggered 200 + 45·i ms, 300 ms opacity, 460 ms spring translateY 14 → 0. Out 140/160 ms. | P L762–764 |
| MO-5 | Status 200 ms, footer 240 ms fades. Arc and pips 200 ms. | P L302, L307, L330–331 |
| MO-6 | r2.2 rules stand: translate and opacity only, slides ≤ 20 px, fades ≥ 120 ms, covers swap instantly, text changes at rest. | README §4; R22 01 §3 |
| MO-7 | Navigator show/hide: opacity 280 ms + translateX −24 → 0 over 420 ms, ease-out `cubic-bezier(.22,1,.36,1)`. | README §4; P L80 |
| MO-8 | Navigator content swap: the same slide and fade as the knob content layer, in sync (shared `cOp` / `cTf` / `cTr`). | README §4; P L86 |
| MO-9 | Navigator lists: rows and covers translate 380 ms ease-out, opacity 280 ms. Plate 320 ms transform, 200 ms opacity. Bars: width 120 ms linear. Volume, brightness and temperature row opacity 200 ms. Key fill 120 ms. | README §4; P L99, L109–115, L126, L139, L141, L165 |

## 7. Navigator (README §5; P L79–170, L790–837)

### 7.1 Visibility
| # | Requirement | Source |
|---|---|---|
| NV-1 | Replaces the companion's floating knob mirror. | README intro, §5 |
| NV-2 | Appears on any turn or press (`lastAct`). | README §5; P L475, L496 |
| NV-3 | Auto-hides **4 s** after the last input at Home and at the space roots. | README §5; P L794 |
| NV-4 | Stays visible in Recently Added, Tracks (incl. Seek), Scenes, temperature/scene knob modes and a pending scene. | README §5; P L793 |
| NV-5 | Hidden while a full-screen overlay is open (explorer, Up next, Windows picker): no navKind there. | README §5; P L792 |
| NV-6 | Setting **Auto-hide** (default) / **Pinned** (always shown) / **Off**. | README §5; P L794, L851 |

### 7.2 Geometry and glass (stage units; ×2 on the 5120 × 1440 device)
| # | Requirement | Source |
|---|---|---|
| NV-7 | Left 20 (device 40). Vertically centred in the work area above the 48 px taskbar. **Width 250** (500). Height = content. Padding 16 (32). Gap 14 (28). **Radius 26** (52). | README §5; P L79–84 |
| NV-8 | `backdrop-filter: blur(14px) saturate(1.8) brightness(1.06)`. On Windows: DirectComposition acrylic / backdrop blur with these values. | README §5; P L81 |
| NV-9 | Fill `linear-gradient(160deg, rgba(255,255,255,.18) 0 %, .05 42 %, .09 100 %)` over `rgba(18,18,22,.30)`. | README §5; P L81 |
| NV-10 | Rim insets: `0 1px 0 rgba(255,255,255,.6)`, `0 −1px 0 .14`, `1px 0 0 .22`, `−1px 0 0 .1`. | README §5; P L81 |
| NV-11 | Specular: radial white .22 → transparent, 220 × 160 at (−40, −60), `closest-side`. | README §5; P L82 |
| NV-12 | Drop shadow `0 18px 50px rgba(0,0,0,.35)`. Text shadow `0 1px 2px rgba(0,0,0,.35)`. No colour tint and no ambient fill (the `nav.amb` values are computed but never drawn). | README §5; P L81, L84 |

### 7.3 Type
| # | Requirement | Source |
|---|---|---|
| NV-13 | Archivo. Caps labels 11 px, 600, 0.12 em, white 75 %. Titles 15/19 600. Secondary 12/16 white 85 %. Meta 11/15 white 70 %. Numbers tabular. | README §5; P L85–118 |

### 7.4 Content by state
| # | Requirement | Source |
|---|---|---|
| NV-14 | **Path row** (all states, ellipsis): `Home`, `Music`, `Music › Recently Added`, `Music › Playlists`, `Music › Tracks`, `Music › Tracks › Seek`, `Lights`, `Lights › Scenes`. | README §5; P L85, L806–831 |
| NV-15 | **Home / Music (now)**: 64 px cover (radius 8, shadow `0 8px 20px .35` + 1 px white-.2 inset) + title / artist / status. Status = `Playing · m:ss of m:ss` or `Paused`, or a message in its colour. Volume row: caps `Volume` + `{v}%` and a 4 px bar (track white .2, fill white). Row **60 % at rest, 100 % while turning**. | README §5; P L87–101, L800, L805–808 |
| NV-16 | **Lights**: caption + **44 px** number (46 lh, −0.03 em) + 16 px unit at white .8: `Brightness` `62 %`, `Colour temperature` `3200 K`, or `Lights` `Off`. **Brightness bar**: 4 px, track .18, fill = the Kelvin colour, width = bri (0 when off). **Temperature bar**: gradient kel(2200) → kel(3400) → kel(6500), white 4 × 12 marker (radius 2, 1 px black-.4 ring) at (K − 2200)/43 %. **Scene row**: top rule white .2, caps `Scene` + scene name 14/600 (with ` · adjusted`). The row the knob is changing is 100 %, the other 50 %. | README §5; P L103–120, L809–814 |
| NV-17 | **Recently Added (covers)**: 196 px tall vertical carousel. 120 px covers (radius 8, shadow `0 10px 24px .4`). Neighbours at ±86 px scale 0.55 and ±132 px scale 0.38 (±170 at 0.30, hidden). Opacity 1 / .55 / .25. z by distance. Then title, artist, meta `{i} / {n} · {year}`. Keys `Back · Full screen · Play next · Play`. | README §5; P L122–135, L815–820 |
| NV-18 | **Tracks (rows)**: 190 px window, 5 rows × 38 px around the playing song, **wrapping at the album ends**. Row: 16 px number (♪ for the playing song) 11 px white .7, title 13/17 600, tag 10 px caps 0.08 em. Playing title `#9CF0BC`. Tags `Now` (white .6), `Skip to` / `Back to` in green `#6ED996` on the target. Plate `rgba(255,255,255,.16)` radius 10, inset top highlight .35, at the target (translateY trackPos × 38). Row opacity 1 / .65 / .5 by distance. Status `Turn for previous or next` / `Press 4 to skip`. Keys `Back · Up next · Seek · Skip` (Skip at 40 % at Now). | README §5; P L136–150, L821–826 |
| NV-19 | **Seek**: 44 px cover (radius 6) + title 14/18. 36 px `m:ss` (40 lh, −0.02 em) + 12 px `of m:ss`. 4 px warm `#FFBE69` bar. Keys `Exit seek · Up next · Set · Skip (40 %)`. Path `Music › Tracks › Seek`. | README §5; P L151–160, L827–829 |
| NV-20 | **Scenes**: the same 5-row list (number, name, tag `Running` `#7EE0A2` on the running unadjusted scene), plate at the centre. Status `Press 4 to run` (1e). [OFF] `Runs in 1 s` amber for 1d. Keys `Back · — · — · Run` (2/3 at 40 %). | README §5; P L830–836 |
| NV-21 | **Keys (all states)**: 2 × 2 grid under a top rule (white .18, padding-top 12, gap 8/10). 16 px key box (radius 4, 1 px white 55 %), digit 10 px 700 + 11 px label (white .9) of what 1–4 do **now**. Pressed = white fill with black digit. Unavailable or empty = 40 %. | README §5; P L162–169, L795 |
| NV-22 | Lights keys: `Home · Scenes · Temperature|Brightness · All off|Turn on`. Home keys: `Music · Windows · Lights · Play|Pause`. Music keys: `Home · Recent · Tracks · Play|Pause`. | P L798, L808, L814 |
| NV-23 | `Hold 1 for Home` (11/14, white .7, margin −4) below the keys when depth ≥ 2. | README §5; P L170, L799 |
| NV-24 | Messages replace the status line in their colour (`nav.st` / `nav.stc`). | P L804 |

## 8. Copy (README §6 + the prototype)

| # | Context | Copy | Source |
|---|---|---|---|
| CP-1 | Skip at Now (unavailable) | `Turn to pick previous or next` (`#FF8474`) | README §6; P L548 |
| CP-2 | Skip in Seek | `Set or cancel seek first` | README §6; P L547 |
| CP-3 | Scenes 2/3 | `Turn to choose · 4 runs it` | README §6; P L574 |
| CP-4 | Seek | `Seek set` (`#7EE0A2`) · `Seek cancelled` (`#A6A6A6`) | README §6; P L544, L546 |
| CP-5 | Overshoot guard | `Home · press 1 again for Music` | README §6; P L518 |
| CP-6 | Lights | `Lights off` · `Lights on` · `Tap 4 to turn on` · `Knob: brightness` · `Knob: temperature` (amber) · [OFF] `Knob: scenes` | README §6; P L509, L567 |
| CP-7 | Scenes | `Scene running` · `running now` · [OFF] `Runs in 1 s · 1 cancels` · `Scene cancelled` | README §6 |
| CP-8 | Windows | `Snapped left` · `Snapped right` · `Switched to {app}` | README §6; P L560–562 |
| CP-9 | Tracks | `Turn for previous or next` · `Previous` · `Next` · `Now: {song}` · `Press 4 to skip` | README §2.2; P L681 |
| CP-10 | Seek status | `of {dur} · 3 sets · 1 cancels` (`#FFBE69`) | README §2.2; P L680 |
| CP-11 | Lights title | `{scene} · adjusted` | README §2.2; P L628 |
| CP-12 | Lights sub | `{bri}% · {K} K` | README §2.2 |
| CP-13 | Lights big | `Brightness` · `Colour temperature` | README §2.2 |
| CP-14 | Scenes meta | `{i} / {n} · {bri}% · {K} K` / `{i} / {n} · running now` | README §2.2; P L722 |
| CP-15 | Prototype-only messages | `Paused` / `Playing` (1.4 s), `Plays next · {album}`, `Queue replaced`, `Skipped · back at neutral`, `Shuffle on/off`, `Liked`, `Unfavourite in Music app`. r2.2's copy sheet governs where it differs. | P L508, L536–537, L549, L553, L555 |
| CP-16 | Navigator status | `Playing · m:ss of m:ss`, `Paused`, `Press 4 to run`, `Turn for previous or next`, `Press 4 to skip`, `Hold 1 for Home` | P L807, L825, L834, L170 |

## 9. Home Assistant bridge (README §7)

| # | Requirement | Source |
|---|---|---|
| HA-1 | Brightness: `light.turn_on` on the hall group, `brightness_pct` 1–100, 1 % per detent. Throttle ≤ 10 Hz, send the final value on settle. | README §7 |
| HA-2 | Temperature: `light.turn_on`, `color_temp_kelvin` 2200–6500, 100 K per detent, clamped to the bulbs' reported min/max. | README §7 |
| HA-3 | Scenes list: the user's configured automations, scenes and scripts (name + target bri/K for the preview line). Run = `scene.turn_on` / `script.turn_on` / `automation.trigger` by type. | README §7 |
| HA-4 | All off: `scene.create` snapshot (`snapshot_entities`), then `light.turn_off`. | README §7 |
| HA-5 | Turn on: `scene.turn_on` of that snapshot. | README §7 |
| HA-6 | State: subscribe to the group's state. An external change updates the knob and shows the reveal for 2.6 s. | README §7 |
| HA-7 | Haptics: brightness BINARIS BEER (as volume). Temperature and scenes MIDI SKIPPER, with bounds per mode. | README §7 |
| HA-8 | Connection through Desk Dial, one fixed light group. | user decision |

## 10. State (README §8)

| # | Requirement | Source |
|---|---|---|
| ST-1 | `space` ∈ home · music · albums · explorer · tracks · upnext · windows · lights · scenes. | README §8 |
| ST-2 | `lightsKnobMode` (bri · temp), `bri`, `kelvin`, `on`, `sceneIndex`, `adjusted`, `offSnapshot`. | README §8 |
| ST-3 | `seek`, `seekFrom` (for Cancel), `trackPos` −1/0/1. | README §8 |
| ST-4 | `holdStartedAt` (progress ring), `homeArrivedAt` (overshoot guard). | README §8 |
| ST-5 | `navigatorMode` (auto/pinned/off, persisted setting), `lastInputAt`. | README §8 |
| ST-6 | [OFF] `homeOption`, `homeDomain`, `lastDomain`, `pendingScene`. | README §8 |

## 11. Tokens (README §9)

| # | Requirement | Source |
|---|---|---|
| TK-1 | Ink `#F2F2F2`, secondary `#A6A6A6`, meta `#7C7C7C`, disabled `#5A5A5A`, nav `#E6E6E6`, confirm `#6ED996`, cancel/error `#FF8474`, success `#7EE0A2`, warm `#FFBE69` / LED `255,190,105`, green LED `110,217,150`, red LED `255,60,40`, pink `255,40,90`. | README §9 |
| TK-2 | A **warm/amber line tone** (`#FFBE69`) is used by `Knob: temperature`, the Seek status and `Shuffle on/off`. | README §2.2; P L567, L680 |

## 12. r2.2 items that r3 flows inherit

| # | Requirement | Source |
|---|---|---|
| R22-1 | The three full-screen overlays (explorer, Up next, Window picker), their 32:9 tables, blur recipes and lifetime (60 s idle, lock, sleep) are unchanged. | README intro; R22 README §7 |
| R22-2 | Covers swap instantly. Text changes at rest. Headings fit r 112. | R22 01 §3 |
| R22-3 | Unavailable-button availability table (Play next sources, Up next under AirPlay, Seek capability, Like states) stands. The flash changes per G-9. | R22 01 §2 |
| R22-4 | Seek behaviour: sent 250 ms after the last detent, stops 3 s before the end, `Jumping…`, and a song change exits Seek. **r3 changes 1 to Cancel (restore) and 3 to Set**, so a scrub is applied only on Set. | R22 README §8; README §1.2 |
| R22-5 | Toasts never appear over overlays. No toast for Play/Pause or Back. | R22 01 §8 |
| R22-6 | Mirror labels `RECENT`, `FAVOURITES`, `UP NEXT`. r3 relabels the explorer mirror `ON SCREEN` inside the arc path. | R22 01 §3; P L671 |
| R22-7 | Haptic profiles: Home volume / Seek BINARIS BEER. Lists MIDI SKIPPER. Tracks MIDI CLACK JONES. Do not change the installed profiles. | R22 README §3 |
| R22-8 | Tracks line under shuffle or repeat (`Next: shuffle pick`, …) applies to the `Now:` sub in r3 only where r3 shows a neighbour. r3 shows `Now: {song}`. | R22 01 §3; README §2.2 |
| R22-9 | Settings (tray, status strip) are unchanged. They gain the Navigator setting (NV-6) and the Home Assistant column. | README §5, §7 |

## 13. Open decisions in the design (README §12), as resolved

1. Home: **1a**.
2. Lights: **1e**.
3. Breadcrumbs: **Arc**, pre-rendered.
4. All off on tap or hold: not decided, so the tap stays.
5. Monitor content beyond the Navigator for Lights: none, except the Navigator.
6. r2.2 carry-overs (Like pink, green breathing on the ring, 48 px text widths): open.
