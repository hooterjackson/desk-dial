# Artwork fixtures (120 px RGB565)

Wire-format covers for the LVGL harness (`harness`) and later tests.
Each `.rgb565` file is 120 x 120 pixels, RGB565 little endian, row major,
exactly 28,800 bytes, the same bytes the companion sends in an `art` upload.
The `.png` files are 120 px previews decoded back from the `.rgb565` bytes.

| File | Source |
|---|---|
| `art-hall-120.rgb565` | Synthetic, calm "hall" cover: a dusk gradient with a low sun and two hill bands (`hall_source()` in `harness/make_art_fixtures.py`). Fictional, like the bright cover: no real album art is published. Passed through `artwork.prepare_artwork()` the same way as the bright cover below. |
| `art-bright-120.rgb565` | Synthetic bright, busy cover: saturated diagonal stripes, a white/colour checker band behind the title area and a white disc. Passed through the companion's own `artwork.prepare_artwork()`, so it has the real 0.8 opacity + black readability scrim, the LANCZOS 240->120 resample and RGB565 LE packing. The scrim was **not** skipped. |

Regenerate with:

```powershell
& 'app\.venv\Scripts\python.exe' '.\harness\make_art_fixtures.py'
```

Output is deterministic for the same companion code. Fixtures are test data
only; they are not shipped to the knob.
