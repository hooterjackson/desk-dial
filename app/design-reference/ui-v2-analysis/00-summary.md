# 00 · UI V2 master design: completeness review, contradictions, decisions and build plan

Read-only synthesis, 2026-09-25. It reviews the analysis set in this folder against the master handoff and the current code, fills the gaps it finds, and proposes the plan for the one combined release (firmware **1.0.0-cc5.4** + **desktop v7**, which carries ALIVE "Warm · alive" and the whole master design).

Nothing was run. No serial/COM port, knob, Tk window, Sonos or Apple Music call was used. `credentials.bin` and `settings.json` were not opened.

## Keys

| Key | File (paths under `<repo>\`) |
|---|---|
| R, S01…S05 | `app\design-reference\design_handoff_nano_d_master\README.md`, `specs\01…05-*.md` |
| BS, RC, KF, KM, CC | `…\prototypes\Browse and Snap.dc.html`, `Ring Choreography v2.dc.html`, `Knob Face.dc.html`, `knob-model.js`, `Nano_D Control Center.dc.html` |
| A01…A06 | `…\ui-v2-analysis\01-knob-behaviour.md` … `06-services.md` |
| CS, CP, CL, CF, RP, RA | `…\ui-v2-analysis\check-seek.md`, `check-play-next.md`, `check-like.md`, `check-favourite-playlists.md`, `research-apple-music-play-next.md`, `research-artwork-resolution.md` |
| AL, P4 | `firmware\ALIVE.md`, `PRESENTATION_V4.md` |
| code | `app\control_center\*.py`, `firmware\src\*` |
| MEM | the user's auto-memory note `nanod-cc53-release.md` (Claude project memory) |

---

## 0. Headline

1. **Coverage is good.** Across 01–06 and the six check/research files, every mode, button, LCD layout, LED target, LED moment, overlay, icon and tray state in the master is extracted with numbers and citations. Every README §9 acceptance item maps to a gate (§1.1).
2. **Five things nobody analysed, now filled in §1.3:**
   - the **240 Hz** desktop animation requirement;
   - **input blackouts** during every host-driven knob re-entry;
   - **slow, all-or-nothing playlist playback**;
   - **overlay lifetime** (idle, lock, sleep);
   - **Tracks `Next:` / `Prev:` titles under Sonos shuffle**.
3. **Biggest risk: 240 Hz.** The user wants every desktop animation at the monitor's 240 Hz (MEM:56; the display is 5120 × 1440 at 240 Hz, RA:239). The explorer and Up next as analysed cannot reach it:
   - they use CPU-composited covers plus a 14.7 MB stage-size `UpdateLayeredWindow` per frame (A03 §10.2 item 3; A05 §5.5);
   - resampling one pane bitmap already measured 21–31 ms on this PC (`CAROUSEL.md:125`);
   - the refresh-rate study has not landed (no `refresh-0*.md` in this folder).

   A GPU path must be spiked before the music overlays are built (G1).
4. **Design corrections backed by evidence:**
   - Play next is `DesiredFirstTrackNumberEnqueued = P+1+i`, **not** `EnqueueAsNext=1` (A06 §1.4).
   - Favourite playlists need `extend=inFavorites`. The user has **2 of 239** playlists favourited, and one is Apple's "Favorite Songs", so **Like does reach the tab**, through that playlist (CF:7-15).
   - The two big overlay covers need **1200 px** requests, not the design's 600 px (RA:23-30).
   - "~360 ms wake" is a leftover from the pre-alive CSS model (G6).
5. **Most contradictions resolve by precedence.** Four need the user: the paused Play colour (U1), Like on Up next (U2), Shuffle semantics (U4) and the volume amber/red body brightness (U8). The full list is §3.
6. **The plan (§4):**
   - four contract docs plus an acceptance update;
   - ten work packages with disjoint file ownership;
   - four gate stages;
   - one hardware window, with live Sonos/Apple checks before it, each with the user's go-ahead.

---

## 1. Completeness critic

### 1.1 README §9 acceptance checklist: coverage and verifying gate

| # | Acceptance item (R:234-244) | Analysed in | Status / gap | Gate that proves it (§4.4) |
|---|---|---|---|---|
| 1 | Every mode's four buttons, icons and LED levels match §4 and §6; only button 4 is ever green | A01 §1.4-1.5, §3; A02 §3-4; A04 §2.10, §3.3; A05 §2.2 | Complete. Contradiction C1 (paused Play is green) goes to **U1** | A1 controller map tests; A2 target golden from BS `renderVals()`; A4 LCD harness |
| 2 | Back up one level everywhere; hold = Home; Windows only from Home | A01 §4.1, §4.4; A04 §6.1-6.2; A05 §2.2-2.3 | Complete. Host-only hold timing is proven broken (A04 §6.1); a **firmware `kh` event** is required | A1; A3 (`kh` parse); H turning test (hold feel, F24/serial race) |
| 3 | Home volume number hidden at rest, springs in at 48 px | A04 §2.6 | Already implemented (`cc_display.cpp:791-839`). No work | Existing harness |
| 4 | Seek: 5 s per detent on the 67-detent profile; ring laps the song; exits after 3 s idle | A01 §3.5; A02 §4.5; A04 §7; CS; A06 §2 | Complete. Rulings: `T_end = D−3`, flush on exit (§3 delegated) | A1; A2 twin replay (`lap`); L live W2; H feel |
| 5 | Play next inserts the album after the current song; Up next shows those rows with their own covers | A06 §1; CP; A05 §2.6; A06 §6 (ledger) | Mechanism corrected (C3). **Not yet proven on this household** (U3) | A1 with a positional FakeSpeaker (today it ignores `position`, A06 §7); L W1 |
| 6 | Explorer: horizontal square carousel; tabs on 2 and 3 keep positions; playlists as a 2 × 2 mosaic | A03 §2; A05 §5; CF; RA | Complete, but see G1 (refresh), G5 (art size), G4 (data) | A1 scene machines; S1 supervised frame time |
| 7 | Up next: vertical list; the cover stays still for an album and crossfades for a playlist | A03 §3; A06 §4, §6 | Complete. Album vs playlist needs the provenance ledger (A06 §6) | A1 ledger tests; L R1 census |
| 8 | Snap: tray hidden until first snap; thumbnail flies; windows land flush; auto-close when both sides are filled | A03 §4; A05 §6 | Complete. The design's `SW_RESTORE` is wrong (C24) | A1 fake-native placement; S3 supervised snap |
| 9 | LEDs: warm-dim rest with breath; ~360 ms wake; lists only item colours; one foreground moment; nothing above 3 Hz | A02; AL | "~360 ms" (G6) and "3 Hz" (G7) must be restated as oracle-match criteria | A2 oracle and golden; H LED tour |
| 10 | No toast over an overlay; none for Play/Pause | A03 §5; A05 §7 | The prototype breaks it (Like and Shuffle toasts, BS:662, :691). Resolved in C9 | A1 stage test "toast refused while a scene is open" |
| 11 | Tray icon follows the taskbar theme and the connection state | A03 §7; A05 §8 | Already met (assets byte-identical). Optional: `WM_SETTINGCHANGE` instead of the 2 s poll | A1 `test_cc_tray` |

### 1.2 Spec-section coverage

| Section | Covered by | Note |
|---|---|---|
| R §0 precedence, §1 files, §2 fidelity | all | S01's own intro still names stale files (`SCREEN-SPEC.md`, `LED-SPEC.md`, S01:13-18). This is cosmetic |
| R §3 hardware and profiles | A01 §2; A04 §7 | BINARIS BEER is valid for Seek; no new profile |
| R §4 grammar, map, icons, footer | A01 §1.5, §3; A04 §3; A05 §2.2 | Complete, including the BS naming trap (A04 §3.2) |
| R §5 LCD | A01 §1-3; A04 §2 | Complete. LVGL text shadow and tabular digits are decided in §3 |
| R §6 LEDs | A02; AL | Complete |
| R §7.1 overlays and toasts | A03 §1-5; A05 §5-7 | Complete, apart from G1 and G9 |
| R §7.2 main window, settings, tray, recovery | A03 §6; A05 §8-9 | Conflicts with the user's "no main window" (C28 → U14) |
| R §7.3 icons | A03 §7; A05 §8 | Assets byte-identical. The theme event is optional |
| R §8 integration notes | A06; CP; CS; CL; CF; RA | Two corrections: `EnqueueAsNext` (C3) and 600 px art (C4). "Minimized uses the last frame" is already true in v6 (`CAROUSEL.md:91`) |
| S01 §1-8 | A01, A03 | Complete |
| S02 §1-9 | AL (in progress); A02 | Step 5 of Coming online (the LCD fade-up at 1600–2200 ms, S02:155) is omitted by AL D6. It stays omitted (§3 delegated) |
| S03 | A01 §3, §5; A03 §6 | S03's LED sections (L1–L4, white/targeted colour, S03:167-213) are superseded by S02 (C15). The RGB565 transfer is superseded by the artwork2 JPEG path |
| S04 | A03 §4; A05 §6; CAROUSEL (v6) | Title parsing, duplicates, icons and the closed-window rules are unchanged and still valid |
| S05 | A03 §7; A05 §8 | Complete |
| CC §05 state table, §06 stress, §07 tokens, §08 review | history only | CC:1105 ("At home nothing is green") bears on U1; CC:1108 ("Volume stays white") is superseded by S02 |

### 1.3 Gaps found and filled

| # | Category | Gap | Evidence | Fill / recommendation |
|---|---|---|---|---|
| **G1** | Overlay behaviour, performance | **The 240 Hz requirement is not budgeted anywhere.** | The user wants every animation, including explorer, Up next, picker swipes and the floating knob, at maximum refresh (MEM:56). 240 Hz at k = 2 gives a **4.17 ms** frame. A05 §5.5 estimates 15–25 ms per explorer frame. `CAROUSEL.md:125` measured 21 ms (31 ms with placement) to resample a 2280 × 1120 pane before a 10 MB ULW. The stage chrome would be 14.7 MB per frame (A03 §10.2.3). `Pacer` already paces on DwmFlush (`carousel.py:476-520`), so composition is the limit, not pacing; its fallback wait of 8 ms caps at 125 Hz. AL:421 caps the floating knob at "up to 60 fps". | **Spike before WP8**, on the picker's own GPU pipeline: explorer covers and Up next rows as **DWM thumbnails of small hidden source windows**, moved per frame with `DwmUpdateThumbnailProperties`, which the picker cards already do. The ambient layer should be DWM-stretched (A05 §5.4 option B). Text layers change only on a detent, so upload them with `UpdateLayeredWindowIndirect` + `prcDirty`. Target per **U10**. Gate S1 records the p95 frame interval during a 420 ms turn. AL:421 needs an amendment (K2). |
| **G2** | State, knob input | **Every host-driven re-entry is an input blackout.** | A new control puts the knob in phase 1 (`control_center.cpp:215-221`). `cc_input_id()` is 0 until ready (`:255`), so key events are dropped. The motor runs `move(0)` with **no detents** (`foc_thread.cpp:105`), and motion is **rebased away** at ready (`foc_thread.cpp:98-104`). Entering waits for motor, HMI and LCD acks, including a 46–149 ms JPEG decode on a new art key (A04 §6.1). A05 §2.4 lists seven host-driven kinds (tab switch, Back from the explorer, Up next open, Shuffle focus, Seek on/off, snap auto-advance, queue change while Up next is open). Only Seek was assessed, as harmless (A04 §7). | (1) **Re-enter at the design's own swap instants,** when the design already ignores input: explorer tab at **190 ms** (BS:806-808; turns ignored BS:706); Shuffle at **200 ms** (BS:690, :719); explorer and Up next Play at **380 ms** (BS:696, :813); snap advance at **420 ms** (BS:855). This also fixes contradiction A5: an immediate re-entry would flip the knob LCD 190 ms early. (2) Keep the frame's `artKey` unchanged across a re-entry where the design allows, so no decode runs inside "entering". (3) Never re-enter for a **passive** change (the queue changed elsewhere) until 400 ms after the last detent. (4) Add an `enterMsLast/Max` diag, and measure it in the hardware window (gate H3). |
| **G3** | Error path, latency | **Playing a playlist is slow and all-or-nothing, and the explorer makes playlists common.** | `resolve()` maps each library track with its own `/v1/me/library/songs/{id}/catalog` GET whenever the tracks page lacks `relationships.catalog` (`apple_music.py:308-316`). Today that is always, because no `include` is sent (`:368`). Live Apple GETs on this account took about 0.3–0.36 s (CF:16, CF:56), so "Favorite Songs" (16) needs about 5–6 s and "PAPER LANTERN" (34) about 11–12 s before Sonos is touched (estimate). `play_items` then reads the **whole queue twice per song** (`sonos.py:384`, `:390`). One track without a unique catalog match aborts everything: "Nothing was queued." (`apple_music.py:314-327`). Two latent bugs: `trackCount` never exists on library playlists (CF:70), so `apple_music.py:369-371` never checks them; and `_collection` follows `next` verbatim (`:293`), which drops `extend`/`include` (CF:74). | Add `include=catalog` to `/tracks` (the code already consumes `relationships.catalog`, `:309-311`). Verify it read-only (**R5**). Verify staging with one slice read per song. Fix the pager to re-apply params, and take the count from `meta.total`. Add a latency gate (≤ 3 s for a 34-track playlist, measured in W5). Strictness is **U6**. |
| **G4** | Data | **06 is stale on Favourite playlists; the live check supersedes it.** | A06 §5.3 calls `inFavorites` "unverified". CF (written earlier, run **live**, read-only) found: `extend=inFavorites` is required (0/239 without it, 239/239 with it; CF:44-45); the undocumented `filter[inFavorites]=true` works (CF:49); the user has 2 favourites, Favorite Songs (16) and PAPER LANTERN Ep. 1 (34) (CF:8-11, :89-90); and Favorite Songs collects liked songs (CF:13). | Use CF §5's recipe. Record that Like **does** feed the tab through Favorite Songs, which partly reconciles S01:222 with R:226. Plan placeholder and mosaic cases: 123 own playlists have fixed 1200 px URLs, 5 are on `blobstore` (rejected by the allowlist), 6 have no art (CF:98-103). |
| **G5** | Assets | **Artwork sizes are too small in the design.** | R:228 and S01:193 say 600 px. At k = 2 the explorer centre card is 680 px and the Up next cover 760 px (RA:23). A03 Q2 and A05 §5.3 proposed `ceil(340·k)` / `ceil(380·k)`. | Adopt RA:25-30, 43-52: request **1200** for the two big covers and their ±1 neighbours, **600** for side cards and mosaic tiles, **240** for row covers, and **64 px** from cache for the ambient blur. Never 3000 (the 2 MiB cap). Upscale ≤ 1.5×, otherwise use a matted cover. `bgColor` fills the card while it loads. |
| **G6** | LED acceptance | **"~360 ms wake" is not what the alive engine does.** | R:133 and R:242 inherit it from the pre-alive CSS (`KF:123` `WAKE = 'background 360ms …'`; CC:59, CC:993). The engine (RC; BS:500, :509) rises with τ **55 ms** (body), **10 ms** (cursor) and **40 ms** (buttons), so the body reaches 95 % in about 165 ms. The Wake front moment lasts 520 ms (S02:131). | Restate acceptance 9 as **"matches the oracle"** (A2). If the user prefers the slower 360 ms feel, that's a hands-on note, not a spec change. |
| **G7** | LED acceptance | **The 3 Hz rule against the Head shake.** | S02:107 and R:176/R:242 say nothing modulates above 3 Hz. The Head shake moves a red gaussian (w 0.9) ±1.6 segments at **3.2 Hz** (S02:165; RC:350), so a segment next to the cursor peaks about twice per cycle (up to ~6.4 Hz) for 700 ms. S02:167 exempts it as movement. The new moments pass: scatter bumps are 260 ms (≈1.9 Hz), half-wash is monotone, embers have 2.4–4.0 s periods. | Keep it verbatim (AL ports RC). Record it as ruling **D30** "motion exemption" in K2, and check at the LED tour that it doesn't read as flashing. |
| **G8** | Knob copy | **The Tracks neighbour titles are wrong under Sonos native shuffle.** | The master shows `Next: {title}` / `Prev: {title}` (R:119; BS:952). A05 §5.3 would read `get_queue(P, 1)`. Under native `SHUFFLE*` the next track isn't row P+1, and the order may be unobservable (A06 §3.2 H1). Previous is refused in shuffle (`sonos.py:163-164`, via A06). Also, at the last row with `REPEAT_ALL`, BS toasts "End of queue" (BS:673) but Sonos wraps. | In native shuffle, show `Next: shuffled` (proposed copy) and "Previous unavailable" (KM:457). With `REPEAT_ALL` at the last row, show `Next: {row 1}` and allow the skip. This is moot if **U4** picks companion shuffle. |
| **G9** | Overlay behaviour | **Overlay lifetime isn't specified.** | There's no idle timeout in the design or in v6 (no match in `control_center/`). The explorer and Up next never take focus, so the picker's focus-loss dismissal doesn't cover "the user walked away". Keyboard can't reach them (non-activating). | Close the explorer or Up next on: knob disconnect (A05 §5.7); Sonos group change; external foreground change; **session lock, suspend or display off** (`WTS_SESSION_LOCK`, `PBT_APMSUSPEND`); a full-screen app (`SHQueryUserNotificationState` 3/4, as the floating knob does); and **60 s without knob input** (proposed; the knob goes back one level). The picker is unchanged. |
| **G10** | State, Sonos | **Play resets shuffle in the prototype.** | `playItem` sets `shuffle:false` on every Play (BS:769). With native Sonos shuffle that means writing `SetPlayMode`, a setting the user may have chosen in the Sonos app. With companion shuffle it costs nothing. | Part of **U4**. |
| **G11** | Docs | **ALIVE.md contradicts the combined release.** | AL:386 says "Not touched: … LCD rendering". AL:419 says "Keep `render_lcd` byte-identical". AL:421 says "up to 60 fps" (G1). | Amend in K2. |
| **G12** | Recovery | **Explorer while Sonos is down.** | A05 D9 refuses to open it. KM:381 and S03 say Browse works without Sonos. | Open it when Apple Music is available, with Play and Play next `dim` and meta "Sonos unavailable". Up next refuses, because it needs the queue. |
| **G13** | Error copy | **No design copy for the new actions' failures** (Play next, Seek, Shuffle, Like, Snap, playlists). | R and S01 draw only the happy path. BS is optimistic everywhere (A01 §5.1). | A single copy sheet (§3.3) for one approval pass. |
| **G14** | Parity | **The Python LCD mirror can't do the firmware's tabular digits or text shadow by default.** | `lcd_preview.py` renders with PIL, which has no raqm or `tnum` (A05 §5.1 notes the same for Archivo). The floating knob must match the knob. | Mirror whatever firmware chooses: T1 (a remapped `.tf` cmap via fontTools; `gen_lvgl_font.py` needs the same trick) or T2 fixed cells, plus the shadow twins. This goes in WP1. |
| **G15** | Release mechanics | **Release mechanics aren't planned in 01–06.** | They need a cc5.4 `PROFILES` entry in `tools/nanod_cc5_tooling.py` (MEM:81); `check_nanod_cc5.py` generalised to cc5.4 (AL §11.7); `Build-Desktop.ps1` v7 and a frozen `smoke-test.json` (`Install-Desktop.ps1` requires it, MEM:27); rollback to `desktop-dist-v6` and the cc5.3 firmware backup; and `ACCEPTANCE.md` (last touched 2026-09-22). | WP9 (§4.2). |
| **G16** | Accessibility | **No reduced-motion behaviour.** | The design is silent. | Honour "Show animations in Windows" (`SPI_GETCLIENTAREAANIMATION`): replace flies and staggers with 180 ms fades. Use BS's legend labels (BS:943-989) as accessible names. Low priority. |

Categories checked with **no new gap**:
- **Modes:** all seven are covered, plus idle, notice and offline (A01 §3).
- **Buttons:** the hold on buttons 2–4 is ignored (A04 §10.15).
- **LED targets:** the Seek lap is shown awake, and Up next uses the 20-entry window (A02 F14).
- **Icons:** the LCD vocabulary (A04 §3.3); overlay exports at 16/18/20/34 px × k (A05 §5.2.9).
- **Tray:** covered (A05 §8).
- **Tests:** about 150 controller tests are rewritten (A05 §11.2). New suites: A05 §11.3, plus the BS-`draw()` oracle (A02 §9).

### 1.4 Still unverified, and how to verify each

| Id | What | Kind | Method | Needs the user's go-ahead because |
|---|---|---|---|---|
| R1 | Metadata on companion-added queue rows (`creator`, `album`, `albumArtURI`, track number) | read-only Sonos | A06 §8 R1 | it reads their system |
| R2 | Seek capability while playing and paused | read-only Sonos | A06 §8 R2 (the user starts and pauses in the Sonos app) | the user acts |
| R3 | Native shuffle shape (H1 or H2) | read-only Sonos | A06 §8 R3 (the user toggles shuffle in the Sonos app) | the user acts |
| R4 | Catalog-song batch: `inFavorites`, `trackNumber`, `artwork.width` | read-only Apple | A06 §8 R4, third bullet. The playlist part is **done** (CF) | their account |
| **R5** (new) | `include=catalog` on library album and playlist `/tracks`; resolve timing for the two favourites | read-only Apple | a GET-only probe like CF's `GetOnlySession` | their account |
| W1 | Play next: 2 songs at P+1, P+2 while paused, then removed | reversible **queue write** | CP §5; A06 §8 W1 | it changes their queue |
| W2 | Seek ±20 s on a playing queue track | **audible** | CS §5; A06 §8 W2 | playback moves |
| W3 | `ReorderTracksInQueue` on an upcoming row, and around the current row | reversible queue write | A06 §8 W3 | it changes their queue |
| W4 | Like: PUT value 1 → GET → the user checks the star in the Music app → DELETE → GET | reversible **favourites write** | CL §5; A06 §8 W4 | it changes their favourites (and may add to their library) |
| **W5** (new) | Play "Favorite Songs" end to end; measure the resolve + stage + start time | **replaces their queue** | in the hardware window | irreversible, apart from the encrypted recovery snapshot |
| S1–S5 | Overlay frame time and memory, snap on real windows, toast placement, tray theme | supervised desktop | §4.4 | it moves their windows (S3) |
| H1–H6 | Everything on the knob | hardware window | §4.5 | a flash |

---

## 2. Contradictions and resolutions

### 2.1 Inside the master (README against specs against prototype)

| # | Contradiction | Sources | Resolution |
|---|---|---|---|
| C1 | Paused Play on Home: **green** breath, against "only button 4 is ever green" | Green: R:138, S01:100, S02:77, S02:106. Only 4: R:70, R:234, S01:47. BS renders it **warm** (BS:504-508, 944). CC:1105: "At home nothing is green" | **U1** |
| C2 | Like "feeds the explorer's Favourite playlists" against "It does not appear in Favourite playlists" | S01:222 and stale BS:376, against R:226 | R wins for the mechanism (it rates a song). CF:13 shows the song does land in the favourited "Favorite Songs" playlist. The toast `Added to Favourites · {t}` (BS:662) stays accurate |
| C3 | Play next via `EnqueueAsNext=1` | R:224, S01:221 | Incorrect in normal play. Use `DesiredFirstTrackNumberEnqueued = P+1+i` with `EnqueueAsNext=0` (A06 §0, §1.4; CP) |
| C4 | Overlay art "600 px" | R:228, S01:193, BS:377 | 1200/600/240/64 (G5) |
| C5 | Seek handle "≈ 60 %" | R:95, S01:60 | The path puts it at x 15.5/24 ≈ 65 % (BS:403). **The path wins** |
| C6 | Screen-change distance: ±20 px, "±16–20", or 16 | R:126, S03:161; S01:129; BS:649 | **20 px** (README precedence; `cc_display.cpp:87` is already 20). Only the text layer slides (BS structure, A04 §2.1) |
| C7 | Explorer/Up next turn: 420 ms against 440 ms + 45·a / 40·a ms delays | R:187, S01:191; BS transition strings (A03 §2.6) | 420 ms with no delay on turns; delays only on open and source switch (A03 Q1) |
| C8 | Up next backdrop "same as the explorer" against 0.55 / 0.45 | S01:197; A03 §1.2 | The prototype's numbers |
| C9 | Toasts over an open overlay | R:209, S01:254, against BS:662, :691 | **No toast while a scene is open.** The heart pop and the `Shuffle on` / `In order` line carry the feedback. Exit toasts start after close |
| C10 | "Never show the next song's title before the skip" | S03:147, against R:119 | R wins (G8 limits it under shuffle) |
| C11 | Windows button 1: red Cancel | S02:78; S03 buttons table; S04:10 — against R:80 | **Back**, `nav` warm. The `stop` tone stays only for v6 hosts |
| C12 | Back toast | S04:80 "Cancelled · focus restored", against BS:829 | `Back · focus restored`, only when nothing was snapped |
| C13 | Toast place and hold | S04:79: centre, 1.5 s; R:208 and S01:253: bottom centre (top 588), 1.8 s | R |
| C14 | Picker glass pane, 480 × 300 cards | S04 | Superseded (R:20): full-screen blur, 400 × 250 |
| C15 | LED model | S03:167-213 (L1–L4 white, targeted colour, amber 255,150,30 / red 255,55,35, instant/260 ms damping) against S02 | S02 supersedes (S02:10), with the user's colours on top |
| C16 | Volume amber/red body level | S01:134 and BS:997 give 0.62; S02:70 and KM:505 give semantic class 2 = 1.0 | **U8** |
| C17 | Volume colour gate | BS:997 gates on value and position; V4 on position only | BS. It matches the user's "80–90 % amber, ≥ 90 % red" and differs only at 79 and 89 (A02 F2) |
| C18 | Ambient tint families | S02:144 "Windows/Recent"; S01:158 "Explorer / Windows / Up next"; BS:521 all four | BS: recent, explorer, Up next, windows |
| C19 | Recently Added first entry | S03:30 item 1; BS:596 `rIdx: 1` (item 2) | Item 1 (a BS artefact) |
| C20 | Recently Added paging and More | S03 pages + More; BS a flat list | **U5** |
| C21 | "~360 ms wake" | R:133, R:242 against the engine | Oracle match (G6) |
| C22 | "Nothing above 3 Hz" against the Head shake | R:176, S02:107 against S02:165 | Motion exemption, D30 (G7) |
| C23 | "Windows then treats the pair as a Snap group" | S01:249; BS:373 | No public API guarantees it. Keep it out of the copy (A03 Q19) |
| C24 | `ShowWindow(SW_RESTORE)` before placing | S01:247; BS:377 | It **activates** the target and would dismiss the picker. Use `SW_SHOWNOACTIVATE` / `SetWindowPlacement` (A05 §6.4 step 3) |
| C25 | "All three overlays never take focus" | R:180 | The explorer and Up next are truly non-activating. The picker keeps its activatable host (`CAROUSEL.md` deviation 6), because Switch and Back need the foreground |
| C26 | Idle icon row words | S03:108 ("Play/Pause, Browse, Win, Tracks") against the new map | `Play/Pause · Browse · Tracks · Win`. The master names don't fit 46 px (A01 Q2) |
| C27 | Footer dim ink #5A5A5A against #4A4A4A | BS:938 against S03:51 and `cc_presentation.h:96` | #5A5A5A (hi-fi prototype, §3 delegated) |
| C28 | Main window, tray menu and recovery cards | R §7.2, CC §04 | The user's standing decision is no main window (DESKTOP.md). **U14** covers the Settings status strip |
| C29 | Hint `[3] Playlists` against tab `Favourite playlists` | BS:1077, S01:174 | Keep both; the hint is deliberately short |

### 2.2 Master against the user's standing decisions

| Master says | Where | Standing decision | Status |
|---|---|---|---|
| Warm follows the time of day (3000 K → 1900 K) | R:131; S02 §6; BS:487 | Warm is **#FF8424 all day**; time of day only dims resting brightness | AL:36, AL §8.3. **But** AL's constant 255,189,105 outputs **#FF8224** through AL §9's sRGB EOTF (A02 §2.3). Fix in K2: 255,190.45,104.97, or accept #FF8224 |
| Amber 255,118,0 / red 255,24,0 | R:139-140; S02:54-55 | Amber **#FF3A0A**, red **#FF0000** | AL:39-40. AL's AMBER 255,130,59 outputs **#FF390B**; 255,131,56 gives exactly #FF3A0A (A02 §2.3). Fix in K2 |
| Offline: 12 amber marks, 0.15–0.5 pulse while reconnecting | S02:81 | Drain → amber marks → native profile lights on native input | AL D5, §8.1 |
| Offline LCD "Resumes at Volume" | KM:369 | Native controls take over | Keep "Native controls active" (`cc_display.cpp:1317-1321`) |
| Main window with a live mirror | R §7.2 | Tray plus floating knob only | Keep (U14) |
| One full-screen picker blur with a 6 % sheen | S01 §7 | "Full screen or not at all"; Frosted / No background in Settings (`ui.py:117`) | Consistent on full screen. Sheen and setting scope: **U9** |
| (silent) | — | The desktop floating knob runs the same choreography | AL §10.3. The new moments come free once `feedback.moment` exists |
| (silent) | — | Every animation at maximum refresh (MEM:56) | Conflicts with AL:421 (60 fps) and the CPU overlay design: **U10** |
| (silent) | — | One combined release | AL:386 and :419 say LCD is untouched (G11) |

### 2.3 Master against ALIVE.md (the amendments K2 must carry)

A02 §7 (F1–F24) and §9 list these item by item. In short:
1. **Class 2 semantic** 1.0 → 0.62, and S 0.81 in every role. This follows **U8** (AL:152).
2. **Paused Play** per **U1** (AL:172 makes it green today).
3. **Windows button 1 is Back:** `stop`/red Cancel is no longer used by the master (F8).
4. **New effects** `half` (900 ms, FG) and `scatter` (700 ms, FG), and `bloom` with a colour. Ported verbatim from BS:541-543, including half's `addB` without `amp` (F18). Scatter takes a deterministic xorshift32 seed (F17).
5. **Triggers need `feedback.moment`** (`queued`, `shuffle`, `like`, `unlike`, `snap` + `side` + `color`). Without them AL §6.4 would **wash** on Play next and on a snap, and **green-bloom** on Like and Shuffle (A02 §6.10). No target flash with a moment (F13).
6. **Families** `explorer` and `upnext`, and Seek's `transport ↔ lap` change counts as MODE (F15, F19). The **Up next classes** P 0.14 and N 0.70 on absolute `ring.now` (F14).
7. **Buttons:** `lit:"on"` gives WARM 1.0, `lit:"off"` WARM 0.30, heart + on gives PINK 1.0, and a colour + on gives `sat(color)` 1.0. Resting is 0.12 if the awake level is ≥ 0.5, else 0.04 (F16).
8. **Tint** on recent, explorer, upnext and windows. D7's wash extends to the explorer; Up next Play and a warm-app Switch follow §3's LED rulings.
9. **Scope text** (AL:386, :419, :421), and the **palette fix** (§2.2).
10. **Acceptance wording:** the wake (G6) and the 3 Hz motion exemption (G7).
11. A **second oracle** on BS `draw()` (BS:485-579), next to the RC oracle.

### 2.4 Between the analysis files (the resolution this summary adopts)

| # | Disagreement | Adopted |
|---|---|---|
| A1 | Knob mirrors reuse the `recent` layout (A05 §2.7) or get new `explorer` / `upnext` tokens (A04 §2.3) | **New tokens.** Reusing `recent` breaks the slide direction (Up next → Tracks would enter from the right), and `cc_alive_family` defaults unknown layouts to Home |
| A2 | Button state on the wire: per-button `tone`/`accent` plus a "40-bit mask" for Up next (A05 §2.7, §4), or `buttons[j].lit` + the existing `buttons[j].color` + `ring.now` + `feedback.moment/side/color` + `ring.style:"lap"` (A02 §8; A04 §5) | **A02/A04**: one set of fields for both the LCD ink and the LEDs |
| A3 | Hold: firmware or host timing (A05 §2.3 a/b) | **Firmware `kh`, plus `ks` in `ready`.** A04 §6.1 shows host timing produces false Homes |
| A4 | Seek `T_end` = D−1 (A01 §2) or D−3 (CS:178; A04 §7) | **D−3** |
| A5 | Explorer tab re-entry immediately (A05 §5.6) or at 190 ms (BS:808) | **At 190 ms** (G2) |
| A6 | `inFavorites` unverified (A06 §5.3) or verified live (CF) | **CF** |
| A7 | Art size `ceil(340·k)` (A03, A05) or 1200/600/240 (RA) | **RA** |
| A8 | Explorer with Sonos down: refuse (A05 D9) or browse (KM:381) | **Browse, with Play dimmed** (G12) |
| A9 | Snap restore: `SW_RESTORE` (A03 §4.9, citing the design) or non-activating (A05 §6.4) | **Non-activating** |
| A10 | Meaning-based wire tokens (A04 §3.2) and the v7 → cc5.3 downgrade table (A05 D8) | **Both.** They cover opposite host/firmware pairings |

---

## 3. Decisions

### 3.1 Decisions the user must make

| # | Decision | Options | Recommendation |
|---|---|---|---|
| **U1** | **Paused Play button** (Home, button 1) | (a) Breathe **green**: the spec (S01:100, S02:106), already built (AL:172). (b) Breathe **warm**: the prototype (BS:504-508), and it keeps "only button 4 is green" (R:234, CC:1105) | **(a)**, confirmed at the LED tour. The flip is one flag in both engines |
| **U2** | **Up next button 3: Like** (this writes to the user's Apple Music account) | (a) **Like** = `PUT /v1/me/ratings/songs/{catalogId}` value 1, un-like = `DELETE` (never −1). Liked songs land in "Favorite Songs", which shows in the tab (CF:13). The consent copy (`credentials.py:245`) and the docstring (`apple_music.py:1`) must change. (b) Replace it with **Play next for the highlighted row** (`ReorderTracksInQueue`; no Apple write; A06 §5.5). (c) Like where the row is a catalog song; the heart is dim elsewhere | **(a) + (c)**, after live test **W4** passes. Fall back to (b) only if W4 fails |
| **U3** | **Live verification of Play next on the user's Sonos** (W1 changes their queue; reversible) | (a) Approve W1 now: 2 songs while paused, verified, then removed (CP §5). (b) Build behind a flag and verify in the hardware window. (c) Drop Play next from this release | **(a)**. It de-risks the only design mechanism that was wrong (C3). W2 (Seek, audible) and W3 (reorder) are separate approvals |
| **U4** | **Shuffle semantics** in Up next | (a) **Native Sonos shuffle**: one call, but it may reshuffle played rows, the order may be invisible (H1), Play next must be refused while it's on, and Play must write `SetPlayMode` to honour BS:769. (b) **Companion reorder** of the upcoming rows with `ReorderTracksInQueue`: exact design semantics, about 2 SOAP calls per moved row, a restore record; other controllers see a reordered queue with shuffle "off". (c) **Hybrid**: (b) for ≤ 60 upcoming rows, (a) above that | Run read-only **R3** first, then **(c)**. Sub-rules: Shuffle off keeps a Play-next block right after the current track (not at the end, A06 §3.5a), and Play from the knob starts unshuffled (BS:769) |
| **U5** | **Recently Added paging** | (a) Flatten the loaded pages into one list with prefetch; retire More (A05 D1). (b) Keep 10-item pages + More on the knob; the explorer shows a flat list. (c) Cap at the 50 most recent | **(a)**. It matches the prototype and makes the explorer and the knob share one index |
| **U6** | **Playlist playback strictness** (one unplayable track) | (a) All-or-nothing, as today ("Nothing was queued."). (b) Skip unplayable tracks and say `Playing 33 of 34`. (c) Strict for albums, lenient for playlists | **(c)**. Playlists come into the main flow with the explorer (G3) |
| **U7** | **Favourite playlists tab content** (the user has 2 favourites today) | (a) Favourited only, as designed; empty state "No favourite playlists yet" (CF:141). (b) Favourites first, then the user's own playlists (134). (c) All 239 library playlists, favourites first. "Pinned" is not possible with any option (A06 §5.3) | **(a)**. It is exactly the design, and favouriting in the Music app adds more (with a few minutes of sync lag) |
| **U8** | **LED values the user tunes by eye** | Volume amber/red body: (a) **0.62** like the warm body (S01:134, BS:997), shoulder 0.81; (b) **1.0** (AL today). PINK for Like: (a) the design's 255,40,90 (≈ #FF051A at full); (b) choose from 3 candidates on the ring, as with WARM/AMBER/RED | Body **(a)**, confirmed at the tour. PINK **(b)** |
| **U9** | **Picker background** (the user was undecided, MEM:35) | (a) Keep the Frosted / No background setting and add the 6 % sheen to Frosted. (b) Frosted only, as designed, with the sheen. (c) Keep v6 exactly (no sheen) | **(a)**. The explorer and Up next are always frosted (their ambient layer needs the blur), whatever this setting says |
| **U10** | **Desktop refresh target** (decide after the refresh study and the G1 spike) | (a) **240 Hz everywhere**: needs the GPU path for explorer/Up next covers and rows; more build risk. (b) 240 Hz for the picker, snap fly, toasts and floating knob; **≥ 120 Hz** for the explorer and Up next. (c) A 60 Hz floor everywhere | **(b)** as the release gate, **(a)** as the goal if the spike holds 4.2 ms |
| **U11** | **Optimistic or confirmed Play** (explorer, Up next, Recently Added) | (a) Confirmed, as today: the knob waits on "Starting…" with Back disabled. (b) Optimistic, as in BS: Home and Wash at once, a shake on a later failure. (c) **Hybrid**: the overlay closes at 380 ms and the knob goes Home at once with status "Starting…" and the Working comet; Wash on `ok`; Head shake + "Didn't start" on failure; Home Play/Pause is disabled while pending | **(c)** for music. Switch stays confirmed; it takes 2–5 ms (MEM:35) |
| **U12** | **Snap moves the user's other window** (no undo exists) | (a) As designed: when the picker closes with one side filled, place the previously focused window on the other half (R:205). (b) Move only windows the user snapped | **(a), at close only**, not at the first snap (A03 Q14). After a pair closes, focus the side snapped last |
| **U13** | **Hardware windows** | (a) One window at the end (flash, checks, LED tuning, end to end). (b) Add an early, non-release LED-tuning flash to settle U1/U8 and the drive before the UI is finished | **(a).** The tour tool carries runtime candidates for PINK and the body level, so tuning fits in one window |
| **U14** | **Recovery surface** without a main window | (a) Add the 3-column service strip (Knob / Sonos / Apple Music, with `Set manual IP…` and `Renew sign-in…`) to the top of Settings (A05 §9.2). (b) Nothing new: tray, balloons and knob copy only | **(a)** |

### 3.2 Rulings delegated to the build (adopt unless the user objects)

| Area | Ruling | Source |
|---|---|---|
| Seek | `T_end = D−3`. The displayed clock is frozen at the target while seeking. A still-debouncing target is **flushed** on an explicit exit. A track change exits Seek and drops the target. Seek is dim when `SeekTime` is missing or the duration is unknown | CS:178, :186, :202-208 |
| Knob LCD | Slide 20 px, text layer only. Dim ink #5A5A5A. Text shadow option B (12 twin labels, hard 1 px at 80 %, behind a compile flag; dropped if `lvglMinFree` < 30 KB). Tabular 48 px font T1 (+5 KB). The four mirror headings may run to r 112 (143 px chord), keeping their tracking. Windows tile fallback: `sat(app colour)` with a white Medium letter. Snap footer ink: `sat()` of the app colour. Icon masks trimmed per use (−8.8 KB). Legacy tokens `home`/`more`/`cancel` kept for v6 hosts | A04 §2, §3, §12 |
| LED | Tracks Prev cursor is 52 (not BS's 53). The skip sweep starts from the previous cursor. A Switch to a warm app **green-blooms** (AL today). Up next Play **washes** in the jumped-to album colour. No target flash with a moment. Scatter uses xorshift32 and rejects seeds with a minimum spacing under 3 segments. The Coming-online LCD fade stays omitted (AL D6) | A02 F9-F13, F17 |
| Overlays | Turn 420 ms with no delay. Clicks are eaten; only the centre card or focused row acts. The floating knob hides while the explorer or Up next is open. Toasts go on the foreground window's monitor. The picker host grows to the monitor and eats clicks. Overlay lifetime per G9. Reduced motion per G16 | A03 Q1, Q12, Q13, Q18; A05 D10 |
| Data | Up next context from a provenance ledger plus a heuristic, with the title `Sonos queue` for foreign queues. Playlist mosaic from the first 4 distinct albums (fewer than 4: one full-bleed cover); its ring colour is `dominant()` of the first cover, seeded by `bgColor`. Play next capped at 100 songs. Up next reads a windowed queue (±10 around the focus). Art sizes per G5 | A06 §4.3, §6; A03 Q6; RA |
| Buttons | The hold fires only for physical slot 0 (`kh`). F24 fires only when the slot's icon is `win` (Home). The host skips logical 3 on Home only, and the firmware tags `kd` with `hid:1` | A04 §6.1-6.2; A05 §3, R1 |
| Tray | Handle `WM_SETTINGCHANGE` "ImmersiveColorSet", with a 30 s poll as a backstop | A05 §8 |
| Capability | `presentation: 5` + `alive.version: 1`. One parser/fixture change set carries both the ALIVE fields and the v5 fields | A04 §5.2; A02 §9 §1 |

### 3.3 Error and pending copy sheet (G13; one approval pass)

The design has none of this copy. Knob meta lines are 12 px and must fit about 170 px. Toasts never show while an overlay is open.

| Action | Condition | Knob | LED | Toast | Basis |
|---|---|---|---|---|---|
| Play next | pending | meta `Queueing…` | Working comet | — | A01 §5.2 |
| Play next | ok | meta `Queued next` for 1.5 s | Sweep from segment 0 | `Queued next · {album}` | S01:221 |
| Play next | the source isn't the queue | `Not playing from the queue` | Head shake | `Not playing from the queue · use Play` | A06 §1.8 |
| Play next | Sonos native shuffle on (unless U4 = b/c) | `Shuffle is on` | Head shake | `Shuffle is on · turn it off to play next` | A06 §1.6 |
| Play next | nothing playing | `Nothing playing · use Play` | Head shake | same | A06 §1.8 |
| Play next | rolled back / partial / song changed | `Couldn't queue` (#FF8A7A) | Head shake | `Couldn't queue {album} · nothing added` / `Partly queued · check the Sonos queue` / `Song changed · try again` | A06 §1.8 |
| Play (a playlist) | unplayable track (U6 = b/c) | `Playing 33 of 34` | Wash | `Playing {name} · {room}` | G3 |
| Seek | unavailable (radio, AirPlay, TV, line-in, no duration) | button 3 dim | — | — | CS:202-203 |
| Seek | 701/711/timeout | stays in Seek at the target | Head shake | — | CS:207 |
| Shuffle | the source isn't the queue | button 2 dim | — | — | A06 §3.5c |
| Shuffle | the queue changed before a restore | `Queue changed · order kept` | Head shake | — (overlay open) | A06 §3.4 |
| Like | row not a catalog song | heart dim | — | — | A06 §5.2 |
| Like | 401/403 | the sign-in-expired state | Head shake | tray balloon | CL §4 |
| Snap | hung / elevated / minimum width | `{App} isn't responding` / `Couldn't move {App}` / `{App} can't fit half` | Head shake | — | A05 §6.4, §6.7 |
| Up next | the source is AirPlay, radio or TV | the overlay doesn't open; meta `Up next is on the playing device` | Head shake | — | RP:26 |
| Explorer | no favourite playlists | card `No favourite playlists yet` | — | — | CF:141 |
| Explorer | Sonos unavailable | opens; Play dim; meta `Sonos unavailable` | — | — | G12 |

---

## 4. Build plan for the combined release (cc5.4 + desktop v7)

### 4.1 Contract documents (write and freeze before code)

| Id | Document | Owner | Content | Built from |
|---|---|---|---|---|
| K1 | `firmware\PRESENTATION_V5.md` | WP0 | The v5 frame, replacing P4 whenever the knob advertises `presentation: 5`: layouts `seek`/`explorer`/`upnext` with depths (home 0, tracks/seek 1, recent 1+page, windows 5, explorer 30+tab, upnext 30) and `groupOf(seek) = tracks`; the token table; tones on/off/colour and inks; `buttons[j].lit/.color`; `ring.style:"lap"` (index/count in seconds); `ring.now`; `feedback.moment/side/color`; the LCD tree changes (footer out of `content`, content opacity, Windows art fade 560 ms); Seek boxes; heading rule; twins; fonts (`:` + `cc_font_48t`); `kh` and `ks` in `ready`; the F24 icon gate; the byte budget; `frames_v5.json`; the host/firmware compatibility matrix | A04 §2-6; A02 §8; A01 §8 |
| K2 | `firmware\ALIVE.md`, revision 2 | WP0 + WP2 | §2.3 of this summary, A02 §9, D19-D30, the U1/U8 outcomes | A02; this file |
| K3 | `app\CONTROL_CENTER_V5.md` | WP0 | The per-mode grammar, Back/hold, modes and sub-states, **the re-entry helper and its timing (G2)**, timers (A01 §4.2 + A05 §2.5), the effects contract (A05 §2.6), the confirmation policy (U11), the toast service rules and catalogue, the §3.3 copy, the service contracts (Sonos `play_next`/`seek`/`shuffle`/`queue_window`/`jump`/`move_next` and the `_state` additions; Apple `_send`/`like`/`unlike`/`ratings`/`favourite_playlists`/`catalog_songs`, `include=catalog`, the pager fix), the provenance ledger, invalidation (`runtime.py:1165`), recovery and the Settings strip, simulator fakes | A05; A06; CS; CP; CL; CF |
| K4 | `app\DESKTOP_STAGE.md`, plus amendments to `CAROUSEL.md` §12, `FLOATING_KNOB.md` and `APP_ICON.md` | WP0 | Stage engine and scenes, host roles, frost recipes, ambient layer, geometry and motion tables (A03 §2-4), snap tray, fly and placement recipe (A05 §6.4), focus contract, art sizes and caches (RA), **refresh targets and how they're measured (U10)**, the memory budget, lifecycle (G9), suppression and capture exclusion, toasts | A03; A05 §5-7; RA |
| K5 | `app\ACCEPTANCE.md`, v7 section | WP9 | R §9 mapped to the gates in §1.1 and §4.4 | this file |

### 4.2 Work packages (disjoint write ownership)

| WP | Scope | Owns (exclusive write) | Consumes | Exit gate |
|---|---|---|---|---|
| **WP0** | Contracts | K1–K4 (docs only) | decisions U1–U14 | review sign-off |
| **WP1** | Firmware LCD and its Python twin | `src\cc_display.cpp/.h`; `control_center\lcd_preview.py`; `harness` harness and `cc5_report.py` render fixtures | WP3 enums; WP9 masks and fonts | A4 |
| **WP2** | LED engine, both ports (continues the running ALIVE engine workflow) | `src\cc_alive.cpp/.h`, `src\cc_lights.cpp/.h`; `control_center\alive_lights.py`, `preview_lights.py`; `tests\js\alive_oracle.cjs` (+ the BS-`draw()` oracle), `alive_golden.cjs`; `tests\tools\make_alive_sequences.py`; `tests\test_alive_*.py`; `harness\alive_tests.cpp` | K2; the ALIVE base passing its own gates first | A2 |
| **WP3** | Wire, parser and fixtures (ALIVE §3 fields and v5 fields in **one** change set) | `src\cc_presentation.h`, `src\cc_frame_parse.cpp`; `control_center\presentation.py`, `device.py`; `tests\fixtures\frames_v5.json`; `parse_tests`; `tests\test_cc_contract_v5.py`, `test_cc_device.py` | K1 | A3 |
| **WP4** | Firmware integration and input | `src\hmi_thread.cpp/.h` (ALIVE HMI integration **and** the `kh` long press), `src\com_thread.cpp` (`kh`, `lim`), `src\control_center.cpp` (`ks` in `ready`, F24 icon gate, capability 5, enter-time diag), `src\lcd_thread.cpp` (render-time diag only) | WP2, WP3 | A5, A6 |
| **WP5** | Companion state machine | `control_center\controller.py`, `runtime.py`, `simulation.py`; the controller/stage3/lookahead/enter-frames/touch/warmup/runtime-colours tests | WP3 (`presentation.py`); WP6 interfaces (fakes first) | A1 |
| **WP6** | Services | `control_center\sonos.py`, `apple_music.py`, `credentials.py` (consent copy), `artwork.py` (sizes, unscrimmed covers, `_SCRIM_STOPS` .60/.72/.92/1.0, allowlist); a new `control_center\queue_context.py` (ledger); `tests\test_cc_music.py` and the other service tests; `work\probes\*` (dry-run by default) | K3 | A1 + L gates |
| **WP7** | Stage core, picker V2 and snap | `control_center\carousel.py`, `carousel_render.py`, `windows.py`; `CAROUSEL.md`; `tests\test_carousel_*.py`, `test_cc_windows.py`, `test_window_labels.py` | K4 | milestone **M7a**: the stage-core API (scenes, parametric frost, a non-activating click-eating host role, the toast service) with **every existing carousel test green**; then picker V2 and snap → A1, S3 |
| **WP8** | Music scenes | new `control_center\scene_music.py`, `render_music.py`, `music_overlay.py` (adapter); `tests\test_scene_music.py` | M7a; the G1 spike result; WP6 data; WP9 overlay icons | A1, S1, S2 |
| **WP9** | Tooling, assets, packaging, docs | `harness\export_handoff_icons.cjs`, `gen_lvgl_font.py`, `font_tests.py`; generated `src\cc_icons.cpp/.h` and `src\fonts\*` (48 px with `:`, `cc_font_48t`); `assets\handoff-icons`, `assets\lcd-icons` (@2x/@3x); overlay icon exports; `tools\nanod_cc5_tooling.py` (the cc5.4 `PROFILES` entry), `check_nanod_cc5.py` (cc5.4), `tools\nanod_alive_tour.py` (the master moments and runtime candidates); `Build-Desktop.ps1`, `Install-Desktop.ps1`; `tests\test_packaging.py`; `README.md`, `DESKTOP.md`, `ACCEPTANCE.md` | K1, K4 | A6, A7 |
| **WP10** | Desktop shell | `control_center\ui.py` (suppression reasons `explorer`/`queue`, capture exclusions, wiring `MusicOverlayAdapter`, Settings strip and labels), `standalone.py` (tray `WM_SETTINGCHANGE`, menu sub-line), `overlay.py` and `knob_face.py` (floating knob: new tones and colours, frame rate per U10); `tests\test_cc_ui.py`, `test_cc_tray.py`, `test_cc_knob_face.py` | WP5, WP7, WP8 | A1, S4, S5 |

Conflict rules:
- `hmi_thread.cpp` has **one** owner (WP4), even though ALIVE's integration workflow planned to touch it.
- `carousel.py` belongs to WP7 only. WP8 builds on its API and never edits it.
- `ui.py` belongs to WP10 only.
- Generated icons and fonts are written only by WP9.
- `lcd_preview.py` stays with its firmware twin in WP1.

### 4.3 Order and dependencies

```
Phase 0  decisions U1–U14 · read-only checks R1–R5 · consented W1/W3/W4 · refresh study lands · K1–K4 frozen
Phase 1  WP3 fixtures ─┬─► everyone builds against frames_v5.json
         WP9 assets ───┤   WP2 master additions (after the ALIVE base gates pass)
         WP6 adapters (fakes) · WP7a stage core (no behaviour change) · G1 GPU spike
Phase 2  WP1 LCD (WP3+WP9) · WP4 fw integration (WP2+WP3) · WP5 controller (WP3+WP6 APIs)
         WP7b picker V2 + snap (WP7a) · WP8 music scenes (WP7a + spike + WP6 + WP9)
Phase 3  WP10 shell integration → simulator end to end → packaging (WP9)
Phase 4  gates A (automated) → S (supervised desktop) → L (live services, consented)
Phase 5  hardware window H (go-ahead; beep cues; rollback ready)
```

Critical paths:
- **Firmware:** K1 → WP3 → WP1 + WP4 → PlatformIO build → H.
- **Desktop:** K4 + G1 spike → WP7a → WP8 → S1.

The music overlays are the largest and least certain block; they cannot start until the spike settles the rendering approach.

### 4.4 Verification gates

| Gate | Checks | Needs |
|---|---|---|
| **A1** | The Python suite green, including about 150 rewritten controller-driven tests (A05 §11.2) and the new suites (A05 §11.3): the map per mode, hold from every mode, Back targets, **re-entry timing** (G2), Seek mapping and timers, snap state machine, toast suppression, ledger, playlist pager, `include=catalog` handling | nothing |
| **A2** | The RC oracle and a **new BS-`draw()` oracle** within 2e-3; a target golden from BS `renderVals()` with tagged deviations; twin replay covering every new moment, the Seek MODE and the PRNG; palette output checks (#FF8424, #FF3A0A) | nothing |
| **A3** | Parser parity v5 (firmware `parse_tests` against `device.py`); the worst-case byte budget (Windows, 20 colour entries, two button colours, `snap` feedback, `clock`, `progress`) | nothing |
| **A4** | LCD harness renders for seek, the mirrors, Tracks and Windows snap meta: chords, heading fit, `Turn to choose` within 168 px, **0 px Seek jitter** with the tabular font; `lcd_preview` parity including the twins | nothing |
| **A5** | `cpp11_gate.py`, MSVC `/W4 /WX`, `light_tests`, `media_tests`, `jpeg_tests`, `led_wire_tests` | nothing |
| **A6** | PlatformIO build < 0x140000 with the headroom recorded (estimated +25 to +55 KB, A04 §9.1); icon and font `--check` | nothing |
| **A7** | The frozen desktop `--smoke-test`; the v7 packaging tests | nothing |
| **S1** | Overlay frame intervals at k = 2 for the picker turn, snap fly, explorer turn and source switch, Up next turn and shuffle: p95 per U10 | supervised desktop |
| **S2** | dwm.exe commit and process memory within the K4 budget (80 MB today, CAROUSEL §5) | supervised desktop |
| **S3** | Snap on real windows (maximized, minimized, UWP, elevated, mixed DPI); focus kept; flush edges; one-side close | supervised desktop; **it moves their windows** |
| **S4 / S5** | Toast placement and suppression; a live tray theme switch | supervised desktop |
| **L** | R1–R5 read-only; W1–W5 per §1.4 | the user's go-ahead for each |
| **H** | See §4.5 | the user's go-ahead |

### 4.5 The hardware window (only after A, S and L pass, and with the user's go-ahead)

Follow MEM's hands-on rules: wait for "ready", use beep cues only for the turning test (`NANOD_AUDIBLE_CUES=1`), and get an explicit go-ahead before flashing.

1. **H1 Flash** cc5.4 with the cc5.3 app-only procedure: backup, verify, rollback ready. Desktop rollback is `desktop-dist-v6`.
2. **H2 `check_nanod_cc5.py` (cc5.4):**
   - the `alive` and `presentation: 5` capabilities;
   - `ledFps` ≥ 55 idle and ≥ 45 during cover transfers;
   - `ledRenderUsMax` ≤ 3000;
   - `lim` and `kh` events;
   - `heapMinFree` (expected ≈ 48 KB) and `lvglMinFree` ≥ 30 KB with the twins;
   - `lcdRenderUsMax`;
   - **enter→ready latency** (G2);
   - no `error` replies under stress.
3. **H3 Turning test** (beeps):
   - Seek at 5 s per detent, including the End stop at 0:00 and at `T_end`;
   - the 600 ms hold from every mode;
   - the re-entry feel at the snap advance, the tab switch and Shuffle;
   - the F24/serial race on Home button 4.
4. **H4 LED tour** (`nanod_alive_tour.py`):
   - settle U1 and U8 (PINK candidates, body 0.62);
   - `ledDrive` and dither;
   - every moment: half left/right, scatter, pink bloom, sweep from 0, lap, the Up next levels, pair on/off, the snap button colour;
   - Head shake legibility (G7).
5. **H5 LCD:**
   - Seek digits don't jitter;
   - the twins read well on light covers;
   - the mirror headings fit;
   - the Windows art fades;
   - Up next spin lag from JPEG decodes (A04 §2.3).
6. **H6 End to end, with services** (each audible or queue-changing step consented):
   - explorer → Play (W5 latency);
   - Up next → Like, Shuffle, Play;
   - Play next;
   - a snap pair.

   Then install desktop v7.

**Needs the knob:** H1–H6. **Doesn't:** A-gates, S-gates, and L-gates R1–R5 and W1–W4, which can all finish before the window, so it stays short.

### 4.6 Items to feed back to Claude Design

The user asked for a design prompt once the research is complete (MEM:60). These constraints would change or complete the design:
- Play next works only from the Sonos queue, and not under native shuffle. The refusal states in §3.3 need visuals.
- Shuffle semantics (U4): what Up next shows under native shuffle, and after Shuffle off.
- Favourite playlists: the tab lists favourited *playlists*. Today that is 2 items, one of them "Favorite Songs", which Like feeds. It needs empty and thin-list states; playlist art may be missing (6 have none), fixed-size, or on disallowed hosts, so the mosaic needs a fallback.
- Artwork: 5 % of albums top out at 600 px, and user playlists often have no art. Big covers need 1200 px requests; the design needs a matted fallback.
- The pending and failure states the prototype skips: playlist Play can take many seconds (G3), plus Seek, Like, Snap and Up next on AirPlay.
- Tracks `Next:` / `Prev:` under shuffle and repeat-all (G8).
- Refresh-rate constraints (G1) on blur radius, card count and per-frame work at 240 Hz.
- The knob: a 118 px heading chord at r 104; no blur for text shadows on LVGL; tabular digits.
- Snap: no guaranteed Windows "Snap group"; a non-activating restore; how the other window moves on a one-sided close (U12).
- Overlay lifetime (G9) and reduced motion (G16).
