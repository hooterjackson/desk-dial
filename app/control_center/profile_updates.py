"""Fetching updated app profiles from the public Desk Dial repo (plan section 5b; S1 lane DD-C).

Off by default. Settings > Apps has "Check for updates" (any time) and the opt-in
"Fetch updated profiles from the Desk Dial repo (once a day)" (settings.json ``profile_updates``:
``off`` | ``daily``, with ``profile_updates_last`` the time of the last finished check).

What one check does, and nothing more:

* One HTTPS GET of ``INDEX_URL`` (no query string, a plain ``User-Agent: DeskDial/<version>``, a
  timeout, certificate verification on, no redirects, at most ``INDEX_MAX`` bytes). Nothing about the
  user, the PC or the profiles in use is sent.
* The index (``tools/profiles/make_index.py`` writes it) lists, per profile,
  ``{id, file, sha256, bytes, desk_dial_min, overlay?: {file, sha256, bytes}}``, the paths relative to
  the repo's ``profiles/``. A profile that needs a newer Desk Dial is skipped.
* Each file that differs from the copy already in ``profiles_updates_dir()`` (or, with no copy there,
  from the bundled one) is downloaded from ``BASE_URL`` + its path, checked against its declared size,
  the 128 KB cap and its SHA-256, validated with ``app_profiles.load_pair`` (Karl file and sidecar
  together, as the Library will read them), and only then switched in, each file with ``os.replace``.
* On any failure the previous good file stays. ``profiles\\user\\`` (imports) is never written; the
  updates folder is the only one this module writes.

``run_check`` is the whole check (blocking, for a worker thread). ``ProfileUpdater`` runs it off the Tk
thread and hands the ``CheckResult`` back to the Tk tick (``poll``). Tests pass a fake ``opener``;
nothing here touches the network on import.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import queue
import re
import shutil
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import app_profiles

_log = logging.getLogger(__name__)

# The public repo keeps Desk Dial under app/ (the Action commits app/profiles/karl/*.json and app/profiles/index.json).
REPO_RAW = "https://raw.githubusercontent.com/hooterjackson/desk-dial/main/app/profiles/"
INDEX_URL = REPO_RAW + "index.json"
BASE_URL = REPO_RAW
INDEX_MAX = 64 * 1024
FILE_MAX = app_profiles.FILE_MAX          # 128 KB, the validator's own cap
TIMEOUT_S = 15.0
DAY_S = 24 * 60 * 60
SETTINGS = ("off", "daily")
DEFAULT_SETTING = "off"
INDEX_FORMAT = 1
INDEX_PROFILES_MAX = 64

_FILE = re.compile(r"(karl/)?[a-z0-9_-]{1,11}(\.windows)?\.json")
_SHA = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"\d{1,5}(\.\d{1,5}){0,3}")

# Settings > Apps copy (plain words; the README session lists them).
TEXT_CHECKING = "Checking for updated profiles…"
TEXT_UP_TO_DATE = "Profiles are up to date."
TEXT_UPDATED = "Updated: {names}."
TEXT_OFFLINE = "Couldn't reach the Desk Dial repo. Your profiles haven't changed."
TEXT_BAD_INDEX = "The profile list from the Desk Dial repo wasn't usable. Your profiles haven't changed."
TEXT_KEPT = "{name}: {reason}. Kept the current version."
TEXT_TOO_NEW = "{name}: needs Desk Dial {version} or later."
REASON_SIZE = "the download was too big"
REASON_SHORT = "the download was incomplete"
REASON_HASH = "the download didn't match its checksum"
REASON_INVALID = "the new file didn't pass the profile checks"
REASON_OFFLINE = "the download failed"
REASON_WRITE = "it couldn't be saved"


class UpdateError(Exception):
    """One failed step, with a plain-words reason (never a URL or a path)."""

    def __init__(self, reason, offline=False):
        super().__init__(reason)
        self.reason, self.offline = reason, offline


@dataclass
class CheckResult:
    ok: bool = True                      # the index was read (offline / a bad index: False)
    offline: bool = False
    updated: list = field(default_factory=list)      # names switched in
    kept: list = field(default_factory=list)         # plain-words lines, one per profile not updated
    finished: float = 0.0                # time.time() when the check ended

    @property
    def text(self):
        """One short status for Settings > Apps."""
        if self.offline:
            return TEXT_OFFLINE
        if not self.ok:
            return TEXT_BAD_INDEX
        lines = [TEXT_UPDATED.format(names=", ".join(self.updated)) if self.updated else
                 (TEXT_UP_TO_DATE if not self.kept else "")]
        lines.extend(self.kept)
        return " ".join(line for line in lines if line)


# ---------------------------------------------------------------------------------------------- policy
def normal_setting(value):
    return value if value in SETTINGS else DEFAULT_SETTING


def normal_last(value):
    """settings.json ``profile_updates_last``: a finite time >= 0, else 0."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return 0
    return value


def due(setting, last, now):
    """True when the daily check should run: only with ``daily``, a day after the last one (or when the
    clock went backwards past it)."""
    if normal_setting(setting) != "daily":
        return False
    last = normal_last(last)
    return last == 0 or now - last >= DAY_S or now < last


# ---------------------------------------------------------------------------------------------- versions
def version_tuple(text):
    if not isinstance(text, str) or not _VERSION.fullmatch(text.strip()):
        return None
    parts = [int(p) for p in text.strip().split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def version_ok(minimum, current):
    """Is ``current`` (Desk Dial's public version) at least ``minimum``? An unknown current version
    (a source checkout without desktop-version.txt) is treated as new enough."""
    need = version_tuple(minimum)
    if need is None:
        return False
    have = version_tuple(current) if current else None
    return have is None or have >= need


# ---------------------------------------------------------------------------------------------- HTTP
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):      # noqa: D401 (urllib's API)
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def default_opener():
    """urllib with certificate and host-name verification (the default context), no redirects, no proxy
    credentials of ours and no cookies."""
    context = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirect())


def user_agent(version):
    version = version if isinstance(version, str) and re.fullmatch(r"[0-9A-Za-z.+-]{1,40}", version) else "0"
    return f"DeskDial/{version}"


def fetch(url, cap, opener, version, timeout=TIMEOUT_S):
    """GET ``url`` (HTTPS only, no query) and return at most ``cap`` bytes; UpdateError otherwise."""
    if not url.startswith("https://") or "?" in url or "#" in url:
        raise UpdateError(REASON_OFFLINE)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent(version)}, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise UpdateError(REASON_OFFLINE, offline=True)
            length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
            if length is not None and length.strip().isdigit() and int(length) > cap:
                raise UpdateError(REASON_SIZE)
            data = response.read(cap + 1)
    except UpdateError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _log.info("Profile update fetch failed (%s)", type(exc).__name__)      # never the URL
        raise UpdateError(REASON_OFFLINE, offline=True) from None
    if len(data) > cap:
        raise UpdateError(REASON_SIZE)
    return data


# ---------------------------------------------------------------------------------------------- the index
def parse_index(data):
    """The index bytes -> a list of entries (dicts), or UpdateError for anything malformed."""
    try:
        doc = app_profiles.read_json(data, "index.json")
    except app_profiles.ProfileError:
        raise UpdateError("bad index") from None
    if doc.get("format") != INDEX_FORMAT or not isinstance(doc.get("profiles"), list):
        raise UpdateError("bad index")
    entries = doc["profiles"]
    if len(entries) > INDEX_PROFILES_MAX:
        raise UpdateError("bad index")
    seen, out = set(), []
    for entry in entries:
        if not isinstance(entry, dict):
            raise UpdateError("bad index")
        pid = entry.get("id")
        if not app_profiles.valid_id(pid) or pid in seen:                   # DD-7: never a device name
            raise UpdateError("bad index")
        seen.add(pid)
        _check_file(entry, pid, overlay=False)
        if not isinstance(entry.get("desk_dial_min"), str) or version_tuple(entry["desk_dial_min"]) is None:
            raise UpdateError("bad index")
        overlay = entry.get("overlay")
        if overlay is not None:
            if not isinstance(overlay, dict):
                raise UpdateError("bad index")
            _check_file(overlay, pid, overlay=True)
        out.append(entry)
    return out


def _check_file(entry, pid, overlay):
    name = entry.get("file")
    if not isinstance(name, str) or not _FILE.fullmatch(name):
        raise UpdateError("bad index")
    stem = name.rsplit("/", 1)[-1]
    if stem != (f"{pid}.windows.json" if overlay else f"{pid}.json"):
        raise UpdateError("bad index")
    if not isinstance(entry.get("sha256"), str) or not _SHA.fullmatch(entry["sha256"]):
        raise UpdateError("bad index")
    size = entry.get("bytes")
    if type(size) is not int or not 0 < size <= FILE_MAX:
        raise UpdateError("bad index")


# ---------------------------------------------------------------------------------------------- the check
def _sha_of(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _current(updates_dir, bundled_dir, name):
    """SHA-256 of the copy Desk Dial has now: the updates folder's, else the bundled one's."""
    leaf = name.rsplit("/", 1)[-1]
    here = _sha_of(updates_dir / leaf)
    if here is not None:
        return here
    if bundled_dir is not None:
        return _sha_of(Path(bundled_dir) / name)
    return None


def _download(entry, opener, version):
    data = fetch(BASE_URL + entry["file"], FILE_MAX, opener, version)
    if len(data) < entry["bytes"]:
        raise UpdateError(REASON_SHORT)
    if len(data) > entry["bytes"]:
        raise UpdateError(REASON_SIZE)
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise UpdateError(REASON_HASH)
    return data


def _write_new(path, data):
    """A fully written, fsynced temporary file next to ``path`` (not yet switched in)."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".new", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        _unlink(tmp)
        raise
    return Path(tmp)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _update_one(entry, updates_dir, bundled_dir, opener, version):
    """Download, check and switch in one profile. Returns its name when something changed, None when it
    was already current. UpdateError keeps the previous good files."""
    pid = entry["id"]
    karl_name, overlay = entry["file"], entry.get("overlay")
    karl_changed = _current(updates_dir, bundled_dir, karl_name) != entry["sha256"]
    overlay_changed = overlay is not None and _current(updates_dir, bundled_dir, overlay["file"]) != overlay["sha256"]
    if not karl_changed and not overlay_changed:
        return None
    karl_data = _download(entry, opener, version) if karl_changed else None
    overlay_data = _download(overlay, opener, version) if overlay_changed else None
    # Validate the pair exactly as the Library will read it, in a private staging folder.
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(updates_dir)))
    try:
        karl_path = staging / f"{pid}.json"
        if karl_data is not None:
            karl_path.write_bytes(karl_data)
        else:
            source = updates_dir / f"{pid}.json"
            if not source.is_file() and bundled_dir is not None:
                source = Path(bundled_dir) / karl_name
            shutil.copyfile(source, karl_path)
        overlay_path = None
        if overlay is not None:
            overlay_path = staging / f"{pid}.windows.json"
            if overlay_data is not None:
                overlay_path.write_bytes(overlay_data)
            else:
                source = updates_dir / f"{pid}.windows.json"
                if not source.is_file() and bundled_dir is not None:
                    source = Path(bundled_dir) / overlay["file"]
                shutil.copyfile(source, overlay_path)
        try:
            profile = app_profiles.load_pair(karl_path, overlay_path, source="updates")
        except app_profiles.ProfileError as exc:
            _log.warning("Updated profile %s refused: %s", pid, "; ".join(exc.problems[:3]))
            raise UpdateError(REASON_INVALID) from None
        if profile.id != pid:
            raise UpdateError(REASON_INVALID)
        name = profile.name
    except OSError:
        raise UpdateError(REASON_WRITE) from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # Switch in: both files written in full first, then each replaced atomically. The sidecar goes
    # first, so a crash between the two leaves a pair the Library can still read (it falls back to a
    # sidecar that fits).
    pending = []
    try:
        if overlay_data is not None:
            pending.append((_write_new(updates_dir / f"{pid}.windows.json", overlay_data),
                            updates_dir / f"{pid}.windows.json"))
        if karl_data is not None:
            pending.append((_write_new(updates_dir / f"{pid}.json", karl_data), updates_dir / f"{pid}.json"))
        for tmp, final in pending:
            os.replace(tmp, final)
    except OSError:
        raise UpdateError(REASON_WRITE) from None
    finally:
        for tmp, _final in pending:
            if tmp.exists():
                _unlink(tmp)
    return name


def run_check(updates_dir, bundled_dir=None, version=None, opener=None, user_dir=None, names=None, clock=time.time):
    """One whole check (blocking: run it off the Tk thread). Never raises; never writes outside
    ``updates_dir``, and refuses to run when ``updates_dir`` is (or is inside) ``user_dir``. ``names``
    ({id: name}) words the messages about profiles that weren't updated."""
    result = CheckResult()
    updates_dir = Path(updates_dir)
    try:
        if user_dir is not None:
            user = Path(user_dir).resolve()
            target = updates_dir.resolve()
            if target == user or user in target.parents:
                raise UpdateError("bad target")
        opener = opener if opener is not None else default_opener()
        try:
            entries = parse_index(fetch(INDEX_URL, INDEX_MAX, opener, version))
        except UpdateError as exc:
            result.ok, result.offline = False, exc.offline
            return result
        updates_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            label = (names or {}).get(entry["id"]) or entry["id"]
            if not version_ok(entry["desk_dial_min"], version):
                result.kept.append(TEXT_TOO_NEW.format(name=label, version=entry["desk_dial_min"]))
                continue
            try:
                name = _update_one(entry, updates_dir, bundled_dir, opener, version)
            except UpdateError as exc:
                if exc.offline:
                    result.offline = True
                    result.ok = False
                    return result
                result.kept.append(TEXT_KEPT.format(name=label, reason=exc.reason))
                continue
            if name is not None:
                result.updated.append(name)
    except Exception as exc:          # a worker never dies with an exception
        _log.warning("Profile update check failed (%s)", type(exc).__name__)
        result.ok = False
    finally:
        result.finished = clock()
    return result


class ProfileUpdater:
    """Runs ``run_check`` on a worker thread; the Tk tick collects the result with ``poll``."""

    def __init__(self, updates_dir, bundled_dir=None, version=None, user_dir=None, opener=None, runner=run_check):
        self.updates_dir, self.bundled_dir, self.version = updates_dir, bundled_dir, version
        self.user_dir, self.opener, self.runner = user_dir, opener, runner
        self.names = {}                  # {id: name} for the messages (set on the Tk thread before start)
        self._results = queue.Queue()
        self._thread = None
        self.last = None                 # the last CheckResult

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Start one check unless one is running. True when started."""
        if self.busy:
            return False
        names = dict(self.names)

        def work():
            try:
                result = self.runner(self.updates_dir, self.bundled_dir, self.version, self.opener, self.user_dir, names)
            except Exception:                    # run_check never raises; a stand-in might
                result = CheckResult(ok=False, finished=time.time())
            self._results.put(result)
        self._thread = threading.Thread(target=work, name="deskdial-profile-updates", daemon=True)
        self._thread.start()
        return True

    def poll(self):
        """The finished CheckResult (once), or None."""
        try:
            result = self._results.get_nowait()
        except queue.Empty:
            return None
        self.last = result
        return result
