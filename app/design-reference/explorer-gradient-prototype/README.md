# Explorer gradient lab (prototype)

A browser prototype of a new background for the full-screen Music explorer. It uses the mesh-gradient shader from [Paper Shaders](https://github.com/paper-design/shaders) (0.0.81, Apache-2.0):
- The colours come from the focused cover.
- They glide to the next cover's colours as the knob turns.
- Each detent nudges the gradient.

The page doesn't touch the app. Nothing in `app/control_center` imports it.

## Open it

Open `index.html` in Chrome or Edge on the 32:9 monitor, then press `F` for full screen. Paper Shaders loads from cdn.jsdelivr.net, so the page needs internet. Without it, or without WebGL2, the page falls back to Blobs. The file has no `<!doctype>` because it is also published as an Artifact, which adds its own; locally it runs in quirks mode, which doesn't affect this layout.

| Key | Acts as |
| --- | --- |
| ← / → or mouse wheel | One knob detent |
| Shift + ← / → | Fast spin (8 detents) |
| `2` | Recently Added ⇄ Playlists (the planned one-button toggle) |
| `1`, `3`, `4` | Back, Visualizer, Play (only show a message) |
| `M` | Next background mode |
| `F` | Full screen |
| `H` | Hide the panel and the fps chip |

## What to compare

| Mode | What it is | What the native build would need |
| --- | --- | --- |
| Paper shader | The real mesh-gradient shader at full resolution | A pixel shader that runs every frame: an HLSL port on the stage's D3D11 device with a small native render thread, so no Python runs per frame |
| Current | Today's ambient, rebuilt the way the stage builds it (DESKTOP_STAGE §7.5 / §12) | Nothing, it ships today |
| Blobs | Soft colour discs on looping transform animations, colour changes as A/B crossfades, the turn as one group nudge | Only what DirectComposition already does: DWM-run animations, zero per-frame Python, no new code outside the stage |

The fps chip shows frames per second and the 95th-percentile frame time. On the G93SC it should read close to 240 fps and about 4.2 ms. Lower **Render scale** to see how much a lower-resolution shader saves; a soft gradient barely changes at 50 %.

## Palette

1. The cover is shrunk to 64 px, the same size today's ambient starts from.
2. Its pixels are grouped into 9 colours by k-means in OKLab, a colour space where distances match what the eye sees. The largest group comes first.
3. Each colour gets its lightness capped (**Lightness cap**, kept low for the OLED) and its saturation scaled (**Saturation**), then is pulled back into sRGB without changing hue.
4. A near-black colour in the main hue is added as slot 0, so the gradient always has some deep black.

The app could also seed this from Apple's artwork `bgColor` and the existing `artwork.dominant_rgb`.

A focus change waits 200 ms (the debounce), then all colours glide to the new palette over 600 ms. These are the same timings as today's crossfade. A fast spin builds nothing until it settles.

## Covers

The covers and titles are made up and drawn in the page. **Use my covers** loads your own images into that browser tab only. Nothing is uploaded or saved.

**Copy settings** copies the panel's values as JSON, ready to take into the native build.
