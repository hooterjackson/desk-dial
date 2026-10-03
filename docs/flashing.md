# Flashing the knob firmware

This guide puts the Desk Dial firmware v2.0.0 on a Nano_D++. It also shows how to put your old firmware back. Plan on about half an hour, most of it spent waiting for the backup.

You will:

1. put the knob into its bootloader,
2. save a full copy of its memory,
3. write the new firmware into the app area only,
4. check what was written,
5. restart the knob.

Every command here uses [esptool](https://github.com/espressif/esptool), Espressif's own flashing tool. The guide never erases the whole chip and never writes over the bootloader. Your knob's calibration, its settings and Karl's profiles stay on the knob.

> **Only for a Nano_D++.** Desk Dial has been tested on one knob, the author's. Read [compatibility](compatibility.md) first. Do not flash a Ratchet H1 or any other board with this file.

## What you need

- **A Nano_D++** ([Karl Malota's hardware](https://github.com/katbinaris/Nano_D_PlusPlus)), still on Karl's firmware or on Desk Dial v1.0 / v1.1.
- **Windows 10 or 11.**
- **A USB-C cable that carries data.** Some cables only charge. Plug the knob straight into the PC, not into a hub.
- **Python 3** from [python.org](https://www.python.org/downloads/windows/). During setup, tick "Add python.exe to PATH". If `python` is not found later, type `py` instead.
- **esptool 4.x**, which also installs pySerial. Open PowerShell and run:

  ```powershell
  python -m pip install "esptool>=4.8,<5"
  ```

  Desk Dial was flashed with esptool 4.12.0. esptool 5 renamed the commands this guide uses, so stay on 4.x.
- **From the [v2.0.0 release](https://github.com/hooterjackson/desk-dial/releases/tag/v2.0.0):** `desk-dial-firmware-2.0.0-F.bin` and `SHA256SUMS`. Put both in one folder, open PowerShell in that folder, and run every command below from there.

### Check the download

```powershell
Get-FileHash .\desk-dial-firmware-2.0.0-F.bin -Algorithm SHA256
```

*You should see* a long hash. It must match the `desk-dial-firmware-2.0.0-F.bin` line in `SHA256SUMS`; the letters may be in a different case. If the hash is different, download the file again and do not flash it.

### Close everything that talks to the knob

Only one program can have the knob's port open at a time. Before you start:

- quit Desk Dial: right-click its tray icon and choose **Quit**;
- close Karl's Nano_D web configurator, the Arduino IDE, PlatformIO monitors and any serial terminal.

## Step 1: put the knob into its bootloader

### Find the knob's port

With the knob plugged in and running, run:

```powershell
python -m serial.tools.list_ports -v
```

*You should see* a port whose details include `VID:PID=239A:8010`, for example `COM7`. That is the knob's normal port, and both Karl's firmware and Desk Dial's use it. If no line shows `239A:8010`, try another cable or another USB port. If there is still none, see [The knob does not start](recovery.md#the-knob-does-not-start).

### Send the bootloader signal

The knob goes into its bootloader when a program opens its port at 1200 baud and closes it again. This is the same "1200-bps touch" the Arduino and PlatformIO upload tools use. Replace `COM7` with your port:

```powershell
python -c "import serial; s = serial.Serial(); s.port = 'COM7'; s.baudrate = 1200; s.open(); s.dtr = False; s.close()"
```

The command may print an error as the port disappears under it. That is expected. Send it once and do not repeat it.

*You should see* the knob's screen go dark, and Windows play its disconnect and connect sounds. Run the list again:

```powershell
python -m serial.tools.list_ports -v
```

There should now be a port with `VID:PID=303A:1001`, usually with a different COM number, for example `COM8`. This is the chip's built-in bootloader port. **Use this port for every esptool command until Step 5.**

**Why not esptool's own reset?** The ESP32-S3 has a USB port of its own (`303A:1001`), and esptool can reset the chip through it with `--before default_reset` or `--before usb_reset`. The Nano_D++ firmware, Karl's and Desk Dial's alike, turns that port off and runs its own USB device (`239A:8010`) instead. While the firmware runs, esptool has nothing to reset through, so the 1200-bps touch is the way in. Once the knob is in the bootloader, the commands below use `--before no_reset`, because the chip is already waiting.

## Step 2: back up the whole knob (do not skip)

This copies all 4 MB of the knob's flash into one file. That includes the bootloader, the firmware, the calibration, the settings and the profiles. With this file you can always go back to exactly what you had. Replace `COM8` with your bootloader port:

```powershell
python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub read_flash 0 0x400000 my-nanod-backup.bin
```

*You should see* esptool connect and print the chip line, `Chip is ESP32-S3 ... (revision v0.x)`, then a progress counter. Reading can take several minutes. It ends with a line that starts `Read 4194304 bytes`, followed by `Staying in flasher stub.`

Next, check that the copy matches the knob. This reads the knob again and compares:

```powershell
python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub verify_flash 0 my-nanod-backup.bin
```

*You should see* `-- verify OK (digest matched)`.

Finally, check the size and the partition table. The file must be exactly 4194304 bytes:

```powershell
(Get-Item .\my-nanod-backup.bin).Length
python -c "import hashlib; d = open('my-nanod-backup.bin', 'rb').read(); print(hashlib.sha256(d[0x8000:0x8C00]).hexdigest())"
```

*You should see* `4194304`, then `148b959cbff1c38aa8e1d5c0ba9d612c54997b945e56a63f41223eef650653a1`. That hash is Karl's v1.0.0 partition table, which Desk Dial keeps unchanged. **If you get a different hash, stop.** Your knob uses another memory layout, and this guide's addresses may not fit it. Unplug the knob, plug it back in, and ask in an [issue](https://github.com/hooterjackson/desk-dial/issues) or on [Karl's Discord](https://discord.gg/mVTvppcfp6).

Copy `my-nanod-backup.bin` somewhere safe, such as a second drive or cloud storage, and keep it. It is the only exact copy of your knob's original firmware and calibration. The file also contains your knob's serial number and your own settings, so do not post it publicly.

## Step 3: write the new firmware (app area only)

The firmware lives in the knob's app area, which starts at address `0x10000`. Write the release file there and nowhere else:

```powershell
python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 desk-dial-firmware-2.0.0-F.bin
```

*You should see* `Compressed ... bytes`, a progress counter and then `Hash of data verified.` This takes under a minute.

**Do not unplug the knob while it writes.** If the write stops with an error, leave the knob plugged in: it stays in the bootloader, and you can run the same command again. If that fails too, see [A write failed](recovery.md#a-write-failed-part-way).

Never do these. Each one can destroy your calibration and profiles:

- `erase_flash` or `erase_region`;
- writing the release file at `0` or at any address other than `0x10000`;
- a "merged" or "factory" image from anywhere else.

Address `0` is only for restoring your own full backup ([recovery](recovery.md#restore-the-whole-backup)).

## Step 4: check what was written

```powershell
python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub verify_flash 0x10000 desk-dial-firmware-2.0.0-F.bin
```

*You should see* `-- verify OK (digest matched)`. Together with the `SHA256SUMS` check you did before starting, this proves the knob holds exactly the released file.

If verification fails, **do not restart the knob.** Run Step 3 again, then Step 4. If it still fails, write your old firmware back while the knob is still in the bootloader ([recovery](recovery.md#go-back-to-your-own-firmware)).

## Step 5: restart the knob

Restart the knob only after Step 4 says `verify OK`:

```powershell
python -m esptool --chip esp32s3 --port COM8 --before no_reset --after hard_reset read_mac
```

*You should see* the knob's MAC address and then `Hard resetting via RTS pin...`. Don't post the MAC address publicly; it identifies your knob.

The knob restarts:

- its screen shows **DESK DIAL IS BOOTING...** and then its own screen;
- Windows may set the knob up as a new USB device once, because the new firmware adds a volume control;
- after about two seconds without Desk Dial, the knob works as a plain Windows volume knob, and its screen reads **PC volume**.

If the screen stays dark after about ten seconds, unplug the knob, wait five seconds and plug it back in.

Now start Desk Dial **v2.0.0**. *You should see* the knob connect. The status line at the top of the Settings window shows a firmware version that starts with `2.0.0`.

If you are coming from v1.0 or v1.1, update Desk Dial **before** you flash. See [compatibility](compatibility.md#upgrading-from-v11).

## Going back to your old firmware

The quick way back uses only the firmware part of your backup. Your current calibration and settings stay as they are.

If the knob calibrated itself while it ran Desk Dial firmware, older firmware does not find that calibration and calibrates again on first start. The knob turns on its own for a few seconds; leave it untouched on the desk. To get the exact old calibration back, restore the whole backup ([recovery](recovery.md#restore-the-whole-backup)).

1. Cut the app area out of your backup:

   ```powershell
   python -c "d = open('my-nanod-backup.bin', 'rb').read(); open('my-nanod-app.bin', 'wb').write(d[0x10000:0x150000])"
   ```

2. Do Step 1 (bootloader), then write the file at `0x10000`:

   ```powershell
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 my-nanod-app.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after no_reset_stub verify_flash 0x10000 my-nanod-app.bin
   python -m esptool --chip esp32s3 --port COM8 --before no_reset --after hard_reset read_mac
   ```

*You should see* `verify OK`, and then the knob starting the firmware it ran before.

To get back to Karl's stock firmware without a backup, or to restore everything including the calibration, see [recovery](recovery.md).

## If something goes wrong

| What you see | What to do |
|---|---|
| `Could not open port` or `Access is denied` | Another program has the port. Quit Desk Dial and close every serial tool, then try again. |
| No `303A:1001` port after the touch | Wait ten seconds and list the ports again. If the knob's screen is still on, its firmware did not take the signal. Unplug it, plug it back in and try once more with the `239A:8010` port. |
| `Failed to connect to ESP32-S3` | Check that you used the `303A:1001` port, not the `239A:8010` one. Unplug the knob, plug it back in and start again at Step 1. |
| Different partition table hash in Step 2 | Stop. See Step 2. |
| `verify_flash` fails | Don't restart the knob. Write again (Step 3), or write your backup's app area ([above](#going-back-to-your-old-firmware)). |
| After the restart the knob still shows the old firmware | Ask in an [issue](https://github.com/hooterjackson/desk-dial/issues). Include the esptool output, but leave out the MAC address. |
| The knob does not start at all | [Recovery](recovery.md#the-knob-does-not-start). |

More help: [troubleshooting](troubleshooting.md) · [FAQ](faq.md) · [issues](https://github.com/hooterjackson/desk-dial/issues) · [Karl's Discord](https://discord.gg/mVTvppcfp6).
