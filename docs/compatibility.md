# Compatibility

Desk Dial has two parts: the Windows app and the knob firmware. Both carry the same version number, and they are tested together as a pair. This page covers three things: what happens when the versions don't match, how to upgrade from v1.1, and what has been tested on real hardware.

## Which app works with which firmware

Desk Dial 2.0.0 checks what the knob says it can do each time it connects. It only uses a feature when the knob reports it. Older firmware therefore keeps working, just with fewer features. The older Desk Dial (v1.0 / v1.1) works the same way in the other direction.

| | **Firmware v1.0 / v1.1** | **Firmware v2.0.0** | **Karl's stock firmware v1.0.0** |
|---|---|---|---|
| **Desk Dial 2.0.0** | Works, with fewer features ([details](#desk-dial-200-with-firmware-v10--v11)) | **Everything works. This is the tested pair.** | Connects, backs up the knob's profiles, then stops at "Stock firmware · display/control extension required" |
| **Desk Dial v1.0 / v1.1** | Works as released | Works as v1.1 did, plus a few firmware changes you can't switch off ([details](#desk-dial-v1x-with-firmware-200)) | Same stock-firmware stop |

Desk Dial v1.0 and v1.1 are the same app; v1.1 changed only the firmware. The two firmware versions report the same version text, so Desk Dial can't tell them apart.

### Desk Dial 2.0.0 with firmware v1.0 / v1.1

Music, Windows, the launcher Home and the Navigator work. These things need firmware v2.0.0, and on the older firmware they are missing or reduced:

- **Feel:** the knob keeps its older feel. The per-screen feels, the firm and light steps, and the thump when a hold lands all need v2.0.0.
- **Knob sounds:** none. In Settings › Knob, **Knob sounds**, **Volume** and **Reduced haptics** can be changed and are saved, but they do nothing until the firmware is updated.
- **Lights:** they work, but the knob draws them with a simpler list screen instead of the lights and scenes screens.
- **Onshape and app profiles:** the knob shows a plain text screen instead of Karl's Onshape screen (the cube and the command wheel), and app profiles don't get their own screen on the knob. Whether their shortcuts work on the PC with the older firmware has not been tested.
- **Quiet at rest:** missing. The motor keeps a faint hum when you let go. The 10-minute dim and 60-minute sleep from v1.1 still work.
- **Recalibration:** not available. The firmware does not support it.

### Desk Dial v1.x with firmware 2.0.0

The old app talks to the new firmware the way it talked to v1.1. Music and Windows work as before. The old app has no Lights, no Onshape and no app profiles, so the knob shows none of them. You will also notice:

- **No sounds.** The old app never turns sounds on, so the knob stays silent.
- **The older feel.** The old app doesn't ask for the new per-screen feels. The end stops still work.
- **Firmware behaviour that is always on:** the motor goes quiet at rest, the screen dims and sleeps after inactivity, and the knob trips (goes limp) if it ever spins on its own.
- **A volume knob when the app is closed.** About two seconds after Desk Dial quits, the knob starts changing the Windows volume.
- **A new USB device.** Windows sets the knob up as a new USB device once, because v2.0.0 adds a volume control.

This combination works, but it isn't a setup to stay on. Update the app too.

## Upgrading from v1.1

These steps also apply to v1.0. **Update Desk Dial first, then the firmware.**

1. **Desk Dial.** Quit Desk Dial from the tray, then unzip the 2.0.0 release over the old folder. Your settings stay in `%LOCALAPPDATA%\DeskDial`. Start it. It works with your current firmware, with the reduced features [listed above](#desk-dial-200-with-firmware-v10--v11).
2. **Firmware.** Follow the [flashing guide](flashing.md). Make a **new** full backup first, even if you have one from an earlier install.
3. **Done.** When the knob reconnects, Desk Dial picks up the new features on its own. You don't need to change any setting.

In this order, there is never a moment when the app is older than the knob. To go back, restore the firmware first ([recovery](recovery.md)), then the app if you want to. The app rollback is optional, because Desk Dial 2.0.0 also works with the old firmware.

## What has been tested

### Hardware

Desk Dial has been tested on **one Nano_D++, the author's**. Everything else is untested.

| | Status |
|---|---|
| Nano_D++, early batch: ESP32-S3 (revision v0.1), 4 MB flash with PSRAM, Karl's firmware v1.0.0 as delivered | **Tested** (one knob) |
| Other Nano_D++ batches or board revisions | Untested |
| ESP32-S3 revision v0.2 or later | Untested |
| A knob whose partition table differs from Karl's v1.0.0 (the flashing guide checks this) | Not supported. Don't flash it |
| Ratchet H1, or any other board that shares Karl's firmware repository | **Don't flash it** |
| Knob powered from a PC USB port (5 V) | **Tested** |
| Knob on a 9 V USB-C Power Delivery supply | Untested. The firmware is meant to scale the motor to the higher voltage |
| One PC, Windows 11 | Tested. Windows 10 is supported but untested |

The firmware is written for the Nano_D++ motor (7 pole pairs, 5.3 Ω), its MT6701 angle sensor and 4 MB of flash. A board with different parts can feel wrong, fail to calibrate or fail to start. esptool prints your chip revision when it connects (`Chip is ESP32-S3 ... (revision v0.x)`), and Step 2 of the flashing guide checks the flash layout.

If you try Desk Dial on a knob that is not in the tested row, please report how it went in an [issue](https://github.com/hooterjackson/desk-dial/issues), whether it worked or not.

### Features not yet tested on real hardware

These are in v2.0.0 and covered by automated tests, but they have not yet been tried on a real knob:

| Feature | What it does |
|---|---|
| **Volume knob without the app** | With Desk Dial closed, the knob changes the Windows volume, 36 steps per turn |
| **Dim and sleep** | The screen dims after 10 minutes without input and everything switches off after 60 minutes. The first press or turn wakes it and is otherwise ignored |
| **End-stop easing** | If you keep leaning on an end stop for a long time, its push-back eases to about half, to protect the motor |
| **Self-spin trip** | If the knob ever spins on its own for 2 seconds (for example after a bad calibration), it goes limp until you press a button. Spinning it yourself faster than about 2.4 turns a second for 2 seconds trips it too |
| **Motor recalibration** | The firmware supports it, but Desk Dial 2.0.0 does not offer it in Settings |

### App profiles

The badges in Settings › Apps tell you how far each profile has been checked:

| App | Badge | Meaning |
|---|---|---|
| Onshape | **Tested** | Tried by the author on Windows, in Chrome |
| Figma | **Not yet tested** | Shortcuts mapped from Karl Malota's Mac profile to Windows and checked against Figma's documentation, but not tried |
| Plasticity | **Not yet tested** | Same as Figma |
| Blender | **Basic** | The knob scrolls; no command wheel |
| AutoCAD | **Basic** | Same as Blender |

If you try a "Not yet tested" profile, please tell us in an [issue](https://github.com/hooterjackson/desk-dial/issues) how it went.

More: [flashing](flashing.md) · [recovery](recovery.md) · [FAQ](faq.md) · [changelog](../CHANGELOG.md)
