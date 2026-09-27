# cc5 album artwork and targeted-colour LEDs (1.0.0-cc5.2): build, package, install

Status: **1.0.0-cc5.2 gated, built by `build_nanod_cc5.py` and packaged on 2026-09-23
(23:18-23:20 UTC); UNFLASHED.** Image `nanod-control-center-1.0.0-cc5.2.bin`, 1,010,656 B,
SHA-256 `45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572`;
`manifest-1.0.0-cc5.2.json` is `UNFLASHED` and `manifest.json` is still the installed cc4
record. The knob runs cc4 (`1.0.0-cc4`) again:
1.0.0-cc5.1 was rolled back on 2026-09-23 (21:30 UTC) and the full 4 MB verified identical
to the pre-cc5 backup. cc4 stays installed until the app-only install in Stage 10 completes
and `finalize_nanod_cc5.py` records it. The contract is
`firmware/PRESENTATION_V4.md` (presentation 4), unchanged from 1.0.0-cc5 apart
from additive `diag` fields. Read [RECOVERY.md](RECOVERY.md) section 5 (cc5 -> cc4 rollback)
before any hardware step. In this file, cc5 means the cc5 release being installed,
1.0.0-cc5.2, unless a step names 1.0.0-cc5 or 1.0.0-cc5.1.

Before asking for the hardware window: run the Stage 9 gates on the final tree, then
[Build](#build-never-uploads) and [Package](#package-no-device-manifestjson-untouched)
below, and fill in the package table from their records. Done for 1.0.0-cc5.2 on
2026-09-23: every gate passed (`../diagnostics/cc5-stage9-cc5.2-prebuild-gates.log`), the
build was accepted and the package table below is filled in from `../diagnostics/cc5-build.json`
and `manifest-1.0.0-cc5.2.json`.

Every command in this file uses absolute paths, so it works from any folder.

## Incident history

**1.0.0-cc5 (superseded, never finalized).** On 2026-09-23 it was flashed app-only and
verified; boot sanity and the inventory passed. The first `check_nanod_cc5.py` run passed
every check until its stress section, where the knob reset and re-enumerated on USB
(Windows logged it "surprise removed" at 16:16:36.583Z). **The knob was not turned in that
run**: the evidence records 0 knob events, and `--turn-seconds 10` only added three cold
art transfers before the stress. No core dump was written, although every watchdog and
stack check is set to panic and write one, so the reset bypassed the panic handler: a
supply dip (brownout) or an interrupt-watchdog system reset after a lock-up are the
candidates, and 1.0.0-cc5 could not tell which. A second run, knob untouched, passed the
stress and failed only the diag stack margin (HMI 628 B free of 4608). The knob was
rolled back to cc4 with the scripted rollback (full 4 MB verified identical to the pre-cc5
backup; `../diagnostics/cc5-rollback.superseded-20260923T213036Z.json`). Its image, source
archive and manifest stay in this folder; the manifest is marked `SUPERSEDED` (the previous
file is kept as `manifest-1.0.0-cc5.superseded-<UTC>.json`).

**1.0.0-cc5.1 (superseded, never finalized).** It kept the presentation contract and
changed: HMI and LCD stacks to at least twice their worst case (HMI 4608 -> 9216 B, LCD
8192 -> 12288 B; HMI no longer built a 2.9 KB `hmiConfig` every pass); the 4 KB CDC receive
queue in internal RAM instead of PSRAM; bounded, yielding control-center replies (a reply
cut short is ended with `\n` so the next one survives); reboot detection and reset
attribution in `diag` (`resetReason`, per-CPU ROM reasons, `bootCount`, `uptimeMs`, the
previous boot's COM/LCD/HMI breadcrumbs, core dump presence, `rxQueue`, `stackFoc`,
`stackUsbd`); and `check_nanod_cc5.py` reading `diag` after every section, watching for
re-enumeration, and running the stress twice (untouched, then while the knob is turned).
Its package was built twice (the first packaging, before three review fixes, is kept as
`manifest-1.0.0-cc5.1.superseded-20260923T195947Z.json` with its build log, build record and
gate log `*.superseded-2026092319*`); the installed image was SHA-256 `f75ac481...`.

Hardware window 2, 2026-09-23 (times UTC): installed 20:25 and verified
(`../diagnostics/cc5-flash-checks.json`). **cc5.1 fixed the reset**: four
`check_nanod_cc5.py` runs without a reboot (`bootCount` and `uptimeMs` continuous, coredump
partition blank, receive queue internal), stacks healthy (HMI 8,088 B free of 9,216, LCD
6,696, COM 9,256, FOC 6,300), the untouched stress passed three times (300 frame updates and
4 cold 120 px art transfers each, 0 errors) and stress+turn passed on traffic (145 turn
events, 0 errors); the first two runs failed only the turning gate. **A new defect appeared in the
third run** (20:35-20:38 UTC; the hang at about 20:37 UTC, 13:37 local; `../diagnostics/cc5-device-checks.superseded-20260923T212425Z.json`),
about 9 s into the untouched stress (heavy frames and cold art transfers; the knob was not
being turned): **the HMI task hung inside `FastLED.show()`**. The ring and button LEDs froze
and the buttons were dead. HMI never acknowledged the release, so the session stayed
"releasing": the run ended with "No release acknowledgement within 3.0 s", and every new
control was refused with "Control ID must advance; wait for release before reconnecting"
(the fourth run, 21:24 UTC, `../diagnostics/cc5-device-checks.json`, failed at its first
control). LCD and FOC kept running, so the native screen and the haptics worked, no
watchdog fired and nothing was written to the coredump partition. After a software reset
(one 1200-bps touch, then `read_mac --after hard_reset`; RTC memory retained) `diag`
`previous` showed HMI's last breadcrumb `show` at uptime 700,236 ms, while the COM and LCD
breadcrumbs ran on to about 3,784,782 ms: HMI had stopped inside `FastLED.show()` 51 minutes
earlier while the other tasks lived. The knob was rolled back to cc4 with the scripted
rollback at 21:30 UTC (`ROLLED_BACK_VERIFIED_RESET`, full 4 MB identical to the pre-cc5
backup; `../diagnostics/cc5-rollback.json`). Its image, source archive and manifest stay in
this folder as history.

**Cause.** A task/interrupt race in FastLED 3.6.0's own ESP32 RMT driver
(`clockless_rmt_esp32.cpp`): the task starts the strips and increments an unlocked counter
(`gNext`) afterwards, the interrupt restarts strips and counts finished ones (`gNumDone`),
and `show()` waits with `portMAX_DELAY` for `gNumDone == 2`. If HMI is switched out for
0.24-1.8 ms between starting the buttons strip and `gNext++`, the counters desync and every
later `show()` waits forever (details in `firmware/CONTROL_CENTER.md`, "LED
transport"). HMI, LCD and COM run at priority 1 on core 0 with 1 ms time slicing; cc5's LCD
(LVGL 9 animations, full-screen flushes, the art upscale) and COM (JSON frames, art chunks)
are busy under load, where cc4's were rarely runnable, which is why cc4 ran 23.5 h without
it. The race is latent in cc4 too. The exact interleaving cannot be proven after the fact
(FastLED's counters were not captured), but it explains every symptom, a discrete-event
model of the driver reproduces it, and nothing else in the evidence does.

## What 1.0.0-cc5.2 changes

The presentation contract, the logical LED model (`light_tests.py`: 2174149 checks,
unchanged), the physical ring mapping, the 51 brightness cap and every haptic path are
unchanged. cc5.2 adds (details: `firmware/CONTROL_CENTER.md`):

- **Hang-proof LED transport.** FastLED keeps `show()`, brightness, colour correction, the
  dither gate and the pixel pipeline; only its clockless RMT driver is replaced by
  project-owned code (`src/cc_led_rmt.*`, `src/cc_led_wire.*`) on the ESP-IDF 4.4 RMT
  driver: same pins, colour orders, RMT channels and memory blocks, the same WS2811 bit
  timing (625/625 and 300/950 ns), the same bytes. Each strip has its own channel and
  driver semaphore, nothing is started from an interrupt, every wait is bounded (at most
  5 ms for the previous frame), and a failed channel is stopped, reinstalled and counted;
  three failures in a row skip that strip for 1 s. `show()` returns within milliseconds
  whatever happens. FastLED's driver is no longer linked. Dithering is unchanged: FastLED
  switches it off below 100 fps and HMI shows at most every 16 ms, so the knob sends plain
  `scale8` values, as cc4, cc5 and cc5.1 did.
- **Task watchdog.** 10 s with panic on HMI, LCD and COM (IDLE0 stays watched). A task
  stalled for 10 s now resets the knob with `resetReason` `task_wdt`, a core dump and its
  breadcrumbs, instead of freezing silently. COM leaves the watchdog around SPIFFS/NVS
  `save` and `load`; HMI and LCD write no flash.
- **Release robustness.** Once the motor has restored the native profile, a release still
  waiting for the LEDs or the LCD after 1 s completes with `{"released":true,
  "reason":"forced","unacked":["hmi"]}` and is counted. The motor acknowledgement is always
  required.
- **Liveness in `diag`:** `hmiAgeMs`, `lcdAgeMs`, `comAgeMs`, `focAgeMs` with each task's
  step, the watchdog subscription, `sessionPhase`, `releasePendingMs`, `forcedReleases`, and
  the LED transport counters (`ledTxTimeouts`, `ledWriteErrors`, `led` per strip). LCD and
  COM keep an RTC heartbeat, so after a reset `previous` says when each task last completed
  a pass.
- **Checks.** Every `diag` checkpoint of `check_nanod_cc5.py` and `check_nanod_cc5_lease.py`
  now fails on any task age over 1000 ms, on any LED transmit timeout or driver error, and
  on any forced release. `check_nanod_cc5.py` adds an **unattended soak** after
  stress+turn (`--soak-minutes`, default 20): companion-like traffic (changed frames and
  heartbeats, cold and cached art, layout and LED-style switches, flashes) with a release
  and a new control every 30 s and a `diag` checkpoint every 10 s. It needs nobody at the
  knob and has no audible cue. New hard gates: `taskLiveness` and `unattendedSoak`.
- **Hygiene.** HMI copies the 1040-byte host frame only when the presentation changed (the
  LCD already did); its two debug lines never wait on a full USB buffer.

What this does not prove: the bench checks of the new transport (a logic-analyzer
comparison with cc4, a fault-injection build that forces recoveries, a soak longer than 20
minutes) are still to do (`CONTROL_CENTER.md`, "Validation boundaries").

## Build (never uploads)

```powershell
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' '<repo>\tools\build_nanod_cc5.py'
```

The script runs `platformio run -d firmware -e nanofoc_d` with
`PLATFORMIO_CORE_DIR=<pio-core>`. There is no upload
target and no git or device access. The complete log goes to
`work/nanod-cc5.2-build.log` in UTF-8 (the earlier releases keep `work/nanod-cc5-build.log`
and `work/nanod-cc5.1-build.log`).

The build is accepted only when all three conditions hold:

- The log contains `[SUCCESS]`.
- `.pio/build/nanofoc_d/firmware.bin` is an ESP image (magic `0xE9`) smaller than app0 (`0x140000`).
- The image contains `1.0.0-cc5.2`.

The record is `../diagnostics/cc5-build.json`, with size, SHA-256, headroom and the
delta from cc4. An older record is kept as `cc5-build.superseded-<UTC>.json`.

**Compile verification (not the release build).** The final 1.0.0-cc5.2 source tree was
built with PlatformIO directly (`platformio run -e nanofoc_d`, the same core directory, no
upload) on 2026-09-23: `[SUCCESS]`, no new compiler warning, `firmware.bin` 1,010,656 B
(`0xF6BE0`), SHA-256 `45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572`,
containing `1.0.0-cc5.2` and not `1.0.0-cc5.1`; RAM 228,928 B and flash 1,010,289 B used
(PlatformIO). The ELF has no `ESP32RMTController` symbol (FastLED's driver is gone), the IDF
RMT interrupt `rmt_driver_isr_default` and `rmt_fill_memory` are in IRAM (`0x40375928`,
`0x403758e4`), and both controllers with their item buffers are in internal RAM (`.bss` at
`0x3FCC3668` and `0x3FCC399C`). Stack frames: `CCRmtStrip::send` 32 B, `install` 80 B,
`recover` 32 B, each `showPixels` 32 B, `cc_handle_command` 0x250 (cc5.1: 0x230), `cc_service`
176 B. The release build by `build_nanod_cc5.py` on the same tree is incremental and must
produce the same image SHA-256.

**Release build (2026-09-23, 23:18:54 UTC).** `build_nanod_cc5.py` on the same tree:
`[SUCCESS]` (incremental, nothing recompiled), exit 0, **ACCEPTED**. `firmware.bin`
1,010,656 B, SHA-256 `45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572`,
identical to the compile verification; ESP magic `0xE9`, contains `1.0.0-cc5.2` and not
`1.0.0-cc5.1`; RAM 228,928 B and flash 1,010,289 B used. Log `work/nanod-cc5.2-build.log`
(2,089 B, SHA-256 `23fbc6cd87db8843aa5afa531c98b0bf2acba61f9c2218d3e9153638a0777deb`);
record `../diagnostics/cc5-build.json` (SHA-256
`b84d0be5f3e580ab9736ff25939ef1c4d58be4130487a19ff7264c9031dafd96`; the cc5.1 record is kept
as `cc5-build.superseded-20260923T231910Z.json`).

## Package (no device, manifest.json untouched)

```powershell
& '<repo>\app\.venv\Scripts\python.exe' '<repo>\tools\package_nanod_cc5.py'
```

The script requires an accepted build record whose SHA-256 still matches
`firmware.bin`. It writes three files to this folder:

- `nanod-control-center-1.0.0-cc5.2.bin`
- `nanod-control-center-1.0.0-cc5.2-source.zip`, built from
  `git ls-files --cached --others --exclude-standard` (read-only git with
  `safe.directory`, `.vscode/` excluded). Every archived file is compared with the
  working tree.
- `manifest-1.0.0-cc5.2.json`, with status `UNFLASHED`. It records artifact hashes,
  source hashes, `changedFromCc4` and `changedFromPreviousCc5` (added, modified and
  removed files against 1.0.0-cc5.1), expected capabilities, the compatibility note, and
  `gates` (SHA-256 of each gate log below).

It marks `manifest-1.0.0-cc5.1.json` (still `UNFLASHED`: the cc5.1 install was never
finalized, and the rollback restored only `manifest.json`) and `manifest-1.0.0-cc5.json`
`SUPERSEDED` with their history, keeping each previous file as
`manifest-<version>.superseded-<UTC>.json`; the images and source archives of 1.0.0-cc5 and
1.0.0-cc5.1 are never touched. Packaging 1.0.0-cc5.2 again (after a fix) keeps its previous
manifest, source archive and a different image as `<name>.superseded-<UTC>.<ext>`.
`manifest.json`, the installed cc4 record, is never modified here.

| Item | Value |
|---|---|
| `firmware.bin` | 1,010,656 B (`0xF6BE0`), `../diagnostics/cc5-build.json` (accepted, build started 2026-09-23T23:18:54Z) |
| app0 slot | 1,310,720 B (`0x140000`) |
| Headroom | 300,064 B |
| Change from cc4 (927,088 B) | +83,568 B (+1,760 B from 1.0.0-cc5.1) |
| Image SHA-256 | `45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572` (`nanod-control-center-1.0.0-cc5.2.bin`; identical to the compile verification) |
| RAM / flash used (PlatformIO) | 228,928 B / 1,010,289 B (+6,560 B RAM from cc5.1, almost all the LED item buffers) |
| Source archive | `nanod-control-center-1.0.0-cc5.2-source.zip`, 1,257,318 B, SHA-256 `f750529cfbe0d00df4cac499492bed1ebbb57482b96b29a3e00e191e189e5211`; 118 files, each equal to the working tree (checkout HEAD `79ca593f...`, none missing) |
| `changedFromCc4` | 22 added, 15 modified, 0 removed |
| `changedFromPreviousCc5` | from 1.0.0-cc5.1: 4 added (`src/cc_led_rmt.cpp`, `src/cc_led_rmt.h`, `src/cc_led_wire.cpp`, `src/cc_led_wire.h`), 10 modified (`CONTROL_CENTER.md`, `PRESENTATION_V4.md`, `platformio.ini`, `src/cc_diag.cpp`, `src/cc_diag.h`, `src/com_thread.cpp`, `src/control_center.cpp`, `src/hmi_thread.cpp`, `src/lcd_thread.cpp`, `src/main.cpp`), 0 removed, as expected |
| `manifest-1.0.0-cc5.2.json` | 26,286 B, SHA-256 `2bfb1a6c5cc3b484d023cf6c2822d49b870a007da0e8e745519a5794d1c7a8f3`, status `UNFLASHED`, validation `firmwareBuild` PASS, `physicalValidation` PENDING, `flashWriteIssued` false; 15 gate files recorded, among them this release's gate log, build log and build record |
| Superseded | `manifest-1.0.0-cc5.1.json` `UNFLASHED` -> `SUPERSEDED` (previous file kept as `manifest-1.0.0-cc5.1.superseded-20260923T231948Z.json`); `manifest-1.0.0-cc5.json` was already `SUPERSEDED`; their images and source archives untouched |
| `manifest.json` | untouched: still `1.0.0-cc4` `INSTALLED`, SHA-256 `99e32f021f37f5c18fdf4ed2153298581ec1aaa780a058190395db36d2d74f65` before and after |

History: 1.0.0-cc5 was 1,001,888 B, SHA-256 `c123f9dcf92ba9e58f9d5412681c62d0dfffcbd03f80208bc5f538abfc8d49f3`;
1.0.0-cc5.1 was 1,008,896 B, SHA-256 `f75ac481ec1ff6349a05cbee187af2e67a8e5addeea3cd389743db6cdbe64236`
(`nanod-control-center-1.0.0-cc5.bin` and `nanod-control-center-1.0.0-cc5.1.bin`, kept).

The desktop v3 bundle needs no rebuild for 1.0.0-cc5.2: no bundled companion source changed
(the changes are firmware, the `work/` tooling, the lcd-preview gates and the tests).
Checked read-only on 2026-09-23 at 23:19 UTC (`../diagnostics/cc5-desktop-v3-current-check.json`,
SHA-256 `4d30169cffc94660ade5477972c592c04452cd8d9fae6c3a88a50d8dfdfb4890`; the exe was never
run): the 15 bundled PYZ modules and the entry script `standalone.py` equal the current sources
compiled by the same Python 3.14.5, the 123 bundled assets are byte-identical, and
`desktop-dist-v3` (1,161 files) and `desktop-dist-v2` (1,097 files) match their SHA-256
listings with no mismatch, missing or extra file. `Build-Desktop.ps1` was not run; the v3 exe
is still SHA-256 `90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19`.

## Gate evidence

Each file's SHA-256 at packaging time is recorded in `manifest-1.0.0-cc5.2.json` under `gates`.

| Gate | Evidence |
|---|---|
| Stage 0: snapshot and protection | `../diagnostics/cc5-stage0.json`, `../backups/source-snapshots/` |
| Stage 1: builds unblocked | `../diagnostics/cc5-stage1-build.log` |
| Stage 2: contract, parser parity, serial | `../diagnostics/cc5-stage2-firmware.log`, `../diagnostics/cc5-stage2-tests.log` |
| Stage 5: LED model parity and hue report | `../diagnostics/cc5-stage5-leds.log`, `../diagnostics/cc5-led-hue-report.json` |
| Stage 6: LCD fonts, renderer, harness | `../diagnostics/cc5-stage6-lcd.log` |
| Stage 8: full gates | `../diagnostics/cc5-stage8-gates.log` |
| Stage 9: pre-build gates (suite, LED and parser parity, session capture, C++11, fonts, harness, report, frames) | `../diagnostics/cc5-stage9-gates.log` |
| Stage 9: build and package (1.0.0-cc5, superseded) | `work/nanod-cc5-build.log`, `../diagnostics/cc5-build.superseded-20260923T180621Z.json`, `manifest-1.0.0-cc5.json` |
| 1.0.0-cc5.1 gates (superseded release) | `../diagnostics/cc5-stage9-cc5.1-gates.log`, `../diagnostics/cc5-stage9-cc5.1-prebuild-gates.log`, `work/nanod-cc5.1-build.log`, `manifest-1.0.0-cc5.1.json` |
| 1.0.0-cc5.2 source gates, run on the final tree while writing it (2026-09-23; recorded here, not as a diagnostics log): `cpp11_gate.py` (5 shared units including `cc_led_wire.cpp`, the 5 font units, and the new firmware source rules: no `FastLED.addLeds<`, no other RMT user), `led_wire_tests.py` (87 checks, 200 random frames against an independent encoder), `light_tests.py` (2174149 checks, unchanged), `parse_tests.py` (220 parser cases, unchanged), the PlatformIO compile above (an incremental rebuild after the last change reproduced its SHA-256), and the 22 companion modules that create no Tk window (744 tests, Tk windows, serial ports and browsers blocked; `test_cc5_tooling.py` 147 of them). The LVGL harness (`build.py`, `cc5_report.py`) was not rerun: no LCD source changed. The four Tk modules (`test_cc_icons`, `test_cc_ui`, `test_cc_windows`, `test_standalone`) run with the whole suite in step 10, after the companion is quit | this section |
| 1.0.0-cc5.2 Stage 9 pre-build gates, build and package (2026-09-23, 23:18-23:20 UTC; no device, no COM port, no upload, no git writes, no Tk window; the running companion kept its PID) | `../diagnostics/cc5-stage9-cc5.2-prebuild-gates.log` (39,495 B, SHA-256 `9bd3e2d47034bc694ccf894f1e0eca10b14e1cb7145ac18a6a77001a2b87f90c`), ALL PASSED: `cpp11_gate.py` (5 shared units incl. `cc_led_wire.cpp`, 5 font units, firmware source rules), `led_wire_tests.py` (87 checks, 200 random frames), `light_tests.py` (2174149 checks), `parse_tests.py` (220 cases), a fresh session capture and `parse_tests.py --frames` on it (444 lines accepted, cc4 parser 225), `font_tests.py`, `build.py cc5-handoff` + `cc5_report.py` (19/19), `make_cc5_frames.py --check`, and the 22 non-Tk companion modules (744 tests; Tk, serial ports, browsers and hardware scripts blocked). Then `work/nanod-cc5.2-build.log`, `../diagnostics/cc5-build.json`, `manifest-1.0.0-cc5.2.json` (see the package table) |
| Stage 9: desktop v3 build and frozen smoke test (not installed) | `../diagnostics/cc5-stage9-desktop.json`, `../diagnostics/cc5-desktop-dist-v3-sha256.json` |
| Stage 9: tooling unit tests | `tests/test_cc5_tooling.py`, run as part of the companion suite |

## Hardware window (Stage 10)

### Go-ahead first

Nothing below runs without the user's explicit go-ahead. The request to the user
includes the rollback commands in [Rollback and abort](#rollback-and-abort) and
RECOVERY.md section 5. It also asks the user either to confirm physical BOOT/RESET
access on the enclosure or to accept explicitly that it is unestablished
(RECOVERY.md section 2).

The request also states the **stress+turn hard gate** of step 8b: the user must be at
the knob and, when `check_nanod_cc5.py` prints `Turn the knob continuously now for 60 s`,
turn it back and forth until `Stop turning` appears (about a minute). The untouched
pass before it needs the knob left alone. Fewer than 20 claimed position events inside
the stress+turn frame window, or a pause over 3 s in it, fails 8b as "turning not
detected during stress; rerun" (rerun 8b and keep turning until `Stop turning`; turning
only during the cold transfers before the stress does not count); any reboot or USB
re-enumeration during 8b or 8c is a NO-GO.

The request also states the **unattended soak gate** of step 8b (1.0.0-cc5.2): right after
`Stop turning`, the script prints `UNATTENDED SOAK: 20 min ...` and runs 20 minutes of
companion-like traffic (changed frames and heartbeats, cold and cached artwork, layout and
LED-style switches, flashes, and a release followed by a new control every 30 s) with a
`diag` checkpoint every 10 s. It needs nobody at the knob, turning is not needed, and there
is no audible cue, so 8b takes about 25-30 minutes in all. Every `diag` checkpoint of 8b and
8c, the soak's included, fails on a task age over 1000 ms (a stalled HMI, LCD, COM or FOC
task), an LED transmit timeout or driver error, or a forced release. A failed soak or
liveness check is a NO-GO (never a rerun), like a reboot. `finalize_nanod_cc5.py` refuses
cc5.2 without both stress passes, the turning, no reboot, liveness at every checkpoint and a
completed soak of at least 20 minutes. The request also says that the knob now runs cc4,
that step 4 only confirms the locked pre-cc5 backup (it is never replaced), that 1.0.0-cc5
reset during its stress with the knob untouched, and that 1.0.0-cc5.1 did not reset but its
HMI task hung inside `FastLED.show()` during the untouched stress (LEDs and buttons frozen,
releases never acknowledged) and was rolled back; cc5.2 replaces FastLED's LED transport and
adds the task watchdog, the release timeout and the liveness checks (see
[What 1.0.0-cc5.2 changes](#what-100-cc52-changes)).

### Ports, interpreters and evidence

Every script discovers its ports itself; none contains a COM number, and each aborts
unless exactly one port matches:

- **Application port:** `239A:8010`, serial `NANO_D`, compared case-insensitively.
- **ROM port:** `303A:1001`, serial `12:34:56:78:9A:BC`.

Two interpreters are used. The flashing scripts refuse to run outside the flash venv
or with an esptool other than 4.12.0.

| Name | Path | Steps |
|---|---|---|
| `$flash`: flash venv, esptool 4.12.0 | `<repo>\tools\nanod-flash-venv\Scripts\python.exe` | 3, 4, 5, 6, abort (`$flash`) and firmware rollback (`$flashPython`, as in RECOVERY.md) |
| `$app`: companion venv | `<repo>\app\.venv\Scripts\python.exe` | 2, 7, 8, 10 |

Each block sets the interpreter it runs to the absolute path above, so no block depends
on an earlier one for it. Each block also sets `$global:LASTEXITCODE = -1` before every
native command, so a command that did not run can never pass its exit-code check or
print a false exit 0. Two sets of variables carry evidence from one step to a later
one, and they exist only in the PowerShell window that set them: `$beforeInventory`
(step 2 to step 5) and `$demo`, `$dataDir`, `$stamp` and `$dataHashesBefore` (9a to
9b). The later step refuses to run without them.

Evidence goes to `<repo>\app\diagnostics`
(`diagnostics\` below). The scripts rename older evidence and never overwrite it.

Each step block below is wrapped in `. { ... }`, so the first `throw` stops the block.
Its messages mean:

- `GO: ...` (the block's last line): go on to the next step.
- `NOT RUN: ...`: the block stopped before it changed anything. Fix what the message
  names and run the same block again. This is never a reason for a rollback.
- `NO-GO: ...`: stop, and do what that step's **No-go** line says.

### Step 1. Quit the companion, disable its task, smoke-test the v3 build

Interpreter: none (PowerShell and the frozen v3 executable
`<repo>\app\desktop-dist-v3\NanoDControlCenter\NanoDControlCenter.exe`).

Quit the companion from its tray icon (**Quit**). Do not use `Stop-Process` or
`taskkill`: Quit releases the knob cleanly. Then disable the `NanoD Control Center` task
for the whole window, so the cc4-era companion cannot relaunch (it has a sign-in trigger
and three automatic restarts), and run the smoke test:

```powershell
. {
  Disable-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop | Out-Null
  if ((Get-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop).State -ne 'Disabled') { throw 'NOT RUN: the startup task is not disabled' }
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: NanoDControlCenter is still running; quit it from the tray' }
  $v3 = '<repo>\app\desktop-dist-v3\NanoDControlCenter\NanoDControlCenter.exe'
  $smokeJson = Join-Path $env:LOCALAPPDATA 'NanoDControlCenter\logs\smoke-test.json'
  $smokeStart = (Get-Date).ToUniversalTime()
  $smoke = Start-Process -FilePath $v3 -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru -Wait
  if ($smoke.ExitCode -ne 0) { throw "NO-GO: the frozen smoke test exited $($smoke.ExitCode)" }
  $report = Get-Content -Raw -LiteralPath $smokeJson -ErrorAction Stop | ConvertFrom-Json
  $written = (Get-Item -LiteralPath $smokeJson).LastWriteTimeUtc
  if ($report.pid -ne $smoke.Id -or $written -lt $smokeStart) { throw 'NO-GO: smoke-test.json is not from this run (pid or time differ)' }
  if ($report.passed -ne $true -or $report.frozen -ne $true -or $report.executable -ne $v3) { throw 'NO-GO: smoke-test.json reports a failed check or another executable' }
  "GO: smoke test pid $($smoke.Id) exit 0, smoke-test.json written $($written.ToString('o'))"
}
```

Go: the startup task is disabled, no `NanoDControlCenter` process runs, the smoke test
exits 0 first, and then `smoke-test.json` carries this run's pid, a time after the
start, `passed` and the v3 path. The smoke test takes no single-instance mutex and opens
no port.

No-go: nothing touched the knob. [Re-enable the companion](#re-enable-the-companion)
and stop; the v3 build needs fixing before any hardware step.

### Step 2. Pre-flash inventory (cc4, presentation 2)

Interpreter: `$app`. Script:
`<repo>\app\device_inventory.py`
(read-only; never enters host control).

```powershell
. {
  $beforeInventory = $null
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running; quit it from the tray, disable the startup task again (step 1, first two lines), then run this block again' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $appPort = & $app -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.find_app_port())"
  if ($LASTEXITCODE -ne 0 -or -not $appPort) { throw 'NO-GO: exactly one 239A:8010 NANO_D port is required' }
  $global:LASTEXITCODE = -1
  $output = & $app '<repo>\app\device_inventory.py' --port $appPort; $output
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: the inventory failed' }
  $saved = @($output | Select-String -Pattern '^Inventory saved: (.+)$')
  if ($saved.Count -ne 1) { throw 'NO-GO: device_inventory.py did not name one saved inventory' }
  $name = Split-Path -Leaf $saved[0].Matches[0].Groups[1].Value
  $inventory = Get-Content -Raw -LiteralPath "<repo>\app\backups\$name" -ErrorAction Stop | ConvertFrom-Json
  # profiles is one JSON object (name -> profile), so count its properties, not the object
  if ($inventory.settings.firmwareVersion -ne '1.0.0-cc4' -or $inventory.capabilities.presentation -ne 2 -or @($inventory.profiles.PSObject.Properties).Count -ne 10) { throw 'NO-GO: the knob is not cc4 with presentation 2 and ten profiles' }
  $beforeInventory = $name
  "GO: before-inventory $beforeInventory (1.0.0-cc4, presentation 2, ten profiles)"
}
```

Go: `backups\control-center-inventory-*.json` reports `1.0.0-cc4`, presentation 2 and
ten saved profiles. `device_inventory.py` writes `profiles` as one JSON object that maps
each name to its profile, so the block counts that object's properties. `$beforeInventory`
holds the file name for step 5.

No-go: nothing was sent that changes the knob, and it still runs cc4.
[Re-enable the companion](#re-enable-the-companion) and stop. A running companion is a
`NOT RUN`: quit it, disable the task again and run step 2 again.

### Step 3. Enter the ROM bootloader (one 1200-bps touch)

Interpreter: `$flash`. Script:
`<repo>\tools\nanod_enter_bootloader_v2.py`
(no esptool, no write).

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running; quit it from the tray, disable the startup task again (step 1, first two lines), then run this block again' }
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\nanod_enter_bootloader_v2.py'
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: no ROM bootloader port (the message above says why). Do not repeat the touch blindly; see the No-go line' }
  'GO: ROM bootloader present (see the printed port)'
}
```

The script sends one 1200-bps open with DTR false, then closes, and polls for
`303A:1001` with the chip MAC as its serial. It refuses, sending nothing, while the
companion runs. Evidence: `diagnostics\cc5-usb-boot-entry*.json`.

Go: exit 0 and `ROM bootloader: COM<n> (serial 12:34:56:78:9A:BC)`. Nothing is written
in this step.

No-go: nothing was written. If the message says the companion is running, it is a
`NOT RUN` (the script sent nothing): quit it from the tray, disable the task again and
run step 3 again. If the touch was sent but no ROM port appeared, list
ports: when the application port is back, cc4 is running, so
[re-enable the companion](#re-enable-the-companion) and stop; when a MAC-matched ROM
port is present, use [Abort before any write](#abort-before-any-write); when neither
appears, see RECOVERY.md section 2.

### Step 4. Full 4 MB backup

Interpreter: `$flash`. Script:
`<repo>\tools\backup_nanod_cc5.py` (`flash_id`,
`read_flash 0x0 0x400000`, `verify_flash 0x0` against the read; read-only on the device).

```powershell
. {
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\backup_nanod_cc5.py'
  if ($LASTEXITCODE -ne 0) { throw "NO-GO: backup exit $LASTEXITCODE; nothing was written" }
  $backup = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5-backup.json' -ErrorAction Stop | ConvertFrom-Json
  if ($backup.passed -ne $true -or $backup.identityVerified -ne $true -or $backup.verifiedAgainstDevice -ne $true -or $backup.bytes -ne 4194304 -or $backup.cc4AtApp0 -ne $true -or $backup.file -ne 'nanod-cc4-before-cc5-full.bin') { throw 'NO-GO: cc5-backup.json is not a verified 4 MB cc4 backup' }
  "GO: backups\nanod-cc4-before-cc5-full.bin, 4,194,304 B, sha256 $($backup.sha256)"
}
```

Go: exit 0, and `cc5-backup.json` shows the MAC and 4MB identity, 4,194,304 B verified
against the device, cc4 at app0, and `nanod-cc4-before-cc5-full.bin` as the backup. For
1.0.0-cc5.2, as for 1.0.0-cc5.1, the record's `role` is `current backup (identical to the
locked pre-cc5 backup)`: see below.

No-go: nothing was written; use [Abort before any write](#abort-before-any-write). Exit
3 means the fresh read differs from the locked pre-cc5 backup (or its app0 is not cc4);
the read was kept as a diagnostic read. After that abort, inspect with the user.

`backup_nanod_cc5.py` never replaces the pre-cc5 backup once it is a rollback input.
That is the case when any `cc5-flash-checks*.json` records a write attempt, when a
`cc5-rollback*.json` exists, or when a cc5 manifest (`manifest-1.0.0-cc5.2.json`, or the
superseded `manifest-1.0.0-cc5.json` and `manifest-1.0.0-cc5.1.json`) is no longer
`UNFLASHED`. All three hold since the 1.0.0-cc5 and 1.0.0-cc5.1 installs and rollbacks.
The script then accepts the fresh read as a valid **current** backup only when it is
byte-identical to the locked
`nanod-cc4-before-cc5-full.bin` (which is what the verified rollback left: the knob holds
exactly those bytes), its app0 holds cc4, and `cc5-backup.json` records that file's
SHA-256. It keeps the read as `backups/nanod-cc4-confirm-read-<UTC>.bin`, writes a new
`cc5-backup.json` naming the same backup file and SHA-256 (the old record is kept as
`cc5-backup.superseded-<UTC>.json`) and exits 0; prepare and install keep using the
locked backup. When the read differs in any byte, nothing is accepted: it is kept as
`backups/nanod-diagnostic-full-<UTC>.bin`, with `cc5-backup-diagnostic-read-<UTC>.json`,
and the script exits 3. A failed backup run never replaces `cc5-backup.json` either; its
record is `cc5-backup-failed-<UTC>.json`.

### Step 5. Prepare (host only)

Interpreter: `$flash`. Script:
`<repo>\tools\prepare_nanod_cc5_install.py
--before-inventory <step 2 file>`. It reads files only; the knob stays in the ROM
bootloader.

```powershell
. {
  if (-not $beforeInventory) { throw 'NOT RUN: $beforeInventory is not set in this window; set it to the file name on the GO line of step 2, then run step 5 again' }
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\prepare_nanod_cc5_install.py' --before-inventory $beforeInventory
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: prepare stopped; nothing was written' }
  $prep = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5-preparation.json' -ErrorAction Stop | ConvertFrom-Json
  $rollbackHash = (Get-FileHash -Algorithm SHA256 -LiteralPath '<repo>\app\backups\nanod-cc4-before-cc5-active-app.bin' -ErrorAction Stop).Hash
  if ($prep.activeApp -ne 'app0' -or $prep.applicationOffset -ne 0x10000 -or $prep.applicationSize -ne 0x140000 -or $prep.partitionTableUnchanged -ne $true -or $prep.otaSelectionUnchanged -ne $true) { throw 'NO-GO: the layout is not app0 at 0x10000/0x140000 with the original partition table and OTA data' }
  if ($prep.rollbackStartsWithCc4 -ne $true -or $prep.cc4ImageSha256 -ne '89ddf172ffa43bf3e3721868ab5a0d502f906460b5caaa72b15ba67c793be737' -or $prep.rollbackBytes -ne 1310720 -or $rollbackHash -ne $prep.rollbackSha256) { throw 'NO-GO: the rollback app0 is not the verified cc4 app0' }
  "GO: rollback app0 sha256 $($prep.rollbackSha256); expected image sha256 $($prep.expectedSha256)"
}
```

Go: the partition table and OTA data are unchanged, OTA selects app0 at
`0x10000`/`0x140000`, app0 holds the cc4 image (SHA-256 `89ddf172...`), and
`backups\nanod-cc4-before-cc5-active-app.bin` (1,310,720 B) matches `rollbackSha256`.
`backups\nanod-cc5.2-expected-full.bin` is the backup with 1.0.0-cc5.2 at app0 and the
rest of its last 4 KB sector erased (`nanod-cc5-expected-full.bin` and
`nanod-cc5.1-expected-full.bin` stay as history).

No-go: nothing was written; use [Abort before any write](#abort-before-any-write).

### Step 6. App-only install

Interpreter: `$flash`. Script:
`<repo>\tools\install_nanod_cc5.py`.

```powershell
. {
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\install_nanod_cc5.py'
  $installExit = $LASTEXITCODE
  "install_nanod_cc5.py exit $installExit; act on it with the table below"
}
```

`install_nanod_cc5.py` runs every step before the final reset with `--baud 460800
--before no_reset --after no_reset_stub`, so the stub session is kept throughout, as in
the proven cc4 install:

1. `flash_id`: MAC and 4MB.
2. `verify_flash 0x0` against the fresh backup.
3. `write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000` with the cc5.2 image.
4. `verify_flash 0x0` against the prepared expected image.
5. Only then `read_mac --after hard_reset`.

It never uses `erase_flash`, a filesystem upload, a PlatformIO upload or a full-image
write. If step 3 or 4 fails, the script does **not** reset. The same applies if anything
unexpected happens after the write starts. In the same stub session it writes the cc4
active-app backup at `0x10000`, verifies app0, and verifies the full image against the
fresh backup. It resets only after all three pass.

The exit code and the `outcome` in `diagnostics\cc5-flash-checks.json` agree:

| Exit | Outcome | Meaning | Go / no-go |
|---|---|---|---|
| 0 | `INSTALLED_VERIFIED_RESET` | cc5 written, full 4 MB verified, reset confirmed. | GO: step 7. |
| 5 | `INSTALLED_VERIFIED_RESET_UNCONFIRMED` | cc5 verified in flash; the reset was not confirmed. | Run only the printed `read_mac --after hard_reset` command, once. Then GO: step 7. At step 10, add `--accept-unconfirmed-reset`. |
| 1 | none | Nothing was sent: wrong environment, an input file's SHA-256, or not exactly one ROM port. | NO-GO: [Abort before any write](#abort-before-any-write). |
| 2 | `STOPPED_BEFORE_WRITE` | Identity or pre-write verify failed (or a usage error). Nothing written, no reset. | NO-GO: [Abort before any write](#abort-before-any-write). |
| 3 | `RESTORED_CC4_RESET` | cc5 failed; cc4 restored and verified, then reset. | NO-GO: cc4 runs again. [Re-enable the companion](#re-enable-the-companion) and stop. |
| 6 | `RESTORED_CC4_VERIFIED_RESET_UNCONFIRMED` | cc5 failed; cc4 restored and verified; the reset was not confirmed. | Run only the printed command, once. Then as exit 3. |
| 4 | `RESTORE_FAILED_NO_RESET` | The restore did not verify. The chip was **not** reset. | NO-GO: do not reset, unplug or power-cycle. [Firmware rollback](#firmware-rollback-cc5---cc4) (scripted) now. |
| -1 | none | The script did not run (the block's own marker). | NOT RUN: nothing was sent; fix the interpreter path and run step 6 again. |
| Any other | `STARTED` or none | The script was interrupted (for example with Ctrl+C). | NO-GO. Open `diagnostics\cc5-flash-checks.json`: if `writeAttempted` is true, or the file is missing or older than this run, do not reset; [firmware rollback](#firmware-rollback-cc5---cc4) (scripted). Otherwise [Abort before any write](#abort-before-any-write). |

A reset counts as confirmed only when esptool exits 0, names the chip MAC and prints
its hard-reset line.

### Step 7. Boot sanity (no companion)

Interpreter: `$app` (port listing only; no port is opened).

Watch the knob: the native screen must come up and stay for at least 30 s, with no
reboot loop. Then:

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running. Quit it from the tray, disable the startup task again (step 1, first two lines), then run step 7 again. This is not a firmware fault' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $appPort = & $app -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.poll_ports(t.is_app_port, 60, settle=30)[0] or '')"
  if ($LASTEXITCODE -ne 0 -or -not $appPort) { throw 'NO-GO: 239A:8010 NANO_D did not stay enumerated for 30 s' }
  "GO: $appPort stable for 30 s"
}
```

Go: one `239A:8010` (`NANO_D`) port enumerated without interruption for 30 s, the
native screen seen for at least 30 s, and no companion process.

No-go (unstable port, no native screen or a reboot loop):
[firmware rollback](#firmware-rollback-cc5---cc4). If neither the application port nor
the ROM port appears, write nothing and see RECOVERY.md section 2. A running companion
is a `NOT RUN`, never a reason for a firmware rollback.

### Step 8. Post-flash checks

Interpreter: `$app` for all three. The companion stays quit: each block first refuses
with `NOT RUN` while a `NanoDControlCenter` process exists. The check scripts also refuse
on their own (`require_companion_quit`) before they write any evidence.

**8a. Inventory.** Script:
`<repo>\app\device_inventory.py`.

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running; quit it from the tray, disable the startup task again (step 1, first two lines), then run this block again' }
  $afterName = $null
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $appPort = & $app -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.find_app_port())"
  if ($LASTEXITCODE -ne 0 -or -not $appPort) { throw 'NO-GO: exactly one 239A:8010 NANO_D port is required' }
  $global:LASTEXITCODE = -1
  $output = & $app '<repo>\app\device_inventory.py' --port $appPort; $output
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: the inventory failed' }
  $saved = @($output | Select-String -Pattern '^Inventory saved: (.+)$')
  if ($saved.Count -ne 1) { throw 'NO-GO: device_inventory.py did not name one saved inventory' }
  $name = Split-Path -Leaf $saved[0].Matches[0].Groups[1].Value
  $after = Get-Content -Raw -LiteralPath "<repo>\app\backups\$name" -ErrorAction Stop | ConvertFrom-Json
  # profiles is one JSON object (name -> profile), so count its properties, not the object
  if ($after.settings.firmwareVersion -ne '1.0.0-cc5.2' -or $after.capabilities.presentation -ne 4 -or @($after.profiles.PSObject.Properties).Count -ne 10) { throw 'NO-GO: the knob is not cc5.2 with presentation 4 and ten profiles' }
  $afterName = $name
  "GO: $afterName (1.0.0-cc5.2, presentation 4, ten profiles)"
}
```

**8b. Device checks.** Script:
`<repo>\tools\check_nanod_cc5.py`. Leave the knob
alone until the script prints `Turn the knob continuously now for 60 s`; then turn it
back and forth until `Stop turning` appears. After that the unattended soak runs for 20
minutes (`UNATTENDED SOAK: 20 min ...`, then one progress line every 10 s): you may leave
the knob, no turning is needed, and there is no audible cue. The block takes about 25-30
minutes.

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running; quit it from the tray, disable the startup task again (step 1, first two lines), then run this block again' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\check_nanod_cc5.py' --turn-seconds 60 --soak-minutes 20
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: device checks failed; see failures and gates in diagnostics\cc5-device-checks.json. If the output above says NanoDControlCenter is running, it is NOT RUN instead (no evidence was written): quit it, disable the startup task again and run 8b again. If the only failures are turning not detected or a touched untouched pass, run 8b again and turn only when prompted. A stalled task, LED transmit failure, forced release or failed soak is never a rerun' }
  'GO: diagnostics\cc5-device-checks.json passed'
}
```

It works in two parts, with reboot detection throughout:

- **Reboot detection:** `diag` (`resetReason`, `uptimeMs`, `bootCount`) at the start and
  after every section (and every 10 s in the soak), a port watcher throughout, and Windows'
  LastArrivalDate for the knob's USB device whenever no raw control is claimed (also after
  each soak release). A changed `bootCount`, an uptime
  that went back, or any re-enumeration prints
  `!!! REBOOT OR USB RE-ENUMERATION DETECTED` and fails the run; the script then waits
  for the knob and reads `diag` once more, read-only, so the evidence names the reset
  reason, the ROM reasons per CPU and each task's last breadcrumb. The start also
  requires a blank coredump partition and the receive queue in internal RAM.
- **Task liveness (1.0.0-cc5.2):** every one of those `diag` replies must show each task
  age (`hmiAgeMs`, `lcdAgeMs`, `comAgeMs`, `focAgeMs`) at most 1000 ms, `ledTxTimeouts`,
  `ledWriteErrors` and `forcedReleases` at 0 and both LED strips installed; otherwise it
  prints `!!! TASK STALL, LED TRANSMIT FAILURE OR FORCED RELEASE` with the stalled task's
  step and fails the run. 1.0.0-cc5.1's hang passed every reboot check; it fails this one.
- **DeviceBridge part:** inventory and capabilities (presentation 4; artwork with
  `composited: "scrim80"` and `available`; `glyphs`; `diag`), saved profiles identical
  and only `firmwareVersion` changed against the step 2 inventory, the four controls
  ready at their positions, v4 frames in both LED styles, and bridge-level art (cold
  transfer, cache hit, a superseded cover never becoming ready).
- **Raw serial part:** v2 frames accepted; stale frame and stale control rejected
  while the control stays claimed; art CRC, cache, stale and parse cases; per-chunk
  timing of a cold transfer plus three more cold transfers (the start of the 1.0.0-cc5
  run-1 sequence); **stress, untouched:** about 300 frame updates interleaved with art
  transfers right after them, with zero error replies, no release and no knob events;
  **stress+turn:** the same sequence again while you turn the knob, with at least 20
  claimed position events inside the stress-frame window and no pause over 3 s in it,
  from its start to its end (otherwise "turning not detected during stress; rerun", a
  FAIL to rerun; events during the cold transfers before it do not count), the largest
  knob-event gaps recorded; the **unattended soak** (20 minutes, see above; the stress
  control is released first and must not be released `forced`; the first error reply, art
  error, unexpected or forced release, failed checkpoint or missing reply stops it with
  `!!! SOAK STOPPED`); and diag margins (LVGL heap at least 25 % free at its minimum, LCD,
  COM, HMI and FOC stacks above 1 KB, no serial reply cut short).

The evidence's `gates` object must be all true for step 10: `stressUntouched`,
`stressTurn`, `turningDetected`, `noRebootOrReenumeration`, `rebootFieldsReported`,
`coredumpBlank`, `rxQueueInternal`, `diagMargins`, `taskLiveness` (every checkpoint
healthy) and `unattendedSoak` (a completed soak of at least 20 minutes). The evidence also
records every checkpoint's liveness in `rebootWatch.timeline`, any failure in
`liveness.failures`, and the soak's cycles, releases, checkpoints and transfers in
`sections.soak`.

**8c. Lease checks.** Script:
`<repo>\tools\check_nanod_cc5_lease.py`. Turn the
knob during the native observation.

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running; quit it from the tray, disable the startup task again (step 1, first two lines), then run this block again' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\check_nanod_cc5_lease.py' --observe-native-seconds 10
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: lease checks failed; see failures in diagnostics\cc5-lease-checks.json. If the output above says NanoDControlCenter is running, it is NOT RUN instead (no evidence was written): quit it, disable the startup task again and run 8c again' }
  'GO: diagnostics\cc5-lease-checks.json passed'
}
```

It checks five things:

- The lease expires about 2 s after ready.
- Art packets alone do not renew it.
- Frames continue through transfers lasting several lease periods.
- After a host-lost expiry the claim is released: stale frame, native knob events,
  re-entry and intentional release. Confirm by eye that the LCD shows
  "NANO_D++ / Waiting for PC / Native controls active" and then the native screen.
- No reboot: `diag` at the start and at the end shows the same `bootCount` and a later
  `uptimeMs`.
- Task liveness (1.0.0-cc5.2): both of those `diag` replies show every task age at most
  1000 ms and no LED transmit failure or forced release; every release in the cases is
  acknowledged normally (`lease-expired` for an expiry, no reason for the intentional one).

Go: all three exit 0.

No-go: stop and decide with the user between investigating on cc5 (the companion stays
quit while you investigate) and the [firmware rollback](#firmware-rollback-cc5---cc4).
A reboot or re-enumeration is always this no-go, never a rerun: keep
`diagnostics\cc5-device-checks.json` (its `rebootWatch.postDropDiag` holds the reset
reason and the breadcrumbs) and, when the reason is `brownout` or `poweron`, check the USB
port, cable and power source before anything else. A `task_wdt` reset means a task stalled
for 10 s: keep the core dump (never erase it; read `0x3F0000 0x10000` with `esptool
read_flash` for analysis) and the breadcrumbs. A stalled task, an LED transmit failure, a
forced release or a failed soak is the same no-go: keep the evidence (`liveness.failures`,
`sections.soak`) and read `diag` once more, read-only, before deciding.
Do not finalize. A running companion is a `NOT RUN`, never a reason for a firmware
rollback: quit it, disable the task again and run the same block again. If you stay on
cc5 without finalizing, [re-enable the companion](#re-enable-the-companion): the cc4-era
companion works with cc5, which accepts its v2 frames (8b).

### Step 9. Install the desktop app (v3)

Interpreter: PowerShell. Script:
`<repo>\app\Install-Desktop.ps1`.
Run 9a and 9b in the same window; 9c sets its own paths.

**9a. Keep the installed program and records; hash the user data.** Only hashes of
`credentials.bin` and `settings.json` are recorded, never their contents.

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: quit the companion from the tray first' }
  $demo = '<repo>\app'
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $programs = Join-Path $env:LOCALAPPDATA 'Programs\NanoDControlCenter'
  $dataDir = Join-Path $env:LOCALAPPDATA 'NanoDControlCenter\data'
  $dataHashesBefore = $null
  $programBackup = "$demo\backups\desktop-program-before-cc5-$stamp"
  Copy-Item -LiteralPath $programs -Destination $programBackup -Recurse -ErrorAction Stop
  if (@(Get-ChildItem -LiteralPath $programBackup -File -Recurse).Count -ne @(Get-ChildItem -LiteralPath $programs -File -Recurse).Count) { throw 'NO-GO: the program folder copy is incomplete' }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath "$programBackup\NanoDControlCenter.exe" -ErrorAction Stop).Hash -ne '95909AAE4AA4852F5E4954EEED329E513FC474BC50E08B8DCD6655CE410A123D') { throw 'NO-GO: the installed exe is not the recorded cc4-era companion' }
  foreach ($name in 'desktop-installation.json', 'desktop-startup-task.xml', 'desktop-user-data.json', 'native-desktop-verification.json') {
    $old = "$demo\diagnostics\$name"
    $keep = "$demo\diagnostics\" + [IO.Path]::GetFileNameWithoutExtension($name) + "-before-cc5-$stamp" + [IO.Path]::GetExtension($name)
    if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $keep -ErrorAction Stop }
  }
  $hashes = @(Get-FileHash -Algorithm SHA256 -LiteralPath "$dataDir\credentials.bin", "$dataDir\settings.json" -ErrorAction Stop | Select-Object @{n = 'file'; e = { Split-Path -Leaf $_.Path } }, @{n = 'sha256'; e = { $_.Hash } })
  $hashes | ConvertTo-Json | Out-File -NoClobber -Encoding utf8 -LiteralPath "$demo\diagnostics\cc5-desktop-data-sha256-before-$stamp.json" -ErrorAction Stop
  $dataHashesBefore = $hashes
  "GO: program folder kept as $programBackup; data hashes recorded"
}
```

The installer overwrites `desktop-installation.json` and `desktop-startup-task.xml` and
recreates `desktop-user-data.json`; `Verify-NativeDesktop.ps1` overwrites
`native-desktop-verification.json`. 9a keeps the cc4-era copies as `*-before-cc5-<UTC>`.

No-go (9a): nothing was installed, and the cc4-era companion is still installed. It
works with cc5, which accepts v2 frames (step 8b). [Re-enable the
companion](#re-enable-the-companion) and decide with the user.

**9b. Forward install with `-Mirror`.** `-Mirror` removes program files that v3 no
longer ships, so the installed folder matches `desktop-dist-v3` exactly. The installer
verifies every file hash, never overwrites existing user data, and re-registers the
startup task (the new registration is enabled, with its sign-in trigger; nothing starts
until 9c).

```powershell
. {
  if (-not ($demo -and $dataDir -and $stamp -and $dataHashesBefore)) { throw 'NOT RUN: run 9a in this window first; nothing was installed' }
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v3 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: Install-Desktop.ps1 failed; use the desktop rollback' }
  $dataHashesAfter = @(Get-FileHash -Algorithm SHA256 -LiteralPath "$dataDir\credentials.bin", "$dataDir\settings.json" -ErrorAction Stop | Select-Object @{n = 'file'; e = { Split-Path -Leaf $_.Path } }, @{n = 'sha256'; e = { $_.Hash } })
  $dataHashesAfter | ConvertTo-Json | Out-File -NoClobber -Encoding utf8 -LiteralPath "$demo\diagnostics\cc5-desktop-data-sha256-after-$stamp.json" -ErrorAction Stop
  if (Compare-Object $dataHashesBefore $dataHashesAfter -Property file, sha256) { throw 'NO-GO: credentials.bin or settings.json changed during the install' }
  $installed = Get-Content -Raw -LiteralPath "$demo\diagnostics\desktop-installation.json" -ErrorAction Stop | ConvertFrom-Json
  $bundleHash = (Get-FileHash -Algorithm SHA256 -LiteralPath "$demo\desktop-dist-v3\NanoDControlCenter\NanoDControlCenter.exe" -ErrorAction Stop).Hash
  if ($installed.sha256 -ne $bundleHash) { throw 'NO-GO: the installed exe is not the v3 bundle' }
  "GO: v3 installed ($bundleHash); user data hashes unchanged"
}
```

The v3 bundle exe recorded in Stage 9 has SHA-256 `90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19`.

No-go (9b): [desktop rollback](#desktop-rollback-cc5-companion---cc4-era-companion). A
change in the user data hashes also needs the user: the installer never writes existing
user data, so something else did.

**9c. Re-enable and start the task, then verify.** This block sets its own paths, so it
also runs in a new window after 9b.

```powershell
. {
  $demo = '<repo>\app'
  $dataDir = Join-Path $env:LOCALAPPDATA 'NanoDControlCenter\data'
  Enable-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop | Out-Null
  $taskStart = Get-Date
  Start-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop
  $statusFile = Join-Path $env:LOCALAPPDATA 'NanoDControlCenter\logs\status.json'
  do {   # up to 90 s for the knob to connect; status.json is rewritten while the app runs
    Start-Sleep -Seconds 3
    try { $status = Get-Content -Raw -LiteralPath $statusFile -ErrorAction Stop | ConvertFrom-Json } catch { $status = $null }
    $fresh = $status -and (Get-Item -LiteralPath $statusFile).LastWriteTime -ge $taskStart
  } until (($fresh -and $status.ready -eq $true) -or (Get-Date) -gt $taskStart.AddSeconds(90))
  $exe = Join-Path $env:LOCALAPPDATA 'Programs\NanoDControlCenter\NanoDControlCenter.exe'
  $processes = @(Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue)
  if ($processes.Count -ne 1 -or $processes[0].Path -ne $exe) { throw "NO-GO: expected exactly one NanoDControlCenter process from $exe" }
  if (-not $fresh -or $status.pid -ne $processes[0].Id) { throw 'NO-GO: status.json is not from this process' }
  if ($status.ready -ne $true -or $status.connected -ne $true -or $status.firmwarePresentation -ne 4 -or $status.dataDir -ne $dataDir) { throw 'NO-GO: status.json is not ready on presentation 4 with the real data folder' }
  $readyLine = Select-String -LiteralPath (Join-Path $env:LOCALAPPDATA 'NanoDControlCenter\logs\app.log') -Pattern 'Device ready' | Select-Object -Last 1
  if (-not $readyLine -or [datetime]::ParseExact($readyLine.Line.Substring(0, 19), 'yyyy-MM-dd HH:mm:ss', $null) -lt $taskStart.AddSeconds(-1)) { throw 'NO-GO: app.log has no "Device ready" line since the start' }
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\diagnostics\Verify-NativeDesktop.ps1'
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: Verify-NativeDesktop.ps1 failed' }
  $native = Get-Content -Raw -LiteralPath "$demo\diagnostics\native-desktop-verification.json" -ErrorAction Stop | ConvertFrom-Json
  if ($native.diagnosticExitCode -ne 0 -or $native.music.passed -ne $true) { throw 'NO-GO: the read-only Apple Music check failed' }
  "GO: pid $($processes[0].Id), $($status.deviceStatus)"
}
```

Go: one process from the install path, a `status.json` written by that process after
the start (ready, connected, presentation 4, the real data folder), a `Device ready`
line in `app.log` since the start, and `Verify-NativeDesktop.ps1` passing its read-only
Apple Music check.

No-go (9c): quit the companion from its tray icon, then
[desktop rollback](#desktop-rollback-cc5-companion---cc4-era-companion).

### Step 10. Finalize (records only)

Interpreter: `$app`. Script:
`<repo>\tools\finalize_nanod_cc5.py`. It touches
no device, network or desktop, and checks everything before it writes anything.

Run the companion suite first and note its count:

```powershell
. {
  $app = '<repo>\app\.venv\Scripts\python.exe'
  Set-Location '<repo>\app'
  $global:LASTEXITCODE = -1
  & $app -m unittest discover -s tests -q
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: the companion suite failed; do not finalize' }
  'GO: note the count on the "Ran <n> tests" line above'
}
```

Then finalize. Replace `<suite-tests>` with that count; left in place, it stops
PowerShell from running the block at all. The light count, 2174149, is the
`PASS: 2174149 light-renderer check(s)` line of the `light_tests.py` gate: unchanged in
1.0.0-cc5.2 (the logical LED model did not change; the count was the same in the
1.0.0-cc5, 1.0.0-cc5.1 and 1.0.0-cc5.2 gate logs, `diagnostics\cc5-stage9-gates.log`,
`diagnostics\cc5-stage9-cc5.1-prebuild-gates.log` and
`diagnostics\cc5-stage9-cc5.2-prebuild-gates.log`). Type it without separators; a
comma would make PowerShell pass a list. Replace it only if a later `light_tests.py` gate
ran.

```powershell
. {
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\finalize_nanod_cc5.py' --companion-tests <suite-tests> --light-assertions 2174149
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: finalize refused (see its STOP line); nothing was recorded' }
  $firmware = '<repo>\app\firmware'
  if ((Get-FileHash -LiteralPath "$firmware\manifest.json").Hash -ne (Get-FileHash -LiteralPath "$firmware\manifest-1.0.0-cc5.2.json").Hash) { throw 'NO-GO: manifest.json is not the cc5.2 record' }
  'GO: cc5.2 recorded as INSTALLED'
}
```

After install exit 5, add `--accept-unconfirmed-reset` to the finalize line. Without it,
only outcome `INSTALLED_VERIFIED_RESET` is accepted.

Finalize requires `cc5-flash-checks.json` with a verified install, and
`cc5-device-checks.json` and `cc5-lease-checks.json` that passed, were written after it,
and show `1.0.0-cc5.2` with presentation 4. The device checks' `gates` must all be true
(both stress passes, the turning, no reboot or re-enumeration, the reboot fields, a blank
coredump partition, the internal receive queue, the diag margins, task liveness at every
checkpoint and the completed 20-minute unattended soak). It records the SHA-256 of every
evidence file in `cc5-installation.json`. The 1.0.0-cc5 and 1.0.0-cc5.1 installs and their
rollbacks, all from before this install, are history and do not block it. It refuses
after any rollback made or started since the install, even one that left no
`cc5-rollback.json`. It checks for a `cc5-rollback*.json`
or `manifest-at-cc5-rollback-*.json`, a `backups\cc5-manual-rollback-*` or
`backups\cc5-rollback-*` folder, a `cc5-rollback-*.log`, and a ROM bootloader entry
(`cc5-usb-boot-entry*.json`) from at or after the install. It also refuses a cc5
manifest marked `ROLLED_BACK`, or a `manifest.json` that is not the record its status
requires. On success it writes `diagnostics\cc5-installation.json`, marks
`manifest-1.0.0-cc5.2.json` `INSTALLED`, copies it byte-identically to `manifest.json`,
and updates `diagnostics\validation.json`, keeping the old one as
`validation-before-cc5.json`.

Go: `GO: cc5.2 recorded as INSTALLED`.

No-go: finalize wrote nothing, and the knob and the desktop app keep working as they
are. Fix what the STOP line names (for example a placeholder left in, or a post-flash
check that ran before the install) and run step 10 again. Never roll back because of a
finalize refusal alone. If the STOP line names a rollback or a bootloader entry after
the install, cc5 cannot be recorded from this install's evidence: decide with the user.

Physical acceptance (Stage 11) is separate. Nothing above claims it.

## Rollback and abort

### Abort before any write

Use this for a NO-GO in steps 3-5, or install exit 1 or 2. Nothing was written, so cc4
is intact and a reset is safe. If the knob is in the ROM bootloader, leave it with the
read-only reset (interpreter `$flash`). The block does not rely on remembering that
nothing was written: it verifies app0 against the cc4 image first (read-only) and resets
only when that verify passes.

```powershell
. {
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flash -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.find_rom_port())"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'Exactly one MAC-matched ROM port is required; nothing was reset. If 239A:8010 (NANO_D) is present, cc4 is already running' }
  $global:LASTEXITCODE = -1
  & $flash -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 '<repo>\app\firmware\nanod-control-center-1.0.0-cc4.bin'
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not hold the cc4 image, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob: run this block again once; if app0 still does not verify, leave the knob in the ROM bootloader and decide with the user (RECOVERY.md section 5, reset rule)' }
  $global:LASTEXITCODE = -1
  $reset = (& $flash -u -m esptool --chip esp32s3 --port $romPort --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed; list ports before trying again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed; list ports before trying again, once' }
  'cc4 is restarting. Next: re-enable the companion.'
}
```

Then [re-enable the companion](#re-enable-the-companion). For a NO-GO in steps 1-2 the
knob never left cc4: only re-enable the companion.

### Firmware rollback, cc5 -> cc4

Use this after install exit 4 (without any reset), or for a NO-GO in steps 7-8. Keep
the companion quit; the startup task is still disabled from step 1. Primary path,
scripted, with the flash venv. This block is the same as the scripted block in
RECOVERY.md section 5:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false   # this block may write app0
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\nanod_enter_bootloader_v2.py'
  if ($LASTEXITCODE -ne 0) { throw 'No ROM bootloader port; this block sent and wrote nothing. If the message above says the companion is running: quit it from the tray and run this block again. After install exit 4 or a failed rollback write, if no MAC-matched ROM port remains: stop (reset rule). Otherwise fix the cause (section 2) and run this block again' }
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py'
  "rollback_nanod_cc5.py exit $LASTEXITCODE; act on it with the table below"
}
```

Act on the exit code with the table in RECOVERY.md section 5 (Firmware, scripted). The
bootloader step sends nothing when the ROM port is already present (after install exit
4). RECOVERY.md section 5 also has the reset and retry rules, the manual esptool
fallback and the checks after the rollback (inventory `1.0.0-cc4`, presentation 2, ten
profiles). Install exit 4 counts as a started rollback write: from then on, never reset,
unplug or power-cycle the knob except as that section says.

### Desktop rollback, cc5 companion -> cc4-era companion

Use this for a NO-GO in 9b or 9c, or with a firmware rollback when wanted (the cc5
companion also works with cc4). Quit the companion from its tray icon first, then:

```powershell
. {
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v2 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'The desktop rollback failed; the program folder copy from step 9a is in backups\desktop-program-before-cc5-<UTC>' }
}
```

Then [re-enable the companion](#re-enable-the-companion).

### Re-enable the companion

```powershell
. {
  Enable-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop | Out-Null
  Start-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop
}
```
