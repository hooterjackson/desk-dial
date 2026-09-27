# App and tray icons (desktop v5, user handoff 2026-09-24)

Status: **implemented in desktop v5** (items 1-8; FLOATING_KNOB.md section 9.14 records that section 5 below replaces that spec's section 6 tooltip rule, and 9.18 the item 3 correction). Code: `ui.apply_app_icon` and `ui.AppWindowIcons` (item 3), `standalone.make_tray_icon`/`TrayIconApi`/`TrayPresenter`/`taskbar_theme` (items 4-6), `standalone.smoke_app_icons` (item 7); tests in `tests/test_cc_tray.py`, `tests/test_packaging.py` and `tests/test_cc_runtime_overlay.py` (item 8).

Source: `assets/app-icon/` is copied byte-for-byte from the designer handoff, `design_handoff_app_icon`. Its `README.md` is normative. The assets are final: never redraw them, and never re-encode them unless a size is missing.

| Use | File |
|---|---|
| Exe, Start-menu shortcut, window title bar, taskbar button | `ico/nano-d-app.ico` (16, 20, 24, 32, 40, 48, 64 and 256 px; hand-tuned small drawing at 16–24 px) |
| Tk windows, high-DPI photo icons | `png/nano-d-app-256.png` and `png/nano-d-app-32.png` |
| Tray icon | `ico/nano-d-tray-{dark\|light}-{connected\|missing}.ico` (16, 20, 24 and 32 px) |

## Requirements

1. **Exe icon.** `Build-Desktop.ps1` passes `--icon <abs path>\assets\app-icon\ico\nano-d-app.ico` to PyInstaller.
   - `assets` are already bundled (`--add-data assets;assets`), so `assets/app-icon` ships automatically.
   - Verify: after the build, the v5 exe's icon resource holds all 8 frames. Use `ExtractIconExW` or `LoadImageW` from the exe, or a PE resource read.
2. **Start-menu shortcut.** `Install-UserData.ps1` sets `IconLocation` to the installed exe, index 0.
3. **Tk windows** (root, Settings, and every Toplevel). `ui.apply_app_icon(root)` runs once on the root, before any Toplevel is created, in both `standalone.py` and `app.py`:
   - `root.iconphoto(True, PhotoImage(256 png), PhotoImage(32 png))`, and nothing else through Tk. Tk's first default icon registers the `TkTopLevel` window class with the exact 32 px frame.
   - On Windows, a `<Map>` binding on the `Toplevel` and `Tk` class tags (`ui.AppWindowIcons`). Each mapped window gets the `.ico`'s own frames for that window's DPI. `LoadImageW(<nano-d-app.ico>, IMAGE_ICON, cx, cx, LR_LOADFROMFILE)` loads them, with `cx = GetSystemMetricsForDpi(SM_CXICON or SM_CXSMICON, GetDpiForWindow(frame))`. They are sent to the window as `WM_SETICON` `ICON_BIG` and `ICON_SMALL`. The first mapped window also sets the class icons (`GCLP_HICON`, `GCLP_HICONSM`). The HICONs are cached per size and kept for the life of the process.

   **Correction (final review, 2026-09-24):** the handoff README's `root.iconbitmap(default=<nano-d-app.ico>)` is not used, for two reasons:
   - Tk 8.6.15 cannot read this `.ico`'s PNG-compressed frames. It falls back to the 16 px frame stretched to 32 px.
   - Because it is the first default call, it registers the class with that blurred icon. The photos that follow then land on the `TkChild` class, which no toplevel uses.

   Passing `iconphoto` alone still lets Windows shrink the regular drawing for the small icon, which the README forbids. The per-window `.ico` frames avoid both problems: the title bar and the taskbar button show the hand-tuned small drawing at 16–24 px and the regular drawing from 32 px. Scaling or moving a window to a monitor with another DPI later leaves Windows to scale the loaded icon.

   Resolve paths through the existing assets resolver, so they work frozen (`sys._MEIPASS`) and in dev. Do not set an explicit AppUserModelID; the frozen exe's own identity groups the taskbar buttons.
4. **Tray icon** (pystray 0.19.5, win32). Subclass `pystray.Icon` as `TrayIcon`, overriding `_assert_icon_handle` so it never re-serializes a PIL image, because that path drops the hand-tuned frames:
   - `LoadImageW(NULL, <ico path>, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)`, where `cx = cy = GetSystemMetricsForDpi(SM_CXSMICON, dpi)`;
     - `dpi` comes from `GetDpiForSystem()`, or from the tray's monitor when available;
     - fall back to `GetSystemMetrics(SM_CXSMICON)`.
   - It is a no-op when a handle already exists. Changing the path clears the handle and calls pystray's `_update_icon` path on the tray thread; the `icon` property setter already does this, so keep pystray's lifecycle, including `DestroyIcon`.
   - `Icon(…, icon=<PIL image>)` is still given a small PIL image. pystray requires one, and `_update_icon` checks `self.icon`. The Win32 handle, however, always comes from the `.ico` path.
   - Declare `LoadImageW` and `GetSystemMetricsForDpi` with x64-correct argtypes and restypes on a private `WinDLL`.
5. **Tray state.**
   - The tray shows **connected** when the knob is connected, connecting-ready, or claimed and ready. It shows **missing** when there is no knob, it is reconnecting, the bridge is closed, or the user disconnected it on purpose.
   - The icon, the tooltip and the menu header switch together, on the Tk thread, on every change of that boolean, and only on a change:
     - **Connected:** tooltip `Desk Dial · Knob connected`, menu header `Knob connected`.
     - **Missing:** tooltip `Desk Dial · Knob not found`, menu header `Knob not found`.
     - The app is Desk Dial since 2026-09-26 (`design-reference/ui-v2-analysis/rename-desk-dial.md`); the
       designer's handoff still says `Nano_D++ · …`. The icon files keep their `nano-d-*` names (they carry no text).
   - The detailed device status stays available as a second disabled menu line. This supersedes FLOATING_KNOB.md section 6's tooltip rule.
6. **Taskbar theme.** Read `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\SystemUsesLightTheme`: 0 means the `dark` set, 1 the `light` set, and a missing value means `dark`.
   - Poll it from the Tk thread every 2 s; it is cheap and needs no window subclassing.
   - Swap the icon live when it changes.
7. **Smoke test** (frozen gate). This adds checks and weakens none. The checks:
   - All 5 `.ico` files and the two PNGs exist in the bundle.
   - The ICO frames match the table above (Pillow `info['sizes']`).
   - `LoadImageW` returns a non-null `HICON` for the small-icon size from each tray ICO and from the app ICO, and each is destroyed afterwards.
   - The running exe (`sys.executable` when frozen) has an embedded icon with at least 1 frame.
8. **Tests** (headless). These cover:
   - the theme and state mapping to files, tooltips and headers;
   - the registry read, with a fake winreg;
   - `TrayIcon._assert_icon_handle`, using a fake loader to prove it uses the file path and the small-icon size, and never calls `serialized_image`;
   - the ICO frame inventory;
   - `Build-Desktop.ps1` containing `--icon` with the app ICO;
   - `Install-UserData.ps1` `IconLocation`;
   - root icon calls in `standalone.py`, checked by reading the source or through an injectable root fake;
   - `ui.apply_app_icon` (`iconphoto` only, the `<Map>` bindings) and `ui.AppWindowIcons`: the sizes for each window's DPI, `WM_SETICON`, the class icons set once and cached handles, all with a fake API; `LoadImageW` returns exactly the designer's PNG pixels at 16–64 px (no window).

   Tk-window tests stay in the Tk modules and run at install time. `test_cc_ui.ChromelessAppIconTests` maps a hidden Settings window and compares its `WM_GETICON` and class icons, pixel for pixel, with the PNGs.
