# Smoke-test artwork

`smoke-art-120.rgb565` is the artwork the frozen `--smoke-test` decodes and draws on the LCD
(`standalone.SMOKE_ART`). It is synthetic: a 120 x 120 RGB565 little-endian image (28,800 bytes)
made by `tests/tools/make_smoke_art.py` from arithmetic only (a colour gradient, a light disc and a
dark band). It replaces the real album cover the bundle used to carry (audit finding C12-05).

`assets/fixtures` (the LVGL harness and render tests' covers) is test data and is not packed into
the release bundle: `Build-Desktop.ps1` stages `assets` without it.
