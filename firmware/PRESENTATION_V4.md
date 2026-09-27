# Control-center presentation contract v4 (cc5)

Status: **frozen for cc5**. Change it only together with both adapters and their tests:

- Python: `app/control_center/presentation.py` (constants and pure helpers) and `device.py` (validation, stripping, slimming).
- Firmware: `src/cc_presentation.h` (CCFrame, tokens, helpers) and `src/control_center.cpp` (`parse_frame`).

Design source: `app/design-reference/design_handoff_nano_d_artwork_color/`, the "album artwork + targeted-colour LEDs" variant.
- `knob-model.js` is the behavioural source of truth.
- `Knob Face.dc.html` is the renderer reference.

Deliberate deviations are listed in section 9.

Presentation never reloads a haptic profile, re-arms a control, or moves a detent. Frames are presentation only. Only `control` (enter) changes bounds, profile or position.

## 1. Capabilities (firmware reply to `{"capabilities":"?"}`)

| Key | cc4 | cc5 |
|---|---|---|
| `controlCenter` | 1 | 1 |
| `presentation` | 2 | **4** |
| `artwork` | absent | `{version:1,width:120,height:120,format:"RGB565_LE",chunkBytes:384,cacheEntries:8,available:bool,composited:"scrim80"}` |
| `glyphs` | absent (ASCII) | `"latin-ext-a"`: U+0020–007E, U+00A0–017F, plus · – — ‘ ’ “ ” • … |
| `diag` | absent | 1. `{"diag":"?"}` returns `{"diag":{lvglFree,lvglMinFree,heapMinFree,stackLcd,stackCom,stackHmi}}` (bytes). Additive in 1.0.0-cc5.1 (the capability stays 1): `stackFoc`, `stackUsbd`, `heapFree`, `psramFree`, `txStalls`, `txDroppedBytes`, and reboot detection: `resetReason` (`esp_reset_reason()` as a string), `resetCode`, `rtcReset`/`rtcResetNames` (per-CPU ROM reasons), `bootCount` (RTC counter with a magic), `rtcRetained`, `uptimeMs`, `previous` (the last per-task breadcrumbs before the reset), `coredump` and `rxQueue`. Additive in 1.0.0-cc5.2 (the capability stays 1): task liveness `hmiAgeMs`, `lcdAgeMs`, `comAgeMs`, `focAgeMs` with `hmiStep`, `lcdStep`, `comOp`, `comStage`; the task watchdog `taskWdtS`, `wdtTasks`; `sessionPhase`, `releasePendingMs`, `forcedReleases`, `lastForced`; the LED transport `led` (per strip) with `ledTxTimeouts` and `ledWriteErrors`; and `previous.lastAliveMs` with a per-task `aliveMs`. Field meanings: `CONTROL_CENTER.md`, "Diagnostics". |

The saved pre-cc5 source reported `presentation:3`. The host treats anything below 4 as legacy.

1.0.0-cc5.1 changes nothing in this contract: frames, rings, the LED model, layouts, art and errors are as in 1.0.0-cc5. Only the `diag` reply gained the additive fields above.

1.0.0-cc5.3 keeps `presentation:4`, the v1 `artwork` object and the `art` command byte-identical, and adds the sibling capability `artwork2`, the `media` command and the optional frame field `iconKey`. They are specified in `ARTWORK2.md`: 240 px JPEG covers, 32×32 app icons on the Windows tile, knob-side prefetch with a `have` query, and unpaced whole-line writes when negotiated.

1.0.0-cc5.2 changes nothing in this contract either: frames, rings, the LED model (section 5, `light_tests.py` unchanged), layouts, art and errors are as in 1.0.0-cc5. Only the `diag` reply gained the additive fields above. The LED transport under the model changed (same bytes, bit timing, pins and colour orders) and a release may now be answered with `"reason":"forced"` (`CONTROL_CENTER.md`, "Release" and "LED transport").

## 2. Compatibility

**The host (v4 companion) talking to older firmware** (`presentation < 4`):
- Strip every v4-only field: `restLayout`, `heading`, `meta`, `titleTone`, `metaTone`, `statusTone`, `page`, `artDim`, `feedback`, `ring.first`, `ring.unavailable`, `ring.colors`, `ring.moreIndex` and `ring.external`.
- Map `layout:"notice"` to `"nowPlaying"`.
- Transliterate all text to ASCII.
- Keep every legacy field and each button's `color`.
- Send no artwork unless the `artwork` capability is valid.

**Firmware (cc5) accepting legacy frames** (presentation 2 or 3, no `layout`): every v4 field is optional.
- `layout` is derived from `mode`:
  - `VOLUME` → `nowPlaying`
  - `RECENTLY ADDED` → `recent`
  - `TRACKS` → `tracks`
  - `WINDOWS` → `windows`
- Such frames render with no art and white LEDs, because `ledStyle` defaults to `white`.
- Button `color`, if present, is ignored for LEDs; tone is always derived (section 6).

## 3. Frame fields

All text is UTF-8. The limits are byte capacities that match the CCFrame buffers minus the NUL terminator.
- **Python** truncates at the last code-point boundary within the capacity.
- **Firmware** truncates at the same boundary.
- A string is never split inside a multibyte sequence.
- Control characters (< 0x20) are rejected.

| Field | Type / bound | Default when absent | Meaning |
|---|---|---|---|
| `id` | int 1..0x7FFFFFFF | required | Control ID the frame belongs to |
| `mode` | text ≤24 | required | Legacy mode title (`VOLUME` etc.) |
| `target` | text ≤64 | required | Legacy (room/desktop). Not drawn by v4 renderers |
| `value` | text ≤64 | required | `big` (volume value such as `54%`) |
| `detail` | text ≤96 | required | Legacy; ignored by v4 renderers |
| `status` | text ≤64 | required | `st` status line |
| `title` / `subtitle` | text ≤96 | "" | `title` / `sub` |
| `counter` | text ≤24 | "" | Legacy; omitted for v4 |
| `activity` | `idle\|loading\|pending\|error\|unavailable\|offline` | `idle` | Drives only pulses and the Home-offline endpoint (section 5) |
| `layout` | `nowPlaying\|volume\|idle\|recent\|tracks\|windows\|notice` | derived from mode | Which LCD layout to draw |
| `restLayout` | `nowPlaying\|idle` | `nowPlaying` | Base layout under a `volume` reveal; `idle` keeps art and footer hidden |
| `heading` | text ≤32 | "" | `label` row at y32 (e.g. `RECENTLY ADDED · P2`, `TRACKS`) |
| `meta` | text ≤96 | "" | `meta` line (Recent/Tracks/Windows/notice) |
| `titleTone` | `ink\|muted` | `ink` | `tc` |
| `metaTone` | `meta\|secondary\|error\|success` | `meta` | `mc` |
| `statusTone` | `meta\|secondary\|error\|success` | `meta` | `sc` |
| `page` | int 0..255 | 0 | Recent page. While a next page is loading, this is the **requested** page |
| `volumeVisible` | bool | false | Legacy mirror of `layout=="volume"` |
| `volumeCaption` | text ≤96 | "" | `volCap` (Home only) |
| `confirmedVolume` | int 0..100 | `ring.value` | Sonos-confirmed volume (Home only) |
| `ledStyle` | `white\|color` | `white` | `color` = targeted colour |
| `artKey` | `[A-Za-z0-9_-]{0,64}` | "" | Content key of the cover to show. Empty means no art |
| `artDim` | bool | false | Draw the cover at 0.35 instead of 0.8 (`image_opa` 112 over pre-composited pixels) |
| `feedback` | `{kind:"ok"\|"err", seq:int 1..0x7FFFFFFF}` | absent | Flash trigger (section 5.8) |
| `buttons` | exactly 4 × `{label ≤16, enabled bool, icon, color?}` | required | `icon` ∈ `play pause list win tracks back home more prev next switch cancel ""`. `color` is optional for v4 |
| `ring` | object | required | Section 4 |

**Tone colours (LCD):**
- `ink` `#F2F2F2`, `muted` `#7C7C7C`.
- `meta` `#7C7C7C`, `secondary` `#A6A6A6`, `error` `#FF8A7A`, `success` `#7EE0A2`.

**v4 field map** (knob-model `lcd` → wire). Renderers draw wire text verbatim and never invent copy.

| knob-model | Wire |
|---|---|
| `label` | `heading` |
| `title` | `title` |
| `sub` | `subtitle` |
| `meta` | `meta` |
| `st` | `status` |
| `big` | `value` |
| `volCap` | `volumeCaption` |
| `tc` / `mc` / `sc` | `titleTone` / `metaTone` / `statusTone` |
| `art` | `artKey` + `artDim` |
| `iconOp` (Windows tile 0.35) | unavailable bit of the selected entry |

## 4. Ring object

| Field | Type / bound | Default | Meaning |
|---|---|---|---|
| `style` | `off\|level\|selection\|transport` | required | Pattern |
| `value` | int 0..100 | required | `level`: requested (display) volume |
| `index` | int 0..65535 | required | Absolute selected entry (`selection`, `transport`) |
| `count` | int 0..65535 | required | Absolute entry count; for `transport` it is 3 (0 Prev, 1 Neutral, 2 Next) |
| `first` | int | derived (see below) | First transmitted entry. Must satisfy `0 ≤ first ≤ index < first+20`. Always 0 when `count ≤ 20` |
| `colors` | list ≤ `min(20, count-first)` of int 0..0xFFFFFF | absent (all white) | `colors[k]` is the accent of entry `first+k`; `0` = no accent → white. Only sent when `ledStyle=="color"` and style is `selection` |
| `unavailable` | int, < `1 << min(20, count-first)` | 0 | Bit k: entry `first+k` is unavailable (Recent) or closed (Windows). For `transport`, bit0 means Prev is unavailable and bit2 means Next is unavailable (Next landmarks are still drawn) |
| `moreIndex` | int −1..count−1 | −1 | Absolute index of the Recent `More` entry |
| `external` | bool | false | `level`: volume last changed on Sonos. The endpoint is L4. The host owns the lifetime (6 s, or cleared by a local turn) |

Parsers reject:
- `index ≥ count` for `selection`/`transport`.
- A **present** `first` outside the window rule.
- More colours than allowed.
- Mask bits beyond the window.

**A missing `first` is never rejected.** This applies to legacy (v2) companions and to any ring without the field; the section 2 legacy acceptance takes precedence. The host and every parser derive `first` = 0 when `count ≤ 20`, otherwise `clamp(index-9, 0, count-20)`. `colors` and `unavailable` are kept only when that derived `first` is 0 (they were relative to an implicit 0); otherwise they are ignored. This is the `rules.absentFirst` decision in `tests/fixtures/frames_v4.json`, which both parsers are tested against.

**Host window rule.** `first = 0` when `count ≤ 20`, otherwise `clamp(index-9, 0, count-20)`.

## 5. LED model (identical in `preview_lights.py` and `cc_lights.cpp`)

### 5.1 Coordinates, palette, levels

- **Coordinates.** Logical segment 0 is 12 o'clock, increasing clockwise. The physical mapping stays in firmware `address()`: reflection plus orientation, unchanged from cc4.
- **Write semantics.** `put(i,c,l)` **overwrites** `ring[i mod 60]`; it never max-combines. Draw order is: marks, body, endpoint/cursor, pending override, flash.
- **LED palette:**

  | Name | Value |
  |---|---|
  | W | `0xFFFFFF` |
  | G | `0x46E178` |
  | R | `0xFF4834` |
  | AMBER | `0xFF961E` |
  | VRED | `0xFF3723` |

  These are separate from the LCD inks.
- **Levels:** L0..L4 = `0, 15, 46, 102, 204`. The volume shoulder level is `LS = 74`. Output per channel is `(c*level + 127) / 255`, computed before the global FastLED brightness cap (51). Dithering stays at FastLED's default.

### 5.2 Volume (`style:"level"`)

**Definitions** (v = value, c = confirmedVolume, both integers):
- `n = (v+1)/2`
- `nc = (c+1)/2`
- `vseg(x) = (35 + (x+1)/2) mod 60`
- `volc(k) = W` unless `ledStyle=="color"`, in which case `k ≥ 45` → VRED, `k ≥ 40` → AMBER, else W

**Drawing:**
1. **Bound marks:** `put(35,W,L1)`, then `put(25,W,L1)`.
2. **Body, k = 0..n:** `put(35+k, volc(k), k ≤ nc ? L2 : L1)`. The span above the confirmed value is L1 while an increase is pending.
3. **Pending decrease:** for k = n+1..nc, `put(35+k, volc(k), L1)`.
4. **Odd-v shoulder** (v odd and n ≥ 1): `put(35+n-1, volc(n-1), LS)`.
5. **Endpoint:** `put(vseg(v), volc(n), external ? L4 : L3)`.

The cursor is `vseg(v)`.

**Home offline** (`activity=="offline"` with `level`): only `put(vseg(c), W, L1)`. No marks. Cursor `vseg(c)`.

### 5.3 Lists (`style:"selection"`, Recent and Windows)

**Definitions** (per transmitted entry j = first..first+len−1, with k = j−first):
- `c0 = (count-1)/2`
- `slot(j) = ((j-c0)*3) mod 60`
- `acc(j)` = W when `ledStyle!="color"`, when `j==moreIndex`, or when the accent is 0; otherwise `colors[k]`
- An entry j is "unavailable" when mask bit k is set

**Drawing:**
1. **Landmarks:** for each available entry j, `put(slot(j), acc(j), L1)`. Unavailable entries leave a gap.
2. **More:** if `moreIndex ≥ 0`, also `put(slot(moreIndex)+1, W, L1)` (the More double landmark).

**Cursor** (entry `index`):
- More → `put(slot,W,L3)` and `put(slot+1,W,L3)`.
- Unavailable → `put(slot, isWindows ? acc(index) : W, L2)`. `isWindows` means `mode=="WINDOWS"` or `layout=="windows"`.
- Otherwise → `put(slot, acc(index), L3)`.

**Pending** (`activity=="pending"`): `put(cursor, W, pulse)`.

**Loading** (`activity=="loading"`): **only** `put(0, W, pulseL2L1)`; nothing else.

### 5.4 Tracks (`style:"transport"`, always white)

**Landmarks:**
- Unless Prev is unavailable, `put(52,W,L1)` and `put(53,W,L1)`.
- `put(0,W,L1)`, `put(7,W,L1)`, `put(8,W,L1)`.

**Selection:**
- index 0 → 52 and 53 at L3 (only when Prev is available); cursor 52.
- index 2 → 7 and 8 at L3; cursor 8.
- index 1 → `put(0,W,L2)`; cursor 0.

**Pending:** the selected pair takes `pulse`.

### 5.5 Off

`style:"off"` → all segments dark. The cursor is 0, for flashes.

### 5.6 Pulses

- **`pulse`** (pending): L3 on even phases and L1 on odd phases. Each phase is 260 ms, anchored at the onset of the pending state, starting HIGH. After 3000 ms of continuous pending, it holds at L1.
- **`pulseL2L1`** (loading): L2 on even phases and L1 on odd phases, anchored at loading onset. No hold.

Onset resets whenever the pending or loading condition starts.

### 5.7 Damping

Segments are compared by peak channel.
- A segment whose new target is **not lower** than what is shown snaps immediately (instant rise).
- Otherwise it decays from the shown colour to the target over 260 ms using the 17-entry easeOutQuint LUT `{0,67,123,165,195,216,230,239,245,249,252,253,254,255,255,255,255}` (t in 1/16 steps, linear between entries). Blending is per channel: `from + (to-from)*e/255`.

Buttons fade from the shown colour to the target over 220 ms with the same LUT.

Everything snaps on renderer reset or an orientation change. Time arithmetic is millis-wrap safe.

### 5.8 Flash (`feedback`)

- **Trigger:** when a frame carries `feedback` and `seq != lastSeq`, start a flash and set `lastSeq = seq`. This holds **regardless of control ID or layout**.
- **Seeding:** `lastSeq` is seeded, without flashing, only by the first frame after a renderer reset (the unclaimed→claimed transition in firmware; PreviewLights construction in Python). A frame without `feedback` leaves `lastSeq` unchanged.
- **Pattern:**
  - `ok`: G at L4 on cursor−1, cursor, cursor+1 for 650 ms.
  - `err`: R at L3, same segments, for 900 ms.

  Drawn last (overwrite), once, with no strobing. The flash ignores `ledStyle`.

### 5.9 Buttons

`tone(slot, icon, enabled)`:

| Condition | Tone | LED | LCD footer ink |
|---|---|---|---|
| `icon==""` | none | off | hidden |
| `!enabled` | dim | W at L1 | `#4A4A4A` |
| `slot==0 && icon=="cancel"` | stop | R at L2 | `#FF8474` |
| `slot==3 && icon ∈ {play,prev,next,switch}` | go | G at L3 | `#6ED996` |
| otherwise | nav | W at L2 | `#E6E6E6` |

The idle-row ink follows the same rule. Home Play and Tracks are nav (white); Recent Play is go; More is nav.

The press highlight is unchanged from cc4 (blend toward white while held).

## 6. LCD layouts (summary; the geometry is in Knob Face and the design-lcd notes)

**Common:**
- Canvas 240×240, black. Optical safe circle r104 around (120,120).
- Footer: 20 px A8 icons centred at x 56/99/141/184, glyph y154–174.
- Idle row: 26 px icons centred at x 51/97/143/189, y100; 12 px words at y≈134.

**Art:**
- The host sends 120×120 RGB565 already composited: 0.8 opacity plus the scrim (0.35 at y0, 0.55 at y108, 0.90 at y149, black from y168).
- Firmware upscales ×2 once per key into a PSRAM buffer and draws it at `image_opa` 255, or 112 with `artDim`.
- The host alone decides visibility through `artKey`. Renderers never gate art on `activity`.

**Where art appears:**
- Shown on `nowPlaying`, `volume` (not over `restLayout:"idle"`), `recent` (per item, including partial/Sonos-down), and `tracks`.
- Never on `windows`, `notice`, Recent loading/empty/auth/More, or disconnected.

**Art swaps and fades:**
- Cached covers swap instantly on a key change.
- A late-arriving cover fades in (60 ms delay + 420 ms).
- Entering idle fades out over 560 ms; returning from idle fades in over 420 ms.
- A previous cover is never shown for a new key.

**Screen change:**
- Happens only when (mode, recent page) changes.
- Content enters from +20 px when `depth(new) ≥ depth(old)`, otherwise from −20 px.
  - depth: home 0, tracks 1, recent 1+page, windows 5
  - Motion: transform 380 ms OUT, opacity 220 ms.
- The art layer does not translate.
- A control-id change alone, a Home layout change, a detent, a Tracks re-centre or a heartbeat never slides.

**Motion:**
- Translate and opacity only.
- The SPR overshoot (0.34, 1.45, 0.64, 1) is used only for translate; opacity uses OUT (0.22, 1, 0.36, 1) or IN (0.4, 0, 1, 1), clamped to 0..255.
- No `opa_layered` and no transforms (LVGL heap is 64 KB).
- An identical frame (heartbeat) starts no animation and re-sets no text.

## 7. Errors (presentation is never fatal)

- The host strips invalid or unsupported **optional** fields and logs them. Only malformed required fields reject a frame.
- An artwork size or format mismatch emits `artwork-error`; it never produces `error` or a disconnect.
- **Firmware:** a line starting with `{"art"` that fails to parse or is oversize is answered with `{"artAck":{"id":…,"key":…,"op":"parse","error":"parse"}}`. The id and key come from a bounded raw prefix scan; they are omitted if they are not found.
- **Firmware:** an oversize line is discarded through its newline, with one reply.
- **Host:** while an art chunk is outstanding, a bare parse or oversize `error` becomes `artwork-error` plus an abort (one retry). Every other `error` reply stays fatal, as in cc4.

## 8. Size budget (v4 slimming, presentation ≥ 4 only)

Omit the following:
- Default-valued optional fields:
  - default tones
  - `artDim:false`, `page:0`
  - `ring.first:0`, `ring.unavailable:0`, `ring.moreIndex:-1`, `ring.external:false`
  - empty `heading`, `meta` and `artKey`
- `volumeCaption`, `confirmedVolume`, `restLayout` and `volumeVisible` outside Home.
- `counter`.
- Button `color`.

Worst case, Windows with 20 entries in colour mode and 96-byte titles, must be **≤ 1,100 bytes**. The limit applies to the JSON-escaped line.

If a slimmed frame is still over budget, the host trims legacy fields in this order:
1. Empty `detail`.
2. Empty `value`, but **never on Home layouts** (`nowPlaying`, `volume`, `idle`), which draw the volume digits from it.
3. Empty `target`.

**Last resort** (escape-heavy text only, such as titles full of quotes or backslashes): remove whole code points from the end of the longest of `volumeCaption`, `subtitle` and `title` until the line fits, and log `"<field> shortened"`.

The firmware never depends on the trimmed legacy fields for v4 rendering.

## 9. Deliberate deviations from `knob-model.js`

The golden-fixture test lists these explicitly.

1. **Odd-v volume shoulder** at segment `35+n-1`, level LS=74 (the handoff requires feedback at every 1 %).
2. **Pending span in both directions** at L1. The model only covers increases (audit #12).
3. **Pending pulse is white for Windows.** The model uses the app colour; README:204 and audit #12 say white.
4. **Pending pulse holds L1 after 3 s** (motion table CC:694).
5. **More than 20 entries** use the window rule. The model collides at n ≥ 21.
6. **Tracks "Previous unavailable".** The title stays "Previous track" in the `muted` tone, and the meta line says "Previous unavailable" (229 px does not fit 180 px).
7. **Art does not translate** on a screen change, and decorative scale transforms are omitted.
8. **Disconnected.** Firmware hands control back to the native UI (cc4 behaviour) instead of the model's seg-0 pattern. The host-lost notice is restyled to "NANO_D++ / Waiting for PC / Native controls active".
9. **UWP/packaged apps** get no accent (white) and a letter tile. Package-icon extraction is deferred.

## 10. C++11 rules (firmware is `gnu++11`)

- No C++14 features: relaxed `constexpr`, digit separators, `make_unique`, generic lambdas or `auto` return type deduction.
- Tables go at namespace-scope `constexpr`. Never use odr-used `static constexpr` class members.
- Shared translation units (`cc_lights.cpp`, `cc_display.cpp`, `cc_icons.cpp`, frame parser) must pass `harness/cpp11_gate.py` and MSVC `/W4 /WX`.
