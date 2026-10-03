# Changelog

All notable changes to Desk Dial (the Windows app and the knob firmware) are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

From v2.0.0 on, the app and the firmware share one version number.

## [2.0.0] - 2026-10-03

A large update, both for the app and for the knob firmware. Install both: Desk Dial v2.0.0 and the knob firmware v2.0.0. If you are upgrading from v1.1, see [compatibility](docs/compatibility.md) for the order.

### Added

- **App profiles.** The knob now follows the program you work in, using Karl Malota's Nano_D app profiles (with his permission), mapped to Windows shortcuts:
  - Onshape: Tested.
  - Figma and Plasticity: Not yet tested.
  - Blender and AutoCAD: Basic (the knob scrolls only).
- **Settings › Apps.** One row per app, each Off, Manual or Auto:
  - **Rules…** adds your own programs or websites to an app.
  - **Import profile…** and **Open profiles folder** add profiles of your own.
  - **Check for updates** fetches updated profiles. The daily fetch is off by default; when on, it makes one plain HTTPS request to this repository and sends nothing about you.
- **Automatic app detection.** Desk Dial recognises a desktop app by its program file, and a web app by the website's host in Chrome, Edge, Brave, Vivaldi or Opera. It reads only the program name and the host, and only for apps that are not Off.
- **App mode in the tray.** The tray's **App mode** menu switches an app on and off by hand.
- **App screens on the knob.** The knob receives each app's profile over USB and draws its screen: icon, command wheel and cards. Profiles are kept in the knob's memory only, never in its storage.
- **Onshape mode, with Karl's Onshape UI on the knob** (adapted with his permission):
  - turn to zoom; hold a button and turn to tilt, orbit or pan;
  - a wheel of command cards on hold 3, and a parameter mode for typing values;
  - a wireframe cube that turns with the view;
  - hold all four buttons for a second to go back Home.
- **Safety rules for every app.** Desk Dial refuses shortcuts that leave the app, such as the Windows key, Alt+Tab, Alt+F4 and the browser's tab keys. It never targets a terminal or Windows' own shell, and sends nothing on the lock screen or a UAC prompt. Typed text needs the app to have the keyboard focus. Shortcuts follow your keyboard layout, and a key your layout lacks is refused with "Not on this keyboard".
- **Home Assistant lights:**
  - brightness and warmth for one area from the knob;
  - the area's scenes, scripts and automations;
  - All off and Turn on, which restores the lights as they were.
  - Settings has a **Test connection** button, and shows a note when the token would travel unencrypted over `http://`.
- **The Navigator.** A small frosted-glass card at the edge of the screen shows where you are on the knob and what the four buttons do. It is click-through and never takes focus.
- **A feel for every control** (the "r4" feel). Each kind of control has its own detents, with a firm wall at each end and a thud when you hit it.
  - Every button press gives one haptic tick, and an action that waits for a speaker gives its haptic at the press, not twice.
  - The motor goes quiet 250 ms after the knob stops, including when it rests against a wall.
  - **Reduced haptics** gives softer steps and one short pulse instead of thumps.
- **Knob sounds:** clicks and thumps synthesised on the knob, after Karl's sound design (with his permission). **Settings › Knob** has **Knob sounds** On/Off and a **Volume** slider from 0 to 100 %.
- **Offline PC volume.** With no program connected to the knob for 2 seconds, it works as a plain Windows volume knob (36 clicks per turn). Its screen reads "PC volume", with a brief + or − on each step. This only starts on a knob that Desk Dial has connected to at least once, so knobs used with their own MIDI or keyboard profiles keep working.
- **Play next lands in green.** Holding button 4 to play a song next (or add it to the queue) flashes the ring green when it lands.
- **Motor calibration messages.** While the motor aligns, the knob shows "Calibrating - hands off". If the alignment fails, it shows "Calibration failed - replug" instead of silently ignoring turns.
- **Version display.** The knob reports its full version, for example `2.0.0+cc5.8.F`, and the Settings status strip shows it next to the app's version.
- **Mixed-build detection.** A firmware image built with two different LVGL configurations shows a red screen with a white "!" instead of drawing garbage, and reports it in its diagnostics.
- **`Uninstall-Desktop.ps1`** removes a from-source install (program folder, sign-in task, Start-menu shortcut). It keeps your data unless you add `-RemoveData`.
- **Guides:** [flashing](docs/flashing.md), [recovery](docs/recovery.md), [compatibility](docs/compatibility.md), [building the firmware](docs/build-firmware.md), [building the app](docs/build-app.md) and [troubleshooting](docs/troubleshooting.md), plus feature, setup and [privacy](docs/privacy.md) pages.
- **A GitHub Action that proposes Karl's updated profiles.** It opens one pull request for review and never merges anything.

### Changed

- **One version for the app and the firmware.** Both are v2.0.0. The knob's version string starts with the public version, followed by the internal build id and the binary letter.
- **Binary F is the recommended firmware.** It refreshes the screen every 12 ms instead of every 16 ms. Binary D is the same code at the old refresh rate, kept as a fallback ([building the firmware](docs/build-firmware.md)).
- **The Onshape setting moved.** It was Settings › Knob › Onshape mode and is now the Onshape row in **Settings › Apps**. Your previous choice is carried over. The tray's "Onshape mode" item became the **App mode** menu.
- **New knob sounds.** The firmware's old recorded sound files are gone; every click and thump is synthesised.
- **Offline PC volume needs one Desk Dial connection first** (see Added), so the knob never takes over the volume on a PC that never ran Desk Dial.
- **A smaller app.** The app bundle is about 11 MB smaller: unused image codecs, XML extras and Tcl's time-zone data are left out.

### Fixed

This release fixes 177 issues found in a pre-release audit of the app, the firmware and the tools. The notable ones, by area:

- **Settings and credentials.** `settings.json` is now always written atomically, a file with a byte-order mark is read correctly, and a damaged file is set aside instead of being silently replaced by defaults. Signing in to Apple Music no longer deletes the saved Home Assistant token. An unreadable credential file, for example after a Windows password reset, or an IPv6 speaker address no longer stops Desk Dial from starting. The Home Assistant token is only ever sent to the address it was saved for.
- **No personal defaults.** Desk Dial no longer ships the author's Sonos room as a default. That default made Sonos report "room no longer available" for everyone else. A new speaker address now forgets the old room. Speaker, room and light labels in the app and the simulator are neutral, and the Apple Team ID field starts empty.
- **Motor safety.**
  - Raw register writes can no longer switch the motor out of its safe mode or raise the voltage past the 2.2 V cap; only an allow-list of registers is accepted, each range-checked.
  - The motor supply estimate assumes the higher voltage when the USB-PD contract cannot be read.
- **Calibration.** The motor calibration is stored as one checked entry, and implausible data is rejected at boot. A failed alignment is retried once and never leaves an uncalibrated motor running after a wake.
- **Knob crashes and hangs.**
  - Connecting after a profile was deleted in another configurator no longer crashes and restarts the knob.
  - An empty or deleted current profile can no longer leave the knob unmapped.
  - A PC program that keeps the port open but stops reading no longer stalls the knob into a watchdog reset.
  - Several memory leaks on the serial path are closed, and the screen library's memory pool is larger.
- **Feel.** Slow turns of volume and brightness no longer over-count, step backwards or drop clicks. A profile change keeps the detents where the shaft is. The wall's thud now comes together with its force. A haptic event during a detent pulse is no longer lost.
- **Power.** While the knob sleeps, nothing is drawn. Before, the hidden screen was still rendered at full rate.
- **Keys and USB.** Keys held when Desk Dial disconnects, or when a profile changes, are released instead of auto-repeating. A key binding sends exactly its own key codes. MIDI knob values stay in range.
- **Profiles on the knob.** Profile names now fit the knob's file system: a long name was accepted but never saved. Reading an unknown profile no longer creates it. The knob no longer reports a stored Wi-Fi password.
- **Home Assistant.**
  - After a rejected token, Desk Dial backs off (from 60 s up to 1 h) instead of retrying every minute; a ban (403) is shown as "Blocked by Home Assistant", with the fix.
  - Turn on works again after a Home Assistant restart.
  - The fallback mode makes one request per refresh instead of one per light.
  - Local addresses bypass the system proxy.
  - Areas with more than 32 lights are fully controlled.
- **Sonos and Apple Music.**
  - The volume no longer jumps after the speaker was offline.
  - The Up next queue is remembered across restarts.
  - Shuffle moves no longer clash with queue changes made elsewhere, and a speaker's volume limit is accepted.
  - A never-connected Apple Music asks you to connect instead of saying the sign-in expired.
  - Covers that load slowly time out on schedule.
- **Connection.**
  - A knob that is missing one of Desk Dial's expected profiles is no longer reconnected in an endless loop.
  - A knob on stock firmware is no longer reconnected every 70 seconds, writing a new backup file each time.
  - With two knobs plugged in, the tray says so.
  - A lost key release no longer swallows the next press.
  - Quit really ends the program, after releasing the knob first.
- **Onshape and privacy.**
  - With every app Off, Desk Dial no longer reads the front window or the browser's address bar.
  - The address bar's host decides whether a page is Onshape, so a page merely titled "Onshape" no longer counts.
  - Keystrokes need the keyboard focus in the page.
  - A drag ends when another window comes to the front.
  - Shortcuts carry the right key codes for your layout, and typed values carry their unit.
- **Settings window.**
  - The Knob page scrolls and its notes are no longer clipped, and Settings never grows past the screen.
  - The Home Assistant light list scrolls.
  - The tray's Show knob explains when there is nothing to show, and the status strip names a stock-firmware knob or a busy F24 hotkey.
- **Install and files.**
  - `Install-Desktop.ps1` stages the new program, verifies it and restores the previous one on failure, and works on a fresh clone.
  - `status.json` is written atomically and only when it changes. It reports the playback state but never a title.
  - PyJWT is updated to 2.15.0.
- **Firmware build.**
  - A change to `lv_conf.h` now rebuilds every object; mixed builds made the screen stay dark.
  - Every library is pinned, including the indirect ones, so a fresh clone builds what the release did.
  - The image no longer contains the build machine's folder names.
- **Flashing tools.** The tools check the knob's identity before sending the bootloader signal, find the knob by its USB identity rather than a fixed COM port, and refuse to run while Desk Dial holds the port.

### Known issues

- **Tested on one knob,** the author's, powered from a PC's USB port. Not yet tested on real hardware:
  - the app profiles other than Onshape (Figma, Plasticity, Blender, AutoCAD);
  - Onshape's tilt direction and tool-search hits;
  - Onshape in Edge, Brave, Vivaldi and Opera (Chrome only);
  - non-US keyboard layouts;
  - the offline PC volume mode;
  - the screen dimming after 10 minutes and sleeping after 60;
  - a **9 V USB-C Power Delivery supply** (the firmware scales the motor for it, but nobody has measured it on a knob);
  - a self-signed `https://` certificate on Home Assistant (likely refused).
- **Windows 10 and 11 only.** No macOS or Linux. One knob per PC.
- **Firefox is not supported** for Onshape and the other web apps.
- **Apps running as administrator** cannot receive the knob's input (Windows blocks it), and the knob shows no message.
- **Spotify and other streaming services** are not supported; music is Sonos and Apple Music only.
- **The app is not code-signed.** SmartScreen warns on the first start, and Smart App Control on Windows 11 may block it.
- **`http://` Home Assistant.** With an `http://` address, the Home Assistant token crosses your network unencrypted. Settings warns about it.
- **Sonos setup.** Speakers are not discovered; you type the address, and a speaker change needs a restart of Desk Dial.

## [1.1] - 2026-09-28

Knob firmware only (1.0.0-cc5.4 with sleep). The app stayed at v1.0.

### Added

- **Dims after 10 minutes** without a touch (screen to about 20 %). Any turn or press brightens it again.
- **Sleeps after an hour.** The screen goes dark, the ring and button lights turn off and the motor powers down. Music playing does not keep it awake.
- **Wakes on the first turn or press,** and that first touch only wakes it: no volume change, no skipped song. The value never jumps on wake.

## [1.0] - 2026-09-27

The first public release: the Desk Dial app for Windows and the knob firmware 1.0.0-cc5.4.

### Added

- **Sonos volume on the knob,** with a warm-white LED arc (amber from 80 %, red from 90 %).
- **Apple Music on the round screen:** Recently Added and your favourite playlists with album art, and play, skip and seek from the knob.
- **Up next** queue and **Play next**.
- **A Windows switcher and picker** driven from the knob.
- **A floating on-screen knob** on the desktop.
- **"Warm · alive" LEDs:** one steady dim warm white at rest, brighter when you touch the knob.
- Flashing tools that back up the knob first, verify every write and can roll back.

### Known issues

- Knob screen animations ran at about 15 fps.
- Windows only. Music needs a Sonos system and an Apple Music subscription.

[2.0.0]: https://github.com/hooterjackson/desk-dial/compare/v1.1...v2.0.0
[1.1]: https://github.com/hooterjackson/desk-dial/compare/v1.0...v1.1
[1.0]: https://github.com/hooterjackson/desk-dial/releases/tag/v1.0
