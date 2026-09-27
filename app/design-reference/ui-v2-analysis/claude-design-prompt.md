# Nano_D++ master handoff: revision request from engineering

You designed the **Nano_D++ master handoff** (`design_handoff_nano_d_master`: README, specs 01–05, and the `Browse and Snap` prototype). Engineering has now checked it against:
- the real knob hardware;
- the user's Sonos system and Apple Music account, with live read-only probes plus reversible tests the user approved;
- the user's PC and screen.

Most of the design stands as it is. Please produce a **revised master handoff** that designs around the constraints below. Keep everything not mentioned here. Keep the same file names and structure so we can diff it, and include a **changelog** against the current master.

---

## 1. Fixed decisions (the user has made these; please don't change them)

- **LED colours, tuned by the user on the real ring.**
  - **Warm** is fixed all day. Time of day only dims the resting brightness; it never shifts the hue. Please drop the 3000 K → 1900 K hue shift.
  - Volume **80–90 %** is **amber**, and volume **≥ 90 %** is **red**. Failure red is the same red.
  - Green `0,255,98` and blue `40,140,255` stay as designed.
  - **Pink** for Like: use `255,40,90` as a starting point. The user will choose the final pink from candidates on the real ring, so don't treat it as final.

  | Colour | In prototypes (sRGB) | What the ring emits |
  |---|---|---|
  | Warm | `#FFBE69` | `#FF8424` |
  | Amber | `#FF8338` | `#FF3A0A` |
  | Red | `#FF0000` | `#FF0000` |

- **When the PC isn't connected:** the ring drains, then shows amber waiting marks. If the user turns or presses the knob in that state, the knob's own profile lights take over, because its native controls still work.
- **The on-screen floating knob** (desktop) mirrors the physical ring with the same choreography.
- **No main window.** The companion is the tray icon, the floating knob, the full-screen overlays and a Settings window.
- **The Favourite playlists tab** shows the playlists the user has favourited. That includes Apple's automatic **Favorite Songs** playlist, because the user has starred it.
- **Up next, button 3 = Like.** We tested it live on the user's account. One like makes the song a **Favorite** (the star) and puts it in the **Favorite Songs** playlist within about 2 seconds. Design Like as the button. Keep a Play-next-for-this-row variant only as a documented fallback.
- **Starting a playlist that contains unplayable songs** (region locks, uploaded-only songs) still plays, and says `Playing 33 of 34`. **Albums stay all-or-nothing:** if any song can't play, nothing is queued.

## 2. The user's screen: a 32:9 OLED at 240 Hz

- **The monitor.** A Samsung Odyssey G93SC OLED, **5120 × 1440 at 100 % scaling, 240 Hz**.
- **The layout doesn't fill it.** The prototypes' 1280 × 720 frame, scaled uniformly (×2), covers only the **middle 2560 × 1440**, leaving 1280 px empty on each side.
  - **Please design the Music explorer, Up next and the window picker for 32:9 as well as 16:9.**
  - For example, more cards visible on the ultrawide, or a deliberate centred stage with the frosted desktop around it.
  - **State the rule:** what scales and what extends.
- **Every frame shows.** OLED pixels switch instantly, so every dropped frame is visible. That is why the motion rules below are strict.

## 3. Motion and rendering rules for the desktop overlays (240 Hz)

The overlays are built on Windows' compositor (DirectComposition). The GPU runs at 240 Hz at no cost for **translate, scale, opacity and rectangular clips of pre-drawn images**, and for **crossfades between two pre-drawn states**. Anything else forces redrawing pixels every frame at 5120 px wide, and that cannot hold 240 Hz. So please follow these rules:

1. **Blur.**
   - Each surface has one fixed blur recipe: radius, saturate and tint.
   - The blur is taken from a **snapshot of the desktop when the overlay opens**. It is not live: a video playing behind it won't move.
   - Never animate a blur, saturate or brightness value, and don't move anything *behind* a blur.
   - The ambient cover layer changes by **crossfading two pre-blurred images**.
2. **No layout animation.**
   - Width, height, left, top and padding never animate. That covers the tab underline, the dots and the snap "fly".
   - Use `scaleX` or translate on fixed pieces instead.
   - Any bar whose width changes must be a square-cornered solid bar.
3. **Shadows.**
   - Shadow parameters never animate.
   - Shadows are fixed images that move, scale and fade with their element.
   - A shadow change is a crossfade between two fixed shadows.
4. **Large colour changes are crossfades,** never colour transitions. That covers the ambient layer, the big cover and row backgrounds.
5. **Text changes only when the motion rests,** for example when a detent lands, and fades by opacity. No counting numbers, marquees or re-wrapping while things move.
6. **No per-frame effects on big areas:** animated gradients, grain, particles, shimmer sweeps, parallax on the blurred backdrop, or video.
7. **Real app windows never animate.**
   - Animate their live thumbnails instead.
   - Move the real window once, while it is covered.
   - Live thumbnails stay flat and square, and only fade: no rounded corners, rotation or perspective.
8. **Don't show pictures below about 40 % of their prepared size while they're visible.** Your current scale tables are fine.
9. **The floating knob's ring glow:** specify the look for a small set of brightness levels, rather than a glow that reshapes continuously.
10. **Write every motion as a tuple:** element, property (translate, scale, opacity or clip), from, to, duration in ms, delay, and curve.
    - Write every look change as two states plus a crossfade duration.
    - Write springs as `cubic-bezier` with overshoot, or as stiffness and damping with a fixed duration.
    - Name the event that changes an asset, e.g. "the label changes when a detent lands" or "the ambient follows the focused cover; newest wins during a fast spin".

Your design already follows most of this: transform and opacity motion, static blurs, square corners, labels that fade, and real windows moved under cover. The fixes are the tab underline, the dots and the snap-fly width animation; the Up next row `box-shadow` transition; the ambient `background` transition; and the card shadow switching.

## 4. Knob screen rules (LCD: 60 fps at most, and 240 is impossible)

- **Frame rate.** The knob's 240 × 240 screen gets at most about 87 frames a second over its data line, and the panel itself probably refreshes at 60 Hz or less. **Design for 60 fps.**
- **Translate and opacity only.**
  - LVGL can't scale layers within its 64 KB of memory.
  - Please drop the 0.98 / 0.93 scale in the volume reveal and the 1.06 art scale on Windows.
- **Screen changes.**
  - Only the content fades and slides; the cover and footer stay put.
  - Covers **swap instantly**, never crossfade.
- **Keep animated areas small.**
  - Slides are **20 px or less**: there's no tearing sync, so big moves tear.
  - Fades last **at least 120 ms**; shorter ones read as a pop.
- **Text shadow.** LVGL can't blur, so the `0 1px 3px` shadow isn't possible. Choose between a **hard 1 px offset shadow at 80 %** and relying on the **darker scrim** alone.
- **Seek digits.** Seek's 48 px `m:ss` needs **tabular (fixed-width) digits and a `:` glyph**; we will add both to the font.
- **Headings.** At the heading line (top ≈ 32) the safe circle (r 104) leaves about **118 px**. `RECENT · SCREEN`, `PLAYLISTS · SCREEN` and `UP NEXT · SCREEN` don't fit at the current tracking. Please rule on it: shorter labels, tighter tracking, or letting the heading reach r 112 (about 143 px).
- **Add a 60 fps preview toggle** to the prototype's knob screen, so the LCD is judged at its real frame rate. The browser on this 240 Hz monitor shows it four times smoother than the knob can ever be.
- **LEDs** run at 60 fps and are time-based, with nothing flashing faster than 3 Hz. The Head shake counts as motion, not flashing.

## 5. Artwork: what we can actually get

- **Apple Music catalog art** can be requested at any size up to the original.
  - 95 % of albums are at least 1400 px.
  - About 5 % of old back-catalogue albums stop at **600 px**.
- **The user's library:**
  - Recently Added: all 96 albums and 4 playlists have **1200 × 1200** art.
  - Library playlists: 227 of 239 have **1200 × 1200**, 1 has 1080, and **11 have no art at all**.
- **Sonos only serves 400 × 400** for now playing and queue rows.
  - Up next can fetch 1200 px from Apple Music when a row is an Apple Music catalog song.
  - Otherwise the row only has the 400 px cover.
- **Sizes on the user's screen:**
  - explorer centre card **680 px**;
  - Up next cover **760 px**;
  - on a 4K screen at 200 %: 1020 px and 1140 px.
- **Designs needed:**
  - **Small art:** never upscale more than 1.5×. Beyond that, show the sharp cover at 1.5× on a blurred mat of itself. Please design that mat.
  - **Missing art:** a placeholder.
  - **Loading art:** a placeholder in Apple's `bgColor` for the artwork.
  - **Playlists without their own art:** a 2 × 2 mosaic of the first 4 different album covers; with fewer than 4 different albums, one full-bleed cover.

## 6. How each service really behaves (please design these states)

### Play next (Recently Added, button 3)
- **How it works.**
  - Apple Music's own "Playing Next" queue can't be reached from Windows at all.
  - The knob uses the **Sonos queue**, exactly like the Sonos app's own Play Next: songs are inserted after the current song and the rest is kept.
  - Several Play nexts stack newest-first, as in Apple Music and Sonos.
- **Only while the Sonos queue is the playing source.** Design the unavailable states:
  - **AirPlay** from the Music app, radio, or TV/line-in: `Not playing from the queue · use Play`.
  - Nothing playing: `Nothing playing · use Play`.
  - **Sonos shuffle on:** `Shuffle is on · turn it off to play next`, unless your shuffle design (§7, U4) changes this.
- **Progress.** Looking up an album's songs in Apple Music took about 6 s in a live test (we will cache it), and songs are then inserted one at a time. So even an album can take a few seconds, and a long playlist longer. Design a **`Queueing…`** progress state; we'll cap it at about 100 songs.
- **Success:** `Queued next` on the knob for 1.5 s, the toast `Queued next · {album}`, and a sweep.
- **Failure:**
  - `Couldn't queue {album} · nothing added`
  - `Partly queued · check the Sonos queue`
  - `Song changed · try again`

### Up next (the full-screen view)
- **Only when the Sonos queue is playing.** During AirPlay the Sonos queue holds old songs that aren't playing.
  - Our proposal: the view doesn't open, and the knob says `Up next is on the playing device`.
  - Or design a now-playing-only card.
- **Long queues load around the focused row;** design a **loading** state.
- **Queues started from another controller** get the title `Sonos queue`.
- **Rows that aren't Apple Music catalog songs** (local, other services) only have 400 px art and **no Like** (heart dimmed).

### Seek (Tracks, button 3)
- **Availability.** Only when Sonos offers seeking and the song length is known. Radio, streams, line-in and AirPlay can't seek, so button 3 is dimmed there.
- **Limits and timing.**
  - Seek stops **3 s before the end**, because seeking to the end skips the song.
  - Sonos takes about **0.5–2 s** to land a jump; the time shown stays frozen at the target meanwhile.
- **Exit.**
  - A target still waiting to be sent is sent on exit.
  - If the song changes, Seek exits.
- **Failure:** stays in Seek at the target, with a head shake.

### Like (Up next, button 3)
- **It writes to the user's Apple Music account.** Verified live: a like is the Favorite star, and the song appears in Favorite Songs within about 2 s.
- **Where liked songs go.** They also land in the **Favorite Songs** playlist, which is in the Favourite playlists tab. Apple can take a few minutes to sync it.
- **The heart state loads just after the list opens;** design the "not known yet" state.
- **An expired sign-in** leads to a recovery state (see §8).

### Favourite playlists tab (explorer, button 3)
- **Today it has exactly 2 items:** Favorite Songs and PAPER LANTERN Ep. 1.
- **Design these states:**
  - a **thin list** of 1–3 items in a carousel designed for many;
  - **empty:** `No favourite playlists yet`, plus how to add one: star a playlist in the Music app.
- There's no way to read "pinned" playlists, and changes take a few minutes to sync.

### Starting playback (explorer, Up next, Recently Added)
- **Playlists can take several seconds** to queue.
- **Our recommendation (U11):**
  - the overlay closes at 380 ms;
  - the knob goes Home straight away, showing `Starting…` with the Working comet;
  - the wash plays on success;
  - on failure, a head shake and `Didn't start`.
- **Home Play/Pause is disabled while starting.**

### Window snapping (the picker)
- **Windows doesn't guarantee a "Snap group"** for the pair, so leave it out of the copy.
- **Closing with one side filled:** the window that had focus before takes the other half (U12). Please confirm this and design how it looks.
- **Failures:**
  - `{App} isn't responding`
  - `Couldn't move {App}`
  - `{App} can't fit half`
- **Focus.** The picker takes focus, because Switch and Back need it. The explorer and Up next never take focus.

### Toasts
- **Never shown over an open overlay;** exit toasts appear after it closes.
- **No toast for Play/Pause.**
- **Placement:** bottom centre of the monitor showing the foreground window, held 1.8 s.

## 7. Contradictions in the current master: pick one answer and update it everywhere

1. **Paused Play on Home (U1).** Specs 01/02 say it breathes **green**. The README says "only button 4 is ever green", and the prototype renders it **warm**. We recommend **green**; the user will confirm on the ring.
2. **Volume amber/red body level (U8).** Spec 01 and the prototype use **0.62**, the LED spec uses **1.0**. We recommend **0.62**, with the odd-volume shoulder at 0.81.
3. **Windows, button 1.** The README says **Back**; specs 02/03/04 say a red Cancel. We recommend **Back**, in warm.
4. **Play next wording.** "EnqueueAsNext" is wrong for normal play; we insert explicitly after the current song. Please remove the API term.
5. **"Like feeds Favourite playlists"** (spec 01) against the README. What actually happens: a liked song lands in the *Favorite Songs* playlist, and the tab lists favourited *playlists*.
6. **Art size.** "600 px" becomes 1200 / 600 / 240 by use (§5).
7. **Seek icon handle.** The text says ≈ 60 %; the path draws it at about 65 %. Please pick one.
8. **Screen-change slide.** 16 px or 20 px? We recommend **20 px**.
9. **Turn timing.** 420 ms, or 440 ms with stagger? We recommend **420 ms**, with stagger only on open and source switch.
10. **Up next backdrop values** vs "same as the explorer".
11. **Toasts over overlays.** The prototype shows Like and Shuffle toasts over the overlay, which the README forbids.
12. **Toast place and hold.** Bottom centre, held 1.8 s, or centre and 1.5 s (spec 04)?
13. **Recently Added's first highlighted entry.** Item 1 or item 2 (prototype)?
14. **"~360 ms wake".** The LED engine's wake is a 520 ms moment, and the ring rises in 10–55 ms. Please reword.
15. **"Nothing above 3 Hz" vs the Head shake.** State that the shake is motion and exempt.
16. **Idle icon row labels.** The master's names don't fit in 46 px. We propose `Play/Pause · Browse · Tracks · Win`.
17. **Footer dim ink.** `#5A5A5A` (prototype) or `#4A4A4A` (spec 03)?
18. **Hold button 1 for 600 ms = Home.** It's in the spec but not in the prototype. Add it: the press acts as now, and if the button is still held at 600 ms the knob goes Home.
19. **"Only item colours in a coloured list"** conflicts with the Recent "More" double landmark, the warm unavailable cursor and the warm pending pulse. Please decide each.
20. **The Up next ring beyond 20 tracks** overflows. We'll show a 20-entry window around the focus unless you design otherwise.
21. **Scatter (Shuffle) positions.** The prototype's formula clusters: in 17.6 % of seeds two sparks land within one segment, and one seed puts all 9 sparks on segment 0. Please specify a well-spread pattern.
22. **Pink must never be re-saturated,** because the accent re-saturation turns it into `255,11,68`.

## 8. Designs that are missing

- Every pending, failure and unavailable state in §6.
- **Loading** states for the explorer and Up next.
- The **empty and thin** Favourite playlists tab.
- **Small and missing art** (§5).
- Up next during **AirPlay**.
- Seek unavailable.
- Snap failures.
- **Overlay lifetime:** what happens on screen lock, sleep, or long idle. We suggest they close.
- A **reduced-motion** variant.
- **Settings "status strip" (U14).** Since there's no main window, recovery needs a place. We propose three columns at the top of Settings: **Knob / Sonos / Apple Music**, with `Set manual IP…` and `Renew sign-in…`.
- **Window-picker background (U9).** Keep the user's **Frosted / No background** setting. Should Frosted get the 6 % top sheen? The explorer and Up next are always frosted.
- **Tracks `Next:` / `Prev:` titles under shuffle or repeat.** Sonos doesn't know the next song under shuffle. What should the line say?
- **Shuffle semantics in Up next (U4).**
  - Sonos's own shuffle: one command, but it may reshuffle played songs, and the resulting order can't be shown.
  - Or the companion reorders only the upcoming rows: exactly your design, a few seconds on long queues, and other Sonos apps see a reordered queue with shuffle off.
  - We recommend reordering up to 60 upcoming rows and using Sonos shuffle above that.
  - Please design what Up next shows in each case, and after Shuffle is turned off: a Play next block stays right after the current song.
- **Recently Added paging (U5).** We recommend **one flat list** with prefetch and no "More" item; the library has more than 100 items. Please confirm, and design the end of the list.

## 9. Deliverables

- **A revised README** (with precedence), **revised specs**, and a **revised `Browse and Snap` prototype** with:
  - every state from §6 and §8 reachable, through a state picker;
  - **32:9 and 16:9** desktop frames;
  - a **60 fps knob-screen preview toggle**;
  - a **motion table** of tuples (§3.10) for every overlay and knob animation;
  - a **blur recipe** per surface;
  - a **copy sheet** for every knob meta line (12 px, 170 px or less) and every toast.
- **A changelog** against the current master, with the same file names and structure.
