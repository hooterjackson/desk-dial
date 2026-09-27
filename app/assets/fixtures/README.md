# Artwork fixtures (120 px RGB565)

Wire-format covers for the LVGL harness (`harness`) and later tests.
Each `.rgb565` file is 120 x 120 pixels, RGB565 little endian, row major,
exactly 28,800 bytes, the same bytes the companion sends in an `art` upload.
The `.png` files are 120 px previews decoded back from the `.rgb565` bytes.

| File | Source |
|---|---|
| `art-den-120.rgb565` | Byte copy of `previews/artwork-transport/den-now-playing-120.rgb565` (a real album cover as the speaker served it; SHA-256 prefix `59e756d3d31b21226f1b272d` = its wire key). |
| `art-bright-120.rgb565` | Synthetic bright, busy cover: saturated diagonal stripes, a white/colour checker band behind the title area and a white disc. Passed through the companion's own `artwork.prepare_artwork()`, so it has the real 0.8 opacity + black readability scrim, the LANCZOS 240->120 resample and RGB565 LE packing. The scrim was **not** skipped. |

Regenerate with:

```powershell
& '.\app\.venv\Scripts\python.exe' '.\harness\make_art_fixtures.py'
```

Output is deterministic for the same companion code. Fixtures are test data
only; they are not shipped to the knob.
