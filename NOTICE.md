# Notice and credits

Desk Dial is released under the MIT License (see [LICENSE](LICENSE)), except for
the parts listed below, which keep their own authors and terms.

## Karl Malota (katbinaris)

Desk Dial runs on the **Nano_D++**, a haptic knob designed by **Karl Malota
(katbinaris)**. The hardware is his: <https://github.com/katbinaris/Nano_D_PlusPlus>.
Desk Dial is an independent project built on his work with his permission; it
is not an official Nano_D++ product.

### Knob firmware: NanoD_RatchetH1

The `firmware/` folder is based on Karl Malota's **Nano_D++ / Ratchet_H1
firmware**: <https://github.com/katbinaris/NanoD_RatchetH1>, shipped release
**v1.0.0** (commit `79ca593f228aed353fe5bd427190d19b4d15578d`). It is used and
published here with his permission. The original portions remain his work;
thank you for building a hackable, open haptic knob.

The history shows the boundary: the commit "firmware: import upstream
NanoD_RatchetH1 v1.0.0" is the unmodified upstream tree. The Desk Dial
control-center changes come after it (the `cc_*` sources, the edits to the
threads, audio and haptic code, and the contracts `ALIVE.md`,
`PRESENTATION_V5.md`, `V5_VOCABULARY.md`, `CONTROL_CENTER.md` and friends).
MIT applies to those changes; for the upstream portions, follow the upstream
author's terms.

**The MIT License does not apply to the upstream portions.** The upstream
repository carries no licence file, so no open-source licence has been granted
for them; they are published here with Karl Malota's permission. If you fork
or redistribute this firmware, the upstream portions stay under his terms: ask
him, or check his repository for a licence he may add later. The upstream
bitmap fonts in `firmware/src/fonts/ui_font_*.c` are
part of those portions.

### Adapted from his `feat/firmware-esp-idf-quadra` branch

The following Desk Dial files adapt code, data or design from Karl Malota's
`feat/firmware-esp-idf-quadra` branch of NanoD_RatchetH1 (its `NanoDepsidf/`
ESP-IDF firmware), **with his permission**. He agreed to their publication
here under the MIT License with credit; each file names its source in its
header. The original ideas, artwork and numbers remain his work.

| Desk Dial file (`firmware/src/`) | What it is | Adapted from |
|---|---|---|
| `cc_app_canvas.cpp`, `cc_app_canvas.h` | App canvas timing and animation state: the shape that follows the knob, the command wheel, parameter view, the idle (attract) timer and pacing | `display_task.cpp` |
| `cc_app_ui.h`, `cc_app_screens.cpp` | The app screen (top bar, badge, legend) and the idle plasma rippling out of the app icon, with its colour sampling | `ui_screens.cpp`, `ui_fx.cpp`, `app_colors.c` |
| `cc_app_cards.cpp` | Animated command cards (all 15 element kinds), the command wheel, the parameter screen; Windows keycaps instead of macOS glyphs | `ui_cards.cpp` |
| `cc_app_shape.cpp` | The isometric cube, pyramid and octahedron and their styles | `ui_shape.cpp` |
| `cc_app_gfx.cpp`, `cc_app_gfx.h` | Pixel drawing toolkit (primitives, text, keycaps) drawing into an RGB565 buffer | `ui_gfx.cpp` |
| `cc_app_fonts.cpp` | Silkscreen 8 px and 10 px bitmap fonts, glyphs unchanged (the Silkscreen typeface itself is under the SIL OFL 1.1, see Fonts) | `fonts/ui_font_silkscreen*.cpp` |
| `cc_app_icons.c` | Onshape app icon, 24 px and 48 px pixel art, bytes unchanged | `app_profiles/icons/onshape_*.c` |
| `cc_app_onshape.c` | Onshape's command rings, command names, animated card scenes and parameter visuals (Windows shortcuts) | `app_profiles/onshape.c` |
| `cc_app_profile.h` | Profile display model: scene elements, slots, parameters | `app_profiles/app_profile.h` |
| `cc_app_store.c`, `cc_app_store.h` | App profile model, element set, parameter model, limits and upload state machine | `app_profiles/app_profile.h`, `profile_json.c`, `host_link.c` |
| `cc_app_store_msg.cpp`, `cc_app_store_msg.h` | The app profile upload request | `host_link.c` |
| `audio/cc_sound.h` | Click and thump synthesis: WOOD_TOCK, TICK_THUD, the fine click and the button thump | `i2s_task.c` |
| `cc_haptic_fx.h` | Haptic effect player, pulse shape and effect token table, translated to this firmware's units | `control_task.c`, `haptic_params.h` |

## App profiles: Karl Malota's app profiles and app canvas

Desk Dial's app profiles and the knob's app canvas are adapted, with the author's permission, from **Karl Malota
(katbinaris)**: <https://github.com/katbinaris/NanoD_RatchetH1>, branch `feat/firmware-esp-idf-quadra`, commit
`55e47cbb313416ca678936b51e5c1988ef5590d4`. The original portions remain his work.

- **Profile format:** the app profile JSON, `"format": 1`, and its model (slots, command rings, animated command cards
  described as drawing elements, parameter mode, macros). Desk Dial reads Karl's files unchanged.
  - Desk Dial's own additions are the Windows add-on files (`<id>.windows.json`) and the knob's compact upload format
    (`firmware/APP_PROFILES.md`).
- **The apps' data:** `app/profiles/karl/onshape.json`, `figma.json`, `plasticity.json`, `blender.json` and
  `autocad.json`, exported from his firmware's built-in profiles with his own exporter (`tools/profile_json_test`):
  - the command names, shortcuts and command-card scenes;
  - the parameter definitions;
  - the legends and plasma colours.
- **The app canvas renderer:** `firmware/src/cc_app_*`, adapted from his `ui_cards`, `ui_screens`, `ui_shape`, `ui_fx`,
  `ui_gfx`, `app_colors` and the Silkscreen bitmap fonts. This includes:
  - the command wheel and cards;
  - the cube, pyramid and octahedron shapes and their styles;
  - the parameter screens;
  - the idle plasma and its colour sampling.
- **App icons:** pixel art by Karl Malota (katbinaris), from his Nano_D app profiles. Each profile carries 24 px and
  48 px icons.
- **Input engine:** Desk Dial's Windows input engine (`app/control_center/app_engine.py`) follows the slot, tap,
  command-wheel and parameter semantics of his `app_mode.c`.

The logos depicted in the app icons (Onshape, Figma, Plasticity, Blender, AutoCAD) are trademarks of their respective
owners. They are shown only to identify the app each profile is for. Desk Dial is not affiliated with or endorsed by
them.

The profile exporter is built with cJSON v1.7.18 (MIT, Dave Gamble and cJSON contributors), downloaded at build time
and not included here.

## Fonts (SIL Open Font License 1.1)

| Font | Used in | Licence text |
|---|---|---|
| Archivo (The Archivo Project Authors) | Desk Dial (`app/assets/fonts/Archivo.ttf`) | `app/assets/fonts/OFL-Archivo.txt` |
| Montserrat (The Montserrat.Git Project Authors) | Desk Dial (`app/assets/fonts/Montserrat.ttf`); the knob (`firmware/src/fonts/cc_font_*.c`, rendered from the same Montserrat, and LVGL's built-in Montserrat sizes) | `app/assets/fonts/OFL-Montserrat.txt` |
| Silkscreen (The Silkscreen Project Authors) | The knob's app canvas (`firmware/src/cc_app_fonts.cpp`, via Karl Malota's bitmap conversion) | `firmware/src/fonts/OFL-Silkscreen.txt` |

The fonts are used unchanged or as bitmap renderings, under their original
names. The Desk Dial download carries the Archivo and Montserrat fonts with
their `OFL-*.txt` files beside them (`_internal/assets/fonts/`).

## Knob firmware libraries

PlatformIO downloads these at build time (`firmware/platformio.ini`
`lib_deps`, versions pinned there). They are not included in this repository,
but they are compiled into the knob's firmware image and keep their own
licences:

| Library | Version | Licence |
|---|---|---|
| LVGL | 9.0.0 | MIT (its built-in Montserrat fonts: SIL OFL 1.1) |
| FastLED | 3.6.0 | MIT |
| TFT_eSPI (Bodmer) | 2.5.43 | Mixed: FreeBSD for Bodmer's code, MIT for the parts from Adafruit_ILI9341, BSD for the parts from Adafruit_GFX; its fonts keep their own terms (see its `license.txt`) |
| ArduinoJson | 7.0.2 | MIT |
| Simple FOC (Arduino-FOC) | 2.3.3 | MIT |
| SimpleFOCDrivers | 1.0.7 | MIT |
| Adafruit TinyUSB Library | 3.1.0 | MIT |
| SdFat - Adafruit Fork | 2.3.103 | MIT |
| AceButton | 1.10.1 | MIT |
| MIDI Library (FortySevenEffects) | 5.0.2 | MIT |
| SparkFun STUSB4500 | 1.1.5 | MIT (SparkFun code); SparkFun hardware designs are CC BY-SA 4.0 and are not used here |

The firmware also links the Arduino core for ESP32 2.0.14 (PlatformIO
`espressif32@6.5.0`; LGPL-2.1 for the Arduino core, including Wire, SPI, FS,
LittleFS, SPIFFS and Preferences) and ESP-IDF (Apache-2.0, with its components'
own licences). The complete firmware source is in this repository, so you can
rebuild and relink the image with a modified core (see
[docs/build-firmware.md](docs/build-firmware.md)).

Adafruit SPIFlash (MIT) and Adafruit NeoPixel (LGPL-3.0) are pulled in by
TinyUSB's dependency list but are not compiled into the image.

The vendored `firmware/lib/XTI2S` audio library (XTronical, GNU GPL 3.0 or
later) is part of the upstream tree. It is **not compiled into the release
image**: the v2.0.0 firmware's audio does not use it, and the release build
contains no XTI2S objects. It stays in the tree only as upstream source, under
its own GPL terms.

## Desk Dial (the Windows app)

Desk Dial's Python dependencies (`app/requirements*.txt`) are installed from
PyPI and keep their own licences. The frozen `DeskDial.exe` download bundles
some of them, together with the Python runtime, Tcl/Tk, OpenSSL and the native
libraries inside Pillow and lxml. The download carries
`THIRD-PARTY-NOTICES.md` and a `licenses/` folder with their notices and
licence texts.

| Package | Licence | In the download |
|---|---|---|
| pystray | LGPL-3.0 | Yes (see below) |
| Pillow | MIT-CMU (bundled libraries: see its licence file) | Yes |
| soco | MIT | Yes |
| pyserial | BSD-3-Clause | Yes |
| requests | Apache-2.0 | Yes |
| urllib3 | MIT | Yes |
| idna | BSD-3-Clause | Yes |
| charset-normalizer | MIT | Yes |
| certifi | MPL-2.0 | Yes (unmodified) |
| PyJWT | MIT | Yes |
| cryptography | Apache-2.0 OR BSD-3-Clause | Yes |
| cffi | MIT-0 | Yes (backend module) |
| lxml | BSD-3-Clause (bundled libxml2, libxslt: MIT; iconv: LGPL-2.1; zlib) | Yes |
| websocket-client | Apache-2.0 | Yes |
| ifaddr | MIT | Yes |
| xmltodict | MIT | Yes |
| appdirs | MIT | Yes |
| six | MIT | Yes |
| packaging | Apache-2.0 OR BSD-2-Clause | Yes |
| setuptools | MIT | Yes (pulled in by the freezer) |
| PyInstaller | GPL-2.0-or-later with the PyInstaller bootloader exception | Its bootloader and runtime hooks only |
| pyinstaller-hooks-contrib, altgraph, pefile, pywin32-ctypes, pycparser | Apache-2.0 / GPL-2.0 (hooks), MIT, MIT, BSD-3-Clause, BSD-3-Clause | No (build tools only) |

**PyInstaller** is GPL-2.0-or-later with an exception that allows its
bootloader to be distributed with programs under any licence; Desk Dial ships
only that bootloader and PyInstaller's runtime support, so the GPL does not
extend to Desk Dial.

**pystray** is LGPL-3.0. The download includes it unchanged, frozen into
`DeskDial.exe`; its licence texts (LGPL-3.0 and the GPL-3.0 it builds on) are in
the download's `licenses/pystray/`. You may replace it: Desk Dial's complete
source and build script are in this repository (`app/`,
`app/Build-Desktop.ps1`), so you can install a modified pystray and rebuild the
app, or run Desk Dial from source with it. The same holds for the LGPL-2.1
iconv inside lxml (`_internal/lxml/`).

## Other third-party material

- `app/design-reference/`: design handoffs made for this project. Their sample
  album covers and the app logos in the window-carousel mock-ups belong to
  their respective owners and are used only as test and design fixtures.

## Not affiliated

Desk Dial is a personal project. It is not affiliated with or endorsed by
Apple, Sonos, Home Assistant, Microsoft, Onshape, Figma, Plasticity, Blender or
Autodesk. Apple Music, Sonos, Home Assistant, Windows, Onshape, Figma,
Plasticity, Blender and AutoCAD are trademarks of their respective owners,
used here only to name what Desk Dial works with.
