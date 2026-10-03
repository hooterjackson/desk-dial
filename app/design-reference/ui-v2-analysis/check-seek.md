# Feasibility check: Seek (jumping through the song on Sonos)

Question: "Seek: how jumping through the song works on Sonos."
Scope: read-only. No Sonos or Apple Music call was made, no serial port was opened, and the companion was not run. Evidence comes from the project source, the installed SoCo 0.31.2 source, one existing diagnostics capture from 2026-09-22, and public documentation.

Paths are relative to `app/` unless they start with `soco/`, which means `.venv/Lib/site-packages/soco/`.

---

## Verdict: works, with caveats

Sonos supports the design's recipe natively for the content this companion plays: Apple Music songs in the local queue (`x-rincon-queue:…#0`). The recipe is AVTransport `Seek(Unit=REL_TIME, Target=H:MM:SS)` on the group coordinator.

- **Evidence from the user's own system.** The room's capture from 2026-09-22 already advertises `SeekTime` for an Apple Music queue (`diagnostics/sonos-readiness.json:83-90`). It also lists the `Seek(InstanceID, Unit, Target)` action (`:51-58`).
- **Position is readable.** A second probe saw the playing Apple Music song's position advance (`diagnostics/quiet-sonos-probe.json:30-33`).

Four caveats shape the build:

1. **The capability flag is `SeekTime`, not `Seek`.** Sonos advertises `X_DLNA_SeekTime`, and SoCo strips it to `SeekTime` (`soco/core.py:2258-2273`). The companion's parser keeps the part after the last underscore (`control_center/sonos.py:182`), so it also produces `SeekTime`. A test for `"Seek" in actions` would always be false.
2. **The companion does not read duration yet.** `_state()` calls `get_current_track_info()` but copies only `position`, as a raw string (`control_center/sonos.py:180, 202`). Both `duration` and a parsed position must be added. Nothing in the controller uses position today.
3. **A successful SOAP reply is not proof that the seek happened.** Per the UPnP spec, Seek moves the transport to `TRANSITIONING` and returns immediately. Home Assistant maintainers saw a Sonos speaker accept a seek for Pandora and then do nothing. So the seek must be confirmed by re-reading the position, and never replayed, as `set_volume` already does.
4. **Never seek at or past the duration.** Sonos documents that a target beyond the track's length jumps to the end and skips to the next track. Clamp the target below the duration.

**Not needed:**
- No new haptic profile. Seek reuses the installed `BINARIS BEER` profile that Home volume already uses.
- No change to Play next or the queue.

**Needed outside Sonos** (this is what actually blocks the UI):
- The knob contract has no `seek` layout and no song-lap ring style. Both need a firmware and contract addition.

---

## 1. How the companion reads and writes Sonos today

### Reads (`SonosAdapter._state`, `control_center/sonos.py:177-204`)

Every read goes to `group.coordinator`, which `_context()` resolves (`sonos.py:122-145`). `_context()` also computes a group revision from the room, group, coordinator and member UIDs (`:143-144`).

| Field | Source call | Line | Notes |
|---|---|---|---|
| title, artist, art, `track_id` | `coordinator.get_current_track_info()` (UPnP `GetPositionInfo`) | 180, 192-194, 200 | `track_id` is a digest of uri, playlist_position, title and artist (`:153-156`). **It does not include position, so a seek does not change it.** It is therefore a safe "same song" guard. |
| actions | `coordinator.available_actions` (UPnP `GetCurrentTransportActions`) | 181-182 | Parsed to a set of last-underscore segments, e.g. `{"Set","Stop","Pause","Play","SeekTime","SeekTrackNr","Next"}` |
| playback | `get_current_transport_info()["current_transport_state"]` | 184 | `PLAYING` / `PAUSED_PLAYBACK` / `STOPPED` / `TRANSITIONING` |
| media_uri | `get_current_media_info()["uri"]` | 186 | Used by Previous to require `x-rincon-queue:` and `SeekTrackNr` (`:159-175`) |
| `position` | `track["position"]` (`RelTime`) | 202 | A raw `"H:MM:SS"` string. Not parsed, and not used anywhere in the controller. |
| duration | — | — | **Missing.** `track["duration"]` (`TrackDuration`) is already in the same response and is simply not copied. |

**Cost per read.** Each `read_state` makes about 8 SOAP round-trips:
- zone-group topology
- `GetPositionInfo`
- `GetCurrentTransportActions`
- the queue `Browse`
- `GetTransportInfo`
- `GetTransportSettings`
- `GetMediaInfo`
- group volume, which is a snapshot plus a get (`soco/groups.py:130-136`)

**Polling cadence:**
- **Tk loop:** `ui.py:99 POLL_MS = 25`, and each tick calls `Runtime.poll()` (`runtime.py:1239-1255`).
- **State reads:** `Controller.tick()` asks for a `state` read **once per second**, and only when no command or volume write is pending (`controller.py:680-682`).
- **Worker:** all Sonos I/O runs on one worker thread, `ThreadPoolExecutor(max_workers=1, "nanod-sonos")` (`runtime.py:161`). Seeks, reads and volume writes are therefore naturally serialized.

### Writes: the volume model to copy

**Controller side** (`controller.py`):
- `position()` records a latest-wins intent: `desired_volume`, stored as an atomic `(value, group_revision)` pair (`:329-342`).
- It sets `volume_due` to at least 100 ms after the previous write (`:509-513`).
- `tick()` dispatches one `volume` effect when the intent exists, none is in flight, and the due time has passed (`:674-679`).

**Runtime side** (`runtime.py:1103-1117`):
- Enforces the rate on the I/O lane.
- Reads the **current** intent when the job actually starts, not when it was queued.
- Discards the job if the epoch or group changed.

**Adapter side** (`sonos.py:215-238`):
- `_assert_group(expected_revision)` first.
- Then the write.
- Then a 2 s readback loop at 50 ms intervals until the device reports the target.
- On timeout it raises "not confirmed" and **never replays the write** (comments at `:221-223`).

**Transport, the closest existing command** (`sonos.py:240-306`):
- Guards with `expected_track_id` (`:249-250`).
- Re-reads actions at command time (`:251`).
- Re-verifies the track right before the call (`:290-296`).
- Calls `coordinator.avTransport.Seek([...("Unit","TRACK_NR")...], timeout=self.timeout)` (`:297`).

**Seek should be a sibling of these two**: the debounce and intent handling of volume, plus the track guard and readback of transport.

---

## 2. What the installed SoCo does (0.31.2, `soco/`)

- **`seek()` signature** (`soco/core.py:875-924`): `@only_on_master def seek(self, position=None, track=None)`.
  - `position` must match `^[0-9][0-9]?:[0-9][0-9]:[0-9][0-9]$`, i.e. `H:MM:SS` or `HH:MM:SS` (`:919-920`). Otherwise it raises `ValueError`.
  - It sends `avTransport.Seek([("InstanceID",0),("Unit","REL_TIME"),("Target",position)])` (`:922-924`).
  - `track=` (zero-based) sends `Unit=TRACK_NR, Target=track+1` (`:913-916`).
  - It **takes no `timeout`**. The adapter already bounds every SoCo call through `soco.config.REQUEST_TIMEOUT = self.timeout` (`sonos.py:103`). For consistency with `sonos.py:297`, call `coordinator.avTransport.Seek(..., timeout=self.timeout)` directly.
- **Documented behaviour** (`soco/core.py:894-907`):
  - It raises UPnP error 701 "if seeking is not supported" and 711 "if the target is invalid".
  - The docstring says of a playing speaker: "it will continue to play after seek". Of a paused one: "If paused it will remain paused."
- **Coordinator only.** `@only_on_master` raises `SoCoSlaveException` on a non-coordinator (`soco/core.py:139-153`). `available_actions` is also coordinator-only (`:2258`). The companion always addresses `group.coordinator`, so this is already satisfied.
- **`get_current_track_info()`** (`soco/core.py:2004-2037`):
  - It calls `GetPositionInfo`.
  - `duration` = `TrackDuration` and `position` = `RelTime`, both strings like `"0:03:32"`. **Precision is whole seconds.** The UPnP format allows `H+:MM:SS[.F+]`, but Sonos returns whole seconds, e.g. `"0:00:00"` in `diagnostics/sonos-readiness.json:19`.
  - For line-in the metadata is `"NOT_IMPLEMENTED"` (`:2096-2098`).
  - For radio the duration is `"0:00:00"` (`:2103-2104`).
  - SoCo's docstring warns that calling this on a group member returns that member's last track, not the group's (`:2019-2021`). The companion reads the coordinator, so it is unaffected.
- **`available_actions`** (`soco/core.py:2258-2273`): documented values are `'Set','Stop','Pause','Play','Next','Previous','SeekTime','SeekTrackNr'`. The raw values `X_DLNA_SeekTime` and `X_DLNA_SeekTrackNr` are stripped to the part after the last underscore. **The seek capability is `SeekTime`.**
- **UPnP errors SoCo names for AVTransport** (`soco/services.py:911-935`):

  | Code | Meaning |
  |---|---|
  | 701 | Transition not available |
  | 710 | Seek mode not supported |
  | 711 | Illegal seek target |
  | 712 | Play mode not supported |
  | 718 | Invalid InstanceID |

  The adapter already sanitizes all of these into `SonosError` text.
- **SoCo's own use of REL_TIME seek on queues.** `Snapshot.restore()` seeks back to the saved `RelTime`, but only when a **local queue** (`x-rincon-queue:…#0`) was playing (`soco/snapshot.py:108-117, 195-208`). Streams are restored by URI, with no seek. This is the same class of content the companion plays.
- **Source classes by URI** (`soco/core.py:3081-3096`):
  - Radio: `x-sonosapi-stream:`, `x-sonosapi-radio:`, `x-sonosapi-hls:`, `x-rincon-mp3radio:`, `aac:`, `hls-radio:`, `x-sonos-http:sonos…`
  - Line-in: `x-rincon-stream:`
  - TV: `x-sonos-htastream:`
  - AirPlay and Spotify Connect: `x-sonos-vli:`

  Apple Music songs added by share link are `x-sonos-http:song%3a….mp4` items inside the local queue (the fixtures mirror this at `tests/test_cc_music.py:202-205`).

---

## 3. Sonos semantics from public sources

| Topic | Finding | Source |
|---|---|---|
| **Seek arguments** | `Unit` is `TRACK_NR`, `REL_TIME` or `TIME_DELTA`. `Target` is a 1-based track number, or `hh:mm:ss` for REL_TIME, or `+/-hh:mm:ss` for TIME_DELTA. | https://sonos.svrooij.io/services/av-transport |
| **Unsupported content or wrong speaker** | Seek "Returns error code 701 in case that content does not support Seek or send to non-coordinator". Error 800 means "Command not supported or not a coordinator". | same |
| **CurrentTransportActions** | The spec defines it as the actions that can be invoked "for the current resource at this specific point in time". Its example for an Internet live stream is only "Play, Stop". On a non-coordinator, Sonos returns only Start/Stop. | UPnP AVTransport:1 §2.2.26, http://upnp.org/specs/av/UPnP-av-AVTransport-v1-Service.pdf; svrooij (above) |
| **The flag is dynamic** | The user's own capture shows no `Next`/`Previous` with a 1-track queue, but `SeekTime` and `SeekTrackNr` present. **Re-read the actions at command time.** | `diagnostics/sonos-readiness.json:83-90` |
| **Which sources allow REL_TIME seek** | **On-demand queue tracks (Apple Music): yes.** Sonos's "Scrubbing" feature is the timeline under the artwork. A Sonos community answer adds that a radio station via any service has "no rewind or fast forward". Apple Music scrubbing on Sonos is in common use (users even scrub to kick lossless). **Radio and streams: no.** **Line-in and TV: no** (no metadata or duration; the transport is owned by the input). The user's own room advertises `SeekTime` with an Apple Music queue. | https://en.community.sonos.com/controllers-and-music-services-228995/how-do-fast-forward-or-rewind-when-playing-a-song-6875822 ; https://en.community.sonos.com/controllers-and-music-services-228995/apple-music-lossless-not-working-properly-6893926 ; `diagnostics/sonos-readiness.json:83-90` |
| **Cloud API equivalent** | `canSeek`: when false, "the `seek` command returns an error". It is true by default and set per service policy. `playbackStatus.availablePlaybackActions.canSeek` exposes it. | https://docs.sonos.com/docs/playback-policy-list.md ; https://docs.sonos.com/reference/playback-playbackstatus.md |
| **Seeking past the duration** | Sonos Control API seek: if the position exceeds the track duration, "Sonos moves to the end of the current track, which results in a skip to the next track". UPnP 711 "Illegal seek target" covers a target "not present on the media". **Always clamp below the duration.** | https://docs.sonos.com/reference/playback-seek-groupid.md ; UPnP §2.4.12.4 |
| **State during and after a seek** | UPnP: Seek "Changes TransportState to 'TRANSITIONING' and then returns immediately", then "will return to the previous transport state". The spec lists only STOPPED and PLAYING as allowed states (§2.4.12.2). Sonos also accepts a paused transport: SoCo documents "If paused it will remain paused". **Verify this live** (below). | UPnP §2.4.12.2-3; `soco/core.py:906-907` |
| **Latency** | There is no published figure. The SOAP call returns immediately (it just enters TRANSITIONING). For Apple Music the player must then re-buffer from the service with an HTTP range request. Sonos's service guide says seeking is implemented through range requests and `Content-Range`. The audible gap is likely a fraction of a second to about 1–2 s, but **this is an estimate: measure it in the live check.** | https://docs.sonos.com/docs/playback-on-sonos.md |
| **Is position immediately accurate after a seek?** | **Not guaranteed.** Position is not evented: `RelTime` is not carried in `LastChange` (packet capture in HA #181315), so it must be polled with `GetPositionInfo`. During a transition a read can still show the old clock, or `0:00:00` (HA #181315 describes this at track changes). In the same discussion a maintainer saw a Pandora seek accepted with no effect. **Confirm by polling until TRANSITIONING ends and `RelTime` lands near the target.** | https://github.com/home-assistant/core/issues/181315 ; https://github.com/home-assistant/core/pull/181323 |
| **How others guard seeks** | node-sonos-ts seeks back to a saved `RelTime` only when `RelTime` exists, `MediaDuration !== '0:00:00'`, and the source is not a broadcast. It tolerates failure "for some music services (radio or stream)". HA's Sonos `media_seek` sends `str(timedelta(seconds=int(position)))` to `soco.seek`, which gives e.g. `"0:03:05"`. | https://raw.githubusercontent.com/svrooij/node-sonos-ts/main/src/sonos-device.ts ; https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/sonos/media_player.py |
| **Rate limits and debouncing** | No documented rate limit for local UPnP. Controllers seek once on scrub release, not per pixel. The design's 250 ms quiet period plus **one seek in flight, latest target wins** (the volume pattern) is enough. The single Sonos worker already prevents overlapping SOAP writes. | design README §8; `runtime.py:161` |

---

## 4. Mapping the design to the companion

Design sources:
- `design_handoff_nano_d_master/README.md:59-60` (Seek = BINARIS BEER, 67 detents/rev, 5 s per detent)
- `:39` (don't change installed profiles)
- `:225` (REL_TIME 250 ms after the last detent; exit after 3 s idle, or on 3, Back or Open on screen)
- `specs/01…:162-167`
- Prototype, `prototypes/Browse and Snap.dc.html`:
  - `:712`: `p = clamp(pos + 5·d, 0, D−1)`, and End stop when the value does not change
  - `:634`: the song clock is frozen while seeking
  - `:664`: a 3 s idle re-arm on every turn
  - `:1000`: ring = `floor(pos/D·60)`

### 4.1 Haptic profile: no change

`PROFILES = {"volume": "BINARIS BEER", …}` (`control_center/controller.py:36-37`). `control()` sends `PROFILES[self.screen.mode]` with `min/max/position` (`:309-316`). Seek is simply a **new control entry** with profile `"BINARIS BEER"` and new bounds. The mode or sub-state key needs a `PROFILES` entry, e.g. `"seek": "BINARIS BEER"`.

The device layer accepts this:
- The profile must be in the inventory (`device.py:936-937`), and it already is.
- `min` must be 0.
- `max` must be ≤ 65 535 (`device.py:945-946`). At 5 s per detent that allows up to about 91 h.

The design's own table confirms 67 detents/rev for BINARIS BEER (`specs/03-SCREEN-and-state.md:27-29`).

### 4.2 Bounds and detent mapping

Let `D` be the parsed `TrackDuration` in seconds and `p` the position at entry. Extrapolate `p`: last polled `RelTime`, plus the time since that read while `PLAYING`.

- `T_end = max(0, D − 3)`. This is the highest target ever sent: a margin under the length so the rounding of whole-second durations never overshoots into a skip, and the readback has time to confirm before the song ends. The design's prototype uses `D − 1`; 3 s is the safer choice for real playback.
- `n0 = ceil(p / 5)`
- `max = n0 + ceil((T_end − p) / 5)`
- Enter the control with `position = n0`.
- Detent `n` maps to `t(n) = clamp(p + 5·(n − n0), 0, T_end)`.
  - `t(0) = 0:00` and `t(max) = T_end`, so the firmware's bound End stop and the LED `BOUND` moment (`specs/02-LED-choreography.md:133, 176`) fire exactly at 0:00 and at the end.
  - Each detent is ±5 s from where the user entered, as in the prototype.
  - There are about `ceil(D/5) + 1` detents, matching the design's "ceil(duration/5)".
- **Clock during Seek.** While Seek is open the LCD shows `t(n)`, a frozen clock as in prototype `:634`, not the polled `RelTime`. A state poll must not overwrite the displayed target.
- **After exit.** The display returns to the live position.

The ring lap is visual (`floor(t/D·60)`) and independent of physical rotation. A 3:30 song is about 43 detents, about 0.64 turn. A 7 min song is about 85 detents, about 1.3 turns.

### 4.3 When Seek is offered (button 3 lit or disabled)

Add to `_state()`:
- `duration` and `position_s` (both parsed; `""`, `NOT_IMPLEMENTED` or unparseable becomes `None`)
- a monotonic `position_read_at`
- `can_seek = "SeekTime" in actions and duration > 0 and playback in ("PLAYING", "PAUSED_PLAYBACK") and position_s is not None`

As belt-and-braces, also exclude media URIs of the radio, line-in, TV and `x-sonos-vli:` classes (`soco/core.py:3081-3096`).

| Case | Behaviour |
|---|---|
| Duration unknown, `0:00:00` or `NOT_IMPLEMENTED` (radio, Apple Music radio stations, line-in, TV) | `can_seek = False`. Button 3 is disabled (LED 0.14). Seek is never entered. |
| `SeekTime` missing from actions (policy, AirPlay or Spotify Connect, a non-coordinator answer) | Same as above. |
| `STOPPED` | Disabled. SeekTime is advertised when stopped (`sonos-readiness.json:17,88`), but a scrub with no audio is not meaningful. |
| **Track changes during Seek** (song ends, or a skip from another controller) | Every seek intent carries `expected_track_id`. The adapter re-checks the track right before `Seek` (as `sonos.py:290-296` does). A state poll or completion showing a new `track_id` **exits Seek** (Reveal) and **drops** any pending target. It is never applied to the new song. A track change while confirming a target within the last ~3 s counts as "song ended", not as a failure. |
| **Grouped** | The seek goes to `group.coordinator` and moves the whole group in sync. `expected_group_revision` guards it: a regroup raises `GroupChanged`, which exits Seek and reports "Group changed". Satellites and stereo pairs are already resolved by `_context()` (`sonos.py:131-138`). |
| **Seek fails** (701/711/timeout) | Head-shake or `err` flash. Seek stays open at the displayed target so the user can turn again or exit. No automatic retry, and never a replay. |
| **Exit** | Button 3, Back, Open on screen/Up next, or 3 s without a turn. Recommendation: on an explicit exit, **flush** a still-debouncing target (send it now) rather than drop it, because the LCD already showed it. Confirm this choice with the user. |

### 4.4 Implementation recipe

**Controller** (pure, mirrors volume):
- **On entry:** compute `p`, `D`, `n0`, `max`. `_enter()` a control with profile BINARIS BEER. Arm the 3 s idle deadline.
- **`position(n)` in Seek:**
  - `seek_target = t(n)`
  - `seek_due = now + 0.25`
  - re-arm the 3 s idle deadline
  - The intent is the atomic pair `(target, group_revision, track_id)`.
- **`tick()`:**
  - If there is a target, no seek in flight, and `now ≥ seek_due`, `request("seek", …)`.
  - Suppress the 1 s state poll while it is in flight. This already happens for commands (`controller.py:680`).
  - Handle the idle exit.
- **`complete("seek")`:** apply the returned state; `ok` or `err` feedback. If a newer target arrived meanwhile, the next `tick()` sends it (latest wins).
- **Other wiring:**
  - Add `"seek"` to `invalidate_actions` (`runtime.py:1165`).
  - Add it to the `obsolete_group` kinds (`controller.py:764`).
  - Add it to the `complete()` state-applying branch (`:839`).

**Runtime** (`_background`, next to `volume`, `runtime.py:1103-1117`):
- Read the **current** seek intent when the job starts.
- Discard it if the epoch, group or track changed, or Seek was exited without a flush.
- Call the adapter.

**Adapter** (`SonosAdapter.seek(seconds, expected_group_revision, expected_track_id)`, inside `self._lock`):

```text
context = _assert_group(rev); c = context[1].coordinator
track = c.get_current_track_info(); if _track_id(track) != expected -> TrackChanged
D = secs(track["duration"]); if not D -> SonosError("This source can't seek")
actions = parse(c.available_actions); if "SeekTime" not in actions -> SonosError(...)
before = c.get_current_transport_info()["current_transport_state"]
if before not in ("PLAYING","PAUSED_PLAYBACK") -> SonosError(...)
target = clamp(int(seconds), 0, max(0, D - 3))
_assert_group(rev); re-check _track_id                      # like sonos.py:292-294
c.avTransport.Seek([("InstanceID",0),("Unit","REL_TIME"),
                    ("Target", f"{target//3600}:{target%3600//60:02d}:{target%60:02d}")],
                   timeout=self.timeout)
sent = monotonic(); deadline = sent + 3.0                    # never replay the Seek
loop every 100 ms:
    _assert_group(rev)
    t = c.get_current_track_info(); if _track_id(t) != expected: (song ended near T_end -> ok) else TrackChanged
    s = c.get_current_transport_info()["current_transport_state"]
    if s != "TRANSITIONING":
        pos = secs(t["position"]); slack = (monotonic()-sent) + 1.5 if s == "PLAYING" else 1
        if target - 1 <= pos <= target + slack:
            state = _state(_assert_group(rev)); state["_applied_seek"] = target
            state["_seek_kept_state"] = (s == before)   # record whether paused stayed paused
            return state
    if monotonic() >= deadline: raise SonosError("The seek was not confirmed. Refresh before retrying.")
```

Wrap unexpected exceptions like `transport()` does (`sonos.py:303-306`). The fixtures need `"SeekTime"` added to `FakeSpeaker.available_actions`, plus `duration`/`position` added to `FakeSpeaker.track` (`tests/test_cc_music.py:226, 233`).

### 4.5 Not Sonos, but required for the UI (flagged for the build)

- **The knob contract has no Seek presentation.**
  - `presentation.LAYOUTS` (`control_center/presentation.py:57`) has no `seek`.
  - `RING_STYLES` (`:62`) is `off/level/selection/transport`.
  - `device._ring` caps `value` at 0..100 (`device.py:251-258`).
  - The 48 px `m:ss` / `of m:ss` layout and the song-lap ring therefore need a firmware and contract addition. A `song` ring could carry `index = t` and `count = D` in seconds, both ≤ 65 535.
- **The Song hand needs the same data.** The resting Song hand (`specs/02-LED-choreography.md:142`) needs the same parsed `position`/`duration`. Today the preview runs its own clock (`control_center/alive_lights.py:47-49`).

---

## 5. Proposed live check

**Not run.** It needs the user's go-ahead.

**Purpose:** confirm on the user's room (Hall) and an Apple Music queue track:
- that `SeekTime` is advertised while playing and while paused
- that REL_TIME seek lands
- how long the transition and readback take
- that paused stays paused

**What the user will notice:** one audible 20 s jump forward and back.

**Preconditions:**
- An Apple Music song from the local queue is playing, with at least 60 s left.
- The volume is whatever the user likes; the script never touches volume.
- The companion is closed, so there is no concurrent writer.
- No knob and no COM port are involved.

**Steps** (a standalone script against the pinned coordinator, using the adapter's `_context()` for group resolution):

1. **Read-only probe.** Record:
   - `GetPositionInfo` (`RelTime`, `TrackDuration`, `TrackURI`)
   - `GetCurrentTransportActions`
   - `GetTransportInfo`
   - the `GetMediaInfo` URI
   - the group revision and `track_id`

   **Stop here and report** if `SeekTime` is absent or the duration is `0:00:00`. That alone answers "this source can't seek".
2. **Forward seek.** `p0` = the extrapolated position. Send one `Seek(REL_TIME, p0 + 20 s)`, clamped to `D − 10`. Poll every 100 ms for up to 3 s and record:
   - the time until the state leaves `TRANSITIONING`
   - the time until `RelTime` is within ±2 s of the target
   - the final state, which should be `PLAYING`
3. **Seek back.** Send one `Seek(REL_TIME, p0 + elapsed)`, where elapsed is the wall-clock time since step 2. The listener ends up where the song would have been anyway. Verify it the same way.
4. **Optional paused variant.** Only if the user pauses from the Sonos app themselves: repeat steps 2–3 while paused, and check that the state is still `PAUSED_PLAYBACK` after each seek. The script never presses Play or Pause.
5. **Abort rules:**
   - Abort on any group-revision or `track_id` change, and write nothing more.
   - Never replay a Seek.
   - Never seek past `D − 10`. **Do not test the past-the-end case live:** it would skip the track.

**Output:** a small JSON in `diagnostics/`, with the same shape as `sonos-readiness.json`, containing:
- actions while playing and while paused
- the duration and position strings
- the timings
- the preserved-state flags

---

## Sources

**Project**
- `control_center/sonos.py:103, 122-145, 153-204, 215-306`
- `control_center/controller.py:36-37, 309-342, 498-513, 674-682, 764, 839`
- `control_center/runtime.py:161, 1098-1120, 1158-1174, 1239-1255`
- `control_center/ui.py:99`
- `control_center/device.py:936-948, 251-258`
- `control_center/presentation.py:57, 62`
- `control_center/alive_lights.py:47-49`
- `tests/test_cc_music.py:202-266`
- `diagnostics/sonos-readiness.json:17-19, 51-58, 83-90`
- `diagnostics/quiet-sonos-probe.json:30-33`
- `design-reference/design_handoff_nano_d_master/README.md:39, 59-60, 225`
- `specs/01-FEATURES-explorers-snap-seek.md:162-167`
- `specs/02-LED-choreography.md:133, 142, 176`
- `specs/03-SCREEN-and-state.md:27-29`
- `prototypes/Browse and Snap.dc.html:375, 634, 664, 712, 1000`

**SoCo 0.31.2**
- `soco/core.py:139-153, 875-924, 2004-2037, 2096-2104, 2258-2273, 3081-3096`
- `soco/services.py:902-935`
- `soco/snapshot.py:108-117, 195-208`
- `soco/groups.py:130-146`

**Public**
- [UPnP AVTransport:1 service template](http://upnp.org/specs/av/UPnP-av-AVTransport-v1-Service.pdf): §2.2.14, §2.2.22, §2.2.26, §2.4.12
- [svrooij Sonos AVTransport reference](https://sonos.svrooij.io/services/av-transport)
- [Sonos Control API: seek](https://docs.sonos.com/reference/playback-seek-groupid.md)
- [Sonos: playback policy list (canSeek)](https://docs.sonos.com/docs/playback-policy-list.md)
- [Sonos: playbackStatus](https://docs.sonos.com/reference/playback-playbackstatus.md)
- [Sonos: Playback on Sonos](https://docs.sonos.com/docs/playback-on-sonos.md)
- [Sonos Community: fast forward and rewind](https://en.community.sonos.com/controllers-and-music-services-228995/how-do-fast-forward-or-rewind-when-playing-a-song-6875822)
- [Sonos Community: Apple Music lossless and scrubbing](https://en.community.sonos.com/controllers-and-music-services-228995/apple-music-lossless-not-working-properly-6893926)
- [Home Assistant issue #181315: Sonos position staleness](https://github.com/home-assistant/core/issues/181315)
- [Home Assistant PR #181323: position after seek](https://github.com/home-assistant/core/pull/181323)
- [Home Assistant Sonos media_player.py](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/sonos/media_player.py)
- [node-sonos-ts sonos-device.ts](https://raw.githubusercontent.com/svrooij/node-sonos-ts/main/src/sonos-device.ts)
