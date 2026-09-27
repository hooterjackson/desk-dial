# Rename inventory: Nano_D++ / NanoD Control Center → Desk Dial

Read-only inventory, snapshot 2026-09-26 08:15 UTC (01:15 local). The rename workflow was
editing these trees at the same time, so line numbers can move. At the snapshot none of the
files listed had been renamed yet (Build-Desktop.ps1 00:33, Install-Desktop.ps1 00:34,
ui.py 00:46, cc_display.cpp 2026-09-25 22:05 local).

Trees: `D` = `app`, `F` = `firmware`, `W` = `work` (the
tooling next to the firmware, outside both trees but it depends on the names).

## 0. Summary

| Category | Change | Keep / optional |
|---|---|---|
| A. Desktop user-visible strings (titles, tray, toasts, Settings, Apple consent) | 17 (1 is optional wording) | 6 dev-only strings, optional |
| B. Install-level (exe/spec, installer scripts, task, shortcut, program and data folders, logs) | 31 lines in 7 files (Build-Desktop.ps1 6, Install-Desktop.ps1 15, Install-UserData.ps1 6, one path line each in standalone.py, ui.py, credentials.py, queue_context.py) | `TRAY_NAME` optional; mutex/event names kept (see H9) |
| C. Knob firmware user-visible strings | 1 required (offline sub) + 1 recommended (boot screen) | 1 optional (serial banner), USB descriptors kept |
| D. Contracts and copy sheets | 13 lines + 1 note | historical rulings kept |
| E. Docs (README, DESKTOP.md, ACCEPTANCE.md) | 13 lines (README 2, DESKTOP.md 11, ACCEPTANCE.md 0) | historical runbooks and handoffs kept |
| F. Tests asserting the old names | 36 lines in 8 files | about 20 assertions kept (historical runbooks, pinned bundles, USB serial, sample data) |
| G. Tooling next to the firmware (`W`) that breaks silently | 21 lines in 12 files | — |
| H. Internal identifiers that should NOT change | — | 21 |

The risky items are in section 11.

## 1. Identity: old → new

| Thing | Old | Proposed |
|---|---|---|
| Display name | `Nano_D++`, `Nano_D++ Control Center`, `Nano_D++ · Control Center` | **Desk Dial** |
| Caps heading | `NANO_D++` | `DESK DIAL` |
| Frozen exe / PyInstaller `--name` / generated spec | `NanoDControlCenter.exe` / `NanoDControlCenter` / `desktop-build-vN\NanoDControlCenter.spec` | `DeskDial.exe` / `DeskDial` / `DeskDial.spec` (no space: `Get-Process -Name`, `tasklist /FI "IMAGENAME eq …"` and quoting stay simple) |
| Bundle folder | `desktop-dist-vN\NanoDControlCenter\` | `desktop-dist-v8\DeskDial\` (new build folders, see 11.10) |
| Program folder | `%LOCALAPPDATA%\Programs\NanoDControlCenter` | `%LOCALAPPDATA%\Programs\DeskDial` |
| Per-user home | `%LOCALAPPDATA%\NanoDControlCenter\` (`data\`, `logs\`, `backups\`, root `.bin` files) | `%LOCALAPPDATA%\DeskDial\` (same layout) |
| Scheduled task (sign-in) | `\NanoD Control Center` | `\Desk Dial` |
| Transient install task | `NanoD Data Setup <guid>` | `Desk Dial Data Setup <guid>` |
| Start-menu shortcut | `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Nano_D++ Control Center.lnk` | `…\Programs\Desk Dial.lnk` |
| Startup-folder shortcut | none (sign-in start is the scheduled task) | none |
| Registry keys owned by the app | none (no Run value, no Uninstall key, no App Paths) | none |
| Registry the app causes Windows to write | `HKCU\Control Panel\NotifyIconSettings\10361537688783620186` (ExecutablePath = the old exe, InitialTooltip `Nano_D++ Control Center`) | a new entry is created for the new exe path (see 11.11) |
| Exe version resource | none (FileDescription, ProductName, OriginalFilename all empty in the v7 build) | proposed: add one (section 3.1) |

## 2. A. Desktop user-visible strings (change)

| # | Where | Now | Proposed | Seen as |
|---|---|---|---|---|
| A1 | `D\standalone.py:63` `TRAY_TIP_PREFIX` | `Nano_D++ · ` | `Desk Dial · ` | tray tooltip: `Desk Dial · Knob connected` / `Desk Dial · Knob not found` (26 UTF-16 units, limit 127) |
| A2 | `D\standalone.py:66` `BALLOON_TITLE` | `Nano_D++` | `Desk Dial` | tray notification (toast) title |
| A3 | `D\control_center\ui.py:136` `SETTINGS_TITLE` | `Nano_D++ Settings` | `Desk Dial Settings` | Settings window title, taskbar button |
| A4 | `D\control_center\ui.py:148` `SETUP_SAVED_NOTES[True]` | `…after you quit Nano_D++ Control Center from the tray…` | `…after you quit Desk Dial from the tray…` | Settings Save note |
| A5 | `D\control_center\ui.py:786` strip, knob ok | `Nano_D++ · USB · firmware {v}` / `Nano_D++ · USB` | `USB · firmware {v}` / `USB` (the column is already titled Knob). Alternative: `Desk Dial knob · USB · firmware {v}` | Settings status strip |
| A6 | `D\control_center\ui.py:790` strip, knob problem | `Waiting for Nano_D++ on USB. The knob’s own controls still work.` | `Waiting for the knob on USB. The knob’s own controls still work.` | Settings status strip |
| A7 | `D\control_center\ui.py:1015` root title | `Nano_D++ · Control Center` | `Desk Dial` | dev/simulator main window (the root stays withdrawn in the installed app) |
| A8 | `D\control_center\ui.py:1226` header | `NANO_D++` | `DESK DIAL` | dev/simulator window header |
| A9 | `D\control_center\ui.py:2076` | `Nano_D++ · Simulator states` | `Desk Dial · Simulator states` | simulator picker title |
| A10 | `D\control_center\ui.py:2455` | `Quit Nano_D++` | `Quit Desk Dial` | Settings button when the tray icon fails |
| A11 | `D\control_center\ui.py:2311` (optional wording) | `Connect a knob with the control-center firmware first` | `Connect the knob with Desk Dial firmware first` | Settings button-order calibration |
| A12 | `D\control_center\overlay.py:107` `WINDOW_TITLE` | `Nano_D knob` | `Desk Dial knob` | floating knob window name (screen readers, Accessibility Insights, window lists) |
| A13 | `D\control_center\carousel.py:3318` `HOST_TITLE` | `Nano_D++ · Windows` | `Desk Dial · Windows` | carousel host window name |
| A14 | `D\control_center\credentials.py:29` `CONSENT_TEXT` | `Allow Nano_D++ to read your Apple Music library…` | `Allow Desk Dial to read your Apple Music library…` | Apple Music connect page |
| A15 | `D\control_center\credentials.py:251` | `<title>Connect Apple Music · Nano_D++</title>` | `Connect Apple Music · Desk Dial` | browser tab |
| A16 | `D\control_center\credentials.py:255` MusicKit `app.name` | `Nano_D++ Control Center` | `Desk Dial` | Apple's authorization sheet. Existing Music User Tokens stay valid (the name is display only) |
| A17 | `D\control_center\lcd_preview.py:482` `OFFLINE['subtitle']` | `Open Nano_D++ on your PC` | `Open Desk Dial on your PC` (NBSP, see 5.2) | desktop mirror of the knob's offline screen |

Dev-only, optional: `D\app.py:41` (`Control center UI smoke passed`), the dependency errors
`D\control_center\apple_music.py:239`, `D\control_center\credentials.py:137`,
`D\control_center\sonos.py:466` (`Install the control-center dependencies…`; the frozen bundle
always has them), `D\standalone.py:1172` (smoke frame subtitle `Nano_D++`, never shown),
`D\render_previews.py:121` (preview HTML title). The docstrings at `D\app.py:1`,
`D\control_center\__init__.py:1`, `device.py:1`, `lcd_preview.py:1` are cosmetic.

Keep (sample data): `D\control_center\simulation.py:112` (`Nano D Control Center` is a fake
Claude window title in the simulator; `tests\test_window_labels.py:82-83` uses the same string
on its own).

Tray menu items (`standalone.py:462-473`: `Show knob`, `Open Settings…`, `Connect/Disconnect
knob`, `Quit`) and every other Settings string carry no brand. Nothing changes there.

## 3. B. Install-level (change)

### 3.1 Build-Desktop.ps1

| Line | Now | Proposed |
|---|---|---|
| 10-11 | `$Dist='desktop-dist-v7'`, `$Work='desktop-build-v7'` | new folders (`desktop-dist-v8` / `desktop-build-v8`), or a cleaned v7 (11.10). If v7 ships under the old name, add v7 to `$rollbackFolders` (:22) |
| 15 | comment `%LOCALAPPDATA%\NanoDControlCenter\logs\smoke-test.json` | `%LOCALAPPDATA%\DeskDial\logs\smoke-test.json` |
| 45 | `--name NanoDControlCenter` | `--name DeskDial` (exe, spec and bundle folder follow) |
| 48 | `"$Dist\NanoDControlCenter\NanoDControlCenter.exe"` | `"$Dist\DeskDial\DeskDial.exe"` |
| 53 | `Get-Process -Name NanoDControlCenter` | `Get-Process -Name DeskDial, NanoDControlCenter` |
| 37 | `assets\app-icon\ico\nano-d-app.ico` | keep (H14) |
| new | — | `--version-file` with FileDescription `Desk Dial`, ProductName `Desk Dial`, InternalName `DeskDial`, OriginalFilename `DeskDial.exe`, FileVersion `8.0.0.0`. Task Manager, the toast source and Settings › Taskbar › other system tray icons then show "Desk Dial" instead of the exe name. Add a `tests\test_packaging.py` assertion for it |

### 3.2 Install-Desktop.ps1

| Line | Now | Proposed |
|---|---|---|
| 22, 24 | comments with old bundle and smoke paths | new paths |
| 62 | `"$Bundle\NanoDControlCenter"` | a per-bundle identity table: pinned v2–v6 (and v7 if it ships old-name) → `NanoDControlCenter`, new → `DeskDial` |
| 63 | `Programs\NanoDControlCenter` | `Programs\DeskDial` (identity table) |
| 64 | `NanoDControlCenter\data` | `DeskDial\data` (identity table) |
| 65, 66, 69, 73 | `NanoDControlCenter.exe` | `DeskDial.exe` (identity table) |
| 74 | `NanoDControlCenter\logs\smoke-test.json` | `DeskDial\logs\smoke-test.json`. It must change together with `standalone.py:2185`; if not, the install fails closed |
| 79 | `Get-Process -Name 'NanoDControlCenter'` + `'Quit the existing control center before updating.'` | both names; `'Quit Desk Dial (or the old Nano_D++ Control Center) from the tray before updating.'` |
| 82 | comment `NanoDControlCenter\data` | `DeskDial\data` |
| 118 | `'NanoD Data Setup '` | `'Desk Dial Data Setup '` |
| 136 | task `'NanoD Control Center'`, description `'Standalone Nano_D++ Sonos and Windows control center. Runs in the signed-in user session.'` | task `'Desk Dial'`, description `'Desk Dial: the knob's Sonos, Apple Music and Windows companion. Runs in the signed-in user session.'` |
| 137 | `'Nano_D++ Control Center.lnk'` | `'Desk Dial.lnk'` |
| 138, 139 | task name in the export and in `diagnostics\desktop-installation.json` | `'Desk Dial'` (the report file names stay the same, H6) |
| new | — | after the new install verifies: `Unregister-ScheduledTask 'NanoD Control Center'` if present. Back up `Programs\NanoDControlCenter` to `backups\` and then remove it. Uninstalling a rollback bundle does the reverse (section 10) |

### 3.3 Install-UserData.ps1 (runs through the scheduled task, outside AppData virtualization)

| Line | Now | Proposed |
|---|---|---|
| 6 | `NanoDControlCenter\data` | `DeskDial\data`. Do the legacy migration first (section 4), then the existing copy of missing files from staging |
| 23 | `Programs\NanoDControlCenter` | `Programs\DeskDial` |
| 24 | `'Nano_D++ Control Center.lnk'` | `'Desk Dial.lnk'`. Also delete the old `.lnk` here: it lives under `%APPDATA%`, so it must be removed in this unvirtualized context (11.4) |
| 27, 29 | `NanoDControlCenter.exe` target and icon | `DeskDial.exe` |
| 32 | `'Open Nano_D++ Control Center settings; …'` | `'Open Desk Dial settings; the app keeps running in the tray, and the floating knob slides in when you touch the knob.'` |

### 3.4 Per-user paths in the app (5 separate constructions: consolidate into one `control_center/paths.py`)

| Line | Now | Proposed |
|---|---|---|
| `D\standalone.py:2185` | `home = LOCALAPPDATA\NanoDControlCenter` (`logs\` app.log, crash.log, status.json, smoke-test.json, music-check.json) | `LOCALAPPDATA\DeskDial` |
| `D\control_center\ui.py:83` (`:85` BACKUP_DIR is derived) | `DATA_DIR = LOCALAPPDATA\NanoDControlCenter\data` | `…\DeskDial\data` |
| `D\control_center\credentials.py:75` | default `LOCALAPPDATA\NanoDControlCenter\credentials.bin`. `sonos.py:786` and `:1408` derive the root-level `queue-recovery.bin` and `shuffle-restore.bin` from it | `…\DeskDial\credentials.bin` (the same root-level files) |
| `D\control_center\queue_context.py:40` (docstrings `:12`, `:117`) | `…\NanoDControlCenter\data\queue-ledger.json` | `…\DeskDial\data\queue-ledger.json` |
| `D\standalone.py:62` `TRAY_NAME` (optional) | `NanoDControlCenter` (pystray's internal icon and window-class name, never shown) | `DeskDial`, or keep. `tests\test_cc_tray.py:111` asserts it |

Log and status files after the rename: `%LOCALAPPDATA%\DeskDial\logs\{app.log(.1-.3),
crash.log(.1), status.json, smoke-test.json, music-check.json}`. Device backups:
`%LOCALAPPDATA%\DeskDial\backups\control-center-inventory-*.json`. The file names do not
change. The planned C3 art cache (`DESKTOP_STAGE.md:1117`) becomes `%LOCALAPPDATA%\DeskDial\cache\art\`.

## 4. Per-user data migration (proposal)

What exists today under `%LOCALAPPDATA%\NanoDControlCenter\` (names only, contents not read):
`data\settings.json`, `data\credentials.bin`, the root `queue-recovery.bin` (present),
`backups\control-center-inventory-*.json` (20 files) and `logs\` (5 files).
`data\queue-ledger.json` and the root `shuffle-restore.bin` appear only when used.

1. **Where.** The primary step goes in `Install-UserData.ps1`, which already runs as the user
   through a one-shot scheduled task so that a packaged (MSIX) parent's AppData redirection
   cannot capture the writes. The app also runs a first-run fallback in `standalone.main()`
   after the single-instance mutex is acquired (so only one process migrates). It is never
   run on `--smoke-test`. `--check-music` reads the new path and reports "not migrated" when
   the files are absent.
2. **What.** Copy, never move, and only files missing at the destination:
   `data\{settings.json, credentials.bin, queue-ledger.json}` → `DeskDial\data\`, and the root
   `{queue-recovery.bin, shuffle-restore.bin}` → `DeskDial\` (the root, next to where
   `CredentialStore().path.with_name()` looks). `backups\*` → `DeskDial\backups\` is optional
   and small. `logs\` is not copied: new logs start fresh and the old ones stay where they are.
3. **Verify.** Write to a temp name, compare SHA-256 with the source, rename. On any mismatch,
   delete the partial new files and fail the install (the old home is untouched). Write
   `DeskDial\migration.json` with: source home, per file `{name, bytes, copied, hashMatch}`, and
   the time. Never file contents or hashes of secrets in logs. The installer's
   `diagnostics\desktop-user-data.json` report gets the same fields.
4. **DPAPI.** `credentials.bin`, `queue-recovery.bin` and `shuffle-restore.bin` are
   `CryptProtectData` user-scope blobs: no LOCAL_MACHINE flag, no entropy (`credentials.py:58-60`).
   The same Windows user on the same machine can decrypt them at any path, so a copy is enough.
   Keep the file header `NANOD-CREDENTIALS-1` (H10). The DPAPI description string
   `Nano_D++ MusicKit` (`credentials.py:59`) is not used to decrypt; changing it to
   `Desk Dial MusicKit` only affects new writes and is optional.
5. **Old home.** Keep `%LOCALAPPDATA%\NanoDControlCenter\` untouched as the backup and as the
   rollback bundles' live data (section 10). Delete it only when the user asks.

## 5. C. Knob firmware user-visible strings

### 5.1 Strings

| # | Where | Now | Proposed |
|---|---|---|---|
| C1 (required) | `F\src\cc_display.cpp:121` `OFFLINE_SUB` | `"Open Nano_D++ on your PC"` | `"Open Desk\xC2\xA0" "Dial on your PC"` (U+00A0, 5.2). Split the literal: `"\xA0Dial"` would read `\xA0D` as one hex escape |
| C1 comments | `F\src\cc_display.cpp:126`, `F\src\cc_display.h:96` | `"Open Nano_D++ on your PC"` | new copy |
| C2 (recommended) | `F\src\screens\ui_bootimg.c:16` (stock boot screen, every power-up) | `"NANO_D++\nIS BOOTING..."` | `"DESK DIAL\nIS BOOTING..."`. Font `ui_font_SGK100h16` covers ASCII 32–126, and the label is centred with content width, so it fits |
| C3 (optional) | `F\src\main.cpp:90` | `Serial.println("Welcome to Nano_D++!")` | `"Welcome to Desk Dial!"` (serial console only; no host code matches it) |

The offline screen has no heading since PRESENTATION_V5 (`cc_display.cpp:1697` hides it; P4-8
retired `NANO_D++`). The design model still labels that state `NANO_D++`
(`design_handoff_nano_d_master_r2.2\prototypes\knob-model.js:369`). If UI V2 brings a heading
back, `DESK DIAL` fits (5.2).

### 5.2 Width check (the contracts' Montserrat method)

Method: PRESENTATION_V5.md Notation (`D\assets\fonts\Montserrat.ttf` at wght 500, advance
widths, no kerning, ±2 px), plus the authoritative LVGL port (`W\lcd-preview\font_tests.py`
`resolved_run_width`: `cc_font_N` → kerned `lv_font_montserrat_N` fallback for ASCII;
`lv_text_get_width` adds letter space n−1 times) and the firmware's ink-row chord (`safeHalf`).
The script is in the session scratchpad: `rename\measure_desk_dial.py`.

Calibration: it reproduces every contract value exactly.

| String | Size | Design (ours / contract) | LVGL (ours / contract) |
|---|---|---|---|
| `Open Nano_D++ on your PC` | 14 | 197.9 / 197.9 | 202 |
| `Waiting for PC` | 22 | 163.6 / 163.6 | 163 |
| `Knob controls still work` | 14 | 167.5 / 167.5 | 171 / 171 (erratum R-c) |
| `Speaker group changed` | 12 | 147.6 / 147.6 | 144 |

Results:

| String | Element | Design | LVGL | Limit | Outcome |
|---|---|---|---|---|---|
| `DESK DIAL` (caps, +1 px tracking) | heading 12 | 74.8 | 75 | 138 (the r112 chord of rows 34..42 is wider, so the 138 box governs) | fits, with 63 px to spare (`NANO_D++` was 75.2 / 76) |
| `Open Desk Dial on your PC` | offline sub 14 | 192.2 | 198 | 170 | two balanced lines, as today (P5-3) |
| line 1 `Open Desk Dial` | sub 14 | 110.4 | 114 | 170 (the r104 chord at y 105 is wider) | fits |
| line 2 `on your PC` | sub 14 | 78.0 | 80 | 170 (y 123) | fits |
| `Desk Dial` | title 22 / 16 | 105.7 / 76.9 | 105 / 76 | 170 | fits, if it is ever used as a title |

**Wrap hazard (risky, 11.5).** `fitTwoLines` (`cc_display.cpp:465+`) and its mirror
`lcd_preview.fit_two_lines` break only at ASCII space and keep the split with the smaller wider
line. The candidates with a plain space are:

| Split | LVGL widths | Wider line |
|---|---|---|
| `Open Desk` / `Dial on your PC` | 82 / 112 | 112 (chosen) |
| `Open Desk Dial` / `on your PC` | 114 / 80 | 114 |

So the knob and the desktop mirror would both render `Open Desk` / `Dial on your PC` (checked
with `lcd_preview.fit_two_lines`). With U+00A0 between Desk and Dial (in `cc_font_14`, 4 px,
the same as a space) both render `Open Desk Dial` / `on your PC`. The design's CSS greedy wrap
would give `Open Desk Dial on your` / `PC` (168.3 ≤ 170). The contract's balanced rule still
wins, so note this for the designers.

`Waiting for PC` and `Knob controls still work` do not change.

## 6. D. Contracts and copy sheets (change)

| Where | Now | Proposed |
|---|---|---|
| `F\V5_VOCABULARY.md:714` `knob.sub.offline` | `Open Nano_D++ on your PC` | `Open Desk Dial on your PC` (NBSP between Desk and Dial; add a rename ruling that points to this file) |
| `F\V5_VOCABULARY.md:731` `settings.knob.ok` | `Nano_D++ · USB · firmware {v}` | A5 |
| `F\V5_VOCABULARY.md:732` `settings.knob.problem` | `Waiting for Nano_D++ on USB. …` | A6 |
| `F\V5_VOCABULARY.md:907` VOC-R11 | historical ruling | keep, append "renamed to Desk Dial" |
| `F\PRESENTATION_V5.md:597` width table | `Open Nano_D++ on your PC` 197.9 px | `Open Desk Dial on your PC` 192.2 px (LVGL 198), two balanced lines, NBSP |
| `F\PRESENTATION_V5.md:684` 8.10 layout | `Open Nano_D++` / `on your PC` | `Open Desk Dial` / `on your PC` |
| `F\PRESENTATION_V5.md:685` erratum R-c | `Open Nano_D++ on your PC keeps 0` | new copy |
| `F\PRESENTATION_V5.md:1045` P5-3 | `Open Nano_D++ on your PC` 197.9 px | new copy, 192.2 px |
| `F\CONTROL_CENTER.md:3` | `(the Nano_D++ desktop companion)` | `(the Desk Dial desktop companion)` |
| `D\CONTROL_CENTER_V5.md:1489` `settings.apple.consent` | `Allow Nano_D++ to read…` | A14 |
| `D\CONTROL_CENTER_V5.md:1045` (code excerpt) | `NanoDControlCenter\data\queue-ledger.json` | new path |
| `D\DESKTOP_STAGE.md:1117` | `%LOCALAPPDATA%\NanoDControlCenter\cache\art\` | `%LOCALAPPDATA%\DeskDial\cache\art\` |
| `D\APP_ICON.md:40-41` | tooltip `Nano_D++ · Knob connected / not found` | `Desk Dial · …` |

Keep (historical or designer-owned): `F\PRESENTATION_V4.md:329` and `F\CONTROL_CENTER.md:571`
(the retired `NANO_D++ / Waiting for PC / Native controls active` notice); `F\README.md:1`,
`F\hid.md`, `F\midi.md` (upstream docs for the kit hardware); `D\assets\app-icon\README.md:1, 4, 71`
(the designer's handoff record; add an implementation note instead); every
`D\design-reference\design_handoff_*` file (for example r2.2 `specs\01-…:141, :488`,
`specs\05-APP-ICON.md:74`, `icons\README.md:71`, `prototypes\knob-model.js:369`). The UI V2
master handoff prompt should state the new name before it goes to the designer; the files under
`ui-v2-analysis\` are analysis records.

## 7. E. Docs (change)

- `D\README.md:1` `# Nano_D++ control center` → `# Desk Dial`
- `D\README.md:8` `Open **Nano_D++ Control Center** from Start` → `Open **Desk Dial** from Start`
- `D\README.md:94`: keep `NanoD Control Center`. It is the MusicKit key/identifier name in the
  Apple developer portal, which is external. The developer token is signed by key ID, not by name.
- `D\DESKTOP.md:3` install path → `…\Programs\DeskDial\DeskDial.exe`
- `D\DESKTOP.md:15-16` tooltips → `Desk Dial · …`
- `D\DESKTOP.md:26` `Find **Nano_D++ Control Center** in Start` → `Find **Desk Dial** in Start`
- `D\DESKTOP.md:32`, `:43` task **NanoD Control Center** → **Desk Dial**
- `D\DESKTOP.md:37` **Quit Nano_D++** → **Quit Desk Dial**
- `D\DESKTOP.md:39` `the uniquely identified Nano_D++ USB device` → `the uniquely identified knob (USB serial NANO_D)`
- `D\DESKTOP.md:48` data path → `%LOCALAPPDATA%\DeskDial\data`, plus a migration note (section 4)
- `D\DESKTOP.md:255`, `:257` smoke exe and report paths → new
- Add to DESKTOP.md: the tray icon's "show in taskbar corner" choice resets once (11.11), and
  the old task, shortcut and program folder are removed by the installer.
- `D\ACCEPTANCE.md`: no occurrences (only `nanod-*` paths and `control-center-inventory` file names, H4 and H6).

Keep: `D\LEGACY-DEMO.md` (the stock-kit demo); `D\FLOATING_KNOB.md:232, :278` (v5 rollout
record); `D\firmware\BUILD-cc5.md`, `BUILD-cc5.3.md`, `RECOVERY.md` (runbooks for old-name
bundles, asserted by tests). Exception: any block in RECOVERY.md that is run against the
current install, such as the quit block at `:241-243`, needs both names (11.12).

## 8. F. Tests

Change (36 lines, 8 files):

- `D\tests\test_cc_tray.py`: 43, 44, 111 (also `TRAY_NAME`, if renamed), 190, 224, 231, 245,
  548, 559, 598, 602, 603, 604, 605, 606, 608, 610, 657, 659
- `D\tests\test_cc_ui.py`: 627, 1091, 1123, 1124, 1140
- `D\tests\test_cc_runtime_overlay.py`: 603, 617, 652
- `D\tests\test_cc5_settings_strip.py`: 43, 45, 50
- `D\tests\test_packaging.py`: 104, 176, 178. Add assertions for the old task, shortcut and
  program folder cleanup, and for the version resource.
- `D\tests\test_cc_overlay.py`: 1583 (window title only; the class `NanoD.KnobOverlay` stays)
- `D\tests\test_cc_lcd_preview.py`: 821 (`('subtitle','Open Desk Dial'), ('subtitle','on your PC')`)
- `D\tests\test_cc_credentials.py`: 19

Add: a migration test (copy only missing files, root `.bin` files included, hash verified,
never on `--smoke-test`, old home untouched) and a mirror test that the offline sub never
splits the name.

Keep:

- `D\tests\test_cc5_tooling.py:3728`, `:3730`: change only if the RECOVERY quit block becomes dual-name.
- `D\tests\test_cc5_tooling.py:3878-4256`: historical runbooks and pinned rollback bundle paths
  `…\NanoDControlCenter\NanoDControlCenter.exe`.
- USB serial `NANO_D`: `D\tests\test_cc5_tooling.py:131`, `:157-160`; `D\tests\test_standalone.py:40`.
- Sample data: `D\tests\test_window_labels.py:82-83`; `D\tests\tools\capture_session_frames.py:425`, `:1657`;
  `render_carousel_previews.py:41, 47, 532`.
- `D\tests\js\knob_golden.cjs:21, 114, 116, 130` loads `Nano_D Control Center.dc.html` by name.
- Design-derived fixtures: `alive_golden.json`, `knob_golden.json`, `cc5_frames.json` (`NANO_D++`
  labels and the `Nano_D++ control center` sample window).
- Dev preview page titles: `D\tests\tools\make_cc5_frames.py:77`, `render_floating_previews.py:248` (optional).

## 9. G. Tooling next to the firmware (`W`, change: it breaks silently otherwise)

| Where | Now | Why it matters |
|---|---|---|
| `W\nanod_cc5_tooling.py:82` `COMPANION_IMAGE` (used `:648-661`) | `NanoDControlCenter.exe` | **flash-safety interlock**: it would report "not running" while `DeskDial.exe` owns the knob. Check both images |
| `W\nanod_cc5_tooling.py:661` | `disable the 'NanoD Control Center' task` | name both tasks |
| `W\check_desktop_v7.py:7, 37, 38` | old logs and exe paths | the verifier would read stale `status.json` or report a missing exe; needs a new-identity checker |
| `W\finalize_nanod_cc5.py:277` | `name\NanoDControlCenter\NanoDControlCenter.exe` | per-bundle identity |
| `W\probes\apple_favourite_playlists_probe.py:265`, `live_like_test.py:658, 783`, `live_play_next_test.py:72`, `live_readonly_probe.py:87`, `live_seek_test.py:484, 513`, `unfavorite_webplayer_once.py:23` | `NanoDControlCenter\data\…`, `IMAGENAME eq NanoDControlCenter.exe` | after migration they read the **stale but still decryptable** old copy and act on old tokens or settings |
| `W\lcd-preview\cc54_report.py:1197, 1200, 1243, 1252` | expects `Open Nano_D++ on your PC` | the LCD render gate fails after C1 (fails closed) |
| `W\lcd-preview\main.cpp:1316` | render label | cosmetic |
| `D\diagnostics\Verify-NativeDesktop.ps1:2-3` | old logs and exe paths | verifier |

Keep: `nanod_cc5_tooling.py:78`, `:573`, `:606`, `:803` (serial `NANO_D`, H1);
`nanod_enter_bootloader*.py`, `probe_nanod.py` (messages about the stock hardware);
`gen_lvgl_font.py` comments; `spike_dcomp\*`.

## 10. H. Internal identifiers that should NOT change

| # | Identifier | Where | Reason |
|---|---|---|---|
| H1 | USB serial descriptor `Nano_D` and host match `(0x239A, 0x8010)` + serial `NANO_D` (any case) | `F\src\main.cpp:42`; `D\standalone.py:324-325`; `W\nanod_cc5_tooling.py:78` | port discovery for the app and all flash/rollback tooling. cc5.3 and older firmware report it, so changing it breaks rollback compatibility |
| H2 | USB product `Nano_D++ (Beta)`, MIDI `Nano_D MIDI`, HID `Nano_D HID` | `F\src\main.cpp:40`, `F\platformio.ini:51`, `F\src\hmi_thread.cpp:194, :202` | the hardware's USB identity. Changing it renames Windows devices and MIDI ports, which breaks DAW mappings and the stock configurator. Decide this separately; it is not part of an app rename |
| H3 | Python package `control_center` and its modules; classes `ControlCenterApp`, `ControlCenterRuntime` | whole tree; `Build-Desktop.ps1:45` hidden-imports | imports, PyInstaller hidden-import list, tests. No user sees them |
| H4 | Folder names `app`, `firmware`, `nanod-*-venv`; firmware files `nanod-control-center-1.0.0-cc*.bin` / `-source.zip`, manifests, `control_center.cpp/.h`, `cc_*.cpp` | `D\firmware\`, `F\src\` | manifests pin SHA-256 and paths; rollback tooling, contracts and memory use these paths |
| H5 | Capability and wire names `controlCenter`, `leaseMs`, `hostFrame`, `artwork2`, `presentation`; wire error `Release control center before changing device configuration` | `F\src\control_center.cpp:177`, `:346`; VOC:422 | wire contract. The new host must keep working with cc5.3 firmware |
| H6 | Diagnostics and backup file names (`diagnostics\cc5-*`, `desktop-installation.json`, `desktop-startup-task.xml`, `desktop-user-data.json`, `backups\control-center-inventory-*.json`) | `D\diagnostics\`, `D\control_center\device.py:1819` | historical evidence that tools read. "Control center" here is the firmware feature name |
| H7 | Thread names `NanoD-*`; executor prefixes `nanod-sonos/library/lookahead`; loggers `nanod.*` | overlay, stage, carousel, windows, artwork, runtime, standalone | contracts (DESKTOP_STAGE, K4) cite them; continuity of logs and status.json |
| H8 | Win32 class names `NanoD.KnobOverlay`, `NanoD.Stage.Host`, `NanoD.Carousel.*` | `overlay.py:106`, `stage\host.py:52`, `carousel.py:3315-3317` | internal (self-exclusion is by PID, `windows.py:302`); tests assert them |
| H9 | Mutex `Local\NanoDControlCenter.App`, event `Local\NanoDControlCenter.Show` | `D\standalone.py:2223`, `:2227` | **keep**: the rollback bundles v2–v7 hard-code them. Keeping them makes old and new builds mutually exclusive, so two companions never fight over the COM port during the switch or a rollback |
| H10 | Credential file header `NANOD-CREDENTIALS-1` | `D\control_center\credentials.py:72` | file format of `credentials.bin`, `queue-recovery.bin`, `shuffle-restore.bin`. Changing it makes them unreadable and breaks rollback |
| H11 | HTTP header `X-NanoD-Nonce` | `credentials.py:208` + page JS | internal local-authorization protocol |
| H12 | Info keys `nanod.iconPayload`, `nanod.iconHires` | `artwork.py:445`, `windows.py:122`, `carousel.py:1060` | internal dict keys |
| H13 | Environment switches `NANOD_FPS_HUD`, `NANOD_AUDIBLE_CUES` | stage engine, overlay | the hands-on runbooks and the user's saved preferences use them |
| H14 | Icon files `nano-d-app.ico`, `nano-d-tray-*.ico/png/svg` | `D\assets\app-icon\`, `Build-Desktop.ps1:37`, `standalone.py:74-75` | the designer's file names; `test_packaging.py:82-110` asserts them. The icons contain no text |
| H15 | Design handoff folders and files (`design_handoff_nano_d_master*`, `Nano_D Control Center.dc.html`, `knob-model.js`) | `D\design-reference\` | designer-owned records; `knob_golden.cjs:116` loads the page by name |
| H16 | Rollback bundles `desktop-dist-v2..v6` (and v7 if it ships old-name) | `Install-Desktop.ps1:40-44` | pinned SHA-256; they contain `NanoDControlCenter\NanoDControlCenter.exe`; never rebuild them |
| H17 | Historical runbooks | `D\firmware\BUILD-cc5.md`, `BUILD-cc5.3.md`, `RECOVERY.md` | rollback procedures for old-name bundles; tests assert them |
| H18 | DPAPI description `Nano_D++ MusicKit` | `credentials.py:59` | not used to decrypt. Optional cosmetic change, affects new writes only |
| H19 | Apple MusicKit key name `NanoD Control Center` | Apple developer portal (`README.md:94`) | external; tokens are signed by key ID |
| H20 | Knob setting `deviceName` default `Nano_<serial>` | `F\src\DeviceSettings.cpp:32` | the knob's own configurable name (Zero/One) |
| H21 | Legacy demo (`legacy_app.py`, `session.py:177`, `LEGACY-DEMO.md`) | `D\` | demo for the stock kit; not the Desk Dial app |

## 11. Risky items

1. **Flash interlock bypass.** `W\nanod_cc5_tooling.py:82` and every runbook check use
   `Get-Process -Name NanoDControlCenter` / `IMAGENAME eq NanoDControlCenter.exe`. After the
   rename they pass while `DeskDial.exe` holds the knob. Update them to check both names before
   the next firmware window (cc5.4).
2. **Two companions at sign-in.** If the old task `NanoD Control Center` (Running now) is not
   unregistered, both tasks start. If the mutex names were also renamed, the two processes
   would not exclude each other and would contend for the knob's port. Keep H9, and have the
   installer remove the old task (and a rollback install remove `Desk Dial`).
3. **Incomplete migration.** Paths are built in 5 places. `queue-recovery.bin` (present today)
   and `shuffle-restore.bin` live in the home root, not in `data\`, so a `data\`-only migration
   silently drops the Sonos queue-recovery state. Consolidate the paths and migrate the root
   `.bin` files too.
4. **AppData virtualization.** Run from a packaged parent (such as this desktop app), writes to
   `%LOCALAPPDATA%` and `%APPDATA%` are redirected (`Install-Desktop.ps1:104-106`). The
   migration and the add/remove of Start-menu shortcuts must run inside `Install-UserData.ps1`'s
   scheduled-task context, not in `Install-Desktop.ps1` directly.
5. **The offline sub splits the name.** With a plain space the balanced wrap renders `Open Desk`
   / `Dial on your PC` on the knob and on the desktop mirror. Use U+00A0, and write the C
   literal as `"Open Desk\xC2\xA0" "Dial on your PC"` (a hex-escape trap).
6. **Rollback identity.** The pinned v2–v6 bundles hard-code the old exe, folder, data path,
   task and shortcut. `Install-Desktop.ps1` needs a per-bundle identity table. A rollback
   returns to the pre-migration data snapshot: settings changed or Apple re-authorizations
   done in Desk Dial are not carried back unless an explicit `-CarryDataBack` copies them
   (hashed, after backing up the old files). *(Not built, RN-6: nothing is carried back.)*
7. **Stale-credential probes.** The `W\probes\*` scripts keep reading the old home. It still
   decrypts, so they run on outdated tokens or settings without failing.
8. **Credential header** H10 must not change. Old and new builds share the file format.
9. **Smoke-report coupling.** `standalone.py:2185` and `Install-Desktop.ps1:74` must move
   together. If they do not, the install is refused ("no passing frozen smoke test"); this
   fails closed.
10. **Build folders.** Rebuilding into `desktop-dist-v7` leaves both `NanoDControlCenter\` and
    `DeskDial\` in it (PyInstaller only replaces its own `--name` folder). Prefer v8 folders.
    If v7 ships under the old name, add it to the rollback list with its pinned hash.
11. **Tray preference reset.** Windows keys tray settings by exe path. The new exe gets a new
    `NotifyIconSettings` entry, so a "show in taskbar corner" choice resets once, and the stale
    `Nano_D++ Control Center` entry stays listed in Taskbar settings. It is harmless;
    Windows owns it. Do not delete it from the installer without asking.
12. **Recovery runbook.** The live quit block (`D\firmware\RECOVERY.md:241-243`) runs
    `Disable-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction Stop`, which throws once
    the old task is gone. That fails closed but blocks recovery. Its process check misses
    `DeskDial`. Make it dual-name and update `test_cc5_tooling.py:3728-3730`.

## 12. Uninstall and rollback (no uninstaller exists)

- **Forward install (old → Desk Dial):**
  1. Refuse to install if either process is running.
  2. Install to `Programs\DeskDial`.
  3. Migrate the data (section 4, task context).
  4. Register the `Desk Dial` task and the `Desk Dial.lnk` shortcut.
  5. After verification, unregister `NanoD Control Center`, delete `Nano_D++ Control Center.lnk`
     (task context), and back up then remove `Programs\NanoDControlCenter`.
  6. Keep `%LOCALAPPDATA%\NanoDControlCenter\` as the backup.
- **Rollback (Desk Dial → v6 or old-name v7):**
  1. Refuse to install if either process is running.
  2. Unregister `Desk Dial` and delete `Desk Dial.lnk`.
  3. Install the pinned bundle to `Programs\NanoDControlCenter`.
  4. Re-register `NanoD Control Center` and recreate `Nano_D++ Control Center.lnk`.
  5. The data is the old home as it was at migration time. `-CarryDataBack` is optional
     *(not built, RN-6)*.
  6. `%LOCALAPPDATA%\DeskDial\` stays, so returning to Desk Dial later does not migrate again
     (the migration only copies missing files).
- **Firmware rollback:** unaffected, because the USB identity is unchanged (H1, H2). The
  offline-sub copy change only ships with the next firmware (cc5.4 or later). cc5.3 keeps
  `Open Nano_D++ on your PC` on the knob until then.
- **Full removal, when the user asks:** both tasks, both shortcuts, both program folders.
  Data folders only on explicit request. The stale tray entries are Windows-owned.

## 13. Machine state observed (names only, read-only)

- Task `\NanoD Control Center`: Running. Action
  `…\Programs\NanoDControlCenter\NanoDControlCenter.exe --background`. Description as
  `Install-Desktop.ps1:136`.
- Installed exe: 7,640,995 B, dated 2026-09-25 01:24 (the v6 bundle).
- Start menu: `Nano_D++ Control Center.lnk`. Startup folder: empty.
- `HKCU\…\Run`: no entry. Uninstall and App Paths: no entry.
- `%LOCALAPPDATA%\DeskDial`: does not exist yet.

## 14. Rename plan

Written 2026-09-26. Sections 1–13 hold the detail; this section sets the order and the checks.

### 14.1 The name

- **Display name: `Desk Dial`.** Two words, title case, in every place a person reads it
  (tray, toasts, Settings, Start menu, Task Scheduler, the Apple consent page, docs). Use caps
  `DESK DIAL` only where the design already uses caps (the boot screen and the dev header).
  Never write `DeskDial`, `Deskdial` or `Desk Dial++` in UI text.
- **Internal slug: `DeskDial`** (no space). It is used for `DeskDial.exe`, the PyInstaller
  `--name`, `%LOCALAPPDATA%\Programs\DeskDial` and the data home `%LOCALAPPDATA%\DeskDial\`.
- **Display name also for:** the task `\Desk Dial`, the transient `Desk Dial Data Setup <guid>`
  task and `Desk Dial.lnk`, because people see these.
- **Unchanged:** everything in section 10. That includes the USB serial `NANO_D`, the USB, MIDI
  and HID names, the mutex and event names, `NANOD-CREDENTIALS-1`, the `control_center`
  package, and thread and class names.
- **Name check (2026-09-26): low risk.**
  - No US trademark exists for DESKDIAL, DESK DIAL or DESK-DIAL, live or dead.
  - "DeskDial" is also the name of a new iPhone timer app with 0 ratings, and of a dormant 2024
    hobby repo with 0 stars. Writing it with a space keeps it visibly separate from both.
  - The only nearby mark is DIALDESK (US reg. 7724754, call-centre software). It matters only if
    you file a trademark yourself.
  - The EU register was not checked.

### 14.2 Order of work

0. **Fix the flash-safety tooling first.** This comes before any flash, including cc5.4's.
   - Make the interlock recognise both process names: `W\nanod_cc5_tooling.py:82` and `:661`
     (11.1), and `D\diagnostics\Verify-NativeDesktop.ps1`.
   - Make the quit block at `D\firmware\RECOVERY.md:241-243` work with both names, and do not let
     it throw when the old task is gone (11.12). Update `test_cc5_tooling.py:3728-3730` to match.
   - Make the `W\probes\*` scripts resolve the home folder once: the new home, or the old one
     only if the new one does not exist (11.7).
1. **One path module.**
   - Put the home, data, logs, backups, credentials and the root `.bin` paths in
     `control_center/paths.py`, along with the legacy-home constant and the migration function
     (section 4).
   - Make the 5 separate constructions from 3.4 use it. Once this is done, the rename is a
     single change.
2. **App strings.**
   - Change A1–A17 (section 2). A5 and A6 drop the brand.
   - Change the matching contract rows in the same change: `V5_VOCABULARY.md` 714/731/732, the
     rest of section 6, and `APP_ICON.md:40-41`.
   - The Python offline mirror (A17) becomes `'Open Desk Dial on your PC'`.
3. **Firmware copy.**
   - C1: `OFFLINE_SUB = "Open Desk\xC2\xA0" "Dial on your PC"`. Keep the split literal (11.5).
   - C2: the boot screen becomes `DESK DIAL\nIS BOOTING...`.
   - C3 (optional): `Welcome to Desk Dial!`.
   - Update the `PRESENTATION_V5.md` width rows (597, 684, 685, 1045) to 192.2 px / LVGL 198,
     two balanced lines, NBSP.
   - Update `W\lcd-preview\cc54_report.py:1197-1252` to the new copy.
   - Ship C1 in the same window as the renamed desktop. The cc5.4 binary is not built yet, so it
     can carry C1. If the old-name desktop has to ship with cc5.4, hold C1 until the next
     firmware; the knob should never tell the user to open an app name that isn't installed.
4. **Build and install (upgrade from the old name).**
   - **`Build-Desktop.ps1`:**
     - New folders `desktop-dist-v8` and `desktop-build-v8` (11.10). The unshipped old-name v7
       build is never installed and is not pinned.
     - `--name DeskDial`, plus a `--version-file` with FileDescription and ProductName
       `Desk Dial`.
     - The running-process check covers both names.
   - **`Install-Desktop.ps1`:**
     - A per-bundle identity table: pinned v2–v6 use the old names, new bundles use `DeskDial`
       (11.6).
     - Refuse to start if either `DeskDial` or `NanoDControlCenter` is running.
     - Change the smoke-report path together with `standalone.py:2185` (11.9).
     - New `-DryRun` switch: it runs every check and refusal, writes
       `diagnostics\desktop-install-plan.json` and changes nothing.
     - Seed `local\` into staging only (14.3).
     - Register `\Desk Dial` with the new description.
     - Then, only after the bundle hashes verify and the data step reports a pass:
       - unregister `\NanoD Control Center`;
       - move `Programs\NanoDControlCenter` to
         `D\backups\desktop-program-NanoDControlCenter-<UTC>` (moved, never hard-deleted);
       - record both in `diagnostics\desktop-installation.json`.
     - Installing a pinned rollback bundle does the reverse (section 12).
   - **`Install-UserData.ps1`** runs in the task context (11.4), in this order:
     1. Migrate from the old home. Copy only the files missing at the new location, check each
        by SHA-256 and write `DeskDial\migration.json` (section 4). The root `.bin` files are
        included.
     2. Copy the staged seeds, again only files that are missing.
     3. Create `Desk Dial.lnk` and delete `Nano_D++ Control Center.lnk`.
   - **First-run fallback in the app.** `standalone.main()` calls the same migration function
     after it gets the mutex, if `migration.json` is absent and the old home exists. It never
     runs on `--smoke-test` or `--check-music`. This covers a manual copy of the program folder
     that skips the installer.
   - The old home `%LOCALAPPDATA%\NanoDControlCenter\` stays untouched (section 4, item 5).
5. **Tests.**
   - Update the 36 lines in section 8.
   - Add tests for:
     - Migration: copies only missing files, includes the root `.bin` files, verifies hashes,
       never runs in smoke mode, and leaves the old home untouched.
     - The seed-order hazard in 14.3.
     - The identity table, covering both the forward install and a rollback.
     - Removal of the old task, shortcut and program folder, with mocks.
     - The version resource (`test_packaging.py`).
     - The offline mirror: `fit_two_lines` never splits "Desk Dial".
     - A smoke run leaves `DeskDial\data\` empty.
   - Run the full pytest suite.
6. **Docs.**
   - Update `README.md` and `DESKTOP.md` (section 7). Add the tray-preference reset note and
     the cleanup note.
   - Add a rename ruling to `V5_VOCABULARY.md` that points here.
   - The UI V2 master handoff prompt should state "Desk Dial" before it goes to the designer.
   - Historical runbooks, pinned bundles and design-handoff files stay as they are.

### 14.3 A new hazard found while planning

`Install-Desktop.ps1:89-96` copies `local\settings.json` and `local\credentials.bin` into the
data folder before the task-context step runs. Both files exist today.

- **Today:** the data folder already holds the live files, so the "only if missing" rule keeps
  them.
- **After the rename:** on the first Desk Dial install, `DeskDial\data\` is empty. The project
  seeds would land there first, and the migration would then skip the user's live
  `settings.json` and `credentials.bin` from the old home because they are no longer "missing".
  Desk Dial would start on stale settings and an older Apple sign-in, with no error.
- **Fix:** seed `local\` into staging only, and run the migration from the old home before the
  staged seeds (14.2 step 4). Add a test in which both sources exist and the old home wins.

### 14.4 Checks that prove it

1. **Frozen smoke test.** Run `desktop-dist-v8\DeskDial\DeskDial.exe --smoke-test --headless`.
   - `%LOCALAPPDATA%\DeskDial\logs\smoke-test.json` shows `passed: true` and `frozen: true`,
     `executable` is that exe, and the report is newer than the exe.
   - The run created nothing in `DeskDial\data\`.
   - The old home's file list and hashes are the same before and after (names and hashes only).
   - `(Get-Item …\DeskDial.exe).VersionInfo.FileDescription` is `Desk Dial`.
2. **Dry-run install review.** Run `Install-Desktop.ps1 -Bundle desktop-dist-v8 -Mirror -DryRun`
   and read `diagnostics\desktop-install-plan.json`. It should show:
   - identity `DeskDial`;
   - a refusal if either process is running;
   - task `\Desk Dial` to register and `\NanoD Control Center` to unregister;
   - the old program folder to be moved to `backups\` and the old `.lnk` to be removed;
   - the migration list: whichever `data\` files and root `.bin` files exist in the old home,
     with names and sizes only;
   - no data file to be written from `local\` before the migration.

   Then dry-run the rollback `-Bundle desktop-dist-v6 -DryRun` and confirm it plans the reverse.
   After both dry runs the scheduled tasks, the Start-menu shortcuts and both program and data
   folders are unchanged. Run the real install only after this review.
3. **Harness widths.**
   - Move `rename\measure_desk_dial.py` from the session scratchpad into `W\lcd-preview\` so it
     survives this session.
   - It must reproduce the four calibration values in 5.2 and give:
     - `DESK DIAL`: 74.8 / 75 against a 138 px limit;
     - `Open Desk Dial`: 110.4 / 114 against 170;
     - `on your PC`: 78.0 / 80 against 170.
   - `lcd_preview.fit_two_lines` returns `Open Desk Dial` / `on your PC`.
   - `cc54_report.py`'s LCD render gate passes with the new copy.
   - The LVGL harness (`W\lcd-preview\main.cpp`) renders the same split, and the NBSP shows as
     a space, not a missing-glyph box.
4. **After the real install.**
   - Exactly one sign-in task (`\Desk Dial`), one shortcut (`Desk Dial.lnk`) and one process
     (`DeskDial.exe`) exist.
   - Every entry in `migration.json` shows `hashMatch: true`.
   - Settings shows the same speaker settings and Apple Music connection as before.
   - The tray tooltip reads `Desk Dial · Knob connected`.
   - With `DeskDial.exe` running, the flash tooling refuses to flash (step 0).

## 15. Implementation record (2026-09-26, the rename package)

Built to sections 1-14 and the lead's RENAME ruling, whose four risky items take precedence where the
two differ. Nothing was installed, flashed or shown on screen; the checks of 14.4 items 1, 2 and 4 on
the real profile belong to the hardware window (`firmware\BUILD-cc5.4.md` steps 1 and 9).

| # | Plan | Built | Why |
|---|---|---|---|
| RN-1 | New folders `desktop-dist-v8` / `desktop-build-v8`, FileVersion 8.0.0.0 (3.1, 11.10) | `desktop-dist-v7\DeskDial\DeskDial.exe`, FileVersion 7.0.0.0 (`desktop-version.txt`). Build-Desktop.ps1 moves an old-name `NanoDControlCenter\` build out of the dist folder into the work folder (never deleted) before PyInstaller runs, and refuses an exe without the `Desk Dial` FileDescription | the ruling names the v7 folder; 11.10's "cleaned v7" option. The unshipped old-name v7 build is not pinned |
| RN-2 | Migrate `data\` and the root `.bin` files; `logs\` stays (4.2) | the **whole** old home (`data\`, `logs\`, `backups\`, root `.bin` files, anything else), copied once (`DeskDial\migration.json` marks it done, so a later install never brings back a `queue-recovery.bin` the app removed), each file hash-checked under a `.migrating` name before it takes its own, a file already in the new home kept, the old home only read | ruling item 3 |
| RN-3 | Primary step in Install-UserData.ps1 plus a first-run fallback in `standalone.main()` (4.1, 14.2 step 4) | installer only: Install-Desktop.ps1 plans it (also in `-DryRun`) and runs it through its one-shot task step (Install-UserData.ps1, `Desk Dial Data Setup <guid>`); the app never reads the old home (`control_center/paths.py` names it only as `LEGACY_HOME_NAME`) | ruling item 3 ("inside Install-Desktop.ps1, not the app"); the copy itself must run outside AppData virtualization (11.4). A program folder copied by hand without the installer starts with empty data; the old home stays. **Accepted by the lead (2026-09-26).** |
| RN-4 | — | the task step first checks the installed exe's hash **as the signed-in user sees it**, and stops before any data work if it differs | `Programs\DeskDial` is a new folder: from a packaged parent its creation could be redirected (11.4) and the sign-in task would find no exe. **Accepted by the lead (2026-09-26).** |
| RN-5 | Retire the old name after verification (3.2, 12) | in this order: bundle hashes verify, task step (program check, migration, seeds, new shortcut) passes, `\Desk Dial` registered, `\NanoD Control Center` unregistered, then a second task step removes `Nano_D++ Control Center.lnk` and moves `Programs\NanoDControlCenter` to `backups\desktop-program-NanoDControlCenter-<UTC>`; `diagnostics\desktop-installation.json` records both (`replaced`). A rollback bundle does the reverse by the same table (`$identities`, `$bundleIdentities`) | ruling item 2; 11.2 |
| RN-6 | `-CarryDataBack` for a rollback (11.6, optional) | not built: no installer option carries data back. Settings changed and Apple Music sign-ins made in Desk Dial stay only in `%LOCALAPPDATA%\DeskDial\`, and are copied back by hand, with the user, if wanted (`firmware\BUILD-cc5.4.md` "Desktop rollback, v7 -> v6", `DESKTOP.md`, the `Install-Desktop.ps1` header) | optional; a rollback reads the old home as it was copied |
| RN-7 | A11 wording (optional) | unchanged | optional; "control-center firmware" is the firmware feature's name (H6) |
| RN-8 | `TRAY_NAME` (optional) | kept `NanoDControlCenter` | internal (H8); nothing shows it |
| RN-9 | C3 serial banner (optional), H18 DPAPI description (optional), dev-only strings (2) | unchanged, except the never-shown smoke frame subtitle (`Desk Dial`) | optional |
| RN-10 | Offline screen: no heading (5.1); the ruling mentions an offline heading `DESK DIAL` | **no heading**: K1 8.10 and the r2.2 design (S01:141) have none and `cc54_report` checks that none shows. A heading would measure 74.8 px (LVGL 75) against 138 (5.2); adding one is a one-line firmware change plus a K1 amendment | ~~lead's decision; flagged in the report~~ **Decided by the lead (2026-09-26): no heading**, as built (K1 8.10 and r2.2; `cc54_report` keeps checking that none shows) |
| RN-11 | Firmware copy ships with the renamed desktop (14.2 step 3) | C1 and C2 in `cc_display.cpp` / `ui_bootimg.c`; binaries A, B and C rebuilt and repackaged (UNFLASHED; earlier packages kept as `*.superseded-*`), `BUILD-cc5.4.md` tables updated; the harness dump `harness\cc54-handoff` re-rendered (`cc54_report` 39 of 39); the offline entry of `tests\test_cc_render_snapshot.py` amended by hand (nine digests; its docstring says why) | TOOL-bc's note 1 |
| RN-12 | The UI V2 handoff prompt states the new name (6, 14.2 step 6) | not edited | the prompt has not gone to the designer; state the name when it does |
| RN-13 | The knob never names an app that is not installed (14.2 step 3) | a desktop rollback to v6 from a cc5.4 knob always follows the firmware rollback to cc5.3: every step-9 NO-GO in `firmware\BUILD-cc5.4.md` rolls back the firmware first, then the desktop, and the desktop rollback block refuses until the binary's rollback record is newer than its install record and reports a verified cc5.3. cc5.3 next to Desk Dial (the old copy) stays allowed (section 12). Recorded in K1 16.8 E-r | review finding RN-R3: cc5.4 carries C1 and C2, so a desktop-only rollback after step 9 would have left `Open Desk Dial on your PC` next to NanoD Control Center |

Checks run: `harness\measure_desk_dial.py` (moved from the scratchpad; every value of 5.2
reproduced, exit 0); the LVGL harness with `cc54_report.py` (39 of 39; `offline` requires the split
`Open Desk Dial` / `on your PC`, and the render shows the no-break space as a space); a scratch build
of the Desk Dial bundle (FileDescription and ProductName `Desk Dial`, FileVersion 7.0.0.0) and its
frozen `--smoke-test --headless` with `LOCALAPPDATA` pointed at a scratch folder (14 of 14 checks; it
wrote only `DeskDial\logs\smoke-test.json`); and `Install-UserData.ps1` run against temporary folders
(`tests\test_packaging.py` `UserDataStepSandboxTests`). The installer's dry-run logic is covered only by
the static tests (`tests\test_packaging.py` `InstallScriptTests`, `test_the_dry_run_changes_nothing`);
the dry run itself is 14.4 item 2 and belongs to the supervised runbook (`firmware\BUILD-cc5.4.md` step
9a), with the user.

Process breach (review finding RN-R4): the rename package also ran a byte-identical copy of
`Install-Desktop.ps1 -DryRun`, twice (the `desktop-dist-v7` and `desktop-dist-v6` plans), with
`LOCALAPPDATA` pointed at a scratch folder. The hard rule for this release is "edit it, don't run it".
The redirect did not keep the run off the real system: it read the real process list, Task Scheduler
and Start menu. It only read them; nothing on the machine changed, and no `desktop-install-plan.json`
was written to `diagnostics\`. But whether it changed nothing depended on the untested script under
review. Those runs are not evidence for this release, and the plans they wrote in the session
scratchpad are not checks. No test or test tool under `tests\` runs `Install-Desktop.ps1`, and a static
test keeps it that way (`InstallScriptTests.test_install_desktop_is_never_run_by_a_test`).

**Acknowledged by the lead (2026-09-26).** RN-R4 stands as a recorded process breach of this release. The installer's dry run is only the supervised runbook's step 9a, run with the user; no agent runs `Install-Desktop.ps1` in any form, not even a copy with `-DryRun`.
