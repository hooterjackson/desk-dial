# Troubleshooting

This page covers problems with the knob, the firmware and the services Desk Dial talks to, and how to collect diagnostics you can share without giving away personal data. For the app's own messages ("Knob not found", "Token rejected (401)", "Point at the model" and the rest) and what each one means, see the [FAQ's troubleshooting section](faq.md#troubleshooting) first. This page does not repeat it.

Words used here: a *detent* is one click of the knob. The buttons are *button 1* to *button 4*, left to right. Settings paths such as **Settings › Apps** mean: right-click the Desk Dial icon in the tray, open Settings, then choose that page.

Desk Dial v2.0.0 has been tested on one knob, the author's. If yours behaves differently, please [open an issue](https://github.com/hooterjackson/desk-dial/issues).

## The knob is not found

The tray reads "Knob not found" and the knob shows "Waiting for PC".

1. **Check that Windows sees the knob.** Open Device Manager and look under **Ports (COM & LPT)**. In PowerShell, with Desk Dial's Python or any Python that has pySerial:

   ```powershell
   python -m serial.tools.list_ports -v
   ```

   The knob is the port whose details include `VID:PID=239A:8010`. If there is no such port, try another USB-C cable (some only charge), plug the knob straight into the PC rather than a hub, and try another USB port.
2. **Only one knob.** With two knobs plugged in, Desk Dial connects to neither and the tray says "Two knobs found · unplug one, or choose its USB port in Settings".
3. **The firmware.** "Stock firmware · display/control extension required" means the knob still runs Karl's firmware. Follow the [flashing guide](flashing.md). If the knob only shows up as `303A:1001`, it is waiting in its bootloader: unplug it and plug it back in.
4. **Wait a few seconds.** Desk Dial looks for the knob again every few seconds, so you do not need to restart it.

More checks, including the F24 hotkey conflict, are in the [FAQ](faq.md#the-tray-says-knob-not-found).

## The port is busy

Only one program can have the knob's port open at a time. While another program holds it, Desk Dial cannot connect and the tray keeps saying "Knob not found". The flashing commands fail with `Could not open port` or `Access is denied`.

- Close Karl's Nano_D web configurator, the Arduino IDE, PlatformIO's serial monitor, PuTTY and any other serial terminal.
- Make sure only one Desk Dial runs. Check the tray and Task Manager for `DeskDial.exe`, and for `python.exe` if you run it from source.
- Before you flash, quit Desk Dial from the tray (**Quit**). The flashing steps need the port to themselves.
- If the port stays busy after closing everything, unplug the knob, wait five seconds and plug it back in.

## The screen is black (or red) after flashing

First, rule out the normal cases:

- **The knob is asleep.** After 60 minutes without a touch, the screen, the lights and the motor switch off. Turn the knob or press a button: the first touch only wakes it.
- **It is still starting.** When the motor has to align itself, often on the first start after a flash, the screen reads "Calibrating - hands off". Leave the knob alone until it finishes. "Calibration failed - replug" means it was touched or blocked: unplug it and plug it back in without touching it.
- **Desk Dial is not running.** Without the app the knob shows its own screen: "Waiting for PC", or "PC volume" once Desk Dial has used this knob before.

If the screen stays dark (or stays on the old firmware's picture) while the knob otherwise works, so it still turns with detents, lights up and connects to Desk Dial, the image was most likely a **mixed build**. This happens to firmware built from source, never to the release file. An incremental PlatformIO build after a change to `include/lv_conf.h` links two incompatible layouts of the screen library, and the screen never draws. v2.0.0 detects a mixed image at start-up and shows a **red screen with a white "!"** instead. The knob still works as a dial, so it is not bricked.

To fix it:

1. Build again, clean, exactly as in [building the firmware](build-firmware.md#build-always-clean).
2. Flash the new image with the [flashing guide](flashing.md).

If you flashed the release file and the screen stays dark, check the download against `SHA256SUMS`, then flash and verify again. If the knob does not start at all, see [recovery](recovery.md).

## No sound from the knob

- **Settings › Knob › Knob sounds** must be **On**, and the **Volume** slider above 0. The volume is the knob speaker's master volume, from 0 to 100 in steps of 5; it does not follow the PC's volume.
- **Reduced haptics** On silences the clicks you hear while turning. Event sounds stay.
- Sounds need the Desk Dial firmware v2.0.0. Karl's firmware plays none, and older Desk Dial firmware ignores these settings. The Settings status strip shows the firmware the knob reported; it should start with `2.0.0`. See [compatibility](compatibility.md).

## Onshape or another app does not switch

The knob should change to the app's screen when you work in Onshape, Figma, Plasticity, Blender or AutoCAD. If it does not:

1. **The app's mode.** In **Settings › Apps**, the app must be **Manual** or **Auto**. Every app is Off until you choose (Onshape keeps the mode you chose before v2.0.0).
   - **Auto** switches the knob to the app whenever that app is the front window.
   - **Manual** switches only when you choose the app in the tray's **App mode** menu.
2. **The browser.** Onshape and Figma in the browser are recognised by the address bar's host in **Chrome, Edge, Brave, Vivaldi or Opera**. Only Chrome has been tried; **Firefox is not supported**. Desktop apps are recognised by their program file (`Figma.exe`, `Plasticity.exe`, `blender.exe`, `acad.exe`). To add a program or a website, use **Rules…** on the app's row.
3. **The pointer and the focus.** Buttons and keys go to the app only while the mouse pointer is over it ("Point at the model" or "Point at the app") and it has the keyboard focus ("Click the model first" or "Click the app first"). Click into the page or the app once.
4. **Apps running as administrator get nothing.** Windows blocks input from a normal program into an elevated one, and the knob shows no message. Start the app (or the browser) normally.
5. **Held keys.** While you hold Ctrl, Shift, Alt or the Windows key on the keyboard, the knob's shortcuts and typed values are skipped.
6. **The lock screen.** On the lock screen and on a UAC prompt, nothing is sent at all.
7. **The tray says why.** If the tray answers "Turn Onshape on in Settings › Apps first." or "Onshape needs the knob connected (firmware with the r3 screens).", do what it says.

Shortcuts follow your keyboard layout. If a key does not exist on your layout, the knob says "Not on this keyboard" and sends nothing. See [Apps](features/apps.md) for each app's commands and limits.

## Home Assistant does not connect

In **Settings › Home Assistant**, press **Test connection** and read the status. The FAQ explains [each message](faq.md#troubleshooting). The usual causes:

- **http or https.** The address must start with `http://` or `https://` and include the port, for example `http://homeassistant.local:8123`. Use the scheme your Home Assistant actually serves: an `https://` address against a plain-http server fails, and the other way round too.
  - With `http://` the token crosses your network unencrypted, and Settings shows a note under the address saying so.
  - With `https://` the certificate is checked, so a self-signed certificate is most likely refused (not yet tested).
- **The token.** Use a **long-lived access token** from your Home Assistant profile (Security, "Long-lived access tokens"). Paste all of it.
  - "Token rejected (401)": create a new token and paste it again.
  - The saved token is sent only to the saved address. After changing the address, paste the token again.
  - After a rejected token, Desk Dial waits before it tries again: 60 seconds, then longer each time, up to an hour, so it does not trip Home Assistant's login ban.
- **"Blocked by Home Assistant"** (403): Home Assistant has banned this PC after too many failed logins. Remove the PC's IP address from `ip_bans.yaml` in your Home Assistant configuration, then restart Home Assistant.
- **A proxy.** Desk Dial talks to a Home Assistant on your local network directly, without the Windows proxy, so a proxy setting is not the cause for a local address.

## Sonos is not found

The knob says "Looking for Sonos…" and then "Sonos unavailable", and the Settings strip reads "Not found".

- **Desk Dial does not search for speakers.** Type the speaker's IPv4 address in **Settings › Music** (Sonos app: Settings, System, About My System). If your router gave the speaker a new address, type the new one. A reserved (static) address in your router stops this from happening again.
- **Restart after changing the speaker.** Quit Desk Dial from the tray and start it again; the new address is used from then on.
- **Same network.** The PC and the speaker must be on the same local network. Guest Wi-Fi, a VPN on the PC or a separate network for smart devices usually blocks the connection.
- **The main speaker.** For a stereo pair or a home-theatre set, use the main speaker's address, not its partner or Sub. Desk Dial says so if you picked the wrong one.
- Nothing needs opening in Windows Firewall. Desk Dial only makes outgoing connections to the speaker (port 1400).

More in [setting up Sonos](setup/sonos.md).

## Collecting diagnostics without personal data

When you report a problem, a few files help a lot. Some of them contain details about your home, so look at each file before you attach it.

### Where the files are

Everything Desk Dial writes is under `%LOCALAPPDATA%\DeskDial\`. Paste that into the Explorer address bar to open it. The logs are in `%LOCALAPPDATA%\DeskDial\logs\`:

| File | What it is | Safe to share? |
|---|---|---|
| `status.json` | A snapshot of the running app, rewritten while it runs | **The safest file.** Edit the fields below first. |
| `app.log` (and `app.log.1` to `.3`) | The app's diary: connections, errors, state changes | Only after reading and editing it |
| `crash.log` | Written only if the app dies: a stack trace of every thread | Usually, after replacing your user name |
| `smoke-test.json`, `music-check.json` | Results of the self-tests, if you ran them | Yes, after replacing your user name |

**Never share** anything from `%LOCALAPPDATA%\DeskDial\data\` (your speaker address, settings and the encrypted `credentials.bin`), the other `.bin` files, or anything in `backups\` (your knob's serial number and profiles). Do not post a full flash backup of the knob either: it holds the serial number and your settings.

### What the logs may contain

By design, no file in `logs\` contains a token, a password, a window title or a browser address. They can still contain things you may not want to publish:

- **Your Windows user name**, inside file paths (the user-folder part of each path), in `status.json`, `app.log` and `crash.log`.
- **Your Home Assistant area, light and scene names and ids**, which are usually named after your rooms (for example `light.<room>_lamp`), in `status.json` and `app.log`.
- **Your Sonos room name, or a speaker or Home Assistant address,** in an error line of `app.log`.

**Before you share a file, open it in a text editor and replace these with neutral text,** for example your user name → `me`, `living_room` → `room1`, and any IP address → `x.x.x.x`. Keep the structure of the file intact.

### status.json, field by field

`status.json` was designed for sharing. It never carries a token, the Home Assistant address, a window title or a web address. Check these fields before you send it:

| Field | Contains | What to do |
|---|---|---|
| `executable`, `dataDir` | Paths that include your Windows user name | Replace the user name |
| `lights` | Your Home Assistant area id and name, and the ids and names of its lights and scenes | Rename them, or delete them |
| `connected`, `deviceStatus`, `firmware`, `firmwarePresentation` | Whether the knob is connected and what its firmware can do | Keep: this is what helps most |
| `mode`, `screenStatus`, `ready`, `loading` | The knob's current screen | Keep |
| `sonosOnline`, `playback`, `volume` | Whether the speaker answers, play state and volume (never a song title) | Keep |
| `musicAuthorized` | Whether Apple Music is set up (yes or no, never the token) | Keep |
| `onshape`, `app` | The app modes, which app is active, whether it matched by program or website, and refusal counters | Keep |
| `knobFeel`, `frames`, `stage`, `overlay`, `fastPath`, `media`, `process` | Counters and timings | Keep |
| `startupCredentialFile` | Whether `credentials.bin` exists, its size and a hash of the encrypted file (never its contents) | Keep or delete |

### Your versions

Put both versions in your report. They are shown in the status strip at the top of the Settings window: the Desk Dial version and the firmware version the knob reported (for example `2.0.0+cc5.8.F`).

## Getting help

- **Bugs and questions:** [GitHub Issues](https://github.com/hooterjackson/desk-dial/issues). Say what you did, what you expected and what happened, and attach the edited files from above.
- **The knob itself** (hardware, Karl's firmware and configurator): [Karl's Discord](https://discord.gg/mVTvppcfp6).

See also: [FAQ](faq.md) · [privacy](privacy.md) · [flashing](flashing.md) · [recovery](recovery.md) · [compatibility](compatibility.md).
