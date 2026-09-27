# Changelog: master handoff r1 → r2

The file names and structure are unchanged, so r1 and r2 can be diffed directly. Every entry is keyed to engineering's revision request (§ numbers and U numbers).

## Files
| File | Change |
|---|---|
| `README.md` | Rewritten for r2, keeping the same section numbers. |
| `CHANGELOG.md` | New: this file. |
| `specs/01-FEATURES-explorers-snap-seek.md` | Rewritten for r2, with new sections 4c, 4d and 9–12, and appendices A–C. |
| `specs/02…05` | An r2 override block at the top of each, plus in-place fixes to the lines it contradicts. |
| `prototypes/Browse and Snap.dc.html` | Revised (details below). |
| `prototypes/handoff-tables.js` | New: the motion, blur and copy data. |
| `prototypes/assets/`, `icons/` | Unchanged. |

## §1 Fixed decisions (applied as given)
- **Warm** is fixed at `#FFBE69` (the ring emits `#FF8424`). Time of day only dims resting brightness; the 3000 K → 1900 K hue shift is removed from spec 02 §2/§6 and from the prototype.
- **Amber** is `#FF8338` (emits `#FF3A0A`) at 80–90 %. **Red** is `#FF0000` at ≥ 90 % and for failure. Green and blue are unchanged. **Pink** `255,40,90` is marked as a candidate.
- **PC not connected:** the ring drains, then shows amber marks. Input hands the lights to the knob's own profile (prototype state picker → PC connection).
- **Floating knob:** mirrors the physical ring.
- **No main window:** the companion is the tray, the floating knob, the overlays and Settings. Specs 03 and 05 are updated.
- **Favourite playlists:** the favourited playlists, including Favorite Songs. The prototype shows today's 2 items.
- **Up next button 3 = Like.** Play next for this row is documented as the fallback. The copy is reworded: a like is the Favorite star and lands in Favorite Songs.
- **Starting playback:** playlists play what's playable (`Playing 33 of 34`); albums are all-or-nothing.

## §2 32:9 OLED
- **New 01 §11 rule:** scale by height; the blur, tint and ambient cover the full width; content sits in a centred 16:9 stage; the carousels extend on 32:9 tables; Up next stays in the stage.
- **New tables:** 32:9 tables for the explorer (01 §5) and the window picker (01 §7). No visible card goes below 0.40.
- **Prototype:** a 16:9 / 32:9 frame toggle.

## §3 240 Hz motion and rendering
- **Tab underline:** a width animation becomes `scaleX` on a fixed bar. The tab label colour transition becomes an opacity change.
- **Dots:** width animation replaced by fixed dots and a translating 6 × 6 marker.
- **Snap fly:** the left/top/width/height animation becomes translate plus uniform scale of a fixed 400 × 250 live thumbnail.
- **Up next rows:** the per-row background and box-shadow transitions become a fixed focus plate the rows move through.
- **Ambient layers** (explorer and Up next): background transitions become two pre-blurred layers crossfading A↔B, 200 ms after the last detent; the newest wins.
- **Up next big cover:** the background transition becomes a crossfade A↔B, 120 ms after the last detent.
- **Card shadows** (explorer and picker): switching shadows becomes two fixed shadow layers crossfading. The picker's `outline` becomes a separate fading frame layer.
- **Real desktop windows:** their layout transitions are removed. A snapped window moves once, under the overlay, and is revealed when the picker closes (snapshot blur).
- **Window picker:** perspective removed; the Arc study is withdrawn.
- **Labels:** text swaps when a detent lands, then fades in over 160 ms.
- **Stagger:** used only on open and source switch; detents are 420 ms with no stagger (#9).
- **Floating-knob glow:** six fixed looks instead of a continuous glow.
- **Appendix A:** a motion table of tuples. **Appendix B:** a blur recipe per surface.

## §4 Knob screen
- **Scaling removed:** the volume reveal (0.98 / 0.93) and the Windows and idle art (1.06).
- **Screen change:** only the content layer slides, by 20 px (#8). Covers swap instantly.
- **Text shadow:** a hard `0 1px 0` at 80 % over the darker scrim (the `0 1px 3px` blur is gone).
- **Headings:** may reach r 112 (≈ 138 px) at 0.04 em tracking. The mirror labels are shortened to `RECENT`, `FAVOURITES` and `UP NEXT`.
- **Font:** tabular digits and `:` are added to the 48 px face for Seek.
- **Prototype:** a **60 fps preview** toggle quantises LCD transitions to 16.7 ms steps. The LED canvas now always draws at 60 fps.
- **Windows LCD:** title moved to top 98 and meta to top 140, so a 2-line title no longer touches the meta.

## §5 Artwork
- **Sizes:** 1200 px for overlays (600 px floor on old albums), 400 px from Sonos, 240 px on the knob (#6).
- **Designs:** the small-art mat (≤ 1.5× upscale, sharp on a pre-blurred mat of itself), the missing-art placeholder, the loading `bgColor` fill, the loading-list state, and the playlist mosaic rule (first 4 different albums, else one full-bleed cover).

## §6 Service behaviour
- **Play next:** uses the Sonos queue, stacks newest first, is blocked off-queue or under Sonos shuffle, shows `Queueing… k of n`, and has three failure states.
- **Up next:** doesn't open off-queue (the knob explains why). Adds loading, `Sonos queue`, and non-catalog rows (400 px art, no Like).
- **Seek:** only on the Sonos queue with a known length; stops 3 s before the end; `Jumping…` while the time is frozen at the target; a pending target is sent on exit; a song change exits Seek; failure shakes and stays.
- **Like:** a "not known yet" outline heart, and a sign-in-expired recovery.
- **Favourites:** thin (2) and empty states.
- **Starting playback (U11):** the overlay closes at 380 ms, Home shows `Starting…` with the Working comet and Play/Pause disabled, then a wash or a shake.
- **Snap:** the "Snap group" copy is removed; U12 is confirmed and previewed; three failure states.
- **Focus:** the picker takes focus; the explorer and Up next never do.

## §7 Contradictions resolved
1. **Paused Play:** green (U1). The README rule reads "button 4 is green when available; the exception is paused Home Play". The prototype now renders it green.
2. **Amber/red body level:** 0.62, with the odd-volume shoulder at 0.81 (U8). Spec 02 is fixed.
3. **Windows button 1:** warm Back. The red Cancel is removed from specs 02, 03 and 04.
4. **"EnqueueAsNext":** removed. Songs are inserted explicitly after the current song.
5. **"Like feeds Favourite playlists":** corrected. The liked song lands in the *Favorite Songs* playlist; the tab lists favourited playlists.
6. **Art size:** 1200 / 600 / 240 by use.
7. **Seek icon:** the handle is at 65 %, and the path is redrawn to match (`M3 12h8.7M17.7 12H21M14.7 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z`).
8. **Screen-change slide:** 20 px.
9. **Turn:** 420 ms; stagger only on open and source switch.
10. **Up next backdrop:** now its own recipe, tint 0.55 and ambient 0.45 (appendix B).
11. **Toasts over overlays:** removed. Like and Shuffle give knob feedback only; exit toasts appear 360 ms after close.
12. **Toasts:** bottom centre of the foreground window's monitor, held 1.8 s. Spec 04's "centre, 1.5 s" is withdrawn.
13. **Recently Added first entry:** item 1 (the prototype had item 2).
14. **Wake:** reworded. The Wake moment is 520 ms, and segments rise with τ = 10–55 ms.
15. **3 Hz rule:** the Head shake is stated as motion and exempt.
16. **Idle icon row labels:** `Play/Pause · Browse · Tracks · Win`.
17. **Footer dim ink:** `#5A5A5A`.
18. **Hold 1 for Home:** implemented in the prototype; the press acts, and Home follows at 600 ms.
19. **Coloured-list rule:** More is removed (flat list); an unavailable item keeps its colour at 0.45; warm is allowed only for transient moments.
20. **Up next ring over 20 tracks:** a 20-entry window around the focus.
21. **Scatter:** a spread pattern `(seed + ORD[k]·60/9) mod 60`, with `ORD = [0,4,8,3,7,2,6,1,5]`.
22. **Pink:** never re-saturated.

## §8 New designs
- **States:** every §6 pending, failure and unavailable state, in 01 and the state picker.
- **Loading:** explorer and Up next loading states.
- **Favourites:** empty and thin tabs.
- **Artwork:** small and missing art.
- **Off-queue:** Up next during AirPlay (it doesn't open), and Seek unavailable.
- **Snap:** failure states.
- **Overlay lifetime:** lock, sleep and 60 s idle close instantly (01 §9); a *Lock screen now* button in the prototype.
- **Reduced motion:** 01 §10, and a prototype toggle.
- **Settings status strip (U14):** 01 §12, rendered in the prototype and driven by the state picker.
- **Window-picker background (U9):** Frosted / No background is kept as a user setting. **No sheen**, for consistency with the explorer and Up next, and one less large layer at 240 Hz.
- **Tracks lines under shuffle or repeat:** `Next: shuffle pick`, `Prev: last played`, `Next: back to track 1`.
- **Shuffle in Up next (U4):** the companion reorders ≤ 60 upcoming rows; above that, Sonos shuffle with a "Sonos is shuffling the rest" card. A Play next block stays after the current song when shuffle turns off.
- **Recently Added paging (U5):** one flat list with prefetch, no More; the end shows `{n} / {n} · end` with the End stop.
- **Copy sheet:** every knob meta, line, status and heading, plus every toast (01 appendix C), measured live in the prototype.

## r2.1 — wider explorer and artwork fallbacks
- **32:9 explorer:** the carousel now runs off both monitor edges (to distance 8, scale floor 0.40, opacity 0.5 at the edge). Preload is ±12 items on 32:9 and ±6 on 16:9, plus 4 ahead.
- **Low-res art:** the blurred mat is replaced by an **Extended sleeve**: the sharp cover at ≤ 1.5× on a radial gradient of its own dominant colour.
- **No art:** the grey glyph tile is replaced by a **Generated sleeve**: a hashed two-tone gradient with the title set in Archivo 800.
- **Loading art:** `bgColor` plus the title and artist in `textColor1`, then a 240 ms crossfade to the cover.
- **Knob and ring:** lists longer than 20 use the 20-entry ring window. No-art items take the palette accent.
- **Prototype:** the sample library is extended to 24 items by repeating the 9 available covers. The **Artwork → Real library mix** state (now the default) shows sharp, low-res, no-art and still-loading cards together.

- **r2.1 fix:** the prototype's playback clock and Seek had stopped working because of a name clash in the code; both work again.

## r2.2 — follow-up 1 from engineering
Everything else in r2.1 stands.

### 1. Like is add-only
- **Proposal confirmed, with one change.** On a row that's already liked:
  - The heart stays filled pink.
  - Button 3 dims to **pink at 0.30**. This is not the generic 0.14 disabled level, so the button still says "liked" rather than "broken". The footer icon becomes a filled heart in `#A3244A`.
  - A press plays the Head shake and shows `Unfavourite in Music app` for 2.2 s.
  - The on-screen hint reads `[3] Liked`.
- **Copy changed:** the proposed `Unfavourite in the Music app` measures 176 px, which overflows 170; it is shortened to `Unfavourite in Music app` (152 px).
- **Removed:** the unlike moment, `Like removed`, and any heart-off animation.
- **Row hearts, four distinct states:**

  | State | Look |
  |---|---|
  | Liked | filled `#FF285A` |
  | Not liked | outline at 45 % |
  | Not known yet | dashed outline (2.2 / 2.4) at 30 % |
  | Not in Apple Music | outline at 15 % |

- **Save failure:** `Didn’t save · try again`, with a Head shake (prototype: Like state → Save fails).

### 2. Copy approval
All widths were measured in Montserrat 500 in the prototype.
| Proposed | Decision | Width |
|---|---|---|
| `Can’t seek · no length` | Approved | 132 px |
| `Sonos unavailable` | Approved, for the knob meta and the Home status | 110 px |
| `Not available` | Approved | 79 px |
| `Queue changed` | Approved (the shortened form); the order stays as it is | 98 px |
| `Didn’t shuffle · try again` | Approved | 146 px |
| `Nothing to shuffle` | Approved | 111 px |
| `Didn’t save · try again` | Approved | 131 px |
| `Starting…` / `Pausing…` / `Shuffling…` | Approved | 58 / 58 / 64 px |
| `Library not loaded` | Approved | 111 px |
| `Home, then Browse` (14 px) | Approved | 141 px |
| `Sign-in expired` | Approved | 92 px |
| `Group changed` | **Rewritten:** `Speaker group changed`. "Group" alone is ambiguous. | 147 px (≤ 160 for the status line) |
| `Can’t open on screen` | **Rewritten:** `Couldn’t open on screen`, to match the other past-tense failures (`Couldn’t move`, `Couldn’t queue`) | 149 px |
| `… · {u} songs unavailable` | Approved: `Playing {k} of {n} · {u} songs unavailable`, or `1 song` when u = 1 | toast |
| `Nothing recently added` / `Add an album or a playlist to your library in the Music app.` | Approved | overlay |
| `Library not loaded` / `Go Home, then Browse to retry.` | Approved | overlay |
| `Apple Music sign-in expired` / `Open Settings on your PC to sign in again.` | Approved | overlay |
| Idle row slot 1: `Play` / `Pause` | Approved; the label follows the icon | ≤ 46 px |
| `Unfavourite in the Music app` | **Shortened:** `Unfavourite in Music app` | 152 px |

All of these are in the copy sheet (spec 01 appendix C and the prototype's live-measured table).

### 3. Seek timing
- **Confirmed:** the knob holds the frozen target time and `Jumping…` for as long as the jump takes (about 2.7 s, up to about 5 s), **with the Working comet on the ring throughout**.
- **Landed** means playback has resumed, not that a position report has arrived. After 8 s with no resume, go to the failure state.
- **Quick turns:** still one jump, 250 ms after the last detent. Turning during a jump updates the frozen time, and at most one more jump is sent when the current one lands.
- **Prototype:** Seek now takes 2.7 s (Slow: 5 s).

### 4. Play next timing
- **1–10 s is fine.** One refinement: during the lookup phase, before k counts up, the meta shows `Finding songs…` instead of `Queueing… 0 of n`. Then `Queueing… {k} of {n}` at about 0.5 s per song, with the Working comet throughout.
- **Prototype:** cached lookup 0.4 s, uncached 4.5 s, 0.5 s per song.

## Still open (needs the user on real hardware)
- **Final pink** for Like.
- **Paused-Play green:** the user confirms it on the ring (U1).
- **Font check:** confirm the copy-sheet widths once the 48 px tabular font and the Montserrat build are on the device.
