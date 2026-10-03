# Handoff: Nano_D++ — Button grammar, Music explorer, Up next, Window snapping

## Overview
This package is the **current master spec** for the Nano_D++ knob and its Windows companion. It adds:
1. **One Back button** everywhere. Button 1 goes up a level; on Home, where there is no level to go up, it is Play/Pause.
2. **Music explorer.** A full-screen, blurred-desktop cover carousel of Recently Added albums and Favourite playlists.
3. **Up next.** A full-screen vertical track list, opened from Tracks, with Shuffle, Like and Play.
4. **Window snapping.** Snap left and Snap right in the window picker, which build a two-window split.
5. **A consistent icon and button grammar** across all modes.

The knob screen, LED choreography and window picker look follow the earlier specs, which are included in `specs/`. **Where this README disagrees with them, this README wins.**

| Spec | Covers |
|---|---|
| `specs/SCREEN-SPEC.md` | LCD geometry, artwork layer, volume reveal, state model |
| `specs/LED-SPEC.md` | Warm · alive colours, levels, damping, effect recipes (firmware LED task) |
| `specs/WINDOW-CAROUSEL-SPEC.md` | Window picker geometry, motion, title parsing, icons |
| `specs/APP-ICON-SPEC.md` | Companion app and tray icons |

## About the design files
`Browse and Snap.dc.html` is a **design reference built in HTML**: an interactive prototype of the whole flow. It is not production code. To open it, serve the folder over HTTP (`python -m http.server`).

Controls in the prototype:
- **Turn:** ←/→ or the scroll wheel, or drag the knob screen.
- **Buttons:** keys 1–4, or click the button caps.

Rebuild it in the real targets:
- **Firmware** (LVGL + the LED task): knob screen, ring and buttons.
- **Companion** (Python): the full-screen overlays, Windows snapping and artwork fetching.

In the prototype's logic class:
- `renderVals()` holds the LED targets per mode (`ring`, `keys → _btns`).
- `draw()` is a working port of the LED engine from `LED-SPEC.md`.
- The footer and legend arrays list the button map.

## Fidelity
**High-fidelity** for the knob (LCD, ring, buttons) and the overlay layouts and motion. Desktop windows, album tracklists and playlist contents are sample data.

---

## 1. Button grammar (applies to every mode)
| Slot | Rule |
|---|---|
| **1** | **Back**: up one level. On Home: Play/Pause. **Hold 600 ms = Home** from anywhere. |
| **2** | On the knob: **Open on screen** (expand icon). On screen: first of a pair, or a modifier. |
| **3** | On screen: second of a pair, or a modifier. |
| **4** | **The action.** The only green button. |

Each icon has exactly one meaning:
| Icon | Meaning |
|---|---|
| chevron-left | Back |
| expand (four corners) | Open on screen |
| music notes (two beamed) | Browse music |
| list (dots + lines) | Tracks |
| clock | Recently Added |
| list-music | Favourite playlists |
| heart | Like |
| list-plus | Play next |
| scrubber (track line with a ring handle placed right of centre, at ~60 %) | Seek |
| shuffle | Shuffle |
| play / pause | Play, Pause |
| skip / prev | Skip |
| window | Windows |
| rectangle with left / right half filled | Snap left / right |
| check | Switch |

All icons are Lucide-style on a 24 grid: 20 px on the LCD, 2.3 stroke. The Snap icons are a rectangle outline plus a filled half; the paths are in `I` and `HALF` in the prototype.

**Windows opens only from Home.** It was removed from Recently Added and Tracks.

## 2. Button map
| Mode | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Home | Play / Pause | Browse music | Tracks | Windows |
| Recently Added (knob) | Back | Open on screen | **Play next** (inserts the album after the current song, queue kept) | **Play** (replaces queue) |
| Music explorer (screen) | Back | Recently Added | Favourite playlists | **Play** |
| Tracks (knob) | Back (exits Seek first) | Open on screen | **Seek** (toggle) | **Skip** (Prev/Next by position; disabled at Neutral and while seeking) |
| Up next (screen) | Back | Shuffle | Like | **Play** |
| Windows (screen) | Back (restores focus) | Snap left | Snap right | **Switch** |

**Back targets:**
- Recently Added → Home
- Explorer → Recently Added (keeping the same album)
- Tracks → Home
- Up next → Tracks
- Windows → the mode it was opened from (Home)

**Button LEDs:** see `LED-SPEC.md` §3.
| State | Level |
|---|---|
| Nav | warm 0.70 |
| Disabled | 0.14 |
| Pair, active | warm 1.0 |
| Pair, inactive | warm 0.30 |
| Action | green `0,255,98` at 1.0 |
| Liked heart | pink `255,40,90` at 1.0 |
| Snap button, side assigned | that app's colour at 1.0 |

**Paused:** on Home, button 1 breathes green (2.6 s cycle).

## 3. Knob screen (LCD 240 × 240)
Geometry follows `SCREEN-SPEC.md`:
- **Footer:** slot centres x **56, 99, 141, 184**, glyph box y 154–174.
- **Button caps:** 48 × 48, centres 70 px apart. They line up under the four footer slots.

**Scrim change.** Use this darker scrim over the artwork on every art screen. The old one was unreadable on light covers. Add a text shadow of `0 1px 3px rgba(0,0,0,.8)`.
| Distance from top | Black opacity |
|---|---|
| 0 % | 0.60 |
| 45 % | 0.72 |
| 62 % | 0.92 |
| 70 % | solid black |

| Mode | Layout |
|---|---|
| **Home** | Title 22/26, 2 lines, top 60; artist 14/18, top 114; status 12, top 134. **Volume reveal** on the first detent (below). |
| **Recently Added** | Label `RECENTLY ADDED` 12 caps, top 32; title 22/26, top 52; artist 14, top 106; meta `{i} / {n}` 12, top 127. Cover art behind. |
| **Explorer / Up next** (mirrors the screen) | Same list layout. Label `RECENT · SCREEN`, `PLAYLISTS · SCREEN` or `UP NEXT · SCREEN`. Meta `{i} / {n}`, plus ` · playing` on Up next when applicable. |
| **Tracks** | Label `TRACKS`; title top 54 (`Turn to choose` / `Next track` / `Previous track`); position row at top 88 (x 72–168: prev · dot · next, 16 px, selected `#F2F2F2`, others `#7C7C7C`); line top 110 (`Now: …` / `Next: …` / `Prev: …`); meta top 130 (`Press 4 to skip` or `{i} / {n}` plus ` · shuffle`). |
| **Windows** | App icon 32 × 32 at x 104, top 42; app name 14, top 80; window title 16/20, 2 lines, top 100; meta top 139 (`Left: Claude · pick right`). No artwork. |

**Volume reveal on Home:**
- **In:** the track layer exits (150/190 ms ease-in, −8 px, scale 0.98). The volume layer enters 50 ms later with a spring (`cubic-bezier(.34,1.45,.64,1)`, 340 ms).
- **Volume layer:** caption `{title}`, or `Paused · {title}`, at top 52; value at **48 px** (digits) + **22 px** % in `#A6A6A6`, top 76.
- **Out:** the reveal hides 1.4 s after the last detent (value exits in 170 ms, track returns in 420 ms after a 90 ms delay).
- **Status line:** `Minimum` / `Maximum` at the ends.

**Screen change:** content enters from ±16–20 px (380 ms ease-out, opacity 220 ms). Going deeper enters from the right, going back from the left.

## 4. Ring (targets; engine per `LED-SPEC.md`)
| Mode | Pattern |
|---|---|
| Home | Volume arc from segment 35 clockwise, 2 %/segment: bounds L1 0.30, body 0.62, endpoint 1.0. Amber past 80 %, red past 90 %. |
| Recently Added / Explorer | One landmark per item, 3 segments apart and centred on 12 o'clock, in the item's colour at 0.45 (warm items 0.30). Cursor in its colour at 1.0. |
| Up next | Landmarks in each track's album colour. **No other colours.** Played 0.14, now playing 0.70, upcoming 0.45, cursor 1.0. |
| Tracks | Prev 52+53, Neutral 0, Next 7+8, warm 0.30. Selected: 1.0 (Neutral 0.62). |
| Windows | Landmarks in the app colour at 0.45 (monochrome apps warm 0.30). Cursor 1.0. |

**Rule:** a list's ring uses only its items' colours, varied by level. No extra ticks, and no warm markers mixed into a coloured list.

Colours come from the artwork and icons via dominant-colour extraction (`knob-model.js → dominant()`), re-saturated. The prototype hard-codes approximate values in `ALB[].c`, `PL[].c` and `W[].c`.

### Moments specific to this feature
These build on the recipes in `LED-SPEC.md` §7.
| Event | Moment |
|---|---|
| Any turn | Spin trail (tick) / End stop (bound) at list ends and at volume 0 or 100 |
| First input after 5 s of rest | Wake |
| Mode change | Reveal (landmarks unfold from 12 o'clock) |
| Play / Pause on Home | Fill / Drain on the volume arc |
| Skip | Sweep: clockwise for Next, anticlockwise for Previous |
| Play an album or playlist, or Switch a window | Wash in that album's or app's colour |
| **Snap left / right** | **Half-wash**: that half of the ring (segments 31–59 left, 1–29 right) fills with the app colour from its middle outward over 300 ms, holds until 380 ms, then fades over 520 ms. The matching snap button is tinted. |
| **Like** | Bloom in pink `255,40,90` |
| **Shuffle** (Up next, or Shuffle play) | **Scatter**: 9 hot sparks at pseudo-random segments, 55 ms apart, each a 260 ms bump |
| Resting | Breath, time-of-day warm, and the Song hand while playing |
| Explorer / Windows / Up next | Ambient tint of the cursor colour on unlit segments (+0.06) |

---

## 4b. Seek (Tracks, button 3)
- **Enter:** press 3. The knob switches to the fine **BINARIS BEER** profile (67 detents), and each detent moves **5 s** through the song. No new haptic profile is needed.
- **LCD:** `SEEK` label; the song title in 14 px at top 52; the position in **48 px** tabular digits at top 76; `of {duration}` in 14 px at top 128. Footer: Back · Open on screen · Seek (lit warm 1.0) · Skip (disabled).
- **Ring:** the song as one lap from 12 o'clock. Played segments are warm 0.62, and the head is 1.0. Faint 0.30 ticks every 5 segments mark the unplayed part. At rest while playing, the same lap appears as the Song hand.
- **Live seek:** send `Seek(REL_TIME)` to Sonos 250 ms after the last detent. At 0:00 or at the end, the End stop moment plays.
- **Exit:** press 3 again, press Back, open Up next, or wait 3 s without a turn. Each returns to Prev · Now · Next with the Reveal moment.
- Durations in the prototype are sample data.

## 5. Music explorer (companion overlay)
- **Surface:** full-screen, topmost, never takes focus.
  - Backdrop: blur 36 px, saturate 1.3, plus `rgba(8,8,10,.5)`.
  - An **ambient layer** shows the focused cover (or a playlist's first cover), blurred 90 px with saturate 1.5 at 50 %, and crossfades over 600 ms.
- **Tabs** at top 44, centred, 36 px apart: `[2] clock Recently Added` and `[3] list-music Favourite playlists`. Active: white with a 2 px underline that grows over 320 ms. Inactive: 55 % white.
- **Carousel:** centre (640, 318) on the 1280 × 720 reference frame.

  | Distance from centre | Offset X | Scale | Opacity | Dark overlay |
  |---|---|---|---|---|
  | 0 | 0 | 1.00 | 1 | 0 |
  | 1 | ±300 | 0.60 | 0.92 | 0.24 |
  | 2 | ±470 | 0.42 | 0.55 | 0.48 |
  | 3 or more | ±590 / ±660 | 0.30 / 0.22 | 0 | — |

  - **Cards:** square, **340 × 340**. The selected card's shadow is `0 40px 80px rgba(0,0,0,.55)`; a 1 px inset at 12 % white.
  - **Albums** use the cover full-bleed. **Playlists** use a 2 × 2 mosaic of four album covers.
- **Label** at top 514: title 30/36 (600 weight); sub 17 (artist, or "Favourite playlist"); meta 14 (`{year} · {n} tracks` or `{n} songs · {duration}`).
- **Dots** at top 622. **Button hints** at top 664: `[1] Back [2] Recently Added [3] Playlists [4] Play`.
- **Motion:**
  - **Open:** cards rise from +30 px at scale 0.9, staggered by 45 ms × distance, over 440 ms.
  - **Turn:** 420 ms ease-out, with a 14 px bump at the ends.
  - **Source switch:** cards drop out (160 ms), then the new source staggers in. Each source keeps its own position.
  - **Play:** the centre card grows to 1.12 while the others fade. The overlay closes at 380 ms and playback starts.
- **Artwork:** fetch at 600 px and cache it; the knob keeps its 240 px copy.

## 6. Up next (companion overlay)
- **Surface:** same backdrop and ambient treatment as the explorer, driven by the focused track's cover.
- **Left column** (x 120, top 120):
  - **Cover** 380 × 380, with a 40/80 shadow. It crossfades over 420 ms when the focused track's album changes. **For a single album it stays still.**
  - **Below the cover:** `UP NEXT` in 13 caps; the context title at 24/30; the sub line (`artist · year`, or `Favourite playlist · n songs · duration`); the shuffle state, with a shuffle icon plus `Shuffle on` or `In order`.
- **Vertical list** (x 600, width 560, focus centre y 320). Rows are 88 px tall, scaled around their left edge.

  | Distance from focus | Offset Y | Scale | Opacity |
  |---|---|---|---|
  | 0 | 0 | 1.00 | 1 |
  | 1 | ±100 | 0.78 | 0.72 |
  | 2 | ±176 | 0.66 | 0.46 |
  | 3 | ±236 | 0.58 | 0.24 |
  | 4 | ±284 | 0.52 | 0 |

  Played rows are dimmed ×0.6.
  - **Focused row:** 14 % white fill, a 1 px inset at 28 %, and a 20/50 shadow.
  - **Album queue:** each row shows the track number (20 px, tabular), title 22/26 and artist 14.
  - **Playlist queue:** each row shows a 56 × 56 cover, title, and `artist · album`.
  - **Right edge of each row:** a tag in 12 caps (`Now playing` in green `#6ED996`, `Up next`, `Played`), and a pink heart when liked (pops to 1.5×, then settles with a spring).
- **Motion:**
  - **Open:** rows slide in from +40 px, staggered 40 ms.
  - **Turn:** 420 ms ease-out, with a 14 px bump at the ends.
  - **Shuffle:** rows fade out (160 ms), then the reordered list staggers back in.
  - **Play:** the focused row grows to 1.06; the overlay closes at 380 ms.
- **Shuffle** reorders only the tracks after the one now playing. Turning it off restores album order and keeps the current track.
- **Play next** (Recently Added, button 3): the companion calls Sonos `AddURIToQueue` with `EnqueueAsNext`. The knob meta shows `Queued next` for 1.5 s, the toast reads `Queued next · {album}`, and a warm Sweep runs clockwise. In Up next, rows from another album show their own cover and `artist · album`.
- **Like** toggles the track in the user's Favourites (Apple Music library "love" or a favourites playlist). This feeds the explorer's Favourite playlists.

## 7. Window picker changes (see `WINDOW-CAROUSEL-SPEC.md`)
- **Full-screen blur**, replacing the framed glass pane: backdrop blur 40 px, saturate 1.6, plus `rgba(10,10,12,.5)`, and a 6 % top sheen.
- **Card size:** base **400 × 250**, centre (640, 370).

  | Distance from centre | Offset X | Scale | Opacity |
  |---|---|---|---|
  | 0 | 0 | 1.00 | 1 |
  | 1 | ±280 | 0.56 | 0.95 |
  | 2 | ±400 | 0.34 | 0.60 |
  | 3 or more | ±490 / ±540 | 0.26 / 0.20 | 0 |

- **Snap tray:** **hidden until the first snap.**
  - **Reveal:** it drops in from −14 px at scale 0.94 (spring, 460 ms), while the carousel group moves down from −44 px to 0.
  - **Slots:** two, 176 × 110, 14 px apart, at top 104, each labelled `[2] Snap left` / `[3] Snap right`. Empty: dashed outline with the snap icon. Filled: a thumbnail of the window, its app badge, and `Left · {App}`.
  - **Hide again:** when no side is assigned.
- **Snap flow:**
  1. The highlighted window's thumbnail flies from the card to its half of the screen (460 ms ease-out, fading at 380 ms).
  2. The window is placed behind the overlay at 360 ms.
  3. The picker stays open and moves the highlight to the next unassigned window.
  4. Snapping a window that already has the other side moves it.
  5. Once both sides are filled, the picker closes at 820 ms with the toast `Side by side · {A} and {B}`.
  6. Closing with only one side assigned keeps the previously focused window on the other half.
- **Implementation:**
  - Place each window with `SetWindowPos` to the monitor work-area halves (use `GetMonitorInfo`, and `ShowWindow(SW_RESTORE)` first if maximized).
  - Compensate using `DWMWA_EXTENDED_FRAME_BOUNDS` so no gap shows.
  - Windows 11 then treats the pair as a Snap group.
  - A snapped card shows a chip (`◧ Left` / `◨ Right`), and its description gets ` · Snapped left` or ` · Snapped right`.

## 8. Toasts
- **Style:** glass pill at the bottom centre (top 588), springing in and holding 1.8 s.
- **Never shown over an open overlay.** Any toast is cleared when the explorer, Up next or the window picker opens.
- **No toast for Play/Pause.** The knob already shows it.

## Files
- `Browse and Snap.dc.html` — the interactive prototype, with the button map and notes below it.
- `knob-model.js` — shared helpers, including colour extraction. The prototype only loads it; its state machine covers the older flows.
- `specs/*.md` — the earlier specs this builds on.
- `support.js`, `_ds/…`, `assets/…` — needed only to open the prototype. The covers and icons are placeholders.
