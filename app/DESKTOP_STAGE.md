# DESKTOP_STAGE: the desktop rendering contract (desktop v7)

Status: **frozen build contract (K4)**, written 2026-09-25 for the one combined release **firmware 1.0.0-cc5.4 + desktop v7**: the "Warm · alive" LED engine plus the whole r2.1 master design. Documents only: nothing was built, shown on screen or run for this file.

Review amendments (2026-09-25): two-leg motions read per leg (S5-31); the floating knob's engine renders once per message while hidden (§11.2, K2 M27); glow radii in K2's unit (§11.3); the GIL rule covers JSON and XML parses (§4.7.3); snap placement uses posted calls only, with a hard deadline and no activating re-maximize (§9.6, §9.7, S5-32); the explorer draws its empty, sign-in and error states (§7.4, S5-33, VOC-K4-04).

Consistency pass (2026-09-25, across K1–K4): the presenter API takes K3's pushed payloads with `t0` (the one QPC clock, VOC-R25) and the extra fields, and emits `snap_result(side, accepted)`, `cancel_result(restored, completed)` and `system(motion)` (§2.3, §4.1); the snap advance goes to the next unassigned window after the snapped one (§9.5, K3 C5-46); no toast after a `hold` close (§9.7); the explorer enters at the index K3 sends and drops old-control positions (§5.3, §7.6); context strings and `data` patches as K3 sends them (§8.2, §8.3); the hidden floating knob follows K2 M27 with its catch-up (§11.2) and one knob budget, ≤ 2.5 ms p95 (P6, §11.4); the hidden-render test is H9 (§6.6); the knob art row points to K3 §10.5 (§13.1); `disconnect` on the knob per VOC-R23 (§15); VOC-K4-01…04 absorbed (§21.3); no floating-knob tooltip (§11.1, VOC-R24).

**[r2.2] amendment (2026-09-25, late; design follow-up r2.2, VOC key `R22`, VOC-R26…R29).** Up next only: Like is add-only for good, so the **unlike (heart-off) animation is withdrawn** and a `likes` patch only ever pops a heart in (§2.3, §8.3, §8.5, S5-31); the row heart has **four distinct looks** (liked: filled `#FF285A`; not liked: outline at 45 %; not known yet: **dashed** outline, dash 2.2 / gap 2.4, at 30 %; not in Apple Music: outline at 15 %, no Like) (§8.3, S5-34); the hint reads **`[3] Liked`** on a liked row (§8.2); VOC-K4-02's copy is now `Couldn’t open on screen` (§21.3). Seek, Play next and the copy approval change nothing drawn here; the floating knob's LCD mirror picks up the `liked` footer through K1 (§11.5). Every change is tagged **[r2.2]**.

**[errata] Phase-2b gate (2026-09-26; lead rulings R-i, R-l and R-h).** Docs only: recorded in §21.4 and tagged **[errata]** or **[erratum R-i]** in place. **R-i** corrects H9 for a summon by a message: the floating knob's first visible frame equals the K2 M27 reference, and the comparison with the continuously rendered twin (within 0.02) applies from +300 ms of visible frames (§6.6 H9, §11.4; E-i). The fast-lane art worker `NanoD-art-fast` joins §2.2 and §13.4 (E-t). **R-l** accepts the build deviations WP7b-D1…D7 and WP8-D1…D9 as built. Since the phase-3 build, K3's `windows_cancel` carries the close `reason` (K3 C5-78), so WP7b-D6's inference is only the fallback for a payload without one (§2.3; E-c). **R-h**'s step 3 (the picker chrome on the GPU, WP7c) is §9.10; it draws the fly's shadow, so S5-4 and WP7b-D7 hold for the step-1 CPU chrome only (§9.5; E-h).

**[errata] Phase-3b decisions (2026-09-26; the lead).** Docs only: recorded in §21.5 and tagged **[errata]** in place. The H5 parse bench's result is §4.7.3's; §6.3's step-3 row is v7's picker row; S5-4 holds for the step-1 fallback chrome only; the picker's GPU chrome is wired in the app (§9.10); WP8-D10 (with the S1 pickup threshold), WP7c-D1…D13 and KE-1…KE-4 are accepted.

**[proposed errata] Frame-drop fixes (2026-09-26; pending the user's acceptance).** The on-screen tours of 2026-09-26 led to fixes that the code carries but this contract did not yet say: uploads a frame ahead with a bind-only reveal (§4.5; E-S1), the open's t1 margin of one P (§4.6.5 item 1, G1-6; E-S2), designed holds that are not missed frames and the in-motion fields §6.3's judge reads (§6.2, §6.3; E-S3), and the picker loop's lock rule (§5.1 P5; E-P1, with CAROUSEL.md §12.5). Recorded in §21.6 and tagged **[proposed erratum]** in place; they take effect when the user accepts them, and the on-screen re-run is judged against the amended text. The thumbnails' re-registration on animated frames stays an open item (O-R1).

This file decides how every desktop surface is drawn, moved, paced, measured and torn down. Every token, id and copy id it uses comes verbatim from `firmware\V5_VOCABULARY.md` (VOC). The few additions it needs are listed as `VOC-K4-nn` in §21.3.

| This file owns | Owned elsewhere |
|---|---|
| The DirectComposition **stage engine** and its two scenes, `explorer` and `upnext` | When an overlay opens or closes, re-entry timing (190 / 200 / 380 / 420 ms), confirmation policy, copy text and when a toast is raised: **K3** `CONTROL_CENTER_V5.md` |
| The picker v2 presentation, the snap tray, the fly and the window placement recipe (VOC §8.4) | Wire, parser and knob LCD: **K1** `PRESENTATION_V5.md` |
| The toast presenter | LED targets and effects, including the engine output `e` that the floating knob draws: **K2** (ALIVE rev 2) |
| The floating knob's drawing and frame loop | Settings and its status strip: **K3** |
| Blur recipes, the desktop art pipeline, memory budget | The icon and font exports: WP9 |
| Frame pacing, FrameStats, the desktop acceptance thresholds, the G1 spike | The acceptance record itself: K5 `ACCEPTANCE.md` (WP9) |

---

## 0. Keys, precedence, conventions

### 0.1 Source keys

VOC §0.1 keys are used as defined there: R, CH, S01…S05 (S01 App A/B/C = its appendices), BS (**r2.1** line numbers), HT, KM, 00, A01…A06, CS, CP, CL, CF, RP, RA, LC, RF0…RF3 (with AR-1…AR-22 from RF0's adversarial review), AL, P4, CAR, FK, PR, DV, CT, RT, UI, OV. Added here (all under `app\`):

| Key | File |
|---|---|
| CA | `control_center\carousel.py` |
| CR | `control_center\carousel_render.py` |
| KFC | `control_center\knob_face.py` |
| AW | `control_center\artwork.py` |
| WN | `control_center\windows.py` |
| SO | `control_center\sonos.py` (as K3 uses it) |
| ST | `standalone.py` |
| LP | `control_center\lcd_preview.py` |
| AI | `APP_ICON.md` |
| MS-n | Microsoft Learn pages, listed in §23 |

Citations are `KEY:line` or `KEY §n`.

### 0.2 Precedence

- **Behaviour and look:** r2.1 README > S01 (with App A motion, App B blur, App C copy) > S02 > S03 > S04 > S05 > the BS prototype (VOC rule 3).
- **Motion:** App A is the motion authority: "Every animation is listed as a tuple in 01 appendix A" (R:123). Where App A is silent, BS's values apply, including its CSS `ease`. Where App A is ambiguous (one `ms` for a two-leg tuple such as the heart's `0.4 → 1.5 → 1` or an end bump's `0 → ∓14 → 0`), BS's reading applies: the duration is per leg (S5-31).
- **Feasibility:** the engineering analysis (00 and its sources, RF0 with its adversarial review) with r2.1 applied on top.
- **User decisions** are binding (VOC header; task). **Engineering rulings** already made are kept unless r2.1 contradicts them with good reason.
- Every departure from r2.1 has an `S5-n` id with a reason (§21).

### 0.3 Units, k, the stage, the monitor

| Term | Definition | Source |
|---|---|---|
| unit | one px of the prototype's 1280 × 720 reference stage | S01:445 |
| **k** | `min(W / 1280, H / 720)` of the chosen monitor, in physical px (`layout_for`, CR:221-229). For every monitor 16:9 or wider this equals r2.1's "scale by height" (H / 720). For narrower monitors, where r2.1 is silent, it fits the width, as v6 does | S01:445; CR:221 |
| stage | the 1280 × 720-unit box centred on the monitor | S01:447 |
| **wide** | `W / k > 1281`. Wide monitors use the **32:9 tables** of the explorer and the picker; others use the 16:9 tables. This is BS's `wide = SW > 1280` | BS:1142, :1170 |
| the user's monitor | Samsung Odyssey G93SC, 5120 × 1440 at 240 Hz, 100 % scaling: **k = 2**, stage 2560 × 1440 px at x 1280–3840, monitor edge ±1280 units from the stage centre; `rcWork` 5120 × 1392 | RF2 §2.1; RA §3.1; S01:264 |
| rest pixels | every rest position and size is `round(units × k)` physical px, so text sprites at rest land on whole pixels | RF0 §3 rule 12 |
| monitor choice | the monitor holding the foreground window when the overlay opens (`MonitorFromWindow(GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY)`), as the picker does today. Toasts use the same rule at show time. The floating knob stays on the primary monitor | CAR:53; S01:421; FK §4 |

### 0.4 Curves

| Name | `cubic-bezier` | Where it is used | Source |
|---|---|---|---|
| **OUT** | (0.22, 1, 0.36, 1) | the default | S01:468; BS:474; CA:131 |
| **IN** | (0.4, 0, 1, 1) | exits: explorer card exit, Up next shuffle fade, toast exit | S01:468 |
| **SPR** | (0.34, 1.45, 0.64, 1) | snap tray, toast scale, the heart | S01:468; CA:132 |
| **EASE** | (0.25, 0.1, 0.25, 1), CSS `ease` | only where App A is silent and BS says `ease`: tray slot border, slot empty glyph, slot badge, picker cards-group fade, Up next shuffle-line colour | BS:65, :68, :71, :81, :235 |

- r1's HEART curve (0.34, 1.6, 0.64, 1) is retired. r2.1 draws the heart with SPR (S01:495; BS:255).
- The floating knob's slide keeps v5's ease-out cubic (in, 220 ms) and ease-in cubic (out, 260 ms) (FK:121; OV:86-87).

### 0.5 CSS semantics the stage reproduces

1. **Transforms.** The prototype appends enter offsets after the table scale, so they act in the scaled space: an enter rise of 30 units on a card at table scale S moves it 30·S units, and the enter scale 0.9 multiplies S (A03 §0; BS:1175, :1206). The stage animates these as separate properties (§4.6.6).
2. **Scale origins:** the card centre (explorer, picker, fly), the row's left-middle point (Up next, `transform-origin: 0 50%`, BS:244), the bar centre (tab underline), the tray container centre (snap tray).
3. **Opacity** on an element with children is **group opacity**. The stage uses `DCOMPOSITION_OPACITY_MODE_LAYER` wherever children overlap (§4.4).
4. **Transitions retarget, never queue.** A new target starts a transition from the current value over the full duration; a target equal to the current target changes nothing (CAR §4; CA:135-174; S01:476).
5. **Text changes at rest.** A text swap happens when the detent lands (the moment the new index is known), then the new text fades in 0 → 1 over 160 ms OUT (S01:118, :484; BS:791-798).

### 0.6 Time

- **One clock: QPC** (`time.perf_counter()`). DirectComposition frame statistics report QPC ticks with an explicit `timeFrequency` (MS-4). Absolute animation begin times are taken to be QPC ticks too; the unit is undocumented (MS-3; AR-14) and G1 check P7 confirms it (§19).
- **P** = one refresh period, `qpcRefreshPeriod` from `DwmGetCompositionTimingInfo(NULL)`: 4.1667 ms here (RF2 §2.1). Every threshold below is written in P. P is re-read on `WM_DISPLAYCHANGE`.
- **Schedule, don't wake.** Any motion whose start is known when it is triggered is committed at the trigger, with its future start expressed as a hold segment (§4.6.4). Examples: the explorer's new-source entry at +190 ms, the overlay close at +380 ms after Play. Python wakes only for content that becomes ready and for clean-up, and both tolerate ±1 frame.

### 0.7 Pixels and colour

- Surfaces are premultiplied BGRA8: `DXGI_FORMAT_B8G8R8A8_UNORM` (87) with `DXGI_ALPHA_MODE_PREMULTIPLIED` (1) for sprites with alpha, and `DXGI_ALPHA_MODE_IGNORE` (3) for opaque content (covers, frost, ambient).
- Compositing is in gamma-encoded sRGB, as in the browser prototype and v6 (CAR §3). The output is SDR (colour space 0, RF2 §2.1).
- Sprites are prepared at physical resolution and never upscaled on the fly (RF0 §3 rule 12). Blurred layers and shadows are the exception: they are stored small on purpose and stretched by the compositor (§12).

---

## 1. The decisions in one page

1. **Two engines.** The explorer and Up next are scenes on one new **DirectComposition stage** (thread `NanoD-stage`, one full-monitor, non-activating, click-eating host window). All their motion is **compositor-run**: DWM evaluates the curves at every composed frame, so Python does **no per-frame work** (RF0 §2.0). The picker keeps its **v6 window stack** (layered windows + DWM thumbnails, activatable host) with pacing and compose fixes (VOC-D05; S5-2).
2. **Curves** are the CSS cubic-béziers fitted as piecewise cubic segments, with ≤ 0.5 px error over each tuple's largest travel (AR gate; RF2 §2.3 measured 0.24 px with 8 segments). **Retargets** start at the next compositor frame from the exact value of the curve DWM is running (AR-14).
3. **Sampling is LINEAR with SOFT borders, never nearest** (AR-8). Covers are kept in two resolution levels to limit minification shimmer (S5-28).
4. **GIL rules:** only pure property setters use GIL-keeping `PYFUNCTYPE` calls. `Commit`, surface draws, device work, waits and window calls release the GIL (AR-16). The switch interval is **1 ms**, never below (AR-1). `timeBeginPeriod(1)` plus the Windows 11 power-throttling opt-out (AR-2).
5. **Input:** the stage host never activates and **eats every click**. A left click on the centre card or focused row acts as Button 4; nothing else acts. The wheel is eaten, and keys stay with the foreground app (AR-4; S5-3, S5-23).
6. **Python-stepped surfaces** (the picker's thumbnails and chrome, the floating knob's ring, the toast) pace on the **compositor clock**, sample the curves at the **predicted display time**, judge pacing by wake intervals, and lock to every second vblank with hysteresis when they can't hold every vblank (AR-10).
7. **Proof of 240 Hz** comes from displayed frames: `DCompositionGetTargetStatistics` for the stage, present cadence plus PresentMon for layered windows, and changed-frame lateness for the knob ring (AR-13, AR-22). Gate: explorer, Up next, floating knob and toasts at 240; the picker at a steady 120 until its chrome moves to the GPU (RF0 §5).
8. **Floating knob:** the `AliveLights` engine runs on the overlay thread, fed by a serial fast path; the ring is composed **at every vblank while visible**, with **six pre-rendered glow looks**, straight into the DIB (user decision; S02 r2; RF1 C1 + C2; AR-9).
9. **Art:** requests of 1200 / 600 / 240 px (Sonos 400), an encoded LRU and a prepared-sprite LRU, decode and resize off the GIL, first build ≤ 20 ms per cover, the Extended / Generated / loading sleeves exactly as r2.1 draws them.
10. **Snap:** the fly animates the live thumbnail's rectangle with a uniform scale; the real window moves **once at 360 ms**, restored **without activation** (never `SW_RESTORE`, VOC-D01), with frame compensation and verification, on a worker thread that reaches the target only through posted calls and resolves every job by a **hard 800 ms deadline** (§9.6).
11. **G1 spike** (supervised, with the user's go-ahead) proves compositor-run 240 Hz with frame statistics, the input contract, capture exclusion, sampling quality and memory **before** WP8 builds the music scenes (§19).

---

## 2. Surfaces, threads, windows

### 2.1 Surface table (VOC §7.1 ids)

| Surface | Thread | Window(s) | Composition | Python per frame | Focus | Input (§3) |
|---|---|---|---|---|---|---|
| `explorer`, `upnext` | **`NanoD-stage`** (new) | one host, `rcMonitor`, `WS_POPUP`, ex `WS_EX_TOPMOST \| WS_EX_TOOLWINDOW \| WS_EX_NOACTIVATE \| WS_EX_NOREDIRECTIONBITMAP` (0x08200088) | DirectComposition target, DWM-run animations | **0** | never | click-eating |
| `picker` | `NanoD-carousel` (v6) | dim (monitor), glass (monitor), **host (now monitor-sized)**, chrome (a band, §9.2) | `UpdateLayeredWindow` + DWM thumbnails | thumbnails + chrome while moving | **takes focus** (v6 contract) | host eats clicks; centre-card click = Switch |
| `toast` | `NanoD-carousel` (a service, no longer tied to a picker session) | toast layered window, ex 0x080800A8 | ULW | only while the pill animates | never | click-through |
| `knob` | `NanoD-overlay` (v5) | layered window, ex 0x080800A8 | ULW, double-width DIB | ring at every vblank while visible | never | click-through |
| `settings` | Tk | Tk window | — | — | normal | normal (K3) |
| `tray` | pystray (ST) | — | — | — | — | — |

There is **no main window** (R:42; S01:453).

### 2.2 Threads

| Thread | Owns | Never does |
|---|---|---|
| Tk (existing) | the controller (K3), `ui.py`, Settings, the F24 hotkey, the Tk-side presenter facades | per-frame work; window calls on another thread's windows (FK §1) |
| `NanoD-stage` (new) | the stage host window, the D3D11 and DirectComposition devices, every COM object of the stage, stage uploads and commits | Tk calls; waits on other threads while holding the GIL |
| `NanoD-stage-capture` (new; a `CaptureWorker` instance, CA:686) | the stage's desktop capture and frost and ambient builds | HWND calls, apart from `BitBlt` on the screen DC |
| `NanoD-carousel` (v6) | the picker windows, DWM thumbnails, chrome compose, the toast window | music scenes |
| `NanoD-capture` (v6) | the picker frost and toast glass captures | — |
| `NanoD-overlay` (v5) | the floating knob window, DIB, and in v7 the `AliveLights` engine (§11) | Tk calls |
| `NanoD-art-1`, `NanoD-art-2` (new) | fetch, decode, resize and sleeve builds (§13), at `THREAD_PRIORITY_BELOW_NORMAL` | GIL-holding C calls over 1 ms while an animation episode runs (§4.7.3; the same rule binds K3's service lanes, including their JSON and XML parses) |
| `NanoD-art-fast` (new; WP8-R1, **[errata]** 21.4 E-t) | the art pipeline's **fast lane** (§13; `ArtService`, `LANE_FAST`): the 1 × 1 tick uploads that time the scenes' delayed work (the ambient's 200 ms and the big cover's 120 ms debounces, the 150 ms sharpen, the switch swap end), the ambient builds, the labels, row and column text, loading tiles, sharpen sprites and statics, and plans (any art worker takes those), at `THREAD_PRIORITY_BELOW_NORMAL`. It shares the two art workers' CPU slots (at most 2 jobs compute at once; a tick takes none), and `NanoD-art-1` / `-2` help with its lane when no art job is due | network I/O (it never fetches, so a tick lands within one fast-lane job, ≤ ~7 ms, of its `not_before` whatever the fetches do); art-lane jobs (C2, fetch, decode, sleeves); GIL-holding C calls over 1 ms while an animation episode runs (§4.7.3, as the art workers) |
| `NanoD-snap` (new) | real-window placement and verification (§9.6), each job under a hard deadline | any call that waits on another process's thread (only `ShowWindowAsync` and `SetWindowPos` with `SWP_ASYNCWINDOWPOS` reach a target window, §9.6); anything that can block the Tk or carousel thread |
| serial reader (DV, existing) | device I/O; in v7 it also posts the **input fast path** (§5.3) | HWND calls other than `PostMessageW` and `SetEvent` |

Every native thread keeps the v5/v6 skeleton: per-thread PMv2 DPI awareness (`SetThreadDpiAwarenessContext(-4)`), a module-level WNDPROC thunk that is never freed, a newest-wins mailbox plus `PostMessageW` (and, for threads that wait on the compositor clock, an auto-reset event), and teardown on the owning thread (CAR §5; FK §1).

### 2.3 Presenter API (Tk → presenters) and events back

The method names are VOC §7.4's presenter effects, one-to-one. K3 owns the payloads and **pushes** them with every field below (K3 §11.1, C5-53). This contract fixes what each call **must** carry and how the presenter behaves. Every call is non-blocking: it posts to the presenter's newest-wins mailbox and returns. Every call also carries `kind`, `request`, `control_id` and `view_id` (K3 §10.1).

**`t0`.** Every timed call carries `t0`: the controller's `time.perf_counter()` (QPC seconds, §0.6) at the press or event that caused it. The presenter anchors **every** scheduled leg to `t0` (`t0` + 190, 200, 360, 380 ms; the pair close at `t0` + 820 is K3's), converting it to QPC ticks for `SetAbsoluteBeginTime` / the hold segments of §4.6.4, never to the time the post arrives (VOC-R25). A `t0` already in the past when the call is handled shortens the leading hold by that much; a leg whose start has passed begins at the next frame (t1, §4.6.5) at the value the curve has at t1.

| Call (VOC §7.4) | Must carry (K3 payload) | Presenter behaviour |
|---|---|---|
| `explorer_open` | `t0`, `source` (`recent` \| `favourites`), `state` (§7.4: `loading` \| `ready` \| `empty` \| `signin` \| `error`, the **displayed** state of that source as K3 §5.2.3 and §5.3.4 map it), `index`, `count` (or null while loading), the item descriptors for the preload window (§13.2), `items_first` (absolute index of the first descriptor), `items_rev`, `control_id`, `control_min`, `reduced_motion`, `foreground_hwnd`, `sonos_available` | §4.9 open sequence; §7 |
| `explorer_highlight` | `index`, `control_id`, optional `bump` (−1 \| 1 from a knob `lim`), new descriptors (`items`, `items_first`, `items_rev`) when `items_rev` changed, and `state` and `count` when they changed (a data update with an unchanged `index` plays no turn) | turn motion (§7.6); end bump; a state change (§7.4) |
| `explorer_source` | `t0`, `source`, `state`, `index` (the new source's remembered index), `count`, descriptors, `items_first`, `items_rev` | the source switch (§7.6), committed at `t0`; the new source enters at `t0` + 190 **at the `index` sent** |
| `explorer_close` | `t0`, `reason` (VOC §7.3), `close_at_ms` (380 for `play`, else 0) | animated or instant close (§15); `play` closes at `t0` + 380 |
| `upnext_open` | `t0`, rows for the window (21 around the focus, VOC §8.2 `queue_window`), `now`, `focus`, `count` (T, or P + 1 with the card), `card` (`{n}` or null), `context` {`kind`: `album` \| `playlist` \| `foreign`, `title`, `sub`}, `shuffle` (`off` \| `companion` \| `sonos`), `likes_known`, `loading`, `control_id`, `control_min`, `reduced_motion`, `foreground_hwnd` | §8 |
| `upnext_highlight` | `index`, `control_id`, optional `bump` | turn motion |
| `upnext_rows` | `t0`, `reason` (`data` \| `likes` \| `shuffle` \| `queue_changed`), a row patch, `now`, `focus`, `count`, `card`, `shuffle`, `likes_known`, `context` (when it changed) | `data`: fill-in, heart states **set without a pop**; `likes`: the heart pop / unlike animation (§8.3; **[r2.2]** the pop only: no unlike exists, so a `likes` patch is always `liked:true`); `shuffle`: rows out at `t0`, re-entry at `t0` + 200 (§8.5); `queue_changed`: re-render in place |
| `upnext_close` | `t0`, `reason`, `close_at_ms` | §15 |
| `windows_open` … `windows_hide` (existing), `windows_snap`, `windows_close_pair` | v6 fields; `windows_highlight` adds `index`, `control_id`, `bump`; `windows_cancel` adds `origin`, `home`, `complete` (`left` \| `right` \| null) and **[errata]** `reason` (`back` \| `hold` \| `lock` \| `sleep` \| `idle`; K3 C5-78), passed on as `cancel(origin, complete=, reason=)` (21.4 E-c); `windows_snap` adds `t0`, `index`, `side`, `target_rect` (physical `rcWork` half), `place_at_ms` (360) | §9 |
| `toast` | `text`, `exit` (bool) | §10 |
| `note_touch` (existing, FK §5) | — | also warms the stage device (§4.2) |

Events back to Tk (drained by the adapters' `pump()`, the `_hotkey_pending` pattern, CAR §1, and handed one by one to K3's single entry point `presenter_event`, VOC-R22): `opened(surface)`, `closed(surface, reason)`, `click_action(surface)`, `refused(surface, reason)` with reason `busy` \| `device`, `system(kind)` with `kind` ∈ `lock`, `sleep` (suspend or display off), `display`, **`motion`** (the Windows *Animation effects* setting changed, §4.1), `snap_result(side, outcome)` with outcome ∈ **`accepted`** (posted when the §9.5 t = 0 pre-checks pass, before the placement), then `ok` \| `move_rejected` \| `cant_fit`; or at once `hung` \| `move_rejected` when a pre-check fails (VOC §8.5), and **`cancel_result(restored, completed)`** answering `windows_cancel` (focus restored; the U12 one-side completion done, §9.7). There is no `display_off` kind.

### 2.4 One overlay at a time

- At most one of `explorer`, `upnext`, `picker` is open; the controller's modes guarantee it (K3).
- Defensively, `ui.py` (WP10) keeps an **overlay registry**, `open_surfaces`, updated from `opened` and `closed` events. The toast presenter and the floating-knob suppression read it (§10.4, §17). An open request that arrives while another overlay is registered is refused with reason `busy` (VOC-K4-02) and logged.

### 2.5 Z-order

- Every overlay window is `HWND_TOPMOST`, re-asserted with `SWP_NOACTIVATE` on each show. It covers the taskbar while open and gives it back on hide (G1 check P10).
- The toast never shows while an overlay is open (§10.4), and the floating knob is suppressed while any overlay is open (§17), so our own windows never compete.
- Inside the picker, bottom to top: dim → glass → host (thumbnails) → chrome (CAR §5). The snap fly is a thumbnail on the host, drawn above the cards because it is registered last (§9.7).

### 2.6 Capture exclusion

- Every snapshot (stage frost, picker frost, toast glass) excludes our own visible windows with `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE = 0x11)` from just before the capture until it is taken, then `WDA_NONE` (CAR §5; RF2 §4a).
- The stage captures **before** its host is shown (§4.9), so only the floating knob (it may still be sliding out) and a fading toast need the exclusion. The existing `set_capture_exclusions(hwnds)` path is reused (UI `_sync_capture_exclusions`); the stage gets the same list.

---

## 3. Input contract for full-monitor windows (AR-4)

| Window | Styles | `WM_MOUSEACTIVATE` | `WM_NCHITTEST` | Left click | Wheel | Keys | Source |
|---|---|---|---|---|---|---|---|
| **Stage host** (explorer, Up next) | not layered, not transparent, `WS_EX_NOACTIVATE` | `MA_NOACTIVATE` (3): the click reaches the window, nothing activates | `HTCLIENT` everywhere | `WM_LBUTTONDOWN` + `WM_LBUTTONUP` both inside the **rest rect** of the centre card (explorer) or the focus plate (Up next) → `click_action`, which K3 handles exactly like Button 4 (a dimmed Play gives the reason and the Head shake). Any other click, and every right, middle and X button, is eaten with no action | eaten (return 0) | never received: the host never has focus, so keys go to the foreground app (§22 Q4) | 00 §3.2 "Overlays"; S5-3, S5-23 |
| **Picker host** (v6) | activatable, `WS_EX_NOREDIRECTIONBITMAP`, **now `rcMonitor`** | `MA_NOACTIVATEANDEAT` (4) while the foreground belongs to another process or to no window, else default | `HTCLIENT` | centre card → Switch; everything else ignored (CAR dev 5) | turns, as v6 (keyboard, wheel) | Esc, Enter and the arrows, as v6 | CAR:158; 00 §3.2 |
| Picker glass, dim, chrome | layered, click-through | `MA_NOACTIVATE` | `HTTRANSPARENT` | — | — | — | CAR §5 |
| Toast, floating knob | 0x080800A8, click-through | `MA_NOACTIVATE` | `HTTRANSPARENT` | — | — | — | FK §4 |

- `WM_SETCURSOR` on the stage host sets `IDC_ARROW` (never the busy cursor).
- The stage host is **never** shown with `SW_SHOW`, `SW_SHOWNORMAL`, `SW_SHOWDEFAULT`, `SetForegroundWindow`, `SetActiveWindow` or `BringWindowToTop` (the FK:127 list). Show: `SetWindowPos(HWND_TOPMOST, rcMonitor, SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW)`.
- Touch and pen arrive as mouse messages and follow the same rules.
- **Why click-eating and not click-through** (AR-4 option b): a click-through full-screen overlay would send clicks to apps the user cannot see under the frost. Eating clicks keeps the hidden desktop untouched. Back, the 600 ms hold and the 60 s idle close are the ways out.
- G1 check P1 (§19) verifies that the foreground window is unchanged after a click, a wheel turn and a key press on the stage.

---

## 4. The stage engine (DirectComposition)

### 4.1 Thread and host window

- **Start.** `NanoD-stage` starts with the app (after `start_overlay()` in ST, inside the same `try`/`finally` as the overlay, FK §9.15). It creates only the host window; the devices come later (§4.2). If the thread fails to start, the stage is disabled, the reason is logged, and every open is answered with `refused(reason="device")`.
- **Class** `NanoD.Stage.Host`: module-level WNDPROC thunk, `hInstance = GetModuleHandleW(None)`, `ERROR_CLASS_ALREADY_EXISTS` (1410) tolerated, created hidden (never `WS_VISIBLE` at creation), styles as §2.1.
- **DWM attributes** set once: `DWMWA_TRANSITIONS_FORCEDISABLED` (3) = TRUE, `DWMWA_EXCLUDED_FROM_PEEK` (12) = TRUE, `DWMWA_WINDOW_CORNER_PREFERENCE` (33) = `DWMWCP_DONOTROUND` (1) (CAR §5).
- **System notifications.** The host is the app's single observer of these, for all three overlays:
  - `WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)`. `WM_WTSSESSION_CHANGE` (0x02B1) with `WTS_SESSION_LOCK` (7), `WTS_CONSOLE_DISCONNECT` (2) or `WTS_REMOTE_DISCONNECT` (4) → `system(lock)`.
  - `WM_POWERBROADCAST` with `PBT_APMSUSPEND` (4) → `system(sleep)`. `RegisterPowerSettingNotification(hwnd, GUID_CONSOLE_DISPLAY_STATE, DEVICE_NOTIFY_WINDOW_HANDLE)`: `PBT_POWERSETTINGCHANGE` (0x8013) with data 0 (display off) → `system(sleep)`.
  - `WM_DISPLAYCHANGE`, `WM_DPICHANGED`, `WM_SETTINGCHANGE` (`SPI_SETWORKAREA`), `WM_DWMCOMPOSITIONCHANGED` → `system(display)`. It also re-reads P and checks the device (§4.3).
  - `WM_SETTINGCHANGE` with `SPI_SETCLIENTAREAANIMATION` (0x1043) → **`system(motion)`**: K3 re-reads the Windows *Animation effects* setting at once for reduced motion (VOC-R09; K3 §14.3; §16). K3 keeps a 5 s backstop on the Tk tick for when the stage thread is down.
  - `WM_ENDSESSION` → instant close and teardown.
  - All of these are unregistered at close.
- **Handlers** are wrapped in `try/except BaseException` and fall back to `DefWindowProcW` (FK §4).
- **Show** only after the first commit of a scene (§4.9), with the §3 flags. **Hide** with `ShowWindow(SW_HIDE)` on the stage thread, after the root opacity reaches 0 (animated close) or at once (instant close). After hiding, the scene's visuals are released and the root is emptied in one commit.

### 4.2 Devices and their lifetime

| Step | Call | Notes |
|---|---|---|
| Adapter | `CreateDXGIFactory1` → `EnumAdapters1` → for each adapter `EnumOutputs`, match `GetDesc().Monitor` to the chosen monitor's HMONITOR | Here the RTX 4090 owns the only output; the iGPU has none (RF2 §2.1). Never create on an adapter without the monitor (cross-adapter copies). Fallback: the default adapter, then `D3D_DRIVER_TYPE_WARP`. If both fail: `refused(reason="device")` |
| D3D11 | `D3D11CreateDevice(adapter, D3D_DRIVER_TYPE_UNKNOWN, NULL, D3D11_CREATE_DEVICE_BGRA_SUPPORT (0x20), [11_1, 11_0, 10_1, 10_0], …)` | 134 ms once; +53.5 MB private (RF2 §2.3). Never the debug layer in a release build |
| DComp | `QueryInterface(IDXGIDevice)` → `DCompositionCreateDevice3(dxgiDevice, IID_IDCompositionDesktopDevice, &dev)` | 0.75 ms |
| Target | `dev->CreateTargetForHwnd(hwnd, TRUE, &target)` | the host's topmost layer |
| Warm-up | at the **first knob touch** (`note_touch`) of the session, posted to `NanoD-stage` | a touch always comes before an overlay; a cold open adds ≈ 134 ms (AR-19) |
| Release | after **600 s** with no open scene: release every stage COM object, surfaces first | frees the 53.5 MB. The encoded and prepared-sprite caches (§13.3) stay |

### 4.3 Device loss and display changes

- **Detection:** a failed HRESULT from `Commit`, `BeginDraw`, `EndDraw`, `CreateSurface` or `UpdateSubresource` equal to `DXGI_ERROR_DEVICE_REMOVED` (0x887A0005) or `DXGI_ERROR_DEVICE_RESET` (0x887A0007), or `IDCompositionDevice::CheckDeviceState` reporting invalid. Checked at every open, after any failed call, and on `system(display)`.
- **Recovery:**
  1. If a scene is open, close it at once with reason **`device`** (VOC-K4-01). There is no mid-scene rebuild: closing is simpler and deterministic.
  2. Release every COM object on the stage thread, in reverse creation order. Log `GetDeviceRemovedReason` once.
  3. Recreate the devices, at most twice, 1 s apart. After a second failure, stay cold; the next open tries again.
  4. Nothing is re-uploaded eagerly. Surfaces are rebuilt from the prepared-sprite cache at the next open.
- **A display change while a scene is open** (`system(display)`, or the monitor disappearing): instant close with reason **`display`** (VOC-K4-01). The layout is recomputed at the next open.

### 4.4 Visual tree rules

| Rule | Setting | Why |
|---|---|---|
| Sampling | `SetBitmapInterpolationMode(DCOMPOSITION_BITMAP_INTERPOLATION_MODE_LINEAR = 1)` on the scene root; every other visual inherits. **`NEAREST_NEIGHBOR` (0) is forbidden**, and a unit test asserts that no call passes it | when every visual inherits, the tree defaults to nearest neighbour (MS-6; AR-8). The ×8 frost would show 8 px blocks and scaled covers would shimmer |
| Edges | `SetBorderMode(DCOMPOSITION_BORDER_MODE_SOFT = 0)` on the root | the default is aliased (MS-7). LINEAR + SOFT is Microsoft's own recipe for antialiasing |
| Group opacity | `SetOpacityMode(DCOMPOSITION_OPACITY_MODE_LAYER = 0)` on the scene root, every explorer card container and the Up next left column. `MULTIPLY` (1) only on containers whose children never overlap (Up next rows) | LAYER composes the subtree at opacity 1, then blends the result (MS-5). That is CSS group opacity. Without it, a fading card shows its shadow through its cover, and the root fade would blend the ambient over the frost twice |
| Full-width layers | the frost and ambient visuals extend at least one reduced pixel (8 physical px) past every monitor edge; the host clips them | SOFT edges and LINEAR sampling fade the last pixel row; the overdraw keeps the monitor edge solid |
| Rest pixel snap | rest offsets are whole physical pixels (§0.3); sprites are made at their rest size | text stays crisp at rest |
| Z-order | sibling order changes only at a detent (`RemoveVisual`, then `AddVisual` with a reference visual), with no animation | CSS `z-index` changes instantly at the detent (BS:1183 `z: 20 − a`) |
| Content swap | `SetContent` with a new surface is committed in the same batch as the animation that reveals it | no frame shows new content with old motion |

### 4.5 Surfaces and uploads

- `dev->CreateSurface(w, h, DXGI_FORMAT_B8G8R8A8_UNORM, alphaMode, &surface)`, with `alphaMode` per §0.7.
- **Upload:** `surface->BeginDraw(NULL, IID_ID3D11Texture2D, &tex, &offset)` → `context->UpdateSubresource(tex, 0, &box at offset, bytes, pitch, 0)` → `EndDraw()`. The bytes are premultiplied BGRA: PIL `tobytes("raw", "BGRa")` of an RGBA image. Measured: 0.285 ms of CPU for a 680 px cover and 0.021 ms for a 640 × 180 frost (RF2 §2.4).
- **Upload budget per stage wake: ≤ 4 ms.** The rest waits for the next wake (about the next frame), so an input commit never queues behind uploads. **[proposed erratum E-S1]** An upload wake also stops at 2.5 MB, flushes the context after each upload and commits its uploads at once in their own Commit (content only); upload wakes are paced two frames and 1 ms after the device's previous upload-carrying Commit (which would otherwise block until then); a surface reaches the scene's reveal only once that Commit is a frame (4 ms) old, so the reveal is a bind-only Commit and no input or reveal Commit carries an upload (§21.6).
- **Solid colours** (tint, shades, dots, marker, underline) are a 1 × 1 opaque surface scaled by the visual's transform. They cost nothing and scale exactly under LINEAR.
- **Residency while the device is warm:** the preload window's surfaces plus an LRU of **64 cover-surface pairs** (§13.3). Everything else is released at scene close.

### 4.6 The animation builder

#### 4.6.1 Evaluation model (documented)

- An `IDCompositionAnimation` is a list of segments. `AddCubic(beginOffset, d, c, b, a)` gives `x(t) = a·t³ + b·t² + c·t + d`, where **t is in seconds from that segment's own begin offset**: "for every segment, time (t) … begins at t = 0" (MS-2; the page's two-segment example confirms it).
- `End(endOffset, endValue)` holds the final value.
- A segment with only a constant causes no recomposition (MS-1), so hold segments cost nothing.
- DWM samples the function at every composed frame, independently of our threads (MS-2).
- `SetAbsoluteBeginTime` does not change when a commit takes effect; it only shifts where sampling starts. A begin time earlier than the first frame that includes the commit drops the start of the curve; a later one delays it (MS-3).

#### 4.6.2 Fitting the CSS curves

- For a tuple (curve, duration D, from v0, to v1), the builder emits cubic Hermite segments in time. At each segment boundary it matches the exact CSS value and slope: the bézier solved for time, the same maths as `CubicBezier` (CA:104-129) but analytic.
- **Adaptive subdivision:** start with 8 uniform segments; split any segment whose maximum error exceeds the bound; at most 32 segments.
- **Error bound:** ≤ 0.5 physical px over the tuple's travel at the scene's k for offsets; ≤ 0.5 px of the element's size for scales; ≤ 0.002 for opacities. Measured: 0.24 px for OUT over 640 px with 8 segments (RF2 §2.3).
- SPR (with overshoot) typically needs 12–16 segments. Every App A tuple is checked by the headless curve-fit gate (§6.6 H3).
- Segment tables are cached per (curve, D) as normalised polynomials and scaled by (v1 − v0) when an animation is built.

#### 4.6.3 The analytic twin

- For each animated property, Python keeps **the same fitted segments** DWM runs, plus the absolute begin time. Its value at any QPC time is what DWM samples, to float precision, and that makes retargets continuous. (The exact bézier would differ from the fit by up to 0.5 px.)
- The twin also answers "is this property still moving?", which ends episodes (§6.2) and starts the sharpen passes (§8.6).

#### 4.6.4 Delays, holds and multi-leg motions

- **A delay** is a leading constant segment, `AddCubic(0, v0, 0, 0, 0)`, followed by the curve's segments offset by the delay. Staggers (45·a ms explorer, 40·a ms Up next), the explorer's new source at +190 ms, the Up next shuffle re-entry at +200 ms and the close at +380 ms after Play are all committed at their trigger this way. The twin knows the pre-start value.
- **A multi-leg motion** is one animation. App A's `ms` is read **per leg**, as BS runs it (S5-31). The end bump: leg 1 from 0 to −14·dir over 160 ms OUT, leg 2 at +160 ms back to 0 over 160 ms OUT, 320 ms in all (BS:778, :143, :242). The heart: 0.4 → 1.5 over 380 ms SPR, hold 1.5, then at +420 ms 1.5 → 1 over 380 ms SPR, 800 ms in all (BS:255, :827-828, :1216).

#### 4.6.5 Begin times and retargets (AR-14)

1. On an event, read `IDCompositionDevice::GetFrameStatistics` → `nextEstimatedFrameTime` (QPC). **t1 = nextEstimatedFrameTime**, plus one P if `t1 − now < 1.5 ms` (the build and commit would miss it). **[proposed erratum E-S2]** The open's batch (about 600 calls, its Commit carrying the frost and the build's sprites: 1.4–5 ms to its return) keeps a margin of one P instead of 1.5 ms, counted from the moment its upload-carrying Commit can return (two frames and 1 ms after the device's previous upload Commit); the device pays its first upload Commit at creation (§21.6).
2. For each property to retarget, `v1 = twin(t1)`. Build the new tuple from v1 to the new target, with its full duration and curve, beginning at t1 (CSS semantics, §0.5 item 4). A new target equal to the current target changes nothing.
3. `Reset()` a pooled animation object (or take a new one), `SetAbsoluteBeginTime(t1)`, add the segments and `End`, then bind it through the property's animation overload.
4. **Never change an animation object that is still bound.** Treat a bound animation as captured when it was set: rebuild it and set it again.
5. **All properties of one event go in one `Commit`.** If DWM picks the commit up one frame late, it samples the new function at t1 + P, and the path stays continuous (MS-3).
6. Velocity is **not** matched at a retarget. CSS transitions restart from the current value with the curve's own start slope, and changing that needs design sign-off (AR-14).
7. If G1 check P7 finds that begin times are not QPC ticks, the fallback is to set no absolute begin time and give every animation a leading hold of `t1 − (predicted commit frame)`, computed from `lastFrameTime` and P.

#### 4.6.6 Which properties are animated

| Element | Binding |
|---|---|
| Card or row position | `IDCompositionVisual::SetOffsetX(anim)`, `SetOffsetY(anim)` on the container. Explorer: X = table offset; Y = rest y + enter rise. Up next: X = row left + enter shift; Y = table offset. The end bump animates the offset of the cards or rows container |
| Card or row scale | `SetTransform(IDCompositionTransformGroup[ScaleTransform "table S", ScaleTransform "enter e"])`, both centred per §0.5 item 2. `SetScaleX` and `SetScaleY` are bound to the **same** animation object (uniform scale) |
| Opacity | `IDCompositionVisual3::SetOpacity(anim)` |
| Tab underline | a `ScaleTransform` whose `ScaleX` is animated about the bar centre |
| Crossfades | two sibling visuals: the upper one's opacity 0 → 1 over an opaque lower one, or A → 0 with B → 1 for the ambient |

#### 4.6.7 Commit discipline and the compositor clock

- One commit per event batch. `WaitForCommitCompletion` is never called on the hot path (only by the G1 spike and the benches).
- A `Commit` that takes more than 2 ms is logged, rate-limited (AR-16).
- **`DCompositionBoostCompositorClock(TRUE)`** is called at the start of every animation episode, and `FALSE` when the episode's last animation ends (the twin knows when). It is harmless when Dynamic Refresh Rate is off (MS-4; AR-11).

### 4.7 COM calls and the GIL (AR-16, AR-5, RF2 §2.3)

#### 4.7.1 Call styles

| Style | Used for | Why |
|---|---|---|
| **`ctypes.PYFUNCTYPE`**, one prototype built once per vtable slot (keeps the GIL) | pure, non-blocking setters only: `SetOffsetX/Y` (float and animation overloads), `SetOpacity`, `SetOpacityMode`, `SetBitmapInterpolationMode`, `SetBorderMode`, `SetContent`, `SetClip`, `SetTransform`, `AddVisual`, `RemoveVisual`, `ScaleTransform::SetScaleX/Y`, `SetCenterX/Y`, `IDCompositionAnimation::Reset`, `SetAbsoluteBeginTime`, `AddCubic`, `End`, `AddRef`, `Release` | with one busy Python thread, `WINFUNCTYPE` turned a 0.03 ms push into 229 ms; `PYFUNCTYPE` kept it at 0.03 ms (RF2 §2.3) |
| **GIL-releasing** (`WINFUNCTYPE` / `WinDLL`) | `Commit`, `WaitForCommitCompletion`, `GetFrameStatistics`, `CheckDeviceState`, `CreateSurface`, `CreateVisual`, `CreateAnimation`, `Create*Transform`, `BeginDraw`, `EndDraw`, `UpdateSubresource`, device and target creation; every window, DWM and user32 call (`CreateWindowExW`, `SetWindowPos`, `ShowWindow`, `SetWindowDisplayAffinity`, `DwmSetWindowAttribute`, `DwmGetCompositionTimingInfo`, `DwmFlush`); `DCompositionWaitForCompositorClock`, `DCompositionBoostCompositorClock`, `DCompositionGetFrameId`, `DCompositionGetStatistics`, `DCompositionGetTargetStatistics`; `MsgWaitForMultipleObjectsEx`, `GetMessageW` | any of these can wait on DWM, the GPU, a TDR, the lock screen or a cross-thread message. Waiting while holding the GIL would freeze Tk, the serial reader and the tray (AR-16) |

- Vtable slots are declared from the SDK headers. **Each one is verified by an S_OK unit test on a device without a target**, as RF2 did for its 13 slots (§6.6 H6). MSVC puts the later-declared overload first (RF2 §2.3).
- Objects are created on the stage thread only, and never inside a detent's hot path: visuals, transforms and animation objects come from pools filled at open.

#### 4.7.2 Process settings (at startup, in ST; WP10)

1. `timeBeginPeriod(1)` at start and `timeEndPeriod(1)` at exit (RF0 §3 rule 9).
2. `SetProcessInformation(GetCurrentProcess(), ProcessPowerThrottling (4), &state, sizeof state)` with `PROCESS_POWER_THROTTLING_STATE{Version = 1, ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED (0x1) | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION (0x4), StateMask = 0}`. This is the documented opt-out ("always honor timer resolution", and HighQoS) for a process whose windows are hidden or never focused (MS-9; AR-2).
3. **`sys.setswitchinterval(0.001)`, never below 1 ms.** Below 1 ms, CPython 3.14's GIL wait rounds down to 0 ms and every waiting thread spins, measured at 70–74 % of a core (AR-1). Re-run `gil_spin_cost.py` after every Python upgrade.
4. **Startup self-check**, logged once: three 8 ms `MsgWaitForMultipleObjectsEx` waits must each measure ≤ 9.5 ms (about 8.25 ms expected, not about 16 ms, RF1 §3.6). Otherwise log `timer resolution not honoured` and carry on.

#### 4.7.3 Worker GIL rules: PIL, JSON and XML (AR-5)

While **any** animation episode runs (the stage, the picker, a toast, or the visible floating knob), code on other threads must not hold the GIL inside one C call for more than **1 ms**. The rule covers **every** thread of the process: the art workers, and also K3's service lanes (`audio`, `library`, `lookahead`, K3 §1) and the Tk thread. The floating knob is visible during Home and Tracks spins, while the 1 s Sonos poll runs, so its 240 Hz loop is the one most exposed.

- **Allowed on workers** (measured GIL-releasing, AR-5): JPEG decode (including `draft()`), `reduce`, `resize` with any filter, `GaussianBlur`, `tobytes`, `frombuffer`, and `paste(image, box, mask)` (a masked paste).
- **Forbidden during episodes:** `Image.alpha_composite` on images over 64 K px. At 2560 × 1440 it held the GIL for 15.8 ms and made 66 % of 240 Hz frames late (AR-5). Use a masked paste of straight colour into a premultiplied RGBX canvas instead, which is an exact premultiplied "over" (RF1 C2).
- **Text:** label, row and sleeve text is drawn one glyph run at a time onto small canvases, as `TextEngine` does (CR:926-1053). Every new text path is added to the GIL bench (`gil_pil_hold.py`, §6.6 H5).
- `render_label` uses `alpha_composite` today (CR:1253-1377). **WP7 replaces it with masked pastes** before picker B1 moves label prefetch onto a worker.
- **Parsing (JSON and XML).** `json.loads` and ElementTree's C parser (which soco uses) each parse a whole document in **one C call that holds the GIL**. ~~Nothing has measured them yet (RF0–RF2 measured PIL only).~~ **[errata]** The H5 bench has measured them (the result below). The cases, at the largest size each lane asks for:

  | Parse | Where | Largest request today |
  |---|---|---|
  | Apple JSON, `catalog_songs` | lookahead lane | 300 ids with `extend=inFavorites` (K3 §9.8.4) |
  | Apple JSON, `resolve` tracks page | library / lookahead | `limit=100` for albums and playlists, `include=catalog`, own-params pager (K3 §9.8.7, C5-52) |
  | Apple JSON, playlists page | library / lookahead | `limit=100` with `extend=inFavorites` (K3 §9.8.5), `playlist_meta` first page `limit=100` (K3 §9.8.8) |
  | Apple JSON, Recently Added page | library / lookahead | `limit=25` (K3 §9.8.6) |
  | Sonos DIDL-Lite (soco, ElementTree) | audio lane | `get_queue(max_items=100)` (SO:315) |
  | Sonos ZoneGroupState (soco, ElementTree) | audio lane | every `_context()` (SO:122-127: `zone_group_state.clear_cache()` then `all_zones`), on each 1 s poll and each assert |

  - **H5 bench** `gil_parse_hold.py` (new, §6.6): parses a fixture for each row, sized like the largest response the lane asks for (recorded during a supervised live check, or synthetic; the bench itself fetches nothing), 20 times on a worker while a probe thread measures its own GIL wait. Reported: p95 and max hold per parse.
  - **Rule, applied per row only where the bench shows a hold over 1 ms:**
    - **Apple JSON:** cap the batch so that one response parses in ≤ 1 ms. Starting values, to be tuned by the bench: `catalog_songs` ids ≤ **50** (from 300); playlist and `resolve` pages `limit` ≤ **25** (from 100). **[errata]** Tuned: `catalog_songs` 50; `resolve` and `playlist_meta` pages 50 (WP6-GIL-D1); playlists pages stay 100. A smaller page is more requests on a background lane, not more latency for the focused item (K3 prefetch rules unchanged).
    - **Sonos XML:** queue reads in windows of ≤ **21** rows (VOC §8.2 `queue_window` already asks for 21); a full-queue read (`SO:315`, 100 per page) is **deferred while an episode runs**. A deferred parse waits at most **1 s** (one poll period) and never delays a user-initiated read (Play next, shuffle, a mode entry); those run at once and are accepted as a rare, bounded hitch. ZoneGroupState can't be split: if its parse exceeds 1 ms, the 1 s poll skips `_context()` while an episode runs and uses the cached context, for at most **3 s**; every assert before a write still reads it fresh.
  - **Where recorded:** here (the rule and the bench) and in K3 (the caps and deferrals on its lanes: K3 §1.2, with notes in §9.6.1, §9.8.4 and §9.8.7).
  - **[errata] Result** (WP6-gil, `tools\stage_checks\gil_parse_hold.py`, 2026-09-26; `design-reference\ui-v2-analysis\gil-parse-hold.md`; accepted by the lead 2026-09-26). One C call, p50 / p95 on the user's PC: `catalog_songs` 300 ids 1.85–3.29 / ≤ 3.80 ms → **50 ids** per request (0.26–0.49 / ≤ 0.55); `/tracks` pages (`resolve`, `playlist_meta`) 100 rows 0.92–1.55 / ≤ 1.74 ms → **`limit=50`** (0.43–0.71 / ≤ 0.81), not 25 (WP6-GIL-D1, K3 §19); playlists pages of 100 (0.20–0.22), Recently Added 25 (0.05), `ratings` 100 (0.04), the Sonos Browse envelope at 100 rows (0.26–0.49; lxml parses the DIDL-Lite with the GIL released) and ZoneGroupState at 32 players (0.15–0.17) all hold under 1 ms, so **no deferral, no smaller windows and no cached context** (WP6-GIL-D2). The cap rule is one call p50 ≤ 0.5 ms and p95 ≤ 1.0 ms. The queue-recovery copy a start saves is encoded in parts (largest single C call 0.80 ms at 5,000 rows, where one `json.dumps` held 8–14 ms). W5 re-checks `limit=50` live and the per-100 KB rates on recorded bodies.

### 4.8 Scene model and tests

- Each scene (`explorer`, `upnext`, and later the picker chrome) is a **pure-Python model**: a list of visuals, each with a sprite id, rest transform, opacity and clip, plus the tweens that drive them. It is tested on a fake clock, as `CarouselMachine` is (CAR §10).
- A **PIL reference renderer** draws the same visual list with LINEAR sampling, SOFT edges and LAYER group opacity. It gives golden images without a GPU, including 16:9 and 32:9 renders of every BS state-picker state (§6.6 H4).
- The DirectComposition backend is the only code that touches COM. It sits behind an interface with a fake that every test uses (the `Win32CarouselBackend` pattern, CAR §5).

### 4.9 Open and close sequence (explorer, Up next)

| t | Step | Thread |
|---|---|---|
| 0 | `*_open` arrives. If the device is cold, create it now, in parallel with the capture (≤ 134 ms) | stage |
| 0 | Exclude the floating knob and any toast from capture (§2.6), then `BitBlt` `rcMonitor` from the screen DC. The host is still hidden, so it needs no exclusion. **Timeout 500 ms** (`CAPTURE_TIMEOUT_S`, CA:208) → tint-only frost | stage-capture |
| ≈ 41 ms | Frost at 1/8 (§12): `reduce(8)`, blur, saturate, tint folded in, ≈ 5 ms. First ambient layer from the focused item's 64 px source or `art_bg`, ≈ 3–5 ms | stage-capture |
| ≈ 50 ms | Upload frost and ambient. Build the tree with every card or row in its hidden pose; cards whose sprites aren't ready get `art.loading` (§13.6). Commit the root opacity 0 → 1 (340 ms OUT) and every entry animation, with t1 = the next frame | stage |
| same wake | Show the host (§3). Post `opened` | stage |
| ≤ 100 ms p95 warm | the first composed frame of the open (§6.3) | DWM |

- The root fade starts only once the frost exists, so the frost never pops in mid-fade (S5-15).
- The first ambient layer is set without a crossfade, as in BS: while an overlay isn't open, both layers take the value directly (BS:779-790).
- **Animated close** (`back`, `hold`, and `play` after its 380 ms): commit the root 1 → 0 over 340 ms OUT. One frame after the twin reaches 0: hide, release the scene's visuals and its frost surface, post `closed`. Card and row surfaces stay in the LRU.
- **Instant close** (every reason not caused by a user action, §15): hide in the same stage wake, release, post `closed`. No fade, no toast.

---

## 5. Frame pacing for Python-stepped surfaces

These rules apply to every loop Python steps per frame: the picker (thumbnail rects and chrome), the floating knob (slide and ring) and the toast (pill). The stage has no such loop. Each rule cites what it fixes.

### 5.1 Rules

| # | Rule | Fixes |
|---|---|---|
| P1 | **Motion is a function of time,** never of frame count. Every value is `f(t)` from a curve with an absolute start; a retarget starts from the curve's value at the retarget time | RF0 §3 rule 1 (already true, RF1 §2.5) |
| P2 | **Sample at the predicted display time:** `t_target = qpcVBlank + n·P` (`DwmGetCompositionTimingInfo`), with n the smallest integer such that `t_target ≥ now + work_p95_estimate`, where the estimate is an EWMA over the last 0.5 s. Never sample "now" when the compose starts | 1–3 vblanks of jitter at CA:930, OV:745 (RF1 A5) |
| P3 | **Pace on the compositor clock:** `DCompositionWaitForCompositorClock(count, handles, timeout)` (Windows 11 22000+, from `GetProcAddress`), with the thread's mailbox event among `handles`. `WAIT_OBJECT_0 + count` means the clock ticked; `WAIT_OBJECT_0 + i` means handle i was signalled (MS-4). Fallback 1: `DwmFlush`. Fallback 2: one period on a high-resolution waitable timer (`CreateWaitableTimerExW(…, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x2, …)`). Window messages are drained with `PeekMessageW` at the top of every loop turn | display-independent pacing; mixed refresh rates follow the right display (AR-21) |
| P4 | **Judge pacing by the interval between wake-ups:** a wait that returns at least 0.5 P after the previous return is pacing. v6's "two flushes under 0.5 ms → wait 8 ms" heuristic is **removed** | the 16 ms stalls at CA:512-517, OV:1211-1218 (RF1 A1, §3.6) |
| P5 | **Rate lock with hysteresis.** When a loop's work p95 over the last 0.5 s exceeds **0.8 P**, present every second vblank and sample 2 P ahead. Unlock when the p95 has stayed below **0.6 P** for 0.5 s. FrameStats counts the cadence switches. **[proposed erratum E-P1]** In the carousel's loop (the picker and the toast): one-off frames (an open's setup, the frost's upload, the chrome's warm-up) count nowhere; the GPU chrome's detent frames feed P2's estimate only; the lock engages only once the loop has run 0.25 s since its last idle pause and at least two frames of the window are over 0.8 P (§21.6; CAROUSEL.md §12.5) | a steady 120 instead of judder between 240 and 120 near the budget (AR-10) |
| P6 | **Per-frame budget:** floating knob **≤ 2.5 ms p95** at 100 % scale (the §6.3 "Knob ring" gate; RF0 §4.2's knob row, stricter than RF0 rule 6's general 2.5 ms median / 3.0 ms p95); toast ≤ 1.0 ms p95; picker step 1 ≤ 5.6 ms p95 compose + present, under the 120 lock | RF0 §3 rule 6, §4.2 |
| P7 | **No large buffer is allocated per frame.** Compose straight into the mapped DIB; use dirty rects where a layered window is re-uploaded | RF1 C2, B5 |
| P8 | **Run only while something moves.** When idle, block in `GetMessageW` or `MsgWaitForMultipleObjectsEx(INFINITE)`. No polling timer in an animation thread | RF0 §3 rule 8 |
| P9 | **No timers in frame paths:** no `after(`, `SetTimer(` or `sleep(` in an animation module outside an idle-path allowlist (static scan, §6.6 H2). Never hard-code 16.7, 8.3 or 4.17 ms; read P | RF0 §3 rule 3 |
| P10 | **Tk stays out of every frame path.** Tk posts events and immutable scenes, newest wins | the 25 ms tick (UI:99, :1857) |
| P11 | **Boost the compositor clock** for each episode (§4.6.7) | AR-11 |
| P12 | **One clock, QPC.** `AliveLights` takes `now` in uint32 ms: `int(t_qpc_seconds × 1000) & 0xFFFFFFFF`, sampled at `t_target` | RF0 §3 rule 11; AL §4 |
| P13 | Frame threads (`NanoD-overlay`, `NanoD-carousel`) run at `THREAD_PRIORITY_ABOVE_NORMAL`; workers at `BELOW_NORMAL` | protects them from other processes and from our own workers (RF1 A4) |

### 5.2 Loop shape

```
while running:
    drain PeekMessageW; drain the mailbox and the fast-path queue
    if not animating: block in GetMessageW / MsgWait(INFINITE)       # P8
    t_target = predicted display time                                # P2
    step(t_target); present()          # FrameStats: t_wake, t_target, work_ms, present_ms
    wait on the compositor clock or the mailbox event                # P3, P4, P5
```

### 5.3 The input fast path (AR-9)

- **Required in v7 for the floating knob's LED engine.** The serial reader (DV) posts `detent(delta)`, `limit(dir)`, `press(slot)` and `position(control_id, p)` straight to the `NanoD-overlay` mailbox, each stamped with **its QPC time at the serial read**, and signals the mailbox event.
- The engine queues them with those timestamps; `render` processes them in AL §4's fixed order.
- Frames, clock, progress and `reducedMotion` still come from Tk, because the controller decorates them (K1, K2).
- Without it, the ring's cursor would rise in 30 Hz steps inside a 240 fps ring (a τ 10 ms rise against a 25–31 ms Tk tick).
- **Recommended for the overlays too** (§22 Q3). The same `position` events go to the stage and the picker. The presenter maps `index = p − control_min` for the current `control_id` and retargets at once (`control_min` is 0 in every list mode, K3 §11.1). The controller's own `*_highlight` for the same (id, index) is then a no-op, and a different index from the controller wins. While a scene is swapping (explorer +190 ms, Up next +200 ms) or playing, fast-path positions are recorded but not presented (A05 §5.6). **Positions tagged with a `control_id` older than the current one are discarded, never applied**: after a source switch they are positions in the old source's bounds (K3 §5.3.3, C5-9).

---

## 6. FrameStats and acceptance

### 6.1 How each surface is measured (AR-13)

| Surface | Method | A displayed frame is |
|---|---|---|
| `explorer`, `upnext` | **Compositor frame statistics.** Starting from the episode's first frame id (`DCompositionGetFrameId(COMPOSITION_FRAME_ID_COMPLETED)`), the stage walks every frame id in order: `DCompositionGetStatistics(id, &frameStats, n, targetIds, &actual)`, then `DCompositionGetTargetStatistics(id, &targetId, &targetStats)` for the monitor's target. It harvests every **250 ms** during an episode (a low-rate wake, not per frame) and once at the end | a frame with `targetStats.presentTime ≠ 0` on our monitor's target (MS-4 sample). DWM evaluates our running animations at every composed frame, so displayed frames during an episode are our motion frames |
| `picker`, `knob` slide, `toast` | **Present cadence** in the app: the QPC time after each `UpdateLayeredWindow` returns, mapped to a vblank index `round((t − qpcVBlank) / P)`. On-screen proof: PresentMon's dwm.exe display cadence in the supervised runs (downloaded only with the user's OK), or a ≥ 960 fps camera burst | a present that lands on a different vblank from the previous one |
| `knob` ring | **Changed-frame lateness:** only frames whose quantised output changed count (§11.4); a changed frame is late when it is presented after its `t_target` vblank | at rest the breath changes by less than one output level on most frames; counting those would reward redundant work (AR-22) |

The "target" in compositor statistics is the display, not our window (MS-4 glossary). The G1 spike checks that the statistics history is deep enough for a 250 ms harvest, that is ≥ 64 frames (check P9).

### 6.2 FrameStats fields (one record set per surface id)

**Per frame** (Python-stepped loops): `t_wake`, `t_target`, `work_ms`, `present_ms`, `refresh_count` (`cRefresh` at present), `changed` (knob ring), `cadence` (1 or 2).

**Per episode** (from a motion's start to its settle; for the stage, the twin's end):

| Field | Meaning |
|---|---|
| `surface`, `kind` | VOC surface id; `open`, `turn`, `switch`, `shuffle`, `play`, `close`, `snap`, `slide`, `ring` or `toast` |
| `method` | `dcomp_target_stats` \| `present_cadence` \| `ring_changed` |
| `frames`, `vblanks`, `fps` | displayed frames; vblanks elapsed; frames ÷ duration |
| `interval_ms` p50 / p95 / p99 / max | between displayed frames |
| `missed`, `double_missed` | intervals over 1.5 P and over 2.5 P |
| `work_ms` p95 / max | per frame (Python loops) or per event (stage: wake → `Commit` returns) |
| `cpu_pct_one_core` | `GetThreadTimes` of the frame thread (for the stage, all stage threads) over the episode |
| `cadence_switches`, `late_changed` | P5 switches; the knob ring's late changed frames |
| `rate_hz`, `boosted`, `rm` | `rateRefresh` at the start; boost on; reduced motion |
| `holds`, `fps_in_motion`, `interval_P_in_motion`, `missed_in_motion`, `double_missed_in_motion` | **[proposed erratum E-S3]** stage episodes: the vblanks without a presented frame where nothing changed (a designed hold, §4.6.4: the heart's 40 ms, a switch's 170 → 190 ms), from the episode's batches (`frames.ChangeModel`), and the figures above without them. The raw fields keep their meaning (§21.6) |
| `locked_frames`, `paced_frames`, `rereg_frames`, `rereg_ms` | **[proposed erratum E-P1]** picker episodes: presents paced under the 120 lock, and the thumbnails' re-registrations, for the attribution of missed frames (CAROUSEL.md §12.5 E-P2) |

- **Export:** `presenter.metrics()` (picker, CA:611-620), `overlay.metrics()` (knob, OV:1645) and a new `stage.metrics()`. Each keeps `last`, `worst` since start and `totals` per episode kind, written to `status.json` under `frames.<surface>`, next to today's `compose_ms_max` and `glass_upload_ms`.
- **Logging:** one line per episode that misses §6.3, at most one per 30 s per surface.
- **HUD:** `NANOD_FPS_HUD=1` shows a small text sprite on the stage or in a corner of the picker chrome, updated 4 times a second, never per frame. Off by default, and never on the floating knob.

### 6.3 Thresholds (normal and stress runs)

P = 4.1667 ms here. On time is ≤ 1.1 P (4.6 ms); one missed vblank is 2 P (8.33 ms, "≤ 8.4 ms"); two is 3 P (12.5 ms). CPU is a share of **one core**, which is 6.25 % of the 16-thread 9800X3D in Task Manager (RF0 §4).

**[proposed erratum E-S3]** For the stage (Explorer, Up next) the frames/s and interval columns are read from an episode's in-motion fields (§6.2): a vblank where nothing on the stage changed (a designed hold) is neither a displayed frame owed nor a missed one; a frame lost while something moves still counts (`frames.judge_stage`, `basis` "in_motion"). This is what the column heading, "Displayed frames/s in motion", already says (§21.6).

| Surface (tour, §6.4) | Displayed frames/s in motion | Frame interval | Python work | CPU | Stress run |
|---|---|---|---|---|---|
| **Explorer (E), Up next (U)** | **≥ 0.979 × rate** (≥ 235 here) | p95 ≤ 1.1 P, p99 ≤ 2.02 P, max ≤ 2.02 P | 0 per frame. Per detent, wake → `Commit` ≤ 1.5 ms p95 | companion ≤ 30 % of one core above idle at 20 detents/s with a warm prepared-sprite cache, ≤ 15 % at 10/s. A cold cache is recorded, not gated (about +35 %, AR-6) | **same thresholds** (DWM runs the motion) |
| **Picker (W), step 1** | ≥ 118 (the 2 P lock) | p95 ≤ 2.02 P, max ≤ 3 P, no gap ≥ 16 ms | compose + present ≤ 5.6 ms p95 on the 16:9 table; the 32:9 table per §22 Q2 | carousel thread ≤ 70 % | ≥ 110, max ≤ 3 P |
| **Picker (W), step 3** (chrome on the GPU; ~~later~~ **[errata]** v7's picker: R-h, §9.10, wired in the app 2026-09-26; step 1 is its fallback) | ≥ 235 | p95 ≤ 1.1 P, p99 ≤ 2.02 P | ≤ 1.5 ms p95 on normal frames, ≤ 3.0 ms on detent frames | carousel thread ≤ 35 % | ≥ 228, max ≤ 3 P |
| **Knob slide (K)** | ≥ 235 (expected; go/no-go at S1, AR-3) | p95 ≤ 1.1 P, max ≤ 2.02 P, no 16 ms stall | ≤ 0.2 ms | — | ≥ 228 |
| **Knob ring (K)**, visible and animating | changed frames on their target vblank ≥ 98 %; late by ≥ 2 P ≤ 0.5 % | — | ≤ 2.5 ms p95 at 100 % | overlay thread ≤ 50 % while visible; **while hidden, no loop or timer**: only the per-message engine render with its ≤ 60 catch-up steps (§11.2, K2 M27; 0.06–0.17 ms per render, ≤ 10 ms per message, outside any frame path) | ≥ 97 % on time |
| **Toasts (T)** | ≥ 235 | p95 ≤ 1.1 P | ≤ 1.0 ms p95 | — | ≥ 228 |

- **If the knob slide or the toast misses 235 at S1** (the only on-screen data so far missed 7.5–12 % of frames, AR-3), the fallback is the P5 lock at 120, and the floating knob moves onto the stage engine next (RF0 step 4).
- **Latency, all surfaces, with the fast path** (§5.3): serial read → the first displayed frame showing the new target ≤ **3 P + 2 ms** p95. Without the overlay fast path (§22 Q3), the explorer, Up next and picker are measured from the controller's effect instead: ≤ 2 P p95.
- **Open latency:** the knob button's serial read → the first composed frame of the open ≤ **100 ms** p95 with a warm device and cached sprites; ≤ **250 ms** with a cold device (AR-6, AR-19).
- **Independence checks** (RF0 §4.2): the ring's frame rate is unchanged in a test build with `POLL_MS = 100`; the stage's episode fps is unchanged in the stress run.
- **Guards** (recorded; investigated if exceeded): dwm.exe CPU during tour E ≤ +15 % of one core over its idle; dwm.exe GPU 3D ≤ 20 %; memory per §14.

### 6.4 Tours (supervised, with the user's go-ahead; driven by a scripted detent replay, no hands needed)

| Tour | Script |
|---|---|
| **E** | Recently Added with ≥ 25 items: 20 detents at 10/s, a 1 s pause, 20 at 20/s, 10 reversals at 20/s, a source switch and back, 10 detents, then Play (grow and close). Three times on the 32:9 table (the user's monitor), once with a forced 16:9 layout |
| **U** | a playlist queue of ≥ 25 rows: the same detent pattern, Shuffle on and off, Like, Play |
| **W** | ≥ 8 windows: 20 detents at 10/s and 20 at 20/s; snap left, snap right (pair close); reopen, one snap, then Back (one-side completion). Both Frosted and No background |
| **K** | 10 summon and slide-out cycles; a 5 s spin at 20 detents/s; a volume sweep into amber and red; fill and drain; 5 s of visible breathing |
| **T** | 5 toasts from different sources, including one replaced while showing |
| **Stress** | each tour again with the test hook `NANOD_STRESS_GIL=1`: a pure-Python burst of 10 ms every 25 ms on another thread, the Tk tick's worst case (RF1 §3.6) |

### 6.5 Supervised gates this contract feeds (00 §4.4)

| Gate | Checks |
|---|---|
| **G1** | the spike (§19), before WP8 starts |
| **S1** | tours E, U, W, K and T at §6.3, normal and stress; the timer-resolution self-check inside the running frozen app, with the overlays hidden and shown (AR-2) |
| **S2** | memory and dwm.exe commit per §14 |
| **S3** | snap on real windows (maximized, minimized, UWP, elevated, mixed DPI): the foreground kept, flush edges, one-side completion; the pair close leaves both halves above the origin (§9.7, the posted raise); **a busy target** (a test app of ours that stops pumping for 2 s right after the pre-check): the picker keeps turning, the snap resolves as `move_rejected` by t0 + 800 ms, a latched Back closes the picker, and nothing is activated. **It moves the user's windows** |
| **S4** | toast placement and suppression |

### 6.6 Headless gates (every build; nothing on screen)

| # | Gate |
|---|---|
| H1 | **Frame-rate independence.** Every state machine (the stage scenes, carousel, slide, toast, and `AliveLights` on the overlay path) sampled on fake clocks at 60, 120, 144, 240 and 360 Hz gives the same value at the same t. A skip of 1–3 vblanks resumes on the curve with no catch-up burst |
| H2 | **No timers in frame paths** (static scan, P9) |
| H3 | **Curve fit:** every App A tuple and every motion in §7–§11, within §4.6.2's bound |
| H4 | **Golden images:** the stage's PIL reference renderer against every BS state-picker state at 16:9 and 32:9 (explorer, Up next); the explorer's state blocks BS doesn't draw (Recently Added empty, sign-in on either tab, error; §7.4) at both ratios, as reviewed goldens; the picker chrome against the `compose_chrome` goldens (CAR:274) |
| H5 | **Budget benches** (reported, not gated, since the PC is shared): knob frame ≤ 2.5 ms p95; picker compose on both tables; stage ≤ 1.5 ms per detent; `gil_pil_hold.py` for every worker operation; **`gil_parse_hold.py` for every JSON and XML parse of §4.7.3's table** (its result sets K3's batch caps); `gil_spin_cost.py` after a Python upgrade |
| H6 | **Vtable slots:** every DirectComposition method this contract binds returns S_OK on a device without a target. No call ever sets `NEAREST_NEIGHBOR` interpolation or `HARD` borders |
| H7 | **Retarget continuity:** the twin's value just before and just after a retarget at t1 agree to 1e-6, for every property kind |
| H8 | **Layout maths:** the tables, the dots cap and window (§7.4), the fly target (§9.5), frame compensation, half rects and the workspace-to-screen conversion (§9.6), the art ladder (§13.1), and the Generated-sleeve hash against BS `genOf` (§13.6) |
| H9 | **Hidden floating knob** (K2 §11 item 5, M27; §11.2, §11.4), with a fake backend that counts renders, composes and presents: while hidden, no loop and no timer run, and the engine renders exactly once per posted frame or input plus its catch-up steps (≤ 60 of 50 ms), with **zero** composes and presents; a `like` feedback posted while hidden, then a slide-in 2 s later, shows no bloom (it ended at 900 ms); a `started` wash posted 300 ms before the slide-in shows at u ≈ 0.27; in both, and after a 10 s hidden spell across the fall asleep, the first visible `e` equals a twin rendered continuously at 60 Hz within 0.02. **[erratum R-i]** For a **summon by a message** (a detent or press whose input makes the knob visible, a Tk frame posted in the same tick as its touch, a feedback frame posted during the arm wait) the first visible frame equals the **M27 reference**, and the comparison with the twin (within 0.02) applies from **+300 ms** of visible frames (21.4 E-i) |

---

## 7. Scene: Music explorer (`explorer`)

Sources: S01 §5 (S01:234-320), App A (S01:472-486), App B (S01:533), BS:124-205 (markup), BS:1023-1046 (open, close, switch, Play), BS:1168-1193 (tables and cards). It never takes focus (S01:234).

### 7.1 Layers, bottom to top

| # | Visual | Surface (k = 2) | Notes |
|---|---|---|---|
| 1 | Frost, tint folded in | 640 × 180 opaque, scaled ×8 (+ overdraw) | `blur.explorer` (§12) |
| 2 | Ambient A | 720 × 260 opaque, scaled ×8, offset −320, −320 px | opacity 0.50 while showing; §7.5 |
| 3 | Ambient B | as A | crossfades with A |
| 4 | Stage container (1280 × 720 units, centred) | — | clips nothing; cards may leave the stage (§18) |
| 4.1 | Tabs | two tab sprites + two underline bars | §7.4 |
| 4.2 | Cards container | — | carries the end bump (`OffsetX`) |
| 4.2.x | Card containers, z by `a` (nearest on top) | §7.3 | LAYER opacity |
| 4.3 | Label | one sprite (title, sub, meta), 900 units wide | §7.4 |
| 4.4 | State block | one sprite | only while the active source's displayed state is `empty`, `signin` or `error` (§7.4) |
| 4.5 | Dot row + marker | one row sprite + one 6 × 6 solid visual | §7.4 |
| 4.6 | Hints | one sprite | static |

The host clips at the monitor edge, so cards enter and leave by translating past it (S01:266).

### 7.2 Geometry (units; physical px at k = 2 on the G93SC)

- **Card:** 340 × 340 units (680 px), centre at stage (640, 318) = monitor px (2560, 636). `a = min(|d|, a_max)`, `d = i − focus`, `sg = sign(d)` (BS:1173-1175).
- **16:9 table** (S01:243-249; BS:1170): `a_max = 4`

| a | Offset X | Scale | Opacity | Shade `#0B0B0C` | Size px | Centre offset px |
|---|---|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 0 | 680 | 0 |
| 1 | ±300 | 0.60 | 0.92 | 0.24 | 408 | ±600 |
| 2 | ±470 | 0.42 | 0.55 | 0.48 | 285.6 | ±940 |
| 3 | ±590 | 0.30 | 0 | 0.60 | (hidden) | ±1180 |
| 4 | ±660 | 0.22 | 0 | 0.60 | (hidden) | ±1320 |

- **32:9 table** (S01:251-262; BS:1170): `a_max = 8`. The monitor edge is at ±1280 units, so a = 7 is cut by the edge (36 px of it show here) and a = 8 is fully off-screen. No visible card is below 0.40.

| a | Offset X | Scale | Opacity | Shade | Size px | Centre offset px |
|---|---|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 0 | 680 | 0 |
| 1 | ±300 | 0.60 | 0.92 | 0.24 | 408 | ±600 |
| 2 | ±500 | 0.46 | 0.84 | 0.34 | 312.8 | ±1000 |
| 3 | ±680 | 0.42 | 0.76 | 0.42 | 285.6 | ±1360 |
| 4 | ±850 | 0.40 | 0.68 | 0.48 | 272 | ±1700 |
| 5 | ±1010 | 0.40 | 0.60 | 0.52 | 272 | ±2020 |
| 6 | ±1170 | 0.40 | 0.54 | 0.55 | 272 | ±2340 |
| 7 | ±1330 | 0.40 | 0.50 | 0.58 | 272 | ±2660 |
| 8 | ±1490 | 0.40 | 0 | 0.60 | (off-screen) | ±2980 |

- **Rendered cards:** every item with `|d| ≤ a_max` has a container; cards beyond sit at the `a_max` slot with opacity 0 and have no visual. A card coming into range is created at the `a_max` slot at opacity 0, then animates in (CSS parity).
- **Z-order:** `20 − a` (BS:1183), reordered instantly at each detent (§4.4).
- **Hit rect** for the click action: the centre card's rest rect (§3).

### 7.3 A card

| Child (bottom to top) | Content | Animated |
|---|---|---|
| Side shadow | shared 1/4-resolution sprite of `0 16px 36px rgba(0,0,0,.40)` around a 340-unit square (σ 18 units), scaled ×4 | opacity 1 when `d ≠ 0`, crossfade 320 ms OUT (S01:269, :479) |
| Focus shadow | shared 1/4-resolution sprite of `0 40px 80px rgba(0,0,0,.55)` (σ 40 units, reach 120 units), scaled ×4 | opacity 1 when `d = 0` |
| Cover L1 | 340 px surface (170 units × k), scaled ×2 inside the card | always opacity 1 |
| Cover L0 | 680 px surface (340 units × k) | opacity 1 when `\|d\| ≤ 1`, else 0; crossfaded on the turn curve, 420 ms OUT (S5-28) |
| Loading layer | `art.loading` sprite (§13.6), present only until the cover is ready | the cover above it fades 0 → 1 over 240 ms OUT (S01:297) |
| Inset line | shared 1 px (`max(1, round(k))` physical px) frame, `rgba(255,255,255,.12)` | — |
| Shade | 1 × 1 `#0B0B0C` scaled to the card | opacity = the table's shade, 320 ms OUT (S01:478) |

- The container's opacity is the table opacity, in LAYER mode.
- Everything visible about the art is baked into L0 and L1: full cover, Extended sleeve, Generated sleeve, mosaic or single (§13.6). The GPU sees only an opaque square.
- **Level choice (AR-8):** L0 serves the centre (680 px, 1:1) and a = 1 (408 px, a 1.67× reduction). L1 serves a ≥ 2 (285.6–312.8 px drawn from 340 px, a 1.09–1.25× reduction). No visible card is minified by more than 1.67×. G1 check P5 judges shimmer at a = 1; if it is visible, a third level at 408 px is added for a = 1.
- A missing L0 (not built yet) leaves L1 showing, upscaled 1.2× at a = 1, until L0 is ready and fades in over 240 ms OUT.

### 7.4 Tabs, label, dots, hints, state blocks and thin lists

- **Tabs** (S01:237-240; BS:130-141): a row at top 44, centred, the two tabs 36 apart. Each tab is a column (gap 10): line 1 is a key box 18 × 18 (1 px `currentColor` border, digit 11 px 700), gap 8, an 18 px icon (stroke 2, round caps and joins), gap 8, the label 17 px 600; line 2 is a 2 px white underline as wide as the column.
  - Tab 1: key `2`, `clock`, `overlay.explorer.tab_recent` (`Recently Added`). Tab 2: key `3`, `playlists` glyph (BS `I.queue`), `overlay.explorer.tab_favourites` (`Favourite playlists`).
  - Active: tab opacity 1 and underline `scaleX(1)`. Inactive: opacity 0.55 and `scaleX(0)`. On a switch the label opacity takes 240 ms OUT and the underline 320 ms OUT (App A S01:481-482), both **at the button press** (S5-5).
  - Each tab is one white sprite whose opacity animates; the underline is a solid bar scaled about its centre (square ends, R:116).
- **Label** (S01:270; BS:178-182): a column at left 190, width 900, top 514 (y 1028 px here), centred, gap 6.
  - Title 30/36 600, −0.01 em, one line, ellipsis at 900. Sub 17/22 at 0.90. Meta 14/18 at 0.72.
  - The text comes from K3's item descriptor: album sub `{artist}`, meta `{year} · {n tracks}`; playlist sub `overlay.explorer.sub_favourite` or `.sub_favourite_auto`, meta `{n} songs · {h} h {mm} min` (BS:1189).
  - One sprite per item, rendered on a worker and prefetched ±3 around the focus (RF0 §2.1). At a detent, the swap happens as soon as the new sprite exists; until then the previous label stays (S5-24). Swap = opacity 0, then 0 → 1 over 160 ms OUT (S01:484).
  - Hidden (opacity 0) while the list is loading, in a block state (`empty`, `signin`, `error`), and during a source switch.
- **Dots and marker** (S01:271-274; BS:190-195): fixed 6 × 6 white dots at 0.40, pitch 14, centred in the stage at top 622, plus one solid 6 × 6 marker that translates to the focused dot over 420 ms OUT (App A S01:483). No width animation.
  - The dot row is one sprite. It is rebuilt when the count changes and is hidden while loading or in a block state.
  - **Long lists** (S5-9): the stage holds at most `DOTS_CAP = floor((1280 − 128 + 8) / 14) = 82` dots. With more items, the row shows an 82-dot window starting at `first = clamp(i − 41, 0, n − 82)`. Where more items exist beyond an end, the 3 end dots on that side are drawn at 0.30 / 0.20 / 0.10 instead of 0.40. The row sprite changes only when `first` or those end fades change (an instant swap); the marker translates to `(i − first) × 14`.
- **Hints** (BS:196-203): top 664, centred, 28 apart, 13 px at 0.80. Each hint is a key box 16 × 16 (1 px border at 0.60, digit 10 px 700), gap 6, then the label: `overlay.explorer.hints` = `[1] Back` `[2] Recently Added` `[3] Playlists` `[4] Play`. One static sprite.
- **State block** (the empty-state geometry of S01:311-313 and BS:183-189, reused for every state with nothing to browse; S5-33): no cards, dots, marker or label. One block sprite at left 340, width 600, top 250, centred, gap 12: a 56 px glyph (stroke 1.6, round caps and joins, rgba .60), the title 28/34 600 white, the help 16/22 at 0.80, wrapped to the 600-unit width (BS `text-wrap: pretty`: no one-word last line). The glyph is always the **active tab's own glyph** (`clock` for Recently Added, `playlists` = BS `I.queue` for Favourite playlists, BS:489, :491), since r2.1 draws no warning glyph.

  | Displayed state (K3) | Tab | Title | Help | Source |
  |---|---|---|---|---|
  | `empty` | Favourite playlists | `overlay.explorer.empty_title` | `overlay.explorer.empty_help` | S01:311-313; BS:183-189 |
  | `empty` | Recently Added | `overlay.explorer.recent_empty_title` (proposed, VOC-K4-04) | `overlay.explorer.recent_empty_help` (proposed) | K3 §5.2.3 row "empty" (Open is not dimmed when the list is empty, K3 §3.1) |
  | `signin` (401/403 with nothing cached to show) | either | `overlay.explorer.signin_title` | `overlay.explorer.signin_help` | K3 §5.2.3, §5.3.4, §15.3 (proposed there for the favourites tab; used for both tabs here, VOC-K4-04) |
  | `error` | either | `overlay.explorer.error_title` (proposed, VOC-K4-04) | `overlay.explorer.error_help` (proposed) | K3 §5.2.3 row "error" |

  - How each state is reached is K3's: the explorer may open on a Recently Added list that is still loading and then fails, or that is empty; a favourites error without a cache is shown as `loading` while CF's retries run (K3 C5-42), so `error` on that tab appears only if K3 sends it.
  - While a block shows: the ambient shows nothing (frost and tint only; BS:1191 has no focused item); the tabs and hints stay; a click anywhere does nothing, because there is no centre card (§3); Play's dimming and its reason are K3's (`empty`, `signin_expired`, `list_error`, K3 §3.1).
  - The block sprite is rebuilt only when the state or the tab changes. Its motion is in §7.6.
- **Thin list (1–3 items)** (S01:308-310): no padding and no fake items. The first item is centred with its neighbours on the right only; the dots show the true count. This falls out of the table.
- **Loading list** (`art.list_loading`, S01:300): cards are `#232325` with the inset line and the shade; there is no label, dots or marker. Placeholders fill the table slots of `[focus − a_max, focus + a_max]`, clamped to `[0, count − 1]` when `count` is known and to `≥ 0` otherwise (S5-11).

### 7.5 Ambient layer

- Two layers, A and B (S01:236, :485; App B S01:533). Content: the focused item's cover (a playlist: the first mosaic cover; a Generated sleeve: its gradient; loading: `art_bg`) built at 1/8 (§12). Visual opacity **0.50**.
- **Trigger:** each change of the focused item, or of the source, restarts a **200 ms** debounce. When it fires, the newest target is built on a worker (≈ 3–5 ms, newest wins; stale builds are dropped). On arrival, the hidden layer gets the new content and the two layers crossfade over **600 ms OUT**: the incoming layer 0 → 0.50, the outgoing 0.50 → 0.
- During a fast spin no ambient is built at all, because the debounce never fires (BS:779-790 `xfUpdate`).
- The crossfade leaves the mid-point slightly weaker than either end (two 0.25 layers), exactly as the prototype's two CSS layers do.

### 7.6 Motion (App A S01:472-486 unless marked)

| Event | Element | Property: from → to | ms | Delay | Curve |
|---|---|---|---|---|---|
| Open | Scene root | opacity 0 → 1 | 340 | 0 | OUT |
| Open | Card (enter) | rise +30·S → 0 units; enter scale 0.9 → 1 (× S) | 440 | 45 × a | OUT |
| Open | Card (enter) | opacity 0 → table | 320 | 45 × a | OUT |
| Open | Tabs, label, dots, hints, or the state block (§7.4) | shown with the root fade | — | — | — |
| Close (`back`, `hold`) | Scene root | opacity 1 → 0 | 340 | 0 | OUT |
| Turn (each detent) | Card | X, S → the new slot's values | 420 | 0 | OUT |
| Turn | Card | opacity → table | 300 | 0 | OUT |
| Turn | Shade | opacity → table | 320 | 0 | OUT |
| Turn | Shadows | side ↔ focus crossfade, when a card enters or leaves the centre | 320 | 0 | OUT |
| Turn | Cover L0 | opacity 0 ↔ 1, when a card crosses \|d\| = 1 ↔ 2 | 420 | 0 | OUT (S5-28) |
| Turn | Marker | translateX `i·14 → (i ± 1)·14` | 420 | 0 | OUT |
| Turn | Label | swap, then opacity 0 → 1 | 160 | 0 | OUT |
| Turn | Ambient | A ↔ B crossfade | 600 | 200 debounce | OUT |
| End stop (knob `lim`) | Cards container | translateX 0 → −14·dir, then → 0 | 160 + 160 | 0 / 160 | OUT (App A S01:480 per leg, S5-31) |
| Source switch (Button 2/3) | Card (exit) | rise 0 → +30·S; scale → 0.9·S; opacity → 0 | 170 | 0 | IN |
| Source switch | Label | opacity → 0 | 160 | 0 | OUT (S5-5) |
| Source switch | Tab label, underline | opacity 0.55 ↔ 1; scaleX 0 ↔ 1 | 240; 320 | 0 | OUT |
| Source switch | New source's cards | enter as on open (stagger 45 × a), at the new source's remembered index | 440 / 320 | 190 + 45 × a | OUT |
| Source switch | Dots and marker | new row and marker position, no slide | instant | 190 | — (S5-10) |
| Source switch | New label | opacity 0 → 1 | 160 | 190 | OUT |
| Play (Button 4, or the centre-card click) | Centre card | scale 1 → 1.12 | 380 | 0 | OUT |
| Play | Other cards | opacity → 0 | 300 | 0 | OUT |
| Play | Scene root | opacity 1 → 0 | 340 | 380 | OUT |
| Art ready | Cover over loading tile | opacity 0 → 1 | 240 | 0 | OUT |
| Source switch | Old state block, if any | opacity → 0 | 160 | 0 | OUT (as the label; S5-33) |
| Source switch | New state block, if the new source has one | opacity 0 → 1 | 160 | 190 | OUT (as the new label; S5-33) |
| State change into a block (K3 `state` patch while open) | Cards (loading placeholders or items) | exit as on a source switch: rise 0 → +30·S; scale → 0.9·S; opacity → 0 | 170 | 0 | IN (S5-33) |
| State change into a block | State block | opacity 0 → 1 | 160 | 190 | OUT (S5-33) |
| State change out of a block (a retry that loads, a sign-in renewed) | State block | opacity → 0 | 160 | 0 | OUT (S5-33) |
| State change out of a block | Cards (loading list or items), label, dots | enter as on open (stagger 45 × a); label and dots as on a source switch | 440 / 320; 160; instant | 190 + 45 × a; 190; 190 | OUT (S5-33) |

- Everything that starts at 190 or 380 ms is committed at `t0` (the press, K3's `t0`; for a state change, the patch) with a hold segment anchored to `t0` (§0.6, §2.3). Turns during a state change's 190 ms are recorded, not shown, and the entry uses the newest index **of the current `control_id`**. The new source's cards are a **second card set**; the old set is released after its 170 ms exit.
- **Turns during a source switch or Play** are recorded, not shown. The switch's entry uses **the `index` K3 sent in `explorer_source`** (the new source's remembered index); positions tagged with the old `control_id` are **discarded**, because they are positions in the old source's bounds (K3 §5.3.3, C5-9; §5.3); a later `explorer_highlight` or fast-path position of the new control wins as usual. After Play, turns are dropped (BS:922; A05 §5.6).
- **A turn during the open stagger** retargets X, S and opacity from their current twin values. The rise and the enter scale keep running on their own properties (§4.6.6), so the card joins its new slot without a jump.
- The labels, tabs and dots stay visible during the Play grow (BS:1040-1045).

### 7.7 Preload and art per card

- **Preload window** (S01:267; CH r2.1): ±12 items on wide monitors and ±6 on 16:9, plus 4 more in the direction of travel, at display size. Anything in the window without a ready sprite shows `art.loading`, never a blank card.
- **Requests** (§13.1): L1 from the **600** rung for every item in the window; L0 from the **1200** rung for `|d| ≤ 2`, plus the next item in the direction of travel, so L0 is ready when a card reaches `|d| = 1`.
- **Build priority:** `|d|` ascending, the direction of travel first. Jobs for items leaving the window are cancelled (newest wins).

---

## 8. Scene: Up next (`upnext`)

Sources: S01 §6 (S01:322-364), App A (S01:487-497), App B (S01:534), BS:207-270, BS:859-890, BS:1194-1229. It never takes focus and **stays inside the 16:9 stage**; on 32:9 the frost and ambient fill the sides (S01:449).

### 8.1 Layers, bottom to top

| # | Visual | Notes |
|---|---|---|
| 1 | Frost, tint folded in | `blur.upnext` (§12) |
| 2–3 | Ambient A, B | opacity 0.45 while showing; the same mechanics as §7.5, following the big cover's album |
| 4 | Stage container | — |
| 4.1 | Left column (LAYER) | a container with the enter rise and fade: the big-cover frame (fixed shadow sprite, cover A, cover B, inset line) and the text sprites |
| 4.2 | Focus plate | one sprite: fill, inset and shadow (§8.2) |
| 4.3 | Rows container | carries the vertical end bump |
| 4.3.x | Row containers (MULTIPLY) | §8.3 |
| 4.4 | Hints | one sprite, re-rendered when its words change |

### 8.2 Geometry (units; px at k = 2)

- **Left column** (S01:325-327; BS:212-240): x 120, y 120, width 380 → x 1520, y 240 px.
  - **Big cover** 380 × 380 (760 px), `#1B1B1D` base, fixed shadow `0 40px 80px rgba(0,0,0,.55)` (a 1/4-resolution sprite), inset 1 px at 0.12.
  - **Text** starts 18 below the cover (y 518 units), gap 6: caption `overlay.upnext.header` (`Up next`) 13 px 600, 0.12 em, uppercase, at 0.72; title 24/30 600, ellipsis at 380; sub 15 px at 0.86, ellipsis.
  - **Shuffle line:** a 16 px `shuffle` icon (stroke 2), gap 6, text 13 px: `overlay.upnext.shuffle_on` / `.shuffle_off` / `.shuffle_sonos`, in `#FFFFFF` when on (companion or Sonos) and at 0.60 when off. A colour or text change is a crossfade of two sprites over 240 ms EASE (BS:235).
  - Context title and sub are **drawn as K3 sends them** in `context{kind, title, sub}` (strings already filled, K3 §9.7.3): album `{title}` and `{artist} · {year}`; a favourited playlist `{title}` and `Favourite playlist · {n} songs · {duration}` (BS:1230's `ctx.n` is the `{n} songs · {h} h {mm} min` string), a non-favourited one `overlay.upnext.sub_playlist`; foreign `overlay.upnext.foreign_title` (`Sonos queue`) and `overlay.upnext.foreign_sub` (BS:1230; S01:337). The presenter composes no context text of its own.
- **Focus plate** (S01:328-330; BS:241): fixed at x 600, y 276, 560 × 88 units (x 2480, y 552, 1120 × 176 px). Fill `rgba(255,255,255,.14)`, inset 1 px at 0.28, shadow `0 20px 50px rgba(0,0,0,.35)`, all baked into one sprite. The rows move through it; no row animates a background or shadow.
- **Rows** (S01:331; BS:244, :1197): left 600, centre y 320, 560 × 88 units, scaled about their left-middle point. `a = min(|d|, 4)`, `d = k − focus`.

| a | Offset Y | Scale | Opacity | Row px (k = 2) | Played row (`k < now`) |
|---|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 1120 × 176, centre y 640 | opacity × 0.6 |
| 1 | ±100 | 0.78 | 0.72 | 873.6 × 137.3, centre 440 / 840 | × 0.6 |
| 2 | ±176 | 0.66 | 0.46 | 739.2 × 116.2, centre 288 / 992 | × 0.6 |
| 3 | ±236 | 0.58 | 0.24 | 649.6 × 102.1, centre 168 / 1112 | × 0.6 |
| 4 | ±284 | 0.52 | 0 | hidden | — |

- **Row inside** (BS:245-256): height 88, padding 0 20, gap 18.
  - **Lead:** art, a 56 × 56 cover (112 px surface) with an inset 1 px at 0.12; or the number, 40 wide, 20 px 500 at 0.72, two digits, tabular (fixed digit cells, since PIL has no `tnum`, A05 §5.1).
  - Art is used for a playlist or foreign context, for placeholders, and for rows whose album is not the context album (a Play-next block). The number is used for rows of the context album (BS:1210).
  - **Text:** title 22/26 600 white, ellipsis; sub 14/18 at 0.82, ellipsis: `{artist}` for context-album rows, else `{artist} · {album}`; non-catalog rows add the `overlay.upnext.row_not_catalog` suffix (S01:339).
  - **Right group** (gap 12): tag 12 px 600, 0.08 em, uppercase: `overlay.upnext.tag_now` in `#6ED996` on the now-playing row, `.tag_next` only on `now + 1`, `.tag_played` on `k < now`, all others at 0.70 (BS:1214-1215). Then the heart (§8.3).
- **Hints** (BS:261-268): top 664, as §7.4, with `overlay.upnext.hints`: `[1] Back` · `[2] Shuffle` \| `Shuffle off` · `[3] Like` \| ~~`Unlike`~~ **[r2.2]** `Liked` · `[4] Play` (**[r2.2]** `[3] Like` \| **`Liked`**: a liked row shows `[3] Liked`, R22 CH §1; `Unlike` is withdrawn). The sprite is swapped (instant) when the shuffle state or the focused row's liked state changes.
- **Hit rect** for the click action: the focus plate (§3).

### 8.3 Row kinds and hearts

| Kind | Lead | Text | Tag | Heart |
|---|---|---|---|---|
| Track, catalog song | number or art | title, sub | per §8.2 | per state below |
| Track, not in Apple Music | art (Sonos 400 → 112 px) | sub with the suffix | per §8.2 | ~~**none** (S01:340)~~ **[r2.2] outline at 15 %**, no Like (R22 CH §1; S5-34) |
| Placeholder (loading) | a 56 px block at 10 % white | two bars: 16 px tall at 14 % white and `(40 + (k·37) mod 40) %` wide; 10 px tall at 10 %, 34 % wide, 6 below (BS:249) | none | none |
| Sonos-shuffle card | none | `overlay.upnext.card_title` / `.card_sub` (`Sonos is shuffling the rest` / `{n} songs · order isn’t shown`) | none | none (S01:360; BS:1199) |

Heart states (BS:255): a 20 px glyph, one sprite for each form, both centred on the heart's origin. **[r2.2]** Three forms now: the **outline** (stroke `#FFFFFF`, 1.8), the **dashed outline** (the same stroke with dash 2.2 / gap 2.4 in the 24-unit glyph space, R22 BS:255 `stroke-dasharray`) and the **filled** heart (`#FF285A`); each is one prepared sprite, faded only. The r2.1 table below is replaced by the r2.2 table after it (R22 CH §1: "four distinct states"; R22 BS:1223 `ghostOp`, `dash`).

**r2.1 (superseded [r2.2]):**

| State | Outline (stroke `#FFFFFF`, 1.8) | Filled (`#FF285A`) |
|---|---|---|
| Likes not loaded yet, row not liked | opacity 0.40 (S01:347) | 0 |
| Not liked | 0 | 0, scale 0.4 |
| Liked | 0 | 1, scale 1 |
| Like lands | 0 | opacity 0 → 1 over 200 ms OUT; scale 0.4 → 1.5 over 380 ms SPR, then at +420 ms 1.5 → 1 over 380 ms SPR (App A S01:495 read per leg, S5-31; BS:255, :827-828) |
| Unlike lands | 0 | opacity 1 → 0 over 200 ms OUT; scale → 1.5 over 380 ms SPR, then at +420 ms → 0.4 over 380 ms SPR (not in App A; BS:255, :827-828, :1216; S5-31). **[r2.2] Withdrawn** (no unlike, R22 CH §1) |

**[r2.2] The four row-heart states (R22 CH §1; R22 S01 §6 "Row heart states"):**

| State | Outline sprite | Dashed sprite | Filled sprite (`#FF285A`) |
|---|---|---|---|
| **Liked** | 0 | 0 | opacity 1, scale 1 |
| **Not liked** | opacity **0.45** | 0 | 0, scale 0.4 |
| **Not known yet** (`likes_known` false, or the row's `liked` is `None`) | 0 | opacity **0.30** | 0, scale 0.4 |
| **Not in Apple Music** (non-catalog row) | opacity **0.15** | 0 | 0; no Like, and never a pop |
| Placeholder row, Sonos-shuffle card | 0 | 0 | 0 (no heart, as before) |
| **Like lands** (a `likes` patch) | → 0 at once | 0 | opacity 0 → 1 over 200 ms OUT; scale 0.4 → 1.5 over 380 ms SPR, then at +420 ms 1.5 → 1 over 380 ms SPR (unchanged, S5-31) |

Precedence when several apply (R22 BS:1222-1223): placeholder / card → not in Apple Music → not known yet → liked / not liked; so a non-catalog row never shows the dashed form. A change between the first four states that arrives in a `data` patch (likes loading → known, a row that turns non-catalog) goes to the new rest form: ~~the sprite opacities switch at once, as BS does (the outline layer has no transition, R22 BS:255)~~ **[r2.2]** the outline and dashed sprites switch opacity at once (R22 BS:255: that layer has no transition), and the filled layer **fades in** as the prototype's does (R22 BS:255: `opacity 200ms cubic-bezier(0.22,1,0.36,1)` on the filled layer, i.e. OUT): when a `data` patch makes a row liked, the prepared filled sprite's opacity goes 0 → 1 over **200 ms OUT**, an opacity crossfade of the prepared filled sprite (a compositor opacity animation, allowed at 240 Hz; nothing is re-rendered), with its scale set to 1 at once (a `data` patch never pops; the prototype's 380 ms scale transition is adopted for Like lands only). There is no animation from liked to anything else (the filled sprite's opacity goes 1 → 0 at once; R22 CH §1 removes any heart-off animation): a liked heart only leaves the liked state through a `data` patch after the user unfavourites the song in the Music app (K3 §5.6.6).

The heart **animates** only when an `upnext_rows{reason: likes}` patch arrives (a confirmed like or unlike; **[r2.2]** a confirmed like: there is no unlike), that is, when K3 decides it has landed (VOC-D03). Heart states that arrive in **`data`** patches (the first states from the catalog or ratings batch, a row that turns non-catalog) are **set without a pop**: the heart jumps to its state's rest form (**[r2.2]** except the filled layer's 200 ms opacity fade-in above, which is not a pop). The presenter never pops a heart on the press (K3 §5.6.6, C5-54).

### 8.4 Big cover and ambient

- **Album context:** the cover is the context album's and **stays still**, even when the focus is on a Play-next row of another album (S01:326; BS:1222).
- **Playlist or foreign context:** the focused row's album cover. Each change restarts a **120 ms** debounce; when it fires, the newest cover is set on the hidden layer and the two crossfade over **420 ms OUT** (App A S01:493; BS:215, :781). Newest wins during a spin.
- **Ambient:** follows the same album as the big cover, with §7.5's 200 ms debounce and 600 ms crossfade, opacity 0.45 (App A S01:494).
- The cover's art states: 760 px from the 1200 rung (catalog) or `art.extended` from Sonos 400 (cover at 600 px, inset 10.5 %, S01:290); `art.generated` (title 38/41 800, artist 17/22, at left 28 / top 26, rule at bottom 28, BS:218-224); `art.loading`.

### 8.5 Motion (App A S01:487-497 unless marked)

| Event | Element | Property: from → to | ms | Delay | Curve |
|---|---|---|---|---|---|
| Open | Scene root | opacity 0 → 1 | 340 | 0 | OUT |
| Open | Left column | translateY +20 → 0 | 460 | 0 | OUT |
| Open | Left column | opacity 0 → 1 | 320 | 0 | OUT |
| Open | Row (enter) | translateX +40·S → 0 | 420 | 40 × a | OUT |
| Open | Row (enter) | opacity 0 → table | 300 | 40 × a | OUT |
| Open | Focus plate | opacity 0 → 1 | 320 | 0 | OUT (BS:241) |
| Close | Scene root | opacity 1 → 0 | 340 | 0 | OUT |
| Turn | Row | Y, S → the new slot | 420 | 0 | OUT |
| Turn | Row | opacity → table (× 0.6 if played) | 300 | 0 | OUT |
| Turn | Big cover | A ↔ B (playlist and foreign only) | 420 | 120 debounce | OUT |
| Turn | Ambient | A ↔ B | 600 | 200 debounce | OUT |
| End stop (knob `lim`) | Rows container | translateY 0 → −14·dir, then → 0 | 160 + 160 | 0 / 160 | OUT (App A S01:497 per leg, S5-31) |
| Shuffle (Button 2) | Rows | opacity → 0 | 160 | 0 | IN (S5-5) |
| Shuffle | Rows in the new order, focus = `now + 1` | enter as on open (stagger 40 × a) | 420 / 300 | 200 + 40 × a | OUT |
| Shuffle | Shuffle line, hints | crossfade; sprite swap | 240; instant | 200 | EASE; — |
| Like / unlike (**[r2.2]** Like only) | Heart | per §8.3 | 380 + 380 | 0 / 420 | SPR (S5-31) |
| Play (Button 4, or the plate click) | Focused row | scale 1 → 1.06 | 420 | 0 | OUT (BS:1206; S5-7) |
| Play | Other rows | opacity → 0 | 300 | 0 | OUT |
| Play | Focus plate | opacity → 0 | 320 | 0 | OUT (BS:1407) |
| Play | Scene root | opacity 1 → 0 | 340 | 380 | OUT |
| Data arrives for a loading row | Row sprite | swap, then opacity 0 → table | 160 | 0 (at rest) | OUT |

- The shuffle exit and the re-entry at +200 ms are anchored to the `t0` of K3's `upnext_rows{reason: shuffle}` patch, which carries the new order: the press for the companion shuffle and its restore, or the verified completion (`t1`) for the Sonos regime (K3 §5.6.5). The knob re-enters at the same `t0` + 200 (K3 §6.2).
- Turns during the shuffle window (0–200 ms) or Play are recorded, not shown (BS:935).
- The left column does not scale on Play: r2.1 dropped r1's 1.04 (BS:1410; S5-7).

### 8.6 Rows at rest: the sharpen pass (AR-17)

- Row text sprites are rendered at scale 1 (the focus size) and minified by the GPU at 0.78 / 0.66 / 0.58, which is slightly soft at rest.
- **Sharpen pass (on by default; G1 check P5 confirms):** 150 ms after the twin reports that the rows have settled, each visible row with a ≠ 0 gets an exact-scale text sprite (rendered on a worker, ≈ 6.7 ms each) that crossfades in over 120 ms OUT in place of the minified one. The first turn discards them.
- The prefetch keeps scale-1 sprites for ±4 rows beyond the visible ones (RF0 §2.2).

---

## 9. Window picker v2 and snap (on the v6 host)

Sources: S01 §7 (S01:366-418), App A (S01:498-511), App B (S01:535-536), R §7.3, BS:57-122, BS:1048-1097, BS:1141-1167; the v6 contracts CAR §1-§11. The picker **takes focus** (S01:367). It stays on the v6 window stack (S5-2): DirectComposition cannot animate a DWM thumbnail (RF2 §4a), and the focus contract needs the activatable in-process host (CAR §1).

### 9.1 What stays from v6, and what changes

- **Stays:** the whole CAR §1 focus contract (the activatable host that owns the foreground; the 150 ms show handshake; verifies of ≤ 250 ms for our window and ≤ 100 ms for others; Switch activates first; no icon work on the WM_HOTKEY path), the thread rules, CAR §6 labels, §7 icons, §8 text, the closed and minimized card rules (CAR §2), the plain-host fallback (CAR §5), and the `picker_background` setting `glass` (Frosted, default) \| `none` (UI:117; R:144).
- **Changes in v7** (the CAROUSEL.md amendment of §20.1): the host grows to `rcMonitor`; the chrome is a band; 400 × 250 cards on two tables; the frame layer and crossfading shadows; the chip; the tray, fly and placement; the new frost recipe; the dots marker; the rise on open; no Switch grow; pacing per §5; B1–B5; FrameStats.

### 9.2 Windows in v7

| Layer | Rect | Change from v6 |
|---|---|---|
| Dim (No background only) | `rcMonitor` | flat `rgba(0,0,0,0.55)` (App B S01:536); unchanged |
| Glass (Frosted only) | `rcMonitor` | **new recipe** `blur.picker_frost` (§12): σ 40·k/8, saturate 1.6, tint `rgba(10,10,12,.50)`, **no dim**, no sheen (S5-21) |
| Host | **`rcMonitor`** (was the pane) | still NOREDIRECTIONBITMAP and activatable. It is the destination of every thumbnail, including the fly and the tray slots. It eats clicks anywhere on the monitor (00 §3.2). `presenter.rect` still reports the card area (CAR §11) |
| Chrome | **a band:** x = stage centre ± `max(X[a_vis] + 200·S[a_vis] + 20, 470)` units, where `a_vis` is the last visible slot (§9.3), y 76–668 units, clamped to the monitor. On the user's 32:9: ± 765 units → 3060 × 1184 px (14.5 MB); on 16:9: ± 488 units | was the pane + 16 units (11.1 MB). Holds shades, frame, shadows, badges, chips, label, dots, marker and the tray chrome. Uploaded with `UpdateLayeredWindowIndirect` and `prcDirty` (B5) |
| Toast | its own window | lifted into the toast service (§10) |

### 9.3 Geometry (units; px at k = 2)

- **Card:** 400 × 250 (800 × 500 px) at centre (640, 370), (2560, 740) px, once the tray is shown. The whole cards group (cards, label, dots) sits 44 units higher (centre y 326) until the first snap or snap failure (BS:81, :1399).
- **16:9 table** (S01:374-380; BS:1142): `a_max = 4`

| a | Offset X | Scale | Opacity | Shade `#111` |
|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 0 |
| 1 | ±280 | 0.56 | 0.95 | 0.22 |
| 2 | ±400 | 0.34 | 0.60 | 0.44 |
| 3 | ±490 | 0.26 | 0 | 0.55 |
| 4 | ±540 | 0.20 | 0 | 0.55 |

- **32:9 table** (S01:382-390; BS:1142): `a_max = 5`

| a | Offset X | Scale | Opacity | Shade | Offset px |
|---|---|---|---|---|---|
| 0 | 0 | 1.00 | 1 | 0 | 0 |
| 1 | ±280 | 0.56 | 0.95 | 0.22 | ±560 |
| 2 | ±420 | 0.42 | 0.70 | 0.44 | ±840 |
| 3 | ±545 | 0.40 | 0.45 | 0.55 | ±1090 |
| 4 | ±665 | 0.40 | 0.25 | 0.55 | ±1330 |
| 5 | ±780 | 0.40 | 0 | 0.55 | ±1560 |

- Shade = `min(0.55, 0.22·a)` on both tables (BS:1150). The thumbnail opacity under a chrome shade keeps CAR §2's formula `o = op·(1 − s) / (1 − op·s)`, with the shade drawn at `op·s`. For example, a = 3 on 32:9: o = 0.269 under a 0.248 shade.
- **Registration:** thumbnails are registered for `|d| ≤ a_vis + 1`, where `a_vis` is the last visible slot (2 on 16:9, 4 on 32:9), plus cards still fading (CAR dev 10). Re-registration runs far → near on each detent, then the fly thumbnail, so the fly stays on top.
- **Card face** (BS:84-99):
  - `#1B1B1D` base; the thumbnail is cover-fit and top-aligned (CAR §2), flat and square, with no perspective, rotation or rounded corners; the r1 Arc study is withdrawn (S01:392; CAR dev 1).
  - Badge 30 × 30 at left 12 / bottom 12, shadow `0 2px 8px rgba(0,0,0,.45)`, letter tile 16 px 700 (CAR §7).
  - Snap chip, when the window holds a side: left 12 / top 12, padding 4 × 8, `rgba(18,18,20,.72)`, a 16 px `rect` + `HALF` icon (stroke 2), then `overlay.picker.badge` (`Left` / `Right`) 12 px 600.
- **Selection frame** (S01:393; BS:87): a separate 2 px `rgba(255,255,255,.9)` square frame 8 units outside the centre card. Opacity 0 → 1 over 320 ms OUT as a card enters the centre.
- **Shadows** (BS:85-86): two fixed layers per card, side `0 12px 30px rgba(0,0,0,.30)` and focus `0 24px 60px rgba(0,0,0,.45)`, crossfading over 320 ms OUT. The **same on both backgrounds** (S5-20).
- **Label** (S01:394; BS:102-109): column at left 190, width 900, top 512 (468 before the tray shows), centred, gap 6.
  - App row: 18 × 18 icon + app name 15 px at 0.92, gap 8. Title 26/32 600, ellipsis at 900. Description 15 px at 0.86, plus `overlay.picker.desc_snapped` when the centre window holds a side.
  - With No background, the label has the text shadow `0 1px 2px rgba(0,0,0,.6)` (App B S01:536).
  - Swap at the detent, then fade in over 160 ms OUT.
- **Dots and marker** (S01:395): as §7.4 (0.40 dots, 6 × 6 marker, 420 ms OUT), at top 622 (578 before the tray shows). No hint row.

### 9.4 Snap tray (S01:398-399; BS:62-79, :1156-1167)

- **Container:** full stage width at top 104 (y 208 px), slots centred, gap 14. Slot 1 (left) is at x 457–633 units, slot 2 (right) at 647–823.
- **Hidden** until the first snap or the first snap failure (`trayOn`, BS:1155).
- **Reveal:** translateY −14 → 0 and scale 0.94 → 1 about the container centre, 460 ms SPR; opacity 0 → 1 over 260 ms OUT; the cards group translateY −44 → 0 over 460 ms OUT (App A S01:504-505).
- **Slot:** a 176 × 110 box (352 × 220 px) with background `rgba(255,255,255,.04)` and an overflow clip. Below it, gap 6: a caption row with the key box (`2` / `3`) and a 12 px label at 0.86.

| Slot state | Border | Content | Caption |
|---|---|---|---|
| Empty | 1 px dashed `rgba(255,255,255,.4)` | a 34 px `rect` + `HALF` glyph, stroke 1.8, at 0.80 | `overlay.picker.slot_empty` |
| One-side preview (U12) | as empty | the origin window's thumbnail at **0.35** | `overlay.picker.slot_keep` at 0.70 |
| Filled | 1 px solid `rgba(255,255,255,.5)` | the window's live thumbnail (fill opacity 0 → 1 over 260 ms OUT) + a 22 × 22 badge at left 8 / bottom 8 | `overlay.picker.slot_filled` |
| Failure (2.4 s) | 1 px solid `rgba(255,132,116,.9)` | unchanged | `overlay.picker.slot_hung` / `.slot_move` / `.slot_fit` in `#FF8474` |

- The one-side preview shows only while exactly one side is filled and the origin window (the foreground window at open) holds neither side (BS:1160).
- Border colour changes are crossfades of two border sprites over 260 ms EASE; the empty glyph fades over 200 ms EASE; the badge over 260 ms EASE (BS:65-71).
- Tray thumbnails are DWM thumbnails on the host (up to 3: left, right, preview). Their rects follow the tray's spring, stepped per frame with the chrome.

### 9.5 Snap flow (t = 0 when `windows_snap` reaches the presenter)

| t (ms) | Event | Owner |
|---|---|---|
| 0 | **Pre-checks** on `NanoD-snap` (≤ 5 ms): the identity still matches (`same_identity`, WN:298-305); not hung (`IsHungAppWindow`); integrity level not above ours (`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetTokenInformation(TokenIntegrityLevel)`; if the query fails, carry on). A failure here → `snap_result(side, hung \| move_rejected)` at once: no fly, no assignment, the slot's failure state and the tray reveal (§9.6) | adapter / snap |
| 0 | Pre-checks passed: post **`snap_result(side, accepted)`** at once (K3 assigns the side, sends the half-wash `feedback{ok, moment:"snap"}` and lights the slot button; K3 §5.7.3, C5-53). The side is assigned. If the same window held the other side, that side is cleared (a **move**, BS:1078). The slot fills; the chip and the description suffix appear; the first snap reveals the tray | presenter |
| 0–460 | **Fly:** a second DWM thumbnail of the same window. Its `rcDestination` goes from the card's live rect to the target rect by translation + **uniform scale**, 460 ms OUT, re-registered last so it is on top. Its opacity is 1 → 0 over 220 ms OUT from 380 ms (App A S01:507-508). ~~**No fly shadow in v7** (S5-4)~~ **[errata]** No fly shadow on the step-1 (CPU) chrome (S5-4); step 3 draws the fly's shadow (§9.10; 21.4 E-h) | carousel |
| 360 | **The real window moves once, under cover** (§9.6), on `NanoD-snap` | adapter / snap |
| 360–≤ 800 | Verify (≤ 200 ms; UWP frames ≤ 400 ms), always inside the **hard deadline of t0 + 800 ms** (§9.6). Success → `snap_result(ok)`, then re-query `DwmQueryThumbnailSourceSize` and recompute `rcSource` for the card, the slot and the fly. Failure, or the deadline → `snap_result(move_rejected \| cant_fit)`, the window is put back per §9.6 step 7 and the slot goes to the failure state | snap |
| ≤ 800 | **Deadline:** `snap_result` has been posted, by the worker or by the carousel's backstop (§9.6). K3's latched Back or hold (C5-12) runs now at the latest | snap / carousel |
| 420 | With one side filled, the highlight advances to the **next window after the snapped one in list order, wrapping at the end, that is neither assigned nor closed** (S01:405 "advances to the next unassigned window", over BS:1090's first-unassigned `findIndex` from 0; K3 C5-46), unless a detent arrived since t0 (K3 C5-10). Example: windows A, B, C, D with nothing assigned; snapping C highlights D, then snapping D highlights A. This is a host-driven re-entry that K3 owns; the presenter just receives `windows_highlight` | K3 |
| 600 | The fly thumbnail is unregistered | carousel |
| 820 | With both sides filled: `windows_close_pair` (§9.7) | K3 |

- **Fly target** (S01:401; BS:1080-1081): `kf = min(halfW / (400·k), workH / (250·k))`, in physical px of the picker monitor's `rcWork` half. The box `(400k·kf) × (250k·kf)` is centred in the half. On the G93SC: half 2560 × 1392 px, kf = min(3.2, 2.784) = 2.784, box 2227 × 1392 px at x 166 (left) or 2726 (right), y 0.
- **Fly start:** the centre card's live rect at t = 0. BS starts from the tray-hidden position when the tray isn't shown yet (BS:1081).
- The fly's source is the window that moves at 360 ms. When the move is verified, its `rcSource` is recomputed. The content then changes while the fly is already fading, which reads as the window settling into its new shape.

### 9.6 The placement recipe (VOC §8.4 `snap`; VOC-D01)

Runs on **`NanoD-snap`**, never on the Tk or carousel thread (S5-14). Physical px, since the process is PMv2.

- **Never wait on the target.** The target can stop pumping messages at any moment after the t = 0 pre-check, and `IsHungAppWindow` only reports a window after about 5 s without `PeekMessage` (MS-13), so a busy app passes it. The recipe therefore reaches the target's window **only** through the two calls that post to the target's thread and return at once: `ShowWindowAsync` (MS-11) and `SetWindowPos` with `SWP_ASYNCWINDOWPOS` (0x4000), whose purpose is that the caller does not block while the other thread handles the request (MS-12).
  - **Forbidden on another process's window:** `SetWindowPlacement`, `ShowWindow`, and `SetWindowPos` without the async flag. None of them has an asynchronous form, so each waits while the target's thread handles the window-position messages.
  - **Allowed, since they never wait on the target:** `GetWindowPlacement`, `GetWindowRect`, `IsWindow`, `IsIconic`, `IsZoomed`, `IsHungAppWindow`, `GetWindowThreadProcessId`, `DwmGetWindowAttribute`, the process and token queries of `native.identity` (WN:481-491) and the integrity pre-check.
  - A unit test with a fake native layer asserts that the snap code issues no other call on a target window (§20.1 item 4).
- **Hard deadline.** A `snap` job resolves by **t0 + 800 ms** (`SNAP_DEADLINE_MS`, t0 = the press, §9.5). A `complete_one_side` job resolves by its start + **600 ms** (`ONE_SIDE_DEADLINE_MS`: the 150 ms restore poll, the 400 ms UWP verify and 50 ms of slack).
  - The worker never starts a wait that would end past the deadline. At the deadline an unfinished job resolves as **`move_rejected`**, runs step 7 (which only posts, so it cannot block) and posts `snap_result`.
  - **Backstop:** the snap presenter on `NanoD-carousel` arms the same deadline when it hands the job over. If no result has arrived by then (the worker died), it posts `snap_result(side, move_rejected)` itself. The first result for a job id wins, and a later one is dropped. A worker that finds its job already resolved runs step 7 before it moves on. The carousel's idle wait uses a timeout equal to the time left to the deadline; this is an idle-path wait on the P9 allowlist.
  - So K3's latched Back or hold (C5-12, now "≤ 800 ms") runs **no later than t0 + 800 ms**, before the pair close at t0 + 820 ms (§9.5). K3's own controller backstop, which treats a snap with no `snap_result` 1000 ms after t0 as `move_rejected` (K3 §5.7.3), stays as the last resort for a lost event; with this deadline it never fires in normal operation.

1. **Save** `P0 = GetWindowPlacement(hwnd)` and `W0 = GetWindowRect(hwnd)`.
2. **Target:** V = the left or right half of `rcWork` of the picker's monitor; with an odd width, the right half takes the extra pixel.
3. **Restore without activating** when `IsIconic` or `IsZoomed`: `ShowWindowAsync(hwnd, SW_SHOWNOACTIVATE)` (4), which shows the window at its restored size without activating it (MS-14). Poll `IsIconic` and `IsZoomed` every 10 ms for at most **150 ms**.
   - A minimized window whose placement carries `WPF_RESTORETOMAXIMIZED` (0x2) may come back maximized. If `IsZoomed` turns true, post `ShowWindowAsync(SW_SHOWNOACTIVATE)` once more, inside the same 150 ms.
   - Still iconic or zoomed at 150 ms → `move_rejected` (step 7).
   - **Never `SW_RESTORE` (9)**: it activates the target and the picker dismisses itself (00 C24; A05 §6.4). **Never `SetWindowPlacement`** (it can block). This drops A05 §6.4 step 3's one-call variant that also set `rcNormalPosition` = V: the window shows its own restored rect for the few frames before step 5, under the frost (Frosted) or visibly (No background, accepted for every snap move, A03 §4.9).
4. **Measure:** W = `GetWindowRect`, E = `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS = 9)`.
5. **Place:** R = (`V.left − (E.left − W.left)`, `V.top − (E.top − W.top)`, `V.right + (W.right − E.right)`, `V.bottom + (W.bottom − E.bottom)`), then `SetWindowPos(hwnd, NULL, R, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_ASYNCWINDOWPOS)` (0x4214).
6. **Verify:** re-read E every 20 ms until it is within 2 px of V, for up to 200 ms (400 ms for `ApplicationFrameWindow`), **cut short by the deadline**. Without a restore every window gets its full verify window (360 + 200, or 360 + 400 = 760 ms); after a restore a UWP window keeps at least 290 ms of it (800 − 360 − 150).
   - A DPI change on the way re-applies step 4–5 once after the app's `WM_DPICHANGED` resize.
   - E wider or taller than V by more than 2 px → `cant_fit`. Anything else that doesn't match, including a UIPI refusal hidden by the async flag, and the deadline → `move_rejected`.
7. **On failure** (including the deadline): put the window back **without activating and without waiting**, with posted calls only. Skipped when nothing was posted yet.
   - N = its saved normal rect: `W0` when it was neither minimized nor maximized; otherwise `P0.rcNormalPosition` converted from workspace to screen coordinates (add `rcWork.left − rcMonitor.left` and `rcWork.top − rcMonitor.top` of the monitor that holds it; a `WS_EX_TOOLWINDOW` window's placement is already in screen coordinates).
   - `SetWindowPos(hwnd, NULL, N, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_ASYNCWINDOWPOS)` (0x4214).
   - **Was minimized:** then `ShowWindowAsync(hwnd, SW_SHOWMINNOACTIVE)` (7), which minimizes without activating (MS-14). A `WPF_RESTORETOMAXIMIZED` flag it had is lost.
   - **Was maximized: left restored at N.** Every maximize command activates the window (`SW_SHOWMAXIMIZED` = `SW_MAXIMIZE` = 3, MS-14). That would dismiss the open picker, or, after the close, take the foreground from the window the picker gave it back to. **No activating command is ever sent** (S5-32).
   - So "nothing moves" (S01:412; S5-13) holds for normal and minimized windows; a maximized window comes back restored (S5-32).
8. **Foreground check:** afterwards `GetForegroundWindow()` must still be the picker host. If it isn't, call `native.focus(host)` once (it works only while this process still holds the grant); otherwise close the picker as `focus_lost` (A05 §6.6).
9. **No "Snap group" claim** anywhere (S01:407).

### 9.7 Close paths

| Close | Sequence |
|---|---|
| **Switch** (Button 4, or the centre-card click) | v6: the adapter activates the target synchronously first (CAR dev 3). Then the exit: root opacity 1 → 0 over 280 ms OUT and the cards group 1 → 0 over 220 ms EASE (BS:81). **No 1.35 grow** (S5-6). Thumbnails are released at the end. `toast.switch` at +360 ms |
| **Back / hold** with no side filled | v6 cancel path: focus the origin, then the same exit; post `cancel_result(restored, completed = false)`. No toast (R:152) |
| **Back / hold** with one side filled (U12) | `complete_one_side` first, on `NanoD-snap`: the origin window takes the other half with §9.6, resolved within its **600 ms deadline**. Then focus the origin; the exit; post **`cancel_result(restored, completed)`**. K3 raises `toast.snap.one_side` (at `max(close + 360 ms, cancel_result)`) **only on a `back` close after `completed = true`; a `hold` close raises no toast** (VOC §7.3; K3 §5.7.4, C5-36). The frost is a snapshot, so the moves stay hidden until it has faded (S01:404). With No background they are visible, which is accepted (A03 §4.9) |
| **Pair** (820 ms after the second snap) | On `NanoD-snap`, while this process still owns the foreground: raise the side snapped **first** with `SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE \| SWP_NOSIZE \| SWP_NOACTIVATE \| SWP_ASYNCWINDOWPOS)` (0x4013), then focus the side snapped **last** through `native.focus`, the v6 focus path on its usual thread (00 U12), which raises it too; the exit; `toast.snap.pair` at +360 ms. Nothing waits on either window (§9.6). The posted raise lands when that window's thread next pumps; the two halves don't overlap, so the order in which the raises land doesn't matter. **S3 checks** that the first-snapped window ends above the origin: MS-12 ties a raise to foreground permission of the process that owns the window, and a posted raise runs on that process's thread. If S3 finds the posted raise refused, the fallback is the synchronous raise (`0x0013`) on a short-lived thread of its own (`NanoD-raise`), fire-and-forget: neither the close nor `NanoD-snap` ever waits for it |
| **lock / sleep / idle** | instant hide (v6 hide path); then `complete_one_side` if one side is filled (VOC-R15); focus is not restored while locked or asleep; post `cancel_result(restored, completed)` (no toast follows these closes, K3 §12.4) |
| **disconnect, focus_lost, display** | instant hide; no one-side completion (VOC-R15; §15) |

### 9.8 Motion (App A S01:498-511 unless marked)

| Event | Element | Property: from → to | ms | Delay | Curve |
|---|---|---|---|---|---|
| Open | Root (frost or dim) | opacity 0 → 1 | 280 | 0 | OUT |
| Open | Card (enter) | rise +24·S → 0; enter scale 0.92 → 1 (× S); opacity 0 → table | 420 | 0 (no stagger) | OUT |
| Turn | Card | X, S → the new slot | 420 | 0 | OUT |
| Turn | Card | opacity → table | 300 | 0 | OUT |
| Turn | Shade | opacity → table | 320 | 0 | OUT (S5-5) |
| Turn | Selection frame; shadows | 0 ↔ 1; side ↔ focus crossfade | 320 | 0 | OUT |
| Turn | Marker; label | translateX 420; swap, then fade in 160 | 420; 160 | 0 | OUT |
| End stop (knob `lim`, keys, wheel) | Cards container | translateX 0 → −12·dir → 0 | 160 + 160 | 0 / 160 | OUT (BS:82, :778; CAR §4; S5-8, S5-31) |
| First snap | Tray | translateY −14 → 0, scale 0.94 → 1; opacity 0 → 1 | 460; 260 | 0 | SPR; OUT |
| First snap | Cards group | translateY −44 → 0 | 460 | 0 | OUT |
| Snap | Slot fill | opacity 0 → 1 | 260 | 0 | OUT |
| Snap | Fly | translate + uniform scale; opacity 1 → 0 | 460; 220 | 0; 380 | OUT |
| Snap | Real window | `SetWindowPos`, no animation | — | 360 | — |
| Close | Root; cards group | opacity 1 → 0 | 280; 220 | 0 | OUT; EASE |

### 9.9 The frame loop (step 1 in v7)

- It runs on `NanoD-carousel` under §5 (P2–P6: compositor-clock pacing, predicted time, the 120 lock).
- **Compose fixes from RF1 §5.2:** B1 (labels prefetched ±3 on a worker with masked pastes, §4.7.3, and more than 6 cached; the previous label stays until the new one is ready), B2 (label and dots in their own layered window, uploaded only on change), B3a (NEAREST shadow bands only while animating, BILINEAR at rest; this is a CPU resize inside the chrome, not a GPU sampling mode), B4 (badge scales quantised to 1/64), B5 (dirty rects).
- **Frame order** stays v6's: right after the pace wait, the thumbnail updates and the chrome ULW go out back to back (CAR:163).
- **The 32:9 table** shows 9 cards instead of 5, so the chrome's shadow area grows about 1.4× (the shadow masked paste is 69–73 % of compose, RF1 §3.2). Whether step 1 holds 120 on this table is §22 Q2.

### 9.10 Step 3 in v7: the chrome on the GPU (lead ruling R-h, 2026-09-26; WP7c)

§22 Q2 is decided for step 3: the headless step-1 compose missed both budgets (CAROUSEL.md §12.3). The build is described in CAROUSEL.md §12.4, and its deviations are WP7c-D1…D13 there.

- **What moves.** Every picker element that is not a live window becomes a DirectComposition visual with a prepared surface, and **the compositor runs its animations**:
  - the side and focus shadows, the selection frame, the #111 shade, the badge, the chip and the placeholder face;
  - the label, the dots and the marker;
  - the tray (backgrounds, borders, glyphs, badges, captions);
  - the fly's shadow (S5-4 is lifted for step 3).
- **What stays.**
  - The live windows stay DWM thumbnails on the v6 host, stepped per frame on `NanoD-carousel` at the predicted display time (§5 P2–P5), through the GIL-keeping `DwmUpdateThumbnailProperties`, sent back to back, and skipped when unchanged.
  - The frost and the dim keep their layered windows.
  - The focus contract, the NOACTIVATE rules, capture exclusion (§2.6) and every behaviour of §9.1–§9.8 are unchanged.
- **Hosting.** The chrome is `control_center/stage/picker_chrome.py`. `carousel.py` never names the stage package; the one wiring point, `standalone.py`, installs the factory (§4.1). **[errata]** Wired (lead decision, 2026-09-26): `standalone.main` installs it right before ControlCenterApp builds the WindowsAdapter (a failed install leaves the step-1 chrome), and the input fast path (`ui.FastPath`) warms its device at a knob touch through `WindowsAdapter.note_touch()`, with the stage's warm-up and never more often (at most once per 10 s; 21.5 E-w).
- **Window (§2.1, §3).** A click-through `WS_EX_NOREDIRECTIONBITMAP` layered window (`0x082800A8`, alpha set once) owned by the picker host, on `rcMonitor`. It is the DirectComposition target, lies above the thumbnails, and clicks pass to the host.
- **Device (§4.2, §4.3).** The chrome has its own D3D11 + DirectComposition device on `NanoD-carousel`, created on the picker monitor's adapter at the first open or at a knob touch, and released after 600 s without an open.
  - A knob touch never holds `NanoD-carousel`, the thread that answers `show()`'s 150 ms handshake: `D3D11CreateDevice` (≈ 130 ms for the process's first device, 14–28 ms after) runs on a short-lived worker, and the carousel thread adopts it and makes the DirectComposition device (≈ 1 ms). An open that arrives first answers its handshake at once and waits for the worker in its setup (one device either way).
  - Every release keeps the device policy in step: a device made for another monitor is released and the next open or touch makes one on the right adapter; after a failed call that is not a loss, the next open tries the GPU again.
  - On loss or a failed sync or upload (in a frame with or without an event), the open picker continues on the step-1 chrome in that frame, and the next open retries. `NANOD_PICKER_CHROME=cpu`, `set_chrome_mode('cpu')`, the plain host and a missing chrome window select the step-1 chrome without warming a device.
- **Motion (§4.6).** At each event the chrome mirrors the carousel machine's tweens: the same start, target, duration, curve and **begin time** (the machine's `t0` in compositor ticks), fitted within §4.6.2's bounds, with one Commit per event.
  - Each chrome property is linear in one tween, by construction of the tree (the card's X, opacity, scale, rise and enter scale; the group's shift and fade; the bump's two legs; the tray; the marker; the label; the fly).
  - Unchanged and invisible properties cost nothing (G1-4).
  - Card visuals come from a pool (§4.7.1): 14 slots at the first open, then one more per frame without an event while fewer than 6 are free and the open's windows could use more, so a detent's batch never makes a visual, clip, transform or animation object.
- **Occlusion.** Every chrome visual is above every thumbnail. So a farther card's chrome is clipped at its nearer card's far edge, with an animated `IDCompositionRectangleClip` edge (not under a closed card).
- **Uploads.** A surface is uploaded, then `ID3D11DeviceContext::Flush` is called, and it is shown only once it is a frame old. Measured here: a Commit right after an upload costs about 3 ms; a frame later, about 0.1–0.2 ms. Sprites are prefetched in frames without an event, so a detent's batch carries properties only. A sprite that is not ready at a sync keeps the card's previous one and is synced in a frame later; the loop stays awake for it at rest too (new icons, labels, a card that closes).
- **Personal text.** At the picker's close, the label visuals and the placeholder faces are unbound in the batch of the chrome's last Commit, then the label surfaces are released; no surface of a window title stays bound while the device stays warm.
- **Gates.** §6.3's "Picker (W), step 3" row now applies.
  - Headless (`stage.picker_bench`, the `picker_selftest` H5 lines, gated at 32:9): per-frame Python work ≤ 1.5 ms p95 on normal frames (R-h) and ≤ 3.0 ms p95 on detent frames; with 30 windows, no card slot made inside a sync.
  - On screen (`tools/stage_checks/picker_snap_checks.py`, supervised): displayed frames ≥ 235 from the compositor's target statistics, the chrome Commits' pickup, the carousel thread's CPU ≤ 35 %, and AR-12's alignment witness. If the thumbnails trail the chrome by a frame, `NANOD_PICKER_THUMB_LEAD` makes them sample that many periods ahead.

---

## 10. Toasts (`toast`)

Sources: S01 §8 (S01:420-423), App A (S01:512-514), App B (S01:537), BS:272, BS:770-774. The presenter is v6's toast window on `NanoD-carousel`, lifted out of the picker session into a **service** (A03 §5.3; A05 §7.2).

### 10.1 Placement and look

- **Where:** the stage of the monitor showing the foreground window at show time; centred horizontally, top **588** units (y 1176 px on the G93SC).
- **Pill:** padding 12 × 18 units, 15 px Archivo, one line, white, square corners, a 1 px `rgba(255,255,255,.2)` border (`max(1, round(k))` px).
- **Glass:** `blur.toast` (§12), a snapshot taken at show time with the toast window excluded. With no capture within 150 ms (`TOAST_CAPTURE_TIMEOUT_S`, CA:209), the tint alone at alpha 0.88 (CR:99).
- **Text fit:** v6 deviation 8 is kept: fitted to the 900-unit column, keeping the `{App} · ` prefix (CR:1316-1336; S5-22).

### 10.2 Motion (App A)

| Phase | Property: from → to | ms | Delay | Curve |
|---|---|---|---|---|
| In | translateY +8 → 0 and opacity 0 → 1 | 260 | 0 | OUT |
| In | scale 0.96 → 1 | 420 | 0 | SPR |
| Out | opacity 1 → 0 (no movement) | 200 | 1800 after the show | IN (S5-5) |

- A toast is visible for 2000 ms in total.
- **Replacement** while a toast shows: the text swaps at once and the 1800 ms hold restarts (BS:770-774), with no new entry motion. The pill's new width takes a fresh glass capture (the toast window is excluded while it runs). Until the capture arrives, the pill keeps its old glass, stretched to the new width.

### 10.3 API

`toast(text, exit=False)`, called from the Tk thread; K3 decides the text and when.

- `exit=True` marks a toast caused by closing an overlay. It shows at `max(t_close + 360 ms, t_request)`, where `t_close` is the close trigger (S01:422; BS:771).

### 10.4 Suppression

- A toast with `exit=False` requested while any overlay is registered open (§2.4) is **dropped**, not queued (S01:422).
- Opening an overlay ends any visible toast at once (BS:1025, :1050).
- Toasts are **dropped while `SHQueryUserNotificationState` returns 3 or 4** (a full-screen D3D app, or presentation mode), the states the floating knob already honours (OV:105; S5-17).
- There is no toast for Play/Pause or Back. That is K3's policy; the presenter doesn't need to know.

---

## 11. The floating knob (`knob`)

Sources: user decision (it mirrors the ring with the same choreography at the display refresh); S02 r2 overrides (six glow looks); R:105; AL §10.3; FK; RF0 §2.4; RF1 C1/C2; AR-7, AR-9, AR-22.

### 11.1 What stays from v5

The window recipe (0x080800A8: click-through, never activates), placement (the primary monitor's `rcWork` left edge + 24 logical px, vertically centred), size (a ring 360 logical px across), the slide (220 ms in, 260 ms out, `ptSrc.x` plus constant alpha), the touch and `HIDE_SECONDS = 2.5` rules, peek, the Knob Face geometry (segments 4 × 10 design px centred at radius 138; plate 154; disc 126), the LCD mirror through `render_lcd` at the overlay's scale, the suppression mechanism and the metrics (FK §2, §4, §9). The floating knob has **no button LEDs** (FK §2: no button strip; K2 M30); the six looks apply to the ring. It has **no tooltip, legend or any text of its own** beyond the LCD mirror: it is click-through (`HTTRANSPARENT`, §3), so hover text could never show, and no desktop legend strings exist in v7 (VOC-R24; K3 C5-7).

### 11.2 The engine on the overlay thread (C1)

- `AliveLights` (AL §4) runs on `NanoD-overlay`.
- **Inputs:** `detent`, `limit`, `press` and the local position arrive through the fast path (§5.3) with their QPC stamps. Decorated frames, `clock`, `progress` and the `reducedMotion` flag arrive from Tk, newest wins. `render(now)` is called with `now` = the frame's `t_target` in uint32 ms (P12).
- Knobs without `alive` keep `PreviewLights`, driven the same way (AL §10.3).
- **While hidden** (the overlay state is `hidden`, for any reason including suppression, §17.1) **and the knob is connected**: no frame loop and no timer. The engine **renders once per posted message**, a Tk frame or a fast-path input, as that message is handled, with `now` = **that message's QPC stamp** in uint32 ms (the serial-read time for a fast-path input, the post time for a Tk frame; P12), never earlier than the previous render's `now`. There is **no compose and no present**. So feedback `seq`s and the frame-derived events (MODE, PLAY/PAUSE, EXT) are consumed when they arrive, exactly when the physical ring plays them, and a stale moment (a Like bloom, a sweep, a scatter) never plays when the knob slides in (K2 §10.3 item 2, M27; this supersedes AL:425's "does not render"). The overlay thread otherwise blocks in `GetMessageW` (FK §4). AL's effect-queue cap of 8 (AL D12) still applies but is rarely reached, because the queue drains at each message.
- **Catch-up (K2 M27).** The engine clamps `dt` at 50 ms (AL §4), so one render after a long gap would leave its damped levels, colours and tint behind the physical ring's. So **before each hidden render, and before the first render after the overlay leaves `hidden`**, the overlay calls `render` at `last + 50`, `last + 100`, … up to the new `now` with the **previous** frame and no new input (the new frame and inputs go only into the final render at `now`), at most **60** steps: a gap longer than 3000 ms first renders once at `now − 3000`, then steps. It needs no engine change, keeps every effect exact (they are functions of `now`), and costs ≤ 60 × 0.17 ≈ **10 ms per message**, on the overlay thread and outside any frame path; each render costs 0.06–0.17 ms (RF0 §2.4).
- **At slide-in** the catch-up above runs first, then the first visible frame is sampled at its `t_target` as usual (§11.4).

### 11.3 Drawing the ring

For each segment i, `e_i` = the engine's tone-mapped output (floats 0..1, AL §4) and `mx = max(e_i)`.

| Part | Rule | Source |
|---|---|---|
| Body | the v5 segment mask, filled with `rgb(36 + 219·e)` per channel; so unlit is `#242424` (v5 used `#1F1F1F`) | AL:418; BS:678; S5-19 |
| Glow look | when `mx > 0.01`: `j = argmin abs(GLL_j − mx)` over `GLL = [0.14, 0.30, 0.45, 0.62, 0.81, 1.00]`; ties go to the lower j (BS's strict `<`). The look is picked from the **rendered** level every frame, not from the target | S02 r2; BS:479-481, :677; VOC §3.3 |
| Glow shape | `GLB = [6, 8, 10, 12, 15, 18]` are **BS canvas px** of `shadowBlur` (the only drawing that uses them: BS's ring, outer diameter 2 × (152 + 7) = **318** BS px, BS:671, :677-679). **The unit and scale are K2's** (K2 §10.3 item 3): physical radius = GLB × **S_glow**, with `S_glow = (the ring's outer diameter in physical px) / 318 = 360 × DPI/96 / 318` = **1.1321** here, so the radii are 6.79, 9.06, 11.32, 13.58, 16.98 and 20.38 px and **σ = radius / 2** = 3.40, 4.53, 5.66, 6.79, 8.49 and 10.19 px. The segment, plate and disc masks keep KnobFace design px × `S_face = 360/286 × DPI/96` (1.2587 here, KFC:195-200); only the glow radii use S_glow | S02 r2 ("at 1× floating-knob size", which names no unit); K2 §10.3 item 3; BS:479-481, :671-679 |
| Glow alpha | fixed per look: `0.95 × GLL_j` | BS:677 |
| Glow colour | `e / mx` (the normalised colour, × 255) | BS:677; AL:419 |
| Order | plate → glows → bodies → disc and LCD (the disc clips the glow, as in v5) | FK §2 |

- **Look sprites:** 60 segments × 6 looks = 360 pre-rotated masks, each the segment shape blurred with that look's σ at the physical scale, with the look's alpha baked in. They are built on the overlay thread while hidden, at startup and on a DPI change: ≤ 100 ms (AR-7 measured 63 ms for 4 shapes and 75 ms for 16) and about 2–3 MB.
- **Window box unchanged:** the largest look reaches 3σ = 30.6 physical px = 24.3 design px past the ring's outer edge (143 + 24.3 = 167.3 design px from the centre), inside the 172 design px that the plate shadow already needs (`FACE_EXTENT`, KFC:185-186).
- The golden and unit tests for the looks use S_glow (the same numbers as K2 §11 item 5, "radii scaled by diameter/318").
- Looks are only **tinted and faded, never reshaped per frame** (S02 r2). They replace AL §10.3's continuous `(5 + 13·mx)·k` blur and v5's 4 shapes × 64 alpha steps (KFC:182-191; S5-18).

### 11.4 Composing a frame (C2) and when to compose

- **Straight into the DIB:** the left half of the double-width DIB is mapped as a premultiplied RGBX PIL image (`frombuffer` with a row stride of 2W × 4 bytes).
  1. Copy the cached "under" layer (plate + shadow) rows in.
  2. Paste each lit segment's solid glow colour through its look mask, then its body colour through the body mask. `paste(colour, box, mask)` into RGBX is an exact premultiplied "over" (RF1 C2).
  3. Paste the cached disc + LCD sprite (straight colour, with its alpha as the mask).
- **No `alpha_composite`, no per-frame `Image.new`, no BGRa conversion, no per-row `memmove`** (AR-5; RF1 C2).
- **Frame rate:** **every vblank while the knob is visible**, paced per §5. The breath is continuous, so this means always while visible (user decision). **While hidden: no loop, no timer, no compose, no present**; only the per-message engine render of §11.2, with its catch-up (K2 M27).
- **Test** (headless gate H9, §6.6; K2 §11 item 5): a fake backend counts, while hidden, exactly one engine render per posted message plus its catch-up steps (≤ 60), and zero composes and presents; a feedback `seq` posted while hidden does not play at the next slide-in; the first visible `e` matches a continuously rendered twin within 0.02. **[erratum R-i]** After a summon by a message, the first visible frame equals the M27 reference instead, and the twin comparison applies from +300 ms of visible frames (H9; 21.4 E-i).
- **Skip unchanged frames (AR-22):** a frame key = the 8-bit body fill, the look index and the 8-bit glow tint of every segment (K2 §10.3 item 2) + the LCD identity + the slide `ptSrc.x` and alpha. When the key is unchanged, neither compose nor present.
- **Budget:** **≤ 2.5 ms p95** at 100 % (P6; the §6.3 "Knob ring" gate, the only one, K2 §10.3 item 5) (RF1 measured 1.43–1.92 ms before C2).
- **Slide:** unchanged, one ULW per vblank with the same frame bytes (RF1 C3).

### 11.5 The LCD mirror

Unchanged: Tk renders `render_lcd` at `lcd_px` when the LCD key changes, and submits it (FK §4). New rule for WP1: at `scale > 1`, `render_lcd` must not call `alpha_composite` on areas over 64 K px while the overlay is visible; use masked pastes (LP:892; AR-5). The byte-identity rule at scale 1 (FK §3) is unaffected, because the floating knob never draws at scale 1. LCD transitions (slides, fades) stay instant on the desktop; animating them is the optional RF0 step 4.

### 11.6 Suppression, reduced motion, metrics

- Suppression reasons are in §17. A `limit` event summons the knob like any touch (AL §10.3).
- **Reduced motion:** no slide. The knob appears and disappears with a 200 ms constant-alpha fade in place (`ptSrc.x` fixed at 0) (S5-16). The engine gets the same `reducedMotion` flag as the physical knob (VOC-R09; K2).
- `overlay.metrics()` adds the FrameStats of §6.2 (`frames.knob`) and `looks_build_ms`.

---

## 12. Blur recipes (App B S01:528-538, implemented)

All radii are CSS `blur()` standard deviations in units, so σ = radius × k physical px, and σ = radius × k / reduce at the reduced scale (`glass_sigma`, CR:286-294; CAR §3 erratum). Saturation uses the Rec.709 matrix (`_saturate_matrix`, CR:301). The tint is folded into the same pass (`_tint_matrix`, CR:305). Every recipe is **fixed per surface, taken from a snapshot at open (or at show), and never animated** (R:112-115).

| Recipe (VOC §7.1) | Source | Reduce | σ at the reduced scale (k = 2) | Saturate | Tint (folded) | Surface (G93SC) | Extra |
|---|---|---|---|---|---|---|---|
| `blur.explorer` | desktop snapshot at open | 8 | 36·k/8 = **9** | 1.3 | `rgba(8,8,10,0.50)` | 640 × 180 opaque, ×8 | ambient: see below, opacity **0.50** |
| `blur.upnext` | desktop snapshot at open | 8 | **9** | 1.3 | `rgba(8,8,10,0.55)` | 640 × 180, ×8 | ambient opacity **0.45** |
| `blur.picker_frost` | desktop snapshot at open | 8 | 40·k/8 = **10** | **1.6** | `rgba(10,10,12,0.50)`, **no dim** | v6 glass window, `rcMonitor`, bilinear upscale on the capture thread | no sheen (S01:371) |
| `blur.picker_none` | — | — | — | — | flat `rgba(0,0,0,0.55)` | v6 dim window | label text shadow `0 1px 2px /0.6` |
| `blur.toast` | desktop snapshot at show | 4 | 24·k/4 = **12** | 1 | `rgba(24,24,26,0.62)` + 1 px `rgba(255,255,255,.2)` border | pill-sized | fallback tint at 0.88 alpha |

- **Ambient layer** (explorer and Up next): source = the focused cover's **64 px** copy, downsampled from any cached rung (RA §4.1), or `art_bg` as a solid while nothing is cached.
  - Build at 1/8 of the bleed box: the monitor plus 160 units on every side (BS:126), i.e. (5120 + 640) / 8 × (1440 + 640) / 8 = **720 × 260**.
  - Cover-fit the square source to it (720 × 720, then the centre 260 rows, as CSS `center / cover`), `GaussianBlur` σ = 90·k/8 = **22.5**, saturate **1.5**.
  - Placed at offset −320, −320 px, scaled ×8. The build costs ≈ 3–5 ms on a worker.
- **Why 1/8 is enough:** a heavy blur has no fine detail. At 1/8 with the GPU's LINEAR upscale, the error is mean 0.18–0.22, p99.9 2–3, max 3–6 in 8-bit levels, against a full-resolution blur costing 144 ms (RF0 §2.0). G1 check P5 confirms LINEAR on screen (AR-8).
- **Capture failure or timeout** (500 ms): the frost is the tint alone over a neutral `#0E0E10` base, still opaque, so the stage never shows the live desktop through a tint that was meant for a blur (S5-30).
- App B's last row, "Small-art mat", means the **Extended sleeve** (VOC-R20; CH r2.1). It is not a blur recipe: see §13.6.

---

## 13. Artwork pipeline

### 13.1 Requests

The ladder is 240, 600, 1200 (and 2000 only if k > 3.5). Request the smallest rung ≥ need ÷ 1.1, capped at `art_max`. Never 3000. `MAX_DOWNLOAD` stays 2 MiB, `MAX_PIXELS` 16 M, and the allowlist is unchanged (`*.mzstatic.com` over https; Sonos `/getaa` on a literal private IPv4 at port 1400) (AW:48-97; RA §4.1).

| Element | Need at k = 2 | Request | Fallback | Source |
|---|---|---|---|---|
| Explorer L0 (centre, `\|d\| ≤ 2` + 1 ahead) | 680 (762 during the Play grow, transient) | **1200** | `art_max` 600 → ≤ 1.5× upscale (1.13×); smaller → `art.extended` | RA §4.1; S01:280 |
| Explorer L1 (the whole preload window) | 340 | **600** | as above | RA §4.1 |
| Mosaic tile | 340 | **600** per tile album | a tile album without art is skipped (§13.6) | S01:301-304 |
| Up next big cover (focused row ± 1) | 760 | **1200**; a non-catalog row: Sonos `/getaa` (≈ 400) | 400 → `art.extended` at 600 px | S01:282; LC:13 |
| Up next row lead | 112 | **240**; non-catalog: `/getaa` | — | S01:283; RA §4.1 |
| Ambient | 64 | none: derived from any cached rung | `art_bg` solid | RA §4.1 |
| Knob (artwork2 240 px) and floating-knob hi-res (480) | 240 | the **240** rung (Sonos-only rows: `/getaa` 400, downscaled); sizes unchanged (AW:52, :57; ARTWORK2). What each knob `artKey` shows (the r2.1 scrim composite, the 240 px `art.loading` / `art.generated` / `art.extended` covers without text) is **K3 §10.5**, built by **WP6**, which owns `artwork.py` (K3 C5-58; K1 §8.4) | — | K3 §10.5 |

The user's library currently tops out at 1200 × 1200 (all 96 Recently Added albums, 227 of 239 playlists, LC:15-16), so 1200 requests hit the originals.

### 13.2 What each item must carry (K3 / WP6 → presenter)

| Field | Type | Meaning |
|---|---|---|
| `art_template` | str | the Apple artwork template (`{w}x{h}` placeholders; others rejected, AW:110-135) |
| `art_max` | int px | `min(artwork.width, artwork.height)` |
| `art_bg` | int `0xRRGGBB` or 0 | Apple `bgColor` |
| `art_ink` | int or 0 | Apple `textColor1` |
| `sonos_art` | str or "" | the `/getaa` URL, for rows without an Apple song |
| `mosaic` | list of ≤ 4 art descriptors | playlists: the first 4 **distinct albums with art**, in track order (§13.6) |
| `title`, `artist` | str | for the Generated and loading sleeves |

These item keys are VOC addition **VOC-K4-03** (absorbed into VOC §7.1; K3 C5-57 fills them). RA §4.5 proposed `art_template`, `art_max`, `art_bg`.

### 13.3 Caches

| Cache | Holds | Key | Budget | Lifetime |
|---|---|---|---|---|
| C1 encoded rungs | the fetched JPEG bytes | sha1(template) + rung, or sha1(`/getaa` URL) | **24 MB** LRU | session (RA §4.2) |
| C2 prepared sprites | L0, L1, 760 and 112 sprites, including sleeves, as JPEG q 92 (a 680 px decode ≈ 1 ms) | (image key, kind, k) | **32 MB** LRU | session |
| C3 disk (optional, §22 Q7) | C1 content | sha256 file names under `%LOCALAPPDATA%\DeskDial\cache\art\` (**[rename]** the Desk Dial home, VOC-R32), never URLs | 96 MB LRU, ≤ 164 days | persistent |
| GPU surfaces | uploaded sprites | as C2 | the preload window + an LRU of 64 cover pairs | while the device is warm |

- No decoded bitmaps are kept apart from what is on the GPU: decoded at fetch size, 40 covers would be 288 MB (RA §4.2).
- URLs are never logged (AW:3-5).

### 13.4 The build pipeline (on `NanoD-art-1` and `NanoD-art-2`)

1. **Order:** `|d|` from the focus ascending, the direction of travel first. Jobs for items that left the window are cancelled; newest wins.
2. **Fetch** through AW's `_fetch` (its bounds, allowlist and cancellation, AW:484-512) into C1.
3. **Decode:** `Image.open`; when the target is ≤ ½ of the source, `draft("RGB", target)` for JPEG DCT scaling; then `reduce(n)` to at most 2× the target; then LANCZOS to the target. Centre-crop non-square sources (`ImageOps.fit`, AW:434; RA §1.3).
4. **Compose the art state** when needed (§13.6), with masked pastes only.
5. **Encode** into C2, then post premultiplied BGRA bytes to the stage thread, which uploads them within its per-wake budget (§4.5).

- **Budgets (AR-6):** first build of a 1200 source → L0 + L1 ≤ **20 ms** on one worker (17.7 ms measured for decode + LANCZOS; L1 from L0 by `reduce(2)`, 0.3 ms). From C2: ≤ **2 ms**. Upload: 0.3 ms of CPU, 0.5 ms until the GPU is done (RF2 §2.4).
- **GIL:** workers follow §4.7.3.
- **Dominant colour** for the Extended sleeve: `dominant_rgb` on a 24 × 24 sample of the decoded cover (AW:193), computed on the worker. The ring colours themselves are K3's (VOC §3.5).

### 13.5 Upscale rule

With `u` = need ÷ source edge (RA §4.3):
- `u ≤ 1.5`: LANCZOS, drawn as `art.full`;
- `u > 1.5`: `art.extended`.

### 13.6 Art states (VOC §7.1 ids)

| Id | Recipe (at the element's size) | Source |
|---|---|---|
| `art.full` | the cover, LANCZOS to size | S01:280 |
| `art.extended` | base `shade(c, 0.30)`; a radial gradient `120% 120% at 50% 38%`: `shade(c, .95)` at 0 %, `shade(c, .5)` at 52 %, `shade(c, .2)` at 100 %, with c = the cover's dominant colour and `shade(c, x) = round(c·x)` per channel. The cover drawn **sharp at 1.5 × its native size**, centred, inset `(need − 1.5·src) / (2·need)` (400 px on a 680 card: 6 %; 300 px: 17 %; Sonos 400 on the 760 cover: 10.5 %), with a fixed shadow `0 18px 40px rgba(0,0,0,.4)` and a 1 px inset at 14 % white. No blur | S01:286-290; BS:540, :544; CH r2.1 |
| `art.generated` | a 160° linear gradient from `g0` to `g1` of `GEN[h mod 8]`; title in Archivo 800 at 34/37, −0.02 em, flush left, at most 4 lines, at left/right 26 and top 24 (explorer card) or 38/41 at 28/26 (Up next cover); artist 16/20 500 at 0.80; a 2 px rule at 0.50 plus a 28 px two-note glyph at 0.70 at bottom 26 (the explorer card only); all in `ink`. The ring uses `accent` (K3); the ambient and the knob LCD use the gradient | S01:291-295; BS:155-164, :218-224, :536-537 |
| `art.loading` | a solid `art_bg`; title 17/21 600 and artist 13/17 500 at 0.75 in `art_ink`, at left/right 22 and bottom 20, gap 4. When `art_bg` is 0 (Sonos, non-Apple rows): `#232325` with `#F2F2F2` ink (S5-11). The real cover fades in over 240 ms OUT when it is ready | S01:296-299; BS:165-170 |
| `art.list_loading` | `#232325`, no text | S01:300 |
| `art.mosaic` | 2 × 2 tiles (TL, TR, BL, BR) of the first 4 distinct albums **with art**, in track order, each 170 units, composed once into one sprite | S01:302; BS:1177 |
| `art.single` | fewer than 4 distinct albums with art: the first one, full bleed. None with art: `art.generated` from the playlist title (S5-12) | S01:303 |

- **GEN palette** (BS:536): `[g0, g1, ink, accent]` =
  `#2B3A55, #131A28, #F3F2F2, (70,120,255)` · `#5A2E24, #26130F, #F6EBE4, (255,100,60)` · `#2F4A3A, #15231B, #ECF4EE, (60,220,120)` · `#4B3B63, #1F182C, #F1EEF6, (150,100,255)` · `#6B5A2A, #2C2410, #F7F1DF, (255,190,40)` · `#2A4F57, #112326, #E9F4F5, (40,210,230)` · `#5C2A3F, #28111B, #F6E9EF, (255,60,140)` · `#3D3D3D, #171717, #F3F2F2, (255,190,105)`.
- **Hash `h`** (BS:537), ported exactly: `x = 7`; for each **code point** of `title + "|" + artist`, add its first UTF-16 code unit (the code point itself below U+10000, else the high surrogate `0xD800 + ((cp − 0x10000) >> 10)`), as `x = (x·31 + unit) mod 9973`; `h = x mod 8`. This matches JS `for…of` + `charCodeAt(0)`; a golden test holds BS-computed samples (§6.6 H8). The same album always gets the same sleeve.
- **Which playlists get a mosaic** is §22 Q1.

---

## 14. Memory budget

| Item | Where | Size (G93SC, k = 2) | Lifetime |
|---|---|---|---|
| D3D11 + DComp devices | process private (driver) | **+53.5 MB** (RF2 §2.3) | first knob touch → 600 s without a scene |
| Stage capture | `NanoD-stage-capture` | 29.5 MB (5120 × 1440 × 4), freed right after `reduce(8)` | ≈ 50 ms per open |
| Frost and ambient builds | workers / stage | ≈ 0.5 + 2 × 0.75 MB | per scene |
| Text sprites (CPU side) | workers | ≤ 1.3 MB each (the explorer label is 1800 × 176 px) until uploaded | transient |
| C1 + C2 art caches | process | ≤ 24 + 32 MB | session |
| GPU surfaces | VRAM | covers 2.31 MB per L0 + L1 pair; ≤ 29 in the preload window, 64 in the LRU → ≤ 148 MB; Up next ≈ 25 MB | device warm |
| Picker (v6 + the v7 band) | process | peak ≤ 80 MB while open (CAR §5), with the chrome at 14.5 MB instead of 11.1 MB | while open |
| Floating knob | process | DIB 1.6 MB + look masks ≤ 3 MB + face | always |

**Guards** (S2, measured against the v6 baseline of the same session):
- private bytes, device warm and nothing open: ≤ **+80 MB** (RF0 §4.2);
- private bytes at the peak of an open: ≤ **+130 MB**; back to the warm level within 1 s of close;
- after the device is released: ≤ +60 MB (caches only);
- stage VRAM (`IDXGIAdapter3::QueryVideoMemoryInfo`, local segment): ≤ **256 MB**;
- dwm.exe commit: after a close within +16 MB of before the open (CAR:279).

---

## 15. Overlay lifetime (VOC §7.3)

| Reason | Detected by | `explorer` / `upnext` | `picker` | Knob (K3) | U12 one-side completion |
|---|---|---|---|---|---|
| `back` | K3 (Button 1) | animated close, 340 ms | v6 cancel + 280 ms exit | parent | **applied** |
| `hold` | K3 (`kh`) | animated close | as `back` | `home` | **applied** |
| `play` | K3 (Button 4 or the click action) | Play motion, close at 380 ms | — | `home` | — |
| `switch` | K3 | — | activate first, 280 ms exit | `home` | — |
| `pair` | K3 at 820 ms | — | raise, focus the last-snapped side, exit | `home` | — |
| `lock` | stage host: `WM_WTSSESSION_CHANGE` → `system(lock)`. For the picker also: on a lost foreground, the adapter calls `OpenInputDesktop`; if it fails or `GetUserObjectInformationW(UOI_NAME)` isn't `Default`, the close is `lock`, not `focus_lost` | **instant** | instant | parent | **applied** (VOC-R15) |
| `sleep` | stage host: `PBT_APMSUSPEND`, or display off (`GUID_CONSOLE_DISPLAY_STATE` = 0) | instant | instant | parent | applied |
| `idle` | K3: 60 s without knob input | instant | instant | parent | applied |
| `disconnect` | runtime | instant | instant | no host mode; knob-local (VOC-R23): `Waiting for PC` **only after a lost host** (lease expiry); the native screen after an intentional release or a power-up (K1 §8.10, P5-11); LEDs offline after any release (K2 §8.1) | not applied |
| `focus_lost` | WN WinEvent (v6) | — | v6 passive exit | `home` | not applied |
| `group`, `foreground`, `source` | K3 / runtime; `foreground` from the WN WinEvent hook routed to the stage adapter | instant | — | parent (`source` → `tracks`) | — |
| **`display`** (VOC-K4-01) | stage host `system(display)`; picker EV_DISPLAY | instant | instant | parent | not applied |
| **`device`** (VOC-K4-01) | stage device lost (§4.3) | instant | — | parent | — |

- **Instant** = hidden in the same presenter wake, with no fade and no toast (S01:426; S5-26).
- For the picker, `complete_one_side` runs after the hide on `NanoD-snap`. Focus is not restored while the session is locked or asleep.
- Exit toasts follow §10.3.

---

## 16. Reduced motion (S01 §10; VOC-R09)

- **Source:** the Settings key `motion` = `system` (the default: Windows *Animation effects*, `SPI_GETCLIENTAREAANIMATION` = 0x1042, re-read on `WM_SETTINGCHANGE`) \| `full` \| `reduced`.
- Each presenter latches the effective value at open (`reduced_motion` in the open payload, §2.3). The floating knob follows it live.

| Surface | Under reduced motion | Kept |
|---|---|---|
| Explorer, Up next | cards and rows **jump** to their slots; every card and row opacity change takes **200 ms OUT**; no enter offsets, no stagger, no end bump, **no Play grow** (the others fade over 200 ms and the root closes at 380 ms); the tab underline and the marker jump; the heart fades over 200 ms with no pop | the root fades (340 ms); the ambient crossfade (600 ms); the big-cover crossfade (420 ms); label and text fades (160 ms), including the explorer's state block; tab label opacity (240 ms); loading → cover (240 ms); the shuffle-line crossfade |
| Picker | cards jump, opacities 200 ms OUT; **no fly** (the slot fills with its 260 ms fade and the real window still moves at 360 ms); the tray **fades only** (260 ms, no spring); the group shift and the marker jump; no end bump | the root fade; the frame and shadow crossfades; the label fade |
| Toast | no translate, no scale | opacity in 260 ms OUT, out 200 ms IN |
| Floating knob | no slide: a 200 ms alpha fade in place | the LED choreography, per K2's reduced-motion rules |

BS sources for the picker, explorer and Up next: BS:1143, :1184, :1208 (`rm ? 'opacity 200ms'`), :1082 (no fly), :1397 (marker), :1399 (tray), :1413 (toast). The floating-knob fade and the heart and Play rules are S5-16.

---

## 17. Suppression rules

### 17.1 The floating knob (`overlay.set_suppressed(reason, on)`, VOC §7.2)

| Reason | Held while | Status |
|---|---|---|
| `disconnected` | the knob is disconnected | existing |
| `picker` | a rect-less (Tk) picker overlaps the knob, Windows mode only | existing (legacy path) |
| `carousel` | the picker is open, from its show handshake to the end of its exit, either background | existing (CAR §11) |
| **`explorer`** | from `explorer_open` to its `closed` event | **new** |
| **`upnext`** | from `upnext_open` to its `closed` event | **new** |
| (a check, not a reason) | `SHQueryUserNotificationState` is 3 or 4 at a slide-in | existing |

While any reason holds, touches do not slide the knob in; it comes back by its normal touch rules afterwards (FK §4). So **no Python frame loop runs while the explorer or Up next is open**.

### 17.2 Toasts
§10.4.

### 17.3 Overlays
One at a time (§2.4). They open whatever the notification state, because the user asked for them (S5-17).

### 17.4 Capture
Every snapshot excludes our own visible windows (§2.6).

---

## 18. The 32:9 rule (S01 §11)

| Rule | Implementation |
|---|---|
| Scale by height | k per §0.3; physical px = units × k (×2 here) |
| Full-width layers | the frost, tint, ambient and the No-background dim cover `rcMonitor` (§12; §9.2), with the §4.4 overdraw |
| The 16:9 stage | tabs, labels, dots, hints, the Up next column and list, the snap tray and the toast sit in the centred 1280 × 720-unit stage |
| Carousels extend | on wide monitors the explorer and picker use their 32:9 tables; cards run past the stage and are clipped only at the monitor edge (§7.2, §9.3); no visible card is below 0.40 |
| Up next stays in the stage | the frost and ambient fill the sides (§8) |
| Snap halves | halves of the picker monitor's `rcWork`: 2560 × 1392 px each here (§9.6) |
| Preload | ±12 on wide monitors, ±6 on 16:9, + 4 in the direction of travel (§7.7) |

---

## 19. The G1 spike: prove compositor-run 240 Hz before the music scenes are built

**Purpose.** Settle the rendering approach on the user's screen with numbers before WP8 writes `scene_music.py` (00 G1 as redirected by RF0 §5 step 2; 00 §4.3 critical path). It replaces 00 G1's thumbnail-sprite spike.

**Needs the user's go-ahead**, like the v6 spike. It shows full-screen windows on the user's monitor for about 15 minutes of their time. It does **not** touch the knob, any serial port, Sonos, Apple Music or any of the user's windows (no window is moved), and it does not run or install the companion. It is a standalone script in a scratch folder, `stage-spike\spike_stage.py`, run with the project venv (`.venv\Scripts\python.exe -I`). Its artwork is the prototype's own covers (`HO\prototypes\assets\covers`, repeated to 24 items as r2.1 does, CH r2.1).

**Safety:** every phase ends by itself within 60 s; a watchdog ends the script after 5 min; the global hotkey **Ctrl+Alt+F12** (`RegisterHotKey`) aborts at once. The windows are non-activating, so they cannot take the keyboard. The script creates windows only on the primary monitor and restores nothing, because it changes nothing.

### 19.1 Phases

| Phase | What runs | Recorded | Pass |
|---|---|---|---|
| **P0 (headless; no go-ahead needed)** | Vtable slot tests for every §4.7.1 method; the curve-fit gate (H3); `PYFUNCTYPE` setters under a busy thread; `GetProcAddress` for `DCompositionWaitForCompositorClock`, `…BoostCompositorClock`, `…GetFrameId`, `…GetStatistics`, `…GetTargetStatistics`; `GetFrameStatistics().timeFrequency` against `QueryPerformanceFrequency`; the sprite build bench (1200 → 680 / 340 with and without `draft`); **the picker compose bench on the 32:9 table** (§22 Q2); device memory | JSON | all slots S_OK; fit ≤ bound; a 33-call setter push ≤ 0.05 ms p95 under contention (RF2 §2.3: 0.031); all five APIs present; `timeFrequency` = the QPC frequency |
| **P1 Input contract** | The host shown full-monitor over the user's own desktop with a translucent test tree. The **user** clicks the centre, clicks elsewhere, turns the wheel and presses Shift once | `GetForegroundWindow` before and after each; the click-action count; `SHQueryUserNotificationState` before, during and after; whether the taskbar is covered and restored | the foreground is unchanged throughout; exactly 1 click action; the wheel eaten; the taskbar restored |
| **P2 Capture exclusion** | `BitBlt` with `WDA_EXCLUDEFROMCAPTURE` on the shown host, against a capture taken before showing | byte difference, excluding the clock region | identical (the v6 p7 method, RF2 §8 item 2) |
| **P3 Explorer tree, 32:9** | frost (1/8, ×8) + ambient A/B + 17 cards (L0/L1, shadows, shade, inset) + label, tabs, dots, hints. Scripted: 20 detents at 10/s, 1 s rest, 20 at 20/s, 10 reversals at 20/s, a source switch ×2, Play grow and close. 3 runs | §6.2 episode fields from target statistics; per-detent wake → `Commit`; commit round trip | §6.3 explorer row: ≥ 0.979 × rate, p95 ≤ 1.1 P, max ≤ 2.02 P; ≤ 1.5 ms per detent |
| **P4 Up next tree** | rows (9, text sprites + 112 px art), big cover A/B, plate, the heart spring; the same detents; the shuffle fade and re-entry | as P3 | as P3 |
| **P5 Visual quality (the user judges)** | A/B toggles on a slow turn: LINEAR against NEAREST; SOFT against HARD; one cover level against L0/L1 (shimmer at a = 1–7 on detailed covers); Up next rows with and without the sharpen pass; frost at 1/8 against 1/4; LAYER against MULTIPLY on a fading card | the user's verdict per toggle | LINEAR + SOFT + LAYER look right; L0/L1 shows no shimmer (otherwise add the 408 px level); sharpen on/off decided |
| **P6 Retarget continuity** | 50 reversals at 20/s at peak speed; a 240 fps phone video is optional | the user's verdict; H7 re-run on the real device | no visible jump or hitch at a reversal |
| **P7 Begin-time unit** | a 1 s linear ramp with its absolute begin set 500 ms ahead in QPC ticks; the first frame in which it moves is found through target statistics and a `WaitForCommitCompletion` probe | the start error | the ramp starts at the QPC begin ± 1 P; otherwise the §4.6.5 item 7 fallback |
| **P8 Stress** | P3 again with a pure-Python burst thread (10 ms every 25 ms) **and** an `alpha_composite` worker on 2560 × 1440 | as P3 | **the same fps thresholds**; wake → `Commit` ≤ 2 P p95 (GIL waits allowed, motion unaffected) |
| **P9 Statistics history** | walking frame ids after 250, 500 and 1000 ms without harvesting | the oldest frame id still answered | ≥ 64 frames of history (so the 250 ms harvest is safe); otherwise harvest at 100 ms |
| **P10 Environment** | P3's first run repeated with a 60 fps video playing in a foreground window; boost on and off. The user reports whether NVIDIA G-SYNC windowed mode is on (they toggle it only if they want to) | `rateRefresh`, `rate_hz`; a visible flash on open (OLED VRR gamma, AR-11) | fps unaffected by the video; no flash; the settings recorded |
| **P11 Memory** | the device warm, a scene open, after close, after the device is released | private bytes; dwm.exe commit before and after; `QueryVideoMemoryInfo` | the §14 guards |

**Optional**, with the user's OK to download: PresentMon during P3, for dwm.exe's display cadence as an independent check (AR-13).

### 19.2 What the result decides

| Outcome | Decision |
|---|---|
| Everything passes | WP8 builds the explorer and Up next on the stage exactly as §7–§8 say |
| P3 or P4 miss 240 but hold ≥ 0.49 × rate | U10 (b): gate the music scenes at 120 for v7, then find the cause (DWM load, VRR) with PresentMon |
| P1 fails (the foreground changes) | switch the host to a layered click-through window (`WS_EX_LAYERED \| WS_EX_TRANSPARENT` with the DirectComposition target, AR-4 option a), accept click-through, and re-run P1 |
| P5 shimmer at a = 1 | add the 408 px level (§7.3) |
| P5 LAYER too costly (fps drop only with LAYER) | card containers use MULTIPLY with the shadow clipped out of the cover rect (a 9-slice shadow sprite) |
| P7 fails | the §4.6.5 item 7 fallback |
| P0 picker bench fails on the 32:9 table | §22 Q2's recommended path |

### 19.3 Output

`stage-spike\results_g1.json` (all phases) plus a plain-language summary. K5 (`ACCEPTANCE.md`, WP9) records the outcome. Nothing is left changed on the machine.

---

## 20. Amendments to CAROUSEL.md, FLOATING_KNOB.md and APP_ICON.md

This contract binds them now. WP7 (CAROUSEL), WP10 (FLOATING_KNOB, APP_ICON) and WP9 (docs) copy the text into those files as their v7 sections. Until then, this section wins where they disagree.

### 20.1 CAROUSEL.md §12 (desktop v7)

1. **Scope:** the picker v2 of §9, on the v6 window stack (S5-2). The CAR §1 focus contract, §6 labels, §7 icons and §8 text are unchanged.
2. **Superseded:**
   - §2 layout: 480 × 300 at (640, 300) and the 320/460/560/620 table become §9.3 (400 × 250, two tables, the group shift);
   - §2 selected card: the 6 px outline becomes the frame layer; interpolated shadows become a crossfade of two fixed layers (**deviation 11 retired**);
   - §2 badge 32 / 14 becomes 30 / 12; dots 22-wide selected, 60 %, radius 3, shadow become fixed 0.40 squares plus a marker;
   - §2 label: top 476 and 28/34 become 512 / 468 and 26/32; description 88 % becomes 86 %;
   - §3 / §11 Frosted recipe: saturate 1.8, tint (18,18,20,.58), 12 % dim become `blur.picker_frost` (S5-21);
   - §3 No background: the card shadows and the second text shadow become §9.3's (S5-20);
   - §4 open: the in-place fade becomes the rise on open (§9.8); §4 Switch: the 1.35 grow is removed (S5-6); §4 Cancel: the red Cancel and `Cancelled · focus restored` become warm Back with no toast (R:152);
   - §4 end bump: **deviation 4 retired**; it is also driven by the knob's `lim`;
   - §4 pacing: DwmFlush with the fast-flush heuristic becomes §5 P2–P5;
   - §5 host: pane-sized becomes `rcMonitor` (it eats clicks everywhere); chrome: pane + margin becomes the band (§9.2);
   - §5 / deviation 8 toast: moves to the toast service (§10); position top 320 becomes 588; hold 1.5 s becomes 1.8 s; tint (30,30,32,.55) becomes (24,24,26,.62). The text-fit rule is kept.
3. **New:** the snap tray, fly, placement and closes (§9.4–§9.7); the registration rule (§9.3); B1–B5 (§9.9); FrameStats (§6.2); reduced motion (§16).
4. **Tests:** CAR §10's list plus H1, H4, H8, the snap state machine with a fake placement, and S3. The fake native layer also asserts that snap code reaches a target window only through `ShowWindowAsync` and `SetWindowPos` with `SWP_ASYNCWINDOWPOS` (never `SetWindowPlacement`, `ShowWindow`, a synchronous `SetWindowPos`, `SW_RESTORE` or `SW_MAXIMIZE`), and that a stalled fake resolves as `move_rejected` at the 800 ms deadline (600 ms for `complete_one_side`), by the worker or by the backstop, with the latched close run once.

### 20.2 FLOATING_KNOB.md §10 (desktop v7)

1. §4 "Frame rate: at most one submit per UI tick (25 ms)" is **superseded**: the ring renders on the overlay thread at every vblank while visible (§11.4), fed by the fast path (§5.3).
2. §2 glow ("alpha ≤ 0.7·level", 4 shapes) is **superseded** by the six looks (§11.3), and the unlit colour by `#242424` (S5-19).
3. §4 slide pacing: `DwmFlush` + the 8 ms fallback becomes §5 P3–P5.
4. §4 suppression gains `explorer` and `upnext` (§17.1).
5. New: C2 compose (§11.4), skipping unchanged frames, the reduced-motion fade (§11.6), FrameStats `frames.knob`.
6. For K2 to carry into ALIVE (read-only here): AL:419's `(5 + 13·mx)·k` glow and AL:423-425's "up to 60 fps" are superseded on the desktop by §11.3 and §11.4 (S5-18), and AL:425's "does not render while hidden" by the per-message render of K2 §10.3 item 2 (M27), which §11.2 adopts. K2 r2 already carries all three.

### 20.3 APP_ICON.md (tray theme)

The taskbar theme follows `WM_SETTINGCHANGE` with `"ImmersiveColorSet"`, handled on pystray's window (`handlers[0x001A]`, which only calls `put('theme')`), with a 30 s poll as a backstop instead of today's 2 s (00 §3.2 "Tray"; A05 §8). No asset changes.

---

## 21. Register

### 21.1 Deviations from r2.1 (S5-n, type D)

| Id | r2.1 says | This contract does | Reason |
|---|---|---|---|
| **S5-1** (= VOC-D01) | "`SW_RESTORE` first if maximized" (R:176; S01:403) | Never `SW_RESTORE`. Restore without activating with `ShowWindowAsync(SW_SHOWNOACTIVATE)` only (not `SetWindowPlacement` or `ShowWindow`, which wait on the target's thread), then `SetWindowPos` with `SWP_ASYNCWINDOWPOS`, frame compensation and verification, under an 800 ms deadline (§9.6) | `SW_RESTORE` activates the target and the picker dismisses itself (00 C24; A05 §6.4). A synchronous call on a busy target would block `NanoD-snap`, and with it K3's latched Back/hold (MS-11, MS-12, MS-13) |
| **S5-2** (= VOC-D05) | the companion's three overlays are built on DirectComposition (R:42) | the explorer and Up next are on the stage; the picker keeps its v6 host with pacing and compose fixes; its chrome moves to the GPU later (RF0 step 3) | DirectComposition cannot animate a DWM thumbnail; the focus contract needs the activatable host; lower risk (RF2 §4a) |
| **S5-3** | clicking a side card or row selects it; clicking the centre plays (BS:1186, :1218) | only the centre card or focused row acts (as Button 4); other clicks are eaten | a click that selects would desync the knob's absolute position (CAR dev 5; 00 §3.2) |
| **S5-4** | the snap fly casts `0 30px 70px rgba(0,0,0,.45)` (BS:120) | ~~no fly shadow in v7~~ **[errata]** no fly shadow on the step-1 (CPU) chrome only, the fallback; the step-3 GPU chrome, v7's picker since R-h and wired in the app on 2026-09-26, draws it (§9.10; 21.4 E-h, 21.5 E-s) | the fly leaves the chrome band on 32:9; drawing the shadow would need a monitor-sized CPU chrome upload per frame (29.5 MB), which breaks the 120 gate. It returns with the GPU chrome (RF0 step 3) |
| **S5-32** | "Failures: … Nothing moves" (S01:412) | A snap or one-side completion that fails on a window that **was maximized** leaves it **restored at its own normal rect**, not maximized again (§9.6 step 7). Normal and minimized windows are put back exactly as they were | every maximize command activates the window (`SW_SHOWMAXIMIZED` = `SW_MAXIMIZE` = 3, MS-14), which would dismiss the open picker or, after the close, take the foreground from the window the picker handed it back to; `SetWindowPlacement` with that command also waits on the target. Rare: it needs a maximized target that passes the pre-checks and then refuses the move, can't fit a half, or misses the deadline |

### 21.2 Rulings (S5-n, type R: between sources, or where r2.1 is silent)

| Id | Ruling | Basis |
|---|---|---|
| **S5-5** | Where App A and BS differ, App A wins: card shades 320 ms **OUT** on both carousels (BS `ease`); toast exit **opacity only**, 200 ms IN (BS reverses the entry); Up next shuffle exit **opacity only**, 160 ms IN (BS also moves the rows +40); explorer tabs change **at the press** (BS at 190 ms); explorer Play grow **380 ms** (BS 420); explorer source-switch label fade-out 160 ms OUT; picker card entry opacity **420 ms** (BS 300) | R:123 (App A is the motion list); S01:472-514 |
| **S5-6** | Switch has **no 1.35 grow**; activation stays first (CAR dev 3) | not in App A; r2.1 BS closes plainly (BS:1092-1097); S04 r2 keeps only "card treatment" |
| **S5-7** | Up next Play: the focused row grows to 1.06 (420 ms OUT); the left column does not scale | BS:1206, :1410; App A silent |
| **S5-8** | Where App A is silent, BS values are used, `ease` included: tray slot border 260 EASE, empty glyph 200 EASE, slot badge 260 EASE, picker cards group 220 EASE, shuffle line 240 EASE, focus plate 320 OUT, picker end bump 12 px | R:123; BS:62-114, :235, :241 |
| **S5-9** | Dots: at most 82 in the stage; longer lists show an 82-dot window with fading end dots | r2.1 silent; Recently Added can hold hundreds of items (U5; LC:15) |
| **S5-10** | A source switch replaces the dot row and the marker at +190 ms with no marker slide | BS slides the marker across a row whose count just changed (BS:194) |
| **S5-11** | Loading without Apple `bgColor` (Sonos and non-Apple rows): `#232325` with `#F2F2F2` ink. The loading list fills the table slots around the focus, clamped when the count is known | r2.1 silent |
| **S5-12** | Mosaic tiles take the first 4 distinct albums **with art**; with none, a Generated sleeve from the playlist title | r2.1 silent; 11 of the user's playlists have no art (LC:16) |
| **S5-13** | Snap `cant_fit`: place, verify, and put the window back (§9.6 step 7), so nothing moves; the one exception is a formerly maximized window (S5-32) | S01:412 "Nothing moves" outranks A05 §6.4 step 6 ("leave it placed") |
| **S5-14** | Real-window placement runs on a `NanoD-snap` worker, with only posted calls on the target and a hard deadline (t0 + 800 ms; 600 ms for `complete_one_side`) plus a carousel-side backstop | its waits (≤ 150 ms restore, ≤ 400 ms verify) must not block Tk or the frame loop; A05 §6.4 put it on Tk. The deadline bounds K3's latched Back/hold (C5-12, ≤ 800 ms), ahead of K3's own 1000 ms last-resort `snap_result_timeout_ms` |
| **S5-15** | The stage's open fade starts only once the frost is built (≤ 500 ms timeout) | a group-faded root that includes the frost would otherwise show the frost popping in; v6 fades its separate glass window instead |
| **S5-16** | Reduced motion where r2.1 is silent: the floating knob fades in place for 200 ms; the heart fades without a pop; no Play grow; the tab underline, marker and picker group shift jump; the toast is opacity-only | S01 §10 ("jump with fades") applied to the remaining motions |
| **S5-17** | Overlays open whatever the notification state; toasts are dropped when `SHQueryUserNotificationState` is 3 or 4 | the overlays are user-initiated and r2.1 designs no refusal; 00 G9's "don't open over full screen" is not adopted |
| **S5-18** | The floating knob renders at every vblank (the user's decision) with the six looks; AL §10.3's 60 fps cap and continuous glow do not apply on the desktop | the user's decision; S02 r2; AR-7 |
| **S5-19** | Floating-knob segment fill `36 + 219·e` (unlit `#242424`) | AL:418; BS:678 |
| **S5-20** | Picker No background uses the same card shadows as Frosted and one label text shadow (`0 1px 2px /0.6`) | r2.1 BS:85-86; App B S01:536 (a change from CAR §3) |
| **S5-21** | Picker frost: σ 40·k/8, saturate 1.6, tint (10,10,12,.50), no dim, no sheen | App B S01:535 (a change from CAR §11) |
| **S5-22** | Toast text fit: v6 deviation 8's 900-unit column with the `{App} · ` prefix kept | r2.1 silent on long text |
| **S5-23** | The wheel over the stage is eaten; keys stay with the foreground app | r2.1's wheel is a prototype control (R:37); the explorer and Up next never take focus (S01:234, :322); AR-4 |
| **S5-24** | A label swaps once its prefetched sprite exists (≤ one render, ≈ 7 ms late in the worst case) | RF1 B1; "text changes at rest" is met within a frame or two |
| **S5-25** | The stage device is created at the first knob touch and released after 600 s without a scene | AR-19 |
| **S5-26** | Explorer and Up next close **instantly** for every reason not caused by a user action (lock, sleep, idle, disconnect, group, foreground, source, display, device); animated for back, hold and play | S01:426 ("close instantly") extended to the additions |
| **S5-27** | The Up next sharpen pass is on by default | AR-17; confirmed or dropped at G1 P5 |
| **S5-28** | Covers in two levels (L0 at 340·k and L1 at 170·k), crossfaded on the 420 ms turn curve | AR-8: no mipmaps; R:122 "no image below about 40 % of its prepared size" |
| **S5-29** | A turn during the explorer's open stagger retargets the table properties while the rise (30·S_open units) and the enter scale run on | CSS transform-list interpolation, approximated to sub-pixel |
| **S5-30** | The stage frost without a capture is the tint over an opaque `#0E0E10` base, not a translucent tint over the live desktop | a translucent tint would show moving windows sharply behind the explorer; v6's picker fallback (CR:127) is unchanged |
| **S5-31** | **App A's `ms` for a two-leg tuple is per leg**, as BS runs it. The heart (S01:495): 0.4 → 1.5 over 380 ms SPR, held, then from +420 ms 1.5 → 1 over 380 ms SPR (≈ 800 ms in all), with the opacity 0 → 1 over 200 ms OUT at 0. The end bumps (S01:480, :497; picker S5-8): 0 → ∓14 (∓12 on the picker) over 160 ms OUT, then from +160 ms back to 0 over 160 ms OUT (320 ms in all). ~~**Unlike**, which App A does not list, follows BS too:~~ (**[r2.2]** withdrawn with the unlike itself, R22 CH §1; kept for history:) opacity 1 → 0 over 200 ms OUT from 0, scale → 1.5 over 380 ms SPR from 0, then → 0.4 over 380 ms SPR from +420 ms (already invisible). Under reduced motion none of this plays (S5-16) | App A gives one duration for a from → via → to tuple and does not say whether it covers one leg or both; S01:344 repeats "spring 380 ms" without settling it. BS, the only running version, is a 380 ms CSS transition per target change with the target flipped to `scale(1.5)` at the press and back at 420 ms (BS:255 transition, :827-828 `likePop` set and cleared at 420 ms, :1216 `heartTf`), and a 160 ms transition per bump leg with the reset at +160 ms (BS:778 `bump()`, :82, :143, :242 transitions; :1394, :1401, :1407 offsets). Fitting both legs into 380 ms would need a split of the SPR curve that no source defines. So this reads App A's tuple, applied to each target change, not a departure from it |
| **S5-33** | Explorer states r2.1 does not draw (Recently Added `empty`, `signin` on either tab, `error`) reuse the empty-favourites block: its geometry and type, the active tab's own glyph, and K3's copy ids (proposed ones where K3 has only knob copy, VOC-K4-04). A state change while the explorer is open reuses the source-switch tuples: the outgoing cards exit (170 ms IN) or the outgoing block fades (160 ms OUT), and the incoming block fades in, or the incoming cards enter with the open stagger, at +190 ms | r2.1 draws only the empty-favourites block (S01:311-313; BS:183-189), which BS shows instantly because its state only changes from the state picker; K3 defines the other states and their copy (K3 §5.2.3, §5.3.4, §15.3), and the explorer can open on a Recently Added list that is still loading or empty (K3 §3.1: Open is dimmed only for `signin_expired` and `list_error`). Reusing designed geometry and App A tuples (S01:473-475, :484) avoids undesigned visuals and glyphs |
| **S5-34** **[r2.2]** | **Row hearts: four looks, non-catalog included.** Liked filled `#FF285A`; not liked outline at 45 %; not known yet dashed (2.2 / 2.4) at 30 %; not in Apple Music outline at 15 % with no Like; no unlike animation; hint `[3] Liked` | R22 CH §1 is the authoritative list, and R22 BS draws exactly this (`ghostOp` 0.15 / 0.3 / 0.45, `dash '2.2 2.4'`, BS:1223); R22 S01 §6's older line "They have no heart; Like is dimmed" for non-catalog rows is superseded by its own r2.2 table ("outline at 15 %; no Like") and the changelog |

### 21.3 VOC additions proposed by K4

| Id | Addition | Where | Why | Status (consistency pass) |
|---|---|---|---|---|
| **VOC-K4-01** | overlay close reasons **`display`** (monitor configuration or DPI change while open) and **`device`** (the stage device was lost). Instant, no toast, knob to the parent mode, no one-side completion | VOC §7.3 | §4.3; §15 | **absorbed**: VOC §7.3 rows `display`, `device`; VOC-R15, VOC-R22; K3 §13.1 (C5-55) |
| **VOC-K4-02** | `refused(surface, reason)` with reason ∈ `busy` \| `device`. K3 maps both to the Head shake and a meta line; the copy `knob.meta.stage_unavailable` = `Can’t open on screen` joins VOC §9.5's approval pass (**[r2.2]** approved as **`Couldn’t open on screen`**, R22 CH §2, VOC-R29) | VOC §7.4, §9.5 | §2.4; §4.2 | **absorbed**: VOC §7.4, §9.5, VOC-R22; K3 §13.5, §15.3 |
| **VOC-K4-03** | item art keys `art_template`, `art_max`, `art_bg`, `art_ink`, `sonos_art`, `mosaic` (host-internal, not wire) | VOC §8 | §13.2; RA §4.5 | **absorbed**: VOC §7.1 "Item art keys"; K3 C5-57 |
| **VOC-K4-04** | overlay copy for the explorer's state block (§7.4): `overlay.explorer.recent_empty_title` = `Nothing recently added` (the text of K3's `knob.title.recent_empty`), `overlay.explorer.recent_empty_help` = `Add an album or a playlist to your library in the Music app.`, `overlay.explorer.error_title` = `Library not loaded` (the text of `knob.title.library_error`), `overlay.explorer.error_help` = `Go Home, then Browse to retry.` (overlay copy, no knob limit; the knob's own sub-line is now `Home, then Browse`, K1 OQ-6); all four proposed for VOC §9.5's approval pass (**[r2.2]** approved, R22 CH §2). K3's proposed `overlay.explorer.signin_title` / `.signin_help` (K3 §15.3) are used on **both** tabs, not only favourites | VOC §9 (overlay copy), §9.5 | §7.4; S5-33 | **absorbed**: VOC §9.5; K3 §15.3 |

### 21.4 [errata] Errata and accepted build deviations of the phase-2b gate (lead rulings, 2026-09-26)

Recorded from the phase-2b build and gate reports (WP7b-picker, WP8 with its fix round, WP10-1); nothing was shown on screen. Lead rulings R-h (the picker's step 3) and R-k (the explorer's 32:9 per-detent work) are build work of their own packages ~~and are not recorded here~~. **[errata]** R-h's step 3 is §9.10 (WP7c); its effect on this section's rows is E-h (WP7b-D7). R-k is named in WP8-D2. K3's phase-3 build makes WP7b-D6 a fallback (E-c).

**Errata.**

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| E-i | **R-i** (WP10-1) | §6.6 H9: in the `like` and `started` cases and after a 10 s hidden spell, "the first visible `e` equals a twin rendered continuously at 60 Hz within 0.02", read as covering every summon | unchanged for those cases (their messages come before the summon). For a **summon by a message** (a detent or press whose input makes the knob visible, a Tk frame posted in the same tick as its touch, a feedback frame posted during the arm wait) the first visible frame equals the **M27 reference** exactly (K2 M27's own procedure run outside the overlay), and the comparison with the continuous 60 Hz twin (within 0.02) applies from **+300 ms** of visible frames. M27's 50 ms catch-up steps make that first frame lead the twin (0.268 for a detent that wakes the ring, 0.112 for a press, measured), a lead that fades to 0.0011 by +300 ms. §11.2's rule, the engine and the counts H9 checks are unchanged | §6.6 H9 and §11.4's Test bullet (both tagged **[erratum R-i]**), §11.2; K2 §11 item 5, M27 (ALIVE 12.6 E-i); `tests/test_cc_knob_face.py` `FloatingKnobAliveTests` (`reference`, `summoned`) |
| E-t | phase-2b gate item (WP8 fix round, WP8-R1) | §2.2 listed `NanoD-art-1` and `NanoD-art-2` only, and WP8-D1 had the timed scene actions ride 1 × 1 tick uploads on those two workers, where a cover fetch could hold them back | the **`NanoD-art-fast`** row of §2.2: a third art worker for the fast lane only (ticks, ambient builds, labels, row and column text, loading tiles, sharpen sprites, statics; plans), never network I/O, sharing the two art workers' CPU slots, so a tick lands within one fast-lane job (≤ ~7 ms) of its `not_before`. §13.4's heading ("on `NanoD-art-1` and `NanoD-art-2`") now reads: the cover jobs on those two, the rest on the fast lane, which they help when idle | §2.2, §13.4; `control_center/stage/scenes/art.py` `ArtService` (`LANE_ART`, `LANE_FAST`) |
| E-c | K3 **C5-78** ([P3]; phase-2b review item R8) | §2.3: `windows_cancel` adds `origin`, `home`, `complete`; WP7b-D6 accepted as a stopgap, the root fix "open work for K3 and the runtime" | `windows_cancel` also carries the close `reason` (`back` \| `hold` \| `lock` \| `sleep` \| `idle`), latched by K3's controller; the runtime passes it on as `cancel(origin, complete=, reason=)` (only the keywords the adapter takes). The picker's inference (WP7b-D6) stays as the fallback for a payload without one; §9.7 and §15's rules per reason are unchanged | §2.3, WP7b-D6 below; K3 §5.7.4, §9.9, C5-78; `control_center/runtime.py` (`windows_cancel`); `tests/test_cc5_windows_snap.py` `CancelReasonTests`, `tests/test_cc5_runtime.py` `CancelReasonPassThroughTests` |
| E-h | **R-h** (WP7c; §22 Q2) | §9.5: "No fly shadow in v7" (S5-4); WP7b-D7 accepted "as S5-4" for the whole picker | step 3 (§9.10) draws the fly's shadow on the GPU chrome, moving with the fly's translate and uniform scale; S5-4 and WP7b-D7 hold for the step-1 (CPU) chrome only, the fallback on device loss or with `NANOD_PICKER_CHROME=cpu` | §9.5, §9.10, S5-4, WP7b-D7 below; CAROUSEL.md §12.4; `control_center/stage/picker_chrome.py` (`picker.fly.shadow`); `tests/test_stage_picker.py` (`test_the_fly_casts_its_shadow_along_the_fly`) |

**Build deviations accepted (R-l).** WP7b-D1…D7 are the picker build's (listed in CAROUSEL.md §12.3); WP8-D1…D9 are the music scenes' (the WP8 build report). Each is accepted as built.

| Id | As built | Departs from | Acceptance (R-l) |
|---|---|---|---|
| **WP7b-D1** | the plain-host fallback frost (CAROUSEL §5) covers the whole monitor, because the v7 host is `rcMonitor` (§2.1) | CAROUSEL §11 ("pane only", written for the v6 pane-sized host) | accepted |
| **WP7b-D2** | the picker's pacer and FrameStats (`LoopPacer`, `LoopStats`) are duplicated in `carousel.py` rather than imported from the stage package, which no module outside it may name (`tests/test_stage_static.py`); the behaviour follows §5 P2–P5 and §6.2 | §5, §6.2 (one pacing implementation) | accepted |
| **WP7b-D3** | after a verified-mismatch placement a window is `cant_fit` when it sits at the half's origin (±2 px) and is larger than the half (its minimum size won); any other mismatch is `move_rejected`; both are put back (S5-13, S5-32) | §9.6 step 7 (no rule to tell the two apart) | accepted |
| **WP7b-D4** | the picker presenter's exits never toast: `toast.switch`, `toast.snap.pair` and `toast.snap.one_side` come from K3 through `toast(text, exit=True)`, which the presenter defers to its exit end | §9.7, §10 | accepted |
| **WP7b-D5** | a display change, a suspend or `close()` during a pending snap resolves the job as `move_rejected` and ignores the worker's late answer; the window may still move once if its posted `SetWindowPos` was already queued | §9.6, §15 | accepted |
| **WP7b-D6** | the adapter infers the cancel `reason` when the runtime passes none: the lifetime reason it saw itself (lock, sleep), else `idle` after 59.5 s without a knob-driven call, else `back` | §9.7, §15 (the close reason is K3's) | ~~accepted as a **stopgap**; the root fix (a `reason` in K3's `windows_cancel`, passed on by the runtime) stays open work for K3 and the runtime~~ **[errata]** accepted as the fallback for a payload without `reason`; the root fix is built: K3's `windows_cancel` carries the close `reason` (K3 C5-78, [P3]) and the runtime passes it on as `cancel(origin, complete=, reason=)` (§2.3, E-c) |
| **WP7b-D7** | no fly shadow | = S5-4 | ~~accepted, as S5-4~~ **[errata]** accepted for the step-1 (CPU) fallback chrome; step 3 draws the fly's shadow (§9.10, S5-4 lifted; E-h) |
| **WP8-D1** | timed scene actions (the ambient's 200 ms and the big cover's 120 ms debounces, the 150 ms sharpen, the switch swap end) have no timer hook in the engine (no scene tick or `next_wake`), so they ride 1 × 1 tick uploads and fire from `uploads_ready`, up to about one upload wake late; since WP8-R1 the ticks run on `NanoD-art-fast` (E-t), never behind a fetch | §4.5, §7.5, §8.4, §8.6 (timed work) | accepted, in its WP8-R1 form |
| **WP8-D2** | the explorer at 32:9 makes about 499 COM calls per detent (Up next about 203); the floor is the builder's fixed calls per animation (WP7a's own probe: 487 calls at 1.43–1.52 ms), so the 1.5 ms margin is thin (explorer 32:9 warm p95 1.58–1.74 ms at the phase-2b gate, on a busy PC) | G1-4, §6.3, H5 | accepted as the measured state; R-k trims the COM work toward p95 ≤ 1.5 ms on the headless bench, and the S1 tours' pickup rate judges it on screen |
| **WP8-D3** | goldens at k = 0.4 (1024 × 288 and 512 × 288) plus two k = 2 crops of the Extended sleeve; no full 5120 × 1440 goldens (size); reviewed by eye at k = 1 | H4 | accepted |
| **WP8-D4** | the reference renderer approximates DirectComposition (bilinear affine, premultiplied over); gradients are compared within ±3 | H4, §4.8 | accepted |
| **WP8-D5** | the simulator's covers are drawn by `SimulatedCovers` in the art service, not in `simulation.py` | §13 (K3 §16, simulator fakes) | accepted |
| **WP8-D6** | the scenes use `scene_music.heart_state`, a copy of `apple_music.heart_state` pinned by an equivalence test, so the credentials module stays out of the stage's imports; they read `liked`, `likes_known` and `catalog` from the payload | §8.3 | accepted |
| **WP8-D7** | loading the fonts holds the GIL about 1–2 ms, once per worker per k (`ArtService.warm(k)` at the open's t = 0); steady-state holds stay ≤ 2 ms | §4.7.3 (≤ 1 ms per C call as the design target), G1-5 (≤ ~2 ms) | accepted: within G1-5, above §4.7.3's target once per open |
| **WP8-D8** | the open's prefetch looks up the monitor itself (`_default_monitor_for`); if the engine picks another monitor, the prefetched sprites are not used | §4.9, §7.7 | accepted |
| **WP8-D9** | `music_tours.py --run` was never run by the build (only `--dry-run` and `--hidden`) | §6.4, §6.5 S1 | accepted: tours E and U stay supervised checks with the user's go-ahead before release |

---

### 21.5 [errata] Lead decisions on the phase-3 gate (2026-09-26)

Recorded from the phase-3 build, review and gate reports (WP7c, WP8-trim, WP6-gil, K-errata) and the lead's decisions of 2026-09-26; nothing was shown on screen. §21.4's tables are unchanged.

**Errata.**

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| E-p | **lead** (WP6-gil) | §4.7.3: the parses unmeasured, starting values `catalog_songs` ≤ 50 and pages ≤ 25, full-queue reads deferred, a cached zone-group context | the H5 result and the caps applied: `catalog_songs` 50 ids per request, `resolve` / `playlist_meta` pages 50 (WP6-GIL-D1), no deferral and no cached context (WP6-GIL-D2); K3 §1.2 holds the table | §4.7.3; K3 §1.2, §9.6.1, §9.8.4, §9.8.7, §9.8.8, §19; `tests/test_cc_gil_parse.py` |
| E-s | **lead** (R-h, WP7c) | §6.3: "Picker (W), step 3 (chrome on the GPU, later)"; §21.1 S5-4: "no fly shadow in v7" | the step-3 row is v7's picker row, gated headlessly by `picker_selftest` (normal frames ≤ 1.5 ms p95, detent frames ≤ 3.0 ms at 32:9) and on screen by `picker_snap_checks.py --chrome gpu` (supervised); the step-1 row stays the fallback's. S5-4 holds for the step-1 chrome only | §6.3, §9.10, §21.1 S5-4; CAROUSEL.md §12.4 |
| E-w | **lead** (WP7c-D11) | §9.10: "the one wiring point, `standalone.py`, installs the factory", not yet done; no knob touch reached the picker | wired: `standalone.main` calls `install_picker_chrome()` once, right before ControlCenterApp builds the WindowsAdapter (never raises; a failure leaves the CPU chrome); `ui.FastPath` calls `WindowsAdapter.note_touch()` wherever it calls the stage's `note_touch()`, with the same limiter (once per 10 s). The reader thread only posts `WM_APP_WARM` (measured ≤ 0.16 ms per touch); the device is made on `NanoD-chrome-warm` and adopted on `NanoD-carousel`, adding no GIL wait above the idle baseline. At startup the carousel thread now also prewarms the shared segment tables (pure Python in 2 ms idle steps, as the stage thread does, WP7a-R4): measured headlessly in fresh processes, the stage alone kept a 0.5 ms-sleeping probe waiting up to 3.6–5.5 ms for about 0.33 s, the picker alone up to 2.6–2.9 ms for about 0.9 s, and both together up to 4.6–7.5 ms for about 0.41 s (the tables are shared, so the work is not doubled); this happens once, while ControlCenterApp is still being built and before the knob can connect, so no overlay takes input then (G1-5). `picker_selftest` checks the wiring (`picker.wired_in_the_app`) | §9.10, §4.2; `standalone.py`, `control_center/ui.py`; `tests/test_cc_tray.py` (`StartupCleanupTests`), `tests/test_standalone.py` (`PickerChromeWiringTests`), `tests/test_cc_ui.py` (`FastPathTests`), `tests/test_stage_picker.py` (`WiringTests`) |

**Build deviations accepted (lead, 2026-09-26).** WP7c-D1…D13 are the picker GPU chrome's (listed in CAROUSEL.md §12.4); WP8-D10 is the music scenes' (WP8-trim); KE-1…KE-4 are K-errata's.

| Id | As built | Departs from | Acceptance (lead) |
|---|---|---|---|
| **WP8-D10** | the explorer's 32:9 per-detent wake → `Commit` p95 ≤ 1.5 ms (headless) holds only on a quiet PC: DirectComposition's periodic Commit (about every 256 ms while animations run, 0.35–1.25 ms) lands in the p95, and 494 COM calls per detent is the builder's floor; the scene's own work (wake → the Commit call) stays ≤ 1.5 ms p95 in every run | §6.3 Explorer row, §6.6 H5 (G1-4) | accepted with the S1 pickup threshold: R-k is judged on screen by `music_tours.py --run` (tours E and U), a tour passing when **≥ 98 % of its known detents are picked up at t1 or t1 + P and none early** (`PICKUP_ON_TIME_MIN`), together with the headless scene work p95 ≤ 1.5 ms; R-k stays open until those supervised tours pass |
| **WP7c-D1…D13** | the chrome's own device (D1), the compositor-run mirror (D2), occlusion by clips (D3), two badge levels (D4), sprites a frame late (D5), the re-registration a frame after the detent (D6), sub-pixel chrome at k ≠ 2 (D7), the fly's shadow (D8), the clip slots outside `com.SLOTS` (D9), no FPS HUD on the picker (D10), off until wired (D11), a support switch, not a setting (D12), GIL-keeping thumbnail updates on both chromes (D13) | §9.10, §22 Q2, §4.2, §6.2, S5-4 | accepted as built (CAROUSEL.md §12.4); D11 is closed by E-w |
| **KE-1** | H9 corrected in the errata sections (21.4 E-i, K2 12.6) rather than in §6.6's row | §6.6 H9 | accepted; the row and §11.4's Test bullet were then tagged in place (review KE-R6) |
| **KE-2** | the WP3b acceptance recorded in K1 16.8 E-l, with K3 E-l4 pointing to it | 21.4 (R-l) | accepted |
| **KE-3** | K-errata left the rename rows of K1, K3 and K4 to the rename package | the rename plan (`rename-desk-dial.md` 6) | accepted; the rename package applied them (K1 16.8 E-r, VOC-R32) |
| **KE-4** | one read-only `python -I` run with a scratch folder as its working directory (nothing written outside a scratch folder) | the phase's working rule | accepted as recorded (a process slip, not a contract change) |

---

### 21.6 [proposed errata] The frame-drop fixes of 2026-09-26 (pending the user's acceptance)

The on-screen tours of 2026-09-26 (`diagnostics/music-tours-20260926-112320.json`, `picker-snap-checks-20260926-112429.json`, `stage-pacing-20260926-112125-onscreen.json`) found drops the bare engine does not have (1630 frames, 0 missed): uploads committed with the animations that reveal them, cold opens losing their leading vblanks, designed holds counted as missed frames, and the picker locked at 120 by single setup frames. The fixes (the `engine`, `device` and `surfaces` module docstrings, S1–S3; `carousel.LoopPacer`, P1) are built and tested headlessly; their review (2026-09-26) found that the text below them had no errata yet and that P1's first form could not lock at 60 Hz. These rows are **proposed**: they take effect when the user accepts them, and the on-screen re-run is judged against the amended text. Nothing was shown on screen.

| # | Proposed by | Was | Now (as built) | Where |
|---|---|---|---|---|
| E-S1 | the frame-drop fixes (S1) | §4.5: "Upload budget per stage wake: ≤ 4 ms. The rest waits for the next wake"; the scenes revealed what an upload wake landed with a Commit in the same wake (on screen those Commits took 4–8 ms: an upload-carrying Commit blocks until about two frames after the previous one), and an upload whose reveal made no call rode the next detent's Commit | one upload wake: ≤ 4 ms **and** ≤ 2.5 MB (`UPLOAD_BUDGET_BYTES`; the first item always goes), a context Flush after each upload, then the wake's own upload-carrying Commit at once (content only); upload wakes are paced two frames and 1 ms after the device's previous upload-carrying Commit (`UPLOAD_GAP_FRAMES`, `UPLOAD_GAP_MARGIN_S`), so that Commit never waits; a surface **ripens** 4 ms (`READY_S`, a frame) after its Commit, and only then enters the LRU and reaches the scene's reveal, whose Commit is bind-only (about 0.01–0.2 ms). §4.4's content-swap rule holds for the reveal (the swap and the animation that shows it share one batch); only the upload moved earlier. A key waiting, uploading or ripening counts as resident for the art planners (`UploadQueue.in_flight`; the review's nit: also while its upload and Commit run). Only the open's Commit carries uploads | §4.4, §4.5; `control_center/stage/surfaces.py` (`UploadQueue`), `engine.py`, `device.py`; `tests/test_stage_surfaces.py` (`UploadQueueTests`), `tests/test_stage_frame_drops.py` (`UploadDisciplineTests`) |
| E-S2 | the frame-drop fixes (S2) | §4.6.5 item 1 and G1-6: t1 = `nextEstimatedFrameTime`, plus P while it is under 1.5 ms away; "an adaptive margin may use only build CPU time, excluding GIL waits, and at most 1 P" | the open's batch (about 600 calls; its Commit carries the frost and the build's sprites: 1.4–5 ms to its return, 3.2–4.8 ms p50 on screen) keeps a margin of **one P**, G1-6's bound, rather than a measured build time, counted from when its upload-carrying Commit can return (two frames and 1 ms after the device's previous upload Commit: `not_before`); the device pays its first upload-carrying Commit at creation (`prime`, about 10 ms that a cold open's Commit used to carry). Every other batch keeps the fixed 1.5 ms rule, and no EWMA exists | §4.6.5 item 1, [G1] G1-6; `control_center/stage/engine.py` (`StageCore.t1`, `_open_not_before`), `clock.py` (`adaptive_margin`); `tests/test_stage_frame_drops.py` (`OpenTests`) |
| E-S3 | the frame-drop fixes (S3) | §6.2: `missed` = intervals over 1.5 P, `double_missed` over 2.5 P, frames ÷ duration; §6.3's judge read those raw fields, so the heart pop's designed 40 ms hold (§4.6.4) failed an Up next episode that dropped nothing (184 of 192 frames on screen) | each stage episode keeps its batches' motion spans; `frames.ChangeModel` says, for a vblank without a presented frame, whether anything changed there; the record adds `holds` and the `*_in_motion` fields (§6.2), and §6.3's judge (`frames.judge_stage`, `basis` "in_motion") reads those, as its column heading "Displayed frames/s in motion" already says; the raw fields keep §6.2's meaning; a frame lost while something moves is still missed | §6.2, §6.3; `control_center/stage/frames.py` (`ChangeModel`, `episode_from_frames`, `judge_stage`), `engine.py`; `tests/test_stage_frame_drops.py` (`HoldTests`) |
| E-P1 | the frame-drop fixes (P1) and their review | §5.1 P5 for the carousel's loop: lock when the work p95 over the last 0.5 s exceeds 0.8 P (P1's first form added: only once the window holds 60 frames) | one-off frames (an open's setup, the frost's upload, the chrome's warm-up adoption) count nowhere; the GPU chrome's detent frames feed P2's estimate only; the lock engages only once the loop has run **0.25 s** since its last idle pause (a pause over max(0.1 s, 6 P) starts a new run and empties the window) and at least **two** frames of the window are over 0.8 P. The 60-frame minimum is withdrawn (at most 31 frames fit the window at 60 Hz, 40 at 240 Hz with work over 2 P). The release rule is unchanged. The picker's FrameStats add `locked_frames`, `paced_frames`, `rereg_frames` and `rereg_ms` (§6.2) | §5.1 P5, §6.2; CAROUSEL.md §12.2, §12.5 (E-P1, E-P2); `control_center/carousel.py` (`LoopPacer`, `LoopStats`); `tests/test_carousel_machine.py` (`PacerTests`, `LoopStatsTests`), `tests/test_stage_frame_drops.py` (`PickerOneOffTests`) |

**Open item O-R1.** The thumbnails' re-registration still runs on animated frames (the frame after each detent's chrome sync, WP7c-D6). The morning's worst displayed picker episodes were snaps at exactly 2 P (interval p50 8.332 ms, max 3 P) with the session's pacer ending at cadence 2 after 17 switches: the P5 lock that E-P1 addresses, not registration. It stays open until the supervised `picker_snap_checks.py --run --chrome gpu` re-run attributes the gaps (CAROUSEL.md §12.5).

---

## 22. Open questions (each with a recommended answer)

| # | Question | Recommended answer |
|---|---|---|
| **Q1** | **Playlist art.** S01 §5 heads the mosaic rule "Playlists without their own art", but its own examples give Favorite Songs a mosaic and PAPER LANTERN Ep. 1 a single cover, and both have their own art (CF:134-135). Should favourited playlists always use the tracks-derived mosaic or single cover, or their own art when they have it? | **Always tracks-derived** (the examples, BS:1177, and 00 §3.2's ring colour from the first mosaic cover). A playlist's own art is used only when none of its tracks has art. It also avoids wide banners and off-`mzstatic` art (CF:175; LC:16). Needs one design nod |
| **Q2** | **The picker on 32:9 in v7.** The 32:9 table shows 9 cards, where the 16:9 table shows 5; the CPU chrome's shadow work grows about 1.4×, and 16:9 already needed B1–B4 to reach 5.1 ms (RF1 §5.2). Will step 1 hold a steady 120 on the user's monitor? | **Decide on G1 P0's headless bench of `compose_chrome` on the 32:9 table** (no go-ahead needed). If compose + present p95 exceeds 7.0 ms after B1–B5, make step 3 (the chrome as DirectComposition visuals on the stage device, thumbnails untouched, with the AR-12 alignment check) part of v7; it reuses §4 wholesale. Otherwise ship step 1 with the 120 lock |
| **Q3** | **An input fast path for the overlays.** Should the stage and the picker take `position` straight from the serial reader, instead of waiting for the controller's `*_highlight` behind the 25 ms Tk tick? | **Yes**, as §5.3 describes. K3 confirms it (K3 §11.1): in list modes `control_min` is 0, so `index = position − control_min` = the controller's index for the active `control_id`; a later controller `*_highlight` with a different index wins; positions of an older `control_id` are discarded. Without it, the latency criterion is measured from the controller's effect (§6.3) |
| **Q4** | **Keys while the explorer or Up next is open** go to the hidden foreground app: Esc or typing can act on an app the user can't see (AR-4). A low-level keyboard hook could swallow them | **Accept and document it; no hook.** r2.1 says these overlays never take focus; a global hook is invasive and risky. The knob's Back, the 600 ms hold and the 60 s idle close are the ways out |
| **Q5** | **PresentMon** (Intel, MIT-licensed) for the S1 and G1 on-screen proof of layered-window cadence: download it? | **Yes, for the supervised checks only**, never shipped, after the user's explicit OK. The fallback is a ≥ 960 fps camera burst |
| **Q6** | **NVIDIA G-SYNC windowed mode / VRR** may change DWM cadence behind our overlays and cause OLED gamma flicker on open (AR-11). Should the user change it? | **Record it at G1 P10; change nothing unless a flash is seen.** The companion boosts the compositor clock regardless |
| **Q7** | **A disk cache for artwork** (new persisted data under `%LOCALAPPDATA%`, 96 MB, hashed names, ≤ 164 days)? | **Yes**, for encoded rungs only. It makes re-opening the overlays instant and cuts CDN traffic. It is P2: v7 can ship without it if WP6 runs short |

---

## 23. Sources

**Design (r2.1):** R §1, §3, §7.1–§7.3, §8, §9 (R:37-42, :110-156, :176); CH §3, §7, r2.1 (CH:31-44, :109-117); S01 §1–§12 and App A/B (S01:234-538); S02 r2 overrides (S02:3-26); S03 r2 overrides; S04 r2 overrides (S04:3-13); BS:57-272 (markup), :474-546 (constants, `GEN`, `genOf`, `extGrad`, `artFor`), :591-596 (LED loop), :662-694 (knob glow), :770-798 (toast, `xfUpdate`, `blink`), :820-890 (like, Up next), :1023-1097 (explorer and picker actions), :1118-1229 (tables, cards, rows), :1383-1413 (bindings); HT:6-75.

**Analysis:** 00 §1.3 (G1, G2, G5, G9, G12, G16), §2 (C7, C9, C24, C25), §3.1 (U9–U12, U14), §3.2 "Overlays", "Data", "Tray", §4.1–§4.4; A03 §0–§5, §10; A05 §5–§7, §10; RA §3.3, §4.1–§4.5; CF:134-135, :175; LC:13-16; RF0 §2.0–§2.5, §3, §4, §5, §6.2 and AR-1…AR-22 (RF0:658-972); RF1 §2–§5; RF2 §2.1–§2.4, §4a, §7, §8.

**Existing contracts and code:** VOC (all sections); AL §4, §10.3 (read only); CAR §1–§11; FK §1–§9; AI; CA:104-199, :476-520, :686, :1772-1775; CR:60-127, :186-229, :286-380, :926-1053, :1253-1385; OV:80-107, :206-220, :1205-1218, :1645; KFC:175-225; AW:40-135, :193, :484-512; WN:124-131, :627-656; UI:99, :1229-1244, :1535; ST:4, :1751.

**Microsoft Learn** (read 2026-09-25):
- MS-1 `IDCompositionAnimation::AddCubic`: https://learn.microsoft.com/en-us/windows/win32/api/dcompanimation/nf-dcompanimation-idcompositionanimation-addcubic
- MS-2 DirectComposition animation: https://learn.microsoft.com/en-us/windows/win32/directcomp/animation
- MS-3 `IDCompositionAnimation::SetAbsoluteBeginTime`: https://learn.microsoft.com/en-us/windows/win32/api/dcompanimation/nf-dcompanimation-idcompositionanimation-setabsolutebegintime
- MS-4 Compositor clock: https://learn.microsoft.com/en-us/windows/win32/directcomp/compositor-clock/compositor-clock
- MS-5 `DCOMPOSITION_OPACITY_MODE`: https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ne-dcomptypes-dcomposition_opacity_mode
- MS-6 `DCOMPOSITION_BITMAP_INTERPOLATION_MODE`: https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ne-dcomptypes-dcomposition_bitmap_interpolation_mode
- MS-7 `DCOMPOSITION_BORDER_MODE`: https://learn.microsoft.com/en-us/windows/win32/api/dcomptypes/ne-dcomptypes-dcomposition_border_mode
- MS-8 `CreateTargetForHwnd`: https://learn.microsoft.com/en-us/windows/win32/api/dcomp/nf-dcomp-idcompositiondesktopdevice-createtargetforhwnd
- MS-9 `SetProcessInformation` (power throttling): https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation
- MS-10 `timeBeginPeriod`: https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod
- MS-11 `ShowWindowAsync` (posts a show-window event to the window's queue; for not waiting on a nonresponsive application): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindowasync
- MS-12 `SetWindowPos` (`SWP_ASYNCWINDOWPOS` 0x4000 posts the request to the owning thread so the caller doesn't block; bringing a window to the top needs foreground permission for the process that owns the window): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos
- MS-13 `IsHungAppWindow` (not responding = no `PeekMessage` within an internal timeout of 5 s, subject to change): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-ishungappwindow
- MS-14 `ShowWindow` (`SW_SHOWNORMAL` 1 and `SW_RESTORE` 9 activate; `SW_SHOWMAXIMIZED` = `SW_MAXIMIZE` 3 activates; `SW_SHOWNOACTIVATE` 4 and `SW_SHOWMINNOACTIVE` 7 do not): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindow

---

## [G1] Spike results (2026-09-25, on screen)

**Run.** The G1 spike ran on screen at 17:47 on 2026-09-25, with the user's go-ahead, with G-SYNC on for windowed and full-screen mode. It made three pacing passes and one witness pass, from source `56a89f35…db6e` in `work\spike_dcomp\`. The full report is `design-reference\ui-v2-analysis\g1-spike.md`, with the raw data in `diagnostics\g1-spike-onscreen-20260925-174737-*.json`.

**Scope.** The results cover "this G1 script at 240 Hz on this PC". The following remain open:
- tour E;
- P1 (clicks), P2, P4 and P5;
- P6 by eye;
- P9 on screen;
- P10 and P11.

Those run with the user's go-ahead before S1 accepts WP8, and §19.2's fallbacks still apply to them.

**Result.** Compositor-run motion is **proven** for the explorer-style card scene:
- **Frames:** 14,666 of 14,670 expected frames were displayed across 9 condition runs, with no step of 2 or more vblanks.
- **Load:** the result held with no load, with a pure-Python burst (10 ms every 25 ms), and with a C call holding the GIL (15 ms every 25 ms).
- **Witness:** W1 was visible and on clock in 810 of 810 samples, and W2 stayed on its curve through 50 reversals at 20/s.
- **AR-8:** LINEAR and SOFT are confirmed on screen pixels.

**Binding for WP7a and WP8.** Where these notes and an earlier section disagree, these notes win for WP7a and WP8.

1. **G1-1, statistics reads keep the GIL (amends §4.7.1).**
   - `DCompositionGetFrameId`, `DCompositionGetStatistics` and `DCompositionGetTargetStatistics` are called through `PYFUNCTYPE`. Under a busy thread, GIL-releasing calls took 24.8 ms to read 24 frames; `PYFUNCTYPE` took 0.05 ms.
   - `IDCompositionDevice::GetFrameStatistics` on the input path follows them, once the H5 bench confirms it.
2. **G1-2, compositor-clock wait fallback (amends §5.1 P3).** `DCompositionWaitForCompositorClock` returns `0xC01E0006` immediately while the display sleeps.
   - Any other return than a clock tick or a signalled handle means "no clock": wait one P on the high-resolution waitable timer.
   - If the display is off, stop the loop.
   - Never loop on the call unguarded.
3. **G1-3, count frames by counters and time, never by frame ids (amends §6.1, §6.2).**
   - Frame ids advance about 240/s on screen but about 4,300–4,800/s while the display sleeps, and DWM keeps only about 300.
   - Count displayed frames with the target statistics' running `presentCount` / `refreshCount`, each mapped to a vblank index from `completedStats.time`. It sits on the vblank grid (R = 1.000); `presentTime` does not.
   - Lost ids are "unknown", never "missed".
   - Harvest only while the display is on.
   - `DwmGetCompositionTimingInfo(NULL).cRefresh` advanced under once a second on screen, so it is not a per-frame `refresh_count`.
4. **G1-4, per-detent budget (§6.3 unchanged; the builder must meet it).**
   - Wake → `Commit` measured p95 1.54, 1.63 and 1.64 ms against the 1.5 ms gate, for 390–577 COM calls per detent at about 1.9 µs each.
   - The builder batches and cuts calls:
     - only visible elements whose target changed;
     - §4.6.2's 0.5 px bound, with cached segment tables;
     - one scale object for X and Y;
     - pooled objects only;
     - one `Commit` per event.
   - H5 gates it on the 32:9 table at 20 detents/s.
5. **G1-5, GIL holds (tightens §4.7.3).** While an overlay can take input, no thread holds the GIL for more than about 2 ms. §4.7.3's 1 ms per C call during episodes stays the design target.
   - **Evidence:** 15 ms holds left frames untouched but delayed detent wakes by up to 15.9 ms, and only 65–84 % of commits were measured done before t1.
   - **Heavy work:** anything that holds longer runs in a worker process, or in chunks under 1 ms. That covers large `alpha_composite`, whole-document JSON/XML parses, and PIL operations not on §4.7.3's GIL-releasing list.
   - **Input path:** keep the GIL through everything before `Commit`, including the statistics read, so `Commit` is its first GIL-releasing call.
6. **G1-6, t1 margin (confirms §4.6.5 item 1).**
   - Use the fixed rule: t1 = `nextEstimatedFrameTime`, plus P while it is under 1.5 ms away.
   - No EWMA of wake → `Commit`: under GIL holds the spike's grew to 14–17 ms. That pushed t1 4–5 frames out, and DWM picked up 3–18 % of detents before t1, so the card held its start value for 1–3 frames.
   - An adaptive margin may use only build CPU time, excluding GIL waits, and at most 1 P.
   - **[proposed erratum E-S2]** One exception, the open's batch: its margin is a fixed one P (this item's bound), not a measured build time, counted from when its upload-carrying Commit can return (§4.6.5 item 1, §21.6). Every other batch keeps the fixed 1.5 ms rule.
7. **G1-7, retarget method (confirms §4.6.3, §4.6.5).**
   - The start value is the twin's float64 value at t1, from the same fitted segments DWM runs. The new animation runs over the full duration with `SetAbsoluteBeginTime(t1)`.
   - Two animation objects per property, alternated; equal targets are skipped.
   - Measured: 293 of 294 detents were picked up at t1 (1 at t1 + P), and the largest float32 jump was 0.00048 px.
8. **G1-8, begin-time unit (settles P7 for this PC; amends §0.6).**
   - Begin times are on the QPC time base. QPC ticks and 100 ns cannot be told apart here, because QPF = `timeFrequency` = 10 MHz.
   - Always convert through `timeFrequency`.
   - Assert `timeFrequency == QueryPerformanceFrequency` at device creation, and use §4.6.5 item 7's fallback if they differ.
9. **G1-9, solid-colour surfaces (amends §4.5).**
   - The spike drew every card's shade from **one shared opaque surface at card size (680 px)**, not a stretched 1 × 1, because a stretched 1 px surface risks bleeding atlas neighbours under LINEAR sampling.
   - WP7a/WP8 do the same (one surface per colour and size class, about 1.8 MB at 680 px) until a pixel test shows the 1 × 1 stretch is clean. P5 decides by eye.
10. **G1-10, close the spike-to-contract gap before WP8 relies on it.**
    - The spike paced on a layered, click-through host (`0x082800A8`, §19.2's P1 fallback) and animated opacity through an `IDCompositionEffectGroup`.
    - WP7a's first supervised on-screen check repeats one normal pacing pass, with the witness, on §2.1's click-eating host (`0x08200088`) with `IDCompositionVisual3::SetOpacity`, or else adopts the spike's proven pair.


---

## 24. The r3 Navigator (`navigator`)

Sources: r3 handoff README §5 (Navigator), §4 (motion), §1.2 / §2.2 (content per state), §9 (tokens); the prototype `Knob IA Prototype.dc.html` L79–170 (markup) and L790–837 (logic); the design checklist `design-reference/r3-design-spec-checklist.md` NV-1…NV-24, MO-7…MO-9. Written 2026-09-29 with the build; nothing was shown on screen for it (headless renders and a never-shown native check only).

### 24.1 What it is and when it replaces the floating knob

- A compact liquid-glass card on the **primary monitor's left edge** that shows where the knob is (path row), what it controls (per-state content) and what buttons 1–4 do now (keys grid). It **replaces the floating knob** (§11) for an r3 knob: `runtime.presentation_level >= 6` (`navigator_model.applies`). A knob below presentation 6 keeps the floating knob, unchanged.
- While it stands in, `ui.ControlCenterApp._render_overlay` holds the floating knob with the suppression reason **`navigator`** (`overlay.SUPPRESS_NAVIGATOR`, §17.1) and draws no LCD scene for it; the knob's ALIVE engine still receives its frames.
- A Navigator that cannot start (no thread, no device) leaves every knob on the floating knob (`Navigator.available` False, `update()` returns False).

### 24.2 Files and threads

| Piece | Where | Thread |
|---|---|---|
| Content + visibility rules (pure) | `control_center/navigator_model.py` | Tk |
| Recently Added covers (bounded LRU over the explorer's art pipeline) | `control_center/stage/scenes/navigator_covers.py` | Tk (asks) / `NanoD-art-*` (fetch, decode) |
| Tk facade `Navigator` (never imports the stage) | `control_center/navigator.py` | Tk |
| Engine `NavigatorEngine`, Win32 loop `NavigatorThread`, backdrop `CaptureWorker` | `control_center/stage/scenes/navigator_engine.py` | **`NanoD-navigator`** / **`NanoD-navigator-capture`** |
| Scene (tree, sprites, motion) | `control_center/stage/scenes/navigator.py` | `NanoD-navigator` |
| Headless rig, reference renderer, design states, contact sheet | `control_center/stage/scenes/navigator_render.py` | tests / tools |
| Wiring | `standalone.py`, the one wiring point outside the stage package (WP8-R11): `_navigator_factory` builds the thread and the covers over `stage.art` and hands them to the facade; `start_navigator` after the stage, `close_navigator` in the `finally`; `ui.py` (`ControlCenterApp(navigator=)`, `_render_navigator`, `FastPath.navigator`, Settings row, capture exclusions) | Tk, reader |

`NanoD-navigator` follows §2.2's skeleton: PMv2 per thread, `ABOVE_NORMAL`, `PeekMessageW` then `MsgWaitForMultipleObjectsEx` on an auto-reset event with the engine's next wake; **no frame loop, no timer while idle** (wakes: a posted state, a turn, a backdrop result, the hide one frame after the slide-out, the 2 s backdrop refresh while shown, the 600 s device release).

### 24.3 The data: a read-only adapter

- The controller is never written. Each Tk tick, `Navigator.update(runtime, frame)` calls `navigator_model.read_snapshot(controller, frame)`: a dict of primitives copied from the controller's public state (`screen.mode/index`, `state`, `display_volume`, `lights` + `display_bri/display_kelvin/lights_display_on()`, `lights_mode`, `recent.items`, `screen.seek`) and from the decorated frame the tick already renders (title, meta + tone, buttons with `enabled`/`lit`, the `volume` reveal layout, `artKey`). `build_content(snapshot, pressed)` turns it into a frozen `NavContent`.
- Tracks rows ±2: the controller's read-only **`queue_titles(rows) -> {row: title}`** (the Tracks neighbour reads, the loaded Up next rows and the playing song); a row it does not know yet shows `—`.
- Covers: the playing cover (Home, Music, Seek) is the runtime's hi-res cover (`runtime.lcd_media(frame, hires=True)`), handed over once per `artKey`. **Recently Added** covers (the focus and ±2) come from `stage.scenes.navigator_covers.NavigatorCovers`: a bounded LRU (24 decoded covers at 120 units, ≈ 7 MB at k 2) fed by the explorer's own art pipeline — the item's art identity is `scene_music.cover_plan` (Apple `art_template` / `art_max` as the controller's list already carries them, else the Sonos `/getaa` URL, else the Generated sleeve), fetched as `LANE_ART` jobs on `NanoD-art-*` through `ArtService.fetch_decoded` → `artwork.CoverStore.fetch` (its allowlist, bounds, C1 cache, no credentials; URLs never logged), nearest first, newest wins (jobs that left the window and have not started are cancelled), a failed cover retried after 30 s. The Tk tick hands each landed image over once (the Tk side remembers 32, the scene keeps 24). Until a cover lands the item shows its accent tile; the art then **fades in over the tile in 240 ms** (a cover already in when the item appears shows at once). No new controller accessor was needed (`controller.recent.items` carries the art fields).
- Posting is newest-wins and only on change (content, visible, eligible, reduced motion); a PIL image is never mutated after hand-off.

### 24.4 Visibility (README §5; NV-2…NV-6)

| Rule | Implementation |
|---|---|
| Appears on any turn or press | `runtime.touch_seq` on the Tk tick; plus the fast path: `FastPath` calls `note_turn()` (position, limit) and `note_press(slot)` (button) from the reader thread; a turn shows an *eligible* Navigator at once (`post_touch`), the Tk tick confirms. Presses do not show it early (a press may open an overlay). |
| Auto-hides 4 s after the last input at Home and the space roots | `Visibility.visible`: `now − last_input < 4.0` for non-sticky content (launcher, Music, Lights in brightness mode) |
| Stays in Recently Added, Tracks (Seek), Scenes, temperature mode | `NavContent.sticky` |
| Hidden while a full-screen overlay is open | modes `explorer`, `upnext`, `windows` have no content; also `runtime.open_surfaces` and the carousel's open state |
| Hidden while the knob is away | `runtime.device_connected` |
| Settings: **Auto-hide** (default) / **Pinned** / **Off** | `settings.json` `navigator` = `auto` / `pinned` / `off`; Settings row "Navigator"; applied at once through `_apply_presentation` → `Navigator.set_mode` |
| Pressed key fills | the slot of the newest press, for 220 ms (`PRESS_FLASH_S`), crossfaded 120 ms |

### 24.5 Geometry (units; ×k physical px, k = `StageLayout(rcMonitor).k` = 2 on the G93SC)

- Host: a column at the monitor's left edge over the work area, `HOST_W = 20 + 250 + 75` units (the shadow's 3σ reach) × `rcWork` height; **click-through** (`ROLE_CLICK_THROUGH`, ex `0x082800A8`: layered + transparent + no redirection bitmap + no-activate + topmost + tool window, `WM_NCHITTEST` → `HTTRANSPARENT`), shown with `SetWindowPos(HWND_TOPMOST, …, SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW)`, hidden with `SW_HIDE` one frame after the slide-out ends. It never covers the whole monitor (fullscreen apps keep independent flip).
- Card: left 20, **width 250**, height = content, **vertically centred in `rcWork`**, padding 16, gap 14, **radius 26**. Heights follow the prototype's flex: `16 + path (11 × 1.088) + 14 + content + 14 + keys 53 (+ 10 + 14 hold line) + 16`; content = now 64 + 12 + 21.97; lights 166.1; covers 196 + 10 + 54; rows / scenes 190 + 10 + 15; seek 44 + 10 + 40 + 10 + 4.

### 24.6 Liquid glass (NV-8…NV-12)

- **Backdrop.** DirectComposition has no backdrop brush (that is Windows.UI.Composition's `HostBackdropBrush`), so the stage's snapshot recipe is used, as for the explorer's frost (§12): `NanoD-navigator-capture` `BitBlt`s the host column with our windows excluded (`WDA_EXCLUDEFROMCAPTURE` for the grab only; the floating knob's window too), reduces it to 1/4, `GaussianBlur` σ = 14·k/4, `saturate(1.8)` (Rec.709 matrix), `brightness(1.06)`. A show whose backdrop is older than 1.5 s waits for a fresh one (≤ 120 ms, else shows with the previous one). **While shown it refreshes every 2 s**; a changed desktop (mean 8-bit difference ≥ 1.5 at 1/16) crossfades in over 250 ms on a second glass visual, an unchanged one costs nothing.
- **Glass sprite** (one opaque premultiplied sprite per card height and backdrop, cached): the backdrop cropped to the card and upscaled (bilinear), `rgba(18,18,22,.30)`, the 160° white gradient .18 / .05 @ 42 % / .09, the specular (radial white .22 → 0, 220 × 160 at (−40, −60), `closest-side`), the four inset rims (`0 1px` .6, `0 −1px` .14, `1px 0` .22, `−1px 0` .10, 1 unit = k px, following the corner curve), cut to the antialiased 26-unit radius. No tint, no ambient fill.
- **Drop shadow** `0 18px 50px rgba(0,0,0,.35)` of the rounded card, built at 1/4 and stretched (LINEAR). **Text shadow** `0 1px 2px rgba(0,0,0,.35)` on every text except the key digits.

### 24.7 Content and type (NV-13…NV-24)

Archivo (bundled variable font, exact weights), caps labels 11/600/0.12 em/white 75 %, titles 15/19 600, secondary 12/16 85 %, meta 11/15 70 %; digits are tabular in Archivo. Paths: `Home`, `Music`, `Music › Recently Added`, `Music › Tracks`, `Music › Tracks › Seek`, `Lights`, `Lights › Scenes`.

| Kind (modes) | Content |
|---|---|
| now (`launcher`, `home`) | 64 cover (r 8, `0 8px 20px .35`, 1 px white .2 ring) + title / artist / `Playing · m:ss of m:ss` or `Paused` or the frame's status in its tone; Volume caps row + 4 px bar (track .2, fill white, 120 ms linear), the row 60 % at rest, 100 % while the frame shows the volume reveal (200 ms) |
| lights | caption + 44 px number (46 line, −0.03 em) + 16 px unit at 80 % (`Brightness 62 %`, `Colour temperature 4100 K`, `Lights Off`); Brightness bar (track .18, fill in the Kelvin colour, 0 when off); Temperature bar (gradient 2200 → 3400 → 6500 K, white 4 × 12 marker with a 1 px black .4 ring at (K − 2200)/4300); Scene row (rule .2, `{scene}` or `{scene} · adjusted`). The row the knob changes 100 %, the other 50 %. No status line (B14). |
| covers (`recent`) | 196-unit clipped carousel: 120 covers (r 8, `0 10px 24px .4`), ±86 @ 0.55, ±132 @ 0.38 (±170 @ 0.30 hidden), opacity 1 / .55 / .25, z by distance (reordered at the detent); title, artist, `{i} / {n} · {year}` |
| rows (`tracks`) | 5 × 38 rows around the playing song, wrapping; number 11 px 70 % (♪ playing), title 13/17 600 (`#9CF0BC` playing), tag 10 px caps (`Now` .6; `Skip to` / `Back to` `#6ED996` on the target); plate `rgba(255,255,255,.16)` r 10 + inset top .35 at the target; status `Turn for previous or next` / `Press 4 to skip` (a message in its tone replaces it) |
| seek | 44 cover (r 6) + title 14/18; 36 px `m:ss` (40 line, −0.02 em) + 12 px `of m:ss`; 4 px `#FFBE69` bar |
| scenes | the rows list: number, name, `Running` `#7EE0A2` on the running unadjusted scene; plate fixed at the centre; `Press 4 to run` |
| keys (all) | 2 × 2 under a .18 rule; 16 box (r 4, 1 px white .55), digit 10/700, label 11 white .9; unavailable / empty 40 %; the prototype's words per mode (`Back · Full screen · Play next · Play`, `Exit seek · Up next · Set · Skip`, …) with availability from the frame; `Hold 1 for Home` (11/14, 70 %, margin −4) when depth ≥ 2 |

### 24.8 Tree and motion (MO-7…MO-9)

```
root (LINEAR, SOFT, LAYER)
└ card (opacity, offset X / Y)        show/hide: opacity 280 ms, X −24 → 0 u 420 ms, OUT
  ├ shadow (1/4 sprite, ×4)
  ├ glass0, glass1 (opacity)          backdrop crossfade 250 ms EASE
  ├ path
  ├ content (opacity, offset X)       swap: from ±20 u, opacity 220 ms / X 380 ms OUT (deeper = from the right)
  │   └ the kind's visuals            one Tree per kind; each row / cover its own Tree (released when it leaves)
  │       rows / covers: Y (and scale) 380 ms OUT, opacity 280 ms EASE; plate 320 ms OUT
  │       bars 120 ms LINEAR (ScaleX about the left edge); dimmed rows 200 ms EASE; marker X 120 ms LINEAR
  ├ keys: line, labels, 4 × (box, pressed box (opacity 120 ms EASE))
  └ hold line (opacity)
```

- Every change is one `animation.Batch` per event (one Commit), compositor-run and sampled by DWM at the display rate: **240 Hz-capable with zero Python per frame**, as the stage (§1). Content swaps and height changes are instant (the prototype's flex), under the content slide.
- **Reduced motion** (`runtime.reduced_motion`): no slides (offsets jump), show/hide is a 200 ms fade, row fades kept.
- Leaving items and swapped kinds release their visuals, animations and surfaces (a 4-round swap test keeps the device's live objects flat).

### 24.9 Measurements, tests and open points

- **Headless** (`tests/test_r3_navigator_model.py`, `tests/test_r3_navigator_scene.py`, 55 tests; with the covers suite 69): content per state from a real controller (R3Fixture), keys, visibility and the Tk facade, the FastPath hook, the Settings value, the `navigator` suppression for an r3 knob and not for r2.2; every design state rendered on the fake device with no violations, opaque rounded glass, the prototype comparison (mean difference < 6/255 per channel; measured 1.3–2.9), motion durations/curves/directions, hide → host hidden, backdrop refresh only on change, display change / lock, touch-show only when eligible, device release after 600 s, facade + engine end to end (auto-hide after 4 s).
- **Contact sheet**: `design-reference/r3-navigator-sheet.png` (prototype left, ours right, 14 states + motion samples); per-state PNGs in `design-reference/r3-navigator/`, the prototype's in `design-reference/r3-navigator-prototype/` (regenerate: `make_prototype_reference.py` there, headless Chrome, offscreen).
- **Native, never shown** (a hidden click-through host, a real D3D11 + DComp device): the scene builds and commits every state with no COM error; a volume detent costs 0.9 ms p50 / 1.3 ms p95 on `NanoD-navigator` (build + Commit); a first show with the glass ≈ 20 ms; the backdrop build 0.4 ms at 1/4, the glass rebuild 2.4 ms; the column `BitBlt` took ~100 ms in the headless session (GIL released, on the capture thread).
- Covers (`tests/test_r3_navigator_covers.py`, 14 tests): the explorer's art identity, the ±2 window nearest first, fetches only through `CoverStore.fetch` with no extra arguments, cancellation of what left the window, no refetch of landed covers, the LRU bound, the Generated sleeve without network, a failing fetch keeps the tile and backs off 30 s, no `ArtService` = tiles, the Tk hand-over once, the 240 ms fade-in and its absence for a cover already in, the scene's image bound.
- Open: (1) the Recently Added covers need the stage's `ArtService` (`standalone` passes `stage.art`); without the stage they stay tiles; (2) the backdrop is a 2 s snapshot, not live — a moving window behind a pinned card lags up to 2 s; the live path is Windows.UI.Composition `HostBackdropBrush` interop; (3) the Scenes 1d pending state (`Runs in 1 s`) is not shown (1e only, as the controller).
