# Nano_D++ — Master handoff for Claude Code (revision 2.1)

This is the complete, current design for the **Nano_D++ haptic knob** and its **Windows companion**. Revision 2 designs around engineering's checks against the real knob hardware, the user's Sonos system and Apple Music account, and their **5120 × 1440 · 240 Hz OLED**. **`CHANGELOG.md` lists every change against r1.**

**Start here, then read `specs/` in order.** When documents disagree, the **precedence** below wins.

---

## 0. Precedence (newest wins)
1. **This README.**
2. `specs/01-FEATURES-explorers-snap-seek.md`. Contents:
   - button grammar and availability
   - every knob layout
   - Seek, Play next and starting playback
   - the Music explorer, Up next and the window picker, each with all their states
   - toasts, overlay lifetime and reduced motion
   - the 32:9 rule and the Settings status strip
   - **Appendix A: motion table**, **B: blur recipes**, **C: copy sheet**
3. `specs/02-LED-choreography.md`: the LED system, with **r2 overrides** at the top (tuned colours, fixed warm, floating-knob glow levels).
4. `specs/03-SCREEN-and-state.md`: base LCD geometry, state model and haptic profiles, with r2 overrides.
5. `specs/04-WINDOW-carousel.md`: window title parsing and icon sourcing, with r2 overrides (most of its layout is superseded by 01 §7).
6. `specs/05-APP-ICON.md`: app and tray icons; the final assets are in `icons/`.

## 1. About the design files
Everything in `prototypes/` is a **design reference built in HTML**, not production code. To view it, serve `prototypes/` over HTTP (`python -m http.server`).

| File | What it is |
|---|---|
| **`Browse and Snap.dc.html`** | **Primary prototype (r2).** Desktop and knob with the final grammar, both explorers, snapping, Seek, Play next and the LED engine, plus: a **state picker** that reaches every §6/§8 state, **16:9 / 32:9 frames**, a **60 fps knob-screen preview**, a **reduced-motion** toggle, the motion table, blur recipes, a live-measured copy sheet and the Settings status strip. |
| `handoff-tables.js` | The data behind appendices A–C (motion, blur, copy). |
| `Ring Choreography v2.dc.html` | Every LED moment, replayable. **r1 visuals:** its time-of-day hue slider is withdrawn (spec 02 r2). |
| `Nano_D Control Center.dc.html` | The earlier full design document. **Superseded where it shows a main window**, which no longer exists. |
| `Window Carousel.dc.html` | The original carousel study. **Arc and the framed pane are withdrawn.** |
| `Knob Face.dc.html`, `knob-model.js` | Older LCD renderer and state machine; still the source of `dominant()` colour extraction. |

**Prototype controls:**
- **Turn:** ←/→, the scroll wheel, or drag the knob screen.
- **Buttons:** keys 1–4 or the caps. **Hold 1 for Home.**

**Build targets:**
- **Firmware:** LVGL, Montserrat plus the new 48 px tabular digits and `:`, and the LED task. The LCD runs at **60 fps**; the LEDs at 60 fps, time-based.
- **Companion:** built on DirectComposition. It has the tray icon, the **floating knob**, three full-screen overlays and **Settings**. **No main window.**
- **Don't change the installed haptic profiles.**

## 2. Fidelity
**High-fidelity** for the knob, overlay layouts, motion, colour and copy. Sample data: windows and thumbnails, tracklists, durations, dominant colours, covers and icons.

---

## 3. Hardware constraints
- **LCD:** 240 × 240 round, safe radius 104; headings may reach **r 112**.
  - The data line allows about 87 fps, and the panel is probably 60 Hz or less, so **design for 60 fps**.
  - LVGL has 64 KB of memory, so **no layer scaling**.
  - There is no tearing sync, so **slides are ≤ 20 px**. **Fades last ≥ 120 ms.**
- **Ring:** 60 RGB segments, 0 at 12 o'clock, clockwise. Four backlit caps on a 70 px pitch.
- **Haptic profiles:**

  | Mode | Profile | Detents per turn |
  |---|---|---|
  | Home volume, Seek | BINARIS BEER | 67 |
  | Lists | MIDI SKIPPER | 20 |
  | Tracks | MIDI CLACK JONES | 8 |

## 4. Button grammar and map
| Mode | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| **Home** | Play / Pause (**green while paused**) | Browse music | Tracks | Windows |
| **Recently Added** | Back | Open on screen | **Play next** | **Play** |
| **Music explorer** | Back | Recently Added | Favourite playlists | **Play** |
| **Tracks** | Back (exits Seek first) | Open Up next | **Seek** | **Skip** |
| **Up next** | Back | Shuffle | **Like** | **Play** |
| **Windows** | **Back** (warm) | Snap left | Snap right | **Switch** |

- **Button 1:** Back everywhere; **holding it 600 ms goes Home** (the press still acts).
- **Button 4:** the action. It is green when available. **The one exception to "only button 4 is green" is Home button 1 while paused.**
- **Unavailable buttons:** they dim in place. A press shows the reason on the knob and plays the Head shake (01 §2).

The icon list is in 01 §1. **Seek's handle sits at 65 %.**

## 5. Knob screen
Full detail is in 01 §3; the key points:
- **Content only:** only the content layer slides (±20 px, 380 ms) and fades (220 ms); the cover and footer stay put. **Covers swap instantly.**
- **Volume reveal:** translate and opacity, **no scale**. It hides 1.4 s after the last detent, once Sonos has confirmed.
- **Text shadow:** a hard `0 1px 0` at 80 % over the darker scrim.
- **Mirror labels:** `RECENT`, `FAVOURITES` and `UP NEXT`, 0.04 em tracking, ≤ 138 px.
- **Every meta line and status** is in the copy sheet (01 appendix C), measured ≤ 170 px (status ≤ 160 px).
- **Tracks under shuffle or repeat:** the line reads `Next: shuffle pick`, `Prev: last played` or `Next: back to track 1`.

## 6. LEDs
Full detail is in spec 02 with its r2 overrides:

| Colour | In prototypes (sRGB) | What the ring emits |
|---|---|---|
| Warm | `#FFBE69` | `#FF8424` |
| Amber | `#FF8338` | `#FF3A0A` |
| Red | `#FF0000` | `#FF0000` |

- **Warm is fixed all day**; time of day only dims resting brightness.
- **Amber** at 80–90 %, **red** at ≥ 90 %; failure uses the same red. **Green** `0,255,98` and **blue** `40,140,255` are unchanged.
- **Pink:** `255,40,90` is a candidate, never re-saturated.
- **Levels:** the volume body is 0.62, with an odd-volume shoulder at 0.81.
- **Lists:** they use only their items' colours for marks. Warm is allowed only for transient moments.
- **Up next:** the ring shows a 20-entry window around the focus.
- **PC not connected:** the ring drains, then shows amber waiting marks. **Input hands the lights to the knob's own profile.**
- **Floating knob:** it mirrors the physical ring. Its glow uses **six pre-rendered looks** (0.14 / 0.30 / 0.45 / 0.62 / 0.81 / 1.0).
- **Rate limit:** nothing modulates brightness above 3 Hz; the **Head shake is motion and exempt**.
- **Scatter:** uses the spread pattern in 01 §4.

## 7. Companion
### 7.1 Rendering rules at 240 Hz
- **Allowed motion:** translate, scale, opacity, rectangular clips and **crossfades between two pre-drawn states**. Nothing else animates.
- **Blur:**
  - **One fixed recipe per surface**, taken from a **desktop snapshot at open** (01 appendix B).
  - Blur, saturate and brightness are never animated, and nothing moves behind a blur.
  - The ambient cover layer is **two pre-blurred images crossfading**.
- **Layout:** no width, height, left, top or padding ever animates. That covers the tab underline (`scaleX`), the dots (a translating marker) and the snap fly (uniform scale).
- **Shadows:** fixed images; a shadow change is a crossfade.
- **Colour:** large colour changes are crossfades.
- **Text:** it changes when the motion rests (a detent lands) and fades in.
- **Big areas:** no per-frame effects.
- **Real windows:** they never animate; they move **once, under cover**. Live thumbnails are flat and square and only translate, scale and fade.
- **Image size:** no image shows below about 40 % of its prepared size.
- **Every animation** is listed as a tuple in 01 appendix A.

### 7.2 32:9 and 16:9 (01 §11)
- **Scale by height.** Physical px = units × (screen height ÷ 720), so ×2 here.
- **Full-width:** the blur, tint, ambient and dim cover the whole monitor.
- **Centred 16:9 stage:** everything else. **The explorer and window carousels extend** on their 32:9 tables, with more cards visible and none visible below 0.40. **Up next** stays in the stage.

### 7.3 Surfaces
- **Music explorer** (01 §5): on 32:9 the carousel runs off both monitor edges, with ±12-item preload. Fallback art: an **Extended sleeve** for low-res covers, a **Generated sleeve** for missing art, and `bgColor` with the title for loading art.
  - Details:
  - Tabs `[2] Recently Added` and `[3] Favourite playlists`. The favourites include Apple's **Favorite Songs**; today the tab holds 2 items.
  - A **thin** list and an **empty** state are designed.
  - Art is 1200 px, with **small-art mat**, **missing** and **loading** states.
  - Playlist mosaics use the first 4 different albums; with fewer than 4, one full-bleed cover.
  - Recently Added is one flat list, starting at item 1.
- **Up next** (01 §6):
  - **Opens only while the Sonos queue is playing.** During AirPlay the knob says `Up next is in Music app`.
  - A **fixed focus plate**; states for loading, `Sonos queue` from another app, and non-catalog rows.
  - **Like** writes the Favorite star (verified live), with a "not known yet" state and a sign-in-expired recovery. **Play next for this row** is the documented fallback.
  - **Shuffle:** the companion reorders ≤ 60 upcoming rows; above that, Sonos shuffle with a "Sonos is shuffling the rest" card. A Play next block stays after the current song.
- **Window picker** (01 §7):
  - **Takes focus.** Frosted or No background (user setting), with no sheen.
  - 400 × 250 cards, and a snap tray hidden until the first snap.
  - Snapping flies the live thumbnail with a uniform scale; the real window moves once at 360 ms.
  - **Closing with one side filled:** the window that had focus takes the other half. This is previewed in the empty slot (U12, confirmed).
  - Failure states: not responding, couldn't move, can't fit half. No "Snap group" copy.
- **Toasts** (01 §8):
  - **Never over an open overlay;** exit toasts appear 360 ms after it closes.
  - Bottom centre of the foreground window's monitor, held 1.8 s.
  - No toast for Play/Pause or Back.
- **Overlay lifetime** (01 §9): overlays close instantly on screen lock, sleep or 60 s idle, and the knob returns to the parent mode.
- **Reduced motion** (01 §10): overlays jump with fades; the LCD fades only; travelling LED moments are skipped while colour meaning is kept.
- **Settings** (01 §12): the **status strip** has three columns (Knob, Sonos, Apple Music) with `Set manual IP…` and `Renew sign-in…`.
- **Icons:** unchanged (A3, orange `#ff6a1a`); files in `icons/`.

## 8. Integration notes (as verified by engineering)
- **Play next:**
  - Uses the **Sonos queue**: insert the album's songs **directly after the current song**, keeping the rest, as the Sonos app's own Play Next does. Several Play nexts stack newest first.
  - Only while the Sonos queue is the playing source and Sonos shuffle is off.
  - Look the songs up in Apple Music first (cache it; about 6 s uncached), then insert one at a time, capped at 100.
  - Apple Music's own "Playing Next" isn't reachable from Windows.
- **Seek:**
  - Sonos seek, sent 250 ms after the last detent. It stops 3 s before the end.
  - Expect 0.5–2 s to land. A pending target is sent on exit; a song change exits Seek.
  - Only when Sonos offers seeking and the song length is known.
- **Like:** the Apple Music rating (value 1) gives the song the **Favorite star**; it appears in **Favorite Songs** within about 2 s. Unavailable for non-catalog rows.
- **Favourite playlists:** the user's favourited playlists, including Favorite Songs. Changes take a few minutes; no "pinned" source exists.
- **Starting playback:**
  - Playlists play whatever is playable, and say `Playing 33 of 34`.
  - **Albums are all-or-nothing.**
  - The overlay closes at 380 ms, and the knob shows `Starting…`.
- **Artwork:** Apple Music catalog art at any size up to the original, **1200 px** for overlays; about 5 % of old albums stop at 600 px. Sonos serves 400 px only. The knob gets 240 px RGB565.
- **Dominant colours:** extracted by the companion (`dominant()`) and sent with each list. **Pink is never re-saturated.**
- **Windows:** `SetWindowPos` to the work-area half, with `SW_RESTORE` first and DWM frame compensation. Live previews via `DwmRegisterThumbnail`.
- **Time of day** is sent on connect and every 10 minutes, and **only dims resting brightness**.

## 9. Acceptance checklist
- [ ] Button map, icons and LED levels match §4 and §6. Button 4 is green when available; Home 1 breathes green while paused; nothing else is green.
- [ ] Hold 1 for 600 ms goes Home from anywhere, and the press still acts.
- [ ] Every unavailable button dims in place, and a press shows its reason from the copy sheet with a Head shake.
- [ ] LCD: 60 fps, translate and opacity only, slides ≤ 20 px, fades ≥ 120 ms, covers swap instantly, text changes at rest.
- [ ] Every copy-sheet knob string fits its measured limit with the real font build.
- [ ] Seek stops 3 s before the end, freezes at the target with `Jumping…`, sends a pending target on exit, exits on song change and shakes on failure.
- [ ] Play next shows `Queueing… k of n`, stacks newest first, blocks off-queue and under Sonos shuffle, and shows all three failure states.
- [ ] Starting playback: the overlay closes at 380 ms, Home shows `Starting…` with the comet, then a wash or a shake. Playlists play partly; albums are all-or-nothing.
- [ ] Explorer: 16:9 and 32:9 tables, no visible card below 0.40, the thin and empty favourites, and small, missing and loading art.
- [ ] Up next: doesn't open off-queue; loading, `Sonos queue`, non-catalog, like-unknown and sign-in-expired states; both shuffle regimes.
- [ ] Picker: takes focus; Frosted and No background; snap fly with uniform scale; the real window moves once; the one-side preview; three failure states.
- [ ] 240 Hz rules in §7.1: no blur, shadow, layout or colour animation. Every motion matches 01 appendix A.
- [ ] Toasts never appear over overlays, and there are none for Play/Pause or Back.
- [ ] Overlays close on lock, sleep and 60 s idle. Reduced motion follows §7.3.
- [ ] LEDs: warm is fixed, time of day dims rest only, tuned colours are used, the floating-knob glow has six looks, the offline hand-off works, and Scatter is spread.

## 10. Folder map
```
README.md                ← this file (master, r2)
CHANGELOG.md             ← every change against r1, keyed to engineering's request
specs/01…05              ← detailed specs, in precedence order (01 carries appendices A–C)
prototypes/              ← HTML references (serve over HTTP)
  Browse and Snap.dc.html      primary, r2
  handoff-tables.js            motion, blur and copy data
  Ring Choreography v2.dc.html LED moments (r1 visuals)
  Nano_D Control Center.dc.html history
  Window Carousel.dc.html      carousel study (history)
  Knob Face.dc.html, knob-model.js, support.js, _ds/, assets/
icons/                   ← final app and tray icons (svg / png / ico)
```
