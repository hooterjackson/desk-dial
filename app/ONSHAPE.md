# Onshape mode (A0) — Desk Dial 7.1.0.0, `desktop-dist-v7-b` (A2 additions: section 10 on, Desk Dial 7.2.0.0)

> **2.0.0 (app profiles, Desk Dial 7.4.0.0) supersedes parts of this file.** Onshape is now one app profile among
> several (`profiles/karl/onshape.json` + `profiles/onshape.windows.json`; the plan's wire and knob store in the
> firmware's `APP_PROFILES.md`; authoring in `profiles/README.md`). Its behaviour is unchanged and proven byte-identical
> by `tests/goldens/onshape_input/`. What changed for the user:
> - **Settings:** Off / Manual / Auto moved from Settings → Knob → Onshape mode (section 7) to **Settings › Apps**,
>   one row per app; `onshape_mode` migrates into `app_modes.onshape` and is kept in sync for rollback.
> - **Tray:** "Onshape mode" / "Leave Onshape mode" became the **App mode** submenu (a Manual toggle per app).
> - **Browsers:** host detection runs in Chrome, Edge, Brave, Vivaldi and Opera (`app_profiles.BROWSER_EXES`); the
>   strict title fallback of section 7 still applies to chrome.exe / msedge.exe only. Tried live: Chrome.
> - **Feel:** the knob profile is BINARIS BEER (67 detents) since 7.2.1.0; the SMOOTH OPERATOR / 0..65535 notes in
>   sections 3, 11 and 12 are history (bounds 0..60000, centre 30000).
> - **Gates added for every app:** nothing is sent on the secure desktop (lock screen, UAC); typed text after a
>   shortcut re-checks the page focus first; dangerous chords and shell targets are refused.

Desk Dial only: no firmware change, no new wire field. The mode runs on a knob that reports
**presentation 6 or later** (the r3 navigation); an older knob never enters it.

The mapping is adapted from `katbinaris/NanoD_RatchetH1` @ `feat/firmware-esp-idf-quadra`
(`NanoDepsidf/src/app_profiles/onshape.c`, Karl Malota), with permission.

## 1. What the knob does

| Input | Action |
|---|---|
| Knob | zoom: fractional wheel deltas, 24 notches per turn in total (wheel up = zoom in) |
| Hold 2 + turn | orbit: right-drag along x, `PX_PER_TURN` (760 px) per turn |
| Hold 4 + turn | pan: middle-drag, the same travel |
| Hold 1 + turn | **tilt** (vertical orbit): right-drag along **y**, the same travel; clockwise drags down (7.2.2.0, section 15; it zoomed as the knob alone in 7.2.1.0, Karl's F1 `ZOOM`) |
| Tap 3 | Undo: Ctrl+Z as one atomic `SendInput` batch |
| Tap 1 | sends nothing; the text screen shows `Hold all 4 for Home` |
| **All four buttons held 1.0 s** | **Home** (leaves the mode; 7.2.1.0, replaces hold 1) |

- Every key acts on its **release**. A key that was **turned during its press** drops both its tap and
  its `kh` (hold), in Onshape mode only.
- No `kh` acts here: the firmware's 600 ms hold of button 1 and 1.0 s hold of button 4 are ignored
  (`hold_action()` is `""`: no hold marker; 1 is tilt's modifier, 4 is pan's).
- **The Home chord** (`onshape.KeyTracker`, `HOME_CHORD_SECONDS` 1.0, `CHORD_KEYS` 3):
  - The 1.0 s runs from the moment the **4th** button goes down; any release before it cancels (all four
    down again starts a new 1.0 s). A `ready.held` mask of all four (a re-entry) never starts it.
  - From the moment **3 buttons** are down, every button then down (and any pressed while one of them is
    still down) is *chorded* until its own release: no tap, no hold, not a modifier. While the chord lasts
    the injector starts nothing: a running drag ends at once (release `chord`), turns zoom / tilt / orbit / pan
    nothing, tap 3 is no Undo, an open wheel closes **unrun** and in parameter mode no key steps, switches
    A/B, confirms or cancels (parameter mode itself stays open). A drag begun with two buttons down is
    therefore released the moment the third goes down.
  - When it matures the runtime (Tk tick, `_poll_onshape`) releases every injected input first, then
    leaves to Home as a user exit (Auto is suppressed until Onshape loses and regains the foreground, as
    the tray's Leave) and deactivates the injector. The four buttons' later `kh` and releases are swallowed
    on any screen until each is released (a late hold 4 on Home would otherwise swap the knob's domain).
  - The text screen's status reads `Hold all 4 for Home` while 3 or more buttons are down.

## 2. Knob screen (presentation 6, `nowPlaying` layout)

- heading `ONSHAPE`; no crumb.
- title = the live action: `ZOOM` / `TILT` / `ORBIT` / `PAN` / `Point at the model` (2 s after a refusal).
- subtitle: `1 tilt · 2 orbit · 4 pan` (7.2.2.0; `Hold 1 tilt · 2 orbit · 4 pan` would be cut off) /
  `Turn to tilt` / `Turn to orbit` / `Turn to pan` / `Put the cursor on it`.
- status line: `Undo` (1.2 s, feedback `ok`), `Hold all 4 for Home` (after a tap on 1, and while 3 or
  more buttons are down).
- buttons: Tilt `expand` · Orbit `shuffle` · Undo `back` · Pan `expand` (existing v6 icons); the held
  modifier is `lit: "on"`. No v6 icon reads as a vertical rotation (checked against every `ICONS_V6` glyph:
  `shuffle` is orbit's, `seek` is a slider, `power` / `clock` read as power and time), so Tilt borrows Pan's
  arrows; the label tells them apart. The app canvas (section 10) draws the legend `TILT · ORBIT · WHEEL · PAN`
  (1.0.0-cc5.6 rebuild for 7.2.2.0; Karl's `ZOOM` under F1 before, `HOME` in the first cc5.6 build).
- ring `off`; no `holdMarker`, no crumb (so the knob's ALIVE hold-1 / hold-4 rings never draw); no artwork.
  The rebuilt cc5.6 also gates them explicitly on the app canvas (`cc_alive.cpp`, a frame with `app`;
  mirrored in `alive_lights.py`, parity sequence `a2-app-no-hold-rings`).
- A refusal flashes feedback `err` + moment `refused`.
- Preview: `design-reference/onshape-knob-preview.png` (rendered through `lcd_preview`).

## 3. Controller mode `onshape`

- `MODES`, `PROFILES` (`SMOOTH OPERATOR`), `MODE_TITLES` (`ONSHAPE`), `_buttons_onshape`,
  `_press_onshape` and `_frame_onshape` are defined.
- The control's bounds are `(0, 65535, 32768)`, re-centred on every entry, and again after 400 ms of
  quiet once the knob has moved more than 30,000 detents from the centre.
- **Profile.** The runtime chooses it from the knob's inventory at connect: `SMOOTH OPERATOR`
  (127 detents per turn), else `SHAVED OPERATOR`, else Home's `BINARIS BEER`. The detent count per turn
  from the inventory scales the zoom rate.
- **Entry** (`enter_onshape`):
  - refused unless presentation is 6 or later;
  - refused while an overlay (the explorer, Up next or the picker, open or opening) or Seek is open;
  - drops an unsent Sonos volume target.
- **No Sonos volume writes** while the mode is on or a switch is pending (`onshape_pending`).
- **Leaving:** `disconnected()`, `set_hardware()` and `set_spaces(False)` leave the mode.
- The controller only presents. `onshape_input(kind, logical, delta)` takes the knob's `down`, `up`,
  `hold`, `turn` and `ready`, plus the injector's `refused` and `undo`.

## 4. Threads and plumbing

- **Held-key mask** (`Runtime.held_mask`, one bit per raw button):
  - set by `kd`, cleared by `release`;
  - re-seeded from `ready.held` (logical slots mapped back through `buttonOrder`);
  - cleared by every enter and on a lost knob.
- **FastPath** (`ui.FastPath`, the serial reader thread) **only enqueues**.
  - It posts every `position`, `limit`, `button`, `release`, `hold`, `ready`, `disconnected`,
    `released`, `error` and `closed` to the injector.
  - While the mode is `pending` or `active` it gives the floating knob and the Navigator no input.
- **Injector** (`control_center/onshape.py`, `OnshapeInjector`, thread `NanoD-onshape`):
  - It calls `SendInput` with the `INPUT` layout from `windows_actions.py`.
  - It acts only for the control id it was activated for.
  - It also runs the watchdog.
  - The Tk thread activates it (control id, `buttonOrder`, detents per turn) as soon as the controller
    enters the mode, and deactivates it when the mode is left.

## 5. Drags

- The button goes down on the **first detent** after the modifier key goes down.
- The first batch is: down, then out and back past `SM_CXDRAG` along the drag's own axis (x for orbit and
  pan, y for tilt; no net movement), so Onshape sees a drag.
  It never sees a click, so no context menu opens and no tab closes.
- Each move goes to `GetCursorPos() + delta × px` along x (tilt: along y, times `TILT_DRAG_SIGN`), as an
  absolute virtual-desktop move (the process is per-monitor DPI aware); px = `PX_PER_TURN` / the profile's
  detents per turn (11 on BINARIS BEER).
- **Release** happens on `ku` of the modifier, or at the **idle deadline**: 800 ms by default,
  settings.json `onshape_idle_ms` (200–5000). The button goes up, then the cursor goes back to where the
  drag began.
- `SM_SWAPBUTTON`: Onshape's right-drag is the physical left button when the buttons are swapped.
  Middle is never swapped.
- **`release_all`** runs on:
  - shutdown;
  - `disconnected` / `released` / `error` / `closed`;
  - focus loss (at once);
  - any exception in the injector;
  - `WM_WTSSESSION_CHANGE` (lock screen, disconnect or logoff; `SessionWatcher`, a message-only window);
  - a short `SendInput` return.
- **Ctrl+Z** is skipped while Shift, Ctrl, Alt or Win is physically held (`GetAsyncKeyState`).
- **cc5.4:** a lost `ku` can leave the logical mask set until the next key line. The idle watchdog still
  lets the operating-system button up. F1 fixes the mask properly.

## 6. Target

- Input is accepted only when `WindowFromPoint(GetCursorPos())` is the browser's **content widget** and
  its root (`GA_ROOT`) is the **Onshape window in the foreground**.
- Content-widget classes: settings.json `onshape_content_classes`. The default
  `["Chrome_RenderWidgetHostHWND"]` was recorded on this PC on 2026-09-30:
  - chrome.exe: top level `Chrome_WidgetWin_1`, content `Chrome_RenderWidgetHostHWND`;
  - Edge is the same Chromium widget;
  - Firefox is excluded, because its frame and content share one class.
- This excludes the tab strip, the toolbar and the bookmarks bar.
- Otherwise the input is refused: `Point at the model` on the knob, **at most one refusal per burst**.
  A burst ends after an idle deadline without input.
- **Keystrokes also need the keyboard focus in the page.** Undo (Ctrl+Z), the command wheel's chords and tool
  search, B-mode typing (Ctrl+A and the typed value) and the Ctrl / Shift parameter scrolls go out only when the
  keyboard focus lies inside the web page under the cursor: UI Automation (`browser_url.focus_in_page`) finds the
  outermost web Document at the cursor and checks that the focused element is inside it. Focus in the address
  bar, the find bar, docked DevTools or another window refuses the keystroke, so it never lands there.
  - Zoom notches, drags and plain (no-modifier) parameter scrolls keep the cursor check alone.
  - The answer is cached for 250 ms (`KEY_FOCUS_CACHE_SECONDS`). When UI Automation cannot tell, the cursor check
    alone decides, as before. Nothing about the focused element is stored or logged.
  - A refusal shows the usual `refused` feedback (feedback `err` + moment `refused`, `Point at the model`), at
    most once per burst; status.json `onshape.injector` counts it in `refusals` and in `focusRefused`.
  - Clicking the model gives the page the focus again.
- The cursor is never warped to find the canvas.

## 7. Auto, Manual and Off

Settings → Knob → **Onshape mode**: Off (the default) / Manual / Auto (settings.json `onshape_mode`).

- **Auto:**
  - It watches `EVENT_SYSTEM_FOREGROUND` plus `EVENT_OBJECT_NAMECHANGE` for the foreground browser's
    process only (`FocusWatcher`), so a tab switch within one window is seen. A 250 ms title poll is the
    fallback.
  - **Strict match:** the exe is `chrome.exe` or `msedge.exe`, and after the browser suffix, Edge's
    `and N more pages` and a trailing Edge profile are removed, the **last** ` | ` / ` - ` segment is
    exactly `Onshape` (`onshape.ONSHAPE_TITLE`).
  - **Check on first use:** the Onshape tab title could not be seen on this PC. status.json
    `onshape.focused` shows whether the rule matches (no title is ever stored or logged). If it stays
    false with Onshape in front, adjust `ONSHAPE_TITLE`.
  - It enters at once. Sonos volume ignores the knob while the switch is pending.
  - It never enters while an overlay or Seek is open.
  - It leaves **500 ms** after Onshape lost the foreground, back to Home. Held input is released at the
    loss.
  - **All four buttons held 1.0 s** (or the tray's Leave) exits and suppresses Auto until Onshape loses
    the foreground and gains it again.
- **Manual:** the tray's `Onshape mode` / `Leave Onshape mode` item enters and leaves. Injection still
  needs Onshape in the foreground and the cursor over its content.
- **Off:** the tray item explains where to turn the mode on. Choosing Off leaves the mode.
- **Address bar (Auto and Manual):** to tell Onshape from other sites, Auto and Manual read the
  foreground browser's address-bar **host** through UI Automation (`browser_url.address_host`):
  - only the host is kept from the address-bar text (the rest is dropped at once); the host is turned
    into an Onshape / not-Onshape verdict and is **never stored or logged**. The verdict is cached per window and title for 5 s
    (`ADDRESS_CACHE_SECONDS`);
  - the read runs on one background worker (`AddressVerdicts`), never on the Tk thread, with UI
    Automation bounded by `ADDRESS_UIA_TIMEOUT_MS`. A window not read yet counts as not Onshape until
    it is. Only when no host can be read does the strict title rule above decide.
- **Off reads nothing:** with Onshape mode Off the foreground watcher is not polled. No window title and
  no address bar is read, and no `EVENT_OBJECT_NAMECHANGE` hook is installed (switching to Off drops
  it).

## 8. status.json `onshape`

The section holds:

- `mode`, `active`, `pending`, `focused`, `suppressed`, `profile` and `refusals`;
- `injector`, with these fields:
  - `active`, `action`, `dragging`, `injects` and `idleMs`;
  - the counts `wheel`, `drags`, `moves`, `undo`, `undoSkipped`, `refusals`, `focusRefused`, `short` and
    `errors`;
  - `releases` by reason.

It never holds a title.

## 9. Tests

`tests/test_onshape.py` covers:

- kd → p×N → ku gives exactly one down, the moves and one up, with the cursor restored;
- the watchdog, and release on an exception, on shutdown, on every lost-knob kind, on focus loss, on a
  session change, on a short return and on `ready`;
- no tap and no `kh` after a turn;
- no Sonos volume writes while a switch is pending or the mode is active;
- the title table, including a tab switch within one window;
- the content widget refusing the tab strip;
- swapped buttons;
- Navigator and floating-knob gating;
- `device._frame` (presentation 6, and the presentation-5 downgrade parsing clean);
- presentation 6 or later only;
- the simulator and the smoke test never injecting.

---

# A2: Karl's Onshape UI on the knob, the command wheel and parameter mode — Desk Dial 7.2.0.0, `desktop-dist-v7-e`

Firmware 1.0.0-cc5.6 draws Karl Malota's Onshape app UI on the knob (the **app canvas**, capability
`appCanvas: 1`; `firmware/CONTROL_CENTER.md` "App canvas", `firmware/BUILD-cc5.6.md`). Desk Dial
7.2.0.0 drives it. Adapted from `katbinaris/NanoD_RatchetH1` @ `feat/firmware-esp-idf-quadra`
(`app_mode.c`, `app_profiles/onshape.c`, `display_task.cpp`, `ui_*.cpp`), with permission.

## 10. The app frame and its gate

- In Onshape mode the controller adds the frame's `app` object: `id` `onshape`, `slot` (zoom / orbit / pan / tilt,
  from the held modifier), `refused` (the 2 s `Point at the model`), `flash` (Undos sent), and from the
  injector (`OnshapeInjector.app_state()`, copied by the runtime every Tk tick) `wheel`, `param`, `echo`.
  Schema: CONTROL_CENTER.md "App canvas" (values in thousandths; `device.app_parse` is the firmware's reading).
- `device._frame` keeps `app` only when the knob reports **presentation ≥ 6 and `appCanvas: 1`**
  (`device.app_capability`). An older knob (cc5.5, cc5.4 D) never sees it and shows A0's text frames (section 2),
  which every app frame still carries as its fallback. An invalid object is stripped (the firmware would reject
  the frame).
- The injector gets `app=True` on activation only for such a knob. Without it the input is exactly A0's:
  tap 3 = Undo, no wheel, no parameter mode (a blind wheel would run commands the user cannot see).
- The knob draws the cube from its own sensor angle (no host latency), lights the keycaps from its own buttons,
  times the button-3 hold bar locally and starts the idle plasma after 5 s. Desk Dial only sends state changes.

## 11. The command wheel (hold 3)

State machine: `control_center/onshape_app.py` (`OnshapeApp`, pure; the injector thread calls it and runs its
actions after the same target check as zoom).

| Input | Effect |
|---|---|
| Press 3 | the wheel opens hidden, on the entry last run in the current ring (initially the first command) |
| Release 3 before 250 ms, never turned | a tap: **Undo** (Ctrl+Z; the knob flashes F3 UNDO) |
| Hold 3 for 250 ms, or turn once | the wheel shows (the first detent only reveals it) |
| Turn while it shows | one entry per 1/12 turn (10.6 detents of SMOOTH OPERATOR), clamped at entry 0 (cancel) and the last command: soft walls, no wrap; reversing at a wall moves at once |
| Press 1 while it shows | MODEL ↔ MODIFY; press 2 SKETCH; press 4 VIEW (each on that ring's last-run entry) |
| Release 3 | runs the entry (entry 0 closes); the knob echoes its card for 1.1 s (commands with a parameter echo on OK) |

- Keys pressed while the wheel is open (the ring switches) do nothing else until released: no drag, no tap
  (the controller swallows them too). A third button down (the Home chord) closes the wheel **unrun**.
- 3 pressed while 1, 2 or 4 is held (tilting, orbiting or panning) does nothing.
- Hold-and-release without turning **repeats** the last command of that ring (Karl's design; open question).
- A release lost while the knob re-entered (`ready.held`) closes the wheel without running anything.
- **No haptic walls yet:** the Onshape control stays SMOOTH OPERATOR over 0..65535; the wheel's ends stop the
  selection, not the knob. Real walls (a `detent.list` feel and bounds) come with F2's feel tokens.

## 12. Parameter mode

After **EXTRUDE, FILLET, CHAMFER, SHELL** (MODEL) or **TRANSFORM, MOVE FACE** (MODIFY) the knob sets the
dialog's number until 3 ends it.

| Input | A: scroll (default) | B: type |
|---|---|---|
| Turn (1/16 turn per step) | one wheel notch over the field under the cursor per step; the knob shows the change (+0.30) | the value (from the command's start: DEPTH 25, RADIUS 1, ...) moves and is clamped to its range (a wall bump nudges the card); nothing is sent while turning |
| Knob alone / 1 held / 4 held | 0.1 (no modifier) / 0.01 with **Ctrl** (1/48 turn per step) / 1.0 with **Shift** | the same steps |
| Knob rests 350 ms | — | **Ctrl+A**, then the value typed with its unit (Unicode keystrokes, e.g. `27.50 mm`) |
| Tap 2 | switch to B | switch to A (remembered across commands) |
| Tap 3 (< 600 ms) | **Enter** | a pending retype, then **Enter** |
| Hold 3 ≥ 600 ms, release | **Esc** (cancel; no echo) | **Esc** |

The starts, ranges and steps are millimetres (Karl's metric values). B types the unit with the number, so a
document set to inches still gets the millimetre value (Onshape converts `27.50 mm`); A scrolls the field in the
document's own unit.

Buttons 1, 2 and 4 are steps / the A↔B switch here, never a drag. Three or more buttons down (the Home
chord) step nothing and send neither Enter nor Esc; parameter mode stays open unless Home fires.

## 13. Windows shortcuts (Karl's macOS chords translated; Onshape help "Keyboard shortcuts")

| Ring | Command | Windows | Verified |
|---|---|---|---|
| MODEL | SKETCH / EXTRUDE / REVOLVE / FILLET | Shift+S / Shift+E / Shift+W / Shift+F | yes (shortcut page) |
| MODEL | CHAMFER, SHELL | tool search: **Alt+C**, type `chamfer` / `shell`, Enter | Alt+C yes; that the phrase's first hit is the tool: **no** |
| MODIFY | BOOLEAN, SPLIT, TRANSFORM, PATTERN (`linear pattern`), MIRROR, MOVE FACE | tool search as above | phrases: **no** |
| SKETCH | LINE L, RECTANGLE G, CIRCLE C, ARC A (3-point), DIMENSION D, TRIM M, CONSTRUCTION Q | single keys (only inside a sketch) | yes |
| VIEW | FRONT Shift+1, RIGHT Shift+4, TOP Shift+5, ISOMETRIC Shift+7, NORMAL TO N, ZOOM TO FIT F, SECTION Shift+X | | yes |
| — | Undo | Ctrl+Z | yes |
| — | numeric field steps | scroll 0.1, Ctrl+scroll 0.01, Shift+scroll 1.0 (help "Numeric fields") | yes (help); hover vs. focus, and whether Chrome's Ctrl+scroll zoom wins: **not verified** |
| — | commit / cancel a dialog | Enter / Escape | yes |

Keys go out only with the cursor over Onshape's model, the keyboard focus inside that page (section 6) and no
real Shift / Ctrl / Alt / Win held (as Undo). The **no keys while a real modifier is held** rule also covers the
parameter scrolls (a real Ctrl would zoom the page, a real Shift would turn a 0.1 notch into a 1.0 step) and B's
typed value (Ctrl+A and the text would become shortcuts): nothing goes out, the count `commandsSkipped` grows,
and a B value that was not typed stays pending and is retyped at the next rest.
Tool search waits 250 ms after Alt+C and 400 ms after the phrase (Karl's 25 / 40 ticks), scheduled on the
injector thread (never a sleep). The knob's wheel shows the same chords (`cc_app_onshape.c`; the tests hold
both tables equal) as CTRL / ALT text keycaps and the shift arrow. status.json `onshape.injector` adds the
counts `commands`, `commandsSkipped`, `scrolls` and `typed`.

## 14. Tests and preview

- `tests/test_onshape_app.py`: the wheel (tap vs. 250 ms, reveal, 12 per turn, walls, ring jumps, memory,
  swallowing, search macro, lost release), parameter mode (A notches and modifiers, B clamp / bump / retype,
  OK / cancel, echo), the Windows table and virtual keys, the firmware table parity, the injector with a fake
  backend (A0 without the capability, refusal off target, macro waits), `device._frame` gating (appCanvas and
  presentation 6 only; older firmware keeps A0), the controller's frame and hold-1 suppression, the runtime's
  activation.
- `harness/app_canvas_tests.py`: the firmware's own drawing and parsing code (MSVC): 32 parse cases
  held to `device.app_parse`, 23 rendered screens, and the contact sheet
  `design-reference/onshape-ui-contact-sheet.png` (with Karl's own `tools/ui_preview` renders for comparison).

---

## 15. Tilt: hold 1 + turn (Desk Dial 7.2.2.0, `desktop-dist-v7-g`; firmware 1.0.0-cc5.6 rebuild)

- **Input** (`onshape.KeyTracker.MODIFIERS` `{0: "tilt", 1: "orbit", 3: "pan"}`, `OnshapeInjector._drag_turn`):
  hold 1 + turn is a **right-button drag along y**. Onshape's default mouse preset rotates on a right-drag, and
  vertical motion pitches the view about the horizontal screen axis. Same machinery as orbit: the button goes
  down on the first detent, the out-and-back threshold step (here along y), one absolute move per detent of
  `PX_PER_TURN / detents` px, the button up and the cursor restored on the release of 1, the idle watchdog, the
  target check with one refusal per burst, swapped buttons, `release_all`.
- **Direction:** `onshape.TILT_DRAG_SIGN = 1`: a clockwise turn drags **down** (screen y grows), expected to
  bring the model's top toward you (more of the top face, as the knob's cube shows); counter-clockwise drags up.
  Not yet checked against Onshape by eye: if it turns the other way, flip the constant; the knob's cube pitches
  from the shaft on its own (clockwise = more top face), so it would then need the same flip in firmware.
- **Unchanged:** the knob alone zooms; hold 2 orbits (x), hold 4 pans, tap 3 is Undo, hold 3 opens the wheel,
  all four held 1.0 s is Home and wins over everything (a tilt begun with two buttons down ends when the third
  goes down). The newest held modifier wins (1 then 2 = orbit; releasing 2 tilts again), each switch releasing
  the old drag first. Inside the wheel 1 still steps MODEL ↔ MODIFY and in parameter mode 1 held is still the
  0.01 step: neither ever tilts. A tap on 1 sends nothing (the text screen says `Hold all 4 for Home`).
- **Knob (app canvas):** the frame's `app.slot` is `tilt` (appended to the wire enum: zoom 0, orbit 1, pan 2,
  tilt 3; `device.APP_SLOTS`, `CCAppSlot`); capability still `appCanvas: 1` (Desk Dial 7.2.1.0 and older never
  send `tilt`, and an older knob never gets `app`). **Install order:** the capability cannot tell the new cc5.6
  build from the one on the knob before it (image `d3d2c235…`), whose parser rejects `tilt`; Desk Dial 7.2.2.0
  on that firmware would have the frame refused while 1 is held (Desk Dial then drops the connection as for any
  refused command). Flash the rebuilt cc5.6 first (BUILD-cc5.6.md "Rebuild: F1 TILT"), then install 7.2.2.0. The cube **pitches** with the knob's own shaft angle
  (one-for-one, the same 32-per-turn stepped poses as orbit, counted from the 30° isometric rest), a vertical
  dotted ring beside it carries the amber marker at the current pitch, the action line reads `F1 TILT`, and when
  tilt ends the pitch eases back to the 30° rest (nearest turn) over the same 220 ms as orbit's settle.
  Contact sheet: `design-reference/onshape-ui-contact-sheet.png` (TILT frames).
- **Tests:** `test_onshape.TiltTests` (y-axis drag: one down, the moves, one up, restore, watchdog, refusal,
  swap, the 1 ↔ 2 switch, same travel as orbit), `ChordInjectorTests` (the chord still wins), the frame / copy /
  button-row tests; `test_onshape_app` (3 while tilting, the wheel's and parameter mode's 1, the `tilt` slot in
  the frame and in `device.app_parse`); `harness/app_canvas_tests.py` (parse cases `tilt` / bad
  `TILT`, the tilt renders and the settle).

## 16. r4 feel in Onshape mode (Desk Dial 7.3.0.0, `desktop-dist-v7-h`; firmware 1.0.0-cc5.7)

- **Feel** (firmware `HAPTICS.md`; capability `feel` 1): the knob alone zooms in `detent.value` (BINARIS BEER's 67
  soft SINE steps per turn, the same travel as 7.2.2); while a modifier is held (1 tilt, 2 orbit, 4 pan) the feel is
  `fluid.light` (viscous, Kd 0.02, no detents; positions still count at 67 per turn, so the drags move the same pixels
  per turn). `Controller.feel()`; `onshape_input` re-enters on a modifier's down or up when the feel changes, and only
  for an r4 knob (`Controller.feel_supported`, set from the capabilities): the new control re-anchors under the finger
  with feel.fade (120 ms), so no detent drops. An older knob never re-enters for this (7.2.2's behaviour exactly).
  To check by feel: a turn that starts at the same instant as the modifier press may lose its first ~50 ms (the
  re-entry's window); if that shows, the fix is to keep one control and let the firmware switch on the held key.
- **Events:** Undo ticks (`_feedback("ok")` -> `confirm.tick`), `Point at the model` refuses (`refuse.buzz`, at most once
  a second, as the refusal line is once per burst). The Home chord lands on the launcher with its own control (no
  thump: it is not a hold-1 landing).
- **Walls:** none (0..60000 re-centred at 25,000 from the centre; the firmware's uint16 range fix now also makes the
  full 0..65535 safe).
- **Tests:** `test_r4_feel.FeelMapTests` (zoom / orbit feels, the re-entry only for an r4 knob).
