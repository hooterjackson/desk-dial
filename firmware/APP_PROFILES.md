# App profiles: wire format and knob store (contract, v1)

Status: frozen for S1 (plan §1b–§1d). Implemented by `src/cc_app_store.h/.c` (knob) and
`control_center/app_profiles.py` (Desk Dial compiler). Any change bumps `wire`.

Credit: the profile model, element set, parameter model and limits are Karl Malota's
(katbinaris) app profiles, `feat/firmware-esp-idf-quadra` `NanoDepsidf/src/app_profiles/`
(`app_profile.h`, `profile_json.c`), adapted with his permission.

## 1. Where the data comes from

- **File format:** Karl's profile JSON, `"format": 1`, unchanged (`profiles/karl/<id>.json`).
- **Windows sidecar:** `<id>.windows.json`, `"overlay": 1`. It holds detection, Windows keys, slot,
  feel and status overrides. It's applied by Desk Dial and never sent to the knob as is.
- **Wire profile (`DDAP`):** what Desk Dial compiles from the two and uploads. It carries **display
  data only**: no macros, phrases, waits, search timings, pointer settings or key codes. Everything
  that types or moves the pointer stays on the PC.

## 2. Encoding rules

- Little-endian. No padding or alignment.
- `u8 / u16 / u32 / i8`: unsigned and signed integers. `f32`: an IEEE-754 binary32. It must be finite
  (no NaN or Inf) and within ±1e7.
- `str`: `u8 len` + `len` bytes, every byte 0x20..0x7E, no NUL. Each field below has its own maximum.
  An empty string is allowed only where marked.
- **Indexes:** `0xFF` means "none".
- **Strict decoding:** the decoder reads exactly `total` bytes. A short read, a trailing byte, a value
  out of range, an unknown enum or an unknown feature bit rejects the whole profile, with a reason
  code (§6). Nothing is partly loaded.

## 3. Layout

```
header
  u8[4] magic        "DDAP"
  u8    wire         1
  u8    reserved     0
  u16   reserved     0
  u32   total        whole blob in bytes, header and trailer included (<= 32768)
  u32   features     bit set, §4; unknown bits -> reject
profile
  str   id           1..11 chars of [a-z0-9_-]
  str   name         1..15
  str   legend[4]    0..7 each (physical keycaps 1..4, left to right)
  u8    visual       0 label | 1 shape
  u8    shape        0 cube | 1 pyramid | 2 octa          (0 when visual = label)
  u8    shape_style  0 face | 1 grips | 2 thick
  u8    stepped      0 | 1
  u32   plasma[3]    each 0..0xFFFFFF, RGB888 cool -> hottest; all 0 = sample icon48
  u8    icons        bit0 icon24 follows, bit1 icon48 follows, other bits 0
  u8[1152] icon24    24x24 RGB565 big-endian (black = transparent), if bit0
  u8[4608] icon48    48x48 RGB565 big-endian, if bit1
slots (exactly 5: knob, f1, f2, f3, f4)
  u8    kind         0 none | 1 drag | 2 wheel | 3 keys | 4 tap | 5 commands
  u8    fx           0 none | 1 zoom | 2 orbit | 3 pan | 4 flash
  u8    button       physical button 0..3 that selects this slot, 0xFF for knob/none
  str   label        0..23 (shown large while the slot is live: "ZOOM")
search chord (for the wheel's search tail; display only)
  u8    mod          display modifier bits, §5
  str   key          0..7 (empty = the profile has no search)
params
  u8    count        0..32
  count x {
    str label        1..23
    str label_neg    0..23 (empty = label)
    f32 steps[3]     F1 / knob / F4 step sizes
    f32 free_step
    f32 start, min, max   min <= start <= max
    u8  decimals     0..4
    u8  flags        bit0 deg, bit1 axes, bit2 planes, bit3 uniform; other bits 0
    u8  visual       0..9 (APP_PV_*)
    u8  modes        0..15
    u8  axis_default 0..3
    u8  field        0 handle | 1 number field (A scroll / B type shown)
  }
scenes
  u8    count        0..128
  count x {
    u8  n_base       0..48
    el  base[n_base]
    u8  n_frames     0..16
    n_frames x { u16 ms 0..60000; u8 n 0..48; el el[n] }
  }
  el = 9 bytes: u8 op 0..14, u8 color 0..4, i8 x, i8 y, u8 w, u8 h, u8 arg, u8 d, u8 flags
       (the same ranges as Karl's profile_json.c element check)
rings
  u8    count        0..8
  count x {
    str name         1..23
    str tab          1..6
    u8  slot         0..4 (Karl's app_slot_t of the jump key)
    u8  cmd_count    1..32
    cmd_count x {
      str name       1..23
      u8  flags      bit0 search (runs through tool search), bit1 disabled on Windows (drawn grey,
                     refused), bit2 macro; other bits 0
      u8  mod        display modifier bits, §5
      str key        0..7 display key label ("E", "F5", "/", "NUM1"); empty when search or macro
      u8  scene      index into scenes, or 0xFF
      u8  param      index into params, or 0xFF
    }
  }
trailer
  u32   crc32        zlib CRC-32 of every byte before it
```

The `crc` in the upload `begin` message is the same value as the trailer.

## 4. Feature bits

| Bit | Name | Set when |
|---|---|---|
| 0 | `SHAPE` | `visual` = 1 |
| 1 | `SHAPE_EXT` | shape ≠ cube, or style ≠ face |
| 2 | `LABEL_VISUAL` | `visual` = 0 |
| 3 | `PARAM_CONSTRAINTS` | any param has axes, planes or uniform flags |
| 4 | `DISABLED_CMDS` | any command has flag bit1 |

The knob advertises the bits it can draw (`appProfileFeatures`, §7). Desk Dial sends only
profiles whose bits are a subset. Otherwise the app runs with text screens.

## 5. Display modifier bits (Windows keycaps)

`0x01` CTRL, `0x02` SHIFT, `0x04` ALT, `0x08` WIN. These are already mapped for Windows by Desk Dial:
Cmd → Ctrl, Opt → Alt, plus the overrides. The knob draws keycaps from these and never maps
anything itself.

## 6. Decoder result codes

`0` ok, `1` short, `2` magic, `3` wire version, `4` total mismatch, `5` crc, `6` feature bit,
`7` string (length or byte), `8` enum or range, `9` count limit, `10` index (scene or param),
`11` id syntax, `12` trailing bytes, `13` no memory, `14` float. The upload error message carries
`decode:<code>@<offset>`.

## 7. Serial messages (capability `appProfiles: 1`)

```
caps:  "appProfiles":1, "appProfileSlots":4, "appProfileMaxBytes":32768, "appProfileFeatures":31
→ {"appProfile":{"op":"begin","id":"figma","bytes":N,"crc":C,"wire":1}}
→ {"appProfile":{"op":"data","off":O,"b64":"…"}}     b64 <= 3000 chars, offsets in order
← {"appProfile":{"ack":O_next}}
→ {"appProfile":{"op":"end"}}
← {"appProfile":{"id":"figma","crc":C,"ok":true}}
← {"appProfile":{"error":"crc|size|order|busy|wire|decode:<code>@<offset>"}}
→ {"appProfile":{"op":"list"}}  ← {"appProfile":{"loaded":[{"id":"figma","crc":C}, …]}}
```

- One upload at a time. A `begin` during an upload aborts the earlier one.
- A partial upload is dropped after 2000 ms without data. That's the same rule as a stalled line.
- `end` decodes the profile into the store, replacing any older copy with the same id. The LRU evicts
  the least recently drawn profile when 4 are loaded or the 128 KB budget would be exceeded.
- The store is RAM only (PSRAM). Nothing is written to flash, and a reboot empties it.

## 8. Frame (`app` object) additions

- `id` may be any loaded profile id. `crc` (u32) must match the loaded copy.
- An unknown id or a crc mismatch draws the neutral "Loading…" app screen. It doesn't reject the
  frame (the new rule).
- `slot` accepts `knob`, `f1`..`f4` in addition to the legacy `zoom`/`orbit`/`pan`/`tilt`.
- `ring` max 7, `index` max 32.
- `param` gains the live constraint (added in S1 at FW-B's request): `axis` optional int 0..3 (X, Y, Z,
  uniform; absent = the profile's `axis_default`; anything else rejects the frame) and `plane` optional bool
  (default false: the axis key with Shift selects the plane instead of the axis).
- Without `appProfiles`, Desk Dial sends only the legacy built-in `onshape` frame, as today.
