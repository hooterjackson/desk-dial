# Handoff: Nano_D++ r3 — Spaces IA, Home Assistant lights, on-screen Navigator

## Overview
r3 restructures the knob around three **spaces** — **Music**, **Windows** and **Lights** — opened from a launcher-style **Home**. It adds control of the office/hall lights through **Home Assistant** (brightness, colour temperature, saved automations/scenes, all off), adds **arc breadcrumbs** to the knob LCD, and replaces the companion's **floating knob mirror** with a compact glass **Navigator** on the left edge of the monitor.

**r3 is a delta on r2.2.** Everything not mentioned here is unchanged from the r2.2 package (`design_handoff_nano_d_master/`, included as `reference_r2.2/`): the three full-screen overlays (Music explorer, Up next, Window picker), their 32:9 tables, artwork rules, LED colour tokens, haptic profiles, motion tables, copy sheet and Settings. Where this README and r2.2 disagree, **this README wins**.

## About the design files
The files in `prototypes/` are **design references built in HTML**. They show the intended look and behaviour; they are not production code. Rebuild them in the real targets:
- **Firmware** (LVGL, 60 fps LED task): knob LCD, ring, button LEDs, the new Lights space.
- **Companion** (Windows tray app): the Navigator overlay, the unchanged full-screen overlays, and the new Home Assistant bridge.

Do not ship the HTML. To run it, serve `prototypes/` over HTTP (e.g. `python -m http.server`) and open `Knob IA Prototype.dc.html`.

**Prototype controls:** turn = drag around the knob, scroll over it, or ←/→ (Shift = 5 detents). Buttons = click or keys 1–4. Hold 1 = Home. Header switchers: **Home** option (1a/1b/1c), **Lights** option (1d/1e), **Breadcrumbs** (Arc / v1 Path + pips / Ring), **Navigator** (Auto-hide / Pinned / Off), **Reset**. The right panel always shows the live button map.

## Fidelity
**High-fidelity** for IA, button maps, LCD layout, copy, LED behaviour and Navigator visuals. Albums, windows, scenes and durations are sample data. Timings are targets to tune on hardware.

---

## 1. Information architecture

```
Home ─┬─ 1 Music ──┬─ 2 Recently Added (knob) ── 2 Music explorer (screen, r2.2)
      │            └─ 3 Tracks (knob) ─────────── 2 Up next (screen, r2.2)
      ├─ 2 Windows ── Window picker (screen, r2.2) opens immediately
      └─ 3 Lights ───  2 Scenes list (knob)        [option 1e]
                       3 Scene selector knob mode  [option 1d]
```

**Global rules**
| Rule | Detail |
|---|---|
| Button 1 goes out | At a space root = **Home**. Deeper = **Back** one level. |
| Button 4 acts | The primary action of the screen (Play/Pause, Play, Skip, Switch, Run, All off). Green when it commits something. |
| Button 2 opens | Opens the next level / full-screen view where one exists. |
| Hold 1 (600 ms) | Home from anywhere, closes any overlay. The ring fills a warm arc over the hold (see §4). |
| Overshoot guard | A tap on 1 within **700 ms** of arriving Home (via 1 or hold) is ignored and the status line reads `Home · press 1 again for Music`. Prevents mashing 1 from landing in Music. |
| Unavailable buttons | Stay in place, dimmed. A press does nothing except show the reason (§6) and flash the bottom ring segments red. |

### 1.1 Home — three candidates (not yet decided)
All three share: **1 Music · 2 Windows · 3 Lights · 4 toggle**. The toggle moved from button 1 (r2.2) to button 4 so the primary action sits on 4 everywhere.

| | Knob on Home | Button 4 | Notes |
|---|---|---|---|
| **1a Launcher** (recommended) | Volume, always | Play / Pause | No new gestures. Brightness needs one press (enter Lights). |
| **1b Double-tap 4** | Volume, or brightness when the Home domain is Lights | Tap: Play/Pause or lights on/off · Double-tap (≤ 300 ms): swap domain | Single taps must wait 300 ms to disambiguate → laggy Play/Pause. |
| **1c Follows last** | Whichever of Music/Lights was **entered** last (Windows doesn't count) | Play/Pause or lights on/off | Implicit mode; the `LIGHTS` label and ring colour must always show it. |

In the Lights domain (1b/1c) Home shows label `LIGHTS`, title = scene name, sub `Hall · {bri}% · {K} K`; off state title `Lights off`, sub `Tap 4 to turn on`.

### 1.2 Button maps
| Screen | Knob | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| **Home** (1a) | Volume | Music | Windows | Lights | Play / Pause |
| **Music** | Volume | Home | Recently Added | Tracks | Play / Pause |
| **Recently Added** (knob list) | Scroll | Back → Music | Full screen (explorer) | Play next | **Play** (replaces queue) |
| **Music explorer** (screen) | Scroll covers | Back → knob list, same album | Recently Added tab | Favourite playlists tab | **Play** |
| **Tracks** | Prev · Now · Next | Back → Music | Up next (screen) | Seek | **Skip** (disabled at Now and in Seek) |
| **Seek** (Tracks mode) | Scrub ±5 s / detent | **Cancel** (restores position) | Up next | **Set** position | disabled |
| **Up next** (screen) | Scroll queue | Back → Tracks | Shuffle | Like (add-only) | **Play** this track |
| **Windows** (picker on screen) | Scroll windows | Home (restores focus) | Snap left | Snap right | **Switch** → Home |
| **Lights 1d** | Brightness · Temperature (2 lit) · Scenes (3 lit) | Home (cancels a pending scene first) | Temperature on/off | Scene selector on/off | All off / Turn on |
| **Lights 1e** (recommended) | Brightness · Temperature (3 lit) | Home | Scenes list | Temperature on/off | All off / Turn on |
| **Scenes list** (1e) | Scroll automations | Back → Lights | — | — | **Run** |

**Lights modes are knob modes, not menus.** The lit button (warm, L 0.9) shows which mode the knob is in; tapping it again returns to brightness. Entering Lights from Home always starts in brightness.

**1d scene selector:** turning moves the selection; the scene **runs 1.0 s after the last detent** (status `Runs in 1 s · 1 cancels`, amber `#FFBE69`). Pressing 1 while pending cancels (`Scene cancelled`). Open concern: pausing mid-scroll can fire a scene — consider 1.5 s or "press 4 to run".

**All off / Turn on:** All off snapshots the current state; Turn on restores that snapshot (not a default scene).

**Turning while lights are off** turns them on at 1 % (brightness) or at the stored level with the new temperature.

---

## 2. Knob LCD (240 × 240, Montserrat 500)
Geometry, scrim, footer slots and colours are r2.2 (spec 03 shared geometry). Changes:

### 2.1 Arc breadcrumb (default)
The breadcrumb replaces the flat top label when enabled.
| Property | Value |
|---|---|
| Path | Arc, centre (120,120), **r 94**, from 180° to 0° across the top (`M 26 120 A 94 94 0 0 1 214 120`), text centred at the apex |
| Type | Montserrat 500, 12 px, caps, letter-spacing 0.96 px (0.08 em) |
| Ancestors | `#7C7C7C`, each followed by ` › ` |
| Current | `#E6E6E6` |
| Home | No breadcrumb (Lights domain shows `LIGHTS`) |
| Hidden | In the idle icon view |

Paths: `MUSIC` · `MUSIC › RECENTLY ADDED` · `MUSIC › RECENT › ON SCREEN` (or `PLAYLISTS ›`) · `MUSIC › TRACKS` · `MUSIC › TRACKS › UP NEXT` · `WINDOWS` · `LIGHTS` · `LIGHTS › SCENE 2 / 5` (1d selector) · `LIGHTS › SCENES` (1e).

**LVGL:** needs arc text (LVGL ≥ 9.3 `lv_arclabel`) or per-glyph rotated labels, or pre-rendered A8 bitmaps per path. Fallback: **v1 flat path** — label row top 32, x 30–210, parent in `#7C7C7C` + current in `#A6A6A6`, gap 5 px; shorten `RECENTLY ADDED` → `RECENT` when a parent is shown; plus depth pips (5 px dots at top 17, gap 5; filled `#E6E6E6` = depth, hollow `inset 1px #5A5A5A` = remaining levels; Music 3, Lights 2, Windows 1). **Ring** variant (1–3 white segments at the bottom, i = 30 / 29,31 / 28,30,32, L 0.7) was explored and not recommended.

### 2.2 Screens (new or changed)
| Screen | Layout | Content |
|---|---|---|
| Home (music) | r2.2 home | Title 22/26 top 60, artist 14 top 114. Idle icon row: `Music · Win · Lights · Play` |
| Music | Home layout + breadcrumb | Same as Home; art behind (r2.2 scrim, full black ≥ 70 %) |
| Tracks (at rest) | Text | Title = **current song** (was "Neutral"), sub = artist, meta `Turn for previous or next` `#7C7C7C` |
| Tracks (turned) | Text | Title `Previous` / `Next`, sub `Now: {song}`, meta `Press 4 to skip` |
| Seek | Big | Caption = song, value `m:ss` 48 px, status `of {dur} · 3 sets · 1 cancels` in `#FFBE69` |
| Lights | Text | Title scene name (`Focus · adjusted` after manual change), sub `{bri}% · {K} K`, meta `Knob: temperature` `#FFBE69` in temp mode |
| Lights (turning) | Big | Caption `Brightness` + `62` `%`, or `Colour temperature` + `3200` `K` |
| Lights off | Text | `Lights off` / `Tap 4 to turn on` |
| Scene selector (1d) / Scenes (1e) | List | prev 14 `#7C7C7C` top 56, current 22 top 78, next 14 top 108; meta `2 / 5 · 48% · 2700 K` or `· running now` |

**Icons (Lucide-style, 24 grid, 20 px, stroke 2.3)** — new in r3:
| Icon | Use | Path |
|---|---|---|
| Album (square + disc) | Recently Added / explorer tab 2 | `M3 3h18v18H3zM12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 11.5v1` |
| Wand + sparkles | Scenes / automations (1d btn 3, 1e btn 2) | `M21.6 2.6l-1.2-1.2a1.2 1.2 0 0 0-1.7 0L2.4 17.7a1.2 1.2 0 0 0 0 1.7l1.2 1.2a1.2 1.2 0 0 0 1.7 0L21.6 4.3a1.2 1.2 0 0 0 0-1.7zM14 7l3 3M5 6v4M19 14v4M10 2v2M7 8H3M21 16h-4M11 3H9` |
| Thermometer | Temperature | `M14 4v10.5a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0z` |
| Power | Lights on/off (Home 4, Lights 4) — always nav `#E6E6E6`, never red | `M12 2v10M18.4 6.6a9 9 0 1 1-12.8 0` |
| Lightbulb | Lights space (Home 3) | Lucide `lightbulb` |
| Music notes / Window | Music / Windows spaces (Home 1/2) | r2.2 icons |
| Home | Button 1 at a space root | Lucide `house` |
| Chevron-left | Button 1 deeper | r2.2 |
| Expand | Open full screen | r2.2 |

---

## 3. Ring (60 segments) — additions
Arc = 45 segments clockwise from index 38 (7:30) through the top to index 22; indices 23–37 (bottom) stay free for signals.

| State | Rendering |
|---|---|
| Brightness | Arc filled to `bri%` in the **current colour temperature** (below); L 0.34 at rest, 1.0 while turning; unfilled L 0.08 |
| Colour temperature | Whole arc in the selected Kelvin colour; filled portion L 0.5 at rest / 1.0 turning, marker segment at position L 1.0, remainder L 0.12. Position = (K − 2200) / 4300 |
| Lights off | All segments off |
| Scene selector / list | N clusters of 3 segments evenly spaced; selected cluster warm L 1.0, others warm L 0.18 |
| Scene ran | Green `110,217,150` wash L 0.68 for 700 ms |
| Hold 1 progress | Warm arc fills 0 → 100 % over 600 ms (shown after 12 %) |
| Unavailable press | Bottom segments 26–34 red `255,60,40` L 0.9 for 320 ms (replaces the full-ring flash) |
| Windows | Marker in white at the window's position, rest warm L 0.1 |
| Explorer / Recently Added | Marker in the album's dominant colour |

**Kelvin → RGB** (white-only bulbs, 2200–6500 K; Tanner Helland approximation):
```
t = K / 100
r = t <= 66 ? 255 : 329.7 * (t − 60)^−0.1332
g = t <= 66 ? 99.47 * ln(t) − 161.12 : 288.12 * (t − 60)^−0.0755
b = t >= 66 ? 255 : 138.52 * ln(t − 10) − 305.04        (clamp 0–255)
```
2200 K ≈ `255,146,39`; 3200 K ≈ `255,183,112`; 6500 K ≈ `255,254,250`. Calibrate against the ring's real white point.

**Button LEDs:** nav white L 0.34, disabled L 0.12, active mode warm `255,190,105` L 0.9, commit green L 0.68, liked pink `255,40,90` L 0.30, snap side assigned = app colour L 1.0. Lights button 4 is **white**, not red.

---

## 4. Motion
r2.2 motion rules stand (translate + opacity only, ≤ 20 px slides, ≥ 120 ms fades).
| Event | Motion |
|---|---|
| Screen change | Content layer slides 20 px in the depth direction (deeper = from right) + fades; 220 ms opacity / 380 ms transform, `cubic-bezier(.22,1,.36,1)` |
| Value reveal (volume/brightness/temp) | r2.2 volume reveal; hides 1.4 s after the last detent |
| Navigator show / hide | Opacity 280 ms + translateX(−24 → 0) 420 ms, ease-out |
| Navigator content swap | Same slide/fade as the knob content layer, in sync |
| Navigator lists | Rows/covers translate 380 ms ease-out; plate 320 ms |

---

## 5. Navigator (companion overlay — replaces the floating knob)
Shown on the monitor whenever the knob is used, except while a full-screen overlay is open (those are unchanged).

**Visibility:** appears on any turn or press. Auto-hides **4 s** after the last input at Home and space roots. **Stays visible** while in Recently Added, Tracks, Scenes, temperature/scene knob modes or a pending scene. Settings: Auto-hide (default) / Pinned / Off.

**Geometry (32:9 = 5120 × 1440; values below in the prototype's 2560 × 720 stage, ×2 for device pixels):** left 20, vertically centred in the work area (above the 48 px taskbar), **width 250**, height = content, padding 16, gap 14, **radius 26**.

**Liquid-glass recipe**
- `backdrop-filter: blur(14px) saturate(1.8) brightness(1.06)`
- Fill: `linear-gradient(160deg, rgba(255,255,255,.18) 0%, rgba(255,255,255,.05) 42%, rgba(255,255,255,.09) 100%)` over `rgba(18,18,22,.30)`
- Rim: inset `0 1px 0 rgba(255,255,255,.6)`, `0 −1px 0 rgba(255,255,255,.14)`, `1px 0 0 rgba(255,255,255,.22)`, `−1px 0 0 rgba(255,255,255,.1)`
- Specular: radial white .22 → transparent, 220 × 160 at (−40, −60)
- Drop shadow `0 18px 50px rgba(0,0,0,.35)`; text-shadow `0 1px 2px rgba(0,0,0,.35)`
- No colour tint / ambient fill. On Windows use DirectComposition acrylic/backdrop blur with these values.

**Type:** Archivo. Caps labels 11/…, 600, 0.12 em, white 75 %. Titles 15/19 600. Secondary 12/16 white 85 %. Meta 11/15 white 70 %. Numbers tabular.

**Content by state**
| State | Content |
|---|---|
| Path row (all) | e.g. `Home`, `Music`, `Music › Recently Added`, `Music › Tracks › Seek`, `Home › Lights`, `Lights › Scenes` |
| Home / Music | 64 px cover (radius 8) + title / artist / `Playing · 1:04 of 4:12`; Volume row (caps label + %) and 4 px bar, 60 % opacity at rest, 100 % while turning |
| Lights | Caption + 44 px number (`62 %`, `3200 K` or `Off`); Brightness bar (fill in Kelvin colour); Temperature bar (gradient 2200 → 3400 → 6500 K, white 4 × 12 marker); Scene row. The row the knob is changing is 100 %, the other 50 % |
| Recently Added | Vertical mini carousel, 196 px tall: 120 px cover; neighbours ±86 px @ 0.55, ±132 @ 0.38; opacity 1 / .55 / .25; then title, artist, `4 / 9 · 1998` |
| Tracks | 5 rows × 38 px around the playing song (wrap-around at album ends); plate `rgba(255,255,255,.16)` radius 10 moves to the target; tags `Now`, `Skip to` / `Back to` (green); playing title `#9CF0BC` |
| Seek | 44 px cover + title, 36 px `m:ss` + `of 4:12`, 4 px warm bar |
| Scenes | Same 5-row list: name + tag `Running` (`#7EE0A2`); status `Runs in 1 s` (amber) / `Press 4 to run` |
| Keys (all) | 2 × 2 grid: 16 px key box (radius 4, 1 px white 55 %) + 11 px label of what 1–4 do now; pressed key fills white; unavailable 40 %. Below it, `Hold 1 for Home` when two or more levels deep |

---

## 6. Copy
| Context | Copy |
|---|---|
| Unavailable: Skip at Now | `Turn to pick previous or next` (`#FF8474`) |
| Unavailable: Skip in Seek | `Set or cancel seek first` |
| Unavailable: Scenes 2/3 | `Turn to choose · 4 runs it` |
| Seek | `Seek set` · `Seek cancelled` |
| Overshoot guard | `Home · press 1 again for Music` |
| Lights | `Lights off` · `Lights on` · `Tap 4 to turn on` · `Knob: brightness` · `Knob: temperature` · `Knob: scenes` |
| Scenes | `Runs in 1 s · 1 cancels` · `Scene running` · `Scene cancelled` · `running now` |
| 1b swap | `Knob sets brightness` · `Knob sets volume` |
| Windows | `Snapped left` · `Snapped right` · `Switched to {app}` |

---

## 7. Home Assistant bridge (proposal for engineering)
| Knob action | HA call |
|---|---|
| Brightness | `light.turn_on` on the hall area/group, `brightness_pct` 1–100, 1 % per detent; throttle to ≤ 10 Hz, send the final value on settle |
| Temperature | `light.turn_on`, `color_temp_kelvin` 2200–6500, 100 K per detent (clamp to the bulbs' reported min/max) |
| Scenes list | The user's configured automations/scenes/scripts (name + target brightness/K for the preview line). Run = `scene.turn_on` / `script.turn_on` / `automation.trigger` by type |
| All off | `scene.create` snapshot (`snapshot_entities`), then `light.turn_off` |
| Turn on | `scene.turn_on` of that snapshot |
| State | Subscribe to the group's state; an external change updates the knob and shows the reveal for 2.6 s (r2.2 rule) |

**Haptics (proposal, existing profiles only):** brightness BINARIS BEER (as volume); temperature and scenes MIDI SKIPPER, with bounds set per mode.

---

## 8. State
`space` (home · music · albums · explorer · tracks · upnext · windows · lights · scenes), `homeOption`, `homeDomain` (1b), `lastDomain` (1c), `lightsKnobMode` (bri · temp · scene), `bri`, `kelvin`, `on`, `sceneIndex`, `adjusted`, `pendingScene {i, at}`, `offSnapshot`, `seek`, `seekFrom`, `trackPos` (−1/0/1), `holdStartedAt`, `homeArrivedAt` (overshoot guard), `navigatorMode`, `lastInputAt`, plus the r2.2 music/window state.

## 9. Tokens
LCD and LED colours are r2.2: ink `#F2F2F2`, secondary `#A6A6A6`, meta `#7C7C7C`, disabled `#5A5A5A`, nav `#E6E6E6`, confirm `#6ED996`, cancel/error `#FF8474`, success `#7EE0A2`, warm `#FFBE69` / LED `255,190,105`, green LED `110,217,150`, red LED `255,60,40`, pink `255,40,90`. New: Kelvin colours (formula above); the Navigator glass values in §5.

## 10. Assets
`prototypes/assets/covers/` (sample album art) and `prototypes/assets/apps/` (sample app icons) are placeholders from r2.2. Icons are Lucide-style paths listed in §2.2 and in r2.2 spec 01.

## 11. Files
| File | What it is |
|---|---|
| `prototypes/Knob IA Prototype.dc.html` | **The r3 prototype** — knob, ring, buttons, 32:9 monitor with Navigator and the r2.2 overlays, all options switchable |
| `prototypes/support.js` | Runtime for the `.dc.html` prototype (do not port) |
| `prototypes/_ds/…/styles.css`, `_ds_bundle.js` | Page chrome styling for the prototype only |
| `prototypes/assets/` | Sample covers and app icons |
| `reference_r2.2/` | The complete r2.2 package: specs 01–05, `Browse and Snap.dc.html`, `knob-model.js`, icons. Source of truth for everything r3 does not change |

## 12. Open decisions
1. Home option: **1a** (recommended), 1b or 1c.
2. Lights option: **1e** (recommended) or 1d; if 1d, the auto-run delay (1.0 s vs 1.5 s vs press 4).
3. Breadcrumbs: **Arc** if LVGL can render it, otherwise v1 flat path + pips.
4. Whether All off should need a hold instead of a tap.
5. Whether Lights should show anything on the monitor beyond the Navigator.
6. r2.2 carry-overs: final Like pink, green breathing on the ring, knob text widths with the 48 px tabular font.
