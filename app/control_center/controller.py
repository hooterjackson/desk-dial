"""Pure, deterministic interaction controller for desktop v7 (CONTROL_CENTER_V5.md, K3). No I/O.

The controller owns the knob modes (``home``, ``recent``, ``explorer``, ``tracks``, ``seek``,
``upnext``, ``windows``), the button grammar with its dim reasons and the Head-shake-with-reason
rule (section 3), Back and the firmware hold (section 4), the re-entry helper and its input
blackouts (section 6), every timer of section 7 on the injected clock, the confirmation policy
(section 8), the transient copy slot (section 2.4), the toast service rules (section 12) and the
overlay lifetime (section 13). It talks to the runtime only: effects out (``drain()``), and
``complete``, ``progress``, device calls and presenter events in.

Effects carry ``kind``, ``request``, ``control_id`` and ``view_id`` (section 10.1). Service
effects (Sonos, Apple Music, windows_open / windows_activate) are ``pending`` until their
``complete``; presenter effects (explorer_*, upnext_*, windows_highlight / _snap / _cancel /
_close_pair / _hide, toast) are posted and never completed: the presenters answer with the
section 11.4 events, which all enter through ``presenter_event`` (VOC-R22). The narrow presenter
interface is therefore: effect dicts out (names VOC section 7.4, payloads section 11.1 with
``t0`` on this controller's clock, ``time.perf_counter`` in production), event dicts in::

    {"kind": "opened" | "closed" | "click_action" | "refused" | "system" | "snap_result"
             | "cancel_result",
     "surface": "explorer" | "upnext" | "picker", "reason": ..., "what": lock|sleep|display|motion,
     "side": "left" | "right", "outcome": ..., "restored": bool, "completed": bool}

Every host-driven move is a new control (``_enter``); presses and turns are honoured only for
the current control id and only after its ``ready``. The embedded frame is the post-ready
projection; its ``artKey`` follows the entry art rule of section 6.3 (the runtime's decorator
keeps the previous cover in an entry and sends the new one in the first frame after ``ready``).

alive (firmware/ALIVE.md revision 2): Home frames carry ``playing`` from the confirmed
transport only; it is omitted while a start is pending and on the frame that first carries a
``started`` moment (K2 M16), and held after a start until PLAYING is confirmed
(ALBUM_START_HOLD_SECONDS, every start kind).
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import count
import logging
import math
import random
import threading
import time

from .presentation import (EXTERNAL_SECONDS, LED_GREEN, LED_RED, LED_WHITE, RING_WINDOW, clean_text,
                           mmss, window_first_v5)
from .onshape import HOME_CHORD_SECONDS, KeyTracker
from .app_engine import (DISABLED_REFUSED, FOCUS_REFUSED, KEYBOARD_REFUSED, REFUSALS, REFUSED, SlotTracker,
                         knob_label, slot_of_button, turn_buttons, wheel_button)
from .queue_context import QueueLedger

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())  # the application configures the real handlers

# Kept for existing imports (the contract LED palette, not the LCD inks).
WHITE, GREEN, RED = LED_WHITE, LED_GREEN, LED_RED
TONE_COLORS = {"go": LED_GREEN, "stop": LED_RED}
# The retired v6 lookahead page marker (kept so old imports resolve; never set any more).
LOOKAHEAD_PAGE = "lookahead"

MODES = ("home", "recent", "explorer", "tracks", "seek", "upnext", "windows", "launcher", "lights", "scenes",
         "onshape")
OVERLAY_MODES = ("explorer", "upnext", "windows")
# r3 (Desk Dial r3 release 1, presentation >= 6 only): `launcher` is the new Home (knob = volume;
# 1 Music · 2 Windows · 3 Lights · 4 Play/Pause), `home` is then the Music space (today's Home screen
# with 1 Home · 2 Recently Added · 3 Tracks · 4 Play/Pause), `lights` / `scenes` the Lights space.
# Without r3 (`Controller.spaces` False) `launcher`, `lights` and `scenes` are never entered.
# A0 (ONSHAPE.md, presentation >= 6 only): `onshape`, the knob as Onshape's mouse (zoom / orbit / pan /
# Undo); the runtime's injector does the input, the controller only what the knob shows and hold 1.
VOLUME_MODES = ("home", "launcher")
LIGHTS_MODES = ("lights", "scenes")
PROFILES = {"home": "BINARIS BEER", "recent": "MIDI SKIPPER", "explorer": "MIDI SKIPPER",
            "tracks": "MIDI CLACK JONES", "seek": "BINARIS BEER", "upnext": "MIDI SKIPPER",
            "windows": "MIDI SKIPPER", "launcher": "BINARIS BEER", "lights": "BINARIS BEER",
            "scenes": "MIDI SKIPPER", "onshape": "BINARIS BEER"}
LIGHTS_TEMP_PROFILE = "MIDI SKIPPER"   # Lights in temperature mode (100 K per detent, bounded)
QUEUE_PROFILE = "MIDI SKIPPER"         # r3.1 Tracks over the whole queue, one row per detent
# DD-BUG-004: a knob whose owner renamed or deleted one of the profiles above still gets a control the
# device accepts: the nearest installed stand-in (this order), else the inventory's first profile. The
# runtime hands the inventory over at `connected` (set_installed_profiles) and shows `profile_status`.
PROFILE_FALLBACKS = {"BINARIS BEER": ("MIDI SKIPPER", "MIDI CLACK JONES"),
                     "MIDI SKIPPER": ("MIDI CLACK JONES", "BINARIS BEER"),
                     "MIDI CLACK JONES": ("MIDI SKIPPER", "BINARIS BEER")}
PROFILE_MISSING_STATUS = "Knob profile missing · {names} · using {used}"
# Legacy `mode` text (presentation < 4 knobs derive a layout from it; v4/v5 knobs ignore it).
MODE_TITLES = {"home": "VOLUME", "recent": "RECENTLY ADDED", "explorer": "RECENTLY ADDED",
               "tracks": "TRACKS", "seek": "TRACKS", "upnext": "TRACKS", "windows": "WINDOWS",
               "launcher": "VOLUME", "lights": "LIGHTS", "scenes": "LIGHTS", "onshape": "ONSHAPE"}
KIND_LABELS = {"album": "Album", "library-albums": "Album", "song": "Song", "library-songs": "Song",
               "playlist": "Playlist", "library-playlists": "Playlist"}
SOURCES = ("queue", "airplay", "radio", "linein", "none")
SHUFFLE_PLAY_MODES = frozenset(("SHUFFLE", "SHUFFLE_NOREPEAT", "SHUFFLE_REPEAT_ONE"))

# ------------------------------------------------------------------ timers (section 7), seconds
SEEK_STEP_S = 5
SEEK_MARGIN_S = 3
SEEK_MAX_DURATION_S = 59999
SEEK_DEBOUNCE = 0.250
SEEK_IDLE = 3.0
SEEK_FAIL_LINE = 2.2
SEEK_LIMIT_LINE = 1.5
REASON_META = 2.0
SIGNIN_META = 2.2
LIKE_FAIL_META = 2.2
LIKE_LATE_CHECK = 5.0
PREFETCH_RESOLVE_REST = 0.4
FAIL_META = 2.4
QUEUED_META = 1.5
QUEUED_META_R3 = 2.2             # r3.1 design: `Queued · {title}` / `Plays next · {track}`
DOMAIN_META = 1.8                # r3.1 design: `Knob sets brightness` / `Knob sets volume`
LIST_SOURCE_META = 1.2           # r3.1 design: `Favourite playlists` / `Recently Added`
FEEDBACK_META = 1.5
PARTIAL_STATUS = 3.0
START_FAIL_STATUS = 2.6
OVERLAY_PLAY_CLOSE = 0.380
OVERLAY_PLAY_CLOSE_MS = 380
TAB_SWAP = 0.190
SHUFFLE_SWAP = 0.200
SNAP_PLACE_MS = 360
SNAP_ADVANCE = 0.420
SNAP_RESULT_TIMEOUT = 1.0
SNAP_PAIR_CLOSE = 0.820
PASSIVE_QUIET = 0.400
EXIT_TOAST_DELAY = 0.360
OVERLAY_IDLE = 60.0
VOLUME_REVEAL_SECONDS = 1.4
EXTERNAL_REVEAL_SECONDS = 2.6
STATE_POLL = 1.0
STATE_POLL_BUSY = 2.0
FAVOURITES_STALE = 600.0
FAVOURITES_BACKOFF = (30.0, 120.0)
RECENT_PAGE = 25
RECENT_AHEAD = 16            # >= 16 loaded items ahead (12 preload + 4 in the direction of travel)
RECENT_RETRY = 5.0           # a failed later page is asked again after this long
COMPANION_SHUFFLE_MAX = 60
UPNEXT_WINDOW = 21
UPNEXT_EDGE = 5
PLAY_NEXT_MAX = 100
# alive (ALIVE.md section 3, R4): after any start a non-PLAYING reading omits `playing` until
# PLAYING is confirmed, a Home Play/Pause is pressed, or this long has passed.
ALBUM_START_HOLD_SECONDS = 10.0
FEEDBACK_SEQ_MAX = 0x7FFFFFFF
SKIP_DIRECTIONS = {"previous": -1, "next": 1}
DISCONNECTED_STATUS = "Knob disconnected · reconnect to resume"
# Line limits in px (VOC section 9.1; Montserrat 500): (font size, limit).
LINE_META = (12, 170)
LINE_STATUS = (12, 160)
LINE_14 = (14, 170)
LINE_R3 = (12, 180)          # r3 status / meta lines (README 2: x 30, w 180)
EXPLORER_PRELOAD_BEHIND = 12
EXPLORER_PRELOAD_AHEAD = 16  # +-12 plus 4 in the direction of travel
# r3 Lights (README sections 1.2, 3, 7).
LIGHTS_WRITE_INTERVAL = 0.25     # <= 4 Hz brightness / temperature writes (each fades over
                                 # home_assistant.LIGHT_TRANSITION), the final value on settle
LIGHTS_POLL = 2.0                # a lights_read while the Lights space is open (the stream is the main source)
LIGHTS_ECHO = 3.0                # our own write's state echo is not an "external" change for this long
LIGHTS_SETTLE = 1.0              # user 2026-09-29: from this long after the last write, lights reporting another
                                 # level than we set (a fade ending short, a late stale report) get it once
                                 # more, without a fade (100 % no longer drifts back to 95 / 97 %)
LIGHTS_MIXED_QUIET = 2.5         # user 2026-09-29: while the knob drives the lights (and this long after the
                                 # last write) the area keeps its uniform / mixed look: the lights report one
                                 # by one mid-fade, which flickered the Navigator card between its layouts
LIGHTS_NEAR = {"bri": 6, "kelvin": 300}   # a report this close to our last write is that write (the knob keeps
                                 # showing what was set); a farther one is a real change (another app, a switch)
SCENE_SETTLE = 3.0               # the state changes a scene run causes are applied silently
LIGHTS_FINAL_WINDOW = LIGHTS_ECHO + LIGHTS_SETTLE   # DD-BUG-002: a near report is "our write" (masked, corrected
                                 # once) only this long after that write; later it is a real change (the HA app,
                                 # an automation, a scene) and is shown, never reverted
LIGHTS_MEMBERS_DRAWN = 32        # DD-BUG-008: per-light rows handed to the frames / Navigator (drawing only);
                                 # a turn targets every on light of the area, however many
LIGHTS_MEMBERS_MAX = 1024        # a sanity bound on the adapter's per-light rows (memory, not targeting)
LIGHTS_MODE_META = 1.4           # `Knob: temperature` / `Knob: brightness` after a mode toggle
SCENE_META = 2.2                 # `Scene running`
KELVIN_MIN, KELVIN_MAX, KELVIN_STEP = 2200, 6500, 100
BRI_ON_HIGH = 99    # lights on: positions 0..99 are 1..100 % (DD-DES-003)
KELVIN_DEFAULT = 2700
SCENES_MAX = 20
# r3 navigation (README sections 1 and 2.1).
HOME_GUARD = 0.7                 # a tap on 1 this soon after arriving Home is ignored (overshoot guard)
HOME_GUARD_META = 1.4            # `Home · press 1 again for Music`
SEEK_R3_META = 1.4               # `Seek set` / `Seek cancelled`
R3_REFUSED_META = 2.0            # r3 unavailable-press reasons (README 1: #FF8474, 2 s)
# The arc breadcrumb of each r3 screen (presentation 6 `crumb`; README 2.1 paths). The launcher has none.
CRUMBS = {"home": "music", "recent": "recent", "tracks": "tracks", "seek": "tracks", "upnext": "upnext",
          "windows": "windows", "lights": "lights", "scenes": "scenes"}
# r3.1 (2026-09-29 feedback round).
HOME_DOMAINS = ("volume", "lights")   # the launcher's knob: music volume or the Lights area's brightness
LIST_SOURCES = ("recent", "favourites")   # the Recently Added list's source (button 3 toggles it)
TRACKS_PAGE = 20                 # whole-queue Tracks: queue rows read per page (the focus page + one ahead)
TRACKS_EDGE = 5                  # the next page is read when the focus is this close to a loaded edge
TRACKS_CACHE_ROWS = 400          # rows kept per queue revision (older pages dropped first)
# A0 Onshape mode (ONSHAPE.md): the knob's control is (0, 65535, 32768), re-centred on every entry
# and again (after a quiet 400 ms) once the knob has travelled this far from the centre.
# 2026-09-30: never 65535 wide. The knob's haptic loop counts positions as a uint16 (haptic.cpp: end - start
# + 1), so 0..65535 wrapped to 0 and switched on its derivative term: the knob buzzed in Onshape mode only.
ONSHAPE_BOUNDS = (0, 60000, 30000)
ONSHAPE_RECENTRE = 25000
ONSHAPE_REFUSED_META = 2.0       # `Point at the model` (the injector refuses at most once per burst)
ONSHAPE_UNDO_META = 1.2
ONSHAPE_PARAM_LAG = 0.5          # after 3's release ends parameter mode, the injector's snapshot may still say `param`
# r4 FEEL (firmware 1.0.0-cc5.7, plan F2; firmware HAPTICS.md, CONTROL_CENTER.md "Feel and sound"). The control's
# `feel` token per screen (r4 section 4.4); device.py sends it only to a knob whose capabilities carry feel 1 (older
# firmware keeps the PROFILES feel exactly). Recently Added / Playlists coast (free.spin) only over this many items.
FREE_SPIN_MIN_ITEMS = 20
FEEL_TOKENS = ("detent.value", "detent.dimmer", "detent.list", "detent.coarse", "detent.fine", "fluid.scrub",
               "fluid.light", "free.spin")
# The frame's `haptic` event tokens (capability hapticFx 1): only four things thump (hold landings, Play, Turn on,
# Scene run; r4 4.4); a refusal or an error buzzes at most once a second.
HAPTIC_TOKENS = ("confirm.tick", "confirm.thump", "nudge.left", "nudge.right", "refuse.buzz", "error.buzz",
                 "confirm.off")
HAPTIC_BUZZ_GAP = 1.0

# ------------------------------------------------------------------ copy (VOC section 9; K3 section 15)
COPY = {
    "knob.heading.recent": "RECENTLY ADDED",
    "knob.heading.explorer_recent": "RECENT",
    "knob.heading.explorer_favourites": "FAVOURITES",
    "knob.heading.upnext": "UP NEXT",
    "knob.heading.tracks": "TRACKS",
    "knob.heading.seek": "SEEK",
    "knob.meta.position": "{i} / {n}",
    "knob.meta.position_end": "{n} / {n} · end",
    "knob.meta.playnext.progress": "Queueing… {k} of {n}",
    "knob.meta.playnext.resolving": "Finding songs…",
    "knob.meta.playnext.ok": "Queued next",
    "knob.meta.playnext.nothing": "Nothing added · retry",
    "knob.meta.playnext.partial": "Partly queued",
    "knob.meta.playnext.song_changed": "Song changed · retry",
    "knob.meta.playnext.airplay": "AirPlay · use Play",
    "knob.meta.playnext.radio": "Radio · use Play",
    "knob.meta.playnext.linein": "Line-in · use Play",
    "knob.meta.playnext.none": "Nothing playing · Play",
    "knob.meta.playnext.shuffle": "Shuffle on · turn it off",
    "knob.meta.loading": "Loading…",
    "knob.title.favourites_empty": "No favourites yet",
    "knob.sub.favourites_empty": "Star one in Music",
    "knob.sub.playlist_count": "{n} songs",
    "knob.meta.tracks.hint": "Press 4 to skip",
    "knob.meta.tracks.position_shuffle": "{i} / {n} · shuffle",
    "knob.meta.tracks.skipping": "Skipping…",
    "knob.meta.upnext.airplay": "Up next is in Music app",
    "knob.meta.upnext.radio": "Radio · no Up next",
    "knob.meta.upnext.linein": "Line-in · no Up next",
    "knob.meta.upnext.none": "Nothing playing",
    "knob.meta.seek.radio": "Can’t seek · radio",
    "knob.meta.seek.airplay": "Can’t seek · AirPlay",
    "knob.meta.seek.linein": "Can’t seek · line-in",
    "knob.meta.seek.none": "Nothing playing",
    "knob.meta.seek.no_length": "Can’t seek · no length",
    "knob.meta.upnext.position_playing": "{i} / {n} · playing",
    "knob.meta.upnext.loading": "Loading queue…",
    "knob.meta.like.on": "Liked",
    "knob.meta.like.unknown": "Checking likes…",
    "knob.meta.like.not_catalog": "Not an Apple Music song",
    "knob.meta.like.signin_expired": "Sign-in expired",
    "knob.meta.like.signin_needed": "Not signed in",
    "knob.meta.like.failed": "Didn’t save · try again",
    "knob.meta.like.unlike_in_music": "Unfavourite in Music app",
    "knob.meta.shuffle.on": "Shuffle on",
    "knob.meta.shuffle.off": "Shuffle off · in order",
    "knob.meta.shuffle.sonos": "Sonos is shuffling",
    "knob.meta.shuffle.queue_changed": "Queue changed",
    "knob.meta.shuffle.failed": "Didn’t shuffle · try again",
    "knob.meta.shuffle.nothing": "Nothing to shuffle",
    "knob.meta.snap.left_set": "Left: {App} · pick right",
    "knob.meta.snap.right_set": "Right: {App} · pick left",
    "knob.meta.snap.hung": "{App} not responding",
    "knob.meta.snap.move": "Couldn’t move {App}",
    "knob.meta.snap.fit": "{App} can’t fit half",
    "knob.meta.windows.switching": "Switching…",
    "knob.meta.windows.no_focus": "Didn’t come forward · retry",
    "knob.meta.windows.closed": "Closed · can’t switch",
    "knob.title.no_windows": "No eligible windows",
    "knob.line.tracks.now": "Now: {title}",
    "knob.line.tracks.next": "Next: {title}",
    "knob.line.tracks.prev": "Prev: {title}",
    "knob.line.tracks.end": "End of queue",
    "knob.line.tracks.start": "Start of queue",
    "knob.line.tracks.next_shuffle": "Next: shuffle pick",
    "knob.line.tracks.prev_shuffle": "Prev: last played",
    "knob.title.tracks.choose": "Turn to choose",
    "knob.title.tracks.prev": "Previous track",
    "knob.title.tracks.next": "Next track",
    "knob.meta.skip.end": "End of queue",
    "knob.meta.skip.start": "Start of queue",
    "knob.meta.skip.prev_unavailable": "Previous unavailable",
    "knob.meta.skip.next_unavailable": "Next unavailable",
    "knob.line.seek.length": "of {m:ss}",
    "knob.line.seek.jumping": "Jumping…",
    "knob.line.seek.failed": "Didn’t jump · try again",
    "knob.line.seek.limit": "Stops 3 s before end",
    "knob.status.starting": "Starting…",
    "knob.status.pausing": "Pausing…",
    "knob.status.partial": "Playing {k} of {n}",
    "knob.status.start_failed": "Didn’t start",
    "knob.status.album_blocked": "Album unavailable",
    "knob.status.paused": "Paused",
    "knob.status.setting": "Setting…",
    "knob.status.changed_elsewhere": "Changed on Sonos",
    "knob.status.minimum": "Minimum",
    "knob.status.maximum": "Maximum",
    "knob.status.nothing_playing": "Nothing playing",
    "knob.status.sonos_unavailable": "Sonos unavailable",
    "knob.status.group_changed": "Speaker group changed",
    "knob.status.connecting": "Connecting knob",
    "knob.caption.nothing_playing": "Nothing playing",
    "knob.caption.now_playing": "Now playing",
    "knob.caption.volume": "{title}",
    "knob.caption.volume_paused": "Paused · {title}",
    "knob.title.looking_for_sonos": "Looking for Sonos…",
    "knob.title.sonos_unavailable": "Sonos unavailable",
    "knob.sub.looking_for_sonos": "Looking for Sonos…",
    "knob.meta.windows_still_works": "Windows still works",
    "knob.title.recent_empty": "Nothing recently added",
    "knob.sub.recent_empty": "Apple Music library",
    "knob.title.signin_expired": "Apple Music sign-in expired",
    "knob.sub.signin_expired": "Renew on your PC",
    "knob.title.signin_needed": "Connect Apple Music",
    "knob.sub.signin_needed": "Sign in on your PC",
    "knob.title.library_error": "Library not loaded",
    "knob.sub.library_error": "Home, then Browse",
    "knob.title.upnext_sonos_card": "Shuffled by Sonos",
    "knob.meta.busy.starting": "Starting…",
    "knob.meta.busy.pausing": "Pausing…",
    "knob.meta.busy.shuffling": "Shuffling…",
    "knob.meta.library_error": "Library not loaded",
    "knob.meta.signin_expired": "Sign-in expired",
    "knob.meta.signin_needed": "Not signed in",
    "knob.meta.sonos_unavailable": "Sonos unavailable",
    "knob.meta.item_unavailable": "Not available",
    "knob.meta.group_changed": "Speaker group changed",
    "knob.meta.stage_unavailable": "Couldn’t open on screen",
    "overlay.explorer.untitled": "Untitled playlist",
    "overlay.upnext.shuffle_on": "Shuffle on",
    "overlay.upnext.shuffle_off": "In order",
    "overlay.upnext.shuffle_sonos": "Shuffle on · Sonos picks the order",
    "toast.playnext.ok": "Queued next · {album}",
    "toast.playnext.not_queue": "Not playing from the queue · use Play",
    "toast.playnext.none": "Nothing playing · use Play",
    "toast.playnext.shuffle": "Shuffle is on · turn it off to play next",
    "toast.playnext.nothing": "Couldn’t queue {album} · nothing added",
    "toast.playnext.partial": "Partly queued · check the Sonos queue",
    "toast.playnext.song_changed": "Song changed · try again",
    "toast.start.ok": "Playing {name}",
    "toast.start.partial": "Playing {k} of {n} · {u} songs unavailable",
    "toast.start.partial_one": "Playing {k} of {n} · 1 song unavailable",
    "toast.start.album_blocked": "{album} can’t play · a song is unavailable",
    "toast.start.failed": "Couldn’t start {name}",
    "toast.skip.next": "Next · {title}",
    "toast.skip.prev": "Previous · {title}",
    "toast.switch": "{App} · {Title}",
    "toast.snap.pair": "Side by side · {A} and {B}",
    "toast.snap.one_side": "{A} left · {B} right",
    "toast.like.signin_expired": "Apple Music sign-in expired · open Settings",
    "toast.like.signin_needed": "Apple Music not connected · open Settings",
    # r3 Lights (README sections 2.2 and 6).
    "knob.heading.music": "MUSIC",
    "knob.heading.lights": "LIGHTS",
    "knob.heading.scenes": "SCENES",
    "knob.title.lights_off": "Lights off",
    "knob.sub.lights_off": "Tap 4 to turn on",
    "knob.sub.lights_level": "{bri}% · {K} K",
    "knob.sub.lights_level_bri": "{bri}%",
    "knob.title.lights_adjusted": "{scene} · adjusted",
    "knob.title.lights_default": "Lights",
    "knob.title.lights_not_set_up": "Lights not set up",
    "knob.sub.lights_not_set_up": "Add Home Assistant in Settings",
    "knob.title.lights_connecting": "Connecting to lights…",
    "knob.sub.lights_connecting": "Home Assistant",
    "knob.title.lights_offline": "Lights unavailable",
    "knob.sub.lights_offline": "Can’t reach Home Assistant",
    "knob.sub.lights_unavailable": "The light is unavailable",
    "knob.title.lights_auth": "Home Assistant sign-in",
    "knob.sub.lights_auth": "Check the token in Settings",
    "knob.caption.brightness": "Brightness",
    "knob.caption.temperature": "Colour temperature",
    "knob.status.lights_changed": "Changed in Home Assistant",
    "knob.meta.lights.knob_temperature": "Knob: temperature",
    "knob.meta.lights.knob_brightness": "Knob: brightness",
    "knob.meta.lights.on": "Lights on",
    "knob.meta.lights.off": "Lights off",
    "knob.meta.lights.unavailable": "Lights unavailable",
    "knob.meta.lights.no_scenes": "No scenes set up",
    "knob.meta.lights.no_temperature": "No colour temperature",
    "knob.meta.lights.failed": "Didn’t change · try again",
    "knob.meta.lights.not_allowed": "Not allowed in Desk Dial",
    "knob.meta.lights.signin": "Check the token in Settings",
    "knob.meta.lights.blocked": "Blocked by Home Assistant",
    "knob.meta.scenes.position": "{i} / {n}",
    "knob.meta.scenes.preview": "{i} / {n} · {bri}% · {K} K",
    "knob.meta.scenes.preview_bri": "{i} / {n} · {bri}%",
    "knob.meta.scenes.running": "{i} / {n} · running now",
    "knob.meta.scenes.choose": "Turn to choose · 4 runs it",
    "knob.meta.scene.running": "Scene running",
    "knob.meta.scene.failed": "Didn’t run · try again",
    "toast.scene.ok": "Lights · {scene}",
    "toast.scene.failed": "Couldn’t run {scene}",
    # r3 navigation (README sections 1, 2.2 and 6; release 2 of the plan, delivered with release 1).
    "knob.status.home_guard": "Home · press 1 again for Music",
    "knob.meta.skip.choose": "Turn to pick previous or next",
    "knob.meta.skip.seeking": "Set or cancel seek first",
    "knob.meta.seek.set": "Seek set",
    "knob.meta.seek.cancelled": "Seek cancelled",
    "knob.line.seek.r3": "of {m:ss} · 3 sets · 1 cancels",
    "knob.title.tracks.prev_r3": "Previous",
    "knob.title.tracks.next_r3": "Next",
    "knob.meta.tracks.turn": "Turn for previous or next",
    "knob.meta.snap.left": "Snapped left",
    "knob.meta.snap.right": "Snapped right",
    "knob.status.switched": "Switched to {App}",
    # r3.1 (2026-09-29 feedback round): hold 4, the Playlists toggle, whole-queue Tracks, area Lights.
    "knob.heading.playlists": "PLAYLISTS",
    "knob.status.domain.lights": "Knob sets brightness",
    "knob.status.domain.volume": "Knob sets volume",
    "knob.sub.lights_area_level": "{name} · {bri}% · {K} K",
    "knob.sub.lights_area_level_bri": "{name} · {bri}%",
    "knob.title.lights_count": "{n} lights",
    "knob.title.lights_count_one": "1 light",
    "knob.title.lights_none": "No lights in {name}",
    "knob.title.lights_blocked_unav": "Lights unavailable",
    "knob.title.lights_none_area": "No lights in the area",
    "knob.sub.lights_none": "Add them in Home Assistant",
    "knob.meta.lights.none": "No lights in {name}",
    "knob.meta.lights.not_connected": "Home Assistant not connected",
    "knob.meta.lights.no_scenes_area": "No scenes in {name}",
    "knob.meta.lights.check": "Check them in Home Assistant",
    "knob.meta.lights.open_settings": "Open Settings on your PC",
    "knob.meta.lights.area": "{name} · {lights}",
    "knob.meta.lights.one_unavailable": "{name} unavailable",
    "knob.meta.lights.n_unavailable": "{n} lights unavailable",
    "knob.meta.lights.some_on": "{on} of {ok} on",
    "knob.meta.lights.average": " · average",
    "knob.meta.lights.raw": "{text}",
    "knob.title.lights_nc": "Not connected",
    "knob.sub.lights_nc": "Home Assistant",
    "knob.caption.brightness_average": "Brightness · average",
    "knob.meta.upnext.already_playing": "Already playing",
    "knob.meta.upnext.plays_next": "Plays next · {title}",
    "knob.meta.queued_title": "Queued · {title}",
    "knob.meta.list.favourites": "Favourite playlists",
    "knob.meta.list.recent": "Recently Added",
    "knob.meta.list.position_artist": "{i} / {n} · {artist}",
    "knob.meta.list.position_songs": "{i} / {n} · {count} songs",
    "knob.sub.favourite_playlist": "Favourite playlist",
    "knob.meta.tracks.skip_to": "Skip to {n} / {T} · 4 plays",
    "knob.meta.tracks.back_to": "Back to {n} / {T} · 4 plays",
    "knob.meta.tracks.playing": "Playing {n} / {T}",
    "knob.status.nothing_loaded": "Nothing loaded",
    "knob.status.nothing_loaded_pick": "Nothing loaded · pick in Recent",
    "knob.title.lights_area_missing": "Area not found",
    "knob.sub.lights_area_missing": "Pick the area in Settings",
    "knob.meta.lights.area_missing": "Area not found",
    "knob.meta.tracks.browse": "Turn to browse the queue",
    "knob.meta.tracks.play": "Press 4 to play",
    "knob.sub.tracks.skip_to": "Skip to · {n} / {T}",
    "knob.sub.tracks.back_to": "Back to · {n} / {T}",
    "knob.title.tracks.row": "Track {n}",
    # A0 Onshape mode (ONSHAPE.md): the title is the live action.
    "knob.heading.onshape": "ONSHAPE",
    "knob.title.onshape.zoom": "ZOOM",
    "knob.title.onshape.orbit": "ORBIT",
    "knob.title.onshape.pan": "PAN",
    "knob.title.onshape.tilt": "TILT",
    "knob.title.onshape.refused": "Point at the model",
    # DD-SEC-001: the cursor is on the model but the keyboard focus is outside the page (address bar, find bar).
    "knob.title.onshape.focus_refused": "Click the model first",
    "knob.sub.onshape.zoom": "1 tilt · 2 orbit · 4 pan",   # "Hold 1 tilt ..." is cut off
    "knob.sub.onshape.orbit": "Turn to orbit",
    "knob.sub.onshape.tilt": "Turn to tilt",
    "knob.sub.onshape.pan": "Turn to pan",
    "knob.sub.onshape.refused": "Put the cursor on it",
    "knob.sub.onshape.focus_refused": "Keys go to the page",
    "knob.status.onshape.undo": "Undo",
    "knob.status.onshape.home": "Hold all 4 for Home",
    # App profiles (plan 4a, S1 DD-B): a chord the foreground keyboard layout can't type, a command the profile turned
    # off on Windows. Nothing is sent; the knob says why (the canvas gives way to this text screen for the moment).
    "knob.title.onshape.keyboard_refused": "Not on this keyboard",
    "knob.sub.onshape.keyboard_refused": "Its key needs another layout",
    "knob.title.onshape.disabled_refused": "Not on Windows",
    "knob.sub.onshape.disabled_refused": "This command is off here",
    # App profiles: every other app's text screen (heading = the profile's name, title = the live action, subtitle =
    # its legend), shown on a knob without the app canvas or while its profile uploads.
    "knob.title.app.refused": "Point at the app",
    "knob.sub.app.refused": "Put the cursor on it",
    "knob.title.app.focus_refused": "Click the app first",
    "knob.sub.app.focus_refused": "Keys go to the app",
    "knob.title.app.keyboard_refused": "Not on this keyboard",
    "knob.sub.app.keyboard_refused": "Its key needs another layout",
    "knob.title.app.disabled_refused": "Not on Windows",
    "knob.sub.app.disabled_refused": "This command is off here",
    "knob.title.app.cancel": "Cancel",
    "knob.sub.app.param": "Tap {n} OK · hold {n} cancel",
    "knob.status.app.home": "Hold all 4 for Home",
}
# Home button labels (the idle-row words, VOC-D08; each <= 46 px at 12 px).
HOME_LABELS = ("Play", "Pause", "Browse", "Tracks", "Win")

_view_ids = count(1)


def copy_text(copy_id, **fields):
    """The text of ``copy_id`` with ``{name}`` placeholders filled (no fitting)."""
    text = COPY[copy_id]
    for name, value in fields.items():
        text = text.replace("{" + name + "}", str(value))
    return text


# ------------------------------------------------------------------ fitting (K3 section 15.1)
_measure_fn = None


def measure(text, size):
    """Width in knob px of ``text`` at ``size`` (the lcd_preview font metrics when available)."""
    global _measure_fn
    if _measure_fn is None:
        try:
            from .lcd_preview import text_width
            _measure_fn = text_width
        except Exception:  # pragma: no cover - the metrics module is optional here
            _measure_fn = False
    if _measure_fn:
        try:
            return _measure_fn(text, size)
        except Exception:
            pass
    return int(round(len(text) * size * 0.58))


_FIT_CACHE = OrderedDict()


APP_NAMES = {"onshape": "Onshape", "figma": "Figma", "plasticity": "Plasticity", "blender": "Blender",
             "autocad": "AutoCAD"}


def app_display_name(profile):
    """A profile's name for people ("Figma", "AutoCAD"): Karl's names are capitals."""
    pid = getattr(profile, "id", None)
    if pid in APP_NAMES:
        return APP_NAMES[pid]
    name = str(getattr(profile, "name", "") or pid or "")
    return name[:1].upper() + name[1:].lower()


def fit_copy(copy_id, line=LINE_META, **fields):
    """``copy_id`` filled and fitted to ``line`` = (size, limit px): placeholder values are
    ellipsized first (longest first, U+2026), measured with the knob's own font metrics."""
    key = (copy_id, line, tuple(sorted((k, str(v)) for k, v in fields.items())))
    hit = _FIT_CACHE.get(key)
    if hit is not None:
        _FIT_CACHE.move_to_end(key)
        return hit
    size, limit = line
    values = {name: clean_text(str(value)) for name, value in fields.items()}
    text = copy_text(copy_id, **values)
    shortened = dict(values)
    guard = 0
    while measure(text, size) > limit and guard < 400:
        guard += 1
        name = max(shortened, key=lambda k: len(shortened[k]), default=None)
        if name is None or not shortened[name].rstrip("…"):
            break
        base = shortened[name].rstrip("…")
        shortened[name] = base[:-1].rstrip() + "…"
        text = copy_text(copy_id, **shortened)
    _FIT_CACHE[key] = text
    if len(_FIT_CACHE) > 1024:
        _FIT_CACHE.popitem(last=False)
    return text


def _clean_frame(frame):
    """Remove control characters from every text field and button label (outside metadata may
    carry newlines or tabs, which the device contract rejects in required fields)."""
    for name, value in frame.items():
        if isinstance(value, str):
            frame[name] = clean_text(value)
    for button in frame.get("buttons") or ():
        if isinstance(button, dict) and isinstance(button.get("label"), str):
            button["label"] = clean_text(button["label"])
    return frame


def _needs_login(lower):
    """An Apple Music sign-in/authorization failure (lower-cased status text). A never-connected
    Apple Music ("Connect Apple Music ...", outcome ``signin_needed``) is not one (DD-BUG-023)."""
    return "authorization" in lower or "credentials" in lower


def _signin_needed(error):
    """Apple Music was never connected on this PC (outcome ``signin_needed``, DD-BUG-023)."""
    return getattr(error, "outcome", None) == "signin_needed"


def _clamp(value, low, high):
    return max(low, min(high, value))


def _int(value, default=0):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _item_id(item):
    return str(item.get("id", "")) if isinstance(item, dict) else ""


def presenter_event_dict(event):
    """One section 11.4 presenter event as the dict the controller dispatches on, or None.

    K4's stage posts ``(kind, payload)`` tuples (``stage.presenter.Mailbox``); a ``system``
    payload names its own kind (``lock``, ``sleep``, ``display``, ``motion``), which becomes
    ``what`` and never replaces the event kind. The picker and the fakes post dicts, which pass
    through unchanged."""
    if isinstance(event, (tuple, list)) and len(event) == 2 and isinstance(event[0], str):
        kind, payload = event
        if isinstance(payload, dict):
            fields = dict(payload)
        else:
            fields = {} if payload is None else {"value": payload}
        inner = fields.pop("kind", None)
        if kind == "system" and "what" not in fields:
            fields["what"] = inner if inner is not None else fields.get("system", fields.get("value"))
        fields["kind"] = kind
        return fields
    return event if isinstance(event, dict) else None


def _descriptor(item):
    """An item as presenters receive it: the K4 section 13.2 art keys and the list fields; the
    raw Apple ``_resource`` never leaves the controller."""
    if not isinstance(item, dict):
        return None
    return {key: value for key, value in item.items() if not key.startswith("_")}


# ------------------------------------------------------------------ state objects
@dataclass
class RecentList:
    """The flat Recently Added list of one visit (section 5.2.2; shared by recent and the explorer)."""
    visit: int = 0
    apple_visit: int | None = None
    items: list = field(default_factory=list)
    total: int | None = None
    complete: bool = False
    next_offset: int = 0
    inflight: int | None = None
    inflight_lane: str = ""
    state: str = "loading"          # loading | ready | empty | signin | error
    signin_needed: bool = False     # state signin: never connected, not expired (DD-BUG-023)
    retry_at: float = 0.0
    rev: int = 0

    def count(self):
        if self.state in ("loading", "empty", "signin", "error"):
            return 0
        if self.total is not None and not self.complete:
            return max(self.total, len(self.items))
        return len(self.items)

    def item(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None


@dataclass
class FavouritesList:
    """Favourite playlists (section 9.8.5): session cache, refreshed after 600 s."""
    items: list = field(default_factory=list)
    state: str = "none"             # none | loading | ready | empty | signin | error
    signin_needed: bool = False     # state signin: never connected, not expired (DD-BUG-023)
    loaded_at: float | None = None
    focus_id: str | None = None
    inflight: int | None = None
    retry_at: float = 0.0
    backoff: int = 0
    meta: dict = field(default_factory=dict)      # playlist id -> playlist_meta result
    meta_inflight: dict = field(default_factory=dict)   # playlist id -> request
    rev: int = 0

    def count(self):
        return len(self.items) if self.state == "ready" else 0


@dataclass
class ExplorerState:
    source: str = "recent"
    index_by_source: dict = field(default_factory=dict)
    swap_until: float = 0.0
    swap_to: str | None = None
    play_until: float = 0.0
    sent: dict = field(default_factory=dict)      # what the last push carried (items window, state, count)


@dataclass
class SeekState:
    D: int = 1
    p0: int = 0
    n0: int = 0
    max: int = 0
    target_s: int = 0
    due: float | None = None
    inflight: int | None = None
    acked_s: int | None = None      # the target of the last jump sent: the one its job read at start
    landed_s: int | None = None     # the target of the jump that last landed in this burst
    fail_until: float = 0.0
    limit_until: float = 0.0
    idle_due: float = 0.0
    track_id: str | None = None
    left: bool = False              # Seek was left; results apply silently (C5-16)
    dropped: bool = False           # a track / group change or a disconnect dropped the target (C5-47)

    def t(self, n):
        return _clamp(self.p0 + SEEK_STEP_S * (n - self.n0), 0, max(0, self.D - SEEK_MARGIN_S))

    @property
    def busy(self):
        return self.inflight is not None or (self.landed_s is not None and self.target_s != self.landed_s)


@dataclass
class UpNextState:
    P: int = 1
    T: int = 0
    card: bool = False
    regime: str = "companion"
    rows: dict = field(default_factory=dict)      # 1-based row -> row dict
    loading: bool = True
    reads: list = field(default_factory=list)     # queued (start, count, purpose)
    read_inflight: int | None = None
    revision: str = ""
    enriched: set = field(default_factory=set)    # song ids asked for (catalog + ratings)
    ratings_failed: set = field(default_factory=set)
    context: dict | None = None
    sent_context: dict | None = None
    swap_until: float = 0.0
    play_until: float = 0.0
    armed_toast: str | None = None
    identity: tuple | None = None                 # focus identity kept across a re-read
    pending_regime: str | None = None             # a Sonos-shuffle regime change waiting for its window


@dataclass
class SnapJob:
    item_id: str
    side: str
    t0: float
    accepted: bool = False
    turned: bool = False


@dataclass
class WindowsState:
    items: list = field(default_factory=list)
    origin: dict | None = None
    left: str | None = None
    right: str | None = None
    desk_open: str | None = None
    snap_busy: SnapJob | None = None
    last_side: str | None = None
    latched_close: str | None = None
    failure: dict | None = None
    switch_request: int | None = None


@dataclass
class StartPending:
    request: int
    kind: str
    name: str
    accent: int
    source: str
    closed_at: float
    item_id: str = ""


@dataclass
class PlayNextJob:
    request: int
    item: dict
    name: str
    accent: int
    k: int = 0
    n: int | None = None
    phase: str = "resolving"


@dataclass
class ShuffleJob:
    request: int
    on: bool
    regime: str
    plan: list = field(default_factory=list)
    playnext_offsets: list = field(default_factory=list)
    accepted: bool = False
    t0: float = 0.0
    record_order: list = None        # [P3] on (companion): the base rows' signatures the record will hold


@dataclass
class TransientCopy:
    copy_id: str
    text: str
    tone: str
    until: float


@dataclass
class LightsState:
    """The Home Assistant light as the adapter last reported it (r3; README section 8 subset)."""
    configured: bool = False
    known: bool = False              # a state was ever read
    online: bool = False
    reason: str = "not_configured"   # not_configured | connecting | offline | auth | unavailable | ""
    on: bool = False
    bri: int = 0                     # 1..100 while on (0 off)
    last_bri: int = 0                # the level before the last off (turn-on by temperature uses it)
    kelvin: int | None = None
    min_k: int = KELVIN_MIN
    max_k: int = KELVIN_MAX
    supports_ct: bool = True
    name: str = ""                   # r3.1: the Home Assistant area's name (shown as the room label)
    count: int | None = None         # r3.1: the lights in that area (None: an adapter without it)
    detail: str = ""                 # r3.1: why the area is not usable ("no_lights", "area_missing", ...)
    on_count: int | None = None      # r3.1: the lights that are on
    members: list = field(default_factory=list)   # r3.1: [{entity_id, name, on, bri, kelvin, available}]
    scenes: list = field(default_factory=list)   # [{entity_id, type, label, running, bri?, kelvin?}]
    snapshot: bool = False
    scene_id: str | None = None      # the scene Desk Dial last ran (the title)
    scene_label: str = ""
    adjusted: bool = False           # changed by hand after that scene


@dataclass
class Screen:
    """One per mode entry (a new view_id per Screen).

    Compat for v6-era callers (release tooling, previews): ``pages=[page dicts]`` seeds the flat
    Recently Added list when the Screen is assigned to a controller, ``windows=<snapshot dict>``
    becomes a WindowsState and the old mode name ``volume`` means ``home``."""
    mode: str = "home"
    index: int = 0
    parent_index: int | None = None
    status: str = ""
    view_id: int = field(default_factory=lambda: next(_view_ids))
    explorer: ExplorerState | None = None
    seek: SeekState | None = None
    upnext: UpNextState | None = None
    windows: WindowsState | None = None
    recent: RecentList | None = None
    pages: list = field(default_factory=list)

    def __post_init__(self):
        if self.mode == "volume":
            self.mode = "home"
        if isinstance(self.windows, dict):
            snapshot = self.windows
            self.windows = WindowsState(items=[dict(item) for item in snapshot.get("items") or ()],
                                        origin=snapshot.get("origin"))
        self._legacy_pages = list(self.pages) if self.pages else None
        self.pages = []

    @property
    def loading(self):
        """Compat (status.json): the knob list waits for its first page."""
        return bool(self.mode in ("recent", "explorer") and self.recent is not None
                    and self.recent.state == "loading")

    @property
    def page(self):
        return 0


# ------------------------------------------------------------------ the controller
class Controller:
    def __init__(self, clock=time.perf_counter, rng=None):
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self.screen = Screen()
        self.control_id = 0
        self.ready = True
        self.hardware = False
        self.effects = []
        self.pending = {}
        self.serial = 0
        self.state = {"online": False, "volume": 0, "group_label": "Speaker",
                      "group_revision": "", "title": "", "artist": "",
                      "can_next": False, "can_previous": False,
                      "can_play": False, "can_pause": False, "playback": "UNKNOWN"}
        self.state_known = False
        self._state_at = 0.0
        self._intent_lock = threading.Lock()
        self._volume_intent = (None, "")
        self._seek_lock = threading.Lock()
        self._seek_targets = {}          # seek request -> latest target (read at job start)
        self._seek_read = {}             # seek request -> the target its job read when it started
        self.volume_request = None
        self.volume_due = 0.0
        self.last_volume_write = -10.0
        self._volume_reveal_until = 0.0
        self._volume_reveal_source = ""
        self._external_until = 0.0
        self._album_start_until = 0.0
        self.last_poll = -10.0
        self.command_request = None      # the Home play/pause or the Tracks skip that is out
        self.button_order = [0, 1, 2, 3]
        self.windows_hid_enabled = True
        self.notice = ""
        self.decorate = None
        self.accent_lookup = None        # runtime hook: (kind, item) -> 0xRRGGBB (section 10.4)
        self.feedback = None
        self.feedback_seq = 0
        # r4: the newest haptic event ({token, seq}, in every frame until the next; the knob plays each seq once),
        # the time of the last buzz per token (refuse / error at most once a second), and whether the knob runs
        # the r4 feel (capabilities.feel, set by the runtime: Onshape's modifiers then re-enter for fluid.light).
        self.haptic = None
        self.haptic_seq = 0
        self._haptic_buzz_at = {}
        self.feel_supported = False
        self._started_seq = None         # the `started` feedback whose first frame omits playing
        self._decorate_failed = False
        self.reduced_motion = False
        self.music_signin_expired = False
        self.upnext_button3 = "like"     # settings.json `upnext_button3` (no UI)
        self.ledger = QueueLedger(autosave=False)
        # Controller-wide state (section 2.2).
        self.recent = RecentList()
        self.favourites = FavouritesList()
        self.start = None
        self.play_next_job = None
        self.shuffle_job = None
        # [P3] The companion-shuffle restore record's base rows (signature digests, their order at
        # Shuffle on) when known: from this controller's own accepted Shuffle on, or the record the
        # runtime loaded at start (`shuffle_record`). The Shuffle-off preview ranks by it (K3 9.5.3).
        self.shuffle_record_order = None
        self.move_next_request = None
        self.like_inflight = set()
        self.transient = None
        self.due = []                    # (at, cause, view_id, fn)
        self.last_knob_input = self.clock()
        self._last_detent = -10.0
        self._detent_dir = 1
        self._home_arrived_at = -10.0    # r3: the last arrival at the launcher (overshoot guard)
        self._passive = None             # (cause, view_id): a passive re-entry waiting for quiet
        self._preresolve_due = None
        self._preresolve_batch = 0
        self._preresolve_sent = set()    # (kind, id) asked for pre-resolution and maybe still queued
        self._toasts = []                # (at, text): exit toasts due
        self._seek_bg = None             # SeekState still landing after Seek was left
        self._neighbours = {}            # Tracks neighbour titles per (queue_revision, P)
        self._neighbours_request = None
        self._cancel_pending = None      # the picker close waiting for cancel_result
        self.last_reentry_cause = ""
        self.origin = None               # compat: v6 Windows origin (never a resumable Screen)
        # r3 (presentation >= 6): the spaces navigation and the Lights space. Off = r2.2 exactly.
        self.spaces = False
        self.lights = LightsState()
        self.lights_mode = "bri"         # bri | temp (README 1.2: knob modes, not menus)
        self._lights_lock = threading.Lock()
        self._lights_intent = {}         # {"bri": 1..100, "kelvin": K}: the newest unsent / in-flight target
        self.lights_request = None       # the lights_set in flight
        self.lights_due = 0.0
        self.last_lights_write = -10.0
        self.lights_command = None       # the lights_power / scene_run in flight
        self._lights_reveal_until = 0.0
        self._lights_reveal_kind = "bri"
        self._lights_reveal_source = ""
        self._lights_expect = None       # (values, until): our own write's echo
        self._lights_reported = {}       # the adapter's last on / bri / kelvin, before the echo mask
        self._lights_final = None        # (values, t, settled): the last write's applied values
        self._lights_reconcile = False   # the next lights_set is the settle write (no fade)
        self._mixed_shown = None         # the area's uniform / mixed look as shown (held while the knob drives)
        self._scene_settle_until = 0.0
        self.last_lights_poll = -10.0
        self._knob_bounds = None         # (min, max, position) the knob holds (entry or its last turn)
        # r3.1 (2026-09-29): hold 4 swaps the launcher's knob (kept for the session); the Recently
        # Added list's source (button 3) with each source's focus; the whole-queue Tracks row cache.
        self.home_domain = "volume"
        self.list_source = "recent"
        self._list_index = {"recent": 0, "favourites": 0}
        self._tracks_rows = {}           # 1-based row -> row dict, for `_tracks_revision`
        self._tracks_revision = None
        self._tracks_pages = {}          # page start (0-based) -> the queue_window request in flight
        self._tracks_retry_at = 0.0
        self._tracks_is_queue = False    # the Tracks regime of the last entry (whole queue / transport)
        # A0 Onshape mode (ONSHAPE.md): the knob profile the runtime chose from the inventory, the key
        # grammar (a turn drops a key's tap and hold; 3+ keys down = the Home chord), the refusal line, the user
        # exits (all four held 1.0 s, the tray: Auto waits for Onshape to lose and regain the foreground), Auto's
        # pending switch and when all four buttons went down (the Home chord's start; None = not all four down).
        self.onshape_profile = PROFILES["onshape"]
        # DD-BUG-004: the knob's installed profile names (None until a connected inventory says) and the
        # required names it lacks (each control then uses a stand-in, never a name the device refuses).
        self.installed_profiles = None
        self.missing_profiles = ()
        self.onshape_keys = KeyTracker()
        self.onshape_pending = False
        self.onshape_user_exits = 0
        self._onshape_refused_until = 0.0
        self._onshape_refused_kind = "refused"
        self._onshape_chord_at = None
        # A2 (ONSHAPE.md section 10): the injector's wheel / parameter / echo state (onshape.OnshapeInjector
        # .app_state(), set by the runtime every tick for a knob with the app canvas; None otherwise) and the keys
        # pressed while the wheel or parameter mode owned them (their tap shows nothing).
        self.onshape_app = None
        self._onshape_swallowed = set()
        self._onshape_wheel = None         # the control id under which 3's press opened the wheel (OnshapeApp.down)
        self._onshape_param_left_at = None # when 3's release ended parameter mode (the snapshot lags the injector)
        # App profiles (plan 3, S1 DD-B): the "onshape" screen is the app mode of every profile. `app_profile` is the
        # active app_profiles.AppProfile (None = Onshape, presented exactly as before); `app_canvas_ref` the (id, crc)
        # the knob has loaded for it (the runtime sets it once an upload is confirmed; None = the text screen).
        self.app_profile = None
        self.app_canvas_ref = None
        self._enter("startup")

    # ------------------------------------------------------------------ the current Screen
    @property
    def screen(self):
        return self._screen

    @screen.setter
    def screen(self, screen):
        """Every Screen goes through here: list modes share the controller-wide lists."""
        legacy = getattr(screen, "_legacy_pages", None)
        if legacy is not None and screen.mode in ("recent", "explorer"):
            items = [dict(item) for page in legacy if isinstance(page, dict)
                     for item in page.get("items") or () if isinstance(item, dict)]
            complete = not (legacy and isinstance(legacy[-1], dict) and legacy[-1].get("next"))
            previous = getattr(self, "recent", None)
            self.recent = RecentList(visit=(previous.visit + 1) if previous else 1, items=items, total=None,
                                     complete=complete, state="ready" if items else "empty",
                                     next_offset=len(items))
            screen._legacy_pages = None
        if screen.mode in ("recent", "explorer") and hasattr(self, "recent"):
            screen.recent = self.recent
        if screen.mode == "explorer" and screen.explorer is None:
            screen.explorer = ExplorerState(index_by_source={"recent": screen.index})
        if screen.mode == "windows" and screen.windows is None:
            screen.windows = WindowsState()
        if screen.mode == "upnext" and screen.upnext is None:
            P, T = self._position() if hasattr(self, "state") else (1, 0)
            screen.upnext = UpNextState(P=max(1, P), T=T, loading=True)
        if screen.mode == "seek" and screen.seek is None:
            screen.seek = SeekState()
        self._screen = screen

    # ------------------------------------------------------------------ effects
    def request(self, kind, **payload):
        """A service effect: pending until complete()."""
        self.serial += 1
        effect = {"kind": kind, "request": self.serial,
                  "control_id": self.control_id, "view_id": self.screen.view_id, **payload}
        self.pending[self.serial] = effect
        self.effects.append(effect)
        return self.serial

    def _present(self, kind, **payload):
        """A presenter effect (posted, never completed; section 11.1)."""
        self.serial += 1
        effect = {"kind": kind, "request": self.serial,
                  "control_id": self.control_id, "view_id": self.screen.view_id, **payload}
        self.effects.append(effect)
        return effect

    def drain(self):
        effects, self.effects = self.effects, []
        return effects

    def forget(self, effect):
        """An unsent write effect the runtime dropped (section 10.2): never replayed, and every
        job reference to it is released (busy dims, pending spans, in-flight guards)."""
        request = effect.get("request")
        self.pending.pop(request, None)
        if self.volume_request == request:
            self.volume_request = None
        if self.command_request == request:
            self.command_request = None
        if self.start is not None and self.start.request == request:
            self.start = None
        if self.play_next_job is not None and self.play_next_job.request == request:
            self.play_next_job = None
        if self.shuffle_job is not None and self.shuffle_job.request == request:
            self.shuffle_job = None
        if self.move_next_request == request:
            self.move_next_request = None
        if effect.get("kind") == "like":
            self.like_inflight.discard(str(effect.get("song_id")))
        for seek in (self.screen.seek, self._seek_bg):
            if seek is not None and seek.inflight == request:
                seek.inflight = None
                seek.acked_s = None
        if effect.get("kind") == "seek":
            with self._seek_lock:
                self._seek_targets.pop(request, None)
                self._seek_read.pop(request, None)
        if self.screen.windows is not None and self.screen.windows.switch_request == request:
            self.screen.windows.switch_request = None
        if self.lights_request == request:
            self.lights_request = None
        if self.lights_command == request:
            self.lights_command = None

    # ------------------------------------------------------------------ intents (lane handoffs)
    @property
    def display_volume(self):
        return int(self.desired_volume if self.desired_volume is not None else self.state["volume"])

    @property
    def desired_volume(self):
        with self._intent_lock:
            return self._volume_intent[0]

    @desired_volume.setter
    def desired_volume(self, value):
        with self._intent_lock:
            self._volume_intent = (value, self.state.get("group_revision", ""))

    def volume_intent(self):
        """Atomic worker handoff: current target and the group it belongs to."""
        with self._intent_lock:
            return self._volume_intent

    def lights_intent(self):
        """Atomic worker handoff (the volume pattern): the newest brightness / temperature target,
        read when the `lights_set` job starts, so a burst of detents sends only its latest value."""
        with self._lights_lock:
            return dict(self._lights_intent)

    def _set_lights_intent(self, **values):
        with self._lights_lock:
            self._lights_intent.update(values)

    def _clear_lights_intent(self, applied=None):
        """Drop the targets `applied` reached (all of them without `applied`)."""
        with self._lights_lock:
            if applied is None:
                self._lights_intent = {}
                return
            for key, value in applied.items():
                if value is not None and self._lights_intent.get(key) == value:
                    del self._lights_intent[key]

    @property
    def display_bri(self):
        intent = self.lights_intent()
        if "bri" in intent:
            return intent["bri"]
        return self.lights.bri if self.lights.on else 0

    @property
    def display_kelvin(self):
        intent = self.lights_intent()
        if "kelvin" in intent:
            return intent["kelvin"]
        kelvin = self.lights.kelvin
        return kelvin if type(kelvin) is int else _clamp(KELVIN_DEFAULT, self.lights.min_k, self.lights.max_k)

    def lights_display_on(self):
        return bool(self.lights_intent()) or self.lights.on

    def seek_target(self, effect):
        """The newest target of a `seek` job, read when the job starts (the volume pattern). The
        value read is remembered: it is the target that jump lands on (section 5.5.4)."""
        request = effect.get("request")
        with self._seek_lock:
            target = self._seek_targets.get(request, effect.get("target_s"))
            if request is not None:
                self._seek_read[request] = target
            return target

    @property
    def windows_button(self):
        """The raw button of the Win slot (VOC section 2.5): never a literal. r2.2: slot 3 (Home 4);
        r3: slot 1 (the launcher's 2 Windows)."""
        return self.button_order[self._windows_slot()]

    def _windows_slot(self):
        """The logical slot whose press opens the picker: r3's launcher 2, r2.2's Home 4."""
        return 1 if self.spaces else 3

    @windows_button.setter
    def windows_button(self, _value):
        pass  # derived from button_order (K3 section 3.1 notes)

    # ------------------------------------------------------------------ state queries
    def source(self):
        source = self.state.get("source")
        if source in SOURCES:
            return source
        # A state without the section 9.1 class (an older adapter or fake): the queue only when
        # its rows are known, a stream otherwise.
        if not self.has_media():
            return "none"
        return "queue" if self.state.get("queue_length") else "radio"

    def has_media(self):
        """Streams can play with an empty queue and without a supplied title."""
        return bool(self.state.get("playback") in ("PLAYING", "PAUSED_PLAYBACK")
                    or any(self.state.get(name) for name in
                           ("can_play", "can_pause", "can_next", "can_previous"))
                    or self.state.get("queue_length", 0))

    def _position(self):
        """(P, T): the 1-based playing row and the queue length."""
        total = _int(self.state.get("queue_length"), 0)
        position = _int(self.state.get("playlist_position"), 0)
        if position <= 0 and total:
            position = 1
        return position, total

    def shuffle_active(self):
        return bool(self.state.get("companion_shuffle") or self.state.get("shuffle")
                    or self.state.get("play_mode") in SHUFFLE_PLAY_MODES)

    def sonos_shuffle(self):
        return bool(self.state.get("shuffle") or self.state.get("play_mode") in SHUFFLE_PLAY_MODES)

    def playback_action(self):
        """Choose an absolute action from confirmed state, never a blind toggle."""
        playback = self.state.get("playback")
        direction = "pause" if playback == "PLAYING" else "play"
        stable = playback in ("PLAYING", "PAUSED_PLAYBACK", "STOPPED")
        enabled = bool(self.state["online"] and stable and not self.command_request
                       and self.state.get("can_" + direction))
        return direction, enabled

    def confirmed_playing(self):
        """A Home frame's `playing` (ALIVE.md section 3, R3/R4), or None to omit it."""
        if not self.state_known or not self.state.get("online"):
            return None
        if self.start is not None:
            return None   # K2 M16: omitted while a start is pending
        playback = self.state.get("playback")
        if playback == "PLAYING":
            return True
        if playback not in ("PAUSED_PLAYBACK", "STOPPED"):
            return None
        if self._album_start_until and self.clock() < self._album_start_until:
            return None
        return False

    def _home_command(self):
        command = self.pending.get(self.command_request)
        if command and command.get("kind") == "transport" and command.get("direction") in ("play", "pause"):
            return command
        return None

    def _skip_command(self):
        command = self.pending.get(self.command_request)
        if command and command.get("kind") == "transport" and command.get("direction") in ("previous", "next"):
            return command
        return None

    def _busy_code(self):
        """The running exclusive queue action's busy code (section 2.3), or None."""
        if self.start is not None:
            return "starting"
        if self.play_next_job is not None or self.move_next_request is not None:
            return "queueing"
        if self.shuffle_job is not None:
            return "shuffling"
        return None

    def _overlay_open(self):
        return self.screen.mode in ("explorer", "upnext", "windows") or any(
            effect.get("kind") == "windows_open" for effect in self.pending.values())

    def _accent(self, kind, item):
        """0xRRGGBB accent of an entry; 0 (warm) when unknown."""
        if not isinstance(item, dict):
            return 0
        lookup = self.accent_lookup
        if lookup is not None:
            try:
                value = lookup(kind, item)
                if type(value) is int and 0 <= value <= 0xFFFFFF:
                    return value
            except Exception:  # presentation is never fatal
                pass
        value = item.get("accent")
        return value if type(value) is int and 0 <= value <= 0xFFFFFF else 0

    # ------------------------------------------------------------------ entering (section 6)
    def _enter(self, cause=""):
        self.control_id += 1
        self.ready = not self.hardware
        self.last_reentry_cause = cause
        self._passive = None
        control = self.control()
        self._knob_bounds = (control["min"], control["max"], control["position"])
        if self.screen.mode == "tracks":
            self._tracks_is_queue = self._tracks_queue()
        self.effects.append({"kind": "device_enter", "control": control})

    def _reenter(self, cause, index=None):
        """One control for one host-driven move; `index` clamped into the new bounds."""
        if index is not None:
            self.screen.index = index
        low, high, _ = self.bounds()
        if self.screen.mode not in VOLUME_MODES + ("lights", "onshape"):
            self.screen.index = _clamp(self.screen.index, low, high)
        self._enter(cause)

    def _schedule(self, at, cause, fn, *, any_screen=False):
        """Run fn in tick() at `at` if the Screen that scheduled it is still current."""
        self.due.append((at, cause, None if any_screen else self.screen.view_id, fn))

    def _cancel_due(self, view_id):
        self.due = [entry for entry in self.due if entry[2] != view_id]

    def _run_due(self, now):
        ready = [entry for entry in self.due if entry[0] <= now]
        if not ready:
            return
        self.due = [entry for entry in self.due if entry[0] > now]
        for at, cause, view_id, fn in sorted(ready, key=lambda entry: entry[0]):
            if view_id is not None and view_id != self.screen.view_id:
                continue
            try:
                fn()
            except Exception:  # a presentation timer is never fatal
                _log.exception("Controller timer %s failed", cause)

    def _request_passive(self, cause, *, now_if_waiting=False):
        """Section 6.4: a re-entry the user did not cause waits 400 ms after the last detent."""
        if now_if_waiting or self.clock() - self._last_detent >= PASSIVE_QUIET:
            self._reenter(cause)
        else:
            self._passive = (cause, self.screen.view_id)

    def _run_passive(self, now):
        if self._passive is None:
            return
        cause, view_id = self._passive
        if view_id != self.screen.view_id:
            self._passive = None
            return
        if now - self._last_detent >= PASSIVE_QUIET:
            self._passive = None
            self._reenter(cause)

    def _new_screen(self, mode, index=0, cause="", **fields):
        self._cancel_due(self.screen.view_id)
        if self.spaces:
            self.transient = None   # r3.1 design (`go`): a new screen starts without the old message
        if mode == "launcher" and self.screen.mode != "launcher":
            self._home_arrived_at = self.clock()   # README 1: the overshoot guard's arrival
        self.screen = Screen(mode=mode, index=index, **fields)
        if mode in ("recent", "explorer"):
            self.screen.recent = self.recent
        if mode in OVERLAY_MODES:
            # Every overlay entry re-arms the 60 s lifetime idle (section 13.1): the press that
            # opened it (a knob button, or the Win button's F24) is the overlay's first input.
            self.last_knob_input = self.clock()
        self._enter(cause or mode)

    def _go_home(self, cause="home"):
        """To `home`: r2.2's Home, r3's Music space (Back from Recently Added / Tracks)."""
        if self.screen.mode == "seek":
            self._leave_seek(flush=True)
        self._new_screen("home", self.display_volume, cause)

    def _root(self):
        """The Home of the navigation: r3's launcher, r2.2's Home."""
        return "launcher" if self.spaces else "home"

    def _go_root(self, cause="home"):
        """Hold 1, the picker's Back / Switch and every "Home from anywhere" (r3: the launcher)."""
        if self.screen.mode == "seek":
            self._leave_seek(flush=True)
        self._new_screen(self._root(), self.display_volume, cause)

    def set_spaces(self, on):
        """r3 navigation on (presentation >= 6) or off (r2.2 exactly). Leaves a space the other
        navigation does not have for its Home; the caller's next entry (set_hardware) sends it."""
        on = bool(on)
        if on == self.spaces:
            return
        self.spaces = on
        if self.screen.mode in ("launcher", "onshape") + LIGHTS_MODES and not on:
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode="home", index=self.display_volume)
        elif on and self.screen.mode == "home":
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode="launcher", index=self.display_volume)

    # ------------------------------------------------------------------ bounds and control
    # ------------------------------------------------------------------ r3.1 helpers
    def _lights_domain(self):
        """r3.1: the launcher's knob sets the Lights area's brightness (hold 4 swapped it)."""
        return bool(self.spaces and self.screen.mode == "launcher" and self.home_domain == "lights")

    def _lights_knob(self):
        """The knob sets the lights now: the Lights space, or the launcher in its lights domain."""
        return self.screen.mode == "lights" or self._lights_domain()

    def _lights_knob_mode(self):
        """bri | temp of the lights knob: the launcher's lights domain is always brightness."""
        return self.lights_mode if self.screen.mode == "lights" else "bri"

    def _recent_source(self):
        """The knob list's source: r3 toggles Recently Added / Favourite playlists on button 3;
        r2.2 is always Recently Added (its button 3 is Play next)."""
        return self.list_source if self.spaces and self.list_source in LIST_SOURCES else "recent"

    def _shown_source(self):
        """The list source on screen (recent / explorer), else None."""
        mode = self.screen.mode
        if mode == "recent":
            return self._recent_source()
        if mode == "explorer" and self.screen.explorer is not None:
            return self.screen.explorer.source
        return None

    def _tracks_queue(self):
        """r3.1 whole-queue Tracks: the knob browses rows 1..T (the queue is the source)."""
        if not self.spaces or self.source() != "queue":
            return False
        return self._position()[1] > 0

    def _list_count(self):
        mode = self.screen.mode
        if mode == "recent":
            return self._source_count(self._recent_source())
        if mode == "explorer":
            return self._source_count(self.screen.explorer.source)
        if mode == "upnext":
            return self._upnext_count()
        if mode == "windows":
            return len(self.screen.windows.items) if self.screen.windows else 0
        return 0

    def _kelvin_range(self):
        low = _clamp(self.lights.min_k, KELVIN_MIN, KELVIN_MAX)
        high = _clamp(self.lights.max_k, low, KELVIN_MAX)
        return low, high

    def bounds(self):
        mode = self.screen.mode
        if mode == "onshape":
            return ONSHAPE_BOUNDS
        if mode in VOLUME_MODES and not self._lights_domain():
            return 0, 100, self.display_volume
        if self._lights_knob():
            if self._lights_knob_mode() == "temp":
                low, high = self._kelvin_range()
                count = (high - low) // KELVIN_STEP + 1
                return 0, count - 1, _clamp((self.display_kelvin - low) // KELVIN_STEP, 0, count - 1)
            # Brightness 1 % per detent. The control contract fixes min at 0 (device._enter and the
            # firmware refuse any other min). While on, 0..99 = 1..100 % (DD-DES-003: the wall sits at
            # the 1 % floor, no dead detent below it; All off turns the light off); from off 0..100,
            # position 0 = off and the first detent turns it on at 1 %. The LED ring's local cursor
            # (alive_lights._local / firmware cc_alive_local, style bri) must read the on frame as
            # value = position + 1 (max 99) and the off frame as value = position (max 100).
            if self.lights_display_on():
                return 0, BRI_ON_HIGH, _clamp(self.display_bri, 1, 100) - 1
            return 0, 100, 0
        if mode == "scenes":
            high = max(0, min(SCENES_MAX, len(self.lights.scenes)) - 1)
            return 0, high, _clamp(self.screen.index, 0, high)
        if mode == "tracks":
            if self._tracks_queue():
                T = self._position()[1]
                return 0, T - 1, _clamp(self.screen.index, 0, T - 1)
            return 0, 2, _clamp(self.screen.index, 0, 2)
        if mode == "seek":
            seek = self.screen.seek
            return 0, seek.max, _clamp(self.screen.index, 0, seek.max)
        high = max(0, self._list_count() - 1)
        return 0, high, _clamp(self.screen.index, 0, high)

    @staticmethod
    def required_profiles():
        """Every profile name a control can ask for (DD-BUG-004)."""
        return tuple(sorted(set(PROFILES.values()) | {LIGHTS_TEMP_PROFILE, QUEUE_PROFILE}))

    def set_installed_profiles(self, profiles):
        """The connected knob's inventory ({name: profile} or names; DD-BUG-004). Returns the required
        names it lacks; their controls then use the nearest installed stand-in (`_installed_profile`)."""
        if isinstance(profiles, dict):
            names = [name for name in profiles if isinstance(name, str)]
        elif isinstance(profiles, (list, tuple)):
            names = [name for name in profiles if isinstance(name, str)]
        else:
            names = []
        self.installed_profiles = tuple(names) if names else None
        if self.installed_profiles is None:
            self.missing_profiles = ()
        else:
            self.missing_profiles = tuple(name for name in self.required_profiles()
                                          if name not in self.installed_profiles)
            if self.missing_profiles:
                _log.warning("Knob inventory lacks %s; using installed stand-ins", ", ".join(self.missing_profiles))
        return self.missing_profiles

    def _installed_profile(self, name):
        """`name` when installed (or the inventory is unknown), else its nearest installed stand-in."""
        installed = self.installed_profiles
        if not installed or name in installed:
            return name
        for other in PROFILE_FALLBACKS.get(name, ()):
            if other in installed:
                return other
        return installed[0]

    @property
    def profile_status(self):
        """A precise status line while required profiles are missing ('' when all are installed)."""
        if not self.missing_profiles:
            return ""
        used = sorted({self._installed_profile(name) for name in self.missing_profiles})
        return PROFILE_MISSING_STATUS.format(names=", ".join(self.missing_profiles), used=", ".join(used))

    def control(self):
        low, high, position = self.bounds()
        profile = PROFILES[self.screen.mode]
        if self.screen.mode == "lights" and self.lights_mode == "temp":
            profile = LIGHTS_TEMP_PROFILE
        elif self.screen.mode == "tracks" and self._tracks_queue():
            profile = QUEUE_PROFILE   # r3.1: the whole queue, one row per detent
        elif self.screen.mode == "onshape":
            profile = self.onshape_profile or PROFILES["onshape"]
        profile = self._installed_profile(profile)
        return {"id": self.control_id, "profile": profile, "feel": self.feel(),
                "min": low, "max": high, "position": position,
                # The Win slot's raw button sends F24 (the knob's icon gate: that slot shows `win`).
                # F24 is what opens the picker: the WM_HOTKEY grant is the only way Windows lets
                # the picker take the foreground (a serial press alone is refused focus). r2.2:
                # Home 4; r3: the launcher's 2 Windows (button 4 is Play/Pause there, never F24).
                "windowsButton": self.windows_button, "buttonOrder": self.button_order[:],
                "windowsHidEnabled": bool(self.windows_hid_enabled and self.screen.mode == self._root()),
                "frame": self.frame(assume_ready=True)}

    # ------------------------------------------------------------------ transient copy (section 2.4)
    def _set_transient(self, copy_id, *, tone="meta", ms=REASON_META, text=None, **fields):
        """Show copy on the current screen's copy line; the id's twin follows the line."""
        home = self.screen.mode in VOLUME_MODES
        if home and copy_id.startswith("knob.meta.") and copy_id.replace("knob.meta.", "knob.status.") in COPY:
            copy_id = copy_id.replace("knob.meta.", "knob.status.")
        elif not home and copy_id.startswith("knob.status.") and copy_id.replace("knob.status.", "knob.meta.") in COPY:
            copy_id = copy_id.replace("knob.status.", "knob.meta.")
        line = LINE_STATUS if copy_id.startswith("knob.status.") else LINE_META
        if text is None:
            text = fit_copy(copy_id, line, **fields)
        self.transient = TransientCopy(copy_id, text, tone, self.clock() + ms)

    def _transient(self):
        transient = self.transient
        if transient is None:
            return None
        if self.clock() >= transient.until:
            self.transient = None
            return None
        return transient

    def _feedback(self, kind, skip=0, *, moment=None, side=None, color=None, haptic=None):
        """Arm a moment: a new seq plays exactly once (VOC section 4). r4: it also arms its haptic event
        (`haptic` a token to override the default of _feedback_haptic, False for none)."""
        if haptic is not False:
            self._haptic(haptic or self._feedback_haptic(kind, skip, moment, side))
        self.feedback_seq = self.feedback_seq % FEEDBACK_SEQ_MAX + 1
        self.feedback = {"kind": kind, "seq": self.feedback_seq}
        if kind == "err" and moment == "refused":
            self.feedback["moment"] = "refused"   # r3 (presentation 6): the unavailable-press flash
        elif kind == "ok" and skip in (-1, 1):
            self.feedback["skip"] = skip
        elif kind == "ok" and moment:
            self.feedback["moment"] = moment
            if moment == "snap" and side in (-1, 1):
                self.feedback["side"] = side
            if moment in ("snap", "started") and type(color) is int and color:
                self.feedback["color"] = color
            if moment == "started":
                self._started_seq = self.feedback_seq

    # ------------------------------------------------------------------ r4 feel and haptics
    def feel(self, mode=None):
        """The r4 feel token of the current screen (r4 section 4.4): Home music volume detent.value; Home lights /
        Lights brightness detent.dimmer, temperature detent.fine; Recently Added / Playlists detent.list (free.spin
        over FREE_SPIN_MIN_ITEMS items); Tracks / Up next detent.list; Seek fluid.scrub; Windows / Scenes
        detent.coarse; Onshape detent.value to zoom, fluid.light while a modifier (tilt / orbit / pan) is held."""
        mode = self.screen.mode if mode is None else mode
        if mode == "onshape":
            return "fluid.light" if self._onshape_fluid() else "detent.value"
        if mode == self.screen.mode and self._lights_knob():
            return "detent.fine" if self._lights_knob_mode() == "temp" else "detent.dimmer"
        if mode in VOLUME_MODES:
            return "detent.value"
        if mode == "seek":
            return "fluid.scrub"
        if mode in ("windows", "scenes"):
            return "detent.coarse"
        if mode in ("recent", "explorer"):
            return "free.spin" if self._list_count() > FREE_SPIN_MIN_ITEMS else "detent.list"
        if mode in ("tracks", "upnext"):
            return "detent.list"
        return "detent.value"

    def _onshape_fluid(self):
        """Onshape: a held modifier drags (fluid.light), the way the injector reads it: never while the command
        wheel or parameter mode owns the knob, nor for a swallowed key (a ring switch / a parameter step), so those
        keys never re-enter (a re-entry re-activates the injector, which would close the wheel / parameter mode)."""
        slot = self.onshape_keys.modifier_slot()
        if self.app_profile is not None:
            # App profiles: a drag slot (held, or the knob alone: Plasticity's zoom) is fluid; wheel / keys slots click.
            spec = self.app_profile.slots.get("knob") if slot is None else slot_of_button(self.app_profile, slot)
            if spec is None or spec.kind != "drag" or (slot is not None and slot in self._onshape_swallowed):
                return False
            return not (self._onshape_wheel_open() or self._onshape_param_on())
        if slot is None or slot in self._onshape_swallowed:
            return False
        return not (self._onshape_wheel_open() or self._onshape_param_on())

    def _onshape_wheel_open(self):
        """The command wheel is open, as OnshapeApp.down / up / chord / seed track it: 3 went down with none of 1 / 2 / 4
        down and parameter mode off, and it is still down under the same control (a re-activation resets the app)."""
        return self._onshape_wheel is not None and self._onshape_wheel == self.control_id \
            and self.onshape_app is not None and self.onshape_keys.is_down(self._app_wheel_button())

    def _app_wheel_button(self):
        """The logical button that holds the command wheel open: 3 for Onshape, the profile's commands slot otherwise
        (None: the profile has no wheel)."""
        return 2 if self.app_profile is None else wheel_button(self.app_profile)

    def _onshape_param_on(self):
        """Parameter mode is on: the injector's snapshot says so, unless 3's release just ended it (the snapshot is
        polled once a tick, so it may still show `param` for a moment)."""
        app = self.onshape_app
        if not isinstance(app, dict) or "param" not in app:
            return False
        left = self._onshape_param_left_at
        return left is None or self.clock() - left >= ONSHAPE_PARAM_LAG

    def _haptic(self, token):
        """Arm a haptic event (r4 4.2): a new seq plays exactly once on a hapticFx knob (every later frame carries
        it until the next). refuse.buzz and error.buzz at most once a second each (the knob enforces it too)."""
        if token not in HAPTIC_TOKENS:
            return
        if token in ("refuse.buzz", "error.buzz"):
            now = self.clock()
            last = self._haptic_buzz_at.get(token)
            if last is not None and now - last < HAPTIC_BUZZ_GAP:
                return
            self._haptic_buzz_at[token] = now
        self.haptic_seq = self.haptic_seq % FEEDBACK_SEQ_MAX + 1
        self.haptic = {"token": token, "seq": self.haptic_seq}

    @staticmethod
    def _feedback_haptic(kind, skip, moment, side):
        """The haptic event a feedback moment carries by default (r4 4.4): refusals buzz, errors buzz slower; a
        skip or a window snap nudges its way; a queue landing and a started list thump; the rest ticks."""
        if kind == "err":
            return "refuse.buzz" if moment == "refused" else "error.buzz"
        if skip in (-1, 1):
            return "nudge.right" if skip == 1 else "nudge.left"
        if moment == "snap":
            return "nudge.left" if side == -1 else "nudge.right"
        if moment in ("queued", "started"):
            return "confirm.thump"
        return "confirm.tick"

    # ------------------------------------------------------------------ toasts (section 12)
    def _toast(self, copy_id, **fields):
        """A toast now: dropped while an overlay is open (rule 1)."""
        if self._overlay_open():
            return
        self._present("toast", text=copy_text(copy_id, **fields), exit=False)

    def _exit_toast(self, copy_id, close_at, **fields):
        """An overlay's exit toast: at max(close + 360 ms, now) (rules 2 and 7)."""
        now = self.clock()
        at = max(close_at + EXIT_TOAST_DELAY, now)
        text = copy_text(copy_id, **fields)
        if at <= now:
            if not self._overlay_open():
                self._present("toast", text=text, exit=True)
            return
        self._toasts.append((at, text))

    def _run_toasts(self, now):
        if not self._toasts:
            return
        due = [entry for entry in self._toasts if entry[0] <= now]
        self._toasts = [entry for entry in self._toasts if entry[0] > now]
        for _at, text in due:
            if self._overlay_open():
                continue  # another overlay is open at that moment: dropped
            self._present("toast", text=text, exit=True)

    # ------------------------------------------------------------------ public input API (section 2.5)
    def _accepts(self, control_id):
        return self.ready and (control_id is None or control_id == self.control_id)

    def _play_window(self, now):
        explorer, upnext = self.screen.explorer, self.screen.upnext
        return bool((explorer and now < explorer.play_until) or (upnext and now < upnext.play_until))

    def position(self, position, control_id=None):
        if not self._accepts(control_id) or type(position) is not int:
            return
        low, high, current = self.bounds()
        if self._lights_bri_frame() is not None:
            # DD-DES-003: brightness has two frames (on 0..99, off 0..100); a detent reads in the frame the
            # knob holds (its control or last turn) until a re-entry moves it to the other one.
            low, high, current = self._knob_bounds
        if not low <= position <= high or position == current:
            return
        now = self.clock()
        mode = self.screen.mode
        if mode == "onshape":
            # The injector turns detents into input; the controller only re-centres the knob's control.
            self.last_knob_input = self._last_detent = now
            if abs(position - ONSHAPE_BOUNDS[2]) > ONSHAPE_RECENTRE:
                self._request_passive("onshape recentre")
            return
        if self._play_window(now):
            return
        if mode == "explorer" and now < self.screen.explorer.swap_until:
            return  # positions of the old source's control are discarded (section 5.3.3)
        if mode == "upnext" and now < self.screen.upnext.swap_until:
            return
        self.last_knob_input = now
        self._detent_dir = 1 if position > current else -1
        self._last_detent = now
        if self._lights_knob():
            self._lights_turn(position, low, high, now)
            return
        if mode in VOLUME_MODES:
            if not self.state["online"] or self.onshape_pending:
                # A0: Sonos volume ignores the knob while a switch to Onshape is pending. DD-BUG-003: the
                # knob's absolute position moved anyway, so it is re-anchored at the shown volume once it
                # rests (else the first detent after Sonos returns jumps the volume to the drifted spot).
                self._request_passive("ignored turn")
                return
            self.desired_volume = position
            self._reveal_volume(VOLUME_REVEAL_SECONDS, "local")
            self._external_until = 0.0
            self.volume_due = max(now, self.last_volume_write + 0.1)
            return
        self.screen.index = position
        if self.spaces and mode in ("tracks", "upnext", "windows") and self.transient is not None:
            self.transient = None   # r3 (README 2.2): a turn on these screens clears the message line
        if mode == "recent":
            if self._recent_source() == "favourites":
                self._favourites_moved()
            else:
                self._recent_moved()
        elif mode == "explorer":
            self._explorer_moved()
        elif mode == "tracks":
            if self._tracks_queue():
                self._tracks_fetch()
        elif mode == "scenes":
            pass
        elif mode == "seek":
            seek = self.screen.seek
            seek.target_s = seek.t(position)
            if not self.spaces:
                seek.due = now + SEEK_DEBOUNCE   # r2.2: the live scrub (r3 applies it on Set only)
            seek.idle_due = now + SEEK_IDLE
            # A turn during a jump only moves the frozen target (C5-68). A job still queued on
            # the audio lane reads this newest target when it starts (the volume pattern).
            if seek.inflight is not None:
                with self._seek_lock:
                    self._seek_targets[seek.inflight] = seek.target_s
        elif mode == "upnext":
            self._present("upnext_highlight", index=position, control_id=self.control_id, bump=0)
            self._upnext_refill()
        elif mode == "windows":
            windows = self.screen.windows
            if windows.snap_busy is not None:
                windows.snap_busy.turned = True
            if windows.switch_request is None:
                self._present("windows_highlight", index=position, control_id=self.control_id, bump=0)

    def turn(self, delta):
        """A host-side turn (simulator, picker keys without a knob session)."""
        low, high, current = self.bounds()
        self.position(_clamp(current + delta, low, high))

    def button(self, logical, control_id=None, hid=False):
        if not self._accepts(control_id) or logical not in (0, 1, 2, 3):
            return
        if hid:
            return  # this press also sent F24: the hotkey path already acted (VOC section 2.5)
        now = self.clock()
        if self._play_window(now):
            return  # every button and hold (C5-9)
        self.last_knob_input = now
        mode = self.screen.mode
        if self._silent_guard(mode, logical, now):
            return
        spec = self._buttons()[logical]
        code = spec["code"]
        if code is not None:
            self._refuse(logical, code)
            return
        # 2026-09-30 (the user: every interaction has a sound and a haptic): every accepted press ticks (opening a menu,
        # Back, Home, a source switch...). Armed first, so a screen the press enters carries it in its entry frame; a
        # press that thumps, nudges or buzzes arms its own event after this one, and only the newest seq plays.
        self._haptic("confirm.tick")
        getattr(self, "_press_" + mode)(logical, now)

    def hold(self, logical, control_id=None):
        """The firmware's hold (`kh`), once per event (section 4.2): logical 0 (600 ms) = Home / Back.
        r3.1 (presentation 6): logical 3 (1.0 s) = the screen's secondary action (`_hold_4`); the
        runtime has already dropped that press's tap. Holds of logical 1 and 2 are ignored. Onshape mode
        has no holds (1 is ZOOM, 4 PAN; Home is all four held: onshape_home_chord)."""
        if self.screen.mode == "onshape":
            return
        if logical == 3 and self.spaces and self._accepts(control_id):
            self._hold_4(control_id)
            return
        if logical != 0 or not self._accepts(control_id):
            return
        now = self.clock()
        if self._play_window(now):
            return
        self.last_knob_input = now
        mode = self.screen.mode
        if mode == self._root():
            return
        self._haptic("confirm.thump")   # r4 4.4: hold 1 = tension -> thump -> Home
        if mode in ("recent", "tracks", "home") + LIGHTS_MODES:
            self._go_root("hold")
        elif mode == "seek":
            self._leave_seek(flush=True)
            self._new_screen(self._root(), self.display_volume, "hold")
        elif mode == "explorer":
            self._close_explorer("hold")
        elif mode == "upnext":
            self._close_upnext("hold")
        elif mode == "windows":
            windows = self.screen.windows
            if windows.snap_busy is not None:
                windows.latched_close = "hold"
            else:
                self._close_windows("hold")

    # ------------------------------------------------------------------ hold 4 (r3.1)
    def _hold_actions(self):
        """{mode: action(now)} of hold 4: the launcher's knob domain swap, and "queue / Play next"
        in the music lists (Recently Added / Playlists, the explorer's both sources, Up next)."""
        return {"launcher": self._swap_domain, "recent": self._hold_queue_list, "explorer": self._hold_queue_list,
                "upnext": self._hold_move_next}

    def hold_action(self, mode=None):
        """Read-only: the label of hold 4 on `mode` (default: now), or '' where hold 4 does not exist
        (r3.1 design `hasHold4`: Home, Recently Added / Playlists, the explorer and Up next only; the
        runtime lets a `kh` elsewhere pass, so 4 acts on its release). The Navigator's HOLD chip."""
        mode = self.screen.mode if mode is None else mode
        if not self.spaces or mode == "onshape":
            return ""   # A0: Onshape mode has no hold 4 (4 is pan's modifier)
        if mode == "launcher":
            return "Knob to music" if self.home_domain == "lights" else "Knob to lights"
        if mode in ("recent", "explorer"):
            return "Queue"
        if mode == "upnext":
            return "Play next"
        return ""

    def _hold_4(self, control_id):
        """Hold 4 (>= 1.0 s): the screen's secondary action; where a screen has none, the hold is
        simply the press (the runtime suppressed the tap when the hold matured)."""
        now = self.clock()
        if self._play_window(now):
            return
        mode = self.screen.mode
        action = self._hold_actions().get(mode)
        if action is None:
            self.button(3, control_id)
            return
        self.last_knob_input = now
        if mode == "explorer" and now < self.screen.explorer.swap_until:
            return   # a tab swap is running: the focus belongs to neither source yet (section 3.4)
        if mode == "upnext" and now < self.screen.upnext.swap_until:
            return
        code = self._hold_code(mode)
        if code is not None:
            self._refuse(3, code, hold=True)
            return
        action(now)

    def _queue_code(self, source, item):
        """Play next's own dims (section 3.1 Recent 3) for `item` of the list `source`."""
        state = self._source_state(source)
        code = self._list_codes(state, item, item is not None, source)
        if code is None and source == "favourites" and item is not None:
            if (self.favourites.meta.get(_item_id(item)) or {}).get("empty"):
                code = "item_unavailable"
        if code is None:
            code = self._src_code() or ("sonos_shuffle" if self.sonos_shuffle() else None)
        return code

    def _hold_code(self, mode):
        if mode == "launcher":
            return None
        if mode in ("recent", "explorer"):
            source = self._shown_source()
            return self._queue_code(source, self._source_item(source, self.screen.index))
        if mode == "upnext":
            upnext = self.screen.upnext
            focus_row = self._upnext_focus_row()
            if upnext.loading or (focus_row is None and not self._upnext_on_card()):
                return "loading"
            if self._upnext_on_card():
                return "sonos_card"
            if focus_row.get("row") == upnext.P:
                return "already_playing"   # r3.1 design: the playing row cannot play next
            busy = self._busy_code()
            if busy:
                return busy
            if not self.state["online"]:
                return "sonos_unavailable"
            return None
        return None

    def _swap_domain(self, now):
        """Launcher hold 4: the knob swaps music volume <-> the Lights area's brightness (1b)."""
        self.home_domain = "lights" if self.home_domain != "lights" else "volume"
        self._volume_reveal_until = 0.0
        self._lights_reveal_until = 0.0
        lights = self.home_domain == "lights"
        self._set_transient("knob.status.domain.lights" if lights else "knob.status.domain.volume", tone="warm",
                            ms=DOMAIN_META)
        self._feedback("ok", haptic="confirm.thump")   # r3.1 (Job B): the landing flash; r4: a hold landing thumps
        self._reenter("home domain")
        if lights:
            self._lights_read()

    def _hold_queue_list(self, now):
        """Recently Added / Playlists (knob list or explorer) hold 4: Play next (section 9.3)."""
        source = self._shown_source()
        item = self._source_item(source, self.screen.index)
        if item is None:
            return
        self._feedback("ok", moment="queued")   # r3.1 (Job B): the green landing at the hold, not the result
        if source == "favourites":
            self._dispatch_play_next(item, kind="playlist", accent=self._accent("playlist", item))
        else:
            self._dispatch_play_next(item)

    def _hold_move_next(self, now):
        """Up next hold 4: the focused row plays next (`move_next`, section 9.4)."""
        upnext = self.screen.upnext
        row = self._upnext_focus_row()
        self._feedback("ok", moment="queued")   # r3.1 (Job B): the green landing at the hold
        self.move_next_request = self.request("move_next", row=row["row"],
                                              expected_group_revision=self.state["group_revision"],
                                              expected_update_id=upnext.revision, item=_descriptor(row))

    def limit(self, direction, control_id=None):
        """An end-stop push (`lim`): Seek limit line and idle re-arm, overlay end bumps, lifetime."""
        if direction not in (-1, 1) or not self._accepts(control_id):
            return
        now = self.clock()
        self.last_knob_input = now
        mode = self.screen.mode
        if mode == "seek":
            seek = self.screen.seek
            seek.idle_due = now + SEEK_IDLE
            if direction == 1 and self.screen.index >= seek.max:
                seek.limit_until = now + SEEK_LIMIT_LINE
        elif mode == "explorer":
            self._present("explorer_highlight", index=self.screen.index, control_id=self.control_id, bump=direction)
        elif mode == "upnext":
            self._present("upnext_highlight", index=self.screen.index, control_id=self.control_id, bump=direction)
        elif mode == "windows":
            self._present("windows_highlight", index=self.screen.index, control_id=self.control_id, bump=direction)

    def device_ready(self, control_id):
        if control_id == self.control_id:
            self.ready = True

    def set_hardware(self, enabled):
        """A knob (re)connect: fresh state read and Home (C5-2)."""
        self.hardware = enabled
        if enabled:
            self.last_poll = -10.0
            # DD-BUG-007: a re-home without a disconnect first (the knob after a recalibration) leaves
            # every mode the way disconnected() does: overlays close at once (no focus restore, no U12),
            # Seek drops its unsent target, Onshape lets go of its keys. The entry below is the only one.
            mode = self.screen.mode
            if mode in OVERLAY_MODES:
                self._close_overlay_now("disconnect")
            elif mode == "seek":
                self._leave_seek(flush=False, drop=True)
            elif mode == "onshape":
                self._onshape_reset()
            if self.screen.mode != self._root():
                self._cancel_due(self.screen.view_id)
                self.screen = Screen(mode=self._root(), index=self.display_volume)
            self._enter("reconnect")
        else:
            self._enter("hardware off")

    def disconnected(self):
        """Section 13.4: close every overlay (`disconnect`), exit Seek dropping its target, clear
        the transient; a pending start finishes honestly; the Screen becomes Home."""
        mode = self.screen.mode
        if mode in ("explorer", "upnext", "windows"):
            self._close_overlay_now("disconnect")
        if self.screen.mode == "seek":
            self._leave_seek(flush=False, drop=True)   # an exit the user did not make (C5-47)
        self.hardware = False
        self.ready = False
        self.desired_volume = None
        self._volume_reveal_until = 0.0
        self._volume_reveal_source = ""
        self._external_until = 0.0
        self.transient = None
        self._toasts = []
        self._passive = None
        self._clear_lights_intent()
        self._lights_reveal_until = 0.0
        if self.screen.mode != self._root():
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode=self._root(), index=self.display_volume)

    def set_reduced_motion(self, on):
        self.reduced_motion = bool(on)

    def open_windows(self):
        """F24 (or serial logical 3 without a hotkey) on Home only (section 5.7.1). The Win press
        is the knob's own button (its `kd` is dropped as `hid`), so it counts as knob input for
        the lifetime idle (section 13.1)."""
        self.last_knob_input = self.clock()
        if self.screen.mode != self._root() or any(e.get("kind") == "windows_open" for e in self.pending.values()):
            return
        self.request("windows_open")

    def dismiss_windows(self):
        """External focus won (`focus_lost`): hide without focus restore, no U12, Home."""
        if self.screen.mode == "windows":
            self._close_overlay_now("focus_lost")

    def home(self):
        """Compat: Back to Home from anywhere (the picker closes with `back`)."""
        if self.screen.mode == "windows":
            self._close_windows("back")
        elif self.screen.mode == "explorer":
            self._close_explorer("hold")
        elif self.screen.mode == "upnext":
            self._close_upnext("hold")
        elif self.screen.mode != self._root():
            self._go_root("home")

    def close_overlay(self, reason):
        """Lifetime closes (section 13.1): lock, sleep, idle, group, foreground, source, disconnect.

        Never latched behind an in-flight snap (WP5R-2): only Back and hold wait for the snap to
        resolve (C5-12, 5.7.3); lock, sleep and idle close the picker at once (5.7.4; K4 15 "instant",
        hidden in the same presenter wake), and a latched Back or hold gives way to them. A
        `snap_result` that arrives after the close is dropped (the picker is no longer the Screen)."""
        mode = self.screen.mode
        if mode in ("explorer", "upnext", "windows"):
            self._close_overlay_now(reason)

    # ------------------------------------------------------------------ presenter events (section 11.4)
    def presenter_event(self, event):
        """The one entry point for every presenter event (VOC-R22): K4's ``(kind, payload)``
        tuples and the picker's dicts alike (``presenter_event_dict``)."""
        event = presenter_event_dict(event)
        if event is None:
            return
        kind = event.get("kind")
        surface = event.get("surface")
        control = event.get("control_id")
        if control is not None and control != self.control_id and kind in ("click_action",):
            _log.debug("Presenter event %s for an old control dropped", kind)
            return
        if kind in ("opened",):
            return
        if kind == "closed":
            reason = event.get("reason")
            if reason in ("display", "device"):
                self.presenter_closed(surface, reason)
            return
        if kind == "refused":
            self.presenter_refused(surface, event.get("reason"))
            return
        if kind == "click_action":
            if self._surface_mode(surface) == self.screen.mode:
                self.button(3, self.control_id)
            return
        if kind == "system":
            what = event.get("what", event.get("system", event.get("value")))
            if what in ("lock", "sleep"):
                self.close_overlay(what)
            elif what == "motion":
                on = event.get("reduced", event.get("on"))
                if type(on) is bool:
                    self.set_reduced_motion(on)
            elif what == "foreground":
                if self.screen.mode in ("explorer", "upnext"):
                    self.close_overlay("foreground")
            return
        if kind == "snap_result":
            self.snap_result(event.get("side"), event.get("outcome"))
            return
        if kind == "cancel_result":
            self.cancel_result(bool(event.get("restored")), bool(event.get("completed")))

    @staticmethod
    def _surface_mode(surface):
        return {"explorer": "explorer", "upnext": "upnext", "picker": "windows"}.get(surface)

    def presenter_closed(self, surface, reason):
        """A close the presenter started (`display`, `device`): parent mode, no toast, no U12."""
        mode = self._surface_mode(surface)
        if mode is None or mode != self.screen.mode:
            return
        self._close_overlay_now(reason, emit=False)

    def presenter_refused(self, surface, reason):
        """Section 13.5: the knob leaves the mode it entered at the press for the parent."""
        mode = self._surface_mode(surface)
        if mode is None or mode != self.screen.mode:
            return
        if reason == "busy":
            _log.warning("The %s overlay was refused as busy (one-overlay guard)", surface)
        self._close_overlay_now("refused", emit=False)
        self._feedback("err")
        self._set_transient("knob.meta.stage_unavailable", tone="error", ms=FAIL_META)
        self.notice = "The screen overlay could not open."

    # ------------------------------------------------------------------ closes (section 13)
    def _close_overlay_now(self, reason, emit=True):
        mode = self.screen.mode
        if mode == "explorer":
            self._close_explorer(reason, emit=emit)
        elif mode == "upnext":
            self._close_upnext(reason, emit=emit)
        elif mode == "windows":
            self._close_windows(reason, emit=emit)

    def _close_explorer(self, reason, emit=True):
        now = self.clock()
        explorer = self.screen.explorer
        index = explorer.index_by_source.get("recent", 0)
        source = "recent"
        if self.spaces:
            # r3.1: the knob list returns on the explorer's source and focus (the tabs stay in sync).
            source = explorer.source if explorer.source in LIST_SOURCES else "recent"
            explorer.index_by_source[source] = self.screen.index
            self.list_source = source
            self._list_index.update({key: value for key, value in explorer.index_by_source.items()
                                     if key in LIST_SOURCES})
            index = explorer.index_by_source.get(source, 0)
        if emit:
            self._present("explorer_close", t0=now, reason=reason, close_at_ms=0)
        if reason in ("hold", "disconnect"):
            if reason == "disconnect":
                self._cancel_due(self.screen.view_id)
                self.screen = Screen(mode=self._root(), index=self.display_volume)
                return
            self._new_screen(self._root(), self.display_volume, "hold")
            return
        self._new_screen("recent", index, reason)
        if source == "favourites":
            self._request_playlist_meta()
        else:
            self._recent_moved(schedule_preresolve=False)

    def _close_upnext(self, reason, emit=True):
        now = self.clock()
        upnext = self.screen.upnext
        parent = self.screen.parent_index if self.screen.parent_index is not None else 1
        armed = upnext.armed_toast if upnext else None
        if emit:
            self._present("upnext_close", t0=now, reason=reason, close_at_ms=0)
        if reason == "back" and armed:
            self._exit_toast(armed, now)
        if reason == "disconnect":
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode=self._root(), index=self.display_volume)
            return
        if reason == "hold":
            self._new_screen(self._root(), self.display_volume, "hold")
            return
        focus = self.screen.index if self.spaces else None
        self._enter_tracks(parent, reason, focus=focus)   # r3.1: Tracks takes Up next's row

    def _close_windows(self, reason, emit=True):
        """Picker closes: back/hold/lock/sleep/idle apply U12 and go through `windows_cancel`, which
        carries the close `reason` (K3 5.7.4, C5-78, phase-2b review item R8; the picker's own
        inference is only the fallback for a payload without one, WP7b-D6); back/hold/idle restore focus, lock and sleep
        never do (K4 15); disconnect, focus_lost and display hide without either (VOC-R15)."""
        now = self.clock()
        windows = self.screen.windows
        if emit:
            if reason in ("back", "hold", "lock", "sleep", "idle"):
                complete = None
                assigned = [side for side in ("left", "right") if getattr(windows, side)]
                if len(assigned) == 1:
                    snapped = getattr(windows, assigned[0])
                    if windows.desk_open is not None and windows.desk_open != snapped:
                        complete = "right" if assigned[0] == "left" else "left"
                self._present("windows_cancel", origin=windows.origin, home=True, complete=complete, reason=reason)
                self._cancel_pending = {"reason": reason, "closed_at": now, "complete": complete,
                                        "left": self._window_app(windows.left),
                                        "right": self._window_app(windows.right),
                                        "origin": self._window_app(windows.desk_open)}
            else:
                self._present("windows_hide")
                self._cancel_pending = None
        if reason == "disconnect":
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode=self._root(), index=self.display_volume)
            return
        self._new_screen(self._root(), self.display_volume, reason)

    def _window_app(self, item_id):
        if item_id is None:
            return ""
        for item in (self.screen.windows.items if self.screen.windows else ()):
            if item.get("id") == item_id:
                return item.get("label_app") or item.get("app", "")
        return ""

    def cancel_result(self, restored, completed):
        """`windows_cancel` answered (C5-53): `toast.snap.one_side` only after a completed back close."""
        pending, self._cancel_pending = self._cancel_pending, None
        if not pending:
            return
        if not restored and pending["reason"] not in ("lock", "sleep"):
            # K4 15: a lock or sleep close never restores focus, so `restored` false is expected there.
            self.notice = "Original window no longer available"
        if pending["reason"] == "back" and completed and pending["complete"]:
            left, right = pending["left"], pending["right"]
            if pending["complete"] == "left":
                left = pending["origin"]
            else:
                right = pending["origin"]
            self._exit_toast("toast.snap.one_side", pending["closed_at"], A=left, B=right)

    # ------------------------------------------------------------------ silent guards (section 3.4)
    def _silent_guard(self, mode, logical, now):
        if mode == "explorer":
            explorer = self.screen.explorer
            if logical in (1, 2) and now < explorer.swap_until:
                return True
        elif mode == "upnext":
            upnext = self.screen.upnext
            if logical == 1 and now < upnext.swap_until:
                return True
            if logical == 2:
                row = self._upnext_focus_row()
                if row and row.get("song_id") in self.like_inflight:
                    return True
        elif mode == "windows":
            windows = self.screen.windows
            if windows.switch_request is not None:
                return True
            if windows.snap_busy is not None:
                if logical == 0:
                    windows.latched_close = "back"
                return True
        return False

    # ------------------------------------------------------------------ refusals (section 3.3)
    def _reason(self, code, slot, hold=False):
        """(copy_id, tone, seconds, toast_id) or None when the press is ignored (C5-59). `hold`:
        r3.1's hold 4 (queue / Play next) takes Play next's reasons."""
        mode = self.screen.mode
        if self.spaces and code == "neutral":
            if mode == "tracks" and self._tracks_queue():
                return "knob.meta.tracks.browse", "error", R3_REFUSED_META, None   # r3.1 whole queue
            return "knob.meta.skip.choose", "error", R3_REFUSED_META, None   # README 6
        if self.spaces and code == "seeking":
            return "knob.meta.skip.seeking", "error", R3_REFUSED_META, None
        if code in ("loading", "empty", "neutral", "seeking", "sonos_card"):
            return None
        if code == "starting":
            if mode in VOLUME_MODES and slot == self._play_slot():
                return None
            return "knob.meta.busy.starting", "meta", REASON_META, None
        if code == "queueing":
            if mode == "recent":
                return None
            job = self.play_next_job
            if job is not None and job.k >= 1 and job.n:
                return "knob.meta.playnext.progress", "meta", REASON_META, None
            return "knob.meta.playnext.resolving", "meta", REASON_META, None
        if code == "shuffling":
            if mode == "upnext":
                return None
            return "knob.meta.busy.shuffling", "meta", REASON_META, None
        if code == "transport_pending":
            if mode in VOLUME_MODES:
                return None
            if self._skip_command() is not None:
                return None
            command = self._home_command() or {}
            copy_id = "knob.meta.busy.pausing" if command.get("direction") == "pause" else "knob.meta.busy.starting"
            return copy_id, "meta", REASON_META, None
        if code == "nothing_next":
            P, T = self._position()
            if T - P < 2:
                return None
            return "knob.meta.shuffle.nothing", "meta", REASON_META, None
        if code == "sonos_unavailable":
            return ("knob.status.sonos_unavailable" if mode in VOLUME_MODES else "knob.meta.sonos_unavailable"), \
                "meta", REASON_META, None
        if code == "nothing_playing":
            if self.spaces:
                # r3.1 design: Music 3 `Nothing loaded`; Play `Nothing loaded · pick in Recent`.
                if mode == "home" and slot == 2:
                    return "knob.status.nothing_loaded", "error", R3_REFUSED_META, None
                return "knob.status.nothing_loaded_pick", "error", R3_REFUSED_META, None
            return "knob.status.nothing_playing", "meta", REASON_META, None
        if code == "signin_expired":
            return "knob.meta.signin_expired", "error", SIGNIN_META, None
        if code == "signin_needed":
            return "knob.meta.signin_needed", "error", SIGNIN_META, None
        if code == "list_error":
            return "knob.meta.library_error", "meta", REASON_META, None
        if code == "item_unavailable":
            return "knob.meta.item_unavailable", "meta", REASON_META, None
        if code.startswith("src_"):
            cls = code[4:]
            if mode == "recent" or (hold and mode == "explorer"):
                toast = "toast.playnext.none" if cls == "none" else "toast.playnext.not_queue"
                return "knob.meta.playnext." + cls, "meta", REASON_META, toast
            if slot == 2 and mode == "tracks":
                return "knob.meta.seek." + cls, "meta", REASON_META, None
            return "knob.meta.upnext." + cls, "meta", REASON_META, None
        if code == "sonos_shuffle":
            return "knob.meta.playnext.shuffle", "meta", REASON_META, "toast.playnext.shuffle"
        if code == "no_length":
            return "knob.meta.seek.no_length", "meta", REASON_META, None
        if code == "skip_unavailable":
            copy_id = "knob.meta.skip.prev_unavailable" if self.screen.index == 0 else "knob.meta.skip.next_unavailable"
            return copy_id, "meta", REASON_META, None
        if code == "likes_unknown":
            return "knob.meta.like.unknown", "meta", REASON_META, None
        if code == "not_catalog":
            return "knob.meta.like.not_catalog", "meta", REASON_META, None
        if code == "closed":
            return "knob.meta.windows.closed", "meta", REASON_META, None
        if code == "unlike_unavailable":
            return "knob.meta.like.unlike_in_music", "meta", LIKE_FAIL_META, None
        if code == "scenes_choose":
            return "knob.meta.scenes.choose", "error", REASON_META, None   # README 6: unavailable copy
        if code == "lights_unavailable":
            # r3.1 design (`lightsBlock`): the reason of the blocked state.
            block = self.lights_block()
            if block == "empty":
                return "knob.meta.lights.none", "error", REASON_META, None
            if block == "area":
                return "knob.meta.lights.area_missing", "error", REASON_META, None
            if block == "unav":
                return "knob.meta.lights.unavailable", "error", REASON_META, None
            if block == "connecting":
                return "knob.title.lights_connecting", "meta", REASON_META, None
            return "knob.meta.lights.not_connected", "error", REASON_META, None
        if code == "no_scenes":
            if self.lights.name:
                return "knob.meta.lights.no_scenes_area", "error", REASON_META, None
            return "knob.meta.lights.no_scenes", "meta", REASON_META, None
        if code == "already_playing":
            return "knob.meta.upnext.already_playing", "error", R3_REFUSED_META, None
        if code == "no_temperature":
            return "knob.meta.lights.no_temperature", "meta", REASON_META, None
        return None   # lights_pending: ignored (C5-59)

    def _refuse(self, slot, code, hold=False):
        """A press never acts on a dimmed button: reason copy + Head shake, unless ignored."""
        reason = self._reason(code, slot, hold)
        if reason is None:
            return
        copy_id, tone, seconds, toast = reason
        fields = {}
        if copy_id == "knob.meta.playnext.progress":
            job = self.play_next_job
            fields = {"k": job.k, "n": job.n}
        elif copy_id in ("knob.meta.lights.none", "knob.meta.lights.no_scenes_area"):
            fields = {"name": self.lights.name or "the area"}
        if self.spaces:
            # r3 (README 1 "Unavailable buttons"): the reason in #FF8474 for at least 2 s and the
            # bottom-segment red flash (feedback moment `refused`) instead of the head shake.
            self._set_transient(copy_id, tone="error", ms=max(seconds, R3_REFUSED_META), **fields)
            self._feedback("err", moment="refused")
        else:
            self._set_transient(copy_id, tone=tone, ms=seconds, **fields)
            self._feedback("err", haptic="refuse.buzz")
        if toast and self.screen.mode == "recent" and (hold or (slot == 2 and not self.spaces)):
            self._toast(toast)

    # ------------------------------------------------------------------ the button grammar (section 3.1)
    @staticmethod
    def _btn(icon, label, code=None, lit=None, color=0):
        return {"icon": icon, "label": label, "code": code, "lit": lit, "color": color}

    def _buttons(self):
        return getattr(self, "_buttons_" + self.screen.mode)()

    def _src_code(self):
        source = self.source()
        return None if source == "queue" else "src_" + source

    def _play_slot(self):
        """The Play / Pause slot: button 4 in r3 (Home and Music), button 1 in r2.2."""
        return 3 if self.spaces else 0

    def _play_button(self):
        online = self.state["online"]
        playing = online and self.state.get("playback") == "PLAYING"
        token = "pause" if playing else "play"
        command = self._home_command()
        code = None
        if not online:
            code = "sonos_unavailable"
        elif self.start is not None:
            code = "starting"
        elif command is not None:
            code = "transport_pending"
            token = "pause" if command.get("direction") == "play" else "play"
        elif not self.has_media():
            code = "nothing_playing"
        return self._btn(token, "Pause" if token == "pause" else "Play", code)

    def _buttons_home(self):
        online = self.state["online"]
        tracks_code = "sonos_unavailable" if not online else ("nothing_playing" if not self.has_media() else None)
        if self.spaces:
            # r3 Music space: 1 Home · 2 Recently Added · 3 Tracks · 4 Play / Pause.
            return [self._btn("house", "Home"), self._btn("album", "Recent"),
                    self._btn("tracks", "Tracks", tracks_code), self._play_button()]
        return [self._play_button(),
                self._btn("list", "Browse"),
                self._btn("tracks", "Tracks", tracks_code),
                self._btn("win", "Win")]

    def _buttons_launcher(self):
        """r3 Home (1a Launcher): 1 Music · 2 Windows · 3 Lights · 4 Play / Pause; r3.1: in the
        lights domain (hold 4) button 4 is the area's power (All off / Turn on)."""
        fourth = self._power_button() if self._lights_domain() else self._play_button()
        return [self._btn("list", "Music"), self._btn("win", "Win"), self._btn("bulb", "Lights"), fourth]

    def _lights_code(self):
        """r3.1: every blocked state dims 2-4 with its own reason (`_reason` "lights_unavailable")."""
        return "lights_unavailable" if self.lights_block() is not None else None

    def _power_button(self):
        """All off / Turn on (Lights 4, the launcher's lights domain 4)."""
        code = self._lights_code()
        power_code = code or ("lights_pending" if self.lights_command is not None else None)
        return self._btn("power", "All off" if self.lights_display_on() else "Turn on", power_code)

    def _buttons_lights(self):
        """r3 Lights (1e): 1 Home · 2 Scenes list · 3 Temperature on/off · 4 All off / Turn on."""
        lights = self.lights
        code = self._lights_code()
        scenes_code = code or (None if lights.scenes else "no_scenes")
        temp_code = code or (None if lights.supports_ct else "no_temperature")
        temp = self._btn("thermo", "Temp", temp_code, lit="on" if self.lights_mode == "temp" else None)
        return [self._btn("house", "Home"), self._btn("wand", "Scenes", scenes_code), temp, self._power_button()]

    def _buttons_scenes(self):
        """r3 Scenes list: 1 Back → Lights · 4 Run; 2 and 3 dimmed (`Turn to choose · 4 runs it`)."""
        code = self._lights_code()
        run_code = code or ("empty" if not self.lights.scenes else
                            ("lights_pending" if self.lights_command is not None else None))
        return [self._btn("back", "Back"), self._btn("", "", "scenes_choose"), self._btn("", "", "scenes_choose"),
                self._btn("switch", "Run", run_code)]

    def _signin_code(self, source="recent"):
        """The dim of a list in state ``signin``: never connected or expired (DD-BUG-023)."""
        lst = self.recent if source == "recent" else self.favourites
        return "signin_needed" if lst.signin_needed else "signin_expired"

    def _list_codes(self, lst_state, item, focused_loaded, source="recent"):
        """The shared first dims of Recent 3/4 and Explorer 4 (loading ... item_unavailable)."""
        if lst_state == "loading" or not focused_loaded:
            if lst_state not in ("empty", "signin", "error"):
                return "loading"
        if lst_state == "empty":
            return "empty"
        if lst_state == "signin":
            return self._signin_code(source)
        if lst_state == "error":
            return "list_error"
        busy = self._busy_code()
        if busy:
            return busy
        if not self.state["online"]:
            return "sonos_unavailable"
        if item is not None and item.get("available") is False:
            return "item_unavailable"
        return None

    def _buttons_recent(self):
        if self.spaces:
            return self._buttons_recent_r3()
        lst = self.recent
        item = lst.item(self.screen.index)
        loaded = item is not None
        open_code = self._signin_code() if lst.state == "signin" else ("list_error" if lst.state == "error" else None)
        play_code = self._list_codes(lst.state, item, loaded)
        next_code = play_code
        if next_code is None:
            next_code = self._src_code() or ("sonos_shuffle" if self.sonos_shuffle() else None)
        return [self._btn("back", "Back"), self._btn("expand", "Full screen" if self.spaces else "Open", open_code),
                self._btn("playnext", "Play next", next_code), self._btn("play", "Play", play_code)]

    def _buttons_recent_r3(self):
        """r3.1 Recently Added: 1 Back · 2 Full screen · 3 Playlists / Recent (the list's source) ·
        4 Play (hold 4: Play next, gated by Play next's own dims)."""
        source = self._recent_source()
        item = self._source_item(source, self.screen.index)
        state = self._source_state(source)
        open_code = self._signin_code(source) if state == "signin" else ("list_error" if state == "error" else None)
        play_code = self._list_codes(state, item, item is not None, source)
        if play_code is None and source == "favourites" and item is not None:
            if (self.favourites.meta.get(_item_id(item)) or {}).get("empty"):
                play_code = "item_unavailable"
        # r3.1 design: one list-music icon (`playlists`), lit amber (`act`) on Favourite playlists.
        toggle = self._btn("playlists", "Playlists") if source == "recent" else \
            self._btn("playlists", "Recent", lit="on")
        return [self._btn("back", "Back"), self._btn("expand", "Full screen", open_code), toggle,
                self._btn("play", "Play", play_code)]

    def _buttons_explorer(self):
        explorer = self.screen.explorer
        source = explorer.source
        item = self._source_item(source, self.screen.index)
        state = self._source_state(source)
        code = self._list_codes(state, item, item is not None, source)
        if code is None and source == "favourites" and item is not None:
            meta = self.favourites.meta.get(_item_id(item)) or {}
            if meta.get("empty"):
                code = "item_unavailable"
        recent_on = source == "recent"
        return [self._btn("back", "Back"),
                self._btn("album" if self.spaces else "clock", "Recent", lit="on" if recent_on else "off"),
                self._btn("playlists", "Playlists", lit="off" if recent_on else "on"),
                self._btn("play", "Play", code)]

    def _tracks_upnext_code(self):
        if not self.state["online"]:
            return "sonos_unavailable"
        return self._src_code()

    def _queue_end(self, index):
        """Tracks 4 at a queue end: 'end' / 'start' (the press is refused), or None."""
        # r4 4.3 (walls everywhere, no wrap-around): repeat-all no longer lets Next wrap to track 1 or Previous to
        # the last track; the queue's ends are walls like every other list's.
        if self.source() != "queue" or self.sonos_shuffle():
            return None
        P, T = self._position()
        if index == 2 and T and P >= T:
            return "end"
        if index == 0 and P <= 1 and T:
            return "start"
        return None

    def _buttons_tracks(self):
        online = self.state["online"]
        index = _clamp(self.screen.index, 0, 2)
        upnext_code = self._tracks_upnext_code()
        seek_code = upnext_code
        if seek_code is None and not self._can_seek():
            seek_code = "no_length"
        if seek_code is None and self.start is not None:
            seek_code = "starting"
        if self._tracks_queue():
            # r3.1 whole queue: 4 plays the focused row (`jump`); on the playing row it is dimmed.
            P, T = self._position()
            play_code = None
            if _clamp(self.screen.index, 0, T - 1) == P - 1:
                play_code = "neutral"
            elif not online:
                play_code = "sonos_unavailable"
            elif self._busy_code():
                play_code = self._busy_code()
            elif self.command_request is not None:
                play_code = "transport_pending"
            return [self._btn("back", "Back"), self._btn("expand", "Up next", upnext_code),
                    self._btn("seek", "Seek", seek_code), self._btn("play", "Play", play_code)]
        skip_code = None
        if index == 1:
            skip_code = "neutral"
        elif not online:
            skip_code = "sonos_unavailable"
        else:
            busy = self._busy_code()
            if busy:
                skip_code = busy
            elif self.command_request is not None:
                skip_code = "transport_pending"
            elif self._queue_end(index) is None:
                offered = self.state.get("can_previous") if index == 0 else self.state.get("can_next")
                if not offered:
                    skip_code = "skip_unavailable"
        return [self._btn("back", "Back"), self._btn("expand", "Up next", upnext_code),
                self._btn("seek", "Seek", seek_code),
                self._btn("prev" if index == 0 else "next", "Skip", skip_code)]

    def _can_seek(self):
        if "can_seek" not in self.state:
            return False
        duration = self.state.get("duration_s")
        if isinstance(duration, int) and duration > SEEK_MAX_DURATION_S:
            return False
        return bool(self.state.get("can_seek"))

    def _buttons_seek(self):
        if self.spaces:
            # README 1.2 Seek: 1 Cancel (restores) · 2 Up next · 3 Set · 4 disabled.
            # r3.1 design: 4 in Seek is the dimmed Play (`Set or cancel seek first`).
            return [self._btn("back", "Cancel"), self._btn("expand", "Up next", self._tracks_upnext_code()),
                    self._btn("seek", "Set", lit="on"), self._btn("play", "Play", "seeking")]
        return [self._btn("back", "Back"), self._btn("expand", "Up next", self._tracks_upnext_code()),
                self._btn("seek", "Seek", lit="on"), self._btn("next", "Skip", "seeking")]

    def _buttons_upnext(self):
        upnext = self.screen.upnext
        online = self.state["online"]
        active = self.shuffle_active()
        busy = self._busy_code()
        focus_row = self._upnext_focus_row()
        on_card = self._upnext_on_card()
        loading_focus = upnext.loading or (focus_row is None and not on_card)
        # Button 2 (shuffle)
        shuffle_code = None
        P, T = self._position()
        U = max(0, T - P)
        if upnext.loading or (not active and U <= COMPANION_SHUFFLE_MAX and not self._upcoming_loaded()):
            shuffle_code = "loading"
        elif busy:
            shuffle_code = busy
        elif not online:
            shuffle_code = "sonos_unavailable"
        elif not active and U <= COMPANION_SHUFFLE_MAX and U - len(self._playnext_offsets()) < 2:
            shuffle_code = "nothing_next"
        # Button 3 (like, or the Play next fallback)
        liked = bool(focus_row and focus_row.get("liked") is True)
        if self.upnext_button3 == "playnext":
            like = self._btn("playnext", "Play next")
            if loading_focus:
                like["code"] = "loading"
            elif on_card:
                like["code"] = "sonos_card"
            elif busy:
                like["code"] = busy
        else:
            like = self._btn("heart", "Liked" if liked else "Like", lit="on" if liked else None)
            if loading_focus:
                like["code"] = "loading"
            elif on_card:
                like["code"] = "sonos_card"
            elif focus_row.get("catalog") is False or not focus_row.get("song_id"):
                like["code"] = "not_catalog"
            elif focus_row.get("liked") is None:
                like["code"] = "likes_unknown"
        # Button 4 (play)
        play_code = None
        if loading_focus:
            play_code = "loading"
        elif on_card:
            play_code = "sonos_card"
        elif busy:
            play_code = busy
        elif not online:
            play_code = "sonos_unavailable"
        return [self._btn("back", "Back"), self._btn("shuffle", "Shuffle", shuffle_code, lit="on" if active else "off"),
                like, self._btn("play", "Play", play_code)]

    def _buttons_windows(self):
        windows = self.screen.windows
        item = self._window_item(self.screen.index)
        code = "empty" if not windows.items else ("closed" if item is not None and not item.get("available") else None)
        left = self._window_item_by_id(windows.left)
        right = self._window_item_by_id(windows.right)
        left_btn = self._btn("snapleft", "Snap left", code)
        right_btn = self._btn("snapright", "Snap right", code)
        if left is not None:
            left_btn.update(lit="on", color=self._accent("window", left))
        if right is not None:
            right_btn.update(lit="on", color=self._accent("window", right))
        first = self._btn("house", "Home") if self.spaces else self._btn("back", "Back")   # r3: a space root
        return [first, left_btn, right_btn, self._btn("switch", "Switch", code)]

    # ------------------------------------------------------------------ Home (section 5.1)
    def _toggle_playback(self):
        direction, enabled = self.playback_action()
        playback = self.state.get("playback")
        if playback not in ("PLAYING", "PAUSED_PLAYBACK", "STOPPED") or not self.state.get("can_" + direction):
            return  # an unstable transport: silently ignored (no blind toggle)
        self.notice = ""
        self._album_start_until = 0.0
        self._haptic("confirm.tick")   # r4 4.4: Play / Pause ticks
        self.command_request = self.request("transport", direction=direction,
                                            expected_group_revision=self.state["group_revision"],
                                            expected_track_id=self.state.get("track_id"))

    def _lights_targets(self):
        """The entity ids a brightness / temperature write goes to: the available lights that are
        on; None (the whole area) when none is on or the adapter reports no per-light rows."""
        members = [m for m in self.lights.members if isinstance(m, dict)]
        on = [str(m.get("entity_id")) for m in members
              if m.get("on") and m.get("available", True) is not False and m.get("entity_id")]
        return on or None

    def _lights_power(self):
        """All off / Turn on of the Lights area (Lights 4; the launcher's lights domain 4)."""
        on = not self.lights_display_on()
        self._clear_lights_intent()
        self._lights_reveal_until = 0.0
        self._haptic("confirm.thump" if on else "confirm.off")   # r4 4.4: Turn on thumps, All off is one soft pulse
        self.lights_command = self.request("lights_power", on=on)

    def _press_home(self, logical, now):
        if self.spaces:
            # r3 Music space.
            if logical == 0:
                self._go_root("home")
            elif logical == 1:
                self._browse()
            elif logical == 2:
                self._enter_tracks(1, "tracks")
            elif logical == 3:
                self._toggle_playback()
            return
        if logical == 0:
            self._toggle_playback()
        elif logical == 1:
            self._browse()
        elif logical == 2:
            self._enter_tracks(1, "tracks")
        elif logical == 3:
            self.open_windows()

    def _press_launcher(self, logical, now):
        if logical == 0:
            if now - self._home_arrived_at < HOME_GUARD:
                # README 1 overshoot guard: a 1 this soon after arriving Home is ignored.
                self._set_transient("knob.status.home_guard", tone="secondary", ms=HOME_GUARD_META)
                return
            self._new_screen("home", self.display_volume, "music")
        elif logical == 1:
            self.open_windows()
        elif logical == 2:
            self._enter_lights("lights")
        elif logical == 3:
            if self._lights_domain():
                self._lights_power()
            else:
                self._toggle_playback()

    # ------------------------------------------------------------------ Lights (r3 README 1.2, 7)
    def _enter_lights(self, cause, mode="bri"):
        """Entering Lights from Home always starts in brightness (README 1.2)."""
        self.lights_mode = mode
        self._lights_reveal_until = 0.0
        if cause == "lights":
            self.transient = None   # Home's status copy does not follow into Lights
        self._new_screen("lights", 0, cause)
        self._lights_read()

    def _lights_read(self):
        if any(e.get("kind") == "lights_read" for e in self.pending.values()):
            return
        self.last_lights_poll = self.clock()
        self.request("lights_read")

    def _press_lights(self, logical, now):
        lights = self.lights
        if logical == 0:
            self._go_root("home")
        elif logical == 1:
            index = 0
            for position, scene in enumerate(lights.scenes):
                if scene.get("entity_id") == lights.scene_id:
                    index = position
            self._lights_reveal_until = 0.0
            self.transient = None
            self._new_screen("scenes", index, "scenes")
        elif logical == 2:
            self.lights_mode = "bri" if self.lights_mode == "temp" else "temp"
            self._lights_reveal_until = 0.0
            self._set_transient("knob.meta.lights.knob_temperature" if self.lights_mode == "temp"
                                else "knob.meta.lights.knob_brightness", tone="warm", ms=LIGHTS_MODE_META)
            self._reenter("lights mode")
        elif logical == 3:
            self._lights_power()

    def _press_scenes(self, logical, now):
        if logical == 0:
            self._enter_lights("back", self.lights_mode)
        elif logical == 3:
            scenes = self.lights.scenes
            index = _clamp(self.screen.index, 0, max(0, len(scenes) - 1))
            scene = scenes[index]
            self._clear_lights_intent()
            self._haptic("confirm.thump")   # r4 4.4: Scene run thumps (on the press)
            self.lights_command = self.request("scene_run", entity_id=scene.get("entity_id"),
                                               label=scene.get("label", ""))
            self._enter_lights("scene run", self.lights_mode)

    def _reveal_lights(self, kind, seconds, source):
        self._lights_reveal_kind = kind
        self._lights_reveal_until = self.clock() + seconds
        self._lights_reveal_source = source

    def _lights_reveal(self):
        """'bri' / 'temp' while the big value shows (1.4 s after the last detent, 2.6 s after an
        external change; held while a write is out), else None."""
        if not self._lights_knob() or not self._lights_reveal_until:
            return None
        if self.clock() < self._lights_reveal_until or (self._lights_reveal_source == "local" and (
                self.lights_intent() or self.lights_request is not None)):
            return self._lights_reveal_kind
        return None

    def _lights_bri_frame(self):
        """The brightness frame the knob holds (DD-DES-003): 1 = on (0..99 = 1..100 %), 0 = off (0..100, 0 = off),
        None outside Lights brightness or before the knob holds a brightness control."""
        if not self._lights_knob() or self._lights_knob_mode() == "temp" or self._knob_bounds is None:
            return None
        frame = tuple(self._knob_bounds[:2])
        if frame == (0, BRI_ON_HIGH):
            return 1
        return 0 if frame == (0, 100) else None

    def _lights_turn(self, position, low, high, now):
        """A detent in Lights: brightness 1 % or temperature 100 K per detent; from off it turns the
        light on (1 % or the stored level with the new temperature)."""
        lights = self.lights
        # The knob holds this position whether or not the turn is honoured (DD-BUG-003): an ignored turn
        # (blocked, offline, no temperature) leaves bounds() != _knob_bounds, so _lights_tick re-anchors it.
        self._knob_bounds = (low, high, position)
        if self.lights_block() is not None:
            if lights.online or self.lights_block() != "connecting":
                self._refuse(3, "lights_unavailable")   # r3.1 design: the turn is denied with the reason
            return
        if not lights.online:
            return
        if self._lights_knob_mode() == "temp":
            if not lights.supports_ct:
                return
            kelvin_low, kelvin_high = self._kelvin_range()
            self._set_lights_intent(kelvin=_clamp(kelvin_low + position * KELVIN_STEP, kelvin_low, kelvin_high))
            self._reveal_lights("temp", VOLUME_REVEAL_SECONDS, "local")
        else:
            offset = 1 if high == BRI_ON_HIGH else 0     # DD-DES-003: the on frame starts at 1 %
            if not self.lights_display_on():
                if position + offset < 1:
                    return   # off: detent 0 is "off"; the first detent up turns it on at 1 %
                if self.transient is not None and self.transient.copy_id == "knob.meta.lights.off":
                    self.transient = None   # turning on: the All off copy no longer applies
            # 1 % is the lowest level (position 0 while on); All off turns the light off.
            self._set_lights_intent(bri=_clamp(position + offset, 1, 100))
            self._reveal_lights("bri", VOLUME_REVEAL_SECONDS, "local")
        if lights.scene_id:
            lights.adjusted = True
        self.lights_due = max(now, self.last_lights_write + LIGHTS_WRITE_INTERVAL)

    def _lights_tick(self, now):
        lights = self.lights
        self._lights_settle(now)
        if lights.online and self.lights_intent() and self.lights_request is None and now >= self.lights_due:
            # r3.1 design: a turn changes only the lights that are on (all to the same value); from
            # all off it turns every available light on (`targets` None: every available light).
            reconcile, self._lights_reconcile = self._lights_reconcile, False
            self.lights_request = self.request("lights_set", on_bri=lights.last_bri or None,
                                               targets=self._lights_targets(),
                                               **({"transition": 0} if reconcile else {}))
            self.last_lights_write = now
        if (self.screen.mode in LIGHTS_MODES or self._lights_domain()) and now - self.last_lights_poll >= LIGHTS_POLL:
            self._lights_read()
        # The knob follows a change it did not make (external, a scene, the lights coming online):
        # a passive re-entry once the knob has rested (section 6.4), never over a pending write.
        if (self._lights_knob() and not self.lights_intent() and self.lights_request is None
                and self.lights_command is None and self._passive is None
                and self._knob_bounds is not None and self.bounds() != self._knob_bounds):
            self._request_passive("lights changed")
        if self.screen.mode == "scenes":
            low, high, _ = self.bounds()
            if self._knob_bounds is not None and (low, high) != self._knob_bounds[:2] and self._passive is None:
                self._request_passive("scenes changed")

    def lights_state(self, state):
        """A Home Assistant state (the adapter's read_state, from its stream or a read)."""
        if not isinstance(state, dict):
            return
        lights = self.lights
        now = self.clock()
        before = (lights.on, lights.bri, lights.kelvin)
        was_known, was_online = lights.known, lights.online
        lights.configured = bool(state.get("configured"))
        lights.online = bool(state.get("online"))
        reason = state.get("reason")
        lights.reason = "" if lights.online else (reason if isinstance(reason, str) and reason else "offline")
        lights.scenes = [dict(scene) for scene in (state.get("scenes") or ())[:SCENES_MAX] if isinstance(scene, dict)
                         and isinstance(scene.get("entity_id"), str)]
        lights.snapshot = bool(state.get("snapshot"))
        # r3.1 (Job C's area bridge): the area's name, its light count and the reason it is unusable
        # arrive with every state, online or not ("no_lights" / "area_missing" are offline states).
        if isinstance(state.get("name"), str):
            lights.name = state["name"]
        if "count" in state:
            count = state.get("count")
            lights.count = count if type(count) is int and count >= 0 else None
        detail = state.get("detail")
        lights.detail = detail if isinstance(detail, str) else ""
        on_count = state.get("on_count")
        lights.on_count = on_count if type(on_count) is int and on_count >= 0 else None
        if "lights" in state:
            lights.members = [dict(m) for m in (state.get("lights") or ()) if isinstance(m, dict)][:LIGHTS_MEMBERS_MAX]
        if not lights.online:
            if was_online:
                self._clear_lights_intent()
                self._lights_reveal_until = 0.0
            return
        values = {"on": bool(state.get("on")), "bri": _int(state.get("bri"), 0),
                  "kelvin": state.get("kelvin") if type(state.get("kelvin")) is int else None}
        self._lights_reported = dict(values)
        expect = self._lights_expect
        if expect is not None:
            expected, until = expect
            matches = all(values.get(key) == value for key, value in expected.items())
            if matches or now >= until:
                self._lights_expect = None
            else:
                # Our own write has not echoed yet: keep what we showed (no flicker back).
                values = {key: expected.get(key, value) for key, value in values.items()}
        settling = False
        final = self._lights_final_live(now)
        if final is not None:
            raw = self._lights_reported
            near = bool(raw.get("on")) and all(
                raw.get(key) is None or abs(raw[key] - value) <= LIGHTS_NEAR[key] for key, value in final[0].items())
            if near:
                # Our last write, reported a little short (a fade ending short / a stale report): the knob keeps
                # what was set, and the settle write (once) puts the lights exactly there.
                settling = True
                values = {key: final[0].get(key, value) for key, value in values.items()}
                self._lights_correct(now)
            else:
                self._lights_final = None            # a real change (off, another app, a scene): shown
        lights.on, lights.bri = values["on"], _clamp(values["bri"], 0, 100)
        if lights.on and lights.bri < 1:
            lights.bri = lights.last_bri or 1   # a Turn on whose level has not echoed yet
        if lights.on and lights.bri >= 1:
            lights.last_bri = lights.bri
        if values["kelvin"] is not None:
            lights.kelvin = values["kelvin"]
        for key in ("min_k", "max_k"):
            if type(state.get(key)) is int:
                setattr(lights, key, _clamp(state[key], KELVIN_MIN, KELVIN_MAX))
        if type(state.get("supports_ct")) is bool:
            lights.supports_ct = state["supports_ct"]
            if not lights.supports_ct and self.lights_mode == "temp":
                self.lights_mode = "bri"
        lights.known = True
        after = (lights.on, lights.bri, lights.kelvin)
        ours = (self.lights_intent() or self.lights_request is not None or self.lights_command is not None
                or expect is not None or settling or now < self._scene_settle_until)
        # User 2026-09-29: a light drifting its colour temperature a little after our brightness writes
        # (4400 -> 4500 K) is not an external change: it flashed the knob's caption to Temperature mid-turn.
        drift = (after[:2] == before[:2] and after[2] is not None and before[2] is not None
                 and abs(after[2] - before[2]) <= LIGHTS_NEAR["kelvin"])
        local = self._lights_reveal_source == "local" and self._lights_reveal() is not None
        if was_known and was_online and after != before and not ours and not drift and not local:
            # An external change (the HA app, a wall switch): the knob shows it for 2.6 s (r2.2 rule).
            if lights.on:
                kind = "temp" if after[:2] == before[:2] else "bri"
                self._reveal_lights(kind, EXTERNAL_REVEAL_SECONDS, "external")
            if lights.scene_id:
                lights.adjusted = True
        if self.screen.mode == "scenes" and self.screen.index >= len(lights.scenes):
            self.screen.index = max(0, len(lights.scenes) - 1)

    def _expect(self, **values):
        self._lights_expect = (values, self.clock() + LIGHTS_ECHO)

    def _lights_settle(self, now):
        """The tick's side of the settle write (a short report that came while a write was in flight)."""
        self._lights_correct(now)

    def _lights_final_live(self, now):
        """The last write's applied values while its settle window lasts (DD-BUG-002), else None (dropped)."""
        final = self._lights_final
        if final is not None and now - final[1] > LIGHTS_FINAL_WINDOW:
            self._lights_final = None
            return None
        return final

    def _lights_correct(self, now):
        """From LIGHTS_SETTLE after the last write, once per write and only within LIGHTS_FINAL_WINDOW: when
        the lights report (a little) another level or temperature than that write set, send it once more
        without a fade."""
        final = self._lights_final_live(now)
        if final is None or final[2] or now - final[1] < LIGHTS_SETTLE:
            return
        if (not self.lights.online or self.lights_intent() or self.lights_request is not None
                or self.lights_command is not None or now < self._scene_settle_until):
            return
        reported = self._lights_reported
        if not reported.get("on"):
            return                                   # turned off meanwhile (All off, a switch): leave it
        differ = {key: value for key, value in final[0].items()
                  if reported.get(key) is not None and reported.get(key) != value}
        if differ:
            self._lights_final = (final[0], final[1], True)
            self._lights_reconcile = True
            self._set_lights_intent(**differ)
            self.lights_due = now

    def _lights_failure(self, error, copy_id):
        outcome = getattr(error, "outcome", None)
        self._feedback("err")
        if outcome == "auth":
            self.lights.online, self.lights.reason = False, "auth"
            self._set_transient("knob.meta.lights.signin", tone="error", ms=SIGNIN_META)
        elif outcome == "forbidden":    # DD-BUG-049: HTTP 403 (an IP ban): offline until Settings fixes it
            self.lights.online, self.lights.reason = False, "forbidden"
            self._set_transient("knob.meta.lights.blocked", tone="error", ms=SIGNIN_META)
        elif outcome == "not_allowed":
            self._set_transient("knob.meta.lights.not_allowed", tone="error", ms=FAIL_META)
        else:
            if outcome in ("offline", "not_configured"):
                self.lights.online, self.lights.reason = False, outcome
            self._set_transient(copy_id, tone="error", ms=FAIL_META)

    def _lights_set_result(self, effect, result, error):
        if self.lights_request == effect["request"]:
            self.lights_request = None
        if error is not None:
            if self._discarded(error):
                return
            self._clear_lights_intent()
            self._lights_reveal_until = 0.0
            self._lights_failure(error, "knob.meta.lights.failed")
            return
        result = dict(result or {})
        applied = result.pop("_applied", None) or {}
        applied = {key: applied.get(key) for key in ("bri", "kelvin") if type(applied.get(key)) is int}
        expected = {"on": True, **applied}
        self._clear_lights_intent(applied)
        self._expect(**expected)
        if applied:
            self._lights_final = (dict(applied), self.clock(), effect.get("transition") == 0)
        self.lights_state(result)

    def _lights_power_result(self, effect, result, error):
        if self.lights_command == effect["request"]:
            self.lights_command = None
        if error is not None:
            if self._discarded(error):
                return
            self._lights_failure(error, "knob.meta.lights.failed")
            return
        on = bool(effect.get("on"))
        self._lights_final = None   # DD-BUG-002: All off / Turn on supersedes the last level write
        self._expect(on=on)
        self.lights_state(result)
        self._set_transient("knob.meta.lights.on" if on else "knob.meta.lights.off", tone="secondary",
                            ms=FEEDBACK_META)

    def _scene_run_result(self, effect, result, error):
        if self.lights_command == effect["request"]:
            self.lights_command = None
        label = effect.get("label") or ""
        if error is not None:
            if self._discarded(error):
                return
            self._lights_failure(error, "knob.meta.scene.failed")
            self._toast("toast.scene.failed", scene=label)
            return
        lights = self.lights
        lights.scene_id, lights.scene_label, lights.adjusted = effect.get("entity_id"), label, False
        self._scene_settle_until = self.clock() + SCENE_SETTLE
        self._lights_final = None   # DD-BUG-002: the scene's levels are the lights' now, never "corrected" back
        self.lights_state(result)
        # The scene ran: the firmware's 700 ms green wash (feedback ok in the LIGHTS family). The thump was the press's.
        self._feedback("ok", haptic=False)
        self._set_transient("knob.meta.scene.running", tone="success", ms=SCENE_META)
        self._toast("toast.scene.ok", scene=label)

    def _reveal_volume(self, seconds, source):
        self._volume_reveal_until = self.clock() + seconds
        self._volume_reveal_source = source

    def _home_layout(self, ready=None, reveal=True):
        ready = self.ready if ready is None else ready
        if not self.state["online"]:
            return "notice"
        if not ready:
            return "nowPlaying"
        now = self.clock()
        if reveal and self._volume_reveal_until and (now < self._volume_reveal_until
                                                     or self.desired_volume is not None or self.volume_request is not None):
            return "volume"
        if self._home_command() or self.start is not None:
            return "nowPlaying"
        if not self.has_media():
            return "idle"
        # r3.1 (2026-09-29): paused keeps the Now Playing layout (artwork + buttons); only STOPPED
        # and no media rest on `idle`.
        if self.state.get("playback") == "STOPPED":
            return "idle"
        return "nowPlaying"

    # ------------------------------------------------------------------ Recently Added (section 5.2)
    def _browse(self):
        """Home 2: a new visit at item 1 (C5-1); r3.1: always on the Recently Added source."""
        self.recent = RecentList(visit=self.recent.visit + 1)
        self.list_source = "recent"
        self._list_index["recent"] = 0
        self._new_screen("recent", 0, "browse")
        self._request_recent_page(lane="library")

    def _request_recent_page(self, lane):
        lst = self.recent
        if lst.inflight is not None:
            return
        kind = "recent" if lane == "library" else "recent_lookahead"
        lst.inflight = self.request(kind, visit=lst.apple_visit, offset=lst.next_offset, limit=RECENT_PAGE,
                                    list_visit=lst.visit)
        lst.inflight_lane = lane

    def _recent_index(self):
        """max(recent index, explorer recent index): what the prefetch keeps ahead of."""
        mode = self.screen.mode
        if mode == "recent":
            if self._recent_source() == "favourites":
                return self._list_index.get("recent", 0)   # r3.1: the Recently Added focus kept aside
            return self.screen.index
        if mode == "explorer":
            return self.screen.explorer.index_by_source.get("recent", 0)
        return None

    def _recent_prefetch(self):
        lst = self.recent
        index = self._recent_index()
        if index is None:
            return
        if lst.state == "loading" and not lst.items and lst.inflight is None and self.clock() >= lst.retry_at:
            self._request_recent_page("library")   # the first page, asked again (a held list)
            return
        if lst.state in ("loading", "empty", "signin", "error") or lst.complete:
            return
        focused_unloaded = index >= len(lst.items)
        if lst.inflight is not None:
            # Section 5.2.2: a fast spin outran the prefetch. The page the user now waits for moves
            # to the library lane (the lookahead one may sit behind a pre-resolution for seconds);
            # whichever copy lands first is kept, the other is dropped by its offset.
            if focused_unloaded and lst.inflight_lane == "lookahead":
                lst.inflight = None
                self._request_recent_page("library")
            return
        if self.clock() < lst.retry_at:
            return
        if len(lst.items) - 1 - index >= RECENT_AHEAD:
            return
        self._request_recent_page("library" if focused_unloaded else "lookahead")

    def _recent_moved(self, schedule_preresolve=True):
        self._recent_prefetch()
        if schedule_preresolve:
            self._preresolve_due = self.clock() + PREFETCH_RESOLVE_REST
            self._drop_stale_preresolve()

    @staticmethod
    def _preresolve_key(item):
        return (item.get("kind"), str(item.get("id")))

    def _drop_stale_preresolve(self):
        """Section 5.2.2 / 9.8.7: a new focus drops the queued (unsent) pre-resolutions that are
        no longer the focus or a neighbour, at the detent (not at the next rest). The runtime
        keeps only `keep` in the lookahead lane's queue; the one running finishes into the cache."""
        if not self._preresolve_sent:
            return
        index = self._recent_index()
        keep = []
        if index is not None:
            for target in (index, index + self._detent_dir, index - self._detent_dir):
                item = self.recent.item(target)
                if item is not None and self._preresolve_key(item) not in keep:
                    keep.append(self._preresolve_key(item))
        if not self._preresolve_sent - set(keep):
            return
        self._preresolve_sent.intersection_update(keep)
        self._present("resolve_drop", keep=[{"kind": kind, "id": ident} for kind, ident in keep])

    def _recent_result(self, effect, result, error):
        lst = self.recent
        if effect.get("list_visit") != lst.visit:
            return  # a page of an older visit never commits
        if lst.inflight == effect["request"]:
            lst.inflight = None
        offset = effect.get("offset")
        if type(offset) is int and offset != lst.next_offset:
            return  # the other copy of this page (moved to the library lane, section 5.2.2) landed first
        twin = lst.inflight is not None and (self.pending.get(lst.inflight) or {}).get("offset") == offset
        if error is not None:
            if twin:
                return  # the library copy of this page is still out: it answers for the page
            if self._discarded(error):
                lst.retry_at = self.clock() + RECENT_RETRY   # the list keeps its state; asked again
                return
            outcome = getattr(error, "outcome", None)
            needed = _signin_needed(error)
            signin = needed or outcome == "signin_expired" or getattr(error, "status", None) in (401, 403) or \
                _needs_login(str(error).lower())
            if not lst.items:
                lst.state = "signin" if signin else "error"
                lst.signin_needed = needed
                lst.rev += 1
                self._list_state_changed()
            else:
                lst.retry_at = self.clock() + RECENT_RETRY
            return
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            return
        if twin:
            lst.inflight = None   # this copy won; the other one is dropped by its offset when it lands
        was_count = lst.count()
        was_loaded_end = self._recent_index() is not None and self._recent_index() >= len(lst.items) - 1
        if lst.apple_visit is None:
            lst.apple_visit = result.get("visit")
        lst.items.extend(deepcopy(result["items"]))
        total = result.get("total")
        lst.total = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else lst.total
        lst.complete = bool(result.get("complete"))
        lst.next_offset = _int(result.get("offset"), lst.next_offset) + RECENT_PAGE
        if lst.complete and lst.total is not None and lst.total != len(lst.items):
            lst.total = len(lst.items)
        lst.state = "ready" if lst.items else ("empty" if lst.complete else "ready")
        if not lst.items and not lst.complete:
            lst.state = "loading"
            self._request_recent_page("library")
        lst.rev += 1
        if self.screen.mode in ("recent", "explorer"):
            count_now = lst.count()
            if count_now != was_count:
                if self._shown_source() == "recent":
                    if was_count == 0:
                        self._reenter("recent loaded")
                    else:
                        self._request_passive("recent growth", now_if_waiting=was_loaded_end)
            self._list_state_changed()
            self._recent_prefetch()
            if was_count == 0 and self.screen.mode in ("recent", "explorer"):
                self._preresolve_due = self.clock() + PREFETCH_RESOLVE_REST

    def _list_state_changed(self):
        if self.screen.mode == "explorer":
            self._explorer_push_highlight(data=True)

    def _preresolve(self, now):
        """C5-66: 400 ms after the last detent on a loaded Recently Added item, the focused item,
        then its neighbour in the direction of travel, then the other neighbour."""
        if self._preresolve_due is None or now < self._preresolve_due:
            return
        self._preresolve_due = None
        index = self._recent_index()
        if index is None or self._shown_source() != "recent":
            return
        lst = self.recent
        focus = lst.item(index)
        if focus is None:
            return
        order = [index, index + self._detent_dir, index - self._detent_dir]
        self._preresolve_batch += 1
        for position, target in enumerate(order):
            item = lst.item(target)
            if item is None or item.get("available") is False:
                continue
            self._preresolve_sent.add(self._preresolve_key(item))
            self._present("resolve", item=_descriptor_resource(item), direction=self._detent_dir,
                          focused=position == 0, batch=self._preresolve_batch)

    # ------------------------------------------------------------------ explorer (section 5.3)
    def _source_count(self, source):
        return self.recent.count() if source == "recent" else self.favourites.count()

    def _source_state(self, source):
        if source == "recent":
            return self.recent.state
        state = self.favourites.state
        if state in ("none", "loading"):
            return "loading"
        if state == "error":
            return "loading"   # C5-42: without a cache the tab shows loading while retries run
        return state

    def _source_item(self, source, index):
        if source == "recent":
            return self.recent.item(index)
        return self.favourites.items[index] if 0 <= index < len(self.favourites.items) else None

    def _favourites_index(self):
        focus = self.favourites.focus_id
        for index, item in enumerate(self.favourites.items):
            if _item_id(item) == focus:
                return index
        return 0

    def _open_explorer(self, now):
        """Recent 2: the explorer, on the knob list's source and focus (r3.1: Playlists opens on
        the Favourites tab)."""
        index = self.screen.index
        source = self._recent_source()
        self._list_index[source] = index
        by_source = {"recent": index if source == "recent" else self._list_index.get("recent", 0)}
        if source == "favourites":
            by_source["favourites"] = index
        explorer = ExplorerState(source=source, index_by_source=by_source)
        self._new_screen("explorer", index, "explorer open", explorer=explorer)
        self._favourites_ensure(now)
        self._present("explorer_open", t0=now, **self._explorer_payload(source, index),
                      control_id=self.control_id, control_min=0, reduced_motion=self.reduced_motion,
                      foreground_hwnd=None, sonos_available=bool(self.state["online"]))
        explorer.sent = self._explorer_sent_marker(source, index)
        if source == "favourites":
            self._request_playlist_meta()

    def _favourites_ensure(self, now, force=False):
        fav = self.favourites
        if fav.inflight is not None or now < fav.retry_at:
            return
        if fav.state == "ready" or fav.state == "empty":
            if fav.loaded_at is not None and now - fav.loaded_at <= FAVOURITES_STALE and not force:
                return
            fav.inflight = self.request("favourite_playlists", force=False, lane="lookahead")
            return
        if fav.state in ("none", "error", "signin", "loading"):
            fav.state = "loading" if fav.state in ("none", "error") else fav.state
            fav.inflight = self.request("favourite_playlists", force=True, lane="library")

    def _favourites_result(self, effect, result, error):
        fav = self.favourites
        if fav.inflight == effect["request"]:
            fav.inflight = None
        now = self.clock()
        if error is not None:
            outcome = getattr(error, "outcome", None)
            status = getattr(error, "status", None)
            if outcome in ("signin_expired", "signin_needed") or status in (401, 403):
                if not fav.items:
                    fav.state = "signin"
                    fav.signin_needed = outcome == "signin_needed"
                fav.loaded_at = None  # stale
                fav.retry_at = now + FAVOURITES_BACKOFF[0]
            elif outcome == "rate_limited" or status == 429:
                fav.retry_at = now + FAVOURITES_BACKOFF[min(fav.backoff, len(FAVOURITES_BACKOFF) - 1)]
                fav.backoff += 1
                if not fav.items:
                    fav.state = "error"
            else:
                fav.retry_at = now + FAVOURITES_BACKOFF[min(fav.backoff, len(FAVOURITES_BACKOFF) - 1)]
                fav.backoff += 1
                if not fav.items:
                    fav.state = "error"
            fav.rev += 1
            self._favourites_changed()
            return
        if not isinstance(result, list):
            return
        fav.backoff = 0
        fav.items = [dict(item) for item in result if isinstance(item, dict)]
        fav.state = "ready" if fav.items else "empty"
        fav.loaded_at = now
        fav.rev += 1
        self._favourites_changed()

    def _favourites_changed(self):
        mode = self.screen.mode
        if mode not in ("recent", "explorer"):
            return
        if self._shown_source() == "favourites":
            focus = self._favourites_index()
            if mode == "explorer":
                self.screen.explorer.index_by_source["favourites"] = focus
                if focus != self.screen.index or self._list_count() - 1 != self.bounds()[1]:
                    self._request_passive("favourites refresh")
            else:
                # r3.1 the knob list on Favourite playlists: the focus follows its playlist.
                self._list_index["favourites"] = focus
                moved = focus != self.screen.index
                self.screen.index = focus
                if moved or (self._knob_bounds is not None and self.bounds()[:2] != self._knob_bounds[:2]):
                    self._request_passive("favourites refresh")
            self._request_playlist_meta()
        if mode == "explorer":
            self._explorer_push_highlight(data=True)

    def _request_playlist_meta(self):
        """Count, mosaic and accent of the playlists near the focus (lookahead lane)."""
        fav = self.favourites
        if self._shown_source() != "favourites":
            return
        index = self.screen.index
        for position in range(max(0, index - 2), min(len(fav.items), index + 3)):
            item = fav.items[position]
            playlist = _item_id(item)
            focused = position == index
            known = fav.meta.get(playlist)
            if playlist in fav.meta_inflight or (known is not None and (not focused or known.get("duration_ms") is not None)):
                continue
            fav.meta_inflight[playlist] = self.request("playlist_meta", playlist_id=playlist, duration=focused,
                                                       last_modified=item.get("last_modified"))

    def _meta_result(self, effect, result, error):
        fav = self.favourites
        playlist = effect.get("playlist_id")
        if fav.meta_inflight.get(playlist) == effect["request"]:
            del fav.meta_inflight[playlist]
        if error is not None or not isinstance(result, dict):
            return
        merged = dict(fav.meta.get(playlist) or {})
        merged.update({key: value for key, value in result.items() if value is not None or key not in merged})
        fav.meta[playlist] = merged
        fav.rev += 1
        if self.screen.mode == "explorer":
            self._explorer_push_highlight(data=True)

    def _explorer_window(self, source, index):
        """Descriptors for the preload window (+-12 + 4 ahead): (items, items_first)."""
        total = self._source_count(source)
        first = max(0, index - EXPLORER_PRELOAD_BEHIND)
        last = min(total, index + EXPLORER_PRELOAD_AHEAD + 1)
        items = []
        for position in range(first, last):
            item = self._source_item(source, position)
            descriptor = _descriptor(item)
            if descriptor is not None and source == "favourites":
                meta = self.favourites.meta.get(_item_id(item))
                if meta:
                    descriptor.update({key: meta[key] for key in ("count", "mosaic", "art_state", "first_art",
                                                                  "duration_ms", "empty") if key in meta})
                    descriptor["accent"] = self._accent("playlist", item)
            elif descriptor is not None:
                descriptor["accent"] = self._accent("recent", item)
            items.append(descriptor)
        return items, first

    def _explorer_payload(self, source, index):
        items, first = self._explorer_window(source, index)
        state = self._source_state(source)
        total = self._source_count(source)
        return {"source": source, "index": index, "count": total if state != "loading" else None,
                "items": items, "items_first": first, "items_rev": self._source_rev(source), "state": state}

    def _source_rev(self, source):
        return self.recent.rev if source == "recent" else self.favourites.rev

    def _explorer_sent_marker(self, source, index):
        _items, first = self._explorer_window(source, index)
        state = self._source_state(source)
        return {"first": first, "rev": self._source_rev(source), "state": state,
                "count": self._source_count(source) if state != "loading" else None}

    def _explorer_push_highlight(self, bump=0, data=False):
        explorer = self.screen.explorer
        source = explorer.source
        index = self.screen.index
        marker = self._explorer_sent_marker(source, index)
        payload = {"index": index, "control_id": self.control_id, "bump": bump}
        sent = explorer.sent
        if marker["first"] != sent.get("first") or marker["rev"] != sent.get("rev"):
            items, first = self._explorer_window(source, index)
            payload.update(items=items, items_first=first, items_rev=marker["rev"])
        if marker["state"] != sent.get("state") or marker["count"] != sent.get("count"):
            payload.update(state=marker["state"], count=marker["count"])
        if data and len(payload) == 3:
            return  # nothing new to push
        explorer.sent = marker
        self._present("explorer_highlight", **payload)

    def _explorer_moved(self):
        explorer = self.screen.explorer
        explorer.index_by_source[explorer.source] = self.screen.index
        if explorer.source == "recent":
            self._recent_moved()
        else:
            self._favourites_moved()
        self._explorer_push_highlight()

    def _favourites_moved(self):
        """A detent on Favourite playlists (the explorer's tab or r3.1's knob list)."""
        item = self._source_item("favourites", self.screen.index)
        if item is not None:
            self.favourites.focus_id = _item_id(item)
        if self.screen.mode == "recent":
            self._list_index["favourites"] = self.screen.index
        self._request_playlist_meta()

    def _toggle_list_source(self, now):
        """r3.1 Recently Added 3: the knob list's source Recently Added <-> Favourite playlists, each
        keeping its focus (Playlists: the last focused playlist); crumb, heading and icon follow."""
        source = self._recent_source()
        self._list_index[source] = self.screen.index
        target = "favourites" if source == "recent" else "recent"
        self.list_source = target
        if target == "favourites":
            self._favourites_ensure(now)
            fav = self.favourites
            if fav.items:
                fav.focus_id = _item_id(fav.items[0])
        index = 0   # r3.1 design: the toggle starts the other list at its first item
        self._list_index[target] = index
        self._haptic("confirm.tick")   # r4 4.4: 3 source = tick (+ feel.fade on the knob)
        self._reenter("list source", index=index)
        self._set_transient("knob.meta.list.favourites" if target == "favourites" else "knob.meta.list.recent",
                            tone="warm", ms=LIST_SOURCE_META)
        if target == "favourites":
            self._request_playlist_meta()
        else:
            self._recent_moved()

    def _press_explorer(self, logical, now):
        explorer = self.screen.explorer
        if logical == 0:
            self._close_explorer("back")
        elif logical in (1, 2):
            target = "recent" if logical == 1 else "favourites"
            if target == explorer.source:
                return  # the active tab: ignored silently
            self._tab_switch(target, now)
        elif logical == 3:
            item = self._source_item(explorer.source, self.screen.index)
            if item is None:
                return
            kind = "playlist" if explorer.source == "favourites" else self._item_kind(item)
            accent = self._accent("playlist" if explorer.source == "favourites" else "recent", item)
            self._dispatch_start(item, kind, accent, "explorer", now)
            explorer.play_until = now + OVERLAY_PLAY_CLOSE
            self._present("explorer_close", t0=now, reason="play", close_at_ms=OVERLAY_PLAY_CLOSE_MS)
            self._schedule(now + OVERLAY_PLAY_CLOSE, "overlay play",
                           lambda at=now + OVERLAY_PLAY_CLOSE: self._overlay_play_home(at))

    def _tab_switch(self, target, now):
        explorer = self.screen.explorer
        explorer.index_by_source[explorer.source] = self.screen.index
        if target == "favourites":
            index = self._favourites_index()
            self._favourites_ensure(now)
        else:
            index = explorer.index_by_source.get("recent", 0)
        explorer.index_by_source[target] = index
        explorer.swap_until = now + TAB_SWAP
        explorer.swap_to = target
        self._present("explorer_source", t0=now, **self._explorer_payload(target, index))
        explorer.sent = self._explorer_sent_marker(target, index)

        def switch():
            explorer.source = target
            explorer.swap_to = None
            self._reenter("tab switch", index=index)
            if target == "favourites":
                self._request_playlist_meta()
            else:
                self._recent_moved()
        self._schedule(now + TAB_SWAP, "tab switch", switch)

    def _overlay_play_home(self, closed_at=None):
        """t0 + 380: the overlay has closed; the knob goes Home with `Starting…` (section 5.3.5)."""
        if self.start is not None:
            self.start.closed_at = self.clock() if closed_at is None else closed_at
        self._new_screen("home", self.display_volume, "overlay play")

    # ------------------------------------------------------------------ starts (sections 8, 9.2)
    @staticmethod
    def _item_kind(item):
        kind = item.get("kind", "")
        return {"library-albums": "album", "library-playlists": "playlist",
                "library-songs": "song"}.get(kind, kind or "album")

    def _drop_seek_follow_up(self):
        """K3 C5-77: a start drops a Seek follow-up still waiting after Seek was left, as a track
        change drops a pending target (C5-47): never sent; the in-flight jump still resolves first."""
        seek = self._seek_bg
        if seek is None:
            return
        seek.due = None
        seek.dropped = True
        seek.target_s = seek.acked_s if seek.acked_s is not None else seek.target_s
        if seek.inflight is not None:
            with self._seek_lock:        # a job still queued reads no newer target
                self._seek_targets[seek.inflight] = seek.target_s

    def _dispatch_start(self, item, kind, accent, source, now):
        name = item.get("title", "")
        # DD-DES-001: one event at the press, as Scene run: Play's started thump (r4 4.4) plays here, and the
        # speaker's answer carries no second haptic (_start_result); a failure keeps its error.buzz.
        self._haptic(self._feedback_haptic("ok", 0, "started", None))
        self._drop_seek_follow_up()
        request = self.request("play_items", item=deepcopy(_descriptor_resource(item)), name=name, accent=accent,
                               source=source, lenient=kind == "playlist", item_kind=kind,
                               expected_group_revision=self.state["group_revision"])
        self.start = StartPending(request, kind, name, accent, source, self._start_closed_at(source, now),
                                  _item_id(item))
        self.notice = ""
        return request

    @staticmethod
    def _start_closed_at(source, now):
        """StartPending.closed_at: an overlay start closes its overlay at t0 + 380 (section 5.3.5
        step 4), so its exit toast is due at max(t0 + 380 + 360, result) even when the result
        lands first (section 12.3); a Recent start has no overlay (the press time)."""
        return now + OVERLAY_PLAY_CLOSE if source in ("explorer", "upnext") else now

    def _press_recent(self, logical, now):
        if logical == 0:
            self._go_home("back")
        elif logical == 1:
            self._open_explorer(now)
        elif logical == 2:
            if self.spaces:
                self._toggle_list_source(now)   # r3.1: Recently Added <-> Favourite playlists
                return
            item = self.recent.item(self.screen.index)
            self._dispatch_play_next(item)
        elif logical == 3:
            if self._recent_source() == "favourites":
                item = self._source_item("favourites", self.screen.index)
                self._dispatch_start(item, "playlist", self._accent("playlist", item), "recent", now)
            else:
                item = self.recent.item(self.screen.index)
                self._dispatch_start(item, self._item_kind(item), self._accent("recent", item), "recent", now)
            self._new_screen("home", self.display_volume, "start")

    def _start_result(self, effect, result, error):
        start = self.start
        if start is None or start.request != effect["request"]:
            return self._apply_result_state(effect, result, error)
        self.start = None
        now = self.clock()
        overlay = start.source in ("explorer", "upnext")
        if error is not None:
            outcome = getattr(error, "outcome", None) or "start_failed"
            if self._discarded(error):
                return
            if outcome == "group_changed":
                self._feedback("err")
                self._group_changed_copy()
                return
            blocked = outcome == "album_blocked"
            self._feedback("err")
            self._set_transient("knob.status.album_blocked" if blocked else "knob.status.start_failed",
                                tone="error", ms=START_FAIL_STATUS)
            if getattr(error, "unavailable", False) and start.source == "recent":
                for item in self.recent.items:
                    if _item_id(item) == start.item_id:
                        item["available"], item["reason"] = False, str(error)
                        self.recent.rev += 1
            toast = "toast.start.album_blocked" if blocked else "toast.start.failed"
            fields = {"album": start.name} if blocked else {"name": start.name}
            if overlay:
                self._exit_toast(toast, start.closed_at, **fields)
            else:
                self._toast(toast, **fields)
            if getattr(error, "partial", False):
                self.notice = str(error)
            return
        result = dict(result or {})
        info = result.pop("_start", None) or {}
        result.pop("_final_song_ids", None)
        self._state(result, enter=False)
        if self.confirmed_playing() is not True:
            self._album_start_until = now + ALBUM_START_HOLD_SECONDS
        self._feedback("ok", moment="started", color=start.accent, haptic=False)   # DD-DES-001: armed at the press
        k, n, u = _int(info.get("k"), 0), _int(info.get("n"), 0), _int(info.get("u"), 0)
        if start.kind == "playlist" and u > 0 and n:
            self._set_transient("knob.status.partial", ms=PARTIAL_STATUS, k=k, n=n)
            toast, fields = ("toast.start.partial_one" if u == 1 else "toast.start.partial"), {"k": k, "n": n, "u": u}
        else:
            toast, fields = "toast.start.ok", {"name": start.name}
        if start.source == "tracks":
            # r3.1 design: Tracks 4 played the focused row: `Playing {n} / {T}` (success).
            P, T = self._position()
            self._set_transient("knob.meta.tracks.playing", tone="success", ms=R3_REFUSED_META, n=P, T=T)
        if overlay:
            self._exit_toast(toast, start.closed_at, **fields)
        else:
            self._toast(toast, **fields)

    # ------------------------------------------------------------------ Play next (section 9.3)
    def _dispatch_play_next(self, item, kind=None, accent=None):
        """Play next (section 9.3) of an album / song, or (r3.1) a favourite playlist (`kind`
        "playlist", its playlist accent)."""
        kind = kind or self._item_kind(item)
        accent = self._accent("recent", item) if accent is None else accent
        request = self.request("play_next", item=deepcopy(_descriptor_resource(item)), name=item.get("title", ""),
                               accent=accent, item_kind=kind,
                               expected_group_revision=self.state["group_revision"],
                               expected_track_id=self.state.get("track_id"))
        self.play_next_job = PlayNextJob(request, dict(item), item.get("title", ""), accent)
        self.notice = ""

    def progress(self, request, payload):
        """Section 10.3: progress of a running job (a stale request is ignored)."""
        if request not in self.pending or not isinstance(payload, dict):
            return
        job = self.play_next_job
        if job is not None and job.request == request:
            phase = payload.get("phase")
            if phase in ("resolving", "inserting"):
                job.phase = phase
            if type(payload.get("n")) is int:
                job.n = payload["n"]
            if type(payload.get("k")) is int:
                job.k = payload["k"]
            return
        shuffle = self.shuffle_job
        if shuffle is not None and shuffle.request == request and payload.get("phase") == "accepted":
            if not shuffle.accepted:
                shuffle.accepted = True
                self._note_shuffle_record(shuffle)
                self._feedback("ok", moment="shuffle", haptic=False)   # DD-DES-001: the press ticked
                self._set_transient("knob.meta.shuffle.on" if shuffle.on else "knob.meta.shuffle.off",
                                    tone="warm" if self.spaces else "meta", ms=FEEDBACK_META)

    def _playnext_result(self, effect, result, error):
        job = self.play_next_job
        mine = job is not None and job.request == effect["request"]
        if effect["kind"] == "move_next":
            if self.move_next_request == effect["request"]:
                self.move_next_request = None
            mine = True
        if not mine:
            return self._apply_result_state(effect, result, error)
        name = job.name if job is not None else ""
        self.play_next_job = None if effect["kind"] == "play_next" else self.play_next_job
        overlay = self._overlay_open()
        if error is not None:
            if self._discarded(error):
                return
            outcome = getattr(error, "outcome", None) or "nothing_added"
            self._feedback("err")
            meta = {"partial": "knob.meta.playnext.partial", "song_changed": "knob.meta.playnext.song_changed",
                    "sonos_shuffle_on": "knob.meta.playnext.shuffle",
                    "group_changed": "knob.meta.group_changed",
                    "sonos_unavailable": "knob.meta.sonos_unavailable",
                    "signin_expired": "knob.meta.signin_expired",
                    "signin_needed": "knob.meta.signin_needed"}.get(outcome, "knob.meta.playnext.nothing")
            toast = {"partial": "toast.playnext.partial", "song_changed": "toast.playnext.song_changed",
                     "sonos_shuffle_on": "toast.playnext.shuffle"}.get(outcome, "toast.playnext.nothing")
            if outcome == "not_queue_source":
                cls = getattr(error, "source", None) or self.source()
                cls = cls if cls in ("airplay", "radio", "linein", "none") else "none"
                meta = "knob.meta.playnext." + cls
                toast = "toast.playnext.none" if cls == "none" else "toast.playnext.not_queue"
            self._set_transient(meta, tone="error", ms=FAIL_META)
            if effect["kind"] == "play_next" and not overlay:
                self._toast(toast, album=name)
            return
        result = dict(result or {})
        result.pop("_inserted", None)
        self._apply_state_result(result)
        if not self.spaces:
            self._feedback("ok", moment="queued")   # r3.1 flashes at the hold (above), not again here
        if self.spaces:
            # r3.1 design: `Queued · {title}` / Up next `Plays next · {track}` (success, 2.2 s).
            if effect["kind"] == "move_next":
                title = (effect.get("item") or {}).get("title", "")
                self._set_transient("knob.meta.upnext.plays_next", tone="success", ms=QUEUED_META_R3,
                                    text=fit_copy("knob.meta.upnext.plays_next", LINE_R3, title=title))
            else:
                self._set_transient("knob.meta.queued_title", tone="success", ms=QUEUED_META_R3,
                                    text=fit_copy("knob.meta.queued_title", LINE_R3, title=name))
        else:
            self._set_transient("knob.meta.playnext.ok", ms=QUEUED_META)
        if effect["kind"] == "play_next" and not overlay:
            self._toast("toast.playnext.ok", album=name)
        self._our_queue_changed()

    # ------------------------------------------------------------------ Tracks (section 5.4)
    def _enter_tracks(self, index, cause, focus=None):
        """Tracks: r3.1 browses the whole queue from the playing row (the focus is a 0-based row;
        `focus`: Up next's row on its Back); without a queue (a stream) and in r2.2 the 3-position
        transport (0 previous · 1 · 2 next)."""
        if self._tracks_queue():
            P, T = self._position()
            index = _clamp(focus, 0, T - 1) if type(focus) is int else P - 1
        self._new_screen("tracks", index, cause)
        self._neighbours_read()
        self._tracks_fetch()

    # r3.1 whole-queue Tracks: a paged row cache per queue revision -------------------------------
    def _tracks_sync_revision(self):
        revision = str(self.state.get("queue_revision", ""))
        if revision != self._tracks_revision:
            self._tracks_revision = revision
            self._tracks_rows = {}
            self._tracks_pages = {}

    def _tracks_fetch(self):
        """Read the queue page of the focus (and the next / previous page near a loaded edge) with
        `queue_window` (purpose `tracks_page`); at most one read per page in flight."""
        if self.screen.mode != "tracks" or not self._tracks_queue():
            return
        self._tracks_sync_revision()
        if self.clock() < getattr(self, "_tracks_retry_at", 0.0):
            return
        P, T = self._position()
        focus = _clamp(self.screen.index, 0, T - 1)
        starts = []
        for probe in (focus, focus + TRACKS_EDGE, focus - TRACKS_EDGE, P - 1):
            if 0 <= probe < T:
                start = probe // TRACKS_PAGE * TRACKS_PAGE
                if start not in starts:
                    starts.append(start)
        for start in starts:
            last = min(T, start + TRACKS_PAGE)
            if start in self._tracks_pages or all(n in self._tracks_rows for n in range(start + 1, last + 1)):
                continue
            self._tracks_pages[start] = self.request("queue_window", start=start, count=last - start,
                                                     purpose="tracks_page", key=[self._tracks_revision])
        if len(self._tracks_rows) > TRACKS_CACHE_ROWS:
            keep = sorted(self._tracks_rows, key=lambda n: abs(n - 1 - focus))[:TRACKS_CACHE_ROWS]
            self._tracks_rows = {n: self._tracks_rows[n] for n in keep}

    def _tracks_page_result(self, effect, result, error):
        start = effect.get("start")
        if self._tracks_pages.get(start) == effect["request"]:
            del self._tracks_pages[start]
        key = (effect.get("key") or [None])[0]
        if key != self._tracks_revision:
            return   # a page of an older queue revision never commits
        if error is not None or not isinstance(result, dict):
            if error is not None and not self._discarded(error):
                self._tracks_retry_at = self.clock() + 1.0   # asked again by the next turn / tick
            return
        for row in result.get("rows") or ():
            if isinstance(row, dict) and type(row.get("row")) is int:
                self._tracks_rows[row["row"]] = dict(row)
        self._tracks_fetch()

    def _tracks_state_changed(self, was_position):
        """A state while on Tracks: the focus follows the playing row it was on; the knob re-enters
        when the queue's length or the Tracks regime (whole queue / transport) changed."""
        if self.screen.mode != "tracks" or not self.spaces:
            return
        queue = self._tracks_queue()
        if queue != getattr(self, "_tracks_is_queue", queue):
            self.screen.index = self._position()[0] - 1 if queue else 1
            self._request_passive("tracks regime")
            self._tracks_fetch()
            return
        if not queue:
            return
        P, T = self._position()
        old = _int(was_position, 0)
        if old and P != old and self.screen.index == old - 1:
            self.screen.index = P - 1
            self._request_passive("tracks now playing")
        elif self._knob_bounds is not None and self.bounds()[:2] != self._knob_bounds[:2]:
            self.screen.index = _clamp(self.screen.index, 0, T - 1)
            self._request_passive("tracks queue changed")
        self._tracks_fetch()

    def _tracks_jump(self, now):
        """r3.1 Tracks 4 on another row: `jump` there (stays on Tracks, which re-centres on it)."""
        number = self.screen.index + 1
        row = self._tracks_rows.get(number) or {}
        name = row.get("title", "")
        accent = self._accent("row", row) if row else 0
        playing, _total = self._position()
        self._haptic("nudge.right" if number > playing else "nudge.left")   # r4 4.4: a jump nudges its way
        self._drop_seek_follow_up()
        request = self.request("jump", row=number, name=name, accent=accent,
                               expected_group_revision=self.state["group_revision"],
                               expected_track_id=self.state.get("track_id"),
                               expected_update_id=str(self.state.get("queue_revision", "")))
        self.start = StartPending(request, "track", name, accent, "tracks", now, str(row.get("song_id") or ""))
        self.notice = ""

    def _neighbours_read(self):
        if self.screen.mode not in ("tracks",) or self.source() != "queue":
            return
        if self._tracks_queue():
            return   # r3.1: the whole-queue page cache has the rows
        P, T = self._position()
        key = (self.state.get("queue_revision"), P)
        if key in self._neighbours or self._neighbours_request in self.pending:
            return
        # r3: rows P-2..P+2 (the Navigator's Tracks card, queue_titles); r2.2: P-1..P+1.
        start, count = (max(0, P - 3), 5) if self.spaces else (max(0, P - 2), 3)
        self._neighbours_request = self.request("queue_window", start=start, count=count, purpose="tracks",
                                                key=list(key))

    def _neighbours_result(self, effect, result, error):
        if error is not None or not isinstance(result, dict):
            return
        key = tuple(effect.get("key") or ())
        entry = self._neighbours.setdefault(key, {})
        for row in result.get("rows") or ():
            if isinstance(row, dict) and type(row.get("row")) is int:
                entry[row["row"]] = row.get("title", "")
        if len(self._neighbours) > 8:
            for old in list(self._neighbours)[:-8]:
                del self._neighbours[old]

    def _press_tracks(self, logical, now):
        if logical == 0:
            self._go_home("back")
        elif logical == 1:
            self._open_upnext(now)
        elif logical == 2:
            self._enter_seek(now)
        elif logical == 3:
            if self._tracks_queue():
                self._tracks_jump(now)
                return
            index = self.screen.index
            end = self._queue_end(index)
            if end is not None:
                if self.spaces:   # r3: an unavailable press (README 1)
                    self._set_transient("knob.meta.skip." + end, tone="error", ms=R3_REFUSED_META)
                    self._feedback("err", moment="refused")
                    return
                self._set_transient("knob.meta.skip." + end, ms=FEEDBACK_META)
                self._feedback("err")
                return
            direction = {0: "previous", 2: "next"}[index]
            # DD-DES-001: a skip nudges its way at the press (r4 4.4); its result carries no second haptic.
            self._haptic(self._feedback_haptic("ok", SKIP_DIRECTIONS[direction], None, None))
            self.notice = ""
            self.command_request = self.request("transport", direction=direction,
                                                expected_group_revision=self.state["group_revision"],
                                                expected_track_id=self.state.get("track_id"), index=index)

    def _transport_result(self, effect, result, error):
        if self.command_request == effect["request"]:
            self.command_request = None
        home_command = effect.get("direction") in ("play", "pause")
        if error is not None:
            if self._discarded(error):
                return
            self.notice = str(error)
            self._feedback("err")
            return
        result = dict(result or {})
        if self._obsolete_group(effect, result):
            return
        reenter = self._state(result, enter=False)
        if home_command:
            if reenter and self.screen.mode in VOLUME_MODES:
                self._enter("volume")
            return
        skip = SKIP_DIRECTIONS.get(effect.get("direction"), 0)
        self._feedback("ok", skip, haptic=False)   # DD-DES-001: the press nudged
        self._toast("toast.skip.next" if skip == 1 else "toast.skip.prev", title=self.state.get("title", ""))
        if (self.screen.mode == "tracks" and effect.get("view_id") == self.screen.view_id
                and not self._tracks_queue()):
            self.screen.index = 1
            self._reenter("skip ok", index=1)
        elif reenter and self.screen.mode in VOLUME_MODES:
            self._enter("volume")

    # ------------------------------------------------------------------ Seek (section 5.5)
    def _enter_seek(self, now):
        duration = _int(self.state.get("duration_s"), 0) or 1
        position = _int(self.state.get("position_s"), 0)
        if self.state.get("playback") == "PLAYING":
            position += int(max(0.0, now - self._state_at))
        p = min(position, duration)
        end = max(0, duration - SEEK_MARGIN_S)
        p1 = min(p, end)
        n0 = math.ceil(p1 / SEEK_STEP_S)
        maximum = n0 + math.ceil((end - p1) / SEEK_STEP_S)
        seek = SeekState(D=duration, p0=p1, n0=n0, max=maximum, target_s=p1, idle_due=now + SEEK_IDLE,
                         track_id=self.state.get("track_id"), acked_s=p1)
        self._new_screen("seek", n0, "seek", seek=seek, parent_index=1)

    def _seek_busy(self):
        seek = self.screen.seek if self.screen.mode == "seek" else None
        return bool(seek and seek.busy)

    def _seek_tick(self, now):
        for seek in (self.screen.seek if self.screen.mode == "seek" else None, self._seek_bg):
            if seek is None:
                continue
            if seek.due is not None and now >= seek.due and seek.inflight is None:
                if seek.target_s != seek.acked_s and not seek.dropped:
                    self._send_seek(seek)
                else:
                    # Nothing waits: the last jump sent is the target (or it was dropped), so the
                    # burst is over and `seek_busy` ends with it (C5-68).
                    seek.due = None
                    seek.landed_s = None
        seek = self.screen.seek if self.screen.mode == "seek" else None
        if (seek is not None and not self.spaces and not seek.busy and seek.due is None
                and now >= seek.idle_due):   # r3 Seek waits for Set / Cancel (README 1.2)
            self._leave_seek(flush=False, drop=False)
            self._enter_tracks(1, "seek idle")
        if self._seek_bg is not None and self._seek_bg.inflight is None and (
                self._seek_bg.due is None or self._seek_bg.target_s == self._seek_bg.acked_s):
            self._seek_bg = None

    def _send_seek(self, seek):
        seek.due = None
        seek.acked_s = seek.target_s
        request = self.request("seek", target_s=seek.target_s, expected_group_revision=self.state["group_revision"],
                               expected_track_id=seek.track_id)
        seek.inflight = request
        with self._seek_lock:
            self._seek_targets[request] = seek.target_s

    def _leave_seek(self, flush=True, drop=False, commit=False):
        """Explicit exits flush a debouncing target (C5-68: while a jump is in flight the one
        follow-up target is kept for when it lands); unmade exits drop it (C5-47). r3 (README 1.2):
        only Set (`commit`) applies a scrub; every other exit drops it."""
        seek = self.screen.seek
        if seek is None:
            return
        if self.spaces and not commit:
            flush, drop = False, True
        seek.left = True
        if drop:
            seek.due = None
            seek.dropped = True
            seek.target_s = seek.acked_s if seek.acked_s is not None else seek.target_s
            if seek.inflight is not None:
                with self._seek_lock:   # a job still queued reads no newer target
                    self._seek_targets[seek.inflight] = seek.target_s
        elif flush and seek.target_s != seek.acked_s:
            if seek.inflight is None:
                self._send_seek(seek)
            else:
                seek.due = self.clock()
        if seek.inflight is not None or (seek.due is not None and seek.target_s != seek.acked_s):
            self._seek_bg = seek

    def _press_seek(self, logical, now):
        if self.spaces:
            self._press_seek_r3(logical, now)
            return
        if logical in (0, 2):
            self._leave_seek(flush=True)
            self._enter_tracks(1, "seek off")
        elif logical == 1:
            self._leave_seek(flush=True)
            self._enter_tracks(1, "seek off")
            if self._tracks_upnext_code() is None:
                self._open_upnext(now)

    def _press_seek_r3(self, logical, now):
        """README 1.2 Seek: a scrub is applied only by 3 Set; 1 Cancel leaves the song where it
        was (nothing was sent), 2 opens Up next without applying the scrub."""
        seek = self.screen.seek
        if logical == 2:
            self._leave_seek(flush=True, commit=True)   # the one seek of this Seek visit
            self._enter_tracks(1, "seek set")
            self._set_transient("knob.meta.seek.set", tone="success", ms=SEEK_R3_META)
            self._feedback("ok")
            return
        self._leave_seek(flush=False, drop=True)
        self._enter_tracks(1, "seek cancel" if logical == 0 else "seek off")
        if logical == 0:
            self._set_transient("knob.meta.seek.cancelled", tone="secondary", ms=SEEK_R3_META)
        elif logical == 1 and self._tracks_upnext_code() is None:
            self._open_upnext(now)

    def _seek_result(self, effect, result, error):
        seek = None
        for candidate in (self.screen.seek if self.screen.mode == "seek" else None, self._seek_bg):
            if candidate is not None and candidate.inflight == effect["request"]:
                seek = candidate
        with self._seek_lock:
            self._seek_targets.pop(effect["request"], None)
            read = self._seek_read.pop(effect["request"], None)
        now = self.clock()
        if seek is None:
            if error is not None and not self._discarded(error) and getattr(error, "outcome", None) == "not_confirmed":
                self._feedback("err")
            if error is None:
                self._apply_state_result(result)
            return
        seek.inflight = None
        if error is not None:
            if self._discarded(error):
                seek.landed_s = None
                return
            outcome = getattr(error, "outcome", None) or "not_confirmed"
            seek.landed_s = None
            seek.due = None
            seek.acked_s = seek.target_s  # a pending follow-up target is dropped with the failure
            if outcome == "song_changed":
                if not seek.left:
                    self._leave_seek(flush=False, drop=True)
                    self._enter_tracks(1, "seek song changed")
                return
            self._feedback("err")
            if not seek.left:
                seek.fail_until = now + SEEK_FAIL_LINE
                seek.idle_due = now + SEEK_IDLE
            return
        result = dict(result or {})
        applied = result.pop("_applied_seek", effect.get("target_s"))
        result.pop("_seek_kept_state", None)
        # The landed target is the one this job read when it started (a job still queued picks up
        # the newest turn), not the one at send time: a later turn back to the sent value must
        # still be sent (section 5.5.4, C5-68). The adapter's clamp of it (`_applied_seek`) is
        # only the fallback when the read is unknown.
        if type(read) is int:
            landed = read
        elif type(applied) is int:
            landed = applied
        else:
            landed = seek.acked_s
        seek.acked_s = landed
        seek.landed_s = landed
        if seek.dropped:
            seek.target_s = landed   # a dropped target is never sent afterwards (C5-47)
        self._apply_state_result(result)
        if seek.target_s == seek.landed_s:
            seek.landed_s = None
            seek.due = None
        elif seek.due is None:
            seek.due = now   # the one follow-up jump, still 250 ms after the last detent
        if not seek.left:
            seek.idle_due = now + SEEK_IDLE

    # ------------------------------------------------------------------ Up next (section 5.6)
    def _upnext_count(self):
        upnext = self.screen.upnext
        if upnext is None:
            return 0
        if upnext.card:
            return upnext.P + 1
        return upnext.T

    def _upnext_on_card(self):
        upnext = self.screen.upnext
        return bool(upnext and upnext.card and self.screen.index == upnext.P)

    def _upnext_focus_row(self):
        upnext = self.screen.upnext
        if upnext is None or self._upnext_on_card():
            return None
        return upnext.rows.get(self.screen.index + 1)

    def _upcoming_loaded(self):
        upnext = self.screen.upnext
        if upnext is None:
            return False
        return all(row in upnext.rows for row in range(upnext.P + 1, upnext.T + 1))

    def _playnext_offsets(self):
        """0-based offsets (from P+1) of the upcoming rows the ledger attributes to Play next."""
        upnext = self.screen.upnext
        if upnext is None:
            return []
        return [row - upnext.P - 1 for row in range(upnext.P + 1, upnext.T + 1)
                if upnext.rows.get(row, {}).get("segment") == "playnext"]

    def _open_upnext(self, now):
        P, T = self._position()
        card = self.sonos_shuffle()
        upnext = UpNextState(P=P, T=T, card=card, regime="sonos" if card or T - P > COMPANION_SHUFFLE_MAX else "companion",
                             revision=str(self.state.get("queue_revision", "")))
        parent = _clamp(self.screen.index, 0, 2) if self.screen.mode == "tracks" else 1
        focus = max(0, P - 1)
        if self.screen.mode == "tracks" and self._tracks_queue():
            # r3.1 design: Up next opens on the row Tracks has in focus (and Back returns it).
            parent = self.screen.index
            focus = _clamp(self.screen.index, 0, max(0, (P + 1 if card else T) - 1))
        self._new_screen("upnext", focus, "upnext open", upnext=upnext, parent_index=parent)
        upnext.reads.append((max(0, focus - 10), UPNEXT_WINDOW, "upnext"))
        shuffle_read = self._upcoming_read(max(0, focus - 10))
        if shuffle_read is not None:
            upnext.reads.append(shuffle_read)
        self._present("upnext_open", t0=now, **self._upnext_payload(), control_id=self.control_id, control_min=0,
                      reduced_motion=self.reduced_motion, foreground_hwnd=None)
        self._upnext_next_read()

    def _upnext_payload(self, rows=None):
        upnext = self.screen.upnext
        return {"rows": self._upnext_rows_payload(rows), "now": upnext.P - 1, "focus": self.screen.index,
                "count": self._upnext_count(), "card": {"n": max(0, upnext.T - upnext.P)} if upnext.card else None,
                "context": self._upnext_context(), "shuffle": self._shuffle_token(),
                "likes_known": self._likes_known(), "loading": upnext.loading}

    def _shuffle_token(self):
        if self.sonos_shuffle():
            return "sonos"
        if self.state.get("companion_shuffle"):
            return "companion"
        return "off"

    def _likes_known(self):
        upnext = self.screen.upnext
        rows = [row for row in upnext.rows.values() if row.get("song_id") and row.get("catalog") is not False]
        return bool(rows) and all(row.get("liked") is not None for row in rows)

    def _row_role(self, number):
        P = self.screen.upnext.P
        if number < P:
            return "played"
        if number == P:
            return "now"
        if number == P + 1:
            return "next"
        return "upcoming"

    def _upnext_rows_payload(self, rows=None):
        upnext = self.screen.upnext
        numbers = sorted(upnext.rows) if rows is None else rows
        out = []
        for number in numbers:
            row = upnext.rows.get(number)
            if row is None:
                continue
            entry = _descriptor(row)
            entry["role"] = self._row_role(number)
            entry["accent"] = self._accent("row", row)
            out.append(entry)
        return out

    def _upnext_context(self):
        upnext = self.screen.upnext
        rows = [upnext.rows[number] for number in sorted(upnext.rows)]
        try:
            context = self.ledger.classify(rows, total=upnext.T)
        except Exception:
            _log.exception("Queue ledger classification failed")
            return {"kind": "foreign", "title": "Sonos queue", "sub": ""}
        for number, role in zip(sorted(upnext.rows), context.roles):
            upnext.rows[number]["segment"] = role
        upnext.context = context.presenter()
        return upnext.context

    def _upnext_next_read(self):
        upnext = self.screen.upnext
        if upnext is None or upnext.read_inflight is not None or not upnext.reads:
            return
        start, size, purpose = upnext.reads.pop(0)
        upnext.read_inflight = self.request("queue_window", start=start, count=min(100, max(1, size)),
                                            purpose=purpose)

    def _upnext_refill(self):
        upnext = self.screen.upnext
        if upnext is None or upnext.loading or not upnext.rows:
            return
        focus_row = self.screen.index + 1
        if focus_row > upnext.T:
            return
        low, high = min(upnext.rows), max(upnext.rows)
        near_low = focus_row - low < UPNEXT_EDGE and low > 1
        near_high = high - focus_row < UPNEXT_EDGE and high < upnext.T
        missing = focus_row not in upnext.rows
        if not (near_low or near_high or missing):
            return
        start = max(0, self.screen.index - 10)
        spec = (start, UPNEXT_WINDOW, "upnext")
        upnext.reads = [read for read in upnext.reads if read[2] != "upnext"] + [spec]  # newest need wins
        self._upnext_next_read()

    def _window_result(self, effect, result, error):
        purpose = effect.get("purpose")
        if purpose == "tracks_page":
            return self._tracks_page_result(effect, result, error)
        if purpose in ("tracks", "tracks_last"):
            if self._neighbours_request == effect["request"]:
                self._neighbours_request = None
            return self._neighbours_result(effect, result, error)
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if upnext is None or effect.get("view_id") != self.screen.view_id:
            return
        if upnext.read_inflight == effect["request"]:
            upnext.read_inflight = None
        if error is not None or not isinstance(result, dict):
            if upnext.loading:
                # The whole queue is still loading: ask again in a second (the 60 s idle close
                # bounds it); the frame keeps `Loading queue…` with the Working comet.
                spec = (effect.get("start", 0), effect.get("count", UPNEXT_WINDOW), effect.get("purpose", "upnext"))

                def retry(spec=spec, upnext=upnext):
                    upnext.reads.insert(0, spec)
                    self._upnext_next_read()
                self._schedule(self.clock() + 1.0, "upnext retry", retry)
            self._upnext_next_read()
            return
        first_window = upnext.loading
        upnext.loading = False
        total = _int(result.get("total"), upnext.T)
        new_rows = []
        for row in result.get("rows") or ():
            if not isinstance(row, dict) or type(row.get("row")) is not int:
                continue
            number = row["row"]
            existing = upnext.rows.get(number) or {}
            merged = dict(row)
            for key in ("catalog", "liked", "album", "track_number", "art_template", "art_max", "art_bg",
                        "art_ink", "accent", "url", "release_year", "disc_number"):
                if key in existing and existing.get("signature") == row.get("signature"):
                    merged.setdefault(key, existing[key])
            merged.setdefault("liked", None)
            if not merged.get("song_id"):
                merged["catalog"] = False
            else:
                merged.setdefault("catalog", None)
            upnext.rows[number] = merged
            new_rows.append(number)
        if total != upnext.T and not upnext.card:
            upnext.T = total
        upnext.revision = str(result.get("update_id", upnext.revision))
        self._upnext_enrich(new_rows)
        now = self.clock()
        if upnext.identity is not None:
            self._upnext_restore_identity()
        if upnext.pending_regime is not None:
            regime, upnext.pending_regime = upnext.pending_regime, None
            self._present("upnext_rows", t0=now, reason="shuffle", **self._upnext_payload())
            upnext.swap_until = now + SHUFFLE_SWAP
            self._schedule(now + SHUFFLE_SWAP, "sonos shuffle off", lambda: self._reenter("sonos shuffle off"))
        else:
            reason = "data" if first_window or effect.get("purpose") != "requeue" else "queue_changed"
            self._present("upnext_rows", t0=now, reason=reason, **{**self._upnext_payload(new_rows)})
        self._upnext_next_read()

    def _upnext_enrich(self, numbers):
        upnext = self.screen.upnext
        ids = []
        for number in numbers:
            song = upnext.rows[number].get("song_id")
            if song and song not in upnext.enriched and song not in ids:
                ids.append(str(song))
        if not ids:
            return
        upnext.enriched.update(ids)
        self.request("catalog_songs", ids=ids[:300])
        self.request("ratings", ids=ids[:100], purpose="rows")

    def _enrich_result(self, effect, result, error):
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if effect["kind"] == "ratings" and effect.get("purpose") == "late_check":
            return self._late_check_result(effect, result, error)
        if upnext is None:
            return
        ids = [str(v) for v in effect.get("ids") or ()]
        if error is not None or not isinstance(result, dict):
            if effect["kind"] == "ratings" and ids:
                if not set(ids) <= upnext.ratings_failed:
                    upnext.ratings_failed.update(ids)
                    upnext.enriched.difference_update(ids)  # retried once with the next window read
            return
        changed = []
        for number, row in upnext.rows.items():
            song = str(row.get("song_id") or "")
            if song not in ids:
                continue
            if effect["kind"] == "catalog_songs":
                found = result.get(song) or {}
                if found.get("catalog"):
                    for key in ("album", "track_number", "disc_number", "duration_s", "art_template", "art_max",
                                "art_bg", "art_ink", "url", "release_year"):
                        if found.get(key) is not None:
                            row[key] = found[key]
                    row["accent"] = found.get("accent", row.get("accent", 0))
                    row["catalog"] = True
                else:
                    row["catalog"] = False
            else:
                row["liked"] = result.get(song) == 1
            changed.append(number)
        if changed:
            self._present("upnext_rows", t0=self.clock(), reason="data", **self._upnext_payload(sorted(changed)))

    def _upnext_changes(self, before_revision, before_position):
        """Section 5.6.8: a song ended (roles live) or the queue changed (re-read around the focus)."""
        upnext = self.screen.upnext
        P, T = self._position()
        revision = str(self.state.get("queue_revision", ""))
        if self.source() != "queue":
            self.close_overlay("source")
            return
        position_changed = P != upnext.P
        revision_changed = revision != before_revision and revision != upnext.revision
        if self._exclusive_running() and revision_changed:
            revision_changed = False  # our own job's edits wait for its completion (section 1.1)
        if position_changed:
            upnext.P = P
            self._present("upnext_rows", t0=self.clock(), reason="data", **self._upnext_payload([]))
        if revision_changed:
            self._upnext_requeue(T)

    def _upnext_requeue(self, T=None):
        upnext = self.screen.upnext
        focus_row = upnext.rows.get(self.screen.index + 1)
        if focus_row is not None:
            signature = focus_row.get("signature")
            occurrence = sum(1 for number in sorted(upnext.rows) if number <= self.screen.index + 1
                             and upnext.rows[number].get("signature") == signature)
            upnext.identity = (signature, occurrence)
        if T is None:
            T = self._position()[1]
        upnext.T = T
        upnext.card = self.sonos_shuffle()
        upnext.rows = {}
        upnext.revision = str(self.state.get("queue_revision", ""))
        start = max(0, self.screen.index - 10)
        upnext.reads = [(start, UPNEXT_WINDOW, "requeue")]
        shuffle_read = self._upcoming_read(start)
        if shuffle_read is not None:
            upnext.reads.append(shuffle_read)
        upnext.read_inflight = None
        self._upnext_next_read()

    def _upcoming_read(self, window_start):
        """The rows P+1..T read (section 5.6.1, section 9.7.1) that the companion shuffle plan
        needs (section 9.5.2), when U <= 60 and the 21-row window from `window_start` (0-based)
        does not cover them; else None. On open and after every re-read, so Shuffle never stays
        dimmed `loading` once the rows were dropped."""
        upnext = self.screen.upnext
        P, T = upnext.P, upnext.T
        U = T - P
        if upnext.card or not 0 < U <= COMPANION_SHUFFLE_MAX:
            return None
        if window_start <= P and window_start + UPNEXT_WINDOW >= T:
            return None
        return (P, U, "shuffle")

    def _upnext_restore_identity(self):
        upnext = self.screen.upnext
        signature, occurrence = upnext.identity
        seen = 0
        target = None
        for number in sorted(upnext.rows):
            if upnext.rows[number].get("signature") == signature:
                seen += 1
                if seen == occurrence:
                    target = number - 1
                    break
        upnext.identity = None
        count_now = self._upnext_count()
        if target is None:
            target = _clamp(self.screen.index, 0, max(0, count_now - 1))
        if target != self.screen.index or self.bounds()[1] != max(0, count_now - 1):
            self.screen.index = target
            self._request_passive("upnext queue changed")

    def _exclusive_running(self):
        return self._busy_code() is not None

    def _our_queue_changed(self):
        """A Play next / shuffle / jump / move_next of ours completed: as a revision change."""
        if self.screen.mode == "upnext":
            self._upnext_requeue()

    def _press_upnext(self, logical, now):
        upnext = self.screen.upnext
        if logical == 0:
            self._close_upnext("back")
        elif logical == 1:
            self._shuffle_press(now)
        elif logical == 2:
            row = self._upnext_focus_row()
            if self.upnext_button3 == "playnext":
                self.move_next_request = self.request("move_next", row=row["row"],
                                                      expected_group_revision=self.state["group_revision"],
                                                      expected_update_id=upnext.revision, item=_descriptor(row))
                return
            self._like_press(row)
        elif logical == 3:
            row = self._upnext_focus_row()
            accent = self._accent("row", row)
            # DD-DES-001: an Up next jump nudges its way at the press, as a Tracks jump (r4 4.4), never a thump.
            self._haptic("nudge.right" if row["row"] > self._position()[0] else "nudge.left")
            self._drop_seek_follow_up()
            self.request("jump", row=row["row"], name=row.get("title", ""), accent=accent,
                         expected_group_revision=self.state["group_revision"],
                         expected_track_id=self.state.get("track_id"), expected_update_id=upnext.revision)
            request = self.serial
            self.start = StartPending(request, "track", row.get("title", ""), accent, "upnext",
                                      self._start_closed_at("upnext", now), str(row.get("song_id") or ""))
            upnext.play_until = now + OVERLAY_PLAY_CLOSE
            self._present("upnext_close", t0=now, reason="play", close_at_ms=OVERLAY_PLAY_CLOSE_MS)
            self._schedule(now + OVERLAY_PLAY_CLOSE, "overlay play",
                           lambda at=now + OVERLAY_PLAY_CLOSE: self._overlay_play_home(at))

    def _like_press(self, row):
        upnext = self.screen.upnext
        if row.get("liked") is True:
            self._refuse(2, "unlike_unavailable")  # [r2.2] add-only, final (C5-67): no request
            return
        if self.music_signin_expired:
            self._set_transient("knob.meta.like.signin_expired", tone="error", ms=SIGNIN_META)
            self._feedback("err")
            upnext.armed_toast = "toast.like.signin_expired"
            return
        song = str(row.get("song_id"))
        self.like_inflight.add(song)
        self.request("like", song_id=song, row=row["row"])

    def _like_result(self, effect, result, error):
        song = str(effect.get("song_id"))
        self.like_inflight.discard(song)
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if error is not None:
            if self._discarded(error):
                return
            outcome = getattr(error, "outcome", None) or "failed"
            self._feedback("err")
            if outcome == "not_catalog":
                self._set_transient("knob.meta.like.not_catalog", ms=REASON_META)
                if upnext is not None:
                    changed = [n for n, row in upnext.rows.items() if str(row.get("song_id")) == song]
                    for number in changed:
                        upnext.rows[number]["catalog"] = False
                    if changed:
                        self._present("upnext_rows", t0=self.clock(), reason="data",
                                      **self._upnext_payload(sorted(changed)))
            elif outcome == "signin_expired":
                self.music_signin_expired = True
                self._set_transient("knob.meta.like.signin_expired", tone="error", ms=SIGNIN_META)
                if upnext is not None:
                    upnext.armed_toast = "toast.like.signin_expired"
            elif outcome == "signin_needed":   # never connected: not an expired sign-in (DD-BUG-023)
                self._set_transient("knob.meta.like.signin_needed", tone="error", ms=SIGNIN_META)
                if upnext is not None:
                    upnext.armed_toast = "toast.like.signin_needed"
            else:
                self._set_transient("knob.meta.like.failed", tone="error", ms=LIKE_FAIL_META)
                if getattr(error, "late_check", False) or getattr(error, "confirm_timeout", False):
                    self._schedule(self.clock() + LIKE_LATE_CHECK, "like late check",
                                   lambda s=song: self.request("ratings", ids=[s], purpose="late_check"),
                                   any_screen=True)
            return
        if not (isinstance(result, dict) and result.get("liked") is True):
            return
        self._feedback("ok", moment="like", haptic=False)   # DD-DES-001: the press ticked
        self._set_transient("knob.meta.like.on", ms=FEEDBACK_META)
        self.favourites.loaded_at = None  # Favorite Songs changed: the Favourites cache is stale (CF:15)
        if upnext is not None:
            changed = [n for n, row in upnext.rows.items() if str(row.get("song_id")) == song]
            for number in changed:
                upnext.rows[number]["liked"] = True
            if changed:
                self._present("upnext_rows", t0=self.clock(), reason="likes",
                              **{**self._upnext_payload([]), "rows": [{"row": n, "liked": True} for n in sorted(changed)]})

    def _late_check_result(self, effect, result, error):
        if error is not None or not isinstance(result, dict):
            return
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if upnext is None:
            return
        ids = [str(v) for v in effect.get("ids") or ()]
        changed = []
        for number, row in upnext.rows.items():
            song = str(row.get("song_id") or "")
            if song in ids and result.get(song) == 1 and row.get("liked") is not True:
                row["liked"] = True
                changed.append(number)
        if changed:
            self._present("upnext_rows", t0=self.clock(), reason="data", **self._upnext_payload(sorted(changed)))

    def _shuffle_press(self, now):
        upnext = self.screen.upnext
        P, T = self._position()
        U = max(0, T - P)
        active = self.shuffle_active()
        rev, track = self.state["group_revision"], self.state.get("track_id")
        if not active and U <= COMPANION_SHUFFLE_MAX:
            pn = self._playnext_offsets()
            rest = [offset for offset in range(U) if offset not in pn]
            self.rng.shuffle(rest)
            plan = pn + rest
            expected = [upnext.rows[P + 1 + offset].get("signature") for offset in range(U)]
            request = self.request("shuffle_reorder", on=True, plan=plan, playnext_offsets=pn, expected_rows=expected,
                                   expected_update_id=upnext.revision, expected_group_revision=rev,
                                   expected_track_id=track)
            # The record the adapter persists at acceptance: the base rows (every upcoming row but the
            # Play-next block) in their order now (K3 9.5.2 step 3).
            record = [expected[offset] for offset in range(U) if offset not in pn]
            self.shuffle_job = ShuffleJob(request, True, "companion", plan, pn, t0=now,
                                          record_order=record if all(isinstance(s, str) for s in record) else None)
            order = list(range(1, P + 1)) + [P + 1 + offset for offset in plan]
            self._present_reordered(now, order, "companion")
            upnext.swap_until = now + SHUFFLE_SWAP
            self._schedule(now + SHUFFLE_SWAP, "shuffle", lambda: self._reenter("shuffle", index=min(
                self._upnext_count() - 1, P)))
            return
        if not active:
            request = self.request("set_shuffle", on=True, expected_group_revision=rev)
            self.shuffle_job = ShuffleJob(request, True, "sonos", t0=now)
            return
        if self.sonos_shuffle():
            request = self.request("set_shuffle", on=False, expected_group_revision=rev)
            self.shuffle_job = ShuffleJob(request, False, "sonos", t0=now)
            return
        request = self.request("shuffle_reorder", on=False, playnext_song_ids=self.ledger.playnext_units(),
                               expected_update_id=upnext.revision, expected_group_revision=rev, expected_track_id=track)
        self.shuffle_job = ShuffleJob(request, False, "companion", t0=now)
        order = self._restore_order()
        self._present_reordered(now, order, "off")
        upnext.swap_until = now + SHUFFLE_SWAP
        self._schedule(now + SHUFFLE_SWAP, "shuffle", lambda: self._reenter("shuffle", index=min(
            self._upnext_count() - 1, P)))

    def _note_shuffle_record(self, job):
        """[P3] A companion Shuffle on was accepted: the adapter persisted its restore record."""
        if job.on and job.regime == "companion" and job.record_order:
            self.shuffle_record_order = list(job.record_order)

    def shuffle_record(self, order):
        """[P3] The runtime's read of the persisted restore record at start (K3 9.5.3, 9.5.5): the
        base rows' signature digests in the record's order, or None / [] when there is none. It lets
        the Shuffle-off preview match the restore after a companion restart."""
        if isinstance(order, (list, tuple)) and order and all(isinstance(s, str) and s for s in order):
            self.shuffle_record_order = list(order)
        else:
            self.shuffle_record_order = None

    def _restore_order(self):
        """The shuffle-off target order: Play-next rows first (current order), then the base rows in
        the order they had at Shuffle on, then anything else as it stands.

        [P3] (K3 9.5.3; the phase-2a review's recommended fix) When the restore record is known
        (`shuffle_record_order`, while the state reports `companion_shuffle`), the base rows are
        ranked by it, per signature in queue order as the adapter attributes them (sonos.py
        `_attribute_restore`, step 3), so the preview is the realised order also after a reorder
        without a ledger entry or on a queue the companion did not start (limitations 2 and 3).
        Otherwise by the ledger's start order (the P2a rule)."""
        upnext = self.screen.upnext
        P, T = upnext.P, upnext.T
        upcoming = [n for n in range(P + 1, T + 1) if n in upnext.rows]
        pn = [n for n in upcoming if upnext.rows[n].get("segment") == "playnext"]
        record = self.shuffle_record_order if self.state.get("companion_shuffle") else None
        if record:
            key, pool = "signature", list(record)
        else:
            key, pool = "song_id", list(self.ledger.base.song_ids) if self.ledger.base else []
        size = len(pool)
        ranked = []
        for n in upcoming:
            if n in pn:
                continue
            value = str(upnext.rows[n].get(key) or "")
            if value in pool:
                rank = pool.index(value)
                pool[rank] = None  # each entry once
            else:
                rank = size + n
            ranked.append((rank, n))
        return list(range(1, P + 1)) + pn + [n for _, n in sorted(ranked)]

    def _present_reordered(self, now, order, token):
        upnext = self.screen.upnext
        reordered = {}
        for position, number in enumerate(order, start=1):
            if number in upnext.rows:
                reordered[position] = dict(upnext.rows[number], row=position)
        rows = []
        for position in sorted(reordered):
            entry = _descriptor(reordered[position])
            entry["role"] = self._row_role(position)
            entry["accent"] = self._accent("row", reordered[position])
            rows.append(entry)
        payload = self._upnext_payload([])
        payload.update(rows=rows, focus=min(self._upnext_count() - 1, upnext.P), shuffle=token)
        self._present("upnext_rows", t0=now, reason="shuffle", **payload)

    def _shuffle_result(self, effect, result, error):
        job = self.shuffle_job
        if job is None or job.request != effect["request"]:
            return self._apply_result_state(effect, result, error)
        self.shuffle_job = None
        now = self.clock()
        if error is not None:
            if self._discarded(error):
                return
            outcome = getattr(error, "outcome", None) or "failed"
            self._feedback("err")
            copy_id = "knob.meta.shuffle.queue_changed" if outcome == "queue_changed" else "knob.meta.shuffle.failed"
            self._set_transient(copy_id, tone="error", ms=FAIL_META)
            if self.screen.mode == "upnext":
                self._upnext_requeue()
            return
        self._apply_state_result(dict(result or {}))
        if job.regime == "companion":
            if job.on:
                self._note_shuffle_record(job)
            else:
                self.shuffle_record_order = None      # restored: the adapter deleted the record
            if not job.accepted:
                self._feedback("ok", moment="shuffle", haptic=False)   # DD-DES-001: the press ticked
                self._set_transient("knob.meta.shuffle.on" if job.on else "knob.meta.shuffle.off", ms=FEEDBACK_META)
            self._our_queue_changed()
            return
        # Sonos native regime: confirmed on the verified completion (t1).
        self._feedback("ok", moment="shuffle", haptic=False)   # DD-DES-001: the press ticked
        self._set_transient("knob.meta.shuffle.sonos" if job.on else "knob.meta.shuffle.off", ms=FEEDBACK_META)
        if self.screen.mode != "upnext":
            return
        upnext = self.screen.upnext
        if job.on:
            upnext.card = True
            upnext.regime = "sonos"
            upnext.rows = {n: row for n, row in upnext.rows.items() if n <= upnext.P}
            self._present("upnext_rows", t0=now, reason="shuffle", **self._upnext_payload())
            upnext.swap_until = now + SHUFFLE_SWAP
            self._schedule(now + SHUFFLE_SWAP, "sonos shuffle on",
                           lambda: self._reenter("sonos shuffle on", index=self.screen.upnext.P))
        else:
            upnext.card = False
            upnext.regime = "companion" if upnext.T - upnext.P <= COMPANION_SHUFFLE_MAX else "sonos"
            upnext.pending_regime = "off"
            self._upnext_requeue()

    # ------------------------------------------------------------------ Windows (section 5.7)
    def _window_item(self, index):
        windows = self.screen.windows
        return windows.items[index] if windows and 0 <= index < len(windows.items) else None

    def _window_item_by_id(self, item_id):
        if item_id is None or self.screen.windows is None:
            return None
        for item in self.screen.windows.items:
            if item.get("id") == item_id:
                return item
        return None

    def _windows_open_result(self, effect, result, error):
        if error is not None or not isinstance(result, dict):
            if error is not None and not self._discarded(error):
                self._feedback("err")
                if not self._overlay_open():
                    self.notice = str(error)
            return
        if self.screen.mode != self._root():
            self._present("windows_hide")
            return
        items = [dict(item) for item in result.get("items") or () if isinstance(item, dict)]
        origin = result.get("origin")
        desk_open = None
        if isinstance(origin, dict):
            for item in items:
                if item.get("hwnd") == origin.get("hwnd"):
                    desk_open = item.get("id")
        windows = WindowsState(items=items, origin=origin, desk_open=desk_open)
        index = _clamp(_int(result.get("index"), 0), 0, max(0, len(items) - 1))
        self._new_screen("windows", index, "windows open", windows=windows)

    def _press_windows(self, logical, now):
        windows = self.screen.windows
        if logical == 0:
            self._close_windows("back")
            return
        item = self._window_item(self.screen.index)
        if logical in (1, 2):
            side = "left" if logical == 1 else "right"
            item_id = item.get("id")
            if getattr(windows, side) == item_id:
                return  # C5-11: already holds this side
            windows.snap_busy = SnapJob(item_id, side, now)
            windows.failure = None
            self._present("windows_snap", t0=now, index=self.screen.index, side=side, target_rect=None,
                          place_at_ms=SNAP_PLACE_MS, item=dict(item))
            self._schedule(now + SNAP_RESULT_TIMEOUT, "snap timeout",
                           lambda job=windows.snap_busy: self._snap_timeout(job))
            return
        if logical == 3:
            windows.switch_request = self.request("windows_activate", item=deepcopy(item), index=self.screen.index)

    def _snap_timeout(self, job):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is None or windows.snap_busy is not job:
            return
        _log.warning("No snap result within %d ms: treated as move_rejected", int(SNAP_RESULT_TIMEOUT * 1000))
        self.snap_result(job.side, "move_rejected")

    def snap_result(self, side, outcome):
        """Section 5.7.3: `accepted` assigns the side (half-wash); `ok` resolves; a failure unassigns."""
        if side in (-1, 1):
            side = "left" if side == -1 else "right"
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is None or windows.snap_busy is None or windows.snap_busy.side != side:
            return
        job = windows.snap_busy
        now = self.clock()
        item = self._window_item_by_id(job.item_id) or {}
        app = item.get("label_app") or item.get("app", "")
        if outcome == "accepted":
            if job.accepted:
                return
            job.accepted = True
            other = "right" if side == "left" else "left"
            if getattr(windows, other) == job.item_id:
                setattr(windows, other, None)
            setattr(windows, side, job.item_id)
            windows.last_side = side
            self._feedback("ok", moment="snap", side=-1 if side == "left" else 1, color=self._accent("window", item))
            if windows.left and windows.right:
                self._schedule(job.t0 + SNAP_PAIR_CLOSE, "snap pair close", self._close_pair)
            elif self._last_detent < job.t0:
                self._schedule(job.t0 + SNAP_ADVANCE, "snap advance", lambda j=job: self._snap_advance(j))
            return
        if outcome == "ok":
            windows.snap_busy = None
            self._run_latched()
            return
        # a failure: a pre-check (`hung`, `move_rejected`) or the placement (`move_rejected`, `cant_fit`)
        if job.accepted and getattr(windows, side) == job.item_id:
            setattr(windows, side, None)
            self.due = [entry for entry in self.due if entry[1] not in ("snap pair close", "snap advance")]
        windows.snap_busy = None
        windows.failure = {"side": side, "reason": outcome, "until": now + FAIL_META}
        self._feedback("err")
        copy_id = {"hung": "knob.meta.snap.hung", "cant_fit": "knob.meta.snap.fit"}.get(outcome, "knob.meta.snap.move")
        self._set_transient(copy_id, tone="error", ms=FAIL_META, App=app)
        self._run_latched()

    def _run_latched(self):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is not None and windows.latched_close and windows.snap_busy is None:
            reason, windows.latched_close = windows.latched_close, None
            self._close_windows(reason)

    def _snap_advance(self, job):
        windows = self.screen.windows
        if self.screen.mode != "windows" or self._last_detent >= job.t0:
            return  # C5-10: a detent since t0 cancels the advance
        items = windows.items
        start = next((i for i, item in enumerate(items) if item.get("id") == job.item_id), None)
        if start is None:
            return
        for step in range(1, len(items)):
            candidate = items[(start + step) % len(items)]
            if candidate.get("id") in (windows.left, windows.right) or not candidate.get("available", True):
                continue
            index = (start + step) % len(items)
            self._reenter("snap advance", index=index)
            self._present("windows_highlight", index=index, control_id=self.control_id, bump=0)
            return

    def _close_pair(self):
        windows = self.screen.windows
        if self.screen.mode != "windows" or not (windows.left and windows.right):
            return
        now = self.clock()
        left, right = windows.left, windows.right
        a, b = self._window_app(left), self._window_app(right)
        self._present("windows_close_pair", left=left, right=right, focus=windows.last_side)
        self._cancel_pending = None
        self._new_screen(self._root(), self.display_volume, "snap pair")
        self._exit_toast("toast.snap.pair", now, A=a, B=b)

    def _activate_result(self, effect, result, error):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is not None and windows.switch_request == effect["request"]:
            windows.switch_request = None
        if windows is None:
            return
        if error is None and result:
            item = effect.get("item") or {}
            now = self.clock()
            self._feedback("ok")
            self._new_screen(self._root(), self.display_volume, "switch")
            app = item.get("label_app") or item.get("app", "")
            if self.spaces:
                # README 6 `Switched to {app}` on the Home status line (the picker has closed).
                self._set_transient("knob.status.switched", tone="success", ms=R3_REFUSED_META,
                                    text=fit_copy("knob.status.switched", LINE_R3, App=app))
            self._exit_toast("toast.switch", now, App=app, Title=item.get("title", ""))
            return
        if error is not None and self._discarded(error):
            return
        self._feedback("err")
        self._set_transient("knob.meta.windows.no_focus", tone="error", ms=FAIL_META)
        if effect.get("index") is not None and effect["index"] != self.screen.index:
            self._present("windows_highlight", index=self.screen.index, control_id=self.control_id, bump=0)

    # ------------------------------------------------------------------ tick (section 7)
    def tick(self):
        now = self.clock()
        self._run_due(now)
        self._run_toasts(now)
        if (self.state["online"] and self.desired_volume is not None and self.volume_request is None
                and now >= self.volume_due and self.screen.mode != "onshape" and not self.onshape_pending):
            self.volume_request = self.request("volume", value=self.desired_volume,
                                               expected_group_revision=self.state["group_revision"])
            self.last_volume_write = now
        interval = STATE_POLL_BUSY if self._exclusive_running() else STATE_POLL
        if (now - self.last_poll >= interval and not self.command_request and not self.volume_request
                and not any(e["kind"] == "state" for e in self.pending.values())):
            self.last_poll = now
            self.request("state")
        self._seek_tick(now)
        self._preresolve(now)
        if self.spaces:
            self._lights_tick(now)
        self._run_passive(now)
        if self.screen.mode in ("recent", "explorer"):
            self._recent_prefetch()
        if self.screen.mode == "explorer" or self._shown_source() == "favourites":
            self._favourites_ensure(now)
        if self.screen.mode == "tracks":
            self._tracks_fetch()
        if self.screen.mode in ("explorer", "upnext", "windows") and now - self.last_knob_input >= OVERLAY_IDLE:
            self.close_overlay("idle")

    # ------------------------------------------------------------------ state (section 9.1)
    def _state(self, state, previous_position=None, volume_response=False, enter=True):
        """Apply a Sonos state. Returns whether Home needs a fresh entry (new bounds)."""
        old_group = self.state.get("group_revision")
        group_changed = bool(old_group and state.get("group_revision") and state.get("group_revision") != old_group)
        previous = self.display_volume if previous_position is None else previous_position
        was_online = self.state["online"]
        was_track = self.state.get("track_id")
        was_revision = str(self.state.get("queue_revision", ""))
        was_position = self.state.get("playlist_position")
        confirmed_before = self.state["volume"]
        self.state.update(state)
        if "companion_shuffle" in state and not state["companion_shuffle"]:
            self.shuffle_record_order = None   # [P3] the adapter reports no restore record any more
        self.state_known = True
        self._state_at = self.clock()
        if self.state["online"] and self.state.get("playback") == "PLAYING":
            self._album_start_until = 0.0
        if group_changed or not self.state["online"]:
            self._volume_reveal_until = 0.0
            self._volume_reveal_source = ""
            self._external_until = 0.0
        elif (was_online and not volume_response and self.desired_volume is None
              and self.volume_request is None and confirmed_before != self.state["volume"]):
            self._reveal_volume(EXTERNAL_REVEAL_SECONDS, "external")
            self._external_until = self.clock() + EXTERNAL_SECONDS
        if group_changed:
            self.desired_volume = None
        reenter = self.screen.mode in VOLUME_MODES and (
            group_changed or (self.desired_volume is None and previous != self.display_volume))
        if not self.state["online"]:
            self.desired_volume = None
        # K3 section 5: lifetime and mode consequences of the new state.
        mode = self.screen.mode
        if group_changed and mode in ("explorer", "upnext"):
            self.close_overlay("group")
            reenter = False
        elif mode == "seek" and (group_changed or (was_track and self.state.get("track_id") != was_track)):
            self._leave_seek(flush=False, drop=True)
            self._enter_tracks(1, "seek track changed")
            reenter = False
        elif mode == "upnext" and self.state["online"]:
            self._upnext_changes(was_revision, was_position)
        elif mode == "tracks":
            self._neighbours_read()
            self._tracks_state_changed(was_position)
        if group_changed and self.state["online"]:
            self._group_changed_copy()
        if reenter and enter:
            self._enter("volume")
        return reenter

    def _group_changed_copy(self):
        """The `Group changed` Home condition (section 15.2; r2.2 `Speaker group changed`), on the
        current copy line (Home `status`, else its `meta` twin, C5-56), for `group_changed_ms`
        (C5-76) in the `error` tone (lead ruling R-j, K3 E-j: was `meta`)."""
        self._set_transient("knob.status.group_changed", tone="error", ms=START_FAIL_STATUS)

    def _apply_state_result(self, result):
        result = dict(result or {})
        for key in [k for k in result if k.startswith("_")]:
            result.pop(key)
        if result:
            self._state(result)

    def _apply_result_state(self, effect, result, error):
        if error is None and isinstance(result, dict):
            self._apply_state_result(result)

    @staticmethod
    def _discarded(error):
        return getattr(error, "outcome", None) == "discarded" or "discarded" in str(error).lower()

    def _obsolete_group(self, effect, result):
        expected = effect.get("expected_group_revision")
        return bool(expected is not None and expected != self.state.get("group_revision")
                    and isinstance(result, dict) and result.get("group_revision") == expected)

    # ------------------------------------------------------------------ completions (sections 8, 9)
    def complete(self, request, result=None, error=None):
        effect = self.pending.pop(request, None)
        if not effect:
            return
        kind = effect["kind"]
        if kind == "state":
            if error is not None:
                self.state["online"] = False
                self.state_known = True
                self.desired_volume = None
                self._external_until = 0.0
                return
            self._state(dict(result or {}))
            return
        if kind == "volume":
            return self._volume_result(effect, result, error)
        if kind == "transport":
            return self._transport_result(effect, result, error)
        if kind in ("play_items", "jump"):
            return self._start_result(effect, result, error)
        if kind in ("play_next", "move_next"):
            return self._playnext_result(effect, result, error)
        if kind == "seek":
            return self._seek_result(effect, result, error)
        if kind in ("shuffle_reorder", "set_shuffle"):
            return self._shuffle_result(effect, result, error)
        if kind == "queue_window":
            return self._window_result(effect, result, error)
        if kind in ("catalog_songs", "ratings"):
            return self._enrich_result(effect, result, error)
        if kind == "like":
            return self._like_result(effect, result, error)
        if kind in ("recent", "recent_lookahead"):
            return self._recent_result(effect, result, error)
        if kind == "favourite_playlists":
            return self._favourites_result(effect, result, error)
        if kind == "playlist_meta":
            return self._meta_result(effect, result, error)
        if kind == "windows_open":
            return self._windows_open_result(effect, result, error)
        if kind == "windows_activate":
            return self._activate_result(effect, result, error)
        if kind == "lights_read":
            if error is None:
                self.lights_state(result)
            else:
                self.lights_state({"configured": self.lights.configured, "online": False,
                                   "reason": getattr(error, "outcome", None) or "offline",
                                   "scenes": self.lights.scenes})
            return
        if kind == "lights_set":
            return self._lights_set_result(effect, result, error)
        if kind == "lights_power":
            return self._lights_power_result(effect, result, error)
        if kind == "scene_run":
            return self._scene_run_result(effect, result, error)

    def _volume_result(self, effect, result, error):
        self.volume_request = None
        obsolete_group = effect.get("expected_group_revision") != self.state.get("group_revision")
        if error is not None:
            if self._discarded(error):
                return
            self.last_poll = -10
            if obsolete_group:
                return  # a write to the old group finishes quietly (CT:813-814, section 10.2)
            self.desired_volume = None
            self._feedback("err")
            if getattr(error, "outcome", None) == "group_changed":
                self._group_changed_copy()
            if not self._overlay_open():
                self.notice = str(error)
            if self.screen.mode in VOLUME_MODES:
                self._enter("volume")
            return
        result = dict(result or {})
        if obsolete_group and result.get("group_revision") == effect.get("expected_group_revision"):
            return
        previous_position = self.display_volume
        applied = result.pop("_applied_volume", effect.get("value"))
        if self.desired_volume == applied:
            self.desired_volume = None
        reenter = self._state(result, previous_position=previous_position, volume_response=True, enter=False)
        if reenter:
            self._enter("volume")

    # ------------------------------------------------------------------ frames
    def frame(self, assume_ready=False):
        """Presentation projection, decorated by the injected presentation hook. assume_ready=True
        is the post-ready projection embedded in control()."""
        frame = self._frame(assume_ready)
        if not assume_ready and self._started_seq is not None:
            # K2 M16: only the first frame carrying the `started` moment omits `playing`.
            self._started_seq = None
        decorate = self.decorate
        if decorate is None:
            return frame
        try:
            if assume_ready:
                frame["_entry"] = True
            decorated = decorate(deepcopy(frame))
            if not isinstance(decorated, dict):
                raise TypeError("Presentation decorator must return a frame")
            decorated.pop("_entry", None)
            return _clean_frame(decorated)
        except Exception:
            if not self._decorate_failed:
                self._decorate_failed = True
                _log.exception("Presentation decorator failed; using the undecorated frame")
            frame.pop("_entry", None)
            return frame

    def _frame(self, assume_ready=False):
        ready = self.ready or assume_ready
        mode = self.screen.mode
        specs = self._buttons()
        buttons = []
        for spec in specs:
            button = {"label": spec["label"], "enabled": spec["code"] is None, "icon": spec["icon"]}
            if spec["lit"]:
                button["lit"] = spec["lit"]
                if spec["lit"] == "on" and spec["color"]:
                    button["color"] = spec["color"]
            buttons.append(button)
        frame = {"mode": MODE_TITLES[mode], "target": self._target(), "value": "", "detail": "",
                 "status": "", "title": "", "subtitle": "", "counter": "", "activity": "idle",
                 "buttons": buttons, "ring": {"style": "off", "value": 0, "index": 0, "count": 0},
                 "layout": mode, "heading": "", "meta": "", "titleTone": "ink", "metaTone": "meta",
                 "statusTone": "meta"}
        getattr(self, "_frame_" + mode)(frame, ready)
        if self.spaces:
            crumb = self._crumb(mode)
            if crumb:
                frame["crumb"] = crumb
            if self.hold_action():
                frame["holdMarker"] = True   # r3.1: hold 4 exists here (the knob's hold tick and ring)
        if not ready and self.hardware and mode in VOLUME_MODES:
            frame["status"], frame["activity"] = COPY["knob.status.connecting"], "loading"
        frame["value"] = frame["value"] or frame["title"]
        frame["detail"] = frame["detail"] or frame["subtitle"]
        frame["reducedMotion"] = self.reduced_motion
        if self.feedback:
            frame["feedback"] = dict(self.feedback)
        if self.haptic:
            frame["haptic"] = dict(self.haptic)   # r4: device.py keeps it only for a hapticFx knob
        return _clean_frame(frame)

    def _crumb(self, mode):
        """r3 (presentation 6): the arc breadcrumb token of `mode` (README 2.1), '' on the launcher."""
        if mode == "explorer":
            explorer = self.screen.explorer
            return "onScreenPlaylists" if explorer is not None and explorer.source == "favourites" else "onScreenRecent"
        if mode == "recent" and self._recent_source() == "favourites":
            return "playlists"   # r3.1: MUSIC › PLAYLISTS
        return CRUMBS.get(mode, "")

    def queue_titles(self, rows):
        """Read-only (the Navigator's Tracks card): {row: title} for the queue rows asked (1-based,
        e.g. P-2..P+2, wrapped by the caller), from the Tracks neighbour reads and the Up next rows
        already loaded, plus the playing song; a row not known yet is absent. Requests nothing."""
        known = {}
        P, _T = self._position()
        key = (self.state.get("queue_revision"), P)
        known.update(self._neighbours.get(key, {}))
        if self._tracks_revision == str(self.state.get("queue_revision", "")):
            for row, entry in self._tracks_rows.items():
                if isinstance(entry, dict) and entry.get("title"):
                    known.setdefault(row, entry["title"])
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if upnext is not None:
            for row, entry in upnext.rows.items():
                if isinstance(entry, dict) and entry.get("title"):
                    known.setdefault(row, entry["title"])
        if P and self.state.get("title"):
            known[P] = self.state.get("title")
        return {row: known[row] for row in (rows or ()) if type(row) is int and known.get(row)}

    def _target(self):
        if self.screen.mode == "windows":
            return "DESKTOP"
        if self.screen.mode == "onshape":
            return app_display_name(self.app_profile) if self.app_profile is not None else "Onshape"
        room_count = self.state.get("group_room_count", 1)
        if isinstance(room_count, int) and room_count > 1:
            return f"{self.state.get('room_label', 'Speaker')} + {room_count - 1} room{'s' if room_count > 2 else ''}"
        return self.state.get("group_label", "Speaker")

    def _selection_ring(self, index, count, entries, kind, unavailable=None):
        """A v5 selection ring: `first` by VOC-R03, colours of the window, the unavailable mask."""
        if count <= 0:
            return {"style": "off", "value": 0, "index": 0, "count": 0}
        index = _clamp(index, 0, count - 1)
        first = window_first_v5(index, count)
        window = min(RING_WINDOW, count - first)
        colors, mask = [], 0
        for k in range(window):
            entry = entries(first + k)
            colors.append(self._accent(kind, entry) if entry is not None else 0)
            if unavailable is not None and entry is not None and unavailable(entry):
                mask |= 1 << k
        ring = {"style": "selection", "value": 0, "index": index, "count": count, "first": first, "colors": colors}
        if mask:
            ring["unavailable"] = mask
        return ring

    # Home ------------------------------------------------------------------------------------------------
    def _frame_home(self, frame, ready):
        now = self.clock()
        online = self.state["online"]
        layout = self._home_layout(ready)
        title = self.state.get("title") or ""
        frame["title"] = title or COPY["knob.caption.nothing_playing"]
        frame["subtitle"] = self.state.get("artist", "") if title else ""
        frame["value"] = f"{self.display_volume}%" if online else "--"
        frame["detail"] = self.state.get("title") or "Nothing playing"
        status, tone = self._home_status(layout, now)
        activity = "idle"
        if (self.start is not None or self.desired_volume is not None or self._home_command() is not None
                or self.play_next_job is not None or self.shuffle_job is not None or self.move_next_request is not None):
            activity = "pending"
        if layout == "notice":
            if not self.state_known:
                frame.update(title=COPY["knob.title.looking_for_sonos"], subtitle="", status="", activity="idle")
                frame["ring"] = {"style": "off", "value": self.display_volume, "index": 0, "count": 101}
            else:
                frame.update(title=COPY["knob.title.sonos_unavailable"], subtitle=COPY["knob.sub.looking_for_sonos"],
                             meta=COPY["knob.meta.windows_still_works"], status=COPY["knob.status.sonos_unavailable"],
                             activity="offline")
                frame["ring"] = {"style": "level", "value": self.display_volume, "index": 0, "count": 101}
            frame["layout"] = "notice"
        else:
            frame.update(status=status, statusTone=tone, activity=activity, layout=layout)
            frame["ring"] = {"style": "level", "value": self.display_volume, "index": 0, "count": 101,
                             "external": now < self._external_until}
        rest = self._home_layout(ready, reveal=False)
        frame["restLayout"] = "idle" if rest == "idle" else "nowPlaying"
        frame["volumeVisible"] = frame["layout"] == "volume"
        caption = self.state.get("title") or (COPY["knob.caption.now_playing"] if self.has_media()
                                              else COPY["knob.caption.nothing_playing"])
        command = self._home_command() or {}
        if self.state.get("playback") == "PAUSED_PLAYBACK" and command.get("direction") != "play":
            caption = copy_text("knob.caption.volume_paused", title=caption)
        frame["volumeCaption"] = caption
        frame["confirmedVolume"] = self.state["volume"]
        if self.spaces and self.screen.mode == "home":
            frame["heading"] = COPY["knob.heading.music"]   # r3: the Music space (the launcher has none)
        playing = self.confirmed_playing()
        started_frame = (self._started_seq is not None and self.feedback is not None
                         and self.feedback.get("seq") == self._started_seq)
        if playing is not None and not started_frame:
            frame["playing"] = playing

    def _home_status(self, layout, now):
        """Section 2.4 Home precedence: Starting… > transient > reveal > transport pending > Paused."""
        if self.start is not None:
            return COPY["knob.status.starting"], "meta"
        transient = self._transient()
        if transient is not None:
            tones = ("meta", "secondary", "error", "warm") if self.spaces else ("meta", "secondary", "error")
            return transient.text, transient.tone if transient.tone in tones else "meta"
        if layout == "volume":
            volume = self.display_volume
            if self.desired_volume is not None:
                return COPY["knob.status.setting"], "meta"
            if self._volume_reveal_source == "external":
                return COPY["knob.status.changed_elsewhere"], "secondary"
            if volume == 0:
                return COPY["knob.status.minimum"], "secondary" if self.state.get("playback") != "PLAYING" else "meta"
            if volume == 100:
                return COPY["knob.status.maximum"], "secondary" if self.state.get("playback") != "PLAYING" else "meta"
            return "", "meta"
        command = self._home_command()
        if command is not None:
            return (COPY["knob.status.starting"] if command.get("direction") == "play" else COPY["knob.status.pausing"]), "meta"
        if layout == "idle":
            return "", "meta"
        if self.state.get("playback") == "PAUSED_PLAYBACK":
            return COPY["knob.status.paused"], "secondary"
        return "", "meta"

    # Recent ----------------------------------------------------------------------------------------------
    def _list_meta(self, lst_count, index, complete):
        if complete and lst_count and index == lst_count - 1:
            return copy_text("knob.meta.position_end", n=lst_count)
        return copy_text("knob.meta.position", i=index + 1, n=lst_count)

    def _playnext_meta(self):
        job = self.play_next_job
        if job is None:
            return None
        if job.phase == "resolving" or job.k < 1 or not job.n:
            return COPY["knob.meta.playnext.resolving"]
        return copy_text("knob.meta.playnext.progress", k=job.k, n=job.n)

    def _frame_list_recent(self, frame, index, *, explorer=False):
        lst = self.recent
        frame["page"] = 0
        frame["heading"] = COPY["knob.heading.explorer_recent" if explorer else "knob.heading.recent"]
        if lst.state == "loading":
            frame.update(meta=COPY["knob.meta.loading"], activity="loading")
            return
        if lst.state == "empty":
            frame.update(title=COPY["knob.title.recent_empty"], subtitle=COPY["knob.sub.recent_empty"])
            return
        if lst.state in ("signin", "error"):
            signin = self._signin_code() if lst.state == "signin" else None
            frame.update(title=COPY["knob.title." + signin if signin else "knob.title.library_error"],
                         subtitle=COPY["knob.sub." + signin if signin else "knob.sub.library_error"],
                         meta=COPY["knob.meta.windows_still_works"], metaTone="secondary", activity="error")
            return
        total = lst.count()
        index = _clamp(index, 0, max(0, total - 1))
        item = lst.item(index)
        pending = self.play_next_job is not None
        frame["activity"] = "pending" if pending else "idle"
        progress = None if explorer else self._playnext_meta()
        transient = self._transient()
        if item is None:
            frame["meta"] = COPY["knob.meta.loading"]
        else:
            frame["title"] = item.get("title", "")
            frame["subtitle"] = item.get("artist") or KIND_LABELS.get(item.get("kind"), "")
            if self.spaces and not explorer and item.get("artist"):
                # r3.1: the artist is on the `{i} / {n} · {artist}` line; the subtitle names the kind
                # (and the year when known) instead of repeating it.
                year = item.get("year") or item.get("release_year")
                kind = KIND_LABELS.get(item.get("kind"), "Album")
                frame["subtitle"] = f"{kind} · {year}" if year else kind
            if item.get("available") is False:
                frame["titleTone"] = "muted"
                frame["artDim"] = True
            frame["meta"] = self._list_meta(total, index, lst.complete)
            if self.spaces and not explorer and item.get("artist"):
                # r3.1 design: `{i} / {n} · {artist}`.
                frame["meta"] = fit_copy("knob.meta.list.position_artist", LINE_R3, i=index + 1, n=total,
                                         artist=item.get("artist"))
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        if progress is not None:
            frame["meta"], frame["metaTone"] = progress, "meta"
        frame["ring"] = self._selection_ring(index, total, lst.item, "recent",
                                             unavailable=lambda entry: entry.get("available") is False)

    def _frame_recent(self, frame, ready):
        if self._recent_source() == "favourites":
            self._frame_list_favourites(frame, self.screen.index)   # r3.1: MUSIC › PLAYLISTS
            return
        self._frame_list_recent(frame, self.screen.index)

    # Explorer --------------------------------------------------------------------------------------------
    def _frame_explorer(self, frame, ready):
        explorer = self.screen.explorer
        source = explorer.source
        frame["layout"] = "explorer"
        if source == "recent":
            self._frame_list_recent(frame, self.screen.index, explorer=True)
            frame["page"] = 0
            return
        self._frame_list_favourites(frame, self.screen.index, explorer=True)

    def _frame_list_favourites(self, frame, index, *, explorer=False):
        """Favourite playlists: the explorer's Favourites tab (page 1) or r3.1's knob list (page 0,
        heading PLAYLISTS, the Play next progress on its meta line)."""
        frame["page"] = 1 if explorer else 0
        frame["heading"] = COPY["knob.heading.explorer_favourites" if explorer else "knob.heading.playlists"]
        fav = self.favourites
        state = self._source_state("favourites")
        if state == "loading":
            frame.update(meta=COPY["knob.meta.loading"], activity="loading")
            return
        if state == "empty":
            frame.update(title=COPY["knob.title.favourites_empty"], subtitle=COPY["knob.sub.favourites_empty"])
            return
        if state == "signin":
            code = self._signin_code("favourites")
            frame.update(title=COPY["knob.title." + code], subtitle=COPY["knob.sub." + code])
            return
        total = fav.count()
        index = _clamp(index, 0, max(0, total - 1))
        item = fav.items[index] if index < len(fav.items) else None
        if item is None:
            frame["meta"] = COPY["knob.meta.loading"]
        else:
            meta = fav.meta.get(_item_id(item)) or {}
            frame["title"] = item.get("title") or COPY["overlay.explorer.untitled"]
            count = meta.get("count")
            if isinstance(count, int):
                frame["subtitle"] = "1 song" if count == 1 else copy_text("knob.sub.playlist_count", n=count)
            if meta.get("empty"):
                frame["titleTone"] = "muted"
                frame["artDim"] = True
            frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=total)
            if self.spaces and not explorer:
                # r3.1 design: `Favourite playlist`, `{i} / {n} · {count} songs`.
                frame["subtitle"] = COPY["knob.sub.favourite_playlist"]
                if isinstance(count, int):
                    frame["meta"] = copy_text("knob.meta.list.position_songs", i=index + 1, n=total, count=count)
        transient = self._transient()
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        progress = None if explorer else self._playnext_meta()
        if progress is not None:
            frame["meta"], frame["metaTone"] = progress, "meta"
        frame["activity"] = "pending" if self.play_next_job is not None else "idle"
        frame["ring"] = self._selection_ring(index, total, lambda j: fav.items[j] if j < len(fav.items) else None,
                                             "playlist",
                                             unavailable=lambda entry: bool((fav.meta.get(_item_id(entry)) or {}).get("empty")))

    # Tracks ----------------------------------------------------------------------------------------------
    def _neighbour(self, row):
        P, _ = self._position()
        entry = self._neighbours.get((self.state.get("queue_revision"), P)) or {}
        return entry.get(row)

    def _frame_tracks_queue(self, frame):
        """r3.1 whole-queue Tracks: the focused row, `Turn to browse the queue` on the playing row,
        elsewhere `Skip to` / `Back to` · {n} / {T} and `Press 4 to play`; a selection ring."""
        P, T = self._position()
        index = _clamp(self.screen.index, 0, T - 1)
        number = index + 1
        row = self._tracks_rows.get(number) or {}
        tone = "meta"
        if number == P:
            frame["title"] = self.state.get("title") or row.get("title") or COPY["knob.caption.nothing_playing"]
            frame["subtitle"] = self.state.get("artist") or row.get("artist") or ""
            meta = COPY["knob.meta.tracks.browse"]
        else:
            # r3.1 design: the focused song / artist and `Skip to {n} / {T} · 4 plays` in green.
            frame["title"] = row.get("title") or copy_text("knob.title.tracks.row", n=number)
            frame["subtitle"] = row.get("artist") or ""
            meta = copy_text("knob.meta.tracks.skip_to" if number > P else "knob.meta.tracks.back_to", n=number, T=T)
            tone = "success"
        jumping = self.start is not None and self.start.source == "tracks"
        if jumping:
            meta, tone = COPY["knob.meta.tracks.skipping"], "meta"
        transient = self._transient()
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        else:
            frame["meta"], frame["metaTone"] = meta, tone
        frame["activity"] = "pending" if jumping else "idle"
        # r3.1 (19.10): the `queue` ring, the focus among the T rows with the playing row as `now`.
        ring = self._selection_ring(index, T, lambda j: self._tracks_rows.get(j + 1), "row")
        ring.pop("unavailable", None)
        ring.update(style="queue", now=_clamp(P - 1, -1, T - 1))
        frame["ring"] = ring

    def _frame_tracks(self, frame, ready):
        index = _clamp(self.screen.index, 0, 2)
        frame["heading"] = COPY["knob.heading.tracks"]
        if self._tracks_queue():
            self._frame_tracks_queue(frame)
            return
        title = self.state.get("title") or ""
        queue = self.source() == "queue"
        P, T = self._position()
        now_line = fit_copy("knob.line.tracks.now", LINE_14, title=title) if title else COPY["knob.caption.nothing_playing"]
        skip = self._skip_command()
        transient = self._transient()
        if self.spaces:
            # README 2.2 Tracks: at rest the current song / artist / `Turn for previous or next`;
            # turned `Previous` / `Next`, `Now: {song}`, `Press 4 to skip`.
            if index == 1:
                frame["title"] = title or COPY["knob.caption.nothing_playing"]
                frame["subtitle"] = self.state.get("artist") or ""
                meta = COPY["knob.meta.tracks.turn"]
            else:
                frame["title"] = COPY["knob.title.tracks.next_r3" if index == 2 else "knob.title.tracks.prev_r3"]
                frame["subtitle"] = now_line
                meta = COPY["knob.meta.tracks.hint"]
        elif index == 1:
            frame["title"] = COPY["knob.title.tracks.choose"]
            frame["subtitle"] = now_line
            if queue and T:
                meta = copy_text("knob.meta.tracks.position_shuffle" if self.shuffle_active() else "knob.meta.position",
                                 i=P, n=T)
            else:
                meta = ""
        else:
            frame["title"] = COPY["knob.title.tracks.next" if index == 2 else "knob.title.tracks.prev"]
            meta = COPY["knob.meta.tracks.hint"]
            if not queue:
                frame["subtitle"] = now_line
            elif self.sonos_shuffle():
                frame["subtitle"] = COPY["knob.line.tracks.next_shuffle" if index == 2 else "knob.line.tracks.prev_shuffle"]
            elif index == 2:
                if P < T:
                    neighbour = self._neighbour(P + 1)
                    frame["subtitle"] = fit_copy("knob.line.tracks.next", LINE_14, title=neighbour) if neighbour \
                        else COPY["knob.title.tracks.next"]
                else:
                    frame["subtitle"] = COPY["knob.line.tracks.end"]   # r4: no wrap (was "Next: back to track 1")
            else:
                if P > 1:
                    neighbour = self._neighbour(P - 1)
                    frame["subtitle"] = fit_copy("knob.line.tracks.prev", LINE_14, title=neighbour) if neighbour \
                        else COPY["knob.title.tracks.prev"]
                else:
                    frame["subtitle"] = COPY["knob.line.tracks.start"]   # r4: no wrap to the last track
        if skip is not None:
            meta = COPY["knob.meta.tracks.skipping"]
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        else:
            frame["meta"] = meta
        frame["activity"] = "pending" if skip is not None else "idle"
        can_previous, can_next = bool(self.state.get("can_previous")), bool(self.state.get("can_next"))
        frame["ring"] = {"style": "transport", "value": 0, "index": index, "count": 3,
                         "unavailable": (0 if can_previous else 1) | (0 if can_next else 4)}
        frame["value"] = ("Previous", "Neutral", "Next")[index]

    # Seek ------------------------------------------------------------------------------------------------
    def _frame_seek(self, frame, ready):
        seek = self.screen.seek
        now = self.clock()
        frame["heading"] = COPY["knob.heading.tracks" if self.spaces else "knob.heading.seek"]
        frame["title"] = self.state.get("title") or ""
        target = _clamp(seek.target_s, 0, max(0, seek.D - 1))
        frame["ring"] = {"style": "lap", "value": 0, "index": target, "count": _clamp(seek.D, 1, SEEK_MAX_DURATION_S)}
        transient = self._transient()
        if seek.busy:
            frame["meta"] = COPY["knob.line.seek.jumping"]
        elif now < seek.fail_until:
            frame["meta"], frame["metaTone"] = COPY["knob.line.seek.failed"], "error"
        elif transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        elif now < seek.limit_until:
            frame["meta"] = COPY["knob.line.seek.limit"]
        elif self.spaces:
            # README 2.2: `of {dur} · 3 sets · 1 cancels` in #FFBE69.
            frame["meta"], frame["metaTone"] = copy_text("knob.line.seek.r3", **{"m:ss": mmss(seek.D)}), "warm"
        else:
            frame["meta"] = copy_text("knob.line.seek.length", **{"m:ss": mmss(seek.D)})
        frame["activity"] = "pending" if seek.busy else "idle"
        frame["value"] = mmss(target)

    # Up next ---------------------------------------------------------------------------------------------
    def _frame_upnext(self, frame, ready):
        upnext = self.screen.upnext
        frame["heading"] = COPY["knob.heading.upnext"]
        count_all = self._upnext_count()
        index = _clamp(self.screen.index, 0, max(0, count_all - 1))
        pending = self.shuffle_job is not None or bool(self.like_inflight)
        if upnext.loading:
            frame.update(meta=COPY["knob.meta.upnext.loading"], activity="loading")
            frame["ring"] = {"style": "off", "value": 0, "index": 0, "count": 0}
            return
        frame["activity"] = "pending" if pending else "idle"
        transient = self._transient()
        if upnext.card and index == upnext.P:
            frame["title"] = COPY["knob.title.upnext_sonos_card"]
            frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=count_all)
        else:
            row = upnext.rows.get(index + 1)
            if row is None:
                frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=count_all)
            else:
                frame["title"] = row.get("title", "")
                frame["subtitle"] = row.get("artist", "")
                if index + 1 == upnext.P:
                    frame["meta"] = copy_text("knob.meta.upnext.position_playing", i=index + 1, n=count_all)
                else:
                    frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=count_all)
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        ring = self._selection_ring(index, count_all,
                                    lambda j: None if (upnext.card and j == upnext.P) else upnext.rows.get(j + 1),
                                    "row")
        ring.pop("unavailable", None)   # Up next frames never set `unavailable` (C5-61)
        ring["now"] = upnext.P - 1
        if self.spaces and ring.get("style") == "selection":
            ring["style"] = "queue"   # r3.1 (19.10): Up next shares the Tracks queue ring (no Sonos card mark)
        elif upnext.card:
            ring["card"] = True
        frame["ring"] = ring

    # Windows ---------------------------------------------------------------------------------------------
    def _frame_windows(self, frame, ready):
        windows = self.screen.windows
        items = windows.items
        frame["layout"] = "windows"
        if not items:
            frame["title"] = COPY["knob.title.no_windows"]
            return
        index = _clamp(self.screen.index, 0, len(items) - 1)
        item = items[index]
        frame["title"] = item.get("title", "")
        app = item.get("label_app") or item.get("app", "")
        frame["subtitle"] = app
        transient = self._transient()
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        elif self.spaces and windows.left and not windows.right:
            frame["meta"], frame["metaTone"] = COPY["knob.meta.snap.left"], "success"   # README 6
        elif self.spaces and windows.right and not windows.left:
            frame["meta"], frame["metaTone"] = COPY["knob.meta.snap.right"], "success"
        elif windows.left and not windows.right:
            frame["meta"] = fit_copy("knob.meta.snap.left_set", LINE_META, App=self._window_app(windows.left))
        elif windows.right and not windows.left:
            frame["meta"] = fit_copy("knob.meta.snap.right_set", LINE_META, App=self._window_app(windows.right))
        elif windows.switch_request is not None:
            frame["meta"] = COPY["knob.meta.windows.switching"]
        elif not item.get("available", True):
            frame["meta"] = COPY["knob.meta.windows.closed"]
        elif self.spaces:
            frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=len(items))   # README 2.2 `{i} / {n}`
        if not item.get("available", True):
            frame["titleTone"] = "muted"
        frame["activity"] = "pending" if windows.switch_request is not None else "idle"
        if self.spaces:
            # README 3: a white marker at the window's position on the arc, the rest warm L 0.1.
            frame["ring"] = {"style": "marker", "value": 0, "index": index, "count": len(items)}
            return
        frame["ring"] = self._selection_ring(index, len(items), lambda j: items[j] if j < len(items) else None,
                                             "window", unavailable=lambda entry: not entry.get("available", True))

    # Launcher (r3 Home) --------------------------------------------------------------------------------
    def _frame_launcher(self, frame, ready):
        """The r2.2 Home screens (nowPlaying / volume / idle / notice) with the launcher's buttons;
        r3.1: in the lights domain (hold 4) the Lights frames (heading LIGHTS, the area's level)."""
        if self._lights_domain():
            self._frame_lights(frame, ready)
            return
        self._frame_home(frame, ready)

    # Lights (r3) -----------------------------------------------------------------------------------------
    def _lights_title(self):
        """The scene Desk Dial ran while nothing was adjusted after it; otherwise (r3.1 design: an
        adjustment returns the title to the area) the area's name, else `Lights`."""
        lights = self.lights
        if lights.scene_label and not lights.adjusted:
            return lights.scene_label
        return lights.name or COPY["knob.title.lights_default"]

    def _lights_level(self, bri, kelvin, area=False):
        """`{bri}% · {K} K` (the Lights space); `{area} · {bri}% · {K} K` on Home's lights domain."""
        name = self.lights.name
        if area and name:
            if self.lights.supports_ct:
                return fit_copy("knob.sub.lights_area_level", LINE_14, name=name, bri=bri, K=kelvin)
            return fit_copy("knob.sub.lights_area_level_bri", LINE_14, name=name, bri=bri)
        if self.lights.supports_ct:
            return copy_text("knob.sub.lights_level", bri=bri, K=kelvin)
        return copy_text("knob.sub.lights_level_bri", bri=bri)

    def lights_area(self):
        """Read-only (the knob frames and the Navigator): the area's facts. `count` (None for the
        single-light setup), `ok` / `on` (available / on lights), `bad` (names of the unavailable
        lights), `mixed` (some available lights off, or the on lights differ in level or K) and
        `members` (the per-light rows Job C's adapter reports, [] without them)."""
        lights = self.lights
        members = [m for m in lights.members if isinstance(m, dict)]
        count = lights.count if type(lights.count) is int else (len(members) if members else None)
        if members:
            ok = [m for m in members if m.get("available", True) is not False]
            on = [m for m in ok if m.get("on")]
            bad = [str(m.get("name") or m.get("entity_id") or "") for m in members if m.get("available", True) is False]
            kelvins = [m.get("kelvin") for m in on if type(m.get("kelvin")) is int]   # brightness-only lights have none
            levels = [_int(m.get("bri"), 0) for m in on]
            # Lights within LIGHTS_NEAR of each other are uniform (reporting drift after a fade), not mixed.
            spread = (bool(levels) and max(levels) - min(levels) > LIGHTS_NEAR["bri"]) or \
                (bool(kelvins) and max(kelvins) - min(kelvins) > LIGHTS_NEAR["kelvin"])
            mixed = self._steady_mixed(bool(on) and (len(on) < len(ok) or spread))
            return {"count": count, "ok": len(ok), "on": len(on), "bad": bad, "mixed": mixed,
                    "members": members[:LIGHTS_MEMBERS_DRAWN]}
        on_count = lights.on_count if type(lights.on_count) is int else None
        mixed = self._steady_mixed(bool(count and on_count is not None and 0 < on_count < count))
        return {"count": count, "ok": count, "on": on_count, "bad": [], "mixed": mixed, "members": []}

    def _steady_mixed(self, mixed):
        """The area's mixed look, held while the knob drives the lights (a write pending or in flight, the
        big value showing after a turn, or LIGHTS_MIXED_QUIET after the last write)."""
        busy = bool(self.lights_intent() or self.lights_request is not None or self.lights_command is not None
                    or self.clock() - self.last_lights_write < LIGHTS_MIXED_QUIET
                    or (self._lights_reveal_source == "local" and self._lights_reveal() is not None))
        if self._mixed_shown is None or not busy:
            self._mixed_shown = mixed
        return self._mixed_shown

    def lights_block(self):
        """Why the lights cannot be used (r3.1 design `lightsBlock`), or None: `connecting`,
        `nc` (Home Assistant not connected), `area` (the area is gone), `empty` (no lights in the
        area) or `unav` (every light unavailable)."""
        lights = self.lights
        detail = lights.detail
        if detail == "area_missing":
            return "area"
        if detail == "no_lights" or (lights.configured and lights.count == 0):
            return "empty"
        if detail == "lights_unavailable":
            return "unav"
        if not lights.online:
            if lights.configured and (lights.reason == "connecting" or detail in ("connecting", "registry")
                                      or (not lights.known and lights.reason in ("", "connecting"))):
                return "connecting"
            return "nc"
        area = self.lights_area()
        if area["members"] and not area["ok"]:
            return "unav"
        return None

    def _lights_words(self, n):
        return COPY["knob.title.lights_count_one"] if n == 1 else copy_text("knob.title.lights_count", n=n)

    def _lights_status(self, home=False):
        """The unavailable / mixed line of the lights (r3.1): (text, tone) or None. Home's domain
        drops ` · average`."""
        area = self.lights_area()
        if area["bad"]:
            text = (copy_text("knob.meta.lights.one_unavailable", name=area["bad"][0]) if len(area["bad"]) == 1
                    else copy_text("knob.meta.lights.n_unavailable", n=len(area["bad"])))
            return fit_copy("knob.meta.lights.raw", LINE_R3, text=text), "error"
        if area["mixed"]:
            if area["on"] is not None and area["ok"] and area["on"] < area["ok"]:
                text = copy_text("knob.meta.lights.some_on", on=area["on"], ok=area["ok"])
            else:
                text = self._lights_words(area["ok"] or 0)
            return (text if home else text + COPY["knob.meta.lights.average"]), "secondary"
        return None

    def _lights_area_line(self):
        """`{area} · 3 lights` (meta), or '' for the single-light setup."""
        area = self.lights_area()
        if area["count"] is None or not self.lights.name:
            return ""
        return fit_copy("knob.meta.lights.area", LINE_R3, name=self.lights.name, lights=self._lights_words(area["count"]))

    def _ring_kelvin(self, kelvin):
        return _clamp(kelvin if type(kelvin) is int else KELVIN_DEFAULT, KELVIN_MIN, KELVIN_MAX)

    def _bri_ring(self, bri, kelvin):
        return {"style": "bri", "value": _clamp(bri, 0, 100), "index": 0, "count": 0,
                "kelvin": self._ring_kelvin(kelvin)}

    def _ctemp_ring(self, kelvin):
        kelvin = self._ring_kelvin(kelvin)
        return {"style": "ctemp", "value": _clamp(int(round((kelvin - KELVIN_MIN) * 100 / (KELVIN_MAX - KELVIN_MIN))), 0, 100),
                "index": 0, "count": 0, "kelvin": kelvin}

    def _frame_lights_blocked(self, frame, block):
        """r3.1 blocked Lights screens (the design's `blockedView`): ring off, dimmed buttons."""
        lights = self.lights
        name = lights.name
        if block == "connecting":
            frame.update(title=COPY["knob.title.lights_connecting"], subtitle=COPY["knob.sub.lights_connecting"],
                         activity="loading")
        elif block == "empty":
            frame.update(title=copy_text("knob.title.lights_none", name=name) if name else COPY["knob.title.lights_none_area"],
                         subtitle=COPY["knob.sub.lights_none"], activity="unavailable")
        elif block == "unav":
            area = self.lights_area()
            sub = (fit_copy("knob.meta.lights.area", LINE_14, name=name, lights=self._lights_words(area["count"] or 0))
                   if name and area["count"] is not None else "")
            frame.update(title=COPY["knob.title.lights_offline"], subtitle=sub, activity="offline",
                         meta=COPY["knob.meta.lights.check"], metaTone="error")
        elif block == "area":
            frame.update(title=COPY["knob.title.lights_area_missing"], subtitle=COPY["knob.sub.lights_area_missing"],
                         activity="unavailable")
        else:   # nc: not configured, offline, the token refused
            frame.update(title=COPY["knob.title.lights_nc"], subtitle=COPY["knob.sub.lights_nc"],
                         meta=COPY["knob.meta.lights.open_settings"], metaTone="error",
                         activity="error" if lights.reason in ("auth", "forbidden") else "offline")

    def _frame_lights(self, frame, ready):
        """Lights (r3 1e; r3.1 design): the Lights space and Home's lights domain (`home`: the
        area's name on the level line, the big value captioned with it, no temperature mode)."""
        lights = self.lights
        home = self.screen.mode == "launcher"
        frame["layout"] = "lights"
        frame["heading"] = COPY["knob.heading.lights"]
        frame["ring"] = {"style": "off", "value": 0, "index": 0, "count": 0}
        block = self.lights_block()
        if block is not None:
            self._frame_lights_blocked(frame, block)
            transient = self._transient()
            if transient is not None:
                frame["meta"], frame["metaTone"] = transient.text, transient.tone
            return
        bri, kelvin, on = self.display_bri, self.display_kelvin, self.lights_display_on()
        pending = bool(self.lights_intent() or self.lights_request is not None or self.lights_command is not None)
        frame["activity"] = "pending" if pending else "idle"
        reveal = self._lights_reveal() if on else None
        temp_mode = self._lights_knob_mode() == "temp"
        mixed = self.lights_area()["mixed"]
        if reveal is not None:
            # The big value (README 2.2 "Lights (turning)"): caption + digits + unit.
            frame["layout"] = "lightsbig"
            if reveal == "temp":
                frame.update(volumeCaption=COPY["knob.caption.temperature"], value=str(kelvin), valueUnit="K")
                frame["ring"] = self._ctemp_ring(kelvin)
            else:
                caption = (lights.name or COPY["knob.caption.brightness"]) if home else \
                    COPY["knob.caption.brightness_average" if mixed else "knob.caption.brightness"]
                frame.update(volumeCaption=caption, value=str(bri), valueUnit="%")
                frame["ring"] = self._bri_ring(bri, kelvin)
            frame["title"] = self._lights_title()
            frame["subtitle"] = self._lights_level(bri, kelvin, area=home)
            # The firmware draws a lights / lightsbig frame's 12 px line from `meta` (not `status`).
            transient = self._transient()
            if transient is not None:
                frame["meta"], frame["metaTone"] = transient.text, transient.tone
            elif self._lights_reveal_source == "external" and not pending:
                frame["meta"], frame["metaTone"] = COPY["knob.status.lights_changed"], "secondary"
            return
        if not on:
            frame.update(title=COPY["knob.title.lights_off"], subtitle=COPY["knob.sub.lights_off"])
            line = "" if home else self._lights_area_line()
            if line:
                frame["meta"], frame["metaTone"] = line, "meta"
        else:
            frame["title"] = self._lights_title()
            frame["subtitle"] = self._lights_level(bri, kelvin, area=home)
            status = self._lights_status(home=home)
            if temp_mode:
                frame["meta"], frame["metaTone"] = COPY["knob.meta.lights.knob_temperature"], "warm"
            elif status is not None:
                frame["meta"], frame["metaTone"] = status
            elif not home and self._lights_area_line():
                frame["meta"], frame["metaTone"] = self._lights_area_line(), "meta"
            frame["ring"] = self._ctemp_ring(kelvin) if temp_mode else self._bri_ring(bri, kelvin)
        transient = self._transient()
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone

    def _scene_label(self, scene):
        if not isinstance(scene, dict):
            return ""
        return scene.get("label") or scene.get("entity_id", "").split(".")[-1].replace("_", " ").capitalize()

    def _frame_scenes(self, frame, ready):
        lights = self.lights
        scenes = lights.scenes[:SCENES_MAX]
        frame["layout"] = "scenes"
        frame["heading"] = COPY["knob.heading.scenes"]
        if not scenes:
            frame.update(title=COPY["knob.meta.lights.no_scenes"], subtitle=COPY["knob.sub.lights_not_set_up"])
            frame["ring"] = {"style": "off", "value": 0, "index": 0, "count": 0}
            return
        count = len(scenes)
        index = _clamp(self.screen.index, 0, count - 1)
        scene = scenes[index]
        frame["title"] = self._scene_label(scene)
        frame["prevTitle"] = self._scene_label(scenes[index - 1]) if index > 0 else ""
        frame["nextTitle"] = self._scene_label(scenes[index + 1]) if index < count - 1 else ""
        running = bool(scene.get("running")) or (scene.get("entity_id") == lights.scene_id and not lights.adjusted
                                                  and lights.on)
        if running:
            meta = copy_text("knob.meta.scenes.running", i=index + 1, n=count)
        elif type(scene.get("bri")) is int and type(scene.get("kelvin")) is int:
            meta = copy_text("knob.meta.scenes.preview", i=index + 1, n=count, bri=scene["bri"], K=scene["kelvin"])
        elif type(scene.get("bri")) is int:
            meta = copy_text("knob.meta.scenes.preview_bri", i=index + 1, n=count, bri=scene["bri"])
        else:
            meta = copy_text("knob.meta.scenes.position", i=index + 1, n=count)
        frame["meta"] = meta
        transient = self._transient()
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        frame["activity"] = "pending" if self.lights_command is not None else "idle"
        frame["ring"] = {"style": "clusters", "value": 0, "index": index, "count": count}

    # ------------------------------------------------------------------ A0 Onshape mode (ONSHAPE.md)
    def can_enter_onshape(self):
        """Presentation >= 6 only (the r3 navigation), and never over an overlay or Seek."""
        if not self.spaces:
            return False
        if self.screen.mode == "onshape":
            return True
        return self.screen.mode not in OVERLAY_MODES + ("seek",) and not self._overlay_open()

    def enter_onshape(self, cause="onshape"):
        """The Onshape mode (Auto, the tray or Settings' Manual). Re-centred (a new control at
        30000); an unsent Sonos volume target is dropped (the knob no longer sets volume)."""
        if self.screen.mode == "onshape":
            return True
        if not self.can_enter_onshape():
            return False
        self.desired_volume = None
        self._volume_reveal_until = 0.0
        self.onshape_keys.clear()
        self._onshape_swallowed.clear()
        self._onshape_wheel = None
        self._onshape_param_left_at = None
        self._onshape_refused_until = 0.0
        self._onshape_refused_kind = "refused"
        self._onshape_chord_at = None
        self._new_screen("onshape", ONSHAPE_BOUNDS[2], cause)
        return True

    def exit_onshape(self, cause="onshape exit"):
        """Back to Home (Auto after the focus loss, the tray, Settings Off). Not a user exit."""
        if self.screen.mode != "onshape":
            return False
        self._onshape_reset()
        self._go_root(cause)
        return True

    def _onshape_reset(self):
        """Onshape mode's key grammar and app state, cleared on every way out."""
        self.onshape_keys.clear()
        self._onshape_swallowed.clear()
        self._onshape_wheel = None
        self._onshape_param_left_at = None
        self._onshape_chord_at = None
        self.onshape_app = None

    def _onshape_exit_by_user(self, cause):
        """All four buttons held (onshape_home_chord; the tray's Leave counts too, in the runtime): Home, and
        Auto waits until Onshape loses and regains the foreground."""
        self.onshape_user_exits += 1
        self.last_knob_input = self.clock()
        self.exit_onshape(cause)

    def onshape_input(self, kind, logical=None, delta=0):
        """The knob's events in Onshape mode (Tk thread, from the runtime): ``down`` / ``up`` /
        ``hold`` (logical slot), ``turn`` (delta), ``ready`` (``logical`` = the held mask), and the
        injector's results ``refused`` / ``undo``. Presentation only: the injector does the input; the
        runtime fires the Home chord (onshape_chord_due / onshape_home_chord)."""
        if self.screen.mode != "onshape":
            return
        now = self.clock()
        keys = self.onshape_keys
        feel_before = self.feel() if kind in ("down", "up") else None
        if kind == "down":
            self.last_knob_input = now
            # A2: mirror OnshapeApp.down. In parameter mode 1 / 2 / 4 are a step (3 is OK / cancel); with the wheel
            # open they switch rings; 3 opens the wheel only with none of 1 / 2 / 4 down (else it does nothing and a
            # modifier pressed next still drags).
            wheel = self._app_wheel_button()
            if self.onshape_app is not None and logical in range(4):
                if self._onshape_param_on():
                    if logical != wheel:
                        self._onshape_swallowed.add(logical)
                elif self._onshape_wheel_open():
                    if logical != wheel:
                        self._onshape_swallowed.add(logical)
                elif logical == wheel and not any(keys.is_down(s) for s in range(4) if s != wheel):
                    self._onshape_wheel = self.control_id
            keys.down(logical)
            if keys.chording:
                self._onshape_wheel = None             # the Home chord closes an open wheel unrun (OnshapeApp.chord)
            self._haptic("confirm.tick")               # 2026-09-30: every press ticks (a modifier, Undo, the chord)
            if keys.mask == 0xF:
                if self._onshape_chord_at is None:
                    self._onshape_chord_at = now       # the 4th button: the Home chord's 1.0 s starts
            else:
                self._onshape_chord_at = None
        elif kind == "turn":
            self.last_knob_input = now
            keys.turn()
        elif kind == "up":
            self._onshape_chord_at = None              # a release before 1.0 s cancels the Home chord
            if logical == self._app_wheel_button():
                if self._onshape_param_on() and keys.is_down(logical):
                    self._onshape_param_left_at = now  # OK / cancel: parameter mode ends (the snapshot catches up)
                self._onshape_wheel = None             # the wheel closes (it runs its entry or sends Undo)
            if logical in self._onshape_swallowed:
                self._onshape_swallowed.discard(logical)
                keys.up(logical)
            elif keys.up(logical) == "tap" and logical == 0 and self.app_profile is None:
                # Button 1 is ZOOM (hold + turn, Karl's F1): a tap sends nothing and only says how to leave.
                self._set_transient("knob.status.onshape.home", tone="meta", ms=REASON_META)
        if feel_before is not None and self.feel_supported and self.feel() != feel_before:
            # r4 (an r4 knob only): orbit / pan / tilt turn fluid (fluid.light), the knob alone zooms in detents; the
            # new control re-anchors under the finger (feel.fade), so no detent drops.
            self._reenter("onshape feel")
        elif kind == "hold":
            if logical not in self._onshape_swallowed:
                keys.hold(logical)                     # no hold acts here (it only drops that press's tap)
        elif kind == "ready":
            keys.seed(logical)
            mask = logical if type(logical) is int else 0
            self._onshape_swallowed.intersection_update(s for s in range(4) if mask & (1 << s))
            if not mask & (1 << 2):
                self._onshape_wheel = None             # 3's release was lost: the wheel closes (OnshapeApp.seed)
            if keys.mask != 0xF:
                self._onshape_chord_at = None          # a mask seen only on re-entry never starts the chord
        elif kind in REFUSALS:
            # DD-SEC-001: `focus_refused` (onshape.FOCUS_REFUSED) is the same refusal (sound, buzz, red flash) with
            # its own words: the cursor is on the model but the keys would land outside the page.
            self._onshape_refused_until = now + ONSHAPE_REFUSED_META
            self._onshape_refused_kind = kind
            self._feedback("err", moment="refused")
        elif kind == "undo":
            self._set_transient("knob.status.onshape.undo", tone="meta", ms=ONSHAPE_UNDO_META)
            self._feedback("ok")

    def onshape_chord_due(self, now=None):
        """All four buttons have been down together for HOME_CHORD_SECONDS (from the 4th press)."""
        if self.screen.mode != "onshape" or self._onshape_chord_at is None or self.onshape_keys.mask != 0xF:
            return False
        now = self.clock() if now is None else now
        return now - self._onshape_chord_at >= HOME_CHORD_SECONDS

    def onshape_home_chord(self):
        """The Home chord matured (the runtime has already released every injected input and swallows the four
        buttons' later holds and releases): Home, and Auto waits for Onshape to lose and regain the foreground."""
        if not self.onshape_chord_due():
            return False
        self._onshape_exit_by_user("chord")
        return True

    def onshape_action(self):
        """zoom | tilt | orbit | pan | refused | focus_refused: the knob's title now."""
        if self.screen.mode != "onshape":
            return ""
        if self.clock() < self._onshape_refused_until:
            return self._onshape_refused_kind
        return self.onshape_keys.action()

    def _buttons_onshape(self):
        if self.app_profile is not None:
            return self._buttons_app()
        return self._buttons_onshape_legacy()

    def _buttons_app(self):
        """App profiles: each button's legend word (title case; a blank legend shows a dash), the held slot lit."""
        live = self.onshape_keys.modifier_slot()
        legend = tuple(self.app_profile.legend) + ("",) * 4
        out = []
        for button in range(4):
            spec = slot_of_button(self.app_profile, button)
            word = (legend[button] or "").strip()
            label = word[:1].upper() + word[1:].lower() if word else "—"
            icon = "expand" if spec is not None and spec.kind in ("drag", "wheel", "keys") else "back"
            out.append(self._btn(icon, label, lit="on" if live == button else None))
        return out

    def _buttons_onshape_legacy(self):
        """1 Tilt (hold + turn: the vertical orbit; 7.2.2.0) · 2 Orbit (hold + turn) · 3 Undo (tap) · 4 Pan
        (hold + turn); the held modifier is lit; the knob alone zooms. Home is all four held (no button of its own).
        No v6 icon reads as a vertical rotation, so Tilt borrows Pan's arrows (`expand`; ONSHAPE.md section 2)."""
        slot = self.onshape_keys.modifier_slot()
        return [self._btn("expand", "Tilt", lit="on" if slot == 0 else None),
                self._btn("shuffle", "Orbit", lit="on" if slot == 1 else None),
                self._btn("back", "Undo"), self._btn("expand", "Pan", lit="on" if slot == 3 else None)]

    def _press_onshape(self, logical, now):
        """Host-side presses (the simulator window): the knob's keys arrive through onshape_input."""
        if logical == 0:
            self._set_transient("knob.status.onshape.home", tone="meta", ms=REASON_META)

    def _frame_onshape(self, frame, ready):
        if self.app_profile is not None:
            self._frame_app(frame)
            return
        action = self.onshape_action()
        frame["layout"] = "nowPlaying"
        frame["heading"] = COPY["knob.heading.onshape"]
        frame["title"] = COPY["knob.title.onshape." + action]
        frame["subtitle"] = COPY["knob.sub.onshape." + action]
        frame["ring"] = {"style": "off", "value": 0, "index": 0, "count": 0}
        frame["activity"] = "idle"
        transient = self._transient()
        if self.onshape_keys.chording:
            # The Home chord is building (3+ buttons down): say what finishes it.
            frame["status"], frame["statusTone"] = COPY["knob.status.onshape.home"], "meta"
        elif transient is not None:
            frame["status"], frame["statusTone"] = transient.text, transient.tone
        app = self.onshape_app
        if isinstance(app, dict):
            # A2: the knob's own Onshape UI (device._frame keeps it only for an appCanvas knob; an older knob
            # shows the text above). slot = the cube scene; the wheel, parameter mode and echo come from the injector.
            slot = self.onshape_keys.action()
            frame["app"] = {"id": "onshape", "slot": slot if slot in ("zoom", "orbit", "pan", "tilt") else "zoom"}
            if action in ("refused", "focus_refused"):
                frame["app"]["refused"] = True
            if action == "focus_refused":
                # DD-SEC-001: the keys would land outside the page; the knob's canvas says CLICK MODEL FIRST
                # (a firmware without it ignores the unknown key and keeps POINT AT MODEL).
                frame["app"]["refusedFocus"] = True
            for name in ("flash", "wheel", "param", "echo"):
                if name in app:
                    frame["app"][name] = deepcopy(app[name])
            if action in (KEYBOARD_REFUSED, DISABLED_REFUSED):
                del frame["app"]           # app profiles: the text screen says why for the moment

    # ------------------------------------------------------------------ app profiles (plan 3, S1 DD-B)
    def enter_app(self, profile, cause="app"):
        """The app mode for `profile` (an app_profiles.AppProfile; None or id "onshape" = Onshape as before). A switch
        from another app re-enters (a new control: the new profile's feel and an empty key grammar)."""
        target = None if profile is None or getattr(profile, "id", None) == "onshape" else profile
        if self.screen.mode == "onshape":
            if target is self.app_profile or (target is not None and self.app_profile is not None
                                              and target.id == self.app_profile.id):
                self.app_profile = target
                return True
            self._set_app_profile(target)
            self._onshape_reset()
            self.app_canvas_ref = None
            self._onshape_refused_until = 0.0
            self._new_screen("onshape", ONSHAPE_BOUNDS[2], cause)
            return True
        if not self.can_enter_onshape():
            return False
        self._set_app_profile(target)
        self.app_canvas_ref = None
        return self.enter_onshape(cause)

    def exit_app(self, cause="app exit"):
        return self.exit_onshape(cause)

    def _set_app_profile(self, profile):
        self.app_profile = profile
        self.onshape_keys = KeyTracker() if profile is None else SlotTracker(turn_buttons(profile),
                                                                             knob_label(profile))

    def app_id(self):
        """The active app's profile id ("onshape" for Onshape), or None outside the app mode."""
        if self.screen.mode != "onshape":
            return None
        return self.app_profile.id if self.app_profile is not None else "onshape"

    def app_slot_token(self):
        """The frame's `app.slot` for a profile app: the held turn slot's name (f1..f4), else knob."""
        held = self.onshape_keys.modifier_slot()
        spec = slot_of_button(self.app_profile, held) if held is not None and self.app_profile is not None else None
        return spec.name if spec is not None else "knob"

    def _app_live_label(self):
        held = self.onshape_keys.modifier_slot()
        profile = self.app_profile
        spec = profile.slots.get("knob") if held is None else slot_of_button(profile, held)
        return (spec.label if spec is not None and spec.label else profile.name).upper()

    def _frame_app(self, frame):
        """App profiles: the text screen (heading = the profile's name, title = the live action or the wheel's command,
        subtitle = the legend) and, once the knob has the profile, the `app` object for its canvas."""
        profile = self.app_profile
        action = self.onshape_action()
        app = self.onshape_app if isinstance(self.onshape_app, dict) else {}
        legend = " · ".join(word for word in profile.legend if word and word.strip())
        frame["layout"] = "nowPlaying"
        frame["mode"] = profile.name
        frame["heading"] = profile.name
        frame["ring"] = {"style": "off", "value": 0, "index": 0, "count": 0}
        frame["activity"] = "idle"
        if action in REFUSALS:
            frame["title"], frame["subtitle"] = COPY["knob.title.app." + action], COPY["knob.sub.app." + action]
        elif "param" in app:
            param = app["param"]
            cmd = self._app_command(param.get("ring"), param.get("index"))
            name = cmd.param.label if cmd is not None and cmd.param is not None else ""
            frame["title"] = f"{name} {param.get('value', 0) / 1000:.2f}".strip()
            frame["subtitle"] = copy_text("knob.sub.app.param", n=(self._app_wheel_button() or 2) + 1)
        elif "wheel" in app:
            wheel = app["wheel"]
            cmd = self._app_command(wheel.get("ring"), wheel.get("index"))
            ring = wheel.get("ring", 0)
            rings = profile.rings
            frame["title"] = cmd.name if cmd is not None else COPY["knob.title.app.cancel"]
            frame["subtitle"] = rings[ring].name if 0 <= ring < len(rings) else ""
        else:
            frame["title"], frame["subtitle"] = self._app_live_label(), legend
        transient = self._transient()
        if self.onshape_keys.chording:
            frame["status"], frame["statusTone"] = COPY["knob.status.app.home"], "meta"
        elif transient is not None:
            frame["status"], frame["statusTone"] = transient.text, transient.tone
        ref = self.app_canvas_ref
        if ref is not None and isinstance(self.onshape_app, dict) and action not in (KEYBOARD_REFUSED,
                                                                                     DISABLED_REFUSED):
            pid, crc = ref
            frame["app"] = {"id": pid, "crc": crc, "slot": self.app_slot_token()}
            if action in (REFUSED, FOCUS_REFUSED):
                frame["app"]["refused"] = True
            if action == FOCUS_REFUSED:
                frame["app"]["refusedFocus"] = True
            for name in ("flash", "wheel", "param", "echo"):
                if name in app:
                    frame["app"][name] = deepcopy(app[name])

    def _app_command(self, ring, index):
        rings = self.app_profile.rings if self.app_profile is not None else ()
        if type(ring) is not int or type(index) is not int or not 0 <= ring < len(rings):
            return None
        commands = rings[ring].commands
        return commands[index - 1] if 1 <= index <= len(commands) else None

    # ------------------------------------------------------------------ compat and view models (section 11.2)
    def items(self):
        mode = self.screen.mode
        if mode == "windows":
            return list(self.screen.windows.items) if self.screen.windows else []
        if mode in ("recent", "explorer"):
            return list(self.recent.items if self._shown_source() == "recent" else self.favourites.items)
        if mode == "upnext":
            upnext = self.screen.upnext
            return [upnext.rows.get(n) for n in range(1, self._upnext_count() + 1)]
        return []

    def selected(self):
        items = self.items()
        index = self.screen.index
        return items[index] if 0 <= index < len(items) else None

    def presented_index(self):
        return self.screen.index

    def presented(self):
        return self.selected()

    def lookahead_page(self):
        return None  # the v6 page lookahead is retired (flat list, U5)

    def lookahead_live(self, request):
        return False

    def recent_wanted(self, list_visit, offset=None):
        """Whether a page for the Recently Added visit `list_visit` (at `offset`) is still wanted
        (lane check, any thread): a copy of a page that already landed is not (section 5.2.2)."""
        lst = self.recent
        return list_visit == lst.visit and (type(offset) is not int or offset >= lst.next_offset)

    def art_item(self):
        """(kind, item) whose cover the knob shows (section 10.4 art identity), or (kind, None)."""
        mode = self.screen.mode
        if mode == "recent" and self._recent_source() == "recent":
            return "recent", self.recent.item(self.screen.index) if self.recent.state == "ready" else None
        if mode in ("recent", "explorer"):
            source = self._shown_source()
            if source == "recent":
                return "recent", self.recent.item(self.screen.index) if self.recent.state == "ready" else None
            item = self._source_item("favourites", self.screen.index) if self.favourites.state == "ready" else None
            if item is not None:
                meta = self.favourites.meta.get(_item_id(item)) or {}
                item = dict(item, **{key: meta[key] for key in ("mosaic", "first_art") if key in meta})
            return "playlist", item
        if mode == "upnext":
            return "row", self._upnext_focus_row()
        if mode == "launcher" and self._lights_domain():
            return "lights", None
        if mode in ("home", "launcher", "tracks", "seek"):
            return "playing", None
        return mode, None

    def explorer_view(self):
        explorer = self.screen.explorer if self.screen.mode == "explorer" else None
        index = self.screen.index if explorer else 0
        recent_index = explorer.index_by_source.get("recent", 0) if explorer else self.screen.index
        recent_items, recent_first = self._explorer_window("recent", recent_index)
        fav_items, _ = self._explorer_window("favourites", explorer.index_by_source.get("favourites", 0)
                                             if explorer else 0)
        return {"source": explorer.source if explorer else "recent", "index": index,
                "recent": {"items": recent_items, "first": recent_first, "total": self.recent.total,
                           "state": self.recent.state, "complete": self.recent.complete, "rev": self.recent.rev},
                "favourites": {"items": fav_items, "state": self._source_state("favourites"), "rev": self.favourites.rev},
                "sonos_available": bool(self.state["online"]), "reduced_motion": self.reduced_motion}

    def upnext_view(self):
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if upnext is None:
            return None
        active = self.shuffle_active()
        row = self._upnext_focus_row()
        liked = bool(row and row.get("liked") is True)
        token = self._shuffle_token()
        line = {"sonos": "overlay.upnext.shuffle_sonos", "companion": "overlay.upnext.shuffle_on"}.get(
            token, "overlay.upnext.shuffle_off")
        return {"focus": self.screen.index, "now": upnext.P - 1, "T": upnext.T,
                "rows": self._upnext_rows_payload(), "regime": upnext.regime,
                "card": {"n": max(0, upnext.T - upnext.P)} if upnext.card else None,
                "context": self._upnext_context(), "shuffle": token, "likes_known": self._likes_known(),
                "loading": upnext.loading, "shuffle_line": COPY[line],
                "hints": ["Back", "Shuffle off" if active else "Shuffle", "Liked" if liked else "Like", "Play"],
                "reduced_motion": self.reduced_motion}

    def windows_view(self):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is None:
            return None
        keep = None
        assigned = [side for side in ("left", "right") if getattr(windows, side)]
        if len(assigned) == 1 and windows.desk_open and windows.desk_open != getattr(windows, assigned[0]):
            keep = self._window_item_by_id(windows.desk_open)
        failure = windows.failure if windows.failure and self.clock() < windows.failure["until"] else None
        return {"items": windows.items, "index": self.screen.index, "left": windows.left, "right": windows.right,
                "keep": keep, "failure": failure}


def _descriptor_resource(item):
    """An item for a service effect: every field, the Apple `_resource` included (resolve needs it)."""
    return dict(item) if isinstance(item, dict) else {}
