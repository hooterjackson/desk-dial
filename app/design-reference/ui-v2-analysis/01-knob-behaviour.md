# UI V2 analysis 01: knob behaviour in the master design

Read-only extraction, 2026-09-25. Subject: `design_handoff_nano_d_master` (the "UI V2 master handoff"). Target: the combined release firmware **1.0.0-cc5.4** plus **desktop v7**, which also carries the ALIVE LED work already in progress.

This file covers the **knob**: LCD, the four buttons, haptic profiles, the knob-side state machine and timers, and the LED hooks that knob events trigger. The companion overlays (explorer, Up next, window picker) appear only where the knob mirrors them or depends on them. The LED engine itself is ALIVE.md / spec 02, and only its per-mode targets and triggers are listed here.

---

## 0. Sources, precedence, notation

| Abbrev. | File (all paths absolute under `<repo>\`) |
|---|---|
| **R** | `app\design-reference\design_handoff_nano_d_master\README.md` |
| **S01** | `…\design_handoff_nano_d_master\specs\01-FEATURES-explorers-snap-seek.md` |
| **S02** | `…\specs\02-LED-choreography.md` |
| **S03** | `…\specs\03-SCREEN-and-state.md` |
| **S04** | `…\specs\04-WINDOW-carousel.md` |
| **BS** | `…\prototypes\Browse and Snap.dc.html`: the primary prototype. Its knob LCD is rendered **inline** (BS:206–258). It does not use Knob Face. |
| **KF** | `…\prototypes\Knob Face.dc.html`: the older LCD renderer. It is the only source for the idle-icon-row motion. |
| **KM** | `…\prototypes\knob-model.js`: the older state machine. It is the source for loading, error and offline copy, and for `finishAlive()`. |
| **CC** | `…\prototypes\Nano_D Control Center.dc.html` |
| **CT** | `app\control_center\controller.py` (current) |
| **RT / DV / AW / PR** | `control_center\runtime.py`, `device.py`, `artwork.py`, `presentation.py` (current) |
| **FD** | `firmware\src\cc_display.cpp` (current LCD renderer) |
| **FP** | `firmware\src\cc_presentation.h` (current tones and inks) |
| **FW:x** | other firmware sources under `firmware\src\` |
| **AL** | `firmware\ALIVE.md` (in progress) |
| **P4** | `firmware\PRESENTATION_V4.md` |

- **Precedence** (R:15–21): R > S01 > S02 > S03 > S04.
  - R:107 sends base geometry, the artwork layer and the state model to S03. Where R, S01 and BS are silent (loading, errors, idle view, offline), S03 and KM stay in force.
  - Where BS contradicts R or S01, the spec text wins. Each such case is listed in section 6.
- **User decisions that override the design:**
  - WARM is fixed at LED output **#FF8424** all day. Time of day only dims the resting brightness.
  - Volume 80–90 % is LED **#FF3A0A**, and volume ≥ 90 % is **#FF0000**. The design uses amber 255,118,0 and red 255,24,0.
  - When the PC is away, the ring drains, then shows the amber marks. The native profile lights take over on native input.
  - The desktop floating knob runs the same choreography.
  - There is one combined release.
- **Notation:**
  - Coordinates are LCD pixels on the 240 × 240 face. `top` is the CSS top of the line box.
  - `22/26` means font size / line height.
  - Colours are hex.
  - **OUT** = `cubic-bezier(0.22,1,0.36,1)`, **IN** = `cubic-bezier(0.4,0,1,1)`, **SPR** = `cubic-bezier(0.34,1.45,0.64,1)`.
  - "{i} / {n}" is 1-based, with spaces around the slash.

---

## 1. Shared foundations

### 1.1 Geometry
- **LCD:** 240 × 240 round, black. The safe circle has radius 104. Nothing essential goes outside r 104, and the bezel may hide r 112–120 (R:52; S03:49).
- **Footer:**
  - Four 20 px glyphs (viewBox 24, stroke 2.3, round caps and joins).
  - Left edges x **46 / 89 / 131 / 174**, which puts the centres at **56 / 99 / 141 / 184**. Top 154, so the glyph box is y 154–174 (BS:253–254, BS:980; R:104; S01:104).
  - A second path of each glyph, `f.fill`, is filled with currentColor. Only the Snap half uses it (BS:254).
  - Colour changes take 240 ms `ease` (BS:253).
  - **The footer is not part of the sliding content layer.** It is a sibling of the text layer (BS:209 vs BS:251), so it does not move on a screen change.
- **Button caps:** 48 × 48 on a 70 px pitch, in one row (R:54; S01:105).
  - In the BS canvas they sit at x = 61 + 70·j, y 398 (BS:260, BS:570, BS:982). The caps line up with the footer slots by order only (the LCD slots are 43 px apart).
  - A press lowers the cap 2 px for 140 ms. This is prototype-only feedback (BS:650, BS:986).
- **Common text column:** x 35, width 170 (centred on 120). The exceptions:
  - Home status: x 40, w 160.
  - Windows meta: x 30, w 180.
  - Volume value and Seek time: x 0, w 240.

### 1.2 Type and inks
- **Font:** Montserrat, weight 500, root ink #F2F2F2 (BS:206).
- **Sizes and uses:**

  | Size | Used for |
  |---|---|
  | 12 | labels, meta, status |
  | 14 | artist, sub-lines, captions, app name, `of m:ss` |
  | 16 | window title |
  | 22 | titles, and the volume `%` |
  | 48 | volume digits, Seek time |

- **Tracking:** caps labels use letter-spacing **0.08 em** (BS:222). The 48 px lines use **−0.02 em** with line height 46 (BS:217, BS:241).
- **Tabular digits:** only the Seek time and the `of m:ss` line use `font-variant-numeric: tabular-nums` (BS:241–242).
- **Inks:**

  | Ink | Hex | Used for |
  |---|---|---|
  | Ink | #F2F2F2 | titles, volume digits, Seek time, selected Tracks glyph |
  | Secondary | #A6A6A6 | caps labels, artist and sub-lines, captions, `%`, app name, `of m:ss` |
  | Meta | #7C7C7C | meta lines, Home status, unselected Tracks glyphs |
  | Error | #FF8A7A | from S03 (S03:52); not used in BS |
  | Success | #7EE0A2 | from S03 (S03:52); not used in BS |

  BS also computes `lcd.metaCol = '#8A8A8A'` (BS:979) but no template uses it, so ignore it.

### 1.3 Artwork layer, scrim, text shadow
- **Art:**
  - Full-bleed 240 px cover at opacity **0.8**. It is 0 on Windows (BS:946, 953, 959, 965, 970, 1091).
  - Transform is none, and `scale(1.06)` on Windows (BS:1089).
  - Transitions: opacity **560 ms OUT**, transform **1100 ms OUT** (BS:207).
  - A cover change itself is instant: `background` has no transition.
- **Scrim** (R:108; S01:107–113; BS:208): a black vertical gradient.

  | From top | Row (px) | Opacity |
  |---|---|---|
  | 0 % | 0 | 0.60 |
  | 45 % | 108 | 0.72 |
  | 62 % | 148.8 | 0.92 |
  | 70 % | 168 | 1.0 (solid) |

  The scrim is fully opaque on every art screen and 0 on Windows, with no transition (BS:1089).
- **Text shadow:** `0 1px 3px rgba(0,0,0,.8)` on the whole text layer (BS:209; R:108). Footer glyphs are outside that layer, so they have no shadow.
- **Which cover each screen shows:**

  | Screen | Cover |
  |---|---|
  | Home, Tracks, Seek | the now-playing **track's** album (`ALB[ct.al]`, BS:946, 953). In a playlist it changes with each song. |
  | Recently Added | the highlighted album (BS:965) |
  | Explorer, albums | the focused album |
  | Explorer, playlists | the cover of the playlist's **first mosaic album** (BS:935, 970) |
  | Up next | the focused row's album (BS:959) |
  | Windows | none |

- **Rules from S03 that still apply:**
  - An unavailable library item's art is drawn at 35 % (S03:57).
  - With no cover, draw the clean layout with no placeholder (S03:72).
  - The idle view fades the art out and scales it to 1.06 (S03:114).

### 1.4 Button tones: footer ink and button LED (BS:938, BS:983–988; R:147–155; S01:89–98)

| Tone | Meaning | LCD footer ink | LED colour | LED level (awake) |
|---|---|---|---|---|
| `nav` | navigation / normal | #E6E6E6 | WARM | 0.70 |
| `go` | the action (button 4) | #6ED996 | GREEN 0,255,98 | 1.0 |
| `on` | pair, active / modifier on | #FFFFFF | WARM | 1.0 |
| `off` | pair, inactive / modifier off | #7A7A7A | WARM | 0.30 |
| `dim` | disabled | **#5A5A5A** (BS). S03, KM and the firmware use #4A4A4A. | WARM | 0.14 |
| colour `c` | liked heart, assigned Snap side | `rgb(c)` | `c` | 1.0 |

- **Paused Play on Home, button 1:**
  - The specs say it turns green and breathes on a 2.6 s cycle: S01:100; R:138; S02:54 and :106.
  - The breath multiplier is `0.55 + 0.45·(0.5 + 0.5·cos(2πt / 2600 ms))`.
  - BS breathes it but keeps it WARM, because its Home footer tone is `nav` (BS:508, BS:944). Follow the spec. AL 5.3 already does.
- **Resting** (5 s without input): every lit button goes WARM at 0.12, or 0.04 when dim. This is multiplied by the breath and the time-of-day brightness (S02:71). In BS, both `off` and `dim` rest at 0.04, because the rule is `b.a ≥ 0.5 ? 0.12 : 0.04` (BS:507).
- **Retired tone:** the red `stop` / Cancel tone. Windows button 1 is now Back (nav).
- **The design's WARM** is 255,164,84 in BS (BS:406), following time of day. [user] It is fixed at LED #FF8424.

### 1.5 Icon vocabulary (BS `I` / `HALF`, BS:395–405; R:83–102; S01:49–68)

The BS keys are misleading: `I.next` is *list-plus* (Play next), `I.tracks` is *skip-forward*, and `I.list` is the Tracks list.

| Meaning (one meaning per icon) | BS key | Path (24 grid; stroked unless noted) | Knob use |
|---|---|---|---|
| Back | `back` | `M15 18l-6-6 6-6` (chevron-left) | slot 1, all modes except Home |
| Play | `play` | `M7 4.5v15l12-7.5z` | Home slot 1 when paused; slot 4 in Recent, Explorer, Up next |
| Pause | `pause` | `M8 5v14M16 5v14` | Home slot 1 while playing |
| Browse music | `note` | `M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z` | Home slot 2 |
| Tracks | `list` | `M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01` | Home slot 3 |
| Windows | `win` | `M3 5h18v14H3zM3 9h18` (window with title bar) | Home slot 4 |
| Open on screen | `expand` | `M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7` | slot 2 in Recent and Tracks |
| Recently Added | `clock` | `M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0` | Explorer slot 2 |
| Favourite playlists | `queue` (list-music) | `M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3` | Explorer slot 3 |
| Play next | `next` (list-plus) | `M11 12H3M16 6H3M16 18H3M18 9v6M21 12h-6` | Recent slot 3 |
| Seek | `seek` | `M3 12h9.5M18.5 12H21M15.5 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z`. The ring handle is centred at x 15.5. | Tracks slot 3 |
| Skip / Next | `tracks` (skip-forward) | `M5 5v14l9-7zM18 5v14` | Tracks slot 4, and the position row's right glyph |
| Previous | `prev` (skip-back) | `M19 5v14l-9-7zM6 5v14` | Tracks slot 4 when Prev is selected, and the position row's left glyph |
| Shuffle | `shuffle` | `M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22M18 2l4 4-4 4M2 6h1.9c1.5 0 2.9.9 3.6 2.2M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8M18 14l4 4-4 4` | Up next slot 2 |
| Like | `heart` | `M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z` | Up next slot 3 |
| Snap left / right | `rect` + `HALF.left` / `HALF.right` | outline `M3 5h18v14H3z` plus a **filled** half: `M3 5h9v14H3z` (left) or `M12 5h9v14h-9z` (right) | Windows slots 2 and 3 |
| Switch | `check` | `M20 6L9 17l-5-5` | Windows slot 4 |

- On the LCD the icons are 20 px with stroke 2.3 (R:83).
- The Tracks position row uses 16 px glyphs with stroke 2.3 (BS:231–233). The idle row uses 26 px glyphs with stroke 2.1 (KF:42).
- The position row's centre is a **filled 6 × 6 circle**, not the `dot` path (BS:232).
- The Seek handle is at x 15.5, about 65 % of the 24 grid or 69 % of the track, while R:95 says "≈ 60 %". The path is authoritative.

### 1.6 Screen change (LCD flip), `flipLcd(dir)` BS:649
- **Motion:**
  1. The content layer is set, with no transition, to `translateX(16·dir px)` and opacity 0.
  2. Two frames later it moves to `translateX(0)` and opacity 1, with `opacity 220ms OUT, transform 380ms OUT`.
- **Direction:** `dir = +1` (deeper) enters from the right, and `−1` (back) from the left.
- **What moves:** only the text layer. The art, scrim and footer stay put (BS:207–209, 251).
- **Distance:** the specs say ±20 px (R:126; S03:161) or "±16–20" (S01:129). BS uses 16.
- **Where it runs:** only on the transitions marked "flip" in section 4.1.
- **No flip on:** Seek on/off, Play next, Skip, Shuffle, Like, Snap, or turning.

### 1.7 Ring targets per mode (BS `renderVals()` BS:991–1015)
This is a summary only. The engine is ALIVE / S02, and the [user] colour overrides apply.

| Mode | Target |
|---|---|
| Home | Bounds 35 and 25 at WARM 0.30, then the arc from segment 35 clockwise at 0.62, k = 0…round(vol/2). The endpoint `35 + n` is 1.0 and takes the colour of its position. Segments with k/50 ≥ 0.8 are AMBER when vol ≥ 80, and k/50 ≥ 0.9 are RED when vol ≥ 90 (BS:994–998). Segment 35 is always lit, at 0.62 or 1.0, because the k = 0 put overwrites the 0.30 bound. Near-max embers flicker each RED segment while awake and vol ≥ 90 (BS:491, 498). |
| Recently Added, Explorer, Windows | One landmark per item at `(i − floor((n−1)/2))·3`, in the item colour at 0.45, or 0.30 for warm or monochrome items. The cursor is in its colour at 1.0 (BS:1010–1013). Unlit segments get an ambient tint of +0.06 of the cursor colour, τ 220 ms (BS:521–524). |
| Up next | Landmarks at `(k − c0)·3` in each track's **album** colour: played 0.14, now playing **0.70**, upcoming 0.45, cursor 1.0 (BS:1005–1008; R:146). It also gets the ambient tint. |
| Tracks | Prev at 52+53, Neutral at 0, Next at 7+8, all WARM 0.30. The selected one is 1.0, or 0.62 for Neutral (BS:1004). |
| Seek | The song as one lap from 12 o'clock: `n = min(59, floor(pos/D·60))`. Segments k < n are WARM 0.62, unplayed segments with k mod 5 = 0 are 0.30, and the head n is 1.0 (BS:999–1002). |

- **Rule:** a list's ring uses only its items' colours, varied by level. No extra ticks, and no warm markers mixed in (R:145; S01:140).
- **New levels for AL:** Up next needs **0.14** and **0.70**. AL 5.2 only has the classes 0.30 / 0.45 / 0.62 / 1.0.

**Moments triggered by knob events** (R:156–176; S01:144–158; BS:393 for durations in ms):

| Moment | When | Duration (ms) |
|---|---|---|
| Spin trail (tick) | any turn that moves the cursor | 180 |
| End stop (bound) | turn at a limit | 460 |
| Wake | first input after 5 s of rest | 520 |
| Mode-change Reveal | any mode change (BS:581), plus Seek on/off and the 3 s Seek timeout (BS:664, 667) | 450 |
| Press | any press | 220 |
| Play fill / Pause drain | Home button 1 | 760 / 860 |
| Skip sweep | Tracks button 4; also the clockwise sweep from segment 0 for Play next (BS:781) | 640 |
| Wash | Play an album or playlist (BS:771); Switch a window (BS:862) | 1100 |
| **Half-wash** | Snap (BS:849). Segments 31–59 for left, 1–29 for right. It fills from its middle outward over 300 ms, holds until 380 ms, then fades over 520 ms; the matching button is tinted 0.6. | 900 |
| **Pink bloom** | Like, only when liking (BS:661) | 900 |
| **Scatter** | Shuffle: 9 hot sparks, 55 ms apart, each a 260 ms bump (BS:688) | 700 |

- **Composition:** one foreground moment at a time. `FG = fill, drain, sweep, wash, half, bloom, scatter` (BS:394). A new one fades the old in 120 ms, and the base ducks by 35 %.
- **Not yet in AL:** Half-wash, Scatter, pink Bloom, and the Play-next sweep at segment 0. AL's effect list is at AL:265.

---

## 2. Haptic profiles per mode

- **No new profiles.** Only the per-mode bounds and entry positions change (R:39; S03:34).
- **Seek** is the one new case. It switches **within Tracks** between two installed profiles (R:60; S01:163).

| Mode / sub-state | Profile | Detents / turn | Bounds | Entry position | Host-driven re-entry (new control id and position) |
|---|---|---|---|---|---|
| Home (volume) | BINARIS BEER | 67 | 0–100, 1 % per detent (R:59) | current volume | — |
| Recently Added (knob) | MIDI SKIPPER | 20 | 0 … n−1. BS uses the full list with no More item (BS:704). | BS: the last knob position `rIdx` is kept across visits. It starts at 1, so the first entry lands on item 2 (BS:596). Playing album i sets it to i (BS:769). Back from the explorer sets it to the explorer's Recently Added index (BS:801). S03:30 says item 1, or the restored position on Back. | returning from the explorer |
| Explorer, Recently Added tab | MIDI SKIPPER | 20 | 0 … nRecent−1 | always this tab on open, at the knob's `rIdx` (BS:795) | on a tab switch, bounds and position change (BS:805–809) |
| Explorer, Favourite playlists tab | MIDI SKIPPER | 20 | 0 … nPlaylists−1 | the remembered `xIdx.playlists`, initially 0 (BS:596) | tab switch |
| Tracks | MIDI CLACK JONES | 8 | Prev · Neutral · Next, 3 positions (R:62) | Neutral (BS:736) | after a skip, and on Seek exit: back to Neutral (BS:667, 676) |
| **Seek** (Tracks, button 3) | **BINARIS BEER** | 67 | 0 … D−1 s, **5 s per detent**, clamped (BS:712) | the current song position | on entry and on exit (profile swap) |
| Up next (screen) | MIDI SKIPPER | 20 | 0 … queue length − 1 | the now-playing row (`qSel = qNow`, BS:680) | after Shuffle, the focus moves to `qNow + 1` (BS:690) |
| Windows (screen) | MIDI SKIPPER | 20 | 0 … N−1 of the list **frozen at open** | the first window that isn't the foreground one: index 1 normally, 0 when the foreground window isn't first (BS:819–820). S03:32 calls this "index 2 (most recent other window)". | after a snap, the highlight moves at 420 ms to the first window that is neither this one nor assigned (BS:854–855) |

- **Seek position mapping** (recommended; BS stores seconds, not detents).
  - The prototype does `pos = clamp(pos ± 5, 0, D−1)` from an arbitrary start, so positions are not multiples of 5 s. To keep the knob's absolute-position model (CT:1–5, CT:498–523), use:
    - `p0 = ceil(pos0 / 5)`
    - `P = p0 + ceil((D − 1 − pos0) / 5)`
    - bounds `0 … P`, entry `p0`
    - `seconds(p) = clamp(pos0 + 5·(p − p0), 0, D − 1)`
  - This reaches 0:00 and D−1 exactly, as BS does.
- **Host-driven moves need re-entry.** The knob's position is authoritative within one control id (CT:1–5). Every host-driven index move in the table (Snap auto-advance, Shuffle, tab switch, Seek, return from the explorer) therefore needs a new `control` entry carrying the new position.
- **Prototype drag steps** (BS:872) are 360/67° on Home and in Seek, and 18° everywhere else. That includes Tracks, where the real profile is 45° per detent.

---

## 3. Mode by mode

For each mode: (a) the buttons, (b) the LCD, (c) the ring and haptics, (d) behaviour and timers. The "Legend" labels come from BS:944–989 and are the prototype's own button descriptions; use them for tooltips, the desktop legend and aria text (`Button {i}: {label}`, BS:986).

### 3.1 Home (legend title "Home · now playing", BS:943; turn legend "Turn: volume", BS:989)

**(a) Buttons** (BS:944; R:74; S01:75)

| Slot | Icon | Legend | Enabled rule | Tone → footer ink / LED |
|---|---|---|---|---|
| 1 | `pause` while playing, `play` otherwise | "Pause" / "Play" | Sonos reachable, something to play, and no play/pause request already out (KM:209; CT:416–423). BS never disables it. | `nav` #E6E6E6, WARM 0.70. **Paused:** green 1.0, breathing 2.6 s (spec; see 1.4). Disabled: `dim`. |
| 2 | `note` | "Browse music" | always; Browse works without Sonos (KM:381) | `nav` |
| 3 | `list` | "Tracks" | Sonos reachable and something playing (KM:215, 381, 401; CT:589) | `nav`, or `dim` |
| 4 | `win` | "Windows" | always. **Windows opens only from here** (R:81; S01:70). | `nav`. Home has no green button. |

Holding button 1 does nothing here: you are already Home. No toast for Play/Pause (R:210; S01:255).

**(b) LCD at rest, playing** (BS:210–219; R:109)

| Element | Box | Type | Copy |
|---|---|---|---|
| Title | x 35, w 170, top 60 | 22/26 #F2F2F2, max 2 lines, `text-wrap: balance`, clamp with ellipsis | track title |
| Artist | x 35, w 170, top 114 | 14/18 #A6A6A6, 1 line, ellipsis | artist |
| Status | x 40, w 160, top 134 | 12/14 #7C7C7C | "" while playing (BS:1084). S03:84: "Starting…" / "Pausing…" while a transport request is out. |
| Art | full face | 0.8, with scrim | now-playing album |

There is **no room name and no volume number** at rest (R:109).

**Paused**
- Status "Paused" (BS:1084).
- Slot 1 shows `play`, green and breathing.
- The ring plays the Pause drain (860 ms) on the confirmed pause, then the Play button breathes (S02:138).
- 4 s after a **confirmed** pause, the idle view takes over (3.1.2).

**3.1.1 Volume reveal**

*Trigger.* Any Home detent (BS:703). A change made elsewhere reveals for 2.6 s with status "Changed on Sonos" (S03:97, S03:99).

*Motion in, from the first detent:*
- The track layer exits: opacity → 0 over **150 ms IN**, and transform → `translateY(−8px) scale(0.98)` over **190 ms IN** (BS:1086).
- The volume layer enters from `translateY(6px) scale(0.93)`: opacity over **180 ms OUT, 50 ms delay**, and transform over **340 ms SPR, 50 ms delay** (BS:1087).

*Volume layer* (BS:215–218):

| Element | Box | Type | Copy |
|---|---|---|---|
| Caption | x 35, w 170, top 52 | 14/18 #A6A6A6, 1 line | `{title}` while playing; `Paused · {title}` while paused (BS:1085; R:111); "Nothing playing" with an empty queue (S03:97) |
| Value | x 0, w 240, top 76 | digits **48/46**, −0.02 em, #F2F2F2, then `%` at **22 px**, 0 tracking, #A6A6A6. Gap 2 px, baseline-aligned, centred as a group. | `{vol}` + "%" |
| Status | x 40, w 160, top 134 | 12/14 #7C7C7C | "Minimum" at 0, "Maximum" at 100, else "" (BS:1084; S01:127). S03:97 adds "Setting…" (not yet confirmed) and "Changed on Sonos". |

*Hide.*
- **1400 ms after the last detent** (BS:703, a per-detent counter), but **only once Sonos has confirmed the value, re-checking every 400 ms** (R:110; S03:98). BS skips the confirmation check.
- The value exits with opacity **170 ms IN** and transform **190 ms IN**.
- The track returns with opacity **320 ms OUT** and transform **420 ms OUT**, both after a **90 ms** delay (BS:1086–1087).

*Ring.* The live volume arc. End stop at 0 and 100.

*Haptics.* BINARIS BEER, 0–100.

**3.1.2 Idle icon view** (not in BS; from S03:101–117, KF:39–46 and 143–153, KM:399–408, CC:1066)
- **When:**
  - nothing is playing; or
  - **4 s after a confirmed pause**, cancelled by any Play press or by resuming (S03:103–104; KM:253–256).
  - The current companion also uses it for STOPPED with playable media (CT:465).
- **What's removed:** title, artist and footer. The status line fades out (KF:51, 153).
- **Centred row:**
  - Four columns, each a **26 px** icon (stroke 2.1) over a **12/14** word, with an 8 px gap between them.
  - Columns are **46 px** wide in a 184 px row starting at x 28, so the centres are 51 / 97 / 143 / 189. The row is at top 100 (S03:108; KF:39–44).
  - The row mirrors the footer. With the master map that is **Play/Pause · Browse music · Tracks · Windows**. The words are not specified in the master; see open question 2.
  - Ink is `nav` #E6E6E6. Disabled items are #4A4A4A (S03:109). Nothing playing: Play and Tracks are disabled. Paused: all four are active.
- **Motion in:**
  1. The footer fades out over **160 ms IN** (KF:149).
  2. The title and artist exit with opacity **150 ms IN** and transform **190 ms IN** to `translateY(−10px)` (KF:147, 153).
  3. The art fades over **560 ms OUT** and scales to **1.06** over **1100 ms OUT** (KF:150, 152).
  4. The icons enter left to right, each delayed **200 + 45·i ms**, from `translateY(14px) scale(0.9)`: opacity **300 ms OUT**, transform **460 ms SPR** (KF:144–145).
- **Motion out:**
  - The icons exit with opacity **140 ms IN** and transform **160 ms IN**.
  - The footer returns over **280 ms OUT**, after a **140 ms** delay.
  - The art returns with opacity **420 ms OUT** and transform **700 ms OUT**, both after **60 ms**.
  - The track returns over **320 / 420 ms OUT**, after **90 ms** (KF:146–150).
- **Buttons:** unchanged. A volume turn still reveals the volume layer over the idle row (KF:143).

**3.1.3 Sonos unavailable** (not in BS; KM:378–383; CT:1103–1112)
- The screen uses the list geometry (`notice`):

  | Element | Copy |
  |---|---|
  | Title | "Sonos unavailable" |
  | Sub-line | "Looking for Sonos…" |
  | Meta | "Windows still works" |

  Before the first Sonos read, the title alone says "Looking for Sonos…", with no art and no ring (CT:1104–1107).
- **Footer in the new map:** 1 dim, 2 nav, 3 (Tracks) dim, 4 (Windows) nav.
- **Ring:** the confirmed endpoint only (S03; AL D15).
- **Turns** are ignored (KM:189; CT:507).

### 3.2 Recently Added on the knob (legend "Recently Added · on the knob", BS:961; turn "Turn: choose an album")

**(a) Buttons** (BS:963; R:75; S01:76)

| Slot | Icon | Legend | Enabled rule | Tone |
|---|---|---|---|---|
| 1 | `back` | "Back to Home" | Disabled while a Play from this view is pending (S03:133; KM:219, 447). This is not in BS. | `nav` |
| 2 | `expand` | "Open on screen" | list loaded (recommended; BS always enables it) | `nav` |
| 3 | `next` (list-plus) | "Play next · keeps your queue" | Item available and Sonos reachable. This is recommended, mirroring Play (KM:441–443). | `nav` (warm, **not green**) |
| 4 | `play` | "Play · replaces queue" | Item available, Sonos reachable, and no Play pending (KM:441–447) | `go` |

**(b) LCD, list layout** (BS:221–226; S01:118)

| Element | Box | Type | Copy |
|---|---|---|---|
| Label | x 35, w 170, top 32 | 12/14 caps, 0.08 em, #A6A6A6, 1 line | "RECENTLY ADDED" (BS:964). S03:122 adds " · P{n}" on later pages; the master has no pages. |
| Title | top 52 | 22/26 #F2F2F2, 2 lines, balanced | album title. #7C7C7C when unavailable (S03:132). |
| Sub-line | top 106 | 14/18 #A6A6A6, 1 line | artist |
| Meta | top 127 | 12/14 #7C7C7C, 1 line | "**Queued next**" for **1500 ms** after Play next, else `{i} / {n}` (BS:964; S01:118, 221) |
| Art | full face | 0.8, or 0.35 when unavailable | highlighted album |

The consequence copy is **dropped**. S03 had "{i}/{n} · Replaces queue" and "· Loads, doesn't play"; the legend now carries it.

**States from S03 / KM that the master leaves open** (keep them, or decide; section 7):

| State | LCD | Buttons |
|---|---|---|
| Pending | meta "Starting…" in #A6A6A6 (KM:446) | Back and Play dim |
| Partial failure | "Queue replaced · didn't start" in #FF8A7A (KM:450) | Play retries |
| Unavailable item | "{i}/{n} · Not available", title #7C7C7C (KM:437) | Play dim |
| Sonos down | "{i}/{n} · Sonos unavailable" (KM:443) | — |
| Loading | title "Loading…", sub-line "Apple Music" or "Page n" (KM:418) | — |
| Empty | "Nothing recently added" / "Apple Music library" (KM:421) | — |
| Sign-in expired | "Apple Music sign-in expired" / "Renew on your PC" / meta "Windows still works" in #A6A6A6 (KM:424) | — |
| More item | "More" / "Next 10 items" (KM:433) | **not in the master** |

**(c) Ring and haptics:** album-colour landmarks and cursor (1.7). MIDI SKIPPER, 20 detents.

**(d) Behaviour**
- **Play next (3):**
  - Inserts the album after the current song; the queue is kept (BS:776–780; R:224, Sonos `AddURIToQueue` with `EnqueueAsNext=1`).
  - The knob stays in Recently Added. The meta shows "Queued next" for 1500 ms; BS re-renders at 1600 ms (BS:782).
  - Warm Sweep clockwise from segment 0 (BS:781).
  - Toast `Queued next · {album}` (BS:783).
- **Play (4):**
  - → **Home**, flip −1.
  - Wash in the album colour, plus Reveal.
  - Toast `Playing {album} · Hall` (BS:766–774).
  - The queue is replaced, shuffle turns off, Seek turns off, and Tracks returns to Neutral (BS:769).
- **Open on screen (2):** → Explorer on the Recently Added tab at the same album (BS:793–798).
- **Back (1):** → Home, flip −1 (BS:739).

### 3.3 Music explorer mirror (the screen is primary; legend "Music explorer · on screen", BS:967; turn "Turn: choose an album")

**(a) Buttons** (BS:968; R:76; S01:77)

| Slot | Icon | Legend | Enabled rule | Tone |
|---|---|---|---|---|
| 1 | `back` | "Back to the knob list" | always | `nav` |
| 2 | `clock` | "Recently Added" | always; a no-op when already active or while a switch is fading (BS:806) | `on` (#FFFFFF, WARM 1.0) when it's the active tab, else `off` (#7A7A7A, WARM 0.30) |
| 3 | `queue` (list-music) | "Favourite playlists" | as slot 2 | `on` / `off`, inverse of slot 2 |
| 4 | `play` | "Play" | item playable and Sonos reachable (recommended) | `go` |

**(b) LCD, list layout** (BS:969)

| Element | Copy |
|---|---|
| Label | "**RECENT · SCREEN**" or "**PLAYLISTS · SCREEN**" |
| Title | album or playlist title |
| Sub-line | album: the artist. Playlist: the song count, i.e. the first part of its meta, e.g. "48 songs" (`xc.n.split(' · ')[0]`). |
| Meta | `{i} / {n}` within the active tab |
| Art | the focused album's cover, or the playlist's first mosaic album, at 0.8 |

**(c) Ring:** item colours (`ALB[].c` / `PL[].c`), landmarks 0.45 / 0.30, cursor 1.0, ambient tint.

**(d) Behaviour**
- **Guards:**
  - Turns are ignored during a tab-switch fade (190 ms) and during the Play animation (380 ms and more) (BS:706).
  - At either end: End stop, plus the on-screen row bumping 14 px for 160 ms (BS:708, 651, 1073).
- **Tab switch (2 / 3)** (BS:805–809):
  - The cards fade first. **190 ms** later the source switches and the knob LCD flips: +1 into Playlists, −1 back to Recently Added.
  - Each tab keeps its own index.
  - The ring swaps lists with no Reveal, because the mode is unchanged (BS:581).
  - The haptic bounds change, which needs re-entry.
- **Opening** always lands on the Recently Added tab, at the knob's album (BS:795).
- **Back (1):** → Recently Added on the knob, flip −1. `rIdx` takes the explorer's recent index **only if the recent tab is active** (BS:801); see artefact 13.
- **Play (4):**
  - The centre card grows. At **380 ms** the overlay closes and `playItem` runs: → **Home**, flip −1, Wash, toast `Playing {name} · Hall` (BS:810–815).
  - Cleanup happens at 760 ms.
- The overlay clears any toast when it opens (BS:794).

### 3.4 Tracks (legend "Tracks · on the knob", BS:948; turn "Turn: Previous · Now · Next")

**(a) Buttons** (BS:951; R:77; S01:78)

| Slot | Icon | Legend | Enabled rule | Tone |
|---|---|---|---|---|
| 1 | `back` | "Back to Home" | always. **While seeking it exits Seek only** (BS:749). | `nav` |
| 2 | `expand` | "Open on screen" | the queue is known (recommended). While seeking it exits Seek, then opens Up next (BS:750). | `nav` |
| 3 | `seek` | "Seek", or "Seek on · press to finish" while seeking | the song is seekable with a known duration (recommended; not in the design) | `nav`, or `on` (#FFFFFF, WARM 1.0) while seeking |
| 4 | `prev` when Prev is selected, else `tracks` (skip-forward) | "Previous track" / "Next track" / "Skip · turn first" | Prev or Next selected **and** not seeking (BS:951). The current companion also requires `can_previous` / `can_next` and no command out (CT:974–975). | `go`, else `dim` (#5A5A5A, WARM 0.14) |

**(b) LCD** (BS:227–237; S01:120; R:116–120)

| Element | Box | Type | Copy |
|---|---|---|---|
| Label | x 35, w 170, top 32 | 12/14 caps, 0.08 em, #A6A6A6 | "TRACKS" |
| Title | x 35, w 170, top 54 | 22/26 #F2F2F2, **one line**, ellipsis | Neutral "Turn to choose"; "Next track"; "Previous track" (BS:952) |
| Position row | x 72–168 (w 96), top 88, spread evenly, vertically centred | left: skip-back 16 px, stroke 2.3; middle: a **6 × 6 filled circle**; right: skip-forward 16 px | selected #F2F2F2, the others #7C7C7C (BS:1088) |
| Line | x 35, w 170, top 110 | 14/18 #A6A6A6, 1 line | Neutral `Now: {title}`. Next: `Next: {next title}`, or "End of queue". Prev: `Prev: {previous title}`, or "Start of queue" (BS:952). |
| Meta | x 35, w 170, top 130 | 12/14 #7C7C7C, 1 line | Prev/Next: "**Press 4 to skip**". Neutral: `{i} / {n}` (the now-playing position in the queue), plus " · shuffle" when shuffle is on (BS:952). |
| Art | | 0.8 | now-playing album |

- The master **shows the next and previous titles before the skip** (R:119). This supersedes S03:147, "Never show the next song's title before the skip".
- S03 / KM extras the master doesn't mention:
  - Title "Previous unavailable" in #7C7C7C when the source can't go back (KM:457–458).
  - Meta "Skipping…" while pending (KM:461).

**(c) Ring:** the transport pattern (1.7). MIDI CLACK JONES, 8 detents. Entry and return at Neutral.

**(d) Skip (4)** (BS:670–679)
- The Sweep runs in the skip's direction.
- The queue index moves ±1, the song position resets, and playback runs.
- **The knob returns to Neutral and stays in Tracks.** The LCD then reads "Turn to choose" / `Now: {new}` / `{i} / {n}`. There is no "Skipped" copy; S03's "Skipped · back at neutral" is gone.
- Toast `Next · {t}` or `Previous · {t}`.
- At the ends of the queue there is no skip. The toast reads "End of queue" or "Start of queue", with no LED moment (BS:673).

### 3.5 Seek (Tracks sub-state; legend "Tracks · seeking"; turn "Turn: 5 s per detent")

**Enter.** Tracks + button 3 (BS:751; R:113–115; S01:162–168).
- `tPos` resets to Neutral.
- Reveal moment.
- The **3 s idle timer** starts (BS:665–669).
- The **LCD does not flip**; the layers swap instantly.
- The haptic profile changes to BINARIS BEER.

**(a) Buttons** (BS:951; R:164)

| Slot | Icon | Tone | Press |
|---|---|---|---|
| 1 | Back | nav | exits Seek → Tracks |
| 2 | Open on screen | nav | exits Seek, then opens Up next |
| 3 | Seek | **`on`** (#FFFFFF, WARM 1.0) | exits Seek |
| 4 | Skip | **`dim`** | ignored (BS:752) |

**(b) LCD** (BS:238–243)

| Element | Box | Type | Copy |
|---|---|---|---|
| Label | x 35, w 170, top 32 | 12/14 caps, 0.08 em, #A6A6A6 | "SEEK" |
| Caption | x 35, w 170, top 52 | 14/18 #A6A6A6, 1 line | song title |
| Time | x 0, w 240, top 76, centred | **48/46**, −0.02 em, **tabular**, #F2F2F2 | `m:ss`: minutes unpadded, seconds 2 digits (`mmss`, BS:445) |
| Duration | x 35, w 170, top 128 | 14/18 #A6A6A6, tabular | `of m:ss` |
| Art | | 0.8 | now-playing album |

There is no position row and no meta line.

**(c) Ring:** the song lap (1.7). BINARIS BEER, 67 detents, 5 s per detent.

**(d) Behaviour**
- **Turn:**
  - `pos = clamp(pos ± 5, 0, D−1)` (BS:712).
  - Every detent restarts the 3 s timer, including one at a limit (BS:713).
  - An unchanged position gives the End stop (BS:714). The spec puts the End stop at 0:00 and at the end (S01:166).
- **Live seek:** Sonos `Seek(Unit=REL_TIME)`, sent **250 ms after the last detent** (R:225; S01:166). BS does not model it.
- **Playhead:** in BS it is frozen while in Seek (BS:634). The real Sonos keeps playing; see open question 5.
- **Exit:** button 3, Back, Open on screen, or **3000 ms without a turn** (BS:664, BS:749–751; R:225). Each returns to Prev · Now · Next at Neutral, with Reveal (S01:167).

### 3.6 Up next mirror (the screen is primary; legend "Up next · on screen", BS:955; turn "Turn: move through the queue")

**(a) Buttons** (BS:957; R:78; S01:79)

| Slot | Icon | Legend | Enabled rule | Tone |
|---|---|---|---|---|
| 1 | `back` | "Back to Tracks" | always | `nav` |
| 2 | `shuffle` | "Shuffle on" / "Shuffle off" (the legend states the current state) | not during the shuffle fade (BS:683) | shuffle on: `on` (#FFFFFF, WARM 1.0). Off: `off` (#7A7A7A, WARM 0.30). |
| 3 | `heart` | "Liked · tap to remove" / "Like this track" | the Apple Music ratings API is reachable (R:226) | liked: **pink `rgb(255,40,90)`** in the footer and LED pink at 1.0. Otherwise `nav`. |
| 4 | `play` | "Play this track" | | `go` |

**(b) LCD, list layout** (BS:958; S01:119)

| Element | Copy |
|---|---|
| Label | "**UP NEXT · SCREEN**" |
| Title | focused track title (22/26, 2 lines) |
| Sub-line | its artist. Rows added with Play next also show only the artist here; the album appears only on screen. |
| Meta | `{i} / {n}`, plus " · playing" when the focused row is the one now playing |
| Art | the focused track's album cover |

**(c) Ring:** played / now / upcoming / cursor levels (1.7), plus the tint. MIDI SKIPPER, 20 detents.

**(d) Behaviour**
- **Guards:**
  - Turns are ignored during the shuffle fade (about 200 ms) and during Play (BS:719).
  - At either end: End stop, plus the screen bumping 14 px (BS:721).
- **Shuffle (2)** (BS:682–692):
  - The Scatter moment plays.
  - At 200 ms the rows **after the one now playing** are reordered, and the focus jumps to `min(n−1, now+1)`; the knob needs re-entry.
  - Turning shuffle off restores album order and keeps the current track.
  - Toast "Shuffle on · up next reshuffled" or "Shuffle off · album order".
- **Like (3)** (BS:657–663):
  - Toggles the like. The pink Bloom plays **only when liking**, and the heart pops for 420 ms on screen.
  - Toast `Added to Favourites · {t}` or `Removed from Favourites · {t}`.
- **Play (4)** (BS:693–698):
  - The focused row grows. At **380 ms**: → **Home**, flip −1, that track plays, toast `Playing {t}`.
- **Back (1):** → Tracks, flip −1 (BS:681). `tPos` stays as it was before Up next opened.

### 3.7 Windows (the picker is on screen; legend "Windows · picker on screen", BS:972; turn "Turn: choose a window")

**Open.** Home + 4 (BS:737, 817–824).
- The return mode is Home, the sides are cleared, and any toast is cleared.
- LCD flips +1.
- The **art fades out over 560 ms and scales to 1.06 over 1100 ms**, and the scrim goes to 0 (BS:1089).

**(a) Buttons** (BS:974; R:80; S01:80)

| Slot | Icon | Legend | Enabled rule | Tone |
|---|---|---|---|---|
| 1 | `back` | "Back · restore focus" | always. S03 / the current companion disable it while a switch is out (CT:560). | `nav`. **No longer red Cancel.** |
| 2 | `rect` + left half | "Snap left" | the highlighted window is open (recommended; not designed) | `nav`. When the left side is assigned: footer `rgb(app colour)`, LED app colour 1.0. |
| 3 | `rect` + right half | "Snap right" | as slot 2 | as slot 2, for the right side |
| 4 | `check` | "Switch to window" | not a closed window, and no switch pending (KM:491) | `go` |

**(b) LCD** (BS:244–249; S01:121; R:122–125)

| Element | Box | Type | Copy |
|---|---|---|---|
| App icon | 32 × 32 at x 104, top 42 | the app's icon | Fallback in BS / S04:106: a tile in the app's dominant colour with its white first letter, 16 px weight 700. S03:152 uses a #444 tile with an #F2F2F2 letter, at 35 % when the window is closed. |
| App name | x 35, w 170, top 80 | 14/18 #A6A6A6, 1 line | app name |
| Window title | x 35, w 170, top 100 | 16/20 #F2F2F2, 2 lines, balanced | cleaned window title |
| Meta | x 30, w 180, top 139 | 12/14 #7C7C7C, 1 line | Only the left side assigned: `Left: {App} · pick right`. Only the right: `Right: {App} · pick left`. Otherwise "" (BS:975). S03:155 adds "Closed · can't switch", "Switching…" and "Didn't come forward · retry" (#FF8A7A). |

- **No label, no count, and no display or profile details** (R:125; S03:157).
- **No art.**
- The LCD always describes the **highlighted** window. The snapped badge ("◧ Left" / "◨ Right") appears only on the screen card (BS:907, 912).

**(c) Ring:** app-colour landmarks and cursor, plus the tint (1.7). MIDI SKIPPER over the frozen list.

**(d) Snapping states** (BS:839–857; S01:235–250)

| State | Knob | Screen and timing |
|---|---|---|
| No side assigned | meta ""; slots 2 and 3 `nav` | snap tray hidden |
| Snap left or right | Half-wash on that half; the matching button takes the app colour; meta `Left: {App} · pick right` or `Right: …` | The thumbnail flies (460 ms). The window is placed at **360 ms**. At **420 ms** the highlight moves to the **first window in list order** that is neither this one nor assigned, which needs knob re-entry. The tray drops in (460 ms SPR). |
| Snapping a window already on the other side | that side clears; the window moves (BS:841) | |
| Both sides assigned | meta "" | At **820 ms** the picker closes → **Home**, flip −1, toast `Side by side · {A} and {B}` |
| Back with one side assigned | → Home, flip −1, **no toast** | the other half keeps the previously focused window (BS:832–838) |
| Back with none | → Home, flip −1, toast "Back · focus restored" (BS:829) | focus restored |
| Switch (4) | → Home, flip −1, Wash in the app colour | toast `{app} · {title}` (BS:858–864) |

---

### 3.8 PC away, disconnected, reconnecting
- **LCD:**
  - Current firmware notice: "NANO_D++" / "Waiting for PC" / "**Native controls active**" (FD:1317–1321).
  - The design (KM:369): "NANO_D++" / "Waiting for PC" (or "Reconnecting…") / "Resumes at Volume", with meta "Old turns are discarded".
  - [user] The native profile takes over on native input, so the current copy is the right one. No change.
- **LEDs:** drain, then the amber marks every 5th segment. The native lights take over on native input [user] (AL D5). Buttons are dark (KM:512; S02:81).
- **Input** while disconnected is discarded (S03:229; KM:172).
- **Reconnect:** a fresh state read, then **Home**. Gestures are never replayed (S03:229; KM:297–300).
- **Coming-online moment:** 2800 ms, with the LCD fading up at 1600–2200 ms (S02:150–155). AL D6 leaves out the LCD fade.

---

## 4. State machine

### 4.1 Transitions (knob-relevant)

"flip ±1" is section 1.6. Toasts are desktop-side and are listed because they name the knob event (R:207–210).

| # | From | Input | Guard | To | LCD | LED moments | Toast | Companion effect | Source |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Home | turn ±1 | Sonos reachable | Home | volume reveal | tick; End stop at 0 / 100 | — | volume write (current: at most one per 100 ms, CT:512) | BS:703 |
| 2 | Home | 1 | enabled | Home | status "Paused" / "" | Fill / Pause drain | **none** | play/pause | BS:734 |
| 3 | Home | 2 | — | Recently Added | flip +1 | Reveal | — | load the list | BS:735 |
| 4 | Home | 3 | Tracks enabled | Tracks (Neutral) | flip +1 | Reveal | — | — | BS:736 |
| 5 | Home | 4 | — | Windows | flip +1; art out | Reveal | cleared | open the picker (frozen list) | BS:737, 817–824 |
| 6 | Recently Added | turn | — | Recently Added | item | tick / End stop | — | art for the item | BS:704 |
| 7 | Recently Added | 1 | not pending | Home | flip −1 | Reveal | — | — | BS:739 |
| 8 | Recently Added | 2 | — | Explorer, Recently Added tab, same album | flip +1 | Reveal | cleared | open the explorer overlay | BS:793–798 |
| 9 | Recently Added | 3 | — | Recently Added | meta "Queued next" for 1.5 s | Sweep clockwise from segment 0 | `Queued next · {album}` | AddURIToQueue EnqueueAsNext=1 | BS:776–784; R:224 |
| 10 | Recently Added | 4 | enabled | Home | flip −1 | Wash (album) + Reveal | `Playing {album} · Hall` | replace the queue, play | BS:766–774 |
| 11 | Explorer | turn | not fading or playing | Explorer | item | tick / End stop + 14 px bump | — | — | BS:705–709 |
| 12 | Explorer | 1 | — | Recently Added | flip −1 | Reveal | — | close the overlay | BS:799–804 |
| 13 | Explorer | 2 / 3 | another tab, not fading | Explorer | at 190 ms, flip +1 (playlists) or −1 (recent) | the ring swaps lists | — | tab switch | BS:805–809 |
| 14 | Explorer | 4 | — | Home, at 380 ms | flip −1 | Wash + Reveal | `Playing {name} · Hall` | play | BS:810–815 |
| 15 | Tracks | turn ±1 | within −1…1 | Tracks | position | tick / End stop | — | — | BS:717 |
| 16 | Tracks | 1 | not seeking | Home | flip −1 | Reveal | — | — | BS:749 |
| 17 | Tracks | 2 | — | Up next (focus = now playing) | flip +1 | Reveal | cleared | open the Up next overlay | BS:680, 750 |
| 18 | Tracks | 3 | — | Seek | instant | Reveal | — | — | BS:665–669 |
| 19 | Tracks | 4 | Prev/Next selected, not at an end | Tracks, Neutral | content | Skip sweep ±; `ok` feedback | `Next · {t}` / `Previous · {t}` | next / previous | BS:670–679 |
| 19b | Tracks | 4 | at a queue end | Tracks | — | — | "End of queue" / "Start of queue" | — | BS:673 |
| 20 | Seek | turn ±1 | — | Seek | time | tick / End stop | — | Seek(REL_TIME) 250 ms after the last detent | BS:711–716; R:225 |
| 21 | Seek | 1, 3, or 3 s idle | — | Tracks, Neutral | instant | Reveal | — | — | BS:664, 749, 751 |
| 22 | Seek | 2 | — | Up next | flip +1 | Reveal | cleared | overlay | BS:750 |
| 23 | Seek | 4 | — | (ignored) | — | press only | — | — | BS:752 |
| 24 | Up next | turn | not fading or playing | Up next | row | tick / End stop + 14 px bump | — | — | BS:718–723 |
| 25 | Up next | 1 | — | Tracks | flip −1 | Reveal | — | close the overlay | BS:681 |
| 26 | Up next | 2 | not fading | Up next (focus = now + 1) | content | Scatter | shuffle copy | reorder the queue | BS:682–692 |
| 27 | Up next | 3 | — | Up next | heart ink | pink Bloom when liking | Favourites copy | rating API | BS:657–663; R:226 |
| 28 | Up next | 4 | — | Home, at 380 ms | flip −1 | Reveal | `Playing {t}` | jump to the track | BS:693–698 |
| 29 | Windows | turn | — | Windows | window | tick / End stop + 12 px bump | — | highlight the card | BS:724–728, 1067 |
| 30 | Windows | 1 | — | Home | flip −1 | Reveal | "Back · focus restored" (only when no side is assigned) | restore focus | BS:825–831 |
| 31 | Windows | 2 / 3 | — | Windows, highlight advances at 420 ms | meta and button colour | Half-wash | — | SetWindowPos to the half | BS:839–857 |
| 32 | Windows | 2 / 3 completing a pair | — | Home, at 820 ms | flip −1 | Half-wash, then Reveal | `Side by side · {A} and {B}` | Snap group | BS:851–853 |
| 33 | Windows | 4 | enabled | Home | flip −1 | Wash (app) + Reveal | `{app} · {title}` | activate | BS:858–864 |
| 34 | any | **hold 1 ≥ 600 ms** | — | Home. From Windows it also restores focus; from Seek it exits Seek. | flip −1 (assumed) | Reveal | — | — | R:67; S01:44. **Not in BS.** |
| 35 | any | 5 s without input | not pending or flashing | (rest) | — | settle to dim warm, breath, Song hand | — | — | BS:476–479; S02:92 |
| 36 | connected | USB lost / release | — | away | notice | drain, then amber marks | — | — | S02:157–162; [user] |
| 37 | away | reconnect | — | Home | fade-up | Coming online | — | fresh state read | S03:229; S02:150–155 |

### 4.2 Timers

| Timer | Value | Started by | Effect | Source |
|---|---|---|---|---|
| Rest (LED sleep) | **5000 ms** | every turn or press | dim warm breath; the next input plays Wake and still acts | BS:476–479; S02:92–93 |
| Rest after a change made elsewhere | 3200 ms | external volume event | as above | S02:92 |
| Rest deferral | re-check every 1000 ms | pending, or a flash showing | no sleep while working | S02:92; KM:286 |
| Volume reveal | **1400 ms** after the last detent, **and** only once Sonos confirms; re-check every **400 ms** | Home detent | hide the reveal | BS:703; R:110; S03:98; CT:42, 451 |
| External reveal | 2600 ms | volume changed elsewhere | reveal plus "Changed on Sonos" | S03:99; CT:43 |
| "Changed elsewhere" ring emphasis | 6000 ms | external change | blue cursor | KM:289; PR:30 |
| Paused idle | **4000 ms** after a **confirmed** pause | playAck(paused) | idle icon row | S03:104; KM:253; CT:44 |
| Hold | **600 ms** | button 1 held | Home | R:67; S01:44 |
| Seek send | **250 ms** after the last Seek detent | Seek detent | Sonos Seek(REL_TIME) | R:225; S01:166 |
| Seek idle exit | **3000 ms** after entry or the last Seek detent | entry, each detent | exit Seek, Reveal | BS:664; R:225 |
| Queued next | **1500 ms** (the meta); BS re-renders at 1600 ms | Play next | meta back to `{i} / {n}` | BS:780–782, 964; S01:221 |
| Toast | 1800 ms | any toast | fade | BS:648; R:208 |
| LCD flip | opacity 220 ms, transform 380 ms | a screen change | — | BS:649 |
| Footer colour | 240 ms ease | a tone change | — | BS:253 |
| Explorer tab switch | 190 ms | 2 / 3 | swap, then flip | BS:808 |
| Explorer / Up next Play | overlay closes at **380 ms**; cleanup at 760 ms | 4 | → Home | BS:696–697, 813–814 |
| Overlay close cleanup | 360 ms (explorer, Up next), 320 ms (Windows) | Back | — | BS:681, 803, 830 |
| Shuffle reorder | 200 ms | Up next 2 | reorder, focus = now + 1 | BS:690 |
| Like pop | 420 ms | Up next 3 | — | BS:660 |
| Snap | placement **360 ms**; flying thumb cleared 700 ms; highlight advance **420 ms**; auto-close **820 ms** | Windows 2 / 3 | — | BS:847–855 |
| End-of-list bump on screen | 160 ms; 14 px (explorer, Up next), 12 px (Windows) | turn at an end | — | BS:651, 1067, 1073, 1078 |
| Cap press visual | 140 ms | press | prototype only | BS:650 |
| LED moment durations | tick 180, bound 460, wake 520, reveal 450, press 220, fill 760, drain 860, sweep 640, wash 1100, half 900, bloom 900, scatter 700 | — | — | BS:393 |
| Working comet | 1.4 s per lap, while any action is pending | pending | — | R:163; S02:134 |
| Flash (S03) vs moments (S02) | ok 650 / err 900 (S03:189–190); Confirmed 900, Head shake 700 (S02:135–136) | feedback | — | — |

### 4.3 Input guards and no-ops (BS)
- Explorer: turns are ignored during the tab-switch fade (190 ms) and after Play (up to 760 ms) (BS:706). Pressing 2 or 3 on the active tab, or during a fade, is a no-op (BS:806).
- Up next: turns are ignored during the shuffle fade (200 ms) and after Play (BS:719). Button 2 during a fade is a no-op (BS:683).
- Seek: button 4 is ignored (BS:752).
- Tracks: button 4 at Neutral is ignored (BS:671).
- **Every** press first plays the Press moment and resets the rest timer (BS:732).
- **Not guarded in BS**: presses during overlay animations, snapping during a flying thumbnail, and turns during Play in Recently Added or Tracks.

### 4.4 Hold 600 ms (not prototyped)
The spec is the only source (R:67; S01:44; BS:371 in prose only).

**Current plumbing:**
- The firmware reports pressed and released edges (FW `hmi_thread.cpp:334–345`). AceButton long press is not enabled; only a 50 ms click delay is set (FW `hmi_thread.cpp:258–259`).
- The companion acts on the **down** edge (DV:846–850; RT:1390).

**Recommendation.** Keep button 1 acting on the down edge (up one level, or Play/Pause on Home). If it is still held at 600 ms, go on to **Home** from wherever that press landed.
- It is monotone. Seek → Tracks → Home. Up next → Tracks → Home. Explorer → Recently Added → Home. Windows → Home.
- There is no tap latency.
- On Home a hold is a no-op, so Play/Pause only fires on the press edge.
- The hold can be detected on the knob (AceButton long press at 600 ms, then a new wire event), or on the host by timing `kd` → `ku`. Firmware-side detection is more robust against serial latency.

---

## 5. Working and failing: what the knob shows

### 5.1 Designed
- **The master prototype has no pending or failure states.** Every action in BS is instant and optimistic: Play goes Home and Washes at once, and Switch closes at once. The specs add only the LED side:
  - **Working comet** while waiting on Sonos or Windows (R:163; S02:134).
  - **Confirmed** (green bloom) on success, **Head shake** (red) on failure (R:164; S02:135–136).
- **S03 / KM LCD copy still applies**, because the master doesn't replace it:

  | Where | State | Copy |
  |---|---|---|
  | Home | volume pending | "Setting…" |
  | Home | transport pending | "Starting…" / "Pausing…" |
  | Home | changed elsewhere | "Changed on Sonos" |
  | Home | Sonos offline | "Sonos unavailable" / "Looking for Sonos…" / "Windows still works" |
  | Recently Added | pending | "Starting…" |
  | Recently Added | partial failure | "Queue replaced · didn't start" (#FF8A7A) |
  | Recently Added | loading | "Loading…" |
  | Recently Added | empty | "Nothing recently added" |
  | Recently Added | sign-in | "Apple Music sign-in expired" / "Renew on your PC" / "Windows still works" |
  | Tracks | pending | "Skipping…" |
  | Tracks | no previous | "Previous unavailable" |
  | Windows | pending | "Switching…" |
  | Windows | failure | "Didn't come forward · retry" (#FF8A7A) |
  | Windows | closed window | "Closed · can't switch" |

  Rules that go with it: Back is disabled while a Play is pending (no undo, S03:228), and nothing is replayed after a reconnect.
- **The current companion adds compact knob copy** (CT:1049–1091): "Music login needed", "Playback incomplete", "Group changed", "Queue changed", "Connecting knob", "Knob disconnected", "Action failed: see app", "Library not loaded / Home, then Browse to retry", "Preparing playback", and "No eligible windows".

### 5.2 Gaps in the master (recommended defaults, consistent with S03)

| Case | Recommended knob behaviour |
|---|---|
| Play next pending or failed | meta "Queueing…", then Head shake plus meta "Couldn't queue" in #FF8A7A; stay in Recently Added |
| Play from the explorer, Up next or Recently Added | Decide optimistic (BS) or confirmed (S03 / current). Recommended: keep the confirmed flow. Show "Starting…" with the Working comet, then go Home with the Wash on `ok`, as AL D7 / D8 already assume. |
| Seek send failed, or an unseekable source (radio, stream with no duration) | Seek button `dim` when the duration is unknown. On failure, Head shake and stay in Seek. |
| Like unavailable (R:226: the API may be unreachable) | slot 3 `dim`, or the fallback R suggests (Play next for the highlighted track) |
| Shuffle failed | Head shake; the order is unchanged |
| Up next queue still loading | label "UP NEXT · SCREEN", title "Loading…", sub-line "Sonos queue" |
| Explorer loading / empty / sign-in (either tab) | S03's full-screen list states, with the "RECENT · SCREEN" / "PLAYLISTS · SCREEN" label |
| Snap failed (SetWindowPos refused, or a fixed-size window) | Head shake, meta "Couldn't snap"; no side assigned |
| Snap or Switch on a closed window | slots 2–4 `dim` (S04:111 disables Switch on closed windows) |

---

## 6. Prototype artefacts and internal contradictions (do not port)

1. **End stop on every other 1 % detent.** BS detects the bound when the ring cursor didn't move (BS:584). The volume arc is 2 % per segment and Seek's lap is D/60 s per segment, so mid-range detents also flare. AL D4 already rules: BOUND is the haptic end stop.
2. **Paused Play breathes WARM in BS** (BS:508, 944). The specs say green (S01:100; S02:106; KM:510).
3. **Hold 600 ms is not implemented** in BS.
4. **There is no idle icon row** in BS. Use S03 / KF.
5. **The volume reveal hides at 1.4 s even when unconfirmed** in BS (BS:703). The spec waits for Sonos.
6. **The BS note "Freed buttons in Tracks" (BS:376) is stale.** It says 2 opens Up next and 3 is Like; the map says 3 is Seek and Like lives in Up next.
7. **What Like means.** S01:222 says Like "feeds the explorer's Favourite playlists". R:226 says it rates the **song** and does **not** appear there, and R wins. The toast `Added to Favourites · {t}` (BS:662) fits S01, not R.
8. **Toasts over an open overlay.** Like and Shuffle toast while Up next is open (BS:662, 691), against R:209 ("Never shown over an open overlay").
9. **Footer dim ink:** #5A5A5A in BS (BS:938), #4A4A4A in S03:51, KM:312 and the firmware (FP:96).
10. **Flip distance:** 16 px in BS (BS:649), 20 px in R:126 and S03:161.
11. **Dead fields and code:** `lcd.metaCol` (BS:979); Home's `lcd.labelTop/titleTop/subTop` (BS:945); `shufflePlay()` (BS:785–792), which no button reaches.
12. **Recently Added first entry** is item 2 (`rIdx: 1`, BS:596). S03:30 says item 1.
13. **Back from the explorer on the playlists tab** doesn't sync `rIdx` to the Recently Added position browsed earlier (BS:801). S01:84 says "keeping the same album". Recommended: always use the explorer's Recently Added index.
14. **Snap auto-advance** picks the first eligible window **in list order**, not the next one to the right (BS:854).
15. **Windows Back toast:** "Back · focus restored" (BS:829). S04:80 says "Cancelled · focus restored".
16. **"Only button 4 is ever green"** (R:234) against the green paused Play on button 1 (R:138; S01:100).
17. **The Up next ring has no window.** Positions `(k − c0)·3` wrap past 20 items (BS:1007). The current v4 window rule (FP:126–131, 20 entries) needs to be applied.
18. **The Seek playhead is frozen** in BS (BS:634). Sonos keeps playing.
19. **Drag step** is 18° in Tracks (BS:872). The real profile is 8 detents per turn.
20. **Seek handle position:** the path puts it at about 65 % of the icon. R:95 says "≈ 60 %".
21. **Copy S03 forbids.** S03:147 ("Never show the next song's title before the skip") is superseded by R:119.

---

## 7. Open questions (need a decision before building)

1. **Recently Added paging and More.** The master has one flat list shared with the explorer (BS:704, 795). The current companion pages 10 at a time, with More and lookahead (CT:344–354, CT:607–628), and S03 has "RECENTLY ADDED · P2". Keep pages on the knob, or show the whole list, and how does the explorer's index map across pages?
2. **Idle row words and order.** The row should mirror the new footer (Play/Pause · Browse music · Tracks · Windows).
   - The words would be "Play/Pause" · "Browse" · "Tracks" · "Win".
   - "Browse music" and "Windows" don't fit the 46 px columns at 12 px.
3. **Optimistic or confirmed Play and Switch.** BS is instant. S03 and the current companion wait for confirmation, with Back disabled while waiting. See 5.2.
4. **Hold semantics.** The recommendation is in 4.4. Also: does a hold on Home do nothing, and does it suppress the release?
5. **Seek details:**
   - the position mapping (section 2);
   - does the time keep ticking in Seek (BS: frozen);
   - what the knob shows between the send and Sonos confirming;
   - Seek for sources without a duration.
6. **Up next with a long queue.** It needs the ring window (artefact 17), and a knob state while the queue loads.
7. **Like fallback** when the Apple Music API is unreachable (R:226).
8. **Error copy** for Play next, Seek, Like, Shuffle and Snap (5.2).
9. **Windows tile fallback:** the app's dominant colour with a white letter (BS, S04), or #444 (S03, current)?
10. **Text shadow on LVGL.** LVGL 9 labels have no text-shadow and the LVGL heap is 64 KB (FD:37–39). Options: a 1 px-offset black duplicate at about 80 % opacity (no blur), or none.
11. **Tabular digits for Seek.** Montserrat's digits are proportional. Use a fixed advance per digit cell, or regenerate a tabular 48 px and 14 px digit subset.
12. **Footer dim ink:** #5A5A5A or #4A4A4A.
13. **Screen-change distance:** 16 or 20 px. And does the art cross-fade with the content (current) or stay still (BS)?
14. **Does entering or leaving Seek slide?** BS: no (an instant swap plus the ring Reveal).

---

## 8. Deltas vs current (firmware cc5.3 + desktop v6, plus ALIVE cc5.4 / v7 in progress)

| # | Area | Current | Master design | What changes |
|---|---|---|---|---|
| 1 | **Home button map** | 1 Play/Pause · 2 Browse (`list`) · 3 Win (`win`) · 4 Tracks (`tracks`) (CT:979–992) | 1 Play/Pause · 2 **Browse music (`note`)** · 3 **Tracks (`list`)** · 4 **Windows (`win`, new path)** (BS:944) | Slots 3 and 4 swap. The wire token `list` changes meaning (Browse → Tracks), and Browse gets a new icon. |
| 2 | **Windows entry / HID F24 path** | `windowsButton = 2` (slot 3). F24 fires in **any** mode when that slot is enabled (FW `control_center.cpp:294–297`). RT:1387 skips the serial edge for logical 2 (CT:139, 531–535). | Windows is **slot 4, Home only** (R:81) | Set `windowsButton = 3`. F24 must fire only on Home, e.g. only when the slot's icon is `win`; otherwise Play or Skip on button 4 would send F24. `controller.button(2)` in RT:1093 must be remapped. |
| 3 | Button 1 outside Home | Back. Recently Added steps back through pages. Windows: **red Cancel** (`stop`, FP:170). | **Back** everywhere, `nav` (no red). Up one level: Explorer → Recently Added, Up next → Tracks, Seek → Tracks (S01:82–87) | Cancel and the `stop` tone retire from the knob. There is no page-back (open question 1). |
| 4 | Button 2 outside Home | **Home** (`home`) in Recently Added, Tracks and Windows (CT:979–981) | Recently Added / Tracks: **Open on screen** (`expand`). Explorer: Recently Added tab. Up next: Shuffle. Windows: Snap left. | The Home icon retires; Home becomes the 600 ms hold. |
| 5 | Button 3 outside Home | **Win** everywhere (CT:981) | Recently Added: **Play next**. Tracks: **Seek**. Explorer: Favourite playlists. Up next: **Like**. Windows: **Snap right**. | "Windows opens only from Home." |
| 6 | Button 4 | Home: Tracks. Recently Added: Play (green) / More (white). Tracks: Prev/Next/Skip (`prev`/`next` icons). Windows: Switch (`switch` arrows). | Home: Windows (nav). Recently Added / Explorer / Up next: Play (go). Tracks: Skip with **skip-back / skip-forward**, dim at Neutral or while seeking. Windows: Switch with **`check`**. | More is gone from the master. The Switch glyph changes. |
| 7 | **Hold 600 ms = Home** | none. The companion acts on down edges (DV:846–850). | required (R:67) | New hold detection; see 4.4. |
| 8 | **New knob modes** | volume, recent, tracks, windows (CT:36–37). Layouts nowPlaying / volume / idle / recent / tracks / windows / notice (FW `cc_frame_parse.cpp:14–16`; P4:71). | + **Explorer mirror**, **Up next mirror**, **Seek** | Contract bump: new layout (`seek`) and headings. The list mirrors can reuse the `recent` layout. They need their own group or depth, or an explicit slide direction (row 17). |
| 9 | **Icon vocabulary** | wire: `play pause list win tracks back home more prev next switch cancel ""` (P4:86). Firmware masks also include ok, dot, warn, usb (FW `cc_icons.cpp:110–157`). | new: note, expand, clock, list-music, list-plus, seek, shuffle, heart, rect + filled half left/right, check, skip-forward. Changed paths: back (chevron, was arrow), play, win (window, was two windows), list (dots at x 3.5) (BS:395–405) | New A8 masks at 20 px, and at 26 px for the idle row's Home icons. The two-path Snap icon needs a filled half. The contract token list grows, so parser and validator must agree. |
| 10 | **Footer inks and button LEDs** | tones none / dim #4A4A4A / stop #FF8474 / go #6ED996 / nav #E6E6E6 (FP:94–100); LED from the tone (AL 5.3) | + **on** #FFFFFF / WARM 1.0; + **off** #7A7A7A / WARM 0.30; + **custom colour** (pink 255,40,90; app colour) at 1.0; dim #5A5A5A? (BS:938, 983) | New tones in the frame, e.g. per-button `tone` / `accent`, because `tone(slot, icon, enabled)` (FP:164–174) can't express pairs or modifiers. AL 5.3 needs on, off and custom. |
| 11 | Recently Added LCD | meta `{i}/{n} · Replaces queue` / `· Not available` / `· Sonos unavailable` / "Starting…" etc.; heading "RECENTLY ADDED · P{n}" (CT:1126–1160) | meta `{i} / {n}` or "**Queued next**" for 1.5 s (BS:964) | Drop the consequence copy and page headings (unless open question 1 decides otherwise). Add the Queued-next timer. |
| 12 | Tracks LCD | line always `Now: {title}`; meta "One press, one skip" / "Press once to skip" / "Skipping…" / "Skipped · back at neutral" (success) (CT:1161–1183) | line `Now: / Next: / Prev: {title}`, "End of queue" / "Start of queue"; meta "Press 4 to skip" / `{i} / {n}[ · shuffle]` (BS:952) | The companion needs the Sonos queue (next and previous titles, index, count, shuffle). The "Skipped" copy goes. |
| 13 | Tracks position row | named 16 px icons prev / dot / next at x 72 / 112 / 152, stroke 2.4 (FD:64–65, 856–861) | skip-back · **6 × 6 filled circle** · skip-forward across x 72–168, stroke 2.3 (BS:230–234) | New glyphs; the dot becomes a circle. |
| 14 | **Seek layout** | — | "SEEK", caption, 48 px `m:ss`, `of m:ss` (BS:238–243) | `cc_font_48` has only `% - 0–9` (FW `fonts/cc_fonts.h:12`), so **U+003A `:` must be added**. Tabular digits (open question 11). A new layout, and a profile swap within Tracks. |
| 15 | Seek ring | — | the song lap (BS:999–1002) | A new ring style. The host already sends `progress` (AL section 3), but the lap must be drawn **awake** in Seek, not only as the resting Song hand. |
| 16 | Explorer / Up next rings | — | item or album colours; Up next levels 0.14 / 0.70 / 0.45 / 1.0 (BS:1005–1013) | Up next needs per-entry levels (played / now / upcoming) on the selection ring. AL 5.2 lacks 0.14 and 0.70. Long queues need the window rule. |
| 17 | **Screen change** | on a group or page change only; ±**20 px**; the **stage** (art, content and footer) fades 0 → 255 over 220 ms while the content, including the footer, slides 380 ms (FD:1263–1274, 1223; P4:275–276) | ±**16 px** (BS) or 20 (spec); **the text layer only**; footer and art stay; the direction is explicit per transition, including the explorer tab switch within one mode (BS:649, 808) | Carry an explicit slide direction (or new depths). Take the footer out of the sliding layer. Stop fading the art on screen changes. |
| 18 | Art on Windows | hidden **instantly** (`prepareArt` → ART_NONE → `hideArt`, FD:1025–1031, 961–969) | fades **560 ms OUT** and scales to **1.06** over 1100 ms; scrim to 0 (BS:1089) | Use the idle-view fade. The firmware animates translate and opacity only, with no scale (FD:37–39), so the scale is a documented deviation. |
| 19 | **Scrim** | composited on the host: stops (row, opacity) (0, .35) (108, .55) (149, .90) (168, 1.0), × 0.8 art (AW:56, 237–241) | **.60 / .72 / .92 / solid** at 0 / 45 / 62 / 70 % (R:108) | Change `_SCRIM_STOPS` to ((0, .60), (108, .72), (149, .92), (168, 1.0), (239, 1.0)). Content-hash keys change naturally. The `composited: "scrim80"` capability name (ARTWORK2.md:31) may need a new value so that old caches are never mixed in. |
| 20 | **Text shadow** | none | `0 1px 3px rgba(0,0,0,.8)` on all LCD text (R:108) | LVGL has no text shadow (open question 10). This also affects the Python LCD mirror, `lcd_preview.py`, and the floating knob. |
| 21 | Windows LCD meta | "Closed · can't switch" / "Switching…" / "Didn't come forward · retry" (CT:1189–1196) | + `Left: {App} · pick right` / `Right: {App} · pick left` (BS:975) | Snap state reaches the knob frame. |
| 22 | Windows tile | letter tile #444 with an #F2F2F2 16 px letter, or the 32 × 32 app icon (FD:902–927; FP:89) | the app icon; fallback is the app's dominant colour with a white letter (BS W[]; S04:106) | Optional change (open question 9). |
| 23 | Home copy | same geometry; the volume reveal matches (FD:791–839; CT:1216–1238) | unchanged. Caption `Paused · {title}`; "Minimum" / "Maximum" (BS:1084–1085) | No change, apart from the idle row order and words (open question 2). |
| 24 | Paused Play LED | AL 5.3: GREEN breathing on slot 0 (in progress) | green, breathing 2.6 s (S01:100) | Matches. BS's warm breath is an artefact. |
| 25 | **Haptics** | volume BINARIS BEER; recent / windows MIDI SKIPPER; tracks MIDI CLACK JONES (CT:36–37) | + Seek on BINARIS BEER within Tracks; Explorer and Up next on MIDI SKIPPER | New entries. **Host-driven position moves** (Snap auto-advance, Shuffle focus, tab switch, Seek, return from the explorer) each need a re-entry with the new position (CT:279–282). |
| 26 | Play from Recently Added | pending "Preparing playback" / "Starting…" with Back disabled; on `ok` → Home with the ok flash (CT:629–634, 864–866) | BS: immediately → Home + Wash (BS:766–774) | Decide (open question 3). AL D7 / D8 assume the confirmed flow. |
| 27 | Windows Switch | pending "Switching…", verify, then Home + ok (CT:896–906) | BS: immediately Home + Wash (BS:858–864) | Same decision as row 26. |
| 28 | After a Tracks skip | Neutral + "Skipped · back at neutral" until the next turn (CT:860–863, 1170–1171) | Neutral + `{i} / {n}`; Sweep (BS:676) | Drop the success copy. The Sweep is already in AL (D9 `feedback.skip`). |
| 29 | New LED moments | AL: boot, down, wake, tick, bound, bloom, fail, sweep, fill, drain, shimmer, wash, reveal, press (AL:265) | + **half** (Snap), **scatter** (Shuffle), **pink bloom** (Like), and a **sweep from segment 0** (Play next) (BS:541–543, 781) | Extend AL. It must also carry triggers the knob can't infer: snap side and colour, shuffle, like, queued. |
| 30 | Recently Added paging | pages of 10 with More and lookahead (CT:344–354, 607–628) | a flat list, no More (BS:704) | Open question 1. |
| 31 | Offline LCD | "NANO_D++" / "Waiting for PC" / "Native controls active" (FD:1317–1321) | KM: "Waiting for PC" / "Resumes at Volume" | Keep the current copy ([user] native profile behaviour). |
| 32 | Floating knob and LCD mirror | `lcd_preview.py`, `knob_face.py` and `overlay.py` mirror FD and the v4 LEDs | [user] the same choreography | Every row above also lands in the Python mirror. |
| 33 | Label / heading box | x 30, w 180, top 31 (FD:50) | x 35, w 170, top 32 (BS:222); KF used 30 / 180 | Minor. The chord fitting already clamps to the safe circle. |
| 34 | List meta box | x 24, w 192 (FD:60) | x 35, w 170 (BS:225); KF 24 / 192 | Minor. |
| 35 | Tracks title box | x 30, w 180 (FD:61) | x 35, w 170 (BS:229) | Minor. |
