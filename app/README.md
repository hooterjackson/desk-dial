# Desk Dial

The knob's desktop companion, formerly the Nano_D++ control center (renamed 2026-09-26,
`design-reference/ui-v2-analysis/rename-desk-dial.md`).

A Python/Tk companion with one shared controller for the simulator and physical
knob. The four controls are Sonos group volume, Apple Music Recently Added,
Previous/Next, and a Windows window picker.

**The standalone Windows app and cc3 firmware are installed.**
Open **Desk Dial** from Start or its tray icon. Windows starts it
when you sign in; closing its window hides it to the tray. It runs independently
of Codex and reconnects to the knob with fresh state. Use the tray's Quit command
to stop it. See [standalone app instructions](DESKTOP.md).

The knob now has the corrected ring direction, raised and evenly spaced icon
footer, and white LEDs except for available cancel/confirm actions. The complete
flash verification and preservation of all ten saved profiles passed. The
standalone executable is running in live mode with the knob and the Sonos speaker connected.
Physical appearance and full live-feature acceptance remain separate from these
software and protocol checks. See [ACCEPTANCE.md](ACCEPTANCE.md).

## Warm · alive: firmware 1.0.0-cc5.4 + desktop v7 (built, not installed)

The next release is one combined firmware and desktop release. The firmware
(`firmware/ALIVE.md`, `PRESENTATION_V5.md`) renders the ring and button
LEDs itself from the frames (presentation 5). Desktop v7 (`DESKTOP_STAGE.md`,
[standalone app instructions](DESKTOP.md#warm--alive-desktop-v7-with-firmware-100-cc54))
mirrors those lights on the floating knob, draws the Explorer and Up next music
overlays on its own compositor thread, adds the Settings status strip and the
Motion setting, and sends knob turns to the floating knob straight from the USB
reader. Desktop v7 also works with a knob still on cc5.3 (presentation-4 frames).

- Bundle: `desktop-dist-v7-l` (`Build-Desktop.ps1`; its frozen
  `--smoke-test --headless` passes). Desktop rollback: `desktop-dist-v6`, from a
  knob on cc5.4 only after the firmware rollback to cc5.3 (cc5.4 names Desk Dial on
  the knob; `firmware/BUILD-cc5.4.md`).
- Firmware tooling: `tools/nanod_cc5_tooling.py` now names 1.0.0-cc5.4 as the
  current release (`CURRENT`); its build record carries the heap projection, and
  `rollback_nanod_cc5.py --to cc5.3` restores cc5.3 from the pre-cc5.4 backup.
- The simulator (**Launch.cmd**) gains a state picker for every simulated
  outcome (PC connection, playing source, Sonos shuffle and repeat, Play next,
  starting playback, seek, like, Up next, Favourite playlists, Recently Added);
  its PC connection drives a simulated alive knob.
- The hardware window (flash, device checks, hands-on acceptance) and the desktop
  install are still to come; until then cc5.3 and desktop v6 stay installed.

## Launch

- Double-click **Launch.cmd** for the complete simulator. It sends no speaker or
  desktop actions. Use the mouse wheel or arrow keys to turn, and click the four
  buttons below the dial.
- Double-click **Launch-Live.cmd** to use your configured Sonos speaker, your authorized Apple Music library,
  and real Windows windows. It does not automatically connect the knob. The same
  on-screen controls perform real actions in this mode.
- **Setup** contains the speaker IP, USB port, physical button calibration, and
  MusicKit authorization. A fresh install can run **Setup.cmd** first.

Python 3.10+ with Tk is required. This workspace has a local `.venv` with the pinned
dependencies installed. No background service or startup entry is installed.
The original desktop-input prototype is retained as `python app.py --legacy`.

## Four controls, four buttons

All four unlabeled buttons are below the knob. Their physical left-to-right roles
are **Back/Cancel · Browse/Home · Win · primary action**. The cc3 presentation uses
white by default, red for available Back/Cancel, and green for an available
confirmation. Dim white indicates disabled actions. The display retains action
cues above the icon row; the primary Tracks shortcut stays white on the home screen.

| Control | Existing installed profile | Turn | Green action |
|---|---|---|---|
| Volume / now playing | BINARIS BEER, 67 detents/revolution | 1 group-volume percentage point | Open Tracks |
| Recently Added | MIDI SKIPPER, 20 detents/revolution | 1 item or the explicit More entry | Play whole item / load More |
| Tracks | MIDI CLACK JONES, 8 detents/revolution | Previous / Neutral / Next | One skip, then recenter to Neutral |
| Windows | MIDI SKIPPER, 20 detents/revolution | 1 window in a frozen list | Switch to the chosen window |

Volume is live. Back does not undo it. Recently Added preserves Apple’s ordering,
shows ten items per page, and has a separate More entry. Play replaces the queue
after resolving the complete library selection and staging verified content.
Back restores the previous page and selection; Home returns to volume.

Win temporarily interrupts any screen. Red cancels to the previous screen and
original window. Home cancels to volume. Green switches and returns to volume.
Repeated Win presses leave the active picker intact. Turning never activates a
candidate. Escape cancels. External focus changes dismiss without stealing focus.
Closed windows retain their unavailable slot until the picker closes.

Previous selects the preceding queue track; it never seeks to the start of the
current track. Sources without a reliable predecessor, including shuffle history
that Sonos does not expose, show Previous as unavailable. Next uses Sonos’s current
transport capability. No long presses, double taps, knob presses, or hidden chords.

## Current local setup

- Sonos: the configured speaker, seeded from its IP address in Setup and pinned by its
  verified room UID. Group scope (stereo pair and Sub) is resolved from Sonos before
  commands.
- Apple: dedicated **NanoD Control Center** MusicKit credentials are configured
  and user authorization has completed. Live Recently Added and exact catalog
  resolution were verified. Credentials are encrypted with Windows DPAPI in
  `local/credentials.bin`, under the Windows user who authorized the application.
- Home Assistant (Lights): the address in Settings can be `https://` (the certificate
  is verified, and the live connection then uses `wss://`). With `http://`, the
  long-lived access token travels unencrypted on your network unless Home Assistant
  runs on the same PC; Settings shows a note under the address in that case.
- Knob: firmware `1.0.0-cc1` installed on 22 September 2026. The application
  returned on COM8 and reported host-control capability; all ten installed
  profiles were unchanged, with GRASSY HOPPER restored as the native selection.
  The full original flash, actual partition map, original application, and
  pre/post-install profile inventories are retained in `backups/`.

The `.p8` download is still your original private key; keep a private backup.
Do not check `local/`, `backups/`, credentials, or `.p8` files into source control.
The provided `.gitignore` excludes these locations.

## Hardware setup and recovery

1. Use `python app.py --list-ports` to find the current application port; COM8
   was observed after this installation.
2. Run `python device_inventory.py --port COM8` (substitute the observed port).
   This only reads inventory and creates a profile backup; it never arms control.
3. The extension is already installed. [firmware/RECOVERY.md](firmware/RECOVERY.md)
   records the verified application-only rollback procedure. Building or launching
   the companion does not flash firmware.
4. Choose Connect knob. The companion backs up
   all installed profiles, verifies capability, registers F24, and waits for the
   device’s readiness acknowledgment before accepting actions.
5. Button order is already verified and saved for this kit. To recalibrate, in
   Setup choose **Verify physical button order**. Press the leftmost button,
   then the remaining three in order. Save, disconnect, and reconnect to apply
   the physical-to-raw mapping consistently to input, LEDs, and the Win hotkey.
6. Complete the physical acceptance checklist in `ACCEPTANCE.md`.

Installation changed only the application image at `0x10000`. The full 4MB device
contents matched the expected post-install image, proving the flash operation
preserved the bootloader, partition table, OTA metadata, NVS/calibration, saved
profiles/filesystem, second application slot, and other bytes outside its erased
application sectors. This check was made before restarting the application;
normal firmware operation can subsequently update its own saved state.
The before/after installed-profile JSON matched exactly, and the filtered settings
comparison changed only `firmwareVersion`. Machine checks exercised all four
control entries and separate display/LED updates without sending Sonos actions
or Windows HID actions. Those acknowledgments do not replace hands-on checks.

The extension copies an existing profile into runtime state and changes only its
temporary bounds, logical position, and coordinate origin. Saved haptics and
calibration remain untouched. Display/LED frame updates do not re-enter the motor
profile. Host lease expiry releases ownership and displays a disconnected notice;
reconnect reads state afresh.

## Failure behavior

- Volume shows requested versus confirmed values. Writes are coalesced at a
  maximum of ten per second; pending old-group targets are discarded.
- Network requests run outside the UI/serial threads. Late responses cannot
  navigate a screen the user has already left.
- Music login errors and unavailable library items remain visible. Home then
  Browse retries a failed first page. More never plays music.
- Queue replacement is guarded by Sonos update IDs and exact staged-content
  verification. Partial failure is reported, with encrypted queue recovery
  retained locally; external queue changes are never blindly overwritten.
- Windows uses DWM thumbnails with text fallback. F24 conflicts disable physical
  control rather than silently switching through another app’s shortcut.
- A serial failure releases/disables control. Unsent actions are invalidated,
  and reconnect never replays old gestures. An action already sent to Sonos can
  finish and is reported honestly; Back cannot recall it.

## Development and checks

From this directory:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -q
.venv/Scripts/python.exe app.py --smoke-test
.venv/Scripts/python.exe render_previews.py
```

`previews/index.html` contains exports of the actual Tk instrument canvas with
sample data. These are a layout aid, not evidence of physical LCD rendering.

`control_center/controller.py` owns navigation and logical state; `runtime.py`
dispatches effects; `device.py` is the sole serial owner; `sonos.py`,
`apple_music.py`, `credentials.py`, and `windows.py` provide real integrations.
`simulation.py` provides deterministic replacements using the same controller.

Windows UI/DPAPI checks must run as your normal Windows user. The constrained
agent sandbox cannot load this machine’s Tcl resources or open the real desktop;
the hidden Tk smoke test was therefore run in the normal user session.
