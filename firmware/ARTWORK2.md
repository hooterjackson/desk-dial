# artwork2: 240 px covers, app icons, knob-side prefetch, unpaced transport (1.0.0-cc5.3)

Status: **frozen for cc5.3**. This is an additive extension of `PRESENTATION_V4.md` (contract v4). Change it only together with both adapters and their tests.

- Python: `app/control_center/presentation.py` (the `ARTWORK2_*` / `MEDIA_*` / `ICON_*` / `COVER_*` constants), `device.py`, `runtime.py`, `artwork.py`, `lcd_preview.py`.
- Firmware: `src/cc_media_store.h` (platform-neutral store), `src/cc_media.cpp`/`.h` (ESP wrapper and `media` command), `src/cc_jpeg.cpp`/`.h` (ROM TJpgDec glue), `src/control_center.cpp`, `src/cc_frame_parse.cpp`, `src/cc_presentation.h`, `src/cc_display.cpp`, `src/lcd_thread.cpp`, `src/com_thread.cpp`, `src/main.cpp`.

Why it exists (user report, 2026-09-23):
- Covers took ~5 s to appear: 80 % of that was the host's 64 B / 5 ms write pacing.
- Covers looked low-res: 120 px on the wire, scaled up 2× on the knob.
- Nothing could be preloaded: cc5.2 accepts art only for the current frame's `artKey`.
- App icons never reached the knob: cc5.2 draws only a letter tile.

Everything in contract v4 stays as it is. `presentation` stays **4**. The v1 `artwork` object, the `art` command, its error strings, its binding rule and its 120 px store stay **byte-identical**, so an old (cc5.2-era) companion works unchanged against cc5.3.

## 1. Capability

cc5.3 adds one sibling key to the `{"capabilities":"?"}` reply. All other keys are unchanged, including `artwork`.

```json
"artwork2":{"version":1,"available":true,"composited":"scrim80","paced":false,"rxBytes":8192,
            "chunkBytes":2048,"haveKeys":24,
            "cover":{"width":240,"height":240,"format":"JPEG","maxBytes":32768,"entries":24},
            "icon":{"width":32,"height":32,"format":"RGB565_LE","bytes":2048,"entries":48,"background":"black"}}
```

| Field | Meaning |
|---|---|
| `version` | 1 |
| `available` | false when either PSRAM store could not be allocated. The host then uses v1 art, or none |
| `composited` | `"scrim80"`: covers arrive pre-composited exactly as in v1 (0.8 opacity plus the readability scrim) |
| `paced` | false: the host may write whole lines without 64 B / 5 ms pacing (section 3) |
| `rxBytes` | CDC receive queue size in bytes actually configured: 8192 in internal RAM. It reports 0 when the queue landed in PSRAM and 256 when the default queue was kept. Any value other than 8192 fails the host's exact-match gate, so the host falls back to paced v1 (lead ruling, 2026-09-24) |
| `chunkBytes` | Maximum decoded bytes in one `data` line (2048, which is 2732 base64 characters) |
| `haveKeys` | Maximum keys in one `have` query (24) |
| `cover` | 240×240 baseline JPEG, at most 32768 bytes, 24 cached entries (plus one staging slot) |
| `icon` | 32×32 RGB565 little-endian, alpha-composited onto black, exactly 2048 bytes, 48 cached entries (plus one staging slot) |

**Host gating.** The host uses artwork2 only when all of these hold:
- `presentation ≥ 4`;
- `artwork2` is an object with `version == 1` and `available == true`;
- every field above has exactly the listed type and value. Unknown extra fields are ignored.

Otherwise the host behaves exactly as the v4 companion does today: v1 art with pacing when `artwork` is valid (cc5.x), and text only on cc4.

## 2. Compatibility matrix

| Host \ Firmware | cc4 | cc5.2 | cc5.3 |
|---|---|---|---|
| desktop v2 (cc4-era) | text | v2 frames, text | v2 frames, text |
| desktop v3 (cc5.2-era) | text | v1 art, paced | v1 art, paced. The v1 path is unchanged |
| desktop v4 (this) | text, paced | v1 art, paced (no artwork2) | **artwork2**: JPEG covers, icons, prefetch, unpaced |

cc5.3 keeps the v1 `art` path and its 9 × 28,800 B store, allocated at boot as in cc5.2. `artKey` names **either** kind of cover:
- The LCD looks the key up in the artwork2 cover store first, then in the v1 store.
- Keys are content hashes of different payloads, so they cannot collide in practice.

## 3. Transport (only when artwork2 is negotiated)

**Host.**
- Writes each complete line in one `write()` call: no 64 B slicing, no sleeps. This applies to frames, controls, heartbeats, `diag`, `media` and everything else.
- **Stop-and-wait** for `media` lines: at most one `media` line is outstanding, and the next goes only after its `mediaAck`. `art` (v1) lines are never sent while artwork2 is negotiated.
- Frames stay coalesced to at most one per UI tick (25 ms), plus the 0.5 s heartbeat.
- In-flight bound: one media line (≤ 2.9 KB) plus at most two frame lines (≤ 1.1 KB each) is < 5.2 KB, under the 8 KB queue.
- If artwork2 is not negotiated, `PacedSerial` (64 B / 5 ms) stays in force exactly as today.

**Firmware.**
- `Serial.setRxBufferSize(8192)` before `Serial.begin()`, in internal RAM. It is guarded as in cc5.2, so `diag.rxQueue` still reports `internal`, `psram` or `default`, and `diag.rxQueueBytes` reports the size.
- The line buffer stays 4096 + NUL. A 2048-byte chunk makes a data line of about 2.9 KB, which fits.
- COM idle sleep is **1 tick** while any of these hold:
  - a partial line is pending;
  - `Serial.available() > 0`;
  - a `media` upload is receiving;
  - the last complete line was handled less than **20 ms** ago.

  Otherwise it stays 10 ticks, as in cc5.2. So stop-and-wait costs about 1–3 ms per line instead of about 10 ms.

`media` lines, like `art`, `diag` and `capabilities`, **never renew the lease**. The host keeps sending heartbeat frames during transfers.

## 4. The `media` command

One channel for both kinds. Every `{"media":{…}}` line is answered by **exactly one** `{"mediaAck":{…}}` line, in order.

### 4.1 Requests

| `op` | Fields (besides `id`, `op`, `kind`) |
|---|---|
| `begin` | `key`, `bytes` (int), `crc32` (int 0..0xFFFFFFFF, CRC-32/IEEE of the whole payload, as in `zlib.crc32`) |
| `data` | `key`, `offset` (int, the next expected byte), `data` (base64, standard alphabet with padding, decoded length 1..`chunkBytes`) |
| `commit` | `key` |
| `have` | `keys`: array of 1..`haveKeys` keys |

- `id`: int, the active control ID.
- `kind`: `"cover"` or `"icon"`.
- `key`: `[A-Za-z0-9_-]{1,24}`.

### 4.2 Replies

Success and error replies share one shape:

```json
{"mediaAck":{"id":7,"op":"begin","kind":"cover","key":"…","offset":0}}
{"mediaAck":{"id":7,"op":"data","kind":"icon","key":"…","offset":2048,"error":"Media offset mismatch"}}
{"mediaAck":{"id":7,"op":"have","kind":"cover","have":[true,false,true]}}
```

- `offset` is the number of payload bytes the store now holds for this upload. For `have` there is no `key`/`offset`; `have[i]` answers `keys[i]`.
- An error reply echoes whatever of `id`, `op`, `kind` and `key` parsed validly. It carries `offset` when an upload context matched, otherwise `offset` is 0.

### 4.3 Validation order and error strings

Checks run in this order. The first failure is the reply's `error`, and it changes no state unless noted.

1. Not valid JSON, or the line is oversize: the `parse` reply `{"mediaAck":{"op":"parse","error":"parse"[,"id":…][,"key":…]}}`. `id` and `key` come from a bounded 192-byte prefix scan, as for `art`, and appear only when found intact.
2. `op` missing or not one of the four: `"Unknown media operation"`.
3. `kind` not `cover`/`icon`: `"Unknown media kind"`.
4. Store for that kind not allocated: `"Media unavailable"`.
5. `id` is not the active control ID, or no session is `entering`/`ready`: `"Stale media control"`.
6. Per op:
   - **`have`:** `keys` missing, not an array, empty, or longer than `haveKeys`, or any key fails the pattern: `"Invalid media keys"`.
   - **`begin`:**
     - key fails the pattern: `"Invalid media key"`;
     - `bytes`/`crc32` missing, not integers, or outside 0..0xFFFFFFFF: `"Media size and CRC required"` (lead ruling, 2026-09-24);
     - cover `bytes` not in 1..`maxBytes`, or icon `bytes != 2048`: `"Invalid media size"`.
   - **`data`:**
     - key fails the pattern: `"Invalid media key"`;
     - no receiving upload, or its kind/key differ: `"No matching media upload"`;
     - `data` not valid base64, empty, or decoded > `chunkBytes`: `"Invalid media data"`;
     - `offset` + decoded length > `bytes`: `"Media chunk bounds"`;
     - `offset != received` and it is not an identical retry (4.4): `"Media offset mismatch"`.
   - **`commit`:**
     - key fails the pattern: `"Invalid media key"`;
     - no matching receiving upload or begin-hit context for this kind/key: `"No matching media upload"`;
     - `received != bytes`: `"Media upload incomplete"`;
     - CRC differs: `"Media checksum mismatch"`. The upload is cancelled.
     - cover payload not a baseline JPEG of exactly 240×240 decodable by the ROM TJpgDec (`cc_jpeg_validate`), **or** not ending in the EOI marker `FF D9` (trailing bytes are rejected; the host encoder never emits them): `"Media decode failed"`. The upload is cancelled.

`media` failures are **presentation-only**. The host reports them as `media-error` events and never disconnects for them. While a `media` line is outstanding, a bare `{"error":…}` parse or oversize reply is mapped to `media-error` for that key (one retry), exactly as the v1 art rule does. Every other `error` stays fatal, as today.

### 4.4 Store semantics (normative: the C++ store and the Python FakeKnob model must agree step for step)

Each kind has its own store: `S = entries + 1` slots of `slotBytes` (cover 32768, icon 2048).

Per slot:
- `valid`, `key`, `bytes`, `crc` (the committed image);
- `stamp` (uint32).

Per store:
- a `clock` (uint32, starts 0; `touch(slot)` sets `slot.stamp = ++clock`);
- `displayed` (slot index or −1);
- `frameKey` (the current frame's `artKey` for covers, `iconKey` for icons; empty when none).

One **global** upload context covers both kinds:
- `kind`, `key`, `bytes`, `crc`, `slot`, `received`, `hit` (bool), `lastChunkOffset`, `lastChunkLen`;
- `active` (bool).

**Pinned slots** of a store are:
- `displayed`;
- the valid slot whose key equals `frameKey`.

Pinned slots are never chosen as victims.

- **`have`.** For each key in order: true iff a valid slot holds it. Each hit is `touch`ed, in request order. Nothing else changes, and any upload in progress is **not** cancelled.
- **`begin`:**
  1. If a valid slot holds `key` with the same `bytes` and `crc` (**hit**): cancel any other active upload (its slot, invalid since its own begin, stays invalid), then set the context to `{active, hit:true, key, kind, slot, bytes, received:bytes}` and `touch(slot)`. Reply `offset = bytes`.
  2. Otherwise (**miss**): cancel any active upload (as in 1). Choose the victim in this store:
     - the lowest-index invalid slot, if any;
     - else the valid, non-pinned slot with the smallest `stamp` (ties: lowest index).

     Set `victim.valid = false` (**eviction happens at begin**), then set the context to `{active, hit:false, slot:victim, received:0}`. Reply `offset = 0`.

     If every slot is pinned (impossible with S ≥ 3; at most 2 pins), reply `"Media unavailable"`.
- **`data`:**
  - If `offset == received`: copy, add to the running CRC, set `received += len`, and remember `lastChunkOffset`/`lastChunkLen`.
  - Else if `offset == lastChunkOffset`, `offset + len == received`, and the bytes equal those stored: an **identical retry**. Accept with no change.
  - Reply `offset = received`.
  - A `data` for a hit context is `"No matching media upload"`, because it has no receiving slot.
- **`commit`:**
  - Hit context: reply `offset = bytes` and end the context. The slot stays valid.
  - Miss context: after the checks, invalidate any **other** valid slot of this store with the same key. Then set `slot.valid = true` with key/bytes/crc, `touch(slot)`, bump the global `mediaVersion`, end the context, and reply `offset = bytes`.
- **Cancellation.** An upload context ends when:
  - a new `begin` arrives (either kind);
  - `commit` succeeds or fails its CRC/decode check;
  - the control ID changes (a new `control`, or a release).

  The slot of a cancelled miss stays invalid. Committed slots **survive** releases, new controls and lease expiry until reboot.
- **Frame keys.** When a frame (or the frame embedded in `control`) is accepted, the store's `frameKey` becomes its `artKey` (covers) and `iconKey` (icons). An empty key is fine.
- **Display adoption (LCD).** When the LCD draws a key, `adopt(kind, key)` finds the valid slot, sets `displayed = slot` and `touch`es it, but only when `displayed` changes to that slot. When the LCD draws no media of a kind, `displayed = −1`.

**Parity rule.** The Python FakeKnob (`tests/tools/capture_session_frames.py`) implements this section exactly, including adoption. Adoption is modelled at frame acceptance: `adopt(frameKey)` if present, else `displayed = −1`. A frame naming a key that is committed later is adopted at that commit. The C++ store unit tests replay the same trace fixture (`harness/media_store_traces.json`) and must produce identical replies and identical slot tables after every step.

## 5. Payloads

**Cover** (`kind:"cover"`):
- A baseline (sequential, non-progressive) JFIF JPEG of exactly 240×240, 8-bit YCbCr.
- Chroma subsampling: 4:2:0 or 4:4:4.
- No restart-marker requirement. No EXIF, ICC or comment segments.
- At most 32768 bytes.

The pixels are the host's 240 px composited image, exactly as the v1 pipeline builds it before its 120 px reduction:
1. crop-fit to 240 with LANCZOS;
2. 0.8 opacity plus the scrim (`artwork._scrim_factor` stops);
3. no RGB565 quantisation before encoding.

**Host encoder:**
- Pillow `save(format="JPEG", quality=q, subsampling=2, optimize=True, progressive=False)`.
- Quality ladder q = 85, 80, 75, 70, 65, 60: the first result ≤ 32768 bytes is used. If none fits, there is no artwork2 cover for that item, and the frame's `artKey` is empty.
- `key = sha256(jpeg).hexdigest()[:24]`.

**Icon** (`kind:"icon"`):
- 32×32 RGB565 little-endian, row-major, 2048 bytes.
- Source: the host's 32×32 RGBA (IconWorker's LANCZOS `icon_thumbnail`), alpha-composited onto black as `c' = round(c·a/255)` per channel.
- Converted with rounding: `r5 = (r·31 + 127)//255`, `g6 = (g·63 + 127)//255`, `b5 = (b·31 + 127)//255`.
- `key = sha256(raw).hexdigest()[:16]`.
- The UWP host (`ApplicationFrameHost`) and windows with no icon send **no** icon, so the letter tile shows.

## 6. Frame

`artKey` (existing) names the cover to draw, of either kind (section 2).

`iconKey` (new, optional):
- `[A-Za-z0-9_-]{0,24}`, default "".
- Meaningful only on `layout:"windows"`: the selected entry's icon.
- Validated and stripped exactly like `artKey`: a malformed value is stripped, logged and never fatal.
- CCFrame gains `char iconKey[25]`.
- The host emits it only when artwork2 is negotiated, only on the windows layout, and omits it when empty (v4 slimming).
- The size budget (1100 B) applies unchanged. A 16-character key adds ≤ 29 B, and the section 8 trim order absorbs the rest.
- cc5.2 ignores the field (unknown fields are skipped).

## 7. LCD rendering (cc5.3)

**Covers.** Art layouts, fades, `artDim` (`image_opa` 112), the late-arrival fade (60 + 420 ms), the idle fade-out and "a stale cover is never shown" are all unchanged from contract v4 section 6. What changes:
- Two 240×240 RGB565 PSRAM buffers, **front** and **back** (2 × 115,200 B). The `lv_image` always shows the front buffer.
- When the key to draw changes:
  - `cc_media_adopt(cover, key)` hit: decode the JPEG with `cc_jpeg_decode_240` into the **back** buffer, then swap front and back, re-point the image source, and invalidate.
  - Else the v1 store has the key: upscale ×2 (existing bilinear) into the back buffer, then swap.
  - Else: no art.
- A decode failure counts `jpegDecodeErrors` and shows no art for that key until the key changes. There is no retry loop.
- The decode runs on the LCD thread. Its duration is measured with `esp_timer_get_time()` into `jpegDecodeMsMax`/`jpegDecodeMsLast`.
- Pixel format: whatever the existing `art240` buffer uses for `LV_COLOR_FORMAT_RGB565` (same byte order as `upscaleArt` writes). TJpgDec gives RGB888, and each channel is converted with rounding (`(r·31+127)/255` etc.).

**Icons (windows layout).**
- If `iconKey` is non-empty and `cc_media_adopt(icon, iconKey)` hits: copy the 2048 bytes into a static display buffer when the key changes. Show an `lv_image` child (32×32, `LV_COLOR_FORMAT_RGB565`, `recolor_opa` 0) that fills the tile, set the tile background transparent, and hide the letter.
- Otherwise draw the existing letter tile: `#444`, 16 px `#F2F2F2` initial. The tile is hidden when `subtitle` is empty.
- The closed entry (unavailable bit) keeps the whole tile group at opa 89 (0.35), icon or letter.
- The icon appears instantly when it arrives. There is no fade (the design specifies none).
- **Letter initial:** the first code point of `subtitle`, upper-cased when it is ASCII `a`–`z`. Other code points are drawn as-is. `lcd_preview.py` does the same.

## 8. Diagnostics (additive; `diag` capability stays 1)

| Field | Meaning |
|---|---|
| `rxQueueBytes` | CDC receive queue size actually configured (8192) |
| `mediaCommits` | Successful `media` commits since boot (both kinds) |
| `mediaErrors` | `media` error replies since boot (all ops, parse included) |
| `mediaEvictions` | Valid slots evicted at `begin` since boot |
| `jpegDecodes`, `jpegDecodeErrors` | LCD cover decodes attempted / failed since boot |
| `jpegDecodeMsMax`, `jpegDecodeMsLast` | Longest and last decode duration, in ms |

COM breadcrumb `op` names gain `media-begin`, `media-data`, `media-commit`, `media-have` and `media-other`. `arg` is the offset.

## 9. Host behaviour (desktop v4)

**Capability and transport.**
- `DeviceBridge` parses `artwork2` (section 1) after `capabilities`.
- When it is negotiated, the bridge switches the port to whole-line writes and exposes `media_capability` (a dict). Otherwise `media_capability` is None and everything is as today.

**Interfaces** (between `device.py` and `runtime.py`):
- `DeviceBridge.set_media_wanted(kind: str, items: list[tuple[str, bytes]]) -> None`:
  - Replaces the whole wanted list for `kind` (`"cover"`/`"icon"`). The list is priority-ordered: index 0 is what the knob shows now.
  - It is thread-safe: it is queued to the bridge thread like `submit`.
  - It is a no-op when `media_capability` is None.
  - The bridge copies nothing it does not need, and keeps at most `entries − 4` items per kind (20 covers, 44 icons). The rest are dropped and counted (`log` once per change).
- Events (existing event queue):
  - `("media-ready", {"kind","key"})` on commit or begin-hit;
  - `("media-error", {"kind","key","error"})` on an error reply, timeout or parse mapping.

**Push engine** (inside the bridge, per kind, both kinds sharing the single upload pipe):
- **Mirror.** A set of keys believed present. It is cleared on (re)connect and on `capabilities`. Keys are added on `have:true`, begin-hit and commit; removed on `have:false` and on any error for that key.
- **Have probe.** When the wanted list changes and its index-0 key differs from the last probed index-0, or when the list holds keys the mirror has not confirmed since the last probe, send one `have` with up to `haveKeys` keys:
  - index 0 first;
  - then every wanted key not confirmed in this connection, in wanted order.

  A `have` is a normal stop-and-wait media line.
- **Upload order.** Walk the wanted list in order, and upload the first key not in the mirror (begin → data… → commit). Then re-evaluate.
  - Covers take precedence over icons when both kinds have a missing index-0. Otherwise alternate by list position.
  - **Preemption:** if index 0 of a kind changes to a missing key while another key's upload is mid-way, finish at most the current line, then start the new index 0 with a fresh `begin`, which cancels the old upload on the knob.
- **Order of writes.** A frame naming a new `artKey`/`iconKey` is always written **before** any media line issued because of that selection change, so the knob pins it first.
- **Retries.** A per-line ack timeout of 1.5 s or an error aborts the upload.
  - The key is retried once after 1.0 s.
  - After a second failure the key is marked failed for this connection, and is not retried until reconnect or until it drops out of and re-enters the wanted list.
  - `"Stale media control"` after a control-ID change is not a failure: the engine simply re-evaluates with the new ID.
- **Control-ID binding.** Every media line carries the bridge's current control ID. A control change cancels the in-flight upload on the host too (the knob cancels its context).

**Runtime (wanted lists).**
- **Covers:**
  1. index 0 is the cover of what the knob shows now (Now Playing, Tracks or the selected Recent item), when prepared;
  2. then, when a Recent page is shown, the prepared covers of that page's items (More excluded) by distance from the selection (ties: the following item first);
  3. then the Now Playing cover, if not already listed.
  - Duplicates are removed, and the list is capped by the bridge.
- **Icons:** in Windows mode, index 0 is the selected window's icon, then the other windows of the frozen list by distance (ties: following first), deduplicated by key. Outside Windows mode the icon list is empty (the knob cache keeps the icons anyway).
- The wanted list is recomputed on every poll, but `set_media_wanted` is called only when a list changes.

**ArtworkService (prefetch).**
- When a Recent page is presented, the runtime calls `ArtworkService.prefetch(urls)` with the page's cover URLs ordered by distance from the selection.
- Prefetch jobs run on **3** worker threads with the existing allowlist, no-credential, no-redirect, size and time bounds.
- The foreground (current selection) request keeps its 0.12 s debounce and always runs before queued prefetch jobs.
- A selection change never cancels queued prefetch jobs of the same page. A new page or leaving Recent drops the queued ones that have not started.
- The LRU grows to 64 entries (`cache_size` clamp lifted to 128).

`ArtworkResult` gains:
- `jpeg: bytes | None` and `jpeg_key: str | None` (section 5), built in the same `prepare_artwork` pass as the v1 120 px payload.
- `raw`/`key` (v1) stay, so a cc5.2 knob still gets v1 art.
- `jpeg` is None when no ladder quality fits.

**Frame decoration.**
- With artwork2 negotiated, `artKey` = `jpeg_key` (empty if None), and `iconKey` = the selected window's icon key on the windows layout.
- Without it, as today (the v1 `key`, and no `iconKey`).

**Icons.** `artwork.icon_payload(rgba: PIL.Image.Image) -> tuple[str, bytes]` builds section 5's icon from IconWorker's 32×32 RGBA. The runtime caches payloads by window handle/icon identity.

**Mirror** (`lcd_preview.render_lcd`):
- With artwork2, the cover is the JPEG decoded with Pillow and quantised to RGB565 with rounding, drawn at 240 without upscaling.
- The Windows tile draws the icon exactly as section 7, from the same 2048-byte payload (decoded back from RGB565). It is no longer a deliberate difference from the knob.
- The letter tile upper-cases ASCII initials.
- Without artwork2 the mirror behaves exactly as today.

**Status.** `status.json` gains `artwork2` (bool, negotiated) and `media` with per-kind `wanted`, `present` (mirror size), `uploads`, `hits`, `errors`, `failedKeys` and `lastError`.

## 10. Verification (required before the hardware window)

- Python suite green: non-Tk modules during development, and the full suite at the window.
- Parser parity: `frames_v4.json` gains `iconKey` cases (valid, too long, bad characters, non-windows layout). Python and C++ must give identical accept/strip results.
- Store parity: `media_store_traces.json`, replayed through the C++ store (MSVC `/W4 /WX` and the `gnu++11` syntax gate) and through the Python FakeKnob, with identical replies and slot tables.
- JPEG glue: the harness compiles `cc_jpeg.cpp` against a shim that maps `esp_rom_tjpgd_*` to LVGL's bundled TJpgDec. It decodes the design sample covers encoded by the host encoder, and must meet all of these (lead ruling, 2026-09-24):
  - The decoder's RGB888 output, before the RGB565 conversion, is within PSNR ≥ 40 dB of a Pillow RGB888 decode of the same JPEG. This is the `decoder-rgb888` rule.
  - The glue's RGB565 conversion is bit-exact to the section 7 rounding formula applied to that RGB888 output, with 0 mismatching pixels.

  A direct RGB565-vs-RGB565 comparison amplifies one-level RGB888 differences at rounding boundaries into 8-level steps, so it is not used as the gate. Progressive, oversize, non-240 and trailing-byte JPEGs must be rejected by `cc_jpeg_validate`.
- LVGL harness (`cc5-handoff`) plus `cc5_report.py`, with new checks:
  - 240 cover frames render at full resolution;
  - the Windows tile with an icon (open, and closed at opa 89), and without an icon (letter tile, upper-cased);
  - no animation on a heartbeat-identical frame;
  - LVGL heap ≤ 50 %.
- Transport model: a FakeKnob/ArtSerial CDC model with an 8192-byte queue, 1- and 10-tick drains and injected 30–100 ms COM stalls. The host's unpaced stop-and-wait engine must never overflow it, and must recover from a dropped or corrupted line through the retry rule.
- Light tests unchanged (`light_tests.py` 2,174,149 checks). PlatformIO build under 0x140000.
- Hardware (Stage 10 checks, extended):
  - v1 art still works (compatibility);
  - artwork2 cover and icon round trips;
  - `have`;
  - prefetch of non-current keys accepted and kept;
  - pinning (the frame's key is never evicted);
  - decode time (`jpegDecodeMsMax` ≤ 200 ms, `jpegDecodeErrors` 0; see 12.11);
  - unpaced stress (untouched, and while turning) with frames and media transfers at full speed;
  - the 20-minute soak with media traffic (covers, icons, have, prefetch);
  - every cc5.2 liveness and reboot gate.

## 11. Page lookahead and Home warm-up (desktop v4, host only; user request 2026-09-24)

Goal (user): "once we finish preloading the first 11 items on the first page, preload the second page. After navigating to the second page, load the next/third page, and so on, so that the album artwork is always preloaded."

No firmware or wire change. The knob cache (24 covers) and the bridge cap (`entries − 4` = 20) hold the current page (≤ 10 covers; More has none) plus the next page (≤ 10 covers).

### 11.1 Next-page list prefetch (controller)

**Trigger.** Every time a Recent page is presented, the controller issues **one** background list request (`kind:"recent"`, `prefetch:true`, `cursor = pages[page]["next"]`, `page = page + 1`) when all of these hold:
- not `loading`;
- the page has a `next` cursor;
- `page + 1 == len(pages)` (the next page is not loaded);
- no prefetch for that page is already in flight.

"Presented" means:
- after a page result;
- after More or Back moves to an already-loaded page;
- on resume.

**Invisibility.** A prefetch request is invisible:
- no `loading` or status text, no pulse, no flash, no desktop notice, no failure copy;
- it never changes `page`, `index` or the control ID;
- it never re-enters (no new control).

**Result.** When the prefetch returns and the Recent session that issued it is still the current Recent screen (same `Screen` object), and `page == len(pages)`, the page is appended to `pages`, and nothing else changes. The page's `More` item appears on the current page unchanged: it is already there, since the current page has `next`.

**Errors.** A prefetch error is silent. The next More press falls back to today's foreground load ("Loading next page…").

**More while a prefetch is in flight.** Pressing More while the prefetch for the next page is in flight does **not** issue a second request. The controller:
1. sets `loading = True` and "Loading next page…", exactly as today;
2. adopts the in-flight request as the foreground one, so its result navigates as a normal page result would (page, index 0, re-enter);
3. if it fails, shows today's failure behaviour.

**Session scope.** Leaving Recent (Home, Windows, play) or starting a new Recent session drops the prefetch, and its late result is ignored. Resuming Recent from Windows re-evaluates the trigger.

**Chaining.** After More moves to page N+1 (instantly, because it was prefetched), presenting it triggers the prefetch of page N+2. So the list is always one page ahead.

### 11.2 Cover prefetch order (runtime)

When a Recent page is presented, the runtime calls `ArtworkService.prefetch(urls)` with:
1. the current page's cover URLs by distance from the selection (ties: following first);
2. **then** the next page's cover URLs in index order, when the next page is loaded (prefetched).

When the next page arrives later, the runtime re-issues the prefetch with the combined list. Already-cached or already-queued URLs are not fetched twice.

Ring accents: when the next page is loaded, its accent URLs are requested too (`AccentService.request_many`), after the current page's.

### 11.3 Knob wanted list (runtime, covers)

1. index 0: the current cover;
2. the current page by distance;
3. **then the next page's prepared covers in index order**;
4. then Now Playing.

The bridge caps this at 20, so on a full page the Now Playing cover falls off the end.

### 11.4 Home warm-up (runtime)

While the controller is on Home (`volume` mode) and connected:
- The runtime keeps a background copy of Recent page 1 (`recent` list, cursor None, `page 0`), fetched off the UI thread through the same Apple Music client and bounds the controller uses:
  - once 10 s after startup;
  - then every **10 minutes**;
  - and immediately after leaving Recent: use the page 1 the controller already holds, with no extra request.
- Its cover URLs are prefetched into `ArtworkService`.
- Its prepared covers are appended to the Home wanted list after Now Playing (≤ 10).

Entering Recent still fetches page 1 fresh, exactly as today ("Loading library…"). The warm-up changes no text, list or behaviour. Covers whose content is unchanged have the same `jpeg_key`, so they are already on the knob and appear instantly.

Warm-up errors are silent and retried at the next 10-minute tick. The warm-up never runs:
- without Apple Music credentials;
- while the Recent auth state is "sign-in expired";
- when artwork is disabled in Settings.

### 11.5 Tests

**Controller:**
- a prefetch is issued on presentation;
- it is invisible (frames unchanged except nothing);
- More after the prefetch completes is instant (no `loading` frame);
- More during an in-flight prefetch adopts it;
- a prefetch error is silent, then More falls back;
- leaving Recent drops it;
- chaining N → N+1 → N+2;
- Back to an earlier page issues no new request;
- resume from Windows.

**Runtime:**
- the prefetch URL order;
- the wanted order with the next page;
- the cap interplay;
- the Home warm-up schedule;
- warm-up covers named on Home;
- no warm-up without credentials or when artwork is off;
- no UI-thread network.

**Session capture:** `capture_session_frames.py` still produces valid frames, and the frames-v4 parse gate still passes.

## 12. Lead rulings (2026-09-24)

These rulings were made by the lead (Claude, working with the user who owns the knob) after the first implementation pass. They are normative, and the code and tests follow them.

1. **`rxBytes`** reports the queue size actually configured. It is 0 in PSRAM and 256 for the default queue. Any value other than 8192 fails the host's exact-match gate, and the host falls back to paced v1 (section 1).
2. **`bytes`/`crc32`** that are not integers in 0..0xFFFFFFFF get `"Media size and CRC required"` (section 4.3).
3. **Trailing bytes** after the JPEG EOI marker are rejected with `"Media decode failed"` (section 4.3).
4. **The JPEG glue gate** is the `decoder-rgb888` rule (section 10).
5. **Dispatch order.** A line that holds `capabilities`, `diag` or `art` as well as `media` gets only the reply of the first of those that the cc5.2 dispatch order handles, and no `mediaAck`. The host never sends such lines. The rule "exactly one mediaAck per media line" applies to lines that hold only `media`.
6. **Display-buffer reuse.** The LCD may draw a cover whose pixels one of its two art buffers still holds, even when neither store holds the key any more. Keys are content hashes, so those pixels are exactly that cover; the store's `displayed` pin is then −1. Icons never do this. Hosts and the FakeKnob must not assume that a store miss means no art on the LCD (section 7).
7. **Host event shape.** Events use the existing event-queue form:
   - `{"kind":"media-ready","media":"cover"|"icon","key","hit"}`;
   - `{"kind":"media-error","media","key" ("" for a have),"op","error","retrying","failed"}`.
8. **Grace hold.** After a per-line timeout, or a bare `{"error":…}` mapped to a media line, that line stays outstanding until a reply matches it or its grace ends: `MEDIA_LINE_GRACE` 2.0 × the 1.5 s ack timeout, so 3.0 s after it was written. A retry therefore comes at max(failure + 1.0 s, write + 3.0 s). Replies carry no sequence number, so this keeps every reply attributed to its own line.
9. **Host mirror.** The host's mirror follows the knob's LRU conservatively: a key leaves it once `entries − 3` other keys may have been touched since its confirming line. So `present` ≤ `entries − 3`, and a still-wanted key that leaves the mirror is probed again with `have`.
10. **Idle sleep.** COM keeps its 1-tick idle while an upload the host abandoned is still receiving, until the next `begin`, `control`, release or lease expiry (section 3). A 1 ms poll costs only a few microseconds per wake, and liveness is unaffected.
11. **Decode-time gate: 200 ms.** The hardware gate on `jpegDecodeMsMax` is ≤ 200 ms (section 10), raised from 150 ms. The first cc5.3 hardware run (2026-09-24) measured 150 decodes with 0 errors:
    - most took 50–130 ms, the last one 84 ms;
    - the maximum was **151 ms**, under the heaviest simultaneous COM and LCD load.

    Every liveness, stress and soak gate passed. The user then tried scrolling Recent by hand, found covers fast and sharp and scrolling fine, and approved the higher limit. The 150 ms figure had been a pre-hardware estimate with margin, not a derived requirement.
