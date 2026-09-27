"""Deterministic simulator fakes (CONTROL_CENTER_V5.md section 16); never open devices or touch
the desktop, the network or audio.

One ``SimControls`` object holds the knobs the r2.2 state picker offers (BS:1352-1365); the dev
window and the tests set them. The fakes raise the real adapters' exception classes, so the
runtime maps them to the section 9.10 outcomes exactly as it does for the live services.

Timings are modelled on an injectable ``clock`` / ``sleep`` pair (``time.monotonic`` /
``time.sleep`` by default); a test passes a fake clock whose ``sleep`` advances it, so every
"slow" option runs synchronously. Ring accents are fixed ints (0xRRGGBB) or None (= warm).

Artwork (``SimControls.art``, K4 section 13.2 / 13.6): items carry the art keys of each state
(``art_template``, ``art_max``, ``art_bg``, ``art_ink``). Templates use the ``simulation://``
scheme, which the artwork allowlist rejects (``artwork.artwork_url``: https ``*.mzstatic.com``
only), so the simulator never causes a download: ``simulation://art/...`` names a cover a
simulated cover source may draw, ``simulation://loading/...`` one that never arrives.

Every control reaches its state through the fakes (section 16): ``upnext`` reshapes the queue
(``longshuffle`` = more than 60 upcoming rows, ``normal`` = the album again), ``art = "list"``
holds the explorer's lists loading, and ``connected`` drives ``SimulatedDevice``'s
connected / disconnected events.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from queue import Queue
import threading
import time


_APPLE_ERRORS = ("AppleMusicError", "LikeNotConfirmed", "MusicUnavailable", "NotCatalog", "ResolveTimeout",
                 "UnlikeUnavailable")
_SONOS_ERRORS = ("GroupChanged", "NotQueueSource", "NothingPlaying", "PlayNextFailed", "QueueChanged",
                 "QueueReplacementFailed", "SeekNotConfirmed", "SeekUnavailable", "ShuffleFailed", "SongChanged",
                 "SonosError", "SonosShuffleOn", "SonosUnavailable", "TrackChanged")


class _Errors:
    """The real adapters' exception classes, imported on first raise: importing the simulator
    (ui.py does) must not load the adapters, which pull in Pillow (knob_face's no-PIL rule)."""

    def __getattr__(self, name):
        if name in _APPLE_ERRORS:
            from . import apple_music as module
        elif name in _SONOS_ERRORS:
            from . import sonos as module
        else:
            raise AttributeError(name)
        value = getattr(module, name)
        setattr(self, name, value)
        return value


_E = _Errors()


def __getattr__(name):
    """`simulation.GroupChanged` etc. still resolve (lazily) for callers that imported them here."""
    if name in _APPLE_ERRORS or name in _SONOS_ERRORS:
        return getattr(_E, name)
    raise AttributeError(name)

# ------------------------------------------------------------------ the BS library (BS:499-535)
_RGB = lambda c: (c[0] << 16) | (c[1] << 8) | c[2]  # noqa: E731
ALBUMS = [
    ("Promises", "Floating Points, Pharoah Sanders & LSO", 2021, (120, 150, 190)),
    ("Night Drive", "Chromatics", 2007, (255, 40, 90)),
    ("Heligoland", "Massive Attack", 2010, (255, 120, 30)),
    ("Moon Safari", "Air", 1998, (60, 170, 255)),
    ("Hounds of Love", "Kate Bush", 1985, (160, 90, 255)),
    ("Elis & Tom", "Elis Regina & Antônio Carlos Jobim", 1974, (255, 190, 60)),
    ("Blue Lines", "Massive Attack", 1991, (255, 40, 20)),
    ("Tropicália ou Panis et Circencis", "Various artists", 1968, (255, 150, 40)),
    ("Kind of Blue", "Miles Davis", 1959, (40, 120, 255)),
]
TRACKS = [
    ["Movement 1", "Movement 2", "Movement 3", "Movement 4", "Movement 5", "Movement 6", "Movement 7",
     "Movement 8", "Movement 9"],
    ["Night Drive", "I Want Your Love", "Running Up That Hill", "Tick of the Clock", "Healer"],
    ["Pray for Rain", "Babel", "Splitting the Atom", "Girl I Love You", "Psyche", "Flat of the Blade",
     "Paradise Circus", "Rush Minute", "Saturday Come Slow", "Atlas Air"],
    ["La Femme d’Argent", "Sexy Boy", "All I Need", "Kelly Watch the Stars", "Talisman", "Remember",
     "You Make It Easy", "Ce Matin-là", "New Star in the Sky", "Le Voyage de Pénélope"],
    ["Running Up That Hill", "Hounds of Love", "The Big Sky", "Mother Stands for Comfort", "Cloudbusting",
     "And Dream of Sheep", "Under Ice", "Waking the Witch", "Watching You Without Me", "Jig of Life",
     "Hello Earth", "The Morning Fog"],
    ["Águas de Março", "Pois É", "Só Tinha de Ser com Você", "Modinha", "Triste", "Corcovado",
     "O Que Tinha de Ser", "Por Toda a Minha Vida", "Fotografia", "Soneto de Separação",
     "Chovendo na Roseira", "Inútil Paisagem"],
    ["Safe from Harm", "One Love", "Blue Lines", "Be Thankful for What You’ve Got", "Five Man Army",
     "Unfinished Sympathy", "Daydreaming", "Lately", "Hymn of the Big Wheel"],
    ["Miserere Nobis", "Coração Materno", "Panis et Circencis", "Lindonéia", "Parque Industrial",
     "Geléia Geral", "Baby", "Três Caravelas", "Enquanto Seu Lobo Não Vem", "Mamãe Coragem",
     "Bat Macumba", "Hino ao Senhor do Bonfim"],
    ["So What", "Freddie Freeloader", "Blue in Green", "All Blues", "Flamenco Sketches"],
]
PLAYLISTS = [  # (title, albums, colour, length, unplayable index, auto)
    ("Favorite Songs", [4, 1, 2, 3], (255, 70, 70), 12, None, True),
    ("PAPER LANTERN Ep. 1", [6, 7], (150, 110, 255), 34, 20, False),
]
MORE_PLAYLISTS = [
    ("Late Night Drive", [1, 6, 2, 3], (255, 60, 110), 48),
    ("Sunday Morning", [5, 8, 3, 0], (255, 190, 90), 36),
    ("Bossa & Tropicália", [5, 7, 8, 4], (255, 150, 40), 52),
    ("Deep Focus", [0, 2, 8, 1], (90, 150, 255), 27),
    ("Kitchen Dance", [4, 6, 3, 7], (200, 90, 255), 61),
    ("Headphones Only", [0, 4, 2, 5], (80, 200, 170), 22),
]
WINDOWS = [  # (app, title, accent) BS:727-735; ChatGPT's warm marker is sent as 0
    ("Google Chrome", "Calendar · Week of Sep 22", (255, 200, 40)),
    ("Claude", "Nano D Control Center", (255, 110, 60)),
    ("Slack", "Danny Lewis", (230, 50, 200)),
    ("ChatGPT", "PCB layout questions", None),
    ("Google Chrome", "Understand the PCB", (255, 200, 40)),
    ("Bambu Studio", "Rack_Base(2)", (0, 230, 90)),
    ("File Explorer", "Downloads", (255, 190, 60)),
]


ART_SIZES = {"full": 1200, "small400": 400, "small300": 300}   # art_max (K4 13.5: 400 / 300 px are extended)
LONG_QUEUE_ROWS = 90                         # the `longshuffle` queue: 85 upcoming rows from row 5
HELD = "Simulated loading list: request discarded"   # `art = "list"`: the lists stay loading


def art_mode(art, index):
    """The art state of item ``index`` under ``SimControls.art`` (BS ``modeOf``, BS:1177): one of
    ``full``, ``small400``, ``small300``, ``none``, ``loading``."""
    if art == "mixed":
        if index % 12 == 4:
            return "small400"
        if index % 12 == 10:
            return "small300"
        if index % 9 == 7:
            return "none"
        return "full"
    return {"small": "small400", "missing": "none", "loading": "loading"}.get(art, "full")


def art_keys(art, index, identifier, colour):
    """K4 section 13.2 keys for one item: the template (never fetchable), art_max, art_bg, art_ink."""
    mode = art_mode(art, index)
    if mode == "none" or not colour:
        return {"art_template": "", "art_max": 0, "art_bg": 0, "art_ink": 0}
    scheme = "loading" if mode == "loading" else "art"
    size = ART_SIZES.get(mode, ART_SIZES["full"])
    return {"art_template": f"simulation://{scheme}/{identifier}/{{w}}x{{h}}bb.jpg", "art_max": size,
            "art_bg": _RGB(colour), "art_ink": 0xF2F2F2}


def dur_of(title):
    """BS ``durOf`` (BS:553): 170..359 s from the title."""
    x = 0
    for character in title:
        x = (x * 31 + ord(character)) % 997
    return 170 + x % 190


def _song_id(album, index):
    return str(1_400_000_000 + album * 1000 + index)


def _digest(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:24]


def album_tracks(album):
    title, artist, year, colour = ALBUMS[album % len(ALBUMS)]
    return [{"title": name, "artist": artist, "album": title, "catalog_id": _song_id(album % len(ALBUMS), k),
             "url": f"simulation://song/{_song_id(album % len(ALBUMS), k)}", "track_number": k + 1,
             "duration_ms": dur_of(name) * 1000, "art_template": ""}
            for k, name in enumerate(TRACKS[album % len(ALBUMS)])]


def playlist_tracks(albums, length, bad=None):
    rows = []
    for k in range(length):
        album = albums[k % len(albums)]
        names = TRACKS[album]
        name = names[(k // len(albums) * 2 + k) % len(names)]
        title, artist, _year, _colour = ALBUMS[album]
        index = TRACKS[album].index(name)
        rows.append({"title": name, "artist": artist, "album": title, "catalog_id": _song_id(album, index),
                     "url": f"simulation://song/{_song_id(album, index)}", "track_number": None,
                     "duration_ms": dur_of(name) * 1000, "art_template": "", "_bad": bad == k})
    return rows


class SimControls:
    """The simulator's state picker (K3 section 16); plain attributes, set by the dev window or tests."""

    def __init__(self):
        self.connected = True         # the PC connection: SimulatedDevice posts connected / disconnected
        self.source = "queue"         # queue | airplay | radio | linein | none
        self.play_mode = "NORMAL"     # the six Sonos modes
        self.pn = "ok"                # ok | slow | live | proto | partial | nothing | changed
        self.start = "ok"             # ok | slow | fail | blocked
        self.seek = "ok"              # ok | slow | slow5 | noresume | live | fail
        self.like = "ok"              # ok | loading | expired | fail
        self.upnext = "normal"        # normal (the album) | loading | foreign | longshuffle (> 60 upcoming)
        self.favs = "real"            # real | empty | many
        self.art = "full"             # full | mixed | small | missing | loading | list (the lists stay loading)
        self.snap = "ok"              # ok | hung | move | fit | integrity
        self.stage = "ok"             # ok | refused | display
        self.recent = "normal"        # normal | many | empty | error | expired


class _SimTime:
    def __init__(self, clock=None, sleep=None):
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep


# ------------------------------------------------------------------ Sonos
class SimulatedSonos:
    """A queue of row dicts with a playing row, a play mode, a position advancing on the sim clock and
    every K3 section 9 op (positional Play next with progress, confirmed Seek, the shuffle hybrid with a
    restore record, windows, jump, move_next, Previous under shuffle, group changes on demand)."""

    def __init__(self, controls=None, *, clock=None, sleep=None):
        self.controls = controls or SimControls()
        self._time = _SimTime(clock, sleep)
        self._lock = threading.RLock()
        self.state = dict(online=True, room_id="sim-den", room_label="Den",
                          group_id="sim-den", group_label="Den · Stereo pair", group_revision="sim:1",
                          group_room_count=1, volume=28, title="Night Drive", artist="Sample library",
                          can_next=True, can_previous=True, track_id="1", queue_revision="1",
                          playback="PLAYING", can_play=False, can_pause=True)
        self.fail = False
        self.queue = []                # row dicts
        self.P = 0                     # the 1-based playing row (0: no queue model)
        self.update_id = 1
        self.position_s = 74
        self._position_at = self._time.clock()
        self._transitioning_until = None
        self.record = {}               # the companion-shuffle restore record
        self.calls = []                # (op, args) of every mutating op (tests)
        self.seeks = []                # every Seek sent (never resent)
        self.inserts = []
        self._shape = "album"          # the queue shape SimControls.upnext last asked for

    # ---------------------------------------------------------------- the queue model
    def _apply_controls(self):
        """``SimControls.upnext`` reshapes the queue when it changes (section 16): ``longshuffle``
        loads a queue with more than 60 upcoming rows, any other value the album again."""
        shape = "long" if self.controls.upnext == "longshuffle" else "album"
        if shape == self._shape:
            return
        self._shape = shape
        if shape == "long":
            self.load_rows(LONG_QUEUE_ROWS, position=5)
        else:
            self.load_album()

    def load_album(self, album=4, position=5, playing=True):
        """Replace the queue with a BS album (Hounds of Love by default, BS qNow 4 → row 5)."""
        with self._lock:
            self.queue = [self._row(track) for track in album_tracks(album)]
            self.P = min(position, len(self.queue))
            self.update_id += 1
            self.state["playback"] = "PLAYING" if playing else "PAUSED_PLAYBACK"
            self.position_s = 74
            self._position_at = self._time.clock()
            self._sync()
        return self

    def load_rows(self, count, position=1):
        """A long queue of `count` rows (the `longshuffle` state: > 60 upcoming)."""
        with self._lock:
            tracks = []
            album = 0
            while len(tracks) < count:
                tracks.extend(album_tracks(album))
                album += 1
            self.queue = [self._row(track) for track in tracks[:count]]
            self.P = position
            self.update_id += 1
            self._sync()
        return self

    @staticmethod
    def _row(track):
        song = track.get("catalog_id")
        return {"title": track.get("title", ""), "artist": track.get("artist", ""), "album": track.get("album", ""),
                "song_id": str(song) if song else None, "duration_s": (track.get("duration_ms") or 0) // 1000 or
                dur_of(track.get("title", "")), "uri": track.get("url", ""),
                "signature": _digest(track.get("title", ""), song, id(track))}

    def _sync(self):
        """Mirror the queue model into the scalar state (tests may still set it directly)."""
        if not self.queue or not 1 <= self.P <= len(self.queue):
            return
        row = self.queue[self.P - 1]
        self.state.update(title=row["title"], artist=row["artist"], track_id=f"{self.P}:{row['signature']}",
                          queue_revision=str(self.update_id),
                          can_next=self.P < len(self.queue) or self._repeat() == "all",
                          can_previous=self.P > 1 or self._repeat() == "all")

    def _repeat(self):
        mode = self.controls.play_mode
        return {"REPEAT_ALL": "all", "SHUFFLE": "all", "REPEAT_ONE": "one", "SHUFFLE_REPEAT_ONE": "one"}.get(mode, "off")

    def _now_position(self):
        if self.state.get("playback") != "PLAYING":
            return self.position_s
        return self.position_s + int(self._time.clock() - self._position_at)

    def read_state(self):
        if self.fail:
            raise RuntimeError("Simulated Sonos connection lost")
        with self._lock:
            self._apply_controls()
            state = deepcopy(self.state)
            if not self.queue:
                return state
            now = self._time.clock()
            transitioning = self._transitioning_until is not None and now < self._transitioning_until
            if self._transitioning_until is not None and not transitioning:
                self._transitioning_until = None
                self.state["playback"] = "PLAYING"
                self._position_at = now
                state["playback"] = "PLAYING"
            if transitioning:
                state["playback"] = "TRANSITIONING"
            row = self.queue[self.P - 1] if 1 <= self.P <= len(self.queue) else {}
            duration = row.get("duration_s") or None
            position = min(self._now_position(), duration or 0)
            source = self.controls.source
            if state["playback"] == "STOPPED":
                source = "none"
            state.update(
                queue_length=len(self.queue), playlist_position=self.P, position_s=position, duration_s=duration,
                position=f"0:{position // 60:02d}:{position % 60:02d}",
                duration=f"0:{(duration or 0) // 60:02d}:{(duration or 0) % 60:02d}",
                read_at=now, source=source, play_mode=self.controls.play_mode,
                shuffle=self.controls.play_mode in ("SHUFFLE", "SHUFFLE_NOREPEAT", "SHUFFLE_REPEAT_ONE"),
                repeat=self._repeat(), song_id=row.get("song_id"), actions=["Next", "Pause", "Play", "Previous",
                                                                            "Seek", "SeekTime"],
                companion_shuffle=bool(self.record), host="192.0.2.10",
                can_seek=source == "queue" and bool(duration) and state["playback"] in ("PLAYING", "PAUSED_PLAYBACK")
                and (duration or 0) <= 59999,
                can_play=state["playback"] in ("PAUSED_PLAYBACK", "STOPPED"),
                can_pause=state["playback"] == "PLAYING")
            return state

    def _check(self, revision):
        self.read_state()
        if revision != self.state["group_revision"]:
            raise _E.GroupChanged("Group changed · read current volume before adjusting")

    def change_group(self):
        """A group change on demand (the next guarded op raises GroupChanged)."""
        with self._lock:
            number = int(self.state["group_revision"].split(":")[-1]) + 1
            self.state["group_revision"] = f"sim:{number}"

    def _step(self, between_steps, seconds=0.0):
        if seconds:
            self._time.sleep(seconds)
        if between_steps is not None:
            between_steps()

    # ---------------------------------------------------------------- volume and transport
    def set_volume(self, value, expected_group_revision):
        self._check(expected_group_revision)
        self.state["volume"] = value
        return self.read_state()

    def transport(self, direction, expected_group_revision, expected_track_id=None):
        self._check(expected_group_revision)
        if expected_track_id and expected_track_id != self.state["track_id"]:
            raise _E.TrackChanged("The playing track changed. Review the action and try again.")
        self.calls.append(("transport", direction))
        if direction in ("play", "pause"):
            self.state.update(playback="PLAYING" if direction == "play" else "PAUSED_PLAYBACK",
                              can_play=direction == "pause", can_pause=direction == "play")
            self.position_s = self._now_position() if direction == "pause" else self.position_s
            self._position_at = self._time.clock()
            return self.read_state()
        if self.queue:
            with self._lock:
                step = 1 if direction == "next" else -1
                self.P = (self.P - 1 + step) % len(self.queue) + 1
                self.position_s = 0
                self._position_at = self._time.clock()
                self._sync()
            return self.read_state()
        self.state["track_id"] = str(int(self.state["track_id"]) + (1 if direction == "next" else -1))
        self.state["title"] = "Sample track " + self.state["track_id"]
        return self.read_state()

    # ---------------------------------------------------------------- starts (section 9.2)
    def play_items(self, items, expected_group_revision, *, between_steps=None, name=None):
        self._check(expected_group_revision)
        tracks, total, unavailable = self._tracks(items)
        mode = self.controls.start
        if mode == "fail":
            raise _E.QueueReplacementFailed("Playback failed while staging. Added tracks were removed; "
                                         "the original queue remains.")
        for _ in tracks:
            self._step(between_steps, 2.6 / max(1, len(tracks)) if mode == "slow" else 0.0)
        with self._lock:
            self.queue = [self._row(track) for track in tracks]
            self.P = 1
            self.update_id += 1
            self.record = {}
            self.controls.play_mode = {"SHUFFLE_NOREPEAT": "NORMAL", "SHUFFLE": "REPEAT_ALL",
                                       "SHUFFLE_REPEAT_ONE": "REPEAT_ONE"}.get(self.controls.play_mode,
                                                                                self.controls.play_mode)
            self.state.update(playback="PLAYING")
            self.position_s = 0
            self._position_at = self._time.clock()
            self._sync()
            self.calls.append(("play_items", len(tracks)))
        state = self.read_state()
        state["_final_song_ids"] = [row["song_id"] for row in self.queue]
        state["_start"] = {"k": len(tracks), "n": total, "u": unavailable, "name": name}
        return state

    @staticmethod
    def _tracks(items):
        if isinstance(items, dict):
            tracks = list(items.get("tracks") or [])
            return tracks, int(items.get("total", len(tracks))), int(items.get("unavailable", 0))
        tracks = list(items or [])
        return tracks, len(tracks), 0

    # ---------------------------------------------------------------- Play next (section 9.3)
    def _gate(self, shuffle_ok=False):
        source = self.controls.source
        if source != "queue" or not self.queue:
            if source == "none" or not self.queue:
                raise _E.NothingPlaying("Nothing is playing from the Sonos queue.")
            raise _E.NotQueueSource("Not playing from the Sonos queue.", source=source)
        if not shuffle_ok and self.controls.play_mode in ("SHUFFLE", "SHUFFLE_NOREPEAT", "SHUFFLE_REPEAT_ONE"):
            raise _E.SonosShuffleOn("Sonos shuffle is on.")

    def play_next(self, items, expected_group_revision, expected_track_id, progress=None, between_steps=None):
        self._check(expected_group_revision)
        self._gate()
        if expected_track_id and expected_track_id != self.state["track_id"]:
            raise _E.SongChanged("The song changed before Play next finished.")
        tracks, _total, _unavailable = self._tracks(items)
        tracks = tracks[:100]
        mode = self.controls.pn
        per_song = {"slow": 0.5, "live": 0.54, "proto": 0.5}.get(mode, 0.0)
        if mode == "nothing":
            raise _E.PlayNextFailed("Sonos did not queue the item. Nothing was added.", outcome="nothing_added")
        start_row = self.P + 1
        inserted = []
        for index, track in enumerate(tracks):
            self._step(None, per_song)
            if mode == "changed" and index == 1:
                raise _E.SongChanged("The song changed before Play next finished.", inserted=index, rolled_back=True)
            if mode == "partial" and index == max(1, len(tracks) // 2):
                raise _E.PlayNextFailed("Play next was only partly verified. Inspect the Sonos queue.",
                                     outcome="partial", inserted=index)
            with self._lock:
                self.queue.insert(self.P + index, self._row(track))
                self.update_id += 1
                self._sync()
            inserted.append(str(track.get("catalog_id")))
            self.inserts.append(str(track.get("catalog_id")))
            if progress is not None:
                progress({"phase": "inserting", "k": index + 1, "n": len(tracks)})
            if between_steps is not None:
                between_steps()
        state = self.read_state()
        state["_inserted"] = {"start_row": start_row, "song_ids": inserted}
        return state

    # ---------------------------------------------------------------- Seek (section 9.4)
    def seek(self, seconds, expected_group_revision, expected_track_id, between_steps=None):
        self._check(expected_group_revision)
        if expected_track_id and expected_track_id != self.state["track_id"]:
            raise _E.TrackChanged("The playing track changed.")
        row = self.queue[self.P - 1] if self.queue else {}
        duration = row.get("duration_s") or 0
        if not duration:
            raise _E.SeekUnavailable("This source cannot seek.")
        target = max(0, min(int(seconds), max(0, duration - 3)))
        self.seeks.append(target)
        mode = self.controls.seek
        if mode == "fail":
            raise _E.SeekNotConfirmed("The seek was not confirmed.")
        land = {"ok": 0.6, "slow": 1.8, "slow5": 5.0, "live": 2.65, "noresume": None}.get(mode, 0.6)
        start = self._time.clock()
        with self._lock:
            self.position_s = target
            self._position_at = start
            self._transitioning_until = start + land if land is not None else float("inf")
        while True:
            self._step(between_steps, 0.1)
            now = self._time.clock()
            if land is not None and now - start >= land:
                with self._lock:
                    self._transitioning_until = None
                    self._position_at = now
                state = self.read_state()
                state["_applied_seek"] = target
                state["_seek_kept_state"] = True
                return state
            if now - start >= 8.0:
                with self._lock:
                    self._transitioning_until = None
                raise _E.SeekNotConfirmed("The seek was not confirmed.")

    # ---------------------------------------------------------------- shuffle (section 9.5)
    def load_shuffle_record(self):
        return dict(self.record)

    def shuffle_reorder(self, on, expected_group_revision, expected_track_id, *, plan=None, playnext_offsets=(),
                        expected_rows=None, playnext_song_ids=(), expected_update_id=None, progress=None,
                        between_steps=None):
        self._check(expected_group_revision)
        self._gate()
        if expected_track_id and expected_track_id != self.state["track_id"]:
            raise _E.TrackChanged("The playing track changed.")
        with self._lock:
            upcoming = self.queue[self.P:]
            if on:
                pn = [int(v) for v in playnext_offsets or ()]
                plan = [int(v) for v in plan or ()]
                if len(upcoming) > 60 or len(upcoming) - len(pn) < 2 or sorted(plan) != list(range(len(upcoming))) \
                        or plan[:len(pn)] != pn:
                    raise _E.ShuffleFailed("This queue cannot be shuffled here.")
                if expected_rows is not None and [row["signature"] for row in upcoming] != list(expected_rows):
                    raise _E.QueueChanged("The queue changed. Nothing was shuffled.")
                self.record = {"base_rows": [[row["signature"], row["song_id"]] for offset, row in enumerate(upcoming)
                                             if offset not in set(pn)]}
            else:
                if not self.record:
                    raise _E.QueueChanged("There is no companion shuffle to undo.")
        if progress is not None:
            progress({"phase": "accepted"})
        with self._lock:
            if on:
                self.queue = self.queue[:self.P] + [upcoming[offset] for offset in plan]
            else:
                order = {signature: index for index, (signature, _song) in enumerate(self.record["base_rows"])}
                # Bare ids or the ledger's [song_id, start_row] units (queue_context.playnext_units).
                pn_ids = [entry[0] if isinstance(entry, (list, tuple)) else entry for entry in playnext_song_ids or ()]
                pn_rows, base_rows = [], []
                for row in upcoming:
                    if row["signature"] in order:
                        base_rows.append(row)
                    elif row["song_id"] in pn_ids:
                        pn_rows.append(row)
                    else:
                        self.record = {}
                        raise _E.QueueChanged("The queue changed. The original order cannot be restored.")
                self.queue = self.queue[:self.P] + pn_rows + sorted(base_rows, key=lambda row: order[row["signature"]])
                self.record = {}
            self.update_id += 1
            self._sync()
            self.calls.append(("shuffle_reorder", on))
        for _ in range(3):
            self._step(between_steps)
        return self.read_state()

    def set_shuffle(self, on, expected_group_revision):
        self._check(expected_group_revision)
        mapping = {"NORMAL": "SHUFFLE_NOREPEAT", "REPEAT_ALL": "SHUFFLE", "REPEAT_ONE": "SHUFFLE_REPEAT_ONE"}
        if on:
            self.controls.play_mode = mapping.get(self.controls.play_mode, self.controls.play_mode)
        else:
            inverse = {value: key for key, value in mapping.items()}
            self.controls.play_mode = inverse.get(self.controls.play_mode, self.controls.play_mode)
        self.calls.append(("set_shuffle", on))
        return self.read_state()

    # ---------------------------------------------------------------- queue reads and moves (section 9.6)
    def queue_window(self, start, count, expected_group_revision=None):
        if expected_group_revision:
            self._check(expected_group_revision)
        if self.controls.upnext == "loading":
            raise _E.SonosUnavailable("Sonos is unavailable.")
        with self._lock:
            self._apply_controls()
            rows = []
            for index, row in enumerate(self.queue[start:start + count]):
                rows.append({"row": start + index + 1, "title": row["title"], "artist": row["artist"],
                             "album": row["album"], "sonos_art": "", "song_id": row["song_id"],
                             "duration_s": row["duration_s"], "signature": row["signature"],
                             "service": "apple" if row["song_id"] else "other"})
            return {"start": start, "rows": rows, "update_id": str(self.update_id), "total": len(self.queue)}

    def jump(self, row, expected_group_revision, expected_track_id, expected_update_id, *, name=None):
        self._check(expected_group_revision)
        if self.controls.start == "fail":
            raise _E.SonosError("Play was not confirmed.")
        with self._lock:
            if str(expected_update_id) != str(self.update_id):
                raise _E.QueueChanged("The queue changed.")
            self.P = row
            self.state["playback"] = "PLAYING"
            self.position_s = 0
            self._position_at = self._time.clock()
            self._sync()
        state = self.read_state()
        state["_start"] = {"k": 1, "n": 1, "u": 0, "name": name, "row": row}
        return state

    def move_next(self, row, expected_group_revision, expected_update_id, *, item=None):
        self._check(expected_group_revision)
        self._gate()
        with self._lock:
            if expected_update_id is not None and str(expected_update_id) != str(self.update_id):
                raise _E.QueueChanged("The queue changed.")
            if row > self.P + 1:
                moved = self.queue.pop(row - 1)
                self.queue.insert(self.P, moved)
            elif row < self.P:
                self.queue.insert(self.P, dict(self.queue[row - 1], signature=_digest("re", row, self.update_id)))
            self.update_id += 1
            self._sync()
        return self.read_state()


# ------------------------------------------------------------------ Apple Music
class SimulatedAppleMusic:
    """The flat Recently Added list (pages of 25 with meta.total), Favourite playlists, playlist meta,
    catalog songs, ratings, the add-only Like and resolve (lenient playlists skip PAPER LANTERN's track
    20), with a per-call resolve counter and an `expired` switch (401-shaped errors)."""

    RECENT_PAGE = 25
    # Kept for older dev-window code: one accent per v6 title.
    TITLES = [album[0] for album in ALBUMS]

    def __init__(self, controls=None, *, clock=None, sleep=None):
        self.controls = controls or SimControls()
        self._time = _SimTime(clock, sleep)
        self.expired = False
        self.resolve_calls = 0
        self.liked = set()
        self.likes = []
        self._cache = {}
        self._running = set()
        self._visit = 0

    def _auth(self):
        if self.expired or self.controls.recent == "expired":
            raise _E.AppleMusicError("Apple Music authorization expired · reconnect in Setup", status=401)

    def _library(self):
        count = {"many": 100, "empty": 0}.get(self.controls.recent, 26)
        items = []
        for index in range(count):
            if index % 13 == 12 and index < 26:
                playlist = PLAYLISTS[1] if index == 12 else PLAYLISTS[0]
                title, albums, colour, length, _bad, _auto = playlist
                items.append(self._item(f"p{index}", title, "Sample library", "playlist", colour, length,
                                        resource="library-playlists", index=index))
                continue
            album = index % len(ALBUMS)
            title, artist, year, colour = ALBUMS[album]
            items.append(self._item(f"a{index}", title if index < len(ALBUMS) else f"{title} ({index})", artist,
                                    "album", colour, len(TRACKS[album]), year=year,
                                    available=index != 9, index=index))
        return items

    def _item(self, identifier, title, artist, kind, colour, count, *, year=None, available=True,
              resource="library-albums", index=0, art=None):
        art = self.controls.art if art is None else art
        keys = art_keys(art, index, identifier, colour)
        accent = _RGB(colour) if colour and keys["art_template"] else None   # no art: the GEN accent (runtime)
        return {"id": identifier, "title": title, "artist": artist, "kind": kind, "available": available,
                "reason": "" if available else "No Sonos-compatible catalog match", "accent": accent,
                **keys, "year": year, "track_count": count, "resource_type": resource,
                "_resource": {"id": identifier, "type": resource}}

    def _hold(self):
        """``art = "list"``: the explorer's lists stay loading (BS "Loading list"); the controller
        keeps the list loading and asks again."""
        if self.controls.art == "list":
            raise _E.AppleMusicError(HELD)

    # ---------------------------------------------------------------- Recently Added (section 9.8.6)
    def recent_page(self, offset=0, *, visit=None, limit=RECENT_PAGE, background=False, wanted=None):
        self._auth()
        self._hold()
        if self.controls.recent == "error":
            raise _E.AppleMusicError("Apple Music could not load the library.", status=500)
        if wanted is not None and not wanted():
            raise _E.AppleMusicError("Obsolete library request discarded")
        if visit is None:
            self._visit += 1
        items = self._library()
        page = items[offset:offset + limit]
        return {"items": deepcopy(page), "offset": offset, "limit": limit, "total": len(items),
                "complete": offset + limit >= len(items), "visit": self._visit}

    def recent(self, cursor=None, limit=10):
        """The v6 pager (older callers): cursor = the next offset."""
        start = int(cursor or 0)
        page = self.recent_page(start, visit=None if cursor is None else self._visit, limit=limit)
        return {"items": page["items"], "next": str(start + limit) if not page["complete"] else None}

    # ---------------------------------------------------------------- resolve (section 9.8.7)
    @staticmethod
    def _key(item):
        return (item.get("kind"), str(item.get("id")))

    def resolve_cached(self, item, *, lenient=None):
        hit = self._cache.get(self._key(item))
        return deepcopy(hit) if hit is not None else None

    def resolve_running(self, item):
        return self._key(item) in self._running

    def evict_resolved(self, item):
        self._cache.pop(self._key(item), None)

    def preresolve(self, item, *, focused=False):
        if item.get("available") is False or self.resolve_cached(item) is not None:
            return None
        count = item.get("track_count")
        if isinstance(count, int) and count > 100:
            return None
        return self.resolve(item, background=True)

    def resolve(self, item, *, lenient=None, background=False, deadline_s=20.0):
        self._auth()
        if isinstance(item, dict) and item.get("available") is False:
            raise _E.MusicUnavailable(item.get("reason") or "This library item is unavailable.")
        cached = self.resolve_cached(item)
        if cached is not None:
            return cached
        key = self._key(item)
        self._running.add(key)
        try:
            self.resolve_calls += 1
            delay = {"slow": 1.8, "live": 3.5, "proto": 4.5}.get(self.controls.pn, 0.0)
            if delay:
                self._time.sleep(delay)
            kind = item.get("kind")
            title = item.get("title", "")
            if kind == "playlist":
                lenient = True if lenient is None else lenient
                playlist = next((p for p in PLAYLISTS if p[0] == title), None)
                if playlist is not None:
                    tracks = playlist_tracks(playlist[1], playlist[3], playlist[4])
                else:
                    more = next((p for p in MORE_PLAYLISTS if p[0] == title), MORE_PLAYLISTS[0])
                    tracks = playlist_tracks(more[1], min(more[3], 40))
            else:
                lenient = False if lenient is None else lenient
                album = next((i for i, a in enumerate(ALBUMS) if title.startswith(a[0])), 0)
                tracks = album_tracks(album)
                if self.controls.start == "blocked":
                    tracks[1]["_bad"] = True
            playable = [track for track in tracks if not track.get("_bad")]
            unavailable = len(tracks) - len(playable)
            if unavailable and not lenient:
                raise _E.MusicUnavailable("A song of this album is unavailable. Nothing was queued.")
            if not playable:
                raise _E.MusicUnavailable("This library item contains no playable tracks.")
            result = {"tracks": [{k: v for k, v in track.items() if not k.startswith("_")} for track in playable],
                      "total": len(tracks), "unavailable": unavailable}
            self._cache[key] = deepcopy(result)
            return result
        finally:
            self._running.discard(key)

    # ---------------------------------------------------------------- Up next data (sections 9.8.2-9.8.4)
    def catalog_songs(self, ids, *, background=True):
        self._auth()
        result = {}
        for position, song in enumerate(ids or ()):
            song = str(song)
            if self.controls.upnext == "foreign" and position % 3 == 2:
                result[song] = {"catalog": False}
                continue
            album = (int(song) - 1_400_000_000) // 1000 if song.isdigit() else 0
            title, artist, year, colour = ALBUMS[album % len(ALBUMS)]
            keys = art_keys(self.controls.art, position, f"s{song}", colour)
            result[song] = {"catalog": True, "album": title, "artist": artist, "track_number":
                            int(song) % 1000 + 1 if song.isdigit() else None, "disc_number": 1,
                            "duration_s": None, **keys,
                            "accent": _RGB(colour) if keys["art_template"] else None,
                            "url": f"simulation://song/{song}", "release_year": year}
        return result

    def ratings(self, ids, *, background=True):
        self._auth()
        if self.controls.like == "loading":
            raise _E.AppleMusicError("Apple Music did not answer.", status=503)
        return {str(song): 1 for song in ids or () if str(song) in self.liked}

    def like(self, catalog_id):
        """Add-only Like ([r2.2] C5-67): the favourites POST, then the ratings read-back."""
        song = str(catalog_id)
        if self.controls.like == "expired" or self.expired:
            raise _E.AppleMusicError("Apple Music sign-in expired.", status=401)
        if self.controls.like == "fail":
            raise _E.AppleMusicError("Apple Music is busy. Try again.", status=429)
        if not song.isdigit():
            raise _E.NotCatalog("This song is not in the Apple Music catalog.", status=404)
        self._time.sleep(0.4)
        self.likes.append(song)
        self.liked.add(song)
        self._time.sleep(1.0)
        if self.controls.like == "loading":
            raise _E.LikeNotConfirmed("The like was not confirmed by Apple Music.")
        return {"liked": True}

    def unlike(self, catalog_id):
        raise _E.UnlikeUnavailable("Unfavourite in Music app")

    # ---------------------------------------------------------------- Favourite playlists (section 9.8.5)
    def favourite_playlists(self, *, background=False):
        self._auth()
        self._hold()
        mode = self.controls.favs
        if mode == "empty":
            return []
        rows = [(p[0], p[1], p[2], p[3], p[5]) for p in PLAYLISTS]
        if mode == "many":
            rows += [(p[0], p[1], p[2], p[3], False) for p in MORE_PLAYLISTS]
            rows += [(f"Mix {n:02d}", [n % 9, (n + 3) % 9], (90, 90 + n * 4 % 160, 200), 20 + n, False)
                     for n in range(1, 25)]
        items = []
        for title, albums, colour, length, auto in rows:
            identifier = "pl-" + _digest(title)[:8]
            # A playlist's cover is its mosaic (playlist_meta); the list item carries its first album's
            # art (BS draws favourites `full` except with no art at all).
            art = "missing" if self.controls.art == "missing" else "full"
            item = self._item(identifier, title, "", "playlist", colour, None, resource="library-playlists", art=art)
            item.update(favourite=True, auto=auto, can_edit=not auto, has_catalog=not auto, untitled=False,
                        last_modified="2026-09-25", _albums=albums, _length=length)
            items.append(item)
        return sorted(items, key=lambda i: (i["title"].casefold(), i["id"]))

    def playlist_meta(self, playlist_id, *, duration=False, last_modified=None, background=True):
        self._auth()
        for item in self.favourite_playlists():
            if item["id"] == playlist_id:
                albums = item.get("_albums") or []
                # The first 4 distinct albums **with art**, in order (section 9.8.8): SimControls.art
                # decides which have art (`missing`: none, so the playlist is Generated).
                mosaic = []
                for a in dict.fromkeys(albums):
                    keys = art_keys(self.controls.art, a, f"al{a}", ALBUMS[a][3])
                    if keys["art_template"]:
                        mosaic.append(keys)
                length = item.get("_length") or 0
                state = "mosaic" if len(mosaic) >= 4 else ("single" if mosaic else "generated")
                return {"id": playlist_id, "count": length, "mosaic": mosaic[:4] if len(mosaic) >= 4 else mosaic[:1],
                        "art_state": state, "first_art": mosaic[0] if mosaic else None,
                        "accent": item["accent"] or 0, "duration_ms": length * 240_000 if duration else None,
                        "empty": length == 0}
        raise _E.AppleMusicError("This playlist is unavailable.", status=404, code="40403")


# ------------------------------------------------------------------ Windows
class SimulatedWindows:
    """The BS window set (BS:727-735); snap posts snap_result events per the chosen outcome (section 9.9)."""
    supports_hotkey = False

    def __init__(self, controls=None):
        self.controls = controls or SimControls()
        self.events = []
        self.placements = []
        self.cancels = []
        self.cancel_reasons = []     # the close reason each cancel carried (R8; None from an older caller)
        self.pairs = []
        self.highlights = []
        self.visible = False

    def snapshot(self):
        items = []
        for index, (app, title, colour) in enumerate(WINDOWS):
            items.append({"id": str(index), "hwnd": index + 1, "pid": 100 + index, "title": title, "app": app,
                          "available": True, "accent": _RGB(colour) if colour else None})
        return {"items": items, "index": 1, "origin": {"hwnd": 1, "pid": 100}}

    def show(self, snapshot):
        self.visible = True

    def highlight(self, index, *args, **kwargs):
        self.highlights.append(index)

    def activate(self, item):
        self.visible = False
        return bool(item.get("available"))

    def cancel(self, origin, complete=None, reason=None):
        """Restore focus; with `complete`, move the origin to that half first (U12). `reason` (K3
        5.7.4, R8): a lock or sleep close never restores focus (K4 15); the completion still runs."""
        self.visible = False
        self.cancels.append((origin, complete))
        self.cancel_reasons.append(reason)
        restored = reason not in ("lock", "sleep")
        self.events.append({"kind": "cancel_result", "restored": restored, "completed": complete is not None})
        return restored

    def snap(self, effect):
        side = effect.get("side")
        outcome = self.controls.snap
        self.placements.append((effect.get("index"), side))
        if outcome == "hung":
            self.events.append({"kind": "snap_result", "side": side, "outcome": "hung"})
            return
        if outcome == "integrity":
            self.events.append({"kind": "snap_result", "side": side, "outcome": "move_rejected"})
            return
        self.events.append({"kind": "snap_result", "side": side, "outcome": "accepted"})
        final = {"ok": "ok", "move": "move_rejected", "fit": "cant_fit"}.get(outcome, "ok")
        self.events.append({"kind": "snap_result", "side": side, "outcome": final})

    def close_pair(self, left, right, focus):
        self.visible = False
        self.pairs.append((left, right, focus))
        return True

    def take_events(self):
        events, self.events = self.events, []
        return events

    def hide(self):
        self.visible = False

    def close(self):
        pass

    def set_hotkey_enabled(self, enabled):
        pass


# ------------------------------------------------------------------ presenters (K4 section 2.3)
REQUIRED_FIELDS = {
    "explorer_open": ("t0", "source", "state", "index", "count", "items", "items_first", "items_rev", "control_id",
                      "control_min", "reduced_motion", "foreground_hwnd", "sonos_available"),
    "explorer_highlight": ("index", "control_id"),
    "explorer_source": ("t0", "source", "state", "index", "count", "items", "items_first", "items_rev"),
    "explorer_close": ("t0", "reason", "close_at_ms"),
    "upnext_open": ("t0", "rows", "now", "focus", "count", "card", "context", "shuffle", "likes_known", "loading",
                    "control_id", "control_min", "reduced_motion", "foreground_hwnd"),
    "upnext_highlight": ("index", "control_id"),
    "upnext_rows": ("t0", "reason", "rows", "now", "focus", "count", "card", "shuffle", "likes_known"),
    "upnext_close": ("t0", "reason", "close_at_ms"),
    "windows_snap": ("t0", "index", "side", "target_rect", "place_at_ms"),
    "windows_cancel": ("origin", "home", "complete", "reason"),
    "windows_close_pair": ("left", "right", "focus"),
    "toast": ("text", "exit"),
}
COMMON_FIELDS = ("kind", "request", "control_id", "view_id")
UPNEXT_REASONS = ("data", "likes", "shuffle", "queue_changed")


class FakeStagePresenter:
    """Records every pushed presenter effect with its full payload and posts the section 11.4 events
    on demand. ``strict`` asserts that each payload carries K4 section 2.3's required fields."""

    def __init__(self, controls=None, strict=True):
        self.controls = controls or SimControls()
        self.strict = strict
        self.posted = []
        self.events = []
        self.open_surface = None

    def post(self, effect):
        kind = effect.get("kind")
        if self.strict:
            missing = [name for name in COMMON_FIELDS + REQUIRED_FIELDS.get(kind, ()) if name not in effect]
            if missing:
                raise AssertionError(f"{kind} is missing {missing}")
            if kind == "upnext_rows" and effect.get("reason") not in UPNEXT_REASONS:
                raise AssertionError(f"upnext_rows reason {effect.get('reason')!r}")
        self.posted.append(dict(effect))
        surface = {"explorer_open": "explorer", "upnext_open": "upnext"}.get(kind)
        if surface is not None:
            stage = self.controls.stage
            if stage == "refused":
                self.events.append({"kind": "refused", "surface": surface, "reason": "device"})
                return
            self.open_surface = surface
            self.events.append({"kind": "opened", "surface": surface})
            if stage == "display":
                self.open_surface = None
                self.events.append({"kind": "closed", "surface": surface, "reason": "display"})
        elif kind in ("explorer_close", "upnext_close"):
            surface = "explorer" if kind == "explorer_close" else "upnext"
            if self.open_surface == surface:
                self.open_surface = None
                self.events.append({"kind": "closed", "surface": surface, "reason": effect.get("reason")})

    def emit(self, kind, **fields):
        self.events.append({"kind": kind, **fields})

    def take_events(self):
        events, self.events = self.events, []
        return events

    def of(self, kind):
        return [effect for effect in self.posted if effect.get("kind") == kind]


class SimulatedToasts:
    """The toast service (K4 section 10.3) for the simulator and tests: records every toast."""

    def __init__(self):
        self.shown = []

    def toast(self, text, exit=False):
        self.shown.append((text, bool(exit)))


# ------------------------------------------------------------------ the device bridge (section 16 "PC connection")
class _DeviceEvents(Queue):
    """The bridge's event queue; each read first turns a ``SimControls.connected`` change into its
    ``connected`` / ``disconnected`` event (the runtime drains it on its poll)."""

    def __init__(self, device):
        super().__init__()
        self._device = device

    def get_nowait(self):
        self._device.sync()
        return super().get_nowait()


class SimulatedDevice:
    """A device bridge fake driven by ``SimControls.connected``: a presentation-5 knob that claims
    when connected, answers every ``enter`` with ``ready`` and records every command. It never
    opens a port."""

    alive = False

    def __init__(self, controls=None, presentation=5):
        self.controls = controls or SimControls()
        self.presentation = presentation
        self.commands = []
        self.connected = False            # what the runtime was last told
        self.events = _DeviceEvents(self)

    def sync(self):
        want = bool(self.controls.connected)
        if want == self.connected:
            return
        self.connected = want
        if want:
            self.events.put({"kind": "connected",
                             "capabilities": {"controlCenter": True, "presentation": self.presentation}})
        else:
            self.events.put({"kind": "disconnected", "message": "Knob disconnected"})

    def submit(self, *command):
        self.commands.append(command)
        if command and command[0] == "enter" and self.connected and isinstance(command[1], dict):
            self.events.put({"kind": "ready", "id": command[1].get("id")})

    def post_progress(self, *args):
        self.commands.append(("progress",) + args)
