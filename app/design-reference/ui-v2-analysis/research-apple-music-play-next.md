# Research: Apple Music's own "Play Next", and how the knob can use it

Date: 2026-09-25. This was a read-only desk study.
- No calls were made to the user's Sonos speakers or to Apple Music with the user's identity. There was no soco call, no `api.music.apple.com` request, and no token was used.
- No credentials, settings or keys were opened.
- Sources are public Apple, Sonos and Microsoft documentation, public forums and public GitHub source, plus the installed SoCo 0.31.2 in `.venv`.
- Local paths are relative to `app/`.

Scope note: the Sonos UPnP mechanics of inserting after the current track (`AddURIToQueue`, `DesiredFirstTrackNumberEnqueued`, `EnqueueAsNext`) are covered separately. This file calls that **the Sonos-queue route** and links to `design-reference/ui-v2-analysis/check-play-next.md`; it does not repeat that analysis.

---

## Plain-language summary

- **What "Play Next" means in Apple Music.** Play Next puts a song, album or playlist right after the song that is playing, and the rest of the list stays as it was. That list is called "Playing Next" or "Up Next". **It lives inside the one Apple Music app on the one device that is playing.** iCloud does not sync it to your other devices.
- **Apple gives a Windows program no way into that list.**
  - The Apple Music web service (the one the companion already uses) can read and edit your library, but it cannot play, skip or queue anything.
  - The Apple Music app for Windows has no automation interface.
  - Windows media controls can only play, pause and skip.
- **When Sonos plays Apple Music the way the knob does it, the list that counts is the Sonos queue.** The Sonos app has its own "Play Next" for Apple Music, which puts music right after the current song in that queue. **On Sonos, that is the native Play Next.** The knob can do exactly the same thing.
- **When your iPhone, Mac or PC AirPlays Apple Music to Sonos, the list lives on that phone or computer.** Sonos only plays the sound. The knob cannot see or change that list; use Play Next on the phone.
- **Apple Music has no "Spotify Connect"-style link to Sonos.** Sonos does not list Apple Music among the apps that can control Sonos directly. So there is no shared "cloud queue" that both apps could edit.
- **Recommendation for the knob.** Make **Play next** do exactly what the Sonos app's Play Next does, and offer it only while Sonos is playing its own queue.
  - During AirPlay, radio, TV or line-in, show a short message such as "Playing from AirPlay · use Play to start this here".
  - Never quietly change the hidden queue in the background.
- **Up next** shows the Sonos queue only while the queue is what is playing. During AirPlay it shows the current song (if Sonos reports one) and says the list is on the device that is AirPlaying.
- **Apple Music catches:**
  - Every track must match a catalog song that is available in your country.
  - Music videos, uploaded-only songs and Smart Playlists can't play on Sonos.
  - The Sonos explicit filter can block tracks.
  - Apple's Autoplay (similar songs after the end) does not work in the Sonos queue.

**One correction to the brief.** "AirPlay from Windows is not available" is only half true.
- A **web page** using MusicKit JS in Chrome or Edge cannot AirPlay.
- The **Apple Music app for Windows** *can* AirPlay to AirPlay 2 speakers, including Sonos (§2.6, §3b). In that case its queue is on the PC, and there is still no API to reach it.

---

## 1. What Play Next, Play Last / Add to Queue, Up Next and Autoplay mean

| Term | Meaning | Where documented |
|---|---|---|
| **Play Next** | Inserts the selection **right after the song that's playing** (Apple's wording: "top of the queue"). Each new Play Next goes in front of earlier ones, so the most recent one plays first. | iPhone/Android: "To play your selection right after the song that's playing, tap Play Next" ([support.apple.com/109336](https://support.apple.com/en-us/109336)). Mac: "Add music to the beginning of the queue: Choose Play Next" ([Mac guide](https://support.apple.com/guide/music/queue-your-songs-musb1e6d1c76/mac)). Windows: "Choose Play Next to add music to the top of the queue" ([Windows guide](https://support.apple.com/guide/music-windows/queue-up-your-songs-musb1e6d1c76/windows)). Web: "Add music to the top of the queue" ([web guide](https://support.apple.com/guide/music-web/queue-up-your-songs-apdm275ada6c/web)). |
| **Play Last**, now **Add to Queue** | Appends the selection to the bottom of the queue. The newest iPhone and Mac guides say "Add to Queue"; Windows and web still say "Play Last". | [109336](https://support.apple.com/en-us/109336), [Mac guide](https://support.apple.com/guide/music/queue-your-songs-musb1e6d1c76/mac) (macOS 27 edition), [Windows guide](https://support.apple.com/guide/music-windows/queue-up-your-songs-musb1e6d1c76/windows), [web guide](https://support.apple.com/guide/music-web/queue-up-your-songs-apdm275ada6c/web) |
| **Playing Next / Up Next** | The visible list of upcoming items. You can reorder it or remove items. History (already played) sits above it. On Windows, **"Clear" appears next to an album or playlist**, so the queue is shown grouped by the container it came from. | [Windows guide](https://support.apple.com/guide/music-windows/queue-up-your-songs-musb1e6d1c76/windows), [Mac guide](https://support.apple.com/guide/music/queue-your-songs-musb1e6d1c76/mac), [109336](https://support.apple.com/en-us/109336) |
| **Autoplay** (∞) | Once the queue runs out, adds similar songs at the end. Needs a subscription. **The on/off setting** syncs across devices on the same Apple Account; the queue does not. | Windows and Mac guides (see above): "When you turn off AutoPlay on a device … AutoPlay is turned off on all other devices that use the same Apple Account." |

**Where the queue lives, and whether it syncs**
- **It belongs to the app on the playing device.**
  - Mac: "If you quit Music, the queue is automatically saved for the next time you open Music." ([Mac guide](https://support.apple.com/guide/music/queue-your-songs-musb1e6d1c76/mac))
  - Windows says the same ([Windows guide](https://support.apple.com/guide/music-windows/queue-up-your-songs-musb1e6d1c76/windows)).
  - That is a **local** save.
  - Windows adds: "A song needs to be playing before you can use the Playing Next queue."
- **It is not synced by iCloud.** An Apple Community answer to "How to sync Up Next between devices" (Nov 2022) says: "No. Up next only works on the device being used." ([discussions.apple.com/thread/254377119](https://discussions.apple.com/thread/254377119)). Sync Library syncs the library and playlists, not the queue.
- **The only cross-device moves are Apple-to-Apple hand-offs.**
  - iPhone to HomePod or Apple TV: "Transfer what you're listening to between the two devices" ([109336](https://support.apple.com/en-us/109336)).
  - SharePlay "shared queue" between iPhones in the same session ([support.apple.com/108767](https://support.apple.com/en-us/108767)).
  - Neither is reachable from Windows or from a third-party program.
- **Nothing in iOS 27 changes this.** Coverage of the iOS 27 and 27.2 Apple Music changes mentions no queue sync, casting or speaker-integration change ([9to5Mac, Jun 2026](https://9to5mac.com/2026/06/10/ios-27-heres-all-the-new-apple-music-features/), [9to5Mac, Sep 2026](https://9to5mac.com/2026/09/21/ios-27-2-reveals-new-features-coming-to-apple-music-carplay-more/)).

---

## 2. Every programmatic way to use Apple Music's own queue

### 2.1 MusicKit for Swift (Apple platforms only)
- **`MusicPlayer.Queue.insert(_:position:)`**
  - It takes a single item, a sequence of items, or queue entries ([MusicPlayer.Queue](https://developer.apple.com/documentation/musickit/musicplayer/queue)).
  - Positions:
    - `.afterCurrentEntry` is "similar to the Play Next feature in the Music app".
    - `.tail` is "similar to the Play Later feature".
  - Availability: iOS/iPadOS/tvOS 15+, macOS 14+, visionOS 1+ ([EntryInsertionPosition](https://developer.apple.com/documentation/musickit/musicplayer/queue/entryinsertionposition)).
- **`ApplicationMusicPlayer`**
  - It plays "in a way that doesn't affect the Music app's state".
  - Its queue exposes `entries` ([ApplicationMusicPlayer](https://developer.apple.com/documentation/musickit/applicationmusicplayer)).
  - This is a *separate* queue owned by your app, not the user's Music app queue.
- **`SystemMusicPlayer`** "controls the Music app's state".
  - It shares only repeat, shuffle and playback status ([SystemMusicPlayer](https://developer.apple.com/documentation/musickit/systemmusicplayer)).
  - It is available on iOS, iPadOS, tvOS, visionOS and Mac Catalyst. There is **no native macOS** entry.
  - An Apple Frameworks Engineer: "SystemMusicPlayer's queue only gives apps access to the currentEntry" ([forums/706231](https://developer.apple.com/forums/thread/706231)).
  - So an iPhone app can insert into the Music app's queue, but it **cannot read the upcoming list**.
- **Older MediaPlayer API:** `MPMusicPlayerController.prepend(_:)` "inserts … immediately after the currently playing media item" (iOS 10.3+, [docs](https://developer.apple.com/documentation/mediaplayer/mpmusicplayercontroller/prepend(_:))).
- **Verdict for this project: not usable.**
  - It needs a native Apple-platform app.
  - It controls playback on *that* iPhone or Mac.
  - It would reach Sonos only if that device is AirPlaying (§3b).
  - A Windows companion cannot call it.

### 2.2 MusicKit on the Web (MusicKit JS v1 and v3)
- **v1 documentation:**
  - `playNext` "Inserts the media items for the descriptor immediately after the currently playing media item in the queue."
  - `playLater` "…after the last media item in the queue."
  - Source: [MusicKit JS v1](https://js-cdn.music.apple.com/musickit/v1/index.html).
- **v3 documentation:** `playNext(options, clear?)` "Inserts the MediaItem(s) defined by QueueOptions immediately after the nowPlayingItem". `playLater` inserts "after the last MediaItem". There is also an example `await music.playNext({ song: '…' })` ([MusicKit on the Web v3 docs](https://js-cdn.music.apple.com/musickit/v3/docs/index.html), MusicKit instance reference, read from the public docs bundle).
- **Where it plays.** The queue belongs to *that* web page's MusicKit instance, and audio plays in that browser.
  - Without user authorization, playback is limited to previews (`previewOnly` in the same v3 reference).
  - It is not the user's Music app queue.
  - It is the same technology the Apple Music web player uses, and that player's queue does not sync either (§1).
- **Can it reach Sonos?** Not in a supported way from Windows.
  - AirPlay from web pages uses WebKit-only APIs: `webkitShowPlaybackTargetPicker` and `WebKitPlaybackTargetAvailabilityEvent` ([Apple WebKit JS docs](https://developer.apple.com/documentation/webkitjs/adding_an_airplay_button_to_your_safari_media_controls)).
  - These are Safari APIs; Chrome, Edge and WebView2 on Windows have no AirPlay sender.
  - Sound would come out of the PC's audio device. Getting it to Sonos would need third-party AirPlay-sender software or a Sonos line-in. That is lossy, adds latency, and takes over the room.
  - **Verdict: not usable for Play Next on Sonos.**

### 2.3 MusicKit for Android
There is a MusicKit SDK for Android apps, for authentication and playback on *that* Android device ([developer.apple.com/musickit/android](https://developer.apple.com/musickit/android/index.html)). Same verdict as 2.1: it controls local playback, not Sonos.

### 2.4 Apple Music API (REST): no playback or queue endpoints
- **What the API covers.** The topic index ([developer.apple.com/documentation/applemusicapi](https://developer.apple.com/documentation/applemusicapi)) has only these groups:
  - Albums, Artists, Songs and Music Videos
  - Playlists and Stations
  - Search
  - Ratings, Genres and Charts
  - Activities, Curators and Record Labels
  - Add to favorites
  - Replay data
  - Recommendations and History
  - Multiple-resource fetch
  - Storefront and test endpoints
- **Nothing controls a device.** There is no playback, player, queue, device or now-playing endpoint.
- **History** holds only *past* listening: heavy rotation, recently played resources, tracks and stations, and recently added ([History](https://developer.apple.com/documentation/applemusicapi/history)). It does not include upcoming items.
- **Writes** are limited to library items: create playlist, add tracks *to the end of a library playlist*, add to library ([Playlists API](https://developer.apple.com/documentation/applemusicapi/playlists-api)), plus ratings and favorites.
- **Verdict.** The companion is already using everything this API can do for Play Next:
  - reading the library (`control_center/apple_music.py:27-28`, `:125`);
  - resolving tracks (`:356-383`).

### 2.5 Apple Music app for Windows
- **Not scriptable.** Apple Code-Level Support, quoted in the developer forums (Feb 2024): "there is no supported way to achieve the desired functionality given the currently shipping system configurations". The thread's summary: "Apple Music for Windows is not scriptable. There is no public API." ([forums/740837](https://developer.apple.com/forums/thread/740837), [forums/729225](https://developer.apple.com/forums/thread/729225))
- **iTunes COM (`IiTunes`).**
  - iTunes for Windows is still distributed (Apple page updated 3 Aug 2026).
  - But "On your Windows PC, you manage your podcasts and audiobooks in iTunes" ([support.apple.com/118290](https://support.apple.com/en-us/118290)).
  - After installing Apple Music or Apple TV, "you can only use those apps for your music, TV shows, and movies; you can continue to use iTunes to listen to your audiobooks and podcasts" ([How iTunes is changing on PC](https://support.apple.com/guide/itunes/how-itunes-is-changing-itns5ecc4f3c/windows)).
  - So iTunes COM cannot drive the Apple Music app's queue. It is also undocumented and legacy.
  - **Verdict: dead end.**
- **Windows System Media Transport Controls (`GlobalSystemMediaTransportControlsSession`).**
  - Methods ([Microsoft Learn](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession)):
    - reading: `GetPlaybackInfo`, `GetTimelineProperties`, `TryGetMediaPropertiesAsync`;
    - transport: `TryPlay`, `TryPause`, `TryTogglePlayPause`, `TryStop`, `TrySkipNext`, `TrySkipPrevious`, `TryFastForward`, `TryRewind`, `TryRecord`;
    - settings: `TryChangePlaybackPosition`, `TryChangePlaybackRate`, `TryChangeShuffleActive`, `TryChangeAutoRepeatMode`, `TryChangeChannelUp/Down`.
  - **Nothing adds, inserts or reads a queue.**
  - Third-party flyouts show that Apple Music on Windows registers with SMTC ([pocket-lint](https://www.pocket-lint.com/windows-11-media-flyout-application-microsoft-store/)).
- **URL schemes and UI automation.**
  - No documented URL scheme was found for queue actions.
  - Driving the app's UI with Windows UI Automation is conceivable but unsupported and brittle. That is my assessment, not a documented option. **Not recommended.**
- **AirPlay from the Windows app is supported.**
  - "select the AirPlay button, then select the checkbox next to the speaker"; it works with "AirPlay- or AirPlay 2-enabled device[s]" ([Apple Music on Windows: speakers](https://support.apple.com/en-kw/guide/music-windows/musa3fedf052/windows)).
  - The Apple Community confirms AirPlay to receivers from the new app (Feb 2024, [thread 255480860](https://discussions.apple.com/thread/255480860)).
  - The Windows app can therefore be the AirPlay source for Sonos (§3b), with its queue on the PC.

### 2.6 Summary table

| Route | Runs on | Whose queue it edits | Reaches Sonos? | Usable by the Windows companion? |
|---|---|---|---|---|
| MusicKit Swift, `.afterCurrentEntry` | iOS, iPadOS, macOS 14+, tvOS, visionOS | Your app's queue (Application) or the Music app's queue (System; insert only) | Only if that device AirPlays | No |
| MPMusicPlayerController `prepend` | iOS, iPadOS, Catalyst, tvOS | Music app / app queue player | Only via AirPlay | No |
| MusicKit JS `playNext` | Browser or webview | That page's own queue | No (no AirPlay outside Safari) | Technically yes, but it plays on the PC, not Sonos |
| MusicKit Android | Android | That app's queue | No | No |
| Apple Music API (REST) | Anywhere | None; no queue endpoints | No | Already used, for library reads only |
| Apple Music app for Windows | Windows | Its own queue | Yes, via its AirPlay | No; no API, no COM |
| iTunes COM | Windows | iTunes only (podcasts and audiobooks once Apple Music is installed) | n/a | No |
| SMTC | Windows | None; transport only | n/a | Only play, pause, next and previous of whatever app is playing |
| **Sonos queue with the Apple Music service** | Sonos | **The Sonos queue** | **Yes** | **Yes: the Sonos-queue route** |

---

## 3. How Apple Music reaches Sonos, and which queue is in charge

### 3a. Sonos queue with the Apple Music service (what the companion does today)
- **The Sonos queue is authoritative.**
  - Items are Sonos queue rows pointing at the Apple Music service: sid 204, service type 52231, URIs like `x-sonos-http:song%3a<catalogId>.mp4?sid=204&flags=8224&sn=…` ([SoCo issue #812](https://github.com/SoCo/SoCo/issues/812)).
  - The companion identifies its rows by that `song:<id>` pattern (`control_center/sonos.py:63-68`).
  - It adds them through SoCo's `ShareLinkPlugin` Apple Music support. That code turns `…/album/<slug>/<albumId>?i=<songId>` into `song:<songId>`, service 52231 (`.venv/Lib/site-packages/soco/plugins/sharelink.py:152-187`, add call `:216-285`).
- **The Sonos app's Play Next is a Sonos-queue insert.** Sonos documents it as "Play Next: Adds track(s) to queue after the current track". Its siblings are "Play Now", "Add to End of Queue" and "Replace Queue" ([Sonos: Add tracks to the queue](https://support.sonos.com/en-us/article/add-tracks-to-the-queue)).
  - It is available for Apple Music items in the Sonos app.
  - It was briefly missing after the May 2024 app rewrite and restored on 4 Jun 2024 ([Sonos Community](https://en.community.sonos.com/controllers-and-music-services-229131/today-s-update-play-next-add-to-end-of-queue-6896732)).
  - Community note in that thread: the options are hidden when "the room/group that's in focus is not currently using the queue".
- **Its semantics match Apple's.** Both put the newest Play Next right after the current song, and both keep the rest of the queue. **This is the "native Play Next" available on Sonos.**
- **A public implementation does the same for Apple Music.** node-sonos-http-api's `applemusic/next/…`:
  - computes `nextTrackNo = trackNo + 1` and calls `addURIToQueue(uri, metadata, true, nextTrackNo)`;
  - does **not** switch source;
  - its `now` mode first switches to `x-rincon-queue:` ([appleMusic.js](https://raw.githubusercontent.com/jishi/node-sonos-http-api/master/lib/actions/appleMusic.js), [README](https://github.com/jishi/node-sonos-http-api)).
  - The details of this call, including why `EnqueueAsNext` is not the right lever outside shuffle, are the Sonos-queue route: see `check-play-next.md`.
- **Autoplay does not exist here.** Apple's Autoplay (similar songs after the end) is not available when Sonos plays Apple Music from its queue.
  - Sonos staff (Jan 2021) passed it on as a feature request.
  - Community experts say Apple would have to implement it through the Sonos partner program ([Sonos Community 6854645](https://en.community.sonos.com/controllers-and-music-services-228995/using-apple-music-how-to-enable-autoplay-similar-songs-within-sonos-app-6854645)).

### 3b. AirPlay 2 from the Music app (iPhone, Mac or Windows) to Sonos
- **The sender's Music app queue is authoritative.** Sonos only renders the audio.
  - Sonos: "Some apps like Spotify and Apple Music allow direct AirPlay streaming from within the app itself" ([Sonos: Stream AirPlay audio](https://support.sonos.com/en-us/article/stream-airplay-audio-to-sonos)).
  - Sonos Community best answer (Jan 2024): "When Airplaying you are not really using the Sonos system at all". The Sonos queue shows "queue not in use".
  - Another reply: "When Airplaying you're using the Apple Music App - the playing queue is therefore the one you see in that App" ([Sonos Community 6889068](https://en.community.sonos.com/controllers-and-music-services-229131/i-cannot-add-tracks-songs-to-queue-from-airplay-from-iphone-music-6889068)).
- **What the Sonos UPnP state looks like.**
  - The track or transport URI is `x-sonos-vli:…,airplay:…`.
  - SoCo classifies it as `AIRPLAY` with the regex `^x-sonos-vli:.*,airplay:` (`.venv/Lib/site-packages/soco/core.py:3095`, source table `:3082-3097`, `music_source` `:1904-1913`).
  - Spotify Connect uses the same `x-sonos-vli` family with `,spotify:` (`core.py:3096`).
- **The companion cannot see or change the AirPlay sender's queue.** There is no route from the Sonos side back to the sender's list.
- **The Sonos queue still exists during AirPlay, but it is dormant.** `get_queue` would return whatever was queued before AirPlay started.
  - This is a trap for Up next: **showing that list as "Up next" during AirPlay would be wrong.**
  - Inserting into it would do nothing audible until the queue becomes the source again.
  - The Sonos app itself hides Play Next when the room "is not currently using the queue" (community explanation in [Sonos Community 6896732](https://en.community.sonos.com/controllers-and-music-services-229131/today-s-update-play-next-add-to-end-of-queue-6896732)). That is the same gate this file recommends in §4.2.
- **Current-song metadata during AirPlay.**
  - The Sonos app usually shows the AirPlay track's title and artwork. Community threads report it being wrong or stale at times, for example "AIRPLAY wrong artwork and track info" ([Sonos Community 6839334](https://en.community.sonos.com/troubleshooting-228999/airplay-wrong-artwork-and-track-info-after-update-6839334)).
  - Treat it as best effort, and verify on this system before relying on it.
- **Special case: the Windows Apple Music app on the same PC is the AirPlay sender.**
  - SMTC can give the companion that app's current title, artist and playback state, and play, pause, next and previous (§2.5).
  - It still cannot give the queue or insert into it.
  - This is an optional, read-only enhancement at most.

### 3c. Any other Apple Music and Sonos integration
- **Direct Control / "Connect"-style.** Sonos lists "Amazon Music, Audible, IDAGIO, iHeartRadio, Pandora, Spotify, TIDAL" as services that stream and control Sonos from their own app. **Apple Music is not listed.** Instead, "you can stream audio from that device to Sonos using AirPlay" ([Sonos: Stream audio from another app](https://support.sonos.com/en-us/article/stream-audio-to-sonos-from-another-app)).
- **Sonos Cloud Queue.**
  - It exists in the Sonos developer platform: `playbackSession/loadCloudQueue`. It is "available for content integrations only", and the **music service** runs the cloud-queue server ([About Cloud Queue API](https://docs.sonos.com/reference/about-cloud-queue-api), [loadCloudQueue](https://docs.sonos.com/reference/playbacksession-loadcloudqueue-sessionid)).
  - Apple Music content on Sonos appears as ordinary local-queue rows (`x-sonos-http:song…sid=204`, §3a), and Apple offers no Direct Control.
  - So **there is no Apple Music cloud queue on Sonos that a third party could edit.**
- **Siri.**
  - Siri on an iPhone, HomePod or Apple TV plays Apple Music *on* Sonos via AirPlay 2 once the speakers are in the Home app.
  - Sonos: "this will not add Siri to a voice-enabled Sonos product or let you control them directly within the Apple Home app" ([Sonos: Use Siri](https://support.sonos.com/en-us/article/use-siri-to-control-sonos-speakers)).
  - Queue voice commands therefore act on the sender's Music queue (§3b).
- **Sonos Voice Control.**
  - It supports Apple Music ([Sonos: services for voice control](https://support.sonos.com/en-us/article/music-services-that-work-with-sonos-voice-control)).
  - The official list of voice requests has **no** queue or play-next request ([list of voice requests](https://support.sonos.com/en-us/article/list-of-voice-requests-for-sonos-voice-control)).
  - Alexa or Google "play next" with Apple Music on Sonos was not verified in any source I found. Treat it as unavailable.
- **SharePlay shared queue.** This is iPhone-to-iPhone: other people add to the host's queue ([108767](https://support.apple.com/en-us/108767)). If the host is AirPlaying to Sonos, that is still the §3b case. It is not reachable from Windows.

**Bottom line for 3:**
- With the Sonos service, the Sonos queue is authoritative, and the Sonos app's Play Next inserts into it.
- With AirPlay, the sender's Music app queue is authoritative and cannot be reached.
- There is no third, "cloud" Apple Music queue.

---

## 4. Recommendation for this project

### 4.1 How to "use native Play Next"
**Make the knob's Play next copy the Sonos app's Play Next exactly:**
- insert the highlighted album or playlist right after the current track in the Sonos queue;
- keep everything else;
- don't change the source.

That is the only native Play Next that applies to the way the companion plays today (`control_center/sonos.py:351-451` builds the Sonos queue). It also matches Apple's own meaning (§1).
- Mechanics, verification and rollback: **the Sonos-queue route**, `check-play-next.md`.
- That file also corrects the design text at `specs/01-FEATURES-explorers-snap-seek.md:221`, which names `EnqueueAsNext`.

Don't pursue MusicKit, MusicKit JS, the Windows app, iTunes COM or SMTC for this (§2.6). None of them can put music into what Sonos is playing.

### 4.2 Gate Play next on the current Sonos source
The companion already reads the media URI (`sonos.py:186`) and already refuses Previous when the source isn't the queue (`sonos.py:161-162`). Use the same gate. Classify the source with the SoCo table (`core.py:3082-3097`), applied to the transport URI and the track URI.

| Current source (as Sonos reports it) | Play next (button 3) | Knob / toast text (suggested) | Up next view |
|---|---|---|---|
| **Queue** (`x-rincon-queue:`), playing or paused | **Enabled**: insert after the current row | `Queued next` (1.5 s) · toast `Queued next · {album}` (as designed) | Sonos queue: History (dimmed), Now playing, upcoming. The inserted block shows its own cover (as designed). |
| Queue, stopped with no current row, or the queue is empty | Behave like **Play** (start the album), or disable with "Nothing playing · press Play". Apple itself requires a song to be playing before Play Next (Windows guide). | `Nothing playing · press Play` | Empty state |
| **AirPlay** (`x-sonos-vli:…,airplay:`) | **Disabled.** Never insert into the dormant queue. | `Playing from AirPlay · use Play to start it here` | Now-playing card only (title and art if Sonos reports them), plus: "Up next is on the device that's AirPlaying." **Do not show the dormant Sonos queue as Up next.** |
| Spotify Connect (`x-sonos-vli:…,spotify:`) | Disabled | `Playing from Spotify · use Play to start it here` | Now-playing card only |
| Radio / stream (`x-sonosapi-stream`, `x-sonosapi-radio`, `x-sonosapi-hls`, `x-rincon-mp3radio`, `aac:`, `hls-radio:`), including Apple Music radio | Disabled | `Radio has no queue · use Play to start it here` | Now-playing card only |
| TV (`x-sonos-htastream:`) or line-in (`x-rincon-stream:`) | Disabled | `TV is playing · use Play to start it here` / `Line-in is playing · …` | Now-playing card only |
| Unknown | Disabled | `Can't queue on this source` | Now-playing card only |

**Why not "switch to the queue, then insert"?**
- Switching source is what **Play** does. The existing replace flow already switches with `SetAVTransportURI(x-rincon-queue:…)` (`sonos.py:413-415`).
- Doing it under the label Play next would interrupt an iPhone's AirPlay session, or the TV, without warning.
- Keep the two buttons honest: button 3 only ever *adds*, and button 4 takes over the room.
- If the user presses Play during AirPlay or TV, a one-time confirm such as "Stop AirPlay and play here?" is worth considering. That is a design decision, not a technical need.

### 4.3 How Play next should treat albums and playlists
- **Insert the whole item as one contiguous block, in its own order.** This is what Apple's Play Next does with an album or playlist, and Windows shows a per-album or per-playlist "Clear".
  - Keep playlist order and intentional duplicates, as `resolve` already does (`control_center/apple_music.py:377`).
  - Albums and playlists resolve the same way: a list of catalog songs (`apple_music.py:356-383`).
- **Several Play nexts stack newest-first.** This matches both Apple and Sonos. The toast "Queued next" is accurate. Up next should show the newest block directly after Now playing.
- **Keep the per-track expansion rather than inserting a Sonos album or playlist container.** Containers would mean `x-rincon-cpcontainer:1004206c…` or `1006206c…` via share links (`sharelink.py:38-69`, `:163-176`), and they don't fit here:
  - A library album can be a *subset* of the catalog album.
  - A private library playlist (`p.…` id) has no Sonos share link at all. Only catalog `pl.…` and public user `pl.u-…` playlists do (`sharelink.py:168-176`; library playlist `isPublic`/`hasCatalog` in [LibraryPlaylists.Attributes](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/attributes-data.dictionary)).
  - The module deliberately avoids "whole-catalog-album substitution" (`apple_music.py:1-5`).
  - An optional optimisation, not needed for v1: use one container insert when the library album's catalog track list is identical to the catalog album's.
- **Large playlists.**
  - The present staging re-reads the full queue before and after every added song (`sonos.py:382-397`).
  - For a long playlist inserted into a long queue that becomes many requests. Consider:
    - progress on the knob, such as `Queuing 12 / 80`;
    - a confirm step above a size limit;
    - lighter verification for the insert path (see `check-play-next.md`).
  - Apple's in-app Play Next is instant, so the user will notice slowness.

### 4.4 Apple Music-specific caveats to carry into Play next
- **Library versus catalog IDs.** Sonos needs **catalog song IDs**. Library IDs (`i.…`, `l.…`, `p.…`) mean nothing to Sonos. Each library track is already mapped to exactly one catalog song, or the whole item is refused (`apple_music.py:305-328`).
- **Uploaded or matched-only tracks.**
  - `hasCatalog = false` tracks are marked unplayable (`apple_music.py:268-269`).
  - A non-song resource is refused (`:317-318`).
  - Sonos itself says "Smart Playlists, music videos … are not supported on Sonos" ([Apple Music on Sonos](https://support.sonos.com/en-us/services/apple-music?r=1)).
  - Library playlists can contain `library-music-videos` (`trackTypes`, [LibraryPlaylists.Attributes](https://developer.apple.com/documentation/applemusicapi/libraryplaylists/attributes-data.dictionary)).
  - Keep all-or-nothing ("Nothing was queued") for Play next as for Play. A partial "next" block would be confusing.
- **Region and storefront.**
  - Apple: when `playParams` is present, "the song is available to play with an Apple Music subscription" ([Songs.Attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)). The companion already refuses songs without it (`apple_music.py:326-327`).
  - Sonos plays with **the Apple Music account linked in Sonos**, and the share-link metadata pins no account (`sharelink.py:246-264`; `check-play-next.md` §1).
  - If that account differs from the MusicKit account the companion reads (another Apple ID or country), availability can differ. Surface Sonos's own refusal rather than retrying.
- **Explicit content.**
  - The Sonos explicit filter supports Apple Music ([Sonos: Filter explicit content](https://support.sonos.com/en-us/article/filter-explicit-content-on-sonos)).
  - With it on, expect explicit tracks to be refused or skipped. Sonos doesn't document which, so verify.
  - Catalog songs carry `contentRating: "explicit" | "clean"` ([Songs.Attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)), so the explorer or Up next can show an "E" badge. Sonos's own app shows explicit badging for Apple Music ([Apple Music on Sonos](https://support.sonos.com/en-us/services/apple-music?r=1)).
- **No Autoplay after the queue ends** when Sonos plays from its queue (§3a). If the user expects "keep playing similar music", that only happens with AirPlay from the Music app.
- **Shuffle.** Apple's docs don't say how Play Next behaves with shuffle on. For the Sonos side, see the Sonos-queue route (`check-play-next.md`, caveat 2).

### 4.5 Things not to do
- Don't insert into the Sonos queue when the queue isn't the active source. The music would silently wait there and surprise the user later.
- Don't present the dormant Sonos queue as "Up next" during AirPlay, radio or TV.
- Don't promise that "Play next" on the knob shows up in the iPhone's or PC's Music app queue. It won't; the two queues are unrelated.
- Don't automate the Apple Music Windows UI, iTunes COM, or a MusicKit JS webview for this feature.

### 4.6 Checks worth doing on the real system (only with the user's go-ahead; these touch the speakers)
1. **While AirPlaying from the iPhone Music app,** read `get_current_media_info()["uri"]`, `get_current_track_info()` and `available_actions`. This confirms:
   - the `x-sonos-vli:…,airplay:` prefix on this system;
   - whether title, artist and art are reported;
   - whether Next is offered, which would forward to the sender.
2. **During AirPlay, read `get_queue`** to confirm it returns the old, dormant queue. This proves the Up next rule in 4.2 is needed.
3. **Run the reversible Play-next live test** described in `check-play-next.md` §5.

---

## Sources

**Apple: user documentation**
- https://support.apple.com/en-us/109336: Play Next, Add to Queue, Playing Next, AutoPlay, HomePod transfer
- https://support.apple.com/guide/music/queue-your-songs-musb1e6d1c76/mac: Mac; queue saved locally on quit; AutoPlay setting syncs
- https://support.apple.com/guide/music-windows/queue-up-your-songs-musb1e6d1c76/windows: Windows; Play Next / Play Last; saved on quit; "a song needs to be playing"
- https://support.apple.com/guide/music-web/queue-up-your-songs-apdm275ada6c/web: web player
- https://discussions.apple.com/thread/254377119: "Up next only works on the device being used"
- https://support.apple.com/en-us/108767: SharePlay music sessions
- https://support.apple.com/en-us/118290 and https://support.apple.com/guide/itunes/how-itunes-is-changing-itns5ecc4f3c/windows: iTunes limited to podcasts and audiobooks
- https://support.apple.com/en-kw/guide/music-windows/musa3fedf052/windows and https://discussions.apple.com/thread/255480860: Apple Music for Windows AirPlay

**Apple: developer documentation**
- https://developer.apple.com/documentation/musickit/musicplayer/queue
- https://developer.apple.com/documentation/musickit/musicplayer/queue/entryinsertionposition
- https://developer.apple.com/documentation/musickit/applicationmusicplayer
- https://developer.apple.com/documentation/musickit/systemmusicplayer
- https://developer.apple.com/forums/thread/706231: SystemMusicPlayer queue exposes currentEntry only
- https://developer.apple.com/documentation/mediaplayer/mpmusicplayercontroller/prepend(_:)
- https://js-cdn.music.apple.com/musickit/v1/index.html and https://js-cdn.music.apple.com/musickit/v3/docs/index.html: MusicKit JS playNext and playLater
- https://developer.apple.com/documentation/webkitjs/adding_an_airplay_button_to_your_safari_media_controls: WebKit-only AirPlay
- https://developer.apple.com/musickit/android/index.html
- https://developer.apple.com/documentation/applemusicapi: topic index, no playback endpoints
- https://developer.apple.com/documentation/applemusicapi/history
- https://developer.apple.com/documentation/applemusicapi/playlists-api
- https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary
- https://developer.apple.com/documentation/applemusicapi/libraryplaylists/attributes-data.dictionary
- https://developer.apple.com/forums/thread/740837 and https://developer.apple.com/forums/thread/729225: Apple Music for Windows not scriptable

**Microsoft**
- https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession

**Sonos**
- https://support.sonos.com/en-us/article/add-tracks-to-the-queue: Play Next = "after the current track"
- https://support.sonos.com/en-us/article/stream-airplay-audio-to-sonos
- https://support.sonos.com/en-us/article/stream-audio-to-sonos-from-another-app: Direct Control list, no Apple Music
- https://support.sonos.com/en-us/article/use-siri-to-control-sonos-speakers
- https://support.sonos.com/en-us/article/music-services-that-work-with-sonos-voice-control
- https://support.sonos.com/en-us/article/list-of-voice-requests-for-sonos-voice-control
- https://support.sonos.com/en-us/article/filter-explicit-content-on-sonos
- https://support.sonos.com/en-us/services/apple-music?r=1
- https://docs.sonos.com/reference/about-cloud-queue-api and https://docs.sonos.com/reference/playbacksession-loadcloudqueue-sessionid
- https://en.community.sonos.com/controllers-and-music-services-229131/i-cannot-add-tracks-songs-to-queue-from-airplay-from-iphone-music-6889068
- https://en.community.sonos.com/controllers-and-music-services-229131/today-s-update-play-next-add-to-end-of-queue-6896732
- https://en.community.sonos.com/controllers-and-music-services-228995/using-apple-music-how-to-enable-autoplay-similar-songs-within-sonos-app-6854645
- https://en.community.sonos.com/troubleshooting-228999/airplay-wrong-artwork-and-track-info-after-update-6839334: title only; the page returned 403 to the fetcher

**GitHub and press**
- https://github.com/SoCo/SoCo/issues/812: Apple Music URI `x-sonos-http:song%3a…sid=204`
- https://github.com/jishi/node-sonos-http-api and https://raw.githubusercontent.com/jishi/node-sonos-http-api/master/lib/actions/appleMusic.js
- https://9to5mac.com/2026/06/10/ios-27-heres-all-the-new-apple-music-features/ and https://9to5mac.com/2026/09/21/ios-27-2-reveals-new-features-coming-to-apple-music-carplay-more/
- https://www.pocket-lint.com/windows-11-media-flyout-application-microsoft-store/

**Local files (read-only)**
- `control_center/apple_music.py`: lines 1-5, 27-28, 251, 265-269, 305-328, 330-354, 356-383
- `control_center/sonos.py`: lines 63-68, 159-175, 177-204 (186), 351-451 (382-397, 413-419)
- `.venv/Lib/site-packages/soco/plugins/sharelink.py`: lines 38-69, 152-187, 216-285
- `.venv/Lib/site-packages/soco/core.py`: lines 1874-1913, 2354-2393, 3071-3097
- `design-reference/design_handoff_nano_d_master/specs/01-FEATURES-explorers-snap-seek.md`: lines 76, 195-222
- `design-reference/ui-v2-analysis/check-play-next.md`: the Sonos-queue route
