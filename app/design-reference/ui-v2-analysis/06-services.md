# 06 · Services feasibility: Sonos and Apple Music for the master design

Date: 2026-09-25. Read-only desk study.
- No Sonos call and no Apple Music call was made, no serial or COM port was opened, and the companion was not run.
- `credentials.bin`, `settings.json` and the recovery store were not opened. Only code in `credentials.py` was read.
- Evidence comes from: the companion source; the installed SoCo 0.31.2 in `.venv/Lib/site-packages/soco` (`__init__.py:20`); two existing diagnostics captures from 2026-09-22; and public documentation.
- Paths are relative to `app/` unless they start with `soco/` (= `.venv/Lib/site-packages/soco/`) or are URLs.
- Design sources: `design-reference/design_handoff_nano_d_master/` is abbreviated **M/**. Precedence is README > specs/01 > … (M/README.md:15-21).
- Earlier desk checks in this folder go deeper on single topics, and this file re-verifies and consolidates them: `check-play-next.md`, `check-seek.md`, `check-like.md`, `research-apple-music-play-next.md`. Where they disagree with this file, the source citations here were re-read on 2026-09-25.

Verdict words: **works** (supported by public API and existing code) · **works with caveats** (supported, with named limits or a live confirmation still owed) · **not possible** (no public API, or blocked by the platform).

---

## 0. Summary

| # | Design feature | Verdict | Mechanism | Main caveats |
|---|---|---|---|---|
| 1 | **Play next** (Recently Added, button 3; "inserts the album after the current song, queue kept", M/specs/01:76) | **Works with caveats** | Same Apple Music share-link URI and DIDL the companion already sends, with `DesiredFirstTrackNumberEnqueued = P+1+i` per song (P = current queue row). **Not** `EnqueueAsNext=1`. | Only while the queue is the source (`x-rincon-queue:`). Shuffle on means the play order is random: refuse, or use companion shuffle (§3). An album is N calls with no transaction. Race at a song boundary. Positional insert on this household is not yet proven live. |
| 2 | **Seek** (Tracks, button 3; `Seek(REL_TIME)` 250 ms after the last detent, M/README.md:225) | **Works with caveats** | `avTransport.Seek(Unit=REL_TIME, Target=H:MM:SS)` on the group coordinator. Position and duration come from `GetPositionInfo` (`RelTime`, `TrackDuration`). | The capability flag is `SeekTime`, not `Seek`. Whole-second precision. Queue tracks only: radio, AirPlay, line-in and TV cannot seek. The seek must be confirmed by polling. Clamp below the duration, or Sonos skips to the next track. |
| 3 | **Shuffle** (Up next, button 2; "reorders only the tracks after the one now playing. Turning it off restores album order and keeps the current track", M/specs/01:220) | **Native Sonos shuffle: does not meet the rule exactly. Companion-side reorder: works with caveats.** | Native: `SetPlayMode` `NORMAL↔SHUFFLE_NOREPEAT`, `REPEAT_ALL↔SHUFFLE`, `REPEAT_ONE↔SHUFFLE_REPEAT_ONE`. Exact rule: keep `NORMAL`/`REPEAT_*` and physically permute rows P+1..T with `ReorderTracksInQueue`, remembering the original order to restore. | Native shuffle picks from the whole queue, and whether UPnP exposes its order is undocumented. Reordering costs about 2 SOAP calls per moved row, so it needs a size cap. Other controllers see a reordered queue with shuffle "off". |
| 4 | **Up next data** (title, artist, album, art, position, now playing, played/upcoming) | **Works with caveats** | `ContentDirectory.Browse(Q:0)` via `get_queue(start, n)` gives title, creator, album, `albumArtURI`, URI, duration and `update_id`/`total_matches`. `GetPositionInfo.Track` gives the now-playing row. | No track numbers, no container or playlist name, and no year. Art is a speaker-proxied `/getaa` URL of unknown size. Up to 1,000 rows per Browse per the docs; the companion pages at 100. "Played" is inferable only in non-shuffle modes. |
| 5a | **Like** (Up next, button 3; `PUT /v1/me/ratings/songs/{id}`, M/README.md:226) | **Works with caveats** | The existing developer JWT plus Music-User-Token. The song id comes from the queue row URI (`_song_id`, `sonos.py:63-68`). Un-like is `DELETE`. | Apple never says rating 1 = the Music app's "Favorite" (strongly implied; live check). Never send -1 (that is "Suggest Less"). Rows from other services or library-only rows cannot be liked. The consent copy promises no library changes (`credentials.py:245`). |
| 5b | **Favourite playlists** (explorer tab 3; "favourited or pinned playlists", M/README.md:227) | **Favourited: works with caveats. Pinned: not possible.** | `GET /v1/me/library/playlists` (paged), keeping `attributes.inFavorites == true`, or a batch `GET /v1/me/ratings/library-playlists?ids=…` keeping value 1. | Whether `inFavorites` is populated is unverified (live read-only check). Pins exist only in private Apple endpoints. Smart playlists (incl. the auto "Favorite Songs") are reportedly not listed. Playlist meta `{n} songs · {duration}` needs the track list. |
| 5c | **Track lists and 600 px artwork** | **Works** | Library album tracks (300 per page), library playlist tracks (100 per page), catalog songs by id (≤ 300 ids per request). Artwork template `{w}x{h}` expanded to 600 by the existing `apple_artwork_url(…, size)`. | Clamp to `artwork.width/height`. Library playlists without custom art need the 2 × 2 mosaic from track covers. |
| 5 fallback | **Play next for the highlighted Up next row** (M/README.md:226) | **Works** (no Apple call) | Upcoming row: `ReorderTracksInQueue(row → P+1)`. Played row: re-insert its own share link at P+1. | Same queue-source and shuffle gates as #1. |
| 6 | **Album queue vs playlist queue** (row layout, left-column context) | **Works with caveats** | Primary: a companion-side provenance ledger written when `play_items` or Play next succeeds, keyed by the queue's song-id sequence. Fallback: a heuristic (all rows share album and artist, so it is an album). | The Sonos queue carries no container, playlist name or track number. A queue built elsewhere can only be classified heuristically and has no playlist name. |

**Correction to the handoff.** M/README.md:224 and M/specs/01:221 name `EnqueueAsNext` as the "insert after the current track" control.
- SoCo documents it as effective **only in shuffle** (`soco/core.py:2375-2376`, `soco/plugins/sharelink.py:227-228`).
- Sonos inserts "prior to the specified `DesiredFirstTrackNumberEnqueued`" in NORMAL mode (svrooij AVTransport).
- Suggested wording: "`AddURIToQueue` per song with `DesiredFirstTrackNumberEnqueued = current playlist_position + 1 + i` (`EnqueueAsNext` = 0; it only affects shuffle). Offered only while the Sonos queue is the source; see Shuffle."

---

## 1. Play next

### 1.1 Design intent
- **Button map:** Recently Added, button 3 = **Play next (queue kept)**; button 4 = Play (replaces queue) (M/README.md:75; M/specs/01:76).
- **Up next rows:** "Albums added with Play next show their own cover in each row" (M/README.md:193). "rows from another album show their own cover and `artist · album`" (M/specs/01:221).
- **Feedback:**
  - the knob meta shows `Queued next` for 1.5 s;
  - the toast reads `Queued next · {album}`;
  - a warm Sweep runs clockwise (M/specs/01:221).
  - In the prototype, `meta: Date.now() - s.queuedAt < 1500 ? 'Queued next' : …` (`M/prototypes/Browse and Snap.dc.html:964`) and `flash('Queued next · ' + ALB[i].t)` (`:783`).
- **Prototype semantics** (`Browse and Snap.dc.html:776-784`): the whole album is spliced in directly after `qNow` (`order = qOrder.slice(0, qNow+1).concat(idx, qOrder.slice(qNow+1))`). Everything else is kept.
- **Acceptance:** "Play next inserts the album after the current song; Up next shows those rows with their own covers" (M/README.md:238).
- **Integration note to verify:** "Sonos `AddURIToQueue` with `EnqueueAsNext=1`, inserting after the current track. Confirm it works with the Apple Music service on Sonos." (M/README.md:224).

### 1.2 How the companion queues Apple Music today (exact)

**Resolution** (`control_center/apple_music.py`)
- Recently Added resource types map to kinds:
  - `library-albums` → `album`
  - `library-playlists` → `playlist`
  - `library-songs` → `song` (`:251`)
- `resolve(item)` (`:356-383`):
  - Albums and playlists are fetched through `/v1/me/library/{albums|playlists}/{id}/tracks` (`:366-368`, paged by `_collection`, `:282-294`).
  - The count is checked against `trackCount` (`:369-371`).
  - Every library track must map to **exactly one catalog song** (`_catalog_song`, `:305-328`).
  - Order and duplicates are preserved (`:377`).
- Output per track: `{"title", "artist", "catalog_id", "url", "library_id"}` (`:380-382`).
  - `url` is always `https://music.apple.com/{sf}/album/{slug}/{albumId}?i={songId}`, taken from Apple's own song URL or the related album URL.
  - It "never invent[s] an album ID" (`:330-354`, comment `:338-339`).
- **Albums and playlists both become a flat list of catalog songs.** No container id ever reaches Sonos. This is deliberate: "No title search or whole-catalog-album substitution is used" (`:3-5`).

**Enqueue** (`control_center/sonos.py`, `play_items`, `:351-451`)
- **Validation.** Every item must match `https://music.apple.com/[a-z]{2}/album/<slug>/<digits>?i=<catalog_id>` (`:355-362`), or it raises `Every track needs a verified Apple Music song link before playback.`
- **Per song:** `plugin.add_share_link_to_queue(item["url"], position=0, dc_title=escape(title), timeout=self.timeout)` (`:388-389`), i.e. **append**. `plugin` is SoCo's `ShareLinkPlugin` (`:99`, `:107`, `:378`).
- **Checks after each song** (`:390-394`):
  - the return value is `before.total + 1`;
  - the total grew by 1;
  - the old rows are unchanged (`_signature` = title + resource URIs, `:58-60`);
  - the new last row's song id equals `catalog_id` (`_song_id` = regex `song[:/](\d+)(?:\D|$)` on the unquoted resource URI, `:63-68`).
- **Replacement and start:**
  - `RemoveTrackRangeFromQueue(InstanceID=0, UpdateID=<verified>, StartingIndex=1, NumberOfTracks=old_total)` (`:344-349`, `:405`)
  - then `SetAVTransportURI(x-rincon-queue:{uid}#0)`, `Seek(TRACK_NR, 1)` and `Play` (`:413-419`).

**What SoCo sends for each song** (`soco/plugins/sharelink.py`)
- **Canonical form.** `AppleMusicShare.canonical_uri`: `…/album/<slug>/<albumId>?i=<songId>` becomes `song:<songId>` (`:155-161`). The album id in the link is not sent.
- **Encoding.** `extract` replaces `:` with `%3a` (`:183-187`).
- **Magic for `song`:** prefix `""`, key `10032020`, class `object.item.audioItem.musicTrack` (`:59-63`). Service number `52231` (`:180-181`), which is Apple Music sid 204 × 256 + 7.
- **SOAP call:**
  - `EnqueuedURI = "song%3a<songId>"`
  - `EnqueuedURIMetaData` = `<DIDL-Lite …><item id="10032020song%3a<songId>" parentID="-1" restricted="true"><dc:title>{escaped title}</dc:title><upnp:class>object.item.audioItem.musicTrack</upnp:class><desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">SA_RINCON52231_X_#Svc52231-0-Token</desc></item></DIDL-Lite>` (`:246-264`)
  - `AddURIToQueue(InstanceID=0, EnqueuedURI, EnqueuedURIMetaData, DesiredFirstTrackNumberEnqueued=position, EnqueueAsNext=int(as_next))` (`:267-276`)
- **Return value.** Only `int(FirstTrackNumberEnqueued)` (`:278-279`).
- **Account.** No account serial (`sn`) is pinned, so Sonos uses its linked Apple Music account.
- **Resolved rows.** Once Sonos resolves the song, queue rows look like `x-sonos-http:song%3a<id>.mp4?sid=204&flags=8224&sn=N` ([SoCo #812](https://github.com/SoCo/SoCo/issues/812)). The unit-test fake mirrors this (`tests/test_cc_music.py:203-207`).

**Live evidence on this household (2026-09-22).**
- The quiet probe appended one Apple Music song with the same call (`tools/quiet_sonos_probe.py:210-217`, `position=0`).
- It verified the row's song id and played it muted: `single_song_staged: ok`, `exact_song_playing_while_muted: ok` (`diagnostics/quiet-sonos-probe.json:24-33`).
- The device's own SCPD capture shows `AddURIToQueue` in-args `InstanceID, EnqueuedURI, EnqueuedURIMetaData, DesiredFirstTrackNumberEnqueued, EnqueueAsNext` and out-args `FirstTrackNumberEnqueued, NumTracksAdded, NewQueueLength` (`diagnostics/sonos-readiness.json:22-37`).

### 1.3 SoCo API surface (installed 0.31.2)

| API | Exact signature / behaviour | Source |
|---|---|---|
| `SoCo.add_uri_to_queue(uri, position=0, as_next=False, **kwargs)` | Wraps `uri` in a bare `DidlObject` (`protocol_info="x-rincon-playlist:*:*:*"`, empty title) and calls `add_to_queue`. `@only_on_master`. | `soco/core.py:2354-2364` |
| `SoCo.add_to_queue(queueable_item, position=0, as_next=False, **kwargs)` | `position`: "The index (1-based) at which the URI should be added. Default is 0 (add URI at the end of the queue)". `as_next`: "Whether this URI should be played as the next track in shuffle mode. This only works if `play_mode=SHUFFLE`." Returns `int(FirstTrackNumberEnqueued)`. | `soco/core.py:2366-2393` (quotes `:2373-2376`) |
| `SoCo.add_multiple_to_queue(items, container=None, **kwargs)` | `AddMultipleURIsToQueue` in chunks of 16 ("we can only add 16 items", `:2410`). **Hard-codes** `UpdateID=0`, `DesiredFirstTrackNumberEnqueued=0`, `EnqueueAsNext=0` (`:2419`, `:2425-2426`), so it cannot insert at a position. Returns nothing. | `soco/core.py:2395-2429` |
| `ShareLinkPlugin.add_share_link_to_queue(uri, position=0, as_next=False, **kwargs)` | Same `position`/`as_next` semantics (docstring `:225-228`). `dc_title` kwarg; the remaining kwargs (e.g. `timeout`) go to the SOAP call. Returns `int(FirstTrackNumberEnqueued)`. On `SoCoException` it tries the next matching service, then re-raises (`:280-285`). | `soco/plugins/sharelink.py:216-285` |
| Raw `coordinator.avTransport.AddURIToQueue([...])` | `Service.__getattr__` dispatches any action (`soco/services.py:192-220`). `send_command` returns **all** out-args as a dict (`:501-510`, `unwrap_arguments` at `:506`), so a direct call yields `FirstTrackNumberEnqueued`, `NumTracksAdded` and `NewQueueLength`. | `soco/services.py` |
| `PlexPlugin.add_to_queue` (reference pattern) | Inserts a list at a position by adding **each item in reverse order at the same position** (`:135-150`). Note for shuffle: "Enqueuing multi-track items like albums or playlists will select one track randomly as the next item and shuffle the remaining tracks throughout the queue." | `soco/plugins/plex.py:111-153` (note `:124-126`) |
| `get_current_track_info()["playlist_position"]` | `GetPositionInfo.Track`: the 1-based queue row of the current track. | `soco/core.py:2023-2034` |
| `get_current_media_info()["uri"]` | `GetMediaInfo.CurrentURI`; `x-rincon-queue:<uid>#0` while the queue is the source. | `soco/core.py:2136-2159` |
| `play_mode` | `GetTransportSettings.PlayMode`. | `soco/core.py:570-592` |

### 1.4 Sonos semantics: `EnqueueAsNext` versus an explicit position

| Source | What it says | Weight |
|---|---|---|
| SoCo docstrings (installed) | `as_next` = "played as the next track **in shuffle mode**. This only works if play_mode=SHUFFLE"; `position` = 1-based insert index, 0 = end. | High (library maintainers; `core.py:2373-2376`, `sharelink.py:225-228`) |
| svrooij Sonos API docs, AVTransport `AddURIToQueue` | `DesiredFirstTrackNumberEnqueued`: "use `0` to add at the end or `1` to insert at the beginning". Remark: "**In NORMAL play mode the songs are added prior to the specified `DesiredFirstTrackNumberEnqueued`.**" `EnqueueAsNext`: boolean, with no semantics given. | High (reverse-engineered reference; https://sonos.svrooij.io/services/av-transport) |
| go-sonos `AddURIToQueueIn` comments | `DesiredFirstTrackNumberEnqueued`: "0 to insert the new item at the end of the queue. If non-zero the new track will be inserted at this location". `EnqueueAsNext`: "???? (possibly unsupported)". `NumTracksAdded`: "(always 1)" for a single track. | Medium (https://raw.githubusercontent.com/ianr0bkny/go-sonos/master/upnp/AVTransport.go) |
| node-sonos `Sonos.prototype.queue(options, positionInQueue = 0)` | **Always** sends `EnqueueAsNext: 1`. Its doc says position "defaults to end of queue, 0 to explicitly set end of queue". So `EnqueueAsNext=1` with position 0 **appends** in normal play. | High as behavioural evidence (https://raw.githubusercontent.com/bencevans/node-sonos/master/lib/sonos.js) |
| Home Assistant Sonos, `enqueue: next` | `pos = (self.media.queue_position or 0) + 1`, then `share_link.add_share_link_to_queue(media_id, position=pos, timeout=LONG_SERVICE_TIMEOUT, …)` (≈ lines 733-745). The same `pos` is used for `soco.add_to_queue` (≈ 690-697) and `add_uri_to_queue` (≈ 716-720). **`as_next` is never set.** This is the same plugin and call as the companion, in production for Apple Music share links. | High (https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/sonos/media_player.py, fetched 2026-09-25) |
| node-sonos-http-api `applemusic/next/…` | `nextTrackNo = player.coordinator.state.trackNo + 1; addURIToQueue(uri, metadata, true, nextTrackNo)`, i.e. position +1 **and** `EnqueueAsNext=1`. | Medium (https://raw.githubusercontent.com/jishi/node-sonos-http-api/master/lib/actions/appleMusic.js) |
| sonos2mqtt docs | "EnqueueAsNext: true" controls whether an item plays after the current track. Its example uses `DesiredFirstTrackNumberEnqueued: 0`. No test evidence is given. | Low; contradicts node-sonos (https://sonos2mqtt.svrooij.io/control/playback.html) |
| Sonos support | Play Next: "Add the track(s) to the queue after the current track and play them next." | Defines the target behaviour (https://support.sonos.com/en-us/article/add-tracks-to-the-queue) |

**Conclusion.**
- In `NORMAL`, `REPEAT_ALL` and `REPEAT_ONE`, **the position does the work**: `DesiredFirstTrackNumberEnqueued = P + 1` puts the song directly after the current row P and pushes later rows down.
- `EnqueueAsNext=1` alone does not move an item "next" in normal play: node-sonos appends with it on every call. At best it is harmless together with a position, which is what node-sonos-http-api sends.
- `EnqueueAsNext` only matters in shuffle, where per SoCo's Plex note a multi-track item gets **one** random track made next and the rest scattered.
- **The design's `EnqueueAsNext=1` should be replaced by an explicit position** (see §0).

### 1.5 Can it be done with the companion's existing URI and metadata style? **Yes.**
- Play next is the existing `add_share_link_to_queue` call with `position = P + 1 + i` instead of `0`.
- It uses the same validated `album/…?i=<songId>` URL, the same `dc_title`, the same `song%3a<id>` URI and DIDL, and the same `_song_id` verification.
- There is no new service id, token or metadata form. Home Assistant uses exactly this for "enqueue next" with share links (§1.4).

**Exact call sequence** (a new `SonosAdapter.play_next(items, expected_group_revision, expected_track_id)`, inside `self._lock` like every adapter method, `sonos.py:90`). Nothing is removed except its own verified block on rollback.

```text
0  validate every item exactly like play_items (sonos.py:355-362); N = len(items); songs = [catalog_id…]
1  ctx = _assert_group(rev); c = ctx[1].coordinator                                   # sonos.py:147-151
2  media = c.get_current_media_info()["uri"]
   if not media.startswith("x-rincon-queue:")            -> refuse NOT_QUEUE          # same gate as sonos.py:161
3  mode = c.play_mode                                                                # GetTransportSettings
   if mode in {"SHUFFLE","SHUFFLE_NOREPEAT","SHUFFLE_REPEAT_ONE"} -> refuse SHUFFLE (see 1.6)
4  track = c.get_current_track_info()
   if expected_track_id and _track_id(track) != expected_track_id -> TrackChanged    # sonos.py:153-156
5  head = c.get_queue(0, 1); T0 = int(head.total_matches); U0 = str(head.update_id)
   P = int(track["playlist_position"] or 0)
   if T0 == 0 or not 1 <= P <= T0                        -> refuse NOTHING_PLAYING
   if T0 + N > MAX_QUEUE (5000, sonos.py:72)             -> refuse FULL
6  anchor = _signature(c.get_queue(P-1, 1)[0])            # the current row itself
7  plugin = ShareLinkPlugin(c)                            # sonos.py:378
   for i, item in enumerate(items):                       # forward order, consecutive rows
       want = P + 1 + i
       got = plugin.add_share_link_to_queue(item["url"], position=want,
                                            dc_title=escape(item["title"]), timeout=self.timeout)
       if got != want: stop -> rollback
       # an ambiguous timeout: read c.get_queue(want-1, 1); continue only if _song_id(row) == songs[i]
8  S = c.get_queue(P-1, N+2)   (page at 100 if N > 98)
   verify: int(S.total_matches) == T0 + N
           _signature(S[0]) == anchor                     # current song still directly before the block
           [_song_id(x) for x in S[1:1+N]] == songs       # exact order, duplicates kept
           str(S.update_id) != U0
9  now = int(c.get_current_track_info()["playlist_position"])
   ok if now == P  or  P+1 <= now <= P+N                  # the song ended mid-insert: playback moved INTO the block
   bad if now > P+N                                       # the song ended before the 1st insert; the block is behind it
10 return _state(_assert_group(rev))                      # the knob then shows "Queued next"
```

**Current song is the last row (P == T0).**
- `want = T0 + 1 + i` is exactly "end of queue".
- Passing `want` works if Sonos accepts `length + 1` as an insert position (go-sonos says ReorderTracksInQueue needs `length + 1` to reach the end).
- Passing `0` (end) is the guaranteed equivalent: use `desired = 0 if want > T0 + i else want`, and still expect `got == want`.

**Why forward order at consecutive positions**, rather than Plex-style reverse inserts at one position:
- The partial state is always "the first k songs of the album, in order, right after the current song".
- If the current song ends mid-sequence, playback moves into song 1 of the block and the rest still follow in order.

**Rollback.** This applies to any failed check after at least one insert. Remove with the guarded helper `RemoveTrackRangeFromQueue(InstanceID=0, UpdateID=<just read>, StartingIndex=P+1, NumberOfTracks=k)` (`sonos.py:344-349`), but **only if all of these hold**:
- rows P+1..P+k are exactly the k songs this call inserted;
- `anchor` is intact;
- the current row is not inside the block.

Otherwise, report a partial result, with the same honesty as `sonos.py:447-451`.

**`as_next`.** Leave it `False` (`EnqueueAsNext=0`). That is Home Assistant's proven call, and the companion's existing call with only `position` changed.

### 1.6 What happens with shuffle on
- Sonos `SHUFFLE*` modes pick the play order themselves. A block physically inserted at P+1 is *in* the queue, but **nothing guarantees it plays next or in order**. The design's "album after the current song" cannot be honoured.
- `EnqueueAsNext=1` in shuffle makes at most **one random track** of a multi-track item next and "shuffle[s] the remaining tracks throughout the queue" (`soco/plugins/plex.py:124-126`).
  - That note is written for container items (albums or playlists as one URI).
  - For the companion's per-song inserts, the likely effect is that the last-inserted song (or each song in turn) becomes "next" and the others scatter. This is **unverified**.
- **Recommendation:**
  - In native Sonos shuffle, refuse Play next with `Shuffle is on · turn it off to play next`. The copy is a proposal; the design has none.
  - If the build adopts **companion-side shuffle** (§3.4), the Sonos play mode stays `NORMAL`/`REPEAT_*`, so Play next is exact even while "Shuffle on" is shown.
    - The prototype's intent is that a Play-next block inserted while shuffled sits right after the current track in play order (`Browse and Snap.dc.html:778`, the splice happens on `qOrder`).
    - Companion shuffle reproduces that literally.

### 1.7 How to confirm success
1. **Per call:** the return value `FirstTrackNumberEnqueued == want` (`sharelink.py:278-279`).
   - For stronger checks, call `coordinator.avTransport.AddURIToQueue` directly with the identical `EnqueuedURI`/`EnqueuedURIMetaData` built exactly as `sharelink.py:243-264` does.
   - Then also check `NumTracksAdded == 1` and `NewQueueLength == T0 + i + 1`. `send_command` returns all out-args (`soco/services.py:506`), and the device exposes them (`diagnostics/sonos-readiness.json:32-36`).
2. **After the loop, one slice read** (step 8 above):
   - total = T0 + N;
   - the anchor row is unchanged;
   - rows P+1..P+N have `_song_id` == `songs` in order;
   - the `update_id` changed.
3. **Transport untouched:**
   - `GetTransportInfo` state is unchanged (no interruption);
   - the current row is P, or has moved into the block (step 9).
4. **Only then:**
   - the knob shows `Queued next` for 1.5 s;
   - the toast `Queued next · {album}`;
   - the warm Sweep (M/specs/01:221; the LED moment "Sweep | Play next", M/README.md:175).

   While waiting, show the existing pending treatment. The working comet is "waiting on Sonos or Windows" (M/README.md:163).

### 1.8 Failure modes

| Condition | Detection | Suggested knob / toast (proposal) |
|---|---|---|
| Source is not the queue: radio (incl. Apple Music stations), AirPlay, Spotify Connect, line-in, TV | Media URI not `x-rincon-queue:`. Classes per `soco/core.py:3082-3097`: `x-sonosapi-radio:`, `x-sonosapi-hls:`, `x-sonosapi-stream:`, `x-rincon-mp3radio:`, `aac:`, `hls-radio:`, `x-sonos-http:sonos` = radio; `x-rincon-stream:` = line-in; `x-sonos-htastream:` = TV; `x-sonos-vli:…,airplay:` / `,spotify:` | `Not playing from the queue · use Play` |
| Empty queue / no current row | `T0 == 0` or P out of `1..T0` | `Nothing playing · use Play` (Play replaces the queue, which is equivalent here) |
| Sonos shuffle on | `play_mode` in `SHUFFLE*` | `Shuffle is on · turn it off to play next` (unless companion shuffle, §3.4) |
| Repeat one | `REPEAT_ONE` | Insert normally. Note that the current song repeats until the user skips; toast `Queued next · repeat one is on` |
| Song changed before the first insert | step-4 track guard, or `now > P+N` at step 9 | Automatic rollback of its own block, then `Song changed · try again` |
| Sonos rejects the share link | `SoCoUPnPException` on call 1 (UPnP 800/402/804). Share-link enqueue on S2 broke once with UPnP 800 until a Sonos firmware fix ([SoCo #969](https://github.com/SoCo/SoCo/issues/969), Dec 2024) | `Sonos refused this album · nothing queued` |
| Failure mid-album, rollback possible | slice check | Remove own block; `Couldn't queue {album} · nothing added` |
| Failure mid-album, rollback impossible (foreign edit, current row inside block) | slice mismatch | `Partly queued · check the Sonos queue` |
| Group changed | `_assert_group` (`sonos.py:147-151`) | Existing text: `The Sonos group changed. Review the displayed group before adjusting it.` |
| Apple resolution failed | `MusicUnavailable` from `resolve` | Existing messages ending in `Nothing was queued.` (`apple_music.py:287-375`) |
| Apple sign-in expired | 401/403 (`apple_music.py:109-110`) | Existing recovery state "Apple Music sign-in expired / Renew on your PC" (M/specs/03:136) |

### 1.9 Cost and latency
- **Apple resolution (existing path, per item):** 1 or more pages of `/tracks`, **plus one `/v1/me/library/songs/{id}/catalog` request per track** whenever the tracks response carries no `relationships.catalog` (`apple_music.py:308-313`).
  - Today `resolve` sends no `include` parameter (`:368`), so this is the normal case.
  - Add `/v1/catalog/{sf}/songs/{id}` when the catalog song lacks `url` (`:321-325`), and `/songs/{id}/albums` when the URL is not already in album form (`:340-350`).
  - **A 12-track album is ≈ 13–37 Apple requests before Sonos is touched.**
  - Optimisation to verify: `?include=catalog` on the tracks request, which the code already consumes at `:309-311`.
  - Apple publishes no rate number; excess gives 429, which "resolves itself shortly after the request rate has reduced" ([Generating developer tokens](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens)). The companion maps 429 to `Apple Music is temporarily limiting requests. Try again shortly.` (`apple_music.py:111-112`).
- **Sonos:**
  - N × `AddURIToQueue` plus about 5 small reads.
  - Do **not** copy `play_items`' full-queue re-read before and after every song (`sonos.py:384`, `:390`, which is O(N × queue pages)). Insertion is non-destructive, so the per-call return value plus one slice check is sufficient.
  - Per-call latency on this system is unmeasured; measure it in the live check (§8).
- **Long playlists:** `MAX_TRACKS = 5000` (`apple_music.py:30`). Cap Play next at a size (proposal: 100 songs) or show progress (`Queueing 12 / 80`, proposal). `Queued next` must only follow verification.

### 1.10 Alternatives considered
- **One call per album container.**
  - `x-rincon-cpcontainer:1004206calbum%3a<albumId>` (`sharelink.py:39-43`, `:163-166`).
  - Sonos expands it; `NumTracksAdded` reports the count; the position places the block.
  - **Rejected as default:** it plays the **catalog** album, which can differ from the user's **library** album (edition, a subset of tracks). The module forbids that substitution (`apple_music.py:3-5`).
  - Private library playlists (`p.…` ids) have no share-link form: the SoCo regex needs `pl.` (`sharelink.py:172-176`).
  - Possible later optimisation only when the resolved song list provably equals the catalog album.
- **`AddMultipleURIsToQueue`:** at most 16 URIs per call (`soco/core.py:2410`). SoCo's wrapper cannot set a position (`:2425-2426`). It is untested with the bare `song%3a` form.

---

## 2. Seek

### 2.1 Availability and constraints
- **Action.** AVTransport `Seek(InstanceID=0, Unit=REL_TIME, Target="H:MM:SS")` on the **group coordinator**.
  - Units: `TRACK_NR` / `REL_TIME` / `TIME_DELTA`.
  - Target: "`hh:mm:ss` for `REL_TIME` or `+/-hh:mm:ss` for `TIME_DELTA`".
  - "Returns error code 701 in case that content does not support Seek or send to non-coordinator" ([svrooij AVTransport](https://sonos.svrooij.io/services/av-transport)).
- **SoCo wrapper:** `seek(position=None, track=None)`, `@only_on_master` (`soco/core.py:875-924`).
  - `position` must match `^[0-9][0-9]?:[0-9][0-9]:[0-9][0-9]$` (`:919-920`).
  - It sends `("Unit","REL_TIME"),("Target",position)` (`:922-924`).
  - "If speaker is already playing it will continue to play after seek. If paused it will remain paused." (`:906-907`)
  - Raises UPnP 701 "if seeking is not supported" and 711 "if the target is invalid" (`:894-897`).
  - The wrapper takes no `timeout`, so call `coordinator.avTransport.Seek([...], timeout=self.timeout)` as `sonos.py:297` already does for `TRACK_NR`.
- **Capability flag.** `available_actions` returns the part after the last `_` of `X_DLNA_SeekTime`, so the flag is **`SeekTime`** (`soco/core.py:2258-2273`). The companion's own parser gives the same (`sonos.py:181-182`). **Test `"SeekTime" in actions`; `"Seek"` would never match.**
- **This household.** The 2026-09-22 capture with an Apple Music queue advertises `Set, Stop, Pause, Play, SeekTime, SeekTrackNr` (`diagnostics/sonos-readiness.json:83-90`). The transport was `STOPPED` (`:17`), so a PLAYING/PAUSED capture is still owed.
- **Queue versus radio versus Apple Music tracks:**

| Source | Seek? | Why |
|---|---|---|
| Apple Music songs in the local queue (`x-rincon-queue:…#0`, rows `x-sonos-http:song%3a….mp4`) | **Yes** | On-demand HTTP stream. SoCo's `Snapshot.restore()` itself REL_TIME-seeks only for a local queue (`soco/snapshot.py:195-208`). Sonos implements seeking via HTTP range requests ([Playback on Sonos](https://docs.sonos.com/docs/playback-on-sonos.md)). |
| Apple Music radio / stations, any radio | **No** | `TrackDuration` is `0:00:00` for radio (`soco/core.py:2103-2105`). "Sonos products don't use the queue when playing music from radio services" ([Sonos](https://support.sonos.com/en-us/article/using-the-queue-in-the-sonos-app)). |
| AirPlay / Spotify Connect (`x-sonos-vli:`) | **No (from here)** | The sender owns the transport. |
| Line-in / TV | **No** | Metadata is `NOT_IMPLEMENTED` (`soco/core.py:2096-2099`). |

- **Past the end.** The Sonos Control API documents: "If this value exceeds the current track duration time, Sonos moves to the end of the current track, which results in a skip to the next track" ([playback/seek](https://docs.sonos.com/reference/playback-seek-groupid)). **Clamp the target below the duration.** The prototype clamps to `D − 1` (`Browse and Snap.dc.html:712`); `check-seek.md` §4.2 recommends `D − 3` for real playback.
- **Stale-target guard.** The same doc's `itemId`: "If included and it does not match the currently playing item, the command fails. This ensures that playback does not jump back to a track if a user starts to scrub just as the player begins to play the next item".
  - UPnP has no such parameter. The companion's equivalent is re-checking `expected_track_id` immediately before `Seek`, as `transport()` does (`sonos.py:290-296`).

### 2.2 Reading the current position and duration
- `get_current_track_info()` (`soco/core.py:2004-2134`) calls `GetPositionInfo` and returns:
  - `playlist_position` (= `Track`, the 1-based queue row)
  - `duration` (= `TrackDuration`)
  - `uri` (= `TrackURI`)
  - `position` (= `RelTime`)
  - `metadata`
  - `title`, `artist`, `album`, `album_art` (`:2027-2037`, `:2109-2132`)
- `position` and `duration` are strings like `"0:03:32"` (**whole seconds** on Sonos; the capture shows `"0:00:00"` at `diagnostics/sonos-readiness.json:19`).
- Raw `GetPositionInfo` also has `AbsTime`, `RelCount`, `AbsCount` (svrooij). SoCo drops them.
- **Called on a group member,** it returns "the last track this speaker was playing" (`:2018-2021`). The companion always reads `group.coordinator` (`sonos.py:179-180`).
- **Companion today:**
  - `_state` copies only the raw `position` string (`sonos.py:202`), and nothing uses it.
  - It does **not** copy `duration` or `playlist_position` (`sonos.py:188-202`).
  - Seek needs parsed `duration`, parsed `position`, and a monotonic read time so the LCD can extrapolate while `PLAYING`.
- **Precision and freshness.** Position is not evented; it must be polled. During `TRANSITIONING` a read can show the old clock ([HA #181315](https://github.com/home-assistant/core/issues/181315)).

### 2.3 Rate limiting and confirmation
- **No documented rate limit** for local UPnP.
- **The design's own throttle:** one `Seek(REL_TIME)` 250 ms after the last detent; exit after 3 s idle or on 3, Back or Open on screen (M/README.md:225; M/specs/01:166-167; prototype idle re-arm `Browse and Snap.dc.html:664`).
- **Implement like volume:**
  - a latest-wins intent `(target, group_revision, track_id)`, as in `controller.py:329-342` and `:498-513`;
  - one seek in flight;
  - the runtime reads the current intent when the job starts (`runtime.py:1103-1117`);
  - minimum spacing about 100 ms (`runtime.py:1106`).
- **All Sonos I/O is already serialized** on one worker thread (`runtime.py:161`). The 1 Hz state poll is suppressed while a command is pending (`controller.py:680-682`).
- **Confirm by polling, never replay.** UPnP Seek goes to `TRANSITIONING` and returns immediately. Poll `GetTransportInfo` and `GetPositionInfo` about every 100 ms for ≤ 3 s, until the state leaves `TRANSITIONING` and `RelTime` is near the target.
- **Error codes** (`soco/services.py:911-935`; svrooij):

  | Code | Meaning |
  |---|---|
  | 701 | Transition not available |
  | 710 | Seek mode not supported |
  | 711 | Illegal seek target |
  | 718 | Invalid InstanceID |
  | 800 | Command not supported or not a coordinator |

- **Full build recipe** (bounds, detent mapping `t(n) = clamp(p + 5·(n − n0), 0, T_end)`, state additions, live check): `check-seek.md` §4-§5.

**Verdict: works with caveats** (queue tracks only; confirm by polling; clamp below the duration).

---

## 3. Shuffle

### 3.1 Design rule
- "**Shuffle** reorders only the tracks after the one now playing. Turning it off restores album order and keeps the current track." (M/specs/01:220; M/README.md:195)
- **Prototype, `toggleShuffle`** (`Browse and Snap.dc.html:682-692`):
  - **On:** `head = qOrder.slice(0, qNow+1)` (played rows and the current row keep their order). `rest = qOrder.slice(qNow+1)` is Fisher-Yates shuffled. `order = head.concat(rest)`, `qNow` unchanged.
  - **Off:** `order = [0..n-1]` (the natural queue order), and `qNow = curIdx` (the current track's natural index), so the current track keeps playing.
  - The focus moves to `min(n-1, now+1)`.
  - Toasts: `Shuffle on · up next reshuffled` / `Shuffle off · album order` (`:691`).
  - Scatter LED moment (`:687`; M/specs/01:156).
- **Side effects of "off" in the prototype:**
  - Rows that were played while shuffled and lie *after* the current track in natural order become "upcoming" again.
  - Rows added with Play next go back to their append position (their `queue` index), so **"off" silently undoes a Play next placement**. That is a prototype artifact the build must decide on (§3.5).
- **Knob:** the Tracks meta appends ` · shuffle` (`Browse and Snap.dc.html:952`; M/README.md:120). Up next shows `Shuffle on` / `In order` (`:1080`), and the button-2 hint reads `Shuffle` / `Shuffle off` (`:1081`).
- `shufflePlay` (`:785-792`) exists but no button calls it.

### 3.2 Sonos play modes (native shuffle)
- **Values:**

  | Play mode | (shuffle, repeat) |
  |---|---|
  | `NORMAL` | (False, False) |
  | `SHUFFLE_NOREPEAT` | (True, False) |
  | `SHUFFLE` | (True, True) |
  | `REPEAT_ALL` | (False, True) |
  | `SHUFFLE_REPEAT_ONE` | (True, "ONE") |
  | `REPEAT_ONE` | (False, "ONE") |

  (`soco/core.py:3058-3068`; SoCo's own note: `'SHUFFLE'` "Turns on shuffle *and* repeat. (It's strange, I know.)", `:578-579`)
- **Shuffle transitions preserve repeat** (the SoCo `shuffle` setter maps `(shuffle, repeat)`, `:611-615`):
  - `NORMAL ↔ SHUFFLE_NOREPEAT`
  - `REPEAT_ALL ↔ SHUFFLE`
  - `REPEAT_ONE ↔ SHUFFLE_REPEAT_ONE`
- **Write:** `avTransport.SetPlayMode([("InstanceID",0),("NewPlayMode",mode)])` (`soco/core.py:594-601`).
  - svrooij: "Send to non-coordinator returns error code 712. If SONOS queue is not activated returns error code 712." So shuffle is only offered while the source is the queue.
  - Confirm by reading back `GetTransportSettings.PlayMode`, as the volume write does (`sonos.py:224-234`).
- **What native shuffle does to the order is poorly documented:**
  - Sonos support: "The Shuffle function randomizes the song order when playing from the queue." ([Sonos](https://support.sonos.com/en/article/shuffle-repeat-and-crossfade-songs))
  - Since app 5.4 (2015), community reports quote the release notes: with shuffle on, "the order of the tracks in the queue changes". Turning shuffle off returns the original order, and turning it on again gives a different mix ([Sonos Community, "Request for feedback: Shuffle"](https://en.community.sonos.com/controllers-and-music-services-228995/request-for-feedback-shuffle-6517514/index8.html); release-note page https://www.sonos.com/en-us/software/release/5-4 returned 403 to the fetcher).
  - Users report the original first track "pinned" to the start of a shuffled playlist ([Sonos Community, Sept 2024](https://en.community.sonos.com/general-feedback-and-conversation-229090/sonos-implementation-of-shuffle-6904897)).
  - They also report playback reverting "to the first song in the unshuffled play list" when shuffle is set via Home Assistant ([HA Community, Feb 2026](https://community.home-assistant.io/t/sonos-shuffle-doesnt-work-well/982322)).
- **Not documented anywhere I found:**
  - whether UPnP `Browse(Q:0)` returns the shuffled order while shuffle is on;
  - whether `GetPositionInfo.Track` is then an index in shuffled or original order.

  Two hypotheses:
  - **H1:** Browse keeps the original order and `Track` is the original row. The shuffled order is internal to the player. Then Up next **cannot show** the upcoming order, and "played" cannot be derived.
  - **H2:** Browse returns the permuted order, as the app shows. Then Up next can show it, but the permutation covers the whole queue: **played rows can be reshuffled into "upcoming"**, and the current track may be moved to the top.
- **The companion already treats shuffle history as unknowable:** Previous is refused with `Previous is unavailable while shuffle history cannot be verified.` (`sonos.py:163-164`), and the demo README says "shuffle history that Sonos does not expose" (`README.md:61-63`).

### 3.3 Does native shuffle satisfy the design rule?

| Rule part | Native `SetPlayMode(SHUFFLE*)` |
|---|---|
| "reorders only the tracks after the one now playing" | **Not guaranteed.** Sonos shuffles the queue ("All songs in the queue … will shuffle", community, 2015, thread above). Already-played rows can come back. Under H1 the order is not even visible. |
| "Turning it off restores album order" | **Yes.** The queue order was never changed (H1), or Sonos restores it (H2 per the 5.4 notes). |
| "and keeps the current track" | **Probably yes.** Changing play mode does not stop the transport; playback continues sequentially from the current row. Unverified; live check. |
| Up next shows the new order landing (M/specs/01:218; the prototype's `qFade` restagger) | **H1: no. H2: yes.** |
| Play next "after the current song" while shuffled | **No** (§1.6). |
| Previous on the knob | Disabled by the existing rule (`sonos.py:163-164`). |

### 3.4 Exact rule: companion-side shuffle with `ReorderTracksInQueue`
- **Idea.** Leave Sonos in `NORMAL`/`REPEAT_ALL`/`REPEAT_ONE`, and **physically permute rows P+1..T** of the queue. The Sonos queue order then *is* the play order: Up next, Play next, Previous and Next all stay exact.
- **Action:** `ReorderTracksInQueue(InstanceID=0, StartingIndex, NumberOfTracks, InsertBefore, UpdateID)`, all `ui4` ([svrooij](https://sonos.svrooij.io/services/av-transport)).
  - go-sonos doc comment: "Move a contiguous range of tracks to a given point in the queue … @startingIndex is the first track in the range to be moved, where the first track in the queue is track 1; @numberOfTracks is the length of the range; @insertBefore set the destination position in the queue; @updateId should be 0. Note that to move tracks to the end of the queue @insertBefore must be set to the number of tracks in the queue plus 1. This method fails with 402 if @startingndex, @numberOfTracks, or @insertBefore are out of range." ([go-sonos AVTransport.go](https://raw.githubusercontent.com/ianr0bkny/go-sonos/master/upnp/AVTransport.go))
  - node-sonos exposes `reorderTracksInQueue(startingIndex, numberOfTracks, insertBefore, updateId = 0)`, so `UpdateID=0` is accepted as "unguarded".
  - SoCo has no wrapper, but the service proxy dispatches it (`soco/services.py:192-220`), exactly as the companion already calls `RemoveTrackRangeFromQueue` (`sonos.py:344-349`).
  - svrooij lists **no out-args** for ReorderTracksInQueue (unlike `RemoveTrackRangeFromQueue → NewUpdateID`). A guarded sequence therefore has to re-read `update_id` (`get_queue(0,1)`) after each move.
- **Shuffle on** (proposed `SonosAdapter.shuffle_upcoming(rev, expected_track_id)`):
  1. Gates:
     - the queue is the source;
     - `play_mode` is not already `SHUFFLE*` (if it is, see §3.5);
     - the track guard passes;
     - `U = T − P ≥ 2`.
  2. Read the full queue (`_queue`, `sonos.py:308-321`). Record `restore = {update_id_after, rows P+1..T as _signature list, P, current row signature}`. Persist it like the encrypted recovery snapshot (`sonos.py:323-342`) so a crash can restore order.
  3. Fisher-Yates over rows P+1..T.
  4. Realise the permutation with single-row moves. For `k = P+1 .. T`: find the current row `r ≥ k` of the item that belongs at `k`; if `r ≠ k`, then `ReorderTracksInQueue(StartingIndex=r, NumberOfTracks=1, InsertBefore=k, UpdateID=<fresh update_id>)`.
     - Rows ≤ P are never moved, so the current row and `playlist_position` do not change and `_track_id` stays valid.
     - At most `U − 1` moves. Fewer if you keep the longest already-ordered subsequence: `U − LIS`, about `U − 2√U` for a random permutation.
  5. Verify with one full read: rows ≤ P unchanged; rows P+1..T equal the planned permutation by `_signature`.
- **Shuffle off:** restore rows P'..T (P' = the current row now) to the recorded album order, keeping the current track playing.
  - Move **other** rows around the playing row rather than the playing row itself. Any permutation can be reached with one element held fixed, which minimises playback risk.
  - The current row index changes if rows move in front of it, so the companion's `_track_id` digest changes (`sonos.py:153-156` includes `playlist_position`). Pending commands will see `TrackChanged`, which is harmless, and the next state poll resyncs.
  - Apply the restore only if the queue still contains exactly the recorded rows: same multiset of `_signature`, and no foreign edits since `update_id_after`, or edits that are provably only the companion's own Play next blocks.
  - Otherwise refuse with `Queue changed · order kept` (proposal) and drop the restore record.
- **Cost.** About 2 SOAP calls per moved row (the move plus an `update_id` re-read) when guarded, or 1 with `UpdateID=0` and a single verification read at the end.
  - 12-track album, current = 4 → ≤ 7 moves → ≈ 14 calls.
  - 100-track playlist → ≈ 180 calls.
  - Per-call time is unmeasured. At an assumed 30–80 ms per LAN SOAP call, that is about 0.5–1 s for an album and 5–15 s for a large playlist (estimate).
  - **Cap it** (proposal: companion shuffle when `U ≤ 60`; above that, native `SetPlayMode` with Up next showing `Shuffle on · order chosen by Sonos`, if the live check proves H1).
- **Consequences:**
  - **Other controllers.** The Sonos app sees a physically reordered queue with its own shuffle indicator **off**. Turning shuffle on in the Sonos app then shuffles the permuted queue natively.
  - **Repeat-all.** After a wrap, the permuted order repeats instead of reshuffling (acceptable).
  - **Crash mid-shuffle.** The queue stays partially permuted. The persisted restore record makes "Shuffle off" still possible after restart.
  - **Queue revision churn.** Every move bumps `update_id`, so Previous's queue guard (`sonos.py:295-296`) will reject a Previous press racing the shuffle. That is intended.
  - **Unverified behaviours, for the live check:**
    - that `ReorderTracksInQueue` works on Apple Music rows;
    - that moving rows *after* the current one never interrupts playback;
    - that moving rows *before* the current one (restore) keeps playing the same song and updates `Track`.

### 3.5 Recommendation
1. **Read-only live check first** (§8, R3): the user toggles shuffle in the Sonos app while the companion only reads `GetTransportSettings`, `GetPositionInfo.Track` and `Browse(Q:0)` before and after. This settles H1 or H2 in about 6 reads.
2. **If H2**, and native shuffle keeps played rows at the top: native `SetPlayMode` is enough for the design and costs one call. Up next re-reads the queue after the toggle.
3. **Otherwise**, use companion-side shuffle (§3.4) for queues up to the cap, and native shuffle above it (with honest copy).
4. **Design decisions to confirm:**
   - (a) What "off" does with Play-next blocks inserted while shuffled. Proposal: keep them right after the current track, not the prototype's end-of-queue.
   - (b) Whether a native shuffle already turned on in the Sonos app shows as `Shuffle on` in Up next (it must; read `play_mode`).
   - (c) Copy when shuffle is unavailable (radio or AirPlay: `Shuffle needs the Sonos queue`).

**Verdict:** native shuffle does not meet the rule exactly (and can't display the order under H1). Companion-side reorder works with caveats (cost cap, other-controller visibility, live verification).

---

## 4. Up next data from the Sonos queue

### 4.1 What `get_queue` returns
- **Call.** `SoCo.get_queue(start=0, max_items=100, full_album_art_uri=False)` sends one `ContentDirectory.Browse(ObjectID="Q:0", BrowseFlag="BrowseDirectChildren", Filter="*", StartingIndex=start, RequestedCount=max_items, SortCriteria="")`. It returns a `Queue` (a list of DIDL objects) with `number_returned`, `total_matches` and `update_id` (`soco/core.py:2275-2318`; the `Queue` class at `soco/data_structures.py:1339-1346`; properties at `:1300-1313`).
- **Page size.** svrooij: "RequestedCount … maximum is 1,000 … Using 0 is equivalent to 1,000"; "Send one request, check the `TotalMatches` and - if necessary - do additional requests with higher `StartingIndex`" ([svrooij ContentDirectory](https://sonos.svrooij.io/services/content-directory)). The companion pages at 100 (`sonos.py:311`) with a consistency check on `update_id`/`total` across pages (`:315-316`).
- **Per-row fields** (`DidlMusicTrack`, class `object.item.audioItem.musicTrack`):

| Field (SoCo attribute) | DIDL element | Use in Up next | Source |
|---|---|---|---|
| `title` | `dc:title` | row title | `soco/data_structures.py:498-511` |
| `creator` | `dc:creator` | artist | `:449-452` |
| `album` | `upnp:album` | `artist · album`; album grouping | `:879-888` |
| `album_art_uri` | `upnp:albumArtURI` | cover (relative `/getaa?s=1&u=…` for service tracks; `full_album_art_uri=True` makes it absolute) | `:843-850`; `soco/core.py:2312-2314` |
| `original_track_number` | `upnp:originalTrackNumber` | **usually absent** for service tracks in the queue (it is not in sonos2mqtt's queue field list) | `:883` |
| `resources[0].uri` | `res` | `x-sonos-http:song%3a<catalogId>.mp4?sid=204&flags=…&sn=N` → `_song_id` → Apple catalog id | `sonos.py:63-68`; [SoCo #812](https://github.com/SoCo/SoCo/issues/812) |
| `resources[0].duration` | `res@duration` | row duration / playlist total | `soco/data_structures.py:175-204` |
| `item_id` / `parent_id` | `@id` / `@parentID` | `Q:0/<n>` / `Q:0` (row identity is positional, not stable) | [sonos2mqtt](https://sonos2mqtt.svrooij.io/control/playback.html) |

  sonos2mqtt's documented queue item fields: `Album, Artist, AlbumArtUri, Title, UpnpClass ("object.item.audioItem.musicTrack"), Duration ("0:MM:SS"), ItemId ("Q:0/1"), ParentId ("Q:0"), TrackUri, ProtocolInfo`.
- **Metadata of rows the companion added is still to be confirmed.** The companion enqueues with only `dc:title` in its DIDL (`sharelink.py:246-264`), and Sonos fills the rest from the service. Home Assistant uses the same call in production, and its users see full metadata. Whether **this** household's companion-added rows carry `creator`, `album` and `albumArtURI` is unverified; that is the read-only census R1 in §8.

### 4.2 Now playing, played, upcoming
- **Now playing** = row `Track` from `GetPositionInfo` (`get_current_track_info()["playlist_position"]`, `soco/core.py:2034`), 1-based.
  - Only meaningful while `GetMediaInfo.CurrentURI` starts with `x-rincon-queue:`.
  - During AirPlay, radio or TV the Sonos queue still exists but is **dormant**, and must not be shown as Up next (`research-apple-music-play-next.md` §3b, §4.2).
- **Duplicates.** Identify the current row by **index**, never by URI: playlists can contain duplicates, which `resolve` keeps (`apple_music.py:377`).
- **Played / Now playing / Up next tags** (M/specs/01:214; prototype `Browse and Snap.dc.html:1041`: `now ? 'Now playing' : past ? 'Played' : k === qNow + 1 ? 'Up next' : ''`):

| Play mode | Played | Now playing | Up next (tag) / upcoming |
|---|---|---|---|
| `NORMAL`, `REPEAT_ONE` | rows `< Track` ("before", strictly: a jump may have skipped some) | `Track` | `Track+1` / rows `> Track` |
| `REPEAT_ALL` | rows `< Track` this lap; after a wrap they are upcoming again | `Track` | `Track+1`, wrapping to 1 at the end |
| Companion shuffle (§3.4) | same as NORMAL (the queue order *is* the play order) | `Track` | same |
| Native `SHUFFLE*` | **unknown** under H1 (Sonos exposes no shuffle history; `sonos.py:163-164`) | `Track` | unknown under H1. Show `Shuffle on · order chosen by Sonos` (proposal) and no Played tags. |

- **Knob mirrors.** `{i} / {n}` (M/specs/01:119-120) = `Track / total_matches`, which is cheap: `_state` already reads `get_queue(0,1)` every poll (`sonos.py:183`).
  - Add `playlist_position` and the media-URI class to `_state`. It does not copy them today (`sonos.py:188-202`).

### 4.3 Cost for long queues, and a read plan
- **Full read (`_queue`):** `ceil(T/100)` Browse calls. `MAX_QUEUE = 5000` (`sonos.py:72`), so up to 50 calls. Each page carries about 100 DIDL items.
  - Rough size estimate: 0.8–1.5 KB per item before XML escaping, i.e. about 100–150 KB per page.
  - Sonos's own practical queue ceiling is reportedly about 64–65k tracks (community, [Maximum Tracks in Queue](https://en.community.sonos.com/controllers-and-music-services-228995/maximum-tracks-in-queue-6838916)). This is low-weight evidence; the companion's own cap is 5,000.
- **Windowed read (recommended for Up next).** The list shows ±4 rows around the focus (M/specs/01:202-208). Read:
  - `get_queue(max(0, focus−10), 21)` on open, plus a 21-row window whenever the focus nears an edge (about 1 Browse per 10 detents);
  - `update_id` and `total_matches` come with every page.
- **Change detection.** The 1 Hz poll already reads `update_id`/`total_matches` (`sonos.py:183`, `:200-201`). Re-read the visible window only when `update_id` or `Track` changes.
- **Ring.** Up next landmarks need each row's album colour (M/specs/01:136). The prototype puts rows 3 segments apart around 12 o'clock (`Browse and Snap.dc.html:1005-1007`), so more than 20 rows alias on 60 segments. Only the visible window's colours are needed (a LED-doc concern, see 02-leds).
- **Row covers and metadata from Apple, not Sonos.**
  - Batch the window's `_song_id`s into `GET /v1/catalog/{sf}/songs?ids=a,b,…` ("The maximum fetch limit is 300", [Get Multiple Catalog Songs by ID](https://developer.apple.com/documentation/applemusicapi/get-multiple-catalog-songs-by-id)). That gives `albumName`, `trackNumber`, `discNumber`, `durationInMillis`, `artwork` (template), `url`, `contentRating` and `inFavorites` ([Songs.Attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)).
  - It is one request per ≤ 300 rows, and fills the gaps the Sonos queue has: track numbers for album rows, 600 px big cover, 112 px (2 × 56) row thumbnails, the heart state, and the album id for grouping (`include=albums`).
  - Rows without a song id (other services, library-only uploads) fall back to Sonos `/getaa`. The artwork allowlist already accepts `http://<known speaker IPv4>:1400/getaa` (`control_center/artwork.py:69-107`). The size `/getaa` serves is undocumented.
  - The storefront comes from the cached `_get_storefront()` (`apple_music.py:296-303`).
- **Up next "Play"** (button 4, "jump to track"): `Seek(Unit=TRACK_NR, Target=row)`, already used by Previous (`sonos.py:297`), with the same track and queue guards (`:290-296`).

**Verdict: works with caveats** (queue source only; played/upcoming unknowable under native shuffle H1; metadata of companion-added rows to be confirmed; windowed reads to stay cheap).

---

## 5. Apple Music

### 5.1 Tokens and endpoints today (code only)

| Item | Finding | Source |
|---|---|---|
| **Developer token** | ES256 JWT minted locally **per request**: `iss` = Team ID, `kid` = Key ID, `iat` = now − 30, `exp` = now + 3600, signed with the user's MusicKit `.p8`. Optional `origin` claim for the consent page. A static `developer_token` is the fallback. | `control_center/credentials.py:125-143` |
| Key import | `from_key_file(team_id, key_id, path)`: 10-character ids, `.p8` ≤ 16,384 bytes containing `BEGIN PRIVATE KEY`, validated locally with no network. | `credentials.py:106-122` |
| **Music-User-Token** | Obtained with **MusicKit JS v3** in the user's own browser. A one-use loopback `ThreadingHTTPServer(("127.0.0.1", 0))` (`:232`) serves a page that loads `https://js-cdn.music.apple.com/musickit/v3/musickit.js` (`:249`) and calls `MusicKit.configure(...)` and then `MusicKit.getInstance().authorize()` (`:248`). The token is POSTed back to `/token`, guarded by Host, Origin, `X-NanoD-Nonce` (`compare_digest`), a 900 s expiry (`:162`) and a 1–16,384-char check. It is stored as `music_user_token` (`:219`). | `credentials.py:146-252` |
| Storage | DPAPI CurrentUser with UI_FORBIDDEN (`:51-53`), magic `NANOD-CREDENTIALS-1\n` (`:65`), atomic replace (`:86-103`), `%LOCALAPPDATA%\NanoDControlCenter\credentials.bin` (`:68`). | `credentials.py:30-103` |
| Refresh | None. Each request re-reads the store (`apple_music.py:92-96`), so re-authorizing takes effect without a restart. Apple documents no Music-User-Token lifetime. Music Assistant documents "expire[s] … after 180 days" ([Music Assistant](https://www.music-assistant.io/music-providers/apple-music/)). The developer-token `exp` must be ≤ 15,777,000 s ([Generating developer tokens](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens)); the companion uses 3,600. | as cited |
| Request | `GET` only. Headers `Authorization: Bearer <JWT>`, `Music-User-Token`, `Accept: application/json`; `allow_redirects=False`; timeout 8 s (`:32`). Paths are restricted to `https://api.music.apple.com/v1/…` (`_safe_path`, `:79-88`). | `apple_music.py:90-123` |
| Errors | 401/403 → `Apple Music authorization expired or access was denied. Reconnect in settings.` · 429 → `…temporarily limiting requests…` · other non-200 → generic · the body must have a `data` list (`:116-117`) · exceptions are sanitised (`:121-123`). | `apple_music.py:109-123` |
| Endpoints used today (all GET) | `/v1/me/library/recently-added` (`:28`, `:196`, `:235`) · `/v1/me/library/songs/{id}` (`:365`) · `/v1/me/library/{albums\|playlists}/{id}/tracks` (`:368`) · `/v1/me/library/songs/{id}/catalog` (`:313`) · `/v1/me/storefront` (`:298`) · `/v1/catalog/{sf}/songs/{id}` (`:322`) · `/v1/catalog/{sf}/songs/{id}/albums` (`:340`) · `/v1/catalog/{sf}/albums/{id}` (`:349`) | `apple_music.py` |
| Id formats seen | Library album `l.<7 chars>`, library song `i.<14 chars>`, catalog song numeric (`diagnostics/apple-music-readiness.json`, shapes only) | diagnostics |
| Copy promising read-only | Module docstring "Read-only Apple Music library browsing" (`apple_music.py:1`). Consent page: "Allow the knob companion to read your Recently Added library. This page does not play music or modify your library." (`credentials.py:245`) | as cited |

Apple documents no scopes for Music User Tokens. Every personalised endpoint, read or write, says only "This endpoint requires a music user token" (e.g. [Add a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/add-a-personal-content-rating-33dop)). **So no new token type is needed for (a), (b) or (c).**

### 5.2 (a) Like: `PUT /v1/me/ratings/songs/{id}`

**Apple contract** (fetched 2026-09-25):
- **Add:** `PUT https://api.music.apple.com/v1/me/ratings/songs/{id}`.
  - Body `RatingRequest`: `{"type":"rating","attributes":{"value":1}}`.
  - `200 RatingsResponse`, for example `{"data":[{"id":"907242702","type":"ratings","href":"/v1/me/ratings/songs/907242702","attributes":{"value":1}}]}`.
  - Errors: 401, 403, 500.
  - "A rating indicates whether a user likes `(1)` or dislikes `(-1)` the song. These are the only two ratings supported."
  - "For a particular song, the personal ratings for that song's catalog ID and library ID … stay synced."
  - [Add a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/add-a-personal-content-rating-33dop)
- **Remove:** `DELETE https://api.music.apple.com/v1/me/ratings/songs/{id}` → `204` with no body ([Delete a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/delete-a-personal-content-rating-3a3a2)). **Un-like must be DELETE, never value -1** (-1 = dislike / "Suggest Less").
- **Read many:** `GET /v1/me/ratings/songs?ids=907242702,1151618586` → `200` ([Get Multiple Personal Song Ratings](https://developer.apple.com/documentation/applemusicapi/get-multiple-personal-content-ratings-6wab5)). No maximum id count is documented; Music Assistant batches 100. What an all-unrated set returns (empty `data` or 404) is undocumented, so handle both.
- **Explicit favourites endpoint (newer):** `POST https://api.music.apple.com/v1/me/favorites?ids=…` → `202 Accepted`, empty body.
  - "if a customer favorites a song, the song is added to their `favorite songs` playlist. If they like an album or playlist, they can filter on `favorited album` in their library view"; "Bulk additions of heterogenous types are permitted."
  - [Add resource to favorites](https://developer.apple.com/documentation/applemusicapi/add-resource-to-favorites)
  - **No "remove from favorites" endpoint exists in the API index** ([Apple Music API index](https://developer.apple.com/documentation/applemusicapi), topic "Adding a resource to favorites" has only the POST).
  - The typed-id form (`ids[songs]=`) is inferred by analogy and unverified.
- **`inFavorites`** (boolean, "Whether the catalog resource ID is in the person's favorites") is an attribute of `Songs`, `LibrarySongs` and `LibraryPlaylists` ([Songs.Attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary), [LibrarySongs.Attributes](https://developer.apple.com/documentation/applemusicapi/librarysongs/attributes-data.dictionary), [LibraryPlaylists.Attributes](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/attributes-data.dictionary)).
- **Is rating 1 = the Music app's star "Favorite"?** Strongly implied, not stated.
  - Since iOS 17.1 the apps offer only Favorite and Suggest Less.
  - Music Assistant ships favourites as `PUT me/ratings/{type}/{id}` value 1 and reads them back via ratings. Its source: `set_favorite` builds `{"type": "ratings", "attributes": {"value": 1 if favorite else -1}}` and PUTs `me/ratings/{item_type}/{id}` or `me/ratings/library-{item_type}/{id}` ([library.py](https://raw.githubusercontent.com/music-assistant/server/dev/music_assistant/providers/apple_music/library.py)).
  - Note: MA un-favourites with -1, which is a dislike. **Do not copy that.**
  - Details: `check-like.md` §2.2.

**Mapping a Sonos queue row to a song id:**
- `_song_id(row)` extracts `song:<digits>` from the unquoted resource URI (`sonos.py:63-68`). It is load-bearing today (`sonos.py:391-394`, `:407`, `:421`) and was verified live on this household (§1.2).
- It matches both `x-sonos-http:song%3a<id>.mp4?sid=204…` ([SoCo #812](https://github.com/SoCo/SoCo/issues/812): the number "is in fact the ID of the played song") and any other scheme carrying `song%3a<id>`.
- **Catalog id** → `PUT /v1/me/ratings/songs/{catalogId}`. No storefront is needed, and the library copy stays in sync by Apple's statement above.
- **Library-only rows** (uploads, or "My Library" picks in the Sonos app, e.g. `librarytrack%3ai.…`): `_song_id` returns `None`. They *might* map to `/v1/me/ratings/library-songs/{i.…}`, but that is unverified, so **disable Like** for them in v1.
- **Rows from other services, radio, line-in:** disabled. Show the disabled level 0.14 (M/README.md:151).
- **Account caveat.** The Sonos-linked Apple Music account and the companion's MusicKit account are independent. Like writes to the companion's account, which is also the one the explorer reads.

**Heart state for the visible rows:** one `GET /v1/me/ratings/songs?ids=` (≤ 100) per window change. Or read `inFavorites` from the same `GET /v1/catalog/{sf}/songs?ids=` batch that §4.3 uses for covers, if the live check shows it is populated.

**Code and copy deltas Like forces:**
- `AppleMusicClient._get` is GET-only and requires a `data` list (`apple_music.py:104`, `:116-117`), so it cannot carry 204 or 202. Add `_send(method, path, json, expected_status)` reusing `_safe_path`, the credential loader, the headers, `allow_redirects=False` and the sanitised errors, plus `Content-Type: application/json` for PUT.
- Route 401/403 from Like into the existing "sign-in expired" state. `_needs_login` (`controller.py:83-85`) matches the message, and the runtime sets `music_signin_expired` only from Recently Added results (`runtime.py:239-241`, `:955-964`).
- The consent copy (`credentials.py:245`) and docstring (`apple_music.py:1`) must stop promising "does not … modify your library". Favouriting can add the song to the library (Apple web guide, cited in `check-like.md` §2.4).
- The recovery card body "Recently Added can't load. Volume, Tracks and Windows are unaffected." (`M/prototypes/Nano_D Control Center.dc.html:1028`) should also mention Favourite playlists and Like.
- **Confirmed-state UI.** Heart pop and pink bloom `255,40,90` (M/README.md:142, :173; M/specs/01:155) **only after 200/204**. The prototype plays them immediately (`Browse and Snap.dc.html:657-663`).
  - Toasts: `Added to Favourites · {title}` / `Removed from Favourites · {title}` (`:662`).
  - Toasts never over an open overlay (M/README.md:209), and Up next *is* an overlay, so the heart pop is the feedback while it is open.

**Verdict (a): works with caveats.**

### 5.3 (b) "Favourite playlists"
- **Design:** "the user's favourited or pinned playlists from the Apple Music library" (M/README.md:227). The explorer tab is `[3] list-music Favourite playlists` (M/specs/01:174).
- **Card sub** "Favourite playlist"; meta `{n} songs · {duration}` (M/specs/01:186); a 2 × 2 mosaic of four album covers (M/README.md:185).
- **Like does not feed this tab.** Spec 01:222 says it does, but README:226 wins (M/README.md:15-21). A liked **song** goes into Apple's auto "Favorite Songs" playlist ([Add resource to favorites](https://developer.apple.com/documentation/applemusicapi/add-resource-to-favorites)), and that is a song favourite, not a favourited **playlist**.
- **Apple offers:**

| Need | Endpoint / attribute | Notes |
|---|---|---|
| All library playlists | `GET /v1/me/library/playlists` (`include`, `l`, `limit`, `offset`, `extend`; requires a music user token) → `LibraryPlaylistsResponse` | [Get All Library Playlists](https://developer.apple.com/documentation/applemusicapi/get-all-library-playlists). Paged via `next` ([Fetching resources by page](https://developer.apple.com/documentation/applemusicapi/fetching-resources-by-page)). `_collection` already follows `next` (`apple_music.py:282-294`). |
| Favourited filter | `attributes.inFavorites == true` | Optional attribute, not marked Extended ([LibraryPlaylists.Attributes](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/attributes-data.dictionary)). Whether it is populated on a plain request is **unverified** (live read-only check R4). Other attributes: `artwork`, `canEdit` (required), `dateAdded`, `description`, `hasCatalog` (required), `name` (required), `playParams`, `isPublic` (required), `trackTypes` (Extended: `library-music-videos`, `library-songs`). |
| Favourited filter, alternative | `GET /v1/me/ratings/library-playlists?ids=…` → keep value 1 | Listed under "Get Multiple Personal Library Playlist Ratings" ([Ratings](https://developer.apple.com/documentation/applemusicapi/ratings-api)). Music Assistant reads playlist favourites exactly this way: `get_ratings(playlist_library_item_ids, MediaType.PLAYLIST)` → `is_favourite` ([library.py](https://raw.githubusercontent.com/music-assistant/server/dev/music_assistant/providers/apple_music/library.py)). |
| "Pinned" playlists | **No public endpoint.** Pins exist only in private endpoints needing "a privileged developer token … Shipping these APIs inside production software is likely to violate Apple's terms" ([MusanovaKit](https://github.com/rryam/MusanovaKit)). | **Not possible.** |
| Track list (to play; mosaic; count and duration) | `GET /v1/me/library/playlists/{id}/tracks`. `tracks` relationship "Fetch limits: 100 default, 100 maximum" ([LibraryPlaylists.Relationships](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/relationships-data.dictionary)). | Already used by `resolve(kind="playlist")` (`apple_music.py:366-371`). |

- **Caveats:**
  - **Smart and auto playlists** (incl. "Favorite Songs") are reportedly not returned by `/v1/me/library/playlists` (Apple forum 112677, cited in `check-like.md` §2.4). Unverified.
  - Library playlists carry **no track count or duration**. `{n} songs · {duration}` needs the track list: `ceil(n/100)` requests per playlist, summing `durationInMillis` ([LibrarySongs.Attributes](https://developer.apple.com/documentation/applemusicapi/librarysongs/attributes-data.dictionary), required). Fetch lazily for the centre card ±2, and cache per playlist by `lastModifiedDate`/`dateAdded` (proposal).
  - **The 2 × 2 mosaic** needs four distinct album covers: take the first tracks' `artwork` (required on `LibrarySongs`) from the same `/tracks` page (`limit` small).
  - **Playability:** playlists may contain music videos (`trackTypes`) and uploads. `resolve` already refuses the whole item with "Nothing was queued." (`apple_music.py:305-328`). Sonos does not support Smart Playlists or music videos ([Apple Music on Sonos](https://support.sonos.com/en-us/services/apple-music?r=1)).
- **Fallback if `inFavorites` is not populated and ratings return nothing:** show user-created playlists (`canEdit: true`) under the same tab with a changed sub label (a design decision), or hide the tab.

**Verdict (b): favourited = works with caveats; pinned = not possible.**

### 5.4 (c) Track lists and 600 px artwork
- **Album tracks:** `/v1/me/library/albums/{id}/tracks`. `tracks` "Fetch limits: 300 default, 300 maximum" ([LibraryAlbums.Relationships](https://developer.apple.com/documentation/applemusicapi/libraryalbums/relationships-data.dictionary)). Already used (`apple_music.py:368`).
- **Playlist tracks:** as in 5.3 (100 per page).
- **Catalog metadata per song:** `GET /v1/catalog/{sf}/songs?ids=` (≤ 300). Fields: `albumName` (required), `artistName`, `artwork` (required), `discNumber`, `durationInMillis` (required), `trackNumber`, `url` (required), `playParams`, `contentRating`, `inFavorites` ([Songs.Attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)).
  - `resolve` already fetches catalog songs but copies only `name`, `artistName`, `id`, `url` (`apple_music.py:379-382`).
  - Up next and the explorer need `albumName`, `trackNumber`, `durationInMillis` and `artwork.url` added to that dict, with no extra request.
- **Artwork object:** `url` "`{w}x{h}` must precede image filename … For example, `{w}x{h}bb.jpeg`"; `width`/`height` = "The maximum width/height available"; `bgColor` = "The average background color of the image" ([Artwork](https://developer.apple.com/documentation/applemusicapi/artwork)).
- **600 px:** `apple_artwork_url(artwork, size=600)` already substitutes `{w}`, `{h}` and `{f}`, accepts sizes 16–3000, and rejects any other token such as `{c}` (`control_center/artwork.py:110-135`).
  - Today's constants: `ARTWORK_SIZE = 480` (`:52`), `ACCENT_SIZE = 96` (`:53`), `HIRES_SIZE = 480` (`:57`). The design asks 600 for overlays and 240 for the knob (M/README.md:228; M/specs/01:193).
  - Clamp to `min(600, width, height)` when those are > 0.
  - Downloads are capped at 2 MiB (`MAX_DOWNLOAD`, `:50`), with a 2 s connect / 3 s read / 8 s total timeout and no redirects (`:484-512`). A 600 px JPEG is far below the cap.
  - `bgColor` can seed the dominant colour before the image arrives (proposal; M/README.md:229 asks for `dominant()` from the image).

**Verdict (c): works.**

### 5.5 Fallback proposed by the design: Play next for the highlighted track (instead of Like)
- **Upcoming row** (`row > Track`): move it, don't duplicate it.
  - `ReorderTracksInQueue(InstanceID=0, StartingIndex=row, NumberOfTracks=1, InsertBefore=Track+1, UpdateID=<update_id>)` (§3.4), then verify with a slice read.
  - It needs no Apple call and works for rows from **any** service.
- **Played row** (`row < Track`): re-insert rather than move, so the history stays put.
  - Use the existing share-link path at `position = Track + 1` with the song's catalog `url`, which the §4.3 batch already has. No invented album id (`apple_music.py:338-339`).
  - Moving a row from before the current track also shifts `Track` by −1, which would invalidate `_track_id`.
- **Current row / already next:** no-op, with a short confirmation.
- **Gates:** same as §1.8 (queue source; not native shuffle).
- **LED and copy:** the Sweep moment (M/README.md:175). Proposal: `Plays next · {title}`.

**Verdict: works** (the live check is shared with §1 and §3).

---

## 6. Album queue versus playlist queue

**The design needs the distinction:**
- **Album:** the cover stays still, rows show track numbers, sub `artist · year`.
- **Playlist:** 56 px per-row covers, `artist · album`, crossfading cover, sub `Favourite playlist · n songs · duration`.
- Sources: M/README.md:190-193; M/specs/01:198-213.
- The prototype decides from what it last played (`s.np.kind`, `Browse and Snap.dc.html:1027`). Rows use art when `isPl || tr.al !== s.np.i` and numbers when `!isPl && tr.al === s.np.i` (`:1039`). Context from `s.np` (`:1049`).

**What the Sonos queue can tell:**
- Per row: title, creator, album, `albumArtURI`, URI and duration (§4.1).
- **No container id, no playlist name, no source kind, and usually no track number.** `GetMediaInfo.CurrentURI` is only `x-rincon-queue:<uid>#0` for the queue.
- **So the queue data alone cannot say "this is playlist X".**

**Recommended identification** (in order):
1. **Provenance ledger (authoritative).**
   - When `play_items` succeeds, record `{kind (album|playlist|song), library_id, name, artist, year/trackCount, artwork template, song_ids: [...], final update_id}` from the Recently Added or explorer item.
     - `play_items` already verifies `[_song_id(x) for x in final.items] == songs` (`sonos.py:407`, `:421`).
     - Library albums carry `trackCount` (`apple_music.py:369`).
   - When Play next succeeds, append a segment `{start_row, song_ids, album context}`.
   - On each Up next open, compare the current queue's `_song_id` sequence to the ledger's segments, not just `update_id`: a reorder or insertion elsewhere changes `update_id` without invalidating the segments.
   - If it matches:
     - **album queue:** a single `album` segment and no foreign rows → still cover, track numbers, `artist · year`;
     - **playlist queue:** a `playlist` segment → per-row covers, `Favourite playlist · n songs · duration` (or `Playlist · …` for a non-favourite);
     - Play-next segments → their rows show their own cover and `artist · album` (M/specs/01:221).
2. **Heuristic (queue built elsewhere, or the ledger is stale):**
   - all rows share `album` + `creator` (normalised), or all mapped song ids share one catalog album (via `include=albums` in the §4.3 batch) → **album queue**, titled by the album name. Track numbers come from the catalog `trackNumber`/`discNumber`. The year needs the catalog album's `releaseDate`.
   - otherwise → **mixed queue**, with playlist-style rows and **no playlist name** (there is none to show). Proposed copy: title `Sonos queue`, sub `{n} songs · {duration}`. The design has no copy for this case.
3. **Not the queue source** (AirPlay, radio, TV): no list. Show a now-playing card only (`research-apple-music-play-next.md` §4.2).

**Verdict: works with caveats.** Exact for queues the companion built; heuristic, and without playlist names, for queues built by other controllers.

---

## 7. Adapter and client additions this design needs (none done; read-only)

| Area | Addition | Anchors |
|---|---|---|
| `SonosAdapter._state` | add `playlist_position`, parsed `duration` and `position` with a read timestamp, media-URI class (`queue/radio/airplay/…`), `can_seek` (`"SeekTime" in actions` and duration > 0 and PLAYING/PAUSED) | `sonos.py:177-204` |
| `SonosAdapter.play_next(items, rev, track_id)` | §1.5 | reuse `sonos.py:355-362`, `:344-349` |
| `SonosAdapter.seek(seconds, rev, track_id)` | §2; `check-seek.md` §4.4 | sibling of `sonos.py:215-306` |
| `SonosAdapter.set_shuffle(on, rev)` | native `SetPlayMode`, or the companion reorder (§3.4) with a persisted restore record | `sonos.py:323-342` pattern |
| `SonosAdapter.queue_window(start, count)` | windowed `get_queue` plus `update_id`/`total` | `sonos.py:308-321` |
| `SonosAdapter.move_next(row, rev)` | `ReorderTracksInQueue` (fallback for Like) | §5.5 |
| `AppleMusicClient._send` + `like/unlike/ratings/catalog_songs(ids)/library_playlists()` | §5.2-5.4 | `apple_music.py:90-123` |
| `resolve` output | add `albumName`, `trackNumber`, `discNumber`, `durationInMillis`, `artwork` | `apple_music.py:379-382` |
| Provenance ledger | §6 | `runtime.py:1146-1156` (play completion) |
| Test fake | `FakeSpeaker.add_share_link_to_queue` ignores `position` and always appends (`tests/test_cc_music.py:268-280`). It needs positional insert, `ReorderTracksInQueue`, `SetPlayMode`, `"SeekTime"` in `available_actions` (`:226`), and `duration`/`position` in `track` (`:233`). | tests |

---

## 8. Proposed live checks (NOT run; each needs the user's go-ahead)

All checks use a standalone script against the pinned coordinator.
- It uses no companion, no knob and no COM port.
- It logs only counts, booleans, positions and song ids. **No tokens, no titles.**

**Read-only (no audible effect):**
- **R1. Queue census.** One windowed `Browse(Q:0)` around the current row. Report, per row: whether `creator`/`album`/`albumArtURI` are present; whether `original_track_number` is present; the `_song_id` match rate; the `update_id`. This settles §4.1.
- **R2. Seek capability while playing and paused.** `GetCurrentTransportActions`, `GetPositionInfo` (`TrackDuration`/`RelTime`) and `GetMediaInfo`. The user starts and pauses playback in the Sonos app.
- **R3. Native shuffle shape (H1/H2).** The user toggles shuffle in the Sonos app. Before and after, read `GetTransportSettings`, `GetPositionInfo.Track` and `Browse(Q:0, 0, 30)`. Compare the order and `Track`.
- **R4. Apple read-only** (about 4 GETs):
  - `GET /v1/me/library/playlists?limit=100` (first page): count `inFavorites` true/false/absent;
  - `GET /v1/me/ratings/library-playlists?ids=<that page>`;
  - `GET /v1/catalog/{sf}/songs?ids=<R1 ids ≤ 300>`: `inFavorites` present?, `trackNumber`, `artwork.width`.

**Reversible writes (separate approval each):**
- **W1. Play next, 2 songs.** At `P+1`, `P+2` while **paused**. Verify per §1.7, then `RemoveTrackRangeFromQueue(StartingIndex=P+1, NumberOfTracks=2, UpdateID=<fresh>)`. Detailed steps: `check-play-next.md` §5.
- **W2. Seek ±20 s** on a playing Apple Music queue track; measure the `TRANSITIONING` time and landing accuracy (`check-seek.md` §5).
- **W3. ReorderTracksInQueue.** Move one upcoming row to `P+1` and back; confirm playback is uninterrupted and `Track` is unchanged. Then move one row from **before** P to after it and back; confirm the current song keeps playing and `Track` shifts by −1/+1.
- **W4. Like.** On an already-library song that is currently unrated: PUT value 1 → GET → the user checks for the star in the Music app → DELETE → GET (`check-like.md` §5).

---

## 9. Sources

**Local (read-only):**
- `control_center/sonos.py`: 58-68, 72, 90, 95-109, 147-156, 159-175, 177-204, 215-306, 308-349, 351-451
- `control_center/apple_music.py`: 1-5, 27-32, 79-123, 251, 265-277, 282-383
- `control_center/credentials.py`: 30-103, 106-143, 146-252
- `control_center/artwork.py`: 48-57, 69-135, 484-512
- `control_center/runtime.py`: 161, 239-241, 955-964, 1098-1156, 1215
- `control_center/controller.py`: 83-85, 329-342, 498-513, 674-682
- `README.md` (demo): 50-63
- `tests/test_cc_music.py`: 203-280
- `tools/quiet_sonos_probe.py`: 41-43, 206-220
- `diagnostics/sonos-readiness.json`: 14-19, 22-58, 83-92
- `diagnostics/quiet-sonos-probe.json`: 24-33
- `diagnostics/apple-music-readiness.json` (field shapes only)
- SoCo 0.31.2:
  - `soco/__init__.py:20`
  - `soco/core.py`: 570-632, 732-761, 875-947, 1874-1913, 2004-2159, 2258-2342, 2354-2457, 3058-3097
  - `soco/plugins/sharelink.py`: 31-69, 152-187, 216-285
  - `soco/plugins/plex.py`: 111-153
  - `soco/services.py`: 152, 192-220, 434-510
  - `soco/data_structures.py`: 165-204, 445-452, 834-888, 1300-1346
  - `soco/snapshot.py`: 195-208
- Design:
  - `M/README.md`: 15-21, 75, 78, 120, 142, 146, 151, 163, 173-175, 185, 189-195, 209, 224-229, 238
  - `M/specs/01-FEATURES-explorers-snap-seek.md`: 76, 79, 119-120, 136, 155-156, 162-167, 174, 186, 193, 195-222
  - `M/specs/03-SCREEN-and-state.md`: 136
  - `M/prototypes/Browse and Snap.dc.html`: 408-445, 601, 657-698, 712, 753-757, 766-792, 952-964, 1005-1007, 1027-1049, 1080-1081
  - `M/prototypes/Nano_D Control Center.dc.html`: 1028
- Earlier checks: `check-play-next.md`, `check-seek.md`, `check-like.md`, `research-apple-music-play-next.md`

**Sonos / UPnP:**
- [svrooij AVTransport](https://sonos.svrooij.io/services/av-transport)
- [svrooij ContentDirectory](https://sonos.svrooij.io/services/content-directory)
- [go-sonos AVTransport.go](https://raw.githubusercontent.com/ianr0bkny/go-sonos/master/upnp/AVTransport.go)
- [node-sonos sonos.js](https://raw.githubusercontent.com/bencevans/node-sonos/master/lib/sonos.js)
- [node-sonos-http-api appleMusic.js](https://raw.githubusercontent.com/jishi/node-sonos-http-api/master/lib/actions/appleMusic.js)
- [Home Assistant Sonos media_player.py](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/sonos/media_player.py)
- [sonos2mqtt playback](https://sonos2mqtt.svrooij.io/control/playback.html)
- SoCo issues: [#812](https://github.com/SoCo/SoCo/issues/812), [#969](https://github.com/SoCo/SoCo/issues/969)
- Sonos Control API: [seek](https://docs.sonos.com/reference/playback-seek-groupid), [setPlayModes](https://docs.sonos.com/reference/playback-setplaymodes-groupid), [Playback on Sonos](https://docs.sonos.com/docs/playback-on-sonos.md)
- Sonos support:
  - [Add tracks to the queue](https://support.sonos.com/en-us/article/add-tracks-to-the-queue)
  - [Using the queue](https://support.sonos.com/en-us/article/using-the-queue-in-the-sonos-app)
  - [Shuffle, repeat, and crossfade](https://support.sonos.com/en/article/shuffle-repeat-and-crossfade-songs)
  - [Apple Music on Sonos](https://support.sonos.com/en-us/services/apple-music?r=1)
- Sonos Community (low weight):
  - [Request for feedback: Shuffle](https://en.community.sonos.com/controllers-and-music-services-228995/request-for-feedback-shuffle-6517514/index8.html)
  - [Sonos' implementation of Shuffle](https://en.community.sonos.com/general-feedback-and-conversation-229090/sonos-implementation-of-shuffle-6904897)
  - [Maximum Tracks in Queue](https://en.community.sonos.com/controllers-and-music-services-228995/maximum-tracks-in-queue-6838916)
- [HA Community: Sonos shuffle doesn't work well](https://community.home-assistant.io/t/sonos-shuffle-doesnt-work-well/982322)
- [HA #181315](https://github.com/home-assistant/core/issues/181315)

**Apple:**
- [Apple Music API index](https://developer.apple.com/documentation/applemusicapi)
- [Ratings](https://developer.apple.com/documentation/applemusicapi/ratings-api)
- [Add a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/add-a-personal-content-rating-33dop)
- [Delete a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/delete-a-personal-content-rating-3a3a2)
- [Get Multiple Personal Song Ratings](https://developer.apple.com/documentation/applemusicapi/get-multiple-personal-content-ratings-6wab5)
- [Add resource to favorites](https://developer.apple.com/documentation/applemusicapi/add-resource-to-favorites)
- [Get All Library Playlists](https://developer.apple.com/documentation/applemusicapi/get-all-library-playlists)
- [LibraryPlaylists.Attributes](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/attributes-data.dictionary)
- [LibraryPlaylists.Relationships](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/relationships-data.dictionary)
- [LibraryAlbums.Relationships](https://developer.apple.com/documentation/applemusicapi/libraryalbums/relationships-data.dictionary)
- [LibrarySongs.Attributes](https://developer.apple.com/documentation/applemusicapi/librarysongs/attributes-data.dictionary)
- [Songs.Attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)
- [Get Multiple Catalog Songs by ID](https://developer.apple.com/documentation/applemusicapi/get-multiple-catalog-songs-by-id)
- [Artwork](https://developer.apple.com/documentation/applemusicapi/artwork)
- [Fetching resources by page](https://developer.apple.com/documentation/applemusicapi/fetching-resources-by-page)
- [Generating developer tokens](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens)

**Third-party:**
- [Music Assistant: Apple Music](https://www.music-assistant.io/music-providers/apple-music/)
- [Music Assistant library.py](https://raw.githubusercontent.com/music-assistant/server/dev/music_assistant/providers/apple_music/library.py)
- [MusanovaKit (private pins API)](https://github.com/rryam/MusanovaKit)
