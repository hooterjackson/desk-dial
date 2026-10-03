# Research: artwork resolution for the full-screen overlays

Question: what is the highest-resolution album, playlist and track artwork the Windows companion can fetch, and how should the new full-screen designs (Music explorer, Up next) be sized to those assets?

Scope: read-only research on 2026-09-25.
- **Not touched:** no request to the Sonos speakers, no Apple Music API call with the user's tokens, no credential or settings file opened, no serial port, and the companion was not run.
- **Measured:** real artwork was sampled from Apple's **public** endpoints only: the iTunes Search/Lookup API, the public `mzstatic.com` image CDN, and one public `music.apple.com` playlist page. This PC's displays were read with Win32 calls.
- **Evidence files** (temporary, in a scratch folder `<scratch>/artwork-research/`): `results.json` (17 albums × 8 sizes, formats, latency), `results2.json` (80 more albums, maximum size only), `results3.json` (CDN cache state per size, 12 albums), and the scripts `sample.py`, `sample2.py`, `sample3.py`.

Paths are relative to `app/` unless they start with `soco/`, which means `.venv/Lib/site-packages/soco/` (SoCo 0.31.2). `B&S:Lnnn` is a line in `design-reference/design_handoff_nano_d_master/prototypes/Browse and Snap.dc.html`.

---

## Plain-language summary

- **Apple artwork is a size template.** You can ask for any square size up to 10,000 px, but you never get more than the original upload. Apple does not upscale. Each artwork object states that maximum (`width`/`height`), so the companion can know it before downloading (§1.1, §1.5).
- **Real maximums vary widely.** Across 97 sampled catalog albums:
  - 62 % are 3000 px or larger;
  - 95 % are at least 1400 px, which is Apple's current delivery minimum;
  - 5 % stop at **600 px**. These are older back-catalogue albums such as *Tidal Glass*.
  
  Apple's own editorial playlists are 3840 px. User-made playlists often have **no artwork at all** in the API. The design's 2 × 2 mosaic of album covers avoids that problem (§1.2, §1.3).
- **On this PC the two biggest covers need 680 px and 760 px.** This PC has one 5120 × 1440 monitor at 100 % scaling, so the design scales by k = 2. The explorer's centre card is 680 px and the Up next cover is 760 px. On a 4K monitor they would be 1020 px and 1140 px.
  - The handoff says "fetch at 600 px" (README §8). That is too small for these two covers and fine for everything else (§3).
- **Recommendation: three fetch sizes.**
  - **1200 px** for the two large covers (and for the neighbours about to become one).
  - **600 px** for side cards and mosaic tiles.
  - **240 px** for Up next row covers.
  - The 90 px ambient blur needs only about **64 px**, taken from any copy already cached.
  - 1200 and 600 are also the sizes Apple's CDN most often has ready: about 15 ms, against 0.3 to 1 s for unusual sizes (§1.6, §4.1).
- **Sonos covers are too small for Up next, but there is a way around it.** Sonos's own cover for a track is about 400 px (the earlier measurement), too soft for a 760 px cover. Every Sonos queue row's URI contains the Apple Music song id, which the companion already parses. One Apple Music API call for up to 300 ids returns full-quality artwork for the whole queue (§2.3).
- **The cost is small if only on-screen covers are decoded.**
  - About 40 covers take about 4 MB at 600 px and about 13 MB at 1200 px as JPEG.
  - Only what is on screen needs decoding, at screen size: about 10 to 20 MB.
  - **Never request 3000 px.** A quarter to two-thirds of those files exceed the companion's 2 MiB download cap, they are cold at the CDN, and nothing on screen needs them (§1.4, §4.1).
- **When the source is too small, don't stretch it far.** This covers 600 px albums on a 4K screen, Sonos-only art and radio logos.
  - Up to 1.5× larger: upscale smoothly.
  - Beyond 1.5×: show the sharp cover on a blurred mat made from itself.
  - While images load, show the artwork's own `bgColor` so no card sits empty (§4.3, §4.4).

## Recommendation at a glance

| Element (design px) | Needed on this PC (k = 2) | Needed at 4K (k = 3) | **Request** | Fallback when the source is smaller |
|---|---|---|---|---|
| Explorer centre card (340) | 680 px (762 during Play) | 1020 px (1142) | **1200** (2000 only if k > 3.5) | ≤ 1.5× upscale, else matted (§4.3) |
| Explorer cards at distance ±1 | 408 px, but they become the centre on the next detent | 612 px | **1200**, prefetched | as above |
| Explorer cards at ±2 and the rest of the page | 286 px | 428 px | **600** | upscale |
| Playlist mosaic tile (170) | 340 px | 510 px | **600** per tile album | < 4 distinct albums: one full-bleed cover |
| Ambient layer (blur 90) | σ = 180 px over 5760 × 2080 | σ = 270 px | **no fetch**: 64 px from any cached copy | `bgColor`, then the cover |
| Up next cover (380) | 760 px (790 during Play) | 1140 px (1186) | **1200** (focused track ±1) | Sonos 400 px → matted |
| Up next row cover (56) | 112 px (119 during Play) | 168 px | **240** (Apple template), or Sonos `/getaa` | upscale |
| Knob (unchanged) | 240 px LCD; about 302 px floating preview | about 604 px floating preview | 480 today; optionally the shared 600 | — |

---

## 1. Apple Music artwork

### 1.1 How an artwork object works (documented)

The `Artwork` object ([docs](https://developer.apple.com/documentation/applemusicapi/artwork); JSON source: `https://developer.apple.com/tutorials/data/documentation/applemusicapi/artwork.json`) has these attributes:

| Attribute | Required | Meaning (Apple's wording, abridged) |
|---|---|---|
| `url` | yes | "The URL to request the image asset. `{w}x{h}` must precede image filename, as placeholders for the `width` and `height` values … For example, `{w}x{h}bb.jpeg`" |
| `width`, `height` | yes | "The maximum width/height available for the image." |
| `bgColor` | no | "The average background color of the image." |
| `textColor1…4` | no | Text colours to use over `bgColor`. |

Beyond the documented template:
- **Apple's own web client asks for more placeholders.** It uses `{f}` (format) and a crop code, which Apple's web templates show as `{c}`. A public playlist page served `…/{w}x{h}bb.{f}` and `…/{w}x{h}SC.DN01.{f}` (scratch `hits.html`, the "Today's Hits" page).
- The web client requests these with the query parameters `art[url]=f` / `art[url]=c` ([bomberfish.ca](https://bomberfish.ca/blog/apple-music-api)).
- **The companion accepts only the documented placeholders.** It substitutes `{w}`, `{h}` and `{f}`→`jpg`, and rejects any other `{…}` token (`control_center/artwork.py:110-135`). It sends neither `art[url]` parameter (`control_center/apple_music.py:196, 235`), so its templates are the documented `{w}x{h}bb.jpg` form.

### 1.2 Per resource type

| Resource | `artwork` in the docs | What it is in practice | Max size |
|---|---|---|---|
| **Catalog albums** (`albums`) | **required** ("The artwork for the album") | The label's cover on `is1-ssl.mzstatic.com/image/thumb/Music…/…/{w}x{h}bb.jpg` | 600 to 4000 px measured (§1.3). Apple's current delivery rule: "recommended … 3000 by 3000 pixels or larger. The minimum size is 1400 by 1400" ([Apple Music Provider Support](https://itunespartner.apple.com/music/support/5215-digital-packaging-music)). Older back-catalogue predates that rule. |
| **Catalog songs** (`songs`) | **required**, "The album artwork" | The album's cover: same image and same max | as the album |
| **Catalog playlists** (`playlists`) | **optional** | Editorial playlists carry designed art on `…/image/thumb/Features…/…png/{w}x{h}bb.{f}`, including Apple's title typography. "Today's Hits" declares `width`/`height` **3840**, and a 10000 request returned 3840 × 3840 (scratch `hits.html`; §1.5). The same page also has a 1080 px `containerArtwork` with crop `SC.DN01`. | 1080 to 3840 px |
| **Library albums** (`library-albums`, what Recently Added lists) | **required**, "The album artwork" | For catalog-backed albums, a catalog-style `mzstatic` template (a `library-songs` example uses `Features1/…/{w}x{h}bb.jpeg` with 1200 × 1200, [forum 101328](https://developer.apple.com/forums/thread/101328)). **Not verified for this user's library.** Reading it needs the user's token, which was out of bounds. | Expected to equal the catalog cover; unverified |
| **Library playlists** (`library-playlists`, Favourite playlists) | **optional** | **User-made playlists often have no `artwork` at all.** A June 2025 forum report shows `/v1/me/library/playlists` objects without artwork even with `extend`/`include`, and it is unanswered ([forum 788448](https://developer.apple.com/forums/thread/788448)). Apple's apps show a client-side mosaic that the API "does not give" (search summary of [discussions 251303151](https://discussions.apple.com/thread/251303151)). Artwork cannot be set through the API (Apple engineer, [forum 707608](https://developer.apple.com/forums/thread/707608)). Since iOS 17.1, users can pick generated designs in which the playlist title is drawn on the art ([MacRumors](https://www.macrumors.com/2023/09/28/custom-apple-music-playlist-art-options/)). **Whether the API exposes those designs was not found.** Editorial playlists added to the library have `hasCatalog: true` and presumably keep their editorial art. | none, or up to 3840 |
| **Library songs** (`library-songs`) | **required**, "The album artwork" | Catalog-matched songs: the album cover. **Uploaded (non-matched) songs:** no public source documents the host or size of their art. | unknown for uploaded |

Consequences for this project:
- **The companion never plays uploaded-only media.** Songs with `hasCatalog: false` are marked unavailable (`control_center/apple_music.py:268-269`). Library tracks without a unique catalog song raise "unsupported or uploaded-only media" (`apple_music.py:305-318`). So uploaded tracks never reach the Sonos queue, and Up next never needs their art. Recently Added can still *list* an uploaded album.
- **An artwork URL off `*.mzstatic.com` is dropped.** It fails the allowlist (`artwork.py:82-84`), `apple_artwork_url` then returns `""`, and the item has no cover (`artwork.py:132-135`).
- **The design's mosaic avoids the missing-artwork problem.** Explorer playlists are drawn as a 2 × 2 mosaic of *album* covers (01 §5; B&S:L123-127, L925). The tiles come from the playlist's tracks, whose artwork is "the album artwork" and required, rather than from the playlist's own optional artwork.

### 1.3 Measured maximum sizes (public catalog sample)

Method: for each album, the iTunes Search API's `artworkUrl100` was rewritten to `10000x10000bb.jpg` and the returned image's dimensions were read.
- Pass 1: 17 hand-picked albums from 1920s recordings to 2026 singles.
- Pass 2: 80 albums spread across the result lists of 20 genre and era searches, such as bossa nova, choro, forró, afro house, netlabel, chiptune EP, punk demo 1980 and gospel 1960s.

Maximum edge, **n = 97**:

| Max edge | Count | Share |
|---|---|---|
| 600 (one 600 × 612) | 5 | 5 % |
| 1400 to 1440 | 12 | 12 % |
| 1500 to 1600 | 17 | 18 % |
| 2000 to 2560 | 3 | 3 % |
| **3000** | 53 | 55 % |
| 3200 to 4000 | 7 | 7 % |

- **At least 1200 px: 95 %. At least 3000 px: 62 %. Median: 3000 px.**
- **The 600 px items are old back-catalogue:**
  - *Tidal Glass* (1959);
  - Robert Johnson, *King of the Delta Blues Singers* (1961);
  - John Williams, *The Great Paraguayan* (1995);
  - *The Indispensible Django Reinhardt* (1983 issue, 600 × 612);
  - Infected Rain, *EP 2009* (2011).
- **Big-label remasters are often 1500 px.** *Abbey Road* (2019 mix), *Thriller*, *Random Access Memories*, *Legend*, the Glenn Gould *Goldberg Variations* and the Bessie Smith *Empress of the Blues* compilation all stop at 1500 px.
- **New releases are never below 1400 px, and usually 3000 or more.** Of the 43 releases dated 2020 or later: 36 were ≥ 3000, 6 were 1400 to 1440, and 1 was 2000.
- **4 of 80 were slightly non-square** (600 × 612, 1423 × 1411, 1500 × 1520, 3532 × 3575). Always centre-crop to a square, as `ImageOps.fit` already does (`artwork.py:434`).

### 1.4 Bytes and JPEG properties per requested size

Pass 1 (17 albums; only rows where the returned size equals the requested one):

| Request | n | Bytes: min / median / max | Edge HIT |
|---|---|---|---|
| 240 | 17 | 9 KB / 19 KB / 33 KB | 14 / 17 |
| **600** | 17 | 42 KB / **89 KB** / 163 KB | 15 / 17 |
| **1200** | 15 | 120 KB / **347 KB** / 570 KB | 16 / 17 |
| 2000 | 7 | 540 KB / 1.21 MB / 1.37 MB | 2 / 17 |
| 3000 | 7 | 0.74 MB / **2.57 MB** / 3.16 MB | 6 / 17 |

- **Encoding is uniform.** Every default response is a baseline JPEG, 4:2:0 subsampled, with no ICC profile and an estimated IJG quality of about 94. That held for all 17 albums at every size.
- **Pass 3** (12 less popular albums) gives similar medians: 600 → 104 KB, 1200 → 314 KB.
- **The 3000 px size breaks the companion's download cap.** Five of the seven 3000 px files exceed `MAX_DOWNLOAD = 2 MiB` (`artwork.py:50`). So do 13 of the 80 pass-2 originals, and 13 of the 53 that were 3000 px or more.
- **Decode cost on this PC** (Pillow 12.3, one 3000 px source, best of 10):

  | Source | Decode | LANCZOS resize to 680 |
  |---|---|---|
  | 600 | 0.8 ms | — |
  | 1200 | 3.8 ms | 9.8 ms |
  | 2000 | 12.4 ms | 21.5 ms |
  | 3000 | 27.6 ms (18.6 ms with `draft()`) | 43 ms |

### 1.5 Arbitrary sizes and formats

Measured on `is1-ssl.mzstatic.com` (pass 1 `formats`, plus direct probes):
- **Any integer size works, up to 10,000.** 680, 760, 1020 and 683 all returned exactly that size. `10000x10000bb.jpg` returned the original; **`10001` and above return HTTP 400** (`application/json`, 129 bytes).
- **Apple never upscales.** A request above the original returns the original: *Tidal Glass* returns 600 × 600 for 680, 1020, 1200 and 10000.
- **`bb` fits the image inside the box.** `1000x600bb` returned 600 × 600 for a square cover. Non-square boxes behave oddly (`600x1000cc` returned 1000 × 1000), so **always request square sizes**. For square sources, `cc` and `sr` returned the same bytes as `bb`.
- **Formats** (by changing the extension; undocumented, but it works today). At 600 px:

  | Extension | *Abbey Road* | *Tidal Glass* | *Thriller* | Notes |
  |---|---|---|---|---|
  | `.jpg` | 163 KB | 61 KB | 89 KB | |
  | `.webp` | 53 KB | 23 KB | 28 KB | about ⅓ of the JPEG |
  | `.png` | 699 KB | 355 KB | 611 KB | 4 to 7× the JPEG, no benefit |

  - `.heic` returned `image/heic` (8.6 KB), which Pillow cannot decode without a plugin.
  - `.avif` → HTTP 400.
  - `.gif` returned a JPEG-sized payload labelled `image/gif`: not useful.
- **A quality suffix works:** `-60` gives about q86, `-100` or `-999` gives about q99 (a 3000 px `-999` file was 5.8 MB).
- **Advice: keep `.jpg` with the default quality.** It is the documented form, and the companion's template substitution produces it (`artwork.py:129`). WebP would cut bytes by about 3×, but it relies on undocumented extension rewriting and was a CDN miss more often.

### 1.6 Latency (this PC's network, 2026-09-25)

- **CDN-hot sizes are fast.** Requests on a warm connection that hit the edge return in about **12 to 20 ms**. In pass 1 (popular albums), 600 and 1200 were edge hits for 15 and 16 of 17 albums, with a median time to first byte of **14 ms** and **15 ms**.
- **Uncommon sizes are cold at the CDN.**
  - 2000, 5000 and 10000 were mostly misses. Median time to first byte: 212 ms, 137 ms and 573 ms; worst: 1.7 s, 1.8 s and 2.5 s.
  - Odd sizes (683, 761, 1021) were **misses on the first request every time**: 94 to 1036 ms, median 678 ms. The same URL was a hit the second time.
- **Less popular albums** (pass 3, 12 albums, total time):

  | Size | Median | Edge hits |
  |---|---|---|
  | 1200 | 52 ms | 7 / 12, the best-cached size |
  | 600 | 131 ms | 3 / 12 |
  | **480** (what the companion requests today) | **308 ms** | 2 / 12 |
  | 1400 to 3000 | 450 to 830 ms | 0 / 12 |

- **A new TLS connection adds about 210 to 280 ms.** That was the first request after a dropped connection. The companion already keeps one `requests.Session` per worker (`artwork.py:747-753`), so this cost is paid once.
- **The CDN allows long-lived caching.** Responses carry `Cache-Control: max-age=14144932, no-transform` (about 164 days), so a local cache is allowed.
- **Apple Music API latency was not measured**, because that would need the user's tokens.

---

## 2. What the companion fetches today, and the natural source for each new surface

### 2.1 Today

| What | Source | Size | Where |
|---|---|---|---|
| Recently Added cover (knob LCD) | Apple library `attributes.artwork` template | **480 px** (`ARTWORK_SIZE`) | `apple_music.py:273`; `artwork.py:52` |
| Ring accent per list item | the same template | 96 px (`ACCENT_SIZE`) | `apple_music.py:275`; `artwork.py:53` |
| Now-playing cover (Home, Tracks) | the Sonos track's `album_art` (the speaker's `/getaa` proxy) | whatever Sonos serves: **about 400 px** by the earlier measurement (not re-measured) | `sonos.py:194-195`; `soco/core.py:2126-2131`; `soco/music_library.py:56-69` |

What each download produces:
- a 240 px scrimmed preview (`artwork.py:434-439`);
- a 120 px RGB565 transfer (`:442`);
- the artwork2 240 px JPEG of at most 32 KB (`artwork.py:327-345`; `control_center/presentation.py:93-96`);
- a desktop-only 480 px scrimmed q90 JPEG (`artwork.py:255-269`; `FLOATING_KNOB.md:57`).

Limits and caches:
- **Allowlist:** HTTPS `*.mzstatic.com` on port 443, or plain HTTP to a configured private IPv4 speaker on port 1400 with path `/getaa` (`artwork.py:69-96`). No credentials and no redirects are sent (`artwork.py:484-512`).
- **Download bounds:** at most 2 MiB (`artwork.py:50`); at most 16 M pixels (`:51`); timeouts of 2 s connect, 3 s read and 8 s total (`:493, :505`); only `image/*` content types (`:500-502`).
- **Template sizes** are clamped to 16…3000 (`artwork.py:127`).
- **Caches:**
  - `ArtworkService` LRU of 64 entries (`presentation.py:101`; clamp 128 at `artwork.py:537`), with 3 prefetch workers (`presentation.py:100`);
  - `AccentService` LRU of 256 (`artwork.py:900-903`).
- **All cached covers are scrimmed.** The explorer needs **unscrimmed** covers, so neither cached copy can be reused as-is (as `03-desktop.md:242-245` also notes).
- **The Apple Music API** is `api.music.apple.com` with a developer token plus the Music-User-Token (`apple_music.py:27, 104-108`). The companion already calls catalog songs (`apple_music.py:322`) and library track lists (`apple_music.py:366-368`).

### 2.2 Natural source per new surface

| Surface | Items | Natural artwork source |
|---|---|---|
| Explorer, Recently Added | `library-albums` (and `library-playlists`) from `/v1/me/library/recently-added` (`apple_music.py:28, 251`). The user's sample page was 10 albums, mostly singles (`diagnostics/apple-music-readiness.json:5-85`). | The item's own `attributes.artwork` template. It is already there: `apple_music.py:273` expands it at 480 px, and `width`/`height`/`bgColor` are simply not kept yet. |
| Explorer, Favourite playlists | `library-playlists` (README §8 "Favourite playlists source") | Mosaic: the first 4 **distinct** album artworks among the playlist's tracks (`/v1/me/library/playlists/{id}/tracks`, first page only). The same call `resolve()` makes, which pages through all tracks (`apple_music.py:366-368`). The playlist's own `artwork` is optional and often missing (§1.2). The ambient layer uses "a playlist's first cover" (B&S:L935). |
| Up next, album queue | Sonos queue rows | One cover for the whole album (B&S:L1039, L1048). Use the Apple catalog cover via the song id (§2.3). |
| Up next, playlist or Play-next rows | Sonos queue rows | Rows at 112 px can use either the row's `/getaa` (about 400 px, enough) or the Apple template at 240. The big 760 px cover needs the Apple template (§2.3). |
| Now playing (knob, floating knob) | Sonos current track | Today `/getaa`. Optionally the Apple catalog cover via the song id. |

### 2.3 From a Sonos queue row to full-resolution Apple artwork

1. **The row URI carries the catalog song id.**
   - The companion enqueues `EnqueuedURI = "song%3a<catalogId>"` through SoCo's `AppleMusicShare` (`soco/plugins/sharelink.py:152-187, 59-63`; `sonos.py:388-389`).
   - Sonos turns it into a queue row such as `x-sonos-http:song%3a1362668489.mp4?sid=204&flags=8224&sn=3`. That is visible in a public `/getaa` URL on the [Sonos Community](https://en.community.sonos.com/controllers-and-music-services-228995/sonos-link-to-album-art-is-local-ip-even-though-it-s-cloud-music-being-played-6864641) and in [SoCo #812](https://github.com/SoCo/SoCo/issues/812), as cited in `research-apple-music-play-next.md:169`.
2. **The companion already parses it.** `_song_id()` unquotes each resource URI and matches `song[:/](\d+)` (`sonos.py:63-68`). Staging and replacement depend on it (`sonos.py:393, 407, 421`), and the test fake uses the same URI (`tests/test_cc_music.py:203-206`). `check-like.md:118-125` also shows that the regex matches the newer `x-sonosapi-hls-static:` form.
3. **The current track works the same way.** `get_current_track_info()` returns `uri` (`soco/core.py:2036`), which `sonos.py:155` already hashes. The same regex yields the playing song's id.
4. **One API call covers a whole queue page.** `GET /v1/catalog/{storefront}/songs?ids=…` accepts "a maximum fetch limit" of **300** ids ([docs](https://developer.apple.com/documentation/applemusicapi/get-multiple-catalog-songs-by-id)). Each song's required `attributes.artwork` is its album cover, with its maximum `width`/`height` (§1.2). The companion already knows its storefront (`apple_music.py:296-303`) and the auth pattern.
5. **Why not the public iTunes Lookup API.** It is documented only for 100 px and 60 px artwork ("sized to 100×100 pixels or 60×60 pixels"). It is meant for promotional use and is "limited to approximately 20 calls per minute" ([iTunes Search API](https://performance-partners.apple.com/search-api)). It would also add a new host.
6. **Why Sonos's own image is small.** Image resizing is a Sonos *app* feature: "the Sonos app will replace an image with the right resolution for each particular use", with sizes up to 1500 × 1500 ([Sonos docs](https://docs.sonos.com/docs/add-album-art)). A player's `/getaa` proxy only serves what the service's metadata gave it, which is consistent with the about 400 px seen earlier.
7. **Fallback.** Rows that do not match an Apple song (radio, other services, line-in) keep their `/getaa` art and follow the small-source rules in §4.3.

---

## 3. This PC's display and element sizes

### 3.1 Monitors (read with Win32 as per-monitor-aware V2; read-only)

| Monitor | Primary | Resolution (physical) | Work area | Scaling | Other |
|---|---|---|---|---|---|
| `\\.\DISPLAY1` | **yes (only monitor)** | **5120 × 1440** | 5120 × 1392 | **96 DPI = 100 %** (system DPI 96) | EDID `SAM7454`, 119 × 34 cm (about 49″, 32:9), raw 109 px/in, 240 Hz on an RTX 4090 |

The companion is per-monitor-aware V2 (`app.py:27`, `standalone.py:1741`, `control_center/overlay.py:1042-1045`). The overlays therefore draw in **physical pixels**, so the Windows scaling setting does not change pixel counts; only physical resolution does.

### 3.2 Scaling rule assumed

The rule is **uniform s = k = min(W/1280, H/720)**, with the 1280 × 720 stage centred on the monitor. This is exactly what the window carousel already does (`control_center/carousel_render.py:179-183, 221-229`; `03-desktop.md:26-29`).
- **This PC:** k = min(4, 2) = **2**. The stage is 2560 × 1440 at x = 1280. Blur and frost cover the whole monitor.
- **1440p at 100 %:** k = 2.
- **4K at 200 %:** k = min(3840/1280, 2160/720) = **3**. It is physical 3840 × 2160; the 200 % setting is irrelevant for a per-monitor-aware app.
- **Also checked:** 1080p gives k = 1.5; 5K gives k = 4.

### 3.3 Device pixels per element

Values are design px × scale × k. "Transient" values are brief animation peaks (Play grow; B&S:L922, L1035, L1079).

| Element | Design size × scale | **This PC** (5120 × 1440, k = 2) | 1440p / 100 % (k = 2) | 4K / 200 % (k = 3) |
|---|---|---|---|---|
| Explorer centre card (01 §5; B&S:L122) | 340 × 1.00 | **680** | 680 | 1020 |
| — Play grow (transient) | 340 × 1.12 | 762 | 762 | 1142 |
| Explorer card at d = ±1 | 340 × 0.60 | 408 | 408 | 612 |
| Explorer card at d = ±2 | 340 × 0.42 | 286 | 286 | 428 |
| Explorer card at d ≥ 3 | opacity 0 (B&S:L917) | not drawn | — | — |
| Mosaic tile, centre card (B&S:L123-127) | 170 × 1.00 | 340 | 340 | 510 |
| Mosaic tile at d = ±1 / ±2 | 170 × 0.60 / 0.42 | 204 / 143 | 204 / 143 | 306 / 214 |
| Ambient box (monitor + 160·k per side; `03-desktop.md:90-91`) | — | 5760 × 2080 | 3200 × 2080 | 4800 × 3120 |
| Ambient cover "cover"-fit (B&S:L407) / blur σ = 90·k (B&S:L105) | — | 5760² / σ 180 | 3200² / σ 180 | 4800² / σ 270 |
| **Ambient source needed** (sample spacing ≤ σ/2, so N ≥ 2·side/σ) | — | **64** | 36 | 36 |
| Up next cover (01 §6; B&S:L158) | 380 × 1.00 | **760** | 760 | 1140 |
| — Play (transient) | 380 × 1.04 | 790 | 790 | 1186 |
| Up next row cover, focused (B&S:L175) | 56 × 1.00 | 112 | 112 | 168 |
| — row at ±1 / Play (B&S:L1028, L1035) | 56 × 0.78 / 1.06 | 87 / 119 | 87 / 119 | 131 / 178 |
| Window picker card (not artwork: a live DWM thumbnail) | 400 × 250 | 800 × 500 | 800 × 500 | 1200 × 750 |
| Snap-tray slot (01 §7) | 176 × 110 | 352 × 220 | 352 × 220 | 528 × 330 |
| Floating knob LCD (ring 360 logical px = 286 design px; `FLOATING_KNOB.md:49`) | 240 × 360/286 | about 302 | about 302 | about 604 (the 480 px hi-res cover would be upscaled 1.26×) |
| Knob hardware LCD | 240 | 240 | 240 | 240 |

**Required source pixels = the device pixels above.** Downscaling from a larger source with LANCZOS is always fine. The two elements that exceed 600 px on this PC are the explorer centre card and the Up next cover. The ±1 explorer cards count too, because a turn moves them to the centre within 420 ms.

---

## 4. Recommendation

### 4.1 Which size to request per element

Use a **ladder of sizes that are warm at Apple's CDN**: 240, 600, 1200, and 2000 only for k > 3.5. Rules:
- **Request** the smallest rung ≥ need ÷ 1.1. Up to 10 % upscale is invisible, so a 612 px need is served by 600.
- **Cap** the request at the item's known maximum, min(`artwork.width`, `artwork.height`), because Apple returns the original anyway.

Why not exact sizes such as 680 or 760? Each odd size is almost always a CDN miss: 0.3 to 1 s on first view (§1.6). The 1200 rung costs about 3× the bytes of an exact 680 (about 330 KB against about 115 KB), but it arrives in about 15 to 50 ms and serves both large elements up to 4K.

| Element | Ladder pick at k = 2 (this PC and 1440p) | Pick at k = 3 (4K) | Notes |
|---|---|---|---|
| Explorer centre, and d = ±1 prefetch | 1200 | 1200 | Also covers the Play grow (762 / 1142). |
| Explorer d = ±2 and the rest of the page | 600 | 600 | Draw the 600 immediately; swap in the 1200 when a card nears the centre. |
| Mosaic tiles (4 per playlist) | 600 | 600 | 340 / 510 px needed. |
| Up next cover (focused track ±1) | 1200 | 1200 | Album queue: one fetch in total. |
| Up next rows | 240 | 240 | 112 / 168 px needed; one batch catalog call gives every row's template (§2.3). |
| Ambient | no fetch | no fetch | Downsample any cached copy to 64 px; show `bgColor` until one exists. |
| Knob | unchanged (480) | unchanged | Optional: fetch the shared 600 and derive the 240 and 480 knob images from it. That is one download instead of two, and 480 is a cold size (§1.6). It changes the knob's art keys once. |

For 5K and larger (k ≥ 4, needs of 1360 to 1520 px), use **2000 for the two large elements only**. The largest measured 2000 px file was 1.37 MB, within the 2 MiB cap. **Never 3000:** 5 of 7 (pass 1) and 13 of 53 (pass 2) such files exceed `MAX_DOWNLOAD` (§1.4). They are also mostly CDN misses, and `apple_artwork_url` already stops at 3000 (`artwork.py:127`).

### 4.2 Caching and budgets (about 40 covers)

| Store | Per cover | 40 covers |
|---|---|---|
| Encoded 600 JPEG | 89 to 104 KB median (42 to 163 KB) | about **4 MB** (2 to 6.5 MB) |
| Encoded 1200 JPEG (large-cover candidates only) | 314 to 347 KB median (120 to 570 KB) | about **13 MB** (5 to 23 MB) worst case, if all 40 become large |
| Encoded 240 JPEG (rows) | about 20 KB | about 0.8 MB |
| Decoded RGBA at *fetch* size (1200² + 600²) | 5.76 + 1.44 MB | **288 MB: do not keep decoded** |
| Decoded RGBA at *device* size (k = 2) | 680²: 1.85 MB; 760²: 2.31 MB; 408²: 0.67 MB; 340²: 0.46 MB; 112²: 0.05 MB | only what is on screen |

- **Memory: keep encoded bytes, not bitmaps.** Use an LRU keyed by (template URL, size), with a budget of about 24 MB for encoded bytes. This is separate from the knob's scrimmed `ArtworkService` cache.
- **Decode on demand, at device size, on a worker thread.**
  - Decode cost is 4 ms for 1200 px, plus about 10 ms to resize to 680 (§1.4).
  - Keep only the visible set:
    - explorer: 1 × 680² + 2 × 408² + 2 × 286² ≈ 3.8 MB, plus a prefetched centre-size copy for each of the ±1 cards (≈ 3.7 MB);
    - Up next: about 7.5 MB with 9 rows and ±1 large covers;
    - ambient: a 64 px source, composited at the reduced scale the frost already uses (`carousel_render.py:317-326`).
  - Decoded working set: **under about 20 MB**.
- **Disk (optional).** Apple allows about 164 days of caching (§1.6). A 64 to 100 MB LRU under `%LOCALAPPDATA%`, with file names hashed from the URL (the companion never logs URLs, `artwork.py:3-5`), would make re-opening the overlays instant.
- **Prefetch.** Mirror the knob's page prefetch (`artwork.py:697-725`):
  - explorer: 1200 for ±1, 600 for the rest of the page, plus the next page's 600s;
  - Up next: 1200 for focused ±1, and 240 for every visible row.

### 4.3 Fallbacks when only a small source exists

Compute u = need ÷ source edge, where the source edge is known from `artwork.width`/`height`, or from the decoded image for `/getaa`.

| Case | Typical u on this PC → at 4K | Treatment |
|---|---|---|
| u ≤ 1.1 | — | Plain LANCZOS. |
| 1.1 < u ≤ 1.5 | 600 px album at the explorer centre (1.13) or Up next (1.27) | LANCZOS upscale. Album art tolerates it. |
| u > 1.5 | **Sonos-only 400 px art on the Up next cover (1.9)**; 600 px album at 4K (1.7 / 1.9); radio logos | **Matted:** fill the square with the cover's own blur (the ambient pipeline at card size, a slight darken), and draw the sharp cover centred at 1.5 × its native size, for example 600 px inside the 760 px frame. It never looks pixelated and keeps the square silhouette. |
| No artwork (user playlist with no tracks, uploaded item off `mzstatic`, rejected template) | — | `#222` tile with the list-music or letter glyph. The ambient uses `bgColor` if present, otherwise none. |
| Playlist with 1 to 3 distinct albums | — | One full-bleed cover, using the large-cover rules. With ≥ 4 distinct albums, use the 2 × 2 mosaic. |
| Image still loading | — | Card filled with `artwork.bgColor` (free, already in the JSON). The ambient crossfades from `bgColor` to the blurred cover over its 600 ms transition (01 §5). This replaces the grey "slow artwork" state (`03-desktop.md:265`). |

### 4.4 "Scaling the designs to the assets": concrete proposal

1. **Keep the geometry uniform.** k = min(W/1280, H/720), as the carousel does. Card sizes never change per item, since a carousel whose cards resize per album would feel broken.
2. **Size requests per element, not per design.** Each art element has need = ceil(design px × k). The request is ladder_up(need ÷ 1.1) ∩ art_max, as in §4.1. The README §8 / 01 §5 line "fetch at 600 px" becomes: **1200 large / 600 secondary / 240 rows / ambient derived.**
3. **Cap the displayed upscale, not the layout.** A per-item quality treatment (§4.3) absorbs small sources: LANCZOS up to 1.5×, matted beyond.
4. **Only the two large elements scale with k beyond 1200.** Up to k = 3.5 (all common monitors, 4K included), every element fits under 1200 px. Above that, fetch 2000 for those two elements only. The smallest *reliable* catalog source is 1400 (95 % of the sample) and the floor is 600. So the 1200 rung is almost always a downscale, and 600 px albums are the only catalog case that needs §4.3.
5. **Never block on the network.** `bgColor` first, then the 600 px image, then 1200 px when needed, each crossfading. The ambient always comes from whatever is already cached.

### 4.5 What this implies in code (for the implementer)

1. **Keep the whole artwork dict on each item.** `apple_music.py:270-277` keeps only the expanded 480 and 96 URLs. Also keep `url` (the template), `width`, `height` and `bgColor`, for example as `art_template`, `art_max` and `art_bg`.
2. **Add a desktop cover store.** It should hold unscrimmed images, key by (template, size), and reuse `_fetch` with the same allowlist and bounds (`artwork.py:484-512`). **No new host is needed:** Apple images stay on `*.mzstatic.com`, and catalog lookups go to `api.music.apple.com`.
3. **Parse the song id in `SonosAdapter`.** Add a `catalog_song_id` to the current track (`sonos.py:180, 193-195`) and to Up next queue rows, using `_song_id`'s regex (`sonos.py:63-68`).
4. **Add a batch catalog lookup.** The Apple Music client gets a method for `GET /v1/catalog/{sf}/songs?ids=` (≤ 300 ids). The same response also brings `albumName` and `durationInMillis`, which Up next and Seek need.
5. **Keep `MAX_DOWNLOAD = 2 MiB` and the 3000 clamp.** The recommended sizes stay well inside them.

---

## Not verified / open questions

- **The user's library artwork sizes.** The `width`/`height` of Recently Added and Favourite-playlist items were not read, because that needs the user's tokens. Suggested check: log counts of (type, `width`, `height`, host is `mzstatic`) once, with **no URLs**.
- **Sonos `/getaa` resolution for Apple Music tracks.** About 400 px is taken from the task brief's earlier measurement; it was not re-measured.
- **Generated artwork on library playlists.** Whether library playlists with iOS 17.1+ generated artwork expose it in `attributes.artwork`, and at what size.
- **Uploaded (non-matched) library artwork.** Its host and size are undocumented publicly. If it is not on `*.mzstatic.com`, the allowlist drops it (§1.2).
- **Latency depends on cache state.** Figures are from this PC's connection on one day. Edge-cache state varies by region and popularity. The conclusion (common sizes are hot, odd sizes are cold) is consistent across all three passes.

## Sources

- Apple, Artwork object: https://developer.apple.com/documentation/applemusicapi/artwork (JSON: `…/tutorials/data/documentation/applemusicapi/artwork.json`)
- Apple, resource attributes (artwork required or optional): `…/applemusicapi/{albums,songs,playlists,libraryalbums,libraryplaylists,librarysongs}/attributes-data.dictionary`
- Apple, Get Multiple Catalog Songs by ID (≤ 300 ids): https://developer.apple.com/documentation/applemusicapi/get-multiple-catalog-songs-by-id
- Apple Music Provider Support, artwork 3000 recommended / 1400 minimum: https://itunespartner.apple.com/music/support/5215-digital-packaging-music
- iTunes Search API (artworkUrl100/60, about 20 calls per minute, promotional use): https://performance-partners.apple.com/search-api
- Forum: library playlists without artwork (June 2025): https://developer.apple.com/forums/thread/788448
- Forum: no playlist artwork upload via the API: https://developer.apple.com/forums/thread/707608
- Forum: library-songs artwork example (1200 × 1200 template): https://developer.apple.com/forums/thread/101328
- Apple Community, playlist mosaic art: https://discussions.apple.com/thread/251303151
- MacRumors, iOS 17.1 playlist art designs: https://www.macrumors.com/2023/09/28/custom-apple-music-playlist-art-options/
- Apple web client artwork parameters: https://bomberfish.ca/blog/apple-music-api
- Sonos, album art sizes and app-side substitution: https://docs.sonos.com/docs/add-album-art
- Sonos Community, `/getaa` with `x-sonos-http:song%3a…sid=204`: https://en.community.sonos.com/controllers-and-music-services-228995/sonos-link-to-album-art-is-local-ip-even-though-it-s-cloud-music-being-played-6864641
- SoCo #812 (Apple Music queue URI), via `research-apple-music-play-next.md:169`: https://github.com/SoCo/SoCo/issues/812
- Public page used for editorial playlist artwork: https://music.apple.com/us/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb
