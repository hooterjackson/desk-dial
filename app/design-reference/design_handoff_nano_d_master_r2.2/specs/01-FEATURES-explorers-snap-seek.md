# Spec 01 — Button grammar, Music explorer, Up next, Seek, Play next, Window snapping (r2)

Revision 2 designs around engineering's findings on the real knob, the user's Sonos and Apple Music, and the 5120 × 1440 · 240 Hz OLED. Where this file and the README disagree, the README wins. `CHANGELOG.md` lists every change against r1.

## Overview
This spec covers every mode of the knob and the three full-screen overlays of the companion:
- **One Back button.** Button 1 goes up one level everywhere. On Home it is Play/Pause. Holding it for 600 ms goes Home.
- **Music explorer.** A cover carousel of Recently Added albums and Favourite playlists.
- **Up next.** A vertical track list opened from Tracks, with Shuffle, **Like** and Play.
- **Seek** (Tracks, button 3) and **Play next** (Recently Added, button 3), limited to what Sonos can actually do.
- **Window snapping** (Snap left / Snap right) in the window picker.
- **Designed states** for pending, failure, unavailable, loading, empty, small art and missing art, reachable from the prototype's **state picker**.

## About the design files
`prototypes/Browse and Snap.dc.html` is a **design reference in HTML**, not production code. To open it, serve `prototypes/` over HTTP.

Controls in the prototype:
- **Turn:** ←/→, the scroll wheel, or drag the knob screen.
- **Buttons:** keys 1–4, or press the caps. Hold 1 for Home.

Toggles above the stage:
- **Desktop frame:** 16:9 or 32:9.
- **Window picker background:** Frosted or No background.
- **Knob screen:** browser rate, or a **60 fps preview**. The LCD's CSS transitions are then quantised to 16.7 ms steps.
- **Motion:** Full or Reduced.

The page also carries the motion table, the blur recipes, the copy sheet (measured in Montserrat 500) and the Settings status strip. Their data lives in `prototypes/handoff-tables.js` and is reproduced in appendices A–C below.

Rebuild in the real targets:
- **Firmware** (LVGL + the 60 fps LED task): knob screen, ring and button LEDs.
- **Companion:** tray, floating knob, the three overlays (DirectComposition) and Settings.

## Fidelity
**High-fidelity** for layout, colour, motion and copy. Windows, tracklists, durations and dominant colours are sample data.

---

## 1. Button grammar
| Slot | Rule |
|---|---|
| **1** | **Back**: up one level. On Home: **Play/Pause**. **Hold 600 ms = Home** from anywhere: the press acts as normal, and if the button is still held at 600 ms the knob goes Home and closes any overlay. |
| **2** | On the knob: **Open on screen**. On screen: first of a pair, or a modifier. |
| **3** | The mode's secondary action (Play next, Seek), or the second of a pair / modifier on screen. |
| **4** | **The action.** Green when available. |

**Green:** button 4 is green whenever its action is available. **The single exception is Home button 1 while paused**, which breathes green (U1), because resuming is the action there. Every other button is warm or dim.

**Unavailable buttons stay in place**:
- They dim to 0.14 and their icon ink is `#5A5A5A`.
- A press on a dimmed button does not act. It shows the reason on the knob's meta line for 2 s and plays the Head shake. Recently Added's Play next also shows a toast, since no overlay is open there.

### Icons (one meaning each; Lucide-style, 24 grid, LCD 20 px, stroke 2.3)
| Icon | Meaning |
|---|---|
| chevron-left | Back |
| expand (four corners) | Open on screen |
| two beamed music notes | Browse music |
| list (dots + lines) | Tracks |
| clock | Recently Added |
| list-music | Favourite playlists |
| list-plus | Play next |
| **scrubber: track line with a ring handle at 65 %** (`M3 12h8.7M17.7 12H21M14.7 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z`) | Seek |
| heart | Like |
| shuffle | Shuffle |
| play / pause | Play, Pause |
| skip-forward / skip-back | Skip |
| window | Windows |
| rectangle with the left / right half filled | Snap left / right |
| check | Switch |

## 2. Button map
| Mode | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| **Home** | Play / Pause (green while paused) | Browse music | Tracks | Windows |
| **Recently Added** (knob) | Back → Home | Open on screen | **Play next** | **Play** (replaces queue) |
| **Music explorer** (screen) | Back → Recently Added (same album) | Recently Added | Favourite playlists | **Play** |
| **Tracks** (knob) | Back → Home (exits Seek first) | Open Up next | **Seek** | **Skip** (by position; off at Neutral and while seeking) |
| **Up next** (screen) | Back → Tracks | Shuffle | **Like** | **Play** (jump to track) |
| **Windows** (screen) | **Back** (warm), restores focus | Snap left | Snap right | **Switch** |

**Windows opens only from Home.**

### Availability (dims the button, gives a reason on press)
| Button | Available when | Reason on the knob |
|---|---|---|
| Home 1 | Not starting playback | — (ignored while `Starting…`) |
| Recently Added 3 · Play next | The Sonos queue is the playing source, Sonos shuffle is off, and nothing is queueing | `AirPlay · use Play` · `Radio · use Play` · `Line-in · use Play` · `Nothing playing · Play` · `Shuffle on · turn it off` |
| Recently Added 4 · Play | Nothing is queueing or starting | — |
| Tracks 2 · Up next | Sonos queue is playing | `Up next is in Music app` (AirPlay) · `Radio · no Up next` · `Line-in · no Up next` · `Nothing playing` |
| Tracks 3 · Seek | Sonos queue is playing and the song length is known | `Can’t seek · AirPlay` · `Can’t seek · radio` · `Can’t seek · line-in` |
| Up next 3 · Like | Row is an Apple Music catalog song, like states have loaded, and the row is **not already liked** (Like is add-only, r2.2) | `Not an Apple Music song` · `Checking likes…` · `Unfavourite in Music app` |
| Up next 4 · Play | Row is a real song (not loading, not the Sonos-shuffle card) | — |
| Explorer 4 · Play | The list has items and has loaded | — |

**Up next during AirPlay:** we take engineering's proposal. The view does not open, and the knob says `Up next is in Music app`. There is no now-playing-only card, because the knob already shows now playing.

### Button LEDs
| State | Colour · level |
|---|---|
| Nav | warm 0.70 |
| Disabled | warm 0.14 |
| Pair, active | warm 1.0 |
| Pair, inactive | warm 0.30 |
| Action | green `0,255,98` 1.0 |
| Paused Play (Home 1) | green, breathing `0.55 + 0.45·(0.5 + 0.5·cos(2π·t/2600))` |
| Like on a liked row (r2.2) | pink (candidate `255,40,90`) at **0.30**, never re-saturated. The footer icon is a filled heart in `#A3244A`. |
| Snap side assigned | that app's colour 1.0 |
| PC not connected | off (the knob's own profile lights take over on input) |

## 3. Knob screen (LCD 240 × 240, 60 fps)
**Rendering rules (LVGL):**
- **Translate and opacity only.** No scaling of layers.
- **Frame rate:** design for **60 fps**.
- **Slides:** 20 px or less.
- **Fades:** at least 120 ms.
- **Screen change:** only the **content layer** slides and fades. The cover and footer stay still.
- **Covers swap instantly**, never crossfade. They fade only when shown or hidden (entering Windows, the idle view, or PC not connected).
- **Text changes at rest.** When a detent lands, the meta and status lines swap text, then fade in over 160 ms. No counting numbers.

**Scrim and text:**
- **Scrim:** the darker scrim over artwork: black **0.60 / 0.72 / 0.92 / solid** at 0 / 45 / 62 / 70 % from the top.
- **Text shadow:** a **hard 1 px offset**, `0 1px 0` black at 80 % (draw the glyphs twice, offset by one pixel).

**Headings** (top 32):
- **Width:** a heading may reach **r 112** (≈ 138 px wide at that line), set in 12 px caps with **0.04 em** tracking. The bezel hides only r 112–120.
- **Idle icon row, slot 1 (r2.2):** the label follows the icon, `Play` or `Pause`, since `Play/Pause` can’t fit the 46 px column.
- **Mirror labels shortened:** the on-screen mirror labels are **`RECENT`**, **`FAVOURITES`** and **`UP NEXT`**. The `· SCREEN` suffix is dropped.
- **Knob list label:** `RECENTLY ADDED` measures ≈ 118 px, which fits.

**Fonts:** add **tabular digits and a `:` glyph** to the 48 px face (Montserrat 48, digits, `%` and `:`), for Seek's `m:ss` and the volume value.

### Layouts
| Mode | Layout |
|---|---|
| **Home** | Title 22/26, 2 lines, top 60; artist 14/18, top 114; status 12, top 134 (`Starting…`, `Playing 33 of 34`, `Didn’t start`, `Album unavailable`, `Paused`, `Minimum`, `Maximum`). |
| **Recently Added** | Label top 32; title 22/26, top 52; artist 14, top 106; meta 12, top 127: `{i} / {n}`, `96 / 96 · end`, `Queueing… 3 of 9`, `Queued next`, or a failure line. |
| **Explorer / Up next mirror** | Same list layout. Meta `{i} / {n}`, `· playing`, `Loading…`, or `Loading queue…`. Empty favourites: title `No favourites yet`, sub `Star one in Music`. |
| **Tracks** | Label `TRACKS`; title top 54; position row at top 88; line top 110 (`Now: …` / `Next: …` / `Prev: …`); meta top 130. |
| **Seek** | Label `SEEK`; song title 14, top 52; **48 px `m:ss`**, top 76; line 14, top 128: `of 4:47`, `Jumping…`, `Didn’t jump · try again` (`#FF8474`), or `Stops 3 s before end`. |
| **Windows** | App icon 32 × 32 at x 104, top 42; app name 14, top 80; window title 16/20, 2 lines, top 98; meta 12, top 140. |
| **PC not connected** | `Waiting for PC` 22 px at top 70; sub 14 px at top 104: `Open Nano_D++ on your PC`, or `Knob controls still work` after input. No footer, no art. |

### Tracks line under shuffle or repeat
Sonos can't know the next song under its own shuffle.
| Condition | `Next:` | `Prev:` |
|---|---|---|
| Normal | `Next: {title}` / `End of queue` | `Prev: {title}` / `Start of queue` |
| Sonos shuffle on | `Next: shuffle pick` | `Prev: last played` |
| Repeat all, last song | `Next: back to track 1` | as normal |
| Companion shuffle (≤ 60 rows) | the real next title (the order is known) | as normal |

### Volume reveal (Home)
- **In:** the track layer translateY 0 → −8 and opacity 1 → 0 (190 / 150 ms, ease-in). The volume layer translateY +6 → 0 (340 ms, spring, 50 ms delay), opacity 0 → 1 (180 ms, 50 ms delay). **No scale.**
- **Out:** 1.4 s after the last detent, once Sonos has confirmed. The volume layer exits (+6 px, 190 / 170 ms, ease-in); the track layer returns after 90 ms (420 / 320 ms, ease-out).
- **Caption:** `{title}` or `Paused · {title}`. Value in 48 px digits plus a 22 px `%` in `#A6A6A6`.

### Screen change
The content layer moves translateX ±20 → 0 (380 ms, ease-out) with opacity 0 → 1 (220 ms). Going deeper uses +20; going back uses −20.

## 4. Ring
The LED engine is in spec 02. Colours are those tuned on the ring (spec 02 §2).

| Mode | Pattern |
|---|---|
| **Home** | The volume arc runs from segment 35 clockwise, 2 % per segment. Bounds L1 0.30; body **0.62**; endpoint 1.0. **Odd volumes** light the next segment at **0.81** (a half step). Positions ≥ 80 % are **amber**, ≥ 90 % **red** (U8). |
| **Recently Added / Explorer** | One landmark per item, 3 segments apart and centred on 12 o'clock, in the item's colour at 0.45 (items with no colour: warm 0.30). The cursor is at 1.0. **One flat list:** no More item. |
| **Up next** | Landmarks in each track's album colour. Played 0.14, now playing 0.70, upcoming 0.45, cursor 1.0. **Beyond 20 tracks** show a 20-entry window around the focus (focus 10 from the window start, clamped at the ends). While the list is loading, only the Working comet shows. The Sonos-shuffle card has no landmark. |
| **Tracks** | Prev 52+53, Neutral 0, Next 7+8, warm 0.30. Selected 1.0 (Neutral 0.62). |
| **Seek** | The song as one lap from 12 o'clock: played segments warm 0.62, head 1.0, unplayed every 5th segment 0.30. |
| **Windows** | Landmarks in the app colour at 0.45 (monochrome apps warm 0.30). Cursor 1.0. |
| **PC not connected** | Drain, then 12 amber marks (every 5th segment) at 0.12, breathing `0.6 + 0.4·sin(2π·t/2600)`. On input, the knob's own profile lights take over (firmware). |

**List colour rule (U19):** a list's static marks use only its items' colours.
- **Recently Added "More":** removed. The list is one flat list (U5).
- **Unavailable item:** its landmark is omitted, and the cursor on it keeps the item's colour at 0.45.
- **Transient moments:** warm is allowed. The Working comet, pending pulses and sparks are moments, not marks, so they may be warm inside a coloured list.

### Moments used here (recipes in spec 02 §7)
| Event | Moment |
|---|---|
| Turn / past a limit | Spin trail / End stop |
| First input after rest | Wake |
| Mode change | Reveal |
| Home Play / Pause | Fill / Drain |
| Skip | Sweep, clockwise for Next, anticlockwise for Previous |
| Play next queued | Sweep, clockwise from 12 o'clock |
| Start succeeded, window switched | Wash in that album's or app's colour |
| Snap | Half-wash (left half 31–59, right half 1–29) |
| Like | Bloom in pink (not re-saturated) |
| Shuffle | Scatter (spread pattern below) |
| Any failure or blocked press | **Head shake**: motion, not flashing, so it is exempt from the 3 Hz rule |
| Waiting on Sonos, Apple Music or a queue load | **Working** comet, one lap per 1.4 s |
| PC disconnected | **Going offline** drain, then the amber marks |

**Scatter pattern:** 9 sparks at `(seed + ORD[k]·60/9) mod 60`, where `ORD = [0, 4, 8, 3, 7, 2, 6, 1, 5]` and `seed` is uniform in [0, 60). The sparks are 6.67 segments apart, each follows the one before by 1–4 positions around the ring, and they never cluster. Each spark starts 55 ms after the previous one and is a 260 ms bump.

---

## 4b. Seek (Tracks, button 3)
- **Available:** only when the Sonos queue is playing and the song length is known. Radio, streams, line-in and AirPlay dim button 3.
- **Enter:** press 3. The knob switches to the **BINARIS BEER** profile (67 detents); each detent moves **5 s**.
- **Limit:** seeking stops **3 s before the end**, because seeking to the end skips the song. Turning past it plays the End stop and shows `Stops 3 s before end`.
- **Send:** a target is sent **250 ms after the last detent**. The displayed time **stays frozen at the target**.
  - **Measured on the real system (r2.2):** a jump takes about **2.7 s** before Sonos plays again, and Sonos reports the new position before it has finished buffering.
  - **Confirmed:** the knob holds the frozen target and `Jumping…` **for as long as it takes (up to about 5 s)**, and the ring runs the **Working comet** throughout.
  - Treat it as landed only when playback resumes, not when the position report arrives.
  - After 8 s with no resume, go to the failure state.
  - **Turning during a jump** moves the frozen time to the new target. At most one more jump is queued, sent when the current one lands, so quick turns still send one jump per pause.
- **Exit:** press 3 again, press Back, open Up next, or wait 3 s without a turn. **The 3 s idle exit counts from the moment the jump lands** (r2.2); Seek never times out while a jump is waiting or in flight. **A target still waiting to be sent is sent on exit.** If the song changes, Seek exits.
- **Failure:** stay in Seek at the target, play the Head shake, and show `Didn’t jump · try again` for 2.2 s.

## 4c. Play next (Recently Added, button 3)
- **How it works:** the companion uses the **Sonos queue**, exactly like the Sonos app's own Play Next. It inserts the album's songs directly after the current song and keeps the rest. Apple Music's own "Playing Next" isn't reachable from Windows.
- **Stacking:** repeated Play nexts stack **newest first**, directly after the current song.
- **Unavailable:** see §2. The press shows the knob reason plus a toast: `Not playing from the queue · use Play`, `Nothing playing · use Play`, or `Shuffle is on · turn it off to play next`.
- **Progress:**
  - **Lookup first (r2.2):** while the album's songs are looked up in Apple Music (3–6 s uncached, near-instant when pre-loaded), the meta shows `Finding songs…` instead of `Queueing… 0 of n`.
  - The meta then shows `Queueing… {k} of {n}` (about 0.5 s per song, so 1–10 s is expected and fine), and the Working comet runs throughout.
  - Buttons 3 and 4 are dimmed while it runs.
  - The first step is the Apple Music song lookup (about 6 s uncached), then songs insert one at a time.
  - It is capped at 100 songs.
- **Success:** `Queued next` for 1.5 s, the toast `Queued next · {album}`, and a Sweep.
- **Failure:** Head shake, red meta for 2.4 s, and a toast:

  | Case | Knob meta | Toast |
  |---|---|---|
  | Nothing inserted | `Nothing added · retry` | `Couldn’t queue {album} · nothing added` |
  | Stopped partway | `Partly queued` | `Partly queued · check the Sonos queue` |
  | Current song changed during insert | `Song changed · retry` | `Song changed · try again` |

## 4d. Starting playback (explorer, Up next, Recently Added) — U11
1. **Overlay closes:** any open overlay closes at 380 ms.
2. **Knob goes Home straight away:** status `Starting…` and the Working comet. Home Play/Pause is disabled.
3. **Success:** the Wash in the item's colour, then the toast `Playing {name}`.
4. **Playlist with unplayable songs** (region lock, uploaded-only): it still plays. The status shows `Playing 33 of 34` for 3 s, with the toast `Playing 33 of 34 · 1 song unavailable`.
5. **Album with any unplayable song:** nothing is queued (all-or-nothing). Head shake, status `Album unavailable`, toast `{album} can’t play · a song is unavailable`.
6. **Failure:** Head shake, status `Didn’t start`, toast `Couldn’t start {name}`.

---

## 5. Music explorer (companion overlay, never takes focus)
- **Backdrop:** see appendix B. The blur comes from a **snapshot of the desktop at open**.
- **Ambient layer:** **two pre-blurred images crossfading** (A↔B, 600 ms). It follows the focused cover **200 ms after the last detent**; during a fast spin the newest cover wins.
- **Tabs** at top 44, 36 px apart:
  - Active: label at opacity 1 and a fixed 2 px underline at `scaleX(1)`.
  - Inactive: opacity 0.55 and `scaleX(0)`.
  - Both change in 240 / 320 ms.
- **Carousel:** centre (640, 318) in the 16:9 stage; square cards **340 × 340**.

  **16:9 table**
  | Distance | Offset X | Scale | Opacity | Shade |
  |---|---|---|---|---|
  | 0 | 0 | 1.00 | 1 | 0 |
  | 1 | ±300 | 0.60 | 0.92 | 0.24 |
  | 2 | ±470 | 0.42 | 0.55 | 0.48 |
  | 3 / 4 | ±590 / ±660 | 0.30 / 0.22 | 0 | — |

  **32:9 table** (the row runs **off both edges of the monitor**; no visible card below 0.40)
  | Distance | Offset X | Scale | Opacity | Shade |
  |---|---|---|---|---|
  | 0 | 0 | 1.00 | 1 | 0 |
  | 1 | ±300 | 0.60 | 0.92 | 0.24 |
  | 2 | ±500 | 0.46 | 0.84 | 0.34 |
  | 3 | ±680 | 0.42 | 0.76 | 0.42 |
  | 4 | ±850 | 0.40 | 0.68 | 0.48 |
  | 5 | ±1010 | 0.40 | 0.60 | 0.52 |
  | 6 | ±1170 | 0.40 | 0.54 | 0.55 |
  | 7 | ±1330 | 0.40 | 0.50 | 0.58 |
  | 8 | ±1490 | 0.40 | 0 | — |

  - The monitor edge is at ±1280 units, so distance 7 is cut by the edge and distance 8 is fully off-screen.
  - Opacity stays high all the way out, so the library reads as continuing past the bezel instead of fading into a vignette.
  - The overlay clips at the monitor edge. Cards enter and leave by translating past it, and are never scaled below 0.40.
  - **Preload:** ±12 items around the focus on 32:9 and ±6 on 16:9, at display size, plus 4 more in the direction of travel. Decode ahead of display so a fast spin shows loading tiles, never blank cards.

- **Card shadows:** each card has two fixed shadow layers, side `0 16px 36px /0.4` and focus `0 40px 80px /0.55`. They **crossfade** over 320 ms as a card enters or leaves the centre.
- **Label** at top 514 (title 30/36, sub 17, meta 14). It changes **when the detent lands** and fades in over 160 ms.
- **Position marker:**
  - Fixed 6 × 6 dots at 40 %, 14 px pitch.
  - One solid 6 × 6 square at full opacity **translates** to the focused dot (420 ms).
  - No width animation.
- **Stagger:** only on **open** and **source switch**, 45 ms × distance. Detents are 420 ms with no stagger.
- **Play:** the centre card scales to 1.12, the others fade out, and the overlay closes at 380 ms (§4d).

### Artwork (explorer, Up next, knob)
| Use | Fetch | Notes |
|---|---|---|
| Explorer centre card | **1200 px** (Apple Music catalog, any size up to the original) | Shown at 680 px on the 1440 p monitor, 1020 px on 4K at 200 % |
| Up next big cover | **1200 px** for catalog songs, otherwise Sonos **400 px** | Shown at 760 px (1140 px on 4K) |
| Up next rows, knob LCD | 400 px rows · **240 px** knob (RGB565) | Knob caches current + highlighted |
| Ambient layers | the same image, pre-blurred once | — |

- **Low-res art · Extended sleeve:** never upscale more than **1.5×**.
  - Show the cover **sharp at 1.5× its native size**, centred on the card, with a fixed shadow `0 18px 40px /0.4` and a 1 px inset at 14 % white.
  - Fill the rest of the square with a **radial gradient built from the album's own dominant colour**: 95 % at the centre (50 % / 38 %), 50 % at 52 %, 20 % at the corners. The cover appears to glow out into its own colour.
  - The gradient is pre-rendered once per album (no blur needed).
  - Examples: 400 px on a 680 px card → 88 % (inset 6 %); 300 px → 66 % (inset 17 %); a 400 px Sonos cover on the 760 px Up next frame → 79 % (inset 11 %).
- **No art · Generated sleeve:**
  - A designed typographic cover: a 160° linear gradient between two tones picked by hashing *artist + title* into an 8-entry muted palette. The palette is in the prototype as `GEN` and uses the companion's dark neutrals.
  - The title is set flush left in Archivo 800 at 34/37 (4 lines at most), with the artist at 16 px (80 %), a 2 px rule and a two-note glyph at the foot, in the palette's ink.
  - It is stable per album, so the same album always gets the same sleeve.
  - The ring uses the palette's accent. The ambient layer and the knob LCD use the gradient.
- **Loading art:**
  - A solid fill in Apple's artwork `bgColor`, with the title (17 px 600) and artist (13 px) bottom-left in Apple's `textColor1`. The card is already identifiable, and the real cover **crossfades in** over 240 ms when decoded.
  - There is no shimmer or per-frame effect.
  - On the knob, the LCD shows `bgColor` under the scrim.
- **Loading list:** neutral `#232325` cards. The label, dots and marker are hidden, the knob shows `Loading…`, and the ring runs only the Working comet.
- **Playlists without their own art:**
  - With at least 4 different albums: a 2 × 2 mosaic of the **first 4 different album covers**.
  - With fewer: **one full-bleed cover** (the first album).
  - Example: Favorite Songs → mosaic; PAPER LANTERN Ep. 1 → single cover.

### Explorer empty and error states (r2.2)
All of these use the empty-state layout (glyph, 28/34 title, 16/22 help text at 80 %). Button 4 is dimmed.
| State | Title | Help | Knob |
|---|---|---|---|
| Recently Added empty | `Nothing recently added` | `Add an album or a playlist to your library in the Music app.` | `No items` |
| Library failed to load | `Library not loaded` | `Go Home, then Browse to retry.` | title `Library not loaded`, sub `Home, then Browse` |
| Sign-in expired, nothing cached (either tab) | `Apple Music sign-in expired` | `Open Settings on your PC to sign in again.` | `Sign-in expired` |
| Sonos down | the list shows normally | — | Play dimmed, `Sonos unavailable` |

### Favourite playlists tab
- **Contents:** the playlists the user has favourited (starred), including Apple's automatic **Favorite Songs**. Today that is **2 items: Favorite Songs and PAPER LANTERN Ep. 1**.
- **Thin list (1–3 items):**
  - The focus stays centred, with no padding or fake items; dots show the true count.
  - The first item is centred with neighbours on the right only. That's deliberate: it keeps the detent-to-card mapping identical to long lists.
- **Empty:**
  - Title `No favourite playlists yet` (28/34), with help text `Star a playlist in the Music app. It appears here within a few minutes.` (16/22, 80 %) and a list-music glyph at 60 %.
  - Button 4 is dimmed. The knob shows `No favourites yet` / `Star one in Music`.
- **Sub line:** Favorite Songs shows `Favourite playlist · made by Apple Music`.
- **Sync:** changes take a few minutes to appear. There is no "pinned" playlists source.

### Recently Added paging (U5)
- **One flat list** with prefetch around the focus. There is no More item.
- **End of the list:** the End stop plays, and the meta reads `{n} / {n} · end`.
- **First highlighted entry:** item 1 (newest) (U13).

## 6. Up next (companion overlay, never takes focus)
- **Opens only while the Sonos queue is playing** (§2).
- **Backdrop:** see appendix B. The ambient follows the big cover (A↔B, 600 ms).
- **Left column** (x 120, top 120): the **big cover** is 380 units, with its fixed shadow on the frame.
  - **Album:** the cover stays still, and rows show track numbers.
  - **Playlist or queue from another app:** the cover crossfades A↔B (420 ms) to the focused track, **120 ms after the last detent**; the newest wins.
- **Focus plate:**
  - A **fixed** plate on the focus line (x 600, y 276, 560 × 88), with 14 % white fill, a 1 px inset at 28 % and the 20/50 shadow.
  - The rows move through it; no row animates its background or shadow.
- **Rows:** use the translateY / scale / opacity table (16:9 and 32:9 alike; see §11).
- **Row stagger:** 40 ms × distance, only on **open** and after a **shuffle**.
- **Loading** (long queues load around the focus):
  - The now-playing row is known.
  - Other rows are placeholders: a 56 px block at 10 % plus two bars at 14 % / 10 %.
  - The knob shows `Loading queue…`; Shuffle, Like and Play are dimmed; the ring runs only the Working comet.
- **Queue started from another controller:** the title is **`Sonos queue`**, the sub `Started in another app · {n} songs`, and every row shows its own cover.
- **Rows that aren't Apple Music catalog songs** (local files, other services):
  - Their sub line ends `· not in Apple Music`.
  - They have no heart; Like is dimmed.
  - Only 400 px art is available, so the big cover uses the small-art mat.
- **Like (button 3) — add-only (r2.2):**
  - One press gives the song the Apple Music **Favorite star**. It appears in the **Favorite Songs** playlist within about 2 s (Apple can take a few minutes to sync that playlist into the tab).
  - The heart pops (0.4 → 1.5 → 1, spring 380 ms), the ring plays a pink Bloom, and the knob meta reads `Liked`.
  - **Third-party apps can't remove a favourite** (Apple Support 111118, verified live), so **there is no unlike and no "heart turns off" moment**.
  - **On a row that's already liked:**
    - The row's heart stays filled pink.
    - Button 3 dims to **pink at 0.30** (not the generic 0.14, so the button still reads as "liked"), with the footer icon filled in `#A3244A`.
    - A press plays the Head shake and shows `Unfavourite in Music app` for 2.2 s.
    - The on-screen hint reads `[3] Liked`.
  - **Save failed** (rate limit or server error): Head shake and `Didn’t save · try again` in red.
  - **No toast** while the overlay is open.
- **Row heart states** (20 px, right edge of each row):

  | State | Look |
  |---|---|
  | Liked | filled `#FF285A` |
  | Not liked | outline, 1.8 stroke, white at 45 % |
  | Not known yet | **dashed** outline (2.2 / 2.4), white at 30 % |
  | Not an Apple Music song | outline at 15 %; no Like |
- **Heart not known yet:**
  - Just after the list opens, rows show the **dashed outline** until like states load.
  - The knob Like button is dimmed, with the meta `Checking likes…`.
- **Sign-in expired:**
  - Head shake and the meta `Sign-in expired`.
  - After the overlay closes, the toast `Apple Music sign-in expired · open Settings`.
  - The Settings status strip shows Apple Music: **Sign-in expired · Renew sign-in…** (§12).
- **Documented fallback:** if the ratings API becomes unavailable, button 3 becomes **Play next for this row**, which inserts the focused song after the current one.

### Shuffle (button 2) — U4
We take engineering's recommendation:
| Upcoming rows | Shuffle on | What Up next shows |
|---|---|---|
| **≤ 60** | The **companion reorders** the upcoming rows in the Sonos queue (Sonos shuffle stays off) | The new order. Rows fade out (160 ms), then re-enter with the open stagger. The ring plays Scatter. The knob shows `Shuffle on`. |
| **> 60** | **Sonos's own shuffle** | Played rows, the now-playing row, then one **card row**: `Sonos is shuffling the rest` / `{n} songs · order isn’t shown`. The card can't be played or liked, and the knob shows `Sonos is shuffling`. |

- **Shuffle off:** the upcoming rows return to album or playlist order. **A Play next block stays directly after the current song.**
- **Knob feedback:** `Shuffle off · in order`.
- **Other Sonos apps:** they see the reordered queue with shuffle off. That is expected.

## 7. Window picker (companion overlay, takes focus)
- **Focus:** the picker **takes focus**, because Switch and Back need it. The explorer and Up next never do.
- **Background** (U9): keep the user's setting.
  - **Frosted** (default): desktop snapshot, blur 40, saturate 1.6, tint 0.50.
  - **No background:** a flat 55 % black dim, with a `0 1px 2px /0.6` text shadow on the labels.
  - **No top sheen** in either.
- **Cards:** 400 × 250 at centre (640, 370) in the 16:9 stage.

  **16:9 table**
  | Distance | Offset X | Scale | Opacity |
  |---|---|---|---|
  | 0 | 0 | 1.00 | 1 |
  | 1 | ±280 | 0.56 | 0.95 |
  | 2 | ±400 | 0.34 | 0.60 |
  | 3 / 4 | ±490 / ±540 | 0.26 / 0.20 | 0 |

  **32:9 table**
  | Distance | Offset X | Scale | Opacity |
  |---|---|---|---|
  | 0 | 0 | 1.00 | 1 |
  | 1 | ±280 | 0.56 | 0.95 |
  | 2 | ±420 | 0.42 | 0.70 |
  | 3 | ±545 | 0.40 | 0.45 |
  | 4 | ±665 | 0.40 | 0.25 |
  | 5 | ±780 | 0.40 | 0 |

- **Live thumbnails** stay flat and square and only translate, scale and fade: **no perspective, rotation or rounded corners.** The r1 "Arc" study is withdrawn.
- **Selection:** a separate 2 px square frame, 8 px outside the centre card, fading 320 ms. The two fixed shadows crossfade.
- **Label:** changes when the detent lands, then fades in over 160 ms.
- **Position marker:** the same translating square as in the explorer.

### Snap
- **Snap tray:** hidden until the first snap, or the first snap failure.
  - **Reveal:** translateY −14 → 0 and scale 0.94 → 1 (spring 460 ms, opacity 260 ms). The carousel group moves translateY −44 → 0.
- **Fly:**
  - The highlighted card's **live thumbnail** (fixed 400 × 250 layer) **translates and uniformly scales** from the card to the centre of its half: `k = min(halfW / 400, 672 / 250)`, 460 ms ease-out, fading out 380 → 600 ms.
  - Nothing animates width or height.
- **The real window moves once, at 360 ms, under the overlay** (`SetWindowPos` to the monitor work-area half; `SW_RESTORE` first if maximized; compensate with `DWMWA_EXTENDED_FRAME_BOUNDS`).
  - Because the blur is a snapshot, the moved window is seen when the picker closes.
- **After a snap:** the highlight advances to the next unassigned window. Snapping a window that already holds the other side moves it.
- **Both sides filled:** the picker closes at 820 ms, and afterwards shows the toast `Side by side · {A} and {B}`.
- **Copy:** don't promise a Windows "Snap group"; Windows may or may not form one.
- **Closing with one side filled (U12, confirmed):**
  - The window that had focus when the picker opened takes the other half.
  - While only one side is filled, the empty slot previews this: that window's thumbnail at 35 %, labelled `Right · keeps {App}` (or Left).
  - After Back: the toast `{A} left · {B} right`.
- **Failures:** the slot shows a red outline, `1px rgba(255,132,116,.9)`, and a red label for 2.4 s. Nothing moves, and the knob plays the Head shake with a short meta.

  | Case | Slot label | Knob meta |
  |---|---|---|
  | Hung | `{App} isn’t responding` | `{App} not responding` |
  | Move rejected | `Couldn’t move {App}` | `Couldn’t move {App}` |
  | Minimum size exceeds half | `{App} can’t fit half` | `{App} can’t fit half` |

## 8. Toasts
- **Style:** glass pill, bottom centre of the **monitor showing the foreground window**, top 588 in the 720 stage, held **1.8 s**.
- **Never shown over an open overlay.** Toasts caused by closing an overlay appear **360 ms after it closes**. Toasts raised while an overlay is open are dropped; the knob meta carries that feedback instead (Like, Shuffle, snap failures).
- **No toast** for Play/Pause, or for Back.

## 9. Overlay lifetime
- **Close instantly, with no toast,** on **screen lock**, **sleep**, the session going to the lock screen, or **60 s without knob input**.
- **Where the knob goes:** it returns to the overlay's parent mode (explorer → Recently Added, Up next → Tracks, picker → Home).
- **Picker:** focus is restored. A window already snapped stays where it was placed.
- **PC disconnected:** every overlay closes and the knob shows `Waiting for PC`.
- The prototype's **Lock screen now** button simulates this.

## 10. Reduced motion
Follow the Windows *Animation effects* setting, or the companion's own Motion setting.
- **Overlays:**
  - Cards and rows **jump** to their positions, with opacity fades only (200 ms).
  - No end-stop bumps, no fly, no stagger, no tray spring; the tray simply fades.
  - Crossfades stay.
- **Knob LCD:** no slides. Content only fades (220 ms); the volume reveal is opacity only.
- **LEDs:**
  - Wake, Spin trail, Sweep, Scatter and Reveal are skipped.
  - The Head shake becomes a stationary red throb.
  - Colour meaning is kept: Wash, Half-wash, Bloom, Fill/Drain and the Working comet stay.

## 11. 32:9 layout rule
- **Scale by height.** The layout is authored on a 720-unit-high stage; physical px = units × (screen height ÷ 720), so ×2 on the 1440 p monitor.
- **Full-width surfaces:** the snapshot blur, tint, ambient layer and No-background dim always cover the whole monitor.
- **The 16:9 stage:** everything else is laid out in a **centred 1280 × 720 stage**: tabs, labels, dots, hints, the Up next column and list, the snap tray and the toast.
- **Carousels:** the explorer and window carousels **extend beyond the stage** on the 32:9 tables (§5, §7). More cards are visible on the same pitch, and no visible card goes below 40 % of its prepared size.
- **Up next** doesn't extend, because its content is a vertical list. On 32:9 the frosted desktop and ambient fill the sides.
- **Snap halves** are halves of the monitor's work area: 2560 px each on the user's screen.

## 12. Settings status strip (U14)
**There is no main window.** The companion is the tray icon, the floating knob, the three overlays and a **Settings** window. The strip at the top of Settings is where recovery lives:

| Column | OK state | Problem state | Action |
|---|---|---|---|
| **Knob** | `Connected` · `Nano_D++ · USB · firmware {v}` | `Not connected` · `Waiting for Nano_D++ on USB. The knob’s own controls still work.` | `Knob settings…` / `Troubleshoot…` |
| **Sonos** | `{Room}` · source and IP (`Playing from the Sonos queue · 192.168.1.40`) | `Not found` · `Can’t reach Sonos on this network` | **`Set manual IP…`** |
| **Apple Music** | `Signed in` · `Library and likes available` | `Sign-in expired` · `Like and Favourite playlists are paused until you sign in again.` | **`Renew sign-in…`** (a primary light button when expired) |

- **Status marks:** a square 8 px mark per column: `#6ED996` OK, `#FF7A66` problem.
- **Style:** companion dark palette (spec 03, companion tokens), 2 px rule under the strip.
- **Tray:** the tray menu's "Open Settings…" jumps to the strip.

---

## Appendix A — Motion table
Curves: **OUT** `cubic-bezier(0.22,1,0.36,1)` · **IN** `cubic-bezier(0.4,0,1,1)` · **SPR** `cubic-bezier(0.34,1.45,0.64,1)` (a fixed-duration spring with overshoot). Delay is after the trigger. Desktop surfaces use translate, scale, opacity and crossfades only. The knob LCD uses translate and opacity at 60 fps.

| Surface | Element | Property | From | To | ms | Delay | Curve | Trigger |
|---|---|---|---|---|---|---|---|---|
| Explorer | Overlay root | opacity | 0 | 1 | 340 | 0 | OUT | Open (reverse on close: 1→0, 340, OUT) |
| Explorer | Card (enter) | translateY · scale | +30 · ×0.9 | 0 · table | 440 | 45 × distance | OUT | Open, source switch (only times a stagger is used) |
| Explorer | Card (enter) | opacity | 0 | table | 320 | 45 × distance | OUT | Open, source switch |
| Explorer | Card (exit) | translateY · scale · opacity | 0 · table · table | +30 · ×0.9 · 0 | 170 | 0 | IN | Source switch; new source enters at 190 ms |
| Explorer | Card (turn) | translateX · scale | table(d) | table(d∓1) | 420 | 0 | OUT | Each detent; retarget mid-flight, never queue |
| Explorer | Card (turn) | opacity | table(d) | table(d∓1) | 300 | 0 | OUT | Each detent |
| Explorer | Card shade (#0B0B0C) | opacity | table(d) | table(d∓1) | 320 | 0 | OUT | Each detent |
| Explorer | Card shadow | crossfade | side shadow | focus shadow | 320 | 0 | OUT | Card enters or leaves the centre |
| Explorer | Row (end stop) | translateX | 0 | ∓14 → 0 | 160 | 0 | OUT | Turn past either end |
| Explorer | Tab underline | scaleX | 0 | 1 | 320 | 0 | OUT | Button 2 / 3; fixed 2 px bar, square ends |
| Explorer | Tab label | opacity | 0.55 | 1 | 240 | 0 | OUT | Button 2 / 3 |
| Explorer | Position marker | translateX | i × 14 | (i±1) × 14 | 420 | 0 | OUT | Each detent; fixed 6 × 6 square over fixed dots |
| Explorer | Label (title/sub/meta) | opacity | 0 | 1 | 160 | 0 | OUT | Text swaps when the detent lands, then fades in |
| Explorer | Ambient layer | crossfade A↔B | previous cover | focused cover | 600 | 200 ms | OUT | 200 ms after the last detent; newest wins in a fast spin |
| Explorer | Centre card (play) | scale | 1 | 1.12 | 380 | 0 | OUT | Button 4; other cards opacity → 0, 300 ms; overlay closes at 380 |
| Up next | Overlay root | opacity | 0 | 1 | 340 | 0 | OUT | Open / close |
| Up next | Left column | translateY · opacity | +20 · 0 | 0 · 1 | 460 | 0 | OUT | Open (opacity 320 ms) |
| Up next | Row (enter) | translateX · opacity | +40 · 0 | 0 · table | 420 | 40 × distance | OUT | Open, after shuffle (opacity 300 ms) |
| Up next | Row (turn) | translateY · scale | table(d) | table(d∓1) | 420 | 0 | OUT | Each detent |
| Up next | Row (turn) | opacity | table(d) | table(d∓1) | 300 | 0 | OUT | Each detent |
| Up next | Focus plate | — | static | static | — | 0 | — | Fixed at the focus line; rows move through it |
| Up next | Big cover | crossfade A↔B | previous | focused track cover | 420 | 120 ms | OUT | Playlists only, 120 ms after the last detent; newest wins |
| Up next | Ambient layer | crossfade A↔B | previous | focused track cover | 600 | 200 ms | OUT | Same trigger as the explorer |
| Up next | Heart | scale | 0.4 | 1.5 → 1 | 380 | 0 | SPR | Like lands (opacity 0→1, 200 ms) |
| Up next | Rows (shuffle) | opacity | table | 0 | 160 | 0 | IN | Button 2; reordered rows re-enter with the open stagger |
| Up next | Row (end stop) | translateY | 0 | ∓14 → 0 | 160 | 0 | OUT | Turn past either end |
| Windows | Overlay root | opacity | 0 | 1 | 280 | 0 | OUT | Open / close |
| Windows | Card (enter) | translateY · scale · opacity | +24 · ×0.92 · 0 | 0 · table · table | 420 | 0 | OUT | Open |
| Windows | Card (turn) | translateX · scale | table(d) | table(d∓1) | 420 | 0 | OUT | Each detent |
| Windows | Card (turn) | opacity | table(d) | table(d∓1) | 300 | 0 | OUT | Each detent |
| Windows | Selection frame | opacity | 0 | 1 | 320 | 0 | OUT | Card enters the centre (2 px square frame, separate layer) |
| Windows | Card shadow | crossfade | side shadow | focus shadow | 320 | 0 | OUT | Card enters or leaves the centre |
| Windows | Snap tray | translateY · scale | −14 · 0.94 | 0 · 1 | 460 | 0 | SPR | First snap (opacity 260 ms OUT) |
| Windows | Carousel group | translateY | −44 | 0 | 460 | 0 | OUT | First snap |
| Windows | Slot fill | opacity | 0 | 1 | 260 | 0 | OUT | Snap lands |
| Windows | Snap thumbnail (fly) | translate · uniform scale | card centre · 1 | half centre · half ÷ card width | 460 | 0 | OUT | Snap; live thumbnail only, flat and square |
| Windows | Snap thumbnail (fly) | opacity | 1 | 0 | 220 | 380 ms | OUT | Snap |
| Windows | Real window | SetWindowPos (no animation) | current rect | half of work area | — | 360 ms | — | Once, under the overlay |
| Windows | Position marker | translateX | i × 14 | (i±1) × 14 | 420 | 0 | OUT | Each detent |
| Windows | Label | opacity | 0 | 1 | 160 | 0 | OUT | Detent lands |
| Toast | Pill | translateY · opacity | +8 · 0 | 0 · 1 | 260 | 0 | OUT | Shown only after overlays close |
| Toast | Pill | scale | 0.96 | 1 | 420 | 0 | SPR | Show |
| Toast | Pill (exit) | opacity | 1 | 0 | 200 | 1800 ms | IN | Hold 1.8 s |
| Knob LCD | Content layer (screen change) | translateX | ±20 | 0 | 380 | 0 | OUT | Mode change: + going deeper, − going back; cover and footer stay |
| Knob LCD | Content layer (screen change) | opacity | 0 | 1 | 220 | 0 | OUT | Mode change |
| Knob LCD | Track layer (reveal out) | translateY · opacity | 0 · 1 | −8 · 0 | 190 | 0 | IN | First volume detent (opacity 150 ms) |
| Knob LCD | Volume layer (reveal in) | translateY | +6 | 0 | 340 | 50 ms | SPR | First volume detent |
| Knob LCD | Volume layer (reveal in) | opacity | 0 | 1 | 180 | 50 ms | OUT | First volume detent |
| Knob LCD | Volume layer (hide) | translateY · opacity | 0 · 1 | +6 · 0 | 190 | 0 | IN | 1.4 s after the last detent and Sonos confirmed (opacity 170 ms) |
| Knob LCD | Track layer (return) | translateY · opacity | −8 · 0 | 0 · 1 | 420 | 90 ms | OUT | After hide (opacity 320 ms) |
| Knob LCD | Cover | swap | previous | new | — | 0 | — | Instant, never crossfaded |
| Knob LCD | Cover (show/hide) | opacity | 0 / 0.8 | 0.8 / 0 | 240 | 0 | OUT | Entering / leaving Windows or the idle view |
| Knob LCD | Footer icon ink | crossfade | old tone | new tone | 160 | 0 | OUT | Button state changes |
| Knob LCD | Meta / status line | opacity | 0 | 1 | 160 | 0 | OUT | Text swaps at rest, then fades in |
| Knob LCD | Seek digits | — | — | — | — | 0 | — | Redraw when a detent lands; no counting |

## Appendix B — Blur recipes
Radii are at the 720-unit reference; multiply by screen height ÷ 720. Every recipe is fixed per surface and never animated.

| Surface | Source | Radius | Saturate | Tint | Ambient layer | Sheen / extras |
|---|---|---|---|---|---|---|
| Music explorer | Desktop snapshot at open | 36 px | 1.3 | `rgba(8,8,10,0.50)` | Focused cover, pre-blurred 90 px, saturate 1.5, opacity 0.50, 160 px bleed; crossfade A↔B 600 ms | None |
| Up next | Desktop snapshot at open | 36 px | 1.3 | `rgba(8,8,10,0.55)` | Focused track cover, pre-blurred 90 px, saturate 1.5, opacity 0.45, 160 px bleed; crossfade A↔B 600 ms | None |
| Window picker · Frosted (default) | Desktop snapshot at open | 40 px | 1.6 | `rgba(10,10,12,0.50)` | None | None (the 6 % sheen is dropped) |
| Window picker · No background | — | — | — | `rgba(0,0,0,0.55) flat` | None | None; labels get the text shadow 0 1px 2px / 0.6 |
| Toast | Desktop snapshot at show | 24 px | 1 | `rgba(24,24,26,0.62) + 1 px rgba(255,255,255,0.2)` | None | None |
| Small-art mat | The cover itself | 24 px (pre-rendered) | 1 | `rgba(0,0,0,0.35)` | — | Sharp cover centred at ≤ 1.5× native, 1 px inset rgba(255,255,255,0.12) |

## Appendix C — Copy sheet
Knob widths are measured in Montserrat 500:
- **Meta lines:** 12 px, ≤ 170 px.
- **Knob lines** (14 px, Tracks and Seek): ≤ 170 px.
- **Home status:** 12 px, ≤ 160 px.
- **Headings:** 12 px caps at 0.04 em, ≤ 138 px.

The prototype measures them live. Values below are approximate character counts; re-check with the real font build. Toasts and overlay copy have no knob limit.

| Surface | Context | Text | Limit | Chars |
|---|---|---|---|---|
| Knob heading | Recently Added list | `RECENTLY ADDED` | ≤ 138 px | 14 |
| Knob heading | Explorer mirror · Recently Added | `RECENT` | ≤ 138 px | 6 |
| Knob heading | Explorer mirror · Favourite playlists | `FAVOURITES` | ≤ 138 px | 10 |
| Knob heading | Up next mirror | `UP NEXT` | ≤ 138 px | 7 |
| Knob heading | Tracks | `TRACKS` | ≤ 138 px | 6 |
| Knob heading | Seek | `SEEK` | ≤ 138 px | 4 |
| Knob meta | List position | `12 / 96` | ≤ 170 px | 7 |
| Knob meta | End of Recently Added | `96 / 96 · end` | ≤ 170 px | 13 |
| Knob meta | Play next · progress | `Queueing… 3 of 9` | ≤ 170 px | 16 |
| Knob meta | Play next · success (1.5 s) | `Queued next` | ≤ 170 px | 11 |
| Knob meta | Play next · failed | `Nothing added · retry` | ≤ 170 px | 21 |
| Knob meta | Play next · partial | `Partly queued` | ≤ 170 px | 13 |
| Knob meta | Play next · song changed | `Song changed · retry` | ≤ 170 px | 20 |
| Knob meta | Play next · AirPlay | `AirPlay · use Play` | ≤ 170 px | 18 |
| Knob meta | Play next · radio | `Radio · use Play` | ≤ 170 px | 16 |
| Knob meta | Play next · line-in / TV | `Line-in · use Play` | ≤ 170 px | 18 |
| Knob meta | Play next · nothing playing | `Nothing playing · Play` | ≤ 170 px | 22 |
| Knob meta | Play next · Sonos shuffle on | `Shuffle on · turn it off` | ≤ 170 px | 24 |
| Knob meta | Explorer loading | `Loading…` | ≤ 170 px | 8 |
| Knob meta | Favourites empty | `No favourites yet` | ≤ 170 px | 17 |
| Knob meta | Tracks | `Press 4 to skip` | ≤ 170 px | 15 |
| Knob meta | Tracks · shuffle | `4 / 12 · shuffle` | ≤ 170 px | 16 |
| Knob meta | Up next · AirPlay | `Up next is in Music app` | ≤ 170 px | 23 |
| Knob meta | Up next · radio | `Radio · no Up next` | ≤ 170 px | 18 |
| Knob meta | Seek · radio | `Can’t seek · radio` | ≤ 170 px | 18 |
| Knob meta | Seek · AirPlay | `Can’t seek · AirPlay` | ≤ 170 px | 20 |
| Knob meta | Up next position | `5 / 12 · playing` | ≤ 170 px | 16 |
| Knob meta | Up next · loading | `Loading queue…` | ≤ 170 px | 14 |
| Knob meta | Like · on | `Liked` | ≤ 170 px | 5 |
| Knob meta | Like · already liked (add-only, r2.2) | `Unfavourite in Music app` | ≤ 170 px | 24 |
| Knob meta | Like · save failed | `Didn’t save · try again` | ≤ 170 px | 23 |
| Knob meta | Seek · unknown or over-long length | `Can’t seek · no length` | ≤ 170 px | 22 |
| Knob meta | Explorer · Sonos down (Play dimmed) | `Sonos unavailable` | ≤ 170 px | 17 |
| Knob meta | Unplayable list item | `Not available` | ≤ 170 px | 13 |
| Knob meta | Shuffle off refused · queue changed | `Queue changed` | ≤ 170 px | 13 |
| Knob meta | Shuffle failed | `Didn’t shuffle · try again` | ≤ 170 px | 26 |
| Knob meta | Shuffle · < 2 upcoming | `Nothing to shuffle` | ≤ 170 px | 18 |
| Knob meta | Busy · start running | `Starting…` | ≤ 170 px | 9 |
| Knob meta | Busy · pause running | `Pausing…` | ≤ 170 px | 8 |
| Knob meta | Busy · shuffle running | `Shuffling…` | ≤ 170 px | 10 |
| Knob meta | Play next · song lookup (before k counts) | `Finding songs…` | ≤ 170 px | 14 |
| Knob meta | Apple Music library failed | `Library not loaded` | ≤ 170 px | 18 |
| Knob meta | Sonos group changed during an action | `Speaker group changed` | ≤ 170 px | 21 |
| Knob meta | PC refused to open an overlay | `Couldn’t open on screen` | ≤ 170 px | 23 |
| Knob line 14 px | Retry hint under Library not loaded | `Home, then Browse` | ≤ 170 px | 17 |
| Knob meta | Like · state unknown | `Checking likes…` | ≤ 170 px | 15 |
| Knob meta | Like · non-catalog row | `Not an Apple Music song` | ≤ 170 px | 23 |
| Knob meta | Like · sign-in expired | `Sign-in expired` | ≤ 170 px | 15 |
| Knob meta | Shuffle · companion | `Shuffle on` | ≤ 170 px | 10 |
| Knob meta | Shuffle · off | `Shuffle off · in order` | ≤ 170 px | 22 |
| Knob meta | Shuffle · Sonos (> 60 left) | `Sonos is shuffling` | ≤ 170 px | 18 |
| Knob meta | Windows · one side | `Left: Claude · pick right` | ≤ 170 px | 25 |
| Knob meta | Snap · hung | `Slack not responding` | ≤ 170 px | 20 |
| Knob meta | Snap · move failed | `Couldn’t move Slack` | ≤ 170 px | 19 |
| Knob meta | Snap · too big | `Slack can’t fit half` | ≤ 170 px | 20 |
| Knob line 14 px | Tracks · now (long titles end in …) | `Now: Tick of the Clock` | ≤ 170 px | 22 |
| Knob line 14 px | Tracks · Sonos shuffle, next unknown | `Next: shuffle pick` | ≤ 170 px | 18 |
| Knob line 14 px | Tracks · shuffle, previous | `Prev: last played` | ≤ 170 px | 17 |
| Knob line 14 px | Tracks · repeat all, last track | `Next: back to track 1` | ≤ 170 px | 21 |
| Knob line 14 px | Seek · length | `of 4:47` | ≤ 170 px | 7 |
| Knob line 14 px | Seek · waiting for Sonos | `Jumping…` | ≤ 170 px | 8 |
| Knob line 14 px | Seek · failed | `Didn’t jump · try again` | ≤ 170 px | 23 |
| Knob line 14 px | Seek · limit | `Stops 3 s before end` | ≤ 170 px | 20 |
| Knob status 12 px | Home · starting | `Starting…` | ≤ 160 px | 9 |
| Knob status 12 px | Home · playlist partly playable (3 s) | `Playing 33 of 34` | ≤ 160 px | 16 |
| Knob status 12 px | Home · start failed | `Didn’t start` | ≤ 160 px | 12 |
| Knob status 12 px | Home · album blocked | `Album unavailable` | ≤ 160 px | 17 |
| Knob status 12 px | Home | `Paused` | ≤ 160 px | 6 |
| Knob status 12 px | Home · Sonos down | `Sonos unavailable` | ≤ 160 px | 17 |
| Knob status 12 px | Home · group changed | `Speaker group changed` | ≤ 160 px | 21 |
| Knob title 22 px | PC not connected | `Waiting for PC` | ≤ 170 px | 14 |
| Toast | Play next · success | `Queued next · Midnight Arcade` | — | 25 |
| Toast | Play next · AirPlay / radio / line-in | `Not playing from the queue · use Play` | — | 37 |
| Toast | Play next · nothing playing | `Nothing playing · use Play` | — | 26 |
| Toast | Play next · Sonos shuffle | `Shuffle is on · turn it off to play next` | — | 40 |
| Toast | Play next · failed | `Couldn’t queue Midnight Arcade · nothing added` | — | 42 |
| Toast | Play next · partial | `Partly queued · check the Sonos queue` | — | 37 |
| Toast | Play next · song changed | `Song changed · try again` | — | 24 |
| Toast | Start · success (after overlay closes) | `Playing PAPER LANTERN Ep. 1` | — | 26 |
| Toast | Start · partly playable | `Playing 33 of 34 · 1 song unavailable` | — | 37 |
| Toast | Start · partly playable (plural) | `Playing 31 of 34 · 3 songs unavailable` | — | 38 |
| Toast | Start · album blocked | `Tidal Glass can’t play · a song is unavailable` | — | 47 |
| Toast | Start · failed | `Couldn’t start PAPER LANTERN Ep. 1` | — | 33 |
| Toast | Switch | `Claude · Nano D Control Center` | — | 30 |
| Toast | Snap · both sides | `Side by side · Claude and Slack` | — | 31 |
| Toast | Snap · one side, closed | `Claude left · Chrome right` | — | 26 |
| Toast | Like · sign-in expired (after close) | `Apple Music sign-in expired · open Settings` | — | 43 |
| Overlay | Favourites empty · title | `No favourite playlists yet` | — | 26 |
| Overlay | Favourites empty · help | `Star a playlist in the Music app. It appears here within a few minutes.` | — | 71 |
| Overlay | Recently Added empty · title | `Nothing recently added` | — | 22 |
| Overlay | Recently Added empty · help | `Add an album or a playlist to your library in the Music app.` | — | 60 |
| Overlay | Library error · title | `Library not loaded` | — | 18 |
| Overlay | Library error · help | `Go Home, then Browse to retry.` | — | 30 |
| Overlay | Sign-in expired, nothing cached · title | `Apple Music sign-in expired` | — | 27 |
| Overlay | Sign-in expired, nothing cached · help | `Open Settings on your PC to sign in again.` | — | 42 |
| Knob idle row | Slot 1 label (follows the icon, 46 px column) | `Play` | ≤ 46 px | 4 |
| Knob idle row | Slot 1 label while playing | `Pause` | ≤ 46 px | 5 |
| Overlay | Up next · queue from another app | `Sonos queue` | — | 11 |
| Overlay | Up next · Sonos shuffle card | `Sonos is shuffling the rest · order isn’t shown` | — | 47 |
| Overlay | Snap slot · one side preview | `Right · keeps Chrome` | — | 20 |
