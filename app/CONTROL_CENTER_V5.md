# CONTROL_CENTER_V5: companion state machine and services contract (K3)

Status: **frozen build contract**, written 2026-09-25 for the one combined release **firmware 1.0.0-cc5.4 + desktop v7** (the "Warm · alive" LED engine plus the whole r2.1 master design). Documents only; nothing was built or run, and no knob, serial port, Sonos, Apple Music or Tk window was touched.

This is **K3** of the four contracts named in `firmware\V5_VOCABULARY.md` (cited **VOC**). It owns the controller grammar, modes and sub-states, Back and hold, the re-entry helper, every timer, the confirmation policy, the Sonos / Apple Music / Windows service contracts, the provenance ledger, the toast service rules, overlay lifetime, the Settings status strip and recovery, copy *use*, the simulator fakes and the test plan. It does **not** restate wire validation (K1 `PRESENTATION_V5.md`), LED math (K2, the ALIVE revision) or surface rendering (K4 `DESKTOP_STAGE.md`); where it depends on them it says so.

Every token, id, enum value and copy string from VOC is used verbatim. New ones are listed as `C5-n` additions (§19) for VOC to absorb.

**Revision 2 (2026-09-25, cross-contract review).** Aligned with K1 `PRESENTATION_V5.md`, K2 `ALIVE_R2_DRAFT.md` and K4 `DESKTOP_STAGE.md`: the presenter interface is one push contract with K4's payload fields plus `t0` (§11); snap acceptance, cancel completion, `refused`, `system(kind)` and the `display` / `device` closes are handled (§5.7, §13); the audio lane lets short jobs run between the steps of long queue jobs (§1.1); `play_items` staging follows 00 G3 with a job deadline (§9.2); the companion shuffle keeps a Play-next block first and never moves rows at or before the playing row (§9.5); the host hold fallback is withdrawn (K1 defers `kh`, §4.2). The Seek offer is capped at D ≤ 59 999 s, the knob-side art (scrim, loading and Generated covers) has an owner (§10.5), and hold closes raise no toast. New entries C5-45…C5-58; revised C5-8 (withdrawn), C5-9, C5-18, C5-27, C5-28, C5-33, C5-36, C5-37, C5-41 (§19).

**Revision 3 (2026-09-25, consistency pass across K1–K4).** The Home slot-0 label follows its icon (`Play` / `Pause`, VOC-D08, C5-60); the desktop legend column and `legend.*` are withdrawn (VOC-R24, C5-7); `windowsButton = button_order[3]` (raw); K3's busy dims are `ignored` only where their state is on screen, else the busy line is the reason and the Head shake plays (VOC-D07, C5-59); the ring wire forms of K1/K2 (the Up next card, loading lists, unloaded entries, C5-61); one presenter-event entry point (`presenter_event`, VOC-R22); the snap latch bound is K4's 800 ms deadline (C5-12); `explorer_highlight` carries `state` / `count`; the GIL parse rule of K4 §4.7.3 (§1.2); K1's OQ-4 answer (§6); `Queue changed` and `Home, then Browse` for the approval pass; `led_pink` / `led_vol_full` settings keys (§14.4). New entries C5-59…C5-61; revised C5-3, C5-7, C5-12 (§19).

**Revision 4 (2026-09-25 evening, live-check amendments; evidence `AN\live-checks.md` (LC) and `AN\like-star-mismatch.md` (LS)).** Three services change on live evidence, with nothing else in the grammar touched. **Like** uses `POST /v1/me/favorites?ids[songs]=<id>` (202), the only call shown to reach the user's devices; `PUT /v1/me/ratings` changed the server but never reached the iPhone, so it is not used, and neither is `DELETE /v1/me/ratings` (it cleared the server but not the iPhone's star). **Unlike** sits behind `UNLIKE_STRATEGY ∈ {"favorites_delete", "add_only"}`, default **`add_only`**, because the web player's `DELETE /v1/me/favorites` was **not** sent (LS 23:01 UTC: blocked by the session's permission system, no result recorded). The heart state has one source, `GET /v1/me/ratings/songs?ids=` (§9.8.2–§9.8.3, §5.6.6, C5-62…C5-64; C5-40 superseded). **Seek** is confirmed when the transport has left `TRANSITIONING` **and** the position reads within ±2 s of the target, inside a **5 s** window (live: 2.64 / 2.69 s to leave `TRANSITIONING`, RelTime at the target from the first read while still buffering); never resent; the knob clock stays frozen at the target (`Jumping…`) until then; the confirmation polls yield to short jobs (§9.4, §1.1, C5-65; C5-15 revised). **Play next** pre-resolves the focused Recently Added item and its neighbours, so the job starts inserting at once (live: inserts at P+1+i land exactly while playing, 522 / 560 ms each; an uncached 8-track album resolves in 3–6 s) (§9.3, §9.8.7, C5-66). K2 is now **`ALIVE.md` revision 2** (the draft merged; `ALIVE_R2_DRAFT.md` kept, superseded, same section numbers).

**r2.2 amendment (2026-09-25, late; design follow-up r2.2, VOC key `R22`, authoritative list R22 CH "r2.2 — follow-up 1 from engineering").** Docs only; every change is tagged **[r2.2]**, withdrawn items are marked in place, and ids are kept. (1) **Like is add-only, for good** (C5-67): the web player's `DELETE /v1/me/favorites` was sent once with the user's approval and refused (**HTTP 400, code 40012**, LS), so `UNLIKE_STRATEGY = add_only` is final; the `favorites_delete` branch, the `unlike` effect, `unlike_unsupported`, the moment `unlike`, `knob.meta.like.off` (`Like removed`) and the heart-off animation are withdrawn. A liked row keeps Button 3 enabled with `lit:"on"` (the knob draws tone `liked`: PINK 0.30, filled `#A3244A` heart); a press plays the Head shake and shows `Unfavourite in Music app` for 2.2 s; the label and the hint read `Liked`; a save failure shows `Didn’t save · try again` with the Head shake. (2) **Copy approved** (C5-70): the §15.3 strings as listed, with `Speaker group changed` and `Couldn’t open on screen` rewritten. (3) **Seek** (C5-68): landed = playback resumed (the transport left `TRANSITIONING`), not a position report; no resume in `seek_confirm_ms` = **8000** → failure; `Jumping…` + the Working comet hold throughout; a turn during a jump moves the frozen target and at most one follow-up jump is sent when the current one lands. (4) **Play next** (C5-69): `Finding songs…` until the first song is queued, then `Queueing… {k} of {n}` at ≈ 0.5 s per song, the Working comet throughout.

**Phase-2a text amendment (2026-09-25, night; tag [P2a]).** Docs only: it records what the phase-2a build and its review settled, with no change to the grammar, the copy or the wire. Every change is tagged **[P2a]** and superseded text is struck through in place. (1) **Shuffle off takes the ledger's Play-next units** `[song_id, start_row]` and attributes the rows in two passes, so ~~the restored order equals the controller's preview~~ the adapter puts first the same Play-next rows as the controller's preview; the base rows follow in their order at Shuffle on, which the preview (the ledger's start order) matches only when they still stood in it (review fix, item 6) (§9.5.3, C5-73). (2) **`jump` lands by the Seek rule** (playback resumed at the row, ≤ 8 s, polls that yield to short jobs), not a 2 s read-back, so it is no longer one atomic step on the audio lane (§9.6.2, §1.1, C5-74). (3) The internal effect **`resolve_drop{keep}`** drops stale queued pre-resolutions at each detent (§5.2.2, §9.8.7, §10.1, C5-75). (4) **`Speaker group changed`** shows for `group_changed_ms` = **2600** (§7, §9.10, C5-76). (5) **Appendix A** signs off the grammar oracle: every footer slot where the controller differs from the r2.2 prototype, with its ruling (lead ruling R-e). The live jump-latency check is added to §17.3 (W2b). **Review fixes (2026-09-26; the phase-2a K-docs review KD-R1, R2, R3, R6, R7; same tag [P2a], wrong claims struck through in place).** (6) The shuffle-off preview equals the realised order only when the upcoming base rows stood in the ledger's start order at Shuffle on; §9.5.3 lists where they do not (a reorder without a ledger entry, a queue the companion did not start, a played Play-next row outside the loaded window), each shown by the re-read after the job; the fix is handed to WP5 and WP6 (§18). (7) **A start drops a Seek follow-up still waiting after Seek was left** (C5-77, new ruling): §1.1's "a new Seek cannot be queued" was false, because that follow-up reached the audio lane while an Up next jump confirmed and ran inside the jump's steps; the controller change is WP5's (§18). (8) `group_changed` per op: a start shows `Speaker group changed` with `err` and no toast; a seek, shuffle or transport failure shows its own failure first and the group copy from the next state poll (§8, §9.10, C5-76). (9) The `seek_confirm_ms` rows name the Up next `jump`'s use of the window (`PLAYING` at the row, else `start_failed`, C5-74; §7). (10) Appendix A is pinned exactly by `tests\test_kdocs_contract.py` (§A.1, §A.5).

**Phase-2b errata (2026-09-26; tag [P2b]).** Docs only: the lead's rulings on the phase-2b gate. Superseded text is struck through in place and every change is tagged **[P2b]**. (1) **R-j** (KD-4): `Speaker group changed` is failure copy and shows in the **`error`** tone, not `meta`, wherever it shows (§2.4, §7, §8, §9.10, C5-76); its duration, the `err` rules per op and the precedence are unchanged. (2) **R-l**: the phase-2a K-docs deviations KD-1…KD-3 and the host deviations WP3b-D1…D4 are accepted as built. Both are listed in §19's phase-2b table (E-j, E-l1…E-l4).

**Phase-3 amendment (2026-09-26; tag [P3]; the WP5-fixes build).** Code and text together; superseded text is struck through in place. (1) **C5-77 is built**: `_dispatch_start` and the Up next Play press drop a waiting Seek follow-up (`_drop_seek_follow_up`), pinned by `tests\test_cc5_tracks_seek.py` and `tests\test_kdocs_contract.py` (no longer pending). (2) **`windows_cancel` carries the close `reason`** (`back` \| `hold` \| `lock` \| `sleep` \| `idle`; C5-78, the phase-2b review item R8): the runtime passes it to `cancel(origin, complete=, reason=)`, so the picker no longer has to infer it (WP7b-D6 stays only as its fallback for a payload without one); a `cancel_result(restored=false)` after a `lock` or `sleep` close raises no desktop notice, since those closes never restore focus (K4 §15) (§5.7.4, §9.9, §11). (3) **The Shuffle-off preview ranks the base rows by the restore record** when the controller knows it: from its own accepted Shuffle on, or the record the runtime loads at start (C5-79; the recommended fix of the phase-2a review, KD-R1), so §9.5.3's limitations 2 and 3 apply only when it does not (§5.6.5, §9.5.3). (4) R-j's `error` tone for `Speaker group changed` (item 1 above) is built in the controller. **Review fixes (the phase-3 review, WP5R-1 and WP5R-2).** (5) The places that still named the ledger's start order as the preview's only rule (§9.5.3 step 3 and the limitations lead-in, C5-73) carry the C5-79 qualifier, and C5-73's handoff clause is struck. (6) **Lock, sleep and idle close the picker at once during a snap**: the controller had latched them behind the snap like Back and hold, which neither C5-12 nor K4 §15 ("instant") allowed; only Back and hold are latched now (§5.7.3, §5.7.4, C5-12), pinned by `tests\test_cc5_windows_snap.py`.

**Phase-3b amendment (2026-09-26; tag [P3b]; the lead's decisions on the phase-3 gate).** Docs only. (1) **The H5 parse bench result** (WP6-gil, `gil_parse_hold.py`): §1.2 records it and the caps applied: `catalog_songs` ≤ 50 ids per request (§9.8.4), `resolve` and `playlist_meta` pages `limit=50` (§9.8.7, §9.8.8, with `playlist_meta`'s 100-track window and 10,000-track duration reach), no deferral of Sonos reads (§9.6.1). (2) **Accepted deviations** (§19 [P3b] table): WP5P3-D1…D5 of the phase-3 WP5 build and WP6-GIL-D1, D2, D3 and D5 of WP6-gil (D4 is withdrawn). Superseded text is struck through in place and every change is tagged **[P3b]**.

---

## 0. Frame

### 0.1 Keys

The VOC §0.1 keys apply (R, CH, S01…S05, BS, HT, KM, 00, A01…A06, CS, CP, CL, CF, RP, RA, LC, RF0…RF3, AL, P4, CC, PR, DV, CT, RT, UI, OV, CAR, FK). BS line numbers are the **r2.1** file's. Added here:

| Key | File (under `<repo>\`) |
|---|---|
| VOC | `firmware\V5_VOCABULARY.md` |
| SO, AM, SI, CRD, WN, ST | `app\control_center\sonos.py`, `apple_music.py`, `simulation.py`, `credentials.py`, `windows.py`, `app\standalone.py` |
| K1, K2, K4 | the sibling contracts (VOC header); K2 is `firmware\ALIVE.md` **revision 2** since rev 4 (the merged draft; `ALIVE_R2_DRAFT.md` is kept, superseded, with the same section numbers) |
| LS | `app\design-reference\ui-v2-analysis\like-star-mismatch.md` (rev 4; LC is `live-checks.md` in the same folder, VOC §0.1) |

**[r2.2]** `R22` is VOC §0.1's key for `design_handoff_nano_d_master_r2.2\` (R22 CH §1–§4 = its CHANGELOG items 1–4; R22 S01, R22 BS, R22 HT).

Line numbers for CT, RT, SO, AM, SI and UI were re-read on 2026-09-25 against today's tree. A05 and A06 cite older numbers (for example A05's `RT:1165` for `invalidate_actions` is `RT:1395` today); this file uses today's.

### 0.2 Precedence

VOC rule 3: r2.1 README > S01 > S02 > S03 > S04 > S05 for behaviour and look; the engineering analysis (00 and its sources, with r2.1 on top) for feasibility; user decisions are binding. Inside the design, the prototype (BS) is below the specs where they disagree (R §0).

### 0.3 Binding inputs

**User decisions.** Warm `#FF8424` all day (K2); amber/red (K2); offline drain → amber marks → native lights (firmware); floating knob mirrors the ring at the display refresh (K4); **no main window**; **Favourite playlists = favourited playlists including Favorite Songs** (00 U7); **Like = the Apple Music Favorite** (the star; Apple stores it as rating 1), made with `POST /v1/me/favorites`, the call that reaches the user's devices (verified live 2026-09-25 22:06 UTC, LS; rev 4 replaces the rating `PUT`, which never reached the iPhone), fallback Play next for the row; **Unlike** only where it provably reaches the devices (`UNLIKE_STRATEGY`, default `add_only`, C5-63); **[r2.2] Like is add-only, final** (`UNLIKE_STRATEGY = add_only`; the favourites `DELETE` → 400 / 40012; R22 CH §1; C5-67); **playlists lenient** (`Playing 33 of 34`), **albums all-or-nothing** (00 U6); one hardware window at the end (00 U13); paused Play green (00 U1, K2); volume body 0.62 (00 U8, K2); picker keeps Frosted / No background, no sheen (00 U9, K4); **Recently Added one flat list** (00 U5); **shuffle hybrid** (companion reorder ≤ 60 upcoming rows, Sonos shuffle above; 00 U4); **optimistic-hybrid Play** (overlay closes at 380 ms, knob Home `Starting…` + comet, then wash or shake; 00 U11); **Switch stays confirmed** (00 U11); **Snap one-side close moves the previously focused window** (00 U12, confirmed); Settings status strip (00 U14); screen 5120 × 1440 @ 240 Hz, 100 % scaling.

**Engineering rulings kept.** Play next = `DesiredFirstTrackNumberEnqueued = P+1+i`, never `EnqueueAsNext`, only from the queue with Sonos shuffle off (A06 §1.4; 00 C3); Seek `T_end = D − 3`, 250 ms debounce, confirm by read-back (rev 4: `TRANSITIONING` left **and** the position within ±2 s of the target, within 5 s; C5-65; **[r2.2]** landed = playback resumed, within 8 s, the position is not a condition, one follow-up jump at most, C5-68), never resend, pending target flushed on exit (CS §4; 00 §3.2); snapped windows restored non-activating (VOC-D01); hold = firmware `kh` + `ks` in `ready` (VOC-D06); F24 only when slot 3's icon is `win`; art 1200/600/240, Sonos 400 (RA §4.1); presentation 5 + alive 1 (VOC §6.5); 00 §3.2 delegated rulings.

### 0.4 Build ownership (00 §4.2)

| Part of this contract | WP | Files (exclusive write) |
|---|---|---|
| §2–§8, §10, §12 (service side), §13 (logic), §16, controller/runtime tests | WP5 | `control_center\controller.py`, `runtime.py`, `simulation.py`; `tests\test_cc5_*.py` (§17) |
| §9, the ledger, consent copy, knob art (§10.5), service tests | WP6 | `control_center\sonos.py`, `apple_music.py`, `credentials.py`, **`artwork.py`** (00 §4.2 WP6 row: sizes, unscrimmed covers, `_SCRIM_STOPS` .60/.72/.92/1.0, allowlist; K1 §8.4), new `control_center\queue_context.py`; `tests\test_cc_sonos_v7.py`, `test_cc_apple_v7.py`, `test_cc_ledger.py`, `test_cc_knob_art_v7.py` |
| §14 Settings strip and Motion control, tray label | WP10 | `control_center\ui.py`, `standalone.py` |
| Presenter implementations named in §11–§13 | WP7 / WP8 (K4) | `carousel.py`, `windows.py`, new stage/scene modules |

### 0.5 Id conventions

`C5-n` (§19) are this contract's entries. Kind **D** = departs from r2.1 (with reason); **R** = ruling where r2.1 is silent or sources disagree; **A** = addition that VOC must absorb (new code, op, copy id, field). VOC-D01…D08 and VOC-R01…R25 are inherited unchanged.

---

## 1. Architecture seam

| Layer | Thread | Owns | Talks to |
|---|---|---|---|
| **Controller** (`controller.py`) | Tk thread; pure, injected clock and RNG | modes, grammar, timers, confirmation, copy choice, frames, effects | Runtime only (effects out; `complete`, `progress` and events in) |
| **Runtime** (`runtime.py`) | Tk thread (25 ms poll, `UI:99`) + 3 lanes | lanes, device events, invalidation, art/accent decoration, media lists, toast service routing, session events | controller, services, presenters, device bridge |
| **Services** | lanes | `SonosAdapter`, `AppleMusicClient`, `QueueLedger`, `WindowsAdapter` ops | runtime only |
| **Presenters** (K4) | their own native threads (`NanoD-stage`, `NanoD-carousel`, `NanoD-overlay`) | explorer, Up next, picker, toast, floating knob | receive presenter effects on the Tk thread; post input back through a pump (CAR §1 "Thread safety") |

**Lanes** (today `RT:334-338`; unchanged count, new assignments):

| Lane | Executor | Ops (VOC §7.4 op ids) |
|---|---|---|
| `audio` | `nanod-sonos`, 1 worker running the step scheduler of §1.1 | short: `state`, `volume`, `transport`, `seek`, `queue_window`; exclusive (§2.3): `play_items` (Sonos phase), `play_next` (Sonos phase), `shuffle_reorder`, `set_shuffle`, `jump`, `move_next` |
| `library` | `nanod-library`, 1 worker, foreground Apple session | `recent` (the page the user waits for), `resolve` (for `play_items` / `play_next`), `like`, `unlike` (**[r2.2]** withdrawn, C5-67), `favourite_playlists` (explorer open with no cache) |
| `lookahead` | `nanod-lookahead`, 1 worker, background Apple session (`AM:69-77`) | `recent_lookahead`, `catalog_songs`, `ratings`, `favourite_playlists` (refresh), `playlist_meta`, `resolve` (**pre-resolution** of the focused Recently Added item and its neighbours, §9.8.7, C5-66; always the lane's lowest priority: every other queued lookahead op runs first), the Home warm-up (ARTWORK2 §11.4, kept) |

All Sonos I/O stays serialized on `audio` (CS §3 "Rate limits"): one thread, one SOAP call at a time. A job reads its intent when it **starts**, not when it was queued (the volume pattern, `RT:1340-1354`).

### 1.1 Audio lane scheduling: long jobs yield between steps (C5-48)

Today every `SonosAdapter` op holds the adapter `RLock` for its whole body (`SO:90`, `:367`) on the single `nanod-sonos` worker, so a volume turn, a Seek or a Play/Pause queued behind a 100-song Play next (100 `AddURIToQueue` calls, A06 §1.9: unmeasured), a 34-song start (§9.2) or a 60-row companion shuffle (up to 59 moves × 3 calls ≈ 177 SOAP calls, §9.5.2, OQ-5) would wait for the whole job. The lane therefore runs a **step scheduler**:

| Rule | Detail |
|---|---|
| Two queues | **short** (`state`, `volume`, `transport`, `seek`, `queue_window`) and **exclusive** (at most one running, §2.3) |
| Steps | A long exclusive op (`play_items` staging, `play_next` inserts, `shuffle_reorder` moves) is written as a sequence of **steps**. A step is one mutating SOAP call plus its own verification reads (≤ 3 calls: an insert + its tail-slice read; a position read + an `UpdateID` read + one `ReorderTracksInQueue`). Each step takes the adapter lock for its own calls only |
| Yield | The adapter takes `between_steps: Callable[[], None]` and calls it after every step **with its lock released**. The runtime's `between_steps` runs every queued short job (FIFO; volume and seek read their newest intent at start), then returns |
| Seek confirmation (rev 4, C5-65; **[r2.2]** C5-68: until playback resumes, ≤ 8 s) | `seek` is a short job, but its confirmation lasts ≈ 2.7 s live (§9.4). It sends its one `Seek` as a step, then **each confirmation poll is a step**: between polls it calls `between_steps()`, which runs the queued short jobs **except another `seek`** (a newer target waits for this one to resolve, latest wins, §5.5.4). So a volume turn or a Play/Pause during a landing seek waits at most one poll (≤ 3 calls), never the whole window. A seek that runs inside an exclusive job's `between_steps()` yields the same way; that job resumes when the seek resolves (≤ 5 s; **[r2.2]** ≤ 8 s), and its next step re-reads what it depends on as always |
| Atomic parts | ~~`set_shuffle`, `jump`, `move_next` are one step each.~~ **[P2a]** `set_shuffle` and `move_next` are one step each. `jump` is not (C5-74): its guards, `Seek(TRACK_NR)` and `Play` are one step, then **each confirmation poll is a step**, as for a `seek` (row above; §9.6.2), so a short job queued behind a jump waits at most one poll, not the whole landing (a seek's took ≈ 2.7 s live, W2). Unlike a seek's, a jump's `between_steps()` runs every queued short job ~~(a new Seek cannot be queued: `starting` dims it, §2.3)~~. **[P2a] (C5-77)** No `seek` may run there: `starting` dims the Tracks Seek button (§2.3), and a start **drops** a Seek follow-up still waiting after Seek was left (§5.5.5). The lane itself skips a `seek` only inside another seek, so the controller's drop is the guard; without it the follow-up reached the lane while the jump confirmed and ran inside one of its poll steps (a `not_confirmed` Head shake over `Starting…` during `TRANSITIONING`, or a seek of the restarted track whose ≤ 8 s confirmation could use up the jump's window). The destructive tail of `play_items` (guarded `RemoveTrackRangeFromQueue` → `SetAVTransportURI` → `Seek(TRACK_NR 1)` → `Play` → final check, `SO:406-427`) is **one** step: nothing runs between the removal and `Play` |
| State poll | During an exclusive job the 1 s poll is admitted to the short queue **at most once per 2000 ms** (bounds the slowdown to ≈ 8 reads × t_call per 2 s, CS §1) |
| Our own revisions | While an exclusive job of ours runs, a `queue_revision` change in a state result is **not** an external change: §5.6.8 and §5.4.2 re-reads wait for the job's completion (which counts as a revision change, §9.7.1). `playlist_position` changes still re-tag Up next roles at once |
| Guards after a yield | Short jobs never change the queue or skip the track: skips and every queue-changing press are dimmed while an exclusive job runs (§2.3). Each step re-reads what it depends on (a fresh `UpdateID` and the playing row per move, §9.5; the returned `FirstTrackNumberEnqueued` per insert, §9.2, §9.3). A song that ends during a yield is handled by the op's own position rules (§9.3 step 9, §9.5 C5-50) |
| Bound | A short job waits for at most **one step**: ≤ 3 × t_call (≈ 150–240 ms at the 50–80 ms per call A06 §3.4 estimates), or ≈ 10 calls for a start's destructive step (only volume, the poll and Up next reads can queue behind it: `starting` dims Seek, Play/Pause and skips); the worst case is one step's timeouts (5 s per call, `SO:74`) |

Rejected alternative: a separate RenderingControl lane with its own lock. It would put two threads on one shared `SoCo` object whose zone-group cache `_context` clears on every call (`SO:122-145`), and it would still leave Seek and Play/Pause (AVTransport) behind the job.

### 1.2 Parses and the GIL (K4 §4.7.3)

`json.loads` and ElementTree's C parser (which soco uses) parse a whole response in one C call that holds the GIL. While **any** desktop animation episode runs (the stage, the picker, a toast, or the visible floating knob, which is visible during Home and Tracks spins while the 1 s poll runs), no thread of this process may hold the GIL inside one C call for more than **1 ms** (K4 §4.7.3, the rule for every thread, these three lanes and the Tk thread included). The bench `gil_parse_hold.py` (K4 §6.6 H5) measures each parse below at its largest size; **only the rows where it shows a hold over 1 ms** change, as K4 §4.7.3 sets out:

| Parse (lane) | Largest request today | If the bench shows > 1 ms |
|---|---|---|
| Apple `catalog_songs` (lookahead) | ~~300 ids~~ **[P3b]** 50 ids per request (`CATALOG_BATCH`; §9.8.4; rev 4 drops `extend=inFavorites`) | ids ≤ **50** per request: **[P3b]** applied (300 ids held 1.85–3.29 ms, 50 ids hold 0.26–0.49 ms) |
| Apple `resolve` / `playlist_meta` tracks pages, playlists pages (library, lookahead) | ~~`limit=100`~~ **[P3b]** tracks pages `limit=50` (§9.8.7, §9.8.8); playlists pages `limit=100` (§9.8.5) | `limit` ≤ **25** (more requests on the same lane; the resolve deadline, §9.8.7, and W5 are re-checked). **[P3b]** Tracks pages **50** (100 rows held 0.92–1.55 ms, 50 rows hold 0.43–0.71 ms; accepted deviation WP6-GIL-D1, §19); playlists pages stay 100 (0.20–0.22 ms) |
| Apple Recently Added page | `limit=25` (§9.8.6) | — (already 25) |
| Sonos queue DIDL-Lite (audio) | `get_queue(max_items=100)` (`SO:315`) | Up next and Tracks reads stay windows of ≤ 21 rows (§9.7.1); a **full-queue read is deferred while an episode runs**, by at most **1 s**, except a read that a user action needs at once (a Play next, a shuffle, a start's staging, a mode entry), which runs and is accepted as a rare bounded hitch. **[P3b]** Not applied: the Browse envelope of 100 rows holds 0.26–0.49 ms and lxml parses the DIDL-Lite with the GIL released, so no read is deferred and the windows stay as they are (accepted deviation WP6-GIL-D2) |
| Sonos ZoneGroupState (audio) | every `_context()` (`SO:122-127`), each poll and assert | the 1 s poll uses the cached context while an episode runs, for at most **3 s**; every guard before a write still reads it fresh (§9). **[P3b]** Not applied: 0.15–0.17 ms at 32 players; the poll reads it fresh (WP6-GIL-D2) |

~~The caps and deferrals are WP6's to apply after the bench, before the hardware window;~~ **[P3b]** Applied by WP6-gil after the bench (`tools\stage_checks\gil_parse_hold.py`, 2026-09-26; `design-reference\ui-v2-analysis\gil-parse-hold.md`; cap rule: one C call p50 ≤ 0.5 ms and p95 ≤ 1.0 ms): the two Apple caps above, no Sonos deferral, and the queue-recovery copy a start saves is encoded one value and one row at a time (largest single C call 0.80 ms at 5,000 rows; one `json.dumps` held 8–14 ms). The bench result is recorded with W5 (§17.3), whose live check also confirms `limit=50` pages on an album and a playlist (WP6-GIL-D1).

---

## 2. Controller state model

### 2.1 Modes

Controller mode ids are VOC-R01. Group, depth, family and layout tokens are VOC §1.1 and belong to K1/K2; they are repeated here only where the controller must know them.

| Mode (`Screen.mode`) | Parent | Profile (`PROFILES`) | Bounds (`min`..`max`) | Entry position | Layout token | Overlay |
|---|---|---|---|---|---|---|
| `home` (renamed from v6 `volume`, VOC-N04) | — | BINARIS BEER | 0..100 | display volume (`CT:348-350`) | `nowPlaying`/`volume`/`idle`/`notice` | — |
| `recent` | `home` | MIDI SKIPPER | §5.2.2 | 0 on Browse (item 1, U13); the explorer's recent index on explorer Back | `recent` (page 0) | — |
| `explorer` | `recent` | MIDI SKIPPER | 0..n−1 of the active source; 0..0 when empty or loading | recent: the Recent index; favourites: the remembered playlist (§5.3.2) | `explorer` (page 0/1) | `explorer` |
| `tracks` | `home` | MIDI CLACK JONES | 0..2 | 1 (Neutral) | `tracks` | — |
| `seek` | `tracks` | BINARIS BEER | 0..`max` (§5.5.1) | `n0` | `seek` | — |
| `upnext` | `tracks` | MIDI SKIPPER | 0..rows−1 (§5.6.2) | the now-playing row | `upnext` | `upnext` |
| `windows` | `home` | MIDI SKIPPER | 0..len−1 of the frozen snapshot (0..0 when empty) | the snapshot's index (`CT:947`) | `windows` | `picker` |

`PROFILES`, `mode_title` (legacy field) and the dev-window descriptions (`UI:1002-1005`, A05 §2.1) gain every key above; a missing key is a `KeyError` on the first entry (A05 §2.1).

### 2.2 Screen and shared state

```python
@dataclass
class Screen:                      # one per mode entry (a new view_id per Screen, CT:102-111)
    mode: str = "home"
    index: int = 0                 # absolute knob position inside bounds (authoritative, CT:1-5)
    parent_index: int | None = None   # Tracks index to return to (upnext); Recent index (explorer)
    status: str = ""               # desktop-side text (notice), never knob copy (§2.4)
    view_id: int = field(default_factory=lambda: next(_view_ids))
    explorer: ExplorerState | None = None   # §5.3
    seek: SeekState | None = None           # §5.5
    upnext: UpNextState | None = None       # §5.6
    windows: WindowsState | None = None     # §5.7 (replaces the v6 dict)
```

Controller-wide state that outlives one Screen:

| Object | Lifetime | Contents |
|---|---|---|
| `recent_list: RecentList` | one visit (from Browse until the next Browse) | §5.2.2; shared by `recent` and the explorer's recent tab (U5) |
| `favourites: FavouritesList` | session (refreshed, §9.8.5) | items sorted (C5-30), `state ∈ {none, loading, ready, empty, signin, error}`, `loaded_at`, `focus_id` |
| `start: StartPending \| None` | from a Play press until its result | `request`, `kind ∈ {album, playlist, song, track}`, `name`, `accent`, `source ∈ {recent, explorer, upnext}`, `closed_at` (overlay close time or press time) |
| `play_next: PlayNextJob \| None` | from Recent 3 until its result | `request`, `item`, `name` (album/playlist title), `accent`, `k`, `n`, `phase ∈ {resolving, inserting}` (**[r2.2]** the knob shows `Finding songs…` while `phase == resolving` or `k == 0`, C5-69) |
| `shuffle_job: ShuffleJob \| None` | from Up next 2 until its result | `request`, `on`, `regime ∈ {companion, sonos}`, `plan`, `playnext_offsets` (§9.5.2), `accepted` |
| `like_inflight: set[str]` | per request | song ids with a like out (**[r2.2]** like only) (one per song, CL §4.2); rev 4: out for the request **and** its read-back (≈ 0.6–1.6 s, §9.8.2) |
| `unlike_strategy: "favorites_delete" \| "add_only"` — **[r2.2] fixed at `"add_only"`** (C5-67): the `favorites_delete` value, the settings.json override and the downgrade are withdrawn; the rest of this row is rev 4 history | runtime, latched at start; downgraded for the session | the effective `UNLIKE_STRATEGY` (§9.8.2; default `"add_only"`, settings.json `unlike_strategy` without UI overrides it for the W4b live check); an `unlike_unsupported` result sets `"add_only"` until the companion restarts (C5-63) |
| `transient: TransientCopy \| None` | until `until` | `copy_id`, `text`, `tone ∈ {meta, error, secondary}`, `until` (clock), `target` (§2.4) |
| `due: list[Due]` | per scheduled action | host-driven re-entries and delayed effects (§6.2), each `(at, cause, view_id, fn)` |
| `last_knob_input: float` | always | clock time of the last `position`, `button`, `hold` or `limit` of the current control (lifetime idle, §13) |
| `reduced_motion: bool` | latched | the effective Motion setting (§14.3) |
| `rng: random.Random` | injected | the companion-shuffle plan (§9.5); seedable in tests |
| `clock` | injected | seconds, float; **`time.perf_counter`** (QPC) in production, the one clock K4 uses (K4 §0.6), so every `t0` the controller puts in a presenter effect is on the presenter's timeline (§11.1) |

v6 state that retires: `origin` resume paths other than Home (A05 §2.2 "dead code"), the Recent `pages`/`page`/More/lookahead-adoption machinery (`CT:185-294`, `CT:367-377`, `CT:648-675`), `SKIPPED_STATUS` (`CT:61`).

### 2.3 Exclusive queue actions and busy codes (C5-3)

At most **one queue-changing action** runs at a time: a start (`play_items` or `jump`), a Play next, a shuffle (`shuffle_reorder` or `set_shuffle`) or a `move_next`. While one runs, the buttons that would start another (or skip the track under it) are **dimmed with the running action's busy code**, and a press on them is **ignored** (only the knob's Press moment):

| Busy code | Running action | Dims (in addition to the design's own dims) |
|---|---|---|
| `starting` | start pending (`Starting…`) | Home 1 (S01:86), Recent 3/4, Explorer 4, Tracks 3/4, Up next 2/4 |
| `queueing` | Play next inserting | Recent 3/4 (S01:87-88), Explorer 4, Tracks 4, Up next 2/4 |
| `shuffling` | a shuffle running | Recent 3/4, Explorer 4, Tracks 4, Up next 2/4 |

Reason: each of these would race the running job's guards (`TrackChanged`, `QueueChanged`, SO:153-156, :312-325) and turn a success into `song_changed`. Like, Seek, volume and Play/Pause are not queue-changing and stay available (Seek is still dimmed by `starting`, because the track is about to change; **[P2a]** for the same reason a start drops a Seek follow-up still waiting after Seek was left, C5-77): Like runs on the `library` lane, and volume, Seek, Play/Pause and the state poll run **between the job's steps** on the `audio` lane, waiting at most one step (§1.1, C5-48).

### 2.4 Transient copy slot (C5-6)

One global slot carries every short-lived knob copy (reasons, results, confirmations), as BS `kmeta` does (BS:775). It is drawn on the **current screen's copy line**, whatever screen that is when it is set or while it lasts:

| Current mode | Line (frame field) | Precedence over the mode's own copy on that line |
|---|---|---|
| `home` | `status` | `Starting…` (a start pending) **>** transient **>** volume-reveal status **>** transport pending **>** `Paused` (BS:1287; C5-34) |
| `recent` | `meta` | Play next progress (**[r2.2]** `Finding songs…` / `Queueing… {k} of {n}`, C5-69) **>** transient **>** position (BS:1269) |
| `explorer`, `upnext`, `windows` | `meta` | transient **>** the mode's meta (BS:1263, :1276, :1284) |
| `tracks` | `meta` | transient **>** meta (BS:1257) |
| `seek` | `meta` (the 14 px line, VOC §6.2) | `Jumping…` (**[r2.2]** for the whole seek span, §5.5.6) / seek failure **>** transient **>** `of {m:ss}` (BS:1417) |

A new transient replaces the old one at once. Tones: **reason copy `meta`**, **failure copy `error`** (`#FF8474`, VOC-R10), sign-in expired `error` (BS:825) (C5-5); **[P2b]** `Speaker group changed` counts as failure copy, `error` (C5-76, lead ruling R-j). Durations are §7.

### 2.5 Controller public API

| Call | From | Semantics |
|---|---|---|
| `position(p, control_id)` | device `position` | absolute detent; ignored unless ready and the id matches (`CT:542-547`) |
| `button(logical, control_id, hid=False)` | device `button` (down edge) and presenter input | §3; `hid=True` on logical 3 is dropped (the F24 path already acted, VOC §2.5) |
| `hold(logical, control_id)` | device `hold` (from `kh`, including a `kh` the firmware deferred to just after `ready`, K1 §11.2 step 5) | logical 0 only; §4.2 |
| `limit(direction, control_id)` | device `limit` (`lim`) | Seek limit line, overlay end bumps, Seek idle re-arm, lifetime input |
| `device_ready(control_id)` | device `ready` | marks ready (`ks` is consumed by `device.py` to re-seed its pressed mask, K1 §11.3) |
| `set_hardware(enabled)`, `disconnected()` | runtime | §13.4 |
| `open_windows()` | runtime `hotkey()` (F24) and serial logical 3 without a hotkey | Home only (§5.7.1) |
| `dismiss_windows()` | `WindowsAdapter.on_focus_lost` (`UI:771`) | close reason `focus_lost` |
| `close_overlay(reason)` | runtime lifetime checks, and `presenter_event` for `system(lock\|sleep)` | §13 |
| **`presenter_event(event)`** | the runtime's adapter `pump()` (K4 §2.3), for **every** §11.4 event: the **one entry point** (VOC-R22, VOC §7.4) | dispatches in the controller: `opened` / `closed` (a close the controller asked for) → registry only; `closed(surface, display\|device)` → `presenter_closed`; `refused` → `presenter_refused`; `click_action(surface)` → `button(3)`; `system(lock)` / `system(sleep)` → `close_overlay("lock" / "sleep")`; `system(display)` → nothing (the presenter reports its own `closed`); `system(motion)` → re-evaluate the Motion setting at once (§14.3); `snap_result` / `cancel_result` → the calls below. An event for a surface or control that is no longer current is logged and dropped |
| `presenter_closed(surface, reason)` | `presenter_event`: `closed(surface, reason)` for a close the **presenter** started (`display`, `device`; K4 §4.3, §15) | §13.1: parent mode, no toast, no U12 |
| `presenter_refused(surface, reason)` | `presenter_event`: `refused(surface, busy\|device)` (K4 §2.3, VOC-K4-02) | §13.5 |
| `snap_result(side, outcome)` | `presenter_event`: `snap_result` (§9.9) | §5.7.3 |
| `cancel_result(restored, completed)` | `presenter_event`: `cancel_result` (§9.9) | gates `toast.snap.one_side` (§5.7.4) |
| `tick()` | every runtime poll | timers (§7), due re-entries (§6), state polls |
| `complete(request, result=None, error=None)` | runtime results | §8, §9 |
| `progress(request, payload)` | runtime results (new channel, §10.3) | Play next `k of n`, shuffle acceptance |
| `set_reduced_motion(on)` | runtime (§14.3) | latched frame field |
| `frame(assume_ready=False)`, `control()` | runtime, device bridge | K1 validates; content per §5 |
| `explorer_view()`, `upnext_view()`, `windows_view()` | the runtime's presenter facades, Tk thread | read-only view models from which the facades build the pushed payloads (§11.2); presenters never call them |
| `drain()` | runtime | effects (§10) |

---

## 3. Button grammar

### 3.1 Per-mode map (v7 host, presentation 5)

Tokens and tones are VOC §2.2–§2.4; the knob derives the tone. **Label** is the wire legend (≤ 16 B, `PR:72`), also the Home idle-row word (every Home label ≤ 46 px at 12 px, K1 §8.6.3). There are **no desktop legend strings**: the floating knob is click-through with no tooltip, and BS's `legend` (BS:1297, drawn at BS:341-349) is the prototype's key-hint panel, not a product surface (VOC-R24; C5-7 revised). Dim codes are listed **in evaluation order**; the first that applies is the reason; whether a dimmed press is `ignored` or answered with reason copy and the Head shake is §3.2 (per mode, C5-59).

| Mode | Slot (Button = slot + 1) | Token | Label | `lit` / `color` | Dim codes (order) | Press when enabled |
|---|---|---|---|---|---|---|
| `home` | 0 | `pause` if confirmed PLAYING, else `play` | **`Pause` while the token is `pause`, else `Play`** (the label follows the icon; VOC-D08, C5-60) | — | `sonos_unavailable`, `starting`, `transport_pending`, `nothing_playing` | `transport` play/pause (§8) |
| `home` | 1 | `list` | `Browse` | — | — (Browse works without Sonos, A01 §3.1) | → `recent`, new visit (§5.2) |
| `home` | 2 | `tracks` | `Tracks` | — | `sonos_unavailable`, `nothing_playing` | → `tracks` (index 1) |
| `home` | 3 | `win` | `Win` | — | — | `open_windows()` (F24 path, §4.3) |
| `recent` | 0 | `back` | `Back` | — | — | → `home` |
| `recent` | 1 | `expand` | `Open` | — | `signin_expired`, `list_error` | → `explorer` (§5.3.1) |
| `recent` | 2 | `playnext` | `Play next` | — | `loading`, `empty`, `signin_expired`, `list_error`, `starting`, `queueing`, `shuffling`, `sonos_unavailable`, `item_unavailable`, `src_none`, `src_airplay`, `src_radio`, `src_linein`, `sonos_shuffle` | `play_next` (§9.3) |
| `recent` | 3 | `play` | `Play` | — | `loading`, `empty`, `signin_expired`, `list_error`, `starting`, `queueing`, `shuffling`, `sonos_unavailable`, `item_unavailable` | start (§8, §9.2) |
| `explorer` | 0 | `back` | `Back` | — | — | close `back` → `recent` |
| `explorer` | 1 | `clock` | `Recent` | `on` if the recent tab is active, else `off` | — (a press on the active tab, or during a tab swap, is ignored silently) | tab switch (§5.3.3) |
| `explorer` | 2 | `playlists` | `Playlists` | inverse of slot 1 | — (as slot 1) | tab switch |
| `explorer` | 3 | `play` | `Play` | — | `loading`, `empty`, `signin_expired`, `list_error`, `starting`, `queueing`, `shuffling`, `sonos_unavailable`, `item_unavailable` | start at 380 ms (§5.3.5) |
| `tracks` | 0 | `back` | `Back` | — | — | → `home` |
| `tracks` | 1 | `expand` | `Up next` | — | `sonos_unavailable`, `src_none`, `src_airplay`, `src_radio`, `src_linein` | → `upnext` (§5.6.1) |
| `tracks` | 2 | `seek` | `Seek` | — | `sonos_unavailable`, `src_none`, `src_airplay`, `src_radio`, `src_linein`, `no_length`, `starting` | → `seek` (§5.5.1) |
| `tracks` | 3 | `prev` at index 0, else `next` | `Skip` | — | `neutral`, `sonos_unavailable`, `starting`, `queueing`, `shuffling`, `transport_pending`, `skip_unavailable` | skip (§5.4.4) |
| `seek` | 0 | `back` | `Back` | — | — | exit Seek (flush) → `tracks` |
| `seek` | 1 | `expand` | `Up next` | — | as Tracks 1 | exit Seek (flush), then → `upnext` |
| `seek` | 2 | `seek` | `Seek` | `on` | — | exit Seek (flush) → `tracks` |
| `seek` | 3 | `next` | `Skip` | — | `seeking` (always) | — |
| `upnext` | 0 | `back` | `Back` | — | — | close `back` → `tracks` |
| `upnext` | 1 | `shuffle` | `Shuffle` | `on` while shuffle is active (a companion restore record, or Sonos `SHUFFLE*`), else `off` | `loading`, `starting`, `queueing`, `shuffling`, `sonos_unavailable`, `nothing_next` | shuffle toggle (§5.6.5) |
| `upnext` | 2 | `heart` (fallback mode: `playnext`) | `Like` / **[r2.2] `Liked`** (liked; was `Unlike`, R22 CH §1) | `on` when the focused row is liked: **[r2.2]** the knob draws tone `liked` (PINK 0.30, filled `#A3244A` heart; VOC §2.3 row 4) | `loading`, `sonos_card`, `not_catalog`, `likes_unknown` | like (§5.6.6); **[r2.2]** a press on a **liked** row is always refused at the press (`unlike_unavailable`, §3.2: Head shake + `Unfavourite in Music app` for 2.2 s; the button stays enabled) |
| `upnext` | 3 | `play` | `Play` | — | `loading`, `sonos_card`, `starting`, `queueing`, `shuffling`, `sonos_unavailable` | jump at 380 ms (§5.6.7) |
| `windows` | 0 | `back` | `Back` | — | — | close `back` (U12, §5.7.4) |
| `windows` | 1 | `snapleft` | `Snap left` | `on` + `color` = the left app's raw accent when assigned; else `nav` (BS:1282) | `empty`, `closed` | snap left (§5.7.3) |
| `windows` | 2 | `snapright` | `Snap right` | as slot 1 for the right side | `empty`, `closed` | snap right |
| `windows` | 3 | `switch` | `Switch` | — | `empty`, `closed` | `windows_activate` (confirmed) |

Notes:
- `windowsButton = button_order[3]` (the **raw** index mapped to slot 3; `windowsButton` is raw, CC:229; never the literal 3) and `windowsHidEnabled = (mode == "home")` in every control (VOC §2.5, §6.1; K1 §11.4; A04 §6.2). `self.windows_button` becomes `button_order[3]` (`CT:156`, `RT:1603`). The firmware sends F24 only while `frame.buttons[3]` is enabled with icon `win` (K1 §11.4).
- Home 1 while a Home play/pause is out shows the requested state's control dimmed (v6 rule, `CT:1042-1045`) with code `transport_pending`.
- Up next Button 3 fallback mode: a settings.json key `upnext_button3 ∈ {"like", "playnext"}` (default `"like"`, no UI). In `"playnext"` mode slot 2 is `playnext` / `Play next` and presses run `move_next` (§9.6.3) (S01:353; A06 §5.5).

### 3.2 Dim reasons

VOC §2.6 is the base table (codes, copy ids, shake, toast). This contract **extends scopes** and **adds codes** (C5-4). "Buttons" are numbered 1–4 (Button n = slot n−1, VOC §0.2):

| Code | New / extended | Buttons | Condition | Knob copy | Shake | Toast |
|---|---|---|---|---|---|---|
| `sonos_unavailable` | extended | + Home 1, Home 3, Tracks 2/3/4, Up next 2/4 | `state.online` false | `knob.meta.sonos_unavailable`; on Home the `status` twin `knob.status.sonos_unavailable` (same text, C5-56) | yes | — |
| `no_length` | extended | Tracks 3 | + the duration exceeds **59 999 s** (K1 §4.3 `LAP_COUNT_MAX`; §9.1 `can_seek`, C5-51) | `knob.meta.seek.no_length` | yes | — |
| `loading` | extended | + Recent 3/4 | the list or the focused item is not loaded | — (on screen: meta `Loading…`, §5.2.3) | ignored | — |
| `empty` | extended | + Recent 3/4, Windows 2/3/4 | no items | — (on screen: title `Nothing recently added` / `No eligible windows`) | ignored | — |
| `starting` | extended | per §2.3 | a start pending | Home 1: — (on screen: status `Starting…` + comet, S01:86). Elsewhere: `knob.meta.busy.starting` (`Starting…`) | Home 1 ignored; elsewhere **yes** | — |
| `queueing` | extended | per §2.3 | Play next running | Recent 3/4: — (on screen: meta ~~`Queueing…`~~ **[r2.2]** `Finding songs…` (then `Queueing… {k} of {n}`), S01:87-88; R22 CH §4, C5-69). Elsewhere: the running job's busy line, `knob.meta.playnext.progress` (`.resolving` before the count is known; **[r2.2]** `Finding songs…` until the first song is queued, C5-69) | Recent ignored; elsewhere **yes** | — |
| **`shuffling`** | new | per §2.3 | a shuffle running | Up next 2/4: — (on screen: the Working comet, `activity:"pending"`, §5.6.4). Elsewhere: `knob.meta.busy.shuffling` (`Shuffling…`) | Up next ignored; elsewhere **yes** | — |
| **`transport_pending`** | new | Home 1, Tracks 4 | a play/pause or skip is out (`CT:383-399`) | Home 1: — (on screen: the requested state's dimmed icon + status `Starting…` / `Pausing…`). Tracks 4 during its own skip: — (meta `Skipping…`). Tracks 4 while a Home play/pause is out: `knob.meta.busy.starting` / `knob.meta.busy.pausing` | Home 1 and own skip ignored; else **yes** | — |
| **`signin_expired`** | new | Recent 2/3/4, Explorer 4 | the list failed with 401/403 (§9.10) | `knob.meta.signin_expired` (`Sign-in expired`, error tone, 2200 ms as BS:825; the list twin of `knob.meta.like.signin_expired`, C5-56) | yes | — |
| **`list_error`** | new | Recent 2/3/4, Explorer 4 | the list failed otherwise | `knob.meta.library_error` (`Library not loaded`, the `meta` twin of `knob.title.library_error`, C5-56) | yes | — |
| **`skip_unavailable`** | new | Tracks 4 | the direction is not offered and the source is not a queue end (no `Next` / no preceding target, `SO:158-175`) | `knob.meta.skip.prev_unavailable` / `.next_unavailable` (§15.2) | yes | — |
| **`nothing_next`** | new | Up next 2 | shuffle off, companion regime (`U ≤ 60`) and fewer than 2 upcoming rows **outside the Play-next block** (`U_r < 2`; A06 §3.4 gate applied to the rows that move, C5-45) | `U < 2`: — (on screen: the list shows fewer than two upcoming rows). `U ≥ 2` (only Play-next rows could move): `knob.meta.shuffle.nothing` (`Nothing to shuffle`) | `U < 2` ignored; else **yes** | — |
| **`unlike_unavailable`** (rev 4) | new, **a press refusal, not a dim** | Up next 3 | the focused row is liked (**[r2.2]** always: add-only is final, C5-67; rev 4 also required `unlike_strategy == "add_only"`) | `knob.meta.like.unlike_in_music` (**[r2.2]** `Unfavourite in Music app`, 152.7 px, approved; was `Unfavourite in Music`) for **`like_fail_meta_ms` 2200** (R22 CH §1), meta tone | **yes** | — (overlay open) |

**Why `unlike_unavailable` is not a dim** (rev 4): `enabled:false` always wins over `lit` (VOC §2.1; K2 §5.3 row 2), so a dimmed liked heart would lose its PINK on the LED and the LCD footer, the knob's only sign that the row is liked. **[r2.2]** The design confirms it: a liked Button 3 is PINK at **0.30**, not the generic 0.14 disabled level, so it says "liked" rather than "broken", with a filled `#A3244A` footer heart (R22 CH §1); the knob derives that look (tone `liked`) from `enabled` + `lit:"on"`. The button therefore stays **enabled** with `lit:"on"`, and the press is refused through the §3.3 path (reason copy on `meta`, `reason_meta_ms`, `feedback{kind:"err"}`), as Tracks 4 refuses a skip at a queue end while enabled (§5.4.4). No request is sent. ~~The label stays `Unlike` and the desktop hint `Like | Unlike`~~ **[r2.2]** The label is `Liked` and the desktop hint reads `[3] Liked` on a liked row (`Like` otherwise; K4 builds the hint from the liked state; R22 CH §1). The refusal copy shows for `like_fail_meta_ms` 2200 (the §3.3 `spec.ms`), not `reason_meta_ms`.

**Which dims may be `ignored` (C5-59; VOC-D07; VOC §2.6 second table).** r2.1 designs "ignored" only for Home 1 while `Starting…` (S01:86); every other dimmed press gets its reason and the Head shake (R:76, :182). A code is `ignored` only in a mode where its state is **on the screen where the press happens** (a busy line, the Working comet, an explaining title, the Seek screen, the overlay's own content); in every other mode the same code answers with reason copy (for the busy codes, the busy line itself) and `feedback{kind:"err"}`. So `REASONS[code]` carries a predicate `ignored(mode, state)` instead of a flag, and each "Elsewhere" copy id above is drawn on the current `meta` line (§2.4) for `reason_meta_ms`.

### 3.3 The Head-shake-with-reason rule

A press on a dimmed button **never acts** (S01:48-50). The firmware plays the Press moment on every down edge; the host then:

```text
refuse(mode, slot, code):
    spec = REASONS[code]                      # VOC §2.6 + §3.2
    if spec.ignored(mode, state): return      # Press only, only where the state is on screen (VOC-D07; C5-59;
                                              # S01:86; BS:851, :885, :953, :971, :1005, :1042)
    text = copy(spec.copy_id(mode, slot))
    set_transient(text, tone=spec.tone, ms=spec.ms or 2000)   # reason_meta_ms (S01:50)
    feedback("err")                           # Head shake at the current cursor (VOC §4.2 row 1)
    if mode == "recent" and slot == 2 and spec.toast and no overlay open:
        toast(spec.toast)                     # S01:50, S01:209
```

- Every press re-arms the 2000 ms and sends a new `feedback.seq` (one shake per press).
- The frame is rebuilt; **no re-entry** (bounds and profile are unchanged).
- `Checking likes…` shakes (VOC §2.6; S01:50 outranks BS:824).
- Tones per §2.4: reasons `meta`; `signin_expired` `error`.
- Copy ids name the line they are drawn on (VOC §9.1 grammar): a reason shown in Home `status` uses its `knob.status.*` twin, one shown in `meta` its `knob.meta.*` twin (C5-56).

### 3.4 Silent busy guards (not dims)

Sub-second in-flight operations do not dim (a flicker would read as a state change); presses on them are ignored with only the Press moment. Buttons are numbered 1–4 here (VOC §0.2), as in §3.2:

| Guard | While | Ignored presses |
|---|---|---|
| like in flight | the focused row's song id is in `like_inflight`: the request and its read-back, ≈ 0.6–1.6 s (rev 4: POST 388 ms, rating 1 readable ≈ 1 s later, LS 22:06 UTC; was ≈ 145 ms for the rating `PUT`); the Working comet shows it (§5.6.4) | Up next 3 |
| snap in flight | from a snap press until its placement resolves (≤ 800 ms: K4 §9.6's hard deadline, t0 + 800) | Windows 2/3/4 (Button 1 and hold are **latched**, C5-12) |
| switch in flight | `windows_activate` out (`CT:401-402`) | Windows 1/2/3/4 |
| tab swap | 190 ms after a tab press (BS:1036) | Explorer 2/3 |
| shuffle swap | 200 ms after a shuffle press (BS:871) | Up next 2 |
| Play window | 380 ms after an explorer or Up next Play (BS:1042, :885) | every button and hold (C5-9) |

---

## 4. Back targets and hold

### 4.1 Back (Button 1 outside Home; "up one level", S01:41, :71-81)

| From | Back goes to | Knob index there | Overlay close reason | Notes |
|---|---|---|---|---|
| `recent` | `home` | volume | — | — |
| `explorer` | `recent` | `explorer.index_by_source["recent"]` (always the recent tab's index, A01 artefact 13) | `back` | S01:76 "same album" |
| `tracks` | `home` | volume | — | — |
| `seek` | `tracks` | 1 (Neutral) | — | flushes a debouncing target (§5.5.5) |
| `upnext` | `tracks` | the Tracks index held when Up next opened (A01 §3.6) | `back` | — |
| `windows` | `home` | volume | `back` | restores focus; applies U12 (§5.7.4); latched while a snap is in flight (C5-12) |

### 4.2 Hold 600 ms = Home

**Wire.** Firmware AceButton long press at 600 ms after the debounced press, only for the raw button mapped to slot 0, at most once per press, sent as `{"id","ks","kh":raw}` ≈ 620–640 ms after contact (VOC §6.3; A04 §6.1). `device.py` emits `{"kind":"hold","id","button":<logical>}` (VOC §6.4).

**Controller.** The press already acted on its down edge (S01:41). `hold(0, control_id)`:

| Current mode (after the press acted) | Hold does |
|---|---|
| `home` | nothing (no overlay can be open on Home) |
| `recent`, `tracks` | → `home` |
| `seek` | flush the pending target, exit Seek, → `home` (S01:77) |
| `explorer` | close with reason `hold`, → `home` |
| `upnext` | close with reason `hold`, → `home` |
| `windows` | close with reason `hold` (restore focus, U12 applied, VOC-R15), → `home` |
| inside the 380 ms Play window | nothing (the knob is already going Home, §3.4) |

No close by `hold` raises a toast, not even the one-side toast or an armed sign-in toast (VOC §7.3 `hold` row; BS:893-898 `goHome` flashes nothing; C5-36).

**One hold per press, no host timer (C5-8 withdrawn).** The firmware sends **at most one `kh` per physical press** (K1 §11.2). A long press that fires while the knob is entering after the Back re-entry is **not** dropped: the firmware latches it (`pendingHold`) and sends `kh` with the new control id right after that control's `ready`, if the button is still down (K1 §11.2 step 5, P5-R10). The controller therefore:
- acts on every `hold(0, control_id)` whose id is the current control's, once; it does **not** require a `kd` for logical 0 in that control (the `kd` of a press made while entering was dropped, `cc_input_id()` = 0, 00 G2; the press then did not act, and the hold still goes Home);
- runs no host-side hold timer: host timing on the 25 ms Tk tick is what VOC-D06 retired (A04 §6.1), and a timer racing a `ku` handled later in the same poll could fire a false Home;
- ignores a `hold` for logical 1–3 (the firmware never sends one, K1 §11.2 step 2).
- A presentation-4 knob sends neither `kh` nor `ks`: there is no hold (VOC §2.2).

### 4.3 F24 and `hid` routing (VOC §2.5; A05 §3 R1)

- `Runtime.hotkey()` calls `controller.open_windows()` instead of `button(2)` (`RT:1325-1333`), still synchronously inside WM_HOTKEY (foreground grant).
- The serial `kd` of logical 3 is **dropped when it carries `hid:1`** (presentation 5). On a presentation-4 knob it is dropped when `mode == "home"` and the hotkey is registered (`RT:1642-1647` today skips logical 2 in every mode).
- Without a hotkey (simulator, `SI:94`), serial logical 3 on Home calls `open_windows()`.

---

## 5. Modes in detail

Copy ids are VOC §9 unless marked (§15.2 lists this contract's retained and added ids). "Transient" is §2.4.

### 5.1 Home

**5.1.1 Entry.** Back from `recent` or `tracks`; hold from any mode; any start (§8); picker close; reconnect (C5-2). Profile BINARIS BEER, bounds 0..100 (`CT:341-346`).

**5.1.2 Frame.**

| Field | Content |
|---|---|
| `layout` | v6 `_home_layout` (`CT:480-511`): `notice` when offline; `volume` during a reveal; `idle` when nothing to play or 4 s after a confirmed pause or STOPPED with media; else `nowPlaying`. `restLayout` as v6 |
| `title` / `subtitle` | track title / artist; `knob.caption.nothing_playing` when none |
| `status` | precedence §2.4: `knob.status.starting` (start pending) > transient (`knob.status.partial` 3000 ms, `knob.status.start_failed` / `knob.status.album_blocked` 2600 ms error tone, reasons, results of actions started elsewhere) > reveal status (`knob.status.setting`, `knob.status.changed_elsewhere`, `knob.status.minimum`, `knob.status.maximum`, `CT:1276-1298`) > transport pending (`knob.status.starting` for a resume, `knob.status.pausing`) > `knob.status.paused` > "" |
| `volumeCaption` | `knob.caption.volume` / `knob.caption.volume_paused` (not while a Play request is out, `CT:1253-1255`) |
| `activity` | `pending` while a start, a volume write or a transport is pending, or any §8 "comet" action runs; `offline` on the notice |
| `playing` | confirmed transport only (ALIVE R3/R4, `CT:448-467`); the album-start hold (`ALBUM_START_HOLD_SECONDS = 10`, `CT:57`) applies to **every** start kind (album, playlist, song, jump). **Omitted** (K2 M16, `ALIVE.md` revision 2 §10.2): on every Home frame while a start is pending (`status` = `Starting…`), and on the frame that carries `feedback.moment:"started"`, so the first confirmed `playing:true` never cuts the `started` wash with Fill. It returns on the next Home frame after the `started` frame |
| notice | `knob.title.looking_for_sonos` before the first read; else `knob.title.sonos_unavailable` / `knob.sub.looking_for_sonos` / `knob.meta.windows_still_works` (§15.2; `CT:1157-1166`) |

**5.1.3 Turns.** Volume intent, latest wins, one write per 100 ms, read-back confirmed, never replayed (`CT:542-557`, `RT:1340-1354`, `SO:219-242`). Reveal hides 1400 ms after the last detent **and** once the value is confirmed; the controller re-evaluates every tick (the v6 rule holds the reveal while `desired_volume` or `volume_request` is set, `CT:495-497`), which satisfies "re-check every 400 ms" (S03 volume reveal). External change: 2600 ms reveal + `Changed on Sonos` (`CT:762-766`).

**5.1.4 Paused idle.** 4000 ms after a **confirmed** pause, cancelled by a Home 1 press (`CT:588-600`, `:746-755`).

### 5.2 Recently Added (knob list; flat list, U5)

**5.2.1 Entry.** Home 2 → `Screen(mode="recent", index=0)` and a **new visit**: `recent_list.reset()` and a foreground `recent` request for offset 0 (C5-1). Explorer Back → `recent` at the explorer's recent index (the visit continues).

**5.2.2 The list model.**

```python
class RecentList:
    visit: int                     # grows at each Browse
    items: list[dict]              # loaded, in Apple order; item shape §9.8.6
    total: int | None              # Apple meta.total when present (OQ-1)
    complete: bool                 # the last page had no `next`
    next_offset: int               # 25 × pages loaded
    inflight: int | None           # the one page request out (either lane)
    state: "loading" | "ready" | "empty" | "signin" | "error"
```

- **Page size 25** (Apple's maximum for this endpoint; the live probe read 100 items in 4 pages, LC:16) (C5-31).
- **Prefetch.** Keep **≥ 16 loaded items ahead** of `max(recent index, explorer recent index)`: 12 preload + 4 in the direction of travel (S01:267). When fewer remain and `not complete` and nothing is in flight, request the next page on the **lookahead** lane (`recent_lookahead`). If the focused item itself is unloaded (a fast spin outran the prefetch), the request moves to the **library** lane (the user is waiting).
- **Bounds.** When `total` is known: `0..total−1` from the first page on; unloaded positions are valid and show the loading item state. When `total` is unknown: `0..len(items)−1`, growing as pages land (§6.4 passive rule, with the loaded-end exception).
- **End.** Focus on the last item of a complete list → meta `knob.meta.position_end`; turning past plays the knob's End stop (S01:319).
- **Pre-resolution** (rev 4, C5-66). `prefetch_resolve_rest_ms` (400) after the last detent on a **loaded** item (the knob list or the explorer's recent tab, which share the index), the controller asks the runtime to pre-resolve the focused item, then its neighbour in the direction of travel, then the other neighbour (§9.8.7). A new focus drops the queued (unsent) pre-resolutions that are no longer the focus or a neighbour; one already running finishes and lands in the cache. **[P2a]** The drop happens **at the detent**, not at the next rest (C5-75): each detent on Recently Added (the knob list, the explorer's recent tab, or a switch back to that tab) that leaves a sent pre-resolution outside the new focus ± 1 emits the internal effect `resolve_drop{keep}` (§10.1), `keep` = the new focus and its two neighbours among the loaded items; the runtime removes every queued pre-resolution not in `keep` from the lookahead lane (the running one is never dropped). A spin with no rest therefore resolves nothing, even with an earlier batch still queued. Leaving Recently Added (Back, hold) drops nothing: the batch for the item the user last rested on still runs into the cache. So a Play next or a Play on an item the user rested on for about a second finds its songs cached and starts inserting at once (§9.3).

**5.2.3 Frame.**

| State | `title` | `subtitle` | `meta` | `activity` | Ring |
|---|---|---|---|---|---|
| first page loading (the whole list) | "" | "" | `knob.meta.loading` | `loading` | **`style:"off"`** (K1 §4.6): Working comet only (VOC-R06; K2 M31) |
| item loaded, available | item title | artist, else the kind label (`KIND_LABELS`, `CT:41-42`) | Play next progress > transient > `knob.meta.position_end` / `knob.meta.position` | `pending` while Play next runs, else `idle` | selection (VOC §3.2) |
| item loaded, unavailable | item title, `titleTone:"muted"`; **`artDim:true`** (the cover at 0.35, K1 §8.4, §8.6.5) | as above | as above | as above | landmark omitted; cursor 0.45 in its colour (VOC-R05) |
| item not yet loaded (the count is known; a fast spin outran the prefetch) | "" | "" | `knob.meta.loading` | the list's own: `pending` while Play next runs, else `idle` (**never `loading`**, K2 M31) | selection with that entry's colour **0** in `colors[]`: a warm landmark, the cursor WARM on it; the local cursor keeps working (K1 §4.6; C5-61) |
| empty | `knob.title.recent_empty` | `knob.sub.recent_empty` | "" | idle | `off` |
| sign-in (401/403) | `knob.title.signin_expired` | `knob.sub.signin_expired` | `knob.meta.windows_still_works` (`metaTone:"secondary"`) | `error` | `off` |
| error | `knob.title.library_error` | `knob.sub.library_error` | `knob.meta.windows_still_works` | `error` | `off` |

`artDim` is sent only on the unavailable row (every other state omits it). `heading` = `knob.heading.recent`; `page` = 0 (VOC §1.1). Ring `first` follows VOC-R03 (`first = clamp(index − 10, 0, count − 20)` for `count > 20`, replacing `window_first`'s `index − 9`, `PR:155-159`); `colors[]` = album accents (VOC §3.5); no `moreIndex`.

**5.2.4 Buttons.** §3.1. Play next progress replaces the position meta: `knob.meta.playnext.resolving` during the Apple lookup, then `knob.meta.playnext.progress` (`Queueing… {k} of {n}`) (§9.3). With the item pre-resolved (§5.2.2, C5-66) there is no lookup: ~~the first line is `Queueing… 0 of {n}` at the press~~ (**[r2.2] superseded**: the first line is `Finding songs…`, below) and `k` counts up by one per verified insert (≈ 0.5 s each, LC W1). **[r2.2] (C5-69; R22 CH §4)** The meta is `knob.meta.playnext.resolving` = **`Finding songs…`** while the job is resolving **or** `k == 0` (so a pre-resolved item shows `Finding songs…` until its first insert lands, ≈ 0.5 s, like the prototype's 0.4 s cached lookup), then `Queueing… {k} of {n}` for `k ≥ 1`; **`Queueing… 0 of {n}` is never shown**. `activity:"pending"` (the Working comet) runs from the press to the result, lookup included (K2 M33).

### 5.3 Music explorer (screen primary; knob mirrors)

**5.3.1 Entry.** Recent 2 at time `t0`:
1. `explorer = ExplorerState(source="recent", index_by_source={"recent": recent.index}, swap_until=0, play_until=0)`.
2. Re-enter at once (mode change: the knob's LCD flips +1 by depth, K1).
3. Effect `explorer_open` (payload §11.1: `t0`, `source`, `index`, `count`, the preload items, `items_first`, `items_rev`, `state`, `control_id`, `control_min`, `reduced_motion`, `foreground_hwnd`, `sonos_available`); the presenter clears any toast (BS:1024).
4. Favourites: if `favourites.state == "ready"` and `now − loaded_at ≤ 600 s`, use it; if older, refresh on `lookahead`; if none, load on `library` (state `loading`).
5. If the presenter answers `refused(explorer, busy|device)`, §13.5 returns the knob to `recent` with a shake and `knob.meta.stage_unavailable`.

**5.3.2 Per-source positions.**
- Recently Added: `index_by_source["recent"]` **is** the shared list's index (U5). It is re-seeded from the knob on every open (BS:1025) and returned to the knob on Back.
- Favourites: `favourites.focus_id` (a playlist id), session-long (BS keeps `xIdx.playlists` across opens; C5-30 keys it by id per CF §5 "Remember xIdx.playlists by playlist id"). Resolved to an index at each entry into the tab; a missing id → index 0.

**5.3.3 Tab switch** (Button 2 = Recently Added, Button 3 = Favourite playlists; BS:1035-1039; 00 G2):

| Time | Controller | Presenter |
|---|---|---|
| `t0` (press on the inactive tab, not during a swap) | `swap_until = t0 + 190`; turns and tab presses are ignored until then (C5-9) | `explorer_source{t0, source, index, count, items, items_first, items_rev, state}` with `index` = the new source's remembered index: cards exit 170 ms IN (S01 App A), the new set is committed at the press to enter at `t0 + 190` (K4 §0.6, §7.6) |
| `t0 + 190` | `source` switches; **re-enter** with the new source's bounds and remembered index (`page` 0 ↔ 1, the LCD flips +1 into favourites, −1 back) | the new source enters **at the `index` the controller sent**, with the 45 ms × distance stagger; knob positions from the old control id that arrived during the swap are discarded, never applied to the new source (they are positions in the old source's bounds) |

**5.3.4 Frame.** `layout:"explorer"`, `page` 0 (recent) / 1 (favourites), `heading` `knob.heading.explorer_recent` / `knob.heading.explorer_favourites`.

| State | `title` | `subtitle` | `meta` | Ring |
|---|---|---|---|---|
| recent tab | as §5.2.3 (same list, same states) | as §5.2.3 | transient > `knob.meta.position_end` / `knob.meta.position` (S01:319 puts `· end` in the explorer's own section; BS:1276 omits it, lower precedence) | selection, album accents |
| favourites loaded | playlist name, or `overlay.explorer.untitled` | `knob.sub.playlist_count` when the count is known, else "" | transient > `knob.meta.position` | selection, playlist accents (first mosaic cover, VOC §3.5) |
| favourites, playlist unavailable (a 404 `40403` empty playlist, §9.8.8) | as loaded, `titleTone:"muted"`, **`artDim:true`** | as loaded | as loaded | landmark omitted (VOC-R05) |
| favourites loading (no cache, or retrying after an error, C5-42) | "" | "" | `knob.meta.loading` | `style:"off"` + `activity:"loading"`: comet only (K1 §4.6; K2 M31) |
| favourites item not yet loaded (count known) | "" | "" | `knob.meta.loading` | selection with that entry's colour 0, the list's own activity (as §5.2.3; C5-61) |
| favourites empty (confirmed by the full scan, CF §5) | `knob.title.favourites_empty` | `knob.sub.favourites_empty` | "" | `off` |
| favourites sign-in (401/403, no cache) | `knob.title.signin_expired` | `knob.sub.signin_expired` | "" | `off` |

A thin list (1–3 items) needs nothing special: the focus stays centred and the count is true (S01:308-310).

**The screen's state.** Every explorer payload carries the active source's **displayed state** in `state` (`loading` \| `ready` \| `empty` \| `signin` \| `error`, §11.1), as the rows above map it (the recent tab's from §5.2.3). For `empty`, `signin` and `error` the overlay shows its **state block** instead of cards (K4 §7.4, S5-33): the favourites empty copy `overlay.explorer.empty_title` / `.empty_help`; for Recently Added `overlay.explorer.recent_empty_title` / `.recent_empty_help`; `overlay.explorer.signin_title` / `.signin_help` on **either** tab; `overlay.explorer.error_title` / `.error_help` (§15.3; VOC-K4-04). A state change while the explorer is open goes out in `explorer_highlight` with `state` and `count` (§11.1); K4 animates it like a source switch (K4 §7.6).

**5.3.5 Play** (Button 4 at `t0`; S01 §4d; BS:1040-1046):
1. Guards §3.1; the start effect (`play_items`, §9.2) is dispatched **at `t0`** so the Apple lookup overlaps the animation (there is no undo; the press cannot be taken back).
2. `play_until = t0 + 380`; turns, presses and hold are ignored until then (C5-9).
3. Effect `explorer_close{t0, reason:"play", close_at_ms:380}` (centre card grows to 1.12, others fade; the overlay closes at `t0 + 380`, S01:276; K4 anchors the close leg to `t0`).
4. At `t0 + 380`: `start.closed_at = now`; mode → `home` (re-entry, flip −1); Home shows `Starting…` with the comet (§5.1.2).

**5.3.6 Other input.** Back → §4.1. `limit(±1)` → `explorer_highlight{index, control_id, bump:±1}` (the 14 px end bump, S01 App A). A click on the centre card arrives as `click_action(explorer)` = Button 4 (§11.3). Sonos down: the explorer still opens; Play dims `sonos_unavailable` (00 G12; VOC-R14).

### 5.4 Tracks

**5.4.1 Entry.** Home 3 (index 1); Up next Back (the saved index); Seek exits (index 1, BS:848 resets `tPos`); a skip's completion (index 1).

**5.4.2 Neighbour titles.** Only when the source class is `queue`: `queue_window(start=max(0, P−2), count=3)` (1-based rows P−1..P+1) on entry and whenever `(queue_revision, playlist_position)` changes while in Tracks; cached per that pair; **never** in the 1 s poll (A05 §5.3).

**5.4.3 Frame.** `heading` `knob.heading.tracks`.

| Index | `title` | `subtitle` (the 14 px line) | `meta` |
|---|---|---|---|
| 1 (Neutral) | `knob.title.tracks.choose` | `knob.line.tracks.now` | transient > `knob.meta.tracks.skipping` (skip out) > `knob.meta.tracks.position_shuffle` (companion or Sonos shuffle on) / `knob.meta.position` (queue) / "" (other sources) |
| 2 (Next) | `knob.title.tracks.next` | Sonos shuffle → `knob.line.tracks.next_shuffle`; next row exists → `knob.line.tracks.next`; last row ∧ `REPEAT_ALL` → `knob.line.tracks.next_wrap`; else `knob.line.tracks.end` | transient > skipping > `knob.meta.tracks.hint` |
| 0 (Prev) | `knob.title.tracks.prev` | Sonos shuffle → `knob.line.tracks.prev_shuffle`; previous row exists → `knob.line.tracks.prev`; first row ∧ `REPEAT_ALL` → `knob.line.tracks.prev` with the **last** row's title (C5-25); else `knob.line.tracks.start` | as index 2 |

- Companion shuffle shows the real neighbour (the queue order is the play order, S01:149).
- Non-queue sources: the line is `knob.line.tracks.now` at every index (C5-25).
- Ring `transport`; `unavailable` bit0 when Previous is not offered, bit2 when Next is not offered (`CT:1236-1237`).

**5.4.4 Skip** (Button 4, index 0 or 2):
- Queue source at an end (`End of queue` / `Start of queue` line): refuse with transient `knob.meta.skip.end` / `knob.meta.skip.start` 1500 ms + `err`, no toast (BS:853).
- Otherwise `transport{direction, expected_group_revision, expected_track_id, index}` (confirmed, `SO:244-310`; under Sonos shuffle Previous uses `avTransport.Previous`, C5-19).
- On `ok`: index → 1 (re-entry), `feedback{ok, skip:±1}` (Sweep), toast `toast.skip.next` / `toast.skip.prev` with the new title from the result state (BS:857). On error: `err`; desktop notice (§12.6).

### 5.5 Seek (Tracks sub-mode)

**5.5.1 Entry** (Tracks 3; S01 §4b; CS §4.4). Preconditions (§3.1 dims): source `queue`, `can_seek` (§9.1). Then:

```text
D   = state.duration_s                                   # 1 ≤ D ≤ 59 999 by can_seek (K1 §4.3)
p   = min(state.position_s + (elapsed since read_at if PLAYING else 0), D)   # extrapolated
Te  = max(0, D - 3)                                      # T_end, seek_margin_s = 3
p'  = min(p, Te)
n0  = ceil(p' / 5)                                       # seek_step_s = 5
max = n0 + ceil((Te - p') / 5)
t(n) = clamp(p' + 5·(n - n0), 0, Te)                     # t(0) = 0:00, t(max) = Te
```

Re-enter `Screen(mode="seek", index=n0)` with profile BINARIS BEER, bounds `0..max`; with D ≤ 59 999 s, `max ≤ ⌈59 996 / 5⌉ + 1 = 12 001`, well inside the control's 0…65 535 (CS §4.1), and the `lap` frame always satisfies K1's `1 ≤ count ≤ 59 999`, `index < count` (`LAP_COUNT_MAX`, K1 §4.3, P5-R11), so the host validator never rejects it (C5-51). Arm the idle timer (3000 ms). No LCD slide (group `tracks`; the `transport ↔ lap` change fires the Reveal, VOC §1.1).

**5.5.2 State.** `SeekState{D, p0: p', n0, max, target_s, pending: bool, due: float|None, inflight: bool, fail_until: float|None, limit_until: float|None, idle_due, track_id}`. **[r2.2]** Plus `landed_s: float|None`, the target of the jump that last landed in the current burst (cleared when nothing is pending); `seek_busy = inflight or (landed_s is not None and target_s != landed_s)` drives `Jumping…`, `activity:"pending"` and the idle deferral (§5.5.4–§5.5.6; C5-68).

**5.5.3 Turns.** `position(n)`: `target_s = t(n)`; `due = now + 0.250` (`seek_debounce_ms`); re-arm idle (`now + 3.0`). The displayed time is frozen at `target_s` (BS:1416; S01:202): a state poll never overwrites it. **Rev 4 (C5-65):** it stays frozen at the target, with `Jumping…` and the Working comet, until the seek ~~is **confirmed** (§9.4: the transport has left `TRANSITIONING` and the position reads within ±2 s of the target), for at most `seek_confirm_ms` (5000)~~ (**[r2.2] superseded**: has landed, i.e. playback has resumed, within `seek_confirm_ms` = 8000; below, C5-68). Sonos reports the target position from the first read while it is still buffering (LC W2: RelTime = target at ≈ 0.5 s, `TRANSITIONING` until 2.64 / 2.69 s), so a position in a poll is never evidence that the jump landed. **[r2.2] (C5-68; R22 CH §3)** "Landed" means **playback has resumed** (the transport has left `TRANSITIONING`), not that a position report has arrived; the deadline is `seek_confirm_ms` = **8000**. A turn during a jump moves `target_s`, so the frozen time follows it at once (§5.5.4 sends it as the one follow-up jump).
`limit(±1)`: re-arm idle (BS:929); at `+1` while `index == max`: `limit_until = now + 1.5` (the line `knob.line.seek.limit`, BS:930).

**5.5.4 Sending.** In `tick()`: when `due` has passed, nothing is in flight and `target_s` differs from the last confirmed target → `request("seek", target_s, expected_group_revision, expected_track_id)`; `inflight = True`. Latest wins: a newer target waits for the in-flight one and is sent next (CS §4.4). The runtime reads the **current** target when the job starts (the volume pattern). **[r2.2] At most one follow-up jump (C5-68):** turns during a jump only move `target_s` (and re-arm `due`); when the jump lands, if `target_s` differs from the landed target, exactly **one** more `seek` is sent with the latest target, as soon as `due` has passed (still 250 ms after the last detent); turns during that jump repeat the rule. Nothing is queued beyond one pending target. `seek_busy` = `inflight` **or** (a jump has landed in this burst **and** `target_s` differs from it): it keeps `Jumping…` and `activity:"pending"` up between the two jumps, so the Working comet never gaps (R22 CH §3; K2 M33).

**5.5.5 Exit.** Button 3, Button 1, Button 2 (then Up next), hold, idle (3000 ms without a turn or `lim`), a track change, a group change, a disconnect.
- Explicit exits **flush** a debouncing target (send it now), then leave (R §8 "A pending target is sent on exit"; CS §4.3). These are the exits the user makes: Button 3, Button 1, Button 2 and hold. (The idle exit cannot find a pending target: the 250 ms debounce always fires first, and the idle exit waits while a seek is in flight.) **[r2.2]** An explicit exit while a jump is in flight keeps the one follow-up target: it is sent when the current jump lands (never two in flight, C5-68), and its result applies silently after Seek was left (C5-16). **[P2a] (C5-77)** A start sent before that landing (`play_items` from Recent or the explorer, the Up next `jump`) **drops** the waiting target, as a track change does (C5-47): the start replaces or restarts the track, so the target belongs to playback that is ending. The jump already in flight still resolves first (a failure still gives `err`, C5-16).
- **The idle exit is deferred while a seek is sending or confirming**, and re-armed for 3000 ms from its completion (C5-15); **[r2.2]** also while a follow-up target waits (`seek_busy`), so the 3 s count starts when the last jump lands (R22 S01 §4b).
- A track change (`track_id` differs in a poll or a result) exits Seek, **drops** any pending target, no shake (S01:203 "If the song changes, Seek exits"; CS §4.3). A group change and a disconnect (§13.4) drop it too. This departs from S01:203 / R §8 "sent on exit" (**C5-47**, kind D): the target was computed against the old song's duration and track id, so sending it would seek the new song (the adapter's track guard would refuse it anyway, `TrackChanged`, §9.4); "sent on exit" applies to the exits the user makes.
- Every exit re-enters Tracks at index 1 (BS:833-837).

**5.5.6 Frame** (VOC §6.2 recommended mapping; K1 decides). `layout:"seek"`, `heading` `knob.heading.seek`, `title` = song title, `ring{style:"lap", index: target_s, count: D}` (the firmware formats the 48 px `m:ss` from `ring.index`), `meta`:

| Condition (first match) | `meta` | `metaTone` |
|---|---|---|
| `inflight` (sent, not landed) **[r2.2]** or a follow-up target waiting after a landing (`seek_busy`, §5.5.4) | `knob.line.seek.jumping` | `meta` |
| `fail_until` not passed | `knob.line.seek.failed` | `error` |
| transient set (e.g. a reason copy for Button 2) | transient | per §2.4 |
| `limit_until` not passed | `knob.line.seek.limit` | `meta` |
| otherwise | `knob.line.seek.length` with `{m:ss}` = D | `meta` |

`activity:"pending"` while `inflight` (the Working comet runs until Sonos lands the jump, S01:202). **[r2.2]** While `seek_busy`: from the first send until the **last** jump lands, ≈ 2.7 s per jump, up to 8 s (R22 CH §3; K2 M33).

**5.5.7 Results.** `ok`: no feedback (silent success, VOC §4.2); `inflight = False`; the confirmed state applies; SongProgress re-posts the new position (`RT:106-107`, `PROGRESS_SEEK_MS`). `not_confirmed` (701/711/timeout; **[r2.2]** timeout = no playback resume within 8 s): stay in Seek at the target, `err`, `fail_until = now + 2.2` (S01:204); a pending follow-up target is dropped with it. A result that arrives after Seek was left: `err` only on failure (C5-16). Expected latency (rev 4, LC W2, playing): ≈ 2.7 s from the send to `ok` (Seek reply 49–61 ms, then ≈ 2.6 s of buffering); the audio is near silent meanwhile, which is why the clock waits.

### 5.6 Up next (screen primary; knob mirrors)

**5.6.1 Open** (Tracks 2 or Seek 2 at `t0`):
- Preconditions: source class `queue` (PLAYING or PAUSED_PLAYBACK) (S01:323; R §7.3). Otherwise refuse per §3.3 with `knob.meta.upnext.airplay` / `.radio` / `.linein` / `.none` and a shake; **the overlay does not open** (S01:95).
- `upnext = UpNextState(P, T, focus=P−1, rows={}, regime, ...)`; `parent_index` = the Tracks index. Re-enter at once (mode change, position `P−1`, bounds §5.6.2). Effect `upnext_open` (payload §11.1: `t0`, the loaded rows, `now`, `focus`, `count`, `context`, `shuffle`, `likes_known`, `loading`, `control_id`, `control_min`, `reduced_motion`, `foreground_hwnd`); clear any toast (BS:861). A `refused(upnext, …)` answer returns the knob to `tracks` (§13.5).
- Reads (§9.7.1): `queue_window(start=max(0, P−1−10), count=21)`; when `U = T − P ≤ 60` and the window does not cover rows P+1..T, also `queue_window(start=P, count=U)` (1-based rows P+1..T; the shuffle plan needs them, §9.5.2). Until rows land: `Loading queue…` state.

**5.6.2 Bounds.**
- Normal (and companion shuffle): `0..T−1`.
- Sonos native shuffle regime (§5.6.5): rows 0..P−1 (played + now) then **one card row** at index P → bounds `0..P` (BS:869 `qLen`) — subject to OQ-2. On the wire the card is `ring.card:true` with `count = P + 1`, `now = P − 1` (K1 §4.4, VOC-K1a; §5.6.4); OQ-2's H1 variant is the same form with `count = 2`, `now = 0`.

**5.6.3 Row model** (`UpNextRow`, filled by §9.7): `row` (1-based), `title`, `artist`, `album`, `song_id`, `catalog: bool` (the catalog batch returned it, C5-43), `duration_s`, `track_number`, the K4 §13.2 art keys (`art_template`, `art_max`, `art_bg`, `art_ink` from the catalog batch; `sonos_art` = the row's Sonos `/getaa` URL, always present, used when the row has no Apple art; C5-57), `accent`, `role ∈ {played, now, next, upcoming, card, placeholder}` (`next` = P+1 only, BS qRows tag), `segment ∈ {base, playnext, foreign}` (ledger, §9.7.3), `liked ∈ {True, False, None}`.

**5.6.4 Frame.** `layout:"upnext"`, `heading` `knob.heading.upnext`, ring `selection` + `now` = P−1 (VOC §3.1; K1/K2).

| Focused row | `title` | `subtitle` | `meta` |
|---|---|---|---|
| any loaded row | row title | row artist | transient > `knob.meta.upnext.position_playing` (focus = now) / `knob.meta.position` |
| a placeholder (not loaded) | "" | "" | `knob.meta.upnext.loading` while the first window is out, else `knob.meta.position` |
| the Sonos card | `knob.title.upnext_sonos_card` | "" | `knob.meta.position` |

Ring wire form (K1 §4.4, §4.6; K2 5.1.4, M31; C5-61):
- **Before the first window lands** (the whole queue is loading): `ring.style:"off"` + `activity:"loading"` (Working comet only).
- **After it:** `selection` with `index` = the focus, `count` = T (or P + 1 with the card), `first` by the window rule (VOC §3.4), `now` = P − 1, `colors[]` = each row's album accent; a **placeholder** row outside the loaded windows goes out with colour **0** (a warm entry, class Q 0.45 when upcoming), never as `loading`. `activity` is `pending` while a shuffle runs **or a like / unlike is in flight** (**[r2.2]** a like; there is no unlike) (rev 4: the request plus its read-back take ≈ 0.6–1.6 s, so the Working comet says "working" until the pink bloom or the shake; C5-62), else `idle`.
- **Sonos native shuffle regime** (`U > 60`, §5.6.5): the rows 0 … P − 1 (played + now) plus the card at index P: **`card:true`**, `count = P + 1`, `now = P − 1`, the card's `colors` slot **0**. The card is identified only by `card` (K1 P5-R24).
- **Up next frames never set `ring.unavailable`**: Up next rows have no unavailable state (BS:1318-1321), and both parsers strip it on `upnext` anyway (K1 §4.4). A non-catalog row only dims Like (`not_catalog`).

Art identity: the focused row's cover (VOC §1.1).

**5.6.5 Shuffle (Button 2; U4; S01:355-364).** State: `active = companion_record_valid or play_mode in SHUFFLE*`; `regime = "companion" if U ≤ 60 else "sonos"` (evaluated at the press; `U = T − P`, every upcoming row, as the S01:357-360 table counts them). `pn` = the upcoming rows whose ledger segment is `playnext` (§9.7.3), in their current order (newest block first); `U_r = U − |pn|` = the rows that move.

**The Play-next block stays directly after the current song whether shuffle turns on or off** (R:142 "A Play next block stays after the current song", not limited to off; BS:873-878 builds `head + pn + rest` on both edges, shuffling `rest` when turning on and sorting it when turning off; S01:362 repeats it for off) (C5-45).

| Press when | Action | Knob / screen |
|---|---|---|
| inactive, `U ≤ 60`, `U_r ≥ 2` | plan = `pn` offsets first (current order), then a Fisher–Yates permutation of the other `U_r` offsets with `self.rng` (§9.5.2); `shuffle_job(on, companion, plan, playnext_offsets)`; effect `upnext_rows{t0, reason:"shuffle", rows: the loaded window in the planned order, focus: P, shuffle:"companion"}` (K4 fades the rows out 160 ms IN at `t0` and re-enters them at `t0 + 200`, K4 §8.5) | at `t0 + 200`: the knob re-enters, focus → P (row P+1) = `min(n−1, now+1)` (BS:881) (C5-9: turns ignored in [t0, t0+200)); on **acceptance** (§8): `feedback{ok, moment:"shuffle"}` + transient `knob.meta.shuffle.on` 1500 ms |
| inactive, `U > 60` | `set_shuffle(on)` (native) | on verified completion (time `t1`): `ok+shuffle`, transient `knob.meta.shuffle.sonos`; effect `upnext_rows{t0: t1, reason:"shuffle", rows: played + now, card: {n}, shuffle:"sonos"}`; at `t1 + 200` the knob re-enters with bounds `0..P`, focus = the card. Sonos picks the order of every upcoming row, so a Play-next block is **not** kept in this regime (the card says the order isn't shown; C5-45) |
| active, companion record | `shuffle_reorder(off)` (restore, §9.5.3) | effect `upnext_rows{t0, reason:"shuffle", rows: the **restore target order** (Play-next block first, then original order), shuffle:"off"}` (**[P2a]** the controller's preview of it: the base rows by the ledger's start order, which is not always the order the adapter restores, §9.5.3 limitations; **[P3]** by the restore record's order when the controller knows the record, which is the order the adapter restores, C5-79); knob re-entry at `t0 + 200`; on acceptance: `ok+shuffle`, `knob.meta.shuffle.off` |
| active, Sonos `SHUFFLE*` (either regime) | `set_shuffle(off)` (C5-17) | on completion: `ok+shuffle`, `knob.meta.shuffle.off`; re-read the window; when it lands (time `t1`) `upnext_rows{t0: t1, reason:"shuffle", shuffle:"off"}` and the knob re-enters at `t1 + 200` with bounds `0..T−1` |
| `U ≤ 60`, `U_r < 2` and inactive | ignored (`nothing_next`, C5-41) | — |

Failures: `queue_changed` → `err` + `knob.meta.shuffle.queue_changed` (2400 ms, error) and the record is dropped; any other failure → `err` + `knob.meta.shuffle.failed` (the record is kept when the queue is still attributable, §9.5.5); in both cases the window is re-read and `upnext_rows{reason:"queue_changed"}` re-renders the true order (§8).

**5.6.6 Like (Button 3; S01:342-353; LC).**
- Availability per §3.1 (`likes_unknown` while the focused row's `liked` is `None`; `not_catalog` when `catalog` is false; `sonos_card` on the card).
- A known sign-in expiry (`runtime.music_signin_expired`) sends **no request**: transient `knob.meta.like.signin_expired` (2200 ms, error), `err`, and the exit toast `toast.like.signin_expired` is armed for this overlay session; it shows only after a `back` close (C5-36).
- **Rev 4: a liked row under `unlike_strategy == "add_only"`** (the default until W4b passes, C5-63); **[r2.2] a liked row, always** (add-only is final, C5-67): the press is refused per §3.3 with `unlike_unavailable` (transient `knob.meta.like.unlike_in_music` = **`Unfavourite in Music app`**, meta tone, **`like_fail_meta_ms` 2200** (was `reason_meta_ms`); `feedback{kind:"err"}`, the Head shake). Button 3 stays enabled with `lit:"on"`, which the knob draws as tone `liked` (PINK 0.30, filled `#A3244A` heart); label `Liked`; hint `[3] Liked` (R22 CH §1). **No request**, no patch; the heart stays liked and PINK. The row's heart can then be cleared only in the Music app, and the next `ratings` read shows it (a `data` patch, no animation).
- Otherwise `like{song_id, row}` (not liked) (**[r2.2]** only: the `unlike{song_id, row}` effect of rev 4's `favorites_delete` is withdrawn, C5-67); add to `like_inflight`; the Up next frame carries `activity:"pending"` until the result (§5.6.4).
- Results (§8, §9.8.2): ok like → `feedback{ok, moment:"like"}` (pink bloom), transient `knob.meta.like.on` 1500 ms, `upnext_rows{reason:"likes", rows:[{row, liked:true}]}` (the heart pops after confirmation, K4 §8.3); ~~ok unlike → `feedback{ok, moment:"unlike"}` (no LED effect), `knob.meta.like.off`, `upnext_rows{reason:"likes", rows:[{row, liked:false}]}` (the unlike animation, K4 §8.3)~~ **[r2.2] withdrawn**: no unlike, no `Like removed`, no heart-off animation (R22 CH §1); `not_catalog` → mark the row non-catalog (a `data` patch; **[r2.2]** its heart becomes the 15 % outline with no Like, not removed, K4 §8.3), `err`, `knob.meta.like.not_catalog`; `signin_expired` → as above; `failed` / `rate_limited` → `err`, `knob.meta.like.failed` (**[r2.2]** `Didn’t save · try again`, error tone, `like_fail_meta_ms` 2200, with the Head shake; R22 CH §1), no patch; ~~**`unlike_unsupported`** (rev 4: Apple refused the favourites `DELETE` with 400 or 405, §9.8.2) → the runtime sets `unlike_strategy = "add_only"` for the session (logged once, status code only), `err`, transient `knob.meta.like.unlike_in_music`, no patch (the heart stays liked)~~ **[r2.2] withdrawn** (no unlike request exists, C5-67).
- **A like that Apple accepted but did not show in time** (rev 4): the 202 came, but the read-back did not see rating 1 within `like_confirm_ms` (§9.8.2) → `failed` as above, and the runtime schedules one `ratings([song_id])` read `like_late_check_ms` (5000) later on the lookahead lane; if it reads 1, a `data` patch sets the heart (no pop, no moment). An accepted favourite is never re-sent automatically.
- Heart states that arrive from the ratings batch (§9.7.2; rev 4: the only heart source, C5-64) go out in `data` patches: they set the state without the pop. Only `likes` patches animate (C5-54).
- The row's `liked` updates on success only. The Favourites cache is marked stale (Favorite Songs changed, CF:15).

**5.6.7 Play (Button 4 at `t0`; BS:884-890).** Guards §3.1 (placeholder `loading`, card `sonos_card`). Dispatch `jump{row, …}` at `t0`; `play_until = t0 + 380`; effect `upnext_close{t0, reason:"play", close_at_ms:380}`; at `t0 + 380` → Home with `Starting…` (§5.3.5 steps 2–4 apply). The name for the toast is the row title; the accent is the row's album accent. The focused row equal to the now-playing row restarts it (C5-35).

**5.6.8 Changes while open** (A05 §5.7; 00 G2(3)):
- `playlist_position` changes (a song ended): re-tag roles live; the focus does **not** follow (03 §3.5); `ring.now` moves.
- `queue_revision` changes (an edit elsewhere, or a Play next / shuffle of ours finishing): drop cached rows, re-read the window around the focused row, keep the focus by identity (`signature`, occurrence), clamp if it is gone, and re-render with `upnext_rows{reason:"queue_changed"}`; re-enter only if the index or bounds changed, and only by the passive rule (§6.4). Revision changes seen **while an exclusive job of ours runs** wait for its completion (§1.1).
- The source leaves the queue → close with reason `source`, → `tracks` (VOC §7.3).
- Group change → close `group`, → `tracks`.

**5.6.9 Back / hold / limit.** Back → `tracks` at `parent_index` (close `back`; the armed sign-in toast shows 360 ms after it, §12.4). Hold → `home` (close `hold`; the armed toast is dropped, C5-36). `limit(±1)` → `upnext_highlight{index, control_id, bump}` (14 px bump). A click on the focus plate arrives as `click_action(upnext)` = Button 4 (§11.3).

### 5.7 Windows and snap

**5.7.1 Open.** `open_windows()` only when `mode == "home"` and no `windows_open` is pending (`CT:575-579` without the any-mode entry): `request("windows_open")` → synchronous snapshot + show (`RT:1431-1433`); `complete` → `Screen(mode="windows", windows=WindowsState(...))`, re-entry (flip +1). `WindowsState{items, origin, index, left: id|None, right: id|None, desk_open: origin id, snap_busy: SnapJob|None, advance_due, latched_close: reason|None, turned_since_snap: bool, failure: {side, reason, until}|None}`.

**5.7.2 Frame.** `layout:"windows"`, no heading; `title` = window title, `subtitle` = the label's **display** app name (A05 §2.7; VOC §9.1 `{App}`), `meta`: transient > `knob.meta.snap.left_set` (left only) / `knob.meta.snap.right_set` (right only) > `knob.meta.windows.switching` (switch out) > `knob.meta.windows.closed` (highlighted window closed) > "". Empty snapshot: `knob.title.no_windows`; Buttons 2/3/4 dim `empty`. Ring `selection`, app accents (VOC §3.5).

**5.7.3 Snap** (Button 2 = left, Button 3 = right, on highlighted window `w`; S01 §7 "Snap"; BS:1071-1091):

| Case | Controller |
|---|---|
| `w` closed | dim `closed` → refusal §3.3 |
| `w` already holds this side | ignored (C5-11) |
| a snap is in flight | ignored (§3.4) |
| otherwise | 1. `snap_busy = SnapJob(w, side, t0)`. 2. Effect `windows_snap{t0, index, side, target_rect, place_at_ms:360}` (`target_rect` = the physical `rcWork` half of the picker's monitor, K4 §9.5-§9.6). The presenter posts it; its pre-checks run on `NanoD-snap` (≤ 5 ms: identity, `IsHungAppWindow`, integrity level; K4 §9.5 t = 0). 3. **Pre-check failure** = event `snap_result(side, "hung" \| "move_rejected")` → `failure = {side, reason, until: now + 2.4}`, `err`, transient `knob.meta.snap.hung` (`hung`) or `knob.meta.snap.move` (`move_rejected`, e.g. a window of a higher integrity level) (2400 ms, error), side not assigned, `snap_busy = None`. 4. **Acceptance** = event `snap_result(side, "accepted")` (C5-18, C5-53) → assign the side (if `w` held the other side, that side clears: a move, BS:1078), `feedback{ok, moment:"snap", side:±1, color: w.accent}` (half-wash), slot button `lit:"on"` + colour. 5. At `t0 + 360` the presenter places the window once, then verifies (≤ 200 ms, UWP ≤ 400 ms, K4 §9.6); event `snap_result(side, "ok")` → `snap_busy = None`; `snap_result(side, "move_rejected" \| "cant_fit")` → unassign the side, `failure` 2400 ms, `err`, transient `knob.meta.snap.move` / `.fit`. 6. On acceptance with both sides assigned → `close_pair_due = t0 + 820`. 7. Else on acceptance `advance_due = t0 + 420`: the highlight moves to the **next window after `w` in list order, wrapping at the end, that is neither assigned nor closed** (S01:405 "advances to the next unassigned window"; C5-46), by re-entry — **unless a detent arrived since `t0`**, which cancels the advance (C5-10); no advance when no window qualifies. Example: windows A, B, C, D, nothing assigned; snapping C highlights D; then snapping D highlights A. |

- Outcome names are VOC §8.5's (`hung`, `move_rejected`, `cant_fit`) plus the acceptance event `accepted`; the controller never waits synchronously on the presenter (K4 §2.3: every call posts and returns).
- Latched close: a Back or hold pressed while `snap_busy` is set is stored in `latched_close` and executed when the snap resolves (a pre-check failure, or the placement result; **≤ 800 ms**: K4 §9.6 resolves every snap by `t0 + 800`, by its worker or by the carousel's backstop, before the 820 ms pair close) (C5-12). If no `snap_result` arrives within 1000 ms of `t0` (`snap_result_timeout_ms`), the controller treats the snap as `move_rejected` (logged), so a lost event never leaves the picker latched; with K4's deadline this last resort never fires in normal operation. **[P3]** Only Back and hold are latched (the phase-3 review item WP5R-2): a `lock`, `sleep` or `idle` close during a snap closes the picker **at once** (§5.7.4; K4 §15 "instant"), with its own `reason` and U12 from the sides assigned at that moment, and replaces a latched Back or hold; a `snap_result` that arrives after it is dropped (the picker is no longer the Screen). The move then runs behind the lock screen or the sleep, and an `idle` close cannot meet a snap in practice (the snap press is knob input).
- Pair close at `t0 + 820`: effect `windows_close_pair{left, right, focus: the side snapped last}` (00 U12 sub-rule) → mode `home` (re-entry), exit toast `toast.snap.pair` (§12).

**5.7.4 Back / hold / lifetime closes.** Effect ~~`windows_cancel{origin, home:true, complete: side|None}`~~ **[P3]** `windows_cancel{origin, home:true, complete: side|None, reason}` (C5-78): `reason` is the close (`back` \| `hold` \| `lock` \| `sleep` \| `idle`, VOC §7.3), latched with the close as before (**[P3]** a Back or hold behind a snap, C5-12; lock, sleep and idle are never latched, §5.7.3); the picker hides at once for `lock`, `sleep`, `idle`, plays its exit for `back` and `hold`, and never restores focus for `lock` or `sleep` (K4 §15), so a `cancel_result(restored=false)` after those two raises no desktop notice (`Original window no longer available` stays for the others). When exactly one side is assigned and the origin window (`desk_open`) is not the snapped one, `complete` names the empty side, and the adapter moves the origin there with the same non-activating recipe **at close only** (S01:408-411; 00 U12; VOC-D01), then restores focus to it. The presenter answers with the event `cancel_result(restored: bool, completed: bool)` (C5-53). Exit toast `toast.snap.one_side` only after `cancel_result(completed=true)` on a `back` close (BS:1061), at `max(close + 360 ms, the event)` (§12.1). Applies to `back`, `hold`, `lock`, `sleep`, `idle`; not to `disconnect`, `focus_lost` or `display` (VOC-R15; K4 §15). No toast on Back without a completion (VOC-N21), and none on `hold` (VOC §7.3; C5-36).

**5.7.5 Switch** (Button 4): `windows_activate{item, index}` (synchronous, verified, `RT:1434-1435`; CAR §1). ok → `origin = None`, mode `home` (re-entry), `feedback{ok}` (plain ok: wash in the app accent via AL D7 row 9, or green bloom for a warm app, VOC §4.2), exit toast `toast.switch`. Snapped windows stay where they are (S01 §7; 03 §4.8). Failure → `err`, transient `knob.meta.windows.no_focus` (error), unfreeze the highlight (`CT:326-330`).

**5.7.6 Focus lost.** `dismiss_windows()` (`CT:698-704`): hide without focus restore, no U12, → `home`.

---

## 6. Re-entry helper and input blackouts

### 6.1 What a re-entry costs

Every host-driven change of position, bounds or profile is a new `control` (a new id, `CT:296-299`). From its send until `ready` the knob is **blind** (00 G2; A04 §6.1):
- `cc_input_id()` is 0, so every `kd`, `ku` and position is dropped by the firmware (a long press of slot 0 is the exception: it is latched and sent as `kh` right after `ready`, K1 §11.2 step 5);
- the motor runs `move(0)` with no detents, and motion is rebased away at `ready`;
- entering waits for the motor, HMI and LCD acks. In the R5-off firmware builds (binaries B and C, K1 §12.6) that includes a 46–154 ms JPEG decode when the new frame names a new cover; in binary A (R5 on) the render only posts the decode and acks at once (K1 §12.5.5, P5-R26).

### 6.2 The helper

```python
def _reenter(self, cause: str, *, index: int | None = None) -> None:
    """One control for one host-driven move. Bounds and profile come from the new Screen;
    index (when given) is clamped into the new bounds; the embedded frame is the post-ready
    projection (CT:332-339), with the entry art rule of §6.3."""

def _schedule(self, at: float, cause: str, fn) -> None:
    """Run fn in tick() at `at` if the Screen (view_id) that scheduled it is still current."""
```

| Cause | When | Input guard before it | Index / bounds | Source |
|---|---|---|---|---|
| mode change by a button (Browse, Tracks, Open, Up next, Seek on/off, Back, Switch ok) | at the press or completion | — | the new mode's entry (§2.1) | `CT:296-299` |
| explorer tab switch | **t0 + 190 ms** (`tab_swap_ms`) | turns and tab presses ignored in [t0, t0+190) | new source's bounds and remembered index | BS:1038; 00 G2 |
| explorer / Up next Play | **t0 + 380 ms** (`overlay_play_close_ms`) → Home | turns, presses and hold ignored in [t0, t0+380) | Home | S01:225; BS:1044, :888 |
| Up next shuffle | **t0 + 200 ms** (`shuffle_swap_ms`) | turns and Button 2 ignored in [t0, t0+200) | focus = P (row P+1); bounds unchanged (companion) | BS:881 |
| Sonos-shuffle regime change | `t1 + 200 ms`, `t1` = the time its `upnext_rows{reason:"shuffle"}` patch is sent (the verified completion, or for off the re-read window) | turns and Button 2 ignored in [t1, t1+200) | bounds `0..P` (on) / `0..T−1` (off) | §5.6.5 |
| snap advance | **t0 + 420 ms** (`snap_advance_ms`), armed at acceptance, cancelled by any detent since t0 | — | the next unassigned, open window after the snapped one, wrapping | S01:405; C5-46; C5-10 |
| snap pair close | **t0 + 820 ms** (`snap_pair_close_ms`) → Home | — | Home | S01:406 |
| Tracks skip ok | at completion | — | index 1 | `CT:913-916` |
| Recent bounds growth (total unknown) | passive rule §6.4 | — | new `max` | §5.2.2 |
| Up next queue change | passive rule §6.4 | — | focus by identity | §5.6.8 |
| favourites list refresh while on that tab | passive rule §6.4 | — | focus by id | §5.3.2 |
| Seek idle exit | 3000 ms idle (deferred while in flight) | — | Tracks 1 | §5.5.5 |
| knob reconnect | `set_hardware(True)` | — | Home (C5-2) | `CT:513-523` |

Controller timers resolve on the 25 ms runtime tick (`UI:99`). Each timed presenter effect carries `t0` = the controller's clock (`time.perf_counter`, QPC) when it handled the press, and the presenter anchors every scheduled leg (+190, +200, +360, +380 ms) to that `t0`, not to its own receipt time (K4 §0.6, §2.3, §4.6.4; VOC-R25; C5-53). So the screen leg lands exactly at `t0 + d` and the knob re-entry between `t0 + d` and `t0 + d + 25 ms`.

### 6.3 Entry art rule (C5-13; 00 G2(2))

The frame embedded in a `control` keeps the **previous frame's `artKey`**; the new cover key goes out in the **first frame after `ready`**. The decode then runs after the knob accepts input, not inside entering. Covers swap instantly anyway (S01:117). Applies to every re-entry, **unconditionally** (the host can tell binary A from B/C only through `diag`, and one rule is simpler to test). K1 confirms (§12.5.5, P5-R26; OQ-4 closed): a `control` that keeps the previous `artKey` is valid in every build; in R5-off builds (B, C) entering waits for the decode, so this rule shortens the blind window by 46–154 ms at the cost of the decode landing in the first render after `ready`, usually inside the 380 ms slide (frames skipped, the slide still ends on time); in binary A entering never waits, and the rule only delays the cover by ≈ `enterMsLast`.

### 6.4 Passive rule (C5-14; 00 G2(3))

A re-entry caused by something the user did not do on the knob (a list grew, the queue changed elsewhere, a refresh) waits until **400 ms after the last detent** of the current control. Exception: when the focus sits on the loaded end of a growing Recently Added list (the user is waiting against the End stop), the growth re-enters at once. While deferred, frames already show the new content; only bounds and position wait.

### 6.5 Diagnostics

When the knob reports `enterMsLast` / `enterMsMax` in `diag` (VOC §6.1, K1), the runtime logs them once per minute at debug level with the cause of the last re-entry. Gate H3 reads them (00 §4.5).

---

## 7. Timers

Names are VOC §10 where they exist. All run on the controller's injected clock, in `tick()`, unless noted.

| Id | Value | Starts | Effect | Source |
|---|---|---|---|---|
| `hold_ms` | 600 | firmware (deferred past `ready` when entering, K1 §11.2) | `kh` → Home (§4.2) | S01:41 |
| `seek_debounce_ms` | 250 | each Seek detent | send the latest target | S01:202 |
| `seek_idle_ms` | 3000 | Seek entry, each detent, each `lim`, each seek completion | exit Seek (deferred while in flight) | S01:203; BS:929; C5-15 |
| `seek_confirm_ms` | **[r2.2] 8000** (r2.2; rev 4: 5000; was 3000) (adapter, 100 ms polls that yield between them, §1.1) | the `Seek` reply (**[P2a]** an Up next `jump`: the `Seek(TRACK_NR)` reply, C5-74) | **[r2.2]** landed when playback has resumed (the transport has left `TRANSITIONING`; the position is not a condition, R22 CH §3, C5-68); rev 4: confirmed when `TRANSITIONING` has been left **and** the position is within ±2 s of the target; else `not_confirmed` (never resent). **[P2a] (C5-74)** The same window bounds an Up next `jump` (§9.6.2): played on the first `PLAYING` read at `row` (after a `TRANSITIONING` read, or ≥ 1.0 s after the reply when none was seen; PAUSED_PLAYBACK, STOPPED or another row keep polling); none by then → `start_failed` (the start's failure path, §8), never resent | CS §4.4; LC W2 (2.64 / 2.69 s to leave `TRANSITIONING`; the 3 s window had ≈ 0.3 s to spare); C5-65; **[P2a]** C5-74 |
| `seek_fail_line_ms` | 2200 | Seek failure | `Didn’t jump · try again` | S01:204 |
| `seek_limit_line_ms` | 1500 | `lim +1` at `max` | `Stops 3 s before end` | BS:930 |
| `reason_meta_ms` | 2000 | refused press | reason copy | S01:50 |
| `signin_meta_ms` | 2200 | Like with sign-in expired | `Sign-in expired` (error) | BS:825 |
| `like_readback_ms` | 250 (rev 4) | the like `POST` answered (**[r2.2]** the unlike `DELETE` is withdrawn) | the next `GET /v1/me/ratings/songs?ids=<id>` read-back (first at +250 ms) | LS 22:06 UTC (rating 1 readable ≈ 1 s after the 202); C5-62 |
| `like_confirm_ms` | 4000 (rev 4) | the like `POST` answered (**[r2.2]** like only) | read-back not matched → `failed` (§5.6.6) | C5-62 |
| **`like_fail_meta_ms`** **[r2.2]** | 2200 | a press on a liked row (`unlike_unavailable`) or a like save failure | `Unfavourite in Music app` (meta tone) / `Didn’t save · try again` (error tone), each with the Head shake | R22 CH §1 ("for 2.2 s"); R22 BS:827-828; C5-67 |
| `like_late_check_ms` | 5000 (rev 4) | a like read-back that timed out | one `ratings([id])` read; rating 1 → a `data` patch (no pop) | C5-62 |
| `prefetch_resolve_rest_ms` | 400 (rev 4) | each detent on Recently Added (knob or explorer recent tab) | pre-resolve the focused item, then its neighbours | LC W1 (uncached resolve 3–6 s); C5-66 |
| `fail_meta_ms` | 2400 | Play next / snap / shuffle failure | error copy; snap slot outline | S01:216, :412 |
| `queued_meta_ms` | 1500 | Play next ok | `Queued next` | S01:215 |
| `feedback_meta_ms` | 1500 | Like / Shuffle ok (**[r2.2]** no Unlike), skip refused at an end | their copy | BS:830, :882, :853 |
| `partial_status_ms` | 3000 | playlist started partly | `Playing {k} of {n}` | S01:228 |
| `start_fail_status_ms` | 2600 | start failed / album blocked | `Didn’t start` / `Album unavailable` | BS:993 |
| `group_changed_ms` | **[P2a]** 2600 | a `group_revision` change seen in a state poll or result while online; a start or a volume write that fails with `group_changed` (**[P2a]** a seek, shuffle or transport that fails with it shows its own failure first; the next state poll then starts this, §9.10) | `Speaker group changed` on the current line (Home `status` twin, else `meta`, C5-56), ~~`meta` tone~~ **[P2b]** `error` tone (§9.10; R-j) | the design gives no duration (R22 S01 App C); = `start_fail_status_ms` (BS:993); C5-76 |
| `overlay_play_close_ms` | 380 | explorer / Up next Play | close + Home | S01:225 |
| `tab_swap_ms` | 190 | tab press | source switch + re-entry | BS:1038 |
| `shuffle_swap_ms` | 200 | Shuffle press | rows re-enter + re-entry | BS:881 |
| `snap_place_ms` | 360 | snap accepted | the window moves once | S01:403 |
| `snap_advance_ms` | 420 | snap accepted (one side) | highlight advance | BS:1090 (timing); S01:405 (target, C5-46) |
| `snap_result_timeout_ms` | 1000 | `windows_snap` sent | a missing `snap_result` counts as `move_rejected` (last resort; K4 resolves every snap by `t0 + 800`, `snap_deadline_ms`, K4 §9.6) | C5-53 |
| `snap_pair_close_ms` | 820 | second side accepted | picker closes | S01:406 |
| `passive_quiet_ms` | 400 | each detent | passive re-entries may run | 00 G2(3) |
| `exit_toast_delay_ms` | 360 | an overlay close | its exit toast | S01:422 |
| `toast_hold_ms` | 1800 | toast shown (presenter) | fade out | S01:421 |
| `overlay_idle_s` | 60 | each knob input while an overlay is open | close `idle` | S01:426 |
| `volume_hide_ms` | 1400 | each Home detent | hide the reveal once confirmed | S01:153 |
| `external_reveal_ms` | 2600 | a volume change elsewhere | reveal + `Changed on Sonos` | S03 |
| `paused_idle_ms` | 4000 | a confirmed pause | idle row | S03 |
| state poll | 1000; **2000 while an exclusive queue job runs** | tick | `state` request unless a transport or a volume write is out (`CT:727-729` extended); during an exclusive job it runs between the job's steps (§1.1), and its `queue_revision` changes wait for the job's completion | CS §1; C5-48 |
| start staging deadline | `6 + 0.15·N` s (N = songs) | the Sonos phase of `play_items` starts | staging not finished → rollback → `start_failed` (§9.2) | C5-37 |
| resolve deadline | 20 s | a `resolve` starts | `start_failed` / `nothing_added`, nothing staged (§9.8.7) | C5-37 |
| Tracks neighbours | on `(queue_revision, P)` change | Tracks | `queue_window(P−2, 3)` | A05 §5.3 |
| favourites refresh | 600 s staleness; 429 back-off 30 s then 120 s | explorer open / refresh | `favourite_playlists` | CF §5 |
| Recently Added warm-up | 10 s after start, then every 600 s (unchanged) | Home | page 1 copy | `RT:100-101` |
| resolve cache TTL | 1800 s | a resolve | cache entry expires | §9.8.7 |
| Motion re-check | at once on `system(motion)`; 5000 as a backstop | presenter event / tick (Settings `system`) | `reducedMotion` latch | §14.3 |

**Reduced motion changes none of these** (C5-32): S01 §10 changes what the knob LCD, LEDs and overlays draw, not when the state changes.

---

## 8. Confirmation policy (VOC-D03; 00 U11)

"Acceptance" = the service's own preflight passed and the action is committed; "verified" = the adapter's read-back confirmed the end state. `ok`/`err` are `feedback.kind`; moments are VOC §4.

| Action | Knob before the result | `ok` sent when | `ok` carries | Knob copy on ok | Toast on ok | On failure |
|---|---|---|---|---|---|---|
| Volume (Home turn) | reveal, `Setting…`, pending span | — (silent) | — | reveal hides | — | `err`, reveal returns to the confirmed value (`CT:836-840`) |
| Play/Pause (Home 1) | status `Starting…` / `Pausing…` | — (silent; Fill/Drain come from `playing`, AL D8) | — | — | **none** (S01:423) | `err`; notice (§12.6) (**[P2a]** likewise for `group_changed`: no knob copy until the next state poll shows `Speaker group changed`, §9.10) |
| Skip (Tracks 4) | meta `Skipping…` | verified (`SO:244-310`) | `skip:±1` (Sweep) | back to Neutral | `toast.skip.next` / `.prev` | `err`; notice (**[P2a]** `group_changed` as Play/Pause) |
| **Start** (Recent 4, Explorer 4, Up next 4) | **Home at once** (Recent) or at 380 ms (overlays): `Starting…`, comet, Home 1 dim (U11) | verified (`play_items` / `jump` confirmed PLAYING; **[P2a]** `jump` by the §9.6.2 landing rule, ≤ 8 s, C5-74) | `moment:"started"`, `color` = the item's accent (VOC-R07) | "" (album, song, track, full playlist); `knob.status.partial` 3000 ms (playlist partly playable) | `toast.start.ok` / `toast.start.partial`, ≥ 360 ms after the overlay close (§12.3) | album blocked: `err`, `knob.status.album_blocked` 2600 ms, `toast.start.album_blocked`; **[P2a]** `group_changed`: `err` + `knob.status.group_changed` (`Speaker group changed`, `group_changed_ms` 2600, ~~`meta` tone~~ **[P2b]** `error` tone, R-j), **no** `start_failed` copy and **no** toast (§9.10, C5-76); otherwise `err`, `knob.status.start_failed` 2600 ms, `toast.start.failed` |
| **Play next** (Recent 3) | meta `Queueing…` → `Queueing… {k} of {n}` (rev 4: a pre-resolved item starts at `Queueing… 0 of {n}` with no lookup, C5-66); **[r2.2]** meta `Finding songs…` until the first song is queued, then `Queueing… {k} of {n}` (k ≥ 1; never `0 of {n}`), ≈ 0.5 s per song (C5-69), comet from the press to the result, Recent 3/4 dim | verified (slice read, §9.3) | `moment:"queued"` (Sweep from 0) | `knob.meta.playnext.ok` 1500 ms | `toast.playnext.ok` | per outcome (§9.10): `err` + red meta 2400 ms + toast |
| **Seek** | `Jumping…`, comet; the clock frozen at the target until confirmed (**[r2.2]** until the last jump lands, a follow-up jump included; a turn moves the frozen target) | verified (rev 4: `TRANSITIONING` left **and** the position within ±2 s of the target, ≤ 5 s; live ≈ 2.7 s; C5-65; **[r2.2]** landed = playback resumed, ≤ 8 s, C5-68) | — (silent) | `of {m:ss}` | — | `err`, `Didn’t jump · try again` 2200 ms, stay in Seek (**[P2a]** also for `group_changed`; the next state poll then exits Seek to Tracks with `Speaker group changed`, §9.10) |
| **Shuffle, companion** | rows re-enter at 200 ms from the plan; comet while moving | **acceptance** (job preflight: rows match, record persisted, C5-18) | `moment:"shuffle"` (Scatter) | `knob.meta.shuffle.on` / `.off` 1500 ms | — (overlay open) | `err` + `queue_changed` / `failed` copy 2400 ms; rows re-read (**[P2a]** `group_changed` gives the `failed` copy; the next state poll closes Up next `group` with `Speaker group changed`, §9.10) |
| **Shuffle, Sonos** | — | verified (`GetTransportSettings` read-back) | `moment:"shuffle"` | `knob.meta.shuffle.sonos` / `.off` | — | `err` + `knob.meta.shuffle.failed` (**[P2a]** also for `group_changed`, then the group copy from the next state poll, §9.10) |
| **Like / Unlike** (**[r2.2]** Like only: add-only is final, C5-67) | rev 4: the Working comet (`activity:"pending"`, ≈ 0.6–1.6 s) | verified (rev 4): like = `POST /v1/me/favorites` 202 **and** rating 1 read back; ~~unlike (`favorites_delete` only) = `DELETE /v1/me/favorites` 2xx **and** no rating read back (§9.8.2)~~ (**[r2.2]** withdrawn). A press on a liked row is refused at the press (no request) | `moment:"like"` (pink Bloom); ~~`moment:"unlike"` (nothing)~~ **[r2.2]** never sent | `knob.meta.like.on` 1500 ms (**[r2.2]** `.off` withdrawn); heart pops on screen after confirmation | — (overlay open) | `err` + copy (§5.6.6: **[r2.2]** `Didn’t save · try again`, 2200 ms); liked-row refusal: `knob.meta.like.unlike_in_music` (**[r2.2]** `Unfavourite in Music app`, 2200 ms) + shake |
| **Snap** | fly on screen at t0 | **acceptance**: the presenter's `snap_result(side, "accepted")` after its ≤ 5 ms pre-checks (K4 §9.5 t = 0) | `moment:"snap"`, `side`, `color` | `knob.meta.snap.left_set` / `.right_set` | pair: `toast.snap.pair` after close | pre-check (`hung`, `move_rejected`) or placement (`move_rejected`, `cant_fit`) failure: `err`, slot outline 2400 ms, `knob.meta.snap.hung` / `.move` / `.fit` |
| **Switch** (U11: stays confirmed) | `Switching…` | verified (activation, ≤ 100 ms, CAR §1) | plain `ok` (wash in the app accent or green bloom, VOC §4.2 rows 9–10) | → Home | `toast.switch` after close | `err`, `Didn’t come forward · retry` |
| Picker Back with U12 | — | `cancel_result(completed=true)` | — | → Home | `toast.snap.one_side` after close (`back` only; none on `hold`) | completion failed: no toast; focus restored if possible |
| `move_next` (fallback) | comet | verified | `moment:"queued"` | `knob.meta.playnext.ok` | — (overlay open) | `err` + Play next copy |

Rules:
- **Moments start on the host's feedback, never on the press** (VOC-D03). The target flash is suppressed whenever `moment` is present (VOC-R08).
- A start's `ok` goes wherever the knob is when it lands (it may have left Home); the `started` wash plays at the current cursor (VOC §4.2 row 8).
- No controller-side start watchdog; the **job** is bounded instead (C5-37): `resolve` gives up after 20 s in total (§9.8.7), and the `play_items` staging gives up after `6 + 0.15·N` s and ends in the existing staging rollback (§9.2). Past the destructive step the job runs to its result, each call bounded by the Sonos 5 s timeout (`SO:74`). Home 1 stays dimmed until the result: the target is ≤ 3 s for a 34-song playlist (W5, §9.8.7), and the dim can outlast the two deadlines only by the destructive step, whose calls are each bounded by 5 s.

---

## 9. Services

All adapters keep today's discipline: one lock per adapter (`SO:90`), group guard `_assert_group(expected_revision)` (`SO:147-151`), track guard `_track_id` (`SO:153-156`), no replay of writes, sanitized error text (`SO:307-310`; `AM:109-123`).

### 9.1 `SonosAdapter.read_state()` additions (`SO:177-208`)

| Field | Type | Computation |
|---|---|---|
| `playlist_position` | int ≥ 0 | `int(track["playlist_position"])`, 0 when empty or invalid |
| `position_s`, `duration_s` | int \| None | parsed `H:MM:SS` of `track["position"]` / `track["duration"]` (`RT:109-140` parser); `""`, `NOT_IMPLEMENTED` or 0 duration → None (the raw strings stay for ALIVE progress) |
| `read_at` | float | `time.monotonic()` of the `GetPositionInfo` read |
| `source` | `queue` \| `airplay` \| `radio` \| `linein` \| `none` | playback `STOPPED` (or no track) → `none`; media URI `x-rincon-queue:` → `queue` if `queue_length > 0` and `1 ≤ P ≤ T`, else `none`; `x-sonos-vli:` containing `airplay` → `airplay`; `x-rincon-stream:` or `x-sonos-htastream:` → `linein`; any other URI → `radio`; `TRANSITIONING` keeps the previous class (C5-38; VOC §8.1; A06 §1.8) |
| `can_seek` | bool | `source == "queue"` ∧ `"SeekTime" in actions` ∧ `0 < duration_s ≤ 59 999` ∧ `position_s is not None` ∧ playback ∈ {PLAYING, PAUSED_PLAYBACK} (CS §4.3; the upper bound is K1 §4.3 `LAP_COUNT_MAX`, C5-51). Tracks 3 dims with `no_length` when the source is `queue` but the length or `SeekTime` test fails (VOC §2.6) |
| `shuffle` | bool | `play_mode ∈ {SHUFFLE, SHUFFLE_NOREPEAT, SHUFFLE_REPEAT_ONE}` |
| `repeat` | `off` \| `all` \| `one` | from `play_mode` (A06 §3.2 table) |
| `song_id` | str \| None | `_song_id`-style match on `track["uri"]` (RA §4.5 item 3) |
| `actions` | sorted list | the parsed set (`SO:182`) |

The 1 s poll cost is unchanged (≈ 8 round trips, CS §1).

### 9.2 Start: `play_items` (+ resolution strictness)

**Resolution** (library lane, `AM.resolve`, §9.8.7): albums and single songs **strict** (any unplayable track → `album_blocked`); playlists **lenient** (skip unplayable tracks; zero playable → `start_failed`) (00 U6; R §8 "Starting playback").

**Sonos** (`SO:355-455`): the recovery snapshot, the staging-rollback rules, the guarded replacement and the start sequence are kept. **The staging verification changes** (00 G3 "Verify staging with one slice read per song"; C5-49). Today every song costs a `_assert_group` (a zone-group read through `_context`, `SO:122-151`) plus **two full paged `_queue` reads** (`SO:386-399`, reads at `:388` and `:394`), so a 34-song start is ≥ 136 SOAP calls that grow with the existing queue length (≈ 4–11 s at 30–80 ms per call, before any Apple time).

```text
0  validate items (SO:356-366, unchanged); N = len(items); songs = [catalog_id…]
1  ctx = _assert_group(rev); c = coordinator
   original = _queue(c)                          # ONE full read before staging (recovery + signatures)
   capacity check; _save_recovery(...)            # unchanged (SO:377-380)
   T0 = original.total; deadline = monotonic() + 6 + 0.15·N
2  for i, (item, song) in enumerate(zip(items, songs)):            # one step each (§1.1)
       if monotonic() > deadline: raise StartTimeout                 # → staging rollback (below)
       got = plugin.add_share_link_to_queue(item["url"], position=0, dc_title=escape(title), timeout)
       if got != T0 + i + 1: raise QueueChanged                      # FirstTrackNumberEnqueued = the new last row
       tail = c.get_queue(start=T0 + i, max_items=1)                 # ONE 1-row slice read of the new tail row
       if int(tail.total_matches) != T0 + i + 1 or _song_id(tail[0]) != song: raise QueueChanged
       staged.append(song); expected_revision = str(tail.update_id)  # what the rollback guard compares (SO:436-446)
       between_steps()                                               # §1.1: short jobs may run here
       # an ambiguous timeout on the insert: read the same slice; continue only if it holds `song`
3  _assert_group(rev); verified = _queue(c)                         # ONE full read after staging
   verified.revision == expected_revision, verified[:T0] signatures == original signatures,
   [_song_id(x) for x in verified[T0:]] == songs, else QueueChanged
4  destructive step, unchanged and atomic (§1.1): _remove_range(c, 0, T0, verified.revision) → final read →
   (C5-20 unshuffle) → SetAVTransportURI → Seek(TRACK_NR 1) → Play → final check (SO:406-427)
```

- **Deadline** (C5-37): `StartTimeout` before step 4 takes the existing staging rollback path (`SO:436-455`: remove exactly our staged tail when the prefix and revision prove it is ours) and reports `start_failed` (`partial` notice only when the rollback cannot prove it). No deadline applies once step 4 has begun.
- **Group changes during staging** are caught by the step 3 and step 4 group checks (inserts made to a coordinator that left the group are then rolled back); the per-song `_assert_group` is dropped.
- **W5 fallback** (§9.8.7): if the measured latency misses the gate, WP6 may drop the per-song slice read and verify the whole staged tail with one read at step 3 (the rollback already covers a late mismatch). Either way the insert's return value is checked per song.

Plus:
1. **Unshuffled start** (C5-20): after the replacement and before `Play`, if `play_mode` is `SHUFFLE_NOREPEAT` / `SHUFFLE` / `SHUFFLE_REPEAT_ONE`, `SetPlayMode` to `NORMAL` / `REPEAT_ALL` / `REPEAT_ONE` (repeat kept; A06 §3.2), read back.
2. The companion-shuffle restore record is dropped (the queue is replaced).
3. The result carries `_final_song_ids`; the runtime records the base segment in the ledger (§9.7.3, §10.4).
4. Result: the state dict plus `_start = {"k": playable, "n": total, "u": unavailable, "name": name}`.

**`jump`** (Up next Play): §9.6.2.

### 9.3 Play next (`play_next`)

**Controller gates** (from cached state; §3.1 Recent 3): list/item ready, not busy, online, item available, `source == "queue"`, not `shuffle` (Sonos). Companion shuffle on is allowed (the play mode is NORMAL/REPEAT; A06 §1.6).

**Effect** `play_next{item, name, accent, expected_group_revision, expected_track_id}` → library lane `resolve` (with the cache, §9.8.7), then the audio lane insert. Progress payloads:

| Payload | When | Knob meta (Recent) |
|---|---|---|
| `{"phase":"resolving","n": n or None}` | at job start | ~~`knob.meta.playnext.progress` with `k = 0` when `n` is known (album `trackCount`, a cached playlist count); else `knob.meta.playnext.resolving`~~ **[r2.2]** always `knob.meta.playnext.resolving` = `Finding songs…`, whether or not `n` is known (R22 CH §4: "instead of `Queueing… 0 of n`"; C5-69) |
| `{"phase":"inserting","k": k,"n": n}` | after each verified insert | `knob.meta.playnext.progress` (**[r2.2]** for `k ≥ 1`; a `k = 0` payload, the cache-hit start below, keeps `Finding songs…`) |

**Strictness and cap** (C5-21): the U6 rule applies (albums strict: one unplayable song → `nothing_added`; playlists lenient: the playable songs). At most **100** songs: the first 100 in order (R §8; S01:214). Success copy is unchanged in both cases (OQ-3).

**Adapter** `SonosAdapter.play_next(items, expected_group_revision, expected_track_id, progress=None, between_steps=None) -> dict` — A06 §1.5 / CP §4.1 verbatim, with this contract's names; each insert is one step (§1.1):

```text
0  validate every item exactly as play_items (SO:356-366); N = len(items) ≤ 100; songs = [catalog_id…]
1  ctx = _assert_group(rev); c = ctx[1].coordinator
2  uri = c.get_current_media_info()["uri"]; if not uri.startswith("x-rincon-queue:")  -> NotQueueSource
3  if c.play_mode in {"SHUFFLE","SHUFFLE_NOREPEAT","SHUFFLE_REPEAT_ONE"}               -> SonosShuffleOn
4  track = c.get_current_track_info(); if _track_id(track) != expected_track_id       -> TrackChanged
5  head = c.get_queue(0, 1); T0 = int(head.total_matches); U0 = str(head.update_id)
   P = int(track["playlist_position"] or 0)
   if T0 == 0 or not 1 <= P <= T0                                                   -> NothingPlaying
   if T0 + N > MAX_QUEUE (5000, SO:72)                                              -> QueueFull (→ nothing_added)
6  anchor = _signature(c.get_queue(P-1, 1)[0])
   re-check _track_id(c.get_current_track_info()) == expected                        # shrink the race
7  plugin = self._share_link_factory(c)
   for i, item in enumerate(items):
       want = P + 1 + i
       desired = want if want <= T0 + i else 0          # current row is the last row → append (0 = end)
       got = plugin.add_share_link_to_queue(item["url"], position=desired,
                                            dc_title=escape(item["title"]), timeout=self.timeout)
       if got != want: -> verify failure (rollback)
       # ambiguous timeout: read c.get_queue(want-1, 1); continue only if _song_id(row) == songs[i]
       progress({"phase":"inserting","k": i+1,"n": N})
       between_steps()                                  # §1.1: volume / Seek / Play-Pause / state may run here
8  S = c.get_queue(P-1, N+2)  (paged at 100)
   check total == T0+N; _signature(S[0]) == anchor; [_song_id(x) for x in S[1:1+N]] == songs;
         str(S.update_id) != U0
9  now = int(c.get_current_track_info()["playlist_position"])
   ok if now == P or P+1 <= now <= P+N;  now > P+N → song_changed (the song ended before the 1st insert)
10 state = _state(_assert_group(rev)); state["_inserted"] = {"start_row": P+1, "song_ids": songs}
   return state                        # the runtime appends it to the ledger (§9.7.3, §10.4)
```

- `EnqueueAsNext` is never set (`as_next=False`, A06 §1.5).
- **Rollback** (any failed check after ≥ 1 insert): re-read; remove with `RemoveTrackRangeFromQueue(InstanceID=0, UpdateID=<just read>, StartingIndex=P+1, NumberOfTracks=k)` (`SO:348-353`) **only if** rows P+1..P+k are exactly this call's k songs, the anchor is intact and the current row is not inside the block; else report `partial` (A06 §1.5).
- **No automatic retry** after `song_changed` (C5-22).
- **Stacking**: each call inserts at P+1 of the then-current P, so the newest block sits directly after the current song (R §8; RP §4.3).

**Measured (rev 4; LC "Play next: 2 songs after the current one", 2026-09-25 21:26 UTC, W1).** Den (S2, its own coordinator), PLAYING row 2 of 10, NORMAL:
- `AddURIToQueue` with `DesiredFirstTrackNumberEnqueued` = P+1, then P+2, `EnqueueAsNext` = 0: **522 ms** and **560 ms**; Sonos returned **exactly** the requested rows (3, 4), so step 7's `got == want` check is valid; the old P+1 moved to P+3; the playing row, its track URI and PLAYING were unchanged, with no audible gap. The write phase (first guard to the rollback) took 1.3 s.
- The inserted rows carry **artist, album and cover art from Sonos** (`/getaa`), although the companion sends only the title; Up next can draw them as soon as the slice read lands, before any catalog enrichment (§9.6.1, §9.7.2).
- The guarded rollback `RemoveTrackRangeFromQueue(StartingIndex, NumberOfTracks, fresh UpdateID)` took **12 ms**.
- **Apple resolution** (today's `AppleMusicClient.resolve`, one track-list GET then one catalog lookup per track, sequential), 8-track album, uncached: **3.07 s**, **3.52 s** and **6.25 s** in three runs (track list 424–465 ms; lookups 249–893 ms, mostly 250–350 ms).
- **Totals for an 8-song album:** ≈ 4.2–4.5 s of inserts (+ the final slice read), plus 3–6 s of resolution when uncached: 7.5–10.5 s. Pre-resolution (below) removes the second part in the common case.
- Not yet measured (CP §5 extras a–e, still open): paused, REPEAT_ALL, companion shuffle on, a whole album, the song-boundary race, `EnqueueAsNext` alone.

**Pre-resolution and the resolve cache (rev 4, C5-66).** The job **checks the resolve cache first** (§9.8.7). A hit skips the library-lane step: the first progress is `{"phase":"inserting","k":0,"n":N}` at the press (knob `Queueing… 0 of {n}`; **[r2.2]** knob `Finding songs…` until the first insert lands, ≈ 0.5 s, C5-69), and the audio lane starts inserting at once. A pre-resolution of the same `(kind, library_id)` already **running** on the lookahead lane is **joined** (the job waits for that result, under the same 20 s deadline, instead of starting a second lookup); one only **queued** there is dropped, and the job resolves on the library lane itself. A miss resolves on the library lane as before (`Queueing…` meanwhile, **[r2.2]** `Finding songs…`; 20 s deadline). The `Queueing… {k} of {n}` line and its per-insert updates are unchanged.

**[r2.2] Timings (R22 CH §4, recorded).** The design accepts 1–10 s for a Play next. Its prototype models a cached lookup of **0.4 s**, an uncached one of **4.5 s** and **0.5 s per song** (R22 BS:1015); the live numbers above (uncached 3.07–6.25 s, inserts 522 / 560 ms) fit that model. The knob shows `Finding songs…` for the lookup and `Queueing… {k} of {n}` for the inserts, with the Working comet throughout (K2 M33).

**Outcomes** (§9.10): `ok`, `partial`, `nothing_added` (0 inserted, rolled back, share link refused, resolution failed, strict album with an unplayable song, queue full), `song_changed`, `not_queue_source` (→ the per-class copy), `sonos_shuffle_on`, `sonos_unavailable`, `group_changed`, `signin_expired`, `rate_limited`.

### 9.4 Seek (`seek`)

`SonosAdapter.seek(seconds, expected_group_revision, expected_track_id, between_steps=None) -> dict` — CS §4.4 with `T_end = D − 3`, **rev 4 confirmation rule** (C5-65; LC W2):

```text
ctx = _assert_group(rev); c = ctx[1].coordinator
track = c.get_current_track_info(); if _track_id(track) != expected              -> TrackChanged
D = secs(track["duration"]); if not D                                            -> SeekUnavailable
actions = parse(c.available_actions); if "SeekTime" not in actions              -> SeekUnavailable
before = c.get_current_transport_info()["current_transport_state"]
if before not in ("PLAYING","PAUSED_PLAYBACK")                                   -> SeekUnavailable
target = clamp(int(seconds), 0, max(0, D - 3))
_assert_group(rev); re-check _track_id                                           # SO:296-298 pattern
c.avTransport.Seek([("InstanceID",0),("Unit","REL_TIME"),
                    ("Target", f"{target//3600}:{target%3600//60:02d}:{target%60:02d}")],
                   timeout=self.timeout)
sent = monotonic(); deadline = sent + 8.0                     # [r2.2] seek_confirm_ms 8000 (rev 4: 5.0); the Seek is NEVER resent
seen_transitioning = False; last_group_check = sent
every 100 ms until deadline:                                  # each poll is one step (§1.1): lock per poll only
    between_steps()                                           # queued short jobs run here (not another seek)
    if monotonic() - last_group_check >= 0.5: _assert_group(rev); last_group_check = monotonic()
    t = c.get_current_track_info()
    if _track_id(t) != expected: return ok if target ≥ D-6 (within 3 s of T_end: the song ended, CS §4.3) else TrackChanged
    s = c.get_current_transport_info()["current_transport_state"]
    if s == "TRANSITIONING": seen_transitioning = True; continue        # RelTime already reads the target: not proof
    left = seen_transitioning or monotonic() - sent >= 1.0              # see "Never saw TRANSITIONING" below
    if left and s in ("PLAYING", "PAUSED_PLAYBACK"):                    # [r2.2] landed = playback resumed (C5-68);
                                                                        # rev 4 also required abs(pos - target) <= 2
        if abs(secs(t["position"]) - target) > 2: log_debug("seek landed off target")   # [r2.2] diagnostic only
        _assert_group(rev)
        state = _state(...); state["_applied_seek"] = target
        state["_seek_kept_state"] = (s == before); return state
raise SeekNotConfirmed                                                           # → not_confirmed
```

- **Why this rule.** Live (LC W2, Den, PLAYING, 2 seeks): the first poll ≈ 0.5 s after the Seek reply already read **`TRANSITIONING` with RelTime = the target**; the transport left `TRANSITIONING` at **2.64 s** and **2.69 s**, and the first settled read was the target exactly (0 s off). So the position alone confirms nothing (it is the target while the speaker is still buffering and silent), and the old 3 s window had ≈ 0.3 s to spare. Confirmation now needs the transport **out of** `TRANSITIONING` **and** the position within ±2 s; the window is 5 s (≈ 2.3 s margin over the measurement). **[r2.2] (C5-68; R22 CH §3)** The design settles it: **landed = playback has resumed**, not that a position report has arrived. The adapter returns on the first read out of `TRANSITIONING` (PLAYING, or PAUSED_PLAYBACK when the seek was sent paused or another controller paused meanwhile), whatever the position (logged if it is more than 2 s off); the window is **8 s** (the design's "about 2.7 s, up to about 5 s" plus margin); no resume by then → `SeekNotConfirmed` → `not_confirmed`.
- **Never saw `TRANSITIONING`.** A speaker that never reports it (or a paused seek, not yet measured: CS §5 step 4) confirms on a non-`TRANSITIONING` read within ±2 s taken **≥ 1.0 s** after the Seek reply (**[r2.2]** on a PLAYING / PAUSED_PLAYBACK read taken ≥ 1.0 s after the reply; the ±2 s condition is dropped). That delay keeps a stale pre-seek read (the first poll comes ≈ 450 ms after the reply, LC) from confirming a seek that has not begun; a seek within 2 s of the current position is then confirmed immediately, which is harmless.
- **Never resent**, whatever the outcome; a newer target waits and is sent next (§5.5.4).
- **Load.** 100 ms polls of two calls each (track, transport), the group read every 500 ms and once before the result; ≤ 5 s (**[r2.2]** ≤ 8 s). Between polls the lane runs queued short jobs (§1.1, C5-65), so volume and Play/Pause stay responsive while a seek lands.
- **The knob clock** stays frozen at the target with `Jumping…` until this returns (§5.5.3). **[r2.2]** A turn meanwhile moves the frozen target; when this returns, the controller sends at most one follow-up `seek` with the latest target (§5.5.4), itself never resent.

UPnP 701 / 710 / 711 → `not_confirmed`; 800 → `sonos_unavailable`; `GroupChanged` → `group_changed` (§9.10).

### 9.5 Shuffle hybrid

**9.5.1 Regimes** (U4): companion reorder when the upcoming count `U = T − P ≤ 60`; Sonos native shuffle above. Off always undoes whichever regime is active.

**9.5.2 `shuffle_reorder(on=True, plan, playnext_offsets, expected_rows, …)`** (A06 §3.4; C5-45, C5-50):

```text
controller, at the press (self.rng):
   pn   = offsets (0-based within rows P+1..T) of the upcoming rows whose ledger segment is playnext (§9.7.3),
          ascending = their current order, newest block first
   rest = every other offset, ascending; Fisher–Yates over rest
   plan = pn + rest                                  # the Play-next block stays directly after the current song
effect shuffle_reorder{on: true, plan, playnext_offsets: pn, expected_rows: [signature of rows P+1..T],
                       expected_update_id, expected_group_revision, expected_track_id}
adapter:
 1 gates: queue source; play_mode not SHUFFLE*; _track_id == expected; U = T - P ≤ 60; U_r = U - len(pn) ≥ 2;
   plan is a permutation of 0..U-1 whose first len(pn) entries equal pn        (else failed, nothing moved)
 2 read rows P+1..T (one Browse ≤ 60); they must equal expected_rows (else QueueChanged, nothing moved)
 3 persist the restore record (DPAPI store "shuffle-restore.bin", the SO:327-346 pattern):
     {room_uid, coordinator_uid, group_revision, created_at,
      base_rows: [signature, song_id] of the rows at offsets NOT in pn, in original order, update_id_after: None}
 4 progress({"phase":"accepted"})                                  # → ok + moment "shuffle" (§8)
 5 model = the signatures of rows 1..T from step 2 (kept in step with every move below)
   remaining = [row at offset plan[j] for j in 0..U-1]  (by signature); k = P + 1; P_cur = P
   while remaining:
       r = the first row index ≥ k in `model` holding remaining[0]
       if r == k: remaining.pop(0); k += 1; continue                # already in place: no SOAP call
       U_now = str(c.get_queue(0,1).update_id)
       pos = int(c.get_current_track_info()["playlist_position"])   # C5-50: the playing row, read last before the move
       if pos < P or pos > T: raise QueueChanged                     # jumped elsewhere: stop, record kept
       if pos >= k:                                                  # a song ended: rows k..pos are played / playing
           drop from `remaining` every row now at k..pos (they stay where they are); k = pos + 1; P_cur = pos
           continue                                                  # re-evaluate from the new k
       P_cur = pos
       c.avTransport.ReorderTracksInQueue([("InstanceID",0),("StartingIndex",r),("NumberOfTracks",1),
                                           ("InsertBefore",k),("UpdateID",int(U_now))], timeout)
       apply the move to `model`; remaining.pop(0); k += 1
       between_steps()                                               # one step = 3 calls (§1.1)
   (this left-to-right fill makes at most U_r − 1 moves, A06 §3.4 step 4; the Play-next block, already at P+1…,
    costs none. A06's LIS shortcut, ≈ U_r − 2√U_r moves, is not used: its moves land anywhere after P, and the
    re-plan rule below is only proven for the fill order)
 6 verify: one read of rows 1..T: rows ≤ P unchanged (signatures); rows P+1..T == the realised order
   (the plan minus the rows skipped in step 5, which sit at their positions) by signature;
   playlist_position ∈ {P_cur, P_cur + 1} (a song may end during the read) — else failed (record kept)
 7 record.update_id_after = update_id; persist; return _state(...)
```

**No row at or before the playing row ever moves** (C5-50). The position is re-read before every move, so a song that ends mid-reorder (a 60-row reorder takes ≈ 5–9 s at 30–50 ms per call, so a 4-minute song ends inside it ≈ 2–4 % of the time) freezes the rows up to the new playing row and the plan continues after it; the knob already confirmed at acceptance and nothing more is shown. The residual race is one SOAP call wide (the position is read last, right before the move) and exists only for a move into the position right after the playing row (`k = P_cur + 1`); every later move has `k ≥ P_cur + 2`, which one song end cannot reach. Step 6's position check catches it (`failed`, record kept, Shuffle off restores). Rows ≤ P never move (A06 §3.4). A failure after step 4 leaves a partly permuted queue with a valid record (Shuffle off still restores).

**9.5.3 `shuffle_reorder(on=False)`** (restore; A06 §3.4–3.5; S01:362):

```text
 1 load the record; P' = current row; the upcoming rows R = rows P'+1..T
 2 attribute each row in R: a base row (in the record), a Play-next row, or foreign; since C5-45 the Play-next
   rows present when shuffle turned on are not in the record either.
   [P2a] (C5-73) The effect's playnext_song_ids are the ledger's Play-next UNITS, QueueLedger.playnext_units()
   (§9.7.3): one [song_id, start_row] per song of every Play-next segment, newest block first; start_row = the
   1-based row the block's first song was inserted at (P+1 of that press); null or 0 (a ledger file older than
   start_row) = the unit matches any row. Plain song ids (the rev 1 to r2.2 interface) are still accepted.
   Two passes (sonos.py _attribute_restore):
   pass 1 (units only), in queue order, from the lowest start_row: a row numbered >= a free unit's start_row
     that holds the unit's song takes that unit (the latest start_row first). A played row (<= P') marks its
     unit "played"; an upcoming row that takes one is a Play-next row.
   pass 2 (every upcoming row pass 1 left, and every row of a plain-id payload): record first, per signature:
     of the k rows left with one signature, as many as the record still holds are base rows (the later ones
     in queue order); the earlier ones are Play-next rows (a Play next always inserts ahead of the base rows)
     and each takes a unit still free (a plain id first, then the lowest start_row, then one a played row
     gave back), else the row is foreign.
   Any foreign row → QueueChanged (drop the record)
 3 target = [Play-next rows in their current relative order (newest block first)] +
            [base rows sorted by their original index = their order at Shuffle on (the record, 9.5.2 step 3)]
   [P2a] not the ledger's start order, which the controller's preview uses (limitations below)
   [P3] the preview uses the ledger's start order only when the controller does not know the record,
        C5-79; with the record known it ranks the base rows by the record too (the [P3] paragraph below)
 4 progress({"phase":"accepted"})
 5 realise with guarded single-row moves exactly as 9.5.2 step 5, including the per-move position read and the
   re-plan after a song ends (C5-50): never moving the playing row or any row before it
 6 verify as 9.5.2 step 6; delete the record; return state
```

**[P2a] Why units (C5-73).** The controller previews the restore at the press (`upnext_rows{reason:"shuffle"}`, §5.6.5) from the ledger's own roles, `QueueLedger.classify` with its position rule (§9.7.3). With units the adapter attributes by the same rule, so ~~the realised order equals the preview~~ **[P2a]** the adapter and the preview put the same rows in the Play-next block, including two cases that plain ids cannot tell apart: a **Play next of a song the shuffle had already played** (its row has the same signature as that played base row, which the record still holds, so a record-first rule sorted it back to the base row's original index; with units it stays next), and the **base twin of a played Play-next row** (the played row gives its unit back, so the upcoming base row returns to its index). The controller sends `playnext_song_ids = ledger.playnext_units()`; plain ids stay accepted for older callers and keep the record-first rule of pass 2. A 160-seed randomized end-to-end test (controller press → runtime → adapter, `test_cc_sonos_v7.py`) holds units to the preview exactly (**[P2a]** on histories that start with the companion's own `play_items` and never reorder base rows before Shuffle on, so the record's order is the ledger's) and plain ids to never being wrong where the phase-1 record-first rule was right. The simulator accepts both forms. ~~**Remaining limitation:** the preview classifies only the rows it has loaded (the ±10 window plus rows P+1..T when U ≤ 60, §9.7.1), so a played Play-next row more than ≈ 10 rows above the playing row can still make the preview differ from the realised order; the re-read after the job (a revision change, §9.7.1) shows the true order. Rare, and accepted for this release.~~ **[P2a]** It is limitation 1 below, one of three.

**[P2a] Limitations** (the phase-2a K-docs review, KD-R1, found 2 and 3). The adapter restores the base rows in the **record's** order, the order they had when Shuffle went on (step 3; 9.5.2 step 3). The preview (`upnext_rows{reason:"shuffle"}`, the controller's `_restore_order`) ranks them by the **ledger's start order** (`base.song_ids`, which only `play_items` writes) **[P3]** only when the controller does not know the record (C5-79; with the record known it ranks them by the record's order and limitations 2 and 3 do not arise, the [P3] paragraph below) and puts the rows the ledger does not know after them, in their current order. The two agree only when the upcoming base rows still stood in the ledger's start order at Shuffle on. They differ in three cases:
1. a played Play-next row more than ≈ 10 rows above the playing row: the preview classifies only the rows it has loaded (the ±10 window plus rows P+1..T when U ≤ 60, §9.7.1). Rare;
2. base rows reordered before Shuffle on without a ledger entry: an Up next `move_next` of an upcoming row (Button 3 in the Play-next fallback, §9.6.3; only a played row's re-insert returns `_inserted` and reaches the ledger) or a reorder made in another Sonos app (same ids, so every row still classifies as base and the companion shuffle stays available);
3. a queue the companion did not start (started in the Sonos app, or replaced there after our last `play_items`): the ledger's base is empty or an older start's, so the preview keeps the shuffled order (or moves the few ids it knows first) while the adapter restores the order at Shuffle on. The companion shuffle is offered on such a queue (§5.6), so this case is **common**.

In each case the realised order is the record's (headless probes on the fakes, album 90…99 playing row 2: a `move_next` of row 8 → preview 90…99, realised 90 91 97 92 93 94 95 96 98 99; a queue started in the Sonos app → preview = the shuffled order, realised 90…99), and the re-read after the job (a revision change, §9.7.1) shows it, so the list re-enters a second time when the job completes. These are recorded as limitations of this build: the contract promises the realised order (the record's), not its equality with the preview. ~~The recommended fix (the preview ranks the base rows by the record's order, which the adapter persists and can report, so it also survives a companion restart) is handed to WP5 and WP6 (§18).~~ `tests\test_kdocs_contract.py` pins cases 2 and 3 and the equal case (**[P3]** for a controller that does not know the record, below).

**[P3] The preview follows the record when the controller knows it (C5-79; the recommended fix, WP5 side).** The controller keeps the record's base rows (their signature digests, in the record's order) as `shuffle_record_order`: from its **own** companion Shuffle on, at the job's acceptance (the adapter persisted the record before `progress(accepted)`, 9.5.2 step 3; the controller already sent those digests as `expected_rows` minus the Play-next offsets), and from the record the runtime **loads at start** (`load_shuffle_record()` on the audio lane, 9.5.5; the runtime hands only the digests to the controller through its results queue, so it also survives a companion restart). It is forgotten when a state reports `companion_shuffle: false` or a Shuffle off completes. While the state reports `companion_shuffle`, `_restore_order` ranks the upcoming non-Play-next rows by it, per signature in queue order as step 2 attributes them; rows it does not hold follow in their current order (the adapter treats them as Play-next or foreign). With the record known, limitations 2 and 3 do not arise (the preview is the realised order: `tests\test_cc5_upnext.py` runs the three histories above through the real adapter, in session and after a restart); limitation 1 stays. No wire change: the WP6 side (the adapter reporting the record with its reads) is not needed, since `load_shuffle_record()` already returns it.

**9.5.4 `set_shuffle(on, expected_group_revision)`** (native; A06 §3.2): `avTransport.SetPlayMode([("InstanceID",0),("NewPlayMode", mode)])` with `NORMAL ↔ SHUFFLE_NOREPEAT`, `REPEAT_ALL ↔ SHUFFLE`, `REPEAT_ONE ↔ SHUFFLE_REPEAT_ONE`; read back `GetTransportSettings.PlayMode` for ≤ 2 s at 50 ms (the `SO:219-242` pattern); 712 → `failed`.

**9.5.5 Record validity.** The companion shuffle is "on" iff a record exists for this room and the current upcoming rows are attributable to it (§9.5.3 step 2). A start (`play_items`) or an invalid attribution deletes it. Other Sonos controllers see a physically reordered queue with shuffle off; that is expected (S01:364). Under the **Sonos** regime (`U > 60`) Sonos picks the order of every upcoming row, including a Play-next block; the card copy (`{n} songs · order isn’t shown`) already says so (C5-45).

### 9.6 Queue reads and moves

**9.6.1 `queue_window(start, count)`** → `c.get_queue(start=start, max_items=count)` (0-based `start`, `count ≤ 100`; the Up next and Tracks windows ask for ≤ 21, and a full-queue read ~~follows §1.2's deferral while a desktop animation runs~~ **[P3b]** runs at once, also while a desktop animation runs: the §1.2 bench measured 0.26–0.49 ms for a 100-row page's envelope, WP6-GIL-D2) → `{"start", "rows": [row dicts], "update_id", "total"}`. Row dict: `{"row": start+i+1, "title", "artist": creator, "album", "sonos_art": sonos_artwork_url(album_art_uri, coordinator ip) (AW:99; renamed from `art_url` to K4 §13.2's key, C5-57), "song_id": _song_id(item), "duration_s", "signature": digest of _signature(item), "service": "apple" if song_id else "other"}` (A06 §4.1). Read-only; runs on `audio`.

**9.6.2 `jump(row, expected_group_revision, expected_track_id, expected_update_id, *, name=None, between_steps=None)`** (Up next Play; A06 §4.3): group and track guards; queue source (Sonos shuffle allowed); `get_queue(0,1).update_id == expected_update_id` and `1 ≤ row ≤ T`, else `QueueChanged`; `Seek(Unit=TRACK_NR, Target=row)` (as `SO:301`), then `Play` if not PLAYING (these calls are one step, §1.1); ~~confirm `playlist_position == row` and PLAYING within 2 s (the transport read-back pattern, `SO:275-286`)~~. **[P2a] Confirmed by the Seek landing rule** (§9.4, C5-68; C5-74): a jump buffers a new stream as a seek does (live W2: `TRANSITIONING` for 2.64 / 2.69 s), so the old 2 s window would fail a jump that is about to play. **Played** = the first `PLAYING` read with `playlist_position == row` taken after a `TRANSITIONING` read, or taken ≥ 1.0 s after the Seek reply when the speaker never reported `TRANSITIONING`, within `seek_confirm_ms` = **8000**; any other read (PAUSED_PLAYBACK, STOPPED, another row) keeps polling. The polls are §9.4's: every 100 ms, **each its own step**, with `between_steps()` run between them with the adapter lock released (§1.1; **[P2a]** no `seek` runs there: a start drops a waiting Seek follow-up, C5-77); the group is checked every 0.5 s and once before the result (`GroupChanged` → `group_changed`). Not played by 8 s → `SonosError` → `start_failed` (the start's failure path, §8); the Seek is never resent. Result = state + `_start = {"k": 1, "n": 1, "u": 0, "name", "row"}` for the row. A successful jump therefore holds Home's `Starting…` and the comet about as long as a seek takes to land (≈ 2.7 s at W2's numbers; a jump is a start, §5.6.7); the jump's own latency is not measured yet (§17.3 W2b).

**9.6.3 `move_next(row, expected_group_revision, expected_update_id)`** (Like fallback; A06 §5.5): queue source and not Sonos shuffle (else `not_queue_source` / `sonos_shuffle_on`); upcoming row (`row > P+1`) → `ReorderTracksInQueue(StartingIndex=row, NumberOfTracks=1, InsertBefore=P+1, UpdateID=<fresh>)`; played row (`row < P`) → re-insert its share link at P+1 (§9.3 step 7 with N = 1; needs the row's catalog `url` from §9.7.2); row P or P+1 → ok with no change. Verify by a slice read.

### 9.7 Up next data

**9.7.1 Read plan** (A06 §4.3; 00 §3.2 "windowed ±10"):

| Trigger | Read |
|---|---|
| open | `queue_window(max(0, f−10), 21)`; plus rows P+1..T when `U ≤ 60` and not covered |
| focus within 5 rows of the loaded window's edge | the next 21-row window around the focus |
| `queue_revision` or `playlist_position` changes (1 s poll) | drop rows, re-read the window around the focus (§5.6.8) |
| a Play next / shuffle / jump / move_next of ours completes | as a revision change |

Rows beyond the loaded windows are placeholders. At most one `queue_window` is in flight; a newer need replaces an unsent one.

**9.7.2 Catalog enrichment** (lookahead lane): for every new batch of rows with a `song_id`, `catalog_songs(ids ≤ 300)` (§9.8.4). A returned song fills `album`, `track_number`, `disc_number`, `duration_s`, the art keys `art_template`, `art_max` (min of `artwork.width`/`height`), `art_bg` (`bgColor`), `art_ink` (`textColor1`) (K4 §13.2; requests 240 for rows and 1200 for the big cover ±1, RA §4.1), `accent` seed (`bgColor`), `url` (for `move_next`), `release_year`. A song id the catalog does not return → `catalog = False` (C5-43; LC "0/1 found"). Rows without a song id → `catalog = False`, art from `sonos_art` only (Sonos `/getaa`, 400 px, LC:13; `art_bg` = 0, so K4 draws the `#232325` loading state, S5-11). **Heart state (rev 4, C5-64; C5-40 superseded):** for every new batch of rows with a song id, `ratings(ids ≤ 100)` (§9.8.3) on the lookahead lane, in parallel with the catalog batch; `liked = (value == 1)`, and an id absent from the answer is `False`. The catalog batch no longer requests `inFavorites`. Until the ratings answer, `liked = None` (`Checking likes…`); a failed ratings read leaves `None` and is retried once with the next window read.

**9.7.3 Provenance ledger** (`control_center/queue_context.py`; A06 §6; C5-23, C5-24).

```python
class QueueLedger:
    """Per pinned room; persisted to %LOCALAPPDATA%\DeskDial\data\queue-ledger.json
    (ids, names and artwork templates only; no tokens)."""
    base: Segment | None            # from the last successful play_items
    playnext: list[Segment]         # from successful play_next calls, newest first
    def record_start(self, segment, final_song_ids): ...   # replaces everything
    def append_playnext(self, start_row, song_ids, context): ...
    def classify(self, rows) -> Context: ...
    def playnext_units(self) -> list: ...   # [P2a] [[song_id, start_row], ...], newest block first (§9.5.3, C5-73)
```

`Segment{kind ∈ {album, playlist, song, playnext}, name, artist, year, library_id, art_template, accent, song_ids, favourite: bool, auto: bool, created_at}`; **[P2a]** a `playnext` segment also stores `start_row` (the row its first song was inserted at, from `_inserted.start_row`, §9.3 step 10; `None` in an older file).

**Classification** of the current queue (rows' `song_id`s, None for non-catalog):
1. Build a multiset of ledger ids: `base.song_ids` ⊎ every `playnext.song_ids`.
2. Attribute each row by id (each id consumed once per occurrence); a Play-next id is taken before a base id. **[P2a] Position rule** (C5-45, C5-73): in queue order, a Play-next id is taken first only for a row **at or below** its block's `start_row` (the latest start row first); a row above it holding the same id is a base row (a played song re-queued), because our rows only move down after an insert. A row the rule leaves without a base id still takes any Play-next unit left before it counts as foreign, so foreign detection stays the plain id multiset (C5-24); a segment without `start_row` matches any row. The shuffle-off restore (§9.5.3) attributes by this same rule.
3. **Any unattributable row** (None, or an id not in the multiset) → **foreign**.
4. Result:

| Result | Left column (K4) | Rows |
|---|---|---|
| base `album` (with or without Play-next rows) | title = album name; sub = `{artist} · {year}` (BS qCtx; year omitted when unknown); the big cover stays still (S01:326) | base rows show `track_number`; Play-next rows show their own cover and `artist · album` (S01 §6) |
| base `playlist` | title = playlist name; sub = `Favourite playlist · {n} songs · {duration}` when favourited (BS:1230 qCtx `'Favourite playlist · ' + ctx.n`, where `ctx.n` is BS's `PL[].n` string `{n} songs · {h} h {mm} min`, BS:511-516), else `overlay.upnext.sub_playlist` (§15.3) | every row its own cover, `artist · album`; the big cover crossfades 120 ms after the last detent |
| base `song` | as playlist, title = the song's album | as playlist |
| **foreign** | `overlay.upnext.foreign_title` / `overlay.upnext.foreign_sub` (`{n}` = T) (S01:337) | every row its own cover |

Matching by multiset survives the companion shuffle (rows permuted, same ids). A foreign queue never gets an album heuristic (C5-23). Non-catalog rows append `overlay.upnext.row_not_catalog` to their sub and have no heart (S01:338-341).

The presenter receives the result as `context{kind, title, sub}` (§11.1) with the strings already filled; `kind` ∈ `album` | `playlist` | `foreign` (K4 §2.3), and a base `song` is sent as `playlist`. K4 draws `title` and `sub` as given (its §8.2 shorthand `Favourite playlist · {n}` is this row's string).

### 9.8 Apple Music client (`AppleMusicClient`)

**9.8.1 `_send(method, path, *, json=None, params=None, expected=(200,), background=False)`** (CL §4.5; A06 §5.2): reuses `_safe_path` (`AM:79-88`), the credential reload (`AM:95-99`), `developer_token`, the two headers + `Accept: application/json`, plus `Content-Type: application/json` when `json` is given; `allow_redirects=False`; timeout 8 s; returns the parsed body for a 200 with a body, `None` for 202/204. Errors raise `AppleMusicError` with a new **`status` attribute** (int or None) set by both `_get` and `_send` (CF §5 "Code deltas"). The module docstring stops saying "Read-only" (`AM:1`).

**9.8.2 `like(catalog_id)` / `unlike(catalog_id)`** (R §8; CL §4.1; **rev 4 on live evidence**, LS and LC 2026-09-25, C5-62, C5-63; **[r2.2]** `unlike` withdrawn, add-only is final, C5-67):

*What the live checks showed* (song 1000000001, the companion's own Apple Music sign-in, no Sonos):

| Call | Apple's answer | Server state after it | The user's iPhone |
|---|---|---|---|
| `PUT /v1/me/ratings/songs/{id}` value 1 (21:27 UTC) | 200, value 1 | rating 1, `inFavorites` true, first in Favorite Songs | **no star**, even after ≈ 30 min and an app restart |
| `POST /v1/me/favorites?ids[songs]={id}`, no body (22:06 UTC) | **202**, empty body, 388 ms | the same values (rating 1 after ≈ 1 s, `inFavorites` after ≈ 3 s, Favorite Songs ≈ 2 s) | **starred** |
| `DELETE /v1/me/ratings/songs/{id}` (22:42 UTC) | 204, 98 ms | no rating, `inFavorites` false, out of Favorite Songs (all within ≈ 2.6 s) | **still starred** 19 min later (23:01 UTC) |
| `DELETE /v1/me/favorites?ids[songs]={id}` (the web player's call) | **not sent** (23:01 UTC: blocked by the session's permission system); public code reports 204 (WaveForge) and 400 "Insufficient Permissions" (Slipmat, vinilo) | — | — |
| **[r2.2]** the same `DELETE /v1/me/favorites?ids[songs]={id}`, sent once by `work/probes/unfavorite_webplayer_once.py` with the user's approval (2026-09-25 16:03 PDT) | **HTTP 400, code 40012 "Insufficient Permissions"**, 333 ms | nothing changed | nothing changed |

The stored data is identical after the `PUT` and the `POST`; only the favourites call also tells the user's devices. So:

- **like** = `POST /v1/me/favorites?ids[songs]={catalog_id}` (no body; `expected=(200, 202, 204)`), then **read back** `GET /v1/me/ratings/songs?ids={catalog_id}` every `like_readback_ms` (250, first at +250 ms) until the value is **1** → `{"liked": true}`; not seen within `like_confirm_ms` (4000) → `failed` (the late check of §5.6.6 follows). A 202 means "accepted", not "done" (LS), which is why the read-back is the confirmation.
- **[r2.2] unlike: withdrawn.** `UNLIKE_STRATEGY = "add_only"` is **final** (R22 CH §1; the favourites `DELETE` above was refused for our token, and the ratings `DELETE` does not reach the devices). `AppleMusicClient` sends no unlike request of any kind; the controller refuses a press on a liked row (`unlike_unavailable`, §3.2, §5.6.6). The constant may stay in `apple_music.py` as `"add_only"` for the tests, but the `favorites_delete` branch, the settings.json override and `unlike_unsupported` are not built (C5-67). Rev 4 text, superseded:
- **unlike**, by the effective **`UNLIKE_STRATEGY`** (a module constant in `apple_music.py`, default **`"add_only"`**; settings.json `unlike_strategy` without UI overrides it; C5-63):
  - **`"add_only"`** (the default until W4b passes, §17.3): **no unlike request exists.** The controller refuses the press on a liked row (`unlike_unavailable`, §3.2, §5.6.6); the adapter's `unlike` raises `UnlikeUnavailable` if called anyway (a programming error; tests assert it is never called).
  - ~~**`"favorites_delete"`**~~ (**[r2.2]** withdrawn: Apple answers 400 / 40012): `DELETE /v1/me/favorites?ids[songs]={catalog_id}` (no body; `expected=(200, 202, 204)`), then read back as above until the song has **no rating** (the `?ids=` read returns no row for it) → `{"liked": false}`; still rated after `like_confirm_ms` → `failed`. **400 or 405** → `unlike_unsupported` (the runtime switches the session to `add_only`, §5.6.6); a 404 counts as ok **only** when the read-back shows no rating (C5-44 revised).
- **Never** `PUT /v1/me/ratings/…` (it does not reach the user's devices), **never** `DELETE /v1/me/ratings/…` for Unlike (it clears the server but leaves the star on the user's devices, so the companion's heart and the phone would disagree), and **never value −1** ("Suggest Less", A06 §5.2). A test asserts that no code path issues a ratings write (§17.2).
- **Errors** (both calls; **[r2.2]** the like call only): 404 on the `POST` → `not_catalog`; 401/403 → `signin_expired`; 429 → `rate_limited`; 400/405 on the `POST` → `failed` (logged by status only: our sign-in could not use the favourites call, which the live check did not see); other → `failed`. Read-back GETs use the same mapping, except that a 404 on the read-back means "no rating".
- **Timing:** like ≈ 0.4 s `POST` + ≈ 1 s until rating 1 is readable ≈ **0.6–1.6 s** to the pink bloom (the Working comet runs meanwhile, §5.6.4). Both calls (**[r2.2]** the like call) run on the `library` lane with their read-backs (≤ 4.4 s per request; the Up next overlay is open, so no Recently Added page or start resolve waits behind it).
- **Consent copy** (§14.2) already says "mark songs as Favorites when you press Like"; unchanged.

**9.8.3 `ratings(ids ≤ 100)`**: `GET /v1/me/ratings/songs?ids=a,b,…` → `{id: value}`; unrated ids are absent; a 404 for the batch → `{}` (CL §4.3). `liked = (value == 1)`. **Rev 4: the one source of the heart state** (C5-64): the Up next rows (§9.7.2), the like read-back (§9.8.2; **[r2.2]** there is no unlike read-back) and the late check (§5.6.6) all read it. *Why ratings and not `extend=inFavorites`:* the rating is the one server field behind both the star and Favorite Songs (the Music app's Unfavorite deletes it; the favourites `POST` sets it to 1; LC 21:22 UTC, LS), it is readable ≈ 1 s after a `POST` against ≈ 3 s for `inFavorites` (LS 22:06 UTC), and one source for rows **and** read-backs means a `data` patch from a catalog re-read inside that 2 s gap can never flip a heart the read-back has just confirmed. The cost is one extra GET per 21-row window on the lookahead lane.

**9.8.4 `catalog_songs(ids ≤ 300)`** (~~≤ 50 per request if the §1.2 parse bench shows a GIL hold over 1 ms~~ **[P3b]** at most **50 ids per request**, `CATALOG_BATCH`, since the §1.2 bench measured 300 ids at 1.85–3.29 ms; an Up next read of 51–60 upcoming songs takes two requests): `GET /v1/catalog/{sf}/songs?ids=…` (storefront from `_get_storefront`, `AM:296-303`; **rev 4: no `extend=inFavorites`**, C5-64) → per id `{album: albumName, track_number, disc_number, duration_ms: durationInMillis, art: {template, width, height, bgColor, textColor1}, url, release_year}` (A06 §4.3, §5.4; RA §4.5).

**9.8.5 `favourite_playlists()`** (CF §5 verbatim; U7):
1. **Fast path**: `GET /v1/me/library/playlists?limit=100&extend=inFavorites&filter[inFavorites]=true`; accept only if every page is 200, the result is non-empty and every row has `inFavorites === true`. Page by re-sending **our own params** plus the `offset` from `next` (Apple's `next` drops `extend` and `limit`, CF §2 row 8). Reject otherwise.
2. **Full scan**: `GET /v1/me/library/playlists?limit=100&extend=inFavorites` (+ offset pages, own params); dedupe by id; compare with `meta.total` and re-scan once on a mismatch; every row must carry a boolean `inFavorites` (a missing key is a schema failure → step 3); "no favourites" is concluded only here.
3. **Ratings fallback**: `GET /v1/me/ratings/library-playlists?ids=<≤ 100>`; value 1 = favourite; a 404 batch = none.
4. **Folders** (only if a root listing contains `library-playlist-folders`): walk `/v1/me/library/playlist-folders/{id}/children?limit=100&extend=inFavorites`.
- Sort client-side by `name.casefold()`, then id; unnamed rows last as `overlay.explorer.untitled` (C5-30).
- Item shape: the Recently Added item shape with `kind:"playlist"`, `resource_type:"library-playlists"`, plus `can_edit`, `has_catalog`, `auto` (= name `Favorite Songs` ∧ `canEdit` false ∧ `hasCatalog` false; drives `overlay.explorer.sub_favourite_auto`), `last_modified`. **Favorite Songs is kept** (user decision; CF "In plain language").
- Errors: 401/403 → `signin_expired` (keep the cache, mark stale); 429 → keep the cache, no full scan, retry after 30 s then 120 s; anything else on the fast path → step 2.

**9.8.6 Recently Added pager** (`recent` / `recent_lookahead`; U5; 00 G3):
- `GET /v1/me/library/recently-added?limit=25&offset={25·k}`; own params re-applied on every page (never Apple's `next` verbatim, `AM:293`); the page validation of `_recent_result` (`AM:238-280`) stays.
- `total` from `meta.total` when present (OQ-1); `complete` when a page has no `next`.
- Item shape (`AM:270-277`) gains the K4 §13.2 art keys `art_template`, `art_max` (min of width/height), `art_bg` (`bgColor`), **`art_ink`** (`textColor1`, for the `art.loading` title and artist, K4 §13.6), plus `year` (from `releaseDate`), `track_count` (library albums), keeping `artwork_url`, `accent_url`, `_resource` (RA §4.5 item 1; VOC-K4-03 adopted, C5-57). Items without artwork carry `art_template = ""`, `art_max = 0`, `art_bg = 0`, `art_ink = 0` and get `art.generated` (K4 §13.6).
- The visit bookkeeping (`_recent_visit`, `AM:59`) stays: a page of an older visit never commits.

**9.8.7 `resolve(item, *, lenient)`** (00 G3; U6):
- `/v1/me/library/{albums|playlists}/{id}/tracks?include=catalog&limit=100` for **both** kinds, with the own-params pager: every page re-sends `include=catalog&limit=100` plus the `offset` taken from `next` (Apple's `next` drops them, CF §2 row 8; `AM:293`). `limit=100` is the only value verified live here (library playlist listings, CF §2 rows 1–3, and a library playlist's `/tracks`, row 17; album `/tracks` is unverified with any `limit`); today's code sends no `limit` (`AM:368`), and `limit=300` is not used (C5-52). ~~If the §1.2 parse bench shows a page holding the GIL over 1 ms, the page size drops to 25 (K4 §4.7.3) and the 20 s deadline and W5 are re-checked.~~ **[P3b]** The bench measured a 100-row page at 0.92–1.55 ms (p95 up to 1.74), so every page is **`limit=50`** (`TRACKS_PAGE_LIMIT`, 0.43–0.71 ms) where this line says `limit=100`: a 100-track item that was not pre-resolved takes 2 requests (≈ 0.45 s more), ≈ 2,200 tracks fit the 20 s deadline, and the page bound scales with the page size, so an item over 5,000 tracks still fails as too long. 50, not 25: accepted deviation WP6-GIL-D1 (§19); 25 is the one-constant fallback if W5's recorded bodies parse above ≈ 0.6 ms at p50, and R5/W5 check `limit=50` live. The code already consumes `relationships.catalog` (`AM:309-311`); counts from `meta.total` (library playlists have no `trackCount`, CF §2). R5 adds the exact album and playlist queries of this line (read-only, §17.3) before WP6 freezes it.
- **Deadline** (C5-37): 20 s for the whole resolve (all pages and any per-track `/catalog` fallback, `AM:305-328`); past it → `start_failed` for a start, `nothing_added` for a Play next; nothing is staged.
- Per track `_catalog_song` (`AM:305-328`); a per-track `MusicUnavailable` is fatal when strict (albums, songs) and **skipped and counted** when lenient (playlists). Lenient with zero playable → fatal.
- Returns `{"tracks": [...], "total": n, "unavailable": u}`; each track gains `album`, `track_number`, `duration_ms`, `art_template` (A06 §7).
- **Cache**: LRU of 64 entries keyed `(kind, library_id)`, TTL 1800 s, evicted on any start or Play next failure citing it (R §8 "cache it; about 6 s uncached"). **Measured uncached (rev 4, LC W1):** 3.07 s, 3.52 s and 6.25 s for the same 8-track album with today's resolve (one track-list GET, 424–465 ms, then one catalog lookup per track, 249–893 ms each, in sequence). Every `play_items`, `play_next` and pre-resolution reads the cache first and writes it on success; lenient results are cached with their `unavailable` count.
- **Pre-resolution (rev 4, required; replaces the optional warm-up; C5-66).** Trigger: `prefetch_resolve_rest_ms` (400) after the last detent on a **loaded** Recently Added item (the knob list, or the explorer's recent tab). Order: the focused item, then the neighbour in the direction of the last detent, then the other neighbour (focus ± 1, clamped to the loaded list). Each is skipped when it is cached, unavailable (`item_unavailable`), or larger than 100 tracks (albums by `track_count`; a playlist without a known count is resolved only when focused). Lane: `lookahead`, **one pre-resolution at a time**, always after every other queued lookahead op (a `recent_lookahead` page the user may be waiting on runs first). A new focus drops the queued pre-resolutions that are no longer the focus or its neighbours; the running one finishes into the cache. **[P2a]** The drop runs at every detent through the internal effect `resolve_drop{keep}` (§5.2.2, §10.1, C5-75): the lookahead lane keeps only the queued keys in `keep` (`LookaheadLane.keep_preresolve`). The 20 s resolve deadline applies. Cost: ≈ 9–10 Apple GETs per 8-track album, only after a rest, so a fast spin costs nothing. Consumers: Play next (§9.3: cache hit → inserts at once; a running pre-resolution of the same item is joined) and every start (`play_items`, which also shortens the W5 latency, §17.3).
- **Batching (recommended, WP6).** Where the track list carries `playParams.catalogId` or the `catalog` relationship (R5 checks `include=catalog`), no per-track lookup is needed; the remaining per-track fallbacks should go out as **one** `catalog_songs(ids)` batch instead of one GET per track (≈ 0.25–0.9 s each today). Not required for this release; if applied, the W1 timing above is re-measured.
- Latency gate (00 G3, extended; C5-49): **from the Play press to confirmed PLAYING, ≤ 3 s for a 34-track playlist**, covering the uncached resolve, the Sonos staging, the replacement and the start (not the resolve alone), measured in live check W5. If W5 misses it, WP6 applies the §9.2 fallback (one tail read for the whole staged block) and W5 is re-run; the gate result and per-call times are recorded.

**9.8.8 `playlist_meta(playlist_id)`** (C5-28; CF §5 "Track count and duration"): `GET /v1/me/library/playlists/{id}/tracks?limit=100&include=catalog` (first page) → `count = meta.total`, `mosaic` = the art descriptors (`art_template`, `art_max`, `art_bg`, `art_ink`) of the first 4 distinct albums **with art**, in track order (albums without art are skipped; fewer than 4 with art → the first one with art only, full bleed; none → `art.generated` from the playlist title; S01:301-304; K4 §13.2, §13.6, S5-12; C5-57), `first_art` = the first album with art, `accent` seed from it (VOC §3.5 `playlist`); `duration_ms` only for the focused playlist (all pages), cached by `(id, last_modified)`. **[P3b]** Pages are `limit=50` (§9.8.7): the mosaic and the count keep the **first 100 tracks** as their window, reading a second page only when the first 50 hold fewer than 4 albums with art or Apple sends no `meta.total` (accepted deviation WP6-GIL-D3); the duration reads at most `META_MAX_TRACKS` = **10,000** tracks (200 pages of 50; over it, no page is read for it; accepted deviation WP6-GIL-D5). After the first page: a neighbour whose window page fails keeps what it has (the mosaic so far, the count from `meta.total` or none) and does not raise, while the focused playlist still raises; a failed duration page keeps the count and mosaic with `duration_ms` None and caches nothing; a list that cannot be read to its end within the bound gives `duration_ms` None, cached by `(id, last_modified)`; a 401/403 raises everywhere (D3, D5). A 404 `40403` → an empty playlist (Play dims `item_unavailable`).

### 9.9 Windows operations (K4 owns the recipes)

| Op | Adapter call | Result to the controller |
|---|---|---|
| `windows_open` | `snapshot()` + `show()` (`RT:1431-1433`), synchronous inside WM_HOTKEY (the CAR §1 focus contract K4 §9.1 keeps) | snapshot dict |
| `windows_highlight` | `highlight(index)` (+ `control_id`, `bump`) | — |
| `windows_activate` | `activate(item)` (verified, synchronous as v6, CAR §1) | bool |
| `windows_cancel` | `cancel(origin, complete=side or None` **[P3]** `, reason=` the close (C5-78)`)` — restore focus (never for `lock` / `sleep`, K4 §15); with `complete`, first move the origin to that half non-activating on `NanoD-snap` (VOC-D01; VOC §8.4 `complete_one_side`; K4 §9.7). **[P3]** The runtime passes only the keywords the adapter takes (a v6 adapter gets `cancel(origin)`); a picker handed no `reason` keeps inferring it (WP7b-D6) | event **`cancel_result(restored: bool, completed: bool)`** (C5-53) |
| `windows_snap` | posts `{t0, index, side, target_rect, place_at_ms: 360}`; K4 runs the pre-checks on `NanoD-snap` at receipt, the placement at `t0 + 360`, then verifies (K4 §9.5-§9.6) | events (C5-53): first **`snap_result(side, "accepted")`** when the pre-checks pass (≤ 5 ms) or `snap_result(side, "hung" \| "move_rejected")` when they fail; after an acceptance, `snap_result(side, "ok")` when the placement verifies or `snap_result(side, "move_rejected" \| "cant_fit")` when it fails (≈ 360–560 ms; UWP ≤ 760 ms; always by the hard deadline `t0 + 800`, which counts as `move_rejected`, K4 §9.6) |
| `windows_close_pair` | `close_pair(left, right, focus)` — raise both, focus `focus` | bool |
| `windows_hide` | `hide()` | — |

Outcome names are VOC §8.5's; `accepted` is the one addition (C5-53). The controller never blocks on the picker for `windows_snap` or `windows_cancel` (K4 §2.3).

### 9.10 Outcome codes → knob, toast, LED

VOC §8.5 is the base. Mapping from exceptions:

| Exception / status | Ops | Outcome |
|---|---|---|
| `GroupChanged` (`SO:28`) | any Sonos op | **`group_changed`** (C5-28): `err`; transient (**[P2a]** from the op's own result only for a start and a volume write; for the other ops from the next state poll, below) `knob.status.group_changed` on Home (`status` line) or its `meta` twin `knob.meta.group_changed` elsewhere (same text `Group changed`, C5-56; **[r2.2]** `Speaker group changed`, R22 CH §2, C5-70); overlays close `group`. **[P2a]** The copy shows for **`group_changed_ms` = 2600** in ~~`meta`~~ **[P2b]** `error` tone (§7, C5-76; R-j), also when a state poll or result (not a failed op) shows a new `group_revision`: then the copy only, with no `err` (nothing the user pressed failed), and the §13.1 `group` closes and the Seek drop (C5-47) apply. A volume write to the old group finishes quietly (no `err`, no copy; `obsolete_group`, §10.2). A Play next that fails with `group_changed` keeps the Play next failure rule instead (§9.3: `knob.meta.group_changed`, `error` tone, `fail_meta_ms` 2400, `toast.playnext.nothing`). **[P2a] Per op** (review KD-R3). A **start** (`play_items`, `jump`): `err` + the copy for `group_changed_ms` from its result, **no** `start_failed` copy and **no** toast (§8). A **seek**, a **shuffle** (`shuffle_reorder`, `set_shuffle`) and a **transport** press keep their own failure first: Seek `err` + `Didn’t jump · try again` (`seek_fail_line_ms`, stays in Seek); shuffle `err` + `knob.meta.shuffle.failed` `Didn’t shuffle · try again` (`error` tone, `fail_meta_ms` 2400); transport `err` + the desktop notice, no knob copy. The copy then comes from the next state poll that reads the new `group_revision` (every 1000 ms; 2000 ms while an exclusive job runs, §7): copy only, no second `err`, with its consequences (Seek exits to Tracks, C5-47; Up next closes `group`, §13.1). `move_next` keeps the Play next rule (`error` tone, 2400 ms; no toast, Up next is open) |
| `TrackChanged` | play_next, seek, jump, shuffle | `song_changed` (Play next); Seek exits silently; others `failed` |
| `QueueChanged` | play_items, play_next, shuffle, jump, move_next | `queue_changed` (shuffle), `nothing_added` / `partial` (Play next per rollback), `start_failed` (starts) |
| `NotQueueSource`, `NothingPlaying`, `SonosShuffleOn` | play_next, move_next | `not_queue_source` (per class), `sonos_shuffle_on` |
| `SeekUnavailable`, `SeekNotConfirmed`, UPnP 701/710/711 | seek | `not_confirmed` |
| UPnP 800 / 402 / 804 on the first `AddURIToQueue` | play_next | `nothing_added` |
| UPnP 712 | set_shuffle | `failed` → `knob.meta.shuffle.failed` |
| `StartTimeout` (staging deadline, §9.2) / resolve deadline (§9.8.7) | play_items, play_next (resolve) | `start_failed` (after the staging rollback) / `nothing_added` |
| `QueueReplacementFailed(partial=False)` | play_items | `start_failed` |
| `QueueReplacementFailed(partial=True)` | play_items | `start_failed` + desktop notice "inspect Sonos" (`SO:454`) |
| `MusicUnavailable` strict / all unplayable | resolve for a start | `album_blocked` (album) / `start_failed` |
| any Sonos transport error / unreachable | any | `sonos_unavailable` |
| Apple 401/403 | any Apple op | `signin_expired`; `runtime.music_signin_expired = True` for **every** Apple result (generalises `RT:1140-1149`); cleared by any successful Apple result |
| Apple 429 | any | `rate_limited` |
| Apple 404 | `ratings` → none (also a like read-back: "no rating"); ~~`unlike` (`favorites_delete`) → ok only when the read-back shows no rating, else `failed` (C5-44 revised)~~ (**[r2.2]** withdrawn); `like` (`POST /v1/me/favorites`) → `not_catalog`; playlist tracks → empty playlist | as listed |
| Apple 400 / 405 (rev 4) | `unlike` (`favorites_delete`: `DELETE /v1/me/favorites`) | **`unlike_unsupported`**: the session's `unlike_strategy` becomes `add_only`; `err`, `knob.meta.like.unlike_in_music` (§5.6.6; C5-63). **[r2.2] Withdrawn** (no unlike request exists; C5-67) |
| Apple 400 / 405 (rev 4) | `like` (`POST /v1/me/favorites`) | `failed` (`knob.meta.like.failed`), logged by status code only |
| like read-back not matched within `like_confirm_ms` (rev 4; **[r2.2]** like only) | `like` | `failed` (`knob.meta.like.failed`, **[r2.2]** `Didn’t save · try again` 2200 ms + Head shake); one late `ratings` check after 5 s (§5.6.6) |
| `UnlikeUnavailable` (rev 4) | `unlike` called under `add_only` | never expected (the controller refuses first); `failed` + an error log. **[r2.2]** With no `unlike` method at all this row is moot; a test asserts no DELETE ever goes to `/v1/me/favorites` or `/v1/me/ratings` |
| other | any | `failed` |

---

## 10. Effects, lanes and runtime deltas

### 10.1 Effect kinds (VOC §7.4; C5-28)

Every effect carries `kind`, `request`, `control_id`, `view_id` (`CT:173-179`) and, for presenter-timed ones, `t0`.

| Kind | Payload | Lane | Result → controller |
|---|---|---|---|
| `state` | — | audio | state (§9.1) |
| `volume` | `value`, `expected_group_revision` | audio | state + `_applied_volume` |
| `transport` | `direction`, `expected_group_revision`, `expected_track_id`, `index?` | audio | state |
| `play_items` (renamed from `play`) | `item`, `name`, `accent`, `source`, `lenient`, `expected_group_revision` | library (resolve) → audio | state + `_start` + `_final_song_ids` |
| `play_next` | `item`, `name`, `accent`, `expected_group_revision`, `expected_track_id` | library → audio | state + `_inserted`; progress |
| `seek` | `target_s`, `expected_group_revision`, `expected_track_id` (the runtime reads the latest target at job start) | audio | state + `_applied_seek` |
| `shuffle_reorder` | `on`, `plan?` + `playnext_offsets?` + `expected_rows?` (on, §9.5.2), `playnext_song_ids?` (off, §9.5.3; **[P2a]** the ledger's `[song_id, start_row]` units, plain ids still accepted, C5-73), `expected_update_id`, `expected_group_revision`, `expected_track_id` | audio | state; progress `accepted` |
| `set_shuffle` | `on`, `expected_group_revision` | audio | state |
| `queue_window` | `start`, `count`, `purpose ∈ {upnext, tracks, shuffle}` | audio | rows |
| `jump` | `row`, `name`, `accent`, `expected_group_revision`, `expected_track_id`, `expected_update_id` | audio | state + `_start` |
| `move_next` | `row`, `expected_group_revision`, `expected_update_id` | audio | state |
| `like` / `unlike` | `song_id`, `row` (rev 4: `unlike` is emitted only under `unlike_strategy == "favorites_delete"`; **[r2.2]** `unlike` is never emitted, C5-67) | library (the request and its read-back, §9.8.2) | `{"liked": bool}`; errors per §9.10 (**[r2.2]** `unlike_unsupported` withdrawn) |
| `ratings` | `ids` | lookahead | `{id: value}` |
| `catalog_songs` | `ids` | lookahead | per-id dicts |
| `favourite_playlists` | `force` | library (no cache) / lookahead (refresh) | list |
| `playlist_meta` | `playlist_id`, `duration: bool` | lookahead | meta |
| `recent` / `recent_lookahead` | `visit`, `offset`, `limit: 25` | library / lookahead | page |
| `resolve` (pre-resolution, rev 4, C5-66) | `item`, `direction` (the order of §9.8.7) | lookahead, lowest priority, one at a time; queued ones dropped on a focus change | cached silently |
| `resolve_drop` **[P2a]** (internal, C5-75) | `keep: [{kind, id}]` (the new focus and its two neighbours among the loaded Recently Added items; may be empty) | none: the runtime applies it on the Tk thread as it drains the effects, in order after any `resolve` effects drained before it, by pruning the lookahead lane's queued pre-resolutions to `keep` (`LookaheadLane.keep_preresolve`); the running one is never dropped | — (no result, no `complete`). Emitted through the controller's presenter-effect path (`kind`, `request`, `control_id`, `view_id`) but **never posted to a presenter and never sent to the knob**; neither a service op (VOC §7.4's 1:1 list) nor a presenter effect |
| presenter effects | §11.1 | Tk thread; each posts to the presenter's newest-wins mailbox and returns (K4 §2.3), except the v6 synchronous `windows_open` / `windows_activate` | presenter events (§11.1) |
| `toast` | `text`, `exit` (§12; K4 §10.3) | Tk thread | — |
| `device_enter` | `control` | device bridge | — (unchanged, `RT:1424-1428`) |

### 10.2 Invalidation

`invalidate_actions()` (`RT:1395-1411`) drops unsent **write** effects: `volume`, `transport`, `play_items`, `play_next`, `seek`, `shuffle_reorder`, `set_shuffle`, `jump`, `move_next`, `like`, `unlike` (**[r2.2]** withdrawn) (VOC §7.4; A05 §2.6). Reads are dropped by their obsolete control or view id as today. `obsolete_group` (`CT:813-814`) covers every op carrying `expected_group_revision`. Already-dispatched work finishes honestly and is never replayed after a reconnect (S03 "Reconnection").

### 10.3 Progress channel

Jobs may call `progress(payload)` any number of times before completing. The runtime posts `("progress", request, payload)` on its results queue (`RT:341`); `poll()` routes it to `controller.progress(request, payload)` before completions (`RT:1482-1488`). A progress for a request no longer pending is ignored.

### 10.4 Runtime deltas

| Area | Change | Today |
|---|---|---|
| device events | `hold` → `controller.hold` (including a `kh` deferred to just after `ready`, K1 §11.2); `button` passes `hid`; `ready` → `device_ready(id)` (`device.py` re-seeds its pressed mask from `ks`, K1 §11.3; the controller no longer needs it, C5-8 withdrawn); `limit` → `controller.limit(dir, id)` besides the touch and `limit_seq` | `RT:1581-1675`; limit only a touch (`RT:1617-1627`) |
| hotkey | `controller.open_windows()` | `button(2)` (`RT:1330`) |
| serial skip | drop `kd` with `hid`; else drop logical 3 on Home when the hotkey is registered | logical 2 always (`RT:1642-1647`) |
| `windows_button` | `button_order[3]` | `button_order[2]` (`RT:1603`) |
| `_note_library` | every Apple result feeds `music_signin_expired` | `recent` only (`RT:1140-1149`) |
| disconnect / error / released | also `controller.close_overlay("disconnect")` via `disconnected()`; toast service drops pending toasts | `windows.hide()` only (`RT:1649-1657`) |
| presenter events | drained by the adapters' `pump()` on the Tk tick (K4 §2.3) and passed, every one, to `controller.presenter_event(event)`, the single entry point (§2.5; VOC-R22), which dispatches: `system(lock)` → `close_overlay("lock")`; `system(sleep)` (suspend **or** display off, K4 §4.1) → `close_overlay("sleep")`; `system(display)` → nothing (the presenter closes its own scene and reports `closed(surface, "display")`); **`system(motion)`** → re-evaluate the Motion setting at once (§14.3); `closed(surface, reason)` for `display` / `device` → `presenter_closed`; `refused` → `presenter_refused`; `click_action(surface)` → `button(3)`; `snap_result`, `cancel_result` → the controller calls of §2.5; `opened` / `closed` also update the `open_surfaces` registry (K4 §2.4). There is no `display_off` kind (C5-53) | none |
| art identity | per mode: explorer = focused item (playlist: first mosaic cover); upnext = focused row; seek/tracks = now playing | `RT:476-488` (`ART_LAYOUTS`, `RT:78`) |
| accents | per mode: recent/explorer recent = album; favourites = playlist (first cover with art); upnext = row album; windows = app. **No-art items** (Recent, explorer, Up next rows) use the Generated-sleeve palette accent `GEN[h mod 8].accent` with K4 §13.6's hash `h` of the title and artist (BS `genOf`) (VOC §3.5; BS:536-537). **Sent as 0 (warm)** (K2 M26): the palette's eighth entry (index 7, accent `(255,190,105)`, the warm marker BS draws warm, `isW`, BS:1328) and monochrome app icons | `kind = "window" if windows else "recent"` |
| media wanted lists | explorer and Up next mirrors by distance (VOC §7.1 knob art) | Recent pages by distance |
| entry art | §6.3 | — |
| ledger | `QueueLedger` owned by the runtime, written from `_final_song_ids` (`play_items`) and `_inserted` (`play_next`) on success, read by the controller through `upnext_view()` and passed into `shuffle_reorder(off)` (**[P2a]** as `playnext_units()`, C5-73) | — |
| lanes | §1 table and the §1.1 scheduler | `RT:334-338`, `_background` (`RT:1335-1376`) |

### 10.5 Knob art: what `artwork.py` sends as each `artKey` (WP6; K1 §8.4; C5-58)

K1 §8.4 needs the host to send every knob cover pre-composited and to render the covers r2.1 draws for items without a usable image. WP6 owns `artwork.py` (§0.4; 00 §4.2), so this contract fixes it; K4 §13 owns only the desktop sizes.

| Step | Rule | Source |
|---|---|---|
| 1. Pick the 240 px source (per the art identity row of §10.4) | Apple art: request the **240** rung (`art_template`, RA §4.1). Sonos-only rows: `sonos_art` (400 px) downscaled | K4 §13.1 "Knob (artwork2 240 px)"; RA §4.1 |
| 2. Pick the art state at need = 240 | `art.full` when `u = 240 / art_max ≤ 1.5` (LANCZOS to 240, centre-cropped); `art.extended` when `u > 1.5` (K4 §13.6 recipe at 240 px: radial gradient of the cover's dominant colour, the cover sharp at 1.5× its native size, centred); `art.loading` while the cover is not fetched yet = a solid 240 × 240 of `art_bg` (`#232325` when `art_bg` is 0, S5-11), **no text** (the knob LCD draws the title and artist itself, K1 §8.6); `art.generated` when the item has no art = the 160° linear gradient `g0 → g1` of `GEN[h mod 8]`, **no text** (K4 §13.6: "the ambient and the knob LCD use the gradient") | K1 §8.4 ("loading items a host-rendered `bgColor` cover, missing art a host-rendered Generated-sleeve cover"); K4 §13.5-§13.6 |
| 3. Composite the r2.1 scrim | `pixel = cover × 0.8 × (1 − s(y))`, `s` at pixel centres `y + 0.5`, linear between the stops **(0, 0.60), (108, 0.72), (148.8, 0.92), (168, 1.0)**, `s = 1` below 168 (`_SCRIM_STOPS`); every state above, the v1 120 px cover included | K1 §8.4; R:84; S01:121 |
| 4. Encode and key | baseline JPEG for artwork2 (AW2 §4); `artKey` = the content hash of the composited bytes, so loading → real cover is a new key and swaps instantly on the knob (K1 §8.4 motion) | K1 §8.4; AW2 |
| Budget | on the existing artwork2 prefetch workers (3 threads, ARTWORK2 §9), never on Tk; no `alpha_composite` over 64 K px while an overlay animates (K4 §4.7.3) | ARTWORK2 §9; K4 §4.7.3 |

The capability string stays `"scrim80"` (K1 §8.4). Tests: `test_cc_knob_art_v7.py` (WP6) checks the scrim stops at rows 0, 107, 108, 148, 168, 239 against K1's formula, the four art states, and that a loading key differs from the real cover's key.

---

## 11. Presenter contract (controller ↔ K4 surfaces) (C5-53)

One interface, frozen in both contracts: the controller's effects are **pushed** to the presenters with every field K4 §2.3 requires, plus `t0`. The runtime's presenter facades (Tk thread) build each payload from the view models of §11.2 and post it to the presenter's newest-wins mailbox; presenters never call back into the controller (K4 §2.3). Presenters answer only with the events of §11.4.

### 11.1 Presenter effects (Tk thread, non-blocking post; names VOC §7.4)

Every effect also carries `kind`, `request`, `control_id` (the controller's current control id) and `view_id` (§10.1). **`t0`** is the controller clock (`time.perf_counter`, QPC seconds, K4 §0.6) at the press or event that caused the effect; the presenter anchors every scheduled leg to it (`t0 + 190`, `+200`, `+360`, `+380`, `+820`), not to the time the post arrives (K4 §4.6.4 hold segments). `control_min` is always **0** in the list modes (bounds start at 0, §2.1), so K4's fast path `index = p − control_min` (K4 §5.3, §22 Q3) equals `Screen.index`; a later controller `*_highlight` with a different index wins.

| Effect | Payload (K4 §2.3 fields **+** K3 fields) | Meaning |
|---|---|---|
| `explorer_open` | `t0`, `source` (`recent` \| `favourites`), `index`, `count` (int, or `None` while the first page loads), `items` (descriptors for the preload window, ±12 + 4 ahead of `index`: §9.8.6 / §9.8.5 item shape with the K4 §13.2 art keys), `items_first` (absolute index of `items[0]`), `items_rev` (int, bumped on any list change), `state` (`loading` \| `ready` \| `empty` \| `signin` \| `error`), `control_id`, `control_min`, `reduced_motion`, `foreground_hwnd` (the foreground window at the press), `sonos_available` | open the scene (never takes focus) |
| `explorer_source` | `t0`, `source`, `index` (the new source's remembered index, §5.3.2), `count`, `items`, `items_first`, `items_rev`, `state` | cards exit at `t0`; the new source enters at `t0 + 190` **at `index`**; positions from the old `control_id` are discarded (§5.3.3) |
| `explorer_highlight` | `index`, `control_id`, `bump ∈ {-1, 0, 1}`; `items`, `items_first`, `items_rev` when `items_rev` changed; **`state` and `count` when either changed** (a data update with an unchanged `index` plays no turn, K4 §2.3) | a detent landed / an end bump / new descriptors / a state change (the state block, K4 §7.4, §7.6) |
| `explorer_close` | `t0`, `reason` (VOC §7.3), `close_at_ms` (380 for `play`, else 0) | close; `play` plays the grow first |
| `upnext_open` | `t0`, `rows` (the loaded window, ≤ 21 around the focus; row shape §5.6.3 with `role`, `segment`, `liked`, the art keys), `now` (P − 1), `focus`, `count` (T, or P + 1 with the card), `card` (`{n}` \| `None`), `context` (`{kind: album \| playlist \| foreign, title, sub}`, §9.7.3), `shuffle` (`off` \| `companion` \| `sonos`), `likes_known` (bool), `loading` (bool), `control_id`, `control_min`, `reduced_motion`, `foreground_hwnd` | open |
| `upnext_highlight` | `index`, `control_id`, `bump` | — |
| `upnext_rows` | `t0`, `reason` (C5-54, below), `rows` (the patch), `now`, `focus`, `count`, `card`, `shuffle`, `likes_known`, `context` (when it changed) | see the reason table |
| `upnext_close` | `t0`, `reason`, `close_at_ms` | as explorer |
| `windows_open`, `windows_activate`, `windows_hide` | v6 fields (CAR §1) | v6 names kept (VOC-N15) |
| `windows_highlight` | v6 fields + `index`, `control_id`, `bump` | — |
| `windows_cancel` | `origin`, `home: true`, `complete` (`left` \| `right` \| `None`), **[P3]** `reason` (`back` \| `hold` \| `lock` \| `sleep` \| `idle`, C5-78) | answered by `cancel_result` (§9.9) |
| `windows_snap` | `t0`, `index`, `side`, `target_rect` (physical `rcWork` half of the picker monitor), `place_at_ms` (360) | answered by `snap_result` (§9.9) |
| `windows_close_pair` | `left`, `right`, `focus` | — |
| `toast` | `text`, `exit` (bool) (K4 §10.3) | the controller posts exit toasts at their due time (§12.1), so K4's `max(t_close + 360, t_request)` resolves to `t_request` |

**`upnext_rows` reasons** (one enum with K4 §2.3; C5-54):

| `reason` | Sent when | Patch | K4 behaviour |
|---|---|---|---|
| `data` | rows land (`queue_window`); catalog or ratings enrichment lands (art keys, `catalog`, the first `liked` states); a row becomes non-catalog | the changed rows | fill in; heart states set **without** a pop |
| `likes` | a like **or** an unlike is confirmed (§5.6.6); **[r2.2]** a like only | `[{row, liked}]` (**[r2.2]** `liked:true` only) | the heart pop / unlike animation (K4 §8.3); **[r2.2]** the pop only: the unlike animation is withdrawn |
| `shuffle` | at the Shuffle press (companion on, and off = restore), or when a native `set_shuffle` result lands (§5.6.5) | the whole loaded window **in the new order**, `focus`, `shuffle`, `card` | rows fade out (160 ms IN) at `t0`, re-enter at `t0 + 200` (K4 §8.5) |
| `queue_changed` | a re-read after a revision change or a failed shuffle (§5.6.8) | the whole loaded window | re-render in place |

### 11.2 View models (read-only, Tk thread, used by the facades)

- `explorer_view()` → `{source, index, recent: {items (window of ±12 + 4 ahead around the index), first, total, state, complete, rev}, favourites: {items, state, rev}, sonos_available, reduced_motion}`.
- `upnext_view()` → `{focus, now, T, rows (loaded, with roles), regime, card: {n} | None, context (§9.7.3), shuffle ∈ {off, companion, sonos}, likes_known, loading, shuffle_line ∈ {overlay.upnext.shuffle_on, .shuffle_off, .shuffle_sonos}, hints (overlay.upnext.hints with Shuffle/Shuffle off and Like/Unlike, BS:1412; **[r2.2]** Like/**Liked**: `[3] Liked` on a liked row, R22 CH §1), reduced_motion}`.
- `windows_view()` → `{items, index, left, right, keep: origin item | None (the one-side preview, S01:410), failure: {side, reason, until} | None}`.

### 11.3 Presenter input (C5-27; CAR §9 deviation 5; UI:1558-1565; RF0 AR-4; K4 §3)

| Surface | Input | Controller call |
|---|---|---|
| explorer | `click_action(explorer)`: press and release inside the centre card's rest rect | `button(3)` (Play; a dimmed Play gives its reason and the shake) |
| Up next | `click_action(upnext)`: press and release inside the focus plate | `button(3)` (Play) |
| explorer, Up next | any other click, every wheel turn | eaten by the stage (K4 §3; S5-3, S5-23); never reaches the controller |
| explorer, Up next | keys | never received: the stage never has focus, so keys go to the foreground app (R §7.3; K4 §22 Q4) |
| picker | Enter / centre-card click, Esc | `button(3)` (Switch), `button(0)` (Back) (`UI:770`, `:775`) |
| picker | wheel, arrow keys | `turn(±1)` **only without a knob session** (`controller.hardware` false), as `_picker_turn` today |

There are no picker keys for Snap: K4 defines none, so Snap is Buttons 2/3 on the knob only (the v6-era `snap(side)` presenter path is dropped, C5-27).

### 11.4 Presenter events (K4 → Tk, drained by `pump()`; routing §10.4)

| Event | Controller |
|---|---|
| `opened(surface)` | — (registry only, K4 §2.4) |
| `closed(surface, reason)` | nothing for a close the controller asked for; `presenter_closed` for `display` / `device` (§13.1) |
| `click_action(surface)` | `button(3)` for the current control |
| `refused(surface, busy \| device)` | `presenter_refused` (§13.5) |
| `system(lock \| sleep \| display \| motion)` | §10.4 presenter events row |
| `snap_result(side, accepted \| hung \| move_rejected \| ok \| cant_fit)` | §5.7.3 |
| `cancel_result(restored, completed)` | §5.7.4 |

---

## 12. Toasts

### 12.1 Service rules (S01 §8; R §7.3; CH §7 #11-12)

1. **Never over an open overlay.** A toast requested while the explorer, Up next or the picker is open (or opening) is **dropped**, unless it is that overlay's **exit toast**.
2. **Exit toasts** start `exit_toast_delay_ms` = **360 ms after the close trigger** (BS:771). If the result arrives later, the toast starts at the result. If another overlay is open at that moment, the toast is dropped.
3. **Hold** `toast_hold_ms` = **1800 ms**; a new toast replaces the current text at once and restarts the hold (BS:773).
4. **No toast** for Play/Pause, Back (picker Back without a completion included), **any `hold` close** (VOC §7.3; BS:893-898; C5-36), Seek, volume, or anything while an overlay is open (Like, Shuffle, snap failures carry their feedback on the knob, S01:422).
5. Placement: bottom centre of the foreground window's monitor, top 588 in the 720 stage (K4).
6. Text: the copy ids of §12.2 with placeholders filled; K4 fits the text.
7. Exit toasts are posted with `exit=True` at their due time (§11.1). K4 drops any toast while `SHQueryUserNotificationState` is 3 or 4 (a full-screen D3D app or presentation mode; K4 §10.4, S5-17).

### 12.2 Catalogue (every toast the companion raises)

| Toast id | Trigger | Timing |
|---|---|---|
| `toast.playnext.ok` | Play next ok (Recent) | on the result (no overlay) |
| `toast.playnext.not_queue` / `.none` / `.shuffle` | Recent 3 refused (§3.3) | at the press |
| `toast.playnext.nothing` / `.partial` / `.song_changed` | Play next failures | on the result |
| `toast.start.ok` / `.partial` / `.album_blocked` / `.failed` | start results | Recent: on the result; explorer / Up next: ≥ 360 ms after the close |
| `toast.skip.next` / `toast.skip.prev` | Tracks skip ok | on the result |
| `toast.switch` | Switch ok | 360 ms after the picker close |
| `toast.snap.pair` | both sides placed | 360 ms after the 820 ms close |
| `toast.snap.one_side` | picker Back with `cancel_result(completed=true)` | `max(close + 360 ms, cancel_result)`; never after `hold` |
| `toast.like.signin_expired` | a sign-in expiry during the Up next session | 360 ms after a `back` close only (C5-36) |

`{name}` = album, playlist, song or row title; `{album}` = the Play next item's title; `{k}`, `{n}`, `{u}` from `_start`; `toast.start.partial` uses `songs` when `{u}` > 1 (VOC §9.2). **[r2.2]** Approved: `Playing {k} of {n} · {u} songs unavailable`, `1 song` when `{u}` = 1 (R22 CH §2).

### 12.3 Starts from overlays

The exit toast of a start is scheduled at `max(closed_at + 360 ms, result time)`; a failure toast follows the same rule.

### 12.4 Exit-toast arming

An overlay session has at most one armed exit toast (the latest wins). `hold` closes drop it (VOC §7.3; BS:893-898 `goHome` flashes nothing), and so do `lock`, `sleep`, `idle`, `disconnect`, `focus_lost`, `group`, `foreground`, `source`, `display` and `device` closes ("close instantly, with no toast", S01:426; K4 §15).

### 12.5 Balloons (C5-26)

The tray balloon (`ST:671-708`, one per 10 s) stays for failures that have **no** r2.1 toast (volume, Play/Pause, skip, picker open) and shows the full `notice` text. A failure that has a toast never balloons. No balloon is shown while an overlay is open (it is dropped).

### 12.6 The desktop notice

`controller.notice` keeps the full sanitized failure text (`CT:832-833`, `:867-868`) for the balloon and the Settings strip's detail; it is never knob copy.

---

## 13. Overlay lifetime

### 13.1 Close reasons (VOC §7.3)

| Reason | Detector | Surfaces | Knob goes to | U12 completion | Toast |
|---|---|---|---|---|---|
| `back` | Button 1 | all | parent (§4.1) | applied | its exit toast |
| `hold` | `kh` (§4.2) | all | `home` | applied | **none** (VOC §7.3; BS:893-898; C5-36) |
| `play` | Button 4 | explorer, upnext | `home` at 380 ms | — | start toast |
| `switch` | Button 4 | picker | `home` | — | `toast.switch` |
| `pair` | second snap | picker | `home` at 820 ms | — | `toast.snap.pair` |
| `lock` | presenter event `system(lock)` (K4 §4.1: `WTS_SESSION_LOCK`, console or remote disconnect; for the picker also K4 §15's input-desktop test) | all | parent | applied | none |
| `sleep` | presenter event `system(sleep)` (K4 §4.1: `PBT_APMSUSPEND`, or display off `GUID_CONSOLE_DISPLAY_STATE` = 0) | all | parent | applied | none |
| `idle` | **60 s** without knob input (`last_knob_input`: position, button, hold, `lim`) while an overlay is open | all | parent | applied | none |
| `disconnect` | device `disconnected` / `closed` / `error` / `released` | all | no host mode; knob-local (VOC-R23): `Waiting for PC` **only after a lost host** (lease expiry); the native screen after an intentional release or a power-up (K1 §8.10, P5-11); LEDs offline after any release (K2 §8.1) | not applied | none |
| `focus_lost` | `WindowsAdapter.on_focus_lost` | picker | `home` | not applied | none |
| `group` | `group_revision` changed in a result or poll | explorer, upnext | parent | — | none |
| `foreground` | an external foreground change (the adapter's WinEvent hook, A05 §5.7) | explorer, upnext | parent | — | none |
| `source` | the source class leaves `queue` | upnext | `tracks` | — | none |
| **`display`** (VOC-K4-01) | presenter-initiated: `closed(surface, "display")` after a monitor or DPI change (K4 §4.3, §15; picker EV_DISPLAY) | all | parent | not applied | none |
| **`device`** (VOC-K4-01) | presenter-initiated: `closed(surface, "device")` after the stage device was lost (K4 §4.3) | explorer, upnext | parent | — | none |

"Parent" is VOC §7.1: explorer → `recent`, Up next → `tracks`, picker → `home` (S01:427). For `display` and `device` the presenter has already closed its scene; `presenter_closed` runs §13.2 steps 1, 2 and 4, drops the armed exit toast (§12.4) and emits no close effect (C5-55).

### 13.2 What a close does in the controller

1. Cancel due re-entries of the closing Screen (§6.2).
2. Seek is not an overlay; a lifetime event while in Seek does nothing to Seek.
3. Emit `*_close{reason}` (or `windows_cancel`/`windows_hide`); drop or keep the armed exit toast (§12.4).
4. Re-enter the target mode.

### 13.3 Full-screen apps (C5-33)

Overlays open whatever the notification state, because the user asked for them (K4 S5-17, §17.3; 00 G9's "don't open over full screen" is not adopted). Only toasts are dropped while `SHQueryUserNotificationState` is 3 or 4 (K4 §10.4). The controller has no full-screen rule of its own.

### 13.4 Disconnect and reconnect (C5-2)

`disconnected()` (`CT:532-540` extended): close every overlay (`disconnect`), exit Seek dropping its target, clear `transient`, `start` stays (its job may finish honestly and its result applies silently), and set the Screen to `home`. `set_hardware(True)` then re-enters Home after the fresh state read (S03 "Reconnection: … read fresh state and go to Volume"; v6 resumed the current screen).

### 13.5 A presenter refuses to open (C5-55; VOC-K4-02)

The controller has already entered `explorer` or `upnext` at the press (§5.3.1 step 2, §5.6.1). On `refused(surface, reason)`:

| `reason` | Cause (K4) | Controller |
|---|---|---|
| `device` | the stage thread failed to start, or neither the monitor's adapter nor WARP gave a device (K4 §4.1, §4.2) | cancel the Screen's due re-entries; re-enter the **parent** (`recent` at the explorer's recent index, or `tracks` at `parent_index`); `feedback{err}` (Head shake); transient `knob.meta.stage_unavailable` (**[r2.2]** `Couldn’t open on screen`, was `Can’t open on screen`; `error` tone, `fail_meta_ms` 2400) on the parent's `meta` line; no toast; desktop notice + log |
| `busy` | another overlay is registered open (K4 §2.4); the controller's one-overlay rule makes this a bug | as `device`, and log it at warning level |

A favourites load or an Up next read already in flight continues, and its result updates the lists silently.

---

## 14. Settings (no main window)

### 14.1 Status strip (S01 §12; 00 U14; BS:1368-1372)

Three columns at the top of Settings, refreshed every 1000 ms while Settings is open (the `_refresh_setup_actions` pattern, `UI:1370`):

| Column | OK state (mark `#6ED996`) | Problem state (mark `#FF7A66`) | Source of truth | Action |
|---|---|---|---|---|
| Knob | `settings.knob.ok` with `{v}` = the firmware version from `capabilities` | `settings.knob.problem` | `runtime.device_connected ∧ device_supported` | `Knob settings…` (OK) scrolls to the Knob USB port and button-order fields; `Troubleshoot…` (problem) shows `runtime.device_status` under the strip and focuses the port field (C5-39) |
| Sonos | `settings.sonos.ok`: `{Room}` = `room_label`, source phrase by `state.source` (`queue` → `Playing from the Sonos queue`, `airplay` → `Playing via AirPlay`, `radio` → `Playing radio`, `linein` → `Playing line-in`, `none` → `Idle`), `{ip}` = `state.host` | `settings.sonos.problem` | `controller.state["online"]` | `Set manual IP…` focuses the speaker IP field (a change applies after a restart, as `SETUP_SAVED_NOTES`, `UI:122-129`) |
| Apple Music | `settings.apple.ok` | `settings.apple.problem` (the action is the primary light button); **not signed in** (no Music user token): `settings.apple.none` (§15.3, C5-39) | `runtime.music_signin_expired`; `apple.has_credentials()` | `Renew sign-in…` / `Sign in…` runs the existing MusicKit authorization (`UI:1716-1730`; `CRD:146-252`) |

Style: companion dark palette, 8 px square marks, 2 px rule under the strip (S01:461-462). The tray's Settings item is renamed `tray.open_settings` and opens Settings scrolled to the strip (S01:463).

### 14.2 Consent copy (CL §4.5)

`credentials.py:245` stops promising "does not … modify your library" and uses `settings.apple.consent` (§15.3). Re-authorization is not technically required (CL §1 "Token scope"); the new text shows at the next sign-in.

### 14.3 Motion setting (VOC-R09)

Settings key `motion ∈ {"system", "full", "reduced"}` (default `"system"`), shown as a segmented control `settings.motion.*` (§15.3). Effective value: `system` → `SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION = 0x1042)` false → reduced (00 G16); re-evaluated **at once** when the stage host posts `system(motion)` (it watches `WM_SETTINGCHANGE` with `SPI_SETCLIENTAREAANIMATION`, K4 §4.1), and every 5 s on the Tk tick as a backstop (the stage thread may be down). The runtime calls `controller.set_reduced_motion(on)`; the frame carries the latched `reducedMotion` in every `control` and in the next frame after a change (VOC §6.2); the facades put it in every open payload (`reduced_motion`, §11.1), which the presenters latch at open (K4 §16).

### 14.4 Existing controls kept

`Album artwork`, `LEDs` (`Colour` / `Warm only`, stored `color` / `white`, `UI:130-133`), `Switcher background` (`Frosted` / `No background`, `UI:116-117`, U9), the button-order probe, the Apple Team ID / Key ID / `.p8` fields.

**settings.json keys without UI** (read by `device.py`, sent in **every enter frame** to a knob with `alive`, never to others; VOC §6.2; K1 §7.3; K2 §3.2): `led_drive` → `ledDrive`, `led_dither` → `ledDither` (existing), and new **`led_pink`** (an int 0..0xFFFFFF, or a `"#RRGGBB"` string converted to the int; 0 = the built-in PINK) → `ledPink`, **`led_vol_full`** (bool) → `ledVolFull`. They exist for the LED tour in the hardware window (PINK pick; the U8 body-level A/B) and are never shown in Settings.

---

## 15. Copy use

### 15.1 Sources

Knob, toast, overlay, Settings and tray copy come from VOC §9.2 (r2.1 Appendix C), §9.3 (r2.1 outside App C), §9.4 (retained v6) and §9.5 (engineering). Typography is exact (VOC §9.1). Knob lines are fitted by the host to their measured limits (meta ≤ 170 px, status ≤ 160 px, line ≤ 170 px, Montserrat 500, VOC §9.1): placeholders (`{App}`, `{title}`, `{name}`) are ellipsized first, measured with the `lcd_preview` font metrics (WP1 exposes `measure(text, size)`).

### 15.2 v6 copy audit (VOC §9.4 asked K3 to audit `CT:1049-1196`; today `CT:995-1274`)

| v6 string | Where | v7 | Id |
|---|---|---|---|
| `Looking for Sonos…` (title before the first read) · `Sonos unavailable` / `Looking for Sonos…` / `Windows still works` (title / sub / meta) | Home notice | **kept** | `knob.title.looking_for_sonos`; `knob.title.sonos_unavailable`, `knob.sub.looking_for_sonos`, `knob.meta.windows_still_works` |
| `Setting…`, `Changed on Sonos`, `Minimum`, `Maximum`, `Paused` | Home | kept | VOC ids |
| `Starting…` / `Pausing…` (transport pending) | Home status | kept (S03 Home) | `knob.status.starting`, **`knob.status.pausing`** |
| `Nothing playing`, `Now playing`, `Paused · {title}` | Home captions | kept | VOC ids; **`knob.caption.now_playing`** for `Now playing` |
| `Group changed` | Home condition | kept (**[r2.2]** reworded `Speaker group changed`, R22 CH §2) | **`knob.status.group_changed`** |
| `Connecting knob` | knob syncing | kept | **`knob.status.connecting`** |
| `Music login needed`, `Playback incomplete`, `Queue changed`, `Action failed: see app`, `Last action failed`, `Preparing playback`, `Stopped` | Home / lists | **retired** in their v6 roles (sign-in states, start copy, shake). The text `Queue changed` returns as `knob.meta.shuffle.queue_changed` (K1 OQ-2, §15.3), a different meaning | — |
| `Nothing recently added` / `Apple Music library` | Recent empty | kept | **`knob.title.recent_empty`**, **`knob.sub.recent_empty`** |
| `Apple Music sign-in expired` / `Renew on your PC` | Recent, explorer | kept | **`knob.title.signin_expired`**, **`knob.sub.signin_expired`** |
| `Library not loaded` / `Home, then Browse to retry` | Recent error | title kept; sub **shortened to `Home, then Browse`** (141.2 px; the v6 text is 197.1 px at 14 px, over the 170 px sub line; K1 §8.6.11, OQ-6; approval pass; **[r2.2]** approved) | **`knob.title.library_error`**, **`knob.sub.library_error`** |
| `Loading…`, `Page {n}`, `RECENTLY ADDED · P{n}`, `More`, `Next 10 items`, `· Loads, doesn’t play`, `· Replaces queue`, `· Not available`, `· Sonos unavailable`, `Queue replaced · didn’t start`, `Starting…` (Recent meta) | Recent | retired (flat list, hybrid Play) | `Loading…` → `knob.meta.loading` |
| `Skipping…` | Tracks meta | kept (S03 Tracks) | **`knob.meta.tracks.skipping`** |
| `Previous unavailable` / `Next unavailable` | Tracks | kept as refusal copy (C5-25) | **`knob.meta.skip.prev_unavailable`**, **`knob.meta.skip.next_unavailable`** |
| `One press, one skip`, `Press once to skip`, `Skipped · back at neutral`, `Turn to choose · Green to skip`, `Next unavailable for this source` | Tracks | retired | — |
| `No eligible windows` | Windows | kept (sub dropped) | **`knob.title.no_windows`** |
| `Cancel to return`, `Turn to preview · Green to switch`, `Window switched`, `Original window no longer available` | Windows / desktop | retired from the knob; the last stays a desktop notice | — |
| `Switching…`, `Didn’t come forward · retry`, `Closed · can’t switch` | Windows | kept | VOC ids |
| `Volume confirmed`, `Playing selected item`, `Reading Sonos…`, `Adjusting volume…`, `Loading library…`, `Loading next page…`, `Resolving library item…`, `Sonos unavailable · check connection`, `Group changed · volume refreshed`, `Knob disconnected · reconnect to resume`, `Synchronizing knob…` | desktop statuses | internal only (never on the knob) | — |

### 15.3 Additions for the one approval pass (00 G13; C5-29; **[r2.2]** approved, C5-70)

**[r2.2] The approval pass is closed** (R22 CH §2; C5-70; VOC-R29): every row below is approved as listed, except the four (**[r2.2]** corrected from "three") marked **[r2.2]**, which take the design's text. All of them are rows of R22 App C. The only copy item still open is CH "Still open" → "Font check" (K1 §15.3 `copy` with the real font build).

| Id | Text | Why |
|---|---|---|
| `knob.meta.playnext.resolving` | ~~`Queueing…`~~ **[r2.2] `Finding songs…`** (94.7 px) | Play next during the Apple lookup and until the first song is queued, instead of `Queueing… 0 of {n}` (§5.2.4, §9.3; R22 CH §4; C5-69) |
| `overlay.upnext.sub_playlist` | `Playlist · {n} songs · {duration}` | a started playlist that is not favourited (BS only draws favourites) |
| `overlay.explorer.meta_album` | `{year} · {n} tracks` (`1 track`) | BS explorer label meta (`xc.y + ' · ' + xc.n`, BS:1189) |
| `overlay.explorer.meta_playlist` | `{n} songs · {duration}` (`1 song`); `{duration}` = `{h} h {mm} min` or `{m} min` | BS `PL[].n` format; 03 Q7 |
| `overlay.explorer.untitled` | `Untitled playlist` | CF §5 unnamed rows |
| `overlay.explorer.signin_title` / `.signin_help` | `Apple Music sign-in expired` / `Open Settings on your PC to sign in again.` | the explorer's state block for 401/403 with nothing cached, on **either** tab (K4 §7.4; VOC-K4-04) |
| `overlay.explorer.recent_empty_title` / `.recent_empty_help` | `Nothing recently added` / `Add an album or a playlist to your library in the Music app.` | the explorer's state block, Recently Added empty (K4 §7.4, S5-33; VOC-K4-04) |
| `overlay.explorer.error_title` / `.error_help` | `Library not loaded` / `Go Home, then Browse to retry.` | the explorer's state block, list error (K4 §7.4; VOC-K4-04) |
| `settings.apple.none` | `Not signed in` · `Sign in to use Recently Added, Favourite playlists and Like.` · action `Sign in…` | first run (the strip has only OK/expired) |
| `settings.motion` | `Motion` · `Match Windows` / `Full` / `Reduced` | VOC-R09 |
| `settings.apple.consent` | `Allow Desk Dial to read your Apple Music library and to mark songs as Favorites when you press Like. A Favorite can add the song to your library.` | CL §4.5; **[rename]** was `Allow Nano_D++ …` (VOC-R32) |
| Home slot-0 label | `Play` / `Pause` (follows the icon; replaces r2.1's `Play/Pause`) | 67.4 px cannot fit the 46 px idle-row column (VOC-D08; K1 P5-12; C5-60); 25.9 / 37.3 px |
| `knob.meta.shuffle.queue_changed` | `Queue changed` (was `Queue changed · order kept`, 172.2 px) | shuffle-off restore refused; fits the 170 px meta line (98.4 px; K1 OQ-2; VOC §9.5) |
| `knob.sub.library_error` | `Home, then Browse` (was `… to retry`) | fits the 170 px sub line (141.2 px at 14 px; K1 OQ-6; §15.2) |
| `knob.meta.busy.starting` / `knob.meta.busy.pausing` / `knob.meta.busy.shuffling` | `Starting…` / `Pausing…` / `Shuffling…` | a busy-dimmed press where the busy line is not on screen (§3.2, C5-59); the first two are the `meta` twins of `knob.status.starting` / `knob.status.pausing` (57.6 / 58.1 / 63.7 px) |
| `knob.meta.shuffle.nothing` | `Nothing to shuffle` | Up next 2 with only Play-next rows upcoming (`nothing_next`, `U ≥ 2`, §3.2; C5-59) (110.8 px) |
| `knob.meta.library_error` | `Library not loaded` | the `list_error` reason drawn in `meta` (§3.2); the `meta` twin of `knob.title.library_error` (C5-56) |
| `knob.meta.signin_expired` | `Sign-in expired` | the `signin_expired` list reason (§3.2); the list twin of `knob.meta.like.signin_expired` (C5-56) |
| `knob.status.sonos_unavailable` | `Sonos unavailable` | the `sonos_unavailable` reason on Home's `status` line; the twin of `knob.meta.sonos_unavailable` (C5-56) |
| `knob.meta.group_changed` | ~~`Group changed`~~ **[r2.2] `Speaker group changed`** (147.6 px; "Group" alone is ambiguous, R22 CH §2); `knob.status.group_changed` takes the same text (≤ 160 px) | the `group_changed` transient on any `meta` line (§9.10); the twin of `knob.status.group_changed` (C5-56); **[P2a]** shown for `group_changed_ms` 2600 (C5-76) |
| `knob.meta.stage_unavailable` | ~~`Can’t open on screen`~~ **[r2.2] `Couldn’t open on screen`** (149.1 px; past tense like `Couldn’t move`, `Couldn’t queue`, R22 CH §2) | a presenter refused to open (§13.5; K4 VOC-K4-02 proposal, adopted; VOC §9.5); ~~129.0 px~~ **[r2.2]** 149.1 px < 170 |
| `knob.meta.like.unlike_in_music` (rev 4) | ~~**`Unfavourite in Music`** (125.9 px, meta tone)~~ **[r2.2] `Unfavourite in Music app`** (152.7 px, meta tone, 2200 ms; approved, R22 CH §1–§2) | ~~Unlike under `add_only`, or after `unlike_unsupported` (§3.2 `unlike_unavailable`, §5.6.6; C5-63).~~ **[r2.2]** A press on a liked row (`unlike_unavailable`, §3.2, §5.6.6; add-only final, C5-67). The wording asked for, `Unfavourite in the Music app`, measures **176.4 px** (Montserrat 500, 12 px, K1 §8.6.11 method), over the 170 px meta line, and would be ellipsized; both go to the approval pass. Spelling follows the product's `Favourite`; Apple's own menu item says `Unfavorite` |
| VOC §9.5 rows | as listed there | already proposed |

---

## 16. Simulator fakes (`simulation.py`)

The simulator reaches every r2.1 state-picker option (BS:1352-1365) with deterministic data and **no I/O**. A single `SimControls` object holds the knobs; the dev window (`UI:680-682`) and tests set them.

| BS group | Sim control | Values |
|---|---|---|
| PC connection | device bridge fake | connected / disconnected |
| Playing source | `SimulatedSonos.source` | `queue`, `airplay`, `radio`, `linein`, `none` |
| Sonos shuffle / Repeat | `play_mode` | the six Sonos modes |
| Play next outcome | `pn` | `ok`, `slow` (resolve 1.8 s, 0.5 s per insert), **`live`** (rev 4: uncached resolve 3.5 s, then 0.54 s per insert, LC W1; a pre-resolved item skips the 3.5 s), `partial`, `nothing`, `changed`; **[r2.2]** new value **`proto`**: the r2.2 prototype's timings, lookup 0.4 s (cached, a pre-resolved item) or 4.5 s (uncached), then 0.5 s per song (R22 BS:1015), for the `Finding songs…` → `Queueing… {k} of {n}` sequence; the existing values are unchanged |
| Starting playback | `start` | `ok`, `slow` (2.6 s), `fail`, `blocked` (album); PAPER LANTERN plays 33 of 34 |
| Seek | `seek` | `ok` (0.6 s), `slow` (1.8 s), **[r2.2]** **`slow5`** (resume after 5 s, the r2.2 prototype's slow jump, R22 BS:843; `live` covers its 2.7 s), **[r2.2]** **`noresume`** (never leaves `TRANSITIONING`: `not_confirmed` at 8 s), **`live`** (rev 4: `TRANSITIONING` for 2.65 s with the position already at the target from the first read, then PLAYING at the target; LC W2), `fail` |
| Like state | `like` | `ok` (rev 4: 202 after 0.4 s, rating 1 readable 1.0 s later), `loading` (ratings never answer), `expired` (401), **`unsupported`** (rev 4: the favourites `DELETE` answers 400; **[r2.2]** withdrawn), **[r2.2] `fail`** (the `POST` answers 429 or 5xx: `Didn’t save · try again` + Head shake; R22 BS state "Save fails") |
| Unlike strategy | `unlike` | **`add_only`** (default), **`favorites_delete`** (rev 4, C5-63). **[r2.2]** Withdrawn: always `add_only` (C5-67) |
| Up next | `upnext` | `normal` (album), `loading`, `foreign` (every third row non-catalog), `longshuffle` (> 60 upcoming) |
| Favourite playlists | `favs` | `real` (Favorite Songs, PAPER LANTERN Ep. 1), `empty`, `many` |
| Artwork | `art` | `full`, `mixed`, `small`, `missing`, `loading`, `list` |
| Snap outcome | `snap` | `ok`, `hung`, `move` (`move_rejected`), `fit` (`cant_fit`); plus `integrity` (`move_rejected` at the pre-check) |
| Stage | `stage` | `ok`, `refused` (`refused(surface, device)`), `display` (closes the open scene with `display`) |

Fakes:
- **`SimulatedSonos`** (today `SI:11-52`): a queue of row dicts (the 24-album BS library, BS:499-535), `playlist_position`, `play_mode`, `position_s` advancing on a sim clock, `duration_s` (BS `durOf`, BS:553), `source`, `can_seek`; ops `play_items` (with `_start`), `play_next` (positional insert, progress callbacks, outcomes), `seek`, `shuffle_reorder` (applies the plan, keeps a restore record), `set_shuffle`, `queue_window`, `jump`, `move_next`, `transport` (Previous under shuffle), group changes on demand.
- **`SimulatedAppleMusic`** (today `SI:55-90`): the flat Recently Added list with `meta.total`, pages of 25; `favourite_playlists`; `playlist_meta`; `catalog_songs`; `ratings`; `like`/`unlike` (rev 4: the favourites calls with a ratings store the read-back sees after a configurable delay; `unlike` raises `UnlikeUnavailable` under `add_only`; **[r2.2]** `like` only: the fake has no `unlike`, and a `fail` switch answers 429); `resolve(lenient)` with unplayable track index 20 of PAPER LANTERN (BS:521) and a per-call resolve counter (so tests see a pre-resolved Play next make no lookup); an `expired` switch raising 401-shaped errors with `status = 401`.
- **`SimulatedWindows`** (today `SI:93-118`): the BS window set (BS:727-735) with accents; `snap` posting `snap_result(side, accepted | hung | move_rejected)` and then `ok | move_rejected | cant_fit` per the chosen outcome (§9.9); `cancel(origin, complete)` recording placements and posting `cancel_result`; `close_pair`.
- **`FakeStagePresenter`** (tests): records every pushed presenter effect with its full payload (§11.1) and `t0`, posts the §11.4 events on demand (`opened`, `closed` incl. `display` / `device`, `click_action`, `refused`, `system(kind)`), and asserts that each payload carries K4 §2.3's required fields.
- **`FakeSpeaker`** (`tests\test_cc_music.py`, today `:216-280`): a configurable per-call latency on the fake clock (default 50 ms) so the §1.1 scheduler and the §9.2 deadline are testable, and a hook that advances `playlist_position` after the n-th SOAP call (§9.5 C5-50); rev 4: a seek script (`TRANSITIONING` for N ms with RelTime already at the target, then PLAYING or PAUSED_PLAYBACK; optionally never `TRANSITIONING`) for §9.4; **[r2.2]** plus a script that never leaves `TRANSITIONING` (→ `not_confirmed` at 8 s) and one that lands off the target (still `ok`).

---

## 17. Test plan

### 17.1 Existing suites (counts are today's `def test` counts)

| File | Tests | Action | Why |
|---|---|---|---|
| `test_cc_controller.py` | 70 | **rewrite** to §3–§5 | v4 grammar, `button(2)` = Windows, Cancel, resume-origin paths (A05 §11.2) |
| `test_cc_stage3.py` | 88 | **rewrite** copy per mode | §5 frames, §15 audit |
| `test_cc_lookahead.py` | 46 | **retire** most; keep visit bookkeeping cases; move to `test_cc5_recent_list.py` | flat list replaces pages/More/adoption |
| `test_cc_prefetch.py` | 18 | rewrite for the flat-list prefetch threshold | §5.2.2 |
| `test_cc_enter_frames.py` | 35 | rewrite presses; add the new modes; §6.3 entry art | — |
| `test_cc_runtime_colours.py` | 30 | rewrite presses, per-mode accents | §10.4 |
| `test_cc_warmup.py` | 24 | mostly unchanged (Browse is logical 1 in both grammars); mode rename `volume` → `home` | — |
| `test_cc_touch.py` | 16 | rewrite `SimulatorWindowsButtonTests` / `HotkeyTouchTests` to logical 3 on Home, `limit` routing | §4.3 |
| `test_cc_ui.py` | 56 | adjust `windows_button == button_order[3]`, `button(2)` → `open_windows` | §4.3 |
| `test_cc_media_runtime.py`, `test_cc_runtime_overlay.py`, `test_cc_handoff.py`, `test_cc_playback.py`, `test_cc_art_swap.py` | 30 / 67 / 17 / 14 / 7 | adjust presses on the way to a state; `play` → `play_items` | — |
| `test_cc_music.py` | 26 | keep every `play_items` case; `FakeSpeaker` gains positional insert, `ReorderTracksInQueue`, `SetPlayMode`, `SeekTime` and `duration`/`position` (`tests\test_cc_music.py:216-280`) | §9 |
| `test_cc_tray.py` | 62 | `Open Settings…` label | §14.1 |
| `test_cc_device.py`, `test_cc_media_bridge.py`, `test_cc_session_capture.py`, `test_cc_presentation.py`, `test_cc_contract_v4.py` | — | WP3 (K1) | — |
| `test_carousel_*`, `test_cc_windows.py` | — | WP7 (K4) | — |

CAR §1's "every controller test must stay green unchanged" is amended for v7 (A05 §11.2).

### 17.2 New suites (WP5 unless noted; headless, fake clock, seeded RNG)

| Suite | Covers |
|---|---|
| `test_cc5_grammar.py` | every mode × slot × state of §3.1: token, label (Home slot 0 `Play` with `play`, `Pause` with `pause`; every Home label ≤ 46 px by `lcd_preview.measure`, C5-60; **[r2.2]** Up next slot 2 `Liked` on a liked row, `Like` otherwise), `lit`/`color` (**[r2.2]** a liked row: `heart`, enabled, `lit:"on"`, never dimmed), enabled; every dim code in §3.2 with its evaluation order, copy (the line-matching ids of C5-56: `knob.status.sonos_unavailable` on Home, `knob.meta.*` elsewhere), tone, shake, toast; the per-mode `ignored` predicate of C5-59 (e.g. `shuffling` ignored in Up next but reason `Shuffling…` + shake on Recent 3/4, Explorer 4 and Tracks 4; `starting` ignored only on Home 1; `nothing_next` ignored only when `U < 2`); §3.4 silent guards; no desktop legend strings exist (VOC-R24); `no_length` for D = 60 000 s |
| `test_cc5_grammar_oracle.py` + `tests\js\grammar_oracle.cjs` | a golden of BS `renderVals().foot` (icon key, tone) for every state-picker combination (BS:1352-1365), compared with the controller after the VOC-N06 token map; deviations tagged C5-n. **[P2a]** The golden is the **r2.2** prototype's; every differing slot and its ruling is signed off in **Appendix A** (lead ruling R-e); an untagged difference fails the suite and is fixed to match the design unless a ruling is added there first; **[P2a]** (review KD-R6) the oracle's tags cover whole regions, so `tests\test_kdocs_contract.py` pins §A.2 exactly: a new, changed or vanished difference anywhere fails until Appendix A is updated |
| `test_cc5_back_hold.py` | §4: Back targets; hold from every mode; one action per `hold` event; a `kh` that arrives right after `ready` with no `kd` in that control (the firmware deferral, K1 §11.2 step 5) goes Home; **no host hold timer** (a `ready` with logical 0 held and no `kh` does nothing; a `ku` handled in the same poll never fires a Home); no toast after any `hold` close; presentation 4 has no hold; `hid` drop; F24 → `open_windows` only on Home |
| `test_cc5_reentry.py` | §6: every cause in the table with its time, guard window, index and bounds; control ids monotonic; profile per mode; entry art rule; passive rule incl. the loaded-end exception; due re-entries cancelled when their Screen leaves |
| `test_cc5_recent_list.py` | §5.2: fresh visit at item 1; pages of 25; ≥ 16 ahead; foreground vs lookahead lane; total known (unloaded positions) vs unknown (growth); `· end`; states empty / sign-in / error; `artDim` only on unavailable items; explorer shares the index; ring wire forms (C5-61): first page loading → `style:"off"` + `activity:"loading"`; an unloaded entry of a known list → `selection` with that entry's colour 0 and `activity` idle (or `pending` during Play next), never `loading` |
| `test_cc5_explorer.py` | §5.3: open at the Recent index; tab swap at 190 ms with ignored input, the new source entering at the controller's index, old-control positions discarded; favourites focus by id; thin, empty, loading, sign-in, error, each with its displayed `state` in `explorer_open` / `explorer_source`, and a state change while open sent in `explorer_highlight` with `state` and `count`; Sonos down; Play at 380 ms and Home `Starting…`; Back index; bumps; `refused(explorer, device)` → `recent` + shake + `knob.meta.stage_unavailable` |
| `test_cc5_tracks_seek.py` | §5.4–§5.5: neighbour lines incl. shuffle and repeat-all; end refusals; Previous under shuffle; Seek mapping (n0, max, t(n), T_end = D−3, examples incl. D = 210 s, p = 74 s → n0 = 15, max = 42 with Te = 207, A04 §7), `can_seek` false for D = 60 000 s, `max ≤ 12 001` at D = 59 999 s; debounce 250, latest wins, idle 3000 deferred while in flight, flush on each explicit exit (Button 1/2/3, hold), a track change, group change or disconnect drops the pending target (C5-47), failure line 2200, limit line 1500; **rev 4 (C5-65):** with the sim `live` seek, the frame keeps `ring.index` = the target, `Jumping…` and `activity:"pending"` for the whole 2.65 s (state polls that read the target position while `TRANSITIONING` change nothing), `ok` only after the confirmation, the idle exit re-armed from it; a confirmation that exceeds 5 s gives `not_confirmed` and exactly one `Seek` was sent; **[r2.2] (C5-68):** the deadline is 8 s (`noresume` → `not_confirmed` at 8 s, one `Seek`); `ok` comes when playback resumes even if the position is off the target; a turn during a jump moves `ring.index` at once and sends exactly **one** follow-up `seek` with the latest target when the first lands (not before 250 ms after the last detent), however many detents came; `Jumping…` and `activity:"pending"` stay set without a gap from the first send until the follow-up lands; the idle exit counts from the last landing; **[P2a] (C5-77)** Seek → turn → Button 1 or Button 2 while the first jump is in flight → a Recent or Up next start before it lands: no follow-up `seek` is ever sent (without the start it is); **[P3]** built (`SeekStartDropsFollowUpTests`): Recent, explorer and Up next starts; the target goes back to the acked one and a job still queued reads no newer one; the in-flight jump's failure still gives `err` (C5-16); a start with nothing waiting changes nothing |
| `test_cc5_upnext.py` | §5.6: open gates per source; windows ±10 and edge refill; roles; placeholders; ledger contexts (incl. `Favourite playlist · {n} songs · {duration}`); non-catalog rows; heart states (`data` patches do not pop, `likes` patches for like **and** unlike; **[r2.2]** like only, never `liked:false`); **rev 4 (C5-62…C5-64):** hearts only from `ratings` (a catalog batch never sets `liked`); `activity:"pending"` from the like press to its result; under `add_only` a press on a liked row sends no effect, keeps Button 3 enabled with `lit:"on"`, shows `knob.meta.like.unlike_in_music` ~~for 2000 ms~~ (**[r2.2]** struck: the duration is 2200 ms, below) and one `feedback{err}` per press; ~~under `favorites_delete` it sends `unlike`; `unlike_unsupported` switches the session to `add_only` (the next press on a liked row is refused without a request)~~; **[r2.2] (C5-67):** the refusal copy is `Unfavourite in Music app` for **2200** ms; no code path ever emits an `unlike` effect or `moment:"unlike"`, and `knob.meta.like.off` is never drawn; the label is `Liked` and the hints read `[3] Liked` on a liked row; a save failure (`fail`) shows `Didn’t save · try again` (error tone) for 2200 ms with one `feedback{err}`; a like read-back timeout gives `failed` and the late `ratings` check sets the heart by a `data` patch without a moment; shuffle hybrid (plan with the Play-next block first on **on** and off, `U_r < 2` ignored, `upnext_rows{reason:"shuffle"}` at the press, knob re-entry at 200 ms, acceptance moment, native regime card and bounds at completion + 200, `queue_changed`); ring wire forms (C5-61): `style:"off"` + `activity:"loading"` before the first window, placeholders as colour 0, the card as `card:true` with `count = P + 1`, `now = P − 1` and colour 0, and no Up next frame ever carrying `unavailable`; revision changes during our own job deferred; Play at 380 ms; passive changes; `source` close; `refused(upnext, …)` → `tracks`; **[P3] (C5-79):** the Shuffle-off preview by a loaded record, by the ledger without one, Play-next rows first and rows outside the record last, our own Shuffle on remembered at acceptance only, forgotten on `companion_shuffle:false` and a completed Shuffle off; end to end on the real adapter, §9.5.3's three histories (the equal case, a `move_next`, a reorder in another app, a queue the companion did not start) give preview = realised in session and after a restart |
| `test_cc5_windows_snap.py` | §5.7: assign on `snap_result(accepted)` only; move from the other side; same-side no-op; pre-check `hung` → `knob.meta.snap.hung`, pre-check `move_rejected` → `knob.meta.snap.move`; placement `move_rejected` / `cant_fit`; a missing `snap_result` after 1000 ms → `move_rejected`; advance at 420 to the **next** unassigned, open window after the snapped one, wrapping (A, B, C, D: snap C → D; snap D → A), unless turned; pair close at 820 with focus on the last side; latched Back/hold; U12 on back/hold/lock/sleep/idle but not disconnect/focus_lost/display; `toast.snap.one_side` only after `cancel_result(completed=true)` on `back`, never on `hold`; **[P3] (C5-78):** every `windows_cancel` carries its close `reason` (back, hold, lock, sleep, idle; also ~~a close~~ **[P3] (WP5R-2)** a Back or hold latched behind a snap), `windows_hide` closes carry none, and `restored=false` after a lock or sleep close sets no notice; **[P3] (WP5R-2):** lock, sleep and idle during a snap close at once (never latched, C5-12; K4 §15), with or without an accepted side, replace a latched Back, and the snap's late results change nothing |
| `test_cc5_start.py` | §8 starts: Recent (Home at once), explorer / Up next (380 ms); `Starting…`; Home 1 dim; `playing` omitted while `Starting…` and on the `started` frame (M16); `started` + colour; partial 33 of 34 status 3000 + toast; album blocked; failure; the staging deadline → `start_failed`; exclusive busy dims (§2.3) |
| `test_cc5_playnext.py` | controller side of §9.3: gates and refusal copy + toast; progress meta; ok meta 1500 + Sweep moment + toast; each failure outcome's copy/toast/LED; **rev 4 (C5-66):** a pre-resolved item shows `Queueing… 0 of {n}` at the press and makes no resolve call (**[r2.2]** `Finding songs…` until its first insert, C5-69); **[r2.2]:** the meta is `Finding songs…` while resolving and while `k == 0`, `Queueing… {k} of {n}` from `k = 1`, and `Queueing… 0 of {n}` never appears in any frame; `activity:"pending"` from the press to the result with no gap between the lookup and the first insert; a press while its pre-resolution runs joins it (one resolve in total); a press while it is only queued resolves on the library lane and drops the queued one |
| `test_cc5_preresolve.py` (rev 4) | §5.2.2 / §9.8.7 pre-resolution (C5-66): nothing before 400 ms of rest; then focus, the neighbour in the direction of travel, the other neighbour; cached, unavailable and > 100-track items skipped; one at a time on the lookahead lane and after a queued `recent_lookahead`; a focus change drops the stale queued ones (**[P2a]** at the detent, through `resolve_drop{keep}`: after a rest on item 5, a spin from 5 to 20 with no rest empties the queue and resolves nothing; the running one is never dropped; C5-75); the explorer's recent tab triggers it too; a spin across 96 items with no rest resolves nothing |
| `test_cc5_confirmation.py` | §8 table row by row: when `ok` is sent, its moment, no flash with a moment (VOC-R08) |
| `test_cc5_toasts.py` | §12: dropped while open, exit toasts at +360 or the result, replacement, catalogue, arming and dropping by close reason (incl. `hold`, `display`, `device`), balloons |
| `test_cc5_lifecycle.py` | §13: every close reason incl. `display` / `device` (presenter-initiated, no close effect emitted), parent modes, 60 s idle from knob input (incl. `lim`), `refused` busy / device, disconnect → Home on reconnect |
| `test_cc5_presenter_payloads.py` | §11: every presenter effect carries K4 §2.3's required fields plus `t0` from the injected clock; `control_min` = 0 in list modes; `upnext_rows` reasons exactly `data` / `likes` / `shuffle` / `queue_changed`; every §11.4 event enters through the one entry point `presenter_event` and reaches its handler (§2.5, VOC-R22); `system(motion)` updates `reducedMotion` in the next frame; no `display_off` handling |
| `test_cc5_runtime.py` | §10: lanes per op, progress channel ordering, invalidation list, `_note_library` for every Apple op, presenter events, per-mode art identity and accents (no-art items get the GEN accent; GEN index 7 and monochrome apps send 0, M26). **§1.1 scheduler** (with `FakeSpeaker` at 50 ms per call): during a 100-song Play next, a volume intent issued after insert 10 reaches `SetVolume` within **200 ms** of fake time and the job still ends `ok`; a Seek and a Play/Pause issued mid-job likewise; the state poll runs at most once per 2000 ms during the job; a queue-changing press stays dimmed; **rev 4 (C5-65):** a volume intent issued 1 s into a 2.65 s seek confirmation reaches `SetVolume` within one poll step (≤ 200 ms), and a second seek waits for the first to resolve; **[P3]:** `windows_cancel`'s `reason` reaches `cancel(origin, complete=, reason=)`, an adapter without it gets `cancel(origin, complete=)` or `cancel(origin)`, a payload without it passes `reason=None` (the picker's inference), and a lock close on the simulated picker restores nothing and raises no notice (C5-78); the record loaded at start reaches the controller as its base-row digests, a missing or malformed one as none (C5-79); the picker gets the overlay registry and the Motion setting at build and on every change |
| `test_cc5_settings_strip.py` (WP10) | §14: three columns × states, source phrases, actions, Motion effective value (incl. `system(motion)`) |
| `test_cc_sonos_v7.py` (WP6) | §9.1 source classes (every URI prefix in A06 §1.8), `can_seek` incl. D > 59 999; §9.2 staging: one full read before and after, per song the returned `FirstTrackNumberEnqueued` + one 1-row tail read, no per-song `_assert_group`, a wrong song id or total → rollback, `StartTimeout` → rollback + `start_failed`, `between_steps` called between inserts but not inside the destructive step; §9.3 insert positions incl. last row, verify, rollback guards, `partial`, song changed (now > P+N), cap 100; §9.4 clamp, confirm by polling, never resend, track change near the end; **rev 4 (C5-65):** a read in `TRANSITIONING` whose position equals the target never confirms; confirmation at the first non-`TRANSITIONING` read within ±2 s (2.65 s script → `ok` at ≈ 2.7 s); a read 3 s off after leaving `TRANSITIONING` keeps polling (**[r2.2]** now `ok`: landed = playback resumed, the offset only logged); no `TRANSITIONING` at all → confirmed only from 1.0 s after the reply; 5.0 s → `SeekNotConfirmed` with exactly one `Seek` call (**[r2.2]** 8.0 s, C5-68); `between_steps` called between polls and never inside a call; §9.5 plan realisation with the Play-next block first on **on**, `U_r` gate, verify incl. `playlist_position`, record persistence without the Play-next rows, restore with Play-next rows, foreign rows refused, **the track advancing mid-shuffle** (after move j: no row at or before the new playing row moves, the plan continues after it, verify passes) and a jump elsewhere mid-shuffle (`QueueChanged`, record kept); **[P2a] (C5-73)** shuffle off with `[song_id, start_row]` units: a Play next of a song the shuffle already played stays next, the base twin of a played Play-next row returns to its index, and a 160-seed random history run end to end (controller → runtime → adapter) realises exactly the controller's preview (**[P2a]** histories started by the companion with no base-row reorder; the §9.5.3 limitations 2–3 are pinned by `tests\test_kdocs_contract.py`); plain ids are still accepted (record first per signature, never wrong where the phase-1 rule was right); §9.6 `jump` / `move_next` guards; **[P2a] (C5-74)** `jump` by the landing rule: a 2.65 s `TRANSITIONING` script → `ok`; with no `TRANSITIONING`, `ok` only from 1.0 s after the reply; stopped, never resumed, resumed after 8 s or playing the wrong row → `start_failed` at 8 s with one `Seek`; the polls run as steps with the lock released; a group change while confirming → `group_changed`; `SetPlayMode` mapping; Previous under shuffle |
| `test_cc_apple_v7.py` (WP6) | `_send` (headers, 202 and 204 with empty bodies, `status`), like/unlike incl. 404s, ratings 200-empty/404, **rev 4 (C5-62…C5-64):** like = exactly `POST /v1/me/favorites` with the query `ids[songs]=<id>` and no body, then `GET /v1/me/ratings/songs?ids=<id>` read-backs every 250 ms until value 1 (fake clock), a read-back that never shows 1 → `failed` at 4000 ms; `UNLIKE_STRATEGY` default `"add_only"` (the adapter's `unlike` raises `UnlikeUnavailable`); ~~`"favorites_delete"` = exactly `DELETE /v1/me/favorites?ids[songs]=<id>` then read-back until no rating, 400 and 405 → `unlike_unsupported`, 404 with no rating → ok~~ (**[r2.2]** withdrawn: a recording session proves no `DELETE` of any kind is ever sent, C5-67); a recording session proves **no** request ever goes to `PUT` or `DELETE /v1/me/ratings/…` and no body carries `value: -1`; `catalog_songs` sends no `extend=inFavorites`; `catalog_songs` shape (incl. `textColor1` → `art_ink`) and missing ids, the resolve cache hit / join for pre-resolution, the favourites recipe (fast path accept/reject, full scan, ratings fallback, own-params paging, sort, `Untitled playlist`, 429 back-off), the Recently Added pager (`art_ink`), `resolve` with exactly `include=catalog&limit=100` on every page for albums and playlists, leniency, the 20 s deadline, the cache; `playlist_meta` mosaic skips albums without art |
| `test_cc_knob_art_v7.py` (WP6) | §10.5: scrim stops, the four knob art states at 240 px, content-hash keys |
| `test_cc_ledger.py` (WP6) | §9.7.3: base + Play-next attribution, multiset after shuffle, foreign detection, persistence per room |
| `test_cc5_simulation.py` | §16: every sim control reaches its state end to end through the controller |
| `test_kdocs_contract.py` (K-docs, **[P2a]**) | contract claims pinned to the code (the phase-2a K-docs review): Appendix A exactly, both ways (KD-R6); the §9.5.3 shuffle-off limitations 2–3 and the equal case (KD-R1; **[P3]** for a controller that does not know the record, C5-79); C5-77~~, pending WP5~~ (KD-R2; **[P3]** built, `PENDING_WP5` is empty); `group_changed` per op (§8, §9.10; KD-R3); both `seek_confirm_ms` rows and the adapter's 8 s `jump` window → `start_failed` (KD-R7) |

### 17.3 Live gates (00 §1.4; each with the user's go-ahead)

R1 queue census, R2 seek capability, **R3 native shuffle shape** (OQ-2) + Previous under shuffle (OQ-6), R4/R5 Apple read-only (incl. `meta.total` on recently-added, OQ-1; **R5 adds the exact §9.8.7 queries** `GET /v1/me/library/albums/{id}/tracks?include=catalog&limit=100` and `GET /v1/me/library/playlists/{id}/tracks?include=catalog&limit=100` with a second page by own params, C5-52), W1 Play next, W2 Seek, **[P2a]** W2b jump latency (§9.6.2), **W3 reorder** (OQ-5; per-call time and a 60-row reorder with position reads), W4 Like, **W5 playlist start latency, press → confirmed PLAYING** (resolve + staging + start, ≤ 3 s for 34 tracks; C5-49).

**Status after 2026-09-25 (rev 4):**
- **W1 Play next: done** (21:26 UTC, 2 songs at P+1/P+2 while PLAYING, 522 / 560 ms, exact rows, Sonos metadata on the new rows, rollback 12 ms; §9.3). Still open: CP §5 extras a–e.
- **W2 Seek: done while PLAYING** (21:23 UTC, +20 s and back: 2.64 / 2.69 s to leave `TRANSITIONING`, RelTime at the target from the first read; §9.4). Still open: the **paused** variant (CS §5 step 4), which the 1.0 s "never saw `TRANSITIONING`" rule covers until measured.
- **W4 Like: done with the favourites call** (22:06 UTC: `POST /v1/me/favorites` 202, rating 1 after ≈ 1 s, **the star appeared on the user's iPhone**; the earlier rating `PUT` at 21:27 UTC never did; §9.8.2).
- **[r2.2] W4b: done** (2026-09-25 16:03 PDT, with the user's approval, `work/probes/unfavorite_webplayer_once.py`): `DELETE /v1/me/favorites?ids[songs]=1000000001` → **HTTP 400, code 40012 "Insufficient Permissions"**, 333 ms, nothing changed (LS). `add_only` stays, and R22 CH §1 makes it final (C5-67). The rev 4 entry below is history.
- **W4b Unlike (new, needs the user's go-ahead): not run.** One `DELETE /v1/me/favorites?ids[songs]=<id>` on a song the user favourited for the test, then the user's iPhone check: **star gone** → the contract default becomes `favorites_delete` by an amendment (C5-63); **still starred, or 400/405** → `add_only` stays. The 23:01 UTC attempt was blocked by the session's permission system before any request (LS). The test song from 22:06 UTC is still starred on the iPhone and must be un-starred in the Music app (LS "Clean-up").
- **[P2a] W2b Jump latency (new, needs the user's go-ahead): not run.** No live check covers `jump` yet. With the queue playing, one Up next Play on a row a few rows ahead (`Seek(TRACK_NR)` + `Play`), logging the Seek reply time, the time the transport leaves `TRANSITIONING` and the first `PLAYING` read at the row (numbers only, no titles). Pass: lands well inside `seek_confirm_ms` 8000 (the W2 seeks took 2.64 / 2.69 s); the result sets how long Home shows `Starting…` after an Up next Play (§9.6.2, C5-74). The same check on a paused queue covers the Play-after-Seek path.
- **[2026-09-26] R3, W2 paused, W3, W5 probes (`work/probes/live_*_test.py`, not yet run live), after their review:** a Ctrl+C never leaves a change without a restore or an instruction. R3 (no `--restore` mode) stops and restores the play mode at once, holding Ctrl+C until that is done; W3 and W5 stop and restore at once, and a second Ctrl+C keeps the probe's files and prints the exact `--restore` command; W2 sends no further Seek and says where the song stands. W5 restores the position at which the start interrupted the song (the snapshot's position plus the time it played on until the start removed its rows; none when a staging rollback never interrupted it), and does not run while the companion holds a Shuffle-restore record for the room (a row re-created by song id changes its signature, §9.5.5). W3 counts a song that ended mid-reorder as restored as far as allowed (the playing row is never moved) and removes its files. Each probe's dry run simulates these cases offline.

---

## 18. Handoffs

| To | Item |
|---|---|
| K1 | **Closed** (consistency pass): §6.3 confirmed by K1 §12.5.5 (P5-R26; OQ-4); the Sonos card is `ring.card` (K1 §4.4, VOC-K1a) and a loading list is `style:"off"` + `activity:"loading"` (K1 §4.6, VOC-K1g), both used in §5.2.3, §5.3.4, §5.6.4 (C5-61); every `knob.status.*` addition fits 160 px and every K3 knob string is measured (K1 §8.6.11); the Seek field mapping of §5.5.6 is K1 §8.6.8; the Home label follows the icon (VOC-D08, K1 P5-12); `Queue changed` (OQ-2) and `Home, then Browse` (OQ-6) are in §15.2–§15.3. Done here earlier: Seek is offered only for D ≤ 59 999 s (K1 §4.3); `artDim` on unavailable items (K1 §8.6.5); the §10.5 knob art (K1 §8.4). |
| K2 | Adopted: M16 (`playing` omitted while `Starting…` and on the `started` frame, §5.1.2), M26 (GEN index 7 and monochrome apps send accent 0, §10.4) and M31 (loading lists vs unloaded entries, §5.2.3, §5.3.4, §5.6.4; C5-61). The M24 settings keys are in §14.4. Every moment in §8 is VOC §4.2; the `started` colour source is VOC §3.5. |
| K4 | The pushed payloads of §11.1 (K4 §2.3 fields + `t0`, legs anchored to `t0`); `upnext_rows` reasons (C5-54); events `snap_result(side, accepted)` at the pre-check and `cancel_result(restored, completed)`, `system(motion)` (§11.4); the explorer source switch enters at the controller's index and discards old-control positions (§5.3.3); snap advance to the next unassigned window after the snapped one (C5-46); no toast after a `hold` close (C5-36); the §9.7.3 context strings drawn as given; the §10.5 knob art row in K4 §13.1; session and foreground hooks (§13.1); toast placement and fitting; the stage input recipe (AR-4). |
| Rev 4 (2026-09-25 evening) | **K1:** no change needed. K1 states no seek confirmation time; its §4.3 already freezes the Seek clock at the target "while seeking and while `Jumping…`", which C5-65 now bounds at 5 s; its `lim` row (≤ 1 per 150 ms while ready, §11.1) is unchanged by K2's ruling Q1 (every push into a bound). **K2:** `ALIVE.md` revision 2 is authoritative (the draft merged, with the round-2 records C2, F1/W2, W1 and ruling Q1); K3's citations of `ALIVE_R2_DRAFT` sections still resolve (same numbers). **K4:** nothing required; the Like read-back delays the heart pop by ≈ 1 s (it already pops on the `likes` patch only). Optional, for the copy approval pass: under `add_only`, show `Liked` instead of `Unlike` in `overlay.upnext.hints` for a liked row (needs an `unlike_available` flag in the Up next payloads; not in this release unless the pass asks). **[r2.2] Now required and simpler:** the hint is `[3] Liked` on every liked row (R22 CH §1); no flag is needed, because add-only is final and `liked` alone decides it. **VOC:** absorbs C5-62…C5-66 (VOC §8.2, §8.3, §8.5, §2.6, §9.5, §10, §16). |
| **[r2.2]** (2026-09-25, late) | **K1:** the derived tone `liked` (filled `#A3244A` heart, mask `heartfill`; P5-R29), `unlike` a reserved moment (P5-R30), the approved widths (`Speaker group changed` 147.6, `Couldn’t open on screen` 149.1, `Unfavourite in Music app` 152.7, `Finding songs…` 94.7). **K2:** M32 (liked PINK 0.30, resting 0.04) and M33 (the pending spans this contract sends, §5.2.4, §5.5.6). **K4:** four row-heart looks (liked filled `#FF285A`; not liked outline 45 %; not known yet dashed 2.2 / 2.4 at 30 %; not in Apple Music outline 15 %), the hint `[3] Like` \| `Liked`, no unlike animation (K4 §8.2, §8.3, S5-34). **VOC:** VOC-R26…R29, tone `liked`, `like_fail_meta_ms`, `seek_confirm_ms` 8000, the approved copy (VOC §15 items 29–33). |
| **[P2a]** (2026-09-25, night) | **K1, K2, K4:** nothing required (no wire, LED or surface change; `resolve_drop` never leaves the host). **VOC** (absorbed in its revision 6, §15 item 35, §16): C5-73 (`shuffle_reorder` off takes units, VOC §8.2), C5-74 (`jump` landing rule, VOC §8.2), C5-75 (internal effect `resolve_drop`, VOC §7.4), C5-76 (`group_changed_ms` 2600, VOC §10). **WP6:** the `QueueLedger.playnext_units()` docstring says the adapter treats a unit with no start row as a bare id; the adapter (like `classify`) treats it as matching any row, which is what §9.5.3 records. **Test owner (WP5):** `test_cc5_grammar_oracle.py`'s `deviation()` allows a tag per case pattern and slot, not per kind of difference; two slots under its `VOC-R14` tag differ in the token, which §3.1 and C5-38 explain (Appendix A rows A1 and A3); **[P2a] review (KD-R6):** Appendix A is now pinned exactly by `tests\test_kdocs_contract.py`. **Live gates:** W2b (§17.3) |
| **[P2a] review** (2026-09-26) | **[P3] Done** (both WP5 items below, 2026-09-26: C5-77 as asked; the preview fix on the controller and runtime side alone, C5-79, see the [P3] row). **WP5 (required before the hardware window):** C5-77: when a start is sent (`_dispatch_start` and the Up next `jump` press), drop a waiting `_seek_bg` the way `_leave_seek(drop=True)` drops a target (`due` none, `dropped`, the target set back to the acked one, a queued job's target frozen); then remove `C5-77` from `PENDING_WP5` in `tests\test_kdocs_contract.py` and add the case to `test_cc5_tracks_seek.py`. **WP5 + WP6 (recommended; §9.5.3 limitation 3 is common):** preview the shuffle-off order from the record: the adapter reports the record's base-row order (signatures) with the Up next reads, and `_restore_order` ranks the base rows by it (the ledger's start order only when no record is reported); then §9.5.3, C5-73, VOC §8.2 and the pinned cases change together. **Test owner (WP5), optional:** fold the Appendix A pin into `test_cc5_grammar_oracle.py`. **K1, K2, K4:** nothing (no wire, LED or surface change) |
| **[P2b]** (2026-09-26) | **VOC (required):** §8.5's `group_changed` row and §10's `group_changed_ms` row still say `meta` tone; R-j makes it `error` (C5-76, §19 E-j). **K1:** 8.6.1 and 8.6.9 name the tone (K1 16.8 E-j); nothing else changes, the tone travels in `statusTone` / `metaTone`. **WP5:** `_group_changed_copy` sets the `error` tone and `test_kdocs_contract.py` asserts it (both already so in the tree on 2026-09-26). **K2, K4:** nothing |
| **[P3]** (2026-09-26, WP5-fixes) | **VOC:** absorb C5-78 in §16 (it adds `reason`, one of §7.3's close ids `back` \| `hold` \| `lock` \| `sleep` \| `idle`, to the `windows_cancel` payload; §7.4 lists the kinds only and K3 owns the payloads, so no other VOC text changes). C5-79 changes no wire. **K4:** §2.3 and §9.7 name `windows_cancel{origin, home, complete}`: add `reason`; the adapter's `cancel(origin, complete=None, reason=None)` already takes it, so `CAROUSEL.md` WP7b-D6's inference is now only the fallback for a payload without one (its text still says K3 carries none). **WP6:** nothing required: C5-79 uses `load_shuffle_record()` as it is (the runtime reads it once at start); the adapter reporting the record with its reads is no longer needed. **K1, K2:** nothing |
| **[P3b]** (2026-09-26, lead decisions) | **Done:** VOC absorbs C5-78 and C5-79 in §16 and states the C5-79 qualifier in §8.2 and the parse caps in §8.3 (its revision 8); K4 records the H5 result in §4.7.3; `CAROUSEL.md` WP7b-D6 names C5-78 (K-errata KE-R4). Nothing is handed on |
| VOC | **Absorbed** in the consistency pass (VOC §16): C5-4 and C5-59 (codes and the per-mode `ignored` check, VOC §2.6), C5-28 (`playlist_meta`, `play_items` rename, `recent_lookahead` effect, `group_changed` outcome), C5-29 and C5-56 (copy ids of §15.2–§15.3; the ones others name in VOC §9.5), C5-53 (presenter payload fields, `t0`, the events of §11.4, snap outcome `accepted`), C5-54 (`upnext_rows` reasons), C5-55 (close reasons `display`, `device`; `refused`), C5-57 (item art keys, VOC-K4-03), C5-60 (Home label). C5-7's `legend.*` is withdrawn (VOC-R24). |

---

## 19. Deviations, rulings and additions (C5)

| Id | Kind | Entry | Basis / reason |
|---|---|---|---|
| C5-1 | R | Browse starts a new visit at item 1; the explorer's Back restores its index | S03 entry "item 1"; U13; BS never resets `rIdx` on Browse (BS:954), which would point at the wrong album after new additions |
| C5-2 | R | Reconnect lands on Home | S03 state model "on reconnect read fresh state and go to Volume"; v6 resumed (`CT:513-523`) |
| C5-3 | R | **Revised (rev 3).** One queue-changing action at a time; busy dims `starting` / `queueing` / `shuffling` beyond S01:86-93, `ignored` only where the busy state is on screen, else answered with the busy line and the Head shake (C5-59) | the running job's guards would fail the second action (`SO:153-156`, `:312-325`) |
| C5-4 | A | Dim codes `transport_pending`, `signin_expired`, `list_error`, `shuffling`, `skip_unavailable`, `nothing_next`; wider scopes for `sonos_unavailable`, `loading`, `empty`, `starting`, `queueing` | states r2.1 leaves without a reason (VOC §2.6 is the base) |
| C5-5 | R | Reason copy 2000 ms in `meta` tone; failures `error` tone; Play next refusal 2000 ms (not BS's 2200) | S01:50 over BS:1007; VOC-R10 |
| C5-6 | R | One transient copy slot, drawn on the current screen's line, with per-mode precedence | BS `kmeta` / `kt()` (BS:775, :1286-1287) |
| C5-7 | A | **Revised (rev 3).** Wire labels ≤ 16 B (Home labels also ≤ 46 px, C5-60). The rev 1–2 `legend.*` desktop strings (BS `renderVals()` legends as a floating-knob tooltip) are **withdrawn** | `PR:72`; VOC-R24: the floating knob is click-through (`HTTRANSPARENT`, FK:47, :92-95; K4 §3) with no tooltip or text panel, and BS's `legend` (BS:1297, drawn at BS:341-349) is the prototype's key-hint panel, not a product surface |
| C5-8 | R | **Withdrawn (rev 2).** No host hold fallback or timer: the controller acts on each `kh`, including one the firmware deferred to just after `ready` (§4.2) | K1 §11.2 step 5 (P5-R10) latches a long press made while entering and sends it after `ready`, so rev 1's premise ("dropped by the firmware") was wrong; a host timer on the 25 ms Tk tick is the host timing VOC-D06 retired and could fire a false Home when a `ku` is handled after `tick()` in the same poll (A04 §6.1) |
| C5-9 | R | Turns ignored in the 190 / 200 / 380 ms windows; presses and hold ignored during the 380 ms Play window. The explorer's new source enters at the index the controller sends; positions from the old control id are discarded by the controller **and** the presenter (§5.3.3) | BS:922, :935 guard turns; presses are unguarded in BS (A01 §4.3), but a Back after a dispatched start has no meaning. Positions during the swap belong to the old source's bounds, so K4 §7.6's "entry uses the newest index" would apply a Recent position to Favourites (K4 to align) |
| C5-10 | **D** | A detent within 420 ms of a snap cancels the auto-advance | BS:1090 always advances; the re-entry would yank the knob from a position the user just chose |
| C5-11 | **D** | Snapping a window to the side it already holds is a no-op | BS re-flies and re-places it (BS:1078-1088); a second `SetWindowPos` gains nothing and costs the 360 ms cover |
| C5-12 | R | **Revised (rev 3).** Back / hold during an in-flight snap are latched until the snap resolves: **≤ 800 ms** (K4 §9.6's hard deadline `t0 + 800`, before the 820 ms pair close); the 1000 ms controller backstop (C5-53) stays as the last resort for a lost event. **[P3]** Lock, sleep and idle are never latched: they close the picker at once, also during a snap, and replace a latched Back or hold (§5.7.3; the phase-3 review item WP5R-2) | the window must move once, under cover (S01:403; R §7.1); rev 2's "≤ 760 ms" assumed a verify that could not block, which K4's posted-calls recipe and deadline now guarantee. **[P3]** A lock or sleep hides the screen, so there is no cover to keep, and K4 §15 makes those closes instant ("hidden in the same presenter wake"); the controller had latched them too, which no contract allowed |
| C5-13 | R | Entry frames keep the previous `artKey`; the new key follows the `ready` | 00 G2(2); OQ-4 |
| C5-14 | R | Passive re-entries wait 400 ms after the last detent (loaded-end exception) | 00 G2(3) |
| C5-15 | **D** | Seek's 3 s idle exit is deferred while a seek is sending or confirming, then re-armed | S01:203 would exit mid-`Jumping…`; the confirm takes up to **5 s** (rev 4, C5-65; live ≈ 2.7 s, LC W2), longer than BS's 0.6 / 1.8 s sim; **[r2.2]** up to **8 s** and across a follow-up jump (C5-68): the 3 s count starts when the last jump lands (R22 S01 §4b) |
| C5-16 | R | A seek result arriving after Seek was left: `err` only on failure | S01:204 assumes the user is still in Seek |
| C5-17 | **D** | Under Sonos native shuffle, Button 2 turns it off | BS:872 only shows `Sonos is shuffling` (a state-picker artefact), which would leave no way to turn Sonos shuffle off from the knob; S01:362 "Shuffle off" applies to both regimes |
| C5-18 | R | Confirmation timing per action (§8): Like/unlike (**[r2.2]** Like only) and native Shuffle on verified completion; companion Shuffle and Snap on acceptance (Snap: the presenter's `snap_result(side, "accepted")`, C5-53); Play next and starts on verified completion; Switch confirmed | VOC-D03 (owner K3); 00 U11 |
| C5-19 | R | Previous under Sonos native shuffle uses `avTransport.Previous` when offered | S01:147 designs `Prev: last played`; `SO:163-164` refuses today; OQ-6 |
| C5-20 | R | `play_items` restores the unshuffled play mode (repeat kept) before `Play`; the companion shuffle record is dropped | BS:997 starts unshuffled; 00 U4 sub-rule |
| C5-21 | R | Play next follows U6 (albums strict, playlists lenient), capped at the first 100 in order; success copy unchanged | U6; R §8 cap; OQ-3 |
| C5-22 | R | No automatic retry after `song_changed` | S01 §4c shows `Song changed · retry`; A06 §1.5 allowed one retry |
| C5-23 | R | Up next context comes from the ledger or is `Sonos queue`; no album heuristic for foreign queues | S01:337 over 00 §3.2 / A06 §6 heuristic |
| C5-24 | R | Ledger attribution by id multiset; one unattributable row → foreign | survives the companion shuffle's permutation |
| C5-25 | R | Tracks on non-queue sources: `Now: {title}` at every index; refusal copy `Previous unavailable` / `Next unavailable`; REPEAT_ALL first row shows the last row as `Prev:` | S01:142-149 covers only the queue; the wrap is what Previous does (`SO:173-174`) |
| C5-26 | R | Failures with an r2.1 toast never balloon; balloons only for failures without a toast, never over an overlay | S01 §8 toast rules; `ST:671-708` |
| C5-27 | R | Presenter input: `click_action` on the explorer's centre card / Up next's focus plate = Button 4; other clicks and the wheel are eaten by the stage; keys never reach the stage; only the **picker**'s wheel and arrow keys turn, and only without a knob session; no picker keys for Snap (the rev 1 `snap(side)` path is dropped) | CAR §9 deviation 5; `UI:1558-1565`; RF0 AR-4; K4 §3, S5-3, S5-23 (the stage eats the wheel and never has focus); K4 defines no Snap keys |
| C5-28 | A | Op `playlist_meta`; effect `play` → `play_items`; `recent` / `recent_lookahead` effects; progress channel; outcome `group_changed`; presenter payload fields `t0`, `bump`, `reason`, `close_at_ms`, `place_at_ms` (the full payload set is C5-53) | VOC §7.4 is 1:1 with ops; these fill gaps |
| C5-29 | A | Copy ids of §15.2 (retained) and §15.3 (new, approval pass; **[r2.2]** approved, C5-70) | VOC §9.4 audit; 00 G13 |
| C5-30 | R | Favourites sorted client-side, unnamed last as `Untitled playlist`, focus remembered by playlist id | CF §2 ("not strictly alphabetical"), CF §5 |
| C5-31 | R | Recently Added pages of 25; ≥ 16 loaded ahead; total from `meta.total`, else open-ended | S01:267; LC:16; OQ-1 |
| C5-32 | R | Controller timings unchanged under reduced motion | S01 §10 changes drawing only |
| C5-33 | R | **Revised (rev 2).** Overlays open whatever the notification state; only toasts are dropped when `SHQueryUserNotificationState` is 3 or 4 (§13.3) | aligned with K4 S5-17 / §17.3 (user-initiated overlays; r2.1 designs no refusal); 00 G9's refusal is not adopted |
| C5-34 | R | Home status precedence | BS:1287 |
| C5-35 | R | Up next Play on the now-playing row restarts it | BS:884-888 (`pos: 0`) |
| C5-36 | R | **Revised (rev 2).** Exit toasts (the sign-in toast, `toast.snap.one_side`) follow only `back` closes; a `hold` close raises **no** toast; the U12 completion still applies on `hold` | VOC §7.3 (`hold`: no toast); BS:867 and BS:1061 (Back only); BS:893-898 `goHome` flashes nothing; S01:426 (other closes have no toast). K4 §9.7's one-side toast after a hold defers to this (K3 owns toasts) |
| C5-37 | R | **Revised (rev 2).** No controller-side watchdog; job deadlines instead: `resolve` 20 s in total; `play_items` staging `6 + 0.15·N` s, ending in the existing staging rollback → `start_failed`; none after the destructive step begins | rev 1 relied on per-call timeouts, which bound a start only by N × (8 s Apple + 5 s Sonos) and left Home 1 dimmed without limit; the rollback path (`SO:436-455`) already exists; the destructive step cannot be rolled back, so it runs to its result (each call ≤ 5 s, `SO:74`) |
| C5-38 | R | Source class: STOPPED → `none`; other `x-sonos-vli:` → `radio`; TRANSITIONING keeps the last class | VOC §8.1 catch-all; avoids flapping dims |
| C5-39 | A | Settings: Motion control, Apple `Not signed in` state, the behaviour of `Knob settings…` / `Troubleshoot…` / `Set manual IP…` / `Sign in…` | S01 §12 names the actions without behaviour; VOC-R09 |
| C5-40 | R | **Superseded by C5-64 (rev 4).** Was: heart state from the catalog batch's `inFavorites` (schema-checked), ratings as fallback | LC shows `catalog_inFavorites` true within 2 s; one request serves art and hearts (CL §4.1). Rev 4: `inFavorites` lags the rating by ≈ 2 s after a favourites `POST` (LS), which a read-back-confirmed heart cannot tolerate |
| C5-41 | R | Shuffle on with fewer than 2 upcoming rows **outside the Play-next block** (`U_r < 2`, companion regime) is ignored (`nothing_next`) | A06 §3.4 gate, applied to the rows that move (C5-45); 03 §3.7 |
| C5-42 | R | Favourites load errors: cache kept; without a cache the tab shows the loading state while CF's retries run | CF §5 error handling; avoids undesigned error copy |
| C5-43 | R | Queue rows whose song id the storefront catalog does not return are non-catalog | LC: 1000000002 "0 of 1 found" |
| C5-44 | R | **Revised (rev 4).** `unlike` (`favorites_delete` only) treats a 404 as ok **when the read-back shows no rating**. **[r2.2] Withdrawn** with the `unlike` op (C5-67) | the end state (no rating) is what was asked; with the favourites `DELETE` a 404 alone does not prove the favourite is gone |
| C5-45 | R | The companion shuffle keeps the Play-next block (the upcoming rows the ledger attributes to Play next) directly after the current song on **on** as well as off: the plan puts them first in their current order and permutes only the other `U_r` rows; the `U ≥ 2` gate applies to `U_r`; the regime threshold stays `U ≤ 60` over all upcoming rows; the restore record holds only the base rows. Under the Sonos regime (`U > 60`) the block cannot be kept | R:142 "A Play next block stays after the current song" is not limited to off; BS:873-878 builds `head + pn + rest` on both edges, shuffling `rest` when turning on and sorting it when turning off; S01:362 repeats it for off. The threshold follows S01:357-360's "upcoming rows". Sonos native shuffle orders every upcoming row itself (A06 §3.2); the card copy says the order isn't shown |
| C5-46 | R | After a one-side snap the highlight advances to the **next** window after the snapped one in list order, wrapping, skipping assigned and closed windows (not BS's first unassigned in list order) | S01:405 "advances to the next unassigned window" outranks BS:1090's `findIndex` from 0 (§0.2); with A, B, C, D, snapping C gives D (BS: A). The highlight also moves forward from where the user is instead of jumping back to the head of the list. Skipping closed windows is added: a closed window can only be refused (`closed`). K4 §9.5 t = 420 to mirror |
| C5-47 | **D** | Seek exits the user did not make (a song change, a group change, a disconnect) **drop** a pending target instead of sending it | S01:203 and R §8 say a pending target is sent on exit and that a song change exits Seek. The target was computed against the old song's duration and track id, so sending it would seek the new song (the adapter's track guard would refuse it anyway, §9.4); "sent on exit" is kept for every exit the user makes (Button 1/2/3, hold) |
| C5-48 | R | Audio-lane step scheduler: long queue jobs yield between steps (≤ 3 SOAP calls each) to queued short jobs (`state`, `volume`, `transport`, `seek`, `queue_window`); the state poll runs at most every 2000 ms during a job; our own revision changes wait for the job's completion (§1.1) | rev 1 said volume, Seek and Play/Pause "stay available" while they queued behind jobs of seconds on one worker holding one lock (`SO:90`, `:367`), with the poll suspended. One thread keeps Sonos I/O serialized (CS §3) and avoids two threads on one `SoCo` object; a RenderingControl lane was rejected (it would not free Seek or Play/Pause) |
| C5-49 | R | `play_items` staging per 00 G3: one full queue read before staging and one after, per song the returned `FirstTrackNumberEnqueued` plus one 1-row tail read, no per-song `_assert_group`; the W5 gate covers press → confirmed PLAYING (resolve + stage + start); W5 fallback: one tail read for the whole block | today's loop costs a zone-group read and two full paged reads per song (`SO:386-399`), ≥ 136 SOAP calls for 34 songs, growing with the queue (00 G3); the ≤ 3 s gate could not be met. A06 §1.5 already rejects copying it for Play next |
| C5-50 | R | The companion shuffle and its restore read the playing row before every move, never move a row at or before it, and re-plan after it when a song ends mid-reorder; a jump elsewhere stops the job (`queue_changed`, record kept); verification includes `playlist_position` | rev 1 checked the track once (step 1) and assumed P fixed for seconds (A06 §3.4); a song ending mid-reorder would put moved rows behind the playhead, where they never play, while verification still passed. Costs one extra call per move (3 per move, OQ-5) |
| C5-51 | R | Seek is offered only for `D ≤ 59 999 s` (else Tracks 3 dims `no_length`) | K1 §4.3 `LAP_COUNT_MAX` (P5-R11): a longer `lap` would be rejected by both parsers, and a rejection is fatal on the host (P4 §7); the `no_length` copy is the closest existing reason |
| C5-52 | R | `resolve` sends `include=catalog&limit=100` on every page for albums and playlists (own-params pager); `limit=300` is not used; R5 adds the exact queries | `limit=100` is the only value verified live (CF §2 rows 1–3, 17); today's code sends none (`AM:368`); an unverified `limit=300` rejected by Apple would fail every album start and album Play next |
| C5-53 | A | One presenter interface with K4: effects pushed with K4 §2.3's required fields plus `t0` (QPC, the controller's injected `time.perf_counter`), legs anchored to `t0`; the controller consumes K4's events, adding `snap_result(side, "accepted")` at the pre-check and `cancel_result(restored, completed)`; outcome names are VOC §8.5's; a missing `snap_result` counts as `move_rejected` after 1000 ms; `system(kind)` per K4 (`lock`, `sleep` incl. display off, `display`, plus `motion`); no `display_off` kind | rev 1 had pull view models, synchronous `windows_snap` / `windows_cancel` results and `session_event(display_off)`, none of which K4 provides (K4 §2.3: every call posts and returns); without `accepted`, the snap half-wash could only follow the verified placement (≈ 0.5 s late); without `t0` the scene's +190/+200/+380 legs and the knob re-entry drift apart |
| C5-54 | A | `upnext_rows` reasons `data` (fills, initial heart states, no pop), `likes` (a confirmed like **or** unlike, `[{row, liked}]`; **[r2.2]** a like only), `shuffle` (the new order; K4 schedules +200 from `t0`), `queue_changed` | K4 §2.3 / §8.3 / §8.5's enum; rev 1's `loaded` / `shuffle_out` / `shuffle_in` / `like` and its missing unlike patch would have broken the heart and the shuffle re-entry |
| C5-55 | A | Close reasons `display` and `device` (VOC-K4-01) handled as presenter-initiated closes (parent mode, no toast, no U12); `refused(surface, busy \| device)` → Head shake, `knob.meta.stage_unavailable`, back to the parent mode (§13.5) | K4 §4.1-§4.3, §15; the controller enters `explorer` / `upnext` at the press, so a refusal otherwise left the knob in an overlay mode with nothing on screen |
| C5-56 | A | Copy ids that match their line: `knob.meta.library_error`, `knob.meta.signin_expired`, `knob.status.sonos_unavailable`, `knob.meta.group_changed` (texts unchanged) | VOC §9.1 id grammar `<surface>.<context>`: rev 1 drew `knob.title.library_error` in `meta`, `knob.meta.sonos_unavailable` in Home `status`, `knob.meta.like.signin_expired` for list failures and `knob.status.group_changed` on `meta` lines |
| C5-57 | A | Item and row art keys per K4 §13.2 (VOC-K4-03): `art_template`, `art_max`, `art_bg`, **`art_ink`** (`textColor1`), **`sonos_art`** (renamed from `art_url`), `mosaic` from the first 4 distinct albums **with art** | K4 §13.2, §13.6, S5-12 (11 of the user's playlists have no art, LC:16) |
| C5-58 | R | WP6 `artwork.py` composites every knob cover with the r2.1 scrim (.60 / .72 / .92 / 1.0) and renders the 240 px `art.loading` (flat `art_bg`), `art.generated` (GEN gradient) and `art.extended` knob covers, without text (§10.5) | K1 §8.4 requires it of WP6; 00 §4.2 assigns `artwork.py` to WP6; rev 1 listed no owner (K4 §13.1 now points its knob row here) |
| C5-59 | **D** (= VOC-D07, per mode) | A dim code is `ignored` (Press moment only) **only in a mode where its state is on screen**: `starting` on Home 1; `queueing` in Recent; `shuffling` in Up next; `transport_pending` on Home 1 and on Tracks 4 during its own skip; `nothing_next` when `U < 2`; `loading`, `empty` everywhere. Elsewhere the press gets reason copy on the `meta` line and `feedback{kind:"err"}`: `knob.meta.busy.starting` / `.pausing` / `.shuffling`, the running Play next's `knob.meta.playnext.progress` (or `.resolving`), `knob.meta.shuffle.nothing` (§3.2) | R:76 and the acceptance line R:182 ask for a reason and a Head shake on every dimmed press; VOC-D07 allows "ignored" only where r2.1 has no copy **and** the state is visible (VOC §2.6). K3's busy dims reach modes where their busy line and comet are not drawn (a start's `Starting…` shows only on Home; Play next's `Queueing…` (**[r2.2]** `Finding songs…` / `Queueing… {k} of {n}`) only in Recent; the shuffle comet only in Up next), where a silent ignore would read as a broken button. Reusing the busy lines as the reasons adds only four short strings to the approval pass |
| C5-60 | **D** (= VOC-D08) | The Home slot-0 label follows its icon: `Pause` with `pause`, else `Play` (so the idle row reads `Play`) | r2.1's idle-row word `Play/Pause` (S03:15 override #16) is 67.4 px against the 46 px column (S03:134): it overlaps `Browse` and crosses the safe circle (K1 §8.6.3, P5-12); BS's own Home 1 legend is `Pause` / `Play` (BS:1247); in the copy approval pass (**[r2.2]** approved, R22 CH §2) |
| C5-61 | R | Ring wire forms (K1 §4.4, §4.6; K2 M31, 5.1.4): a **whole list loading** (first Recently Added page, favourites without a cache, Up next before its first window) is `ring.style:"off"` + `activity:"loading"`; an **unloaded entry of a known list** (a spin past the prefetch, an Up next placeholder) is a `selection` entry with colour 0 and the list's own `activity`, never `loading`; the **Sonos card** is `card:true`, `count = P + 1`, `now = P − 1`, colour 0; **Up next frames never set `unavailable`** | with `loading` on one missing entry the whole ring blanks and the knob's local cursor freezes (K2 5.1.3 case 1, 6.3), the opposite of S01:267 "a fast spin shows loading tiles, never blank cards"; the card has one wire form (K1 P5-R24), and Up next rows have no unavailable state (BS:1318-1321) |
| C5-62 | R (rev 4) | **Like = `POST /v1/me/favorites?ids[songs]=<id>`** (no body, 202), confirmed by reading back rating 1 (`ratings`, every 250 ms, ≤ 4 s), with the Working comet meanwhile; a timed-out read-back is `failed` plus one late check after 5 s. Never `PUT /v1/me/ratings` | LS / LC 2026-09-25: the rating `PUT` (21:27 UTC) set the server but never showed on the user's iPhone, even after ≈ 30 min and a restart; the favourites `POST` (22:06 UTC) stored the same values and the star appeared. 202 means accepted, not done (LS), so the heart waits for the read-back |
| C5-63 | R (rev 4; **[r2.2] superseded by C5-67**) | **Unlike behind `UNLIKE_STRATEGY ∈ {"favorites_delete", "add_only"}`, default `"add_only"`** until live check W4b passes. `add_only`: a press on a liked row is refused at the press (`unlike_unavailable`, `Unfavourite in Music`, Head shake), no request, the heart stays PINK (not a dim, §3.2). `favorites_delete`: `DELETE /v1/me/favorites?ids[songs]=<id>` + read-back of no rating; 400/405 → `unlike_unsupported`, which switches the session to `add_only`. Never `DELETE /v1/me/ratings` | LS 22:42–23:01 UTC: the rating `DELETE` cleared the server but the iPhone kept the star, so the companion's heart and the user's devices would disagree; the web player's favourites `DELETE` was not sent (the session's permission system blocked it; no result recorded) and public code reports both 204 and 400 "Insufficient Permissions" for it. The default flips only by a contract amendment after W4b |
| C5-64 | R (rev 4) | **The heart state has one source: `GET /v1/me/ratings/songs?ids=` (value 1 = liked)**, for Up next rows, like/unlike read-backs (**[r2.2]** like only, C5-67) and the late check; `catalog_songs` drops `extend=inFavorites`. Supersedes C5-40 | the rating is the one field behind the star and Favorite Songs (the Music app's Unfavorite deletes it; the favourites `POST` sets it; LC 21:22 UTC, LS); it is readable ≈ 1 s after a `POST` against ≈ 3 s for `inFavorites`; one source cannot flip a just-confirmed heart back in a `data` patch. Cost: one GET per 21-row window |
| C5-65 | R (rev 4; **[r2.2] amended by C5-68**: the position is no longer a condition, 8 s) | **Seek confirmation = the transport has left `TRANSITIONING` and the position reads within ±2 s of the target**, within **5 s** (`seek_confirm_ms`, was 3 s); a speaker that never reports `TRANSITIONING` confirms from 1.0 s after the reply; never resent; the knob clock stays frozen at the target with `Jumping…` until then; the confirmation polls yield to short jobs on the audio lane (§1.1) | LC W2 (21:23 UTC, PLAYING, 2 seeks): RelTime read the target from the first poll (≈ 0.5 s) while the speaker was still `TRANSITIONING` and near silent; it left `TRANSITIONING` at 2.64 / 2.69 s, so the 3 s window had ≈ 0.3 s to spare and a position-only rule would confirm ≈ 2 s early |
| C5-66 | R (rev 4) | **Pre-resolution**: 400 ms after the last detent on a loaded Recently Added item (knob or explorer recent tab), resolve the focused item, then its neighbours (direction of travel first) on the lookahead lane, lowest priority, one at a time, into the resolve cache; Play next (and every start) reads the cache first and joins a running pre-resolution, so it starts inserting at once; `Queueing… {k} of {n}` unchanged (**[r2.2]** preceded by `Finding songs…`, C5-69). Replaces the optional 800 ms warm-up | LC W1 (21:26 UTC): inserts at P+1+i land exactly while playing at 522 / 560 ms each; an uncached 8-track album resolves in 3.07 / 3.52 / 6.25 s, which would otherwise precede every Play next, with the knob on `Queueing…` before the first insert |
| **C5-67** | R (**[r2.2]**) | **Like is add-only, final.** `UNLIKE_STRATEGY = "add_only"` with no alternative: no `unlike` effect, op, read-back, outcome (`unlike_unsupported`) or moment is ever produced; `knob.meta.like.off` is never drawn; no heart-off animation. A liked row: Button 3 `heart`, **enabled**, `lit:"on"` (the knob draws tone `liked`: PINK 0.30, filled `#A3244A` heart); label `Liked`; hint `[3] Liked`; a press → `unlike_unavailable`: Head shake + `Unfavourite in Music app` for `like_fail_meta_ms` 2200, no request. Save failure → `Didn’t save · try again` (error) for 2200 ms + Head shake. Supersedes C5-63 and C5-44 | R22 CH §1 (**[r2.2]** "Proposal confirmed…", "Removed: the unlike moment…"); LS (`like-star-mismatch.md`): "Conclusion for the build (UNLIKE_STRATEGY = add_only)", and the favourites `DELETE` → 400 / 40012 (2026-09-25 16:03 PDT); VOC-R26 |
| **C5-68** | R (**[r2.2]**) | **Seek lands when playback resumes**: the adapter returns on the first PLAYING / PAUSED_PLAYBACK read after `TRANSITIONING` (or ≥ 1.0 s after the reply when none was seen); the position is logged, not checked; `seek_confirm_ms` = **8000** → `not_confirmed`. The knob holds the frozen target, `Jumping…` and `activity:"pending"` for the whole span (`seek_busy`); a turn during a jump moves the target, and at most **one** follow-up jump (the latest target, after the 250 ms debounce) is sent when the current one lands. Amends C5-65 and C5-15 | R22 CH §3; R22 S01 §4b; R22 BS:843-844, :936; VOC-R27 |
| **C5-69** | R (**[r2.2]**) | **Play next meta:** `knob.meta.playnext.resolving` = `Finding songs…` while resolving or `k == 0`; `Queueing… {k} of {n}` for `k ≥ 1` (≈ 0.5 s per song); `Queueing… 0 of {n}` never shown; `activity:"pending"` for the whole job. Timings recorded: prototype cached lookup 0.4 s, uncached 4.5 s; live uncached 3.07–6.25 s, inserts 522 / 560 ms | R22 CH §4; R22 S01 §4c; R22 BS:1015, :1275; VOC-R28 |
| **C5-70** | A (**[r2.2]**) | **Copy approved** (R22 CH §2): every §15.3 row as listed; rewritten `Speaker group changed` (`knob.status.group_changed`, `knob.meta.group_changed`; 147.6 px ≤ 160) and `Couldn’t open on screen` (`knob.meta.stage_unavailable`, 149.1 px); `Unfavourite in Music app` (152.7 px); `Finding songs…` (94.7 px); `toast.start.partial` `… · {u} songs unavailable` / `1 song`. Closes the C5-29 approval pass | R22 CH §2; VOC-R29; K1 §8.6.11 widths |
| **C5-71** | R (**[r2.2]**) | **`Finding songs…` holds until song 1's insert is confirmed** (confirmed design point): the meta is `knob.meta.playnext.resolving` while resolving or `k == 0`, with `k` = verified inserts (§5.2.4), so `Queueing… 1 of {n}` first appears when the first insert is verified. Matches R22 CH §4 ("before k counts up"); the prototype switches at the end of the lookup (R22 BS:1015: `k = 1` right after the 0.4 / 4.5 s lookup, while song 1 is still being inserted), so the knob shows `Finding songs…` about one insert (≈ 0.5 s) longer. Refines C5-69 | R22 CH §4; R22 BS:1015, :1275; VOC-R30 |
| **C5-72** | R (**[r2.2]**) | **The liked Button 3 is enabled-with-refusal** (confirmed design point): R22 CH §1 says the button "dims" to PINK 0.30; K3 sends `heart`, **enabled**, `lit:"on"` (K1 tone `liked`) and refuses the press itself (`unlike_unavailable`: Head shake + `Unfavourite in Music app` for `like_fail_meta_ms` 2200, no request), the same visible and audible result as a "not available" press; a `dim` state would draw WARM 0.14 with the `#5A5A5A` outline and read as broken. Refines C5-67 | R22 CH §1; R22 BS:827 (a press → `knobMeta(…, 2200)` + `fail`), :1268 (drawn `'on'`); VOC-R31; VOC §2.3 row 4 |
| **C5-73** | R (**[P2a]**) | **Shuffle off takes the ledger's Play-next units.** `shuffle_reorder(off)`'s `playnext_song_ids` carries `QueueLedger.playnext_units()`: one `[song_id, start_row]` per Play-next song, newest block first (`start_row` null or 0 = any row); plain ids stay accepted. The adapter attributes the upcoming rows in two passes: pass 1 gives units by the ledger's position rule (a row at or below the unit's `start_row`, the latest first; a played row marks its unit played); pass 2 attributes the rest record first per signature (the later identical rows are base rows, the earlier ones Play-next rows that take a free unit, else foreign). The ledger's `classify` uses the same position rule, so ~~the restore equals the controller's preview~~ **[P2a]** the adapter puts first the same Play-next rows as the controller's preview; the base rows follow in the record's order (their order at Shuffle on), which the preview (the ledger's start order) matches only when they still stood in it: not after a reorder without a ledger entry (a `move_next` of an upcoming row, another Sonos app) and not on a queue the companion did not start (§9.5.3 limitations 2–3) (§9.5.3, §9.7.3). **[P3]** That preview order is only the fallback when the controller does not know the record; with the record known the preview ranks the base rows by the record's order, which is the order the adapter restores (C5-79) | phase-2a review WP6R22-1 (build WP6-A1): with plain ids, a Play next of a song the shuffle had already played has the signature of that played base row, which the record still holds, so shuffle off sorted it back to the base row's index while the preview kept it next. Units fix it end to end (a 160-seed randomized test, controller → runtime → adapter). Limitation kept: the preview sees only loaded rows (a played Play-next row ≈ 10+ rows above the playing row); the re-read after the job corrects the list. **[P2a]** Limitations 2–3 found by the phase-2a K-docs review (KD-R1; headless probes on the fakes); ~~fix handed to WP5 and WP6 (§18)~~ **[P3]** fixed on the controller/runtime side (C5-79); the ledger's start order is only the fallback when the controller does not know the record |
| **C5-74** | R (**[P2a]**) | **`jump` lands by the Seek rule**: after `Seek(TRACK_NR, row)` (+ `Play` if not PLAYING), played = the first `PLAYING` read at `row` after `TRANSITIONING`, or ≥ 1.0 s after the reply when none was seen, within `seek_confirm_ms` 8000, else `start_failed`; 100 ms polls, each its own audio-lane step with `between_steps()` between them (so `jump` leaves §1.1's one-step list; **[P2a]** no `seek` runs between them, C5-77); group checked every 0.5 s and before the result; never resent. Replaces "PLAYING at `row` within 2 s" | live W2 (LC): a seek stays `TRANSITIONING` 2.64 / 2.69 s, and a jump buffers a new stream the same way, so a 2 s window fails jumps that are about to play; an 8 s job holding the lane would stall volume and Play/Pause, hence the steps. R22 CH §3 / C5-68 is the same "landed = playback resumed" rule. The live jump latency is still to be measured (§17.3 W2b) |
| **C5-75** | A (**[P2a]**) | **Internal effect `resolve_drop{keep}`** (controller → runtime only): at every detent on Recently Added that leaves a sent pre-resolution outside the new focus ± 1, `keep` = the new focus and its loaded neighbours; the runtime prunes the lookahead lane's queued pre-resolutions to `keep` (the running one finishes into the cache). Never posted to a presenter, never on the wire, no result; not a service op (VOC §7.4) | phase-2a review WP5-R8: the drop happened only at the next 400 ms rest, so during a spin stale neighbours kept running (≈ 9–10 Apple GETs each) and delayed the new focus's pre-resolution by 3–6 s, while §5.2.2 and §9.8.7 tie the drop to the focus change; an empty `resolve` batch cannot carry it (the runtime dispatches only non-empty batches) |
| **C5-76** | R (**[P2a]**) | **`Speaker group changed` shows for `group_changed_ms` = 2600** in ~~`meta`~~ **[P2b]** `error` tone (lead ruling R-j, 2026-09-26; KD-4) on the current line (Home `status`, else `meta`), for a group change seen in a state poll or result (copy only, no `err`) and for a start or volume write that fails with `group_changed` (with `err`); a volume write to the old group finishes quietly; a Play next failure keeps its own rule (§9.3: error tone, 2400 ms); **[P2a]** a start shows no `start_failed` copy and no toast, and a seek, shuffle or transport failure shows its own failure first (`Didn’t jump · try again` / `Didn’t shuffle · try again` / the desktop notice), the copy following from the next state poll (review KD-R3) (§7, §8, §9.10) | the design gives the copy (R22 S01 App C, "Knob meta · Sonos group changed during an action" and "Knob status · Home · group changed") but no duration; 2600 ms is the Home status failure duration (`start_fail_status_ms`, BS:993) and the length of a `Changed on Sonos` reveal (`external_reveal_ms`); build deviation WP5-D12 |
| **C5-77** | R (**[P2a]**, review KD-R2) | **A start drops a Seek follow-up that is still waiting.** When a start is sent (`play_items` from Recent or the explorer, the Up next `jump`) while a Seek follow-up target waits for the in-flight jump to land (kept across an explicit exit, §5.5.5, C5-68), the target is dropped as a track change drops it (C5-47): never sent; the in-flight jump still resolves first (a failure still gives `err`, C5-16). So no `seek` is ever queued behind a start, and a start's `between_steps()` (the `jump`'s confirmation polls, `play_items`' staging steps) never runs one (§1.1, §2.3, §5.5.5, §9.6.2) | phase-2a K-docs review KD-R2: §1.1 said a new Seek cannot be queued behind a jump (`starting` dims it), but the follow-up kept across an explicit exit is sent by the controller's tick without looking at the pending start, and the audio lane skips a `seek` only inside another seek. So Seek → turn → Button 2 → Up next Play within ≈ 2.7 s ran the follow-up inside the jump: during `TRANSITIONING` → `SeekUnavailable` → `not_confirmed` → a Head shake over `Starting…`; after it, a seek of the restarted track back to the old target, whose ≤ 8 s confirmation (one jump step) could use up the jump's window (`start_failed` while playing). The start is the newer intent and replaces or restarts the track. Controller change handed to WP5 (§18); pinned by `tests\test_kdocs_contract.py` (skipped with the handoff reason until it lands). **[P3] Built** (`Controller._drop_seek_follow_up`; the pins run, `PENDING_WP5` is empty) |
| **C5-78** | A (**[P3]**; phase-2b review item R8) | **`windows_cancel` carries the close `reason`** (`back` \| `hold` \| `lock` \| `sleep` \| `idle`, VOC §7.3); the runtime passes it as `cancel(origin, complete=, reason=)` with only the keywords the adapter takes; a `cancel_result(restored=false)` after `lock` or `sleep` sets no desktop notice (§5.7.4, §9.9, §11) | the picker had to infer the reason (WP7b-D6: its own lock/sleep detection, else `idle` after 59.5 s without knob input, else `back`), although the controller latched it in `_cancel_pending`; K4 §15 needs it (instant hide for lock/sleep/idle, no focus restore for lock/sleep), and a lock close then showed `Original window no longer available`. The inference stays as the picker's fallback for a payload without one |
| **C5-79** | R (**[P3]**; the phase-2a review's recommended fix, KD-R1) | **The Shuffle-off preview ranks the base rows by the restore record when the controller knows it** (its own accepted companion Shuffle on, or the record the runtime loads at start), per signature in queue order as the adapter attributes them; by the ledger's start order only when it does not; forgotten on `companion_shuffle:false` or a completed Shuffle off (§5.6.5, §9.5.3) | §9.5.3 limitations 2 and 3 (common on a queue the companion did not start) made the preview differ from the realised order, with a second re-entry after the job. The record's order is exactly the order the adapter restores, and `load_shuffle_record()` already returns it, so no adapter or wire change is needed (the WP6 half of the handoff is dropped) |

Inherited from VOC and applied here: VOC-D01 (never `SW_RESTORE`; r2.1 README §8 still says it), VOC-D03 (moments on host feedback), VOC-D06 (firmware hold), VOC-D07 (ignored dims, per mode: C5-59), VOC-D08 (Home label: C5-60), VOC-R07 (`started`), VOC-R09 (`reducedMotion`), VOC-R14 (additions), VOC-R15 (U12 closes), VOC-R19 (favourites empty in `title`), VOC-R22 (one presenter-event entry point, §2.5), VOC-R23 (the knob after a `disconnect`, §13.1), VOC-R24 (no desktop legends, C5-7), VOC-R25 (`t0` on one QPC clock), **[r2.2]** VOC-R26 (Like add-only, C5-67), VOC-R27 (Seek landing, C5-68), VOC-R28 (`Finding songs…`, C5-69), VOC-R29 (copy approved, C5-70), VOC-R30 (`Finding songs…` until song 1's insert is confirmed, C5-71), VOC-R31 (liked Button 3 enabled-with-refusal, C5-72); from K2 **[r2.2]** M33 (the pending spans, §5.2.4, §5.5.6). From K2 (`ALIVE.md` revision 2 §10.2, formerly ALIVE_R2_DRAFT): M16 (`playing` omission, §5.1.2) and M26 (accent 0 for GEN index 7 and monochrome apps, §10.4). From K4: VOC-K4-01 (C5-55), VOC-K4-02 (C5-55, §15.3), VOC-K4-03 (C5-57), S5-17 (C5-33).

**[P2b] Errata and accepted deviations of the phase-2b gate (lead rulings, 2026-09-26)**

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| E-j | **R-j** (KD-4) | C5-76: `Speaker group changed` in the neutral `meta` tone, as the controller showed it, also after a failed start or volume write; the phase-2a K-docs build left the choice to the lead (KD-4), since §2.4 gives failure copy the error tone | the **`error`** tone (`#FF8474`, VOC-R10) wherever it shows: Home `status` and every `meta` line, from a failed start or volume write and from a state poll alike. The duration (`group_changed_ms` 2600), the `err` rules per op (§9.10) and the precedence (§2.4) are unchanged; a Play next failure keeps §9.3's rule (already `error`) | §2.4, §7, §8 (Start row), §9.10, C5-76; K1 8.6.1, 8.6.9 (K1 16.8 E-j); `controller.py` `_group_changed_copy`; `tests\test_kdocs_contract.py` `GroupChangedPerOpTests` |
| E-l1 | **R-l** (KD-1) | the four phase-2a changes were numbered C5-73…C5-76, though no ids were asked for | **accepted**: they keep C5-73…C5-76 (the way VOC absorbs K3 changes, VOC §16) | §19 |
| E-l2 | **R-l** (KD-2) | §9.7.3 was changed beyond the listed §9.5.3 | **accepted**: §9.7.3's position rule, `playnext_units()` and the segment's `start_row` (C5-73) stand, with §10.1 and §10.4 | §9.5.3, §9.7.3, §10.1, §10.4 |
| E-l3 | **R-l** (KD-3) | live gate W2b (jump latency) added to §17.3 from a separate gatekeeper item | **accepted**: W2b stays in §17.3, not run; it runs only with the user's go-ahead | §17.3 |
| E-l4 | **R-l** (WP3b-D1…D4) | the host deviations of WP3b (diag request and event, the recorded session, the V4 frame checker) | **accepted**, recorded in K1 16.8 E-l. For this contract: §6.5's once-a-minute diag request is dropped, never queued, while no knob with `diag: 1` is connected (WP3b-D1), and the `diag` event carries only the listed fields (WP3b-D2) | §6.5; K1 12.3, 16.8 |

**[P3b] Accepted deviations of the phase-3 builds (lead decisions, 2026-09-26)**

| # | Ruling | Was | Now | Where |
|---|---|---|---|---|
| WP5P3-D1 | **lead** (2026-09-26) | `tests\test_kdocs_contract.py` changed only inside `PENDING_WP5` | **accepted**: `assert_group_copy` defaults to `tone="error"`, one line outside `PENDING_WP5`, since R-j (E-j) breaks the pinned `meta` check and no other package owns the file | C5-76, E-j |
| WP5P3-D2 | **lead** (2026-09-26) | C5-78 as asked (review item R8): pass the close `reason` | **accepted**: also, a `cancel_result(restored=false)` after a `lock` or `sleep` close raises no desktop notice (`Original window no longer available`), since K4 §15 never restores focus for those closes | §5.7.4, §11, C5-78 |
| WP5P3-D3 | **lead** (2026-09-26) | the simulator's picker restored focus for every close | **accepted**: `SimulatedWindows.cancel` reports `restored=False` for `lock` and `sleep` and records the reasons it received | §16, C5-78 |
| WP5P3-D4 | **lead** (2026-09-26) | C5-79: the preview ranks the base rows by the record | **accepted**: rows the record does not hold go to the end of the preview in their current order (the adapter treats them as Play-next or foreign), and the list re-reads after the job, as before | §9.5.3, C5-79 |
| WP5P3-D5 | **lead** (2026-09-26) | new entries would extend the [P2b] or E-* errata | **accepted**: new ids C5-78 and C5-79 and the tag **[P3]**, separate from K-errata's [P2b] and the E-* errata | header, §19 |
| WP6-GIL-D1 | **lead** (2026-09-26) | §1.2, §9.8.7: a tracks page over 1 ms drops to `limit` ≤ 25 | **accepted**: `limit=50` (0.43–0.71 ms, within 1 ms at p95 in every run); 25 would double the pages and halve what fits in the 20 s deadline (≈ 1,100 tracks). Unverified live: R5/W5 check it, and 25 is the one-constant fallback | §1.2, §9.8.7, §9.8.8 |
| WP6-GIL-D2 | **lead** (2026-09-26) | §1.2, §9.6.1: full-queue reads deferred while an episode runs, 21-row windows, the cached zone-group context | **accepted**: none of them applied; no Sonos parse holds over 1 ms (the Browse envelope 0.26–0.49 ms at 100 rows, ZoneGroupState 0.15–0.17 ms) | §1.2, §9.6.1 |
| WP6-GIL-D3 | **lead** (2026-09-26) | §9.8.8: the first page of 100 gives the count and the mosaic | **accepted**: with 50-row pages a second page is read (at most 100 tracks in all) when the first 50 hold fewer than 4 albums with art or Apple sends no `meta.total`; if it fails, a neighbour keeps what it has and the focused playlist still raises | §9.8.8 |
| WP6-GIL-D5 | **lead** (2026-09-26) | §9.8.8: the duration from all pages | **accepted**: at most `META_MAX_TRACKS` = 10,000 tracks (200 pages of 50); past it, or when a page fails or offsets do not advance, the count and mosaic stay with `duration_ms` None (no raise), and an unreadable list's None is cached by `(id, last_modified)` | §9.8.8 |

---

## 20. Open questions (genuine; each with a recommended answer)

| # | Question | Why it is open | Recommended answer |
|---|---|---|---|
| OQ-1 | Does `GET /v1/me/library/recently-added` return `meta.total`? | Documented for library playlists (CF §2), unverified for this endpoint; the live probe read 4 pages without logging it (LC:16) | Add one read-only check to R4/R5. If present: bounds = total from page 1 (no growth re-entries). If absent: the open-ended mode of §5.2.2 as written |
| OQ-2 | Under Sonos native shuffle, does `Browse(Q:0)` keep the original order (H1) or the shuffled one (H2)? | A06 §3.2; live check R3 not run | Run R3 before WP5 freezes §5.6.2. H2: keep the design (played rows, now, card). H1: show only the now-playing row and the card (bounds `0..1`), because rows before `Track` are not the played ones |
| OQ-3 | Should a Play next of a partly playable playlist say how many songs were skipped? | U6 makes playlists lenient; r2.1 has copy for partial *starts* (`Playing 33 of 34`) but none for Play next | Keep `Queued next` / `Queued next · {album}` (no new copy) for this release; revisit if the user notices |
| OQ-4 *(closed by K1)* | Does the firmware's "entering" wait for the cover decode (so §6.3's art deferral shortens the blackout)? | A04 §6.1 says yes; K1 owns the entering sequence | **Answered by K1 §12.5.5 (P5-R26):** yes in the R5-off builds (binaries B and C), no in binary A (R5 posts the decode and acks at once). §6.3 stays **unconditional** (valid and harmless in every build); gate H3 measures `enterMsLast` with and without a cover change on whichever binary ships |
| OQ-5 | Is a 60-row companion shuffle fast enough? | up to `U_r − 1` = 59 guarded moves × 3 SOAP calls (position read, `UpdateID` read, move; C5-50) ≈ 177 calls; per-call time on this household unmeasured (A06 §3.4 estimates 30–80 ms), so ≈ 5.3–14 s. Volume, Seek and Play/Pause stay responsive meanwhile (§1.1), and the knob confirmed at acceptance | **Keep the cap at 60**: it is the user’s binding decision (00 U4). W3 measures the per-call time and a full 60-row reorder with the position reads. If it exceeds 6 s (≈ 34 ms per call), report the numbers to the user with the option of a lower cap (the largest U whose `3·(U − 1)·t_call` ≤ 4 s, e.g. 27 rows at 50 ms, Sonos shuffle above); the contract does not change the cap on its own. Not an option: dropping the per-move position read (C5-50) |
| OQ-6 | Under Sonos shuffle, does `avTransport.Previous` go to the last played track? | S01:147 designs `Prev: last played`; no source confirms Sonos's UPnP behaviour | Verify during R3 (read-only for the state, one Previous only with the user's go-ahead). If it does not, dim Tracks Button 4 at Prev with `skip_unavailable` under Sonos shuffle |
| OQ-7 (rev 4; **[r2.2] closed**: the call is refused, 400 / 40012; add-only is final, C5-67; the refusal copy is `Unfavourite in Music app`) | Does `DELETE /v1/me/favorites?ids[songs]=<id>` remove the star from the user's devices, with the companion's sign-in? | The rating `DELETE` clears the server but not the iPhone (LS 23:01 UTC); the favourites `DELETE` was not sent (blocked by the session's permission system); public reports disagree (204 vs 400 "Insufficient Permissions") | Ship `add_only` (C5-63). Run W4b (§17.3) with the user's go-ahead: star gone on the iPhone → amend the default to `favorites_delete`; 400/405 or star kept → keep `add_only`. Approve the refusal copy (`Unfavourite in Music` or the 176 px `Unfavourite in the Music app`) in the copy pass either way |
| OQ-8 (rev 4) | Does a **paused** seek report `TRANSITIONING`, and how long does it take? | W2 ran only while PLAYING (LC); CS §5 step 4 not run | Keep C5-65's "no `TRANSITIONING` seen → confirm from 1.0 s" fallback (**[r2.2]** C5-68: a PLAYING / PAUSED_PLAYBACK read ≥ 1.0 s after the reply, within 8 s); measure it with the next Seek live check and tighten the rule only if the numbers ask for it |

---

## Appendix A. Grammar-oracle sign-off: controller vs the r2.2 prototype (**[P2a]**; lead ruling R-e)

**Rule (R-e).** Every difference between the controller's button map and the r2.2 prototype cites a contract ruling; an undocumented difference is fixed in the controller to match the design. This appendix is the sign-off table. It changes no behaviour.

### A.1 Method and result

- **Design side:** `tests\fixtures\grammar_oracle_bs.json`, produced by `tests\js\grammar_oracle.cjs` from the r2.2 master's `prototypes\Browse and Snap.dc.html`: BS `renderVals()`'s `foot` (glyph key and tone of each of the four slots) for every state-picker combination that reaches the footer (BS:1352-1365), with the logic block evaluated unmodified except one capture line.
- **Controller side:** `tests\test_cc5_grammar_oracle.py` drives the v7 controller into each state through its public inputs only (presses, turns, completions, presenter events) and compares its frame's buttons slot by slot: the icon after the VOC-N06 token map, and the tone derived as the knob derives it (K1 §5.2, `button_tone_v5`; r2.2's liked heart, `on` + PINK, is the tone `liked`, VOC §2.3 row 4). Labels and press behaviour are not in the footer; they are §A.4.
- **Result (2026-09-25, night, the tree after phase 2a):** 238 golden cases; 237 compared (one is not a companion frame, §A.3); **948 slots**, **925 equal**, **23 differ**; **0 untagged**. By the oracle's tag: `C5-61` 11, `VOC-R14` 7, `C5-4` 3, `skip_unavailable` 2. Guard runner: `test_cc5_grammar_oracle.py` ran 4 tests, 0 failures, 0 errors, 0 skipped (the golden also regenerated byte-identical from the r2.2 prototype). **[P2a]** (review KD-R6) `tests\test_kdocs_contract.py` pins this result: the observed differences must equal §A.2 row for row, §A.2 must parse to the same set with each row's rulings, and the counts in this bullet must be the run's.
- Every one of the 23 slots is listed in §A.2 with the ruling that allows it. The oracle's tag is kept as a column; the **Ruling** column is authoritative where the two differ in precision (rows A1 and A3: the oracle files them under `VOC-R14`, but the token difference comes from §3.1 and C5-38).

### A.2 The 23 differing slots

Notation: `token · tone`, tones as K1 §5.2 (`nav`, `go`, `dim`, `on`, `off`, `liked`); the controller's dim code in brackets. The golden's `busy` spans are the prototype's `Starting…` (`start`) and Play next (`pn`) states; `list` is its "Loading list" art option.

| # | Case (golden) | Button | Controller | r2.2 prototype | Differs in | Oracle tag | Ruling | Verdict |
|---|---|---|---|---|---|---|---|---|
| A1 | `home-playing-none` | Button 1 | `play · dim` [`nothing_playing`] | `pause · nav` | token and tone | `VOC-R14` | token: §3.1 Home slot 0 (`pause` only while PLAYING is confirmed) with §9.1 / C5-38 (source `none` = STOPPED or no track, so never PLAYING; BS's picker combines "playing" with source none, a state no speaker reports). Tone: VOC §2.6 `nothing_playing` (Home 1, Home 3), VOC-R14 (S03 idle row) | documented |
| A2 | `home-playing-none` | Button 3 | `tracks · dim` [`nothing_playing`] | `tracks · nav` | tone | `VOC-R14` | VOC-R14 (Home 3 dims with `nothing_playing`, S03 idle row); VOC §2.6; §3.1 | documented |
| A3 | `home-playing-starting-none` | Button 1 | `play · dim` [`starting`] | `pause · dim` | token | `VOC-R14` | §3.1 Home slot 0 token with §9.1 / C5-38, as A1. The dim itself matches the design (`starting`: S01 "Home 1: not starting playback") | documented |
| A4 | `home-playing-starting-none` | Button 3 | `tracks · dim` [`nothing_playing`] | `tracks · nav` | tone | `VOC-R14` | VOC-R14; VOC §2.6 | documented |
| A5 | `home-paused-none` | Button 1 | `play · dim` [`nothing_playing`] | `play · go` | tone | `VOC-R14` | VOC §2.6 `nothing_playing` (Home 1), VOC-R14 | documented |
| A6 | `home-paused-none` | Button 3 | `tracks · dim` [`nothing_playing`] | `tracks · nav` | tone | `VOC-R14` | VOC-R14; VOC §2.6 | documented |
| A7 | `home-paused-starting-none` | Button 3 | `tracks · dim` [`nothing_playing`] | `tracks · nav` | tone | `VOC-R14` | VOC-R14; VOC §2.6 | documented |
| A8 | `tracks--1-none` | Button 4 | `prev · dim` [`skip_unavailable`] | `prev · go` | tone | `skip_unavailable` | C5-4 (`skip_unavailable`, §3.2): with nothing playing Sonos offers no Previous (`SO:158-175`); BS models no transport capabilities | documented |
| A9 | `tracks-1-none` | Button 4 | `next · dim` [`skip_unavailable`] | `next · go` | tone | `skip_unavailable` | C5-4 (`skip_unavailable`, §3.2): no Next offered | documented |
| A10 | `tracks-1-queue-start` | Button 3 | `seek · dim` [`starting`] | `seek · nav` | tone | `C5-4` | C5-3, C5-4 (§2.3: `starting` dims Tracks 3, because the track is about to change; §3.1 Tracks slot 2) | documented |
| A11 | `tracks-1-queue-start` | Button 4 | `next · dim` [`starting`] | `next · go` | tone | `C5-4` | C5-3, C5-4 (§2.3: `starting` dims Tracks 4; a skip would race the start's guards) | documented |
| A12 | `tracks-1-queue-pn` | Button 4 | `next · dim` [`queueing`] | `next · go` | tone | `C5-4` | C5-3, C5-4 (§2.3: `queueing` dims Tracks 4; a skip would turn the Play next into `song_changed`) | documented |
| A13 | `recent-queue-shuffle_off-idle-list` | Button 3 | `playnext · dim` [`loading`] | `playnext · nav` | tone | `C5-61` | C5-4 (`loading` extended to Recent 3/4, §3.2) with C5-61 / K2 M31 (the first page loading is the whole-list state, §5.2.3). BS's "Loading list" dims only the explorer; its knob list never loads | documented |
| A14 | `recent-queue-shuffle_off-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |
| A15 | `recent-queue-shuffle_on-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 (Button 3 dims on both sides: Sonos shuffle is on) | documented |
| A16 | `recent-airplay-shuffle_off-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 (Button 3 dims on both sides: the source is AirPlay; likewise radio, line-in and none below) | documented |
| A17 | `recent-airplay-shuffle_on-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |
| A18 | `recent-radio-shuffle_off-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |
| A19 | `recent-radio-shuffle_on-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |
| A20 | `recent-linein-shuffle_off-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |
| A21 | `recent-linein-shuffle_on-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |
| A22 | `recent-none-shuffle_off-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |
| A23 | `recent-none-shuffle_on-idle-list` | Button 4 | `play · dim` [`loading`] | `play · go` | tone | `C5-61` | C5-4, C5-61, as A13 | documented |

Everything else matches the prototype slot for slot, including r2.2's one footer change: a liked Up next row's Button 3 is `heart` with tone `liked` on both sides (R22 BS:1268; C5-67, C5-72). The explorer, Seek (idle, jumping, failed), every Up next kind × like state × shuffle × focus, the picker's snap slots and every busy span not listed above are identical.

### A.3 Not compared

| Case | Why | Ruling |
|---|---|---|
| `home-pc-off` | PC not connected: the knob draws its own firmware screen and footer; the companion sends no frame to compare | VOC-R23; K1 §8.10 (P5-11) |

### A.4 Differences the footer oracle cannot see (labels, press behaviour), all ruled

| Where | r2.2 prototype / specs | Controller | Ruling |
|---|---|---|---|
| Home Button 1 label (idle-row word) | `Play/Pause` (S03:15) | `Play` / `Pause`, following the icon | VOC-D08, C5-60 (approved, R22 CH §2) |
| Button legends | BS's `legend` key-hint panel (BS:1297, :341-349) | wire labels only; no desktop legend strings | C5-7, VOC-R24 |
| Up next Button 3 on a liked row | R22 CH §1 says it "dims" to PINK 0.30; BS draws it `'on'` and answers a press with the refusal (R22 BS:827, :1268) | enabled, `lit:"on"` (tone `liked`), the press refused with the Head shake and `Unfavourite in Music app` for 2200 ms | C5-67, C5-72, VOC-R31 |
| A press on a dimmed button | reason + Head shake everywhere (R:76, :182); BS silent in some states | `ignored` only where the state is on screen, else reason + Head shake | VOC-D07, C5-59 |
| Recent 3 refusal copy duration | 2200 ms (BS:1007) | 2000 ms (`reason_meta_ms`) | C5-5 (S01:50 outranks BS) |
| Up next Button 2 under Sonos native shuffle | shows `Sonos is shuffling` only (BS:872) | turns Sonos shuffle off | C5-17 |
| Snap to the side a window already holds | re-flies and re-places it (BS:1078-1088) | no-op | C5-11 |
| Snap auto-advance | always, to the first unassigned window from the head (BS:1090) | to the next unassigned, open window after the snapped one, wrapping; cancelled by a detent within 420 ms | C5-10, C5-46 |
| Presses during the 380 ms Play window | only turns are guarded (BS:922, :935) | turns, presses and hold ignored | C5-9 |
| Hold = Home | a host timer (BS:891) | firmware `kh` only | VOC-D06 |
| Moments (Like, Shuffle, Snap, Play next) | start on the press (BS:829, :879, :1088, :1021) | start on the host's `feedback` | VOC-D03 |

### A.5 Undocumented differences

**None.** No slot differs without a ruling, so nothing has to change in the controller to match the design. From now on an untagged difference fails `test_every_footer_matches_or_is_a_listed_deviation`; it is fixed to match the r2.2 prototype unless a ruling is first added to this contract (a C5 entry) and to this appendix. **[P2a]** (review KD-R6) The oracle's tags cover whole regions (74 case-slot pairs under its four tags, 23 of them differing), so on its own it lets a slot inside a region change unnoticed; `tests\test_kdocs_contract.py` (`AppendixASignOffTests`) closes that: a new, changed or vanished difference anywhere fails until §A.2 and the test's signed-off set are updated together.
