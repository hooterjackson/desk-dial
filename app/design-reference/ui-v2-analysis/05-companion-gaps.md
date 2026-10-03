# 05 — Companion gap map: what desktop v7 must change for the master design

This is a read-only analysis, written 2026-09-25. Nothing was run except a static `ast`/regex scan of `tests/*.py` (Python from `.venv`, no imports of the app). No serial port, knob, Tk window, Sonos or Apple Music was touched.

**Subject:** the **companion** (desktop) code changes that the master handoff `design_handoff_nano_d_master` forces. They are listed per module, with file:line against the current tree (desktop v6 plus the in-progress ALIVE work).

**Target:** the one combined release, firmware 1.0.0-cc5.4 plus desktop v7. It carries ALIVE ("Warm · alive") and the whole master design.

**Companions to this file:**
- `01-knob-behaviour.md`: the knob's LCD, grammar and state machine.
- `02-leds.md`: LED recipes.
- `03-desktop.md`: the design-side numbers for the overlays, toasts, tray and settings. Its section numbers are cited as `03 §n`, and its Q-numbers as `03 Q<n>`.
- `check-seek.md`, `check-play-next.md`, `check-like.md`, `research-apple-music-play-next.md`: the Sonos and Apple Music feasibility checks.

This file does **not** repeat design numbers that 03 already extracts. It maps them onto code.

---

## 0. Conventions, sources, headline

### 0.1 Citation keys
| Key | File (under `app/` unless noted) |
|---|---|
| `CT:n` | `control_center/controller.py` |
| `RT:n` | `control_center/runtime.py` |
| `DV:n` | `control_center/device.py` |
| `PR:n` | `control_center/presentation.py` |
| `CA:n` | `control_center/carousel.py` |
| `CR:n` | `control_center/carousel_render.py` |
| `WN:n` | `control_center/windows.py` |
| `UI:n` | `control_center/ui.py` |
| `OV:n` | `control_center/overlay.py` (floating knob) |
| `AL:n` | `control_center/alive_lights.py` (in progress) |
| `SO:n` / `AM:n` / `AW:n` | `control_center/sonos.py` / `apple_music.py` / `artwork.py` |
| `SI:n` / `LP:n` | `control_center/simulation.py` / `lcd_preview.py` |
| `ST:n` | `standalone.py` (the tray lives here, **not** in `ui.py`; see §8) |
| `CAROUSEL §n`, `APP_ICON`, `FLOATING_KNOB`, `DESKTOP` | the companion docs |
| `ALIVE §n` | `firmware/ALIVE.md` |
| `R §n` / `S01 §n` | master `README.md` / `specs/01-FEATURES-explorers-snap-seek.md` |
| `B&S:Ln` | `prototypes/Browse and Snap.dc.html` |

### 0.2 Standing user decisions that shape the desktop work
- WARM is LED output #FF8424 all day. Volume 80–90 % is #FF3A0A, and ≥ 90 % is #FF0000. These live in the LED engine (`AL`, 02). The companion only feeds the engine.
- When the PC is away, the ring drains, then shows the amber marks, then the native profile lights take over. This is firmware only; the desktop simply hides (ALIVE §8.1).
- The floating knob runs the same choreography: `AliveLights` in `ui.py`/`overlay.py` (ALIVE §10.3).
- There is one combined release.
- Still standing from earlier releases:
  - no main window: tray plus floating knob (DESKTOP.md; `ST:1-16`);
  - the picker background is "full screen or not at all" (CAROUSEL §11);
  - Frosted / No background is a Settings choice (`UI:117`).

### 0.3 Headline
1. **The controller is the largest change.**
   - `button()` (`CT:528-638`) is a hard-coded v4 grammar. Button 2 opens Windows from any mode (`CT:531-535`), 1 is Browse/Home, 3 is Tracks/action, and Windows 1 is Cancel.
   - The master needs:
     - five new modes or sub-states: `explore`, `queue`, `seek`, plus snap state inside `windows` (and a Play-next state in `recent`);
     - a new button table;
     - hold-to-Home;
     - host-driven re-entries;
     - about ten new effect kinds;
     - a presentation contract bump for the new layouts, icons, tones and ring styles.
   - About **150 controller-level tests** press the remapped buttons or assert v4 legends (§11).
2. **The picker gains snapping.** The carousel stack (`CA`/`CR`) can host it with extensions. The biggest structural change is that the **host must grow from the pane to the monitor**, so the fly animation and the tray thumbnails can leave the pane.
   - Placement is new native code in `windows.py`.
   - The design's `ShowWindow(SW_RESTORE)` **activates** the target. That would trip the picker's own focus-loss dismissal (`WN:1700-1751`), so the build must use a non-activating restore (§6.4, risk R2).
3. **Music explorer and Up next can reuse the carousel stack's thread, windows, frost capture, text engine, tweens, pacer and toast.** They cannot reuse its activatable host, its DWM-thumbnail cards or its pane-sized chrome.
   - What is genuinely new:
     - cover rendering on the CPU (a 680 px centre card at k = 2), or a DWM-thumbnail trick;
     - the ambient layer;
     - tabs, hints, rows, mosaics and staggered motion;
     - a new data pipeline: 600 px covers, Favourite playlists, the full Sonos queue with metadata, and ratings.
   - The recommended shape is **one shared "desktop stage" engine with three scenes**, so the toast rule ("never over an overlay") is enforced in one place (§5.1).
4. **The toast becomes a service** used by knob actions, not only by picker exits. The mechanics exist (`CA:427-473`, `CA:1625-1691`). The position, tint, hold, copy and owner change (§7).
5. **The tray already does light/dark and connected/missing** (`ST:389-425`, `ST:710-761`). The only gap is event-driven theme switching (`WM_SETTINGCHANGE` "ImmersiveColorSet") instead of the 2 s poll. That is a one-handler change in pystray's `_message_handlers` (§8).
6. **Settings and recovery**: the design's main window, recovery cards and new Settings layout conflict with the no-main-window decision. The recommendation is a service strip at the top of Settings, plus a few label changes (§9).

---

## 1. Target flow: who does what in v7

| Layer | v6 today | v7 needs |
|---|---|---|
| Firmware ↔ `device.py` | `kd` down edges only (`DV:843-852`). F24 from the `windowsButton` slot in every mode (01 §8 row 2). | Hold-600 event, or `ku` up edges forwarded; the ALIVE `lim` event (ALIVE §3); an F24 that fires only on Home (slot 4, `win` icon); contract v5 fields (§4). |
| `runtime.py` | Routes `kd` to `controller.button`, skipping logical 2 while F24 is registered (`RT:1384-1390`). `hotkey()` calls `button(2)` (`RT:1088-1096`). | Skip logical **3 on Home only**. `hotkey()` calls `open_windows()`. New lanes and effects: seek, play_next, queue, shuffle, jump, like, playlists, snap, overlay effects and toasts (§3). |
| `controller.py` | Four modes (`CT:36-37`) and the v4 grammar. | Seven presentation states, the master grammar, hold, timers, re-entries (§2). |
| Providers | Sonos (read, volume, transport, replace queue), Apple (Recent pages, resolve), Windows (snapshot, show, activate, cancel, highlight). | Sonos: queue read, Play next, jump, shuffle, seek, neighbour titles, duration. Apple: playlists, ratings, extra metadata. Windows: snap placement. A **stage presenter**: explorer, Up next, picker, toasts (§5–§7). |
| UI (`ui.py`, `standalone.py`) | Floating knob suppression `disconnected` / `picker` / `carousel` (`UI:1211-1219`); tray; Settings. | Suppression for the new overlays, capture exclusions for the new frost, the tray theme event, the Settings service strip and labels (§8–§10). |

---

## 2. `controller.py`: button grammar, modes and frames

### 2.1 Modes, profiles and bounds
| Item | Today | v7 change |
|---|---|---|
| `Screen.mode` values | `volume / recent / tracks / windows` (`CT:90`, `CT:999`) | Add `explore` (the explorer is on screen), `queue` (Up next is on screen) and `seek` (a Tracks sub-state with its own control). Snap state goes into `screen.windows` (§2.6). |
| `PROFILES` (`CT:36-37`) | 4 entries | Add `seek: "BINARIS BEER"`, `explore: "MIDI SKIPPER"` and `queue: "MIDI SKIPPER"` (R §3). `control()` indexes `PROFILES[self.screen.mode]` (`CT:313`), so a missing key is a `KeyError` on the first entry. |
| `bounds()` (`CT:318-323`) | volume 0..100; tracks 0..2; else 0..len(items)−1 | seek: `0..P`, entry `p0` (01 §2 mapping). explore: 0..n−1 of the **active source**. queue: 0..rows−1 (entry = the now-playing row). |
| `items()` (`CT:344-354`) | windows snapshot; Recent page + a synthetic `__more__` | explore: the active source's list (Recent pages flattened, or the playlists list; see D1). queue: the queue rows. |
| `mode_title` (`CT:999`) | dict with 4 keys | New keys, or `KeyError`. These are legacy fields, but they are still built on every frame. |
| `ui._render_panel` (`UI:1002-1005`, `UI:1021`) | a descriptions dict and `PROFILES[mode]` | Same `KeyError` risk in the chrome=True dev window. It needs entries for the new modes. |

### 2.2 The button table: today against the master
Today (`CT:528-638`, legends at `CT:979-981`, icons at `CT:38-41`):

| Mode | 1 (index 0) | 2 (index 1) | 3 (index 2) | 4 (index 3) |
|---|---|---|---|---|
| Home | Play/Pause (`CT:545-557`) | Browse → Recent (`CT:537-540`) | **Windows, from any mode** (`CT:531-535`) | Tracks (`CT:588-592`) |
| Recent | Back: pages back, else Home (`CT:562-584`) | Home (`CT:541-542`) | Windows | Play / More (`CT:601-634`) |
| Tracks | Home | Home | Windows | Prev/Next skip (`CT:593-600`) |
| Windows | **Cancel** (red, `stop` tone) (`CT:558-561`) | Home → `windows_cancel(home=True)` (`CT:645-647`) | (ignored: already open) | Switch (`CT:635-638`) |

Master (R §4; S01 §2). Each change is noted as **new** or **changed**:

| Mode | 1 | 2 | 3 | 4 | Code impact |
|---|---|---|---|---|---|
| Home | Play/Pause | Browse music → Recent | **Tracks** (changed: was 4) | **Windows** (changed: was 3; F24 + serial fallback) | Swap the branches `CT:588-592` and `CT:531-535`. Windows becomes a new `open_windows()`, reachable **only** from `volume`. |
| Recent | Back → Home (disabled while Play is pending, as `CT:562-563`; the page-back of `CT:564-582` is decision D1) | **Open on screen** → `explore` (new) | **Play next** (new effect `play_next`) | Play (More: D1) | New branches. Remove the Windows entry. |
| Explorer | Back → `recent` at the explorer's Recently Added index (S01 §2; 01 §6 item 13) | Tab Recently Added | Tab Favourite playlists | Play (library item or playlist) | New. Tab switch = re-entry with the source's bounds and remembered index (§2.5). |
| Tracks | Back → Home. **In Seek, Back exits Seek first** (01 §4.1 row 21). | **Open on screen** → `queue` (exits Seek first) | **Seek** toggle (new control, BINARIS BEER) | Skip by position; `dim` at Neutral and while seeking | New Seek sub-state. The skip logic stays (`CT:593-600`). |
| Up next | Back → `tracks` (Neutral) | Shuffle (new `shuffle` effect) | Like (new `like` effect; fallback D6) | Play = jump to the row (new `jump` effect) → Home | New. |
| Windows | **Back** (changed from Cancel: warm `nav`, no red) → restores focus; toast only when nothing was snapped | **Snap left** (new) | **Snap right** (new) | Switch (`check` icon) | Replace the `CT:558-561` Cancel with Back. New snap branches (§2.6). |
| any | **Hold 1 for ≥ 600 ms → Home** (new) | | | | New `hold_home()`; see §2.3. |

Knock-on effects in the same function:
- `self.windows_button = 2` (`CT:139`) → **3**. `runtime` also sets it from `button_order[2]` → `button_order[3]` (`RT:1356`; `UI:799`). It travels in every control as `windowsButton` (`CT:315`) and tells the firmware which slot sends F24. The firmware must also gate F24 to Home (01 §8 row 2).
- `home()` (`CT:644-649`): Windows is now entered only from Home, so `origin` always equals a Home screen. Recommendation: keep `origin` for Home's own state (a pending Home play/pause or volume write can still complete while the picker is open, `CT:755-760`). The **Recent/Tracks resume paths are dead code** after v7: `_resume_screen` Recent reload (`CT:659-666`); the suspended-origin branches for play and skip (`CT:813-817`, `CT:867-875`); `_leave_windows` restoring a non-Home origin (`CT:910-918`); `dismiss_windows` restoring origin (`CT:651-657`). Simplify them, or leave them unreachable and keep their tests (§11 says which).

### 2.3 Back, Home and hold
- **Back is "up one level"** (S01 §2 "Back targets"):
  - Recent → Home;
  - Explorer → Recent;
  - Tracks → Home;
  - Seek → Tracks (Neutral);
  - Up next → Tracks;
  - Windows → Home.

  Implement it as a per-mode `back()` table instead of today's mixed `index == 0` branches (`CT:544-585`).
- **Hold 600 ms = Home** is not prototyped (01 §4.4). Recommendation (01 §4.4): the press edge acts at once (Back, or Play/Pause on Home); if the button is still held at 600 ms, go on to Home. That makes the hold monotone: Seek → Tracks → Home, Explorer → Recent → Home, and so on.
- **Plumbing today cannot carry a hold:**
  - `device._consume` clears `_pressed` on `ku` but emits **no event** for it (`DV:843-852`).
  - `runtime._device_events` already has a dead branch for up edges (`RT:1372-1375`), which only discards from `held`.
- **Options:**
  - **(a) Firmware hold (recommended in 01):** AceButton long-press, sent as e.g. `{"id": n, "kh": 0}`. `DV:_consume` emits `{"kind": "hold", "button": 0}`, and `RT` maps it through `button_order` to `controller.hold(logical)`.
  - **(b) Host timing:** `DV` emits up edges, and `RT.poll` fires once when `now − down_at[0] ≥ 0.6` while the button is still held. Serial latency jitter lands in the threshold.
- **`hold_home()` per mode:**

  | Mode | Action |
  |---|---|
  | windows | `windows_cancel(home=True)` (today's `home()`, `CT:645-646`) |
  | explore / queue | an `overlay_close` effect, then Home |
  | seek | exit Seek, then Home |
  | Recent while a play is pending | blocked, like Back (no undo, `CT:562-563`) |
  | Home | no-op |

### 2.4 Host-driven re-entries (absolute positions stay authoritative)
Each of these moves the knob's index without a detent. Each therefore needs `_enter()` (a new control id) with the new `position` and `max`, and never restarts the haptic profile in the firmware (`CT:1-5`; 01 §2):
- the explorer tab switch (new bounds and the remembered index);
- Back from the explorer (Recent at the explorer's index);
- opening Up next on the now-playing row;
- Shuffle moving the focus to `qNow + 1`;
- Seek entry and exit (a profile swap);
- snap auto-advance at 420 ms;
- a Play-next insertion that shifts Up next rows (only if Up next is open; see §5.7).

Today the only host-driven re-entries are page changes (`CT:270-277`, `CT:575-582`) and a Tracks skip (`CT:860-863`), so the mechanism exists.

### 2.5 Timers the controller must own (all in `tick()`, `CT:674-682`, with the injected clock)
| Timer | Value | Source |
|---|---|---|
| Seek send | 250 ms after the last Seek detent, latest wins | R §8; check-seek §4.4 |
| Seek idle exit | 3 s after entry or the last detent | R §8; B&S:L664 |
| `Queued next` meta | 1.5 s | S01 §6; B&S:L964 |
| Snap auto-advance | 420 ms after the snap's start | B&S:L854-855 |
| Snap pair close | 820 ms after the second snap | B&S:L851-852 |
| Explorer tab-switch swap | 190 ms (presentation only; the re-entry can be immediate, §5.6) | B&S:L808 |
| Explorer / Up next Play close | 380 ms (the overlay's), then Home | B&S:L696, L813 |
| Hold | 600 ms (only if host timing, option b) | R §4 |

The paused-idle (`CT:44`) and volume-reveal (`CT:42-43`) timers are unchanged.

### 2.6 New effects (the controller → runtime contract)
| Effect kind | Payload | Lane / thread | Completion → controller | Notes |
|---|---|---|---|---|
| `explore_open` / `explore_close` / `explore_source` / `explore_highlight` | model: items per source + index | Tk thread, synchronous like `windows_*` (`RT:1192-1209`) | open ok → mode `explore`; error → stay in Recent + `err` flash | The presenter must refuse to open without data (03 Q5) |
| `playlists` | cursor/page | library lane (`RT:1221`) | the Favourite playlists list | New Apple API call (check-like §2.4) |
| `play_next` | item + group rev + track id | library lane (resolve), then the audio lane, like `play` (`RT:1214-1217`, `RT:1146-1156`) | ok → `Queued next` 1.5 s + Sweep (needs a new frame trigger, 02 §6.4) + toast; err → Head shake + copy | check-play-next §4.1 recipe; refuse unless the queue is the source and shuffle is off |
| `seek` | target s, group rev, track id | audio lane; the intent is read at job start (as volume, `RT:1103-1117`) | state; ok/err | check-seek §4.4; add to `invalidate_actions` (`RT:1165`) and `obsolete_group` (`CT:764`) |
| `queue` | window (start, count) | audio lane | rows + position + revision | `SO:_queue` (`SO:308-321`) is full-read only, capped at 5000 |
| `queue_open` / `queue_close` / `queue_highlight` | rows, qNow, context | Tk thread | as explore | |
| `shuffle` | on/off + revision | audio lane | reordered rows | Semantics undecided (D5) |
| `jump` | row index + revision + track id | audio lane | state → Home | SoCo `play_from_queue` = SeekTrackNr + Play |
| `like` | catalog song id, on/off | library lane (Apple **write**) | heart state; err → Head shake; 401/403 → `music_signin_expired` | check-like §4; `AM._get` is GET-only (`AM:90-123`) |
| `windows_snap` | item, side, snap state | Tk thread, synchronous (like `windows_activate`) | placed / failed(reason) | §6 |
| `windows_close_pair` | left, right | Tk thread | Home + toast | §6.5 |
| `toast` | text | Tk thread → stage | none | §7; never for Play/Pause |

`invalidate_actions` (`RT:1158-1174`) drops only `volume / transport / play`. Add `seek`, `play_next`, `shuffle`, `jump` and `like` (never replayed after a reconnect, `specs/03-SCREEN-and-state.md:227-229`).

### 2.7 Frame projection (`_frame`, `CT:941-1214`)
Knob layouts and copy are 01's. This is only the code map:
- **Legends and icons.**
  - `BUTTON_ICONS` (`CT:38-41`) lacks `expand clock list-music list-plus seek shuffle heart snap-left snap-right check skip-back note` (R §4 icon table; 03 App. A).
  - `win`, `back`, `play` and `list` change paths; `list` changes **meaning**: it was Browse, it becomes Tracks (01 §8 row 1).
  - Button labels are capped at 16 bytes (`PR:72`). "Favourite playlists" is 19, so use short labels such as `Playlists`.
- **Tones.**
  - `button_tone(slot, icon, enabled)` (`PR:156-165`) knows `none/dim/stop/go/nav` only.
  - The master needs `on` (warm 1.0), `off` (warm 0.30), a custom colour (pink 255,40,90 for Like; the app colour for a filled snap side) and "only slot 4 is green" (R §6). Separately, the paused Play breathes green on slot 1 (01 §6 item 16).
  - This needs **per-button tone/accent fields in the frame**. The tone function cannot derive "pair active/inactive" from (slot, icon, enabled) (01 §8 row 10).
  - `TONE_COLORS` (`CT:32`) and the `color` per button (`CT:996-997`) follow.
- **Layouts and headings.**
  - `LAYOUTS` (`PR:57`) gains `seek`.
  - The list mirrors can reuse `recent`, with headings `RECENT · SCREEN` / `PLAYLISTS · SCREEN` / `UP NEXT · SCREEN` (these fit `heading` capacity 32, `PR:71`).
  - The Windows meta adds `Left: {App} · pick right`. It needs the display app name, which today lives only in the adapter's labels (`WN:1996-2035`); the frame uses the exe stem `item["app"]` (`CT:1188`). Route the label's `app` into the snapshot items, or decorate it in the runtime.
- **Rings.**
  - `RING_STYLES` (`PR:62`) has no song lap for Seek.
  - The selection ring has no per-entry levels for Up next (played 0.14 / now 0.70 / upcoming 0.45; R §6).
  - Both are contract additions (01 §8 rows 15–16; 02). `_list_ring` (`CT:1240-1260`) grows a `levels` or `played`/`now` field.
- **Copy removed or changed** (01 §8 rows 11, 12, 28):
  - `· Replaces queue`, `Loads, doesn't play`, `RECENTLY ADDED · P{n}` (D1);
  - `Skipped · back at neutral`;
  - `Turn to preview · Green to switch`.

  `_REPLACEABLE_STATUSES` and `quiet_statuses` (`CT:53-55`, `CT:1042-1043`) list those strings.
- **The contract version.**
  - `PRESENTATION_VERSION = 4` (`PR:10`).
  - The new tokens need a capability (e.g. presentation 5, or `grammar: 2`). `device._buttons` would otherwise **strip unknown icons to ""** (`DV:227-231`), which hides the footer glyph and turns the LED off.
  - **Decision D8:** a v7 host with a cc5.3 knob either (i) maps new tokens to the nearest legacy glyphs in `device.py`, keeping one controller, or (ii) refuses control with "Update the knob firmware". Recommended: (i).

### 2.8 Pending and optimistic behaviour
The prototype is optimistic: Play and Switch act at once. The companion confirms (`CT:629-634`, `CT:896-906`). Keep confirmation (01 §5.2, 03).

Consequences for the overlays:
- Explorer and Up next Play animate and close at 380 ms whatever the outcome.
- The knob shows `Starting…` with the Working comet until `ok`, then goes Home with the Wash.
- The toast is sent **on success only**.
- A failure plays the Head shake and becomes a tray balloon, as `notice` does today (`ST:671-708`).

---

## 3. `runtime.py`

| Area | Today | Change |
|---|---|---|
| F24 path | `hotkey()` → `controller.button(2)` (`RT:1088-1096`) | → `controller.open_windows()`, a no-op unless mode is `volume`. Still synchronous inside WM_HOTKEY (the foreground grant). |
| Serial skip | Skip logical 2 whenever the hotkey is supported (`RT:1384-1390`) | Skip **logical 3 when mode is `volume`** and the hotkey is supported. **Race analysis (R1):** if F24 wins, the picker's `_enter()` gives a new control id, and the late `kd` (old id) is dropped by `DV:834-835` and `CT:529`. If the serial edge wins, it is skipped on Home. Safer: the firmware tags a `kd` that also sent F24 (`"hid":1`), and the host skips exactly those. |
| `windows_button` | `= button_order[2]` on connect (`RT:1356`) and in `UI:799` | `button_order[3]` |
| New device events | — | `hold` (§2.3); `limit` (ALIVE `lim`): `note_touch("limit")`, overlay end bumps, `AliveLights.limit`. |
| `dispatch()` | `windows_*` synchronous; others on lanes (`RT:1184-1223`) | New synchronous kinds: `explore_*`, `queue_*`, `windows_snap`, `windows_close_pair`, `toast`. New lane kinds per §2.6. |
| `_background()` | state, volume, transport, recent (`RT:1098-1139`) | seek, play_next (via `_resolved`-style chaining), queue, shuffle, jump, like, playlists |
| `invalidate_actions()` | 3 kinds (`RT:1165`) | + seek, play_next, shuffle, jump, like |
| `_note_library()` | Sign-in state from `recent` results only (`RT:955-964`) | Also `playlists` and `like` results (check-like §4.3) |
| Disconnect | `windows.hide()` only (`RT:1391-1399`) | Also close the explorer, Up next and any toast |
| Art identity | Recent item, else playing (`RT:291-303`); `ART_LAYOUTS` (`RT:65`) | explore: the focused item's cover (a playlist's first mosaic cover); queue: the focused row's cover; seek: now playing (per 01) |
| Ring colours | `_decorate_colors`: `kind = "window" if windows else "recent"` (`RT:475`) | Per-source accent keys: `recent`, `playlist`, `queue` (album of the row), `window` |
| Accents | Recent page URLs and window icons (`RT:485-550`) | Playlist colour (03 Q6: the first cover), queue rows (album art per row) |
| Knob covers (artwork2) | Recent page by distance, then now playing, then the warm-up (`RT:682-718`) | explore and queue mirrors by distance |
| Progress / duration | `position` string only (`SO:202`) | ALIVE §10.2 `progress`, plus the Seek model: parse `duration` and `position` (check-seek §1 caveat 2) |
| Toast routing | none (the picker toasts itself) | `toast` effects → the stage presenter (§7) |

---

## 4. `device.py` (host validator and serial events)

- **`_consume`** (`DV:803-852`):
  - forward `ku` (option b), or a new `kh` hold message (option a);
  - parse ALIVE `lim` → emit `{"kind": "limit", "direction": ±1}`;
  - optionally parse a `hid` flag on `kd` (R1).
- **`_buttons`** (`DV:214-248`) validates `icon in presentation.ICONS` (`DV:228`). Add:
  - the new tokens;
  - per-button `tone` / `accent` fields, gated by capability;
  - the legacy downgrade table (D8).
- **`_ring`** (`DV:251-312`):
  - `value` is limited to 0..100 (`DV:253`);
  - a song-lap ring needs index/count in seconds (≤ 65 535; check-seek §4.5) or a new style;
  - Up next levels need a new window-relative field, with the same "relative to first" validation as `colors`/`unavailable` (`DV:290-301`).
- **`_optional`** (`DV:315-346`): new layout `seek`; `feedback.kind` values (today `ok`/`err`, `DV:343`) may gain moment hints (skip is ALIVE's; queued/like/scatter/half are 02's call).
- **`_KNOWN_FIELDS`** (`DV:110-112`) and `_slim` (`DV:349-370`) get new fields and defaults.
- **Budget:** `FRAME_BUDGET_BYTES = 1100` (`PR:74`). Per-button tones (4 × ~15 B), Up next levels (20 entries, e.g. a 40-bit mask) and ALIVE's latched fields must all fit. Record the worst case in tests (ALIVE §3 already asks this for its fields).
- **`_enter`** (`DV:929-970`): `windowsButton` is validated 0..3 (`DV:947`). No change unless the firmware wants an explicit "F24 on Home only" flag.
- **Parity:** the firmware parser and `device.py` must accept and reject identically (ALIVE §3). This extends `tests/fixtures/frames_v4.json` / `cc5_frames.json` and the parity suites (§11).

---

## 5. Music explorer and Up next overlays

### 5.1 Can they reuse the carousel stack? Piece by piece
| Carousel piece | Where | Reuse for the explorer / Up next | Change needed |
|---|---|---|---|
| Thread + Win32 skeleton (dedicated thread, PMv2 per thread, module WNDPROC thunk, `Mailbox`, `_Status`, `_Log`) | `CA:549-657`, `CA:1904-1942`, `CA:2675-2830` | **Yes** | The mailbox needs scene requests (`OpenRequest` has picker fields only, `CA:525`) |
| `CubicBezier`, `EASE_OUT`, `SPRING`, `Tween` | `CA:104-175` | **Yes** | Add `HEART = (0.34,1.6,0.64,1)` and CSS `ease` (03 §0). `Tween.retarget` has **no delay** (`CA:158-167`), so staggers need a start-delay parameter (45·a ms explorer, 40·a ms Up next) |
| `Pacer` (DwmFlush) | `CA:476-520` | **Yes** | — |
| `CaptureWorker` + `frost_canvas` | `CA:686-770`, `CR:341-350` | **Yes** | The recipe is hard-coded: blur via `frost_sigma`, `_SATURATE` 1.8, `_GLASS_TINT` (18,18,20,.58) with the 0.88 dim (`CR:115-127`, `CR:312-326`). Parametrise per scene: explorer σ 36·k/8, saturate 1.3, tint (8,8,10,.50); Up next the same with .55; picker 40·k/8, 1.6, (10,10,12,.50), **no dim**, plus a 6 % sheen to 30 % H (03 §1.2) |
| Glass window (monitor-sized, click-through ULW, constant-alpha fade, `release_retained`) | `CA:2463-2486`, `CA:2516-2556`; CAROUSEL §11 | **Yes** (the frost) | The fade is 340 ms for explorer / Up next (B&S:L103, L154) against the picker's 280 ms (`CA:182`) |
| Dim window | `CA:2445-2461` | Not used (no dim in the master) | — |
| **Host** (activatable, NOREDIRECTIONBITMAP, **pane-sized**, thumbnail destination, eats clicks) | `CA:1774`, `CA:2049-2053`, `CA:2125-2166`, `CA:2260-2269` | **No** for explorer / Up next: they must never take focus (R §7.1) | A new non-activating role: `WS_EX_NOACTIVATE | TOPMOST | TOOLWINDOW | LAYERED`, **without** `WS_EX_TRANSPARENT`, returning `MA_NOACTIVATEANDEAT`. It eats clicks without activating (03 Q12). The floating knob proves a background process may show a topmost non-activating window (`OV:206`) |
| Chrome (layered, pane + 16 px margin) | `CA:2428-2443`; `CR:199-202` | Partly | The explorer tabs (top 44) and hints (top 664) fall outside the pane (70..1210 × 92..652, `CR:71`), so the chrome must span the **stage** (1280 × 720 · k = 14.7 MB at k = 2). `ChromeScene` (`CR:1420-1430`) is card-specific |
| Toast window + `ToastMachine` | `CA:427-473`, `CA:814-828`, `CA:1625-1691`, `CR:1316-1385` | **Yes** | §7 |
| Display affinity + `set_capture_exclusions` | `CA:2308-2345`; `UI:1517-1538` | **Yes** | The new captures must exclude the floating knob too (`UI:_sync_capture_exclusions`) |
| `TextEngine` (Archivo + fallbacks, fit, ellipsis) | `CR:926-1053` | **Yes** | New sizes and weights: 30/36 600, 17/22, 14/18, 13 caps 600 at 0.12 em, 22/26 600, 12 caps 600 at 0.08 em, 20 px tabular numbers (Archivo `tnum`? PIL cannot select OpenType features without raqm; use fixed digit cells) |
| `ShadowCache` | `CR:662-790` | **Yes**, generalised | Today it is keyed on picker `CARD_SHADOWS` (`CR:101-104`) and interpolates centre/side by `selw`. New sets: explorer `0 40 80 .55` / `0 16 36 .4`; Up next focused row `0 20 50 .35`; cover `0 40 80 .55`; fly `0 30 70 .45` |
| `_SpriteScaler` (BILINEAR while animating, LANCZOS at rest, LRU 48) | `CR:1433-1481` | **Yes** | Cover sprites are large. Raise the limit, or quantise scales |
| `render_dots` | `CR:1280-1312` | Partly | The master dots are **square, opacity .5, no shadow** (03 §1.3); today they are radius 3 (`CR:1297`) with a shadow (`CR:1305`). Add a style parameter (the picker changes too, §6.1) |
| `CarouselMachine` / `_CardTweens` | `CA:224-424` | Pattern only | Its table is the picker's (`CR:77-78`, `CR:232-236`), its open has no motion (`CA:286-306`), and its exits are picker-specific. Write `CoverRowMachine` (horizontal, explorer table, stagger, source switch, Play grow 1.12) and `QueueListMachine` (vertical, QY/QS table, played ×0.6, shuffle refade, Play 1.06) on the same Tween base |
| DWM thumbnails | `CA:2565-2595` | Not for covers (they are bitmaps) | Optional GPU-scaling trick: §5.4 option B |

**Conclusion.** Reuse the stack, but not by opening a second `CarouselPresenter`. Make the NanoD-carousel thread a **shared "desktop stage"** with three scenes:
- `picker` (today's session);
- `explorer`;
- `queue`;

plus the toast service.

Why:
- the three overlays are mutually exclusive by knob mode;
- one thread and window set bounds memory (CAROUSEL §5's 80 MB budget);
- the toast rule is naturally enforced: `_open` already ends any toast (`CA:1046`).

Proposed files:
- `stage.py`: the engine, mailbox, backend and presenter facade, moved from `carousel.py`;
- `stage_render.py`: the shared render helpers, moved from `carousel_render.py`;
- `scene_picker.py`: today's machine and compose;
- `scene_music.py`: the explorer and Up next machines;
- `render_music.py`: covers, mosaics, rows, tabs and hints.

A lower-churn alternative: keep the module names, add `scene` to `_Session` / `OpenRequest`, and put the new rendering in `explorer_render.py`.

Either way the facade must be **one object shared by two adapters**:
- `WindowsAdapter`, through the `PickerOverlay` factory (`WN:1555-1565`);
- a new `MusicOverlayAdapter`, built in `ui.providers` (`UI:740-758`).

### 5.2 What must be built new (rendering)
All numbers are 03's, with design px mapped through `Layout.k` (`CR:179-229`).

1. **Explorer cards** (03 §2.3–§2.4):
   - 340 × 340; 680 px at k = 2;
   - table offsets ±300 / 470 / 590 / 660, scales .60 / .42 / .30 / .22, opacities .92 / .55 / 0;
   - shade `#0b0b0c` at `min(.6, .24a)`;
   - a 1 px inset at 12 % white;
   - no badge, outline or text.

   The centre (640, 318) is a new `card_rect` variant: today's card_rect uses the picker constants and pane-local points (`CR:276-283`).
2. **Playlist mosaic:** 2 × 2 of 170 px tiles (340 px at k = 2 each), composited **once per playlist** on a worker. The first 4 distinct albums (03 Q6).
3. **Ambient layer:** the focused cover, box inflated by 160 px, blur 90, saturate 1.5, opacity .50 (explorer) or .45 (Up next), 600 ms `ease` crossfade (03 §1.2). New: §5.4.
4. **Tabs** (03 §2.2):
   - key box 18 × 18, 18 px Lucide icon, 17 px 600 label;
   - colour `#fff` against `.55`, 240 ms `ease`;
   - the underline grows from the centre over 320 ms OUT.
5. **Label** at top 514 (title 30/36 600, sub 17/22 .9, meta 14/18 .72). It fades over 180 ms during a source switch.
6. **Dots** at top 622, and the **hint row** at top 664: key boxes 16 × 16 with a 1 px .6 border, 10 px 700 digit, 13 px .8 labels, gap 28 (03 §1.3).
7. **Up next left column** (03 §3.2):
   - 380 px cover, shadow 40/80 plus the inset, 420 ms `ease` crossfade (two sprites blended);
   - `UP NEXT` caption, title, sub and shuffle line (16 px icon + text, colour tween).
8. **Up next rows** (03 §3.3):
   - 88 px tall, 560 wide at x 600, scaled around their left-middle point;
   - table offsets ±100 / 176 / 236 / 284, scales .78 / .66 / .58 / .52, opacities .72 / .46 / .24 / 0; played rows ×0.6;
   - focused row: 14 % fill, 28 % inset, 20/50 shadow;
   - lead: a 56 px cover **or** the 2-digit track number;
   - title 22/26 600; sub 14/18 .82;
   - tag 12 caps, `#6ED996` for Now playing;
   - heart 20 px `#ff2a5a` with a HEART-curve pop.

   Pre-render each row once per k as a sprite. The tag and heart are separate sprites.
9. **Icons for the overlays** (tabs, hints, shuffle, heart, snap halves, the chip): there is no vector renderer in the Python stack. Today's LCD icons are pre-exported PNG/SVG masks (`assets/handoff-icons`, `assets/lcd-icons`, generated by `harness/export_handoff_icons.cjs`). Export the new `I` / `HALF` paths (B&S:L395-L405; 03 App. A) at 16/18/20/34 px × k ∈ {1, 1.5, 2, 3}, or add a small SVG-path rasteriser.
10. **Motion** (03 §2.6, §3.4):
    - open stagger;
    - turn 420 ms (spec; not the prototype's delayed transition; 03 Q1);
    - end bump 14 px (explorer X, Up next Y);
    - source switch: drop 160/180 ms, then stagger in;
    - shuffle: fade 160 ms, then restagger;
    - Play grow, and the overlay fade 340 ms at 380 ms.

### 5.3 Data pipeline (new)
| Need | Today | New |
|---|---|---|
| Overlay covers | 480 px Apple template for the LCD, plus a **scrimmed** 480 px JPEG for the floating knob (`AW:52`, `AW:255-270`) | Unscrimmed covers at `ceil(340·k)` px (explorer) and `ceil(380·k)` (Up next). The Apple template takes any size (`AW:110`). Items keep `_resource` with the artwork template (`AM:277`), so no extra API call is needed. An `ArtworkService` variant with its own cache: 680 px RGBA ≈ 1.85 MB each, so cap it at the visible ±3 plus the mosaics |
| Album year and track count | Not parsed (`AM:266-277`) | Library-album attributes include `releaseDate` and `trackCount` (Apple docs). Add them to the item dict |
| Playlist song count and duration, mosaic albums | — | A library-playlist tracks fetch (`AM:_collection`, `AM:282-294`), summing `durationInMillis`. Heavy for long playlists: cache per playlist and revision |
| Favourite playlists list | — | `GET /v1/me/library/playlists` filtered on `inFavorites` (check-like §2.4); verify first. Empty source: 03 Q5 |
| Queue rows (Up next) | `get_queue(0,1)` for counts (`SO:183`); the full `_queue` for replacement (`SO:308-321`) | A **windowed** read around `playlist_position` (e.g. P−50..P+100, pages of 100). Per row: title, artist, album, `album_art_uri` → `sonos_artwork_url` (`AW:99`), `_song_id` (`SO:63-68`), original track number. Re-read on `queue_revision` change (`SO:200`) |
| Liked state | — | `GET /v1/me/ratings/songs?ids=` in chunks (check-like §4.1) |
| Neighbour titles for the Tracks LCD (`Next: …` / `Prev: …`) | — | `get_queue(P, 1)` and `get_queue(P−2, 1)`. **Do not add them to the 1 s state poll** (`CT:680-682`). Cache them per (queue revision, position) |
| Row covers 56 px | — | Downscaled from the row's cover. Sonos `getaa` sizes vary, so prefer the Apple catalog template when `_song_id` exists (one batched `GET /v1/catalog/{sf}/songs?ids=` also gives album names and `inFavorites`) |

### 5.4 The ambient layer and memory (the one open technical choice)
- **A. Composite into the frost.** On every focus change, build `frost ⊕ ambient` and crossfade two monitor-sized glass ULWs.
  - At 5120 × 1440 that is 2 × 29.5 MB retained, plus the 14.7 MB stage chrome, plus a 29.5 MB build buffer: about **104 MB peak**, over CAROUSEL §5's 80 MB.
  - It also costs one 29.5 MB `UpdateLayeredWindow` per detent (a detent every ~50 ms on a fast turn), so throttle it to the resting item.
- **B. The DWM stretch trick (spike).** Render frost + ambient at 1/8 scale into a small hidden source window. Let a `DwmRegisterThumbnail` on a monitor-sized NOREDIRECTIONBITMAP host stretch it. Crossfade two thumbnails with `DWM_TNP_OPACITY`.
  - Blurred content survives bilinear stretching, the memory is tiny, and the scaling runs on the GPU.
  - Unvalidated: that an off-screen or cloaked source keeps rendering thumbnails. The same trick could shrink v6's frost upload (03 §10.2 item 4).
- **Recommendation:** spike B; fall back to A with the ambient updated only after 150 ms of rest.

### 5.5 Frame cost (to measure; the CAROUSEL §10 style supervised check)
- The picker's card pixels are DWM thumbnails (GPU).
- The explorer's are CPU sprites. At k = 2, a moving frame resizes up to 5 covers (680 / 408 / 286 px) and pastes them premultiplied into a 14.7 MB chrome, then uploads it with ULW.
- Expect 15–25 ms per frame (an estimate, not measured).

Mitigations:
- quantised scale steps in `_SpriteScaler`;
- `UpdateLayeredWindowIndirect` with `prcDirty`;
- or covers as DWM thumbnails of hidden source windows (the picker's own pipeline).

`compose_ms` / `compose_ms_max` already exist (`CA:1408-1410`).

### 5.6 Knob coupling
- **Tab switch.** The controller switches the source and re-enters **at once**, with the remembered index. The presenter plays the drop and stagger, and shows the newest index when the stagger starts.
  - The prototype ignores turns during the 190 ms fade (B&S:L706).
  - The companion must **record** them (absolute positions, `CT:498-522`) and only defer the presentation. Otherwise the knob and the screen desync.
- **Play animation.** The same rule applies during the Play animation (380 ms).
- **Clicks.** Side-card and row clicks must not select: they would desync the knob, like picker deviation 5 (CAROUSEL §9). Decide per 03 Q12.

### 5.7 Lifecycle rules not in the design (recommended)
- Close the explorer or Up next on:
  - a knob disconnect (as `RT:1398` does for the picker);
  - a Sonos group change;
  - an external foreground change. Reuse the adapter's WinEvent hook (`WN:533-566`, `WN:1700-1710`), routed to a new `on_music_overlay_focus_lost`.
- **Full-screen D3D or presentation mode:** do not open over it. The floating knob already reads `SHQueryUserNotificationState` 3/4 (`OV:105`; FLOATING_KNOB §4).
- **Floating knob:** suppress it while either overlay is open, with new reasons `explorer` / `queue` in `UI:_update_suppression` (`UI:1211-1219`). `set_suppressed` takes any reason string (`OV:1588-1610`). This follows 03 Q18.
- **Queue changes while Up next is open:** re-read, keep the focus by song id, and re-enter the knob if the index moved.

---

## 6. Window picker V2 and snapping

### 6.1 Presentation deltas in `carousel_render.py` / `carousel.py`
03 §9.1 rows P1–P21 hold the values. Code locations:

| Delta | Code |
|---|---|
| Card 480 × 300 → **400 × 250**; centre y 300 → **370**, or 326 with the tray hidden | `CR:72-73`; `card_rect` `CR:276-283` gains a y offset |
| Offsets 320/460/560/620 → **280/400/490/540** | `TABLE` `CR:77-78` |
| Badge 32/inset 14 → **30/12** | `CR:86`, used at `CR:1606-1607` |
| Label top 476 → **512** (468 without the tray); title 28/34 −0.01 → **26/32**; description .88 → **.86** + ` · Snapped left/right` | `CR:88-89`; `render_label` `CR:1207+` |
| Dots top 616 → **622** (578); opacity .6 → **.5**; square; no shadow | `CR:92-93`, `CR:1297`, `CR:1305` |
| Frost recipe | `CR:115-127`, `CR:312-326` (§5.1) |
| Sheen (Q11) | new; fold it into `_frost_small` |
| Open motion: cards rise from +24·S at ×0.92 | `CarouselMachine.start` has no card motion (`CA:286-306`) |
| **Group shift −44 → 0** when the tray first shows (460 ms OUT); label and dots shift with it | a new tween in `CarouselMachine` |
| Back toast `Cancelled · focus restored` → `Back · focus restored`, **only with no snap** | `CR:109`; `play_cancel_exit` `CA:2987-2989`; `_dismiss` `CA:1175` |
| Snap chip (half icon + `Left` / `Right`) | new chrome sprite |
| End bump from the knob | today keyboard and wheel only (`CA:340-347`; deviation 4). The ALIVE `limit` event can drive it (§3) |
| Knob buttons Cancel/Home/Windows/Switch → Back/Snap L/Snap R/Switch | `CT:979-981` (§2.2) |

### 6.2 New presenter protocol (Tk → stage)
- `snap(index, side, target_rect)`: start the fly, fill the tray slot, set the chip and description suffix.
- `set_snap_state({"left": id | None, "right": id | None})`: drives the tray visibility (hidden while both are None) and the group shift.
- `play_pair_exit(toast_text)`: at 820 ms, fade like Switch; toast `Side by side · {A} and {B}`.
- The adapter's `_drain_presenter` (`WN:1722-1742`) knows `switch / cancel / turn`. It may add `snap` from keys `2` / `3` or arrows, but the knob is the primary input.

### 6.3 Host, fly and tray (the structural change)
- **The fly** goes from the card rect to the target half of `rcWork` in physical px (03 §4.7). Its thumbnail must leave the pane.
  - The host is pane-sized today (`CA:2260-2269`), and a DWM thumbnail is clipped to its destination window.
  - **Grow the host to `rcMonitor`.** It is NOREDIRECTIONBITMAP, so it is transparent.
  - `card_rect` and the chrome then move from pane-local to monitor-local coordinates (`Layout.pane_point`, `CR:213-215`).
  - `presenter.rect` must keep reporting the card area, which the floating-knob suppression reads (`UI:1246-1253`).
  - Behaviour change: today clicks outside the pane fall through the click-through frost to the apps behind it, which ends the picker through focus loss. With a monitor-sized host they are eaten. Decide.
- **Thumbnail registrations:** one for the card, **one for the fly** (a second thumbnail of the same source), and one for each tray slot (176 × 110). The registration plan `REGISTER_DISTANCE = 3` (`CR:83`, `CA:1347-1361`) must count them.
- **Stale source size:** after placement the source window's size changes (half width). `s.sizes[i]` is captured once at registration (`CA:1441`, `CA:1456`) and feeds `cover_source` (`CA:1468`). **Re-query `DwmQueryThumbnailSourceSize`** after the placement settles, or the crop is wrong.
- **Frosted hides the move** (a static snapshot). No background shows it live (03 §4.9).

### 6.4 Placement algorithm (new native code in `windows.py`)
`NativeWindows._bind` (`WN:419-448`) declares no placement API. Add:
- `SetWindowPos`, `GetWindowRect`, `IsZoomed`, `MonitorFromWindow`, `GetMonitorInfoW` (for `rcWork`);
- `GetWindowPlacement` / `SetWindowPlacement`, `IsHungAppWindow`, `GetDpiForWindow`;
- `DwmGetWindowAttribute`, which is bound already (`WN:448`) and today used only for `DWMWA_CLOAKED` (14) (`WN:512`). It is also needed with `DWMWA_EXTENDED_FRAME_BOUNDS` (9).

The process is PMv2 (`ST:1741`), so `GetWindowRect` and the extended frame bounds are both physical px. Good.

Recipe: `WindowsAdapter.snap(item, side)`, run under `_changing_focus = True` (`WN:1600`):
1. **Validate.** `same_identity(item, native.identity(hwnd))` (`WN:298-305`), as `activate` does (`WN:1852`). If the window is hung (`IsHungAppWindow`), refuse: "{App} isn't responding".
2. **Choose the monitor.** Use the monitor of the picker's origin: `CA:monitor_rect` (`CA:2245-2257`) reads only `rcMonitor`, so extend it to return `rcWork`. Target V = the left or right half of `rcWork`. For an odd width, give the extra pixel to the right half.
3. **Un-minimize or un-maximize without activating.** Use `ShowWindowAsync(hwnd, SW_SHOWNOACTIVATE=4)`, or `SetWindowPlacement` (showCmd `SW_SHOWNOACTIVATE`, `rcNormalPosition` = the target in **workspace** coordinates), which does both in one call. **Not `SW_RESTORE` (9).** SW_RESTORE activates, which ends the picker through `_drain_foreground` / `_check_focus_lost` (`WN:1700-1751`). Wait, bounded (≤ 150 ms, polling `IsIconic` / `IsZoomed`); never block on the target.
4. **Measure.** W = `GetWindowRect`, E = the extended frame bounds. Set R = V expanded by (E−W) on each side (03 §4.9).
5. **Place.** `SetWindowPos(hwnd, NULL, R, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_ASYNCWINDOWPOS)`. The async flag keeps a hung target from blocking the Tk thread, matching the "never wait for the other process" rule of `WN:644`.
6. **Verify.** Re-read E within ≤ 200 ms. If it differs by more than 2 px:
   - a DPI change (monitor move): re-apply once after the app's `WM_DPICHANGED` self-resize;
   - an app minimum size: report "{App} can't fit half the screen", and leave it placed (it overlaps);
   - otherwise: failure.
7. **Z-order at close.** A and B were placed with `SWP_NOZORDER`, so the origin X (the foreground before the picker, top of the normal z-order) would cover them when the overlay closes. At `windows_close_pair`, raise A and B with `SetWindowPos(HWND_TOP, NOMOVE | NOSIZE | NOACTIVATE)` while this process still owns the foreground, then `native.focus()` the chosen one (D11).
8. **One side only on close.** "Keeps the previous window on the other half" (R §7.1): move origin X to the other half with the same recipe **on close only** (03 Q14), then restore focus to X through the existing `cancel()` (`WN:1873-1894`). The focus path's `restore=True` calls `ShowWindowAsync(9)` only if the window is iconic (`WN:643-644`), so it is harmless after placement.
9. **"Snap group".** No public API forms one, and none says a `SetWindowPos` placement registers one. Keep it out of the copy (03 Q19).

### 6.5 Controller and adapter snap state
- `screen.windows["snap"] = {"left": id | None, "right": id | None}`.
- A snap on the other side's window **moves** it (B&S:L840-842).
- Auto-advance at 420 ms goes to the **first unassigned window in list order** (B&S:L854; 01 §6 item 14 flags that this is not "the next one"). It is a host-driven re-entry (§2.4).
- **Both sides filled** → at 820 ms the `windows_close_pair` effect; the controller goes Home; toast `Side by side · {A} and {B}`, with display names from the adapter labels (`WN:1989-1994` builds the Switch toast the same way).
- **Switch after a snap** only activates the target; the snapped windows stay where they are (03 §4.8 item 6).
- **Failure:** Head shake; knob meta, e.g. `Couldn't move {App}` (03 Q15); the slot stays empty.

### 6.6 Focus contract: what stays and what changes
- **Stays.** The picker keeps its activatable host that owns the foreground (CAROUSEL §1; deviation 6). Switch and Back arrive over serial and need the foreground to `SetForegroundWindow`.
- **Snap needs no foreground.** `SetWindowPos` works across processes of the same integrity level. Snap must, however, **not lose it**: use the non-activating restore (§6.4 step 3), keep `_changing_focus` around the whole snap, and afterwards verify `GetForegroundWindow()` is still the host. If it is not, try `native.focus(host)` once (it succeeds only while this process still holds the grant), else close as focus-lost.
- **Opening.** Today it is F24 from slot 3 in any mode; in v7 it is F24 from slot 4 on Home only (§2.2, §3).
- **CAROUSEL §1 invariants to keep:** the host is visible and activatable when `show()` returns; the 150 ms handshake; the verify of ≤ 250 ms for our own window and ≤ 100 ms for others (`WN:129-131`); no icon work in the WM_HOTKEY path.

### 6.7 Snap risks
| # | Risk | Detail | Mitigation |
|---|---|---|---|
| S1 | **Elevated (admin) windows** | UIPI: a medium-IL process cannot move a high-IL window. PowerToys documents the same limit for FancyZones with elevated apps. With `SWP_ASYNCWINDOWPOS` the call may "succeed" and do nothing. | Never trust the return value; verify the rect (step 6). On failure: Head shake, `Couldn't move {App} · it runs as administrator` (copy to decide). Optionally pre-check the IL (`OpenProcessToken` may itself be denied) |
| S2 | **UWP / ApplicationFrameHost** | The snapshot keeps the frame window (`WN:278-281`, `WN:519`). Moving `ApplicationFrameWindow` works. A **suspended** minimized UWP app may restore slowly. Some UWP frames enforce minimum sizes. | Longer bounded verify (≤ 400 ms) for UWP; report instead of retrying |
| S3 | Maximized windows | `SetWindowPos` on a maximized window moves it but keeps `WS_MAXIMIZE`, so it snaps back when un-maximized | Un-maximize first (step 3) |
| S4 | Minimized windows | SW_RESTORE activates (R2) | SW_SHOWNOACTIVATE or `SetWindowPlacement` |
| S5 | Mixed-DPI move | The app resizes itself on `WM_DPICHANGED` | Re-apply once after settle |
| S6 | Minimum track size larger than half the work area | Overlap | Verify and report (03 Q15) |
| S7 | Hung target | `SWP_ASYNCWINDOWPOS` posts; the move may never happen | `IsHungAppWindow` pre-check; bounded verify |
| S8 | Owned or modal dialogs of the target | The snapshot rule keeps owned windows only with `WS_EX_APPWINDOW` (`WN:292`) | None needed |
| S9 | Full-screen or borderless games | A borderless window resized to half may re-assert full screen | Report on mismatch |
| S10 | Virtual desktops | Cloaked windows are excluded (`WN:289`) | — |
| S11 | Thumbnail crop after the move | `s.sizes` goes stale (§6.3) | Re-query |
| S12 | Focus loss during a snap | R2 | `_changing_focus`, non-activating restore, host check |

---

## 7. Toasts

### 7.1 Current implementation
- **Owner:** the carousel engine thread. The toast window role is `"toast"`: layered, unowned, click-through (`CA:2046`, `CA:1806-1807`).
- **Trigger:** only at the end of a picker exit (`_finish_exit` → `_start_toast`, `CA:1184-1188`). There is also a late path for a Dismiss that arrives after teardown (`CA:1165-1168`).
- **Texts:** the Switch toast `{App} · {Title}` (`WN:1989-1994`) and `CANCEL_TOAST` (`CR:109`).
- **Machine:** `ToastMachine`: fade 260 ms OUT, rise 8 px, scale .96 → 1 with SPRING over 420 ms, **hold 1.5 s** (`CA:196-200`, `CA:427-473`).
- **Glass:** its own capture job; 150 ms timeout, then the 88 % tint fallback (`CA:209`, `CA:1625-1660`; `CR:1350-1378`).
- **Position:** stage top **320**, centred (`CR:97`, `CR:1381-1385`; deviation 8).
- **Rule already met:** a new picker open ends any toast before its capture (`CA:1043-1046`).
- **Failures** are **tray balloons**, rate-limited to one per 10 s (`ST:51`, `ST:671-708`).

### 7.2 Changes
| Change | Where |
|---|---|
| Position top 320 → **588** (bottom centre) | `CR:97`, `toast_rect` `CR:1381-1385` |
| Tint (30,30,32,.55) → **(24,24,26,.62)** | `CR:98`, `_TOAST_TINT` `CR:314` |
| Hold 1.5 → **1.8 s**; a new toast replaces the text at once and restarts the timer (B&S:L648) | `CA:198`; `_start_toast` ends the old one (`CA:1629`), then capture (new glass per text) |
| **A service independent of the picker**: `stage.toast(text, monitor=None)` from the Tk thread; the monitor of the foreground window (03 Q13) | a new presenter method and a Mailbox field; `layout_for(monitor_rect(GetForegroundWindow()))` |
| **Never over an open overlay**: drop, or queue until close? The design says "never shown" and "cleared when one opens". Recommendation: drop while any scene is open, except the overlay-exit toasts (`Playing …`, `Side by side …`, `{App} · {Title}`, `Back · focus restored`), which start after the exit, as today. | engine: refuse `toast` while `session` is set; `_open` already clears |
| **No toast for Play/Pause** | controller never emits one |
| Copy catalogue (03 §5.2): `Playing {album} · {room}`, `Queued next · {album}`, `Next · {track}`, `Previous · {track}`, `End of queue`, `Start of queue`, `Playing {track}`, `Back · focus restored`, `Side by side · {A} and {B}`, `{App} · {Title}`. **Not** the Like and Shuffle toasts while Up next is open (03 Q13). | controller `toast` effects (§2.6); `room` = `state["group_label"]` (`CT:110`, `SO:190`) |
| Text fitting | `fit_toast_text` keeps the `{App} · ` prefix (`CR:1316-1336`). Extend the prefix rule to `Playing … · {room}` (keep the suffix) or accept an ellipsis |
| Timing | knob-only toasts are sent **on confirmation** (§2.8), so they lag the press by the Sonos round trip (hundreds of ms). Acceptable; say so in the spec |

---

## 8. Tray icon: light/dark and connected/missing

**Correction to the task premise:** the pystray `TrayIcon` subclass lives in **`standalone.py`** (`make_tray_icon`, `ST:530-658`), not in `ui.py`. `ui.py` only sets the app icon for Tk windows (`AppWindowIcons`, `apply_app_icon`, `UI:405-552`; APP_ICON item 3).

| Requirement (R §7.2–§7.3; 05; APP_ICON) | Status today | Gap |
|---|---|---|
| Four tray ICOs, dark/light × connected/missing | `tray_icon_file` (`ST:389-394`); loaded at `SM_CXSMICON` per DPI through `_assert_icon_handle` (`ST:565-581`) | None. The `icons/` handoff assets are byte-identical to `assets/app-icon/` (03 §7) |
| Swap on every connection change; tooltip `Nano_D++ · Knob connected` / `Knob not found`; header | `TrayPresenter._apply_knob_state` (`ST:733-752`); `tray_tooltip` (`ST:382-386`); `TRAY_HEADERS` (`ST:62`); presence = `runtime.device_connected` (`knob_present`, `ST:405-410`) | None |
| Follow `SystemUsesLightTheme` | `taskbar_theme` reads HKCU (`ST:412-425`) | None |
| **Watch `WM_SETTINGCHANGE`** ("ImmersiveColorSet") | **Polled every 2 s** (`THEME_POLL_MS` `ST:63`; `poll_theme` `ST:1837-1843`, `ST:1900`) | **Change.** pystray's window is a hidden top-level `WS_POPUP` (it receives broadcasts; `.venv/.../pystray/_win32.py:235-257`). Its dispatcher looks up `icon._message_handlers` and returns 0 for anything missing (`_win32.py:411-413`). `make_tray_icon` already registers `WM_TRAY_ICON_FILE` there (`ST:655-659`). Add `handlers[0x001A] = on_setting_change`, which reads `lParam` as `wstring_at` (guard null) and, on `"ImmersiveColorSet"`, only calls `put('theme')` (the tray-thread → Tk rule, `ST:1797-1801`). `handle_requests` maps `'theme'` to `presenter.set_theme(taskbar_theme())`. Keep the poll as a slow backstop (e.g. 30 s). Tests: extend `test_cc_tray.py`'s 4 theme tests with a fake handler call |
| "Reconnecting" state | The tray shows **missing** while reconnecting (APP_ICON item 5) | Only the Settings service strip distinguishes it (§9) |
| Menu (design: header + `{room} · {vol} %`, `Open Nano_D++`, Connect/Disconnect, `Quit` "Stops the knob") | `tray_menu_model` (`ST:433-444`): header, device status, Show knob, Settings…, Connect/Disconnect, Quit | Decision (03 C3). The native pystray menu cannot style a hint; `Quit (stops the knob)` is possible. The status sub-line could become `{room} · {vol} %` from `controller.state` |

---

## 9. Settings and recovery states

### 9.1 Current Settings
`ControlCenterApp.setup` (`UI:1550-1766`):
- Title `Nano_D++ · Setup` (`UI:1568`); heading `Connect your desk` (`UI:1574`); subtitle `SETUP_SUBTITLE` (`UI:113-114`).
- Fields: `Hall speaker IP`, `Knob USB port`, raw button order with the `Verify physical button order` probe (`UI:1583-1613`); `Apple Team ID`, `MusicKit Key ID`, `Choose .p8 key` (`UI:1614-1620`).
- Segmented choices: `Album artwork` On/Off, `LEDs` `Targeted colour` / `White` (`UI:1656-1657`), `Switcher background` Frosted / No background (`UI:1659-1666`).
- Buttons: `Save settings` / `Authorize Apple Music`.
- On tray failure: Connect/Quit rows (`UI:1733-1753`).

### 9.2 Deltas
| Item | Change | Code |
|---|---|---|
| LED labels | `Colour` / `Warm only` (ALIVE §2, §10.2) | `UI:1657`; `DEFAULT_LED_STYLE` comment `UI:130` |
| Button-order probe | Unchanged; it is physical. If a knob map is shown (CC design), use the **new grammar** (03 Q17) | new, optional |
| **Service strip** (the recovery states' home, since there is no main window; 03 Q16) | Three columns. **Knob**: `Connected` / `Not found` / `Reconnecting`, from `runtime.device_connected` plus standalone's `RetryPolicy.inflight`, which `ui` cannot see today, so pass a status callable in. **Sonos**: `{group_label}` / `Unavailable`, from `controller.state["online"]` (`CT:110`). **Apple Music**: `Signed in` / `Sign-in needed`, from `runtime.music_signin_expired` (`RT:241`). Each has the CC detail line and CTA (03 §6.5): `Set manual IP…` → the IP field; `Renew sign-in…` → `Authorize Apple Music` | new widget above the heading; refresh from `_refresh_setup_actions`-style polling (`UI:1352-1383`) |
| Like changes the consent copy | `credentials.py:245` promises no library changes (check-like §4.5) | `credentials.py` |
| LED brightness (proposed) | Only if ALIVE's `led_drive` gets a UI (03 Q17) | new |
| Launch at sign-in | Today an installer scheduled task, with no toggle | Decision |
| Switcher background | Keep Frosted / No background, or drop No background (03 Q11) | `UI:117`, `WN:85-86` |

### 9.3 Recovery states: where each shows in v7
| State (CC) | Knob | Tray | Settings strip | Other |
|---|---|---|---|---|
| Knob not found | offline LCD (firmware) | missing icon, `Knob not found` | Knob `Not found` (bad) | — |
| Reconnecting… | — | missing icon | Knob `Reconnecting` (wait) | "Turns and presses made while unplugged are discarded" is already true (`RT:1391-1399`) |
| Hall unavailable | `Sonos unavailable` / `Windows still works` (`CT:1103-1112`) | header stays; a balloon only for a failed action | Sonos `Unavailable` + `Set manual IP…` | Explorer, Up next and Seek refuse to open (new) |
| Apple Music sign-in expired | Recent full-screen sign-in state (`CT:1133-1135`); new: the same on the explorer's tabs and on Like (disabled) | balloon (existing auth message path, `UI:1788-1807`) | Apple Music `Sign-in needed` + `Renew sign-in…` | — |

---

## 10. Floating knob (`overlay.py` / `ui.py`), LCD mirror and LEDs
- **Suppression:** add reasons `explorer` / `queue` (§5.7) in `UI:_update_suppression` (`UI:1211-1219`), keyed on the new presenter's published rect or visibility. The picker's `carousel` reason stays (`UI:1246-1253`).
- **Capture exclusion:** the shared stage takes the knob's hwnd once (`UI:1517-1538`) and applies it to every scene's frost capture.
- **LCD mirror:** `lcd_preview.render_lcd` (`LP`) must draw:
  - the `seek` layout (48 px `m:ss`, `of m:ss`);
  - the mirror headings;
  - the Windows snap meta;
  - the new footer tones (on/off/custom colour);
  - the new icons: `LEGACY_ICON` / `ICON_NAMES` (`LP:469-472`) and the masks under `assets/handoff-icons` + `assets/lcd-icons` (@2x/@3x).

  The Tracks row changes (skip-back/forward and a 6 px dot) are 01's. They land here because the floating knob draws the same layouts (FLOATING_KNOB §2–§3).
- **LEDs:** `AliveLights` today has families `home / recent / tracks / windows` (`AL:104`) and no `half`, `scatter`, pink `bloom` or sweep-from-0 (`AL:142-146`, `AL:895`). Adding them, and the explorer/queue/seek families, is 02's work. The companion must **feed** the triggers the engine cannot infer: snap side and colour, like, shuffle, queued (02 §6.10). The floating knob then shows them too (ALIVE §10.3).
- **Summon:** the ALIVE `limit` event is a touch (ALIVE §10.3).

---

## 11. Simulation and tests

### 11.1 Simulator
`SI` implements only `read_state / set_volume / transport / play_items` (`SI:11-53`), `recent / resolve` (`SI:55-91`) and `snapshot / show / highlight / activate / cancel / hide` (`SI:93-118`).

v7 fakes are needed for: queue windows, play_next, jump, shuffle, seek (with duration and position), neighbour titles, playlists, ratings, snap (placed/failed), and a fake stage presenter for the explorer, Up next and toasts. The dev window's key bindings (`UI:680-682`) and `list_selected` (`UI:966-969`, modes `recent` / `windows` only) need the new modes.

### 11.2 Existing tests that the change touches
**Method:** a static scan of every `def test*` body (`ast`) for:
- presses of logical 1, 2 or 3;
- v4 legend or icon tokens (`Cancel/Home/Win/Browse/More/Switch`, `cancel/home/more/switch`);
- F24 plumbing (`hotkey(`, `windows_button`, `windowsButton`, `supports_hotkey`);
- carousel constants;
- toast constants;
- theme polling.

The counts are **upper bounds**. They include some false positives: carousel event names `'switch'` / `'cancel'`, and window-label words such as "Home" in `test_window_labels.py`.

| File | Tests | Touched | Why | Expected action |
|---|---|---|---|---|
| `test_cc_controller.py` | 70 | **37** (b3: 27, b1: 13, b0: 12, b2: 3, hotkey: 4; origin/resume: 12) | `NavigationTests` and the others press the v4 map; Windows from Recent/Tracks; Cancel; F24 → `button(2)` (`:824-846`) | **Rewrite** to the master table. The origin-resume tests become Home-only or are deleted |
| `test_cc_stage3.py` | 88 | **36** (b3: 25, b0: 17, b1: 7, icons: 7; origin: 6) | Copy per mode (`HomeCopy`, `RecentCopy`, `TracksCopy`, `WindowsCopy`, `PendingFreeze`, `OffView*`) | **Rewrite** copy and legends; the off-view suspended paths shrink |
| `test_cc_lookahead.py` | 46 | **20** grammar, 28 paging | Recent paging, More, prefetch | Depends on **D1**: keep pages → adjust presses only; flatten → rewrite most |
| `test_cc_enter_frames.py` | 35 | **13** | Enter-frame equality per mode and button | Rewrite presses; add new modes |
| `test_cc_runtime_colours.py` | 30 | **10** | Ring and button colours per mode | Rewrite presses; new tones |
| `test_cc_warmup.py` | 24 | 7 | Browse = b1 | Presses (b1 stays Browse on Home; mostly **unchanged**) |
| `test_cc_presentation.py` | 15 | 7 | `button_tone` (`PR:156-165`) | **Rewrite** for the new tones |
| `test_cc_touch.py` | 16 | 6 | `SimulatorWindowsButtonTests`, `HotkeyTouchTests` (logical 2 = Windows) | Rewrite to logical 3 on Home |
| `test_cc_ui.py` | 56 | 6 | `windows_button == button_order[2]` (`:289`, `:409`); `button(2)` = Windows (`:791`, `:815`) | Adjust |
| `test_cc_media_runtime.py`, `test_cc_runtime_overlay.py`, `test_cc_handoff.py`, `test_cc_playback.py`, `test_cc_art_swap.py` | 30 / 67 / 17 / 14 / 7 | 4 / 4 / 3 / 3 / 1 | Presses on the way to a state | Adjust presses |
| `test_cc_lcd_preview.py`, `test_cc_led_model.py`, `test_alive_lights.py`, `test_cc_knob_face.py`, `test_cc_contract_v4.py`, `test_alive_golden.py` | 74 / 56 / 95 / 21 / 60 / 9 | 22 / 6 / 6 / 2 / 2 / 1 | Old icon tokens and tones | Stay valid if the old tokens stay accepted (D8); **add** new-token tests |
| `test_cc_device.py`, `test_cc_media_bridge.py`, `test_cc_session_capture.py` | 30 / 61 / 13 | 1 / 1 / 1 | `windowsButton` in control fixtures | The value 2 → 3 |
| `test_cc_windows.py` | 59 | 3 | Hotkey registration | **Unchanged** (the mechanism stays) |
| `test_carousel_machine.py` | 33 | 7 | `TABLE` / geometry | Constants |
| `test_carousel_render.py` | 46 | 12 geometry, 7 frost, 3 toast | Constants and the frost recipe | Constants; the frost goes parametric |
| `test_carousel_presenter.py` | 75 | 6 geometry, 3 frost, 11 toast, 5 Cancel toast | | Constants; the toast service; `Back · focus restored` |
| `test_carousel_adapter.py` | 113 | 7 toast text, 3 Cancel, 12 focus/origin | | Mostly unchanged; add snap |
| `test_carousel_live.py` | 7 | 1 / 1 | Env-gated live windows | Re-run under supervision |
| `test_cc_tray.py` | 62 | 4 theme | Poll | Add the `WM_SETTINGCHANGE` handler test |
| `test_packaging.py` | 20 | — | Version gates (v2–v5 refused) | Add v7 / `desktop-dist-v7` |

**Order of magnitude:** about **150 tests** in controller-driven files press remapped buttons or assert v4 legends and need rewriting. About **40 carousel tests** need constant or toast updates. About **40 renderer and LED tests** stay green if the old tokens remain valid.

CAROUSEL §1 says "every AdapterTests, ForegroundEventTests and controller test must stay green unchanged". v7 **cannot** keep that for controller tests, so the spec must amend it.

### 11.3 New suites needed
- **Controller:**
  - the master button map per mode;
  - hold-to-Home from every mode;
  - Back targets;
  - host-driven re-entries (new id, position and max; the profile only on Seek);
  - the Seek mapping (01 §2) and its 250 ms / 3 s timers;
  - the Queued-next timer;
  - the snap state machine (assign, move, auto-advance at 420 ms, pair close at 820 ms, one-side Back);
  - the toast effects (none for Play/Pause);
  - the explorer source memory.
- **Runtime:** the F24 / serial race (R1); the new lanes and invalidation; `limit` and `hold` events.
- **Device:** v5 field validation and parity fixtures; the frame budget with every new field; the `kh` / `lim` parsing; the legacy downgrade (D8).
- **Stage:** the scene machines with a fake clock (stagger, source switch, shuffle, Play); frost recipes per scene; toast suppression while a scene is open; the tray and fly thumbnail registrations; source-size re-query.
- **Windows:** placement with a fake native layer (restore without activation, frame compensation, DPI re-apply, UIPI failure, hung window, verify timeouts); the `_changing_focus` guard during a snap.
- **Tray:** `WM_SETTINGCHANGE` routing.
- **Sonos / Apple fakes:** queue windows, play-next rollback (check-play-next §4.1), ratings.

---

## 12. Risk register (most severe first)
| # | Risk | Effect | Mitigation |
|---|---|---|---|
| R1 | **Button 4 has two roles**: Windows on Home (F24) and Switch in the picker (serial). The F24 and serial race. | A double action: opening the picker and immediately Switching, or opening without a foreground grant | Control-id filtering (`DV:834`, `CT:529`) + skip logical 3 on Home + firmware F24 only on Home; ideally the firmware tags the `kd` (§3) |
| R2 | The **design's SW_RESTORE activates** the snapped window | The picker dismisses itself mid-snap (focus loss, `WN:1700-1751`) | Non-activating restore (§6.4) + `_changing_focus` |
| R3 | **Explorer frame cost** (CPU covers at k = 2) and **ambient memory** (≥ 100 MB with option A) | Janky 420 ms turns; over the 80 MB budget | The §5.4 spike, sprite caching, dirty-rect ULW; measure before committing |
| R4 | **Elevated / UWP / min-size windows** | Silent snap failures | Verify, then report (§6.7) |
| R5 | **Shuffle semantics** are not Sonos shuffle (D5) | Wrong order shown, or queue rewrites | Decide; the physical reorder has rollback |
| R6 | **Play next only works from the queue, with shuffle off** (check-play-next) | Refusals the design doesn't draw | Copy plus the Head shake (check-play-next §4.2) |
| R7 | **Like**: the Apple write scope and the Favorite mapping are unverified (check-like) | Button 3 may need the fallback | D6; the check-like §5 live test |
| R8 | **Contract v5** across firmware and host, and the frame budget | Stripped icons (`DV:231`) or rejected frames | Parity fixtures; D8 |
| R9 | **Host-driven re-entries** multiply (seven kinds, §2.4) | Knob/screen desync if one is missed | A single `_reenter(index, bounds)` helper plus tests |
| R10 | **Queue size** (up to 5000 rows) | Slow Up next open | Windowed reads |
| R11 | **Test churn** (§11) | Schedule | Rewrite by mode, keep old tests for unchanged flows |
| R12 | **Picker host grows to the monitor** | Suppression and click semantics change (§6.3) | Explicit tests; keep `rect` = the card area |

---

## 13. Decisions needed (new here, or restated for the companion)
| # | Question | Recommendation |
|---|---|---|
| D1 | Recently Added **paging / More** on the knob and in the explorer (01 Q1; 03 Q3) | Flatten loaded pages into one list. Prefetch the next page near the end and extend the bounds by re-entry. Keeps the lookahead lane; retires More. Costs the most test churn (`test_cc_lookahead`) |
| D2 | Explorer and Up next **turn timing** (03 Q1) | The spec: 420 ms, no delay |
| D3 | **Mouse** on explorer / Up next (03 Q12) | Eat clicks, act only on the centre card or focused row |
| D4 | Toasts **over overlays** and the monitor for knob-only toasts (03 Q13) | Drop while open; foreground window's monitor |
| D5 | Up next **Shuffle** semantics on Sonos | Physical reorder of the upcoming rows (`ReorderTracksInQueue`, guarded by UpdateID), with the original order kept for Off; or disable Shuffle while Sonos shuffle is on |
| D6 | **Like** unreachable (R §8) | Run the check-like live test. Fallback: Play next for the highlighted row (check-like §4.6) |
| D7 | **Snap focus at pair close** | Raise both; focus the side snapped last |
| D8 | v7 host with a **cc5.3 knob** | Downgrade table in `device.py` (new icons → nearest legacy glyphs); single controller |
| D9 | Explorer / Up next when **Sonos or Apple Music is unavailable** | Refuse to open: Head shake plus knob copy |
| D10 | **Picker host = monitor**: eat clicks everywhere? | Yes; it also removes accidental activation through the frost |
| D11 | **One-side close**: move the origin at the first snap (prototype) or on close (03 Q14)? | On close |
| D12 | Keep **No background** for the picker and add the **sheen** (03 Q11) | User's call |

---

## 14. Suggested build order
1. **Contract v5 and grammar.** Controller table, hold, re-entry helper, `device.py` validation and downgrade, `runtime` F24 and serial rules, simulator. No overlays yet: `explore` / `queue` modes show their knob mirrors only.
2. **Seek.** Sonos duration and seek; controller Seek; `progress` shared with ALIVE.
3. **Picker V2.** Constants, frost recipe, dots, label, open motion, Back toast. Then **snap**: native placement, host → monitor, fly and tray thumbnails, controller snap state.
4. **Toast service**, and the knob-action toasts.
5. **Stage refactor**, then **explorer** (Recently Added first, then Favourite playlists), then **Up next** (read-only first; then jump, Play next, Shuffle, Like per D5/D6).
6. **Tray theme event**, the Settings strip, label changes.
7. **Supervised checks.** Picker snap on the real desktop (elevated, UWP, maximized and minimized targets); explorer frame times at k = 2; the Play next, Seek and Like live tests (each only with the user's go-ahead, per the check files).
