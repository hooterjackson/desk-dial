# Application-only recovery for this Nano_D++ kit

The control-center firmware is installed. These are recovery instructions, not a
setup step to repeat during ordinary use. They apply to the verified ESP32-S3
revision 0.1, MAC **12:34:56:78:9A:BC**, with 4MB flash. A different device, changed
partition table, or intervening OTA update requires a fresh inspection before any
write. Never guess a port or application offset.

## Verified originals

Files are under `../backups/` relative to this document:

| File | Size | SHA-256 |
|---|---:|---|
| `nanod-original-full-20260922.bin` | 4,194,304 | `fc131f9366b276cf4bf10cdd8c61d32840f9a61b6ff966a1c323cdf2789d509c` |
| `nanod-original-active-app.bin` | 1,310,720 | `a1981ea2a1c57cf5ff64d0602a54bbad9e7e4f0863931bbdc30541a659f9b51a` |
| `nanod-expected-after-install.bin` | 4,194,304 | `cb2343ee22eb31e9e9fa13f1c4d8093c27b1aebb8b9c75204d94d618c7f56081` |

`nanod-original-manifest.json` records partition hashes and OTA selection.
`nanod-original-partitions.bin` and `.csv` preserve the actual partition table.
The original full image passed a device `verify_flash` digest check before the
installation. After writing, another complete 4MB digest check matched the
expected image above. That expected image differs from the original only in the
candidate bytes and the erased remainder of its last 4KB sector.

| Region | Offset | Size |
|---|---:|---:|
| Partition table | `0x8000` | `0x1000` |
| NVS / calibration | `0x9000` | `0x5000` |
| OTA selection | `0xE000` | `0x2000` |
| **app0: installed and rollback target** | **`0x10000`** | **`0x140000`** |
| app1 | `0x150000` | `0x140000` |
| SPIFFS / saved profiles | `0x290000` | `0x160000` |
| Coredump | `0x3F0000` | `0x10000` |

OTA record sequence 1 selects app0. The second valid record has sequence 0 and
does not win selection. The installation retained both records unchanged.

## 1. Release the companion and identify USB

Disconnect the knob in the companion, then close the companion and any serial
monitor or vendor configuration app. One process must own the serial port.
Open PowerShell in the `nanod-desktop-demo` directory. The following examples use
the isolated recovery environment already installed for this task:

```powershell
$flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
& $flashPython -m esptool version
& $flashPython -m serial.tools.list_ports -v
Get-FileHash -Algorithm SHA256 -LiteralPath '.\backups\nanod-original-active-app.bin'
```

The tool version used successfully was **esptool 4.12.0**. Its newer RAM stub
resolved slow native-USB reads. It is separate from the unchanged firmware build
environment, which uses esptool 4.5.1.

Confirm the rollback file hash above. The application last appeared on **COM8**,
VID `239A`, PID `8010`, serial `NANO_D` (Windows reported it in upper case; compare
it case-insensitively). The ROM bootloader last appeared on **COM9**, VID `303A`,
PID `1001`, serial `12:34:56:78:9A:BC`. Port numbers can change.

## 2. Enter the bootloader once, then rediscover the port

If the matching bootloader is already present, skip the touch. Otherwise, confirm
the application port and issue one 1200-bps open/close, the method declared by the
vendor board configuration. The following command explicitly checks the expected
application identity on the supplied port before touching it; change its final
`COM8` argument only to the application port you just observed:

```powershell
@'
import sys
import serial
from serial.tools.list_ports import comports
port = sys.argv[1]
matches = [p for p in comports() if p.device == port
           and p.vid == 0x239A and p.pid == 0x8010
           and (p.serial_number or "").casefold() == "nano_d"]
if len(matches) != 1:
    raise SystemExit("Matching Nano_D++ application port absent; no reset sent")
handle = serial.Serial()
handle.port, handle.baudrate = port, 1200
try:
    handle.open()
    handle.dtr = False
except (serial.SerialException, OSError) as exc:
    print("Touch ended during USB transition:", type(exc).__name__)
finally:
    if handle.is_open:
        handle.close()
'@ | & $flashPython - COM8
```

Wait for Windows to enumerate the bootloader, then run port listing again:

```powershell
& $flashPython -m serial.tools.list_ports -v
```

Use the newly observed bootloader port below. `COM9` is the verified historical
example, not an automatic choice. Confirm its MAC and flash size with a read-only
identity query:

```powershell
& $flashPython -u -m esptool --chip esp32s3 --port COM9 --before no_reset --after no_reset_stub flash_id
```

Stop if the identity differs or no bootloader appears. Do not repeatedly reset or
treat any of the four front application buttons as BOOT. Their GPIOs are
41/40/45/46, whereas ESP32-S3 BOOT uses GPIO0. Physical BOOT/RESET access on this
enclosure has not been established.

## 3. Confirm the current layout before rollback

Read just the current partition table and compare its SHA-256 with the saved
table. This is read-only on the device:

```powershell
& $flashPython -u -m esptool --chip esp32s3 --port COM9 --before no_reset --after no_reset_stub read_flash 0x8000 0x1000 '.\backups\nanod-current-partitions.bin' --no-progress
Get-FileHash -Algorithm SHA256 -LiteralPath '.\backups\nanod-current-partitions.bin', '.\backups\nanod-original-partitions.bin'
```

Both hashes must match. The known installation leaves OTA selection on app0; if
another firmware update has occurred, inspect its current OTA metadata before
continuing. Keep the complete original backup even though the following rollback
uses only the extracted app0 bytes.

## 4. Restore only app0, verify, then reboot

The next command **writes firmware**. Run it only after the identity, backup hash,
partition layout, and app0 selection checks above. It restores the complete
original app0 partition, without writing bootloader, partition table, OTA
metadata, NVS, SPIFFS, or app1:

```powershell
& $flashPython -u -m esptool --chip esp32s3 --port COM9 --baud 460800 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 '.\backups\nanod-original-active-app.bin'
```

After successful writing, verify the full restored application partition and
return to the application with a hardware reset:

```powershell
& $flashPython -u -m esptool --chip esp32s3 --port COM9 --before no_reset --after hard_reset verify_flash 0x10000 '.\backups\nanod-original-active-app.bin'
```

Rediscover the application port and use `device_inventory.py --port COM8`, with
the observed application port substituted. The original firmware will lack
`controlCenter=1`; the companion should remain unarmed. Confirm the saved profiles
are present. Application-only rollback preserves any legitimate saved settings
changes made since installation; it does not rewind those data partitions.

Do not use `erase_flash`, an erase-all option, a filesystem upload, a generic
PlatformIO upload, or a full-flash write for this rollback. The complete backup is
retained for diagnosis and exceptional recovery, not a blanket write operation.

## 5. cc5 -> cc4 rollback

> Since 1.0.0-cc5.3 this section is the history path back to cc4. For 1.0.0-cc5.3 -> 1.0.0-cc5.2
> use [section 6](#6-cc53---cc52-rollback). `rollback_nanod_cc5.py` without `--to` (as every
> block below runs it) is `--to cc4` only while the records never show cc5.3 written to the
> knob. Once `../diagnostics/cc5.3-flash-checks.json` records a write attempt, or
> `manifest-1.0.0-cc5.3.json` is `INSTALLED` or `ROLLED_BACK`, it refuses to run without `--to`
> (exit 2, a usage error: nothing was sent). To go from cc5.3 two releases back to cc4, add
> `--to cc4` to the script lines below: it restores the cc4 app0 after any cc5.x, marks every
> INSTALLED cc5.x manifest `ROLLED_BACK`, and its evidence names the newest release the records
> show written (`fromVersion`, `writeEvidence`). Its "Leave the bootloader" block verifies the
> cc5.2 image; when cc5.3 is installed, use section 6's instead.

Use this after the cc5 application-only install (`../diagnostics/cc5-flash-checks.json`).
It returns app0 to the exact bytes read from the knob just before cc5 was written. Those
bytes start with the installed cc4 image (`nanod-control-center-1.0.0-cc4.bin`, SHA-256
`89ddf172ffa43bf3e3721868ab5a0d502f906460b5caaa72b15ba67c793be737`).

In this section, cc5 means the cc5 release being installed: **1.0.0-cc5.2**
(`nanod-control-center-1.0.0-cc5.2.bin`, `manifest-1.0.0-cc5.2.json`). The two earlier cc5
builds were both rolled back with the scripted block below on 2026-09-23, each with outcome
`ROLLED_BACK_VERIFIED_RESET` and the full 4 MB then verified identical to the pre-cc5 backup:
1.0.0-cc5 after it reset during its stress check
(`../diagnostics/cc5-rollback.superseded-20260923T213036Z.json`), and 1.0.0-cc5.1 after its
HMI task hung inside `FastLED.show()` (LEDs and buttons frozen, releases never acknowledged;
`../diagnostics/cc5-rollback.json`). Both are superseded and stay in `firmware/` as history.
The two files below serve every cc5 release. The pre-cc5 backup is never replaced after a
cc5 write; `backup_nanod_cc5.py` only confirms that a fresh read is byte-identical to it
(BUILD-cc5.md step 4), so a rollback from 1.0.0-cc5.2 restores exactly the cc4 the knob runs
now.

| File under `../backups/` | Size | SHA-256 recorded in `../diagnostics/cc5-preparation.json` |
|---|---:|---|
| `nanod-cc4-before-cc5-active-app.bin` (rollback app0, `0x10000`-`0x150000` of the read below) | 1,310,720 (`0x140000`) | `rollbackSha256` |
| `nanod-cc4-before-cc5-full.bin` (pre-cc5 full read) | 4,194,304 (`0x400000`) | `beforeSha256` |

Firmware rollback alone is safe to leave in place with the cc5 companion. That
companion reads `presentation` from the knob. Against cc4 (presentation 2) it strips
every v4 field, transliterates text to ASCII and sends no artwork. The knob then
shows text only, with white LEDs, and all four controls keep working. Rolling back
the desktop app is optional.

The scripted rollback (`rollback_nanod_cc5.py`) is the path to use. The manual esptool
blocks are the fallback for when the script itself cannot run: its exit 1 for a cause
in the script or in the cc4 record that cannot be fixed. A cause in the environment (the
flash venv's Python or esptool), a file hash or the ROM port is never a reason for the
manual blocks: they use the same flash venv, and block 1 refuses the same things. Three
rules apply to both paths:

- **Reset rule.** Never reset, unplug or power-cycle the knob yourself once a rollback
  write has started, or after install exit 4 (its restore write failed). app0 may be
  partly written, and physical BOOT/RESET access on this enclosure has not been
  established (section 2). From then on, the only resets are the rollback script's own
  (exit 0), the one command it prints after exit 5, and manual block 4. Block 4 resets
  only when its interlock `$rollbackVerified` says block 2 or block 3 verified the
  rollback in this PowerShell window, and only after it has verified app0 once more
  itself. Any write outside block 2 invalidates that interlock: the scripted block
  clears it before its first command (so does the Quit block, which starts every
  rollback unverified), and after an install run in the same window you start again at
  block 1.
- **Retry rule.** Count every failed rollback write or verify, whichever path it came
  from: script exit 4, block 2 stopping at `write_flash` or the app0 verify, block 3
  stopping, and block 4 finding app0 different from the rollback file. After the first,
  retry once. After the second, stop: leave the knob connected and powered in the ROM
  bootloader, do not reset it, and keep `../diagnostics/cc5-rollback*` and
  `../backups/cc5-manual-rollback-*` for diagnosis. If the ROM port disappears after a
  failed write, stop the same way; never unplug or power-cycle to bring a port back.
- **Nothing written yet.** While cc5 is still verified in app0 (the install ended with
  exit 0 or 5, and no rollback write has started since), a stop that wrote nothing may
  leave the ROM bootloader with the read-only reset in
  [Leave the bootloader without writing](#leave-the-bootloader-without-writing). cc5 then
  starts again. That block does not trust this rule alone: it verifies app0 against the
  cc5 image first and does not reset when app0 differs. After install exit 4, or after
  any counted failure, the reset rule applies instead.

### Quit the companion

Quit the companion from its tray icon (**Quit**). Do not use `Stop-Process` or
`taskkill`: Quit releases the knob cleanly. Then disable the startup task and confirm
that nothing owns the port. The companion is Desk Dial from desktop v7 (task `Desk Dial`,
`DeskDial.exe`) and NanoD Control Center before it or after a desktop rollback, so the block
disables whichever task exists and checks both images. The task has a sign-in trigger and three automatic restarts,
so the block checks that it really is disabled:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false   # a new rollback starts unverified
  foreach ($task in 'Desk Dial', 'NanoD Control Center') {   # Desk Dial from desktop v7; the old name before it or after a desktop rollback
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
      Disable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
      if ((Get-ScheduledTask -TaskName $task -ErrorAction Stop).State -ne 'Disabled') { throw "The startup task '$task' is not disabled; nothing was sent. Disable it, then run this block again" }
    }
  }
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'The companion (DeskDial or NanoDControlCenter) is still running; quit it from the tray, then run this block again. Nothing was sent' }
  'The companion is quit and its startup task is disabled. Next: the scripted block.'
}
```

Every block below sets the interpreter it runs, `$flashPython` (the flash venv with
esptool 4.12.0), to its absolute path. It also sets `$global:LASTEXITCODE = -1` before
each native command, so a command that did not run can never pass its exit-code check.
Every path is absolute, so the working folder does not matter.

### Firmware, scripted (use this first)

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

`nanod_enter_bootloader_v2.py` finds the application port by VID `239A`, PID `8010`
and serial `NANO_D`, compared case-insensitively. It sends one 1200-bps touch, then
waits for the ROM port whose serial is the chip MAC. When that ROM port is already
present and no application port is (for example after install or rollback exit 4), it
sends nothing and exits 0. It refuses, sending nothing, while the companion runs. It
writes `../diagnostics/cc5-usb-boot-entry*.json` and never overwrites an earlier one.

`rollback_nanod_cc5.py` runs only under the flash venv with esptool 4.12.0, on the one
MAC-matched ROM port. Every esptool step uses `--baud 460800 --before no_reset --after
no_reset_stub` until the final reset, as the proven cc4 install did:

1. Checks the file hashes, and that `manifest-cc4.json` is the cc4 record.
2. Runs `flash_id` and requires MAC `12:34:56:78:9A:BC` and 4MB flash.
3. Reads the partition table (`0x8000`, `0x1000`) and the OTA data (`0xE000`, `0x2000`).
   Both must equal the pre-cc5 backup.
4. Writes the rollback file with `write_flash --flash_mode keep --flash_freq keep
   --flash_size keep 0x10000`.
5. Verifies app0 (`verify_flash 0x10000` against the rollback file).
6. Verifies the full 4 MB (`verify_flash 0x0` against the pre-cc5 backup).
7. Only then resets the chip with `read_mac --after hard_reset`. The reset counts as
   confirmed only when esptool exits 0, names the chip MAC and prints its hard-reset line.

If the full verify differs, the script verifies each region on its own. The
bootloader, partition table, OTA data, app0 and app1 must match. Any drift in
`nvs`, `spiffs` or `coredump` is reported and never rewritten: cc5 may have saved
settings there, or written a crash dump.

Once the flash is verified, the script also restores `manifest.json` from
`manifest-cc4.json`, keeping the previous file as `manifest-at-cc5-rollback-<UTC>.json`.
It writes `../diagnostics/cc5-rollback.json`; the `outcome` field there matches the
exit code:

| Exit code | Meaning | Do next |
|---|---|---|
| 0 | cc4 is restored, verified and reset. `manifest.json` is the cc4 record again. | [After the rollback](#after-the-rollback). |
| 1 | Nothing was sent to the device: wrong Python or esptool, a file hash, the cc4 record, or not exactly one MAC-matched ROM port. Usually no evidence file is written. | Fix the cause and run the scripted block again; after a failed write, never by unplugging (reset rule). A wrong Python or esptool, a file hash or the ROM port is never a reason for the manual blocks: they use the same flash venv and block 1 refuses the same causes. Only when the cause is the cc4 record or the script itself, and it cannot be fixed, use the manual blocks. |
| 2 | Identity, partition table or OTA data did not match (or a command-line usage error). This run wrote nothing and did not reset. | Stop and write nothing. Nothing written yet: [leave the bootloader without writing](#leave-the-bootloader-without-writing), [re-enable the companion](#re-enable-the-companion) and inspect the evidence with the user. After install exit 4 or a counted failure: leave the knob in the ROM bootloader and stop (reset rule). |
| 4 | A write or verify failed after the write started. The chip was **not** reset. | Reset rule. First counted failure: run the scripted block once more. Second: stop (retry rule). |
| 5 | cc4 is written and verified and `manifest.json` is restored, but the reset was **not confirmed**. | Run only the `read_mac --after hard_reset` command the script prints, once. If the ROM port is gone and `239A:8010` (`NANO_D`) is present, the chip has already restarted. Then [After the rollback](#after-the-rollback). If that single retry also cannot confirm a reset and the ROM port is still present: because the full image was already **verified**, unplugging the USB cable, waiting 5 s and plugging it back in is a safe reset. This is the only case where a power-cycle is allowed. Then [After the rollback](#after-the-rollback). The same applies to install exit 6 (cc4 restored and verified, reset unconfirmed). |
| 6 | The device rollback verified and reset, but `manifest.json` was **not** restored (`recordsError`). | Fix the cause, then run `rollback_nanod_cc5.py --records-only` (block below). Then [After the rollback](#after-the-rollback). |
| -1 | The script did not run at all (the block's own marker). Nothing was sent. | Fix the interpreter path and run the scripted block again. |
| Any other | The script was interrupted (for example with Ctrl+C). | Open `../diagnostics/cc5-rollback.json`. If `writeAttempted` is true, or the file is missing or older than this run, treat it as exit 4. Otherwise treat it as exit 2. |

This table replaces the script's own last line where they differ. After exit 1 or 2 the
script says cc5 is still in app0; that holds only while nothing has been written (not
after install exit 4 or a counted failure). After exit 4 it points to the manual
commands; run the scripted block once more instead, and use the manual blocks only for
an exit 1 whose cause is the cc4 record or the script itself and cannot be fixed.

```powershell
. {
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --records-only
  if ($LASTEXITCODE -ne 0) { throw 'manifest.json was not restored; fix the cause printed above and run this block again. It does not touch the knob' }
}
```

### Firmware, manual esptool fallback

Use this path only when the script itself cannot run: exit 1 for a cause in the cc4
record or the script that cannot be fixed. Never use it to get around the environment:
block 1 first requires esptool 4.12.0 in the flash venv, as the script does. The knob
must already be in the ROM bootloader. The scripted block's first command puts it
there, and sends nothing when it is already there. If that command cannot run either,
use the section 2 touch once, and only while nothing has been written.

The blocks issue the same esptool commands as the script, with the same options
(`--baud 460800 --before no_reset --after no_reset_stub`) and offsets, one block at a
time. Run the blocks in order, in one PowerShell window. Each block is wrapped in
`. { ... }`, so PowerShell runs the whole block as one unit and the first `throw` stops
the rest of it, whether you paste the block or type it. PowerShell does not stop when a
native command fails. For that reason every esptool line is followed by its own
`$LASTEXITCODE` check. Variables set in one block, such as `$romPort`, carry over to
the next.

Three interlock flags carry state between blocks. Each block clears every flag it
depends on or re-establishes **before its first command**, so a `verified` left over
from an earlier run can never let block 4 reset after a later failed write or verify:

| Flag | Set true by | Cleared before any command by | Required by |
|---|---|---|---|
| `$layoutVerified` | block 1, after every read-only check passed | the Quit and scripted blocks, blocks 1 and 2 | block 2 |
| `$app0Verified` | block 2, after the app0 verify | the Quit and scripted blocks, blocks 1 and 2 | block 3 |
| `$rollbackVerified` | block 2 after the full 4 MB verify, or block 3 | the Quit and scripted blocks, blocks 1, 2 and 3 | block 4 |

Block 2 clears `$layoutVerified` too, so every write follows a fresh block 1. A new
PowerShell window starts with no flags set, which every guard treats as not verified.
`install_nanod_cc5.py` also writes app0 and cannot clear these flags: after an install
run in this window, start again at block 1. Block 4 is the backstop. Right before its
reset it verifies app0 against the rollback file itself, on a freshly discovered ROM
port, and it refuses to reset when that verify fails.

**Block 1: read-only checks.** This block writes nothing to the knob. It first requires
esptool 4.12.0 in the flash venv (the version `rollback_nanod_cc5.py` enforces); blocks
2-4 run only after block 1 passed in the same window, so they use that checked esptool.
It checks both file hashes and the chip identity. It cuts the pre-cc5 backup into region
files. It then reads the partition table and the OTA data and compares them with the
backup, in code:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $esptoolVersion = & $flashPython -c "import esptool; print(esptool.__version__)"
  if ($LASTEXITCODE -ne 0 -or $esptoolVersion -ne '4.12.0') { throw 'The flash venv does not have esptool 4.12.0; nothing was sent. Fix the flash venv; the manual blocks are no way around it' }
  $backupFull = '<repo>\app\backups\nanod-cc4-before-cc5-full.bin'
  $rollbackApp = '<repo>\app\backups\nanod-cc4-before-cc5-active-app.bin'
  $prep = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5-preparation.json' -ErrorAction Stop | ConvertFrom-Json
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $rollbackApp -ErrorAction Stop).Hash -ne $prep.rollbackSha256) { throw 'Rollback file hash mismatch; nothing was sent' }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $backupFull -ErrorAction Stop).Hash -ne $prep.beforeSha256) { throw 'Pre-cc5 backup hash mismatch; nothing was sent' }
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'Exactly one MAC-matched ROM bootloader port is required; nothing was sent' }
  $work = (New-Item -ItemType Directory -ErrorAction Stop -Path ('<repo>\app\backups\cc5-manual-rollback-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))).FullName
  $global:LASTEXITCODE = -1
  @'
import sys
from pathlib import Path
backup, out = Path(sys.argv[1]).read_bytes(), Path(sys.argv[2])
if len(backup) != 0x400000:
    raise SystemExit("The pre-cc5 backup is not 4 MB")
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
    if ($current -ne $saved) { throw "$name differs from the pre-cc5 backup; nothing was written. Stop and inspect" }
  }
  $layoutVerified = $true
  "Block 1 passed on $romPort. Nothing has been written. Next: block 2."
}
```

**Block 2: write and verify.** This block **writes firmware**. It restores app0 only,
then verifies app0 and the full 4 MB. It never resets:

```powershell
. {
  if (-not $layoutVerified) { throw 'Block 1 has not passed since the last write; run block 1 first. Nothing was written' }
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'write_flash failed. Do NOT reset, unplug or power-cycle the knob; see the failure table' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'app0 verify failed. Do NOT reset, unplug or power-cycle the knob; see the failure table' }
  $app0Verified = $true
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x0 $backupFull
  if ($LASTEXITCODE -ne 0) { throw 'app0 is verified, but the full image differs from the pre-cc5 backup. Do NOT reset; run block 3' }
  $rollbackVerified = $true
  'app0 and the full 4 MB match the pre-cc5 backup. The chip has not been reset. Next: block 4.'
}
```

**Block 3: only when block 2 stopped at the full verify.** The full 4 MB compare
cannot tell you where the images differ. This block verifies each critical region on
its own against the region files from block 1. The regions are the bootloader
(`0x0`-`0x8000`), the partition table (`0x8000`-`0x9000`), the OTA data
(`0xE000`-`0x10000`), app0 (`0x10000`-`0x150000`) and app1 (`0x150000`-`0x290000`).
These five regions and `nvs` (`0x9000`), `spiffs` (`0x290000`) and `coredump`
(`0x3F0000`) cover the whole flash with no gap. So if all five match, the difference is
only in settings saved or a crash dump written while cc5 ran. That is not a reason to
write anything else:

```powershell
. {
  if (-not $app0Verified) { throw 'Block 2 has not verified app0 in this window. Do NOT reset' }
  $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $regions = [ordered]@{ 'bootloader' = '0x0'; 'partition-table' = '0x8000'; 'otadata' = '0xE000'; 'app0' = '0x10000'; 'app1' = '0x150000' }
  foreach ($name in $regions.Keys) {
    $global:LASTEXITCODE = -1
    & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash $regions[$name] "$work\region-$name.bin"
    if ($LASTEXITCODE -ne 0) { throw "$name differs from the pre-cc5 backup, or its verify did not run. Do NOT reset, unplug or power-cycle the knob; see the failure table" }
  }
  $rollbackVerified = $true
  'Every critical region matches; only nvs, spiffs or coredump differ. The chip has not been reset. Next: block 4.'
}
```

**Block 4: check app0, reset, records.** This is the only block that resets. It refuses
unless block 2 or block 3 printed its success line after the last write in this window.
It then finds the ROM port again and verifies app0 against the rollback file once more,
and resets only when that verify passes. It writes nothing to the knob:

```powershell
. {
  if (-not $rollbackVerified) { throw 'The rollback has not been verified in this window. Do NOT reset' }
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'No single MAC-matched ROM port; nothing was reset. If 239A:8010 (NANO_D) is present, an earlier block 4 reset already restarted the chip: run only the records-only block. Otherwise do NOT reset; see the failure table' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not match the rollback file, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob; see the failure table' }
  $global:LASTEXITCODE = -1
  $reset = (& $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed. The flash is verified: run only this block again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed. The flash is verified: run only this block again, once' }
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --records-only
  if ($LASTEXITCODE -ne 0) { throw 'The chip is reset into cc4, but manifest.json was not restored. Fix the cause printed above, then run only the records-only block' }
  'cc4 is restored, verified and reset; manifest.json is the cc4 record again.'
}
```

`--records-only` restores `manifest.json` and writes `cc5-rollback.json`. It does not
touch the device. It is the same command as the records-only block under the exit-code
table.

**If a block stops**, the message names what failed. Do exactly this:

| Stopped in | State of app0 | Do next |
|---|---|---|
| Block 1, the esptool check | Unchanged by this block | Nothing was sent. The flash venv must have esptool 4.12.0: fix it, then run the scripted block again (the script requires the same version). After a failed write, the reset rule still applies while you fix it. |
| Block 1, a port or file problem | Unchanged by this block | Fix it and run block 1 again. After a failed write the reset rule applies: never unplug or power-cycle to get a port back; if no MAC-matched ROM port remains, stop. |
| Block 1, identity, partition table or OTA data | Unchanged by this block | Never run block 2. Nothing written yet: [leave the bootloader without writing](#leave-the-bootloader-without-writing), [re-enable the companion](#re-enable-the-companion) and inspect with the user. After install exit 4 or a counted failure: leave the knob in the ROM bootloader and stop (reset rule). |
| Block 2, `write_flash` or the app0 verify | May be partly written | Reset rule. First counted failure: run block 1, then block 2 again. Second: stop (retry rule). |
| Block 2, the full 4 MB verify ("run block 3") | app0 verified | Run block 3. Do not run block 2 again. |
| Block 3 | app0 verified; a critical region differs or its verify did not run | Reset rule. First counted failure: run block 1, block 2 and, if block 2 sends you there, block 3 again. Second: stop (retry rule). |
| Block 4, finding the ROM port | Verified by block 2 or 3 | Nothing was reset. If `239A:8010` (`NANO_D`) is present, an earlier block 4 reset already restarted the chip: run only the records-only block, then [After the rollback](#after-the-rollback). Otherwise the reset rule applies: if no MAC-matched ROM port remains, stop. |
| Block 4, the app0 verify | Differs from the rollback file, or not checked | Nothing was reset. Reset rule. First counted failure: run block 1, then block 2 again. Second: stop (retry rule). |
| Block 4, the reset | Verified by this block | Run block 4 again, once; it finds the port and verifies app0 again. If that also fails to confirm the reset, stop: app0 is verified, so leave the knob connected and decide with the user. |
| Block 4, the records | Verified and reset | Fix the cause printed, then run only the records-only block. Then [After the rollback](#after-the-rollback). |

A second counted failure ends the rollback: follow the retry rule and do not run
block 4. If the PowerShell window is lost, start again at block 1; the flags are gone,
so block 4 cannot run before a new block 2 or block 3 passes. The reset rule still
applies in the new window.

### Leave the bootloader without writing

Only under the **Nothing written yet** rule: cc5 is still verified in app0 (install exit
0 or 5), and no rollback write has started since. This block writes nothing. It does not
rely on remembering that rule, which a lost window or a forgotten write would break:
it first verifies app0 against the installed cc5 image (read-only;
`nanod-control-center-1.0.0-cc5.2.bin`) and resets only when that verify passes. A partly
written app0 therefore never gets a reset from here. The abort in `BUILD-cc5.md` makes the
same check against the cc4 image, for a stop before the install wrote anything:

```powershell
. {
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'No single MAC-matched ROM port; nothing was reset. If 239A:8010 (NANO_D) is present, the knob is already running' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 '<repo>\app\firmware\nanod-control-center-1.0.0-cc5.2.bin'
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not hold the cc5.2 image, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob: run this block again once; if app0 still does not verify, leave the knob in the ROM bootloader and decide with the user (reset rule)' }
  $global:LASTEXITCODE = -1
  $reset = (& $flashPython -u -m esptool --chip esp32s3 --port $romPort --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed; list ports, then run this block again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed; list ports, then run this block again, once' }
  'The knob is restarting into the cc5.2 already in app0. Next: re-enable the companion.'
}
```

Wait for the native screen, then [re-enable the companion](#re-enable-the-companion).
Inspect the evidence (`../diagnostics/cc5-rollback.json` and any
`../backups/cc5-manual-rollback-*` reads) with the user before any further write.
`finalize_nanod_cc5.py` refuses to record cc5 after any rollback attempt, including one
that wrote nothing.

### After the rollback

With the companion still quit, wait for the native screen, then confirm that the
application port stays enumerated for 30 s and read the inventory:

```powershell
. {
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $appPort = & $flashPython -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.poll_ports(t.is_app_port, 60, settle=30)[0] or '')"
  if ($LASTEXITCODE -ne 0 -or -not $appPort) { throw 'No stable 239A:8010 NANO_D port; write nothing and see section 2' }
  $global:LASTEXITCODE = -1
  & '<repo>\app\.venv\Scripts\python.exe' '<repo>\app\device_inventory.py' --port $appPort
  if ($LASTEXITCODE -ne 0) { throw 'The inventory failed' }
}
```

The port check only lists devices; it opens no port. `device_inventory.py` runs with the
companion's own venv and never enters host control. The new
`../backups/control-center-inventory-*.json` must show `firmwareVersion` `1.0.0-cc4`,
`presentation` 2, and the same ten profiles.

### Desktop rollback, optional

Quit the cc5 companion from its tray icon first if it is running (the installer refuses
otherwise), then:

```powershell
. {
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v2 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'The desktop rollback failed; the startup task may still be disabled' }
}
```

`-Mirror` removes program files that are not in the cc4-era bundle, such as the
v3-only assets. It works on the install folder only. User data under
`%LOCALAPPDATA%\NanoDControlCenter\data` is not touched. The installer never
overwrites an existing `settings.json` or `credentials.bin`. The cc4-era companion
reads only the settings keys it knows, so the cc5 keys `led_style` and `artwork`
are ignored.

### Re-enable the companion

Whether or not you rolled back the desktop app, finish with:

```powershell
. {
  # Exactly one startup task: Desk Dial (desktop v7 on) or, before it or after a desktop rollback, NanoD Control Center.
  $tasks = @('Desk Dial', 'NanoD Control Center' | Where-Object { Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue })
  if ($tasks.Count -ne 1) { throw "Expected exactly one companion startup task, found $($tasks.Count); decide with the user" }
  Enable-ScheduledTask -TaskName $tasks[0] -ErrorAction Stop | Out-Null
  Start-ScheduledTask -TaskName $tasks[0] -ErrorAction Stop
}
```

## 6. cc5.3 -> cc5.2 rollback

Use this after the 1.0.0-cc5.3 application-only install (`../diagnostics/cc5.3-flash-checks.json`,
firmware/BUILD-cc5.3.md step 6). It returns app0 to the exact bytes read from the knob just
before cc5.3 was written. Those bytes start with the installed 1.0.0-cc5.2 image
(`nanod-control-center-1.0.0-cc5.2.bin`, SHA-256
`45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572`). The cc5.2 install's own
evidence (`../diagnostics/cc5-*.json`) and its backup pair (`nanod-cc4-before-cc5-*.bin`) are
history: this section never reads them as its inputs and never writes them.

| File under `../backups/` | Size | SHA-256 recorded in `../diagnostics/cc5.3-preparation.json` |
|---|---:|---|
| `nanod-cc5.2-before-cc5.3-active-app.bin` (rollback app0, `0x10000`-`0x150000` of the read below) | 1,310,720 (`0x140000`) | `rollbackSha256` |
| `nanod-cc5.2-before-cc5.3-full.bin` (fresh full read before the cc5.3 write) | 4,194,304 (`0x400000`) | `beforeSha256` |

The pre-cc5.3 backup is never replaced after a cc5.3 write: `backup_nanod_cc5.py` then only
confirms that a fresh read is byte-identical to it. The records the rollback restores come from
`firmware/manifest-cc5.2.json`, the installed cc5.2 record that `package_nanod_cc5.py` kept
byte-identical when it packaged cc5.3.

Firmware rollback alone is safe to leave in place with the desktop v4 companion. It reads the
capabilities: without `artwork2` (cc5.2) it sends v1 art with pacing, as desktop v3 does, and
every control keeps working. Rolling the desktop app back to v3 is optional
([below](#cc53-desktop-rollback-to-v3-optional)).

The scripted rollback (`rollback_nanod_cc5.py --to cc5.2`) is the path to use. The manual
esptool blocks are the fallback for when the script itself cannot run: its exit 1 for a cause
in the script or in the cc5.2 record that cannot be fixed. A wrong Python or esptool, a file
hash or the ROM port is never a reason for the manual blocks: they use the same flash venv,
and block 1 refuses the same things. The three rules of section 5 apply here unchanged, with
cc5.3 in place of cc5 and cc5.2 in place of cc4:

- **Reset rule.** Never reset, unplug or power-cycle the knob yourself once a rollback
  write has started, or after install exit 4 (its restore write failed). From then on, the
  only resets are the rollback script's own (exit 0), the one command it prints after exit 5,
  and manual block 4, which resets only when `$rollbackVerified` says block 2 or block 3
  verified the rollback in this PowerShell window, and only after it has verified app0 once
  more itself. Any write outside block 2 invalidates that interlock.
- **Retry rule.** Count every failed rollback write or verify, whichever path it came from.
  After the first, retry once. After the second, stop: leave the knob connected and powered in
  the ROM bootloader, do not reset it, and keep `../diagnostics/cc5.3-rollback*` and
  `../backups/cc5.3-manual-rollback-*` for diagnosis.
- **Nothing written yet.** While cc5.3 is still verified in app0 (install exit 0 or 5, and no
  rollback write has started since), a stop that wrote nothing may leave the ROM bootloader
  with [the read-only reset](#cc53-leave-the-bootloader-without-writing), which verifies app0
  against the cc5.3 image first.

### cc5.3: Quit the companion

Quit the companion from its tray icon (**Quit**). Do not use `Stop-Process` or `taskkill`.
Then disable the startup task and confirm that nothing owns the port:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false   # a new rollback starts unverified
  foreach ($task in 'Desk Dial', 'NanoD Control Center') {   # Desk Dial from desktop v7; the old name before it or after a desktop rollback
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
      Disable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
      if ((Get-ScheduledTask -TaskName $task -ErrorAction Stop).State -ne 'Disabled') { throw "The startup task '$task' is not disabled; nothing was sent. Disable it, then run this block again" }
    }
  }
  if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'The companion (DeskDial or NanoDControlCenter) is still running; quit it from the tray, then run this block again. Nothing was sent' }
  'The companion is quit and its startup task is disabled. Next: the scripted block of section 6.'
}
```

Every block below sets `$flashPython` (the flash venv with esptool 4.12.0) to its absolute
path and `$global:LASTEXITCODE = -1` before each native command. Every path is absolute.

### cc5.3: Firmware, scripted (use this first)

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

`nanod_enter_bootloader_v2.py` behaves as in section 5 (one 1200-bps touch, or nothing when the
MAC-matched ROM port is already present; `../diagnostics/cc5-usb-boot-entry*.json`).
`rollback_nanod_cc5.py --to cc5.2` runs only under the flash venv with esptool 4.12.0, on the
one MAC-matched ROM port, every esptool step with `--baud 460800 --before no_reset --after
no_reset_stub` until the final reset:

1. Checks the file hashes against `cc5.3-preparation.json`, that the rollback app0 starts with
   the cc5.2 image, and that `manifest-cc5.2.json` is the cc5.2 record.
2. Runs `flash_id` and requires MAC `12:34:56:78:9A:BC` and 4MB flash.
3. Reads the partition table (`0x8000`, `0x1000`) and the OTA data (`0xE000`, `0x2000`).
   Both must equal the pre-cc5.3 backup.
4. Writes the rollback file with `write_flash --flash_mode keep --flash_freq keep
   --flash_size keep 0x10000`.
5. Verifies app0 (`verify_flash 0x10000` against the rollback file).
6. Verifies the full 4 MB (`verify_flash 0x0` against the pre-cc5.3 backup). If it differs,
   each region is verified on its own; drift in `nvs`, `spiffs` or `coredump` is reported and
   never rewritten.
7. Only then resets the chip with `read_mac --after hard_reset` (confirmed only when esptool
   exits 0, names the chip MAC and prints its hard-reset line).

Once the flash is verified, the script restores `manifest.json` from `manifest-cc5.2.json`,
keeping the previous file as `manifest-at-cc5.3-rollback-<UTC>.json`, marks
`manifest-1.0.0-cc5.3.json` `ROLLED_BACK` when it was `INSTALLED`, and writes
`../diagnostics/cc5.3-rollback.json`, whose `outcome` matches the exit code:

| Exit code | Meaning | Do next |
|---|---|---|
| 0 | cc5.2 is restored, verified and reset. `manifest.json` is the cc5.2 record again. | [After the rollback](#cc53-after-the-rollback). |
| 1 | Nothing was sent to the device: wrong Python or esptool, a file hash, the cc5.2 record, or not exactly one MAC-matched ROM port. | Fix the cause and run the scripted block again; after a failed write, never by unplugging (reset rule). Only when the cause is the cc5.2 record or the script itself, and it cannot be fixed, use the manual blocks. |
| 2 | Identity, partition table or OTA data did not match (or a command-line usage error). This run wrote nothing and did not reset. | Stop and write nothing. Nothing written yet: [leave the bootloader without writing](#cc53-leave-the-bootloader-without-writing), [re-enable the companion](#cc53-re-enable-the-companion) and inspect the evidence with the user. After install exit 4 or a counted failure: leave the knob in the ROM bootloader and stop (reset rule). |
| 4 | A write or verify failed after the write started. The chip was **not** reset. | Reset rule. First counted failure: run the scripted block once more. Second: stop (retry rule). |
| 5 | cc5.2 is written and verified and `manifest.json` is restored, but the reset was **not confirmed**. | Run only the `read_mac --after hard_reset` command the script prints, once. If the ROM port is gone and `239A:8010` (`NANO_D`) is present, the chip has already restarted. Then [after the rollback](#cc53-after-the-rollback). If that single retry also cannot confirm a reset and the ROM port is still present, the verified image makes unplugging the USB cable for 5 s a safe reset (the only case where a power-cycle is allowed). The same applies to install exit 6 (cc5.2 restored and verified, reset unconfirmed). |
| 6 | The device rollback verified and reset, but `manifest.json` was **not** restored (`recordsError`). | Fix the cause, then run the records-only block below. Then [after the rollback](#cc53-after-the-rollback). |
| -1 | The script did not run at all (the block's own marker). Nothing was sent. | Fix the interpreter path and run the scripted block again. |
| Any other | The script was interrupted (for example with Ctrl+C). | Open `../diagnostics/cc5.3-rollback.json`. If `writeAttempted` is true, or the file is missing or older than this run, treat it as exit 4. Otherwise treat it as exit 2. |

This table replaces the script's own last line where they differ.

```powershell
. {
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --to cc5.2 --records-only
  if ($LASTEXITCODE -ne 0) { throw 'manifest.json was not restored; fix the cause printed above and run this block again. It does not touch the knob' }
}
```

### cc5.3: Firmware, manual esptool fallback

Use this path only for an exit 1 whose cause is the cc5.2 record or the script itself and
cannot be fixed. The knob must already be in the ROM bootloader (the scripted block's first
command puts it there). The blocks issue the same esptool commands as the script, one block at
a time, in one PowerShell window; each is wrapped in `. { ... }` so the first `throw` stops it,
and every esptool line is followed by its own `$LASTEXITCODE` check. The interlock flags
`$layoutVerified`, `$app0Verified` and `$rollbackVerified` work exactly as in section 5 (the
table there): each block clears every flag it depends on or re-establishes before its first
command, and `install_nanod_cc5.py` writes app0 too, so after an install run in this window
start again at block 1.

**Block 1: read-only checks.** It requires esptool 4.12.0 first, checks both file hashes and
the chip identity, cuts the pre-cc5.3 backup into region files and compares the partition table
and the OTA data with it:

```powershell
. {
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $esptoolVersion = & $flashPython -c "import esptool; print(esptool.__version__)"
  if ($LASTEXITCODE -ne 0 -or $esptoolVersion -ne '4.12.0') { throw 'The flash venv does not have esptool 4.12.0; nothing was sent. Fix the flash venv; the manual blocks are no way around it' }
  $backupFull = '<repo>\app\backups\nanod-cc5.2-before-cc5.3-full.bin'
  $rollbackApp = '<repo>\app\backups\nanod-cc5.2-before-cc5.3-active-app.bin'
  $prep = Get-Content -Raw -LiteralPath '<repo>\app\diagnostics\cc5.3-preparation.json' -ErrorAction Stop | ConvertFrom-Json
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $rollbackApp -ErrorAction Stop).Hash -ne $prep.rollbackSha256) { throw 'Rollback file hash mismatch; nothing was sent' }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $backupFull -ErrorAction Stop).Hash -ne $prep.beforeSha256) { throw 'Pre-cc5.3 backup hash mismatch; nothing was sent' }
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'Exactly one MAC-matched ROM bootloader port is required; nothing was sent' }
  $work = (New-Item -ItemType Directory -ErrorAction Stop -Path ('<repo>\app\backups\cc5.3-manual-rollback-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))).FullName
  $global:LASTEXITCODE = -1
  @'
import sys
from pathlib import Path
backup, out = Path(sys.argv[1]).read_bytes(), Path(sys.argv[2])
if len(backup) != 0x400000:
    raise SystemExit("The pre-cc5.3 backup is not 4 MB")
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
    if ($current -ne $saved) { throw "$name differs from the pre-cc5.3 backup; nothing was written. Stop and inspect" }
  }
  $layoutVerified = $true
  "Block 1 passed on $romPort. Nothing has been written. Next: block 2."
}
```

**Block 2: write and verify.** This block **writes firmware**: app0 only, then verifies app0
and the full 4 MB. It never resets:

```powershell
. {
  if (-not $layoutVerified) { throw 'Block 1 has not passed since the last write; run block 1 first. Nothing was written' }
  $layoutVerified = $false; $app0Verified = $false; $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'write_flash failed. Do NOT reset, unplug or power-cycle the knob; see the failure table' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'app0 verify failed. Do NOT reset, unplug or power-cycle the knob; see the failure table' }
  $app0Verified = $true
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x0 $backupFull
  if ($LASTEXITCODE -ne 0) { throw 'app0 is verified, but the full image differs from the pre-cc5.3 backup. Do NOT reset; run block 3' }
  $rollbackVerified = $true
  'app0 and the full 4 MB match the pre-cc5.3 backup. The chip has not been reset. Next: block 4.'
}
```

**Block 3: only when block 2 stopped at the full verify.** It verifies each critical region
(bootloader, partition table, OTA data, app0, app1) against the region files from block 1; if
all match, the difference is only in `nvs`, `spiffs` or `coredump`:

```powershell
. {
  if (-not $app0Verified) { throw 'Block 2 has not verified app0 in this window. Do NOT reset' }
  $rollbackVerified = $false
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $regions = [ordered]@{ 'bootloader' = '0x0'; 'partition-table' = '0x8000'; 'otadata' = '0xE000'; 'app0' = '0x10000'; 'app1' = '0x150000' }
  foreach ($name in $regions.Keys) {
    $global:LASTEXITCODE = -1
    & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash $regions[$name] "$work\region-$name.bin"
    if ($LASTEXITCODE -ne 0) { throw "$name differs from the pre-cc5.3 backup, or its verify did not run. Do NOT reset, unplug or power-cycle the knob; see the failure table" }
  }
  $rollbackVerified = $true
  'Every critical region matches; only nvs, spiffs or coredump differ. The chip has not been reset. Next: block 4.'
}
```

**Block 4: check app0, reset, records.** The only block that resets. It refuses unless block 2
or block 3 printed its success line after the last write in this window, finds the ROM port
again, verifies app0 against the rollback file once more, and resets only when that passes:

```powershell
. {
  if (-not $rollbackVerified) { throw 'The rollback has not been verified in this window. Do NOT reset' }
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'No single MAC-matched ROM port; nothing was reset. If 239A:8010 (NANO_D) is present, an earlier block 4 reset already restarted the chip: run only the records-only block. Otherwise do NOT reset; see the failure table' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 $rollbackApp
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not match the rollback file, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob; see the failure table' }
  $global:LASTEXITCODE = -1
  $reset = (& $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed. The flash is verified: run only this block again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed. The flash is verified: run only this block again, once' }
  $global:LASTEXITCODE = -1
  & $flashPython '<repo>\tools\rollback_nanod_cc5.py' --to cc5.2 --records-only
  if ($LASTEXITCODE -ne 0) { throw 'The chip is reset into cc5.2, but manifest.json was not restored. Fix the cause printed above, then run only the records-only block' }
  'cc5.2 is restored, verified and reset; manifest.json is the cc5.2 record again.'
}
```

`--to cc5.2 --records-only` restores `manifest.json` from `manifest-cc5.2.json` and writes
`cc5.3-rollback.json`; it does not touch the device. **If a block stops**, act as the section 5
failure table says for the same block, with the pre-cc5.3 files: a stop in block 1 wrote
nothing; a stop in block 2 at `write_flash` or the app0 verify, in block 3, or at block 4's app0
verify is a counted failure (reset rule; first: run block 1, then block 2 again; second: stop);
block 2 stopping at the full verify sends you to block 3; a block 4 reset that was not
confirmed is run again once.

### cc5.3: Leave the bootloader without writing

Only under the **Nothing written yet** rule: cc5.3 is still verified in app0 (install exit 0
or 5), and no rollback write has started since. This block writes nothing; it first verifies
app0 against the installed cc5.3 image (read-only; `nanod-control-center-1.0.0-cc5.3.bin`) and
resets only when that verify passes. BUILD-cc5.3.md's abort makes the same check against the
cc5.2 image, for a stop before the install wrote anything:

```powershell
. {
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $romPort = & $flashPython -c "from serial.tools.list_ports import comports; m=[p.device for p in comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').replace(':','').lower()=='123456789abc']; print(m[0] if len(m)==1 else '')"
  if ($LASTEXITCODE -ne 0 -or -not $romPort) { throw 'No single MAC-matched ROM port; nothing was reset. If 239A:8010 (NANO_D) is present, the knob is already running' }
  $global:LASTEXITCODE = -1
  & $flashPython -u -m esptool --chip esp32s3 --port $romPort --baud 460800 --before no_reset --after no_reset_stub verify_flash 0x10000 '<repo>\app\firmware\nanod-control-center-1.0.0-cc5.3.bin'
  if ($LASTEXITCODE -ne 0) { throw 'app0 does not hold the cc5.3 image, or its verify did not run. Nothing was reset. Do NOT reset, unplug or power-cycle the knob: run this block again once; if app0 still does not verify, leave the knob in the ROM bootloader and decide with the user (reset rule)' }
  $global:LASTEXITCODE = -1
  $reset = (& $flashPython -u -m esptool --chip esp32s3 --port $romPort --before no_reset --after hard_reset read_mac) -join "`n"; Write-Host $reset
  if ($LASTEXITCODE -ne 0) { throw 'The reset was not confirmed; list ports, then run this block again, once' }
  if ($reset -notmatch '12:34:56:78:9a:bc' -or $reset -notmatch 'Hard resetting') { throw 'The reset was not confirmed; list ports, then run this block again, once' }
  'The knob is restarting into the cc5.3 already in app0. Next: re-enable the companion.'
}
```

Wait for the native screen, then [re-enable the companion](#cc53-re-enable-the-companion).
`finalize_nanod_cc5.py` refuses to record cc5.3 after any rollback attempt of either path
(`cc5.3-rollback*`, `cc5-rollback*`, their work folders, logs and restored-manifest copies), or
a ROM bootloader entry after the install, including one that wrote nothing.

### cc5.3: After the rollback

With the companion still quit, wait for the native screen, then confirm that the application
port stays enumerated for 30 s and read the inventory:

```powershell
. {
  $flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'
  $global:LASTEXITCODE = -1
  $appPort = & $flashPython -c "import sys; sys.path.insert(0, r'<repo>\tools'); import nanod_cc5_tooling as t; print(t.poll_ports(t.is_app_port, 60, settle=30)[0] or '')"
  if ($LASTEXITCODE -ne 0 -or -not $appPort) { throw 'No stable 239A:8010 NANO_D port; write nothing and see section 2' }
  $global:LASTEXITCODE = -1
  & '<repo>\app\.venv\Scripts\python.exe' '<repo>\app\device_inventory.py' --port $appPort
  if ($LASTEXITCODE -ne 0) { throw 'The inventory failed' }
}
```

The new `../backups/control-center-inventory-*.json` must show `firmwareVersion`
`1.0.0-cc5.2`, `presentation` 4, the v1 `artwork` capability, no `artwork2`, and the same ten
profiles.

### cc5.3: Desktop rollback to v3, optional

Quit the v4 companion from its tray icon first if it is running (the installer refuses
otherwise), then install the v3 bundle (its exe SHA-256
`90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19`; `Install-Desktop.ps1`
refuses a `desktop-dist-v3` whose exe has another hash):

```powershell
. {
  $global:LASTEXITCODE = -1
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<repo>\app\Install-Desktop.ps1' -Bundle desktop-dist-v3 -Mirror
  if ($LASTEXITCODE -ne 0) { throw 'The desktop rollback failed; the startup task may still be disabled' }
}
```

`-Mirror` removes program files that v3 does not ship. User data under
`%LOCALAPPDATA%\NanoDControlCenter\data` is never touched, and v3 ignores settings keys it
does not know. The v3 companion works with both cc5.2 and cc5.3 (v1 art, paced).

### cc5.3: Re-enable the companion

```powershell
. {
  # Exactly one startup task: Desk Dial (desktop v7 on) or, before it or after a desktop rollback, NanoD Control Center.
  $tasks = @('Desk Dial', 'NanoD Control Center' | Where-Object { Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue })
  if ($tasks.Count -ne 1) { throw "Expected exactly one companion startup task, found $($tasks.Count); decide with the user" }
  Enable-ScheduledTask -TaskName $tasks[0] -ErrorAction Stop | Out-Null
  Start-ScheduledTask -TaskName $tasks[0] -ErrorAction Stop
}
```

## Reference

The successful software entry follows the vendor's `use_1200bps_touch` and
`wait_for_upload_port` board settings. The recovery loader remains Espressif's
ROM loader plus a temporary RAM stub. [Espressif boot-mode reference](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/boot-mode-selection.html)
and [esptool 4.12.0 release](https://github.com/espressif/esptool/releases/tag/v4.12.0).
