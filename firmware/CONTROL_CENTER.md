# Control-center extension (1.0.0-cc5.3)

The control center lets one host (the Desk Dial desktop companion) own the knob
over USB CDC for a session: it installs runtime-only detent bounds, draws the LCD
and LEDs from host frames, and receives tagged turns and presses. Nothing is
persisted: no profile, calibration, setting or motor gain is saved or changed.
When the host releases the knob, or stops renewing its lease, the firmware hands
control back to the native UI.

The build identifies itself as `1.0.0-cc5.3` (`NANO_FIRMWARE_VERSION` in
`platformio.ini`, printed at boot and reported as `firmwareVersion` by
`{"settings":"?"}`).

**1.0.0-cc5.3: artwork2.** cc5.3 keeps the presentation contract (`presentation` 4), the
v1 `artwork` capability, the `art` command, its error strings, its binding rule and its
120 px store byte-identical, so a cc5.2-era companion works unchanged. It adds what
[ARTWORK2.md](ARTWORK2.md) specifies (the normative contract for everything below):

- The sibling capability `artwork2` (see [Capabilities](#capabilities)).
- The `media` command: 240×240 baseline JPEG covers and 32×32 RGB565 app icons pushed into
  two PSRAM stores (24 covers and 48 icons, each plus one staging slot) with `have`,
  `begin`, `data` and `commit`, bound to the active control ID, with knob-side prefetch
  (see [Media upload](#media-upload-artwork2-100-cc53)).
- The optional frame field `iconKey` (the selected Windows entry's icon).
- An 8192-byte CDC receive queue in internal RAM, so a host that negotiated artwork2 writes
  whole lines without the 64 B / 5 ms pacing, and a 1-tick COM sleep while lines keep
  arriving (see [Serial protocol](#serial-protocol)).
- Additive `diag` fields: `rxQueueBytes`, `mediaCommits`, `mediaErrors`, `mediaEvictions`,
  `jpegDecodes`, `jpegDecodeErrors`, `jpegDecodeMsMax`, `jpegDecodeMsLast`, and the COM
  breadcrumbs `media-begin`, `media-data`, `media-commit`, `media-have`, `media-other`.

ARTWORK2.md section 11 (page lookahead and Home warm-up, desktop v4) needs no firmware change:
see [Page lookahead and Home warm-up](#page-lookahead-and-home-warm-up-desktop-v4). The lead's
rulings on the first implementation pass are ARTWORK2.md section 12; the notes below cite them.

**1.0.0-cc5.2 and the superseded 1.0.0-cc5.1.** cc5.1 was installed on 2026-09-23
and fixed cc5's reset: four check runs without a reboot, healthy stacks, the untouched
stress passed three times. In the third run the HMI task **hung inside `FastLED.show()`**
about 9 s into the untouched stress (heavy frames and cold art transfers). After a software
reset the RTC breadcrumbs showed `previous.hmi.step` `show` at uptime 700,236 ms while the
COM and LCD breadcrumbs ran on to about 3,784,782 ms. The ring and button LEDs froze, the
buttons were dead, and no release could complete (HMI never acknowledged it), so every new
control was refused with "Control ID must advance". LCD and FOC kept running, so the native
screen and the haptics worked, no watchdog fired and no core dump was written. The knob was
rolled back to cc4. The cause is a task/interrupt race in FastLED 3.6.0's own ESP32 RMT
driver (see [LED transport](#led-transport-100-cc52)), latent in cc4 too but exposed by
cc5's heavier core-0 load. cc5.2 keeps the presentation contract and the logical LED model
unchanged and adds:

- A **hang-proof LED transport**: FastLED keeps `show()`, brightness, colour correction,
  the dither gate and the pixel pipeline; only its clockless RMT driver is replaced by a
  project-owned sender on the ESP-IDF RMT driver with the same pins, colour orders, RMT
  channels and bit timing, where every wait is bounded and a failed channel is recovered
  and counted (`cc_led_rmt.*`, `cc_led_wire.*`).
- A **task watchdog** (10 s, panic, core dump) on the HMI, LCD and COM tasks
  (see [Task watchdog and liveness](#task-watchdog-and-liveness-100-cc52)).
- **Release robustness:** once the motor has restored the native profile, a release still
  waiting for the LEDs (HMI) or the LCD after 1 s completes with reason `forced`, naming
  the subsystem that did not acknowledge, and is counted.
- **Liveness in `diag`:** per-task ages (`hmiAgeMs`, `lcdAgeMs`, `comAgeMs`, `focAgeMs`) and
  steps, the watchdog subscription, the session phase, `releasePendingMs`,
  `forcedReleases`, and the LED transport counters (`ledTxTimeouts`, `ledWriteErrors`,
  `led` per strip). LCD and COM also keep an RTC heartbeat, so `previous` says when each
  task last completed a pass.
- Hygiene: HMI copies the 1040-byte host frame only when the presentation changed (as the
  LCD already did), and its two debug lines never wait on a full USB buffer.

**1.0.0-cc5.1 and the superseded 1.0.0-cc5.** The first cc5 build (`1.0.0-cc5`)
was installed on 2026-09-23 and reset once during the post-flash stress check,
with no panic output and no core dump; the knob had not been turned (that run's
extra cold art transfers only filled the cover cache before the stress). It was
rolled back to cc4 and never finalized. cc5.1 keeps the presentation contract
unchanged and adds:

- Task stacks with at least twice the worst case: HMI 4608 -> 9216 B (628 B were
  free), LCD 8192 -> 12288 B. HMI no longer builds a 2.9 KB `hmiConfig` on every
  10 ms pass: queued configs are received in out-of-line helpers.
- The 4 KB CDC receive queue (a FreeRTOS kernel object) in internal RAM; in cc5
  the PSRAM malloc threshold had put it in PSRAM.
- Bounded control-center replies: no unbounded `USBCDC::write()` spin when the
  host stops reading (`cc_serial_out`).
- Reboot detection and reset attribution in `{"diag":"?"}` (see Diagnostics).

**What a frame means is defined in [PRESENTATION_V4.md](PRESENTATION_V4.md),
the frozen cc5 presentation contract.** It covers frame and ring fields,
compatibility with older hosts and firmware, the LED model, LCD layouts and art
rules, error handling, the frame size budget, deliberate deviations from the
design, and the C++11 rules. This document covers the session protocol and where
the firmware implements it.

## Build (compile only)

```powershell
$env:PLATFORMIO_CORE_DIR='<pio-core>'
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' -m platformio run -d '<repo>\firmware'
```

- Environment `nanofoc_d`. Dependencies are pinned in `platformio.ini`: LVGL 9.0.0, ArduinoJson 7.0.2, FastLED 3.6.0 and the others.
- The short `PLATFORMIO_CORE_DIR` (the `pio-knob` junction points at `tools/platformio-core`) avoids GCC's command-line length limit on Windows.
- Output: `.pio/build/nanofoc_d/firmware.bin`.

Building does not flash. Installation writes the application image to the
verified application partition only. It never erases flash, uploads the
filesystem, replaces the partition table or writes NVS or calibration. The
procedure and rollback are in `app/firmware/RECOVERY.md`
and the cc5 install scripts. `app/firmware/manifest.json`
records which build is installed.

## Architecture

| Source (`src/`) | Role |
|---|---|
| `control_center.cpp/.h` | Session state and command handling: `capabilities`, `diag`, `art` dispatch, `media` dispatch (1.0.0-cc5.3), `release`, `control`, `frame`, and refusal of configuration changes while claimed. Lease bookkeeping. Presentation-change counter for the LCD and HMI (it includes `cc_media_version()`). The release acknowledgement timeout (`forced`, 1.0.0-cc5.2). The FOC liveness stamp (in `cc_take_request`, which FOC calls every loop). 1.0.0-cc5.3: the frame keys of every accepted frame and control go to the media stores (pins), and the media upload is cancelled whenever the active control ID changes (a new control, a release, a lease expiry). `harness/media_tests.py` runs this wiring on the host (a verbatim copy of the unit with the real `cc_media.cpp` and `cc_frame_parse.cpp`, stubs for the rest). |
| `cc_media_store.h` | The artwork2 store and `media` request handler (1.0.0-cc5.3, ARTWORK2.md section 4): per-kind slot tables, clock, displayed slot and frame-key pins, the global upload context, validation order and error strings, replies, the parse-reply prefix scan, CRC-32 and base64. Platform-neutral and header-only; `harness/media_tests.py` replays the shared trace fixture through it. |
| `cc_media.cpp/.h` | The ESP wrapper (1.0.0-cc5.3): the two PSRAM stores (25 × 32768 B and 49 × 2048 B; fail-soft), the mutex shared by COM and LCD, the `media` command and parse replies, breadcrumbs, counters, the capability object, and the LCD's `cc_media_adopt` / `cc_media_release_display` / `cc_media_version`. |
| `cc_jpeg.cpp/.h` | Cover JPEG glue over the ESP32-S3 ROM TJpgDec (1.0.0-cc5.3): `cc_jpeg_validate` (COM, at commit: SOI first and EOI as the last two bytes, baseline, 3 components, exactly 240×240, at most 32768 B; the scan itself is decoded only by the LCD) and `cc_jpeg_decode_240` (LCD: RGB888 to the art buffer's RGB565 with rounding, timed into `jpegDecode*`). Each thread has its own static 4 KB work area. Compiled unchanged on the host through `harness/tjpgd_shim`. |
| `cc_diag.cpp/.h` | Reboot detection and reset attribution (1.0.0-cc5.1): reset reasons, the RTC boot counter, per-task breadcrumbs in RTC memory, the read-only core dump check and the receive-queue location, all reported by `diag`. 1.0.0-cc5.2: per-task liveness (RAM) and RTC heartbeats for LCD and COM, and the task watchdog helpers (`cc_wdt_*`). 1.0.0-cc5.3: the media breadcrumbs (the COM operation field is 5 bits now, with a new RTC magic), the receive-queue size (`cc_boot_rx_queue_internal_bytes()` is the capability's `rxBytes`; `diag` `rxQueueBytes` is the size actually configured), the LCD `decode` breadcrumb, and the media and JPEG `diag` fields. Firmware-only. |
| `cc_led_rmt.cpp/.h` | The LED transport (1.0.0-cc5.2): `CCLedController<ORDER, LEDS>`, a FastLED `CPixelLEDController` that makes the bytes exactly like FastLED's clockless controller, and `CCRmtStrip`, which sends them on one RMT channel through the ESP-IDF 4.4 driver with bounded waits, recovery and counters (`diag` `led`). Firmware-only. |
| `cc_led_wire.cpp/.h` | The WS2811 RMT item encoder (1.0.0-cc5.2): FastLED's WS2811 bit timing as RMT items, MSB first. Platform-neutral. |
| `cc_serial_out.cpp/.h` | Bounded, yielding writes for every control-center reply, artAck, knob and key event and error (1.0.0-cc5.1). COM thread only. |
| `cc_frame_parse.cpp/.h` | **The contract-v4 frame parser** (`cc_parse_frame`, `cc_json_uint`, `cc_json_text`). Platform-neutral. `control_center.cpp` calls it for the frame embedded in `control` and for every `frame`. 1.0.0-cc5.3: `iconKey`. |
| `cc_presentation.h` | `CCFrame` (1.0.0-cc5.3: `iconKey[25]`), `CCButton`, wire enums, LCD ink tokens, shared helpers. |
| `cc_display.cpp/.h` | LCD renderer. One retained LVGL 9 tree with semantic diffing, the art layer and the host-lost notice screen. |
| `cc_lights.cpp/.h` | LED model: ring and button tones, pulses, damping and flashes (contract section 5). |
| `cc_icons.cpp/.h`, `fonts/cc_font_*.c` | A8 footer and idle-row icons. Montserrat Medium text fonts with the latin-ext-a glyph set (generated by `harness/gen_lvgl_font.py`). |
| `cc_artwork.cpp/.h`, `cc_art_store.h` | Art upload protocol and the PSRAM cover store: 8 cached covers plus 1 staging slot. |
| `com_thread.cpp` | Non-blocking line assembly, command dispatch, art and media parse replies, input-event tagging. COM breadcrumbs. Task watchdog: fed per pass and per handled line, unsubscribed around `save`/`load` (1.0.0-cc5.2). 1.0.0-cc5.3: 1-tick sleep while a media upload is receiving or a line was handled less than 20 ms ago; the line assembly, the bad-line reply choice and the sleep rule are platform-neutral helpers in `cc_media_store.h`. Task stack 12000 B. |
| `foc_thread.cpp` | Applies `control` and release requests to the motor. Checks the lease. Rebases setup motion. Task stack 8192 B (unchanged; reported as `stackFoc`). |
| `hmi_thread.cpp` | Tagged button events, the F24 pulse, LED rendering, native input suppression. HMI breadcrumbs and the uptime heartbeat. Registers the two LED strips with FastLED (ring: RMT channel 0, GPIO 38, RGB; buttons: channel 2, GPIO 42, GRB). Task watchdog fed per pass (1.0.0-cc5.2). Task stack 9216 B. |
| `lcd_thread.cpp` | Host screen, native handback, host-lost notice, LVGL `diag` sampling. LCD breadcrumbs. Task watchdog fed per pass (1.0.0-cc5.2). 1.0.0-cc5.3: two 240×240 RGB565 art buffers in PSRAM (front and back, fail-soft: one buffer decodes in place, none renders text only), the artwork2 lookups for `cc_display` (`cc_media_adopt`, `cc_media_release_display`, and `cc_jpeg_decode_240` under the `decode` breadcrumb), both display pins released at the handback. Task stack 12288 B. |
| `haptic.cpp`, `haptic_bounds.h` | Runtime rebase of the detent profile. Boundary recovery that yields within 2 ms and steps inward from the endpoint actually hit. |
| `main.cpp` | Records the reset reason first, then sets the task watchdog to 10 s with panic (1.0.0-cc5.2). 8192-byte CDC receive buffer (4096 B before 1.0.0-cc5.3), allocated in internal RAM (the PSRAM malloc limit is raised to 16384 for it and restored only when PSRAM initialised; after a failed PSRAM init the malloc policy is never touched). Initialises the art store and the media stores and checks the core dump partition (read-only) before any thread starts. |

**Session phases.** A session moves through idle → entering → ready →
releasing → idle. The state is guarded by one spinlock in `control_center.cpp`.

1. An accepted `control` posts one request to the FOC thread.
2. The FOC, HMI (LEDs shown) and LCD (frame rendered) threads each report the control ID they applied.
3. When all three match, the FOC thread rebases any motion made during setup, and the COM thread replies `ready`.

A release goes the other way: the FOC thread restores the native profile and acknowledges,
and HMI and LCD acknowledge once they no longer show the host frame. Since 1.0.0-cc5.2 the
motor acknowledgement is always waited for, but a missing HMI or LCD acknowledgement is not
waited for longer than 1 s (see [Release](#release)).

Frames are presentation only. They never touch the FOC thread, a profile or a
detent.

**Unchanged from earlier builds.** The vendor's regular-detent motor
implementation, force curve and motor gains. A `control` copies an existing
named profile into runtime-only state. Only the logical bounds, the initial
index and the detent origin change.

## Serial protocol

- Newline-delimited JSON over USB CDC at 115200 baud.
- The host opens the port with DTR/RTS asserted, as verified with this kit.
- One host owns the port. The companion writes in 64-byte chunks with 5 ms gaps, unless it
  negotiated artwork2 (1.0.0-cc5.3): then it writes each complete line in one `write()` and
  keeps at most one `media` line outstanding (stop-and-wait on its `mediaAck`), which fits the
  receive queue (ARTWORK2.md section 3).
- The CDC receive queue is **8192 bytes** in internal RAM (1.0.0-cc5.3; 4096 before).
  `diag` `rxQueueBytes` reports the size actually configured (256 when the core's default
  queue had to be kept). `capabilities` `artwork2.rxBytes` reports it only while the queue is
  in internal RAM, and 0 when it landed in PSRAM anyway (`diag` `rxQueue` `psram`): the host
  writes unpaced only against `rxBytes` 8192, so either failure keeps it paced on v1 art
  (ARTWORK2.md section 12, ruling 1).
- The COM thread sleeps 1 tick between passes while a partial line is pending, more bytes are
  queued, a media upload is receiving, or a complete line was handled less than 20 ms ago;
  otherwise 10 ticks, as in cc5.2 (1.0.0-cc5.3). The line assembly, the choice of reply for an
  oversize or non-JSON line and this sleep rule live in `src/cc_media_store.h`
  (`CCLineAssembler`, `cc_bad_line_reply`, `cc_com_idle_ticks`), so `media_tests.py` checks the
  code `com_thread.cpp` runs. Accepted limit (ratified by the lead: ARTWORK2.md section 12,
  ruling 10): an upload the host gives up on
  after a `data` or `commit` error that leaves the context open (`Media offset mismatch`,
  `Invalid media data`, `Media chunk bounds`, `Media upload incomplete`, or a lost line) keeps
  "receiving" until the next `begin`, control, release or lease expiry, so COM keeps its 1-tick
  idle meanwhile (about ten times the cc5.2 wake-up rate on core 0, each pass still yielding a
  tick; no liveness or watchdog risk). ARTWORK2.md sections 3 and 4.4 fix both rules as written;
  a time bound on either is a contract change.
- Only the first JSON value of a line is read (ArduinoJson's `deserializeJson`): anything after
  it is ignored without a reply. A line whose newline was lost is therefore handled as its own
  first command, and the line glued to it is dropped silently; the companion's heartbeat
  replaces a dropped frame. The FakeKnob reads lines the same way.
- A command line may be up to **4096 bytes** before its newline.
  - An oversize line gets exactly one reply: `{"error":"Command too large"}`, or the art `parse` reply for an art line, or the media `parse` reply for a media line (1.0.0-cc5.3). The rest of the line is discarded through its newline.
  - A partial line that stalls for 2000 ms is dropped.
- A line that is not JSON gets `{"error":"JSON parse error","msg":…}`. An art line gets the art `parse` reply instead, and a media line the media `parse` reply.
- Replies are written only as fast as the 64-byte USB transmit buffer drains. If the host keeps the port open but stops reading for 250 ms, the rest of that reply is dropped and counted (`diag` `txStalls`, `txDroppedBytes`); the firmware never spins on a full buffer. A reply cut after part of it went out is ended with `\n` at once if the buffer has room, otherwise the next reply starts with `\n`, so a host loses only the cut reply (one unparseable line, or an empty one) and never the reply after it.

### Capabilities

`{"capabilities":"?"}` returns:

```json
{"capabilities":{"controlCenter":1,"leaseMs":2000,"hostFrame":1,"runtimeProfileBounds":1,
 "taggedInput":1,"windowsHidKey":"F24","buttonOrder":1,"windowsHidControl":1,
 "presentation":4,"glyphs":"latin-ext-a",
 "artwork":{"version":1,"width":120,"height":120,"format":"RGB565_LE","chunkBytes":384,
            "cacheEntries":8,"available":true,"composited":"scrim80"},
 "artwork2":{"version":1,"available":true,"composited":"scrim80","paced":false,"rxBytes":8192,
             "chunkBytes":2048,"haveKeys":24,
             "cover":{"width":240,"height":240,"format":"JPEG","maxBytes":32768,"entries":24},
             "icon":{"width":32,"height":32,"format":"RGB565_LE","bytes":2048,"entries":48,"background":"black"}},
 "diag":1}}
```

- 1.0.0-cc5.6 adds `"appCanvas":1` after `"glyphs"` ([App canvas](#app-canvas-a2-100-cc56)).
- 1.0.0-cc5.7 adds `"feel":1,"hapticFx":1,"knobSound":1,"offlineVolume":1,"recalibration":1,"knobVolume":1` after `"appCanvas"`
  ([Feel and sound](#feel-and-sound-r4-100-cc57)).
- App profiles add `"appProfiles":1,"appProfileSlots":4,"appProfileMaxBytes":32768,"appProfileFeatures":31` after
  `"knobVolume"` ([App profiles](#app-profiles-upload-and-store)); `appCanvas:1` stays.

- `artwork.available` is false when the PSRAM cover store could not be allocated. Text controls are unaffected.
- `artwork2` (1.0.0-cc5.3) is added after `artwork`, with the fields in ARTWORK2.md section 1
  order; every other key is byte-identical to cc5.2. `artwork2.available` is false when either
  media store (or their mutex) could not be allocated; the host then uses v1 art, or none.
  `rxBytes` is the receive queue actually configured while it is in internal RAM (8192; 256
  with the core's default queue; 0 when it landed in PSRAM). The host uses artwork2 only when every
  listed field has exactly this type and value (`harness/media_tests.py` compares the
  object byte for byte with the companion's `presentation.ARTWORK2_CAPABILITY`).
- `glyphs:"latin-ext-a"` means U+0020–007E, U+00A0–017F and · – — ‘ ’ “ ” • …. A host treats `presentation` < 4 as legacy (contract section 2).

### Control (enter)

`{"control":{…}}` fields:

| Field | Rule |
|---|---|
| `id` | 1..0x7FFFFFFF. While a session is active it must be greater than the current ID. |
| `profile` | Name of an existing installed profile. Its first knob value must be a regular, non-progressive detent profile. |
| `min` | 0 |
| `max` | 0..65535 |
| `position` | min..max |
| `windowsButton` | Raw button index 0..3 |
| `buttonOrder` | Optional. A permutation of 0..3 mapping physical left-to-right positions to raw indices. Default identity. |
| `windowsHidEnabled` | Optional boolean, default true |
| `feel` | 1.0.0-cc5.7, optional: an r4 feel token ([Feel and sound](#feel-and-sound-r4-100-cc57)); absent = the preset's legacy feel |
| `reducedHaptics` | 1.0.0-cc5.7, optional boolean, default false |
| `sound` | 1.0.0-cc5.7, optional int 0..3 (off, Low, Medium, High = volume 0 / 40 / 70 / 100 %), default 0 |
| `soundVolume` | 1.0.0-cc5.7 (`knobVolume`, 2026-09-30), optional int 0..100: the master volume percent; overrides `sound` |
| `frame` | A complete contract-v4 frame |

Errors:

- `{"error":"Invalid control or unknown existing profile"}`
- `"Control center requires an existing regular non-progressive preset"`
- `"Invalid button order"`
- `"Windows HID enable must be a boolean"`
- `"Control ID must advance; wait for release before reconnecting"`: the ID did not advance, or a release is in progress.
- 1.0.0-cc5.7: `"Invalid feel token"`, `"Reduced haptics must be a boolean"`, `"Invalid sound level"`.

Once motor, LEDs and LCD have applied the entry, the knob replies
`{"ready":id,"p":position}`. The frame embedded in `control` is what the knob
shows at that point. Motion during setup is rebased, not reported as a turn. The
motor applies no detent torque until then.

### Frame and heartbeat

`{"frame":{"id":id,…}}` replaces the presentation of the current entry and
renews the lease. It changes nothing else and is not acknowledged.

- `{"error":"Invalid control frame"}`: the frame does not parse.
- `{"error":"Stale control frame"}`: its ID is not the current entry's, or no session is active.
- `iconKey` (1.0.0-cc5.3, optional, `[A-Za-z0-9_-]{0,24}`): the selected Windows entry's app
  icon. It is kept only on the windows layout (a legacy frame whose mode derives `windows`
  counts). Unlike the strict optional fields, a malformed `iconKey`, or one on any other layout,
  is stripped (stored as "") and never rejects the frame, matching the host's stripping.
- Every accepted frame (and the frame embedded in an accepted `control`) hands its `artKey`
  and `iconKey` to the media stores as their frame keys: the valid slot holding a frame key is
  never evicted (ARTWORK2.md section 4.4).

The host sends a current frame at least every **500 ms**. The companion's
DeviceBridge re-sends the latest frame after 0.5 s without one, and the runtime
sends a frame whenever it changes. An identical (heartbeat) frame starts no
animation and re-sets no text.

### Feel and sound (r4, 1.0.0-cc5.7)

The normative spec is [HAPTICS.md](HAPTICS.md) (plan stages F2 and F3). On the wire:

- **Control** `feel` (`detent.value`, `detent.dimmer`, `detent.list`, `detent.coarse`, `detent.fine`, `fluid.scrub`,
  `fluid.light`, `free.spin`), `reducedHaptics` and `sound` (0..3), each per control, never stored; a release restores
  the native profile, legacy and silent. A control without them runs the 1.0.0-cc5.6 haptic loop exactly.
- **Frame** `haptic`: `{"token": "confirm.tick" | "confirm.thump" | "confirm.off" | "nudge.left" | "nudge.right" |
  "refuse.buzz" | "error.buzz", "seq": 1..0x7FFFFFFF}` on any layout, the strict rule (`Invalid control frame`). Each new
  seq plays once; a claim seeds it. Desk Dial keeps the newest event in every frame until the next.
- **Recalibration**: `{"recalibrate":true}` or `{"recalibrate":{"acceptDirection":true}}` (refused while claimed, as
  before) answers `{"calibrating":true}`, then `{"calibrated":{"ok":bool,"reason":...}}` (HAPTICS.md section 11). The
  plain-text "Recalibrating motor" line is gone.
- **Offline volume**: the HID interface gains a Consumer Control collection as report ID 4; while no host has the port
  open for 2 s the knob steps the PC's volume (HAPTICS.md section 9). Nothing else about USB changes.
- **Diag** (additive): `supplyVolts`, `feel`, `reducedHaptics`, `soundLevel`, `fxPlayed`, `fxPulses`, `fxDropped`,
  `wallHits`, `wallDir`, `foldbackPct`, `foldbackEvents`, `tripLatched`, `spinTrips`, `offlineVolume`, `calState`,
  `calOutcome`, `audioReady`, `audioPlayed`, `audioUnderruns`, `audioDropped`,
  `audioSuperseded` (waiting sound requests outranked by a louder one, or by a newer one of equal gain).

Compatibility: Desk Dial 7.2.x on this firmware sends none of these and gets the cc5.6 feel, no sound, the same walls
(the r4 wall law runs only with a feel token) and the same protocol; Desk Dial 7.3 on cc5.6 / cc5.5 sends none of them
(device.py gates each on its capability) and keeps today's profiles.

### App canvas (A2, 1.0.0-cc5.6)

Karl Malota's app UI for Onshape on the knob (adapted from `katbinaris/NanoD_RatchetH1` @
`feat/firmware-esp-idf-quadra`, with permission; every ported file credits him in its header). The
capabilities reply adds `"appCanvas":1` (after `glyphs`; nothing else changes). A host that never sends
the frame's `app` object sees 1.0.0-cc5.5 D exactly.

**The `app` object** (optional, top level of any frame, any layout; `cc_frame_parse.cpp` `parse_app`, the
host reading is `device.app_parse`, both held to one table by `harness/app_canvas_tests.py`):

```json
"app": {"id": "onshape", "crc": 0, "slot": "zoom" | "orbit" | "pan" | "tilt" | "knob" | "f1" … "f4",
        "refused": false, "flash": 12,
        "wheel": {"ring": 0, "index": 2},
        "param": {"ring": 0, "index": 2, "mode": "A" | "B", "value": 300, "step": 1, "bump": 0},
        "echo":  {"ring": 0, "index": 2, "seq": 4}}
```

| Field | Rule (anything else rejects the whole frame) | Meaning |
|---|---|---|
| `id` | required, 1..11 characters of `[a-z0-9_-]` (app profiles; before: only `"onshape"`) | the profile: an uploaded one ([App profiles](#app-profiles-upload-and-store)), or the built-in Onshape (`cc_app_onshape.c`) for `"onshape"` with `crc` 0 |
| `crc` | optional int 0..0xFFFFFFFF, default 0 (app profiles) | the CRC-32 of the uploaded profile the host means; 0 = the built-in Onshape |
| `slot` | required, `zoom` / `orbit` / `pan` / `tilt` (tilt: the 1.0.0-cc5.6 rebuild for Desk Dial 7.2.2.0; an older host never sends it), or `knob` / `f1` / `f2` / `f3` / `f4` (app profiles: the profile's own slots, values 4..8 after the legacy 0..3) | the cube scene the knob's turn drives; a profile slot takes its label and micro-interaction from the profile |
| `refused` | optional bool | the action line reads POINT AT MODEL (amber) |
| `flash` | optional int 0..0x7FFFFFFF | a change = the 260 ms amber Undo flash (F3 UNDO) |
| `wheel` | optional; `ring` 0..7, `index` 0..32 (app profiles; before 0..15) | present = the command wheel is shown; index 0 = cancel |
| `param` | optional; `ring` 0..7, `index` 1..32, `mode` `A`/`B`, `value` int ±99,999,999 (thousandths), `step` 0..2, `bump` optional int 0..0x7FFFFFFF, `axis` optional int 0..3, `plane` optional bool (app profiles) | parameter mode: A shows `value` as the change (+0.30), B as the value; `step` lights 0.01 / KNOB 0.1 / 1.0; a `bump` change nudges the card 3 px for 90 ms; `axis` the live constraint X / Y / Z / uniform (absent = the profile's `axis_default`), `plane` true = the plane of that axis (the axis key with Shift) |
| `echo` | optional; `ring` 0..7, `index` 1..32, `seq` 1..0x7FFFFFFF | a `seq` change replays that command's card for 1.1 s |

Unknown keys inside `app` are ignored. Ring / index values outside the profile draw as "cancel" (the
wheel) or fall back to the main screen (param, echo).

**The one non-strict rule (app profiles, APP_PROFILES.md section 8):** a well-formed `id` that is not loaded, or a
`crc` that differs from the loaded copy, is **accepted**; the LCD thread then draws the neutral "Loading…" app screen
(`cc_app_store_acquire()` returns NULL) instead of rejecting the frame. A malformed `id` or `crc` still rejects it.
`CCAppState::id` is the id text (`char[12]`, `""` without an `app` object; `cc_app_present()`), plus `crc`.
`sizeof(CCFrame)` is 1,316 B (+16 from 1,300 B; xtensa g++, ILP32).

**Drawing.** While a frame with `app` is current the LCD thread does not call `lv_timer_handler()` (LVGL is
paused: no refresh, no flush, no LVGL heap use) and `CCAppCanvas` (`cc_app_canvas.*`) draws the UI into a
PSRAM 240 × 240 RGB565 frame (115,200 B) with plain rect fills (`cc_app_gfx.*`: a thin shim in place of
LovyanGFX; the Silkscreen 8 / 10 px pixel fonts, the Onshape icons). Each frame is pushed in ten 24-row
chunks through LVGL's own two internal draw buffers, idle meanwhile, as DMA bounce buffers (`draw_buf`,
`draw_buf2`; `pushImageDMA` on the one TFT_eSPI instance, its transaction and MOSI routing unchanged), then
`dmaWait`. When the frame loses its `app` (or the session ends) the active LVGL screen is invalidated and
the host frame re-rendered, so LVGL redraws in full. The PSRAM frame and the plasma tables (~8.6 KB) are
allocated once at LCD start; without them an app frame shows the LVGL text screen (A0's). The canvas
pushes count in `lcdFps` and `lcdFlushUs`; no new diag field.

**Local, not host-driven:** the cube follows the knob's own sensor angle (`cc_app_angle_read()`, 1e-4 rad,
one aligned word the FOC task writes each pass from the angle it already reads) with Karl's stepped poses
(32 per turn, zoom in 1/8 doublings, pan in 2 px) and the 220 ms ease to the nearest 45° + k·90° pose when
orbit ends; in `tilt` the view's pitch follows the knob instead (the same 32-per-turn steps about the 30° rest,
a vertical ring beside the cube carries the marker) and eases back to the 30° rest over 220 ms when tilt ends;
a jump above 2 rad between passes (a re-anchor) is ignored. The keycaps light from the HMI's
live key mask (physical order through `buttonOrder`); parameter mode's "RELEASE: OK / CANCEL" bar runs from
the local button-3 press (600 ms). The idle plasma starts after 5 s without knob motion, a key change or a
new app state, and any of them ends it.

**Pacing:** a moving cube, a wheel slide, the flash / echo / nudge edges and every new state draw at most
once per `CC_LCD_PERIOD_MS` (D 16 ms, F 12 ms), and a moving cube only when its stepped pose changes;
looping animations (card keyframes, the plasma, the hold bar) redraw every 33 ms (Karl's ~30 fps); a still
screen draws nothing. Frame time ≈ draw (~1.1–1.9 ms, model) + 11.8 ms push at 80 MHz: ~60 fps on D,
~73–77 fps on F for moving screens (`app-canvas-report.json`; diag `lcdFps` measures it on the knob).
Asleep (`cc_sleep`): nothing is drawn.

**LEDs:** unchanged. The frame around the `app` object is A0's text frame (ring `off`), which the HMI's
ALIVE engine renders as today.

### App profiles (upload and store)

The contract is [APP_PROFILES.md](APP_PROFILES.md) (wire 1): the DDAP wire profile, the `appProfile` messages and
the frame additions above. The profile model is adapted from Karl Malota's (katbinaris) app profiles,
`feat/firmware-esp-idf-quadra`, with permission. The knob side:

- **Decoder** (`cc_app_store.c`, pure C99): `cc_app_decode()` checks every rule of APP_PROFILES.md sections 2-4 in
  a first pass that also sizes the result, then fills one allocation (the profile, its rings, commands, scenes,
  keyframes, elements, params, NUL-terminated strings and icons). Strict: the CRC-32, the exact `total`, unknown or
  inconsistent feature bits (the header's bits must be exactly what the content uses), every string, enum, range,
  count and index; the reason code and offset of section 6, nothing partly loaded. A search or macro command must
  carry an empty key.
- **Store:** RAM only (PSRAM through `cc_app_store_device.cpp`; nothing is written to flash, a reboot empties it):
  4 entries, 128 KB of decoded profiles, LRU by last draw (an upload counts as a draw). The LCD thread draws through
  `cc_app_store_acquire(id, crc)` / `cc_app_store_release()`: an acquired profile is never freed; eviction or
  replacement retires it and its last release frees it. `("onshape", 0)` is the built-in Onshape unless an upload
  with crc 0 exists. A static FreeRTOS mutex guards the records (COM writes, LCD reads).
- **Upload** (`cc_app_store_msg.cpp`; the COM task routes `{"appProfile":...}` before every other command; RAM only,
  so it is allowed during a claim and never renews the lease): one at a time (a `begin` drops the earlier upload),
  offsets strictly in order, a PSRAM staging buffer of `bytes` (<= 32768) from `begin` to `end`, base64 decoded
  straight into it, dropped after 2000 ms without `begin` / `data` (checked every COM pass and by each message).
  Replies: a successful `begin` has none (the first `data` line's `ack` follows); `data` -> `{"ack":next}`; `end` ->
  `{"id","crc","ok":true}`; `list` -> `{"loaded":[{"id","crc"}...]}`, most recently drawn first, uploads only.
  Errors: `crc` (begin's crc is not the CRC-32 of the received bytes before the trailer, or not a u32), `size`
  (bytes 0 or > 32768, b64 empty, > 3000 characters or not padded standard base64, a chunk past `bytes`, `end` before
  every byte), `order` (data / end without an upload, an offset other than the next byte, an id that is not 1..11 of
  `[a-z0-9_-]`, a malformed field, an unknown op), `busy` (no staging memory; the store cannot make room because
  acquired profiles hold the budget), `wire` (wire not 1), `decode:<code>@<offset>` (the decoder; `11@16` when the
  blob names another id than `begin`; `13@0` when PSRAM is exhausted). Any error ends the upload.
- **Internal heap:** a data line is at most ~3,050 B (the 4096 B line limit holds). ArduinoJson 7.0.2 copies the b64
  string while parsing; growing it to 4095 characters makes a 4,104 B block, which the S3 malloc policy
  (`CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL` 4096) places in PSRAM. Measured on an ILP32 build
  (`harness/app_store_tests.py`): 4,179 B peak in internal-sized blocks, 4,164 B held after the parse
  (the 3,009 B string, the 1 KB variant pool, the keys), 8,204 B for every block together; the media data line
  (2,732 characters) costs the same within ~270 B. The staging buffer and the decoded profiles are PSRAM only.
- **Tests:** `harness/app_store_tests.py` (MSVC /W4 /WX; the fuzz and a COM-vs-LCD thread stress also
  under /fsanitize=address).

### Lease

The lease is **2000 ms**. It runs from the last accepted `control` or `frame`,
and is checked by the FOC thread independently of the COM thread. When it
expires the knob releases itself (see handback below).

These never renew the lease: `art`, `media` (1.0.0-cc5.3), `diag`, `capabilities` and
read-only inventory commands. The host keeps sending heartbeat frames during transfers.

### Release

`{"release":true}`:

- **Session active:** the pre-session runtime detent profile, position and gains are restored, with native input and the native screen. When that is complete the knob replies `{"released":true}`.
- **No session:** the reply is immediate.

A lease expiry performs the same restoration and replies
`{"released":true,"reason":"lease-expired"}`.

**Acknowledgement timeout (1.0.0-cc5.2).** A release completes when the motor (native
profile restored), the LEDs (HMI) and the LCD have acknowledged it. The motor's
acknowledgement is always required. Once it is in, a presentation acknowledgement still
missing 1000 ms after the release started is no longer waited for: the knob replies

```json
{"released":true,"reason":"forced","unacked":["hmi"]}
```

`unacked` names the subsystems that did not acknowledge (`hmi`, `lcd`, or both);
`"leaseExpired":true` is added when the release came from a lease expiry. The release counts
in `diag` `forcedReleases` and `lastForced`. A forced release means a task is stalled: the
host should treat it as a fault (the check scripts fail on it), even though the session is
idle again and native haptics are back. A new `control` still needs fresh acknowledgements
from all three before `ready`, so a dead HMI or LCD cannot arm a session; the task watchdog
resets such a knob within 10 s. In 1.0.0-cc5.1 a hung HMI kept the session "releasing"
forever: no reply, and every new control was refused with "Control ID must advance". A
release received while one is already in progress still gets no reply of its own; the
first release's reply (at the latest 1 s after the motor) answers both.

### Input events

Turns are sent as `{"id":id,"p":position}`: absolute positions within the entry's bounds.

Buttons are sent as `{"id":id,"ks":mask,"kd":n}` or `{"id":id,"ks":mask,"ku":n}`.
They use raw indices; frame legends and LED pairs follow `buttonOrder`.

**Key state on position lines (1.0.0-cc5.5, F1).** A position line of the ready control is
`{"id":id,"p":position,"ks":mask}`. Its `ks` is the mask the knob last reported (on a `kd`, `ku`, `kh` or
`ready` line) AND the buttons down now, so it can only **clear** bits, never set them: a press is always
reported by its own `kd`, and a key-up that was lost (the key event queue, 16 events since 1.0.0-cc5.5, was
full) is cleared by the next turn. While a key event is still queued the line repeats the last reported mask,
so it never runs ahead of a `ku` on its way (the HMI queues a `ku` before it publishes the cleared bit; COM
reads the live mask, then the queue). An older host that copies any `ks` into its pressed mask (Desk Dial v7)
therefore never loses a `kd` or a `ku` to a position line; a newer one clears the bits and reports each as a
release. Native (unclaimed) position lines are unchanged.

- **Tagging.** While claimed, only events tagged with the current ID are sent, and only after its `ready` reply went out. Nothing is emitted while entering or releasing, and events are never replayed after a release or reconnect.
- **F24.** When `windowsHidEnabled` is true, the Windows button emits one 60 ms USB HID F24 pulse in addition to its tagged event, if the frame's legend for it is enabled. The host de-duplicates the two paths. Simulated sessions set `windowsHidEnabled:false`.
- **Native behaviour while claimed.** Native MIDI, configured key and knob actions, and on-device profile switching are suppressed. Queued native haptic configuration is ignored.
- **Configuration changes while claimed.** `updates`, `current`, `save`, `load`, `R`, `recalibrate`, `profiles` (list) and `settings` (object) are refused with `{"error":"Release control center before changing device configuration"}`. Read-only inventory stays available: `{"profiles":"#all"}`, `{"profile":name}` and `{"settings":"?"}`.

### Diagnostics

`{"diag":"?"}` is read-only and never touches the session or the lease. It returns:

```json
{"diag":{"lvglFree":N,"lvglMinFree":N,"heapMinFree":N,"stackLcd":N,"stackCom":N,"stackHmi":N,
 "stackFoc":N,"stackUsbd":N,"heapFree":N,"psramFree":N,"txStalls":N,"txDroppedBytes":N,
 "resetReason":"poweron","resetCode":1,"rtcReset":[1,14],"rtcResetNames":["POWERON_RESET","…"],
 "bootCount":N,"rtcRetained":true,"uptimeMs":N,
 "previous":{"uptimeMs":N,"comLines":N,"com":{"op":"art-data","stage":"line","arg":N,"atMs":N},
             "lcd":{"step":"refresh","atMs":N},"hmi":{"step":"show","atMs":N}},
 "coredump":{"blank":true,"present":false,"status":"ESP_ERR_INVALID_SIZE","bytes":0},
 "rxQueue":"internal",
 "hmiAgeMs":4,"lcdAgeMs":1,"comAgeMs":0,"focAgeMs":0,"hmiStep":"wait","lcdStep":"wait",
 "comOp":"diag","comStage":"line","taskWdtS":10,"wdtTasks":["hmi","lcd","com"],
 "sessionPhase":"idle","releasePendingMs":0,"forcedReleases":0,"lastForced":[],
 "led":{"ring":{"frames":N,"txTimeouts":0,"writeErrors":0,"recoveries":0,"skipped":0,"maxWaitUs":0,
                "lastErr":"none","installed":true},
        "buttons":{…}},
 "ledTxTimeouts":0,"ledWriteErrors":0,
 "rxQueueBytes":8192,"mediaCommits":N,"mediaErrors":N,"mediaEvictions":N,
 "jpegDecodes":N,"jpegDecodeErrors":0,"jpegDecodeMsMax":N,"jpegDecodeMsLast":N}}
```

The first six fields are the cc5 reply, unchanged. Everything after them is
additive: up to `rxQueue` in 1.0.0-cc5.1, up to `ledWriteErrors` in 1.0.0-cc5.2 (plus
`previous.lastAliveMs` and the per-task `aliveMs`), the last eight in 1.0.0-cc5.3
(ARTWORK2.md section 8; the `diag` capability stays 1). A host that knows only the older
fields ignores the others. Sizes are in bytes:

| Field | Meaning | Source |
|---|---|---|
| `lvglFree` | Current free LVGL heap (64 KB) | Sampled by the LCD thread once per second |
| `lvglMinFree` | LVGL heap low-water mark: the lower of the lowest free size sampled and total minus LVGL's peak-use counter (cc5 reported only the latter, which ignores block overhead and could exceed `lvglFree`) | Sampled by the LCD thread once per second |
| `heapMinFree` | Minimum free internal RAM since boot | Measured at the reply |
| `stackLcd`, `stackHmi` | Task stack high-water marks (free bytes) | Sampled by the LCD and HMI threads once per second |
| `stackCom` | COM task stack high-water mark | Measured at the reply |
| `stackFoc`, `stackUsbd` | FOC task and TinyUSB `usbd` task high-water marks; -1 if the task is not found | Measured at the reply |
| `heapFree`, `psramFree` | Free internal RAM and free PSRAM now | Measured at the reply |
| `txStalls`, `txDroppedBytes` | Replies cut short because the host stopped reading for 250 ms, and the bytes they lost (a reply dropped whole because the previous cut line could not be ended yet counts too) | Counted by `cc_serial_out` |
| `resetReason`, `resetCode` | `esp_reset_reason()` of this boot: `poweron`, `software`, `panic`, `int_wdt`, `task_wdt`, `wdt`, `brownout`, `external`, `deepsleep`, `sdio` or `unknown` | Read first thing in `setup()` |
| `rtcReset`, `rtcResetNames` | The ROM's reset reason for CPU 0 and CPU 1 (`esp32s3/rom/rtc.h`). It separates a brownout (`RTCWDT_BROWN_OUT_RESET`, 15) from an interrupt-watchdog system reset (`TG1WDT_SYS_RESET`, 8) or a power-on (`POWERON_RESET`, 1) | Read first thing in `setup()` |
| `bootCount` | Boots since the RTC memory last lost power (1 after a power-on) | RTC memory counter with a magic |
| `rtcRetained` | The RTC memory kept its content through the last reset, so `previous` is valid. False after a power-on or a reset that cleared RTC memory, and on the first boot after a build with another RTC layout (1.0.0-cc5.3 widened the COM operation field for the media breadcrumbs and changed the magic, so the first cc5.3 boot after cc5.2 reports false and `bootCount` 1) | Magic check at boot |
| `uptimeMs` | `millis()` at the reply | Measured at the reply |
| `previous` | Only when `rtcRetained`: the last HMI heartbeat before the reset (`uptimeMs`), the newest heartbeat of any task (`lastAliveMs`, 1.0.0-cc5.2), the lines the COM thread had handled (`comLines`), and each task's last breadcrumb with its time (`atMs`) and its last completed pass (`aliveMs`, 1.0.0-cc5.2): COM `op` (`capabilities`, `diag`, `art-begin`, `art-data`, `art-commit`, `art-other`, `release`, `control`, `frame`, `native`, `parse-error`, `oversize`, and from 1.0.0-cc5.3 `media-begin`, `media-data`, `media-commit`, `media-have`, `media-other`) and `stage` (`wait`, `read`, `line`, `service`, `events`) with `arg` (line length, frame or control ID, or art or media offset); LCD `step` (`wait`, `host`, `render`, `refresh`, `timers`, `diag`, and from 1.0.0-cc5.3 `decode`: an artwork2 cover JPEG decode inside a render); HMI `step` (`wait`, `config`, `buttons`, `hid`, `leds`, `show`, and from 1.0.0-cc5.2 `show-ring`, `show-buttons`, `led-recover`) | RTC memory, one 32-bit store per step by each task; each crumb's time is resolved against its own task's heartbeat |
| `coredump` | `blank` (the partition's first word is still erased), `present` (a complete core dump image), `status` (`esp_core_dump_image_get`) and its size. Read-only: the firmware never erases it | Checked once in `setup()` |
| `rxQueue` | Where the CDC receive queue (8 KB since 1.0.0-cc5.3, 4 KB before) was allocated: `internal` (expected), `psram`, or `default` (the 256-byte queue was kept) | Measured in `setup()` |
| `hmiAgeMs`, `lcdAgeMs`, `comAgeMs`, `focAgeMs` | Milliseconds since each task's latest breadcrumb (HMI, LCD, COM) or loop pass (FOC, through `cc_take_request`). A healthy knob shows a few ms; COM is about 0 by construction (it answers). 1.0.0-cc5.2 | RAM, one aligned 32-bit store per step, measured at the reply |
| `hmiStep`, `lcdStep`, `comOp`, `comStage` | Each task's current breadcrumb (names as in `previous`): where a stalled task stopped | This boot's RTC breadcrumbs |
| `taskWdtS`, `wdtTasks` | The task watchdog timeout (0 if its configuration failed) and the tasks subscribed now (`hmi`, `lcd`, `com`; COM leaves it during `save`/`load`) | `cc_diag` |
| `sessionPhase` | `idle`, `entering`, `ready` or `releasing` | Session state |
| `releasePendingMs` | How long the current release has waited for its acknowledgements (0 unless releasing) | Session state |
| `forcedReleases`, `lastForced` | Releases completed without an HMI or LCD acknowledgement since boot, and the subsystems the last one missed | Session state |
| `led` | Per strip (`ring`, `buttons`): `frames` sent, `txTimeouts` (the previous frame had not ended 5 ms after it was due), `writeErrors` (driver install, configuration or write failed), `recoveries` (channel stopped, driver reinstalled), `skipped` (frames dropped during a 1 s hold-off after three consecutive failures), `maxWaitUs` (longest wait for the previous frame), `lastErr` (`esp_err_t` name, `ESP_ERR_TIMEOUT` for a timeout, `none`) and `installed` | Counted by the HMI task in `cc_led_rmt` |
| `ledTxTimeouts`, `ledWriteErrors` | `txTimeouts` and `writeErrors` summed over both strips | `cc_led_rmt` |
| `rxQueueBytes` | The CDC receive queue size actually configured: 8192, or 256 when the core's default queue was kept. 1.0.0-cc5.3 | Measured in `setup()` |
| `mediaCommits` | Successful `media` commit replies since boot, both kinds (a begin-hit's commit included). 1.0.0-cc5.3 | `cc_media` |
| `mediaErrors` | `media` error replies since boot: every op, the `parse` reply included. 1.0.0-cc5.3 | `cc_media` |
| `mediaEvictions` | Valid slots evicted by a `begin` since boot (reusing an invalid slot is not an eviction). 1.0.0-cc5.3 | `cc_media` |
| `jpegDecodes`, `jpegDecodeErrors` | Cover decodes the LCD attempted and those that failed, since boot. 1.0.0-cc5.3 | `cc_jpeg`, counted in `cc_jpeg_decode_240` |
| `jpegDecodeMsMax`, `jpegDecodeMsLast` | The longest and the last cover decode, in ms rounded up (`esp_timer_get_time`), failed decodes included. 1.0.0-cc5.3 | `cc_jpeg` |

**1.0.0-cc5.5 (F1, safety and measurement).** Appended by `cc_diag_live()`, all additive (the capabilities
are unchanged):

| Field | Meaning | Source |
|---|---|---|
| `usbMidiOk`, `usbHidOk` | TinyUSB accepted the MIDI and HID interfaces at boot (booleans). A refusal is reported, never waited on | `HmiThread::init_usb()` in `setup()` |
| `hidRetries` | HID reports TinyUSB refused (endpoint busy) since boot; each is retried on the next HMI pass. At most one report goes out per pass, and a report is marked sent only when TinyUSB accepts it | `HmiThread::handleHid()` |
| `pdRead` | The STUSB4500 RDO_STATUS read (I2C 0x28, register 0x91, four bytes LSB first, up to three tries) worked | `HmiThread::init_pd()` in `setup()`, before the threads |
| `pdPdo` | RDO bits 30:28: the position of the source PDO the knob requested (1..7); 0 = no explicit contract (plain Type-C / USB 5 V) or the read failed | same |
| `pdVolts` | The voltage of the knob's own sink PDO at that position (DPM_SNK_PDO1..3, bits 19:10 x 50 mV, whole volts): 5 or 9 as `init_pd()` programs PDO1 / PDO2; 0 = unknown (no contract, a position past three, a failed read). PD sources list their fixed supplies in ascending voltage from 5 V, so position 2 is the 9 V offer of a charger that has one | same |
| `pdRdo` | The raw 32-bit RDO; only when `pdRead` | same |
| `focLoopHz` | FOC loop passes in the last completed second; 0 when no second completed for 2 s | `cc_diag_foc_pass()`, once per FOC pass |
| `focLoopUsMax` | The longest pass-to-pass interval since the previous read (µs; reset on read). A recalibration or a blocked pass shows here | same |
| `uqAbsMax` | The largest \|`motor.voltage.q`\| since the previous read, in **millivolts** (reset on read). The haptic PID peaks at 0.4 x 5.3 = 2.12 V | same |
| `uqCapMs` | Milliseconds since boot with \|Uq\| at the motor voltage cap (within 0.1 %) | same |
| `uqCapMv` | That cap, `motor.voltage_limit`, in millivolts: 2200 | same |

The motor output cap: `foc_thread.cpp` sets `motor.voltage_limit = 2.2` before `motor.init()` (phase
resistance 5.3 kept; it acts as the gain of torque voltage mode). `motor.init()` also clamps the alignment
voltage to it. No `{"R":…}` register write can raise it: after every write `voltage_limit` and
`voltage_sensor_align` are brought back into [0, 2.2]; writes of `REG_PHASE_VOLTAGE` (0x16),
`REG_DRIVER_VOLTAGE_LIMIT` (0x53) and `REG_DRIVER_VOLTAGE_PSU` (0x55) are refused and answered with the
unchanged value (`HapticCommander.h`). The motor driver (STSPIN233 VS) runs from VBUS through a load switch
with no regulator: on a 9 V PD contract (`pdVolts` 9) the same 2.2 V command is about 1.8 times the drive of a
5 V contract, because `voltage_power_supply` stays 5 until F2 scales it from the contract.

**Reboot detection.** A host compares two replies: a different `bootCount`, or a
smaller `uptimeMs` with the same `bootCount`, means the knob reset in between.
`tools/check_nanod_cc5.py` reads `diag` at the start and after every section and
fails on either; after a USB drop it waits for the knob and reads `diag` once
more, so its evidence names the reset reason and the breadcrumbs. A reset that
bypasses the panic handler (brownout, or an interrupt-watchdog system reset
after a lock-up) leaves no core dump; `rtcReset` and `previous` still identify it.

**Liveness (1.0.0-cc5.2).** A reboot check alone cannot see a task that stopped while
the others run on: 1.0.0-cc5.1's hung HMI passed every one. A host reads the ages
instead: `tools/check_nanod_cc5.py` fails any checkpoint where a task age exceeds 1000 ms,
or where `ledTxTimeouts`, `ledWriteErrors` or `forcedReleases` is not 0, and its
unattended soak reads `diag` every 10 s. A task stalled for 10 s is reset by the task
watchdog (`resetReason` `task_wdt`, a core dump, and that task's breadcrumbs in
`previous`).

### Artwork upload

The host sends one 120×120 RGB565 little-endian cover (28,800 bytes), already
composited (`scrim80`: 0.8 opacity plus the readability scrim), per `artKey`.
Every `{"art":{…}}` line is answered by exactly one
`{"artAck":{"id":…,"key":…,"op":…,"offset":N[,"error":"…"]}}`.

| `op` | Request fields | Success `offset` |
|---|---|---|
| `begin` | `bytes` (must be 28800), `crc32` (CRC-32 of the whole image) | 0, or 28800 when a cover with this key and CRC is already cached (the host skips straight to `commit`) |
| `data` | `offset` (the next expected byte), `data` (base64, ≤ 512 characters, ≤ 384 bytes decoded) | bytes received so far. A repeated chunk identical to bytes already written is accepted (lost-ACK retry). |
| `commit` | none | 28800. The cover becomes valid, and the LCD adopts it by key. |

- **Binding.** `id` must be the active entry's control ID, and `key` (`[A-Za-z0-9_-]{1,64}`) must equal the current frame's `artKey`. Otherwise the reply is `"Stale artwork selection"`. The frame that names a key therefore precedes its upload.
- **Errors.** Other `error` texts: `Artwork memory unavailable`, `Artwork size and CRC required`, `Artwork size must be 28800`, `Invalid artwork chunk`, `No matching artwork upload`, `Artwork chunk bounds`, `Artwork offset mismatch`, `Artwork upload incomplete`, `Artwork checksum mismatch`, `Unknown artwork operation`. Artwork failures are presentation-only: the host reports them as `artwork-error` events, never as a disconnect.
- **`parse` op.** An art line that is not valid JSON, or is oversize, is answered with `{"artAck":{"id":…,"key":…,"op":"parse","error":"parse"}}` (contract section 7). The `id` and `key` come from a bounded 192-byte scan of the raw line prefix, and are omitted unless found intact.
- **Store.** Covers are identified by content key. A commit invalidates any other slot with the same key. `begin` evicts the least recently used non-active slot (or a free one) unless the key and CRC are already cached. The LCD upscales a key ×2 once into a 240×240 PSRAM buffer and draws it at `image_opa` 255, or 112 with `artDim`. Swap and fade rules are in contract section 6.

The v1 `art` command, its store and its strings are unchanged in 1.0.0-cc5.3. While artwork2 is
negotiated the host sends no `art` lines.

### Media upload (artwork2, 1.0.0-cc5.3)

The normative specification is [ARTWORK2.md](ARTWORK2.md) sections 4 and 5. The store and the
request handler are `src/cc_media_store.h` (platform-neutral); `src/cc_media.cpp` wraps them.
Every `{"media":{…}}` line gets exactly one `{"mediaAck":{…}}`, in order, whatever its value.

| `op` | Request fields (besides `id`, `op`, `kind`) | Success reply |
|---|---|---|
| `have` | `keys`: 1..24 keys | `"have":[bool…]`, true where a valid slot holds the key. Hits are touched in request order; an upload in progress is not affected |
| `begin` | `key`, `bytes`, `crc32` (CRC-32/IEEE of the payload) | `offset` 0 (a miss: the victim slot is invalidated at once), or `offset` = `bytes` when a valid slot already holds the key with the same size and CRC (a hit: go straight to `commit`) |
| `data` | `key`, `offset` (the next expected byte), `data` (standard base64 with padding, 1..2048 bytes decoded) | `offset` = bytes received. A repeat of the last chunk (same offset, same bytes) is accepted unchanged |
| `commit` | `key` | `offset` = `bytes`. The slot becomes valid (other slots with the key are invalidated), and the LCD adopts it by key |

- `id` is the active control ID (a session entering or ready); `kind` is `cover` (240×240
  baseline JPEG, 1..32768 bytes) or `icon` (32×32 RGB565 little-endian on black, exactly 2048
  bytes); `key` is `[A-Za-z0-9_-]{1,24}`.
- **Replies.** Keys in the order `id`, `op`, `kind`, `key`, `offset` (or `have`), `error`.
  An error reply carries each of `id` (an integer 1..0x7FFFFFFF), `op`, `kind` and `key` that
  parsed validly; `have` replies never carry `key` or `offset`; `offset` is the upload's received
  bytes once a `data`/`commit` matched the upload, otherwise 0.
- **Checks, in order** (the first failure is the `error`; only the checksum and decode failures
  change state, by ending the upload): `Unknown media operation`, `Unknown media kind`,
  `Media unavailable` (store not allocated), `Stale media control`; then `have`:
  `Invalid media keys`; `begin`: `Invalid media key`, `Media size and CRC required`,
  `Invalid media size`; `data`: `Invalid media key`, `No matching media upload` (also for a
  begin-hit context), `Invalid media data`, `Media chunk bounds`, `Media offset mismatch`;
  `commit`: `Invalid media key`, `No matching media upload`, `Media upload incomplete`,
  `Media checksum mismatch`, `Media decode failed` (covers only: `cc_jpeg_validate`).
- **Integers** follow ARTWORK2.md 4.3 literally. A JSON integer is a number ArduinoJson stores
  as an integer: no fraction or exponent, within −2^63..2^64−1 (a longer one parses as a float
  and is not an integer); never a bool or a string.
  - `begin` `bytes` and `crc32`: missing, not an integer, or outside 0..0xFFFFFFFF (negative and
    huge values included) is `Media size and CRC required` (ARTWORK2.md 4.3; lead ruling of
    2026-09-24, ARTWORK2.md section 12, ruling 2); a `bytes` inside that range but outside
    1..32768 (covers) or other than 2048 (icons) is `Invalid media size`.
  - `data` `offset`: `offset` + decoded length > `bytes` is `Media chunk bounds`; otherwise any
    offset other than the received count that is not an identical retry, a negative one
    included, is `Media offset mismatch`.
- **Cover check at commit** (`Media decode failed`): the marker segments up to SOS as the ROM
  reads them (SOI first, one SOF0 with 8-bit samples and 3 components, no other SOF type), the
  ROM decoder's `prepare` (tables, sampling factors, work area), exactly 240×240, at most 32768
  bytes, and EOI (FF D9) as the **last two bytes** (a cover cut short or followed by trailing
  bytes is refused, as the companion's FakeKnob refuses it; ARTWORK2.md section 12, ruling 3).
  The entropy-coded scan is not decoded at commit: a scan damaged in the middle but still ending with EOI commits and then
  fails on the LCD (`jpegDecodeErrors`, no art for that key). The payload CRC-32 limits that
  case to a host encoder bug; `harness/jpeg_tests.py` pins it
  (`decode-fails-truncated-scan-with-eoi`).
- **`parse` op.** A media line that is not JSON, or is oversize, is answered with
  `{"mediaAck":{"op":"parse","error":"parse"[,"id":N][,"key":"…"]}}`; `id` and `key` come from a
  192-byte scan of the raw prefix and appear only when found intact (as for art).
- **Binding.** Unlike v1 art, a key need not be the current frame's: any key may be prefetched
  under the active control ID. The upload context ends at a new `begin` (either kind), at a
  commit, and when the control ID changes: a new `control`, a `release`, or a lease expiry
  (noticed by the COM thread's next service pass, before the next line). Committed slots survive
  releases, new controls and lease expiry until reboot. `media` never renews the lease.
- **Store.** Covers: 24 entries plus one staging slot of 32768 B; icons: 48 plus one of 2048 B;
  both in PSRAM (919,552 B). The frame keys (`artKey`, `iconKey` of the current frame) and the
  slot the LCD displays are pinned: `begin` takes the lowest-index invalid unpinned slot, else
  the least recently touched valid unpinned one. Decisions where ARTWORK2.md is silent (pinned by
  `harness/media_store_traces.json`, which the companion's FakeKnob replays too):
  - invalidating a slot changes only its `valid` flag: its key and stamp stay until it is
    committed again;
  - the displayed slot stays pinned even after a commit of its key elsewhere invalidated it,
    so the LCD can still be decoding from it;
  - a frame key that cannot name a media slot (a v1-length `artKey`, a malformed `iconKey`)
    pins nothing;
  - a `data` request whose `offset` is absent or not an integer fails with `Media chunk bounds`
    (after the data check);
  - a miss `begin` ends the upload in progress before it chooses the victim (ARTWORK2.md 4.4
    step 2), so when every slot is pinned (possible only in the small fixture configurations)
    the reply is `Media unavailable` and the other upload stays cancelled;
  - a request whose `media` value is not an object is an unknown operation;
  - a begin-hit's `commit` counts in `mediaCommits` but does not bump the media version;
  - a request that names the live upload but fails before an upload context is matched (a
    stale control ID, a rejected `begin` for the same key) carries `offset` 0, not the received
    count (ARTWORK2.md 4.2).

  The fixture's `check` steps compare each part they carry: the slot tables, `displayed`,
  `clock` and `receiving` (an upload context that is not a begin hit, `CCMediaStore::receiving()`,
  which drives the COM thread's 1-tick idle), so a release, a new control and an accepted frame
  in the middle of an upload are observable on their own. A kind's configuration may say
  `"available": false`: a store that was never allocated (no slots, an empty table) answers
  `Media unavailable` before the control check (ARTWORK2.md 4.3 step 4).
- **LCD.** `cc_media_adopt(kind, key)` returns the displayed slot's bytes (the pointer stays
  valid while that slot is displayed: displayed slots are never evicted or written), and
  `cc_media_release_display(kind)` ends the display; a miss also leaves no media displayed. The
  LCD decodes a cover with `cc_jpeg_decode_240` (its own static work area) straight from PSRAM,
  without holding the store's mutex; `cc_media_version()` changes at every miss commit and is
  part of `cc_presentation_state()`.
- **Covers still held by a display buffer.** The renderer draws a cover whose pixels one of its
  two art buffers still holds (the front buffer, or the back buffer after a swap) without a
  store lookup, even when neither store holds the key any more: for example on the return after
  a handback once the store has evicted the key. Keys are content hashes, so those pixels are
  exactly the cover; the store's displayed slot is then −1 (no pin). ARTWORK2.md section 7
  reads "else: no art" for a key neither store holds; the lead ratified this reuse in
  ARTWORK2.md section 12, ruling 6 (`harness` README, `cc_display.h`; checked by
  `cc5_report.py` `a2_handback`). Icons never do this: the Windows tile shows an icon only on a store hit,
  otherwise the letter tile. The host and the FakeKnob must not assume that a store miss means
  no art on the LCD.
- **Memory.** Internal RAM: the slot tables (about 3 KB), a 2 KB decoded-chunk buffer, two 4 KB
  TJpgDec work areas (COM and LCD) and the 4 KB more for the receive queue. When either PSRAM
  store cannot be allocated, artwork2 is off (`available` false) and every media request gets
  `Media unavailable`; v1 art and text are unaffected.
- **Host side (desktop v4, `control_center/device.py`): ARTWORK2.md section 9 details ratified
  by the lead in ARTWORK2.md section 12, rulings 7–9** (the tests pin them:
  `tests/test_cc_media_bridge.py`):
  - events travel in the existing event queue as `{"kind":"media-ready","media":"cover"|"icon",
    "key","hit"}` and `{"kind":"media-error","media","key" ("" for a have),"op","error",
    "retrying","failed"}` (`kind` is already the queue's event-name field; ruling 7);
  - after a per-line timeout, or a bare `{"error":…}` parse/oversize reply mapped to a media line,
    that line stays outstanding: no other media line is written until a reply matches it or its
    grace ends (`MEDIA_LINE_GRACE` × the 1.5 s ack timeout = 3.0 s after it was written), so the
    retry comes at max(failure + 1.0 s, write + 3.0 s). Replies carry no sequence number and a
    `have` reply names no key, so this keeps every reply attributed to its own line. A bare error
    that arrives while the only line is already in its grace is consumed and logged (at most
    once a minute), never fatal (ruling 8);
  - the mirror follows the knob's LRU instead of a plain add/remove set: a key leaves it once
    `entries − 3` other keys may have been touched since its confirming line was written, so
    `present` ≤ `entries − 3`; a still-wanted key that leaves it is probed again (ruling 9).

### Page lookahead and Home warm-up (desktop v4)

The normative specification is [ARTWORK2.md](ARTWORK2.md) section 11 (user request of
2026-09-24). It is host-only: **no firmware or wire change**, and the knob sees nothing but the
`media` traffic of section 4 (with a cc5.2 knob, the v1 `art` traffic it already had).

- **Recent stays one page ahead.** Each time a Recent page is presented, the companion
  (`control_center/controller.py`) requests the next page in the background, invisibly; More
  onto a prefetched page is instant, and More while that request is in flight adopts it
  (section 11.1).
- **Covers follow.** The runtime (`control_center/runtime.py`) prefetches the current page's
  covers by distance, then the next page's in index order, and with artwork2 names the next
  page's covers in the knob's cover wanted list after the current page's (sections 11.2 and
  11.3). The current page (at most 10 covers) plus the next (at most 10) fit the bridge's cap
  of `entries − 4` = 20 and the knob's 24-cover store; covers that are not the current frame's
  are the knob-side prefetch of section 4, which the existing `check_nanod_cc5.py` gates
  `mediaPrefetch` and `mediaPinning` already cover.
- **Home warm-up.** On Home the runtime keeps a background copy of Recent page 1 (10 s after
  startup, then every 10 minutes, or the controller's page 1 when Recent is left). With
  artwork2 it names those covers after Now Playing on the knob, so entering Recent shows them
  at once. On a cc5.2 knob only the host cache is warmed, and the v1 upload stays paced. Entering Recent still
  loads page 1 fresh ("Loading library…"). The warm-up never runs without Apple Music
  credentials, while sign-in has expired, or with artwork off (section 11.4).
- Background list requests run on their own `lookahead` lane with their own HTTP session, so
  they never delay a foreground page load. Two choices where section 11 is silent are
  documented in the code: an adopted More load still navigates after a knob reconnect
  (`Controller._complete_lookahead`), and on a cc5.2 knob the prefetched page's queued covers
  are re-issued when it is presented (`Runtime._poll_prefetch`). Tests:
  `tests/test_cc_lookahead.py`, `tests/test_cc_warmup.py`.

## Host-lost notice and native handback

- **Intentional release.** Restores the native runtime profile, native input, native LEDs and the native screen the knob showed before the session. No notice is shown.
- **Lease expiry.** Performs the same restoration. Only after it has fully completed does the LCD show the host-lost notice: **"NANO_D++" / "Waiting for PC" / "Native controls active"**. It uses the design tokens and list geometry (contract section 9, deviation 8), with no host button legends.
  - Native controls are active underneath. The notice does not claim the device or block a reconnect.
  - It stays until a valid new `control` (the original native screen is kept for the next intentional release) or an explicit `release` (which restores the native screen).

## LED transport (1.0.0-cc5.2)

**The 1.0.0-cc5.1 hang.** FastLED 3.6.0's ESP32 driver (`clockless_rmt_esp32.cpp`) sends
both strips through one shared state machine. The last controller's `showPixels()` starts
the strips from the task (`startNext()`: start the channel, then `gNext++`) and blocks in
`xSemaphoreTake(gTX_sem, portMAX_DELAY)`. The RMT interrupt counts finished strips
(`gNumDone++`), gives the semaphore only when `gNumDone == 2`, and otherwise starts the
next controller itself while `gNext < 2`. None of this is locked; it assumes the task
finishes starting both strips before either one ends. In cc5, HMI, LCD and COM all run at
priority 1 on core 0 with 1 ms time slicing, and LCD (LVGL refreshes, 115 KB flushes, the
art upscale) and COM (JSON frames, art chunks) are busy under load. When HMI is switched
out for 0.24-1.8 ms right after starting the buttons strip and before `gNext++`, the
buttons finish (0.24 ms), the interrupt restarts them, their second end gives the
semaphore while the ring is still sending, `show()` returns and zeroes the counters, the
ring's late end restarts the ring, and its end leaves `gNumDone` at 2. From then on each
frame's two ends make 3 and 4: `== 2` never holds again and HMI waits forever. Both strips
end cleanly, so there is no interrupt storm, no interrupt watchdog and no task watchdog
(only IDLE0 was watched, and it kept running). The same race exists in cc4; cc4's other
core-0 tasks were rarely runnable, so it did not show in 23.5 h. The exact interleaving
cannot be proven after the fact (the counters were not captured), but it matches every
symptom and a discrete-event model of the driver reproduces it.

**The replacement.** FastLED keeps everything up to the wire: `FastLED.show()`, the
controller list, `setBrightness()` and the 51 cap, colour correction, the refresh guard
and `PixelController` with its dither gate. Only the clockless transport changes:

- `CCLedController<ORDER, LEDS>` (`cc_led_rmt.h`) is a `CPixelLEDController`. Its
  `showPixels()` makes the bytes exactly as FastLED's `ClocklessController::loadPixelData()`
  did (`loadAndScale0/1/2`, `advanceData`, `stepDithering`), and `getMaxRefreshRate()` is 400
  as before. `hmi_thread.cpp` registers the same two strips with
  `FastLED.addLeds(&controller, leds, count)`: the ring (60 LEDs, RGB, GPIO 38, RMT channel 0,
  memory blocks 0-1) and the buttons (8 LEDs, GRB, GPIO 42, channel 2, blocks 2-3), the
  channels and blocks FastLED used. The logical LED model, `cc_ring_address()` and the cap are
  untouched, so `light_tests.py` is unchanged.
- `cc_led_encode()` (`cc_led_wire.cpp`) writes one RMT item per bit, MSB first, with
  FastLED's WS2811 timing at 40 MHz: a one is 25 ticks high and 25 low (625/625 ns), a zero
  12 high and 38 low (300/950 ns), 1.25 us per bit. `harness/led_wire_tests.py`
  recomputes FastLED's own `mOne`/`mZero` from its formulas and checks the encoder against an
  independent Python encoder.
- `CCRmtStrip` (`cc_led_rmt.cpp`) owns one channel through the ESP-IDF 4.4 legacy RMT driver,
  installed from the HMI task (its interrupt is on core 0, level 3, in IRAM, like FastLED's).
  Per frame it polls `rmt_wait_tx_done(channel, 0)`; only if the previous frame has not ended
  does it keep polling, once per tick, for at most 5 ms (a frame lasts at most 1.8 ms and was
  started at least 2.5 ms earlier), then waits 60 us for the WS2811 latch. It encodes into its
  static item buffer and calls `rmt_write_items(..., wait_tx_done = false)`, whose own
  `portMAX_DELAY` take of the driver semaphore therefore never waits. A frame still in flight
  after the grace (`txTimeouts`) or a driver error (`writeErrors`) is recovered: the channel is
  stopped, its driver uninstalled (this never blocks, because no write ever set
  `wait_tx_done`) and installed again (`recoveries`). Three consecutive failures on a strip
  skip it for 1 s (`skipped`). The breadcrumbs `show-ring`, `show-buttons` and `led-recover`
  follow `show`.
- Each channel has its own driver semaphore, given once per frame by its own end
  interrupt; nothing is started from an interrupt and no counter is shared, so a task switch
  anywhere is harmless. `FastLED.show()` returns within a few milliseconds whatever happens,
  and HMI keeps polling the buttons and acknowledging controls.

**What stays exactly as before.** The bytes on the wire (same `PixelController`, same
scaling), the bit timing, pins, colour orders, channels and memory blocks, idle-low lines,
the 2.5 ms minimum spacing of `show()` and the order of the strips. FastLED's RMT driver is
no longer instantiated, so the linker drops it (`ESP32RMTController` is absent from the
ELF). Differences: between frames the lines stay connected to the RMT (idle low) instead of
being switched to a GPIO driven low, and `show()` returns as soon as both frames are started
instead of waiting until they end (at most 1.8 ms later; HMI's LED acknowledgement follows
`show()` as before). Cost: 6,528 B of internal RAM for the item buffers (1,440 + 192 items),
which the IRAM interrupt requires.

**Dithering.** Contract 5.1 says dithering stays at FastLED's default. FastLED's default is
the stored mode `BINARY_DITHER` (HMI re-asserts it on every claim transition), but
`FastLED.show()` switches dithering off for every frame while its measured rate is below
100 fps, and HMI shows at most every 16 ms. So the bytes sent are plain
`scale8(c, brightness)` (`FASTLED_SCALE8_FIXED`) with no temporal dithering, in cc4, cc5 and
cc5.1 alike. cc5.2 keeps `FastLED.show()` and `PixelController`, so this is unchanged. Real
temporal dithering would need 100 fps or more from `show()`: a visible change and more HMI
load, for the contract owner to decide.

**Ownership.** The RMT peripheral belongs to these two strips. No FastLED clockless
controller (`FastLED.addLeds<CHIPSET, PIN, ...>`) may be added anywhere: it would bring back
FastLED's driver and its interrupt on the same interrupt source. `harness/cpp11_gate.py`
fails on `addLeds<`, on other RMT users (`neopixelWrite`, `rmtInit`, `Adafruit_NeoPixel`) and on
FastLED ESP32 driver options in `src/` (comments are ignored). No FastLED build option fixes
the race: `FASTLED_RMT_BUILTIN_DRIVER` keeps the same counters and `portMAX_DELAY`,
`FASTLED_RMT_MAX_CHANNELS=1` moves flash-resident calls into the IRAM interrupt,
`FASTLED_ESP32_FLASH_LOCK` does not link, and the I2S driver targets the classic ESP32.

**Interrupt-masked sections.** Measured, and not a cause: the 1040-byte `CCFrame` copies
under the session spinlock take about 1-4 us, against the 60 us refill budget of each half
of an RMT channel's memory. They are unchanged except that HMI now copies the host frame
only when the presentation changed (as the LCD did), which removes most of them and most of
the FOC thread's spinning on the other core. HMI, LCD and COM keep their priority (1, core
0): with the bounded transport a task switch inside `show()` is harmless, and LCD and COM
pacing stays as tested.

## Task watchdog and liveness (1.0.0-cc5.2)

- `setup()` sets the ESP-IDF task watchdog to **10 s with panic** (`esp_task_wdt_init`,
  which in IDF 4.4 reconfigures the running watchdog; IDLE0 stays subscribed, now with 10 s
  instead of 5 s).
- HMI, LCD and COM subscribe when they start and feed it once per loop pass, at their `wait`
  breadcrumb (COM also after every command line it handles; each reply gives up after 250 ms
  without progress). Their normal passes take milliseconds (HMI about 10-20 ms, LCD up to
  tens of ms with a full refresh). The watchdog is never fed from anything that keeps
  running while the task's own work is stuck.
- **Flash writes.** COM leaves the watchdog around the `save` and `load` commands (SPIFFS and
  NVS; a SPIFFS garbage collection may take seconds) and rejoins after them. They are refused
  while a session is claimed. HMI and LCD write no flash; a flash write elsewhere only pauses
  them for single erase or program operations (with `CONFIG_SPI_FLASH_YIELD_DURING_ERASE`),
  far below 10 s.
- FOC is not subscribed: it is a busy loop next to the haptic code. Its liveness is
  `focAgeMs` (stamped in `cc_take_request()`, which it calls every loop).
- HMI's two debug lines (`Hmi settings updated ...`, `Received a sysex message`) are written
  only when the USB transmit buffer has room for them, so HMI never spins on a host that
  stopped reading.
- A task that stops making progress for 10 s panics: `resetReason` `task_wdt`, a core dump in
  flash (`coredump.present`), and that task's last breadcrumbs in `previous`. The USB device
  re-enumerates and the session ends; the host sees a reboot instead of a silent freeze.
  Before 10 s, `diag` already shows the stalled task's age and step. The core dump partition
  is 64 KB; an ELF dump holds the used part of every task stack (a few KB each here), which
  should fit. If one ever does not, the reset reason and the breadcrumbs still name the task.

## C++11 rules (contract section 10)

The firmware compiles as `gnu++11` (Arduino-ESP32, GCC 8.4):

- No C++14 features: relaxed `constexpr`, digit separators, `make_unique`, generic lambdas or `auto` return type deduction.
- Tables go at namespace-scope `constexpr`. Never use odr-used `static constexpr` class members.
- The shared translation units must pass `harness/cpp11_gate.py` and MSVC `/W4 /WX`:
  - `cc_lights.cpp`
  - `cc_display.cpp`
  - `cc_icons.cpp`
  - `cc_frame_parse.cpp`
  - `cc_led_wire.cpp` (1.0.0-cc5.2)
  - `cc_jpeg.cpp` (1.0.0-cc5.3), shared with the host through `harness/tjpgd_shim`
    (`UNIT_INCLUDES` in `cpp11_gate.py` puts the shim and LVGL's TJpgDec on its include path);
    its firmware compile line against the real ROM header is checked by `jpeg_tests.py` and
    `media_tests.py --firmware-syntax`
  - `cc_media_store.h` (1.0.0-cc5.3, header-only: `HEADER_UNITS` in `cpp11_gate.py` holds a
    small translation unit that odr-uses the store and the COM transport helpers; `media_tests.py`
    runs the same unit)

`cpp11_gate.py` needs no device and no PlatformIO. For each shared unit it:

1. Compiles it with the ESP32-S3 xtensa g++ (`-std=gnu++11 -fsyntax-only -Wall -Wextra -Wpedantic`). Any C++14/17 diagnostic fails.
2. Checks the object file for undefined `Class::member` data symbols.
3. Runs a self-test that proves the compiler rejects a C++14 construct.

It also compiles the generated `src/fonts/cc_font_*.c` in gnu99, where any diagnostic fails.
Since 1.0.0-cc5.2 it also checks the firmware source rules of [LED transport](#led-transport-100-cc52)
(no `FastLED.addLeds<...>`, no other RMT user) over every file in `src/`.

The MSVC builds are:

| Tool (in `harness`) | Unit |
|---|---|
| `parse_tests.py` | `cc_frame_parse.cpp`, checked against `app/tests/fixtures/frames_v4.json` |
| `light_tests.py` | `cc_lights.cpp` (LED model), with `cc_frame_parse.cpp` |
| `build.py` | `cc_display.cpp` and `cc_icons.cpp` in the LVGL host harness, on the firmware `lv_conf.h` |
| `led_wire_tests.py` | `cc_led_wire.cpp`, against FastLED 3.6.0's WS2811 item words and an independent encoder (1.0.0-cc5.2) |
| `media_tests.py` | `cc_media_store.h` (with `cc_jpeg.cpp`): the shared trace fixture `media_store_traces.json` (every `mediaAck` byte for byte, every slot table; the fixture's reference model judges covers with a marker pre-scan, so each cover payload it judged is checked against the compiled `cc_jpeg_validate` first), direct checks, the COM thread's line transport (`cc_bad_line_reply`, `CCLineAssembler`: exactly one reply per oversize line and the 2 s expiry, and the ARTWORK2.md section 3 idle sleep rule), the capability object against the companion's `presentation.ARTWORK2_CAPABILITY`, and the gnu++11 gate for the header; the `control_center.cpp` media wiring (a verbatim copy of the unit with the real `cc_media.cpp` and `cc_frame_parse.cpp` and host stubs; C4244 is off for that unit only, for its cc5.2 narrowing assignments): capabilities order and `rxBytes`, exactly one reply per media line (the `mediaAck` ahead of `release`, `control` and `frame`; `capabilities`, `diag` and `art` keep their cc5.2 place before `media` and answer alone, so a line combining one of them with `media` gets no `mediaAck`; the host never combines commands: ARTWORK2.md section 12, ruling 5), frame keys from accepted controls and frames only, the upload cancelled by a new control, a release and a lease expiry but not by a stale ID or a rejected control, media never renewing the lease, raw bytes routed as `com_thread.cpp` routes them (an oversize or non-JSON media line gets exactly one parse `mediaAck`, counted in `mediaErrors`); `--firmware-syntax` also checks this track's firmware units with their PlatformIO command lines (1.0.0-cc5.3) |
| `jpeg_tests.py` | `cc_jpeg.cpp` through `tjpgd_shim/` and LVGL's TJpgDec R0.03: the design covers encoded by the host encoder itself (`control_center.artwork.prepare_artwork2`) and variants accepted, progressive/oversize/other sizes/grayscale/CMYK, a missing EOI, trailing bytes and damaged data rejected, the glue's RGB565 bit-exact against the decoder's own RGB888, the decoder within 40 dB of Pillow, then the ARTWORK2.md section 10 figure under the rule in force (`SECTION10_RULE`, the contract's text; exit 2, never a PASS, when only that rule fails: see [Validation boundaries](#validation-boundaries)) (1.0.0-cc5.3) |

Add any new platform-neutral unit to `SHARED_UNITS` in `cpp11_gate.py` (a header-only one to
`HEADER_UNITS`, with a translation unit that odr-uses it).

## Validation boundaries

Host-side tests and harnesses cover the protocol, the parser, the LED model and
the rendered LCD:

- the Python suite
- parser parity
- `light_tests`
- the LVGL harness and `cc5_report.py`
- the C++11 gate
- `media_tests` and `jpeg_tests` (1.0.0-cc5.3)

A successful firmware build establishes compilation only. These still need the
actual device: physical feel, LED order and brightness, the rendered 240 px
panel, focus handoff, lease restoration and art transfer timing. For 1.0.0-cc5.3 also the
ROM decoder itself (the host runs LVGL's TJpgDec R0.03 behind the ROM API; the ROM holds R0.01b),
cover decode time (`jpegDecodeMsMax`), PSRAM and internal RAM margins with both stores
allocated, and unpaced transfers against the real 8 KB queue (ARTWORK2.md section 10).

**ARTWORK2.md section 10 JPEG rule (1.0.0-cc5.3).** The lead ruling of 2026-09-24 (ARTWORK2.md
section 12, ruling 4) amended section 10 to the `decoder-rgb888` rule: for every design cover
encoded by the host encoder, the
decoder's RGB888 is within PSNR ≥ 40 dB of Pillow's RGB888 decode, and the glue's RGB565 is
bit-exact to the section 7 rounding of that RGB888. It is met: worst decoder 43.14 dB with
Pillow 12.3, 0 glue mismatches (`jpeg_tests.py --section10-rule decoder-rgb888` exits 0). The
text before the ruling (RGB565 against Pillow after RGB565 rounding) measured 39.40 dB for
`cover-glass weather-album`: rounding both sides turns TJpgDec's ±1 RGB888 differences (a floored
IDCT and replicated chroma, shared by the ROM's R0.01b) into whole RGB565 steps, which is why
the ruling does not compare RGB565 with RGB565. `jpeg_tests.py` still reports that reading, the
RGB565-vs-unrounded-RGB888 reading (worst 40.08 dB) and 4:4:4 host encoding (worst 40.71 dB at
10–35 % more bytes) for reference. The script's default rule, the constant `SECTION10_RULE` in
`harness/jpeg_tests.py`, is `'decoder-rgb888'`, matching the amended section 10, so a
plain `jpeg_tests.py` run exits 0 when it is met. Exit 1 is an implementation failure; exit 2
(never a PASS) means every implementation check passed but the section 10 rule in force did
not, which is a contract decision for the lead.

The hardware window should also confirm what the host tests cannot:

- the media wiring the host test exercises with stubs: a `release`, or a lease expiry, in the
  middle of an upload makes the next `data` line fail (`Stale media control` while releasing,
  `No matching media upload` after a new control), and a transfer of media lines alone does
  not keep the lease alive;
- the COM thread's timing: an oversize `media` line (more than 4096 bytes) gets exactly one
  parse `mediaAck` and `mediaErrors` grows by one; during a stop-and-wait upload the next line
  after a `mediaAck` is answered within about 1–3 ms (not about 10 ms), and an idle knob
  goes back to 10-tick sleeps.

For the 1.0.0-cc5.2 LED transport, the device checks (`check_nanod_cc5.py`: liveness at
every checkpoint, both stress passes and the 20-minute unattended soak) show that it keeps
running under load. They do not measure the wire. Still to be checked on the bench: a logic
analyzer comparison against cc4 on GPIO 38 and 42 (300/950 ns and 625/625 ns bits, GRB order
on the buttons, idle low, a latch gap of at least 50 us), a fault-injection build that forces
timeouts to exercise the recovery, and a longer soak.
