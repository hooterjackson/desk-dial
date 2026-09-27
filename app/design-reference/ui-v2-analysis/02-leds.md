# UI V2 analysis 02: LED additions of the master design, relative to ALIVE.md

Read-only extraction, 2026-09-25. This file covers only the LEDs (ring and button backlights, on the knob and the desktop floating knob). Screens, overlays, icons and haptics are covered by the other analyses.

---

## 0. Sources, citation keys, method

| Key | File |
|---|---|
| **R** | `design_handoff_nano_d_master/README.md` |
| **S1** | `design_handoff_nano_d_master/specs/01-FEATURES-explorers-snap-seek.md` |
| **S2** | `design_handoff_nano_d_master/specs/02-LED-choreography.md` |
| **S3** | `design_handoff_nano_d_master/specs/03-SCREEN-and-state.md` |
| **BS** | `design_handoff_nano_d_master/prototypes/Browse and Snap.dc.html` (primary prototype) |
| **RC** | `design_handoff_nano_d_master/prototypes/Ring Choreography v2.dc.html` |
| **KM** | `design_handoff_nano_d_master/prototypes/knob-model.js` |
| **A** | `firmware/ALIVE.md` |
| **V4** | `firmware/PRESENTATION_V4.md` |
| **AL** | `app/control_center/alive_lights.py`. It was being edited while this was written, so it's cited by symbol name, not by line. |

Citations are `KEY:line`. All design paths are under `app/design-reference/`.

**Identity check** (SHA-256, first 12 hex digits). S2 is byte-identical to `design_handoff_led_choreography/README.md` (`24D6B620ED0B`). RC, KM, `Knob Face.dc.html` and `support.js` are byte-identical to the copies A was written against (`23221A390496`, `28661EFD992E`, `6227E9F40827`, `8FE7DF74405F`). So A's design sources and oracle inputs have not changed. Every LED addition in the master comes from four places:
- **R §6** (R:128–176);
- **S1** §2 (button LEDs, S1:89–100), §4 (ring and moments, S1:131–158), §4b (Seek, S1:162–168) and §6 (Play next and Like, S1:221–222);
- **the BS logic class:** `renderVals()` (BS:877–1097, ring and buttons at BS:938–1015), `draw()` (BS:485–579), and the triggers in the handlers (BS:580–864).

`Window Carousel.dc.html` and `specs/04` have no LED content. `Nano_D Control Center.dc.html` is history (R:30). Its "LED brightness Dim/Standard/Bright" block is marked *Proposed* (Control Center:723–727) and predates the master.

**Precedence** (R:15–21): R > S1 > S2 > S3. R:28–29 makes BS the reference for *behaviour* and RC the reference for *LED recipes and timing*. So for **targets and triggers**, S1 + BS beat S2 + KM `finishAlive()`. For **recipe math**, RC holds unless BS adds or changes a recipe.

**BS dead code, not part of the design:**
- `renderVals()` returns `segs` (BS:1016–1025), a DOM ring with a `wash` override that forces alpha ≥ 0.85. It also returns `keys[].sh/.strip` (BS:987).
- The template binds neither. It draws the ring and buttons only on the canvas (BS:205, via `draw()`) and binds only `k.on/aria/x/tf` (BS:259–261).
- So the `s.wash` state set at BS:661, 676, 772 and 850 is dead preview state. **Don't implement it.**
- `shufflePlay()` (BS:785–792) has no call site.

---

## 1. Summary

1. **Three new moments:**
   - **half-wash** (`half`, Snap left/right);
   - **pink bloom** (`bloom` with a colour, Like);
   - **scatter** (`scatter`, Shuffle).
2. **Existing recipes get new triggers:**
   - `sweep` at segment 0, clockwise, for **Play next**;
   - `wash` for **Explorer Play**;
   - `reveal` for Explorer, Up next and **Seek** entry/exit.
3. **Two new ring patterns:**
   - **Seek lap:** played 0.62, ticks every 5th segment at 0.30, head 1.0.
   - **Up next list:** played 0.14, now playing 0.70, upcoming 0.45, cursor 1.0, in album colours.
4. **Two new families:** Explorer and Up next. They get the list geometry, the ambient tint and reveals.
5. **New button states:**
   - pair/toggle **on** WARM 1.0 and **off** WARM 0.30;
   - **Seek lit** 1.0;
   - **liked heart** PINK 1.0;
   - **snap assigned** in the app colour at 1.0;
   - plus a transient 0.6 tint on button 2 or 3 during the half-wash.
6. **Volume:**
   - The master draws the **amber/red body at 0.62**, like warm. A gives it 1.0 as a semantic class-2 colour.
   - The master gates amber/red on the **value** (≥ 80 / ≥ 90) as well as the position. This differs from v4 only at 79 % and 89 %.
7. **Ring rule** (R:145, S1:140): no extra markers and no warm ticks in a coloured list. Three v4/A items break it:
   - the Recent **More double landmark**;
   - the **Recent unavailable cursor** in W;
   - the **Recent pending pulse** in W.
8. **Windows button 1 is now Back** (warm nav 0.70). It is no longer Cancel (red).
9. **Paused Play:** the design contradicts itself. R §6 and S1:100 say green breath. R:70, S1:47 and R:234 say "only button 4 is ever green". BS actually renders a **warm** breathing button.
10. **The v4/A wire can't express most of this yet.** It needs a Seek ring style, the Up next now-playing index, per-button on/off/colour, and feedback "moments" (Play next, Shuffle, Like, Snap). Without them, A would show a green bloom or a wash for every one of these confirmations.
11. **Scatter** is not random. It is an arithmetic progression round the ring, driven by one `Math.random()` seed, and 17.6 % of seeds put two sparks within 1 segment of each other. The ports need a deterministic seed.
12. **Side finding (not from the master).** A §2's design-space WARM/AMBER were derived with pure gamma 2.2. Through A §9's sRGB EOTF they output **#FF8224 / #FF390B**, not the user's **#FF8424 / #FF3A0A**.

---

## 2. Palette

### 2.1 New colours

| Role | Design value (0–255) | Source | LED output at full through A §9.1 (sRGB EOTF) | Notes |
|---|---|---|---|---|
| **PINK** (Like) | **255,40,90** | R:142; S1:97, 155; BS:661 (bloom), BS:957 (button) | 255, 5.41, 26.07 ≈ **#FF051A** | Semantic, like GREEN. **It must never go through `sat()`:** `sat(255,40,90)` = 255,11,68. |
| PINK spark | `mix(PINK, white, 0.3)` = **255, 104.5, 139.5** | BS:542 | — | Derived the same way as the green spark (RC:349) |
| Snap button (side assigned) | that app's colour | R:155; S1:98; BS:974, 985 | — | Production applies `sat()`; R:143 says colours are "re-saturated". BS uses the raw sample colours. |
| Half-wash | that app's colour | S1:154; BS:849 | — | Same |
| Up next landmarks | each track's **album** colour | R:146; S1:136; BS:1006 | — | Same |
| LCD heart glyph | `#ff2a5a` | BS:183 | — | LCD only, not LED |

There's **no user decision** on PINK yet. The user tuned WARM, AMBER and RED on the hardware; PINK needs the same hands-on check (see §10).

BS's `WARM = [255,164,84]` (BS:406) is the design's **warm marker**, the same as RC `MODEL_WARM` (RC:108) and KM `finishAlive` `WARM` (KM:497).
- It means role WARM, never that literal colour.
- `draw()` replaces it with the time-of-day `WM` (BS:496, 511). The exception is `bound`, which gets it literally (§6.6).
- The sample colours are raw approximations. Production computes `dominant()` on the desktop and re-saturates (R:143, R:229).

### 2.2 User decisions that override the design (the master repeats the design values)

| Master says | Where | User decision (stands) | In A |
|---|---|---|---|
| Warm follows the time of day, about 3000 K at midday and 1900 K at night | R:131; S2 §6; BS:487 (`warmAt()`) | WARM is fixed at LED **#FF8424** all day. Time of day only dims the resting brightness. | §2 WARM row, §8.3, D1 |
| Amber 255,118,0 for volume 80–90 % and offline marks | R:140; S2:55; BS:997 | LED **#FF3A0A** | §2, D2 |
| Red 255,24,0 for volume ≥ 90 % and failure | R:139; S2:54; BS:997 | LED **#FF0000** | §2, D2 |
| Offline: 12 amber marks, pulsing 0.15–0.5 while reconnecting | S2:81 | Drain, then amber marks. Native profile lights take over on native input. | §5.2, §8.1, D5 |
| The companion sends the time on connect and every 10 min | R:231 | Kept; it only drives resting brightness | §3 `clock` |
| — | — | The desktop floating knob runs the same choreography | §10.3. The new moments must be in AL too. |
| — | — | One combined release: firmware cc5.4 + desktop v7, with the LEDs and the whole master | §1 (see §9 for the capability version) |

The user's volume rule ("80–90 % → amber, ≥ 90 % → red") is a statement about the **value**. The master's value gate (§7, F2) matches it better than v4's position-only rule.

### 2.3 Side finding: A §2's constants don't reproduce the user's LED colours through A §9

This was computed exactly with A §9.1's EOTF (`L = ((e+0.055)/1.055)^2.4`) at drive 255:

| A constant | Output through the sRGB EOTF | A's column says | Pure gamma 2.2 would give | sRGB inverse of the user's pick |
|---|---|---|---|---|
| WARM 255,189,105 | 255, 129.76, 36.02 = **#FF8224** | #FF8424 | 255, 131.9, 36.2 = #FF8424 | 255, **190.45**, 104.97 |
| AMBER 255,130,59 | 255, 56.92, 11.15 = **#FF390B** | #FF3A0A | #FF3A0A | 255, **131.13, 55.76** → integers 255,131,56 give exactly #FF3A0A |

- The constants were derived with gamma 2.2. D3 claims "the palette is derived with the same curve", which is not what these numbers show.
- The error is ≤ 2.2 counts at full scale, and ≤ 1.3 counts at the default drive of 150.
- With integers, G = 132 can't be hit: 190 gives 131.26 and 191 gives 132.86. So store 190.45, or accept #FF8324.
- This isn't a master item. It belongs in the A §2 / D3 fix list (§9).

---

## 3. Levels

### 3.1 Buttons (R:147–155, S1:89–100, BS:983–988)

```js
const lvl = t => t === 'go' ? [GREEN, 1] : t === 'on' ? [WARM, 1] : t === 'off' ? [WARM, 0.3] : t === 'dim' ? [WARM, 0.14] : [WARM, 0.7];
const keys = foot.map((f, i) => { const [c0, a0] = lvl(f.t), c = f.c || c0, a = f.c ? 1 : a0; return { _t: { c, a }, … } });   // BS:983–988
```

The resting rule (BS:507) is `ta = asleep ? (b.a >= 0.5 ? 0.12 : 0.04) * br : b.a`, where `br` already includes `tod.b` (BS:489).

| State | BS tone | Colour | Awake | Resting | A §5.3 today |
|---|---|---|---|---|---|
| Nav | `nav` | WARM | 0.70 | 0.12 | nav 0.70 / 0.12 (same) |
| Disabled | `dim` | WARM | 0.14 | 0.04 | dim 0.14 / 0.04 (same) |
| Action | `go` | GREEN | 1.00 | 0.12 (warm) | go 1.0 / 0.12 (same) |
| **Pair or toggle active** (explorer tab, Shuffle on, Seek lit) | `on` | WARM | **1.00** | 0.12 | **new** |
| **Pair or toggle inactive** (explorer tab, Shuffle off) | `off` | WARM | **0.30** | **0.04** (because 0.30 < 0.5) | **new**. A's "0.04 if dim, else 0.12" would give it 0.12. |
| **Liked heart** | `on` with `c` | PINK | **1.00** | 0.12 (warm) | **new** |
| **Snap button, side assigned** | `on` with `c` | app colour | **1.00** | 0.12 (warm) | **new** |
| Cancel | — | RED | — | — | A keeps `stop`, but no master mode uses it (F8) |
| Paused Play (Home, slot 0) | `nav` × breath | **WARM** in BS | 0.70 × (0.55…1.0) | 0.12 × breath | A has GREEN 1.0 × breath (F4) |

### 3.2 Ring (S1 §4 S1:131–140, R:145–146, BS:991–1014)

The resting rule (BS:497) is `ta = asleep ? (r.a >= 0.99 ? 0.16 : r.a >= 0.5 ? 0.1 : 0.05) * br : r.a`. It gives the same values as A's class column for the existing classes.

| Pattern | Awake, BS | A class | A awake today | Resting (BS) |
|---|---|---|---|---|
| List landmark, coloured item | 0.45 | 1, semantic | 0.45 (same) | 0.05 |
| List landmark, warm item | 0.30 | 1, warm | 0.30 (same) | 0.05 |
| List cursor | 1.00 | 3 | 1.00 (same) | 0.16 |
| Volume bound marks (35, 25) | 0.30 | 1, warm | 0.30 (same) | 0.05 |
| Volume body, warm | 0.62 | 2, warm | 0.62 (same) | 0.10 |
| **Volume body, amber/red** | **0.62** | 2, semantic | **1.00 (conflict, F1)** | 0.10 |
| Volume odd shoulder | not modelled | S | 0.81 warm / **1.00** semantic (F3) | 0.13 |
| Volume endpoint | 1.00 | 3 | 1.00 (same) | 0.16 |
| Tracks landmarks / selected pair / neutral selected | 0.30 / 1.00 / 0.62 | 1 / 3 / 2 | same | 0.05 / 0.16 / 0.10 |
| **Seek**: played / 5th-segment ticks / head | 0.62 / 0.30 / 1.00 | new pattern on classes 2 / 1 / 3 | — | 0.10 / 0.05 / 0.16 |
| **Up next**: played | **0.14** | **new class P** | — | 0.05 |
| **Up next**: now playing | **0.70** | **new class N** | — | 0.10 |
| **Up next**: upcoming | **0.45 in any colour** | class 1, but ignores the warm/semantic split | — | 0.05 |
| Up next: cursor | 1.00 | 3 | — | 0.16 |

---

## 4. Per-mode targets, exactly as BS computes them

- **Writes:** `put(i, c, a)` overwrites `ring[mod60(i)] = {c, a}` (BS:993).
- **Lit:** a cell is lit if and only if `a > 0`. The draw loop tests `r && r.a` (BS:495) and the tint tests `!(ring[i] && ring[i].a)` (BS:524).
- **Cursor:** `_cursor` is the **highest index with `a >= 1`**, or 0 if there's none (BS:1015). A takes the cursor from the geometry instead (F9).
- **List slots:** `(i − c0)·3` with `c0 = floor((n − 1)/2)` (BS:1006, 1011). This is the same as V4 §5.3 `slot(j)`.
- **Button targets:** `_btns = keys[]._t` (BS:1015).

### 4.1 Home (BS:994–998; footer BS:944)
```js
const n = Math.round(s.vol / 2);
put(35, WARM, 0.3); put(25, WARM, 0.3);
for (let k = 0; k <= n; k++) put(35 + k, s.vol >= 90 && k / 50 >= 0.9 ? [255, 24, 0] : s.vol >= 80 && k / 50 >= 0.8 ? [255, 118, 0] : WARM, 0.62);
const e = 35 + n; put(e, ring[e % 60].c, 1);
```
- **Arc length:** `n = Math.round(v/2)`, which is `(v+1) div 2` for integers, the same as V4 `n`.
- **Colour of segment k:**
  - RED if `v ≥ 90 && k ≥ 45`;
  - else AMBER if `v ≥ 80 && k ≥ 40`;
  - else WARM.
  - `k/50 ≥ 0.9` equals `k ≥ 45` exactly in IEEE doubles, and `k/50 ≥ 0.8` equals `k ≥ 40`.
- **Segments:**
  - 35 gets WARM 0.30, then the body at k = 0 overwrites it.
  - 25 stays WARM 0.30 unless `n = 50` (v ≥ 99).
  - `35+k` for k = 0…n−1 gets `colour(k)` at 0.62.
  - The endpoint `35+n` gets `colour(n)` at 1.0 and is the cursor.
- **Heat:** `mode == home && !asleep && vol ≥ 90` (BS:491). The ember factor applies to cells whose colour starts 255,24 (BS:498).
- **Buttons:**
  1. Play or Pause (icon by state): nav 0.70, breathing while paused (BS:504, 508);
  2. Browse music: nav 0.70;
  3. Tracks: nav 0.70;
  4. Windows: nav 0.70.
- **Not modelled in BS:** the pending span, the odd shoulder, external (blue) and the Sonos-off notice.

| Volume | n | BS ring | A / V4 ring (confirmed = displayed) |
|---|---|---|---|
| 54 | 27 | Segments 35–59 and 0–1 WARM 0.62; 2 WARM 1.0; 25 WARM 0.30 | Same |
| **79** | 40 | Endpoint at 15 is **WARM** 1.0 | Endpoint at 15 is **AMBER** 1.0; shoulder at 14 is WARM 0.81 |
| 85 | 43 | k 40–42 (segments 15–17) AMBER **0.62**; endpoint 18 AMBER 1.0 | 15–16 AMBER **1.0** (class 2 semantic); shoulder 17 AMBER **1.0**; 18 AMBER 1.0 |
| **89** | 45 | k 40–44 (15–19) AMBER 0.62; endpoint 20 **AMBER** 1.0; no embers | Endpoint 20 **RED** 1.0 (volRed); no embers, because heat needs v ≥ 90 |
| 95 | 48 | 15–19 AMBER 0.62; 20–22 RED 0.62; endpoint 23 RED 1.0; embers on 20–23 | 15–19 AMBER 1.0; 20–21 RED 1.0; shoulder 22 RED 1.0; 23 RED 1.0; embers on 20–23 |
| 100 | 50 | 20–24 RED 0.62; endpoint 25 RED 1.0 | 20–24 RED 1.0; 25 RED 1.0 |

### 4.2 Recently Added on the knob (BS:1009–1014; footer BS:963)
```js
const items = s.mode === 'windows' ? W : s.mode === 'explore' ? L : ALB, cur = s.mode === 'windows' ? s.sel : s.mode === 'explore' ? xi : s.rIdx;
const c0 = Math.floor((items.length - 1) / 2);
items.forEach((it, i) => put((i - c0) * 3, it.c, it.c === WARM ? 0.3 : 0.45));
put((cur - c0) * 3, items[cur].c, 1);
```
- **Landmarks:** the 9 albums (`c0 = 4`) sit at segments **48, 51, 54, 57, 0, 3, 6, 9, 12**.
- **Levels:** each album's colour at 0.45 (0.30 when the colour is the warm marker); the cursor in its colour at 1.0.
- **Sample colours** (BS:409–417): 120,150,190 · 255,40,90 · 255,120,30 · 60,170,255 · 160,90,255 · 255,190,60 · 255,40,20 · 255,150,40 · 40,120,255.
- **Tint:** on (§6.8).
- **Buttons:**
  1. Back: nav 0.70;
  2. Open on screen: nav 0.70;
  3. **Play next**: nav 0.70;
  4. **Play**: GREEN 1.0.
- **Not modelled in BS:** paging and More, unavailable items, loading, pending, the auth and empty states. V4 §5.3 covers them.

### 4.3 Music explorer, on screen (same code; footer BS:968)
- **Recently Added tab:** identical to §4.2, with the cursor at `xIdx.recent`.
- **Favourite playlists tab:** 6 items (`c0 = 2`) at segments **54, 57, 0, 3, 6, 9**. Colours (BS:420–425): 255,60,110 · 255,190,90 · 255,150,40 · 90,150,255 · 200,90,255 · 80,200,170.
- **Levels:** 0.45 / 0.30 / cursor 1.0, as in §4.2. **Tint:** on.
- **Buttons:**
  1. Back: nav 0.70;
  2. **Recently Added**: `on` 1.0 if that tab is active, else `off` 0.30;
  3. **Favourite playlists**: `on` or `off`, the other way round;
  4. **Play**: GREEN 1.0.
- **Tab switch** (`setSrc`, BS:805–809): the mode stays `explore`, so there's **no reveal**. The landmarks just damp to the new list.

### 4.4 Tracks (BS:1003–1004; footer BS:951)
```js
[52, 53].forEach(i => put(i, WARM, s.tPos === -1 ? 1 : 0.3)); put(0, WARM, s.tPos === 0 ? 0.62 : 0.3); [7, 8].forEach(i => put(i, WARM, s.tPos === 1 ? 1 : 0.3));
```
- **Ring:** identical to V4 §5.4 and A. **Tracks levels don't contradict A.**
- **Cursor:**
  - Prev: **53** in BS (the "last `a ≥ 1`" rule). V4 and KM:470 use **52** (F9).
  - Neutral: 0.
  - Next: 8.
- **No tint.**
- **Buttons:**
  1. Back: nav 0.70;
  2. Open on screen: nav 0.70;
  3. **Seek**: nav 0.70;
  4. **Skip**: GREEN 1.0 when `tPos ≠ 0` (icon prev for −1, skip-forward for +1), else dim 0.14.
- **Not modelled in BS:** Prev unavailable (V4 bit 0) and pending.

### 4.5 Seek (Tracks, button 3) (BS:999–1002; footer BS:951)
```js
const D = durOf(ct), n = Math.min(59, Math.floor(s.pos / D * 60));
for (let k = 0; k < 60; k++) put(k, WARM, k < n ? 0.62 : 0.3 * (k % 5 === 0 ? 1 : 0));
put(n, WARM, 1);
```
- **Ring:** the song is one lap from 12 o'clock, clockwise.
  - The head is `n = min(59, floor(pos/D·60))`, with pos and D in seconds.
  - Segments `k < n` are played: WARM 0.62.
  - Segments `k > n` are unplayed: WARM 0.30 when `k mod 5 = 0`, otherwise **unlit** (the entry exists with `a = 0`).
  - The head is WARM 1.0 and is the cursor. Everything is warm (S1:165).
- **Example:** pos 74 s of D 300 s gives n = 14. Segments 0–13 are at 0.62, 14 is at 1.0, and 15, 20, 25, …, 55 are at 0.30.
- **Buttons:**
  1. Back: nav 0.70;
  2. Open on screen: nav 0.70;
  3. **Seek**: `on` 1.0;
  4. Skip: dim 0.14, with the skip-forward icon because `tPos` is reset to 0.
- **Turning:** the position moves ±5 s, clamped to [0, D − 1] (BS:712). A clamped turn plays `bound` (BS:714); S1:166 says the End stop plays at 0:00 and at the end.
- **Reveal:** on enter and exit (BS:667) and on the 3 s idle exit (BS:664), even though the mode stays `tracks`.
- The durations are sample data (`durOf`, BS:444).
- With 5 s per detent and D/60 s per segment, many detents don't move the head. BS then fires `bound` through `componentDidUpdate` (BS:584). A's D4 already prevents this.

### 4.6 Up next, on screen (BS:1005–1008; footer BS:957)
```js
const n = s.qOrder.length, c0 = Math.floor((n - 1) / 2), col = k => ALB[Q[s.qOrder[k]].al].c;
for (let k = 0; k < n; k++) put((k - c0) * 3, col(k), k < s.qNow ? 0.14 : k === s.qNow ? 0.7 : 0.45);
put((s.qSel - c0) * 3, col(s.qSel), 1);
```
- **Entries:** k is the position in play order, after any shuffle. The colour is **the track's album colour**; a playlist mixes colours, and Play-next rows keep their own album's colour.
- **Levels:**
  - played (`k < qNow`): **0.14**;
  - now playing: **0.70**;
  - upcoming: **0.45**, with **no warm check** (other lists use 0.30 for warm items);
  - cursor: 1.0, which hides the 0.70 when the cursor is on the playing track.
- **Example (BS's initial state, BS:595–601):** Hounds of Love, 12 tracks, colour 160,90,255, `qNow = qSel = 4`, so `c0 = 5`.
  - k 0–3 (segments 45, 48, 51, 54): 0.14;
  - k 4 (segment 57): the cursor, 1.0;
  - k 5–11 (segments 0, 3, …, 18): 0.45.
- **Tint:** on.
- **Buttons:**
  1. Back: nav 0.70;
  2. **Shuffle**: `on` 1.0 or `off` 0.30;
  3. **Like**: PINK 1.0 if liked, else nav 0.70;
  4. **Play**: GREEN 1.0.
- BS applies **no window** to long lists. From 21 entries, slots collide: with n = 24, both k = 0 and k = 20 land on segment 27. Keep V4's 20-entry window rule (V4:116, V4:326).

### 4.7 Windows, on screen (the list code in §4.2; footer BS:973–974)
- **Landmarks:** the 7 windows (`c0 = 3`) sit at segments **51, 54, 57, 0, 3, 6, 9**.
- **Sample colours** (BS:609–615): Chrome 255,200,40 · Claude 255,110,60 · Slack 230,50,200 · **ChatGPT is the warm marker (0.30)** · Chrome · Bambu 0,230,90 · Explorer 255,190,60.
- **Tint:** on, unless the cursor item is warm.
- **Buttons:**
  1. **Back** (restores focus): nav 0.70;
  2. **Snap left**: that app's colour at 1.0 if the left side is assigned, else nav 0.70;
  3. **Snap right**: the same for the right side;
  4. **Switch**: GREEN 1.0.
- Unassigned snap buttons are **nav 0.70, not off 0.30**, even though R:68–69 and S1:45–46 call buttons 2 and 3 "a pair" on screen.
- **Snapped windows are not marked on the ring.** Only their cards get a chip (BS:907).
- **Not modelled in BS:** closed, pending and failed.
- **There is no Cancel button** (F8).

---

## 5. `draw()` diff: RC:267–396 against BS:485–579

| RC | BS | Status | Detail |
|---|---|---|---|
| 268–273 | 486–491 | changed | **Time of day:** RC's `hour()` rounds to half hours (RC:185). BS uses continuous `getHours() + getMinutes()/60` (BS:487), which matches A D18.<br>**Asleep:** RC uses `v.ledSleep` (KM:498: asleep and no flash, no pending, connected). BS uses `this.asleep`, a plain 5000 ms timer from the last touch (BS:476–479), with no pending, flash or external holds. A §6.1 stays.<br>**Breath:** RC has `restK = asleep ? tod.b : 1` and `br = asleep ? 1+0.4·sin(t/5200·τ) : off ? 0.6+0.4·sin(t/2600·τ) : 1` (RC:271–272). BS folds them together: `br = asleep ? (1 + 0.4·sin(t/5200·τ))·tod.b : 1` (BS:489), with no offline breath.<br>**Warm test:** by identity on 255,164,84 (BS:490).<br>**Heat:** same (RC:273, BS:491). |
| 274–286 ring damping | 492–503 | equivalent | Lit test on `r.a` instead of `r.l`. Colour is `WM` when asleep or warm, else `c/255`. Resting alpha comes from awake-alpha thresholds (BS:497), not from finishAlive's class table (KM:501, 505). Ember test on colour 255,24 (BS:498). τ and the colour snap are identical. |
| 287–296 buttons | 504–513 | **changed** | `pausedPlay`: RC requires Home, awake and a **green** button 0 (RC:287). BS requires Home, not playing and awake (BS:504), and applies it to a **warm nav** button (F4). Resting alpha from thresholds (BS:507). No `bm` mask. The colour always damps at τ 70. |
| 298–304 masks and helpers | 514–520 | same | `bm` and `lcd` are dropped because BS has no boot or down. `add`, `addG`, `addB` and `comet` are identical. |
| 306 Working comet | — | not modelled | BS has no pending state. A §8.4.1 is unchanged. |
| 308–311 tint | 521–524 | **changed** | Families: RC tints windows and recent (RC:308). BS tints **recent, explore, queue and windows** (BS:521). The colour is the raw `c/255` (BS:522); production uses `sat()`. τ 220 and +0.06 are unchanged. |
| 313–316 song hand | 525 | same | Same fake 214 s lap; no `conn` check. A §8.4.3 is unchanged. |
| 318–324 effect loop | 526–530 | same | Duck applies to every FG effect (BS's FG list has no boot or down). |
| 326–344 boot, down | — | not in BS | Unchanged in A |
| 345 wake | 532 | identical | |
| 346 tick | 533 | identical | |
| 347 bound | 534 | changed | `const c = e.c \|\| WM` fallback (§6.6) |
| 348 pending | — | not in BS | Design-only in A too |
| 349 bloom | 542 | **changed** | Colour parameter plus the matching spark (§6.2) |
| 350 fail | — | not in BS | Unchanged in A |
| 351 sweep | 539 | identical | New trigger (§6.4) |
| 352 fill / 353 drain | 537 / 538 | identical | `e.n = Math.round(vol/2)` (BS:471) |
| 354 shimmer | — | not in BS | Unchanged in A |
| 355 wash | 540 | identical math | The colour arrives as 0–255 and the recipe divides it. New triggers (§6.5). |
| 356 reveal | 535 | identical | New triggers (§6.7) |
| 357 press | 536 | identical | |
| — | **541 `half`** | **new** | §6.1 |
| — | **543 `scatter`** | **new** | §6.3 |
| 362 LCD fade | — | removed | A D6 already omits it |
| 364–395 compose | 547–578 | same | No `glow` prop (it's 1) and no `bm`. The +2 px press offset (BS:570) is visual only. Tone map (BS:553) is identical. |
| `play()` 226–237 | 469–475 | changed | **`DUR`** (BS:393) adds `half: 900` and `scatter: 700`, and drops boot, down, fail, shimmer and pending. **`FG`** (BS:394) is fill, drain, sweep, wash, **half**, bloom, **scatter**. **Default `at`:** RC uses `v.cursor`; BS uses `this._cursor` (the last cell with `a ≥ 1`). **Replacement:** BS replaces any non-FG type except tick and press, which for its types is exactly wake, reveal and bound (same as RC:234). No queue cap in either; A D12 keeps 8. |

---

## 6. New and changed recipes

### 6.1 `half`, the half-wash for Snap: **new** (BS:541; DUR 900 at BS:393; FG at BS:394)
```js
case 'half': { const c = e.c.map(x => x / 255), fade = ms < 380 ? 1 : 1 - eo((ms - 380) / 520);
  for (let k = 1; k < 30; k++) { const i = e.side === 'left' ? 60 - k : k, d = cl(ms / 300) * 30;
    if (Math.abs(k - 15) <= d / 2 + 0.5) A(i, c, 0.75 * fade); }
  addB(e.side === 'left' ? 1 : 2, c, 0.6 * fade); break; }
```
- **Parameters:** `side` is `'left'` or `'right'`; `c` is the app colour, 0–255 (sat()'d in production). `at` is unused.
- **Segments:** right is `i = k` (1–29); left is `i = 60 − k` (**59 down to 31**). Segments 0 and 30 are never lit. This matches S1:154 ("31–59 left, 1–29 right").
- **Growth:** `d = cl(ms/300)·30`, and a segment is lit when `|k − 15| ≤ d/2 + 0.5`. It grows from the middle of each half, segment 15 (3 o'clock) or 45 (9 o'clock). The segment at distance j lights at `ms ≥ 20j − 10`:

  | j | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
  | lights at (ms) | 0 | 10 | 30 | 50 | 70 | 90 | 110 | 130 | 150 | 170 | 190 | 210 | 230 | 250 | 270 |

  The edge is hard, with no gaussian. The half is full at 270 ms; S1 says "over 300 ms".
- **Alpha:** `0.75·fade·amp` per lit segment (`A` applies `amp`).
  - `fade = 1` until 380 ms, then `1 − eo((ms − 380)/520)`.
  - That's 0.4552 at 500 ms, 0.1920 at 600, 0.0569 at 700, 0.0071 at 800 and 0 at 900.
- **Base:** no dim of its own (the wash has `m *= 1 − 0.55·fade`). Only the FG duck `0.35·sin(π·u)·amp` applies.
- **Button:** `addB(slot, c, 0.6·fade)`, where left is slot 1 (button 2) and right is slot 2 (button 3). **This isn't multiplied by `amp`**; wash multiplies its `addB` by `amp` (BS:540). So a half-wash that gets killed keeps its full button tint until it is dropped at kill + 120 ms. A verbatim port keeps this.
- **Trigger:** `snap(side)` plays it when the button is pressed (BS:849). BS also:
  - sets `left`/`right` in the same update, so the button's persistent target becomes the app colour at 1.0 at once;
  - moves the highlight to the next unassigned window 420 ms later (BS:855), which moves the cursor with no tick;
  - when both sides are filled, closes the picker at 820 ms (BS:852). The mode changes and a reveal plays, while the half keeps running (reveal isn't FG).

### 6.2 `bloom` with a colour, including the pink bloom for Like: **changed** (BS:542 against RC:349)
```js
case 'bloom': { const c = (e.c || [0, 255, 98]).map(x => x / 255), d = eo(u / 0.8) * 30;
  for (let i = 0; i < 60; i++) { const x = Math.abs(cd(i, at)); A(i, c, 0.9 * (1 - u * 0.5) * gs(x - d, 1.5)); if (x < d) A(i, c, 0.16 * Math.pow(1 - u, 1.5)); }
  AG(at + 30, 1, mix3(c, [1, 1, 1], 0.3), 0.8 * bump(ms, 560, 900)); break; }
```
- **What changed:** RC's `GRN` constant became the parameter `c`, defaulting to 0,255,98. The spark colour is now `mix(c, white, 0.3)`. Everything else is identical: 900 ms, FG, fronts `d = eo(u/0.8)·30`, front alpha `0.9·(1 − 0.5u)·gs(|cd(i,at)| − d, 1.5)`, trail `0.16·(1−u)^1.5` inside the front, and the spark at `at + 30` with `0.8·bump(ms, 560, 900)`.
- **Like:** `this.play('bloom', { c: [255, 40, 90] })` (BS:661).
  - It plays **only when the track becomes liked**. Unliking plays nothing; there's only a toast (BS:662).
  - `at` is the Up next cursor.
  - The pink spark is 255, 104.5, 139.5.
- BS plays no green bloom anywhere, because it has no host feedback.

### 6.3 `scatter` for Shuffle: **new** (BS:543; DUR 700; FG)
```js
case 'scatter': { for (let k = 0; k < 9; k++) { const p = (e.seed * (k + 3) * 7.31) % 60, st = k * 55; AG(p, 0.8, HOT, 0.8 * bump(ms, st, st + 260)); } break; }
```
- **Seed:** `seed = 1 + Math.random()·9`, a value in [1, 10), drawn once per trigger (BS:688, and BS:790 in the dead `shufflePlay`).
- **Spark k (k = 0…8):**
  - position `p_k = (seed·(k+3)·7.31) mod 60`, evaluated as `((seed·(k+3))·7.31) % 60` on floats;
  - start `st_k = 55k` ms (0, 55, …, 440);
  - a gaussian of width 0.8 (it covers `floor(p−2.4)` to `ceil(p+2.4)`) in **HOT**, with alpha `0.8·bump(ms, st_k, st_k+260)·amp`, peaking at `st_k + 130`;
  - the last spark ends at 700 ms, which is `DUR`.
- **How the "pseudo-random" segments are chosen:** they aren't random. The 9 positions are an arithmetic progression round the ring, `3s, 4s, …, 11s (mod 60)`, with step `s = 7.31·seed`. Each spark jumps `s mod 60` segments from the last one.
- **Degenerate seeds** (computed over 90,000 seeds spread evenly over [1, 10)):
  - The minimum circular spacing between any two of the 9 positions is under 0.5 segment for 8.8 % of seeds, under 1 for 17.6 %, under 2 for 35.1 % and under 3 for 52.5 %.
  - 26 seed windows collapse onto 8 or fewer points. The worst are:
    - seed ≈ **8.2079** (step 60): all 9 sparks land on segment 0, as one blob with summed alpha 2.35–2.44 for about 500 ms;
    - seed ≈ **4.104** (step 30): the sparks alternate between two opposite points;
    - seeds ≈ 2.736 and 5.472 (steps 20 and 40): three points;
    - also ≈ 1.026, 1.368, 1.642, 2.052, 3.283, 6.156, 9.234, 9.576 (steps 7.5, 10, 12, 15, 24, 45, 7.5, 10).
  - Even the degenerate seeds never modulate faster than 3 Hz, because overlapping bumps sum smoothly. They just don't *look* scattered.
- **Triggers:**
  - Up next button 2 plays scatter **both when turning shuffle on and when turning it off** (BS:688).
  - S1:156 also names "Shuffle play", but that only exists in the dead `shufflePlay`. There, `playItem` starts a `wash` and `scatter` starts in the same tick, so the wash is killed immediately (both are FG) and fades out over 120 ms.
- **For the ports:** make `seed` an effect parameter so the oracle can inject it, and draw it from a deterministic PRNG shared by both ports (§9). Optionally, reject seeds whose minimum spacing is under 3 segments.

### 6.4 `sweep` for Play next: **new trigger** (BS:781)
- **Play next:** `this.play('sweep', { dir: 1, at: 0 })` runs the unchanged recipe (RC:351 = BS:539), `comet(60·eo(u), +1, 10, HOT, WARM, 0.85·(1 − u³)·amp)`.
  - 640 ms, FG.
  - It's always **one full clockwise lap from 12 o'clock**, whatever the cursor. S1:221 says "a warm Sweep runs clockwise"; R:175 says "Sweep | Play next".
- **Skip** (BS:675): `play('sweep', { dir: tPos })` at the **cursor before the skip**, which is 8 for Next (53 in BS for Previous). A D9 starts it at the *new* cursor, which is 0 once the host puts Tracks back to Neutral.

### 6.5 `wash`: new triggers (recipe unchanged, BS:540 = RC:355)

| Action | Line | Colour | `at` |
|---|---|---|---|
| Recently Added, button 4 Play | BS:742, then `playItem` BS:771 | album colour | the Recent cursor (the mode switches to Home in the same update, but `_cursor` isn't recomputed until the next render) |
| **Explorer, button 4 Play** | BS:747, then BS:813 (after 380 ms), then BS:771 | album **or playlist** colour | the explorer cursor |
| Windows, button 4 Switch | BS:862 | app colour. **This includes a warm app** (ChatGPT): it washes in warm, where RC:215 would green-bloom (F11). | the picker cursor |
| Up next, button 4 Play | BS:693–698 | **none.** There's no wash and no bloom, only the reveal from the mode change at 380 ms (F12). | — |

### 6.6 `bound`: fallback colour
- BS:534 adds `const c = e.c || WM`. BS always passes `c: ring[cursor].c/255` (BS:584, 702), so a warm cursor bounds in the literal marker 255,164,84 instead of the time-of-day warm. That's a prototype artefact; A's "WARM → WARM" is correct.
- **BS triggers:**
  - explicit `bnd()` at list ends: explorer (BS:708), Seek (BS:714), Tracks (BS:717), Up next (BS:721) and Windows (BS:726);
  - "the cursor didn't move" (BS:584). On Home this fires on every other 1 % detent, and in Seek on every detent that doesn't move the head. **A D4** (bound only at the haptic end stop) is still needed.

### 6.7 `reveal`: new triggers
- **Any `s.mode` change** (BS:581). Home, recent, **explore**, tracks, **queue** and windows are all separate modes, so opening or closing the explorer, Up next and the picker all reveal.
- **Seek enter and exit** (BS:667) and **the 3 s auto-exit** (BS:664), even though the mode stays `tracks`.
- **Not** the explorer tab switch (BS:805–809).

### 6.8 Ambient tint: more families (BS:521–524)
```js
const listMode = ['recent', 'explore', 'queue', 'windows'].includes(s.mode);
const cr = this._ring[this._cursor], tt = listMode && !asleep && cr && !isWarm(cr.c) ? cr.c.map(x => x / 255) : [0, 0, 0], tk = 1 - Math.exp(-dt / 220);
```
R:170 ("lists and explorers") and S1:158 ("Explorer / Windows / Up next") say the same.

### 6.9 Unchanged, and still normative from RC
- **Unchanged in BS:** wake, tick, press, fill, drain, the sweep and wash math, reveal, compose, tone map, every damping τ, the colour τ, embers and the song hand.
- **Not exercised by BS but still in the design** (R:159–168): boot, down, fail, shimmer, the Working comet and the offline breath.

### 6.10 Trigger map: what BS does, and what A would do today

| User action | BS effect (line) | A today, from host feedback | Needed |
|---|---|---|---|
| Home 1 Play/Pause | fill or drain on press (BS:734) | fill or drain from confirmed `playing` (D8) | nothing |
| Recent 3 **Play next** | sweep at 0, +1 (BS:781) | ok in recent with a non-warm accent → **wash** (D7). **Wrong.** | a feedback moment `queued` |
| Recent 4 Play | wash (BS:771) | wash (D7) | nothing |
| Explorer 2/3 tab | nothing | nothing, as long as the family doesn't change between tabs | keep one family for both tabs |
| **Explorer 4 Play** | wash (BS:813, then 771) | **bloom green**, because explore isn't in D7 | extend D7 |
| Tracks 3 **Seek** on/off | reveal (BS:667) | nothing, same family | reveal on the transport↔lap style change |
| Tracks 4 Skip | sweep at the old cursor (BS:675) | sweep at the new cursor (D9) | optional (§9, §6.4) |
| Tracks 2 Up next / Back | reveal (BS:581) | reveal only with a new family | family `upnext` |
| Up next 2 **Shuffle** | scatter (BS:688) | **bloom green** | a feedback moment `shuffle` |
| Up next 3 **Like** | pink bloom, on like only (BS:661) | **bloom green** | feedback moments `like` / `unlike` |
| Up next 4 Play | nothing, plus reveal (BS:693–698) | bloom green | a ruling (F12) |
| Windows 2/3 **Snap** | half, plus button tint (BS:849) | ok in windows with an accent → **wash** in the app colour. **Wrong.** | a feedback moment `snap` with side and colour |
| Windows 4 Switch | wash, even for a warm app (BS:862) | wash if non-warm, green bloom if warm | a ruling (F11) |
| Windows 1 Back | reveal | reveal | nothing |
| Any press / turn | press; wake / tick / bound | same | nothing |

---

## 7. Contradictions and flags

**F1: Volume body in amber/red: 0.62 (master) against 1.0 (A).**
- **The master:** S1:134 says "bounds L1 0.30, body 0.62, endpoint 1.0. Amber past 80 %, red past 90 %". BS:997 uses 0.62 for every colour.
- **A:** A §5.2 (A:149–155) gives semantic class 2 1.00, from S2:70 and KM:505 (`act ? (e.l >= 2 ? 1 : 0.45)`).
- **Precedence** makes S1 + BS win.
- **Effect:** the amber/red part of the arc drops to 62 %, and the embers then swing between 0.45 and 0.62. **Adopt it**, but flag it for the hands-on check, since it's visible.
- Class 2 semantic is also used by the Windows **closed-entry cursor** (accent at V4 L2). At 0.62 it stays dimmer than a live cursor, which is what V4 intended.

**F2: The volume colour gate: value and position (master) against position only (V4/A).**
- **BS:997:** RED if `v ≥ 90 && k ≥ 45`; AMBER if `v ≥ 80 && k ≥ 40`.
- **V4 §5.2 (V4:157):** `k ≥ 45` gives VRED and `k ≥ 40` gives AMBER, whatever the value.
- Since `k ≤ n = (v+1) div 2`, they differ **only at v = 79**, where the endpoint at segment 15 is WARM in BS and AMBER in V4, **and at v = 89**, where the endpoint at segment 20 is AMBER in BS and RED in V4 (with volRed set but no embers).
- **Adopt BS.** It matches the user's own wording: amber for 80–90 %, red for ≥ 90 %.
- For V4's pending-decrease span (k from n+1 to nc), gate on the confirmed volume.

**F3: The odd-volume shoulder, S.**
- BS has no shoulder. A D10 keeps it at 0.81 warm and **1.00** semantic.
- With F1, a semantic S at 1.0 would sit above the 0.62 body. **Make S 0.81 for every role.**

**F4: The paused Play button: green or warm? The design contradicts itself.**
- **Green:** R:138 ("a breathing Play button while paused"), S1:100 ("button 1 breathes green (2.6 s cycle)") and S2:77.
- **Only button 4 is green:** R:70 and S1:47 ("4 … The only green button"), and the acceptance line R:234 ("Only button 4 is ever green").
- **BS:** Home button 1 is `nav` (BS:944), which is WARM 0.70. `pausedPlay` (BS:504) breathes it between 0.385 and 0.70, in warm.
- **A 5.3** makes it GREEN 1.0 with the same breath.
- **Needs a user ruling.** The suggested default is to keep A (green). It's stated explicitly three times, and "only button 4 is green" reads as the action-button rule. Record it as a deviation from BS.

**F5: The Recent More double landmark breaks the ring rule.**
- **V4 (V4:180, 183):** More gets `put(slot+1, W, L1)`, and the cursor on More gets both `slot` and `slot+1` at L3.
- **R:145 and S1:140:** "Never add extra marker ticks or mix warm ticks into a coloured list."
- **BS** has no paging or More.
- **If More survives** in the UI V2 flow (see the 01 analysis): drop the `+1` cell, and treat More as a **warm item**, with a single landmark at 0.30 and the cursor WARM 1.0. That's allowed, because warm items are "its items' colours" (S1:135 "warm items 0.30"; BS's ChatGPT is warm at 0.30).

**F6: Unavailable and closed entries.**
- **Gaps are fine.** A gap adds no marker (V4:179).
- **Recent's unavailable cursor is W at L2** (V4:184). That's a warm tick in a coloured list, so use the entry's accent, as Windows already does. With F1 it would sit at 0.62.
- **The master shows no unavailable state.**

**F7: Pending pulses in coloured lists.**
- V4 draws the pending cursor in W (V4:187). A D13 changed only Windows to the app colour.
- The ring rule extends this to **Recent, Explorer and Up next**: pulse in the entry's accent.
- Loading (`put(0, W, pulseL2L1)`, V4:189) draws no list, so it stays warm. Tracks stays warm.

**F8: Windows button 1 is Back, not Cancel.**
- R:79 ("Back (restores focus)") and BS:974 make it `nav`, WARM 0.70.
- S2:78 ("Cancel is red") and V4 §5.9 `stop` (V4:243) are superseded for Windows.
- Keep `stop` in the tone table only for hosts that still send `cancel`.
- The user decision "RED for Cancel" (A:39) becomes moot.

**F9: The Tracks Prev cursor is 53 in BS and 52 in V4/KM.**
- BS takes the "last cell with `a ≥ 1`" (BS:1015). That's an artefact. **Keep 52.**
- It only moves the origin of tick, bound, fail and sweep by one segment.

**F10: Where the skip sweep starts.**
- BS starts it at the selected pair (8 or 53). A D9 starts it at the new cursor, 0.
- This is minor: the sweep is a full lap either way.
- **Proposed:** start it at the **previous** cursor, as D7 does for wash, to match BS.

**F11: Switching to a warm-coloured app.**
- BS always washes, in warm for ChatGPT (BS:862). RC's `detect()` blooms green when the cursor is warm (RC:215), and A D7 follows RC.
- **Needs a ruling.** The suggested default is to keep A: green confirms a Switch (R:138 lists Switch under green).

**F12: Up next Play (jump to track).**
- BS shows no moment (BS:693–698). A would green-bloom on the host's ok.
- **Suggested:** wash in the jumped-to track's album colour at the previous cursor, which extends D7. That fits R:171 ("Wash | playing an album") and keeps a coloured list free of green.
- **Needs a ruling.**

**F13: A's feedback flash with the new moments.**
- In A, every `ok` also turns cursor ±2 GREEN for 650 ms (A:162, from KM:508). BS has no flash at all.
- With a pink bloom, a scatter, a half-wash or a Play-next sweep, a green flash would add green to moments the design shows without it. It would also mix green into a coloured list, against R:145.
- **Proposed:** suppress the target flash whenever a feedback moment is present. Keep it for plain ok, wash and skip, as A has it now.

**F14: Up next with more than 20 entries.**
- BS collides from 21 entries (§4.6). Keep V4's window rule (V4:116, 130).
- The played / now / upcoming split must use **absolute** indices, which needs `now` on the wire.

**F15: The tint families.**
- A 5.4 and AL `alive_finish` tint only `recent` and `windows`.
- Add **explorer** and **upnext**.

**F16: Resting levels for the new alphas.**
- BS's thresholds give 0.14 → 0.05, 0.70 → 0.10 and button `off` 0.30 → **0.04**.
- A's button rule ("0.04 if dim, else 0.12") must be rewritten around those thresholds.

**F17: Scatter's seed** is non-deterministic in BS and degenerate for part of its range (§6.3). A must specify the PRNG.

**F18: Half's button tint ignores `amp`** (§6.1). Port it verbatim and give it an oracle case.

**F19: Seek is inside the Tracks family.**
- A's MODE event only fires on a family change (A:249).
- Seek enter and exit must also reveal (BS:664, 667): fire MODE when the ring style changes between `transport` and `lap`.

**F20: Skipping at the end of the queue.**
- BS shows a toast ("End of queue" / "Start of queue", BS:673) and no LED moment. A shows `fail` if the host sends `err`.
- Keep A. This is a host decision; the design just doesn't model it.

**F21: Home "only button 4 green" and Windows on Home.**
- Home's slot 4 is Windows, which is nav (BS:944).
- V4's tone rule (V4:244: go only for play, prev, next, switch at slot 3) already gives nav for `win`. No change.

**F22: `ledStyle "white"` (warm only, A D16) and the new colours.**
- **Proposed:**
  - Up next landmarks become WARM, keeping the 0.14 / 0.70 / 0.45 / 1.0 levels, which are colour-agnostic in BS;
  - the half-wash colour becomes WARM;
  - the snap button tint becomes WARM 1.0, the same as `on`;
  - **PINK is kept**, because it's semantic, like GREEN and BLUE. That last point needs a ruling.

**F23: The BS sleep model is simpler.**
- It's a 5 s timer with no pending, flash or external holds (BS:476–479). R:129 still says "never while pending or showing feedback".
- **Keep A §6.1.**

**F24: BS's `bound` colour for a warm cursor** is the literal marker (§6.6). It's an artefact; no change.

The **Tracks levels**, **the volume bound marks and endpoint**, **the list slot geometry** (3 segments apart, centred on 12 o'clock), **the gaps** and **the Home external blue** don't contradict A.

---

## 8. Wire consequences (LED side only; the frame contract belongs with the 01 and 03 analyses)

The knob computes LED targets from frames. BS computes them from its own state, and nothing in V4 + A carries the following:

| Need | Why | Proposal |
|---|---|---|
| Family for Explorer and Up next | Tint, reveal, D7 wash, Up next levels | New `layout` tokens (for example `explorer`, `upnext`), or an explicit family field. The LCD for both reuses the list layout (S1:119). |
| Seek ring | The lap pattern | `ring.style: "lap"` with `index` (position in s) and `count` (duration in s, ≥ 1). The head is `n = min(59, floor(index·60/count))`, the integer form of BS:1000 (the float form can differ at exact boundaries). |
| Up next played / now | Classes P and N | `ring.now`: int −1…count−1, the absolute index of the now-playing entry (−1 or absent means none). The classes are computed on absolute indices inside the 20-entry window. |
| Pair on/off, Seek lit, Shuffle, liked heart | Button levels | `buttons[j].lit`: `"on"` or `"off"` (absent means the V4 tone). A heart with `lit:"on"` means PINK 1.0, and **the knob supplies PINK** so it never passes through `sat()`. |
| Snap button in the app colour | Persistent tint | Reuse V4's optional `buttons[j].color`. The firmware already parses it (`cc_frame_parse.cpp:131`), but it's unused, and the host strips it (V4:305). With `alive`, a non-zero colour on an enabled button means `sat(color)` at 1.0. |
| Play next / Shuffle / Like / Unlike / Snap confirmations | The right moment instead of bloom or wash | `feedback.moment`: `queued`, `shuffle`, `like`, `unlike` or `snap`, valid only with `kind:"ok"` (stripped otherwise, like `feedback.skip`). For `snap`, also `feedback.side` (−1 left, 1 right) and `feedback.color` (int 0…0xFFFFFF, 0 meaning warm). The colour is explicit because the picker auto-advances 420 ms after a snap (BS:855), so "the previous selected accent" (D7) could already be the next window. |
| Byte budget | V4 §8 (V4:307) worst case ≤ 1,100 B | Re-measure the worst case: Windows, 20 entries in colour, 96-byte titles, plus two button colours and a `snap` feedback carrying side and colour. |

The same `lit` and `color` fields also drive the LCD footer ink. BS's inks (BS:938) are: nav `#E6E6E6`, go `#6ED996`, dim **`#5A5A5A`** (V4 has `#4A4A4A`), on `#FFFFFF`, off `#7A7A7A`, and a colour draws as `rgb(c)`. Those belong to the 01/03 analyses.

---

## 9. Proposed ALIVE.md changes, section by section

**Header (A:1–17)**
- Say that A also covers the master's LED additions for the combined cc5.4 + v7 release.
- Add the sources: R §6; S1 §2, §4, §4b and §6; the BS logic class (`renderVals` BS:938–1015, `draw` BS:485–579, handlers BS:580–864).
- State the precedence: **S1 + BS decide targets and triggers; RC decides recipe math**, except the BS-only recipes `half`, `scatter` and colour `bloom`.
- Replace "the v4 ring *geometry* … are unchanged" (A:10–11) with the following:
  - v4 geometry is reused for Home, Recent, Explorer, Windows and Tracks;
  - alive-only post-passes are added (5.1);
  - there are alive-only patterns for Seek and Up next;
  - button meanings follow the master map (R §4).

**§1 Capability**
- Keep `alive.version: 1`, and define it to include the master additions. No cc5.4 ships without them, because it's one release.
- Bump to 2 only if a cc5.4 build carrying just the v1 subset is ever installed on the user's knob.

**§2 Palette**
- **PINK:** add a row for design 255,40,90 (≈ #FF051A at full), semantic, never `sat()`'d. Add the PINK spark, `mix(PINK, white, 0.3)` = 255,104.5,139.5, and pass PINK and its spark as palette parameters, like WARM and HOT.
- **Palette derivation:** either correct WARM to 255,190.45,104.97 and AMBER to 255,131,56, or correct the "LED output" column and D3. See §2.3.
- **Warm only:** extend D16 as in F22.
- **Warm marker:** note that BS's 255,164,84 is the warm marker, for the golden remap.

**§3 Wire**
- Add `ring.style "lap"`, `ring.now`, `buttons[j].lit`, the alive meaning of `buttons[j].color`, and `feedback.moment`, `.side` and `.color` (§8).
- Add parity fixtures and the byte-budget check.
- No new knob-to-host events.

**§4 Engine**
- The effect struct gains `side` (for half), `seed` (for scatter) and a colour `c` for bloom.
- Add a deterministic PRNG for scatter seeds, identical in C++ and Python:
  - for example xorshift32, seeded with a fixed constant in `reset()`;
  - one draw per scatter, mapped to `1 + 9·u` with `u` in [0, 1).
  - Twin replay then compares seeds directly. The API is otherwise unchanged.

**§5.1 Ring cells**
- **Step 3:** add roles for the new families. Explorer and Up next use the selection ring's accent rule.
- **Level-ring colour gate (F2):** use `colour(k, x)` = RED if `x ≥ 90 && k ≥ 45`, AMBER if `x ≥ 80 && k ≥ 40`, else WARM.
  - `x` is the displayed value for `k ≤ n` (body, shoulder and endpoint), and `confirmedVolume` for the pending-decrease span.
  - The `volRed` flag follows the RED role.
- **Coloured-list post-pass** (families recent, explorer, upnext and windows, in colour mode):
  - More becomes a single warm landmark with no `+1` cell, in both the landmark and the cursor (F5);
  - the unavailable cursor takes the entry's accent (F6);
  - the pending pulse takes the entry's accent. This extends D13 (F7).
- **New Seek lap pattern** (`lap`):
  - `k < n`: class 2 WARM;
  - `k > n` with `k mod 5 = 0`: class 1 WARM;
  - `k > n` otherwise: unlit;
  - head `n`: class 3 WARM, which is the cursor.
- **New Up next reclass** (family upnext, with `now`):
  - window entries with `j < now`: class **P**;
  - `j == now`: class **N**;
  - `j > now`: class 1 at **0.45 in any role**;
  - the cursor: class 3 in its accent.
  - V4's window rule applies (F14).

**§5.2 Alpha: the new table**

| Class | Awake, warm | Awake, semantic | Resting |
|---|---|---|---|
| P (Up next played) | 0.14 | 0.14 | 0.05 |
| 1 | 0.30 | 0.45 (and 0.45 for any role in Up next) | 0.05 |
| 2 | 0.62 | **0.62** (was 1.00) [F1] | 0.10 |
| S | 0.81 | **0.81** (was 1.00) [F3] | 0.13 |
| N (Up next now playing) | 0.70 | 0.70 | 0.10 |
| 3 / 4 | 1.00 | 1.00 | 0.16 |

- **Flash:** not applied when the frame's feedback has a `moment` (F13).
- External and offline are unchanged.

**§5.3 Buttons**
- **Tones:** derive them from the master icon set. `go` means slot 3, enabled, with an icon from play, prev, next or switch/check. Home's slot 3 (Windows) stays `nav`. `stop` applies only if `cancel` is still sent.
- **New states:**
  - `lit:"on"`: WARM 1.0;
  - `lit:"off"`: WARM 0.30;
  - heart with `lit:"on"`: PINK 1.0;
  - a non-zero `color`: `sat(color)` at 1.0, or WARM 1.0 if `sat()` falls back.
- **Resting:** 0.12 when the awake alpha is ≥ 0.5, else 0.04 (F16).
- **Paused Play:** per the ruling (F4).

**§5.4 Flags**
- `family` becomes home, recent, **explorer**, tracks, **upnext** or windows. `tracks` carries a `seek` sub-state, from the ring style `lap`.
- `tint` applies to recent, explorer, upnext and windows (F15).
- New flags: `moment`, `side` and `mcolor`, from the feedback.

**§6.1 and §6.2**
- No change. Explicitly keep A's sleep model over BS's (F23).
- Note that `lim` at the Seek ends plays `bound` (S1:166).

**§6.3 Local cursor**
- Explorer and Up next use the selection row.
- For `lap`: no local cursor, because the 5 s steps are mapped host-side. Record it as a deviation. Otherwise, define the mapping together with the Seek control contract.

**§6.4 Frame events**
1. **MODE:** a family change, **or a change between ring styles `transport` and `lap`**, starts `reveal` (F19).
2. **Feedback `ok`**, checked in this order:
   1. `skip ±1` → sweep (at the **previous** cursor, if F10 is accepted);
   2. `queued` → sweep with `at = 0`, `dir = +1`;
   3. `shuffle` → scatter with a PRNG seed;
   4. `like` → bloom in PINK at the new cursor;
   5. `unlike` → nothing;
   6. `snap` → half with `side` and `sat(feedback.color)`, where 0 means WARM;
   7. D7 wash when the previous family is recent, **explorer** or windows (and **upnext**, if F12 is accepted) with a non-warm accent;
   8. otherwise → bloom in GREEN.

   Cases 2–6 run without the target flash (F13).
3. **Frame memory:** it now also covers explorer and upnext.

**§7 Effects**
- `DUR` adds `half: 900` and `scatter: 700`. `FG` adds `half` and `scatter`.
- Recipes, verbatim: `half` from BS:541, including the `addB` with no `amp` (F18); `bloom` from BS:542 (colour and spark); `scatter` from BS:543, with the seed as a parameter.
- Queue cap and eviction are unchanged. Both new effects are FG, so they kill running FG effects and duck the base.

**§8.2 and §8.4**
- `pausedPlay` per F4. The button resting rule per F16.
- The tint families per F15.
- Song hand and Working comet are unchanged.

**§9 Output**
- No change beyond the §2 palette fix. The power limit B already covers the brightest case (full warm).

**§10.2 Host (`controller.py`, `presentation.py`, `device.py`)**
- Send `lap` in Seek, `now` on the Up next mirror, `lit` and `color` on buttons (snap colours use the same `dominant()` accent as the ring), and the feedback moments.
- Stop stripping the button `color` when the knob has `alive`.
- Drop colours under `ledStyle "white"`.
- Recompute the byte budget.

**§10.3 Floating knob**
- Nothing new. It receives the same decorated frames, so the new moments come for free. It must draw the PINK and app-colour buttons (A:418).

**§11 Verification**
- **Oracle:** add a second harness for the BS logic class `draw()` (BS:485–579).
  - Stubs: a fixed `Date` (hour), the canvas, React and DCLogic.
  - One mechanical capture patch in the two compose loops (BS:557–559, 567–569).
  - Cases:
    - `half`, left and right, killed while growing and while fading (to check the button tint without `amp`);
    - pink and green `bloom`;
    - `scatter` with fixed seeds, including 1.0, 5.0, 8.2079 and 4.104;
    - `sweep` at 0;
    - the tint for explore and queue.
- **Target golden:** add BS `renderVals()` targets for:
  - Home at v = 0, 54, 79, 80, 85, 89, 90, 95, 99 and 100;
  - Recent;
  - the explorer, both tabs;
  - Tracks at −1, 0 and +1;
  - Seek at several positions;
  - Up next fresh, after Play next (n > 20) and shuffled;
  - Windows with left and right assigned.

  Map them to frames and tag the deviations: the 53 cursor, V4's pending span, shoulder and external, the window rule, and paused Play.
- **Twin replay:** every new feedback moment, the Seek MODE, and the PRNG sequence.
- **Parser parity:** the new fields and the byte budget.
- **Hands-on tour** (`nanod_alive_tour.py`): add the pink bloom (**PINK needs a value check on the hardware**), the half-wash on both sides, scatter, the Play-next sweep, the Seek lap, the Up next levels, pair on/off and the snap button colour.

**§12 New deviations and rulings (numbers continue from D18)**
- **D19** The volume body is 0.62 in every colour, and S is 0.81 in every role (S1:134, BS:997, over S2:70 and KM:505).
- **D20** The volume colours are gated on value and position (BS:997), which matches the [user] wording. They differ from V4 at 79 and 89.
- **D21** Coloured lists get no extra or warm markers: More is a single warm item, and the unavailable and pending cursors use the accent (R:145).
- **D22** The Tracks Prev cursor is 52 (V4), not 53 (a BS:1015 artefact).
- **D23** Scatter seeds come from a deterministic PRNG, with optional rejection of degenerate seeds.
- **D24** The new moments run on host confirmation (`feedback.moment`). BS plays them on press.
- **D25** No target flash with a moment.
- **D26** Paused Play follows the user's ruling. BS renders it warm.
- **D27** Up next uses V4's window rule; BS collides at 21 or more entries.
- **D28** Explorer Play washes, which extends D7. Up next Play and warm Switch follow the rulings (F11, F12).
- **D29** Seek has no local cursor, or it's defined by the Seek control contract.

---

## 10. Open questions for the user

1. **Paused Play button:** green breath (R §6, S1 §2, A today) or warm breath (BS; "only button 4 is ever green", R:234)?
2. **PINK for Like:** take the design value 255,40,90 (≈ #FF051A at full), or tune it on the hardware like warm, amber and red?
3. **Volume amber/red body at 0.62** (master) instead of today's 1.0: accept it?
4. **Up next Play** (jump to a track): a wash in the album colour, a green bloom, or nothing (BS)?
5. **Switching to a warm-coloured app:** a warm wash (BS) or a green bloom (RC and A today)?
6. **Warm only:** keep PINK there, as a semantic colour?
7. **Capability:** keep `alive.version` at 1 for the combined release?
