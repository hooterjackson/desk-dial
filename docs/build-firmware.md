# Building the knob firmware

This guide builds the Desk Dial knob firmware v2.0.0 from the `firmware/` folder of this repository. You only need it if you want to change the firmware or check the release image yourself. To put the released firmware on a knob, use the [flashing guide](flashing.md) instead; it does not need a build.

The guide never flashes anything. Writing an image to the knob is covered by the [flashing guide](flashing.md) only.

## What you need

- **Windows 10 or 11.** The release is built on Windows, and the host test harness below is Windows only.
- **Python 3** from [python.org](https://www.python.org/downloads/windows/). The release was built with Python 3.14.
- **PlatformIO Core 6.2.0**, installed with pip (below). The Visual Studio Code extension works too, as long as its Core is 6.2.0.
- **About 2 GB of free disk** for the ESP32 toolchain and the libraries PlatformIO downloads on the first build.

You do not need the Arduino IDE. PlatformIO downloads the right Arduino core for you.

## What the build uses

Everything is pinned in `firmware/platformio.ini`, so a fresh clone builds the same versions as the release image.

| Item | Version |
|---|---|
| PlatformIO environment | `nanofoc_d` (the only one; it is the default) |
| Platform | `espressif32@6.5.0` (Arduino core for the ESP32-S3) |
| Board | `nanofoc_d` (`firmware/boards/nanofoc_d.json`, 4 MB flash, partition table `firmware/boards/nano_partitions.csv`) |
| LVGL | `lvgl/lvgl@9.0.0` |
| FastLED | `fastled/FastLED@3.6.0` |
| AceButton | `bxparks/AceButton@1.10.1` |
| MIDI Library | `fortyseveneffects/MIDI Library@5.0.2` |
| TFT_eSPI | `bodmer/TFT_eSPI@2.5.43` |
| ArduinoJson | `bblanchon/ArduinoJson@7.0.2` |
| Adafruit TinyUSB | `adafruit/Adafruit TinyUSB Library@3.1.0` |
| SdFat (Adafruit fork) | `adafruit/SdFat - Adafruit Fork@2.3.103` |
| Simple FOC | `askuric/Simple FOC@2.3.3` |
| SimpleFOCDrivers | `simplefoc/SimpleFOCDrivers@1.0.7` |
| STUSB4500 | `sparkfun/SparkFun STUSB4500@1.1.5` |
| Wire | from the Arduino core |

Two PlatformIO scripts run before every build:

- `scripts/lvconf_guard.py` adds a hash of `include/lv_conf.h` to every compile command, so that a change to that file recompiles every object.
- `scripts/path_prefix_map.py` keeps your own folder names out of the image. Source file names in the image are relative to their project or framework root.

The firmware version is set in `platformio.ini`: the internal build id `1.0.0-cc5.8` and the public version `2.0.0`. The knob reports both together, for example `2.0.0+cc5.8.F`, where the last letter is the binary (below).

## Install PlatformIO

Open PowerShell in the `firmware` folder and make a virtual environment just for the build:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "platformio==6.2.0"
.\.venv\Scripts\pio.exe --version
```

*You should see* `PlatformIO Core, version 6.2.0`.

The `.venv` folder is ignored by git. The commands below call `.\.venv\Scripts\pio.exe`. If PlatformIO is already on your PATH, plain `pio` works the same.

## Choose the binary: F or D

The release ships one firmware with two build settings. They run the same code and differ only in how often the screen refreshes.

| Binary | Build flags | Screen refresh | Role |
|---|---|---|---|
| **F** | `-DCC_LCD_PERIOD_MS=12 -DCC_BUILD_BINARY=6` | every 12 ms | **Recommended.** The release image and the one on the author's knob. |
| D | `-DCC_BUILD_BINARY=4` | every 16 ms (the source default) | The slower fallback, kept in case F misbehaves on your knob. |

`CC_BUILD_BINARY` only labels the image: it puts the letter into the version the knob reports and into its diagnostics. Without it the knob reports no letter.

You pass the flags through the `PLATFORMIO_BUILD_FLAGS` environment variable. PlatformIO adds them to the `build_flags` in `platformio.ini`. Do not edit `platformio.ini` to switch binaries.

## Build (always clean)

> **Build clean every time.** Delete the previous build before each build, and always after switching between F and D or changing any file under `include/`.
>
> `include/lv_conf.h` (LVGL's configuration) reaches LVGL through a macro, `-DLV_CONF_PATH=...`, which PlatformIO's dependency scan cannot see. During development, an incremental build after an edit to `lv_conf.h` recompiled only part of the sources. The image then mixed two layouts of LVGL's objects. It flashed and verified fine, the motor and buttons worked, but **the screen never drew**: the knob kept its old picture or stayed dark. The `lvconf_guard.py` script now forces a full rebuild when `lv_conf.h` changes, and v2.0.0 detects a mixed image at start-up and shows a red screen with a white "!" instead of drawing nonsense. A clean build still costs only a few minutes, so do not rely on either guard.

From the `firmware` folder, binary F:

```powershell
$env:PLATFORMIO_BUILD_FLAGS = "-DCC_LCD_PERIOD_MS=12 -DCC_BUILD_BINARY=6"
.\.venv\Scripts\pio.exe run -e nanofoc_d -t clean
if (Test-Path .pio\build) { Remove-Item -Recurse -Force .pio\build }
.\.venv\Scripts\pio.exe run -e nanofoc_d
```

For binary D, set the variable to `-DCC_BUILD_BINARY=4` instead and run the same three commands.

The first build downloads the platform, the toolchain and the libraries and takes a while. Later clean builds take a few minutes.

When you are done, clear the variable so it does not leak into other PlatformIO projects in the same window:

```powershell
Remove-Item Env:PLATFORMIO_BUILD_FLAGS
```

*You should see* `SUCCESS` at the end, and a `RAM:` and a `Flash:` usage line just before it.

### The result

The image is `firmware\.pio\build\nanofoc_d\firmware.bin`. It is the app image only, written at `0x10000`. The [flashing guide](flashing.md) uses the release's copy, `desk-dial-firmware-2.0.0-F.bin`; your own build goes in the same place with the same commands.

Check its size:

```powershell
(Get-Item .pio\build\nanofoc_d\firmware.bin).Length
```

**The image must be 1,245,184 bytes or smaller.** The app partition holds 1,310,720 bytes (`0x140000`), and the release keeps a 5 % margin. A larger image is refused by the release tooling; do not flash it.

## Run the host test harness

The `harness/` folder builds the knob's real screen code (LVGL 9.0.0 and the firmware's display sources) as a Windows program. It renders every screen to PNG files and runs the firmware's pure logic (frame parsing, LED rings, sounds, haptic effects, the app canvas, the profile store) as unit tests. No knob, no USB port and no network are used.

### What it needs

- **Visual Studio 2022 Build Tools** in the default install location, with the "Desktop development with C++" workload and its "C++ CMake tools for Windows" component. The scripts call the CMake that ships with the Build Tools and the MSVC toolset 14.44. If your toolset has another version number, change the `MSVC` path near the top of the script you run.
- **One firmware build first.** The harness compiles LVGL from `firmware/.pio/libdeps/nanofoc_d/lvgl`, which PlatformIO downloads on the first build.
- **Desk Dial's Python environment** (`app\.venv`, see [building the app](build-app.md)). Several harness tests check the firmware and the app against the same tables, so they import the app's code and need Pillow.

### Run it

From the repository root:

```powershell
.\app\.venv\Scripts\python.exe .\harness\build.py
```

`build.py` first checks that the shared sources compile as C++11 (the device's language level). It then copies `firmware/include/lv_conf.h` into the harness with one host-only change (no TFT_eSPI display driver), builds with CMake and renders. The PNGs land in `harness\rendered\` (ignored by git).

The other checks are scripts named `*_tests.py` in the same folder, for example:

```powershell
.\app\.venv\Scripts\python.exe .\harness\parse_tests.py
.\app\.venv\Scripts\python.exe .\harness\app_canvas_tests.py
```

Each one exits with a non-zero status on any failure.

### If you write your own host build

Any host build that compiles `src/cc_app_canvas.cpp` must also compile `src/cc_app_store.c`: the app canvas looks up the knob's uploaded app profiles in that store. `harness/app_profiles_e2e_tests.py` lists the full set of units it builds together. Leaving `cc_app_store.c` out fails at link time.

Never keep a hand-edited `lv_conf.h` in the harness. It must match the firmware's copy, or the renders show a configuration the knob does not run.

## The release build

The author's release images go through `tools/build_nanod_cc5.py`. It runs the same PlatformIO build with the same flags and adds checks on top:

- it empties the build folder first;
- it rejects any object the run did not compile;
- it rejects a harness whose `lv_conf.h` differs from the firmware's;
- it enforces the 1,245,184-byte size limit.

The steps above are the same build by hand.

## Licences

The firmware builds on Karl Malota's [NanoD_RatchetH1](https://github.com/katbinaris/NanoD_RatchetH1) firmware. The libraries above are downloaded at build time and keep their own licences. See [NOTICE.md](../NOTICE.md).

## Help

[Troubleshooting](troubleshooting.md) · [open an issue](https://github.com/hooterjackson/desk-dial/issues) · [Karl's Discord](https://discord.gg/mVTvppcfp6).
