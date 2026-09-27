# Handoff: Nano_D++ companion — app icon and tray icon

> **Revision 2.** The icon itself is unchanged. With no main window, the app icon is used for the Settings window, the taskbar button while Settings or an overlay is open, the exe, Start and the installer. The tray icon is the companion's permanent presence.


## Overview
New icon for the Nano_D++ Windows companion (Python/Tk tray app). The icon is an abstract view of the knob from above: a dark disc, and on it a white LED ring that fades in over one full turn and ends on an orange cursor dot.

There are two uses:
- **App icon:** the window title bar, the taskbar button, Start and the installer.
- **Tray icon:** the notification area. It shows two states: knob **connected** and knob **missing**.

## About these files
The files are **final production assets**, ready to use as they are. The SVGs are the source; the PNGs and `.ico` files are rendered from them. Don't redraw the icons. If you need a size that isn't included, re-render it from the SVG.

## Fidelity
**Final (pixel-ready).** Colours, geometry and small-size variants are all decided.

## Files
```
svg/
  nano-d-app.svg                 32 px and up (5-unit ring stroke)
  nano-d-app-small.svg           24 px and below (8-unit stroke, bigger dot)
  nano-d-tray-dark-connected.svg   white ring + orange dot (for a dark taskbar)
  nano-d-tray-dark-missing.svg     white dashed ring, 60 % opacity, no dot
  nano-d-tray-light-connected.svg  ink ring + orange dot (for a light taskbar)
  nano-d-tray-light-missing.svg
png/
  nano-d-app-{16,20,24,32,40,48,64,256}.png
  nano-d-tray-{dark|light}-{connected|missing}-{16,20,24,32}.png
ico/
  nano-d-app.ico                  16 · 20 · 24 · 32 · 40 · 48 · 64 · 256 (PNG-compressed frames)
  nano-d-tray-{dark|light}-{connected|missing}.ico   16 · 20 · 24 · 32
```
The app `.ico` uses the small drawing for 16–24 px and the regular drawing for 32 px and up. Keep that split if you rebuild it.

## Geometry (64-unit viewBox, 0° = 12 o'clock, clockwise)
**App icon:**
- **Disc:** r 31, `#201e1d`.
- **Ring:** centred at 32,32.
  | Drawing | Ring radius | Stroke width | Dot radius |
  |---|---|---|---|
  | Regular | 21 | 5 | 4.5 |
  | Small | 19 | 8 | 6.5 |

  Ring colour is `#f3f2f2`. Its opacity ramps linearly from 4 % to 100 %, starting just after 60° and running clockwise a full turn to 60°. The ramp is done with a luminance mask made of overlapping bands, so there are no seams at any DPI.
- **Cursor dot:** at 60° on the ring radius, `#ff6a1a`.

**Tray icon:** no disc, so the glyph sits directly on the taskbar.
| State | Ring |
|---|---|
| Connected | r 22, stroke 9, opacity ramps 10 % → 100 % |
| Missing | r 22, stroke 9, dashed 7/7, 60 % opacity, no dot |

Connected has an orange dot, radius 9. The ring is `#f3f2f2` on a dark taskbar and `#201e1d` on a light taskbar.

## Colours
| Role | Hex |
|---|---|
| Disc / ink | `#201e1d` |
| Ring | `#f3f2f2` |
| Cursor dot | `#ff6a1a` |

The dot is orange rather than red so it isn't read as an error badge at tray size. Don't recolour the dot to show status; the dashed ring is the only "missing" signal.

## Implementation (Python/Tk companion)
1. **Window / taskbar icon:** `root.iconbitmap(default=resource_path("ico/nano-d-app.ico"))`. For crisp high-DPI rendering, also call `root.iconphoto(True, PhotoImage(file=...png/nano-d-app-256.png), PhotoImage(file=...png/nano-d-app-32.png))`.
2. **Executable / installer:** embed `ico/nano-d-app.ico` as the exe icon (PyInstaller `--icon`, or the installer's icon setting) and use it for the Start menu shortcut.
3. **Tray icon:** load the `.ico` that matches the connection state and the taskbar theme. With pystray, use `Image.open(ico_path)`; with raw Win32, use `LoadImage(..., IMAGE_ICON, GetSystemMetrics(SM_CXSMICON), …)` so Windows picks the right frame for the current DPI.
   - **Connected:** `nano-d-tray-{theme}-connected.ico`.
   - **Missing or reconnecting:** `nano-d-tray-{theme}-missing.ico`.
   - **Switch** the icon on every connection change that is already sent to the tray menu, so the icon and the menu header ("Knob connected" / "Knob not found") never disagree.
4. **Taskbar theme:** read `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\SystemUsesLightTheme` (0 = dark taskbar → `dark` set, 1 = light → `light` set). Watch for `WM_SETTINGCHANGE` with `ImmersiveColorSet` and swap the icon live.
5. **Tooltip:** "Nano_D++ · Knob connected" / "Nano_D++ · Knob not found".
6. **Packaging:** bundle the `ico/` and `png/` folders with the app and resolve their paths at runtime (e.g. `sys._MEIPASS` under PyInstaller).

## Don't
- Don't add a separate status badge on top of the tray icon.
- Don't use the app icon (with its disc) in the tray, or the disc-less tray glyph as the app icon.
- Don't scale the regular drawing below 32 px. Use the small one.
