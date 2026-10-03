# Handoff: Nano_D++ Windows picker — carousel redesign

## Overview
This replaces the companion's current Windows picker overlay, which is a dark grid of thumbnails in a black panel. The new picker is a horizontal carousel:
- The **selected window sits in the centre at full size.** Its neighbours shrink and dim with distance.
- **Each knob detent slides the carousel by one window.**
- **Only the centre window is labelled,** with its app, a readable title and a short description.
- The **background is a liquid-glass pane** (default). The design also includes a "no background" variant, where the cards float over a dimmed desktop.

Knob-side behaviour is unchanged: the MIDI SKIPPER profile at 20 detents, the frozen MRU list, entry at index 1, and the buttons (Cancel red, Home, Windows, Switch green).

## About the design files
`Window Carousel.dc.html` is a **design reference built in HTML**, an interactive prototype. It is not production code. To view it, serve this folder over HTTP (`python -m http.server`) and open the file.

Rebuild it in the companion's overlay stack (Python). The overlay must be a **topmost, click-through-when-idle, never-focus-stealing** window, as before. The glass look needs a real backdrop blur. Two ways to get it on Windows 11:
- **DWM system backdrop:** `DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_TRANSIENTWINDOW)` (Acrylic), plus `DWMWA_USE_IMMERSIVE_DARK_MODE`.
- **Custom compositing:** capture the desktop behind the pane and blur it yourself (a layered window, or a Qt/Skia surface).

If Tk can't composite this, host the overlay in a small PySide6 / WinUI / WebView2 window. Everything else in the companion stays in Tk.

## Fidelity
**High-fidelity** for layout, sizes, colours and motion. The window thumbnails and the desktop in the prototype are wireframe placeholders. In production they are **live DWM thumbnails** (`DwmRegisterThumbnail`); for minimized windows, use the last captured frame.

## Layout (reference stage 1280 × 720; scale to the monitor that has focus)
- **Glass pane:** 1140 × 560, centred horizontally, top 92. Corner radius 0 by default (Modernist); a 0–28 px variant is also available.
- **Carousel centre:** x 640, y 300. The base card is **480 × 300** (16:10). Thumbnails fill the card with `object-fit: cover`, top-aligned.

Each card is scaled, shaded and faded by its distance from the centre:
| Distance from centre | Offset X | Scale | Opacity | Dark overlay | Interactive |
|---|---|---|---|---|---|
| 0 (selected) | 0 | 1.00 | 1 | 0 | click = Switch |
| 1 | ±320 | 0.56 | 0.95 | 0.22 | click = select |
| 2 | ±460 | 0.34 | 0.60 | 0.44 | no |
| 3 | ±560 | 0.26 | 0 (hidden) | — | no |
| 4 or more | ±620 | 0.20 | 0 (hidden) | — | no |

The dark overlay is a `#111` layer over the card at that opacity. The largest visible card must stay about 13 px or more inside the pane edges.

- **Arc variant (optional):** side cards also get `rotateY(∓34°)` with perspective 1400 px, plus translateY(−6 px × distance).
- **Selected card:** a 2 px outline at 90 % white, offset 6 px, and a shadow of `0 24px 60px rgba(0,0,0,.45)`. Side cards get `0 12px 30px rgba(0,0,0,.3)`.
- **App badge:** on every card, a 32 × 32 app icon inset 14 px from the bottom left, with a shadow of `0 2px 8px rgba(0,0,0,.45)`. It scales with its card.

### Label (centre window only)
Centred in a 900 px column at top 476:
| Row | Style |
|---|---|
| App | 18 px icon + app name, 15/20, white at 92 % |
| Title | 28/34, weight 600, tracking −0.01 em, white, one line with ellipsis |
| Description | 15/20, white at 88 % |

### Position dots
- Placed at top 616, centred, 8 px apart, one dot per window.
- **Selected:** 22 × 6, full opacity.
- **Others:** 6 × 6 at 60 % opacity.
- Width and opacity change over 320 ms ease-out.

## Visual treatments
### Liquid glass (default)
- **Pane fill:** `rgba(18,18,20,0.58)` with backdrop blur 40 px and saturate 1.8.
- **Border:** 1 px `rgba(255,255,255,0.22)`.
- **Shadows:** inset top highlight `0 1px 0 rgba(255,255,255,.40)`, inset bottom `0 -1px 0 rgba(255,255,255,.08)`, and a drop shadow `0 40px 90px rgba(0,0,0,.35)`.
- **Specular sheen:** a white overlay fading from 12 % at the top to 0 at 24 % of the height.
- **Desktop behind:** dimmed 12 %.

### No background
- **Pane:** none. The desktop is dimmed **55 %** (adjustable 0–80 %).
- **Card shadows:** selected `0 30px 70px rgba(0,0,0,.6)`, sides `0 16px 40px rgba(0,0,0,.5)`.
- **Label text shadow:** `0 1px 2px rgba(0,0,0,.6), 0 2px 18px rgba(0,0,0,.55)`.

## Motion
| Curve | Value |
|---|---|
| Ease-out (enter) | `cubic-bezier(0.22,1,0.36,1)` |
| Spring (emphasis) | `cubic-bezier(0.34,1.45,0.64,1)` |

- **Detent:** every card retargets its transform (420 ms ease-out) and opacity (300 ms). Fast turns retarget mid-flight and never queue. Keep one transform per card and animate it toward the new target.
- **Past either end:** the list does not wrap. The whole row nudges 12 px in the direction you turned and springs back in 160 ms ease-out. This matches the ring's bound flash.
- **Open:** the pane fades in and grows from scale 0.97 to 1 (opacity 280 ms, transform 420 ms). The cards fade in over 260 ms and the desktop dim fades in over 320 ms.
- **Switch (green button):** the centre card grows to scale 1.35 and fades out (420/300 ms). At 380 ms the overlay closes and the target window is brought forward. A glass toast reading "{App} · {Title}" appears at the centre of the screen: it rises 8 px and scales from 0.96 to 1 with the spring, stays up to 1.5 s, then fades.
- **Cancel (red button):** the overlay fades out, focus goes back to the previous window, and the toast reads "Cancelled · focus restored".

## Label text: parsing window titles
The companion only knows the process name and the window title. Derive the three label lines from those:
- **app:** the product name from the exe's version info (`FileDescription`), e.g. "Google Chrome", "File Explorer", "Bambu Studio".
- **title:** the window title with the app suffix removed, then cleaned up by app-specific rules:

  | App | Raw window title | Title | Description |
  |---|---|---|---|
  | Slack | `Danny Lewis (DM) - Riot Games - Slack` | Danny Lewis | Direct message · Riot Games |
  | Slack | `#channel - Workspace - Slack` | #channel | Channel · Workspace |
  | Chrome | `Riot Games - Calendar - Week of September 22, 2026 - Google Chrome` | Calendar · Week of Sep 22 | Riot Games · Google Calendar |
  | Chrome | `9 - Understand the PCB - Engineering…` (leading count = tab badge) | Understand the PCB | Engineering docs · 9 tabs |
  | Chrome | `Meet - …` | Google Meet | In a call · Chrome (only if the tab is audible) |
  | Bambu Studio | leading `*` | Rack_Base(2) | Unsaved changes · 3D print project |
  | Explorer | `Downloads - File Explorer` | Downloads | Folder · Minimized (if iconic) |
  | Claude / ChatGPT | the title, or the app name if blank | Nano D Control Center | Conversation · desktop app |
  | Fallback | anything else | the full title | the process name |

  Keep the rules in a small table-driven module so more apps can be added.
- **Minimized** windows add "Minimized" to the end of the description.
- **Duplicates:** when two windows would get identical labels, add the Chrome profile name or the monitor name to the description.

## Icons
- **Source:** read each window's icon with `WM_GETICON` (ICON_BIG), then `GetClassLongPtr(GCLP_HICON)`, then the exe's icon. For UWP/MSIX apps, use the package logo.
- **Sizes:** render at 64 px and scale it down for the 32 px badge and the 18 px label icon.
- **Missing icon:** use a square tile in the app's dominant colour, with its first letter in white (Archivo, 700).
- `assets/apps/` holds the sample icons used in the prototype; they are placeholders, not for shipping.

## State
State: `{ order[] (frozen MRU snapshot at open), sel (starts at 1), open, switching, bump (−1 | 0 | 1) }`.
- **Closed windows** stay in the list at 35 % opacity, and Switch is disabled on them (as in the current spec).
- **Focus changes elsewhere:** if focus changes outside the picker while it's open, dismiss the picker without switching.
- **Input shortcuts in the prototype** (useful for testing): ← → / wheel = turn, Enter = Switch, Esc = Cancel, W = open.

## Files
- `Window Carousel.dc.html` — the interactive prototype. The Background (Glass / None) and Carousel (Flat / Arc) switches are under the stage. Settings: `background`, `layout`, `radius`, `dim`.
- `support.js`, `_ds/…` — the runtime and Modernist stylesheet, needed only to open the prototype.
- `assets/apps/` — sample app icons.
