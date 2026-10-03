"""H5 parse bench: how long the service lanes' JSON and XML parses hold the GIL (DESKTOP_STAGE
§4.7.3 and §6.6 H5; CONTROL_CENTER_V5 §1.2; [G1] G1-5).

    cd app
    .venv\\Scripts\\python.exe -I ..\\..\\tools\\stage_checks\\gil_parse_hold.py [--reps 20] [--json PATH]
                                 [--recorded DIR] [--only TEXT] [--quick] [--no-save]

Headless and offline. Nothing is shown, fetched or sent: no Sonos, no Apple Music, no serial port,
no settings, no credentials. Every network entry point that requests and soco use is replaced by
one that raises before the first row runs. The one file written is the synthetic queue-recovery
record of the "whole save" rows (DPAPI-protected, as the app writes it), into a temporary folder
removed when the run ends (``--no-save`` skips those rows). The fixtures are synthetic, built
from seeded generators in the shapes the two services return (sizes below). ``--recorded DIR``
adds any ``*.json`` or ``*.xml`` response bodies saved during a supervised live check; their
contents are never printed.

The rule (K4 §4.7.3, tightened by G1-5): while an overlay can take input, no thread holds the GIL
for more than about 2 ms, and 1 ms per C call during an animation episode is the design target.
``json.loads`` (``requests.Response.json``) and ElementTree's expat parser (soco's
``unwrap_arguments``) parse a whole body in one C call. lxml (soco's DIDL-Lite and ZoneGroupState
parses) releases the GIL while libxml2 parses, which this bench checks too.

Each row runs 20 times (``--reps``) in two ways:

- **call**: timed on one thread with nothing else running. For a parse that is one GIL-holding C
  call (``json.loads``, expat; rows of kind ``call``), this time *is* the hold.
- **probe**: the row runs on a worker thread while a probe thread sleeps 0.5 ms at a time and
  records how late it gets the GIL back (``timeBeginPeriod(1)`` and a 1 ms switch interval, as the
  app sets them, K4 §4.7.2). Each repetition's reading is the probe's largest lateness while that
  repetition ran. The idle probe is already about 0.5 ms late (the timer), a probe that wakes
  part-way through a hold sees only the rest of it, and pure-Python work reads 1-2 ms above idle
  (the switch interval, rounded up to the timer tick), which is how the interpreter shares the
  GIL, not a hold.

Two reference rows calibrate the probe: pure Python for about 5 ms (what "no C call holds" reads)
and one ``sorted()`` C call of about 2 ms (what a 2 ms hold reads).

Verdicts:

- ``call`` rows (one C call): ``OK`` when the call p95 is at most 1.0 ms (the design target),
  ``<2ms`` at most 2.0 ms (G1-5's ceiling), ``HOLD`` above.
- ``path`` rows (a whole client path: the parse plus the Python that walks it) and ``lxml`` rows
  (libxml2 parses with the GIL released): ``py`` when the probe p95 stays within the pure-Python
  reference's p95 + 1.0 ms (nothing hidden in the path holds much longer than the interpreter's
  own switching), ``HOLD?`` otherwise. Their parse holds are the ``call`` rows of the same size.

The caps for K3 §1.2 follow from the ``call`` rows with a margin of 2 (``MARGIN``): the largest
size whose hold has a p50 of at most 0.5 ms (a real response up to twice the synthetic fixture's
size still parses within 1 ms) and a p95 of at most 1.0 ms (the tail on this shared PC, where
another process can preempt the thread that holds the GIL, stays within the design target).
The probe cannot tell a C call under about 1.5 ms from the interpreter's own switching on
Windows: the waiting thread's 1 ms timed wait rounds up to the timer tick, so the pure-Python
reference already reads about 2.5 ms. The ``call`` rows are the measurement; the probe confirms
that nothing inside a whole path holds longer.

Fixture sizes (each row prints its body's bytes): an Apple catalog song about 1.5 KB (the default
``albums`` and ``artists`` relationships, no ``extend``); a library track with its catalog song
(``include=catalog``) about 2.3 KB; a library playlist (``extend=inFavorites``) about 0.65 KB; a
Recently Added album about 0.55 KB; a rating 0.1 KB; a Sonos queue row about 0.5 KB of DIDL-Lite
(0.65 KB escaped in the SOAP envelope); a ZoneGroupState member about 0.7 KB.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
import tempfile
import threading
import time
from xml.sax.saxutils import escape, quoteattr

HERE = os.path.dirname(os.path.abspath(__file__))
ND = os.path.normpath(os.path.join(HERE, "..", "..", "app"))
if ND not in sys.path:
    sys.path.insert(0, ND)

PROBE_SLEEP_S = 0.0005
TARGET_MS = 1.0          # K4 §4.7.3: 1 ms per C call during an episode (the design target)
CEILING_MS = 2.0         # [G1] G1-5: no hold over ~2 ms while an overlay can take input
MARGIN = 2.0             # caps: a real body up to MARGIN x the fixture still parses within TARGET_MS
PY_SLACK_MS = TARGET_MS  # path rows: probe p95 within the pure-Python reference's p95 + this
SEED = 20260926


# ----------------------------------------------------------------------------------- offline guard
class NetworkBlocked(RuntimeError):
    pass


def _refuse(*_args, **_kwargs):
    raise NetworkBlocked("gil_parse_hold is offline: a network call was attempted")


def block_network():
    """Every way requests (Apple) and soco (Sonos) reach the network raises from here on."""
    import socket
    import requests
    import requests.adapters
    import urllib3
    requests.adapters.HTTPAdapter.send = _refuse
    requests.Session.request = _refuse
    for name in ("get", "post", "put", "patch", "delete", "head", "request", "options"):
        setattr(requests, name, _refuse)
    urllib3.connectionpool.HTTPConnectionPool.urlopen = _refuse
    socket.create_connection = _refuse
    socket.socket.connect = _refuse
    socket.socket.connect_ex = _refuse
    socket.socket.sendto = _refuse


# ----------------------------------------------------------------------------------- fixtures
WORDS = ("love", "night", "running", "hill", "heart", "light", "river", "summer", "dream", "city", "blue",
         "gold", "fire", "rain", "moon", "ghost", "wild", "time", "dance", "home", "paper", "glass",
         "echo", "silver", "ocean", "stone", "velvet", "signal", "arcade", "neon")
ACCENTED = ("Copper Sun", "Linnéa Holm", "North of June", "Café Tacvba", "Motörhead", "Renée Lys", "Mañana", "Coração",
            "Jóga", "Maré Alta", "Ça plane pour moi")
CJK = ("夜に駆ける", "紅蓮華", "アイドル", "우리의 밤", "少年時代", "春よ、来い")


def _title(rng, words=(2, 5)):
    kind = rng.random()
    if kind < 0.08:
        return rng.choice(CJK)
    base = " ".join(rng.choice(WORDS) for _ in range(rng.randint(*words))).title()
    if kind < 0.20:
        base = rng.choice(ACCENTED) + " " + base
    if kind > 0.85:
        base += rng.choice((" (Remastered 2011)", " [feat. Mira Vale]", " (Live at Wembley 1986)",
                            " - Single Version", " (A Deal With God)"))
    return base


def _hex(rng, n):
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _uuid(rng):
    return f"{_hex(rng, 8)}-{_hex(rng, 4)}-{_hex(rng, 4)}-{_hex(rng, 4)}-{_hex(rng, 12)}"


def _art_url(rng, library=False):
    host = "is1-ssl.mzstatic.com"
    a, b, c = _hex(rng, 2), _hex(rng, 2), _hex(rng, 2)
    folder = f"Music{rng.randint(100, 221)}/v4/{a}/{b}/{c}/{a}{b}{c}{_hex(rng, 2)}-{_uuid(rng)[9:]}"
    leaf = f"{rng.randint(10 ** 11, 10 ** 12 - 1)}.jpg" if not library else f"{_uuid(rng)}.jpg"
    return f"https://{host}/image/thumb/{folder}/{leaf}/{{w}}x{{h}}bb.jpg"


def _colour(rng):
    return _hex(rng, 6)


def catalog_song(rng, song_id, album_id, sf="us"):
    """One catalog ``songs`` resource as ``GET /v1/catalog/{sf}/songs?ids=`` returns it (no
    ``extend``, K3 §9.8.4 rev 4), with the default ``albums`` and ``artists`` relationships."""
    title, album, artist = _title(rng), _title(rng, (1, 3)), _title(rng, (1, 2))
    artist_id = str(rng.randint(10 ** 8, 10 ** 9))
    slug = "-".join(album.lower().split()[:4]) or "album"
    return {
        "id": song_id, "type": "songs", "href": f"/v1/catalog/{sf}/songs/{song_id}",
        "attributes": {
            "albumName": album, "genreNames": [rng.choice(("Alternative", "Pop", "Rock", "Electronic")), "Music"],
            "trackNumber": rng.randint(1, 14), "releaseDate": f"{rng.randint(1965, 2025)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}",
            "durationInMillis": rng.randint(120_000, 420_000), "isrc": f"GB{_hex(rng, 3).upper()}{rng.randint(10 ** 6, 10 ** 7)}",
            "artwork": {"width": 3000, "height": 3000, "url": _art_url(rng), "bgColor": _colour(rng),
                        "textColor1": _colour(rng), "textColor2": _colour(rng), "textColor3": _colour(rng),
                        "textColor4": _colour(rng)},
            "composerName": f"{_title(rng, (1, 2))} & {_title(rng, (1, 2))}",
            "url": f"https://music.apple.com/{sf}/album/{slug}/{album_id}?i={song_id}",
            "playParams": {"id": song_id, "kind": "song"}, "discNumber": 1, "hasCredits": False,
            "isAppleDigitalMaster": rng.random() < 0.5, "hasLyrics": True, "name": title,
            "previews": [{"url": f"https://audio-ssl.itunes.apple.com/itunes-assets/AudioPreview{rng.randint(100, 221)}/v4/"
                                 f"{_hex(rng, 2)}/{_hex(rng, 2)}/{_hex(rng, 2)}/{_uuid(rng)}/mzaf_{rng.randint(10 ** 18, 10 ** 19)}"
                                 f".plus.aac.p.m4a"}],
            "artistName": artist, "audioLocale": "en-US",
            "audioTraits": ["atmos", "lossless", "lossy-stereo", "spatial"][:rng.randint(1, 4)],
            "hasTimeSyncedLyrics": True, "isVocalAttenuationAllowed": True, "isMasteredForItunes": False,
            **({"contentRating": "explicit"} if rng.random() < 0.15 else {}),
        },
        "relationships": {
            "albums": {"href": f"/v1/catalog/{sf}/songs/{song_id}/albums",
                       "data": [{"id": album_id, "type": "albums", "href": f"/v1/catalog/{sf}/albums/{album_id}"}]},
            "artists": {"href": f"/v1/catalog/{sf}/songs/{song_id}/artists",
                        "data": [{"id": artist_id, "type": "artists", "href": f"/v1/catalog/{sf}/artists/{artist_id}"}]},
        },
    }


def library_song(rng, index):
    """One ``library-songs`` row of a ``/tracks?include=catalog`` page (K3 §9.8.7), carrying its
    catalog song in ``relationships.catalog``."""
    song_id = str(1_400_000_000 + rng.randint(0, 99_999_999))
    album_id = str(1_400_000_000 + rng.randint(0, 99_999_999))
    catalog = catalog_song(rng, song_id, album_id)
    library_id = "i." + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789")
                                for _ in range(15))
    a = catalog["attributes"]
    return {
        "id": library_id, "type": "library-songs", "href": f"/v1/me/library/songs/{library_id}",
        "attributes": {
            "albumName": a["albumName"], "discNumber": 1, "genreNames": a["genreNames"][:1], "hasLyrics": True,
            "trackNumber": a["trackNumber"], "releaseDate": a["releaseDate"], "durationInMillis": a["durationInMillis"],
            "name": a["name"], "artistName": a["artistName"], "hasCredits": False,
            "artwork": {"width": 1200, "height": 1200, "url": _art_url(rng, library=True)},
            "playParams": {"id": library_id, "kind": "song", "isLibrary": True, "reporting": True,
                           "catalogId": song_id, "reportingId": song_id},
            "dateAdded": f"20{rng.randint(15, 26)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}T1{rng.randint(0, 9)}:2{rng.randint(0, 9)}:00Z",
        },
        "relationships": {"catalog": {"href": f"/v1/me/library/songs/{library_id}/catalog", "data": [catalog]}},
    }


def library_playlist(rng, index):
    """One ``library-playlists`` row of ``/v1/me/library/playlists?limit=…&extend=inFavorites``."""
    pid = "p." + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789") for _ in range(15))
    gid = "pl.u-" + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789") for _ in range(15))
    attributes = {
        "canEdit": rng.random() < 0.8, "name": _title(rng, (1, 4)), "isPublic": rng.random() < 0.2,
        "hasCatalog": rng.random() < 0.9, "playParams": {"id": pid, "kind": "playlist", "isLibrary": True, "globalId": gid},
        "dateAdded": f"20{rng.randint(15, 26)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}T0{rng.randint(0, 9)}:1{rng.randint(0, 9)}:00Z",
        "lastModifiedDate": f"20{rng.randint(15, 26)}-0{rng.randint(1, 9)}-2{rng.randint(0, 8)}T1{rng.randint(0, 9)}:0{rng.randint(0, 9)}:00Z",
        "inFavorites": rng.random() < 0.3,
        "artwork": {"width": None, "height": None, "url": _art_url(rng, library=True)},
    }
    if rng.random() < 0.4:
        attributes["description"] = {"standard": " ".join(rng.choice(WORDS) for _ in range(rng.randint(4, 24)))}
    return {"id": pid, "type": "library-playlists", "href": f"/v1/me/library/playlists/{pid}", "attributes": attributes}


def library_album(rng, index):
    """One ``library-albums`` row of Recently Added (K3 §9.8.6)."""
    lid = "l." + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789") for _ in range(7))
    return {"id": lid, "type": "library-albums", "href": f"/v1/me/library/albums/{lid}",
            "attributes": {"artistName": _title(rng, (1, 2)), "genreNames": ["Alternative"], "name": _title(rng, (1, 4)),
                           "playParams": {"id": lid, "kind": "album", "isLibrary": True},
                           "releaseDate": f"{rng.randint(1965, 2025)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}",
                           "trackCount": rng.randint(4, 24), "dateAdded": "2026-09-1" + str(rng.randint(0, 9)) + "T10:00:00Z",
                           "artwork": {"width": 1200, "height": 1200, "url": _art_url(rng, library=True),
                                       "bgColor": _colour(rng), "textColor1": _colour(rng)}}}


def apple_page(rows, *, next_path=None, total=None):
    page = {"data": rows}
    if next_path:
        page["next"] = next_path
    if total is not None:
        page["meta"] = {"total": total}
    return json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def catalog_songs_body(n, rng):
    rows = [catalog_song(rng, str(1_400_000_000 + i * 37), str(1_300_000_000 + i // 12)) for i in range(n)]
    return apple_page(rows), [row["id"] for row in rows]


def tracks_page_body(n, rng, total=None):
    rows = [library_song(rng, i) for i in range(n)]
    return apple_page(rows, total=total if total is not None else n)


def playlists_page_body(n, rng):
    return apple_page([library_playlist(rng, i) for i in range(n)], total=n)


def recent_page_body(n, rng):
    return apple_page([library_album(rng, i) for i in range(n)], total=500)


def ratings_body(ids):
    return apple_page([{"id": i, "type": "ratings", "href": f"/v1/me/ratings/songs/{i}", "attributes": {"value": 1}}
                       for i in ids])


DIDL_OPEN = ('<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
             'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">')


def didl_item(rng, row):
    """One Sonos queue row (``Browse(Q:0)``) for an Apple Music song (sid 204), as Sonos sends it."""
    song = 1_400_000_000 + rng.randint(0, 99_999_999)
    uri = f"x-sonos-http:song%3a{song}.mp4?sid=204&flags=8224&sn=3"
    art = f"/getaa?s=1&u=x-sonos-http%3asong%253a{song}.mp4%3fsid%3d204%26flags%3d8224%26sn%3d3"
    duration = f"0:0{rng.randint(2, 6)}:{rng.randint(10, 59)}"
    return (f'<item id="Q:0/{row}" parentID="Q:0" restricted="true">'
            f'<res protocolInfo="sonos.com-http:*:audio/mp4:*" duration="{duration}">{escape(uri)}</res>'
            f'<upnp:albumArtURI>{escape(art)}</upnp:albumArtURI><dc:title>{escape(_title(rng))}</dc:title>'
            f'<upnp:class>object.item.audioItem.musicTrack</upnp:class><dc:creator>{escape(_title(rng, (1, 2)))}</dc:creator>'
            f'<upnp:album>{escape(_title(rng, (1, 3)))}</upnp:album></item>')


def soap_envelope(action, service, fields):
    body = "".join(f"<{name}>{value}</{name}>" for name, value in fields)
    return ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action}Response xmlns:u="urn:schemas-upnp-org:service:{service}:1">{body}</u:{action}Response>'
            '</s:Body></s:Envelope>').encode("utf-8")


def browse_body(n, rng, start=0, total=None):
    didl = DIDL_OPEN + "".join(didl_item(rng, start + i + 1) for i in range(n)) + "</DIDL-Lite>"
    fields = (("Result", escape(didl, {'"': "&quot;"})), ("NumberReturned", n),
              ("TotalMatches", total if total is not None else max(n, 100)), ("UpdateID", 187))
    return soap_envelope("Browse", "ContentDirectory", fields), didl


def _member(rng, index, satellite=False):
    uid = f"RINCON_{_hex(rng, 12).upper()}01400"
    ip = f"192.0.2.{10 + index}"
    attrs = {"UUID": uid, "Location": f"http://{ip}:1400/xml/device_description.xml",
             "ZoneName": _title(rng, (1, 2)), "Icon": "", "Configuration": "1",
             "SoftwareVersion": "85.0-65020", "SWGen": "2", "MinCompatibleVersion": "84.0-00000",
             "LegacyCompatibleVersion": "58.0-00000", "BootSeq": str(rng.randint(10, 400)),
             "TVConfigurationError": "0", "HdmiCecAvailable": "0", "WirelessMode": "0", "WirelessLeafOnly": "0",
             "ChannelFreq": "2437", "BehindWifiExtender": "0", "WifiEnabled": "1", "EthLink": "0",
             "Orientation": "0", "RoomCalibrationState": "4", "SecureRegState": "3", "VoiceConfigState": "0",
             "MicEnabled": "0", "AirPlayEnabled": "1", "IdleState": "1", "MoreInfo": "",
             "SSLPort": "1443", "HHSSLPort": "1843"}
    if satellite:
        attrs["Invisible"] = "1"
        attrs["HTSatChanMapSet"] = f"{uid}:LF,RF;{uid}:SW"
    return uid, attrs


def zgs_body(members, rng):
    """GetZoneGroupState for a household of ``members`` players: groups of 1-3, one home
    theatre with two satellites and a Sub, which soco normalises with lxml and XSLT."""
    groups, i = [], 0
    while i < members:
        size = min(members - i, rng.choice((1, 1, 2, 3)))
        coordinator, parts = None, []
        for k in range(size):
            uid, attrs = _member(rng, i + k)
            coordinator = coordinator or uid
            sats = ""
            if i == 0 and k == 0 and members >= 4:
                sats = "".join("<Satellite " + " ".join(f"{a}={quoteattr(v)}" for a, v in _member(rng, 60 + s, True)[1].items())
                               + "/>" for s in range(3))
            parts.append("<ZoneGroupMember " + " ".join(f"{a}={quoteattr(v)}" for a, v in attrs.items())
                         + (f">{sats}</ZoneGroupMember>" if sats else "/>"))
        groups.append(f'<ZoneGroup Coordinator="{coordinator}" ID="{coordinator}:{rng.randint(100, 999)}">'
                      + "".join(parts) + "</ZoneGroup>")
        i += size
    xml = "<ZoneGroupState><ZoneGroups>" + "".join(groups) + "</ZoneGroups><VanishedDevices></VanishedDevices></ZoneGroupState>"
    return soap_envelope("GetZoneGroupState", "ZoneGroupTopology", (("ZoneGroupState", escape(xml, {'"': "&quot;"})),)), xml


def ledger_file(rng, base_songs, playnext_blocks):
    """queue-ledger.json with one room: a base segment of ``base_songs`` ids and
    ``playnext_blocks`` Play-next segments of 1-20 ids (K3 §9.7.3)."""
    def segment(kind, ids, start_row=None):
        seg = {"kind": kind, "name": _title(rng, (1, 4)), "artist": _title(rng, (1, 2)), "year": 1985,
               "library_id": "p." + _hex(rng, 15), "art_template": _art_url(rng), "accent": rng.randint(0, 0xFFFFFF),
               "song_ids": ids, "favourite": False, "auto": False, "created_at": 1_790_000_000.0}
        if start_row is not None:
            seg["start_row"] = start_row
        return seg
    base = segment("playlist", [str(1_400_000_000 + rng.randint(0, 99_999_999)) for _ in range(base_songs)])
    blocks = [segment("playnext", [str(1_400_000_000 + rng.randint(0, 99_999_999)) for _ in range(rng.randint(1, 20))],
                      rng.randint(1, 100)) for _ in range(playnext_blocks)]
    return {"version": 1, "rooms": {"RINCON_000E58BENCH01400": {"base": base, "playnext": blocks}}}




def recovery_snapshot(rng, rows):
    """The queue-recovery record ``SonosAdapter._save_recovery`` hands to ``CredentialStore.save``
    before a start replaces a queue of ``rows`` rows (serialised there with one ``json.dumps``)."""
    items = []
    for row in range(rows):
        item = didl_item(rng, row + 1)
        items.append({"title": _title(rng), "uri": "x-sonos-http:song%3a1445981467.mp4?sid=204&flags=8224&sn=3",
                      "metadata": DIDL_OPEN + item + "</DIDL-Lite>"})
    return {"room_uid": "RINCON_000E58BENCH01400", "coordinator_uid": "RINCON_000E58BENCH01400",
            "group_revision": _hex(rng, 24), "queue_revision": "187", "items": items,
            "track": {"title": "x", "artist": "y", "album": "z", "position": "0:01:02", "duration": "0:04:58",
                      "uri": "x-sonos-http:song%3a1445981467.mp4", "playlist_position": "3", "metadata": ""},
            "transport": {"current_transport_state": "PLAYING", "current_transport_status": "OK",
                          "current_transport_speed": "1"}, "play_mode": "NORMAL"}


# ----------------------------------------------------------------------------------- measuring
def _time_period(on):
    try:
        import ctypes
        winmm = ctypes.windll.winmm
        (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
    except Exception:
        pass


def _pct(values, q):
    values = sorted(values)
    if not values:
        return 0.0
    return values[min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))]


def baseline(duration_s=0.4):
    late = []
    end = time.perf_counter() + duration_s
    while time.perf_counter() < end:
        t = time.perf_counter()
        time.sleep(PROBE_SLEEP_S)
        late.append(max(0.0, (time.perf_counter() - t - PROBE_SLEEP_S) * 1000.0))
    return {"late_p50_ms": round(_pct(late, 0.5), 3), "late_p95_ms": round(_pct(late, 0.95), 3),
            "late_p99_ms": round(_pct(late, 0.99), 3), "late_max_ms": round(max(late), 3), "samples": len(late)}


def measure_call(op, reps, warm=2):
    for _ in range(warm):
        op()
    durs = []
    for _ in range(reps):
        t = time.perf_counter()
        op()
        durs.append((time.perf_counter() - t) * 1000.0)
    return durs


def measure_probe(op, reps, warm=1):
    """Per repetition: the probe's largest lateness while it ran (the longest GIL wait it saw)."""
    started, done = threading.Event(), threading.Event()
    spans = []

    def work():
        for _ in range(warm):
            op()
        started.set()
        time.sleep(0.002)
        for _ in range(reps):
            t0 = time.perf_counter()
            op()
            spans.append((t0, time.perf_counter()))
            time.sleep(0.001)           # a gap between repetitions, so each reading is its own
        done.set()

    samples = []
    worker = threading.Thread(target=work, name="parse-bench-worker", daemon=True)
    worker.start()
    started.wait()
    while not done.is_set():
        t = time.perf_counter()
        time.sleep(PROBE_SLEEP_S)
        now = time.perf_counter()
        samples.append((t + PROBE_SLEEP_S, max(0.0, (now - t - PROBE_SLEEP_S) * 1000.0)))
    worker.join()
    holds = []
    for t0, t1 in spans:
        inside = [late for wake, late in samples if t0 - 0.0002 <= wake <= t1]
        holds.append(max(inside) if inside else 0.0)
    return holds, len(samples)


def run_row(name, op, reps, meta):
    call = measure_call(op, reps)
    probe, samples = measure_probe(op, reps)
    return {"name": name, **meta,
            "call_p50_ms": round(_pct(call, 0.5), 3), "call_p95_ms": round(_pct(call, 0.95), 3),
            "call_max_ms": round(max(call), 3),
            "probe_p95_ms": round(_pct(probe, 0.95), 3), "probe_max_ms": round(max(probe), 3),
            "probe_samples": samples, "reps": reps}


def judge(row, python_ref_p95):
    """``call`` rows: the call time is the hold. ``path``/``lxml`` rows: the probe against the
    pure-Python reference (``py`` = nothing holds longer than the interpreter's switch)."""
    if row["kind"] in ("call", "reference-call"):
        row["hold_p95_ms"] = row["call_p95_ms"]
        hold = row["hold_p95_ms"]
        row["verdict"] = "OK" if hold <= TARGET_MS else ("<2ms" if hold <= CEILING_MS else "HOLD")
    elif row["kind"] == "reference-python":
        row["hold_p95_ms"] = None
        row["verdict"] = "ref"
    else:
        row["hold_p95_ms"] = None
        row["verdict"] = "py" if row["probe_p95_ms"] <= python_ref_p95 + PY_SLACK_MS else "HOLD?"
    return row


# ----------------------------------------------------------------------------------- the rows
def _response(body, content_type):
    """A real ``requests.Response`` around ``body``: ``.json()`` and ``.text`` run the code the
    app runs (the charset comes from the header, as Apple's and Sonos's responses carry one)."""
    from requests.models import Response
    from requests.structures import CaseInsensitiveDict
    from requests.utils import get_encoding_from_headers
    response = Response()
    response.status_code = 200
    response._content = body
    response._content_consumed = True
    response.headers = CaseInsensitiveDict({"Content-Type": content_type, "Content-Length": str(len(body))})
    response.encoding = get_encoding_from_headers(response.headers)
    return response


class _Session:
    """A requests-like session that answers every GET with one prepared ``requests.Response``."""

    def __init__(self, response_for):
        self.response_for = response_for

    def get(self, url, params=None, **_kwargs):
        return self.response_for(url, params or {})

    def request(self, *_args, **_kwargs):
        raise NetworkBlocked("the bench session only answers GETs")


JSON_TYPE = "application/json;charset=utf-8"
XML_TYPE = 'text/xml; charset="utf-8"'


def reference_rows():
    """Calibration: pure Python (no C call holds) and one ~2 ms GIL-holding C call."""
    loops = 60_000

    def python_work(n=None):
        total = 0
        for i in range(n or loops):
            total += i & 7
        return total
    t = time.perf_counter()
    python_work(60_000)
    per = max(1e-9, time.perf_counter() - t) / 60_000
    loops = max(10_000, int(0.005 / per))
    data = list(range(400_000))
    random.Random(SEED).shuffle(data)
    t = time.perf_counter()
    sorted(data)
    size = max(10_000, min(len(data), int(len(data) * 0.002 / max(1e-6, time.perf_counter() - t))))
    chunk = data[:size]
    return [("reference: pure Python, about 5 ms", python_work,
             {"lane": "-", "parse": "-", "kind": "reference-python", "size": loops, "bytes": 0}),
            ("reference: one sorted() C call, about 2 ms", lambda c=chunk: sorted(c),
             {"lane": "-", "parse": "-", "kind": "reference-call", "size": size, "bytes": 0})]


def apple_rows(rng, quick):
    """(name, op, meta) for every Apple Music parse of K3 §1.2's table."""
    from control_center.apple_music import AppleMusicClient
    creds = {"developer_token": "bench-not-a-token", "music_user_token": "bench-not-a-token"}
    storefront = _response(apple_page([{"id": "us", "type": "storefronts"}]), JSON_TYPE)
    rows = []
    for n in ((300, 100, 60, 50, 25, 21) if not quick else (300, 50)):
        body, ids = catalog_songs_body(n, rng)
        response = _response(body, JSON_TYPE)
        rows.append((f"apple catalog_songs ids={n}: Response.json()", response.json,
                     {"lane": "lookahead", "parse": "json", "kind": "call", "size": n, "bytes": len(body)}))
        if n in (300, 50):
            client = AppleMusicClient(creds, session=_Session(
                lambda url, params, r=response, s=storefront: s if url.endswith("/storefront") else r))
            client.CATALOG_BATCH = n
            rows.append((f"apple catalog_songs ids={n}: client path (json + {n} rows)",
                         lambda c=client, i=ids: c.catalog_songs(i),
                         {"lane": "lookahead", "parse": "json", "kind": "path", "size": n, "bytes": len(body)}))
    for n in ((100, 50, 25) if not quick else (100, 50)):
        body = tracks_page_body(n, rng)
        response = _response(body, JSON_TYPE)
        rows.append((f"apple tracks page limit={n} include=catalog: Response.json()", response.json,
                     {"lane": "library/lookahead", "parse": "json", "kind": "call", "size": n, "bytes": len(body)}))
        if n in (100, 50):
            client = AppleMusicClient(creds, session=_Session(lambda url, params, r=response: r))
            client.TRACKS_PAGE_LIMIT = n
            item = {"id": "p.BENCH", "kind": "playlist", "available": True, "track_count": n}

            def resolve(c=client, it=item):
                c.evict_resolved(it)
                return c.resolve(it, background=True)
            rows.append((f"apple resolve limit={n}: client path (json + {n} tracks)", resolve,
                         {"lane": "library/lookahead", "parse": "json", "kind": "path", "size": n, "bytes": len(body)}))
    for n in ((100, 50, 25) if not quick else (100,)):
        body = playlists_page_body(n, rng)
        rows.append((f"apple playlists page limit={n} extend=inFavorites: Response.json()",
                     _response(body, JSON_TYPE).json,
                     {"lane": "library/lookahead", "parse": "json", "kind": "call", "size": n, "bytes": len(body)}))
    body = recent_page_body(25, rng)
    rows.append(("apple Recently Added limit=25: Response.json()", _response(body, JSON_TYPE).json,
                 {"lane": "library/lookahead", "parse": "json", "kind": "call", "size": 25, "bytes": len(body)}))
    body = ratings_body([str(1_400_000_000 + i) for i in range(100)])
    rows.append(("apple ratings ids=100: Response.json()", _response(body, JSON_TYPE).json,
                 {"lane": "lookahead", "parse": "json", "kind": "call", "size": 100, "bytes": len(body)}))
    # Transfer decoding happens in urllib3's 10 KB reads (zlib releases the GIL while inflating).
    big, _ = catalog_songs_body(300, random.Random(SEED + 1))
    packed = gzip.compress(big, 6)

    def inflate(data=packed):
        import zlib
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        return b"".join(d.decompress(data[i:i + 10240]) for i in range(0, len(data), 10240)) + d.flush()
    rows.append(("apple gzip inflate 300 songs (10 KB reads)", inflate,
                 {"lane": "lookahead", "parse": "transfer", "kind": "path", "size": 300, "bytes": len(packed)}))
    return rows


def sonos_rows(rng, quick):
    """(name, op, meta) for the Sonos parses: the Browse(Q:0) envelope (expat) and its DIDL-Lite
    (lxml), the adapter's whole queue_window path, and ZoneGroupState (expat envelope, then lxml
    and XSLT)."""
    from soco.services import Service
    from soco.data_structures_entry import from_didl_string
    from soco.data_structures import Queue
    from soco import zonegroupstate as ZG
    import lxml.etree as LX
    from control_center.sonos import SonosAdapter
    parse_didl = from_didl_string.__wrapped__          # soco caches by string; the bench parses every time
    adapter = SonosAdapter("192.0.2.10")                 # TEST-NET-1: constructed only, never connected
    rows = []
    for n in ((1, 3, 10, 21, 25, 50, 60, 100) if not quick else (21, 100)):
        body, didl = browse_body(n, rng)
        response = _response(body, XML_TYPE)
        rows.append((f"sonos Browse rows={n}: envelope (unwrap_arguments, expat)",
                     lambda r=response: Service.unwrap_arguments(r.text),
                     {"lane": "audio", "parse": "xml", "kind": "call", "size": n, "bytes": len(body)}))
        if n in (21, 100):
            rows.append((f"sonos Browse rows={n}: DIDL-Lite (from_didl_string: lxml + items)",
                         lambda d=didl: parse_didl(d),
                         {"lane": "audio", "parse": "xml", "kind": "lxml", "size": n, "bytes": len(didl.encode("utf-8"))}))

            def get_queue(r=response):
                out = Service.unwrap_arguments(r.text)
                items = parse_didl(out["Result"])
                page = Queue(items, number_returned=int(out["NumberReturned"]),
                             total_matches=int(out["TotalMatches"]), update_id=int(out["UpdateID"]))
                return [adapter._row(item, index + 1, "192.0.2.10") for index, item in enumerate(page)]
            rows.append((f"sonos queue_window rows={n}: client path (text, envelope, DIDL, rows)", get_queue,
                         {"lane": "audio", "parse": "xml", "kind": "path", "size": n, "bytes": len(body)}))
    for n in ((100, 1000) if not quick else (1000,)):
        _, didl = browse_body(n, random.Random(SEED + n))
        data = didl.encode("utf-8")

        def lxml_parse(d=data):
            return LX.fromstring(d, parser=LX.XMLParser(recover=True, encoding="utf-8"))
        rows.append((f"lxml fromstring alone, DIDL-Lite rows={n} (GIL released?)", lxml_parse,
                     {"lane": "audio", "parse": "xml", "kind": "lxml", "size": n, "bytes": len(data)}))
    for members in ((4, 12, 32) if not quick else (12,)):
        body, xml = zgs_body(members, rng)
        response = _response(body, XML_TYPE)
        rows.append((f"sonos ZoneGroupState members={members}: envelope (expat)",
                     lambda r=response: Service.unwrap_arguments(r.text),
                     {"lane": "audio", "parse": "xml", "kind": "call", "size": members, "bytes": len(body)}))

        def process(x=xml):
            state = ZG.ZoneGroupState()
            state.process_payload(payload=x, source="poll", source_ip="192.0.2.10")
            return state
        rows.append((f"sonos ZoneGroupState members={members}: process_payload (lxml, XSLT, zones)", process,
                     {"lane": "audio", "parse": "xml", "kind": "lxml", "size": members,
                      "bytes": len(xml.encode("utf-8"))}))
    return rows


def store_rows(rng, quick, folder=None):
    """The JSON files the service lanes read and write: the queue ledger (``QueueLedger.save``
    re-reads the file and rewrites it) and the queue-recovery record, before a start replaces the
    queue. For the record: the one ``json.dumps`` of the whole record that ``CredentialStore.save``
    runs (the path before WP6GIL-4, kept as the reference), and the path ``_save_recovery`` runs
    now (``sonos._recovery_json_parts``: one small ``json.dumps`` per value and per queue row, then
    one join), with its largest single C calls (the join, and DPAPI's copy in and out) as ``call``
    rows. With ``folder`` the whole ``_RecoveryStore.save_encoded`` (DPAPI, atomic write) runs too,
    writing the synthetic record into that temporary folder only."""
    import ctypes
    from control_center.sonos import _recovery_json_parts, _RecoveryStore
    rows = []
    for base, blocks in (((100, 8), (1000, 64), (5000, 64)) if not quick else ((1000, 64),)):
        data = ledger_file(rng, base, blocks)
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        size = len(text.encode("utf-8"))
        rows.append((f"ledger json.loads base={base} playnext={blocks}", lambda t=text: json.loads(t),
                     {"lane": "audio", "parse": "json", "kind": "call", "size": base, "bytes": size}))
        rows.append((f"ledger json.dumps base={base} playnext={blocks}",
                     lambda d=data: json.dumps(d, ensure_ascii=False, sort_keys=True),
                     {"lane": "audio", "parse": "json", "kind": "call", "size": base, "bytes": size}))
    for n in ((100, 1000, 5000) if not quick else (100, 5000)):
        record = recovery_snapshot(rng, n)
        whole = json.dumps(record).encode("utf-8")
        size = len(whole)
        rows.append((f"recovery record json.dumps rows={n} (one call: CredentialStore.save, before WP6GIL-4)",
                     lambda r=record: json.dumps(r).encode("utf-8"),
                     {"lane": "audio", "parse": "json", "kind": "call", "size": n, "bytes": size}))
        parts = _recovery_json_parts(record)
        assert b"".join(parts) == whole, "the parts must join to json.dumps(record)"
        rows.append((f"recovery save rows={n}: join of the encoded parts", lambda p=parts: b"".join(p),
                     {"lane": "audio", "parse": "json", "kind": "call", "size": n, "bytes": size}))
        rows.append((f"recovery save rows={n}: DPAPI copy in (create_string_buffer)",
                     lambda w=whole: ctypes.create_string_buffer(w),
                     {"lane": "audio", "parse": "copy", "kind": "call", "size": n, "bytes": size}))
        buffer = ctypes.create_string_buffer(whole)
        rows.append((f"recovery save rows={n}: DPAPI copy out (string_at)",
                     lambda b=buffer, k=size: ctypes.string_at(b, k),
                     {"lane": "audio", "parse": "copy", "kind": "call", "size": n, "bytes": size}))
        rows.append((f"recovery save rows={n}: encode in parts (_recovery_json_parts + join)",
                     lambda r=record: b"".join(_recovery_json_parts(r)),
                     {"lane": "audio", "parse": "json", "kind": "path", "size": n, "bytes": size}))
        if folder:
            store = _RecoveryStore(os.path.join(folder, f"queue-recovery-{n}.bin"))
            rows.append((f"recovery save rows={n}: whole save (parts, DPAPI, atomic write; temp folder)",
                         lambda s=store, r=record: s.save_encoded(b"".join(_recovery_json_parts(r))),
                         {"lane": "audio", "parse": "json", "kind": "path", "size": n, "bytes": size}))
    return rows


def recorded_rows(folder):
    """Response bodies saved during a supervised live check (``*.json`` Apple bodies, ``*.xml``
    SOAP envelopes). Only their names and sizes are reported."""
    from soco.services import Service
    rows = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            body = fh.read()
        if name.lower().endswith(".json"):
            rows.append((f"recorded {name}: Response.json()", _response(body, JSON_TYPE).json,
                         {"lane": "recorded", "parse": "json", "kind": "call", "size": None, "bytes": len(body)}))
        elif name.lower().endswith(".xml"):
            rows.append((f"recorded {name}: envelope (expat)",
                         lambda r=_response(body, XML_TYPE): Service.unwrap_arguments(r.text),
                         {"lane": "recorded", "parse": "xml", "kind": "call", "size": None, "bytes": len(body)}))
    return rows


# ----------------------------------------------------------------------------------- caps
def caps(rows):
    """K3 §1.2's caps: per parse, the largest size whose ``call`` hold has a p50 of at most
    TARGET_MS / MARGIN (a real body up to MARGIN x the fixture still parses within TARGET_MS)
    and a p95 of at most TARGET_MS (this shared PC's preemption included)."""
    bound = TARGET_MS / MARGIN

    def largest(prefix):
        ok = [r["size"] for r in rows if r["kind"] == "call" and r["name"].startswith(prefix)
              and r["call_p50_ms"] <= bound and r["hold_p95_ms"] <= TARGET_MS]
        return max(ok) if ok else None

    def hold(prefix):
        found = [r["hold_p95_ms"] for r in rows if r["kind"] == "call" and r["name"].startswith(prefix)]
        return max(found) if found else None
    paths = [r for r in rows if r["kind"] in ("path", "lxml")]
    return {
        "bound_ms": bound,
        "catalog_songs_ids": largest("apple catalog_songs ids="),
        "tracks_page_limit": largest("apple tracks page limit="),
        "playlists_page_limit": largest("apple playlists page limit="),
        "recent_limit_25_hold_ms": hold("apple Recently Added"),
        "ratings_100_hold_ms": hold("apple ratings"),
        "browse_rows": largest("sonos Browse rows="),
        "browse_100_hold_ms": hold("sonos Browse rows=100:"),
        "zgs_largest_hold_ms": hold("sonos ZoneGroupState"),
        "ledger_largest_hold_ms": hold("ledger"),
        "recovery_rows_within_bound": largest("recovery record json.dumps rows="),
        "recovery_save_largest_hold_ms": hold("recovery save rows="),
        "paths_holding": [r["name"] for r in paths if r["verdict"] != "py"],
    }


def per_100kb(rows):
    """Hold per 100 KB of body for each C parser (from the call rows over 20 KB)."""
    out = {}
    for label, test in (("json.loads", lambda r: r["name"].startswith("apple") and r["kind"] == "call"),
                        ("expat (unwrap_arguments)", lambda r: r["name"].startswith("sonos") and r["kind"] == "call")):
        found = [r["call_p50_ms"] / (r["bytes"] / 102_400) for r in rows if test(r) and r["bytes"] >= 20_000]
        if found:
            out[label] = round(sorted(found)[len(found) // 2], 3)
    return out


# ----------------------------------------------------------------------------------- main
def run(reps=20, quick=False, recorded=None, only=None, echo=True, save=True):
    block_network()
    rng = random.Random(SEED)
    scratch = tempfile.TemporaryDirectory(prefix="gil-parse-hold-") if save else None
    spec = (reference_rows() + apple_rows(rng, quick) + sonos_rows(rng, quick)
            + store_rows(rng, quick, scratch.name if scratch else None))
    if recorded:
        spec += recorded_rows(recorded)
    if only:
        spec = spec[:2] + [row for row in spec[2:] if only.lower() in row[0].lower()]
    previous = sys.getswitchinterval()
    sys.setswitchinterval(0.001)
    _time_period(True)
    try:
        out = {"python": sys.version.split()[0], "reps": reps, "probe_sleep_ms": PROBE_SLEEP_S * 1000,
               "switch_interval_ms": 1.0, "target_ms": TARGET_MS, "ceiling_ms": CEILING_MS, "margin": MARGIN,
               "baseline": baseline(), "rows": []}
        if echo:
            b = out["baseline"]
            print(f"# probe idle: p50 {b['late_p50_ms']:.3f} ms, p95 {b['late_p95_ms']:.3f} ms, "
                  f"max {b['late_max_ms']:.3f} ms over {b['samples']} wakes; reps {reps}", flush=True)
            print(f"# {'row':72s} {'kind':>6s} {'bytes':>8s}  {'call p50':>8s} {'p95':>6s} {'max':>6s}   "
                  f"{'probe p95':>9s} {'max':>6s}  verdict", flush=True)
        python_ref = None
        for name, op, meta in spec:
            row = run_row(name, op, reps, meta)
            if row["kind"] == "reference-python":
                python_ref = row["probe_p95_ms"]
            judge(row, python_ref if python_ref is not None else 2.0 + out["baseline"]["late_p95_ms"])
            out["rows"].append(row)
            if echo:
                print(f"  {name:72s} {row['kind'][:6]:>6s} {row['bytes']:>8d}  {row['call_p50_ms']:8.3f} "
                      f"{row['call_p95_ms']:6.3f} {row['call_max_ms']:6.3f}   {row['probe_p95_ms']:9.3f} "
                      f"{row['probe_max_ms']:6.3f}  {row['verdict']}", flush=True)
        out["python_reference_probe_p95_ms"] = python_ref
        out["caps"] = caps(out["rows"])
        out["hold_per_100kb_ms"] = per_100kb(out["rows"])
        calls = [r for r in out["rows"] if r["kind"] == "call"]
        out["worst_call_hold_p95_ms"] = max((r["hold_p95_ms"] for r in calls), default=0.0)
        return out
    finally:
        _time_period(False)
        sys.setswitchinterval(previous)
        if scratch:
            scratch.cleanup()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--json", default=None, help="write every row to this JSON file")
    ap.add_argument("--recorded", default=None, help="a folder of response bodies from a supervised live check")
    ap.add_argument("--only", default=None, help="run only the rows whose name contains this text")
    ap.add_argument("--quick", action="store_true", help="the largest and the capped size of each parse only")
    ap.add_argument("--no-save", action="store_true",
                    help="skip the whole recovery save rows (they write a synthetic record, DPAPI-protected, "
                         "into a temporary folder that is removed afterwards)")
    a = ap.parse_args(argv)
    result = run(a.reps, a.quick, a.recorded, a.only, save=not a.no_save)
    print("# hold per 100 KB (p50): " + json.dumps(result["hold_per_100kb_ms"]))
    print("# caps (K3 section 1.2): " + json.dumps(result["caps"]))
    print(json.dumps({"baseline": result["baseline"],
                      "python_reference_probe_p95_ms": result["python_reference_probe_p95_ms"],
                      "worst_call_hold_p95_ms": result["worst_call_hold_p95_ms"], "rows": len(result["rows"])}))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
