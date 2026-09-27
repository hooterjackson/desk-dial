# Handoff: Nano_D++ Control Center — Album artwork + targeted-colour LEDs

> **Revision 2 overrides.** Spec 01 wins for the button map, every knob layout and all copy. These points replace the text below:
> - **LCD rendering:**
>   - 60 fps; translate and opacity only; no layer scaling.
>   - Slides ≤ 20 px; fades ≥ 120 ms.
>   - Covers swap instantly.
>   - The volume reveal loses its 0.98 / 0.93 scale, and the idle view loses the 1.06 art scale.
> - **Text shadow:** a hard `0 1px 0` black at 80 %, over the darker scrim (0.60 / 0.72 / 0.92 / solid).
> - **Footer dim ink:** `#5A5A5A` (#17).
> - **Windows, button 1:** **Back**, in warm. The red Cancel is withdrawn (#3).
> - **Recently Added:**
>   - **One flat list** with prefetch (U5). No More item, no pages; the end shows `{n} / {n} · end`.
>   - The first highlighted entry is item 1 (#13).
> - **Idle icon row labels** (#16): `Play/Pause · Browse · Tracks · Win`, in button order.
> - **Artwork sizes** (#6):
>
>   | Use | Size |
>   |---|---|
>   | Explorer and Up next covers | 1200 px |
>   | Old back-catalogue floor | 600 px |
>   | Knob | 240 px (RGB565) |
>
>   Small, missing and loading art are designed in spec 01 §5.
> - **Companion surfaces:** the tray icon and menu, the floating knob, the three full-screen overlays and **Settings**, with its status strip (spec 01 §12). **There is no main window.**
> - **Colours:** see spec 02 r2 (warm `#FFBE69`, amber `#FF8338`, red `#FF0000`).


## Overview
Screen, LED and companion-app design for the Nano_D++ haptic knob: a 240 × 240 round LCD, a 60-segment RGB ring, four RGB-backlit buttons in one row below the knob, and a Windows tray companion. The knob has four controls: **Volume/Now Playing (home)**, **Recently Added**, **Tracks** and **Windows**.

This handoff covers the chosen variant:
- **Screen:** album artwork behind the text (option B in section 00 of the prototype).
- **LEDs:** white by default, with colour in a few specific places (option B in section 00b).

## About the design files
The files in this bundle are **design references built in HTML**. They show the intended look and behaviour; they are not production code. Recreate them in the real stack:
- **Firmware:** LVGL (existing Montserrat 12/14/16/22/32 and built-in symbols).
- **Companion:** existing Python/Tk tray app.

Do not ship the HTML. Do not change the installed haptic profiles.

Open `Nano_D Control Center.dc.html` in a browser (serve the folder over HTTP, e.g. `python -m http.server`, then open the file). In this copy the prototype starts with **artwork on** and **targeted-colour LEDs on**. The "Screen" and "LEDs" switches under the knob let you compare against the white/clean baseline.

`knob-model.js` is the single source of truth for behaviour. It is a pure state machine: `step(state, action) → { state, fx, cmd }` and `view(state, opts) → { lcd, foot, ring[60], buttons[4], hap }`. Port its logic rather than re-deriving it from this README.

## Fidelity
**High-fidelity.** All pixel positions below are native LCD pixels. Colours are final. Timings are final targets, to be tuned on hardware.

---

## Physical constraints (do not change)
| Control | Haptic profile (existing) | Detents/rev | Bounds / entry |
|---|---|---|---|
| Volume (home) | BINARIS BEER | 67 | 0–100 %, 1 % per detent, live |
| Recently Added | MIDI SKIPPER | 20 | 1…N on the current page (10 items + optional More). Entry: item 1 (or restored position on Back) |
| Tracks | MIDI CLACK JONES | 8 | Prev · Neutral · Next. Entry: Neutral |
| Windows | MIDI SKIPPER | 20 | 1…N of the frozen list. Entry: index 2 (most recent other window) |

Only bounds and logical entry position change per mode. Screen and LED updates must never restart a profile.

## Buttons (left → right, one row under the knob)
| # | Home (playing / paused) | Home (nothing playing) | Recently Added | Tracks | Windows |
|---|---|---|---|---|---|
| 1 | Pause / Play (white) | Play (faint, disabled) | Back (white; disabled while playback pending) | Back (white) | Cancel (red) |
| 2 | Browse → Recently Added | Browse | Home | Home | Home |
| 3 | Windows | Windows | Windows | Windows | Windows (does **not** reset selection) |
| 4 | Tracks (white, navigation) | Tracks (faint, disabled) | Play (green) / More (white) / disabled on unavailable | Prev or Next (green); disabled at Neutral | Switch (green); disabled on closed slot |

Button light levels: white = L2, green = L3, red = L2, disabled = faint white L1, inactive = off. Light changes fade over 220 ms ease-out.

---

## LCD — shared geometry (240 × 240, black)
- **Safe circle:** radius 104 px (16 px inset). Bezel may hide r 112–120. Nothing essential outside r 104.
- **Footer:** icons only, 20 px glyph, 2.3 stroke (Lucide-style 24 grid). Slot centres x = **56, 99, 141, 184**, box y 152–176 (glyph ≈ 154–174). Empty slots stay empty; the other slots never shift.
- **Footer colours:** nav `#E6E6E6` · confirm `#6ED996` · cancel `#FF8474` · disabled `#5A5A5A` · off = hidden.
- **Text colours:** ink `#F2F2F2` · secondary `#A6A6A6` · meta `#7C7C7C` · error `#FF8A7A` · success `#7EE0A2`.
- **Font:** Montserrat 500. Caps labels use 12 px with 0.08 em tracking.
- **New asset required:** Montserrat 48, digits and % only, for the volume number (fallback: 32).

### Artwork layer (this variant)
- **Size and placement:** the full 240 × 240 cover, `object-fit: cover`, drawn under all text at **80 % opacity** (35 % for unavailable library items).
- **Scrim:** a vertical black gradient on top of the cover.
  | Distance from top | Black opacity |
  |---|---|
  | 0 % | 0.35 |
  | 45 % | 0.55 |
  | 62 % | 0.90 |
  | 70 % | solid black |

  This keeps the volume number and footer on pure black. In LVGL, use a pre-rendered 240 × 240 A8 mask, or four stacked rectangles at those opacities.
- **Where it shows:**
  - **Home:** now-playing album.
  - **Tracks:** now-playing album.
  - **Recently Added:** the highlighted item's cover, changing each detent.
  - **Not shown:** on the Windows, error, offline or disconnected screens.
- **No cover available:** render the clean layout, with no placeholder art on hardware.
- **Transfer:** 240 × 240 RGB565 ≈ 113 KB. Alternative: 120 × 120 upscaled ≈ 28 KB. Cache the current cover plus the highlighted library item.

### Home — playing
| Element | Position | Type |
|---|---|---|
| Title | x 35–205, top 60 | 22/26, 2 lines max, balanced, ellipsis |
| Artist | top 114 | 14/18 `#A6A6A6`, 1 line |
| Status | top 134 | 12/14 |
| Footer | see shared geometry | Pause · Browse · Win · Tracks |

- **No room label:** the knob sits in the room it controls.
- **Status line at rest:** blank while playing. Shows "Paused", "Starting…" or "Pausing…" when applicable.

### Home — volume reveal (while turning)
- **First detent:**
  - Title and artist lift 8 px and fade out (opacity 150 ms, translate 190 ms, ease-in). No scale (r2).
  - 50 ms later the volume layer rises from translateY(6) to rest (no scale, r2), with a soft overshoot (340 ms, `cubic-bezier(.34,1.45,.64,1)`); its opacity fades in over 180 ms ease-out.
- **Volume layer:**
  | Element | Position | Type |
  |---|---|---|
  | Caption | top 52 | 14/18 `#A6A6A6` |
  | Value | top 76, centred | 48 px digits + 22 px "%" in `#A6A6A6` |
  | Status | top 134 | 12 px |

  Caption text: song title while playing, **"Paused · {title}"** while paused, "Nothing playing" when the queue is empty. Status text: "Setting…", "Changed on Sonos", "Minimum" or "Maximum".
- **Hide:** 1.4 s after the last detent, but only once Sonos has confirmed the value (re-check every 400 ms). The value exits in 170 ms ease-in; the track view returns after a 90 ms delay (420 ms ease-out).
- **External change:** a volume change made elsewhere shows the reveal for 2.6 s.

### Home — idle icon view
Used in two cases:
- **Nothing playing.**
- **4 s after a confirmed pause.** Cancelled by any Play press or by resuming.

What changes:
- **Removed:** the title, artist and footer.
- **Centred row:** four 26 px icons with 12 px words (`Play/Pause · Browse · Tracks · Win`, r2), 46 px columns in a 184 px row from x 28, top 100. Glyph and word are 8 px apart.
  - When nothing is playing, Play and Tracks are disabled (`#4A4A4A`).
  - When paused, all four icons are active.

Transition, in order:
1. The footer fades out (160 ms ease-in) and the title and artist exit (150/190 ms ease-in).
2. The artwork fades out (opacity 240 ms ease-out). No scale on the LCD (r2).
3. The icons enter left to right, each delayed 200 ms + 45 ms × index. Each goes from translateY(14) scale(0.9) to rest (460 ms overshoot) with opacity 300 ms ease-out.

Reverse: icons exit in 140/160 ms ease-in; the footer returns after a 140 ms delay; the art returns over 420/700 ms.

### Recently Added (list layout)
| Element | Position | Type |
|---|---|---|
| Label | top 32 | "RECENTLY ADDED", or "RECENTLY ADDED · P2" on later pages; 12 caps `#A6A6A6` |
| Title | top 52 | 22/26, 2 lines max |
| Artist | top 106 | 14/18 |
| Meta | top 127 | 12/14 `#7C7C7C` |

Meta line by entry:
| Entry | Meta line | Button 4 |
|---|---|---|
| Normal item | `{i}/{n} · Replaces queue` | Play (green) |
| More | `{i}/{n} · Loads, doesn't play` | More (white) |
| Unavailable | `{i}/{n} · Not available` (title in `#7C7C7C`) | Disabled |
| Pending | `Starting…` | Play disabled; button 1 disabled |
| Partial failure | `Queue replaced · didn't start` in `#FF8A7A` | Play (retries) |

Full-screen states: "Loading…", "Nothing recently added", and "Apple Music sign-in expired / Renew on your PC / Windows still works".

### Tracks
| Element | Position | Type |
|---|---|---|
| Label | top 32 | "TRACKS" |
| Title | top 54 | 22/26: "Turn to choose" / "Previous track" / "Next track" / "Previous unavailable" |
| Position row | top 88, x 72–168 | three 16 px glyphs: prev · dot · next; selected `#F2F2F2`, others `#7C7C7C` |
| Now playing | top 110 | 14 px "Now: {title}" |
| Meta | top 130 | "One press, one skip" / "Press once to skip" / "Skipping…" / "Skipped · back at neutral" (success colour) |

Never show the next song's title before the skip. After a skip, return to Neutral and stay in Tracks.

### Windows (knob)
| Element | Position | Type |
|---|---|---|
| App icon | 32 × 32 at x 104, top 42 | letter tile `#444` if no icon; 35 % opacity when closed |
| App name | top 80 | 14/18 `#A6A6A6` |
| Window title | top 100 | 16/20, 2 lines max |
| Meta | top 139 | 12 px, only for "Closed · can't switch", "Switching…", "Didn't come forward · retry" |

- **No label, count or display info on the knob.** The desktop overlay tells identical windows apart.
- **Icon source:** the companion reads the icon (WM_GETICON / exe / package icon), scales it to 32 × 32 and sends it with the frozen list (≈ 2.3 KB RGB565 + alpha each).

### Screen-to-screen transition
- **Motion:** new LCD content enters from translateX(±20 px). Transform 380 ms `cubic-bezier(.22,1,.36,1)`, opacity 220 ms.
- **Direction:** going deeper (Home → Recently Added / Tracks / Windows, or More) enters from the right. Going back enters from the left.
- **Ring and buttons:** switch instantly, with no screen transition.

---

## Ring (60 segments, segment 0 at 12 o'clock, clockwise)
Relative levels as a share of max LED drive; tune on hardware.
| Level | Drive | Used for |
|---|---|---|
| L0 | off | unused segments |
| L1 | ≈ 6 % | landmarks and bound marks |
| L2 | ≈ 18 % | volume arc body |
| L3 | ≈ 40 % | cursor and endpoint |
| L4 | ≈ 80 % | transient flashes only |

- **Damping:** segments light **instantly** and decay over **260 ms ease-out**, so the cursor never lags and fast turns leave a short tail.

### Patterns
- **Volume:** the arc runs from segment 35 (7 o'clock) clockwise to segment 25 (5 o'clock). That is 50 steps, one segment per 2 %.
  - Bound marks at 35 and 25 are L1. The body is L2 and the endpoint L3.
  - While a request is pending, the span between the confirmed and requested value drops to L1.
- **Lists (Recently Added, Windows):** one L1 landmark per entry, 3 segments apart (= 18° = 1 detent at 20/rev), centred on the top. The cursor is L3.
  - Unavailable or closed entries leave a gap, and the cursor there is L2.
  - More is a double landmark.
- **Tracks:** Prev = segments 52+53, Neutral = 0, Next = 7+8. All three are L1; the selected one is L3 and Neutral is L2 when selected.
- **Pending:** the cursor alternates L3/L1 every 260 ms, softened by the decay.
- **Feedback:**
  - Success: green L4 on the cursor ±1 for 650 ms.
  - Failure: red L3 on the cursor ±1 for 900 ms, once. No strobing.

### Targeted colour (this variant)
White stays primary. Colour applies to ring segments only, never to LCD text. Button meanings are unchanged.
- **Volume:**
  | Arc position | Segment colour |
  |---|---|
  | below 80 % | white |
  | 80–90 % | amber `rgb(255,150,30)` |
  | ≥ 90 % | red `rgb(255,55,35)` |

  The endpoint takes the colour of its position. This is a position cue only, not a loudness measurement.
- **Windows:** each landmark and the cursor take the **dominant colour of that app's icon**.
- **Recently Added:** each item landmark and the cursor take the **dominant colour of its album cover**. More stays white.
- **Always white:** Tracks, bound marks, pending pulses and the Loading state.

Dominant-colour extraction (companion side), as in `dominant()` in `knob-model.js`:
1. Downsample the image to 24 × 24 and skip alpha < 128.
2. Discard pixels with max channel < 50 or saturation < 0.3.
3. Bin by 3-3-3 RGB, weighting each pixel by saturation × value, and take the heaviest bin's weighted mean.
4. Normalise so the max channel = 255.
5. Fall back to white when the heaviest bin weight is < 4 (grey or black icons, e.g. Terminal, ChatGPT).

Send one RGB value per list entry with the list payload.

---

## State model (see `knob-model.js`)
Key state:
- **Connection and target:** `conn` (ok | missing | reconnecting), `sonos` (ok | off).
- **Mode:** `home | recent | tracks | windows`.
- **Volume:** `vol` (requested) vs `volConf` (confirmed by Sonos event), `volVis` (reveal visible), `ext` (changed elsewhere).
- **Transport:** `playing` vs `playReq`, `pIdle` (paused-idle view), `nothing` (empty queue).
- **Recently Added:** `recent { page, idx, stack[], status: loading | ready | empty | auth | pending | partial }`.
- **Tracks:** `tracks { pos: -1|0|1, status: idle | pending | done }`.
- **Windows:** `win { order[] (frozen MRU snapshot), idx, closed[], status: browsing | pending | failed, ret (mode to restore on Cancel) }`.

Rules:
- **No undo:** Back or Cancel never undoes dispatched playback or volume.
- **Reconnection:** discard input while disconnected; on reconnect read fresh state and go to Volume. Never replay gestures.
- **Missing music service:** Windows switching stays available when Sonos or Apple Music is unavailable.
- **Windows picker:** the overlay is companion-owned, topmost and never takes focus. It dismisses on an external focus change, and Cancel restores the previous focus.

## Companion app (Archivo, 0 radius, 2 px rules; neutral dark)
| Token | Value |
|---|---|
| Background | `#1B1A1A` |
| Surface | `#242323` |
| Hairline | `#2D2B2B` |
| Strong rule | `#444141` |
| Text | `#F3F2F2` |
| Secondary | `#BAB6B6` / `#9B9797` |
| OK | `#6ED996` |
| Error | `#FF7A66` |

Surfaces (r2): tray icon and menu, floating knob, the three full-screen overlays and Settings, with its status strip (spec 01 §12). **There is no main window.** See section 04 of the prototype for the exact layouts; they are unchanged by this variant.

## Assets
- `assets/covers/*` — sample album covers downloaded from Wikipedia, for the mockup only. Production uses Apple Music artwork.
- `assets/apps/*` — sample app icons from Wikipedia/Wikimedia Commons. Production reads the real icons from Windows.
- **Icons:** Lucide-style paths in `knob-model.js` (`I`), with LVGL symbol equivalents in `LV`. Windows maps to LV_SYMBOL_COPY; Switch needs a custom glyph or LV_SYMBOL_SHUFFLE.

## Files
- `Nano_D Control Center.dc.html` — full design document and interactive prototype (sections 00–08).
- `Knob Face.dc.html` — LCD + ring + buttons renderer (props: `view`, `part`, `zoom`, `art`, `overlay`, `tilt`).
- `knob-model.js` — state machine, view derivation, LED colour extraction, sample data.
- `support.js`, `_ds/…` — runtime and stylesheet needed to open the prototype.
