# UI V2 analysis 04: firmware gap map (master design → cc5.4)

Read-only extraction, 2026-09-25. Target: the one combined release **firmware 1.0.0-cc5.4 + desktop v7**. It carries the ALIVE LED engine (in progress) and the whole master design (`design_handoff_nano_d_master`).

This file lists, for every knob-side change in the master design, what the **firmware** has to change. For each change it gives:
- the current code (file:line);
- the new code, data or wire field;
- the host-side dependency, where the firmware can't act alone;
- the flash and RAM cost;
- the risk.

Behaviour, copy and timings were extracted in 01 (knob), 02 (LEDs) and 03 (desktop). This file does not repeat them, except where the firmware needs an exact number.

---

## 0. Sources, notation, method

All paths are under `<repo>\`.

| Key | File |
|---|---|
| **R, S01, S02, S03** | `app\design-reference\design_handoff_nano_d_master\README.md`, `specs\01-…`, `specs\02-…`, `specs\03-…` |
| **BS** | `…\design_handoff_nano_d_master\prototypes\Browse and Snap.dc.html` (primary prototype) |
| **A01 / A02 / A03** | `…\ui-v2-analysis\01-knob-behaviour.md`, `02-leds.md`, `03-desktop.md` |
| **CS** | `…\ui-v2-analysis\check-seek.md` |
| **FD** | `firmware\src\cc_display.cpp` (LCD renderer) |
| **FDH** | `…\src\cc_display.h` |
| **FP** | `…\src\cc_presentation.h` (CCFrame, enums, tones, inks) |
| **FPA** | `…\src\cc_frame_parse.cpp` (frame parser) |
| **FI** | `…\src\cc_icons.cpp` / `cc_icons.h` (generated A8 masks) |
| **FA / FAH** | `…\src\cc_alive.cpp` / `cc_alive.h` (ALIVE engine, in progress) |
| **FL** | `…\src\cc_lights.cpp` / `cc_lights.h` (v4 ring geometry) |
| **HM / HMH** | `…\src\hmi_thread.cpp` / `hmi_thread.h` |
| **CM** | `…\src\com_thread.cpp` |
| **CCP** | `…\src\control_center.cpp` |
| **FT / HP** | `…\src\foc_thread.cpp` / `haptic.cpp` |
| **LT** | `…\src\lcd_thread.cpp` |
| **LV** | `firmware\include\lv_conf.h` |
| **FN / F48** | `…\src\fonts\cc_fonts.h` / `cc_font_48.c` |
| **GI / GF** | `harness\export_handoff_icons.cjs` / `gen_lvgl_font.py` |
| **AB** | `firmware\.pio\libdeps\nanofoc_d\AceButton\src\ace_button\ButtonConfig.h` (AceButton 1.10.1) |
| **AL / P4 / A2** | `firmware\ALIVE.md`, `PRESENTATION_V4.md`, `ARTWORK2.md` |
| **DV / PR / CT / RT / AW** | `app\control_center\device.py`, `presentation.py`, `controller.py`, `runtime.py`, `artwork.py` |
| **INV** | `app\backups\control-center-inventory-20260924T194448Z-a8bbd7b8.json` (latest profile inventory backup; only profile names and detent fields were read) |
| **B53 / D53** | `app\diagnostics\cc5.3-build.json` / `cc5.3-device-checks.json` |
| **ELF** | `firmware\.pio\build\nanofoc_d\firmware.elf` (2026-09-24 18:32 build, read with `xtensa-esp32s3-elf-size`/`nm` from `C:\esphb\idf\tools\xtensa-esp-elf\esp-14.2.0_20260121`) |

- **LCD boxes** are given as `{x, y, w, h}` in LVGL label-top coordinates, the convention FD:48–49 uses: `y = round(CSS top + CSS baseline offset) − ascent`. Measured from the existing boxes, that is CSS top − 1 for 12/14 lines, CSS top + 1 for 14/18, 16/20 and 22/26 lines, and CSS top − 3 for the 48/46 line.
- **Text widths** in section 2 were computed from `app\assets\fonts\Montserrat.ttf`, instanced in memory at wght 500 (the generator's weight, GF:104). Kerning is ignored, so they are estimates to ±2 px. **Safe chords** use FD's own rule (FD:238–247, radius 104).
- **Nothing was built, flashed or run.** No serial port was opened. Sizes marked "est." are estimates.

---

## 1. Summary: every knob-side change and its firmware work

| # | Master design item | Firmware today | Firmware change | Host / wire dependency | Size |
|---|---|---|---|---|---|
| 1 | **Seek screen**: `SEEK`, 14 px title, **48 px `m:ss`**, `of m:ss` (R:113–115; S01:164; BS:238–243) | No layout (FP:11–14) | New `CC_LAYOUT_SEEK`, a new seek layer with 3 labels, and a tabular 48 px font with `:` (sections 2.2 and 4) | `layout:"seek"`, `ring:{style:"lap", index:s, count:D}` | M |
| 2 | **Explorer mirror** `RECENT · SCREEN` / `PLAYLISTS · SCREEN` (R:121; S01:119) | The list renderer exists (FD:841–849), but it has no family and no depth | New layout `explorer`, drawn by `renderList`; depth 30 + page (tab); art on | `layout:"explorer"`, `page` 0/1 = tab | S |
| 3 | **Up next mirror** `UP NEXT · SCREEN` (R:121) | as above | New layout `upnext`, depth 30; art on | `layout:"upnext"`, `ring.now` | S |
| 4 | **Tracks rows**: `Now/Next/Prev:` line, skip-back · **filled dot** · skip-forward (R:116–120; BS:227–237) | Named glyphs prev/dot/next at 16 px, stroke 2.4 (FD:64–65, 851–866) | New glyph masks, and a filled 6 × 6 dot. The copy is all host text. | none (copy is host text) | S |
| 5 | **Windows**: 32 px app icon, app, title, snap meta (R:122–125) | Already drawn (FD:66–72, 874–927). The artwork2 icon is in place. | None for the layout. Art must **fade** 560 ms on entry, not hide (FD:961–969, 1024–1031). The tile fallback colour is an option. | meta text from the host | S |
| 6 | **Home / volume reveal**: 48 px spring, `Paused · {title}` (R:109–111) | Implemented to the millisecond (FD:791–839) | **None**. The scale 0.98/0.93 stays omitted (P4:328, deviation 7). | reveal timing and confirmation are host-side | – |
| 7 | **Darker scrim** .60/.72/.92/solid (R:108; S01:107–113) | Composited **on the host** (AW:56, 237–241). The knob draws the JPEG as-is (FD:1055–1060). | **None required.** Optionally rename the capability `"scrim80"` (CCP:116, `cc_media_store.h:370`). | `AW:56` `_SCRIM_STOPS` | – |
| 8 | **Text shadow** `0 1px 3px rgba(0,0,0,.8)` (R:108; BS:209) | Not possible. LVGL 9.0.0 has no text shadow (section 2.8). | Optional "twin" labels: a black 80 % copy 1 px lower, with no blur. It's a deviation. | none | S–M |
| 9 | **Screen change**: only the text layer slides; footer and art stay; direction is explicit (R:126; BS:207–251, 649) | The whole stage fades and the footer slides with the content (FD:1223, 1263–1274) | Move the footer out of `content`, fade `content` instead of `stage`, and add new depths (section 2.9) | depth via the new layouts | S |
| 10 | **Button tones** `on` #FFFFFF / `off` #7A7A7A / colour (pink, app); dim #5A5A5A (BS:938, 981) | 5 tones derived from the icon (FP:26, 94–100, 164–184) | New tones ON and OFF, a colour ink, and a decision on the dim ink | `buttons[j].lit`, `buttons[j].color` | S |
| 11 | **Icon vocabulary** (R:83–104; BS:395–405) | 12 wire tokens (FP:20–24) and 16 masks × 3 sizes (FI) | 9 new tokens, 7 changed glyphs, a snap mask with a filled half, and a generator rewrite (section 3) | `presentation.ICONS` (PR:63–64) | M |
| 12 | **Glyphs**: `:` at 48 px, tabular digits | `cc_font_48` has only `% - 0–9` (FN:12) and no fallback (LV:386) | Regenerate with `:`, plus a tabular 48 px descriptor (section 4) | none | S |
| 13 | **Frame fields** | FP:41–73, FPA:232–291 | New layout tokens, `ring.style "lap"`, `ring.now`, `buttons[j].lit`, `feedback.moment/side/color`, plus the ALIVE fields (AL:74–81) (section 5) | DV and PR parity | M |
| 14 | **Hold 600 ms = Home** (R:67; S01:44) | Only press and release edges (HM:334–349). No long press (AB:431). | **A firmware hold event `kh` is needed.** Host-only timing breaks on the Back re-entry (section 6.1). | DV emits `hold` | S |
| 15 | **Windows only from Home** (R:81) | F24 fires on the windows button in **any** mode when it's enabled (CCP:294–299; HM:338–342) | Gate F24 on `icon == win`, and the host sets `windowsHidEnabled` per control | RT:1356, 1385–1389 | XS |
| 16 | **Seek on BINARIS BEER**, 5 s per detent (R:60; S01:163) | The control command already takes any installed REGULAR profile (CCP:203–213) | **None.** The profile exists and is valid (section 7). | host bounds mapping | – |
| 17 | **LED engine additions**: half-wash, pink bloom, scatter, Play-next sweep, Seek lap, Up next levels, on/off/colour buttons (A02 §9) | ALIVE engine without these (FAH:70–73, 108–124; FA:246–253, 384–413, 1176–1209). It's not yet integrated in HM:597–654. | Section 8 | `feedback.moment`, `ring.now`, `lit`, `lap` | M |
| 18 | **Capability** | `presentation: 4` (CCP:110) | `presentation: 5` (plus ALIVE's `alive`). A v6 host still works, because DV compares `>=` (DV:182, 200, 444). | PR `PRESENTATION_VERSION` | XS |

Size key: XS < 10 lines; S < 150 lines; M < 600 lines (firmware plus its twin in `lcd_preview.py` / `alive_lights.py`).

---

## 2. LCD (`cc_display.cpp`)

### 2.1 Current tree and what changes

Today (FD:10–24, 1131–1242):
```
screen
 └ stage            ← opacity tween on a screen change (FD:1268)
    ├ art           ← own opacity tween (FD:1047–1072); never translates
    └ content       ← translate_x on a screen change (FD:1267)
       ├ heading
       ├ home { track, volume, status, idle[4] }
       ├ list { title, sub, meta }            (recent, notice)
       ├ tracks { title, pos[3], sub, meta }
       ├ windows { tile{letter, icon}, app, title, meta }
       └ footer[4]                              ← slides with content (FD:1223)
```

What the master needs (BS:206–258):
```
screen
 └ stage             (no opacity tween any more)
    ├ art             unchanged; also fades 560 ms on Windows entry (2.5)
    ├ content         translate_x ±16/20 px AND opacity 0→255 220 ms (BS:649)
    │  ├ heading
    │  ├ home, list, tracks, windows   (unchanged)
    │  ├ seek { caption, time, duration }   ← NEW (2.2)
    │  └ [optional shadow twins]            ← NEW (2.8)
    └ footer[4]       ← MOVED out of content: no slide, no fade (BS:251 is a sibling of the text layer)
```

Concrete edits:
- **FD:1223.** Create `footerLayer` under `stage`, after `content`, so it draws on top: `makeFullLayer(footerLayer, stage, "footer")`. `renderFooter`'s idle fade (FD:934) stays.
- **FD:1263–1274.** Replace `tweenFrom(stageOpa, 0, 255, 220, 0, EASE_OUT)` with a new `contentOpa` tween on `content`. `lv_obj_set_style_opa` on a parent scales its children in LVGL 9.0, as the stage tween does today, so no layer is needed. Keep `contentTx`.
  - The art then no longer blinks on a screen change, which is what BS does: its art div sits outside the sliding layer (BS:207).
  - The rule "a cached cover swaps instantly" (FD:1063–1069) is unchanged.
- **FD:87** `SLIDE_PX = 20`. BS uses 16 (BS:649); R:126 and S03:161 say 20, and S01:129 says "16–20". The decision is open (A01 open question 13). Changing it is one constant, plus `stats.lastSlide` (FDH:89) and the harness expectations.
- **FD:1252–1253.** The layout clamp `frame.layoutId <= CC_LAYOUT_NOTICE ? … : NOW_PLAYING` assumes NOTICE is the last enum value. New layouts must be appended after NOTICE and the clamp updated. Otherwise they render as Home.
- **FD:1278–1287.** Visibility and dispatch: add `seekLayer`. `listLayer` becomes visible for `recent | notice | explorer | upnext`.
- **FD:1288.** `releaseMedia(ICON)` outside Windows is unchanged.

### 2.2 Seek layout (new)

The source is BS:238–243. The spec is R:113–115 and S01:164.

| Element | CSS (BS) | Firmware box `{x, y, w, h}` | Font / ink | Content |
|---|---|---|---|---|
| Label | x 35, w 170, top 32, 12/14, 0.08 em, #A6A6A6 | existing `heading` (FD:50 `{30, 31, 180, 15}`) | `cc_font_12`, tracking 1 | `SEEK` (host `heading`) |
| Caption | x 35, w 170, top 52, 14/18, #A6A6A6, 1 line, ellipsis | `SEEK_CAPTION = {35, 53, 170, 16}`, the same as `VOL_CAPTION` (FD:54) | `cc_font_14`, `CCInk::context` | song title (host `title`) |
| Time | x 0, w 240, top 76, **48/46, −0.02 em, tabular**, #F2F2F2, centred | `SEEK_TIME = {0, 73, 240, 52}`, the same baseline as `DIGITS_Y` (FD:55, baseline 116) | **`cc_font_48t`** (tabular, section 4), tracking −1 (`DIGITS_TRACKING`, FD:84), `LV_TEXT_ALIGN_CENTER`, `CCInk::text` | `m:ss` |
| Duration | x 35, w 170, top 128, 14/18, #A6A6A6, tabular | `SEEK_DUR = {35, 129, 170, 16}` | `cc_font_14` (see 4.3 on tabular), `CCInk::context` | `of m:ss` |
| Art | 0.8 with scrim | existing art layer | – | now-playing album |
| Footer | Back · Open on screen · Seek (`on`) · Skip (`dim`) | existing footer | – | – |

**Formatting** (BS:445 `mmss`): the minutes are unpadded and may exceed 59; the seconds are two digits.
- `snprintf(buf, 12, "%u:%02u", s / 60, s % 60)`, with `s` a `uint16_t`.
- The duration line is `"of "` + `mmss(D)` (BS:1083 `seekDur`).

**Where the numbers come from.** Recommended: from the ring fields the LED lap needs anyway.
- The time is `ringIndex` (target seconds) and the duration is `ringCount` (D seconds) on `layout:"seek"`.
- One source of truth serves the LCD and the ring, and no new text field is needed.
- The alternative, host-formatted text in `value` and `meta`, must **not** go through the Home digit filter (FD:803–806), which drops `:`.

**Width check** (Montserrat Medium 48 px; tabular cell 33.6 px, `:` 10.9 px, tracking −0.96 px):

| Text | Tabular | Proportional (today's glyphs) |
|---|---|---|
| `0:00` | 108.8 px | 104.1 px |
| `9:59` | 108.8 px | **94.8 px** |
| `10:00`, `59:59`, `72:05` | 141.5 px | 120.9–122.9 px |

- The safe chord at the digit rows (y 81–116) is **192 px**, so every case fits.
- Without tabular digits, a centred `m:ss` changes width by up to 9.3 px between detents. That's a visible 4–5 px side-to-side jitter on every turn, and the reason BS asks for `tabular-nums` (BS:241).

**Motion.** Entering or leaving Seek is an **instant layer swap** with no slide (BS:664–668, A01:176–181).
- `CC_LAYOUT_SEEK` must therefore map to `GROUP_TRACKS` in `groupOf` (FD:772–779).
- The group and page are then unchanged, so there is no slide (FD:1265).

**LVGL heap:** 1 full-screen box plus 3 labels, about 0.8–1.0 KB (est.) of the 64 KB heap (LV:45). The labels are created once, like every other layer (FD:1131–1242).

### 2.3 Explorer and Up next mirrors (new layouts, list geometry)

**Geometry.** Both reuse `renderList` (FD:841–849) and the list boxes:
- `LIST_TITLE {35, 53, 170, 50}`, `LIST_SUB {35, 107, 170, 16}`, `LIST_META {24, 126, 192, 15}` (FD:58–60).
- BS uses x 35 / w 170 for the meta line (BS:225). The difference is minor (A01 row 34).

**Why new layout tokens, not `recent`:**
1. **Slide direction.** `depthOf` (FD:782–789) gives recent `1 + page` and tracks `1`.
   - Up next reached from Tracks as `recent` page 0 has depth 1. Back to Tracks (1 ≥ 1) would then enter from the **right**; BS enters from the left (BS:681).
   - Proposed depths: home 0, tracks/seek 1, recent 1 + page, windows 5, **explorer 30 + page** (page = tab: 0 Recently Added, 1 Favourite playlists), **upnext 30**. These reproduce every BS flip:

     | Transition | BS flip | Source |
     |---|---|---|
     | Recent → Explorer | +1 | BS:797 |
     | Explorer tab to playlists | +1 | BS:808 |
     | Explorer tab back to Recently Added | −1 | BS:808 |
     | Explorer → Recent | −1 | BS:802 |
     | Tracks → Up next | +1 | BS:750 |
     | Up next → Tracks | −1 | BS:681 |
     | Seek → Up next | +1 | BS:750 |
     | Explorer or Up next Play → Home | −1 | BS:813, 696 |
2. **ALIVE families.** The tint, the Reveal and the D7 wash need `explorer` and `upnext` families (A02 F15, F19; section 8).
   - `cc_alive_family` (FA:246–253) maps unknown layouts to HOME. A mirror sent as a new token without that mapping would light like Home.

**The tab switch** is a page change within one layout, so the existing rule "slide when (group, page) changes" (FD:1263–1266) produces it.
- The host sends the new page 190 ms after the press (BS:808).

**Art.** Add `explorer` and `upnext` to `layoutShowsArt` (FD:1025–1026).

**Heading fit (a risk).** At `HEADING` y 31 the cap ink rows are 35–42. The safe chord there is only **118 px**.

| Heading | 12 px, tracking 1 px | No tracking | `showHeading` outcome (FD:546–582) |
|---|---|---|---|
| `RECENTLY ADDED` | 127.8 | 114.8 | special-cased to stay (FD:558, 561) |
| `RECENT · SCREEN` | 124.4 | 110.4 | tracking dropped |
| `UP NEXT · SCREEN` | 129.5 | 114.5 | tracking dropped |
| `PLAYLISTS · SCREEN` | 142.4 | **125.4** | tracking dropped **and ellipsized** (`PLAYLISTS · SCRE…`) |
| `TRACKS`, `SEEK` | 54.2 / 35.2 | – | fit |

- **Decision needed.** Allow the heading to run to r 112 (the bezel start: chord 143 px, BS clips at r 120), or change the copy.
  - Extending the `RECENTLY ADDED` exception to all four labels keeps their tracking consistent.
  - Confirm on the harness (`cc5_report.py` measures corner ink); these widths are ±2 px estimates.

**Up next with a long queue.** The ring window of 20 (FP:29, 126–131) applies. It needs the absolute `ring.now` (section 5).

**Cover decode cost.** Every detent in an Up next **playlist** queue (and in the explorer) can bring a new `artKey`.
- A cover decode costs **46–149 ms** on the knob (D53 `jpegDecodeMsLast` samples). It runs synchronously on the LCD task before the render (FD:1016–1041; LT:357–360).
- Recently Added has the same cost today, but in Up next with mixed-album playlists it happens on most detents. The flagged risk is LCD lag during a fast spin.
- Only the back buffer's previous key is reused for free (FD:979–980).

### 2.4 Tracks

BS:227–237; S01:120.

| Element | BS | Firmware today | Change |
|---|---|---|---|
| Label | x 35, w 170, top 32 | `heading` | none |
| Title | x 35, w 170, top 54, 22/26, **1 line** | `TRACKS_TITLE {30, 55, 180, 24}` (FD:61) | Optionally set x 35 / w 170. The fit is tight: `Turn to choose` is 166.7 px against a 168 px chord (rows 59–80), and `Previous track` is 160.0 px. Keep the chord clamp and check on the harness. |
| Position row | x 72–168, top 88, `space-between`, `align-items: center`: skip-back 16 px, **6 × 6 filled circle**, skip-forward 16 px; **stroke 2.3** | 16 px icons `prev`, `dot`, `next` at x 72 / 112 / 152, y 88; stroke **2.4** (FD:64–65, 856–861; GI:26) | New 16 px masks for skip-back (BS `I.prev`) and skip-forward (BS `I.tracks`) at stroke 2.3. The centre becomes a **filled** circle 6 px across: a 16 px mask with a centred disc (x 117–123, y 93–99), or an `lv_obj` with `LV_RADIUS_CIRCLE`. The names in FD:856 change. |
| Line | top 110, 14/18 | `TRACKS_SUB {35, 111, 170, 16}` | none (host copy `Now:` / `Next:` / `Prev:`, or `End of queue` / `Start of queue`) |
| Meta | top 130, 12/14 | `TRACKS_META {30, 129, 180, 15}` | none (host copy `Press 4 to skip` or `{i} / {n}[ · shuffle]`) |
| Selected ink | #F2F2F2 / #7C7C7C | `CCInk::text` / `CCInk::meta` (FD:858); `#555555` when Prev is unavailable (FD:859; FP:90) | none |

`showNamedIcon` sets each position glyph once and never changes it (FD:730–744). That's fine, because each slot keeps a fixed glyph.

### 2.5 Windows

- **The 32 px app icon already works.** It's the artwork2 `iconKey` in the tile at x 104, y 42 (FD:66, 874–900, 1202–1218; A2 §7). **No layout change.**
  - App name `WIN_APP {35, 81}`, title `WIN_TITLE {35, 101}`, 2 lines, and meta `WIN_META {30, 138, 180}` (FD:70–72) match BS:244–249.
- **Meta** `Left: {App} · pick right` / `Right: {App} · pick left` is host text. At 12 px, `Right: Chrome · pick left` is about 147 px, and the chord at rows 141–152 is 196 px. It fits.
- **Art on entry** (BS:1089; A01 row 18): opacity → 0 over **560 ms OUT**, and `scale(1.06)`.
  - Today `prepareArt` returns `ART_NONE` for Windows (FD:1025–1030) and `hideArt()` cuts the art instantly (FD:961–969).
  - **Change:** treat Windows like the idle view. Keep the front buffer and its key, then run `tween(artOpa, 0, 560, 0, EASE_OUT)` (FD:1071). Release the cover pin after the fade, or keep it until the next key.
  - The scrim is baked into the cover, so it fades with it. That's equivalent on a black LCD.
  - The 1.06 scale stays omitted (P4:284, no transforms).
- **Tile fallback** (A01 open question 9):
  - BS / S04 use the app's dominant colour with a white 16 px **bold** letter. The firmware uses `#444` (FP:89) and Medium 500 (`cc_font_16`).
  - The colour could come from `ringColors[index − first]` in colour mode.
  - Bold would need a new font, so that's a deviation.
- The Windows `activity` and closed-entry rules (FD:868–872, 914–920) are unchanged.

### 2.6 Home and the volume reveal: no firmware change

These are already implemented exactly as R:110, S03:86–99 and BS:1086–1087 specify:

| Motion | Firmware |
|---|---|
| Track exit: opacity 150 ms IN, translate −8 over 190 ms IN | FD:797–798 |
| Track return: 320 / 420 ms OUT after a 90 ms delay | FD:797–798 |
| Volume enter: opacity 180 ms OUT after 50 ms; translate from 6 px over 340 ms **SPR** after 50 ms | FD:821–822 |
| Volume exit: 170 / 190 ms IN | FD:821–822 |

- **Layout:** 48 px digits plus a 22 px `%`, 2 px gap, one shared baseline 116, centred as a group (FD:802–820).
- **Idle icon row:** FD:829–838, with the stagger `200 + 45·i`.
- **Caption and status copy** (`Paused · {title}`, `Minimum` / `Maximum`, no room name) and the 1.4 s hide after Sonos confirms are host-side (CT:42, 451).

### 2.7 Darker scrim: host-composited, no knob change

- **Host:** `AW:56 _SCRIM_STOPS = ((0, .35), (108, .55), (149, .90), (168, 1.0), (239, 1.0))`. `_scrim_factor(y) = 0.8·(1 − a)` (AW:237–241) is applied to every 240 px cover (AW:273–276, 437–439) and to the desktop's 480 px `hires_jpeg` (AW:250–266).
- **Knob:** it draws the JPEG (or the upscaled v1 120 px cover) at `image_opa` 255, or 112 when `artDim` (FD:86, 1055–1060). It never composites a scrim.
  - `LV_GRADIENT_MAX_STOPS 2` (LV:280) would rule out a knob-side four-stop gradient anyway.
- **Change (host only):** `_SCRIM_STOPS = ((0, .60), (108, .72), (149, .92), (168, 1.0), (239, 1.0))`. Rows 108 / 148.8 / 168 are the design's 45 / 62 / 70 %; the current code rounds 148.8 to 149.
  - Cover keys are `sha256(jpeg)[:24]` (AW:317–319, 532–534), so every cached cover gets a new key. Stale covers are never mixed in, on the knob (the PSRAM store is volatile) or on the desktop.
- **Optional firmware change:** the capability strings `art["composited"] = "scrim80"` (CCP:116) and `a["composited"] = "scrim80"` (`cc_media_store.h:370`) describe the composite. Nothing gates on them: only `standalone.py:344` displays them.
  - Renaming them (for example to `"scrim92"`) is cosmetic, and it would break `test_standalone.py:69–74` and `test_cc_contract_v4.py:24` fixtures. **Recommendation:** leave them.

### 2.8 Text shadow: feasibility in LVGL 9.0

- **LVGL 9.0.0 has no text shadow or outline style.** The text properties are only `TEXT_COLOR`, `TEXT_OPA`, `TEXT_FONT`, `TEXT_LETTER_SPACE`, `TEXT_LINE_SPACE`, `TEXT_DECOR` and `TEXT_ALIGN` (`lvgl/src/misc/lv_style.h:273–280`).
- The `SHADOW_*` properties (lv_style.h:247–253) draw a **box** shadow around the object rectangle, not the glyphs. It's also expensive, because `LV_DRAW_SW_SHADOW_CACHE_SIZE 0` (LV:123).
- There is no blur filter, and "no `opa_layered`, no transforms" is a contract rule (FD:37–39; P4:284).

**Options:**

| Option | What | Cost | Verdict |
|---|---|---|---|
| A. Twin labels | For each label drawn over art, a sibling label created **before** it (so it draws below) in black, `text_opa` 204 (0.8), offset (0, +1), same font, tracking, alignment and text | LVGL heap about 250–300 B per twin (object, local styles, text copy; est.). CPU: one extra glyph pass per twin. | Feasible. It's a **hard** 1 px drop with no 3 px blur, so it's a deviation. |
| B. A, limited to labels above y ≈ 125 | Twins for heading, homeTitle, homeArtist, volumeCaption, digits, percent, listTitle, listSub, tracksTitle, tracksSub, seekCaption and seekTime: **12 twins** | about **3.0–3.6 KB** of LVGL heap | **Recommended.** Below y 126 the scrim is ≥ 0.81 black × 0.8 art (≤ 15 % of the cover shows), so a shadow isn't visible. Windows has no art, so it needs no twins. |
| C. Host bakes the shadow into the cover | – | a new 20–30 KB JPEG and a 46–149 ms decode per text change | Rejected |
| D. None | rely on the darker scrim (2.7), which already fixes "unreadable on light covers" (S01:107) | 0 | Fallback, if B costs too much frame time |

**Implementation notes for B:**
- `makeLabel` (FD:672–696) creates the twin.
- `applyText`, `applyTracking` and `setVisible` mirror to it (FD:494–519, 484–490).
- The Home digit and percent reposition (FD:811–820) moves both twins.
- Layer-level tweens (track, volume, content) carry the twins automatically, because they're children of the same layer. No label-level tween touches a label in list B: `statusOpa` targets `status.obj` (FD:1236), which isn't in the list.

**Measure first:** there is no LCD render-time diagnostic today (LT:414–439 samples only heap and stack). Add `lcdRenderUsMax` before judging B.
- For reference, a full 240 × 240 flush is about 12 ms (LT:357).
- Slides redraw the content area at the 33 ms refresh period (LV:64).

### 2.9 Screen-change rules (summary of the edits)

| Rule | Today | Master | Edit |
|---|---|---|---|
| What moves | content, footer included (FD:1223, 1267) | text layer only (BS:209, 251) | footer out of content (2.1) |
| What fades | stage: art, content and footer (FD:1268) | text layer only, opacity 220 ms OUT (BS:649) | `contentOpa` replaces `stageOpa` |
| Distance | 20 px (FD:87) | 16 in BS, 20 in the spec | decision |
| When | a (group, page) change (FD:1263–1266) | every "flip" in A01 §4.1, including the explorer tab switch | new layouts plus depths (2.3) |
| Seek on/off | – | no slide | seek in `GROUP_TRACKS` |

### 2.10 Footer tones and inks

- **Today:** tones are derived from `(slot, icon, enabled)` (FP:163–174):
  - `none` (hidden), `dim` #4A4A4A, `stop` #FF8474, `go` #6ED996, `nav` #E6E6E6 (FP:94–100);
  - the idle row uses the same inks (FD:829–834);
  - ink changes are instant (`showIcon`, FD:713–728).
- **Master tones** (BS:938, 981; A01 §1.4):

| Tone | Footer ink | LED | Used by |
|---|---|---|---|
| `on` | #FFFFFF | WARM 1.0 | explorer tab (active), Shuffle on, Seek while seeking |
| `off` | #7A7A7A | WARM 0.30 (resting 0.04) | explorer tab (inactive), Shuffle off |
| colour `c` | `rgb(c)`: **#FF285A** for the liked heart; the app colour for an assigned snap side (raw in BS:981) | `c` at 1.0 (pink never goes through `sat()`, A02 §2.1) | Like, Snap |
| `dim` | **#5A5A5A** (BS) against #4A4A4A (S03:51, FP:96) | WARM 0.14 | disabled |

- **Firmware:**
  - `CCButtonTone` gains `CC_TONE_ON` and `CC_TONE_OFF` (FP:26). Append them, keeping the existing values.
  - `CCFooterInk` gains `on = 0xFFFFFF` and `off = 0x7A7A7A`, and `dim` follows the decision (FP:94–100).
  - `cc_button_tone` checks `lit` after `!enabled` (FP:163–174). The idle row and the footer then call a new `cc_button_ink(frame, slot)` that returns `rgb(color)` for `lit:on` with a colour, `#FF285A` for `lit:on` + heart, and otherwise `cc_footer_ink(tone)`.
  - `kTones` (FPA:29–30) gains `on` and `off` for diagnostics.
  - The v4 press highlight `pressable()` (FL:208–210) should include ON and OFF.
- **Colour transition:** BS animates the footer colour over 240 ms `ease` (BS:253). The firmware changes it instantly.
  - It's optional: a custom `lv_anim` exec interpolating `image_recolor`, for 8 icon objects, about 40 lines.
- **Risk:** raw app colours as footer ink can be illegible on black. Navy or dark-green icons fall below 3:1 against #000. Consider `sat()` for the LCD ink too, to match the LED.

---

## 3. Icon vocabulary

### 3.1 How icons work today
- **Generator** GI (Node + sharp):
  - It reads the `I` table of the **old** handoff, `design_handoff_nano_d_artwork_color/knob-model.js` (GI:23–25). Its icon paths are byte-identical to the master's `prototypes/knob-model.js`, but **not** to BS's `I` (BS:395–404).
  - It renders each path **stroked only** (`fill="none"`, GI:53–55, 112), at 16 / 20 / 26 px with strokes 2.4 / 2.3 / 2.1 (GI:26–27).
  - It writes A8 `lv_image_dsc_t` arrays plus a linear `strcmp` lookup `cc_icon(name, size)` into `src/cc_icons.cpp/.h` (GI:103–126; FI:108–159). It also writes PNG/SVG copies for the desktop.
  - The `--png-only` mode (@2x/@3x for the floating knob) has a **fidelity gate**: it requires the 1x render to equal the shipped masks (GI:64–73). So the full export must run first.
- **Shipped masks:** 16 icons × 3 sizes (back, cancel, home, list, win, tracks, play, pause, prev, next, more, switch, ok, dot, warn, usb). That's **21,312 B** of mask data (ELF, 48 symbols) plus descriptors and the lookup code.
  - `ok`, `warn` and `usb` are never referenced by the firmware (FD only uses `ICON_NAMES`, FD:102–103, plus `prev` / `dot` / `next`, FD:856). They are dead flash: 3,996 B.
- **Wire tokens:** `"" play pause list win tracks back home more prev next switch cancel` (FP:20–24; FPA:24–27; FD:102–103; PR:63–64; P4:86). The host's label → token map is at CT:38–41.

### 3.2 Naming trap
BS's `I` keys are **glyph names**, and several collide with wire tokens that mean something else (A01:146):

| BS key | Glyph | The wire token with that name means |
|---|---|---|
| `next` | **list-plus** (Play next) | Next / Skip (skip-forward) |
| `tracks` | **skip-forward** | the Tracks mode |
| `list` | list (dots + lines) = the **Tracks** icon | **Browse** in v4 (CT:38 `"Browse": "list"`) |
| `queue` | list-music (Favourite playlists) | – |
| `check` | check (Switch) | – (identical geometry to the unused `ok` mask: `M20 6L9 17l-5-5` against `M20 6 9 17l-5-5`) |

**Recommendation.** Keep wire tokens as **meanings**, as v4 already does ("Presentation roles follow available actions", FP:157). Map meanings to master glyphs. This avoids reusing BS names on the wire, and it keeps a v6 host working with cc5.4:
- v6's Home still sends `list` for Browse and `tracks` for Tracks;
- both show the master glyphs for their meanings.

### 3.3 Token table for cc5.4 (`presentation: 5`)

| Wire token | Meaning | Master glyph (BS key) | Path (24 grid) | Sizes needed | Status |
|---|---|---|---|---|---|
| `""` | none | – | – | – | unchanged |
| `play` | Play | `play` | `M7 4.5v15l12-7.5z` | 20, 26 | **path changed** (was `M7 4l13 8-13 8z`) |
| `pause` | Pause | `pause` | `M8 5v14M16 5v14` | 20, 26 | same path |
| `back` | Back | `back` (chevron-left) | `M15 18l-6-6 6-6` | 20 | **changed** (was an arrow `M19 12H5M12 19l-7-7 7-7`) |
| `list` | **Browse music** | `note` | `M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z` | 20, 26 | **glyph changed** (was the list glyph) |
| `tracks` | **Tracks** | `list` | `M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01` | 20, 26 | **glyph changed** (was double arrows) |
| `win` | Windows | `win` | `M3 5h18v14H3zM3 9h18` | 20, 26 | **changed** (was two windows) |
| `prev` | Previous / skip back | `prev` | `M19 5v14l-9-7zM6 5v14` | 20, **16** | **changed** |
| `next` | Next / Skip | `tracks` | `M5 5v14l9-7zM18 5v14` | 20, **16** | **changed** |
| `switch` | Switch | `check` | `M20 6L9 17l-5-5` | 20 | **glyph changed** (was arrows) |
| `expand` | Open on screen | `expand` | `M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7` | 20 | **new** |
| `clock` | Recently Added (tab) | `clock` | `M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0` | 20 | **new** |
| `playlists` | Favourite playlists (tab) | `queue` | `M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3` | 20 | **new** |
| `playnext` | Play next | `next` | `M11 12H3M16 6H3M16 18H3M18 9v6M21 12h-6` | 20 | **new** |
| `seek` | Seek | `seek` | `M3 12h9.5M18.5 12H21M15.5 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z` (handle at x 15.5, about 65 %; the path is authoritative over R:95's "≈ 60 %") | 20 | **new** |
| `shuffle` | Shuffle | `shuffle` | BS:401 (5 subpaths) | 20 | **new** |
| `heart` | Like | `heart` | `M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z` (stroked; liked = pink ink, not filled) | 20 | **new** |
| `snapleft` | Snap left | `rect` + `HALF.left` | stroke `M3 5h18v14H3z` + **fill** `M3 5h9v14H3z` | 20 | **new; needs a filled path** |
| `snapright` | Snap right | `rect` + `HALF.right` | stroke `M3 5h18v14H3z` + **fill** `M12 5h9v14h-9z` | 20 | **new; needs a filled path** |
| `home` | Home (legacy, v6 hosts) | old `home` | unchanged | 20 | keep for v6 only |
| `more` | More (legacy / paging, A01 open question 1) | old `more` | unchanged | 20 | keep while paging may survive |
| `cancel` | Cancel (legacy, v6 hosts) | old `cancel` | unchanged | 20 | keep for v6 only |
| *(internal)* `dotfill` | Tracks position centre | – | filled circle, 6 px across at 16 px (r 4.5 on the 24 grid) | 16 | **new**, not a wire token |

- The **go rule** `slot == 3 && icon ∈ {play, prev, next, switch}` (FP:171–172; PR:163) stays correct: Play, Skip Prev/Next and Switch are the only green buttons.
  - The Home slot 4 `win` stays `nav`. Seek, Play next and the pairs are never green.
- **Sizes by use:**
  - 20 px for every footer token;
  - 26 px only for tokens that can appear in the **Home idle row** (FD:829–833, `IDLE_ICON 26`): play, pause, list, tracks, win;
  - 16 px only for the position row: prev, next, dotfill.
  - A token without a mask at a size makes `cc_icon()` return nullptr, and `showIcon` **hides** the glyph (FD:715, 727). A missing 26 px Home icon would silently leave a gap in the idle row.

### 3.4 Generator and code changes
1. **GI:23–25.** Read the master `I` and `HALF` from `Browse and Snap.dc.html` (BS:395–405), not the old `knob-model.js`. Keep an explicit **token → (stroke paths, fill paths)** table, because the names differ (3.2).
2. **GI:53–55, 112.** Support one optional filled path per icon: `<path d=… fill="white" stroke="none"/>`. Only the snap halves use it. BS always draws the half filled (BS:974, `f.fill`), so a static mask per side is exact.
3. **GI:26.** Stroke at 16 px becomes **2.3** (BS:231–233). It's 2.4 today, a Knob Face value. 20 px stays 2.3 and 26 px stays 2.1 (KF:42; the master is silent).
4. **Per-size emission.** Emit only the sizes in 3.3, or keep all three sizes for simplicity (the flash trade-off is in 9.1).
5. **Regenerate** `assets/handoff-icons` and the floating knob's @2x/@3x `lcd-icons` (FLOATING_KNOB §2), after the 1x export (the GI:64–73 gate).
6. **Enums and tables** in lock-step:
   - `CCIcon` (FP:20–24): append only, and never renumber;
   - `kIcons` (FPA:24–27);
   - `ICON_NAMES` (FD:102–103);
   - `cc_legacy_icon` (FP:134–148), unchanged;
   - `presentation.ICONS` (PR:63–64);
   - `device._buttons` (DV:228), which uses `PR.ICONS`;
   - `controller.BUTTON_ICONS` (CT:38–41);
   - `lcd_preview.py` (the desktop LCD mirror).
7. **Flash hygiene:** drop the `ok`, `warn`, `usb` and old `dot` masks from the firmware lookup (3,996 B), unless a native screen needs them. None does today (grep of `src/`).

---

## 4. Fonts and glyphs

### 4.1 The `:` in the 48 px font
- `cc_font_48` has 12 glyphs: `%`, `-` and `0–9` (FN:12; F48:386–397). It has **no fallback**, because `LV_FONT_MONTSERRAT_48 0` (LV:386; F48:451–455).
- A `:` in a `cc_font_48` label therefore renders **nothing**. It's a missing glyph, not a box.
- Add U+003A to `DIGIT_SET` (GF:115). The cost is about 8 × 26 px at 4 bpp, so about 104 B of bitmap plus an 8 B descriptor, and one more cmap range.
- The design's asset note already names this font: "Montserrat 48, digits and % only" (S03:54).

### 4.2 Tabular digits at 48 px
- **Why:** see 2.2. Proportional advances at 48 px run from **17.75 px** (`1`, `adv_w` 284/16) to **32.1 px** (`4`, 514/16) (F48:388–397).
- **Montserrat does have tabular figures** (`tnum` → `zero.tf` … `nine.tf`, advance 700/1000 = **33.6 px** at 48 px). But they are **different outlines**, not re-spaced copies: `one.tf` has 13 points against 7 for `one`, and `2`, `5`, `6` and `9` also differ in point count.
- **The generator can't reach them:** it uses Pillow `Layout.BASIC` with no OpenType features (GF:263), and Pillow's raqm is unavailable here.
- **Options:**

| Option | How | Flash | Fidelity |
|---|---|---|---|
| T1 (recommended) | GF builds an in-memory copy of the variable font whose cmap maps U+0030–0039 to the `.tf` glyphs (fontTools; saved to `BytesIO`, which Pillow `truetype()` accepts), then renders a second font `cc_font_48t` with `0–9` and `:` | about 11 glyphs × ~0.45 KB ≈ **+5 KB** | exact `tnum` |
| T2 | The same bitmaps as `cc_font_48`, with a second glyph descriptor table: `adv_w` fixed at 538 (33.6 px × 16) and `ofs_x` adjusted to centre each glyph | about +0.2 KB | fixed-width cells, but the default `1` looks spaced out (a deviation) |
| T3 | One label per digit cell | – | more LVGL objects and code |

- **Keep the volume digits proportional:** BS:217 has no `tabular-nums` on the volume value, and changing them would alter the shipped look. So `cc_font_48` stays for volume, and `cc_font_48t` serves Seek. `font_tests.py` and `gen_lvgl_font.py --check` need the new font.

### 4.3 Tabular digits at 14 px (`of m:ss`)
- ASCII in `cc_font_14` resolves to LVGL's built-in `lv_font_montserrat_14`, which is proportional (FN comment; GF:12–20).
- The duration line is **constant for the whole Seek session**, so proportional digits cause no jitter. **No change** is needed; record it as a deviation from BS:242.

### 4.4 Other glyphs
- Every new string is Latin plus `·` (U+00B7), which is inside the shipped Latin-1 range (GF:108–112). `…` and `–` are also in `cc_font_12/14/16/22` (FN).
- No other glyph work is needed. Idle-row words come from the host button labels (FD:833).

---

## 5. Frame and wire fields

### 5.1 What the parser and CCFrame must add
The parser is FPA:116–291 and the frame is FP:41–73. The host validator must match: DV `_buttons` 214–248, `_ring` 251–312, `_optional` 315–346, `_slim` 349–370.

| Field | Type / range | For | Firmware (parse → store → use) | Notes |
|---|---|---|---|---|
| `layout` + `"seek"`, `"explorer"`, `"upnext"` | token | 2.2, 2.3 | `CCLayout` append (FP:11–14); `kLayouts` (FPA:14–16); FD clamp (FD:1252); `groupOf` / `depthOf` (FD:772–789); `cc_alive_family` (FA:246–253) | `restLayout` unchanged |
| `page` (existing) | 0..255 | explorer tab 0/1 | existing (FPA:267–271) | the depth becomes 30 + page |
| `ring.style` + `"lap"` | token | Seek lap | `CCRingStyle` append (FP:18); `kRingStyles` (FPA:22–23). Validation: `count ≥ 1`, `index < count` (extend FPA:144). `value` stays required and is sent as 0 (FPA:141). | `index` = target seconds, `count` = duration seconds, both ≤ 65,535 (18.2 h) |
| `ring.now` | int −1..count−1 | Up next played / now / upcoming (A02 F14) | new `int16_t ringNow = -1` | absolute index; classes are computed inside the 20-entry window |
| `buttons[j].lit` | `"on"` \| `"off"` | pairs, Shuffle, Seek lit, heart, snap | new `uint8_t lit` in `CCButton` (FP:31–39); parsed in FPA:120–133 | `enabled:false` still wins (dim) |
| `buttons[j].color` (existing) | 0..0xFFFFFF | snap side colour | already parsed (FPA:131) but "never used for LEDs" (FP:38); **used now** when `lit:"on"`. The host must stop stripping it (DV:362–363) for a `presentation ≥ 5` knob. | pink is implied by the heart icon, never sent as a colour (A02 §8) |
| `feedback.moment` | `"queued"` \| `"shuffle"` \| `"like"` \| `"unlike"` \| `"snap"` | LED moments (8) | parsed next to `kind` / `seq` (FPA:276–281); valid only with `kind:"ok"`, otherwise stripped (like ALIVE's `skip`, AL:79) | – |
| `feedback.side` | −1 \| 1 | half-wash side | with `moment:"snap"` | – |
| `feedback.color` | 0..0xFFFFFF | half-wash colour; 0 = WARM | with `moment:"snap"` | explicit, because the picker has already moved on 420 ms later (BS:855) |
| ALIVE fields (AL:74–81) | `clock`, `playing`, `progress{pos,dur}`, `feedback.skip`, `ledDrive`, `ledDither` | ALIVE | not in CCFrame yet: `CCAliveFrameExtra` carries only `playing` and `skip` (FAH:292–297) | same release |
| `iconKey`, `artKey` | existing | – | unchanged (FPA:249, 266) | – |

- **Text fields: no change.** Every master string fits the existing capacities (FP:43–48). The longest meta, `Right: {App} · pick left`, is well under 96 B, and headings are ≤ 19 B of the 32 B limit. The mirror, meta and Tracks copy is all host text: `Queued next`, ` · playing`, ` · shuffle`, `Press 4 to skip`, `Now: …`, `Left: … · pick right`, `End of queue`, `of m:ss` if sent as text.
- **CCFrame growth:** about +24 B (4 × `lit`, `ringNow`, `moment`, `side`, `mcolor`, plus ALIVE's latched values) on a ~1,040 B struct (HM:45). It's copied about 6 times: CCP:41 `frame`, CCP:44 `incoming`, HM:38 `cc_hmi_frame`, LT:282 `frame`, FAH:362 `local_`, and the ALIVE latch. That's about 150 B of RAM in total.
- **Byte budget.** The ≤ 1,100 B worst-case Windows frame (P4:307; PR:74) gains:
  - two button colours and `lit` (about 60 B);
  - `feedback{moment:"snap", side, color}` (about 45 B);
  - `clock` (about 12 B) and `progress` (about 40 B).

  The host shrinks text to fit (DV:420–427), so the firmware is unaffected: its line capacity is 4,096 B (CM:44). But the **test** `test_worst_case_windows_frame_fits_the_budget` (`tests/test_cc_contract_v4.py:1018`) must be re-measured, and the budget raised or confirmed.

### 5.2 Capability
- Bump `c["presentation"] = 4` (CCP:110) to **5**, with an ICONS v5 table.
  - A v6 host treats `presentation ≥ 4` as v4 (DV:182, 200, 444 use `>=`), so it keeps working with cc5.4.
  - It never sends the new tokens or fields.
- Optionally, `c["keyHoldMs"] = 600` so the host knows the knob emits `kh` (6.1).
- ALIVE adds `alive: {version, fps, drive}` (AL:21–30).

---

## 6. Buttons

### 6.1 Hold 600 ms = Home (R:67; S01:44). A firmware event is needed.

**Current plumbing:**
- **AceButton 1.10.1.** Each raw button has its own `ButtonConfig` (HM:251–254). Only `setClickDelay(50)` is set and `kFeatureDoubleClick` is cleared (HM:258–259).
  - `mFeatureFlags` defaults to 0 (AB:431), so **long press is off**. The long-press delay defaults to 1000 ms (AB:92, 436), and debounce to **20 ms** (AB:83, 433).
  - Events are `kEventPressed = 0`, `kEventReleased = 1`, `kEventLongPressed = 4` (`AceButton.h:57–97`).
- **Claimed path** (HM:334–349). Pressed and Released update `keyState`, and F24 is triggered on press. **Any other event type returns** (HM:344).
  - A `KeyEvt{type, index, keyState, cc_input_id()}` is queued (HM:345–346; `hmi_api.h:143–148`, queue depth 5, HM:110).
- **COM** (CM:314–333). It drops a claimed event whose `control_id` is 0 or differs from `cc_input_id()` (CM:321–322), and sends `{"id", "ks", "kd" | "ku"}` (CM:324–330).
- **`cc_input_id()`** is non-zero **only in phase 2 (ready) after the ready reply** (CCP:255).
- **The host** (DV:834–852) consumes messages only when `id == ready_id`. It emits `button` **only on `kd`**; `ku` just clears `_pressed`. It sets `_pressed = 0` on `ready` (DV:831), and the `ready` reply carries no `ks` (CCP:319).

**Latency** from contact to host:
- debounce 20 ms, plus the HMI pass ≤ 10 ms (`vTaskDelay(10)`, HM:322);
- plus the COM pass of 1 or 10 ticks (CM:196–202);
- plus USB CDC.

That's about **25–45 ms** for `kd` and `ku` alike. A host-measured `kd → ku` interval is accurate to about ±20 ms, which is fine against 600 ms.

**Why host-only timing is not enough.** Button 1 acts on the **down** edge (A01 §4.4). Everywhere except Home, Back changes the mode, and the host immediately sends a **new `control`**, a re-entry with a new id. From then until the knob is ready (phase 1, "entering", CCP:220):
- `cc_input_id()` is 0, and every key event is tagged 0 and **dropped** (CM:321–322).
- Entering waits for the motor, HMI and LCD acknowledgements (CCP:276–285). The LCD one includes a render with `lv_refr_now` (LT:316–346), plus a **46–149 ms JPEG decode** when the target screen has a new cover (D53).
- A normal tap lasts 80–150 ms. **Its `ku` often falls inside this window and is lost.** After `ready`, no key event arrives until the next edge. So a host timer started on `kd` can't tell "still held" from "released while entering", and it fires a **false Home** after a quick tap on Back.

**Firmware change (recommended):**
1. **HM:255–260.** `setFeature(kFeatureLongPress)` and `setLongPressDelay(600)` on the four configs. Do **not** set `kFeatureSuppressAfterLongPress`, so `kEventReleased` still follows and `keyState` stays correct.
2. **HM:336–344, claimed branch.** Handle `kEventLongPressed`: queue a `KeyEvt` with `type = 4`.
   - The native branch (HM:350–374) must **ignore** type 4. Today its tail sends a `KeyEvt` for every event type (HM:369–370), which would emit a bare `{"ks":…}` line in native mode and reset `isIdle` (HM:371–373). Alternatively, enable the feature only while claimed, at the claim transition HM:273–286.
3. **CM:326–329.** `else if (keyEvt.type == 4) eventDoc["kh"] = keyEvt.keyNum;`
   - AceButton polls at the 10 ms HMI pass, so the event fires 600–610 ms after the debounced press: **about 620–640 ms after contact**. By then the Back re-entry has normally completed (≤ ~200 ms), so the event carries the new ready id and passes CM:321.
4. **Belt and braces:** add `"ks"` to the `ready` reply (CCP:319). The host then knows at ready whether a button is still down.
   - `keyState` is a protected `HmiThread` member (HMH:57, 104); `ComThread` is a friend (HMH:34) and `control_center.cpp` is not, so add an accessor.
5. **Host** (DV:843–852): emit a `hold` event on `kh` with `id == ready_id`. The controller treats logical button 0's hold as **Home** from any mode. It's a no-op on Home, and from Windows it also restores focus (A01 row 34).
   - A v6 host ignores `kh`: it reads only `p`, `ks`, `ku` and `kd` (DV:836–852; AL:29).

**Cost:** about 20 lines of firmware, no RAM, and 1 more queue message per hold.
**Risk:** AceButton long press also fires for buttons 2–4. The host ignores those holds, and the firmware may restrict `kh` to the raw index of physical slot 0, via `cc_physical_button` (CCP:289–293).

### 6.2 Windows only from Home (F24)
- **Today:**
  - `cc_is_windows_button(i)` is true when ready, HID is enabled, `i == windowsButton` and **the button is enabled** (CCP:294–299). Then F24 is pressed for 60 ms (HM:338–342, 293–295).
  - The host sets `windowsButton` from `button_order[2]` (RT:1356; CT:139, 315) and skips the serial edge of logical 2 (RT:1385–1389).
- **Master:** Windows is **slot 4, Home only**. In every other mode slot 4 is Play, Skip or Switch, so an unchanged firmware would fire F24 and reopen the picker on every Play.
- **Change:**
  - **Host:** `windowsButton = button_order[3]`, and `windowsHidEnabled = (mode == home)` per control. That field already exists per control (CCP:189–192, 218; DV:939–941).
  - **Host:** RT:1387 becomes `logical == 3 and mode == home`.
  - **Firmware, defensive, one line** (CCP:297): add `&& cc_button_icon(frame.buttons[physical]) == CC_ICON_WIN`.

---

## 7. Haptics: Seek on BINARIS BEER

- **The profile exists and is valid.** INV lists `BINARIS BEER` among 10 installed profiles. `knob[0].haptic`: `mode 0` (REGULAR), `detentCount 67`, `kxForce false`, `outputRamp 10000`, native `startPos 0` / `endPos 127`.
  - This passes the control command's checks (CCP:203–212): the name resolves, `knob.num > 0`, REGULAR, `!kxForce`, `detent_count > 0`, and `output_ramp` finite.
  - Home volume already uses it (CT:36–37).
  - For reference, MIDI SKIPPER is 20 detents (`outputRamp 0`) and MIDI CLACK JONES is 8 (`endPos 8`).
- **The swap needs no new firmware.** Seek is a new `control` with `profile:"BINARIS BEER"`, `min 0` (it must be 0, CCP:205), `max ≤ 65535` and `position ∈ [0, max]` (CCP:205–206; DV:945–948).
  - The firmware sets `start_pos = 0` and `end_pos = max` (CCP:213). The FOC thread calls `rebase_runtime(profile, position)` (FT:89–93; HP:114–122), which puts the new detent grid's origin at the **current shaft angle**. There is no jump.
  - The detent width is `2π/67` = 5.37° whatever the bounds (HP:67–68). **5 s per detent** is therefore purely the host's bounds mapping.
- **Bounds mapping** (A01 §2; CS §4.2), with D the duration and p the position at entry, in seconds:
  - `T_end = D − 1` (BS:712) or `D − 3` (CS, the safer choice);
  - `n0 = ceil(p/5)`;
  - `max = n0 + ceil((T_end − p)/5)`;
  - enter with `position = n0`;
  - detent n → `t = clamp(p + 5·(n − n0), 0, T_end)`.
  - Positions 0 and `max` are exactly 0:00 and `T_end`, so the haptic end stop (`atLimit`, HP:249–327), ALIVE's `limit` (AL:214–219) and the End stop moment fire exactly at the ends (S01:166).
  - Example: D = 210 s, p = 74 s, `T_end` = 207 → n0 = 15, max = 42.
  - One revolution is 67 × 5 = 335 s. A 3:30 song is about 0.63 turn; a 60 min mix is about 10.7 turns.
- **Side effects to accept (existing behaviour):**
  - Entering and leaving Seek is a re-entry. During phase 1 the motor runs `move(0)` with no detent torque (FT:105), and motion during entering is rebased away at ready (FT:98–104).
  - That's the same for every mode change today. At Seek entry the user's hand is on button 3, so it's harmless.
- **LEDs and LCD during Seek:**
  - ALIVE's local cursor has no `lap` rule (AL:229–233; A02 D29). The lap head and the `m:ss` update from host frames, one serial round trip (about 20–40 ms) per detent.
  - `device.py` coalesces frames (a newer frame replaces one still waiting, DV:977–979), so fast spins at 67 detents per turn don't queue.
  - A knob-local mapping (sending `p`, `n0`, `step`, `D`) is possible, but it isn't recommended for this release.

---

## 8. LED engine additions (from A02) mapped to firmware

The ALIVE engine exists as platform-neutral code (FA, FAH) but is **not yet wired into the HMI task**. `HmiThread::updateLeds()` still runs the v4 `CCLightRenderer` (HM:597–627) with the `min(51, …)` brightness cap (HM:625). Every item below lands in FA/FAH, and in its Python twin `alive_lights.py`.

| Addition (A02 ref) | Firmware place | Change |
|---|---|---|
| Effect types `half` (900 ms, FG) and `scatter` (700 ms, FG) (A02 §6.1, §6.3) | `CCAliveEffectType` (FAH:121–124); `durations[15]`, `foreground[15]` (FAH:70–73); `draw()` switch (FA:539–690) | Append `CC_FX_HALF` and `CC_FX_SCATTER`. The arrays grow to 17 entries. Port the recipes verbatim from BS:541 and BS:543, including half's `addB(…, 0.6·fade)` **without `amp`** (A02 F18). |
| `bloom` with a colour; PINK 255,40,90 and its spark `mix(PINK, white, 0.3)` (A02 §6.2) | `CC_FX_BLOOM` case (FA:626–638); `CCAliveSpec` palette (FAH:33–40); `CCAlivePalette` (FAH:155–157) | The effect's `c[3]` defaults to GREEN. Add a `pink` palette constant; it never goes through `sat()`. PINK needs a hands-on value check (A02 §2.1). |
| Effect parameters `side` and `seed` | `CCAliveEffect` (FAH:161–174) | Add `int8_t side` and `float seed`. The struct grows about 8 B × 8 queue slots. |
| Deterministic scatter seed (A02 F17) | `CCAlive` state (FAH:345–391) | xorshift32, seeded in `reset()`, one draw per scatter, mapped to `1 + 9u`. Optionally reject seeds with a minimum spacing < 3 segments. |
| Moments on `feedback.moment` (A02 §9, §6.4) | `feedback()` (FA:1017–1030); event dispatch (FA:1176–1194) | Order: `skip` → sweep; `queued` → sweep with `at = 0`, `dir = +1`; `shuffle` → scatter; `like` → PINK bloom at the cursor; `unlike` → nothing; `snap` → half with `side` and `sat(color)`; then D7 wash (extended to explorer, and to upnext if F12 is accepted); else green bloom. **No target flash** with a moment (A02 F13): `flash_` is set in FA:1024. |
| Families `explorer` and `upnext` (A02 F15), and Seek (A02 F19) | `CCAliveFamily` (FAH:117–119); `cc_alive_family` (FA:246–253); tint (FA:407–413); MODE (FA:1177) | Tint for recent, explorer, upnext and windows. Reveal on a family change. For Seek, either a separate family or "a ring style change transport ↔ lap" counts as MODE. |
| Seek lap ring (A02 §4.5) | v4 geometry `cc_ring_target` (FL:252–258) | New `draw_lap`: segment k < n at L2 (46 → class 2 = 0.62 warm); unplayed k with `k mod 5 = 0` at L1 (0.30); head n at L3 (1.0), which is the cursor. `n = min(59, index·60 / count)` in integers. It maps onto the **existing** classes (FA:237–244), so no new alpha is needed. |
| Up next levels: played 0.14, now 0.70, upcoming 0.45 in any role, cursor 1.0 (A02 §4.6) | `cc_alive_targets` after the class loop (FA:353–370); alpha tables (FAH:44–46) | New classes P (0.14 / resting 0.05) and N (0.70 / resting 0.10), applied by a post-pass on absolute indices with `ring.now`. The threshold mapping (FA:237–244) can't produce them. |
| Buttons on / off / colour / pink (A02 §3.1, F16) | buttons (FA:384–405); `CCAliveSpec` button alphas (FAH:52–53) | `lit:on` → WARM 1.0; `lit:off` → WARM 0.30; heart + on → PINK 1.0; colour + on → `sat(color)` 1.0. Resting is 0.12 when the awake alpha ≥ 0.5, else 0.04 (replacing "0.04 if dim"). |
| Volume body in amber/red at 0.62, and S at 0.81 in every role (A02 F1, F3) | `alphaAwakeSemantic` (FAH:45) | `{0, 0.45, 0.62, 0.81, 1, 1}`. Hands-on check. |
| Volume colour gated on value and position (A02 F2) | `volume_color(k, colored)` (FL:67–70), called at FL:85–91 | RED if `v ≥ 90 && k ≥ 45`; AMBER if `v ≥ 80 && k ≥ 40`. Use the confirmed volume for the pending span. |
| Coloured-list rule: More is a single warm item; the unavailable and pending cursors take the accent (A02 F5–F7) | `draw_list` (FL:154–169), or an ALIVE post-pass | Only needed if More or paging survives (A01 open question 1). |
| Paused Play green or warm (A02 F4) | FA:388–392; FAH:87 | Ruling pending; A keeps green. |
| `lim` event also serves the Seek ends | AL:88–91, 214–219 | none beyond ALIVE |

- **Integration (ALIVE work, same release):** HM:597–654 runs the engine at 16 ms, with `FastLED.setBrightness(255)` and drive plus power limit (AL:349–363, 367–386). The press input comes from HM:336 and the limit from `pass_at_limit()` (FT:172–174).
- **ALIVE's own scope line** "Not touched: … LCD rendering" (AL:386) is **overtaken** by this combined release, which touches FD heavily. Update AL:1–17 and AL:386 so the release notes don't contradict each other.
- A02 §2.3 side finding (not a master item): ALIVE's WARM 255,189,105 comes out as #FF8224 through the sRGB EOTF, not the user's #FF8424 (FAH:35). It belongs in ALIVE's D3 fix list.

---

## 9. Flash and RAM impact

### 9.1 Flash (app slot `app0`/`app1` = 0x140000 = 1,310,720 B, `boards/nano_partitions.csv`)
- **cc5.3 today** (B53): **1,023,648 B**, which is 78.1 % of the slot. Headroom is **287,072 B**.
  - The 2026-09-24 local build (ELF, 1,023,760 B) has **no ALIVE symbols** (`nm` finds no `alive`), so the engine is not linked yet.
- **ELF sections:** `.flash.text` 554,903 B and `.flash.rodata` 331,272 B.
  - Icon masks: 21,312 B.
  - `cc_font_48` bitmap: 5,151 B (`glyph_bitmap` 0x141F).
  - `cc_display_render`: 3,266 B.
  - `cc_parse_frame`: 2,684 B.

| Item | Estimate (flash) |
|---|---|
| ALIVE engine as it stands (FA, 1,240 lines, float32, EOTF LUT and tables) | +14 to +22 KB (est.) |
| ALIVE master additions (half, scatter, PRNG, pink bloom, lap, P/N classes, moments, button states) | +2 to +4 KB |
| Parser and CCFrame fields (ALIVE and master), tokens and validation | +1.5 to +3 KB |
| FD: seek layer, new layouts and depths, footer and content re-parenting, Windows art fade, tone and ink logic | +2 to +4 KB |
| FD: shadow twins, option B (code only) | +0.5 to +1 KB |
| Icons, **trimmed**: 21 × 20 px + 5 × 26 px + 3 × 16 px = 8,400 + 3,380 + 768 = **12,548 B** | **−8.8 KB** against 21,312 B |
| Icons, **all 3 sizes**, 22 names: 22 × 1,332 = 29,304 B | +8.0 KB (alternative) |
| `cc_font_48` plus `:` | +0.1 KB |
| `cc_font_48t` (T1, 11 tabular glyphs) or T2 (descriptor only) | +5 KB or +0.2 KB |
| HM hold event, F24 guard, ALIVE HMI integration, `lim` / `kh` in COM | +1 to +3 KB |
| **Total** | **about +25 KB (trimmed icons, T2) to +55 KB (all sizes, T1)** → 1.05–1.08 MB, **80–82 % of the slot**, with ≥ 230 KB of headroom |

**Verdict:** there's no flash risk. Record the real size in `cc5.4-build.json` (`headroomBytes`) as B53 does.

### 9.2 RAM
The sources are D53 and B53:
- internal: `ramUsedBytes` 245,056 of 327,680 (B53); `heapFree` 65,744; `heapMinFree` **57,072**;
- LVGL heap 64 KB (LV:45; `work_mem_int` 0x10000 in `.bss`): `lvglFree` about 37,780, `lvglMinFree` **36,584**;
- `stackLcd` 6,644 free of 12,288 (LT:30); `stackHmi` 8,100 free of 9,216 (HM:24);
- `psramFree` 685,411.

| Item | Where | Estimate |
|---|---|---|
| `CCAlive` static instance | internal `.bss` | **about 8.1 KB**. From FAH:230–391: animator about 3.96 KB (`cur_` 960, `fx_` 8 × 44, `snap_` 1,440, `o_` 720, `m_` 240, and so on), targets about 0.8 KB, `cells_` 0.48 KB, `local_` CCFrame about 1.04 KB, `ringE_` + `buttonE_` 0.77 KB, dither 0.77 KB, input queues 0.16 KB. Confirm with `sizeof` at build. |
| Master additions in ALIVE | internal | about +0.1 KB (effect fields, PRNG) |
| CCFrame growth × about 6 copies | internal | about +0.15 KB |
| ALIVE latch struct (clock, progress, drive, dither) | internal | < 64 B |
| **Internal heap after cc5.4** | – | `heapMinFree` about 57.1 → **about 48–49 KB**. Acceptable, since TinyUSB, the queues and FreeRTOS already fit in the measured minimum. |
| Seek layer (1 box + 3 labels) | LVGL heap | about 0.8–1.0 KB |
| Shadow twins, option B (12) / A (about 24) | LVGL heap | about 3.0–3.6 KB / about 6–7 KB |
| **`lvglMinFree` after cc5.4** | – | about 36.6 → **about 32 KB (B)** / about 29 KB (A) |
| HMI stack | – | the engine state is static (AL:379). The budget stays > 1 KB (AL:379), with 8,100 B measured free. |
| PSRAM | – | unchanged: art buffers 2 × 115,200 B (LT:368–372), media store as in cc5.3 |

**Verdict:** the RAM is fine. The LVGL heap is the tightest pool, and text shadows option A would take 6–7 KB of it. Prefer B and measure `lvglMinFree` on the hardware.

---

## 10. Risks (ranked)

1. **A false "Home" on a quick Back tap if hold is timed only on the host** (6.1). The Back re-entry drops key events during "entering" (CCP:255; CM:321–322), and `ready` carries no `ks` (CCP:319). **Mitigation:** the firmware `kh` event, plus `ks` in `ready`.
2. **F24 on every Play, Skip or Switch** if the Windows button moves to slot 4 without gating (CCP:294–299). **Mitigation:** the host `windowsHidEnabled` per control, plus the firmware icon guard.
3. **The icon generator reads the old design, strokes only, and BS names collide with wire tokens** (3.1, 3.2). **Mitigation:** an explicit token → path table and fill support. A missing 26 px mask hides the idle-row icon silently (FD:715, 727).
4. **The Seek `:` renders blank and the digits jitter** without the font work (4.1, 4.2). `LV_FONT_MONTSERRAT_48 0` means there's no fallback.
5. **`PLAYLISTS · SCREEN` is ellipsized** at the r 104 heading chord (118 px), and all three mirror labels lose their tracking (2.3). This needs a copy or tolerance decision, then a harness check.
6. **Up next cover churn:** 46–149 ms of synchronous JPEG decode per detent on playlist queues (2.3, D53). It can make the LCD lag during fast spins. Accept it as today's Recent behaviour, or have the host hold the art key while the knob moves quickly.
7. **Text shadow fidelity and cost** (2.8): no blur is possible, and each twin doubles glyph drawing. Measure the render time first; there's no LCD render-time diagnostic today.
8. **Slide direction bugs** if the mirrors reuse `recent`: Back from Up next would slide the wrong way (2.3). **Mitigation:** new layouts and depths.
9. **New layouts render as Home** if appended without updating the FD clamp (FD:1252) and `cc_alive_family` (FA:246–253), which both default to Home.
10. **Tight 22 px Tracks title:** `Turn to choose` is 166.7 px against a 168 px chord (2.4). Font rounding may add an ellipsis; check on the harness.
11. **Raw app colours as LCD ink** can be illegible (2.10); consider `sat()`.
12. **Contract drift:** the parser (FPA), the validator (DV), `lcd_preview.py` (the floating knob and mirror), `alive_lights.py`, and the fixtures (`frames_v4.json`, `parse_tests.py`, `cpp11_gate.py`, MSVC `/W4 /WX`, P4:336) must all change together. The floating knob runs the same choreography [user].
13. **Byte budget test** (5.1): the Windows worst case grows by about 150 B. The host shrinks text to fit, but the budget test must be updated deliberately.
14. **The ALIVE document contradicts the combined release** ("LCD rendering not touched", AL:386). Update it before the release notes are written.
15. **Hold on buttons 2–4** also fires with long press enabled on every config. The host must ignore it, or the firmware must restrict `kh` to physical slot 0.

---

## 11. Work order and verification

1. **Contract first.** Write a `PRESENTATION_V5.md` (or amend P4) covering: tokens (3.3), layouts, depths, the lap and `now` ring fields, `lit`, moments, `kh`, capability 5, and the ALIVE fields. Build the shared fixtures, then the FPA and DV parity tests.
2. **Assets.** GI rewrite and export (masks, PNG, @2x/@3x); GF with `:` and `cc_font_48t`; `font_tests.py`.
3. **FD.** Re-parent the tree, add the seek layer, the new layouts and depths, the tones and inks, the Windows art fade, and the twins behind a compile-time flag. Harness renders go through `cc5_report.py` (chords, corner ink, heartbeat inertness through `CCDisplayStats`, FDH:79–93).
4. **HM, CM and CCP.** The long press, `kh`, `ks` in `ready`, and the F24 icon guard.
5. **FA, FAH and FL.** Section 8. Oracle cases from BS `draw()` (half left and right, including the kill; pink and green bloom; scatter with fixed seeds 1.0 / 5.0 / 8.2079 / 4.104; sweep at 0), and target goldens from BS `renderVals()` (A02 §9 §11).
6. **Desktop v7.** `lcd_preview.py` and `alive_lights.py` parity; `presentation.py` (ICONS, LAYOUTS, RING_STYLES, tones, `PRESENTATION_VERSION`); `device.py` (validation, `kh` → `hold`, keep button `color` for v5, the budget); `controller.py` (the map, profiles, Seek mapping, hold, F24).
7. **Size gates.** Firmware ≤ 0x140000, with the measured headroom recorded. `lvglMinFree` and `heapMinFree` come from `{"diag":"?"}` on the hardware, with the user's go-ahead (a hands-on flash is the user's call).

---

## 12. Decisions needed (firmware-relevant)

1. **Heading copy or tolerance** for `PLAYLISTS · SCREEN`, and the tracking of the three mirror labels (2.3).
2. **Text shadow:** option B (12 twins, a hard 1 px drop, no blur) or none (2.8).
3. **Tabular digits:** T1 (true `tnum` glyphs, +5 KB) or T2 (fixed cells, +0.2 KB) (4.2).
4. **Slide distance:** 16 px (BS) or 20 px (spec) (2.1).
5. **Footer dim ink:** #5A5A5A (BS) or #4A4A4A (S03, current) (2.10).
6. **Snap footer ink:** the raw app colour (BS) or `sat()` (2.10).
7. **Windows tile fallback:** the app colour with a white letter (BS; bold isn't available) or #444 (current) (2.5).
8. **Seek numbers:** from the ring (`index`/`count`, recommended) or host text (2.2).
9. **Icon sizes:** trimmed per use (−8.8 KB) or all sizes (+8 KB) (3.3, 9.1).
10. **Legacy tokens** `home`, `more` and `cancel`: keep them for v6 hosts and paging, or drop them after the combined release (3.3).
