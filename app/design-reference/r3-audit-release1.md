# Desk Dial r3 release 1: hardware bug triage and path audit (2026-09-29)

Scope: the two bugs the user found on the knob (binary D, presentation 6) with Desk Dial r3 release 1, an audit of
every r3 path against the r3 README (button maps §1.2 options 1a + 1e, screens §2.2, copy §6), and the design
gap items A2–A10, B3–B8, B10–B12 of `r3-design-gap-audit.md`. Nothing was flashed or installed; the running
Desk Dial and its data were not touched.

How each path was checked: `tests/tools/capture_r3_session.py` drives the real Controller + Runtime +
DeviceBridge against an in-memory presentation-6 knob (FakeKnob with the F24 icon gate), the simulator's Sonos,
Apple Music and Home Assistant, a FakeStagePresenter, and a picker that follows the Windows foreground rule
(a show succeeds only inside the F24 grant, as `WindowsAdapter.show` does). Every one of the 233 frame / control
lines it sent went through the firmware's real `cc_parse_frame` (`harness/parse_tests.py --frames`:
all accepted, stored text identical) and through the firmware's real LCD code in the LVGL harness
(`r3-handoff/r3_screens.json` is now generated from this capture; `r3-handoff/contact-sheet-r3.png`,
`cc54_report.py` 39/39 checks pass on the renders).

## Root causes of the two hardware bugs

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | Home 2 (Windows): the full-screen picker never opens | r3 moved Windows from Home 4 to the launcher's button 2, but the control kept `windowsButton = button_order[3]` and turned `windowsHidEnabled` off on the launcher (`controller.py` `control()`, was `:1184-1187`). So the knob never sent F24 and the picker was opened from a serial press. Windows refuses the foreground to a process that did not get the last input, so `WindowsAdapter.show` hides the picker and raises (`windows.py:1946`); the controller only showed an error line. The stage counters (`opens=0`) count the explorer / Up next only, not the picker. | The Win slot's raw sends F24: `windows_button` = `button_order[1]` in r3 (`controller.py:959`, `:1221`), HID enabled on the launcher. The hid-tagged `kd` is dropped on any slot (`controller.py` `button()`, `runtime.py:2236`). Firmware unchanged for this (it already gates F24 by `windowsButton` + the `win` icon). |
| 2 | Music → Recently Added (and more): the knob shows blank / missing text; no surface opens | The Lights brightness control had `min 1` while the lights are on (`controller.py` `bounds()`, was `:1169`). The bridge (`device.py` `_enter`, "Invalid control bounds") and the firmware (`control_center.cpp:298`, `min` 0..0) both refuse it. The bridge error made the runtime mark the knob unsupported (`runtime.py:2252`): no further enters or frames were sent, so every later screen (Recently Added included) stayed stale or went to the offline screen, and nothing opened. The frames themselves were fine: every r2.2 / r3 screen parses and renders with its text in the firmware harness. | Brightness is 0..100 with position = level; position 0 while on is the 1 % floor (`controller.py:1197`, `_lights_turn`). Regression: every control of the full-stack session passes the bridge (`bridgeErrors == []`). Also: Lights no longer flashes "Lights not set up" before the first HA stream update (`runtime.py:1477` posts the adapter's cached state at install). |

## Path audit (presentation 6)

Expected = README r3 (release 1 plus the gap items delivered now); Actual = the full-stack capture after the
fixes, rendered through the firmware LCD code. "Fixed" names what changed in this job.

| Path | Expected (README) | Actual (after) | Fixed? |
|---|---|---|---|
| Home (launcher) | volume knob; 1 Music · 2 Win · 3 Lights · 4 Play/Pause; no breadcrumb | as expected; no crumb, flat heading none | — |
| Home · turn | volume reveal | `volume` layout, digits | — |
| Home · 4 | Play/Pause, `Paused` | Paused / Playing | — |
| Home · 1 | Music; a tap within 700 ms of arriving Home ignored with `Home · press 1 again for Music` | Music; guard in `_press_launcher` (`controller.py:2086`) | A2 fixed |
| Home · 2 | picker opens on screen immediately | picker opened 4/4, 0 refused (F24 grant) | Bug 1 fixed |
| Home · 3 | Lights, brightness mode | Lights (`Hall`, `62% · 3200 K`); control min 0 | Bug 2 fixed |
| Hold 1 (anywhere but Home) | Home; tap suppressed; warm progress ring 0→100 % over 600 ms (from 12 %), then warm full-ring flash 400 ms | 1 acts on release, `kh` drops the tap (`runtime.py` `_pending_tap`); ring + flash in the firmware alive engine (`cc_alive.cpp`, twin `alive_lights.py`), shown on frames with a crumb only | A3, A4 fixed |
| Music | 1 Home · 2 Recent · 3 Tracks · 4 Play/Pause; arc `MUSIC`; Home → Music slides | crumb `music`, slide from depth 0 → 1 | A8, B10 fixed |
| Recently Added | list; 1 Back → Music · 2 Full screen · 3 Play next · 4 Play; arc `MUSIC › RECENTLY ADDED` | title / artist / `n / N` drawn (harness); label `Full screen` | Bug 2, A8, B12 |
| Recent · 2 | explorer opens full screen, same album | `explorer_open` posted; knob mirror, arc `MUSIC › RECENT › ON SCREEN` | A8 |
| Explorer 1/2/3/4 | Back → list same album / Recent tab (album icon, act) / Playlists tab (act) / Play → Music | as expected; tab 2 icon `album`, lit tab ink `#FFBE69`; arc swaps to `… PLAYLISTS › ON SCREEN` | B4, B6 fixed |
| Recent · 3 / 4 | Play next / Play → Music | `Queued next` / Music | — |
| Tracks (rest) | title = current song, sub = artist, `Turn for previous or next`; arc `MUSIC › TRACKS` | as expected | A9 fixed |
| Tracks · turn | `Previous` / `Next`, `Now: {song}`, `Press 4 to skip`; a turn clears a message | as expected | A9 fixed |
| Tracks · 4 at Now | refused: `Turn to pick previous or next` #FF8474, bottom 26–34 red 320 ms | reason in error tone + feedback `err`/`refused` → `CC_FLASH_REFUSED` (no shake) | A6, A7 fixed |
| Tracks · 3 → Seek | big m:ss; `of {dur} · 3 sets · 1 cancels` #FFBE69; 1 Cancel · 2 Up next · 3 Set · 4 disabled | as expected; nothing sent while scrubbing; Set sends one seek + `Seek set` + green; Cancel sends nothing + `Seek cancelled`; 4 → `Set or cancel seek first`; arc stays `MUSIC › TRACKS` | A5, A6, B7 fixed (ring stays the r2.2 lap) |
| Tracks · 2 → Up next | opens full screen; 1 Back → Tracks · 2 Shuffle (`Shuffle on/off` amber) · 3 Like · 4 Play | `upnext_open` posted; arc `MUSIC › TRACKS › UP NEXT`; Shuffle copy warm | B3 fixed |
| Windows (knob) | title / app / `{i} / {n}`; 1 Home (house) · 2/3 Snap (`Snapped left/right`) · 4 Switch → Home `Switched to {app}`; ring white marker, rest warm 0.1; arc `WINDOWS` | as expected (`marker` ring, new firmware ring style) | B5, B8, B11 fixed |
| Windows · hold 1 | Home | Home | — |
| Lights | scene/group name, `{bri}% · {K} K`; 1 Home · 2 Scenes · 3 Temp (lit warm) · 4 All off / Turn on; arc `LIGHTS` | as expected; `Knob: temperature` / `Knob: brightness` in #FFBE69; Temp icon act | B3, B4 fixed |
| Lights · turn / temp turn | big `Brightness 67 %` / `Colour temperature 3500 K` | as expected | — |
| Lights · 4, turning while off, Turn on | `Lights off` / `Tap 4 to turn on`; turn on at 1 %; restore the snapshot | as expected; the stale `Lights off` line is cleared when a turn switches them on | fixed (copy) |
| After a scene + turn | `{Scene} · adjusted` | `Movie · adjusted` | — |
| Scenes | prev / current / next; `n / N · bri · K`; 1 Back · 2/3 refused `Turn to choose · 4 runs it` · 4 Run → Lights `Scene running`; arc `LIGHTS › SCENES` | as expected; 2/3 now also flash the bottom red | A7 |
| Scenes · hold 1 | Home | Home | — |
| Idle (launcher paused 4 s) | icon row, no arc | unchanged; the crumb is hidden in idle | — |

Not changed on purpose: nav / disabled button LED levels (B1, user decision: keep warm-white nav); Play green
while paused (B2, standing decision); the Recently Added / explorer ring look (B9, not requested); the Seek ring
stays the r2.2 lap (B7 note: the gap audit accepts it). The Navigator (A1, B12-B14) is the separate job.

## Wire / firmware additions (presentation 6, append-only; PRESENTATION_V5 §19.9 in spirit)

- `crumb` (frame, token: `music recent onScreenRecent onScreenPlaylists tracks upnext windows lights scenes`):
  the knob draws a pre-rendered A8 arc (r 94, Montserrat 500 12 px caps, 0.96 px tracking, ancestors #7C7C7C,
  current #E6E6E6; `src/cc_crumbs.cpp`, 46.6 KB in flash, generated by `harness/make_crumbs.py` from
  `control_center/crumb_arc.py`, which the desktop mirror paints too), hides the flat heading, fades 200 ms,
  gives the screen depth for the slide direction, and enables the hold-1 ring.
- line tone `warm` (#FFBE69), ring style `marker`, feedback moment `refused` (kind err only); lit-on footer ink
  `act` #FFBE69 on r3 screens (a frame with a crumb). A presentation-5 knob gets a valid downgrade.
- alive engine: `CC_FLASH_REFUSED`, `CC_FLASH_HOME`, the hold-1 progress ring (`CCAlive::keyUp`, wired in
  `hmi_thread.cpp`), class M 0.10 for the marker ring, active lit-on 0.90 on r3 screens.
- LCD boxes: STATUS and TRACKS_META x 30 w 180 (README L-6), SEEK_LINE x 25 w 190.

## Evidence

- Companion suite: 3,880 tests, 8 failing = the 6 known unrelated `test_cc5_tooling` ones (check-flow 2,
  static 1, RebootWatch 1, runbook doc figures 2) + 2 static tests that flag the Navigator job's new
  `navigator.py` / `navigator_covers.py` importing the stage (not in this job's files).
- New regressions: `tests/test_r3_audit.py` (26 tests: the full-stack session, F24 on the launcher, every
  Lights control valid, grammar, wire / downgrade, crumb masks, mirror, alive twin).
- Firmware gates: `parse_tests.py` PASS (5,242 cases incl. 25 new presentation-6 cases), `alive_tests.py` PASS
  (137,650 checks, 2 new twin sequences), `cc54_report.py` 39/39 PASS, `make_crumbs.py --check` current.
