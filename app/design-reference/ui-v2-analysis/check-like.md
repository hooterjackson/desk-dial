# Check: Like (Up next, button 3) through Apple Music

Question from the user: can the desktop app set favourites through Apple Music? Liked songs do not appear in the "Favourite playlists" section. If Like can't work, the README suggests putting Play next on that button instead.

Design intent:
- Master README §4 (line 78) maps Up next buttons to Back · Shuffle · **Like** · Play.
- §7.1 (line 194) shows a pink heart on liked rows.
- §8 (line 226) proposes `PUT /v1/me/ratings/songs/{id}` (value 1). It notes that this favourites the **song** and does not affect "Favourite playlists".
- The fallback is **Play next** for the highlighted track.
- spec 01 §6 (line 222) says Like "feeds the explorer's Favourite playlists". That contradicts README §8, and the README takes precedence (README §0). The README is correct on this point: see §2.4 below.

Method: I read the code and public documentation only. I made no call to Sonos or to api.music.apple.com, did not open credentials, and did not run the app.

---

## Verdict: **works, with caveats**

The companion already has everything it needs to call the Apple Music rating and favourites endpoints:
- the same host
- the same two headers
- the same kind of user token that another MusicKit-JS app uses to write favourites

The catalog song id for each Up next row can be read from the Sonos queue item URI. The companion already does this, and it was verified live on 22 Sep (§3).

Caveats:
1. **The Favorite mapping is strongly implied, not stated.** Apple's Ratings docs still say "likes (1) / dislikes (-1)". They never say that rating 1 is the star/Favorite the Music app has shown since iOS 17.1. The evidence for the mapping is strong (§2.2), and the live test in §5 confirms it.
2. **Un-like must be `DELETE`, never value -1.** Value -1 is "dislike" (Suggest Less).
3. **Favouriting can add the song to the user's library.** Apple's web guide says so, and it would then show up in Recently Added. Rows from other services, radio, or library-only uploads get no heart (Like is disabled for them).
4. **Some code and copy must change** before this ships (§4.5):
   - The consent page says the companion "does not … modify your library".
   - `AppleMusicClient` is GET-only.
   - The "sign-in expired" state is only fed by Recently Added requests today.

The fallback (Play next for the highlighted row) is also implementable with what exists, and needs no Apple Music call (§4.6).

---

## 1. What Apple Music access the companion has today

| Item | Finding | Source |
|---|---|---|
| Developer token (JWT) | Minted locally **per request**: ES256, `iss` = Team ID, `kid` = Key ID, `exp` = now + 1 h, signed with the user's MusicKit `.p8` key. It never goes stale. A static `developer_token` fallback is also accepted. | `control_center/credentials.py:125-143` |
| Key import | Settings has fields for Apple Team ID and MusicKit Key ID, plus a "Choose .p8 key" button. The key is validated locally with no network call. There is a CLI equivalent. | `ui.py:1614-1620`, `credentials.py:106-122`, `setup_music.py:1-38` |
| Music-User-Token | Obtained with the **MusicKit JS v3 web flow** in the user's normal browser. A one-use loopback server on `127.0.0.1:<random>` serves a page that loads `js-cdn.music.apple.com/musickit/v3/musickit.js`, calls `MusicKit.configure` and then `authorize()`, and POSTs the token back. The POST is protected by a nonce and an Origin check, and the session expires after 15 minutes. It is stored as `music_user_token`. | `credentials.py:146-252` (token POST 198-230, stored at 219, page 243-249); started by `ui.py:1716-1730` ("Authorize Apple Music", `webbrowser.open` at 1727) |
| Storage | Windows **DPAPI** with CurrentUser scope and UI_FORBIDDEN, in `credentials.bin` behind a magic header. Writes are atomic. The installed app keeps it in `%LOCALAPPDATA%\NanoDControlCenter\data`. | `credentials.py:30-61, 64-103`; `ui.py:1719`; `DESKTOP.md:47-50`; demo `README.md:71-74` |
| Refresh | The user token has **no refresh**. Each request re-reads the encrypted store, so re-authorizing in Settings takes effect without a restart. Apple does not document a token lifetime. Music Assistant, which uses the same web flow, documents about 180 days. | `apple_music.py:92-96`, `DESKTOP.md:151-153`; [Music Assistant – Apple Music](https://www.music-assistant.io/music-providers/apple-music/) |
| Headers sent | `Authorization: Bearer <dev JWT>`, `Music-User-Token: <token>`, `Accept: application/json`, with `allow_redirects=False` | `apple_music.py:103-108` |
| Endpoints called today (**all GET**) | `/v1/me/library/recently-added` (28, 196, 235); `/v1/me/library/songs/{id}` (365); `/v1/me/library/{albums\|playlists}/{id}/tracks` (368); `/v1/me/library/songs/{id}/catalog` (313); `/v1/me/storefront` (298); `/v1/catalog/{sf}/songs/{id}` (322); `/v1/catalog/{sf}/songs/{id}/albums` (340); `/v1/catalog/{sf}/albums/{id}` (349) | `apple_music.py` (line numbers in parentheses) |
| Error mapping | 401/403 map to "Apple Music authorization expired or access was denied. Reconnect in settings." 429 maps to "temporarily limiting requests". Any other non-200 is a generic failure. Exceptions are sanitized, so they never carry URLs, headers or tokens. | `apple_music.py:109-123` |
| "Sign-in expired" recovery state | **Confirmed real.** `_needs_login()` matches "authorization / credentials / connect apple music" (`controller.py:83-85`). `runtime.music_signin_expired` is set from **Recently Added list results** and the Home warm-up (`runtime.py:239-241, 955-964, 1032-1038`). The knob then shows "Apple Music sign-in expired / Renew on your PC" (`controller.py:1134`). This state exists only because a user token exists. | as cited |
| Current consent copy | "Allow the knob companion to read your Recently Added library. This page does not play music or modify your library." The module docstring also says "Read-only Apple Music library browsing". | `credentials.py:245`, `apple_music.py:1` |

**Token scope:** Apple documents no scopes for Music User Tokens. The same token is used for all personalized endpoints, reads and writes alike ([User Authentication for MusicKit](https://developer.apple.com/documentation/applemusicapi/user-authentication-for-musickit); every ratings page says only "This endpoint requires a music user token").

There is independent evidence that a MusicKit-JS-v3 token can write ratings. Music Assistant obtains its token with the same `configure` + `authorize()` web flow ([musickit_wrapper.html](https://github.com/music-assistant/server/blob/dev/music_assistant/providers/apple_music/musickit_auth/musickit_wrapper.html)). It then `PUT`s `me/ratings/{type}/{id}` to set favourites ([library.py `set_favorite`](https://github.com/music-assistant/server/blob/dev/music_assistant/providers/apple_music/library.py)).

**So no new token or re-authorization is technically required.** Re-consent with updated copy is still advisable for honesty (§4.5).

---

## 2. Apple Music API: ratings, favourites and favourite playlists

### 2.1 Song rating endpoints (they exist today)

Source: [Ratings](https://developer.apple.com/documentation/applemusicapi/ratings-api).

| Action | Request | Result |
|---|---|---|
| Rate a catalog song | `PUT /v1/me/ratings/songs/{id}` with body `{"type":"rating","attributes":{"value":1}}` | 200 `RatingsResponse` `{"data":[{"id":"…","type":"ratings","attributes":{"value":1}}]}` ([Add a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/add-a-personal-content-rating-33dop)) |
| Clear a rating | `DELETE /v1/me/ratings/songs/{id}` | **204**, no body ([Delete a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/delete-a-personal-content-rating-3a3a2)) |
| Read one | `GET /v1/me/ratings/songs/{id}` | 200 ([Get a Personal Song Rating](https://developer.apple.com/documentation/applemusicapi/get-a-personal-content-rating-4k9c0)). The docs do not say what an unrated song returns; see §4.3. |
| Read many | `GET /v1/me/ratings/songs?ids=a,b,c` | 200 ([Get Multiple Personal Song Ratings](https://developer.apple.com/documentation/applemusicapi/get-multiple-personal-content-ratings-6wab5)) |
| Library-song variants | `PUT`, `GET` and `DELETE` on `/v1/me/ratings/library-songs/{id}` | ([Add a Personal Library Song Rating](https://developer.apple.com/documentation/applemusicapi/add-a-personal-content-rating-8z1fn)) |

- Allowed values: "likes (1) or dislikes (-1) … These are the only two ratings supported."
- Tokens: the developer JWT plus the Music-User-Token. That is exactly what `_get` already sends.
- Catalog and library stay in sync: "the personal ratings for that song's catalog ID and library ID … stay synced". A catalog id is therefore enough, even for songs that are in the library.

### 2.2 Is rating 1 the Music app's "Favorite"?

Apple does **not** state it outright. The evidence:
- **iOS 17.1 release notes (Apple):** "Favorites expanded to include songs, albums, and playlists, and you can filter to display your favorites in the library" ([About iOS 17 Updates](https://support.apple.com/en-us/118723)).
- **Current Apple Support guides** describe only **Favorite** and **Suggest Less / Dislike**. There is no Love anymore ([Rate and personalize music on Mac](https://support.apple.com/guide/music/rate-and-personalize-music-musf7da17c25/mac)).
- **Press coverage:** "The old Love system is no longer available in iOS 17.1" and "Stars have replaced hearts" ([iDownloadBlog](https://www.idownloadblog.com/2023/09/29/ios-17-1-new-apple-music-features-roundup/)). Loved songs "haven't disappeared" ([RouteNote](https://routenote.com/blog/where-are-my-loved-songs-on-apple-music/)). Love was folded into Favorite; it was not a separate state that got deleted.
- **The ratings API still has exactly two values, like (1) and dislike (-1).** These match the app's two choices today, Favorite and Suggest Less.
- **Third-party production use:** Music Assistant implements "favourite" for Apple Music tracks, albums and playlists as `PUT me/ratings/{type}/{id}` with value 1, and reads it back with `GET me/ratings/{type}?ids=` (batches of up to 200, `value == 1`). Its docs say favourites are "sent back to Apple Music for albums, playlists and tracks" ([docs](https://www.music-assistant.io/music-providers/apple-music/), [library.py](https://github.com/music-assistant/server/blob/dev/music_assistant/providers/apple_music/library.py), [api_client.py](https://github.com/music-assistant/server/blob/dev/music_assistant/providers/apple_music/api_client.py)).
  - Note: Music Assistant *un*-favourites with value -1, which is a dislike. The companion must use `DELETE` instead.
- **Known lag:** ratings written through the API may not appear in the Music apps until they resync. The workaround reported was toggling Sync Library on iOS or relaunching Music on macOS. An Apple engineer asked for a Feedback report ([forum 692194](https://developer.apple.com/forums/thread/692194), 2021).

### 2.3 Newer, explicit favourites surface (documented, not in the handoff)

- **`POST /v1/me/favorites?ids[…]=…`** ("Add resource to favorites"): "if a customer favorites a song, the song is added to their `favorite songs` playlist". It returns **202 Accepted**, which Apple defines as "may not have completed". It supports bulk and mixed types ([Add resource to favorites](https://developer.apple.com/documentation/applemusicapi/add-resource-to-favorites)).
  - The parameter is documented only as `ids` ("The ids of the specific type"). By analogy with `POST /v1/me/library?ids[albums]=…` (same `#ids` identifier, [Add a Resource to a Library](https://developer.apple.com/documentation/applemusicapi/add-a-resource-to-a-library)), the song form is `ids[songs]={id}`. **To be verified.**
  - **No "remove from favorites" endpoint is documented.** The only documented removal is `DELETE /v1/me/ratings/songs/{id}`.
- **`inFavorites` (boolean) attribute:** "Whether the catalog resource ID is in the person's favorites". It appears on:
  - [Songs.Attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)
  - [LibrarySongs.Attributes](https://developer.apple.com/documentation/applemusicapi/librarysongs/attributes)
  - [Playlists.Attributes](https://developer.apple.com/documentation/applemusicapi/playlists/attributes-data.dictionary)
  - [LibraryPlaylists.Attributes](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/attributes-data.dictionary)

  It is not marked "Extended". Whether it is populated on a plain request with a user token is **to be verified**.

Together these confirm that "Favorite" is a first-class Apple Music API concept. They make it very likely, but not certain, that rating 1 is the same stored state.

### 2.4 "Favourite playlists" (the explorer's tab 3)

- The README is right: liking a *song* does not favourite any playlist. A liked song is added to Apple's auto-generated **Favorite Songs** playlist ([Apple web guide](https://support.apple.com/guide/music-web/mark-items-as-favorites-apdmc4eaeb66/web)). That playlist is a smart/auto playlist, and `/v1/me/library/playlists` is reported **not to return smart playlists** ([forum 112677](https://developer.apple.com/forums/thread/112677)). So even that playlist may not appear in the tab.
- **Source for the tab:** `GET /v1/me/library/playlists` (paged with `limit`/`offset`; [Get All Library Playlists](https://developer.apple.com/documentation/applemusicapi/get-all-library-playlists)), then filter on `attributes.inFavorites == true`. Other available attributes: `canEdit`, `isPublic`, `hasCatalog`, `dateAdded`, `playParams`, `artwork`.
  - Alternative: batch `GET /v1/me/ratings/library-playlists?ids=…` and keep value 1 ([Ratings](https://developer.apple.com/documentation/applemusicapi/ratings-api), "Get Multiple Personal Library Playlist Ratings").
- **Caveat:** `inFavorites` is described in terms of the "catalog resource ID". Private user playlists with `hasCatalog: false` may not report it. Verify this in the read-only step of §5.
- **"Pinned" playlists:** I found no API for pinned items. The closest equivalents are favourited playlists (above) and user-created ones (`canEdit: true`).
- The explorer can then play a favourited playlist through the existing `resolve()` path for `kind == "playlist"` (`apple_music.py:366-371`).

---

## 3. Identity mapping: Sonos queue row to Apple catalog song id

**How the companion enqueues.** `play_items` accepts only items with a numeric `catalog_id` and a `https://music.apple.com/{sf}/album/…/{albumId}?i={catalog_id}` URL (`sonos.py:351-362`). SoCo's `AppleMusicShare` turns that URL into `song:{catalog_id}` and enqueues `EnqueuedURI = "song%3a{id}"`, with DIDL item id `10032020song%3a{id}` and service `SA_RINCON52231…` (52231 = 204·256+7) (`.venv/Lib/site-packages/soco/plugins/sharelink.py:59-63, 152-187, 243-273`).

**How the companion reads identity back.** `_song_id(item)` unquotes each queue resource URI and matches `song[:/](\d+)` (`sonos.py:63-68`). It is already load-bearing: staging, replacement and start-of-playback checks all compare the queue against the expected catalog ids (`sonos.py:391-394, 407, 421`). The unit test fake uses `x-sonos-http:song%3a{id}.mp4` (`tests/test_cc_music.py:206`).

**Live proof (22 Sep 2026).** `tools/quiet_sonos_probe.py:211-217` appended one song and required `_song_id(staged.items[-1]) == catalog_id`. It also required `exact_song_uri(TrackURI, catalog_id)` during playback (`:41-43`, `:263-266`). The report shows `single_song_staged: ok` and `exact_song_playing_while_muted: ok` (`diagnostics/quiet-sonos-probe.json:25-31`). **On this household, every row the companion queued is mappable to its catalog id, reliably.**

**Rows queued by other controllers** (Sonos app, AirPlay and so on):
- **Apple Music catalog tracks.** Public reports give `x-sonos-http:song%3a{catalogId}.mp4?sid=204&flags=8224&sn=N`, where the number "is in fact the ID of the played song" ([SoCo #812](https://github.com/SoCo/SoCo/issues/812)). Newer integrations use `x-sonosapi-hls-static:` with item id `00032020song%3a…` ([media-manifold-ha](https://github.com/HaniKazmi/media-manifold-ha)). `_song_id`'s scheme-agnostic regex matches both. → **Like enabled.**
- **Apple Music library-only tracks** (uploads, or picks from "My Library" in Sonos). Some integrations use `librarytrack%3Ai.{libraryId}` ([sonos-web-bridge](https://github.com/MephistoJB/sonos-web-bridge)). `_song_id` returns None for these. They *could* go to `PUT /v1/me/ratings/library-songs/i.{id}` if that `i.` id equals the Apple Music API library-song id. That is **unverified**, so disable Like for these rows in v1.
- **Other services, radio, line-in, local files.** → **Like disabled.** Show the button at the disabled 0.14 level (README §6).

**Library vs catalog, and storefront.** Rating endpoints take the catalog id with **no storefront**, and catalog and library ratings stay synced (§2.1). A storefront is needed only to *read* `inFavorites` or metadata through `/v1/catalog/{sf}/songs?ids=…`. The existing `_get_storefront()` already caches it (`apple_music.py:296-303`).

**Account caveat.** The Sonos household's linked Apple Music account and the account authorized in the companion are independent. If they differ (for example a family member's), Like writes to the **companion-authorized** account. That is the one the explorer reads, so it is consistent, but worth a line in Settings.

---

## 4. Build recommendation

### 4.1 Requests the companion would send

| Purpose | Request | Expected response |
|---|---|---|
| Like | `PUT https://api.music.apple.com/v1/me/ratings/songs/{catalogId}` with headers `Authorization: Bearer <developer_token(credentials)>`, `Music-User-Token: <music_user_token>`, `Content-Type: application/json`, `Accept: application/json`. Body: `{"type":"rating","attributes":{"value":1}}` | 200 with `data[0].attributes.value == 1`. Treat that as confirmation. |
| Un-like (toggle off) | `DELETE https://api.music.apple.com/v1/me/ratings/songs/{catalogId}`, same headers | 204. **Never send value -1**, which means "Suggest Less". |
| Heart state | `GET https://api.music.apple.com/v1/me/ratings/songs?ids={id1},{id2},…` in chunks of ≤ 100, sent once when Up next opens and again when the Sonos queue revision changes | Liked means value 1. A missing entry means not liked. Value -1 (disliked elsewhere) also shows no heart. |

- **Optional alternative for heart state:** read `inFavorites` from `GET /v1/catalog/{sf}/songs?ids=…`. The Up next view needs this call anyway for 600 px covers and album names, so the heart state could come along for free. Keep it only if §5 shows the attribute is populated.
- **If §5 shows rating 1 does *not* appear as Favorite:** switch Like to `POST /v1/me/favorites?ids[songs]={id}` (202, then confirm by reading back). Keep `DELETE` ratings for un-like only if §5 proves it clears a POSTed favourite. Otherwise make Like add-only, or use the fallback.

### 4.2 UI and state
- **Confirmed-state semantics,** matching volume (demo `README.md:122-123`): press → pending (working comet) → **heart pops and the pink bloom plays only after 200/204**. On failure, play the head shake; the heart stays unchanged.
- **One in-flight request per song.** Ignore presses while pending.

### 4.3 Error handling
- **401 / 403:** `_get`'s message already contains "authorization", so `_needs_login` is true. But `music_signin_expired` is only set for `kind == "recent"` results (`runtime.py:955-964`). The Like effect must feed the same flag, so the knob shows the existing "Apple Music sign-in expired / Renew on your PC" state (`controller.py:1134`) and the design's recovery state (README §7.2).
  - Apple's docs: 401 means a developer-token or subscription problem, and 403 means a Music-User-Token problem or unaccepted privacy terms ([HTTP Status Codes](https://developer.apple.com/documentation/applemusicapi/http-status-codes)).
- **429:** use the existing message. No automatic retry loop; the user can press again.
- **404 on the multi-id GET** (possible when nothing in the set is rated): treat as "none liked", not as an error. `_get` currently raises on any non-200 (`apple_music.py:113-114`).
- **Network or other failures:** use the existing sanitized messages (`apple_music.py:119-123`). Never log ids together with titles or tokens.

### 4.4 Rate limits
- Apple publishes no number. Exceeding the per-developer-token limit gives 429, which "resolves itself shortly after the request rate has reduced" ([Generating developer tokens](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens)).
- Like is paced by the user. The state read is one request per Up next open per ≤ 100 rows. That is negligible. For reference, Music Assistant throttles itself to about 4 requests per second.

### 4.5 Code and copy deltas this feature forces (not done; this is a read-only check)
- **`apple_music.py`:**
  - `_get` is GET-only and requires a `data` list (`:116-117`), so it cannot carry 204 or 202 responses.
  - Add a small `_send(method, path, json, expected)` that reuses `_safe_path`, the credential loader, the headers, `allow_redirects=False` and the sanitized errors.
  - Add `like(id)`, `unlike(id)` and `ratings(ids)` on top of it.
  - Update the "Read-only" docstring (`:1`).
- **`credentials.py:245` consent copy** currently promises the page does not "modify your library". Change it to say the companion reads the library and marks songs as Favorites when you press Like, which can add them to your library. Re-consent is optional technically but advisable.
- **`runtime.py`:** route Like results into `music_signin_expired` (§4.3).
- **`sonos.py`:** Up next needs a full-queue read (reuse `_queue`, `:308-321`). Today `_state` reads only `max_items=1` (`:183`). Map rows with `_song_id`.
- **LEDs:** `alive_lights.py:895-906` "bloom" currently draws in `pal.green`. The pink bloom (255,40,90) from README §6 still needs its colour. This is minor and part of the cc5.4 LED work.

### 4.6 Fallback: Play next for the highlighted row (implementable now)
- **In NORMAL or REPEAT modes, move the row rather than duplicating it.** The row is already in the Sonos queue, so send `avTransport.ReorderTracksInQueue(InstanceID=0, StartingIndex=i, NumberOfTracks=1, InsertBefore=current+1, UpdateID=<queue.update_id>)`. The action is in Sonos AVTransport ([svrooij AVTransport](https://sonos.svrooij.io/services/av-transport)).
  - SoCo has no wrapper for it, but its service proxy dispatches any action (`soco/services.py:192-218`). That is the same way `sonos.py:344-349` calls `RemoveTrackRangeFromQueue`.
  - Guard it with UpdateID and verify with `_queue` + `_signature` read-back, as `play_items` does.
  - No Apple Music call is needed, and it works for any service's row.
- **To duplicate instead:** `AddURIToQueue` with the row's own URI and DIDL (`didl_metadata` / `to_didl_string`, already used at `sonos.py:326-329`) and `DesiredFirstTrackNumberEnqueued=current+1`.
- **Correction to README §8:** SoCo documents `EnqueueAsNext` as effective only in SHUFFLE (`soco/core.py:2375-2376`, `sharelink.py:227-228`). In NORMAL mode, items go "prior to the specified DesiredFirstTrackNumberEnqueued" ([svrooij](https://sonos.svrooij.io/services/av-transport)). So "insert after the current track" means `DesiredFirstTrackNumberEnqueued = current + 1`, not `EnqueueAsNext=1`.
- **Shuffle:** queue order ≠ play order and Sonos does not expose shuffle history (demo `README.md:61-64`). Either use `EnqueueAsNext=1` or disable the action while Sonos shuffle is on.

---

## 5. Proposed minimal, reversible LIVE test (NOT run; needs the user's go-ahead)

Form: a one-off script modelled on `tools/quiet_sonos_probe.py`. It is dry-run by default and needs `--execute` for any write. It reuses `CredentialStore`, `developer_token` and the sanitized error handling. It logs only status codes, booleans and counts: **no tokens, no titles**.

About 10 Apple requests in total.

**A. Read-only census of the Sonos queue.**
1. Read the full queue with `SonosAdapter._queue`.
2. Report the total and the counts of rows matching `song:<digits>`, rows matching `librarytrack:i.`, and other rows.
3. For a better test, first add one catalog track and one "My Library" track from the Sonos app.

**B. Read-only Apple checks.** Pick test song **S**: a track from an album **already in the library**, for example the Recently Added single used in the 22 Sep probe (`diagnostics/quiet-sonos-probe.json` → `catalog_id`). This makes the "adds to library" side effect moot.
1. `GET /v1/me/ratings/songs?ids=S` must show S **unrated**. If S is already rated, abort so the user's real state is never overwritten.
2. `GET /v1/catalog/{sf}/songs?ids=S` and record whether `inFavorites` is present and its value.
3. `GET /v1/me/library/playlists?limit=100`, first page only, and count `inFavorites` true / false / absent. The user compares the count with the favourited playlists they see in the Music app. This validates the source for §2.4.

**C. Favourite S** (write 1 of 2).
1. `PUT /v1/me/ratings/songs/S {"type":"rating","attributes":{"value":1}}` → expect 200 with value 1.
2. Read back with `GET` ratings (expect 1) and the catalog song (`inFavorites` true?).
3. The user checks the Music app (relaunch it or wait for sync): is the **star shown** on S, and is S in **Favorite Songs**?

**D. Remove it** (write 2 of 2).
1. `DELETE /v1/me/ratings/songs/S` → expect 204.
2. `GET` shows S unrated, and `inFavorites` is false.
3. The user confirms the star is gone and S has left Favorite Songs.

**E. Only if C did not show as Favorite.**
1. `POST /v1/me/favorites?ids[songs]=S` → expect 202.
2. Poll the reads for ≤ 30 s. The user checks for the star.
3. Then `DELETE` the rating and confirm it clears. If it does not clear, stop and ask the user to un-favourite S in the Music app. That is the only possible residue.

**Pass:** C shows the star and a Favorite Songs entry, D removes both, and A shows every companion-queued row as mappable → build Like as in §4.

**Fail:** if neither C nor E produces a removable Favorite → ship the Play next fallback (§4.6).
