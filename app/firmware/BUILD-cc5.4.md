# cc5.4 "Warm · alive" (1.0.0-cc5.4, binaries A to E) and desktop v7 (Desk Dial): build, package, install

Status (2026-09-26, after the hardware window): **binary A was installed (18:35 UTC) and rolled back
(21:12 UTC, `ROLLED_BACK_VERIFIED_RESET`, the full 4 MB equal to the locked pre-cc5.4 backup)** after two
defects the user saw: the LCD stayed dark in every mode and the LEDs flickered. A was never finalized
(`manifest-1.0.0-cc5.4.json` stays `UNFLASHED`). **The knob runs 1.0.0-cc5.3 with Desk Dial v7.** A, B and
C are retired; the fix binaries **D** (A + fixes, the release candidate) and **E** (C + fixes, the
fallback) take their place. After the review of the first D / E build, they were rebuilt by
`build_nanod_cc5.py` (2026-09-27 00:46 UTC, both accepted, the LCD data-line gate with its new call-order
check passed) and repackaged by `package_nanod_cc5.py` (00:47 UTC) after the stage9c gates, both
**UNFLASHED**: binary **D** image SHA-256
`02dcb7d10e64043de7d33fbe0879795235740e3d6d87f8fcc364aab2415774db`, binary **E**
`f7aba69bd3fb8d21acc7ed7f9cdf1a9045c35bf48490a33343fe97e3e8e69917` (the first build's packages are kept
as `*.superseded-20260927T004731Z.*`). See [Fix binaries D and E](#fix-binaries-d-and-e), which also holds
the review fixes and the look session that installs D.

History, the first ladder: **1.0.0-cc5.4 built by `build_nanod_cc5.py` and packaged by `package_nanod_cc5.py` on
2026-09-26 as the three binaries of the PRESENTATION_V5 12.6 build ladder (lead ruling R-m), all
UNFLASHED:** binary **A** (release candidate) image SHA-256
`a3bf376326849481411c74fa69c8602c4e2da97c7b015032c061fba2b5166314`, binary **B** (middle)
`c4ad0cd3a02191e0903d215c69b5060ca5edfc241a9fbe4c5a7ad39d98a60347`, binary **C** (fallback)
`ec60f278571367e84e3cad10f2f8b833245bbcc6383f8aa003081e17e04a2ff1`, rebuilt and repackaged the
same day by the rename package once the Desk Dial copy landed in the firmware tree (same sizes,
RAM and heap projections as the phase-2b gatekeeper's build-only compiles, which predate the copy;
the earlier packages are kept as `*.superseded-20260926T1155*`), then built again (byte-identical
images, records with `logSha256` and the 12.4 sizes) and packaged again by the phase-3 gatekeeper
with the stage-9 gate evidence (13:36 UTC; the rename package's packages are kept as
`*.superseded-20260926T1336*`). The knob runs **1.0.0-cc5.3**
(installed and finalized on 2026-09-24: image `nanod-control-center-1.0.0-cc5.3.bin`, SHA-256
`f1cd05a2cd43e0298ff9b10e4bf05ea77590e5d8e31a68623540f752fdd40541`; its verified install image
`../backups/nanod-cc5.3-expected-full.bin`, SHA-256
`86759e5053988e890517b0849498eea1dd02872a8f69e61d01d003d7c88d8781`). The installed companion is
desktop v6, still named NanoD Control Center (exe SHA-256
`2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F`). `manifest.json` is the
installed cc5.3 record. cc5.3 stays installed until an app-only install in step 6 completes and
`finalize_nanod_cc5.py` records the binary that passed the window (step 10).

Desktop v7 is **Desk Dial** (user decision, 2026-09-26; `../design-reference/ui-v2-analysis/rename-desk-dial.md`):
`desktop-dist-v7\DeskDial\DeskDial.exe`, the task `Desk Dial`, the program folder
`%LOCALAPPDATA%\Programs\DeskDial` and the data home `%LOCALAPPDATA%\DeskDial\`. The USB identity
(`239A:8010`, serial `NANO_D`) and every internal identifier stay as they are, so the firmware tooling
and every rollback are unaffected. The flash interlock refuses while **either** companion runs
(`DeskDial.exe` or `NanoDControlCenter.exe`; `nanod_cc5_tooling.require_companion_quit`), and every
block below checks both.

The contracts are `firmware/PRESENTATION_V5.md` (K1; the build ladder is 12.6, the
internal-RAM budget 12.4, the targets 12.2, the device checks 15.4), `ALIVE.md` (K2 r2, 11.9) and
`V5_VOCABULARY.md`; the desktop half is `CONTROL_CENTER_V5.md` (K3) and `DESKTOP_STAGE.md` (K4). Read
[Rollback and abort](#rollback-and-abort) before any hardware step: RECOVERY.md has no cc5.4 section,
so the cc5.4 -> cc5.3 rollback, scripted and manual, is in this file. In this file, cc5.4 means
1.0.0-cc5.4, cc5.3 the installed 1.0.0-cc5.3, and "the binary under test" `$binary` (A, B or C in
the 2026-09-26 window; D or E since A's rollback).

Every command in this file uses absolute paths, so it works from any folder.

## What 1.0.0-cc5.4 changes

- **Presentation 5** (PRESENTATION_V5.md): the v5 frame (cards, Up next, loading list, the liked heart,
  tuning fields `ledPink` and `ledVolFull`), text twins, the offline native sub-line, `kh` hold events,
  `ks` in every `ready`, `hid` on the Home F24 press, and the LCD pipeline changes R2-R5 of 12.1.
- **"Warm · alive" LEDs** (ALIVE.md r2): the knob renders the ring and button LEDs itself at 60 fps
  from the frame's lights; the `alive` capability (`drive` = min(150, `ledMaxBrightness`)); `lim`
  events at the travel ends.
- **Internal RAM** funded by F1 (the WAV sample arrays `const`, 12.4); audio stays disabled as in
  cc5.3 (R-d).
- **Desk Dial copy on the knob** (the rename; K1 16.8 E-r): the offline sub-line `Open Desk Dial` /
  `on your PC` (a no-break space keeps the name on one line; the offline screen keeps no heading,
  K1 8.10) and the boot screen `DESK DIAL` / `IS BOOTING...`. It is in all three builds below and in
  D and E.
- artwork2, the v1 art path, and the presentation-2/4 frames are unchanged: desktop v6 keeps working on
  cc5.4 with presentation-4 frames, and v7 sends presentation-4 frames to a cc5.3 knob (2.2). The window
  still never ends with cc5.4 next to desktop v6: cc5.4's knob copy names Desk Dial, and the rename plan
  (14.2 step 3) never lets the knob name an app that is not installed, so a desktop rollback from cc5.4
  goes with the firmware rollback ([Desktop rollback, v7 -> v6](#desktop-rollback-v7---v6)).

## The build ladder (PRESENTATION_V5 12.6)

The user allows one hardware window, so three binaries of the same release are staged for it. They
differ only in `CC_LCD_DMA`, `CC_LCD_PERIOD_MS` and `CC_ART_ASYNC`, which `{"diag":"?"}` reports
(`lcdDma`, `lcdPeriodMs`, `artAsync`). Stepping down removes one risk class at a time: A -> B removes
the scheduling changes (the 16 ms period and the ArtDecode task), B -> C removes the DMA driver.

| | A (release candidate) | B (middle) | C (fallback) |
|---|---|---|---|
| Build flags (`PLATFORMIO_BUILD_FLAGS`) | none: the source defaults (`lcd_thread.cpp`) | `-DCC_LCD_PERIOD_MS=33 -DCC_ART_ASYNC=0` | `-DCC_LCD_DMA=0 -DCC_LCD_PERIOD_MS=33 -DCC_ART_ASYNC=0` |
| Pipeline (`lcdDma`, `lcdPeriodMs`, `artAsync`) | true, 16, true | true, 33, false | false, 33, false |
| Build folder | `firmware\.pio\build` | `.pio\build-cc5.4-B` | `.pio\build-cc5.4-C` |
| Image | `nanod-control-center-1.0.0-cc5.4.bin` | `nanod-control-center-1.0.0-cc5.4-B.bin` | `nanod-control-center-1.0.0-cc5.4-C.bin` |
| Manifest | `manifest-1.0.0-cc5.4.json` | `manifest-1.0.0-cc5.4-B.json` | `manifest-1.0.0-cc5.4-C.json` |
| Build record, log | `cc5.4-build.json`, `work\nanod-cc5.4-build.log` | `cc5.4-B-build.json`, `nanod-cc5.4-B-build.log` | `cc5.4-C-build.json`, `nanod-cc5.4-C-build.log` |
| Expected image | `backups\nanod-cc5.4-expected-full.bin` | `nanod-cc5.4-B-expected-full.bin` | `nanod-cc5.4-C-expected-full.bin` |
| Preparation, flash, rollback, installation records | `cc5.4-preparation.json`, `cc5.4-flash-checks.json` (logs `cc5.4-<step>.log`), `cc5.4-rollback.json`, `cc5.4-installation.json` | the same with `cc5.4-B-` | the same with `cc5.4-C-` |
| `lcdFpsAnimMin` target (opaque / blended) | 55 / 45 | 28 / 28 | 28 / 28 |
| Build-only heap projection (12.4, H) | 81,748 B (512) | 86,340 B (512) | 98,648 B (0) |

Shared by all three: the pre-install backup pair `backups\nanod-cc5.3-before-cc5.4-full.bin` and
`nanod-cc5.3-before-cc5.4-active-app.bin` and its record `diagnostics\cc5.4-backup.json`, the
before-inventory, and the device and lease check records `diagnostics\cc5.4-device-checks.json` and
`cc5.4-lease-checks.json` (each run supersedes the previous one as `*.superseded-<UTC>.json`;
`check_nanod_cc5.py --binary` records the binary diag reports, and finalize ties both records to the
binary's install by their times). In the 2026-09-26 window every script took `--binary A|B|C` (default
A); the backup has none. Since A's rollback the ladder has two more binaries, D (A + fixes) and E (C +
fixes), and A, B and C are retired: build, package, prepare, install and finalize take `--binary D|E`
(default D) and refuse A, B and C, while rollback and check take all five
([Fix binaries D and E](#fix-binaries-d-and-e)). The records of earlier releases (`cc5-*`, `cc5.3-*`) and
their backup pairs are never written.

## Build (never uploads)

```powershell
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' '<repo>\tools\build_nanod_cc5.py' --binary A
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' '<repo>\tools\build_nanod_cc5.py' --binary B
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' '<repo>\tools\build_nanod_cc5.py' --binary C
```

Each run is `platformio run -d firmware -e nanofoc_d` with
`PLATFORMIO_CORE_DIR=<pio-core>`; B and C add their flags and build
folder through `PLATFORMIO_BUILD_FLAGS` and `PLATFORMIO_BUILD_DIR` (the caller's own values of those
variables are dropped first). There is no upload target, no git and no device access, and
`.pio\libdeps` is only read. A binary is accepted only when the log has `[SUCCESS]`, the image is an
ESP image (magic `0xE9`) below app0 (`0x140000`) containing `1.0.0-cc5.4`, the compiled pipeline is
the binary's (the image holds the R5 task name `ArtDecode` exactly in A; `firmware.elf` links the R3
draw buffer `draw_buf2` exactly in A and B; the 33 ms period is not visible in the image, so the
device check confirms it through `lcdPeriodMs`), the image differs from the other binaries' accepted
images, the 12.4 build-only heap projection is at least 45,056 B, and `firmware.elf`'s symbol table
gives the two sizes 12.4 records for every binary: `sizeof(CCFrame)` and the ALIVE instance (`st_size`
of `hmi_thread.cpp`'s `cc_hmi_frame` and `alive`, what `nm -S` lists; `heapProjection.ccFrameBytes` and
`aliveInstanceBytes`, with the symbols read). The log is never overwritten: an earlier
`work\nanod-cc5.4[-B|-C]-build.log` is first renamed `nanod-cc5.4[-B|-C]-build.superseded-<UTC>.log`
(a packaged manifest pins its SHA-256 in `gates`), and the record carries the new log's SHA-256
(`logSha256`, and `previousLogKeptAs`).

Built on 2026-09-26 (11:54-11:55 UTC, with the Desk Dial copy) and built again by the phase-3
gatekeeper (13:29-13:30 UTC, same tree: byte-identical images) so the records carry `logSha256` and the
12.4 sizes; all accepted:

| | A | B | C |
|---|---|---|---|
| Image | 1,072,032 B (`0x105BA0`) | 1,070,752 B (`0x1056A0`) | 1,056,128 B (`0x101D80`) |
| Headroom in app0 | 238,688 B | 239,968 B | 254,592 B |
| Change from cc5.3 (1,023,648 B) | +48,384 B | +47,104 B | +32,480 B |
| RAM / flash used (PlatformIO) | 218,844 B / 1,071,673 B | 214,252 B / 1,070,389 B | 202,456 B / 1,055,761 B |
| `ramDeltaVsCc53`, `heapMinFreeProjected` | -26,212 B, 81,748 B | -30,804 B, 86,340 B | -42,600 B, 98,648 B |
| `pipelineEvidence` (R5 task in image, R3 buffer in ELF) | true, true | false, true | false, false |
| Build record SHA-256 | `1755ed08cb4e9a90af27999c6305973e49c10061fd21028def36dd9280d10ee4` | `1c0245ebc8fc6143e74858d88ff4a6a4ba9db464a73d50ba66376fb147163615` | `7876d34f0c796ea41fb3098bfd73fe15261257fd37f9cfb545f899819555005d` |
| Build log SHA-256 (`logSha256`) | `b2f572daaf8a00890b4515a72617762fa11d92b13f01ff9cf1ed2499fedc1d60` | `f21acfd88096db65ee23442a8153b2a5db2f1f95456d9e0a40c294e8a8d29b6a` | `450321f6c362801cda7dd8c82e065a052735705c5218a026203414643421068d` |
| Earlier log kept as | `nanod-cc5.4-build.superseded-20260926T132946Z.log` | `nanod-cc5.4-B-build.superseded-20260926T133002Z.log` | `nanod-cc5.4-C-build.superseded-20260926T133018Z.log` |
| `sizeof(CCFrame)`, ALIVE instance (12.4, from `firmware.elf`) | 1,124 B, 11,284 B | 1,124 B, 11,284 B | 1,124 B, 11,284 B |

C's projection counts no DMA descriptors (12.4: H is 512 B in A and B only), so it reads 98,648 B
where the gatekeeper's build-only note, which used H = 512 B for C, read 98,136 B.

The two sizes are read from these builds' `firmware.elf` with the tooling's reader
(`nanod_cc5_tooling.v5_size_record`; `xtensa-esp32s3-elf-gcc-nm -S` lists `0x464` and `0x2c14`) and
recorded in each build record's `heapProjection` next to `logSha256` (review fixes TOOLBC-2 and
TOOLBC-3); `package_nanod_cc5.py` refuses a record without them.

**Any change to the firmware tree after these builds** (for example a gate fix; the Desk Dial copy
is already in them) means: build all three again, package all three again, and update both tables here.
(A, B and C are retired since A's rollback: the fixed tree is built as D and E,
[Fix binaries D and E](#fix-binaries-d-and-e).)
A binary is never packaged from a build record whose image no longer matches its `firmware.bin`, nor
from one whose `logSha256` is not its build log's.

## Package (no device, manifest.json untouched)

```powershell
& '<repo>\app\.venv\Scripts\python.exe' '<repo>\tools\package_nanod_cc5.py' --binary A
& '<repo>\app\.venv\Scripts\python.exe' '<repo>\tools\package_nanod_cc5.py' --binary B
& '<repo>\app\.venv\Scripts\python.exe' '<repo>\tools\package_nanod_cc5.py' --binary C
```

Each run requires the binary's accepted build record whose SHA-256 still matches its `firmware.bin`
and whose `logSha256` still matches its build log, with both 12.4 sizes in `heapProjection`,
re-checks the image (version, size, the binary's R5 marker), and requires `manifest.json` to be the
INSTALLED cc5.3 record. It writes the binary's image, its source archive (the same 133 files for every
binary: `git ls-files --cached --others --exclude-standard`, without `.vscode/`, `compile_commands.json`
and root `*.d`) and its manifest, status `UNFLASHED`, with a `binary` object (name, role, flags,
pipeline, timing targets, heap projection with the 12.4 sizes, pipeline evidence, build record, build
log and its SHA-256, and the ladder's three manifests). The first run also wrote `manifest-cc5.3.json`, a byte copy of `manifest.json`. Packaging
never changes an installed record, and never touches another binary's package.

| Item | A | B | C |
|---|---|---|---|
| Manifest | `manifest-1.0.0-cc5.4.json`, 32,160 B, SHA-256 `2c7a195a3efef3c974f95c81dd49864d97879c959c5a3cdebdb14f8c0b2d32d1` | `manifest-1.0.0-cc5.4-B.json`, 32,377 B, `30efcc0ae5bbfc1cb2f0358889fea0aed47451b8aaa15eff584d28509e647aba` | `manifest-1.0.0-cc5.4-C.json`, 32,398 B, `a74e2934dd02ce97a5bd7729d2f8af90bdc7cf6198a77e998c733261e65538a4` |
| Source archive | `nanod-control-center-1.0.0-cc5.4-source.zip`, 1,616,650 B, `3b20f8e18d0fc97fc2d2b7972c2b8de8b8f8e9a40ef3cb451d2af663c25e27db` | `...-cc5.4-B-source.zip`, 1,616,650 B, `4386d717ca5eeb0ff97ed059befa35fdc13d4d59d0c9fe1cb3a4ed7ee0dbd35b` | `...-cc5.4-C-source.zip`, 1,616,650 B, `4386d717ca5eeb0ff97ed059befa35fdc13d4d59d0c9fe1cb3a4ed7ee0dbd35b` |
| Gates recorded | 12: the nine `cc5.4-stage9-*` files below, `cc5.4-build.json`, `cc5-led-hue-report.json`, `work\nanod-cc5.4-build.log` | 12: the same nine, `cc5.4-B-build.json`, the hue report, `nanod-cc5.4-B-build.log` | 12: the same nine, `cc5.4-C-build.json`, the hue report, `nanod-cc5.4-C-build.log` |
| Sources | 133 files, checkout HEAD `79ca593f...`, none missing; `changedFromPreviousCc5` (from 1.0.0-cc5.3): 9 added (`ALIVE.md`, `ALIVE_R2_DRAFT.md`, `PRESENTATION_V5.md`, `V5_VOCABULARY.md`, `src/cc_alive.cpp`, `src/cc_alive.h`, `src/cc_art_decode.cpp`, `src/cc_art_decode.h`, `src/fonts/cc_font_48t.c`), 30 modified (with `src/screens/ui_bootimg.c`, the boot screen), 0 removed | the same | the same |
| Superseded | nothing changed: `manifest-1.0.0-cc5.3.json` stays `INSTALLED` (finalize supersedes it); earlier cc5 manifests were already `SUPERSEDED` | | |
| `manifest.json` | untouched: the INSTALLED cc5.3 record, SHA-256 `c36cf33eb8e365783db422077a96b1795e06340ba92240f1c5933fd667a69eb0`, byte-identical to `manifest-cc5.3.json` | | |

(The source archives of the same tree differ only by the time stamps written into them; B and C
were packaged within the same second, so theirs are byte-identical. They are 309 B larger than the
rename package's because the contract files in the tree (`PRESENTATION_V5.md`, `ALIVE.md`) gained the
K-errata entries after it packaged; no file that compiles changed, as the identical images show.)

## Gate evidence

Each manifest's `gates` records, at packaging time, the binary's build record and log and every
`diagnostics\cc5.4-stage*`, `cc5-stage*cc5.4*` and `cc5.4-*-report.json` gate record present, plus
`cc5-led-hue-report.json`. The phase-3 gatekeeper's final gate run (2026-09-26, 13:16-13:36 UTC) is
in `diagnostics\` and every manifest above pins it:

- `cc5.4-stage9-firmware-gates.log`: cpp11 gate, `alive_tests.py` (114,800 checks), `light_tests.py`
  (2,174,210 checks), parser, LED wire, media (and `--firmware-syntax`), JPEG and font tests,
  `measure_desk_dial.py`, the LVGL harness (293 cases, 22 timelines, 0 rejected) and `cc54_report.py`
  (39 of 39; `twin_fade` 26 over the cover, 35 in the volume-reveal overlap class, bounds 28 and 36,
  K1 16.8 E-g); `cc5.4-stage9-cc54-regression-checks.json` is the report's JSON.
- `cc5.4-stage9-companion-suite.log`: the whole companion suite through the guard runner (96 modules,
  3,547 tests, 0 failures, 70 skipped: 54 need Tk, 14 are the live tests, 2 wait for the VOC and
  CAROUSEL owners' K-errata text); `cc5.4-stage9-companion-live-hidden.log`: the 9 hidden-window live
  tests (carousel and floating knob, never shown).
- `cc5.4-stage9-stage-selftest.json` / `.log` (the stage, scenes and picker-chrome self-test, headless),
  `cc5.4-stage9-benches.json` (explorer and Up next per-detent, 5 runs; the picker's per-frame work
  with real DWM calls, 14 and 30 windows), `cc5.4-stage9-supervised-dryruns.log` (the supervised
  scripts' headless dry runs) and `cc5.4-stage9-desktop-v7.json` (the Desk Dial bundle's frozen
  headless smoke test and its embedded-module check).

The display was asleep during that run, so the self-test's end-to-end check and the pacing
self-test saw a `sleep` event, and WP7a's probe bench read 1.523 ms against 1.5 ms: see the
gatekeeper's report; rerun them with the display on before the window. `tests\test_cc5_tooling.py` covers
this tooling with fakes only (profiles and the ladder's names, backup locks across binaries, build
and package per binary with the kept logs and the 12.4 sizes, prepare, install, rollback and finalize
per binary, a step-down A -> B through the real backup, prepare, install and rollback scripts on an
in-memory flash where A left a core dump, the dual-name interlock, and this file read as text).

## Fix binaries D and E

Binary A was installed on 2026-09-26 at 18:35 UTC (`cc5.4-flash-checks.json`, `INSTALLED_VERIFIED_RESET`)
and rolled back at 21:12 UTC (`cc5.4-rollback.json`, `ROLLED_BACK_VERIFIED_RESET`, `fullImageMatchesBackup`
true). It was never finalized. The knob runs 1.0.0-cc5.3 with Desk Dial v7, and `manifest.json` is the
cc5.3 record. D and E replace A, B and C for the next window.

### Why A was rolled back

1. **The LCD stayed dark in every mode.** `platformio.ini` sets `TFT_MOSI=4` and `TFT_MISO=-1`. TFT_eSPI
   2.5.43 on the S3 (`TFT_eSPI_ESP32_S3.h` 340-342, the FSPI branch) turns an unset or -1 `TFT_MISO` into
   `TFT_MOSI`, so `tft.initDMA()` (`lcd_thread.cpp`) calls `spi_bus_initialize` with MOSI = MISO = GPIO4.
   IDF routes GPIO4 out to FSPID (signal 103), then the MISO step routes it to FSPIQ_OUT (102), and no
   command or pixel reaches the GC9A01 after that. A and B call `initDMA`; C does not (`CC_LCD_DMA 0`). The
   panel keeps cc5.3's last frame across a reset, so a static image on it proves nothing.
2. **The LEDs flickered.** The ALIVE output stage's temporal dither was on by default. At the 0-3 count
   levels of rest and offline it moved most LEDs by one count every frame. User decision (2026-09-26): the
   dither is off by default, with a minimum brightness floor so the dimmest designed marks stay visible
   (ALIVE.md 9; `ledDither: true` still turns the dither on).
3. **The rollback printed a false line.** After a clean `ROLLED_BACK_VERIFIED_RESET`,
   `rollback_nanod_cc5.py` printed `Rollback did NOT complete; the chip was NOT reset`. It now prints one
   closing line per outcome: restored and reset, records only, the reset retry command, stopped before
   writing, or `did NOT complete` (exit 4 only). A note on changed data regions follows as its own line,
   so an unconfirmed reset with data drift still prints its retry command.

### The fix binaries

D is A's pipeline with the fixes, and E is C's pipeline with the fixes. Each is built with
`CC_BUILD_BINARY` set to its ladder number (A to E are 1 to 5). The image holds the marker
`cc-build-binary:<n>`, and `{"diag":"?"}` reports the binary's letter as `build`. The version string stays
`1.0.0-cc5.4`. The artifact names, the diag `build` field and the marker tell D and E apart from A.

| | D (release candidate: A + fixes) | E (fallback: C + fixes) |
|---|---|---|
| Build flags (`PLATFORMIO_BUILD_FLAGS`) | `-DCC_BUILD_BINARY=4` | `-DCC_LCD_DMA=0 -DCC_LCD_PERIOD_MS=33 -DCC_ART_ASYNC=0 -DCC_BUILD_BINARY=5` |
| Pipeline (`lcdDma`, `lcdPeriodMs`, `artAsync`) | true, 16, true | false, 33, false |
| diag `build`, `lcdMosiSig` | `"D"`, 103 | `"E"`, 103 (Arduino attaches FSPID, as on cc5.3) |
| Build folder | `.pio\build-cc5.4-D` | `.pio\build-cc5.4-E` |
| Image | `nanod-control-center-1.0.0-cc5.4-D.bin` | `nanod-control-center-1.0.0-cc5.4-E.bin` |
| Manifest | `manifest-1.0.0-cc5.4-D.json` | `manifest-1.0.0-cc5.4-E.json` |
| Build record, log | `cc5.4-D-build.json`, `work\nanod-cc5.4-D-build.log` | `cc5.4-E-build.json`, `nanod-cc5.4-E-build.log` |
| Expected image | `backups\nanod-cc5.4-D-expected-full.bin` | `nanod-cc5.4-E-expected-full.bin` |
| Preparation, flash, rollback, installation and look-check records | `cc5.4-D-preparation.json`, `cc5.4-D-flash-checks.json` (logs `cc5.4-D-<step>.log`), `cc5.4-D-rollback.json`, `cc5.4-D-installation.json`, `cc5.4-D-look-checks.json` | the same with `cc5.4-E-` |
| `lcdFpsAnimMin` target (opaque / blended) | 55 / 45 (A's; not reachable before the performance task) | 28 / 28 |
| Heap projection H (12.4) | 512 B | 0 |

D and E share with A, B and C the locked pre-install backup pair (`nanod-cc5.3-before-cc5.4-*`),
`cc5.4-backup.json`, the step-down base record `cc5.4-step-down-base.json`, and the device and lease check
records. Both binaries carry the same fixes:

- **The MOSI re-attach.** Right after `tft.initDMA()`, `cc_lcd_mosi_reattach()` connects GPIO4 back to FSPID
  (`esp_rom_gpio_connect_out_signal(TFT_MOSI, spi_periph_signal[SPI2_HOST].spid_out, false, false)`). It
  is compiled into every DMA build and does nothing where MISO differs from MOSI. `USE_HSPI_PORT` is
  refused because the encoder owns HSPI.
- **Two new diag fields.** `lcdMosiSig` is GPIO4's output signal (103 is good, 102 is A's defect), and
  `build` is the binary's letter.
- **The stack scan moved.** The `perfWindow` stack scan now runs outside the `perfLock` critical section.
  Inside it, it masked the LED RMT interrupt for about 64-128 us once a second.
- **The LED dither is off by default,** with the brightness floor: a target-lit mark that plain rounding
  would darken shows one count on its dominant channel (ALIVE.md 9 step 4; the channel rule was amended on
  review, 12.7, so a breathing mark passes through the floor without a jump).

Nothing else on the render path changes. The LCD frame rate (`lcdFpsAnimMin` 12-16 on A's pipeline) is
the later performance task, so D cannot pass `lcdTimings` yet. For that reason 8b, 8c and finalize are
not part of the look session below.

**Retired binaries.** `build_nanod_cc5.py`, `package_nanod_cc5.py`, `prepare_nanod_cc5_install.py`,
`install_nanod_cc5.py` and `finalize_nanod_cc5.py` take `--binary D|E` (default D). They refuse A, B and
C in argparse (exit 2, nothing written). `rollback_nanod_cc5.py` and `check_nanod_cc5.py` still take every
binary from A to E, so any binary that was ever written can be rolled back and checked. The retired
binaries' records and packages stay as history and are never rewritten.

| Binary | Retired because |
|---|---|
| A | rolled back 2026-09-26: the dark LCD (`initDMA` with MOSI = MISO) and the flickering LEDs; superseded by D |
| B | the same DMA defect as A; never flashed |
| C | superseded by E (C's pipeline with the fixes); never flashed |

### Build and package D and E

```powershell
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' '<repo>\tools\build_nanod_cc5.py' --binary D
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' '<repo>\tools\build_nanod_cc5.py' --binary E
```

Each build must pass every check of [Build](#build-never-uploads), plus two more:

- **The LCD data-line gate** (`lcdMosiGate` in the build record). The effective pins come from
  `platformio.ini` and the binary's flags, with TFT_eSPI's S3 rule applied (MOSI 4, MISO 4, FSPI). A DMA
  build (D) must link `cc_lcd_mosi_reattach`. A's ELF fails this gate.
- **The build marker.** The image must hold exactly `cc-build-binary:4` (D) or `cc-build-binary:5` (E);
  see `pipelineEvidence.buildMarkers`.

```powershell
& '<repo>\app\.venv\Scripts\python.exe' '<repo>\tools\package_nanod_cc5.py' --binary D
& '<repo>\app\.venv\Scripts\python.exe' '<repo>\tools\package_nanod_cc5.py' --binary E
```

Packaging refuses a build record without a passed `lcdMosiGate`. The manifest's `binary` object also
carries `buildNumber`, `diagBuild`, `parent`, `fixes`, `lcdMosiGate`, `active`, `retired` and the manifests
of all five binaries (`ladder`). Packaging leaves `manifest.json`, the A, B and C packages, and every
`diagnostics\cc5.4-*.json` run record as they are.

**Build figures.** From `cc5.4-D-build.json`, `cc5.4-E-build.json` and the two manifests of the rebuild
after the review (built 2026-09-27 00:46 UTC into `.pio\build-cc5.4-D` and `.pio\build-cc5.4-E`, so A's
`.pio\build` and the B and C folders are untouched; packaged 00:47 UTC, both `UNFLASHED`). The first build
(2026-09-26 23:36-23:41 UTC, D `6abf9c28...`, E `b84e148f...`) is kept: its records as
`cc5.4-D-build.superseded-20260927T004623Z.json` / `cc5.4-E-build.superseded-20260927T004650Z.json`, its logs
as `nanod-cc5.4-D-build.superseded-20260927T004604Z.log` / `nanod-cc5.4-E-build.superseded-20260927T004631Z.log`,
and its images, source archives and manifests as `*.superseded-20260927T004731Z.*`.
`test_cc5_tooling.py` fails for a packaged D or E whose image SHA-256, image bytes, manifest SHA-256 and
heap projection are not in this file.

| | D | E |
|---|---|---|
| Image (bytes, SHA-256) | **1,072,608 B** (`0x105DE0`), `02dcb7d10e64043de7d33fbe0879795235740e3d6d87f8fcc364aab2415774db` | **1,056,608 B** (`0x101F60`), `f7aba69bd3fb8d21acc7ed7f9cdf1a9045c35bf48490a33343fe97e3e8e69917` |
| Headroom in app0 (`0x140000`); change from cc5.3 / from the parent | 238,112 B; +48,960 B / +576 B vs A | 254,112 B; +32,960 B / +480 B vs C |
| RAM / flash used; `heapMinFreeProjected` (12.4) | 218,860 B / 1,072,245 B; `ramDeltaVsCc53` -26,196 B, H 512 B, **81,732 B** (required 45,056 B) | 202,456 B / 1,056,249 B; `ramDeltaVsCc53` -42,600 B, H 0, **98,648 B** (required 45,056 B) |
| `lcdMosiGate` (MOSI, effective MISO, re-attach linked, `callOrder` of `LcdThread::run()`); `buildMarkers` | GPIO4, GPIO4 (FSPI, SPI2_HOST), DMA true, re-attach required and linked, `begin, initDMA, reattach, startWrite`: passed; `[4]` | GPIO4, GPIO4 (FSPI), DMA false, re-attach not required, not linked, `begin`: passed; `[5]` |
| `pipelineEvidence` (R5 task in image, R3 buffer in ELF, re-attach in ELF) | true, true, true | false, false, false |
| `sizeof(CCFrame)`, ALIVE instance | 1,124 B, 11,284 B | 1,124 B, 11,284 B |
| Build record SHA-256, `logSha256` | `9ba41829d2f735a4124064343f7cae10d27ceccd7af9ede12e2ed99b7aaa5d00`, `d742defe19315e61328e200c9be44589a06780facd2a8e1bd0756f25aa53dd66` | `398cd1430b57c6643ed20761bbbb81e6d4fca23c1a15d30f8bfdce036daf3bcb`, `e700d5512478d75ebeda167c97e5431b2afa726a9b5aea979c77caea8afb7bda` |
| Manifest (bytes, SHA-256) | `manifest-1.0.0-cc5.4-D.json`, 36,854 B, `e43047e38279b7fb0a81566ddf7bbb098ed8fea603b2680b7d6560c87615e304` | `manifest-1.0.0-cc5.4-E.json`, 37,072 B, `cf30c489d8e878bbd97a2a74eb38518b4f0b805f5b3fb08ad8891dedbebd491c` |
| Source archive (133 files, checkout HEAD `79ca593f...`) | `...-cc5.4-D-source.zip`, 1,631,979 B, `0d1879bc6faf97649ecdf90aa5ead343846771e68303636bb427fc5335962568` | `...-cc5.4-E-source.zip`, 1,631,979 B, `e64fa8e71db762ddb0df3cd736124b4bf064f17932e85215d4d3b6927a2651c5` (the same 133 files byte for byte; only the zip entries' timestamps differ) |
| Gates recorded | 26: the nine stage9, seven stage9b (with its post-package suite log) and six stage9c files, `cc5.4-alive-floor-report.json`, `cc5-led-hue-report.json`, `cc5.4-D-build.json`, `work\nanod-cc5.4-D-build.log` | 26: the same with `cc5.4-E-build.json` and `nanod-cc5.4-E-build.log` |

The rebuild was incremental in the same folders: PlatformIO recompiled the four sources the review
touched or that include a changed header (`cc_alive.cpp`, `control_center.cpp`, `hmi_thread.cpp`,
`lcd_thread.cpp`). Its only warnings are three library-header warnings those units always show (SdFat's
`FS.h` note, STUSB4500's `DEFAULT` redefinition, TFT_eSPI's `TOUCH_CS` note; all in the first, fresh build
too). The first build's fresh folders also showed seven warnings from `src/ui_helpers.c` (the upstream
SquareLine helper, unchanged since checkout HEAD). No file changed by the fixes warns.

**The fix in the linked image** (`cc5.4-stage9c-lcd-mosi-elf.json`, read-only `xtensa-esp32s3-elf-objdump` of
each `firmware.elf`; the same result as the first build's `cc5.4-stage9b-lcd-mosi-elf.json`, and the build gate
itself now reads the call order, `lcdMosiGate.callOrder`): in D, `LcdThread::run()` calls `TFT_eSPI::begin`, `initDMA`, `cc_lcd_mosi_reattach`,
`startWrite` in that order, and `cc_lcd_mosi_reattach` loads byte 50 of `spi_periph_signal` (SPI2_HOST's
`spid_out`, 103 in the ELF) and calls the ROM's `esp_rom_gpio_connect_out_signal` (`0x40001aa0`) with GPIO 4
and no inversion. A's `run()` calls `begin`, `initDMA`, `startWrite` with no re-attach (the dark LCD). E calls
`begin` only (no DMA, no re-attach). D and E each hold one literal `0x60004564` (`GPIO_FUNC4_OUT_SEL_CFG_REG`,
the `lcdMosiSig` read) and exactly their marker, `cc-build-binary:4` and `cc-build-binary:5`; A holds neither.

### Gate evidence for D and E (stage9b)

Before the build, the host gates run again on the fixed tree. Their output is saved under new names,
`diagnostics\cc5.4-stage9b-*.log` and `.json`; the stage9 records stay as they are. The gates are: the
cpp11 gate; `alive_tests`, `light_tests`, the LED wire, parser, media, JPEG and font tests; the LVGL
harness with `cc54_report.py`; and the companion suite through its guard runner.
`tests\tools\alive_floor_report.py` writes `diagnostics\cc5.4-alive-floor-report.json`, the evidence for
the floor rule. The D and E manifests pin all of them, because the release's gate patterns include
`cc5.4-stage*` and `cc5.4-*-report.json`.

The integrator's run on the fixed tree (2026-09-26: firmware-side gates 23:28-23:31 UTC, companion suite
23:31-23:36 UTC, before the D and E builds; every gate passed, no device, no port):

- `cc5.4-stage9b-firmware-gates.log`: cpp11 gate (8/8 C++11 units, 6/6 C units, the firmware source rules),
  `alive_tests.py` (125,391 checks: the F-T floor unit cases, the RC oracle's 786,240 bytes and the BS
  oracle's 423,936 bytes within 1 with 4,609 and 1,501 floored LEDs identical, the twin replay's 4,259
  masks equal to Python's), `light_tests.py` (2,174,210 checks), the parser (875 cases), the LED wire (419
  checks, the floored bytes reach the wire unchanged), media and `--firmware-syntax` (1,581 parity and 289
  direct checks), JPEG and font tests, `measure_desk_dial.py`, the LVGL harness (293 cases, 22 timelines, 0
  rejected) and `cc54_report.py` (39 of 39; its JSON is `cc5.4-stage9b-cc54-regression-checks.json`), both JS
  design oracles regenerated with node and byte-identical to `tests\fixtures\alive_oracle.json` and
  `alive_oracle_bs.json`, and `alive_floor_report.py --check` (the report is current).
- `cc5.4-stage9b-companion-suite.log` / `.json`: every `tests\test_*.py` through the guard runner (97 modules,
  3,650 tests, 0 failures, 0 errors, 68 skipped: 54 need Tk, 14 are the live tests).
- `cc5.4-stage9b-lcd-mosi-elf.json`: the disassembly check of A's, D's and E's `firmware.elf` (the fix in the
  linked image, above).
- `cc5.4-stage9b-desktop-v7-embedded.json`: the Desk Dial v7 bundle's embedded-module check run again. One
  module differs from the tree, `control_center.alive_lights`: the ruling added test-only functions
  (`DEFAULT_DITHER`, `floor_pixel`, `lit_masks`, the floor in `reference_output`) that nothing in the app
  calls; the desktop draws the engine's `e` as before, so the installed v7 is not rebuilt for D and E.
- `cc5.4-stage9b-post-package-suite.log` (written after the first packaging, so the first manifests do not pin
  it; the rebuilt ones do): the whole companion suite again with D and E packaged and this file filled, 3,650
  tests, 0 failures, 68 skipped.

`tests\test_cc5_tooling.py` covers the D and E tooling with fakes:

- the names, flags, pipelines and retirement of the binaries;
- the LCD data-line gate (A's real ELF fails it when present), its call-order check (the re-attach called
  before `initDMA`, after `startWrite`, or an order that cannot be read, all rejected; the real A, D and E ELFs
  read with objdump when present; `lcd_thread.cpp`'s source order), and the build marker;
- building and packaging D and E;
- the step-down from A to D through the real backup, prepare, install and rollback scripts on an
  in-memory flash;
- the look check's GO and NO-GO cases, its evidence and the five by-eye answers;
- the install's next-step line for D and E (the look session, not `check_nanod_cc5.py`);
- the rollback's closing lines.

### Review fixes and the rebuild (stage9c)

A review of the first D / E build (2026-09-26/27) reported nine defects. All nine were verified and fixed;
D and E were rebuilt and repackaged (the first build is kept as `*.superseded-*`, see the figures above).

1. **The LED floor made the dim point of a breath jump (major).** The first reading of the floor's channel rule,
   `round(v/m)`, also lit a channel ≥ `m/2`, which plain rounding leaves dark just above half a count. The
   floored marks sit in the EOTF's linear toe, where AMBER asks for 0.51 green per red, so all 12 offline
   marks went `#020100` → `#010100` → `#010000` → `#010100` (floored, the dimmest point) → `#010000` every
   breath: green flipped on at the dim point and off on both sides (84 events in 10 s offline; 27 LEDs and
   216 events in 20 s asleep at night). Reproduced with both engines. The rule is now **dominant-only**: one
   count on the dominant channel (a tie lights every tied channel), the byte plain rounding shows just above
   0.5, so the offline marks go `#010000` (floored) → `#010000` → `#010100` → `#020100` with no jump. Same
   rule in `cc_alive.cpp`, `alive_lights.py`, both JS oracles and `make_alive_sequences.py`; both oracle
   fixtures and `alive_sequences.json` regenerated (every `e`, view and effect unchanged, only the floored
   bytes and the header's `output.floorChannels`); `cc5.4-alive-floor-report.json` regenerated with a
   `continuity` section (dominant-only 0 / 0 events, the first reading 642 / 642; the first report is kept as
   `cc5.4-alive-floor-report.superseded-20260927T002257Z.json`); new continuity tests on both engines
   (`floorContinuity`, `test_the_floor_is_continuous_through_the_breath`). ALIVE.md 9 step 4 and 12.7 record the
   amendment. The user's ruling (dither off by default, plus a floor that keeps the dimmest marks visible) is
   unchanged. At the dim point an amber mark now shows one count of red (`#010000`), which the look session
   asks about as `hue`.
2. **The MOSI gate only checked that the re-attach links.** `build_nanod_cc5.py` now reads the LCD setup calls
   of `LcdThread::run()` from `firmware.elf` (`tooling.lcd_run_call_order`, a read-only objdump of that one
   function) and requires every `initDMA` to be followed directly by `cc_lcd_mosi_reattach` and then
   `startWrite`; an order that cannot be read fails a build that needs the re-attach. It is recorded as
   `lcdMosiGate.callOrder`, and packaging refuses a record without it. `test_cc5_tooling.py` also checks the
   source order in `lcd_thread.cpp`.
3. **A wrong comment in `lcd_thread.cpp`** said the blocking build (C, E) keeps lv_tft_espi's own TFT_eSPI
   instance. Both pipelines use the one `tft` instance and its one `begin()`; the comment now says so (no code
   change).
4. **The look session could not catch a later dark screen.** D holds the panel's chip select low for its whole
   uptime, so one SPI framing slip would misframe every later command until a reboot. The look now includes
   about 5 minutes of Desk Dial on Home (`screen_host`) and the native dial after quitting Desk Dial
   (`screen_after_quit`), and the user is told to report a later dark or frozen screen, which rolls D back. The
   per-refresh `endWrite` / `startWrite` hardening stays with the performance task.
5. **`device.py`'s `alive_parse` docstring** still said an absent `ledDither` keeps the dither on. Fixed
   (docstring only; Desk Dial v7 behaves the same).
6. **`install_nanod_cc5.py` pointed D and E at `check_nanod_cc5.py`** (the 8b window, which D cannot pass and
   which would archive A's device-check record). For a fix binary it now prints the look session: step 7's port
   block, 8a, then `check_nanod_cc5_look.py --binary <X>`.
7. **The hue question could not pass by design** (a floored amber mark was `#010100`, yellow). With the amended
   floor the dim point is `#010000`; item 10.1 says so, `hue` is asked separately from `leds`, and the step-down
   table has a row for steady LEDs with a wrong hue or an invisible mark.
8. **Item 8 reused step 7 as it stands**, whose screen check proves nothing on the GC9A01 and whose no-go would
   roll back before any `lcdMosiSig` evidence exists; item 8 now runs only step 7's port block. Item 1 says the
   user quits Desk Dial from the tray (asked for in the go-ahead).
9. **Rollback branches did not quit Desk Dial first.** Every branch of item 12 now starts by quitting Desk Dial
   and disabling its task, and ends with [after the rollback](#after-the-rollback) and
   [re-enable the companion](#re-enable-the-companion).

The stage9c run on the review-fixed tree (2026-09-27: firmware-side gates 00:39-00:41 UTC, companion suite 00:41-00:46 UTC, before the rebuild; every gate passed,
no device, no port):

- `cc5.4-stage9c-firmware-gates.log`: cpp11 gate (8/8 C++11 units, 6/6 C units, the firmware source rules),
  `alive_tests.py` (125,396 checks: the amended floor's unit cases, the continuity runs offline and asleep at
  00:00 and 23:00, the RC oracle's 786,240 bytes and the BS oracle's 423,936 bytes within 1 with 4,609 and
  1,501 floored LEDs identical, the twin replay's 4,259 masks equal to Python's and 2,557 floored LEDs with the
  dominant channel at one count in both ports), `light_tests.py` (2,174,210 checks), the parser (875 cases),
  the LED wire (419 checks), media and `--firmware-syntax` (1,581 parity and 289 direct checks), JPEG and font
  tests, `measure_desk_dial.py`, the LVGL harness (293 cases, 22 timelines, 0 rejected) and `cc54_report.py`
  (39 of 39; `cc5.4-stage9c-cc54-regression-checks.json`), both JS design oracles regenerated with node and
  byte-identical to the fixtures, and `alive_floor_report.py --check`.
- `cc5.4-stage9c-companion-suite.log` / `.json`: every `tests\test_*.py` through the guard runner (97 modules,
  3,657 tests, 0 failures, 0 errors, 68 skipped). The old floor rule fails the new tests (checked by mutation in
  both the Python and the C++ engine).
- `cc5.4-stage9c-lcd-mosi-elf.json`: the disassembly check of A's, D's and E's rebuilt `firmware.elf`.
- `cc5.4-stage9c-desktop-v7-embedded.json`: two bundled modules now differ from the tree,
  `control_center.alive_lights` (test-only floor functions, the amended rule) and `control_center.device` (the
  docstring); the desktop draws the engine's `e` as before, so Desk Dial v7 is not rebuilt.
- `cc5.4-stage9c-post-package-suite.log` (written after packaging, so the rebuilt manifests do not pin it): the
  whole companion suite again with D and E repackaged and this file filled, 3,657 tests, 0 failures, 68
  skipped.

### The look session (hardware, D first)

Nothing here runs without the user's go-ahead. One message asks for all of this: quitting Desk Dial and
disabling its task, the ROM bootloader entry, the read-only step-down read, and flash #1 (D). D's
rollback and E's install each need their own go-ahead. The Desk Dial task is never left disabled at the
end. Run every block in one PowerShell window, because `$beforeInventory` and `$binary` carry from block to
block. The D path takes about 20 minutes: the read about 80 s, the install about 40 s, the port check
30 s, the look check about 10 s, and the user's look about 10 minutes (about 5 of them with Desk Dial on
Home). The E path adds about 15 minutes.

1. **Quit Desk Dial and disable its task.** This session skips step 1's v7 smoke test, because v7 is
   already installed. The go-ahead message asks the user to quit Desk Dial from its tray icon (an
   intentional release: Desk Dial hands the knob back; Claude does not end the process). Once the user
   says it is quit, run:

   ```powershell
   . {
     foreach ($task in 'Desk Dial', 'NanoD Control Center') {
       if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
         Disable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
         if ((Get-ScheduledTask -TaskName $task -ErrorAction Stop).State -ne 'Disabled') { throw "NOT RUN: the startup task '$task' is not disabled" }
       }
     }
     if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion (DeskDial or NanoDControlCenter) is still running; quit it from the tray' }
     'GO: the companion is quit and its startup task is disabled for the session'
   }
   ```

2. Run [step 2](#step-2-pre-flash-inventory-cc53-presentation-4). It records the before-inventory: cc5.3,
   presentation 4, ten profiles.
3. Run [step 3](#step-3-enter-the-rom-bootloader-one-1200-bps-touch).
4. Run the step-down base read, the first block of the
   [step-down](#step-down-between-binaries-presentation_v5-126) (`backup_nanod_cc5.py --step-down`,
   read-only, about 80 s). The script allows it because A's write locked the backup. GO needs a verified
   4 MB read, the critical regions identical to the locked backup, and cc5.3 at app0. The record lists
   any `nvs` drift from cc5.3's use since the rollback. This is the first `cc5.4-step-down-base.json`.
5. Set the binary under test:

   ```powershell
   . {
     $binary = 'D'   # the release candidate (A + fixes); after D's rollback, E
     "Binary under test: $binary"
   }
   ```

6. Prepare D from the step-down base with the second block of the
   [step-down](#step-down-between-binaries-presentation_v5-126). GO needs `baseKind` `step-down base` and
   `beforeFile` set to the locked backup.
7. Run [step 6](#step-6-app-only-install-of-the-binary-under-test) (flash #1). Exit 0 or 5: go on. Exit 3
   or 6: cc5.3 was restored; decide with the user. Exit 4: run the scripted
   [firmware rollback](#firmware-rollback-cc54---cc53) now.
8. Run only the port-stability block of [step 7](#step-7-boot-sanity-no-companion) (the application port
   stays for 30 s), then 8a of [step 8](#step-8-checks-of-the-binary-under-test-126-order) (the inventory:
   `1.0.0-cc5.4`, presentation 5, artwork2, alive, ten profiles). Step 7's "watch the knob" and its no-go for
   "no native screen" do not apply here: the GC9A01 keeps cc5.3's last frame across a reset, so a screen seen
   now proves nothing, and the screen is judged in item 10, after the look check has recorded `build` and
   `lcdMosiSig` (the evidence that tells A's 102 from a "103 but still dark" failure). Do not ask the user to
   look yet. An unstable port or a reboot loop is still a no-go: go to item 12, "D fails on the screen".
9. **The look check.** Script: `check_nanod_cc5_look.py`. It takes two read-only diag reads, at least
   1.5 s apart, without claiming the knob. It gates on: `build` equal to `$binary`; the binary's pipeline
   (D true / 16 / true, E false / 33 / false); `lcdMosiSig` 103 in both reads (102 is A's defect); a
   blank coredump (after a step-down, only the dump the step-down base holds); a reset reason that is not
   `panic`, `int_wdt`, `task_wdt`, `wdt` or `brownout`; and no reboot between the reads. It records
   `ledFps`, `ledShowGapMsMax`, `ledMode`, `lcdFps` and `lcdFullRefrs` without gating them, in
   `diagnostics\cc5.4-<X>-look-checks.json`.

   ```powershell
   . {
     if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running; quit it from the tray and disable its startup task again (item 1), then run this block again' }
     if ($binary -notin 'D', 'E') { throw 'NOT RUN: $binary is not set to D or E in this window (item 5)' }
     $app = '<repo>\app\.venv\Scripts\python.exe'
     $global:LASTEXITCODE = -1
     & $app '<repo>\tools\check_nanod_cc5_look.py' --binary $binary
     $lookExit = $LASTEXITCODE
     if ($lookExit -eq 3) { throw 'NOT RUN: a companion owns the knob, or there is no single 239A:8010 NANO_D port (see above); nothing was recorded. Fix that and run this block again' }
     if ($lookExit -ne 0) { throw "NO-GO: the look check of binary $binary failed (the reasons above, diagnostics\cc5.4-$binary-look-checks.json); do not ask the user to look" }
     $look = Get-Content -Raw -LiteralPath "<repo>\app\diagnostics\cc5.4-$binary-look-checks.json" -ErrorAction Stop | ConvertFrom-Json
     if ($look.go -ne $true -or $look.binary -ne $binary -or $look.reads[1].diag.build -ne $binary -or $look.reads[1].diag.lcdMosiSig -ne 103) { throw "NO-GO: cc5.4-$binary-look-checks.json does not record a GO for binary $binary with lcdMosiSig 103" }
     "GO: binary $binary on the knob (build $binary, lcdMosiSig 103, no crash, no reboot); ask the user to look"
   }
   ```

   NO-GO: do not ask the user to look. Go to item 12, "D fails on the screen".
10. **The user looks** (about 10 minutes, answering yes or no in chat; each answer is one key of item 11):
    1. For about 20 s, without touching the knob: the 12 amber offline marks breathe slowly.
       - `leds`: they are steady (no shimmer, sparkle or flip at the dim point of the breath), and every mark
         stays visible at the dim point.
       - `hue`: they read amber while bright. At the dim point each mark shows one count of red (`#010000`,
         amber's dominant channel: one count cannot mix amber; ALIVE.md 9 step 4, 12.7) and warms back to
         amber as the breath rises. That red is expected; a yellow or white dim point, or a mark that changes
         colour at its dim point, is a fail.
    2. `screen`: the native dial is drawn (not dark, not the old image). A few detents move the value, which
       proves the pixels are live.
    3. [Re-enable the companion](#re-enable-the-companion); Desk Dial starts and claims the knob. The Home
       screen shows the cover on the knob. For about 5 minutes the user uses Home as usual: music plays or a
       track or two is skipped so the cover changes, and the volume is turned a few times. The resting ring
       and buttons stay steady with the dim marks visible (part of `leds`), and a volume turn animates.
       - `screen_host`: the knob's screen keeps updating the whole time (the cover and the volume value
         follow; never dark, frozen or garbled).

       Why this long: D holds the panel's chip select low for its whole uptime (one `startWrite()`, never an
       `endWrite()`), so a single SPI framing slip would misframe every later command until a reboot, while
       `lcdMosiSig` and every LCD counter still look healthy. The per-refresh `endWrite` / `startWrite` is
       deferred to the performance task.
    4. The user quits Desk Dial from its tray (an intentional release: Desk Dial hands the knob back).
       - `screen_after_quit`: the native dial comes back and a few detents move its value.

       Then [re-enable the companion](#re-enable-the-companion) again: it starts Desk Dial (the task stays
       enabled).
11. **Record the answers.** This block opens no port, so it runs while Desk Dial runs. Replace each
    `<pass|fail>` with the user's answer and `<what the user said>` with their words. If a placeholder
    is left in, PowerShell does not run the block.

    ```powershell
    . {
      if ($binary -notin 'D', 'E') { throw 'NOT RUN: $binary is not set to D or E in this window (item 5)' }
      $app = '<repo>\app\.venv\Scripts\python.exe'
      $global:LASTEXITCODE = -1
      & $app '<repo>\tools\check_nanod_cc5_look.py' --binary $binary --record-by-eye leds=<pass|fail> hue=<pass|fail> screen=<pass|fail> screen_host=<pass|fail> screen_after_quit=<pass|fail> --note "<what the user said>"
      $eyeExit = $LASTEXITCODE
      if ($eyeExit -eq 2) { throw "NOT RUN: there is no look-check record of binary $binary; run the look check (item 9) first" }
      if ($eyeExit -ne 0) { throw "NO-GO: the user answered fail for binary $binary (recorded in diagnostics\cc5.4-$binary-look-checks.json); decide with the step-down table" }
      "GO: the user's answers for binary $binary are recorded, all pass"
    }
    ```

12. **Decide** with the D and E rows of the [step-down table](#step-down-between-binaries-presentation_v5-126).
    Desk Dial runs again after item 10, so every branch that rolls a binary back starts by quitting Desk Dial
    from the tray and disabling its task again (item 1; step 3 and the bootloader script refuse with NOT RUN
    while a companion runs), and ends with [after the rollback](#after-the-rollback) and
    [re-enable the companion](#re-enable-the-companion).
    - **D passes** (the look check GO and all five answers pass). By default, keep D installed and not
      finalized. A stayed in the same state for about 2.5 h. `manifest.json` stays the cc5.3 record, and
      Desk Dial v7 runs presentation 5 with alive. Tell the user: if D's screen later goes dark or freezes
      (or the LEDs start to flicker), say so, and D is rolled back (to E, or to cc5.3) the same way, because
      a chip-select framing slip lasts until a reboot. The per-refresh `endWrite` / `startWrite` hardening
      (the performance task) should land before D is kept for the long term. The next binary, from the
      performance task, reaches the knob the same way: roll back D, take a step-down base, prepare, install.
      If the user prefers, roll D back now instead: quit Desk Dial and disable its task (item 1), step 3,
      the scripted [firmware rollback](#firmware-rollback-cc54---cc53) with `$binary` still `D`,
      [after the rollback](#after-the-rollback), then [re-enable the companion](#re-enable-the-companion).
    - **D fails on the screen**: `lcdMosiSig` other than 103, or `screen`, `screen_host` or
      `screen_after_quit` fails (dark, frozen or garbled with 103). With the user's go-ahead:
      1. Quit Desk Dial from the tray and disable its task again (item 1), then run step 3.
      2. Run the scripted [firmware rollback](#firmware-rollback-cc54---cc53) with `$binary = 'D'`. Expect
         exit 0; the false `did NOT complete` line is gone. Then [after the rollback](#after-the-rollback),
         with the companion still quit.
      3. Run step 3 again, then a new step-down read (item 4; the earlier record is kept as
         `*.superseded-*`).
      4. Set `$binary = 'E'` (item 5), prepare E from the base (item 6), and run step 6 (flash #2).
      5. Run item 8 (step 7's port block and 8a), the look check for E (item 9: build E, pipeline false / 33 /
         false, `lcdMosiSig` 103), then the same look (items 10 and 11). E raises and drops chip select on
         every flush (cc5.3's pattern), so the chip-select risk of item 10.3 does not apply to it.

      E passes: keep E, not finalized (Desk Dial runs again from item 10). E fails: quit Desk Dial from the
      tray and disable its task (item 1), run step 3, roll E back to cc5.3,
      [after the rollback](#after-the-rollback), [re-enable the companion](#re-enable-the-companion) (v7
      sends presentation-4 frames to cc5.3), and stop.
    - **D's screen is fine and only the LEDs still flicker** (`leds` fails with a shimmer or a flip). E does
      not help here, because it has the same LED code. Decide with the user whether to keep D or roll back to
      cc5.3 (quit Desk Dial and disable its task, step 3, the scripted rollback,
      [after the rollback](#after-the-rollback), [re-enable the companion](#re-enable-the-companion)).
    - **D's screen is fine and the LEDs are steady, but a mark is not visible or the hue is wrong** (`leds`
      fails on visibility, or `hue` fails). E does not help here either (the same LED code). Decide with the
      user whether to keep D or roll back to cc5.3 the same way (quit Desk Dial and disable its task, step 3,
      the scripted rollback, [after the rollback](#after-the-rollback),
      [re-enable the companion](#re-enable-the-companion)), and record what the user saw with `--note`: the
      floor rule (ALIVE.md 9 step 4, 12.7) is what to revisit.
13. **End state.** The Desk Dial task is enabled and running. The new evidence is
    `cc5.4-step-down-base.json`, `cc5.4-D-preparation.json`, `cc5.4-D-flash-checks.json` and
    `cc5.4-D-look-checks.json`, plus E's records and the rollback records after a step-down. No existing
    `diagnostics\cc5.4-*.json` run record is modified. 8b and 8c do not run, so the device and lease
    check records stay A's.

## Hardware window (Stage 10)

This is the runbook of the 2026-09-26 window (binary A, installed and rolled back). A fix binary's
session follows [the look session](#the-look-session-hardware-d-first), which reuses steps 2, 3, 6 and
7, 8a, the step-down blocks and the rollback below.

### Go-ahead first

Nothing below runs without the user's explicit go-ahead, and **each flash needs its own go-ahead**
(12.6): binary A first, and B or C only when the step-down table says so. The request includes the
rollback commands in [Rollback and abort](#rollback-and-abort), and asks the user either to confirm
physical BOOT/RESET access on the enclosure or to accept explicitly that it is unestablished
(RECOVERY.md section 2).

The request states the **12.6 checks** of step 8 for every binary, in their order, stopping at the first
failure: 1 panel image (by eye), 2 entry and input, 3 timing, 4 memory; and the
[step-down table](#step-down-between-binaries-presentation_v5-126). It states the **stress+turn hard
gate** and the **hands-on section** of step 8c (the user at the knob: turn continuously when
`Turn the knob continuously now` appears, holds and pushes on the prompts; the PC beeps because the
block sets the opt-in `NANOD_AUDIBLE_CUES=1`), the **F24 test** (`--hid-check` sends F24 key presses to
Windows; nothing handles them while the companion is quit), and the **unattended soak gate** (20
minutes after `Stop turning`, nobody at the knob). A failed soak or liveness check, a reboot or a
re-enumeration is a failure of that binary, never a rerun. It states that step 4 makes a new full
backup (NVS and the filesystem may have changed since the cc5.3 install), that one backup serves all
three binaries, and that every rollback returns the bootloader, partition table, OTA data, app0 and
app1 to exactly those bytes, while drift in `nvs`, `spiffs` or `coredump` (settings, or the core dump
a failing binary wrote) is reported and kept, never rewritten; so a step-down reads a step-down base
and prepares the next binary from it (the backup itself is never replaced). And it states the desktop part:
v7 is Desk Dial; step 9 installs it, migrates the data home to `%LOCALAPPDATA%\DeskDial\` (the old
home stays as the backup) and replaces the old task and program folder. A NO-GO in step 9 rolls back
both halves, the firmware to cc5.3 first and then the desktop to v6, because cc5.4's offline and boot
screens name Desk Dial and v6 is still NanoD Control Center
([Desktop rollback, v7 -> v6](#desktop-rollback-v7---v6)).

### Ports, interpreters and evidence

Every script discovers its ports itself; none contains a COM number, and each aborts unless exactly
one port matches:

- **Application port:** `239A:8010`, serial `NANO_D`, compared case-insensitively.
- **ROM port:** `303A:1001`, serial `12:34:56:78:9A:BC`.

| Name | Path | Steps |
|---|---|---|
| `$flash`: flash venv, esptool 4.12.0 | `<repo>\tools\nanod-flash-venv\Scripts\python.exe` | 3, 4, 5, 6, abort, and the firmware rollback (`$flashPython`) |
| `$app`: companion venv | `<repo>\app\.venv\Scripts\python.exe` | 2, 7, 8, 10 |

Each block sets the interpreter it runs to the absolute path above and sets
`$global:LASTEXITCODE = -1` before every native command, so a command that did not run can never
pass its exit-code check. Three sets of variables carry evidence from one step to a later one, only
in the PowerShell window that set them: `$beforeInventory` (step 2 to step 5), `$binary` (the binary
under test, below, for steps 6, 8, 10, the firmware rollback and the desktop rollback) and `$demo`, `$stamp`, `$oldHome` and
`$dataHashesBefore` (9b to 9c). A later step refuses to run without them.

**The binary under test.** Set it once before step 6, and again in a step-down:

```powershell
. {
  $binary = 'D'   # the fix binaries: D first, E after D's rollback (A, B and C are retired)
  "Binary under test: $binary"
}
```

Evidence goes to `<repo>\app\diagnostics`
under the names of [the build ladder](#the-build-ladder-presentation_v5-126); the scripts rename older
evidence of the same name and never overwrite it.

Each step block is wrapped in `. { ... }`, so the first `throw` stops the block:

- `GO: ...` (the block's last line): go on to the next step.
- `NOT RUN: ...`: the block stopped before it changed anything. Fix what the message names and run
  the same block again. This is never a reason for a rollback.
- `NO-GO: ...`: stop, and do what that step's **No-go** line says.

### Step 1. Quit the companion, disable its task, smoke-test the v7 (Desk Dial) build

Interpreter: none (PowerShell and the frozen v7 executable
`<repo>\app\desktop-dist-v7\DeskDial\DeskDial.exe`).

Quit the companion from its tray icon (**Quit**). Do not use `Stop-Process` or `taskkill`: Quit
releases the knob cleanly. Then disable whichever startup task exists (`Desk Dial` or
`NanoD Control Center`; before step 9 it is the old one) for the whole window, and run the smoke test:

```powershell
. {
  foreach ($task in 'Desk Dial', 'NanoD Control Center') {
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
      Disable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
      if ((Get-ScheduledTask -TaskName $task -ErrorAction Stop).State -ne 'Disabled') { throw "NOT RUN: the startup task '$task' is not disabled" }
    }
  }
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion (DeskDial or NanoDControlCenter) is still running; quit it from the tray' }
  $v7 = '<repo>\app\desktop-dist-v7\DeskDial\DeskDial.exe'
  if ((Get-Item -LiteralPath $v7 -ErrorAction Stop).VersionInfo.FileDescription -ne 'Desk Dial') { throw 'NO-GO: the v7 executable does not carry the Desk Dial version resource' }
  $smokeJson = Join-Path $env:LOCALAPPDATA 'DeskDial\logs\smoke-test.json'
  $smokeStart = (Get-Date).ToUniversalTime()
  $smoke = Start-Process -FilePath $v7 -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru -Wait
  if ($smoke.ExitCode -ne 0) { throw "NO-GO: the frozen smoke test exited $($smoke.ExitCode)" }
  $report = Get-Content -Raw -LiteralPath $smokeJson -ErrorAction Stop | ConvertFrom-Json
  $written = (Get-Item -LiteralPath $smokeJson).LastWriteTimeUtc
  if ($report.pid -ne $smoke.Id -or $written -lt $smokeStart) { throw 'NO-GO: smoke-test.json is not from this run (pid or time differ)' }
  if ($report.passed -ne $true -or $report.frozen -ne $true -or $report.executable -ne $v7) { throw 'NO-GO: smoke-test.json reports a failed check or another executable' }
  "GO: smoke test pid $($smoke.Id) exit 0, smoke-test.json written $($written.ToString('o'))"
}
```

Go: every existing startup task is disabled, no `DeskDial` or `NanoDControlCenter` process runs, the
v7 executable is Desk Dial, its smoke test exits 0, and `smoke-test.json` carries this run's pid, a
time after the start, `passed` and the v7 path.

No-go: nothing touched the knob. [Re-enable the companion](#re-enable-the-companion) and stop; the
v7 build needs fixing before any hardware step.

### Step 2. Pre-flash inventory (cc5.3, presentation 4)

Interpreter: `$app`. Script:
`<repo>\app\device_inventory.py`
(read-only; never enters host control).

```powershell
. {
  $beforeInventory = $null
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running; quit it from the tray, disable the startup task again (step 1), then run this block again' }
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
  if ($inventory.settings.firmwareVersion -ne '1.0.0-cc5.3' -or $inventory.capabilities.presentation -ne 4 -or @($inventory.profiles.PSObject.Properties).Count -ne 10) { throw 'NO-GO: the knob is not cc5.3 with presentation 4 and ten profiles' }
  $beforeInventory = $name
  "GO: before-inventory $beforeInventory (1.0.0-cc5.3, presentation 4, ten profiles)"
}
```

Go: `backups\control-center-inventory-*.json` reports `1.0.0-cc5.3`, presentation 4 and ten saved
profiles. `$beforeInventory` holds the file name for step 5 (all three binaries use it).

No-go: nothing was sent that changes the knob, and it still runs cc5.3.
[Re-enable the companion](#re-enable-the-companion) and stop. A running companion is a `NOT RUN`.

### Step 3. Enter the ROM bootloader (one 1200-bps touch)

Interpreter: `$flash`. Script:
`<repo>\tools\nanod_enter_bootloader_v2.py` (no esptool, no
write). A step-down runs this step again after the rollback reset the knob into cc5.3.

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running; quit it from the tray, disable the startup task again (step 1), then run this block again' }
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\nanod_enter_bootloader_v2.py'
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: no ROM bootloader port (the message above says why). Do not repeat the touch blindly; see the No-go line' }
  'GO: ROM bootloader present (see the printed port)'
}
```

The script sends one 1200-bps open with DTR false, then closes, and polls for `303A:1001` with the
chip MAC as its serial. It refuses, sending nothing, while either companion runs. Evidence:
`diagnostics\cc5-usb-boot-entry*.json` (one shared, never-overwritten name for every cc5.x window;
finalize treats an entry after the install as a rollback).

Go: exit 0 and `ROM bootloader: COM<n> (serial 12:34:56:78:9A:BC)`. Nothing is written.

No-go: nothing was written. If the message says a companion is running, it is a `NOT RUN`. If the
touch was sent but no ROM port appeared, list ports: when the application port is back, cc5.3 (or, in
a step-down, cc5.3 after its rollback) is running, so [re-enable the companion](#re-enable-the-companion)
and stop; when a MAC-matched ROM port is present, use [Abort before any write](#abort-before-any-write);
when neither appears, see RECOVERY.md section 2.

### Step 4. Full 4 MB backup (one backup for A, B and C)

Interpreter: `$flash`. Script:
`<repo>\tools\backup_nanod_cc5.py` (`flash_id`,
`read_flash 0x0 0x400000`, `verify_flash 0x0` against the read; read-only on the device). The full
backup runs once per window. A step-down reads a step-down base instead (`backup_nanod_cc5.py
--step-down`, in the [step-down](#step-down-between-binaries-presentation_v5-126)), which never
replaces this backup.

```powershell
. {
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\backup_nanod_cc5.py'
  if ($LASTEXITCODE -ne 0) { throw "NO-GO: backup exit $LASTEXITCODE; nothing was written" }
  $backup = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5.4-backup.json' -ErrorAction Stop | ConvertFrom-Json
  if ($backup.passed -ne $true -or $backup.identityVerified -ne $true -or $backup.verifiedAgainstDevice -ne $true -or $backup.bytes -ne 4194304 -or $backup.fromImageAtApp0 -ne $true -or $backup.fromImageSha256 -ne 'f1cd05a2cd43e0298ff9b10e4bf05ea77590e5d8e31a68623540f752fdd40541' -or $backup.file -ne 'nanod-cc5.3-before-cc5.4-full.bin') { throw 'NO-GO: cc5.4-backup.json is not a verified 4 MB backup with cc5.3 at app0' }
  "GO: backups\nanod-cc5.3-before-cc5.4-full.bin, 4,194,304 B, sha256 $($backup.sha256), role $($backup.role)"
}
```

Go: exit 0, and `cc5.4-backup.json` shows the MAC and 4MB identity, 4,194,304 B verified against the
device, the cc5.3 image at app0, and `nanod-cc5.3-before-cc5.4-full.bin` as the backup (role
`pre-cc5.4 backup`: a fresh read, never a copy of the cc5.3 install image).

No-go: nothing was written; use [Abort before any write](#abort-before-any-write). Exit 3 means the
read was kept as a diagnostic read (`backups\nanod-diagnostic-full-<UTC>.bin`,
`cc5.4-backup-diagnostic-read-<UTC>.json`): once any binary's write was attempted the pre-cc5.4 backup
is locked and a read is accepted only when it is byte-identical to it. Inspect with the user.

### Step 5. Prepare A, B and C (host only)

Interpreter: `$flash`. Script:
`<repo>\tools\prepare_nanod_cc5_install.py --before-inventory
<step 2 file> --binary <A|B|C>`, once per binary (the 2026-09-26 window; A, B and C are retired and
refused now, and D and E are prepared from the step-down base, [the look session](#the-look-session-hardware-d-first)).
It reads files only; the knob stays in the ROM
bootloader. A step-down prepares its next binary again, from the step-down base
(`--step-down-base`); each preparation record names the image it was built from (`baseKind`,
`baseFile`) next to the backup every rollback verifies against (`beforeFile`).

```powershell
. {
  if (-not $beforeInventory) { throw 'NOT RUN: $beforeInventory is not set in this window; set it to the file name on the GO line of step 2, then run step 5 again' }
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  foreach ($name in 'A', 'B', 'C') {
    $global:LASTEXITCODE = -1
    & $flash '<repo>\tools\prepare_nanod_cc5_install.py' --before-inventory $beforeInventory --binary $name
    if ($LASTEXITCODE -ne 0) { throw "NO-GO: prepare --binary $name stopped; nothing was written for it" }
  }
  $rollbackHash = (Get-FileHash -Algorithm SHA256 -LiteralPath '<repo>\app\backups\nanod-cc5.3-before-cc5.4-active-app.bin' -ErrorAction Stop).Hash
  foreach ($prepName in 'cc5.4-preparation.json', 'cc5.4-B-preparation.json', 'cc5.4-C-preparation.json') {
    $prep = Get-Content -Raw -LiteralPath "<repo>\app\diagnostics\$prepName" -ErrorAction Stop | ConvertFrom-Json
    if ($prep.activeApp -ne 'app0' -or $prep.applicationOffset -ne 0x10000 -or $prep.applicationSize -ne 0x140000 -or $prep.partitionTableUnchanged -ne $true -or $prep.otaSelectionUnchanged -ne $true) { throw "NO-GO: $prepName does not target app0 at 0x10000/0x140000 with the original partition table and OTA data" }
    if ($prep.rollbackStartsWithFromImage -ne $true -or $prep.fromImageSha256 -ne 'f1cd05a2cd43e0298ff9b10e4bf05ea77590e5d8e31a68623540f752fdd40541' -or $prep.rollbackBytes -ne 1310720 -or $rollbackHash -ne $prep.rollbackSha256) { throw "NO-GO: $prepName does not name the verified cc5.3 app0 as its rollback" }
  }
  "GO: A, B and C prepared; rollback app0 sha256 $rollbackHash"
}
```

Go: for each binary, the partition table and OTA data equal the original backup, OTA selects app0,
app0 holds the cc5.3 image and equals the app0 the cc5.3 install verified, `manifest.json` is the
cc5.3 record, and the one rollback file `backups\nanod-cc5.3-before-cc5.4-active-app.bin` (1,310,720 B)
matches `rollbackSha256`. Each binary has its own expected image (the backup with that binary at
app0 and the rest of its last 4 KB sector erased).

No-go: nothing was written; use [Abort before any write](#abort-before-any-write).

### Step 6. App-only install of the binary under test

Interpreter: `$flash`. Script:
`<repo>\tools\install_nanod_cc5.py --binary $binary`. Binary D
first (A was the 2026-09-26 window's first); E only after D's rollback, each with the user's go-ahead.

```powershell
. {
  if ($binary -notin 'D', 'E') { throw 'NOT RUN: $binary is not set to D or E in this window (the binary under test block); nothing was sent' }
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\install_nanod_cc5.py' --binary $binary
  $installExit = $LASTEXITCODE
  "install_nanod_cc5.py --binary $binary exit $installExit; act on it with the table below"
}
```

`install_nanod_cc5.py` runs every step before the final reset with `--baud 460800 --before
no_reset --after no_reset_stub`:

1. `flash_id`: MAC and 4MB.
2. `verify_flash 0x0` against the image the binary was prepared from: the fresh backup, or in a
   step-down the step-down base (the preparation's `baseFile`; its record and every critical region
   are checked against the locked backup before anything is sent). A binary is only ever written over
   cc5.3 (in a step-down, after the failed binary's verified rollback).
3. `write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000` with the binary's image.
4. `verify_flash 0x0` against the binary's prepared expected image.
5. Only then `read_mac --after hard_reset`.

It never uses `erase_flash`, a filesystem upload, a PlatformIO upload or a full-image write. If step
3 or 4 fails, or anything unexpected happens after the write starts, it does **not** reset: in the
same stub session it writes the cc5.3 active-app backup at `0x10000`, verifies app0, verifies the full
image against the same image as item 2 (the fresh backup or the step-down base), and resets only
after all three pass.

The exit code and the `outcome` in the binary's flash record (`diagnostics\cc5.4-D-flash-checks.json` or
`cc5.4-E-flash-checks.json`; A's, B's and C's were `cc5.4-flash-checks.json`, `cc5.4-B-` and `cc5.4-C-`) agree:

| Exit | Outcome | Meaning | Go / no-go |
|---|---|---|---|
| 0 | `INSTALLED_VERIFIED_RESET` | The binary written, full 4 MB verified, reset confirmed. | GO: step 7. |
| 5 | `INSTALLED_VERIFIED_RESET_UNCONFIRMED` | The binary verified in flash; the reset was not confirmed. | Run only the printed `read_mac --after hard_reset` command, once. Then GO: step 7. At step 10, add `--accept-unconfirmed-reset`. |
| 1 | none | Nothing was sent: wrong environment, an input file's SHA-256 or binary, or not exactly one ROM port. | NO-GO: [Abort before any write](#abort-before-any-write). |
| 2 | `STOPPED_BEFORE_WRITE` | Identity or pre-write verify failed (or a usage error). Nothing written, no reset. | NO-GO: [Abort before any write](#abort-before-any-write). In a step-down (the chip is still in the ROM bootloader) it means the device no longer equals the image the binary was prepared from, for example a step-5 preparation used after a rollback that reported drift in `nvs`, `spiffs` or `coredump`: run the step-down base and prepare blocks of the [step-down](#step-down-between-binaries-presentation_v5-126) and this step once more. A second exit 2: [Abort before any write](#abort-before-any-write) and decide with the user. |
| 3 | `RESTORED_CC5_3_RESET` | The binary failed; cc5.3 restored and verified, then reset. | NO-GO for this binary: cc5.3 runs again. Decide with the user whether to try the same binary once more or [step down](#step-down-between-binaries-presentation_v5-126); else [re-enable the companion](#re-enable-the-companion) and stop. |
| 6 | `RESTORED_CC5_3_VERIFIED_RESET_UNCONFIRMED` | The binary failed; cc5.3 restored and verified; the reset was not confirmed. | Run only the printed command, once. Then as exit 3. |
| 4 | `RESTORE_FAILED_NO_RESET` | The restore did not verify. The chip was **not** reset. | NO-GO: do not reset, unplug or power-cycle. [Firmware rollback](#firmware-rollback-cc54---cc53) (scripted) now. |
| -1 | none | The script did not run (the block's own marker). | NOT RUN: nothing was sent; fix the interpreter path and run step 6 again. |
| Any other | `STARTED` or none | The script was interrupted (for example with Ctrl+C). | NO-GO. Open the binary's flash record: if `writeAttempted` is true, or the file is missing or older than this run, do not reset; [firmware rollback](#firmware-rollback-cc54---cc53) (scripted). Otherwise [Abort before any write](#abort-before-any-write). |

A reset counts as confirmed only when esptool exits 0, names the chip MAC and prints its hard-reset
line.

### Step 7. Boot sanity (no companion)

Interpreter: `$app` (port listing only; no port is opened). Watch the knob: the native screen must
come up and stay for at least 30 s, with no reboot loop. Then:

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running. Quit it from the tray, disable the startup task again (step 1), then run step 7 again. This is not a firmware fault' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $appPort = & $app -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.poll_ports(t.is_app_port, 60, settle=30)[0] or '')"
  if ($LASTEXITCODE -ne 0 -or -not $appPort) { throw 'NO-GO: 239A:8010 NANO_D did not stay enumerated for 30 s' }
  "GO: $appPort stable for 30 s"
}
```

Go: one `239A:8010` (`NANO_D`) port enumerated without interruption for 30 s, the native screen seen
for at least 30 s (with the offline screen's Desk Dial copy once the firmware carries it), and no
companion process.

No-go (unstable port, no native screen or a reboot loop): the binary fails check 2 (entry and input)
at the latest; [roll it back](#firmware-rollback-cc54---cc53) and use the
[step-down table](#step-down-between-binaries-presentation_v5-126). If neither the application port
nor the ROM port appears, write nothing and see RECOVERY.md section 2. A running companion is a
`NOT RUN`, never a reason for a firmware rollback.

### Step 8. Checks of the binary under test (12.6 order)

Interpreter: `$app` for all four. The companion stays quit: each block first refuses with `NOT RUN`
while a `DeskDial` or `NanoDControlCenter` process exists, and the check scripts refuse on their own
before they write any evidence. The four 12.6 checks, stopping at the first failure:

1. **Panel image** (by eye, during 8a and the first minutes of 8b): the Home cover the checks show
   matches the harness render of the same layout (`<repo>\harness\cc54-handoff\contact-sheet-cc54.png`:
   colours, byte order, no offset); no torn or stale bands during a slide, a volume reveal or a
   cover swap; an orientation change (`setRotation`) redraws cleanly. A failure here: stop 8b with
   Ctrl+C (it releases the knob in its `finally` and writes its evidence as failed) and step down.
2. **Entry and input** (8b): `ready` arrives (`enterMsMax` <= 250 is reported, above it investigate),
   turns and presses reach the host (`stressTurn`, `turningDetected`), a hold produces one `kh`
   (`holdEvents`, `holdDeferred`, `readyKeyState`), no `error` replies (`noErrorReplies`), no reboot
   or re-enumeration (`noRebootOrReenumeration`) and live tasks (`taskLiveness`).
3. **Timing** (8b, gate `lcdTimings`): `lcdFpsAnimMin` >= the binary's targets (A and D 55 / 45; B, C
   and E 28 / 28) and no late refresh outside cover arrivals (`lcdLateRefrs`); `lcdMaxGapMs` recorded. On
   A and D only, film the panel scan (RF3 8.2 step 3) and keep the clip with the evidence.
4. **Memory** (8b, gate `diagMargins`): `heapMinFree` >= 40,960 B, `lvglMinFree` >= 30 KB,
   `stackArtDec` >= 1,024 B (A and D), the other stacks as today.

**8a. Inventory.** Script:
`<repo>\app\device_inventory.py`.

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running; quit it from the tray, disable the startup task again (step 1), then run this block again' }
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
  if ($after.settings.firmwareVersion -ne '1.0.0-cc5.4' -or $after.capabilities.presentation -ne 5 -or $after.capabilities.artwork2.version -ne 1 -or $after.capabilities.alive.version -ne 1 -or @($after.profiles.PSObject.Properties).Count -ne 10) { throw 'NO-GO: the knob is not cc5.4 with presentation 5, artwork2, alive and ten profiles' }
  $afterName = $name
  "GO: $afterName (1.0.0-cc5.4, presentation 5, artwork2, alive, ten profiles)"
}
```

**8b. Device checks.** Script:
`<repo>\tools\check_nanod_cc5.py --binary $binary`. Leave the
knob alone until the script prints `Turn the knob continuously now for 60 s` (a beep); turn it back and
forth until `Stop turning` appears. Then stay for the hands-on section (holds, the End stop pushes and
the F24 presses, each prompted on the knob's title and by a beep). After it the unattended soak runs
for 20 minutes: you may leave the knob. The block takes about 35 minutes.

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running; quit it from the tray, disable the startup task again (step 1), then run this block again' }
  if ($binary -notin 'A', 'B', 'C', 'D', 'E') { throw 'NOT RUN: $binary is not set in this window (the binary under test block)' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $env:NANOD_AUDIBLE_CUES = '1'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\check_nanod_cc5.py' --turn-seconds 60 --soak-minutes 20 --hid-check --binary $binary
  Remove-Item Env:NANOD_AUDIBLE_CUES -ErrorAction SilentlyContinue
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: device checks failed; see failures and gates in diagnostics\cc5.4-device-checks.json and map them to the 12.6 checks above. If the output above says a companion is running, it is NOT RUN instead (no evidence was written): quit it, disable the startup task again and run 8b again. If the only failures are turning not detected or a touched untouched pass, run 8b again and turn only when prompted. A stalled task, LED transmit failure, forced release, failed soak or failed artwork2 check is never a rerun' }
  "GO: diagnostics\cc5.4-device-checks.json passed on binary $binary"
}
```

The run first checks that `{"diag":"?"}` reports the binary under test (`lcdDma`, `lcdPeriodMs`,
`artAsync`, and on D and E `build`, with `lcdMosiSig` 103): installing one binary and checking another
fails here. Its `gates` object must be all
true for step 10: `stressUntouched`, `stressTurn`, `turningDetected`, `noRebootOrReenumeration`,
`rebootFieldsReported`, `coredumpBlank`, `rxQueueInternal`, `diagMargins`, `taskLiveness`,
`unattendedSoak`, `artwork2Capability`, `bridgeArtwork2`, `v1ArtCompatible`, `mediaRoundTrip`,
`mediaPrefetch`, `mediaPinning`, `mediaErrorStrings`, `unpacedTransferTiming`, `jpegDecode`,
`aliveCapability`, `ledFrameRate`, `ledRenderTime`, `limitEvents`, `limitPerPush`, `noErrorReplies`,
`presentation5Capability`, `readyKeyState`, `holdEvents`, `holdDeferred`, `hidIconGate` and
`lcdTimings`.

**8c. Lease checks.** Script:
`<repo>\tools\check_nanod_cc5_lease.py`. Turn the knob during
the native observation.

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running; quit it from the tray, disable the startup task again (step 1), then run this block again' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\check_nanod_cc5_lease.py' --observe-native-seconds 10
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: lease checks failed; see failures in diagnostics\cc5.4-lease-checks.json. If the output above says a companion is running, it is NOT RUN instead (no evidence was written): quit it, disable the startup task again and run 8c again' }
  'GO: diagnostics\cc5.4-lease-checks.json passed'
}
```

Its `artwork2` object (`mediaOnlyDoesNotRenew`, `framesDuringMediaTransfers`) must be all true for
step 10. After a host-lost expiry the knob shows its offline screen: confirm by eye the Desk Dial
copy (no heading; `Waiting for PC`, then the sub-line `Open Desk Dial` / `on your PC` on two lines, the
name never split, K1 16.8 E-r).

**8d. Hands-on acceptance (the binary that passed 8a-8c).** Script:
`<repo>\tools\nanod_alive_tour.py` (interactive: it claims the
knob over raw serial; `help` lists the screens, moments and tuning commands; `quit` restores the
defaults and writes `diagnostics\cc5.4-led-tour*.json`).

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: a companion is running; quit it from the tray, disable the startup task again (step 1), then run this block again' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\nanod_alive_tour.py'
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: the LED tour stopped with an error; see its output. It changes nothing on the knob that a reboot does not restore' }
  'GO: LED tour recorded'
}
```

Record by eye with the user (the list is also in the device-check evidence, `byEye`): every moment of
the tour, PINK among the `ledPink` candidates and the volume body 0.62 vs 1.0 (`ledVolFull`); paused
Play green, Head shake legibility, the wake feel; Seek digits without jitter and the End stop feel at
0:00 and `T_end`; twins legible on light covers and no darkening of text during a slide; no visible
darkening of text during both volume reveals (R-b: the `twin_fade` bound 28; R-g: where the volume
caption crosses the fading home title, the overlap class bounded at 36, 35 measured); headings fit on
glass; the offline native line `Knob controls still work` on one line (R-c); the Windows art fade;
Up next spin without decode stalls (A and D: R5) and never a superseded cover. No by-ear check: audio stays
disabled (R-d).

Go: 8a-8c exit 0 and check 1 passed by eye: the binary passes the four 12.6 checks. Go on with 8d,
then step 9 and step 10 with this `$binary`.

No-go: the binary fails. Keep its evidence (`diagnostics\cc5.4-device-checks.json` is superseded, not
overwritten, by the next binary's run; its `rebootWatch.postDropDiag` holds a reset reason and the
breadcrumbs; a `task_wdt` reset means a task stalled for 10 s: keep the core dump, never erase it).
Do not finalize, and go to the [step-down table](#step-down-between-binaries-presentation_v5-126). A
running companion is a `NOT RUN`, never a reason for a firmware rollback.

### Step-down between binaries (PRESENTATION_V5 12.6)

| Binary under test | Result of the 12.6 checks (stop at the first failure) | Next |
|---|---|---|
| A | passes 1-4 | **ship A**: 8d, then step 9 and step 10 with `$binary = 'A'` |
| A | fails check 1 (panel image) | roll back A; set `$binary = 'C'` (B carries the same DMA driver) |
| A | fails only checks 2-4 | roll back A; set `$binary = 'B'` |
| B | passes 1-4 | **ship B** |
| B | fails any check | roll back B; set `$binary = 'C'` |
| C | passes 1-4 | **ship C** |
| C | fails any check | roll back C to cc5.3 and stop: that also drops ALIVE and presentation 5, and the v7 host sends the presentation-4 downgrade (2.2). Do not run step 9 or 10; [re-enable the companion](#re-enable-the-companion) (desktop v6 still installed) and decide with the user |
| D | passes the look session (look check GO, all five by-eye answers pass) | **keep D** installed, not finalized (the performance task comes next; 8b, 8c and step 10 are not run); if the screen later goes dark or freezes, roll D back |
| D | fails the screen (`lcdMosiSig` not 103, or `screen`, `screen_host` or `screen_after_quit` fails: dark, frozen or garbled with 103) | roll back D; set `$binary = 'E'` (a new step-down base read, then prepare, install and the look session) |
| D | screen passes, only the LEDs still flicker (`leds`) | decide with the user: keep D, or roll back to cc5.3 (E has the same LED code) |
| D | screen passes, LEDs steady, but a mark is not visible or the hue is wrong (`leds` on visibility, or `hue`) | decide with the user: keep D, or roll back to cc5.3 (E has the same LED code) |
| E | passes the look session | **keep E** installed, not finalized |
| E | fails the look session | roll back E to cc5.3 and stop; [re-enable the companion](#re-enable-the-companion) (Desk Dial v7 sends presentation-4 frames to cc5.3) |

Checks 2-4 are read from 8b's evidence as listed at the top of step 8. A failure of any other gate
(the artwork2 media gates, the alive LED rates, the soak) is not one of the four 12.6 checks: a
step-down changes only the LCD pipeline, so stop and decide with the user whether that failure could
come from the pipeline (step down) or not (roll back to cc5.3).

**The step-down**, each flash with the user's go-ahead:

1. The failed binary is verified in app0 (install exit 0 or 5): roll it back with the
   [scripted rollback](#firmware-rollback-cc54---cc53) (`$binary` still names it). Exit 0: cc5.3 runs,
   its bootloader, partition table, OTA data, app0 and app1 verified against the pre-cc5.4 backup, and
   `manifest.json` is the cc5.3 record. A failing binary often leaves drift in `nvs`, `spiffs` or
   `coredump` (a panic or a `task_wdt` reset writes its core dump): the rollback reports it as
   `dataRegionsChangedSinceBackup` and keeps it. Never rewrite or clear it.
2. Set `$binary` to the next binary with the [binary under test](#ports-interpreters-and-evidence) block.
3. Run step 3 (enter the ROM bootloader).
4. Read the step-down base (block below; read-only on the device). The full backup of step 4 is not
   repeated: the locked pre-cc5.4 backup stays the backup of every binary and of every rollback.
5. Prepare the next binary from the step-down base (block below; host only).
6. Run step 6 (install `--binary $binary`): it verifies the device against the step-down base before
   it writes, and a failed write restores cc5.3 and verifies the full 4 MB against the same base.
7. Run steps 7 and 8 for the new binary.

**Step-down base.** Interpreter: `$flash`. Script:
`<repo>\tools\backup_nanod_cc5.py --step-down` (`flash_id`,
`read_flash 0x0 0x400000`, `verify_flash 0x0` against the read). It refuses, reading nothing, unless a
binary's write was attempted (the pre-cc5.4 backup is locked) and `cc5.4-backup.json` still records that
backup. The read becomes the step-down base only when every critical region (bootloader, partition
table, OTA data, app0, app1 and the gaps between partitions) is byte-identical to the locked
`backups\nanod-cc5.3-before-cc5.4-full.bin` and app0 holds cc5.3. It is kept as
`backups\nanod-cc5.3-step-down-base-<UTC>.bin` and recorded in `diagnostics\cc5.4-step-down-base.json`
(an older record is kept as `*.superseded-*`); the locked backup and `cc5.4-backup.json` are never
replaced or rewritten.

```powershell
. {
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\backup_nanod_cc5.py' --step-down
  if ($LASTEXITCODE -ne 0) { throw "NO-GO: step-down read exit $LASTEXITCODE; nothing was written" }
  $stepDown = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5.4-step-down-base.json' -ErrorAction Stop | ConvertFrom-Json
  if ($stepDown.passed -ne $true -or $stepDown.role -ne 'step-down base' -or $stepDown.identityVerified -ne $true -or $stepDown.verifiedAgainstDevice -ne $true -or $stepDown.bytes -ne 4194304 -or $stepDown.criticalRegionsIdenticalToLockedBackup -ne $true -or $stepDown.fromImageAtApp0 -ne $true -or $stepDown.lockedBackupFile -ne 'nanod-cc5.3-before-cc5.4-full.bin') { throw 'NO-GO: cc5.4-step-down-base.json is not a verified 4 MB read with the critical regions of the locked backup and cc5.3 at app0' }
  "GO: step-down base backups\$($stepDown.file), sha256 $($stepDown.sha256); data regions changed since the backup: $(@($stepDown.dataRegionsChangedSinceBackup) -join ', ')"
}
```

Go: exit 0, and the record shows a verified 4 MB read, the critical regions identical to the locked
backup, cc5.3 at app0, and the data regions that changed (for example `coredump`).

No-go: nothing was written. Exit 1: nothing was accepted (refused before reading because the backup is
not locked or `cc5.4-backup.json` does not record it, or the identity, read or verify failed; then see
`cc5.4-backup-failed-<UTC>.json`): fix the cause and run the block again, or decide with the user. Exit
3: the read was kept as a diagnostic read
(`backups\nanod-diagnostic-full-<UTC>.bin`, `cc5.4-backup-diagnostic-read-<UTC>.json`, whose
`notConfirmedBecause` names the critical regions that differ): stop, use
[Abort before any write](#abort-before-any-write) and decide with the user.

**Prepare the next binary from the step-down base.** Interpreter: `$flash`. Script:
`<repo>\tools\prepare_nanod_cc5_install.py --before-inventory
<step 2 file> --binary $binary --step-down-base` (host files only). It checks the step-down record, the
base's SHA-256 and every critical region against the locked backup again, runs every step-5 check on
the base, writes the binary's expected image from the base (the earlier one is kept as
`*.superseded-*`) and records `baseKind` `step-down base`, `baseFile` and `baseSha256`; `beforeFile` and
the rollback app0 stay the locked backup's.

```powershell
. {
  if (-not $beforeInventory) { throw 'NOT RUN: $beforeInventory is not set in this window; set it to the file name on the GO line of step 2, then run this block again' }
  if ($binary -notin 'D', 'E') { throw 'NOT RUN: $binary is not set to D or E in this window (the binary under test block); nothing was written' }
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\prepare_nanod_cc5_install.py' --before-inventory $beforeInventory --binary $binary --step-down-base
  if ($LASTEXITCODE -ne 0) { throw "NO-GO: prepare --binary $binary --step-down-base stopped; nothing was written for it" }
  $diagnostics = '<repo>\app\diagnostics'
  $prepName = if ($binary -eq 'A') { 'cc5.4-preparation.json' } else { "cc5.4-$binary-preparation.json" }
  $prep = Get-Content -Raw -LiteralPath "$diagnostics\$prepName" -ErrorAction Stop | ConvertFrom-Json
  $stepDown = Get-Content -Raw -LiteralPath "$diagnostics\cc5.4-step-down-base.json" -ErrorAction Stop | ConvertFrom-Json
  if ($prep.binary -ne $binary -or $prep.baseKind -ne 'step-down base' -or $prep.baseFile -ne $stepDown.file -or $prep.baseSha256 -ne $stepDown.sha256 -or $prep.beforeFile -ne 'nanod-cc5.3-before-cc5.4-full.bin' -or $prep.activeApp -ne 'app0') { throw "NO-GO: $prepName is not binary $binary prepared from the step-down base" }
  "GO: binary $binary prepared from $($prep.baseFile); expected image sha256 $($prep.expectedSha256)"
}
```

Go: exit 0 and the preparation names the step-down base. Then step 6.

No-go: nothing was written; use [Abort before any write](#abort-before-any-write).

A step-down never refreshes the locked backup (`backup_nanod_cc5.py` without `--step-down` keeps any
read that differs from it as a diagnostic read, exit 3). A binary installed from a step-down base is
rolled back like any other: against the same locked backup, reporting the drift again.

The next binary boots with the failed binary's core dump still in `coredump` (it is evidence: the
step-down base file holds it byte for byte). Its 8b run (`check_nanod_cc5.py --binary $binary`)
accepts exactly that dump in the `coredumpBlank` gate: a present dump of the size the step-down base's
partition names, with a reset reason that is not `panic`, `int_wdt`, `task_wdt`, `wdt` or `brownout`,
recorded as `coredumpInherited` in `cc5.4-device-checks.json`. Any other dump, or a crash reset reason,
fails the gate as before (TB-D9).

`finalize_nanod_cc5.py --binary <shipped>` accepts the earlier binaries' rollbacks, because they
happened before the shipped binary's install, and refuses any rollback or ROM bootloader entry after
it.

### Step 9. Install the desktop app (v7, Desk Dial)

Interpreter: PowerShell. Script:
`<repo>\app\Install-Desktop.ps1`. Run 9a,
9b and 9c in the same window; 9d sets its own paths. The installer (rename plan, sections 4 and 12)
installs to `Programs\DeskDial`, copies the whole old home `%LOCALAPPDATA%\NanoDControlCenter\`
(`data\`, `logs\`, `backups\`, `queue-recovery.bin`, `shuffle-restore.bin`) to `%LOCALAPPDATA%\DeskDial\`
once (`DeskDial\migration.json`), hash verified, keeping any file already there and the old home as the
backup; the per-user steps run as a one-shot task outside AppData virtualization (`Install-UserData.ps1`),
and the local seeds apply only after the migration, where a file is missing. It registers the `Desk Dial` task and `Desk Dial.lnk`, and,
after the new install verifies, unregisters `NanoD Control Center`, removes its shortcut and moves the
old program folder to `backups\`. Only file names, sizes and hashes of user data are ever recorded,
never contents.

**9a. Dry run review.** Read the plan the installer would carry out; nothing is changed:

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: quit the companion from the tray first' }
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v7 -Mirror -DryRun
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: the dry run failed; nothing was installed' }
  'GO: read diagnostics\desktop-install-plan.json with the user (identity DeskDial; task \Desk Dial to register and \NanoD Control Center to unregister; the old program folder to move to backups\; the migration list, names and sizes only; no data file written from local\ before the migration)'
}
```

**9b. Keep the installed program and records; hash the user data.**

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: quit the companion from the tray first' }
  $demo = '<repo>\app'
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $oldHome = Join-Path $env:LOCALAPPDATA 'NanoDControlCenter'
  $dataHashesBefore = $null
  $programs = Join-Path $env:LOCALAPPDATA 'Programs\NanoDControlCenter'
  $programBackup = "$demo\backups\desktop-program-before-cc5.4-$stamp"
  Copy-Item -LiteralPath $programs -Destination $programBackup -Recurse -ErrorAction Stop
  if (@(Get-ChildItem -LiteralPath $programBackup -File -Recurse).Count -ne @(Get-ChildItem -LiteralPath $programs -File -Recurse).Count) { throw 'NO-GO: the program folder copy is incomplete' }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath "$programBackup\NanoDControlCenter.exe" -ErrorAction Stop).Hash -ne '2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F') { throw 'NO-GO: the installed exe is not the recorded v6 companion' }
  foreach ($name in 'desktop-installation.json', 'desktop-startup-task.xml', 'desktop-user-data.json', 'native-desktop-verification.json') {
    $old = "$demo\diagnostics\$name"
    $keep = "$demo\diagnostics\" + [IO.Path]::GetFileNameWithoutExtension($name) + "-before-cc5.4-$stamp" + [IO.Path]::GetExtension($name)
    if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $keep -ErrorAction Stop }
  }
  $present = @('data\credentials.bin', 'data\settings.json', 'queue-recovery.bin', 'shuffle-restore.bin' | Where-Object { Test-Path -LiteralPath (Join-Path $oldHome $_) })
  if ($present -notcontains 'data\credentials.bin' -or $present -notcontains 'data\settings.json') { throw 'NO-GO: the old home has no credentials.bin or settings.json; decide with the user before installing' }
  $hashes = @($present | ForEach-Object { [pscustomobject]@{ file = $_; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $oldHome $_) -ErrorAction Stop).Hash } })
  $hashes | ConvertTo-Json | Out-File -NoClobber -Encoding utf8 -LiteralPath "$demo\diagnostics\cc5.4-desktop-data-sha256-before-$stamp.json" -ErrorAction Stop
  $dataHashesBefore = $hashes
  "GO: program folder kept as $programBackup; $($hashes.Count) user data hashes recorded"
}
```

**9c. Forward install with `-Mirror`.**

```powershell
. {
  if (-not ($demo -and $oldHome -and $stamp -and $dataHashesBefore)) { throw 'NOT RUN: run 9b in this window first; nothing was installed' }
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v7 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: Install-Desktop.ps1 failed; use the desktop rollback' }
  $newHome = Join-Path $env:LOCALAPPDATA 'DeskDial'
  $oldAfter = @($dataHashesBefore | ForEach-Object { [pscustomobject]@{ file = $_.file; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $oldHome $_.file) -ErrorAction Stop).Hash } })
  $newAfter = @($dataHashesBefore | ForEach-Object { [pscustomobject]@{ file = $_.file; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $newHome $_.file) -ErrorAction Stop).Hash } })
  @{ oldHome = $oldAfter; newHome = $newAfter } | ConvertTo-Json -Depth 3 | Out-File -NoClobber -Encoding utf8 -LiteralPath "$demo\diagnostics\cc5.4-desktop-data-sha256-after-$stamp.json" -ErrorAction Stop
  if (Compare-Object $dataHashesBefore $oldAfter -Property file, sha256) { throw 'NO-GO: the old home changed during the install; it is the backup and must stay as it was' }
  if (Compare-Object $dataHashesBefore $newAfter -Property file, sha256) { throw 'NO-GO: the migrated files in the Desk Dial home differ from the old home' }
  $installed = Get-Content -Raw -LiteralPath "$demo\diagnostics\desktop-installation.json" -ErrorAction Stop | ConvertFrom-Json
  $bundleHash = (Get-FileHash -Algorithm SHA256 -LiteralPath "$demo\desktop-dist-v7\DeskDial\DeskDial.exe" -ErrorAction Stop).Hash
  if ($installed.sha256 -ne $bundleHash) { throw 'NO-GO: the installed exe is not the v7 bundle' }
  if (-not (Get-ScheduledTask -TaskName 'Desk Dial' -ErrorAction SilentlyContinue)) { throw 'NO-GO: the Desk Dial task was not registered' }
  if (Get-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction SilentlyContinue) { throw 'NO-GO: the old NanoD Control Center task is still registered; two companions would start at sign-in' }
  if (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\NanoDControlCenter\NanoDControlCenter.exe')) { throw 'NO-GO: the old program folder is still in place' }
  "GO: v7 (Desk Dial) installed ($bundleHash); $($newAfter.Count) user data files migrated with equal hashes; the old home unchanged"
}
```

No-go (9a-9c): the knob runs cc5.4, which names Desk Dial, so the window ends with both halves rolled
back: the [firmware rollback](#firmware-rollback-cc54---cc53) first, then the
[desktop rollback](#desktop-rollback-v7---v6) (the order and the reason are there). A change in the old
home also needs the user: the installer only reads it.

**9d. Start the Desk Dial task, then verify.** This block sets its own paths, so it also runs in a
new window after 9c.

```powershell
. {
  $demo = '<repo>\app'
  $dataDir = Join-Path $env:LOCALAPPDATA 'DeskDial\data'
  Enable-ScheduledTask -TaskName 'Desk Dial' -ErrorAction Stop | Out-Null
  $taskStart = Get-Date
  Start-ScheduledTask -TaskName 'Desk Dial' -ErrorAction Stop
  $statusFile = Join-Path $env:LOCALAPPDATA 'DeskDial\logs\status.json'
  do {   # up to 90 s for the knob to connect; status.json is rewritten while the app runs
    Start-Sleep -Seconds 3
    try { $status = Get-Content -Raw -LiteralPath $statusFile -ErrorAction Stop | ConvertFrom-Json } catch { $status = $null }
    $fresh = $status -and (Get-Item -LiteralPath $statusFile).LastWriteTime -ge $taskStart
  } until (($fresh -and $status.ready -eq $true) -or (Get-Date) -gt $taskStart.AddSeconds(90))
  $exe = Join-Path $env:LOCALAPPDATA 'Programs\DeskDial\DeskDial.exe'
  $processes = @(Get-Process -Name DeskDial -ErrorAction SilentlyContinue)
  if ($processes.Count -ne 1 -or $processes[0].Path -ne $exe) { throw "NO-GO: expected exactly one DeskDial process from $exe" }
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NO-GO: an old NanoDControlCenter process runs next to Desk Dial' }
  if (-not $fresh -or $status.pid -ne $processes[0].Id) { throw 'NO-GO: status.json is not from this process' }
  if ($status.ready -ne $true -or $status.connected -ne $true -or $status.firmwarePresentation -ne 5 -or $status.artwork2 -ne $true -or $status.dataDir -ne $dataDir) { throw 'NO-GO: status.json is not ready on presentation 5 with artwork2 and the Desk Dial data folder' }
  $readyLine = Select-String -LiteralPath (Join-Path $env:LOCALAPPDATA 'DeskDial\logs\app.log') -Pattern 'Device ready' | Select-Object -Last 1
  if (-not $readyLine -or [datetime]::ParseExact($readyLine.Line.Substring(0, 19), 'yyyy-MM-dd HH:mm:ss', $null) -lt $taskStart.AddSeconds(-1)) { throw 'NO-GO: app.log has no "Device ready" line since the start' }
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\diagnostics\Verify-NativeDesktop.ps1'
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: Verify-NativeDesktop.ps1 failed' }
  $native = Get-Content -Raw -LiteralPath "$demo\diagnostics\native-desktop-verification.json" -ErrorAction Stop | ConvertFrom-Json
  if ($native.diagnosticExitCode -ne 0 -or $native.music.passed -ne $true) { throw 'NO-GO: the read-only Apple Music check failed' }
  "GO: pid $($processes[0].Id), $($status.deviceStatus)"
}
```

Go: one `DeskDial` process from the install path and none of the old name, a `status.json` written by
that process after the start (ready, connected, presentation 5, `artwork2` true, the Desk Dial data
folder), a `Device ready` line in `app.log` since the start, and `Verify-NativeDesktop.ps1` passing
its read-only Apple Music check (it reads the installed companion's paths: Desk Dial after step 9). By eye:
the tray tooltip reads `Desk Dial · Knob connected`, Settings shows the same speakers and Apple Music
connection as before, and the floating knob's first frame after a summon (R-i).

No-go (9d): quit the companion from its tray icon, then roll back both halves as for 9a-9c: the
[firmware rollback](#firmware-rollback-cc54---cc53) first, then the [desktop rollback](#desktop-rollback-v7---v6).

### Step 10. Finalize (records only)

Interpreter: `$app`. Script:
`<repo>\tools\finalize_nanod_cc5.py --binary $binary`. It
touches no device, network or desktop, and checks everything before it writes anything.

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

Then finalize. Replace `<suite-tests>` with that count; left in place, it stops PowerShell from
running the block at all. The light count, 2174210, is the `PASS: 2174210 light-renderer check(s)`
line of the `light_tests.py` gate (phase 2b, and the same count in the phase-3 run,
`diagnostics\cc5.4-stage9-firmware-gates.log`); replace it only if a later gate ran. Type it without
separators.

```powershell
. {
  if ($binary -notin 'D', 'E') { throw 'NOT RUN: $binary is not set to D or E in this window; set it to the binary that passed step 8' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\finalize_nanod_cc5.py' --binary $binary --companion-tests <suite-tests> --light-assertions 2174210
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: finalize refused (see its STOP line); nothing was recorded' }
  $firmware = '<repo>\app\firmware'
  $record = if ($binary -eq 'A') { 'manifest-1.0.0-cc5.4.json' } else { "manifest-1.0.0-cc5.4-$binary.json" }
  if ((Get-FileHash -LiteralPath "$firmware\manifest.json").Hash -ne (Get-FileHash -LiteralPath "$firmware\$record").Hash) { throw "NO-GO: manifest.json is not the cc5.4 binary $binary record" }
  "GO: cc5.4 binary $binary recorded as INSTALLED"
}
```

After install exit 5, add `--accept-unconfirmed-reset` to the finalize line. Without it, only outcome
`INSTALLED_VERIFIED_RESET` is accepted.

Finalize requires the binary's flash record with a verified install (for a binary prepared from a
step-down base, also `cc5.4-step-down-base.json` naming that base and read against the backup
`cc5.4-backup.json` records, and a flash record that verified against the same base), the release's device and lease
check records written after it that passed and show `1.0.0-cc5.4` with presentation 5, the device
checks reporting **that binary**, every gate of 8b (except those a recorded waiver names, below) and
both lease cases of 8c true, the after-inventory with `artwork2`, the unchanged `artwork` and `alive`
equal to `min(150, ledMaxBrightness)`, the before-inventory cc5.3, and the ten profiles identical. It refuses after any rollback made or started
since the install, by any profile's or binary's path (`cc5.4[-B|-C|-D|-E]-rollback*.json`, their work
folders, logs and restored-manifest copies, `cc5.4-manual-rollback-*`, and the earlier releases'
names), a ROM bootloader entry after the install, the binary's manifest marked `ROLLED_BACK`, or a
`manifest.json` that is not the record its status requires. On success it writes the binary's
installation record, marks the binary's manifest `INSTALLED` and copies it byte-identically to
`manifest.json`, records the binary under `cc5.4` in `diagnostics\validation.json` (keeping the old
one as `validation-before-cc5.4.json`), names every binary's status in the installation record
(`ladder`), and last marks `manifest-1.0.0-cc5.3.json` `SUPERSEDED` (only while it is `INSTALLED` and
byte-identical to `manifest-cc5.3.json`). The other binaries' manifests stay as they are.

**Recorded waiver.** Use it only when the user has signed off in this window, in their own words, that
the misses ship as a known issue. `--waive-gate NAME` (repeatable) with `--waiver-note "<text>"`
accepts only two categories of gates; the targets are not lowered, and every other gate of 8b must
still be true. A failed run is accepted only when every failed check is one of the waived gates' own
checks, failed for its miss alone, and each waived gate has such a failed check:

- Performance: `lcdTimings`, `ledRenderTime`, `jpegDecode` and `ledFrameRate`, for the measured miss
  alone (lcdFpsAnimMin 55 / 45 on binary A, ledRenderUsMax 3000 us, jpegDecodeMsMax 200 ms, ledFps 58
  and ledShowGapMsMax 20 ms at idle, ledFps 45 under cover transfers). A JPEG decode error, a missing
  diag field, an LED transmit failure, an idle measurement not of the alive renderer (`ledMode`), a
  cover that did not commit in the LCD pass (`coverCommitted`) or the LED load pass, or a stalled LED
  renderer (idle ledFps below 29 or ledShowGapMsMax above 40 ms, ledFps below 22.5 under load: half
  the frame-rate targets, twice the gap) still refuses.
- Operator timing: `limitPerPush` and `limitEvents`, the End stop test, only when its push windows
  were missed: its failed checks may name only a push with no lim (count 0), no lim while held, a lim
  outside the windows, or an end not seen (`no lim +1 seen` / `no lim -1 seen`), and its runs must
  prove the knob emitted each End stop in the right direction at the right end: a lim +1 during the
  push phase at T_end (a push window, the hold, or outside them before the phase ended) and a lim -1
  after the knob reported 0:00 (`reachedZero` and `limAtZero`), each in at least one run. A lim +1
  only after the push phase, or a lim -1 only before 0:00 was reached, proves neither (a firmware
  sending the wrong direction at T_end would look like late pushes). Chatter is a firmware fault and
  always refuses: a count of 2 or more for a push or the hold, two lims of a run closer than 100 ms
  (the firmware's 150 ms less the check's 50 ms jitter), or two lims of one direction in a run closer
  than 0.5 s (more than one lim for one push, which the per-push counts cannot see outside the
  windows; the firmware re-fires after at most 150 ms plus a 150 ms `lim_rearm_ms`). `limitEvents`
  also needs the stress+turn lims passed.

Any other gate name, or a waiver without a note, is refused before anything is read. The installation
record lists each waived gate with its category, what was measured and the note (`waivedGates`,
`waiverNote`; a named gate that passed goes to `waiverNotNeeded`); the manifest stays `INSTALLED` with
`waivedGates` next to it, as does `validation.json`, and the summary line reads `INSTALLED with waived
gates: ...`. For binary A with the user's 2026-09-26 sign-off (LCD animation 12-16 fps, LED render
16-17 ms under the extreme stress, one 222 ms JPEG decode, a 21 ms LED show gap at idle at ledFps 60;
the End stop test of run 3, while the operator followed a lagging relay instead of the beeps: in
attempt 1 no push landed in a push window, the knob sent lim +1 in the hold window (11.0 s), outside
the windows (13.1 s) and after the push phase (14.9 s), then lim -1 at 0:00 (21.7 s); attempts 2 and 3
recorded no clockwise End stop push, only lim -1, the judged attempt 3 two inside the push windows
(the knob was already at 0:00) and one at 0:00; a faster A2 follows later), run this block instead of
the one above, with `<suite-tests>` as above and `<text>` replaced by the user's sign-off (who, when,
what ships). A was rolled back the same evening and is retired, so finalize now refuses `--binary A`
(argparse, exit 2): this block stays as the record of that sign-off.

```powershell
. {
  if ($binary -ne 'A') { throw 'NOT RUN: this waiver is for binary A only; for B or C run the block above' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\finalize_nanod_cc5.py' --binary A --companion-tests <suite-tests> --light-assertions 2174210 --waive-gate lcdTimings --waive-gate ledRenderTime --waive-gate jpegDecode --waive-gate ledFrameRate --waive-gate limitPerPush --waive-gate limitEvents --waiver-note "<text>"
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: finalize refused (see its STOP line); nothing was recorded' }
  $firmware = '<repo>\app\firmware'
  if ((Get-FileHash -LiteralPath "$firmware\manifest.json").Hash -ne (Get-FileHash -LiteralPath "$firmware\manifest-1.0.0-cc5.4.json").Hash) { throw 'NO-GO: manifest.json is not the cc5.4 binary A record' }
  'GO: cc5.4 binary A recorded as INSTALLED (the finalize line above names any waived gates)'
}
```

Go: `GO: cc5.4 binary <X> recorded as INSTALLED` (with the waiver block: `GO: cc5.4 binary A recorded
as INSTALLED (the finalize line above names any waived gates)`). The finalize line reads `INSTALLED with
waived gates: ...` when a gate was waived, or `INSTALLED and copied to manifest.json` with `waiver not
needed` when every named gate passed.

No-go: finalize wrote nothing, and the knob and the desktop app keep working as they are. Fix what the
STOP line names and run step 10 again. Never roll back because of a finalize refusal alone. If the STOP
line names a rollback or a bootloader entry after the install, the binary cannot be recorded from this
install's evidence: decide with the user.

## Rollback and abort

The three rules of RECOVERY.md section 5 apply to every block here, with cc5.4 in place of cc5 and
cc5.3 in place of cc4:

- **Reset rule.** Never reset, unplug or power-cycle the knob yourself once a rollback write has
  started, or after install exit 4. From then on, the only resets are the rollback script's own (exit
  0), the one command it prints after exit 5, and manual block 4, which resets only when
  `$rollbackVerified` says block 2 or block 3 verified the rollback in this PowerShell window, and only
  after it has verified app0 once more itself. Any write outside block 2 invalidates that interlock.
- **Retry rule.** Count every failed rollback write or verify, whichever path it came from. After the
  first, retry once. After the second, stop: leave the knob connected and powered in the ROM
  bootloader, do not reset it, and keep `diagnostics\cc5.4*-rollback*` and
  `backups\cc5.4-manual-rollback-*` for diagnosis.
- **Nothing written yet.** While the binary under test is still verified in app0 (install exit 0 or 5,
  and no rollback write has started since), a stop that wrote nothing may leave the ROM bootloader with
  [the read-only reset](#leave-the-bootloader-without-writing).

### Abort before any write

Use this for a NO-GO in steps 3-5, or install exit 1 or 2. Nothing was written, so cc5.3 is intact
and a reset is safe. The block verifies app0 against the cc5.3 image first (read-only) and resets only
when that verify passes:

```powershell
. {
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flash -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.find_rom_port())"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'Exactly one MAC-matched ROM port is required; nothing was reset. If 239A:8010 (NANO_D) is present, cc5.3 is already running' }
  $global:LASTEXITCODE = -1
  & $flash -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 '<repo>\app\firmware\nanod-control-center-1.0.0-cc5.3.bin'
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not hold the cc5.3 image, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob: run this block again once; if app0 still does not verify, leave the knob in the ROM bootloader and decide with the user (reset rule)' }
  $global:LASTEXITCODE = -1
  $reset = (& $flash -u -m esptool --chip esp32s3 --port $romPort --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed; list ports before trying again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed; list ports before trying again, once' }
  'cc5.3 is restarting. Next: re-enable the companion.'
}
```

Then [re-enable the companion](#re-enable-the-companion). For a NO-GO in steps 1-2 the knob never
left cc5.3: only re-enable the companion.

### Leave the bootloader without writing

Only under the **Nothing written yet** rule: the binary under test is still verified in app0 (install
exit 0 or 5) and no rollback write has started since. This block writes nothing; it verifies app0
against that binary's image first (read-only) and resets only when that verify passes:

```powershell
. {
  if ($binary -notin 'A', 'B', 'C', 'D', 'E') { throw 'NOT RUN: $binary is not set in this window; set it to the binary in app0. Nothing was reset' }
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $image = if ($binary -eq 'A') { '<repo>\app\firmware\nanod-control-center-1.0.0-cc5.4.bin' } else { "<repo>\app\firmware\nanod-control-center-1.0.0-cc5.4-$binary.bin" }
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'No single MAC-matched ROM port; nothing was reset. If 239A:8010 (NANO_D) is present, the knob is already running' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 $image
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not hold the binary under test, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob: run this block again once; if app0 still does not verify, leave the knob in the ROM bootloader and decide with the user (reset rule)' }
  $global:LASTEXITCODE = -1
  $reset = (& $flashPython -u -m esptool --chip esp32s3 --port $romPort --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed; list ports, then run this block again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed; list ports, then run this block again, once' }
  "The knob is restarting into cc5.4 binary $binary, already in app0."
}
```

`finalize_nanod_cc5.py` refuses to record the binary after any ROM bootloader entry after its install,
including one that wrote nothing: this is for stopping the window, not for continuing it.

### Firmware rollback, cc5.4 -> cc5.3

Use this after install exit 4 (without any reset), for a NO-GO in steps 7-8, as the first half of
every step-down, and after a NO-GO in step 9 before the [desktop rollback](#desktop-rollback-v7---v6).
Keep the companion quit (the startup tasks are still disabled from step 1; after 9c, disable the
`Desk Dial` task too). Primary
path, scripted, with the flash venv; `$binary` names the binary being rolled back:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false   # this block may write app0
  if ($binary -notin 'A', 'B', 'C', 'D', 'E') { throw 'NOT RUN: $binary is not set in this window; set it to the binary in app0 (the last install --binary). This block sent and wrote nothing' }
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\nanod_enter_bootloader_v2.py'
  if ($LASTEXITCODE -ne 0) { throw 'No ROM bootloader port; this block sent and wrote nothing. If the message above says a companion is running: quit it from the tray and run this block again. After install exit 4 or a failed rollback write, if no MAC-matched ROM port remains: stop (reset rule). Otherwise fix the cause (RECOVERY.md section 2) and run this block again' }
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --to cc5.3 --binary $binary
  "rollback_nanod_cc5.py --to cc5.3 --binary $binary exit $LASTEXITCODE; act on it with the table below"
}
```

`nanod_enter_bootloader_v2.py` sends nothing when the MAC-matched ROM port is already present (after
install exit 4). `rollback_nanod_cc5.py --to cc5.3 --binary <X>` checks the file hashes against the
binary's preparation record, that the rollback app0 starts with the cc5.3 image and that
`manifest-cc5.3.json` is the cc5.3 record; then `flash_id` (MAC, 4MB), reads the partition table and
OTA data (both must equal the pre-cc5.4 backup), writes `nanod-cc5.3-before-cc5.4-active-app.bin` at
`0x10000` (`--flash_mode keep --flash_freq keep --flash_size keep`), verifies app0, verifies the full
4 MB against the backup (on a difference, each region on its own: drift in `nvs`, `spiffs` or
`coredump` is reported, never rewritten), and only then resets. Once the flash is verified it restores
`manifest.json` from `manifest-cc5.3.json` (the previous file kept as
`manifest-at-cc5.4[-B|-C|-D|-E]-rollback-<UTC>.json`), marks any `INSTALLED` cc5.4 manifest of any binary
`ROLLED_BACK`, and writes the binary's rollback record (`cc5.4-rollback.json` for A,
`cc5.4-<X>-rollback.json` for the others), whose `outcome` matches the exit code. Its last line names
the outcome (since the D and E tooling a clean exit 0 no longer adds a false `did NOT complete`), and a
note on data regions that changed since the backup follows it. Without `--binary` the script
takes the binary whose flash record shows the newest write (else A); this block always names it.

| Exit code | Meaning | Do next |
|---|---|---|
| 0 | cc5.3 is restored, verified and reset. `manifest.json` is the cc5.3 record again. | [After the rollback](#after-the-rollback), or the next step of a step-down. |
| 1 | Nothing was sent: wrong Python or esptool, a file hash, the binary's preparation record, the cc5.3 record, or not exactly one MAC-matched ROM port. | Fix the cause and run the scripted block again; after a failed write, never by unplugging (reset rule). Only when the cause is the cc5.3 record or the script itself, and it cannot be fixed, use the manual blocks. |
| 2 | Identity, partition table or OTA data did not match (or a usage error, such as an unreadable cc5.4 flash record without `--binary`). This run wrote nothing and did not reset. | Stop and write nothing. Nothing written yet: [leave the bootloader without writing](#leave-the-bootloader-without-writing), [re-enable the companion](#re-enable-the-companion) and inspect the evidence with the user. After install exit 4 or a counted failure: leave the knob in the ROM bootloader and stop (reset rule). |
| 4 | A write or verify failed after the write started. The chip was **not** reset. | Reset rule. First counted failure: run the scripted block once more. Second: stop (retry rule). |
| 5 | cc5.3 is written and verified and `manifest.json` is restored, but the reset was **not confirmed**. | Run only the `read_mac --after hard_reset` command the script prints, once. If the ROM port is gone and `239A:8010` (`NANO_D`) is present, the chip has already restarted. If that single retry also cannot confirm a reset and the ROM port is still present, the verified image makes unplugging the USB cable for 5 s a safe reset (the only case where a power-cycle is allowed). The same applies to install exit 6. |
| 6 | The device rollback verified and reset, but `manifest.json` was **not** restored (`recordsError`). | Fix the cause, then run the records-only block below. |
| -1 | The script did not run at all (the block's own marker). Nothing was sent. | Fix the interpreter path and run the scripted block again. |
| Any other | The script was interrupted (for example with Ctrl+C). | Open the binary's rollback record. If `writeAttempted` is true, or the file is missing or older than this run, treat it as exit 4. Otherwise treat it as exit 2. |

```powershell
. {
  if ($binary -notin 'A', 'B', 'C', 'D', 'E') { throw 'NOT RUN: $binary is not set in this window; set it to the binary that was rolled back' }
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --to cc5.3 --binary $binary --records-only
  if ($LASTEXITCODE -ne 0) { throw 'manifest.json was not restored; fix the cause printed above and run this block again. It does not touch the knob' }
}
```

`rollback_nanod_cc5.py` without `--to` is the cc5 -> cc4 history path; once any cc5.x write is on
record it refuses to run without `--to` (exit 2, nothing sent). Always pass `--to cc5.3` here; `--to
cc5.2` or `--to cc4` only if the user decides to go back further (RECOVERY.md sections 6 and 5).

### Firmware, manual esptool fallback

Use this path only for an exit 1 whose cause is the cc5.3 record or the script itself and cannot be
fixed. The knob must already be in the ROM bootloader (the scripted block's first command puts it
there). The blocks issue the same esptool commands as the script, one block at a time, in one
PowerShell window; every esptool line is followed by its own `$LASTEXITCODE` check, and the interlock
flags work as in RECOVERY.md section 5 (each block clears every flag it depends on or re-establishes
before its first command; `install_nanod_cc5.py` writes app0 too, so after an install run in this
window start again at block 1).

**Block 1: read-only checks.** It requires esptool 4.12.0 first, checks both file hashes against the
binary's preparation record and the chip identity, cuts the pre-cc5.4 backup into region files and
compares the partition table and the OTA data with it:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false
  if ($binary -notin 'A', 'B', 'C', 'D', 'E') { throw 'NOT RUN: $binary is not set in this window; nothing was sent' }
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $esptoolVersion = & $flashPython -c "import esptool; print(esptool.__version__)"
  if ($LASTEXITCODE -ne 0 -or $esptoolVersion -ne '4.12.0') { throw 'The flash venv does not have esptool 4.12.0; nothing was sent. Fix the flash venv; the manual blocks are no way around it' }
  $backupFull = '<repo>\app\backups\nanod-cc5.3-before-cc5.4-full.bin'
  $rollbackApp = '<repo>\app\backups\nanod-cc5.3-before-cc5.4-active-app.bin'
  $prepName = if ($binary -eq 'A') { 'cc5.4-preparation.json' } else { "cc5.4-$binary-preparation.json" }
  $prep = Get-Content -Raw -LiteralPath "<repo>\app\diagnostics\$prepName" -ErrorAction Stop | ConvertFrom-Json
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $rollbackApp -ErrorAction Stop).Hash -ne $prep.rollbackSha256) { throw 'Rollback file hash mismatch; nothing was sent' }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $backupFull -ErrorAction Stop).Hash -ne $prep.beforeSha256) { throw 'Pre-cc5.4 backup hash mismatch; nothing was sent' }
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'Exactly one MAC-matched ROM bootloader port is required; nothing was sent' }
  $work = (New-Item -ItemType Directory -ErrorAction Stop -Path ('<repo>\app\backups\cc5.4-manual-rollback-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))).FullName
  $global:LASTEXITCODE = -1
  @'
import sys
from pathlib import Path
backup, out = Path(sys.argv[1]).read_bytes(), Path(sys.argv[2])
if len(backup) != 0x400000:
    raise SystemExit("The pre-cc5.4 backup is not 4 MB")
regions = {"bootloader": (0x0, 0x8000), "partition-table": (0x8000, 0x1000),
           "otadata": (0xE000, 0x2000), "app0": (0x10000, 0x140000), "app1": (0x150000, 0x140000)}
for name, (offset, size) in regions.items():
    (out / f"region-{name}.bin").write_bytes(backup[offset:offset + size])
'@ | & $flashPython - $backupFull $work
  if ($LASTEXITCODE -ne 0) { throw 'Could not cut the backup into regions; nothing was sent' }
  $global:LASTEXITCODE = -1
  $id = (& $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub flash_id) -join "`n"; Write-Host $id
  if ($LASTEXITCODE -ne 0) { throw 'flash_id failed; nothing was written' }
  if ($id -notmatch '12:34:56:78:9a:bc' -or $id -notmatch 'Detected flash size: 4MB') { throw 'Wrong chip or flash size; nothing was written' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub read_flash 0x8000 0x1000 "$work\current-partition-table.bin" --no-progress
  if ($LASTEXITCODE -ne 0) { throw 'Partition table read failed; nothing was written' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub read_flash 0xE000 0x2000 "$work\current-otadata.bin" --no-progress
  if ($LASTEXITCODE -ne 0) { throw 'OTA data read failed; nothing was written' }
  foreach ($name in 'partition-table', 'otadata') {
    $current = (Get-FileHash -Algorithm SHA256 -LiteralPath "$work\current-$name.bin" -ErrorAction Stop).Hash
    $saved = (Get-FileHash -Algorithm SHA256 -LiteralPath "$work\region-$name.bin" -ErrorAction Stop).Hash
    if ($current -ne $saved) { throw "$name differs from the pre-cc5.4 backup; nothing was written. Stop and inspect" }
  }
  $layoutVerified = $true
  "Block 1 passed on $romPort. Nothing has been written. Next: block 2."
}
```

**Block 2: write and verify.** This block **writes firmware**: app0 only, then verifies app0 and the
full 4 MB. It never resets:

```powershell
. {
  if (-not $layoutVerified) { throw 'Block 1 has not passed since the last write; run block 1 first. Nothing was written' }
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'write_flash failed. Do NOT reset, unplug or power-cycle the knob; see the failure rules' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'app0 verify failed. Do NOT reset, unplug or power-cycle the knob; see the failure rules' }
  $app0Verified = $true
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x0 $backupFull
  if ($LASTEXITCODE -ne 0) { throw 'app0 is verified, but the full image differs from the pre-cc5.4 backup. Do NOT reset; run block 3' }
  $rollbackVerified = $true
  'app0 and the full 4 MB match the pre-cc5.4 backup. The chip has not been reset. Next: block 4.'
}
```

**Block 3: only when block 2 stopped at the full verify.** It verifies each critical region
(bootloader, partition table, OTA data, app0, app1) against the region files from block 1; if all
match, the difference is only in `nvs`, `spiffs` or `coredump`:

```powershell
. {
  if (-not $app0Verified) { throw 'Block 2 has not verified app0 in this window. Do NOT reset' }
  $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $regions = [ordered]@{ 'bootloader' = '0x0'; 'partition-table' = '0x8000'; 'otadata' = '0xE000'; 'app0' = '0x10000'; 'app1' = '0x150000' }
  foreach ($name in $regions.Keys) {
    $global:LASTEXITCODE = -1
    & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash $regions[$name] "$work\region-$name.bin"
    if ($LASTEXITCODE -ne 0) { throw "$name differs from the pre-cc5.4 backup, or its verify did not run. Do NOT reset, unplug or power-cycle the knob; see the failure rules" }
  }
  $rollbackVerified = $true
  'Every critical region matches; only nvs, spiffs or coredump differ. The chip has not been reset. Next: block 4.'
}
```

**Block 4: check app0, reset, records.** The only block that resets. It refuses unless block 2 or
block 3 printed its success line after the last write in this window, finds the ROM port again,
verifies app0 against the rollback file once more, and resets only when that passes:

```powershell
. {
  if (-not $rollbackVerified) { throw 'The rollback has not been verified in this window. Do NOT reset' }
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'No single MAC-matched ROM port; nothing was reset. If 239A:8010 (NANO_D) is present, an earlier block 4 reset already restarted the chip: run only the records-only block. Otherwise do NOT reset; see the failure rules' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not match the rollback file, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob; see the failure rules' }
  $global:LASTEXITCODE = -1
  $reset = (& $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed. The flash is verified: run only this block again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed. The flash is verified: run only this block again, once' }
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --to cc5.3 --binary $binary --records-only
  if ($LASTEXITCODE -ne 0) { throw 'The chip is reset into cc5.3, but manifest.json was not restored. Fix the cause printed above, then run only the records-only block' }
  'cc5.3 is restored, verified and reset; manifest.json is the cc5.3 record again.'
}
```

**If a block stops:** a stop in block 1 wrote nothing; a stop in block 2 at `write_flash` or the app0
verify, in block 3, or at block 4's app0 verify is a counted failure (reset rule; first: run block 1,
then block 2 again; second: stop); block 2 stopping at the full verify sends you to block 3; a block
4 reset that was not confirmed is run again once.

### After the rollback

With the companion still quit, wait for the native screen, then confirm that the application port
stays enumerated for 30 s and read the inventory:

```powershell
. {
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $appPort = & $flashPython -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.poll_ports(t.is_app_port, 60, settle=30)[0] or '')"
  if ($LASTEXITCODE -ne 0 -or -not $appPort) { throw 'No stable 239A:8010 NANO_D port; write nothing and see RECOVERY.md section 2' }
  $global:LASTEXITCODE = -1
  & '<repo>\app\.venv\Scripts\python.exe' '<repo>\app\device_inventory.py' --port $appPort
  if ($LASTEXITCODE -ne 0) { throw 'The inventory failed' }
}
```

The new `backups\control-center-inventory-*.json` must show `firmwareVersion` `1.0.0-cc5.3`,
`presentation` 4, `artwork2`, no `alive`, and the same ten profiles. In a step-down, go on with the
next binary (step 3, then the step-down base and its preparation); after a NO-GO in step 9, go on with the
[desktop rollback](#desktop-rollback-v7---v6); otherwise [re-enable the companion](#re-enable-the-companion).
Desktop v7 works with cc5.3 (presentation-4 downgrade); desktop v6 too.

### Desktop rollback, v7 -> v6

Use this for a NO-GO in step 9, and only once the knob is back on cc5.3. cc5.4 names Desk Dial on the
knob (the offline screen's `Open Desk Dial` / `on your PC`, the boot screen's `DESK DIAL`), while v6 is
still NanoD Control Center: a desktop rollback on its own would leave the knob telling the user to open
an app that is not installed, which the rename plan rules out (rename-desk-dial.md 14.2 step 3). After a
NO-GO in step 9, work in this order:

1. Quit the companion from its tray icon, and disable the `Desk Dial` task if 9c registered it
   (`Disable-ScheduledTask -TaskName 'Desk Dial'`).
2. The [firmware rollback](#firmware-rollback-cc54---cc53), with `$binary` still naming the binary that
   step 6 installed, then [after the rollback](#after-the-rollback).
3. This desktop rollback. Its block refuses to install until that binary's rollback record
   (`cc5.4-rollback.json` for A, `cc5.4-<X>-rollback.json` for B to E) is newer than its install
   record (`cc5.4-flash-checks.json`, `cc5.4-<X>-flash-checks.json`) and reports a verified cc5.3
   (`ROLLED_BACK_VERIFIED_RESET`, `ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED` or `RECORDS_ONLY`).
4. [Re-enable the companion](#re-enable-the-companion).

The firmware goes first: if its rollback stops, the knob keeps cc5.4 next to Desk Dial, whose names
match. The other pairing, cc5.3 next to Desk Dial, is the one the rename plan accepts (section 12: cc5.3
keeps its old copy until the next firmware), so after a firmware rollback on its own the desktop may
stay on v7, or come back to v6 with this section when the user wants.

The block installs the pinned v6 bundle (exe SHA-256
`2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F`; `Install-Desktop.ps1` refuses a
`desktop-dist-v6` with another exe). Its identity table reverses the rename: it unregisters `Desk Dial`
and deletes `Desk Dial.lnk`, installs to `Programs\NanoDControlCenter`, and re-registers
`NanoD Control Center` with its shortcut. v6 reads the old home, which the migration kept as it was;
`%LOCALAPPDATA%\DeskDial\` stays, so a later v7 install does not migrate again. Nothing is carried back,
and the installer has no option for it (the rename plan's optional `-CarryDataBack`, RN-6, was not
built): settings changed and Apple Music sign-ins made in Desk Dial since the install stay only in
`%LOCALAPPDATA%\DeskDial\`. If the user wants them in v6, copy those files back into the old home by
hand, together with the user, after keeping a copy of the old files.

```powershell
. {
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: quit the companion from the tray first; nothing was installed' }
  if ($binary -notin 'A', 'B', 'C', 'D', 'E') { throw 'NOT RUN: $binary is not set in this window; set it to the binary that step 6 installed. Nothing was installed' }
  $diagnostics = '<repo>\app\diagnostics'
  $prefix = if ($binary -eq 'A') { 'cc5.4' } else { "cc5.4-$binary" }
  $installRecord = Get-Item -LiteralPath "$diagnostics\$prefix-flash-checks.json" -ErrorAction SilentlyContinue
  $rollbackRecord = Get-Item -LiteralPath "$diagnostics\$prefix-rollback.json" -ErrorAction SilentlyContinue
  if (-not $installRecord) { throw 'NOT RUN: $binary names no installed binary (no flash-checks record); set it to the binary that step 6 installed. Nothing was installed' }
  if (-not $rollbackRecord -or $rollbackRecord.LastWriteTimeUtc -le $installRecord.LastWriteTimeUtc) { throw 'NOT RUN: the knob still runs cc5.4, which names Desk Dial; run the firmware rollback to cc5.3 first. Nothing was installed' }
  $rollbackOutcome = (Get-Content -Raw -LiteralPath $rollbackRecord.FullName -ErrorAction Stop | ConvertFrom-Json).outcome
  if ($rollbackOutcome -notin 'ROLLED_BACK_VERIFIED_RESET', 'ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED', 'RECORDS_ONLY') { throw 'NOT RUN: the firmware rollback did not verify cc5.3; finish it first (its exit code table). Nothing was installed' }
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v6 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: the desktop rollback failed; the program folder copy from step 9b is in backups\desktop-program-before-cc5.4-<UTC>' }
  if (Get-ScheduledTask -TaskName 'Desk Dial' -ErrorAction SilentlyContinue) { throw 'NO-GO: the Desk Dial task is still registered next to the v6 task' }
  'Desktop v6 installed again. Next: re-enable the companion.'
}
```

Then [re-enable the companion](#re-enable-the-companion).

### Re-enable the companion

Exactly one startup task must exist (`Desk Dial` after step 9, `NanoD Control Center` before it or
after a desktop rollback); two would start two companions that contend for the knob:

```powershell
. {
  $tasks = @('Desk Dial', 'NanoD Control Center' | Where-Object { Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue })
  if ($tasks.Count -ne 1) { throw "NO-GO: expected exactly one companion startup task, found $($tasks.Count); decide with the user" }
  Enable-ScheduledTask -TaskName $tasks[0] -ErrorAction Stop | Out-Null
  Start-ScheduledTask -TaskName $tasks[0] -ErrorAction Stop
  "Started the '$($tasks[0])' task."
}
```

## Deviations recorded by the tooling package (TOOL-bc)

| Id | Deviation | Why |
|---|---|---|
| TB-D1 | The device and lease check records keep the release's names (`cc5.4-device-checks.json`, `cc5.4-lease-checks.json`) for every binary; the binary is recorded in them (`binary`, `sections.diag.binary`) and finalize ties them to the binary's install by time | one name per release keeps every block and `check_nanod_cc5_lease.py` unchanged; each binary's own build, package, preparation, flash, rollback and installation records carry its letter |
| TB-D2 | A step-down is a verified rollback to cc5.3, then a step-down base read (`backup_nanod_cc5.py --step-down`) and the next binary prepared from it (`--step-down-base`), then a normal install; never a binary written over another, and never a refreshed backup | the rollback returns every critical region exactly but keeps drift in `nvs`, `spiffs` and `coredump` (a panicking binary writes its core dump), so the next install verifies the device against a base whose critical regions equal the one locked pre-cc5.4 backup; that backup is never replaced and every rollback still verifies against it (review fix TOOLBC-1) |
| TB-D3 | Only the four 12.6 checks drive the step-down table; any other gate failure is decided with the user | 12.6 defines the decisions for checks 1-4 only; a step-down changes nothing but the LCD pipeline |
| TB-D4 | The period (R4) is not verified build-only; `check_nanod_cc5.py --binary` verifies it on the device (`lcdPeriodMs`) | the 33 ms constant leaves no marker in the image or the symbol table |
| TB-D5 | C's heap projection counts H = 0 (98,648 B), not the 512 B the phase-2b note used (98,136 B) | 12.4: H is the SPI DMA descriptors, "A and B" only |
| TB-D6 | The cc5.4 -> cc5.3 rollback, scripted and manual, is in this file, not in RECOVERY.md | RECOVERY.md is outside this package; its sections 5 and 6 stay the history runbooks |
| TB-D7 | The 12.6 check 1 (panel image) compares the covers the device checks show with the harness contact sheet of the same layouts, not a byte-identical frame | no tool shows the harness's exact frame on the knob; 8b's first minutes show design covers on the same layouts |
| TB-D8 | Building binary A rewrote `work\nanod-cc5.4-build.log`, which held the phase-2a gatekeeper's hand-written build note, and the 11:54-11:55 UTC rebuilds rewrote the three logs the first packages pin (the `*.superseded-20260926T1155*` manifests' gates: `30a4d80a...`, `3ea9ad17...`, `b0b102d6...`); those logs are lost. K1 12.4 cites `work\nanod-cc5.4-build.log:1007` (RAM 259,328 B) and `:1021` (headroom 261,424 B), lines the current 60-line log does not have | fixed at the root (review fix TOOLBC-2): `build_nanod_cc5.py` now renames an earlier log to `nanod-cc5.4[-B\|-C]-build.superseded-<UTC>.log` and records `logSha256`, and packaging refuses a log that is not the accepted build's. The two cited figures survive in the phase-2b gatekeeper's scratch copy of that round-2 log (`gatekeeper\nanod-cc5.4-build.round2.log`, 1,027 lines, SHA-256 `1b897bd8...`); ~~the K1 12.4 erratum saying the cited lines are gone belongs to K1's owner~~ the K1 erratum is applied (PRESENTATION_V5 12.4 row 1, 16.8 E-tb; 2026-09-26) |
| TB-D9 | After a step-down, the `coredumpBlank` gate of the next binary accepts the failed binary's core dump that its step-down base holds (same size as the base's partition names, no crash reset reason; `coredumpInherited` in the evidence); the gate stays strict in every other case and without `--binary` | the rollback keeps the dump (the tooling never clears flash outside app0, and the runbook says keep it), so without this the binary after a panicking one could never pass 8b and R-m's A -> B -> C step-down would still stop there; a new panic of the binary under test shows as a crash reset reason or as a reboot (`noRebootOrReenumeration`). ~~Needs the lead's acceptance (review fix TOOLBC-1, not among R-l's accepted deviations)~~ **Accepted by the lead (2026-09-26)** (review fix TOOLBC-1) |
| TB-D10 | D and E are two more binaries of the same release, 1.0.0-cc5.4, not a new release: the version string is unchanged, and D and E are told apart by their artifact names, diag `build` and the image marker `cc-build-binary:<n>` (`CC_BUILD_BINARY`, numeric) | the release's from-release, locked backup, gates, the 8a inventory check, the Desk Dial v7 compatibility and the finalize chain all key on the version; a new release would need a new locked full backup, a rollback target and a runbook. Rebuilding A in place would give A two images and make its evidence ambiguous |
| TB-D11 | The look session installs D and checks it with two diag reads and the user's eye (`check_nanod_cc5_look.py`), without 8b, 8c or finalize; D stays installed, not finalized | D keeps A's `lcdTimings` targets (55 / 45), which the later performance task has to reach (A measured 12-16); the look session proves the two fixes the user saw (the LCD data line and the LED dither) |
| TB-D12 | The fix binaries' two diag fields (`lcdMosiSig`, `build`) live in the tooling's `LCD_FIX_DIAG_FIELDS`, not `LCD_DIAG_FIELDS`; `harness\alive_tests.py` checks the firmware's diag reply and `media_tests.cpp`'s field list against `LCD_DIAG_FIELDS + LCD_FIX_DIAG_FIELDS` (integrator, 2026-09-26) | the companion's `device.DIAG_LCD_FIELDS` mirrors `LCD_DIAG_FIELDS` (`test_cc_device_diag`) and ignores unknown diag fields, so Desk Dial v7 needs no change; the firmware and its host wiring test carry all 26 |
