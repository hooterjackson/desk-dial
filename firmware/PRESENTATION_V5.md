# Control-center presentation contract v5 (cc5.4 + desktop v7)

Status: **frozen build contract (K1)** for the one combined release **firmware 1.0.0-cc5.4 + desktop v7**, written 2026-09-25 and revised the same day after the cross-contract review (Up next card form, internal-RAM budget, R5 protocol, build ladder, K3 copy widths, twin fades) and in the consistency pass across K1–K4 (the `ledPink` / `ledVolFull` tuning fields, 7.3; the loading-list wire form, 4.6; OQ-1, OQ-2, OQ-3 and OQ-6 settled; the widths of the new knob copy; 16.5 status). Documents only; nothing was built, flashed or run for it. The only build figures quoted are from the existing cc5.3 report and the ALIVE build log of 2026-09-25 (12.4). **[r2.2] Amended (2026-09-25, late) for the design follow-up r2.2** (VOC key `R22`; VOC-R26…R29): the liked heart is a new derived tone `liked` (filled `#A3244A` heart, new internal mask `heartfill`; the wire is unchanged), the moment `unlike` is reserved and never sent, the approved copy and its widths (`Speaker group changed`, `Couldn’t open on screen`, `Unfavourite in Music app`, `Finding songs…`), and `Like removed` is gone; changes are tagged **[r2.2]** and listed in 16.6. **[errata]** Corrected after the phase-2a gate by the lead rulings R-b (the measured `twin_fade` bound), R-c (the offline native sub-line), R-d (audio stays off; no by-ear check) and R-f (the cover decoder's abort hook); each is tagged **[erratum R-x]** and listed in 16.7. **[errata]** Corrected again after the phase-2b gate (2026-09-26) by the lead rulings R-g (a per-class `twin_fade` bound of 36 for the volume-reveal overlap class, which closes WP1-D1), R-j (`Speaker group changed` in the error tone; a host rule) and R-l (the host deviations WP3b-D1…D4 accepted); each is tagged **[erratum R-x]** and listed in 16.8. **[rename]** Amended the same day for the app's new name, **Desk Dial** (user decision; VOC-R32): the offline sub-line's copy and widths (8.6.11, 8.10, P5-3), tagged **[rename]** and listed in 16.8 E-r. No wire, parser, layout or budget change. **[errata]** Corrected after the hardware window of 2026-09-26, which rolled binary A back to cc5.3 (a dark LCD): the LCD data-line fix after `initDMA`, the diag fields `lcdMosiSig` and `build`, and the ladder binaries D and E, tagged **[erratum E-lcd]** (12.3, 12.6, 12.6.1) and listed in 16.9.

It **replaces PRESENTATION_V4.md whenever the knob advertises `presentation: 5`**. V4 stays normative for presentation-4 knobs (cc5.3 and older) and for what the v7 host sends them (section 2.2). Change this contract only together with both adapters and their tests:
- **Python:** `app/control_center/presentation.py` (constants, pure helpers), `device.py` (validation, downgrade, slimming, events), `lcd_preview.py` (the floating knob's LCD mirror).
- **Firmware:** `src/cc_presentation.h` (CCFrame, enums, tones, inks), `src/cc_frame_parse.cpp` (parser), `src/cc_display.cpp/.h` (LCD), `src/control_center.cpp` (capability, `ready`, F24 gate), `src/hmi_thread.cpp` + `src/com_thread.cpp` (`kh`, `ks`, `hid`), `src/lcd_thread.cpp` (offline screen, refresh pipeline), and for the pipeline and RAM items of section 12: new `src/cc_art_decode.cpp/.h` (R5 decode task, 12.5), `src/cc_jpeg.cpp` (decode abort), `src/cc_media_store.h` + `src/cc_media.cpp` (decode pin), `src/audio/WavData22m.cpp` + `src/audio/audio.cpp/.h` + `audio_api.h` (`const` samples, 12.4 F1).

Scope split (V5_VOCABULARY.md, "VOC", §0 and §14): **K1 (this file)** owns the wire semantics, parser, LCD and byte budget. **LED targets, effects and recipes are K2's** (the ALIVE revision); **controller grammar, timers, copy use and confirmation policy are K3's** (`CONTROL_CENTER_V5.md`); **desktop surfaces are K4's**. Every token, id, enum value and copy string is used verbatim from VOC; additions are recorded in section 16.4 with `VOC-K1x` ids. ALIVE.md is not edited by this contract.

**Invariant carried from V4 (P4 header):** presentation never reloads a haptic profile, re-arms a control or moves a detent. Frames are presentation only; only `control` (enter) changes bounds, profile or position.

### Sources and keys

Keys are VOC §0.1's (R, CH, S01…S05, BS, HT, 00, A01…A06, CS, RF0, RF3, AL, P4, AW2, CC, FP, FPA, FD, FA, PR, DV, CT, RT). Extra keys used here: **VOC** = `firmware\V5_VOCABULARY.md`; **CCP** = `src\control_center.cpp`; **LT** = `src\lcd_thread.cpp`; **HM** = `src\hmi_thread.cpp`; **CM** = `src\com_thread.cpp`; **FN** = `src\fonts\cc_fonts.h`; **LP** = `control_center\lcd_preview.py`; **REP** = `harness\cc5_report.py`; **GI** = `harness\export_handoff_icons.cjs` (A04 §0). BS line numbers are the **r2.1** file's. Design precedence: R > S01 > S02 > S03 > S04 > S05 (R §0); feasibility: the engineering analysis with r2.1 applied on top; user decisions are binding (VOC rule 3).

**Design references for the LCD:** S01 §3 (layouts, rendering rules), S01 App A (knob motion rows, S01:515-526), S01 App C (copy sheet), the BS knob markup (BS:279-335) and `renderVals()` (BS:1232-1297). S03 stays in force where S01/BS are silent (idle icon view, Windows tile, base geometry), with its r2 override block (S03:3-26).

### Notation

- LCD pixels on the 240 × 240 face; `{x, y, w, h}` boxes are **LVGL label-top** coordinates: `y = round(CSS top + CSS baseline offset) − ascent`, which is CSS top − 1 for 12/14 lines, CSS top + 1 for 14/18, 16/20 and 22/26 lines, CSS top − 3 for 48/46 (A04 §0; FD:48-49). `22/26` = font size / line height.
- Curves: **OUT** `cubic-bezier(0.22,1,0.36,1)`, **IN** `cubic-bezier(0.4,0,1,1)`, **SPR** `cubic-bezier(0.34,1.45,0.64,1)` (S01 App A).
- Widths quoted as "measured" were computed from `app\assets\fonts\Montserrat.ttf` instanced at wght 500 (the generator's weight), advance widths, no kerning: ±2 px. The LVGL harness is authoritative (section 15.3).

---

## 1. Capabilities (firmware reply to `{"capabilities":"?"}`)

| Key | cc5.3 | **cc5.4** |
|---|---|---|
| `controlCenter`, `leaseMs`, `hostFrame`, `runtimeProfileBounds`, `taggedInput`, `windowsHidKey:"F24"`, `buttonOrder`, `windowsHidControl` | as CC | unchanged (CCP:140-143) |
| `presentation` | 4 | **5** |
| `glyphs` | `"latin-ext-a"` | unchanged |
| `alive` | absent | `{"version":1,"fps":60,"drive":<1..255>}` (AL §1; CCP:147-152) |
| `artwork` (v1) | P4 §1 | unchanged, incl. `composited:"scrim80"` (A04 §2.7 recommendation) |
| `artwork2` | AW2 §1 | unchanged, incl. `composited:"scrim80"` |
| `diag` | 1 | 1; additive v5 fields in section 12.3 |

- **`presentation: 5` implies**, with no further key: the v5 frame fields (sections 3–7), the new tokens, `kh`, `ks` in `ready`, `hid` on `kd`, the F24 icon gate and `reducedMotion` (VOC-R17). There is no `keyHoldMs` key.
- `alive` is negotiated independently (AL §1): a presentation-5 knob without a valid `alive` object gets v5 fields but no ALIVE field.

**Host negotiation (device.py).** `presentation_level(caps)` (DV:154-156) → `v5 = level >= 5`, `v4 = level >= 4`.
- **Trap (must fix in v7):** the artwork2, alive, glyph and v4-frame gates compare against `presentation.PRESENTATION_VERSION` today (DV:184, DV:198, DV:286, DV:545). When that constant becomes 5 they would silently treat cc5.3 as legacy (no artwork2, no Latin glyphs, V4 fields stripped). v7 introduces `PRESENTATION_V4 = 4` and `PRESENTATION_V5 = 5`; those four gates use `PRESENTATION_V4`, only the v5 fields use `PRESENTATION_V5`.

## 2. Compatibility

### 2.1 Matrix

| Host | Knob | Frames sent | Input | LEDs | LCD |
|---|---|---|---|---|---|
| **desktop v7** | **cc5.4** (presentation 5, alive 1) | full v5 (this file) + ALIVE §3 fields | `kd`/`ku`/`kh`, `ks` in `ready`, `hid`, `lim` | ALIVE + K2 master additions | v5 renderer (section 8) |
| desktop v7 | presentation 5 without valid `alive` (not shipped; defensive) | v5 fields, no ALIVE field | as above | knob's own engine from frames | v5 |
| **desktop v7** | **cc5.3** (presentation 4, artwork2, no alive) | **presentation-4 downgrade** (2.2); byte-identical to V4 for inputs without v5 content | `kd`/`ku` only: **no hold**; F24 by `windowsHidEnabled` per control; the host skips logical 3 on Home (no `hid`) | V4 §5 model | V4 renderer |
| desktop v7 | cc5.2 / cc5 (presentation 4, no artwork2) | as the cc5.3 row, v1 art rules (AW2 §2) | as above | V4 | V4 |
| desktop v7 | presentation 2/3 (cc4) | V4 §2 legacy rules (every v4 and v5 field stripped, `notice`→`nowPlaying`, ASCII, button `color` kept) | as V4 | legacy | legacy |
| **desktop v6** | **cc5.4** | presentation-4 frames (v6 tests `>= 4`, DV:545), no ALIVE fields | `kh`, `ks`, `hid` are ignored by v6 (DV `_consume` reads only `p`/`ks`/`kd`/`ku`; the extra `ks` in `ready` is not read, DV:1080-1086) | ALIVE engine from frames and local input (AL §1) | v5 renderer drawing v4 frames (2.3) |
| desktop v6 | cc5.3 | V4 | V4 | V4 | V4 |

### 2.2 Presentation-4 downgrade (v7 host → cc5.3 or older presentation-4 firmware)

`device._frame` applies it (A05 §2.7 decision D8(i); 00 A10). The controller always builds v5 frames. The result must be a valid V4 frame; the V4 slimming and 1,100 B budget apply (P4 §8). **Every row is mandatory**: a V4 parser rejects unknown layout, style and icon tokens, and a rejected frame is fatal on the host (P4 §7).

| v5 content | Sent to presentation 4 |
|---|---|
| `layout:"seek"` | `layout:"tracks"`. `title` := `mmss(ring.index)` (e.g. `1:14`); `subtitle` := the v5 `title` (song); `meta`/`metaTone` kept (`of 4:47`, `Jumping…`, …); `heading:"SEEK"` kept; ring := `{"style":"off","value":0,"index":1,"count":3}` (the position row highlights its centre dot). Same group as Tracks, so entering and leaving Seek never slides (P5-R17) |
| `layout:"explorer"` | `layout:"recent"`, `page` := **1 + tab** (tab 0 → 1, tab 1 → 2) |
| `layout:"upnext"` | `layout:"recent"`, `page` := **1** |
| | With these pages the V4 depth `1 + page` reproduces every r2.1 flip direction on cc5.3: Recent→Explorer +, tab 0→1 +, tab 1→0 −, Explorer→Recent −, Tracks→Up next +, Up next→Tracks −, any → Home − (P5-R18) |
| `ring.style:"lap"` on any other layout | `{"style":"off","value":0,"index":0,"count":0}` |
| `ring.now`, `ring.card` | stripped (the card stays an ordinary last entry; its title `Shuffled by Sonos` is host text) |
| `buttons[j].lit` | stripped (V4 tone rule) |
| `buttons[j].color` | stripped (V4 slimming, DV:450-451) |
| Icon tokens | `expand`→`more`, `clock`→`list`, `playlists`→`list`, `playnext`→`more`, `seek`→`tracks`, `shuffle`→`switch`, `heart`→`more`, `snapleft`→`prev`, `snapright`→`next` (VOC §2.2 sketch, adopted as final). None of these lands on slot 3, so the V4 go rule (slot 3 · play/prev/next/switch) never turns a downgraded icon green |
| `feedback.moment:"unlike"` | the whole `feedback` object is omitted (r2.1 plays nothing for an unlike, BS:829; a V4 green flash would claim a moment the design does not show) (P5-R16). **[r2.2]** A v7 host never builds this moment (Like is add-only, VOC-R26); the row stays only so a stray one can never reach a V4 knob as a green flash |
| any other `feedback.moment` (`queued`, `shuffle`, `like`, `snap`, `started`) | `moment`, `side`, `color` stripped: a plain `{"kind":"ok","seq":…}` (V4 green flash) |
| `reducedMotion`, ALIVE fields (incl. `ledPink`, `ledVolFull`) | stripped (no `alive` on these knobs) |
| `metaTone`/`statusTone:"error"` | kept (V4 draws `#FF8A7A`) |
| `heading` (`RECENT`, `FAVOURITES`, `UP NEXT`, `SEEK`, `TRACKS`, `RECENTLY ADDED`) | kept: at 1 px tracking `RECENT` 55.1, `FAVOURITES` 88.5, `UP NEXT` 60.3, `SEEK` 35.2, `TRACKS` 54.2 px, inside the V4 r104 heading chord (118 px); `RECENTLY ADDED` is V4's special case (FD:558) |
| `control.windowsButton`, `control.windowsHidEnabled` | as for v5 (`buttonOrder[3]`, true only on `home`): cc5.3 honours `windowsHidEnabled` per control (CCP:231-234) |
| hold | none: `kh` does not exist; the controller offers no hold (VOC §2.2) |

What a cc5.3 user loses: hold-to-Home, lit/active pair states (explorer tabs, Shuffle, liked heart (**[r2.2]** the `liked` tone: a liked row shows the plain `more` glyph; the press is still refused by the host with `Unfavourite in Music app`), snap colours), the Seek lap and 48 px time, the Up next levels, the new glyphs and moments, reduced motion on the knob. Nothing in this list is unsafe. The v7 floating knob keeps mirroring with the v5 renderer, so during a firmware rollback its LCD may differ in detail (glyphs, inks, fades) from the cc5.3 knob's; nothing else depends on that.

### 2.3 A v6 host on cc5.4

- cc5.4 accepts every presentation-4 frame exactly as V4 specifies (sections 2–4 of P4 and AL §3), including legacy frames without `layout` (P4 §2): `frames_v4.json` and `frames_alive.json` must pass unchanged against the cc5.4 parser (section 15.2). No v4 fixture uses a v5 token as its invalid example (checked: the invalid tokens are `spiral`, `grid`, `stop`).
- Legacy tokens `home`, `more`, `cancel` keep their masks; `cancel` in slot 0 keeps tone `stop` (`#FF8474`).
- The v5 renderer draws v4 frames with v5 geometry and inks (content-only slide, 240 ms art fades, 170 px meta boxes, `#5A5A5A` dim, `#FF8474` error, r2.1 glyphs for the v4 meaning tokens: `list` = Browse music (notes), `tracks` = Tracks (list), A04 §3.2). A v6 Home (`Play/Pause · Browse · Win · Tracks`) therefore still shows the right glyph per meaning. A v6 host's Home slot-0 label `Play/Pause` (67.4 px) still overflows the 46 px idle-row column on cc5.4 and is ellipsized there: a cosmetic v6-on-cc5.4 limitation only, since a v7 host sends `Play` / `Pause` (VOC-D08, P5-12).
- `RECENTLY ADDED · P{n}` headings keep V4's fallback chain (drop tracking, then `RECENT · P{n}`, then ellipsis) (FD:546-582).
- F24: a v6 host sets `windowsButton = buttonOrder[2]` with HID enabled everywhere; its slot 2 is `win` in every v6 mode (A01 §8 row 5), so the cc5.4 icon gate (11.4) changes nothing for it.
- `kh` (and its `ks`), the `ks` in `ready` and `hid` on `kd` are ignored by v6 (DV:1057-1130: a `kh` message only re-seeds `_pressed` from its correct `ks`; no button event).
- `reducedMotion` is reset to false at every claim (7.1), so a v6 session never inherits a v7 setting.

### 2.4 Firmware (cc5.4) accepting legacy frames (presentation 2 or 3, no `layout`)

Unchanged from P4 §2: `layout` is derived from `mode` (`RECENTLY ADDED`→`recent`, `TRACKS`→`tracks`, `WINDOWS`→`windows`, else `nowPlaying`), button `color` never drives LEDs, tone is derived.

---

## 3. Frame fields

### 3.1 Top-level fields

All text is UTF-8; limits are byte capacities (CCFrame buffer − NUL). Python and firmware truncate at the last whole code point within the capacity; control characters (< 0x20) reject (P4 §3; FPA:254-290). **Scope** = where a valid value is kept; a valid value outside its scope is **stripped silently by both sides** (never a rejection).

| Field | Type / bound | Default | Scope | Meaning in v5 | Since |
|---|---|---|---|---|---|
| `id` | int 1..0x7FFFFFFF | required on `frame` | all | control id | v2 |
| `mode` | text ≤ 24 | required | all | legacy mode title; **never read by a v5 renderer when `layout` is present** (3.5) | v2 |
| `target` | text ≤ 64 | required | — | legacy; not drawn | v2 |
| `value` | text ≤ 64 | required | Home | volume digits (`54%`); `""` elsewhere in v5 (Seek's time comes from the ring, 4.3) | v2 |
| `detail` | text ≤ 96 | required | — | legacy; not drawn | v2 |
| `status` | text ≤ 64 | required | Home | 12 px status line (8.6.1) | v2 |
| `title`, `subtitle` | text ≤ 96 | `""` | per layout (3.4) | title / sub-line | v2 |
| `counter` | text ≤ 24 | `""` | — | legacy; omitted | v2 |
| `activity` | `idle\|loading\|pending\|error\|unavailable\|offline` | `idle` | all | LED only (pulses, Working comet, Home-offline endpoint; K2). **The LCD never reads it** | v4 |
| `layout` | `nowPlaying\|volume\|idle\|recent\|tracks\|windows\|notice\|`**`seek\|explorer\|upnext`** | derived from `mode` | — | which LCD layout (section 8) | v4, **v5** |
| `restLayout` | `nowPlaying\|idle` | `nowPlaying` | Home | base under a `volume` reveal | v4 |
| `heading` | text ≤ 32 | `""` | all (drawn when non-empty) | caps label at top 32 (8.5.2) | v4 |
| `meta` | text ≤ 96 | `""` | recent, explorer, upnext, notice, tracks, **seek**, windows | 12 px meta line; **on `seek` the 14 px line** (8.6.8) | v4 |
| `titleTone` | `ink\|muted` | `ink` | list, tracks, windows | `#F2F2F2` / `#7C7C7C` | v4 |
| `metaTone`, `statusTone` | `meta\|secondary\|error\|success` | `meta` | meta / status | inks `#7C7C7C` / `#A6A6A6` / **`#FF8474`** (VOC-R10; was `#FF8A7A`) / `#7EE0A2` | v4 |
| `page` | int 0..255 | 0 | recent, **explorer** | recent: V4 page (v7 always 0, flat list, U5); **explorer: tab, 0 = Recently Added, 1 = Favourite playlists** (VOC-N05) | v4, **v5** |
| `volumeVisible` | bool | false | Home | legacy mirror of `layout=="volume"`; validated, not stored | v4 |
| `volumeCaption` | text ≤ 96 | `""` | Home | 14 px reveal caption | v4 |
| `confirmedVolume` | int 0..100 | `ring.value` | Home | Sonos-confirmed volume (LED) | v4 |
| `ledStyle` | `white\|color` | `white` | all | `color` = accents (K2; Settings "Colour"/"Warm only") | v4 |
| `artKey` | `[A-Za-z0-9_-]{0,64}` | `""` | art layouts (8.4) | cover to draw; `""` = no art | v4 |
| `artDim` | bool | false | art layouts | cover at `image_opa` 112 (0.35 over the 0.8 composite) | v4 |
| `iconKey` | `[A-Za-z0-9_-]{0,24}` | `""` | `windows` | app icon (AW2 §6); malformed → **stripped, never a rejection** | cc5.3 |
| `feedback` | object (section 6) | absent | all | LED moment trigger | v4, **v5** |
| `buttons` | exactly 4 objects (section 5) | required | all | footer, idle row, button LEDs | v2, **v5** |
| `ring` | object (section 4) | required | all | ring pattern + Seek time | v2, **v5** |
| `playing` | bool | absent | nowPlaying, volume, idle, notice | ALIVE (AL §3) | cc5.4 alive |
| `clock` | int 0..1439, **latched** | — | all | ALIVE | cc5.4 alive |
| `progress` | `{pos, dur}` ints 0..86,400,000, `pos ≤ dur` unless `dur == 0`, **latched** | — | all | ALIVE | cc5.4 alive |
| `ledDrive` | int 1..255, **latched** | — | all | ALIVE | cc5.4 alive |
| `ledDither` | bool, **latched** | — (unset = off since the 2026-09-26 user ruling, with the F-T floor; K2 9 step 4, 12.7) | all | ALIVE | cc5.4 alive |
| **`reducedMotion`** | bool, **latched** | false (reset at claim) | all | section 7 (VOC-R09) | **v5** |
| **`ledPink`** | int 0..0xFFFFFF, **latched** (0 = the built-in PINK) | — (kept until reboot) | all | LED tuning (7.3; VOC §6.2; K2 §3.2, M24) | **cc5.4 alive** |
| **`ledVolFull`** | bool, **latched** | — (kept until reboot; unset = false) | all | LED tuning (7.3; VOC §6.2; K2 §3.2, M24) | **cc5.4 alive** |

**Gating.** A v7 host sends the **v5** rows (new layout tokens, `page` as tab, `lap`, `now`, `card`, `lit`, button `color`, `moment`/`side`/`color`, `reducedMotion`, new icon tokens) only when `presentation >= 5`, and the ALIVE rows (`playing`, `clock`, `progress`, `ledDrive`, `ledDither`, `ledPink`, `ledVolFull`) only when `alive` is negotiated (AL §1). Otherwise section 2.2 applies.

### 3.2 Text rules

- **Wire text is drawn verbatim** (P4 §3). The renderer fits it (safe chord, balanced two-line split, U+2026 ellipsis) but never invents copy, with three exceptions: the **Seek time** (`m:ss` formatted from `ring.index`, 4.3), the **Windows tile initial** (first code point of `subtitle`, AW2 §7), and the **firmware-local offline screen** (8.10).
- Glyphs: `latin-ext-a` plus `· – — ‘ ’ “ ” • …` (P4 §1). Every VOC §9 knob string is inside that set (`’` U+2019, `…` U+2026, `·` U+00B7).
- Copy ids, texts and placeholders are VOC §9. Which string is sent when is K3's; the elements that draw each string are listed per layout in 8.6.

### 3.3 Parser strictness (identical in `cc_frame_parse.cpp` and `device.py`)

1. A **required** field missing or malformed → reject (firmware) / `ValueError` (host) (P4 §7).
2. A **present optional** field with an invalid value → **reject** on the firmware; the host **strips and logs** it and never sends it (P4 §3; AL §3). Exception kept: `iconKey` is stripped by both (AW2 §6).
3. A **valid value outside its scope** → stripped by both, silently (the rule `playing` and `feedback.skip` already follow, FPA:112-166).
4. **Unknown fields are ignored** (older/newer senders stay compatible).
5. **Order of evaluation** (both sides): validate every present value on every layout → reject/strip invalid → check combinations (6.2, 4.4) → strip out-of-scope values → apply defaults.
6. JSON integers are never bools or floats (`cc_json_uint`, FPA:246-252); tokens match length-aware (FPA:32-44).

### 3.4 Which fields each layout draws

| Layout | heading | title | subtitle | meta (+tone) | status (+tone) | value / volumeCaption | art | footer | ring (expected) |
|---|---|---|---|---|---|---|---|---|---|
| `nowPlaying` | if non-empty | 22/26 · 2 lines | 14 artist | — | 12 status | — | yes | yes | `level` |
| `volume` | if non-empty | (track layer hidden) | — | — | 12 status | digits + caption | yes, unless `restLayout:"idle"` | yes, unless idle base | `level` |
| `idle` | — | — | — | — | hidden | — | no (fades out) | hidden; the idle row draws button labels | `level` |
| `notice` | if non-empty | 22/26 · 2 lines | 14 | 12 | — | — | no | yes | `level`/`off` |
| `recent` | `RECENTLY ADDED` | 22/26 · 2 lines | 14 artist | 12 | — | — | yes (`artDim`) | yes | `selection`/`off` |
| **`explorer`** | `RECENT` / `FAVOURITES` | 22/26 · 2 lines | 14 artist / `{n} songs` | 12 | — | — | yes | yes | `selection`/`off` |
| **`upnext`** | `UP NEXT` | 22/26 · 2 lines | 14 artist | 12 | — | — | yes | yes | `selection` (+`now`, `card`)/`off` |
| `tracks` | `TRACKS` | 22/26 · **1 line** | 14 line | 12 | — | — | yes | yes | `transport` |
| **`seek`** | `SEEK` | **14 caption** (song) | — | **14 line** | — | **time from ring** | yes | yes | `lap` |
| `windows` | — | 16/20 · 2 lines | 14 app | 12 | — | — | **no** (fades out) | yes | `selection` |

### 3.5 `mode` values (informational)

A v5 renderer never reads `mode` when `layout` is present, and every v5 frame carries `layout`. The host (K3's mode titles, VOC-N04) should still send values that derive the right layout under the legacy rule (2.4): Home layouts any value other than the three legacy strings (e.g. `HOME` or `VOLUME`); `recent`, `explorer`, `upnext` → `RECENTLY ADDED`; `tracks`, `seek` → `TRACKS`; `windows` → `WINDOWS`.

### 3.6 Storage (CCFrame / Python)

Append-only enums (VOC §1.2): `CCLayout` 7 `CC_LAYOUT_SEEK`, 8 `CC_LAYOUT_EXPLORER`, 9 `CC_LAYOUT_UPNEXT`; `CCRingStyle` 4 `CC_RING_LAP`; `CCIcon` 13 `expand` … 21 `snapright`; `CCButtonTone` 5 `CC_TONE_ON`, 6 `CC_TONE_OFF`, **[r2.2] 7 `CC_TONE_LIKED`** (derived, 5.2 row 4; never parsed from the wire); new `CCButtonLit` 0 absent, 1 on, 2 off (**[r2.2]** unchanged); new `CCFeedbackMoment` 0 none, 1 `queued`, 2 `shuffle`, 3 `like`, 4 `unlike`, 5 `snap`, 6 `started` (**[r2.2]** 4 `unlike` is **reserved**: both parsers keep accepting and storing it, so the enum, the parsers' moment tables and the fixtures do not change, but no v7 host sends it and K2 plays nothing for it; P5-R30). New storage (≈ +26 B on the ~1,040 B struct, copied ≈ 6 times, A04 §5.1):

```
CCButton: uint8_t lit = 0;            // CCButtonLit
CCFrame:  int32_t ringNow = -1;       // -1 none (stripped outside upnext/selection); int32_t like
                                      // ringMoreIndex (cc_presentation.h:71): `now` reaches 65,534
                                      // (4.1), which an int16_t would wrap to a negative index
          bool    ringCard = false;
          uint8_t feedbackMoment = 0; // CCFeedbackMoment, 0 unless kind ok
          int8_t  feedbackSide = 0;   // -1/1 with snap only
          uint32_t feedbackColor = 0; // snap/started only
          bool reducedMotionPresent = false, reducedMotion = false; // latched (section 7)
          bool ledPinkPresent = false;    uint32_t ledPink = 0;     // 0..0xFFFFFF, latched (7.3)
          bool ledVolFullPresent = false; bool ledVolFull = false;  // latched (7.3)
```

`ledPink` and `ledVolFull` sit next to `ledDrive` / `ledDither` (cc_presentation.h:82-85) and are latched into the same ALIVE struct on acceptance (AL §3; K2 §3).

The display clamp `layoutId <= CC_LAYOUT_NOTICE` (FD:1252-1253) becomes `<= CC_LAYOUT_UPNEXT`; otherwise the new layouts render as Home (A04 §10 risk 9). Python: `presentation.LAYOUTS += ("seek","explorer","upnext")`, `RING_STYLES += ("lap",)`, `ICONS +=` the nine new tokens, `BUTTON_LIT = ("on","off")`, `FEEDBACK_MOMENTS = ("queued","shuffle","like","unlike","snap","started")`, `LAP_COUNT_MAX = 59999`, `FRAME_BUDGET_BYTES_V5 = 1400`, `INK_ERROR = 0xFF8474`, `FOOTER_INK` gains `on`/`off` and `dim = 0x5A5A5A`, **[r2.2]** and `liked = 0xA3244A` (`FEEDBACK_MOMENTS` keeps `"unlike"` as the reserved value; the controller never emits it, K3 C5-67).

---

## 4. Ring object

### 4.1 Fields

| Field | Type / bound | Default | Meaning |
|---|---|---|---|
| `style` | `off\|level\|selection\|transport\|`**`lap`** | required | pattern (LED math: K2) |
| `value` | int 0..100 | required | `level`: displayed volume; send 0 elsewhere |
| `index` | int 0..65535 | required | `selection`/`transport`: absolute selected entry; **`lap`: target seconds** |
| `count` | int 0..65535 | required | `selection`: entries (incl. the Up next card, 4.4); `transport`: 3; **`lap`: duration D seconds** |
| `first` | int | derived | first transmitted entry (4.2) |
| `colors` | ≤ min(20, count − first) ints 0..0xFFFFFF | absent | raw accent of entry `first + k` (0 = none → warm); `selection` + `ledStyle:"color"` only |
| `unavailable` | int < `1 << min(20, count − first)` | 0 | bit k: entry `first + k` unavailable / closed; `transport`: bit0 Prev, bit2 Next. **Stripped on layout `upnext`** (4.4) |
| `moreIndex` | int −1..count−1 | −1 | legacy (v6 Recent More); a v7 host never sends it |
| `external` | bool | false | `level`: changed on Sonos |
| **`now`** | int −1..count−1 | −1 | **`selection` on layout `upnext` only**: absolute index of the now-playing row (VOC §3.1, VOC-R16) |
| **`card`** | bool | false | **`selection` on layout `upnext` only**: the last entry (`count − 1`) is the "Sonos is shuffling the rest" card (4.4) (**VOC-K1a**) |

### 4.2 Window rule (VOC-R03)

- **v5 host rule:** `first = 0` when `count ≤ 20`, else **`first = clamp(index − 10, 0, count − 20)`** (S01:166 "focus 10 from the window start"; BS:1319, :1326). A v5 host **always sends `first` when `count > 20`**, even when it is 0 — slimming never omits it there (P5-R9). Reason: with `first` omitted the parser derives V4's `clamp(index − 9, …)`, which differs at `index = 10` and would drop the colours (they are kept only when the derived `first` is 0, P4 §4).
- **Parser (unchanged from P4 §4):** a present `first` must satisfy `0 ≤ first ≤ index < first + 20` and be 0 when `count ≤ 20`, else reject; an absent `first` is never rejected and is derived as V4's `clamp(index − 9, 0, count − 20)` for legacy senders (`rules.absentFirst`).
- Colours and mask are relative to the window; lengths per P4 §4. The landmark geometry drawn from the window is K2's (VOC §3.4).

### 4.3 `lap` (Seek) and the Seek time

- Valid only with **`1 ≤ count ≤ 59,999`** and **`index < count`**; otherwise reject (extends FPA:204). `value` is still required (send 0). The upper bound keeps the time ≤ `999:59`, which fits the digit rows (8.6.8) (P5-R11); the host offers Seek only for `D ≤ 59,999 s` (K3).
- `index` is the **target** second the knob shows (the Seek clock is frozen at the target while seeking and while `Jumping…`, CS §4.2; S01 §4b; **[r2.2]** until playback resumes, ≤ 8 s per jump, and it follows a turn made during a jump, VOC-R27). `count` is D. `T_end = D − 3` is the host's bound (VOC §10 `seek_margin_s`); the ring does not know it.
- **LCD:** on `layout:"seek"` with `style:"lap"` the renderer draws `mmss(index)` (8.6.8). On `seek` with any other style it draws no time. A `lap` ring on another layout is valid; only the LEDs use it (K2).
- `mmss(s)` = `snprintf(buf, 8, "%u:%02u", s / 60, s % 60)`: minutes unpadded, seconds two digits (BS:554). Both ports format identically.

### 4.4 `now` and the Up next card

- **`now`:** JSON int in −1..count−1, else reject. Kept only when `style == "selection"` and `layout == "upnext"`; stripped otherwise (both sides). Played / now / upcoming classes are computed on absolute indices inside the window (K2; A02 F14).
- **`card` (Sonos native shuffle above 60 upcoming rows, S01 §6 Shuffle; BS:1199, :1319-1321):** the card is the **last entry**, `count − 1`, so the knob position and the `{i} / {n}` meta include it (BS `qLen = qNow + 2`, BS:869).
  - Valid only as a JSON bool. `card:true` requires `count ≥ 2` and **`now == count − 2`** (the card always follows the now-playing row; Play next is refused under Sonos shuffle), evaluated after `now` is validated: otherwise **reject**.
  - Kept only on `selection` + `upnext` (stripped elsewhere, together with `now`).
  - **This is the only wire form of the card (VOC-K1a, frozen).** The card is identified **only** by `ring.card == true`, and it is always entry `count − 1`. Nothing else marks it: an `unavailable` bit never identifies the card (P5-R24). The earlier recommendation in ALIVE_R2_DRAFT §13 (card = the Up next entry with its `unavailable` bit set) is **not** adopted and is withdrawn there; K2 keys on `ring.card && j == count − 1`, and K3 sends `card:true` in the Sonos-native-shuffle regime (CC5 §5.6.2, §5.6.4; the changes those contracts need are listed in 16.5).
  - **Host form (for K3):** in that regime the rows are 0 … P − 1 (played + now) and the card at index P, so `count = P + 1`, `now = P − 1`, `card:true`, `index` the focus, `first` by the 4.2 rule, the card's `colors` slot 0 (a colour there has no meaning), `unavailable` 0. The same form covers CC5 OQ-2's H1 variant (`count = 2`, `now = 0`).
  - Meaning for the LEDs (K2): the card entry has **no landmark and no cursor** (S01:166). For the LCD: nothing special; its title `Shuffled by Sonos` and empty sub-line are host text (VOC `knob.title.upnext_sonos_card`).
  - Consequence: near the end of a list longer than 20 rows the transmitted window contains the card, so the landmark window is shifted by one entry against BS, which windows over the real rows only (P5-10).
- **`unavailable` on `upnext` (P5-R24):** Up next rows have no unavailable state in r2.1: BS lights every row of the window at 0.14 / 0.70 / 0.45 with no gap (BS:1318-1321), and a non-catalog row only dims Like (VOC §2.4 `not_catalog`). A v7 host sends `unavailable` 0 on `upnext`. A present mask is still validated (bits beyond the window → reject, P4 §4) and then **stripped silently by both parsers** on layout `upnext` (3.3 rule 3), so no row can ever read as unavailable, or as the card, to K2.

### 4.5 Parsers reject (summary)

P4's list (index ≥ count on selection/transport; bad present `first`; too many colours; mask bits beyond the window) plus: `lap` with `count` outside 1..59,999 or `index ≥ count`; `now` not an int in −1..count−1; `card` not a bool, or `card:true` with `count < 2` or `now ≠ count − 2` (on `selection` + `upnext`). Stripped silently (not rejected): `now`/`card` outside `selection` + `upnext`; a valid `unavailable` on layout `upnext`.

### 4.6 Loading lists and unloaded entries (K2 M31; VOC-K1g)

- **A whole list loading** (the first page of Recently Added, a Favourite playlists tab with no cache, Up next before its first window lands): the host sends **`ring.style:"off"`** (`value` 0, `index` 0, `count` 0) with **`activity:"loading"`**. The LEDs show only the Working comet (K2 5.1.3 case 1); the LCD shows the host's `Loading…` / `Loading queue…` meta. A `selection` ring with `activity:"loading"` is still valid and draws the same on the LEDs.
- **An entry that is not loaded yet inside a list whose `count` is known** (a fast spin outran the prefetch; an Up next placeholder row after the first window): an ordinary `selection` ring whose `colors` slot for that entry is **0** (warm), with the list's own `activity` (`idle`, or `pending` while Play next runs), never `loading`. The LEDs keep every landmark and the local cursor keeps running (K2 5.1.3 case 1, 6.3); the LCD shows the host's `Loading…` meta with an empty title.
- Nothing in the parser distinguishes the two; this is the host's rule (K3 §5.2.3, §5.3.4, §5.6.4).

---

## 5. Buttons: icons, `lit`, `color`, tones and LCD inks

### 5.1 Wire fields per button (`buttons[slot]`, exactly 4; slot = Button n − 1)

| Field | Type | Default | Rule |
|---|---|---|---|
| `label` | text ≤ 16 B | required | legend; also the **idle-row word** (8.6.3; every v7 Home label ≤ 46 px, VOC-D08). K3 owns the strings. There is no desktop tooltip or legend text: the floating knob is click-through (VOC-R24) |
| `enabled` | bool | required | `false` = `dim`; always wins over `lit` and `color` |
| `icon` | token (section 9) | required from v2+ senders | meaning token; unknown → reject (parser) / replaced by `""` (host) |
| **`lit`** | `"on"\|"off"` | absent | pairs and toggles only (explorer tabs, Shuffle, Seek-while-seeking, liked heart, assigned snap side); invalid → reject; no scope strip (tone order handles it). **[r2.2]** `heart` + `lit:"on"` = the focused Up next row is liked (Like is add-only): tone `liked` (5.2 row 4). No new wire value (VOC-R26) |
| `color` | int 0..0xFFFFFF | 0 | parsed as before (FPA:191); **meaningful only with `lit:"on"`** on a non-heart icon: the assigned snap side's raw app colour. The v7 host sends it only then and ≠ 0 (VOC §2.1). PINK is never sent |

There is **no reason field** (VOC-R12): a press on a dimmed button still reaches the host as `kd`.

### 5.2 Tone derivation and LCD inks (first match wins; VOC §2.3)

| # | Condition | Tone | Footer / idle-row ink |
|---|---|---|---|
| 1 | `icon == ""` | `none` | hidden |
| 2 | `!enabled` | `dim` | **`#5A5A5A`** (S01:49; S03 override #17; was `#4A4A4A`) |
| 3 | slot 0 · `cancel` (legacy, v6 hosts) | `stop` | `#FF8474` |
| 4 | `lit:"on"` · `heart` | **[r2.2] `liked`** (was `on` + PINK) | **[r2.2] `#A3244A`, glyph = the filled heart (mask `heartfill`, 9.1)** instead of the stroked `heart` (was `#FF285A` stroked; R22 CH §1; R22 BS:1268 `{fill: I.heart, ink: '#A3244A'}`). The LED is PINK at 0.30 (K2 M32) |
| 5 | `lit:"on"` · `color ≠ 0` | `on` + accent | `accent_ink(color)` (5.3) |
| 6 | `lit:"on"` | `on` | **`#FFFFFF`** (BS:1233) |
| 7 | `lit:"off"` | `off` | **`#7A7A7A`** |
| 8 | slot 3 · `icon ∈ {play, prev, next, switch}` | `go` | `#6ED996` |
| 9 | Home layout (`nowPlaying`/`volume`/`idle`/`notice`) · slot 0 · `play` | `go` (paused Play; the breath is LED-only) | `#6ED996` (S01:46, :105; U1) |
| 10 | otherwise | `nav` | `#E6E6E6` |

- "Only Button 4 is green", except paused Home Play (R:74-75; CH §7 #1). The go rule stays correct for every v5 map (A04 §3.3): Seek, Play next, the pairs and Home `win` are never green.
- **Ink changes crossfade** 160 ms OUT (S01 App A "Footer icon ink", S01:524), per channel in 8-bit sRGB, on footer icons, idle icons and idle words (P5-R6). An icon glyph change is instant; its ink crossfades from the ink shown.
- The LED colour and level of every tone (0.14 / 0.30 / 0.70 / 1.0, PINK, `sat()`, GREEN breath, resting rules) are **K2's** (VOC §2.3 columns). **[r2.2]** `liked` is PINK at 0.30, resting WARM 0.04 (K2 5.3, M32).
- `cc_button_ink(frame, slot)` replaces `cc_footer_ink(tone)` at its call sites (FD:830-834, FD:931-932), because rows 4–5 need the button, not just the tone. **[r2.2]** The footer glyph choice follows the tone too: `cc_button_icon(frame, slot)` returns the `heartfill` mask for tone `liked` and the token's own mask otherwise; the glyph swap is instant and the ink crossfades 160 ms from the ink shown (the rule below), so a like that lands shows the filled heart at once and its ink eases to `#A3244A`.

### 5.3 LCD accent ink (snap sides) and the Windows tile colour

`accent_ink(c)`, identical in C++ and Python, integer in/out:
1. `c == 0`, or `sat(c)` (AL §2) falls back to WARM (`max − min < 30`) → `#FFFFFF` (the plain `on` ink) (P5-6).
2. `s = sat(c)`.
3. For `j = 0..8`: `m_j = s + ((255 − s)·j + 4) / 8` per channel (integer); return the first `m_j` whose relative luminance (sRGB → linear, `0.2126 R + 0.7152 G + 0.0722 B`) is **≥ 0.10** (≥ 3:1 against black). `j = 8` is white.

Reason: VOC-D02 moves the snap ink from the raw colour to `sat()` for legibility (A04 §2.10 risk 11), but `sat()` alone leaves pure blue at 2.4:1; the lift reaches 3:1 without changing the LED (P5-5). Example: navy `0x000080` → `sat` `0x0000FF` → `j = 2` → `0x4040FF`.

**Windows tile fallback** (no app icon): tile background `sat(ring.colors[index − first])` when that accent is present and ≠ 0 and `sat` does not fall back, with a `#FFFFFF` Medium-500 16 px initial (00 §3.2; BS:322 draws weight 700, P5-7); otherwise V4's `#444444` tile with a `#F2F2F2` initial (AW2 §7).

---

## 6. Feedback object

### 6.1 Fields

| Field | Type / bound | Rule |
|---|---|---|
| `kind` | `"ok"\|"err"` | required when present |
| `seq` | int 1..0x7FFFFFFF | a new value triggers exactly one moment; seeded without effect by the first frame after a claim (P4 §5.8; AL §6.4) |
| `skip` | int −1\|1 | ALIVE (AL §3): kept only with `ok` |
| **`moment`** | `queued\|shuffle\|like\|unlike\|snap\|started` | kept only with `ok`; stripped with `err`. **[r2.2]** `unlike` is reserved: still valid for both parsers (stored 4), never sent by a v7 host, plays nothing (K2 6.4 row f; P5-R30) |
| **`side`** | int −1 (left) \| 1 (right) | kept only with `moment:"snap"` |
| **`color`** | int 0..0xFFFFFF (0 = warm) | kept only with `moment:"snap"` or `"started"`; raw (the knob applies `sat()`, K2) |

### 6.2 Validation (both parsers)

1. Invalid `kind`, `seq`, `skip`, `moment` token, `side` value or `color` range → reject (host: strip that field and log; for `kind`/`seq` the host strips the whole `feedback`, as today, DV:430-433).
2. With `kind:"ok"`: **`skip` and `moment` both present → reject** (host: strips `moment`, `side`, `color` and logs); **`moment:"snap"` without `side` → reject** (host: strips `moment`).
3. Scope strip: `moment` with `err`; `side` without `snap`; `color` without `snap`/`started` — silently, both sides.

What each moment plays (sweep from 0, scatter, pink bloom, nothing (the reserved `unlike`, **[r2.2]** never sent), half-wash, started wash) and the target-flash suppression are K2's (VOC §4.2, VOC-R07/R08). When the host sends each `ok` is K3's (VOC-D03).

---

## 7. Latched fields

### 7.1 `reducedMotion` (VOC-R09)

- JSON bool, else reject. **Latched** on frame acceptance (`frame` or `control`, the same point as ALIVE's latched fields, AL §3), kept until changed, and **reset to false on every claim** (unclaimed → claimed).
- The v7 host sends it in **every `control` frame** and in the first frame after the effective setting changes (Settings `motion`: `system` = Windows *Animation effects*, `full`, `reduced`); it is slimmed away otherwise (14.2).
- LCD effect: section 8.9. LED effect: K2 (VOC §5).
- A frame whose only change is re-sending the same latched value is a heartbeat (no text set, no animation).

### 7.2 ALIVE latched fields

`clock`, `progress`, `ledDrive`, `ledDither` are unchanged (AL §3). `clock` rides in every `control` frame and again after ≥ 600 s; there is no `clock` command (VOC §6.1).

### 7.3 LED tuning fields `ledPink` and `ledVolFull` (VOC §6.2; K2 §3.2, M24)

- **`ledPink`:** a JSON int in **0..0xFFFFFF** (`cc_json_uint`: never a bool, float or string), else reject (firmware) / strip and log (host). **0 = the built-in PINK constant** (the engine's `set_tuning(…, 0, …)`); any other value is the LED colour at full drive that the ring emits for PINK (K2 section 2).
- **`ledVolFull`:** a JSON bool, else reject / strip and log. `true` = the semantic volume body and half-step at 1.00 (U8(b)); `false` = K2's 0.62 / 0.81.
- **Scope:** all layouts. **Gating:** ALIVE rows (3.1): sent only to a knob with `alive`; the host strips them for any other knob, and the presentation-4 downgrade never carries them (2.2).
- **Latching:** on frame acceptance (`frame` or `control`), in the ALIVE latched struct next to `ledDrive` / `ledDither` (3.6). An absent field keeps the latched value. Unlike `reducedMotion` (reset at every claim, 7.1) they survive releases and claims; only a reboot returns them to "unset" (built-in PINK, `ledVolFull` false).
- **Host:** `device.py` adds them at send time, like `ledDrive` (AL §10.2), in **every `control` frame** and only when settings.json has `led_pink` (an int, or a `"#RRGGBB"` string it converts to the int) or `led_vol_full` (bool). No UI. `tools/nanod_alive_tour.py` sends them directly while the companion is quit.
- **LCD:** none. ~~The LCD heart ink stays `#FF285A` whatever `ledPink` is (OQ-5).~~ **[r2.2] Superseded:** the knob LCD's liked heart is the fixed filled `#A3244A` (tone `liked`, 5.2), independent of `ledPink`; `#FF285A` is only the desktop row heart (K4), never an LCD ink (OQ-5).
- **Budget:** +38 B of latched reserve (14.1).

---

## 8. LCD (`cc_display.cpp`, mirrored by `lcd_preview.py`)

### 8.1 Principles (R §3, §5; S01 §3 rendering rules S01:111-118; CH §4)

1. **Translate and opacity only.** No scale, rotation, transform, `opa_layered` or snapshot layers (LVGL heap 64 KB). The r1 scales (volume 0.98/0.93, Windows/idle art 1.06) are gone in r2.1 (CH §4).
2. **60 fps design target** (section 12). Slides ≤ 20 px; fades ≥ 120 ms (every fade below is 140–320 ms).
3. **Only the content layer slides and fades** on a screen change; the cover and footer stay put (S01:116).
4. **Covers swap instantly**, never crossfade; they fade only when shown or hidden: entering/leaving Windows, the idle view, the offline screen (S01:117; S01:522-523).
5. **Text changes at rest:** when a frame changes a meta or status line (not on a screen change), the new text appears and fades in over 160 ms OUT; no counting numbers (S01:118; S01:525-526).
6. **An identical frame is inert:** no text set, no animation, no redraw (P4 §6; REP `heartbeat`).
7. **Text shadow:** a hard `0 1px 0` black at 80 %, drawn as twin labels (8.5.3) (R §5; S01:122).
8. The LCD **never gates art or text on `activity`** (P4 §6).

### 8.2 Tree and layering (A04 §2.1, with r2.1 applied)

```
screen (black)
 └ stage                      no animation any more (V4 faded it, FD:1268)
    ├ art                     240 × 240 cover; never translates; fades only on show/hide (8.4)
    ├ content                 translate_x ±20 and opacity on a screen change (8.7)
    │  ├ heading (+twin)
    │  ├ home { track{title, artist}, volume{caption, digits, percent}, status, idle[4] }
    │  ├ list { title, sub, meta }              recent · explorer · upnext · notice
    │  ├ tracks { title, pos[3], sub, meta }
    │  ├ seek { caption, time, line }           NEW
    │  ├ windows { tile{letter, icon}, app, title, meta }
    │  └ offline { title, sub }                 NEW, firmware-local (8.10)
    └ footer[4]               MOVED out of content (FD:1223): never slides or fades on a screen change
```

- Z-order: art < content < footer; each twin is created before its label (draws below it).
- The scrim is baked into the cover pixels by the host (8.4); there is no scrim object.
- **Bounded layers** (RF3 R2): every animated layer is sized to its content box instead of `makeFullLayer()` 240 × 240 (FD:1074-1076). Bounds: `content` y 28–156 full width (it slides horizontally); `track` and `volume` the union of their labels; `footer` x 44–196 × y 152–176; `idle[i]` 60 × 48 columns; list/tracks/seek/windows/offline their label unions. The harness proves pixel identity against full-size layers (15.3 `v5_bounded`).

### 8.3 Common geometry and type (R §3; S03 "LCD — shared geometry")

- Canvas 240 × 240; **safe radius 104** for everything except headings, which may reach **r 112** (≈ 138 px; the bezel hides r 112–120) (R:51; S01:125).
- Font Montserrat 500 (`cc_font_12/14/16/22/48` + new `cc_font_48t`, section 10). LVGL line heights / ascents: 12 → 15/12, 14 → 16/13, 16 → 18/15, 22 → 24/20, 48 → 52/43 (FN). Two-line pitch = line height + 2 (`LINE_SPACE`, FD:82): 26 (22 px), 20 (16 px), 18 (14 px).
- Label width = the box width clamped to the safe chord of the label's own ink rows (FD:472-480); ellipsis U+2026 only when the whole text cannot fit (REP `ellipsis_honest`).
- Two-line labels split balanced (`text-wrap: balance` + clamp 2, FD:391-469).
- **Footer:** four 20 px A8 icons, box left x 46/89/131/174 (centres **56/99/141/184**), top **154** (glyph 154–174) (BS:330, :1288; S03 shared geometry). Empty slots stay empty; the others never shift.
- **Inks:** text `#F2F2F2`, secondary `#A6A6A6`, meta `#7C7C7C`, error **`#FF8474`**, success `#7EE0A2`, muted title `#7C7C7C`, disabled position glyph `#555555`, tile `#444444` (S03; VOC §11; VOC-R10).

### 8.4 Art, scrim and art motion

- **Where art shows:** `nowPlaying`, `volume` (not over `restLayout:"idle"`), `recent`, `tracks`, **`seek`**, **`explorer`**, **`upnext`** (add the three to `layoutShowsArt`, FD:1025-1026). Never on `idle`, `windows`, `notice`, the offline screen, or when `artKey` is `""`.
- **Which cover** is the host's `artKey` (K3/K4): Home/Tracks/Seek the now-playing track's album; Recent the focused album; explorer the focused album or a playlist's first mosaic album; Up next the focused row's album; loading items a host-rendered `bgColor` cover, missing art a host-rendered Generated-sleeve cover (S01 §5 Artwork; VOC §7.1 art states).
- **Composite (host, `artwork.py`, WP6):** each 240 px cover (and the v1 120 px cover) is sent pre-composited: `pixel = cover × 0.8 × (1 − s(y))`, `s` evaluated at pixel centres `y + 0.5` by linear interpolation of the r2.1 scrim **(0, 0.60), (108, 0.72), (148.8, 0.92), (168, 1.0)** (0 / 45 / 62 / 70 % of 240), `s = 1` below 168 (R:84 "the darker scrim"; S01:121; A04 §2.7). The capability string stays `"scrim80"`; cover keys are content hashes, so every cover gets a new key and no stale composite is ever mixed (A04 §2.7).
- **Knob draw:** `image_opa` 255, or 112 with `artDim` (0.35 over the 0.8 composite) (P4 §6; FD:1055-1060).
- **Motion** (S01 App A rows "Cover", "Cover (show/hide)", S01:522-523):
  - Key change while the cover is visible and the new key's pixels are ready → **instant swap**.
  - Show (hidden → visible: leaving Windows, idle, offline; a late-arriving cover) → opacity 0 → 255 over **240 ms OUT**, no delay (P5-R3; V4's 60 + 420 ms late fade and 420 ms idle return are replaced).
  - Hide (entering Windows, idle, offline, notice, `artKey:""`) → 255 → 0 over **240 ms OUT** (V4 used 560 ms and an instant cut on Windows).
  - A key with **no pixels in any store** (not uploaded yet) hides at once and never shows the previous cover for the new key (P4 §6 rule kept); it shows with the 240 ms fade when its pixels arrive.
  - A key whose JPEG **is in the store but still decoding** (only when the decode runs off the render path: R5 builds, protocol in 12.5) keeps the previous cover until that decode completes, then swaps instantly; a failed decode hides (P5-R4). A key superseded while decoding is never shown (12.5.4 steps 4–5).
  - A `control` frame that keeps the previous frame's `artKey` (CC5 §6.3, C5-13) is valid in every build: an unchanged key is an art no-op, and the new key in the first frame after `ready` follows the rules above (answer to CC5 OQ-4 in 12.5.5).
  - The first render after the host screen appears snaps (no fade), as V4.

### 8.5 Text rendering

#### 8.5.1 Boxes (all layouts)

| Id | Box `{x, y, w, h}` | Font | Lines | CSS source |
|---|---|---|---|---|
| `HEADING` | **{51, 31, 138, 15}** | 12, tracking 1 px | 1 | left 51, w 138, top 32, 12/14 (BS:295) |
| `HOME_TITLE` | {35, 61, 170, 50} | 22 | 2 | top 60, 22/26 (BS:285) |
| `HOME_ARTIST` | {35, 115, 170, 16} | 14 | 1 | top 114 (BS:286) |
| `STATUS` | {40, 133, 160, 15} | 12 | 1 | x 40, w 160, top 134 (BS:292) |
| `VOL_CAPTION` | {35, 53, 170, 16} | 14 | 1 | top 52 (BS:289) |
| `DIGITS` / `PERCENT` | y 73 / y 96, group centred | 48 (tracking −1) / 22 | 1 | top 76, 48/46; baseline 116 (BS:290; FD:55-57) |
| `LIST_TITLE` | {35, 53, 170, 50} | 22 | 2 | top 52 (BS:296) |
| `LIST_SUB` | {35, 107, 170, 16} | 14 | 1 | top 106 (BS:297) |
| `LIST_META` | **{35, 126, 170, 15}** | 12 | 1 | x 35, w 170, top 127 (BS:298; was {24, 126, 192}) |
| `TRACKS_TITLE` | **{35, 55, 170, 24}** | 22 | 1 | x 35, w 170, top 54 (BS:302; was x 30, w 180) |
| position row | 16 px icons at x **72 / 112 / 152**, y **88** | — | — | x 72–168, top 88, space-between (BS:303-307) |
| `TRACKS_SUB` | {35, 111, 170, 16} | 14 | 1 | top 110 (BS:308) |
| `TRACKS_META` | **{35, 129, 170, 15}** | 12 | 1 | x 35, w 170, top 130 (BS:309; was x 30, w 180) |
| `SEEK_CAPTION` | **{35, 53, 170, 16}** | 14 | 1 | top 52 (BS:313) |
| `SEEK_TIME` | **{0, 73, 240, 52}**, centred | **48t**, tracking −1 | 1 | x 0, w 240, top 76, 48/46, tabular (BS:314) |
| `SEEK_LINE` | **{35, 129, 170, 16}** | 14 | 1 | top 128, 14/18 (BS:315) |
| `TILE` | {104, 42, 32, 32} (initial label y +7) | 16 | 1 | 32 × 32 at x 104, top 42 (BS:322) |
| `WIN_APP` | {35, 81, 170, 16} | 14 | 1 | top 80 (BS:323) |
| `WIN_TITLE` | **{35, 99, 170, 38}** | 16 | 2 | **top 98**, 16/20 (BS:324; CH §4 "title moved to top 98"; was y 101) |
| `WIN_META` | **{35, 139, 170, 15}** | 12 | 1 | **top 140** (BS:325; was {30, 138, 180}) |
| `OFF_TITLE` | **{35, 71, 170, 24}** | 22 | 1 | top 70 (BS:318; S01:140) |
| `OFF_SUB` | **{35, 105, 170, 34}** | 14; **[erratum R-c]** the native line at tracking −1 (8.10) | **2** | top 104, 14/18 (BS:319; P5-3) |
| idle column i | centre x **51 / 97 / 143 / 189**; icon 26 px at top **100**; word box 60 px at y **133** | 12 | 1 | S03 idle view (46 px columns from x 28, glyph–word gap 8) |

Safe chords of these rows (r 104): heading 118 (r 112: **144**), list title 164/194, seek caption 162, seek time **192**, tracks title **168**, offline title 186, offline sub 206, win meta 198, footer 176.

#### 8.5.2 Headings (S01:124-127; CH §4)

- 12 px caps, ink `#A6A6A6`, box {51, 31, 138, 15}, fitted against **min(138, the r 112 chord of its ink rows) = 138 px**.
- Tracking **1 px** (the design's 0.04 em = 0.48 px is not representable: LVGL letter space is an integer) (P5-1). Measured at 1 px: `RECENTLY ADDED` 127.8, `FAVOURITES` 88.5, `UP NEXT` 60.3, `RECENT` 55.1, `TRACKS` 54.2, `SEEK` 35.2 px: all fit.
- Fallback chain for other (legacy) headings: drop tracking; then V4's `RECENTLY ADDED · P` → `RECENT · P` shortening; then ellipsis (FD:546-582). The V4 special case for `RECENTLY ADDED` becomes unnecessary (it fits at r 112).
- The harness safe-circle check allows heading ink out to r 112 (REP `safe_circle`, tolerance widened from "page-1 ≤ 2 px").

#### 8.5.3 Text-shadow twins (R §5; S01:122; A04 §2.8 option B; 00 §3.2)

- For each of **12 labels**: `heading`, `homeTitle`, `homeArtist`, `volumeCaption`, `digits`, `percent`, `listTitle`, `listSub`, `tracksTitle`, `tracksSub`, `seekCaption`, `seekTime` — a sibling twin created **before** the label: ink `#000000`, `text_opa` **204** (0.80), offset **(0, +1)**, same font, tracking, alignment, box, fitted text, lines and visibility; its ink never changes.
- `applyText`, `applyTracking`, `setVisible` and the Home digit/percent reposition (FD:811-820) mirror to the twin. Layer tweens carry twins automatically (same parent).
- **No twins** below y ≈ 125 (meta, status, Seek line, idle words) or on art-less layouts (Windows, offline): the composite there shows ≤ 15 % of the cover (`0.8 × (1 − 0.81)` at y 126) (P5-4).
- **Group fades (P5-13).** A layer's opacity tween fades each label and its twin **separately**: LVGL 9 multiplies the ancestors' `opa` into every label's own draw (`lv_obj_init_draw_label_dsc`, lvgl 9.0.0 in `.pio/libdeps/nanofoc_d`, `src/core/lv_obj_draw.c:150-156`, via `lv_obj_get_style_opa_recursive`, `lv_obj_style.c:640-665`), and 8.1 rule 1 forbids `opa_layered`. At layer opacity `a` a glyph interior shows `a·ink + (1 − a)(1 − 0.8a)·cover` instead of the design's group fade `a·ink + (1 − a)·cover` (BS:282, CSS opacity composites the text shadow with the text); shadow-edge pixels are identical in both (`cover·(1 − 0.8a)`). The difference is `0.8a(1 − a)·cover`, largest at `a = 0.5`: 0.2 × the composite, **≤ 15 of 255 levels** at the twin rows (composite ≤ `255 × 0.8 × (1 − 0.635)` = 74.5 at the heading, y 31). It lasts only while a layer with twins fades: `content` (220 ms, screen change), `track` (150 / 320 ms) and `volume` (180 / 170 ms) (8.8). The harness check `twin_fade` (15.3) bounds it. Hiding the twins during fades was rejected: it would drop the shadow edges, which LVGL draws exactly, and add two tweens per fade.
- **[erratum R-b] Measured bound.** The ≤ 15 above is the float model. LVGL blends the twin and then the label into the RGB565 framebuffer, each blend rounded to 5/6-bit channels (a 5-bit step is 8.2 levels), which the model leaves out: the harness measures **26** over the cover (worst in the `content` fade, 68 under the ink there, 12.7 by the model). The accepted bound is **≤ 28 levels per 8-bit channel inside label ink boxes** (15.3), ~~one bound for every pixel inside them whatever lies under the ink~~ **[erratum R-g]** for every pixel inside them except the overlap class below, confirmed by eye in the hardware window (15.4). ~~**Open (deviation WP1-D1, for the lead; not a bound):**~~ **[erratum R-g] The overlap class.** Where the labels of two fading layers overlap — the volume caption over the home title in both volume reveals (8.8: the track layer fades back in after 90 ms while the volume layer fades out) — the pixel under the caption ink is title ink, not the dark composite, so the float model alone reaches 24 there (0.8a(1 − a) × the title ink, up to 48 at a = 0.5) and **35 is measured**~~, above the ≤ 28 bound: `twin_fade` fails on the two volume reveal-out probes until the lead rules on that class (16.7 E-b)~~. That class has its own bound, **≤ 36 levels per 8-bit channel**: pixels inside a label ink box of the fading layer that are also inside the label ink box of another layer fading in the same capture (two text layers fading over 150–190 ms). The ≤ 28 bound stays for every other pixel inside the boxes. Both are confirmed by eye in the hardware window (15.4); WP1-D1 is closed (16.8 E-g).
- Compile flag `CC_TEXT_TWINS` (default 1). Budget: ≈ 3.0–3.6 KB of LVGL heap; gate `lvglMinFree ≥ 30 KB` with twins on (12.3). If the gate fails, the release is blocked until `LV_MEM_SIZE` is raised within the internal-RAM gate (`heapMinFree ≥ 40 KB`, budget 12.4, where F1 leaves room for it) or the user approves compiling the twins out.

#### 8.5.4 Text at rest (S01:118, :525)

- When a render changes the text of `listMeta`, `tracksMeta`, `winMeta` or `status` **and the screen does not change in that render**, the label's opacity snaps to 0 and fades to 255 over **160 ms OUT**. Titles, sub-lines, captions, the Seek time and the Seek line swap instantly (BS applies the fade only to meta/status, BS:292, :298, :309, :325, :791-797) (P5-R5).
- A hidden line (the status in the idle view) is not un-hidden by this fade; the idle hide wins.
- The offline sub-line swap (8.10) uses the same 160 ms fade.

### 8.6 Per-layout specifications

Copy ids are VOC §9; "when" is K3's policy, repeated here only as the durations VOC §10 names. Tones: `meta` unless stated.

#### 8.6.1 `nowPlaying` (Home at rest) (S01:134; BS:284-292)

| Element | Box | Ink | Wire | Copy |
|---|---|---|---|---|
| Title | HOME_TITLE, 2 lines balanced | `#F2F2F2` | `title` | track title |
| Artist | HOME_ARTIST | `#A6A6A6` | `subtitle` | artist |
| Status | STATUS | `statusTone` | `status` | empty while playing · `Paused` · `Starting…` · `Playing {k} of {n}` (3 s) · `Didn’t start` (**error**, 2.6 s) · `Album unavailable` (**error**, 2.6 s) · reasons `Nothing playing`, `Sonos unavailable` (`knob.status.sonos_unavailable`) · retained v6 `Setting…`, `Changed on Sonos` · K3 §15.2: `Pausing…`, **[r2.2]** `Speaker group changed` (was `Group changed`; 147.6 px ≤ 160; **[erratum R-j]** **error**, 2.6 s), `Connecting knob` |
| Art | full face | — | `artKey` | now-playing album |
| Footer | 4 icons | 5.2 | `buttons` | `pause`/`play` · `list` · `tracks` · `win` |

No room name and no volume number at rest (S03 Home).

#### 8.6.2 `volume` (reveal) (S01 §3 "Volume reveal", S01:151-154; App A S01:517-521; FD:797-822)

| Element | Box | Ink | Wire | Copy |
|---|---|---|---|---|
| Caption | VOL_CAPTION | `#A6A6A6` | `volumeCaption` (else `title`) | `{title}` · `Paused · {title}` · `Nothing playing` · `Now playing` (K3 `knob.caption.now_playing`) |
| Digits | y 73, 48 px proportional, tracking −1 | `#F2F2F2` | `value` (digits and `-` only; FD:803-806) | `54` |
| `%` | y 96, 22 px, 2 px after the digits, group centred on x 120 | `#A6A6A6` | — | `%` |
| Status | STATUS | `statusTone` | `status` | `Minimum` at 0, `Maximum` at 100, `Setting…`, `Changed on Sonos` |

Motion (unchanged from cc5.3, which already matches App A to the millisecond):

| Layer | In (first detent) | Out (1.4 s after the last detent and Sonos confirmed; K3) |
|---|---|---|
| track | opacity → 0 **150 ms IN**; translateY 0 → −8 **190 ms IN** | returns after **90 ms**: opacity 320 ms OUT, translateY −8 → 0 420 ms OUT |
| volume | opacity 0 → 1 **180 ms OUT, delay 50**; translateY +6 → 0 **340 ms SPR, delay 50** | opacity 170 ms IN; translateY → +6 190 ms IN |

`restLayout:"idle"`: the reveal draws over the idle base (art and footer stay hidden).

#### 8.6.3 `idle` (Home idle icon view) (S03 "Home — idle icon view" + r2 overrides; A01 §3.1.2; FD:829-838)

- When: nothing playing, or 4 s after a confirmed pause (K3). Title, artist, status and footer are removed; the art fades out 240 ms (8.4).
- **Row:** four columns centred at x **51 / 97 / 143 / 189**; 26 px icon (stroke 2.1) at top **100**; the 12 px word (the button `label`) at y **133** in a 60 px box; icon and word ink = the button's tone ink (5.2): nothing playing → Play and Tracks `dim` (`#5A5A5A`, S03:135 with the S03:10 override); paused → all active, Play `go` (green).
- **Word width limit:** each Home label must be **≤ 46 px** at 12 px (the design column) so neighbours never touch: `Browse` 45.8, `Tracks` 39.4, `Win` 25.0, `Play` 25.9, `Pause` 37.3 px. r2.1's `Play/Pause` (67.4 px) cannot fit (it would overlap `Browse` by ≈ 10 px and leave the safe circle), so the v7 host sends slot 0's label **following its icon: `Play` or `Pause`** (VOC-D08; K3 C5-60; P5-12; OQ-1 resolved). The idle row only shows while paused or with nothing playing, so it reads `Play`: green when paused, dim `#5A5A5A` when nothing is playing. A v6 host's `Play/Pause` is ellipsized (2.3). The harness `idle_row` check gates every v7 Home label at ≤ 46 px (15.3).
- **Motion:** entry: footer fades out **160 ms IN**; title/artist exit (opacity 150 ms IN, translateY → −10 190 ms IN); art fades out 240 ms OUT; icons enter left to right, each delayed **200 + 45·i** ms, translateY 14 → 0 **460 ms SPR**, opacity **300 ms OUT** (no scale, S03 r2). Exit: icons 140 ms IN (opacity) / 160 ms IN (translate); footer returns **280 ms OUT after 140 ms**; art fades in 240 ms OUT; track returns 320/420 ms OUT after 90 ms.
- A volume turn still reveals the volume layer over the idle row.

#### 8.6.4 `notice` (Home family) (P4 §6; A01 §3.1.3)

List geometry (8.6.5 boxes), no art, footer kept. Retained v6 copy: title `Sonos unavailable` (2 lines at 22 px, 202 px) / sub `Looking for Sonos…` / meta `Windows still works` (VOC §9.4); before the first Sonos read the title is `Looking for Sonos…` (K3 `knob.title.looking_for_sonos`, 2 lines).

#### 8.6.5 `recent` (Recently Added on the knob) (S01:135; BS:295-298, :1265-1271)

| Element | Box | Ink | Wire | Copy |
|---|---|---|---|---|
| Heading | HEADING | `#A6A6A6` | `heading` | `RECENTLY ADDED` |
| Title | LIST_TITLE | `titleTone` (`muted` for an unavailable item) | `title` | album / playlist title · K3 §15.2 list states: `Nothing recently added` (empty), `Apple Music sign-in expired` (sign-in), `Library not loaded` (error) |
| Sub | LIST_SUB | `#A6A6A6` | `subtitle` | artist · K3 §15.2: `Apple Music library`, `Renew on your PC`, `Home, then Browse` (`knob.sub.library_error`, 141.2 px; OQ-6 adopted) |
| Meta | LIST_META | `metaTone` | `meta` | `{i} / {n}` · `{n} / {n} · end` · `Loading…` (whole list, or an unloaded entry, 4.6) · **[r2.2]** `Finding songs…` (K3 `knob.meta.playnext.resolving`, was `Queueing…`; 94.7 px; the lookup, until the first song is queued) · `Queueing… {k} of {n}` (k ≥ 1; `Queueing… 0 of {n}` is never sent) · `Queued next` (1.5 s) · **error** 2.4 s: `Nothing added · retry`, `Partly queued`, `Song changed · retry` · reasons (2 s, meta ink): `AirPlay · use Play`, `Radio · use Play`, `Line-in · use Play`, `Nothing playing · Play`, `Shuffle on · turn it off`, `Not available`, `Sonos unavailable`, `Library not loaded` (K3 `knob.meta.library_error`), `Sign-in expired` (**error**, K3 `knob.meta.signin_expired`), busy reasons `Starting…` (`knob.meta.busy.starting`), `Shuffling…` (`knob.meta.busy.shuffling`) (VOC §2.6 second table) · list states: `Windows still works` (`secondary`) |
| Art | full face | `artDim` for unavailable | `artKey` | focused item |

One flat list (U5): `page` is 0 from a v7 host; the first entry is item 1 (CH §7 #13).

#### 8.6.6 `explorer` (Music explorer mirror) (S01:136; BS:1272-1278)

| Element | Box | Wire | Copy |
|---|---|---|---|
| Heading | HEADING | `heading` | tab 0 `RECENT` · tab 1 `FAVOURITES` (VOC-N09) |
| Title | LIST_TITLE | `title` | focused album / playlist title · empty favourites: **`No favourites yet`** (VOC-R19; 189.4 px at 22 px → two lines) · loading: `""` · favourites sign-in without a cache: `Apple Music sign-in expired` (K3 §5.3) |
| Sub | LIST_SUB | `subtitle` | album: artist · playlist: `{n} songs` (BS:1276) · empty: `Star one in Music` · loading: `""` · sign-in: `Renew on your PC` |
| Meta | LIST_META | `meta` | `{i} / {n}` · `Loading…` · empty: `""` · reasons `Not available`, `Sonos unavailable`, `Library not loaded`, `Sign-in expired` (**error**), **[r2.2]** `Couldn’t open on screen` (was `Can’t open on screen`; **error**, on the parent `recent` after a refused open) · busy reasons `Starting…`, `Queueing… {k} of {n}` / **[r2.2]** `Finding songs…`, `Shuffling…` (VOC §2.6 second table) |
| Art | full face | `artKey` | focused album; playlist: first mosaic album; loading item: `bgColor` cover |

`page` = tab. Ring `off` for an empty list (VOC §3.2). Footer `back` · `clock` (lit on/off) · `playlists` (lit off/on) · `play`.

#### 8.6.7 `upnext` (Up next mirror) (S01:136; BS:1259-1264)

| Element | Box | Wire | Copy |
|---|---|---|---|
| Heading | HEADING | `heading` | `UP NEXT` |
| Title | LIST_TITLE | `title` | focused track title · card: `Shuffled by Sonos` (two lines) · loading placeholder rows: `""` |
| Sub | LIST_SUB | `subtitle` | artist · card and placeholders: `""` |
| Meta | LIST_META | `meta` | `{i} / {n}` · `{i} / {n} · playing` (now row only) · `Loading queue…` · 1.5 s: `Liked`, `Shuffle on`, `Shuffle off · in order`, `Sonos is shuffling` (**[r2.2]** `Like removed` withdrawn: Like is add-only) · reasons: `Checking likes…`, `Not an Apple Music song`, **[r2.2]** `Unfavourite in Music app` (2.2 s, meta ink, a press on a liked row; 152.7 px), `Nothing to shuffle` (`knob.meta.shuffle.nothing`), busy `Starting…`, `Queueing… {k} of {n}` / **[r2.2]** `Finding songs…` · **error**: `Sign-in expired` (2.2 s), `Didn’t save · try again` (**[r2.2]** 2.2 s), `Didn’t shuffle · try again`, `Queue changed` (`knob.meta.shuffle.queue_changed`, 98.4 px; OQ-2 adopted, **[r2.2]** approved), `Sonos unavailable` |
| Art | full face | `artKey` | focused row's album |

`ring.now` and `ring.card` (4.4). Footer `back` · `shuffle` (lit on/off, dim loading) · `heart` (nav / lit on = **[r2.2]** `liked`: the **filled** heart in `#A3244A`, LED PINK 0.30; was the stroked heart in `#FF285A` / dim) · `play`. **[r2.2]** A liked row's heart is never `dim` (it stays enabled; the host refuses the press, VOC §2.6 `unlike_unavailable`).

#### 8.6.8 `seek` (S01:138, §4b; BS:311-316; A04 §2.2)

| Element | Box | Ink | Wire | Copy |
|---|---|---|---|---|
| Heading | HEADING | `#A6A6A6` | `heading` | `SEEK` |
| Caption | SEEK_CAPTION (≤ 162 px chord) | `#A6A6A6` | **`title`** | song title |
| Time | SEEK_TIME, centred on x 120, baseline 116 | `#F2F2F2` | **`ring.index`** with `style:"lap"` | `mmss(index)`, e.g. `1:14`; redrawn per frame, never animated or counted (S01:526) |
| Line | SEEK_LINE | **`#A6A6A6` when `metaTone` is `meta`**, else the tone's ink (P5-R2) | **`meta`** | `of {m:ss}` · `Jumping…` (**[r2.2]** held until playback resumes, ≈ 2.7 s, up to 8 s, across a follow-up jump; the time stays at the frozen target and follows a turn during the jump; VOC-R27) · `Didn’t jump · try again` (**error**, 2.2 s) · `Stops 3 s before end` (1.5 s) |
| Art | full face | — | `artKey` | now-playing album |

- No position row, no meta line (A01 §3.5). `subtitle`, `status`, `value` are ignored.
- **Time font:** `cc_font_48t` (section 10), tracking −1: every `m:ss` of the same number of digits has the same width (`0:00`…`9:59` 108.8 px, `10:00`…`99:59` 141.5 px, `999:59` 174.1 px, all ≤ the 192 px chord of rows 81–116). Proportional digits would jitter up to 9.3 px per detent (A04 §2.2).
- The line is proportional 14 px (P5-2): it is constant for a Seek session (`of 4:47` 47.9 px).
- **Entering/leaving Seek never slides:** `seek` is in group `tracks` (8.7); the tracks and seek layers swap instantly (BS:1415; A01 §3.5). The ring's `transport ↔ lap` change is K2's Reveal.
- Footer while seeking: `back` · `expand` · `seek` lit on · `next` dim.

#### 8.6.9 `tracks` (S01:137, :142-149; BS:300-310, :1250-1258)

| Element | Box | Ink | Wire | Copy |
|---|---|---|---|---|
| Heading | HEADING | `#A6A6A6` | `heading` | `TRACKS` |
| Title | TRACKS_TITLE, 1 line (≤ 168 px chord) | `titleTone` | `title` | `Turn to choose` (166.7 px, tight) · `Previous track` (160.0) · `Next track` |
| Position row | 16 px `prev` at x 72 · `dotfill` at x 112 (6 px disc spanning x 117–123, y 93–99) · `next` at x 152; y 88 | selected (`ring.index`) `#F2F2F2`, others `#7C7C7C`; `prev` `#555555` when `ring.unavailable` bit0 | `ring.index` | — |
| Line | TRACKS_SUB | `#A6A6A6` | `subtitle` | Neutral `Now: {title}` · Next: `Next: {title}` / `End of queue` / `Next: shuffle pick` (Sonos shuffle) / `Next: back to track 1` (repeat all, last song) · Prev: `Prev: {title}` / `Start of queue` / `Prev: last played` (Sonos shuffle) |
| Meta | TRACKS_META | `metaTone` | `meta` | Prev/Next selected `Press 4 to skip` · Neutral `{i} / {n}` / `{i} / {n} · shuffle` · 1.5 s `End of queue` / `Start of queue` (skip refused) · reasons (2 s): `Up next is in Music app`, `Radio · no Up next`, `Line-in · no Up next`, `Nothing playing`, `Can’t seek · AirPlay`, `Can’t seek · radio`, `Can’t seek · line-in`, `Can’t seek · no length` · K3 §15.2: `Skipping…`, `Previous unavailable`, `Next unavailable` (refusal copy, CC5 C5-25) · busy reasons (VOC §2.6 second table): `Starting…`, `Pausing…`, `Queueing… {k} of {n}` / **[r2.2]** `Finding songs…`, `Shuffling…` · **[r2.2]** `Speaker group changed` (`knob.meta.group_changed`, was `Group changed`; **[erratum R-j]** **error**, 2.6 s) · **[r2.2]** `Couldn’t open on screen` (was `Can’t open on screen`; **error**, after a refused Up next open) |
| Art | full face | — | `artKey` | now-playing album |

The next/previous title is shown before the skip (R:87 supersedes S03's "never show the next title"). V4 deviation P4-6 (a muted `Previous track` title with `Previous unavailable` as its standing meta, PRESENTATION_V4.md:327) is retired as a deviation (16.3): r2.1 supplies the lines. K3 keeps `Previous unavailable` / `Next unavailable` only as transient **meta** refusal copy when a direction is not offered (CC5 §3.2 `skip_unavailable`); both fit (126.1 / 102.0 px).

#### 8.6.10 `windows` (S01:139; BS:321-326, :1279-1285)

| Element | Box | Ink | Wire | Copy |
|---|---|---|---|---|
| Tile | TILE | app icon (artwork2 `iconKey`) or letter tile (5.3); closed entry: whole tile group opa **89** (0.35) | `iconKey`, `subtitle` | — |
| App | WIN_APP | `#A6A6A6` | `subtitle` | display app name |
| Title | WIN_TITLE, 2 lines balanced | `titleTone` | `title` | cleaned window title · empty snapshot: `No eligible windows` (K3 `knob.title.no_windows`; 164.4 px at 16 px: one line) |
| Meta | WIN_META | `metaTone` | `meta` | empty (no side assigned) · `Left: {App} · pick right` · `Right: {App} · pick left` · **error** 2.4 s: `{App} not responding`, `Couldn’t move {App}`, `{App} can’t fit half` · retained `Switching…`, `Didn’t come forward · retry` (error), `Closed · can’t switch` |

- **No art:** the cover fades out 240 ms on entry (8.4); no label, count or display info (S03).
- Title line 2 ends above the meta ink with the new tops (REP `windows_meta`).
- Footer `back` (warm, never `cancel`) · `snapleft` · `snapright` (nav, or `lit:"on"` + app colour) · `switch`.

#### 8.6.11 Width check of the knob copy (limits S01 App C: meta/line ≤ 170 px, status ≤ 160 px, heading ≤ 138 px, title 22 px ≤ 170 px)

Every knob string was measured: VOC §9.2/§9.3/§9.4/§9.5 **and K3's knob additions** (CC5 §15.2 kept-v6 ids and §15.3 `knob.*` ids, which CC5 §18 asked K1 to check). Two-line titles are checked per line after the balanced split: line 1 against its chord (164 px for LIST_TITLE), line 2 against the 170 px box. All fit except:

| String | Element | Measured | Limit | Outcome |
|---|---|---|---|---|
| `Queue changed · order kept` (VOC §9.5 `knob.meta.shuffle.queue_changed`, before the consistency pass) | meta 12 | **172.2 px** | 170 | **resolved (OQ-2):** the id's text is now `Queue changed`, 98.4 px (VOC §9.5; CC5 §15.3) |
| `Home, then Browse to retry` (CC5 §15.2 `knob.sub.library_error`, before the consistency pass) | list sub 14 | **197.1 px** | 170 | **resolved (OQ-6):** now `Home, then Browse`, 141.2 px (CC5 §15.2) |
| ~~`Open Nano_D++ on your PC`~~ **[rename]** `Open Desk Dial on your PC` (a no-break space between `Desk` and `Dial`) | offline sub 14 | ~~**197.9 px**~~ **192.2 px** (LVGL 198) | 170 | two balanced lines by design of this contract (P5-3): `Open Desk Dial` 110.4 px (LVGL 114) / `on your PC` 78.0 px (LVGL 80); the no-break space keeps the name on line 1 (16.8 E-r) |
| `Play/Pause` (r2.1's idle word; a v6 host's Home slot-0 label) | idle word 12 | **67.4 px** | 46 | **resolved for v7 (OQ-1):** the label follows the icon, `Play` 25.9 / `Pause` 37.3 px (VOC-D08, P5-12, CC5 C5-60); a v6 host's label is still ellipsized (2.3) |
| `No favourites yet`, `Shuffled by Sonos` | list title 22 | 189.4 / 200.4 px | 2 lines × 164/170 | wrap to two lines (list titles are two-line) |
| `Unfavourite in the Music app` (the Like refusal first proposed, LS) | meta 12 | **176.4 px** | 170 | **[r2.2] resolved by the design:** `Unfavourite in Music app`, 152.7 px (R22 CH §1: 152) |
| `Now: {title}`, `Paused · {title}`, window titles | lines | variable | 170 | ellipsize, as the design's samples do |

K3's knob strings (CC5 §15.2–15.3), measured (Montserrat 500, section Notation, ±2 px):

| Id (CC5) | Text | Element | Measured | Limit |
|---|---|---|---|---|
| `knob.status.starting` · `.pausing` | `Starting…` · `Pausing…` | status 12 | 57.6 · 58.1 | 160 |
| `knob.status.group_changed` | **[r2.2]** `Speaker group changed` (was `Group changed`, 95.5) | status 12 | **147.6** (R22: 147) | 160 |
| `knob.status.connecting` | `Connecting knob` | status 12 | 106.1 | 160 |
| retained (VOC §9.4) | `Setting…` · `Changed on Sonos` · `Minimum` · `Maximum` · `Paused` | status 12 | 52.8 · 115.0 · 59.8 · 62.1 · 45.5 | 160 |
| `knob.caption.now_playing` | `Now playing` | caption 14 | 89.4 | 170 |
| `knob.title.looking_for_sonos` | `Looking for Sonos…` | list title 22 | 216.2 → `Looking` 90.8 / `for Sonos…` 119.5 | 164 / 170 |
| `knob.title.sonos_unavailable` | `Sonos unavailable` | list title 22 | 202.0 → `Sonos` 67.6 / `unavailable` 128.5 | 164 / 170 |
| `knob.sub.looking_for_sonos` | `Looking for Sonos…` | sub 14 | 137.6 | 170 |
| `knob.meta.windows_still_works` | `Windows still works` | meta 12 | 121.8 | 170 |
| `knob.title.recent_empty` | `Nothing recently added` | list title 22 | 266.7 → `Nothing` 92.2 / `recently added` **168.6** | 164 / 170 (tight) |
| `knob.sub.recent_empty` | `Apple Music library` | sub 14 | 136.2 | 170 |
| `knob.title.signin_expired` | `Apple Music sign-in expired` | list title 22 | 310.2 → `Apple Music` 137.3 / `sign-in expired` **167.0** | 164 / 170 (tight) |
| `knob.sub.signin_expired` | `Renew on your PC` | sub 14 | 131.2 | 170 |
| `knob.title.library_error` | `Library not loaded` | list title 22 · meta 12 (`list_error`) | 204.3 → 77.7 / 120.7 · 111.5 | 164 / 170 · 170 |
| `knob.sub.library_error` | `Home, then Browse` (was `Home, then Browse to retry`, 197.1) | sub 14 | 141.2 | 170 (OQ-6 adopted) |
| `knob.meta.library_error` | `Library not loaded` | meta 12 | 111.5 | 170 |
| `knob.meta.signin_expired` | `Sign-in expired` | meta 12 | 92.5 | 170 |
| `knob.status.sonos_unavailable` | `Sonos unavailable` | status 12 | 110.2 | 160 |
| `knob.meta.group_changed` | **[r2.2]** `Speaker group changed` (was `Group changed`, 95.5) | meta 12 | **147.6** | 170 |
| `knob.meta.stage_unavailable` | **[r2.2]** `Couldn’t open on screen` (was `Can’t open on screen`, 129.0) | meta 12 | **149.1** (R22: 149) | 170 |
| **[r2.2]** `knob.meta.like.unlike_in_music` | `Unfavourite in Music app` (rev 4 `Unfavourite in Music`, 125.9) | meta 12 | **152.7** (R22: 152) | 170 |
| `knob.meta.like.failed` | `Didn’t save · try again` (**[r2.2]** approved) | meta 12 | 131.4 | 170 |
| `knob.meta.busy.starting` · `.pausing` · `.shuffling` | `Starting…` · `Pausing…` · `Shuffling…` | meta 12 | 57.6 · 58.1 · 63.7 | 170 |
| `knob.meta.shuffle.nothing` | `Nothing to shuffle` | meta 12 | 110.8 | 170 |
| `knob.meta.shuffle.queue_changed` | `Queue changed` (OQ-2 adopted) | meta 12 | 98.4 | 170 |
| `knob.meta.playnext.progress` (as a busy reason) | `Queueing… 100 of 100` (widest) | meta 12 | 131.5 | 170 |
| `knob.meta.loading` | `Loading…` | meta 12 | 58.2 | 170 |
| `knob.meta.tracks.skipping` | `Skipping…` | meta 12 | 62.6 | 170 |
| `knob.meta.skip.prev_unavailable` · `.next_unavailable` | `Previous unavailable` · `Next unavailable` | meta 12 | 126.1 · 102.0 | 170 |
| `knob.meta.playnext.resolving` | **[r2.2]** `Finding songs…` (was `Queueing…`, 69.1) | meta 12 | **94.7** | 170 |
| `knob.title.no_windows` | `No eligible windows` | Windows title 16 | **164.4** (one line) | 170 |
| retained (VOC §9.4) | `Switching…` · `Closed · can’t switch` · `Didn’t come forward · retry` | meta 12 | 69.7 · 124.0 · 164.6 | 170 |

Closest fits: `Not an Apple Music song` 152.3, `Knob controls still work` 167.5 (14 px; **[erratum R-c]** 171 px with the knob font, the one string the real-font check failed: kept whole on one line at −1 px tracking, 148 px, 8.10), `Didn’t come forward · retry` 164.6, `Waiting for PC` 163.6 (22 px), `Turn to choose` 166.7 against a 168 px chord, and K3's `recently added` 168.6 and `sign-in expired` 167.0 (line 2 of two-line titles, within the ±2 px measurement tolerance of 170). The harness re-measures every string with the real font build (15.3 `copy`, now over VOC §9 **and** CC5 §15.2–15.3), as CH "Still open" asks; a tight string that fails there goes to K3's copy approval pass, never to a smaller font. **[r2.2]** The approval pass itself is closed (R22 CH §2, VOC-R29): every string above is approved, and the four r2.2 strings (`Speaker group changed` 147.6, `Couldn’t open on screen` 149.1, `Unfavourite in Music app` 152.7, `Finding songs…` 94.7) all fit with ≥ 12 px to spare; they match the design's prototype measurements (147 / 149 / 152 px) within 0.7 px. Only the CH "Still open" font check with the real build remains.

### 8.7 Screen change (S01:156-157; S01 App A S01:515-516; A04 §2.3, §2.9)

- **Groups:** `home` = nowPlaying, volume, idle, notice · `recent` · `explorer` · `upnext` · **`tracks` = tracks, seek** · `windows` · `offline` (firmware-local). Display `Group` enum: 0 home, 1 recent, 2 tracks, 3 windows, 4 explorer, 5 upnext (VOC §1.2), **6 offline** (internal, VOC-K1b).
- **Page′** = `page` for groups recent and explorer, else 0.
- **Depth:** home 0 · recent 1 + page′ · tracks 1 · windows 5 · explorer **30 + page′** · upnext **30** · offline — (never slides).
- A screen change happens when `(group, page′)` changes, **except to or from offline** (8.10). Direction: **+20 px when `depth(new) ≥ depth(old)`**, else −20 px.
- **Motion:** `content` translateX from ±20 → 0 over **380 ms OUT** and opacity 0 → 255 over **220 ms OUT**, both starting in the same render. Art and footer do not move or fade (the footer's icons swap and their inks crossfade, 5.2). The stage opacity tween is removed (A04 §2.1; RF3 R2b).
- These depths reproduce every r2.1 flip (VOC §1.1): Recent→Explorer +, tab 0→1 +, tab 1→0 −, Explorer→Recent −, Tracks/Seek→Up next +, Up next→Tracks −, any Play→Home −, Windows→Home −, hold→Home −, Home→Recent/Tracks/Windows +.
- No slide on: a control-id change alone, a Home layout change, a detent, a Tracks re-centre, Seek on/off, Shuffle, Like, Snap, a heartbeat (P4 §6; A01 §1.6).

### 8.8 Motion table (every LCD tween; S01 App A plus the S03 rows App A does not list)

| Tween | Object | Property | From → to | ms | Delay | Curve | Trigger |
|---|---|---|---|---|---|---|---|
| contentTx | content | translateX | ±20 → 0 | 380 | 0 | OUT | screen change |
| contentOpa | content | opacity | 0 → 255 | 220 | 0 | OUT | screen change; offline in/out |
| trackOpa / trackTy | track | opacity / translateY | → 0 / → −8 (−10 idle) | 150 / 190 | 0 | IN | reveal in; idle in |
| | | | → 255 / → 0 | 320 / 420 | 90 | OUT | reveal out; idle out |
| volumeOpa / volumeTy | volume | opacity / translateY | 0 → 255 / +6 → 0 | 180 / 340 | 50 | OUT / SPR | reveal in |
| | | | → 0 / → +6 | 170 / 190 | 0 | IN | reveal out |
| statusOpa | status | opacity | → 0 / → 255 | 240 | 0 | OUT | idle in / out (FD:827) |
| idleOpa[i] / idleTy[i] | idle column | opacity / translateY | 0 → 255 / 14 → 0 | 300 / 460 | 200 + 45·i | OUT / SPR | idle in |
| | | | → 0 / → 14 | 140 / 160 | 0 | IN | idle out |
| footerOpa | footer | opacity | → 0 | 160 | 0 | IN | idle in; offline in |
| | | | → 255 | 280 | 140 | OUT | idle out; offline out |
| artOpa | art | opacity | 0 ↔ 255 | **240** | 0 | OUT | show / hide (8.4) |
| lineOpa (new) | meta / status label | opacity | 0 → 255 | **160** | 0 | OUT | text change at rest (8.5.4) |
| inkFade (new) | footer icon, idle icon, idle word | recolour / text colour | old → new ink | **160** | 0 | OUT | tone change (5.2) |

SPR drives translate only; opacity uses OUT/IN clamped to 0..255 (P4 §6). Tweens use CSS-transition semantics: a changed target retargets from the current value; an unchanged target does nothing (FD:627-645).

### 8.9 Reduced motion (S01 §10, S01:438; VOC-R09)

With `reducedMotion:true` latched, every animation started afterwards follows:
- **Screen change:** no translate (contentTx snaps to 0); content opacity 0 → 255 over **220 ms OUT**.
- **Volume reveal:** opacity only (track and volume translateY targets 0); the opacity timings stay.
- **Idle row:** opacity only (translateY target 0); the 200 + 45·i stagger is kept (S01 §10 is silent on it; it is opacity timing, not motion) (P5-R7).
- Art, footer, meta and ink fades are unchanged (they are fades already).

### 8.10 Offline screen ("PC not connected", firmware-local) (S01:140; BS:317-320; VOC-R11)

- **Trigger (unchanged from CC "Host-lost notice", CC:568-572):** only after a **lease expiry** (host lost), once native control has been fully restored. An **intentional release** and **power-up** keep the native screen, as in cc5.3 (P5-11; OQ-3, settled with K2 for cc5.4).
- **Layout:** no heading, no footer, no art. Title `Waiting for PC` (OFF_TITLE, 22 px, 1 line, `#F2F2F2`; 163.6 px). Sub OFF_SUB, 14 px, two balanced lines, `#A6A6A6`: ~~`Open Nano_D++ on your PC` (→ `Open Nano_D++` / `on your PC`)~~ **[rename]** `Open Desk Dial on your PC` (→ `Open Desk Dial` / `on your PC`; `Desk` and `Dial` are joined by a no-break space, U+00A0, which the balanced split never breaks at, 16.8 E-r); after the **first native input** while it shows (an FOC position change or a button state change while unclaimed: the AL §8.1 definition), `Knob controls still work` (1 line, 167.5 px), faded in 160 ms, kept until the next claim. The V4 `NANO_D++` heading and `Native controls active` are retired (P4-8); **[rename]** the offline screen keeps no heading after the rename (no `DESK DIAL` heading; 16.8 E-r).
- **[erratum R-c] The native line's width.** With the knob font `Knob controls still work` is **171 px** against the 170 px line (LVGL sums whole-pixel kerned advances, `lv_text_get_width`; the design's 167.5 px uses fractional ones), so at 0 tracking the renderer would balance it over two lines. It stays one line with the approved words: when it does not fit its line at 0, the offline sub-line is drawn at **−1 px tracking** (148 px, centred; `cc_display.cpp` `showOfflineSub`, `OFFLINE_NATIVE_TRACKING`). Tracking is K1's integer letter space (8.5.1, 8.5.2's fit step; `applyTracking`), not a smaller font (8.6.11). ~~`Open Nano_D++ on your PC`~~ **[rename]** `Open Desk Dial on your PC` keeps 0 on its two balanced lines. Deviation P5-14 (16.1); checked by eye in the hardware window (15.4). Fallback if the eye check rejects the tighter line: `Controls still work` (130 px at 0 tracking, three of the four approved words) through K3's copy pass.
- **Rendering:** the offline screen is a layer of the host tree, not a separate LVGL screen (today `cc_display_notice_create()` + `lv_screen_load`, LT:303-313), so that the cover can fade: on entry the cover fades out 240 ms OUT, the footer fades out 160 ms IN, the host content is hidden and the offline content fades in 220 ms OUT, **without first loading the native screen** (today one native frame flashes, LT:293-309). Both media display pins are released after the fade (AW2 §4.4).
- **Leaving it:** the next claim's first frame fades the content in (220 ms), shows the cover (240 ms) and returns the footer (280 ms after 140 ms); no slide. An intentional release from there restores `cc_previous_screen` as today.
- Native controls stay active underneath; the offline screen claims nothing and never blocks a reconnect (CC:572).

---

## 9. Icons

### 9.1 Token table (VOC §2.2; glyphs from **r2.1 BS `I`/`HALF`, BS:485-495**)

24-unit viewBox, stroked with round caps and joins unless noted. Sizes by use (A04 §3.3; 00 §3.2 "trimmed per use"): **20 px** stroke 2.3 (footer), **26 px** stroke 2.1 (Home idle row), **16 px** stroke 2.3 (Tracks position row).

| Token (enum) | Meaning | BS key | Path | 20 | 26 | 16 |
|---|---|---|---|---|---|---|
| `""` (0) | none | — | — | — | — | — |
| `play` (1) | Play | `play` | `M7 4.5v15l12-7.5z` | ✓ | ✓ | |
| `pause` (2) | Pause | `pause` | `M8 5v14M16 5v14` | ✓ | ✓ | |
| `list` (3) | **Browse music** | `note` | `M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z` | ✓ | ✓ | |
| `win` (4) | Windows | `win` | `M3 5h18v14H3zM3 9h18` | ✓ | ✓ | |
| `tracks` (5) | **Tracks** | `list` | `M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01` | ✓ | ✓ | |
| `back` (6) | Back | `back` | `M15 18l-6-6 6-6` | ✓ | | |
| `home` (7) | legacy Home | old table | unchanged | ✓ | | |
| `more` (8) | legacy More | old table | unchanged | ✓ | | |
| `prev` (9) | Previous / skip back | `prev` | `M19 5v14l-9-7zM6 5v14` | ✓ | | ✓ |
| `next` (10) | Next / Skip | `tracks` | `M5 5v14l9-7zM18 5v14` | ✓ | | ✓ |
| `switch` (11) | Switch | `check` | `M20 6L9 17l-5-5` | ✓ | | |
| `cancel` (12) | legacy Cancel | old table | unchanged | ✓ | | |
| `expand` (13) | Open on screen | `expand` | `M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7` | ✓ | | |
| `clock` (14) | Recently Added tab | `clock` | `M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0` | ✓ | | |
| `playlists` (15) | Favourite playlists tab | `queue` | `M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3` | ✓ | | |
| `playnext` (16) | Play next | `next` | `M11 12H3M16 6H3M16 18H3M18 9v6M21 12h-6` | ✓ | | |
| `seek` (17) | Seek (handle at 65 %) | `seek` | `M3 12h8.7M17.7 12H21M14.7 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z` (r2.1 redraw, CH §7 #7; A04's r1 path is superseded) | ✓ | | |
| `shuffle` (18) | Shuffle | `shuffle` | BS:492 (5 subpaths) | ✓ | | |
| `heart` (19) | Like (stroked). **[r2.2]** When liked (tone `liked`) the footer draws `heartfill` instead, in `#A3244A`; r2.1's "liked = PINK ink, never filled" is withdrawn (R22 CH §1) | `heart` | `M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z` | ✓ | | |
| `snapleft` (20) | Snap left | `rect` + `HALF.left` | stroke `M3 5h18v14H3z` + **fill** `M3 5h9v14H3z` | ✓ | | |
| `snapright` (21) | Snap right | `rect` + `HALF.right` | stroke `M3 5h18v14H3z` + **fill** `M12 5h9v14h-9z` | ✓ | | |
| *`dotfill`* (internal) | position-row centre | — | filled disc r 4.5 at (12, 12) (6 px at 16 px) | | | ✓ |
| ***`heartfill`*** (internal) **[r2.2]** | liked heart (tone `liked`, footer only) | `heart`, filled (R22 BS:1268 `fill: I.heart`) | the `heart` path above as a **fill path** (`fill="white" stroke="none"`) | ✓ | | |

- Masks: 21 × 20 px + 5 × 26 px + 3 × 16 px = 8,400 + 3,380 + 768 = **12,548 B** (was 21,312 B; −8.8 KB) (A04 §9.1). **[r2.2]** + `heartfill` at 20 px (400 B) = **12,948 B**. `ok`, `warn`, `usb` and the old `dot` are dropped (dead flash, A04 §3.4 item 7).
- A token without a mask at a size makes `cc_icon()` return nullptr and `showIcon` **hide** the glyph (FD:713-728): the 26 px set must cover every token a Home idle row can show (v6 and v7 Home maps use only `play pause list tracks win`).
- **32 px** on the LCD is the Windows **app icon** (artwork2 32 × 32 RGB565 media, AW2 §5), not a mask.
- Desktop-only glyphs never on the wire: BS `note` (sleeve foot), `sleeve`, `album`, `dot`, `rect` (VOC §2.2).

### 9.2 Generation pipeline (WP9; A04 §3.4)

1. `harness/export_handoff_icons.cjs` holds an explicit **token → (stroke paths, fill paths, sizes)** table copied from the r2.1 BS `I`/`HALF` (BS:485-495) (**[r2.2]** plus the internal `heartfill` entry: the `heart` path as a fill path at 20 px; the r2.2 BS `I.heart` string is identical, so the drift gate is unchanged) and checks, on every run, that those strings still occur verbatim in the r2.1 BS file (drift gate). It no longer reads the old `knob-model.js` (GI:23-25).
2. Renders each path with sharp at 16 / 20 / 26 px, strokes 2.3 / 2.3 / 2.1, round caps and joins, `fill="none"` for strokes and `fill="white" stroke="none"` for fill paths; alpha → A8.
3. Writes `src/cc_icons.cpp/.h` (`cc_icon(name, size)`, per-size tables), `assets/handoff-icons` (PNG/SVG) and, after the 1× fidelity gate (GI:64-73), the floating knob's @2x/@3x `assets/lcd-icons`.
4. `--check` regenerates in memory and fails on any byte difference (A6 gate).
5. Lock-step tables: `CCIcon` (FP:20-24, append only), `kIcons` (FPA:24-27), `ICON_NAMES` (FD:102-103), `presentation.ICONS` (PR:63-64), `device._buttons` (DV:315-317), `controller.BUTTON_ICONS` (CT), `lcd_preview.py`.

---

## 10. Fonts

| Face | Use | Glyphs | Notes |
|---|---|---|---|
| `cc_font_12/14/16/22` | all text | unchanged (U+00A0–017F, `– — ‘ ’ “ ” • …`; ASCII through the built-in Montserrat fallback) (FN) | every VOC knob string is covered |
| `cc_font_48` | Home volume digits | unchanged: `%`, `-`, `0–9`, **proportional** | volume stays proportional (BS:290 has no `tabular-nums`) (P5-8) |
| **`cc_font_48t`** (new) | Seek time | `0–9` mapped to Montserrat's **`.tf` tabular outlines** (advance 700/1000 = 33.6 px) + `:` (U+003A, advance 227 → 10.9 px) | same `line_height` 52 / `base_line` 9 (ascent 43) as `cc_font_48`, so y 73 puts the baseline at 116; label tracking −1 px (−0.02 em) (S01:129; CH §4) |

- **Generation (T1, 00 §3.2):** `gen_lvgl_font.py` builds an in-memory copy of the variable font whose cmap maps U+0030–0039 to `zero.tf`…`nine.tf` (fontTools, saved to `BytesIO`, loaded by Pillow), renders 4 bpp Medium 48, and emits `cc_font_48t` (≈ +5 KB flash) (A04 §4.2). `font_tests.py` and `gen_lvgl_font.py --check` cover it.
- **Python mirror:** `lcd_preview.py` uses the same remap for the Seek time and draws the twins (00 G14).
- The 14 px `of m:ss` line stays proportional (P5-2).

---

## 11. Knob → host events, hold and F24

### 11.1 Messages (VOC §6.3)

| Message | Shape | v5 change |
|---|---|---|
| ready | `{"ready":id,"p":pos,"ks":mask}` | **`ks` added**: raw bitmask 0..15 of buttons down when the ready line is built (HMI `keyState` through a new accessor; `control_center.cpp` is not a friend of `HmiThread`, A04 §6.1 item 4) |
| position | `{"id":id,"p":pos}` | — |
| key down | `{"id":id,"ks":mask,"kd":raw[,"hid":1]}` | **`hid:1`** when that same press also sent F24 (11.4) |
| key up | `{"id":id,"ks":mask,"ku":raw}` | — |
| **hold** | `{"id":id,"ks":mask,"kh":raw}` | **new** (11.2) |
| limit | `{"id":id,"lim":-1\|1}` | ALIVE (AL §3): ≤ 1 per 150 ms while ready; in Seek it fires at 0:00 and at `T_end` because positions 0 and `max` map to them (A04 §7) |

Tagging is unchanged: events carry the ready control id and are never replayed after a release or reconnect (CC "Tagging", CC:313). Raw indices on the wire; logical in host events (VOC-N11): `hold {button: logical}`, `button {…, hid: bool}`, `ready {…, held: logical mask}` (VOC §6.4).

### 11.2 `kh` (hold 600 ms = Home; S01:41; VOC-D06; A04 §6.1)

Firmware:
1. **AceButton** (HM:321-322): `setFeature(kFeatureLongPress)` and `setLongPressDelay(600)` on the four configs; **not** `kFeatureSuppressAfterLongPress` (so `kEventReleased` still follows and `keyState` stays right); no repeat.
2. **Claimed branch** (HM:419-435): on `kEventLongPressed` for **raw == `buttonOrder[0]`** (physical slot 0, in force at that moment), queue `KeyEvt{type 4, raw, keyState, cc_input_id(), hid false}`. Long presses of the other raws are ignored.
3. **Native branch** (HM:436-458): ignores type 4 entirely — no `KeyEvt`, no `native_button`, no idle reset: native behaviour stays byte-identical to cc5.3.
4. **COM** (CM:312-331): type 4 → `eventDoc["kh"] = keyNum`, same `id`/`ks` rules as `kd`.
5. **Deferred delivery (P5-R10):** if the long press fires while the session is **entering** (its `KeyEvt` carries id 0), the COM thread latches `pendingHold = raw` (one slot). Immediately after the next `ready` line of the session, if that raw's bit is still set in `keyState`, it sends `{"id":<ready id>,"ks":mask,"kh":raw}`. `pendingHold` clears on that send, on a key-up of that raw (COM sees the `KeyEvt` even when it drops it untagged), on release, and on a new claim. **At most one `kh` per physical press.**
- Timing: 600 ms after the debounced press, sampled at the 10 ms HMI pass → **≈ 620–640 ms after contact** (A04 §6.1). The Back re-entry normally completes within ≈ 200 ms (A04 §6.1); the deferral covers slow entries (e.g. a cover decode on the render path).
- Host: `kh` with `id == ready_id` → `hold` event; the controller's use (Home from any mode; no-op on Home) is K3's. **No host fallback:** the host never times a hold, not even from `ks` at `ready`; the deferred `kh` of step 5 is the only path for a hold that matures during an entry (VOC-D06; CC5 C5-8 withdrawn). A v6 host ignores it (2.3).

### 11.3 `ks` in `ready`

The host re-seeds its pressed mask from it (DV today sets `_pressed = 0` at ready, DV:1085), so an edge lost during entering never leaves a stale "pressed" bit, and a held button is known at ready. Absent (presentation 4) = 0.

**[1.0.0-cc5.5, F1] `ks` on position lines (clear-only).** A position line of the ready control becomes `{"id":id,"p":pos,"ks":mask}` with `mask` = the mask last reported on a `kd` / `ku` / `kh` / `ready` line AND the live mask. It can only clear bits: a press is always reported by its own `kd`; a `ku` lost to a full key queue (16 events since cc5.5, 5 before) is cleared by the next turn. While a key event is still queued, the line repeats the last reported mask, so it never pre-empts a `ku` on its way (the HMI queues a `ku` before it publishes the cleared bit; COM reads the live mask, then the queue). The installed Desk Dial v7, which copies any `ks` into its pressed mask, therefore never loses a `kd` or a `ku` to it (a `ks` equal to the live mask would pre-set the bit of a press whose `kd` is still queued and swallow that `kd`; `tests/test_cc_device_f1.py` replays both). A newer host clears the bits and reports each as a release, before the turn the line carries. No capability: a cc5.4 knob sends no `ks` there.

### 11.4 F24 icon gate (S01:81 "Windows opens only from Home"; A04 §6.2; 00 §3.2)

`cc_is_windows_button(raw)` (CCP:337-342) becomes:

```
phase == ready && !readyReply && windowsHidEnabled && raw == windowsButton
  && frame.buttons[physical(raw)].enabled
  && cc_button_icon(frame.buttons[physical(raw)]) == CC_ICON_WIN      // new in cc5.4
```

- v7 host: `control.windowsButton = buttonOrder[3]` (the **raw** index at physical slot 3; `windowsButton` is raw, CC:229), `windowsHidEnabled = (mode == home)` in every `control` (VOC §6.1); it drops exactly the `kd` edges tagged `hid:1`.
- Without `hid` (presentation 4) the host skips logical 3 on Home when the hotkey is supported (A05 §3 R1): if F24 wins, the picker's re-entry gives a new id and the late `kd` is dropped; if the serial edge wins, it is skipped.
- A v6 host is unaffected (2.3).

---

## 12. LCD performance

### 12.1 Pipeline rules (RF3 §4, §7; RF0 §2.6, §6.3; R §3)

| # | Rule | Source |
|---|---|---|
| R2 | Animated layers bounded to their content boxes (8.2); the volume reveal repaints ≈ 27 %, the footer ≈ 7 % of the screen instead of 100 % | RF3 R2 |
| R2b | Content-only screen-change fade (8.7): no full-screen blend over the cover on a slide | r2.1 S01:116; RF3 R2b |
| R3 | DMA flush with **two partial buffers of 11,520 B**, both static `.bss` in internal RAM (today's single `draw_buf`, LT:23-24, plus one: +11,520 B, funded by F1, 12.4), a single `TFT_eSPI` instance, `dmaWait()` before any other panel access (`setRotation`) and before `cc_lcd_applied()` when it must mean "on glass". Compile flag `CC_LCD_DMA` (1 in binaries A and B, 0 in C, 12.6) | RF3 R3, §4.1 |
| R4 | LVGL refresh and animation period **16 ms**, only with or after R2 + R3 (never alone), and **not below the panel's measured scan period** (P5-R12). Compile flag `CC_LCD_PERIOD_MS` (16 in A; 33 in B and C) | RF3 R4; RF0 AR-15 |
| R5 | JPEG cover decode **off the render path**, in a dedicated decode task with a single-slot newest-wins request, decoder-owned back buffer, abort on supersede and a store decode pin: **protocol in 12.5**. The art rule of 8.4 applies while a decode is pending. It also shortens every `control` entry (the LCD ack no longer waits for a decode, 00 G2; 12.5.5). Compile flag `CC_ART_ASYNC` (1 in A; 0 in B and C) | RF3 R5 |
| — | Translate and opacity only; no layer scaling; covers swap instantly (no two-cover crossfade); slides ≤ 20 px; fades ≥ 120 ms; non-animated changes presented at once (`lv_refr_now`, LT:337-345) | R §3; S01 §3 |
| R6/R7 | `-O2` for LVGL blend code; HMI priority 2 — optional, only if measurements need them | RF3 R6, R7 |

`cc_display.cpp` stays platform-neutral (harness-compiled, `cc_display.h:5-9`); R3/R4/R5 live in `lcd_thread.cpp` and a copied driver under `src/` (never `.pio/libdeps`) (RF3 R3).

### 12.2 Targets

| Measure | Target (binary A; B and C in 12.6) |
|---|---|
| Animated transitions (slide, reveal, idle, fades) | **60 fps**; `lcdFpsAnimMin` ≥ 55 on opaque-cover transitions, ≥ 45 on blended frames (art show/hide) |
| Detent text swap | ≤ 5 ms to the panel |
| JPEG hitch on the render path | 0 ms with R5 (`lcdLateRefrs` 0 outside cover arrivals, 0 with R5) |
| `lcdFullRefrs` | only slides' first frames and art fades |
| LVGL heap | `lvglMinFree` ≥ 30 KB (twins on); harness peak ≤ 34 KB used |
| Internal heap | `heapMinFree` ≥ **40 KB (40,960 B)** measured on the device, and the **build-only projection** of 12.4 ≥ 45,056 B before the hardware window |
| Decode task stack | `stackArtDec` ≥ 1,024 B free (A only) |
| Enter → ready | `enterMsMax` ≤ 250 ms (reported; above it, investigate before release) |

240 fps on the knob is physically impossible (80 MHz single-line SPI: 11.5 ms per full frame, 87 fps ceiling; the panel likely ≤ 60 Hz) (RF3 §0). The floating knob's LCD mirror is change-driven on the desktop (K4).

### 12.3 Diagnostics (additive in `{"diag":"?"}`; the `diag` capability stays 1) (VOC-K1c)

| Field | Definition |
|---|---|
| `lcdFps` | refreshes that reached the panel in the last full second |
| `lcdFpsAnimMin` | lowest 1 s `lcdFps` while animations run; reset on read |
| `lcdRefrUsMax`, `lcdRefrUsAvg` | `LV_EVENT_REFR_START` → `REFR_READY` (+ the final `dmaWait`), over the refreshes of the last full second (windowed like `lcdFps`; 0 when none reached the panel) |
| `lcdRenderUsMax` | time inside `cc_display_render()` (A04 §2.8 "measure first") |
| `lcdFlushUs`, `lcdPxPerRefr`, `lcdFullRefrs` | flush share; Σ w·h per refresh; refreshes ≥ 57,600 px |
| `lcdLateRefrs`, `lcdMaxGapMs` | intervals > 1.5 × period while animating; worst gap |
| `lcdBusyPct`, `core0IdlePct`, `lcdSpiHz` | LCD share of core 0; idle-hook share; SPI clock at boot |
| `enterMsLast`, `enterMsMax` | `control` accepted → `ready` sent, ms (00 G2) |
| `holdEvents`, `holdDeferred` | `kh` lines sent; of which after a `ready` (11.2 step 5) |
| `lcdDma`, `lcdPeriodMs`, `artAsync` | the pipeline compiled into this binary (`CC_LCD_DMA`, `CC_LCD_PERIOD_MS`, `CC_ART_ASYNC`): identifies A / B / C (12.6) **[erratum E-lcd]** by pipeline only: D has A's and E has C's; `build` names the binary (12.6.1) |
| `artDecodeRequests`, `artDecodeAborts`, `artDecodeStale`, `stackArtDec` | R5 builds (12.5): requests posted; decodes aborted by a newer key; completions discarded as stale; decode-task stack free bytes (0 / absent when `artAsync` is false) |
| `lcdMosiSig` **[erratum E-lcd]** | the GPIO-matrix output signal routed to the LCD data pin `TFT_MOSI` (GPIO 4): `GPIO_FUNC4_OUT_SEL_CFG_REG` bits 8:0, read only, sampled at init and once per second. **103** (`FSPID_OUT_IDX`) = SPI2's data line drives the panel (D and E); **102** (`FSPIQ_OUT_IDX`) = binary A's dark-panel defect (12.6.1); any other value is a fault. A JSON integer |
| `build` **[erratum E-lcd]** | the ladder binary compiled into this image: `"A"`…`"E"` for `CC_BUILD_BINARY` 1…5 (a JSON string). **Absent** when the image has no ladder id (`CC_BUILD_BINARY` 0, the source default; A, B and C were built before it existed). The image also holds the marker `cc-build-binary:<n>`. Tells D from A and E from C, whose pipeline fields are equal |

Existing fields stay (`jpegDecodeMsMax/Last`, `lcdAgeMs`, `lvglFree`, `lvglMinFree`, `heapFree`, `heapMinFree` = `heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL)` (CCP:175), …; P4 §1).

**[1.0.0-cc5.5, F1]** `build` may also be `"F"` (`CC_BUILD_BINARY` 6: D's pipeline with `CC_LCD_PERIOD_MS` 12, so `lcdPeriodMs` 12). F1 appends the safety and measurement fields `usbMidiOk`, `usbHidOk`, `hidRetries`, `pdRead`, `pdPdo`, `pdVolts`, `pdRdo`, `focLoopHz`, `focLoopUsMax` (µs, reset on read), `uqAbsMax` (mV, reset on read), `uqCapMs` and `uqCapMv` (CONTROL_CENTER.md "Diagnostics" has the definitions). The `diag` capability stays 1; the host's `device.py` reads them as `DIAG_F1_FIELDS` and v7 ignores them.

### 12.4 Internal-RAM budget (gate `heapMinFree ≥ 40 KB`)

The 40 KB gate was set against today's 65.7 KB free (RF0 §4.3, refresh-00:402; RF3 §8.3). Measured and projected against cc5.4 it cannot be met without funding. A static (`.bss`/`.data`) increase lowers the internal heap, and so its low-water mark, byte for byte; transient allocations lower only the low-water mark.

| # | Item | Internal RAM | Kind | Source |
|---|---|---|---|---|
| 0 | cc5.3 measured `heapMinFree` | **57,072 B** | measured | RF3:71 (`DIAG/cc5.3-device-checks.json`); A04 §9.2 (04-firmware-gaps.md:616) |
| 1 | ALIVE engine (the cc5.4 ALIVE build of 2026-09-25): static RAM 259,328 B against cc5.3's 245,056 B. Of it, the ALIVE instance `alive` is 12,784 B (`nm` on that ELF), not A04's 8.1 KB estimate | **−14,272 B** | static, build-measured | ~~`work/nanod-cc5.4-build.log:1007`~~ **[erratum TB-D8]** line 1007 of the round-2 build log of 2026-09-25, kept only as the phase-2b gatekeeper's scratch copy `nanod-cc5.4-build.round2.log` (16.8 E-tb); `app/diagnostics/cc5.3-build.json:24`; A04 §9.2 (04-firmware-gaps.md:623-627) |
| 2 | v5 presentation state: CCFrame +≈ 26 B × ≈ 6 copies (3.6, incl. the two tuning fields of 7.3), `pendingHold`, the new diag counters, the R5 request/done records | ≈ −512 B | static | 3.6, 11.2, 12.3, 12.5 |
| 3 | ArduinoJson document for 1,400 B frames | ≈ −1,024 B | transient (enters the low-water mark) | 14.1 |
| 4 | R3: the second 11,520 B draw buffer (static), plus the SPI bus's DMA descriptors (≈ 0.5 KB heap at init) | ≈ −12,032 B | static + heap | RF3 R3 (refresh-03:188) |
| 5 | R5: decode task stack 4,096 B + static TCB ≈ 350 B | ≈ −4,446 B | static (12.5.1) | 12.5 |
| — | **Binary A unfunded** | **≈ 24.2 KB** (24,786 B) | | fails 40 KB |
| **F1** | **Funding of record (P5-R21):** declare the five WAV sample arrays `const`: `chime_wav` 52,804 B (`src/audio/WavData22m.cpp:116`), `soft_wav` 216, `hard_wav` 280, `loud_wav` 280, `clack_wav` 384 (`:6`, `:27`, `:54`, `:81`). They are non-`const` `uint8_t[]` today, so they link into internal `.data` (`chime_wav`: 0xCE44 B at 0x3FC936A4, DRAM, in the 2026-09-25 ELF); `const` moves them to flash `.rodata` | **+53,964 B** | static | `audio_api.h:31-45`; nm |
| — | **Binary A funded** (B ≈ 81.2 KB, C ≈ 93.0 KB, 12.6) | **≈ 76.9 KB** (78,750 B) | | passes with ≈ 37 KB margin |

- **F1 is behaviour-neutral.** The samples are only read by `i2s_write()` (legacy I2S driver, copied into its DMA buffers) from `audio_loop()` in the HMI task (`audio.cpp` `audio_loop`, `hmi_thread.cpp:399`), never from an ISR, and `USE_AUDIO_LIB` is off (`platformio.ini:53`). Task-context reads from flash-mapped `.rodata` are legal (during a flash write, the tasks that could read are suspended). Profiles store the sound **by name**, never by pointer (`HapticProfileManager.cpp:486-490`, `:681-682`, JSON persistence `:181`, `:319`). The change is `const` propagation only: the arrays and their `extern` declarations (`audio_api.h:38-42`), the `audioConfig` fields `audio_file` and `key_audio_file` (`audio_api.h:31`, `:33`), `get_audio_file`, `get_audio_filename`, `play_audio`, `start_play`, `check_file`, `AudioCommand::audio_file` and `data_ptr`. Flash grows by 53,964 B, inside the 261,424 B headroom (`nanod-cc5.4-build.log:1021`), together with section 9–10's ≈ +25 KB. ~~The boot chime (`hmi_thread.cpp:335`) and the click sounds are checked by ear in the hardware window (15.4).~~ **[erratum R-d]** Audio stays disabled exactly as in cc5.3: `platformio.ini` keeps `; -DAUDIO_EN=1` commented, so `audio_loop()` (the only reader of the command queue and the only `i2s_write()`, `hmi_thread.cpp` under `#ifdef AUDIO_EN`) never runs and the knob plays nothing, before or after F1. F1 changes no sound anyone can hear, and 15.4 has no by-ear check.
- **If F1 is refused** (the user may want native code untouched), no combination of the other levers reaches 40 KB on binary A: **F2** two 5,760 B draw buffers (1/20 screen each, net 0 against cc5.3's single 11,520 B buffer; 20 flush chunks per full frame instead of 10) gives ≈ 35.5 KB; **F3** moving non-hot CCFrame copies (the LCD snapshot in `render_host_frame`, LT:282, and similar ≈ 1 KB copies) to PSRAM adds ≈ 2 KB, giving ≈ 37.5 KB; **F4** trimming `LV_MEM_SIZE` is not available (`lvglMinFree` is projected at ≈ 32 KB against its 30 KB gate, A04 §9.2). The release then needs the user's decision: ship binary C (≈ 40.3 KB unfunded, 12.6: above the 40,960 B device gate but below the 45,056 B projection margin, so only the device reading can clear it), or lower the gate for A to 35 KB. The justification for the lower gate would be that the measured 57,072 B low-water already contains every dynamic consumer of the cc5.3 stress (TinyUSB, queues, FreeRTOS, ArduinoJson), so the margin guards only unmeasured paths.
- **Build-only check before the hardware window (every binary):** `cc5.4-build.json` records `ramUsedBytes`, `ramDeltaVsCc53 = ramUsedBytes − 245,056`, `sizeof(CCFrame)`, the size of the ALIVE instance (`nm`), and `heapMinFreeProjected = 57,072 − ramDeltaVsCc53 − 1,024 − H`. H is the run-time heap taken by new cc5.4 code outside `.bss`: only the SPI DMA descriptors (≈ 512 B, A and B), because the R3 buffers and the R5 task are static by rule. Gate: **`heapMinFreeProjected ≥ 45,056 B`** (40 KB plus 4 KB for estimate error). The device figure from `{"diag":"?"}` is the release gate (≥ 40,960 B).

### 12.5 R5: the cover decode task (`src/cc_art_decode.cpp/.h`; binary A only)

#### 12.5.1 Task
- `ArtDecode`, created with `xTaskCreateStaticPinnedToCore`. Its stack of **4,096 B** and its TCB are in `.bss`, so the build's `ramUsedBytes` counts them (12.4). It runs on **core 0** at **priority 1**: the priority of LCD, COM and HMI (LT:32, CM:18, HM:169; all on core 0, `main.cpp:21-23`). FreeRTOS round-robins equal priorities at the 1 ms tick, so a running decode delays an LVGL pass by at most one tick per wake and never by a whole decode. The task never runs on core 1 (FOC).
- `LcdThread::run()` creates it after the two PSRAM art buffers (LT:371-372), and only when **both** exist. With one buffer the shown buffer is written in place (`cc_display.cpp` `loadArt`), so R5 stays off at run time and `artAsync` reports false.
- While idle the task blocks on `ulTaskNotifyTake`. It is not subscribed to the task watchdog, because it blocks indefinitely while idle; `jpegDecodeMsMax` bounds a decode.
- It owns the TJpgDec work area `lcdWork` (4 KB, `cc_jpeg.cpp:28-29`). The LCD thread does not decode in R5 builds, so no new work area is needed.
- The platform-neutral renderer reaches it through two new `CCDisplayMedia` hooks: `requestCover(key, jpeg, bytes, dst)` and `pollCover(&key, &result)`. When they are null, `decodeCover` runs synchronously as in cc5.3. That is binaries B and C, and the harness's default.

#### 12.5.2 Shared state (one spinlock `artDecLock`; short sections, no allocation)
- `request {key[65], jpeg, bytes, seq}`: the one decode handed to the task. The LCD writes it **only while no decode is in flight**, then notifies the task.
- **Pending slot (single, newest wins):** the key waiting behind a running decode is the frame's **current `artKey`** itself, read afresh at every render. It is LCD-private and holds no JPEG pointer, so a pending key needs no pin, and a newer frame replaces it by construction.
- `inFlight` (bool): true from the post until the LCD consumes the matching `done`.
- `cancel` (bool): the LCD sets it when the running key is superseded, and the decoder's output callback reads it.
- `done {seq, key, result}`, with `result` one of `ok`, `failed` or `aborted`, and the counter `cc_art_decode_version()`. The task writes them at the end of each decode, and the LCD consumes them.

#### 12.5.3 Buffer ownership
- LVGL only reads `artBuffer[front]`. The decoder never touches it.
- `artBuffer[back]` (back = 1 − front) belongs to the **decoder** from the post of a request until the LCD consumes the matching `done`, whatever its result. While the decoder owns it, the LCD does not re-point the image at it, does not use the back-buffer reuse path (`artKeyOf[back]` is set to `""` at the post, `cc_display.cpp` `loadArt`), does not write it and does not post a second decode into it.
- The LCD swaps (`artFront = back`, `lv_image_set_src`) only when it consumes a `done` of `ok` for the frame's **current** `artKey`. Ownership then returns to the LCD.

#### 12.5.4 Flow
1. **Post.** `prepareArt` (LCD, inside the render) meets a key whose pixels are in neither display buffer and whose JPEG is in the store. If no decode is in flight, it pins the JPEG (12.5.6), clears `cancel`, writes `request`, sets `inFlight`, notifies the task and returns *pending*; the previous cover stays (8.4). If a decode for another key is in flight, the key simply waits as the frame's current key (step 4). No decode runs inside `cc_display_render()`, so every tween starts at its render. This restates the cc5.3 ordering guarantee ("decode before the tweens start", `cc_display.cpp:1016-1025`), which RF3 R5 names as the risk.
2. **Decode.** The task decodes `request` into `artBuffer[back]` with `cc_jpeg_decode_240(jpeg, bytes, dst, &cancel)`. The output callback returns 0 once `cancel` is set, so TJpgDec stops with `JDR_INTR` at the next MCU band (at most 16 of 240 rows, ≈ 3–10 ms).
   **[erratum R-f]** As built in `src/cc_jpeg.cpp/.h`: the 4-argument form returns **`CCJpegResult`** (`CC_JPEG_OK`, `CC_JPEG_FAILED`, `CC_JPEG_ABORTED`) instead of `bool`, so the task tells an abort from a failure (step 5's `aborted`, including a cancel the decoder saw just before a spin back cleared it, must never become `failed`, which hides the cover and marks the key failed). `*cancel` is read **between MCU rows**: before the first MCU of each row is written (15 polls per 4:2:0 cover, 30 for 4:4:4 / 4:2:2), so an aborted decode has written every row above the abort row and nothing from it on. Safe with the ROM R0.01b: returning 0 from the output function is its documented interrupt (`esp_rom_tjpgd.h`: "When a 0 is returned, the esp_rom_tjpgd_decomp function aborts with JDR_INTR"), and every decode starts with `esp_rom_tjpgd_prepare()`, which rebuilds the decoder object and its tables in the static work area, so the next decode is byte-identical to a clean one. An abort counts in `jpegDecodes`, never in `jpegDecodeErrors`, and leaves `jpegDecodeMsLast` / `Max` unchanged (a part decode is not a decode time). A general form `cc_jpeg_decode_240(jpeg, bytes, dst, abort, context)` (a callback polled with the row) lets host tests abort at a chosen band; the 3-argument `bool` form is unchanged. **Wired:** `cc_art_decode.cpp` decodes with `cc_jpeg_decode_240(stage, bytes, dst, &cancelled)` (`cancelled` is `volatile`, written under the spinlock, read by the output callback once per MCU row) and maps the three results with the pure `cc_art_decode_result(decoded, cancelledAtEnd)` (`cc_art_decode.h`): `CC_JPEG_ABORTED` → `aborted` always (even after a spin back cleared `cancel`), `CC_JPEG_FAILED` → `failed`, `CC_JPEG_OK` → `aborted` if `cancel` is set at the end, else `ok` (WP1-D2 resolved).
3. **Complete.** The task writes `done`, bumps the version and blocks again. It never starts a decode by itself; the LCD posts the next one after consuming `done` (12.5.3).
4. **Supersede.** When the frame's key differs from the running key, the LCD sets `cancel`. If the running key becomes the frame's key again before the abort lands (a spin back), the LCD clears `cancel`. A render whose key is the running key does nothing. On a fast Up next spin, only the key where the knob comes to rest decodes to the end.
5. **Consume.** `render_host_frame` renders when `cc_art_decode_version()` changed, next to its art and media version checks (LT:270, :330). `prepareArt` then consumes `done`:
   - `ok` with `done.key == frame.artKey`: record `artKeyOf[back]`, swap and show it. The swap is instant over a visible cover; a hidden or waiting cover shows over 240 ms (8.4).
   - `ok` but stale (`done.key ≠ frame.artKey`): **discarded**. `artKeyOf[back]` stays `""`, and `artDecodeStale` counts it.
   - `aborted`: discarded, counted in `artDecodeAborts`.
   - `failed` for the current key: the 8.4 failed-decode rule (`artFailedKey`, hide).
   After any result, the LCD releases the decode pin and clears `inFlight`. If the frame's current key still has no pixels in either display buffer and has not failed, it posts that key at once (step 1): this is the newest-wins pending request, and it also covers a cancel that the decoder saw just before a spin back cleared it.
6. **Cancel.** `cc_display_release_media()` (release, the offline screen) and any frame whose layout shows no art (Windows, idle, notice, `artKey:""`) set `cancel`; with no art wanted, step 5 posts nothing. The pin is released when that abort's `done` is consumed.

#### 12.5.5 Entering and the cover decode (answers CC5 §6.1, §6.3 and OQ-4)
- **R5 off** (binaries B and C, a one-buffer device, and cc5.3): **entering waits for the decode.** The control's first render runs `cc_display_render()` (LT:332), which decodes a new cover synchronously before `cc_lcd_applied(id)` (LT:346), and the motor arms only once `lcdId` matches (`cc_can_arm`, CCP:319-321). C5-13 (the `control` keeps the previous `artKey` and the new key follows `ready`) therefore shortens the blind window by the decode (46–154 ms). Its cost in these builds: the decode moves into the first render after `ready`, usually inside the 380 ms slide. LVGL animations are time-based, so the slide skips frames for that long but still ends on time.
- **R5 on** (binary A): **entering does not wait**, because the render only posts the request and acks at once. C5-13 is not needed there. It stays valid and harmless, and costs ≈ `enterMsLast` of cover latency, because the decode starts after `ready` instead of at the `control`.
- In every build, a `control` frame that keeps the previous frame's `artKey` is valid (8.4). **Recommendation to K3:** keep C5-13 unconditional. The host can tell A from B/C only through `diag`, and one rule is simpler to test.

#### 12.5.6 Store decode pin (ARTWORK2 §4.4, extended in `cc_media_store.h` / `cc_media.cpp`)
- The pinned slots become the displayed slot, the valid slot whose key equals `frameKey`, **and the decoding slot**: the cover slot whose JPEG the task reads. `pinDecode(key)` sets it when the request is posted (LCD thread, under the store mutex), and `unpinDecode()` clears it when the LCD consumes that decode's `done`, whatever the result. Pinned slots are never victims and are never written (cc_media_store.h:26-27), so an upload during a spin can never overwrite bytes the decoder is reading.
- With the device's 26 cover slots (`CC_MEDIA_COVER_ENTRIES + 1`), three pins leave at least 23 victims. A store of 3 slots or fewer (fixtures only) can have every slot pinned; a miss then answers `Media unavailable`, as today (cc_media_store.h:33).
- Icons are never decoded, so their store is unchanged.

#### 12.5.7 Host tests (before the window)
- Harness check `art_async` (15.3), with a scripted fake decoder that takes a per-request delay and can abort at a chosen band:
  - (a) keys A → B → C inside one decode: only C is ever shown, and A and B never appear after C was requested;
  - (b) the previous cover stays until completion;
  - (c) the front buffer's bytes never change while a decode runs;
  - (d) stale and aborted results are discarded;
  - (e) a failed decode hides the cover;
  - (f) a release, and a no-art layout, during a decode;
  - (g) a spin back to the running key;
  - (h) a 20-key spin at 12 detents/s ends with the resting key's cover within one decode time of the last detent.
- Store fixture (`media_tests.py`): an upload never evicts or writes the decoding slot, and the pin clears on every result.
- `jpeg_tests.py`: an abort at every MCU band returns `JDR_INTR` and leaves the decoder reusable, and the next decode is byte-identical to a clean one. **[erratum R-f]** Measured on the host through `tjpgd_shim` (LVGL's R0.03, the same interrupt contract) over the 24 decodable `jpeg_tests.py` samples (the nine design covers at 4:2:0 and 4:4:4, the 4:2:2, restart, comment, EXIF and gray variants): 525 band aborts, each `CC_JPEG_ABORTED` with the rows above it equal to a clean decode and nothing below written, each followed by a byte-identical clean decode; a never-cancelled hook is polled exactly once per MCU row, top to bottom, before the row is written; a damaged scan is `CC_JPEG_FAILED`. The case is in `jpeg_tests.py` / `jpeg_tests.cpp` (`band_abort_checks`, every run of the gate).
- **[erratum R-f]** `art_async` models the shipped decoder: the fake stops at the next of 15 MCU bands once `cancel` is set and completes through `cc_art_decode_result()` (the harness also checks that mapping over its six inputs), plus a (g) variant where the spin back lands in the pass that consumes the abort (discarded, never `failed`, the key posted again). (h) is checked as **one decode time plus the abort latency of step 2** — at most one MCU band, ⌈decode / 15⌉ ms — plus one LCD pass.

### 12.6 Build ladder for the one hardware window (P5-R23)

RF3 §8.2 planned one-variable-at-a-time flashes; the user allows one hardware window, so three binaries are staged for it.

| Binary | R2 | R3 (DMA) | R4 (period) | R5 | RAM projection with F1 (12.4) | Timing targets |
|---|---|---|---|---|---|---|
| **A** (release candidate) | yes | yes, 2 × 11,520 B | 16 ms, or the measured scan period (P5-R12) | on | ≈ 76.9 KB | 12.2 |
| **B** (middle) | yes | yes | 33 ms | off | ≈ 81.2 KB | `lcdFpsAnimMin` ≥ 28; `lcdLateRefrs` 0 outside cover arrivals; the rest of 12.2 |
| **C** (fallback) | yes | **no**: the single blocking 11,520 B `draw_buf`, exactly as in cc5.3 (LT:23-24, :384) | 33 ms (`LV_DEF_REFR_PERIOD`, `lv_conf.h:64`) | off | ≈ 93.0 KB (≈ 40.3 KB without F1) | as B |

- All three are the same release (`1.0.0-cc5.4`, ALIVE, presentation 5, twins). They differ only in `CC_LCD_DMA`, `CC_LCD_PERIOD_MS` and `CC_ART_ASYNC`, which `diag` reports (12.3). Each is built, harness-gated (15.3) and RAM-projected (12.4) before the window. **Each flash needs the user's go-ahead.**
- R2 is in all three: the harness proves it pixel-identical (`v5_bounded`), and it changes no driver code.
- Stepping down removes one risk class at a time. A → B removes the scheduling changes (the 16 ms period and the decode task). B → C removes the DMA driver: TFT_eSPI DMA on the ESP32-S3 needs a bring-up test, and its byte-order and `dmaWait` ordering (around `setRotation` and `cc_lcd_applied`) are new (RF3 R3; 80 MHz SPI through the GPIO matrix with no documented margin, refresh-03:52, :104).
- **Order of checks per binary** (stop at the first failure):
  1. **Panel image.** A static Home cover matches the harness render of the same frame (colours, byte order, no offset). There are no torn or stale bands during a slide, a volume reveal or a cover swap, and an orientation change (`setRotation`) redraws cleanly.
  2. **Entry and input.** `ready` arrives (`enterMsMax` ≤ 250), a turn and a press reach the host, a hold produces one `kh`, and there are no `error` replies.
  3. **Timing.** `lcdFpsAnimMin`, `lcdLateRefrs` and `lcdMaxGapMs` meet the binary's targets. On A only, film the panel scan (RF3 §8.2 step 3).
  4. **Memory.** `heapMinFree` ≥ 40,960 B, `lvglMinFree` ≥ 30 KB, `stackArtDec` ≥ 1,024 B (A only), and the other stacks as today.
- **Decisions.**
  - A passes 1–4: ship A.
  - A fails check 1: go straight to **C**, because B carries the same DMA driver.
  - A fails only checks 2–4: go to B.
  - B fails any check: go to C.
  - C fails: roll back to the cc5.3 backup. That also drops ALIVE and presentation 5, and the v7 host then sends the presentation-4 downgrade (2.2).
- **[erratum E-lcd]** A, B and C are retired: A failed check 1 on the knob (a dark panel) and was rolled back, B carries the same defect, and C is superseded by E. The ladder is now **D** (A's pipeline plus the fixes) and **E** (C's pipeline plus the fixes): 12.6.1.

#### 12.6.1 [errata] E-lcd: binary A on the knob; binaries D and E (2026-09-26)

**What happened.** Binary A was flashed in the hardware window of 2026-09-26 and rolled back to cc5.3 the same day (`cc5.4-rollback.json`: `ROLLED_BACK_VERIFIED_RESET` at 21:12 UTC, the full image equal to the locked backup). The user saw two defects: the LCD was dark in every mode after boot, and the ring and button LEDs flickered. The flicker is K2's: the ALIVE output stage's temporal dither was on by default at 0–3 count levels. The user's ruling of 2026-09-26 turns it off by default and adds a brightness floor (ALIVE.md §9, §12.7). The LCD defect is recorded here.

**Root cause of the dark panel.** It is confirmed in the source and in the disassembly of the flashed ELF (sha256 `a3bf3763…`, equal to the installed image). It has not been seen on glass yet.
- `platformio.ini` sets `TFT_MOSI=4`, `TFT_MISO=-1`, because the panel has no MISO wire.
- On the ESP32-S3, `TFT_eSPI_ESP32_S3.h:340-342` redefines `TFT_MISO` as `TFT_MOSI`.
- R3's `tft.initDMA()` (`lcd_thread.cpp`) therefore calls `spi_bus_initialize(SPI2_HOST)` with mosi = miso = 4.
- IDF 4.4's `spicommon_bus_initialize_io` routes GPIO 4's output to FSPID (103) and then, in its MISO step, to FSPIQ (102), which the controller does not drive in one-bit mode.
- From that line on, no command and no pixel reached the GC9A01, in native or host mode. Every `lcd*` diag counter measures the ESP32 side, so they all looked healthy.
- The "native screen" seen after the flash was the panel's retained cc5.3 frame. `tft.begin()` sends sleep-out and display-on before `initDMA`, and the GC9A01's frame memory survives a reset.
- B calls `initDMA` too. C and cc5.3 never call it: Arduino's `SPI.begin()` attaches MOSI last, as FSPID.

**Fix, in every DMA build.** `cc_lcd_mosi_reattach()` runs right after `tft.initDMA()` and before `tft.startWrite()`.
- It calls `esp_rom_gpio_connect_out_signal(TFT_MOSI, spi_periph_signal[SPI2_HOST].spid_out, false, false)`, the signal IDF itself used for MOSI. It is a no-op when MISO is a separate pin.
- It has C linkage and is never inlined, so the build gate can find it by name.
- `USE_HSPI_PORT` is refused at compile time: the encoder owns HSPI (`foc_thread.cpp`).
- Nothing else on the render path changed. One `startWrite()` still holds CS for the whole uptime. Ending and restarting the transaction once per refresh is deferred to the performance task, so a D failure can be attributed.
- One hardening change, diag sampling only: `perfWindow` now reads the decode task's stack high-water mark and the render counters before its `perfLock` critical section. The stack scan masked the LED RMT interrupt for about 64–128 µs once a second.

**New diag fields (12.3).**
- `lcdMosiSig`: 103 is good, 102 is A's defect.
- `build`: the ladder letter from `CC_BUILD_BINARY`.

The desktop's diag parser ignores both until it is taught them, so Desk Dial v7 is unaffected.

**Build gate (host, `nanod_cc5_tooling`).**
- It works out the effective TFT pins from `platformio.ini` plus the binary's flags, with the S3 rule (MISO −1 becomes MOSI) and `USE_HSPI_PORT` refused.
- A DMA binary whose effective MISO equals MOSI must link `cc_lcd_mosi_reattach` (build record `lcdMosiGate`). A's ELF fails this gate.
- A numbered binary's image must hold `cc-build-binary:<n>`.

**The ladder now.** Same release `1.0.0-cc5.4` (ALIVE, presentation 5, twins). D and E carry both fixes: this one and K2's dither default and floor.

| Binary | Flags | Pipeline (`lcdDma` / `lcdPeriodMs` / `artAsync`) | diag `build`, `lcdMosiSig` | Timing targets |
|---|---|---|---|---|
| **D** (release candidate) | source defaults + `-DCC_BUILD_BINARY=4` | true / 16 / true (A's; R3 + R4 + R5) | `"D"`, 103 | 12.2, as A. `lcdTimings` is expected to fail until the performance task: `lcdFpsAnimMin` measured 12–16 on A's pipeline |
| **E** (fallback) | C's `-DCC_LCD_DMA=0 -DCC_LCD_PERIOD_MS=33 -DCC_ART_ASYNC=0` + `-DCC_BUILD_BINARY=5` | false / 33 / false (C's) | `"E"`, 103 (Arduino attaches FSPID, as in cc5.3) | as C |

Retired binaries:
- **A**: rolled back 2026-09-26 (dark LCD).
- **B**: the same DMA defect; never flashed.
- **C**: superseded by E; never flashed.

**Hardware check of D (and of E on a step-down): the look session.**
- **Before anyone looks,** two read-only diag reads (`check_nanod_cc5_look.py`) must show all of the following. Otherwise it is NO-GO and nobody is asked to look.
  - `build` is the binary's letter, with its pipeline.
  - `lcdMosiSig` is 103.
  - No core dump and no crash reset reason.
  - No reboot between the two reads.
- **Then by eye:**
  - The native dial is drawn and follows a few detents. A static picture proves nothing: the panel keeps cc5.3's frame across a reset.
  - The host screen appears on a claim.
  - The resting and offline LEDs are steady, with every mark visible.
- The full 8b/8c checks and finalize wait for the performance task.

**Decisions.**
- D's screen fails (`lcdMosiSig` ≠ 103, or dark or garbled despite 103, which would be a second DMA problem): roll back D and install E.
- E fails: roll back to cc5.3.
- The screen is fine and only the LEDs misbehave: E does not help (it has the same LED code). The user decides between keeping D and rolling back.

---

## 13. Errors (presentation is never fatal)

Unchanged from P4 §7 and AW2 §4.3, plus:
- The host **never** sends a v5 token or field to a presentation-4 knob (2.2 is mandatory); if it did, the V4 parser would reject the frame and the host would treat the reply as fatal (P4 §7).
- Invalid v5 values: firmware rejects the frame (3.3); the host strips and logs (`_strip`, DV:142-151) and never sends them.
- Knob events with an unknown id, a `kh` outside 0..3 or a `ks` outside 0..15 are ignored by the host (never an `error`).

---

## 14. Size budget and slimming (presentation ≥ 5)

### 14.1 Budget

- **`FRAME_BUDGET_BYTES_V5 = 1,400 B`** for the JSON-escaped `{"frame":…}` line (newline included), with room reserved for the latched fields the bridge adds at send time: ALIVE's worst values (`clock` 1439, `progress` 86,400,000/86,400,000, `ledDrive` 255, `ledDither` false) **plus `"reducedMotion":false`** (≈ 110 B) (P5-R8) **plus the tuning fields `,"ledPink":16777215` and `,"ledVolFull":false`** (19 + 19 = **38 B**; 7.3), ≈ 148 B of latched reserve in all.
- **Why raise it:** the worst realistic v5 frames measure (this contract's computation, all legacy text empty, with the full latched reserve): **Windows 1,352 B** (20 colours, 96 B title, 96 B app name, a 90 B snap meta, 24-char `iconKey`, two lit colour buttons, `snap` feedback, pending, latched reserve; 1,314 B before the 38 B of tuning fields), explorer 1,261 B, Up next 1,238 B (with `now`, `card`, `like`), Home 1,140 B, Seek 806 B. Under V4's 1,100 B the Windows worst case would shorten a real window title. The firmware line capacity is 4,096 B (CM:40-45), so the parser is unaffected; the ArduinoJson document grows by ≈ 1 KB of transient heap.
- Presentation-4 knobs keep V4's 1,100 B budget and rules (P4 §8; AW2 §6).
- **Over budget** (escape-heavy text, e.g. a Windows frame whose title and app name are quotes: 1,506 B): V4's order — empty `detail`, `value` (never on Home layouts), `target`; then remove whole code points from the end of the longest of `volumeCaption`, `subtitle`, `title` and log `"<field> shortened"` (P4 §8; DV:473-523).

### 14.2 Slimming (host, `_slim`)

Omit:
- V4's defaults: tones at default, `artDim:false`, `page:0`, empty `heading`/`meta`/`artKey`/`iconKey`, `ring.unavailable:0`, `ring.moreIndex:-1`, `ring.external:false`, `counter`; `volumeCaption`/`confirmedVolume`/`restLayout`/`volumeVisible` outside Home (P4 §8).
- **`ring.first:0` only when `count ≤ 20`** (4.2; P5-R9).
- `ring.now` when −1 or outside `upnext`/`selection`; `ring.card` when false; `ring.unavailable` on layout `upnext` (always 0 from a v7 host; stripped by both parsers anyway, 4.4); `ring.colors` unless `ledStyle:"color"` and `selection` (P4 §8).
- button `lit` when the tone is derived (never send "absent"); button `color` unless `lit:"on"`, `color ≠ 0` and `icon ≠ heart` (**V4 stripped every button colour**; v5 keeps this one case).
- `feedback.side` unless `snap`; `feedback.color` unless `snap`/`started` and ≠ 0.
- `reducedMotion` except in `control` frames and the first frame after a change (7.1).
- `ledPink` / `ledVolFull` except in `control` frames when settings.json sets them (7.3).

---

## 15. Fixtures, parity and gates

### 15.1 `tests/fixtures/frames_v5.json` (WP3)

Same format as `frames_v4.json` / `frames_alive.json`: `{contract, about, rules, cases[]}`; each case `{name, note, capabilities, input, expect{accept, output}, rawParity, v5{accept, stored}}`.
- `capabilities`: `{presentation: 4|5, glyphs, artwork2?, alive?}`.
- `expect` describes the **host** (`device._frame(input, capabilities)`); `v5` describes a **cc5.4 parser** fed `input` directly. `stored` = `{layout, page, ringStyle, ringIndex, ringCount, ringFirst, ringNow, ringCard, ringUnavailable, lit[4], color[4], icon[4], feedbackKind, feedbackMoment, feedbackSide, feedbackColor, feedbackSkip, reducedMotion|null, ledPink|null, ledVolFull|null}` (`null` = absent from the frame).
- **Rules:** `host` (exact output, key order irrelevant); `firmwareOutput` (every accepted `expect.output` is accepted by cc5.4 with identical text and v5 values); `firmwareRaw` (when `rawParity`, raw input matches); `v5Raw` (every case: accept exactly when `v5.accept`, then store `v5.stored`; `device.v5_parse(input)` returns the same `(stored, invalid)` or names the invalid field, like `alive_parse`, DV:230-266); `downgrade` (every `presentation:4` case's output is a valid V4 frame that a V4 parser accepts, per 2.2); `windowRule` (v5 `first` = `clamp(index − 10, …)` always sent when `count > 20`; absent `first` still derived as `index − 9`); `card` (incl. the `unavailable` strip on `upnext` and the int32 `now`); `moment`; `lap`; `budget` (≤ 1,400 B with the latched reserve).
- **Required case families** (minimum): each new layout token (p5 accepted; p4 mapped); `lap` valid (count 1, 59,999) and invalid (0, 60,000, `index == count`, `value` missing); `now` valid, out of range (−2, `count`), bool, stripped on recent/explorer/transport/level, and a **large value** (`count` 40,002, `index` 40,001, `now` 40,000, `card:true`, `first` 39,982) that must store as 40,000 on both sides (int32, 3.6); `card` valid, `now ≠ count − 2`, `count < 2`, non-bool, stripped outside upnext; `unavailable` on `upnext`: a valid mask stripped (stored 0) with and without `card`, a mask with bits beyond the window rejected; `lit` on/off/invalid, with `icon ""`, with `enabled:false`; button `color` kept only with `lit:"on"` (host), heart + on (no colour sent); every new icon token, legacy `home/more/cancel`, an unknown token; each `moment` with `ok`, with `err` (stripped), invalid token, `skip` + `moment` (reject/strip), `snap` without `side` (reject/strip), `side` without `snap` (stripped), `color` on `started`/`snap`/`like` (kept/kept/stripped), `color` out of range; `reducedMotion` true/false/invalid; **`ledPink`** valid 0, 1, 0xFFFFFF and invalid −1, 0x1000000, `true`, `"#FF051A"`, 1.5; **`ledVolFull`** valid `true` / `false` and invalid `1`, `"true"`; both stripped by the host for a knob without `alive` and absent from every presentation-4 output (7.3); explorer `page` 0/1; every §2.2 downgrade row; the §14.1 worst cases (with the 38 B tuning reserve) and the escape-heavy shrink; gating (p5 without `alive` → no ALIVE field; p4 → no v5 field). K2's optional case of a `card:true` frame whose card entry has its `unavailable` bit set (ALIVE_R2_DRAFT §13.1 X9) is covered by the `unavailable`-on-`upnext` family above: the mask is stripped (stored 0) and the card is still identified by `card` (P5-R24).
- **[r2.2]** No new case family is needed: the wire did not change. The existing `heart` + `lit:"on"` case now also asserts the derived tone `liked` in the LCD harness (15.3 `footer_static`, `icons`); the `moment` family keeps `unlike` as a valid **reserved** token (accepted, stored 4) with a note that no host output ever contains it (K3's `test_cc5_upnext.py` asserts the controller never emits it).
- `frames_v4.json` and `frames_alive.json` stay unchanged and must pass against the **v7 host** (for their presentation-4 capabilities) and the **cc5.4 parser**.

### 15.2 Parity (gate A3)

- `harness/parse_tests.py` (+ `parse_tests.cpp`, MSVC `/W4 /WX`) runs the cc5.4 parser over `frames_v4.json`, `frames_alive.json` and `frames_v5.json`; `tests/test_cc_contract_v5.py` checks every `expect.output` against an independent reading of this contract (window rule, slimming, budget, downgrade); `tests/test_cc_device.py` covers `_frame`, `v5_parse`, `kh` → `hold`, `hid`, `ks` in `ready`.
- Firmware and Python share one change set for the ALIVE §3 and v5 fields (00 §3.2 "Capability"; A04 §5).

### 15.3 LCD harness gates (gate A4; `harness`, `cc5_report.py` extended; WP1)

Harness fixture `tests/fixtures/cc54_frames.json`, generated by `tests/tools/make_cc54_frames.py` from a scripted tour of BS states (every mode × every state-picker option of BS:1352-1365 that reaches the knob), with `deviations` tagging P5 ids. Checks (existing ones keep running on `cc5_frames.json`, now with the v5 geometry):

| Check | Requirement |
|---|---|
| `parse` | every v5 case parses |
| `safe_circle` | text and icon ink inside r 104; **heading ink inside r 112** |
| `heading_fit` | the six v5 headings verbatim at 1 px tracking; legacy page headings follow the chain |
| `verbatim_text`, `ellipsis_honest`, `label_bounds` | as today, over every v5 box |
| `css_baselines` | every box of 8.5.1 on its CSS baseline ± 1 px |
| `footer_static` | footer centres 56/99/141/184, rows 154–173; **identical pixels in every frame of a slide timeline**; ink crossfade 160 ms; **[r2.2]** Up next Button 3 with `heart` + `lit:"on"` draws the filled `heartfill` in `#A3244A` (tone `liked`), never the stroked heart and never `#5A5A5A` |
| `idle_row` | centres 51/97/143/189, top 100; words centred; **every v7 Home label (`Play`, `Pause`, `Browse`, `Tracks`, `Win`) ≤ 46 px** (VOC-D08, P5-12); a v6 `Play/Pause` label is reported, not failed (2.3) |
| `seek_digits` | `cc_font_48t` used; **0 px jitter**: digit cell x positions identical across `0:00`…`9:59` and across `10:00`…`59:59`; `:` drawn; baseline 116 |
| `windows_geometry` | title top 98 / meta top 140 boxes; title line 2 ink above meta ink |
| `art_rules` | art only on the 8.4 layouts; `artDim` 112; instant swap on key change; 240 ms show/hide; art never translates; decode-pending rule (R5 builds) |
| `slides` | the 8.7 flip table, one timeline per transition; none on Seek on/off, re-centre, heartbeat |
| `motion` | key times of 8.8 (content 220/380, reveal, idle stagger, meta fade 160) at 16 ms sampling |
| `reduced_motion` | with `reducedMotion:true` no translate in any timeline; content fade 220 ms |
| `twins` | exactly the 12 twins: black, opa 204, +1 px, same text; none elsewhere |
| `twin_fade` | on every frame of the `content`, `track` and `volume` fade timelines: compared with a group-composited reference (the layer rendered at opacity 255 off-screen, then blended at the layer's opacity over what lies below), pixels differ **only inside label ink boxes** and by ~~≤ 16 levels per 8-bit channel (P5-13's bound of 15, plus 1 for rounding)~~ **[erratum R-b] ≤ 28 levels per 8-bit channel** (the measured bound: 26 with LVGL's RGB565 per-primitive blending, 8.5.3)~~, whatever lies under the ink~~ **[erratum R-g]** over the cover (every in-box pixel outside the overlap class below); identical at opacity 0 and 255. ~~**Open (WP1-D1):** 35 measured where the labels of two fading layers overlap (the volume reveals, 8.5.3), so the check fails there until the lead rules~~ **[erratum R-g]** Where a label ink box of the probed layer overlaps the label ink box of another layer fading in the same capture (the volume reveals' caption over the home title, 8.5.3; 35 measured): **≤ 36 levels per 8-bit channel**; the ≤ 28 bound holds for every other pixel inside the boxes (`TWIN_FADE_OVERLAP_LIMIT`, 16.8 E-g) |
| `art_async` | R5 protocol (12.5.7 cases a–h) with the scripted fake decoder; the synchronous default path still passes `art_rules` |
| `offline` | layout, copy swap after native input, entry/exit timelines, no native-screen frame in between |
| `copy` | every VOC §9 knob string **and every CC5 §15.2–15.3 knob string (`knob.*` ids)** rendered in its element: fits its App C limit (two-line titles per line after the balanced split: 164 / 170 px), or is on the 8.6.11 exception list |
| `icons` | every token/size of 9.1 exists; snap masks carry the filled half; **[r2.2]** `heartfill` (20 px) exists and is the filled heart path; `--check` byte-identity |
| `v5_bounded` | bounded layers produce the same pixels as full-size layers on every timeline frame |
| `heartbeat`, `latency`, `heap` | as today; heap peak ≤ 34 KB used |
| `mirror_parity` | `lcd_preview.py` draws the same strings, baselines, pens, inks, icons and art decisions as the harness dump for every case (`FirmwareParityTests`), incl. twins and tabular digits |

### 15.4 Device gates (hardware window; 00 §4.5 H2/H3/H5)

Run in the order of the build ladder (12.6): binary A first, the four checks per binary in their order, stepping down only on a failure. Then: capabilities `presentation:5` and `alive`; section 12.2 targets from `{"diag":"?"}` (B and C: their 12.6 targets); `heapMinFree` ≥ 40,960 B against the 12.4 projection; `kh` events (incl. one deferred), `ks` in `ready`, `hid` on the Home F24 press, no F24 on Button 4 outside Home; Seek digits without jitter and the End stop at 0:00 and `T_end`; twins legible on light covers, and no visible darkening of text during a slide (P5-13) **[erratum R-b]** or a volume reveal (the ≤ 28 `twin_fade` bound, 8.5.3, confirmed by eye; ~~the volume reveals also show the open WP1-D1 overlap, 35 measured, for the lead's ruling~~ **[erratum R-g]** and, in both volume reveals, the caption crossing the fading home title within its ≤ 36 bound (35 measured), with no visible darkening of the caption while the two labels cross-fade); headings fit on glass; **[erratum R-c]** the offline native line `Knob controls still work` on one line at −1 px tracking reads cleanly (8.10; else the 8.10 fallback copy); the Windows art fade; Up next spin without decode stalls (A: R5) and never showing a superseded cover; ~~the boot chime and the click sounds as in cc5.3 (F1, 12.4);~~ **[erratum R-d]** no by-ear check: audio stays disabled exactly as in cc5.3 (12.4 F1); `ledPink` and `ledVolFull` accepted and latched by the LED tour (7.3; K2 §11.9); no `error` replies under stress.

---

## 16. Deviations and rulings

### 16.1 Deviations from r2.1 (P5-n)

| Id | r2.1 says | K1 does | Reason |
|---|---|---|---|
| **P5-1** | Headings 0.04 em tracking (S01:125; CH §4) | 1 px letter space | LVGL letter space is an integer; 0.48 px rounds to 0 or 1 (0.48 vs 0.52 away); 1 px keeps the cc5.3 look and every heading still fits 138 px (8.5.2) |
| **P5-2** | `of m:ss` tabular (BS:315) | proportional 14 px | the line is constant during a Seek session, so it cannot jitter (A04 §4.3); saves a second tabular face |
| **P5-3** | Offline sub ~~`Open Nano_D++ on your PC`~~ **[rename]** `Open Desk Dial on your PC` in a 170 px line (BS:319, greedy CSS wrap; the design's wrap of the new copy would give `Open Desk Dial on your` / `PC`, 168.3 px) | two **balanced** lines (~~`Open Nano_D++`~~ **[rename]** `Open Desk Dial` / `on your PC`) | ~~197.9 px~~ **[rename]** 192.2 px (LVGL 198) does not fit 170 px; balanced matches every other two-line knob label |
| **P5-4** | Text shadow on the whole content layer (BS:282) | twins on 12 labels above y ≈ 125 only | ≤ 15 % of the cover shows below y 126; each twin costs ≈ 250–300 B of the 64 KB LVGL heap (A04 §2.8) |
| **P5-5** | Assigned snap side drawn in the raw app colour (BS:1282, :1289) | `accent_ink()`: `sat()` + a lift to ≥ 3:1 | VOC-D02's legibility reason; `sat()` alone leaves blue at 2.4:1 |
| **P5-6** | A monochrome app on an assigned side draws its warm colour (BS ChatGPT `c = WARM`) | host sends `color` 0 (VOC §3.5) → `on` ink `#FFFFFF` | monochrome accents are warm (0) on the wire; the LED is the same WARM 1.0 |
| **P5-7** | Windows letter tile: app colour, **bold** white initial (BS:322) | `sat(app colour)`, Medium 500 initial; `#444` when no accent | no bold face on the knob (A04 §2.5); 00 §3.2 |
| **P5-8** | "add tabular digits … for Seek's m:ss and the volume value" (S01:129) | volume digits stay proportional; tabular only in `cc_font_48t` for Seek | BS:290 draws the volume without `tabular-nums`; changing it would alter the shipped look (A04 §4.2) |
| **P5-9** | Hold detected "if still held at 600 ms" (S01:41; BS host timer BS:891) | firmware `kh` ≈ 620–640 ms after contact, deferred to just after `ready` when it fires during an entry | VOC-D06 (host timing gives false Homes, A04 §6.1); the deferral closes the entering gap |
| **P5-10** | Up next ring windows over the real rows; the card has no slot (BS:1319) | the card is the last ring entry (`card:true`) | the knob position and `{i} / {n}` include the card, and the window rule needs `index < count`; at most a one-entry window shift near the end of > 20 rows (LED; K2 draws) |
| **P5-11** | "PC not connected" shows whenever the PC is away (BS:1414; S01 §9) | only after a lost host (lease expiry); boot and intentional release keep the native screen | an intentional release also happens for device configuration; the knob must stay a plain native knob without the companion (CC:568-572); OQ-3 |
| **P5-12** (= VOC-D08; active) | Idle-row word for Home Button 1 is `Play/Pause` (S03:15 override #16; S03:134) | the Home slot-0 label follows its icon: `Play` / `Pause`; the idle row therefore reads `Play`, green when paused and dim `#5A5A5A` when nothing is playing (8.6.3) | `Play/Pause` is 67.4 px against the 46 px column (8.6.3, 8.6.11). VOC-D08 records the deviation (VOC §13.1), K3 sends the label (CC5 §3.1, C5-60) and the harness gates it (`idle_row`, 15.3). It is in the copy approval pass (VOC §9.5), **[r2.2] approved** (R22 CH §2: "Idle row slot 1: `Play` / `Pause` · Approved"). A v6 host's `Play/Pause` is still ellipsized on cc5.4 (2.3) |
| **P5-13** | Text shadow fades with its text as one group (BS:282; CSS opacity on the layer) | twins and labels fade separately; mid-fade glyph interiors show `(1 − a)(1 − 0.8a)` instead of `(1 − a)` of the cover, at most 15 of 255 levels (a = 0.5) by the float model, **[erratum R-b]** ≤ 28 measured with LVGL's RGB565 blending (35 measured where two fading layers' labels overlap, in the volume reveals: ~~open deviation WP1-D1, 16.7 E-b~~ **[erratum R-g]** bounded at ≤ 36, 16.8 E-g), on the `content`, `track` and `volume` fades only; shadow edges exact (8.5.3) | a group fade needs `opa_layered` (a composited layer from the 64 KB LVGL heap, RF3 §4 "Not recommended"; 8.1 rule 1); hiding the twins during fades would lose the exact shadow edges; bounded by `twin_fade` (15.3) |
| **P5-14** **[erratum R-c]** | Offline native sub-line `Knob controls still work` at the page's letter spacing (0; BS:319, S01:140), 167.5 px in 170 | one line at **−1 px tracking** (148 px) | 171 px with the knob font (whole-pixel kerned advances) would wrap to two lines; the approved words stay (8.10); by eye in the hardware window (15.4) |

### 16.2 Rulings (where r2.1 is silent or K1 had to choose; P5-Rn)

| Id | Ruling | Basis |
|---|---|---|
| P5-R1 | The Seek time comes from `ring.index`/`count`; the firmware formats `m:ss` | A04 §2.2 recommendation; one source for LCD and lap |
| P5-R2 | Seek line ink `#A6A6A6` when `metaTone` is `meta` | BS:315 (`#A6A6A6`, error `#FF8474`) |
| P5-R3 | Every cover show/hide is 240 ms OUT, including idle return and late arrival | S01 App A S01:523 over S03's 420/700 ms and P4's 60 + 420 ms |
| P5-R4 | A decode in progress keeps the previous cover until it completes; missing pixels hide at once | r2.1 "covers swap instantly"; RF3 R5 |
| P5-R5 | The 160 ms text fade applies to meta and status lines only, and not in a render that changes screen | BS:791-797 |
| P5-R6 | Ink crossfade 160 ms OUT on footer icons, idle icons and idle words | S01 App A S01:524 |
| P5-R7 | Reduced motion keeps the idle-row stagger, opacity only | S01 §10 silent on it |
| P5-R8 | Budget 1,400 B for presentation ≥ 5 | 14.1 measurements |
| P5-R9 | `ring.first` is never slimmed when `count > 20` | 4.2 |
| P5-R10 | `kh` deferral to after `ready`; `ks` in `ready` | 11.2 |
| P5-R11 | `lap` count 1..59,999 s | the 192 px digit chord |
| P5-R12 | LVGL period = max(16 ms, measured panel scan period) | RF0 AR-15 |
| P5-R13 | The offline screen is a layer of the host tree | 8.10 (the cover must fade; no native flash) |
| P5-R14 | Layer boxes bounded (R2) with pixel-identity proof | RF3 R2 |
| P5-R15 | `reducedMotion` resets to false at every claim | 7.1 (v6 sessions never inherit it) |
| P5-R16 | On presentation 4, `unlike` sends no feedback; other moments become plain `ok` (**[r2.2]** moot for `unlike`, which a v7 host never sends; kept as a guard) | 2.2 |
| P5-R17 | On presentation 4, Seek renders as `tracks` with the time in `title` | 2.2 |
| P5-R18 | On presentation 4, explorer → `recent` page 1 + tab, upnext → `recent` page 1 | 2.2 (flip directions preserved) |
| P5-R19 | `card:true` requires `now == count − 2` | 4.4 |
| P5-R20 | Twins gate `lvglMinFree ≥ 30 KB`; failing it blocks the release pending the user | 8.5.3; 00 §3.2 |
| P5-R21 | Internal RAM: the 40 KB gate is kept and **funded by F1** (the WAV sample arrays become `const`, +53,964 B of internal RAM); budget table, build-only projection ≥ 45,056 B, and the fallback levers F2–F4 if F1 is refused | 12.4 (cc5.4 ALIVE build: −14,272 B static; R3 −12,032 B; R5 −4,446 B) |
| P5-R22 | R5 is a dedicated decode task (core 0, priority 1, 4,096 B static stack) with a single-slot newest-wins request, a decoder-owned back buffer, abort on supersede, stale results discarded and a store decode pin | 12.5; RF3 R5 (Medium risk: buffer ownership, ordering) |
| P5-R23 | Three staged binaries for the one hardware window: A (R2+R3+R4+R5), B (R2+R3, 33 ms, R5 off), C (R2 only, cc5.3's blocking buffer, 33 ms, R5 off); image correctness checked first | 12.6; RF3 R3 bring-up risk |
| P5-R24 | The Up next card is identified only by `ring.card` (entry `count − 1`); `ring.unavailable` is stripped on layout `upnext` by both parsers | 4.4; BS:1318-1321 (Up next rows have no unavailable state); S01:166 |
| P5-R25 | `ringNow` is stored as `int32_t` | 3.6 (`now` ≤ 65,534; parity with Python) |
| P5-R26 | Entering waits for a cover decode only in R5-off builds; a `control` that keeps the previous `artKey` is valid in every build (answer to CC5 OQ-4) | 12.5.5; LT:332, :346; CCP:319-321 |
| P5-R27 | `ledPink` (0..0xFFFFFF, 0 = built-in) and `ledVolFull` (bool) are ALIVE-gated latched fields kept until reboot (not reset at a claim), +38 B of reserve | 7.3; VOC §6.2; K2 §3.2, M24 |
| P5-R28 | A whole list loading is `ring.style:"off"` + `activity:"loading"`; an unloaded entry of a known list is colour 0 with the list's activity | 4.6; K2 M31 |
| **P5-R29** **[r2.2]** | The liked heart is a **derived** tone, `liked` (`CCButtonTone` 7): `heart` + `lit:"on"` (enabled) → the filled `heartfill` glyph in `#A3244A` on the LCD, PINK 0.30 on the LED (K2 M32). No new wire value, so parsers, budget, slimming and the presentation-4 downgrade are unchanged | R22 CH §1; VOC-R26 (a new `lit` value would change both parsers and the fixtures for a state the existing fields already express) |
| **P5-R30** **[r2.2]** | `moment:"unlike"` stays a **valid reserved** token (stored 4); no v7 host sends it and K2 plays nothing for it | VOC §1.2 append-only enums; rejecting it would change both parsers during a running build for a value nobody sends |

### 16.3 Status of V4's deviations

| V4 | v5 status |
|---|---|
| P4-1 odd-volume shoulder | K2 (VOC-R04 recommends the r2.1 half-step placement) |
| P4-2 pending span both ways; P4-4 pending hold L1 | ALIVE / K2 |
| P4-3 white pending pulse on Windows | superseded by AL D13 (app colour) |
| P4-5 > 20 entries window | superseded by the r2.1 window (VOC-R03, 4.2) |
| P4-6 "Previous unavailable" | **retired**: r2.1 lines (`Start of queue`, `Prev: last played`); `prev` still dims with `unavailable` bit0 |
| P4-7 art does not translate; scales omitted | **retired as a deviation**: r2.1 now specifies exactly this (S01:116; CH §4) |
| P4-8 disconnected notice copy | **replaced** by VOC-R11 and 8.10 |
| P4-9 UWP apps: no accent, letter tile | unchanged (host); the tile colour follows 5.3 |

### 16.4 Vocabulary additions (recorded here per VOC rule 1; to be copied into VOC)

| Id | Addition |
|---|---|
| **VOC-K1a** | `ring.card` (bool): the Up next Sonos-shuffle card is the last ring entry (4.4), identified only by this field; `ring.unavailable` is stripped on `upnext` (P5-R24). This is the frozen wire form that VOC §14 handed to K1 |
| **VOC-K1b** | display `Group` 6 `offline` (internal, not a wire token) and the firmware-local offline screen (8.10) |
| **VOC-K1c** | diag fields `lcdFps`, `lcdFpsAnimMin`, `lcdRefrUsMax`, `lcdRefrUsAvg`, `lcdRenderUsMax`, `lcdFlushUs`, `lcdPxPerRefr`, `lcdFullRefrs`, `lcdLateRefrs`, `lcdMaxGapMs`, `lcdBusyPct`, `core0IdlePct`, `lcdSpiHz`, `enterMsLast`, `enterMsMax`, `holdEvents`, `holdDeferred`, `lcdDma`, `lcdPeriodMs`, `artAsync`, `artDecodeRequests`, `artDecodeAborts`, `artDecodeStale`, `stackArtDec` (12.3) |
| **VOC-K1d** | named durations `art_fade_ms` 240, `ink_fade_ms` 160, `footer_hide_ms` 160, `footer_show_ms` 280 (+140 delay), `idle_stagger_ms` 200 + 45·i, and the reveal set 150/190/180+50/340+50/170/190/320+90/420+90 (8.8) |
| **VOC-K1e** | constants `LAP_COUNT_MAX = 59999`, `FRAME_BUDGET_BYTES_V5 = 1400` (4.3, 14.1) |
| **VOC-K1f** | build flags `CC_LCD_DMA`, `CC_LCD_PERIOD_MS`, `CC_ART_ASYNC` and binary names A / B / C (12.6); task name `ArtDecode` (12.5) |
| **VOC-K1g** | the loading-list wire form `ring.style:"off"` + `activity:"loading"`, and colour 0 with the list's own activity for an unloaded entry of a known list (4.6; K2 M31) |

VOC absorbed VOC-K1a…K1g in its consistency pass (VOC §16). `ledPink` and `ledVolFull` are not K1 additions: VOC §6.2 defines them, and this contract carries their parsing, storage, latching, budget and fixtures (3.1, 3.6, 7.3, 14.1, 15.1).

### 16.5 Changes other contracts needed (all applied in the consistency pass, 2026-09-25)

| Contract | Section | Change | Why | Status |
|---|---|---|---|---|
| ALIVE_R2_DRAFT.md (K2) | §3.1 field table | add `ring.card` (bool, `selection` on `upnext`; VOC-K1a) | K2 must read the card's only wire form | applied |
| ALIVE_R2_DRAFT.md (K2) | §5.1.4 item 5, M14 row, §6.4 (if it restates the card) | identify the card as `ring.card && j == count − 1`, not by the `unavailable` bit; note that `unavailable` never reaches K2 on `upnext` (stripped, P5-R24) | the unavailable-bit form lets K1 + K3 frames draw the card as a 0.45 landmark with a 1.0 cursor | applied |
| ALIVE_R2_DRAFT.md (K2) | §13 K1 row | drop the unavailable-bit recommendation; point to K1 4.4 | frozen by K1 | applied |
| ALIVE_R2_DRAFT.md (K2) | §8.1, OQ-3 | settle OQ-3 jointly (lost-host only for cc5.4; the mismatch after a quit lasts until the first native input) | VOC-R23 | applied (18) |
| CONTROL_CENTER_V5.md (K3) | §5.6.4 frame (and §5.6.2) | in the Sonos-native-shuffle regime send `ring.card:true` with `count = P + 1`, `now = P − 1`, the card's `colors` slot 0; state that Up next frames never set `unavailable` | the frame table set neither field | applied |
| CONTROL_CENTER_V5.md (K3) | §5.2.3, §5.3.4, §5.6.4 | the 4.6 loading-list wire form and colour-0 unloaded entries | K2 M31 | applied |
| CONTROL_CENTER_V5.md (K3) | §6.1, §6.3, OQ-4, §18 K1 row | entering waits for a cover decode only in R5-off builds (binaries B, C); C5-13 stays unconditional; `control` frames keeping the previous `artKey` are valid | K1 12.5.5 answers OQ-4 | applied |
| CONTROL_CENTER_V5.md (K3) | §15.2 `knob.sub.library_error` | `Home, then Browse to retry` (197.1 px) exceeds the 170 px line; `Home, then Browse` (141.2 px) | 8.6.11; OQ-6 | applied (approval pass) |
| CONTROL_CENTER_V5.md (K3) | §5.6.5 / VOC §9.5 `knob.meta.shuffle.queue_changed` | `Queue changed` (98.4 px), reusing the retired v6 text | 172.2 px > 170; OQ-2 | applied (approval pass) |
| CONTROL_CENTER_V5.md (K3) | §3.1 Home slot 0 label | `Play/Pause` → the label follows the icon (`Play` / `Pause`) | 67.4 px > the 46 px idle column; P5-12 | applied (C5-60) |
| CONTROL_CENTER_V5.md (K3) | §18 K1 row | close: the card wire form (4.4), the `knob.status.*` widths (8.6.11: all fit 160 px), OQ-4 (12.5.5), the loading-list form (4.6) | answered here | applied |
| V5_VOCABULARY.md | §3.1 ring table | add the `card` row (VOC-K1a) and "`unavailable`: stripped on `upnext`" | VOC §14 row answered | applied |
| V5_VOCABULARY.md | §14 | close the "Wire form of the Up next Sonos-shuffle card" row → K1 4.4 | frozen | applied |
| V5_VOCABULARY.md | §13.1; §9.3 copy table | the VOC-D08 row (Home slot-0 label follows the icon) | internal inconsistency | already present (VOC-D08); P5-12 active |
| V5_VOCABULARY.md | §0.3 / K1 additions | copy VOC-K1a…K1g (16.4) | VOC rule 1 | applied (VOC §16) |

### 16.6 [r2.2] Revision log (design follow-up r2.2, 2026-09-25)

| # | Change | Source | Where |
|---|---|---|---|
| r2.2-1 | Like add-only: tone **`liked`** (7) for `heart` + `lit:"on"`: filled `heartfill` in `#A3244A`, LED PINK 0.30 (K2); new internal mask `heartfill` (+400 B); `moment:"unlike"` reserved (never sent, plays nothing); `Like removed` withdrawn from the Up next meta; `Unfavourite in Music app` (2.2 s) and `Didn’t save · try again` (2.2 s) listed | R22 CH §1; VOC-R26; P5-R29, P5-R30 | header, 2.2, 3.6, 5.1, 5.2, 6.1, 6.2, 8.6.7, 8.6.11, 9.1, 9.2, 15.1, 15.3, 18 OQ-5 |
| r2.2-2 | Copy approved; widths updated: `Speaker group changed` 147.6 (status and meta), `Couldn’t open on screen` 149.1, `Unfavourite in Music app` 152.7, `Finding songs…` 94.7 | R22 CH §2; VOC-R29 | 8.6.1, 8.6.5, 8.6.6, 8.6.7, 8.6.9, 8.6.11 |
| r2.2-3 | Seek line: `Jumping…` holds until playback resumes (≤ 8 s), across a follow-up jump (host behaviour, K3 C5-68); no LCD change | R22 CH §3; VOC-R27 | 8.6.8 |
| r2.2-4 | Recently Added meta: `Finding songs…` until the first song is queued, then `Queueing… {k} of {n}` (k ≥ 1) (host behaviour, K3 C5-69) | R22 CH §4; VOC-R28 | 8.6.5 |

### 16.7 [errata] Errata of the phase-2a gate (lead rulings, 2026-09-25)

Measured by the LVGL harness (`cc54_report.py`, 293 cases) and the host decoder tests; nothing flashed.

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| E-b | **R-b** (WP1-D1) | `twin_fade` ≤ 16 levels inside label ink boxes (P5-13's float 15 + 1) | **≤ 28** per channel for every pixel inside the label ink boxes, whatever lies under the ink (26 measured over the cover: LVGL blends twin and label separately into RGB565, 5/6-bit rounding per blend); confirmed by eye in the hardware window; no difference outside the boxes (0 measured; the harness's former ≤ 8 allowance there is gone). **Open deviation WP1-D1 (not a bound):** where two fading layers' labels overlap (the volume reveals; 24 by the float model, 35 measured) the ≤ 28 bound fails on the two volume reveal-out probes, so `twin_fade` reports FAIL until the lead rules on that class — a separate bound derived from P5-13's model at each pixel (0.8a(1 − a) × the ink under the caption, plus the RGB565 term) and limited to labels of layers fading in the same capture, or 8.8's reveals sequenced so the two layers never fade at once (options in the report's WP1-D1). **Closed by R-g** (16.8 E-g): ≤ 36 for that class | 8.5.3, 15.3, 15.4, 16.1 P5-13; `cc54_report.py` `TWIN_FADE_LIMIT` 28 (~~one bound;~~ `twin_fade_fails`, self-tested) |
| E-c | **R-c** (WP1-D3) | `Knob controls still work` one line at 0 tracking (167.5 px, design metrics) | the approved words, one line at **−1 px tracking** (171 px at 0 with the knob font; 148 px), only when it does not fit at 0; P5-14. Fallback copy if rejected by eye: `Controls still work` (130 px) via K3 | 8.5.1 `OFF_SUB`, 8.6.11, 8.10, 15.4, 16.1 P5-14; `cc_display.cpp` `showOfflineSub`; the mirror `lcd_preview.py` (`OFFLINE_NATIVE_LABEL`, the same fit test) and its tests follow (`test_offline_screen`: one run at −1; the render snapshot's offline `native` digest) |
| E-d | **R-d** | 12.4 F1 and 15.4: the boot chime and click sounds checked by ear | audio stays disabled exactly as in cc5.3 (`; -DAUDIO_EN=1` commented; `audio_loop()` never runs); no by-ear check | 12.4 F1, 15.4 |
| E-f | **R-f** (WP1-D2) | 12.5.4 step 2 specified, not built | `cc_jpeg.cpp/.h` abort hook: `CCJpegResult cc_jpeg_decode_240(jpeg, bytes, dst, &cancel)` (+ a callback form), polled between MCU rows, `JDR_INTR`, decoder reusable, abort not an error; host-tested at every band in `jpeg_tests.py` / `.cpp`. Wired: `cc_art_decode.cpp` passes `&cancelled` and maps the three results with `cc_art_decode_result()` (an abort never becomes `failed`); the harness fake stops at the next MCU band and `art_async` (h) is back to one decode time (+ at most one band, the step-2 abort latency) | 12.5.4, 12.5.7 |

### 16.8 [errata] Errata of the phase-2b gate (lead rulings, 2026-09-26)

Measured by the LVGL harness (`cc54_report.py`: 293 cases, 47 `twin_fade` probes; 39 of 39 checks after E-g) and recorded from the phase-2b build reports; nothing flashed. Lead ruling R-i (the H9 summon frame) is a K2 / K4 erratum (ALIVE 12.6, DESKTOP_STAGE 21.4) and changes nothing in this contract.

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| E-g | **R-g** (WP1-D1) | `twin_fade`: R-b's one bound (≤ 28) also where the labels of two fading layers overlap; 35 measured there on the two volume reveal-out probes, so the check failed (open deviation WP1-D1, E-b) | a **per-class bound of ≤ 36** per 8-bit channel for the **volume-reveal overlap class**: pixels inside a label ink box of the probed layer that are also inside the label ink box of another layer fading in the same capture (the volume caption over the home title in both volume reveals: two text layers fading over 150–190 ms, 8.8). R-b's ≤ 28 stays for every other pixel inside the label ink boxes, nothing may differ outside them, and opacity 0 and 255 stay identical; a label of a layer at rest makes no overlap class. Confirmed by eye in the hardware window with R-b (15.4). WP1-D1 is closed: `twin_fade` passes (worst: 26 over the cover, 35 in the overlap class) | 8.5.3, 15.3 (R-b's "whatever lies under the ink" struck in both), 15.4, 16.1 P5-13, E-b; `cc54_report.py` `TWIN_FADE_OVERLAP_LIMIT` 36 in `twin_fade_fails` (self-tested: 35 and 36 pass in the class and 37 fails; 29 over the cover fails; 35 under a label at rest is the cover class and fails) |
| E-j | **R-j** (K3 KD-4) | `Speaker group changed` (`knob.status.group_changed` / `knob.meta.group_changed`) in the neutral tone (`meta`, K3 C5-76) | the **error** tone (`#FF8474`, VOC-R10) on the Home `status` line and on every `meta` line, for its 2.6 s (`group_changed_ms`), as K3 §2.4 gives failure copy. A host rule: the tone travels in `statusTone` / `metaTone` as before, so no wire, parser, budget or LCD change | 8.6.1 Status row, 8.6.9 Meta row; K3 §2.4, §7, §9.10, C5-76 (K3 §19, E-j) |
| E-l | **R-l** (WP3b-D1…D4) | the host-side deviations of WP3b (the diag request, the `diag` event, the recorded session) documented by the build, not accepted | **accepted as built.** **WP3b-D1:** a diag request made with no knob connected, or to a knob without `diag: 1`, is dropped, not queued, and pending requests are dropped at connect and disconnect (12.3: read-only, at most one unanswered). **WP3b-D2:** the host's `diag` event carries only the listed fields (the 24 of 12.3, the 6 LED fields of K2 10.1, 7 memory fields and the binary A / B / C of 12.6); no other diag string is read. **WP3b-D3:** the recorded session (`test_cc_session_capture`) holds no `Queueing… {k} of {n}` frame, because its lanes run synchronously and the progress arrives with the result; `test_cc5_playnext` covers that copy. **WP3b-D4:** the V4 frame checker of `test_cc_contract_v4.py` accepts an explicit `first: 0` where V4's own rule would give a non-zero window start (4.2, P5-R9) | 4.2, 12.3, 12.6, 15.1; K3 §6.5 (K3 §19, E-l) |
| E-r | **RENAME** (user decision, 2026-09-26; VOC-R32; `app/design-reference/ui-v2-analysis/rename-desk-dial.md` 5) | offline sub `Open Nano_D++ on your PC` (197.9 px; `Open Nano_D++` / `on your PC`) | `Open Desk Dial on your PC` with a **no-break space** (U+00A0) between `Desk` and `Dial`: `OFFLINE_SUB = "Open Desk\xC2\xA0" "Dial on your PC"` (the literal is split: `"\xA0Dial"` would read `\xA0D` as one hex escape). 192.2 px (LVGL 198) on one line; `fitTwoLines` and its mirror break only at ASCII spaces, so the balanced lines are `Open Desk Dial` 110.4 (LVGL 114) / `on your PC` 78.0 (80), both within 170 px and their r104 chords; with a plain space they would be `Open Desk` / `Dial on your PC` (82 / 112). `cc_font_14` draws U+00A0 4 px wide, like a space. The offline screen keeps no heading (8.10; a `DESK DIAL` heading would measure 74.8 px, LVGL 75, against 138, if one is ever wanted); **decided by the lead on 2026-09-26: no heading**, as built and as r2.2 draws it (RN-10). The stock boot screen reads `DESK DIAL` / `IS BOOTING...` (`ui_bootimg.c`). Harness: `cc54_report.py` `offline` also requires that exact split (`OFFLINE_SUB_LINES`); 39 of 39 checks; widths by `harness/measure_desk_dial.py`. **Pairing:** cc5.4 ships only with the renamed desktop (the rename plan's 14.2 step 3: the knob never names an app that is not installed), so a desktop rollback to v6 (still NanoD Control Center) from a cc5.4 knob always goes with the firmware rollback to cc5.3, firmware first; the desktop rollback block refuses until the binary's rollback record is newer than its install (`app/firmware/BUILD-cc5.4.md`, "Desktop rollback, v7 -> v6"). cc5.3 next to Desk Dial keeps the old copy, the pairing the rename plan accepts (its section 12) | 8.6.11, 8.10, 16.1 P5-3; `cc_display.cpp`, `ui_bootimg.c`, `lcd_preview.py`, `cc54_copy.json` |
| E-tb | **lead** (2026-09-26; tooling deviation TB-D8, review TOOLBC-2) | 12.4 row 1 cites `work/nanod-cc5.4-build.log:1007` for the ALIVE build's static RAM (259,328 B) | that working log was rewritten by later builds of binary A (TB-D8: the build note and the 11:54–11:55 UTC logs are lost); the figure stands, and its source is the round-2 log's copy `nanod-cc5.4-build.round2.log` (1,027 lines; line 1007 `used 259328 bytes`, line 1021 `headroom 261424 B`; SHA-256 `1b897bd84d8e2c79…`). Builds now keep an earlier log as `nanod-cc5.4[-B\|-C]-build.superseded-<UTC>.log` and record its `logSha256`, and packaging refuses a log that is not the accepted build's, so a cited line cannot be lost this way again | 12.4 row 1; `app/firmware/BUILD-cc5.4.md` TB-D8 |

### 16.9 [errata] Errata of the hardware window (2026-09-26)

Binary A was flashed and rolled back the same day (12.6.1). The root cause below is from the source and from the disassembly of the flashed ELF; the fix is built and host-gated, not yet flashed.

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| E-lcd | **lead**, from the hardware-window investigation of A's dark panel (root cause confirmed in the source and the flashed ELF) | 12.6: A, B and C; `initDMA()` alone set up R3; 12.3 had no way to see whether pixels leave the chip on the right pin | every DMA build re-attaches FSPID to `TFT_MOSI` right after `initDMA()` (`cc_lcd_mosi_reattach`; `TFT_MISO` −1 had become `TFT_MOSI` and IDF's MISO step moved GPIO 4 to FSPIQ); `USE_HSPI_PORT` refused; diag `lcdMosiSig` (103 good, 102 the defect) and `build` (`CC_BUILD_BINARY` → `"A"`…`"E"`, image marker `cc-build-binary:<n>`); a host build gate refuses a DMA binary with MISO = MOSI that does not link the re-attach; the decode-task stack scan left `perfLock`. Ladder: **D** = A's pipeline + fixes, **E** = C's + fixes; A, B, C retired; a short look session (`lcdMosiSig` 103 before anyone looks, then a live dial by eye) replaces check 1 for D / E until the performance task | 12.3, 12.6, 12.6.1; `lcd_thread.cpp`, `cc_display.h` (`CCLcdPerf`), `cc_diag.h` (`cc_diag_lcd_perf_fields`); `media_tests.cpp` (diag wiring); `nanod_cc5_tooling.py`, `build_nanod_cc5.py`, `check_nanod_cc5_look.py`; `app/firmware/BUILD-cc5.4.md` |

---

## 17. C++11 rules (firmware is `gnu++11`)

Unchanged from P4 §10: no C++14 features; tables at namespace-scope `constexpr`; no odr-used `static constexpr` members. `cc_presentation.h`, `cc_frame_parse.cpp`, `cc_display.cpp`, `cc_icons.cpp`, `cc_alive.cpp`, `cc_jpeg.cpp` (abort path) and `cc_media_store.h` (decode pin) must pass `harness/cpp11_gate.py` and MSVC `/W4 /WX` (gate A5). `accent_ink()` and `mmss()` are pure functions in `cc_presentation.h`, mirrored in `presentation.py` with shared test vectors.

---

## 18. Open questions (genuine; each with a recommended answer)

| # | Question | Recommended answer |
|---|---|---|
| **OQ-1** *(resolved: VOC-D08)* | The r2.1 idle-row word for Home Button 1 is `Play/Pause` (S03:15 override #16; S03:134). At 12 px it is 67.4 px: in the 46 px column it overlaps `Browse` by ≈ 10 px and crosses the safe circle, and the knob would ellipsize it to `Play/Pa…`. What should the word be? | **Resolved by VOC-D08:** the Home slot-0 **label follows its icon: `Play` or `Pause`** (25.9 / 37.3 px). The idle view only appears while paused or with nothing playing, and in both cases the icon is `play`, so the word is always `Play`: **green** (`go`) when paused, and **dimmed** (`#5A5A5A`) when nothing is playing, because Play and Tracks are disabled then (S03:135 with the S03:10 ink; 8.6.3). The other words stay `Browse · Tracks · Win`. K3 sends it (CC5 C5-60); P5-12 is active; the wording is in the copy approval pass (VOC §9.5), **[r2.2] approved** (R22 CH §2). |
| **OQ-2** *(adopted)* | The engineering copy `Queue changed · order kept` (VOC §9.5, shuffle-off restore refused) measures 172.2 px, over the 170 px meta limit. | **Adopted:** `knob.meta.shuffle.queue_changed` = **`Queue changed`** (98.4 px) in VOC §9.5 and CC5 §15.3: the Head shake already says it failed and the on-screen list shows the kept order. Confirmed in K3's copy approval pass (00 G13); **[r2.2] approved** by the design (R22 CH §2: "the order stays as it is"). |
| **OQ-3** *(settled jointly with K2)* | Should `Waiting for PC` also show after an **intentional** release (e.g. the user quits the companion from the tray)? Today it shows only after a lost host, while the ring shows the amber waiting marks after any release (AL §8.1), so after a clean quit the LEDs say "waiting" and the LCD shows the native screen. | **Settled for cc5.4 by K1 and K2 (VOC-R23; ALIVE_R2_DRAFT §8.1):** keep **lost-host only** (P5-11): a release also happens when the companion changes device settings, and the firmware cannot tell a quit from that without a new `release` field. The LED/LCD difference after a quit lasts only until the first native input, which hands the ring to the native profile lights until the next claim (K2 M29). If the user wants `Waiting for PC` after a quit, add `{"release":true,"offline":true}` in a later release. |
| **OQ-4** | The LCD pipeline changes (R2–R5) were planned as one-variable-at-a-time A/B flashes (RF3 §8.2), but the user wants **one hardware window**. How are they verified? | Stage **three binaries** of the same release (12.6): **A** = R2 + R3 + R4 (16 ms) + R5; **B** = R2 + R3 at 33 ms, R5 off; **C** = R2 only with cc5.3's single blocking buffer, 33 ms, R5 off. A single fallback that kept R3 would leave a DMA bring-up failure with no way back except cc5.3, which also drops ALIVE and presentation 5. Per binary, check panel image correctness first, then entry and input, then `lcdFpsAnimMin` / `lcdLateRefrs` / `lcdMaxGapMs`, then memory. An image failure on A goes straight to C. Film the panel scan rate on A (RF3 §8.2 step 3). Each flash still needs the user's go-ahead. |
| **OQ-5** | ~~The LCD heart ink is the design's candidate PINK `#FF285A`;~~ **[r2.2]** The knob LCD's liked heart ink is the design's `#A3244A`; the LED PINK is tuned by eye on the ring (CH "Still open"). Should a new LED pick change the LCD ink? | **No:** ~~the LCD ink stays `#FF285A`;~~ **[r2.2] superseded:** the knob LCD's liked heart is the fixed filled `#A3244A` (R22 CH §1; tone `liked`, 5.2), not PINK; `#FF285A` is only the desktop row heart (K4), never an LCD ink. The tour changes only K2's LED constant: an `ledPink` pick never changes an LCD ink. Revisit only if the user finds the LCD heart and the ring's PINK visibly mismatched in the hardware window. |
| **OQ-6** *(adopted)* | K3's Recently Added error sub-line `Home, then Browse to retry` (CC5 §15.2 `knob.sub.library_error`) is 197.1 px at 14 px against the 170 px one-line sub; the knob would ellipsize it. | **Adopted:** **`Home, then Browse`** (141.2 px) in CC5 §15.2 and VOC §9.5: the error title `Library not loaded` already says what failed. Confirmed in K3's copy approval pass together with OQ-2; **[r2.2] approved** (R22 CH §2, 141 px). (The explorer's overlay copy `Go Home, then Browse to retry.` has no knob limit, VOC-K4-04.) |
| **OQ-7** | F1 (12.4) funds the internal-RAM gate by making the native WAV samples `const`, a change outside the control-center code. Is that acceptable? | **Yes:** it is `const` propagation only, the samples and every sound stay byte-identical, and it frees 53,964 B that nothing else can replace. If the user wants native code untouched, the release needs their decision between binary C and a 35 KB gate for A (12.4). |


---

## 19. Presentation 6 (Desk Dial r3 release 1: the Lights space; 2026-09-28)

Source: the r3 handoff `design_handoff_nano_d_r3/README.md` §1–§3, §6, §9 (copy: `harness/r3-handoff/design/`) and the approved plan (release 1 of 3: HA bridge, Lights space, launcher Home). Everything here is **append-only** on presentation 5: no token, field, default, layout or rule above changes, so every presentation-5 frame is accepted and drawn exactly as before. Firmware: `cc_presentation.h`, `cc_frame_parse.cpp`, `cc_display.cpp`, `cc_icons.cpp`, `cc_alive.*` (ALIVE.md section 15), `control_center.cpp`; Python reading: `lcd_preview.v6_parse` (parser), `lcd_preview.compose` (LCD mirror), `alive_lights` (LEDs). The host side (device.py validation, controller, Home Assistant) belongs to the Desk Dial job.

### 19.1 Capabilities and gating

- The knob reports **`presentation: 6`**. Nothing else in the capabilities reply changes (alive, artwork, artwork2, diag as before).
- A host sends the section 19 content **only when `presentation >= 6`**. A presentation-5 knob (cc5.4) rejects every token below (fatal on the host), so an older knob keeps the r2.2 UI. The host's other gates stay `>= 4` / `>= 5`.
- New layout tokens (CCLayout, append-only): **10 `lights`**, **11 `lightsbig`**, **12 `scenes`**. New ring styles (CCRingStyle): **5 `bri`**, **6 `ctemp`**, **7 `clusters`**. New icons (CCIcon): **22 `bulb`**, **23 `thermo`**, **24 `power`**, **25 `wand`**, **26 `house`**, **27 `album`**. New enum CCValueUnit: 0 `%`, 1 `K`.

### 19.2 New top-level fields

| Field | Type / bound | Default | Scope (kept on) | Meaning |
|---|---|---|---|---|
| `valueUnit` | `"%"` \| `"K"` (length-aware, case-sensitive) | `"%"` | `lightsbig` | the 22 px unit after the 48 px digits |
| `prevTitle` | text ≤ 64 B (CCFrame `char[65]`) | `""` | `scenes` | the row above the current scene (14 px `#7C7C7C`) |
| `nextTitle` | text ≤ 64 B | `""` | `scenes` | the row below the current scene (14 px `#7C7C7C`) |

Strictness is section 3.3's: a present value is validated on **every** layout (invalid → reject), then stripped silently outside its scope. Text follows 3.2 (control characters reject, longer text is cut at the last whole code point within 64 B). `volume` keeps drawing `%` whatever `valueUnit` says.

### 19.3 Ring additions

| Field | Rule |
|---|---|
| `style:"bri"` | `value` 0..100 = brightness %; **`kelvin` required**; `index` / `count` free (send 0) |
| `style:"ctemp"` | `value` 0..100 = the position of the selected K between the group's min and max (host: `round((K − 2200) · 100 / 4300)` for the design range); **`kelvin` required** = the selected K |
| `style:"clusters"` | `1 ≤ count ≤ 20` scenes, `index < count` the selected one; else reject; `value` 0 |
| `kelvin` | int **2200..6500** (never a bool or float); present on another style → validated, then stripped (stored 0) |

`first`, `colors`, `unavailable`, `moreIndex`, `external`, `now`, `card` keep their section 4 rules on every style (they mean nothing on the new ones; send none).

### 19.4 LCD (`cc_display.cpp`; mirror `lcd_preview.compose`)

| Layout | Draws | Group / depth | Art |
|---|---|---|---|
| `lights` | the Home text drawing on the home layer: `heading` (e.g. `LIGHTS`), `title` 22/26 two lines at y 61, `subtitle` 14 at y 115, and the 12 px line at y 133 = **`meta` in `metaTone`** (never `status`) | Lights, 1 | none |
| `lightsbig` | the Home reveal on the home layer: caption = `volumeCaption` (else `title`), 48 px digits of `value` (digits and `-` before any `%`), the 22 px `#A6A6A6` unit = `valueUnit`; the 12 px line = `meta` | Lights, 1 | none |
| `scenes` | own layer: `prevTitle` 14 px `#7C7C7C` y 57, `title` 22 px one line y 79 (box x 30..210, titleTone, text-shadow twin), `nextTitle` 14 px `#7C7C7C` y 109, `meta` 12 px y 133 (x 30..210, metaTone, 160 ms fade at rest) | Scenes, 2 | none |

- `lights` ↔ `lightsbig` is one group: the change is the Home reveal (track layer out, volume layer in; no slide). Home (0) → Lights (1) → Scenes (2) slide in from the right, back from the left (section 8.7). The idle row never shows on the Lights layouts.
- `cc_font_48` gains `K` (13 glyphs); the unit itself is drawn with the 22 px face like `%` (README r3 §2.2).
- The footer, tones and inks are section 5.2's: `power` on slot 3 is **nav** `#E6E6E6` (never red), a lit-on `thermo` is tone `on` `#FFFFFF`.

### 19.5 Icons

The six r3 prototype paths (`Knob IA Prototype.dc.html` `I.bulb`, `I.temp`, `I.power`, `I.wand`, `I.home`, `I.album`; README §2.2), 24-unit viewBox, round caps and joins, drift-checked verbatim by `export_handoff_icons.cjs` (src `r3`): 20 px at stroke 2.3 (footer) each, `bulb` also 26 px at 2.1 (Home idle row `Music · Win · Lights · Play`). Firmware masks: 37, **16,024 B** (12,948 + 6 × 400 + 676). The r2.1 masks are byte-identical.

### 19.6 Kelvin colour

`cc_kelvin_rgb(K)` (cc_presentation.h) = README r3 §3 (Tanner Helland), clamped 0..255, rounded half up in double; K clamped to 2200..6500. 2200 K = 255,146,39; 2700 K = 255,167,87; 3200 K = 255,184,123; 6500 K = 255,254,250. The nearest channel to a .5 tie over 2200..6500 is 3.1e-5 away, so newlib, MSVC and CPython agree (checked for every K). **Calibration hook:** `CC_KELVIN_GAIN` (= `alive_lights.KELVIN_GAIN`) scales each channel afterwards, `(c · gain + 127) / 255`; `{255, 255, 255}` today. Matching the ring's real white point to the bulbs is a by-eye step on hardware.

### 19.7 Fixtures and gates

- `harness/fixtures/frames_v6.json` (`make_frames_v6.py`): 42 hand-judged cases + the Kelvin vector; `parse_tests.py` holds `lcd_preview.v6_parse` and the firmware parser (MSVC /W4 /WX) to it, with every v4 / ALIVE / v5 default of an accepted frame; the existing v4 / alive / v5 fixtures and the cc5.3 downgrade pass unchanged.
- LCD harness: every accepted `frames_v6` case (group `v6`) and the 17 r3 screens of `r3-handoff/r3_screens.json` (group `r3`); `cc54_report.py` (all 39 checks, incl. `mirror_parity` of `lcd_preview`) extended for the new roles (the scenes title is a thirteenth twin). Contact sheet: `r3-handoff/contact-sheet-r3.png` (`r3_sheet.py`).
- CCFrame grows 136 B (1,124 → 1,260 B on x64 MSVC); the build gates (size, heap projection) apply as before.

### 19.8 Open for the next releases (not in presentation 6)

- The design's amber `#FFBE69` for `Knob: temperature` / `Runs in 1 s` has no line tone; release 1 sends `secondary` (`#A6A6A6`). A `warm` line tone would be one more append-only token.
- The design's active-mode footer ink (`act` `#FFBE69` in the prototype) differs from 5.2's lit-on `#FFFFFF`; release 1 keeps 5.2.
- Arc breadcrumbs, the hold-1 progress ring, the unavailable-press bottom flash: release 2.

### 19.10 [r3.1] Desk Dial r3.1 (user feedback round + the r3.1 design delta; 2026-09-29; append-only)

Sources: the approved r3.1 plan (Job B) and `design-reference/r3.1-design-delta.md` (Job B rows; `Knob IA Prototype
r3.1.dc.html`, copied to `harness/r3-handoff/design-r3.1/`). Nothing above changes; every r3 frame parses and
draws as before.

- **Holds (`kh`, 11.2):** every physical button now sends `{"id","ks","kh":raw}` once per press when held: the raw at
  physical slot 0 (`buttonOrder[0]`) after **600 ms** (`kHoldMs`, unchanged, incl. the deferred-hold rules of step 5),
  every other raw after **1000 ms** (`kHoldOtherMs`). Each claimed press sets its raw's AceButton long-press delay from
  its physical slot (the buttonOrder in force at the press). `kd` / `ku` are unchanged; the host decides tap vs hold
  (button 4 acts on release; a `kh` cancels the tap).
- **`holdMarker`** (top-level bool, absent = false, any other type rejects; kept on every layout): button 4 has a hold
  action on this screen (Home in both domains, Recently Added / Playlists, the explorer, Up next). The LCD draws the
  **hold tick**, a 16 x 2 px bar, radius 1, `#A6A6A6`, at (176, 180) under the button-4 footer icon (x 184), with the
  footer (not in the idle icon view), fading 200 ms (`footer.tick`; the footer layer grows to rows 152..181). The LEDs
  draw the button-4 hold ring only on such a frame (ALIVE.md 15.8).
- **Ring style `queue`** (9, `CC_RING_QUEUE`; count >= 1, index < count, else reject): the whole-queue Tracks and Up
  next. `index` = the focused row, `ring.now` (-1..count-1, validated as in 4.4) = the playing row, **kept on the queue
  ring on every layout**; `first` / `colors` follow the window rule; `kelvin` is validated and stripped. The Tracks
  prev / dot / next position row is drawn only with the `transport` ring (any other ring hides it). LEDs: ALIVE.md 15.9.
- **Crumb `playlists`** (appended after `scenes`, `CC_CRUMB_PLAYLISTS` = 10): the arc `MUSIC › PLAYLISTS` (ancestor
  #7C7C7C, current #E6E6E6), depth 2; `cc_crumbs.cpp` regenerated by `make_crumbs.py` from `crumb_arc.py`.
- **Paused cover:** a Home-layout frame with `playing:false` (the parser keeps `playing` on Home layouts only) draws its
  cover at `image_opa` **143** (0.45 / 0.8 of the pre-composited cover; `cc_art_image_opa`); `artDim` (112) wins; else
  255. Paused therefore keeps the Now Playing layout with its art (the host no longer idles after 4 s paused).
- **Icons:** `house` and `album` also have 26 px masks (stroke 2.1), so the Music space idle row draws Home and Recent:
  firmware masks 17,376 B (16,024 + 2 x 676). The design's `listMusic` glyph is the existing `playlists` token (the same
  path), so button 3 of Recently Added / Playlists sends `icon:"playlists"` (lit `on` in Playlists: the r3 active ink
  `#FFBE69` and the warm 0.90 LED); no new icon token.
- **Wire compatibility:** `playlists`, `queue` and `holdMarker` are rejected by an r3 (release 1) knob; the host sends
  them only to this firmware (knob and Desk Dial are installed together).

## 20. r4 motion (design_handoff_nano_d_r4, 2026-09-30; plan stage F4)

Supersedes the section 8.8 motion rows where they differ; screens, copy and button maps stay r3.1. Summary and
measurements: `MOTION.md`. Normative for `cc_display.cpp` and the harness (`cc54_report.py` `r4_moments`):

- **Tokens.** `SPRING.snap / soft / pop / wall` = (0.36, 0.72) / (0.46, 0.82) / (0.42, 0.52) / (0.34, 0.42)
  (response s, damping), baked as `kSpringLut` (`make_motion.py`), settling in 416 / 544 / 624 / 648 ms; the knob-
  following moments (M4, M5, M13) run on a 4 ms semi-implicit Euler stepper that retargets and never queues.
- **8.7 screen change = M1.** The content enters from **28 px** (was 20) in the depth direction on `SPRING.snap`
  (was 380 ms OUT); opacity 0 → 1 in **240 ms** OUT (was 220). No scale (a transform is a layer). `lastSlide` = ±28.
  The crumb crossfades with it (M15: two slots, 240 ms). From the offline layer and on a claim: 220 ms as 8.10.
- **Reveal.** M2: text out 130 ms IN (−12 px, 160 ms); big layer from +14 px, 180 ms OUT after 40 ms, `SPRING.snap`
  after 40 ms. M3: big out 130 ms IN (+14 px, 160 ms); text back after 90 ms: 260 ms OUT, `SPRING.soft`.
- **Idle row (M11).** Stagger 140 + 40 i ms (was 200 + 45 i), fade 260 ms OUT, from +16 px (was 14) at 85 % icon
  scale, `SPRING.pop`; exit 120 ms opacity / 140 ms offset IN.
- **Text at rest (8.5.4 + M6).** A meta / status line whose text changed at rest fades in over **240 ms** (was 160)
  and rises 10 px (`SPRING.soft`); not on a detent that glides the rows (M4). The Home status leaves with a plain
  fade (its words kept until the next text).
- **New moments.** M4 list glide, M5 track change, M7 press squash (`cc_display_input`), M8 landing pop, M9 Play ⇄
  Pause morph (12 frames, same screen only), M10 hold-4 fill (the icon's own mask in a growing clip box), M13 wall
  stretch (`cc_display_wall`, driven by `cc_wall.h`). Table in `MOTION.md` section 2.
- **Reduced motion (7.1 latch).** Every moment is a **160 ms** opacity crossfade (8.9's 220 ms content fade → 160):
  no translate, scale or morph; M10 fades its warm copy in instead of filling.
- **Layout (README 3.6).** Crumb: at most two named levels, ≤ 190 px of arc, else `‹ CURRENT`; scenes rows 104 /
  160 / 150 / 176 px, Tracks meta 176 px; big value `number | 4 px | unit` (`DIGIT_GAP` 4).
- **Layer boxes (8.2 R2).** content rows 28..164 (M11's +16), list-like layers +10 px below their meta (M6), footer
  42..197 × 150..181 (M8's 1.28×); `v5_bounded` holds.
- **Render speed (12.x).** Twins are hidden while no cover shows (identical pixels); A8 masks draw from flash; the
  LVGL heap bound of the harness is 37 KB (r4: +2.1 KB x64); the device gate `lvglMinFree >= 30 KB` stands.

