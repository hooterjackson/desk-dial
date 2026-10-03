# Handoff: Nano_D++ r3.1 — delta on r3

r3.1 answers the r3 hardware-test feedback (2026-09-29). It is a **delta on r3**: anything not listed here is unchanged from `README_r3.md` (included), which in turn is a delta on `reference_r2.2/`. Where they disagree, this file wins.

**Locked by engineering (reflected in the prototype):** Home = 1a base + hold-4 domain swap, Lights = 1e (Scenes list), arc breadcrumbs (pre-rendered), Home Assistant via the companion, unfilled part of the Lights arcs **off**, nav button LEDs **warm white**, Play **green while paused**.

## Files
| File | What changed |
|---|---|
| `prototypes/Knob IA Prototype r3.1.dc.html` | **New.** r3.1 prototype: knob, ring, 32:9 monitor with Navigator, and the companion Settings window below it |
| `prototypes/Knob IA Prototype.dc.html` | r3 prototype, kept for comparison |
| `README_r3.md` | r3 README (was `README.md`) |
| `reference_r2.2/` | Unchanged |

Run: serve `prototypes/` over HTTP and open the r3.1 file. Header switches: **Music state** (Playing / Paused / Nothing loaded), **Hall area** (All on / Mixed / Unavailable / No lights / Not connected), **Navigator**, **Reset**. The Home, Lights and Breadcrumbs option switches are gone (decided).

---

## 1. Hold 4 (1.0 s) = universal secondary action
| Rule | Value |
|---|---|
| Tap 4 | Acts **on release**, instantly, on every screen (no double-tap, no 300 ms wait) |
| Hold 4 | 1000 ms → secondary action. Release before 1000 ms = tap |
| Screens with a hold action | Home, Recently Added / Playlists (knob list), Music explorer, Up next. Elsewhere hold 4 = tap on release |
| Ring while holding | Warm `255,190,105` arc, L 1.0, fills 0→100 % of the 45-segment arc over 1000 ms; drawn from 15 %. Same family as hold-1 (600 ms) |
| Landing | Ring wash 450–600 ms in the outcome colour (green `110,217,150` for queue; new-domain colour for the swap) |
| LCD hint | 16 × 2 px bar, `#A6A6A6`, radius 1, at (176, 180) under footer slot 4 — shown only where hold 4 does something. Fades with the footer |

### 1.1 Home domain swap
Hold 4 on Home swaps the Home knob **Music volume ⇄ Lights brightness**. Button map stays 1 Music · 2 Windows · 3 Lights; button 4 becomes the domain's toggle.

| | Music domain | Lights domain |
|---|---|---|
| Knob | Volume | Brightness of every on light in the area |
| Button 4 | Play/Pause (pause icon nav; play icon + LED **green** when paused) | Lights on/off, power icon nav `#E6E6E6` (dis `#5A5A5A` when blocked) |
| Label | none | `LIGHTS` (arc) |
| Title / sub | Song / artist | Scene name (or area name after a manual change) / `Hall · 62% · 3200 K` |
| Meta | `Paused` when paused | `2 of 3 on`, `Shelf strip unavailable` (`#FF8474`) |
| Off | — | `Lights off` / `Tap 4 to turn on`, ring off |
| Turning | Volume reveal | Brightness reveal: caption = area name, value `62 %`, arc in the Kelvin colour, unfilled off |
| Ring at rest | r2.2 | Kelvin-colour arc L 0.34 to brightness, unfilled **off** |

**Transition:** status `Knob sets brightness` / `Knob sets volume` (`#FFBE69`, 1.8 s); ring wash in the new domain colour (Kelvin RGB of the current temperature, or warm for music) 450 ms; the LCD content layer and Navigator content slide 20 px (to Lights = from the right, back to Music = from the left) with the r3 screen-change timing (220 ms opacity / 380 ms transform, `cubic-bezier(.22,1,.36,1)`). The domain persists until swapped again.

### 1.2 Queue from selection screens
| Screen | Tap 4 | Hold 4 | Confirmation |
|---|---|---|---|
| Recently Added / Playlists (knob) | Play (replaces queue) | Queue the album / playlist (plays after the current song) | Knob meta `Queued · {title}` `#7EE0A2` 2.2 s; ring green 600 ms; Navigator status line shows the same |
| Music explorer (screen) | Play | Queue | Knob + ring as above; explorer meta line reads `Queued · plays after this song` for 2.2 s (only text changes; layout untouched) |
| Up next (screen) | Play this track | Play next | `Plays next · {song}`; the Up next context line shows it in `#9CF0BC`. Holding on the playing song → `Already playing` (deny) |

The full-screen footers' button-4 hint reads `Play · hold to queue` / `Play · hold for next`.

### 1.3 Navigator hold row
Under the 2 × 2 keys grid: caps label `HOLD` (10 px, 0.12 em, white 60 %) then one chip per hold: 16 px key box + 11 px label. Chips: `1 Home` (when ≥ 2 levels deep), `4 Knob to lights` / `4 Knob to music` (Home), `4 Queue` (Recently Added / Playlists), `4 Play next` (Up next). While held, the key box fills white bottom-to-top with the hold progress; text flips to black past 55 %.

---

## 2. Recently Added knob list: button 3 = Recently Added ⇄ Favourite playlists
| | Recently Added | Favourite playlists |
|---|---|---|
| Breadcrumb | `MUSIC › RECENTLY ADDED` | `MUSIC › PLAYLISTS` |
| List | prev / title / next | same |
| Meta | `4 / 9 · Air` | `2 / 4 · 24 songs` |
| Art behind | Cover | **2 × 2 mosaic** of the first four albums (each 50 % × 50 %), same scrim |
| Ring | Marker in the album colour | Marker in the first album's colour |
| Button 3 | List-music icon, nav | List-music icon **warm** + LED warm L 0.9 (lit = showing playlists; tap to go back) |
| Navigator button 3 label | `Playlists` | `Recent` |

Tap 3 switches source, resets to item 1, status `Favourite playlists` / `Recently Added` (`#FFBE69`, 1.2 s). Button 2 opens the explorer on the **same source and item**; Back from the explorer returns to the knob list on the same item. Music › 2 always opens Recently Added at item 1.

**Navigator carousel for playlists:** same vertical mini carousel (120 px, radius 8), each card a 2 × 2 mosaic; status `2 / 4 · 24 songs` (no year); secondary line `Favourite playlist`.

---

## 3. Tracks = browse the whole queue
The knob moves a **focus row** through the entire queue (clamped, no wrap). Button 4 plays the focused track.

| State | Title | Sub | Meta | Ring | Button 4 |
|---|---|---|---|---|---|
| Focus = playing | Song | Artist | `Turn to browse the queue` `#7C7C7C` | Queue ring | dis, LED L 0.12 |
| Focus elsewhere | Focused song | Artist | `Skip to 5 / 6 · 4 plays` or `Back to 2 / 6 · 4 plays` `#7EE0A2` | Queue ring | Play icon green, LED green |
| Seek | r3 Seek (entering Seek resets focus to the playing song) | | | | disabled |

**Queue ring:** positions spread over the 45-segment arc (`round(i · 44 / (n − 1))`); focus = 3 segments in the album colour L 1.0; playing song = 1 segment warm white `255,232,205` L 0.6; rest album colour L 0.1. Works for any length; markers merge above ~22 tracks — acceptable, the LCD carries the count.

**Tap 4:** at the playing row → deny `Turn to browse the queue`. Elsewhere → play it, status `Playing 5 / 6`, focus stays on it (now the playing row).

**Navigator Tracks:** 5 rows × 38 px **centred on the focus row** (plate fixed in the middle); playing row `♪` + title `#9CF0BC` + tag `NOW`; focus row tag `SKIP TO` / `BACK TO` in `#6ED996`. Status `Turn to browse the queue` or `5 / 6 · Press 4 to play`. Keys: Back · Up next · Seek · Play (dim at the playing row).

**Up next ⇄ Tracks:** 2 opens Up next with its selection on the **focus row**; Back from Up next returns Tracks focused on Up next's row.

---

## 4. Paused keeps the artwork
- Home (music domain) and Music stay on **Now Playing** when paused: art, scrim, title/artist, footer.
- Art opacity drops 0.8 → **0.45** while paused (scrim unchanged, full black ≥ 70 %).
- Meta line (top 134) `Paused` `#A6A6A6`.
- Footer 4 = **Play icon in green `#6ED996`**, button 4 LED green L 0.68.
- The icon-only idle row is **only for "nothing loaded"**:
  - Home: `Music · Win · Lights · Play` (Play dis).
  - Music: `Home · Recent · Tracks · Play` (Tracks and Play dis) — this includes the house and album icons that were missing on hardware.
- Nothing loaded: 4 → deny `Nothing loaded · pick in Recent`; Music 3 → deny `Nothing loaded`. Navigator: placeholder square, `Nothing playing` / `Pick an album in Recent`.

---

## 5. Lights = the whole Home Assistant area
The knob targets **every light in the chosen area** (default Hall), including lights added later; the Scenes list is the area's scenes, scripts and automations.

**Aggregate:** brightness and temperature shown = **average of the lights that are on** (temperature rounded to 100 K). Turning sets **every on light** to the new value (first detent snaps them together). Turning while all are off turns every available light on at 1 %. All off snapshots each light; Turn on restores each light's snapshot (or all on if none were on).

### 5.1 Copy
| State | LCD (Lights space) | Home lights domain | Navigator |
|---|---|---|---|
| All on, uniform | title scene or `Hall`, sub `62% · 3200 K`, meta `Hall · 3 lights` | sub `Hall · 62% · 3200 K` | `3 lights · 3 on` |
| Mixed | meta `2 of 3 on · average` (or `3 lights · average` when all on at different levels); reveal caption `Brightness · average` | meta `2 of 3 on` | caption `Brightness · average`; `3 lights · 2 on` + per-light rows |
| Light unavailable | meta `Shelf strip unavailable` / `2 lights unavailable` `#FF8474` | same | area line in `#FF8474` + per-light rows, row `Unavailable` |
| All off | `Lights off` / `Tap 4 to turn on`, meta `Hall · 3 lights` | `Lights off` / `Tap 4 to turn on` | big `Off` |
| No lights | `No lights in Hall` / `Add them in Home Assistant`; 2–4 disabled, deny `No lights in Hall` | same | big `—`, `No lights in Hall` |
| All unavailable | `Lights unavailable` / `Hall · 3 lights`, meta `Check them in Home Assistant` `#FF8474` | same | `All lights unavailable` |
| Not connected | `Not connected` / `Home Assistant`, meta `Open Settings on your PC` `#FF8474`; deny `Home Assistant not connected` | same | caption `Home Assistant`, `Not connected · open Settings` |
| No scenes in area | Button 2 wand dis; deny `No scenes in {area}` | — | Scenes key dim |

Title rule: the active scene's name while untouched; after any manual change, the **area name** (`Hall`).

### 5.2 Navigator Lights card (area) — compact
Path `Lights › Hall` / `Home › Hall`. No separate big number. Two value rows, each: caps label (11 px) left + value **16/18 px 600 tabular** right, 4 px bar below (gap 5). Brightness row label becomes `Brightness · avg` in a mixed area; value `Off` when all off, `—` when blocked. The row the knob isn't changing drops to 50 %. Then one summary line 12/15: **scene name** (600, white; area name after a manual change) + ` · 3 lights · 2 on` (+ `· 1 unavailable`, whole line `#FF8474`).
- Per-light rows **only when the area is mixed or a light is unavailable**: 6 px dot (Kelvin colour when on, white 25 % off, `#FF8474` unavailable), name 12 px, value 11 px tabular (`62% · 3200 K`, `Off`, `Unavailable`). A uniform area shows just the summary line.

Scenes list rows tag the type (`SCENE`, `SCRIPT`, `AUTOMATION`) or `RUNNING`.

### 5.3 Companion Settings → Home Assistant
Companion tokens (r2.2 spec 03): Archivo, 0 radius, 2 px rules, bg `#1B1A1A`, surface `#242323`, hairline `#2D2B2B`, rule `#444141`, text `#F3F2F2`, secondary `#BAB6B6` / `#9B9797`, OK `#6ED996`, error `#FF7A66`.

- **Status strip** gains a 4th column **Home Assistant**: `Connected` · `Hall · 3 lights · 5 scenes`, or `Not connected` · `Add your address and token below` (8 px square mark).
- **Section nav** (180 px): General · Music · Windows · **Home Assistant** · Knob.
- **Fields** (2-column grid, 36 px controls, caps 11 px labels): Address (`http://homeassistant.local:8123`), Long-lived access token (masked, Show/Hide), Area (select, default Hall), **Test connection** (outlined).
- **Status line** (8 px mark + 13 px): `Not tested since the last change` (grey) · `Connecting to {address}…` (amber) · `Connected · Home Assistant 2026.9 · token valid` (green) · errors (red): `Can’t reach {address}. Check the address and that Home Assistant is running.` / `Token rejected (401). Create a long-lived access token in your Home Assistant profile.`
- **Found (live, after a successful test):** two lists — `Lights in Hall · 3` (dot, name, `62% · 3200 K` / `Off` / `Unavailable`) and `Scenes, scripts and automations · 5` (name + type). Empty area: `No lights in {area} yet. Assign lights to this area in Home Assistant and they appear here and on the knob automatically.` Before a test: `Test the connection to see the lights and scenes in {area}.`
- **Save** (filled `#F3F2F2`, enabled only after a successful test) applies the area to the knob; `Saved · the knob now controls {area}` (green, 2.5 s). **Cancel** reverts the area. Editing the address or token resets the status to untested.

Bridge calls are as r3 §7, targeting `area_id` instead of a group. Subscribe to area registry changes so new lights join without a restart.

---

## 6. LED changes
| Item | r3 | r3.1 |
|---|---|---|
| Nav button LEDs | White `240,240,240` | **Warm white `255,232,205`** (L 0.34; disabled L 0.12) |
| Lights brightness arc, unfilled | L 0.08 | **Off** |
| Temperature arc, beyond the marker | L 0.12 | **Off** (filled part L 0.5 rest / 1.0 turning; marker L 1.0) |
| Play while paused | — | Footer icon + LED **green** |

---

## 7. Open questions
1. **First-detent snap in mixed areas.** Turning sets every on light to average ± 1, which flattens a deliberately uneven room. Alternative: shift each light by the same delta (relative). Relative keeps the mix but the shown average can then clip at 1 / 100 %.
2. **Hold-4 discoverability.** The 16 × 2 px LCD bar is subtle; confirm it reads on hardware or use a 3 × 3 dot.
3. **Hold 4 while paused on Home.** Swapping to Lights while music is paused hides the paused art until you swap back. OK, or should Home remember/indicate the other domain?
4. **Queue semantics** for Apple Music playlists: "plays after the current song" inserts the whole playlist; confirm vs append-to-end.
5. **Tracks for long queues:** clamp (current) vs wrap; and whether Shift/fast turns should accelerate.
6. **Area picker scope:** one area only, or allow multiple (e.g. Hall + Office) with the knob controlling their union?
7. **Explorer queue toast** changes one text line in a full-screen view; confirm that's acceptable, or show it on the knob only.
8. Carry-overs: final Like pink, green breathing confirmation, 48 px tabular text widths.
