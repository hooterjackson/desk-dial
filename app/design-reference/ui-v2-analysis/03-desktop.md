# 03 — Desktop companion: master design extraction (UI V2)

Analysis only (read-only pass, 2026-09-25). Subject: the **companion (desktop) side** of
`design_handoff_nano_d_master`, compared with desktop v6 as built. Target: the one combined
release (firmware 1.0.0-cc5.4 + desktop v7) that carries the "Warm · alive" LEDs (ALIVE.md) and
this whole master design.

## 0. Sources, precedence, conventions

**Design sources** (under `design-reference/design_handoff_nano_d_master/`), in the handoff's own
precedence (README §0): `README.md` (1) > `specs/01` (2) > `specs/02` (3) > `specs/03` (4) >
`specs/04` (5, with its framed glass pane and 480 × 300 cards **superseded**) > `specs/05` (6).
`icons/README.md` is byte-identical to `specs/05-APP-ICON.md` (checked with `diff`).

| Key | File |
|---|---|
| `README §n` | `README.md` |
| `01 §n`, `03`, `04`, `05` | `specs/01-FEATURES-explorers-snap-seek.md`, `specs/03-SCREEN-and-state.md`, `specs/04-WINDOW-carousel.md`, `specs/05-APP-ICON.md` |
| `B&S:Lnnn` | `prototypes/Browse and Snap.dc.html`, line nnn (**primary** prototype: behaviour, layout, motion, button map) |
| `CC:Lnnn` | `prototypes/Nano_D Control Center.dc.html` (section 04 = companion surfaces, L321–L783; data L1020–L1144) |
| `WC:Lnnn` | `prototypes/Window Carousel.dc.html` (card-treatment reference only) |
| code | `control_center/<file>.py:<line>`, `standalone.py:<line>` (all under `app/`) |
| docs | `CAROUSEL.md §n`, `FLOATING_KNOB.md`, `APP_ICON.md`, `DESKTOP.md` (desktop); `firmware/ALIVE.md §n` |

**Coordinates.** "Stage px" are the prototype's 1280 × 720 reference stage (B&S:L24).
Production maps them to physical px exactly as the carousel does today:
`k = min(monW/1280, monH/720)`, stage centred on the monitor (`carousel_render.py:179-229`). On
the user's 5120 × 1440 monitor `k = 2`, the stage is 2560 × 1440 at x = 1280. The prototype
fakes a 48 px taskbar at stage y 672–720 (B&S:L37), so its "work area" is 1280 × 672.

**Curves** (all from the prototype):
| Name | Value | Where |
|---|---|---|
| OUT | `cubic-bezier(0.22,1,0.36,1)` | B&S:L878 (`OUT`), everywhere |
| SPRING | `cubic-bezier(0.34,1.45,0.64,1)` | tray reveal B&S:L47, toast L199 |
| HEART | `cubic-bezier(0.34,1.6,0.64,1)` | liked-heart pop B&S:L183 |
| ease | CSS `ease` = `cubic-bezier(0.25,0.1,0.25,1)` | shades, crossfades, colour changes |

`carousel.py:131-132` already defines OUT (`EASE_OUT`) and SPRING; HEART and `ease` are new.

**CSS transform composition (exactness note).** The prototype appends the enter/hidden offsets
**after** the card's scale, e.g. `translate(-50%,-50%) translateX(±X) scale(S) translateY(30px) scale(0.9)`
(B&S:L923). CSS multiplies left to right, so the offset is scaled by `S` and the scales multiply.
Effective values are given below per overlay; implementers must not use the raw 30/24/40 px for
side cards.

**Standing user decisions that touch the desktop** (over the design):
1. LED colours: warm fixed at LED-output #FF8424; volume 80–90 % #FF3A0A, ≥ 90 % #FF0000 (LED
   analysis, not here). The floating knob runs the same choreography (ALIVE §10.3).
2. PC away: drain → amber marks → native profile lights. Firmware only; "the desktop simply
   hides" (ALIVE §8.1).
3. One combined release: cc5.4 + desktop v7.
4. Earlier, still standing: the **live app has no main window** — tray + floating knob only
   (FLOATING_KNOB.md user request; DESKTOP.md "The app has no main window"); the picker background
   is **"full screen or not at all"** (CAROUSEL §11); **Frosted / No background** is a Settings
   choice (`ui.py:117`).

---

## 1. What all three overlays share

### 1.1 Surface rules
- Topmost, **never take focus**, full screen, blurred backdrop (README §7.1; 01 §5, §6, §7).
  Picker exception, recommended to keep: §4.10.
- Any toast is **cleared when an overlay opens** (B&S:L680, L794, L818:
  `clearTimeout(this._tt); toastOn:false`) and is never shown over one (README §7.1, 01 §8).
- Placement (CC:L747-L756, and the current picker rule `CAROUSEL.md §2`): centred on the display
  holding the foreground window, never spanning two.
- Prototype stacking (z-index): picker 10 (B&S:L43) < explorer 12 (L103) < Up next 13 (L154) <
  snap fly 20 (L99) < toast 30 (L199).
- Font on the whole stage: Archivo (B&S:L24).

### 1.2 Backdrops (exact)
| Overlay | Backdrop filter | Tint over it | Extra layer | Overlay fade (in and out) | Source |
|---|---|---|---|---|---|
| **Music explorer** | `blur(36px) saturate(1.3)` | `rgba(8,8,10,0.5)` | **Ambient**: focused album's cover (playlist: its first mosaic cover), box inset **−160 px** on every side (1600 × 1040 stage px), `center / cover`, `filter: blur(90px) saturate(1.5)`, **opacity 0.5**, `transition: background 600ms ease` | 340 ms OUT | B&S:L103-L105, L935 |
| **Up next** | `blur(36px) saturate(1.3)` | `rgba(8,8,10,0.55)` | Ambient: the **focused track's** album cover, same box and filter, **opacity 0.45**, 600 ms ease | 340 ms OUT | B&S:L154-L156, L1048 |
| **Window picker** | `blur(40px) saturate(1.6)` | `rgba(10,10,12,0.5)` | **Sheen**: `linear-gradient(180deg, rgba(255,255,255,.06) 0%, rgba(255,255,255,0) 30%)` over the full stage | 280 ms OUT | B&S:L43-L45; 01 §7 |
| *Current picker (Frosted, v6)* | σ = 40·k, saturate 1.8 | `rgba(18,18,20,.58)` with the 12 % dim folded in (× 0.88) | none (no sheen, no border: CAROUSEL §11) | frost 280 ms | `carousel_render.py:107-127` |

- 01 §6 says Up next has "the same backdrop and ambient treatment as the explorer"; the
  prototype uses 0.55 / 0.45 instead of 0.5 / 0.5. The numbers above are the prototype's.
- **No desktop dim** in any of the three. The current 12 % dim came from 04's superseded
  "Desktop behind: dimmed 12 %".
- In the current pipeline terms (`carousel_render.py:287-326`): σ at reduce(8) = N·k/8 →
  **9** for the explorer and Up next, **10** for the picker, at k = 2. Composite order, as CSS
  paints it: `F = saturate(blur(desktop))`; `F = F·(1−a) + tint·a`; then
  `F = F·(1−o) + saturate1.5(blur90(coverBox))·o`; picker only: `F += (255−F)·s(y)` with
  `s(y) = 0.06·(1 − y/0.3H)` for `y < 0.3H`.
- Full-screen mapping (not in the design, which only has a 16:9 stage): frost and sheen should
  cover `rcMonitor` (sheen height relative to the monitor), and the ambient box should be
  `rcMonitor` inflated by 160·k, as the frost already is today (CAROUSEL §11).

### 1.3 Shared components
| Component | Exact spec | Source |
|---|---|---|
| **Key box** (hints, tray captions) | 16 × 16, 1 px border `rgba(255,255,255,.6)`, 10 px weight 700, digit centred | B&S:L58, L147, L192 |
| **Tab key box** | 18 × 18, 1 px border `currentColor`, 11 px 700 | B&S:L111 |
| **Hint row** | top 664, full stage width, centred, gap 28 between hints, 13 px, `rgba(255,255,255,.8)`; hint = key box + 6 px + label | B&S:L144-L151, L189-L196 |
| **Dots** | top 622, centred, gap 8, height 6, `#fff`; selected 22 wide at opacity 1, others 6 wide at **0.5**; `transition: width 320ms OUT, opacity 320ms ease`; square (no radius, no shadow) | B&S:L91-L95, L139-L143, L1069, L1076 |
| **End bump** | the card or row container moves −dir × **14 px** (explorer on X, Up next on Y) or −dir × **12 px** (picker, X), 160 ms OUT, and back after 160 ms | B&S:L651, L66, L120, L171, L1067, L1073, L1078 |

### 1.4 Input in the prototype
- ←/↑ and →/↓ turn; keys 1–4 press; the wheel turns one detent per 40 delta units
  (B&S:L622-L630); dragging the knob turns 18° per detent in lists and 360/67° on Home and in
  Seek (B&S:L866-L875).
- Clicks: a side card or row selects it; the centre card or focused row runs the action
  (B&S:L908, L930, L1044). In production this desyncs the knob's absolute position; the picker
  already ignores side-card clicks for that reason (CAROUSEL deviation 5). See §12, Q12.

---

## 2. Music explorer (01 §5, README §7.1, B&S:L103-L152, L793-L815, L916-L935)

### 2.1 Entry, exit, buttons
- **Open**: knob **Recently Added → button 2 "Open on screen"** (B&S:L740 → `openExplorer`,
  L793-L798). On open:
  - The mode becomes `explore`.
  - The source is forced to **Recently Added**, and `xIdx.recent` is set to the knob's `rIdx`
    (same album). `xIdx.playlists` keeps its last value.
  - Toasts are cleared. The knob LCD flips in from the right.
  - `xIn` turns true two frames later (`raf2`), which starts the staggered entry.
- **Buttons while open** (B&S:L743-L747; README §4):
  | Button | Action |
  |---|---|
  | 1 Back | `closeExplorer` (L799-L804): the overlay fades (340 ms), the mode returns to `recent`, `rIdx = xIdx.recent` **only if the source was Recently Added** (from Playlists the knob keeps its old album), the LCD flips in from the left, and `xIn` resets at 360 ms |
  | 2 Recently Added | `setSrc('recent')`; nothing if already active |
  | 3 Favourite playlists | `setSrc('playlists')`; nothing if already active |
  | 4 Play | `playFromExplorer` (L810-L815) |
  | Hold 1 for 600 ms | Home from anywhere (README §4; not implemented in the prototype) |
- **Turn** (L705-L710): ignored while a source switch (`xFade`) or Play (`xPlay`) animates.
  Past either end: bound LED + 14 px bump. Otherwise `xIdx[src] += d`.
- Knob footer, for reference (L968): Back (nav), clock (on when Recently Added is active, else
  off), list-music (on/off), Play (go). The button LEDs are on = warm 1.0, off = warm 0.3,
  go = green 1.0, nav = warm 0.7 (L983).

### 2.2 Tabs (B&S:L107-L118, L1074)
- Row at **top 44**, full width, centred, **gap 36** between the two tabs.
- Each tab is a column (centred, gap 10). Colour: active `#ffffff`, inactive
  `rgba(255,255,255,.55)`; `transition: color 240ms ease`.
- Line 1 (flex gap 8, **17 px weight 600**): tab key box, an 18 px icon (stroke 2, round caps
  and joins), then the label.
  | Tab | Key | Icon | Label |
  |---|---|---|---|
  | 1 | `2` | clock (`I.clock`) | `Recently Added` |
  | 2 | `3` | list-music (`I.queue`) | `Favourite playlists` |
- Underline: 2 px `#fff`, width 0 % → 100 % of the tab column, `transition: width 320ms OUT`.
  The parent centres it, so it **grows from the middle outward**.

### 2.3 Carousel geometry (B&S:L120-L132, L917-L931)
- Container: the whole stage; `transform: translateX(−xBump·14px)`, 160 ms OUT.
- Card: absolute at left 640 / top 318, **340 × 340**,
  `translate(-50%,-50%) translateX(sg·XX[a]) scale(XS[a])`, with `a = min(|i − sel|, 4)`.

| a | Offset X | Scale | Opacity | Shade (`#0b0b0c`) | Box shadow | z | Pointer |
|---|---|---|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 0 | `0 40px 80px rgba(0,0,0,.55)` | 10 | click = Play |
| 1 | ±300 | 0.60 | 0.92 | 0.24 | `0 16px 36px rgba(0,0,0,.4)` | 9 | click = select |
| 2 | ±470 | 0.42 | 0.55 | 0.48 | same | 8 | click = select |
| 3 | ±590 | 0.30 | 0 | 0.60 | same | 7 | none |
| ≥ 4 | ±660 | 0.22 | 0 | 0.60 | same | 6 | none |

- The shade is `min(0.6, 0.24·a)` with `transition: opacity 320ms ease` (L129, L929). The
  shadow switches instantly: it has no transition.
- Derived extents (stage px):
  - Centre card: x 470–810, y 148–488.
  - a = 1: 204 px, at x 238–442 and 838–1042, y 216–420.
  - a = 2: 142.8 px, at x 98.6–241.4 and 1038.6–1181.4, y 246.6–389.4.
  - The gap from centre to a = 1 is 28 px. The a = 1 and a = 2 cards overlap by 3.4 px; the
    a = 1 card is on top.
  - At k = 2 the centre card is 680 physical px.

### 2.4 Card face (B&S:L122-L130, L925)
- `background:#222` until the art arrives; `overflow:hidden`; a 2 × 2 grid.
- **Album**: one tile spanning `1 / 3` on both axes, `url(cover) center / cover`.
- **Playlist**: four tiles, k = 0..3 at column `1 + k%2`, row `1 + ⌊k/2⌋` (TL, TR, BL, BR),
  from `PL[i].a[0..3]`. Each tile is 170 × 170 at scale 1, cover-fit.
- A 1 px inset border `rgba(255,255,255,.12)` over the art (L128), then the shade layer (L129).
- No outline, badge or text on explorer cards (unlike the picker).

### 2.5 Label, dots, hints (B&S:L134-L151, L933-L934, L1075-L1077)
- Column at left 190, width 900, **top 514**, centred, gap 6, `#fff`. During a source switch it
  goes to opacity 0 (`xLabelOp`), with `transition: opacity 180ms ease`.
  | Row | Style | Album | Playlist |
  |---|---|---|---|
  | Title | **30/36**, 600, −0.01 em, one line, ellipsis, max 900 | title | title |
  | Sub | 17/22, `rgba(255,255,255,.9)` | artist | `Favourite playlist` |
  | Meta | 14/18, `rgba(255,255,255,.72)` | `{year} · {n tracks}` (sample: `2021 · 9 movements`, `1985 · 12 tracks`) | `{n} songs · {h} h {mm} min` (sample: `48 songs · 3 h 12 min`, `52 songs · 3 h 01 min`) |
- Derived rows: title y 514–550, sub 556–578, meta 584–602. The text swaps instantly on each
  detent.
- Dots: one per item of the **active** source, top 622 (§1.3).
- Hints (static): `[1] Back`  `[2] Recently Added`  `[3] Playlists`  `[4] Play` (L1077). The
  tab reads "Favourite playlists"; the hint reads "Playlists".

### 2.6 Motion (exact)
Each card's transition string (L928) is
`transform {T}ms OUT {D}ms, opacity {O}ms OUT {D}ms`:
- hidden (`!xIn` or `xFade`): T = 180, O = 160, D = 0;
- otherwise: T = **440**, O = **320**, D = **45·a**.

The hidden pose (L923) appends ` translateY(30px) scale(0.9)` at opacity 0. Effectively:

| Card | Rise | Scale |
|---|---|---|
| Centre | +30 px | 0.90 |
| a = 1 | +18 px | 0.54 |
| a = 2 | +12.6 px | 0.378 |

| Event | Timeline |
|---|---|
| **Open** | Overlay opacity 0 → 1 over 340 ms OUT. Cards go from the hidden pose to rest, transform 440 ms / opacity 320 ms OUT, delayed 0 / 45 / 90 ms for a = 0 / 1 / 2 (01 §5: "rise from +30 px at scale 0.9, staggered by 45 ms × distance, over 440 ms"). Tabs, label, dots and hints come with the overlay fade. |
| **Turn** | Spec: **420 ms ease-out** (01 §5; README §7.1). Prototype: 440 ms with the 45·a ms delay, because the open's transition string stays active (see §2.10). |
| **End** | Bound LED; the card row bumps 14 px (§1.3). |
| **Source switch** (`setSrc`, L805-L809) | t = 0: `xFade`, so every card drops to the hidden pose (180 / 160 ms, no delay) and the label fades out (180 ms). t = 190: the source switches, and the tabs (colour 240 ms, underline 320 ms) and dots follow. The knob LCD flips (+1 towards Playlists, −1 towards Recently Added). `xIn` goes false, then true after two frames, and the new cards stagger in exactly as on open, **at the source's own remembered position**. The label fades back in (180 ms). |
| **Play** (L810-L815, L920-L927) | t = 0: `xPlay`. The centre card scales to **1.12** (440 ms OUT); every other card fades to 0 (320 ms, delayed 45·a). The label, tabs and dots stay. t = **380**: the overlay fades out (340 ms), `playItem` runs (queue replaced, mode **Home**, LCD flip −1, a Wash LED in the item's colour) and the toast reads `Playing {title} · {room}`. t = 760: `xPlay` and `xIn` reset, unseen. |
| **Close** (Back) | The overlay fades out over 340 ms; the cards reset at 360 ms. |
| **Ambient** | Crossfades over 600 ms (ease) on every change of the focused item or source. |

### 2.7 State and position memory
- `src ∈ {recent, playlists}` and `xIdx = {recent, playlists}` (B&S:L596). Each source keeps
  its own position (01 §5).
- Recently Added's position is re-seeded from the knob on **every** open (L795). Playlists'
  position survives across opens for the session (only `fresh()` resets it to 0).
- Play from either source goes to **Home**, not back to Recently Added. Playing an album sets the
  knob's `rIdx` to it (L769).

### 2.8 Knob mirror (for context; LCD analysed elsewhere)
LCD (L969): label `RECENT · SCREEN` / `PLAYLISTS · SCREEN`; title; sub = artist, or the
playlist's song count only (`48 songs`, i.e. `n.split(' · ')[0]`); meta `{i} / {n}`; the art is
the ambient cover at 80 %.

### 2.9 Data the desktop must supply
- **Album**: title, artist, year, track count, a **600 px** cover for the overlay (README §8;
  01 §5), and the dominant colour for the ring (`dominant()` = `artwork.dominant_rgb`,
  `artwork.py:193`).
- **Playlist**: title, song count, total duration, the 4 album covers of the mosaic, and a
  colour. The prototype hard-codes `PL[].c`, and the design does not say which image the
  colour comes from (§12, Q7).
- Size check: at k = 2 the centre card is 680 px, so a 600 px cover is upscaled 1.13×. Apple
  artwork templates take any size (`artwork.apple_artwork_url(artwork, size)`,
  `artwork.py:110`); consider `ceil(340·k)`.
- Today `artwork.py` fetches the 480 px template for the LCD (`ARTWORK_SIZE`, `artwork.py:52`)
  and builds a *scrimmed* 480 px copy for the floating knob (`hires_cover_jpeg`,
  `artwork.py:255`). The explorer needs **unscrimmed** covers, a mosaic composite, and the
  56 px row covers of Up next.

### 2.10 Unspecified, conflicts, errors
- **Turn timing**: spec 420 ms with no delay, against the prototype's 440 ms + 45·a delay.
  Recommend the spec (retarget mid-flight like the picker; a per-distance delay makes far cards
  lag on fast turns). §12, Q1.
- **"Like feeds Favourite playlists"** (01 §6; B&S:L376) conflicts with README §8 ("It does not
  appear in Favourite playlists"). README wins.
- **The room in the toast** is hard-coded `· Hall` (L773). Production: the Sonos group label
  (`controller.state["group_label"]`).
- **Not specified by the prototype**:
  - The Recently Added paging with `More` entries (03; `controller.py:607-632`) and page
    prefetch (ARTWORK2 §11.1). A 50-item list gives 50 dots (up to about 90 fit in 1280 px).
  - Recently Added items that are playlists or songs (the prototype shows albums only).
  - An empty Favourite playlists source.
  - Unavailable items (03: cover at 35 %, `{i}/{n} · Not available`).
  - The pending play state (03: `Starting…`, Back disabled).
  - A partial failure (03: `Queue replaced · didn't start`).
  - An expired Apple Music sign-in (03 has only the knob screen "Apple Music sign-in expired /
    Renew on your PC / Windows still works").
  - Slow artwork (the card shows `#222`).

  §12, Q3–Q6.

---

## 3. Up next (01 §6, README §7.1, B&S:L154-L197, L680-L698, L1027-L1049, L1078-L1081)

### 3.1 Entry, exit, buttons
- **Open**: knob **Tracks → button 2 "Open on screen"** (B&S:L750). If Seek is on, it is
  switched off first (with the Reveal LED); then `openQueue` (L680) runs:
  - toasts are cleared, the mode becomes `queue` and `qIn` turns true after two frames;
  - **`qSel = qNow`**: the focus opens on the playing row;
  - the LCD flips in from the right.
- **Buttons** (L753-L757):
  | Button | Action |
  |---|---|
  | 1 Back | `closeQueue` (L681): overlay fade 340 ms, mode `tracks`, LCD flip −1, `qIn` reset at 360 ms |
  | 2 Shuffle | Toggle (L682-L692), §3.6 |
  | 3 Like | Toggle on the **focused** track (L756 → `like`, L657-L663) |
  | 4 Play | Jump to the focused track (L693-L698) |
- **Turn** (L718-L723): ignored during `qFade` or `qPlay`. Past either end: bound + a 14 px
  **vertical** bump. Otherwise `qSel ± 1`.
- Knob footer, for context (L957):
  - Back (nav);
  - Shuffle: on (warm 1.0) while shuffle is on, off (warm 0.3) while it is off;
  - Heart: on, in pink `255,40,90`, when liked, else nav;
  - Play (go).

  The LCD (L958) shows `UP NEXT · SCREEN`, the title, the artist, and
  `{i} / {n}[ · playing]`.

### 3.2 Left column (B&S:L157-L170, L1049, L1079-L1080)
- Block at left 120, top 120, width 380; flex column, gap 18.
  - Rest pose: `none`.
  - Hidden: `translateY(20px) scale(0.96)`, opacity 0.
  - On Play: `scale(1.04)`.
  - `transition: transform 460ms OUT, opacity 320ms ease`.
- **Cover** 380 × 380:
  - The background is the **focused track's album cover** (`qBig`).
  - `box-shadow: 0 40px 80px rgba(0,0,0,.55), inset 0 0 0 1px rgba(255,255,255,.12)`.
  - `transition: background 420ms ease`: a **crossfade** whenever the album changes.
  - An album queue never changes, so the cover "stays still". A playlist changes per row.
    Play-next album rows bring their own cover.
- **Text** (column gap 6, `#fff`), starting at y 518:
  | Row | Style | Album context | Playlist context |
  |---|---|---|---|
  | Caption | `Up next`, 13 px, 600, 0.12 em, uppercase (renders `UP NEXT`), `rgba(255,255,255,.72)` | same | same |
  | Title | 24/30, 600, one line, ellipsis | album title | playlist title |
  | Sub | 15 px, `rgba(255,255,255,.86)`, ellipsis | `{artist} · {year}` | `Favourite playlist · {n} songs · {duration}` |
  | Shuffle state | 13 px, flex gap 6, 16 px shuffle icon (stroke 2) + text; colour `#ffffff` when on / `rgba(255,255,255,.6)` when off; `transition: color 240ms ease` | `Shuffle on` / `In order` | same |
- The context is **what the companion last started** (`np`). A Play-next album does not change
  it.

### 3.3 Vertical list (B&S:L171-L188, L1028-L1046)
- Container: the whole stage, `transform: translateY(−qBump·14px)`, 160 ms OUT.
- Row: absolute at left **600**, top **320**, width **560**, height **88**,
  `transform-origin: 0 50%`, `translateY(-50%) translateY(sg·QY[a]) scale(QS[a])`. The row
  scales around its left edge's midpoint, so rows stay left-aligned at x 600.

| a | Offset Y | Scale | Opacity | Row centre y | Row span y (derived) |
|---|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 320 | 276–364 |
| 1 | ±100 | 0.78 | 0.72 | 220 / 420 | 185.7–254.3 / 385.7–454.3 |
| 2 | ±176 | 0.66 | 0.46 | 144 / 496 | 115–173 / 467–525 |
| 3 | ±236 | 0.58 | 0.24 | 84 / 556 | 58.5–109.5 / 530.5–581.5 |
| ≥ 4 | ±284 | 0.52 | 0 | — | hidden |

**Played rows** (`k < qNow`) are dimmed: opacity × 0.6 (L1036).

**Row inner** (flex, centred, gap 18, height 88, padding 0 20):
- **Focused row**: background `rgba(255,255,255,.14)`, box-shadow
  `inset 0 0 0 1px rgba(255,255,255,.28), 0 20px 50px rgba(0,0,0,.35)`. Others are transparent
  with no shadow. `transition: background 300ms ease, box-shadow 300ms ease`.
- **Lead**, one of two:
  - **Art**, for a playlist context, or for a row whose album is not the context album (a
    Play-next album): 56 × 56 cover with a 1 px inset border at 12 % white (L175, L1039).
  - **Number**, for an album context row of that album: 40 wide, 20 px weight 500,
    `rgba(255,255,255,.72)`, tabular. It is `padStart(2,'0')` of the **track number within its
    album** (`01`…`12`), kept through shuffle (L176, L440, L1039).
- **Text** (flex 1, gap 4):
  - Title: 22/26, 600, `#fff`, ellipsis.
  - Sub: 14/18, `rgba(255,255,255,.82)`, ellipsis. For a context-album row it is `{artist}`;
    otherwise `{artist} · {album}` (L1040).
- **Right** (gap 12):
  - **Tag**: 12 px, 600, 0.08 em, uppercase.
    | Tag | Row | Colour |
    |---|---|---|
    | `Now playing` | `k = qNow` | `#6ED996` |
    | `Up next` | **only** `k = qNow + 1` | `rgba(255,255,255,.7)` |
    | `Played` | `k < qNow` | `rgba(255,255,255,.7)` |
    | none | any other row | — |

    (L1041-L1042.)
  - **Heart**: 20 px `I.heart`, filled `#ff2a5a`.
    - Opacity 1 when liked, else 0 (200 ms ease).
    - Transform `scale(1.5)` while popping, `scale(1)` when liked, `scale(0.4)` when not.
      `transition: transform 380ms HEART`.
    - The pop lasts 420 ms after the press (L660, L1043).
    - The LED pink is 255,40,90 (#FF285A); the heart's fill differs slightly.

### 3.4 Motion (exact)
Each row's transition string (L1037) is
`transform {T}ms OUT {D}ms, opacity {O}ms OUT {D}ms`:
- hidden (`!qIn` or `qFade`): T = 160, O = 150, D = 0;
- otherwise: T = **420**, O = **300**, D = **40·a**.

The hidden pose appends ` translateX(40px)` at opacity 0. The row scale applies to it, so the
effective shift is 40 / 31.2 / 26.4 / 23.2 px for a = 0 / 1 / 2 / 3.

| Event | Timeline |
|---|---|
| **Open** | Overlay 340 ms OUT. Rows slide in from +40 px, staggered 40 ms × distance (420 / 300 ms). The left column rises from +20 px at 0.96 (460 ms), opacity 320 ms. |
| **Turn** | 420 ms OUT (plus the 40·a delay in the prototype; same issue as §2.10) and a 14 px vertical bump at the ends. |
| **Shuffle** (L682-L692) | t = 0: Scatter LED; `qFade`, so the rows go to the hidden pose (160 / 150 ms). t = **200**: the new order, `shuffle`, `qNow` and **`qSel = min(n−1, qNow+1)`** (the focus jumps to the first upcoming track) apply. `qIn` goes false, then true after two frames: the rows stagger back in (420 / 300 ms, 40·a). The shuffle line changes text and colour (240 ms). |
| **Like** (L657-L663) | Toggles. The heart pops to 1.5 and settles at 420 ms (HEART, 380 ms). On a like (not an unlike): pink Bloom LED and a 420 ms ring wash. |
| **Play** (L693-L698) | t = 0: `qPlay`. The focused row scales to **1.06** (420 ms); the others fade (300 ms, 40·a); the left column scales to 1.04 (460 ms). t = **380**: the overlay closes (340 ms). `qNow = qSel`, playing, **mode = Home** (not Tracks), LCD flip −1, toast `Playing {track}`. t = 760: reset. |
| **Close** | The overlay fades out over 340 ms; `qIn` resets at 360 ms. |
| **Crossfades** | Big cover 420 ms ease; ambient 600 ms ease. |

### 3.5 Queue model and rules (prototype semantics)
- `queue[]` holds the items (title, artist, album, track number or null). `qOrder[]` is the play
  order, as indices into `queue`. `qNow` and `qSel` are positions in `qOrder` (B&S:L601).
- **Album queue** (`queueFor`, L440): one row per album track, `n = k+1`. **Playlist queue**:
  sample rows from the playlist's albums, `n = null` (L442).
- **Play next** (Recently Added, button 3; `playNext`, L776-L784):
  - The album's tracks are **appended to `queue[]`**, and their indices are **inserted into
    `qOrder` right after `qNow`**. The queue is kept.
  - A Sweep LED runs clockwise, the toast reads `Queued next · {album}`, and the knob meta shows
    `Queued next` for 1.5 s (L964).
- **Shuffle on**: `qOrder[0..qNow]` stays; the rest is Fisher–Yates shuffled
  (`Math.random`); `qNow` is unchanged. Only unplayed tracks move (01 §6; README §7.1).
- **Shuffle off**: `qOrder` becomes the identity `[0..n−1]` (queue-array order) and `qNow`
  becomes the current track's array index. So after a Play next, **the queued album lands at
  the end, not next**. Also, every track before the current one in array order is tagged
  `Played`, whether it played or not. This is a prototype artefact against 01 §6 ("restores
  album order and keeps the current track"). §12, Q9.
- **Auto-advance of playback** (L633-L638): while playing and not seeking, `pos` rises by 1 s.
  At a track's end, `qNow + 1` (pos 0), or it stops at the queue's end. An open Up next
  re-tags live (Now playing moves down); `qSel` does not follow.
- **Like key**: album + title (L656), prototype only. Production uses the Apple Music song id
  (README §8), which `sonos._song_id` (`sonos.py:63-68`) already extracts from queue items.
- `shufflePlay` (L785-L792) exists but **no button calls it**. It would give the toast
  `Shuffling {album} · {room}` and a whole-album shuffle with `qNow = 0`.

### 3.6 Data the desktop must supply
- The **Sonos queue** with per-item title, artist, album, album art URI, Apple song id and the
  original track number. Today `sonos.py` reads only `get_queue(start=0, max_items=1)` for
  counts (`sonos.py:183`) plus the paged full read used for replacement (`_queue`,
  `sonos.py:308-320`). The queue may hold up to `MAX_QUEUE` = 5000 items.
- The current queue position and `queue_revision` (update_id), to detect changes made elsewhere.
- Liked state per visible song (Apple Music ratings; README §8).
- The context (album or playlist) that the companion started.

### 3.7 Unspecified, conflicts, errors
Not specified by the prototype:
- Sonos offline.
- The queue changed elsewhere while open.
- A queue started outside the companion: the context title and layout are unknown. Proposal:
  album layout only when every track shares one album.
- An empty queue.
- Shuffle when the current track is the last (nothing left to reorder).
- A failed Like: README §8 says to replace Like with Play next if the API is unreachable.
- A queue far longer than the ring's 20 landmarks.

§12, Q8–Q10.

---

## 4. Window picker V2 and Snap (01 §7, README §7.1, 04, B&S:L43-L101, L817-L864, L896-L913, L1050-L1051)

### 4.1 What governs what
- **New**: 01 §7 and README §7.1 (full-screen blur, 400 × 250 cards, snap tray, snap flow).
- **Still valid from 04**: motion curves, detent retargeting, end bump, Switch exit, title
  parsing, icons, closed-window rules (README §0 lists only the pane and the 480 × 300 cards as
  superseded).
- **Current build**: CAROUSEL.md, with deviations 1–23 and the section 11 amendment.

### 4.2 Backdrop
See §1.2. It matches the user's "full screen or not at all" (CAROUSEL §11). It differs from v6
in four ways: saturate **1.6** (v6: 1.8); tint `rgba(10,10,12,.5)` (v6: `rgba(18,18,20,.58)`);
**no 12 % dim**; and a **6 % top sheen** (v6: none, by §11).

### 4.3 Card geometry (B&S:L65-L81, L897-L910)
- **Group container**: opacity `wCardsOp` (1 while open), `transition: opacity 220ms ease`.
  Transform `wShift` is **`translateY(-44px)` while no side is assigned** and `translateY(0)`
  once the tray shows; transition 460 ms OUT. An inner container carries the bump,
  `translateX(−wBump·12px)`, 160 ms OUT.
- **Card**: absolute at left 640 / **top 370**, **400 × 250**,
  `translate(-50%,-50%) translateX(sg·X[a]) scale(S[a])`, `transition: transform 420ms OUT,
  opacity 300ms OUT` (no stagger).

| a | Offset X | Scale | Opacity | Shade (`#111`) | z | Pointer |
|---|---|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 0 | 10 | click = Switch |
| 1 | ±280 | 0.56 | 0.95 | 0.22 | 9 | click = select |
| 2 | ±400 | 0.34 | 0.60 | 0.44 | 8 | click = select |
| 3 | ±490 | 0.26 | 0 | 0.55 | 7 | none |
| ≥ 4 | ±540 | 0.20 | 0 | 0.55 | 6 | none |

- The effective card centre is **(640, 326)** with the tray hidden and **(640, 370)** with it
  shown.
- Derived extents with the tray shown:
  - Centre card: x 440–840, y 245–495.
  - a = 1: 224 × 140, at x 248–472 and 808–1032, y 300–440. It tucks **32 px under** the
    centre card.
  - a = 2: 136 × 85, at x 172–308 and 972–1108. It tucks 60 px under the a = 1 card.
- **Thumbnail**: the 480 × 300 content scaled 0.8333 (L70). In production this is the cover-fit,
  top-aligned DWM thumbnail (`carousel_render.cover_source`, `:252`).
- **Open pose**: until `wIn` turns true (two frames after open), each card gets
  ` translateY(24px) scale(0.92)` appended at opacity 0 (L900, L904). That is a rise of 24·S[a]
  and a scale of 0.92·S[a], animated with the 420 / 300 ms transition.

### 4.4 Card face (B&S:L68-L80, L905-L907)
- Base `#1b1b1d`, `overflow:hidden`.
- **Selected outline**: 2 px solid `rgba(255,255,255,.9)`, offset 6 px; the others are
  transparent. **Selected shadow** `0 24px 60px rgba(0,0,0,.45)`, sides `0 12px 30px rgba(0,0,0,.3)`.
  Neither has a transition in this prototype; v6 interpolates them over 320 ms (deviation 11,
  from WC's `transition: box-shadow 320ms`).
- **Badge**: left 12, bottom 12, **30 × 30**, the app icon (`contain`) or a letter tile (16 px
  700 `#fff`), shadow `0 2px 8px rgba(0,0,0,.45)` (L72). v6: 32 × 32 inset 14
  (`carousel_render.py:86-87`).
- **Snap chip (new)**, when the window holds a side:
  - Position left 12, top 12. Flex gap 6, padding 4 px 8 px, background `rgba(18,18,20,.72)`,
    `#fff` 12 px 600.
  - Content: a 16 px icon (outline rect `M3 5h18v14H3z`, stroke 2, plus the filled
    `HALF.left` or `HALF.right`) and the word `Left` or `Right` (L73-L78, L907).
  - 01 §7 writes it as `◧ Left` / `◨ Right`.
- **Shade**: `#111` at `min(.55, .22·a)`, `transition: opacity 320ms ease` (L79). Same as v6.

### 4.5 Label and dots (B&S:L83-L95, L912, L1068-L1069)
- Column at left 190, width 900, **top 512** (468 while the tray is hidden), centred, gap 6.
  | Row | Style |
  |---|---|
  | App | flex gap 8, 15 px, `rgba(255,255,255,.92)`: an 18 × 18 icon (letter 10 px 700) + the app name |
  | Title | **26/32**, 600, one line, ellipsis, max 900; no letter-spacing |
  | Description | 15 px, `rgba(255,255,255,.86)`, then **` · Snapped left`** or **` · Snapped right`** when the centre window holds a side |
- v6 has the label at top 476, the title at 28/34 with −0.01 em, and the description at 88 %
  (`carousel_render.py:88-89`). The 04 parsing rules and CAROUSEL §6 labels still apply.
- Dots: top **622** (578 while the tray is hidden), inactive opacity **0.5**, square, no shadow.
  v6: top 616, 0.60, radius 3, shadow `0 0 6 .35` (`carousel_render.py:92-93`).

### 4.6 Snap tray (B&S:L47-L63, L911-L913, L1070-L1071)
- **Container**: left 0, width 1280, **top 104**; flex, centred, **gap 14**; `pointer-events:none`.
  - Hidden: opacity 0, `translateY(-14px) scale(0.94)`.
  - Shown: opacity 1, `translateY(0) scale(1)`.
  - `transition: opacity 260ms OUT, transform 460ms SPRING`.
  - It shows as long as `left` or `right` is set (`trayOn`).
- **Slots**, in order: left (key `2`), then right (key `3`). Each is a column (gap 6, aligned
  start) holding:
  | Part | Spec |
  |---|---|
  | Box | **176 × 110**, `overflow:hidden`, background `rgba(255,255,255,.04)`. Border: empty `1px dashed rgba(255,255,255,.4)`, filled `1px solid rgba(255,255,255,.5)`; `transition: border-color 260ms ease` |
  | Thumbnail | The window's content at scale 0.3667 (fills 176 × 110); opacity 0 → 1 over 260 ms OUT |
  | Empty glyph | Centred **34 px** icon, stroke **1.8** (rect 3,5,18,14 plus the filled half), `rgba(255,255,255,.8)`; opacity 1 → 0 over 200 ms ease when filled |
  | Badge | Left 8, bottom 8, 22 × 22 icon or letter (12 px 700); opacity follows the fill (260 ms ease) |
  | Caption | Gap 6, 12 px, `rgba(255,255,255,.86)`: key box `2`/`3` + `Snap left` / `Snap right` (empty), or `Left · {App}` / `Right · {App}` (filled) |
- Derived: the slots sit at x 457–633 and 647–823, y 104–214; the captions at about y 220–236.

### 4.7 Snap flow timeline (`snap`, B&S:L839-L857)
| t (ms) | Event |
|---|---|
| 0 | The side is assigned (if the same window held the other side, that side is cleared: a **move**). The slot fills (thumbnail and border 260 ms). On the first snap the tray drops in (SPRING 460 ms) while the card group slides from −44 to 0 (460 ms OUT). The **fly** starts at the card rect (440, 245, 400, 250). The **Half-wash** LED starts on that half of the ring and the matching snap button tints in the app colour. The knob footer icon takes the app colour. |
| 0–460 | Fly: `left/top/width/height/transform 460ms OUT`, shadow `0 30px 70px rgba(0,0,0,.45)`, z 20. The content is **stretched** to the box: `scale(w/480, h/300)`. |
| 360 | The window is placed on its half, **behind the overlay** (the desktop model updates). |
| 380–600 | The fly fades out: `opacity 220ms ease 380ms`. |
| 420 | With only one side filled, the highlight moves to the **next unassigned window** (§4.8). |
| 650 | The ring wash state clears. |
| 700 | The fly element is removed. |
| 820 | With both sides filled, the picker closes (`closeWin(false)`: overlay 280 ms, mode back to Home) and the toast reads **`Side by side · {left App} and {right App}`**. |

- **Fly target**: `{0,0,640,672}` or `{640,0,640,672}`, the halves of the prototype's 1280 × 672
  work area (L844). **Production:** the halves of `rcWork` of the picker's monitor, in physical
  px, **not** stage coordinates. On 32:9 the halves lie outside the centred stage.
- **Fly start**: always the tray-shown card rect (y 245), even on the first snap, when the card
  still sits at y 201. The fly starts 44 px below the visible card. Production should start
  from the card's live rect.

### 4.8 Snap rules
1. **Assign/move** (L840-L842): `nxt = {[side]: id}`; if `s[other] === id`, then
   `nxt[other] = null`.
2. **Auto-advance** (L854-L855): `W.findIndex((_, i) => i !== id && i !== left && i !== right)`.
   That is the **first window in list order** (MRU order: index 0 is the window focused at
   open) that is neither the one just snapped nor assigned. It is not "the next one after the
   current". It applies at 420 ms, and not at all when no candidate exists.
3. **Both filled**: close at 820 ms with the toast (above).
4. **The prototype's desktop model** at 360 ms, `deskFor(left, right, deskAtOpen)` (L832-L838),
   with base = the single origin window X:
   - `L = left ?? (X ≠ right ? X : null)` and `R = right ?? (X ≠ left ? X : null)`;
   - a split when both are set and differ, else single.

   So after snapping any A ≠ X to one side, **the origin X appears on the other half at once**.
   Snapping X itself leaves X alone. That is how the prototype realises 01 §7 item 6: "Closing
   with only one side assigned keeps the previously focused window on the other half". When
   production moves the origin (at the first snap, or only on close) is not stated (§12, Q14).
5. **Back** (`closeWin(true)`, L825-L831): the toast `Back · focus restored` shows **only if no
   side was assigned**; with any snap, there is no toast.
6. **Switch after a snap** (L858-L864): the prototype's desktop turns *single* (the switched
   window full size), the picker closes (no Back toast), a Wash LED runs in the app colour, and
   the toast reads `{App} · {Title}`. Production only activates the window; the snapped windows
   stay where they were placed.
7. **Tray hide** ("when no side is assigned"): it cannot happen within one open, because sides
   only move. Each open resets `left/right = null` (L821).
8. **Knob side** (L974-L975): the LCD meta reads `Left: {App} · pick right` or
   `Right: {App} · pick left`. The snap button LED and footer icon take the app colour while
   assigned.

### 4.9 Placement (01 §7 "Implementation"; README §7.1)
Specified by the design:
- Place each window with `SetWindowPos` on the halves of the **monitor work area**
  (`GetMonitorInfo` → `rcWork`).
- Call `ShowWindow(SW_RESTORE)` first if it is maximized.
- Compensate with `DWMWA_EXTENDED_FRAME_BOUNDS` so no gap shows.
- "Windows 11 then treats the pair as a Snap group."

Engineering notes (public Win32 behaviour and the current code):
- **Frame compensation**: after the restore, read `GetWindowRect` (W) and the extended frame
  bounds (E). For a wanted visible rect V, set the window rect to
  `V.left − (E.left−W.left)`, `V.top − (E.top−W.top)`, `V.right + (W.right−E.right)`,
  `V.bottom + (W.bottom−E.bottom)`.
- **Flags**: `SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER`, so the overlay stays topmost
  and focus is untouched. Add **`SWP_ASYNCWINDOWPOS`**: the target belongs to another thread,
  and a hung target must never block the Tk thread. That matches the existing rule for restores,
  `ShowWindowAsync(hwnd, 9)`, "never wait for the other process" (`windows.py:644`). Then verify
  the result with a bounded re-read of `GetWindowRect`.
- **Restore** minimized windows too (`IsIconic`), and wait, bounded, for the async restore
  before measuring the frame.
- **Mixed DPI**: moving a window from a monitor with another DPI triggers its `WM_DPICHANGED`
  self-resize. Re-read and re-apply once if the rect differs.
- **Minimum widths**: an app whose minimum width exceeds half the work area overlaps its
  neighbour. Verify and report (§12, Q15).
- **UIPI**: `SetWindowPos` on an elevated window from a non-elevated process fails. Handle it
  (there is no design copy for it).
- **Thumbnails**: after placement, `DwmQueryThumbnailSourceSize` changes (half width), so
  re-query it and recompute `cover_source` for that card and its tray slot.
- **Frosted hides the move**: the frost is a static snapshot, so the moved windows are invisible
  until the picker closes. With "No background" (live desktop, 55 % dim) they are seen moving.
- **"Snap group"**: no documented public API forms a Windows 11 Snap group, and nothing public
  says a `SetWindowPos` placement registers one. Treat this as **unverified** and keep it out
  of user-facing copy (B&S:L373 also claims it).

### 4.10 Focus and activation
- The design says all overlays "never take focus" (README §7.1). The v6 picker deliberately
  **keeps an activatable host that owns the foreground** (CAROUSEL §1 and deviation 6). Switch
  and Back arrive over serial with no input event, so the process needs foreground rights to
  `SetForegroundWindow` the target or the origin.
- Snapping itself needs no foreground: `SetWindowPos` works across processes.
- **Recommendation**: keep deviation 6 for the picker, and make the explorer and Up next truly
  non-activating (they never change focus).

### 4.11 Motion summary
| Event | Master prototype | v6 build |
|---|---|---|
| Open | Overlay opacity 280 ms OUT; cards rise from +24·S at ×0.92 to rest (420 / 300 ms, no stagger) | Cards at rest, no motion; card group fades 260 ms; frost 280 ms from alpha 0 (`carousel.py:178-199`) |
| Turn | 420 ms OUT transform, 300 ms opacity; shade 320 ms | Same (`MOVE_S`, `FADE_S`, `SHADE_S`) |
| End bump | 12 px, 160 ms | 12 px, 160 ms, **keyboard/wheel only** (deviation 4). ALIVE adds a knob `lim` event (ALIVE §3), so v7 can drive it from the knob too |
| Switch | Overlay fades 280 ms; toast `{App} · {Title}`. **No card grow** in this prototype | Activate first, then the centre card grows to 1.35 and fades (420 / 300 ms), exit ends at 320 ms, toast (deviations 3, 9). 04's Switch motion is not superseded: **keep** |
| Back | Overlay fades 280 ms; toast `Back · focus restored` (only if nothing was snapped) | Fade; toast `Cancelled · focus restored` (`carousel_render.py:109`) |

### 4.12 Picker conflicts to settle
- The sheen (design) against CAROUSEL §11's "no sheen" (§12, Q11).
- Whether "No background" stays: the design has only the full-screen blur (§12, Q11).
- The 04 closed-window rules (35 % opacity, `Closed · can't switch`, Switch disabled) are not
  drawn in the new prototype. They are still valid; keep them.

---

## 5. Toasts (01 §8, README §7.1, B&S:L199, L648)

### 5.1 Style and motion
| Property | Master design | v6 build |
|---|---|---|
| Position | Stage `left:50%`, **top 588** (bottom centre); z 30 | Stage top **320**, centred (`carousel_render.py:97`, `toast_rect` `:1381-1385`; deviation 8) |
| Box | Padding 12 × 18, `background: rgba(24,24,26,0.62)`, `backdrop-filter: blur(24px)`, 1 px border `rgba(255,255,255,0.2)`, `#fff` 15 px, one line, square corners | Same except tint `rgba(30,30,32,.55)` (`carousel_render.py:98`) and a 0.88 fallback tint without a capture |
| In | Opacity 0 → 1 over **260 ms OUT**; transform `translate(-50%,8px) scale(0.96)` → `translate(-50%,0) scale(1)` over **420 ms SPRING** | Same (`ToastMachine`, `carousel.py:427`) |
| Hold | **1800 ms** from the flash; a new flash replaces the text at once and restarts the timer (L648) | 1.5 s (`TOAST_HOLD_S`, `carousel.py:198`) |
| Out | The same transitions in reverse | Same |
| Rules | **Never over an open overlay**; cleared when one opens; **no toast for Play/Pause** | Shown only after the picker closes; no other toasts |
| Text fit | `white-space:nowrap` | Fitted to 900 px, keeping the `{App} · ` prefix (`fit_toast_text`, `carousel_render.py:1316`) |

### 5.2 Copy catalogue (every string in the prototype)
| Toast | Trigger | Source | Allowed by the rules? |
|---|---|---|---|
| `Playing {album or playlist} · {room}` | Play from the explorer, or Recently Added Play on the knob | B&S:L773 | Yes (shown after the overlay closes) |
| `Queued next · {album}` | Recently Added button 3 | B&S:L783; 01 §6 | Yes |
| `Next · {track}` / `Previous · {track}` | A Tracks skip on the knob | B&S:L678 | Yes |
| `End of queue` / `Start of queue` | A skip that cannot move | B&S:L673 | Yes |
| `Added to Favourites · {track}` / `Removed from Favourites · {track}` | Like in Up next | B&S:L662 | **No**: fired while Up next is open (§12, Q13) |
| `Shuffle on · up next reshuffled` / `Shuffle off · album order` | Shuffle in Up next | B&S:L691 | **No**: same conflict |
| `Playing {track}` | Play in Up next | B&S:L696 | Yes |
| `Shuffling {album} · {room}` | `shufflePlay` (not wired to any button) | B&S:L791 | n/a |
| `Back · focus restored` | Picker Back with no side snapped | B&S:L829 | Yes |
| `Side by side · {A} and {B}` | Both snap sides filled | B&S:L852; 01 §7 | Yes |
| `{App} · {Title}` | Picker Switch | B&S:L863 | Yes |
| *(none)* | Play/Pause, source switch, overlay open, Seek | README §7.1 | — |

### 5.3 What production needs
- A **toast service independent of the picker's lifetime**. Today's toast window belongs to the
  carousel engine and shows only after a picker exit. Most of the new toasts come from knob-only
  actions (Play next, Skip, Play), and the explorer and Up next close into toasts.
- **Monitor**: the monitor of the foreground window, the same as the overlays. For knob-only
  toasts the design does not say (§12, Q13).
- **Errors**: today, errors become tray balloons, at most one every 10 s
  (`standalone.NoticeBalloons` `:671`, `NOTICE_INTERVAL` `:51`). The design has no failure
  toasts; its failure feedback is the Head shake LED (02) plus the knob copy from 03.

---

## 6. Main window, Settings, tray, recovery (README §7.2; 03 "Companion app"; CC section 04)

The design itself calls these surfaces "not redrawn since" (README §1 table). The Control
Center document is dated "Design proposal · v1 · 22 Sep 2026" (CC:L21). It predates the new
button grammar.

### 6.1 Tokens (03, table "Companion app")
| Token | Design | `ui.py` |
|---|---|---|
| Background | `#1B1A1A` | `BG` `:82` |
| Surface | `#242323` | `SURFACE` `:83` |
| Hairline | `#2D2B2B` | `HAIRLINE` `:84` |
| Strong rule | `#444141` | `RULE` `:85` |
| Text | `#F3F2F2` | `TEXT` `:86` |
| Secondary | `#BAB6B6` / `#9B9797` | `SECONDARY` / `TERTIARY` `:87-88` |
| OK | `#6ED996` | `OK` `:89` |
| Error | `#FF7A66` | `ERROR` `:90` |

Also: Archivo, radius 0, 2 px rules (`RULE_WIDTH`). **Identical: no delta.**

### 6.2 Main window (CC:L666-L695, data L1132-L1139)
- **Title bar**, 34 px: a 16 px small app icon + `Nano_D++` (600), then `–` and `×` (tooltip
  `Hides to tray`), with a 1 px `#2d2b2b` rule below.
- **Service strip**: 3 columns, then a 2 px `#444141` rule. Each column holds a caption (11 px
  uppercase, 0.08 em, `#9b9797`), a value (14 px 600 with an 8 × 8 status square) and a detail
  (12 px `#9b9797`):
  | Caption | Values (colour) | Detail |
  |---|---|---|
  | `Knob` | `Connected` (#6ed996), `Not found` (#ff7a66), `Reconnecting` (#bab6b6) | `USB` |
  | `Sonos` | `{room}` (ok), `Unavailable` (bad) | `Stereo pair + Sub` / `Retrying` |
  | `Apple Music` | `Signed in` (ok), `Sign-in needed` (bad) | `Recently Added` / `Renew in Settings` |
- **Body**:
  - The caption `Knob is on` (11 px).
  - The mode at **26 px weight 800**: `Volume`, `Recently Added`, `Tracks`, `Windows` or
    `Waiting` (old mode set).
  - A detail line (14 px `#d7d3d3`). On Home it reads `{Paused · }{vol} % · {title} — {artist}`,
    or `Nothing playing`, or `Hall unavailable; Windows still works` while offline. In other modes
    it is the LCD title, or `{App} · {Title}` in Windows.
  - On the right, a **live mirror** of the Knob Face at zoom 0.42, captioned `Live mirror`.
- **Buttons**:
  - `Settings`: primary, 34 px tall, `#f3f2f2` background, `#1b1a1a` text, 600 13 px.
  - `Disconnect knob`: ghost, with a 1 px `#444141` border.
- A `<details>` block titled **`Troubleshooting`** lists `USB serial · COM{n} · firmware {v}`,
  `Sonos · {room} at {ip} · last event {n} s ago` and `Export diagnostics…`.
- Behaviour (CC:L325): "Closing hides to the tray; Quit stops the controller."
- **Current**: the live app has **no main window** (DESKTOP.md; standalone `chrome=False`,
  `ui.py:630-686`). The dev/simulator window (`ControlCenterApp.build`, `ui.py:812-863`) shows
  `NANO_D++` / `Your desk, within reach.`, `Setup`, `LIVE · HALL` / `SIMULATOR`, the mirror,
  a list, and `Connect knob`. Adopting the design's main window would reverse the user's
  floating-knob-only decision (§12, Q16).

### 6.3 Settings (CC:L698-L731; CC:L36 "Existing settings: launch at sign-in, Sonos target, manual IP, Apple Music sign-in. Anything else is tagged Proposed")
| Section | Design | Current (`ui.setup`, `ui.py:1550-1766`) |
|---|---|---|
| Window | Title `Settings` (34 px bar, 2 px rule) | Title `Nano_D++ · Setup`, heading `Connect your desk` (`:1568`, `:1574`), subtitle `SETUP_SUBTITLE` (`:113`) |
| Knob | `Knob` · `Ready` (#6ed996); a 4-cell button map with the **old grammar** (`1 Play/Pause · Back`, `2 Browse · Home`, `3 Windows`, `4 Tracks · Action`); note "Left to right, under the knob. Fixed mapping." and a `Proposed` press-to-light test | Raw button indices, `Verify physical button order` probe (`:1583-1606`) |
| Sonos target | Room radio list with detail (`Hall — Stereo pair + Sub · Victoria`, `Kitchen — One`); `Manual IP, if discovery fails` input (placeholder IP) | `Hall speaker IP` entry; room chosen by config |
| Apple Music | Status `Signed in` / `Sign-in expired` (colour-coded); "Signing keys stay in Windows Credential Manager and are never shown here."; `Renew sign-in…` | `Apple Team ID`, `MusicKit Key ID`, `Choose .p8 key`, `Authorize Apple Music`. Keys are DPAPI-protected (`credentials.bin`), not Credential Manager |
| LED brightness | `Proposed`: Dim · **Standard** · Bright, "Scales L1–L4 together; ratios stay fixed." | none (ALIVE adds `led_drive` in settings.json with **no UI**, ALIVE §10.2) |
| Launch at sign-in | Checkbox `Launch at Windows sign-in` | Installer-registered Task Scheduler task; no toggle |
| Presentation | — | `Album artwork` On/Off, `LEDs` `Targeted colour` / `White` (ALIVE §2 renames them `Colour` / `Warm only`), `Switcher background` `Frosted` / `No background` (`:1656-1665`) |

If the Settings map is shown at all, it must use README §4's grammar (§12, Q17).

### 6.4 Tray (CC:L733-L745, data L1140-L1143; 05 item 3; README §7.2)
| Element | Design | Current (`standalone.py`) |
|---|---|---|
| Icon | Connected / missing .ico by taskbar theme | Same (`tray_icon_file` `:389`) |
| Tooltip | `Nano_D++ · Knob connected` / `Nano_D++ · Knob not found` | Same (`tray_tooltip` `:382`) |
| Menu header | 8 × 8 status square + `Knob connected` / `Knob not found`; sub line `{room} · {vol} %` or `Looking for USB device…` | `Knob connected` / `Knob not found` (`TRAY_HEADERS` `:62`), then the device status line (disabled) |
| Items | `Open Nano_D++`, `Disconnect` / `Connect`, rule, `Quit` with the hint `Stops the knob` | `Show knob` (default, left click, 2.5 s peek), `Settings…`, `Disconnect knob` / `Connect knob`, `Quit` (`tray_menu_model` `:433-444`) |
| Styling | Custom (240 wide, `#242323`, 13 px) | Native Win32 menu via pystray (it cannot be styled) |

### 6.5 Connection and recovery (CC:L757-L778, data L1020-L1030; README §7.2)
Four state cards. Each has the 3-column service strip, a title, a body, a CTA and a small knob
LCD:
| Title | Body | CTA | Strip |
|---|---|---|---|
| `Knob not found` | "Plug in the USB cable. The app keeps looking and connects on its own; nothing else to do." | `Open Settings` | Knob `Not found` (bad) |
| `Reconnecting…` | "Reads fresh volume and track from Sonos, then opens Volume. Turns and presses made while unplugged are discarded." | — | Knob `Reconnecting` (wait) |
| `Hall unavailable` | "Volume and Tracks wait for Sonos. Windows switching keeps working. Retrying every 5 s." | `Set manual IP…` | Sonos `Unavailable` |
| `Apple Music sign-in expired` | "Recently Added can’t load. Volume, Tracks and Windows are unaffected." | `Renew sign-in…` | Apple Music `Sign-in needed` |

**Current**: the tray header and status line, tray balloons for failures, Settings notes for the
Apple Music authorization, and the knob's own LCD states. There is no card surface. With no main
window, these cards have no home unless Settings grows a status header (§12, Q16).

---

## 7. App and tray icons (05 = icons/README.md; README §7.3)
- **Assets**: every file in `icons/` (5 `.ico`, 24 `.png`, 6 `.svg` and `README.md`) is
  **byte-identical** to the installed `assets/app-icon/` (SHA-256 compared file by file). **No
  asset work.**
- Specs already met by v5 (APP_ICON.md items 1–8): exe `--icon`, Start-menu `IconLocation`,
  per-DPI `WM_SETICON`, tray `.ico` loaded at `SM_CXSMICON` per DPI, the connected/missing
  switch together with the tooltip and header, and the dark/light theme.
- Remaining differences:
  1. **Theme watch**: README §7.3 and 05 item 4 ask to watch `WM_SETTINGCHANGE`
     (`ImmersiveColorSet`). v5 polls the registry every 2 s (`THEME_POLL_MS`,
     `standalone.py:63`; APP_ICON.md item 6). This is optional; polling is functionally
     equivalent within 2 s.
  2. 05 item 1's `root.iconbitmap(default=…)` was **deliberately not used** (APP_ICON.md
     "Correction": Tk 8.6.15 cannot read PNG-compressed frames). Keep the correction.
  3. Stale design text to ignore:
     - CC:L596 and L661 describe a *red* cursor and 48/256 px tray frames. 05 is final: orange
       `#ff6a1a`, tray frames 16–32.
     - CC:L719 says "Credential Manager".

---

## 8. Floating knob implications (overlay.py, FLOATING_KNOB.md, ALIVE §10.3)
- **LEDs**: with `alive` firmware the floating knob uses `AliveLights`: the same choreography,
  and the design's segment and button look (ALIVE §10.3). The master moments specific to the
  desktop overlays are the ambient tint in lists/explorers, Wash, **Half-wash** (snap),
  **Pink bloom** (Like), **Scatter** (shuffle) and **Sweep** (Play next) (README §6; B&S:L393
  `DUR`: half 900, bloom 900, scatter 700, sweep 640, wash 1100 ms). They come for free if the
  engine is fed the right events (LED analysis).
- **LCD**: the floating knob draws `lcd_preview.render_lcd` at a higher fidelity
  (FLOATING_KNOB §2), so every new knob layout also appears on the desktop:
  - the Seek screen;
  - the `RECENT · SCREEN`, `PLAYLISTS · SCREEN` and `UP NEXT · SCREEN` mirrors;
  - the Windows snap meta;
  - the footer tones `on #FFFFFF` / `off #7A7A7A` / `dim #5A5A5A` and the per-icon colours for the
    heart and snap halves (B&S:L938, L981).

  The **new icons** (expand, clock, list-music, list-plus, seek, shuffle, heart, rect + half,
  check) each need @2x and @3x masks (FLOATING_KNOB §2, "High-resolution sources").
- **Suppression**: today the reasons are `disconnected`, `picker` and `carousel`
  (`ui.py:1211-1219`). The design does not say whether the knob shows over the explorer or Up
  next. On a 16:9 monitor the knob's box (458 px wide at 100 %, at the left edge of the primary
  monitor) covers the explorer's a = 2 card and Up next's cover column. §12, Q18.
- **Capture exclusion**: any new frost capture must exclude the knob's window exactly as the
  picker does (`set_capture_exclusions`, `ui.py:1517`; CAROUSEL §5).
- **Summon**: ALIVE's `lim` event summons the knob (ALIVE §3). It is also the only knob signal
  that could drive the overlays' end bumps.

---

## 9. Deltas vs current

Legend: **New** = nothing exists; **Change** = existing code or constants change; **Same** = no
work; **Decide** = user or spec-owner decision first (§12).

### 9.1 Window picker
| # | Area | Current (v6) | Master design | Kind |
|---|---|---|---|---|
| P1 | Background | Frosted: full monitor, σ 40·k, saturate 1.8, tint (18,18,20,.58) with 12 % dim folded, no sheen (`carousel_render.py:107-127`); or No background, 55 % dim | Full-screen blur 40, saturate **1.6**, tint **(10,10,12,.5)**, **no dim**, **6 % top sheen** to 30 %; no "No background" variant | Change + Decide (sheen, No background) |
| P2 | Card base | 480 × 300 at (640, 300) (`carousel_render.py:72-73`) | **400 × 250** at **(640, 370)**, or (640, 326) with the tray hidden | Change |
| P3 | Offsets | 320 / 460 / 560 / 620 (`TABLE`, `:77-78`) | **280 / 400 / 490 / 540** | Change |
| P4 | Scale, opacity, shade | 1 / .56 / .34 / .26 / .20; 1 / .95 / .60; min(.55, .22a) | Same | Same |
| P5 | Outline, shadows | Same values, interpolated over 320 ms (deviation 11) | Same values, no transition | Same (keep the interpolation) |
| P6 | Badge | 32 × 32, inset 14 | **30 × 30, inset 12**; letter 16 px | Change |
| P7 | Snap chip | — | `Left` / `Right` chip with a half icon | New |
| P8 | Label | Top 476; title 28/34, −0.01 em; description 88 % | Top **512** (468 with no tray); title **26/32**, no tracking; description **86 %** + ` · Snapped left/right` | Change |
| P9 | Dots | Top 616, inactive .60, radius 3, shadow | Top **622**, inactive **.5**, square, no shadow | Change |
| P10 | Open motion | No card motion; group 260 ms; frost 280 ms | Overlay 280 ms; cards rise from +24·S at ×0.92 (420 / 300 ms) | Change |
| P11 | Snap tray | — | §4.6, spring reveal, group shift −44 → 0 | New |
| P12 | Snap flow | — | Fly, placement at 360 ms, auto-advance at 420 ms, close at 820 ms, toast | New |
| P13 | Window placement | Focus/restore only (`windows.py:627-656`) | `SetWindowPos` to work-area halves, restore, frame compensation | New (native) |
| P14 | Buttons (knob) | 1 **Cancel** (red), 2 Home, 3 Windows, 4 Switch (`controller.py:979-981`) | 1 **Back** (warm), 2 **Snap left**, 3 **Snap right**, 4 Switch | Change (controller) |
| P15 | Back toast | `Cancelled · focus restored` (`carousel_render.py:109`) | `Back · focus restored`, only with no snap | Change |
| P16 | Switch exit | Grow 1.35 and fade, toast `{App} · {Title}` | Toast same; the prototype omits the grow (04 keeps it) | Same |
| P17 | End bump | Keyboard and wheel only | Also at knob ends (via ALIVE `lim`) | Change |
| P18 | Opening | F24 from button 3 in **any** mode (`runtime.py:1385-1390`) | **Button 4, Home only** | Change (firmware HID + runtime) |
| P19 | Focus | Activatable host (deviation 6) | "Never take focus" | Decide (keep deviation 6) |
| P20 | Entry index | MRU index 1 (`windows.py:308-318`) | Same | Same |
| P21 | Floating knob | Suppressed, reason `carousel` | Unspecified | Same |

### 9.2 Toasts
| # | Area | Current | Master | Kind |
|---|---|---|---|---|
| T1 | Position | Stage top 320 | **Top 588** (bottom centre) | Change |
| T2 | Tint | (30,30,32,.55) | **(24,24,26,.62)** | Change |
| T3 | Hold | 1.5 s | **1.8 s** | Change |
| T4 | Owner | The picker's exit only | A service used by knob actions and every overlay exit | New |
| T5 | Copy | 2 strings | 11 strings (§5.2) | New |
| T6 | Suppression | — | Never over an overlay; cleared on open; none for Play/Pause | New |

### 9.3 Music explorer and Up next
| # | Area | Current | Master | Kind |
|---|---|---|---|---|
| X1 | Explorer overlay | — | §2 in full | New |
| X2 | Up next overlay | — | §3 in full | New |
| X3 | Covers | 240 px knob, 480 px scrimmed for the floating knob | **600 px unscrimmed** (or ≥ 340·k), mosaics, 56 px row art, ambient blurs | New |
| X4 | Library sources | Recently Added (paged 10 + More) (`apple_music.py:125`) | Plus **Favourite playlists**, playlist counts and durations, album year and track count | New (API) |
| X5 | Queue read | Counts and a replace-only paged read (`sonos.py:183`, `:308`) | A full queue with metadata, live position and revision | New |
| X6 | Queue writes | Replace the queue (`play_items` `:351`) | **Play next** (insert after current), **jump to track**, **shuffle the remaining tracks** | New |
| X7 | Like | — | Apple Music song rating, heart state per row | New (API; verify) |

### 9.4 Companion surfaces
| # | Area | Current | Master | Kind |
|---|---|---|---|---|
| C1 | Main window | None in the live app; dev window only | Service strip, `Knob is on`, live mirror, Settings, Disconnect, Troubleshooting | Decide |
| C2 | Settings | `Nano_D++ · Setup` with IP, port, button order, keys, presentation, switcher | `Settings`: knob map, room list + manual IP, Apple Music status + Renew, LED brightness (proposed), Launch at sign-in | Decide / Change |
| C3 | Tray menu | Header, status, Show knob, Settings…, Connect/Disconnect, Quit | Header with room and volume sub line, Open Nano_D++, Connect/Disconnect, Quit (`Stops the knob`) | Decide |
| C4 | Tooltip, tray icon files, header text | Match | Match | Same |
| C5 | Theme watch | 2 s poll | `WM_SETTINGCHANGE` | Change (optional) |
| C6 | App icon assets | Byte-identical | — | Same |
| C7 | Recovery cards | None (tray, balloons, knob) | 4 cards | Decide |
| C8 | Floating knob | v4 lights; old layouts | ALIVE engine; new layouts and icon masks; suppression for new overlays | Change + Decide |

---

## 10. Infrastructure: hosting the explorer and Up next on the carousel stack

**Short answer**: the v6 carousel stack can host both overlays with extensions. It already
provides the hard parts: a native, off-Tk-thread, per-monitor-DPI layered-window pipeline with a
captured full-screen frost, `WDA_EXCLUDEFROMCAPTURE`, CSS-exact tweens, DwmFlush pacing,
premultiplied PIL composition and Archivo text with font fallback. README §1 allows PySide6 or
WebView2 only "if Tk can't do the backdrop blur", and the blur is already solved natively.

### 10.1 Reusable as-is
| Piece | Where | Use for the new overlays |
|---|---|---|
| Thread + Win32 skeleton: `CarouselEngine`, `Win32CarouselBackend`, the module WNDPROC thunk, `Mailbox`, `_Log`, `_Status` | `carousel.py:830`, `:1959`, `:1939`, `:549` | One engine thread per overlay kind, or one engine with scene kinds |
| Motion: `CubicBezier`, `EASE_OUT`, `SPRING`, `Tween` (CSS retarget), `ToastMachine` | `carousel.py:104-199`, `:427` | Every transition in §2–§5 (add HEART, `ease` and start delays) |
| Pacing: `Pacer` (DwmFlush, MsgWait fallback) | `carousel.py:476` | Same |
| Capture: `CaptureWorker` + `frost_canvas` + display affinity + `set_capture_exclusions` | `carousel.py:686`; `carousel_render.py:341`; CAROUSEL §5 | The frost for all three |
| Glass window (monitor-sized ULW, constant-alpha fade, `release_retained`) | CAROUSEL §5 and §11 | The frost layer for all three |
| Render: `Layout`/`layout_for`, `Canvas`, `Sprite`, `ShadowCache`, `TextEngine` (Archivo + fallback chain), `_SpriteScaler`, `render_dots`, `render_toast`, premultiplied helpers, `fade_lut` | `carousel_render.py:186-229`, `:441`, `:571`, `:662`, `:926`, `:1433`, `:1280`, `:1350` | Cards, rows, labels, dots, hints, toast |
| Artwork: `apple_artwork_url(size)`, `dominant_rgb` (an exact `dominant()` port), fetch limits | `artwork.py:110`, `:193`, `:48-58` | 600 px covers, list colours |
| Icons: `IconWorker` 128 px masters, `window_labels` | `windows.py:1002`; CAROUSEL §6–§7 | Picker badges and tray slots |
| Tk integration: `_sync_capture_exclusions`, suppression reasons | `ui.py:1517`, `:1211-1256` | New overlay reasons |

### 10.2 What must change or be added
1. **Parametrised frost.** `_frost_small` hard-codes saturate 1.8 and the (18,18,20,.58) tint
   with the 0.88 dim (`carousel_render.py:317-326`). The helpers `_saturate_matrix` and
   `_tint_matrix` (`:301-310`) are already general. Per overlay: σ, saturate, tint and alpha,
   dim (none), sheen (picker).
2. **No host for the explorer and Up next.** They show no DWM thumbnails and never activate, so
   the chrome can be a `LAYER_EX_STYLE` window (`WS_EX_NOACTIVATE`, `carousel.py:1772`).
   Whether it is click-through or click-eating depends on Q12.
3. **Chrome size.** The v6 chrome is the pane plus a margin (stage 54–1226 × 76–668). The
   explorer tabs (top 44) and both hint rows (bottom 680) fall outside it. So the chrome must
   become the full stage (1280 × 720·k = 14.7 MB at k = 2, against about 11 MB today), or be
   split into a static layer (tabs, hints, left column) and a dynamic one.
   `UpdateLayeredWindowIndirect` with `prcDirty` can limit per-frame uploads.
4. **Ambient layer** (new; 600 ms crossfade). Two options:
   - **A.** Two monitor-sized layered windows (frost ⊕ ambient_i), crossfaded by constant alpha
     (no per-frame upload, like today's frost fade). Cost: one 29.5 MB upload per focus change at
     5120 × 1440, and 2 × 29.5 MB retained by DWM while open. That exceeds CAROUSEL §5's 80 MB
     budget once the chrome is added, so it needs a budget decision.
   - **B (spike).** Keep the ambient tiny: blur(90) has no detail, so it can be rendered at
     1/16 scale. Stretch it to the monitor with a **DWM thumbnail** of a small hidden or
     cloaked source window, and use `DWM_TNP_OPACITY` for the crossfade. The GPU scales it and
     the memory is small. Unvalidated: whether a cloaked source still renders a thumbnail.
     Option B could also shrink the v6 frost's upload.
5. **Covers as sprites.** Pre-scaled cover sprites: LANCZOS at rest, BILINEAR while animating
   (`_SpriteScaler`). One mosaic composite per playlist. Per-card shade. New shadow sets for
   `ShadowCache`: explorer `0 40 80 .55` / `0 16 36 .4`, Up next focus `0 20 50 .35`, cover
   `0 40 80 .55`, fly `0 30 70 .45`.
6. **Rows as sprites.** Render each Up next row's text once per k with `TextEngine` (600 / 400
   weights, ellipsis fitting, fallback fonts). Scale around the row's left-middle point per
   frame. Tags and hearts are separate small sprites (the heart pops independently).
7. **Stagger delays.** `Tween.retarget(value, now, duration, curve)` has no delay. Add a start
   offset, or schedule each retarget at `now + 45·a` or `+ 40·a` ms.
8. **Crossfades.** The big Up next cover (420 ms ease) blends two sprites. The ambient is
   item 4.
9. **Toast service.** Lift `ToastMachine`, `render_toast` and the toast window out of the picker
   session (T4), with the new position, tint and hold.
10. **The snap fly and tray slots.**
    - The fly lands on monitor work-area halves, outside today's pane-sized host. Preferred:
      grow the NOREDIRECTIONBITMAP host to `rcMonitor` (it is transparent) and animate the
      **existing thumbnail's** `rcDestination` + opacity. `presenter.rect` must still report the
      card area.
    - Tray slots are two more DWM thumbnails (176 × 110·k). The registration plan
      (`REGISTER_DISTANCE`, `carousel_render.py:83`) must count them.
11. **Window placement** (native, new): §4.9. Run it from the adapter on the Tk thread with
    `SWP_ASYNCWINDOWPOS` and bounded verification, following the existing thread rules
    (CAROUSEL §1).
12. **Performance to measure** (the supervised check, as CAROUSEL §10):
    - the frost pipeline (about 34 ms at 5120 × 1440, CAROUSEL §11) with the new parameters;
    - the chrome compose at stage size with 5 cover sprites and shadows;
    - `glass_upload_ms`, which has still never been measured on hardware (CAROUSEL §11).

### 10.3 Alternatives (for the record)
- **DWM system backdrop** (Acrylic via `DWMWA_SYSTEMBACKDROP_TYPE`): a fixed system recipe, not
  the design's blur, saturate and tint. It also falls back to a flat colour when the window is
  inactive (verify), which rules it out for non-activating overlays.
- **WebView2 / PySide6**: neither can blur live desktop content behind a transparent window, so
  both still need the captured frost as a background image. WebView2 would allow reusing the
  prototype's CSS almost verbatim. The price is a large runtime or packaging dependency, a new
  threading model beside Tk, and re-validating the topmost, affinity and no-activate behaviour
  the native stack already proved. **Recommendation: the native stack.**

---

## 11. Integration touchpoints outside the overlays (desktop code)
1. **Controller** (`controller.py`):
   - New modes `explore` and `queue`, plus the Seek state.
   - The README §4 button map everywhere: Back semantics, hold 600 ms = Home, Windows only from
     Home.
   - New legends and icons (`BUTTON_ICONS` `:38-41` has no expand, clock, list-music,
     list-plus, seek, shuffle, heart, snap or check).
   - Profiles: explorer and Up next use MIDI SKIPPER (20); Seek uses BINARIS BEER (67)
     (README §3; `PROFILES` `:36`).
2. **F24 / Windows entry** (`runtime.py:1385-1390`): today logical button 2's serial edge is
   skipped because F24 is authoritative. In the new grammar logical 2 is Tracks, Play next,
   Seek, Like or Snap right, so it must not be skipped. F24 must come from **button 4 on Home
   only** (a firmware HID mapping change). Switch no longer needs F24 if deviation 6 is kept.
3. **Companion-driven position changes need a knob re-entry.** Absolute device positions are
   authoritative per control id (`controller.py:1-5`). This affects:
   - snap auto-advance (§4.8);
   - the explorer source switch (per-source position and bounds);
   - the shuffle focus jump (`qNow + 1`);
   - opening Up next on `qNow`.

   Each needs an entry with a new position and bounds, and must never restart the haptic
   profile (03).
4. **`lim` events** (ALIVE §3) → the overlay bumps and the End stop LED.
5. **Sonos** (README §8):
   - Play next: `AddURIToQueue` with `EnqueueAsNext=1` after the current track (verify with the
     Apple Music service).
   - Jump to a queue track (`SeekTrackNr`).
   - Seek `REL_TIME` 250 ms after the last detent.
   - Full queue listing (§3.6).
   - Shuffle: the design's semantics (reorder only the tracks after the current one; off
     restores order) are not Sonos `play_mode` shuffle. Sonos does not expose its shuffled
     order, and `sonos.py:163-164` refuses Previous in shuffle modes. The likely route is a
     physical reorder of the remaining tracks (verify).
6. **Apple Music**:
   - Like: `PUT /v1/me/ratings/songs/{id}` (value 1); verify that the desktop's MusicKit grant
     can call it (README §8).
   - Favourite playlists: "favourited or pinned playlists". Verify that an endpoint exists; none
     is used today (`apple_music.py` is read-only browsing).
   - Album year and track count, and playlist song count and duration (possibly an extra
     tracks fetch per playlist).
7. **Time of day**: `clock` in enter frames, and every 10 min (ALIVE §3; README §8).

---

## 12. Open questions and decisions (for the spec owner and the user)
| # | Question | Recommendation |
|---|---|---|
| Q1 | Explorer and Up next **turn timing**: spec 420 ms, no delay, or the prototype's 440 / 420 ms with a 45·a / 40·a ms delay on every turn? | The spec (the delay applies only on open and source switch) |
| Q2 | The explorer's 600 px art against the 680 px card at k = 2 | Fetch `ceil(340·k)` |
| Q3 | Recently Added **paging** (`More`) and prefetch inside the explorer; dot count for long lists | Flatten the loaded pages; prefetch near the end; cap or window the dots |
| Q4 | Recently Added items that are **playlists or songs** in the explorer | Playlists as a mosaic; songs as their album |
| Q5 | Explorer **errors**: auth expired, empty Favourite playlists, unavailable items, partial failure, slow art | Reuse 03's knob copy; do not open the overlay without data; show a `#222` card until art loads |
| Q6 | The playlist mosaic's source (first 4 distinct albums?) and its **ring colour** | First 4 distinct albums in track order; colour = `dominant()` of the first cover |
| Q7 | The playlist **meta format** under 1 h and the singular forms | `{m} min`; `1 song`, `1 track` |
| Q8 | Up next for a queue **not started by the companion** (context unknown) | Album layout only if every track shares one album; the title is that album, or `Sonos queue` |
| Q9 | **Shuffle off** after a Play next: the prototype puts the queued album at the end and tags earlier tracks `Played` | Keep the pre-shuffle order (stored), not the array order |
| Q10 | Like unreachable (API scope) | README §8's fallback: Play next on button 3 |
| Q11 | Picker **sheen** (design 6 %) against CAROUSEL §11 "no sheen"; keep **No background**? | The user decides; the sheen is cheap (fold it into the frost) |
| Q12 | **Mouse** on the explorer and Up next: click-through, click-to-select (desyncs the knob), or click = Back? | Swallow clicks (`MA_NOACTIVATEANDEAT`) and act only on the centre card, like the picker's deviation 5 |
| Q13 | **Toasts over overlays**: the prototype fires Like and Shuffle toasts while Up next is open; README forbids it. And the monitor for knob-only toasts | No toast while open (the heart pop and the `Shuffle on` / `In order` line carry the feedback); knob-only toasts on the foreground window's monitor |
| Q14 | Snap: **when** does the origin move to the other half (at the first snap, as the prototype's desktop shows, or only on close)? What gets focus after Back with one side snapped? | Move the origin on close (Back) only; then restore focus to the origin |
| Q15 | Snap **failures** (UIPI, minimum width, hung target): what does the user see? | Head shake LED + the knob meta `Couldn't move {App}`; the slot stays empty |
| Q16 | **Main window and recovery cards** against the standing "no main window" decision | Keep the floating-knob-only app; optionally add the service strip to the top of Settings |
| Q17 | Settings **knob map** (old grammar in CC), Sonos room list, LED brightness (proposed), Launch at sign-in | Update to README §4 if shown; LED brightness only if ALIVE's `led_drive` gets a UI |
| Q18 | **Floating knob** while the explorer or Up next is open: hide (like `carousel`) or show? | Hide (new suppression reasons), consistent with the picker |
| Q19 | The "**Snap group**" claim | Treat it as unverified; do not mention it in copy |
| Q20 | The picker **open motion**: the prototype's card rise, or v6's in-place fade? | The prototype (it is primary for motion) |

---

## Appendix A — Icon paths used by the desktop overlays (B&S:L395-L405)
Lucide-style, 24 grid. The constant names are misleading; the meanings are:

| Constant | Meaning | Path |
|---|---|---|
| `I.back` | Back (chevron-left) | `M15 18l-6-6 6-6` |
| `I.clock` | Recently Added (tab 2) | `M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0` |
| `I.queue` | **list-music**, Favourite playlists (tab 3) | `M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3` |
| `I.next` | **list-plus**, Play next | `M11 12H3M16 6H3M16 18H3M18 9v6M21 12h-6` |
| `I.tracks` | **skip-forward**, Skip | `M5 5v14l9-7zM18 5v14` |
| `I.prev` | skip-back | `M19 5v14l-9-7zM6 5v14` |
| `I.list` | Tracks (mode) | `M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01` |
| `I.note` | Browse music | `M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z` |
| `I.win` | Windows | `M3 5h18v14H3zM3 9h18` |
| `I.expand` | Open on screen | `M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7` |
| `I.seek` | Seek (handle at x 15.5 / 24, about 65 %) | `M3 12h9.5M18.5 12H21M15.5 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z` |
| `I.shuffle` | Shuffle (also the Up next status line, L166) | `M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22M18 2l4 4-4 4M2 6h1.9c1.5 0 2.9.9 3.6 2.2M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8M18 14l4 4-4 4` |
| `I.heart` | Like (row heart filled `#ff2a5a`) | `M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z` |
| `I.rect` + `HALF.left` / `HALF.right` | Snap left / right: outline + filled half | `M3 5h18v14H3z` + `M3 5h9v14H3z` / `M12 5h9v14h-9z` |
| `I.check` | Switch | `M20 6L9 17l-5-5` |
| `I.play` / `I.pause` | Play / Pause | `M7 4.5v15l12-7.5z` / `M8 5v14M16 5v14` |

Stroke widths: LCD footer 2.3 at 20 px; tabs and chip 2 at 18 and 16 px; the empty tray glyph
**1.8** at 34 px; round caps and joins, except the tray and chip glyphs, which use the SVG
defaults (B&S:L53, L75).

## Appendix B — Prototype-only elements (do not build)
- The simulated desktop windows, their 460 ms move animation and the 48 px taskbar
  (B&S:L25-L41, L884-L894). Real windows move instantly under the overlay.
- The right-hand legend panel and `modeName` labels (B&S:L263-L272, L943-L989), for example
  `Turn: choose an album`. They document the button meanings and could serve as accessibility
  labels.
- The "Browse music icon · options" gallery (B&S:L277-L345). Music notes were chosen.
- Sample data: `ALB`, `PL`, `TR`, `W`, `durOf` and the hard-coded colours (B&S:L408-L444,
  L605-L617).
