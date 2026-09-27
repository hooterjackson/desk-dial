# V5 vocabulary: the shared names, tokens and ids for cc5.4 + desktop v7

Status: **frozen build contract**, written 2026-09-25 for the one combined release **firmware 1.0.0-cc5.4 + desktop v7**
(the "Warm · alive" LED engine plus the whole r2.1 master design). Documents only; nothing was built or run.
Revised the same day after the cross-contract review, and again in the consistency pass that applied every contract's cross-doc changes to all five files (§15 lists every change; §16 lists the K1/K3/K4 additions absorbed here). **Revision 4** (the same evening) absorbs the live-check amendments of K3 (Like, Unlike, Seek, Play next; C5-62…C5-66) and the merge of the ALIVE draft into `ALIVE.md` revision 2 with its round-2 records (§15 items 23–28). **Revision 5 [r2.2]** (2026-09-25, late) applies the design follow-up **r2.2** (`R22` below): Like is add-only for good (a liked row's Button 3 is PINK at 0.30 with a filled `#A3244A` heart; the unlike moment, `Like removed` and the heart-off animation are gone), the §9.5 copy is approved (two strings rewritten), Seek lands when playback resumes (8 s to failure, one follow-up jump), and Play next shows `Finding songs…` during its lookup (§15 items 29–33). Every change is tagged **[r2.2]**. **Revision 6 [P2a]** (2026-09-25, night) absorbs K3's phase-2a text amendment (C5-73…C5-76; §15 item 35): shuffle off takes the ledger's Play-next units, `jump` lands by the Seek rule, the internal effect `resolve_drop`, and `group_changed_ms` 2600. No token, wire field or copy string changes. Its **review fixes** (same tag, §15 item 36) record the shuffle-off preview's limitations, K3 **C5-77** (a start drops a waiting Seek follow-up), `group_changed` per op, and the `jump`'s use of `seek_confirm_ms`. **[rename]** (2026-09-26): the app is **Desk Dial** (VOC-R32, §15 item 37): the offline sub-line and the Settings knob copy change; no token, id, wire field or internal identifier changes. **Revision 8 [P3]** (2026-09-26, the lead's phase-3b decisions; §15 item 38) absorbs K3's phase-3 additions: `windows_cancel` carries the close `reason` (C5-78), the Shuffle-off preview follows the restore record when the controller knows it (C5-79), and the H5 parse caps (`catalog_songs` ≤ 50 ids per request, `limit=50` tracks pages); with the **[P2b]** `error` tone of `Speaker group changed` (R-j, §8.5, §10). No token, knob wire field or copy string changes.

This file is the dictionary the four contracts share. It does not restate their mechanics:
- **K1** `firmware\PRESENTATION_V5.md`: frame, parser, LCD (owns wire semantics, LCD geometry, byte budget).
- **K2** the ALIVE revision for the master additions: **`firmware\ALIVE.md` revision 2** (owns LED targets, effects, recipes; its master rulings are `M1…`). Since 2026-09-25 (rev 4 of this file) the draft `ALIVE_R2_DRAFT.md` is merged into `ALIVE.md`, with the round-2 records C2, F1/W2, W1 and ruling Q1 (K2 §12.5); the draft is kept, marked superseded, with the same section numbers, so citations of "ALIVE_R2_DRAFT §n" below and in the other contracts resolve to `ALIVE.md` §n.
- **K3** `app\CONTROL_CENTER_V5.md`: controller grammar, timers, services, copy use, confirmation policy.
- **K4** `app\DESKTOP_STAGE.md` (+ amendments to `CAROUSEL.md`, `FLOATING_KNOB.md`, `APP_ICON.md`): desktop surfaces.

**Rules for K1–K4.**
1. Every token, id, enum value and copy string below is used **verbatim**. A contract that needs a new one adds it here first (or records it as an addition with a `VOC-` id in its own deviation list and cites this file).
2. Where this file says "K*n* owns", the named contract decides the mechanics; the name here is still binding.
3. Precedence for behaviour and look: r2.1 README > r2.1 specs/01 > 02 > 03 > 04 > 05 (R §0). For feasibility: the engineering analysis (00 and its sources) with the r2.1 changes applied on top. User decisions are binding. Every departure from r2.1 has a `VOC-D` id (§13); every choice between sources has a `VOC-R` id (§13); every naming resolution has a `VOC-N` id (§12).

---

## 0. Keys, notation, numbering

### 0.1 Source keys

All paths under `<repo>\`. `HO` = `app\design-reference\design_handoff_nano_d_master_r2.1\`; `AN` = `app\design-reference\ui-v2-analysis\`.

| Key | File |
|---|---|
| R | `HO\README.md` (r2.1) |
| CH | `HO\CHANGELOG.md` |
| S01…S05 | `HO\specs\01-FEATURES-explorers-snap-seek.md` … `05-APP-ICON.md` (r2.1; S01 App A/B/C = its appendices) |
| BS | `HO\prototypes\Browse and Snap.dc.html` (**r2.1 copy**; line numbers are r2.1's, not the r1 numbers the analysis cites) |
| HT | `HO\prototypes\handoff-tables.js` (motion, blur, copy data) |
| KM | `HO\prototypes\knob-model.js` |
| 00, A01…A06 | `AN\00-summary.md`, `AN\01-knob-behaviour.md` … `AN\06-services.md` |
| CS, CP, CL, CF, RP, RA, LC | `AN\check-seek.md`, `check-play-next.md`, `check-like.md`, `check-favourite-playlists.md`, `research-apple-music-play-next.md`, `research-artwork-resolution.md`, `live-checks.md` |
| LS | `AN\like-star-mismatch.md` (rev 4: which Apple call reaches the user's devices; **[r2.2]** its last section records the web player's `DELETE /v1/me/favorites` sent once with the user's approval, 2026-09-25 16:03 PDT: **HTTP 400, code 40012 "Insufficient Permissions"**, nothing changed, so `UNLIKE_STRATEGY = add_only` is final) |
| **R22** **[r2.2]** | `app\design-reference\design_handoff_nano_d_master_r2.2\`: the design follow-up r2.2. **`R22 CH §1…§4`** = its `CHANGELOG.md` section "r2.2 — follow-up 1 from engineering", items 1 (Like add-only), 2 (copy approval), 3 (Seek timing), 4 (Play next timing): the authoritative list. `R22 S01` = its spec 01 (incl. App C), `R22 BS` = its `Browse and Snap.dc.html`, `R22 HT` = its `handoff-tables.js`. Everything r2.2 does not change stays r2.1 (R22 CH "Everything else in r2.1 stands") |
| RF0…RF3 | `AN\refresh-00-recommendation.md` (incl. its "Adversarial review", AR-n), `refresh-01…03` |
| AL | `firmware\ALIVE.md` **revision 1** (as published before the 2026-09-25 merge; `AL:n` line numbers and `AL §n` refer to it; its text is carried unmarked in revision 2, which is K2) |
| P4, AW2, CC | `firmware\PRESENTATION_V4.md`, `ARTWORK2.md`, `CONTROL_CENTER.md` |
| FP, FPA, FD, FA | `firmware\src\cc_presentation.h`, `cc_frame_parse.cpp`, `cc_display.cpp`, `cc_alive.h/.cpp` |
| PR, DV, CT, RT, UI, OV | `app\control_center\presentation.py`, `device.py`, `controller.py`, `runtime.py`, `ui.py`, `overlay.py` |
| CAR, FK | `app\CAROUSEL.md`, `FLOATING_KNOB.md` |
| K1, K2, K3, K4 | the four contracts named in the header (`PRESENTATION_V5.md`, `ALIVE.md` revision 2 (formerly `ALIVE_R2_DRAFT.md`), `CONTROL_CENTER_V5.md`, `DESKTOP_STAGE.md`); cited as `K1 §n`, `K1 P5-Rn`, `K2 M24`, `K3 C5-n`, `K4 VOC-K4-nn` |

Citations are `KEY:line`, `KEY §n`, or `KEY <id>` (e.g. `00 G12`, `A02 F14`, `00 U11`).

### 0.2 Numbering conventions (used by every contract)

| Thing | Convention | Source |
|---|---|---|
| Buttons, user-facing | **Button 1…4**, left → right under the knob. Button 1 = Back/Play-Pause, Button 4 = the action | R §4; S01 §1 |
| Buttons, wire and host | **slot** 0…3 = `frame.buttons[0..3]` = the controller's **logical index** 0…3 (Button n = slot n−1) | P4 §3; AL §5.3 |
| Buttons, hardware | **raw index** 0…3 as sent in `kd`/`ku`/`kh`; `control.buttonOrder` maps raw → slot | CC "Input events" |
| Ring segments | 0…59, segment 0 at 12 o'clock, clockwise | S02 §1; P4 §5.1 |
| List landmark slot | `slot(j) = ((j − c0)·3) mod 60` (3 segments = 1 detent at 20/rev), see §3.4 for `c0` | P4 §5.3; BS:1326-1329 |
| Volume arc | from segment 35 clockwise 50 steps to 25, 2 % per segment | S01:164; S02 §1 |
| Tracks marks | Prev = 52+53, Neutral = 0, Next = 7+8 | S01:167 |
| Half-wash halves | left = segments 31–59, right = 1–29 (0 and 30 never lit) | S01:187; BS:655 |
| Offline marks | the 12 segments 0, 5, … 55 | S01:170 |
| LCD | 240 × 240 px, safe radius 104, headings to r 112 | R §3; S01:125 |
| Desktop | **units** on a 720-high stage; **k** = screen height ÷ 720 (k = 2 on the 5120 × 1440 G93SC, 100 % scaling); centred 1280 × 720 stage | S01 §11 |
| Durations | ms unless the name ends in `_s` | — |
| Colours | `0xRRGGBB` ints on the wire; `#RRGGBB` in docs | P4 §3 |

### 0.3 Id namespaces (so the four contracts never collide)

| Prefix | Owner | Meaning |
|---|---|---|
| `VOC-Nnn` / `VOC-Dnn` / `VOC-Rnn` | this file | naming resolution / deviation from r2.1 / ruling between sources |
| `P5-n` | K1 | K1's deviations. V4's deviations 1–9 are cited as `P4-1…P4-9` |
| `D1…D19`, `R1…R6` | K2 base (AL §12; carried in K2 §12.1–§12.2) | unchanged in meaning |
| `C2`, `F1/W2`, `W1`, `Q1` | K2 §12.5 (rev 4) | the round-2 integration records and the End-stop ruling Q1 (the round-2 review's ids; not 00's C1–C29 and not K2 §14's open questions Q1–Q2) |
| `M1…M31` | K2, master additions | the LED rulings A02 proposed as "D19–D29" and 00 as "D30", renamed because AL already uses **D19** (tick rounding, AL:501). Crosswalk: A02 D19→M1, D20→M2, D21→M3, D22→M4, D23→M5, D24→M6, D25→M7, D26→M8, D27→M9, D28→M10, D29→M11, 00 D30→M12. M13–M31 are K2's own (recorded in §13.3); **[r2.2]** M32–M33 are K2's r2.2 rulings (§13.3) |
| `C5-n` | K3 | K3's deviations, rulings and additions |
| `S5-n` | K4 | K4's deviations (not `S1…S5`, which are 00's supervised gates) |
| `VOC-K1a…`, `VOC-K4-nn` | K1, K4 | vocabulary additions proposed in K1 §16.4 and K4 §21.3; absorbed here (§16) |
| `X1…X12` | K2 §13.1 | K2's cross-doc change list (all applied, §15) |

Other ids are cited as their sources define them: 00 `U1–U14` (user decisions), `G1–G16` (gaps), `C1–C29` (contradictions), `A1–A10` (analysis disagreements); A02 `F1–F24`; RF0 `AR-1…AR-15`; 00 gates `A1–A7`, `S1–S5`, `L`, `H1–H6`, reads `R1–R5`, writes `W1–W5`.

---

## 1. Concepts, modes and layouts

### 1.1 The master table (one id per concept across every layer)

| Concept (user-facing) | Controller mode (K3, `Screen.mode`) | Wire `layout` token(s) (K1) | Display group | `page` meaning | Slide depth | LED family (K2) | Home family? | Knob art | Knob heading | Haptic profile · detents | Desktop surface (K4) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Home (now playing, volume reveal, idle row, notices) | **`home`** (renamed from v6 `volume`, VOC-N04) | `nowPlaying`, `volume`, `idle`, `notice` (unchanged) | `home` | — (0) | 0 | `home` | **yes** | now playing (not over `restLayout:"idle"`; never on `notice`) | — | BINARIS BEER · 67 | — |
| Recently Added (knob list) | `recent` | `recent` | `recent` | always 0 in v5 (flat list, U5) | 1 + page = **1** | `recent` | no | focused item | `RECENTLY ADDED` | MIDI SKIPPER · 20 | — |
| Music explorer (screen; knob mirrors) | **`explorer`** | **`explorer`** (new) | **`explorer`** | tab: **0 = Recently Added, 1 = Favourite playlists** | **30 + page** | **`explorer`** (new) | no | focused item (playlist: first mosaic cover) | `RECENT` / `FAVOURITES` | MIDI SKIPPER · 20 | `explorer` |
| Tracks (knob) | `tracks` | `tracks` | `tracks` | — | 1 | `tracks` | no | now playing | `TRACKS` | MIDI CLACK JONES · 8 | — |
| Seek (Tracks, button 3) | **`seek`** (sub-mode, parent `tracks`) | **`seek`** (new) | **`tracks`** (so enter/exit never slides) | — | 1 | `tracks` (the `transport` ↔ `lap` style change counts as MODE → Reveal) | no | now playing | `SEEK` | **BINARIS BEER** · 67, 5 s per detent | — |
| Up next (screen; knob mirrors) | **`upnext`** | **`upnext`** (new) | **`upnext`** | — | **30** | **`upnext`** (new) | no | focused row's cover | `UP NEXT` | MIDI SKIPPER · 20 | `upnext` |
| Windows (picker on screen; knob mirrors) | `windows` | `windows` | `windows` | — | 5 | `windows` | no | none (cover fades out on entry) | — | MIDI SKIPPER · 20 | `picker` |
| PC not connected (knob-local) | — (no session) | — (firmware screen) | — | — | — | `offline` (engine) / native profile lights | — | none | — | installed profile (native) | — |

Sources: R §3–§5; S01 §2–§3; A04 §2.1–§2.3 (depths, groups, families); 00 A1 (new tokens, not `recent` reuse); AL §5.4 (families); FD:772-789 (current groups/depths).

- **Slide rule (K1).** A screen change happens when `(group, page′)` changes, where `page′ = page` for groups `recent` and `explorer` and 0 otherwise. Content enters from **+20 px when `depth(new) ≥ depth(old)`**, else −20 px (380 ms OUT translate, 220 ms opacity; only the content layer moves; cover and footer stay; S01:156-157, App A). These depths reproduce every r2.1 flip (A04 §2.3 table): Recent→Explorer +, tab 0→1 +, tab 1→0 −, Explorer→Recent −, Tracks/Seek→Up next +, Up next→Tracks −, any Play→Home −, Windows→Home −, hold→Home −. Tracks↔Seek: same group, instant layer swap, no slide. The knob LCD runs at **60 fps**, translate and opacity only (no layer scaling), slides ≤ 20 px, fades ≥ 120 ms, covers swap instantly (R §3, §5; S01 §3); under `reducedMotion` it fades only (220 ms).
- **Home family** (LEDs: `playing` accepted, PLAY/PAUSE fill/drain, song hand, external blue, paused-Play breath): exactly `nowPlaying`, `volume`, `idle`, `notice` (AL §3 `playing` row; PR `ALIVE_PLAYING_LAYOUTS`). Every other layout, including the new ones, must be mapped explicitly: today `cc_alive_family` and the FD clamp default unknown layouts to Home (FA:246-253; FD:1252; A04 §10 risks 9).
- **Tint families** (ambient +0.06 of the cursor accent): `recent`, `explorer`, `upnext`, `windows` (BS:634; A02 F15).
- **D7-wash families** (plain `ok` after leaving a coloured list washes in the previous accent): `recent`, `explorer`, `upnext`, `windows` (A02 F12/F15; 00 §3.2 "Up next Play washes"). With hybrid Play (§4) most starts use `moment:"started"` instead.
- **PC not connected has two halves with different triggers in cc5.4** (VOC-R23): the **LEDs** enter the offline state after **every** release and at power-up (Going offline drain → 12 AMBER marks → native profile lights on native input; K2 §8.1; user decision); the **LCD** shows the offline screen (`Waiting for PC`, §9.2 `knob.title.offline`) **only after a lost host** (lease expiry); an intentional release and power-up keep the native screen (K1 §8.10, P5-11). K1 OQ-3 is **settled jointly by K1 and K2 for cc5.4**: the two triggers stay as they are; after an intentional release the ring shows the waiting marks while the LCD shows the native screen, until the first native input hands the ring to the native profile lights, which then last until the next claim (K2 M29). A later release may add `{"release":true,"offline":true}` if the user wants `Waiting for PC` after a quit (K1 §18 OQ-3; K2 §8.1).

### 1.2 Enum append order (binding for K1/K2; append only, never renumber)

| Enum (firmware / Python) | Existing values | Appended in v5 |
|---|---|---|
| `CCLayout` / `presentation.LAYOUTS` | 0 `nowPlaying`, 1 `volume`, 2 `idle`, 3 `recent`, 4 `tracks`, 5 `windows`, 6 `notice` | **7 `seek`, 8 `explorer`, 9 `upnext`** |
| display `Group` (FD:106) | 0 home, 1 recent, 2 tracks, 3 windows | **4 explorer, 5 upnext** (seek → tracks); **6 offline** (internal, the firmware-local offline screen, never a wire token; VOC-K1b) |
| `CCRingStyle` / `RING_STYLES` | 0 `off`, 1 `level`, 2 `selection`, 3 `transport` | **4 `lap`** |
| `CCIcon` / `ICONS` | 0 `""`, 1 `play`, 2 `pause`, 3 `list`, 4 `win`, 5 `tracks`, 6 `back`, 7 `home`, 8 `more`, 9 `prev`, 10 `next`, 11 `switch`, 12 `cancel` | **13 `expand`, 14 `clock`, 15 `playlists`, 16 `playnext`, 17 `seek`, 18 `shuffle`, 19 `heart`, 20 `snapleft`, 21 `snapright`** |
| `CCButtonTone` | 0 `none`, 1 `dim`, 2 `stop`, 3 `go`, 4 `nav` | **5 `on`, 6 `off`**, **[r2.2] 7 `liked`** (the liked heart, §2.3 row 4; derived on the knob, never on the wire) |
| button `lit` (new field) | — | 0 absent, 1 `on`, 2 `off` (**[r2.2]** unchanged: a liked row is still `heart` + `lit:"on"`; no new wire value, VOC-R26) |
| feedback moment (new field) | — | 0 none, 1 `queued`, 2 `shuffle`, 3 `like`, 4 `unlike`, 5 `snap`, 6 `started`. **[r2.2]** 4 `unlike` is **retired**: no host sends it (Like is add-only, VOC-R26); the value stays **reserved** (append-only: never renumbered or reused), and a knob that receives it plays nothing (§4.2 row 6) |
| `CCAliveFamily` | 0 home, 1 recent, 2 tracks, 3 windows, 4 offline | **5 explorer, 6 upnext** |
| `CCAliveEffectType` | 0 boot, 1 down, 2 wake, 3 tick, 4 bound, 5 pending, 6 bloom, 7 fail, 8 sweep, 9 fill, 10 drain, 11 shimmer, 12 wash, 13 reveal, 14 press | **15 half, 16 scatter** (`CC_FX_TYPES` becomes 17) |
| `CCAliveRole` (engine-internal) | as AL | **7 `PINK`** (K2 §4, M25) |
| `CCAliveClass` (engine-internal) | as AL (1, 2, 3, 4, S) | **6 `P` (0.14), 7 `N` (0.70), 8 `Q` (0.45 in any role)** (K2 §4, §5.2) |

The C++ layout clamp `layoutId <= CC_LAYOUT_NOTICE` (FD:1252) must become `<= CC_LAYOUT_UPNEXT` (A04 §2.1).

---

## 2. Buttons

### 2.1 Wire fields per button (`frame.buttons[slot]`, exactly 4)

| Field | Type / range | Default | Meaning (v5) | Source |
|---|---|---|---|---|
| `label` | text ≤ 16 B | required | Host legend; on Home it is also the idle-row word (§2.4; ≤ 46 px at 12 px, VOC-D08). It is **not** a tooltip: the floating knob is click-through and has no tooltip or legend text (VOC-R24) | P4 §3; FK:47, :95 |
| `enabled` | bool | required | `false` = **dim** (0.14 LED, `#5A5A5A` ink). Always wins over `lit` and `color` | S01:48-50 |
| `icon` | token (§2.2) | required (v2+ senders) | The glyph **meaning** | P4 §3; 00 A10 |
| `lit` | `"on"` \| `"off"` | absent | Pairs and toggles only: explorer tabs, Shuffle, Seek-while-seeking, liked heart, assigned snap side. Absent = the derived tone. **[r2.2]** On `heart`, `lit:"on"` means **the focused row is liked** (add-only): the knob derives tone `liked` (PINK 0.30, filled `#A3244A` heart, §2.3 row 4); `lit:"off"` is never sent on `heart` (a not-liked row is plain `nav`) | A02 §8; 00 A2; R22 CH §1 |
| `color` | int 0…0xFFFFFF | 0 | **Meaningful only with `lit:"on"`**: the assigned snap side's app colour, sent **raw** (the knob applies `sat()`, §11). Never used for PINK (the knob supplies PINK for `heart`+`on`). The host stops stripping it for a presentation ≥ 5 knob (DV:362-363) | A02 §8; A04 §5.1 |

There is **no reason field on the wire** (VOC-R12). A press on a dimmed button still reaches the host (`kd`), which answers with the reason copy in `meta`/`status` and `feedback{kind:"err"}` (§2.6).

### 2.2 Icon tokens (wire meanings, glyphs from BS `I`/`HALF`)

Tokens are **meanings** (VOC-N06). Glyph paths are the r2.1 prototype's (BS:485-495), 24-unit grid, stroked unless noted. LCD sizes: **20 px** (stroke 2.3) footer; **26 px** (stroke 2.1) only for tokens that can appear in the Home idle row; **16 px** (stroke 2.3) only for the Tracks position row (00 §3.2 "icon masks trimmed per use"; A04 §3.3).

| Wire token | Meaning (r2.1 icon row, S01:52-69) | BS glyph key | Path (r2.1) | Masks | Where (Button n) | Status vs v4 |
|---|---|---|---|---|---|---|
| `""` | none (tone none: hidden, LED off) | — | — | — | PC not connected (knob-local) | unchanged |
| `back` | Back (chevron-left) | `back` | `M15 18l-6-6 6-6` | 20 | Button 1 everywhere except Home | glyph changed (was arrow) |
| `play` | Play | `play` | `M7 4.5v15l12-7.5z` | 20, 26 | Home 1 when paused; Button 4 in Recent, Explorer, Up next | path changed |
| `pause` | Pause | `pause` | `M8 5v14M16 5v14` | 20, 26 | Home 1 while playing | unchanged |
| `list` | **Browse music** (two beamed notes) | `note` | `M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z` | 20, 26 | Home 2 | glyph changed; meaning kept (v4 `list` = Browse) |
| `tracks` | **Tracks** (list, dots + lines) | `list` | `M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01` | 20, 26 | Home 3 | glyph changed; meaning kept |
| `win` | Windows (window with title bar) | `win` | `M3 5h18v14H3zM3 9h18` | 20, 26 | Home 4 (the F24 slot, §6) | glyph changed |
| `prev` | Skip back / Previous | `prev` | `M19 5v14l-9-7zM6 5v14` | 20, 16 | Tracks 4 when Prev selected; position row left | glyph changed |
| `next` | Skip / Next (skip-forward) | `tracks` | `M5 5v14l9-7zM18 5v14` | 20, 16 | Tracks 4 (Next selected, Neutral, Seek); position row right | glyph changed |
| `switch` | Switch (check) | `check` | `M20 6L9 17l-5-5` | 20 | Windows 4 | glyph changed |
| `expand` | Open on screen / Open Up next (four corners) | `expand` | `M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7` | 20 | Recent 2, Tracks 2, Seek 2 | **new** |
| `clock` | Recently Added (tab) | `clock` | `M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0` | 20 | Explorer 2 | **new** |
| `playlists` | Favourite playlists (tab; list-music) | `queue` | `M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3` | 20 | Explorer 3 | **new** |
| `playnext` | Play next (list-plus) | `next` | `M11 12H3M16 6H3M16 18H3M18 9v6M21 12h-6` | 20 | Recent 3 | **new** |
| `seek` | Seek (scrubber, ring handle at 65 %) | `seek` | **`M3 12h8.7M17.7 12H21M14.7 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z`** (r2.1 redraw, CH §7 #7; A04's r1 path is superseded) | 20 | Tracks 3, Seek 3 | **new** |
| `shuffle` | Shuffle | `shuffle` | `M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22M18 2l4 4-4 4M2 6h1.9c1.5 0 2.9.9 3.6 2.2M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8M18 14l4 4-4 4` | 20 | Up next 2 | **new** |
| `heart` | Like (stroked). **[r2.2]** Liked = the same path **filled**, in `#A3244A` (tone `liked`, internal mask `heartfill` below); r2.1's "pink ink, never filled" is withdrawn (R22 CH §1; R22 BS footer `{fill: I.heart, ink: '#A3244A'}`) | `heart` | `M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z` | 20 | Up next 3 | **new** |
| *(internal)* **`heartfill`** **[r2.2]** | Liked heart (footer, tone `liked`) | `heart` as a fill | the `heart` path, **filled** (`fill` white, no stroke; the mask is tinted `#A3244A`) | 20 | Up next 3 on a liked row | **new [r2.2], not a wire token** (K1 §9.1) |
| `snapleft` | Snap left | `rect` + `HALF.left` | stroke `M3 5h18v14H3z` + **fill** `M3 5h9v14H3z` | 20 | Windows 2 | **new; needs a filled path** (A04 §3.4) |
| `snapright` | Snap right | `rect` + `HALF.right` | stroke `M3 5h18v14H3z` + **fill** `M12 5h9v14h-9z` | 20 | Windows 3 | **new; needs a filled path** |
| *(internal)* `dotfill` | Tracks position centre | — | filled disc 6 px across at 16 px | 16 | position row centre | new, **not a wire token** |

**Legacy tokens** (kept in the parser, masks and `cc_legacy_icon` for v6 hosts on cc5.4; a v7 host never sends them): `home` (house, 20), `more` (plus, 20), `cancel` (×, 20, the only token that makes tone `stop`). Masks `ok`, `warn`, `usb` and the old `dot` are dead flash and are dropped (A04 §3.4 item 7). Desktop-only glyph ids (never on the wire): BS `note` (Generated-sleeve foot), `sleeve`, `album`, `dot`, `rect` (BS:485-494).

**Presentation-4 downgrade** (v7 host → cc5.3 knob, 00 A10 / A05 D8(i); K1 owns the final table): `expand`→`more`, `clock`→`list`, `playlists`→`list`, `playnext`→`more`, `seek`→`tracks`, `shuffle`→`switch`, `heart`→`more`, `snapleft`→`prev`, `snapright`→`next`; `lit`, `color`, `ring.now`, `ring.card`, `feedback.moment/side/color`, `reducedMotion` stripped (and no ALIVE field, `ledPink` and `ledVolFull` included, since those knobs lack `alive`); layouts `seek`→`tracks`, `explorer`/`upnext`→`recent` (page 0); ring `lap`→`off`. No hold on presentation 4 (no `kh`).

### 2.3 Tones: derivation, LCD ink, LED level

The knob derives one tone per slot; the host never sends a tone (A04 §2.10; AL §5.3). Order of evaluation (first match wins):

| # | Condition | Tone | LCD footer / idle ink | LED colour · awake level | LED resting | Source |
|---|---|---|---|---|---|---|
| 1 | `icon == ""` | `none` | hidden | off | off | P4 §5.9 |
| 2 | `!enabled` | `dim` | **`#5A5A5A`** (was `#4A4A4A`) | WARM · **0.14** | 0.04 | S01:49, :101; S03 override #17; C27 |
| 3 | slot 0 · `icon == cancel` (legacy only) | `stop` | `#FF8474` | RED · 1.0 | 0.12 | P4 §5.9; AL §5.3 |
| 4 | `lit == on` · `icon == heart` | **[r2.2] `liked`** (was `on` + PINK) | **[r2.2] filled heart (`heartfill`) in `#A3244A`** (was the stroked heart in `#FF285A`) | **[r2.2] PINK `255,40,90` · 0.30**, never `sat()` (was 1.0). Not the 0.14 `dim` level: the button still says "liked", not "broken" | **[r2.2] 0.04 (warm)** by the resting rule (awake 0.30 < 0.5) | S01:106; **R22 CH §1**; R22 S01 §2 "Button LEDs"; R22 BS footer `{c: PINK, a: 0.3, ink: '#A3244A'}`; VOC-R26 |
| 5 | `lit == on` · `color ≠ 0` | `on` + colour | `sat(color)` (VOC-D02) | `sat(color)` · **1.0** | 0.12 (warm) | S01:107; A02 §3.1 |
| 6 | `lit == on` | `on` | **`#FFFFFF`** | WARM · **1.0** | 0.12 | S01:102; BS:1233, :1291 |
| 7 | `lit == off` | `off` | **`#7A7A7A`** | WARM · **0.30** | **0.04** | S01:103; A02 F16 |
| 8 | slot 3 · `icon ∈ {play, prev, next, switch}` | `go` | `#6ED996` | GREEN `0,255,98` · **1.0** | 0.12 (warm) | S01:104; P4 §5.9 |
| 9 | Home family · slot 0 · `icon == play` (paused) | `go` + **paused-Play breath** | `#6ED996` | GREEN · 1.0 × `0.55 + 0.45·(0.5 + 0.5·cos(2π·t/2600))`, awake only | 0.12 × resting breath | S01:105; U1 (green; confirm on hardware); AL §5.3, §8.2; BS:617, :1247 |
| 10 | otherwise | `nav` | `#E6E6E6` | WARM · **0.70** | 0.12 | S01:100 |

- **Resting rule** (buttons): WARM at **0.12 if the awake level ≥ 0.5, else 0.04**, × time-of-day factor × resting breath (BS:620; A02 F16 replaces AL's "0.04 if dim"). **[r2.2]** The `liked` heart (PINK 0.30) therefore rests at WARM 0.04, like `off`.
- **[r2.2] A liked row's Button 3 stays `enabled`** (`heart` + `lit:"on"`): row 2 (`dim`) would win and draw WARM 0.14 with a `#5A5A5A` outline, which reads as broken. A press on it is refused by the host (`unlike_unavailable`, §2.6: Head shake + `Unfavourite in Music app` for 2.2 s) (R22 CH §1).
- **PC not connected:** buttons off (knob-local; the native profile lights take over on native input) (S01:108).
- **`ledStyle:"white"`** (Settings "Warm only", stored `"white"`): colour tones become WARM (row 5 → WARM 1.0 = `on`); GREEN, RED, PINK, BLUE and AMBER marks are kept (AL D16; A02 F22; PINK kept is VOC-R21).
- **Transients on buttons** (effects, not tones): press = that button +0.6·(1−u)² HOT, 220 ms; wash tints Button 4 at 0.55·fade; half-wash tints Button 2 (left) or 3 (right) at 0.6·fade without `amp` (S02 §7; BS:654-655; A02 F18).
- **Footer ink change:** crossfade 160 ms OUT on the LCD (S01 App A "Footer icon ink").
- **"Only Button 4 is green"**, the single exception being paused Home Play (R:74-75; S01:46; CH §7 #1).

### 2.4 Per-mode button map, in tokens and tones (v7 host, presentation 5)

| Mode | Button 1 (slot 0) | Button 2 (slot 1) | Button 3 (slot 2) | Button 4 (slot 3) |
|---|---|---|---|---|
| `home` | `pause` nav (playing) · `play` go+breath (paused) · dim `starting` / `nothing_playing` | `list` nav | `tracks` nav · dim `nothing_playing` | `win` nav (F24 source) |
| `recent` | `back` nav | `expand` nav | `playnext` nav · dim `src_*` / `sonos_shuffle` / `queueing` / `sonos_unavailable` | `play` go · dim `queueing` / `item_unavailable` / `sonos_unavailable` |
| `explorer` | `back` nav | `clock` `lit` on/off | `playlists` `lit` off/on | `play` go · dim `empty` / `loading` / `item_unavailable` / `sonos_unavailable` |
| `tracks` | `back` nav | `expand` nav · dim `src_*` | `seek` nav · dim `src_*` / `no_length` | `prev`/`next` go when Prev/Next selected · `next` dim `neutral` |
| `seek` | `back` nav (exits Seek first) | `expand` nav · dim `src_*` | `seek` `lit:"on"` | `next` dim `seeking` |
| `upnext` | `back` nav | `shuffle` `lit` on/off (on under Sonos shuffle) · dim `loading` | `heart` nav · `lit:"on"` (liked) → **[r2.2] tone `liked`: PINK 0.30, filled `#A3244A` heart** · dim `loading` / `likes_unknown` / `not_catalog` / `sonos_card` · **[r2.2]** a press on a liked row is always refused while the button stays enabled (`unlike_unavailable`: Head shake + `Unfavourite in Music app`, 2.2 s; K3 C5-63, C5-67); label `Like` / **`Liked`** | `play` go · dim `loading` / `sonos_card` |
| `windows` | `back` nav (warm, restores focus; never `cancel`) | `snapleft` nav · `lit:"on"`+`color` when the left side is assigned | `snapright` nav · `lit:"on"`+`color` when assigned | `switch` go · dim `closed` |

Sources: R §4; S01 §2 (map S01:71-81, availability S01:83-93); BS:1247-1284. This is the design's map; K3 §3.1 adds the busy and availability dims of K3 §2.3 and §3.2 (C5-3, C5-4) in its evaluation order, under §2.6's rules. Unassigned snap buttons are `nav`, not `off` (BS:1282; A02 §4.7). Legends (labels ≤ 16 B) are K3's, except the **Home labels, which are the idle-row words**: slot 0 **`Play` while its icon is `play`, `Pause` while it is `pause`** (the label follows the icon, so the idle row, which appears only while paused or with nothing playing, always reads `Play`), then `Browse` · `Tracks` · `Win` (S03 override #16, S03:15, with VOC-D08 replacing its `Play/Pause`). Every Home label must be **≤ 46 px** at 12 px Montserrat 500, the idle-row column (S03:134; K1 §8.6.3): `Play` 25.9, `Pause` 37.3, `Browse` 45.8, `Tracks` 39.4, `Win` 25.0 px.

### 2.5 Hold, F24 and press routing names

| Name | Definition | Source |
|---|---|---|
| **hold** | Button 1 still down 600 ms after its press. The press acts first; the hold then goes **Home** from any mode (closes any overlay; from Seek exits Seek; from Windows restores focus / applies the one-side completion, §7.3). No-op on Home with no overlay. **Timed by the firmware only** (VOC-D06): the host never times a hold, and there is no host fallback timer | R:74; S01:41; BS:891-899 |
| `kh` | Firmware long-press event for the raw button mapped to slot 0 only, at most one per physical press (§6.3). A long press that fires while the knob is **entering** is latched and sent right after the next `ready`, with that ready's id (K1 §11.2 step 5, P5-R10) | 00 A3, §3.2; A04 §6.1; K1 §11.2 |
| **F24 slot** | physical slot 3: **`windowsButton = buttonOrder[3]`**, the **raw** index mapped to slot 3 (`windowsButton` is raw, CC:229), never the literal 3. F24 is sent only while `windowsHidEnabled` (host: true only on `home`) **and** `frame.buttons[3]` is enabled with icon `win` (firmware guard, K1 §11.4) | 00 §3.2; A04 §6.2; K1 §11.4 |
| `hid` flag | `kd` carries `"hid":1` when that press also fired F24; the host drops exactly those edges | 00 §3.2; A05 §3 R1 |

### 2.6 Dim reason codes (host-side only; K3)

A press on a dimmed button: the host shows the copy in the knob's meta/status line for `reason_meta_ms` (2000) and sends `feedback{kind:"err"}` (Head shake) (R:76, :182; S01:50), unless the row says **ignored** (then only the firmware's Press moment plays: no copy, no shake). Recently Added Play next refusals also raise a toast (no overlay is open there) (S01:50).

**Which codes may be ignored.** r2.1 designs "ignored" only for Home 1 while `Starting…` (S01:86); R:76 and the acceptance line R:182 otherwise ask for a reason and a Head shake on every dimmed press. The other ignored rows follow the prototype (BS:851, :885, :953, :971, :1005, :1042) and are deviation **VOC-D07**. A code may be `ignored` only when **both** hold:
1. r2.1 gives it **no reason copy**: the S01 §2 availability table (S01:83-93) marks it "—" or does not list it, and App C has no string for it; and
2. the state that disables the button is **already visible on the screen where the press happens**: a busy line (`Starting…`, `Pausing…`, `Skipping…`, **[r2.2]** `Finding songs…` (was `Queueing…`), `Queueing… {k} of {n}`, `Loading…`, `Loading queue…`) or the Working comet of the operation in flight; the knob title that explains it (`Turn to choose`, `Shuffled by Sonos`, or an empty list's title: `Nothing recently added`, `No favourites yet`, `No eligible windows`); the Seek screen itself; the requested transport state's dimmed icon; or the open overlay's own content (its empty or loading state, or an Up next list with fewer than two upcoming rows).

Every other dim shows its reason and shakes. The rule is evaluated **per mode**: a code can be `ignored` where its state is on screen and need reason copy elsewhere. It also binds codes other contracts add; the K3 codes (K3 §3.2, C5-4) are checked in the second table below, and a code that fails condition 2 in a mode gets reason copy there (added through §9.5) and the shake (K3 C5-59).

| Code | Buttons | Condition | Knob copy (§9) | Head shake | Toast | Source |
|---|---|---|---|---|---|---|
| `starting` | Home 1 | a start is pending (`Starting…`) | — | ignored (S01:86; on screen: `Starting…` + comet) | — | S01:86; BS:953 |
| `nothing_playing` | Home 1, Home 3 | nothing playing (empty queue / no track) | `knob.status.nothing_playing` | yes | — | S03 idle row; VOC-R14 |
| `src_airplay` | Recent 3 · Tracks 2 · Tracks 3 | source class `airplay` | `knob.meta.playnext.airplay` · `knob.meta.upnext.airplay` · `knob.meta.seek.airplay` | yes | Recent 3: `toast.playnext.not_queue` | S01:87-90; BS:805-813 |
| `src_radio` | same | `radio` | `….playnext.radio` · `….upnext.radio` · `….seek.radio` | yes | Recent 3: `toast.playnext.not_queue` | same |
| `src_linein` | same | `linein` | `….playnext.linein` · `….upnext.linein` · `….seek.linein` | yes | Recent 3: `toast.playnext.not_queue` | same |
| `src_none` | same | `none` | `….playnext.none` · `….upnext.none` · `….seek.none` | yes | Recent 3: `toast.playnext.none` | same |
| `sonos_shuffle` | Recent 3 | Sonos native shuffle on | `knob.meta.playnext.shuffle` | yes | `toast.playnext.shuffle` | S01:87; BS:817 |
| `queueing` | Recent 3, Recent 4 | a Play next is inserting | — (meta already `Queueing… k of n`) | ignored (VOC-D07) | — | S01:87-88; BS:1005 |
| `no_length` | Tracks 3 | queue source but the duration is unknown, `SeekTime` is missing, or the duration exceeds **59,999 s** (K1 `LAP_COUNT_MAX`, P5-R11; K3 C5-51) | `knob.meta.seek.no_length` (added) | yes | — | S01:90, :199; CS §4.3 |
| `loading` | Up next 2/3/4, Explorer 4 | list or queue loading | — (on screen: `knob.meta.loading` / `knob.meta.upnext.loading` + comet) | ignored (VOC-D07) | — | S01:92-93, :336 |
| `likes_unknown` | Up next 3 | like states not loaded yet | `knob.meta.like.unknown` | yes (S01:50 rule; BS:824 omits the shake, lower precedence) | — | S01:50, :91, :348 |
| `not_catalog` | Up next 3 | row not an Apple Music catalog song | `knob.meta.like.not_catalog` | yes | — | S01:91; BS:823 |
| `sonos_card` | Up next 3/4 | focus on the "Sonos is shuffling the rest" card | — (on screen: title `Shuffled by Sonos`) | ignored (VOC-D07) | — | S01:92, :360; BS:822, :885 |
| `empty` | Explorer 4 | the list is empty | — (on screen: the overlay's empty state and the knob's empty title, e.g. `No favourites yet`) | ignored (VOC-D07) | — | S01:93, :313 |
| `item_unavailable` | Recent 4, Explorer 4 | item not playable | `knob.meta.item_unavailable` (added) | yes | — | S01:174; VOC-R14 |
| `sonos_unavailable` | Recent 3/4, Explorer 4 (K3 adds Home 1/3, Tracks 2/3/4, Up next 2/4) | Sonos unreachable (explorer still opens; 00 G12) | `knob.meta.sonos_unavailable` (added); on Home's `status` line its twin `knob.status.sonos_unavailable` (K3 C5-56) | yes | — | 00 G12 |
| `neutral` | Tracks 4 | position Neutral | — (on screen: title `Turn to choose`) | ignored (VOC-D07) | — | S01:77; BS:851 |
| `seeking` | Seek 4 | in Seek | — (on screen: the Seek layout) | ignored (VOC-D07) | — | S01:77; BS:971 |
| `closed` | Windows 2/3/4 | the highlighted window closed | `knob.meta.windows.closed` (retained) | yes | — | S04; CT copy |

**K3's added codes and scopes (K3 §2.3, §3.2; C5-3, C5-4), checked per mode against conditions 1–2 (K3 C5-59).** None of these has r2.1 reason copy, so condition 1 holds for all; condition 2 decides per mode. Reason copy is drawn on the current screen's `meta` line (`reason_meta_ms`, meta tone) with `feedback{kind:"err"}`:

| Code | Buttons (K3) | `ignored` where the state is on screen | Elsewhere: knob copy (+ Head shake) |
|---|---|---|---|
| `starting` (scope extended) | Home 1, Recent 3/4, Explorer 4, Tracks 3/4, Up next 2/4 | Home 1: status `Starting…` + Working comet (S01:86) | `knob.meta.busy.starting` (`Starting…`, the `meta` twin of `knob.status.starting`) |
| `queueing` (scope extended) | Recent 3/4, Explorer 4, Tracks 4, Up next 2/4 | Recent 3/4: meta **[r2.2]** `Finding songs…` / `Queueing… {k} of {n}` (S01:87-88; R22 CH §4) | the running Play next's own busy line as the reason: `knob.meta.playnext.progress`, or **[r2.2]** `knob.meta.playnext.resolving` (`Finding songs…`) during the lookup, before the first song is queued (VOC-R28) |
| `shuffling` (new) | Recent 3/4, Explorer 4, Tracks 4, Up next 2/4 | Up next 2/4: the Up next frame carries `activity:"pending"` while a shuffle runs (Working comet, K3 §5.6.4) | `knob.meta.busy.shuffling` (`Shuffling…`) |
| `transport_pending` (new) | Home 1, Tracks 4 | Home 1: the requested state's dimmed icon + status `Starting…` / `Pausing…`; Tracks 4 while its own skip is out: meta `Skipping…` | Tracks 4 while a Home play/pause is out: `knob.meta.busy.starting` / `knob.meta.busy.pausing` (`Pausing…`) |
| `nothing_next` (new) | Up next 2 | fewer than 2 upcoming rows (`U < 2`): the list shows it | `U ≥ 2` with fewer than 2 rows outside the Play-next block (`U_r < 2`, K3 C5-45): `knob.meta.shuffle.nothing` (`Nothing to shuffle`) |
| `loading` (scope extended) | + Recent 3/4 | everywhere it applies: meta `Loading…` (K3 §5.2.3) | — |
| `empty` (scope extended) | + Recent 3/4, Windows 2/3/4 | everywhere: title `Nothing recently added` / `No eligible windows` | — |
| `signin_expired`, `list_error`, `skip_unavailable` (new) | K3 §3.2 | never (they carry reason copy) | `knob.meta.signin_expired` (error tone), `knob.meta.library_error`, `knob.meta.skip.prev_unavailable` / `.next_unavailable` |
| `unlike_unavailable` (rev 4; a **press refusal, not a dim**) | Up next 3 on a liked row (**[r2.2]** always: `UNLIKE_STRATEGY = add_only` is final, VOC-R26; K3 §3.2, C5-63, C5-67) | never | `knob.meta.like.unlike_in_music` (**[r2.2]** `Unfavourite in Music app`, approved, 152.7 px) for **`like_fail_meta_ms` 2200** (R22 CH §1: 2.2 s, not `reason_meta_ms`), meta tone, + Head shake; the button stays `enabled` with `lit:"on"` = tone `liked` (PINK 0.30; a dim would win over `lit` and draw WARM 0.14, §2.1, §2.3) |

---

## 3. Ring

### 3.1 Wire styles and fields (`frame.ring`)

| Field | Type / range | Used by | v5 change | Source |
|---|---|---|---|---|
| `style` | `off` \| `level` \| `selection` \| `transport` \| **`lap`** | all | `lap` appended | A04 §5.1 |
| `value` | int 0…100 | `level`: displayed volume; required elsewhere (send 0) | — | P4 §4 |
| `index` | int 0…65535 | `selection`/`transport`: absolute selected entry; **`lap`: target seconds** | lap meaning | A02 §8 |
| `count` | int 0…65535 | `selection`: entries; `transport`: 3; **`lap`: duration D seconds (≥ 1)** | lap meaning | A02 §8 |
| `first` | int | `selection` window start; **v5 hosts always send it when `count > 20`**, = `clamp(index − 10, 0, count − 20)` (§3.4) | rule | VOC-R03 |
| `colors` | ≤ min(20, count−first) ints | `selection`: accent of entry `first+k` (raw; knob `sat()`s; 0 = warm) | — | P4 §4 |
| `unavailable` | bitmask | `selection`: gap bits; `transport`: bit0 Prev, bit2 Next. **Stripped silently by both parsers on layout `upnext`** (Up next rows have no unavailable state, BS:1318-1321); a v7 host sends 0 there | upnext strip | P4 §4; K1 §4.4, P5-R24 |
| `moreIndex` | int −1 | legacy (Recent More); a v7 host never sends it (U5) | retired | U5 |
| `external` | bool | `level`: changed on Sonos (BLUE) | — | P4 §4 |
| **`now`** | int −1…count−1 | **`selection` on layout `upnext` only**: absolute index of the now-playing row; −1/absent = none. Stripped on any other layout/style. Stored as `int32_t` (K1 P5-R25) | **new** | A02 F14; 00 A2; VOC-R16 |
| **`card`** | bool | **`selection` on layout `upnext` only**: `true` = the last entry (`count − 1`) is the "Sonos is shuffling the rest" card. Valid only with `count ≥ 2` and `now == count − 2`, else reject. **The only wire form of the card** (frozen): nothing else identifies it, never an `unavailable` bit. Host form: `count = P + 1`, `now = P − 1`, the card's `colors` slot 0 (K3 §5.6.4). Stripped with `now` elsewhere | **new** | K1 §4.1, §4.4, P5-R19, P5-R24 (VOC-K1a); K2 5.1.4 item 5 |

**Loading lists (K1 §4.6; K2 M31).** `activity:"loading"` means the **whole list** is not there yet (first page of Recently Added, a Favourite playlists tab with no cache, Up next before its first window). Its wire form is `ring.style:"off"` + `activity:"loading"` (a `selection` ring with `loading` draws the same: comet only). An entry that is not loaded yet **inside a list whose `count` is known** is not loading: it goes out as an ordinary entry with colour 0 (a warm landmark) and the list's own `activity` (`idle`, or `pending` while Play next runs), so the ring keeps its landmarks and the local cursor keeps working.

### 3.2 LED patterns at a glance (K2 owns the math)

"Pattern" is the LED rule; the wire style that carries it is in the second column.

| Pattern id | Wire | Where | Colour / level rules (awake → resting) | Source |
|---|---|---|---|---|
| `level` | `level` | Home | Bounds 35 and 25 WARM 0.30. Body from 35, **0.62 in every colour**: WARM; **AMBER when `v ≥ 80 ∧ k ≥ 40`**; **RED when `v ≥ 90 ∧ k ≥ 45`** (value **and** position gate). Endpoint 1.0 in its position's colour = cursor. **Odd volume: a 0.81 half-step** (placement VOC-R04). External: cursor±1 BLUE 1.0. Near-max embers on RED while awake and v ≥ 90. Pending span per P4 §5.2. Resting 0.05/0.10/0.13/0.16 | S01:164; U8; A02 F1-F3; BS:1305-1310 |
| `selection` | `selection` | Recent, Explorer, Windows | One landmark per entry, 3 segments apart, centred on 12 o'clock (window rule §3.4): **coloured item 0.45, warm item 0.30**; cursor 1.0 in its colour. Unavailable entry: landmark omitted, **cursor on it keeps the item's colour at 0.45** (VOC-R05). Loading list (the **whole** list, `style:"off"` + `activity:"loading"`): **no landmarks, only the Working comet** (VOC-R06; K2 M31). An unloaded entry of a known list is a colour-0 entry: a warm landmark 0.30, the cursor on it WARM 1.0 (K2 M31). Empty list: send style `off`. Warm is allowed only in transient moments (comet, pulses, sparks), never as a static mark in a coloured list. No More | S01:165, :172-175; CH §7 #19; BS:1326-1329 |
| `upnext` | `selection` + `now` on layout `upnext` | Up next | Landmarks in each row's **album** colour: **played (`j < now`) 0.14, now-playing (`j == now`) 0.70, upcoming 0.45 in any colour** (no warm test); cursor 1.0. 20-entry window (§3.4). Loading (before the first window lands): comet only; placeholder rows after that are colour-0 entries (upcoming: 0.45, class Q). The Sonos-shuffle card is the `ring.card` entry `count − 1` (§3.1, VOC-K1a): **no landmark and no cursor cell**; moments start at its slot (K2 M14). Resting: 0.05 / 0.10 / 0.05 / 0.16 | S01:166; A02 §3.2, F14; BS:1317-1321; K2 5.1.4 |
| `transport` | `transport` | Tracks | 52+53, 0, 7+8 at WARM 0.30; selected pair 1.0; Neutral selected 0.62. Cursor: **Prev 52** (VOC-D04), Neutral 0, Next 8. Always warm | S01:167; P4 §5.4 |
| `lap` | **`lap`** | Seek | The song as one lap from 12 o'clock: head `n = min(59, ⌊index·60 / count⌋)` (integers); `k < n` WARM **0.62**; `k > n ∧ k mod 5 = 0` WARM **0.30**; other `k > n` unlit; head WARM **1.0** = cursor. All warm. Drawn awake (not the resting Song hand). The `transport ↔ lap` change fires MODE (Reveal) | S01:168; A02 §4.5, F19; BS:1311-1314 |
| `off` | `off` | empty lists, notices without a ring | all dark; cursor 0 for moments | P4 §5.5 |
| `offline` | (knob-local) | PC not connected: after **every** release and at power-up (K2 §8.1; the LCD half has its own trigger, VOC-R23) | Going offline drain, then 12 AMBER marks (0, 5, … 55) at 0.12 × `0.6 + 0.4·sin(2π·t/2600)`; native input hands the LEDs to the native profile lights **until the next claim** (AL D5's 5 s return of the marks is withdrawn, K2 M29) | S01:170; S02:20; AL §8.1; K2 §8.1, M29 |

### 3.3 Level ladder and floating-knob glow looks

| Level | Used for | Ring resting | Button resting | Glow look (floating knob, 1× size) |
|---|---|---|---|---|
| 1.00 | cursor, endpoint, lap head, `go`, `on`, snap colour (**[r2.2]** the PINK heart moved to 0.30) | 0.16 | 0.12 | **18 px** |
| 0.81 | odd-volume half-step (class S) | 0.13 | — | **15 px** |
| 0.70 | `nav` buttons; Up next now-playing (class N) | 0.10 | 0.12 | nearest → 12 px |
| 0.62 | volume body, Neutral selected, lap played (class 2) | 0.10 | — | **12 px** |
| 0.45 | coloured landmark (class 1 semantic); Up next upcoming and the unavailable list cursor (class Q, any role) | 0.05 | — | **10 px** |
| 0.30 | warm landmark, bounds, lap ticks, `off` buttons (class 1 warm); **[r2.2]** the `liked` heart button (PINK) | 0.05 | 0.04 | **8 px** |
| 0.14 | Up next played (class P), `dim` buttons | 0.05 | 0.04 | **6 px** |
| 0.12 | offline marks (× offline breath) | — | — | nearest → 6 px (the 0.14 look) |

The six glow looks are pre-rendered sprites, only faded and tinted, never reshaped per frame; levels in between use the nearest look (S02 overrides; BS:479 `GLL`/`GLB`). The px values are **BS canvas px** (BS's ring is 318 px across); on the desktop they scale by the ring's outer diameter in physical px ÷ 318 (1.1321 here: radii 6.79 … 20.38 px, σ = radius / 2) (K2 §10.3 item 3; K4 §11.3). The look is picked per frame from the **rendered** level `mx` of the composed segment or button (after breath, effects and tone map), not from the target level (BS:677, :690). Resting values are then × time-of-day factor × resting breath `1 + 0.4·sin(2π·t/5200)` (S02 §3, §5).

### 3.4 The 20-entry window rule (selection and upnext)

- **Transmitted window:** `first = 0` when `count ≤ 20`, else **`first = clamp(index − 10, 0, count − 20)`** ("focus 10 from the window start, clamped at the ends", S01:166; BS:1319, :1326). A v5 host **always sends `first`** for `count > 20`; V4 parsers accept it (`0 ≤ first ≤ index < first + 20`, FPA:214-218). The absent-`first` derivation stays V4's `clamp(index − 9, …)` for legacy senders.
- **Landmark geometry:** `c0 = first + ⌊(min(20, count) − 1) / 2⌋`, `slot(j) = ((j − c0)·3) mod 60` for `j ∈ [first, first + min(20, count))`. For `count ≤ 20` this equals V4 exactly; for longer lists the window is re-centred so the landmarks scroll under a cursor that stays near 12 o'clock, instead of V4's absolute slots that wrap every 20 entries (VOC-R03).
- Applies to every selection ring (Recent flat list, explorer tabs, Windows, Up next) (CH r2.1 "lists longer than 20 use the 20-entry ring window").

### 3.5 Accent sources (what goes into `colors[]`, `buttons[j].color`, `feedback.color`)

| Accent id | Value | Used for | Source |
|---|---|---|---|
| `album` | `dominant()` of the album cover (seeded by Apple `bgColor` while loading); **no-art items use the Generated-sleeve palette accent** | Recent, Explorer Recently Added, `started` | S01:292-295; CH r2.1; BS:541-546 |
| `playlist` | `dominant()` of the **first** mosaic cover | Explorer Favourite playlists, `started` | 00 §3.2 "Data" |
| `row` | the row's album colour (Play-next rows keep their own album) | Up next | S01:166; A02 §4.6 |
| `window` | `dominant()` of the app icon; monochrome apps → warm (0) | Windows, snap button, `snap` moment | S01:169; S02 §2 |
| — | 0 = no accent = WARM | any | P4 §4; AL §2 |

All accents travel **raw**; the knob applies `sat()` (S02 §2; AL §2). **PINK is never an accent and never `sat()`'d** (R:100; S01:106).

---

## 4. Feedback

### 4.1 Fields (`frame.feedback`)

| Field | Type / range | Rule | Source |
|---|---|---|---|
| `kind` | `"ok"` \| `"err"` | required when present | P4 §3 |
| `seq` | int 1…0x7FFFFFFF | a new value triggers exactly one moment; seeded without effect after a claim | P4 §5.8; AL §6.4 |
| `skip` | −1 \| 1 | only with `ok`: knob-initiated Tracks skip | AL §3 |
| **`moment`** | `queued` \| `shuffle` \| `like` \| `snap` \| `started`; **[r2.2]** `unlike` is retired (reserved token: still parsed, never sent, plays nothing; §1.2) | only with `ok` (stripped otherwise); mutually exclusive with `skip` | A02 §8; VOC-R07; R22 CH §1 |
| **`side`** | −1 (left) \| 1 (right) | only with `moment:"snap"` | A02 §8 |
| **`color`** | int 0…0xFFFFFF, 0 = warm | only with `moment:"snap"` or `"started"`; raw, knob `sat()`s | A02 §8; VOC-R07 |

### 4.2 What each feedback plays (K2 order of evaluation)

| # | Feedback | LED effect | Parameters | Target flash (cursor±2) | Knob copy typically sent with it | r2.1 reference trigger |
|---|---|---|---|---|---|---|
| 1 | `err` | `fail` (**Head shake**) | at the new cursor | err flash | the failure/reason copy | every failure or blocked press (S01:190) |
| 2 | `ok` + `skip ±1` | `sweep` | at the **previous** cursor, `dir = skip` | ok flash (unchanged) | `{i} / {n}` | Tracks 4 (BS:855; 00 §3.2 LED) |
| 3 | `ok` + `queued` | `sweep` **from segment 0, clockwise** | `at = 0`, `dir = +1` | **none** | `knob.meta.playnext.ok` | Play next done (S01:185; BS:1021) |
| 4 | `ok` + `shuffle` | `scatter` | `seed` from the shared PRNG (VOC-R18) | none | `knob.meta.shuffle.on` / `.off` / `.sonos` | Shuffle on **and** off (BS:879) |
| 5 | `ok` + `like` | `bloom` in **PINK** | at the Up next cursor; spark `mix(PINK, white, 0.3)` | none | `knob.meta.like.on` | Like lands (S01:188; BS:829) |
| 6 | `ok` + `unlike` — **[r2.2] retired**: no host sends it (there is no unlike, R22 CH §1). Kept only as a guard for the reserved token: it plays **nothing** (no green bloom, no flash) | nothing | — | none | — (**[r2.2]** `knob.meta.like.off` / `Like removed` is withdrawn) | BS:829; R22 CH §1 |
| 7 | `ok` + `snap` | `half` (**Half-wash**) | `side`, `sat(color)` (0 → WARM); tints Button 2/3 | none | `knob.meta.snap.left_set` / `.right_set` | Snap accepted (S01:187; BS:1088) |
| 8 | `ok` + `started` | `wash` in `sat(color)` at the current (Home) cursor; `color` 0 or `sat()`→warm → green `bloom` | `color` = the item's accent (§3.5) | none | Home status cleared / `knob.status.partial` | start confirmed after the knob is already Home (S01 §4d; BS:998, :888) |
| 9 | `ok` (no moment), previous family ∈ {recent, explorer, upnext, windows} with a non-warm accent | `wash` in that accent at the previous cursor (AL D7 extended) | — | ok flash | — | Windows Switch (BS:1095) |
| 10 | any other `ok` | green `bloom` ("Confirmed") | at the new cursor | ok flash | — | Switch to a warm app (00 §3.2: green bloom, F11) |

- **Flash rule:** the v4/AL target flash (ok GREEN / err RED on cursor±2) is **suppressed whenever `moment` is present** (A02 F13 → K2 M7). Rows 2, 9, 10 keep AL's behaviour.
- **Silent success:** actions whose success the design shows without a moment send **no feedback**; they only clear `activity:"pending"` (the Working comet stops): Seek landing (S01:202; **[r2.2]** "landed" = playback resumed, and only after the last follow-up jump, VOC-R27), volume confirmation, Play/Pause (fill/drain come from `playing`, AL §6.4 #3).
- **When** the host sends each ok (on acceptance or on verified completion) is K3's confirmation policy (00 U11 hybrid for starts; VOC-D03). K1/K2 only guarantee: a new `seq` plays the row's effect once.

---

## 5. LED moments and continuous layers

| Design name (S01 §4, S02 §7) | Engine token | Trigger (event / frame) | Dur ms | FG | Reduced motion (S01 §10) | Status in v5 | Source |
|---|---|---|---|---|---|---|---|
| Coming online | `boot` | `claim` / power-up | 2800 | yes | kept | existing (LCD fade omitted, AL D6) | S02 §7 |
| Going offline | `down` | `release` | 1800 | yes | kept | existing | S02 §7 |
| Wake | `wake` | first input while resting | 520 | no | **skipped** | existing | S02 §7; CH §7 #14 |
| Spin trail | `tick` | detent that moves the position | 180 | no | **skipped** | existing | S02 §7; AL D4 |
| End stop | `bound` | haptic end stop (`lim`): **every push into a bound** (K2 ruling Q1, rev 4), not only the first after arriving | 460 | no | kept (screen bump skipped) | existing; also Seek ends (0:00, T_end); **trigger changed** (Q1) | S01:180, :201; AL D4; K2 §12.5 |
| Working | *(layer)* comet | while `activity` pending/loading (incl. Home pending volume). **[r2.2]** The host must keep `pending` for the **whole** Play next job (the `Finding songs…` lookup included, VOC-R28) and for **every** Seek jump until playback resumes, across a follow-up jump (VOC-R27): the comet never gaps (R22 CH §3, §4; K2 M33) | 1400 / lap | — | kept | existing | S01:191 |
| Confirmed | `bloom` (GREEN) | plain `ok` (§4.2 row 10) | 900 | yes | kept | existing | S02 §7 |
| **Like bloom** | `bloom` + colour **PINK** | `moment:"like"` | 900 | yes | kept | **changed** (colour parameter) | S01:188; BS:656; A02 §6.2 |
| Head shake | `fail` | `err` | 700 | yes | **stationary red throb** (`pos = at`) | existing; motion, exempt from the 3 Hz rule | S01:190; S02 overrides; BS:658 |
| Play | `fill` | `playing` false→true on two Home frames | 760 | yes | kept | existing | AL D8 |
| Pause | `drain` | `playing` true→false | 860 | yes | kept | existing | AL D8 |
| Skip | `sweep` | `skip ±1` | 640 | yes | **skipped** | existing | S01:184 |
| **Play-next sweep** | `sweep` (`at 0`, `dir +1`) | `moment:"queued"` | 640 | yes | **skipped** | **new trigger** | S01:185; BS:1021 |
| Changed elsewhere | `shimmer` | `ring.external` false→true | 1000 | yes | kept | existing | S02 §7 |
| Near max | *(layer)* embers | Home, awake, v ≥ 90, RED segments | — | — | kept | existing | S02 §7 |
| Song hand | *(layer)* | resting, Home, `playing` | 1 lap / song | — | kept | existing | S02 §7; AL R3 |
| Mode change | `reveal` | family change, **or `transport` ↔ `lap`** | 450 | no | **skipped** | **new trigger** (Seek; explorer/upnext families) | S01:182; BS:698, :836, :848; A02 F19 |
| Ambient tint | *(layer)* | families recent/explorer/upnext/windows, awake | τ 220 | — | kept | **more families** | BS:634 |
| Switched · now playing | `wash` | §4.2 rows 8–9 | 1100 | yes | kept | new triggers (`started`, explorer/upnext) | S01:186 |
| **Half-wash** | `half` | `moment:"snap"` | 900 | yes | kept | **new** | S01:187; BS:655; A02 §6.1 |
| **Scatter** | `scatter` | `moment:"shuffle"` | 700 | yes | **skipped** | **new** (r2.1 spread recipe) | S01:189, :194; BS:657 |
| Button press | `press` | any button down (claimed) | 220 | no | kept | existing | S02 §7 |
| **Seek lap** | *(pattern, not an effect)* | layout `seek`, ring `lap` | — | — | — | **new pattern** (§3.2) | S01:168 |
| Paused-Play breath | *(button layer)* | Home family, slot 0 `play` enabled, awake | 2600 cycle | — | kept (brightness, < 3 Hz) | existing (green, U1) | S01:105 |
| Offline breath / resting breath | *(layers)* | offline / resting | 2600 / 5200 | — | kept | existing | S02 §5 |

- **FG** = foreground: starting one kills running FG effects (linear 120 ms fade) and ducks the base by `0.35·sin(πu)·amp` (S02 §5). BS's FG list is `fill, drain, sweep, wash, half, bloom, scatter, fail, down` (BS:484); AL adds `boot`, `shimmer` (AL §7).
- **Reduced motion on the knob** needs the knob to know the setting: latched frame field `reducedMotion` (§6.2, VOC-R09). BS skips exactly `wake, sweep, scatter, reveal, tick` (BS:579) and makes `fail` stationary (BS:658).
- **3 Hz rule:** nothing modulates *brightness* above 3 Hz; the Head shake is spatial motion and exempt (R:106; S02 overrides; K2 M12).

---

## 6. Wire messages

### 6.1 Host → knob commands (one JSON object per line)

| Command | Shape (v5) | Reply | Notes / source |
|---|---|---|---|
| capabilities | `{"capabilities":"?"}` | `{"capabilities":{…}}` (§6.5) | CC; P4 §1 |
| diag | `{"diag":"?"}` | `{"diag":{…}}` | P4 §1; additive v5 fields. K2 (§10.1): `ledFps`, `ledRenderUsMax`, `ledRenderUsAvg`, `ledMode` `alive`\|`offline`\|`native` (`native` lasts until the next claim, M29), **`ledShowGapMsMax`**, **`ledLateShows`**. K1 (§12.3, VOC-K1c): `lcdFps`, `lcdFpsAnimMin`, `lcdRefrUsMax`, `lcdRefrUsAvg`, `lcdRenderUsMax`, `lcdFlushUs`, `lcdPxPerRefr`, `lcdFullRefrs`, `lcdLateRefrs`, `lcdMaxGapMs`, `lcdBusyPct`, `core0IdlePct`, `lcdSpiHz`, `enterMsLast`, `enterMsMax`, `holdEvents`, `holdDeferred`, `lcdDma`, `lcdPeriodMs`, `artAsync`, `artDecodeRequests`, `artDecodeAborts`, `artDecodeStale`, `stackArtDec`, **[E-lcd]** `lcdMosiSig` (integer; 103 = the LCD data line is FSPID, 102 = binary A's defect) and `build` (`"A"`…`"E"`, absent without a ladder id). The three build flags `CC_LCD_DMA`, `CC_LCD_PERIOD_MS`, `CC_ART_ASYNC` (reported as `lcdDma`, `lcdPeriodMs`, `artAsync`) identify the pipeline of binary **A / B / C**; **[E-lcd]** `CC_BUILD_BINARY` (reported as `build`) names the binary, **D** (A's pipeline) and **E** (C's) included (K1 §12.6, §12.6.1, VOC-K1f) |
| **control** (enter) | `{"control":{"id":n,"profile":"…","min":0,"max":0…65535,"position":p,"windowsButton":0…3,"windowsHidEnabled":bool,"buttonOrder"?:[…],"frame":{…}}}` | `{"ready":id,"p":pos,"ks":mask}` | Every host-driven move (tab switch at 190 ms, Shuffle at 200 ms, Play at 380 ms, snap advance at 420 ms, Seek on/off, Back from the explorer) is a new control (00 G2). v7: **`windowsButton = buttonOrder[3]`** (raw, §2.5; K1 §11.4), `windowsHidEnabled = (mode == home)` |
| **frame** | `{"frame":{"id":n,…}}` | none (renews the lease) | presentation only; never moves a detent (P4 §0) |
| release | `{"release":true}` | `{"released":true[,"reason":"forced"\|"lease-expired",…]}` | CC |
| media (artwork2) | `{"media":{"id":n,"op":"begin"\|"data"\|"commit"\|"have","kind":"cover"\|"icon",…}}` | exactly one `{"mediaAck":{…}}` | AW2 §4 (240 px JPEG covers, 32 × 32 icons) |
| art (v1) | `{"art":{…}}` | `{"artAck":{…}}` | legacy; never while artwork2 is negotiated |
| *(latched frame fields, not commands)* | `clock`, `progress`, `ledDrive`, `ledDither`, **`reducedMotion`**, **`ledPink`**, **`ledVolFull`** | — | there is **no `clock` command**; the clock rides in frames (AL §3); the two tuning fields are §6.2 (K2 §3.2, M24; K1 §7.3) |
| refused while claimed | `updates`, `current`, `save`, `load`, `R`, `recalibrate`, `profiles` (list), `settings` (object) | `{"error":"Release control center before changing device configuration"}` | CC |

### 6.2 Frame fields new or changed in v5 (sent only to a knob with `presentation ≥ 5`; K1 owns validation)

| Field | Type | Scope | Notes |
|---|---|---|---|
| `layout` | + `seek`, `explorer`, `upnext` | — | §1 |
| `page` | 0…255 | `recent` (always 0 in v5), `explorer` (tab 0/1) | §1.1 |
| `heading` | text ≤ 32 B | — | `RECENTLY ADDED`, `RECENT`, `FAVOURITES`, `UP NEXT`, `TRACKS`, `SEEK` (all ≤ 138 px; may reach r 112) |
| `ring.style` `lap` (`count` 1…`LAP_COUNT_MAX` = 59,999), `ring.now`, **`ring.card`**, `ring.first` rule, `ring.unavailable` stripped on `upnext` | §3.1 | — | K1 §4 (VOC-K1a, VOC-K1e) |
| `buttons[j].lit`, `buttons[j].color` | §2.1 | — | — |
| `feedback.moment/side/color` | §4.1 | — | — |
| `metaTone` / `statusTone` `error` | ink **`#FF8474`** in v5 | — | VOC-R10 |
| **`reducedMotion`** | bool, **latched** | sent in every `control` frame and in the next frame after the effective setting changes | knob LCD: no slides, fades only (220 ms), volume reveal opacity-only; LEDs: §5 (VOC-R09) |
| ALIVE fields | `clock` 0…1439 (latched), `playing` (Home family), `progress{pos,dur}` ms (latched), `feedback.skip`, `ledDrive` 1…255, `ledDither` (latched; unset = off since the 2026-09-26 user ruling, K2 9 step 4, 12.7) | — | AL §3, unchanged |
| **`ledPink`** | JSON int **0…0xFFFFFF** (never a bool, float or string), **latched** (like `ledDrive`); **0 = the built-in PINK constant** (the same meaning as the engine's `set_tuning(…, 0, …)`); an invalid value follows K1 §3.3 rule 2 (firmware rejects the frame, host strips and logs) | tuning only; all layouts; sent only to a knob with `presentation ≥ 5` **and** the `alive` capability (cc5.4); gated with the ALIVE rows (K1 §3.1) | The LED colour (0xRRGGBB at full drive) the ring emits for PINK; the engine sets PINK = per-channel OETF(channel/255) and the spark `mix(PINK, white, 0.3)` of it. Absent keeps the latched value; it survives releases and claims, and only a reboot returns to the PINK constant. The host sends it **only when settings.json has `led_pink`** (an int, or a `"#RRGGBB"` string that `device.py` converts), in every enter frame; **no UI**. It exists to pick PINK on the ring in the one hardware window (K2 §3.2, §14 Q2, M24; 00 U13) |
| **`ledVolFull`** | JSON bool (never an int or string), **latched** (like `ledDither`); same lifetime and validation as `ledPink` | as `ledPink` | `true`: the semantic (AMBER/RED) volume body and half-step use 1.00 instead of 0.62 / 0.81 (the U8(b) alternative); `false`, or never sent since boot: 0.62 / 0.81 (U8(a), the default). Sent **only when settings.json has `led_vol_full`**, in every enter frame; no UI. For the U8 A/B in the hardware window (K2 §3.2, §5.2, M1, M24) |

Both tuning fields are latched in the same struct as `reducedMotion` and the ALIVE fields (K2 §3; K1 §3.6, §7.3), but unlike `reducedMotion` (reset at every claim) they are kept until reboot. They count toward K1's latched reserve: **+38 B** worst case (`,"ledPink":16777215` 19 B + `,"ledVolFull":false` 19 B), so K1's worst frame (Windows) is 1,352 B, under `FRAME_BUDGET_BYTES_V5` = 1,400 (K1 §14.1). K1 carries their parsing, storage and fixtures (K1 §3.1, §3.6, §7.3, §15.1). `tools/nanod_alive_tour.py` sends them directly while the companion is quit (K2 §3.2).

**Seek field mapping (recommended to K1, A04 §2.2):** heading `SEEK`; `title` = song title (14 px caption); the **48 px `m:ss`** is formatted by the firmware from `ring.index` in the tabular face `cc_font_48t` (digits + `:`; minutes unpadded, seconds 2 digits); the 14 px line = host text in `meta` (`of m:ss` / `Jumping…` / `Didn’t jump · try again` with `metaTone:"error"` / `Stops 3 s before end`).

### 6.3 Knob → host messages

| Message | Shape | When | Source |
|---|---|---|---|
| ready | `{"ready":id,"p":pos,`**`"ks":mask`**`}` | after motor, HMI and LCD applied a `control`; **`ks` new in v5** (bitmask of raw buttons down at ready) | CC; 00 A3; A04 §6.1 |
| position | `{"id":id,"p":pos}` | a detent within the ready control | CC |
| key down | `{"id":id,"ks":mask,"kd":raw[,`**`"hid":1`**`]}` | button pressed; `hid:1` when that press also fired F24 | CC; 00 §3.2 |
| key up | `{"id":id,"ks":mask,"ku":raw}` | button released | CC |
| **hold** | `{"id":id,"ks":mask,`**`"kh":raw`**`}` | **new**: AceButton long press at 600 ms (fires ≈ 620–640 ms after contact), only for the raw button mapped to slot 0, at most once per physical press, claimed path only (native branch ignores it). A long press that fires while the knob is **entering** is latched (one slot) and sent **right after the next `ready`** with that ready's id, if the button is still down; a key-up, release or new claim clears it (K1 §11.2 step 5, P5-R10) | A04 §6.1; VOC-D06; K1 §11.2 |
| limit | `{"id":id,"lim":-1\|1}` | end-stop push while ready, ≤ 1 per 150 ms; **every push** into a bound, re-armed after the knob has been off the bound for `lim_rearm_ms` (K2 ruling Q1, rev 4) | AL §3; K2 §6.2, §12.5 |
| released | `{"released":true[,"reason":…,"unacked":[…],"leaseExpired":true]}` | session ended | CC |
| error | `{"error":"…"}` | invalid command | CC |
| acks | `{"artAck":{…}}`, `{"mediaAck":{…}}` | per art/media line | AW2 §4 |

Events are tagged with the current control id and emitted only after its `ready`; never replayed after release or reconnect (CC "Tagging").

### 6.4 Host device events (`device.py` → `runtime.py`)

Existing: `connected`, `disconnected`, `ready` (`id`, `p`, `position`), `position` (`delta`), `button` (`index`, `button`, `pressed`), `limit` (`id`, `dir`), `released`, `media-ready`, `media-error`, `artwork-ready`, `artwork-error`, `error`, `closed` (DV:1078-1949). New in v7: **`hold`** `{"kind":"hold","id":id,"button":<logical index>}` from `kh` (the only source of a hold, VOC-D06); `button` gains **`hid: bool`**; `ready` gains **`held: <logical mask>`** from `ks`, used to re-seed the host's pressed mask (K1 §11.3), never to time a hold.

### 6.5 Capabilities (v5 knob)

`presentation: 5` (was 4; a v6 host still works because it tests `>= 4`, DV:182, :200, :444) and `alive: {version: 1, fps: 60, drive: n}` (00 §3.2 "Capability"). **Presentation 5 implies `kh`, `ks` in `ready`, the new tokens, layouts, fields and `reducedMotion`**; no separate `keyHoldMs` key (VOC-R17). Every other key unchanged (`artwork`, `artwork2`, `glyphs: "latin-ext-a"`, `diag: 1`, `windowsHidKey: "F24"`, `composited: "scrim80"` kept, A04 §2.7).

---

## 7. Desktop surfaces

### 7.1 Surface and scene ids

| Surface id | What | Host / engine (K4) | Focus | Full-width layers | Parent knob mode on close | Floating-knob suppression reason |
|---|---|---|---|---|---|---|
| `explorer` | Music explorer overlay | **stage scene** on the shared DirectComposition host (`NanoD-stage` thread, full-monitor non-activating window); compositor-run animations | never | blur `blur.explorer`, tint, ambient A↔B | `recent` | **`explorer`** |
| `upnext` | Up next overlay | stage scene (same host) | never | `blur.upnext`, tint, ambient A↔B | `tracks` | **`upnext`** |
| `picker` | Window picker + snap tray | **v6 carousel host kept** (activatable, DWM thumbnails); GIL/pacing fixes; chrome to the GPU later (VOC-D05) | **takes focus** | `blur.picker_frost` or `blur.picker_none` | `home` | `carousel` (existing name kept, CAR §11) |
| `toast` | glass pill | v6 toast window, now a **service** used by knob actions | never | — (own `blur.toast` snapshot) | — | none |
| `knob` | floating knob | `overlay.py` layered window; LED engine on the overlay thread; composed **every vblank (240 Hz)** while visible; **while hidden: no loop and no timer, one engine render per posted frame or input (after ≤ 60 catch-up steps of 50 ms), never composed or presented** (K2 M27; K4 §11.2); ring only, no button strips (K2 M30); click-through, no tooltip (VOC-R24) | never | — | — | (is the subject) |
| `settings` | Settings window (Tk) | Tk | normal | — | — | none |
| `settings_strip` | Settings status strip (Knob · Sonos · Apple Music) | inside `settings` | — | — | — | — |
| `tray` | tray icon + menu | pystray (`standalone.py`) | — | — | — | — |

There is **no main window** (user decision; R:42; S01 §12). Sources: R §7; S01 §5–§12; RF0 §2.0–§2.5; 00 §3.2 "Overlays"; FK §4; CAR §11.

**Blur recipe ids** (S01 App B, fixed per surface, never animated; radii at the 720-unit reference × k): `blur.explorer` (36 px, sat 1.3, tint `rgba(8,8,10,0.50)`, ambient 0.50), `blur.upnext` (36 px, 1.3, `rgba(8,8,10,0.55)`, ambient 0.45), `blur.picker_frost` (40 px, 1.6, `rgba(10,10,12,0.50)`, no sheen), `blur.picker_none` (flat `rgba(0,0,0,0.55)`, label shadow `0 1px 2px /0.6`), `blur.toast` (24 px, 1, `rgba(24,24,26,0.62)` + 1 px `rgba(255,255,255,0.2)`). Settings value for the picker background stays `picker_background` = `"glass"` (Frosted, default) \| `"none"` (UI:117).

**Artwork state ids** (explorer, Up next, knob): `art.full` (1200 px, sharp), `art.extended` (Extended sleeve: sharp cover ≤ 1.5× on a radial gradient of its own dominant colour), `art.generated` (Generated sleeve: hashed two-tone 160° gradient + Archivo 800 title; ring uses the palette accent), `art.loading` (Apple `bgColor` fill + title/artist in `textColor1`, 240 ms crossfade in), `art.list_loading` (neutral `#232325` cards, label/dots hidden), `art.mosaic` (2 × 2 of the first 4 distinct albums), `art.single` (full-bleed first album when < 4 distinct). Request sizes: **1200** (big covers and ±1), **600** (side cards, mosaic tiles, old-album floor), **240** (rows; the knob's 240 px artwork2 JPEG), **64** (ambient source), Sonos `/getaa` **400** (S01:278-304; CH r2.1; 00 G5; LC). App B's "Small-art mat" row and S01 §6's "small-art mat" wording mean `art.extended` (VOC-R20). The knob's 240 px covers are composited and rendered by WP6 `artwork.py` (the r2.1 scrim; `art.loading` and `art.generated` without text) (K3 §10.5, C5-58; K1 §8.4).

**Item art keys** (host-internal, never on the wire; VOC-K4-03, adopted by K3 C5-57): `art_template` (Apple `{w}x{h}` template), `art_max` (int px, `min(width, height)`), `art_bg` (int `0xRRGGBB`, Apple `bgColor`, 0 = none), `art_ink` (int, Apple `textColor1`, 0 = none), `sonos_art` (the row's Sonos `/getaa` URL; on every Up next queue row, used when the row has no Apple art; renamed from v6 `art_url`), `mosaic` (≤ 4 descriptors: the first 4 distinct albums **with art**, in track order) (K4 §13.2; K3 §5.6.3, §9.6.1, §9.8.6, §9.8.8).

### 7.2 Floating-knob suppression reasons (`overlay.set_suppressed(reason, on)`)

| Reason | Held while | Status |
|---|---|---|
| `disconnected` | the knob is disconnected | existing |
| `picker` | a rect-less (Tk) picker overlaps the knob, Windows mode only | existing (legacy path) |
| `carousel` | the `picker` surface is open (either background) | existing |
| **`explorer`** | the `explorer` scene is open | **new** (00 §3.2; A05 §5.7 proposed `explorer`) |
| **`upnext`** | the `upnext` scene is open | **new** (A05 proposed `queue`; VOC-N02) |
| *(check, not a reason)* | full-screen D3D / presentation mode (`SHQueryUserNotificationState` 3/4) | existing, checked at slide-in |

### 7.3 Overlay close reasons (lifetime ids; K3/K4)

| Reason id | Applies to | Trigger | Toast after close | Knob goes to | One-side snap completion (U12) | Source |
|---|---|---|---|---|---|---|
| `back` | all | Button 1 | picker one side filled: `toast.snap.one_side`; else none | parent (§7.1) | **applied** | S01:79, :408-411; BS:1056-1062 |
| `hold` | all | hold (§2.5) | none | `home` | **applied** | BS:893-898 |
| `play` | explorer, upnext | Button 4; overlay closes at 380 ms | `toast.start.*` after the start resolves, ≥ 360 ms after close | `home` (`Starting…`) | — | S01 §4d; BS:884-890, :1040-1045 |
| `switch` | picker | Button 4 | `toast.switch` | `home` | — (Switch activates only) | BS:1092-1097 |
| `pair` | picker | both sides filled; closes at 820 ms | `toast.snap.pair` | `home` | — | S01:406 |
| `lock` | all | screen lock / session to the lock screen | **none** | parent | **applied** | S01:426; BS:900-905 |
| `sleep` | all | suspend (`PBT_APMSUSPEND`) / display off | none | parent | applied | S01:426 |
| `idle` | all | **60 s** without knob input | none | parent | applied | S01:426 |
| `disconnect` | all | knob lost (device `disconnected` / `closed` / `error` / `released`) | none | no host mode; **knob-local**: `Waiting for PC` **only after a lost host** (lease expiry); the **native screen** after an intentional release or a power-up (K1 §8.10, P5-11; VOC-R23). LEDs: offline state after any release (K2 §8.1) | **not applied** | S01:429; BS:909 |
| `focus_lost` | picker | external focus change | none | `home` | **not applied** (the user took over) | CAR §1; VOC-R15 |
| `group` | explorer, upnext | Sonos group change | none | parent | — | 00 G9 (addition) |
| `foreground` | explorer, upnext | external foreground change | none | parent | — | 00 G9 (addition) |
| `source` | upnext | the source leaves the Sonos queue | none | `tracks` | — | S01:323 (addition) |
| **`display`** | all | **presenter-initiated**: monitor configuration or DPI change while open (stage host `system(display)`; picker `EV_DISPLAY`); the presenter closes instantly and posts `closed(surface, "display")` | none | parent | **not applied** (the half rects are stale) | K4 §4.3, §15; VOC-K4-01 (addition) |
| **`device`** | explorer, upnext | **presenter-initiated**: the stage's Direct3D/DirectComposition device was lost; instant close, `closed(surface, "device")` | none | parent | — | K4 §4.3, §15; VOC-K4-01 (addition) |

Exit toasts start **360 ms after** the overlay closes; toasts raised while an overlay is open are **dropped** (the knob meta carries that feedback) (S01 §8).

### 7.4 Host effect kinds (controller → runtime / presenter; K3 owns payloads) and presenter events

- **Service effects = the service op ids of §8** (1:1): `play_items`, `play_next`, `seek`, `shuffle_reorder`, `set_shuffle`, `queue_window`, `jump`, `move_next`, `like`, `unlike` (**[r2.2] withdrawn**: never emitted, §8.3), `ratings`, `favourite_playlists`, `playlist_meta`, `catalog_songs`, `recent`, `recent_lookahead`, `resolve`, plus existing `state`, `volume`, `transport` (K3 §10.1, C5-28).
- **[P2a] Internal effect `resolve_drop`** (K3 §10.1, C5-75), controller → runtime only, neither a service op nor a presenter effect: payload `keep: [{kind, id}]` (the new Recently Added focus and its loaded neighbours). The controller emits it at a detent that leaves a sent pre-resolution outside the focus ± 1; the runtime prunes the lookahead lane's queued pre-resolutions to `keep` (the running one finishes into the cache). Never posted to a presenter, never sent to the knob, no result.
- **Presenter effects:** `explorer_open`, `explorer_close`, `explorer_source`, `explorer_highlight`; `upnext_open`, `upnext_close`, `upnext_highlight`, `upnext_rows`; existing `windows_open`, `windows_highlight`, `windows_activate`, `windows_cancel` (= Back; name kept), `windows_hide`; new `windows_snap`, `windows_close_pair`; `toast`; existing `device_enter`. Every call posts to the presenter's newest-wins mailbox and returns (K4 §2.3); K3 pushes the payloads with every field K4 §2.3 requires (K3 §11.1, C5-53).
- **`t0`** (payload field of every timed presenter effect): the controller's clock at the press or event that caused the effect, in seconds of **`time.perf_counter`** (QPC), the one clock K3 and K4 share (K4 §0.6). The presenter anchors every scheduled leg to it (`t0` + 190, 200, 360, 380, 820 ms), never to the time the post arrives (K4 §4.6.4; K3 §6.2). Other payload fields added with it: `items_first`, `state` (explorer: `loading` \| `ready` \| `empty` \| `signin` \| `error`, the displayed state of the active source), `sonos_available`, `card`, `count`, `close_at_ms` (380 for `play`, else 0), `place_at_ms` (360).
- **`upnext_rows` reasons** (one enum in K3 and K4; K3 C5-54): **`data`** (rows or enrichment land, incl. the first heart states; hearts set **without** a pop), **`likes`** (a confirmed like, `[{row, liked:true}]`; the heart pop. **[r2.2]** There is no unlike and no heart-off animation, R22 CH §1), **`shuffle`** (the new order; rows fade out at `t0` and re-enter at `t0 + 200`), **`queue_changed`** (a re-read after a revision change or a failed shuffle; re-render in place).
- **Presenter events (presenter → controller; K4 §2.3 names them, K3 consumes them):** `opened(surface)`; `closed(surface, reason)` (reason from §7.3); `click_action(surface)`; **`refused(surface, reason)`** with reason **`busy`** (another overlay is registered, K4 §2.4) \| **`device`** (the stage could not start or create its device, K4 §4.1-§4.2); `system(kind)` with kind `lock` \| `sleep` (suspend or display off) \| `display` \| **`motion`** (the Windows *Animation effects* setting changed; K4 §4.1, K3 §14.3); `snap_result(side, outcome)` with outcome **`accepted`** (the ≤ 5 ms pre-checks passed, K4 §9.5 t = 0) then `ok` \| `move_rejected` \| `cant_fit` (placement), or at once `hung` \| `move_rejected` (pre-check failure) (§8.5); **`cancel_result(restored, completed)`** (two bools, answering `windows_cancel`: focus restored; the U12 one-side completion done). `surface` is a §7.1 id (`explorer`, `upnext`, `picker`). There is no `display_off` kind. K3 exposes **one entry point** for all of them, `presenter_event(event)` (K3 §2.5; VOC-R22).
- **What the controller does with a presenter-initiated end** (VOC-R22): `closed(surface, display|device)` → the knob re-enters the parent mode (§7.1) with no toast, no reason copy and no U12 completion (§7.3); `refused(surface, busy|device)` → the knob leaves the mode it entered at the press and re-enters the parent mode (explorer → `recent`, upnext → `tracks`, picker → `home`), sends `feedback{kind:"err"}` (Head shake) and shows `knob.meta.stage_unavailable` (**[r2.2]** `Couldn’t open on screen`) for `reason_meta_ms` (§9.5); `busy` is also logged (it means the one-overlay guard of K3 failed). Either way the knob never keeps mirroring an overlay that is not on screen.
- **Never replayed after a reconnect** (`invalidate_actions`): every write op (`volume`, `transport`, `play_items`, `play_next`, `seek`, `shuffle_reorder`, `set_shuffle`, `jump`, `move_next`, `like`; `unlike` **[r2.2]** withdrawn) (RT:1165; A05 §2.6).

---

## 8. Services

### 8.1 Sonos source classes (drive availability and copy)

| Class | Meaning | Mapping | Source |
|---|---|---|---|
| `queue` | the Sonos queue is the source (`x-rincon-queue:`), PLAYING or PAUSED_PLAYBACK | — | A06 §4.2; RP |
| `airplay` | AirPlay stream | — | S01:87 |
| `radio` | radio and any other non-queue stream (Apple Music radio, service streams, unknown non-queue URIs) | catch-all for streams | S01:87 |
| `linein` | line-in **and TV/HDMI** | `x-rincon-stream:`, `x-sonos-htastream:` | S01:87 ("line-in / TV") |
| `none` | nothing playing: STOPPED, no track, or an empty queue | — | S01:87 |

### 8.2 Sonos operations (`SonosAdapter`, group coordinator, `rev` = expected group revision, `track` = expected track id)

| Op id | Args | One-line semantics | Status | Source |
|---|---|---|---|---|
| `read_state` | — | Adds `playlist_position`, `duration`, `position_s` + read time, `source` class, `play_mode` (`shuffle`, `repeat`), `can_seek` (`"SeekTime"` offered ∧ duration > 0 ∧ PLAYING/PAUSED), queue `update_id`/`total` | extended | A06 §7; CS §4.3 |
| `play_items` | items, rev | Replace the queue and play. **Albums all-or-nothing; playlists play the playable subset** and report `k of n` | existing, leniency changed | U6; S01 §4d |
| `play_next` | items (≤ 100), rev, track | `AddURIToQueue` per song with **`DesiredFirstTrackNumberEnqueued = P+1+i`** (`EnqueueAsNext = 0`, never `EnqueueAsNext`); only when the source is `queue` and Sonos shuffle is off; newest block goes directly after the current song; verified by read-back. **Live (rev 4, LC W1):** inserts land exactly at P+1, P+2 while playing, 522 / 560 ms each; the new rows carry Sonos artist, album and art. Its songs come from the resolve cache when the item was **pre-resolved** (K3 C5-66), so the inserts start at once. **[r2.2] Knob progress:** `Finding songs…` during the Apple lookup and until the first song is queued (never `Queueing… 0 of {n}`), then `Queueing… {k} of {n}` at ≈ 0.5 s per song, the Working comet throughout; 1–10 s in all is fine (R22 CH §4). Timings recorded: R22 BS cached lookup ≈ 0.4 s, uncached ≈ 4.5 s, 0.5 s per song; live (LC W1) uncached 3.07–6.25 s, inserts 522 / 560 ms (VOC-R28) | new | R §8; CP §4.1; 00 C3; K3 §9.3; R22 CH §4 |
| `seek` | seconds, rev, track | `Seek(REL_TIME)`, target clamped to **`T_end = D − 3`**, sent 250 ms after the last detent. **[r2.2] Landed = playback has resumed**: the transport has **left `TRANSITIONING`** (a position report is never evidence, even one at the target); **no resume within `seek_confirm_ms` = 8000 → failure**; never resent. Turning during a jump moves the frozen target, and **at most one follow-up jump** (the latest target) is sent when the current one lands, still 250 ms after the last detent; `Jumping…` and the Working comet hold from the first send until the last jump lands (R22 CH §3; VOC-R27; K3 C5-68). Superseded rev 4 wording: **confirmed when the transport has left `TRANSITIONING` and the position reads within ±2 s of the target, within 5 s, never resent** (rev 4, K3 C5-65: live 2.64 / 2.69 s to leave `TRANSITIONING`, RelTime at the target from the first read while still buffering; the knob clock stays frozen at the target with `Jumping…` until then; the polls yield to short jobs). **[r2.2] Still in force** (not superseded): a pending target is **flushed** on an explicit exit (Button 1/2/3, hold) and **dropped** on a track, group or disconnect change (a track change also exits Seek) (K3 C5-47); **[P2a]** a start (`play_items`, `jump`) also drops a follow-up target still waiting after Seek was left (K3 C5-77); Seek is offered only for `D ≤ 59,999 s` (K3 C5-51) | new | S01 §4b; CS §4.2-4.4 |
| `shuffle_reorder` | on, rev, track | **Companion shuffle** for **≤ 60 upcoming rows** (`U`, every upcoming row): permute rows P+1…T with guarded single-row `ReorderTracksInQueue` moves (Sonos shuffle stays off), persisted restore record (base rows only). **A Play-next block stays directly after the current song on "on" as well as "off"** (R:142; BS:873-878): it goes first, only the other `U_r` rows are shuffled (`U_r ≥ 2`). The playing position is read last before every move; no row at or before the playing row ever moves, and the plan continues after a song that ends mid-reorder; a jump elsewhere stops it (`queue_changed`, record kept). Off restores the recorded order behind the Play-next block; refuses if the queue changed (`queue_changed`). **[P2a]** Off takes the ledger's Play-next units `[song_id, start_row]` (plain ids still accepted) and attributes the rows in two passes (units by the ledger's position rule, then the record first per signature), so ~~the restored order equals the controller's preview~~ the adapter puts first the same Play-next rows as the controller's preview; the base rows follow in their order at Shuffle on (the record), which the preview (the ledger's start order; **[P3]** only when the controller does not know the record: with the record known the preview ranks the base rows by the record's order, the order the adapter restores, K3 C5-79) matches only when they still stood in it: **[P2a]** not after a reorder without a ledger entry (an Up next `move_next` of an upcoming row, another Sonos app), not on a queue the companion did not start, and not with a played Play-next row outside the loaded window; the re-read after the job shows the true order (K3 §9.5.3 limitations, C5-73) | new | S01 §6 "Shuffle"; A06 §3.4; U4; K3 §9.5, C5-45, C5-50, C5-73, **[P3]** C5-79 |
| `set_shuffle` | on, rev | **Sonos native shuffle** (`SetPlayMode` NORMAL↔SHUFFLE_NOREPEAT, REPEAT_ALL↔SHUFFLE, REPEAT_ONE↔SHUFFLE_REPEAT_ONE) for **> 60 upcoming rows** | new | S01 §6; A06 §3.2 |
| `queue_window` | start, count (21 around the focus) | Windowed `Browse(Q:0)` + `update_id`/`total_matches`; re-read only when `update_id` or `Track` changes | new | A06 §4.3 |
| `jump` | row, rev, track | Up next Play: `Seek(TRACK_NR, row)` + Play. **[P2a]** Played when the transport has left `TRANSITIONING` and reads PLAYING at `row` (or ≥ 1.0 s after the reply when no `TRANSITIONING` was seen), within `seek_confirm_ms` 8000, else `start_failed`: the Seek landing rule (VOC-R27), not a 2 s read-back; its polls yield to short jobs on the audio lane, never to a `seek`: a start drops a waiting Seek follow-up (K3 §9.6.2, §1.1, C5-74, **[P2a]** C5-77) | new | A06 §4.3; K3 C5-74 |
| `move_next` | row, rev | Like fallback ("Play next for this row"): upcoming row → `ReorderTracksInQueue` to P+1; played row → re-insert its share link at P+1. **[r2.2]** Still the documented fallback, and still only if the favourites API becomes unavailable; add-only Like does not trigger it | new (fallback only) | S01:353; A06 §5.5; R22 S01 §6 |
| `set_volume`, `transport` | existing | unchanged | existing | — |

### 8.3 Apple Music operations (`AppleMusicClient`; GETs plus the new `_send(method, path, json, expected_status)`)

| Op id | Request | One-line semantics | Status | Source |
|---|---|---|---|---|
| `like` | **`POST /v1/me/favorites?ids[songs]={catalogId}`**, no body → **202** (empty); then `ratings` read-back until value 1 (every 250 ms, ≤ 4 s) | Gives the song the **Favorite star on the user's devices** (verified live 2026-09-25 22:06 UTC: the star appeared on the iPhone; rating 1 after ≈ 1 s). **Never `PUT /v1/me/ratings`**: it stores the same server values but never reached the iPhone (rev 4, K3 C5-62) | new, **changed** (rev 4) | R §8; LS; LC; K3 §9.8.2 |
| `unlike` | **[r2.2] Withdrawn: there is no unlike request.** `UNLIKE_STRATEGY = add_only` is **final** (**[r2.2]** R22 CH §1: "Proposal confirmed…", "Removed: the unlike moment…"; LS: "Conclusion for the build (UNLIKE_STRATEGY = add_only)"): the web player's `DELETE /v1/me/favorites?ids[songs]={id}` was sent once with the user's approval (2026-09-25 16:03 PDT) and Apple refused it, **HTTP 400, code 40012 "Insufficient Permissions"**, 333 ms, nothing changed (LS); `DELETE /v1/me/ratings` clears the server but not the devices. The `favorites_delete` branch, the settings override and the outcome `unlike_unsupported` are withdrawn; a press on a liked row is refused (`unlike_unavailable`, §2.6). Rev 4 text, superseded: by **`UNLIKE_STRATEGY`** ∈ {`favorites_delete`, `add_only`}, default **`add_only`**: `add_only` sends nothing (the press is refused, `unlike_unavailable`); `favorites_delete` sends `DELETE /v1/me/favorites?ids[songs]={catalogId}` then a `ratings` read-back until no rating; 400/405 → `unlike_unsupported` (the session falls back to `add_only`) | Removes the star only where it provably reaches the devices. **Never `DELETE /v1/me/ratings`** (it cleared the server but the iPhone kept the star, LS 22:42–23:01 UTC) and **never value −1** ("Suggest Less"). The favourites `DELETE` was not sent (blocked); live check W4b decides the default (rev 4, K3 C5-63) | new, **changed** (rev 4) | LS; A06 §5.2; K3 §9.8.2 |
| `ratings` | `GET /v1/me/ratings/songs?ids=` (≤ 100) | **The one source of heart state** (rev 4, K3 C5-64): Up next rows, like read-backs (**[r2.2]** no unlike read-back exists), the late check; `liked = (value == 1)`; unrated ids are absent (200 or 404 both mean "none") | new | A06 §5.2; CF §5; LS |
| `favourite_playlists` | `GET /v1/me/library/playlists?limit=100&extend=inFavorites&filter[inFavorites]=true`, own pager; full scan / ratings fallbacks | The favourited playlists **including Favorite Songs**, sorted by name; sync lag of minutes; no "pinned" source | new | CF §5; U7 |
| `playlist_meta` | ~~`GET /v1/me/library/playlists/{id}/tracks?limit=100&include=catalog` (first page; all pages for the focused playlist's duration)~~ **[P3]** `GET /v1/me/library/playlists/{id}/tracks?limit=50&include=catalog` (K3 §1.2's parse cap): the first 100 tracks are the window of the mosaic and the count (a second page only when the first 50 hold fewer than 4 albums with art, or without `meta.total`; WP6-GIL-D3); the focused playlist's duration reads every page up to `META_MAX_TRACKS` 10,000 tracks (200 pages), else `duration_ms` None (WP6-GIL-D5) | Count (`meta.total`), the mosaic (first 4 distinct albums with art), the first art and accent seed, the duration | new (K3 C5-28) | K3 §9.8.8, **[P3]** §1.2; CF §5 |
| `catalog_songs` | `GET /v1/catalog/{sf}/songs?ids=` (~~≤ 300; ≤ 50 if K4's `gil_parse_hold.py` bench shows a parse holding the GIL > 1 ms, K4 §4.7.3~~ **[P3]** at most **50 ids per request** (`CATALOG_BATCH`): the bench measured 300 ids at 1.85–3.29 ms and 50 at 0.26–0.49 ms; K3 §1.2, §9.8.4; K4 §4.7.3) | `albumName`, `trackNumber`, `discNumber`, `durationInMillis`, `artwork` (incl. `bgColor`, `textColor1`) for Up next rows; **rev 4: no `extend=inFavorites`** (hearts come from `ratings`, K3 C5-64) | new | A06 §4.3, §5.4; K3 §9.8.4 |
| `recent` / `recent_lookahead` | `GET /v1/me/library/recently-added` pages | **Recently Added pager** feeding one **flat list** (no More), prefetched around the focus; the pager re-applies its own params (Apple's `next` drops them) and takes counts from `meta.total` | existing, semantics changed | U5; 00 G3 |
| `resolve` | ~~`GET /v1/me/library/{albums\|playlists}/{id}/tracks?include=catalog&limit=100` for **both** kinds, with the **own-params pager** (every page re-sends `include=catalog&limit=100` plus the `offset` taken from `next`, whose own query drops them)~~ **[P3]** `GET /v1/me/library/{albums\|playlists}/{id}/tracks?include=catalog&limit=50` for **both** kinds (K3 §1.2's parse cap: a 100-row page held the GIL 0.92–1.55 ms, 50 rows 0.43–0.71 ms; WP6-GIL-D1), with the **own-params pager** (every page re-sends `include=catalog&limit=50` plus the `offset` taken from `next`, whose own query drops them); `limit=300` is not used; 20 s deadline for the whole resolve (≈ 2,200 tracks at 50 per page) | Maps an album or playlist to catalog songs; albums strict, playlists lenient (`k of n`); cached (LRU 64, TTL 1800 s). **Rev 4: pre-resolution** of the focused Recently Added item and its neighbours 400 ms after the last detent, on the lookahead lane, lowest priority (K3 C5-66); live uncached 8-track album 3.07–6.25 s | existing, changed | 00 G3; U6; K3 §9.8.7, C5-37, C5-52, C5-66 |

### 8.4 Windows operations (`windows.py`; K4)

| Op id | Semantics | Source |
|---|---|---|
| `snap` | Place a window in the monitor work-area half, on the `NanoD-snap` worker, reaching the target **only through posted calls**: **non-activating restore** with `ShowWindowAsync(hwnd, SW_SHOWNOACTIVATE)` (4) when iconic or zoomed (≤ 150 ms poll); then `SetWindowPos(…, SWP_NOZORDER \| SWP_NOACTIVATE \| SWP_NOOWNERZORDER \| SWP_ASYNCWINDOWPOS)` (0x4214) with `DWMWA_EXTENDED_FRAME_BOUNDS` compensation; verify the rect (≤ 200 ms, UWP ≤ 400 ms). **Never `SW_RESTORE`**, never `SetWindowPlacement`, `ShowWindow` or a synchronous `SetWindowPos` on the target (each can wait on a busy target's thread). Runs once at 360 ms under the overlay and resolves by a **hard deadline of t0 + 800 ms** (else `move_rejected`); a failed snap puts the window back with posted calls only, and a window that **was maximized comes back restored at its normal rect, never re-maximized** (every maximize command activates; K4 S5-32) | S01:403, :412; VOC-D01; A05 §6.4; K4 §9.6, S5-1, S5-32 |
| `close_pair` | Both sides placed → close at 820 ms; raise the side snapped **first** with a posted `SetWindowPos(HWND_TOP, …, SWP_NOACTIVATE \| SWP_ASYNCWINDOWPOS)`, then focus the side snapped last | S01:406; 00 U12; K4 §9.7 |
| `complete_one_side` | On a close that applies U12 (§7.3): the window that had focus at open takes the other half, with the `snap` recipe, resolved by its start + **600 ms** | S01:408-411 (U12 confirmed); K4 §9.6 |

### 8.5 Outcome codes (service results → knob copy, toast, LED)

| Code | Produced by | Knob copy | Toast (after close / when no overlay) | LED |
|---|---|---|---|---|
| `ok` | all | op's success copy | op's success toast | per §4.2 |
| `partial` | `play_next` | `knob.meta.playnext.partial` | `toast.playnext.partial` | `err` |
| `nothing_added` | `play_next` | `knob.meta.playnext.nothing` | `toast.playnext.nothing` | `err` |
| `song_changed` | `play_next`, `seek`, `jump` | `knob.meta.playnext.song_changed` (Play next); Seek: exits Seek silently | `toast.playnext.song_changed` (Play next) | `err` (Play next) |
| `not_queue_source` | `play_next`, `seek`, `queue_window` | per source class (§2.6) | Play next: `toast.playnext.not_queue` / `.none` | `err` |
| `sonos_shuffle_on` | `play_next` | `knob.meta.playnext.shuffle` | `toast.playnext.shuffle` | `err` |
| `playlist_partial` | `play_items` (playlist) | `knob.status.partial` (3 s) | `toast.start.partial` | `ok` + `started` |
| `album_blocked` | `play_items` (album) | `knob.status.album_blocked` | `toast.start.album_blocked` | `err` |
| `start_failed` | `play_items`, `jump` (incl. the staging deadline `6 + 0.15·N` s and the 20 s resolve deadline, K3 C5-37) | `knob.status.start_failed` | `toast.start.failed` | `err` |
| `not_confirmed` | `seek` (701/711/timeout; **[r2.2]** timeout = no playback resume within `seek_confirm_ms` 8000) | `knob.line.seek.failed` (2.2 s; stays in Seek) | — | `err` |
| `queue_changed` | `shuffle_reorder` (restore refused, or a jump elsewhere mid-reorder) | `knob.meta.shuffle.queue_changed` (added) | — (overlay open) | `err` |
| `not_catalog` | `like` | `knob.meta.like.not_catalog` | — | `err` |
| **`unlike_unsupported`** (rev 4) — **[r2.2] withdrawn** (no unlike request exists, §8.3) | — (was `unlike` under `favorites_delete`: Apple 400 / 405) | — (was `knob.meta.like.unlike_in_music`) | — | — |
| `signin_expired` | Apple 401/403 | Like: `knob.meta.like.signin_expired`; a list: `knob.meta.signin_expired` (K3 C5-56); Settings strip Apple Music problem state | `toast.like.signin_expired` after a `back` close | `err` |
| `rate_limited` / `failed` | Apple 429 / other; rev 4: also a like whose `ratings` read-back does not match within 4 s (K3 §9.8.2) | `knob.meta.like.failed` (added; **[r2.2]** `Didn’t save · try again`, error tone, `like_fail_meta_ms` 2200, with the Head shake, R22 CH §1); shuffle: `knob.meta.shuffle.failed` | — | `err` |
| `sonos_unavailable` | any Sonos op | `knob.meta.sonos_unavailable` (added); on Home `knob.status.sonos_unavailable` | — | `err` |
| `group_changed` | any Sonos op (`GroupChanged`) | Home: `knob.status.group_changed`; elsewhere `knob.meta.group_changed` (both **[r2.2]** `Speaker group changed`, was `Group changed`, R22 CH §2); overlays close `group`. **[P2a]** Shown for `group_changed_ms` 2600, ~~`meta` tone~~ **[P2b]** `error` tone (lead ruling R-j, 2026-09-26; K3 C5-76, §19 E-j); a change seen in a state poll shows the copy with no `err` (K3 §9.10, C5-76). **[P2a] Per op:** a start (`play_items`, `jump`) shows it from its result, with no `start_failed` copy and no toast; a `seek`, a shuffle or a `transport` press shows its own failure first (`knob.line.seek.failed` / `knob.meta.shuffle.failed` / the desktop notice) and the copy from the next state poll; `play_next` / `move_next` keep the Play next rule (`error` tone, 2400 ms) (K3 §8, §9.10) | — (**[P2a]** a `play_next` keeps `toast.playnext.nothing`, K3 §9.3) | `err` (K3 §9.10, C5-28, C5-56) |
| `accepted` | `snap` (pre-checks passed, K4 §9.5 t = 0) | `knob.meta.snap.left_set` / `.right_set` | — | `ok` + `moment:"snap"` (half-wash) |
| `hung` / `move_rejected` / `cant_fit` | `snap` (`hung` and `move_rejected` at the pre-check; `move_rejected` and `cant_fit` at placement; the 800 ms deadline counts as `move_rejected`) | `knob.meta.snap.hung` / `.move` / `.fit` | — (slot label `overlay.picker.slot_*`) | `err` |

---

## 9. Copy-string ids

### 9.1 Conventions

- **Id grammar:** `<surface>.<context>[.<variant>]`, lowercase, dots between segments, `snake_case` inside a segment. Surfaces: `knob.heading`, `knob.title`, `knob.sub`, `knob.meta` (12 px meta line), `knob.line` (14 px Tracks/Seek line), `knob.status` (12 px Home status), `knob.caption` (volume caption), `toast`, `overlay`, `settings`, `tray`.
- **Limits** (Montserrat 500, measured, S01 App C): knob meta 12 px ≤ **170 px**; knob line 14 px ≤ **170 px**; Home status 12 px ≤ **160 px**; headings 12 px caps, 0.04 em, ≤ **138 px**; knob title 22 px ≤ 170 px. Toasts and overlay copy have no knob limit. Byte capacities: `meta` 96 B, `heading` 32 B, `status` 64 B, `title`/`subtitle` 96 B, button `label` 16 B (P4 §3).
- **Typography is exact:** `’` U+2019, `…` U+2026, `·` U+00B7 with a space on each side, `{i} / {n}` with spaces around `/` (v4's `{i}/{n}` is retired).
- **Placeholders:** `{i}` 1-based position; `{n}` count; `{k}` progress count; `{u}` unavailable count; `{title}` track title; `{album}` album title; `{name}` album, playlist or track title of the thing started; `{App}` the window label's **display** app name (not the exe stem; A05 §2.7), `{A}`/`{B}` left/right app names; `{Title}` window title; `{Side}` `Left`/`Right`; `{Room}` Sonos room; `{ip}`; `{v}` firmware version; `{m:ss}` minutes unpadded, seconds 2 digits.

### 9.2 r2.1 Appendix C (every row; key = App C "Surface · Context")

| Id | App C key | Text |
|---|---|---|
| `knob.heading.recent` | Knob heading · Recently Added list | `RECENTLY ADDED` |
| `knob.heading.explorer_recent` | Knob heading · Explorer mirror · Recently Added | `RECENT` |
| `knob.heading.explorer_favourites` | Knob heading · Explorer mirror · Favourite playlists | `FAVOURITES` |
| `knob.heading.upnext` | Knob heading · Up next mirror | `UP NEXT` |
| `knob.heading.tracks` | Knob heading · Tracks | `TRACKS` |
| `knob.heading.seek` | Knob heading · Seek | `SEEK` |
| `knob.meta.position` | Knob meta · List position | `{i} / {n}` |
| `knob.meta.position_end` | Knob meta · End of Recently Added | `{n} / {n} · end` |
| `knob.meta.playnext.progress` | Knob meta · Play next · progress | `Queueing… {k} of {n}` |
| `knob.meta.playnext.ok` | Knob meta · Play next · success (1.5 s) | `Queued next` |
| `knob.meta.playnext.nothing` | Knob meta · Play next · failed | `Nothing added · retry` |
| `knob.meta.playnext.partial` | Knob meta · Play next · partial | `Partly queued` |
| `knob.meta.playnext.song_changed` | Knob meta · Play next · song changed | `Song changed · retry` |
| `knob.meta.playnext.airplay` | Knob meta · Play next · AirPlay | `AirPlay · use Play` |
| `knob.meta.playnext.radio` | Knob meta · Play next · radio | `Radio · use Play` |
| `knob.meta.playnext.linein` | Knob meta · Play next · line-in / TV | `Line-in · use Play` |
| `knob.meta.playnext.none` | Knob meta · Play next · nothing playing | `Nothing playing · Play` |
| `knob.meta.playnext.shuffle` | Knob meta · Play next · Sonos shuffle on | `Shuffle on · turn it off` |
| `knob.meta.loading` | Knob meta · Explorer loading | `Loading…` |
| `knob.title.favourites_empty` | Knob meta · Favourites empty | `No favourites yet` (drawn in `title`, VOC-R19) |
| `knob.meta.tracks.hint` | Knob meta · Tracks | `Press 4 to skip` |
| `knob.meta.tracks.position_shuffle` | Knob meta · Tracks · shuffle | `{i} / {n} · shuffle` |
| `knob.meta.upnext.airplay` | Knob meta · Up next · AirPlay | `Up next is in Music app` |
| `knob.meta.upnext.radio` | Knob meta · Up next · radio | `Radio · no Up next` |
| `knob.meta.seek.radio` | Knob meta · Seek · radio | `Can’t seek · radio` |
| `knob.meta.seek.airplay` | Knob meta · Seek · AirPlay | `Can’t seek · AirPlay` |
| `knob.meta.upnext.position_playing` | Knob meta · Up next position | `{i} / {n} · playing` (suffix only on the now-playing row; else `knob.meta.position`) |
| `knob.meta.upnext.loading` | Knob meta · Up next · loading | `Loading queue…` |
| `knob.meta.like.on` | Knob meta · Like · on | `Liked` |
| `knob.meta.like.off` | Knob meta · Like · off | ~~`Like removed`~~ **[r2.2] withdrawn**: never shown (Like is add-only; R22 CH §1 removes it; R22 App C has no such row). The id stays unused |
| `knob.meta.like.unknown` | Knob meta · Like · state unknown | `Checking likes…` |
| `knob.meta.like.not_catalog` | Knob meta · Like · non-catalog row | `Not an Apple Music song` |
| `knob.meta.like.signin_expired` | Knob meta · Like · sign-in expired | `Sign-in expired` |
| `knob.meta.shuffle.on` | Knob meta · Shuffle · companion | `Shuffle on` |
| `knob.meta.shuffle.off` | Knob meta · Shuffle · off | `Shuffle off · in order` |
| `knob.meta.shuffle.sonos` | Knob meta · Shuffle · Sonos (> 60 left) | `Sonos is shuffling` |
| `knob.meta.snap.left_set` | Knob meta · Windows · one side | `Left: {App} · pick right` |
| `knob.meta.snap.hung` | Knob meta · Snap · hung | `{App} not responding` |
| `knob.meta.snap.move` | Knob meta · Snap · move failed | `Couldn’t move {App}` |
| `knob.meta.snap.fit` | Knob meta · Snap · too big | `{App} can’t fit half` |
| `knob.line.tracks.now` | Knob line 14 px · Tracks · now | `Now: {title}` |
| `knob.line.tracks.next_shuffle` | Knob line 14 px · Tracks · Sonos shuffle, next unknown | `Next: shuffle pick` |
| `knob.line.tracks.prev_shuffle` | Knob line 14 px · Tracks · shuffle, previous | `Prev: last played` |
| `knob.line.tracks.next_wrap` | Knob line 14 px · Tracks · repeat all, last track | `Next: back to track 1` |
| `knob.line.seek.length` | Knob line 14 px · Seek · length | `of {m:ss}` |
| `knob.line.seek.jumping` | Knob line 14 px · Seek · waiting for Sonos | `Jumping…` |
| `knob.line.seek.failed` | Knob line 14 px · Seek · failed | `Didn’t jump · try again` (error ink, 2.2 s) |
| `knob.line.seek.limit` | Knob line 14 px · Seek · limit | `Stops 3 s before end` |
| `knob.status.starting` | Knob status 12 px · Home · starting | `Starting…` |
| `knob.status.partial` | Knob status 12 px · Home · playlist partly playable (3 s) | `Playing {k} of {n}` |
| `knob.status.start_failed` | Knob status 12 px · Home · start failed | `Didn’t start` |
| `knob.status.album_blocked` | Knob status 12 px · Home · album blocked | `Album unavailable` |
| `knob.status.paused` | Knob status 12 px · Home | `Paused` |
| `knob.title.offline` | Knob title 22 px · PC not connected | `Waiting for PC` (firmware-drawn; only after a lost host, VOC-R23) |
| `toast.playnext.ok` | Toast · Play next · success | `Queued next · {album}` |
| `toast.playnext.not_queue` | Toast · Play next · AirPlay / radio / line-in | `Not playing from the queue · use Play` |
| `toast.playnext.none` | Toast · Play next · nothing playing | `Nothing playing · use Play` |
| `toast.playnext.shuffle` | Toast · Play next · Sonos shuffle | `Shuffle is on · turn it off to play next` |
| `toast.playnext.nothing` | Toast · Play next · failed | `Couldn’t queue {album} · nothing added` |
| `toast.playnext.partial` | Toast · Play next · partial | `Partly queued · check the Sonos queue` |
| `toast.playnext.song_changed` | Toast · Play next · song changed | `Song changed · try again` |
| `toast.start.ok` | Toast · Start · success (after overlay closes) | `Playing {name}` |
| `toast.start.partial` | Toast · Start · partly playable | `Playing {k} of {n} · {u} song unavailable` (`songs` when {u} > 1, VOC-R14). **[r2.2] Approved** as `Playing {k} of {n} · {u} songs unavailable`, or `… · 1 song unavailable` when {u} = 1 (the same two strings; R22 CH §2; R22 App C rows "Start · partly playable" and "(plural)") |
| `toast.start.album_blocked` | Toast · Start · album blocked | `{album} can’t play · a song is unavailable` |
| `toast.start.failed` | Toast · Start · failed | `Couldn’t start {name}` |
| `toast.switch` | Toast · Switch | `{App} · {Title}` |
| `toast.snap.pair` | Toast · Snap · both sides | `Side by side · {A} and {B}` |
| `toast.snap.one_side` | Toast · Snap · one side, closed | `{A} left · {B} right` |
| `toast.like.signin_expired` | Toast · Like · sign-in expired (after close) | `Apple Music sign-in expired · open Settings` |
| `overlay.explorer.empty_title` | Overlay · Favourites empty · title | `No favourite playlists yet` (drawn in the explorer's state block, K4 §7.4) |
| `overlay.explorer.empty_help` | Overlay · Favourites empty · help | `Star a playlist in the Music app. It appears here within a few minutes.` |
| `overlay.upnext.foreign_title` | Overlay · Up next · queue from another app | `Sonos queue` |
| `overlay.upnext.card_title` + `overlay.upnext.card_sub` | Overlay · Up next · Sonos shuffle card | `Sonos is shuffling the rest` / `{n} songs · order isn’t shown` (App C joins them with ` · `) |
| `overlay.picker.slot_keep` | Overlay · Snap slot · one side preview | `{Side} · keeps {App}` |

### 9.3 r2.1 strings outside Appendix C

| Id | Text | Source |
|---|---|---|
| `knob.meta.snap.right_set` | `Right: {App} · pick left` | BS:1283 |
| `knob.meta.upnext.linein` / `knob.meta.upnext.none` | `Line-in · no Up next` / `Nothing playing` | S01:89 |
| `knob.meta.seek.linein` / `knob.meta.seek.none` | `Can’t seek · line-in` / `Nothing playing` | S01:90; BS:808 |
| `knob.meta.skip.end` / `knob.meta.skip.start` | `End of queue` / `Start of queue` (skip refused, with `err`) | BS:853 |
| `knob.line.tracks.next` / `.prev` / `.end` / `.start` | `Next: {title}` / `Prev: {title}` / `End of queue` / `Start of queue` | S01:146 |
| `knob.title.tracks.choose` / `.prev` / `.next` | `Turn to choose` / `Previous track` / `Next track` | BS:1257 |
| `knob.sub.favourites_empty` | `Star one in Music` | S01:136 |
| `knob.sub.playlist_count` | `{n} songs` | BS:1276 |
| `knob.title.upnext_sonos_card` | `Shuffled by Sonos` | BS:1263 |
| `knob.sub.offline` / `knob.sub.offline_native` | **[rename]** `Open Desk Dial on your PC` (a no-break space, U+00A0, between `Desk` and `Dial`; was `Open Nano_D++ on your PC`) / `Knob controls still work` (after native input) | S01:140; BS:1414; VOC-R11; VOC-R32 |
| `knob.status.minimum` / `knob.status.maximum` | `Minimum` / `Maximum` | S01:134 |
| `knob.caption.volume` / `knob.caption.volume_paused` | `{title}` / `Paused · {title}` | S01:154 |
| button labels (Home; idle-row words) | **`Play` \| `Pause`** (slot 0, following its icon) · `Browse` · `Tracks` · `Win` | S03 override #16 (S03:15) with **VOC-D08** (r2.1's `Play/Pause`, 67.4 px, cannot fit the 46 px column); §2.4 |
| `overlay.explorer.tab_recent` / `.tab_favourites` | `Recently Added` / `Favourite playlists` | R §7.3; BS:1386 |
| `overlay.explorer.hints` | `Back` · `Recently Added` · `Playlists` · `Play` | BS:1406; 00 C29 |
| `overlay.explorer.sub_favourite` / `.sub_favourite_auto` | `Favourite playlist` / `Favourite playlist · made by Apple Music` | S01:314; BS:1189 |
| `overlay.upnext.header` | `Up next` | BS markup |
| `overlay.upnext.foreign_sub` | `Started in another app · {n} songs` | S01:337 |
| `overlay.upnext.row_not_catalog` | suffix ` · not in Apple Music` | S01:339 |
| `overlay.upnext.tag_now` / `.tag_played` / `.tag_next` | `Now playing` / `Played` / `Up next` | BS qRows |
| `overlay.upnext.shuffle_on` / `.shuffle_off` / `.shuffle_sonos` | `Shuffle on` / `In order` / `Shuffle on · Sonos picks the order` | BS:1411 |
| `overlay.upnext.hints` | `Back` · `Shuffle`\|`Shuffle off` · `Like`\|**`Liked`** (**[r2.2]**, was `Unlike`: on a liked row the hint reads `[3] Liked`, R22 CH §1; R22 BS:1418) · `Play` | BS:1412 |
| `overlay.picker.slot_empty` / `.slot_filled` | `Snap {left\|right}` / `{Side} · {App}` | BS slot() |
| `overlay.picker.slot_hung` / `.slot_move` / `.slot_fit` | `{App} isn’t responding` / `Couldn’t move {App}` / `{App} can’t fit half` | S01:414-418 |
| `overlay.picker.badge` / `.desc_snapped` | `Left` \| `Right` / suffix ` · Snapped left` \| ` · Snapped right` | BS wCards |
| `toast.skip.next` / `toast.skip.prev` | `Next · {title}` / `Previous · {title}` | BS:857 |
| `settings.knob.ok` | `Connected` · **[rename]** `USB · firmware {v}` (`USB` when no version is known; was `Nano_D++ · USB · firmware {v}`) · action `Knob settings…` | S01:457; VOC-R32 |
| `settings.knob.problem` | `Not connected` · **[rename]** `Waiting for the knob on USB. The knob’s own controls still work.` (was `Waiting for Nano_D++ on USB. …`) · action `Troubleshoot…` | S01:457; VOC-R32 |
| `settings.sonos.ok` | `{Room}` · `{source phrase} · {ip}`; phrases `Playing from the Sonos queue`, `Playing via AirPlay`, `Playing radio`, `Playing line-in`, `Idle` · action `Set manual IP…` | S01:458; BS:1370 |
| `settings.sonos.problem` | `Not found` · `Can’t reach Sonos on this network` · action `Set manual IP…` | S01:458 |
| `settings.apple.ok` | `Signed in` · `Library and likes available` · action `Renew sign-in…` | S01:459 |
| `settings.apple.problem` | `Sign-in expired` · `Like and Favourite playlists are paused until you sign in again.` · action `Renew sign-in…` (primary light button) | S01:459 |
| `tray.open_settings` | `Open Settings…` (jumps to the strip) | S01:463 |

### 9.4 Retained v6 copy (not in r2.1, not contradicted; K3 audits the rest of CT:1049-1196)

`knob.status.setting` `Setting…`; `knob.status.changed_elsewhere` `Changed on Sonos`; `knob.caption.nothing_playing` / `knob.status.nothing_playing` `Nothing playing`; notice `Sonos unavailable` / `Looking for Sonos…` / `Windows still works`; `knob.meta.windows.switching` `Switching…`; `knob.meta.windows.no_focus` `Didn’t come forward · retry`; `knob.meta.windows.closed` `Closed · can’t switch` (apostrophe normalised to `’`). Retired: `· Replaces queue`, `Loads, doesn't play`, `RECENTLY ADDED · P{n}`, `Skipped · back at neutral`, `Back · focus restored`, `Cancelled · focus restored`, `Turn to preview · Green to switch`, and "Music login needed" (use `Sign-in expired`).

### 9.5 Engineering-added copy (states r2.1 leaves without copy; one approval pass, 00 G13; **[r2.2]** approved)

**[r2.2] Approval pass: done.** R22 CH §2 approves every string in this table as listed, rewrites two (`knob.status.group_changed` / `knob.meta.group_changed` → `Speaker group changed`; `knob.meta.stage_unavailable` → `Couldn’t open on screen`) and shortens the Like refusal to `Unfavourite in Music app`; all of them are now rows of R22 App C (the design's live-measured copy sheet). The ids are unchanged. Nothing below needs approval any more; the only open copy item is CH "Still open" → "Font check" (re-measure with the real font build, K1 §15.3 `copy`) (VOC-R29).

Widths are measured the way K1 measures (Montserrat 500 advance widths, no kerning, ±2 px; K1 §8.6.11), at 12 px unless noted; the LVGL harness re-measures every string (K1 §15.3 `copy`). **[r2.2]** R22 CH §2 measured the same strings in the prototype within 0.7 px of these values. The knob strings K3 adds for its own states (its §15.2 kept v6 ids and §15.3 additions, C5-29, C5-56) are registered in K3 §15.2–§15.3 and measured in K1 §8.6.11; the ones other contracts must name are repeated here.

| Id | Text | Why | Width |
|---|---|---|---|
| `knob.meta.seek.no_length` | `Can’t seek · no length` | queue item with an unknown or over-long duration (S01:90 requires a known length; K1 `LAP_COUNT_MAX`) | 131.9 px ≤ 170 |
| `knob.meta.sonos_unavailable` / `knob.status.sonos_unavailable` | `Sonos unavailable` | explorer opens with Play dimmed while Sonos is down (00 G12); the `status` twin on Home (K3 C5-56) | 110.2 px ≤ 170 / ≤ 160 |
| `knob.meta.item_unavailable` | `Not available` | unplayable list item (S01:174) | 79.4 px |
| `knob.meta.shuffle.queue_changed` | **`Queue changed`** (was `Queue changed · order kept`, 172.2 px over the 170 px meta line, K1 OQ-2) | shuffle-off restore refused (A06 §3.4); the Head shake says it failed and the list shows the kept order. Reuses the text of a retired v6 string (K3 §15.2) | 98.4 px |
| `knob.meta.shuffle.failed` | `Didn’t shuffle · try again` | reorder/SetPlayMode failure | 145.6 px |
| `knob.meta.shuffle.nothing` | `Nothing to shuffle` | Up next 2 with fewer than 2 upcoming rows outside the Play-next block (`nothing_next`, §2.6 second table; K3 C5-59) | 110.8 px |
| `knob.meta.like.failed` | `Didn’t save · try again` (**[r2.2]** approved; error tone, `like_fail_meta_ms` 2200, with the Head shake, R22 CH §1) | Apple 429 / 5xx on a like, or a like read-back that times out | 131.4 px |
| `knob.meta.like.unlike_in_music` (rev 4, K3 C5-63) | **[r2.2] `Unfavourite in Music app`** (meta tone, `like_fail_meta_ms` 2200; approved, R22 CH §1–§2). Rev 4 text `Unfavourite in Music` (125.9 px) is superseded; the first wording, `Unfavourite in the Music app` (176.4 px, over 170), was rejected | a press on a liked row (`unlike_unavailable`; add-only is final, VOC-R26) | **152.7 px** (R22: 152) |
| `knob.meta.busy.starting` / `knob.meta.busy.pausing` / `knob.meta.busy.shuffling` | `Starting…` / `Pausing…` / `Shuffling…` | a press dimmed by a busy code in a mode where the busy line or comet is not on screen (§2.6 second table; K3 C5-59); the first two are the `meta` twins of `knob.status.starting` / `knob.status.pausing` | 57.6 / 58.1 / 63.7 px |
| `knob.meta.library_error` | `Library not loaded` | the `list_error` reason on a `meta` line (the twin of K3's `knob.title.library_error`, K3 C5-56) | 111.5 px |
| `knob.meta.signin_expired` | `Sign-in expired` (error tone) | the `signin_expired` list reason (the list twin of `knob.meta.like.signin_expired`, K3 C5-56) | 92.5 px |
| `knob.status.group_changed` / `knob.meta.group_changed` | **[r2.2] `Speaker group changed`** (was `Group changed`, 95.5 px: "Group" alone is ambiguous, R22 CH §2) | the `group_changed` outcome on Home's `status` line / on any `meta` line (K3 §9.10, C5-56) | **147.6 px** (R22: 147) ≤ 160 (status) / ≤ 170 (meta) |
| `knob.sub.library_error` (K3 §15.2, kept v6 id) | **`Home, then Browse`** (was `Home, then Browse to retry`, 197.1 px at 14 px, over the 170 px sub line, K1 OQ-6) | Recently Added error sub-line; the title `Library not loaded` says what failed | 141.2 px at 14 px |
| `toast.start.partial` plural | `… · {u} songs unavailable` (**[r2.2]** approved: `Playing {k} of {n} · {u} songs unavailable`, `1 song` when {u} = 1, R22 CH §2) | {u} > 1 | — |
| `knob.meta.stage_unavailable` | **[r2.2] `Couldn’t open on screen`** (was `Can’t open on screen`, 129.0 px; past tense like `Couldn’t move` / `Couldn’t queue`, R22 CH §2) (error tone, `fail_meta_ms`) | the presenter refused an open (`refused(surface, busy\|device)`, §7.4; K4 VOC-K4-02) | **149.1 px** (R22: 149) |
| **[r2.2]** `knob.meta.playnext.resolving` (K3 §15.3 id) | **`Finding songs…`** (was `Queueing…`, 69.1 px) | Play next during the Apple lookup, before the first song is queued (instead of `Queueing… 0 of {n}`); R22 App C "Knob meta · Play next · song lookup (before k counts)" (R22 CH §4; VOC-R28) | **94.7 px** |
| Home slot-0 label | `Play` / `Pause` (replaces `Play/Pause`) | VOC-D08: the r2.1 word cannot fit the idle-row column | 25.9 / 37.3 px ≤ 46 |
| `overlay.explorer.recent_empty_title` / `.recent_empty_help` | `Nothing recently added` / `Add an album or a playlist to your library in the Music app.` | the explorer's Recently Added tab when the list is empty (K4 §7.4 state block, S5-33; VOC-K4-04) | overlay, no knob limit |
| `overlay.explorer.error_title` / `.error_help` | `Library not loaded` / `Go Home, then Browse to retry.` | the explorer's state block when the list failed (K4 §7.4; VOC-K4-04) | overlay |
| `overlay.explorer.signin_title` / `.signin_help` | `Apple Music sign-in expired` / `Open Settings on your PC to sign in again.` | 401/403 with nothing cached, on **either** tab (K3 §15.3 proposed it for favourites; K4 §7.4 uses it for both, VOC-K4-04) | overlay |

---

## 10. Named durations (ms unless `_s`)

| Id | Value | Meaning | Source |
|---|---|---|---|
| `hold_ms` | 600 | Button 1 hold → Home; **firmware only** (AceButton long-press delay); the host has no hold timer (VOC-D06) | S01:41 |
| `seek_step_s` / `seek_margin_s` | 5 / 3 | per detent / `T_end = D − 3` | S01:200-201 |
| `seek_debounce_ms` | 250 | send after the last detent (**[r2.2]** unchanged; a follow-up jump after a landing also waits for it, VOC-R27) | S01:202; R22 CH §3 |
| `seek_idle_ms` | 3000 | Seek exits without a turn; **[r2.2]** counted from the last landing; never while a jump is waiting or in flight (R22 S01 §4b; K3 C5-15, C5-68) | S01:203 |
| `seek_confirm_ms` | **[r2.2] 8000** (r2.2; rev 4: 5000; was 3000) | landing deadline per jump: **playback resumed** (the transport has left `TRANSITIONING`); no resume within it → `not_confirmed` (never resend). Rev 4's "position within ±2 s" is no longer a condition (R22 CH §3). **[P2a]** The same window bounds an Up next `jump` (K3 C5-74): from the `Seek(TRACK_NR)` reply, played on the first `PLAYING` read at the row (after `TRANSITIONING`, or ≥ 1.0 s after the reply when none was seen); none by then → `start_failed`, never resent | CS §4.4; LC W2; K3 C5-65, C5-68; R22 CH §3; **[P2a]** K3 C5-74 |
| `like_readback_ms` / `like_confirm_ms` / `like_late_check_ms` | 250 / 4000 / 5000 (rev 4) | like `ratings` read-back interval / its deadline (→ `failed`) / one late check after a timed-out like (**[r2.2]** like only: no unlike exists) | LS; K3 §7, C5-62 |
| **`like_fail_meta_ms`** **[r2.2]** | 2200 | the Like refusal `Unfavourite in Music app` (`unlike_unavailable`) and the save failure `Didn’t save · try again`, each with the Head shake | R22 CH §1 ("for 2.2 s"); R22 BS `knobMeta(…, 2200)` |
| `prefetch_resolve_rest_ms` | 400 (rev 4) | rest on a Recently Added item before its pre-resolution (and its neighbours') starts | LC W1; K3 §7, C5-66 |
| `seek_fail_line_ms` | 2200 | `Didn’t jump · try again` | S01:204 |
| `reason_meta_ms` | 2000 | dim-press reason | S01:50 |
| `fail_meta_ms` | 2400 | Play next / snap failure meta and slot outline | S01:216, :412 |
| `queued_meta_ms` | 1500 | `Queued next` | S01:215 |
| `feedback_meta_ms` | 1500 | Like / Shuffle metas | BS:830, :882 |
| `partial_status_ms` | 3000 | `Playing {k} of {n}` | S01:228 |
| `start_fail_status_ms` | 2600 | `Didn’t start` / `Album unavailable` | BS:993 |
| `group_changed_ms` | 2600 | **[P2a]** `Speaker group changed` (`knob.status.group_changed` / `knob.meta.group_changed`), ~~`meta` tone~~ **[P2b]** `error` tone (lead ruling R-j, 2026-09-26; K3 C5-76, §19 E-j); the design gives no duration; from a failed start or volume write, or from the next state poll (after a failed seek, shuffle or transport it follows their own failure copy) | K3 §7, §9.10, C5-76 |
| `overlay_play_close_ms` | 380 | explorer/Up next close on Play | S01:225 |
| `tab_swap_ms` | 190 | explorer source switch (re-entry instant) | BS:1038; 00 G2 |
| `shuffle_swap_ms` | 200 | Up next rows re-enter; focus → now + 1 | BS:881 |
| `snap_place_ms` | 360 | the real window moves once | S01:403 |
| `snap_advance_ms` | 420 | highlight → next unassigned window | BS:1090 |
| `snap_pair_close_ms` | 820 | picker closes when both sides are filled | S01:406 |
| `exit_toast_delay_ms` | 360 | toasts after an overlay closes | S01:422 |
| `toast_hold_ms` | 1800 | toast hold | S01:421 |
| `overlay_idle_s` | 60 | overlay lifetime without knob input | S01:426 |
| `volume_hide_ms` | 1400 | reveal hides after the last detent (and Sonos confirmed; re-check 400) | S01:153 |
| `external_reveal_ms` | 2600 | volume changed elsewhere | S03 |
| `paused_idle_ms` | 4000 | idle icon row after a confirmed pause | S03 |
| `led_rest_ms` / `led_rest_external_ms` | 5000 / 3200 | LED sleep | S02 §4 |
| `lcd_slide_px` / `lcd_slide_ms` / `lcd_fade_ms` | 20 / 380 / 220 | screen change | S01:157 |
| `text_fade_ms` | 160 | meta/status/label fade-in at rest | S01:118 |
| `comet_lap_ms` | 1400 | Working comet | S01:191 |
| `rm_fade_ms` | 200 (overlays) / 220 (knob LCD) | reduced-motion fades | S01 §10 |
| `clock_resend_s` | 600 | latched clock resend | AL §3 |
| `lim_gap_ms` | 150 | minimum between `lim` events | AL §3 |
| `lim_rearm_ms` | 75 (rev 4; tuned 40–150 in the hardware turning test) | the knob must be off a bound this long before the next push into it fires `bound` + `lim` (every push fires, K2 ruling Q1) | K2 §6.2, §12.5 |
| `snap_deadline_ms` | 800 | a `snap` job resolves by `t0` + 800 (else `move_rejected`); K3's latched Back/hold runs by then, before the 820 ms pair close | K4 §9.6 (`SNAP_DEADLINE_MS`) |
| `one_side_deadline_ms` | 600 | a `complete_one_side` job resolves by its start + 600 | K4 §9.6 (`ONE_SIDE_DEADLINE_MS`) |
| `snap_result_timeout_ms` | 1000 | controller last resort: no `snap_result` 1000 ms after `t0` counts as `move_rejected` | K3 §7, C5-53 |
| `signin_meta_ms` / `seek_limit_line_ms` | 2200 / 1500 | `Sign-in expired` (error) / `Stops 3 s before end` | BS:825, :930; K3 §7 |
| `start_staging_deadline_s` / `resolve_deadline_s` | `6 + 0.15·N` / 20 | `play_items` staging (then rollback → `start_failed`) / a whole `resolve` | K3 §7, C5-37 |
| `art_fade_ms` / `ink_fade_ms` | 240 / 160 | knob cover show/hide / footer and idle ink crossfade | K1 §8.8 (VOC-K1d) |
| `footer_hide_ms` / `footer_show_ms` | 160 / 280 (+140 delay) | knob footer on idle and offline in / out | K1 §8.8 (VOC-K1d) |
| `idle_stagger_ms` | 200 + 45·i | knob idle-row column i entry delay | K1 §8.8 (VOC-K1d) |
| `hidden_catchup_step_ms` | 50 (≤ 60 steps) | floating knob while hidden: catch-up renders before each per-message render and before the first visible render | K2 §10.3 item 2 (M27) |

---

## 11. Palette and inks (names every contract uses)

| Token | Design value (prototypes, sRGB) | Emitted / drawn | Use | Source |
|---|---|---|---|---|
| `WARM` | `#FFBE69` (BS `WARM = [255,190,105]`) | ring **#FF8424**, fixed all day (ToD dims resting only) | all non-semantic light | R:92-98; AL §2 |
| `HOT` | mix(WARM, white, 0.5) | — | spark heads, wake, comet head | S02 §2 |
| `AMBER` | `#FF8338` | ring **#FF3A0A** | volume 80–90 %, offline marks | R:95; AL §2 |
| `RED` | `#FF0000` | #FF0000 | volume ≥ 90 %, Head shake | R:96 |
| `GREEN` | `0,255,98` | — | `go`, paused Play, Confirmed | R:99 |
| `BLUE` | `40,140,255` | — | changed elsewhere | R:99 |
| `PINK` | `255,40,90` (**candidate**; user picks on the ring) | never `sat()` | liked heart (**[r2.2]** the Button 3 LED at 0.30, tone `liked`), Like bloom; spark `mix(PINK, white, 0.3)` | R:100; CH "Still open"; R22 CH §1 |
| accent | `sat(dominant)` | — | §3.5 | S02 §2 |
| LCD `text` / `context` / `meta` | `#F2F2F2` / `#A6A6A6` / `#7C7C7C` | — | ink / secondary / meta | S03 |
| LCD `error` | **`#FF8474`** (was `#FF8A7A`) | — | failure meta, Seek failure line | S01:138; BS:482 `ERR`; VOC-R10 |
| LCD `success` | `#7EE0A2` | — | (unused by r2.1 copy; kept) | S03 |
| footer `nav` / `go` / `dim` / `on` / `off` / heart | `#E6E6E6` / `#6ED996` / **`#5A5A5A`** / `#FFFFFF` / `#7A7A7A` / ~~`#FF285A`~~ **[r2.2] `liked` `#A3244A` (filled heart)** | — | §2.3 | BS:1233; R22 CH §1 |
| row heart fill (desktop Up next) | `#FF285A` | — | the liked row heart on screen (K4 §8.3); **[r2.2]** the other row states are white outlines at 45 % / dashed 30 % / 15 % | S01 §6; R22 CH §1 |
| Settings status marks | `#6ED996` OK / `#FF7A66` problem | — | `settings_strip` | S01:461 |
| picker failure outline | `1px rgba(255,132,116,.9)` | — | snap slot failure | S01:412 |
| app icon orange | `#ff6a1a` | — | tray/app icon (unchanged) | R:156 |

---

## 12. Naming conflicts resolved (proposal → chosen name → reason)

| Id | Topic | Proposals (source) | Chosen | Reason |
|---|---|---|---|---|
| VOC-N01 | Music explorer | `explore` (BS `mode`, BS:1273; A05 §2.1 mode, A05 §2.6 `explore_*` effects); `explorer` (A04 §2.3 layout; A02 F15 family) | **`explorer`** in every layer (mode, layout, group, family, scene, suppression reason, effects `explorer_*`) | One token per concept; matches the surface name "Music explorer"; `explore` is a prototype state name only |
| VOC-N02 | Up next | `queue` (BS `mode`; A05 mode, suppression reason `queue`, effects `queue_*`); `upnext` (A04, A02) | **`upnext`** everywhere | "queue" already names the Sonos queue (source class `queue`, op `queue_window`, copy `Sonos queue`); a second meaning invites bugs |
| VOC-N03 | Seek | A05 controller mode `seek`; A04 layout `seek`; BS `tracks` + `seek` flag; A02 family `tracks` + style `lap` | controller **sub-mode `seek` (parent `tracks`)**, layout `seek`, **group and family `tracks`**, ring style `lap` | Seek is a Tracks sub-state (no slide, same family; the style change fires the Reveal) but needs its own controller state, profile and LCD layout |
| VOC-N04 | Home | controller `volume` (CT:104 `Screen.mode` default, CT:43 `PROFILES`); BS `home`; AL family `home` | controller mode **`home`** (renamed during the WP5 rewrite); layout tokens `nowPlaying`/`volume`/`idle`/`notice` unchanged | Removes the homonym "mode `volume`" vs "layout `volume`" (the reveal layout); matches the button map, BS and AL. `PROFILES`, `mode_title`, status exports follow |
| VOC-N05 | Explorer tab / source ids | BS `recent` / `playlists` (BS:1386, `xIdx.playlists`); A05 accent kinds `recent` / `playlist` | source ids **`recent`** / **`favourites`**; wire `page` **0 / 1** | "playlists" alone is ambiguous (Recently Added also contains playlists); `favourites` matches the heading `FAVOURITES` and the op `favourite_playlists`. British spelling in our ids (r2.1 copy); Apple's US spelling only inside API paths |
| VOC-N06 | Icon tokens | BS glyph keys (`note`, `list`=Tracks, `tracks`=skip-forward, `next`=list-plus, `queue`=list-music, `check`, `rect`+`HALF`); A05 hyphenated glyph names (`list-music`, `list-plus`, `snap-left`, `snap-right`, `skip-back`, `check`, `note`, A05 §2.7); A04 meaning tokens (A04 §3.3) | **A04 meaning tokens** (`list`=Browse, `tracks`=Tracks, `next`/`prev`=skip, `switch`, `expand`, `clock`, `playlists`, `playnext`, `seek`, `shuffle`, `heart`, `snapleft`, `snapright`) | BS keys collide with v4 tokens that mean something else (A04 §3.2); meaning tokens keep a v6 host correct on cc5.4 (00 A10); `[a-z]+` tokens match the existing parser tables |
| VOC-N07 | Button state on the wire | A05: per-button `tone`/`accent` + a 40-bit Up next mask (A05 §2.7, §4); A02/A04: `lit` + `color` + `ring.now` | **`lit` + `color`**, **`ring.now`** | 00 A2: one set of fields drives both the LCD ink and the LEDs; tone stays derived on the knob |
| VOC-N08 | Tone names | V4 `none/dim/stop/go/nav` (FP:26); BS `nav/go/on/off/dim/none` (BS:1233) | union; **`on`, `off` appended**; `stop` legacy (v6 `cancel` only); **[r2.2] `liked` appended** (7; VOC-R26) | append-only enums; Windows Button 1 is now warm Back (CH §7 #3) |
| VOC-N09 | Mirror headings | r1/A04/A05 `RECENT · SCREEN`, `PLAYLISTS · SCREEN`, `UP NEXT · SCREEN` | **`RECENT`**, **`FAVOURITES`**, **`UP NEXT`** | r2.1 copy sheet (S01:126; App C); fits 138 px with 0.04 em tracking |
| VOC-N10 | Feedback moments | A02 §8 `queued`/`shuffle`/`like`/`unlike`/`snap`; A05 host effect names (`play_next`, `shuffle`, `like`, `windows_snap`) | A02's five **+ `started`** (VOC-R07); host effect names are a different layer (§7.4). **[r2.2]** `unlike` retired (reserved, never sent; VOC-R26) | moments name the LED meaning, effects name the host job |
| VOC-N11 | Hold | A04 `kh` value = raw index; A05 option (a) `{"kh": 0}` and host event `{"kind":"hold","button":0}` | wire **`kh` = raw index** (like `kd`), plus `ks`; host event **`hold`** with the **logical** `button` | consistent with `kd`/`ku`, which are raw on the wire and logical in `device.py` events |
| VOC-N12 | Seek ring | A05 "a song-lap ring … index/count in seconds, or a new style" (A05 §4); A02/A04 `ring.style:"lap"` | **`lap`**, `index` = target s, `count` = D s | 00 A2 |
| VOC-N13 | Up next ring | A05 "levels / played / now field" (A05 §2.7); A02 `ring.now`; task wording "upnext style" | wire **`selection` + `now`**; **pattern id `upnext`** in LED docs | 00 A2 keeps one list style; the pattern name is used only in K2 prose (VOC-R16) |
| VOC-N14 | Service ops | A05 effects `seek`/`play_next`/`queue`/`shuffle`/`jump`/`like`/`playlists`; A06 §7 `play_next`/`seek`/`set_shuffle` (native **or** reorder)/`shuffle_upcoming`/`queue_window`/`move_next`/`library_playlists`; 00 K3 list | **`play_next`, `seek`, `shuffle_reorder`, `set_shuffle` (native only), `queue_window`, `jump`, `move_next`; `like`, `unlike`, `ratings`, `favourite_playlists`, `catalog_songs`, `recent`/`recent_lookahead`, `resolve`**; effect kind = op id (1:1). **[r2.2]** `unlike` withdrawn (VOC-R26; the name stays reserved) | U4's hybrid needs the two shuffle regimes to be distinct ops; `favourite_playlists` names the CF recipe (not all library playlists); `queue` would collide (VOC-N02) |
| VOC-N15 | Overlay presenter effects | A05 `explore_open/close/source/highlight`, `queue_open/close/highlight` | `explorer_*`, `upnext_*` (+ `upnext_rows`); existing `windows_*` names kept (`windows_cancel` = Back) | follows VOC-N01/N02; rename only where the meaning changed or a homonym existed |
| VOC-N16 | Floating-knob suppression | A05 `explorer` / `queue`; existing `carousel`, `picker`, `disconnected` | **`explorer`**, **`upnext`**; `carousel` kept for the picker surface | VOC-N02; `carousel` is live code/test vocabulary with unchanged meaning |
| VOC-N17 | Deviation ids | A02 "D19–D29", 00 "D30" vs AL's existing **D19** (AL:501) | **`M1…M12`** (crosswalk §0.3) | avoid a collision in the doc another workflow owns |
| VOC-N18 | Tracks neighbour copy | 00 G8 `Next: shuffled` / "Previous unavailable" | r2.1 **`Next: shuffle pick`**, **`Prev: last played`**, `Next: back to track 1` | r2.1 designed it (S01:142-149) |
| VOC-N19 | Up next off-queue copy | 00 §3.3 `Up next is on the playing device` | **`Up next is in Music app`** (+ radio/line-in/none variants) | r2.1 (S01:89, :95) |
| VOC-N20 | Play next refusal copy | 00 §3.3 knob `Not playing from the queue` / `Shuffle is on` | per source `AirPlay · use Play` … and `Shuffle on · turn it off` (knob); toasts as App C | r2.1 (S01:87, :209) |
| VOC-N21 | Picker Back toast | r1 BS / A05 §7.2 `Back · focus restored`; S04 `Cancelled · focus restored` | **no Back toast**; one-side close gives `{A} left · {B} right` | r2.1 (R:152; S01:411, :423) |
| VOC-N22 | Artwork fallback names | App B "Small-art mat"; S01 §6 "small-art mat"; R/CH r2.1 "Extended sleeve" | **`art.extended`** (Extended sleeve) | README precedence; CH r2.1 replaced the blurred mat (VOC-R20) |

---

## 13. Deviations from r2.1 (VOC-D) and rulings (VOC-R)

### 13.1 Deviations (r2.1 says X; the contracts do Y)

| Id | r2.1 | Contracts | Reason | Owner |
|---|---|---|---|---|
| **VOC-D01** | Snap: "`SW_RESTORE` first if maximized" (R:176; S01:403; also R §8 "Windows"); failures: "Nothing moves" (S01:412) | **Never `SW_RESTORE`.** Restore non-activating with `ShowWindowAsync(SW_SHOWNOACTIVATE)` **only**, then `SetWindowPos` with `SWP_ASYNCWINDOWPOS` + frame compensation + verify, under the 800 ms deadline (§8.4). No `SetWindowPlacement`, `ShowWindow` or synchronous `SetWindowPos` on the target. A failed snap puts the window back with posted calls; a formerly **maximized** window comes back restored, never re-maximized (K4 S5-32) | `SW_RESTORE` and every maximize command activate the target, so the picker loses the foreground and dismisses itself (00 C24; A05 §6.4, risk R2/S4; MS-14); the synchronous calls wait on a busy target's thread and would block `NanoD-snap` and K3's latched Back/hold (K4 §9.6, MS-11, MS-12) | K4 |
| **VOC-D02** | Assigned snap button ink and LED in the raw app colour (BS:1282-1284, :1291-1293) | `sat(color)` on the LCD ink and the LED | raw colours such as navy or dark green fall below 3:1 on black (A04 §2.10 risk 11); `sat()` matches every other accent on the ring (S02 §2); 00 §3.2 "Snap footer ink" | K1, K2 |
| **VOC-D03** | The prototype starts Like bloom, Shuffle scatter, Snap half-wash and the Play-next sweep on the press (BS:829, :879, :1088, :1021) | These moments start on the host's `feedback` (acceptance or verified completion, as K3 decides per action) | the knob cannot know success; no false confirmation and no undo (K2 M6, formerly A02 D24); Like measured 145 ms PUT (LC), so the delay is small; rev 4: the favourites `POST` plus its read-back take ≈ 0.6–1.6 s, covered by the Working comet (K3 C5-62) | K2, K3 |
| **VOC-D04** | Tracks Prev cursor = segment 53 (BS "last cell with a ≥ 1": marks BS:1316, cursor rule BS:1332) | **52** | BS artefact; V4 and KM use 52 (A02 F9 → K2 M4); only shifts moment origins by one segment | K2 |
| **VOC-D05** | Companion "built on DirectComposition" for the three overlays (R:42; R §7.1) | `explorer` and `upnext` on the DirectComposition stage; the **picker keeps its v6 host** (layered windows + DWM thumbnails) with GIL/pacing fixes in v7, chrome to the GPU later | DirectComposition cannot animate DWM thumbnails; the picker's focus contract needs its activatable host; lower risk (RF0 §2.3; engineering ruling) | K4 |
| **VOC-D06** | "If the button is still held at 600 ms" (S01:41; BS host timer BS:891) | **One mechanism, in the firmware only:** AceButton long press at 600 ms after the debounced press → `kh` ≈ 620–640 ms after contact; slot 0 only; at most one `kh` per physical press; a long press that fires while the knob is entering is sent right after the next `ready` (K1 §11.2 step 5, P5-R10). **No host timer of any kind**, including a fallback armed from `ks` at `ready` (K3's C5-8 is withdrawn); `ks` only re-seeds the pressed mask (K1 §11.3) | host timing fires false Homes after a quick Back tap, because key events are dropped while the knob is entering (A04 §6.1; 00 A3); the deferred `kh` covers exactly the case a host fallback would (a hold that matures during the Back re-entry), so a second, host-timed path would fire for the same press, and its deduplication could not key on the press's `kd` time (a deferred `kh` carries only the new ready id and a raw index) | K1, K3 |
| **VOC-D07** | Every dimmed press shows its reason and plays the Head shake (R:76; acceptance R:182; S01:50); only Home 1 while `Starting…` is "ignored" (S01:86) | Codes marked **ignored** in §2.6 (`queueing`, `loading`, `sonos_card`, `empty`, `neutral`, `seeking`) and K3's added codes **in the modes where their state is on screen** (§2.6 second table: `starting` on Home, `queueing` in Recent, `shuffling` in Up next, `transport_pending` on Home 1 and on Tracks 4 during its own skip, `nothing_next` with fewer than 2 upcoming rows, `loading`, `empty`) play only the Press moment: no copy, no shake. Allowed only when r2.1 gives the state no reason copy **and** the state is already visible where the press happens (§2.6 conditions 1–2); in every other mode the same code shows reason copy (the busy line, §9.5) and shakes (K3 C5-59) | follows the primary prototype (BS:851, :885, :953, :971, :1005, :1042), which is silent in exactly these cases; a red shake for a transient busy state or a self-evident one (Loading, Queueing, Neutral, in Seek) would read as a failure when nothing failed, and the reason is already on screen. One table flag per code (K3 `spec.ignored`), so the hardware window can flip any of them | K3 |
| **VOC-D08** | Home idle-row word for Button 1: `Play/Pause` (S03 override #16, S03:15) | Home slot-0 `label` **follows the icon**: `Play` with `play`, `Pause` with `pause`. `Browse` · `Tracks` · `Win` unchanged | `Play/Pause` measures 67.4 px at 12 px against the 46 px column (S03:134): it overlaps `Browse` by ≈ 10 px, crosses the 104 px safe circle and would be ellipsized to `Play/Pa…` (K1 §8.6.3, OQ-1). The idle row shows only while paused or with nothing playing, so it reads `Play` under the green or dim Play glyph, which is what r2.1 draws; BS's own Home 1 legend is `Pause` / `Play` (BS:1247). Listed in the §9.5 approval pass; **[r2.2] approved** (R22 CH §2, "the label follows the icon") | K3 (label, C5-60), K1 (width gate, P5-12, `idle_row`) |

### 13.2 Rulings (choices between sources, or where r2.1 is silent)

| Id | Ruling | Basis | Owner |
|---|---|---|---|
| VOC-R01 | Controller mode ids `home`, `recent`, `explorer`, `tracks`, `seek`, `upnext`, `windows` (VOC-N01…N04) | §12 | K3 |
| VOC-R02 | One token per concept across controller, wire, LED, desktop (§1.1) | 00 A1 | all |
| VOC-R03 | **Window rule follows r2.1:** `first = clamp(index − 10, 0, count − 20)`, window-relative slots `c0 = first + ⌊(min(20,count) − 1)/2⌋`; supersedes V4's absolute slots for `count > 20` (identical for ≤ 20). v5 hosts always send `first` | r2.1 explicit (S01:166; CH §7 #20, r2.1; BS:1319, :1326) overrides A02 F14 "keep V4" with good reason: the flat Recently Added list (U5, 96+ items) would otherwise wrap the cursor round the ring every 20 items | K1, K2 |
| VOC-R04 | **Odd volume half-step follows r2.1** (recommended): cursor/endpoint at `35 + ⌊v/2⌋` at 1.0, the *next* segment at 0.81; equivalently, in AL's v4-geometry pipeline, swap the classes of V4's shoulder (35+n−1, S) and endpoint (35+n, class 3) for odd v | S01:164 "light the next segment at 0.81 (a half step)"; BS:1305-1310; departs from V4 P4-1 / AL D10 placement (the levels 0.81/1.0 are unchanged) | K2 decides |
| VOC-R05 | **Unavailable list entry** (recommended): landmark omitted; the cursor on it keeps the item's colour at **0.45** (class 1 semantic) instead of V4's L2 | S01:174; P4 §5.3 | K2 decides |
| VOC-R06 | **Loading list/queue** (recommended): no landmarks and no V4 segment-0 loading pulse; only the Working comet | S01:166, :300, :336 | K2 decides |
| VOC-R07 | New feedback moment **`started`** (+ `color`): hybrid Play (U11) puts the knob on Home before the start is confirmed, so AL D7 ("previous family was a list") can never fire; `started` carries the wash colour explicitly. `color` 0 / warm → green bloom (parity with D7) | 00 U11 (user decision); S01 §4d; BS:998, :888 | K1, K2, K3 |
| VOC-R08 | Target flash suppressed whenever `moment` is present (incl. `started`) | A02 F13 → K2 M7; r2.1 draws no flash anywhere | K2 |
| VOC-R09 | Latched frame field **`reducedMotion`** (bool); Settings key `motion` = `"system"` (default: Windows *Animation effects*, `SPI_GETCLIENTAREAANIMATION`) \| `"full"` \| `"reduced"` | S01 §10 makes the knob LCD and LEDs honour it; the knob cannot read the PC setting | K1, K2, K3 |
| VOC-R10 | LCD inks: `error` tone **`#FF8474`** (r2.1 `ERR`), footer `dim` **`#5A5A5A`** | S01:138; BS:482, :1233; 00 C27 | K1 |
| VOC-R11 | PC-not-connected LCD copy follows r2.1 (`Waiting for PC` / `Open Nano_D++ on your PC` / `Knob controls still work`), replacing P4-8's `NANO_D++ / Waiting for PC / Native controls active`. **[rename]** Renamed to Desk Dial: `Open Desk Dial on your PC` (VOC-R32) | S01:140 is explicit and consistent with the user's native-handover decision (the earlier ruling in 00 §2.2 was against KM's "Resumes at Volume") | K1 |
| VOC-R12 | Dim reasons live only in the host (§2.6); no wire field | the knob never acts on a press by itself; saves frame bytes | K1, K3 |
| VOC-R13 | Deviation-id namespaces (§0.3) | AL D19 collision | all |
| VOC-R14 | Additions where r2.1 is silent: explorer opens with Play dimmed when Sonos is down (00 G12); overlay close reasons `group`, `foreground`, `source` (00 G9); Home 3 dims with `nothing_playing` (S03 idle row); new copy §9.5; toast plural | 00 G9, G12, G13 | K3, K4 |
| VOC-R15 | The U12 one-side completion applies on `back`, `hold`, `lock`, `sleep`, `idle`; **not** on `disconnect`, `focus_lost` or `display` | BS:893-905 apply `deskNext` on hold and lock; BS:909 skips it on disconnect; focus loss means the user took over; after a display change the recorded half rects are stale (K4 §15) | K3, K4 |
| VOC-R16 | Up next ring = `selection` + `ring.now` (no `upnext` style token) | 00 A2 engineering ruling; r2.1 does not contradict it | K1, K2 |
| VOC-R17 | Presentation 5 implies `kh`, `ks`-in-`ready`, `reducedMotion`; no `keyHoldMs` key | one capability to test (A04 §5.2 made it optional) | K1 |
| VOC-R18 | Scatter uses the **r2.1 recipe**: sparks at `(seed + ORD[k]·60/9) mod 60`, `ORD = [0,4,8,3,7,2,6,1,5]`, each 55 ms after the previous, 260 ms bumps; **`seed = 60·u`** with `u ∈ [0,1)` from one deterministic xorshift32 shared by both ports (seeded in `reset()`); **no seed rejection** (the spread never clusters) | S01:194; BS:657, :879; supersedes A02 §6.3/F17's `1 + 9u` and rejection | K2 |
| VOC-R19 | App C's "Knob meta · Favourites empty" (`No favourites yet`) is drawn in `title` with `subtitle` `Star one in Music` | S01:136; BS:1276 | K1, K3 |
| VOC-R20 | "Small-art mat" (App B last row; S01:341) means the Extended sleeve | R §7.3; CH r2.1 | K4 |
| VOC-R21 | Under `ledStyle:"white"` PINK stays (semantic, like GREEN); snap/half-wash/started colours become WARM (recommended) | A02 F22 | K2 decides |
| VOC-R22 | **Presenter-initiated ends reach the controller.** K4's additions are absorbed: close reasons `display` and `device` (§7.3; VOC-K4-01), the event `refused(surface, busy\|device)` and the copy `knob.meta.stage_unavailable` (§7.4, §9.5; VOC-K4-02). K3 has one entry point for every presenter event (§7.4); a presenter close returns the knob to the parent mode silently; a refusal returns it to the parent mode with a Head shake and **[r2.2]** `Couldn’t open on screen` (was `Can’t open on screen`, VOC-R29) | without it, a refused open or a device/display close leaves the knob mirroring an overlay that is gone until the 60 s idle close (K3 enters `explorer`/`upnext` at the press); K4 §2.3, §4.3, §15, §21.3 | K3, K4 |
| VOC-R23 | **PC not connected, cc5.4 triggers:** LEDs offline after every release and at power-up (K2 §8.1); LCD `Waiting for PC` only after a lost host (lease expiry); intentional release and power-up keep the native screen (K1 §8.10, P5-11). Every contract describes the knob after a `disconnect` this way, not as "always `Waiting for PC`" | K1 P5-11 is already a recorded K1 deviation (a release also happens for device configuration and the firmware cannot tell it from a quit); after a clean quit the LEDs show the waiting marks while the LCD shows the native screen until the first native input, which K1 and K2 accept for cc5.4 (K1 OQ-3 settled, §1.1; a later `{"release":true,"offline":true}` if wanted) | K1, K2, K3, K4 |
| VOC-R24 | **No floating-knob tooltip or legend text.** The button `label` is the knob's legend and the Home idle-row word only; the floating knob is click-through (`HTTRANSPARENT`, `WS_EX_TRANSPARENT`) with no button strip, text panel or chrome, so hover text can never show and no desktop legend strings exist in v7. BS's `legend` (built at BS:1297, incl. ` · hold for Home`; drawn at BS:341-349 next to key boxes `1`…`4` and `↻`) is the prototype's own key-hint side panel, not a product surface | FK:47, :92-95; K4 §3 (the floating knob row: `MA_NOACTIVATE`, `HTTRANSPARENT`); K4 defines no tooltip | K1, K3, K4 |
| VOC-R25 | **One clock for presenter timing.** Every timed presenter effect carries `t0` on `time.perf_counter` (QPC); K3's controller clock is that clock in production, and K4 anchors every scheduled leg to `t0` (§7.4) | K3 §2.2, §6.2, §11.1 (C5-53); K4 §0.6, §4.6.4 | K3, K4 |
| **VOC-R26** **[r2.2]** | **Like is add-only, for good.** `UNLIKE_STRATEGY = add_only` is final; the `unlike` op, the outcome `unlike_unsupported`, the moment `unlike` (§1.2, reserved), `knob.meta.like.off` (`Like removed`) and every heart-off animation are withdrawn. A liked row: row heart filled `#FF285A`; Button 3 stays **enabled** with `heart` + `lit:"on"`, which the knob draws as the new tone **`liked`** (LED **PINK 0.30**, resting WARM 0.04; footer **filled heart `#A3244A`**, mask `heartfill`); a press is refused with the Head shake and `Unfavourite in Music app` for 2.2 s; label and hint `Liked` (`[3] Liked`). The wire is unchanged (no new `lit` value): the tone is derived, so a cc5.4 parser, the byte budget and the presentation-4 downgrade need nothing new | R22 CH §1 (authoritative), R22 S01 §2 / §6, R22 BS:827, :1268, :1418; LS (favourites `DELETE` → 400 / 40012) | K1 (tone, ink, mask), K2 (LED), K3 (refusal, label), K4 (hearts, hint) |
| **VOC-R27** **[r2.2]** | **Seek lands when playback resumes.** A jump has landed when the transport has left `TRANSITIONING` (a position report never counts, even one at the target); no resume within `seek_confirm_ms` = **8000** → `not_confirmed` (Head shake, `Didn’t jump · try again`, stay in Seek). The knob holds the frozen target, `Jumping…` and `activity:"pending"` (Working comet) **throughout**: from the first send until the **last** jump lands. Turning during a jump moves the frozen target; **at most one follow-up jump** (the latest target) is sent when the current one lands, and not before 250 ms after the last detent | R22 CH §3; R22 S01 §4b; R22 BS:843-844, :936 (≈ 2.7 s, slow 5 s) | K3 (C5-68), K2 (pending, M33) |
| **VOC-R28** **[r2.2]** | **Play next shows `Finding songs…` until the first song is queued** (`knob.meta.playnext.resolving`): during the Apple lookup and, with a pre-resolved item, until the first insert lands (≈ 0.4–0.5 s); `Queueing… 0 of {n}` is never shown; then `Queueing… {k} of {n}` (≈ 0.5 s per song). The Working comet runs for the whole job. 1–10 s in all is fine | R22 CH §4; R22 S01 §4c; R22 BS:1015, :1275 | K3 (C5-69), K2 (pending, M33) |
| **VOC-R29** **[r2.2]** | **Copy approval pass closed.** Every §9.5 string is approved as listed, except `Speaker group changed` (was `Group changed`) and `Couldn’t open on screen` (was `Can’t open on screen`); the Like refusal is `Unfavourite in Music app`; `toast.start.partial` is `Playing {k} of {n} · {u} songs unavailable` / `1 song`. No "needs approval" flag remains in any contract | R22 CH §2 | all |
| **VOC-R30** **[r2.2]** | **`Finding songs…` holds until song 1's insert is confirmed** (confirmed design point). `knob.meta.playnext.resolving` stays while the job resolves and while `k == 0`, `k` counting **verified** inserts (K3 §5.2.4), so `Queueing… 1 of {n}` first appears when the first insert is confirmed. This matches R22 CH §4 ("before k counts up"). The prototype switches at the end of the lookup (R22 BS:1015: `k = 1` right after the 0.4 / 4.5 s lookup, while song 1 is still being inserted), so the knob shows `Finding songs…` about one insert (≈ 0.5 s) longer than the prototype. No copy change; refines VOC-R28 | R22 CH §4; R22 BS:1015, :1275 | K3 (C5-71) |
| **VOC-R31** **[r2.2]** | **The liked Button 3 is modelled as enabled-with-refusal** (confirmed design point). R22 CH §1 says Button 3 "dims" to PINK 0.30 on a liked row; the contracts keep it **enabled** (`heart` + `lit:"on"`, derived tone `liked`, §2.3 row 4) and the host refuses the press (`unlike_unavailable`, §2.6: Head shake + `Unfavourite in Music app` for 2.2 s, no request). The visible and audible result is the same as a "not available" press (the prototype draws the button `'on'` and answers a press with `knobMeta(…, 2200)` + `fail`, R22 BS:827, :1268); a `dim` state would draw WARM 0.14 with the `#5A5A5A` outline and read as broken. Refines VOC-R26 | R22 CH §1; R22 BS:827, :1268, :1366 | K1 (tone), K2 (LED), K3 (C5-72) |
| **VOC-R32** **[rename]** | **The app is Desk Dial** (user decision, 2026-09-26; lead ruling RENAME; `AN\rename-desk-dial.md`). Display name `Desk Dial` wherever a person reads it (the tray tooltip `Desk Dial · Knob connected`, toasts, `Desk Dial Settings`, `Quit Desk Dial`, the Start-menu shortcut and the `Desk Dial` task, the Apple consent page); slug `DeskDial` for `DeskDial.exe`, `%LOCALAPPDATA%\Programs\DeskDial` and the home `%LOCALAPPDATA%\DeskDial\`. Copy changed here: `knob.sub.offline` is `Open Desk Dial on your PC` with a **no-break space** (U+00A0) between `Desk` and `Dial`, so K1's balanced split is `Open Desk Dial` / `on your PC` (192.2 px, LVGL 198 on one line; 114 / 80 px on two; K1 16.8 E-r), never `Open Desk` / `Dial on your PC`; `settings.knob.ok` drops the brand (`USB · firmware {v}`, `USB` without a version: the column is titled Knob) and `settings.knob.problem` reads `Waiting for the knob on USB. …`; `settings.apple.consent` (K3 §15.3) reads `Allow Desk Dial to …`. The offline screen keeps **no heading** (K1 8.10, P4-8; decided by the lead on 2026-09-26, RN-10). Unchanged, as internal identifiers: the USB identity (`239A:8010`, serial `NANO_D`, product `Nano_D++ (Beta)`, MIDI and HID names), every wire, capability and diagnostics name, the mutex and event names, `NANOD-CREDENTIALS-1`, the `control_center` package and the thread, class and logger names | the user renamed the app; S01:140 and S01:457 carry the old name, and so does the r2.2 design (designer-owned; the UI V2 handoff states the new name) | K1, K3, K4 |

### 13.3 K2's master rulings M13–M31, **[r2.2]** + M32–M33 (recorded here per VOC rule 1; K2 owns them, `ALIVE.md` revision 2 §12.3, formerly ALIVE_R2_DRAFT §12.3)

K2 §12.5 (rev 4) adds the round-2 records **C2** (the host re-sends `progress` on the first Home frame with `playing:true` after one without it), **F1/W2** (the HMI sampler `CCAliveKnob` resets on claim, release and any pass without a ready control), **W1** (`led_drive` / `led_dither` pass through raw and are validated when applied) and ruling **Q1** (the End stop fires on every push into a bound: a read-only FOC accessor, `atLimit` and the attractor past the bound, re-armed after `lim_rearm_ms` 75 ms off the bound; §5, §6.3, §10).

M1–M12 are the crosswalk of §0.3. "Dev." = departs from r2.1 (K2 §12.4 has the reasons).

| Id | Ruling (one line) | Dev. |
|---|---|---|
| M13 | Odd volume: the half-step lights the segment **after** the endpoint; the cursor is `35 + ⌊v/2⌋` (= VOC-R04) | no |
| M14 | Up next classes P 0.14 / N 0.70 / Q 0.45 on absolute `ring.now`; the card is the `ring.card` entry `count − 1`, counted in the window, with no mark and no cursor cell; moments start at its slot | yes (card geometry) |
| M15 | The local cursor re-centres the 20-entry window; untransmitted entries stay unlit; an untransmitted cursor is WARM class 3 | yes (latency) |
| M16 | `started` → wash in its colour, or green bloom when warm; the host omits `playing` while a start is pending and on the `started` frame; the engine skips PLAY/PAUSE in that render | yes (warm start only) |
| M17 | Reduced motion (latched `reducedMotion`): wake, tick, sweep, scatter, reveal dropped; fail stationary; boot, down, bound kept; the scatter PRNG still draws | no |
| M18 | Button tones per §2.3; resting 0.12 when the awake level ≥ 0.5, else 0.04 | no |
| M19 | `down` keeps RC's recipe (= S02 §7), not BS:659's simplified drain | yes (from BS only) |
| M20 | Floating-knob glow: six pre-rendered looks with alpha `GLL·0.95`, tinted per frame | no |
| M21 | The skip sweep starts at the previous cursor | no |
| M22 | A feedback moment holds sleep for its effect's duration | no |
| M23 | The half-wash growth test in integers: `20·abs(k − 15) ≤ min(ms, 300) + 10` | no |
| M24 | Latched tuning fields `ledPink` and `ledVolFull` (§6.2) | no (tooling) |
| M25 | PINK is its own role, never `sat()`, kept under Warm only (= VOC-R21) | no |
| M26 | Host accents: the Generated-sleeve warm-marker entry (GEN index 7) and monochrome apps send 0 | no |
| M27 | Floating knob while hidden: one engine render per posted frame or input (after ≤ 60 catch-up steps of 50 ms), no compose, no present, no timer | no |
| M28 | Pulses run only on the list cursor and the Tracks pair; the level and lap rings never pulse | no |
| M29 | The native handover lasts until the next claim; AL D5's 5 s return of the amber marks is withdrawn | no (removes a departure) |
| M30 | The floating knob draws the ring only, no button strips | yes (from the prototypes) |
| M31 | `activity:"loading"` = the whole list (comet only; wire form `style:"off"` + `loading`); an unloaded entry of a known list = colour 0 + the list's activity, drawn as a warm landmark | no |
| **M32** **[r2.2]** | The liked heart (`heart` + `lit:"on"`) is tone `liked`: PINK at **0.30** (not 0.14), never `sat()`; resting WARM 0.04 by M18; the moment `unlike` (reserved) plays nothing and is never a trigger | no (R22 CH §1) |
| **M33** **[r2.2]** | The Working comet's pending condition covers seek-in-flight (every jump until playback resumes, across a follow-up jump) and play-next-in-flight (the lookup included); the engine reads both through `activity:"pending"`, which K3 must send for the whole span | no (R22 CH §3, §4) |

---

## 14. Handed to K1–K4 (named here, decided there)

| Item | Owner | Status (consistency pass, 2026-09-25) |
|---|---|---|
| Wire form of the Up next Sonos-shuffle card (knob position exists; no landmark, no cursor) | K1 | **done:** `ring.card` (K1 §4.4, VOC-K1a; §3.1); K2 5.1.4 and K3 §5.6.4 use it |
| Presentation-4 downgrade table (final) | K1 | **done:** K1 §2.2 (adopts the §2.2 sketch, plus `ring.card` stripped) |
| Worst-case byte budget with `lit`, `color`, `now`, `card`, `moment/side/color`, `reducedMotion`, ALIVE latched fields, `ledPink` / `ledVolFull` | K1 | **done:** K1 §14.1 (1,400 B; worst Windows frame 1,352 B) |
| VOC-R04, R05, R06, R21 | K2 | **done:** adopted as M13, M3, M3/M31, M25 |
| Confirmation policy per action (when each `ok` + moment is sent) | K3 | **done:** K3 §8 |
| Re-entry timing helper (190 / 200 / 380 / 420 ms) and passive-change rule | K3 | **done:** K3 §6 (legs anchored to `t0`, VOC-R25) |
| Copy approval pass for §9.5 | K3 | **[r2.2] done** (R22 CH §2; VOC-R29): all approved, `Speaker group changed` and `Couldn’t open on screen` rewritten, the Like refusal is `Unfavourite in Music app` (152.7 px). Remaining: the CH "Still open" font check with the real font build (K1 §15.3 `copy`) |
| Live check W4b: does the favourites `DELETE` clear the star on the user's devices? (rev 4) | K3 (OQ-7) | **[r2.2] done**: sent once with the user's approval (2026-09-25 16:03 PDT), refused with HTTP 400, code 40012 (LS); `UNLIKE_STRATEGY = add_only` is final (VOC-R26) |
| Q1 detector and its read-only FOC accessor; `lim_rearm_ms` tuning (rev 4) | K2 §12.5 (engine packages build it) | open: build, twin sequences (K2 §11.4), tune in the turning test |
| Refresh targets and FrameStats per surface id | K4 | **done:** K4 §6 |
| K1 OQ-3: whether the LCD also shows `Waiting for PC` after an intentional release | K1 + K2 together | **settled for cc5.4** (§1.1, VOC-R23): lost-host only; the LED/LCD difference after a quit lasts until the first native input; a later `{"release":true,"offline":true}` if the user wants it |
| Parsing, storage, latched-struct slot, fixtures and budget reserve of `ledPink` / `ledVolFull` | K1 | **done:** K1 §3.1, §3.6, §7.3, §14.1, §15.1 |
| Presenter-event entry point and the `display` / `device` / `refused` handling | K3 | **done:** K3 §2.5 `presenter_event`, §13.1, §13.5 |
| The Home `Play` / `Pause` label and the ≤ 46 px idle-word gate | K3 (label), K1 (gate) | **done:** K3 §3.1 (C5-60); K1 §8.6.3, §15.3 `idle_row`, P5-12 |
| Per-mode check of K3's busy dims against VOC-D07 | K3 | **done:** §2.6 second table; K3 §3.2 (C5-59) |

---

## 15. Revision log (cross-contract review, 2026-09-25)

| # | Finding | Result | Where in this file |
|---|---|---|---|
| 1 | Dims with no designed reason play only the Press moment without a deviation id (R:76, :182 ask for reason + shake) | **applied**: VOC-D07 with two binding conditions; `ignored` rows annotated with what is on screen | §2.6, §13.1 |
| 2 | `ledPink` / `ledVolFull` delegated by K2 M24 to VOC §6.2, missing | **applied**: both fields defined (type, range, latching, gating, settings keys, budget note); K1 carries parsing | §6.1, §6.2, §14 |
| 3 | `windowsButton = 3` literal vs K1's raw `buttonOrder[3]` | **applied**: `windowsButton = buttonOrder[3]` (raw) | §2.5, §6.1 |
| 4 | Two hold mechanisms (K1 deferred `kh` P5-R10 and K3 host fallback C5-8) | **applied**: firmware only; VOC-D06 amended; no host timer; `ks` re-seeds only | §2.5, §6.3, §6.4, §10, §13.1 |
| 5 | `Play/Pause` cannot fit the 46 px idle-row column (K1 OQ-1) | **applied**: VOC-D08, slot-0 label follows the icon (`Play` / `Pause`), in the §9.5 approval pass | §2.1, §2.4, §9.3, §9.5, §13.1 |
| 6 | No path for presenter-initiated closes and refusals | **applied**: VOC-K4-01/02 absorbed (`display`, `device`, `refused`, `knob.meta.stage_unavailable`); VOC-R22 | §7.3, §7.4, §9.5, §13.2 |
| 7 | `disconnect` said "always `Waiting for PC`"; K1 shows it only after a lost host | **applied**: VOC-R23; OQ-3 handed to K1 + K2 | §1.1, §3.2, §7.3, §9.2, §13.2, §14 |
| 8 | Floating-knob tooltip claimed but the knob is click-through and K4 defines none | **applied**: tooltip claim dropped; VOC-R24 (no desktop legend strings in v7) | §2.1, §13.2 |

**Revision 3 (consistency pass, 2026-09-25): the cross-doc changes the K1–K4 fixers listed, applied to all five files.**

| # | Change | Source | Where in this file |
|---|---|---|---|
| 9 | The Up next card is `ring.card` (entry `count − 1`), the only wire form; `ring.unavailable` is stripped on `upnext` | K1 P5-R24 / VOC-K1a; K2 X11 | §2.2, §3.1, §3.2, §6.2, §14 |
| 10 | `ledPink` range `0…0xFFFFFF` with 0 = the built-in PINK (was 1…); kept until reboot; budget +38 B (was ≈ 40 B); K1 now carries them | K2 §3.2, X8 | §6.1, §6.2 |
| 11 | Offline: the native handover lasts until the next claim (the 5 s return is withdrawn); K1 OQ-3 settled jointly for cc5.4 | K2 M29, X10 | §1.1, §3.2, §13.2 VOC-R23, §14 |
| 12 | Loading means the whole list (`style:"off"` + `activity:"loading"`); an unloaded entry of a known list is a colour-0 entry | K2 M31, X7, X11 | §3.1, §3.2 |
| 13 | M13–M31, the engine role `PINK`, the classes `P`/`N`/`Q`, the diag fields `ledShowGapMsMax`, `ledLateShows` recorded | K2 X12, §13 | §0.3, §1.2, §3.3, §6.1, §13.3 |
| 14 | K1's additions VOC-K1a…K1g and K4's VOC-K4-01…04 absorbed | K1 §16.4; K4 §21.3 | §1.2, §3.1, §6.1, §6.2, §7.1, §9.5, §10, §16 |
| 15 | Presenter interface: `t0` (one QPC clock, VOC-R25), the extra payload fields, `upnext_rows` reasons, events `system(motion)`, `snap_result(…, accepted)`, `cancel_result(restored, completed)`, one K3 entry point `presenter_event` | K3 C5-53, C5-54 | §7.4, §8.5, §13.2 |
| 16 | `shuffle_reorder` keeps the Play-next block on "on" too and reads the playing row before every move; Seek drops a pending target on a group change or disconnect; `resolve` sends `include=catalog&limit=100` with the own-params pager; op `playlist_meta` | K3 C5-45, C5-47, C5-50, C5-52, C5-28 | §7.4, §8.2, §8.3 |
| 17 | Snap recipe: `ShowWindowAsync(SW_SHOWNOACTIVATE)` and async `SetWindowPos` only, 800 ms / 600 ms deadlines, no re-maximize on failure; outcome `accepted` | K4 §9.6, S5-32 | §8.4, §8.5, §10, §13.1 VOC-D01 |
| 18 | Copy: K3's line-matching twins (`knob.meta.library_error`, `knob.meta.signin_expired`, `knob.status.sonos_unavailable`, `knob.meta.group_changed`, `knob.status.group_changed`), `Queue changed` (OQ-2), `Home, then Browse` (OQ-6), K4's explorer state-block copy (VOC-K4-04), measured widths | K3 C5-56; K1 OQ-2, OQ-6; K4 VOC-K4-04 | §8.5, §9.2, §9.5 |
| 19 | K3's busy dims checked per mode against VOC-D07: ignored only where their busy line or comet is on screen; elsewhere the busy line is the reason copy and the Head shake plays (new copy `knob.meta.busy.*`, `knob.meta.shuffle.nothing`) | VOC fixer's K3 item; K3 C5-59 | §2.6, §9.5, §13.1 VOC-D07 |
| 20 | `no_length` also above 59,999 s; `sonos_unavailable` on Home uses the `knob.status` twin | K3 C5-51, C5-56 | §2.6 |
| 21 | Item art keys (incl. `sonos_art` on queue rows) and the knob art owner (WP6 `artwork.py`) | K3 C5-57, C5-58; K4 VOC-K4-03 | §7.1 |
| 22 | Glow radii in BS px scaled by ring diameter ÷ 318 | K2 §10.3 item 3; K4 §11.3 | §3.3 |

**Revision 4 (2026-09-25 evening): live-check amendments and the ALIVE merge.**

| # | Change | Source | Where in this file |
|---|---|---|---|
| 23 | **Like** = `POST /v1/me/favorites?ids[songs]=<id>` (202) + a `ratings` read-back of value 1; never `PUT /v1/me/ratings` (it never reached the user's iPhone) | LS, LC 2026-09-25; K3 C5-62 | §8.3, §8.5, §10 |
| 24 | (**[r2.2]** superseded by row 29: add-only is final) **Unlike** behind `UNLIKE_STRATEGY` ∈ {`favorites_delete`, `add_only`}, default `add_only` (the web player's favourites `DELETE` was not sent; no result recorded); never `DELETE /v1/me/ratings` (it did not clear the iPhone's star); new refusal `unlike_unavailable` (not a dim), outcome `unlike_unsupported`, copy `knob.meta.like.unlike_in_music` | LS 22:42–23:01 UTC; K3 C5-63 | §2.4, §2.6, §8.3, §8.5, §9.5 |
| 25 | Heart state from `ratings` only; `catalog_songs` drops `extend=inFavorites` | LS; K3 C5-64 | §8.3 |
| 26 | (**[r2.2]** superseded by row 31: landed = playback resumed, 8000 ms) Seek confirmed when `TRANSITIONING` is left **and** the position is within ±2 s; `seek_confirm_ms` 3000 → 5000; never resent; the clock frozen until then | LC W2; K3 C5-65 | §8.2, §10 |
| 27 | Play next: measured inserts (522 / 560 ms, exact rows, Sonos metadata); pre-resolution of the focused Recently Added item and its neighbours (`prefetch_resolve_rest_ms` 400) | LC W1; K3 C5-66 | §8.2, §8.3, §10 |
| 28 | K2 is `ALIVE.md` revision 2 (the draft merged, kept superseded); K2 §12.5 records C2, F1/W2, W1 and ruling Q1 (End stop on every push; `lim_rearm_ms` 75) | K2 §12.5 | header, §0.1, §0.3, §5, §6.3, §10, §13.3 |

**Revision 5 [r2.2] (2026-09-25, late): the design follow-up r2.2 (R22 CH "r2.2 — follow-up 1 from engineering").** Docs only; ids kept, withdrawn items marked in place so a running build can see what changed.

| # | Change | Source | Where in this file |
|---|---|---|---|
| 29 | **Like add-only is final** (VOC-R26): the favourites `DELETE` was refused (400 / 40012); `unlike` op, `unlike_unsupported`, moment `unlike` (reserved, plays nothing), `Like removed` and the heart-off animation withdrawn; new tone **`liked`** (7): PINK 0.30, resting WARM 0.04, filled `#A3244A` heart (internal mask `heartfill`); the liked button stays enabled and a press is refused with `Unfavourite in Music app` for `like_fail_meta_ms` 2200 + Head shake; save failure `Didn’t save · try again` + Head shake; hint `[3] Liked`; four row-heart looks (K4 §8.3) | R22 CH §1; LS | header, §0.1, §1.2, §2.1–§2.4, §2.6, §3.3, §4.1, §4.2, §7.4, §8.3, §8.5, §9.2, §9.5, §10, §11, §12, §13.2, §13.3, §14 |
| 30 | **Copy approved** (VOC-R29): `Speaker group changed` (147.6 px), `Couldn’t open on screen` (149.1 px), `Unfavourite in Music app` (152.7 px), `toast.start.partial` `… · {u} songs unavailable` / `1 song`; no approval flags remain | R22 CH §2 | §7.4, §8.5, §9.2, §9.5, §14 |
| 31 | **Seek** (VOC-R27): landed = playback resumed (`TRANSITIONING` left), not a position report; `seek_confirm_ms` 5000 → **8000**; frozen target + `Jumping…` + Working comet throughout; turning during a jump moves the target and at most one follow-up jump is sent when the current one lands; 250 ms debounce unchanged | R22 CH §3 | §4.2, §5, §8.2, §8.5, §10, §13.2 |
| 32 | **Play next** (VOC-R28): `Finding songs…` (`knob.meta.playnext.resolving`, 94.7 px) until the first song is queued, then `Queueing… {k} of {n}` at ≈ 0.5 s per song; Working comet throughout; timings recorded (prototype: cached lookup 0.4 s, uncached 4.5 s; live 3.07–6.25 s uncached) | R22 CH §4 | §2.6, §5, §8.2, §9.5, §13.2 |
| 33 | K2 rulings **M32** (liked tone) and **M33** (pending covers seek-in-flight and play-next-in-flight); K3 entries **C5-67…C5-70**; K1 rulings **P5-R29…P5-R30**; K4 ruling **S5-34** | K1–K4 [r2.2] | §0.3, §13.3, §16 |
| 34 | **[r2.2] verification fixes:** §8.3 `unlike` cites R22 CH §1 ("Proposal confirmed…", "Removed: the unlike moment…") and LS's "Conclusion for the build" instead of a quote CH §1 does not contain; §8.2 `seek`: the superseded rev 4 wording ends at the C5-65 parenthetical, and the flush / drop rules (C5-47) and `D ≤ 59,999 s` (C5-51) are restated as in force; §10 `seek_idle_ms` counts from the last landing; rulings **VOC-R30** (`Finding songs…` until song 1's insert is confirmed) and **VOC-R31** (the liked Button 3 is enabled-with-refusal); K3 **C5-71**, **C5-72** | r2.2 verification; R22 CH §1, §4; R22 BS:827, :1015, :1268; LS | §8.2, §8.3, §10, §13.2 |

**Revision 6 [P2a] (2026-09-25, night): K3's phase-2a text amendment.** Docs only; it records what the phase-2a build and review settled. No token, wire field, copy string or LED rule changes.

| # | Change | Source | Where in this file |
|---|---|---|---|
| 35 | `shuffle_reorder` off takes the ledger's Play-next units `[song_id, start_row]` and attributes in two passes (restore = the controller's preview); `jump` lands by the Seek rule (≤ 8 s, polls yield to short jobs; was PLAYING at the row within 2 s); new internal effect `resolve_drop{keep}` (not a service op, never a presenter or wire effect); `group_changed_ms` 2600 for `Speaker group changed`. K3 also adds Appendix A, the grammar-oracle sign-off against the r2.2 prototype (23 differing footer slots, each with its ruling; none undocumented) | K3 C5-73…C5-76, K3 Appendix A | header, §7.4, §8.2, §8.5, §10, §16 |
| 36 | **[P2a] review fixes** (the phase-2a K-docs review KD-R1, R2, R3, R6, R7; **[P3]** limitations 2–3 arise only when the controller does not know the record, row 38): the shuffle-off preview equals the realised order only when the base rows stood in the ledger's start order at Shuffle on (limitations recorded: a reorder without a ledger entry, a queue the companion did not start, a played Play-next row outside the loaded window); K3 **C5-77**, a start drops a waiting Seek follow-up (controller change handed to WP5); `group_changed` per op (a start: no `start_failed` copy, no toast; seek, shuffle and transport: their own failure first, the copy from the next state poll); `seek_confirm_ms` also bounds the Up next `jump` (`start_failed`); K3 Appendix A pinned exactly by a test | K3 §9.5.3, C5-73, C5-74, C5-76, C5-77, Appendix A | header, §8.2, §8.5, §10, §16 |

**Revision 7 [rename] (2026-09-26): the app is Desk Dial.** Copy only; no token, id, wire field or LED rule changes.

| # | Change | Source | Where in this file |
|---|---|---|---|
| 37 | **[rename]** VOC-R32: the app is **Desk Dial**. `knob.sub.offline` holds the name together with a no-break space; `settings.knob.ok` / `.problem` drop the brand; VOC-R11 notes the rename | user decision 2026-09-26, lead ruling RENAME, `AN\rename-desk-dial.md`; K1 16.8 E-r (the offline widths), K3 `settings.apple.consent`, K4 §13's art-cache path | header, §9.3, §13.2 |

**Revision 8 [P3] (2026-09-26): K3's phase-3 additions and the phase-2b VOC errata, applied by the lead's phase-3b decisions.** Docs only; no token, knob wire field, copy string or LED rule changes.

| # | Change | Source | Where in this file |
|---|---|---|---|
| 38 | **[P3]** `windows_cancel` carries the close `reason` (one of §7.3's ids `back` \| `hold` \| `lock` \| `sleep` \| `idle`; K3 owns the payload, §7.4 lists the kinds); the Shuffle-off preview ranks the base rows by the restore record when the controller knows it (its own accepted Shuffle on, or the record loaded at start), so row 36's limitations 2–3 arise only without it; the H5 parse caps: `catalog_songs` ≤ 50 ids per request, `resolve` and `playlist_meta` pages `limit=50` (the mosaic's 100-track window, the duration's 10,000-track reach). **[P2b]** (review KE-R2): `Speaker group changed` in the `error` tone in §8.5 and §10 (R-j) | K3 C5-78, C5-79, §1.2, §9.8.4, §9.8.7, §9.8.8 (WP6-GIL-D1, D3, D5 accepted by the lead 2026-09-26); K3 C5-76, §19 E-j | header, §8.2, §8.3, §8.5, §10, §16 |

**Revision 9 [E-lcd] (2026-09-26): the hardware window rolled binary A back (a dark LCD).** Two additive diag fields and the ladder names; no token, frame field, copy string or LED rule changes here (the LED dither default and floor are K2's, ALIVE.md §9, §12.7).

| # | Change | Source | Where in this file |
|---|---|---|---|
| 39 | **[E-lcd]** diag `lcdMosiSig` (integer: the GPIO-matrix output signal on the LCD data pin, 103 good, 102 binary A's defect) and `build` (`"A"`…`"E"` from `CC_BUILD_BINARY`, absent without a ladder id); binaries **D** (A's pipeline + fixes) and **E** (C's + fixes), A / B / C retired; build flag `CC_BUILD_BINARY`, image marker `cc-build-binary:<n>`, symbol `cc_lcd_mosi_reattach` | K1 §12.3, §12.6.1, 16.9 E-lcd | §6.1, §16 (VOC-K1c, VOC-K1f) |

---

## 16. Additions absorbed from K1, K3 and K4 (VOC rule 1)

| Id | Addition | Where it now lives here |
|---|---|---|
| VOC-K1a | `ring.card` (bool): the Up next Sonos-shuffle card is the last ring entry, identified only by this field; `ring.unavailable` stripped on `upnext` (K1 §4.4, P5-R24) | §3.1, §3.2, §6.2 |
| VOC-K1b | display `Group` 6 `offline` (internal) and the firmware-local offline screen (K1 §8.10) | §1.2 |
| VOC-K1c | K1's diag fields (K1 §12.3); **[E-lcd]** plus `lcdMosiSig` (the GPIO-matrix output signal on the LCD data pin: 103 good, 102 binary A's defect) and `build` (the ladder letter, absent without one) (K1 §12.3, §12.6.1) | §6.1 |
| VOC-K1d | K1's named durations `art_fade_ms`, `ink_fade_ms`, `footer_hide_ms`, `footer_show_ms`, `idle_stagger_ms` and the reveal set (K1 §8.8) | §10 (the reveal set stays in K1 §8.8) |
| VOC-K1e | constants `LAP_COUNT_MAX = 59999`, `FRAME_BUDGET_BYTES_V5 = 1400` (K1 §4.3, §14.1) | §6.2 |
| VOC-K1f | build flags `CC_LCD_DMA`, `CC_LCD_PERIOD_MS`, `CC_ART_ASYNC`; binaries A / B / C; the decode task `ArtDecode` (K1 §12.5, §12.6). **[E-lcd]** `CC_BUILD_BINARY` (1…5 = A…E; image marker `cc-build-binary:<n>`); binaries **D** and **E**, with A, B and C retired; the symbol `cc_lcd_mosi_reattach` (K1 §12.6.1) | §6.1 |
| VOC-K1g | the loading-list wire form `ring.style:"off"` + `activity:"loading"`, and colour 0 for an unloaded entry of a known list (K1 §4.6; K2 M31) | §3.1, §3.2 |
| VOC-K4-01 | close reasons `display`, `device` | §7.3 (VOC-R22) |
| VOC-K4-02 | `refused(surface, busy \| device)` and `knob.meta.stage_unavailable` | §7.4, §9.5 (VOC-R22) |
| VOC-K4-03 | item art keys `art_template`, `art_max`, `art_bg`, `art_ink`, `sonos_art`, `mosaic` | §7.1 |
| VOC-K4-04 | explorer state-block copy `overlay.explorer.recent_empty_title/_help`, `.error_title/_help`; `.signin_title/_help` on both tabs | §9.5 |
| K3 C5-4, C5-59 | dim codes `transport_pending`, `signin_expired`, `list_error`, `shuffling`, `skip_unavailable`, `nothing_next`; wider scopes; the per-mode `ignored` check | §2.6 (second table) |
| K3 C5-28, C5-53, C5-54, C5-55 | op `playlist_meta`; outcome `group_changed`; presenter payload fields and `t0`; events `system(motion)`, `snap_result(…, accepted)`, `cancel_result`; `upnext_rows` reasons; `display` / `device` handling | §7.4, §8.3, §8.5 |
| K3 C5-29, C5-56 | knob copy ids of K3 §15.2–§15.3 (the ones other contracts name are repeated in §9.5) | §9.5 |
| K3 C5-60 | the Home slot-0 label `Play` / `Pause` (VOC-D08) | §2.4, §9.3, §9.5 |
| K3 C5-7 (revised) | wire labels ≤ 16 B only; the desktop `legend.*` strings are withdrawn (VOC-R24) | §2.1 |
| K3 C5-62…C5-66 (rev 4) | Like via the favourites `POST`; `UNLIKE_STRATEGY` (`add_only` default), the refusal `unlike_unavailable`, the outcome `unlike_unsupported`, the copy `knob.meta.like.unlike_in_music`; hearts from `ratings`; the Seek confirmation rule and `seek_confirm_ms` 5000; Play-next pre-resolution; the timers `like_readback_ms`, `like_confirm_ms`, `like_late_check_ms`, `prefetch_resolve_rest_ms` | §2.4, §2.6, §8.2, §8.3, §8.5, §9.5, §10 |
| K2 §12.5 (rev 4) | records C2, F1/W2, W1; ruling Q1 and `lim_rearm_ms` | §0.3, §5, §6.3, §10, §13.3 |
| **[r2.2]** K1 P5-R29, P5-R30; K2 M32, M33; K3 C5-67…C5-70; K4 S5-34 | tone `liked` (7) and mask `heartfill`; moment `unlike` reserved; Like add-only final; Seek landing and follow-up jump; `Finding songs…`; approved copy; four row-heart looks | §1.2, §2.2, §2.3, §2.6, §4.1, §4.2, §8.2, §8.3, §8.5, §9.5, §10, §13.2, §13.3 |
| **[P2a]** K3 C5-73…C5-77 | shuffle-off Play-next units and the two-pass attribution (with the preview's limitations); `jump` landing rule; internal effect `resolve_drop`; `group_changed_ms` 2600 (per op); a start drops a waiting Seek follow-up (C5-77, review) | §7.4, §8.2, §8.5, §10 |
| **[P2b]** K3 C5-76 (lead ruling R-j); K1 16.8 E-j | `Speaker group changed` (`knob.status.group_changed` / `knob.meta.group_changed`) is failure copy in the `error` tone (`#FF8474`, VOC-R10) wherever it shows, for its `group_changed_ms` 2600; the per-op rules are unchanged | §8.5, §10 |
| **[P3]** K3 C5-78, C5-79; K3 §1.2 (the H5 parse caps; WP6-GIL-D1, D3, D5) | `windows_cancel` carries the close `reason` (`back` \| `hold` \| `lock` \| `sleep` \| `idle`, §7.3); the Shuffle-off preview follows the restore record when the controller knows it (no wire change); `catalog_songs` ≤ 50 ids per request, `resolve` and `playlist_meta` pages `limit=50`, `playlist_meta`'s 100-track window and 10,000-track duration reach | §7.3, §8.2, §8.3 |
