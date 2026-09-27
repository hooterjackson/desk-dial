# Check: "Play next" — can Sonos insert an Apple Music album right after the current song?

Date: 2026-09-25. Read-only desk check. No call was made to the Sonos system or to Apple Music. The only network use was public documentation and public GitHub source.
Paths below are relative to `app/` unless they are URLs.

Design intent being checked:
- `design-reference/design_handoff_nano_d_master/README.md:75`: Recently Added, button 3 = **Play next** (queue kept).
- `README.md:193`: albums added with Play next show their own cover in Up next.
- `README.md:224` (section 8): "Sonos `AddURIToQueue` with `EnqueueAsNext=1`, inserting after the current track. Confirm it works with the Apple Music service on Sonos."
- `README.md:238`: acceptance item.
- `specs/01-FEATURES-explorers-snap-seek.md:76` and `:221`: Play next shows `Queued next` for 1.5 s and the toast `Queued next · {album}`.

---

## Verdict: works, with caveats

Sonos can insert Apple Music content after the current song while the room is playing from its **queue**. The design names the wrong control for this, though.

- **`EnqueueAsNext=1` does not do it.** SoCo documents that flag as affecting shuffle only. The installed SoCo says `as_next` "only works if play_mode=SHUFFLE" (`soco/core.py:2375-2376`, `soco/plugins/sharelink.py:227-228`). node-sonos sends `EnqueueAsNext: 1` on every add, including plain "add to end of queue" (`DesiredFirstTrackNumberEnqueued: 0`, documented as "defaults to end of queue"). That shows the flag alone does not insert next in normal play.
- **What inserts after the current song is `DesiredFirstTrackNumberEnqueued = current playlist_position + 1`.** Home Assistant ("enqueue: next") and node-sonos-http-api (`applemusic/next/...`) both use this.

The companion already has everything it needs. Today it appends each Apple Music song with `ShareLinkPlugin.add_share_link_to_queue(url, position=0)`. **Play next is the same call with `position = P + 1 + i` (P = the current queue row).** It uses the same URIs, the same DIDL metadata and the same per-song verification. No new URI or metadata style is needed.

Caveats (details in section 4):
1. **Only while the queue is the active source.** Media URI `x-rincon-queue:...`. With radio (including Apple Music radio), line-in, TV, AirPlay or Spotify Connect there is no "current song in the queue". Refuse with a message.
2. **Shuffle.** Physical insertion still works, but playback order is random. Sonos's `EnqueueAsNext` behaviour for multi-track items in shuffle is documented only indirectly: one random track becomes next and the rest are scattered. That defeats "album next". Recommend refusing in shuffle modes, or queuing with a warning.
3. **Albums and playlists are not one call.** The companion expands a library album or playlist into catalog songs (`control_center/apple_music.py:356-383`) and deliberately avoids "whole-catalog-album substitution" (`apple_music.py:3-5`). So an album of N songs is N `AddURIToQueue` calls at consecutive positions. No transaction spans them, and the queue must be verified and rolled back like `play_items` does.
4. **Race at the song boundary.** The risk is that the current song ends between reading P and the first insert. Then the block lands before the new current song. It is detectable afterwards and reversible.
5. **Not yet proven on this household.** The share-link and position combination is used in production by Home Assistant. The companion's own share-link appends work. Positional insertion on the user's own S2 system is still untested. Share-link enqueueing has had a firmware regression before (SoCo #969, Dec 2024, UPnP 800 on S2, fixed by a Sonos update). A short reversible live test (section 5) should confirm it before building.

---

## 1. How the companion queues Apple Music today

### Resolution (`control_center/apple_music.py`)
- Recently Added items become kinds `album`, `playlist` or `song` from `library-albums`, `library-playlists` or `library-songs` (`apple_music.py:251`, item dict `:270-277`).
- `resolve(item)` (`:356-383`):
  - Albums and playlists are fetched through `/v1/me/library/{albums|playlists}/{id}/tracks` (`:366-368`).
  - The track count is checked against `trackCount` (`:369-371`).
  - Each library track is mapped to exactly one catalog song (`_catalog_song`, `:305-328`).
  - Order and intentional duplicates are kept (`:377`).
- Each resolved track is `{"title", "artist", "catalog_id", "url", "library_id"}`. `url` is always `https://music.apple.com/{sf}/album/{slug}/{albumId}?i={songId}`, built by `_song_url` (`:330-354`), which uses the real related album and "never invent[s] an album ID" (`:338-339`).
- **Albums and playlists produce the same kind of output: a list of catalog songs.** No album or playlist container ID is ever passed to Sonos.

### Enqueue (`control_center/sonos.py`, `play_items`, `:351-451`)
Validation:
- Every item must be an `https://music.apple.com/xx/album/<slug>/<digits>?i=<catalog_id>` link (`:355-362`). Anything else is rejected before any queue change.

Preparation:
- Group guard (`_assert_group`, `:147-151`).
- Full paged queue snapshot (`_queue`, `:308-321`). The page size is 100, `MAX_QUEUE = 5000` (`:72`), and the `UpdateID`/total are checked to stay stable across pages.
- An encrypted recovery snapshot is saved (`_save_recovery`, `:323-342`).

Staging, one song per call:
- `plugin.add_share_link_to_queue(item["url"], position=0, dc_title=escape(title), timeout=self.timeout)` (`:388-389`), which **appends**.
- Before each call, the full queue is re-read and compared to the expected signatures and `UpdateID` (`:384-386`).
- After each call it checks all of these (`:390-394`):
  - the return value equals `before.total + 1`;
  - the total grew by 1;
  - the old rows are unchanged;
  - the new last row's song ID equals `catalog_id` (`_song_id` regex `song[:/](\d+)` on the unquoted resource URI, `:63-68`).

Replacement:
- `RemoveTrackRangeFromQueue(StartingIndex=1, NumberOfTracks=old_total, UpdateID=<verified>)` (`_remove_range`, `:344-349`, called at `:405`). The comment says the device `UpdateID` guards this destructive range removal (`:403-404`).
- Then `SetAVTransportURI(x-rincon-queue:{uid}#0)`, `Seek(TRACK_NR, 1)` and `Play` (`:413-419`).

Rollback:
- Only while staging, and only if the old prefix is intact and the tail is exactly its own staged songs, it removes that tail with the guarded range removal (`:432-446`).
- Otherwise it reports "partially changed" (`:447-451`).

### What that call sends to Sonos (installed SoCo 0.31.2, `soco/plugins/sharelink.py`)
- `AppleMusicShare.canonical_uri`:
  - `...album/<slug>/<albumId>?i=<songId>` becomes `song:<songId>` (`:157-161`).
  - A bare album link becomes `album:<id>` (`:163-166`).
  - A `pl.` playlist link becomes `playlist:pl....` (`:172-176`).
- Service type is `52231` (`:180-181`), which is Apple Music sid 204 × 256 + 7.
- For a **song**, the magic prefix is `""` and the key is `10032020` (`:59-63`). So:
  - `EnqueuedURI = "song%3a<songId>"`
  - `EnqueuedURIMetaData` = DIDL `<item id="10032020song%3a<songId>" parentID="-1">`, with class `object.item.audioItem.musicTrack` and `desc cdudn = SA_RINCON52231_X_#Svc52231-0-Token` (`:246-264`).
  - No account serial is pinned; Sonos picks the Apple Music account.
- The SOAP call is `AddURIToQueue(InstanceID=0, EnqueuedURI, EnqueuedURIMetaData, DesiredFirstTrackNumberEnqueued=position, EnqueueAsNext=int(as_next))` (`:267-276`). **It returns only `int(FirstTrackNumberEnqueued)`** (`:278-279`). `NumTracksAdded` and `NewQueueLength` are discarded.
- After Sonos resolves the song, the queue row URI looks like `x-sonos-http:song%3a<id>.mp4?...`. The test fake mirrors this (`tests/test_cc_music.py:206`), and `_song_id` relies on it.

### Tests
`tests/test_cc_music.py`:
- `FakeSpeaker.add_share_link_to_queue` always appends and ignores `position` (`:268-280`).
- `RemoveTrackRangeFromQueue` enforces `UpdateID` (`:250-257`).
- The `play_items` tests cover these cases (`:393-437`):
  - replacement order;
  - rollback of its own tail after a failed second append;
  - refusal to overwrite an external change;
  - a partial result on start failure;
  - rejection of non-song URLs.
- There is **no test for positional insertion yet**. The fake would need `position` support that inserts at `position-1` and returns `position`.
- Other files:
  - `control_center/runtime.py:1145-1156`: resolve, then `play_items` on the audio lane.
  - `control_center/simulation.py:47-52`: simulated `play_items`.
  - No `play_next` exists anywhere yet.

---

## 2. SoCo API facts (installed `.venv/Lib/site-packages/soco`, version 0.31.2, `__init__.py:20`)

| API | Signature / behaviour | Source |
|---|---|---|
| `SoCo.add_uri_to_queue(uri, position=0, as_next=False, **kwargs)` | Wraps the URI in a bare `DidlObject` (protocol `x-rincon-playlist:*:*:*`) and calls `add_to_queue`. `@only_on_master`. | `core.py:2354-2364` |
| `SoCo.add_to_queue(queueable_item, position=0, as_next=False, **kwargs)` | `position` is 1-based, 0 = end. `as_next`: "played as the next track in shuffle mode. This only works if play_mode=SHUFFLE". Returns `int(FirstTrackNumberEnqueued)` only. | `core.py:2366-2393` |
| `SoCo.add_multiple_to_queue(items, container=None, **kwargs)` | `AddMultipleURIsToQueue` in chunks of 16 ("we can only add 16 items"). **Hard-codes `DesiredFirstTrackNumberEnqueued=0` and `EnqueueAsNext=0`**, so it cannot insert at a position. `UpdateID=0`. Returns nothing. | `core.py:2395-2429` |
| `ShareLinkPlugin.add_share_link_to_queue(uri, position=0, as_next=False, **kwargs)` | Same argument semantics. `dc_title` kwarg; other kwargs (e.g. `timeout`) go to the SOAP call. Returns `int(FirstTrackNumberEnqueued)`. | `plugins/sharelink.py:216-285` |
| `plex.PlexPlugin.add_to_queue` | Reference pattern: inserting a list at a position is done **one item per call, in reverse order at the same position**. The docstring notes that as_next with albums/playlists in shuffle "will select one track randomly as the next item and shuffle the remaining tracks throughout the queue". | `plugins/plex.py:111-153` (note `:121-126`) |
| Raw `avTransport.AddURIToQueue([...])` | `Service.send_command` returns a dict of **all** out-arguments (`unwrap_arguments`). A direct call therefore gives `FirstTrackNumberEnqueued`, `NumTracksAdded` and `NewQueueLength`. | `services.py:434-510` (`:506`) |
| `SoCo.remove_from_queue(index)` | `RemoveTrackFromQueue(ObjectID="Q:0/<index+1>", UpdateID="0")`. Unguarded. | `core.py:2431-2448` |
| `RemoveTrackRangeFromQueue` | Not wrapped by SoCo. The companion calls it with a real `UpdateID` (`sonos.py:344-349`). | — |
| `get_current_track_info()['playlist_position']` | `GetPositionInfo.Track` (1-based queue row of the current track; `"0"`/empty with an empty queue). Also returns `uri` = `TrackURI`. | `core.py:2004-2036` |
| `get_current_media_info()['uri']` | `GetMediaInfo.CurrentURI`; `x-rincon-queue:<uid>#0` when the queue is the source. The companion already uses this test (`sonos.py:161`, `:186`). | `core.py:2136-2159` |
| `play_mode` | `GetTransportSettings.PlayMode`: `NORMAL`, `REPEAT_ALL`, `REPEAT_ONE`, `SHUFFLE`, `SHUFFLE_NOREPEAT`, `SHUFFLE_REPEAT_ONE`. | `core.py:570-592` |
| `get_queue(start, max_items)` | Browse `Q:0`. Returns items plus `update_id` and `total_matches`, so a **slice** can be read cheaply. | `core.py:2275-2318` |
| `music_source_from_uri` | `x-sonosapi-radio:`, `x-sonosapi-hls:` and similar are RADIO; `x-rincon-stream:` is LINE_IN; `x-sonos-vli:...,airplay:` is AIRPLAY. | `core.py:1874-1902`, `:3083-3096` |

UPnP action signatures (SoCo wiki, svrooij docs):
- `AddURIToQueue(InstanceID, EnqueuedURI, EnqueuedURIMetaData, DesiredFirstTrackNumberEnqueued, EnqueueAsNext) -> {FirstTrackNumberEnqueued, NumTracksAdded, NewQueueLength}`
- `AddMultipleURIsToQueue(... UpdateID, NumberOfURIs, EnqueuedURIs, EnqueuedURIsMetaData, ContainerURI, ContainerMetaData, DesiredFirstTrackNumberEnqueued, EnqueueAsNext) -> {..., NewUpdateID}`
- `RemoveTrackRangeFromQueue(InstanceID, UpdateID, StartingIndex (1..len), NumberOfTracks) -> {NewUpdateID}`

---

## 3. Sonos semantics from public sources

### 3.1 Position, not the flag
**svrooij Sonos API docs, AVTransport:**
- `DesiredFirstTrackNumberEnqueued`: "use `0` to add at the end or `1` to insert at the beginning".
- Remark: "In NORMAL play mode the songs are added prior to the specified `DesiredFirstTrackNumberEnqueued`." In other words, insertion at that row, pushing later rows down.
- Sources: https://sonos.svrooij.io/services/av-transport and https://sonos-ts.svrooij.io/sonos-device/services/av-transport-service.html

**Home Assistant Sonos integration** (dev branch, fetched 2026-09-25):
- `enqueue: next` does `pos = (self.media.queue_position or 0) + 1`, then `share_link.add_share_link_to_queue(media_id, position=pos, ...)` for share links (`media_player.py` `_play_media_sharelink`, ≈ lines 728-760). It does the same with `soco.add_to_queue(item, position=pos)` for music-service items (≈ 700-707).
- `queue_position` is the 1-based `playlist_position` (`media.py` ≈ 137-139).
- Neither call sets `as_next`.
- This is the same plugin and call the companion uses, in production for Apple Music share links.
- Sources: https://github.com/home-assistant/core/blob/dev/homeassistant/components/sonos/media_player.py and https://github.com/home-assistant/core/blob/dev/homeassistant/components/sonos/media.py

**node-sonos-http-api, Apple Music action:**
- `next`: `nextTrackNo = player.coordinator.state.trackNo + 1; addURIToQueue(uri, metadata, true, nextTrackNo)`, so position +1 and `EnqueueAsNext=1` together.
- `now` also switches the transport to `x-rincon-queue:` first if it is not the source.
- Source: https://github.com/jishi/node-sonos-http-api/blob/master/lib/actions/appleMusic.js (lines 56-70)
- README: `/RoomName/applemusic/{now,next,queue}/album:{albumID}` (https://github.com/jishi/node-sonos-http-api#spotify-apple-music-and-amazon-music-experimental)

**node-sonos:**
- `Sonos.prototype.queue(options, positionInQueue = 0)` always sends `EnqueueAsNext: 1`, and its doc says position "defaults to end of queue, 0 to explicitly set end of queue".
- So `EnqueueAsNext=1` with position 0 **appends**; the flag alone does not produce "next" in normal mode.
- Source: https://github.com/bencevans/node-sonos/blob/master/lib/sonos.js (≈ lines 519-534)

**Conflicting claim, low weight:**
- A small AI-generated PR says that `EnqueueAsNext=1` with `DesiredFirstTrackNumberEnqueued=0` lets "the speaker resolve the position itself" (https://github.com/ux-mark/home-fairy/pull/215, Spotify, June 2026).
- This contradicts node-sonos's long-standing append behaviour and SoCo's docstring, and it has no published live evidence.
- **Do not rely on it.** The live test can settle it cheaply as an optional extra.

**Sonos's own definition** of Play Next: "Add the track(s) to the queue after the current track and play them next" (https://support.sonos.com/en-us/article/add-tracks-to-the-queue).

### 3.2 What `EnqueueAsNext` is for
- SoCo: "Whether this URI should be played as the next track in shuffle mode. This only works if play_mode=SHUFFLE" (`core.py:2375-2376`; https://docs.python-soco.com/en/latest/api/soco.core.html).
- SoCo Plex plugin note, for shuffle: multi-track items "will select one track randomly as the next item and shuffle the remaining tracks throughout the queue" (`plugins/plex.py:121-126`).
- **Conclusion:** in NORMAL, REPEAT_ALL and REPEAT_ONE the position does the work and the flag is at most harmless. node-sonos-http-api sends both. In shuffle the flag at best makes one track next. **An album cannot be guaranteed to play next, in order, while Sonos shuffle is on.**

### 3.3 Current source is not the queue
- Sonos: "Sonos products don't use the queue when playing music from radio services" (https://support.sonos.com/en-us/article/using-the-queue-in-the-sonos-app).
- With radio (including Apple Music stations), line-in, TV, AirPlay or Spotify Connect, `GetPositionInfo.Track` does not describe a queue row.
- Home Assistant then inserts at row 1 of the dormant queue without switching source, so nothing audible happens next.
- node-sonos-http-api `next` does not check; `now` switches to the queue and skips.
- **For the knob's "Play next (queue kept)" the only honest behaviour is to refuse** (see messages) and point the user to Play.

### 3.4 Empty queue
- `total_matches == 0` (and `playlist_position` is `0` or empty).
- Inserting would add the album to an idle queue. It would not play and it is not "after the current song". Refuse and point to Play.
- Play (replace) is equivalent here.

### 3.5 One call for an album container, or per-track?
**Sonos can expand a container in one call:**
- Examples: SoCo share-link album `EnqueuedURI = x-rincon-cpcontainer:1004206calbum%3a<albumId>` (`sharelink.py:39-43`, `:243`), and node-sonos-http-api `x-rincon-cpcontainer:0004206c<album:id>` (`appleMusic.js:14-20`).
- `NumTracksAdded` reports the count, and `DesiredFirstTrackNumberEnqueued` places the block.
- Home Assistant and node-sonos-http-api use exactly this for "next" with albums and playlists.

**This does not fit the companion's model:**
- The container is a **catalog** album. The companion plays a **library** album's own tracks mapped one by one, and explicitly forbids whole-catalog-album substitution (`apple_music.py:3-5`). A catalog album can differ in edition, bonus tracks, or tracks the user did not add.
- Library playlists (`p.` IDs) have no share-link or container form in SoCo (the regex needs `pl.`, `sharelink.py:172-176`).
- A library-album container URI tried by a SoCo user did not play (https://github.com/SoCo/SoCo/issues/995; the maintainer points to share links instead).
- **Per-track insertion is therefore the correct default for both albums and playlists.** A catalog-album container could be a later optimisation, only when the resolved tracks provably equal the catalog album. It would still need the same slice verification.

**`AddMultipleURIsToQueue` is not a shortcut:**
- It takes at most 16 URIs per call (SoCo issue #485, Wireshark shows Sonos's own controller chunking at 16: https://github.com/SoCo/SoCo/issues/485; `core.py:2410`).
- SoCo's wrapper cannot set a position (`core.py:2425-2426`).
- Using it with the bare share-link `song%3a<id>` form is untested anywhere I found.

### 3.6 Shared risks
- Share-link enqueueing to S2 broke once (UPnP 800) until a Sonos firmware update (https://github.com/SoCo/SoCo/issues/969, Dec 2024).
- Apple Music share-link support was added in SoCo 0.26 (https://github.com/SoCo/SoCo/pull/886).
- An open SoCo PR adds tests that assert `position` and `EnqueueAsNext` pass through unchanged (https://github.com/SoCo/SoCo/pull/1017, 2026-09-24, unmerged, no live test).

---

## 4. Recommended implementation (for the build; nothing edited)

### 4.1 Call sequence (new `SonosAdapter.play_next(items, expected_group_revision, expected_track_id)`)
Reuse `play_items`' URL validation, lock, group guard and `ShareLinkPlugin`. Do **not** take a recovery snapshot or remove anything unless rolling back its own verified block.

```
validate items exactly as play_items (sonos.py:355-362)          # verified album?i=song links
ctx = _assert_group(rev); c = ctx[1].coordinator
if not c.get_current_media_info()["uri"].startswith("x-rincon-queue:"):  -> refuse NOT_QUEUE
mode = c.play_mode
if mode in {"SHUFFLE","SHUFFLE_NOREPEAT","SHUFFLE_REPEAT_ONE"}:           -> refuse SHUFFLE (default)
track = c.get_current_track_info()
if expected_track_id and _track_id(track) != expected_track_id:           -> TrackChanged
head = c.get_queue(0, 1); T0 = total_matches; U0 = update_id
P = int(track["playlist_position"] or 0)
if T0 == 0 or not 1 <= P <= T0:                                           -> refuse NOTHING_PLAYING
if T0 + N > MAX_QUEUE:                                                    -> refuse FULL
anchor = _signature(c.get_queue(P-1, 1)[0])     # the current song's own row
re-check: _track_id(c.get_current_track_info()) unchanged                 # shrink the race window
for i, item in enumerate(items):                 # forward order, consecutive rows
    want = P + 1 + i
    desired = want if want <= T0 + i else 0      # current is last row -> append (0 = end)
    got = plugin.add_share_link_to_queue(item["url"], position=desired,
                                         dc_title=escape(item["title"]), timeout=self.timeout)
    if got != want: -> verification failure (stop, go to rollback)
    # on an ambiguous timeout: read c.get_queue(want-1, 1); continue only if
    # _song_id(row) == item's catalog_id, otherwise stop and rollback
S = c.get_queue(P-1, N+2)                        # one slice read (paged if N > ~98)
check: S.total_matches == T0 + N
check: _signature(S[0]) == anchor                # current song still directly before the block
check: [_song_id(x) for x in S[1:1+N]] == songs  # exact order, duplicates kept
now = int(c.get_current_track_info()["playlist_position"])
check: now == P  or  P+1 <= now <= P+N           # finished song moved playback INTO our block = fine
                                                 # now > P+N => song ended before 1st insert; block is behind it
return _state(...)   # knob: "Queued next", toast "Queued next · {album}"
```

Rollback, on any failed check after at least one insert:
- Re-read the slice.
- Remove only if all of these hold:
  - the rows `[P+1 .. P+k]` are exactly the k songs this call inserted;
  - `anchor` is intact;
  - the current track is **not** inside that block.
- Remove with `RemoveTrackRangeFromQueue(InstanceID=0, UpdateID=<update_id just read>, StartingIndex=P+1, NumberOfTracks=k)`, the same guarded helper as `sonos.py:344-349`.
- If the song ended before the first insert (`now > P+N`), the block can be removed the same way and retried once at the new `P`. Or report "Song changed · try again".
- Never remove rows that might be somebody else's.

Why forward order at consecutive positions rather than Plex-style reverse order at one position:
- It gives the knob a correct partial state if a later song fails.
- If the current song ends mid-sequence, playback moves into the first inserted track and the rest still follow it in order.

`as_next`:
- Leave it `False` in NORMAL, REPEAT_ALL and REPEAT_ONE. This is exactly Home Assistant's proven call, and the companion's existing call with only `position` changed.
- Only consider `True` if a later decision allows Play next in shuffle and the live test's optional shuffle case shows what Sonos does.

Verification data:
- The plugin returns only `FirstTrackNumberEnqueued` (`sharelink.py:278-279`), which is enough together with the slice read.
- If `NumTracksAdded` and `NewQueueLength` are wanted as extra checks, call `coordinator.avTransport.AddURIToQueue` directly with the identical URI and metadata. `send_command` returns every out-argument (`services.py:506`).

Cost:
- N `AddURIToQueue` calls plus about 4 small reads.
- Do not repeat `play_items`' full-queue re-read before and after every song (`sonos.py:384`, `:390`). Insertion is non-destructive, and the single slice check at the end, plus the per-call return value, is sufficient.
- Long playlists should be capped or show a pending state. The knob could show `Queueing…` until the verified result arrives, because 1.5 s `Queued next` must only follow verification.

### 4.2 Failure modes and user-visible text (knob meta / toast)

| Condition | Detection | Knob / toast |
|---|---|---|
| Source is radio, line-in, TV, AirPlay or Spotify Connect | media URI not `x-rincon-queue:` | `Not playing from queue · use Play` |
| Sonos shuffle on | `play_mode` in SHUFFLE* | `Shuffle is on · turn it off to play next` (or queue anyway with `Queued · shuffle on`, product decision) |
| Empty queue / no current row | `T0 == 0` or P out of range | `Nothing playing · use Play` |
| Repeat-one | `REPEAT_ONE` | Queue normally, toast `Queued next · repeat one is on` |
| Song changed before or during insert | track ID / anchor / `now > P+N` | Auto-rollback, then `Song changed · try again` |
| Sonos rejects the share link (UPnP 800 / 804 / 402) | `SoCoUPnPException` on the first call | `Sonos refused this album · nothing queued` |
| Partial insert, rollback impossible | slice mismatch | `Partly queued · check the Sonos queue` (same honesty as `sonos.py:450`) |
| Group changed | `_assert_group` | Existing GroupChanged text |
| Apple Music resolution failed | `MusicUnavailable` | Existing messages (`apple_music.py`, "Nothing was queued.") |

### 4.3 Albums vs playlists
- Adapter path: identical. Both arrive as ordered lists of verified catalog songs.
- Differences are only in size and presentation:
  - Playlists can be long (up to `MAX_TRACKS = 5000`, `apple_music.py:30`). That is one SOAP call per song, so cap Play next, for example at 100 songs, or show progress.
  - Playlists can contain duplicates, which are kept.
  - Playlists mix albums, which is exactly the "rows show their own cover and `artist · album`" case in `specs/01:221`.
- Per-row covers in Up next come from the queue rows' own `albumArtURI` after Sonos resolves each song. The live test should confirm that inserted rows carry title, artist and album art metadata, and not just the `dc_title` the companion sends.

### 4.4 Correction for the handoff text
Change `README.md:224` from "`AddURIToQueue` with `EnqueueAsNext=1`" to:

> `AddURIToQueue` per song with `DesiredFirstTrackNumberEnqueued = current playlist_position + 1 + i` (`EnqueueAsNext` only affects shuffle). Available only while the queue is the source and shuffle is off.

`specs/01:221` needs the same correction.

---

## 5. Proposed LIVE test: minimal and reversible (NOT run; needs the user's go-ahead)

**Setup**
- Use a small standalone script built on `SonosAdapter`'s pinned room and coordinator. Do not use the companion app, and open no serial or COM port.
- The only Apple Music calls are the normal read-only library calls to resolve 2 songs from one Recently Added album the user picks.
- Print titles, positions and song IDs only. Never print tokens, credentials or settings.

**Preconditions, confirmed by the user**
- The pinned room is playing or **paused** from its Sonos queue. The first run should be paused, so it has zero audible effect.
- Shuffle is off.
- The queue has at least 3 rows and the current row is not the last.
- If playing, more than 60 s remain in the song.

**Steps**
1. **Read only (R0):**
   - `GetMediaInfo` URI (must start `x-rincon-queue:`);
   - `play_mode`;
   - `GetPositionInfo` (P, TrackURI, title) and transport state;
   - `get_queue(0,1)` (T0, U0);
   - rows P-1..P+1 (title, URI).
   Abort if any precondition fails.
2. **Write, 2 calls:**
   - `add_share_link_to_queue(url_song1, position=P+1, dc_title=...)`, expecting `P+1`.
   - `add_share_link_to_queue(url_song2, position=P+2, dc_title=...)`, expecting `P+2`.
   - Variant for extra evidence: call `avTransport.AddURIToQueue` directly with the identical URI and metadata. Expect `NumTracksAdded=1` and `NewQueueLength = T0+1`, then `T0+2`.
3. **Read and verify (R1):**
   - `get_queue(0,1)`: T1 == T0+2 and U1 ≠ U0.
   - Rows P..P+3 are: the original current row unchanged; song 1 (`_song_id` match); song 2; the original row P+1.
   - `GetPositionInfo`: still P, same TrackURI. Transport state unchanged, so there was no interruption.
   - Record whether rows P+1 and P+2 have creator, album and `albumArtURI`. Up next covers need them.
4. **Undo (W3), only if R1 fully verified and the current track is not P+1 or P+2:** `RemoveTrackRangeFromQueue(InstanceID=0, UpdateID=U1, StartingIndex=P+1, NumberOfTracks=2)`.
5. **Read (R2):** T2 == T0; rows P-1..P+1 equal R0 exactly; P unchanged.
6. **Report:** a table of R0, R1 and R2 with pass or fail per check, plus the elapsed time per AddURIToQueue call (to size album and playlist latency).

**Blast radius**
- At most 2 extra songs after the current one, for a few seconds.
- Nothing is played, skipped or cleared.
- If step 4 is skipped because a check failed, the script prints the exact rows so the user can delete them in the Sonos app. R0 is kept for comparison.

**Optional extras (separate approval each)**
- **(a) Playing:** repeat while playing, to confirm there is no audible glitch.
- **(b) Full album:** use the whole album, to measure latency, then remove the range.
- **(c) EnqueueAsNext alone:** `EnqueueAsNext=1` with position 0 for 1 song. Does it append or go next? This settles the home-fairy claim. Then remove the row.
- **(d) Shuffle:** only if the user already uses shuffle; observe placement and what plays next. Then remove.
- **(e) Catalog album container:** a one-call catalog album container at P+1 (`NumTracksAdded`, order). Then `RemoveTrackRangeFromQueue` of that count.

---

## Sources
Local, read-only:
- `control_center/sonos.py:63-68, 72, 147-151, 159-175, 177-204, 308-349, 351-451`
- `control_center/apple_music.py:3-5, 30, 251, 270-277, 305-383`
- `control_center/runtime.py:1145-1156`
- `control_center/simulation.py:47-52`
- `tests/test_cc_music.py:203-280, 393-437`
- `.venv/Lib/site-packages/soco/__init__.py:20`
- `soco/core.py:570-592, 732-761, 1874-1902, 2004-2036, 2136-2159, 2275-2318, 2354-2457, 3083-3096`
- `soco/plugins/sharelink.py:38-69, 152-187, 216-285`
- `soco/plugins/plex.py:111-209`
- `soco/services.py:434-510`
- `design-reference/design_handoff_nano_d_master/README.md:75, 193, 224, 238`
- `design-reference/design_handoff_nano_d_master/specs/01-FEATURES-explorers-snap-seek.md:76, 221`

Public:
- Sonos: [Add tracks to the queue](https://support.sonos.com/en-us/article/add-tracks-to-the-queue) · [Using the queue](https://support.sonos.com/en-us/article/using-the-queue-in-the-sonos-app)
- [svrooij AVTransport](https://sonos.svrooij.io/services/av-transport) · [node-sonos-ts AVTransport](https://sonos-ts.svrooij.io/sonos-device/services/av-transport-service.html) · [SoCo wiki: UPnP services](https://github.com/SoCo/SoCo/wiki/Sonos-UPnP-Services-and-Functions)
- [SoCo core docs](https://docs.python-soco.com/en/latest/api/soco.core.html) · SoCo [#485](https://github.com/SoCo/SoCo/issues/485), [#969](https://github.com/SoCo/SoCo/issues/969), [#995](https://github.com/SoCo/SoCo/issues/995), [PR #886](https://github.com/SoCo/SoCo/pull/886), [PR #1017](https://github.com/SoCo/SoCo/pull/1017)
- Home Assistant Sonos [media_player.py](https://github.com/home-assistant/core/blob/dev/homeassistant/components/sonos/media_player.py) and [media.py](https://github.com/home-assistant/core/blob/dev/homeassistant/components/sonos/media.py)
- node-sonos-http-api [appleMusic.js](https://github.com/jishi/node-sonos-http-api/blob/master/lib/actions/appleMusic.js) and [README](https://github.com/jishi/node-sonos-http-api) · node-sonos-discovery [Player.js](https://github.com/jishi/node-sonos-discovery/blob/master/lib/models/Player.js)
- node-sonos [sonos.js](https://github.com/bencevans/node-sonos/blob/master/lib/sonos.js) · node-sonos-ts [sonos-device.ts](https://github.com/svrooij/node-sonos-ts/blob/main/src/sonos-device.ts)
- Conflicting claim: [home-fairy PR #215](https://github.com/ux-mark/home-fairy/pull/215)
