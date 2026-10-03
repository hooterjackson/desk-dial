# alive: "Warm · alive" LED choreography (1.0.0-cc5.4, desktop v7), revision 2

> **Status: authoritative. This is `ALIVE.md` revision 2** (contract **K2** of `V5_VOCABULARY.md` §0), 2026-09-25, for the
> one release firmware 1.0.0-cc5.4 + desktop v7. It is the draft `ALIVE_R2_DRAFT.md`, merged here after round 2 of the
> "Warm · alive" integration passed its gates (build-only 1.0.0-cc5.4 at 20:38 UTC: static RAM 259,328 B, flash
> 1,048,929 B), plus the round-2 records **C2**, **F1/W2**, **W1** and ruling **Q1** (section 12.5). Revision 1's deviations
> D1–D18, its rulings R1–R6 and D19 and every section 12 record are carried unchanged in meaning (12.1, 12.2).
> `ALIVE_R2_DRAFT.md` stays next to this file for history, marked superseded; its section numbers are this file's, so a
> citation of either ("ALIVE_R2_DRAFT §10.2", "K2 §10.2") resolves to the same text. Documents only: the merge built and
> ran nothing.
>
> **[r2] Consistency pass (2026-09-25).** The cross-doc changes of 13.1 (X1–X12) were applied to VOC, K1, K3 and K4, and
> this revision (then the draft) was aligned with them: VOC §6.2 now defines the tuning fields (3.2) and K1 carries them; K1 strips
> `ring.unavailable` on `upnext` (3.1, 5.1.4); K1's loading-list form is its §4.6 (5.1.3); OQ-3 is settled with K1 (8.1);
> K4 adopted the /318 glow scale, M27 with its catch-up, and one knob budget (10.3).
>
> **[r2] Marking.** Every change against revision 1 is marked **[r2]**. A heading marked "[r2] (new)" is new in full; a
> heading marked "[r2] (rewritten)" replaces that revision 1 section in full. Unmarked text is revision 1's and still holds.
> **[Q1]**, **[C2]**, **[F1/W2]** and **[W1]** mark the round-2 additions of the merge (12.5).
>
> **[r2.2] Design follow-up r2.2 (2026-09-25, late).** **[r2.2]** marks the changes for
> `design_handoff_nano_d_master_r2.2\CHANGELOG.md` "r2.2 — follow-up 1 from engineering" (VOC key **R22**; VOC-R26…R29):
> the liked heart button is PINK at **0.30** (new tone `liked`, M32), the `unlike` moment is retired (reserved, plays
> nothing, never a trigger), and the Working comet's pending span covers every Seek jump until playback resumes and the
> whole Play next job, lookup included (M33). The rows are listed in section 0. Nothing else in this revision changes.
>
> **[errata] Phase-2b gate (2026-09-26).** Lead ruling **R-i** corrects the hidden floating knob's test for a summon
> (11.5, M27; DESKTOP_STAGE §6.6 H9): the first visible frame equals the M27 reference, and the comparison with
> the continuously rendered twin applies from +300 ms. The engine, M27, the wire and the knob are unchanged. Tagged
> **[erratum R-i]** and listed in 12.6 (E-i).
>
> **[ruling 12.7] LED output (user ruling, 2026-09-26).** After the hardware window rolled binary A back (its temporal
> dither, then on by default, made the resting and offline LEDs flicker), section 9's temporal dither is **off by
> default** (`ledDither:true` re-enables it) and dither off adds the **F-T brightness floor**: a target-lit LED whose
> plain rounding is dark shows one count on its dominant channel, so the dimmest designed marks stay visible. Sections
> 3, 4, 9 step 4, 10.1 and 11 carry it, tagged **[ruling 12.7]**; 12.7 records the ruling, the oracle numbers and the
> same-day amendment of the floor's channel rule (the first reading, `round(v/m)`, made a breathing mark jump at its
> dim point). The engine's `e`, the palette, the power budget, the wire and the host are unchanged.
>
> **[ruling 12.8] Resting and HOT (user ruling, 2026-09-26, later the same day).** Resting is **one steady dim warm
> white**: every lit resting segment at 0.34, the buttons at 0.34 / 0.26, no rest breath, time of day never below
> 0.80, and no song-progress hand at rest. **HOT == WARM**: the chases, the song hand and every other hot accent use
> the same warm white. 12.8 records it; it supersedes the resting column of 5.2 (and D10's 0.13), 5.3's M18 resting
> levels, the rest breath of 8.2, 8.3's resting factor, 8.4's song hand at rest and section 2's HOT.

This is the contract for the LED behaviour from the Claude Design handoff
`app/design-reference/design_handoff_led_choreography/`. The two
design sources are:
- `README.md`, the spec;
- `Ring Choreography v2.dc.html`, whose logic class is the reference: `draw()` and `detect()` are at lines 198–396, and `finishAlive()` is at `knob-model.js:496–516`.

**[r2]** It also covers every LED addition of the **r2.1 master design**
(`design_handoff_nano_d_master_r2.1\`), for the one combined release firmware 1.0.0-cc5.4 + desktop v7:
- R §6 (R:89–107) and the r2 override block of S02 (S02:3–26);
- S01 §2 "Button LEDs" (S01:97–108), §4 "Ring" and its moments table (S01:159–194), §4b Seek (S01:198–204),
  §4c/§4d (S01:215, :227), §6 Like and Shuffle (S01:344, :359) and §10 Reduced motion (S01:432–442);
- the **Browse and Snap** logic class (the primary prototype): `draw()` BS:597–695, `play()` BS:578–586,
  the ring and button targets in `renderVals()` BS:1232–1333, and the moment triggers in its handlers (BS:823–1097);
- CH §7 (the r1 → r2 contradiction rulings) and CH "r2.1" (CH:109–117).

**[r2] Source keys.** This document uses the keys of `V5_VOCABULARY.md` §0.1 (R, CH, S01, S02, BS, KM, 00, A02, A04, A05,
CS, RF0, P4, FA, FK, CT) plus **RC** = `HO\prototypes\Ring Choreography v2.dc.html` (the r2.1 copy; byte-identical to the file
revision 1 was written against, A02 §0, so "design line N" in the unmarked text means RC:N), **AL** = ALIVE.md revision 1 (as published before this merge; its text is carried here unmarked, and `AL:n` line
citations in the other contracts refer to that revision's line numbers),
and **VOC** = `firmware\V5_VOCABULARY.md`. Every name, token, enum value and copy id is VOC's, used verbatim.

It **replaces the LED part of PRESENTATION_V4.md section 5** whenever the knob advertises
`alive`. **[r2]** The screens, haptics, button meanings and frame text are K1's and K3's. The v4 ring geometry is **no
longer reused as is**: section 5.1 defines the alive geometry for every ring style (the volume half-step, the value gate, the
re-centred 20-entry window, Up next and the Seek lap all depart from v4). The v4 model (`cc_lights` / `preview_lights`) stays,
unchanged, for the non-alive path. When the knob lacks `alive`
(cc5.3 and older), every host behaviour stays exactly as today.

User decisions (2026-09-25) that override the design are marked **[user]**, and deliberate
deviations are marked **[Dn]** (section 12). **[r2]** Rulings and deviations for the master additions are marked **[Mn]**
(section 12.3; `M` because ALIVE.md already uses D19, VOC-N17). Where this document and the design disagree,
this document wins. Where this document is silent, the design's code wins, and the
implementer records the case in section 12 before shipping.

**[r2] Precedence between the design sources.** For **targets and triggers**: R, then S01, then S02, then BS `renderVals()`
and its handlers, then KM `finishAlive()` and RC `detect()` (R §0; A02 §0). For **recipe math**: RC `draw()` for every recipe BS leaves unchanged,
and BS `draw()` for the recipes BS adds or changes (`half`, `scatter`, the colour `bloom`, the stationary `fail`). Where a
specification sentence and BS code disagree, the specification wins (e.g. `down`, M19).

---

## 0. [r2] (new) What revision 2 changes

| Area | Change | Where | Id |
|---|---|---|---|
| Volume arc | Amber/red body 0.62 like warm; half-step 0.81 in every role; the half-step lights the **next** segment (cursor at 35 + ⌊v/2⌋); colour gated on value **and** position | 5.1.2, 5.2 | M1, M2, M13 |
| Lists | Only their items' colours: no More double mark, unavailable cursor keeps its colour at 0.45, pending cursor pulses in its colour, a loading **list** shows only the Working comet (an unloaded item inside a known list is a warm landmark, not "loading"); the 20-entry window is re-centred | 5.1.3, 5.1.8 | M3, M9, M31 |
| Up next | New pattern: played 0.14, now playing 0.70, upcoming 0.45 (any colour), cursor 1.0, on absolute `ring.now`; the Sonos-shuffle card (`ring.card`, the last entry) has no mark | 5.1.4 | M14 |
| Offline | The native handover lasts until the next claim (AL's 5 s return of the amber marks withdrawn) | 8.1 | M29 |
| Seek | New `lap` ring: played 0.62, every 5th unplayed 0.30, head 1.0, all warm; no local cursor | 5.1.6, 6.3 | M11 |
| Buttons | Pair `on` 1.0 / `off` 0.30, PINK heart (**[r2.2]** at 0.30, row below), snap side in its app colour, paused Play green breath; resting 0.12 / 0.04 by awake level | 5.3 | M8, M18, M25 |
| Families | `explorer`, `upnext` added; ambient tint and the D7 wash on recent, explorer, upnext, windows; Reveal also on `transport ↔ lap` | 5.4, 6.4 | M10 |
| Moments | `feedback.moment`: `queued` sweep from 0, `shuffle` scatter (r2.1 spread), `like` pink bloom, `unlike` nothing (**[r2.2]** retired, row below), `snap` half-wash, `started` wash; no target flash with a moment | 6.4, 7 | M5–M7, M16, M21 |
| Reduced motion | Latched `reducedMotion`: Wake, Spin trail, Sweep, Scatter, Reveal skipped; Head shake stationary; colour moments kept | 6.5 | M17 |
| Palette | PINK (candidate 255,40,90, never `sat()`), with a runtime tuning field; `ledVolFull` A/B field | 2, 3.2 | M24, M25 |
| Floating knob | Engine on the overlay thread, rendered every vblank (240 Hz), one render per posted message while hidden, six pre-rendered glow looks scaled by ring diameter / 318, the design's fill and glow styling, ring only (no button strips); frame-rate gate is DESKTOP_STAGE §6.3's | 10.3 | M20, M27, M30 |
| Firmware cadence | Deadline cadence 16/17/17 ms; `ledFps` gate ≥ 58 idle / ≥ 45 under load (55 is a recorded target: it needs R7, not in cc5.4); `ledShowGapMsMax`, `ledLateShows` diag; scope text no longer claims the LCD is untouched | 10.1, 11.9 | — |
| **[r2.2]** Buttons | The liked heart (`heart` + `lit:"on"`) is tone **`liked`**: PINK at **0.30** (not the 0.14 dim level, not 1.0), never `sat()`; resting WARM 0.04 by M18 | 5.3 | M32 |
| **[r2.2]** Moments | `unlike` retired: no host sends it (Like is add-only, R22 CH §1); the reserved token plays nothing and is no trigger; no hold | 3.1, 6.1, 6.4, 11 | M32 |
| **[r2.2]** Pending | The Working comet must run for **seek-in-flight** (every jump until playback resumes, ≤ 8 s each, across a follow-up jump) and **play-next-in-flight** (`Finding songs…` lookup included); the engine sees both only as `activity:"pending"`, which K3 sends for the whole span | 6.1, 5.1.6, 8.4 | M33 |
| Verification | A second oracle on BS `draw()`, a BS `renderVals()` golden, new twin sequences, floating-knob frame-rate tests, tour additions | 11 | — |

---

## 1. Capability and versions

- Firmware `NANO_FIRMWARE_VERSION` is `1.0.0-cc5.4`.
- Capabilities gain a sibling object. Every existing key is unchanged:
  `"alive": {"version": 1, "fps": 60, "drive": <effective default drive 1..255>}`.
- **[r2]** `alive.version` **stays 1**, and version 1 **means revision 2**: no cc5.4 ships without the master additions,
  because it is one release (00 §3.2 "Capability"; A02 §9 §1). The v5 frame fields the additions read are carried by
  `presentation: 5` (K1; VOC §6.5). A cc5.4 knob always advertises both.
- The host (desktop v7) uses sections 3–4 only when `capabilities.alive.version == 1`. With older firmware it sends no new field, and its floating knob keeps using `PreviewLights` (v4 model).
- An old host (v6 or earlier) with cc5.4 firmware:
  - It never sends the new fields.
  - It ignores the new `lim` event, because `device.py:_consume` reads only `p/ks/ku/kd` of an id-tagged message.
  - The knob still runs the full choreography from frames and local input. There's no time of day (the resting brightness factor stays 1.0), no song hand, and no Play/Pause/Skip moments.
  - **[r2]** The engine applies the revision 2 targets to its v4 frames: the M13 half-step, the M2 value gate, M1 levels,
    the re-centred window (M9), a legacy `moreIndex` entry as one warm item (M3), `cancel` on slot 0 as tone `stop`
    (red), and the D7 wash / green bloom for every `ok` (no moment field, no reduced motion).

**[r2] Compatibility matrix**

| Host \ knob | cc5.3 (`presentation: 4`, no `alive`) | cc5.4 (`presentation: 5`, `alive: 1`) |
|---|---|---|
| **v6** | unchanged | revision 2 targets on v4 frames (above); no moments beyond AL §6.4 |
| **v7** | K1's presentation-4 downgrade (VOC §2.2: `lit`, `color`, `ring.now`, `feedback.moment/side/color`, `reducedMotion` stripped; `lap` → `off`); floating knob on `PreviewLights` | everything in this document |

## 2. Palette (design space, sRGB 0–255, before the transfer curve of section 9)

| Role | Design-space colour, 0..1 per channel | LED output at full (section 9 transfer) | Source |
|---|---|---|---|
| WARM | **1, 0.746862, 0.411645** | #FF8424 exactly | [user]: warm is fixed all day (the design's time-of-day colour is not used) |
| HOT | mix(WARM, white, 0.5) = **1, 0.873431, 0.705823** | — | design |
| GREEN (confirm) | **0, 1, 98/255** | ≈#00FF1F | design |
| RED (volume ≥ 90 %, Cancel, Fail) | **1, 0, 0** | #FF0000 | [user]: the design has 255,24,0 |
| AMBER (volume 80–90 %, offline marks) | **1, 0.514232, 0.218649** | #FF3A0A exactly | [user]: the design has 255,118,0 |
| BLUE (changed elsewhere) | **40/255, 140/255, 1** | — | design |
| **[r2] PINK** (liked heart, Like bloom; **[r2.2]** the liked heart button at 0.30, 5.3) | **1, 40/255, 90/255** = 1, 0.156863, 0.352941 (candidate) | ≈#FF051A (255, 5.41, 26.07) | R:100; S01:106; S02:15 (a candidate the user picks on the ring; section 14 Q2). **Never `sat()`**: `sat(255,40,90)` = 255,11,68 (R:100; CH §7 #22) |
| **[r2] PINK spark** | mix(PINK, white, 0.3) = **1, 0.409804, 0.547059** | — | BS:656 (the bloom spark is `mix(c, white, 0.3)` of the bloom colour) |
| App/album accent | `sat(dominant)` (below) | — | design |

- **Derivation.** The WARM and AMBER values are the sRGB OETF, the exact inverse of the section 9 transfer, of the LED colours the user picked on the hardware on 2026-09-25:
  - `c ≤ 0.0031308 ? 12.92·c : 1.055·c^(1/2.4) − 0.055`, with c = LED/255;
  - WARM from 132/255 and 36/255, AMBER from 58/255 and 10/255.
- **Storage.** Constants are stored as floats (≥ 6 significant digits), never as rounded 8-bit ints. Rounded ints would miss the picks by one count, and a 1.0.0-cc5.4 review caught exactly that with the earlier int table. They are never re-derived at run time.
- **[r2] PINK tuning.** While the latched tuning field `ledPink` (3.2) is set and non-zero, PINK is the OETF of that LED colour, per
  channel, computed once at acceptance (the WARM/AMBER derivation, applied at run time only for tuning), and the spark is
  mix(PINK, white, 0.3) of it. When the user has picked, the pick is frozen as float constants exactly like WARM and AMBER
  (section 14 Q2) and the tuning field stays for later retuning.
- **The design's own effect colours inside `draw()`** (RED 1,0.094,0; GREEN 0,1,0.384; BLUE; the bloom spark mix) are replaced by this table in production. The oracle tests inject the design's constants instead (section 11.1).
  - **[r2]** The BS oracle (11.2) injects BS's constants: WARM 255,190,105 (BS:496, the fixed r2 warm, CH §1), HOT = its
    mix with white, GREEN 0,255,98, AMBER 255,131,56, RED 255,0,0, PINK 255,40,90. BS's `WARM` array is also its
    **warm marker** (`isW`, BS:497): a target whose colour is that marker means role WARM, never that literal colour (as RC's
    `'255,164,84'` does, A02 §2.1).

**`sat(c)`** re-saturates app and album colours (design; `knob-model.js:499`):
1. Take `mx = max(c)` and `mn = min(c)`.
2. If `mx − mn < 30`, the result is WARM.
3. Otherwise each channel becomes `round(max(0, x − 0.75·mn) / (mx − 0.75·mn) · 255)`.

Integer inputs give integer outputs, and both ports round half away from zero. Rounding
only happens at .5 exactly; C++ `lround`, Python `math.floor(v + 0.5)` for v ≥ 0.

A frame accent of `0` means "no accent", which is WARM (the v4 sentinel). A colour is
classified as an accent only on a selection ring (section 5.2), never by value comparison.
**[r2]** The same holds for a button `color` with `lit:"on"` (5.3) and for `feedback.color` (6.4): 0 is WARM, anything else
goes through `sat()`, and a `sat()` that falls back counts as WARM. **PINK is never an accent**: the knob supplies it for
`heart` + `lit:"on"` and for `moment:"like"`; the host never sends it as a colour (VOC §2.1, §3.5).

**[r2] Accent sources** (host side, VOC §3.5): album = `dominant()` of the cover (seeded by Apple `bgColor` while loading);
playlist = `dominant()` of the first mosaic cover; Up next row = the row's album colour (Play-next rows keep their own
album); window = `dominant()` of the app icon (monochrome → 0); a no-art item = the Generated-sleeve palette accent
(CH r2.1; BS:536, :543). **[M26]** The Generated-sleeve palette entry whose accent is the warm marker `[255,190,105]`
(BS:536, the eighth entry, index 7) is sent as **0**: BS draws it WARM (`isW`, BS:1328), while `sat()` would turn it into
255,161,38.

**LED style.** `ledStyle:"white"` (`coloredLeds == false`) means warm only [D16]:
- List accents and the volume 80/90 % colours are WARM.
- GREEN, RED (Fail/Cancel), BLUE and the AMBER offline marks are kept.
- **[r2]** Up next landmarks become WARM with their levels unchanged (0.14 / 0.70 / 0.45 / 1.0 are colour-agnostic, BS:1320);
  the snap button colour (`lit:"on"` + `color`) becomes WARM 1.0, the same as `on`; the half-wash colour becomes WARM; the
  `started` colour becomes WARM, which gives the green bloom (6.4 row h). **PINK is kept** (heart and Like bloom), because
  it is semantic like GREEN (VOC-R21; A02 F22) [M25].
- The Settings labels become "Colour" and "Warm only". The stored values stay `"color"` and `"white"`.

## 3. Wire additions (frames; only to a knob with `alive`)

Every field is optional. An absent field means "no information", and it never clears a
latched value unless stated. The firmware parser (`cc_frame_parse.cpp`) and the host
validator (`device.py`) must accept and reject identically. Fixtures are shared, as in
PRESENTATION_V4.md.

The host never sends an invalid value: it strips it and logs it (non-fatal). On the
firmware, an invalid value rejects the frame, exactly like other v4 fields.

| Field | Type / range | Semantics |
|---|---|---|
| `clock` | int 0..1439 | Local minutes since midnight. **Latched** on acceptance with the knob's `millis()`. The host sends it in every `control` (enter) frame, and in any frame when ≥ 10 min have passed since it was last sent. |
| `playing` | bool | Home frames only (layouts nowPlaying/volume/idle/notice). The **confirmed** Sonos transport is PLAYING. The host omits it outside Home and when unknown. **[r2]** The new layouts `seek`, `explorer`, `upnext` are not Home family (VOC §1.1); the host also omits it while a start is pending and on the `started` frame (M16). |
| `progress` | `{"pos": int 0..86400000, "dur": int 0..86400000}` with `pos ≤ dur` | Song position in ms. **Latched** on acceptance. `dur == 0` clears it. The host sends it on track change, on a play/pause change, on a seek (its extrapolation is off by > 2 s), and every 30 s while playing. `pos` is extrapolated to the moment the frame is built. **[C2]** Also on the first Home frame with `playing:true` after a Home frame without it (12.5). |
| `feedback.skip` | int −1 or 1 | Only with `feedback.kind == "ok"`: this ok is a knob-initiated Tracks skip in that direction. It is stripped with any other kind. |
| `ledDrive` | int 1..255 | Global drive scale (section 9). **Latched**, and kept across releases until reboot. The firmware clamps it to `ledMaxBrightness`. The host sends it only when settings.json has `led_drive`. |
| `ledDither` | bool | Temporal dithering on or off (section 9). **Latched** like `ledDrive`. It exists for the hands-on A/B, and the host sends it only when settings.json has `led_dither`. **[ruling 12.7]** Unset (never sent since boot) means **off**, the default since the 2026-09-26 user ruling, with the F-T floor of 9 step 4; `true` re-enables the residual dither exactly as before (no floor); `false` is the default made explicit. |

**Latched** fields are latched on a frame *acceptance* (`frame` or `control` command,
`next_version()`), not on every HMI pass. The firmware keeps them in one small struct
guarded by the existing `lock`, with a sequence number, and the HMI task applies it to
the engine when the sequence changes. **[r2]** `reducedMotion`, `ledPink` and `ledVolFull` join that struct.

### 3.1 [r2] (new) v5 fields the engine reads

K1 (`PRESENTATION_V5.md`) owns their syntax, validation, stripping, parity fixtures (`frames_v5.json`) and the byte budget;
the names and ranges are VOC's (§3.1, §2.1, §4.1, §6.2). This section only states what the LED engine does with them.

| Field | Engine use | Section |
|---|---|---|
| `layout` `seek` / `explorer` / `upnext` | families `tracks` / `explorer` / `upnext` (never Home) | 5.4 |
| `page` | none (an explorer tab switch is no MODE) | 6.4 |
| `ring.style` `"lap"` with `index` = target seconds, `count` = duration D seconds (≥ 1) | the Seek lap pattern; `transport ↔ lap` is MODE | 5.1.6, 6.4 |
| `ring.now` int −1…count−1 (layout `upnext` only) | Up next played / now / upcoming classes on absolute indices | 5.1.4 |
| `ring.card` bool (`selection` on layout `upnext` only; K1 §4.4, VOC-K1a; `card:true` requires `count ≥ 2` and `now == count − 2`) | entry `count − 1` is the Sonos-shuffle card: no landmark, no cursor cell; its colour is ignored. `ring.unavailable` never reaches the engine on `upnext`: both parsers strip it there (K1 §4.4, P5-R24), so no Up next entry is ever unavailable | 5.1.4 |
| `activity` `"loading"` (existing token; K1 §3.1) | the **whole list** is loading: comet only (wire form `ring.style:"off"` + `activity:"loading"`, K1 §4.6). Never sent for one unloaded entry of a known list, which is a colour-0 entry with the list's own activity (5.1.3 case 1; M31) | 5.1.3, 6.1 |
| `ring.first` (always sent by v5 hosts when `count > 20`, = `clamp(index − 10, 0, count − 20)`) | the re-centred window | 5.1.1 |
| `buttons[j].lit` `"on"` / `"off"`; `buttons[j].color` int (meaningful with `lit:"on"`) | button tones | 5.3 |
| `feedback.moment` `queued`/`shuffle`/`like`/`unlike`/`snap`/`started` (only with `ok`; **[r2.2]** `unlike` is reserved and never sent, 6.4 row f); `feedback.side` −1/1 (with `snap`); `feedback.color` int (with `snap`, `started`) | moments | 6.4 |
| `reducedMotion` bool, **latched** (every `control` frame, and the next frame after the effective setting changes) | reduced motion | 6.5 |

### 3.2 [r2] (new) Latched tuning fields [M24]

Two latched fields for the hands-on tour only (00 U8, U13: "the tour tool carries runtime candidates for PINK and the body
level, so tuning fits in one window"). **VOC §6.2 defines them** (type, range, gating, settings keys, budget; VOC rule 1);
K1 carries their parsing, storage, latching, budget and fixtures (PRESENTATION_V5 §3.1, §3.6, §7.3, §14.1, §15.1).

| Field | Type / range | Semantics |
|---|---|---|
| `ledPink` | int 0..0xFFFFFF (JSON int only) | The LED colour (0xRRGGBB, at full drive) the ring should emit for PINK. The engine sets PINK = per-channel OETF(channel/255) (section 2). **0 = the built-in PINK constant** (the same meaning as `set_tuning`'s 0, section 4). **Latched** like `ledDrive`: absent keeps it, it survives releases and claims, and reboot returns to the constant. |
| `ledVolFull` | bool (JSON bool only) | `true`: the semantic (amber/red) volume body and half-step use AL's 1.00 instead of 0.62 / 0.81 (the U8(b) alternative, 5.2); `false`: this contract's levels. **Latched** like `ledDither` (same lifetime as `ledPink`). |

- **Validation** (both parsers, K1 §3.3 rules 2 and 6): an out-of-range int, a bool, a float or a string for `ledPink`, or
  a non-bool `ledVolFull`, rejects the frame on the firmware; the host strips and logs it. Scope: all layouts. Gated on
  `alive` (never sent to a knob without it).
- The host sends them only when settings.json has `led_pink` (int, or a `"#RRGGBB"` string that `device.py` converts to the
  int) or `led_vol_full` (bool), in every enter frame, like `ledDrive` (10.2). There is no UI. `tools/nanod_alive_tour.py`
  sends them directly (companion quit). After the tour, the user's pick stays in settings.json until a later build freezes
  it as float constants (section 2), so no second flash is needed inside the one window (00 U13).
- **Byte budget:** the latched reserve grows by `,"ledPink":16777215` (19 B) and `,"ledVolFull":false` (19 B) = **38 B**;
  K1's worst v5 frame (Windows, 1,314 B, PRESENTATION_V5 §14.1) becomes 1,352 B, still under `FRAME_BUDGET_BYTES_V5` 1,400.
- **Status:** PRESENTATION_V5 carries them since the 2026-09-25 consistency pass (its §3.1 rows, §3.6 storage, §7.3,
  the §14.1 reserve, the §15.1 fixture families and P5-R27), so a cc5.4 parser built from K1 latches them and the tour can
  settle PINK and U8 (13.1 X8 applied). Their presence in K1 stays a **release requirement** of this contract.

**Knob → host event (new):** `{"id": <control id>, "lim": -1|1}`.
- It's sent once per end-stop push (section 6.2) while that control is ready, at most one per 150 ms.
  **[Q1]** "Per push" means **every** push into a bound, not only the first one after arriving there: a push that
  follows the knob springing back off the bound for at least `lim_rearm_ms` (75 ms) sends another (6.2, 12.5).
- `-1` means the lower bound (position 0) and `1` the upper bound (position = max).
- Desktop v7 treats it as a touch: it summons the floating knob, and the desktop engine gets `limit(dir)`.
- **[r2]** In Seek, the bounds are 0:00 and `T_end = D − 3` (CS §4.2: `t(0) = 0:00`, `t(max) = T_end`), so `lim` is the
  design's "turning past it plays the End stop" (S01:201).

**Byte budget.** **[r2]** Owned by K1 (VOC §14): the worst case now includes the v5 fields above, `ring.now`, two button
colours, `feedback.moment/side/color`, `reducedMotion`, the ALIVE latched fields and the two tuning fields. AL's statement
(≤ 1,100 B with the ALIVE fields) is superseded by K1's budget; the tests record the size.

## 4. Engine structure (identical in C++ and Python)

The engine is platform-neutral:
- **C++:** `src/cc_alive.h/.cpp`, C++11 and float32. No Arduino/FastLED; it compiles in the firmware, MSVC `/W4 /WX` and `cpp11_gate.py`.
- **Python:** `control_center/alive_lights.py`, float64.

It has three layers, and each is tested on its own:

1. **Targets** `alive_targets(frame, local, state) → Targets`: a pure function from the frame (plus the local cursor, section 6.3) to per-segment and per-button targets, and to the flags the animator needs (section 5).
2. **Animator** `AliveAnimator.step(nowMs, targets, flags, newEffects) → e_ring[60][3], e_buttons[4][3]`:
   - damping, the effect queue, the continuous layers and composition (sections 7–8);
   - its outputs are tone-mapped design-space floats in 0..1;
   - it is a faithful port of the design's `draw()`, and is tested against the design oracle (section 11.1) **[r2]** and
     the BS oracle (section 11.2).
3. **Output** `alive_output(e, drive, dither, residuals) → uint8 RGB`: transfer curve, drive, power limit, quantisation (section 9). C++ only. The desktop draws `e` directly (section 10.3).
   **[ruling 12.7]** It also takes the F-T masks (`cc_alive_output(…, ringLit, buttonLit)`: which LEDs have a lit
   target), which `CCAlive::output()` builds from its last render's targets (`cc_alive_lit()`). Python keeps a
   test-only twin (`reference_output(…, ring_lit, button_lit)`, `lit_masks()`) for the byte checks of section 11.

**The engine** `CCAlive` / `AliveLights` owns the three layers and the event detection
(section 6). Its API, in snake_case in Python:
```
reset(now)                          // power-up: offline state (section 8.1) + reveal
claim(now)                          // unclaimed → claimed: ONLINE
release(now)                        // claimed → unclaimed: OFFLINE (drain)
detent(now, delta)                  // local position moved by delta (≠0) within one control
limit(now, dir)                     // end stop pushed (dir −1/1)
press(now, slot)                    // button down, physical slot 0..3
set_clock(now, minute)              // latched clock (0..1439)
set_progress(now, pos, dur)         // latched progress; dur 0 clears
set_reduced_motion(now, on)         // [r2] latched reducedMotion (6.5)
set_tuning(now, pink_led, vol_full) // [r2] latched ledPink (0 = none) and ledVolFull (3.2)
render(now, frame|null, local_pos, local_max) → ring e[60][3], buttons e[4][3]
asleep(), cursor(), animating()     // animating: any effect or damping residue > 1/1024 or a continuous layer active
```
- **Time** is uint32 ms. Elapsed times are `(uint32)(now − start)`, which is safe across the wrap.
- **Frame gaps.** `dt = min(50, now − lastRender)`, and it's 0 on the first render after `reset`.
- **Input order.** Input methods only *queue* inputs. `render` processes them in this fixed order, after computing the targets and the cursor:
  1. presses;
  2. the wake check;
  3. tick and bound;
  4. the frame-derived events of section 6.4, in their listed order.
- **Periodic phases** use integer modulo, `phase = (now % P) / P` [D11], never `sin(now / k)` on a large float.
- **[r2] Frame fields.** The integration fills the new frame facts (`moment`, `side`, `mcolor`, `now`, `card`, `lit`, `color`,
  the `lap` style) from the parsed frame (K1's `CCFrame.ringNow` / `ringCard`, PRESENTATION_V5 §3.6). Until K1's `CCFrame` carries them, `CCAliveFrameExtra` (FA, `cc_alive.h`) carries them
  next to `playing` and `skip`.
- **[r2] Enums** (append-only; VOC §1.2): `CCAliveFamily` 5 `explorer`, 6 `upnext`; `CCAliveEffectType` 15 `half`, 16
  `scatter` (`CC_FX_TYPES` becomes 17). Internal enums, also append-only: `CCAliveRole` 7 `PINK`; `CCAliveClass` 6 `P`,
  7 `N`, 8 `Q` (5.2).
- **[r2] Effect struct** (`CCAliveEffect`): add `int8_t side` (half: −1 left, +1 right) and `float seed` (scatter,
  0 ≤ seed < 60). `c[3]` now also carries the bloom and half colours. About 8 B more per queue slot.
- **[r2] Scatter PRNG [M5].** The engine owns one xorshift32 state `rng` (uint32), seeded in `reset()` with
  `0x2545F491`. One draw: `rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5` (uint32 arithmetic), then
  `seed = 60 · (rng >> 8) / 16777216`, evaluated in double and stored in the effect (float32 on the knob). The draw happens
  when a `shuffle` moment is processed (6.4 row d), **also when reduced motion skips the scatter**, so the sequence never
  depends on the motion setting. Twin replay compares seeds within 1e-5. `claim`/`release` do not reseed.

## 5. Targets [r2] (rewritten: the alive geometry)

**[r2]** Revision 1 ran the v4 geometry (`cc_ring_target`) and mapped its level values to classes. Revision 2 departs from
v4 in the half-step placement, the colour gate, the window, the list rules, Up next and the lap, so the targets are
**defined here directly**. An implementation may still run the v4 geometry and post-process it, as long as the result
equals these rules; the target goldens (11.3) decide.

### 5.1 Ring cells [r2] (rewritten)

A **cell** is (role, class) plus the rgb for role ACCENT; section 5.2 turns a class and role into an alpha. `put(i, …)`
**overwrites** `ring[i mod 60]` (P4 §5.1); cells are written in the order given. Segment 0 is at 12 o'clock, clockwise.

#### 5.1.1 Window, slots and accents (every `selection` ring, including Up next)

- `N = ring.count`, `I = ring.index`.
- `F = ring.first` when present. When absent (legacy senders only; v5 hosts always send it for `N > 20`, VOC-R03):
  `F = 0` if `N ≤ 20`, else `clamp(I − 9, 0, N − 20)`; `colors` and `unavailable` are kept only when that derived `F` is 0
  (P4 §4 `rules.absentFirst`, unchanged).
- `W = min(20, N)`; the transmitted entries are `j = F … F + W − 1`, with `k = j − F`.
- **[r2] [M9]** `c0 = F + ⌊(W − 1)/2⌋` and `slot(j) = ((j − c0)·3) mod 60` (non-negative). For `N ≤ 20` this equals v4's
  `c0 = (N − 1)/2`. For longer lists the window is **re-centred** on the transmitted window instead of v4's absolute slots,
  so the landmarks scroll under a cursor that stays near 12 o'clock, instead of wrapping every 20 entries (S01:166;
  CH §7 #20 and CH:114 "lists longer than 20 use the 20-entry ring window"; BS:1319, :1326; VOC-R03 and §3.4).
- `acc(j)`: WARM when `ledStyle != "color"`, when `j == moreIndex` (legacy), or when `colors[k]` is absent or 0;
  otherwise `sat(colors[k])`, which is role ACCENT, or WARM when it falls back.
- `avail(j)`: bit `k` of `ring.unavailable` is clear.

#### 5.1.2 Volume (`style:"level"`, Home family) [r2] (rewritten) [M1, M2, M13]

Let `v` be the displayed volume (the local position when applied, 6.3; else `ring.value`) and `c` = `confirmedVolume`
(default `ring.value`), both integers 0..100.
- `e = ⌊v/2⌋`: the **endpoint step** (the cursor).
- `n = (v + 1) div 2`: the lit extent (v4's `n`); `nc = (c + 1) div 2`.
- `seg(k) = (35 + k) mod 60`: the arc runs from segment 35 clockwise, 2 % per step (S01:164).
- **[r2] [M2]** `col(k, x)` = RED if `x ≥ 90 and k ≥ 45`; AMBER if `x ≥ 80 and k ≥ 40`; else WARM. Under `ledStyle:"white"`
  always WARM (D16). The value gate matches the user's "amber 80–90 %, red ≥ 90 %" and BS:1306; it differs from v4 only at
  v = 79 (endpoint WARM, not AMBER) and v = 89 (endpoint AMBER, not RED) (A02 F2; 00 C17).

Cells, in this order:
1. **Bounds:** `seg(0)` = segment 35 and `seg(50)` = segment 25: WARM, class 1.
2. **Body**, k = 0 … n: `col(k, v)`, class 2 when `k ≤ nc`, else class 1 (the span above the confirmed value while an
   increase is pending, P4 §5.2).
3. **Pending decrease**, k = n + 1 … nc: `col(k, c)`, class 1.
4. **[r2] [M13] Half-step** (v odd): k = e + 1 (= n): `col(e + 1, v)`, class **S**.
5. **Endpoint:** k = e: `col(e, v)`, class 3 (class 4 when `ring.external`).

The cursor is `seg(e)`. A cell is flagged `volRed` when its role is RED (the near-max embers, 8.2).

- **[r2] [M13]** For odd v, v4 (and AL D10) put the endpoint at `35 + n` and the shoulder one segment *behind* it. r2.1 puts
  the endpoint at `35 + ⌊v/2⌋` and "lights the **next** segment at 0.81 (a half step)" (S01:164; S02:16; BS:1305–1310;
  VOC-R04). The lit extent (k = 0 … n) and every level are unchanged; only the classes of the top two cells swap and the
  cursor moves back by one segment for odd v. Examples: v = 55 → body 35–59 and 0–1 at 0.62, endpoint 2 at 1.0, half-step
  3 at 0.81, bound 25 at 0.30; v = 99 → endpoint 24 RED 1.0, half-step 25 RED 0.81 (over the bound mark); v = 100 →
  endpoint 25 RED 1.0.
- **Home offline** (`activity:"offline"` with `level`) [D15]: **only** `seg(⌊c/2⌋)` WARM class 1; no marks. The cursor is
  that segment. **[r2]** The endpoint follows M13 (v4: `35 + (c + 1)/2`).
- **Pending** on the level ring is the span above (no pulse), plus the Working comet (6.1).

#### 5.1.3 Lists (`style:"selection"` on `recent`, `explorer`, `windows` and legacy layouts) [r2] (rewritten) [M3, M31]

1. **Loading** (`activity:"loading"`): **no cells**; the cursor is 0. Only the Working comet shows (S01:166, :300, :336;
   VOC-R06). **[r2]** v4's `put(0, W, pulseL2L1)` is not drawn.
   - **[r2] [M31] What "loading" means.** `activity:"loading"` is the design's *Loading list* / *Loading queue*: the **whole list**
     is not there yet (the first page of Recently Added, a Favourite playlists tab without a cache, the Up next queue before
     its first window lands; S01:300, :336; BS:1318, :1325 draw no ring then). K1's wire form for it is `style:"off"` +
     `activity:"loading"` (PRESENTATION_V5 §4.6, VOC-K1g; 13.1 X7 applied); a `selection` ring with `activity:"loading"`
     draws the same (no cells).
   - **An entry that is not loaded yet inside a list whose `count` is known** (a fast spin outran the prefetch,
     CONTROL_CENTER_V5 §5.2.2; an Up next placeholder row after the first window) is **not** loading. The host sends that
     entry with colour 0 and the list's own `activity` (`idle`, or `pending` while Play next runs). The ring then keeps every
     landmark; the unloaded entry is a warm landmark (0.30; class Q 0.45 in Up next's upcoming rows), the cursor on it is
     WARM class 3, and the local cursor (6.3) keeps following the knob. This is S01:165's "items with no colour: warm 0.30"
     and S01:267's "a fast spin shows loading tiles, never blank cards"; blanking the whole ring (and freezing the local
     cursor, 6.3) for one missing page would do the opposite. The knob's `Loading…` meta says it on the LCD.
2. `N == 0` (hosts send `style:"off"` for an empty list; a `selection` with `count` 0 is treated the same): no cells, cursor 0.
3. **Landmarks:** for each transmitted `j` with `avail(j)`: class 1 in `acc(j)` (0.45 coloured, 0.30 warm, 5.2).
   - **[r2]** A legacy `moreIndex` entry is **one warm landmark**; v4's second cell at `slot + 1` is not drawn
     (S01:173; CH §7 #19; A02 F5). v7 hosts never send `moreIndex` (U5, one flat list).
   - Unavailable entries leave a gap (no landmark).
4. **Cursor** at `slot(I)`:
   - available: class 3 in `acc(I)`;
   - **[r2]** unavailable (Recent/explorer unplayable item, Windows closed window): class **Q** (0.45 in any role) in
     `acc(I)`: "the cursor on it keeps the item's colour at 0.45" (S01:174; VOC-R05). v4/AL drew W at L2 (Recent) or the
     accent at L2 (Windows, which AL made 1.0 as semantic class 2);
   - **[r2]** `I == moreIndex` (legacy): WARM class 3, one cell.
5. **Pending** (`activity:"pending"`): the cursor cell's class follows `pulse` (5.1.8). **[r2]** Its colour is `acc(I)` in
   **every** list family (D13 extended from Windows; A02 F7): warm is allowed for transient moments (S01:175), but the
   cursor keeps its item's colour so no warm tick appears in a coloured list.

The cursor is `slot(I)` (0 in cases 1–2).

#### 5.1.4 Up next (`style:"selection"` on layout `upnext`) [r2] (new) [M14]

1. **Loading** (`activity:"loading"`, the queue before its first window lands): no cells, cursor 0 (the Working comet only;
   S01:166, :336). Placeholder rows after that are ordinary entries with colour 0 (5.1.3 case 1).
2. `now` = `ring.now` when present and ≥ 0, else −1 (VOC §3.1).
3. **Landmarks:** for each transmitted `j` with `avail(j)` that is not the card (item 5), in `acc(j)` (the row's album colour;
   on `upnext` `ring.unavailable` is always 0, because both parsers strip it there, K1 §4.4, P5-R24, so `avail(j)` holds
   for every entry):
   - `j < now` (played): class **P** (0.14);
   - `j == now` (now playing): class **N** (0.70);
   - `j > now` (upcoming): class **Q** (0.45 in **any** role: a warm row is also 0.45, BS:1320 has no warm test).
   The split is on **absolute** indices, so it holds anywhere in the 20-entry window (A02 F14).
4. **Cursor** at `slot(I)`: class 3 in `acc(I)`. It covers the now-playing mark when the focus is the playing row.
5. **The Sonos-shuffle card** (S01:360; the `> 60` regime): **`isCard(j)` ⇔ `ring.card == true` and `j == count − 1`**
   (K1's wire form, PRESENTATION_V5 §4.1, §4.4; VOC-K1a). K1 guarantees `now == count − 2`, so the card always follows the
   now-playing row. The card has **no landmark**, and the cursor on it draws **no cell**; the cursor position (for moments)
   is still `slot(I)`. Its `colors` slot is **ignored** (a v7 host sends 0, K1 §4.4), and an `unavailable` bit never
   arrives: both parsers strip `ring.unavailable` on `upnext` (K1 §4.4, P5-R24). The engine still ignores the bit for the
   card if a frame reaches it unparsed (twin replay, 11.4), so the result is the same whether a sender sets them or not.
   The test is on the absolute index, so it holds when the card is outside the transmitted window (6.3).
6. **Pending:** the cursor pulses as in 5.1.3 (not on the card).

**[M14]** Two departures from BS:1317–1322, both artefacts of the prototype's model: (a) the card **counts** as an entry of
the window geometry (BS computes the window over `qNow + 1` rows without it), because the knob's control has a detent on
the card (BS `qLen()` = `qNow + 2`), so detents and 3-segment slots stay 1:1 (the same choice as K1's P5-10); (b) with no
lit cursor, BS's `_cursor` falls to 0 (BS:1332), so moments would start at 12 o'clock; here they start at the card's slot.

#### 5.1.5 Tracks (`style:"transport"`, always WARM)

Unchanged from P4 §5.4:
- **Landmarks:** unless Prev is unavailable (`unavailable` bit 0): segments 52, 53 class 1; segment 0 class 1; 7, 8 class 1.
- **Selection:** index 0 → 52 and 53 class 3 (only when Prev is available), cursor **52**; index 2 → 7 and 8 class 3, cursor 8;
  index 1 → segment 0 class 2 (0.62), cursor 0.
- **Pending:** the selected cells take `pulse`.
- **[r2] [M4]** The Prev cursor stays 52. BS draws 53 because its cursor is "the last cell with a ≥ 1" (BS:1316, :1332;
  VOC-D04); it only shifts moment origins by one segment.

#### 5.1.6 Seek (`style:"lap"`, layout `seek`) [r2] (new)

The song as one lap from 12 o'clock (S01:168; BS:1311–1314). With `T = ring.index` (target seconds) and
`D = max(1, ring.count)` (duration seconds):
- head `h = min(59, ⌊T·60 / D⌋)` in integers (the integer form of BS:1312, A02 §8);
- segments `k < h` (played): WARM class 2 (0.62);
- segments `k > h` with `k mod 5 = 0` (unplayed ticks): WARM class 1 (0.30);
- other segments `k > h`: unlit;
- the head `k = h`: WARM class 3 (1.0). It is the cursor.

All warm; drawn awake like any ring (resting levels when asleep); it is not the resting Song hand. No pulse: while Sonos
lands the jump (`Jumping…`, `activity:"pending"`) only the Working comet runs (S01:202). **[r2.2]** That span is the
whole jump, until playback resumes (≈ 2.7 s, up to 8 s), and it continues without a gap across a follow-up jump sent
when the first lands; the head follows the frozen target, which a turn during the jump moves (R22 CH §3; M33). Example: T = 74, D = 300 → h = 14:
0–13 at 0.62, 14 at 1.0, 15, 20, … 55 at 0.30.

#### 5.1.7 Off

`style:"off"`: all segments dark. The cursor is 0, for moments.

#### 5.1.8 Pulses

`pulse` (pending), unchanged from P4 §5.6: 260 ms phases anchored at the onset of the pending state, starting HIGH; class 3
on even phases and class 1 on odd phases; after 3000 ms of continuous pending it holds class 1. The onset resets whenever
the pending condition starts. It runs on the list cursor (5.1.3, 5.1.4) and the Tracks pair (5.1.5) only [M28]; the level
and lap rings never pulse. **[r2]** v4's `pulseL2L1` (loading) is no longer drawn by the alive engine (5.1.3 case 1).
A 520 ms period is 1.9 Hz, inside the 3 Hz rule.

### 5.2 Alpha (`finishAlive`) [r2] (table rewritten)

Let `semantic = role ≠ WARM`, which covers GREEN/RED/AMBER/BLUE/PINK/accent. A sat() that fell
back to WARM counts as WARM.

| Class | Awake, warm | Awake, semantic | Resting (colour becomes WARM) | Used for |
|---|---|---|---|---|
| **[r2] P** | 0.14 | 0.14 | 0.05 | Up next played |
| 1 | 0.30 | 0.45 | 0.05 | landmarks, volume bounds, lap ticks, Tracks marks |
| **[r2] Q** | 0.45 | 0.45 | 0.05 | Up next upcoming; unavailable list cursor |
| 2 | 0.62 | **[r2] 0.62** (AL: 1.00) [M1] | 0.10 | volume body, Neutral selected, lap played |
| **[r2] N** | 0.70 | 0.70 | 0.10 | Up next now playing |
| S [D10] | 0.81 | **[r2] 0.81** (AL: 1.00) [M1] | 0.13 | volume half-step |
| 3 | 1.00 | 1.00 | 0.16 | cursor, endpoint, lap head, selected pair |
| 4 | 1.00 | 1.00 | 0.16 | external endpoint, flash |

- **[r2] [M1]** Amber and red body segments use 0.62 like warm, and the half-step 0.81 in every role (S01:164; S02:16;
  R:101; CH §7 #2; U8(a)). Class 2 semantic is now used only by the level ring (the unavailable list cursor moved to Q).
  With the tuning field `ledVolFull` (3.2) set, class 2 and S semantic are 1.00 (AL's values) for the hands-on A/B.
- **[r2]** The resting column equals BS's thresholds (`≥ 0.99 → 0.16`, `≥ 0.5 → 0.10`, else 0.05; BS:609) for every class
  but S, which keeps AL D10's 0.13 (BS would give 0.10; VOC §3.3). The golden tags it [D10].

"Resting" means `effectiveAsleep` (section 6.1). The animator multiplies resting targets by
the breath and by the time-of-day brightness (section 8).

Overrides, applied in this order after the table:
- **External** (awake, Home family, `ring.external`): segments cursor−1..cursor+1 become BLUE, alpha 1.
- **Flash** (the v4 feedback flash window: ok 650 ms, err 900 ms): segments cursor−2..cursor+2 become GREEN (ok) or RED (err). Alpha is 1 for |k| ≤ 1 and 0.5 for |k| = 2. A flash forces awake (6.1).
  - **[r2] [M7]** There is **no flash** for a feedback that carries a `moment` (6.4 rows c–h): r2.1 draws no flash with any of
    its moments, and a green flash would put green into a coloured list (A02 F13; VOC-R08). `err`, `skip`, the D7 wash and
    the plain `ok` bloom keep it.
- **Offline** (unclaimed, section 8.1): replaces everything with AMBER at segments 0, 5, … 55, alpha 0.12. There's no reconnecting pulse [D5].

### 5.3 Buttons (physical slots, left to right = frame `buttons` order) [r2] (rewritten) [M18]

The tone is derived on the knob; the host never sends a tone (VOC §2.3). First match wins:

| # | Condition (button `b` in slot `j`) | Tone | LED role · awake alpha | Source |
|---|---|---|---|---|
| 1 | `b.icon == ""` | none | off | P4 §5.9 |
| 2 | `!b.enabled` | dim | WARM · 0.14 | S01:101 |
| 3 | `j == 0` and `b.icon == "cancel"` (legacy v6 hosts only) | stop | RED · 1.0 | P4 §5.9; AL §5.3 |
| 4 | **[r2]** `b.lit == "on"` and `b.icon == "heart"` | **[r2.2] `liked`** (was on + PINK) | **[r2.2] PINK · 0.30** (was 1.0), never `sat()`; not the 0.14 `dim` level, so the button still says "liked" rather than "broken" | S01:106; BS:1262, :1293; **R22 CH §1**; R22 BS:1268 (`c: PINK, a: 0.3`); M32 |
| 5 | **[r2]** `b.lit == "on"` and `b.color ≠ 0` | on + colour | ACCENT `sat(b.color)` · 1.0 (WARM · 1.0 on fallback or warm-only) | S01:107; BS:1282, :1293; VOC-D02 |
| 6 | **[r2]** `b.lit == "on"` | on | WARM · **1.0** | S01:102; BS:1291 |
| 7 | **[r2]** `b.lit == "off"` | off | WARM · **0.30** | S01:103; BS:1291 |
| 8 | `j == 3` and `b.icon ∈ {play, prev, next, switch}` | go | GREEN · 1.0 | S01:104; P4 §5.9 |
| 9 | Home family, `j == 0`, `b.icon == "play"` (enabled: row 2 already took disabled) | go + **paused Play** | GREEN · 1.0 × the paused-Play breath (8.2), awake only; `pausedPlay = true` | S01:105; S02:17; CH §7 #1; U1 [M8] |
| 10 | otherwise | nav | WARM · 0.70 | S01:100 |

- **[r2] [M18] Resting:** every lit button becomes WARM, alpha **0.12 when its awake alpha ≥ 0.5, else 0.04** (BS:620).
  So `off` (0.30) rests at 0.04, where AL's "0.04 if dim, else 0.12" gave 0.12 (A02 F16). **[r2.2]** `liked` (PINK
  0.30) rests at WARM **0.04** by the same rule.
- **[r2.2]** A liked row's heart is always `enabled` (the host refuses the press, VOC §2.6 `unlike_unavailable`), so row 2
  never takes it; if a frame ever sends `heart` + `lit:"on"` with `enabled:false`, row 2 wins as for every button.
- **Offline:** every button is off.
- **[r2]** Where the tones come from (the per-mode map is VOC §2.4): explorer tabs (`clock`/`playlists` on/off), Shuffle
  on/off, Seek lit, the liked heart (**[r2.2]** tone `liked`, PINK 0.30), and an assigned snap side (`snapleft`/`snapright` with `lit:"on"` + raw app colour).
  An unassigned snap button is `nav` 0.70, not `off` (BS:1282; A02 §4.7). Windows Button 1 is a warm `back` (nav), never
  `cancel` (CH §7 #3); `stop` survives only for v6 hosts.
- **[r2] [M8]** Paused Play is **green** (U1). r2.1 now renders it green too (BS:1247; CH §7 #1): "Button 4 is green when
  available; the one exception is Home Button 1 while paused" (R:74–75). The user confirms it on the ring (CH "Still open";
  11.9).
- **Transients** (effects, not tones, section 7): press = that button +0.6·(1−u)² HOT; the wash tints Button 4 at
  0.55·fade·amp; **[r2]** the half-wash tints Button 2 (left) or 3 (right) at 0.6·fade, without `amp`.

### 5.4 Flags handed to the animator
- `effectiveAsleep`, `offline`, `pending` (6.1);
- `family` **[r2]** (home / recent / **explorer** / tracks / **upnext** / windows): `nowPlaying`, `volume`, `idle`,
  `notice` → home; `recent` → recent; `explorer` → explorer; `tracks` and `seek` → tracks; `upnext` → upnext; `windows` →
  windows (VOC §1.1). Every layout is mapped explicitly; nothing defaults to Home (A04 §10 risk 9);
- **[r2]** `style` (the ring style, for the `transport ↔ lap` MODE, 6.4);
- `cursor`;
- `volRed[60]`, and `heat` (Home family, awake, level ring, displayed volume ≥ 90);
- `pausedPlay`;
- `tint`: the cursor's accent (after sat) when the family is **[r2]** recent / explorer / upnext / windows (BS:634; S01
  "Ambient tint"; A02 F15; 00 C18), the cursor target is lit and its role is ACCENT [R2], and it's awake; else none;
- `songHand` (8.4);
- `todB` (section 8.3);
- **[r2]** `reducedMotion` (6.5);
- WARM, HOT **[r2]** and PINK, as parameters, so the oracle can inject the design's.

## 6. Events

### 6.1 Sleep, wake, pending
- **Inputs** are `detent`, `limit`, `press`, and the external rising edge (6.4).
  - An input sets `stateAsleep = false`.
  - It sets `sleepAt = now + 5000`, or `now + 3200` for external.
  - `claim` counts as an input.
- **Falling asleep.** On `render`, if `!stateAsleep` and `now ≥ sleepAt`:
  - if `pending || holdActive`, then `sleepAt = now + 1000`;
  - else `stateAsleep = true`.
- `effectiveAsleep = stateAsleep && !pending && !holdActive && claimed`.
- **[r2] [M22] `holdActive`** replaces AL's `flashActive`: the flash window (ok 650 ms, err 900 ms) **or** a moment hold.
  A feedback moment (6.4 rows c–h) starts a hold for its effect's nominal duration (sweep 640, scatter 700, bloom 900,
  half 900, wash 1100; `unlike` none, and **[r2.2]** `unlike` is retired anyway), so the knob never drops to rest in the middle of a confirmation that no longer
  carries a flash (M7). The hold applies even when reduced motion skips the effect.
- **Wake effect.** When `effectiveAsleep` goes true → false, start `wake` at the cursor (design: `detect()` line 204).
- **[r2] Wake wording** (S02:18; CH §7 #14; 00 G6): the Wake **moment** is 520 ms; each segment rises with τ = 10 ms
  (awake target ≥ 0.9, the cursor) or 55 ms (others), buttons with 40 ms (8.2), so the body reaches 95 % in about 165 ms.
  The old "~360 ms wake" is withdrawn; acceptance is "matches the oracle" (11.1). The first detent or press both wakes and
  acts: the controller acts on it, and the same render plays `wake` and the tick or press.
- **Pending** is either of:
  - frame activity is `pending` or `loading`;
  - Home family with a level ring whose displayed value (local if applied, else `ringValue`) ≠ `confirmedVolume`.

  (R1: not with activity `offline`.) **[r2]** In v7 this covers `Starting…` (Home, pending), `Queueing… k of n`,
  `Jumping…` (Seek), `Switching…`, `Loading…` and `Loading queue…` (loading) (VOC §5 "Working").

  **[r2.2] [M33] The pending condition must include seek-in-flight and play-next-in-flight** (R22 CH §3, §4):
  - **Seek:** from the first `Seek` sent until the **last** jump lands (landed = playback resumed, the transport out of
    `TRANSITIONING`; ≈ 2.7 s, up to `seek_confirm_ms` 8000), including the gap before a follow-up jump that a turn made
    during the jump queued (at most one; it waits for the 250 ms debounce). The comet never stops between two jumps.
  - **Play next:** the whole job, from the press through the Apple lookup (`Finding songs…`) and every insert
    (`Queueing… {k} of {n}`, ≈ 0.5 s per song) to the result.
  - The engine needs no new input: both reach it as frame `activity:"pending"`, which K3 sends for exactly these spans
    (K3 §5.2.4, §5.5.6, C5-68, C5-69). Holding sleep off (`pending` above) follows. The tour checks the comet on a
    5 s jump and on an uncached Play next (11.9).

### 6.2 Local input (firmware HMI task; desktop from `p` / `kd` / `lim` messages)

**`detent(now, delta)`**
- **When it fires:** the FOC position of the *same* control id changed between two HMI passes while claimed and ready. A change caused by a new control id (a host re-enter) is never a detent.
- **Velocity** (design line 206):
  - `dtR = max(16, now − lastRot)`;
  - `vel = dtR > 400 ? 0 : 0.55·vel + 0.45·(1000·|delta|/dtR)`.
- **Tick:** at the new cursor.
  - `dir = sign(cd(newCursor, oldCursor))`, or `sign(delta)` if the cursor didn't move.
  - `len = round(clamp((vel − 4)/14)·7)`.

**`limit(now, dir)`**
- **[Q1]** It fires on **every push into a bound** while claimed and ready (12.5), not only on the rising edge of
  `foc_thread.pass_at_limit()` (revision 1): `pushing = atLimit && attractor ≠ last attractor` (read-only FOC accessor),
  rising from false after it has been false for at least `lim_rearm_ms` (75 ms, tuned in the turning test), and at
  least `lim_gap_ms` (150 ms) after the previous fire, so the ring's `bound` and the wire `lim` stay one-to-one.
  - `dir = +1` when the position is at max, −1 when at 0.
  - Read only; the haptic code is not changed.
- It starts `bound` at the cursor with the cursor target's colour (WARM → WARM) and `dir`.
- It does not tick [D4].
- **[r2]** Every list, Up next, Windows and the explorer bound at their ends this way (BS:918–943); in Seek the bounds are
  0:00 and `T_end` (3.2). In Seek, where most detents don't move the lap head, a detent that moves the position still ticks
  (at the unmoved head, `dir = sign(delta)`), and never bounds (D4; A02 §4.5).

**`press(now, slot)`**
- It fires on a button-down event while claimed.
- It starts `press` on that slot.
- **[r2]** A press on a dimmed button still plays `press`; the host answers with `feedback{kind:"err"}` (the Head shake) or
  ignores it, per VOC §2.6. The 600 ms hold (`kh`) plays nothing of its own: the press already played, and going Home is a
  family change (Reveal).

### 6.3 Local cursor [D14] [r2] (table extended)
While claimed, and the FOC's control id equals the frame's id with the control ready, the
local position replaces the frame's value/index **for the LEDs only**:

| Ring | Condition | Replacement |
|---|---|---|
| Level | `local_max == 100` and layout ≠ notice and activity ≠ offline | displayed value = local position (cursor `35 + ⌊v/2⌋`, M13) |
| Selection (**[r2]** incl. `explorer`, `upnext`) | `local_max == ringCount − 1` and activity ∉ {pending, loading} | `ringIndex` = local position; **[r2]** the window re-centres (below) |
| Transport | `local_max == 2` and activity ≠ pending | `ringIndex` = local position |
| **[r2] Lap** | never [M11] | — |

For the selection ring:
- **[r2] [M15] Re-centring (replaces AL's "v4 defensive rule").** Let `L` be the local index. For `N ≤ 20` nothing else
  changes (`F = 0`). For `N > 20`: `F' = clamp(L − 10, 0, N − 20)`, `c0' = F' + 9`, and the slots use `c0'`. Entries
  `j ∈ [F', F' + 20)` are drawn with the frame's colour, mask and `now` when `j` is inside the transmitted window
  `[F, F + 20)`; entries outside it are **unlit** until the next host frame carries them (one serial round trip, about
  20–40 ms, A04 §7). The cursor is `slot'(L)` in `acc(L)` with its 5.1.3 / 5.1.4 class when `L` is transmitted, else WARM
  class 3 (a transient mark while the host is more than 10 entries behind). When `isCard(L)` (5.1.4 item 5: `ring.card` and
  `L == count − 1`) the cursor draws no cell, transmitted or not. Without this rule, the cursor would jump three
  segments per detent and snap back when the host's re-centred frame arrives.
- **[r2]** `activity:"loading"` disables the local cursor only because a loading list has no entries to walk (5.1.3 case 1);
  an unloaded entry inside a known list keeps the list's own activity, so the local cursor keeps running over it.
- `confirmedVolume` is always the frame's.
- The host's frames stay authoritative for everything else.

**[r2] [M11] No local cursor on the lap.** The Seek detent map `t(n) = clamp(p + 5·(n − n0), 0, T_end)` depends on the
entry position `p` and on `T_end`, which only the host holds (CS §4.2); a knob copy would need `p`, `n0` and `D` on the
wire (A04 §7 "not recommended for this release"). The lap head and the `m:ss` follow host frames, one round trip per detent.

### 6.4 Frame-derived events (in `render`, compared with the previous rendered frame) [r2] (rewritten)
The engine remembers from the last rendered claimed frame:
- family;
- **[r2]** ring style;
- cursor;
- the selected entry's accent (the colour before any pending override, 0 if WARM or none; **[r2]** 0 on the Up next card);
- `external`, `playing` (present or absent), and the feedback seq.

After `claim`, the first frame only seeds these, without events (like the v4 renderer reset).

1. **MODE:** start `reveal` when the family changed, **[r2]** or when the family stayed `tracks` and the ring style changed
   between `transport` and `lap` (Seek enter and exit, including the 3 s idle exit; BS:836, :848; A02 F19). This covers
   every overlay open and close (families `explorer`, `upnext`, `windows`) and every return Home (BS:698). An explorer tab
   switch (`page` 0 ↔ 1) is **not** MODE: the landmarks just damp to the new list (BS:1035–1039; A02 §4.3).
2. **Feedback:** a new valid seq (the v4 rules). **[r2]** Evaluated in this order; the first matching row plays
   (VOC §4.2; A02 §9 §6.4):

   | Row | Feedback | Effect | Flash | Hold |
   |---|---|---|---|---|
   | a | `err` | `fail` at the new cursor (stationary under reduced motion, 6.5) | err | flash |
   | b | `ok` + `skip ±1` | `sweep` at the **previous** cursor, `dir = skip` **[r2] [M21]** | ok | flash |
   | c | **[r2]** `ok` + `moment:"queued"` | `sweep` with `at = 0`, `dir = +1`: one clockwise lap from 12 o'clock (S01:185, :215; BS:1021) | none | 640 |
   | d | **[r2]** `ok` + `moment:"shuffle"` | draw a seed (section 4), then `scatter` with it (S01:189, :359; BS:879); for Shuffle on **and** off | none | 700 |
   | e | **[r2]** `ok` + `moment:"like"` | `bloom` in **PINK** at the new cursor (S01:188, :344; BS:829) | none | 900 |
   | f | **[r2]** `ok` + `moment:"unlike"` — **[r2.2] retired**: no host sends it (Like is add-only, R22 CH §1); the row stays only as the guard for the reserved token, which must never fall through to rows i/j (a wash or green bloom) | nothing (BS:829 blooms only when liking) | none | — |
   | g | **[r2]** `ok` + `moment:"snap"` | `half` with `side = feedback.side` and colour `sat(feedback.color)` (0, a fallback or warm-only → WARM) (S01:187; BS:1088) | none | 900 |
   | h | **[r2]** `ok` + `moment:"started"` | `sat(feedback.color)` is an ACCENT (and `ledStyle:"color"`): `wash` in it at the **new** cursor (the Home endpoint); else `bloom` in GREEN at the new cursor (S01:186, :227; BS:998, :888; VOC-R07) [M16] | none | 1100 / 900 |
   | i | `ok`, previous family ∈ {recent, **[r2]** explorer, upnext, windows}, previous selected accent non-WARM | `wash` with that accent at the previous cursor [D7] | ok | flash |
   | j | any other `ok` | `bloom` in GREEN at the new cursor | ok | flash |

   - `moment` and `skip` never come together (K1 strips a `moment` next to `skip`); if a legacy frame had both, row b wins.
   - **[r2] [M6]** These moments start on the host's feedback, never on the press: the knob cannot know success, and a
     false confirmation cannot be undone (VOC-D03). BS plays them on the press (BS:829, :879, :1021, :1088); K3 decides
     when each `ok` is sent (acceptance or verified completion).
   - **[r2] [M10]** A Windows Switch to a warm (monochrome) app green-blooms (row j), where BS washes in warm (BS:1095):
     green confirms a Switch (S02:79: confirm green is for "Play / Switch buttons, success"; 00 §3.2 "LED"; A02 F11).
   - **[r2]** A silent success sends no feedback (Seek landing, volume confirmation, Play/Pause): the Working comet just
     stops when `activity` clears (VOC §4.2).
3. **PLAY/PAUSE:** both frames are Home family and carry `playing`, and the value changed. Start `fill` (true) or `drain` (false), with `n = (displayedVolume + 1) / 2` in integer arithmetic [D8].
   - **[r2] [M16]** Skipped in a render whose feedback row was h (`started`): the wash must not be cut by `fill` (both are
     foreground). The host rule of R4 is extended the same way (10.2): no `playing` while a start is pending, nor on the
     `started` frame.
4. **EXT:** both frames are Home family, and `ring.external` went false → true.
   - Start `shimmer` from the previous cursor to the new cursor.
   - Count it as an input with a 3200 ms sleep.
5. **Claim and release:**
   - `claim` queues `boot`. Its `home` flag is the family of the first frame rendered after the claim.
   - `release` starts `down`, snapshotting the current damped state (8.2).

**[r2] Where the design's moments come from in v7** (for the tour and the goldens; VOC §5): Play next done → row c;
Shuffle on/off → row d; Like → row e; ~~Unlike → row f~~ (**[r2.2]** no unlike: a press on a liked row is refused, → row a); Snap → row g; Recent/explorer/Up next Play (hybrid: the knob is
already Home with `Starting…`, 00 U11) → row h, or row a on `Album unavailable` / `Didn't start`; Windows Switch → row i
(accent) or j (warm app); Tracks Skip → row b; every failure or blocked press → row a.

### 6.5 [r2] (new) Reduced motion [M17]

S01 §10 makes the knob's LEDs follow reduced motion: "Wake, Spin trail, Sweep, Scatter and Reveal are skipped. The Head
shake becomes a stationary red throb. Colour meaning is kept: Wash, Half-wash, Bloom, Fill/Drain and the Working comet stay"
(S01:439–442). The knob cannot read the PC setting, so it follows the latched frame field `reducedMotion` (VOC-R09);
the desktop engine takes the companion's effective setting directly (10.3).

While `reducedMotion` is true:
- `play()` **drops** `wake`, `tick`, `sweep`, `scatter` and `reveal` before anything else: they are not queued and kill
  nothing (BS:579).
- `fail` is drawn with `pos = at` (BS:658): stationary, same alpha, same base dim.
- Everything else is kept: `boot`, `down`, `bound`, `bloom` (green and pink), `fill`, `drain`, `shimmer`, `wash`, `half`,
  `press`, the flash, and every continuous layer (Working comet, breaths, embers, tint, song hand, paused-Play breath).
  `boot` and `down` are not named by S01 §10 and BS has neither; they mark connect and disconnect once each, so they stay.
- The damping still rises on wake; only the travelling front is skipped.

## 7. Effects (design `draw()` switch, lines 318–360; DUR at line 112) [r2] (extended)
- **Durations (ms):** boot 2800, down 1800, wake 520, tick 180, bound 460, bloom 900, fail 700, sweep 640, fill 760, drain 860, shimmer 1000, wash 1100, reveal 450, press 220; **[r2] half 900, scatter 700** (BS:483).
- **Foreground (FG):** boot, down, bloom, fail, sweep, fill, drain, shimmer, wash, **[r2] half, scatter** (BS:484 plus AL's
  boot and shimmer).
- **Starting an effect** (`play`):
  - **[r2]** Under reduced motion the skipped types are dropped first (6.5).
  - An FG effect sets `kill = now` on every running FG effect that doesn't have one yet.
  - wake, reveal and bound replace any running effect of the same type.
  - tick and press accumulate.
- **Queue:** at most **8** [D12]. When full, drop, in order:
  1. the oldest killed effect;
  2. else the oldest tick;
  3. else the oldest press;
  4. else the oldest effect.
- **Lifetime:**
  - An effect ends when `u = ms/dur > 1`.
  - A killed effect fades with `amp = 1 − (now − kill)/120` and ends at `amp ≤ 0`.
- **Duck:** `duck = max(duck, 0.35·sin(π·u)·amp)` for FG effects other than boot and down (**[r2]** so also half and scatter).

Every recipe is ported **verbatim** from `draw()`, including its constants, `amp` usage and
helpers (the ones used inline without `A`/`AG` stay unattenuated where the design does so):
- `add(i, c, a)` ignores `a ≤ 0.001`;
- `addG(pos, w, c, a)` spans `floor(pos − 3w)..ceil(pos + 3w)`;
- `comet(head, dir, len, c0, c1, a)`: gaussian w 0.7, alpha `a·(1 − k/(len+1))^1.7`.

Other helpers:
- `md(i) = ((round(i) % 60) + 60) % 60`. `round` is JS `Math.round`: half toward +∞.
- `cd(i, j) = ((((i − j) % 60) + 90) % 60) − 30`, using the JS remainder (the sign follows the dividend).
- `eo`, `eio`, `gs`, `bump`, `cl` exactly as lines 99–105.

**Exception:** boot's LCD fade is omitted [D6].

For the `down` recipe, the `snap`/`bsnap` taken at `release` are `cur·a` per channel (design
line 231). `at` is the last claimed cursor. **[r2] [M19]** `down` stays RC's recipe (RC:334–344: 10 ms per segment, the
cursor ember with its +0.35 warm bump, the button snapshot), which is exactly S02 §7 "Going offline". BS:659 is a
simplified variant (16 ms per segment, no ember, no button snapshot); the specification text wins over it.

**[r2] New and changed recipes, verbatim from BS `draw()`** (A = add·amp, AG = addG·amp, as in the design):

- **`bloom`** (BS:656; RC:349 with the colour made a parameter): `c` = the effect colour (default GREEN), `d = eo(u/0.8)·30`;
  for every i with `x = |cd(i, at)|`: `A(i, c, 0.9·(1 − 0.5u)·gs(x − d, 1.5))`, and if `x < d`,
  `A(i, c, 0.16·(1 − u)^1.5)`; then `AG(at + 30, 1, mix(c, white, 0.3), 0.8·bump(ms, 560, 900))`. The Like bloom is
  `c = PINK`, spark 1, 0.409804, 0.547059.
- **`half`** (BS:655; S01:187 "left half 31–59, right half 1–29"): `c` = the effect colour;
  `fade = ms < 380 ? 1 : 1 − eo((ms − 380)/520)`. For k = 1 … 29: `i = side < 0 ? 60 − k : k`; the segment is lit when
  **`20·|k − 15| ≤ min(ms, 300) + 10`** [M23], then `A(i, c, 0.75·fade)`. Finally `addB(side < 0 ? 1 : 2, c, 0.6·fade)`
  **without `amp`** (A02 F18: a killed half keeps its button tint until it is dropped at kill + 120 ms).
  - The growth test is BS's `|k − 15| ≤ d/2 + 0.5` with `d = cl(ms/300)·30`, rewritten in integers. It is identical at
    every integer ms, and it removes the float ties at `ms = 20j − 10`, where float32 and float64 could disagree by a
    whole segment at 0.75 (both happen to light it today; the integer form makes that exact). Segment 15 (or 45) lights at
    0 ms, distance j at `20j − 10` ms, and the half is full at 270 ms. Segments 0 and 30 never light.
  - Fade samples: 0.4552 at 500 ms, 0.1920 at 600, 0.0569 at 700, 0.0071 at 800, 0 at 900 (A02 §6.1). The half has no
    base dim of its own; only the FG duck applies.
- **`scatter`** (BS:657; S01:194; S02:24; CH §7 #21) [M5]: `ORD = [0, 4, 8, 3, 7, 2, 6, 1, 5]`; for k = 0 … 8:
  `p = fmod(seed + (ORD[k]·60)/9, 60)`, `st = 55·k`, `AG(p, 0.8, HOT, 0.8·bump(ms, st, st + 260))`. The sparks are 6.67
  segments apart, each lands 1–4 positions round the ring from the one before, and they never cluster, so no seed is
  rejected (VOC-R18 supersedes A02 §6.3's `1 + 9u` and its rejection). The last spark ends at 700 ms.
- **`fail`** (BS:658; RC:350): `pos = reducedMotion ? at : at + 1.6·sin(2π·3.2·ms/1000)·(1 − eo(u))`;
  `AG(pos, 0.9, RED, 0.95·(1 − u²))`; for k = −3 … 3: `m[md(at + k)] *= 1 − 0.6·sin(πu)`. `reducedMotion` is read at draw
  time.
- **`sweep`** (RC:351 = BS:653), unchanged math: `comet(at + dir·60·eo(u), dir, 10, HOT, WARM, 0.85·(1 − u³)·amp)`. New
  trigger: row c (`at = 0`, `dir = +1`).
- `wake`, `tick`, `bound`, `reveal`, `press`, `fill`, `drain`, `wash` are identical in BS and RC (A02 §5); AL's RC ports stand.
  BS:648's `e.c || WM` fallback for `bound` is a prototype artefact (A02 F24): a warm cursor bounds in WARM.

## 8. Continuous layers and composition (design `draw()` lines 267–316 and 364–395)

### 8.1 Offline state
- **When:** unclaimed after `reset` or `release`. The targets are the section 5.2 offline override, the buttons are off, and the breath is `0.60 + 0.40·sin(2π·phase(2600))`.
- **Native handover** [user]. Firmware only; the desktop simply hides.
  - While unclaimed, any native input switches the LEDs to the **existing native path** unchanged: `halvesPointer`, `nativeKeyLeds`, and FastLED brightness = profile brightness, including `global_sleep_flag` behaviour. Native input means an FOC position change or a button state change.
  - **[r2] [M29]** The handover **lasts until the next claim**: the native path keeps the LEDs however long the knob then
    rests, and the amber marks do not come back. AL's "after 5000 ms with no native input, the engine owns the LEDs again:
    it starts `reveal` and shows the offline marks" is **withdrawn**.
  - A claim from either state runs `claim`.
- **At power-up** the engine starts in the offline state, with a `reveal`.
- **[r2]** This is r2.1's "PC not connected" exactly: drain, then 12 amber marks at 0.12 breathing on 2.6 s; input hands the
  lights to the knob's own profile; "the companion's lights resume **on reconnect** with the Coming online moment" (S02:20;
  S01:170; R:104). BS keeps `native` true until the PC state changes (BS:909, :916, :949) and draws its `NATIVE` pointer
  (BS:1303, the prototype's stand-in for the native profile lights) for as long.
  - **Why M29.** (1) r2.1 has no return to the marks (S02:20; BS above). (2) The user's decision reads "offline drain →
    amber marks → native profile lights on native input", with no return; AL D5 tagged the 5 s return [user], but the
    recorded decision (2026-09-25) does not contain it. (3) K1's offline LCD, once native input has happened, shows `Knob controls still work` **until the
    next claim** (PRESENTATION_V5 §8.10, following BS:1414's `s.native`), so a return of the "waiting" marks after 5 s would
    have the ring say "waiting for the PC" while the screen says "native control". (4) The native path already has its
    own idle behaviour (`global_sleep_flag`), exactly as on cc5.3.
  - Under reduced motion the power-up `reveal` is dropped (6.5), and the marks just damp in.
  - The LED half and the LCD half still differ in one case (PRESENTATION_V5 OQ-3, P5-11; VOC-R23): after an
    **intentional** release (a tray quit), the ring shows the marks while the LCD keeps the native screen, until the first
    native input hands the ring over too. **OQ-3 is settled jointly by K1 and K2 for cc5.4:** the LEDs follow the user's
    decision after every release (drain, marks, native lights on native input, until the next claim), and the LCD keeps
    K1's lost-host-only trigger, because the firmware cannot tell a quit from a configuration release. The difference lasts
    only until the first native input. A later release may add `{"release":true,"offline":true}` if the user wants
    `Waiting for PC` after a quit.

### 8.2 Damping (design lines 274–296; `asleep` = `effectiveAsleep`)

| Where | τ rising | τ falling |
|---|---|---|
| Ring, asleep | 400 ms | 700 ms |
| Ring, awake, target ≥ 0.9 | 10 ms | 140 ms |
| Ring, awake, other target | 55 ms | 140 ms |
| Buttons, asleep | 400 ms | 700 ms |
| Buttons, awake | 40 ms | 160 ms |

- **Ring:** `ta = targetAlpha · breath · restK`, where `restK = asleep ? todB : 1`.
  - The breath: `1 + 0.4·sin(2π·phase(5200))` when asleep, the offline breath when offline, else 1.
  - Then `a += (ta − a)(1 − e^(−dt/τ))`.
  - **Colour**, only when the target is lit: `k = 1 − e^(−dt/(a < 0.02 ? 1 : 70))`, using the *updated* `a`.
- **Heat:** when `heat` and `volRed[i]`, `ta *= 0.72 + 0.28·(0.5 + 0.5·sin(2π·phase(P_i) + 1.9·i))`, with `P_i = round(2π·(380 + (i·97 mod 260)))` ms [D11].
- **Buttons:** `ta = a·restK`, then
  - `× breath` when asleep;
  - `× (0.55 + 0.45·(0.5 + 0.5·cos(2π·phase(2600))))` for slot 0 when `pausedPlay`, awake and Home family;
  - colour `k = 1 − e^(−dt/70)` when lit.
  - **[r2]** `a` is the 5.3 target alpha, which is already the M18 resting value (0.12 / 0.04) when asleep.

### 8.3 Time of day [user]
- Take the latched clock plus the elapsed time: `h = ((minute + (now − at)/60000) mod 1440)/60`.
- `todB` interpolates linearly over the keyframes (hour, factor): (0, 0.55), (5, 0.60), (8, 0.95), (13, 1.00), (17, 1.00), (20, 0.85), (22.5, 0.65), (24, 0.55).
- There's no half-hour rounding [D18].
- Without a latched clock, `todB = 1`.
- WARM never changes with the hour [user]. **[r2]** r2.1 agrees: "Warm is fixed all day; time of day only dims resting
  brightness" (R:98; S02:12; CH §1); BS's `warmAt()` returns the fixed warm with only the factor varying (BS:472–473).

### 8.4 Layers drawn before the effects (overlay `O`, in this order)
1. **Working comet** (while `pending`): `comet(60·phase(1400), +1, 8, HOT, WARM, 0.5)`, with no fade in or out.
   **[r2]** It is the only thing a loading list or queue shows (5.1.3, 5.1.4); it also runs during `Starting…`,
   `Queueing…` and `Jumping…` (BS:1333). **[r2.2]** And during `Finding songs…`; for Seek and Play next it runs for
   their whole span (6.1, M33; R22 BS:1339 `_working`).
2. **Ambient tint:** `tint += (tt − tint)(1 − e^(−dt/220))`, where `tt` is the tint colour or 0. Every segment whose target is unlit gets `+ tint·0.06`. **[r2]** Families recent, explorer, upnext and windows (5.4; BS:634–637).
3. **Song hand:**
   - Shown when `effectiveAsleep`, the family is Home, the last Home frame had `playing == true`, and progress is latched with `dur > 0`.
   - `prog = clamp((pos + (now − at))/dur, 0, 1)` while playing. Progress freezes when a Home frame says `playing:false`.
   - Drawn as `addG(prog·60, 0.75, HOT, 0.26·todB)`.

### 8.5 Compose (design lines 370–395)
- **Ring:** `k = a·m[i]·(1 − duck)`, then `e = tone(rgb·k + O[i])`.
- **Buttons:** `k = a·bm[j]` (no duck), then `e = tone(rgb·k + OB[j])`.
- **Tone map:** if `mx = max(e) > 0.78`, scale by `(0.78 + 0.22·(1 − e^(−(mx − 0.78)/0.22)))/mx`.

The desktop draws `e`, and the knob sends `e` through section 9.

### 8.6 [r2] (new) The 3 Hz rule [M12]
"Nothing modulates brightness above 3 Hz" (R:106; S02:19; CH §7 #15). Checked per layer: resting breath 0.19 Hz, offline
and paused-Play breaths 0.38 Hz, embers 2.4–4.0 s periods, the pending pulse 1.9 Hz, the Working comet one pass per
1.4 s per segment, half-wash monotone, scatter one 260 ms bump per spark position. The **Head shake** moves a red
gaussian ±1.6 segments at 3.2 Hz: it is **spatial motion and exempt** (S02:19; 00 G7, "D30"), and the tour checks it
doesn't read as flashing (11.9). Moments that answer the user's own input (tick, bound, press) follow the input rate, as
the design's do.

## 9. Output (knob)
1. **Transfer curve** [D3]: the sRGB EOTF per channel, `L = e ≤ 0.04045 ? e/12.92 : ((e + 0.055)/1.055)^2.4`, with `e` clamped to 0..1. It may be implemented as a LUT that matches within 1e-4.
2. **Drive:** `v = L·drive`.
   - The default drive is 150, or `ledMaxBrightness` if that is lower.
   - The latched `ledDrive` replaces it, still clamped to `ledMaxBrightness`.
3. **Power limit** [D17]:
   - `S = Σ(r + g + b)` over the 60 ring LEDs plus the 8 button LEDs (2 per slot).
   - `B = 68·(255 + 132 + 36)·150/255 = 16920` exactly, the warmth test's proven load.
   - If `S > B`, every `v` is scaled by `B/S`.
4. **Quantise** **[ruling 12.7]** (rewritten 2026-09-26; revision 2 had dither on by default):
   - **Dither off** (the default: `ledDither` unset or `false`; firmware `CCAliveSpec::defaultDither`): `q = clamp(floor(v + 0.5), 0, 255)`, and the residuals are zeroed.
   - **F-T floor** (dither off only, after step 3): an LED whose design **target is lit** — its section 5 ring cell
     or button slot has a class and an alpha > 0 (`cc_alive_lit(targets())`; Python `lit_masks()`) — whose plain
     rounding is dark on every channel while `m = max(v_r, v_g, v_b) > 0` shows **one count on its dominant
     channel**: `q_c = 1` where `v_c = m` (a tie lights every tied channel), the rest 0. That is the byte plain
     rounding shows just above `m = 0.5`, so a mark breathing through half a count passes through the floor without
     a jump: no channel is lit under the floor that is dark just above it (**[ruling 12.7, amended 2026-09-26]**; the
     first reading, `floor(v_c / m + 0.5)`, also lit a channel ≥ `m/2` and did jump, 12.7). Every other LED
     keeps plain rounding: an LED whose target is unlit (effect tails, halos, gaussian skirts, a segment fading after
     its target went dark) is never floored, and `m = 0` stays dark. The floor adds at most one count per channel
     (≤ 68 × 3 = 204 counts against B = 16920) and leaves every already-visible byte unchanged, so the WARM #FF8424 /
     AMBER #FF3A0A picks and the twin tolerance (11.4) hold. A floored amber or warm mark therefore shows one count
     of red (#010000): one count cannot mix amber, and red is its dominant channel and the hue it has when bright.
   - **Dither on** (only with a latched `ledDither:true`, the A/B): per LED channel, `v' = v + res`, `q = clamp(floor(v' + 0.5), 0, 255)`, `res = v' − q`. The residuals persist across frames. No floor.
   - Why: at the resting and offline levels (0–3 counts) the dither toggled most LEDs by one count every frame on
     the hardware (binary A, 2026-09-26): a flicker. With dither off, plain rounding darkens the dimmest designed marks
     (the 0.11–0.5-count ones); the floor keeps them visible, on their dominant channel, and continuous with plain
     rounding through the breath. Numbers: 12.7.
5. **Write** the raw `q` to `leds`/`ledsp` through `cc_ring_address(i, orientation)` and `kKeyLedPairs`. Set `FastLED.setBrightness(255)`.
   - A led_wire test proves the wire bytes equal `q` at brightness 255. FastLED 3.6's `scale8` must be identity at 255, or the implementation compensates.
   - The existing `min(51, led_max_brightness)` cap is gone in the alive path. The drive and the power limit replace it.

**[r2]** Nothing in this section changes. PINK tuning changes the palette (section 2), not the output. The brightest new
state (a half-wash over a full awake body) stays under the limiter like any other. The optional 120 Hz output-only
dither pass (RF0 §2.7) is **not** in this release; it is adopted only if the `ledDither` A/B shows twinkle at the resting
levels, and then never above ~133 Hz (RF0 §2.7).
**[ruling 12.7]** The hardware showed that twinkle with the per-frame dither (binary A, 2026-09-26); the user ruled
dither off by default with the F-T floor (step 4) instead, and the 120 Hz pass stays out of this release.

## 10. Integration

### 10.1 Firmware (HMI task)
- `updateLeds()` runs the engine when unclaimed-offline or claimed. When the native handover is active, it runs the existing native path unchanged.
- **Cadence:** **[r2]** (RF0 §2.7 R1; the LEDs measured 49 fps with the old `previous = now` gate, RF0:616)
  - Render and show on a **deadline**: `nextShowDue += 16, 17, 17` repeating (exactly 60.0 fps), with `dt` from the real
    `millis()`. If `now` is more than one period past `nextShowDue`, resynchronise (`nextShowDue = now`) instead of
    catching up.
  - The loop delay becomes `clamp(nextShowDue − now, 1, 10)` ms.
  - Everything else in the loop (buttons, HID, MIDI, settings, watchdog, crumbs) is unchanged and still runs every pass.
- **Inputs:**
  - Claim/release come from the existing `cc_lights_active` transition.
  - Detents come from `foc_thread.pass_cur_pos()` for the same control id. The implementer finds the FOC/input control-id binding already used for `p` events (`AngleEvt.control_id` / `cc_input_id()`).
  - Limits come from the **[Q1]** push detector over read-only FOC accessors (`pass_at_limit()` plus the attractor
    test of 12.5), and presses from the claimed button handler (`kEventPressed`).
  - **[F1/W2]** The local-input sampler (`CCAliveKnob`) resets on every claim, every release and every pass without a
    ready control; its first sample after a reset only seeds (12.5).
  - Latched fields are applied from the struct of section 3 (**[r2]** including `reducedMotion`, `ledPink`, `ledVolFull`).
    **[ruling 12.7]** An unset `ledDither` is `CCAliveSpec::defaultDither` (false): the HMI calls
    `alive.output(drive, ledDitherPresent ? ledDither : CCAliveSpec::defaultDither, …)`, and `CCFrame.ledDither` /
    `CCAliveLatch.ledDither` default to false (an absent field stores false; `alive_tests.py` pins all four).
  - The `lim` event goes to the COM task through a small lock-guarded slot, which COM sends as a JSON line with the id.
  - **[r2]** The `kh` hold and the F24 icon gate are WP4's (VOC §2.5); the engine is not involved.
- **Memory:** all engine state is static (no heap, and nothing large on the HMI stack). The HMI stack high-water mark must stay > 1 KB (diag). **[r2]** Revision 2 adds about 70 B per engine (effect `side`/`seed` × 8, the PRNG, the tuning and motion latches).
- **Diag (additive):**
  - `ledFps`: frames shown in the last full second;
  - `ledRenderUsMax`: the maximum µs for engine + output since the last diag read, reset on read;
  - `ledRenderUsAvg`;
  - `ledMode`: `"alive"`, `"offline"` or `"native"` (**[r2]** `"native"` now lasts until the next claim, M29);
  - **[r2]** `ledShowGapMsMax`: the longest interval between two `FastLED.show()` calls since the last diag read, in ms,
    reset on read; `ledLateShows`: the count of such intervals > 20 ms since boot (RF3 §8.1 assigns both to the HMI task;
    they are what decides whether R7 is ever needed, 11.9).
- **The hmiConfig double-free fix** already in `hmi_thread.cpp/.h` ships in this release.
- **Not touched by this contract:** haptic force/profile code, `.pio/libdeps`, FOC control logic (read-only accessors only), the media/artwork code, and the lease semantics. **[r2]** AL also listed "LCD rendering"; this combined release does change the LCD, under K1 (00 G11; A04 §8). `hmi_thread.cpp` has one owner, WP4 (00 §4.2).

### 10.2 Host (desktop v7)
- `presentation.py`: `ALIVE_CAPABILITY`, and the field ranges of section 3. **[r2]** Plus the moment tokens, `side`,
  the `lap` style, `now`, `lit`, the tuning ranges (K1 names them).
- `device.py`:
  - capability gating;
  - validation and strip, with parity fixtures;
  - the `lim` message becomes a `limit` event;
  - a v4 frame with the new fields must fit the byte budget. **[r2]** K1's budget.
  - **[r2]** For a `presentation ≥ 5` knob it stops stripping `buttons[j].color` (DV:362–363; A04 §5.1).
- `sonos.py`: `_state` adds `"duration": track.get("duration", "")` (same soco call, read-only).
- **Frame content** (`controller.py`):
  - `playing` on Home frames (confirmed state only);
  - `feedback.skip` on a Tracks skip success.
  - **[r2]** `ring.style:"lap"` in Seek, with `index` = the displayed target `t(n)` in whole seconds (clamped to `T_end`)
    and `count` = D in whole seconds (CS §4.2);
  - **[r2]** `ring.now` on the Up next mirror; the Sonos-shuffle card as K1 encodes it: `ring.card:true`, the card as entry
    `count − 1` with colour 0 and no `unavailable` bit (PRESENTATION_V5 §4.4; 5.1.4);
  - **[r2] [M31]** `activity:"loading"` only while a whole list is loading (with `style:"off"`); an unloaded entry of a known
    list goes out with colour 0 and the list's own activity (5.1.3 case 1);
  - **[r2]** `buttons[j].lit` / `.color` per VOC §2.4, with raw `dominant()` colours for assigned snap sides;
  - **[r2]** `feedback.moment` (+ `side`, `color`) per K3's confirmation policy; `color` on `started` is the started item's
    accent (VOC §3.5), 0 when warm;
  - **[r2] [M16]** `playing` is **omitted** on every Home frame while a start is pending (`Starting…`) and on the frame
    that carries `moment:"started"`, so the first confirmed `playing:true` can never cut the wash with `fill` (R4
    extended; the knob also guards, 6.4 #3);
  - **[r2] [M26]** accents: 0 for monochrome apps and for the Generated-sleeve entry whose accent is the warm marker.
- **Latched fields** are **not** frame content. `device.py` adds `clock`, `progress`, `ledDrive` and `ledDither` at send time, in `_enter`/`_frame`, with a knob that has `alive`.
  - `clock`: in every control (enter) frame, and in the next frame once ≥ 10 min have passed since it was last sent.
  - `progress`: once, in the next frame after `runtime.py` posts a progress update (the section 3 triggers). It is parsed from Sonos `position`/`duration` `H:MM:SS` and extrapolated from the poll time while PLAYING.
    **[C2]** `SongProgress.home()` also posts on the first Home frame with `playing:true` after a Home frame without it (12.5).
  - `ledDrive`/`ledDither`: only from settings.json `led_drive`/`led_dither`, with no UI. They go in every enter frame when set.
    **[W1]** Settings passes them through raw; they are validated when applied (`runtime.led_tuning()`, then
    `device.set_led_tuning()`): an invalid value is ignored and logged by key name only, never by value (12.5).
  - **[r2]** `reducedMotion` (VOC-R09): the effective motion setting (Settings `motion` = `"system"` → Windows *Animation
    effects*, `SPI_GETCLIENTAREAANIMATION`; `"full"`; `"reduced"`), in every enter frame and in the next frame after it
    changes.
  - **[r2]** `ledPink` / `ledVolFull`: only from settings.json `led_pink` / `led_vol_full`, in every enter frame when set (3.2).

  So controller frames, and the enter-frame / first-poll-frame equality rules of the Stage 8 tests, are unchanged. A heartbeat re-send never repeats a `progress` it already sent.
- **Settings:** the LED labels become "Colour" / "Warm only" (section 2).

### 10.3 Desktop floating knob [user: same choreography] [r2] (rewritten) [M20, M27, M30]

User decision: the floating knob mirrors the ring with the same choreography, at the display refresh (240 Hz on the
Samsung Odyssey G93SC, 5120 × 1440, 100 % scaling). S02:21–23: "Its glow uses six fixed looks keyed by level, as
pre-rendered sprites that are only faded and tinted, never reshaped per frame."

1. **Engine and inputs** (RF0 §2.4 step 0 and AR-9).
   - When the connected knob has `alive`, the floating knob and the simulator use `AliveLights`, **on the overlay thread**
     (`NanoD-overlay`). The Tk thread only posts the decorated frames (the same ones sent to the knob) and LCD scenes.
   - The serial reader posts `position` deltas (as `detent`), `limit` events and `button` downs (as `press`) straight to
     the overlay mailbox, each stamped with its serial-read time in ms; the engine applies each at that time, never at the
     25 ms Tk tick's (AR-9: otherwise a 240 fps ring shows a ~30 Hz staircase).
   - The device `position` is the local position (6.3); clock and progress come straight from the runtime; `reducedMotion`
     is the companion's effective motion setting (not the frame field); `ledPink` / `ledVolFull` come from settings.json.
   - Otherwise (no `alive`) the floating knob keeps `PreviewLights`, unchanged.
   - **Ownership.** This section owns what the engine computes and how a segment looks (colours, the six looks, their radii,
     alpha and scale, item 3). DESKTOP_STAGE (K4) owns the thread, the loop, pacing, the sprite cache's construction and
     composition, and the frame-rate gate (§5, §6.3, §11); K4 §11.3 should cite item 3 here rather than restate it.
2. **Cadence** (VOC §7.1 `knob`: "composed every vblank (240 Hz) while visible").
   - While the overlay state is not `hidden`: the engine renders **once per vblank**, sampled at the **predicted display
     time** of that frame (DESKTOP_STAGE §5.1 P2, P12; RF0 §3 rule 2), passed as integer ms. The face is composed and
     presented whenever its **quantised** content changed (per segment: the 8-bit fill, the glow look index and the 8-bit
     glow tint `round(e/mx·255)`); an unchanged face is skipped (RF0 AR-22). While the engine is `animating()` or a
     continuous layer runs (breaths, embers, comet, tint settling, song hand), that is most frames.
   - Pacing, the compositor-clock wait and the 240 ↔ 120 rate lock are DESKTOP_STAGE §5.1 P3–P5 (RF0 §3 rules 2–3, AR-10).
     The engine is time-based, so a skipped vblank resumes on the curve with no catch-up burst (`dt` is clamped at 50 ms).
   - **[M27]** While hidden and connected: no loop and no timer. The engine renders **once per posted frame or input**
     (no compose, no present), with `now` = that message's QPC stamp in uint32 ms (the serial-read time for inputs, the post
     time for frames, P12), so feedback events and frame-derived events (6.4: MODE, PLAY/PAUSE, EXT) are consumed when they
     arrive, exactly when the physical ring plays them. A moment the ring has already finished therefore never replays when
     the knob slides in; one still running is shown at its current point, which is the mirror the user asked for. Without
     it, 6.4 would only compare frames at the first render after the slide-in and replay a wash, bloom or shake seconds
     late. The overlay thread otherwise blocks in `GetMessageW` (FK §4).
   - **[M27] Catch-up.** Because `dt` is clamped at 50 ms (section 4), one render after a long gap would leave the damped
     base (levels, colours, tint) behind the physical ring's. So, before a hidden render, and before the first render after
     the overlay leaves `hidden`, the overlay calls `render` at `last + 50, last + 100, …` up to the new `now` with the
     **previous** frame and no new input (the new frame and inputs are handed over only for the final render at `now`), at
     most **60** steps: a gap longer than 3000 ms first renders once at `now − 3000` (one clamped step) and then steps.
     This needs no engine change (the same `render` calls), keeps every effect exact (they are functions of `now`), and
     leaves at most e^(−3000/700) ≈ 1.4 % of an unfinished asleep fade. Cost ≤ 60 × 0.17 ≈ 10 ms per message, on the
     overlay thread and outside any frame path.
   - This per-message work is the only work allowed under RF0's and DESKTOP_STAGE §6.3's "0 while hidden" (0.06–0.17 ms
     per render, RF0 §2.4). AL:425's "It never animates while hidden" still holds: nothing loops, composes or presents.
   - AL's "up to 60 fps" and "redraw only on change" are withdrawn (00 G1, G11).
3. **Look** (the design's styling, BS:663–694; RC:374–395 with r2's six looks). For each ring segment, with `e` the
   engine's tone-mapped design-space colour and `mx = max(e)`:
   - **Body fill:** `round(36 + e·219)` per channel (unlit = #242424).
   - **Glow** when `mx > 0.01`: look index `g` = the nearest of `GLL = [0.14, 0.30, 0.45, 0.62, 0.81, 1.0]` to `mx`
     (ties go to the lower look, BS:480's strict `<`); tint `round(e/mx·255)`; **alpha `GLL[g]·0.95`**; blur
     `GLB[g]` of `[6, 8, 10, 12, 15, 18]` BS px (BS:479–481; S02:22; R:105; CH §3), a canvas `shadowBlur`, i.e. a Gaussian
     with **σ = `GLB[g]`/2** (HTML canvas shadow rule).
   - **Scale (one mapping for both contracts):** BS px → physical px by **`s = (outer ring diameter in physical px) / 318`**
     (BS's ring: segment ends at radius 152 + 7 = 159, BS:671, :679, drawn at `devicePixelRatio` 1, BS:663). With KnobFace's 360
     logical px ring (FK §2) at 100 %: `s = 360/318 = 1.1321`, so the six blur radii are **6.79, 9.06, 11.32, 13.58, 16.98
     and 20.38 px** and the six σ are **3.40, 4.53, 5.66, 6.79, 8.49 and 10.19 px**. In general
     `σ_g = GLB[g]/2 × 360/318 × DPI/96`.
     - **Why /318 and not /286.** S02:22 gives the radii "at 1× floating-knob size". The only drawing of the six looks in
       r2.1 is BS `draw()` (BS:677), on a ring 318 px across at 1×; Knob Face's ring (286 design px, FK §2) draws a
       different, four-level glow (`2 + 3·l` px, `Knob Face.dc.html:129`), so Knob Face px are not the unit the six radii
       were authored in. Scaling by ring diameter keeps each glow in the proportion to the ring that the design shows,
       which is what "mirrors the ring" preserves. Reading them as Knob Face px (`S = 360/286 × DPI/96 = 1.2587`) would make
       every glow 11.2 % wider relative to the ring (7.55 … 22.66 px). DESKTOP_STAGE §11.3 uses this mapping (`S_glow`,
       1.1321) for the glows and keeps 1.2587 only for the segment, plate and disc masks (13.1 X1 applied).
   - **Pre-rendered** [M20]: for each of the 60 segment positions, six glow masks (360 in all) with their look's alpha
     already applied, built once per physical size and again on a DPI change, never on a frame. Where and when they are
     built (DESKTOP_STAGE §11.3: on the overlay thread while hidden, ≤ 100 ms) is K4's. A frame only tints (a solid colour
     composited through the cached mask) and pastes; **nothing is blurred per frame** (RF0 AR-7). The glows sit behind
     the bodies and are clipped by the disc (FK §2).
   - **[r2] [M30] Buttons: not drawn.** The floating knob shows the ring only (section 14 Q1, closed): FK §2 "No button
     strip" (the user's v5 decision), DESKTOP_STAGE §11.1, and R:105 / S02:21 say the floating knob mirrors the physical
     **ring**. BS's knob canvas (BS:683–694) and Knob Face (`Knob Face.dc.html:19–23`) draw four button strips; that look
     (strip fill `round(38 + e·217)`, glow alpha `GLL[g]` without 0.95, blur `GLB[g] + 2`, offset y +3 BS px) is recorded
     here only for a later release.
   - AL's continuous glow `(5 + 13·mx)·k` with alpha `min(1, 0.95·mx)` is withdrawn: at 240 Hz it has no cache that fits
     (RF0 AR-7), and r2 replaced it with the six looks (CH §3).
4. **Geometry** is KnobFace's (FK §2; K4 owns it and its amendments). This contract fixes the colours and glows only.
5. **Budget and gate:** **one gate, owned by K4 as the FrameStats owner**: DESKTOP_STAGE §6.3, rows "Knob ring (K)" and
   "Knob slide (K)", its latency rule (serial read → first displayed frame showing it) and its stress column, measured by
   tour K (§6.4) and the H1/H5 headless gates (§6.6). This contract sets no second number. This draft's earlier
   "compose ≤ 2.5 ms p95; frame interval p95 ≤ 4.6 ms / p99 ≤ 8.4 ms over changed frames" is withdrawn in favour of that
   row (changed-frame lateness is K4 §6.1's method for the ring). K4's P6 and §11.4 now state the same knob budget as its
   §6.3 row, **≤ 2.5 ms p95 at 100 %** (RF0 §4.2's knob row, the stricter of RF0 rule 6's general 2.5 ms median / 3.0 ms
   p95) (13.1 X4 applied). Expected per-frame work: about 1.5 ms after RF0 §2.4's C2 ("expected" until the supervised
   check, RF0 AR-3).
6. **Summon:** a `limit` event summons the floating knob like any other knob touch.
7. **Mirror promise:** the floating knob draws the engine's design-space `e`, the same `e` the knob sends through section 9;
   the ring's LED brightness differs by the transfer curve and the drive, by design.
8. **The LCD mirror** is not this contract's (K1/K4). AL's "keep `render_lcd` byte-identical" is withdrawn (00 G11).
9. **Suppression** (K4; VOC §7.2): the knob hides while the explorer (`explorer`), Up next (`upnext`) or the picker
   (`carousel`) is open, so those moments show on the physical ring only.

## 11. Verification (all required before the hardware window)

**[r2]** Items renumbered: 2 (BS oracle) and 5 (floating knob) are new; AL's items 2–7 are now 3, 4, 6, 7, 8 and 9.
The gate names follow 00 §4.4: items 1–4 are gate A2, 7 is A3, 8 is A5–A7, 5 is S1 (tour K) plus headless tests, 9 is H.

1. **Design oracle** (`tests/js/alive_oracle.cjs`):
   - It runs the design's logic class from `Ring Choreography v2.dc.html` and `knob-model.js` unmodified, in a node `vm` with stubs, except for one mechanical source patch that captures `e` in the two compose loops.
   - It emits `tests/fixtures/alive_oracle.json`: scripted cases of (targets in the design's format, flags, effect pushes with params, integer dt steps) and the resulting `e`.
   - The C++ animator (via `harness/alive_tests.cpp`) and the Python animator must match every value within **2e-3**. They take the design's WARM/HOT and `todB = warmAt(h).b` as inputs.
   - Coverage:
     - every effect at ≥ 8 times, each with a kill case;
     - damping up and down in every τ branch, including the colour snap;
     - breath (rest and offline);
     - heat, tint, song hand, Working comet;
     - the queue at capacity;
     - duck, and the tone map above the knee.
   - **[r2]** Unchanged; it still covers `down`, `boot`, `shimmer` and the RC bloom (GREEN).
   - **[ruling 12.7]** Every step also carries `expect.bytes`: section 9 of that step's rounded `e` at drive 150 with
     dither off and the F-T floor on the LEDs whose persistent-view entry is non-null with `a > 0` (`referenceOutput()`,
     float64, the same text in both oracle scripts; the header's `output` names the settings). The script's self-check
     requires bytes on every step and a floor that changes only dark target-lit LEDs, to at most one count per
     channel. The Python `reference_output` reproduces every byte exactly (and every floored byte is one count on the
     dominant channel of the step's `e`); the knob's `cc_alive_output` (float32) matches within 1, and where the
     oracle floored a lit LED more than 1e-3 count below the 0.5 threshold the knob floors it too, with one count on
     the dominant channel and 0 on every channel whose `v/m` is more than 1e-3 below 1 (`alive_tests.cpp`
     `oracleBytes`). Regenerating both fixtures for this (and again for the 12.7 amendment, which changed only the
     bytes of floored LEDs and the header's `output`, now with `floorChannels: "dominant"`) left every `e`, view and
     effect byte-identical.
2. **[r2] (new) BS oracle** (A2 gate; 00 §2.3 item 11; A02 §9 §11) — `tests/js/alive_oracle_bs.cjs` →
   `tests/fixtures/alive_oracle_bs.json`:
   - It runs the BS logic class's `play()` (BS:578–586) and `draw()` (BS:597–695) **unmodified** in a node `vm`, with stubs:
     a 2D canvas context that records nothing (`roundRect`, `fillRect`, `arc`, …), `React`, `DCLogic`,
     `requestAnimationFrame`, `window.devicePixelRatio = 1`, and a fixed `Date` (hour h, so `todB = warmAt(h).b`).
   - One mechanical patch captures `e` in the two compose loops (BS:673–681 and 683–694). Nothing else changes.
   - Inputs per case: `_ring` / `_btns` / `_cursor` (targets with BS's own constant arrays, so `r.c === RED` and `isW`
     work), `_working`, `asleep`, the state fields `mode` (`home`/`recent`/`explore`/`tracks`/`queue`/`windows`), `vol`,
     `playing`, `rm`, `sim.pc`, `native`, effect pushes via `play(type, params)` with explicit `at`, `dir`, `c`, `side`,
     `seed`, and integer dt steps.
   - The C++ and Python animators match every value within **2e-3**, with BS's palette injected (section 2) and
     `todB = warmAt(h).b`.
   - Coverage: `half` left and right (ms 0, 10, 30, 270, 290, 300, the fade 380–900, killed while growing and while fading,
     the button tint without `amp`); `bloom` GREEN and PINK with their sparks; `scatter` at seeds 0.37, 13.21, 29.9, 47.53 and
     59.99 (none puts `p ± 2.4` within 1e-4 of an integer), and killed; `sweep` at 0 with `dir` +1; `fail` with `rm`
     false and true; the tint in modes `explore` and `queue` (families explorer, upnext); ring resting for 0.14, 0.45,
     0.62, 0.70, 1.0; button resting for 0.14, 0.30, 0.70, 1.0; the paused-Play breath; the offline breath (`sim.pc =
     'off'`); the queue at capacity with half and scatter; `wash` (BS copy) for parity.
   - **Not** tested against BS, and tagged in the harness: `down` (M19), `boot` / `pending` / `shimmer` (not in BS), BS's
     button colour damping while unlit (BS:624–625), the `bound` colour fallback (BS:648), the S resting level (D10).
   - **[ruling 12.7]** `expect.bytes` on every step, checked as in 11.1.
3. **Target golden** (`tests/js/alive_golden.cjs` + `tests/tools/knob_adapter.py`):
   - It uses the design's own `view(st, {led:'alive'})` for `scenarios()` and `stress()`, mapped to v4 frames, and compares against `alive_targets`.
   - The comparison is exact on class and role, and within 1e-6 on alpha, after the palette remap: design WARM '255,164,84' → WARM, AG → GREEN, AR/'255,55,35' → RED, AAMB/'255,150,30' → AMBER, ABLUE → BLUE, and sat(x) → sat(x).
   - Every mismatch must be a listed deviation, tagged in the test. **[r2]** New tags: M1 (semantic class 2 / S), M2 (the
     value gate), M3, M9, M13 (the half-step), M18.
   - **[r2] (new) BS golden** `tests/js/alive_golden_bs.cjs` (+ `knob_adapter.py` mapping BS states to v5 frames):
     `renderVals()` (BS:1118–1333) gives `_ring`, `_btns`, `_cursor`; compared with `alive_targets` on the mapped frames,
     exact on class and role, alpha within 1e-6, after the BS remap: `[255,190,105]` → WARM, `[0,255,98]` → GREEN,
     `[255,131,56]` → AMBER, `[255,0,0]` → RED, `[255,40,90]` on a button → PINK, any other colour x → `sat(x)`.
     Cases: Home v ∈ {0, 1, 2, 54, 55, 79, 80, 81, 85, 89, 90, 95, 98, 99, 100}; Recent (24 items) at rIdx ∈ {0, 9, 10,
     12, 23}; the explorer's Recently Added tab (24 items, mixed art) and Favourite playlists (6, the real 2, empty, loading
     list); Tracks tPos −1, 0, +1; Seek at pos 0, 74 and D − 3 for two durations; Up next fresh (12 rows, qNow 4, qSel 0,
     4, 11), after Play next (> 20 rows, qSel near both ends), shuffled, `longshuffle` with qSel on the card (mapped to
     `ring.card:true`, `count = qNow + 2`, `now = qNow`, no `unavailable` bit, as K1 §4.4 encodes it), and loading;
     Windows with no side, the left side, and both; PC not connected; the button tones of every mode (liked heart, pair
     on/off, snap colours, paused Play, `Starting…` dim, Seek lit, Skip dim in Seek). **[r2.2]** The liked heart is
     compared against the **r2.2** BS (`renderVals()` footer `{c: PINK, a: 0.3}`, R22 BS:1268): PINK class at 0.30,
     resting WARM 0.04 (M32); r2.1's PINK 1.0 is no longer the expected value.
     Tags: M4 (53 → 52), M14 (card geometry and cursor), D10, VOC-D02 (snap `sat()`), and the states BS doesn't model
     (the pending span, external, pulses), which are compared against this document only.
4. **Twin replay** (`tests/tools/make_alive_sequences.py` → `harness/alive_sequences.json`):
   - Engine-level sequences (frames, local position, detents, limits, presses, clock, progress, claim, release, reset, times) through both ports.
   - `e` must match within 2e-3, and C++ output bytes within ±1 with dither off.
   - **[ruling 12.7]** Dither off is the default, so the recorded bytes include the F-T floor, with the engine's mask
     (`lit_masks()`, recorded as `lit`). The C++ runner compares its own `cc_alive_lit(targets())` with `lit` exactly;
     a lit LED is visible in both ports or in neither; and on every LED Python floored (its largest channel more than
     0.05 count below 0.5, which covers the 2e-3 `e` tolerance) both ports show one count on the dominant channel
     with every channel ≤ 1, and 0 on every channel more than 0.05 count below the dominant one (`sequenceFloor`).
   - Coverage: every event of section 6, the native-handover state machine, and the local-cursor rules.
   - **[r2]** Added: every moment (queued; shuffle on and off with the PRNG sequence, seeds within 1e-5; like; unlike; snap
     left/right with colour 0 and non-zero; started with colour 0, warm and an accent) (**[r2.2]** `unlike` stays only as
     the guard case: a reserved `unlike` plays nothing, no flash, no wash; plus the `liked` button at PINK 0.30 → 0.04
     at rest, and a Seek frame sequence that keeps `activity:"pending"` across two jumps with no comet gap, M33), row order and the flash rule,
     MODE on `transport ↔ lap` and its absence on a tab switch, families into and out of explorer and upnext, reduced
     motion on and off (the skip list, the stationary fail, the PRNG draw while skipped), the M15 re-centring (N = 96,
     spins past both window edges), the M16 PLAY/PAUSE guard, the M22 moment hold against sleep, and `set_tuning`.
   - **[r2] The Up next card** (5.1.4 item 5): `upnext`, `count` 6, `now` 4, `card:true` (the card is entry 5), `first` 0,
     `colors` [a, b, c, d, e, 0]: focus on the card gives no cursor cell and no landmark at slot(5), and an `err` there
     plays the Head shake at slot(5); a local-cursor spin 3 → 5 → 3 across it; the same frames fed to the engine unparsed
     with the card's `unavailable` bit set, and with a non-zero card colour, give identical `e` (through the parsers the
     bit is stripped anyway, K1 P5-R24, whose `frames_v5.json` case covers it); a long card list (`count` 31, `now` 29, the
     last host frame at index 20 with `first` 10) with the local cursor spun to the untransmitted card (L = 30, `F'` = 11)
     draws no cell there.
   - **[r2] Loading vs an unloaded entry** (5.1.3 case 1): a `recent` list of 96 with `activity:"loading"` (no cells, comet,
     local cursor off) against the same list with `activity:"idle"` and entries 40–47 at colour 0 (warm landmarks, WARM
     class 3 cursor on entry 42, local cursor on).
   - **[r2] Native handover [M29]:** release → drain → marks; one native input → native path; then 60 s without input
     stays native (no reveal, no marks); a claim from there plays `boot`.
   - **[Q1] End stop per push** (the `CCAliveKnob` sampler with a scripted `pushing` input): push, spring back for
     100 ms, push again → two `bound` and two `lim`; held against the bound for 2 s → one; the attractor chattering at
     20 ms for 300 ms during one push → one; a second push 60 ms after springing back (under `lim_rearm_ms`) → none;
     a new control id, a release or a pass without a ready control in between → the next sample only seeds.
5. **[r2] (new) Floating knob** (`tests/test_alive_lights.py`, `tests/test_cc_knob_face.py`):
   - Frame-rate independence (RF0:410): one input script sampled at 60, 120, 144, 240 and 360 Hz (integer-ms timestamps)
     gives `e` within 0.01 at the common instants, and skipping 1–3 vblanks resumes on the curve with no burst.
   - The look: `GLL` nearest-look ties, alpha `GLL[g]·0.95`, σ = `GLB[g]`/2 × ring diameter/318 (at 360 px: 3.40, 4.53,
     5.66, 6.79, 8.49, 10.19 px), fill `36 + e·219`; no button strips are drawn (M30); after warm-up the glow cache never
     misses and nothing is blurred per frame.
   - Tour K (DESKTOP_STAGE §6.4; RF0 tour K: 10 summon cycles, a 5 s spin at 20 detents/s, a volume sweep into amber and
     red, fill and drain, 5 s of breathing; supervised, with the user's go-ahead) against **DESKTOP_STAGE §6.3's gate**
     (10.3 item 5); this contract adds no threshold of its own.
   - **While hidden [M27]:** no frame loop and no timer run, and the engine renders exactly once per posted frame or input
     plus its catch-up steps (≤ 60), with no compose and no present (a test with a fake backend counts renders, composes
     and presents). A `like` feedback posted while hidden, then a slide-in 2 s later, shows no bloom (the bloom ended at
     900 ms); a `started` wash posted 300 ms before the slide-in shows at u ≈ 0.27; in both, and after a 10 s hidden spell
     across the fall asleep, the first visible `e` equals a twin rendered continuously at 60 Hz, within 0.02. DESKTOP_STAGE
     §6.6 runs it as headless gate H9 (13.1 X3 applied).
   - **[erratum R-i] A summon.** When a message itself summons the knob (a detent or press whose input makes it visible,
     a Tk frame posted in the same tick as its touch, or a feedback frame posted during the arm wait), the first visible
     frame equals the **M27 reference** exactly (M27's own procedure run outside the overlay: each message rendered once
     at its own stamp after its catch-up steps, then the catch-up to the first visible frame's time and one render
     there), and the comparison with the twin rendered continuously at 60 Hz (within 0.02) applies from **+300 ms** of
     visible frames. Messages posted before the summon (the `like`, `started` and 10 s cases above) keep the first-frame
     comparison. Why: M27's catch-up steps are 50 ms, so a render at a message's stamp damps over up to 50 ms where the
     twin damps over one 16.7 ms tick. Measured at a summon's first frame: 0.268 for a detent that wakes the ring, 0.112
     for a press; then 0.0065 at +200 ms and 0.0011 at +300 ms (0.001 / 0.002 in the tests), the lead the frame-rate
     tests already let settle for 300 ms after an event. `tests/test_cc_knob_face.py` `FloatingKnobAliveTests`
     (`reference`, `summoned`) checks both, and both fail with the stale pre-WP10-1 schedule (12.6 E-i).
6. **Output unit tests (C++):**
   - transfer-curve points;
   - power limit;
   - the long-run mean of the dither equals `v` within 0.02 for constant inputs;
   - residual bounds;
   - wire bytes at brightness 255 (led_wire).
   - **[ruling 12.7]** `defaultDither` is false; the F-T floor (`alive_tests.cpp` `floorChecks`, Python
     `OutputFloorTests`): v = (0.498, 0.238, 0.208) → #010000, (0, 0.314, 0.124) → #000100, a dim AMBER
     (0.3, 0.154, 0.066) → #010000 (its dominant red, not #010100), ties light every tied channel (a red / blue tie
     → #010001, a near-tie only the dominant one), an unlit tail stays 0, `m = 0` stays 0, a visible LED (and one
     just above 0.5) keeps plain rounding, the floored byte equals plain rounding of the same colour at `m = 0.5`,
     the floor applies after the power limit, no masks give the plain output, and with dither on the masks change
     no byte; `cc_alive_lit` of a target set; the engine's offline marks are floored at the dim point of the breath
     and never dark after the reveal. **Continuity** (the 12.7 amendment; `alive_tests.cpp` `floorContinuity`,
     Python `test_the_floor_is_continuous_through_the_breath`): the engine frame by frame (16/17/17 ms) offline and
     asleep on Home at 00:00 and 23:00 — no floored byte has more counts than the plain byte next to it in time, and
     no channel moves against its value (every `v_c` rising while some `q_c` falls, or the reverse); the first
     reading, `round(v/m)`, fails both. led_wire: the engine's default path (dither off, floor included) reaches the
     wire unchanged. `parse_tests`: an absent `ledDither` stores false.
7. **Parser parity:** new fixtures for every section 3 field, valid and invalid, in both parsers. Byte budget.
   **[r2]** In K1's `frames_v5.json`, including `reducedMotion`, `ledPink` and `ledVolFull` (PRESENTATION_V5 §15.1; 13.1 X8 applied).
8. **Existing gates:**
   - the Python suite;
   - `light_tests` (the v4 model is unchanged for the non-alive path);
   - `parse_tests`, `media_tests`, `jpeg_tests`, `led_wire_tests`;
   - `cpp11_gate.py`, which includes `cc_alive.cpp`;
   - the PlatformIO build-only compile, with the size recorded and < 0x140000;
   - the frozen desktop `--smoke-test`.

   The v4 `PreviewLights` and `cc_lights` stay, for pre-alive firmware and the host mirror.
9. **Hardware** (only after the user's go-ahead; **[r2]** one window at the end, 00 U13):
   - The app-only flash procedure of cc5.3, with its backup, verify and rollback.
   - `check_nanod_cc5.py` generalised to cc5.4, which adds:
     - the `alive` capability;
     - **[r2]** `ledFps ≥ 58` and `ledShowGapMsMax ≤ 20` at idle (R1, the 10.1 deadline cadence, is in cc5.4; RF0:400,
       :401);
     - **[r2]** during transitions and cover transfers: **`ledFps ≥ 45`** (AL's gate, kept) is the pass rule;
       `ledFps ≥ 55`, `ledShowGapMsMax` and `ledLateShows` are **recorded as the target, not gated**. Reason: RF0:400 ties the
       55 to "R1 (+ R7)", and R7 (HMI priority 1 → 2) is not in cc5.4: PRESENTATION_V5 §12.1 makes R6/R7 "optional, only if
       measurements need them", its OQ-4 stages no R7 binary for the one window, and R7 needs the lease, ack and stress
       checks re-run (RF3 R7). A result between 45 and 55 is reported to the user as the case for R7 in a later release
       (RF0 step 4); below 45 it fails as in AL. The user judges transitions and resting twinkle by eye in the tour;
     - `ledRenderUsMax ≤ 3000`;
     - `lim` events during the turning test (including Seek at 0:00 and `T_end`); **[Q1]** one `lim` and one `bound` per
       push, repeated pushes into the same bound included, none while the knob is held against it and none from
       attractor chatter; `lim_rearm_ms` is tuned here (start 75 ms, range 40–150 ms) and the value is recorded;
     - no `error` replies in the stress test.
     - **[ruling 12.7]** by eye, with `ledDither` unset: the resting and offline LEDs are **steady** (no shimmer or
       sparkle, no hue flip at the dim point), **every mark stays visible** at the dim point of its breath (the 12
       offline marks, the resting ring and buttons), and the offline marks read amber while bright; at the dim point
       they show one count of red (#010000, amber's dominant channel), which is expected. The look session records
       the answers (`check_nanod_cc5_look.py --record-by-eye`: `leds` for steady and visible, `hue` for the hue).
   - The lease check.
   - A new tool, `tools/nanod_alive_tour.py` (companion quit), for the hands-on:
     - it plays each moment on demand (claim → frames with feedback/skip/playing/external/mode changes, clock set to night or day);
     - it sets `ledDrive`/`ledDither` for tuning (**[ruling 12.7]** `ledDither:true` is the A/B against the default).
     - **[r2]** it also plays: the half-wash on both sides, scatter, the pink bloom, the sweep from 0, the Seek lap, the Up
       next levels, pair on/off, the snap button colour, `started`, and reduced motion;
     - **[r2.2]** it also shows the **liked** Button 3 (PINK 0.30) next to a `dim` button (WARM 0.14), so the user
       confirms that "liked" does not read as "broken", with the PINK candidates of Q2; and the Working comet through a
       5 s Seek jump with a follow-up jump and through an uncached Play next (M33);
     - **[r2]** it settles, with the user: **PINK** among three `ledPink` candidates (section 14 Q2); the amber/red body
       **0.62** against **1.0** (`ledVolFull`; U8(a) expected); **paused Play green** (U1); Head shake legibility (8.6);
       the wake feel (6.1).

## 12. Deviations and rulings

**[r2]** Restructured: 12.1 and 12.2 are AL §12 verbatim with [r2] notes where revision 2 amends a ruling; 12.3 and 12.4 are new.

### 12.1 Deviations (revision 1, carried)
- **D1** [user] WARM is fixed at LED #FF8424. Time of day only scales the resting brightness. **[r2]** r2.1 now agrees (R:98).
- **D2** [user] AMBER is LED #FF3A0A (volume 80–90 %, offline marks). RED is LED #FF0000 (volume ≥ 90 %, Cancel, Fail). **[r2]** r2.1 now agrees (R:95–96, :99); "Cancel" survives only for v6 hosts.
- **D3** The transfer curve is the sRGB EOTF, not a pure 2.2 power; the README allows "the driver's LUT". At the design's resting levels, a pure 2.2 power leaves most segments below one LED count. The palette is derived with the same curve.
- **D4** BOUND is the haptic end stop (`atLimit` rising edge). The design's "cursor didn't move" rule would flare on every other 1 % volume detent, because the arc moves every 2 %. Every detent that moves the position ticks. **[r2]** BS keeps the "cursor didn't move" rule (BS:701); in Seek it would bound on most detents (A02 §4.5), so D4 matters more.
  **[Q1]** Amended by ruling Q1 (12.5): the end stop fires on every push into a bound, not only on the `atLimit` rising edge.
- **D5** Offline:
  - There's no "reconnecting" pulse; the knob can't tell reconnecting from away.
  - [user] Native input hands the LEDs to the native profile lights, and 5 s without native input returns the amber marks with a reveal.
  - **[r2]** The second bullet is amended by **M29**: the handover lasts until the next claim; the 5 s return is withdrawn
    (the recorded user decision does not contain it, and r2.1 has no return). The first bullet stays a departure (12.4).
- **D6** Boot omits the LCD fade. The display renderer owns the screen.
- **D7** SWITCHED uses the selected entry's accent even when the pending pulse drew the cursor WARM. The README says album start washes; the design code would bloom. **[r2]** Families extended to explorer and upnext (M10); a start now washes through `started` (M16).
- **D8** PLAY/PAUSE fires only between two consecutive Home frames that both carry `playing`. So starting an album from Recent washes instead of being cut off by `fill`. **[r2]** Extended by M16.
- **D9** SKIP only for knob-initiated Tracks skips (`feedback.skip`), not for natural track advances. **[r2]** The sweep starts at the previous cursor (M21).
- **D10** The v4 odd-volume shoulder is kept: 0.81 awake warm, 1.0 semantic, 0.13 resting. **[r2]** Now 0.81 in every role (M1), on the segment after the endpoint (M13); resting stays 0.13 (BS gives 0.10).
- **D11** Periodic phases use integer-ms modulo, and the ember periods are rounded to whole ms.
- **D12** The effect queue is capped at 8, with deterministic eviction.
- **D13** The Windows pending cursor pulses in the app colour (the design). v4 had white. **[r2]** Extended to every list family (M3).
- **D14** Local cursor. The design assumes no host latency. **[r2]** Extended by M15.
- **D15** The Home Sonos-off notice keeps v4's confirmed-endpoint-only ring (WARM, class 1). **[r2]** At `35 + ⌊c/2⌋` (M13).
- **D16** `ledStyle "white"` means warm only. **[r2]** Extended to the new colours; PINK kept (section 2; M25).
- **D17** A power limiter at the warmth test's proven load.
- **D18** Time of day is continuous; the demo page rounds to half hours. **[r2]** BS is continuous too (BS:599).

### 12.2 Lead rulings (2026-09-25, after the engine review), carried
- **R1 (F4).** Section 6.1 "pending" excludes activity `offline`: the Home Sonos-off notice never shows the Working comet. D15 covers this too, and the golden test's Q3 tag maps back to D15.
- **D19 (F5).** Tick length is `round(x + 1e-4)` with `x = clamp((vel − 4)/14)·7`, so exact ties round up identically in float32 and float64.
- **R2 (Q1).** The section 5.4 tint needs the cursor's role to be ACCENT. A sat() that fell back to WARM gives no tint.
- **R3 (Q2, F3).** The song hand and progress extrapolation need the last Home frame's `playing` to be `true`. A missing `playing` counts as not playing.
  - The host re-sends `progress` whenever its transport state goes from unknown or not-playing to PLAYING.
  - **[C2]** It also re-sends it on the first Home frame with `playing:true` after a Home frame without it (12.5).
- **R4 (F2, host rule for D8).** The host puts `playing` on a Home frame only when Sonos has **confirmed** it.
  - It omits `playing` while the transport is TRANSITIONING or unknown, and on the ok frame of an album start until PLAYING is confirmed.
  - So an album start washes, and the first confirmed `playing:true` frame can't cut the wash with `fill`: the frame before it carries no `playing`.
  - **[r2]** Extended by M16 to the hybrid start (`Starting…` frames and the `started` frame).
- **R5.** The palette table in section 2 was corrected to float constants derived with the sRGB OETF (see section 2), and the power budget to exactly 16920.
- **R6.** C++ keeps one `down` snapshot per queue slot (8), as the design does. This was a review fix and needs no deviation.

### 12.3 [r2] (new) Master additions M1–M31 (**[r2.2]** + M32–M33)

M1–M12 are the rulings A02 §9 proposed as "D19–D29" and 00 as "D30", renamed (VOC §0.3 crosswalk: A02 D19→M1 … D29→M11,
00 D30→M12). Each carries forward with the r2.1 outcome. M13 onwards are new here. "Dev." marks a deviation from r2.1.

| Id | Ruling | Basis | Dev.? |
|---|---|---|---|
| **M1** | The volume body is 0.62 in every colour; the half-step 0.81 in every role (5.2). `ledVolFull` gives the U8(b) alternative for the tour | S01:164; S02:16; BS:1308; CH §7 #2; U8(a) | no |
| **M2** | Volume colours are gated on value **and** position; the pending-decrease span on the confirmed value (5.1.2) | BS:1306; A02 F2; 00 C17; [user] wording | no |
| **M3** | Coloured lists carry only their items' colours: a legacy More is one warm item; the unavailable cursor is class Q (0.45) in its colour; the pending cursor pulses in its colour; loading shows only the comet (5.1.3) | S01:172–175; CH §7 #19; VOC-R05, R06; A02 F5–F7 | no |
| **M4** | Tracks Prev cursor 52, not BS's 53 (5.1.5) | VOC-D04; A02 F9; BS:1332 artefact | **yes** (VOC-D04) |
| **M5** | Scatter uses r2.1's spread recipe, `seed = 60·u` from one xorshift32 shared by both ports, no seed rejection (section 4, 7) | S01:194; BS:657, :879; VOC-R18 (supersedes A02 D23 / F17) | no |
| **M6** | The new moments run on host feedback, never on the press (6.4) | VOC-D03; A02 D24 | **yes** (VOC-D03): the knob can't know success |
| **M7** | No target flash with a moment (5.2) | VOC-R08; A02 F13 | no (r2.1 has no flash) |
| **M8** | Paused Play breathes **green** (5.3); confirmed on the ring at the tour | U1; S01:105; BS:1247; CH §7 #1 | no |
| **M9** | The 20-entry window is re-centred on the transmitted window for every selection ring (5.1.1) | S01:166; CH:114; BS:1319, :1326; VOC-R03 (supersedes A02 D27 "keep V4") | no |
| **M10** | Wash triggers: D7 extends to explorer and upnext; a Switch to a warm app green-blooms; starts use `started` (6.4) | 00 §3.2 "LED"; A02 F11, F12; VOC-R07 | **yes** for the warm Switch (BS:1095 washes warm): green confirms a Switch (S02:79) |
| **M11** | Seek has no local cursor (6.3) | CS §4.2; A04 §7 | no (the design assumes no latency; see D14) |
| **M12** | The 3 Hz rule exempts the Head shake as motion (8.6) | S02:19; CH §7 #15; 00 G7 | no |
| **M13** | The odd-volume half-step lights the segment **after** the endpoint; the cursor is `35 + ⌊v/2⌋` (5.1.2) | S01:164; S02:16; BS:1305–1310; VOC-R04 | no (departs from P4-1 / D10 placement) |
| **M14** | Up next: classes P / N / Q on absolute `ring.now`; the card is the `ring.card` entry (`count − 1`, K1 §4.4; its colour ignored; `ring.unavailable` is stripped on `upnext` by both parsers, P5-R24), counted in the window, with no mark and no cursor cell; moments start at its slot (5.1.4) | S01:166, :360; BS:1317–1322; PRESENTATION_V5 §4.4, P5-10 | **yes** (card geometry and cursor origin): the knob has a detent on the card; BS's cursor-0 is an artefact |
| **M15** | The local cursor re-centres the window; entries not yet transmitted stay unlit; an untransmitted cursor is WARM class 3 (6.3) | D14; VOC-R03 | **yes** (the design has no latency) |
| **M16** | `started` → wash in its colour, or green bloom when warm; the host omits `playing` while a start is pending and on the `started` frame; the engine skips PLAY/PAUSE in that render (6.4, 10.2) | VOC-R07; 00 U11; R4 | **yes** for a warm (no-colour) start only: BS:998 washes in the item's colour even when it is the warm marker; green bloom, as M10 (12.4) |
| **M17** | Reduced motion via latched `reducedMotion`: wake, tick, sweep, scatter, reveal dropped; fail stationary; boot, down, bound kept; the PRNG draws regardless (6.5) | S01 §10; BS:579, :658; VOC-R09 | no (boot/down: r2.1 silent) |
| **M18** | Button tones per VOC §2.3; resting 0.12 when the awake alpha ≥ 0.5, else 0.04 (5.3) | S01:97–108; BS:620, :1291; A02 F16 | no |
| **M19** | `down` keeps RC's recipe, which is S02 §7; BS:659's simplified drain is not used (7) | S02 §7; RC:334–344 | **yes** from BS only; follows the spec text |
| **M20** | Floating-knob glow: six pre-rendered looks with the look's own alpha (BS's `GLL·0.95`), tinted per frame; AL's continuous glow withdrawn (10.3) | S02:21–23; R:105; BS:677, :690; RF0 AR-7 | no |
| **M21** | The skip sweep starts at the previous cursor (amends D9's origin) (6.4 row b) | BS:855; VOC §4.2 row 2; A02 F10 | no |
| **M22** | A feedback moment holds sleep for its effect's duration, like the flash it no longer has (6.1) | follows from M7; S02:118 "Sleep never starts while an action is pending or a flash is showing" | no (r2.1 silent on moments) |
| **M23** | The half-wash growth test is evaluated in integers, `20·abs(k − 15) ≤ min(ms, 300) + 10`, equal to BS at every integer ms (7) | BS:655; D19's reasoning (port parity at ties) | no |
| **M24** | Latched tuning fields `ledPink` and `ledVolFull` for the tour (3.2); additions to VOC §6.2 | 00 U8, U13 | no (tooling) |
| **M25** | PINK is its own role (buttons and the Like bloom), never `sat()`, kept under Warm only (2, 5.3) | R:100; S01:106; CH §7 #22; VOC-R21 | no |
| **M26** | Host accents: the Generated-sleeve warm-marker entry and monochrome apps send 0 (2, 10.2) | BS:536, :1328 (`isW`) | no (reproduces the design's warm) |
| **M27** | While hidden, the floating knob's engine renders once per posted frame or input (after ≤ 60 catch-up steps of 50 ms), without composing, and never on a timer; frame-derived moments are consumed when they arrive, so none replays at slide-in (10.3). DESKTOP_STAGE §11.2 / §11.4 / §6.3 / §6.6 H9 adopt it, catch-up included (13.1 X2, X3). **[erratum R-i]** For a summon by a message, H9 compares the first visible frame with the M27 reference and the continuous twin from +300 ms (12.6 E-i) | FK §4 "never animates while hidden"; AL:425; RF0 §3 rule 3, §4.2 "0 while hidden"; the user's mirror decision | no (r2.1 silent) |
| **M28** | Pulses run only on the list cursor and the Tracks pair; the level and lap rings never pulse (5.1.8) | P4 §5.2, §5.6; S01:202 (comet only while jumping) | no (r2.1 silent) |
| **M29** | The native handover lasts until the next claim; AL D5's 5 s return of the amber marks is withdrawn (8.1); VOC §3.2 follows (13.1 X10) | S02:20 "resume on reconnect"; BS:909, :916, :1303, :1414; PRESENTATION_V5 §8.10 (`Knob controls still work` until the next claim); the user's decision (no return named) | no (it removes a departure) |
| **M30** | The floating knob draws the ring only, no button strips (10.3; section 14 Q1 closed) | FK §2 [user]; DESKTOP_STAGE §11.1; R:105; S02:21 | **yes** from the prototypes (BS:683–694; `Knob Face.dc.html:19–23`), which draw the strips |
| **M31** | `activity:"loading"` means the whole list is loading (comet only); an unloaded entry of a known list is sent with colour 0 and the list's own activity, and drawn as a warm landmark (5.1.3 case 1); K3 and K1 follow (13.1 X6, X7) | S01:165, :267, :300, :336; BS:1318, :1325; VOC-R06 | no |
| **M32** **[r2.2]** | The liked heart (`heart` + `lit:"on"`) is tone `liked`: PINK at **0.30**, never `sat()`, resting WARM 0.04 (M18); the `unlike` moment is retired (reserved, plays nothing, no hold, never a trigger) (5.3, 6.1, 6.4) | R22 CH §1; R22 BS:827, :1268; VOC-R26 | no |
| **M33** **[r2.2]** | The Working comet's pending condition covers seek-in-flight (every jump until playback resumes, across a follow-up jump) and play-next-in-flight (the lookup included); the engine reads both as `activity:"pending"`, which K3 must send for the whole span (6.1) | R22 CH §3, §4; R22 BS:1339 (`_working` = busy ∨ seek jump ∨ loading); VOC-R27, R28 | no |

### 12.4 [r2] (new) Every departure from r2.1 in one place

| Id | r2.1 says / does | This contract | Reason |
|---|---|---|---|
| D3 | "gamma 2.2 (or the driver's LUT)" (S02 §9) | sRGB EOTF | resting levels below one LED count with 2.2 |
| D4 | End stop when "the cursor didn't move" (S02 §8; BS:701) | the haptic end stop (`lim`) | flares every other volume detent and most Seek detents otherwise |
| D5 | Offline marks "0.15–0.5 pulsing while reconnecting" (S02:107) | no reconnecting pulse; the marks breathe as always | while unclaimed the knob gets no host signal, so it cannot tell "reconnecting" from "away". (D5's other half, the 5 s return of the marks, is withdrawn by M29, so the handover now matches r2.1: native lights until the next claim, S02:20) |
| D6 | Boot fades the LCD up (S02 §7 step 5) | omitted | the display renderer owns the screen |
| D9 | "A queue index change fires `SKIP(sign)`" (S02:207) | the sweep plays only for a skip made on the knob (`feedback.skip` on its `ok`) | a natural track end, a skip from another controller or a shuffled advance would sweep the ring (a foreground comet at 0.85) unasked every few minutes, across a resting ring, and a shuffled index change has no meaningful sign; the host knows which skips are the knob's |
| D10 | Half-step resting 0.10 (BS:609 thresholds) | 0.13 | AL D10 / VOC §3.3 |
| D12 | "≤ 8 effects" without an eviction rule | cap 8, deterministic eviction | twin parity |
| D14 / M15 | no host latency | local cursor with a re-centred window | host round trip |
| M4 | Prev cursor 53 (BS) | 52 | BS artefact; VOC-D04 |
| M6 | moments on the press (BS) | on host feedback | no false confirmation; VOC-D03 |
| M10 | Switch to a warm app washes warm (BS:1095) | green bloom | green confirms a Switch |
| M14 | card outside the window, cursor 0 (BS) | card counted, no cell, moments at its slot | detent ↔ slot mapping |
| M16 | a start of a no-colour item washes in the warm marker (BS:998, `item.c`) | green bloom (`started` with colour 0, VOC-R07) | the same reason as M10: confirm green is for "Play / Switch buttons, success" (S02:79), and VOC-R07 keeps parity with D7's green bloom for a warm entry |
| M19 | BS:659 simplified `down` | RC `down` = S02 §7 text | the spec outranks the prototype |
| M30 | the prototypes' knob draws four button strips under the ring (BS:683–694; `Knob Face.dc.html:19–23`) | the floating knob draws the ring only | the user's v5 decision (FK §2 "No button strip"); R:105 / S02:21 name only the ring; the LCD footer already shows each button's state |
| VOC-D02 | snap button in the raw app colour (BS:1282, :1293) | `sat(color)` | legibility and consistency with the ring |

### 12.5 Round-2 records and ruling Q1 (2026-09-25, added at the merge)

Round 2 of the "Warm · alive" integration built the engine against this contract and recorded three rulings that the code
already follows; the merge makes them contract. **Ruling Q1** is new behaviour for the engine packages. The ids are the
round-2 review's own (not 00's contradictions C1–C29, RF0's C2 in 10.3, R2's review item "(Q1)" in 12.2, or section 14's
open questions Q1–Q2).

| Id | Record | Where it lives | Sections |
|---|---|---|---|
| **C2** | The host re-sends `progress` on the **first Home frame with `playing:true` after a Home frame without it** (absent or `false`), besides R3's transport rise. The knob extrapolates only from its Home resume edge (R3), so a resume first seen while the knob showed another screen (a resume from the Sonos app, or an album start held back by R4 / M16) would otherwise start the song hand from the position posted back then, off by the time spent away from Home until the next 30 s refresh. | `runtime.py` `SongProgress.home()`: called with the `playing` of each Home frame about to be written; its rise to `true` makes the next `update()` post, like R3's transport rise | 3, 10.2, R3 |
| **F1 / W2** | The HMI's local-input sampler (`CCAliveKnob`, `cc_alive.h`) **resets on every claim, every release and every pass without a ready control** (`cc_input_id() == 0`, or the ready id changed during the reads). Its first sample after a reset only seeds: a detent is a position change of the same control between two passes of one ready interval, and a control id reused across sessions is never compared. | `hmi_thread.cpp` `alive_sample_knob()` with `CCAliveKnob::reset()` / `sample()` | 6.2, 6.3, 10.1 |
| **W1** | settings.json `led_drive` / `led_dither` **pass through raw** from Settings (the UI neither parses nor rewrites them) and are **validated when applied** (`runtime.led_tuning()` on every runtime build and every Save, then `device.set_led_tuning()`): an invalid value is ignored (not sent, as if absent) and logged by key name only, never by value. `led_pink` / `led_vol_full` (3.2) follow the same rule. | `ui.py` → `runtime.apply_led_tuning()` → `device.set_led_tuning()` | 3, 3.2, 10.2 |

**Ruling Q1: the End stop fires on every push into a bound, not only on arrival.**

- **Why.** Revision 1 fired `limit` (the ring's `bound` and the `{"id","lim"}` event) on the rising edge of
  `foc_thread.pass_at_limit()`. The FOC sets `atLimit` on the first push past a bound and clears it only when the position
  moves off the bound, so after the knob springs back from a push `atLimit` is still true, and every further push into the
  same bound played nothing and sent nothing. The design's End stop answers each push ("turning past it plays the End
  stop", S01:201, :319; BS:918–943 bound on every turn at an end).
- **Rule.** Each HMI pass of the ready control samples `pushing` = the FOC is at the limit **and** its attractor has moved
  past the bound: `atLimit && attract_angle ≠ last_attract_angle`. While the knob is pushed past a bound the haptic code
  does not advance `last_attract_angle` (it only moves on a real detent), so the two differ exactly during a push and are
  equal again once the knob springs back to the bound detent. `limit(now, dir)` and one `lim` fire when `pushing` rises
  from false, provided that
  1. `pushing` has been false for at least **`lim_rearm_ms` = 75 ms** (the re-arm hold-off; the attractor chattering
     around the hysteresis edge during one push never fires twice), counted from the last pass that saw it true (the
     first push after arriving at a bound fires at once: arriving does not set `pushing`), and
  2. at least `lim_gap_ms` (150 ms) have passed since the previous fire, so the ring's `bound` and the wire `lim`
     (spaced ≥ 150 ms by COM, section 3) stay one-to-one.
  `dir = +1` when the position is at `max`, −1 when at 0 (unchanged). A push held against the bound fires once.
  A new control id, a release or a pass without a ready control resets the detector with the sampler (F1/W2).
- **Accessor.** One read-only FOC accessor (the contract's "read-only accessors only", 10.1): either
  `FocThread::pass_limit_push()` returning `haptic_state.atLimit && haptic_state.attract_angle != haptic_state.last_attract_angle`,
  or `pass_attract_angle()` / `pass_last_attract_angle()` compared on the HMI side. Both fields are 32-bit floats written by
  the FOC task; a torn pair costs one pass, which the hold-off absorbs. **No change** to haptic force/profile code, FOC
  control logic or `.pio/libdeps`.
- **Where.** `CCAliveKnob::sample()` takes the `pushing` sample (instead of `atLimit`) and applies the edge, the hold-off
  and the gap; `hmi_thread.cpp` passes it; the engine's `limit()` is unchanged. The desktop engine gets `limit` from the
  wire `lim` (10.3) and needs no change; the host treats every `lim` as a touch and, in Seek, as the limit line and the idle
  re-arm (K3 §2.5, §5.5.3), which more events per bound do not disturb. K1's `lim` row (≤ 1 per 150 ms while ready) is
  unchanged.
- **Tuning.** 75 ms is the starting value. The hardware turning test (11.9) checks one `bound` and one `lim` per push at
  slow and fast pushes, none while held and none from chatter, tunes `lim_rearm_ms` within 40–150 ms and records it.
- **Cost.** One accessor call and a few bytes of detector state in the HMI's static `CCAliveKnob` (no heap, no stack);
  no measurable flash or RAM change.

### 12.6 [errata] Errata of the phase-2b gate (lead ruling R-i, 2026-09-26)

Recorded from the phase-2b build report WP10-1 (the summon fix in `control_center/overlay.py`
`OverlayEngine._alive_messages`) and its headless tests; nothing was shown on screen.
(12.7, after this table, records the 2026-09-26 user ruling on the LED output stage.)

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| **E-i** | **R-i** (WP10-1; DESKTOP_STAGE §6.6 H9) | 11.5 and H9: "the first visible `e` equals a twin rendered continuously at 60 Hz, within 0.02", for every hidden case | for a **summon by a message** (a detent or press whose input makes the knob visible, a Tk frame posted in the same tick as its touch, a feedback frame posted during the arm wait) the first visible frame equals the **M27 reference** exactly, and the continuous-twin comparison (within 0.02) applies from **+300 ms** of visible frames; unchanged for messages posted before the summon (the `like`, `started` and 10 s cases). M27's 50 ms catch-up steps are kept: the first-frame gap (0.268 for a waking detent, 0.112 for a press) fades to 0.0011 by +300 ms. The engine, the wire and the knob are unchanged | 11.5, 12.3 M27; DESKTOP_STAGE §6.6 H9 (its 21.4 E-i); `tests/test_cc_knob_face.py` `FloatingKnobAliveTests`: a detent that summons after 10 s hidden, a press with its feedback frame in the arm wait, a Tk frame posted in the same tick as its touch |

### 12.7 [ruling 12.7] LED output: dither off by default, and the F-T floor (user ruling, 2026-09-26)

**Record.** In the hardware window (2026-09-26) binary A of 1.0.0-cc5.4 was rolled back to cc5.3 after two defects the
user saw; one was an LED flicker. Cause: section 9 step 4's temporal dither was **on by default** (the HMI's unset-latch
fallback `true`, and `CCFrame.ledDither` / `CCAliveLatch.ledDither` defaulting to `true`), and it works on the 0–3-count
levels of the resting and offline states, where it moves most LEDs by one count every frame (the investigation's
simulation of the resting ring: 27.4 of 29 lit LEDs change per frame, 32 % of the luminance RMS in 15–30 Hz).

**Ruling (user, 2026-09-26).**
1. The temporal dither is **off by default**. A latched `ledDither:true` (section 3) re-enables it exactly as before,
   for an A/B; `false` is the default made explicit. Its parsing and latching are unchanged; only the unset value
   (the HMI fallback and the two struct defaults) is now false.
2. A **minimum brightness floor** keeps the dimmest designed marks visible: with dither off, plain rounding darkens
   every mark below half a count (among them the 0.49-, 0.25- and 0.11-count ones). The floor must keep the hue as well
   as one or two counts allow. The rule chosen against the oracles and the engine's breaths is **F-T** (9 step 4): a
   target-lit LED whose plain rounding is dark while `m = max v > 0` shows one count on its dominant channel
   (`q_c = 1` where `v_c = m`, a tie lights every tied channel, the rest 0); every other LED keeps plain rounding.

**Amendment (2026-09-26, the same day, after the review of the fix build D / E).** The first reading of F-T's
channel rule was `floor(v_c/m + 0.5)` ("proportional": the dominant channel 1 and a channel ≥ `m/2` also 1). The
review ran both engines frame by frame and found it discontinuous with plain rounding: plain rounding lights a channel
only at `v_c ≥ 0.5`, so just above `m = 0.5` a second channel is dark, while the proportional floor lit it whenever
`v_c ≥ m/2`. The floored marks sit in the sRGB EOTF's linear toe, where `v`'s ratios are the design-space ones (AMBER
0.51 green per red, WARM 0.75; at full level AMBER is 0.23), so for the amber and warm marks that second channel was
green. Offline, all 12 amber marks went #020100 → #010100 → #010000 → **#010100 (floored, the lowest `v`)** →
#010000 → #010100 → #020100 every 2.6 s breath: green on at the dim point, off on both sides — a hue flip and a
brightness bump at the moment the mark should be dimmest (84 events in 10 s). Asleep on Home at night (clock 00:00
and 23:00) the resting ring and buttons did the same on 27 LEDs (216 events in 20 s; at 23:00 the dim point sat on the
0.5-count knife edge and blipped green for 150 ms). The rule is now **dominant-only**, the byte plain rounding shows
just above `m = 0.5`: the offline marks go #010000 (floored) → #010000 → #010100 → #020100, with no jump. It is also
the candidate closest to the cells' full-level colours (an amber mark dims as red, not yellow) and removes the
float32 / float64 knife edge at 0.5 count. The user's ruling (dither off by default, plus a floor that keeps the
dimmest marks visible) is unchanged; only the floor's channel rule, which was ours to choose against the oracles,
changed.

**Why F-T, dominant-only** (`tests/tools/alive_floor_report.py` → `diagnostics/cc5.4-alive-floor-report.json`; the
report of the first reading is kept as `cc5.4-alive-floor-report.superseded-20260927T002257Z.json`. Oracles: both,
6,303 steps, the rounded `e`, drive 150, dither off; target-lit = the view entry is non-null with `a > 0`. Continuity:
the Python engine frame by frame, 20 s each offline and asleep on Home with the clock unset and at 00:00, 06:00,
21:00, 22:30 and 23:00):

| Measure | dominant-only (chosen) | proportional (first reading, superseded) | per-channel (every channel > 0 at 1) |
|---|---|---|---|
| Continuity: floored bytes brighter than the plain byte next to them in time / channels against their value | **0 / 0** | 642 / 642 | 642 / 642 |
| Hue error vs the cell's full-level colour `eotf(c)` (degrees: mean / p95 / max) | **18.5** / 34.6 / 89.9 | 19.6 / 33.5 / 86.1 | 39.4 / 46.1 / 73.9 |
| Hue error vs the ideal linear `v` (toe ratios) | 33.1 / 45.9 / 50.5 | 21.9 / 27.7 / 27.9 | 24.3 / 32.2 / 41.8 |
| Knife edge (347 lit LED-steps within ±0.005 count of 0.5): same bytes either side | **347** | 240 | — |

- Of 152,190 target-lit LED-steps, 136,068 are already visible: F-T leaves their bytes identical (so the section 2
  picks and the ±1 twin tolerance hold). 6,165 round to dark: F-T lights them (#010000 6,108, #000001 33, #000100 24;
  the proportional reading gave #010100 2,734, #010000 2,713, #010101 662 and 56 others). 9,957 have `e = 0` and stay
  dark.
- The ideal-`v` hue error favours the proportional reading only because `v` in the toe asks for the design-space
  ratio (AMBER as 0.51 green per red, which reads yellow); against the hue the same cell has when bright, and over
  time, dominant-only is the better and the only continuous rule.
- A mask-free floor on `e` (max `e` ≥ 1/256) would light 35,326 LED-steps, 29,414 of them (83 %) without a target
  (effect tails, halos, gaussian skirts), and would hold a mark fading asleep (τ 700 ms) at one count for about 1.7 s.
  So the mask is the **target**, not `e`.
- Cost: at most one count per channel (the oracles' worst step adds 51 counts; bound 204; B = 16,920).
- Knife edge: the float32 knob and the float64 twin may round differently within ±0.005 count of 0.5; dominant-only
  is plain rounding at `m = 0.5`, so both sides give the same bytes for all 347 of the oracles' LED-steps there.

**Where.** Firmware: `cc_alive.h` (`CCAliveSpec::defaultDither = false`; `cc_alive_output(…, ringLit, buttonLit)`, masks
defaulting to 0 = no floor; `cc_alive_lit()`), `cc_alive.cpp` (the floor in `pixel()`; `CCAlive::output()` builds the
masks from its targets, with no new members), `hmi_thread.cpp` (the unset-latch fallback), `cc_presentation.h` and
`control_center.h` (`ledDither = false`). Python: `alive_lights.py` (`DEFAULT_DITHER`, `floor_pixel`,
`reference_output(…, ring_lit, button_lit)`, `lit_masks()`; test-only, the desktop draws `e`, 10.3, so Desk Dial is not
rebuilt). Oracles: `referenceOutput()` and `expect.bytes` (11.1, 11.2). Twin: `make_alive_sequences.py` bytes with the
floor and `lit` (11.4). Tests: 11.6; the by-eye check: 11.9.

**Unchanged.** The engine's `e`, the palette, the power budget, the wire, the parser's acceptance of `ledDither`, the
host (it still sends `ledDither` only from settings.json `led_dither`) and `presentation`/`alive` versions.

### 12.8 [ruling 12.8] Resting is one steady dim warm white, and HOT == WARM (user ruling, 2026-09-26)

**Record.** On the hardware (cc5.4 fix build, 2026-09-26) the resting levels of 5.2 (0.05 / 0.10 / 0.16, 0.13 for S)
and M18's buttons (0.12 / 0.04) gave 0–3 counts at drive 150: too dim for the LEDs to show the warm hue (the colour
shifted), and the 5.2 s rest breath moved them through those counts. The chases and accents in HOT
(mix(WARM, white, 0.5)) read as a second, cooler white next to WARM.

**Ruling (user, 2026-09-26).**
1. **Resting = one steady dim warm white.** Every lit segment at rest has alpha **0.34** whatever its class
   (`alphaResting` / `ALPHA_REST`; about (8..11, 5..6, 1..2) counts at drive 150, enough to show the hue). Buttons at
   rest: **0.34** when the awake alpha is ≥ 0.5, else **0.26** (`buttonRestHigh` / `buttonRestLow`; M18's split
   kept). D10's half-step still exists at rest, at the same 0.34.
2. **No rest breath**: the breath runs only offline (8.1). Resting targets are `alpha × max(todB, 0.80)`.
3. **Time of day** (8.3) still dims resting, but never below **0.80** (`restTodMin` / `REST_TOD_MIN`).
4. **No song-progress hand at rest** (8.4): the hand's latch and eligibility (R3) are unchanged, but it is not drawn
   while asleep, and since it was only eligible at rest it is never drawn.
5. **HOT == WARM** (1.0, 0.746862, 0.411645; LED #FF8424 at drive 255): the volume chase, the Working comet head, the
   scatter sparks, the button glints and every other HOT accent are the same warm white.

**Where.** Firmware (flashed and approved): `cc_alive.h` (`hot`, `alphaResting`, `restTodMin`, `buttonRest*`),
`cc_alive.cpp` (`restK`, the breath only offline, the song hand `!asleep`), marked `[user 2026-09-26]`. Python twin:
`alive_lights.py` (`HOT`, `ALPHA_REST`, `REST_TOD_MIN`, `BUTTON_REST_*`, `step()`). Oracles (11.1, 11.2): both
design oracles apply the ruling to the design's `draw()` with literal anchored `RULING_PATCH`es (recorded in each
fixture's `rulingPatch`): HOT = WARM, the resting factor `max(todB, 0.80)` with no breath, no hand at rest, and in
BS the resting levels 0.34 and 0.34 / 0.26 (its fixture views carry them); RC's views keep the design's own targets.
Target goldens (11.3): the RC golden explains every resting-alpha difference from finishAlive with tag **UR-12.8**;
the BS golden maps BS:609 / BS:620 to the ruled levels, so D10 no longer differs there. The floor report (12.7) was
regenerated (the previous one kept as `cc5.4-alive-floor-report.superseded-20260927T031625Z.json`): at rest the F-T
floor is no longer reached and nothing changes frame to frame; it still serves the offline marks and fades.

**Unchanged.** Awake levels (5.2), the offline marks and their breath, the paused-Play breath, the output stage and
the F-T floor (12.7), the wire, the host frames and the `presentation` / `alive` versions.

## 13. [r2] (new) Handed to other contracts

| To | Item |
|---|---|
| **K1** (`PRESENTATION_V5.md`) | Syntax, validation, stripping and fixtures of every field in 3.1 and 3.2; `ledPink` and `ledVolFull` as additions to VOC §6.2; the byte budget. **The Up next card's wire form is K1's `ring.card`** (§4.1, §4.4, VOC-K1a), adopted as is by 5.1.4 (the earlier recommendation of an `unavailable`-bit card is withdrawn). The presentation-4 downgrade (VOC §2.2). |
| **K3** (`CONTROL_CENTER_V5.md`) | When each `ok` and moment is sent (VOC-D03); the M16 `playing` omission; the Seek `lap` index/count (`t(n)`, D); `ring.now`; snap and `started` colours; the M26 accents; `reducedMotion` from the Settings `motion` key; the M31 loading rule. |
| **K4** (`DESKTOP_STAGE.md`, `FLOATING_KNOB.md` amendment) | The overlay-thread engine, the input fast path, the vblank loop and its rate lock, the glow sprite cache's construction (10.3); the single floating-knob frame-rate gate (§6.3); suppression reasons. The glow's looks, radii, alpha and scale are this contract's (10.3 item 3). |
| **ALIVE workflow / WP2** | **Merged (2026-09-25):** this file is revision 2; the draft is kept as `ALIVE_R2_DRAFT.md`, superseded. The existing D-, R- and D19 ids keep their meaning. Still to build in the engine packages (the tree as merged): **M29**, remove the 5000 ms native-handover return (`hmi_thread.cpp` `kNativeHoldMs` and its `CC_LED_MODE_NATIVE` timeout still return the LEDs after 5 s); the twin-replay handover sequence changes with it (11.4). The **10.1 deadline cadence** 16/17/17 ms (`hmi_thread.cpp` still advances `alive_next_show` by a flat `kAliveFrameMs` = 16, ≈ 62.5 fps). **Q1** (12.5): the push detector, its read-only accessor and the 11.4 sequences. The v5 frame fields (3.1) are now in `cc_presentation.h` (PRESENTATION_V5 §3.6), so `CCAliveFrameExtra` can read them from `CCFrame` (section 4, "Frame fields"). |
| **V5_VOCABULARY** | Record M13–M31, the role `PINK`, the classes `P`/`N`/`Q`, the two tuning fields, and the diag fields `ledShowGapMsMax`, `ledLateShows`. **Done** in the consistency pass: VOC §13.3 (M13–M31), §1.2 (`CCAliveRole` 7 `PINK`, `CCAliveClass` 6–8), §6.2 (tuning fields, range 0..0xFFFFFF), §6.1 (diag). **Merge (2026-09-25):** VOC's K2 pointers name `ALIVE.md` revision 2, and `lim_rearm_ms` (Q1) is in VOC §10. |
| **[r2.2]** K1, K3, K4, VOC | **K1:** the derived tone `liked` (`CCButtonTone` 7) for `heart` + `lit:"on"` and its LCD look (filled `heartfill`, `#A3244A`) (K1 5.2, P5-R29); `unlike` stays a reserved moment (P5-R30). **K3:** `activity:"pending"` for the whole Seek span (every jump until playback resumes, across a follow-up jump) and the whole Play next job (lookup included) (M33; K3 C5-68, C5-69); a liked row stays `enabled` + `lit:"on"` and its press is refused (C5-67). **K4:** nothing (the floating knob draws the ring only, M30; its LCD mirror is K1's). **VOC:** tone `liked`, M32–M33, VOC-R26…R28 (recorded, VOC §1.2, §2.3, §13) |

### 13.1 [r2] Cross-doc changes (from the 2026-09-25 consistency review; all applied in the consistency pass, see Status)

| # | File, section | Change | Why (this contract) | Status |
|---|---|---|---|---|
| X1 | DESKTOP_STAGE §11.3 "Glow shape" row | σ = `GLB`/2 × **(ring diameter in physical px)/318** (360/318 × DPI/96 = 1.1321 here: σ 3.40 … 10.19 px, blur radii 6.79 … 20.38 px), replacing `S = 360/286 × DPI/96 = 1.2587`; better, cite 10.3 item 3 instead of restating | one design value, one mapping (10.3 item 3 "Why /318") | applied (DESKTOP_STAGE §11.3 `S_glow`) |
| X2 | DESKTOP_STAGE §11.2 last bullet, §11.4 "0 while hidden", §6.3 "Knob ring (K)" CPU column | adopt M27: while hidden there is no loop, but `render(now)` runs once per posted frame or input (after ≤ 60 catch-up steps), with no compose or present; that per-message work is allowed under "0 while hidden". Replace "the engine does not render (AL:425)" | frame-derived moments would otherwise replay seconds late at slide-in (10.3 item 2) | applied (DESKTOP_STAGE §11.2, §11.4, §6.3, with the catch-up) |
| X3 | DESKTOP_STAGE §6.6 | add the hidden-render test of 11.5 (render/compose/present counts; no replayed bloom; `e` equal to a continuous twin after slide-in) | M27 | applied (DESKTOP_STAGE §6.6 H9) |
| X4 | DESKTOP_STAGE §5.1 P6 and §11.4 "Budget" vs §6.3 | one rule for the knob frame work: §6.3's "≤ 2.5 ms p95 at 100 %" (or change §6.3); P6 and §11.4 say "≤ 2.5 ms median and ≤ 3.0 ms p95" | 10.3 item 5 cites §6.3 as the only gate | applied (DESKTOP_STAGE P6, §11.4: ≤ 2.5 ms p95) |
| X5 | DESKTOP_STAGE §11.4 frame key | add the per-segment 8-bit glow tint `round(e/mx·255)` to the "skip unchanged frames" key (it lists fill and look index only) | a tint change with unchanged fill and look would otherwise never be presented (10.3 item 2) | applied (DESKTOP_STAGE §11.4 frame key) |
| X6 | CONTROL_CENTER_V5 §5.2.3 row "item not yet loaded" (and §5.3.4 recent tab, which inherits it) | `activity` **idle** (or `pending` while Play next runs), and that entry's colour **0** in `colors[]`; the ring is the normal selection (the entry a warm landmark). Keep `activity:"loading"` only for "first page loading" (and §5.3.4 "favourites loading", §5.6.4 before the first window) | M31: with `loading` the whole ring blanks and the local cursor freezes (5.1.3 case 1, 6.3) | applied (CONTROL_CENTER_V5 §5.2.3, §5.3.4, §5.6.4) |
| X7 | CONTROL_CENTER_V5 §18 K1 row; PRESENTATION_V5 §4 | the loading-list wire form: `ring.style:"off"` + `activity:"loading"` (a `selection` ring with `loading` draws the same) | K3 §18 asks K1 for it; 5.1.3 case 1 | applied (PRESENTATION_V5 §4.6, VOC-K1g; CONTROL_CENTER_V5 §18) |
| X8 | PRESENTATION_V5 §3.1, §7.2, §14.1, §15.1, §16.4; `device.py` gating | add `ledPink` (int 0..0xFFFFFF, 0 = built-in PINK) and `ledVolFull` (bool): latched on acceptance with the ALIVE fields, kept across releases and claims, reset only by reboot; all layouts; gated on `alive`; invalid → reject (firmware) / strip and log (host). Latched reserve +38 B (worst Windows frame 1,352 B < 1,400). `frames_v5.json` cases: `ledPink` 0, 1, 0xFFFFFF valid; −1, 0x1000000, `true`, `"#FF051A"`, 1.5 invalid; `ledVolFull` true/false valid, 1 and `"true"` invalid; both absent on a knob without `alive`. Record as VOC additions (VOC §6.2) | M24; without them a cc5.4 parser ignores the fields (K1 §3.3 rule 4) and the tour cannot settle PINK or U8 | applied (PRESENTATION_V5 §3.1, §3.6, §7.3, §14.1, §15.1, P5-R27; VOC §6.2) |
| X9 | PRESENTATION_V5 §15.1 `card` family | optionally one case with `card:true` **and** the card's `unavailable` bit set, stored unchanged (the bit is ignored for the card) | 5.1.4 item 5; the LED side is covered by 11.3 / 11.4 | superseded: K1 strips `ring.unavailable` on `upnext`, so the case stores 0 (PRESENTATION_V5 §15.1, P5-R24); the engine-level case stays in 11.4 |
| X10 | V5_VOCABULARY §3.2 `offline` row | drop "5 s without native input returns the marks with a reveal"; "native input hands the LEDs to the native profile lights until the next claim" | M29 | applied (VOC §3.2) |
| X11 | V5_VOCABULARY §3.2 `selection` / `upnext` rows | "Loading list: comet only" is the whole list; an unloaded entry of a known list is a warm (colour 0) entry; Up next card = `ring.card` (VOC-K1a) | M31, M14 | applied (VOC §3.1, §3.2) |
| X12 | V5_VOCABULARY §13 / §0.3 | record M29–M31 and the diag fields of 10.1 | VOC rule 1 | applied (VOC §0.3, §6.1, §13.3) |

## 14. [r2] (new) Open questions

(Q1 and Q2 here are this section's open questions; ruling **Q1** of 12.5, the End stop per push, is a separate id.)

**Q1. Does the floating knob draw the four button backlights? — Closed: no (M30).**
AL §10.3 drew button strips (`38 + e·217`, with a glow), and BS's knob canvas shows four caps with strips under the ring
(BS:683–694). FK §2 says "No button strip", R §6 says the floating knob "mirrors the physical **ring**", and the user asked
for "just the knob face with the LEDs surrounding it … no toolbar".
*Answer: ring only for this release*, in line with DESKTOP_STAGE §11.1 ("The floating knob has **no button LEDs**"). The LCD
footer on the floating knob already shows each button's state in its ink (green, pink heart (**[r2.2]** the filled
`#A3244A` heart when liked), the snap colour, dim), so
only the transient tints (the wash on Button 4, the half-wash on 2 or 3, the press) and the paused-Play breath are lost on
screen, and K4's geometry stays as it is. The button look in 10.3 is recorded for a later release only; reopening it
needs the user.

**Q2. The final PINK.**
PINK is a candidate (R:100; S02:15; CH "Still open"); the user picked WARM, AMBER and RED on the ring, and 00 U8
recommends the same for PINK.
*Recommended: pick on the ring in the LED tour among three candidates, via `ledPink`, and freeze the pick as float
constants (section 2).* Candidates (design sRGB → LED output at full): **255,40,90 → #FF051A** (the design's), **255,60,120
→ #FF0C30** (softer, more magenta), **255,20,70 → #FF0210** (deeper). Ship 255,40,90 until then.


---

## 15. [r3] Presentation 6: the Lights family (Desk Dial r3 release 1, 2026-09-28)

Source: README r3 §3 (ring, button LEDs), PRESENTATION_V5.md section 19 (wire). Implemented in `cc_alive.h/.cpp` and its twin `control_center/alive_lights.py`; every rule below is append-only, every earlier family, style, class and effect is unchanged, and the user rulings stand: steady warm-white rest (12.8), HOT = WARM, dither off with the F-T floor (12.7), the inactivity dim/sleep of `cc_sleep.*` (untouched).

### 15.1 Family

`CC_ALIVE_LIGHTS` (7) = layouts `lights`, `lightsbig`, `scenes`. A change into or out of it is a MODE event (reveal, 6.4). No tint (not a list family), no song hand, no heat, no PLAY/PAUSE fill/drain, no EXT shimmer (those stay Home's).

### 15.2 Ring targets (the r3 arc)

Arc position k = 0..44 is logical segment `(38 + k) mod 60`: 38 (7:30) clockwise through the top to 22; 23..37 stay free. "Turning" = the frame's layout is `lightsbig` (the host shows it while the knob turns and 1.4 s after).

| Style | Cells | Cursor |
|---|---|---|
| `bri` | n = (45 v + 50) div 100 (v = ring.value, or the local value 15.6): k < n ACCENT `kelvin_rgb(ring.kelvin)` class **3** (1.0) turning, else **L** (0.34); k ≥ n **off** ([user 2026-09-29]) | arc(n − 1), arc(0) when n = 0 |
| `ctemp` | m = (44 value + 50) div 100: k ≤ m ACCENT `kelvin_rgb`; k = m class 3; k < m class 3 turning, else **F** (0.50); k > m **off** ([user 2026-09-29]) | arc(m) |
| `clusters` | N = count (1..20), centre c_s = (120 s + N) div 2N (= round(60 s / N)); cells c_s − 1..c_s + 1 (mod 60, wrapping at 0) WARM class **O** (0.18), the selected one (ring.index or the local index) class 3, drawn last | c_index |
| `off` (lights off) | dark (5.1.7) | 0 |

**[user 2026-09-29] ruling:** the unfilled part of both Lights arcs is OFF, not a dim track. At 0.08 / 0.12 the LEDs showed about one count and drifted to olive / yellow (the same low-level hue shift as the 2026-09-26 resting ruling), so the README's `unfilled L 0.08` (bri) and `remainder L 0.12` (ctemp) are not drawn; the filled part, the marker and the clusters are unchanged. Classes T and R stay in the enum and tables (append-only) but no target uses them.

The Kelvin colour is an ACCENT drawn as is: **never sat()**, no WARM fallback (6500 K = 255,254,250 stays itself), no amber / red volume colours, no near-max embers, in `ledStyle` white and colour alike.

### 15.3 Classes and alphas (append-only CCAliveClass 9..13)

| Class | Awake (warm and semantic) | Resting |
|---|---|---|
| T (bri unfilled; unused since [user 2026-09-29]) | 0.08 | 0 (dark) |
| R (ctemp remainder; unused since [user 2026-09-29]) | 0.12 | 0 |
| O (clusters not selected) | 0.18 | 0 |
| L (bri filled at rest) | 0.34 | 0.34 |
| F (ctemp filled at rest) | 0.50 | 0.34 |

Resting keeps the one steady warm white of 12.8 (every resting cell WARM at 0.34); the unfilled track, the remainder and the other scenes rest dark so the resting ring still reads as the level / the selected scene.

### 15.4 Buttons

5.3 unchanged except row 6 in LIGHTS: a lit-on button (the active knob mode, e.g. Temperature on) is WARM class 3 at **0.90** (`buttonActive`; README r3 "active mode warm L 0.9"); it rests at 0.34 (≥ 0.5, M18). Button 4 `power` is tone nav (WARM 0.70): never red. The scenes list's Run (`switch` on slot 3) is go (GREEN).

### 15.5 Feedback

A plain `ok` (no skip, no moment) on a LIGHTS frame starts the flash kind **`CC_FLASH_WASH`** (3; Python `"wash"`) instead of OK: for **700 ms** every ring segment is GREEN class 4 at **0.68** (a target override, damped like any target), no bloom is queued, and the flash holds sleep like any flash (6.1). `err` keeps rows a (fail) and the red 5-segment flash; moments keep their rows.

### 15.6 Local cursor (6.3)

`bri` takes the local value when the control's max is 100 (the brightness profile, BINARIS BEER like volume); `clusters` takes the local index when max = count − 1 and the activity is not pending / loading; `ctemp` never (the host's bounds follow the group's reported min/max).

### 15.7 Verification

**The marker ring** (`marker`, the r3 Windows screen): pos = (2 index · 44 + span) div 2 span (span = max(1, count − 1), the
local index when max = count − 1); cells pos − 1..pos + 1 on the arc ACCENT white (`markerRgb`) class **3**; the rest of
the arc is **off**. **[user 2026-10-03] ruling:** like the Lights arcs (15.2) and the queue ring (15.9), no sub-floor dim
segments: the design's rest class **M** (WARM 0.10, #020100 at drive 150, hue-shifted) is not drawn. `CC_ALIVE_CLASS_M`
stays in the enum and tables (append-only) but no target uses it. Cursor: `arc_segment(pos)`.

`alive_tests.py`: the four r3 twin sequences (`r3-lights-bri`, `r3-lights-ctemp`, `r3-scenes-clusters`, `r3-lights-off`, in `tests/tools/make_alive_sequences.py`, fed as Raw presentation-6 frames) replay through the firmware's `cc_parse_frame` + `CCAlive` against the Python engine (e within 2e-3, bytes within 1, cursor / flash / effects / asleep exactly), with every earlier case unchanged. `tests/test_alive_r3.py` writes 15.2–15.6 out. The design oracles (RC, BS) do not model the Lights states. The contact sheet `harness/r3-handoff/contact-sheet-r3.png` shows each state's ring bytes next to the r3 prototype's ring.

### 15.8 [r3.1] The button-4 hold ring and its landings (Desk Dial r3.1, 2026-09-29)

While physical slot 3 is held (`press(now, 3)` .. `keyUp(now, 3)`) on a claimed render whose frame has
`holdMarker:true` (PRESENTATION_V5 19.10), on any screen (the launcher Home included, no crumb needed), the hold-1 look
is drawn over the 1000 ms hold (`hold4RingMs`; the firmware's `kh` for every slot but 0 matures then):
`holdFill = round(held x 45 / 1000)` WARM class 4 at 1.0 on the r3 arc, the rest of the ring dark ([user 2026-09-29] no
sub-floor tail; the design's 0.08), shown from **15 %** (150 ms; hold 1 keeps 12 % of 600 ms). At 1000 ms the hold has
no firmware flash: the full arc stays up to 600 ms (`landingWaitMs`) while the **landing window** is open, and the
first new feedback seq within 1500 ms (`landingWindowMs`) of the maturity lands it:

| feedback | landing |
|---|---|
| `ok` (no skip, no moment) | `CC_FLASH_LAND` (6, Python `"land"`): the whole ring 0.68 for **450 ms**, in `cc_kelvin_rgb(ring.kelvin)` (ACCENT) when the landing frame's ring is `bri` / `ctemp` (the Home lights domain), else WARM (back to music) |
| `ok` + moment `queued` | `CC_FLASH_QUEUE` (7, `"queue"`): the whole ring GREEN 0.68 for **600 ms**, instead of the queued sweep (no moment hold) |
| anything else (err, refused, skip, other moments) or later than 1500 ms | as usual (rows a-j) |

The landing window closes on its first new seq, after 1500 ms, and at claim / release. A release of button 4, a claim or
a session release cancels the ring. While the hold-1 ring runs (slot 0 held on a crumb screen) hold 1 wins and the held
slot 3 is dropped until its next press. Host contract: send the domain-swap frame with a plain `ok`, the queued item
with `ok` + `queued`, a denial with `err` (+ `refused`). Python: `alive_lights.HOLD4_MS`, `HOLD4_SHOW_PCT`,
`LANDING_WINDOW_MS`, `LANDING_WAIT_MS`, `LAND_FLASH_MS`, `QUEUE_FLASH_MS`.

### 15.9 [r3.1] The queue ring (whole-queue Tracks and Up next)

Ring style `queue` (PRESENTATION_V5 19.10): row j sits at arc position `pos(j) = round(44 j / max(1, count - 1))` on
the r3 arc (`arc_segment`). The playing row (`ring.now`, when >= 0) is one segment in warm white `0xFFE8CD` (ACCENT)
at the new class **W** (15; 0.60 awake in both tables, 0.34 resting); the focus (the local index while turning,
6.3 like the marker: max = count - 1, not while pending / loading) is `pos(focus) +- 1` at class 3 in its row's album
colour (`sat(colors[focus - first])`, ACCENT) or WARM without one, drawn over the playing segment. **The rest of the
arc is OFF**: the r3.1 prototype's `R.queue` draws it at 0.10 in the album colour, which the user ruling of 2026-09-29
("no sub-floor dim segments", like the unfilled Lights arcs) replaces with off. The queue ring never tints (5.4, like
the marker). Cursor: `arc_segment(pos(focus))`.

Verification: the `r3-hold4-ring` and `r31-queue-ring` twin sequences (`tests/tools/make_alive_sequences.py`, Raw
frames) replay through `cc_parse_frame` + `CCAlive` against the Python engine in `alive_tests.py`;
`tests/test_alive_r3.py` (R31Tests) writes 15.8 / 15.9 out.

## 16. r4 LEDs (design_handoff_nano_d_r4 README 3.3 / 3.4, 2026-09-30; plan stage F4)

A layer after the animator (`CCAlive::r4Layer`; twin `AliveLights._r4_layer`, byte-checked by `alive_tests.py`). The
animator itself and both design oracles are unchanged; `ringE()` / `buttonE()` and section 9 now read the eased values.

1. **Output easer.** Every ring and button LED eases towards the animator's e (after the wall glow) with τ = 50 ms,
   integrated with a first-order hold: `s1 = x1 + (s0 - x0) a - (x1 - x0) b`, `a = e^(-dt/τ)`, `b = τ/dt (1 - a)`
   (x0 / x1: the animator's e at the previous / this render; dt = the real gap since the last render, <= 1000 ms,
   not the animator's 50 ms cap, so a render after a gap lands where a continuous one would); dt 0 changes nothing;
   `|x1 - s1| < 1e-6` lands on x1.
   `animating()` also covers the easer (residue > 1/1024), a wall glow and a sweep. At 16 ms an LED moves ≤ 27.4 % of
   its gap per frame. 11.5 (frame rates) holds on the animator's e within 0.01; the eased output within 0.12 (the
   floating knob's mirror vs a 60 Hz twin within 0.2 while an effect edge passes; `test_cc_knob_face`).
2. **Wall glow (3.3).** Each limit (6.2) also starts the end glow at the cursor: segments cursor ±2 blend towards
   tone(255,232,205 / 255 × 0.9) by g(t): E.out rise over 90 ms (`eo`), then 1 − E.io fall over 420 ms (`eio`),
   from the limit's time. The bound comet (7) still plays under it.
3. **Deny glow.** `CC_FLASH_REFUSED`: segments 26..34 = ACCENT 0xFF3C28 (255,60,40), class 4, 0.9, for **480 ms**
   (15.7's 320 ms RED superseded); the damping and the easer make it a bloom.
4. **M12 domain swap (15.8 superseded for plain ok).** A plain-ok landing (`CC_FLASH_LAND`) draws no wash; it starts
   the sweep: segment i keeps what it shows until `8.7 i` ms after the landing, then eases (200 ms) to the new ring;
   the window is 800 ms (`landFlashMs`). `CC_FLASH_QUEUE` (ok + queued) is unchanged.
5. **Unchanged rulings.** Warm-white rest, green Play while paused, the F-T floor (below-floor LEDs stay off unless
   their target is lit).

