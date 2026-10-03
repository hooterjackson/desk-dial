# Questions and troubleshooting

Desk Dial is a Windows program that turns a Nano_D++ knob into a controller for Sonos speakers, Apple Music, Home Assistant lights, your open windows and Onshape. This page answers the questions people ask first, then walks through the messages you may see when something is not working.

A note on words: a *detent* is one click of the knob as you turn it. The four buttons under the screen are *button 1* to *button 4*, left to right. "Tap 1" means press and release button 1; "hold 1" means keep it down until the knob answers.

The project is tested on one knob, the author's. If your knob behaves differently, please say so in an issue.

## Questions

### Does it work with Spotify?

No. Music comes from two places only: a Sonos speaker on your network, and Apple Music through Apple's own developer interface. There is no Spotify support in this release.

Without any music service set up, the knob still does three things: it switches and snaps your open windows (button 2 on the Home screen), it drives Home Assistant lights once you add an address and an access token (button 3), and it works in Onshape in Chrome or Edge. With a Sonos speaker but no Apple Music, the knob changes the group volume, plays and pauses, skips and seeks within the song, and shows the Sonos queue. Recently Added, Playlists, Play next and Like all need Apple Music.

### Which apps besides Onshape?

Figma and Plasticity (not yet tested: their shortcuts come from Karl's profiles, mapped to Windows), and Blender and AutoCAD (basic: the knob scrolls only), from Karl Malota's Nano_D app profiles. Each is Off until you set it to Manual or Auto in Settings › Apps, and you can import more. See [Apps](features/apps.md).

### Does it run on a Mac or on Linux?

No. Desk Dial is a Windows 10/11 program. It depends on Windows features throughout: the Windows credential encryption (DPAPI), the window-snapping and live-preview interfaces, UI Automation for the Onshape check and the system tray.

### Can I turn the clicks and sounds off?

Yes, in Settings › Knob:

- **Knob sounds** On/Off and a **Volume** slider from 0 to 100 in steps of 5. The default is On at 100 %. Turn sounds Off and the knob's speaker stays silent; the motor still gives you the clicks you feel.
- **Reduced haptics** Off/On. On gives softer, quieter steps with no click sound as you turn, and one short pulse instead of a thump or buzz for events. The end stops stay: the knob still stops at the end of a list or at 100 %.

What stays no matter what: the end stops, and the small tick you feel on every accepted button press.

### Why does the knob vibrate or hum?

It should not, once you let go. 250 ms after the knob stops moving the motor goes quiet and stays quiet until you turn it about one click. Inactivity does the rest: the screen dims after 10 minutes without input and everything switches off after 60 minutes; a press or a 2° turn wakes it, and that waking input is swallowed so nothing changes by accident.

If you can hear the knob humming while nobody touches it, that is a bug. Open Settings on the PC: the status strip at the top shows the firmware version the knob reported. Put that version and the Desk Dial version in your issue, together with what screen the knob was on.

### What happens when the app is not running?

The knob returns to its own screen. Once the PC drops the connection it shows "Waiting for PC" with "Open Desk Dial on your PC" underneath, and reconnects on its own when the app comes back.

The firmware is also designed to act as a plain volume knob while no program on the PC holds its port: after the port has been closed for 2 seconds it sends Windows volume up and down, 36 clicks per turn with no end stop. Its screen then reads "PC volume" and shows a brief + or − on each step; there is no number or arc, because the knob cannot read the PC's volume level. This part has not yet been tested on real hardware.

### Can I use several knobs?

Not with one PC. Desk Dial looks for exactly one knob by its USB identity. With two knobs plugged in it connects to neither, and the tray says "Knob not found" until one of them is unplugged.

### Does it keep my knob's profiles?

Yes. Every time the app connects it reads the profiles and settings stored on the knob and writes them, unchanged, to a backup file under `%LOCALAPPDATA%\DeskDial\backups\` (one file per connection, see [Privacy](privacy.md)). The app refuses to take control of the knob until that backup exists. Nothing from Desk Dial is written to the knob's storage: the feel, sound and LED settings are sent with each session and forgotten when the knob restarts. Karl's own profiles stay as they are.

### How do I go back to Karl's firmware?

Follow the [flashing guide](flashing.md). It covers backing up, flashing the Desk Dial firmware, and restoring the stock firmware. If a flash goes wrong, see [Recovery](recovery.md).

### Which app version works with which firmware?

See the [compatibility table](compatibility.md). In short: the knob needs the Desk Dial firmware from the matching release (v2.0.0); with Karl's stock firmware the app connects, backs up the profiles, and then stops at "Stock firmware · display/control extension required".

## Troubleshooting

### The tray says "Knob not found"

Check in this order:

1. **One knob, one cable.** Desk Dial connects to exactly one knob. Unplug any second knob. Try a different USB cable: some charging cables carry no data.
2. **Give it a few seconds.** The app looks again every few seconds; you do not need to restart it.
3. **Another program has the port.** Close Arduino IDE, PlatformIO monitors, Karl's Nano_D web configurator or anything else that may be talking to the knob.
4. **"Stock firmware · display/control extension required"** in the tray means the knob answered but runs Karl's firmware. Flash the Desk Dial firmware as described in the [flashing guide](flashing.md).
5. **"F24 is unavailable · close the conflicting hotkey app"** means another program has claimed the F24 key, which the knob uses to open the Windows picker (the only way Windows lets the picker take focus). Find the program that registered F24 (macro tools and keyboard utilities are the usual suspects), close it, then reconnect the knob from the tray.

### No album artwork

- Settings › Music › **Album artwork** must be On.
- Covers come from two sources only: Apple's artwork servers for songs Apple Music knows, and the Sonos speaker itself for what it is playing. Anything the speaker plays from another service (radio, line-in, a different streaming provider) shows no cover.
- Covers are kept in memory only; after a restart they load again.

### Lights say "Not connected" or "Open Settings on your PC"

The knob shows "Not connected" with "Open Settings on your PC" while Home Assistant is not set up or cannot be reached. In Settings › Home Assistant, press **Test connection** and read the status column:

- **"Can’t reach Home Assistant on this network."** The address is wrong, Home Assistant is down, or the PC is on another network. Try the same address in a browser on this PC. The address must start with `http://` or `https://` (for example `http://homeassistant.local:8123`).
- **"Token rejected (401)."** Home Assistant refused the long-lived access token. Create a new one: in Home Assistant open your profile, then Security, then "Long-lived access tokens", and paste the whole token.
- **"Area not found."** The area you chose was renamed or deleted in Home Assistant. Choose it again and press Save.

The knob drives every light in the chosen area, including lights you add later.

### No sound from the knob

- Settings › Knob › **Knob sounds** must be On and **Volume** above 0.
- **Reduced haptics** On silences the clicks you hear while turning; only event sounds remain.
- Sounds are part of the Desk Dial firmware. With the stock firmware there are none, and an older Desk Dial firmware ignores the sound settings. Check the firmware version in the Settings status strip and compare it with the [compatibility table](compatibility.md).

### Buttons do nothing in Onshape

- In Settings › Apps, **Onshape** must be Manual or Auto (Off unless you used it before). With Manual, switch it on from the tray's **App mode** menu.
- Onshape must be open in a Chromium browser: tested in **Chrome**; Edge, Brave, Vivaldi and Opera are recognised, not yet tried. Firefox is not supported.
- The knob shows **"Point at the model"** when your mouse pointer is not over the Onshape page in the front window. Move the pointer onto the model and try again. The toolbar, the tab strip and the bookmarks bar do not count.
- A browser running as administrator does not accept input from a normal program. Start the browser normally.

### Windows says "Windows protected your PC"

The program is not signed with a code-signing certificate, so Windows SmartScreen warns on the first start. Click **More info**, then **Run anyway**. On Windows 11 with Smart App Control switched on, Windows may block the program outright with no "Run anyway" option. Smart App Control can only be turned off in Windows Security › App & browser control, and once off it cannot be turned on again without reinstalling Windows; decide for yourself whether that trade-off is worth it.

### Sharing logs safely

When you open an issue, attach:

- `%LOCALAPPDATA%\DeskDial\logs\app.log` (and `app.log.1` if the problem is older)
- `%LOCALAPPDATA%\DeskDial\logs\crash.log` if the app closed on its own
- `%LOCALAPPDATA%\DeskDial\logs\status.json`

Before you attach them, open each file in a text editor and replace your Windows user name wherever it appears in a path (`C:\Users\<you>\...`). `status.json` also lists your Home Assistant area and light ids; remove them if you prefer.

Never attach anything from `data\`, `backups\` or the `credentials.bin` file. They hold your speaker address, your knob's serial number and your encrypted keys. See [Privacy](privacy.md) for what every file contains.

## Limits and known issues

- Tested on one knob, the author's. Recalibrate motor, which other knobs may need, has not yet been tested on real hardware.
- A self-signed `https://` certificate on Home Assistant has not yet been tested on real hardware and will likely be rejected.
- Onshape: the tilt direction and tool-search hits are unverified.
- Spotify and other streaming services are not supported; Sonos and Apple Music only.
- Windows 10/11 only.
- Exactly one knob per PC.
- The offline Windows-volume mode of the firmware has not yet been tested on real hardware.
- Onshape and the other apps: Chromium browsers only, not Firefox. Shortcuts follow your keyboard layout ("Not on this keyboard" when a key is missing); non-US layouts are not yet tried on real hardware.
- Figma and Plasticity are not yet tested; Blender and AutoCAD are basic (the knob scrolls only). See [Apps](features/apps.md).
- The program is unsigned; SmartScreen warns on the first start and Smart App Control may block it.
- The Home Assistant token crosses your network unencrypted when the address starts with `http://`; Settings shows a warning under the address when it does.
