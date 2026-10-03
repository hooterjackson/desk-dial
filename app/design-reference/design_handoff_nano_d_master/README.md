# Nano_D++ — Master handoff for Claude Code

The complete, current design for the **Nano_D++ haptic knob** and its **Windows companion app**. It covers:
- knob screens and button grammar
- LED colours and choreography
- the full-screen **Music explorer** and **Up next** views
- the **window picker** with **Snap left/right**
- **Seek** and **Play next**
- the companion's main window, tray and app icon

**Start here, then read `specs/` in order.** When documents disagree, the **precedence** below wins.

---

## 0. Precedence (newest wins)
1. **This README.**
2. `specs/01-FEATURES-explorers-snap-seek.md`: button grammar, both full-screen explorers, Seek, Play next, snap, toasts, and the knob screen updates.
3. `specs/02-LED-choreography.md`: the "Warm · alive" LED system (firmware LED task).
4. `specs/03-SCREEN-and-state.md`: base LCD geometry, artwork layer, volume reveal, state model, haptic profiles, and the companion's other surfaces.
5. `specs/04-WINDOW-carousel.md`: window picker motion, title parsing, icons. **Superseded:** its framed glass pane (now a full-screen blur) and its 480 × 300 cards (now 400 × 250). See 01 §7.
6. `specs/05-APP-ICON.md`: app and tray icons. Final assets are in `icons/`.

## 1. About the design files
Everything in `prototypes/` is a **design reference built in HTML**. It is not production code. To view it, serve `prototypes/` over HTTP (`python -m http.server`) and open the files below.

| File | What it is | Use it for |
|---|---|---|
| `Browse and Snap.dc.html` | **Primary interactive prototype**: desktop plus knob with the final button grammar, both explorers, snapping, Seek, Play next and the LED engine | Behaviour, layout, motion, button map |
| `Ring Choreography v2.dc.html` | Every LED moment, replayable at ½× and ¼× speed, plus a time-of-day slider | LED effect recipes and timing |
| `Nano_D Control Center.dc.html` | Earlier full design document: states, the companion's main window, settings, tray, recovery states, app-icon exploration | Companion surfaces not redrawn since; history |
| `Window Carousel.dc.html` | The original carousel study (Glass / None, Flat / Arc) | Card treatment reference only |
| `Knob Face.dc.html`, `knob-model.js` | LCD renderer and older state machine | `dominant()` colour extraction and `finishAlive()` LED targets |

Controls in the prototypes: ←/→ or the scroll wheel to turn, 1–4 for the buttons, or click the button caps. You can also drag the knob screen to turn it.

**Build targets** (the existing stack):
- **Firmware** (LVGL, Montserrat, a 60 fps LED task): knob screen, ring, button LEDs.
- **Companion** (Python/Tk tray app): Sonos and Apple Music control, window management, and the full-screen overlays. If Tk can't do the backdrop blur, host just the overlays in a small PySide6 or WebView2 window.
- **Don't change the installed haptic profiles.** Only per-mode bounds and entry positions change.

## 2. Fidelity
**High-fidelity** for the knob (LCD, ring, button LEDs), the overlay layouts, motion and colours. Sample data:
- desktop windows and their thumbnails
- playlist contents
- track durations
- album dominant colours (hard-coded approximations)
- covers and app icons (from Wikipedia/Commons; production uses Apple Music artwork and real Windows icons)

---

## 3. Hardware constraints (unchanged)
- **LCD:** 240 × 240 round, safe radius 104.
- **Ring:** 60 RGB segments. Segment 0 is at 12 o'clock, indices run clockwise.
- **Buttons:** four backlit caps in one row, 48 × 48 on a 70 px pitch.

**Haptic profiles:**
| Mode | Profile | Detents per turn | Notes |
|---|---|---|---|
| Home volume | BINARIS BEER | 67 | 1 % per detent |
| **Seek** | BINARIS BEER | 67 | 5 s per detent |
| Lists: Recently Added, Explorer, Up next, Windows | MIDI SKIPPER | 20 | — |
| Tracks | MIDI CLACK JONES | 8 | Prev · Neutral · Next |

## 4. Button grammar and map (final)
| Slot | Rule |
|---|---|
| **1** | **Back**: up one level. On Home: **Play/Pause**. Hold 600 ms = Home from anywhere. |
| **2** | On the knob: **Open on screen**. On screen: first of a pair, or a modifier. |
| **3** | On screen: second of a pair, or a modifier. On the knob: the mode's secondary action. |
| **4** | **The action.** The only green button. |

| Mode | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| **Home** | Play / Pause | Browse music | Tracks | Windows |
| **Recently Added** (knob) | Back → Home | Open on screen | **Play next** (queue kept) | **Play** (replaces queue) |
| **Music explorer** (screen) | Back → Recently Added | Recently Added | Favourite playlists | **Play** |
| **Tracks** (knob) | Back → Home (exits Seek first) | Open on screen | **Seek** (toggle) | **Skip** (Prev/Next by position; off at Neutral or while seeking) |
| **Up next** (screen) | Back → Tracks | Shuffle | Like | **Play** (jump to track) |
| **Windows** (screen) | Back (restores focus) | Snap left | Snap right | **Switch** |

**Windows opens only from Home.** The old separate Back and Home buttons are merged everywhere.

### Icons (one meaning each; Lucide-style on a 24 grid; LCD 20 px, stroke 2.3)
| Meaning | Icon |
|---|---|
| Back | chevron-left |
| Play / Pause | play / pause |
| Browse music | two beamed music notes |
| Tracks | list (dots + lines) |
| Windows | window (rectangle with a title bar) |
| Open on screen | expand (four corners) |
| Recently Added | clock |
| Favourite playlists | list-music |
| Play next | list-plus |
| Seek | a track line with a ring handle **right of centre (≈ 60 %)** |
| Shuffle | shuffle |
| Like | heart |
| Skip / Previous | skip-forward / skip-back |
| Snap left / right | rectangle with its left / right half filled |
| Switch | check |

The exact paths are in the `I` and `HALF` constants in `Browse and Snap.dc.html`.

**Footer slots:** centres x **56, 99, 141, 184**, glyph box y 154–174. They line up with the four physical caps.

## 5. Knob screen (LCD)
Base geometry and the artwork layer are in 03. Layout per mode is in 01 §3. Key points:
- **Artwork** at 80 % under the **darker scrim**: black at **0.60 / 0.72 / 0.92 / solid** at 0 / 45 / 62 / 70 % from the top. Text shadow `0 1px 3px rgba(0,0,0,.8)`.
- **Home at rest:** track title 22/26 and artist only. **No room name** and no volume number.
- **Volume reveal:** on the first detent the track lifts out and the **48 px** value springs in. It hides 1.4 s after the last detent, once Sonos has confirmed the value.
- **Paused caption:** `Paused · {title}`.
- **Nothing playing, or 4 s after a confirmed pause:** the centred idle icon row replaces the track, and the art fades out (03).
- **Seek:**
  - Label `SEEK`, title 14 px at top 52, **48 px `m:ss`** at top 76, `of m:ss` at top 128.
  - The ring shows the song as one lap from 12 o'clock.
- **Tracks:**
  - Title: `Turn to choose` / `Next track` / `Previous track`.
  - Position row: prev · dot · next.
  - Line: `Now: / Next: / Prev: {title}`.
  - Meta: `Press 4 to skip` or `{i} / {n}`, plus ` · shuffle`.
- **Mirrors of the on-screen views:** `RECENT · SCREEN`, `PLAYLISTS · SCREEN` and `UP NEXT · SCREEN`, each with `{i} / {n}`.
- **Windows:**
  - Layout: 32 px app icon, app name, then window title (2 lines).
  - Meta: `Left: {App} · pick right` while snapping.
  - **No count, and no display or profile details.**
- **Screen change:** content enters from ±20 px (380 ms ease-out). Going deeper comes in from the right, going back from the left.

## 6. LEDs ("Warm · alive"; full recipe in 02)
- **At rest** (5 s without input; never while pending or showing feedback):
  - The ring and buttons settle to a **dim warm** level and breathe on a 5.2 s cycle.
  - The warm colour follows the **time of day**, from about 3000 K at midday to 1900 K at night, and resting brightness drops overnight.
  - While music plays, a faint **Song hand** laps the ring once per song.
- **On touch:** everything rises to **full warm** in about 360 ms, and the first input still acts.
- **Action colours at full saturation:**

  | Colour | RGB | Use |
  |---|---|---|
  | Green | 0,255,98 | Play, Switch, Skip, confirm; a breathing Play button while paused |
  | Red | 255,24,0 | Volume ≥ 90 %, failure |
  | Amber | 255,118,0 | Volume 80–90 %, offline marks |
  | Blue | 40,140,255 | Volume changed elsewhere |
  | Pink | 255,40,90 | Like |
  | App / album | re-saturated dominant colour | Windows, Recently Added, Explorer, Up next |

- **Ring rule:** a list uses **only its items' colours, varied by brightness**. Never add extra marker ticks or mix warm ticks into a coloured list.
  - Up next brightness: played 0.14, now playing 0.70, upcoming 0.45, cursor 1.0.
- **Buttons:**
  | State | Level |
  |---|---|
  | Nav | warm 0.70 |
  | Disabled | 0.14 |
  | Pair, active | warm 1.0 |
  | Pair, inactive | warm 0.30 |
  | Action | green 1.0 |
  | Snap button, side filled | that app's colour |
- **Moments** (02 §7, plus 01 §4):
  | Moment | Event |
  |---|---|
  | Coming online / Going offline | connection changes |
  | Wake | first input after rest |
  | Spin trail | turning faster grows a tail |
  | End stop | turning past a limit |
  | Working comet | waiting on Sonos or Windows |
  | Confirmed / Head shake | success / failure |
  | Play fill / Pause drain | Home transport |
  | Skip sweep | Next or Previous |
  | Changed elsewhere | volume changed from the Sonos app |
  | Near-max embers | volume ≥ 90 % |
  | Mode-change reveal | switching modes |
  | Ambient tint | lists and explorers |
  | Wash | playing an album, switching a window |
  | **Half-wash** | snapping a window |
  | **Pink bloom** | Like |
  | **Scatter** | shuffle |
  | **Sweep** | Play next |
- **Composition:** one foreground moment at a time (a new one fades the old in 120 ms); the base dims 35 % under it; soft-knee tone map; nothing flashes faster than 3 Hz.

## 7. Companion app
### 7.1 Full-screen overlays
All three overlays are topmost, never take focus, and cover the full screen with a blur.

**Music explorer** (01 §5):
- **Background:** blurred desktop plus an ambient layer of the focused cover.
- **Tabs:** `[2] Recently Added` and `[3] Favourite playlists`. Each keeps its own position.
- **Carousel:** a horizontal row of **340 × 340** covers. Albums show their cover full-bleed; playlists show a 2 × 2 mosaic of covers.
- **Label and hints:** title, artist and meta under the centre cover, then dots and the button hints.
- **Motion:** staggered open; 420 ms per detent; the source switch drops cards out, then staggers the new ones in; Play grows the cover and closes the overlay.

**Up next** (01 §6):
- **Layout:** a large 380 px cover on the left, plus a **vertical** list of tracks.
  - **Album:** the cover stays still, and rows show track numbers.
  - **Playlist:** each row has its own 56 px cover, and the large cover crossfades as you move.
  - **Albums added with Play next** show their own cover in each row.
- **Row tags:** Now playing (green), Up next, Played. Liked tracks show a pink heart.
- **Shuffle** reorders only the tracks that haven't played yet. Turning it off restores album order.

**Window picker** (01 §7, plus 04 for motion and title parsing):
- **Background:** full-screen blur.
- **Carousel:** **400 × 250** cards. Only the centre card is labelled, with app, cleaned title and description.
- **Snap tray:**
  - Stays hidden until the first snap, then drops in with a spring.
  - Snapping flies the thumbnail to its half of the screen and places the window with `SetWindowPos` on that half of the monitor's work area, so no gap shows (compensate for the DWM frame).
  - It auto-advances to the next window. When both sides are filled it closes with `Side by side · A and B`.
  - Snapping a window already on the other side moves it.
  - Closing with only one side filled keeps the previous window on the other half.

**Toasts:**
- Glass pill at the bottom centre, 1.8 s.
- **Never shown over an open overlay**, and cleared when one opens.
- **No toast for Play/Pause.**

### 7.2 Main window, settings, tray and recovery (03, and section 04 of the Control Center prototype)
- **Style:** Archivo type, zero corner radius, 2 px rules, neutral dark.
- **Tray icon:** swaps between connected and missing.
- **Tooltip:** `Nano_D++ · Knob connected` or `Knob not found`.
- **Recovery states:** Sonos offline, Apple Music sign-in expired, device missing.

### 7.3 App and tray icons (05; ready-made files in `icons/`)
- **Design:** A3, a dark disc with a white ring fading in over one turn and an **orange `#ff6a1a`** cursor dot.
- **Formats:** `.ico` for the app (16–256 px, with a small drawing at ≤ 24 px) and for the tray (dark or light taskbar × connected or missing).
- **Taskbar theme:** follow `SystemUsesLightTheme` and watch `WM_SETTINGCHANGE` to swap the tray icon live.

## 8. Integration notes (verify before building)
- **Play next:** Sonos `AddURIToQueue` with `EnqueueAsNext=1`, inserting after the current track. **Confirm it works with the Apple Music service on Sonos.**
- **Seek:** Sonos `Seek(Unit=REL_TIME)`, sent 250 ms after the last detent. Exit Seek after 3 s idle, or on 3, Back or Open on screen.
- **Like:** Apple Music API `PUT /v1/me/ratings/songs/{id}` (value 1). This favourites the **song**. **It does not appear in "Favourite playlists"**, which lists favourited *playlists*. Confirm the desktop app can reach this API; if not, replace Like in Up next (candidate: **Play next** for the highlighted track).
- **Favourite playlists source:** the user's favourited or pinned playlists from the Apple Music library.
- **Artwork:** 600 px for the overlays, and 240 px for the knob (RGB565 ≈ 113 KB; cache the current and highlighted covers).
- **Dominant colours:** computed in the desktop app and sent with each list (`dominant()` in `knob-model.js`).
- **Window icons and live previews:** `WM_GETICON`, then the class icon, then the exe or package icon. Live previews use `DwmRegisterThumbnail`; minimized windows use the last captured frame.
- **Time of day:** the desktop app sends local time on connect and every 10 minutes.

## 9. Acceptance checklist
- [ ] Every mode's four buttons, icons and LED levels match §4 and §6. Only button 4 is ever green.
- [ ] Back moves up one level everywhere; holding it goes Home; Windows is reachable only from Home.
- [ ] The Home volume number is hidden at rest and springs in at 48 px on the first detent.
- [ ] Seek: 5 s per detent on the 67-detent profile; the ring laps the song; exits after 3 s idle.
- [ ] Play next inserts the album after the current song; Up next shows those rows with their own covers.
- [ ] Explorer: horizontal square carousel; tabs on 2 and 3 keep their own positions; playlists show a 2 × 2 mosaic.
- [ ] Up next: vertical list; the cover stays still for an album and crossfades for a playlist.
- [ ] Snap: the tray is hidden until the first snap; the thumbnail flies to its half; windows land flush; the picker auto-closes when both sides are filled.
- [ ] LEDs: warm-dim rest with breath; ~360 ms wake; lists use only item colours; one foreground moment at a time; nothing above 3 Hz.
- [ ] No toast over an overlay, and none for Play/Pause.
- [ ] The tray icon follows the taskbar theme and connection state.

## 10. Folder map
```
README.md                ← this file (master)
specs/01…05              ← detailed specs, in precedence order
prototypes/              ← HTML references (serve over HTTP)
  Browse and Snap.dc.html      primary
  Ring Choreography v2.dc.html LED moments
  Nano_D Control Center.dc.html companion surfaces, history
  Window Carousel.dc.html      carousel study
  Knob Face.dc.html, knob-model.js, support.js, _ds/, assets/
icons/                   ← final app and tray icons (svg / png / ico), with their own README
```
