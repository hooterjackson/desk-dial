"""Fictional data for the headless Desk Dial Controller: the companion's simulator, overridden in place.

Import this module before anything constructs a simulator object. It replaces, in place (so every
module that already imported ``control_center.simulation`` sees the change), the simulator's library
(ALBUMS, TRACKS, PLAYLISTS, MORE_PLAYLISTS), its window set (WINDOWS), the Home Assistant sample
(SIM_SCENES, SIM_AREAS, SIM_AREA_LIGHTS) and the Sonos room / group labels, with the invented data of
fixtures.py: no real album, artist, track, playlist, app or room name reaches a recording.

Semantics kept from the simulator:
* PLAYLISTS[0] is the auto "Favourite Songs" playlist (``auto=True``: Apple's own favourites list, not
  editable, no catalog id); the other five are ordinary playlists; all six are Favourite playlists, and
  PLAYLISTS[1] / PLAYLISTS[0] show up in the Recently Added list at rows 13 and 26
  (simulation.SimulatedAppleMusic._library).
* MORE_PLAYLISTS are the extra favourites (SimControls.favs == "many") and the fallback of resolve().
* The area is "Living Room" (id ``living_room``) with four lights, one without colour temperature
  (the simulator's r3.1 "mixed" aggregate rules still apply); scenes Focus / Evening / Movie / Reading /
  Daylight are generic and kept.

check(text) raises when a blocklisted word (a real name, a room, an address, a user path) appears in
``text``; the recorder runs it over every JSON it writes.
"""
from __future__ import annotations

import re

import fixtures as fx
import companion  # noqa: F401  (puts the app on sys.path, no .pyc in its tree)
from control_center import simulation as SIM

APP_VERSION = "7.3.2.0"
FIRMWARE = "1.0.0-cc5.7"
ROOM = fx.ROOM                      # "Living Room": the Sonos room and the lights area
AREA = "living_room"

# ---------------------------------------------------------------- the library (fixtures -> simulator shapes)
SIM.ALBUMS[:] = [(title, artist, year, accent) for title, artist, year, accent, _style in fx.ALBUMS]
SIM.TRACKS[:] = [list(names) for names in fx.TRACKS]
# (title, albums, colour, length, unplayable index, auto): every fixtures playlist is a favourite (the simulator
# had two; Favourite playlists lists PLAYLISTS, simulation.py favourite_playlists), the first one the auto list.
SIM.PLAYLISTS[:] = [(title, albums, colour, length, None, index == 0)
                    for index, (title, albums, colour, length) in enumerate(fx.PLAYLISTS)]
SIM.MORE_PLAYLISTS[:] = [(title, albums, colour, length) for title, albums, colour, length in fx.PLAYLISTS[2:]]
SIM.WINDOWS[:] = [(app, title, accent) for app, title, _desc, accent, _kind in fx.WINDOWS]

# ---------------------------------------------------------------- Home Assistant: the Living Room
SIM.SIM_SCENES[:] = [("Focus", 62, 3200, "scene"), ("Evening", 48, 2700, "scene"), ("Movie", 12, 2200, "script"),
                     ("Reading", 80, 3500, "scene"), ("Daylight", 100, 5000, "automation")]
LIGHTS = (  # (entity, name, area, supports colour temperature)
    (f"light.{AREA}_desk", "Desk lamp", AREA, True), (f"light.{AREA}_floor", "Floor lamp", AREA, True),
    (f"light.{AREA}_shelf", "Shelf strip", AREA, False), (f"light.{AREA}_ceiling", "Ceiling", AREA, True),
    ("light.kitchen_ceiling", "Kitchen ceiling", "kitchen", True),
)
# Tuples are immutable: rebind the module attributes (SimulatedHomeAssistant reads them at construction).
SIM.SIM_AREAS = ((AREA, ROOM), ("kitchen", "Kitchen"), ("office", "Office"))
SIM.SIM_AREA_LIGHTS = LIGHTS

# ---------------------------------------------------------------- Sonos labels
_sonos_init = SIM.SimulatedSonos.__init__


def _fiction_sonos_init(self, controls=None, *, clock=None, sleep=None):
    _sonos_init(self, controls, clock=clock, sleep=sleep)
    self.state.update(room_id="sim-living-room", room_label=ROOM, group_id="sim-living-room", group_label=ROOM,
                      title=fx.TRACKS[2][4], artist=fx.ALBUMS[2][1])


if getattr(SIM.SimulatedSonos.__init__, "__name__", "") != "_fiction_sonos_init":
    SIM.SimulatedSonos.__init__ = _fiction_sonos_init

# ---------------------------------------------------------------- playlist covers
# A favourite playlist's id is "pl-" + digest(title)[:8] (simulation.SimulatedAppleMusic.favourite_playlists);
# its cover on the knob is its first album's (first_art), so a template naming it maps to that album.
PLAYLIST_ALBUM = {"pl-" + SIM._digest(title)[:8]: albums[0] for title, albums, _c, _n in fx.PLAYLISTS}
RECENT_PLAYLIST_ALBUM = {12: fx.PLAYLISTS[1][1][0], 25: fx.PLAYLISTS[0][1][0]}   # Recently Added rows 13 and 26


def album_of(url):
    """fixtures album index for a simulator artwork URL / template, or None (no cover)."""
    if not isinstance(url, str) or not url.startswith("simulation://art/"):
        return None
    ident = url.split("/")[3]
    n = len(fx.ALBUMS)
    try:
        if ident.startswith("al"):
            return int(ident[2:]) % n
        if ident.startswith("pl-"):
            album = PLAYLIST_ALBUM.get(ident)
            return None if album is None else album % n
        if ident.startswith("s") and ident[1:].isdigit():
            return ((int(ident[1:]) - 1_400_000_000) // 1000) % n
        if ident.startswith("a") and ident[1:].isdigit():
            return int(ident[1:]) % n
        if ident.startswith("p") and ident[1:].isdigit():
            album = RECENT_PLAYLIST_ALBUM.get(int(ident[1:]))
            return None if album is None else album % n
    except ValueError:
        return None
    return None


# ---------------------------------------------------------------- the blocklist
BLOCKLIST = ("Kate Bush", "Massive Attack", "Air", "Floating Points", "Chromatics",
             "Miles", "Jobim", "Tropic", "192.168", "RINCON", "Danny", "Bambu", "Claude", "Slack",
             "ChatGPT", "Chrome", "Figma", "Spotify", "Steam", "Undertow", "Morning Fog", "Night Drive",
             "Hounds of Love", "Sample track", r"C:\\Users", "mzstatic")
try:                                   # plus the owner's private terms, kept outside the repo (gates.PRIVATE_TERMS)
    from gates import PRIVATE_TERMS as _PRIVATE
    BLOCKLIST = BLOCKLIST + tuple(_PRIVATE)
except Exception:
    pass
_BLOCK_RE = re.compile("|".join(r"(?<![A-Za-z])" + re.escape(word) + r"(?![a-z])" for word in BLOCKLIST))


def offenders(text):
    """Every blocklisted word found in ``text`` (with 40 characters of context), in order."""
    found = []
    for match in _BLOCK_RE.finditer(text):
        start = max(0, match.start() - 20)
        found.append((match.group(0), text[start:match.end() + 20]))
    return found


def check(text, where=""):
    bad = offenders(text)
    if bad:
        shown = "; ".join(f"{word!r} in {context!r}" for word, context in bad[:8])
        raise SystemExit(f"blocklist hit{' in ' + where if where else ''}: {shown}")
    return True
