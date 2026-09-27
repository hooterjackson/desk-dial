# cc5.3 artwork2 (1.0.0-cc5.3) and desktop v4: build, package, install

Status: **1.0.0-cc5.3 gated, built by `build_nanod_cc5.py` and packaged on 2026-09-24 (image
SHA-256 `f1cd05a2cd43e0298ff9b10e4bf05ea77590e5d8e31a68623540f752fdd40541`); desktop v4 built
into `desktop-dist-v4` (rebuilt on 2026-09-24 after the adopted-lookahead fix; exe SHA-256 `63047D1C7C181C456B0AEE6E825B21326899538164E6AFFECB3800785C0C44A5`,
not installed, frozen smoke test at step 1); UNFLASHED.** The knob runs **1.0.0-cc5.2**
(installed and finalized on 2026-09-23: image `nanod-control-center-1.0.0-cc5.2.bin`, SHA-256
`45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572`; its verified install image
`../backups/nanod-cc5.2-expected-full.bin`, SHA-256
`19cd67b2f91b97bcee942c9dbb2fa4662c337f1d23bd64282d5c852894c1ed12`). The installed companion is
desktop v3 (exe SHA-256 `90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19`).
`manifest.json` is the installed cc5.2 record. cc5.2 stays installed until the app-only install
in step 6 completes and `finalize_nanod_cc5.py` records cc5.3 (step 10).

The contract is `firmware/ARTWORK2.md` (artwork2, an additive extension of
`PRESENTATION_V4.md`; `presentation` stays 4, and the v1 `artwork` object, the `art` command,
its 120 px store, error strings and binding rule are byte-identical, so the v3 companion works
unchanged). Read [RECOVERY.md](RECOVERY.md) section 6 (cc5.3 -> cc5.2 rollback) before any
hardware step. In this file, cc5.3 means 1.0.0-cc5.3 and cc5.2 means the installed 1.0.0-cc5.2.

Every command in this file uses absolute paths, so it works from any folder.

## What 1.0.0-cc5.3 changes

Why (user report, 2026-09-23): covers took about 5 s to appear (80 % of it the host's 64 B / 5 ms
pacing), looked low-res (120 px scaled up twice), nothing could be preloaded, and app icons never
reached the knob. cc5.3 adds (details: `firmware/ARTWORK2.md`):

- **Capability `artwork2`** next to the unchanged `artwork`: 240x240 baseline JPEG covers (at
  most 32768 B, 24 cached), 32x32 RGB565 icons over black (2048 B, 48 cached), `chunkBytes`
  2048, `haveKeys` 24, `rxBytes` 8192, `paced` false.
- **The `media` command** (`have`, `begin`, `data`, `commit`; exactly one `mediaAck` per line)
  with knob-side prefetch: keys the frame does not name are accepted and kept, the frame's and
  the displayed key are pinned, and eviction is least-recently-used at `begin`.
- **Unpaced transport** once negotiated: whole-line writes, stop-and-wait media lines, an
  8192-byte internal CDC receive queue, and a 1-tick COM idle while a line or upload is pending.
- **LCD:** JPEG decode (ROM TJpgDec) into front/back 240x240 buffers, the icon on the Windows
  tile (letter tile otherwise), `iconKey` in frames.
- **diag:** `rxQueueBytes`, `mediaCommits`, `mediaErrors`, `mediaEvictions`, `jpegDecodes`,
  `jpegDecodeErrors`, `jpegDecodeMsMax`, `jpegDecodeMsLast`.
- **Desktop v4** (`desktop-dist-v4`): the artwork2 push engine and wanted lists, prefetch of
  the Recent page covers, icon payloads, whole-line writes; v1 art with pacing against cc5.2,
  text only against cc4. Host only, no firmware change (ARTWORK2.md section 11, user request
  2026-09-24): the Recent list and its covers are kept one page ahead, and on Home a background
  copy of Recent page 1 warms its covers.

Everything cc5.2 fixed stays: the bounded LED transport, the task watchdog, the release
timeout, reboot and liveness fields.

## Build (never uploads)

```powershell
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' '<repo>\tools\build_nanod_cc5.py'
```

The script runs `platformio run -d firmware -e nanofoc_d` with
`PLATFORMIO_CORE_DIR=<pio-core>`. There is no upload target and
no git or device access. The complete log goes to `work/nanod-cc5.3-build.log` in UTF-8 (earlier
releases keep `work/nanod-cc5-build.log`, `nanod-cc5.1-build.log` and `nanod-cc5.2-build.log`).
The build is accepted only when the log contains `[SUCCESS]`,
`.pio/build/nanofoc_d/firmware.bin` is an ESP image (magic `0xE9`) smaller than app0
(`0x140000`), and the image contains `1.0.0-cc5.3`. The record is
`../diagnostics/cc5.3-build.json` (size, SHA-256, headroom, the delta from cc4 and from
cc5.2); the cc5.2 record `cc5-build.json` is never touched.

## Package (no device, manifest.json untouched)

```powershell
& '<repo>\app\.venv\Scripts\python.exe' '<repo>\tools\package_nanod_cc5.py'
```

It requires the accepted build record whose SHA-256 still matches `firmware.bin`, and that
`manifest.json` is the INSTALLED cc5.2 record. It writes to this folder:

- `nanod-control-center-1.0.0-cc5.3.bin`, `nanod-control-center-1.0.0-cc5.3-source.zip`
  (`git ls-files --cached --others --exclude-standard`, `.vscode/` excluded, and so are the
  generated `compile_commands.json` and `*.d` files in the firmware root; every archived
  file compared with the working tree);
- `manifest-1.0.0-cc5.3.json`, status `UNFLASHED`: artifact and source hashes,
  `changedFromCc4`, `changedFromPreviousCc5` (against 1.0.0-cc5.2), the expected capabilities
  (`artwork` unchanged and `artwork2`), the compatibility note and the gate files;
- `manifest-cc5.2.json`: a byte copy of `manifest.json`, the installed cc5.2 record, written
  once (an identical file is kept, a different one stops packaging). Prepare, finalize and the
  cc5.3 -> cc5.2 rollback use it as the cc5.2 record.

Packaging never changes an installed record: `manifest-1.0.0-cc5.2.json` stays `INSTALLED`
(only earlier manifests that were never installed as final are marked `SUPERSEDED`), so an
aborted or rolled-back cc5.3 leaves every cc5.2 record as it is. Step 10 (finalize) marks it
`SUPERSEDED` once cc5.3 is recorded as installed. The images and source archives of every earlier
release are never touched. `manifest.json` is never modified here; the script checks it is
unchanged at the end.

| Item | Value (from `../diagnostics/cc5.3-build.json` and the manifest; packaged 2026-09-24) |
|---|---|
| `firmware.bin` | 1,023,648 B (`0xF9EA0`), magic `0xE9`, contains `1.0.0-cc5.3` (and not `1.0.0-cc5.2`); `../diagnostics/cc5.3-build.json` (accepted, build started 2026-09-24T08:20:33Z; 1,201 B, SHA-256 `43484adbf304b2802d96fd62894bdad62d062043c2f1b394962969f2d7cff8fb`) |
| app0 slot | 1,310,720 B (`0x140000`) |
| Headroom | 287,072 B |
| Change from cc5.2 (1,010,656 B) | +12,992 B (+96,560 B from cc4, 927,088 B) |
| Image SHA-256 | `f1cd05a2cd43e0298ff9b10e4bf05ea77590e5d8e31a68623540f752fdd40541` (`nanod-control-center-1.0.0-cc5.3.bin`; identical to the compile verification of the gate run) |
| RAM / flash used (PlatformIO) | 245,056 B / 1,023,281 B (cc5.2: 228,928 B / 1,010,289 B) |
| Build log | `work/nanod-cc5.3-build.log`, 2,089 B, SHA-256 `5fb2f091bdfcf491ba713e74b4d1e6f7cf8544d7074d0f640ecf5240b0d1bc6e` (`[SUCCESS]`) |
| Source archive | `nanod-control-center-1.0.0-cc5.3-source.zip`, 1,309,487 B, SHA-256 `cd9b83bf74be2339946e69f4de875fe76bd4b16cae1773e3a318097239711661`; 124 files, each equal to the working tree (checkout HEAD `79ca593f...`, none missing; no `.vscode/`, `compile_commands.json` or root `*.d`) |
| `changedFromCc4` | 28 added, 15 modified, 0 removed |
| `changedFromPreviousCc5` | from 1.0.0-cc5.2: 6 added (`ARTWORK2.md`, `src/cc_jpeg.cpp`, `src/cc_jpeg.h`, `src/cc_media.cpp`, `src/cc_media.h`, `src/cc_media_store.h`), 14 modified (`CONTROL_CENTER.md`, `PRESENTATION_V4.md`, `platformio.ini`, `src/cc_diag.cpp`, `src/cc_diag.h`, `src/cc_display.cpp`, `src/cc_display.h`, `src/cc_frame_parse.cpp`, `src/cc_frame_parse.h`, `src/cc_presentation.h`, `src/com_thread.cpp`, `src/control_center.cpp`, `src/lcd_thread.cpp`, `src/main.cpp`), 0 removed |
| `manifest-1.0.0-cc5.3.json` | 26,672 B, SHA-256 `473c94c22c60b0f06d431b9993cc9e3508eabd71be819ec1ba165d343ea01b7f`, status `UNFLASHED`, validation `firmwareBuild` PASS, `physicalValidation` PENDING, `flashWriteIssued` false; `expectedCapabilities.artwork2` equal to `presentation.ARTWORK2_CAPABILITY`; 4 gate files recorded (see [Gate evidence](#gate-evidence)) |
| `manifest-cc5.2.json` | written by packaging: a byte copy of `manifest.json`, 165,844 B, SHA-256 `76da5f8eb92a519698eb0a660970265647b621bef081a23cc87fa0df549005f5` |
| Superseded | nothing changed: `manifest-1.0.0-cc5.2.json` stays `INSTALLED` (byte-identical to `manifest.json`); `manifest-1.0.0-cc5.json` and `manifest-1.0.0-cc5.1.json` were already `SUPERSEDED`; the firmware folder before and after packaging differs only by the four new files, so every earlier image, source archive and manifest is untouched |
| `manifest.json` | untouched: still `1.0.0-cc5.2` `INSTALLED`, SHA-256 `76da5f8eb92a519698eb0a660970265647b621bef081a23cc87fa0df549005f5` before and after, byte-identical to `manifest-cc5.2.json` |

The desktop v4 bundle is built with `Build-Desktop.ps1` (default output `desktop-dist-v4`,
work folder `desktop-build-v4`; it refuses to write into the v2 or v3 folders, which are the
rollback bundles). Build it before the hardware window, with the installed v3 companion still
running: `-SkipSmoke` builds only, because the script's own smoke test refuses to run while a
companion runs. The frozen smoke test is step 1's, after the installed companion is quit. The
script first runs `pip install -r requirements-desktop.txt` in the companion's `.venv` (network
access). Nothing here touches the knob, the installed companion or its task:

```powershell
. {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Build-Desktop.ps1' -SkipSmoke
  if ($LASTEXITCODE -ne 0) { throw "NOT RUN: Build-Desktop.ps1 exited $LASTEXITCODE; the v4 bundle was not built" }
  $v4 = '<repo>\app\desktop-dist-v4\NanoDControlCenter\NanoDControlCenter.exe'
  if (-not (Test-Path -LiteralPath $v4)) { throw 'NOT RUN: the v4 executable is missing after the build' }
  "GO: v4 bundle built: $v4 (SHA-256 $((Get-FileHash -LiteralPath $v4 -Algorithm SHA256).Hash))"
}
```

Go: the block prints `GO:` with the v4 executable's SHA-256; step 1 smoke-tests that executable.
A `NOT RUN:` changed nothing that is installed: fix what it names and run the block again.

First built on 2026-09-24 at 08:22:14–08:22:33 UTC:
- `-SkipSmoke`, exit 0.
- The pip step ran with `PIP_NO_INDEX=1`: every requirement was already satisfied and nothing was downloaded.
- The installed v3 companion kept its PID.
- exe SHA-256 `2F0EB061...`. Superseded; that record is kept as `cc5.3-desktop-v4-build.superseded-*.json`.

**Rebuilt the same way on 2026-09-24 (exit 0)**, after the controller.py adopted-lookahead fix:
- ARTWORK2.md 11.1. The new test is `test_an_adopted_load_survives_a_failed_state_poll`.
- Full non-Tk suite: 1,106 tests OK, in `../diagnostics/cc5.3-desktop-v4-rebuild-suite.log`.
- `GO:` with `desktop-dist-v4\NanoDControlCenter\NanoDControlCenter.exe`, 7,311,584 B, SHA-256 `63047D1C7C181C456B0AEE6E825B21326899538164E6AFFECB3800785C0C44A5`.
- 1,161 files, 65,963,879 B.
- Listing `../diagnostics/cc5.3-desktop-dist-v4-sha256.json` (SHA-256 `7EFE57578C4DFF066BB8EB51B567F0F7961807BF0F9E976B0806E2069D28D22F`).
- Record `../diagnostics/cc5.3-desktop-v4-build.json`.

The firmware package and its gate evidence are unaffected: no firmware file changed. The exe's embedded modules (`control_center.*` and
`protocol`, 15) equal the current sources (read-only PYZ comparison; the exe was not run).
`desktop-dist-v3` (1,161 files, exe `90A23552...`) and `desktop-dist-v2` (1,097 files) matched
their SHA-256 listings (`../diagnostics/cc5-desktop-dist-v3-sha256.json`,
`../backups/source-snapshots/desktop-dist-v2-sha256.json`) before and after the build. Not
installed; the frozen smoke test is step 1's.

## Gate evidence

Each file's SHA-256 at packaging time is recorded in `manifest-1.0.0-cc5.3.json` under
`gates`: `../diagnostics/cc5.3-build.json`, `work/nanod-cc5.3-build.log`, every
`cc5-stage*cc5.3*`, `cc5.3-stage*` and `cc5.3-*-report.json` gate record present, and
`../diagnostics/cc5-led-hue-report.json` (the LED hue report keeps its cc5 name: the gate run
rewrites it, and the LED model is unchanged in cc5.3). The
verification required before the hardware window is ARTWORK2.md section 10: the companion
suite (non-Tk modules), frame parser parity with the `iconKey` cases, store parity
(`harness/media_store_traces.json` through the C++ store and the Python FakeKnob), the
JPEG glue (PSNR >= 40 dB, progressive, oversize and non-240 JPEGs rejected), the LVGL harness
with the new checks, the transport model, `light_tests.py` (2174149 checks, unchanged) and the
PlatformIO build under `0x140000`. `tests/test_cc5_tooling.py` covers this tooling (profiles,
backup locks, prepare, every install exit, rollback to cc5.2 and to cc4, package, finalize and
the artwork2 check gates) with fakes only.

| Gate | Evidence |
|---|---|
| 1.0.0-cc5.3 Stage 9 pre-build gates (2026-09-24, 08:18:19-08:20:14 UTC; no device, no COM port, no USB, no upload, no git writes, no Tk window, no network; the running companion kept PID 27784; `manifest.json` and the source tree unchanged during the run) | `../diagnostics/cc5-stage9-cc5.3-prebuild-gates.log` (59,166 B, SHA-256 `63875b85936c3fe2c2da9b7aada363293d23fd5a678e12dc1b9992278db2afbd`), ALL PASSED: `cpp11_gate.py` (7 C++ units, 5 C font units, firmware source rules over 86 files), `led_wire_tests.py` (87 checks, 200 random frames), `light_tests.py` (2174149 checks, unchanged), `parse_tests.py` (256 parser cases incl. the `iconKey` cases), `font_tests.py`, `media_tests.py` (store parity: 19 cases, 442 media acks, 1581 parity checks, 289 direct checks, 1141 `control_center.cpp` wiring checks), `jpeg_tests.py` (section 10 rule `decoder-rgb888` met: 42 samples, 25 accepted, 17 rejected incl. progressive, oversize and non-240; glue exact; worst decoder PSNR 43.14 dB; worst ROM work area 3096 B), a fresh session capture (old file deleted first; 1,064,589 B) and `parse_tests.py --frames` on it (656 frame lines accepted, cc4 parser 225), `build.py cc5-handoff` + `cc5_report.py` (30/30), `make_cc5_frames.py --check`, the 29 non-Tk companion modules (1105 tests, 0 failures, 0 errors, 0 skipped; Tk, serial ports, browsers and hardware scripts blocked), and the PlatformIO build (`[SUCCESS]`, 1,023,648 B, magic `0xE9`, `1.0.0-cc5.3` present, `1.0.0-cc5.2` absent, SHA-256 `f1cd05a2...`) |
| 1.0.0-cc5.3 build and package (2026-09-24) | `work/nanod-cc5.3-build.log`, `../diagnostics/cc5.3-build.json`, `manifest-1.0.0-cc5.3.json` (see the package table). Its `gates` record the gate log above, `diagnostics/cc5.3-build.json` (SHA-256 `43484adb...`), `diagnostics/cc5-led-hue-report.json` (21,799 B, SHA-256 `aa86b4648c7b880d437f8954638b50dcad85e6e606c08a917e7c16f6649e6f5d`, rewritten by the gate run's companion suite) and `work/nanod-cc5.3-build.log` (SHA-256 `5fb2f091...`) |
| Desktop v4 build (not installed) | `../diagnostics/cc5.3-desktop-v4-build.json`, `../diagnostics/cc5.3-desktop-dist-v4-sha256.json` (see the desktop build above) |
| Deferred to the hardware window | the four Tk modules (`test_cc_icons`, `test_cc_ui`, `test_cc_windows`, `test_standalone`) with the whole suite in step 10, the frozen v4 smoke test in step 1, and every device gate of steps 7-8 |

## Hardware window (Stage 10)

### Go-ahead first

Nothing below runs without the user's explicit go-ahead. The request to the user includes the
rollback commands in [Rollback and abort](#rollback-and-abort) and RECOVERY.md section 6. It
also asks the user either to confirm physical BOOT/RESET access on the enclosure or to accept
explicitly that it is unestablished (RECOVERY.md section 2).

The request states the **stress+turn hard gate** of step 8b: the user must be at the knob and,
when `check_nanod_cc5.py` prints `Turn the knob continuously now for 60 s` (with a beep: step
8b sets the opt-in `NANOD_AUDIBLE_CUES=1`), turn it back and forth until `Stop turning` appears.
The untouched pass before it needs the knob left alone. Fewer than 20 claimed position events
inside the stress+turn frame window, or a pause over 3 s in it, fails 8b as "turning not
detected during stress; rerun" (rerun 8b and keep turning; turning only during the cold
transfers before the stress does not count). In cc5.3 both stress passes write their media
traffic unpaced through artwork2 (covers, icons, `have`, prefetch) and last at least 20 s each;
the untouched pass first replays the cc5.2 stress itself (about 300 frames interleaved with
paced v1 art, as the v3 companion sends it; about 33 s on cc5.2), so it runs longer than the
stress+turn pass.

It states the **unattended soak gate** of step 8b: right after `Stop turning`, 20 minutes of
companion-like traffic with nobody at the knob (changed frames and heartbeats, artwork2 covers,
icons, `have` and prefetch unpaced, a paced v1 art transfer every fourth artwork slot, layout
and LED-style switches, flashes, a release and a new control every 30 s) with a `diag`
checkpoint every 10 s. So 8b takes about 30 minutes. Every `diag` checkpoint fails on a task
age over 1000 ms, an LED transmit timeout or driver error, or a forced release. A failed soak
or liveness check is a NO-GO (never a rerun), like a reboot.

It states the **artwork2 gates** of step 8b: the capability equals the contract, the v4
DeviceBridge negotiates it and delivers a cover and an icon, v1 art still works paced (the v3
companion), cover and icon round trips with begin-hit and `have`, prefetched keys kept and
decoded at once when named, the frame's key pinned while the store overflows, every reachable
error string, every media ack within 1.5 s and every cover within 1.5 s unpaced, and
`jpegDecodeMsMax` <= 200 ms (raised from 150 ms on 2026-09-24, ARTWORK2.md 12.11) with `jpegDecodeErrors` 0. `finalize_nanod_cc5.py` refuses cc5.3
without every one of them. The request also says the knob now runs cc5.2, that step 4 makes a
new full backup (NVS and the filesystem may have changed since the cc5.2 install), and that
the rollback returns exactly those bytes.

### Ports, interpreters and evidence

Every script discovers its ports itself; none contains a COM number, and each aborts unless
exactly one port matches:

- **Application port:** `239A:8010`, serial `NANO_D`, compared case-insensitively.
- **ROM port:** `303A:1001`, serial `12:34:56:78:9A:BC`.

| Name | Path | Steps |
|---|---|---|
| `$flash`: flash venv, esptool 4.12.0 | `<repo>\tools\nanod-flash-venv\Scripts\python.exe` | 3, 4, 5, 6, abort (`$flash`) and firmware rollback (`$flashPython`, as in RECOVERY.md) |
| `$app`: companion venv | `<repo>\app\.venv\Scripts\python.exe` | 2, 7, 8, 10 |

Each block sets the interpreter it runs to the absolute path above and sets
`$global:LASTEXITCODE = -1` before every native command, so a command that did not run can
never pass its exit-code check. Two sets of variables carry evidence from one step to a later
one, only in the PowerShell window that set them: `$beforeInventory` (step 2 to step 5) and
`$demo`, `$dataDir`, `$stamp` and `$dataHashesBefore` (9a to 9b). The later step refuses to
run without them.

Evidence goes to `<repo>\app\diagnostics`
under cc5.3's own names (`cc5.3-backup.json`, `cc5.3-preparation.json`,
`cc5.3-flash-checks.json`, `cc5.3-device-checks.json`, `cc5.3-lease-checks.json`,
`cc5.3-installation.json`, `cc5.3-rollback.json`); the scripts rename older cc5.3 evidence and
never overwrite it, and never touch the cc5.2 records (`cc5-*.json`).

Each step block is wrapped in `. { ... }`, so the first `throw` stops the block:

- `GO: ...` (the block's last line): go on to the next step.
- `NOT RUN: ...`: the block stopped before it changed anything. Fix what the message names and
  run the same block again. This is never a reason for a rollback.
- `NO-GO: ...`: stop, and do what that step's **No-go** line says.

### Step 1. Quit the companion, disable its task, smoke-test the v4 build

Interpreter: none (PowerShell and the frozen v4 executable
`<repo>\app\desktop-dist-v4\NanoDControlCenter\NanoDControlCenter.exe`).

Quit the companion from its tray icon (**Quit**). Do not use `Stop-Process` or `taskkill`:
Quit releases the knob cleanly. Then disable the `NanoD Control Center` task for the whole
window, so v3 cannot relaunch, and run the smoke test:

```powershell
. {
  Disable-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop | Out-Null
  if ((Get-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop).State -ne 'Disabled') { throw 'NOT RUN: the startup task is not disabled' }
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: NanoDControlCenter is still running; quit it from the tray' }
  $v4 = '<repo>\app\desktop-dist-v4\NanoDControlCenter\NanoDControlCenter.exe'
  $smokeJson = Join-Path $env:LOCALAPPDATA 'NanoDControlCenter\logs\smoke-test.json'
  $smokeStart = (Get-Date).ToUniversalTime()
  $smoke = Start-Process -FilePath $v4 -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru -Wait
  if ($smoke.ExitCode -ne 0) { throw "NO-GO: the frozen smoke test exited $($smoke.ExitCode)" }
  $report = Get-Content -Raw -LiteralPath $smokeJson -ErrorAction Stop | ConvertFrom-Json
  $written = (Get-Item -LiteralPath $smokeJson).LastWriteTimeUtc
  if ($report.pid -ne $smoke.Id -or $written -lt $smokeStart) { throw 'NO-GO: smoke-test.json is not from this run (pid or time differ)' }
  if ($report.passed -ne $true -or $report.frozen -ne $true -or $report.executable -ne $v4) { throw 'NO-GO: smoke-test.json reports a failed check or another executable' }
  "GO: smoke test pid $($smoke.Id) exit 0, smoke-test.json written $($written.ToString('o'))"
}
```

Go: the startup task is disabled, no `NanoDControlCenter` process runs, the v4 smoke test
exits 0, and `smoke-test.json` carries this run's pid, a time after the start, `passed` and
the v4 path.

No-go: nothing touched the knob. [Re-enable the companion](#re-enable-the-companion) and stop;
the v4 build needs fixing before any hardware step.

### Step 2. Pre-flash inventory (cc5.2, presentation 4)

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
  if ($inventory.settings.firmwareVersion -ne '1.0.0-cc5.2' -or $inventory.capabilities.presentation -ne 4 -or @($inventory.profiles.PSObject.Properties).Count -ne 10) { throw 'NO-GO: the knob is not cc5.2 with presentation 4 and ten profiles' }
  $beforeInventory = $name
  "GO: before-inventory $beforeInventory (1.0.0-cc5.2, presentation 4, ten profiles)"
}
```

Go: `backups\control-center-inventory-*.json` reports `1.0.0-cc5.2`, presentation 4 and ten
saved profiles. `$beforeInventory` holds the file name for step 5.

No-go: nothing was sent that changes the knob, and it still runs cc5.2.
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

The script sends one 1200-bps open with DTR false, then closes, and polls for `303A:1001` with
the chip MAC as its serial. It refuses, sending nothing, while the companion runs. Evidence:
`diagnostics\cc5-usb-boot-entry*.json` (one shared, never-overwritten name for every cc5.x
window; finalize treats an entry after the install as a rollback).

Go: exit 0 and `ROM bootloader: COM<n> (serial 12:34:56:78:9A:BC)`. Nothing is written.

No-go: nothing was written. If the message says the companion is running, it is a `NOT RUN`.
If the touch was sent but no ROM port appeared, list ports: when the application port is back,
cc5.2 is running, so [re-enable the companion](#re-enable-the-companion) and stop; when a
MAC-matched ROM port is present, use [Abort before any write](#abort-before-any-write); when
neither appears, see RECOVERY.md section 2.

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
  $backup = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5.3-backup.json' -ErrorAction Stop | ConvertFrom-Json
  if ($backup.passed -ne $true -or $backup.identityVerified -ne $true -or $backup.verifiedAgainstDevice -ne $true -or $backup.bytes -ne 4194304 -or $backup.fromImageAtApp0 -ne $true -or $backup.fromImageSha256 -ne '45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572' -or $backup.file -ne 'nanod-cc5.2-before-cc5.3-full.bin') { throw 'NO-GO: cc5.3-backup.json is not a verified 4 MB backup with cc5.2 at app0' }
  "GO: backups\nanod-cc5.2-before-cc5.3-full.bin, 4,194,304 B, sha256 $($backup.sha256), role $($backup.role)"
}
```

Go: exit 0, and `cc5.3-backup.json` shows the MAC and 4MB identity, 4,194,304 B verified
against the device, the cc5.2 image at app0, and `nanod-cc5.2-before-cc5.3-full.bin` as the
backup. The first run's `role` is `pre-cc5.3 backup`: a fresh read, never a copy of the cc5.2
install image, because NVS and the filesystem may have changed since.

No-go: nothing was written; use [Abort before any write](#abort-before-any-write). Exit 3
means the read was kept as a diagnostic read (`backups\nanod-diagnostic-full-<UTC>.bin`,
`cc5.3-backup-diagnostic-read-<UTC>.json`): after a cc5.3 write the pre-cc5.3 backup is locked
and a read is accepted only when it is byte-identical to it (role `current backup (identical to
the locked pre-cc5.3 backup)`, the read kept as `nanod-cc5.2-confirm-read-<UTC>.bin`), or its app0
does not hold cc5.2. Inspect with the user after the abort.

`backup_nanod_cc5.py` never replaces the pre-cc5.3 backup once it is a rollback input: when any
`cc5.3-flash-checks*.json` records a write attempt, a `cc5.3-rollback*.json` exists, or
`manifest-1.0.0-cc5.3.json` is no longer `UNFLASHED`. The cc5.2 history pair
(`nanod-cc4-before-cc5-full.bin`, `nanod-cc4-before-cc5-active-app.bin`) and the cc5.2 records
are never written, renamed or read as this backup's state. A failed run never replaces
`cc5.3-backup.json`; its record is `cc5.3-backup-failed-<UTC>.json`.

### Step 5. Prepare (host only)

Interpreter: `$flash`. Script:
`<repo>\tools\prepare_nanod_cc5_install.py
--before-inventory <step 2 file>`. It reads files only; the knob stays in the ROM bootloader.

```powershell
. {
  if (-not $beforeInventory) { throw 'NOT RUN: $beforeInventory is not set in this window; set it to the file name on the GO line of step 2, then run step 5 again' }
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flash '<repo>\tools\prepare_nanod_cc5_install.py' --before-inventory $beforeInventory
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: prepare stopped; nothing was written' }
  $prep = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5.3-preparation.json' -ErrorAction Stop | ConvertFrom-Json
  $rollbackHash = (Get-FileHash -Algorithm SHA256 -LiteralPath '<repo>\app\backups\nanod-cc5.2-before-cc5.3-active-app.bin' -ErrorAction Stop).Hash
  if ($prep.activeApp -ne 'app0' -or $prep.applicationOffset -ne 0x10000 -or $prep.applicationSize -ne 0x140000 -or $prep.partitionTableUnchanged -ne $true -or $prep.otaSelectionUnchanged -ne $true) { throw 'NO-GO: the layout is not app0 at 0x10000/0x140000 with the original partition table and OTA data' }
  if ($prep.rollbackStartsWithFromImage -ne $true -or $prep.fromImageSha256 -ne '45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572' -or $prep.rollbackBytes -ne 1310720 -or $rollbackHash -ne $prep.rollbackSha256) { throw 'NO-GO: the rollback app0 is not the verified cc5.2 app0' }
  "GO: rollback app0 sha256 $($prep.rollbackSha256); expected image sha256 $($prep.expectedSha256)"
}
```

Go: the partition table and OTA data equal the original backup, OTA selects app0 at
`0x10000`/`0x140000`, app0 holds the cc5.2 image and equals the app0 the cc5.2 install verified
(`nanod-cc5.2-expected-full.bin`), `manifest.json` is the cc5.2 record (`manifest-cc5.2.json`),
and `backups\nanod-cc5.2-before-cc5.3-active-app.bin` (1,310,720 B) matches `rollbackSha256`.
`backups\nanod-cc5.3-expected-full.bin` is the backup with cc5.3 at app0 and the rest of its
last 4 KB sector erased.

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

`install_nanod_cc5.py` runs every step before the final reset with `--baud 460800 --before
no_reset --after no_reset_stub`, so the stub session is kept throughout, as in the proven cc5.2
install:

1. `flash_id`: MAC and 4MB.
2. `verify_flash 0x0` against the fresh backup.
3. `write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000` with the cc5.3 image.
4. `verify_flash 0x0` against the prepared expected image.
5. Only then `read_mac --after hard_reset`.

It never uses `erase_flash`, a filesystem upload, a PlatformIO upload or a full-image write.
If step 3 or 4 fails, or anything unexpected happens after the write starts, it does **not**
reset: in the same stub session it writes the cc5.2 active-app backup at `0x10000`, verifies
app0, verifies the full image against the fresh backup, and resets only after all three pass.

The exit code and the `outcome` in `diagnostics\cc5.3-flash-checks.json` agree:

| Exit | Outcome | Meaning | Go / no-go |
|---|---|---|---|
| 0 | `INSTALLED_VERIFIED_RESET` | cc5.3 written, full 4 MB verified, reset confirmed. | GO: step 7. |
| 5 | `INSTALLED_VERIFIED_RESET_UNCONFIRMED` | cc5.3 verified in flash; the reset was not confirmed. | Run only the printed `read_mac --after hard_reset` command, once. Then GO: step 7. At step 10, add `--accept-unconfirmed-reset`. |
| 1 | none | Nothing was sent: wrong environment, an input file's SHA-256, or not exactly one ROM port. | NO-GO: [Abort before any write](#abort-before-any-write). |
| 2 | `STOPPED_BEFORE_WRITE` | Identity or pre-write verify failed (or a usage error). Nothing written, no reset. | NO-GO: [Abort before any write](#abort-before-any-write). |
| 3 | `RESTORED_CC5_2_RESET` | cc5.3 failed; cc5.2 restored and verified, then reset. | NO-GO: cc5.2 runs again. [Re-enable the companion](#re-enable-the-companion) and stop. |
| 6 | `RESTORED_CC5_2_VERIFIED_RESET_UNCONFIRMED` | cc5.3 failed; cc5.2 restored and verified; the reset was not confirmed. | Run only the printed command, once. Then as exit 3. |
| 4 | `RESTORE_FAILED_NO_RESET` | The restore did not verify. The chip was **not** reset. | NO-GO: do not reset, unplug or power-cycle. [Firmware rollback](#firmware-rollback-cc53---cc52) (scripted) now. |
| -1 | none | The script did not run (the block's own marker). | NOT RUN: nothing was sent; fix the interpreter path and run step 6 again. |
| Any other | `STARTED` or none | The script was interrupted (for example with Ctrl+C). | NO-GO. Open `diagnostics\cc5.3-flash-checks.json`: if `writeAttempted` is true, or the file is missing or older than this run, do not reset; [firmware rollback](#firmware-rollback-cc53---cc52) (scripted). Otherwise [Abort before any write](#abort-before-any-write). |

A reset counts as confirmed only when esptool exits 0, names the chip MAC and prints its
hard-reset line.

### Step 7. Boot sanity (no companion)

Interpreter: `$app` (port listing only; no port is opened).

Watch the knob: the native screen must come up and stay for at least 30 s, with no reboot
loop. Then:

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

Go: one `239A:8010` (`NANO_D`) port enumerated without interruption for 30 s, the native
screen seen for at least 30 s, and no companion process.

No-go (unstable port, no native screen or a reboot loop):
[firmware rollback](#firmware-rollback-cc53---cc52). If neither the application port nor the
ROM port appears, write nothing and see RECOVERY.md section 2. A running companion is a
`NOT RUN`, never a reason for a firmware rollback.

### Step 8. Post-flash checks

Interpreter: `$app` for all three. The companion stays quit: each block first refuses with
`NOT RUN` while a `NanoDControlCenter` process exists, and the check scripts refuse on their
own before they write any evidence.

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
  if ($after.settings.firmwareVersion -ne '1.0.0-cc5.3' -or $after.capabilities.presentation -ne 4 -or $after.capabilities.artwork2.version -ne 1 -or $after.capabilities.artwork2.available -ne $true -or @($after.profiles.PSObject.Properties).Count -ne 10) { throw 'NO-GO: the knob is not cc5.3 with presentation 4, artwork2 and ten profiles' }
  $afterName = $name
  "GO: $afterName (1.0.0-cc5.3, presentation 4, artwork2, ten profiles)"
}
```

**8b. Device checks.** Script:
`<repo>\tools\check_nanod_cc5.py`. Leave the knob alone
until the script prints `Turn the knob continuously now for 60 s` (after three beeps and a high
tone); then turn it back and forth until `Stop turning` appears (a low tone). After that the
unattended soak runs for 20 minutes (`UNATTENDED SOAK: 20 min ...`, one progress line every
10 s): you may leave the knob. The block takes about 30 minutes.

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running; quit it from the tray, disable the startup task again (step 1, first two lines), then run this block again' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $env:NANOD_AUDIBLE_CUES = '1'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\check_nanod_cc5.py' --turn-seconds 60 --soak-minutes 20
  Remove-Item Env:NANOD_AUDIBLE_CUES -ErrorAction SilentlyContinue
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: device checks failed; see failures and gates in diagnostics\cc5.3-device-checks.json. If the output above says NanoDControlCenter is running, it is NOT RUN instead (no evidence was written): quit it, disable the startup task again and run 8b again. If the only failures are turning not detected or a touched untouched pass, run 8b again and turn only when prompted. A stalled task, LED transmit failure, forced release, failed soak or failed artwork2 check is never a rerun' }
  'GO: diagnostics\cc5.3-device-checks.json passed'
}
```

It works in two parts, with reboot detection throughout (as in cc5.2: `diag` at the start and
after every section and every 10 s in the soak, a port watcher, and Windows' LastArrivalDate
whenever no raw control is claimed; any reboot or re-enumeration prints `!!! REBOOT OR USB
RE-ENUMERATION DETECTED`, and every `diag` is also a task-liveness checkpoint):

- **DeviceBridge part (the v4 companion's own code):** inventory and capabilities (presentation
  4, `artwork` unchanged, `artwork2` equal to `control_center/presentation.py`'s
  `ARTWORK2_CAPABILITY`, `glyphs`, `diag`), saved profiles identical and only
  `firmwareVersion` changed against the step 2 inventory, the four controls, v4 frames in both
  LED styles, and **bridgeArtwork2**: the bridge negotiates artwork2 and a 240 px JPEG cover and
  an app icon pushed with `set_media_wanted` become `media-ready`, also when a new selection
  preempts the previous one.
- **Raw serial part:** v2 frames; stale frame and stale control; **v1 art, paced** like the v3
  companion (round trip, cache hit, CRC mismatch, stale id/key, mid-transfer change, parse
  cases); **mediaRoundTrip** (cover and icon, cold then begin-hit, `have`); **mediaPrefetch**
  (three non-current covers accepted and kept, one then named by a frame: a begin-hit decoded
  within 1.5 s, `jpegDecodeMsLast` <= 200 ms; the same for an icon); **mediaPinning** (26 more
  covers and 50 more icons: the frame's keys and the newest stay, the two oldest are evicted,
  `mediaEvictions` grows); **mediaErrors** (every reachable ARTWORK2.md 4.3 error string, the
  identical retry, `mediaErrors` counting exactly those replies; `Media unavailable` is not
  reachable without a failed PSRAM allocation and is recorded as such); **mediaTiming** (five
  cold covers and five icons unpaced: per-line ms, seconds per cover); the cold v1 transfer
  timing and its three replays; **stress, untouched**: first the cc5.2 stress with paced v1 art
  (the 1.0.0-cc5 run-1 sequence as the v3 companion sends it, evidence `sections.stress.v1`),
  then, like **stress+turn**, unpaced through artwork2, at least 300 frame updates and 20 s
  each, zero errors, no release, every transfer committed, `have` never missing a recent cover; the **unattended soak** with artwork2 traffic
  and a paced v1 transfer every fourth slot; and **diag** (LVGL heap and stacks, the internal heap's minimum since boot `heapMinFree` >= 40000 B
  (cc5.2 measured 79692 B; the evidence records the delta), `txStalls`
  0, `jpegDecodes` > 0, `jpegDecodeErrors` 0, `jpegDecodeMsMax` <= 200 ms, `mediaCommits` > 0).

Every run builds its own covers and icons (the design reference assets through the section 5
pipeline, with a small run-specific stamp): the knob keeps committed media until it reboots, so a
rerun of 8b on the same boot uploads cold again instead of finding the first run's keys.

The evidence's `gates` object must be all true for step 10: `stressUntouched`, `stressTurn`,
`turningDetected`, `noRebootOrReenumeration`, `rebootFieldsReported`, `coredumpBlank`,
`rxQueueInternal`, `diagMargins`, `taskLiveness`, `unattendedSoak`, `artwork2Capability`,
`bridgeArtwork2`, `v1ArtCompatible`, `mediaRoundTrip`, `mediaPrefetch`, `mediaPinning`,
`mediaErrorStrings`, `unpacedTransferTiming` and `jpegDecode`.

**8c. Lease checks.** Script:
`<repo>\tools\check_nanod_cc5_lease.py`. Turn the knob
during the native observation.

```powershell
. {
  if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the companion is running; quit it from the tray, disable the startup task again (step 1, first two lines), then run this block again' }
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\check_nanod_cc5_lease.py' --observe-native-seconds 10
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: lease checks failed; see failures in diagnostics\cc5.3-lease-checks.json. If the output above says NanoDControlCenter is running, it is NOT RUN instead (no evidence was written): quit it, disable the startup task again and run 8c again' }
  'GO: diagnostics\cc5.3-lease-checks.json passed'
}
```

It checks: the lease expires about 2 s after ready; art packets alone do not renew it; **media
lines alone (unpaced) do not renew it**; frames continue through art transfers and **through
unpaced cover and icon uploads** lasting several lease periods (a frame before each upload and
frames inside each open upload, which must neither be refused nor end it: `framesInsideUploads`
above 0, every upload committed); after a host-lost expiry the
claim is released (stale frame, native knob events, re-entry, intentional release; confirm by
eye that the LCD shows "NANO_D++ / Waiting for PC / Native controls active"); no reboot; and
task liveness at both `diag` replies. Its `artwork2` object (`mediaOnlyDoesNotRenew`,
`framesDuringMediaTransfers`) must be all true for step 10.

Go: all three exit 0.

No-go: stop and decide with the user between investigating on cc5.3 (the companion stays quit
while you investigate) and the [firmware rollback](#firmware-rollback-cc53---cc52). A reboot or
re-enumeration is always this no-go, never a rerun: keep `diagnostics\cc5.3-device-checks.json`
(its `rebootWatch.postDropDiag` holds the reset reason and the breadcrumbs); a `task_wdt` reset
means a task stalled for 10 s (keep the core dump; never erase it). A stalled task, an LED
transmit failure, a forced release, a failed soak or a failed artwork2 gate is the same no-go.
Do not finalize. A running companion is a `NOT RUN`, never a reason for a firmware rollback. If
you stay on cc5.3 without finalizing, [re-enable the companion](#re-enable-the-companion): the
installed v3 companion works with cc5.3 through the unchanged v1 art path.

### Step 9. Install the desktop app (v4)

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
  $programBackup = "$demo\backups\desktop-program-before-cc5.3-$stamp"
  Copy-Item -LiteralPath $programs -Destination $programBackup -Recurse -ErrorAction Stop
  if (@(Get-ChildItem -LiteralPath $programBackup -File -Recurse).Count -ne @(Get-ChildItem -LiteralPath $programs -File -Recurse).Count) { throw 'NO-GO: the program folder copy is incomplete' }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath "$programBackup\NanoDControlCenter.exe" -ErrorAction Stop).Hash -ne '90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19') { throw 'NO-GO: the installed exe is not the recorded v3 companion' }
  foreach ($name in 'desktop-installation.json', 'desktop-startup-task.xml', 'desktop-user-data.json', 'native-desktop-verification.json') {
    $old = "$demo\diagnostics\$name"
    $keep = "$demo\diagnostics\" + [IO.Path]::GetFileNameWithoutExtension($name) + "-before-cc5.3-$stamp" + [IO.Path]::GetExtension($name)
    if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $keep -ErrorAction Stop }
  }
  $hashes = @(Get-FileHash -Algorithm SHA256 -LiteralPath "$dataDir\credentials.bin", "$dataDir\settings.json" -ErrorAction Stop | Select-Object @{n = 'file'; e = { Split-Path -Leaf $_.Path } }, @{n = 'sha256'; e = { $_.Hash } })
  $hashes | ConvertTo-Json | Out-File -NoClobber -Encoding utf8 -LiteralPath "$demo\diagnostics\cc5.3-desktop-data-sha256-before-$stamp.json" -ErrorAction Stop
  $dataHashesBefore = $hashes
  "GO: program folder kept as $programBackup; data hashes recorded"
}
```

The installer overwrites `desktop-installation.json` and `desktop-startup-task.xml` and
recreates `desktop-user-data.json`; `Verify-NativeDesktop.ps1` overwrites
`native-desktop-verification.json`. 9a keeps the v3-era copies as `*-before-cc5.3-<UTC>`.

No-go (9a): nothing was installed, and v3 is still installed; it works with cc5.3 (v1 art).
[Re-enable the companion](#re-enable-the-companion) and decide with the user.

**9b. Forward install with `-Mirror`.** `-Mirror` removes program files that v4 no longer
ships, so the installed folder matches `desktop-dist-v4` exactly. The installer verifies every
file hash, never overwrites existing user data, and re-registers the startup task (enabled, with
its sign-in trigger; nothing starts until 9c).

```powershell
. {
  if (-not ($demo -and $dataDir -and $stamp -and $dataHashesBefore)) { throw 'NOT RUN: run 9a in this window first; nothing was installed' }
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v4 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: Install-Desktop.ps1 failed; use the desktop rollback' }
  $dataHashesAfter = @(Get-FileHash -Algorithm SHA256 -LiteralPath "$dataDir\credentials.bin", "$dataDir\settings.json" -ErrorAction Stop | Select-Object @{n = 'file'; e = { Split-Path -Leaf $_.Path } }, @{n = 'sha256'; e = { $_.Hash } })
  $dataHashesAfter | ConvertTo-Json | Out-File -NoClobber -Encoding utf8 -LiteralPath "$demo\diagnostics\cc5.3-desktop-data-sha256-after-$stamp.json" -ErrorAction Stop
  if (Compare-Object $dataHashesBefore $dataHashesAfter -Property file, sha256) { throw 'NO-GO: credentials.bin or settings.json changed during the install' }
  $installed = Get-Content -Raw -LiteralPath "$demo\diagnostics\desktop-installation.json" -ErrorAction Stop | ConvertFrom-Json
  $bundleHash = (Get-FileHash -Algorithm SHA256 -LiteralPath "$demo\desktop-dist-v4\NanoDControlCenter\NanoDControlCenter.exe" -ErrorAction Stop).Hash
  if ($installed.sha256 -ne $bundleHash) { throw 'NO-GO: the installed exe is not the v4 bundle' }
  "GO: v4 installed ($bundleHash); user data hashes unchanged"
}
```

No-go (9b): [desktop rollback](#desktop-rollback-v4---v3). A change in the user data hashes
also needs the user: the installer never writes existing user data, so something else did.

**9c. Re-enable and start the task, then verify.** This block sets its own paths, so it also
runs in a new window after 9b.

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
  if ($status.ready -ne $true -or $status.connected -ne $true -or $status.firmwarePresentation -ne 4 -or $status.artwork2 -ne $true -or $status.dataDir -ne $dataDir) { throw 'NO-GO: status.json is not ready on presentation 4 with artwork2 and the real data folder' }
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

Go: one process from the install path, a `status.json` written by that process after the start
(ready, connected, presentation 4, `artwork2` true, the real data folder), a `Device ready` line
in `app.log` since the start, and `Verify-NativeDesktop.ps1` passing its read-only Apple Music
check.

No-go (9c): quit the companion from its tray icon, then
[desktop rollback](#desktop-rollback-v4---v3).

### Step 10. Finalize (records only)

Interpreter: `$app`. Script:
`<repo>\tools\finalize_nanod_cc5.py`. It touches no
device, network or desktop, and checks everything before it writes anything.

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
running the block at all. The light count, 2174149, is the `PASS: 2174149 light-renderer
check(s)` line of the `light_tests.py` gate (the logical LED model is unchanged in cc5.3). Type
it without separators; a comma would make PowerShell pass a list. Replace it only if a later
`light_tests.py` gate ran.

```powershell
. {
  $app = '<repo>\app\.venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $app '<repo>\tools\finalize_nanod_cc5.py' --companion-tests <suite-tests> --light-assertions 2174149
  if ($LASTEXITCODE -ne 0) { throw 'NO-GO: finalize refused (see its STOP line); nothing was recorded' }
  $firmware = '<repo>\app\firmware'
  if ((Get-FileHash -LiteralPath "$firmware\manifest.json").Hash -ne (Get-FileHash -LiteralPath "$firmware\manifest-1.0.0-cc5.3.json").Hash) { throw 'NO-GO: manifest.json is not the cc5.3 record' }
  'GO: cc5.3 recorded as INSTALLED'
}
```

After install exit 5, add `--accept-unconfirmed-reset` to the finalize line. Without it, only
outcome `INSTALLED_VERIFIED_RESET` is accepted.

Finalize requires `cc5.3-flash-checks.json` with a verified install, and
`cc5.3-device-checks.json` and `cc5.3-lease-checks.json` that passed, were written after it,
and show `1.0.0-cc5.3` with presentation 4. Every device gate of 8b and both artwork2 lease
cases of 8c must be true; the after-inventory must carry `artwork2` exactly and the unchanged
`artwork`; the before-inventory must be cc5.2; the ten profiles identical. It refuses after any
rollback made or started since the install, by either path and even one that left no record:
a `cc5.3-rollback*.json` or `cc5-rollback*.json`, a `manifest-at-cc5.3-rollback-*.json` or
`manifest-at-cc5-rollback-*.json`, a `backups\cc5.3-manual-rollback-*`,
`backups\cc5-manual-rollback-*`, `backups\cc5.3-rollback-*` or `backups\cc5-rollback-*` folder,
a `cc5.3-rollback-*.log` or `cc5-rollback-*.log`, `backups\nanod-current-partitions.bin`, or a
ROM bootloader entry (`cc5-usb-boot-entry*.json`) from at or after the install. It also refuses
a cc5.3 manifest marked `ROLLED_BACK`, or a `manifest.json` that is not the record its status
requires (the cc5.2 record `manifest-cc5.2.json` for the first run). On success it writes
`diagnostics\cc5.3-installation.json`, marks `manifest-1.0.0-cc5.3.json` `INSTALLED`, copies it
byte-identically to `manifest.json`, and updates `diagnostics\validation.json` under `cc5.3`,
keeping the old one as `validation-before-cc5.3.json`. Last, it marks `manifest-1.0.0-cc5.2.json`
`SUPERSEDED` (`statusBeforeSupersede` `INSTALLED`, `installedRecord` `manifest-cc5.2.json`; the
previous file is kept byte-identical as `manifest-1.0.0-cc5.2.superseded-<UTC>.json`), only
while it is `INSTALLED` and byte-identical to `manifest-cc5.2.json`. The other cc5.2 records
(`manifest-cc5.2.json`, `cc5-*.json`) stay as they are.

Go: `GO: cc5.3 recorded as INSTALLED`.

No-go: finalize wrote nothing, and the knob and the desktop app keep working as they are. Fix
what the STOP line names and run step 10 again. Never roll back because of a finalize refusal
alone. If the STOP line names a rollback or a bootloader entry after the install, cc5.3 cannot
be recorded from this install's evidence: decide with the user.

Physical acceptance (Stage 11: 240 px covers, app icons, instant prefetched covers) is
separate. Nothing above claims it.

## Rollback and abort

### Abort before any write

Use this for a NO-GO in steps 3-5, or install exit 1 or 2. Nothing was written, so cc5.2 is
intact and a reset is safe. If the knob is in the ROM bootloader, leave it with the read-only
reset (interpreter `$flash`). The block verifies app0 against the cc5.2 image first
(read-only) and resets only when that verify passes.

```powershell
. {
  $flash = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flash -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.find_rom_port())"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'Exactly one MAC-matched ROM port is required; nothing was reset. If 239A:8010 (NANO_D) is present, cc5.2 is already running' }
  $global:LASTEXITCODE = -1
  & $flash -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 '<repo>\app\firmware\nanod-control-center-1.0.0-cc5.2.bin'
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not hold the cc5.2 image, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob: run this block again once; if app0 still does not verify, leave the knob in the ROM bootloader and decide with the user (RECOVERY.md section 6, reset rule)' }
  $global:LASTEXITCODE = -1
  $reset = (& $flash -u -m esptool --chip esp32s3 --port $romPort --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed; list ports before trying again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed; list ports before trying again, once' }
  'cc5.2 is restarting. Next: re-enable the companion.'
}
```

Then [re-enable the companion](#re-enable-the-companion). For a NO-GO in steps 1-2 the knob
never left cc5.2: only re-enable the companion.

### Firmware rollback, cc5.3 -> cc5.2

Use this after install exit 4 (without any reset), or for a NO-GO in steps 7-8. Keep the
companion quit; the startup task is still disabled from step 1. Primary path, scripted, with the
flash venv. This block is the same as the scripted block in RECOVERY.md section 6:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false   # this block may write app0
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\nanod_enter_bootloader_v2.py'
  if ($LASTEXITCODE -ne 0) { throw 'No ROM bootloader port; this block sent and wrote nothing. If the message above says the companion is running: quit it from the tray and run this block again. After install exit 4 or a failed rollback write, if no MAC-matched ROM port remains: stop (reset rule). Otherwise fix the cause (section 2) and run this block again' }
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --to cc5.2
  "rollback_nanod_cc5.py --to cc5.2 exit $LASTEXITCODE; act on it with the table below"
}
```

Act on the exit code with the table in RECOVERY.md section 6 (cc5.3: Firmware, scripted). The
bootloader step sends nothing when the ROM port is already present (after install exit 4).
RECOVERY.md section 6 also has the reset and retry rules, the manual esptool fallback and the
checks after the rollback (inventory `1.0.0-cc5.2`, presentation 4, ten profiles). Install exit
4 counts as a started rollback write: from then on, never reset, unplug or power-cycle the knob
except as that section says. `rollback_nanod_cc5.py` without `--to` is the cc5 -> cc4 history
path (RECOVERY.md section 5); once step 6 has written cc5.3 it refuses to run without `--to`
(exit 2, nothing sent). Always pass `--to cc5.2` here; `--to cc4` only if the user decides to go
back two releases to cc4.

### Desktop rollback, v4 -> v3

Use this for a NO-GO in 9b or 9c, or with a firmware rollback when wanted (v4 also works with
cc5.2: it falls back to v1 art with pacing). Quit the companion from its tray icon first, then
install the v3 bundle (exe SHA-256
`90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19`; `Install-Desktop.ps1`
refuses a `desktop-dist-v3` with another exe):

```powershell
. {
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v3 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'The desktop rollback failed; the program folder copy from step 9a is in backups\desktop-program-before-cc5.3-<UTC>' }
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
