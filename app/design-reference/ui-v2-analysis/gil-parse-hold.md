# H5 parse bench: how long the service parses hold the GIL

Measured headless on 2026-09-26 (03:03–03:19 local time) on the user's PC, which was busy with other work at the time. No network, no Sonos, no Apple Music, no knob, nothing on screen.

- **Bench:** `tools\stage_checks\gil_parse_hold.py` (new; K4 §6.6 H5, K4 §4.7.3, K3 §1.2, [G1] G1-5).
- **Run it:** from `app`: `.venv\Scripts\python.exe -I ..\tools\stage_checks\gil_parse_hold.py [--reps 20] [--json PATH] [--recorded DIR] [--only TEXT] [--quick]`. The script blocks every network entry point of requests, urllib3 and soco before the first row runs.
- **Runs:** six full runs, four at 20 repetitions and two at 60, plus three 60-repetition runs of the JSON rows only. Unless a row says otherwise, the table gives the 60-repetition run at 03:15 and the range over the six full runs. One 20-repetition run (03:12) ran with the whole machine about 1.7 times slower; its figures are the top of each range.
- **Machine:** Windows 11 build 26200, Python 3.14.5, requests 2.34.2, soco 0.31.2, lxml 6.1.3.
- **Tests:** `tests\test_cc_gil_parse.py` pins the caps, checks that no request exceeds them, and runs the bench's fixtures through the real client code. Since the review it also covers `playlist_meta`'s reach and its failures after the first page, and the encoding of the recovery copy.
- **Review fixes (05:30–05:55, WP6GIL-1, -3, -4, -5):** see §2.4, §4.1 and §5. The recovery rows were re-measured at 05:49 (20 repetitions) and 05:57 (60 repetitions).

---

## In plain words

**Two parses were too long, and both are now capped.** Apple Music returns each page of results as JSON, which Python reads in one go. While it reads, no other Python thread can run. On this PC:

- **A tracks page of 100 songs** (used to start an album or playlist, and for the playlist mosaic) took **about 1 ms**, and up to 1.7 ms. It now asks for **50 songs per page**, which take about 0.45 ms.
- **A catalog lookup of 300 songs** (used to fill in Up next rows) took **about 2 ms**, and up to 3.8 ms. It now asks for **50 songs per request**, which take about 0.3 ms.

**Nothing else needed to change.** Every other parse stays well under 1 ms at the largest size the app asks for:

- **Playlists pages** of 100 take 0.2 ms.
- **Recently Added pages** of 25 take 0.05 ms.
- **Like checks** of 100 songs take 0.04 ms.
- **Sonos queue reads** of 100 rows take 0.3 ms. The only part that blocks other threads is a small wrapper. The song list inside it is parsed by lxml, which lets other threads run while it works (checked with 1,000 rows: 3 ms of parsing, while a waiting thread was delayed no more than by normal switching).
- **Sonos zone-group reads** take 0.2 ms even for 32 speakers.
- **The Up next history file** takes 0.5 ms in the worst case.

So the Sonos queue reads keep 100-row pages. They are never postponed during an animation, and the 1 s poll keeps reading the speaker groups fresh.

**What the caps cost.** Starting a 100-song album or playlist that has not been prepared in advance now takes 2 page requests instead of 1, or about 0.45 s more. Items that are prepared in advance (the focused item and its neighbours) are unaffected. An Up next read of 51 to 60 upcoming songs now needs 2 catalog requests instead of 1. The playlist mosaic looks at the same first 100 tracks as before, so it reads a second page only when the first 50 tracks hold fewer than 4 albums.

**One more long hold was found, outside the parse table, and it is now fixed.** Before a start replaces the Sonos queue, the app saves a recovery copy of the old queue. That save used to convert the whole queue to text in one go:

- **100 rows:** 0.13 ms.
- **1,000 rows:** 1.3 to 2.2 ms.
- **5,000 rows (the limit):** 8 to 14 ms.

A start runs while the knob can still take input, so this broke G1-5's 2 ms ceiling for any old queue of about 1,000 rows or more. The save now converts one song at a time. The longest single step left is a copy of the finished text, under 0.8 ms at 5,000 rows (§2.4).

---

## 1. Method

**What holds the GIL.** `requests`' `Response.json()` decodes the body and runs `json.loads`, and `json.loads` parses the whole document in one C call that keeps the GIL. soco reads each SOAP answer with ElementTree's expat parser (`Service.unwrap_arguments`), which is also one C call over the whole envelope. The DIDL-Lite inside a Browse answer and the ZoneGroupState document are parsed with lxml (`from_didl_string`, `normalize_zgs_xml`), which releases the GIL while libxml2 parses.

**Fixtures.** The bench builds seeded, synthetic bodies in the shapes the services return. About 8 % of the titles are Japanese or Korean and about 12 % accented Latin. The bodies are compact UTF-8 JSON, as Apple sends it, and escaped DIDL-Lite inside SOAP, as Sonos sends it.

| Body | Bytes per row | Source of the shape |
|---|---|---|
| Catalog song (`songs?ids=`, default `albums`/`artists` relationships, no `extend`) | ≈ 1.5 KB | K3 §9.8.4; the attributes of Apple's documented song object |
| Library track with its catalog song (`/tracks?include=catalog`) | ≈ 2.3 KB | K3 §9.8.7, §9.8.8 |
| Library playlist (`extend=inFavorites`) | ≈ 0.65 KB | K3 §9.8.5 |
| Recently Added album | ≈ 0.55 KB | K3 §9.8.6 |
| Rating | ≈ 0.1 KB | K3 §9.8.3 |
| Sonos queue row (Apple Music, sid 204) | ≈ 0.5 KB of DIDL-Lite, 0.65 KB escaped in the envelope | `SO:315`, A06 §4.1 |
| ZoneGroupState member | ≈ 0.7 KB | soco 0.31.2 `zonegroupstate.py` |

`--recorded DIR` adds real bodies saved during a supervised live check. It prints only their names and sizes.

**Two measurements per row, 20 repetitions by default (K4 §4.7.3):**

- **call:** the parse is timed on one thread with nothing else running. When the parse is one GIL-holding C call (`json.loads`, expat; rows of kind `call`), this time is the hold.
- **probe:** the row runs on a worker thread. Meanwhile a probe thread sleeps 0.5 ms at a time and records how late it gets the GIL back. The bench uses `timeBeginPeriod(1)` and a 1 ms switch interval, as the app does (K4 §4.7.2).

Two reference rows calibrate the probe:

- **Pure Python** reads 2.0–2.6 ms at p95. The waiting thread's 1 ms timed wait rounds up to the Windows timer tick, so on this platform ordinary switching between Python threads already costs a waiting thread about 2 ms.
- **One `sorted()` C call of 1.1–1.7 ms** reads 1.4–2.5 ms.

So the probe cannot tell a C call under about 1.5 ms from normal switching, and the **call** rows are the measurement. For a whole client path, and for lxml, the probe confirms only that nothing hidden holds much longer than normal switching (`py`: probe p95 within the pure-Python p95 + 1 ms).

**Cap rule.** Each cap is the largest size whose call hold meets both conditions:

- **p50 at most 0.5 ms:** a real body up to twice the fixture's size still parses within the 1 ms design target.
- **p95 at most 1.0 ms:** the tail stays within the design target. On this shared PC the tail includes preemption, because another process can pause the thread that holds the GIL.

The bench prints the caps this rule allows. The two full runs recorded at 03:15 allowed catalog ids ≤ 60, tracks pages ≤ 50, playlists pages ≤ 100 and Browse rows ≤ 100. The slow 03:12 run allowed tracks pages of only 25 (see §3).

## 2. Results

Hold = call time of one C call. p50 / p95 in ms from the 03:15 run (60 repetitions); the range covers all six full runs.

### 2.1 Apple Music JSON (`Response.json()`)

| Parse (lane) | Size | Body | p50 / p95 (03:15) | p50 range | p95 range | Verdict |
|---|---|---|---|---|---|---|
| `catalog_songs` (lookahead) | 300 ids (before) | 446 KB | 1.89 / 2.69 | 1.85–3.29 | 2.13–3.80 | **HOLD** |
| | 100 ids | 149 KB | 0.53 / 0.58 | 0.53–0.97 | 0.55–1.42 | over the rule |
| | 60 ids | 89 KB | 0.33 / 0.55 | 0.32–0.34 | 0.33–0.64 | within |
| | **50 ids (now)** | 74 KB | **0.27 / 0.35** | 0.26–0.49 | 0.28–0.55 | **OK** |
| | 21 ids (one window) | 31 KB | 0.11 / 0.12 | 0.11–0.12 | 0.12–0.16 | OK |
| `/tracks?include=catalog` pages: `resolve`, `playlist_meta` (library, lookahead) | 100 (before) | 230 KB | 0.92 / 1.07 | 0.92–1.55 | 1.00–1.74 | **over 1 ms** |
| | **50 (now)** | 116 KB | **0.49 / 0.77** | 0.43–0.71 | 0.47–0.81 | **OK** |
| | 25 | 58 KB | 0.25 / 0.40 | 0.21–0.26 | 0.23–0.40 | OK |
| Playlists pages, `extend=inFavorites` (library, lookahead) | 100 (unchanged) | 64 KB | 0.22 / 0.36 | 0.20–0.22 | 0.21–0.36 | OK |
| Recently Added (library, lookahead) | 25 (unchanged) | 14 KB | 0.05 / 0.08 | 0.05–0.09 | 0.05–0.09 | OK |
| `ratings` (lookahead) | 100 ids (unchanged) | 10 KB | 0.04 / 0.06 | 0.04 | 0.04–0.07 | OK |

- `json.loads` costs **0.37–0.39 ms per 100 KB** at p50 at normal clock speed (0.41 in the slow run). A recorded body can be checked against this rate.
- **Whole client paths** (the parse plus the Python that walks it; kind `path`): `catalog_songs` of 50 ids, `resolve` of 50 tracks, and gzip transfer decoding in 10 KB reads (zlib releases the GIL) all read `py`. The 300-id path read up to 3.7 ms at p95 on the probe, because of its parse.

### 2.2 Sonos XML (soco)

| Parse (audio lane) | Size | Body | p50 / p95 (03:15) | p50 range | p95 range | Verdict |
|---|---|---|---|---|---|---|
| Browse(Q:0) envelope, expat (`unwrap_arguments`) | 21 rows (a window) | 14 KB | 0.15 / 0.20 | 0.07–0.15 | 0.07–0.20 | OK |
| | 60 rows (U ≤ 60) | 40 KB | 0.17 / 0.32 | 0.16–0.34 | 0.17–0.59 | OK |
| | **100 rows (a page)** | 66 KB | **0.26 / 0.28** | 0.26–0.49 | 0.28–0.54 | **OK** |
| DIDL-Lite, lxml plus soco's per-item objects (`from_didl_string`) | 100 rows | 51 KB | 4.0 of CPU; probe p95 2.02 | | | `py` (GIL released) |
| lxml `fromstring` alone | 1,000 rows | 505 KB | 2.66 of CPU; probe p95 1.35 | | | `py` (GIL released) |
| Whole `queue_window` path (text, envelope, DIDL, rows) | 100 rows | 66 KB | 6.2 of CPU; probe p95 2.06 | | | `py` |
| ZoneGroupState envelope, expat | 32 players | 35 KB | 0.15 / 0.20 | 0.15–0.17 | 0.17–0.28 | OK |
| ZoneGroupState `process_payload` (lxml, XSLT, zones) | 32 players | 24 KB | 0.61 of CPU; probe p95 0.76 | | | `py` |

- Expat costs **0.43–0.46 ms per 100 KB** at p50 at normal clock speed (0.83 in the slow run).
- soco's DIDL-Lite step is mostly Python (about 4 ms for 100 rows). It runs on the audio lane and gives the GIL up at every switch interval, like any Python code.

### 2.3 Files the service lanes read and write

| Operation | Size | Body | p50 / p95 (03:15) | p95 range | Verdict |
|---|---|---|---|---|---|
| Up next history (`QueueLedger.save`), re-read with `json.loads` | 5,000-song base + 64 Play-next blocks | 104 KB | 0.26 / 0.47 | 0.28–0.53 | OK |
| The same history, rewritten with `json.dumps` | same | 104 KB | 0.32 / 0.45 | 0.32–0.61 | OK |
| Recovery copy before the fix (`_save_recovery` → `CredentialStore.save`), one `json.dumps` | 100 rows | 89 KB | 0.12 / 0.13 | 0.13–0.18 | OK |
| | 1,000 rows | 880 KB | 1.48 / 2.24 | 1.43–2.24 | **HOLD** |
| | 5,000 rows (`MAX_QUEUE`) | 4.4 MB | 8.4 / 12.2 | 8.6–14.3 | **HOLD** |

### 2.4 Recovery copy after the fix (review WP6GIL-4)

`_save_recovery` now encodes the record with `sonos._recovery_json_parts`: one small `json.dumps` per value and per queue row, a few microseconds each, with the interpreter handing the GIL over between them at the 1 ms switch interval. One join builds the text, which is byte for byte what `json.dumps(record)` gave. `sonos._RecoveryStore.save_encoded` writes it in the `CredentialStore` format. `CryptProtectData`, the file write and `fsync` release the GIL.

The 05:49 run, 20 repetitions (idle probe p95 0.57 ms; pure-Python reference probe p95 2.05 ms). `call` rows are p50 / p95 in ms; `path` rows give the probe p95.

| Step | Kind | 100 rows (89 KB) | 1,000 rows (880 KB) | 5,000 rows (4.4 MB) | Verdict |
|---|---|---|---|---|---|
| One `json.dumps` of the whole record (the old path, for reference) | call | 0.12 / 0.13 | 1.31 / 1.40 | **13.55 / 14.12** | **HOLD** at 5,000 |
| Join of the encoded parts | call | 0.002 / 0.002 | 0.021 / 0.022 | 0.72 / 0.76 | OK |
| DPAPI copy in (`create_string_buffer` in `credentials._dpapi`) | call | 0.002 / 0.002 | 0.016 / 0.018 | 0.76 / 0.80 | OK |
| DPAPI copy out (`string_at`) | call | 0.001 / 0.002 | 0.012 / 0.013 | 0.54 / 0.55 | OK |
| Encode in parts, the whole path | path | 0.51 | 1.75 | 2.04 | `py` |
| The whole save: parts, DPAPI, atomic write to a temporary folder | path | 0.55 | 2.02 | 2.52 | `py` |

- A 60-repetition run at 05:57 agreed at 5,000 rows:
  - Join: 0.59 / 0.68 ms.
  - Copy in: 0.74 / 0.81 ms, with one repetition at 1.0 ms.
  - Copy out: 0.52 / 0.56 ms.
  - Encode path and whole save: probe p95 2.53 and 2.51 ms, against a pure-Python reference of 2.17 ms (`py`).
  - The one-call `json.dumps`: 8.3 / 13.4 ms.
- The whole save takes 2.5, 43 and 45 ms of wall time (p50), almost all of it in DPAPI and `fsync` with the GIL released.
- The largest single C call is now 0.80 ms at p95 for 5,000 rows, within the 1 ms design target. A real record twice the fixture's size would reach about 1.6 ms: within G1-5's 2 ms ceiling, over the design target. The recorded bodies of the hardware window (§6) settle this.

## 3. Decisions (K3 §1.2's table)

| K3 §1.2 row | Before | Now | Why |
|---|---|---|---|
| Apple `catalog_songs` ids per request | 300 | **50** (`AppleMusicClient.CATALOG_BATCH`) | 300 ids held 1.85–3.29 ms. 50 is K3's and VOC's value, 0.26–0.49 ms. The rule would allow 60, but that saves a request only for a 51–60-row upcoming read |
| Apple `/tracks` pages (`resolve`, `playlist_meta`) | `limit=100` | **`limit=50`** (`TRACKS_PAGE_LIMIT`) | 100 held 0.92–1.55 ms (p95 up to 1.74). 50 holds 0.43–0.71 ms, within 1 ms at p95 in every run (0.47–0.81). 25 would halve the hold again but double the pages (deviation WP6-GIL-D1) |
| Apple playlists pages (favourite playlists, folders) | `limit=100` | **unchanged** (`PLAYLISTS_PAGE_LIMIT` = 100) | 0.20–0.22 ms |
| Apple Recently Added | `limit=25` | unchanged | 0.05–0.09 ms |
| Apple `ratings` | 100 ids | unchanged (`RATINGS_BATCH`, now also used by the playlists' ratings fallback) | 0.04 ms |
| Sonos queue DIDL-Lite | `get_queue(max_items=100)` | **unchanged** (`sonos.QUEUE_PAGE_ROWS` = 100). **No deferral** of full-queue reads during episodes, and no smaller windows | Envelope 0.26–0.49 ms at 100 rows. The DIDL-Lite is parsed by lxml with the GIL released. K3 §1.2 changes only rows over 1 ms (deviation WP6-GIL-D2 records the decision) |
| Sonos ZoneGroupState | every `_context()` | **unchanged**: the poll reads it fresh. `read_state(reuse_context_s)` stays available but the runtime need not pass it | 0.15–0.17 ms at 32 players |

**Why 50 and not 25 for tracks pages.** In the slow 03:12 run the cap rule allowed only 25, because that run's 50-row p50 was 0.71 ms. Its p95 (0.81 ms) still met the 1 ms design target. All other runs allowed 50. The page size trades hold time for start latency:

| Page size | Resolve pages for 100 tracks | Tracks listable within the 20 s resolve deadline |
|---|---|---|
| 100 | 1 | ≈ 4,400 |
| **50** | **2** | **≈ 2,200** |
| 25 | 4 | ≈ 1,100 |

A last quick run at 03:19 caught the PC under heavy load: the idle probe alone was 2.7 ms late at p95. Even then, the new sizes stayed within 1 ms, and the old ones went past G1-5's ceiling:

| Size | p50 / p95 under heavy load (ms) |
|---|---|
| Tracks page, 50 rows (now) | 0.81 / 0.91 |
| Tracks page, 100 rows (before) | 1.73 / 2.29 |
| Catalog lookup, 50 ids (now) | 0.50 / 0.51 |
| Catalog lookup, 300 ids (before) | 3.15 / 4.10 |

The deadline figures are estimates, at the 424–465 ms per page that LC W1 measured. If recorded bodies turn out more than 1.5 times the fixture's size (a p50 above about 0.6 ms at 50 rows), K3's 25 is the fallback: change one constant, `TRACKS_PAGE_LIMIT`.

## 4. Code changes (WP6-gil)

- **`control_center\apple_music.py`:**
  - `TRACKS_PAGE_LIMIT` 100 → 50 and `CATALOG_BATCH` 300 → 50, with the bench's figures in a comment.
  - New `PLAYLISTS_PAGE_LIMIT` (100), used by the favourite-playlists fast path, full scan and folder walk.
  - The playlists' ratings fallback now uses `RATINGS_BATCH`.
  - `resolve` sizes its page bound to the page size (`max(MAX_TRACK_PAGES, ceil(MAX_TRACKS / limit) + 2)`), so an item over 5,000 tracks still fails as "exceeds the supported track limit".
  - `playlist_meta` keeps the mosaic's 100-track window (`MOSAIC_SCAN_TRACKS`). It reads further pages only while fewer than 4 albums were found, and the duration counts every page once. Without `meta.total`, the count is still known when the playlist ends within its first 100 tracks, as it was with a 100-row first page.
  - Docstrings updated.
- **`control_center\sonos.py`:**
  - `QUEUE_PAGE_ROWS` = 100 replaces the literal in `_queue`, `_slice` and `queue_window`, with the bench's figures and the no-deferral decision in a comment.
  - `read_state`'s docstring records that the zone-group reuse is not needed.
  - `_save_recovery` noted its encode cost. This is superseded: §4.1 encodes the record in parts.
- **`control_center\queue_context.py`:** the `save` docstring records the ledger's cost.
- **`control_center\artwork.py`:** no change (it parses no JSON or XML; its PIL work is `gil_pil_hold`'s).
- **Tests:**
  - New `tests\test_cc_gil_parse.py` (15 tests).
  - `test_cc_apple_v7.py`: catalog batches of 50, `limit=50` on every page, `playlist_meta`'s first page at `limit=50`, and the duration test with a first page that already holds 4 albums.
  - `test_cc_music.py`: `limit=50` on the own-params pager.

### 4.1 Review fixes

- **WP6GIL-1, `playlist_meta`'s reach (`apple_music.py`).** With 50-row pages the duration scan still used the pager's default bound of 100 pages, so it reached only 5,000 tracks, down from 10,000. A focused playlist of 5,001 to 10,000 tracks raised, and the tile lost its count, mosaic and duration.
  - New `META_MAX_TRACKS` = 10,000. The page bound is `max(MAX_TRACK_PAGES, ceil(META_MAX_TRACKS / TRACKS_PAGE_LIMIT))`, which is 200 pages of 50.
  - When `meta.total` is over 10,000, no page is read for the duration. The count and mosaic come back with `duration_ms` None.
  - The duration moved into `_playlist_duration`. A list that cannot be read to its end within the bound, or whose offsets do not advance, gives `duration_ms` None, still with count and mosaic. That None is cached by (id, last_modified), so a refocus reads only the 100-track window.
- **WP6GIL-3, a failed page after the first (`apple_music.py`).**
  - A window page (the mosaic's or the count's second page) that fails with anything but a 401/403 ends the window **for a neighbour**. The neighbour keeps what the pages read so far gave: the mosaic found so far, and the count from `meta.total`, or None. The single 100-row read did the same, so the controller no longer drops the whole result.
  - The **focused** playlist still raises on a window failure, as before the change: its duration needs every page. This also avoids replacing a neighbour's full mosaic with a partial one when it gains focus.
  - A failed **duration** page (after a complete window) keeps the count and mosaic with `duration_ms` None, and caches nothing, so the next focus asks again.
  - A 401/403 still raises everywhere. A `CredentialError` is not an `AppleMusicError` and passes through.
  - A partial sum is never returned or cached.
- **WP6GIL-4, the recovery copy (`sonos.py`).** New `_recovery_json_parts(record)` and `_RecoveryStore(CredentialStore).save_encoded(data)`, which is the default recovery store.
  - `_save_recovery` hands the store the joined parts when the store has `save_encoded`. A store without it gets the mapping, as the tests' in-memory stores do.
  - The file format is unchanged (`MAGIC` + DPAPI-protected JSON, prefix `.credentials-` for the temporary file), and `CredentialStore.load` still reads it.
  - `credentials.py` is not changed. `sonos.py` imports its `_dpapi` (see §6). Measurements are in §2.4.
- **WP6GIL-5, comments (`apple_music.py`, `sonos.py`, `queue_context.py`).** The comments that justify the caps now state the two-part rule (p50 ≤ 0.5 ms and p95 ≤ 1.0 ms) and quote this record's 03:15 figures and six-run ranges. Before, they stated a p95 ≤ 0.5 ms rule, which the 50-row cap breaks, and a ≤ 0.35 ms bound for the Browse envelope, which the record does not support.
- **Bench (`gil_parse_hold.py`).** New `recovery save rows=N` rows: the join, DPAPI's copy in and out, the encode path, and the whole save, which writes into a temporary folder removed at the end. `--no-save` skips the whole-save rows. The caps line gains `recovery_save_largest_hold_ms`.
- **Tests:** `test_cc_gil_parse.py` has 31 tests (16 new).
  - Reach: 6,000 and 10,000 tracks, over 10,000 with and without `meta.total`, and the cached None.
  - Failures: 429, 500 and 503 on page 2; a broken `next`; no `meta.total`; 401 and 403; the focused playlist; a failed duration page.
  - Recovery copy: byte identity with `json.dumps`; a 300-row start that makes no large `json.dumps`; the default store beside the credentials; the DPAPI round trip in a temporary folder.
  - The bench's recovery fixture and caps key.

## 5. Deviations

**[P3b] Accepted by the lead (2026-09-26):** D1, D2, D3 and D5, as built (recorded in K3 §19's [P3b] table; K3 §1.2, §9.6.1, §9.8.4, §9.8.7, §9.8.8, VOC §8.3 and K4 §4.7.3 now state the caps). D4 stays withdrawn.

| Id | What | Why |
|---|---|---|
| WP6-GIL-D1 | Tracks pages use `limit=50`, where K3 §9.8.7 and §1.2 say "drops to 25". ~~VOC's `resolve` and `playlist_meta` rows still say `limit=100`~~ **[P3b]** VOC's rows say `limit=50` | K4 §4.7.3 lets the bench tune the starting values. 50 holds within 1 ms at p95 in every run, and 25 would double the pages and halve what fits in the 20 s deadline. `limit=50` is unverified live: `limit=100` and no limit (Apple's default page) both worked live, so 50 is expected to work. Check in R5/W5 |
| WP6-GIL-D2 | No full-queue read deferral, no 21-row splitting of larger windows, no zone-group reuse while an episode runs | K3 §1.2 applies these only where the bench shows a hold over 1 ms. None does (0.28–0.54 ms at 100 rows, 0.2 ms for zone groups) |
| WP6-GIL-D3 | `playlist_meta` may read a second page (at most 100 tracks in all) for the mosaic, or for the count when Apple sends no `meta.total`. If that page fails (anything but a 401/403), a neighbour keeps what the pages read so far gave: the mosaic found so far, and the count from `meta.total`, or None. The focused playlist still raises | When the second page is read successfully, the v7 mosaic and count are exactly what a 100-row first page gave. It costs a lookahead-lane request only when the first 50 tracks hold fewer than 4 albums, or when `meta.total` is missing. When the second page fails, the neighbour keeps a single-art or partial result, where the single 100-row read would have given the full mosaic. Before review WP6GIL-3 it lost everything |
| WP6-GIL-D4 | **Withdrawn (review WP6GIL-4).** The queue-recovery copy is no longer encoded in one `json.dumps`. It is encoded one value and one queue row at a time (§2.4) | The earlier text said the hold was accepted because K3 §1.2 accepts a rare hitch in a user action. That was wrong: K3 §1.2 (and K4 §4.7.3) accept only a full-queue read in 100-row pages that a user action needs at once, and G1-5 has no user-action exemption. No deviation remains |
| WP6-GIL-D5 | `playlist_meta`'s duration reads at most `META_MAX_TRACKS` = 10,000 tracks, in 200 pages of 50. Past that, when a remaining page fails, or when offsets do not advance, the focused playlist keeps its count and mosaic with `duration_ms` None. It does not raise. An unreadable list's None is cached by (id, last_modified) | K3 §9.8.8 says "all pages" and names no limit. 10,000 is the reach 100 pages of 100 had before the parse cap (review WP6GIL-1). Returning count and mosaic keeps the tile filled where a raise made the controller drop the whole result. The cached None stops each refocus from repeating up to 200 lookahead-lane requests (about 90 s at LC W1's rate) |

## 6. Cross-package notes

- **K3 text (lead):** **[P3b] applied on 2026-09-26** (K3 §1.2, §9.6.1, §9.8.4, §9.8.7, §9.8.8 and §19; VOC §8.3; K4 §4.7.3):
  - Record this bench with W5 (§17.3). In the §1.2 table: `catalog_songs` 50 (applied); tracks pages 50 (applied, D1); playlists pages, Recently Added and ratings unchanged; Sonos DIDL-Lite and ZoneGroupState unchanged, with no deferral (D2).
  - §9.6.1: a full-queue read "follows §1.2's deferral" becomes "runs at once; the bench measured 0.3 ms".
  - §9.8.4: "≤ 50 per request".
  - §9.8.7 and §9.8.8: `limit=50`, and the mosaic's 100-track window (D3).
  - §9.8.8: the duration's 10,000-track reach, and the failure rules after the first page (D3, D5).
  - The deviation tables: ~~D1, D2, D3 and D5 need the lead's acceptance. R-l's list does not name them.~~ **[P3b]** D1, D2, D3 and D5 are accepted (lead, 2026-09-26). D4 is withdrawn.
  - VOC §8 rows `catalog_songs`, `resolve`, `playlist_meta`: the same values.
  - K4 §4.7.3: the parse table's result, and §2.4's recovery-copy steps.
- **`credentials.py` (owner of `CredentialStore`), optional tidy-up:** no change is needed any more. `sonos._RecoveryStore.save_encoded(data: bytes)` could move into `CredentialStore` under the same name and signature. `sonos.py` imports the private `credentials._dpapi` until then. `_dpapi`'s two copies (`create_string_buffer` in, `string_at` out; 0.80 and 0.55 ms at 5,000 rows) are now the recovery save's largest GIL holds. A zero-copy variant (pass the bytes' own buffer in; write the output buffer straight to the file) would leave only the join, about 0.76 ms.
- **`credentials.py`, a limit mismatch:** `CredentialStore.load` refuses files over 2,000,000 bytes, but a recovery copy of about 2,300 rows or more is larger. `queue-recovery.bin` is written, never read by the app, so nothing breaks today. A future reader would get "could not be read".
- **Stage and runtime (G1-5):**
  - On this PC, plain Python work on another thread already delays a waiting thread by about 2 ms at p95 (the 1 ms switch interval, rounded up to the timer tick). A sub-1.5 ms C call is indistinguishable from that on the probe.
  - One side observation, from a scratch run outside the bench with a million extra live objects: one garbage-collector pass held the GIL for 67 ms. It was seen once and not measured systematically. If the stage's input-path figures show rare long stalls, `gc.freeze()` after startup is worth measuring.
- **Runtime:** `read_state()` stays as it is. The adapter's `reuse_context_s` is not needed.
- **Hardware window, supervised live checks:**
  - A `/v1/me/library/albums/{id}/tracks?include=catalog&limit=50` and a playlist `/tracks` page answer 50 rows with `next` at `offset=50`.
  - W5: time the resolve of a 100-track playlist.
  - Save one real body of each kind (a 50-id `catalog_songs` answer, a 50-row tracks page, a 100-row Browse envelope) to a private folder, and run the bench with `--recorded` to confirm the per-100 KB rates. Do not commit the bodies: they hold library data.
