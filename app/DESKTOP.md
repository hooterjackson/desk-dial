# Standalone Windows app

The app is **Desk Dial** (renamed from NanoD Control Center on 2026-09-26; desktop v7 on). Installed at
`C:\Users\someone\AppData\Local\Programs\DeskDial\DeskDial.exe`. The v2-v6 rollback bundles keep the old
name and install to `...\Programs\NanoDControlCenter\NanoDControlCenter.exe`.
This is a self-contained executable with bundled Python, Tk, and dependencies.
Neither Codex nor the source workspace is needed to run it.

- The app has no main window. It is a **tray icon** plus the **floating knob**: the
  knob face with its LED ring, floating over the desktop at the left edge of the
  primary screen, vertically centred. It slides in when you turn or press the
  physical knob (or press the Windows button) and slides out 2.5 s after the last
  touch. It never takes the focus and clicks pass through it.
- Tray icon: the knob seen from above (the designer's icon, `APP_ICON.md`), in the
  set that suits the taskbar (dark or light, followed live) and in two states: a
  solid ring with an orange dot while the knob is connected, a dashed ring when it
  is not found. The tooltip says **Desk Dial · Knob connected** or **Desk Dial · Knob
  not found**. The exe, the Start-menu shortcut and the Settings window carry the
  app icon.
- Tray menu: **Knob connected** / **Knob not found** and the detailed device
  status (both greyed), **Show knob** (also a left click on the icon; shows the
  knob for 2.5 s), **Settings…**, **Disconnect knob** / **Connect knob**, and
  **Quit**. Desktop errors (a failed volume change, skip or play) appear as tray
  notifications, one per error (at most one every 10 s). The knob keeps its "Last
  action failed" line until the next action, as before. The Apple Music
  authorization result shows in Settings and, if it failed or Settings is closed,
  as a tray notification.
- Find **Desk Dial** in Start to open Settings (the app keeps
  running in the tray). Settings opens centred on the primary screen, or to the
  right of the floating knob when they would overlap, always fully inside the
  work area (on a small screen it is shorter; Save and Authorize stay visible).
  Closing Settings keeps the tray app and the knob running.
- Use **Quit** in the tray menu to stop the app and release the knob.
- The Windows task **Desk Dial** starts it ten seconds after sign-in.
  It runs as Someone, without elevation, including on battery power.
- Reopening the app opens Settings in the existing instance instead of opening
  another USB connection. Windows Task Scheduler owns the running process
  independently. If the tray icon cannot be created, Settings opens with
  **Connect knob** / **Disconnect knob** and **Quit Desk Dial**, so the app is never
  invisible and unquittable; desktop errors then show in Settings (click to dismiss).
- Automatic connection waits for the uniquely identified knob (USB serial `NANO_D`).
  Reconnection resets to Volume, reads current Sonos state, and discards old
  requests and input. Manual Disconnect pauses automatic connection until Connect
  is selected or the app is restarted.
- In Task Scheduler, disable **Desk Dial** to disable future sign-in
  launches. Quitting the tray app exits normally; crash restarts are limited to
  three attempts, one minute apart.

Settings and encrypted Apple Music credentials live in
`%LOCALAPPDATA%\DeskDial\data`. Device backups and rotating logs are
beside that folder (`backups\`, `logs\`), and the Sonos queue-recovery and shuffle-restore
files are in `%LOCALAPPDATA%\DeskDial\` itself. Credentials were copied as encrypted files and remain bound
to the same Windows user. Updates preserve existing settings and credentials.
The installed app reads and writes its own data, separate from the source tree.

### The rename: from NanoD Control Center to Desk Dial

The first Desk Dial install (`Install-Desktop.ps1 -Bundle desktop-dist-v7 -Mirror`) moves in from
the old name. Run `Install-Desktop.ps1 -Bundle desktop-dist-v7 -Mirror -DryRun` first: it runs
every check, changes nothing and writes the plan to `diagnostics\desktop-install-plan.json`
(file names and sizes only).

- It refuses to start while `DeskDial.exe` or `NanoDControlCenter.exe` runs.
- It copies the whole old home `%LOCALAPPDATA%\NanoDControlCenter\` (`data\`, `logs\`, `backups\`,
  `queue-recovery.bin`, `shuffle-restore.bin`) to `%LOCALAPPDATA%\DeskDial\`, once. Each file is
  checked by SHA-256, a file that already exists in the new home is kept, and
  `%LOCALAPPDATA%\DeskDial\migration.json` records names, sizes and whether each hash matched
  (never contents). The old home stays untouched as the backup. Installing again never copies
  again, so a later install cannot bring back old queue-recovery files.
- It registers the **Desk Dial** task and the **Desk Dial** Start-menu shortcut. Then, only after
  the new program folder and the data step verified, it unregisters **NanoD Control Center**,
  moves `%LOCALAPPDATA%\Programs\NanoDControlCenter` to
  `%LOCALAPPDATA%\DeskDial\backups\program-NanoDControlCenter-<UTC>` (same volume as the program
  folder; moved, never deleted) and then removes its shortcut.
- Windows keeps tray-icon preferences per exe path, so a "show in the taskbar corner" choice
  resets once, and a stale **Nano_D++ Control Center** entry stays listed in Settings >
  Personalization > Taskbar. It is harmless and Windows owns it.
- Rolling back to v6 (`-Bundle desktop-dist-v6 -Mirror`) does the reverse: it unregisters
  **Desk Dial**, moves `Programs\DeskDial` to
  `%LOCALAPPDATA%\NanoDControlCenter\backups\`, removes its shortcut, installs the old
  name and re-registers **NanoD Control Center**. v6 reads the old home as it was when Desk Dial
  copied it; settings changed in Desk Dial since are not carried back (the installer has no option
  for it; copy them back by hand with the user if they are wanted). `%LOCALAPPDATA%\DeskDial\`
  stays for a later return. From a knob on cc5.4 the desktop rollback always follows the firmware
  rollback to cc5.3: cc5.4's offline and boot screens name Desk Dial, and the knob must never name
  an app that is not installed (`firmware/BUILD-cc5.4.md`, "Desktop rollback, v7 -> v6").

The app must run in the signed-in desktop session for Windows switching and
per-user credentials, so it deliberately is not a pre-login Windows service.

## Warm · alive (desktop v7, with firmware 1.0.0-cc5.4)

Desktop v7 is the desktop half of one combined release with firmware
1.0.0-cc5.4 (`firmware/ALIVE.md`, `PRESENTATION_V5.md`; the desktop
contract is `DESKTOP_STAGE.md`). It also runs against a knob still on cc5.3: it
then sends presentation-4 frames and the floating knob keeps v6's lights.

- **The floating knob is alive:** with a cc5.4 knob it renders the same alive
  LED engine as the knob (the breathing idle, press and claim feedback, limit
  flares, the six glow looks of the ring) on its own thread, at every display
  refresh while it is visible. While it is hidden it keeps the engine's state
  up to date without drawing, so it slides in showing what the knob shows. With
  **Motion** set to Reduced (or Windows' *Animation effects* off with Match
  Windows) it fades in place for 200 ms instead of sliding.
- **End stops summon it:** turning against an end stop (volume 0 % or 100 %,
  the first or last list item) now counts as a touch: cc5.4 reports it, so the
  v5 known limit is gone with that firmware.
- **Input fast path:** knob turns reach the floating knob and the music overlays
  straight from the USB reader thread, stamped when they were read, instead of
  waiting for the app's 25 ms UI tick.
- **Music overlays (Explorer and Up next):** they are drawn full-screen by the
  app's own compositor thread (`NanoD-stage`). They never take the focus; clicks on them are eaten so the hidden desktop
  is untouched. Back, the 600 ms hold and 60 s without knob input close them;
  locking the PC, sleep and the display turning off close them at once. The
  floating knob hides while one is open and stays out of their snapshots.
- **Settings:** a status strip at the top shows **Knob**, **Sonos** and **Apple
  Music**, each with its state and one action (Knob settings… or Troubleshoot…,
  Set manual IP…, Sign in… or Renew sign-in…), refreshed every second while
  Settings is open. The LED choices read **Colour** and **Warm only**. **Motion**
  (Match Windows, Full, Reduced) applies when saved, with artwork, LEDs and the
  switcher background.
- **Tray:** the Settings item reads **Open Settings…**. The icon follows the
  taskbar's light or dark theme as soon as Windows reports the change (and
  checks every 30 s in case a change is missed).
- **Timing:** while the app runs it asks Windows for 1 ms timer resolution and
  opts out of power throttling (EcoQoS), so its frame and input threads keep
  their pace on battery; both are undone when it quits.
- **Diagnostics:** `logs/status.json` adds `frames` (per surface: `knob`,
  `picker`, `toast`, `explorer`, `upnext`, with the last and worst frame
  episodes), `stage` (the compositor thread's state and its art workers),
  `openSurfaces`, `reducedMotion` and `process` (the timer and throttling
  settings and their self-check). The `overlay` section adds the alive
  renderer's counters.

## Windows switcher carousel (desktop v6)

`CAROUSEL.md` is the specification. This release replaces only the desktop
picker's presentation: no firmware, wire or contract change, so the knob stays on
1.0.0-cc5.3, and its Windows mode, LCD, ring, buttons and profile are unchanged.

- **What you see:** the knob's Windows button opens a horizontal carousel of live
  window previews on the monitor you were working on. The selected window sits
  in the centre at full size, and its neighbours shrink and dim with distance.
  Each detent slides the carousel by one window. Only the centre window is
  labelled, with its app, a readable title and a short description. Closed
  windows stay in place, faded, and read **Closed · can’t switch**.
- **Switch and Cancel:** green switches at once; the chosen window comes forward
  first, then the centre card grows and fades out, and a short toast names the
  app and title. Red (or Home) restores the previous window, and the toast reads
  **Cancelled · focus restored**. Switching focus to another app yourself closes
  the picker without a toast. With the picker in front, Enter or a click on the
  centre card also switches, and Esc cancels.
- **Settings → Switcher background:** **Frosted** (the default, a full-screen
  frost: the whole monitor behind the carousel turns into a blurred, tinted and
  slightly darkened snapshot, edge to edge, with no pane or border) or **No
  background** (the cards float over the live desktop dimmed to 55 %). It applies
  when saved. On a PC where the carousel has to fall back to its plain window,
  **No background** is shown disabled with a note, the picker uses Frosted
  in a reduced form (the frost fills only the carousel's area, and the rest of
  the screen is lightly dimmed), and a saved No background is kept for when it
  can be shown again.
- **Labels and icons:** app names come from each program's own name (the Start
  menu name for Store apps), and titles are cleaned up per app (Slack, Chrome,
  Bambu Studio, File Explorer, Claude/ChatGPT, then a generic rule). Duplicate
  labels get the Chrome profile or the monitor name. Icons use the sharpest
  source that matches the window's own icon, or a coloured letter tile. Profile
  and monitor names are shown on screen only and never logged.
- The floating knob stays hidden for as long as the carousel is open, with
  either background, including the short Switch or Cancel animation after the
  knob has left Windows mode. Touching the knob meanwhile does not bring it in;
  afterwards it comes back on the next touch, as usual. It is also left out of
  the frost: while the picker takes its snapshot of the screen, the knob's
  window is excluded from the capture, so the knob never appears blurred into
  the background.
- **Diagnostics:** `logs/app.log` records each picker focus change (open,
  switch, cancel) and how long Windows took to grant it (the carousel runs on its
  own thread, so its activation completes a moment after the request; the check
  waits up to 250 ms for the picker, and up to 100 ms for the window a Switch or
  Cancel brings forward). No title or window handle is logged.
- **Opening cost:** in the worst case, opening the picker holds the app's UI
  thread for up to about 400 ms: up to 150 ms for the carousel to come up, and up
  to 250 ms for the focus check. The labels follow only after focus is confirmed.
  Usually the open is far shorter. If focus is not confirmed in time, the picker
  hides and reports the usual "did not grant focus" error. The app does not
  re-focus the previous window on that path; it relies on Windows to activate
  another window when the hidden picker gives up the foreground. This rare path
  has not been checked on screen yet. Neither has the picker's activation
  itself: the visual spike checked the look, the stacking and the thumbnails,
  not the focus, so the supervised check confirms it (CAROUSEL.md section 10).
- **Memory:** after the picker hides, its large buffers are freed and its
  hidden layers give back the screen-sized surfaces Windows keeps for them.

## Floating knob (desktop v5)

`FLOATING_KNOB.md` is the specification. This release changes only the desktop
app: no firmware, wire or contract change, so the knob stays on 1.0.0-cc5.3.

- **Size and place:** the LED ring is about 360 px across at 100 % scaling (it
  follows the primary monitor's DPI). The knob face's box (the backplate plus its
  shadow margin) sits 24 px from the left edge of the work area, so at 100 % the
  backplate's edge is about 47 px and the LED ring about 61 px from the edge. It
  slides out from the screen edge itself. A dark round backplate keeps the LEDs
  readable on light wallpapers.
- **When it shows:** only physical knob touches (a detent, a button press, the
  Windows button's F24) and the tray's **Show knob**. It stays hidden while the
  knob is disconnected, while the Windows picker would cover it, and over
  full-screen games or presentations. Known limit: turning against an end stop
  (volume 0 % or 100 %, the first or last list item) sends no serial event, so
  that gesture alone does not summon the knob.
- **What it shows:** the same layout as the knob's LCD and LED ring, drawn
  directly at the screen's resolution from higher-fidelity sources (a 480 px
  cover, 128 px app icons, @2x/@3x icon masks). It is the same layout at a higher
  fidelity, not a pixel copy of the knob: the knob still receives its 240 px cover
  and 32 px icon payload.
- **Diagnostics:** `logs/status.json` has an `overlay` section (state, DPI, window
  and LCD size, frames presented, UpdateLayeredWindow failures, last error, LCD
  images that had to be fitted to the LCD size (`lcd_resizes`; non-zero only right
  after a DPI change), and the process's GDI/USER object counts).
- The simulator and the dev launcher (`app.py`) keep the full window.

## Browse and desk controls update

- The leftmost home button now offers Play or Pause from confirmed Sonos state.
  It stays white and disables while a command is pending or unsupported. On other
  screens it retains Back/Cancel. Escape never toggles playback at home.
- Windows uses a grid of live previews instead of one large preview. Typical
  window lists fit together; longer lists page automatically with knob selection.
  Green confirms and red cancels. This remains a companion-owned overlay.
  (Desktop v6 replaces the grid with the carousel described above.)
- Recently Added reads the current encrypted authorization for each network
  request, so authorization completed after startup does not require a restart.
  Starting a replacement authorization no longer discards the working grant.
  A failed initial load says “Library not loaded” and gives retry guidance.
- The installer initializes user data in an independent Windows task. This avoids
  packaged-launcher AppData redirection: the original authorization was inside
  Codex's private LocalCache and invisible to the sign-in app. Only missing files
  are copied, credentials stay Windows-encrypted, and existing standalone grants
  are preserved. `diagnostics/desktop-user-data.json` records migration results.
- `--check-music` performs a read-only check through the live UI provider setup
  and writes a sanitized result to `logs/music-check.json`. It does not open USB
  or change the Sonos queue. `status.json` includes the library page count,
  loading/error state, data path, and authorization presence, never token values.

The Claude Design ZIP is extracted under `design-reference/` as a reference.
Its full artwork/UI redesign has not been applied by this controls update.

Validation: 238 Python tests pass. cc4 is installed with a complete 4MB image
verification and saved-profile preservation checks. A diagnostic launched through
Task Scheduler, outside Codex's AppData view, loaded ten real Recently Added items;
the independent companion reports authorization present, USB connected, and ready.
See `diagnostics/native-desktop-verification.json`. On September 22 the user
confirmed Browse, home Play/Pause, and the Windows grid all work on the knob.

## Build and install

Run `Build-Desktop.ps1`, then `Install-Desktop.ps1` from this directory. The
installer copies and hash-verifies the executable bundle, creates the Start-menu
shortcut, and registers the sign-in task. Quit the existing tray app before
updating. It does not copy plaintext secrets or overwrite existing credentials.

Each Desk Dial build goes into a folder of its own; the current one builds into
`desktop-dist-v7-l` / `desktop-build-v7-l` (the build refuses the v2 to v6 rollback
folders and the earlier v7 ones, `desktop-dist-v7` to `desktop-dist-v7-l`) and the
installer defaults to `-Bundle desktop-dist-v7-l`, the bundle `Build-Desktop.ps1` builds. The exe embeds the app icon (`--icon`, all 8 frames).
Its frozen `--smoke-test` adds, for v7: the alive knob face (the six glow looks
built and one frame composed at 96 and 192 DPI), the process timing settings
(set, self-checked and undone) and the music overlays' compositor (its windows
created hidden, opened and closed, checking the GDI/USER object counts).
`--smoke-test --headless` runs every check without creating any Tk window: the
Tk font, image and UI checks are replaced by a run of the app on a stand-in
root, with the v5 knob and with the alive knob. Build-Desktop.ps1 runs the
headless form. As in v6, it also renders the knob face at 100 % and 200 %, draws the
LCD above 240 px from hi-res sources, checks the app and tray icon files and their
frames and loads each tray icon, and creates the knob's layered window hidden
(never shown), presents one frame to it, rebuilds its bitmap twice as a DPI change
does and destroys it, checking that the GDI/USER object counts return to their
baseline.
It also checks every button glyph's @2x/@3x mask and loads the app icon file.
For the Windows carousel it runs the full-screen frost pipeline on a synthetic
screen-sized image, renders
a label whose title needs fallback fonts (Cyrillic, Greek, CJK, Hangul, emoji) in
both backgrounds, checks a letter tile's size and contrast, and creates the
carousel's windows hidden (never shown), registers one live-preview thumbnail
between two of them, composes one frame into the chrome layer's bitmap and
presents it at zero opacity, then starts and closes the picker's own thread and
destroys everything, again checking the GDI/USER object counts.
The desktop step of the cc5.4 window (it can also run on its own, before the
firmware step):

1. Quit the app from the tray. Run
   `desktop-dist-v7-l\DeskDial\DeskDial.exe --smoke-test` (or
   `--smoke-test --headless`) and check that
   `%LOCALAPPDATA%\DeskDial\logs\smoke-test.json` says
   `passed: true`. The installer refuses a new bundle without a passing report
   from that bundle's exe, newer than the exe.
2. Back up the program folder and hash the user data.
3. Run `Install-Desktop.ps1 -Bundle desktop-dist-v7-l -Mirror -DryRun` and read
   `diagnostics\desktop-install-plan.json`, then `Install-Desktop.ps1 -Bundle desktop-dist-v7-l -Mirror`.
4. Confirm the old home's hashes are unchanged and the migrated files in `%LOCALAPPDATA%\DeskDial\`
   have the same hashes, then start the **Desk Dial** task and verify
   (`firmware/BUILD-cc5.4.md` step 9).

The v7 bundle is built as Desk Dial (`desktop-dist-v7\DeskDial\DeskDial.exe`, with the version
resource FileDescription and ProductName `Desk Dial`); its exe SHA-256 and file listing are
recorded in `diagnostics/desktop-v7-build.json` and `diagnostics/desktop-dist-v7-sha256.json`.
The earlier v7 builds recorded there under the old name were never installed; the build moves
their `NanoDControlCenter` folder out of `desktop-dist-v7` (to `desktop-build-v7`).

Uninstall: quit Desk Dial from the tray, review `Uninstall-Desktop.ps1 -DryRun` (it prints its plan
and changes nothing), then run `Uninstall-Desktop.ps1`. It removes the program folder
`%LOCALAPPDATA%\Programs\DeskDial`, the **Desk Dial** sign-in task and the **Desk Dial** Start-menu
shortcut, and keeps the data folder `%LOCALAPPDATA%\DeskDial` (settings, credentials, logs) unless
it is given `-RemoveData`. It refuses while `DeskDial.exe` runs.

Desktop rollback: `Install-Desktop.ps1 -Bundle desktop-dist-v6 -Mirror` (the
floating knob with the Windows-switcher carousel, exe SHA-256
`2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F`; from a knob
on cc5.4 only after the firmware rollback `rollback_nanod_cc5.py --to cc5.3`, because
cc5.4's knob copy names Desk Dial). The v2, v3, v4, v5 and v6
rollback bundles have their exe SHA-256 recorded in the installer, which refuses
a bundle that differs. v6 ignores the new `motion` key in `settings.json`; an
older `settings.json` simply gets Motion = Match Windows. Earlier rollback:
`Install-Desktop.ps1 -Bundle desktop-dist-v5 -Mirror` (the floating knob with
the grid picker, exe SHA-256
`0BF15DB86F5376F763193474457DEDFCB04D8ECEBC401E396E966EB668C2D210`); v5 ignores
the `picker_background` key.

The executable is bundled with [PyInstaller](https://pyinstaller.org/en/stable/).
The tray uses [pystray's Windows integration](https://github.com/moses-palmer/pystray/blob/master/docs/usage.rst).
Exact build dependencies are in `requirements-desktop.txt`.

## Verified on 22 September 2026

212 Python tests pass, including reconnect request identity and retry behavior.
The frozen executable passes its UI smoke test. Task Scheduler launched the
installed executable under `svchost`; the app connected to the physical knob and
Hall in live mode. A second launch exited successfully, leaving one running app.
The standalone app reads firmware **1.0.0-cc3**. The application image and full
flash were verified, all ten saved profiles were preserved, and all four device
control entries plus host-lease recovery passed.

An actual reboot/sign-in, physical cable reconnection with the packaged app,
and final hands-on visual/full-feature acceptance have not yet been observed.
