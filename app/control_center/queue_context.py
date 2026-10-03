"""The Up next provenance ledger (CONTROL_CENTER_V5.md section 9.7.3; C5-23, C5-24).

The ledger remembers what the companion itself put in the Sonos queue: the base segment
of the last successful start (``play_items``) and every successful Play next block,
newest first. ``classify(rows)`` attributes the current queue rows to it by catalog song
id, as a multiset (each id consumed once per occurrence, a Play-next id before a base id,
but never for a row above the row its block was inserted at), so the attribution survives
the companion shuffle's permutation. Any row it cannot
attribute (no song id, or an id the ledger does not hold) makes the queue **foreign**:
Up next then says ``Sonos queue`` and never guesses an album (C5-23).

Persisted per pinned room to ``%LOCALAPPDATA%\\DeskDial\\data\\queue-ledger.json`` (control_center.paths):
catalog ids, names, years and artwork templates only (no tokens, no URLs of the queue,
no window titles). Pure: no network, no Sonos, no Tk.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from .paths import queue_ledger_file

SEGMENT_KINDS = ("album", "playlist", "song", "playnext")
PLAYNEXT_SEGMENTS_MAX = 64
LEDGER_VERSION = 1

# Copy (VOC section 9.3, K3 section 15.3); the host fits placeholders to their lines.
FOREIGN_TITLE = "Sonos queue"                               # overlay.upnext.foreign_title
FOREIGN_SUB = "Started in another app · {n} songs"          # overlay.upnext.foreign_sub
SUB_FAVOURITE = "Favourite playlist · {n} songs · {duration}"
SUB_PLAYLIST = "Playlist · {n} songs · {duration}"          # overlay.upnext.sub_playlist
ROW_NOT_CATALOG = " · not in Apple Music"                   # overlay.upnext.row_not_catalog


def default_path() -> Path:
    return queue_ledger_file()


def format_duration(duration_ms) -> str:
    """``{h} h {mm} min`` or ``{m} min`` (overlay.explorer.meta_playlist); "" when unknown."""
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms <= 0:
        return ""
    minutes = round(duration_ms / 60000)
    if minutes >= 60:
        return f"{minutes // 60} h {minutes % 60:02d} min"
    return f"{max(1, minutes)} min"


def _songs(n) -> str:
    return "1 song" if n == 1 else f"{n} songs"


def _count_sub(template: str, n, duration_ms) -> str:
    """``… · {n} songs · {duration}`` with the singular and without an unknown duration."""
    duration = format_duration(duration_ms)
    head = template.split(" · {n} songs")[0]
    parts = [head, _songs(n)] if isinstance(n, int) else [head]
    if duration:
        parts.append(duration)
    return " · ".join(parts)


@dataclass
class Segment:
    kind: str                      # album | playlist | song | playnext
    name: str = ""
    artist: str = ""
    year: int | None = None
    library_id: str = ""
    art_template: str = ""
    accent: int = 0
    song_ids: list = field(default_factory=list)
    favourite: bool = False
    auto: bool = False
    created_at: float = 0.0
    count: int | None = None       # the item's song count (playlist sub)
    duration_ms: int | None = None
    start_row: int | None = None   # playnext: the row the block started at (classify's position rule)
    album: str = ""                # song: the song's album (the title Up next shows)

    def __post_init__(self):
        if self.kind not in SEGMENT_KINDS:
            raise ValueError("Unknown segment kind")
        self.song_ids = [str(v) for v in (self.song_ids or []) if v is not None and str(v)]

    @classmethod
    def from_dict(cls, value: dict) -> "Segment":
        known = {key: value[key] for key in cls.__dataclass_fields__ if key in value}
        return cls(**known)


@dataclass
class Context:
    """The classification of the current queue rows (section 9.7.3)."""
    kind: str                      # album | playlist | foreign (a base song is sent as playlist)
    title: str
    sub: str
    base_kind: str | None          # album | playlist | song | None (foreign)
    roles: list                    # per row: "base" | "playnext" | "foreign"
    segment: Segment | None = None

    def presenter(self) -> dict:
        """The ``context{kind, title, sub}`` K4 draws as given (section 11.1)."""
        return {"kind": self.kind, "title": self.title, "sub": self.sub}

    def playnext_offsets(self, first_upcoming: int = 0) -> list:
        """0-based offsets (from ``first_upcoming``) of the rows attributed to Play next, ascending."""
        return [i - first_upcoming for i, role in enumerate(self.roles)
                if i >= first_upcoming and role == "playnext"]


class QueueLedger:
    """Per pinned room; persisted to %LOCALAPPDATA%\\DeskDial\\data\\queue-ledger.json
    (ids, names and artwork templates only; no tokens)."""

    def __init__(self, room_uid: str | None = None, *, path=None, clock=None, autosave: bool = True):
        self.room_uid = room_uid or ""
        self.path = Path(path) if path else default_path()
        self._clock = clock or time.time
        self.autosave = autosave
        self._lock = threading.RLock()       # the in-memory ledger (classify readers); never held over disk I/O
        self._save_lock = threading.Lock()   # serialises writers (DD-BUG-031): the newest snapshot lands last
        self.base: Segment | None = None
        self.playnext: list = []   # newest first

    # ------------------------------------------------------------------ writes
    def record_start(self, segment: Segment, final_song_ids) -> None:
        """A successful ``play_items``: the queue is exactly ``final_song_ids`` now; replaces everything."""
        with self._lock:
            base = Segment.from_dict(asdict(segment))
            base.song_ids = [str(v) for v in final_song_ids or []]
            base.created_at = base.created_at or self._clock()
            self.base, self.playnext = base, []
        self._changed()

    def append_playnext(self, start_row: int, song_ids, context: Segment | None = None) -> None:
        """A successful ``play_next`` (or a ``move_next`` re-insert): newest first."""
        with self._lock:
            source = asdict(context) if context is not None else {}
            source.update(kind="playnext", song_ids=list(song_ids or []), start_row=start_row,
                          created_at=self._clock())
            self.playnext.insert(0, Segment.from_dict(source))
            del self.playnext[PLAYNEXT_SEGMENTS_MAX:]
        self._changed()

    def clear(self) -> None:
        with self._lock:
            self.base, self.playnext = None, []
        self._changed()

    def playnext_song_ids(self) -> list:
        """Every Play-next segment's ids, newest block first (section 9.5.3)."""
        with self._lock:
            return [song for segment in self.playnext for song in segment.song_ids]

    def playnext_units(self) -> list:
        """``[song_id, start_row]`` for every Play-next unit, newest block first: what the runtime
        passes as a shuffle-off effect's ``playnext_song_ids`` ([WP6-r22]). The start row lets the
        adapter give a played Play-next row its unit back (the position rule of ``classify``), so
        an upcoming base twin is restored to its place; ``None`` when a segment has no start row
        (an older file: the adapter then treats the id as a bare one)."""
        with self._lock:
            units = []
            for segment in self.playnext:
                start = segment.start_row
                start = start if isinstance(start, int) and not isinstance(start, bool) and start > 0 else None
                units.extend([song, start] for song in segment.song_ids)
            return units

    # ------------------------------------------------------------------ classification
    def classify(self, rows, *, total: int | None = None, first_row: int = 1) -> Context:
        """Attribute ``rows`` (row dicts with ``song_id`` and ``row``, or bare ids / None) to the ledger.

        Multiset of ``base.song_ids`` ⊎ every Play-next block; each row's id is consumed once,
        a Play-next id before a base id; an unattributable row (None, or an id the multiset no
        longer holds) → the whole queue is **foreign**. ``total`` (T) fills the foreign sub.

        Position rule (C5-45, section 9.5.2 ``pn``): a Play-next id is taken first only for a row
        at or below its block's ``start_row``. Our rows only move down after an insert (a later
        Play next goes after the then-playing row; the companion shuffle and ``move_next`` never
        move a row at or before the playing row), so a row above ``start_row`` holding the same
        id is a base row (a played song re-queued with Play next or ``move_next``). A row the
        rule leaves without a unit still takes any Play-next unit left before it counts as
        foreign, so foreign detection stays the plain id multiset (C5-24). Row numbers are a row
        dict's ``row``, else ``first_row`` + the index; a segment without ``start_row`` (older
        files) matches any row.
        """
        rows = list(rows or [])
        ids, numbers = [], []
        for index, row in enumerate(rows):
            song = row.get("song_id") if isinstance(row, dict) else row
            ids.append(str(song) if song is not None and str(song) else None)
            number = row.get("row") if isinstance(row, dict) else None
            numbers.append(number if isinstance(number, int) and not isinstance(number, bool)
                           else first_row + index)
        with self._lock:
            base_left = Counter(self.base.song_ids) if self.base else Counter()
            playnext_left = {}   # song id -> the start rows of its remaining Play-next units
            for segment in self.playnext:
                start = segment.start_row
                start = start if isinstance(start, int) and not isinstance(start, bool) else 0
                for song in segment.song_ids:
                    playnext_left.setdefault(song, []).append(start)
            base = self.base
        roles = [None] * len(ids)
        for index in sorted(range(len(ids)), key=lambda i: numbers[i]):   # queue order
            song, starts = ids[index], playnext_left.get(ids[index]) or []
            eligible = [start for start in starts if start <= numbers[index]]
            if song and eligible:
                starts.remove(max(eligible))
                roles[index] = "playnext"
            elif song and base_left[song] > 0:
                base_left[song] -= 1
                roles[index] = "base"
            elif song and starts:
                starts.remove(min(starts))   # moved above its insert row (another app removed rows)
                roles[index] = "playnext"
            else:
                roles[index] = "foreign"
        count = total if isinstance(total, int) else len(ids)
        if "foreign" in roles or base is None:
            # Without a base segment (no start of ours) only Play-next rows remain: nothing
            # tells what the queue is, so it is the other app's queue too.
            return Context("foreign", FOREIGN_TITLE, FOREIGN_SUB.replace("{n}", str(count)), None, roles)
        if base.kind == "album":
            sub = " · ".join(part for part in (base.artist, str(base.year) if base.year else "") if part)
            return Context("album", base.name, sub, "album", roles, base)
        if base.kind == "playlist":
            template = SUB_FAVOURITE if base.favourite else SUB_PLAYLIST
            n = base.count if isinstance(base.count, int) else len(base.song_ids)
            return Context("playlist", base.name, _count_sub(template, n, base.duration_ms), "playlist", roles, base)
        n = base.count if isinstance(base.count, int) else len(base.song_ids)
        return Context("playlist", base.album or base.name, _count_sub(SUB_PLAYLIST, n, base.duration_ms),
                       "song", roles, base)

    # ------------------------------------------------------------------ persistence
    def _changed(self):
        """After a write, outside ``_lock`` (DD-BUG-031: a classify on the Tk thread never waits for the fsync)."""
        if self.autosave:
            try:
                self.save()
            except OSError:
                pass  # the in-memory ledger stays valid; the next change tries again

    def _room_entry(self) -> dict:
        return {"base": asdict(self.base) if self.base else None,
                "playnext": [asdict(segment) for segment in self.playnext]}

    def _read_all(self) -> dict:
        try:
            if not self.path.is_file() or self.path.stat().st_size > 4_000_000:
                return {}
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION or not isinstance(data.get("rooms"), dict):
            return {}
        return data

    def load(self) -> "QueueLedger":
        """Load this room's ledger (a missing, corrupt or other-version file is an empty ledger)."""
        rooms = self._read_all().get("rooms", {})
        entry = rooms.get(self.room_uid) if isinstance(rooms, dict) else None
        base, playnext = None, []
        if isinstance(entry, dict):
            try:
                base = Segment.from_dict(entry["base"]) if isinstance(entry.get("base"), dict) else None
                playnext = [Segment.from_dict(value) for value in entry.get("playnext") or []
                            if isinstance(value, dict)][:PLAYNEXT_SEGMENTS_MAX]
            except (TypeError, ValueError):
                base, playnext = None, []
        with self._lock:
            self.base, self.playnext = base, playnext
        return self

    def save(self) -> None:
        """Atomically write this room's entry, keeping the other rooms' entries. The re-read and
        the rewrite are one json.loads and one json.dumps (GIL-holding C calls). For a 5000-song base
        with 64 Play-next blocks (104 KB) the H5 bench measured p50 / p95 0.26 / 0.47 ms and 0.32 /
        0.45 ms in its 03:15 run, p95 at most 0.53 and 0.61 ms over six runs (gil-parse-hold.md
        section 2.3), within K3 section 1.2's 1 ms.

        DD-BUG-031: only the room entry's snapshot holds ``_lock``; the re-read, the temp write, the fsync
        and the replace run under ``_save_lock`` alone, so ``classify`` readers never wait on disk I/O. A
        writer snapshots after taking ``_save_lock``, so the newest state is the one written last."""
        with self._save_lock:
            with self._lock:
                entry = self._room_entry()
            data = self._read_all() or {"version": LEDGER_VERSION, "rooms": {}}
            data["rooms"][self.room_uid] = entry
            payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
            self._write(payload)

    def _write(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, prefix=".queue-ledger-",
                                             delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
