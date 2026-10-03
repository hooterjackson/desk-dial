"""Synchronous, pinned-room Sonos adapter for the companion's audio lane.

No discovery or network I/O occurs on import or construction. Queue replacement
stages and verifies all new songs before removing the old queue. Sonos does not
offer a transaction spanning these calls: failures are explicit and an encrypted
recovery snapshot is retained, never silently treated as successful enqueueing.

CONTROL_CENTER_V5.md section 9 (K3) adds Play next (positional inserts at P+1+i,
verified, with a guarded rollback of only our rows), Seek (confirmed by read-back,
never resent), the shuffle hybrid (companion ``ReorderTracksInQueue`` for <= 60
upcoming rows with a persisted restore record; Sonos play mode above), queue
windows, Up next Play (``jump``) and ``move_next``. Long jobs are written as steps
(section 1.1): each step takes the adapter lock for its own calls only and the job
calls ``between_steps()`` with the lock released, so the runtime can run queued
short jobs (volume, Seek, Play/Pause, state) between them. Nothing here activates
a window or touches the desktop.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit, parse_qs
from xml.sax.saxutils import escape

from .credentials import CredentialError, CredentialStore, _dpapi
from .artwork import sonos_artwork_url
from .home_assistant import is_lan_host


PLAY_NEXT_MAX = 100           # C5-21: the first 100 songs in order
COMPANION_SHUFFLE_MAX = 60    # U4: companion reorder for <= 60 upcoming rows
LAP_COUNT_MAX = 59_999        # K1 section 4.3: Seek is offered only for D <= 59 999 s (C5-51)
SEEK_MARGIN_S = 3             # T_end = D - 3
SEEK_CONFIRM_S = 8.0          # seek_confirm_ms 8000 ([r2.2] C5-68; rev 4 C5-65: 5.0)
SEEK_POLL_S = 0.1
SEEK_GROUP_CHECK_S = 0.5
SEEK_NO_TRANSITION_S = 1.0    # never saw TRANSITIONING: confirm only from 1.0 s after the reply
SEEK_LANDED = ("PLAYING", "PAUSED_PLAYBACK")   # [r2.2] C5-68: landed = playback resumed
SEEK_OFF_TARGET_S = 2         # [r2.2] a landing further off is logged (diagnostic only, not a condition)
READBACK_S = 2.0              # transport / play mode read-back window
READBACK_POLL_S = 0.05
# DD-BUG-050: a speaker Volume Limit clamps SetGroupVolume. A read-back that moved from the start
# toward the target, stopped short of it and held for this long is the speaker's limit, not a
# failed write; a limit learned that way also accepts later steps that read exactly that level.
VOLUME_CLAMP_STABLE_S = 0.2
# A knob turned one detent at a time reaches the limit exactly (59 -> 60 confirms), so the next
# step (60 -> 61) reads back unchanged. An upward write that holds at its start for this long,
# when the start is the level this group's previous upward step confirmed, is that limit too.
# Longer than VOLUME_CLAMP_STABLE_S so a slow coordinator is not mistaken for a limit.
VOLUME_UNMOVED_STABLE_S = 0.6
# Queue reads and the GIL (K3 section 1.2, K4 section 4.7.3, [G1] G1-5). soco parses a Browse(Q:0)
# answer twice: the SOAP envelope with ElementTree's expat parser (one GIL-holding C call) and the
# DIDL-Lite inside it with lxml, which parses with the GIL released. The H5 bench
# (tools/stage_checks/gil_parse_hold.py; the record is design-reference/ui-v2-analysis/gil-parse-hold.md
# section 2.2) measured, p50 / p95 in ms of the 03:15 run [p50 range; p95 range over six runs]:
# the envelope of 100 rows 0.26 / 0.28 [0.26-0.49; 0.28-0.54], of 21 rows 0.15 / 0.20
# [0.07-0.15; 0.07-0.20], and the ZoneGroupState envelope of 32 players 0.15 / 0.20
# [0.15-0.17; 0.17-0.28]. All stay within the 1 ms design target, so pages keep 100 rows, no
# full-queue read is deferred while an episode runs, and every poll reads the zone groups fresh.
QUEUE_PAGE_ROWS = 100
SHUFFLE_MODES = frozenset({"SHUFFLE", "SHUFFLE_NOREPEAT", "SHUFFLE_REPEAT_ONE"})
SHUFFLE_ON = {"NORMAL": "SHUFFLE_NOREPEAT", "REPEAT_ALL": "SHUFFLE", "REPEAT_ONE": "SHUFFLE_REPEAT_ONE"}
SHUFFLE_OFF = {value: key for key, value in SHUFFLE_ON.items()}
REPEAT_OF = {"NORMAL": "off", "SHUFFLE_NOREPEAT": "off", "REPEAT_ALL": "all", "SHUFFLE": "all",
             "REPEAT_ONE": "one", "SHUFFLE_REPEAT_ONE": "one"}
_TIME = re.compile(r"([0-9]{1,5}):([0-9]{1,2}):([0-9]{1,2})(?:\.[0-9]{1,9}(?:/[0-9]{1,9})?)?")

# Diagnostics only: numbers and status codes, never titles, URIs, room or group names.
_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())  # the application configures the real handlers


class SonosError(RuntimeError):
    pass


class SonosUnavailable(SonosError):
    """A transport error or an unreachable speaker (``sonos_unavailable``)."""


class GroupChanged(SonosError):
    pass


class TrackChanged(SonosError):
    pass


class SongChanged(TrackChanged):
    """Play next: the song ended before the first insert (``song_changed``, C5-22: no retry)."""

    def __init__(self, message: str, *, inserted=0, rolled_back=False):
        super().__init__(message)
        self.inserted, self.rolled_back = inserted, rolled_back


class QueueChanged(SonosError):
    pass


class NotQueueSource(SonosError):
    """The current source is not the Sonos queue (``not_queue_source``; ``source`` is its class)."""

    def __init__(self, message: str, *, source: str = "none"):
        super().__init__(message)
        self.source = source


class NothingPlaying(NotQueueSource):
    def __init__(self, message: str):
        super().__init__(message, source="none")


class SonosShuffleOn(SonosError):
    pass


class QueueFull(SonosError):
    pass


class PlayNextFailed(SonosError):
    """Play next stopped after its checks: ``outcome`` is ``nothing_added`` (nothing of ours is
    left: refused at the first insert, or rolled back) or ``partial`` (the rollback could not prove
    the rows were only ours, so they stay). ``group_changed``: a group check stopped it (section
    9.10: the op's outcome is ``group_changed`` whatever the rollback did, as for ``play_items``)."""

    def __init__(self, message: str, *, outcome: str, inserted=0, rolled_back=False, group_changed=False):
        super().__init__(message)
        self.outcome, self.inserted, self.rolled_back = outcome, inserted, rolled_back
        self.group_changed = group_changed


class SeekUnavailable(SonosError):
    pass


class SeekNotConfirmed(SonosError):
    pass


class StartTimeout(SonosError):
    """The ``play_items`` staging passed its ``6 + 0.75·N`` s deadline (C5-37, revised 2026-09-27)."""


class ShuffleFailed(SonosError):
    pass


class QueueReplacementFailed(SonosError):
    """``play_items`` stopped after it changed the queue. ``partial``: the rollback could not prove
    the rows were ours (the "inspect Sonos" notice); ``group_changed``: a group check stopped it
    (section 9.10: ``group_changed``, whatever the rollback did)."""

    def __init__(self, message: str, *, recovery_saved=False, partial=False, timeout=False,
                 group_changed=False):
        super().__init__(message)
        self.recovery_saved = recovery_saved
        self.partial = partial
        self.timeout = timeout
        self.group_changed = group_changed


def sonos_outcome(error, op: str) -> str:
    """K3 section 9.10 outcome for an exception from a Sonos op (``op`` = the effect kind)."""
    if isinstance(error, GroupChanged) or getattr(error, "group_changed", False) is True:
        return "group_changed"
    if isinstance(error, SonosUnavailable):
        return "sonos_unavailable"
    if op == "play_next":
        if isinstance(error, TrackChanged):
            return "song_changed"
        if isinstance(error, PlayNextFailed):
            return error.outcome
        if isinstance(error, NotQueueSource):
            return "not_queue_source"
        if isinstance(error, SonosShuffleOn):
            return "sonos_shuffle_on"
        return "nothing_added"   # QueueFull, QueueChanged, an invalid item: nothing of ours was queued
    if op == "move_next":
        if isinstance(error, NotQueueSource):
            return "not_queue_source"
        if isinstance(error, SonosShuffleOn):
            return "sonos_shuffle_on"
        if isinstance(error, PlayNextFailed):
            return error.outcome
        return "failed"
    if op == "seek":
        if isinstance(error, TrackChanged):
            return "song_changed"
        return "not_confirmed"
    if op == "shuffle_reorder":
        return "queue_changed" if isinstance(error, QueueChanged) else "failed"
    if op in ("play_items", "jump"):
        return "start_failed"
    return "failed"


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# ---------------------------------------------------------------------- Play next progress
# Section 9.3 payloads; [r2.2] C5-69 / C5-71 (VOC-R28, VOC-R30): the knob meta is
# `Finding songs…` while the job resolves and until the first insert is verified (k == 0, the
# first payload of a pre-resolved item), then `Queueing… {k} of {n}`, k counting verified
# inserts; `Queueing… 0 of {n}` is never shown. The Working comet runs for the whole job (K2 M33).
PLAYNEXT_RESOLVING = "knob.meta.playnext.resolving"
PLAYNEXT_PROGRESS = "knob.meta.playnext.progress"
PLAYNEXT_COPY = {PLAYNEXT_RESOLVING: "Finding songs…", PLAYNEXT_PROGRESS: "Queueing… {k} of {n}"}


def playnext_resolving(n=None) -> dict:
    """The payload at job start: ``{"phase": "resolving", "n": n or None}``."""
    return {"phase": "resolving", "n": n if _count(n) is not None and n > 0 else None}


def playnext_inserting(k: int, n: int) -> dict:
    """``{"phase": "inserting", "k", "n"}``: after each verified insert (``play_next``), or with
    ``k = 0`` at the press when the item was pre-resolved (the resolve cache hit, C5-66)."""
    return {"phase": "inserting", "k": k, "n": n}


def playnext_meta(payload) -> tuple:
    """The knob meta for a Play next progress payload: ``(copy id, params)``."""
    payload = payload if isinstance(payload, dict) else {}
    k, n = _count(payload.get("k")), _count(payload.get("n"))
    if payload.get("phase") == "inserting" and k is not None and n is not None and 1 <= k <= n:
        return PLAYNEXT_PROGRESS, {"k": k, "n": n}
    return PLAYNEXT_RESOLVING, {}


def playnext_line(payload) -> str:
    """``playnext_meta`` as text: `Finding songs…` or `Queueing… {k} of {n}`."""
    copy_id, params = playnext_meta(payload)
    return PLAYNEXT_COPY[copy_id].format(**params)


# ---------------------------------------------------------------------- start counts
_NO_PROXY_LOCK = threading.Lock()


def bypass_proxy_for(*hosts) -> None:
    """Add LAN speaker addresses to NO_PROXY / no_proxy (DD-RES-004). soco sends its SOAP calls through
    module-level ``requests``, which honours a system or HTTP(S)_PROXY proxy; that proxy cannot reach a
    speaker on the owner's network. Existing entries are kept; public hosts are never added."""
    _merge_no_proxy([str(h).strip() for h in hosts if isinstance(h, str) and is_lan_host(h)])


# The IPv4 ranges is_lan_host treats as the owner's network. requests matches a CIDR NO_PROXY entry
# against an IP-literal URL, so discovery can bypass the proxy before soco learns any speaker address.
_LAN_CIDRS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10")


def bypass_proxy_for_lan_ranges() -> None:
    """Before discovery (DD-RES-004): soco.discover queries the answering speaker's topology over SOAP
    inside the call, so its IP cannot be added first; add the private IPv4 ranges instead."""
    _merge_no_proxy(list(_LAN_CIDRS))


def _merge_no_proxy(wanted) -> None:
    if not wanted:
        return
    with _NO_PROXY_LOCK:
        current = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        entries = [e.strip() for e in current.replace(";", ",").split(",") if e.strip()]
        known = {e.lower() for e in entries}
        added = [h for h in dict.fromkeys(wanted) if h.lower() not in known]
        if not added:
            return
        merged = ",".join(entries + added)
        os.environ["NO_PROXY"] = merged
        os.environ["no_proxy"] = merged


def start_outcome(start) -> str:
    """VOC section 8.5 for a verified start's ``_start``: ``playlist_partial`` when songs were
    unavailable (a lenient playlist, U6), else ``ok``."""
    return "playlist_partial" if start_partial_copy(start) is not None else "ok"


def start_partial_copy(start) -> dict | None:
    """[r2.2] C5-70: a partly playable start's copy, or None when it played everything (or its
    counts are not usable): ``status`` = `Playing {k} of {n}` (``knob.status.partial``) and
    ``toast`` = `Playing {k} of {n} · {u} songs unavailable`, `1 song` when u = 1
    (``toast.start.partial``)."""
    start = start if isinstance(start, dict) else {}
    k, n, u = _count(start.get("k")), _count(start.get("n")), _count(start.get("u"))
    if k is None or n is None or u is None or not (1 <= k < n) or u < 1:
        return None
    songs = "1 song" if u == 1 else f"{u} songs"
    status = f"Playing {k} of {n}"
    return {"status": status, "toast": f"{status} · {songs} unavailable"}


# The queue-recovery copy and the GIL ([G1] G1-5: no hold over about 2 ms while an overlay can take
# input; heavy work in chunks under 1 ms). One json.dumps of the whole record held the GIL for p95
# 1.43-2.24 ms at 1,000 rows and 8.6-14.3 ms at 5,000 (MAX_QUEUE) on the H5 bench (gil-parse-hold.md
# section 2.3), and a start runs it while the knob's input path is live. The record is therefore
# encoded one value, and one queue row, at a time (a few microseconds each; the interpreter hands the
# GIL over between them at the 1 ms switch interval). The largest single C calls left are the one
# join of the parts and DPAPI's copy in and out: p95 0.76, 0.80 and 0.55 ms for the 4.4 MB of 5,000
# bench rows (section 2.4). CryptProtectData, the write and fsync release the GIL.
def _recovery_json_parts(record: dict) -> list[bytes]:
    """``json.dumps(record)`` (string keys; default separators, ASCII output) as a list of small byte
    strings whose join is byte for byte ``json.dumps(record).encode("utf-8")``. Each list value is
    encoded one element at a time; every other value, and each element, with one small
    ``json.dumps``."""
    if not record:
        return [b"{}"]
    parts = []
    for index, (key, value) in enumerate(record.items()):
        parts.append(((", " if index else "{") + json.dumps(key) + ": ").encode("ascii"))
        if isinstance(value, list):
            parts.append(b"[")
            for position, element in enumerate(value):
                if position:
                    parts.append(b", ")
                parts.append(json.dumps(element).encode("ascii"))
            parts.append(b"]")
        else:
            parts.append(json.dumps(value).encode("ascii"))
    parts.append(b"}")
    return parts


class _RecoveryStore(CredentialStore):
    """``queue-recovery.bin``: the ``CredentialStore`` file format (``MAGIC`` + DPAPI-protected
    JSON, readable by ``load``), written from JSON the adapter already encoded in parts, so no
    single call encodes the whole record."""

    def save_encoded(self, data: bytes) -> None:
        """Atomically write ``data`` (UTF-8 JSON of a mapping) as ``CredentialStore.save`` does."""
        if not isinstance(data, bytes) or not data.startswith(b"{"):
            raise CredentialError("Credentials must be a mapping.")
        protected = _dpapi(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".credentials-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(self.MAGIC)
                stream.write(protected)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            raise CredentialError("The encrypted credential file could not be saved.") from None
        finally:
            if temporary and temporary.exists():
                temporary.unlink()


@dataclass
class _QueueSnapshot:
    items: list
    revision: str
    total: int


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _signature(item):
    resources = getattr(item, "resources", [])
    return (getattr(item, "title", ""), tuple(str(resource.uri) for resource in resources))


def row_signature(item) -> str:
    """The queue row's ``signature`` digest (section 9.6.1): what ``expected_rows`` and the
    shuffle restore record hold (no titles or URIs are stored)."""
    return _digest(_signature(item))


def _song_id_from_uri(uri) -> str | None:
    match = re.search(r"song[:/](\d+)(?:\D|$)", unquote(str(uri or "")), re.IGNORECASE)
    return match.group(1) if match else None


def _song_id(item) -> str | None:
    for resource in getattr(item, "resources", []):
        found = _song_id_from_uri(resource.uri)
        if found:
            return found
    return None


def _secs(value) -> int | None:
    """``H:MM:SS`` (UPnP REL_TIME / duration) in whole seconds, None when unknown."""
    if not isinstance(value, str):
        return None
    match = _TIME.fullmatch(value.strip())
    if match is None:
        return None
    hours, minutes, seconds = (int(match.group(i)) for i in (1, 2, 3))
    if minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _hms(seconds: int) -> str:
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _actions(raw) -> set:
    return {a.strip().split("_")[-1] for value in (raw or []) for a in str(value).split(",") if a.strip()}


def _upnp_code(error):
    try:
        return int(getattr(error, "error_code", None))
    except (TypeError, ValueError):
        return None


def _noop(*_args, **_kwargs):
    return None


def _playnext_units(values) -> dict:
    """The Play-next units of a shuffle-off effect (``playnext_song_ids``, section 9.5.3), by song
    id. A plain song id (the K3 section 9.5.3 interface) has no start row (``start`` None). A
    ``[song_id, start_row]`` pair is a unit of ``QueueLedger.playnext_units()`` (WP6-A1): the row
    its block was inserted at, 0 when the ledger has none (an older file), which the ledger's
    ``classify`` treats as matching any row."""
    units = {}
    for value in values or ():
        start = None
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            value, start = value[0], (value[1] if len(value) > 1 else None)
            if isinstance(start, bool) or not isinstance(start, int) or start < 0:
                start = 0
        if value is None or isinstance(value, bool) or not str(value):
            continue
        units.setdefault(str(value), []).append({"start": start, "played": False, "used": False})
    return units


def _eligible_unit(units, song, number):
    """``QueueLedger.classify``'s position rule: the free ledger unit of ``song`` whose block was
    inserted at or above row ``number`` (the latest start row first), or None. Plain ids never
    qualify (they carry no start row)."""
    found = [unit for unit in units.get(song) or () if unit["start"] is not None and unit["start"] <= number
             and not unit["played"] and not unit["used"]] if song else []
    return max(found, key=lambda unit: unit["start"]) if found else None


def _left_unit(units, song):
    """Any unit of ``song`` no upcoming row has taken, or None: a free plain id first, then a free
    ledger unit (the lowest start row, as ``classify``), then one a played row gave back (so a
    row the shuffle kept as Play next is never refused; the id multiset still bounds the rows)."""
    found = [unit for unit in units.get(song) or () if not unit["used"]] if song else []
    if not found:
        return None
    return min(found, key=lambda unit: (unit["played"], unit["start"] is not None, unit["start"] or 0))


def _record_attributes(items, record_rows) -> bool:
    """Whether a companion-shuffle record still describes this queue (DD-BUG-034): every base row
    it holds is still in the queue (by signature digest, as often as the record holds it). The app
    only ever inserts rows (Play next) or moves them (the shuffle), so a queue replaced or cleared
    elsewhere fails this; rows added elsewhere are left to Shuffle off's own attribution."""
    need = {}
    for entry in record_rows:
        if isinstance(entry, (list, tuple)) and entry:
            need[entry[0]] = need.get(entry[0], 0) + 1
    have = {}
    for item in items:
        digest = row_signature(item)
        have[digest] = have.get(digest, 0) + 1
    return all(have.get(digest, 0) >= count for digest, count in need.items())


def _attribute_restore(items, position, record_rows, playnext_song_ids):
    """Shuffle off (section 9.5.3 step 2): attribute every upcoming row (after the 1-based playing
    row ``position``) to the restore record (a base row, by its signature digest) or to Play next.
    Returns ``(pn_signatures, [(original index, signature), ...])``, or ``(None, None)`` when a row
    is foreign.

    [WP6-r22] Two passes, so that the restore equals the controller's preview (``_restore_order``
    ranks the rows by the ledger's roles, ``QueueLedger.classify``):

    1. ``[song_id, start_row]`` units (``QueueLedger.playnext_units()``, WP6-A1) follow the
       ledger's position rule in queue order: a row at or below a unit's start row takes that unit
       (the latest start row first) before the record. A played row gives its unit back, and an
       upcoming row that takes one is Play next. So a Play next of a song the shuffle already
       played stays next, and the base twin of a played Play-next row goes back to its index.
    2. Every other row, and every row of a payload of plain song ids (the K3 section 9.5.3
       interface), is attributed record first, counted per signature as in phase 1 and
       ``simulation.py``: of the k rows left with one signature, as many as the record still holds
       are base rows, and the others need an id left (else foreign). Such rows are identical, and a
       Play next always inserts ahead of the base rows, so the earliest are the Play-next ones (the
       row ``classify`` gives the unit to). Plain ids cannot tell a played Play-next row from its
       base twin, so a Play next of a song the shuffle already played goes back to that played
       row's index; only units restore that case exactly.

    A unit left over (a plain id first, then the lowest start row, then one a played row gave back)
    serves any row that needs one, so a row the shuffle kept as Play next is never refused."""
    base = {}
    for index, entry in enumerate(record_rows):
        if isinstance(entry, (list, tuple)) and entry:
            base.setdefault(entry[0], []).append(index)
    units = _playnext_units(playnext_song_ids)
    starts = [unit["start"] for group in units.values() for unit in group if unit["start"] is not None]
    first = max(1, min(starts)) if starts else position + 1   # rows above every start row give nothing back
    for number in range(first, position + 1):
        unit = _eligible_unit(units, _song_id(items[number - 1]), number)
        if unit is not None:
            unit["played"] = True
    upcoming = items[position:]
    roles = [None] * len(upcoming)   # pass 1: "pn" for a row an eligible unit takes
    for offset, item in enumerate(upcoming):
        unit = _eligible_unit(units, _song_id(item), position + 1 + offset)
        if unit is not None:
            unit["used"] = True
            roles[offset] = "pn"
    digests = [row_signature(item) for item in upcoming]
    left = {}
    for offset, digest in enumerate(digests):
        if roles[offset] is None:
            left[digest] = left.get(digest, 0) + 1
    extra = {digest: max(0, count - len(base.get(digest) or ())) for digest, count in left.items()}
    pn_rows, base_rows = [], []
    for offset, item in enumerate(upcoming):   # pass 2, in queue order
        digest = digests[offset]
        if roles[offset] is None:
            if extra[digest] == 0:
                base_rows.append((base[digest].pop(0), _signature(item)))
                continue
            extra[digest] -= 1
            unit = _left_unit(units, _song_id(item))
            if unit is None:
                return None, None
            unit["used"] = True
        pn_rows.append(_signature(item))
    return pn_rows, base_rows


class SonosAdapter:
    MAX_QUEUE = 5000
    # K3 section 9.2 W5 fallback: False drops the per-song 1-row tail read (each insert's returned
    # position is still checked) and verifies the whole staged tail once after staging. Only if
    # live check W5 misses its gate; the contract default is True.
    stage_tail_reads = True
    # Staging deadline (C5-37): base + per song. Measured 2026-09-27: ~0.49 s/song with tail reads (0.47 without;
    # the share-link AddURIToQueue itself dominates), so the
    # old 6 + 0.15*N (11.1 s for 34 songs) failed 'PAPER LANTERN Ep. 1' at song 23. Generous per-song budget.
    STAGE_DEADLINE_BASE_S = 6.0
    STAGE_DEADLINE_PER_SONG_S = 0.75

    def __init__(self, host: str, room_uid: str | None = None, *, timeout: float = 5.0,
                 soco_factory=None, discover_fn=None, share_link_factory=None,
                 recovery_store=None, shuffle_store=None, clock=None, sleep=None):
        try:
            address = ipaddress.ip_address(host)
            if address.version != 4:
                raise ValueError()
        except ValueError:
            raise SonosError("Enter the Sonos speaker's IPv4 address.") from None
        self.host = str(address)
        self.room_uid = room_uid
        self.timeout = timeout
        self._factory = soco_factory
        self._discover = discover_fn
        self._share_link_factory = share_link_factory
        self._speaker = None
        self._lock = threading.RLock()
        self._last_state = {}
        self._last_source = None
        self._cached_context = None   # (context, monotonic time) for read_state(reuse_context_s)
        self._volume_ceiling = {}     # group uid -> level a speaker Volume Limit clamped to (DD-BUG-050)
        self._volume_confirmed = {}   # group uid -> (level, upward): the last level set_volume confirmed
        self.last_recovery = None
        self.recovery_store = recovery_store
        self.shuffle_store = shuffle_store
        self._shuffle_record = None   # None = not loaded; {} = no record
        self._shuffle_checked = None  # the queue UpdateID the record was last found attributable at (DD-BUG-034)
        self._shuffle_job = False     # a companion shuffle job is moving rows (its UpdateIDs are its own)
        self._shuffle_drop_pending = False   # a drop whose store write failed: retried by the next state read
        self._clock = clock
        self._sleeper = sleep

    # ------------------------------------------------------------------ plumbing
    def _now(self) -> float:
        return (self._clock or time.monotonic)()

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            (self._sleeper or time.sleep)(seconds)

    def _dependencies(self):
        if self._factory is None:
            try:
                import soco
                from soco.plugins.sharelink import ShareLinkPlugin
            except ImportError:
                raise SonosError("Install the control-center dependencies to enable Sonos.") from None
            # Bound all property calls too, including those without timeout kwargs.
            soco.config.REQUEST_TIMEOUT = self.timeout
            soco.config.ZGT_EVENT_FALLBACK = False
            self._factory = soco.SoCo
            self._discover = self._discover or soco.discover
            self._share_link_factory = self._share_link_factory or ShareLinkPlugin
        if self._speaker is None:
            bypass_proxy_for(self.host)
            self._speaker = self._factory(self.host)

    def discover(self) -> list[dict]:
        """Explicit, bounded local discovery; no cross-home multicast assumption."""
        with self._lock:
            self._dependencies()
            bypass_proxy_for_lan_ranges()
            try:
                speakers = self._discover(timeout=min(self.timeout, 5), include_invisible=False) if self._discover else []
                return sorted([{"uid": zone.uid, "name": zone.player_name, "host": zone.ip_address}
                               for zone in (speakers or []) if not zone.is_bridge], key=lambda x: x["name"].casefold())
            except Exception:
                raise SonosError("Sonos discovery did not complete. Enter the room's IP address directly.") from None

    def _context(self):
        self._dependencies()
        speaker = self._speaker
        speaker.zone_group_state.clear_cache()
        # The configured host is only a discovery seed after the UID is pinned.
        zones = list(speaker.all_zones)
        bypass_proxy_for(*(getattr(z, "ip_address", None) for z in zones))   # coordinators and members (DD-RES-004)
        room = next((z for z in zones if z.uid == self.room_uid), None) if self.room_uid else speaker
        if room is None:
            raise GroupChanged("The selected Sonos room is no longer available. Reconnect the intended room.")
        if getattr(room, "is_satellite", False):
            parent = getattr(room, "_satellite_parent", None)
            if parent is None:
                raise SonosError("Select the primary room speaker, not its bonded satellite or Sub.")
            room = parent
        group = room.group
        if group is None:
            raise SonosError("Select the primary speaker of the stereo pair.")
        if self.room_uid is None:
            self.room_uid = room.uid
        visible = set(speaker.visible_zones)
        room_members = sorted((m for m in group.members if m in visible), key=lambda m: m.uid)
        revision = _digest([self.room_uid, group.uid, group.coordinator.uid,
                            sorted(m.uid for m in group.members)])
        context = room, group, room_members, revision
        self._cached_context = (context, self._now())
        return context

    def _assert_group(self, expected: str):
        context = self._context()
        if not expected or context[3] != expected:
            # [r2.2] C5-70 names it `Speaker group changed` ("Group" alone is ambiguous); this is the
            # desktop notice's full text, and the v6 controller matches it by "group changed".
            raise GroupChanged("The speaker group changed. Review the displayed group before adjusting it.")
        return context

    @staticmethod
    def _track_id(track: dict) -> str:
        return _digest([track.get("uri", ""), track.get("playlist_position", ""),
                        track.get("title", ""), track.get("artist", "")])

    @staticmethod
    def _previous_target(track: dict, actions: set, queue_total: int, play_mode: str, media_uri: str):
        """Return a 1-based preceding queue track, never restart the current one."""
        if not media_uri.startswith("x-rincon-queue:") or "SeekTrackNr" not in actions:
            return None, "This source does not expose a preceding queue track."
        if play_mode not in {"NORMAL", "REPEAT_ALL", "REPEAT_ONE"}:
            return None, "Previous is unavailable while shuffle history cannot be verified."
        try:
            position = int(track.get("playlist_position", "0"))
        except (TypeError, ValueError):
            return None, "The current queue position is unavailable."
        if not 1 <= position <= queue_total:
            return None, "The current queue position is unavailable."
        if position > 1:
            return position - 1, ""
        if play_mode == "REPEAT_ALL" and queue_total > 1:
            return queue_total, ""
        return None, "There is no preceding track in this queue."

    @staticmethod
    def _position(track: dict) -> int:
        try:
            return max(0, int(track.get("playlist_position") or 0))
        except (TypeError, ValueError):
            return 0

    def _source(self, playback: str, media_uri: str, queue_length: int, position: int, track: dict) -> str:
        """VOC section 8.1 source class (C5-38): STOPPED or no track → none; the queue only
        with a valid row; ``x-sonos-vli:`` with airplay → airplay, other vli → radio; line-in
        and TV → linein; any other URI → radio; TRANSITIONING keeps the previous class."""
        if playback == "TRANSITIONING" and self._last_source is not None:
            return self._last_source
        uri = str(media_uri or "")
        if playback == "STOPPED" or not (uri or track.get("uri")):
            return "none"
        if uri.startswith("x-rincon-queue:"):
            return "queue" if queue_length > 0 and 1 <= position <= queue_length else "none"
        if uri.startswith("x-sonos-vli:"):
            return "airplay" if "airplay" in uri.lower() else "radio"
        if uri.startswith(("x-rincon-stream:", "x-sonos-htastream:")):
            return "linein"
        return "radio" if uri else "none"

    def _state(self, context) -> dict:
        room, group, room_members, revision = context
        coordinator = group.coordinator
        track = coordinator.get_current_track_info()
        read_at = self._now()
        raw_actions = coordinator.available_actions
        actions = _actions(raw_actions)
        queue = coordinator.get_queue(start=0, max_items=1)
        playback = coordinator.get_current_transport_info().get("current_transport_state", "UNKNOWN")
        play_mode = coordinator.play_mode
        media_uri = coordinator.get_current_media_info().get("uri", "")
        queue_length = int(queue.total_matches)
        previous_target, previous_reason = self._previous_target(track, actions, queue_length, play_mode, media_uri)
        position = self._position(track)
        source = self._source(playback, media_uri, queue_length, position, track)
        self._last_source = source
        # C5-19: under Sonos native shuffle Previous uses avTransport.Previous when offered.
        shuffle_previous = (play_mode in SHUFFLE_MODES and "Previous" in actions and source == "queue")
        position_s = _secs(track.get("position", ""))
        duration_s = _secs(track.get("duration", "")) or None
        state = {"online": True, "room_id": room.uid, "room_label": room.player_name,
                 "group_id": group.uid,
                 "group_label": ", ".join(m.player_name for m in room_members) or room.player_name,
                 "group_room_count": len(room_members),
                 "group_revision": revision, "volume": int(group.volume),
                 "title": track.get("title", ""), "artist": track.get("artist", ""),
                 "artwork_url": sonos_artwork_url(track.get("album_art", ""), coordinator.ip_address),
                 "artwork_host": coordinator.ip_address,
                 "can_next": "Next" in actions, "can_previous": previous_target is not None or shuffle_previous,
                 "can_play": "Play" in actions and playback in ("STOPPED", "PAUSED_PLAYBACK"),
                 "can_pause": "Pause" in actions and playback == "PLAYING",
                 "previous_reason": "" if shuffle_previous else previous_reason, "play_mode": play_mode,
                 "track_id": self._track_id(track), "queue_revision": str(queue.update_id),
                 "playback": playback, "queue_length": queue_length,
                 # The same get_current_track_info() read as the rest of the track
                 # (read-only): "H:MM:SS", "" or "NOT_IMPLEMENTED" (streams). The runtime
                 # parses both for the knob's song position (ALIVE.md section 10.2).
                 "position": track.get("position", ""), "duration": track.get("duration", ""),
                 # K3 section 9.1 additions (same reads, no extra round trip).
                 "playlist_position": position, "position_s": position_s, "duration_s": duration_s,
                 "read_at": read_at, "source": source,
                 "can_seek": (source == "queue" and "SeekTime" in actions and duration_s is not None
                              and 0 < duration_s <= LAP_COUNT_MAX and position_s is not None
                              and playback in ("PLAYING", "PAUSED_PLAYBACK")),
                 "shuffle": play_mode in SHUFFLE_MODES, "repeat": REPEAT_OF.get(play_mode, "off"),
                 "song_id": _song_id_from_uri(track.get("uri", "")), "actions": sorted(actions),
                 "companion_shuffle": self._companion_shuffle_current(coordinator, str(queue.update_id)),
                 "host": room.ip_address}
        self._last_state = state
        return dict(state)

    def read_state(self, *, reuse_context_s: float = 0.0) -> dict:
        """The 1 s poll. ``reuse_context_s`` > 0 reuses a zone-group context read at most that many
        seconds ago (at most 3 s); every guard before a write still reads it fresh. K3 section 1.2
        needs it only if the ZoneGroupState parse held the GIL over 1 ms; the H5 bench measured
        0.15-0.17 ms at p50 and 0.17-0.28 ms at p95 for 32 players (gil-parse-hold.md section 2.2),
        so the runtime polls with the default (a fresh read)."""
        with self._lock:
            try:
                cached = self._cached_context
                if reuse_context_s > 0 and cached is not None and self._now() - cached[1] <= min(reuse_context_s, 3.0):
                    return self._state(cached[0])
                return self._state(self._context())
            except SonosError as error:
                return dict(self._last_state, online=False, error=str(error))
            except Exception:
                return dict(self._last_state, online=False, error="Sonos is unavailable. Check the selected room and network.")

    # ------------------------------------------------------------------ volume, transport
    def set_volume(self, value: int, expected_group_revision: str) -> dict:
        with self._lock:
            try:
                target = max(0, min(100, int(value)))
                context = self._assert_group(expected_group_revision)
                group_uid = getattr(context[1], "uid", None)
                start = int(context[1].volume)
                context[1].volume = target
                # Group writes may return before the coordinator reports the
                # new value. Never acknowledge an old read as this command's
                # result, and never replay the write while awaiting readback.
                deadline = self._now() + READBACK_S
                stable_value, stable_since = None, None
                while True:
                    context = self._assert_group(expected_group_revision)
                    observed = int(context[1].volume)
                    if observed == target:
                        state = self._state(self._assert_group(expected_group_revision))
                        if state["volume"] == target:
                            self._volume_confirmed[group_uid] = (target, target >= start)
                            return state
                    now = self._now()
                    if observed != stable_value:
                        stable_value, stable_since = observed, now
                    ceiling = self._volume_ceiling.get(group_uid)
                    if ceiling is not None and observed > ceiling:
                        self._volume_ceiling.pop(group_uid, None)   # the limit was raised or removed
                        ceiling = None
                    # DD-BUG-050: a Volume Limit holds the level short of the target. Accept it
                    # once it is stable: either it moved up from the start toward the target, or
                    # it is exactly the limit this group clamped to before.
                    clamped = start < observed < target or (ceiling is not None and observed == ceiling < target)
                    # ... or it never moved off a start that this group's last upward step
                    # confirmed: the previous detent landed exactly on the limit.
                    at_limit = observed == start < target and self._volume_confirmed.get(group_uid) == (start, True)
                    hold = VOLUME_CLAMP_STABLE_S if clamped else VOLUME_UNMOVED_STABLE_S
                    if (clamped or at_limit) and now - stable_since >= hold:
                        state = self._state(self._assert_group(expected_group_revision))
                        if state["volume"] == observed:
                            self._volume_ceiling[group_uid] = observed
                            self._volume_confirmed[group_uid] = (observed, True)
                            return state
                    remaining = deadline - now
                    if remaining <= 0:
                        if observed == start < target and stable_since is not None and stable_value == start:
                            # An upward write that held at its start for the whole window (first
                            # step after a restart, at the limit): this one still errors, but the
                            # next upward step that holds at this level is accepted as the limit.
                            self._volume_ceiling[group_uid] = start
                        raise SonosError("The requested volume was not confirmed. Refresh the room state before retrying.")
                    self._sleep(min(READBACK_POLL_S, remaining))
            except SonosError:
                raise
            except Exception:
                raise SonosUnavailable("The volume command could not be confirmed. Refresh the room state before retrying.") from None

    def transport(self, direction: str, expected_group_revision: str,
                  expected_track_id: str | None = None) -> dict:
        if direction not in ("previous", "next", "play", "pause"):
            raise SonosError("Choose Previous, Next, Play, or Pause.")
        with self._lock:
            try:
                context = self._assert_group(expected_group_revision)
                coordinator = context[1].coordinator
                track = coordinator.get_current_track_info()
                if expected_track_id and expected_track_id != self._track_id(track):
                    raise TrackChanged("The playing track changed. Review the action and confirm again.")
                actions = _actions(coordinator.available_actions)
                if direction in ("play", "pause"):
                    target = "PLAYING" if direction == "play" else "PAUSED_PLAYBACK"
                    playback = coordinator.get_current_transport_info().get("current_transport_state", "UNKNOWN")
                    # Another Sonos controller may have already performed the
                    # displayed action. Do not invert it or dispatch it twice.
                    if playback == target:
                        return self._state(self._assert_group(expected_group_revision))
                    allowed = ("STOPPED", "PAUSED_PLAYBACK") if direction == "play" else ("PLAYING",)
                    if playback not in allowed or direction.title() not in actions:
                        raise SonosError(f"This source does not currently support {direction.title()}.")
                    self._assert_group(expected_group_revision)
                    if self._track_id(coordinator.get_current_track_info()) != self._track_id(track):
                        raise TrackChanged("The playing track changed. Review Play/Pause and try again.")
                    arguments = [("InstanceID", 0)]
                    if direction == "play":
                        arguments.append(("Speed", 1))
                    getattr(coordinator.avTransport, direction.title())(arguments, timeout=self.timeout)
                    # A successful SOAP response alone is not confirmation of
                    # the new state. Read back without replaying the command.
                    deadline = self._now() + READBACK_S
                    while True:
                        context = self._assert_group(expected_group_revision)
                        observed = context[1].coordinator.get_current_transport_info().get("current_transport_state")
                        if observed == target:
                            state = self._state(context)
                            if state["playback"] == target:
                                return state
                        remaining = deadline - self._now()
                        if remaining <= 0:
                            raise SonosError(f"{direction.title()} was not confirmed. Refresh the room state before retrying.")
                        self._sleep(min(READBACK_POLL_S, remaining))
                if direction == "previous":
                    queue = coordinator.get_queue(start=0, max_items=1)
                    play_mode = coordinator.play_mode
                    media_uri = coordinator.get_current_media_info().get("uri", "")
                    if (play_mode in SHUFFLE_MODES and "Previous" in actions
                            and media_uri.startswith("x-rincon-queue:")):
                        # C5-19: Sonos picks the last played track under its own shuffle.
                        self._assert_group(expected_group_revision)
                        if self._track_id(coordinator.get_current_track_info()) != self._track_id(track):
                            raise TrackChanged("The playing track changed. Review Previous and confirm again.")
                        coordinator.avTransport.Previous([("InstanceID", 0)], timeout=self.timeout)
                        return self._state(self._assert_group(expected_group_revision))
                    target, reason = self._previous_target(
                        track, actions, int(queue.total_matches), play_mode, media_uri)
                    if target is None:
                        raise SonosError(reason)
                    # Do not let a delayed confirmation seek relative to an old
                    # track or a queue edited during capability checks.
                    self._assert_group(expected_group_revision)
                    if self._track_id(coordinator.get_current_track_info()) != self._track_id(track):
                        raise TrackChanged("The playing track changed. Review Previous and confirm again.")
                    if str(coordinator.get_queue(start=0, max_items=1).update_id) != str(queue.update_id):
                        raise QueueChanged("The queue changed. Review Previous and confirm again.")
                    coordinator.avTransport.Seek([("InstanceID", 0), ("Unit", "TRACK_NR"), ("Target", target)], timeout=self.timeout)
                else:
                    if "Next" not in actions:
                        raise SonosError("This source does not currently support Next.")
                    coordinator.avTransport.Next([("InstanceID", 0)], timeout=self.timeout)
                return self._state(self._assert_group(expected_group_revision))
            except SonosError:
                raise
            except Exception:
                raise SonosUnavailable("The track command could not be confirmed. Refresh before retrying.") from None

    # ------------------------------------------------------------------ queue helpers
    def _queue(self, coordinator) -> _QueueSnapshot:
        items, revision, total = [], None, None
        while total is None or len(items) < total:
            page = coordinator.get_queue(start=len(items), max_items=QUEUE_PAGE_ROWS)
            page_revision, page_total = str(page.update_id), int(page.total_matches)
            if page_total > self.MAX_QUEUE:
                raise SonosError("The Sonos queue is too large to replace safely with this control.")
            if revision is not None and (revision != page_revision or total != page_total):
                raise QueueChanged("The queue changed while loading. Nothing was replaced.")
            revision, total = page_revision, page_total
            items.extend(page)
            if not page and len(items) < total:
                raise QueueChanged("The complete Sonos queue could not be verified.")
        return _QueueSnapshot(items, revision or "0", total or 0)

    @staticmethod
    def _slice(coordinator, start: int, count: int) -> _QueueSnapshot:
        """Rows start+1..start+count (0-based ``start``), paged at ``QUEUE_PAGE_ROWS`` (100) under one
        UpdateID."""
        items, revision, total = [], None, None
        while len(items) < count:
            page = coordinator.get_queue(start=start + len(items),
                                         max_items=min(QUEUE_PAGE_ROWS, count - len(items)))
            page_revision, page_total = str(page.update_id), int(page.total_matches)
            if revision is not None and (revision != page_revision or total != page_total):
                raise QueueChanged("The queue changed while reading it.")
            revision, total = page_revision, page_total
            if not page:
                break
            items.extend(page)
        return _QueueSnapshot(items, revision or "0", total or 0)

    def _save_recovery(self, coordinator, original: _QueueSnapshot, group_revision: str):
        serialized = []
        for item in original.items:
            metadata = getattr(item, "didl_metadata", None)
            if metadata is None:
                from soco.data_structures import to_didl_string
                metadata = to_didl_string(item)
            serialized.append({"title": getattr(item, "title", ""),
                               "uri": item.resources[0].uri if item.resources else "",
                               "metadata": metadata})
        recovery = {"room_uid": self.room_uid, "coordinator_uid": coordinator.uid,
                    "group_revision": group_revision, "queue_revision": original.revision,
                    "items": serialized, "track": coordinator.get_current_track_info(),
                    "transport": coordinator.get_current_transport_info(),
                    "play_mode": coordinator.play_mode}
        if self.recovery_store is None:
            default = CredentialStore().path.with_name("queue-recovery.bin")
            self.recovery_store = _RecoveryStore(default)
        # [G1] G1-5: the record is encoded in parts (_recovery_json_parts), never with one json.dumps
        # of the whole queue. A store without ``save_encoded`` (the tests' in-memory stores) gets
        # the mapping.
        save_encoded = getattr(self.recovery_store, "save_encoded", None)
        if callable(save_encoded):
            save_encoded(b"".join(_recovery_json_parts(recovery)))
        else:
            self.recovery_store.save(recovery)
        self.last_recovery = recovery

    def _remove_range(self, coordinator, start: int, count: int, update_id: str):
        if not count:
            return
        coordinator.avTransport.RemoveTrackRangeFromQueue(
            [("InstanceID", 0), ("UpdateID", int(update_id)),
             ("StartingIndex", start + 1), ("NumberOfTracks", count)], timeout=self.timeout)

    @staticmethod
    def _validate_items(items) -> list[str]:
        songs = []
        for item in items:
            if not isinstance(item, dict):
                raise SonosError("Every track needs a verified Apple Music song link before playback.")
            parsed = urlsplit(item.get("url", ""))
            song_id = str(item.get("catalog_id", ""))
            if (parsed.scheme != "https" or parsed.netloc != "music.apple.com" or
                    not re.fullmatch(r"/[a-z]{2}/album/[^/]+/\d+", parsed.path) or
                    not re.fullmatch(r"\d+", song_id) or parse_qs(parsed.query).get("i") != [song_id]):
                raise SonosError("Every track needs a verified Apple Music song link before playback.")
            songs.append(song_id)
        return songs

    @staticmethod
    def _tracks(items):
        """(tracks, total, unavailable) from a track list or an ``AppleMusicClient.resolve`` result."""
        if isinstance(items, dict):
            tracks = items.get("tracks")
            total, unavailable = items.get("total"), items.get("unavailable")
            return tracks, total if isinstance(total, int) else None, unavailable if isinstance(unavailable, int) else 0
        return items, None, 0

    def _gate_queue(self, coordinator, *, shuffle_ok: bool = False):
        """The queue-source and Sonos-shuffle gates of Play next / move_next (section 9.3 steps 2-3)."""
        uri = coordinator.get_current_media_info().get("uri", "")
        if not str(uri).startswith("x-rincon-queue:"):
            source = self._source("PLAYING", uri, 1, 1, {"uri": uri}) if uri else "none"
            raise NotQueueSource("Not playing from the Sonos queue.", source=source)
        if not shuffle_ok and coordinator.play_mode in SHUFFLE_MODES:
            raise SonosShuffleOn("Sonos shuffle is on.")

    # ------------------------------------------------------------------ start (section 9.2)
    def play_items(self, items, expected_group_revision: str, *, between_steps=None, name=None) -> dict:
        """Replace the queue with ``items`` and play from its first row (section 9.2, C5-49).

        ``items`` is a track list or an ``AppleMusicClient.resolve`` result. Staging: one full
        queue read before and after, per song the returned ``FirstTrackNumberEnqueued`` plus one
        1-row tail read; ``between_steps()`` runs after each insert (lock released), never inside
        the destructive step. The staging has a ``6 + 0.75·N`` s deadline (C5-37, revised 2026-09-27) ending in the
        existing rollback. Before ``Play`` a Sonos shuffle mode goes back to its unshuffled mode
        with repeat kept (C5-20), and the companion shuffle record is dropped. The result is the
        state plus ``_final_song_ids`` and ``_start = {k, n, u, name}``.
        """
        items, total, unavailable = self._tracks(items)
        if not isinstance(items, list) or not items or len(items) > self.MAX_QUEUE:
            raise SonosError("Choose a nonempty music item within the supported queue size.")
        songs = self._validate_items(items)
        step = between_steps or _noop
        changed = False
        saved = False
        staged = []
        original = None
        coordinator = None
        expected_revision = None
        phase = "preparing"
        try:
            with self._lock:
                context = self._assert_group(expected_group_revision)
                coordinator = context[1].coordinator
                original = self._queue(coordinator)
                if original.total + len(items) > self.MAX_QUEUE:
                    raise SonosError("There is not enough supported queue space to stage this item safely.")
                self._save_recovery(coordinator, original, expected_group_revision)
                saved = True
                plugin = self._share_link_factory(coordinator)
                expected_revision = original.revision
                base = original.total
                deadline = self._now() + self.STAGE_DEADLINE_BASE_S + self.STAGE_DEADLINE_PER_SONG_S * len(items)
                phase = "staging"
            for index, (item, song_id) in enumerate(zip(items, songs)):
                if self._now() > deadline:
                    raise StartTimeout("Playback took too long to prepare.")
                with self._lock:
                    changed = True  # An ambiguous network timeout may follow a successful enqueue.
                    want = base + index + 1
                    try:
                        inserted = plugin.add_share_link_to_queue(item["url"], position=0,
                                                                 dc_title=escape(item.get("title", "")),
                                                                 timeout=self.timeout)
                    except Exception:
                        inserted = None  # ambiguous: continue only if the new tail row holds the song
                    if inserted is not None and inserted != want:
                        raise QueueChanged("The staged Sonos queue could not be verified.")
                    if self.stage_tail_reads or inserted is None:
                        tail = coordinator.get_queue(start=base + index, max_items=1)
                        if int(tail.total_matches) != want or len(tail) != 1 or _song_id(tail[0]) != song_id:
                            raise QueueChanged("The staged Sonos queue could not be verified.")
                        expected_revision = str(tail.update_id) if self.stage_tail_reads else None
                    else:
                        expected_revision = None  # W5 fallback: the whole tail is verified below
                    staged.append(song_id)
                step()
            with self._lock:
                self._assert_group(expected_group_revision)
                verified = self._queue(coordinator)
                if ((expected_revision is not None and verified.revision != expected_revision)
                        or verified.total != base + len(songs) or
                        [_signature(x) for x in verified.items[:base]] != [_signature(x) for x in original.items] or
                        [_song_id(x) for x in verified.items[base:]] != songs):
                    raise QueueChanged("Another controller changed the queue before replacement.")
                phase = "replacing"
                # The device's UpdateID guards the destructive range removal. We
                # never fall back to clearing the queue or removing unguarded IDs.
                self._remove_range(coordinator, 0, original.total, verified.revision)
                final = self._queue(coordinator)
                if final.total != len(songs) or [_song_id(x) for x in final.items] != songs:
                    raise QueueChanged("The replacement queue could not be verified.")
                self._assert_group(expected_group_revision)
                phase = "starting"
                self._unshuffle(coordinator)
                # SoCo.play_from_queue() can call get_speaker_info() without a
                # timeout. Use the same documented actions with explicit bounds.
                coordinator.avTransport.SetAVTransportURI(
                    [("InstanceID", 0), ("CurrentURI", f"x-rincon-queue:{coordinator.uid}#0"),
                     ("CurrentURIMetaData", "")], timeout=self.timeout)
                self._assert_group(expected_group_revision)
                coordinator.avTransport.Seek([("InstanceID", 0), ("Unit", "TRACK_NR"), ("Target", 1)], timeout=self.timeout)
                self._assert_group(expected_group_revision)
                coordinator.avTransport.Play([("InstanceID", 0), ("Speed", 1)], timeout=self.timeout)
                final_check = self._queue(coordinator)
                if final_check.revision != final.revision or [_song_id(x) for x in final_check.items] != songs:
                    raise QueueChanged("The queue changed while starting playback.")
                self._drop_shuffle_record()
                state = self._state(self._assert_group(expected_group_revision))
                state["_final_song_ids"] = list(songs)
                state["_start"] = {"k": len(songs), "n": total if total is not None else len(songs),
                                   "u": unavailable, "name": name}
                return state
        except Exception as error:
            if not changed:
                if isinstance(error, SonosError):
                    raise
                raise QueueReplacementFailed("Playback could not be prepared. The existing queue was not changed.", recovery_saved=saved) from None
            rolled_back = False
            # Only clean up a provably unchanged old queue + exactly our
            # known staged tail. Never overwrite somebody else's edits.
            # No group assertion here (section 9.2: "inserts made to a coordinator that left the
            # group are then rolled back"): a group change is the usual reason to be here, and the
            # prefix signatures, the staged tail and the UpdateID below already prove that these
            # rows on this coordinator are ours.
            if phase == "staging" and original is not None and coordinator is not None:
                with self._lock:
                    try:
                        actual = self._queue(coordinator)
                        prefix = [_signature(x) for x in actual.items[:original.total]]
                        tail = [_song_id(x) for x in actual.items[original.total:]]
                        permitted = songs[:len(staged)]
                        if (prefix == [_signature(x) for x in original.items] and
                                tail == permitted and len(tail) == len(staged) and
                                (expected_revision is None or actual.revision == expected_revision)):
                            self._remove_range(coordinator, original.total, len(tail), actual.revision)
                            restored = self._queue(coordinator)
                            rolled_back = [_signature(x) for x in restored.items] == [_signature(x) for x in original.items]
                    except Exception:
                        pass
            if rolled_back:
                message = "Playback failed while staging. Added tracks were removed; the original queue remains."
            else:
                message = "Playback was not completed. The queue may be partially changed; inspect Sonos before retrying. An encrypted recovery snapshot was retained."
            raise QueueReplacementFailed(message, recovery_saved=saved, partial=not rolled_back,
                                         timeout=isinstance(error, StartTimeout),
                                         group_changed=isinstance(error, GroupChanged)) from None

    def _unshuffle(self, coordinator):
        """C5-20: a start plays unshuffled (repeat kept). Best effort: it runs inside the destructive
        step, which runs to its result (section 1.1, C5-37), so nothing here may stop the start: a
        refused (e.g. UPnP 712) or failed ``SetPlayMode``, a failed mode read or an unconfirmed
        read-back is logged by status only and the start goes on to SetAVTransportURI, Seek and
        Play (the state then shows the mode)."""
        try:
            mode = coordinator.play_mode
            if mode not in SHUFFLE_MODES:
                return
            coordinator.avTransport.SetPlayMode([("InstanceID", 0), ("NewPlayMode", SHUFFLE_OFF[mode])],
                                                timeout=self.timeout)
            deadline = self._now() + READBACK_S
            while coordinator.play_mode != SHUFFLE_OFF[mode] and self._now() < deadline:
                self._sleep(READBACK_POLL_S)
        except Exception as error:
            code = _upnp_code(error)
            _log.warning("Start: the unshuffle before Play failed (%s); the start goes on",
                         f"UPnP {code}" if code is not None else type(error).__name__)

    # ------------------------------------------------------------------ Play next (section 9.3)
    def play_next(self, items, expected_group_revision: str, expected_track_id: str,
                  progress=None, between_steps=None) -> dict:
        """Insert ``items`` (≤ 100: the first 100 in order, C5-21) directly after the current
        song: ``AddURIToQueue`` with ``DesiredFirstTrackNumberEnqueued = P+1+i`` (0 = append when
        the current row is the last), never ``EnqueueAsNext``; one step per insert, then one
        slice read verifies the block. ``progress({"phase":"inserting","k","n"})`` after each
        verified insert, so ``k`` counts verified inserts and is never 0 here ([r2.2] C5-69/C5-71:
        the knob shows `Finding songs…` until k = 1, ``playnext_meta``). A group change is
        ``group_changed`` whatever the rollback did (``PlayNextFailed.group_changed``, section
        9.10). Any failed check after ≥ 1 insert rolls back exactly our rows when it
        can prove they are ours (``nothing_added``), else leaves them (``partial``). An insert
        Sonos accepted at a row other than P+1+i is queued, so it counts: it is rolled back with
        the block when provably ours, else the result is ``partial``; so is an ambiguous insert
        (no reply) after which the queue grew without our song at P+1+i.
        Result: the state plus ``_inserted = {"start_row": P+1, "song_ids": [...]}``.
        """
        items, _total, _unavailable = self._tracks(items)
        if not isinstance(items, list) or not items:
            raise SonosError("Choose a nonempty music item to play next.")
        items = items[:PLAY_NEXT_MAX]
        songs = self._validate_items(items)
        report = progress or _noop
        step = between_steps or _noop
        count = len(items)
        inserted = 0
        stray = None   # insert ``inserted`` queued at another row: that row, or 0 when unknown
        coordinator = plugin = None
        position = base = anchor = revision_before = None
        try:
            with self._lock:
                context = self._assert_group(expected_group_revision)
                coordinator = context[1].coordinator
                self._gate_queue(coordinator)
                track = coordinator.get_current_track_info()
                if self._track_id(track) != expected_track_id:
                    raise TrackChanged("The playing track changed. Review Play next and try again.")
                head = coordinator.get_queue(start=0, max_items=1)
                base, revision_before = int(head.total_matches), str(head.update_id)
                position = self._position(track)
                if base == 0 or not 1 <= position <= base:
                    raise NothingPlaying("Nothing is playing from the Sonos queue.")
                if base + count > self.MAX_QUEUE:
                    raise QueueFull("The Sonos queue is full.")
                current = coordinator.get_queue(start=position - 1, max_items=1)
                if len(current) != 1:
                    raise QueueChanged("The queue changed. Nothing was queued.")
                anchor = _signature(current[0])
                if self._track_id(coordinator.get_current_track_info()) != expected_track_id:
                    raise TrackChanged("The playing track changed. Review Play next and try again.")
                plugin = self._share_link_factory(coordinator)
            for index, item in enumerate(items):
                with self._lock:
                    want = position + 1 + index
                    desired = want if want <= base + index else 0  # the current row is the last row → append
                    try:
                        got = plugin.add_share_link_to_queue(item["url"], position=desired, as_next=False,
                                                             dc_title=escape(item.get("title", "")),
                                                             timeout=self.timeout)
                    except Exception:
                        got = None
                    if got != want:
                        if isinstance(got, int) and not isinstance(got, bool) and got > 0:
                            stray = got   # Sonos accepted it at another row: queued there, ours
                            raise _InsertFailed()
                        # Ambiguous (no reply): continue only if the row P+1+i holds the song and
                        # the queue grew by exactly one row.
                        row = coordinator.get_queue(start=want - 1, max_items=1)
                        total = int(row.total_matches)
                        if not (len(row) == 1 and _song_id(row[0]) == songs[index] and total == base + index + 1):
                            if total != base + index:
                                stray = 0   # the queue changed size: the song may be queued elsewhere
                            raise _InsertFailed()
                    inserted = index + 1
                report({"phase": "inserting", "k": inserted, "n": count})
                step()
            with self._lock:
                block = self._slice(coordinator, position - 1, count + 2)
                if (block.total != base + count or not block.items or _signature(block.items[0]) != anchor
                        or [_song_id(x) for x in block.items[1:1 + count]] != songs
                        or block.revision == revision_before):
                    raise _InsertFailed()
                now = self._position(coordinator.get_current_track_info())
                if now > position + count:
                    raise _SongEnded()
                if not (now == position or position + 1 <= now <= position + count):
                    raise _InsertFailed()
                state = self._state(self._assert_group(expected_group_revision))
                state["_inserted"] = {"start_row": position + 1, "song_ids": list(songs)}
                return state
        except _SongEnded:
            rolled = self._rollback_block(coordinator, position, inserted, songs, anchor)
            raise SongChanged("The song changed before Play next finished.", inserted=inserted,
                              rolled_back=rolled) from None
        except (_InsertFailed, QueueChanged):
            if not inserted and stray is None:
                raise PlayNextFailed("Sonos did not queue the item. Nothing was added.",
                                     outcome="nothing_added") from None
            rolled = self._rollback_block(coordinator, position, inserted, songs, anchor, stray)
            raise PlayNextFailed("Play next could not be verified." if rolled else
                                 "Play next was only partly verified. Inspect the Sonos queue.",
                                 outcome="nothing_added" if rolled else "partial",
                                 inserted=inserted + (1 if stray else 0), rolled_back=rolled) from None
        except SonosError as error:
            if inserted:
                rolled = self._rollback_block(coordinator, position, inserted, songs, anchor)
                if not rolled:
                    raise PlayNextFailed("Play next was only partly verified. Inspect the Sonos queue.",
                                         outcome="partial", inserted=inserted,
                                         group_changed=isinstance(error, GroupChanged)) from None
            raise
        except Exception:
            if inserted:
                rolled = self._rollback_block(coordinator, position, inserted, songs, anchor)
                raise PlayNextFailed("Play next was interrupted." if rolled else
                                     "Play next was only partly verified. Inspect the Sonos queue.",
                                     outcome="nothing_added" if rolled else "partial",
                                     inserted=inserted, rolled_back=rolled) from None
            raise SonosUnavailable("Sonos is unavailable. Nothing was queued.") from None

    def _rollback_block(self, coordinator, position, count, songs, anchor, stray=None) -> bool:
        """Remove this call's rows when they are provably ours; True only when nothing of ours is
        left (``nothing_added``), else False (``partial``: what is not proven stays).

        Rows P+1..P+k (the k verified inserts) go only when they are exactly this call's k songs,
        the anchor (the row P) is intact and the playing row is not inside the block (A06 section
        1.5). ``stray`` is the row Sonos reported for insert k+1 when it was not P+k+1 (the song is
        queued there): inside the block (P < stray ≤ P+k) the block is rows P+1..P+k+1 in the
        order that insert made; after it, a one-row read of the stray row under the block read's
        UpdateID must show the song (and not be playing), and that row goes first, so the block
        keeps its row numbers; at or before P it is never touched. ``stray == 0``: the song may be
        queued at an unknown row, so the block is still cleaned but the result is False."""
        if coordinator is None:
            return not count and stray is None
        known = isinstance(stray, int) and not isinstance(stray, bool) and stray > 0
        with self._lock:
            try:
                if known and position < stray <= position + count:
                    block = list(songs[:count])
                    block.insert(stray - position - 1, songs[count])
                    return self._remove_block(coordinator, position, anchor, block)
                if known and stray > position + count:
                    fresh = self._slice(coordinator, position - 1, count + 1)
                    row = coordinator.get_queue(start=stray - 1, max_items=1)
                    now = self._position(coordinator.get_current_track_info())
                    if not (len(fresh.items) == count + 1 and _signature(fresh.items[0]) == anchor
                            and [_song_id(x) for x in fresh.items[1:]] == songs[:count]
                            and len(row) == 1 and _song_id(row[0]) == songs[count]
                            and str(row.update_id) == fresh.revision
                            and now != stray and not position + 1 <= now <= position + count):
                        return False
                    self._remove_range(coordinator, stray - 1, 1, fresh.revision)
                    return self._remove_block(coordinator, position, anchor, songs[:count])
                cleaned = self._remove_block(coordinator, position, anchor, songs[:count])
                return cleaned and stray is None
            except Exception:
                return False

    def _remove_block(self, coordinator, position, anchor, expected) -> bool:
        """Remove rows P+1..P+len(expected) when a fresh read shows exactly ``expected`` (song ids)
        there, the anchor at P and the playing row outside them; the UpdateID of that read guards
        the removal. Caller holds the lock."""
        count = len(expected)
        if not count:
            return True
        fresh = self._slice(coordinator, position - 1, count + 1)
        now = self._position(coordinator.get_current_track_info())
        if (len(fresh.items) == count + 1 and _signature(fresh.items[0]) == anchor
                and [_song_id(x) for x in fresh.items[1:]] == list(expected)
                and not position + 1 <= now <= position + count):
            self._remove_range(coordinator, position, count, fresh.revision)
            return True
        return False

    # ------------------------------------------------------------------ Seek (section 9.4)
    def seek(self, seconds, expected_group_revision: str, expected_track_id: str, between_steps=None) -> dict:
        """Seek the current track to ``seconds`` (clamped to ``[0, D − 3]``), sent **once**.

        Landed ([r2.2] C5-68) = playback resumed: the first ``PLAYING`` / ``PAUSED_PLAYBACK``
        read after a ``TRANSITIONING`` read, or taken ≥ 1.0 s after the reply when the speaker
        never reported ``TRANSITIONING``, within 8 s (``seek_confirm_ms``); else
        ``SeekNotConfirmed``. The position is not a condition (rev 4's ±2 s is withdrawn): a
        landing more than 2 s off is only logged. ``STOPPED`` or any other state keeps polling.
        100 ms polls, each its own step: ``between_steps()`` runs between them with the lock
        released. A track change within 6 s of the end is the song ending (ok); otherwise
        ``TrackChanged``. Result: the state plus ``_applied_seek`` (the target) and
        ``_seek_kept_state``. The controller's one follow-up jump ([r2.2] C5-68: the latest target,
        sent after this one lands) is simply the next call with the same expected ids (a seek never
        changes the track id); the adapter never queues, repeats or resends a target.
        """
        step = between_steps or _noop
        try:
            with self._lock:
                context = self._assert_group(expected_group_revision)
                coordinator = context[1].coordinator
                track = coordinator.get_current_track_info()
                if self._track_id(track) != expected_track_id:
                    raise TrackChanged("The playing track changed.")
                duration = _secs(track.get("duration", ""))
                if not duration:
                    raise SeekUnavailable("This track has no known length.")
                if "SeekTime" not in _actions(coordinator.available_actions):
                    raise SeekUnavailable("This source cannot seek.")
                before = coordinator.get_current_transport_info().get("current_transport_state")
                if before not in ("PLAYING", "PAUSED_PLAYBACK"):
                    raise SeekUnavailable("Nothing is playing.")
                target = max(0, min(int(seconds), max(0, duration - SEEK_MARGIN_S)))
                self._assert_group(expected_group_revision)
                if self._track_id(coordinator.get_current_track_info()) != expected_track_id:
                    raise TrackChanged("The playing track changed.")
                try:
                    coordinator.avTransport.Seek([("InstanceID", 0), ("Unit", "REL_TIME"),
                                                  ("Target", _hms(target))], timeout=self.timeout)
                except Exception as error:
                    code = _upnp_code(error)
                    if code in (701, 710, 711):
                        raise SeekNotConfirmed("Sonos refused the seek.") from None
                    raise SonosUnavailable("Sonos is unavailable.") from None
            sent = self._now()
            seen_transitioning = False
            last_group_check = sent
            for now in self._confirmation_polls(sent, step):
                with self._lock:
                    if now - last_group_check >= SEEK_GROUP_CHECK_S:
                        context = self._assert_group(expected_group_revision)
                        last_group_check = self._now()
                    polled = coordinator.get_current_track_info()
                    if self._track_id(polled) != expected_track_id:
                        if target >= duration - 2 * SEEK_MARGIN_S:
                            state = self._state(self._assert_group(expected_group_revision))
                            state["_applied_seek"] = target
                            state["_seek_song_ended"] = True
                            state["_seek_kept_state"] = False
                            return state
                        raise TrackChanged("The playing track changed.")
                    playback = coordinator.get_current_transport_info().get("current_transport_state")
                    if playback == "TRANSITIONING":
                        seen_transitioning = True  # RelTime already reads the target: not proof
                    elif playback in SEEK_LANDED and (seen_transitioning
                                                      or self._now() - sent >= SEEK_NO_TRANSITION_S):
                        reached = _secs(polled.get("position", ""))
                        if reached is None or abs(reached - target) > SEEK_OFF_TARGET_S:
                            # [r2.2] diagnostic only; numbers, never a title
                            _log.debug("Seek landed %s s off target",
                                       "unknown" if reached is None else reached - target)
                        state = self._state(self._assert_group(expected_group_revision))
                        state["_applied_seek"] = target
                        state["_seek_kept_state"] = playback == before
                        return state
            raise SeekNotConfirmed("The seek was not confirmed.")
        except SonosError:
            raise
        except Exception:
            raise SonosUnavailable("Sonos is unavailable.") from None

    def _confirmation_polls(self, sent: float, step):
        """The confirmation polls of a Seek (section 9.4) or a jump (section 9.6.2): one every
        100 ms from ``sent`` (the Seek reply) up to ``sent`` + 8 s (``seek_confirm_ms``), each its
        own step (section 1.1): ``step()`` (``between_steps``) runs before each with the adapter
        lock released, and the caller takes the lock for that poll's reads. Yields each poll's
        time; the poll at the deadline is the last (no zero-delay re-polls)."""
        deadline = sent + SEEK_CONFIRM_S
        due = sent + SEEK_POLL_S
        while True:
            step()
            now = self._now()
            if now < due:
                self._sleep(min(due, deadline) - now)
            now = self._now()
            if now > deadline + 1e-9:
                return
            yield now
            if self._now() >= deadline - 1e-9:
                return
            due = max(due + SEEK_POLL_S, self._now())

    # ------------------------------------------------------------------ queue reads and moves (section 9.6)
    def _row(self, item, row: int, host: str) -> dict:
        song = _song_id(item)
        resources = getattr(item, "resources", []) or []
        duration = _secs(getattr(resources[0], "duration", "") if resources else "")
        return {"row": row, "title": getattr(item, "title", "") or "",
                "artist": getattr(item, "creator", "") or "", "album": getattr(item, "album", "") or "",
                "sonos_art": sonos_artwork_url(getattr(item, "album_art_uri", "") or "", host),
                "song_id": song, "duration_s": duration or None, "signature": row_signature(item),
                "service": "apple" if song else "other"}

    def queue_window(self, start: int, count: int, expected_group_revision: str | None = None) -> dict:
        """``Browse(Q:0)`` rows start+1..start+count (0-based ``start``, ``count`` ≤ ``QUEUE_PAGE_ROWS``
        = 100) → ``{"start", "rows", "update_id", "total"}``; read-only. One Browse: its envelope
        parse held the GIL 0.26-0.49 ms at p50 and 0.28-0.54 ms at p95 for 100 rows on the H5 bench
        (gil-parse-hold.md section 2.2), within K3 section 1.2's 1 ms, so it runs at once, during an
        animation episode too."""
        if (isinstance(start, bool) or isinstance(count, bool) or not isinstance(start, int)
                or not isinstance(count, int) or start < 0 or not 1 <= count <= QUEUE_PAGE_ROWS):
            raise SonosError("Choose a queue window of at most 100 rows.")
        with self._lock:
            try:
                context = self._assert_group(expected_group_revision) if expected_group_revision else self._context()
                coordinator = context[1].coordinator
                page = coordinator.get_queue(start=start, max_items=count)
                return {"start": start,
                        "rows": [self._row(item, start + index + 1, coordinator.ip_address)
                                 for index, item in enumerate(page)],
                        "update_id": str(page.update_id), "total": int(page.total_matches)}
            except SonosError:
                raise
            except Exception:
                raise SonosUnavailable("Sonos is unavailable.") from None

    def jump(self, row: int, expected_group_revision: str, expected_track_id: str,
             expected_update_id, *, name=None, between_steps=None) -> dict:
        """Up next Play (section 9.6.2): group, track and ``UpdateID`` guards, ``Seek(TRACK_NR,
        row)``, then ``Play`` if not PLAYING. Result: the state plus ``_start`` for the row;
        unconfirmed → ``SonosError`` (``start_failed``).

        [WP6-r22] Confirmed by the seek rule ([r2.2] C5-68), not a 2 s read-back: a jump buffers a
        new stream, and live check W2 saw a seek stay TRANSITIONING for 2.64-2.69 s. Played = the
        first ``PLAYING`` read at ``row`` after a ``TRANSITIONING`` read, or taken ≥ 1.0 s after
        the Seek reply when the speaker never reported TRANSITIONING, within 8 s
        (``seek_confirm_ms``). Any other read keeps polling. The polls are ``seek``'s: 100 ms
        apart, each its own step, with ``between_steps()`` run between them with the lock
        released, so a short job waits at most one poll. The group is checked every 0.5 s and
        before the result."""
        step = between_steps or _noop
        try:
            with self._lock:
                context = self._assert_group(expected_group_revision)
                coordinator = context[1].coordinator
                if self._track_id(coordinator.get_current_track_info()) != expected_track_id:
                    raise TrackChanged("The playing track changed.")
                self._gate_queue(coordinator, shuffle_ok=True)
                head = coordinator.get_queue(start=0, max_items=1)
                if str(head.update_id) != str(expected_update_id):
                    raise QueueChanged("The queue changed.")
                if isinstance(row, bool) or not isinstance(row, int) or not 1 <= row <= int(head.total_matches):
                    raise QueueChanged("The queue changed.")
                self._assert_group(expected_group_revision)
                coordinator.avTransport.Seek([("InstanceID", 0), ("Unit", "TRACK_NR"), ("Target", row)],
                                             timeout=self.timeout)
                sent = self._now()
                playback = coordinator.get_current_transport_info().get("current_transport_state")
                seen_transitioning = playback == "TRANSITIONING"
                if playback != "PLAYING":
                    coordinator.avTransport.Play([("InstanceID", 0), ("Speed", 1)], timeout=self.timeout)
            last_group_check = sent
            for now in self._confirmation_polls(sent, step):
                with self._lock:
                    if now - last_group_check >= SEEK_GROUP_CHECK_S:
                        self._assert_group(expected_group_revision)
                        last_group_check = self._now()
                    playback = coordinator.get_current_transport_info().get("current_transport_state")
                    if playback == "TRANSITIONING":
                        seen_transitioning = True
                    elif playback == "PLAYING" and (seen_transitioning
                                                    or self._now() - sent >= SEEK_NO_TRANSITION_S):
                        if self._position(coordinator.get_current_track_info()) == row:
                            state = self._state(self._assert_group(expected_group_revision))
                            state["_start"] = {"k": 1, "n": 1, "u": 0, "name": name, "row": row}
                            return state
            raise SonosError("Play was not confirmed.")
        except SonosError:
            raise
        except Exception:
            raise SonosUnavailable("Sonos is unavailable.") from None

    def move_next(self, row: int, expected_group_revision: str, expected_update_id, *, item=None) -> dict:
        """The Like fallback "Play next for this row" (section 9.6.3). An upcoming row (> P+1) moves
        to P+1 with ``ReorderTracksInQueue``; a played row (< P) is re-inserted at P+1 from its
        catalog share link (``item`` with ``url``, ``catalog_id``, ``title``; the result then
        carries ``_inserted`` for the ledger); rows P and P+1 need no change. Verified by a slice read."""
        with self._lock:
            try:
                context = self._assert_group(expected_group_revision)
                coordinator = context[1].coordinator
                self._gate_queue(coordinator)
                head = coordinator.get_queue(start=0, max_items=1)
                if expected_update_id is not None and str(head.update_id) != str(expected_update_id):
                    raise QueueChanged("The queue changed.")
                total = int(head.total_matches)
                position = self._position(coordinator.get_current_track_info())
                if not 1 <= position <= total:
                    raise NothingPlaying("Nothing is playing from the Sonos queue.")
                if isinstance(row, bool) or not isinstance(row, int) or not 1 <= row <= total:
                    raise QueueChanged("The queue changed.")
                if row in (position, position + 1):
                    return self._state(self._assert_group(expected_group_revision))
                if row > position + 1:
                    moved = coordinator.get_queue(start=row - 1, max_items=1)
                    if len(moved) != 1:
                        raise QueueChanged("The queue changed.")
                    signature = _signature(moved[0])
                    coordinator.avTransport.ReorderTracksInQueue(
                        [("InstanceID", 0), ("StartingIndex", row), ("NumberOfTracks", 1),
                         ("InsertBefore", position + 1), ("UpdateID", int(head.update_id))], timeout=self.timeout)
                    placed = coordinator.get_queue(start=position, max_items=1)
                    if len(placed) != 1 or _signature(placed[0]) != signature:
                        raise PlayNextFailed("The move could not be verified.", outcome="partial")
                    return self._state(self._assert_group(expected_group_revision))
                song, = self._validate_items([item or {}])
                played = coordinator.get_queue(start=row - 1, max_items=1)
                if len(played) != 1 or _song_id(played[0]) != song:
                    raise QueueChanged("The queue changed.")
                plugin = self._share_link_factory(coordinator)
                want = position + 1
                try:
                    got = plugin.add_share_link_to_queue(item["url"], position=want if want <= total else 0,
                                                         as_next=False, dc_title=escape(item.get("title", "")),
                                                         timeout=self.timeout)
                except Exception:
                    got = None
                placed = coordinator.get_queue(start=position, max_items=1)
                if not (len(placed) == 1 and _song_id(placed[0]) == song and int(placed.total_matches) == total + 1
                        and got in (want, None)):
                    if int(placed.total_matches) == total:
                        raise PlayNextFailed("Sonos did not queue the song.", outcome="nothing_added")
                    raise PlayNextFailed("The song could not be verified.", outcome="partial")
                state = self._state(self._assert_group(expected_group_revision))
                state["_inserted"] = {"start_row": want, "song_ids": [song]}
                return state
            except SonosError:
                raise
            except Exception:
                raise SonosUnavailable("Sonos is unavailable.") from None

    # ------------------------------------------------------------------ shuffle (section 9.5)
    def _shuffle_store(self):
        if self.shuffle_store is None:
            self.shuffle_store = CredentialStore(CredentialStore().path.with_name("shuffle-restore.bin"))
        return self.shuffle_store

    def load_shuffle_record(self) -> dict:
        """Read the companion-shuffle restore record once (store I/O; the runtime calls it on the
        audio lane at start). Afterwards ``read_state()["companion_shuffle"]`` reports it."""
        with self._lock:
            try:
                record = self._shuffle_store().load()
            except Exception:
                record = {}
            self._shuffle_record = record if isinstance(record, dict) else {}
            return dict(self._shuffle_record_for_room() or {})

    def _shuffle_record_for_room(self):
        record = self._shuffle_record
        if record and record.get("room_uid") == self.room_uid and isinstance(record.get("base_rows"), list):
            return record
        return None

    def _save_shuffle_record(self, record: dict) -> None:
        self._shuffle_store().save(record)
        self._shuffle_record = record
        self._shuffle_checked = None
        # A drop still pending from a failed write is superseded: this save overwrote the same
        # file, and retrying the drop would delete the record just made (DD-BUG-034 review).
        self._shuffle_drop_pending = False

    def _drop_shuffle_record(self) -> None:
        """Delete the restore record (a start replaced the queue, or it no longer attributes).
        Only a record already loaded is touched: a start never reads the store by itself (a record
        it did not load no longer attributes to the new queue, which invalidates it, section 9.5.5).
        DD-BUG-034: a failed store write removes the file instead, and failing that is retried by
        the next state read, so a dropped record never comes back at the next start."""
        if self._shuffle_record or self._shuffle_drop_pending:
            self._shuffle_record, self._shuffle_checked = {}, None
            try:
                self._shuffle_store().save({})
                self._shuffle_drop_pending = False
                return
            except Exception:
                pass
            try:
                path = getattr(self._shuffle_store(), "path", None)
                if path is not None:
                    Path(path).unlink(missing_ok=True)
                    self._shuffle_drop_pending = False
                    return
            except Exception:
                pass
            self._shuffle_drop_pending = True

    def _companion_shuffle_current(self, coordinator, update_id: str) -> bool:
        """``read_state()["companion_shuffle"]`` (DD-BUG-034): the record exists for this room and
        the queue is still the one it was made for. While no job of ours is moving rows, a queue
        UpdateID the record has not been checked at (neither the one the shuffle finished at nor the
        last one checked) reads the queue once; a record whose base rows are no longer all in the
        queue (replaced or cleared elsewhere) is dropped."""
        if self._shuffle_drop_pending:
            self._drop_shuffle_record()
        record = self._shuffle_record_for_room()
        if not record:
            return False
        if self._shuffle_job or update_id in (self._shuffle_checked, str(record.get("update_id_after"))):
            return True
        try:
            snapshot = self._queue(coordinator)
        except Exception:
            return True                      # unreadable now: judged at the next poll
        if snapshot.revision != update_id:
            return True                      # moved again while reading: judged at the next poll
        if _record_attributes(snapshot.items, record["base_rows"]):
            self._shuffle_checked = update_id
            return True
        self._drop_shuffle_record()
        return False

    def _realise(self, coordinator, position, total, model, remaining, step, expected_update_id):
        """Guarded single-row moves filling rows left to right from ``position + 1`` (section 9.5.2
        step 5, C5-50). ``model`` holds the row signatures 1..T and follows every move. Before each
        move the ``UpdateID`` and then the playing row are read; a song that ended freezes the rows
        up to the new playing row and the plan continues after it; a jump elsewhere stops the job.
        No row at or before the playing row ever moves. Returns (model, the last playing row).

        DD-BUG-035: ``expected_update_id`` is the queue version ``model`` describes (the snapshot's
        at the start). Each move compares the UpdateID it reads with it (another app's edit between
        steps raises ``QueueChanged`` before any move), and the UpdateID read right after its own
        Reorder, in the same locked step, becomes the next expected version."""
        k, current = position + 1, position
        expected = str(expected_update_id)
        while remaining:
            want = remaining[0]
            found = next((i + 1 for i in range(k - 1, len(model)) if model[i] == want), None)
            if found is None:
                raise QueueChanged("The queue changed while shuffling.")
            if found == k:
                remaining.pop(0)
                k += 1
                continue
            with self._lock:
                update_id = str(coordinator.get_queue(start=0, max_items=1).update_id)
                if update_id != expected:
                    raise QueueChanged("The queue changed while shuffling.")
                playing = self._position(coordinator.get_current_track_info())
                if playing < position or playing > total:
                    raise QueueChanged("Playback moved elsewhere while shuffling.")
                if playing >= k:
                    for index in range(k - 1, playing):
                        if model[index] in remaining:
                            remaining.remove(model[index])
                    k, current = playing + 1, playing
                    continue
                current = playing
                coordinator.avTransport.ReorderTracksInQueue(
                    [("InstanceID", 0), ("StartingIndex", found), ("NumberOfTracks", 1),
                     ("InsertBefore", k), ("UpdateID", int(update_id))], timeout=self.timeout)
                model.insert(k - 1, model.pop(found - 1))
                remaining.pop(0)
                k += 1
                expected = str(coordinator.get_queue(start=0, max_items=1).update_id)
            step()
        return model, current

    def _verify_order(self, coordinator, model, current) -> _QueueSnapshot:
        with self._lock:
            snapshot = self._queue(coordinator)
            if snapshot.total != len(model) or [_signature(x) for x in snapshot.items] != model:
                raise ShuffleFailed("The shuffled order could not be verified.")
            if self._position(coordinator.get_current_track_info()) not in (current, current + 1):
                raise ShuffleFailed("The shuffled order could not be verified.")
            return snapshot

    def shuffle_reorder(self, on: bool, expected_group_revision: str, expected_track_id: str, *,
                        plan=None, playnext_offsets=(), expected_rows=None, playnext_song_ids=(),
                        expected_update_id=None, progress=None, between_steps=None) -> dict:
        """The companion shuffle for ≤ 60 upcoming rows (section 9.5.2 / 9.5.3; C5-45, C5-50).

        **on**: ``plan`` is a permutation of the upcoming offsets 0..U-1 whose first entries are
        ``playnext_offsets`` (the Play-next block stays first); ``expected_rows`` the signature
        digests of rows P+1..T. The restore record (base rows only: digests and song ids, no
        titles) is persisted before ``progress({"phase":"accepted"})``; the moves follow.
        **off**: restores the recorded order behind the Play-next rows (``playnext_song_ids``:
        plain song ids, attributed record first as section 9.5.3 step 2 says; or
        ``[song_id, start_row]`` units from ``QueueLedger.playnext_units()`` (WP6-A1), attributed
        by the ledger's position rule so the result equals the controller's restore preview;
        ``_attribute_restore``); any foreign row drops the record (``QueueChanged``). Rows at or
        before the playing row never move. Result: the state.
        """
        report = progress or _noop
        step = between_steps or _noop
        self._shuffle_job = True
        try:
            if on:
                return self._shuffle_on(expected_group_revision, expected_track_id, plan, playnext_offsets,
                                        expected_rows, report, step)
            return self._shuffle_off(expected_group_revision, expected_track_id, playnext_song_ids, report, step)
        except SonosError:
            raise
        except Exception:
            raise SonosUnavailable("Sonos is unavailable.") from None
        finally:
            self._shuffle_job = False

    def _shuffle_on(self, revision, track_id, plan, playnext_offsets, expected_rows, report, step):
        with self._lock:
            context = self._assert_group(revision)
            coordinator = context[1].coordinator
            self._gate_queue(coordinator)
            if self._track_id(coordinator.get_current_track_info()) != track_id:
                raise TrackChanged("The playing track changed.")
            snapshot = self._queue(coordinator)
            total = snapshot.total
            position = self._position(coordinator.get_current_track_info())
            if not 1 <= position <= total:
                raise NothingPlaying("Nothing is playing from the Sonos queue.")
            upcoming = total - position
            pn = [int(v) for v in (playnext_offsets or ())]
            plan = [int(v) for v in (plan or ())]
            if (upcoming > COMPANION_SHUFFLE_MAX or upcoming - len(pn) < 2 or sorted(plan) != list(range(upcoming))
                    or plan[:len(pn)] != pn):
                raise ShuffleFailed("This queue cannot be shuffled here.")
            rows = snapshot.items[position:]
            if [row_signature(x) for x in rows] != list(expected_rows or []):
                raise QueueChanged("The queue changed. Nothing was shuffled.")
            skip = set(pn)
            record = {"room_uid": self.room_uid, "coordinator_uid": coordinator.uid,
                      "group_revision": revision, "created_at": time.time(),
                      "base_rows": [[row_signature(x), _song_id(x)] for offset, x in enumerate(rows)
                                    if offset not in skip],
                      "update_id_after": None}
            self._save_shuffle_record(record)
        report({"phase": "accepted"})
        model = [_signature(x) for x in snapshot.items]
        remaining = [_signature(rows[offset]) for offset in plan]
        model, current = self._realise(coordinator, position, total, model, remaining, step, snapshot.revision)
        final = self._verify_order(coordinator, model, current)
        with self._lock:
            record = dict(record, update_id_after=final.revision)
            self._save_shuffle_record(record)
            return self._state(self._assert_group(revision))

    def _shuffle_off(self, revision, track_id, playnext_song_ids, report, step):
        with self._lock:
            if self._shuffle_record is None:
                self.load_shuffle_record()
            record = self._shuffle_record_for_room()
            if not record:
                raise QueueChanged("There is no companion shuffle to undo.")
            context = self._assert_group(revision)
            coordinator = context[1].coordinator
            self._gate_queue(coordinator, shuffle_ok=True)
            if self._track_id(coordinator.get_current_track_info()) != track_id:
                raise TrackChanged("The playing track changed.")
            snapshot = self._queue(coordinator)
            total = snapshot.total
            position = self._position(coordinator.get_current_track_info())
            if not 1 <= position <= total:
                raise NothingPlaying("Nothing is playing from the Sonos queue.")
            pn_rows, base_rows = _attribute_restore(snapshot.items, position, record["base_rows"],
                                                    playnext_song_ids)
            if pn_rows is None:
                self._drop_shuffle_record()
                raise QueueChanged("The queue changed. The original order cannot be restored.")
        report({"phase": "accepted"})
        model = [_signature(x) for x in snapshot.items]
        remaining = pn_rows + [signature for _, signature in sorted(base_rows, key=lambda pair: pair[0])]
        model, current = self._realise(coordinator, position, total, model, remaining, step, snapshot.revision)
        self._verify_order(coordinator, model, current)
        with self._lock:
            self._drop_shuffle_record()
            return self._state(self._assert_group(revision))

    def set_shuffle(self, on: bool, expected_group_revision: str) -> dict:
        """Sonos native shuffle (section 9.5.4): ``SetPlayMode`` NORMAL↔SHUFFLE_NOREPEAT,
        REPEAT_ALL↔SHUFFLE, REPEAT_ONE↔SHUFFLE_REPEAT_ONE, read back ≤ 2 s at 50 ms; 712 → failed."""
        with self._lock:
            try:
                context = self._assert_group(expected_group_revision)
                coordinator = context[1].coordinator
                mode = coordinator.play_mode
                target = (SHUFFLE_ON if on else SHUFFLE_OFF).get(mode, mode)
                if target != mode:
                    try:
                        coordinator.avTransport.SetPlayMode([("InstanceID", 0), ("NewPlayMode", target)],
                                                            timeout=self.timeout)
                    except Exception as error:
                        if _upnp_code(error) == 712:
                            raise ShuffleFailed("Sonos refused the play mode.") from None
                        raise SonosUnavailable("Sonos is unavailable.") from None
                    deadline = self._now() + READBACK_S
                    while True:
                        context = self._assert_group(expected_group_revision)
                        if context[1].coordinator.play_mode == target:
                            break
                        remaining = deadline - self._now()
                        if remaining <= 0:
                            raise ShuffleFailed("The play mode was not confirmed.")
                        self._sleep(min(READBACK_POLL_S, remaining))
                return self._state(self._assert_group(expected_group_revision))
            except SonosError:
                raise
            except Exception:
                raise SonosUnavailable("Sonos is unavailable.") from None


class _InsertFailed(Exception):
    """Internal: a Play next check failed (rolled back or reported partial by ``play_next``)."""


class _SongEnded(Exception):
    """Internal: Play next found the playing row past the block (``song_changed``)."""
