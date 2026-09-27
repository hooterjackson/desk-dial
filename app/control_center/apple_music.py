"""Apple Music library browsing, exact library-track resolution and the one Like write.

Library albums/playlists are expanded through their *library* tracks relationship.
Every individual track must map to one catalog song before anything is returned to
the Sonos adapter. No title search or whole-catalog-album substitution is used.

Reads are GETs. The one write (CONTROL_CENTER_V5.md section 9.8.2, C5-62) is
``POST /v1/me/favorites?ids[songs]=<id>`` (Like). Like is add-only, for good ([r2.2]
C5-67: Apple refused the favourites ``DELETE`` for our sign-in, HTTP 400 / 40012): no
unlike request of any kind exists, and ``_send`` refuses every other write before any
I/O, so no code path can send a ``DELETE``, ``PUT`` a rating or send a body (and never
the rating value -1). The heart state has one source, ``GET /v1/me/ratings/songs?ids=``
(C5-64).
"""
from __future__ import annotations

from collections import OrderedDict
import logging
import re
import threading
import time
from copy import deepcopy
from urllib.parse import quote, urlencode, urlsplit, parse_qs, urlunsplit

from .credentials import developer_token, CredentialError
from .artwork import ACCENT_SIZE, apple_artwork_url


# [r2.2] C5-67: Like is add-only, final. The constant stays for the tests; there is no other
# strategy, no settings.json override and no unlike request (K3 section 9.8.2).
UNLIKE_STRATEGY = "add_only"

LIKE_READBACK_S = 0.25      # like_readback_ms
LIKE_CONFIRM_S = 4.0        # like_confirm_ms
RESOLVE_DEADLINE_S = 20.0   # resolve_deadline_s (C5-37)
RESOLVE_CACHE_ENTRIES = 64
RESOLVE_CACHE_TTL_S = 1800.0
PRERESOLVE_MAX_TRACKS = 100  # the Play next cap; larger items are never pre-resolved
FAVORITES = "/v1/me/favorites"
UNTITLED_PLAYLIST = "Untitled playlist"   # overlay.explorer.untitled (C5-30)
FAVORITE_SONGS = "Favorite Songs"
_FAVOURITE_WRITE = re.compile(r"/v1/me/favorites\?ids\[songs\]=(\d{1,20})")
_CATALOG_ID = re.compile(r"\d{1,20}")
_ALBUM_PATH = re.compile(r"/[a-z]{2}/album/[^/]+/\d+")

# Diagnostics only: HTTP status codes, never ids, tokens, Apple error bodies or titles.
_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())  # the application configures the real handlers

HEART_STATES = ("liked", "not_liked", "unknown", "not_catalog")


class AppleMusicError(RuntimeError):
    """Sanitised Apple Music failure. ``status`` is the HTTP status (int) or None;
    ``code`` Apple's error code string when the error body carried one (never logged)."""

    def __init__(self, message: str = "", *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class MusicUnavailable(AppleMusicError):
    pass


class ResolveTimeout(MusicUnavailable):
    """The whole resolve passed its 20 s deadline (C5-37); nothing was staged."""


class NotCatalog(AppleMusicError):
    """The favourites POST answered 404: the song is not in the catalog (``not_catalog``)."""


class LikeNotConfirmed(AppleMusicError):
    """The ratings read-back did not show the requested end state within 4 s (``failed``)."""


class UnlikeUnavailable(AppleMusicError):
    """``unlike`` was called (a programming error: the controller refuses the press first,
    ``unlike_unavailable``; [r2.2] C5-67). Raised before any I/O."""


def apple_outcome(error, op: str, *, kind: str | None = None) -> str:
    """K3 section 9.10 outcome for an exception from an Apple op.

    ``op`` is the effect kind (``like``, ``ratings``, ``catalog_songs``,
    ``favourite_playlists``, ``playlist_meta``, ``recent``, ``play_items``, ``play_next``,
    ``resolve``); ``kind`` the item kind for a start (``album`` / ``playlist`` / ``song``).
    """
    status = getattr(error, "status", None)
    if status in (401, 403):
        return "signin_expired"
    if status == 429:
        return "rate_limited"
    if isinstance(error, NotCatalog):
        return "not_catalog"
    if op == "play_next":
        return "nothing_added"
    if op == "play_items":
        if isinstance(error, MusicUnavailable) and not isinstance(error, ResolveTimeout) and kind == "album":
            return "album_blocked"
        return "start_failed"
    return "failed"


def liked_states(ids, ratings: dict) -> dict:
    """The heart state of each catalog id from a ``ratings`` answer (K3 section 9.7.2, C5-64):
    ``liked = (value == 1)``; an id absent from the answer (unrated, or a 404 batch) is False.
    Ids that are not catalog ids (None, library ids) are left out: those rows are not in Apple
    Music (C5-43) and keep no heart state."""
    ratings = ratings if isinstance(ratings, dict) else {}
    states = {}
    for value in ids or ():
        song = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
        if _CATALOG_ID.fullmatch(song) and song not in states:
            states[song] = ratings.get(song) == 1
    return states


def heart_state(*, catalog, liked) -> str:
    """One of the four row-heart states ([r2.2] R22 CH §1; K4 S5-34 draws them), in K4's
    precedence: ``not_catalog`` (the catalog batch did not return the song) → ``unknown`` (no
    ratings answer yet: ``liked`` None) → ``liked`` / ``not_liked``."""
    if catalog is False:
        return "not_catalog"
    if liked is None:
        return "unknown"
    return "liked" if liked is True else "not_liked"


def _hex_colour(value) -> int:
    """Apple's ``bgColor`` / ``textColor1`` (``"1d1d1f"``) as 0xRRGGBB, 0 when absent or invalid."""
    if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return int(value, 16)
    return 0


def art_keys(artwork) -> dict:
    """K4 section 13.2 item art keys (VOC-K4-03, C5-57) from an Apple ``artwork`` object.

    ``art_template`` is kept only when ``apple_artwork_url`` accepts it (``{w}``/``{h}``/``{f}``
    placeholders on the Apple CDN); ``art_max`` is min(width, height), 0 when unknown.
    Items without usable art carry "", 0, 0, 0 (K4 section 13.6 ``art.generated``).
    """
    template = artwork.get("url") if isinstance(artwork, dict) else None
    if not isinstance(template, str) or not apple_artwork_url(artwork):
        return {"art_template": "", "art_max": 0, "art_bg": 0, "art_ink": 0}
    sizes = [artwork.get(key) for key in ("width", "height")]
    art_max = min(sizes) if all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in sizes) else 0
    return {"art_template": template, "art_max": art_max,
            "art_bg": _hex_colour(artwork.get("bgColor")), "art_ink": _hex_colour(artwork.get("textColor1"))}


def _year(value) -> int | None:
    if isinstance(value, str) and re.match(r"\d{4}", value):
        return int(value[:4])
    return None


def _int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class _Flight:
    """One resolve in progress (joined by a Play next or a start for the same item, C5-66)."""

    def __init__(self, lenient):
        self.lenient = lenient
        self.event = threading.Event()
        self.result = None
        self.error = None


class AppleMusicClient:
    API = "https://api.music.apple.com"
    RECENT = "/v1/me/library/recently-added"
    PLAYLISTS = "/v1/me/library/playlists"
    MAX_TRACK_PAGES = 100
    MAX_TRACKS = 5000
    # Parse caps (K3 section 1.2, K4 section 4.7.3, [G1] G1-5). ``requests``' ``.json()`` parses a whole
    # body in one GIL-holding C call, so a page may not grow past what parses within the 1 ms design
    # target while a desktop overlay animates. The rule is the H5 bench's (tools/stage_checks/
    # gil_parse_hold.py ``caps()``; the record is design-reference/ui-v2-analysis/gil-parse-hold.md,
    # sections 1 to 3): each cap is the largest size whose hold has a p50 of at most 0.5 ms (a real
    # body up to twice the synthetic fixture's size still parses within 1 ms) AND a p95 of at most
    # 1.0 ms (the tail on a shared PC). Holds in ms, p50 / p95 of the 03:15 run [p95 over six runs]:
    #   /tracks?include=catalog page  100 rows 0.92 / 1.07 [1.00-1.74]   50 rows 0.49 / 0.77 [0.47-0.81]
    #   catalog songs?ids= answer     300 ids  1.89 / 2.69 [2.13-3.80]   50 ids  0.27 / 0.35 [0.28-0.55]
    #   playlists page                100 rows 0.22 / 0.36 [0.21-0.36]
    #   Recently Added page            25 rows 0.05 / 0.08 [0.05-0.09]
    #   ratings answer                100 ids  0.04 / 0.06 [0.04-0.07]
    # 50-row tracks pages met the rule in every run except the slow 03:12 one (p50 0.71 ms, p95
    # 0.81 ms), which allowed only 25; the md's section 3 and deviation WP6-GIL-D1 say why 50 stays.
    TRACKS_PAGE_LIMIT = 50    # resolve and playlist_meta pages (was 100: p95 1.00-1.74 ms per page)
    CATALOG_BATCH = 50        # catalog_songs ids per request (was 300: p95 2.13-3.80 ms per answer)
    PLAYLISTS_PAGE_LIMIT = 100  # favourite-playlists pages: p95 0.21-0.36 ms at 100, unchanged
    RATINGS_BATCH = 100       # p95 0.04-0.07 ms at 100, unchanged
    RECENT_PAGE = 25          # p95 0.05-0.09 ms at 25, unchanged
    MOSAIC_SCAN_TRACKS = 100  # playlist_meta looks for its 4 mosaic albums in the first 100 tracks, as
                              # when the first page held 100: it reads a second page only when needed
    META_MAX_TRACKS = 10_000  # playlist_meta's duration reads every page up to this many tracks, the
                              # reach 100 pages of 100 had; its page bound follows TRACKS_PAGE_LIMIT

    def __init__(self, credentials: dict, *, session=None, timeout: float = 8.0, credential_loader=None,
                 background_session=None, clock=None, sleep=None):
        """``session`` serves the foreground (library lane) requests. The lookahead lane
        (ARTWORK2.md section 11: next-page prefetch, Home warm-up) uses its own
        ``background_session``, so the two lanes never share a requests.Session or wait
        for each other's HTTP. When None it is created on first use, except that an
        injected ``session`` without one (tests) is shared by both lanes, one request at
        a time, and never replaced by a real one. Each session is used by one thread at
        a time (its lock).

        ``clock`` / ``sleep`` default to ``time.monotonic`` / ``time.sleep`` (tests inject a fake clock).
        """
        self.credentials = dict(credentials)
        self.credential_loader = credential_loader
        self._owns_session = session is None
        if session is None:
            session = self._new_session()
        self.session = session
        self._session_lock = threading.Lock()
        self._background_session = background_session
        self._background_lock = threading.Lock()
        self._lane_lock = threading.Lock()
        self.timeout = timeout
        self._clock = clock
        self._sleeper = sleep
        self._storefront = None
        self._storefront_lock = threading.Lock()
        self._recent_pages = 0
        self._recent_next = None
        self._recent_seen = set()
        self._recent_cache = {}
        self._recent_lock = threading.RLock()
        self._recent_visit = 0  # grows at each committed page 1 (a new browsing visit)
        self._resolve_lock = threading.Lock()
        self._resolve_cache = OrderedDict()   # (kind, id) -> (expires_at, lenient, result)
        self._resolving = {}                  # (kind, id) -> _Flight
        self.resolve_lookups = 0              # uncached resolves performed (tests, diagnostics)
        self._duration_cache = OrderedDict()  # (playlist id, last_modified) -> duration_ms (None: cannot be read to its end)

    # ------------------------------------------------------------------ plumbing
    def _now(self) -> float:
        return (self._clock or time.monotonic)()

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            (self._sleeper or time.sleep)(seconds)

    @staticmethod
    def _new_session():
        try:
            import requests
            return requests.Session()
        except ImportError:
            raise AppleMusicError("Install the control-center dependencies to enable Apple Music.") from None

    def _http(self, background):
        """(session, lock) for one request: the foreground session, or the lookahead lane's."""
        if not background:
            return self.session, self._session_lock
        with self._lane_lock:
            if self._background_session is None:
                self._background_session = self._new_session() if self._owns_session else self.session
            session = self._background_session
        return (session, self._session_lock) if session is self.session else (session, self._background_lock)

    @classmethod
    def _safe_path(cls, value: str) -> str:
        if not isinstance(value, str):
            raise AppleMusicError("Apple Music returned an invalid pagination link.")
        parsed = urlsplit(value)
        if (parsed.scheme and parsed.scheme != "https") or (parsed.netloc and parsed.netloc != "api.music.apple.com") or parsed.fragment:
            raise AppleMusicError("Apple Music returned an invalid pagination link.")
        if not parsed.path.startswith("/v1/") or ".." in parsed.path or "\\" in value:
            raise AppleMusicError("Apple Music returned an invalid resource link.")
        return urlunsplit(("", "", parsed.path, parsed.query, ""))

    @staticmethod
    def _check_write(method: str, path: str, params, json) -> None:
        """The guarded write helper: exactly the favourites POST of one catalog song, no params,
        no body. Every other method (``DELETE`` of any kind, [r2.2] C5-67; ``PUT``, ``PATCH``) is
        refused before any I/O."""
        if method != "POST" or params or json is not None or not _FAVOURITE_WRITE.fullmatch(path):
            raise AppleMusicError("This Apple Music change is not allowed.")

    @staticmethod
    def _error_code(response):
        try:
            errors = response.json().get("errors")
            code = errors[0].get("code") if isinstance(errors, list) and errors else None
            return code if isinstance(code, str) and len(code) <= 16 else None
        except Exception:
            return None

    def _request(self, method: str, path: str, *, params=None, json=None, expected=(200,), background=False):
        path = self._safe_path(path)
        if method != "GET":
            self._check_write(method, path, params, json)
        # Authorization can complete after the tray app starts. Read the current
        # encrypted store in this background lane instead of retaining an empty
        # startup snapshot until the entire application is restarted.
        credentials = self.credential_loader() if self.credential_loader else self.credentials
        self.credentials = dict(credentials)
        user_token = credentials.get("music_user_token")
        if not isinstance(user_token, str) or not user_token:
            raise AppleMusicError("Connect Apple Music in companion settings first.")
        try:
            token = developer_token(credentials)
            session, lock = self._http(background)
            headers = {"Authorization": "Bearer " + token, "Music-User-Token": user_token,
                       "Accept": "application/json"}
            with lock:  # requests.Session is not documented as thread-safe
                if method == "GET":
                    response = session.get(self.API + path, params=params, headers=headers,
                                           timeout=self.timeout, allow_redirects=False)
                else:
                    response = session.request(method, self.API + path, headers=headers,
                                               timeout=self.timeout, allow_redirects=False)
            status = response.status_code
            if status in (401, 403):
                raise AppleMusicError("Apple Music authorization expired or access was denied. Reconnect in settings.",
                                      status=status)
            if status == 429:
                raise AppleMusicError("Apple Music is temporarily limiting requests. Try again shortly.", status=429)
            if status not in expected:
                raise AppleMusicError("Apple Music could not load this library item. Try again later.",
                                      status=status, code=self._error_code(response))
            if status in (202, 204):
                return None
            if method != "GET" and not getattr(response, "content", b"{}"):
                return None
            return response.json()
        except (AppleMusicError, CredentialError):
            raise
        except Exception:
            # requests exceptions may include URLs, headers or response text.
            raise AppleMusicError("Apple Music could not be reached. Check the connection and retry.") from None

    def _get(self, path: str, *, params=None, background=False) -> dict:
        result = self._request("GET", path, params=params, background=background)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise AppleMusicError("Apple Music returned an incomplete response.")
        return result

    def _send(self, method: str, path: str, *, json=None, params=None, expected=(200,), background=False):
        """K3 section 9.8.1: one request with the usual headers, no redirects, 8 s timeout.
        Returns the parsed body for a 200 with a body, None for 202/204. Writes are limited
        to the favourites calls (``_check_write``)."""
        return self._request(method.upper(), path, params=params, json=json, expected=expected,
                             background=background)

    # ------------------------------------------------------------------ credentials
    def has_credentials(self) -> bool:
        """Whether the credentials last read hold a Music user token.

        No I/O (the Home warm-up asks on the UI thread). Every request still reads the
        current store first (``_get``), so this only decides whether to try at all.
        """
        credentials = self.credentials
        token = credentials.get("music_user_token") if isinstance(credentials, dict) else None
        return isinstance(token, str) and bool(token)

    def refresh_credentials(self) -> bool:
        """Re-read the credential store (no network) and report ``has_credentials()``.

        Store I/O, so background lanes only: the Home warm-up asks before its page-1
        request, so an authorization saved after startup is found without waiting for
        another Apple Music request, and nothing is requested without a Music user token.
        """
        if self.credential_loader:
            self.credentials = dict(self.credential_loader())
        return self.has_credentials()

    # ------------------------------------------------------------------ Recently Added
    def recent(self, cursor: str | None = None, limit: int = 10) -> dict:
        """A None cursor starts a fresh visit; continuation cursors are idempotent.

        Serialize requests and resets so an in-flight old page cannot commit into
        a new visit. A failed response changes no cache, seen IDs, or page count.
        Cached replies are copies: callers cannot mutate the browsing snapshot.
        """
        with self._recent_lock:
            return self._recent_page(cursor, limit)

    def recent_lookahead(self, cursor: str, limit: int = 10, wanted=None) -> dict:
        """The next page of the current visit for the lookahead lane (ARTWORK2.md 11.1).

        The same request, validation, continuation cache and commit as
        ``recent(cursor)``, but the visit lock is held only for the bookkeeping before
        and after the request (no I/O), and the request uses the lookahead lane's own
        session. So a background page never delays a foreground load, not even one
        that is obsolete and still waiting for Apple. ``wanted`` (optional, no I/O) is
        asked with the lock held: an unwanted page raises before any request. A new
        visit committed while the request is out makes the response obsolete: it raises
        and commits nothing. A page the foreground committed meanwhile is returned from
        the cache (one commit). ``limit`` is accepted as by ``recent``: a continuation
        link carries its own. Raises like ``recent``; the caller runs it off the UI thread.
        """
        with self._recent_lock:
            if wanted is not None and not wanted():
                raise AppleMusicError("Obsolete library request discarded")
            path, cached = self._continuation(cursor)
            if cached is not None:
                return cached
            visit = self._recent_visit
        response = self._get(path, background=True)
        with self._recent_lock:
            if visit != self._recent_visit:
                raise AppleMusicError("The library page changed. Refresh Recently Added.")
            path, cached = self._continuation(cursor)
            if cached is not None:
                return cached
            return self._commit_recent(path, response, reset=False)

    def recent_page(self, offset: int = 0, *, visit: int | None = None, limit: int = RECENT_PAGE,
                    background: bool = False, wanted=None) -> dict:
        """One page of the flat Recently Added list (K3 section 9.8.6, U5).

        ``GET /v1/me/library/recently-added?limit=25&offset={offset}`` with our own params
        on every page (Apple's ``next`` is never followed verbatim). ``visit=None`` starts a
        new visit (committed only when the page validates); any other page names its visit
        and raises, committing nothing, when a newer visit started before or while it was
        out (the ``_recent_visit`` bookkeeping). ``wanted`` (no I/O) is asked first.

        Returns ``{"items", "offset", "limit", "total", "complete", "visit"}``: ``total`` from
        ``meta.total`` when present (OQ-1) else None; ``complete`` when the page has no ``next``.
        """
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= self.MAX_TRACKS:
            raise AppleMusicError("The library page changed. Refresh Recently Added.")
        limit = max(1, min(int(limit), self.RECENT_PAGE))
        with self._recent_lock:
            if wanted is not None and not wanted():
                raise AppleMusicError("Obsolete library request discarded")
            current = self._recent_visit
            if visit is not None and visit != current:
                raise AppleMusicError("The library page changed. Refresh Recently Added.")
        response = self._get(self.RECENT, params={"limit": limit, "offset": offset}, background=background)
        result = self._recent_result(response, self.RECENT, set(), {})
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        total = _int_or_none(meta.get("total"))
        with self._recent_lock:
            if self._recent_visit != current:
                raise AppleMusicError("The library page changed. Refresh Recently Added.")
            if visit is None:
                self._recent_visit += 1
                current = self._recent_visit
        return {"items": result["items"], "offset": offset, "limit": limit,
                "total": total if total is not None and total >= 0 else None,
                "complete": not response.get("next"), "visit": current}

    def recent_preview(self, limit: int = 10) -> dict:
        """Recently Added page 1 for the Home warm-up (ARTWORK2.md 11.4), read-only.

        The same request, validation, item shape and bounds as ``recent(None)``, but it
        never resets or commits the browsing visit (its page count, seen IDs,
        continuation cache or next cursor), so a warm-up can never disturb More. It
        takes no visit lock and uses the lookahead lane's session. Raises like
        ``recent``; the caller runs it off the UI thread.
        """
        limit = max(1, min(int(limit), 25))
        response = self._get(self.RECENT, params={"limit": limit}, background=True)
        return self._recent_result(response, self.RECENT, set(), {})

    def _continuation(self, cursor: str):
        """(path, a copy of its cached page or None) for a continuation cursor of the
        current visit; raises when it is not the visit's next page. Visit lock held."""
        path = self._safe_path(cursor)
        if path in self._recent_cache:
            return path, deepcopy(self._recent_cache[path])
        if path != self._recent_next or urlsplit(path).path != self.RECENT:
            raise AppleMusicError("The library page changed. Refresh Recently Added.")
        return path, None

    def _commit_recent(self, path: str, response, reset: bool) -> dict:
        """Validate a Recently Added response and commit it (visit lock held).

        ``reset``: page 1, which starts a new visit. A failed validation changes nothing.
        """
        if reset:
            pages, seen, cache = 0, set(), {}
        else:
            pages, seen, cache = self._recent_pages, set(self._recent_seen), dict(self._recent_cache)
        result = self._recent_result(response, path, seen, cache)
        cache[path] = deepcopy(result)
        # Commit only once every field and pagination link has passed validation.
        self._recent_pages, self._recent_seen = pages + 1, seen
        self._recent_next, self._recent_cache = result["next"], cache
        if reset:
            self._recent_visit += 1
        return deepcopy(result)

    def _recent_page(self, cursor: str | None, limit: int) -> dict:
        limit = max(1, min(int(limit), 25))
        if cursor is None:
            path = self.RECENT
        else:
            path, cached = self._continuation(cursor)
            if cached is not None:
                return cached
        response = self._get(path, params={"limit": limit} if cursor is None else None)
        return self._commit_recent(path, response, reset=cursor is None)

    @staticmethod
    def _check_resource(resource) -> dict:
        if (not isinstance(resource, dict) or not isinstance(resource.get("id"), str) or not resource["id"] or
                not isinstance(resource.get("type"), str) or not resource["type"] or
                not isinstance(resource.get("attributes", {}), dict)):
            raise AppleMusicError("Apple Music returned an incomplete library item.")
        attributes = resource.get("attributes", {})
        if any(value is not None and not isinstance(value, str)
               for value in (attributes.get("name"), attributes.get("artistName"))):
            raise AppleMusicError("Apple Music returned invalid library metadata.")
        return attributes

    @staticmethod
    def _item_art(attributes: dict) -> dict:
        """The art fields every list item carries: the knob's 480 px URL and 96 px accent URL
        (unchanged) plus the K4 section 13.2 keys (C5-57)."""
        artwork = attributes.get("artwork")
        return {"artwork_url": apple_artwork_url(artwork),
                # 96 px of the same template for the ring accent (AccentService).
                "accent_url": apple_artwork_url(artwork, ACCENT_SIZE), **art_keys(artwork)}

    def _recent_result(self, response, path: str, seen: set, cache: dict) -> dict:
        """Validate one Recently Added response into a page dict.

        Adds the page's item identities to ``seen`` (skipping ones already there) and
        rejects a next link that repeats ``path`` or a page in ``cache``. Changes no
        client state.
        """
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise AppleMusicError("Apple Music returned an incomplete library page.")
        next_path = self._safe_path(response["next"]) if response.get("next") else None
        if next_path and (urlsplit(next_path).path != self.RECENT or next_path == path or next_path in cache):
            raise AppleMusicError("Apple Music returned a repeating library page. Refresh Recently Added.")
        items = []
        kinds = {"library-albums": "album", "library-playlists": "playlist", "library-songs": "song"}
        for resource in response["data"]:
            attributes = self._check_resource(resource)
            identity = (resource.get("type"), resource.get("id"))
            if identity in seen:
                continue
            seen.add(identity)
            kind = kinds.get(resource.get("type"), "unsupported")
            available = kind != "unsupported"
            reason = "" if available else "This library media type cannot play through this control."
            if kind == "song" and attributes.get("hasCatalog") is False:
                available, reason = False, "This library track has no Apple Music catalog mapping."
            items.append({"id": resource.get("id", ""),
                          "title": attributes.get("name") or "Untitled library item",
                          "artist": attributes.get("artistName") or "",
                          **self._item_art(attributes),
                          "year": _year(attributes.get("releaseDate")),
                          "track_count": _int_or_none(attributes.get("trackCount")),
                          "kind": kind, "available": available, "reason": reason,
                          "resource_type": resource.get("type"), "_resource": resource})
        # Each page is explicitly requested by the user. Follow Apple's next
        # link without imposing an undisclosed 100-item library cutoff.
        return {"items": items, "next": next_path, "truncated": False}

    # ------------------------------------------------------------------ paging helpers
    def _collection(self, path: str, *, background=False, deadline=None) -> list[dict]:
        """Follow Apple's ``next`` verbatim (only for the catalog relationship of one song)."""
        result, visited = [], set()
        while path:
            path = self._safe_path(path)
            if path in visited or len(visited) >= self.MAX_TRACK_PAGES:
                raise MusicUnavailable("The complete track list could not be verified. Nothing was queued.")
            visited.add(path)
            self._check_deadline(deadline)
            page = self._get(path, background=background)
            result.extend(page["data"])
            if len(result) > self.MAX_TRACKS:
                raise MusicUnavailable("This item exceeds the supported track limit. Nothing was queued.")
            path = page.get("next")
        return result

    def _own_pages(self, path: str, params: dict, *, background=False, deadline=None, max_pages=None):
        """Yield every page of ``path``, re-sending **our own** ``params`` plus the ``offset``
        read from Apple's ``next`` (which drops ``extend``, ``include`` and ``limit``, CF section 2
        row 8; ``AM:293``). A ``next`` for another path, without a numeric increasing offset,
        or past the page bound is refused."""
        path = self._safe_path(path)
        offset, pages = None, 0
        max_pages = max_pages or self.MAX_TRACK_PAGES
        while True:
            self._check_deadline(deadline)
            query = dict(params)
            if offset is not None:
                query["offset"] = offset
            page = self._get(path, params=query, background=background)
            yield page
            link = page.get("next")
            if not link:
                return
            parsed = urlsplit(self._safe_path(link))
            values = parse_qs(parsed.query).get("offset")
            if parsed.path != path or not values or not values[0].isdigit():
                raise AppleMusicError("Apple Music returned an invalid pagination link.")
            following = int(values[0])
            pages += 1
            if (offset is not None and following <= offset) or following <= 0 or pages >= max_pages:
                raise MusicUnavailable("The complete track list could not be verified. Nothing was queued.")
            offset = following

    def _check_deadline(self, deadline):
        if deadline is not None and self._now() > deadline:
            raise ResolveTimeout("Apple Music took too long to list this item. Nothing was queued.")

    def _get_storefront(self, background=False) -> str:
        with self._storefront_lock:
            if self._storefront is not None:
                return self._storefront
        response = self._get("/v1/me/storefront", background=background)
        storefront = response["data"][0].get("id", "") if response["data"] else ""
        if not re.fullmatch(r"[a-z]{2}", storefront):
            raise AppleMusicError("Apple Music did not provide a valid storefront.")
        with self._storefront_lock:
            self._storefront = storefront
        return storefront

    # ------------------------------------------------------------------ resolution
    def _catalog_song(self, resource: dict, *, background=False, deadline=None) -> dict:
        if resource.get("type") == "songs":
            catalog = resource
        elif resource.get("type") == "library-songs":
            related = resource.get("relationships", {}).get("catalog")
            if related is not None and "data" in related and not related.get("next"):
                candidates = related["data"]
            else:
                candidates = self._collection("/v1/me/library/songs/" + quote(str(resource.get("id", "")), safe="") + "/catalog",
                                              background=background, deadline=deadline)
            if len(candidates) != 1 or candidates[0].get("type") != "songs":
                raise MusicUnavailable("At least one library track has no unique Apple Music catalog match. Nothing was queued.")
            catalog = candidates[0]
        else:
            raise MusicUnavailable("This item includes unsupported or uploaded-only media. Nothing was queued.")
        if not re.fullmatch(r"\d+", str(catalog.get("id", ""))):
            raise MusicUnavailable("A catalog track identifier is missing. Nothing was queued.")
        if not catalog.get("attributes", {}).get("url"):
            self._check_deadline(deadline)
            response = self._get(f"/v1/catalog/{self._get_storefront(background)}/songs/{catalog['id']}",
                                 background=background)
            if len(response["data"]) != 1 or response["data"][0].get("id") != catalog["id"]:
                raise MusicUnavailable("A catalog track could not be verified. Nothing was queued.")
            catalog = response["data"][0]
        if not catalog.get("attributes", {}).get("playParams"):
            raise MusicUnavailable("At least one track is unavailable in your Apple Music storefront. Nothing was queued.")
        return catalog

    @staticmethod
    def _album_form_url(song_id: str, url) -> str:
        """The Sonos share-link form ``https://music.apple.com/{sf}/album/{name}/{id}?i={song}``, or ""."""
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (parsed and parsed.scheme == "https" and parsed.netloc == "music.apple.com"
                and _ALBUM_PATH.fullmatch(parsed.path) and parse_qs(parsed.query).get("i") == [song_id]):
            return urlunsplit(("https", "music.apple.com", parsed.path, urlencode({"i": song_id}), ""))
        return ""

    def _song_url(self, song: dict, *, background=False, deadline=None) -> str:
        song_id = str(song["id"])
        url = song.get("attributes", {}).get("url", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "music.apple.com":
            raise MusicUnavailable("Apple Music did not provide a playable song link. Nothing was queued.")
        direct = self._album_form_url(song_id, url)
        if direct:
            return direct
        # SoCo's Apple share-link implementation accepts album URLs with ?i=SONG.
        # Obtain the actual related album URL; never invent an album ID.
        storefront = self._get_storefront(background)
        albums = self._collection(f"/v1/catalog/{storefront}/songs/{song_id}/albums",
                                  background=background, deadline=deadline)
        if not albums or albums[0].get("type") != "albums":
            raise MusicUnavailable("This song has no Sonos-compatible Apple Music link. Nothing was queued.")
        album = albums[0]
        album_url = album.get("attributes", {}).get("url")
        if not album_url:
            album_id = str(album.get("id", ""))
            if not re.fullmatch(r"\d+", album_id):
                raise MusicUnavailable("This song has no verified album link. Nothing was queued.")
            self._check_deadline(deadline)
            response = self._get(f"/v1/catalog/{storefront}/albums/{album_id}", background=background)
            album_url = response["data"][0].get("attributes", {}).get("url", "") if response["data"] else ""
        parsed = urlsplit(album_url)
        if parsed.scheme != "https" or parsed.netloc != "music.apple.com" or not _ALBUM_PATH.fullmatch(parsed.path):
            raise MusicUnavailable("This song has no Sonos-compatible album link. Nothing was queued.")
        return urlunsplit(("https", "music.apple.com", parsed.path, urlencode({"i": song_id}), ""))

    @staticmethod
    def _resolve_key(item: dict):
        if not isinstance(item, dict):
            raise MusicUnavailable("This library item is unavailable.")
        if item.get("available") is False:
            raise MusicUnavailable(item.get("reason") or "This library item is unavailable.")
        identifier = str(item.get("id", ""))
        if not identifier:
            raise MusicUnavailable("This library item has no identifier.")
        kind = item.get("kind")
        if kind not in ("song", "album", "playlist"):
            raise MusicUnavailable("This media type is not supported.")
        return kind, identifier

    def resolve_cached(self, item: dict, *, lenient=None) -> dict | None:
        """A copy of the cached resolve of ``item`` (LRU 64, TTL 1800 s), or None. No I/O."""
        try:
            key = self._resolve_key(item)
        except MusicUnavailable:
            return None
        lenient = (key[0] == "playlist") if lenient is None else bool(lenient)
        with self._resolve_lock:
            entry = self._resolve_cache.get(key)
            if entry is None:
                return None
            expires, cached_lenient, result = entry
            if self._now() >= expires:
                self._resolve_cache.pop(key, None)
                return None
            if cached_lenient != lenient and result["unavailable"]:
                return None  # a strict request never uses a lenient result that skipped tracks
            self._resolve_cache.move_to_end(key)
            return deepcopy(result)

    def resolve_running(self, item: dict) -> bool:
        """Whether a resolve of ``item`` is in progress now (a Play next joins it, C5-66)."""
        try:
            key = self._resolve_key(item)
        except MusicUnavailable:
            return False
        with self._resolve_lock:
            return key in self._resolving

    def evict_resolved(self, item: dict) -> None:
        """Drop ``item`` from the resolve cache (a start or Play next citing it failed)."""
        try:
            key = self._resolve_key(item)
        except MusicUnavailable:
            return
        with self._resolve_lock:
            self._resolve_cache.pop(key, None)

    def resolve(self, item: dict, *, lenient=None, background=False, deadline_s: float = RESOLVE_DEADLINE_S) -> dict:
        """Map a library album, playlist or song to catalog songs (K3 section 9.8.7, U6).

        ``lenient`` defaults per kind: playlists lenient (unplayable tracks skipped and
        counted; zero playable is fatal), albums and songs strict (any unplayable track is
        fatal). Albums and playlists are listed with
        ``/v1/me/library/{albums|playlists}/{id}/tracks?include=catalog&limit=50`` (``TRACKS_PAGE_LIMIT``,
        the K3 section 1.2 parse cap) and the own-params pager. The whole resolve has a ``deadline_s`` (20 s) deadline
        (``ResolveTimeout``). The cache is read first and written on success; a resolve of
        the same item already running on another lane is joined under the same deadline.

        Returns ``{"tracks": [...], "total": n, "unavailable": u}``; each track has
        ``title``, ``artist``, ``catalog_id``, ``url``, ``library_id``, ``album``,
        ``track_number``, ``duration_ms``, ``art_template``.
        """
        key = self._resolve_key(item)
        lenient = (key[0] == "playlist") if lenient is None else bool(lenient)
        cached = self.resolve_cached(item, lenient=lenient)
        if cached is not None:
            return cached
        started = self._now()
        deadline = started + deadline_s
        with self._resolve_lock:
            flight = self._resolving.get(key)
            owner = flight is None or flight.lenient != lenient
            if owner and flight is None:
                flight = self._resolving[key] = _Flight(lenient)
            elif owner:
                flight = None  # a different leniency is running: resolve here, never join it
        if not owner:
            if not flight.event.wait(max(0.0, deadline - self._now())):
                raise ResolveTimeout("Apple Music took too long to list this item. Nothing was queued.")
            if flight.error is not None:
                error = flight.error
                raise type(error)(str(error), status=getattr(error, "status", None)) from None
            return deepcopy(flight.result)
        try:
            result = self._resolve_uncached(item, key, lenient, background, deadline)
        except BaseException as error:
            if flight is not None:
                flight.error = error if isinstance(error, AppleMusicError) else AppleMusicError(
                    "Apple Music could not load this library item. Try again later.")
            raise
        else:
            with self._resolve_lock:
                self._resolve_cache[key] = (self._now() + RESOLVE_CACHE_TTL_S, lenient, deepcopy(result))
                self._resolve_cache.move_to_end(key)
                while len(self._resolve_cache) > RESOLVE_CACHE_ENTRIES:
                    self._resolve_cache.popitem(last=False)
            if flight is not None:
                flight.result = deepcopy(result)
            return result
        finally:
            if flight is not None:
                with self._resolve_lock:
                    if self._resolving.get(key) is flight:
                        del self._resolving[key]
                flight.event.set()

    def preresolve(self, item: dict, *, focused: bool = False) -> dict | None:
        """The lookahead lane's pre-resolution (C5-66): resolve ``item`` into the cache on the
        background session, or return None without I/O when it is cached, unavailable, larger
        than 100 tracks (albums by ``track_count``), or a playlist of unknown size that is not
        ``focused``. Errors propagate (the caller drops them silently)."""
        try:
            key = self._resolve_key(item)
        except MusicUnavailable:
            return None
        if self.resolve_cached(item) is not None or self.resolve_running(item):
            return None
        count = item.get("track_count")
        if isinstance(count, int) and not isinstance(count, bool) and count > PRERESOLVE_MAX_TRACKS:
            return None
        if key[0] == "playlist" and not isinstance(count, int) and not focused:
            return None
        return self.resolve(item, background=True)

    def _resolve_uncached(self, item, key, lenient, background, deadline) -> dict:
        self.resolve_lookups += 1
        kind, identifier = key
        resource = item.get("_resource", {}) or {}
        total = None
        if kind == "song":
            tracks = [resource] if resource.get("type") == "library-songs" else self._collection(
                "/v1/me/library/songs/" + quote(identifier, safe=""), background=background, deadline=deadline)
        else:
            plural = "albums" if kind == "album" else "playlists"
            tracks = []
            # The page bound follows the page size, so an item over MAX_TRACKS still fails as
            # "exceeds the supported track limit" rather than as an unverified list.
            pages = max(self.MAX_TRACK_PAGES, -(-self.MAX_TRACKS // self.TRACKS_PAGE_LIMIT) + 2)
            for page in self._own_pages(f"/v1/me/library/{plural}/{quote(identifier, safe='')}/tracks",
                                        {"include": "catalog", "limit": self.TRACKS_PAGE_LIMIT},
                                        background=background, deadline=deadline, max_pages=pages):
                tracks.extend(page["data"])
                if len(tracks) > self.MAX_TRACKS:
                    raise MusicUnavailable("This item exceeds the supported track limit. Nothing was queued.")
                meta = page.get("meta") if isinstance(page.get("meta"), dict) else {}
                total = _int_or_none(meta.get("total")) if total is None else total
            expected = resource.get("attributes", {}).get("trackCount") if isinstance(resource.get("attributes"), dict) else None
            if (expected is not None and int(expected) != len(tracks)) or (total is not None and total != len(tracks)):
                raise MusicUnavailable("The library item changed while loading. Refresh it before playing.")
        if not tracks:
            raise MusicUnavailable("This library item contains no playable tracks.")
        resolved, unavailable = [], 0
        for track in tracks:  # Preserve order and intentional duplicate playlist entries.
            try:
                song = self._catalog_song(track, background=background, deadline=deadline)
                url = self._song_url(song, background=background, deadline=deadline)
            except ResolveTimeout:
                raise
            except MusicUnavailable:
                if not lenient:
                    raise
                unavailable += 1
                continue
            attributes = song.get("attributes", {})
            resolved.append({"title": attributes.get("name", ""), "artist": attributes.get("artistName", ""),
                             "catalog_id": str(song["id"]), "url": url,
                             "library_id": track.get("id", ""),
                             "album": attributes.get("albumName", "") or "",
                             "track_number": _int_or_none(attributes.get("trackNumber")),
                             "duration_ms": _int_or_none(attributes.get("durationInMillis")),
                             "art_template": art_keys(attributes.get("artwork"))["art_template"]})
        if not resolved:
            raise MusicUnavailable("This library item contains no playable tracks.")
        self._check_deadline(deadline)  # the deadline bounds the whole resolve, its last request included
        return {"tracks": resolved, "total": len(tracks), "unavailable": unavailable}

    # ------------------------------------------------------------------ likes (C5-62..C5-64)
    @staticmethod
    def _catalog_id(value) -> str:
        value = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
        if not _CATALOG_ID.fullmatch(value):
            raise NotCatalog("This song is not in the Apple Music catalog.")
        return value

    def ratings(self, ids, *, background=True) -> dict:
        """``GET /v1/me/ratings/songs?ids=a,b,…`` (batches of 100) → ``{id: value}``; unrated ids
        are absent, a 404 batch means none. ``liked = (value == 1)``: the one source of the
        heart state (C5-64)."""
        wanted = []
        for value in ids or ():
            song = self._catalog_id(value)
            if song not in wanted:
                wanted.append(song)
        result = {}
        for start in range(0, len(wanted), self.RATINGS_BATCH):
            batch = wanted[start:start + self.RATINGS_BATCH]
            try:
                response = self._get("/v1/me/ratings/songs", params={"ids": ",".join(batch)}, background=background)
            except AppleMusicError as error:
                if error.status == 404:
                    continue
                raise
            for row in response["data"]:
                if not isinstance(row, dict) or str(row.get("id")) not in batch:
                    continue
                value = row.get("attributes", {}).get("value") if isinstance(row.get("attributes"), dict) else None
                if isinstance(value, int) and not isinstance(value, bool):
                    result[str(row["id"])] = value
        return result

    def liked_states(self, ids, *, background=True) -> dict:
        """The heart-state read (K3 section 9.7.2; [WP6-r22]): ``{catalog id: liked}`` for every
        catalog id in ``ids``, from one ``ratings`` read (batches of 100): ``liked = (value == 1)``,
        an id absent from the answer is False. Non-catalog ids are left out and never sent (those
        rows are not in Apple Music). A failed read raises, so the caller keeps ``liked = None``
        (``Checking likes…``) and retries once with the next window (section 9.7.2); the late check
        of a timed-out like (section 5.6.6) is one call with one id."""
        wanted = list(liked_states(ids, {}))
        if not wanted:
            return {}
        return liked_states(wanted, self.ratings(wanted, background=background))

    def _rating(self, song: str):
        return self.ratings([song], background=False).get(song)

    def _await_liked(self, song: str) -> bool:
        """Read the rating every 250 ms (first at +250 ms) until it is 1, for at most 4 s. The
        favourites POST answers 202 = accepted, not done."""
        start = self._now()
        deadline = start + LIKE_CONFIRM_S
        due = start + LIKE_READBACK_S
        while due <= deadline + 1e-9:
            now = self._now()
            if now < due:
                self._sleep(due - now)
            if self._rating(song) == 1:
                return True
            due = max(due + LIKE_READBACK_S, self._now())
        return False

    def like(self, catalog_id) -> dict:
        """Like = the Apple Music Favorite (the star): ``POST /v1/me/favorites?ids[songs]=<id>``
        with no body, then the ratings read-back until the value is 1 (K3 section 9.8.2).
        404 → ``NotCatalog``; no read-back match within 4 s → ``LikeNotConfirmed``.
        Never ``PUT /v1/me/ratings``."""
        song = self._catalog_id(catalog_id)
        try:
            self._send("POST", f"{FAVORITES}?ids[songs]={song}", expected=(200, 202, 204))
        except AppleMusicError as error:
            if error.status == 404:
                raise NotCatalog("This song is not in the Apple Music catalog.", status=404) from None
            if isinstance(error.status, int) and error.status not in (401, 403, 429):
                # Section 9.8.2: 400/405 (our sign-in cannot use the favourites call) and other
                # statuses are `failed`, logged by the status code only.
                _log.warning("Like: Apple Music answered HTTP %d", error.status)
            raise
        if self._await_liked(song):
            return {"liked": True}
        raise LikeNotConfirmed("The like was not confirmed by Apple Music.")

    def unlike(self, catalog_id) -> dict:
        """No unlike request exists ([r2.2] C5-67: Like is add-only, final; the favourites
        ``DELETE`` was refused, 400 / 40012, and the ratings ``DELETE`` never reaches the user's
        devices). The controller refuses a press on a liked row itself (``unlike_unavailable``);
        a call here is a programming error and raises ``UnlikeUnavailable`` before any I/O."""
        raise UnlikeUnavailable("Unfavourite in Music app")

    # ------------------------------------------------------------------ Up next catalog data
    def catalog_songs(self, ids, *, background=True) -> dict:
        """``GET /v1/catalog/{sf}/songs?ids=…`` (≤ ``CATALOG_BATCH`` = 50 per request, the K3
        section 1.2 parse cap; no ``extend=inFavorites``, C5-64) → ``{id: row}``. A found row has ``catalog`` True, ``title``, ``artist``,
        ``album``, ``track_number``, ``disc_number``, ``duration_ms``, ``duration_s``,
        ``art`` ({template, width, height, bgColor, textColor1}), the K4 art keys, ``accent``
        (the ``bgColor`` seed), ``url`` (the album-form share link for ``move_next``, "" when
        Apple gives another form) and ``release_year``. An id the storefront does not return
        is ``{"catalog": False}`` (C5-43)."""
        wanted = []
        for value in ids or ():
            song = self._catalog_id(value)
            if song not in wanted:
                wanted.append(song)
        if not wanted:
            return {}
        storefront = self._get_storefront(background)
        found = {}
        for start in range(0, len(wanted), self.CATALOG_BATCH):
            batch = wanted[start:start + self.CATALOG_BATCH]
            try:
                response = self._get(f"/v1/catalog/{storefront}/songs", params={"ids": ",".join(batch)},
                                     background=background)
            except AppleMusicError as error:
                if error.status == 404:
                    continue
                raise
            for song in response["data"]:
                if not isinstance(song, dict) or str(song.get("id")) not in batch:
                    continue
                attributes = song.get("attributes") if isinstance(song.get("attributes"), dict) else {}
                artwork = attributes.get("artwork") if isinstance(attributes.get("artwork"), dict) else {}
                duration_ms = _int_or_none(attributes.get("durationInMillis"))
                keys = art_keys(artwork)
                found[str(song["id"])] = {
                    "catalog": True, "title": attributes.get("name") or "",
                    "artist": attributes.get("artistName") or "",
                    "album": attributes.get("albumName") or "",
                    "track_number": _int_or_none(attributes.get("trackNumber")),
                    "disc_number": _int_or_none(attributes.get("discNumber")),
                    "duration_ms": duration_ms,
                    "duration_s": round(duration_ms / 1000) if duration_ms is not None else None,
                    "art": {"template": keys["art_template"], "width": _int_or_none(artwork.get("width")),
                            "height": _int_or_none(artwork.get("height")),
                            "bgColor": keys["art_bg"], "textColor1": keys["art_ink"]},
                    **keys, "accent": keys["art_bg"],
                    "url": self._album_form_url(str(song["id"]), attributes.get("url")),
                    "release_year": _year(attributes.get("releaseDate"))}
        return {song: found.get(song, {"catalog": False}) for song in wanted}

    # ------------------------------------------------------------------ Favourite playlists (U7)
    def _playlist_item(self, resource: dict) -> dict:
        attributes = self._check_resource(resource)
        name = attributes.get("name") or ""
        can_edit, has_catalog = attributes.get("canEdit"), attributes.get("hasCatalog")
        return {"id": resource["id"], "title": name or UNTITLED_PLAYLIST, "untitled": not name,
                "artist": attributes.get("curatorName") or "",
                **self._item_art(attributes), "year": None, "track_count": None,
                "kind": "playlist", "available": True, "reason": "", "favourite": True,
                "resource_type": "library-playlists", "_resource": resource,
                "can_edit": can_edit is True, "has_catalog": has_catalog is True,
                "auto": name == FAVORITE_SONGS and can_edit is False and has_catalog is False,
                "last_modified": attributes.get("lastModifiedDate") or ""}

    def _scan(self, path: str, params: dict, background) -> tuple[list, int | None]:
        rows, total = [], None
        for page in self._own_pages(path, params, background=background):
            for row in page["data"]:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                    raise AppleMusicError("Apple Music returned an incomplete library item.")
                rows.append(row)
            meta = page.get("meta") if isinstance(page.get("meta"), dict) else {}
            if total is None:
                total = _int_or_none(meta.get("total"))
        unique = list({row["id"]: row for row in rows}.values())
        return unique, total

    @staticmethod
    def _flag(row):
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        return attributes.get("inFavorites")

    def favourite_playlists(self, *, background=False) -> list[dict]:
        """The favourited library playlists, Favorite Songs included (K3 section 9.8.5, CF section 5).

        1. Fast path ``?limit=100&extend=inFavorites&filter[inFavorites]=true`` (own params
           on every page): accepted only when every page is 200, the result is non-empty and
           every row says ``inFavorites`` true. 401/403 and 429 raise at once (no full scan
           under 429); anything else goes to 2.
        2. Full scan ``?limit=100&extend=inFavorites``: deduped, compared with ``meta.total``
           (one re-scan on a mismatch), every row must carry a boolean flag (else 3).
           "No favourites" is concluded only here.
        3. Ratings fallback ``/v1/me/ratings/library-playlists?ids=`` (value 1; 404 = none).
        4. Folders, only when a listing holds ``library-playlist-folders``.
        Sorted by ``name.casefold()`` then id; unnamed rows last as ``Untitled playlist``.
        """
        chosen = None
        try:
            rows, _ = self._scan(self.PLAYLISTS, {"limit": self.PLAYLISTS_PAGE_LIMIT, "extend": "inFavorites",
                                                  "filter[inFavorites]": "true"}, background)
            playlists = [row for row in rows if row.get("type") == "library-playlists"]
            if playlists and all(self._flag(row) is True for row in playlists) and len(playlists) == len(rows):
                chosen = playlists
        except AppleMusicError as error:
            if error.status in (401, 403, 429):
                raise
        if chosen is None:
            chosen = self._full_scan(background)
        items = [self._playlist_item(row) for row in chosen]
        named = sorted((i for i in items if not i["untitled"]), key=lambda i: (i["title"].casefold(), i["id"]))
        unnamed = sorted((i for i in items if i["untitled"]), key=lambda i: i["id"])
        return named + unnamed

    def _full_scan(self, background) -> list[dict]:
        params = {"limit": self.PLAYLISTS_PAGE_LIMIT, "extend": "inFavorites"}
        rows, total = self._scan(self.PLAYLISTS, params, background)
        if total is not None and total != len(rows):
            rows, total = self._scan(self.PLAYLISTS, params, background)
        playlists = [row for row in rows if row.get("type") == "library-playlists"]
        folders = [row for row in rows if row.get("type") == "library-playlist-folders"]
        if all(isinstance(self._flag(row), bool) for row in playlists):
            chosen = [row for row in playlists if self._flag(row) is True]
        else:
            chosen = self._ratings_fallback(playlists, background)
        if folders:
            chosen += self._walk_folders(folders, background)
        return list({row["id"]: row for row in chosen}.values())

    def _ratings_fallback(self, playlists, background) -> list[dict]:
        liked = set()
        ids = [row["id"] for row in playlists]
        for start in range(0, len(ids), self.RATINGS_BATCH):
            batch = ids[start:start + self.RATINGS_BATCH]
            try:
                response = self._get("/v1/me/ratings/library-playlists", params={"ids": ",".join(batch)},
                                     background=background)
            except AppleMusicError as error:
                if error.status == 404:
                    continue
                raise
            for row in response["data"]:
                attributes = row.get("attributes") if isinstance(row, dict) and isinstance(row.get("attributes"), dict) else {}
                if attributes.get("value") == 1 and row.get("id") in batch:
                    liked.add(row["id"])
        return [row for row in playlists if row["id"] in liked]

    def _walk_folders(self, folders, background, depth=0) -> list[dict]:
        found, pending = [], [row["id"] for row in folders][:50]
        for folder in pending:
            rows, _ = self._scan(f"/v1/me/library/playlist-folders/{quote(folder, safe='')}/children",
                                 {"limit": self.PLAYLISTS_PAGE_LIMIT, "extend": "inFavorites"}, background)
            found += [row for row in rows if row.get("type") == "library-playlists" and self._flag(row) is True]
            inner = [row for row in rows if row.get("type") == "library-playlist-folders"]
            if inner and depth < 8:
                found += self._walk_folders(inner, background, depth + 1)
        return found

    # ------------------------------------------------------------------ playlist meta (C5-28)
    @staticmethod
    def _track_art(track: dict) -> dict:
        """Art descriptor of one playlist track: the catalog song's artwork (with bgColor and
        textColor1) when the ``catalog`` relationship carries it, else the library artwork."""
        related = track.get("relationships", {}).get("catalog", {}) if isinstance(track.get("relationships"), dict) else {}
        data = related.get("data") if isinstance(related, dict) else None
        for source in ((data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}), track):
            attributes = source.get("attributes") if isinstance(source.get("attributes"), dict) else {}
            keys = art_keys(attributes.get("artwork"))
            if keys["art_template"]:
                return keys
        return art_keys(None)

    @staticmethod
    def _track_duration(track: dict):
        for source in (track, *(track.get("relationships", {}).get("catalog", {}).get("data") or [])):
            attributes = source.get("attributes") if isinstance(source, dict) and isinstance(source.get("attributes"), dict) else {}
            value = _int_or_none(attributes.get("durationInMillis"))
            if value is not None:
                return value
        return None

    def playlist_meta(self, playlist_id: str, *, duration: bool = False, last_modified=None,
                      background: bool = True) -> dict:
        """First tracks page of a library playlist (``?limit=50&include=catalog``, ``TRACKS_PAGE_LIMIT``)
        → ``count`` (``meta.total``), ``mosaic`` (the first 4 distinct albums **with art** among the
        first ``MOSAIC_SCAN_TRACKS`` = 100 tracks, in track order; fewer than 4 → the first one only;
        none → []), ``art_state`` (``mosaic`` / ``single`` / ``generated``), ``first_art``,
        ``accent`` (its ``bgColor`` seed) and, only when ``duration`` is asked (the focused
        playlist), ``duration_ms`` over every page, cached by (id, last_modified). A 404 ``40403``
        is an empty playlist (``empty`` True). The page size is the K3 section 1.2 parse cap; a
        second page is read for the mosaic only while fewer than 4 albums were found in the tracks
        read so far (the same 100-track window a 100-row first page gave).

        Failures after the first page (WP6-GIL-D3 and D5, gil-parse-hold.md): a window page that cannot be read (anything
        but a 401/403) ends the window of a neighbour, which keeps what the pages read so far
        gave (the mosaic found so far; ``count`` from ``meta.total``, else None), as the single
        100-row read did. For the focused playlist (``duration``) it still raises, because its
        duration needs every page. The duration reads up to ``META_MAX_TRACKS`` tracks (10,000,
        the reach 100 pages of 100 had): a longer playlist, or one whose remaining pages cannot all
        be read, keeps its count and mosaic with ``duration_ms`` None. A partial sum is never
        returned or cached."""
        if not isinstance(playlist_id, str) or not playlist_id or len(playlist_id) > 128:
            raise AppleMusicError("This playlist is unavailable.")
        path = f"{self.PLAYLISTS}/{quote(playlist_id, safe='')}/tracks"
        params = {"limit": self.TRACKS_PAGE_LIMIT, "include": "catalog"}
        empty = {"id": playlist_id, "count": 0, "mosaic": [], "art_state": "generated", "first_art": None,
                 "accent": 0, "duration_ms": 0 if duration else None, "empty": True}
        # The page bound follows the page size, so the duration keeps its 10,000-track reach.
        bound = max(self.MAX_TRACK_PAGES, -(-self.META_MAX_TRACKS // self.TRACKS_PAGE_LIMIT))
        pages = self._own_pages(path, params, background=background, max_pages=bound)
        try:
            first = next(pages)
        except AppleMusicError as error:
            if error.status == 404 and error.code == "40403":
                return empty
            raise
        meta = first.get("meta") if isinstance(first.get("meta"), dict) else {}
        count = _int_or_none(meta.get("total"))

        def window_page():
            """The next page of the 100-track window; None at the end or, for a neighbour, when
            it cannot be read (the generator is finished after a failure)."""
            try:
                return next(pages, None)
            except AppleMusicError as error:
                if duration or error.status in (401, 403):
                    raise
                return None

        distinct, seen, scanned, fetched, page = [], set(), 0, [first], first
        while True:
            for track in page["data"]:
                if scanned >= self.MOSAIC_SCAN_TRACKS:
                    break
                scanned += 1
                if not isinstance(track, dict):
                    continue
                keys = self._track_art(track)
                if not keys["art_template"]:
                    continue
                album = keys["art_template"]
                if album in seen:
                    continue
                seen.add(album)
                distinct.append(keys)
                if len(distinct) == 4:
                    break
            if len(distinct) == 4 or scanned >= self.MOSAIC_SCAN_TRACKS or not page.get("next"):
                break
            page = window_page()
            if page is None:
                break
            fetched.append(page)
        if count is None:
            # No meta.total: as with a 100-row first page, the count is known when the playlist
            # ends within its first MOSAIC_SCAN_TRACKS tracks.
            ended = True
            while fetched[-1].get("next") and sum(len(done["data"]) for done in fetched) < self.MOSAIC_SCAN_TRACKS:
                page = window_page()
                if page is None:
                    ended = False
                    break
                fetched.append(page)
            if ended and not fetched[-1].get("next"):
                count = sum(len(done["data"]) for done in fetched)
        mosaic = distinct if len(distinct) == 4 else distinct[:1]
        first_art = distinct[0] if distinct else None
        total_ms = None
        if duration and (count is None or count <= self.META_MAX_TRACKS):
            total_ms = self._playlist_duration((playlist_id, last_modified), fetched, pages)
        return {"id": playlist_id, "count": count, "mosaic": mosaic,
                "art_state": "mosaic" if len(mosaic) == 4 else ("single" if mosaic else "generated"),
                "first_art": first_art, "accent": first_art["art_bg"] if first_art else 0,
                "duration_ms": total_ms, "empty": count == 0}

    def _playlist_duration(self, cache_key, fetched, pages):
        """``duration_ms`` of the focused playlist: the pages already ``fetched`` plus every
        remaining page of ``pages``, cached by ``cache_key`` = (id, last_modified) when
        last_modified is known. None when the list cannot be read to its end:

        - past the ``META_MAX_TRACKS`` page bound, or an offset that does not advance
          (``MusicUnavailable``): the same list fails the same way, so the None is cached too and
          a refocus sends no further requests for it;
        - a page that fails (a 429, 5xx, timeout or broken link): not cached, the next focus asks
          again.

        A 401/403 raises."""
        with self._resolve_lock:
            if cache_key in self._duration_cache:
                return self._duration_cache[cache_key]
        total_ms = sum(self._track_duration(t) or 0 for done in fetched for t in done["data"]
                       if isinstance(t, dict))
        try:
            for page in pages:
                total_ms += sum(self._track_duration(t) or 0 for t in page["data"] if isinstance(t, dict))
        except MusicUnavailable:
            total_ms = None
        except AppleMusicError as error:
            if error.status in (401, 403):
                raise
            return None
        if cache_key[1] is not None:
            with self._resolve_lock:
                self._duration_cache[cache_key] = total_ms
                while len(self._duration_cache) > 256:
                    self._duration_cache.popitem(last=False)
        return total_ms
