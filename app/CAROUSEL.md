# Windows switcher carousel (desktop v6; the v7 picker v2 in section 12)

Status: **frozen for desktop v6**; **section 12 (desktop v7, DESKTOP_STAGE.md §20.1) wins where it disagrees**. User request (2026-09-24): "Implement this new design for the windows switcher".

Integration amendments (2026-09-25, no scope change): the section 3 blur erratum, the bounded focus verify in section 1, the capture-exclusion rule in section 5, the label rules in section 6 and deviations 8–17 in section 9. They record what the build does and the reasons.

Review amendments (2026-09-25, no scope change): the shorter verify for Switch and Cancel targets in section 1; how farther cards show through nearer ones in section 2; the pane-scale outcome in section 4; in section 5, what the spike did and did not validate, the host's click rule, the exclusion's timing and the retained layered-window memory; the extra label rules in section 6; the brand-colour note in deviation 17 and deviations 18–22 in section 9; the host-activation acceptance items in section 10.

Section 11 implementation notes (2026-09-25, no scope change beyond section 11 itself): the pointers to section 11 in sections 1, 3 and 5, including the Settings name Frosted in section 3 and deviation 2 and the capture exclusion's monitor-wide reach in section 5; deviation 23 and the Frosted timing in deviation 9; the preview check and the frost-upload record in section 10; and the implementation notes at the end of section 11. They record what the build does and the reasons. Section 11's own text, including step 3's blur, is built as written.

- The design handoff is `design-reference/design_handoff_window_carousel/` (`README.md` and `Window Carousel.dc.html`). Its README is normative for visuals and motion, except where this spec deviates (section 9).
- User decisions:
  - **Size:** design proportions, fitting the stage to the monitor.
  - **Visual test:** a visual spike ran on the user's screen before the build (section 10).
- Scope: desktop only.
  - The knob firmware stays 1.0.0-cc5.3.
  - The knob's Windows mode, its LCD, ring, buttons, profile (MIDI SKIPPER) and bounds are unchanged.
  - The controller, runtime and `WindowsAdapter` logic, and the focus/activation contract, are unchanged.
- Only the **presentation** of the desktop picker is replaced (`PickerOverlay` → the carousel presenter), and the picker's label and icon data are enriched.

## 1. Seam and contracts that stay

- `WindowsAdapter` constructs the presenter at the point where it builds `PickerOverlay`, through the module-global factory. Tests patch it.
- The presenter implements the `PickerOverlay` protocol exactly:
  - constructor `(root, native, on_cancel)`;
  - `hwnd`;
  - `show(snapshot)`;
  - `focus_local()`;
  - `highlight(index)`;
  - `set_icons(dict)`;
  - `hide()`;
  - `close()`;
  - plus a new `rect` property: the physical `(x, y, w, h)` of the **glass pane**, which `ui._picker_rect` prefers over `.top`. So floating-knob suppression is keyed to the pane, not to the dim layer. (Superseded by section 11: `rect` reports the stage's pane-sized card area, set from the `show()` handshake to the end of the exit, and while it is set the knob is suppressed with reason `'carousel'`, wherever the knob is. The pane-overlap test remains only for a picker without `rect`.)
- **Focus contract, unchanged.** The picker owns the foreground while open, because Switch and Cancel arrive over serial with no input event.
  - When `show()` returns, `hwnd` must be a visible, activatable, top-level window of this process. It must not be `WS_EX_NOACTIVATE`.
  - `native.focus(hwnd)` then runs synchronously inside the WM_HOTKEY grant, as today.
  - The host lives on the `NanoD-carousel` thread, and a cross-thread activation completes only when that thread reads its queue. So `native.focus` verifies the grant: it re-reads `GetForegroundWindow` every 4 ms (sleeping, never spinning) for at most `FOCUS_VERIFY_SECONDS` = 250 ms.
  - Worst case on open, the Tk thread blocks for the 150 ms handshake, then the 250 ms verify, then the first label computation. Labels are pushed after focus, never inside it.
  - Switch and Cancel targets are windows of other processes. Their verify is bounded by `FOCUS_VERIFY_OTHER_SECONDS` = 100 ms, so a hung target, or one that activates an owned dialog (whose `GA_ROOT` is not the target), blocks the Tk thread for at most 100 ms per Switch or Cancel. v5 checked once; a target that is its thread's active window still passes at the first check.
  - If focus is not granted, the picker hides and `OSError` propagates as today. The origin is not re-focused on that path: `SetForegroundWindow` may already have handed the foreground to the carousel thread, and Windows activates another window when the hidden host gives it up.
  - `show()` may block the Tk thread for a bounded handshake of at most 150 ms while the presenter thread creates and shows the host. On timeout it raises the same `OSError` path as today's failure.
- **Activation stays synchronous and verified.** `adapter.activate` runs focus(target), then verify, then `presenter.hide()`. Cancel runs focus(origin), then `presenter.hide()`. The Switch/Cancel visuals are **exit animations** that play after focus has moved (section 4).
- **Thread safety.** No code on the presenter's native thread calls tkinter or the controller. Presenter input (Esc, Enter, arrow keys, wheel, a centre-card click) is queued on the presenter thread and drained by `adapter.pump()` on the Tk thread, following the `_hotkey_pending` pattern.
- **Invariants to port from the old tests:**
  - `ThumbnailLifecycleTests`: register once, never retry a failure, release on closed, off-screen or hide.
  - `OverlayDismissalTests`: nothing draws or registers after hide or close; thumbnails are released before the window goes; close is idempotent; show-after-close raises.
  - `PickerIconTests`: no icon work in the WM_HOTKEY or focus path.

  `GridTests` retire together with `picker_grid`. Every `AdapterTests`, `ForegroundEventTests` and controller test must stay green unchanged.

## 2. Layout (reference stage 1280 × 720)

- **Monitor:** the one containing the origin (foreground) window at open, from `MonitorFromWindow` and `rcMonitor` in physical px.
- **Stage scale:** `k = min(monW/1280, monH/720)`. On the user's 5120 × 1440 monitor that is `k = 2.0`. The stage is centred on the monitor, and every design value below is multiplied by `k`.
- **Glass pane:** 1140 × 560 at stage (70, 92). Corner radius 0, and the host uses `DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_DONOTROUND`.
- **Carousel centre:** (640, 300). The base card is 480 × 300. Each card at distance `d = i − sel`, with `a = min(|d|, 4)`:

  | a | offset X | scale | opacity | shade (#111) | visible |
  |---|---|---|---|---|---|
  | 0 | 0 | 1.00 | 1 | 0 | yes |
  | 1 | ±320 | 0.56 | 0.95 | 0.22 | yes |
  | 2 | ±460 | 0.34 | 0.60 | 0.44 | yes |
  | 3 | ±560 | 0.26 | 0 | — | no (kept for animation) |
  | ≥4 | ±620 | 0.20 | 0 | — | no |

- **Opacity and shade with DWM thumbnails.** For group opacity `op` and shade `s`, the thumbnail opacity is `o = op·(1−s)/(1−op·s)`, and the chrome draws the `#111` shade at `α = op·s`. That gives `o ≈ 0.937` / `α ≈ 0.209` at `a = 1`, and `o ≈ 0.456` / `α ≈ 0.264` at `a = 2`.
  - What farther cards drew in the chrome (shade, badge, shadow) inside a nearer card's rect shows through it as CSS shows it: at `1 − o` under a thumbnail card's shade, and at `1 − op` under a placeholder face, which is pasted over at `op` (a closed centre card keeps the side card under it, badge and shade, at 65 %). The open and exit fades are a group opacity in the prototype, so a card that is opaque inside the group still hides what is under it while the group fades.
- **Thumbnails:**
  - Cover-fit and top-aligned: `k' = max(W/sw, H/sh)`, `rcSource = ((sw−W/k')/2, 0, (sw+W/k')/2, H/k')`, with `(sw, sh)` from `DwmQueryThumbnailSourceSize`.
  - Only `|d| ≤ 3` are registered.
  - They are re-registered far → near on every detent, because z-order is registration order.
  - All five property flags are sent on every update.
- **Selected card:** a 2 px outline at 90 % white, offset 6 px, with shadow `0 24 60 rgba(0,0,0,.45)`. Side cards get `0 12 30 rgba(0,0,0,.3)`.
- **Badge:** a 32 × 32 app icon inset 14 px from each card's bottom-left, with shadow `0 2 8 rgba(0,0,0,.45)`. It scales with its card.
- **Label** (centre card only). A 900 px column, centred, at top 476, gap 6:

  | Row | Style |
  |---|---|
  | App | 18 px icon + app name, 15/20, white at 92 % |
  | Title | 28/34, weight 600, tracking −0.01 em, white, one line with an ellipsis |
  | Description | 15/20, white at 88 % |

- **Dots:** at top 616, centred, 8 px gap, one per window.
  - Selected: 22 × 6 at full opacity. Others: 6 × 6 at 60 %.
  - Radius 3, shadow `0 0 6 rgba(0,0,0,.35)`.
  - Width and opacity animate over 320 ms ease-out.
- **Closed windows:**
  - They stay in the list and their thumbnail is released (the current invariant).
  - They draw the icon placeholder card at 35 % opacity, and Switch is disabled.
  - The description reads `Closed · can’t switch`.
- **Minimized windows:** DWM supplies the last frame, which the mapping verified. The placeholder card is used only when the source is a caption stub (height ≤ 80 px or aspect > 4) or the thumbnail registration fails.
- **Placeholder card:** `#1c1c1e` with the app icon, or the letter tile, at 96 design px centred.

## 3. Glass and dim (the default "Liquid glass" treatment)

Section 11 supersedes the pane-shaped glass described here: the Frosted background covers the whole monitor, with no sheen, border, inset lines or pane shadow, and no dim window. Its blur is section 11's step 3, not step 2 below. "No background" is unchanged.

- **Pane fill:** a blurred snapshot of the screen behind the pane. The pipeline:
  1. reduce(8);
  2. GaussianBlur(σ = 40·k/8), which is 10 at k = 2. (Erratum: this line read 40·k/8/2. A CSS `blur()` filter takes a standard deviation, unlike a box-shadow blur radius, which is 2σ. So the README's `blur(40px)` is σ = 40·k physical px, or 40·k/8 after reduce(8). That is the spike's `GaussianBlur(10)`, validated on the user's screen. The toast's `blur(24px)` at reduce(4) is σ = 24·k/4.)
  3. CSS `saturate(1.8)` matrix (Rec.709);
  4. dim × 0.88 folded with the tint `rgba(18,18,20,0.58)`;
  5. specular sheen (white 12 % → 0 over the top 24 % of the pane);
  6. bilinear upscale;
  7. then, at full resolution: a 1 px border `rgba(255,255,255,.22)`, an inset top line `.40` and an inset bottom line `.08`.
- The snapshot is taken **after** the host is shown. `WDA_EXCLUDEFROMCAPTURE` on our windows makes the capture show only the desktop behind them. The spike measured the capture at about 15 ms and the glass pipeline at about 8.5 ms.
- The glass layer is a separate layered window just below the host (section 5). It fades in with the pane over 280 ms once it is ready, using the window's constant alpha. Opening never waits on the capture: until the glass is ready, the glass window stays at alpha 0.
- **Desktop dim:** black over the whole monitor, fading in over 320 ms. It is 12 % with glass and 55 % with no background. With glass it also carries the pane's drop shadow, `0 40 90 rgba(0,0,0,.35)`.
- **"No background" variant.** It is a Settings choice: **Switcher background: Frosted / No background** (the default is named Frosted since section 11; it read Liquid glass before). It is stored as `picker_background`, with values `"glass"` (the default) or `"none"`.
  - There is no glass window and no capture.
  - The dim is 55 %.
  - Card shadows are selected `0 30 70 rgba(0,0,0,.6)` and sides `0 16 40 rgba(0,0,0,.5)`.
  - Label text gets the shadow `0 1 2 rgba(0,0,0,.6), 0 2 18 rgba(0,0,0,.55)`.
  - The desktop behind stays live, because the host is transparent.

## 4. Motion (one clock, CSS transition semantics)

- **Curves:** ease-out is `cubic-bezier(0.22,1,0.36,1)`; the spring is `cubic-bezier(0.34,1.45,0.64,1)`.
- **Detent** (`highlight(index)`):
  - Each card's transform retargets from its current value over 420 ms, and its opacity over 300 ms.
  - Fast turns retarget mid-flight and never queue.
  - `highlight` only posts the new target; nothing is redrawn synchronously on the Tk thread.
  - The per-item availability re-check stays in the adapter, as today.
- **Open:**
  - The pane fades in over 280 ms. The 0.97 → 1 scale may be dropped if it costs more than 3 ms per frame. Outcome: it is dropped and the pane fades only (deviation 19). Scaling the glass means resampling the whole pane bitmap every frame, measured on the user's machine at 21 ms per frame (PIL bilinear, 2280 × 1120 RGBA) and 31 ms with placement and premultiplication, before a 10 MB `UpdateLayeredWindow`.
  - Cards fade in over 260 ms, and the dim over 320 ms.
- **Switch** (green):
  - The adapter activates synchronously.
  - The presenter then plays the exit: the centre card grows to 1.35 and fades out over 420/300 ms. The overlay layers stay topmost and non-activating during the exit, and release their thumbnails when it ends, at ≤ 420 ms.
  - Then the toast `{App} · {Title}` appears at the monitor centre: it rises 8 px and scales 0.96 → 1 with the spring over 420 ms, stays up to 1.5 s, then fades over 260 ms.
  - `close()` always releases at once.
- **Cancel** (red, Home, Esc): the overlay fades out over 260 ms, and the toast reads `Cancelled · focus restored`. Focus-loss dismissal gets no toast.
- **End bump:** a 12 px nudge in the turn direction that springs back over 160 ms. It is driven **only** by keyboard or wheel input on the host; the knob sends nothing at its end stops.
- **Pacing:** `DwmFlush`. If a flush takes more than 50 ms (DWM idle), it falls back to `MsgWaitForMultipleObjectsEx` for 8–16 ms and never busy-spins. The loop blocks in `GetMessageW` when idle.

## 5. Native architecture (`control_center/carousel.py`)

This reuses `overlay.py`'s proven patterns:
- a private ctypes declaration table;
- a dedicated thread with per-thread PMv2 DPI awareness;
- a module-level WNDPROC thunk that is never freed;
- a newest-wins Mailbox plus `PostMessageW` from Tk;
- strict teardown on its own thread.

**Classes:**
- `CarouselMachine`: pure state (`order`, `sel`, `open`, `switching`, `bump`) plus per-card tweens. It is unit-tested with a fake clock.
- `CarouselEngine`: runs on the `NanoD-carousel` thread with an injected backend and clock.
- `Win32CarouselBackend`: the only code that calls user32, gdi32, dwmapi or msimg32.
- `CaptureWorker`: a thread that does the BitBlt and the PIL glass, then posts `WM_APP_CAPTURED`. It never touches an HWND.
- `CarouselPresenter`: the Tk facade implementing section 1.

**Windows.** The spike (`<scratch>/carousel-spike`) validated the visuals, the z-order, the display affinity and the thumbnails on the user's screen. It did not validate the host's activation: every spike window was `WS_EX_NOACTIVATE` and none was ever activated. The activatable host's cross-thread activation (the Tk thread's `SetForegroundWindow`, completed when `NanoD-carousel` reads its queue), its keyboard focus, the `WM_ACTIVATE` → `WM_APP_ACTIVATED` gate of the open's setup and the passive exit have run against fakes and hidden windows only. They are acceptance items of the supervised check (section 10). All windows are created hidden at thread start and reused, with `DWMWA_TRANSITIONS_FORCEDISABLED` set on each. Bottom to top, stacking by **ownership** (dim → glass → host → chrome):

| Layer | Class / ex-style | Contents |
|---|---|---|
| **Dim** | `NanoD.Carousel.Dim`, ex `0x080800A8`, the monitor rect | Per-pixel ULW: black α plus the pane shadow (glass only). `WM_NCHITTEST` returns `HTTRANSPARENT`. Owns the glass window. Section 11: uniform black only, shown with "No background" and on the plain-host fallback, never with the Frosted layered host. |
| **Glass** | `NanoD.Carousel.Glass`, ex `0x080800A8`, the pane rect | Per-pixel ULW with the blurred glass, border and highlights. It fades with `SourceConstantAlpha`. Not used with "No background". Owns the host. Section 11: the monitor rect (`rcMonitor`), the frost only. |
| **Host** | `NanoD.Carousel.Host`, WS_POPUP, ex `WS_EX_TOPMOST\|WS_EX_TOOLWINDOW\|WS_EX_NOREDIRECTIONBITMAP`, not layered, **activatable** (never NOACTIVATE) | The pane rect. It is the DWM thumbnail destination, and its own area is transparent. It takes the foreground exactly as today's picker. It handles keys, wheel and the centre-card click (`d = 0` → Switch event; everything else is ignored, so the knob's absolute position never desyncs). A click never activates it while the foreground belongs to another process, or to no window (`WM_MOUSEACTIVATE` → `MA_NOACTIVATEANDEAT`): the Tk thread may already have given the foreground to the Switch or Cancel target before this thread has the exit's Dismiss. Owns the chrome. |
| **Chrome** | `NanoD.Carousel.Chrome`, ex `0x080800A8`, the pane plus a 16-design-px margin | Per-pixel ULW, composed each frame by drawing straight into its DIB memory with PIL (spike: about 0.64 ms compose + 0.41 ms ULW). Holds shades, outline, badges, card shadows, the label and the dots. |
| **Toast** | ex `0x080800A8`, unowned | A small glass pill. Shown after close. |

- **Fallback:** if `WS_EX_NOREDIRECTIONBITMAP` creation or thumbnail registration fails on some machine, the host falls back to a plain popup that paints the glass itself. The spike proved this path too. With that fallback, "No background" is disabled and the picker is forced to glass. Until the glass (or the tint without a capture) arrives, the plain host fills the pane's flat colour in `WM_PAINT`, so the open builds no bitmap before its handshake.
- **Frame order:** each frame computes the integer card rects once, then right after `DwmFlush` returns it sends the thumbnail updates and the chrome ULW back-to-back. The spike saw 21 of 22 frames aligned exactly; the one split frame was caused by the screenshot tool.
- **Display affinity:** `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` goes on dim, glass, host and chrome from show until the glass capture is taken, then `WDA_NONE`, so screen sharing and screenshots include the carousel again. The spike showed captures to be byte-identical to a desktop with no windows while the affinity is set.
  - Other top-level windows of this process that may be anywhere on the captured monitor (section 11: the frost captures the whole monitor) get the same affinity until the capture is taken: `CarouselPresenter.set_capture_exclusions(hwnds)`. The UI passes it the floating knob's `KnobOverlay.hwnd`. Windows of other processes and windows that no longer exist are skipped. `SetWindowDisplayAffinity` is checked per process, so the carousel thread may call it on the overlay thread's window. It does so after the show handshake, just before the capture job is submitted: the handshake itself only sets our own layers' affinity and calls `SetWindowPos`.
- **GDI rules for 32-bit DIBs:** never use GDI text, `FillRect` or raster ops, which zero alpha. Use premultiplied pixels only. Pre-scale badges with PIL, LANCZOS at rest and BILINEAR while animating. (The plain host's flat fill is a `FillRect` on an ordinary redirected window, not on a DIB.)
- **Memory:** the large DIBs (dim, chrome, backdrop, glass) are freed on hide. Budget at most 80 MB while open. The system also keeps each layered window's last `UpdateLayeredWindow` surface after hide (the constant-alpha fades reuse it): about 50 MB at 5120 × 1440 for dim, glass and chrome. So once they are hidden, each gets a 1 × 1 transparent surface (`release_retained`), and every open uploads full content again before its first fade.
- **Cleanup on hide:**
  1. unregister thumbnails, before hiding the host;
  2. hide chrome → host → dim, then give back the retained layered surfaces (1 × 1);
  3. free DIBs larger than 1 MB;
  4. clear the affinity.
- **Cleanup on close:** KillTimer, thumbnails, DIBs and DCs, `DestroyWindow` for toast, chrome, host and dim, `UnregisterClassW`, then join both threads within 1 s.

## 6. Labels (`control_center/window_labels.py`, pure and table-driven)

Start from the mapping draft (`<scratch>/labels-probe/window_labels.py`, 33 tests).
- **API:**
  - `WindowFacts(exe, app, title, class_name, minimized, audible, profile, monitor)`;
  - `label_for(facts, today) -> Label(app, title, desc)`;
  - `disambiguate(facts, labels)`;
  - `app_display_name(exe, package_name, file_description, product_name)`.
- **App name**, in this order:
  1. an override table by exe stem: explorer → File Explorer, bambu-studio → Bambu Studio, steamwebhelper → Steam;
  2. the packaged app's AppsFolder display name;
  3. FileDescription;
  4. ProductName, rejecting boilerplate;
  5. the title-cased exe stem. For a UWP frame (`ApplicationFrameHost`) with no resolved package name, step 5 is replaced: a one-segment title that is not a file name (`Calculator`) is the app name; otherwise (a title with separators, or a bare file name such as `IMG_0001.jpg`) the app row reads `Windows app`, so page or document text never becomes the app name.

  Reject names that are empty, generic, the whole filename, or longer than 48 characters; strip ®™©. Version info is cached per path, and UNC paths are skipped. The AppsFolder name is read on the IconWorker thread, cached, and pre-warmed. Only answers are cached. A failed lookup (for example `shell:AppsFolder` not ready at logon) is asked again, and `window_facts` retries it at most every 60 s (`FAILURE_TTL_SECONDS`).
- **Rules:** the README table, covering Slack DM and channel, the Chrome calendar, tab-count and Meet cases, Bambu `*`, File Explorer (`CabinetWClass`), Claude/ChatGPT, and the fallback.
  - Beyond the README table: a Slack group DM reads `Group message · <workspace>` and a private channel `Private channel · <workspace>`. A File Explorer title `<folder> and N more tabs` becomes the folder with ` · N+1 tabs` in the description. A File Explorer shell place (Home, This PC, Gallery, Network, Recycle Bin, Quick access, Control Panel, Linux) is described `Location`, not `Folder` (deviation 22).
  - Titles are normalised first: NFC, zero-width characters removed, en and em dashes mapped to ` - `.
  - `today` is injected.
  - A rule exception falls back to the generic rule and never breaks the picker.
  - **Edge pre-step,** before the browser rule looks for a trailing site segment. Edge writes `<page>[ and N more pages][ - <profile>] - Microsoft Edge`. ` and N more pages` becomes ` · N+1 tabs` in the description. The profile segment is dropped: the window's own profile, `[InPrivate]`, or, when the profile is unknown, one of Edge's default profile names.
  - **Claude/ChatGPT:** "the title, or the app name if blank". A title that is only an assistant's name (the home view) stays the title row, with the description `Desktop app`. This holds even when the app row reads another name, such as ChatGPT.exe's FileDescription `Codex` while the AppsFolder name is unresolved. A conversation title gets `Conversation · desktop app`.
- **Description fallbacks:** 'Desktop app' when the title equals the app name. The per-app override is Steam → 'Game launcher'. Otherwise it is the trailing site segment for browsers, or the app name.
- **Minimized:** ` · Minimized` is appended. **Closed:** `Closed · can’t switch`.
- **Duplicates:** identical labels get the Chrome profile (from `PKEY_AppUserModel_RelaunchDisplayNameResource`) if the profiles differ, otherwise the monitor friendly name (from `QueryDisplayConfig` + `DisplayConfigGetDeviceInfo`) if the monitors differ. Otherwise the labels stay identical.
- **Meet:** `In a call · Google Chrome` only when a lazy, off-Tk-thread Core Audio check finds an active render or capture session for that browser. Until the check has answered, the label reads `Meeting · Google Chrome`.
- Profile and monitor names are shown on screen only and never logged.
- `item['app']` (the exe stem) is unchanged for the knob. The carousel label lives in new per-item keys, delivered through a separate facts channel (`poll_facts()`), so the icon 3-tuple contract is untouched.

## 7. Icons

A 128 px master per window, built on the IconWorker STA thread and cached. The ladder, in order:
1. The package logo (`IShellItemImageFactory` on `shell:AppsFolder\<AUMID>`).
2. The window's `RelaunchIconResource`, when it `icon_matches()` the window's own icon.
3. The v5 HiresIcon (exe SHIL_JUMBO), also gated by `icon_matches`.
4. The window's own WM_GETICON big or class icon, upscaled with LANCZOS.
5. A letter tile.

- The picker enables hi-res icons in both app modes.
- Jobs are ordered by distance from the selected index.
- The 32 px knob icon and its 2048-byte payload are untouched.
- **Sizes:** the badge is 32·k px and the label icon 18·k px, both LANCZOS-resampled from the master.
- **Letter tile:**
  - The first character of the display name, upper-cased, in Archivo wght 700 at 17/32 of the tile, centred.
  - Colour: a small brand table, else a `zlib.crc32(name.lower())`-indexed palette of mid-dark colours, darkened until white text reaches at least 3:1 contrast.
  - Square corners.

## 8. Text

- The label is rendered with PIL on the carousel thread, never with Tk.
- Font: Archivo, the bundled variable font, with `set_variation_by_axes([wght, 100])` per face, and one face per (px, wght) per thread.
- Weights: 400 for the app and description rows, 600 for the title.
- Layout:
  - fractional advances;
  - tracking −0.01 em on the title;
  - per-glyph drawing with `anchor='ls'`;
  - the ellipsis fitted by binary search on the same width function over 900·k px.
- **Per-glyph font fallback** for glyphs Archivo lacks: Segoe UI (`seguisb.ttf` for 600), then Segoe UI Symbol, then Segoe UI Emoji (`embedded_color`), then Microsoft YaHei, then Malgun Gothic, then Yu Gothic. Coverage comes from each font's cmap, built once. There must be no tofu for Cyrillic, Greek, CJK or emoji titles.

## 9. Deliberate deviations from the design README

1. **Flat only.** The Arc variant needs a rotateY transform, which axis-aligned DWM thumbnails cannot do.
2. **"No background" ships as a Settings choice.** Frosted (section 11) is the default. The design's `dim` slider is fixed at 55 %.
3. **Switch activates first.** The target comes forward at once, and the grow-and-fade plays over it as an exit animation. The README activates at 380 ms. Activating first keeps activation reliable, as the focus contract in section 1 requires.
4. **End bump** is driven by keyboard and wheel only.
5. **Side-card clicks do nothing.** A click on a side card would desync the knob's absolute detent. The centre-card click is Switch.
6. **Not "never focus-stealing".** The picker keeps today's foreground ownership, which the README's own Switch semantics require.
7. **Toast glass** uses its own capture, subject to the same affinity rule.
8. **Toast position and text.** The toast sits at stage top 320, as in the prototype, not at the exact monitor centre. Its text is fitted to the 900 px label column. The `{App} · ` prefix is kept and the title is ellipsized. If the prefix would leave the title less than a quarter of the line, the whole line is ellipsized instead.
9. **Exit timing.** Both exits end when everything visible has reached 0, at 320 ms, when the dim finishes last. The switched card's 420 ms growth continues unseen after its 300 ms fade. Thumbnails are released when the exit ends, within section 4's ≤ 420 ms. With Frosted no dim is shown (section 11): the frost's fade ends at 280 ms, everything visible is gone by 300 ms (Switch, the card's fade) or 280 ms (Cancel), and the exit still ends at 320 ms.
10. **Fading cards stay registered.** After a fast turn, a card beyond |d| 3 keeps its thumbnail while it is still visibly fading out. It is released when its opacity reaches 0. At rest, only |d| ≤ 3 are registered (section 2).
11. **Card shadows transition.** Each card casts one shadow. Its offset, blur and alpha are interpolated between the side and selected shadows as the selection moves, which is what the prototype's `transition: box-shadow 320ms` does.
12. **Emoji font order.** An emoji code point tries Segoe UI Emoji before the rest of section 8's chain, because Segoe UI Symbol has monochrome glyphs for many emoji. An emoji code point here is one followed by VS16, or, unless VS15 follows, one at U+1F000 or above or a BMP `Emoji_Presentation` code point.
13. **Plain-host trigger and retry.** Beyond a failed NOREDIRECTIONBITMAP creation, the host falls back to the plain popup after 2 opens in a row in which at least 3 thumbnail registrations were tried and all failed. It tries the layered host again after 30 min (doubling, up to 24 h), or at once after a display change.
14. **Open setup waits for activation.** After the 150 ms handshake, the open's heavy setup waits up to 40 ms for the host's activation, so it never delays the cross-thread focus. The heavy setup is the monitor-sized dim, the chrome DIB and the first compose. Before the handshake, only our layers' affinity and `SetWindowPos` run: the floating knob's capture exclusion follows the handshake, and the plain host paints its flat colour instead of a prepared pane.
15. **Floating knob kept out of the glass.** The floating knob is a topmost window of this process and may overlap the pane. `set_capture_exclusions` gives it `WDA_EXCLUDEFROMCAPTURE` while the glass capture runs (section 5, display affinity).
16. **Label fallbacks.** The generic description is the app's display name (section 6), not the process name, which reads better than an exe stem. An unresolved UWP frame and an assistant's home title follow section 6.
17. **Missing-icon tile colour.** The tile takes its colour from a brand table, else from a crc32-indexed palette (section 7), not from the app's dominant colour. A window with no icon has no colours to take. Brand and palette colours alike are darkened until white text reaches at least 3:1 contrast, so four brand colours differ from their source, two of them the prototype's own sample tiles: File Explorer #E8B64A → #B38C39, Bambu Studio #00AE42 → #00A03C, Spotify #1DB954 → #1AAA4D and WhatsApp #25D366 → #1CA34E. In practice these apps always supply an icon, so their letter tiles appear only in previews.
18. **Meet label.** The README row reads `In a call · Chrome` (only if the tab is audible). The build writes the browser's display name (`In a call · Google Chrome`), and its audio signal is per browser process, not per tab: any active Core Audio render or capture session of that process counts. Until that check has answered, or when no session is active, the row reads `Meeting · Google Chrome`, a wording the README does not show.
19. **No open scale.** The pane's 0.97 → 1 open scale is dropped and the pane fades only: resampling the pane every frame measured 21 ms (section 4).
20. **Radius 0 only.** Only the default Modernist corner radius 0 ships, and the host is `DWMWCP_DONOTROUND`. The README's rounded 0–28 px variant (pane, cards, toast and badges, with 8 px icons) is not implemented.
21. **Icon sources and size.** The README reads `WM_GETICON(ICON_BIG)`, then `GCLP_HICON`, then the exe icon (the package logo for UWP), and renders at 64 px. The build keeps a 128 px master, because at k = 2 the badge is 64 physical px and the label icon 36. Its ladder (section 7) prefers the high-resolution sources, gated by `icon_matches`, over the window's own small `WM_GETICON` icon.
22. **Explorer shell places.** A File Explorer window on a shell place (Home, This PC, Gallery, Network, Recycle Bin, Quick access, Control Panel, Linux) is described `Location`, where the README's Explorer row says `Folder`: these are not folders.
23. **Full-screen frost instead of the glass pane** (section 11, the user's amendment). The README's Liquid glass is a blurred pane with a 1 px border, inset top and bottom lines, a specular sheen and a drop shadow, over a 12 % desktop dim. The build frosts the whole monitor instead: section 11's blur, the same saturation and tint with the 12 % dim folded in, and no pane, border, inset lines, sheen or pane shadow. The Settings choice is named **Frosted**, as section 11 names it. On the plain-host fallback the frost fills the pane only, over the 12 % dim.

## 10. Verification

- **Pure-logic tests:**
  - `CarouselMachine`: the table positions and opacities, retargeting mid-flight, the bump, the exit and cancel sequences, and the closed and minimized cards.
  - The opacity/shade math.
  - Cover-fit `rcSource`.
  - `window_labels`: the README examples, the real title shapes, name resolution, duplicates, Meet, and fallbacks.
  - The icon ladder with fakes.
  - The letter-tile contrast.
  - Text fitting and fallback coverage.
- **Presenter protocol tests** with a fake backend. The ported invariants (section 1) and the adapter, foreground-event and controller suites stay green unchanged.
- **Env-gated live test** (`NANOD_CAROUSEL_LIVE_TESTS=1`): create, register one thumbnail, compose, destroy, and check that GDI/USER return to baseline, and that hiding leaves the dim, glass and chrome 1 × 1. The windows are never shown, except in the supervised visual check.
- **Frozen smoke test:** it adds a hidden carousel lifecycle, the glass pipeline on a synthetic image, label rendering with fallback fonts, and the letter tile.
- **Preview PNGs:** `tests/tools/render_carousel_previews.py` composes the chrome plus the glass over a sample wallpaper, with the design's sample icons as stand-ins for thumbnails. It covers several selections, the closed and minimized cards, the toast, and a long title with an ellipsis. Since section 11 the glass is the full-screen frost. The previews add a 32:9 monitor (the user's 5120 × 1440 at k = 2), and the script fails unless every `glass_*` preview shows the frost reaching all four screen edges.
- **Supervised visual check** on the user's screen, after the build and with the user's go-ahead: open the picker with the knob, turn, Switch, and Cancel. The host's activation has never run on the real desktop (section 5), so these are explicit acceptance items, not assumptions:
  - Open with the knob's F24 and confirm the log line `Picker open focus granted after X ms (N checks)`, with X well under 250.
  - Enter, Esc, the arrow keys and the wheel reach the host.
  - After Switch and after Cancel, the target or the origin stays in the foreground through the 320 ms exit and after the teardown: the host never becomes active again, also when the centre card is double-clicked.
  - Record `presenter.metrics()`, and dwm.exe's commit before an open and after its hide. The metrics include `capture_ms` and `glass_ms` (the capture thread) and `glass_upload_ms` / `glass_upload_ms_max`: the frost's monitor-sized upload on the carousel thread (the DIB, its copy, `UpdateLayeredWindow` and the show), which lands during the open's card fade. Record `compose_ms_max` with them.
  - Keep the v5 rollback (`-Bundle desktop-dist-v5 -Mirror`) ready.
- **Packaging:** desktop v6 goes in `desktop-dist-v6`. `Build-Desktop.ps1` refuses v2–v5, and the rollback is `-Bundle desktop-dist-v5 -Mirror`. `Install-Desktop.ps1` requires a passing frozen smoke report.

## 11. User amendment (2026-09-25): full-screen frost or nothing

This section supersedes the pane-shaped glass in sections 2, 3 and 5. The user's words: "we either do it full screen or not at all".

**The two backgrounds.**
- **Frosted** (`picker_background = "glass"`, the default). The **whole monitor** behind the carousel is a blurred and tinted snapshot. It has no pane, no pane edges, no border and no inset highlight lines, and the pane drop shadow is dropped.
- **No background** (`"none"`). Unchanged: the desktop stays live, dimmed 55 %, with the card and text shadows of section 3.

**The Frosted pipeline** runs over the full `rcMonitor` in physical px:
1. capture;
2. `reduce(8)`;
3. `GaussianBlur(σ = 40·k/8)`, which is 10 at k = 2 (spec-owner correction, 2026-09-25: this step previously read 40·k/8/2 by mistake);
4. the saturate(1.8) matrix;
5. the dim × 0.88 folded with the tint `rgba(18,18,20,0.58)`;
6. bilinear upscale.

- **No sheen, no border.** With no pane, there is no top-edge highlight to anchor them.
- **Budget:** the spike measured a 41 ms full-monitor capture on the user's 5120×1440 display. The blur runs on the reduced image. The whole pipeline must stay off the Tk thread and the focus path, as before.

**Windows.**
- **The glass window moves to the monitor.** It now covers the whole monitor (`rcMonitor`), no longer the pane rect. It is still a per-pixel ULW layered window, click-through, above the dim and below the host, and it fades in with its constant alpha once the frost is ready.
- **The dim window is not shown with Frosted.** The tint already carries the 12 % dim. Its fade role moves to the glass window's fade, starting from alpha 0.
- **The host and chrome are unchanged.** The host stays the stage-sized `NOREDIRECTIONBITMAP` thumbnail destination; the chrome keeps its pane plus margin rect.
- **`presenter.rect` still reports the stage's pane-sized card area.**
- **Capture and affinity rules** are unchanged: `WDA_EXCLUDEFROMCAPTURE` on our windows until the capture is taken, then `WDA_NONE`.
- **Fallback, plain host:** the frost is painted by the host inside the pane rect only, and the rest of the screen gets the 12 % dim. The spec accepts this degraded fallback.

**Floating knob.** The knob is **suppressed for as long as the carousel is open**, with either background, and returns afterwards following its normal touch rules. This is suppression reason `'carousel'`, replacing the pane-overlap test. Touches while the carousel is open do not slide the knob in.

**Previews.** Regenerate the `glass_*` previews with full-screen frost. Every preview must show the frost reaching all four screen edges.

**Tests.**
- The glass geometry equals `rcMonitor`.
- Frosted has no border, sheen or pane shadow.
- With Frosted, the dim is not shown.
- Suppression holds throughout open → exit and lifts afterwards.
- The frost fade-in starts at alpha 0 and stays click-through.
- The fallback plain host paints the pane only.

**Implementation notes** (what the build does).
- **Blur.** The spec owner ruled on 2026-09-25 for σ = 40·k/8, which is 10 at k = 2 (`frost_sigma`, `FROST_SIGMA_DIVISOR = 1`). This is the CSS standard-deviation reading of the README's `blur(40px)`, consistent with section 3 and with the spike's validated `GaussianBlur(10)`. The earlier "/2" in step 3 was an error.
- **Capture thread.** The capture thread builds the frost as the glass window's premultiplied DIB layout (`frost_canvas`). The carousel thread only copies it into the DIB and calls `UpdateLayeredWindow` at constant alpha 0. The capture is decoded straight from its DIB, with no intermediate copy. On a synthetic 5120 × 1440 image the frost pipeline measured about 34 ms.
- **Memory.** At 5120 × 1440 the frost's DIB is 29.5 MB. It is freed right after the upload, and the retained surface is shrunk to 1 × 1 on hide (section 5). The peak while open is about 70 MB: the frost image and its DIB during the upload, plus the 11 MB chrome. That is within section 5's 80 MB. It is estimated from the buffer sizes, not measured; the supervised check records dwm.exe's commit (section 10).
- **Capture failure or timeout.** With no capture, the frost is the tint alone with the 12 % dim folded in, a translucent uniform layer over the live desktop. On the plain host the pane keeps its flat colour.
- **Upload cost.** The carousel thread's part, a 29.5 MB DIB, its copy, a monitor-sized `UpdateLayeredWindow` and the show, runs while the cards fade in. It has not been measured on hardware yet. `presenter.metrics()` reports it as `glass_upload_ms` (and `glass_upload_ms_max`), and the supervised check records it (section 10).
- **Suppression timing.** The `'carousel'` suppression follows `presenter.rect` on the UI's next tick. Until the frost's capture is taken, the knob's window is also excluded from it (section 5), so it is never blurred into the frost.
- **Settings label.** The Settings choice reads **Frosted / No background**, the names this section gives.

## 12. Desktop v7: the picker v2 (DESKTOP_STAGE.md §20.1)

This section is the v7 contract for the picker. DESKTOP_STAGE.md (K4) §9, §10, §5 and §6.2 and CONTROL_CENTER_V5.md (K3) §5.7 and §9.9 are normative. Where sections 1–11 disagree with this section, this section wins. The text of K4 §20.1 follows, then what the build does (§12.2) and its deviations (§12.3).

### 12.1 The amendment (K4 §20.1, copied)

1. **Scope:** the picker v2 of K4 §9, on the v6 window stack (S5-2). The §1 focus contract, §6 labels, §7 icons and §8 text are unchanged.
2. **Superseded:**
   - §2 layout: 480 × 300 at (640, 300) and the 320/460/560/620 table become K4 §9.3 (400 × 250, two tables, the group shift);
   - §2 selected card: the 6 px outline becomes the frame layer; interpolated shadows become a crossfade of two fixed layers (**deviation 11 retired**);
   - §2 badge 32 / 14 becomes 30 / 12; dots 22-wide selected, 60 %, radius 3, shadow become fixed 0.40 squares plus a marker;
   - §2 label: top 476 and 28/34 become 512 / 468 and 26/32; description 88 % becomes 86 %;
   - §3 / §11 Frosted recipe: saturate 1.8, tint (18,18,20,.58), 12 % dim become `blur.picker_frost` (S5-21);
   - §3 No background: the card shadows and the second text shadow become K4 §9.3's (S5-20);
   - §4 open: the in-place fade becomes the rise on open (K4 §9.8); §4 Switch: the 1.35 grow is removed (S5-6); §4 Cancel: the red Cancel and `Cancelled · focus restored` become warm Back with no toast (R:152);
   - §4 end bump: **deviation 4 retired**; it is also driven by the knob's `lim`;
   - §4 pacing: DwmFlush with the fast-flush heuristic becomes K4 §5 P2–P5;
   - §5 host: pane-sized becomes `rcMonitor` (it eats clicks everywhere); chrome: pane + margin becomes the band (K4 §9.2);
   - §5 / deviation 8 toast: moves to the toast service (K4 §10); position top 320 becomes 588; hold 1.5 s becomes 1.8 s; tint (30,30,32,.55) becomes (24,24,26,.62). The text-fit rule is kept.
3. **New:** the snap tray, fly, placement and closes (K4 §9.4–§9.7); the registration rule (K4 §9.3); B1–B5 (K4 §9.9); FrameStats (K4 §6.2); reduced motion (K4 §16).
4. **Tests:** §10's list plus H1, H4, H8, the snap state machine with a fake placement, and S3. The fake native layer also asserts that snap code reaches a target window only through `ShowWindowAsync` and `SetWindowPos` with `SWP_ASYNCWINDOWPOS` (never `SetWindowPlacement`, `ShowWindow`, a synchronous `SetWindowPos`, `SW_RESTORE` or `SW_MAXIMIZE`), and that a stalled fake resolves as `move_rejected` at the 800 ms deadline (600 ms for `complete_one_side`), by the worker or by the backstop, with the latched close run once.

### 12.2 What the build does (WP7b, 2026-09-25)

**Modules.** `control_center/carousel_render.py` holds the pure geometry and pixels: `Layout`, `layout_for(monitor, work)`, the two tables (`table_state(d, wide)`), `card_rect`, `slot_rect`, `fly_target`/`fly_rect`, `ShadowCache`, the sprites (badge, chip, slot glyph, border, caption, slot badge, dots, marker, toast) and `compose_chrome`. `control_center/carousel.py` holds `CarouselMachine`, `ToastMachine`, `LoopPacer`/`LoopStats`, `CarouselEngine` (the NanoD-carousel thread logic), `LabelWorker` (NanoD-label), `SnapWorker` + `Win32SnapNative` (NanoD-snap), `Win32CarouselBackend` and `CarouselPresenter`. `control_center/windows.py` (`WindowsAdapter`) is the runtime's seam: the v6 methods plus `snap`, `half_rect`, `close_pair`, `cancel(origin, complete=, reason=)`, `foreground_hwnd`, `take_events`, `toast`, `set_overlay_registry` and `set_reduced_motion`.

**Layout (K4 §9.2–§9.3).**
- k = min(W/1280, H/720) on the picker's monitor. The table is the 32:9 one when W/k > 1281, else the 16:9 one.
- The host is `rcMonitor`: host-local px are monitor-local px.
- The chrome is a band: x = centre ± max(X[a_vis] + 200·S[a_vis] + 20, 470) units, y 76–668 units, clamped to the monitor. That is 3060 × 1184 px (14.5 MB) on the user's 5120 × 1440 and 1648 × 1032 px on a 2560 × 1440 monitor.
- `presenter.rect` still reports the stage's card area (70, 92, 1140, 560 units), as the UI's `'carousel'` suppression expects.
- Cards are 400 × 250 at centre (640, 370). The cards group is shifted −44 units until the tray first shows.
- Tables: 16:9 is ((0,1,1),(280,.56,.95),(400,.34,.60),(490,.26,0),(540,.20,0)), a_vis 2. 32:9 is ((0,1,1),(280,.56,.95),(420,.42,.70),(545,.40,.45),(665,.40,.25),(780,.40,0)), a_vis 4. The shade is min(0.55, 0.22·a). Thumbnails are registered for |d| ≤ a_vis + 1 only.
- A card's thumbnail shows at o = op(1 − s)/(1 − op·s) under its #111 shade drawn at op·s.
- Shadows are two fixed layers per card: side (0 12 30 /.30) and focus (0 24 60 /.45). Side is painted at op(1 − selw), then focus at op·selw.
- The frame layer is a 2-unit white outline at 0.90, offset 6 units, faded by selw.
- The badge is 30 / 12. The chip is at 12/12, rgba(18,18,20,.72), with the half glyph and `Left`/`Right` at 12 px 600.
- The label is 900 units at left 190. It is at top 512 with the tray shown and 468 before. Its rows are the app row (15 px at .92), the title 26/32 600, and the description 15 px at .86 plus `· Snapped left/right`.
- The dots are fixed 6-unit squares at 0.40, pitch 14, at top 622 (578 before the tray), plus a translating marker. At most 82 dots are shown, with the end dots fading (S5-9).
- The tray is at top 104. Its two slots are 176 × 110, centred with gap 14 (x 457 and 647 units), each with a caption row 6 below.

**Motion (K4 §9.8, App A).**
- **Open:** the root is 280 ms OUT. Each card rises 24·S → 0 and scales 0.92 → 1, with opacity 0 → table, over 420 ms OUT.
- **Turn:** X and S take 420 ms, opacity 300 ms, the shade 320 ms OUT, and the frame/shadow crossfade 320 ms. The marker moves over 420 ms. The label swaps, then fades in over 160 ms. Only a label for another card fades in (the selection moved, or the first label of an open). A new sprite for the same card (the ` · Snapped left/right` suffix appearing at acceptance or going after a failed placement, label or icon data arriving after open, the card closing) replaces the old one at the current opacity, with no blink, as BS:1340's `_labKey` does (WP7b-R4).
- **End bump:** 12 units, 160 + 160 ms. It is driven by `highlight(index, bump=±1)`.
- **Tray reveal:** translateY −14 → 0 and scale 0.94 → 1 over 460 ms SPR, opacity over 260 ms OUT, and the group shift −44 → 0 over 460 ms OUT.
- **Slots:** fill 260 OUT, borders 260 EASE, glyph 200 EASE, badge 260 EASE.
- **Fly:** 460 ms OUT, a fade from 380 ms over 220 ms, released at 600 ms.
- **Close:** the root 280 ms OUT and the cards group 220 ms EASE. Every exit ends at 280 ms; there is no Switch grow.
- **Toast:** in over 260 OUT with a +8 rise and scale 0.96 → 1 over 420 SPR, a 1.8 s hold, out over 200 IN. A replacement restarts the hold.
- **Reduced motion** is latched at open, from `set_reduced_motion`. Positions and the group shift jump, card opacity changes take 200 ms, there is no bump and no fly, the tray only fades, and the toast is opacity only.

**Snap (K4 §9.4–§9.7).**
- `snap(request)` posts a job to NanoD-snap. The worker runs these steps:
  1. Pre-checks: identity, `IsHungAppWindow` → `hung`, and integrity above ours → `move_rejected`. A pass answers `accepted`.
  2. At t0 + 360 ms it restores without activation (`ShowWindowAsync` 4 or 7 only), polling every 10 ms up to 150 ms. A restore-to-maximized is reposted once.
  3. It sets the frame-compensated rect of the monitor's rcWork half with one `SetWindowPos(SWP_ASYNCWINDOWPOS | NOACTIVATE | NOZORDER | NOOWNERZORDER)`. The compensation is DWMWA_EXTENDED_FRAME_BOUNDS against GetWindowRect.
  4. It verifies every 20 ms up to 200 ms (400 ms for `ApplicationFrameWindow`), cut short by the deadline.
- The job answers `ok`, `cant_fit` or `move_rejected` by t0 + 800 ms. The carousel thread arms the same deadline as a backstop, and the first answer wins.
- A failed placement is put back with posted calls. A formerly maximized window stays restored at its normal rect, never re-maximized (S5-32).
- On acceptance the card's live thumbnail flies (translate + uniform scale) to a box centred in the rcWork half it is snapped to (K4 §9.5: kf = min(halfW / (400·k), workH / (250·k)); 2227 × 1392 px at x 166 for left or 2726 for right, y 0, on the G93SC). The target is the snap job's own half rect, so the fly ends where the window is placed. The slot fills with a second thumbnail of the window. (WP7b-R1: the job's rect used to be read as a side name, and every left snap flew to the right half.)
- Failures show on the slot for 2.4 s with the three VOC captions, in `#FF8474`: `overlay.picker.slot_hung` `{App} isn’t responding` (the pre-check found it hung), `overlay.picker.slot_move` `Couldn’t move {App}` (`move_rejected`, including the deadline) and `overlay.picker.slot_fit` `{App} can’t fit half` (`cant_fit`).
- Snapping a window already on the other side moves it. Both sides filled lead the runtime to `close_pair` at 820 ms: the posted raise, then the focus, then the pair exit.
- `complete_one_side` (U12) moves the origin to the empty half by its start + 600 ms. It is previewed as a ghost (0.35) in the empty slot while the picker is open.
- `raise_window` is a posted `SetWindowPos(HWND_TOP, NOACTIVATE | ASYNC)`.

**Events.** `take_events()` returns the input events plus:
- `snap_result(side, accepted | ok | move_rejected | cant_fit | hung)`;
- `complete_result(job, completed)`;
- `closed(display)` on WM_DISPLAYCHANGE;
- `system(sleep)` on suspend.

The adapter turns these into K3's `opened` / `closed(picker, reason)`, `snap_result`, `cancel_result(restored, completed)` and `system(lock | sleep)`. It adds lock detection through the input desktop and the focus-lost path.

**Toast service (K4 §10).**
- Toasts are presenter-level, outside any picker session: `toast(text, exit=False)`.
- A non-exit toast is dropped while any overlay is open (the picker, or what the runtime's registry lists).
- An exit toast waits for the picker's exit and shows at max(t_close + 360 ms, t_request). It is dropped while another overlay is open.
- An overlay that opens ends a showing toast. Toasts are dropped when `SHQueryUserNotificationState` is 3 or 4 (S5-17).
- The glass is `blur.toast`: reduce 4, σ 24·k/4 (12 px at k = 2, K4 §12), tint (24,24,26,.62), fallback tint at .88, at top 588.
- The pill is rendered on NanoD-label (`LabelWorker.submit_toast`, newest wins, ahead of labels) with `render_toast_canvas`: fills and masked pastes into a premultiplied canvas, never `Image.alpha_composite` (K4 §4.7.3: a fitted pill is up to about 160 K px at k = 2). The carousel thread only pastes the premultiplied pill into the toast window (resized while the scale springs). The tint-only pill is rendered first: it sizes the window and the glass capture and is the 150 ms capture-timeout fallback. A replacement restarts the hold at once, keeps the old pill up until NanoD-label has the new text on the old glass (stretched), then takes a fresh capture for the new width (K4 §10.2). No text fitting, blur or drawing runs on the carousel thread (WP7b-R6).

**Frame loop (K4 §5, §6.2, §9.9).**
- The pace wait uses `DCompositionWaitForCompositorClock` with the mailbox event. Without the export it falls back to one period on a high-resolution waitable timer (G1-2). There is no `sleep` and no `SetTimer` in a frame path, and no hard-coded period: P comes from `DwmGetCompositionTimingInfo`.
- The frame time is the predicted display time.
- The 120 lock engages when work p95 > 0.8 P and releases after 0.5 s under 0.6 P. **[erratum E-P1, proposed 2026-09-26, pending the user's acceptance]** One-off frames (an open's setup, the frost's upload, the GPU chrome's warm-up adoption) count nowhere; the GPU chrome's detent frames feed P2's estimate but not the lock's window; and the lock engages only once the loop has run 0.25 s since its last idle pause and at least two frames of the window are over 0.8 P (§12.5).
- FrameStats records present-cadence episodes in `metrics()['frames']` (K4 §6.2). Per frame it keeps `work_ms` (the wake to the start of the present: the drain and the compose) and `present_ms` (the thumbnail updates, the chrome ULW and the B2 layers). Each episode record has `work_ms`, `present_ms` and `compose_present_ms` (the per-frame sum, which is K4 §6.3's picker budget) as p95/max, `cpu_pct_one_core` (`time.thread_time`, i.e. GetThreadTimes of NanoD-carousel, over the episode), `boosted` and `rm`. Its `kind` is one of K4 §6.2's kinds; the end bump is a `turn`. Per surface, `totals` add `wall_s` and `cpu_s` per kind, and `pooled` holds every episode frame's compose + present and work in 0.1 ms histograms, so a check can take a pass's p95 from two reads (`hist_delta`, `hist_quantile`) (WP7b-R2).
- The pacer and stats are in `carousel.py`, not shared with the stage (see WP7b-D2).

**Compose (B1–B5).**
- **B1:** labels are rendered on NanoD-label with masked pastes only, for the selection and ±3, with 10 kept. The previous label stays until the new one exists (S5-24).
- **B2:** the label and the dots are separate layered windows, uploaded only on change. Group fades are constant alphas and the shift is a window move.
- **B3a:** shadow bands use NEAREST while animating and BILINEAR at rest. Rest band sets are cached.
- **B4:** badge and chip scales are quantised to 1/64.
- **B5:** the chrome is uploaded with `UpdateLayeredWindowIndirect` and `prcDirty` = the previous drawn box ∪ the current footprint. Only that box is cleared.
- Also in WP7b: solid-ink masked pastes go through zero-copy RGBX views of one cached buffer per ink (the same bytes as Pillow's colour fill, about 0.4× its cost on Pillow 12). Hot pastes and resizes call Pillow's core directly. Both are byte-exact and tested.

**Backgrounds.**
- **Frosted** is `blur.picker_frost`: capture → reduce(8) → σ 40·k/8 → saturate 1.6 → tint (10,10,12,.50), with no dim and no sheen, over rcMonitor. It runs on NanoD-capture and is uploaded into the glass window at alpha 0, then faded with the root. Without a capture the frost is a solid tint at alpha 0.50.
- **No background** is a flat 55 % dim, with the same card shadows and one text shadow, 0 1px 2px /.6 (S5-20).

**Tests and checks added in the WP7b fix round (2026-09-26).**
- **H4 goldens** (K4 §6.6; WP7b-R7): `tests/test_carousel_goldens.py` runs the production presenter inline on the fake backend and composes the monitor as the windows stack (desktop, frost or dim, the thumbnails as flat per-window colours at the engine's rects, opacities and z-order, the chrome band, the label and dots layers). States on both tables (1280 × 720 and 2560 × 720, k = 1): `open` (a closed and a minimized caption-stub card on screen), `turn` (mid-turn), `fly` (a left snap 360 ms into its fly), `filled` (the chip, the filled slot and the one-side preview) and `failure` (No background, a refused snap's red slot). The goldens are `tests/goldens/picker/*.png`, written with `NANOD_WRITE_GOLDENS=1` and reviewed by eye; a match allows 0.1 % of channel values to differ by more than 3 levels. A fly moved into the other half fails it. `tests/tools/render_carousel_previews.py` is still the v6 tool: its preview backend lacks the `layer_*` methods of B2, so it cannot run against v7 (it is outside this package).
- **S3 coverage** (K4 §6.5; WP7b-R10): `tools/stage_checks/picker_snap_checks.py` classifies every `--real-hwnd` by class and integrity level (`uwp` for `ApplicationFrameWindow`, `elevated` above our integrity, else `real`). The S3 verdict records each required kind (maximized, minimized, UWP, elevated, mixed DPI) as covered, failed or `not covered`, so a run without a UWP and an elevated window is never a complete S3. An elevated target must end `move_rejected`, not moved. The stand-in runtime raises VOC `toast.snap.one_side` after a completed Back. The dry run adds a stand-in UWP frame and an elevated window.

### 12.3 Deviations and open items (WP7b)

**[P2b] Accepted (lead ruling R-l, 2026-09-26; recorded in K4 §21.4):** WP7b-D1…D7 are accepted as built, WP7b-D6 and WP7b-D7 as corrected below.

- **WP7b-D1: plain-host fallback frost is monitor-wide.** The §5 plain-host fallback paints the frost over the whole host, because the v7 host is `rcMonitor`. §11's "pane only" assumed the v6 pane-sized host.
- **WP7b-D2: the pacer lives in `carousel.py`.** `LoopPacer`/`LoopStats` duplicate the stage's pacing logic instead of importing it. `tests/test_stage_static.py` forbids any non-stage module from naming the stage package. The behaviour follows K4 §5 P2–P5 and §6.2.
- **WP7b-D3: how `cant_fit` is decided.** After a verified-mismatch placement, a window counts as `cant_fit` when it sits at the half's origin (±2 px) and is larger than the half (its minimum size won). Any other mismatch is `move_rejected`. Both are put back (S5-13, S5-32).
- **WP7b-D4: no picker toasts.** The presenter's exits never toast. VOC `toast.switch` (`{App} · {Title}`), `toast.snap.pair` (`Side by side · {A} and {B}`) and `toast.snap.one_side` (`{A} left · {B} right`, only after a `back` close with `completed = true`) come from K3 through `toast(text, exit=True)`, which the presenter defers to its exit end.
- **WP7b-D5: teardown resolves pending jobs.** A display change, a suspend or `close()` during a pending snap resolves the job as `move_rejected`, and the worker's late answer is ignored. The window may still move once if its posted `SetWindowPos` was already queued.
- **WP7b-D6: the adapter infers `reason`.** ~~K3's `windows_cancel` carries no `reason`, and `runtime.py` calls `cancel(origin, complete=)` without one.~~ **[P3]** K3's `windows_cancel` carries the close `reason` (K3 C5-78), and `runtime.py` passes it as `cancel(origin, complete=, reason=)`. `cancel(origin, complete, reason=None)` takes an explicit reason when the runtime passes one. Otherwise it uses the lifetime reason it saw itself (lock through the input desktop, sleep), else **`idle` when `IDLE_INFER_SECONDS` (59.5 s) have passed since the last knob-driven call** (show, highlight, snap, activate; K3 closes after 60 s without knob input), else `back`. So an idle close hides at once, as K4 §9.7 and §15 require, with the completion after the hide (WP7b-R8). ~~The inference is a stopgap: the fix at the root is a K3 erratum that adds `reason` to the `windows_cancel` payload (the controller already latches it in `_cancel_pending`) and has the runtime pass `reason=effect.get("reason")`. Those files belong to K3's and the runtime's packages.~~ **[P3]** The root fix is built (K3 C5-78; K4 21.4 E-c): the inference stays only as the fallback for a payload without `reason`.
- **WP7b-D7: no fly shadow.** As S5-4 says: the fly is a DWM thumbnail outside the chrome band. **[P2b]** This holds for the step-1 (CPU) chrome only: step 3 draws the fly's shadow (§12.4; K4 §9.10, 21.4 E-h).
- **Q2 (open, lead decision): the step-1 budget is missed on both tables (WP7b-R3).** K4 §6.3's "Picker (W), step 1" row gates compose + present ≤ 5.6 ms p95 on the 16:9 table without condition; for the 32:9 table, §22 Q2 (named by §6.3 and §19.2) makes step 3 (the chrome as DirectComposition visuals on the stage device) part of v7 when compose + present p95 exceeds 7.0 ms after B1–B5. The headless bench is `<scratch>/wp7b/bench_compose.py`: the real `CarouselEngine` on the fake backend at k = 2, with open, 14 turns, a snap with tray and fly, 6 turns, and a second snap, repeated 5 times. It times `compose_chrome` only; the present (the ULW upload) cannot be measured without a window and only adds to it. Compose p95 over the steady frames, the median of the 5 repetitions (their range), on this shared PC:

  | Run | 16:9 (2560 × 1440) | 32:9 (5120 × 1440) |
  |---|---|---|
  | WP7b build (2026-09-25) | 6.3 ms (5.8–6.7) | 7.19 ms (6.90–7.85) |
  | Verifier's re-run (other load) | 8.35 ms (7.22–9.17) | 9.89 ms (7.89–11.26) |
  | This fix round (2026-09-26) | 6.82 ms (6.77–6.93); turns 6.97, whole `_prepare` 7.02 | 8.07 ms (7.96–8.12); turns 8.21, whole `_prepare` 8.28 |

  - Every run misses both gates on compose alone: 16:9 is over 5.6 ms, and 32:9 is at or over 7.0 ms before any present time. The picker therefore runs step 1 under the 120 lock, with frames of 2 P or more during turns on 32:9.
  - WP7b does not build step 3. It needs the stage device and the stage package, which this package may not import (WP7b-D2, `tests/test_stage_static.py`), and it is its own work item.
  - **Decision needed before release** (not taken here): either (a) make step 3 part of v7, per §22 Q2's recommended path, hosting the chrome visuals in the stage package or granting `test_stage_static` an exception for the picker; or (b) record a K4 erratum that accepts step 1 at the 120 lock on 32:9 and restates the 16:9 budget.
  - **Decided (lead ruling R-h, 2026-09-26): (a).** Step 3 is built (WP7c, §12.4): the chrome moves onto DirectComposition, hosted in the stage package, with the CPU chrome of this section as its fallback. The step-1 numbers above stay the record of the fallback path.
  - The supervised W check now measures the gate itself: compose + present p95 over each pass's episode frames and the carousel thread's CPU (≤ 70 % of one core), from FrameStats (WP7b-R2); before, it gated compose alone.

### 12.4 Step 3: the chrome on the GPU (WP7c, 2026-09-26; lead ruling R-h)

K4 §9.10 is the contract text; this section says what the build does. Every other rule of §12.1–§12.3 (the focus contract, the thumbnails, snap, the tray's behaviour, the toast service, the plain host) is unchanged.

**What moves.** Everything of the picker that is not a live window: the two card shadows (side and focus, crossfading), the selection frame, the #111 shade, the badge, the snap chip, the placeholder face, the label, the dots and marker, the snap tray (backgrounds, the three border looks, glyphs, badges, captions) and the fly's shadow. They become DirectComposition visuals with prepared surfaces, and the **compositor runs their animations**. The live windows stay DWM thumbnails on the host, stepped per frame by `NanoD-carousel`. The frost (the glass window) and No background's dim keep their layered windows and constant-alpha fades.

**Where the code is.**
- `control_center/stage/picker_chrome.py`: `PickerChrome` (the device, the tree, `sync(view)`, uploads, the lifetime). It is hosted in the stage package so the static rule holds: `carousel.py`, `carousel_render.py` and `windows.py` never name the stage package (K4 §4.1).
- `carousel.install_gpu_chrome(factory)`: the seam. The one wiring point, `standalone.py`, calls `picker_chrome.install()` once at startup ~~(a cross-package line, see the WP7c report)~~ **[P3b]** (wired by the lead's decision of 2026-09-26: `standalone.main` runs `install_picker_chrome()` right before ControlCenterApp builds the WindowsAdapter, whose presenter reads the factory when it is made; a failed install is logged and leaves the CPU chrome). Without that call the picker keeps the CPU chrome.
- `carousel.py`: `CarouselEngine` drives the GPU chrome (`_prepare_gpu`, `_gpu_view`, `_gpu_sync`, `_gpu_prefetch`, `_present_gpu`, `_gpu_fallback`), `ChromeView` / `ChromeCardInfo` / `ChromeSlotInfo` (what the engine hands over at each event), the chrome's window on `Win32CarouselBackend`, and the batched thumbnail updates.
- `carousel_render.py`: the chrome's sprites (`sprite_bgra`, `gpu_shadow_sprite`, `frame_ring_sprite`, `placeholder_face_bgra`, `slot_border_colour_sprite`, `half_sprite`, `solid_bgra`, `card_box_px`).
- `control_center/stage/picker_device.py`: the native device made in two halves for a knob touch (`prepare` on a worker thread, `adopt` on `NanoD-carousel`, `discard`).
- `control_center/stage/picker_testing.py` (the headless rigs and a reference renderer with clips), `picker_bench.py` (the benches) and `picker_selftest.py` (the stage self-test extended with the picker's checks).

**The window.** A new layered window `NanoD.Carousel.Gpu`, ex style `0x082800A8` (click-through, never activating, `WS_EX_NOREDIRECTIONBITMAP`, `SetLayeredWindowAttributes` alpha 255), is created hidden with the chrome and owned by the host, so it always lies above the host and its thumbnails. At an open it is placed on `rcMonitor`: the thumbnails' host-local pixels are its client pixels. It shows after the chrome's first Commit, is hidden with the other layers, is excluded from capture while the frost is taken, and is recreated with the host (§5 fallback). Clicks fall through to the host, so the focus contract, `MA_NOACTIVATEANDEAT` and the centre-card Switch are unchanged.

**The device.** The chrome has its own D3D11 + DirectComposition device on `NanoD-carousel`. It is created on the adapter of the picker's monitor at the first open, or earlier by `note_touch()`. It is released after 600 s without an open (`device.DevicePolicy`, K4 §4.2). The stage's segment tables (`curves.Prewarmer`) are warmed in 2 ms idle steps from the carousel thread's start; the stage thread warms the same shared tables. See WP7c-D1 for why the device is not shared.
- **A knob touch never holds `NanoD-carousel`** (the thread that answers `show()`'s 150 ms handshake; review finding WP7c-R6). `note_touch()` posts `WM_APP_WARM`; the engine calls `PickerChrome.warm_async`, which runs the slow half on a short-lived worker thread, `NanoD-chrome-warm`: the adapter that owns the monitor and `D3D11CreateDevice` (measured here: 129 ms for the process's first device, 14–28 ms after). An `ID3D11Device` is free-threaded, and its immediate context is used by one thread at a time (the worker only creates it). The worker's end posts `WM_APP_WARM` again, and the carousel thread adopts the half: `IDXGIDevice`, the DirectComposition device and the timeFrequency check, about 1 ms (`picker_device.adopt`).
  - An open that arrives while the worker runs answers its handshake at once. Its setup (after the handshake) waits for the worker, at most 1 s, and adopts its half: one device either way. Headless, with a 400 ms worker and the touch 2 ms before `show()`, the handshake took about 1 ms (before the fix, a 160 ms creation made `show()` fail).
  - A half made for another monitor, or one that finishes after `close()`, is released, never adopted.
- **The policy follows every release** (review finding WP7c-R1). A device made for another monitor (a second monitor, or HMONITORs renumbered by a display change) is released and the next open or touch makes one on the right adapter. A failed call that is not a loss (E_INVALIDARG, any exception in a sync, an upload or `begin`) releases everything and marks the policy cold, so the next open tries the GPU again. Only a loss goes through the policy's recreate limit.

**The mirror.** `CarouselMachine` stays the only source of motion.
- At every event that retargets it (open, turn, end bump, tray reveal, slot looks, failures, exit, a label swap, the fly), the engine builds a `ChromeView` and calls `sync(view)`: one batch, one Commit.
- Each chrome property is programmed as the machine's own tween: the same start, target, duration and curve (OUT, IN, SPR, EASE), and **the same begin time**. That is the machine's `t0` (`perf_counter`), converted to the compositor's ticks. The stage builder fits it within K4 §4.6.2's bounds (`Batch.to(..., anchor=t0, v_from=start)`).
- A begin time in the past drops the start of the curve (MS-3). So at every displayed frame the chrome shows the value the thumbnails sample for that frame (P2's predicted display time).
- The tree makes each property linear in exactly one tween:
  - the card's position container: X and its opacity (own × the closed factor);
  - a scale by `s`, then the enter rise, then a scale by the enter scale;
  - the cards container: the end bump, programmed as two legs in one animation;
  - the group: the shift and the group opacity; the root: the root fade;
  - the tray: its Y, scale and opacity; the marker's X; the label's alpha;
  - the fly: X, Y, scale and its delayed fade.
- A property whose tween did not change since the last sync costs no call, and invisible cards get no slot (G1-4, R-k).
- Card visuals are pooled and reordered far → near at each detent (`Tree.reorder`). The first open builds 14 slots. After that, a frame without an event adds one slot (`grow_pool`: 12 visuals, a clip, 2 transforms and 22 animation objects) while fewer than 6 are free and the open's windows could use more, so a detent's sync never makes an object (K4 §4.7.1, §9.10; review finding WP7c-R4). A burst that still finds no free slot grows one inside the sync and counts it (`slots_grown_in_sync`: 0 in the tests at 20 and 40 detents/s with 30 windows, in the reviewer's 40-window probe at 83 detents/s, and in the benches).

**Occlusion.** Every chrome visual lies above every thumbnail, so a farther card's chrome must not darken the nearer card's thumbnail.
- Each card's chrome is clipped to the half-plane beyond its nearer neighbour's far edge: an animated `IDCompositionRectangleClip` edge on a clip holder with no offset or transform.
- The centre card and cards under a closed card are not clipped.
- The edge is one machine tween when the neighbour's X and scale retarget together. In mixed motions (fast turns on 32:9 far cards, a turn during the open's enter) it is one curve anchored at the latest retarget (`clip_approx`; ≤ 2.3 px in the tests, on far, dim cards). See WP7c-D3.

**Uploads a frame ahead.** Measured headlessly on this PC: a Commit that follows a surface upload at once costs about 3 ms (it waits for the copy); one a frame later costs about 0.1–0.2 ms; a property-only Commit costs 0.02–0.1 ms.
- Every upload is followed by `ID3D11DeviceContext::Flush`.
- A surface is shown only once it is at least 4 ms old (`Surfaces.ready`).
- Frames without an event prefetch (`_gpu_prefetch`, one sprite's uploads per frame): the waiting label first, then the badges of the cards the machine holds (the full-size badge near the centre, the half-resolution copy on side cards: WP7c-D4), the chips, and the tray's glyphs.
- A label swaps once its surface is ready: one frame after its upload (S5-24's "the previous label stays").
- A sprite that is not ready at a sync is left out of that batch and synced in the next frame (`want_sync`, counted in `late_uploads`). This happens at the open and at a snap, while those elements fade in from 0, and at rest: new icons or labels (`set_icons`, `set_labels`) and a card that closes (its placeholder face).
  - `want_sync` keeps the engine's loop awake until that sync, at rest too (review finding WP7c-R3; before, the new badge or face waited for the next input).
  - A card slot that already shows this card keeps its previous badge, chip or face until the new surface is ready, as the tray keeps its caption. A slot just given to another card shows nothing of the previous card's.
- Once the cards rest, the frames also build (one per frame) what a snap of the selected card would show at once: the chips, its slot badge and the slot captions of either outcome (`_gpu_prebuild_snap`). So the acceptance frame, the fly's first, renders no text (its frame fell from about 9.6 ms to under 5 ms in the bench).

**The frame loop.**
- Per frame, the engine computes only the thumbnails: the same `card_rect`, `thumb_opacity`, `slot_rect` and `fly_rect` as step 1, at the predicted display time.
- Every update of a frame goes out back to back through the GIL-keeping `DwmUpdateThumbnailProperties` (G1-1, R-h; `update_thumbnails`). On the GPU chrome an unchanged thumbnail is not sent again.
- The detent's re-registration (z-order is registration order) moves to the frame after the detent's Commit (WP7c-D6).
- `NANOD_PICKER_THUMB_LEAD` (periods, default 0) lets the thumbnails sample ahead if the on-screen witness shows them landing a frame late (AR-12).

**Fallbacks (R-h).** The CPU chrome (§12.2's band, label and dots layers) draws in these cases:
- `set_chrome_mode('cpu')` on the presenter or the adapter;
- `NANOD_PICKER_CHROME=cpu`;
- the plain host;
- no chrome window (`Win32CarouselBackend.has_gpu_window` is False when `_create_gpu_window` failed; review finding WP7c-R7). Like the switches and the plain host, this is not a fallback: no `gpu_fallbacks` count, no warning per open, and a knob touch warms no device;
- a device that cannot be created;
- **device loss or a failed sync or upload mid-open**, in a detent's frame or in a frame without an event (the prefetch's `CreateSurface` or `UpdateSubresource`, where K4 §4.3 detects a loss too; review finding WP7c-R2). The open continues on the CPU chrome in that same frame: the band and layers are allocated, and the label and dots are composed again. The chrome releases every object, and the next open tries the GPU again (after a loss at most twice, 1 s apart, then cold until the next open, K4 §4.3).

**Metrics.** `presenter.metrics()` adds:
- `chrome` ('gpu' | 'cpu'), `gpu_sessions`, `gpu_fallbacks`;
- `gpu`: syncs, last and max sync ms, calls, animations, commit ms, `clip_approx`, `late_uploads`, device creates and losses, surfaces;
- also `last_release` (monitor, error, lost, idle, close), `warm_starts`, `warm_adopted`, `warm_ms` (touch to adoption), `warming`, and the pool's `slots`, `slots_grown_ahead` and `slots_grown_in_sync`.

**Personal text at the close** (review finding WP7c-R5). `end()` unbinds the label visuals and every placeholder face in the batch of its Commit (the root to 0), then releases the session's label surfaces. A DirectComposition visual holds its own reference to its content, so before this fix the last window title's surface stayed alive on the GPU until the next open or the 600 s release.

FrameStats records (K4 §6.2) add:
- `chrome`, `normal_ms` and `detent_ms` (the per-frame Python work, compose + present, split by whether the frame carried a sync), `detent_frames` and `sync_ms`;
- the pooled `normal_ms` / `detent_ms` histograms;
- `recent`: the last 64 episodes' (kind, t0, t_end, chrome), which the supervised check matches with the compositor's displayed frames.

**Headless benches** (`.venv\Scripts\python.exe -I control_center\stage\picker_bench.py --dwm`, by path from the project folder: `-m` cannot find the package under `-I`; k = 2):
- the production engine in real time at 240 Hz, with the chrome on the native device without a target;
- real DWM thumbnails of the carousel's own hidden windows, updated through the GIL-keeping export;
- the label worker on its thread;
- a session of: open, 14 turns at ~7/s, 20 at 20/s, a left snap with the tray and the fly, 6 turns, a right snap, the exit.
- Medians of 3 repetitions on this shared PC (2026-09-26), in ms; the brackets give the range of the p95 over the repetitions:

  | Table | Normal frames p50 / p95 / max | Detent frames p50 / p95 / max | Sync (build + Commit) p50 / p95 / max |
  |---|---|---|---|
  | 16:9 (2560 × 1440) | 0.34 / **0.68** (0.67–0.72) / 2.26 | 0.99 / **2.23** (1.88–2.49) / 4.90 | 0.48 / 1.82 / 3.47 |
  | 32:9 (5120 × 1440) | 0.42 / **0.79** (0.79–0.80) / 2.60 | 1.07 / **2.60** (2.39–2.74) / 4.53 | 0.45 / 1.93 / 3.32 |

  - The lead's target (per-frame Python work ≤ 1.5 ms p95 at 32:9) and §6.3's step-3 row (≤ 1.5 ms p95 on normal frames, ≤ 3.0 ms on detent frames) hold on both tables.
  - About 1,450 frames and 91–93 detent frames per repetition; "detent frames" are every frame that carried a sync (turns, label swaps, the snap's events).
  - The maxima are the snap frames (the tray's reveal, the chip, the fly).
  - Step 1 on the same PC: compose alone 5.45 ms p95 (16:9) and 6.36 ms (32:9), before any present.
- After the review fixes (WP7c-R1…R7), same session, same PC, busier (2026-09-26). `--count 30` runs it with 30 windows, so the card pool grows:

  | Table, windows | Normal frames p50 / p95 / max | Detent frames p50 / p95 / max | Card slots (grown inside a sync) |
  |---|---|---|---|
  | 16:9, 14 (3 reps) | 0.35 / **0.70** (0.69–0.73) / 1.99 | 1.01 / **1.99** (1.85–2.03) / 5.16 | 14 (0) |
  | 32:9, 14 (3 reps) | 0.46 / **0.87** (0.81–0.89) / 2.44 | 1.08 / **2.21** (2.16–2.34) / 4.78 | 14 (0) |
  | 16:9, 30 (2 reps) | 0.38 / **0.80** (0.79–0.81) / 2.94 | 0.90 / **2.09** (2.05–2.13) / 5.15 | 20 (0) |
  | 32:9, 30 (2 reps) | 0.55 / **1.01** (0.97–1.04) / 3.44 | 1.16 / **2.65** (2.43–2.87) / 5.71 | 23 (0) |

  - Both gates hold on every row. The normal-frame p95 at 32:9 with 14 windows is 0.08 ms above the first record; the fixes add no per-frame work on normal frames (a flag test, and the pool step only while slots are short), so this is within the PC's run-to-run spread.

**Tests and checks.**
- `tests/test_stage_picker.py` covers:
  - the GPU path replaces the band and the layers;
  - at every frame of an open, fast and slow turns, a long move, an end bump, a snap and the exit, every chrome property that the fake device recorded equals the machine within the fit bounds, and the chrome's card box equals the thumbnail rect within 1.5 px (the headless half of AR-12);
  - the clips; the z-order; one Commit per event, none without a change, and no upload in a detent's batch;
  - the label readiness; the fly's shadow; the exit and the teardown;
  - device loss mid-open → the CPU chrome, then the GPU at the next open;
  - an uncreatable device, the switches, the plain host and a missing window;
  - the 600 s release and the knob-touch warm-up; the close releasing everything;
  - thumbnails not re-sent; the install seam; the static rule; the FrameStats split;
  - parity with compose_chrome at rest (H4, WP7c-D3);
  - the sprites; and, on the native device without a target, the clip slots and the context flush (H6);
  - the review fixes (`ReviewFixTests`, each shown to fail with its fix reverted): a monitor change and a failure that is not a loss leave the next warm or open on the GPU (R1); a loss in a quiet frame's `CreateSurface` or upload hands the open to the CPU chrome in that frame, and the loop then rests (R2); new icons, labels and a closing card at rest are synced in with no input and no badge blanks meanwhile, and a reused slot never shows another card's sprites (R3); with 30 windows at 20 and 40 detents/s on both tables, no pooled object is made inside a sync (R4); the close unbinds the label and the faces before its Commit and releases the label surfaces (R5); a knob touch makes nothing of the device on the carousel thread, the handshake answers with the worker still running, the open adopts its half (one device), a half for another monitor or after `close()` is released, and on real threads `show()` answers well inside 150 ms with a 400 ms worker (R6); a missing window keeps the CPU chrome with no fallback count and no device (R7); and, natively, a device made in two halves on two threads (R6).
- `tests/test_carousel_presenter.py` and `test_carousel_live.py` cover the new window: its styles, ownership, attributes, affinity, hide and destroy order, and `has_gpu_window` (False while the method still exists when the window could not be made). They also cover the batched updates on real hidden windows.
- `test_carousel_adapter.py` covers `note_touch` and `set_chrome_mode`.
- **[P3b]** The wiring: `tests/test_cc_tray.py` `StartupCleanupTests` (the real `main()` with a stand-in kernel32: the install runs once, right before ControlCenterApp, and a failing install still starts the app), `tests/test_standalone.py` `PickerChromeWiringTests` (a presenter made after the install takes the GPU chrome, one made before keeps the CPU chrome; a raising, half-way or import-failing install leaves the CPU chrome), `tests/test_cc_ui.py` `FastPathTests` and the shell tests (a knob touch reaches the runtime's picker with the stage, never more often; a runtime swap is followed), `tests/test_stage_picker.py` `WiringTests` (the fast path on a reader thread → the adapter → the production presenter: the reader only posts, the worker makes the device).
- `.venv\Scripts\python.exe -I control_center\stage\picker_selftest.py` (by path; `--picker-only` skips the scenes) runs the stage self-test with the scenes, then:
  - the picker's static checks;
  - **[P3b]** the app's wiring (WP7c-D11 closed): `standalone.main` installs the chrome once, right before ControlCenterApp, and `ui.FastPath` warms the picker with the stage (read from the source);
  - H6 for the eight clip setters (S_OK, NULL refused by the animation overloads) and the context flush;
  - the native device in two halves (D3D11 on a worker thread, the rest adopted here; about 1 ms to adopt);
  - an end-to-end GPU session per table on the native device, warmed by a knob touch (one device, adopted), with hidden windows' thumbnails;
  - the benches, gated on 32:9, and a 32:9 session with 30 windows whose pool grows in quiet frames only (gated). Run 2026-09-26 after the review fixes: 10 of 10 gated checks passed.
- `tools/stage_checks/picker_snap_checks.py --chrome gpu|cpu|both` (supervised, not run) measures step 3 on screen:
  - the compositor's displayed frames per picker episode;
  - the chrome Commits' pickup classes;
  - the step-3 row of K4 §6.3;
  - AR-12's alignment witness (1-px rows through the cards: the frame's centre against the thumbnail's; it recommends `NANOD_PICKER_THUMB_LEAD` when the thumbnails trail).
- Its `--dry-run` runs the tours on the GPU chrome (fakes) and checks the witness analysis on synthetic rows.

**Deviations (WP7c).** **[P3b] Accepted (lead, 2026-09-26; recorded in K4 §21.5):** WP7c-D1…D13 are accepted as built; D11 is closed by the wiring.
- **WP7c-D1: the chrome's own device.** K4 §22 Q2 said "on the stage device". The chrome has its own device on `NanoD-carousel`: the stage device lives on `NanoD-stage`, and sharing it would need COM calls from two threads plus a lock in files outside this package.
  - Measured headlessly: a second device next to a warm stage device costs about **16 MB** private and **17–28 ms** to create. If the picker makes the process's first device, it costs 144 ms and 54 MB.
  - Both warm: ≈ 70 MB, inside §14's +80 MB guard.
  - `note_touch()` moves the creation off the open (~~a cross-package line in `ui.py`, see the report~~ **[P3b]** wired: `ui.FastPath` calls `WindowsAdapter.note_touch()` together with the stage's `note_touch()`, at most once per 10 s), and off `NanoD-carousel` too: its slow half runs on a worker thread (see "The device"), so a touch right before a press never delays `show()`'s handshake.
- **WP7c-D2: compositor-run mirror, not lockstep stepping.** RF0 step 3 planned to step the chrome per frame from the thumbnails' values. R-h asks for compositor-run animations. The chrome runs the machine's own curves with the machine's begin times, and the thumbnails are stepped at the predicted display time.
  - Headless: both follow the same curves at every frame (within 1.5 px of the thumbnail's integer rect).
  - On screen, the thumbnails can land a frame late (AR-12). The supervised witness decides, and `NANOD_PICKER_THUMB_LEAD` is the lever (0 until measured).
- **WP7c-D3: occlusion by clips.** A farther card's chrome is clipped away inside its nearer neighbour. compose_chrome keeps (1 − cover)/(1 − drawn) of it under a translucent card. Under a closed nearer card nothing is clipped (closer to CSS's 65 %).
  - Measured parity against compose_chrome with the CPU label and dots layers, k = 1, at rest and after a turn: a mean alpha difference of **0.19** levels (16:9) and **0.46–0.56** (32:9), with **0.06–0.10 %** of pixels more than 24 levels apart. Those pixels are the overlap strips of the 32:9 far cards and half-pixel edges at k = 1.
  - In mixed motions the clip edge is approximated (≤ 2.3 px, far cards).
- **WP7c-D4: two levels for badges and chips.** A card whose scale stays under 0.75 shows a half-resolution copy (S5-28's rule applied to small sprites; the copy swaps at events). Placeholder faces and the frame keep one level.
- **WP7c-D5: sprites a frame late.**
  - A new label shows about one frame (4 ms) after its sprite exists; S5-24 allows "≤ one render".
  - A badge, caption or glyph not prepared by an event is left out of that batch for a frame (`late_uploads`). This happens at the open and the snap, while those elements fade in from 0, and at rest when new icons or labels arrive or a card closes. The card keeps its previous badge or chip for that frame; a closing card's face appears a frame after its sync.
- **WP7c-D6: the re-registration a frame after the detent.** The thumbnails' z-order changes 4 ms after the chrome's. This keeps the ≈ 1 ms of DWM registrations off the detent frame.
- **WP7c-D7: sub-pixel chrome at k ≠ 2.** The chrome is continuous and the thumbnails are integer rects. At the user's k = 2 every rest edge is a whole pixel. At other k, a card edge may be a half pixel apart (≤ 0.5 px).
- **WP7c-D8: the fly's shadow returns** (S5-4 is lifted for the GPU chrome). It is drawn above the cards, as the fly thumbnail is registered last, with a hole along the fly's box. LINEAR magnification to kf = 2.78 softens its inner edge by about 1.4 px on the last frames, while it fades.
- **WP7c-D9: the clip slots outside `com.SLOTS`.** The eight `IDCompositionRectangleClip` setters and `ID3D11DeviceContext::Flush` (slot 111) are resolved in `picker_chrome.py`. `com.py` belongs to another package, and adding PY slots there would enlarge `test_stage_device`'s H6 set. The picker self-test proves them.
- **WP7c-D10: no FPS HUD on the picker chrome.** K4 §6.2's HUD exists on the stage only.
- **WP7c-D11: off until wired.** The GPU chrome runs only once `standalone.py` calls `picker_chrome.install()`. **[P3b]** Wired on 2026-09-26 (the lead's decision): the app installs it at startup and the fast path warms it at a knob touch; measured headlessly on the real presenter and device, a touch costs the reader thread ≤ 0.16 ms and the device's creation adds no GIL wait above the idle baseline. At startup the carousel thread now also prewarms the shared segment tables (pure Python in 2 ms idle steps, as the stage thread does, WP7a-R4): measured headlessly in fresh processes, the stage alone kept a 0.5 ms-sleeping probe waiting up to 3.6–5.5 ms for about 0.33 s, the picker alone up to 2.6–2.9 ms for about 0.9 s, and both together up to 4.6–7.5 ms for about 0.41 s (the tables are shared, so the work is not doubled); this happens once, while ControlCenterApp is still being built and before the knob can connect, so no overlay takes input then (G1-5).
- **WP7c-D12: a support switch, not a setting.** `set_chrome_mode` and `NANOD_PICKER_CHROME=cpu` exist; Settings (K3) has no choice.
- **WP7c-D13: GIL-keeping thumbnail updates on both chromes.** `update_thumbnails` is used by the CPU chrome too, with the same calls in the same order; only the GPU chrome skips unchanged updates.

**Open items.** **[P3b]** The app's wiring is done and verified headlessly; what is left is supervised, with the user's go-ahead:
- `picker_snap_checks.py --run --chrome gpu` (and `--stress`): tour W's displayed fps ≥ 235, the pickup, AR-12's witness (and `NANOD_PICKER_THUMB_LEAD` if it trails), S3 on the GPU chrome, memory per §14 with both devices warm.
- The by-eye check of the clip edges on the 32:9 far cards.
- **[2026-09-26]** The thumbnails' re-registration on animated frames (WP7c-D6), open until the on-screen re-run attributes the picker's gaps (§12.5, O-R1).

### 12.5 The frame-drop fixes of 2026-09-26: errata (proposed, pending the user's acceptance)

The on-screen tours of 2026-09-26 (`diagnostics/music-tours-20260926-112320.json`, `picker-snap-checks-20260926-112429.json`) led to fixes S1–S3 (the stage, K4 §21.6) and P1 (this loop). The review of those fixes found that P1's first form could not lock at 60 Hz, nor at 240 Hz once the work passed 2 P, and that none of the four changes had errata. The rows below are **proposed**: they take effect when the user accepts them, and the on-screen re-run is judged against the amended text. Nothing here was shown on screen.

| # | Was | Now (as built) | Where |
|---|---|---|---|
| **E-P1** | §12.2 "Frame loop" and K4 §5.1 P5: the 120 lock engages when the work p95 over the last 0.5 s exceeds 0.8 P, and releases after 0.5 s under 0.6 P | For the carousel's loop (the picker and the toast, `carousel.LoopPacer`): (1) a **one-off frame** (an open's setup, the frost's upload, the GPU chrome's warm-up adoption) is recorded nowhere, neither in P2's estimate nor in P5's window; (2) a frame that carried the **GPU chrome's detent sync** feeds P2's estimate but not P5's window (its own budget is 3.0 ms, K4 §6.3 step-3 row); (3) the lock engages only once the loop has **run 0.25 s** (`LOCK_MIN_SPAN_S`) since its last idle pause and at least **two frames** of the window are over 0.8 P (`LOCK_MIN_OVER`: with fewer than 20 frames the nearest-rank p95 is the worst frame, so one slow frame alone never locks); a pause longer than max(0.1 s, 6 P) between two loop frames starts a new run and empties P5's window. The release rule is unchanged. P1's first form (a minimum of 60 frames in the window) is **withdrawn**: the 0.5 s window holds at most 31 frames at 60 Hz, and 40 at 240 Hz once the work is over 2 P, so the lock could never engage where it is meant to (review, 2026-09-26). Measured headlessly (`drop_bench.py`, `lock_by_rate`): a loop whose work stays over 0.8 P locks 0.25 s into its run at 60, 120, 144 and 240 Hz, with work under P, over P and over 2 P; one frame of 3 P among light ones never locks | `control_center/carousel.py` (`LoopPacer.frame_done`, `lock_ready`, `run_gap`; `CarouselEngine.present`'s `oneoff` / `p5` flags); `tests/test_carousel_machine.py` `PacerTests`; `tests/test_stage_frame_drops.py` `PickerOneOffTests`; `control_center/stage/drop_bench.py` |
| **E-P2** | §12.4 FrameStats: the episode record and `recent` (kind, t0, t_end, chrome) | Each picker episode also records `locked_frames` (presents paced under the 120 lock), `paced_frames`, `rereg_frames` and `rereg_ms` (the thumbnails' re-registration: how often and how long); each `recent` entry gains a fifth field with those facts and the re-registration times (ms from the episode's start). `picker_snap_checks.py` gives every displayed episode an `attribution`: the P5 lock (most presents at cadence 2 and a displayed interval p50 of about 2 P), the re-registration (at least half of the gaps begin within 1.5 P of a re-registering frame), or neither | `control_center/carousel.py` (`LoopStats`); `tools/stage_checks/picker_snap_checks.py` (`attribute_gaps`, checked by `--dry-run`); `tests/test_carousel_machine.py` `LoopStatsTests`, `tests/test_stage_frame_drops.py` `PickerOneOffTests` |

**Open item O-R1: the re-registration on animated frames.** The brief listed the thumbnails' DWM (re)registration on animated frames among the causes. It is still there: after every detent the frame after the chrome's sync unregisters and re-registers the thumbnails (z-order is registration order; WP7c-D6), about 1–2 ms of DWM calls. But the morning's data points elsewhere: the worst displayed episode of each tour W pass was a **snap** (Frosted 149.0 fps, 68 missed of 126 frames over 203 vblanks; No background 137.8 fps, 74 missed of 117), with displayed frames exactly 2 P apart (interval p50 8.332 ms, max 3 P), and the session's pacer ended at cadence 2 after 17 switches (the opens: 493 missed of 516 frames). That is the P5 120 lock, which E-P1 addresses, not registration. The item stays open until the supervised `picker_snap_checks.py --run --chrome gpu` re-run confirms it through E-P2's attribution. If the re-run names the re-registration, the fix is to keep it off animated frames: register once the cards rest, or re-register only the cards whose order changed.
