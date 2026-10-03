# Recovery and going back

This page covers four things: putting your own firmware back, going back to Karl's stock firmware, what to do when the knob does not start, and rolling Desk Dial back. It uses the same tools and port names as the [flashing guide](flashing.md). Read that first; the commands below assume you have esptool 4.x and know your knob's bootloader port (`303A:1001`, shown here as `COM8`).

## The knob's memory, in short

The Nano_D++ has 4 MB of flash, laid out exactly as in Karl's firmware v1.0.0. Desk Dial does not change the layout.

| Area | Address | Size | What it holds |
|---|---|---|---|
| Bootloader | `0x0` | | starts the chip; never touched by the flashing guide |
| Partition table | `0x8000` | | the map below; never touched |
| `nvs` | `0x9000` | 20 KB | the knob's settings and the **motor calibration** |
| `otadata` | `0xE000` | 8 KB | which app area to start (app0) |
| **`app0`** | **`0x10000`** | **1,280 KB** | **the firmware**: the only area the flashing guide writes |
| `app1` | `0x150000` | 1,280 KB | second app area, unused |
| `spiffs` | `0x290000` | 1,408 KB | the knob's **haptic profiles** (Karl's profiles and any you made) |
| `coredump` | `0x3F0000` | 64 KB | crash information |

So there are two ways back:

- **Firmware only:** write the app area of your backup at `0x10000`. Your settings and profiles stay as they are now. Your calibration stays too, unless the knob calibrated itself under Desk Dial firmware (see below).
- **Everything:** write your backup from `0x9000` to the end (settings, app areas, profiles and crash area). The knob returns to exactly the moment you made the backup, with its firmware, calibration, settings and profiles. The bootloader and the partition table are left alone, because the flashing guide never changes them.

## Go back to your own firmware

You need the `my-nanod-backup.bin` you made in [Step 2 of the flashing guide](flashing.md#step-2-back-up-the-whole-knob-do-not-skip).

### Restore the firmware only (recommended)

If the knob calibrated itself while it ran Desk Dial firmware, older firmware does not find that calibration and calibrates again on first start. The knob turns on its own for a few seconds; leave it untouched on the desk. To get the exact old calibration back, restore the whole backup.

1. Cut the app area out of the backup:

   ```powershell
   python -c "d = open('my-nanod-backup.bin', 'rb').read(); open('my-nanod-app.bin', 'wb').write(d[0x10000:0x150000])"
   ```

2. Put the knob into its bootloader ([flashing guide, Step 1](flashing.md#step-1-put-the-knob-into-its-bootloader)).
3. Write, check, restart:

   ```powershell
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 my-nanod-app.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub verify_flash 0x10000 my-nanod-app.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after hard_reset read_mac
   ```

*You should see* `Hash of data verified.`, then `-- verify OK (digest matched)`, and then the knob starts the firmware it had before.

### Restore the whole backup

Use this when the firmware-only restore did not help, or when you want your old calibration and profiles back too. Use only **your own** backup of **this** knob. Never use another knob's file.

1. Cut everything after the partition table out of the backup:

   ```powershell
   python -c "d = open('my-nanod-backup.bin', 'rb').read(); open('my-nanod-data-and-app.bin', 'wb').write(d[0x9000:])"
   ```

   This covers `nvs` (calibration and settings), `otadata`, `app0`, `app1`, `spiffs` (profiles) and `coredump`: everything the knob keeps.

2. Put the knob into its bootloader ([flashing guide, Step 1](flashing.md#step-1-put-the-knob-into-its-bootloader)).
3. Write, check, restart. **Do not unplug the knob while it writes.**

   ```powershell
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x9000 my-nanod-data-and-app.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub verify_flash 0x9000 my-nanod-data-and-app.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after hard_reset read_mac
   ```

This takes several minutes. *You should see* `verify OK`, and then the knob exactly as it was when you made the backup.

**Last resort only:** if you have reason to believe the bootloader or the partition table itself is damaged, you can write the whole 4 MB file at `0` instead (`write_flash ... 0 my-nanod-backup.bin`, then `verify_flash 0 my-nanod-backup.bin`). That rewrites the bootloader too: if the write is cut off in its first seconds, the knob can only be reached through its BOOT pin, which may not be reachable on a Nano_D++ (see [below](#no-port-at-all-or-the-port-keeps-appearing-and-disappearing)). **Do not unplug the knob while it writes.**

## Go back to Karl's stock firmware

**If your backup was made while the knob still ran Karl's firmware**, it already holds his firmware. Restore it as above. This is the exact original, and the best way back.

**If you have no such backup**, you have to build Karl's firmware yourself. No ready-made file of the stock firmware is published: neither Karl's v1.0.0 release nor this project ships one.

1. Install [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html), or VS Code with the PlatformIO extension.
2. Get Karl's source at the v1.0.0 tag:

   ```powershell
   git clone --branch v1.0.0 https://github.com/katbinaris/NanoD_RatchetH1.git
   cd NanoD_RatchetH1
   ```

3. Build it, but **don't upload from PlatformIO**:

   ```powershell
   pio run -e nanofoc_d
   ```

4. Write only the app area, exactly like the flashing guide but with the file you just built:

   ```powershell
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 .pio\build\nanofoc_d\firmware.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub verify_flash 0x10000 .pio\build\nanofoc_d\firmware.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after hard_reset read_mac
   ```

Two things to know:

- **This is close to stock, but maybe not identical.** Karl's v1.0.0 asks for library versions "at least" a given release (for example `lvgl@^9.0.0`). A build today may pick up newer library versions than the ones the knob shipped with. To match more closely, edit `platformio.ini` and pin each library in `lib_deps` to its minimum version: remove the `^` so that `lvgl/lvgl@^9.0.0` becomes `lvgl/lvgl@9.0.0`, and do the same for the others. If the build fails, ask on [Karl's Discord](https://discord.gg/mVTvppcfp6).
- **Why not PlatformIO's upload button?** It also rewrites the bootloader, the partition table and the app selection. For Karl's v1.0.0 these are the same as on your knob, so it should do no harm. Still, writing only the app area with esptool is the smaller and safer change.

With Karl's firmware back on the knob, Desk Dial connects, backs up the knob's profiles, and then stops at "Stock firmware · display/control extension required". That is expected.

## The knob does not start

First, find out what the knob is doing. Unplug it, wait five seconds, plug it straight into the PC with a data cable, and run:

```powershell
python -m serial.tools.list_ports -v
```

### A `239A:8010` port is listed

The firmware is running, even if the screen looks wrong. You can use the normal way in: the 1200-bps touch from [Step 1 of the flashing guide](flashing.md#step-1-put-the-knob-into-its-bootloader). Then restore your firmware ([above](#go-back-to-your-own-firmware)).

### A `303A:1001` port is listed

The chip's built-in USB port is visible, which means the firmware is not running. Maybe it never started, or a write was interrupted. esptool's normal reset works on this port and puts the chip into its bootloader by itself. Use `--before default_reset` for the first command:

```powershell
python -m esptool --chip esp32s3 --port COM8 --before default_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 my-nanod-app.bin
```

Then run `verify_flash` and the restart exactly as in [Restore the firmware only](#restore-the-firmware-only-recommended). You can also write `desk-dial-firmware-2.0.0-F.bin` here instead of your backup.

This path follows from how the ESP32-S3 works. It has not yet been tried on a Nano_D++ by this project.

### No port at all, or the port keeps appearing and disappearing

This can happen when the firmware crashes very early, before its USB starts, or when it restarts in a loop. Then the 1200-bps touch cannot work, because there is no running firmware to receive it.

The ESP32-S3 has a standard way into its bootloader for this case: hold its **BOOT** pin (GPIO0) low while the chip powers up or resets. On many boards that is a button labelled BOOT, usually paired with one labelled EN or RST.

**Whether you can reach BOOT and EN on a Nano_D++ has not been confirmed.** This project has not checked whether the board has these buttons where you can reach them, or how far the enclosure would have to be opened. So:

- **If your board has a BOOT button or pad you can reach:** unplug the knob. Hold BOOT, plug the USB cable in (or press and release EN while holding BOOT), then let go of BOOT. A `303A:1001` port should appear. Continue as in [A `303A:1001` port is listed](#a-303a1001-port-is-listed), but use `--before no_reset`.
- **If you can't find one:** don't open the enclosure, and don't bridge pins on a guess. Ask on [Karl's Discord](https://discord.gg/mVTvppcfp6), where people know the hardware, or open an [issue](https://github.com/hooterjackson/desk-dial/issues). Say what you flashed and what the port list shows.

Before you go that far, try another cable, another USB port on the PC (one on the back of a desktop PC, not a hub), and a different PC if you have one.

### A write failed part way

**Don't unplug the knob and don't restart it.** While nothing resets it, the chip stays in its bootloader, even if the app area is half written. Run the same `write_flash` command again. If it keeps failing, write your backup's app area (`my-nanod-app.bin`) instead. If you have already unplugged it, see [A `303A:1001` port is listed](#a-303a1001-port-is-listed).

## Roll Desk Dial back

Desk Dial is a folder you unzip, not an installed program, so going back is a swap:

1. Quit Desk Dial: right-click its tray icon and choose **Quit**.
2. Optional but wise: copy the folder `%LOCALAPPDATA%\DeskDial\data` somewhere safe.
3. Delete the Desk Dial folder, or rename it.
4. Download the Desk Dial zip from the release you want, for example [v1.0](https://github.com/hooterjackson/desk-dial/releases/tag/v1.0). v1.1 changed only the firmware, so it uses the same Desk Dial as v1.0. Unzip it and start `DeskDial.exe`.

Your settings stay in `%LOCALAPPDATA%\DeskDial`, which every version uses. If you also roll the firmware back, restore the firmware first and then the app. Desk Dial 2.0.0 works with the older firmware too ([compatibility](compatibility.md)), so rolling the app back is optional.

## Where your data lives

| What | Where | Kept when you flash the app area? |
|---|---|---|
| Firmware | knob, app area at `0x10000` | replaced |
| Motor calibration, knob settings | knob, `nvs` | yes |
| Karl's haptic profiles and your own | knob, `spiffs` | yes |
| App profiles (Onshape, Figma and so on) on the knob | knob memory only; Desk Dial sends them each time it connects | not stored |
| Feel, sound and LED settings | Desk Dial; sent to the knob with each session | not stored on the knob |
| Desk Dial settings and keys | `%LOCALAPPDATA%\DeskDial\data\` | on the PC |
| Copies of the knob's profiles | `%LOCALAPPDATA%\DeskDial\backups\` (one file per connection) | on the PC |
| Logs | `%LOCALAPPDATA%\DeskDial\logs\` | on the PC |
| Your full knob backup | wherever you saved `my-nanod-backup.bin` | keep it safe |

Never share anything from `data\` or `backups\`, or your knob backup. See [Privacy](privacy.md).
