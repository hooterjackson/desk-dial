# Explorer gradient lab (prototype)

A browser prototype of a new background for the full-screen Music explorer. It uses the mesh-gradient shader from [Paper Shaders](https://github.com/paper-design/shaders) (0.0.81, Apache-2.0):
- The colours come from the focused cover.
- They glide to the next cover's colours as the knob turns.
- Each detent nudges the gradient.

The page doesn't touch the app. Nothing in `app/control_center` imports it.

## Open it

Open `index.html` in Chrome or Edge on the 32:9 monitor, then press `F` for full screen. Paper Shaders loads from cdn.jsdelivr.net, so the page needs internet. Without it, or without WebGL2, the page shows a message instead of the gradient. The file has no `<!doctype>` because it is also published as an Artifact, which adds its own; locally it runs in quirks mode, which doesn't affect this layout.

| Key | Acts as |
| --- | --- |
| ← / → or mouse wheel | One knob detent |
| Shift + ← / → | Fast spin (8 detents) |
| `2` | Recently Added ⇄ Playlists (explorer) |
| `3` | Open Up next (explorer) |
| `4` | Play: the visualizer follows the song you play |
| `U` | Album explorer ⇄ Up next |
| `V` | Visualizer now |
| `F` | Full screen |
| `H` | Hide the panel and the fps chip |

## Idle visualizer

The page has two full-screen views, the album explorer and Up next (`U` switches between them), with the gradient behind both.

**Going idle**
- After 5 s with no knob input, the albums or tracks fade away. The outer items go first and the centre last, sinking and blurring as they go.
- The gradient then becomes a full-screen visualizer:
  - it glides to the playing song's colours;
  - it gets brighter;
  - it reacts more strongly to the sound.

**Waking up**
- Any knob input (arrows, wheel, `1`–`4`) brings the view back, centre first.
- By default that first touch only wakes the screen; it doesn't also turn or press. The panel can change this.
- The mouse and the panel never wake it, so you can tune the visualizer while it runs.

**Where the sound comes from**
- **Simulated beat** (default): a beat clock at a set tempo. This is the Sonos case, where the app could know the tempo but has no audio.
- **Song file**: you load a file in the browser tab and it plays there. A real spectrum analyser then drives the gradient.

| Sound | Drives |
| --- | --- |
| Bass | Size pulse and swirl |
| Beats (onsets) | A push forward in the drift |
| Mids | Distortion |
| Highs | Edge grain |
| Overall level | Opens the dim |

The panel tunes the idle time, fade timings, visualizer dim and reactivity (in the visualizer and while browsing), and whether the song's title shows in the visualizer.

## Palette

1. The cover is shrunk to 64 px, the same size today's ambient starts from.
2. Its pixels are grouped into 9 colours by k-means in OKLab, a colour space where distances match what the eye sees. The largest group comes first.
3. Each colour gets its lightness capped (**Lightness cap**, kept low for the OLED) and its saturation scaled (**Saturation**), then is pulled back into sRGB without changing hue.
4. A near-black colour in the main hue is added as slot 0, so the gradient always has some deep black.

The app could also seed this from Apple's artwork `bgColor` and the existing `artwork.dominant_rgb`.

A focus change waits 200 ms (the debounce), then all colours glide to the new palette over 600 ms. These are the same timings as today's crossfade. A fast spin builds nothing until it settles.

## Covers

The covers, songs and titles are made up and drawn in the page. **Use my covers** and **Load a song file** load your own files into that browser tab only. Nothing is uploaded or saved.

**Copy settings** copies the panel's values as JSON, ready to take into the native build.
