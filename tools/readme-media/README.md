# README media pipeline

Everything under `docs/media/` is rendered by this folder, headless, from fictional data. The knob
frames come from the firmware's own LCD code (`cc_display.cpp` and friends on LVGL 9.0.0) built for
the host and driven by a fake tick; the LED ring comes from the app's LED engine (`alive_lights.py`);
the desktop overlays come from the app's own stage renderer and window carousel. No knob, no
speakers, no music account, no screen capture, no network.

## Prerequisites

- Windows, CMake 3.20+ and the Visual Studio 2022 Build Tools with MSVC 14.44 (`build_lcd.py` falls
  back to the CMake bundled with the Build Tools when `cmake` is not on PATH).
- The knob firmware checkout with its PlatformIO dependencies installed: `<firmware>/.pio/libdeps/nanofoc_d/`
  must hold `lvgl` (9.0.0) and `ArduinoJson` (7.0.2). If it does not, run `pio run` once in the
  firmware folder; the pipeline only reads that tree and never edits it.
- The host LCD harness checkout (`lcd-preview`, for `tjpgd_shim/`).
- The companion app's source folder (the one holding `control_center/`) and its virtual environment:
  Python 3.14 with Pillow >= 12 built with WebP. Run every command below with that environment's
  `python.exe`. The pipeline imports the app through `companion.py` with `sys.dont_write_bytecode`
  set, so no `.pyc` lands in the app tree.

## The one command

```
python tools/readme-media/render_all.py ^
    --firmware <knob firmware checkout> --harness <lcd-preview checkout> ^
    --app <companion source folder> --build <scratch build dir> --work <scratch work dir> ^
    --out docs/media
```

Steps, each timed in the log: **build** (`build_lcd.py`: CMake configure of `lcd/CMakeLists.txt`,
then every present target: `knob-anim`, and `app-canvas-anim`, `haptic-trace`, `sound-dump` when
their `.cpp` exists), **scenes** (every entry of `scenes_registry.SCENES`, in order), **manifest**
(`docs/media/manifest.json`), **gates** (page weight, blocklist, and the sizes table rewritten
between `<!-- media-table -->` and `<!-- /media-table -->` in `docs/media/README.md`). A failed gate
exits non-zero after every step has run, so one log shows everything.

Options: `--scenes hero stills` renders a subset; `--skip-build` reuses `--build`; `--no-logo`
builds `app-canvas-anim` with a plain badge instead of the Onshape logo (the public media show the real logo);
`--list` prints the registered scenes. `render_media.py` is a thin alias that forwards to
`render_all.py`.

## Before a push: `--check`

```
python tools/readme-media/render_all.py ... --out docs/media --check
```

Renders into a temporary folder under `--work` (nothing under `--out` is touched), then
`manifest.check` compares it with the committed `docs/media/manifest.json`: files added, removed or
changed (bytes and sha256) and version drift (the firmware, app and pipeline stamps computed now
against the stamps in the manifest). It also weighs the fresh render against the budget and runs
the blocklist. Any difference exits non-zero and prints the diff. With `--scenes`, only the rendered
files are compared; the others are seeded from the committed folder.

## Adding a scene

1. Write `def scene_x(ctx) -> list[Path]` in your own module. `ctx` is a `scenes_registry.Context`:
   `ctx.out` (where to write), `ctx.work` (scratch), `ctx.knob_anim` / `ctx.exe("name")` (the
   headless renderers from `--build`), `ctx.app`, `ctx.firmware`, `ctx.no_logo`. Keep imports inside
   the function so one broken scene does not stop the others.
2. Tag every file you write: `ctx.produced(path, SOURCE)` with one of `manifest.SOURCES`
   (`firmware LCD renderer`, `LED twin (alive_lights.py)`, `app stage renderer`, `app carousel`,
   `firmware app canvas`, `firmware feel laws + knob model`, `firmware sound bank`, `real footage`).
3. Register it in `scenes_registry.py`: `SCENES["x"] = scene_x`. Insertion order is render order.
4. Use only `fixtures.py` data and respect the budget (below). Animated output is a WebP for the
   README's `<picture>` source plus a GIF `<img>` fallback.

## Fictional data and the blocklist

Nothing rendered may show real albums, artists, tracks, app logos, home room names, IPs, MACs or
Windows user paths. `gates.blocklist` scans `README.md`, `docs/` and this folder: the text of every
`.md` / `.json` / `.py`, the metadata of every PNG / WebP / GIF (text chunks, EXIF, XMP, ICC
description; never pixels) and every file name. The terms are `gates.BLOCKLIST`; short words match on
word boundaries, the rest as plain case-sensitive substrings.

The only way around a hit is `gates.ALLOWLIST`: a repo-relative path mapped to the exact terms that
file may contain, each with a reason in the module docstring (for example the FAQ's "Does it work
with Spotify?" question, or Home Assistant's default hostname in setup prose). Media files are never
allowlisted.

## The manifest

`docs/media/manifest.json` (schema 1, documented at the top of `manifest.py`): `generated_at`;
`firmware` {`version` from `NANO_FIRMWARE_VERSION` in `platformio.ini`, `git` HEAD SHA, `dirty`};
`app` {`version` from `filevers` in `desktop-version.txt`, `tree` = sha256 over the sorted
(relative path, sha256) of `control_center/*.py` and `standalone.py`}; `pipeline` {`git` HEAD SHA
of this repo, `tree` = the same hash over `tools/readme-media/**/*.py` and `lcd/*`}; and per file
`name`, `scene`, `source`, `bytes`, `sha256`, `width`, `height`, `frames`, `fps`, `duration_ms`,
`data: "fictional"`. `manifest.py write|check` also works on its own:

```
python tools/readme-media/manifest.py check --media docs/media --firmware <fw> --app <app>
```

## Page-weight budget

A WebP-capable browser downloads, per `<picture>`, only the WebP `<source>`, never the GIF. The
README's weight is therefore the sum of every `<picture>`'s WebP (or its `<img>` when there is no
source) plus every bare `<img>` and Markdown image. `gates.budget` prints a table and fails over:

| class | files | cap |
|---|---|---|
| hero | the hero loop's WebP (stem `hero` or `*-hero`) | 1.0 MB |
| loop | every other animated WebP | 1.2 MB |
| desktop | `desktop-*.webp` full-screen clips | 2.0 MB |
| still | PNG / SVG | 300 KB |
| gif | every GIF fallback (not counted in the total) | 2.9 MB |
| total | the README's WebP-path weight | 12 MB |

`python tools/readme-media/gates.py budget|blocklist|sizes` runs one gate alone.
