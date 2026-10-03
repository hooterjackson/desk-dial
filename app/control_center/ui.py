"""Tk companion: the knob mirror, physical button row, and separate setup.

The mirror draws what the knob draws: the LCD is ``lcd_preview.render_lcd`` of
the runtime's decorated frame (the one deliberate difference: the Windows
layout shows the real application icon instead of the knob's letter tile), and
the ring/buttons are ``PreviewLights`` drive colours shown with the Knob Face
optical mapping. Presentation settings (album artwork, LED style) apply live
and never re-enter a control.

Floating knob (FLOATING_KNOB.md section 6): ``ControlCenterApp(..., chrome=False,
overlay=KnobOverlay)``, used only by the installed live app, builds no widget on
the root, which stays withdrawn (it still owns F24, parents Settings and hosts every
timer; the Windows picker is the carousel's own native windows, not a Tk child). Each tick keeps PreviewLights running while the knob is
connected and, while the overlay wants frames, renders the LCD at the overlay's
physical size (same layout, higher fidelity) and the ring colours, and hands a
changed OverlayScene to the overlay thread; a new physical touch calls
overlay.touch(). ``chrome=True`` (the default: app.py and the simulator) is the
full window, unchanged.

Windows switcher carousel (CAROUSEL.md, desktop v6): each tick hands the live picker
its icons (the IconWorker's 128 px masters, in both modes) and the runtime's label
facts (``_sync_picker_icons``); the floating knob is suppressed for as long as the
carousel is open, with either background, from its open to the end of its exit
animation (reason ``'carousel'``, ``_carousel_open``: CAROUSEL.md section 11), and its
window is kept out of the frost's capture (``_sync_capture_exclusions``: KnobOverlay.hwnd
to set_capture_exclusions); Settings adds **Switcher background: Liquid
glass / No background** (``picker_background``, applied live like artwork and LEDs).
On the carousel's plain-host fallback "No background" is shown disabled with a note
(WindowsAdapter.picker_backgrounds) and a stored "none" is kept, not overwritten.

Desktop v7 (DESKTOP_STAGE K4, CONTROL_CENTER_V5 K3, ALIVE K2; WP10):
- **Presenters.** The runtime gets the stage presenter (``stage``: the ``MusicOverlay`` over
  ``stage.scenes.start_music_stage``, started by standalone.py after the floating knob) and the
  toast service (the WindowsAdapter's ``toast``). The simulator gets ``FakeStagePresenter`` and
  ``SimulatedToasts`` over one ``SimControls`` (K3 section 16), a ``SimulatedSonos`` with the BS
  album loaded, and the state picker's PC connection drives a ``SimulatedDevice``. The picker gets
  the overlay registry (``set_overlay_registry``) and the effective Motion setting.
- **Input fast path** (K4 5.3, 22 Q3): the DeviceBridge's reader thread hands each ``position``,
  ``limit`` and ``button`` event, stamped with its QPC read time, to ``FastPath`` before the Tk
  tick sees it: the floating knob's engine (``post_input``) and, while an explorer or Up next is
  up, the stage (``position``); a knob touch also warms the stage device and the picker's GPU
  chrome device (``note_touch`` on both, together and at most once per FAST_TOUCH_SECONDS;
  CAROUSEL.md 12.4: the picker is the runtime's WindowsAdapter, handed over each tick).
- **Floating knob.** A knob with ``alive`` is drawn by AliveLights on the overlay thread: the Tk
  tick only posts the frame the knob was sent, the claim, the control's maximum and the latched
  clock / progress / Motion / tuning (``_post_alive``), and the LCD scene while the knob wants
  frames. Knobs without ``alive`` keep PreviewLights scenes. Suppression reasons ``explorer`` and
  ``upnext`` hold from the open (the mode) to the ``closed`` event (the registry); the stage gets
  the same capture exclusions as the picker.
- **Settings** opens on the status strip (Knob / Sonos / Apple Music, K3 14.1: ``strip_model``)
  with Motion (``settings.motion``: Match Windows / Full / Reduced) among the presentation rows.
"""
from __future__ import annotations

from collections import OrderedDict
import ctypes
import json
import logging
import math
from pathlib import Path
import queue
import os
import re
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, font
import webbrowser

from .controller import Controller, PROFILES, app_display_name
# The Knob Face LED colour model lives in knob_face (Tk-free, shared with the floating
# knob); these names stay importable from here for the mirror and existing callers.
from .knob_face import (
    BUTTON_FACE, LED_FLOOR, LED_MATCH_TOLERANCE, LED_PALETTE, OPTICAL_ALPHA, STRIP_MIN_ALPHA,
    led_source, optical_alpha, ring_display, ring_palette, strip_display,
)
from .presentation import LED_STYLES, RING_SEGMENTS
from .preview_lights import PreviewLights
from .simulation import (SIM_AREAS, FakeStagePresenter, SimControls, SimulatedAppleMusic, SimulatedDevice,
                         SimulatedHomeAssistant, SimulatedSonos,
                         SimulatedToasts, SimulatedWindows)
from . import app_profiles, paths, profile_updates
from .onshape import (CONTENT_CLASSES as ONSHAPE_CONTENT_CLASSES, DEFAULT_IDLE_MS as DEFAULT_ONSHAPE_IDLE_MS,
                      DEFAULT_ONSHAPE_MODE, ONSHAPE_MODES, normal_classes as normal_onshape_classes,
                      normal_idle_ms as normal_onshape_idle_ms, normal_mode as normal_onshape_mode)
from .runtime import (Runtime, DEFAULT_KNOB_SOUND, DEFAULT_KNOB_VOLUME, KNOB_SOUND_LEVELS, KNOB_VOLUME_MAX,
                      KNOB_VOLUME_STEP, SHUTDOWN_JOIN_S, knob_volume_setting, normal_knob_volume)
# Settings "Switcher background" (CAROUSEL.md section 3). Importing windows has no side effect.
from .windows import DEFAULT_PICKER_BACKGROUND, PICKER_BACKGROUNDS

APP_DIR = Path(__file__).resolve().parents[1]
# The installed app keeps its data and device backups in the Desk Dial home (control_center.paths:
# %LOCALAPPDATA%\DeskDial\data and \backups); a source checkout keeps them next to the code.
DATA_DIR = paths.data_dir() if getattr(sys, "frozen", False) else APP_DIR / "local"
BACKUP_DIR = paths.backups_dir() if getattr(sys, "frozen", False) else APP_DIR / "backups"
FONT_DIR = APP_DIR / "assets" / "fonts"
# App icon (APP_ICON.md item 3): Tk 8.6 cannot read the PNG-compressed frames of the .ico, so
# Tk gets the two PNGs (iconphoto) and every mapped Tk window gets the .ico's own frames for its
# DPI through Win32 (AppWindowIcons: LoadImageW, WM_SETICON and the TkTopLevel class icons).
APP_ICON_DIR = APP_DIR / "assets" / "app-icon"
APP_ICON_ICO = APP_ICON_DIR / "ico" / "nano-d-app.ico"
APP_ICON_PHOTOS = (APP_ICON_DIR / "png" / "nano-d-app-256.png", APP_ICON_DIR / "png" / "nano-d-app-32.png")
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
GCLP_HICON, GCLP_HICONSM = -14, -34
SM_CXICON, SM_CXSMICON = 11, 49
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

# Design tokens (Control Center design system): square corners, 2 px rules.
BG = "#1B1A1A"          # window background
SURFACE = "#242323"     # panels, fields, buttons
HAIRLINE = "#2D2B2B"    # quiet rules
RULE = "#444141"        # strong rules, selected segments
TEXT = "#F3F2F2"
SECONDARY = "#BAB6B6"
TERTIARY = "#9B9797"
OK = "#6ED996"
ERROR = "#FF7A66"
NOTICE = ERROR
RULE_WIDTH = 2
FALLBACK_FAMILY = "Segoe UI"
UI_FAMILY = FALLBACK_FAMILY   # "Archivo" once registered and visible to Tk (ensure_ui_font)
FR_PRIVATE = 0x10
BUNDLED_FONTS = ("Archivo.ttf", "Montserrat.ttf")
_registered_fonts = {}

POLL_MS = 25
LOG_INTERVAL_SECONDS = 30.0
# Default window sizes; fit_height() grows them when the content needs more
# (Archivo's metrics are taller than Segoe UI's, and the simulator adds rows).
WINDOW_SIZE = (1060, 840)
WINDOW_MIN_SIZE = (1000, 800)
SETUP_SIZE = (600, 850)
SETTINGS_GAP = 24               # px between the floating knob's box and Settings when they would overlap
SETTINGS_MIN_HEIGHT = 400       # px: Settings never shrinks below this to fit a small work area
SPI_GETWORKAREA = 0x0030
WS_OVERLAPPEDWINDOW = 0x00CF0000
SCREEN_MARGIN = 80              # taskbar and title bar
SETUP_NOTE_LINES = 3            # reserved for the Save confirmation, so it never clips
SETUP_NOTE_WRAP = 540
SETTINGS_GROUP_GAP = 28         # px right of each Settings choice group (Onshape mode, Reduced haptics, ...)
SETUP_SUBTITLE = ("Artwork, LEDs, Motion and the switcher background apply when saved. "
                  "Other changes need a reconnect or a restart.")
SETTINGS_TITLE = "Desk Dial Settings"
# r3.1 (Claude Design C1): the Settings window's pages, in the page list's order.
SETTINGS_PAGES = (("general", "General"), ("music", "Music"), ("windows", "Windows"),
                  ("home_assistant", "Home Assistant"), ("knob", "Knob"), ("apps", "Apps"))
# Pages with no use for the window's Save settings row (Home Assistant has its own Save; Apps applies at once),
# built on their first show.
SETTINGS_OWN_SAVE_PAGES = ("home_assistant", "apps")
# Settings "Switcher background" choices: (button text, picker_background value). The names are
# CAROUSEL.md section 11's: Frosted (the full-screen frost, the default) and No background.
PICKER_BACKGROUND_CHOICES = (("Frosted", "glass"), ("No background", "none"))
# Under the choices when the carousel runs on its plain-host fallback (CAROUSEL.md section 5).
PICKER_BACKGROUND_FALLBACK_NOTE = ("No background needs a window mode this PC did not allow; "
                                   "the switcher uses Frosted.")
SETUP_SAVED_NOTES = {
    # The live companion is the tray icon plus the floating knob: closing Settings keeps
    # both running, and only the tray's Quit ends it.
    True: ("Settings saved. Album artwork and LED style apply now, on the knob and the floating "
           "knob; button order when the knob reconnects. A Sonos speaker change takes effect "
           "after you quit Desk Dial from the tray and open it again."),
    False: ("Settings saved. Album artwork and LED style apply now; button order when the knob "
            "reconnects. A Sonos speaker change takes effect the next time live mode starts."),
}
DEFAULT_LED_STYLE = "color"   # "Colour"
# Settings "LEDs" choices: (button text, led_style value). ALIVE.md sections 2 and 10.2 [D16]:
# the labels are "Colour" and "Warm only"; the stored values stay "color" and "white".
LED_STYLE_CHOICES = (("Colour", "color"), ("Warm only", "white"))
# settings.json keys with no Settings UI, kept through load and Save only when present
# (ALIVE.md sections 3 and 10.2: the knob's LED drive and dither, for the hands-on tuning;
# K3 14.4: led_pink and led_vol_full, for the hardware window's PINK pick and U8 A/B).
LED_TUNING_KEYS = ("led_drive", "led_dither", "led_pink", "led_vol_full")
# Settings "Motion" (K3 14.3, copy settings.motion): (button text, motion value); "system" follows
# the Windows Animation effects setting.
MOTION_CHOICES = (("Match Windows", "system"), ("Full", "full"), ("Reduced", "reduced"))
MOTION_VALUES = tuple(value for _text, value in MOTION_CHOICES)
DEFAULT_MOTION = "system"
# Settings "Navigator" (r3 README section 5; DESKTOP_STAGE 24): the glass card that replaces the floating
# knob for an r3 knob. Auto-hide (4 s after the last input at Home and the space roots) / Pinned / Off.
NAVIGATOR_CHOICES = (("Auto-hide", "auto"), ("Pinned", "pinned"), ("Off", "off"))
NAVIGATOR_VALUES = tuple(value for _text, value in NAVIGATOR_CHOICES)
DEFAULT_NAVIGATOR = "auto"
# The status strip (K3 14.1; S01 12; BS:1373-1378): refreshed this often while Settings is open.
STRIP_REFRESH_MS = 1000
STRIP_TITLE_COLOR = "#9B9797"
STRIP_DETAIL_COLOR = SECONDARY
SONOS_SOURCE_PHRASES = {"queue": "Playing from the Sonos queue", "airplay": "Playing via AirPlay",
                        "radio": "Playing radio", "linein": "Playing line-in", "none": "Idle"}
# The simulator window's description per controller mode (a dev surface, never product copy;
# K3 2.1: every mode has one, so a new mode can never be a KeyError).
MODE_DESCRIPTIONS = {
    "home": "Turn for group volume. 1 Play or Pause · 2 Browse · 3 Tracks · 4 the window picker.",
    "recent": "Recently Added, one flat list. 1 Back · 2 Open on screen · 3 Play next · 4 Play.",
    "explorer": "The Music explorer is on screen. 1 Back · 2 Recently Added · 3 Favourite playlists · 4 Play.",
    "tracks": "Turn to Previous or Next. 1 Back · 2 Up next · 3 Seek · 4 Skip.",
    "seek": "Turn to move through the song in 5 s steps; it jumps after a short pause. 1 or 3 Back · 2 Up next.",
    "upnext": "Up next is on screen. Turn through the queue. 1 Back · 2 Shuffle · 3 Like · 4 Play.",
    "windows": "Turn to preview a window. 1 Back · 2 Snap left · 3 Snap right · 4 Switch.",
    "launcher": "Home (r3). Turn for group volume. 1 Music · 2 Windows · 3 Lights · 4 Play or Pause.",
    "lights": "Lights (r3). Turn for brightness, or temperature after 3. 1 Home · 2 Scenes · 3 Temperature · "
              "4 All off / Turn on.",
    "scenes": "Scenes (r3). Turn to choose. 1 Back to Lights · 4 Run.",
    "onshape": "Onshape (A0). Turn to zoom; hold 1 and turn to tilt, hold 2 and turn to orbit, hold 4 and turn to pan; "
               "tap 3 Undo; hold all four buttons 1 s for Home. The simulator never sends input.",
}
# A0 Onshape mode (ONSHAPE.md) is Settings > Apps' Onshape row since app profiles (APP_MODE_CHOICES below);
# settings.json `onshape_idle_ms` (the drag idle deadline) and `onshape_content_classes` (the browser content
# widget classes) have no UI.
# r4 (firmware 1.0.0-cc5.7; firmware HAPTICS.md): Settings > Knob sounds On / Off with a volume (default On, 100 %),
# Reduced haptics Off / On (the r4 section 7 fallbacks; walls stay) and Recalibrate motor. settings.json
# `knob_sounds` (bool), `knob_sound_volume` (0..100; Desk Dial 7.3.1, replacing the shown `knob_sound_level`),
# `reduced_haptics` (bool). Sent with each control of an r4 knob; never stored on the knob. An older knob ignores
# them. Knob sounds and the volume apply (and are saved) at once: the slider on release.
KNOB_SOUNDS_CHOICES = (("On", "on"), ("Off", "off"))
REDUCED_HAPTICS_CHOICES = (("Off", "off"), ("On", "on"))
# DD-BUG-040 (ID-SOUND-ALL): every interaction has a sound and a haptic; the note never claims silence.
KNOB_FEEL_NOTE = ("Every turn, wall and press has a sound and a haptic; the volume sets how loud. Reduced haptics: "
                  "softer steps, one pulse instead of a thump or buzz; the ends still stop the knob.")
# D-RECAL (user decision for v2.0.0): Settings > Knob does not show Recalibrate motor, because recalibration has
# never been rehearsed on hardware. The code path (RecalibrationGuard, Runtime.recalibrate_motor, the device's
# recalibrate command) stays; True shows the button and its Keep / Dismiss row again.
SHOW_RECALIBRATE = False
RECALIBRATE_NOTE = ("Recalibrating aligns the knob's motor again (about 10 s). Keep your hands off the knob; the "
                    "screens come back when it is done.")
# DD-BUG-051: a recalibration the knob refused because the motor direction came out reversed is shown in
# Settings with an explicit Keep / Dismiss; only Keep sends acceptDirection (a plain Recalibrate never does).
DIRECTION_CHANGED_NOTE = ("Recalibration kept the old calibration: the motor direction came out reversed, usually "
                          "because the knob moved during alignment. Press Recalibrate motor again with your hands off "
                          "the knob. Keep new direction only if you are sure nothing touched it.")
DIRECTION_KEEP_NOTE = "Recalibrating and accepting the new motor direction · keep your hands off the knob."
# Plan section 3c (S1 DD-C): Onshape mode moved to Settings > Apps, one row per app profile; the Knob page keeps
# this pointer. settings.json `app_modes` {id: off|manual|auto} (Onshape migrated from `onshape_mode`, which is
# kept in sync for one release so a rollback still reads it; every other app is Off until chosen), `app_rules`
# {id: {exe: [...], host: [...]}} (added to the profile's own detection; program names and bare hosts only, never
# a URL), `app_order` (ids, earlier wins a tie), `profile_updates` (off | daily) and `profile_updates_last`.
APPS_POINTER_NOTE = "Onshape and other apps: Settings › Apps."
APP_MODE_CHOICES = (("Off", "off"), ("Manual", "manual"), ("Auto", "auto"))
APP_MODES = tuple(value for _text, value in APP_MODE_CHOICES)
# The sidecar status `community` keeps its internal name; Settings shows it as "Not yet tested" (mapped from Karl's Mac
# profile and checked against the app's Windows docs, not tried by the author) until an owner confirms it.
APP_STATUS_BADGES = {"tested": "Tested", "community": "Not yet tested", "basic": "Basic"}
APP_SOURCE_LABELS = {"bundled": "Karl", "user": "Imported", "updates": "Updated"}
APP_ORDER_MAX = 64
APP_RULES_MAX = 32                  # per list, as the profile validator takes them
APP_ICON_SIZE = 24
APPS_INTRO = ("Each app profile sets what the knob and its buttons do in that app. Manual: turn it on from the "
              "tray’s App mode menu. Auto: on while the app is in front. Hold all four knob buttons for 1 s "
              "for Home.")
APPS_EMPTY = "No app profiles found."
APPS_NOT_DETECTED = "Not detected yet · add a program or website in Rules…"
APPS_IMPORT = "Import profile…"
APPS_OPEN_FOLDER = "Open profiles folder"
APPS_CHECK = "Check for updates"
APPS_FETCH_DAILY = "Fetch updated profiles from the Desk Dial repo (once a day)"
APPS_RULES = "Rules…"
APPS_IMPORTED = "Imported {name}."
APPS_IMPORTED_OFF = "Imported {name}. Choose Manual or Auto to use it."
# A re-import (an id that was already there, from any source) turns that app Off (S3 decision).
APPS_IMPORTED_REPLACED = "Imported {name}. It's Off: choose Manual or Auto to use it."
APPS_IMPORT_FAILED = "Couldn't import {file}: {problems}"
APPS_MORE = "(and {count} more)"
APPS_FOLDER_FAILED = "Couldn't open the profiles folder."
APPS_SAVE_FAILED = "Applied, but the settings file could not be written."
APPS_NO_LIBRARY = "App profiles aren't available."
RULES_TITLE = "Rules · {name}"
RULES_INTRO = ("Desk Dial picks {name} when one of these is in front. A program: its file name, such as "
               "Figma.exe. A website: its host, such as figma.com or *.figma.com, in Chrome, Edge, Brave, "
               "Vivaldi or Opera.")
RULES_PROGRAMS = "Programs"
RULES_WEBSITES = "Websites"
RULES_BUILT_IN = "Built in: {rules}"
RULES_NONE = "None added"
RULES_ADD = "Add"
RULES_REMOVE = "Remove"
RULES_DONE = "Done"
RULE_BAD_EXE = "Enter a program file name such as Figma.exe."
RULE_BAD_HOST = "Enter a website host such as figma.com or *.figma.com."
RULE_HOST_ONLY = "Kept the host only: {host}. Desk Dial never stores a web address."
RULE_FILE_ONLY = "Kept the file name only: {name}."
RULE_DUPLICATE = "That one is already in the list."
RULE_FULL = "A list holds up to 32 entries."
RULE_ADDED = "Added {value}."
RULE_REMOVED = "Removed {value}."
# The simulator's state picker (K3 16; BS:1352-1370): (SimControls field, label, (value, text) ...).
SIM_PICKER = (
    ("connected", "PC connection", ((True, "Connected"), (False, "Disconnected"))),
    ("source", "Playing source", (("queue", "Sonos queue"), ("airplay", "AirPlay"), ("radio", "Radio"),
                                  ("linein", "Line-in"), ("none", "Nothing"))),
    ("play_mode", "Sonos shuffle / repeat", (("NORMAL", "Off"), ("SHUFFLE", "Shuffle"),
                                             ("SHUFFLE_NOREPEAT", "Shuffle, no repeat"),
                                             ("REPEAT_ALL", "Repeat all"), ("REPEAT_ONE", "Repeat one"),
                                             ("SHUFFLE_REPEAT_ONE", "Shuffle, repeat one"))),
    ("pn", "Play next outcome", (("ok", "Queued"), ("slow", "Slow"), ("live", "Live timing"),
                                 ("proto", "Prototype timing"), ("partial", "Partial"), ("nothing", "Nothing"),
                                 ("changed", "Song changed"))),
    ("start", "Starting playback", (("ok", "Starts"), ("slow", "Slow"), ("fail", "Fails"),
                                    ("blocked", "Album blocked"))),
    ("seek", "Seek", (("ok", "Lands"), ("slow", "Slow"), ("slow5", "Slow 5 s"), ("noresume", "Never resumes"),
                      ("live", "Live timing"), ("fail", "Fails"))),
    ("like", "Like state", (("ok", "Known"), ("loading", "Not known yet"), ("fail", "Save fails"),
                            ("expired", "Sign-in expired"))),
    ("upnext", "Up next", (("normal", "Album"), ("loading", "Loading"), ("foreign", "From another app"),
                           ("longshuffle", "Sonos shuffle > 60"))),
    ("favs", "Favourite playlists", (("real", "Today (2)"), ("empty", "Empty"), ("many", "Many"))),
    ("recent", "Recently Added", (("normal", "Normal"), ("many", "Many"), ("empty", "Empty"),
                                  ("error", "Error"), ("expired", "Sign-in expired"))),
    ("art", "Artwork", (("full", "1200 px"), ("mixed", "Real library mix"), ("small", "Low-res"),
                        ("missing", "None"), ("loading", "Loading"), ("list", "Loading list"))),
    ("snap", "Snap outcome", (("ok", "Snaps"), ("hung", "Not responding"), ("move", "Couldn’t move"),
                              ("fit", "Can’t fit half"), ("integrity", "Pre-check fails"))),
    ("stage", "Stage", (("ok", "Opens"), ("refused", "Refused"), ("display", "Display change"))),
    ("ha", "Home Assistant", (("ok", "Connected"), ("slow", "Slow"), ("offline", "Offline"),
                              ("auth", "Token refused"), ("notset", "Not set up"))),
)
FAST_PATH_LOG_EVERY = 500       # DD-RES-016: the fast path logs its first failure, then one in this many
FAST_TOUCH_SECONDS = 10.0       # the stage's and the picker's note_touch (device warm-ups) at most this often from the fast path

# Mirror geometry: Knob Face device coordinates (LCD and ring centred on 170,170)
# drawn at MIRROR_SCALE around MIRROR_CENTRE on a fixed canvas.
MIRROR_SIZE = (478, 545)
MIRROR_CENTRE = (239, 220)
MIRROR_SCALE = 1.5
KNOB_CENTRE = 170
RING_RADIUS = 138               # rotate(i*6deg) translateY(-138px)
SEGMENT_WIDTH, SEGMENT_HEIGHT = 4, 10
DISC_RADIUS = 126               # the 252 px bezel disc
BUTTON_LEFT, BUTTON_TOP, BUTTON_SIZE, BUTTON_GAP, STRIP_HEIGHT = 49, 336, 44, 22, 3
LCD_NATIVE = 240
LCD_PIXELS = round(LCD_NATIVE * MIRROR_SCALE)
DEVICE_BG = "#141414"
DISC_FILL, DISC_EDGE = "#0a0a0a", "#262626"
SEGMENT_OFF = "#1f1f1f"
BUTTON_FILL, BUTTON_EDGE, STRIP_OFF = "#202020", "#2c2c2c", "#262626"
LCD_CACHE_SIZE = 12
OVERLAY_LCD_CACHE_SIZE = 8      # floating knob LCD images (up to ~600 px RGBA at 200 %)

# Knob Face optical mapping (OPTICAL_ALPHA, LED_FLOOR, LED_PALETTE, BUTTON_FACE,
# STRIP_MIN_ALPHA) and the ring/strip colour functions: knob_face (imported above).


def register_fonts(names=BUNDLED_FONTS):
    """Register the bundled fonts for this process only (GDI FR_PRIVATE).

    Call before any Tk font that uses them is created. Returns {file: count}
    (count 0 = not registered). Never raises.
    """
    if os.name != "nt":
        return dict(_registered_fonts)
    try:
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        add = gdi.AddFontResourceExW
        add.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
        add.restype = ctypes.c_int
    except (AttributeError, OSError):
        return dict(_registered_fonts)
    for name in names:
        if _registered_fonts.get(name):
            continue
        path = FONT_DIR / name
        try:
            _registered_fonts[name] = int(add(str(path), FR_PRIVATE, None)) if path.is_file() else 0
        except OSError:
            _registered_fonts[name] = 0
    return dict(_registered_fonts)


def ensure_ui_font(root):
    """Archivo when Tk can see it after private registration, else Segoe UI."""
    global UI_FAMILY
    register_fonts()
    try:
        available = "Archivo" in font.families(root)
    except Exception:          # TclError, or a stand-in root without Tk (the headless smoke check)
        available = False
    UI_FAMILY = "Archivo" if available else FALLBACK_FAMILY
    return UI_FAMILY


def label(parent, text="", size=11, color=TEXT, **kwargs):
    return tk.Label(parent, text=text, font=(UI_FAMILY, size), bg=parent.cget("bg"), fg=color, **kwargs)


def button(parent, text, command, **kwargs):
    return tk.Button(parent, text=text, command=command, bg=SURFACE, fg=TEXT, activebackground=HAIRLINE,
                     activeforeground=TEXT, relief="flat", borderwidth=0, padx=15, pady=8,
                     highlightthickness=RULE_WIDTH, highlightbackground=RULE, highlightcolor=TEXT,
                     font=(UI_FAMILY, 10), cursor="hand2", **kwargs)


def fit_height(window, width, height, margin=SCREEN_MARGIN, limit=None):
    """Grow a top-level ``window`` of ``width`` x ``height`` until its packed
    content fits, capped to the screen (and to ``limit`` px, when given: e.g. the
    work area's room, DD-BUG-020). Never shrinks it.

    Returns the new height, or None when nothing changed (content fits, the
    window is not a real Tk window, or Tk refused).
    """
    if not isinstance(window, tk.Wm):
        return None
    try:
        window.update_idletasks()
        needed = min(window.winfo_reqheight(), window.winfo_screenheight() - margin)
        if limit is not None:
            needed = min(needed, int(limit))
        if needed <= height:
            return None
        window.geometry(f"{width}x{needed}")
    except tk.TclError:
        return None
    return needed


def show_fitted(window, width, height, place=None):
    """Show a just-built top-level window already grown to fit (see fit_height).

    Call before Tk has processed any idle event for it: it is sized while
    withdrawn, so it never flashes at the default height first. ``place(window,
    width, height)``, when given, positions it at its fitted size while it is
    still withdrawn, so it never appears at another position first.
    """
    if not isinstance(window, tk.Wm):
        return None
    try:
        window.withdraw()
    except tk.TclError:
        return None
    grown = None
    try:
        grown = fit_height(window, width, height)
        return grown
    finally:
        if place is not None:
            try:
                place(window, width, grown or height)
            except Exception:
                _log.exception("Window could not be placed")
        try:
            window.deiconify()
        except tk.TclError:
            pass


def wrapped_lines(widget, text, size, width):
    """Lines ``text`` takes in UI_FAMILY at ``size`` pt, word-wrapped at ``width`` px
    (at this display's scaling, so the reservation holds at any DPI)."""
    spec = (UI_FAMILY, size)
    lines, current = 1, ""
    for word in str(text).split():
        trial = f"{current} {word}" if current else word
        if current and int(widget.tk.call("font", "measure", spec, "-displayof", widget, trial)) > width:
            lines, current = lines + 1, word
        else:
            current = trial
    return lines


NOTE_MIN_WRAP = 200             # px: a note never wraps narrower than this (a stand-in or unmapped parent)
NOTE_CHROME = 6                 # px: a Label's padx + borderwidth on both sides when it cannot be read


def note_wrap_width(available, inset=0, chrome=NOTE_CHROME, limit=SETUP_NOTE_WRAP):
    """FU-1: the wraplength for a note shown in a container ``available`` px wide, of which ``inset`` px
    go to its group's padding. The note's requested width (wrap + ``chrome``) then fits the container, so
    Tk's packer never squeezes the label (a squeezed label centres its text and clips both ends: the Knob
    page's notes inside its ScrollPage, narrower by the scrollbar). ``limit`` caps it at the usual wrap;
    an unknown width (1 px, unmapped) keeps ``limit``."""
    try:
        available = int(available)
    except (TypeError, ValueError):
        return limit
    if available <= 1:
        return limit
    return max(NOTE_MIN_WRAP, min(limit, available - int(inset) - int(chrome)))


def label_chrome(widget):
    """Horizontal px a Label adds around its text (padx, borderwidth, highlight, both sides)."""
    try:
        return 2 * sum(int(float(widget.cget(option))) for option in ("padx", "borderwidth", "highlightthickness"))
    except (tk.TclError, AttributeError, TypeError, ValueError):
        return NOTE_CHROME


def track_note_wrap(note, container, inset=0):
    """FU-1: keep ``note``'s wraplength at ``container``'s width (less ``inset``) as it is laid out and
    resized, so a note never gets wider than the page it is on. Left-anchored, so even a transient
    squeeze clips only the end of a line, never its start. Returns ``note``."""
    def fit(event=None):
        try:
            width = getattr(event, "width", None) if event is not None else container.winfo_width()
            wrap = note_wrap_width(width, inset, label_chrome(note))
            if int(float(note.cget("wraplength"))) != wrap:
                note.configure(wraplength=wrap)
        except (tk.TclError, AttributeError, TypeError, ValueError):
            pass
    try:
        note.configure(anchor="w", justify="left")
        container.bind("<Configure>", fit, add="+")
    except (tk.TclError, AttributeError, TypeError):    # a stand-in widget: the fixed wrap stays
        pass
    fit()
    return note


def refit_height(window, size, limit=None):
    """Grow ``window`` again after its content grew (a longer message), never shrinking.

    ``size`` is the [width, height] the window was last given (updated in
    place); once the window is mapped its real size is used instead, so a size
    the user chose is kept unless the content no longer fits it. ``limit``: the
    most client height the window may grow to (a number, or a callable giving one
    or None), e.g. Settings' room in the work area so it never grows under the
    taskbar (DD-BUG-020).
    """
    if not isinstance(window, tk.Wm):
        return None
    try:
        if window.winfo_ismapped():
            size[:] = [window.winfo_width(), window.winfo_height()]
    except tk.TclError:
        return None
    if callable(limit):
        try:
            limit = limit()
        except Exception:
            limit = None
    grown = fit_height(window, *size, limit=limit)
    if grown:
        size[1] = grown
    return grown


def render_lcd(frame, artwork=None, window_icon=None, *, artwork2=False):
    """lcd_preview.render_lcd, imported on first use so a broken renderer only blanks the mirror."""
    from .lcd_preview import render_lcd as renderer
    return renderer(frame, artwork, window_icon, artwork2=artwork2)


def render_overlay_lcd(frame, artwork=None, window_icon=None, *, artwork2=False, pixels=LCD_NATIVE,
                       hires_cover=None, hires_icon=None):
    """The floating knob's LCD: lcd_preview.render_lcd drawn directly at ``pixels`` (never an
    upscale of the 240 px image), RGBA ``pixels`` x ``pixels``. Above 240 px the hi-res cover
    and icon are used when given (same layout, higher fidelity)."""
    from PIL import Image
    from .lcd_preview import render_lcd as renderer
    options = {"scale": pixels / LCD_NATIVE}
    if pixels > LCD_NATIVE:
        options.update(hires_cover=hires_cover, hires_icon=hires_icon)
    if artwork2:
        options["artwork2"] = True
    image = renderer(frame, artwork, window_icon, **options).convert("RGBA")
    if image.size != (pixels, pixels):   # a renderer that rounds differently: fit, never crop
        image = image.resize((pixels, pixels), Image.Resampling.LANCZOS)
    return image


def rects_overlap(first, second):
    """Whether two (x, y, width, height) rectangles share any pixel."""
    if not first or not second:
        return False
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return aw > 0 and ah > 0 and bw > 0 and bh > 0 and ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def settings_origin(work, size, avoid=None, gap=SETTINGS_GAP, frame=(0, 0)):
    """Where Settings opens in the floating-knob app (FLOATING_KNOB.md section 9.12): the
    (x, y) of a window whose client area is ``size`` (width, height) and whose title bar and
    borders add ``frame`` (width, height) (``wm geometry +x+y`` places that outer rectangle),
    centred on the primary work area ``work`` (left, top, right, bottom). When that would
    overlap ``avoid`` (the floating knob's (x, y, width, height), always on top), it moves
    right of it by ``gap``, as far as the work area allows. The outer rectangle stays inside
    the work area whenever it fits, and is never above or left of it."""
    left, top, right, bottom = (int(v) for v in work)
    outer_width, outer_height = int(size[0]) + int(frame[0]), int(size[1]) + int(frame[1])
    x = left + max(0, (right - left - outer_width) // 2)
    y = top + max(0, (bottom - top - outer_height) // 2)
    if rects_overlap((x, y, outer_width, outer_height), avoid):
        ax, _ay, aw, _ah = (int(v) for v in avoid)
        x = max(left, min(max(x, ax + aw + gap), right - outer_width))
    return x, y


def settings_client_height(work, height, frame=(0, 0), minimum=SETTINGS_MIN_HEIGHT):
    """The Settings client height that keeps the whole window (``frame`` added) inside the
    work area's height: ``height`` when it fits, else the room left (never below ``minimum``,
    never above ``height``). The Save and Authorize row is packed at the bottom first, so a
    shorter window squeezes the rows above it, never those buttons."""
    room = int(work[3]) - int(work[1]) - int(frame[1])
    height = int(height)
    return height if height <= room else min(height, max(int(minimum), room))


def settings_height_limit(work, frame=(0, 0), minimum=SETTINGS_MIN_HEIGHT):
    """The most client height Settings may grow to (DD-BUG-020): the work area's room with the
    title bar and borders (``frame``) added, never below ``minimum``; None without a work area.
    refit_height takes it, so a page change or a long note never grows Settings under the
    taskbar (the Knob page scrolls instead)."""
    if not work:
        return None
    return max(int(minimum), int(work[3]) - int(work[1]) - int(frame[1]))


def scroll_fraction_for(top, bottom, content, view, first):
    """The yview fraction that brings a row spanning ``top``..``bottom`` px of ``content`` px into a
    ``view`` px viewport whose first visible fraction is ``first``; None when it is already fully
    visible or nothing scrolls (DD-BUG-020: Settings > Knob scrolls to a focused row)."""
    content, view = int(content), int(view)
    if content <= 0 or view <= 0 or content <= view:
        return None
    shown = float(first) * content
    if top >= shown and bottom <= shown + view:
        return None
    start = top if top < shown else bottom - view
    start = max(0, min(content - view, start))
    return start / content


class ScrollPage:
    """A Settings page whose rows scroll when the window is too short for them (DD-BUG-020: the
    Knob page's sounds row, volume slider and Recalibrate were clipped at 100-150 % scaling).
    ``outer`` is what is packed and forgotten as the page; rows are built in ``inner``. The canvas
    asks for the rows' full height, so Settings still grows to fit them when the work area has
    room; when it has not (the window is clamped to the work area), Tk's packer shrinks the canvas
    and a scrollbar and the mouse wheel reach the rest. Nothing is hidden: every row stays
    reachable at every scaling."""

    WHEEL_UNITS = 3

    def __init__(self, parent, bg):
        self.outer = tk.Frame(parent, bg=bg)
        self._bar_shown = False
        self._requested = None
        try:
            self.canvas = tk.Canvas(self.outer, bg=bg, highlightthickness=0, borderwidth=0, yscrollincrement=12)
            self.bar = tk.Scrollbar(self.outer, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=self.bar.set)
            self.inner = tk.Frame(self.canvas, bg=bg)
            self._item = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
            self.canvas.pack(side="left", fill="both", expand=True)
        except (tk.TclError, AttributeError, TypeError):
            # No scrolling canvas (a stand-in parent): the rows go in the page frame itself, as before.
            self.canvas = self.bar = None
            self.inner = self.outer
            return
        self.inner.bind("<Configure>", self._sync, add="+")
        self.canvas.bind("<Configure>", self._sync, add="+")
        try:
            self.outer.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")
        except (tk.TclError, AttributeError):
            pass

    def scrollable(self):
        """True when the rows are taller than the shown viewport."""
        if self.canvas is None:
            return False
        try:
            return int(self.inner.winfo_reqheight()) > int(self.canvas.winfo_height()) > 1
        except (tk.TclError, TypeError, ValueError):
            return False

    def _sync(self, _event=None):
        """Keep the canvas's request at the rows' height, the rows at the canvas's width, the
        scroll region at the rows' size, and the scrollbar shown only while it is needed."""
        if self.canvas is None:
            return
        try:
            content = int(self.inner.winfo_reqheight())
            if content != self._requested:
                self._requested = content
                self.canvas.configure(height=content)
            width = int(self.canvas.winfo_width())
            if width > 1:
                self.canvas.itemconfigure(self._item, width=width)
            self.canvas.configure(scrollregion=(0, 0, max(width, 1), content))
            need = self.scrollable()
            if need and not self._bar_shown:
                self.bar.pack(side="right", fill="y", before=self.canvas)
                self._bar_shown = True
            elif not need and self._bar_shown:
                self.bar.pack_forget()
                self.canvas.yview_moveto(0)
                self._bar_shown = False
        except (tk.TclError, TypeError, ValueError):
            pass

    def _wheel(self, event):
        """The mouse wheel anywhere in Settings scrolls this page while it is shown and scrolls."""
        try:
            if not self.outer.winfo_ismapped() or not self.scrollable():
                return None
            delta = int(getattr(event, "delta", 0) or 0)
        except (tk.TclError, TypeError, ValueError):
            return None
        if delta:
            self.canvas.yview_scroll(-self.WHEEL_UNITS if delta > 0 else self.WHEEL_UNITS, "units")
        return "break"

    def see(self, widget):
        """Scroll so ``widget`` (a row inside ``inner``) is fully visible, e.g. a focused field."""
        if self.canvas is None:
            return
        try:
            top = int(widget.winfo_rooty()) - int(self.inner.winfo_rooty())
            bottom = top + int(widget.winfo_height())
            first = float(self.canvas.yview()[0])
            fraction = scroll_fraction_for(top, bottom, int(self.inner.winfo_reqheight()),
                                           int(self.canvas.winfo_height()), first)
        except (tk.TclError, TypeError, ValueError, IndexError):
            return
        if fraction is not None:
            self.canvas.yview_moveto(fraction)


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def window_frame_extent(dpi=None):
    """(width, height) a Tk toplevel's title bar and borders add to its client area, i.e. to
    the rectangle ``wm geometry +x+y`` positions: AdjustWindowRectExForDpi of
    WS_OVERLAPPEDWINDOW at ``dpi`` (the system DPI when None). (0, 0) when unknown."""
    if os.name != "nt":
        return 0, 0
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        rect = _Rect(0, 0, 0, 0)
        try:
            adjust = user32.AdjustWindowRectExForDpi
            adjust.argtypes = (ctypes.POINTER(_Rect), ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint)
            adjust.restype = ctypes.c_int
            if dpi is None:
                system_dpi = user32.GetDpiForSystem
                system_dpi.argtypes, system_dpi.restype = (), ctypes.c_uint
                dpi = int(system_dpi())
            done = adjust(ctypes.byref(rect), WS_OVERLAPPEDWINDOW, 0, 0, int(dpi))
        except AttributeError:        # before Windows 10 1607: the system DPI
            adjust = user32.AdjustWindowRectEx
            adjust.argtypes = (ctypes.POINTER(_Rect), ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
            adjust.restype = ctypes.c_int
            done = adjust(ctypes.byref(rect), WS_OVERLAPPEDWINDOW, 0, 0)
        if done and rect.right >= rect.left and rect.bottom >= rect.top:
            return rect.right - rect.left, rect.bottom - rect.top
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return 0, 0


def primary_work_area(window=None):
    """The primary monitor's work area (left, top, right, bottom) in this process's pixels
    (SPI_GETWORKAREA); the screen size from Tk (or None) when that is unavailable."""
    if os.name == "nt":
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            query = user32.SystemParametersInfoW
            query.argtypes = (ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint)
            query.restype = ctypes.c_int
            rect = _Rect()
            if query(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0) and rect.right > rect.left and rect.bottom > rect.top:
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
    if window is None:
        return None
    try:
        return 0, 0, int(window.winfo_screenwidth()), int(window.winfo_screenheight())
    except (tk.TclError, AttributeError, TypeError, ValueError):
        return None


class AppIconApi:
    """The Win32 calls behind the Tk windows' app icon, declared on a private user32 WinDLL
    with x64-correct prototypes (handles are pointer-sized; LPARAM/LONG_PTR are ssize_t)."""

    def __init__(self):
        self._user32 = None

    def _u(self):
        if self._user32 is None:
            u = ctypes.WinDLL("user32", use_last_error=True)
            u.LoadImageW.restype = ctypes.c_void_p
            u.LoadImageW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_uint)
            u.SendMessageW.restype = ctypes.c_ssize_t
            u.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
            u.SetClassLongPtrW.restype = ctypes.c_size_t
            u.SetClassLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
            u.GetSystemMetrics.restype, u.GetSystemMetrics.argtypes = ctypes.c_int, (ctypes.c_int,)
            try:
                u.GetDpiForWindow.restype, u.GetDpiForWindow.argtypes = ctypes.c_uint, (ctypes.c_void_p,)
                u.GetSystemMetricsForDpi.restype = ctypes.c_int
                u.GetSystemMetricsForDpi.argtypes = (ctypes.c_int, ctypes.c_uint)
            except AttributeError:
                pass                     # before Windows 10 1607: GetSystemMetrics only
            self._user32 = u
        return self._user32

    def icon_sizes(self, hwnd):
        """(big, small) icon px for the window's DPI: SM_CXICON and SM_CXSMICON."""
        u = self._u()
        try:
            dpi = int(u.GetDpiForWindow(hwnd))
        except (AttributeError, OSError):
            dpi = 0
        sizes = []
        for metric, default in ((SM_CXICON, 32), (SM_CXSMICON, 16)):
            size = 0
            if dpi > 0:
                try:
                    size = int(u.GetSystemMetricsForDpi(metric, dpi))
                except (AttributeError, OSError):
                    size = 0
            if size <= 0:
                size = int(u.GetSystemMetrics(metric))
            sizes.append(size if size > 0 else default)
        return tuple(sizes)

    def load(self, path, size):
        """LoadImageW(NULL, path, IMAGE_ICON, size, size, LR_LOADFROMFILE): the .ico frame drawn
        for that size (PNG-compressed frames included). An HICON (int) or None."""
        return self._u().LoadImageW(None, str(path), IMAGE_ICON, int(size), int(size), LR_LOADFROMFILE) or None

    def set_window_icon(self, hwnd, which, handle):
        self._u().SendMessageW(hwnd, WM_SETICON, which, handle)

    def set_class_icon(self, hwnd, index, handle):
        self._u().SetClassLongPtrW(hwnd, index, handle)


class AppWindowIcons:
    """APP_ICON.md item 3 on Windows. Every mapped Tk toplevel (``<Map>`` of the Toplevel and Tk
    class tags) gets the designer's .ico frames for its own DPI: WM_SETICON ICON_BIG at
    SM_CXICON and ICON_SMALL at SM_CXSMICON, so the title bar and the taskbar button show the
    hand-tuned small drawing at 16-24 px and the regular one from 32 px. They are loaded with
    LoadImageW because Tk 8.6 cannot read the PNG-compressed frames (``wm iconbitmap`` falls
    back to the 16 px frame stretched to 32 px). The first mapped toplevel also sets the
    TkTopLevel class icons (GCLP_HICON, GCLP_HICONSM), so a later window starts with them.
    The HICONs are cached per size and kept for the process lifetime (windows and the class
    use them). ``api`` is AppIconApi (tests pass a stand-in)."""

    def __init__(self, path=APP_ICON_ICO, api=None):
        self.path = Path(path)
        self.api = api if api is not None else AppIconApi()
        self.handles = {}
        self.class_icons = False
        self.windows = 0
        self.failures = 0

    def _icon(self, size):
        if size not in self.handles:
            self.handles[size] = self.api.load(self.path, size)
        return self.handles[size]

    def apply(self, hwnd):
        """The icons for the toplevel frame ``hwnd`` (a Tk wrapper). Raises when the .ico did not load."""
        big_size, small_size = self.api.icon_sizes(hwnd)
        big, small = self._icon(big_size), self._icon(small_size)
        if not big or not small:
            raise OSError(f"LoadImageW gave no icon from {self.path.name} at {big_size}/{small_size} px")
        self.api.set_window_icon(hwnd, ICON_BIG, big)
        self.api.set_window_icon(hwnd, ICON_SMALL, small)
        if not self.class_icons:
            self.api.set_class_icon(hwnd, GCLP_HICON, big)
            self.api.set_class_icon(hwnd, GCLP_HICONSM, small)
            self.class_icons = True
        self.windows += 1
        return big_size, small_size

    def on_map(self, event):
        """``<Map>`` of a toplevel: its frame (``wm frame``, the wrapper once mapped) gets the
        icons. Never raises; the first failure is logged."""
        widget = getattr(event, "widget", None)
        if not isinstance(widget, tk.Wm):
            return
        try:
            hwnd = int(widget.wm_frame(), 16)
            if hwnd:
                self.apply(hwnd)
        except Exception:
            self.failures += 1
            if self.failures == 1:
                _log.warning("App icon could not be set on a window", exc_info=True)


def apply_app_icon(root, photo_image=None, window_icons=None):
    """APP_ICON.md item 3, once on the root before any Toplevel exists, so the root, Settings
    and every Toplevel (title bar and taskbar button) show the app icon.

    - ``iconphoto(True, 256 px, 32 px)`` alone: Tk's first default icon registers the
      TkTopLevel class with the exact 32 px frame. ``iconbitmap(default=nano-d-app.ico)`` is
      not called: Tk 8.6 cannot read its PNG-compressed frames, and it would register the
      16 px frame stretched to 32 px and send the photos to the TkChild class instead.
    - Windows: ``<Map>`` of the Toplevel and Tk class tags runs ``window_icons.on_map``
      (AppWindowIcons), which gives each mapped window the .ico's own frames at its DPI.

    Paths come from APP_DIR (the bundle when frozen). No AppUserModelID is set. Never raises;
    returns what was applied. ``photo_image(path)`` makes a Tk photo and ``window_icons`` is
    the AppWindowIcons (tests pass stand-ins)."""
    applied = {"iconphoto": False, "windowIcons": False}
    try:
        make = photo_image or (lambda path: tk.PhotoImage(master=root, file=str(path)))
        photos = [make(path) for path in APP_ICON_PHOTOS]
        root.iconphoto(True, *photos)
        root._nanod_app_icons = photos   # Tk forgets a photo image once Python frees it
        applied["iconphoto"] = True
    except Exception:
        _log.warning("App photo icons could not be set", exc_info=True)
    try:
        if window_icons is None and os.name == "nt":
            window_icons = AppWindowIcons()
        if window_icons is not None:
            for tag in ("Toplevel", "Tk"):
                root.bind_class(tag, "<Map>", window_icons.on_map, add="+")
            root._nanod_window_icons = window_icons
            applied["windowIcons"] = True
    except Exception:
        _log.warning("App window icons could not be bound", exc_info=True)
    return applied


def _close_quietly(resource):
    """close() a provider or service on a failure path; its own error is only logged."""
    close = getattr(resource, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        _log.exception("%s did not close cleanly", type(resource).__name__)


# ------------------------------------------------------------- desktop v7 wiring
class AliveSimulatedDevice(SimulatedDevice):
    """The simulator's knob (K3 16 "PC connection"): a presentation-5 knob that also reports
    ``alive``, so the simulator's mirror and the floating knob run the v7 engine. No port."""
    alive = True
    closed = False
    COMMANDS_KEPT = 200

    def submit(self, *command):
        super().submit(*command)
        if len(self.commands) > self.COMMANDS_KEPT:     # a simulator session runs for hours
            del self.commands[:-self.COMMANDS_KEPT]

    def sync(self):
        want = bool(self.controls.connected)
        if want == self.connected:
            return
        self.connected = want
        if want:
            self.events.put({"kind": "connected",
                             "capabilities": {"controlCenter": 1, "presentation": self.presentation, "diag": 0,
                                              "alive": {"version": 1, "fps": 60, "drive": 150}}})
        else:
            self.events.put({"kind": "disconnected", "message": "Knob disconnected"})


class FastPath:
    """The serial reader's input fast path (K4 5.3, 22 Q3; K2 10.3 item 1). ``handle(kind,
    values, t)`` runs on the DeviceBridge's reader thread for each ``position``, ``limit`` and
    ``button`` event, stamped ``t`` (``time.perf_counter()`` at the read), before the event is
    queued for the Tk tick. It only posts: ``overlay.post_input`` (a lock and PostMessageW) and,
    while ``stage_open``, ``stage.position`` (a lock and SetEvent). A knob touch also warms the
    stage device and the picker's GPU chrome device (``note_touch`` on ``stage`` and ``windows``,
    together, at most once per FAST_TOUCH_SECONDS: ``_warm``). The Tk thread keeps
    ``button_order``, ``stage_open`` and ``windows`` (the runtime's picker, when it can warm)
    current. Never raises into the reader.

    A0 (ONSHAPE.md): every knob event also goes to the Onshape injector (``onshape``, a queue put;
    it acts only for its own control), including ``release``, ``hold``, ``ready`` and the lost-knob
    kinds (``disconnected`` / ``released`` / ``error`` / ``closed``: every held input goes up). While
    ``onshape_state`` is ``pending`` or ``active`` the floating knob and the Navigator get no input."""

    # The reader-thread kinds (install_fast_path): input first, then the kinds only Onshape needs.
    INPUT_KINDS = ("position", "limit", "button")
    ONSHAPE_KINDS = ("release", "hold", "ready", "disconnected", "released", "error", "closed")

    def __init__(self, overlay=None, stage=None, clock=time.perf_counter, windows=None, navigator=None):
        self.overlay = overlay
        self.navigator = navigator      # r3 Navigator: a turn shows it at once, a press fills its key
        self.stage = stage
        self.windows = windows          # WindowsAdapter (note_touch: the picker's GPU chrome, CAROUSEL.md 12.4)
        self.clock = clock
        self.button_order = [0, 1, 2, 3]
        self.stage_open = False
        self.posted = 0
        self.failures = 0
        self._touched = None
        self.onshape = None             # onshape.OnshapeInjector (the Tk tick keeps it current)
        self.onshape_state = "off"      # off | pending | active (the Tk tick keeps it current)

    def handle(self, kind, values, t=None):
        t = self.clock() if t is None else t
        try:
            control_id = values.get("id")
            overlay = self.overlay
            injector = self.onshape
            if injector is not None and (kind in self.ONSHAPE_KINDS or kind in self.INPUT_KINDS):
                try:
                    injector.post(kind, values)          # enqueue only: SendInput runs on NanoD-onshape
                except Exception:
                    self._failed("Onshape injector")
            if kind in self.ONSHAPE_KINDS:
                return False
            if self.onshape_state != "off" and kind in self.INPUT_KINDS:
                self.posted += 1
                return True                              # Onshape: no floating knob, no Navigator
            if kind == "position":
                position = values.get("position", values.get("p"))
                delta = values.get("delta")
                if overlay is not None and type(position) is int:
                    overlay.post_input("position", (position, delta if type(delta) is int else 0), control_id, t)
                stage = self.stage
                if stage is not None and self.stage_open and type(position) is int:
                    stage.position(control_id, position, t)
                self._navigator("turn")
            elif kind == "limit":
                direction = values.get("dir")
                if overlay is not None and direction in (-1, 1):
                    overlay.post_input("limit", direction, control_id, t)
                self._navigator("turn")
            elif kind == "button":
                raw = values.get("button", values.get("index"))
                order = self.button_order
                if overlay is not None and raw in order:
                    overlay.post_input("press", order.index(raw), control_id, t)
                if raw in order:
                    self._navigator("press", order.index(raw))
            else:
                return False
            self.posted += 1
            self._warm(t)
            return True
        except Exception:
            self._failed("knob event")
            return False

    def _failed(self, where):
        """Count a fast-path failure and log it (DD-RES-016): the first one, then one in every
        FAST_PATH_LOG_EVERY, at WARNING with the traceback (call inside ``except``). Rate-limited by
        count so the reader thread never floods app.log; ``failures`` is reported by the Tk tick
        (``failure_counts['fast-path']``) and ``status()``. Never raises."""
        self.failures += 1
        count = self.failures
        if count == 1 or count % FAST_PATH_LOG_EVERY == 0:
            try:
                _log.warning("Knob fast path failed (%s; %d failure(s) so far): the floating knob or the "
                             "Navigator may not follow the knob", where, count, exc_info=True)
            except Exception:
                pass

    def status(self):
        """status.json: the fast path's counters (DD-RES-016)."""
        return {"posted": self.posted, "failures": self.failures}

    def _navigator(self, kind, slot=None):
        """r3 Navigator (README section 5): only posts (a lock, SetEvent); never raises."""
        nav = self.navigator
        if nav is None:
            return
        try:
            if kind == "press":
                nav.note_press(slot)
            else:
                nav.note_turn()
        except Exception:
            self._failed("Navigator " + str(kind))

    def _warm(self, t):
        """A knob touch (K4 4.2, AR-19): the stage's device and the picker's GPU chrome device
        (CAROUSEL.md 12.4) are warmed together, at most once per FAST_TOUCH_SECONDS, so the picker is
        never warmed more often than the stage. Both calls only post to their own threads (each
        makes its device there or on its own worker), so the reader thread never waits for a device
        and holds the GIL only for the call itself (G1-5). A failing warm-up is counted in
        ``failures`` and never stops the other one."""
        stage, windows = self.stage, self.windows
        if stage is None and windows is None:
            return
        if self._touched is not None and t - self._touched < FAST_TOUCH_SECONDS:
            return
        self._touched = t
        for target in (stage, windows):
            if target is not None:
                try:
                    target.note_touch()
                except Exception:
                    self._failed("warm-up")


def install_fast_path(device, fast):
    """Wrap the DeviceBridge's ``_emit`` (reader thread) so every input event reaches ``fast``
    first, stamped at the read; everything else, and the event itself, is queued as before."""
    emit = getattr(device, "_emit", None)
    if not callable(emit) or getattr(emit, "_nanod_fast_path", False):
        return False

    def fast_emit(kind, **values):
        if kind in FastPath.INPUT_KINDS or kind in FastPath.ONSHAPE_KINDS:
            fast.handle(kind, values, time.perf_counter())
        return emit(kind, **values)
    fast_emit._nanod_fast_path = True
    device._emit = fast_emit
    return True


def firmware_version(device):
    """The knob's firmware version string (``settings.firmwareVersion`` in the inventory the bridge
    wrote at connect, ``device.backup_path``), or None. Only that one field is read."""
    path = getattr(device, "backup_path", None)
    if not path:
        return None
    key = str(path)
    if key in _FIRMWARE_VERSIONS:
        return _FIRMWARE_VERSIONS[key]
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle).get("settings", {}).get("firmwareVersion")
    except (OSError, ValueError, AttributeError, TypeError):
        value = None
    value = value if isinstance(value, str) and 0 < len(value) <= 40 else None
    if len(_FIRMWARE_VERSIONS) > 16:
        _FIRMWARE_VERSIONS.clear()
    _FIRMWARE_VERSIONS[key] = value
    return value


_FIRMWARE_VERSIONS = {}          # inventory path -> version (one read per connection)

# FW-PUB-004: Desk Dial's own version is desktop-version.txt's ProductVersion (the public version of the Desk Dial +
# knob pair; FileVersion keeps its own series). The file sits in APP_DIR in a source checkout and is bundled there by
# Build-Desktop.ps1, so the frozen app reads the same string its exe resource carries.
APP_VERSION_FILE = APP_DIR / "desktop-version.txt"
_PRODUCT_VERSION = re.compile(r"StringStruct\(\s*'ProductVersion'\s*,\s*'([^']*)'\s*\)")
_APP_VERSION = []                # [version or None] once read


def app_version(text=None):
    """Desk Dial's public version (desktop-version.txt's ProductVersion), or None when the file or the field is
    missing. ``text`` parses that content instead of the file (and is not cached). Never raises."""
    if text is None:
        if _APP_VERSION:
            return _APP_VERSION[0]
        try:
            content = APP_VERSION_FILE.read_text(encoding="utf-8")
        except (OSError, ValueError):
            content = ""
    else:
        content = text
    match = _PRODUCT_VERSION.search(content or "")
    value = match.group(1).strip() if match else ""
    value = value if 0 < len(value) <= 40 else None
    if text is None:
        _APP_VERSION.append(value)
    return value


def write_settings(config):
    """Write settings.json atomically (DD-BUG-017): a temporary file in DATA_DIR, flushed and
    fsynced, then os.replace, so a crash or power loss leaves either the old or the new file, never
    a torn one. Raises OSError (callers report it); the temporary file never stays behind."""
    import tempfile
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = json.dumps(config, indent=2).encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=DATA_DIR, prefix=".settings-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, DATA_DIR / "settings.json")
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def read_settings_file():
    """settings.json as a mapping, or {} when there is none (DD-BUG-017). A UTF-8 BOM (PowerShell
    5.1 ``Set-Content -Encoding UTF8``) is accepted. A file that does not parse as a JSON object is
    renamed ``settings.json.bad-<time>`` and logged once, so the defaults written by the next Save
    never replace the owner's hand-edited file."""
    path = DATA_DIR / "settings.json"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError:                          # locked or denied: left alone, defaults for now
        _log.warning("settings.json could not be opened; defaults used")
        return {}
    except ValueError:                       # not UTF-8 at all: corrupt
        text = None
    if text is not None:
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    aside = path.with_name(f"settings.json.bad-{time.strftime('%Y%m%d-%H%M%S')}")
    counter = 1
    while aside.exists():
        aside = path.with_name(f"settings.json.bad-{time.strftime('%Y%m%d-%H%M%S')}-{counter}")
        counter += 1
    try:
        os.replace(path, aside)
        _log.warning("settings.json could not be read; kept as %s and defaults used", aside.name)
    except OSError:
        _log.warning("settings.json could not be read or set aside; defaults used")
    return {}


# DD-BUG-047: older builds shipped a fixed default room_uid and every Save wrote it into
# settings.json. A room_uid is kept only when this marker says the configured speaker reported it
# (_persist_pinned_room); any other room_uid is dropped once on load, and the speaker at the
# configured IPv4 then pins its own room again (SonosAdapter._context).
ROOM_UID_SOURCE_KEY = "room_uid_source"
ROOM_UID_FROM_SPEAKER = "speaker"
SONOS_NOT_CONFIGURED = "Enter your Sonos speaker's IPv4 address in Settings > Music."


def valid_speaker_ip(value):
    """True for a dotted IPv4 address (what SonosAdapter accepts); IPv6 and names are refused."""
    import ipaddress
    try:
        ipaddress.IPv4Address((value or "").strip())
        return True
    except (ValueError, TypeError, AttributeError):
        return False


CREDENTIALS_LOCKED_DETAIL = "Saved sign-ins could not be unlocked - sign in again."


def apply_speaker_ip(config, speaker_ip):
    """Store a Settings speaker IP; a different speaker un-pins the room (DD-BUG-047), so the new
    speaker's own room is used instead of a room id that belongs to the old one."""
    speaker_ip = (speaker_ip or "").strip()
    if speaker_ip != (config.get("speaker_ip") or ""):
        config["room_uid"] = ""
    config["speaker_ip"] = speaker_ip


class UnconfiguredSonos:
    """The live Sonos stand-in while no speaker IPv4 is configured: always offline with a hint,
    and every command fails with the same hint (never a crash, never a network request)."""
    host = ""
    room_uid = None
    last_recovery = None

    def __init__(self, message=SONOS_NOT_CONFIGURED):
        self.message = message

    def read_state(self, **_kwargs):
        return {"online": False, "error": self.message}

    def close(self):
        pass

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        from .sonos import SonosUnavailable
        message = self.message

        def unavailable(*_args, **_kwargs):
            raise SonosUnavailable(message)
        return unavailable


def _apple_signed_in(apple):
    """True when the Apple Music client has a Music user token (``has_credentials()``); a client
    without the method (the simulator) counts as signed in."""
    check = getattr(apple, "has_credentials", None)
    if not callable(check):
        return True
    try:
        return bool(check())
    except Exception:
        return False


def strip_model(runtime, *, firmware=None, speaker_ip="", credentials_locked=False, app=None):
    """The Settings status strip (K3 14.1; VOC settings.knob/sonos/apple copy; BS:1373-1378): three
    columns, each {name, ok, state, detail, action, key, primary}. ``key`` names the action for the
    window (knob_settings, troubleshoot, manual_ip, renew_signin, sign_in). FW-PUB-004: the Knob
    column's detail ends with Desk Dial's own version ``app`` when given, next to the knob's
    firmware version, so a bug report names both halves of the pair."""
    attached = bool(getattr(runtime, "device_connected", False))
    connected = bool(attached and getattr(runtime, "device_supported", False))
    if connected:
        knob = {"name": "Knob", "ok": True, "state": "Connected",
                "detail": f"USB · firmware {firmware}" if firmware else "USB",
                "action": "Knob settings…", "key": "knob_settings", "primary": False}
    elif attached:
        # DD-BUG-039: the knob is on USB but Desk Dial can't drive it: name the runtime's real cause,
        # never "Waiting for the knob on USB". Only a stock-firmware status asks for a reflash; F24
        # owned by another app is its own state; anything else (host control released, a device
        # error on a supported knob) is a neutral "Needs attention" with the runtime's status.
        status = str(getattr(runtime, "device_status", "") or "")
        if status.startswith("Stock firmware"):
            state, detail = "Firmware needed", status
        elif "F24" in status:
            state, detail = "Hotkey busy", status
        else:
            state, detail = "Needs attention", status or "Desk Dial can’t drive the knob yet · disconnect and reconnect"
        knob = {"name": "Knob", "ok": False, "state": state, "detail": detail,
                "action": "Troubleshoot…", "key": "troubleshoot", "primary": False}
    else:
        knob = {"name": "Knob", "ok": False, "state": "Not connected",
                "detail": "Waiting for the knob on USB. The knob’s own controls still work.",
                "action": "Troubleshoot…", "key": "troubleshoot", "primary": False}
    if app:
        knob["detail"] = f"{knob['detail']} · Desk Dial {app}"
    controller = getattr(runtime, "controller", None)
    state = getattr(controller, "state", None) or {}
    if state.get("online"):
        phrase = SONOS_SOURCE_PHRASES.get(state.get("source"), SONOS_SOURCE_PHRASES["none"])
        host = state.get("host") or speaker_ip or ""
        sonos = {"name": "Sonos", "ok": True, "state": state.get("room_label") or state.get("group_label") or "Sonos",
                 "detail": f"{phrase} · {host}" if host else phrase,
                 "action": "Set manual IP…", "key": "manual_ip", "primary": False}
    else:
        sonos = {"name": "Sonos", "ok": False, "state": "Not found", "detail": "Can’t reach Sonos on this network",
                 "action": "Set manual IP…", "key": "manual_ip", "primary": False}
    if getattr(runtime, "music_signin_expired", False):
        apple = {"name": "Apple Music", "ok": False, "state": "Sign-in expired",
                 "detail": "Like and Favourite playlists are paused until you sign in again.",
                 "action": "Renew sign-in…", "key": "renew_signin", "primary": True}
    elif not _apple_signed_in(getattr(runtime, "apple", None)):
        apple = {"name": "Apple Music", "ok": False, "state": "Not signed in",
                 "detail": "Sign in to use Recently Added, Favourite playlists and Like.",
                 "action": "Sign in…", "key": "sign_in", "primary": True}
        if credentials_locked:
            apple.update(state="Sign in again", detail=CREDENTIALS_LOCKED_DETAIL)
    else:
        apple = {"name": "Apple Music", "ok": True, "state": "Signed in", "detail": "Library and likes available",
                 "action": "Renew sign-in…", "key": "renew_signin", "primary": False}
    columns = [knob, sonos, apple]
    if hasattr(runtime, "ha"):
        columns.append(ha_strip_column(runtime))   # r3: only a runtime with the Home Assistant bridge
    return columns


def _count(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def ha_strip_column(runtime):
    """The Settings strip's Home Assistant column (Desk Dial r3; r3.1 copy): from the controller's
    view of the lights (``Controller.lights``) and the adapter's own ``read_state`` (area name, light
    count, why the area is unavailable; no I/O), never from the token. Key ``home_assistant`` opens
    the Home Assistant page."""
    column = {"name": "Home Assistant", "ok": False, "state": "Not connected",
              "detail": "Add your address and token below",
              "action": "Set up…", "key": "home_assistant", "primary": False}
    if getattr(runtime, "ha", None) is None:
        return column
    lights = getattr(getattr(runtime, "controller", None), "lights", None)
    if lights is None:
        return column
    column["action"] = "Home Assistant…"
    area = {}
    read = getattr(runtime.ha, "read_state", None)
    if callable(read):
        try:
            area = read() or {}
        except Exception:
            area = {}
    area = area if isinstance(area, dict) and area.get("area_id") else {}
    area_name = area.get("name") or "the area"
    if lights.online:
        scenes = _count(len(lights.scenes), "scene")
        if area:
            detail = f"{area.get('name') or 'Area'} · {_count(int(area.get('count') or 0), 'light')} · {scenes}"
        else:
            detail = f"{lights.name or 'Light'} · {scenes}"
        column.update(ok=True, state="Connected", detail=detail)
    elif lights.reason == "auth":
        column.update(state="Token rejected", detail="Create a long-lived access token in your Home Assistant profile.",
                      primary=True)
    elif lights.reason == "forbidden":   # DD-BUG-049: HTTP 403, usually an IP ban after failed logins
        column.update(state="Blocked by Home Assistant", detail=HA_FORBIDDEN_DETAIL, primary=True)
    elif lights.reason == "not_configured" or not lights.configured:
        pass
    elif lights.reason == "connecting" or not lights.known and lights.reason in ("", "connecting"):
        column.update(state="Connecting", detail="Looking for Home Assistant…")
    elif lights.reason == "unavailable" and area.get("detail") == "area_missing":
        column.update(state="Area not found", detail="Choose the area again below", primary=True)
    elif lights.reason == "unavailable" and area.get("detail") == "no_lights":
        column.update(state=f"No lights in {area_name}",
                      detail=f"Assign lights to {area_name} in Home Assistant")
    elif lights.reason == "unavailable" and area:
        column.update(state="Lights unavailable", detail=f"All lights in {area_name} are unavailable")
    elif lights.reason == "unavailable":
        column.update(state="Light unavailable", detail="Home Assistant reports the light as unavailable.")
    else:
        column.update(state="Not reachable", detail="Can’t reach Home Assistant on this network.")
    return column


def ha_form_values(url, light, scenes, token="", saved_token=False, area=""):
    """Validate the Home Assistant dialog (pure): returns the settings.json values
    {ha_base_url, ha_area, ha_light_entity, ha_scenes} or raises ValueError with the note to show.
    ``area`` (an area id, r3.1) is preferred; ``light`` (one light.… entity) is the single-light
    alternative when no area is chosen. ``scenes`` is the ordered selection [(entity_id, label)]
    (optional: the area's own scenes are listed automatically); a token is required unless one is
    saved."""
    from .home_assistant import normalize_base_url, normalize_scenes, valid_area, valid_entity
    base = normalize_base_url(url)
    area = (area or "").strip()
    light = (light or "").strip()
    if area and not valid_area(area):
        raise ValueError("Choose the area from the list (use Test connection)")
    if not area and not valid_entity(light, ("light",)):
        raise ValueError("Choose the area the knob controls, or one light.… entity")
    if not (token or "").strip() and not saved_token:
        raise ValueError("Paste a long-lived access token from your Home Assistant profile")
    chosen = normalize_scenes([{"entity_id": entity, "label": label} for entity, label in scenes])
    return {"ha_base_url": base, "ha_area": area, "ha_light_entity": "" if area else light, "ha_scenes": chosen}


def ha_area_choices(areas, current=""):
    """The dialog's area menu (pure): ([(area_id, "<area name> · 3 lights")], the preselected area id) —
    the configured area, else ``home_assistant.default_area``'s pick. A configured area Home Assistant
    no longer lists stays selectable (marked) so a Save never silently changes it."""
    from .home_assistant import default_area
    rows = [(area_id, name, count) for area_id, name, count in areas or ()]
    if current and current not in [row[0] for row in rows]:
        rows.append((current, f"{current} (not found)", 0))
    choices = [(area_id, f"{name} · {count} light{'' if count == 1 else 's'}") for area_id, name, count in rows]
    return choices, default_area(rows, current)


# ---------------------------------------------------------------- Settings > Home Assistant (r3.1 C1)
HA_DEFAULT_ADDRESS = "http://homeassistant.local:8123"
HA_INTRO = ("The knob controls every light in the area you choose, including lights you add later. The area’s "
            "scenes, scripts and automations appear in the knob’s Scenes list.")
HA_UNTESTED = "Not tested since the last change"
HA_NO_AREA = "your area"                 # DD-BUG-038: the area words before one is chosen (no room name)
HA_CHOOSE_AREA = "Choose an area"
HA_TOKEN_REJECTED = "Token rejected (401). Create a long-lived access token in your Home Assistant profile."
HA_TOKEN_FOR_ADDRESS = ("Paste the access token for this address. The saved token is only sent to the saved "
                        "Home Assistant address.")
HA_STATUS_MARKS = {"idle": TERTIARY, "testing": "#FFBE69", "ok": OK, "error": ERROR}
HA_LIGHT_DOTS = {"on": OK, "off": RULE, "unavailable": ERROR}
HA_SAVED_SECONDS = 2.5
HA_KINDS = {"scene": "SCENE", "script": "SCRIPT", "automation": "AUTOMATION"}


HA_CLEARTEXT_NOTE = ("The token travels unencrypted on your network; use https:// if Home Assistant has a "
                     "certificate.")


def ha_cleartext_note(address):
    """DD-SEC-005: the one-line note under the address when the token would cross the network in clear
    (http:// to a host other than this PC); '' for https://, a loopback host or an address that is not
    valid yet. http stays supported."""
    from urllib.parse import urlsplit
    import ipaddress
    try:
        parts = urlsplit((address or "").strip()) if isinstance(address, str) else None
        host = parts.hostname if parts is not None else None
    except ValueError:
        return ""
    if parts is None or parts.scheme.lower() != "http" or not host:
        return ""
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        return ""
    try:
        if ipaddress.ip_address(host).is_loopback:
            return ""
    except ValueError:
        pass
    return HA_CLEARTEXT_NOTE


HA_FORBIDDEN_DETAIL = ("Too many failed logins from this PC: remove its IP from ip_bans.yaml in Home Assistant, "
                       "then restart it.")


def ha_unreachable(address):
    return f"Can’t reach {address or 'an empty address'}. Check the address and that Home Assistant is running."


class HaSettingsModel:
    """The Settings window's Home Assistant page (Claude Design r3.1, C1) without Tk: the address, the
    token (typed only; a saved one is never shown), the area, the Test connection status, the live
    lists of the chosen area, the Save gate and Cancel. The Tk page only mirrors it."""

    def __init__(self, config, saved_token=False):
        config = config if isinstance(config, dict) else {}
        self.address = config.get("ha_base_url") or HA_DEFAULT_ADDRESS
        self.token = ""
        self.saved_token = bool(saved_token)
        self.saved_address = config.get("ha_base_url") or ""   # DD-BUG-037: where the saved token may go
        self.saved_area = config.get("ha_area") or ""
        self.area = self.saved_area
        self.status = "idle"                 # idle | testing | ok | error
        self.error = ""
        self.result = None                   # the last successful test_connection result
        self.tested_address = ""
        self.show_token = False
        self.saved_at = None
        self.saved_name = ""
        self.generation = 0                  # bumped by every edit and test: late results are dropped

    # ---- edits
    def edit_address(self, value):
        value = value if isinstance(value, str) else ""
        if value != self.address:
            self.address = value
            self._untested()

    def edit_token(self, value):
        value = value if isinstance(value, str) else ""
        if value != self.token:
            self.token = value
            self._untested()

    def _untested(self):
        """Any address / token edit: the last test no longer counts (Save waits for a new one)."""
        self.status, self.error, self.result = "idle", "", None
        self.generation += 1

    def toggle_token(self):
        self.show_token = not self.show_token

    def choose_area(self, area_id):
        """Changing the area keeps the test status (only the lists follow)."""
        if isinstance(area_id, str) and area_id:
            self.area = area_id

    def cancel(self):
        """Cancel reverts the area choice to the saved one."""
        self.area = self.saved_area or self._default()

    # ---- the test
    def saved_token_applies(self, address=None):
        """DD-BUG-037: the saved token is sent only to the saved address (both normalized); an edited
        address needs its token typed."""
        if not self.saved_token or not self.saved_address:
            return False
        from .home_assistant import normalize_base_url
        try:
            return (normalize_base_url((self.address if address is None else address) or "").lower()
                    == normalize_base_url(self.saved_address).lower())
        except ValueError:
            return False

    def begin_test(self, need_token=True):
        """Start a test: returns (address, None) to probe, or (None, error copy) when there is
        nothing to probe (then the status is already ``error``). The simulator's Home Assistant
        needs no token (``need_token`` False)."""
        from .home_assistant import normalize_base_url
        address = (self.address or "").strip()
        try:
            base = normalize_base_url(address)
        except ValueError:
            self.status, self.error, self.result = "error", ha_unreachable(address), None
            return None, self.error
        if need_token and not self.token.strip() and not self.saved_token_applies(address):
            self.error = HA_TOKEN_FOR_ADDRESS if self.saved_token else HA_TOKEN_REJECTED
            self.status, self.result = "error", None
            return None, self.error
        self.status, self.error, self.tested_address = "testing", "", address
        self.generation += 1
        return base, None

    def finish_test(self, result, generation=None):
        """The probe's answer; False (ignored) when an edit or a newer test came after it."""
        if generation is not None and generation != self.generation:
            return False
        result = result if isinstance(result, dict) else {}
        if result.get("ok"):
            self.status, self.error, self.result = "ok", "", result
            if self.area not in self.area_ids():
                self.area = self._default()
        else:
            self.status, self.result = "error", None
            outcome = result.get("outcome")
            if outcome == "auth":
                self.error = HA_TOKEN_REJECTED
            elif outcome == "forbidden":     # DD-BUG-049: the adapter's 403 copy, not "can't reach"
                self.error = result.get("message") or HA_FORBIDDEN_DETAIL
            else:
                self.error = ha_unreachable(self.tested_address)
        return True

    # ---- what the page shows
    def areas(self):
        return list((self.result or {}).get("areas") or [])

    def area_ids(self):
        return [row[0] for row in self.areas()]

    def _default(self):
        from .home_assistant import default_area
        return default_area(self.areas(), self.saved_area) or self.saved_area

    def area_name(self, area_id=None):
        area_id = self.area if area_id is None else area_id
        for row in self.areas():
            if row[0] == area_id:
                return row[1]
        return area_id or HA_NO_AREA

    def area_choices(self):
        """[(area_id, name)] for the Area menu; the saved area stays listed until a test shows the list."""
        rows = [(row[0], row[1]) for row in self.areas()]
        if not rows and self.area:
            rows = [(self.area, self.area_name())]
        return rows

    def test_label(self):
        return "Testing…" if self.status == "testing" else "Test connection"

    def cleartext_note(self):
        """The note under the address (DD-SEC-005); '' when the token stays encrypted or local."""
        return ha_cleartext_note(self.address)

    def status_line(self):
        """(text, square colour) of the status line."""
        if self.status == "testing":
            text = f"Connecting to {self.tested_address}…"
        elif self.status == "ok":
            version = (self.result or {}).get("version") or ""
            text = f"Connected · Home Assistant {version} · token valid" if version else \
                "Connected · Home Assistant · token valid"
        elif self.status == "error":
            text = self.error
        else:
            text = HA_UNTESTED
        return text, HA_STATUS_MARKS[self.status]

    def areas_note(self):
        """DD-BUG-010: after a successful test that could not read the area list (no WebSocket and a
        non-admin token: the template API is admin-only), the test's ``areas_note``; else ''."""
        if self.status != "ok" or self.areas():
            return ""
        note = (self.result or {}).get("areas_note")
        return note if isinstance(note, str) else ""

    def placeholder(self):
        """The text in place of the lists before a successful test ('' once they show); after a
        successful test with no readable area list, the reason (``areas_note``)."""
        if self.status == "ok":
            return self.areas_note()
        if self.status == "error":
            return f"Fix the connection to see what’s in {self.area_name()}."
        return f"Test the connection to see the lights and scenes in {self.area_name()}."

    def lists(self):
        """The two live lists of the chosen area (after a successful test): {lights_head, lights:
        [(name, value, dot colour, value colour)], lights_empty, scenes_head, scenes: [(name, KIND)],
        scenes_empty}; None before a successful test, or when the area list could not be read
        (``areas_note``: the placeholder shows why instead of an empty area)."""
        if self.status != "ok" or self.areas_note():
            return None
        details = ((self.result or {}).get("area_details") or {}).get(self.area) or {}
        name = self.area_name()
        lights = []
        for row in details.get("lights") or ():
            if not row.get("available"):
                lights.append((row.get("name", ""), "Unavailable", HA_LIGHT_DOTS["unavailable"], ERROR))
            elif row.get("on"):
                value = f"{row.get('bri')}% · {row.get('kelvin')} K" if row.get("kelvin") else f"{row.get('bri')}%"
                lights.append((row.get("name", ""), value, HA_LIGHT_DOTS["on"], SECONDARY))
            else:
                lights.append((row.get("name", ""), "Off", HA_LIGHT_DOTS["off"], SECONDARY))
        scenes = [(row.get("name", ""), HA_KINDS.get(row.get("type"), "SCENE")) for row in details.get("scenes") or ()]
        return {"lights_head": f"Lights in {name} · {len(lights)}", "lights": lights,
                "lights_empty": "" if lights else (f"No lights in {name} yet. Assign lights to this area in Home "
                                                   "Assistant and they appear here and on the knob automatically."),
                "scenes_head": f"Scenes, scripts and automations · {len(scenes)}", "scenes": scenes,
                "scenes_empty": "" if scenes else "No scenes, scripts or automations in this area."}

    # ---- Save
    @property
    def can_save(self):
        """Save is enabled only after a successful test (since the last address / token edit)."""
        return self.status == "ok" and bool(self.area)

    def save_values(self):
        """The settings.json values Save writes (``ha_scenes`` is left as it is); ValueError when
        Save is not allowed yet."""
        if not self.can_save:
            raise ValueError("Test the connection first")
        values = ha_form_values(self.address, "", [], self.token, self.saved_token_applies(), area=self.area)
        values.pop("ha_scenes", None)
        return values

    def mark_saved(self, now):
        self.saved_area = self.area
        self.saved_name = self.area_name()
        self.saved_at = now
        if self.token.strip():
            self.saved_token = True
        try:
            from .home_assistant import normalize_base_url
            self.saved_address = normalize_base_url(self.address)
        except ValueError:
            pass

    def saved_text(self, now):
        if self.saved_at is None or now - self.saved_at >= HA_SAVED_SECONDS:
            return ""
        return f"Saved · the knob now controls {self.saved_name}"


_APP_ID = re.compile(r"[a-z0-9_-]{1,11}")
_RULE_KINDS = (("exe", app_profiles.exe_rule_ok), ("host", app_profiles.host_rule_ok))


def valid_app_id(value):
    return isinstance(value, str) and bool(_APP_ID.fullmatch(value))


def normal_app_modes(value):
    """settings.json `app_modes`: {id: off|manual|auto}; anything else is dropped."""
    if not isinstance(value, dict):
        return {}
    return {pid: mode for pid, mode in value.items() if valid_app_id(pid) and mode in APP_MODES}


def normal_app_rules(value):
    """settings.json `app_rules`: {id: {exe: [...], host: [...]}} with bare program names and bare hosts only
    (``app_profiles.exe_rule_ok`` / ``host_rule_ok``), no duplicates, at most APP_RULES_MAX per list. A bad entry
    is dropped, never the whole setting (one bad rule would otherwise make the Library ignore them all)."""
    out = {}
    if not isinstance(value, dict):
        return out
    for pid, rules in value.items():
        if not valid_app_id(pid) or not isinstance(rules, dict):
            continue
        entry = {}
        for kind, check in _RULE_KINDS:
            items = rules.get(kind)
            if not isinstance(items, list):
                continue
            kept, seen = [], set()
            for item in items:
                if check(item) and item.lower() not in seen:
                    seen.add(item.lower())
                    kept.append(item)
            if kept:
                entry[kind] = kept[:APP_RULES_MAX]
        if entry:
            out[pid] = entry
    return out


def normal_app_order(value):
    if not isinstance(value, list):
        return []
    out = []
    for pid in value:
        if valid_app_id(pid) and pid not in out:
            out.append(pid)
    return out[:APP_ORDER_MAX]


def normal_app_settings(config):
    """The app-profile keys of a loaded settings mapping, validated in place (plan section 3c). Migration:
    `onshape_mode` (already normalised) becomes ``app_modes["onshape"]`` when the file has none, and
    `onshape_mode` then follows ``app_modes["onshape"]`` (kept in sync for one release: a rollback to the
    previous Desk Dial reads it). Unknown ids are kept here; ``prune_app_ids`` drops them once the profile
    library has loaded."""
    modes = normal_app_modes(config.get("app_modes"))
    if "onshape" not in modes:
        modes["onshape"] = normal_onshape_mode(config.get("onshape_mode"))
    config["app_modes"] = modes
    config["onshape_mode"] = modes["onshape"]
    config["app_rules"] = normal_app_rules(config.get("app_rules"))
    config["app_order"] = normal_app_order(config.get("app_order"))
    config["profile_updates"] = profile_updates.normal_setting(config.get("profile_updates"))
    config["profile_updates_last"] = profile_updates.normal_last(config.get("profile_updates_last"))
    return config


def prune_app_ids(config, known):
    """Drop, silently, the ids of profiles the loaded library doesn't have. Nothing is dropped when the library
    has nothing (it failed to load), and Onshape is always kept (its mode mirrors `onshape_mode`)."""
    known = set(known or ())
    if not known:
        return config
    known.add("onshape")
    config["app_modes"] = {k: v for k, v in (config.get("app_modes") or {}).items() if k in known}
    config["app_rules"] = {k: v for k, v in (config.get("app_rules") or {}).items() if k in known}
    config["app_order"] = [k for k in (config.get("app_order") or []) if k in known]
    return config


def normal_rule(kind, text):
    """What the Rules dialog stores for a typed ``text``: (value, note) for ``kind`` "exe" (a bare program file
    name) or "host" (a bare host, optionally ``*.`` + host). A pasted path keeps the file name and a pasted web
    address keeps the host only, each with a note saying so. ValueError(plain words) for anything else. The
    typed text is never logged or stored as typed."""
    import urllib.parse
    text = (text or "").strip().strip("\"'").strip()
    if kind == "exe":
        name = re.split(r"[\\/]", text)[-1].strip()
        note = RULE_FILE_ONLY.format(name=name) if name and name != text else ""
        if not app_profiles.exe_rule_ok(name):
            raise ValueError(RULE_BAD_EXE)
        return name, note
    if kind != "host":
        raise ValueError(RULE_BAD_HOST)
    value = text.lower()
    if re.search(r"[/:?#@\\\s]", value):
        try:
            host = urllib.parse.urlsplit(value if "//" in value else "//" + value).hostname or ""
        except ValueError:
            host = ""
        host = host.rstrip(".")
        if not app_profiles.host_rule_ok(host):
            raise ValueError(RULE_BAD_HOST)
        return host, RULE_HOST_ONLY.format(host=host)
    value = value.rstrip(".")
    if not app_profiles.host_rule_ok(value):
        raise ValueError(RULE_BAD_HOST)
    return value, ""


def icon24_rgb565(value):
    """A profile's 24 px icon as its 1152 RGB565 big-endian bytes (raw or Karl's base64), or None."""
    import base64
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, str):
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, TypeError):
            return None
    else:
        return None
    return raw if len(raw) == APP_ICON_SIZE * APP_ICON_SIZE * 2 else None


def icon24_png(value):
    """The 24 px icon as PNG bytes for a Tk PhotoImage: RGB565 big-endian expanded to 8 bits per channel, pure
    black transparent (Karl's icons are drawn on black). None when there is no usable icon. Pure: no Tk."""
    import struct
    import zlib
    raw = icon24_rgb565(value)
    if raw is None:
        return None
    size = APP_ICON_SIZE
    rows = bytearray()
    for y in range(size):
        rows.append(0)                                    # filter: none
        for x in range(size):
            pixel = (raw[2 * (y * size + x)] << 8) | raw[2 * (y * size + x) + 1]
            r5, g6, b5 = pixel >> 11, (pixel >> 5) & 0x3F, pixel & 0x1F
            rows += bytes(((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2),
                           0 if pixel == 0 else 255))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def app_warnings_note(warnings):
    """The row's small note: the first warning, plus how many more."""
    items = [str(w) for w in (warnings or ()) if str(w).strip()]
    if not items:
        return ""
    return items[0] if len(items) == 1 else f"{items[0]} {APPS_MORE.format(count=len(items) - 1)}"


class AppsSettingsModel:
    """Settings > Apps (plan section 3c) without Tk: the rows, the Off / Manual / Auto choice, the Rules
    dialog's lists, Import, the daily-fetch toggle and the page's status line. Every change applies at once
    (``runtime.set_app_mode`` / ``reload_profiles``) and is saved with ``save`` (write_settings of the whole
    config); a save that fails is reported, never raised. Never logs a rule's text, a title or a URL."""

    def __init__(self, config, runtime, library=None, save=None):
        self.config, self.runtime, self.library = config, runtime, library
        self._save = save
        self.message = ""                # the page's status line (import, update or save outcome)
        self.message_ok = True

    # ---------------------------------------------------------------- saving
    def save(self):
        if self._save is None:
            return True
        try:
            self._save(self.config)
            return True
        except OSError:
            _log.warning("App settings applied but settings.json could not be written")
            self.say(APPS_SAVE_FAILED, ok=False)
            return False

    def say(self, text, ok=True):
        self.message, self.message_ok = text, ok

    # ---------------------------------------------------------------- rows
    def rows(self):
        try:
            raw = list(self.runtime.app_rows())
        except Exception:
            _log.warning("App rows could not be read", exc_info=True)
            raw = []
        out = []
        for row in raw:
            pid = row.get("id")
            if not valid_app_id(pid):
                continue
            mode = row.get("mode")
            if mode not in APP_MODES:
                mode = (self.config.get("app_modes") or {}).get(pid, "off")
            out.append({"id": pid, "name": str(row.get("name") or pid),
                        "badge": APP_STATUS_BADGES.get(row.get("status"), APP_STATUS_BADGES["basic"]),
                        "source": APP_SOURCE_LABELS.get(row.get("source"), APP_SOURCE_LABELS["bundled"]),
                        "mode": mode, "summary": row.get("detect_summary") or APPS_NOT_DETECTED,
                        "warnings": app_warnings_note(row.get("warnings")), "icon24": row.get("icon24"),
                        "active": bool(row.get("active"))})
        return out

    def name(self, pid):
        return next((row["name"] for row in self.rows() if row["id"] == pid), pid)

    # ---------------------------------------------------------------- modes
    def set_mode(self, pid, mode):
        """Off / Manual / Auto for one app, applied and saved at once. Onshape's also goes to `onshape_mode`."""
        if mode not in APP_MODES or not valid_app_id(pid):
            return False
        setter = getattr(self.runtime, "set_app_mode", None)
        if callable(setter):
            setter(pid, mode)
        elif pid == "onshape" and callable(getattr(self.runtime, "set_onshape_mode", None)):
            self.runtime.set_onshape_mode(mode)              # a runtime from before app profiles
        modes = dict(self.config.get("app_modes") or {})
        modes[pid] = mode
        self.config["app_modes"] = modes
        if pid == "onshape":
            self.config["onshape_mode"] = mode
        self.save()
        return True

    # ---------------------------------------------------------------- rules
    def built_in_rules(self, pid):
        """The profile's own detection (its sidecar), shown but not editable."""
        profile = self.library.get(pid) if self.library is not None else None
        detect = (getattr(profile, "raw_overlay", None) or {}).get("detect") or {}
        return {kind: list(detect.get(kind) or ()) for kind, _check in _RULE_KINDS}

    def rules(self, pid):
        rules = (self.config.get("app_rules") or {}).get(pid) or {}
        return {kind: list(rules.get(kind) or ()) for kind, _check in _RULE_KINDS}

    def add_rule(self, pid, kind, text):
        """(ok, message): store a program name or host the owner typed, after normal_rule."""
        try:
            value, note = normal_rule(kind, text)
        except ValueError as exc:
            return False, str(exc)
        current = self.rules(pid)
        if value.lower() in {v.lower() for v in current[kind] + self.built_in_rules(pid)[kind]}:
            return False, RULE_DUPLICATE
        if len(current[kind]) >= APP_RULES_MAX:
            return False, RULE_FULL
        current[kind].append(value)
        self._set_rules(pid, current)
        return True, note or RULE_ADDED.format(value=value)

    def remove_rule(self, pid, kind, value):
        current = self.rules(pid)
        if value not in current.get(kind, ()):
            return False, ""
        current[kind].remove(value)
        self._set_rules(pid, current)
        return True, RULE_REMOVED.format(value=value)

    def _set_rules(self, pid, rules):
        all_rules = dict(self.config.get("app_rules") or {})
        entry = {kind: values for kind, values in rules.items() if values}
        if entry:
            all_rules[pid] = entry
        else:
            all_rules.pop(pid, None)
        self.config["app_rules"] = normal_app_rules(all_rules)
        self.apply_rules()
        self.save()

    def apply_rules(self):
        """Hand the rules to the library and the runtime, then reload (detection follows at once)."""
        if self.library is not None:
            self.library.rules = self.config["app_rules"]
        if hasattr(self.runtime, "app_rules") and not callable(getattr(self.runtime, "app_rules")):
            try:
                self.runtime.app_rules = self.config["app_rules"]
            except Exception:
                pass
        reload = getattr(self.runtime, "reload_profiles", None)
        if callable(reload):
            try:
                reload()
            except Exception:
                _log.warning("Profiles could not be reloaded", exc_info=True)

    # ---------------------------------------------------------------- import
    def import_profile(self, path):
        """Library.import_file (Karl file + sibling <id>.windows.json), then runtime.reload_profiles().
        (ok, message) in plain words; the problems are listed, at most three. Re-importing an id that already
        exists (any source) sets that app Off first (set_mode: the runtime releases held input when it is
        active, the setting is saved and onshape_mode follows), so a changed profile never runs unchosen."""
        if self.library is None:
            self.say(APPS_NO_LIBRARY, ok=False)
            return False, self.message
        path = Path(path)
        if path.name.endswith(".windows.json"):          # the sidecar was picked: import its Karl file
            path = path.with_name(path.name[:-len(".windows.json")] + ".json")
        file_name = path.name
        try:
            existing = {p.id for p in self.library.profiles()}
        except Exception:
            existing = set()
        try:
            profile = self.library.import_file(path)
        except app_profiles.ProfileError as exc:
            problems = list(exc.problems) or [str(exc)]
            text = "; ".join(problems[:3])
            if len(problems) > 3:
                text += " " + APPS_MORE.format(count=len(problems) - 3)
            self.say(APPS_IMPORT_FAILED.format(file=file_name, problems=text), ok=False)
            return False, self.message
        except OSError as exc:
            self.say(APPS_IMPORT_FAILED.format(file=file_name, problems=exc.strerror or type(exc).__name__),
                     ok=False)
            return False, self.message
        replaced = profile.id in existing
        if replaced:
            self.set_mode(profile.id, "off")
        reload = getattr(self.runtime, "reload_profiles", None)
        if callable(reload):
            try:
                reload()
            except Exception:
                _log.warning("Profiles could not be reloaded after an import", exc_info=True)
        mode = (self.config.get("app_modes") or {}).get(profile.id, "off")
        if replaced:
            template = APPS_IMPORTED_REPLACED
        else:
            template = APPS_IMPORTED_OFF if mode == "off" else APPS_IMPORTED
        self.say(template.format(name=app_display_name(profile)), ok=True)
        return True, self.message

    # ---------------------------------------------------------------- updates
    @property
    def fetch_daily(self):
        return self.config.get("profile_updates") == "daily"

    def set_fetch_daily(self, on):
        self.config["profile_updates"] = "daily" if on else "off"
        self.save()


def effective_motion(setting, probe):
    """K3 14.3: ``system`` follows Windows Animation effects (``probe()`` True = animations off),
    ``full`` / ``reduced`` are fixed. Returns True for reduced motion."""
    if setting == "full":
        return False
    if setting == "reduced":
        return True
    try:
        return bool(probe())
    except Exception:
        return False


# The strip column's detail wrap by columns per row: (600 px window / columns) - 32 px padding - slack.
STRIP_DETAIL_WRAP = {3: 160, 2: 250}


class SettingsStrip:
    """The status strip at the top of Settings (K3 14.1; S01 12; BS:435-446): three columns, each
    an 11 px uppercase name, an 8 px square mark (#6ED996 OK, #FF7A66 problem), the state, the
    detail and one action button (a primary light button for an expired or missing sign-in), with a
    2 px rule under the strip. ``update(model)`` repaints from ``strip_model``; ``actions`` maps an
    action key to a callable. Tk thread only.

    ``columns`` is the model's column count when the window opens: four (Home Assistant) are laid
    out as two rows of two (DD-BUG-021), since four side by side do not fit the 600 px window and
    the last one was clipped to a sliver."""

    def __init__(self, parent, actions, columns=3):
        self.actions = dict(actions)
        self.frame = tk.Frame(parent, bg=BG)
        self._rows = []
        self._per_row = 2 if columns == 4 else 3
        self._detail_wrap = STRIP_DETAIL_WRAP[self._per_row]
        self._rule = tk.Frame(self.frame, bg=RULE, height=RULE_WIDTH)      # the 2 px rule under the strip
        self._row_frame(0)
        self._rule.pack(fill="x")
        self.detail = label(self.frame, "", 10, SECONDARY, wraplength=SETUP_NOTE_WRAP, justify="left", anchor="w")
        self._detail_shown = False
        self.columns = []
        self.model = None
        for index in range(max(3, columns)):
            self._add_column(index)

    def _row_frame(self, row):
        """Row ``row`` of columns, created on first use above the rule (a hairline between rows)."""
        while len(self._rows) <= row:
            if self._rows:
                tk.Frame(self.frame, bg=HAIRLINE, height=1).pack(fill="x", before=self._rule)
            frame = tk.Frame(self.frame, bg=BG)
            if self._rows:
                frame.pack(fill="x", before=self._rule)
            else:
                frame.pack(fill="x")
            self._rows.append(frame)
        return self._rows[row]

    def _add_column(self, index):
        """One strip column (the fourth, Home Assistant, when the model has it)."""
        row_of_columns = self._row_frame(index // self._per_row)
        if index % self._per_row:
            tk.Frame(row_of_columns, bg=HAIRLINE, width=1).pack(side="left", fill="y")
        column = tk.Frame(row_of_columns, bg=BG, padx=16, pady=14)
        column.pack(side="left", fill="both", expand=True)
        name = label(column, "", 8, STRIP_TITLE_COLOR, anchor="w")
        name.configure(font=(UI_FAMILY, 8, "bold"))
        name.pack(anchor="w")
        state_row = tk.Frame(column, bg=BG)
        state_row.pack(anchor="w", pady=(6, 0))
        mark = tk.Frame(state_row, bg=OK, width=8, height=8)           # the 8 px square mark
        mark.pack(side="left", padx=(0, 8))
        state = label(state_row, "", 11, TEXT, anchor="w")
        state.configure(font=(UI_FAMILY, 11, "bold"))
        state.pack(side="left")
        detail = label(column, "", 9, STRIP_DETAIL_COLOR, anchor="w", justify="left",
                       wraplength=self._detail_wrap)
        detail.pack(anchor="w", pady=(6, 0), fill="x")
        action = button(column, "", lambda index=index: self._run(index))
        action.configure(padx=10, pady=4, font=(UI_FAMILY, 9, "bold"))
        action.pack(anchor="w", pady=(8, 0))
        self.columns.append({"name": name, "mark": mark, "state": state, "detail": detail, "action": action,
                             "key": None})

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)
        return self

    def _run(self, index):
        key = self.columns[index]["key"]
        action = self.actions.get(key)
        if action is not None:
            action()

    def show_detail(self, text):
        """The text under the strip (Troubleshoot: the knob's device status)."""
        self.detail.configure(text=text or "")
        if text and not self._detail_shown:
            self.detail.pack(fill="x", padx=16, pady=(8, 0))
            self._detail_shown = True
        elif not text and self._detail_shown:
            self.detail.pack_forget()
            self._detail_shown = False

    def update(self, model):
        if model == self.model:
            return False
        self.model = model
        while len(self.columns) < len(model):
            self._add_column(len(self.columns))
        for column, entry in zip(self.columns, model):
            column["name"].configure(text=entry["name"].upper())
            column["mark"].configure(bg=OK if entry["ok"] else ERROR)
            column["state"].configure(text=entry["state"])
            column["detail"].configure(text=entry["detail"])
            primary = bool(entry.get("primary"))
            column["action"].configure(text=entry["action"], bg=TEXT if primary else SURFACE,
                                       fg=BG if primary else TEXT,
                                       activebackground=SECONDARY if primary else HAIRLINE,
                                       activeforeground=BG if primary else TEXT,
                                       highlightbackground=TEXT if primary else RULE)
            column["key"] = entry["key"]
        return True


class RecalibrationGuard:
    """DD-BUG-051: when to offer accepting a refused motor direction change. A plain Recalibrate never
    sends ``acceptDirection``; only ``confirm`` does, and only while the knob's latest answer to a
    recalibration started here is a refusal with the reason 'direction-changed', on the same runtime
    and connection. ``observe`` runs each Tk tick: any tick that sees the knob disconnected, a new
    runtime or another result withdraws the offer."""

    REASON = "direction-changed"

    def __init__(self):
        self._runtime = None
        self._baseline = None        # calibration_result when a run was last started here
        self._armed = False          # a run started here awaits its answer
        self._offer = None           # the refusal (the runtime's result object) offered for Keep

    @classmethod
    def refused(cls, result):
        return isinstance(result, tuple) and len(result) >= 2 and result[0] is False and result[1] == cls.REASON

    def _follow(self, runtime):
        if runtime is not self._runtime:
            self._runtime, self._baseline, self._armed, self._offer = runtime, None, False, None

    def observe(self, runtime):
        self._follow(runtime)
        if not bool(getattr(runtime, "device_connected", False)):
            self._armed, self._offer = False, None           # a replug never inherits the offer
            return
        result = getattr(runtime, "calibration_result", None)
        if self._offer is not None and result is not self._offer:
            self._offer = None
        if self._armed and not getattr(runtime, "calibrating", False) and result is not self._baseline:
            self._armed = False
            self._offer = result if self.refused(result) else None

    def pending(self, runtime):
        """True while Settings should offer Keep new direction / Dismiss."""
        self.observe(runtime)
        return self._offer is not None

    def _start(self, runtime, accept):
        self._follow(runtime)
        baseline = getattr(runtime, "calibration_result", None)
        message = runtime.recalibrate_motor(accept_direction=accept)
        if not message:
            self._baseline, self._armed, self._offer = baseline, True, None
        return message

    def press(self, runtime):
        """Settings > Knob > Recalibrate motor: always without accepting a direction change."""
        return self._start(runtime, False)

    def confirm(self, runtime):
        """Keep new direction: the only path that sends acceptDirection true."""
        if not self.pending(runtime):
            return "There is no refused direction change to keep."
        return self._start(runtime, True)

    def dismiss(self):
        self._offer = None


# ---------------------------------------------------------------- mirror maths
def segment_polygon(index, centre=MIRROR_CENTRE, factor=MIRROR_SCALE):
    """Canvas polygon of ring segment ``index`` (0 = twelve o'clock, clockwise).

    Knob Face: a 4 x 10 px box centred on the origin, translateY(-138px), then
    rotate(index * 6deg) about the LCD centre.
    """
    theta = math.radians(index * 360 / RING_SEGMENTS)
    cos, sin = math.cos(theta), math.sin(theta)
    cx, cy = centre
    half_w, half_h = SEGMENT_WIDTH / 2, SEGMENT_HEIGHT / 2
    points = []
    for lx, ly in ((-half_w, -RING_RADIUS - half_h), (half_w, -RING_RADIUS - half_h),
                   (half_w, -RING_RADIUS + half_h), (-half_w, -RING_RADIUS + half_h)):
        points += [cx + (lx * cos - ly * sin) * factor, cy + (lx * sin + ly * cos) * factor]
    return points


def button_box(slot, centre=MIRROR_CENTRE, factor=MIRROR_SCALE):
    """(x0, y0, x1, y1) of physical button ``slot``'s face; its strip sits below y1."""
    cx, cy = centre
    left = BUTTON_LEFT + slot * (BUTTON_SIZE + BUTTON_GAP) - KNOB_CENTRE
    top = BUTTON_TOP - KNOB_CENTRE
    return (cx + left * factor, cy + top * factor,
            cx + (left + BUTTON_SIZE) * factor, cy + (top + BUTTON_SIZE) * factor)


# optical_alpha, led_source, ring_display, strip_display and ring_palette: knob_face
# (imported above; the same colour model the floating knob draws).
def lcd_cache_key(frame):
    """The frame without its ring, plus the few ring fields the LCD itself reads
    (Tracks position inks, the closed state of the selected window)."""
    ring = frame.get("ring") if isinstance(frame.get("ring"), dict) else {}
    rest = {key: value for key, value in frame.items() if key not in ("ring", "id")}
    return repr(rest) + repr(tuple(ring.get(key) for key in ("style", "index", "count", "first", "unavailable")))


def compose_lcd(frame, art=None, icon=None, artwork2=False):
    """render_lcd at native 240 px, scaled once to the mirror size.

    RGBA: transparent outside the round glass, so the square image never
    covers the bezel or the diagonal ring segments. ``artwork2`` (negotiated,
    ARTWORK2.md section 9 "Mirror"): ``art`` is the cover JPEG and ``icon`` the
    2048-byte icon payload the knob receives (Runtime.lcd_media).
    """
    from PIL import Image
    # The keyword only when negotiated: the v1 call stays exactly as before.
    lcd = (render_lcd(frame, art, icon, artwork2=True) if artwork2 else render_lcd(frame, art, icon)).convert("RGBA")
    return lcd.resize((LCD_PIXELS, LCD_PIXELS), Image.Resampling.LANCZOS)


class ControlCenterApp:
    # Defaults for stand-ins built without __init__ (tests): the full window, no overlay.
    chrome = True
    overlay = None
    _picker_exclusions = None
    overlay_submits = 0
    setup_actions = None
    setup_connect_button = None
    setup_notice_label = None
    _setup_has_actions = False
    _setup_set_note = None
    tray_messages = ()
    stage = None
    navigator = None
    fast_path = None
    sim_controls = None
    sim_device = None
    sim_knob = False            # the simulator's runtime uses sim_device (the picker's PC connection)
    sim_window = None
    strip = None
    mirror_lights = None
    app_library = None
    profile_updater = None
    apps_model = None
    _apps_refresh = None

    def __init__(self, root, smoke=False, live=False, chrome=True, overlay=None, stage=None, navigator=None):
        """``chrome=False`` (standalone live only): the floating knob. No window is built on
        ``root`` (header, panels, footer, canvas, window fitting and key bindings are
        skipped) and ``overlay`` (a KnobOverlay, or None) shows the knob instead. ``stage`` is
        the explorer / Up next presenter for live mode (a ``MusicOverlay``; K4 2.3)."""
        self.root, self.smoke = root, smoke
        self.closing = False
        self.live = live
        self.chrome = bool(chrome)
        self.overlay = overlay
        self.stage = stage
        # r3: the Navigator (navigator.Navigator) stands in for the floating knob of an r3 knob.
        self.navigator = navigator
        self.overlay_submits = 0    # scenes handed to the overlay (the smoke test reads it)
        # The simulator's one set of state-picker knobs (K3 16) and its knob (PC connection).
        self.sim_controls = SimControls()
        self.sim_device = AliveSimulatedDevice(self.sim_controls)
        self.strip = None           # the open Settings window's status strip (SettingsStrip)
        self.mirror_lights = None   # the simulator mirror's AliveLights (a knob with `alive`)
        # Tray failure (chrome=False): {"connect": fn, "quit": fn, "label": fn -> str}
        # adds Connect/Disconnect and Quit to Settings, so the app stays reachable.
        self.setup_actions = None
        self.setup_connect_button = None
        self.setup_notice_label = None  # tray failure: controller.notice (no balloons without a tray)
        self._setup_has_actions = False
        self.setup_window = None
        self.setup_note = None      # the Setup window's status line (tests read it)
        self.setup_size = None      # [width, height] the Setup window was last fitted to
        self._setup_set_note = None  # the open Setup window's note setter (None when closed)
        self.recal_guard = RecalibrationGuard()   # DD-BUG-051: Keep new direction only after a refusal
        self._setup_refresh_recal = None          # the open Settings' Keep / Dismiss row refresher
        # chrome=False: texts for tray balloons (the Apple Music authorization outcome; the
        # tray takes them with take_tray_messages()). v4 showed these in the status line.
        self.tray_messages = []
        self.auth = None
        self.last_signature = None
        ensure_ui_font(root)   # before any Tk font of ours exists
        self.config = self.load_config()
        self.root.title("Desk Dial")
        self.root.configure(bg=BG)
        if self.chrome:
            self.root.geometry("{}x{}".format(*WINDOW_SIZE))
            self.root.minsize(*WINDOW_MIN_SIZE)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.controller = Controller()
        self.device = None
        # The input fast path (K4 5.3): installed on the bridge before it can read anything.
        self.fast_path = FastPath(overlay=overlay if hasattr(overlay, "post_input") else None, stage=stage,
                                  navigator=navigator)
        if not smoke:
            from .device import DeviceBridge
            self.device = DeviceBridge(BACKUP_DIR)
            install_fast_path(self.device, self.fast_path)
        self.preview_lights = PreviewLights()
        self._poll_id = None
        self._failure_logged = {}
        self.failure_counts = {}   # stage -> failures (runtime, claim, auth, picker-icons, render, mirror)
        self.mirror_failures = 0
        self.lcd_renders = 0
        self._reset_mirror_state()
        self.runtime = self._make_runtime(live)
        self.fast_path.windows = self._picker_warmer(self.runtime)    # then kept current by each tick
        if self.chrome:
            self.build()
            self._apply_mode_controls()
            self._fit_window()
            self.root.bind("<Escape>", lambda e: self.escape())
            self.root.bind("<Left>", lambda e: self.controller.turn(-1))
            self.root.bind("<Right>", lambda e: self.controller.turn(1))
        self.poll()

    def escape(self):
        """The simulator window's Esc: Button 1 (Back) everywhere except Home, where Button 1 is
        Play / Pause (K3 3.1) and Esc must never toggle playback."""
        root = self.controller._root() if hasattr(self.controller, "_root") else "home"
        if self.controller.screen.mode == "onshape":
            self.controller._onshape_exit_by_user("escape")   # A0: Home (on the knob: all four buttons held 1 s)
        elif self.controller.screen.mode != root:
            self.controller.button(0)

    # ------------------------------------------------------------ settings
    @staticmethod
    def load_config():
        # DD-BUG-047: no speaker, room or port is assumed; the owner enters them (the tray finds the port).
        default = {"speaker_ip": "", "room_uid": "", ROOM_UID_SOURCE_KEY: "",
                   "port": "", "button_order": [0, 1, 2, 3], "button_order_verified": False,
                   "led_style": DEFAULT_LED_STYLE, "artwork": True,
                   "picker_background": DEFAULT_PICKER_BACKGROUND, "motion": DEFAULT_MOTION,
                   "navigator": DEFAULT_NAVIGATOR,
                   "ha_base_url": "", "ha_area": "", "ha_light_entity": "", "ha_scenes": [],
                   "onshape_mode": DEFAULT_ONSHAPE_MODE, "onshape_idle_ms": DEFAULT_ONSHAPE_IDLE_MS,
                   "onshape_content_classes": list(ONSHAPE_CONTENT_CLASSES),
                   "knob_sounds": True, "knob_sound_level": DEFAULT_KNOB_SOUND,
                   "knob_sound_volume": DEFAULT_KNOB_VOLUME, "reduced_haptics": False,
                   # Plan section 3c: app profiles (normal_app_settings migrates `onshape_mode`).
                   "app_modes": {}, "app_rules": {}, "app_order": [],
                   "profile_updates": profile_updates.DEFAULT_SETTING, "profile_updates_last": 0}
        try:
            value = read_settings_file()        # BOM-tolerant; a corrupt file is set aside (DD-BUG-017)
            default.update({k: value[k] for k in default if k in value})
            # alive LED tuning (ALIVE.md sections 3 and 10.2): optional, no UI, kept only when
            # present so Save writes back exactly what the user put there (never a null).
            # Validated where it is applied (runtime.led_tuning); never logged by value.
            for key in LED_TUNING_KEYS:
                if key in value:
                    default[key] = value[key]
        except (OSError, ValueError, TypeError):
            pass
        for key in ("speaker_ip", "room_uid", "port"):
            if not isinstance(default[key], str):
                default[key] = ""
        if default["speaker_ip"] and not valid_speaker_ip(default["speaker_ip"]):
            _log.warning("settings.json speaker_ip is not an IPv4 address; Sonos is not set up")
            default["speaker_ip"] = default["room_uid"] = ""     # DD-BUG-001: never a startup crash
        if default.get(ROOM_UID_SOURCE_KEY) != ROOM_UID_FROM_SPEAKER:
            default["room_uid"] = ""                # one-time migration: re-pin from the speaker
            default[ROOM_UID_SOURCE_KEY] = ""
        mapping = default["button_order"]
        if (not isinstance(mapping, list) or len(mapping) != 4 or
                any(type(index) is not int for index in mapping) or sorted(mapping) != [0, 1, 2, 3]):
            default["button_order"] = [0, 1, 2, 3]
            default["button_order_verified"] = False
        # Presentation settings are optional in older settings.json files (the
        # installer never overwrites it): the code defaults govern the upgrade.
        if default["led_style"] not in LED_STYLES:
            default["led_style"] = DEFAULT_LED_STYLE
        if type(default["artwork"]) is not bool:
            default["artwork"] = True
        if default["picker_background"] not in PICKER_BACKGROUNDS:
            default["picker_background"] = DEFAULT_PICKER_BACKGROUND
        if default["motion"] not in MOTION_VALUES:
            default["motion"] = DEFAULT_MOTION
        if default["navigator"] not in NAVIGATOR_VALUES:
            default["navigator"] = DEFAULT_NAVIGATOR
        # r4 knob sounds and haptics (settings.json; older files have none: On at 100 %, haptics full). A file from
        # before the volume keeps its level but starts at 100 % (knob_sound_level is no longer shown or sent).
        if type(default["knob_sounds"]) is not bool:
            default["knob_sounds"] = True
        if default["knob_sound_level"] not in KNOB_SOUND_LEVELS:
            default["knob_sound_level"] = DEFAULT_KNOB_SOUND
        default["knob_sound_volume"] = normal_knob_volume(default["knob_sound_volume"])
        if type(default["reduced_haptics"]) is not bool:
            default["reduced_haptics"] = False
        # A0 Onshape mode: Off unless chosen; the tunables are validated here (never logged).
        default["onshape_mode"] = normal_onshape_mode(default["onshape_mode"])
        default["onshape_idle_ms"] = normal_onshape_idle_ms(default["onshape_idle_ms"])
        default["onshape_content_classes"] = list(normal_onshape_classes(default["onshape_content_classes"]))
        # App profiles (plan section 3c): validated, `onshape_mode` migrated into app_modes and kept in sync.
        normal_app_settings(default)
        # r3 Home Assistant (the token is never here: CredentialStore key `ha_token`).
        from .home_assistant import normalize_base_url, normalize_scenes, valid_area, valid_entity
        try:
            default["ha_base_url"] = normalize_base_url(default["ha_base_url"]) if default["ha_base_url"] else ""
        except (ValueError, TypeError, AttributeError):
            default["ha_base_url"] = ""
        if not valid_area(default["ha_area"]):
            default["ha_area"] = ""       # r3.1: the area (every light in it) wins over one light
        if not valid_entity(default["ha_light_entity"], ("light",)):
            default["ha_light_entity"] = ""
        default["ha_scenes"] = normalize_scenes(default["ha_scenes"])
        return default

    def _picker_background(self):
        value = self.config.get("picker_background", DEFAULT_PICKER_BACKGROUND)
        return value if value in PICKER_BACKGROUNDS else DEFAULT_PICKER_BACKGROUND

    def _picker_backgrounds_available(self):
        """The Switcher background values the live picker can show: WindowsAdapter's
        ``picker_backgrounds`` (only "glass" on the carousel's plain-host fallback, CAROUSEL.md
        section 5), else both (the simulator, a provider without it). Never raises."""
        windows = getattr(getattr(self, "runtime", None), "windows", None)
        try:
            values = tuple(value for value in getattr(windows, "picker_backgrounds", PICKER_BACKGROUNDS)
                           if value in PICKER_BACKGROUNDS)
        except Exception:
            values = ()
        return values or PICKER_BACKGROUNDS

    def _apply_presentation(self, runtime=None):
        """Presentation only: the next frame is decorated differently; nothing re-enters.
        The switcher background goes to the live picker (WindowsAdapter) at once."""
        runtime = runtime if runtime is not None else self.runtime
        style = self.config.get("led_style", DEFAULT_LED_STYLE)
        runtime.led_style = style if style in LED_STYLES else DEFAULT_LED_STYLE
        runtime.artwork_enabled = self.config.get("artwork", True) is not False
        setter = getattr(getattr(runtime, "windows", None), "set_picker_background", None)
        if setter is not None:
            setter(self._picker_background())
        # settings.json led_drive / led_dither to the bridge (ALIVE.md 10.2): in every enter
        # frame of a knob with `alive`, and once after a change. Runs on every runtime build
        # (before the first enter) and on every Save.
        apply_led_tuning = getattr(runtime, "apply_led_tuning", None)
        if callable(apply_led_tuning):
            apply_led_tuning(self.config)
        # Motion (K3 14.3): re-evaluated at once; the runtime latches it into the controller, the
        # knob's frames and (through the tick) the presenters.
        set_motion = getattr(runtime, "set_motion", None)
        if callable(set_motion):
            motion = self.config.get("motion", DEFAULT_MOTION)
            set_motion(motion if motion in MOTION_VALUES else DEFAULT_MOTION)
        # r3 Navigator: Auto-hide / Pinned / Off, applied at once (the Tk tick re-evaluates it).
        navigator = getattr(self, "navigator", None)
        if navigator is not None:
            mode = self.config.get("navigator", DEFAULT_NAVIGATOR)
            navigator.set_mode(mode if mode in NAVIGATOR_VALUES else DEFAULT_NAVIGATOR)
        # App modes (plan section 3c; Onshape's is A0's Onshape mode), applied at once: each app whose mode the
        # runtime doesn't already have. A runtime from before app profiles gets Onshape's alone.
        set_app_mode = getattr(runtime, "set_app_mode", None)
        if callable(set_app_mode):
            try:
                current = dict(runtime.app_modes() or {})
            except Exception:
                current = {}
            for pid, mode in (self.config.get("app_modes") or {}).items():
                if current.get(pid) != mode:
                    set_app_mode(pid, mode)
        else:
            set_onshape = getattr(runtime, "set_onshape_mode", None)
            if callable(set_onshape):
                set_onshape(self.config.get("onshape_mode", DEFAULT_ONSHAPE_MODE))
        tuning = getattr(runtime, "set_onshape_tuning", None)
        if callable(tuning):
            tuning(self.config.get("onshape_idle_ms", DEFAULT_ONSHAPE_IDLE_MS))
        # r4: Knob sounds (the volume) and Reduced haptics, applied at once (an r4 knob gets them with its next
        # control).
        set_feel = getattr(runtime, "set_knob_feel", None)
        if callable(set_feel):
            set_feel(volume=knob_volume_setting(self.config), reduced_haptics=self.config.get("reduced_haptics") is True)

    def _apply_knob_sound(self, sounds_on, volume):
        """Settings > Knob sounds and its volume, applied and saved at once (no Save needed; the knob re-enters once).
        Only these two keys change; the file is written best effort (logged, never by value)."""
        self.config.update(knob_sounds=sounds_on is True, knob_sound_volume=normal_knob_volume(volume))
        set_feel = getattr(getattr(self, "runtime", None), "set_knob_feel", None)
        if callable(set_feel):
            set_feel(volume=knob_volume_setting(self.config))
        try:
            write_settings(self.config)
        except OSError:
            _log.warning("Knob sounds applied but settings.json could not be written")

    # ------------------------------------------------------------- runtime
    def providers(self, live):
        if not live:
            # K3 16: one SimControls for every fake; the BS album is playing from the queue.
            controls = self.sim_controls if self.sim_controls is not None else SimControls()
            return (SimulatedSonos(controls).load_album(), SimulatedAppleMusic(controls),
                    SimulatedWindows(controls))
        from .sonos import SonosAdapter
        from .apple_music import AppleMusicClient
        from .credentials import CredentialStore
        from .windows import WindowsAdapter
        from .credentials import CredentialError
        from .sonos import SonosError
        store = CredentialStore(DATA_DIR / "credentials.bin")
        # DD-BUG-001: an unreadable credential file (another Windows account, a restored profile)
        # starts Apple Music signed out with a strip notice; the next sign-in sets the file aside.
        try:
            credentials = store.load()
            self.credentials_locked = False
        except CredentialError:
            _log.warning("Saved sign-ins could not be unlocked; Apple Music starts signed out")
            credentials, self.credentials_locked = {}, True

        def load_credentials():
            try:
                found = store.load()
            except CredentialError:
                self.credentials_locked = True
                return {}
            self.credentials_locked = False
            return found
        speaker_ip = self.config.get("speaker_ip") or ""
        try:
            sonos = (SonosAdapter(speaker_ip, room_uid=self.config.get("room_uid") or None) if speaker_ip
                     else UnconfiguredSonos())
        except SonosError:
            _log.warning("Sonos speaker address is not usable; Sonos is not set up")
            sonos = UnconfiguredSonos()
        return (sonos,
                AppleMusicClient(credentials, credential_loader=load_credentials), WindowsAdapter(self.root,
                    on_hotkey=lambda: self.runtime.hotkey(),
                    on_cancel=lambda: self.controller.button(0),
                    on_focus_lost=lambda: self.controller.dismiss_windows(),
                    on_closed=lambda: self.render(force=True),
                    # The carousel's own input (CAROUSEL.md section 1): Enter or a centre-card
                    # click is the green button, Esc the red one (on_cancel), arrows/wheel turn.
                    on_switch=lambda: self.controller.button(3),
                    on_turn=self._picker_turn))

    def ha_provider(self, live):
        """The r3 Lights bridge: the simulator's SimulatedHomeAssistant, or the live adapter from
        settings.json + the credential store (None when Home Assistant is not set up; nothing
        connects until the runtime starts it). Never raises."""
        if not live:
            controls = self.sim_controls if self.sim_controls is not None else SimControls()
            return SimulatedHomeAssistant(controls, area=SIM_AREAS[0][0])   # r3.1: the simulator's first area
        try:
            from .credentials import CredentialStore
            from .home_assistant import build_adapter
            return build_adapter(self.config, CredentialStore(DATA_DIR / "credentials.bin"))
        except Exception as exc:
            _log.warning("Home Assistant not available (%s)", type(exc).__name__)
            return None

    def onshape_provider(self, live):
        """(injector, focus watcher, session watcher) for the live tray app, else (None, None, None).
        Never raises."""
        if not live or getattr(self, "smoke", False) or os.name != "nt":
            return (None, None, None)
        config = getattr(self, "config", {}) or {}
        from .onshape import live_service
        return live_service(config.get("onshape_idle_ms", DEFAULT_ONSHAPE_IDLE_MS),
                            config.get("onshape_content_classes"))

    def _make_runtime(self, live, providers=None, controller=None):
        """One builder for startup and the simulator/live toggle.

        Live: cover art and Recent accents from the configured speaker/Apple CDN,
        app icons from the IconWorker. Simulator: no network services; its items
        carry their own accents and there are no icons.

        ``controller`` defaults to ``self.controller``; the toggle passes a fresh
        one so nothing of the current runtime changes until the new one exists.
        The providers (built here or passed in) belong to the new runtime: on
        failure nothing is left running, since the services it started and the
        windows provider are closed before the error propagates.
        """
        controller = controller if controller is not None else self.controller
        sonos, apple, windows = self.providers(live) if providers is None else providers
        services = []
        artwork = accents = icons = None
        try:
            if live:
                from .artwork import ArtworkService, AccentService
                from .windows import IconWorker
                hosts = tuple(host for host in (self.config.get("speaker_ip"),) if host)
                artwork = ArtworkService(speaker_hosts=hosts)
                services.append(artwork)
                accents = AccentService(speaker_hosts=hosts)
                services.append(accents)
                # The picker's facts and 128 px icon masters in both modes (CAROUSEL.md section 7);
                # the HiresIcon copies only for the floating knob's LCD.
                icons = IconWorker(facts=True) if self.chrome else IconWorker(hires=True, facts=True)
                services.append(icons)
                # K3 11 / K4 2.3: the stage presenter (explorer, Up next) and the toast service
                # (the picker's toast window, lifted out of its session: K4 10).
                stage, toasts, device = self.stage, windows, self.device
            else:
                # K3 16: the simulator's presenters follow the state picker; its knob is the USB
                # bridge (a real knob, as in v6) until the picker's PC connection picks the
                # simulated one (SimulatedDevice, connected or disconnected).
                controls = self.sim_controls if self.sim_controls is not None else SimControls()
                stage, toasts = FakeStagePresenter(controls), SimulatedToasts()
                device = self.device
                if getattr(self, "sim_knob", False) and self.sim_device is not None:
                    device = self.sim_device
                    device.connected = False       # a new runtime: the simulated knob connects afresh
                    device.events = type(device.events)(device)
            ha = self.ha_provider(live)
            if ha is not None:
                services.append(ha)
            # A0 (ONSHAPE.md): SendInput only for the live tray app on real hardware; the simulator,
            # the smoke test and tests never get an injector.
            onshape = self.onshape_provider(live)
            services.extend(service for service in onshape if service is not None)
            runtime = Runtime(controller, sonos, apple, windows, device,
                              artwork=artwork, accents=accents, icons=icons, stage=stage, toasts=toasts, ha=ha,
                              onshape=onshape[0], onshape_focus=onshape[1], onshape_session=onshape[2],
                              **self._app_runtime_kwargs())
        except Exception:
            for service in services:
                _close_quietly(service)
            _close_quietly(windows)
            raise
        try:
            runtime.button_order = self.config["button_order"][:]
            # K3 3.1: windowsButton is button_order[3] (raw), derived by the controller.
            controller.button_order = self.config["button_order"][:]
            registry = getattr(windows, "set_overlay_registry", None)
            if callable(registry):
                # K4 2.4 / 10.4: the toast service and the picker read the open overlays.
                registry(lambda runtime=runtime: set(getattr(runtime, "open_surfaces", ()) or ()))
            self._apply_presentation(runtime)
        except Exception:
            try:
                # Stops its services and lanes (and its windows provider); the
                # shared DeviceBridge keeps running.
                runtime.shutdown(close_device=False)
            except Exception:
                pass
            raise
        return runtime

    def _app_library(self):
        """The app profiles (plan section 5a): bundled < updates < user by id, with the owner's rules. Built once
        and shared by every runtime (the simulator toggle keeps it); once it has loaded, ids it doesn't know are
        dropped from the settings (prune_app_ids). None when it can't be built. Never raises."""
        if self.app_library is not None:
            return self.app_library
        config = getattr(self, "config", None) or {}
        try:
            library = app_profiles.Library(paths.bundled_profiles_dir(), paths.profiles_updates_dir(),
                                           paths.profiles_user_dir(), rules=config.get("app_rules") or {})
        except Exception as exc:
            _log.warning("App profiles could not be loaded (%s)", type(exc).__name__)
            return None
        for problem in library.problems[:20]:
            _log.info("App profiles: %s", problem)
        self.app_library = library
        if isinstance(config, dict) and "app_modes" in config:
            prune_app_ids(config, [profile.id for profile in library.profiles()])
        return library

    def _app_runtime_kwargs(self):
        """Runtime's app-profile arguments (lane DD-B's interface): the library, app_modes, app_rules and
        app_order from settings.json. Only the ones this Runtime takes are passed."""
        config = getattr(self, "config", None) or {}
        values = {"app_library": self._app_library(), "app_modes": dict(config.get("app_modes") or {}),
                  "app_rules": dict(config.get("app_rules") or {}), "app_order": list(config.get("app_order") or [])}
        try:
            import inspect
            accepted = inspect.signature(Runtime.__init__).parameters
        except (TypeError, ValueError):
            return {}
        if any(p.kind is p.VAR_KEYWORD for p in accepted.values()):
            return values
        return {key: value for key, value in values.items() if key in accepted}

    # ---------------------------------------------------------------- build
    def build(self):
        outer = tk.Frame(self.root, bg=BG, padx=30, pady=25)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        label(header, "DESK DIAL", 12, SECONDARY).pack(anchor="w")
        label(header, "Your desk, within reach.", 26).pack(side="left", anchor="w", pady=(3, 16))
        self.setup_button = button(header, "Setup", self.setup)
        self.setup_button.pack(side="right", padx=(10, 0))
        self.env_button = button(header, "LIVE" if self.live else "SIMULATOR", self.toggle_environment)
        self.env_button.pack(side="right")
        # K3 16: the simulator's state picker (PC connection, source, outcomes, artwork ...).
        self.states_button = button(header, "States…", self.open_sim_picker)
        self.states_button.pack(side="right", padx=(0, 10))
        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="y")
        self.canvas = tk.Canvas(left, width=MIRROR_SIZE[0], height=MIRROR_SIZE[1], bg=BG, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<MouseWheel>", lambda e: self.controller.turn(1 if e.delta > 0 else -1))
        self.turns = tk.Frame(left, bg=BG)
        self.turns.pack(fill="x", padx=65)
        button(self.turns, "↶  One detent", lambda: self.controller.turn(-1)).pack(side="left")
        button(self.turns, "One detent  ↷", lambda: self.controller.turn(1)).pack(side="right")
        self.hint = label(left, "Mouse wheel or ← → to turn · click a button below the dial", 9, TERTIARY)
        self.hint.pack(pady=12)
        right = tk.Frame(body, bg=SURFACE, padx=22, pady=20, highlightthickness=RULE_WIDTH,
                         highlightbackground=HAIRLINE, highlightcolor=HAIRLINE)
        right.pack(side="right", fill="both", expand=True, padx=(24, 0), pady=(10, 12))
        self.mode_label = label(right, "NOW PLAYING", 10, SECONDARY, anchor="w")
        self.mode_label.pack(fill="x")
        self.target_label = label(right, "", 22, anchor="w")
        self.target_label.pack(fill="x", pady=(5, 15))
        self.description = label(right, "", 12, SECONDARY, wraplength=380, justify="left", anchor="w")
        self.description.pack(fill="x", pady=(0, 15))
        self.listbox = tk.Listbox(right, bg=SURFACE, fg=TEXT, selectbackground=RULE, selectforeground=TEXT,
            font=(UI_FAMILY, 11), borderwidth=0, highlightthickness=0, activestyle="none", height=12,
            exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.list_selected)
        self.detail_label = label(right, "", 10, TERTIARY, wraplength=380, justify="left", anchor="w")
        self.detail_label.pack(fill="x", pady=(15, 5))
        self.status_label = label(right, "", 11, TEXT, wraplength=380, justify="left", anchor="w")
        self.status_label.pack(fill="x", pady=(10, 0))
        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill="x", pady=(8, 0))
        self.device_label = label(footer, "Knob disconnected", 10, SECONDARY)
        self.device_label.pack(side="left")
        self.connect_button = button(footer, "Connect knob", self.connect)
        self.connect_button.pack(side="right")
        self.notice_label = label(outer, "", 10, NOTICE, wraplength=980, justify="left", anchor="w")
        self.notice_label.pack(fill="x", pady=(6, 0))
        self.notice_label.bind("<Button-1>", lambda e: self.clear_notice())
        self._build_mirror()

    def _build_mirror(self):
        """Static Knob Face device: 60 segments, bezel, LCD image and four buttons.

        Items are created once; each tick only reconfigures what changed.
        """
        from PIL import ImageTk
        canvas = self.canvas
        (width, height), (cx, cy) = MIRROR_SIZE, MIRROR_CENTRE
        edge = RULE_WIDTH / 2
        canvas.create_rectangle(edge, edge, width - edge, height - edge, fill=DEVICE_BG,
                                outline=HAIRLINE, width=RULE_WIDTH, tags=("device",))
        radius = DISC_RADIUS * MIRROR_SCALE
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=DISC_FILL,
                           outline=DISC_EDGE, width=1, tags=("bezel",))
        self.lcd_photo = ImageTk.PhotoImage("RGBA", (LCD_PIXELS, LCD_PIXELS), master=self.root)
        self.lcd_item = canvas.create_image(cx, cy, image=self.lcd_photo, tags=("lcd",))
        # Segments stack above the LCD image (they never overlap its round glass).
        self.ring_items = [canvas.create_polygon(segment_polygon(i), fill=SEGMENT_OFF, outline="",
                                                 tags=("ring-led", f"ring-led-{i}"))
                           for i in range(RING_SEGMENTS)]
        self.button_items, self.strip_items = [], []
        for slot in range(4):
            x0, y0, x1, y1 = button_box(slot)
            tag = f"button{slot}"
            self.button_items.append(canvas.create_rectangle(
                x0, y0, x1, y1, fill=BUTTON_FILL, outline=BUTTON_EDGE, width=1,
                tags=(tag, "mirror-button", "action-label:")))
            self.strip_items.append(canvas.create_rectangle(
                x0, y1, x1, y1 + STRIP_HEIGHT * MIRROR_SCALE, fill=STRIP_OFF, outline="",
                tags=(tag, "mirror-strip")))
            canvas.tag_bind(tag, "<Button-1>", lambda e, n=slot: self.press(n))
            canvas.tag_bind(tag, "<Enter>", lambda e: canvas.configure(cursor="hand2"))
            canvas.tag_bind(tag, "<Leave>", lambda e: canvas.configure(cursor=""))

    def _reset_mirror_state(self):
        """Forget everything drawn: the next visible tick redraws the mirror in full."""
        self._lcd_key = None
        self._lcd_cache = OrderedDict()
        self._ring_drive = [None] * RING_SEGMENTS
        self._ring_fill = [None] * RING_SEGMENTS
        self._strip_fill = [None] * 4
        self._button_labels = [None] * 4
        self._led_cache = {}
        self._mirror_hidden = False
        self._mirror_blank = False
        self._claimed = False
        self._picker_icon_signature = None
        self._picker_facts_revision = None   # runtime.window_facts_revision last handed to the picker
        self._picker_priority = None         # the selection the IconWorker last ordered its facts by
        self._picker_prewarmed = False       # IconWorker.prewarm ran for this runtime
        self._picker_exclusions = None       # (picker id, hwnds) last handed to set_capture_exclusions
        # Floating knob (chrome=False).
        self._touch_seen = None          # runtime.touch_seq last handed to overlay.touch()
        self._overlay_active = False     # the overlay was out of `hidden` on the last tick
        self._overlay_blank = False
        self._lights_stale = True        # a tick skipped PreviewLights (knob not connected)
        self._scene_signature = None     # (lcd key, ring) of the last submitted scene
        self._ring_key = None
        self._ring_colors = None
        self._overlay_lcd_cache = OrderedDict()
        # reason -> the last value sent to set_suppressed; a v7 reason still held stays known, so
        # its release is sent after the reset (the quiet reasons are never re-sent as off).
        previous = getattr(self, "_suppressed", None) or {}
        self._suppressed = {reason: True for reason in ("explorer", "upnext", "navigator") if previous.get(reason)}
        self._setup_connect_text = None
        self._setup_notice_text = None
        # Desktop v7.
        self.mirror_lights = None        # the simulator mirror's AliveLights
        self._mirror_claimed = False
        self._alive_posted = None        # the frame object last posted to the floating knob's engine
        self._alive_latched = {}         # latched name -> the value last posted
        self._stage_exclusions = None    # hwnds last handed to the stage presenter
        self._presenter_motion = None    # the reduced-motion value last handed to the picker

    def _apply_mode_controls(self):
        """Simulator controls (turn buttons, list, environment toggle) only when not live."""
        states = getattr(self, "states_button", None)
        if self.live:
            for widget in (self.turns, self.hint, self.listbox, self.env_button):
                widget.pack_forget()
            if states is not None:
                states.pack_forget()
            return
        if not self.turns.winfo_manager():
            self.turns.pack(fill="x", padx=65, after=self.canvas)
        if not self.hint.winfo_manager():
            self.hint.pack(pady=12, after=self.turns)
        if not self.listbox.winfo_manager():
            self.listbox.pack(fill="both", expand=True, before=self.detail_label)
        if not self.env_button.winfo_manager():
            self.env_button.pack(side="right", after=self.setup_button)
        if states is not None and not states.winfo_manager():
            states.pack(side="right", padx=(0, 10), after=self.env_button)

    def _fit_window(self):
        """Grow the main window when this mode's rows need more height (the
        simulator's turn buttons and hint do), so the footer and the notice are
        never squeezed out. Keeps a size the user chose; never shrinks."""
        root = self.root
        try:
            state, mapped = root.state(), root.winfo_ismapped()
        except tk.TclError:
            return
        if state == "zoomed":
            return   # maximized: as tall as the screen allows already
        if mapped and state == "normal":
            fit_height(root, root.winfo_width(), root.winfo_height())
        elif state == "normal":
            show_fitted(root, *WINDOW_SIZE)   # startup, not shown yet: size it before its first map
        else:
            fit_height(root, *WINDOW_SIZE)    # withdrawn (tray start) or iconified: applies when shown

    # ---------------------------------------------------------------- input
    def press(self, slot):
        self.controller.button(slot)

    def list_selected(self, event):
        selection = self.listbox.curselection()
        if selection and self.controller.screen.mode in ("recent", "windows", "explorer"):
            self.controller.position(selection[0])

    def _last_toast(self):
        """The simulator's last toast text (SimulatedToasts), or '' (the live toast is on screen)."""
        shown = getattr(getattr(self.runtime, "toasts", None), "shown", None)
        try:
            return str(shown[-1][0]) if shown else ""
        except (IndexError, TypeError, KeyError):
            return ""

    # ------------------------------------------------------------ rendering
    def render(self, force=False):
        frame = self.runtime.frame()
        if not self.chrome:
            self._render_overlay(frame, force)
            self._refresh_setup_actions()
            return
        self._render_panel(frame, force)
        self._render_mirror(frame, force)

    def _render_panel(self, frame, force=False):
        if not self.chrome:
            return   # no panel without the main window
        c = self.runtime.controller
        signature = repr((frame, c.screen.index, c.items(), self.runtime.device_status,
                          self.runtime.device_connected, c.notice, self.live, self._last_toast()))
        if not force and signature == self.last_signature:
            return
        self.last_signature = signature
        self.mode_label.configure(text=frame.get("mode", ""))
        self.target_label.configure(text=frame.get("target", ""))
        # Keyed by the v7 mode names (K3 2.1); an unknown mode shows nothing rather than failing.
        self.description.configure(text=MODE_DESCRIPTIONS.get(c.screen.mode, ""))
        if not self.live:
            self.listbox.delete(0, "end")
            if c.screen.mode in ("recent", "windows", "explorer"):
                for i, item in enumerate(c.items()):
                    prefix = "·" if item.get("available") else "×"
                    self.listbox.insert("end", f"{prefix}  {i+1:02d}   {item['title']}")
                if c.items():
                    self.listbox.selection_set(c.screen.index)
                    self.listbox.see(c.screen.index)
            else:
                for text in (["PREVIOUS", "NEUTRAL", "NEXT"] if c.screen.mode == "tracks" else [c.state.get("title") or "Nothing playing", c.state.get("artist", "")]):
                    self.listbox.insert("end", text)
                if c.screen.mode == "tracks":
                    self.listbox.selection_set(c.screen.index)
        selected = c.selected() or {}
        detail = selected.get("title", "")
        if selected.get("artist"):
            detail += "\n" + selected["artist"]
        detail += "\n\n" + PROFILES.get(c.screen.mode, "")
        self.detail_label.configure(text=detail.strip())
        full_status = c.screen.status or frame.get("status", "") or frame.get("meta", "")
        if c.screen.mode == "tracks" and c.screen.index == 0 and not c.state.get("can_previous"):
            full_status = c.state.get("previous_reason") or frame.get("status", "")
        toast = self._last_toast()
        if toast and not full_status:
            full_status = f"Toast · {toast}"
        self.status_label.configure(text=full_status or ("Simulated data · no desktop or speaker actions" if not self.live else "Ready"))
        self.device_label.configure(text=self.runtime.device_status)
        self.connect_button.configure(text="Disconnect knob" if self.runtime.device_connected else "Connect knob")
        self.notice_label.configure(text=(c.notice + "  ·  Click to dismiss") if c.notice else "")

    def _mirror_visible(self):
        """The smoke test renders the mirror while withdrawn; otherwise only when shown.

        chrome=False: while the floating knob wants frames (it is not `hidden`)."""
        if not self.chrome:
            return self._overlay_wants()
        if self.smoke:
            return True
        try:
            return self.root.state() not in ("withdrawn", "iconic")
        except tk.TclError:
            return False

    def _render_mirror(self, frame, force=False):
        if not self._mirror_visible():
            self._mirror_hidden = True
            return
        if self._mirror_hidden:
            # Coming back into view: no stale decay or flash from while hidden.
            self._mirror_hidden = False
            self.preview_lights.reset()
            force = True
        try:
            self._draw_mirror(frame, force or self._mirror_blank)
            self._mirror_blank = False
        except Exception:
            self.mirror_failures += 1
            self._log_failure("mirror", "Knob mirror could not be drawn; showing a blank mirror")
            self._blank_mirror()

    def _mirror_alive_lights(self, frame):
        """The simulator mirror of a knob with ``alive`` (K2 10.3: "the floating knob and the
        simulator use AliveLights"): the engine on the Tk thread at the tick, claimed with the
        session, fed the frame the knob was sent. (ring e x60, buttons e x4)."""
        from .alive_lights import AliveLights
        from .overlay import qpc_ms
        runtime = self.runtime
        now = qpc_ms(time.perf_counter())
        lights = self.mirror_lights
        if lights is None:
            lights = self.mirror_lights = AliveLights(now)
            self._mirror_claimed = False
        claimed = bool(self._claimed)
        if claimed and not self._mirror_claimed:
            lights.claim(now)
        elif self._mirror_claimed and not claimed:
            lights.release(now)
        self._mirror_claimed = claimed
        lights.set_reduced_motion(now, bool(getattr(runtime, "reduced_motion", False)))
        sent = getattr(runtime, "last_frame", None)
        framed = sent if isinstance(sent, dict) else {"id": runtime.controller.control_id, **frame}
        return lights.render(now, framed if claimed else None, None, None)

    def _draw_mirror(self, frame, force):
        c = self.runtime.controller
        self._draw_lcd(frame, force)
        canvas = self.canvas
        legends = frame.get("buttons") if isinstance(frame.get("buttons"), list) else []
        if getattr(self.runtime, "alive", False):
            from .knob_face import alive_fill_hex
            ring_e, buttons_e = self._mirror_alive_lights(frame)
            for i, e in enumerate(ring_e):
                fill = alive_fill_hex(e)
                if force or fill != self._ring_fill[i]:
                    canvas.itemconfigure(self.ring_items[i], fill=fill)
                    self._ring_fill[i] = fill
                self._ring_drive[i] = None
            strips = ["#{:02x}{:02x}{:02x}".format(*(int(38 + 217 * max(0.0, min(1.0, v)) + 0.5) for v in e))
                      for e in buttons_e]    # the recorded strip look (K2 10.3 M30: 38 + 217 e)
        else:
            self.mirror_lights = None
            ring, buttons = self.preview_lights.render(frame, c.control_id, int(time.monotonic() * 1000))
            palette = ring_palette(frame)
            for i, drive in enumerate(ring):
                if not force and drive == self._ring_drive[i]:
                    continue
                self._ring_drive[i] = drive
                fill = self._led_hex(ring_display, drive, palette)
                if fill != self._ring_fill[i]:
                    canvas.itemconfigure(self.ring_items[i], fill=fill)
                    self._ring_fill[i] = fill
            strips = [self._led_hex(strip_display, buttons[slot], LED_PALETTE) for slot in range(4)]
        for slot in range(4):
            fill = strips[slot]
            if force or fill != self._strip_fill[slot]:
                canvas.itemconfigure(self.strip_items[slot], fill=fill)
                self._strip_fill[slot] = fill
            legend = legends[slot] if slot < len(legends) and isinstance(legends[slot], dict) else {}
            text = str(legend.get("label", ""))
            if force or text != self._button_labels[slot]:
                # Full action names stay on the canvas for accessibility and exports.
                canvas.itemconfigure(self.button_items[slot],
                                     tags=(f"button{slot}", "mirror-button", f"action-label:{text}"))
                self._button_labels[slot] = text

    def _led_hex(self, display, drive, palette):
        key = (display, drive, palette)
        value = self._led_cache.get(key)
        if value is None:
            if len(self._led_cache) > 4096:
                self._led_cache.clear()
            value = self._led_cache[key] = display(drive, palette)
        return value

    def _presented_window(self):
        c = self.runtime.controller
        item = c.presented() if hasattr(c, "presented") else c.selected()
        return item if isinstance(item, dict) else None

    def _draw_lcd(self, frame, force):
        media = getattr(self.runtime, "lcd_media", None)
        if media is not None:
            # What the knob draws: with artwork2 the JPEG cover and the 2048-byte
            # icon payload the frame names, otherwise the v1 preview and RGBA icon.
            item = self._presented_window() if frame.get("layout") == "windows" else None
            art, icon, artwork2, identity = media(frame, item)
            key = (lcd_cache_key(frame),) + tuple(identity)   # (frame, art key drawn, icon, artwork2)
        else:
            artwork2 = False
            result = self.runtime.artwork_result
            art_key = frame.get("artKey") or ""
            art = (result.preview if art_key and result is not None
                   and getattr(result, "key", None) == art_key else None)
            icon, icon_identity = None, None
            if frame.get("layout") == "windows":
                item = self._presented_window()
                if item is not None:
                    icon = self.runtime.window_icons.get(item.get("id"))
                    if icon is not None:
                        icon_identity = (item.get("id"), id(icon))
            key = (lcd_cache_key(frame), art_key if art is not None else "", icon_identity)
        if not force and key == self._lcd_key:
            return
        image = self._lcd_cache.get(key)
        if image is None:
            image = compose_lcd(frame, art, icon, artwork2)
            self.lcd_renders += 1
            self._lcd_cache[key] = image
            while len(self._lcd_cache) > LCD_CACHE_SIZE:
                self._lcd_cache.popitem(last=False)
        else:
            self._lcd_cache.move_to_end(key)
        self.lcd_photo.paste(image)
        self._lcd_key = key

    def _blank_mirror(self):
        """Fallback after a failed draw: dark LCD, unlit ring and strips."""
        if self._mirror_blank or not self.chrome:
            return
        self._mirror_blank = True
        self._lcd_key = None
        try:
            from PIL import Image
            self.lcd_photo.paste(Image.new("RGBA", (LCD_PIXELS, LCD_PIXELS), (0, 0, 0, 0)))
        except Exception:
            pass
        try:
            for item in self.ring_items:
                self.canvas.itemconfigure(item, fill=SEGMENT_OFF)
            for item in self.strip_items:
                self.canvas.itemconfigure(item, fill=STRIP_OFF)
        except tk.TclError:
            pass
        self._ring_drive = [None] * RING_SEGMENTS
        self._ring_fill = [SEGMENT_OFF] * RING_SEGMENTS
        self._strip_fill = [STRIP_OFF] * 4

    # ------------------------------------------------------- floating knob
    def _overlay_wants(self):
        """overlay.wants_frames (a plain bool the overlay publishes; False without one)."""
        try:
            return self.overlay is not None and bool(self.overlay.wants_frames)
        except Exception:
            return False

    def _render_overlay(self, frame, force=False):
        """One chrome=False tick (FLOATING_KNOB.md sections 1 and 6).

        PreviewLights runs every tick while the knob is connected (and whenever a scene
        is built), so decay and flashes stay continuous. Suppression follows the picker
        and the connection. While the overlay wants frames, or on the tick of a new
        touch, the LCD (at overlay.lcd_px) and the ring colours are handed over as an
        OverlayScene, only when they changed; the scene goes before overlay.touch().
        Leaving `hidden` forces a full scene; the lights are reset only when they
        missed ticks meanwhile (the old reset-on-reappear), so the flash of the touch
        that summoned the knob is kept.
        """
        runtime, overlay = self.runtime, self.overlay
        seq = getattr(runtime, "touch_seq", 0)
        if self._touch_seen is None:
            self._touch_seen = seq           # a new runtime: its earlier touches are not news
        touched = seq != self._touch_seen
        self._touch_seen = seq
        navigating = self._render_navigator(frame)
        if overlay is None or getattr(overlay, "state", None) == "disabled":
            return   # no floating knob (its window could not be created): nothing to draw
        connected = bool(runtime.device_connected)
        self._update_suppression(connected)
        self._set_suppressed("navigator", navigating, quiet_off=True)
        if navigating:
            # r3: the Navigator replaced the floating knob. The knob's engine still gets its frames
            # (cheap, it stays in step); no LCD scene is drawn for the hidden knob.
            if callable(getattr(overlay, "set_alive", None)) and getattr(runtime, "alive", False):
                overlay.set_alive(True)
                self._post_alive()
            return
        if self._render_overlay_alive(frame, touched, force):
            return
        active = touched or self._mirror_visible()   # the gate: overlay.wants_frames
        if active and not self._overlay_active:
            force = True
            if self._lights_stale:
                self.preview_lights.reset()
        self._overlay_active = active
        drives = None
        if connected or active:
            drives, _buttons = self.preview_lights.render(frame, runtime.controller.control_id,
                                                          int(time.monotonic() * 1000))
            self._lights_stale = False
        else:
            self._lights_stale = True
        if active:
            try:
                self._submit_scene(frame, drives, force or self._overlay_blank)
                self._overlay_blank = False
            except Exception:
                self.mirror_failures += 1
                self._log_failure("mirror", "Floating knob could not be drawn; showing a blank knob")
                self._blank_overlay()
        if touched:
            overlay.touch()

    def _render_navigator(self, frame):
        """r3 (README section 5; DESKTOP_STAGE 24): the Navigator's tick. True while it stands in
        for the floating knob (an r3 knob, presentation >= 6, with a working Navigator); the
        floating knob is then held with the suppression reason 'navigator'."""
        nav = self.navigator
        if nav is None:
            return False
        runtime = self.runtime
        try:
            overlay_open = bool(self._carousel_open())
        except Exception:
            overlay_open = False
        try:
            active = bool(nav.update(runtime, frame, overlay_open=overlay_open))
        except Exception:
            self._log_failure("navigator", "The Navigator could not be updated; the floating knob stays")
            return False
        try:
            hwnd = int(getattr(self.overlay, "hwnd", 0) or 0) if self.overlay is not None else 0
            nav.set_exclusions((hwnd,) if hwnd else ())
        except Exception:
            pass
        return active

    def _render_overlay_alive(self, frame, touched, force):
        """Desktop v7 (K2 10.3; K4 11): with a knob that has ``alive`` the overlay thread draws the
        ring with AliveLights. The tick posts the frame the knob was sent, the claim and the
        control's maximum when they change, the latched values when they change, and the LCD
        scene while the knob wants frames; a touch still calls overlay.touch() (the fast path
        touches first). Returns False (the v5 path runs) for a knob without ``alive`` or an
        overlay without the engine."""
        overlay, runtime = self.overlay, self.runtime
        set_alive = getattr(overlay, "set_alive", None)
        if not callable(set_alive):
            return False
        alive = bool(getattr(runtime, "alive", False))
        set_alive(alive)
        if not alive:
            self._alive_posted = None
            self._alive_latched = {}
            return False
        self._post_alive()
        active = touched or self._mirror_visible()
        if active and not self._overlay_active:
            force = True
        self._overlay_active = active
        self._lights_stale = True            # PreviewLights is not run for an alive knob
        if active:
            try:
                self._submit_scene(frame, None, force or self._overlay_blank)   # the LCD; the ring is the engine's
                self._overlay_blank = False
            except Exception:
                self.mirror_failures += 1
                self._log_failure("mirror", "Floating knob LCD could not be drawn; showing a blank knob")
                self._blank_overlay()
        if touched:
            overlay.touch()
        return True

    def _post_alive(self):
        """The engine's inputs from the Tk side (K2 10.3 item 1): the frame the knob was sent
        (``runtime.last_frame``, with its id), the claim (``_watch_claim``), the control's maximum
        (the local cursor's bound), and clock / progress / Motion / tuning straight from the runtime."""
        runtime, overlay, controller = self.runtime, self.overlay, self.runtime.controller
        sent = getattr(runtime, "last_frame", None)
        claimed = bool(self._claimed)
        posted = self._alive_posted
        if isinstance(sent, dict) and (posted is None or posted[1] != claimed or posted[0] != sent):
            local_max = None
            try:
                if sent.get("id") == controller.control_id:
                    local_max = int(controller.bounds()[1])
            except Exception:
                local_max = None
            if overlay.post_frame(sent, claimed=claimed, local_max=local_max) is not False:
                self._alive_posted = (sent, claimed)
        elif not isinstance(sent, dict) and posted is not None and posted[1] and not claimed:
            overlay.post_frame(posted[0], claimed=False, local_max=None)   # the release still reaches the engine
            self._alive_posted = (posted[0], False)
        local = time.localtime()
        values = {"clock": local.tm_hour * 60 + local.tm_min,
                  "reduced_motion": bool(getattr(runtime, "reduced_motion", False))}
        progress = getattr(runtime, "last_progress", None)
        if isinstance(progress, tuple) and len(progress) >= 2:
            values["progress"] = (getattr(runtime, "progress_seq", 0), int(progress[0]), int(progress[1]))
        tuning = getattr(runtime, "led_tuning_v5", None)
        if isinstance(tuning, tuple) and len(tuning) == 2:
            pink, vol_full = tuning
            values["tuning"] = (pink if type(pink) is int else 0, bool(vol_full))
        changed = {name: value for name, value in values.items() if self._alive_latched.get(name) != value}
        if not changed:
            return
        if "progress" in changed:
            changed["progress"] = changed["progress"][1:]
        if overlay.set_latched(**changed) is not False:
            self._alive_latched.update({name: values[name] for name in changed})

    def _update_suppression(self, connected):
        """Hold the overlay hidden while the knob is disconnected, while the carousel is open
        (reason 'carousel', CAROUSEL.md section 11: from its open to the end of its exit, with
        either background; touches meanwhile do not slide the knob in, and it comes back by its
        normal touch rules), and while a picker without ``rect`` (a Tk window) covers it
        (reason 'picker'). Every reason is sent on each change, and again after a reset.
        Desktop v7 (K4 17.1): 'explorer' and 'upnext' from the open (the controller's mode enters
        at the press) to the scene's ``closed`` event (the runtime's ``open_surfaces`` registry)."""
        self._set_suppressed("disconnected", not connected)
        self._set_suppressed("picker", self._picker_overlaps())
        self._set_suppressed("carousel", self._carousel_open())
        mode = self.runtime.controller.screen.mode
        surfaces = getattr(self.runtime, "open_surfaces", None) or ()
        self._set_suppressed("explorer", mode == "explorer" or "explorer" in surfaces, quiet_off=True)
        self._set_suppressed("upnext", mode == "upnext" or "upnext" in surfaces, quiet_off=True)

    def _set_suppressed(self, reason, on, quiet_off=False):
        """Send a suppression reason when it changes. ``quiet_off``: a reason never held yet is
        not sent as off (the overlay starts with none held; the v7 reasons stay silent until an
        explorer or Up next first opens)."""
        on = bool(on)
        if self._suppressed.get(reason) is on:
            return
        if quiet_off and not on and reason not in self._suppressed:
            self._suppressed[reason] = False
            return
        self._suppressed[reason] = on
        self.overlay.set_suppressed(reason, on)

    def _picker_overlaps(self):
        """Whether a picker without ``rect`` (a Tk window, which hides at once) covers the
        floating knob; it counts only while the controller is in Windows mode. The carousel
        (a picker that publishes ``rect``) never counts here: section 11 replaced its pane
        overlap test with the 'carousel' reason (_carousel_open), which holds the knob hidden
        for the whole open, wherever the knob is."""
        windows_mode = self.runtime.controller.screen.mode == "windows"
        if not windows_mode:
            return False
        publishes, picker_rect = self._picker_geometry(measure_top=True)
        if publishes or picker_rect is None:
            return False
        try:
            rect = self.overlay.rect
        except Exception:
            rect = None
        return rects_overlap(rect, picker_rect)

    def _carousel_open(self):
        """True while the carousel is open: its ``rect`` (the stage's pane-sized card area) is
        published from the show() handshake until the teardown at the end of the Switch or
        Cancel exit animation (or at once on a plain hide), whatever the controller's mode and
        the background (CAROUSEL.md section 11). A raising ``rect`` counts as closed. Tk
        thread; never a native call from here."""
        publishes, rect = self._picker_geometry(measure_top=False)
        return bool(publishes and rect is not None)

    def _picker_rect(self):
        """(x, y, width, height) of the shown Windows picker in physical px (the process is
        per-monitor DPI aware), or None. Tk thread; never a native call from here.

        The carousel publishes its stage's pane-sized card area (``rect``, None when closed);
        a picker without ``rect`` (a Tk window) is measured through its ``top``."""
        return self._picker_geometry()[1]

    def _picker_geometry(self, measure_top=True):
        """(publishes, rect): ``publishes`` is True for a picker with a ``rect`` property (the
        carousel; a raising one counts as no picker), and ``rect`` is _picker_rect()'s answer.
        ``measure_top=False`` leaves a Tk picker's ``top`` unread (rect None)."""
        picker = getattr(self.runtime.windows, "overlay", None)
        if picker is None:
            return False, None
        try:
            rect = picker.rect
        except AttributeError:
            pass
        except Exception:
            return True, None
        else:
            try:
                x, y, width, height = (int(value) for value in rect)
            except (TypeError, ValueError):
                return True, None
            return True, ((x, y, width, height) if width > 0 and height > 0 else None)
        top = getattr(picker, "top", None) if measure_top else None
        if top is None:
            return False, None
        try:
            if not top.winfo_ismapped():
                return False, None
            return False, (top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height())
        except (tk.TclError, AttributeError):
            return False, None

    def _submit_scene(self, frame, drives, force):
        from .knob_face import ring_colors
        from .overlay import OverlayScene
        overlay = self.overlay
        pixels = int(getattr(overlay, "lcd_px", 0) or 0)
        pixels = pixels if pixels > 0 else LCD_NATIVE
        lcd, lcd_key = self._overlay_lcd(frame, pixels, force)
        drives = tuple(drives) if drives is not None else (0,) * RING_SEGMENTS
        ring_key = (drives, ring_palette(frame))
        if ring_key != self._ring_key or self._ring_colors is None:
            self._ring_colors = tuple(tuple(color) for color in ring_colors(frame, drives))
            self._ring_key = ring_key
        signature = (lcd_key, self._ring_colors)
        if not force and signature == self._scene_signature:
            return
        overlay.submit(OverlayScene(lcd_key, lcd, self._ring_colors))
        self._scene_signature = signature
        self.overlay_submits += 1

    def _overlay_lcd(self, frame, pixels, force):
        """(RGBA image at ``pixels``, key): the knob's LCD drawn at the overlay's size, from
        the hi-res cover and icon above 240 px. Cached by frame, media and size; the images
        are never mutated after hand-off."""
        hires = pixels > LCD_NATIVE
        item = self._presented_window() if frame.get("layout") == "windows" else None
        media = self.runtime.lcd_media(frame, item, hires=True) if hires else \
            self.runtime.lcd_media(frame, item) + (None, None)
        art, icon, artwork2, identity, hires_cover, hires_icon = media
        key = (lcd_cache_key(frame),) + tuple(identity) + (pixels,)
        image = self._overlay_lcd_cache.get(key)
        if image is None:
            image = render_overlay_lcd(frame, art, icon, artwork2=artwork2, pixels=pixels,
                                       hires_cover=hires_cover, hires_icon=hires_icon)
            self.lcd_renders += 1
            self._overlay_lcd_cache[key] = image
            while len(self._overlay_lcd_cache) > OVERLAY_LCD_CACHE_SIZE:
                self._overlay_lcd_cache.popitem(last=False)
        else:
            self._overlay_lcd_cache.move_to_end(key)
        return image, key

    def _blank_overlay(self):
        """Fallback after a failed scene: an unlit ring and no LCD, once per failure run."""
        if self._overlay_blank:
            return
        self._overlay_blank = True
        self._scene_signature = None
        try:
            from .knob_face import ring_colors
            from .overlay import OverlayScene
            ring = tuple(tuple(color) for color in ring_colors({}, (0,) * RING_SEGMENTS))
            self.overlay.submit(OverlayScene(None, None, ring))
        except Exception:
            pass

    def peek(self, seconds=2.5):
        """Tray "Show knob" (DD-BUG-018). While the r3 Navigator stands in for the floating knob
        (the overlay is then held with the reason 'navigator' and would ignore a peek), the
        Navigator is shown instead, as a knob turn would (it appears from the next tick and
        follows its own auto-hide); otherwise the overlay's peek (a touch with its own duration).
        Returns True when something will show, False when nothing can (no knob connected, the
        Navigator not eligible, no floating knob): the tray can say so instead of a silent no-op."""
        nav = self.navigator
        if nav is not None and getattr(nav, "active", False):
            if not getattr(nav, "eligible", False):
                return False
            try:
                nav.note_turn()
            except Exception:
                self._log_failure("navigator", "The Navigator could not be shown from the tray")
                return False
            return True
        overlay = self.overlay
        if overlay is None or getattr(overlay, "state", None) == "disabled":
            return False
        return overlay.peek(seconds) is not False     # False while a suppression reason holds

    def peek_available(self):
        """Whether tray "Show knob" can show anything now (DD-BUG-018): a connected knob and
        either an eligible Navigator (when it stands in for the floating knob) or a floating knob
        window. The tray disables the item when this is False."""
        if not bool(getattr(self.runtime, "device_connected", False)):
            return False
        nav = self.navigator
        if nav is not None and getattr(nav, "active", False):
            return bool(getattr(nav, "eligible", False))
        overlay = self.overlay
        return overlay is not None and getattr(overlay, "state", None) != "disabled"

    def _refresh_setup_actions(self):
        """The tray-failure Settings rows: keep Connect/Disconnect's label current, and show
        controller.notice (the tray's balloons are missing) until it is dismissed or the
        next action clears it, as the v4 window's notice line did."""
        widget = self.setup_connect_button
        label_of = (self.setup_actions or {}).get("label")
        if widget is not None and label_of is not None:
            try:
                text = label_of()
                if text != self._setup_connect_text:
                    widget.configure(text=text)
                    self._setup_connect_text = text
            except tk.TclError:
                self.setup_connect_button = None   # Settings was closed
        notice_widget = self.setup_notice_label
        if notice_widget is None:
            return
        notice = self.controller.notice
        text = (notice + "  ·  Click to dismiss") if notice else ""
        if text == self._setup_notice_text:
            return
        try:
            notice_widget.configure(text=text)
        except tk.TclError:
            self.setup_notice_label = None     # Settings was closed
            return
        self._setup_notice_text = text
        if text:
            self._refit_setup()                     # a long notice grows, never clips

    def _refit_setup(self):
        """Grow Settings to fit what it now shows (a long notice, FU-2: the Home Assistant lists after a
        test), never past the work area (DD-BUG-020); what still does not fit scrolls. Never raises."""
        try:
            window = self.setup_window
            if window is None or self.setup_size is None:
                return None
            return refit_height(window, self.setup_size,
                                limit=lambda: settings_height_limit(primary_work_area(window), window_frame_extent()))
        except Exception:
            _log.exception("Setup window could not be refitted")
            return None

    def _recal_guard(self):
        """The app's RecalibrationGuard (DD-BUG-051), made on first use."""
        guard = self.__dict__.get("recal_guard")
        if guard is None:
            guard = self.__dict__["recal_guard"] = RecalibrationGuard()
        return guard

    def _log_failure(self, key, message):
        """Count a failure of stage ``key`` and logging.exception it at most once per
        LOG_INTERVAL_SECONDS per key (call inside except)."""
        counts = self.__dict__.setdefault("failure_counts", {})
        logged = self.__dict__.setdefault("_failure_logged", {})
        counts[key] = counts.get(key, 0) + 1
        now = time.monotonic()
        last = logged.get(key)
        if last is None or now - last >= LOG_INTERVAL_SECONDS:
            logged[key] = now
            _log.exception(message)

    # --------------------------------------------------------------- device
    def clear_notice(self):
        self.controller.notice = ""

    def connect(self):
        if self.sim_knob and not self.live:
            # The simulator's knob: the button flips the state picker's PC connection (K3 16).
            self.sim_controls.connected = not self.runtime.device_connected
            return
        if not self.device:
            return
        if self.runtime.device_connected:
            self.device.submit("disconnect")
        else:
            self.runtime.device_status = "Reading profiles and backing up device…"
            self.runtime.button_order = self.config["button_order"][:]
            self.device.submit("connect", self.config["port"])

    def _dialog_parent(self):
        """messagebox parent: the main window, or (chrome=False, root withdrawn) Settings."""
        if self.chrome:
            return self.root
        window = self.setup_window
        try:
            return window if window is not None and window.winfo_exists() else None
        except tk.TclError:
            return None

    def toggle_environment(self):
        if self.runtime.device_connected and not (self.sim_knob and not self.live):
            messagebox.showinfo("Disconnect first", "Disconnect the knob before changing simulator/live mode.", parent=self._dialog_parent())
            return
        if self.controller.command_request or self.controller.volume_request:
            self.controller.screen.status = "Wait for the current Sonos action to finish"
            return
        requested = not self.live
        # Build the whole replacement (controller, providers, services, runtime)
        # first. Any failure closes what was built (_make_runtime owns the new
        # providers) and leaves the current runtime untouched and running.
        try:
            controller = Controller()
            providers = self.providers(requested)
            runtime = self._make_runtime(requested, providers, controller)
        except Exception as exc:
            _log.exception("Could not switch to %s mode", "live" if requested else "simulator")
            messagebox.showerror("Setup required", str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, parent=self._dialog_parent())
            return
        old = self.runtime
        try:
            # The DeviceBridge is shared: only this runtime's own work stops.
            old.shutdown(close_device=False)
        except Exception:
            _log.exception("Previous runtime did not shut down cleanly")
        self.controller, self.runtime = controller, runtime
        self.live = requested
        if self.chrome:
            self.env_button.configure(text="LIVE" if self.live else "SIMULATOR")
        self.last_signature = None
        self.preview_lights.reset()
        self._reset_mirror_state()
        if self.chrome:
            self._apply_mode_controls()
            self._fit_window()

    # ------------------------------------------------------------ simulator (K3 16)
    def set_sim_connection(self, value):
        """The state picker's PC connection: "usb" (the DeviceBridge: a real knob, as in v6),
        "connected" or "disconnected" (the SimulatedDevice). Switching between the bridge and the
        simulated knob builds a fresh runtime (like the simulator / live toggle); a real knob must
        be disconnected first. Returns True when applied."""
        if self.live:
            return False
        want_sim = value in ("connected", "disconnected")
        if want_sim:
            self.sim_controls.connected = value == "connected"
        if want_sim == bool(self.sim_knob):
            return True
        if self.runtime.device_connected and not self.sim_knob:
            self.controller.screen.status = "Disconnect the USB knob before simulating one"
            return False
        previous = self.sim_knob
        self.sim_knob = want_sim
        try:
            controller = Controller()
            runtime = self._make_runtime(False, None, controller)
        except Exception:
            self.sim_knob = previous
            _log.exception("Could not switch the simulator's knob")
            return False
        old = self.runtime
        try:
            old.shutdown(close_device=False)
        except Exception:
            _log.exception("Previous runtime did not shut down cleanly")
        self.controller, self.runtime = controller, runtime
        self.last_signature = None
        self.preview_lights.reset()
        self._reset_mirror_state()
        return True

    def set_sim_state(self, name, value):
        """One state-picker option (a SimControls field; PC connection goes to set_sim_connection)."""
        if name == "connected":
            return self.set_sim_connection("connected" if value else "disconnected")
        if name == "usb":
            return self.set_sim_connection("usb")
        if not hasattr(self.sim_controls, name):
            return False
        setattr(self.sim_controls, name, value)
        self.last_signature = None
        return True

    def open_sim_picker(self):
        """The simulator's state picker window (K3 16; BS:1352-1370): one row per SimControls group."""
        existing = self.sim_window
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                return existing
        except tk.TclError:
            pass
        win = self.sim_window = tk.Toplevel(self.root, bg=BG)
        win.title("Desk Dial · Simulator states")
        if self.chrome:
            win.transient(self.root)
        body = tk.Frame(win, bg=BG, padx=20, pady=16)
        body.pack(fill="both", expand=True)
        label(body, "SIMULATOR STATES", 10, SECONDARY).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        rows = (("pc", "PC connection", (("usb", "Knob on USB"), ("connected", "Simulated · connected"),
                                         ("disconnected", "Simulated · disconnected"))),) + \
            tuple(entry for entry in SIM_PICKER if entry[0] != "connected")
        for row, (name, title, options) in enumerate(rows, start=1):
            label(body, title, 10, SECONDARY).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=2)
            texts = [text for _value, text in options]
            if name == "pc":
                current = ("usb" if not self.sim_knob else
                           ("connected" if self.sim_controls.connected else "disconnected"))
            else:
                current = getattr(self.sim_controls, name, options[0][0])
            chosen = tk.StringVar(value=next((text for value, text in options if value == current), texts[0]))

            def picked(text, name=name, options=options):
                value = next(value for value, option in options if option == text)
                if name == "pc":
                    self.set_sim_connection(value)
                else:
                    self.set_sim_state(name, value)
            menu = tk.OptionMenu(body, chosen, *texts, command=picked)
            menu.configure(bg=SURFACE, fg=TEXT, activebackground=HAIRLINE, activeforeground=TEXT, relief="flat",
                           highlightthickness=0, font=(UI_FAMILY, 10))
            menu.grid(row=row, column=1, sticky="w", pady=2)
        return win

    def _watch_claim(self):
        """PreviewLights.reset() once per claim, like the firmware renderer reset.

        The claim is latched per connection: the first entry acknowledgement
        after connect/reconnect claims. Later entries drop ``c.ready`` until the
        knob acknowledges them, but that is not an unclaim (the firmware keeps
        its lastSeq, flash, decay and fade), so it never resets the lights.
        Disconnect, an error or a release (``device_supported`` drops) ends the
        session; the next acknowledged entry claims again. (The end is observed
        on a tick of its own: a reconnect is only requested after the
        disconnect was seen, and its port open and handshake span many ticks.)
        """
        runtime = self.runtime
        c = runtime.controller
        session = bool(runtime.device_connected and runtime.device_supported
                       and getattr(c, "hardware", False))
        if not session:
            self._claimed = False
        elif c.ready and not self._claimed:
            self.preview_lights.reset()
            self._claimed = True

    def _sync_picker_icons(self):
        """Hand the picker its icons and label facts (Tk thread; the presenter paints them only
        once it holds focus). Icons (CAROUSEL.md section 7): the IconWorker's 128 px master,
        else the floating knob's 128 px copy, else the knob's 32 px icon (windows.picker_icons).
        Facts (section 6): the runtime's merged IconWorker facts, handed to the WindowsAdapter
        when they changed; it computes the labels. The IconWorker also orders its remaining
        facts jobs by the current selection, and warms its caches once per runtime. The floating
        knob's window is named to the picker so its glass capture leaves the knob out."""
        from .windows import picker_icons
        runtime = self.runtime
        windows = runtime.windows
        overlay = getattr(windows, "overlay", None)
        self._sync_capture_exclusions(overlay)
        setter = getattr(overlay, "set_icons", None)
        facts = getattr(runtime, "window_facts", None) or {}
        if setter is not None:
            icons = picker_icons(runtime.window_icons, facts, getattr(runtime, "window_hires_icon", None))
            signature = tuple((key, id(value)) for key, value in icons.items())
            if signature != self._picker_icon_signature:
                self._picker_icon_signature = signature
                setter(icons)
        push = getattr(windows, "set_window_facts", None)
        revision = getattr(runtime, "window_facts_revision", 0)
        if push is not None and revision != self._picker_facts_revision:
            self._picker_facts_revision = revision
            push(facts)
        worker = getattr(runtime, "icons", None)
        screen = runtime.controller.screen
        index = screen.index if screen.mode == "windows" else None
        if index != self._picker_priority:
            self._picker_priority = index
            prioritize = getattr(worker, "prioritize", None)
            if index is not None and prioritize is not None:
                prioritize(index)
        if not self._picker_prewarmed and worker is not None:
            self._picker_prewarmed = True
            prewarm, items = getattr(worker, "prewarm", None), getattr(windows, "prewarm_items", None)
            if prewarm is not None and items is not None:
                prewarm(items())

    def _sync_capture_exclusions(self, picker):
        """Keep the floating knob out of the carousel's frost (CAROUSEL.md sections 5 and 11). The
        knob is a topmost window of this process anywhere on the monitor the frost captures, and
        its 'carousel' suppression only follows on a later tick (and slides it out), so it would
        be blurred into the frost. Its handle
        (KnobOverlay.hwnd) goes to the picker's set_capture_exclusions, which applies from the
        next open. It is sent once the window exists and again whenever the handle or the picker
        changes (a new runtime builds a new picker). Tk thread. A picker without the method
        (a stand-in) is skipped."""
        try:
            hwnd = int(getattr(self.overlay, "hwnd", 0) or 0) if self.overlay is not None else 0
        except Exception:
            hwnd = 0
        hwnds = (hwnd,) if hwnd else ()
        try:   # r3: the Navigator may still be sliding out when an overlay captures its frost
            nav_hwnd = int(getattr(self.navigator, "hwnd", 0) or 0) if self.navigator is not None else 0
        except Exception:
            nav_hwnd = 0
        if nav_hwnd:
            hwnds = hwnds + (nav_hwnd,)
        # K4 2.6: the stage's frost capture excludes the same windows (the floating knob may still
        # be sliding out when an explorer or Up next opens).
        stage_setter = getattr(self.stage, "set_capture_exclusions", None) if self.stage is not None else None
        if stage_setter is not None and hwnds != self._stage_exclusions:
            self._stage_exclusions = hwnds
            stage_setter(hwnds)
        setter = getattr(picker, "set_capture_exclusions", None)
        if setter is None:
            return
        key = (id(picker), hwnds)
        if key == self._picker_exclusions:
            return
        self._picker_exclusions = key      # a failing call is counted once, not retried every tick
        setter(hwnds)

    @staticmethod
    def _picker_warmer(runtime):
        """The runtime's picker when a knob touch can warm its GPU chrome (``note_touch``: the live
        WindowsAdapter, CAROUSEL.md 12.4), else None (the simulator's windows, stand-ins)."""
        windows = getattr(runtime, "windows", None)
        return windows if callable(getattr(windows, "note_touch", None)) else None

    def _sync_presenters(self):
        """Per tick (Tk thread): the fast path's button order, whether a stage scene can take
        positions (K4 5.3) and the picker a knob touch warms (the current runtime's, so a runtime
        swap is followed), and the effective Motion setting for the picker (K3 14.3; the stage and
        the controller latch it through the open payload and the frames)."""
        runtime = self.runtime
        fast = self.fast_path
        if fast is not None:
            failures = getattr(fast, "failures", 0)
            if type(failures) is int and failures:     # DD-RES-016: the smoke test and status.json see them
                self.__dict__.setdefault("failure_counts", {})["fast-path"] = failures
            order = list(getattr(runtime, "button_order", fast.button_order))
            if order != fast.button_order:
                fast.button_order = order
            mode = runtime.controller.screen.mode
            surfaces = getattr(runtime, "open_surfaces", None) or ()
            fast.stage_open = mode in ("explorer", "upnext") or "explorer" in surfaces or "upnext" in surfaces
            warmer = self._picker_warmer(runtime)
            if getattr(fast, "windows", None) is not warmer:
                fast.windows = warmer
            # A0: the Onshape injector and whether the knob's input is Onshape's now.
            injector = getattr(runtime, "onshape", None)
            if getattr(fast, "onshape", None) is not injector:
                fast.onshape = injector
            state = getattr(runtime, "onshape_fast_state", None)
            fast.onshape_state = state() if callable(state) else "off"
        motion = bool(getattr(runtime, "reduced_motion", False))
        if motion != self._presenter_motion:
            setter = getattr(runtime.windows, "set_reduced_motion", None)
            if callable(setter):
                setter(motion)
            self._presenter_motion = motion

    def _picker_turn(self, delta):
        """A turn from the picker's own input (arrow keys, the wheel). Only without a knob
        session: a host-side turn would desync the knob's absolute detent (CAROUSEL.md
        section 9), so with the knob this is a no-op (the carousel may still nudge at an end)."""
        controller = self.controller
        if getattr(controller, "hardware", False):
            return
        controller.turn(delta)

    # ---------------------------------------------------------------- setup
    def setup(self, page=None):
        """The Settings window (r3.1: a window of pages). Under the status strip, a page list —
        General, Music, Windows, Home Assistant, Knob — shows one page at a time; every setting
        behaves as before, only its place changed (``SETTINGS_PAGES``). ``page`` opens that page.
        chrome=False (tray Settings…): not transient for the withdrawn root (Tk never maps a
        transient of an unmapped master) and brought forward with deiconify/lift/focus_force; with
        ``setup_actions`` (tray failure) it also offers Connect/Disconnect and Quit. Its settings
        content is the same in both modes."""
        existing = self.setup_window
        if existing and existing.winfo_exists():
            if self.chrome:
                existing.lift()
                self._open_setup_page(page)
                return
            if self._setup_has_actions or not self.setup_actions:
                self._present_setup(existing)
                self._open_setup_page(page)
                return
            # The tray failed while Settings was open: rebuild it with Connect and Quit.
            self.runtime.on_button_probe = None
            self._setup_set_note = None
            existing.destroy()
        win = self.setup_window = tk.Toplevel(self.root, bg=BG)
        win.title(SETTINGS_TITLE)
        win.geometry("{}x{}".format(*SETUP_SIZE))
        if self.chrome:
            win.transient(self.root)
        fields, entry_widgets = {}, {}
        field_pages = {"Speaker IP": "music", "Knob USB port": "knob"}

        def focus_field(name):
            show_page(field_pages.get(name))
            widget = entry_widgets.get(name)
            if widget is not None:
                try:
                    widget.focus_set()
                    widget.select_range(0, "end")
                except tk.TclError:
                    pass
                scroller = scrollers.get(field_pages.get(name))
                if scroller is not None:
                    try:
                        win.update_idletasks()
                    except tk.TclError:
                        pass
                    scroller.see(widget)

        def troubleshoot():
            # DD-BUG-039: the cause under the strip and the Knob page; no USB-port focus (the tray's
            # auto-connect finds the knob by itself and never reads that field).
            self.strip.show_detail(self.runtime.device_status)
            show_page("knob")
        # K3 14.1: the status strip at the top of Settings, where recovery lives.
        self.strip = SettingsStrip(win, {
            "knob_settings": lambda: focus_field("Knob USB port"),
            "troubleshoot": troubleshoot,
            "manual_ip": lambda: focus_field("Speaker IP"),
            "renew_signin": lambda: authorize(),
            "sign_in": lambda: authorize(),
            "home_assistant": lambda: show_page("home_assistant"),
        }, columns=self._strip_columns()).pack(fill="x")
        self._refresh_strip()
        # r3.1: the page list (one row: the window keeps its width).
        page_bar = tk.Frame(win, bg=SURFACE)
        page_bar.pack(fill="x")
        page_buttons = {}
        for key, title in SETTINGS_PAGES:
            page_buttons[key] = button(page_bar, title, lambda key=key: show_page(key))
            page_buttons[key].pack(side="left")
        body = tk.Frame(win, bg=BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        host = tk.Frame(body, bg=BG)
        # DD-BUG-020: the Knob page (the longest) scrolls when the work area is too short for it;
        # ``shells`` are what is packed and forgotten as a page, ``pages`` where its rows are built.
        pages, shells, scrollers = {}, {}, {}
        for key, _title in SETTINGS_PAGES:
            if key in ("knob", "apps"):
                scrollers[key] = ScrollPage(host, BG)
                shells[key], pages[key] = scrollers[key].outer, scrollers[key].inner
            else:
                shells[key] = pages[key] = tk.Frame(host, bg=BG)
        built = {}                                   # pages built on first show (Home Assistant, Apps)
        current = [None]
        titles = {}
        for key, title in SETTINGS_PAGES:
            if key != "home_assistant":
                titles[key] = label(pages[key], title, 23)
                titles[key].pack(anchor="w")
        heading = label(pages["general"], SETUP_SUBTITLE, 10, SECONDARY, wraplength=SETUP_NOTE_WRAP, justify="left")
        heading.pack(anchor="w", pady=(2, 15))

        def entry(name, default="", parent=None):
            parent = parent if parent is not None else pages["general"]
            label(parent, name, 10, SECONDARY).pack(anchor="w", pady=(9, 3))
            value = tk.StringVar(value=default)
            widget = tk.Entry(parent, textvariable=value, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=(UI_FAMILY, 11), highlightthickness=RULE_WIDTH, highlightbackground=HAIRLINE,
                              highlightcolor=RULE)
            widget.pack(fill="x", ipady=6)
            fields[name] = value
            entry_widgets[name] = widget
            return value
        # The StringVars keep their creation order (speaker IP, knob port, button order, Team ID, …).
        ip = entry("Speaker IP", self.config["speaker_ip"], pages["music"])
        port = entry("Knob USB port", self.config["port"], pages["knob"])
        order = entry("Raw button indices, physical left to right", ",".join(map(str, self.config["button_order"])),
                      pages["knob"])
        label(pages["knob"], "Press each physical button during setup and note its raw index below.", 9,
              TERTIARY).pack(anchor="w", pady=5)
        probe_label = label(pages["knob"], "Button order still needs physical verification", 10, SECONDARY)
        probe_label.pack(anchor="w")
        captured = []
        def probe(raw):
            if raw in captured:
                probe_label.configure(text="That button is already recorded · press the next one to its right")
                return
            captured.append(raw)
            if len(captured) == 4:
                order.set(",".join(map(str, captured)))
                self.config["button_order_verified"] = True
                probe_label.configure(text="All four recorded left to right · Save settings to apply")
                self.runtime.on_button_probe = None
            else:
                probe_label.configure(text=f"Recorded {len(captured)} of 4 · press the next button to its right")
        def calibrate():
            if not self.runtime.device_supported or not self.controller.ready:
                probe_label.configure(text="Connect a knob with the control-center firmware first")
                return
            captured.clear()
            self.runtime.on_button_probe = probe
            probe_label.configure(text="Press the leftmost physical button, then continue to the right")
        button(pages["knob"], "Verify physical button order", calibrate).pack(anchor="w", pady=4)
        team = entry("Apple Team ID", parent=pages["music"])   # FU-3: empty; the ID is the user's own
        key = entry("MusicKit Key ID", parent=pages["music"])
        key_path = tk.StringVar()
        key_row = tk.Frame(pages["music"], bg=BG)
        key_row.pack(fill="x", pady=12)
        button(key_row, "Choose .p8 key", lambda: key_path.set(filedialog.askopenfilename(parent=win, filetypes=[("Apple private key", "*.p8")]))).pack(side="left")
        label(key_row, "Key and token are protected locally with Windows", 9, TERTIARY).pack(side="left", padx=12)
        # Knob presentation (after the existing fields; their StringVar order is unchanged).
        style = self.config.get("led_style", DEFAULT_LED_STYLE)
        artwork_choice = tk.StringVar(value="off" if self.config.get("artwork", True) is False else "on")
        led_choice = tk.StringVar(value=style if style in LED_STYLES else DEFAULT_LED_STYLE)
        # The Windows switcher's backdrop (CAROUSEL.md sections 5 and 11): on the carousel's
        # plain-host fallback only Frosted is offered, and a stored "none" is kept as is.
        backgrounds = self._picker_backgrounds_available()
        stored_background = self._picker_background()
        background_locked = stored_background not in backgrounds
        background_choice = tk.StringVar(value=DEFAULT_PICKER_BACKGROUND if background_locked else stored_background)
        def segmented(title, variable, options, parent, disabled=(), on_change=None):
            group = tk.Frame(parent, bg=BG)
            group.pack(side="left", padx=(0, SETTINGS_GROUP_GAP))
            label(group, title, 10, SECONDARY).pack(anchor="w", pady=(0, 3))
            row = tk.Frame(group, bg=BG)
            row.pack(anchor="w")
            widgets = {}
            def paint():
                for value, widget in widgets.items():
                    chosen = variable.get() == value
                    widget.configure(bg=RULE if chosen else SURFACE, fg=TEXT if chosen else SECONDARY)
            def choose(value):
                if value in disabled:
                    return
                variable.set(value)
                paint()
                if on_change is not None:
                    on_change(value)
            for text, value in options:
                widgets[value] = button(row, text, lambda v=value: choose(v))
                if value in disabled:
                    widgets[value].configure(state="disabled", disabledforeground=TERTIARY, cursor="")
                widgets[value].pack(side="left")
            paint()
            return group

        def section(parent):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", pady=(12, 10))
            return row
        segmented("Album artwork", artwork_choice, (("On", "on"), ("Off", "off")), section(pages["music"]))
        segmented("LEDs", led_choice, LED_STYLE_CHOICES, section(pages["knob"]))
        unavailable = tuple(value for _, value in PICKER_BACKGROUND_CHOICES if value not in backgrounds)
        switcher_row = section(pages["windows"])
        switcher_group = segmented("Switcher background", background_choice, PICKER_BACKGROUND_CHOICES,
                                   switcher_row, disabled=unavailable)
        if unavailable:
            track_note_wrap(label(switcher_group, PICKER_BACKGROUND_FALLBACK_NOTE, 9, TERTIARY,
                                  wraplength=SETUP_NOTE_WRAP, justify="left"), switcher_row,
                            SETTINGS_GROUP_GAP).pack(anchor="w", pady=(4, 0))
        # K3 14.3 (settings.motion): Match Windows (the Animation effects setting) / Full / Reduced.
        stored_motion = self.config.get("motion", DEFAULT_MOTION)
        motion_choice = tk.StringVar(value=stored_motion if stored_motion in MOTION_VALUES else DEFAULT_MOTION)
        segmented("Motion", motion_choice, MOTION_CHOICES, section(pages["general"]))
        # r3 Navigator (README section 5): Auto-hide (default) / Pinned / Off, on a row of its own.
        stored_navigator = self.config.get("navigator", DEFAULT_NAVIGATOR)
        navigator_choice = tk.StringVar(value=stored_navigator if stored_navigator in NAVIGATOR_VALUES
                                        else DEFAULT_NAVIGATOR)
        segmented("Navigator", navigator_choice, NAVIGATOR_CHOICES, section(pages["general"]))
        # A0 Onshape mode moved to Settings > Apps (plan section 3c, one row per app); the Knob page points there.
        apps_row = section(pages["knob"])
        apps_group = tk.Frame(apps_row, bg=BG)
        apps_group.pack(side="left", padx=(0, SETTINGS_GROUP_GAP))
        # FU-1: the Knob page's notes wrap at the scrolled page's width (less the group's gap), never wider.
        track_note_wrap(label(apps_group, APPS_POINTER_NOTE, 9, TERTIARY, wraplength=SETUP_NOTE_WRAP,
                              justify="left"), apps_row, SETTINGS_GROUP_GAP).pack(anchor="w")
        # r4 (Settings > Knob): Knob sounds On / Off with its volume on one row (both apply and save at once, the
        # slider on release), Reduced haptics, Recalibrate motor.
        sounds_choice = tk.StringVar(value="off" if self.config.get("knob_sounds") is False else "on")
        haptics_choice = tk.StringVar(value="on" if self.config.get("reduced_haptics") is True else "off")
        sounds_row = section(pages["knob"])
        volume = [normal_knob_volume(self.config.get("knob_sound_volume", DEFAULT_KNOB_VOLUME))]

        def apply_sound(*_args):
            self._apply_knob_sound(sounds_choice.get() != "off", volume[0])
        segmented("Knob sounds", sounds_choice, KNOB_SOUNDS_CHOICES, sounds_row, on_change=apply_sound)
        volume_group = tk.Frame(sounds_row, bg=BG)
        volume_group.pack(side="left", anchor="n", padx=(0, 28))
        label(volume_group, "Volume", 10, SECONDARY).pack(anchor="w", pady=(0, 3))
        volume_row = tk.Frame(volume_group, bg=BG)
        volume_row.pack(anchor="w", pady=(11, 0))     # level with the middle of the On / Off buttons
        volume_text = label(volume_row, f"{volume[0]} %", 10, TEXT, width=5, anchor="w")

        def slide(value):
            volume[0] = normal_knob_volume(int(round(float(value))))
            volume_text.configure(text=f"{volume[0]} %")
        slider = tk.Scale(volume_row, from_=0, to=KNOB_VOLUME_MAX, resolution=KNOB_VOLUME_STEP, orient="horizontal",
                          length=240, showvalue=False, command=slide, bg=RULE, troughcolor=SURFACE,
                          activebackground=SECONDARY, relief="flat", borderwidth=0, sliderrelief="flat",
                          highlightthickness=RULE_WIDTH, highlightbackground=HAIRLINE, highlightcolor=RULE,
                          cursor="hand2")
        slider.set(volume[0])
        slider.bind("<ButtonRelease-1>", apply_sound)
        slider.bind("<KeyRelease>", apply_sound)
        slider.pack(side="left")
        volume_text.pack(side="left", padx=(10, 0))
        haptics_row = section(pages["knob"])
        haptics_group = segmented("Reduced haptics", haptics_choice, REDUCED_HAPTICS_CHOICES, haptics_row)
        track_note_wrap(label(haptics_group, KNOB_FEEL_NOTE, 9, TERTIARY, wraplength=SETUP_NOTE_WRAP, justify="left"),
                        haptics_row, SETTINGS_GROUP_GAP).pack(anchor="w", pady=(4, 0))

        # D-RECAL (v2.0.0): Recalibrate motor is hidden until recalibration has been rehearsed on hardware; the
        # runtime, device and firmware command stay (SHOW_RECALIBRATE).
        if SHOW_RECALIBRATE:
            guard = self._recal_guard()

            def recalibrate():
                # DD-BUG-051: a plain press never accepts a direction change (Keep new direction does).
                message = guard.press(self.runtime)
                refresh_recal()
                set_note(message or RECALIBRATE_NOTE)

            def keep_direction():
                message = guard.confirm(self.runtime)
                refresh_recal()
                set_note(message or DIRECTION_KEEP_NOTE)

            def dismiss_direction():
                guard.dismiss()
                refresh_recal()
                set_note("")
            recal_button = button(pages["knob"], "Recalibrate motor", recalibrate)
            recal_button.pack(anchor="w", pady=4)
            direction_row = tk.Frame(pages["knob"], bg=BG)
            track_note_wrap(label(direction_row, DIRECTION_CHANGED_NOTE, 9, NOTICE, wraplength=SETUP_NOTE_WRAP,
                                  justify="left"), direction_row).pack(anchor="w", pady=(0, 4))
            direction_buttons = tk.Frame(direction_row, bg=BG)
            direction_buttons.pack(anchor="w")
            button(direction_buttons, "Keep new direction", keep_direction).pack(side="left")
            button(direction_buttons, "Dismiss", dismiss_direction).pack(side="left", padx=(8, 0))
            direction_shown = [False]

            def refresh_recal():
                """Show the Keep / Dismiss row only while a refusal from a run started here is pending."""
                try:
                    want = guard.pending(self.runtime)
                    if want and not direction_shown[0]:
                        direction_row.pack(anchor="w", fill="x", pady=(0, 8), after=recal_button)
                    elif not want and direction_shown[0]:
                        direction_row.pack_forget()
                    direction_shown[0] = want
                except tk.TclError:
                    pass
            self._setup_refresh_recal = refresh_recal
            refresh_recal()
        else:
            self._setup_refresh_recal = None
        # Authorize Apple Music lives on the Music page, packed first at its bottom (a short window
        # squeezes the fields above it, never the button).
        button(pages["music"], "Authorize Apple Music", lambda: authorize()).pack(
            side="bottom", anchor="w", pady=(8, 0), before=titles["music"])
        # Space for the Save confirmation is reserved up front (the fitted window
        # already includes it); a longer message grows the window (refit_height).
        saved_note = SETUP_SAVED_NOTES[bool(getattr(self, "live", False))]
        try:
            reserved = max(SETUP_NOTE_LINES, wrapped_lines(win, saved_note, 10, SETUP_NOTE_WRAP))
        except Exception:
            reserved = SETUP_NOTE_LINES   # measuring is best effort; refit_height still applies
        note = self.setup_note = label(body, "", 10, SECONDARY, wraplength=SETUP_NOTE_WRAP,
                                       justify="left", anchor="nw", height=reserved)
        fitted = self.setup_size = list(SETUP_SIZE)

        def height_limit():
            # DD-BUG-020: never grow past the work area (title bar and borders included).
            return settings_height_limit(primary_work_area(win), window_frame_extent())

        def set_note(text):
            # Natural height from now on: within the reservation nothing moves;
            # beyond it (a long error) the window grows instead of clipping.
            note.configure(text=text, height=0)
            try:
                refit_height(win, fitted, limit=height_limit)
            except Exception:
                _log.exception("Setup window could not be refitted")
        # The Apple Music authorization outcome arrives on a later tick (_report_auth).
        self._setup_set_note = set_note
        def save():
            try:
                mapping = [int(v.strip()) for v in order.get().split(",")]
                if sorted(mapping) != [0, 1, 2, 3]:
                    raise ValueError()
                import ipaddress
                if ip.get().strip():                  # empty: Sonos not set up yet (DD-BUG-047)
                    ipaddress.IPv4Address(ip.get().strip())   # Sonos takes IPv4 only (DD-BUG-001)
            except ValueError:
                set_note("Enter the speaker's IPv4 address and each index 0, 1, 2, 3 once.")
                return
            led = led_choice.get() if led_choice.get() in LED_STYLES else DEFAULT_LED_STYLE
            # A stored choice the fallback cannot show was never offered here: it is kept.
            background = stored_background if background_locked else background_choice.get()
            background = background if background in PICKER_BACKGROUNDS else DEFAULT_PICKER_BACKGROUND
            motion = motion_choice.get() if motion_choice.get() in MOTION_VALUES else DEFAULT_MOTION
            navigator = navigator_choice.get() if navigator_choice.get() in NAVIGATOR_VALUES else DEFAULT_NAVIGATOR
            apply_speaker_ip(self.config, ip.get())
            self.config.update(port=port.get().strip(), button_order=mapping,
                               led_style=led, artwork=artwork_choice.get() != "off",
                               picker_background=background, motion=motion, navigator=navigator,
                               knob_sounds=sounds_choice.get() != "off",
                               knob_sound_volume=volume[0], reduced_haptics=haptics_choice.get() == "on")
            self.config["button_order_verified"] = len(captured) == 4 and mapping == captured
            self._apply_presentation()
            try:
                write_settings(self.config)
            except OSError:
                set_note("Artwork, LEDs, the switcher background and Motion applied, but the settings file "
                         "could not be written.")
                return
            set_note(saved_note)
            self._refresh_strip()
        def authorize():
            try:
                from .credentials import (CredentialError, CredentialStore, MusicKitCredentials, AuthServer,
                                          musickit_saver)
                store = CredentialStore(DATA_DIR / "credentials.bin")
                if key_path.get():
                    credentials = MusicKitCredentials.from_key_file(team.get(), key.get(), key_path.get())
                else:
                    try:
                        credentials = store.load()
                    except CredentialError:   # DD-BUG-001: only a fresh key file can sign in again
                        set_note("Saved sign-ins could not be unlocked. Choose your MusicKit key file "
                                 "to sign in again.")
                        return
                # Keep the working grant until the replacement consent succeeds.
                # Saving a freshly chosen key here would erase its user token.
                if self.auth:
                    self.auth.stop()
                # Merge only the MusicKit keys into the file as it is when consent completes:
                # the Home Assistant token (and anything saved meanwhile) is kept (DD-RES-001).
                self.auth = AuthServer(credentials, on_token=musickit_saver(store))
                url = self.auth.start()
                webbrowser.open(url)
                set_note("Complete Apple Music authorization in your browser.")
            except Exception as exc:
                set_note(str(exc) if isinstance(exc, RuntimeError) else "Could not start MusicKit authorization")
        # Created last (keyboard order), packed first at the bottom: a short
        # window squeezes the page above, never Save.
        actions = tk.Frame(body, bg=BG)
        actions.pack(side="bottom", fill="x", pady=(15, 0))
        button(actions, "Save settings", save).pack(side="left")
        note.pack(side="bottom", fill="x")
        host.pack(fill="both", expand=True)
        self._setup_has_actions = bool(not self.chrome and self.setup_actions)
        if self._setup_has_actions:
            # Tray failure: the knob can still be connected, disconnected and quit.
            extra = tk.Frame(body, bg=BG)
            extra.pack(side="bottom", fill="x", pady=(12, 0), before=actions)
            label(extra, "Tray icon unavailable", 9, TERTIARY).pack(side="left")
            self._setup_connect_text = None
            self.setup_connect_button = button(extra, "Connect knob", lambda: self._setup_action("connect"))
            self.setup_connect_button.pack(side="left", padx=(12, 0))
            button(extra, "Quit Desk Dial", lambda: self._setup_action("quit")).pack(side="right")
            # No tray balloons either: a failed action's notice shows here (click to dismiss).
            self._setup_notice_text = None
            self.setup_notice_label = label(body, "", 10, NOTICE, wraplength=SETUP_NOTE_WRAP, justify="left",
                                            anchor="w", cursor="hand2")
            self.setup_notice_label.pack(side="bottom", fill="x", pady=(8, 0), after=extra)
            self.setup_notice_label.bind("<Button-1>", lambda e: self.clear_notice())
            self._refresh_setup_actions()

        def show_page(name):
            """One page at a time; the Home Assistant page has its own Save / Cancel, so the
            window's Save settings row and note make way for it. Never raises."""
            if name not in pages or name == current[0]:
                return
            try:
                if current[0] is not None:
                    shells[current[0]].pack_forget()
                if name in SETTINGS_OWN_SAVE_PAGES:
                    if name not in built:
                        builder = self._build_ha_page if name == "home_assistant" else self._build_apps_page
                        built[name] = builder(pages[name], win)
                    if current[0] not in SETTINGS_OWN_SAVE_PAGES:
                        actions.pack_forget()
                        note.pack_forget()
                elif current[0] in SETTINGS_OWN_SAVE_PAGES:
                    note.pack(side="bottom", fill="x", before=host)
                    actions.pack(side="bottom", fill="x", pady=(15, 0), before=note)
                shells[name].pack(fill="both", expand=True)
                current[0] = name
                # 2026-09-30: a taller page (Knob, with Onshape mode) grows the window instead of squeezing
                # its last rows away (Tk shrinks the last-packed widgets first). Never shrinks. DD-BUG-020:
                # never past the work area either; the Knob page scrolls for what does not fit.
                refit_height(win, fitted, limit=height_limit)
                for key_name, widget in page_buttons.items():
                    chosen = key_name == name
                    widget.configure(bg=RULE if chosen else SURFACE, fg=TEXT if chosen else SECONDARY)
            except Exception:
                _log.exception("Settings page %s could not be shown", name)
        self._setup_open_page = show_page
        # The first page: packed directly (no page is shown yet).
        first = page if page in pages and page not in SETTINGS_OWN_SAVE_PAGES else "general"
        shells[first].pack(fill="both", expand=True)
        current[0] = first
        for key_name, widget in page_buttons.items():
            widget.configure(bg=RULE if key_name == first else SURFACE, fg=TEXT if key_name == first else SECONDARY)
        def done():
            self.runtime.on_button_probe = None
            if self._setup_set_note is set_note:
                self._setup_set_note = None
            self.strip = None
            self._setup_refresh_recal = None
            self._setup_open_page = lambda name=None: None
            self._apps_refresh = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", done)
        self._schedule_strip(win)
        # The default height would clip Archivo's taller rows. chrome=False: placed while still
        # withdrawn, clear of the floating knob (FLOATING_KNOB.md section 9.12).
        grown = show_fitted(win, *SETUP_SIZE, place=None if self.chrome else self._place_settings)
        if grown:
            fitted[1] = grown
        if not self.chrome:
            self._present_setup(win)
        if page in SETTINGS_OWN_SAVE_PAGES:
            show_page(page)

    def _place_settings(self, win, width, height):
        """chrome=False: Settings opens centred on the primary work area, or right of the
        floating knob's box when they would overlap (the knob is always on top and slides in
        on every button press, e.g. during "Verify physical button order"). The whole window,
        title bar and borders included, stays inside the work area: on a small one it is made
        shorter (the Save and Authorize row stays; the rows above it are squeezed). Its
        content is section 6's."""
        work = primary_work_area(win)
        if not work:
            return None
        frame = window_frame_extent()
        fitted = settings_client_height(work, height, frame)
        overlay = self.overlay
        avoid = getattr(overlay, "rect", None) if overlay is not None else None
        x, y = settings_origin(work, (width, fitted), avoid, frame=frame)
        if fitted != int(height):
            win.geometry(f"{width}x{fitted}")
        win.geometry(f"+{x}+{y}")
        return x, y

    def _report_auth(self, text, authorized):
        """chrome=False (FLOATING_KNOB.md section 9.13): v4 showed the Apple Music authorization
        outcome in the main window's status line, which the floating knob has not got. It goes
        to the open Settings window's note (where authorization was started) and, when it failed
        or Settings is closed, to a tray balloon (take_tray_messages). The knob's LCD status line
        still shows it too."""
        shown = False
        set_note, window = self._setup_set_note, self.setup_window
        if set_note is not None and window is not None:
            try:
                if window.winfo_exists():
                    set_note(text)
                    shown = True
            except tk.TclError:
                pass
        if not authorized or not shown:
            if not isinstance(self.tray_messages, list):
                self.tray_messages = []
            self.tray_messages.append(text)
        return shown

    def take_tray_messages(self):
        """The texts waiting for tray balloons (oldest first); the list is emptied."""
        messages = self.tray_messages
        if not messages:
            return []
        self.tray_messages = []
        return list(messages)

    # ---------------------------------------------------------------- Home Assistant (r3 / r3.1)
    def home_assistant_settings(self):
        """Settings > Home Assistant (r3.1: a page of the Settings window, no longer a dialog)."""
        self.setup(page="home_assistant")

    def _open_setup_page(self, page):
        opener = getattr(self, "_setup_open_page", None)
        if page and callable(opener):
            opener(page)

    def _build_ha_page(self, page, win):
        """The Home Assistant page (Claude Design r3.1, C1), built on its first show. All state and
        copy live in ``HaSettingsModel``; this only mirrors it into Tk widgets. The token is stored
        with Windows DPAPI in the credential store (never settings.json) and a saved token is never
        shown. Test connection is read-only; Save is enabled only after a successful test."""
        from .home_assistant import HomeAssistantAdapter, load_token, save_token
        from .credentials import CredentialError, CredentialStore, STORE_LOCK
        store = CredentialStore(DATA_DIR / "credentials.bin")
        model = self.ha_model = HaSettingsModel(self.config, saved_token=bool(load_token(store)))
        results = queue.Queue()

        def caption(parent, text):
            widget = label(parent, text.upper(), 8, TERTIARY, anchor="w")
            widget.configure(font=(UI_FAMILY, 8, "bold"))
            widget.pack(anchor="w", pady=(10, 4))
            return widget

        def field(parent, variable, show=None):
            widget = tk.Entry(parent, textvariable=variable, bg=SURFACE, fg=TEXT, insertbackground=TEXT,
                              relief="flat", show=show, font=(UI_FAMILY, 11), highlightthickness=1,
                              highlightbackground=RULE, highlightcolor=TEXT)
            return widget
        label(page, "Home Assistant", 23).pack(anchor="w")
        label(page, HA_INTRO, 10, SECONDARY, wraplength=SETUP_NOTE_WRAP, justify="left").pack(anchor="w", pady=(2, 4))
        caption(page, "Address")
        address = tk.StringVar(value=model.address)
        address_field = field(page, address)
        address_field.pack(fill="x", ipady=6)
        cleartext = label(page, "", 9, TERTIARY, wraplength=SETUP_NOTE_WRAP, justify="left", anchor="w")
        cleartext_shown = [False]
        caption(page, "Long-lived access token" + (" · saved (leave empty to keep it)" if model.saved_token else ""))
        token_row = tk.Frame(page, bg=BG)
        token_row.pack(fill="x")
        token = tk.StringVar(value="")
        token_entry = field(token_row, token, show="•")
        token_entry.pack(side="left", fill="x", expand=True, ipady=6)
        show_button = button(token_row, "Show", lambda: toggle())
        show_button.pack(side="left")
        caption(page, "Area")
        area_row = tk.Frame(page, bg=BG)
        area_row.pack(fill="x")
        area_var = tk.StringVar(value="")
        area_menu = tk.OptionMenu(area_row, area_var, "")
        area_menu.configure(bg=SURFACE, fg=TEXT, activebackground=HAIRLINE, activeforeground=TEXT, relief="flat",
                            highlightthickness=0, font=(UI_FAMILY, 10), anchor="w", width=18)
        area_menu.pack(side="left")
        test_button = button(area_row, "Test connection", lambda: test())
        test_button.pack(side="left", padx=(14, 0))
        status_row = tk.Frame(page, bg=BG)
        status_row.pack(fill="x", pady=(12, 8))
        status_mark = tk.Frame(status_row, bg=TERTIARY, width=8, height=8)
        status_mark.pack(side="left", anchor="n", pady=(5, 0), padx=(0, 10))
        status_text = label(status_row, "", 10, TEXT, wraplength=SETUP_NOTE_WRAP - 20, justify="left", anchor="w")
        status_text.pack(side="left", fill="x")
        tk.Frame(page, bg=RULE, height=RULE_WIDTH).pack(fill="x")
        # The footer first (packed at the bottom: a short window squeezes the lists, never Save).
        footer = tk.Frame(page, bg=BG)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        tk.Frame(footer, bg=RULE, height=RULE_WIDTH).pack(fill="x", pady=(0, 12))
        save_button = button(footer, "Save", lambda: save())
        save_button.pack(side="left")
        button(footer, "Cancel", lambda: cancel()).pack(side="left", padx=(12, 0))
        saved_label = label(footer, "", 10, OK, anchor="w")
        saved_label.pack(side="left", padx=(12, 0))
        # FU-2: the lights and scenes scroll between the status rule and the Save rule when the work area
        # cannot fit them all (four lights cut the fourth row); the window grows first (refresh's refit).
        scroller = ScrollPage(page, BG)
        scroller.outer.pack(fill="both", expand=True, pady=(12, 0))
        content = scroller.inner
        placeholder = track_note_wrap(label(content, "", 10, TERTIARY, wraplength=SETUP_NOTE_WRAP, justify="left",
                                            anchor="w"), content)
        lists = tk.Frame(content, bg=BG)
        lights_head = caption(lists, "")
        lights_box = tk.Frame(lists, bg=BG)
        lights_box.pack(fill="x")
        scenes_head = caption(lists, "")
        scenes_box = tk.Frame(lists, bg=BG)
        scenes_box.pack(fill="x")
        shown = {"lists": None, "choices": None}

        def rows(box, entries, empty):
            for child in box.winfo_children():
                child.destroy()
            if empty:
                try:
                    wrap = note_wrap_width(box.winfo_width())
                except (tk.TclError, AttributeError):
                    wrap = SETUP_NOTE_WRAP
                label(box, empty, 10, SECONDARY, wraplength=wrap, justify="left",
                      anchor="w").pack(fill="x", pady=(6, 0))
            for entry in entries:
                row = tk.Frame(box, bg=BG)
                row.pack(fill="x", pady=3)
                if len(entry) == 4:                     # a light: name, value, dot, value colour
                    name, value, dot, colour = entry
                    tk.Frame(row, bg=dot, width=8, height=8).pack(side="left", padx=(0, 10))
                    label(row, name, 11, TEXT, anchor="w").pack(side="left")
                    label(row, value, 10, colour, anchor="e").pack(side="right")
                else:                                   # a scene / script / automation: name, KIND
                    name, kind = entry
                    label(row, name, 11, TEXT, anchor="w").pack(side="left")
                    tag = label(row, kind, 8, TERTIARY, anchor="e")
                    tag.configure(font=(UI_FAMILY, 8, "bold"))
                    tag.pack(side="right")

        def pick(area_id):
            model.choose_area(area_id)
            refresh()

        def refresh():
            try:
                text, colour = model.status_line()
                status_text.configure(text=text)
                status_mark.configure(bg=colour)
                test_button.configure(text=model.test_label())
                note = model.cleartext_note()
                cleartext.configure(text=note)
                if note and not cleartext_shown[0]:
                    cleartext.pack(anchor="w", fill="x", pady=(4, 0), after=address_field)
                    cleartext_shown[0] = True
                elif not note and cleartext_shown[0]:
                    cleartext.pack_forget()
                    cleartext_shown[0] = False
                save_button.configure(state="normal" if model.can_save else "disabled",
                                      bg=TEXT if model.can_save else SURFACE, fg=BG if model.can_save else TERTIARY)
                choices = model.area_choices()
                if choices != shown["choices"]:
                    menu = area_menu["menu"]
                    menu.delete(0, "end")
                    for area_id, name in choices:
                        menu.add_command(label=name, command=lambda area_id=area_id: pick(area_id))
                    shown["choices"] = choices
                area_var.set(model.area_name() if model.area or choices else HA_CHOOSE_AREA)
                data = model.lists()
                if data is None:
                    lists.pack_forget()
                    placeholder.configure(text=model.placeholder())
                    placeholder.pack(fill="x")
                    shown["lists"] = None
                else:
                    placeholder.pack_forget()
                    lists.pack(fill="both", expand=True)
                    if data != shown["lists"]:
                        lights_head.configure(text=data["lights_head"].upper())
                        scenes_head.configure(text=data["scenes_head"].upper())
                        rows(lights_box, data["lights"], data["lights_empty"])
                        rows(scenes_box, data["scenes"], data["scenes_empty"])
                        shown["lists"] = data
                        self._refit_setup()             # FU-2: grow to show every row (work area cap)
                saved_label.configure(text=model.saved_text(time.monotonic()))
            except tk.TclError:
                pass                                    # the window is closing

        def toggle():
            model.toggle_token()
            token_entry.configure(show="" if model.show_token else "•")
            show_button.configure(text="Hide" if model.show_token else "Show")

        def edited(*_args):
            model.edit_address(address.get())
            model.edit_token(token.get())
            refresh()
        address.trace_add("write", edited)
        token.trace_add("write", edited)

        def test():
            if model.status == "testing":
                return
            ha = getattr(self.runtime, "ha", None)
            simulated = not getattr(self, "live", False) and ha is not None
            base, _error = model.begin_test(need_token=not simulated)
            generation = model.generation
            refresh()
            if base is None:
                return
            if simulated:
                model.finish_test(ha.test_connection(), generation)     # the simulator's Home Assistant
                refresh()
                return
            # DD-BUG-037: the saved token only for the saved address (begin_test already refused others).
            typed = model.token.strip() or (load_token(store) if model.saved_token_applies() else "")
            try:
                probe = HomeAssistantAdapter(base, typed, "")
            except ValueError:
                model.finish_test({"ok": False, "outcome": "offline"}, generation)
                refresh()
                return
            import threading
            threading.Thread(target=lambda: results.put((generation, probe.test_connection())),
                             name="nanod-ha-test", daemon=True).start()
            poll()

        def poll():
            try:
                generation, result = results.get_nowait()
            except queue.Empty:
                try:
                    win.after(150, poll)
                except tk.TclError:
                    pass
                return
            model.finish_test(result, generation)
            refresh()

        def save():
            try:
                values = model.save_values()
            except ValueError:
                return                                   # not tested yet: Save does nothing
            try:
                if model.token.strip():
                    with STORE_LOCK:             # one merge at a time with MusicKit (DD-RES-001)
                        try:
                            save_token(store, model.token.strip())
                        except CredentialError:
                            # DD-BUG-001: a file this account cannot unlock is set aside, never blocks Save.
                            if not store.set_aside_if_unreadable():
                                raise
                            save_token(store, model.token.strip())
                # DD-RES-010: the in-memory settings change only once the file has them.
                write_settings({**self.config, **values})
                self.config.update(values)
            except Exception as exc:
                _log.warning("Home Assistant settings not saved (%s)", type(exc).__name__, exc_info=True)
                status_text.configure(text="The Home Assistant settings could not be saved.")
                status_mark.configure(bg=ERROR)
                return
            if getattr(self, "live", False):
                self.runtime.set_home_assistant(self.ha_provider(True))
            else:
                self._sim_ha_area(values["ha_area"])
            model.mark_saved(time.monotonic())
            refresh()
            try:
                win.after(int(HA_SAVED_SECONDS * 1000) + 100, refresh)
            except tk.TclError:
                pass
            self._refresh_strip()

        def cancel():
            model.cancel()
            refresh()
        refresh()
        return model

    # ---------------------------------------------------------------- Apps (plan section 3c)
    def _build_apps_page(self, page, win):
        """Settings > Apps, built on its first show: one row per app profile (icon, name, status badge, source,
        Off / Manual / Auto, what detects it, Rules…, warnings), then Import profile…, Open profiles folder,
        Check for updates and the daily-fetch box. All state and copy live in ``AppsSettingsModel``; every
        change applies and is saved at once (no Save button)."""
        import base64
        model = self.apps_model = AppsSettingsModel(self.config, self.runtime, self._app_library(), save=write_settings)
        track_note_wrap(label(page, APPS_INTRO, 10, SECONDARY, wraplength=SETUP_NOTE_WRAP, justify="left"),
                        page).pack(anchor="w", pady=(2, 12))
        rows_box = tk.Frame(page, bg=BG)
        rows_box.pack(fill="x")
        tk.Frame(page, bg=RULE, height=RULE_WIDTH).pack(fill="x", pady=(4, 12))
        actions = tk.Frame(page, bg=BG)
        actions.pack(fill="x")
        button(actions, APPS_IMPORT, lambda: import_profile()).pack(side="left")
        button(actions, APPS_OPEN_FOLDER, lambda: open_folder()).pack(side="left", padx=(8, 0))
        check_button = button(actions, APPS_CHECK, lambda: check())
        check_button.pack(side="left", padx=(8, 0))
        fetch = tk.BooleanVar(value=model.fetch_daily)
        tk.Checkbutton(page, text=APPS_FETCH_DAILY, variable=fetch, command=lambda: model.set_fetch_daily(fetch.get()),
                       bg=BG, fg=SECONDARY, activebackground=BG, activeforeground=TEXT, selectcolor=SURFACE,
                       font=(UI_FAMILY, 10), highlightthickness=0, borderwidth=0, anchor="w",
                       cursor="hand2").pack(anchor="w", pady=(12, 0))
        status = track_note_wrap(label(page, "", 10, SECONDARY, wraplength=SETUP_NOTE_WRAP, justify="left",
                                       anchor="w"), page)
        status.pack(fill="x", pady=(10, 0))
        icons = []                                   # the rows' PhotoImages live as long as the page
        shown = {"rows": None, "status": None}

        def segmented_row(parent, pid, mode):
            group = tk.Frame(parent, bg=BG)
            for text, value in APP_MODE_CHOICES:
                chosen = value == mode
                widget = button(group, text, lambda value=value: choose(pid, value))
                widget.configure(padx=10, pady=4, bg=RULE if chosen else SURFACE, fg=TEXT if chosen else SECONDARY)
                widget.pack(side="left")
            return group

        def build_rows(rows):
            for child in rows_box.winfo_children():
                child.destroy()
            icons.clear()
            if not rows:
                label(rows_box, APPS_EMPTY, 10, SECONDARY, anchor="w").pack(fill="x")
            for row in rows:
                frame = tk.Frame(rows_box, bg=BG)
                frame.pack(fill="x", pady=(0, 12))
                top = tk.Frame(frame, bg=BG)
                top.pack(fill="x")
                png = icon24_png(row["icon24"])
                image = None
                if png is not None:
                    try:
                        image = tk.PhotoImage(master=win, data=base64.b64encode(png).decode("ascii"), format="png")
                        icons.append(image)
                    except tk.TclError:
                        image = None
                if image is not None:
                    tk.Label(top, image=image, bg=BG, borderwidth=0).pack(side="left", padx=(0, 10))
                else:
                    tk.Frame(top, bg=BG, width=APP_ICON_SIZE, height=APP_ICON_SIZE).pack(side="left", padx=(0, 10))
                label(top, row["name"], 11, TEXT, anchor="w").pack(side="left")
                badge = label(top, row["badge"].upper(), 8, OK if row["badge"] == APP_STATUS_BADGES["tested"]
                              else TERTIARY, anchor="w")
                badge.configure(font=(UI_FAMILY, 8, "bold"))
                badge.pack(side="left", padx=(10, 0))
                segmented_row(top, row["id"], row["mode"]).pack(side="right")
                detail = tk.Frame(frame, bg=BG)
                detail.pack(fill="x", padx=(APP_ICON_SIZE + 10, 0), pady=(4, 0))
                rules = button(detail, APPS_RULES, lambda pid=row["id"]: self._open_rules_dialog(model, pid, win,
                                                                                                  refresh))
                rules.configure(padx=10, pady=4)
                rules.pack(side="right")
                track_note_wrap(label(detail, f"{row['source']} · {row['summary']}", 9, TERTIARY,
                                      wraplength=SETUP_NOTE_WRAP, justify="left", anchor="w"),
                                detail, 110).pack(side="left", fill="x")
                if row["warnings"]:
                    track_note_wrap(label(frame, row["warnings"], 9, NOTICE, wraplength=SETUP_NOTE_WRAP,
                                          justify="left", anchor="w"), frame,
                                    APP_ICON_SIZE + 10).pack(anchor="w", padx=(APP_ICON_SIZE + 10, 0), pady=(4, 0))

        def refresh():
            try:
                rows = model.rows()
                signature = [{k: v for k, v in row.items() if k != "icon24"} for row in rows]
                if signature != shown["rows"]:
                    build_rows(rows)
                    shown["rows"] = signature
                    self._refit_setup()
                updater = self.profile_updater
                busy = updater is not None and updater.busy
                text = profile_updates.TEXT_CHECKING if busy else model.message
                check_button.configure(state="disabled" if busy else "normal")
                if (text, model.message_ok) != shown["status"]:
                    status.configure(text=text, fg=SECONDARY if model.message_ok else NOTICE)
                    shown["status"] = (text, model.message_ok)
                    self._refit_setup()
                fetch.set(model.fetch_daily)
            except tk.TclError:
                pass                                 # the window is closing

        def choose(pid, mode):
            model.set_mode(pid, mode)
            refresh()

        def import_profile():
            path = filedialog.askopenfilename(parent=win, title=APPS_IMPORT.rstrip("…"),
                                              filetypes=[("App profile", "*.json")])
            if path:
                model.import_profile(path)
                refresh()

        def open_folder():
            if not self.open_profiles_folder():
                model.say(APPS_FOLDER_FAILED, ok=False)
                refresh()

        def check():
            if self.check_profile_updates():
                model.say(profile_updates.TEXT_CHECKING)
            refresh()
        self._apps_refresh = refresh
        refresh()
        return model

    def _open_rules_dialog(self, model, pid, parent, on_change=None):
        """Rules… for one app: the profile's own programs and websites (fixed), the owner's (Remove), and a field
        to add one, checked by ``AppsSettingsModel.add_rule`` with its outcome in plain words."""
        name = model.name(pid)
        dialog = tk.Toplevel(parent, bg=BG)
        dialog.title(RULES_TITLE.format(name=name))
        dialog.transient(parent)
        body = tk.Frame(dialog, bg=BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        label(body, RULES_TITLE.format(name=name), 16).pack(anchor="w")
        label(body, RULES_INTRO.format(name=name), 10, SECONDARY, wraplength=440, justify="left").pack(
            anchor="w", pady=(4, 8))
        outcome = label(body, "", 10, SECONDARY, wraplength=440, justify="left", anchor="w")
        boxes = {}
        for kind, title in (("exe", RULES_PROGRAMS), ("host", RULES_WEBSITES)):
            caption = label(body, title.upper(), 8, TERTIARY, anchor="w")
            caption.configure(font=(UI_FAMILY, 8, "bold"))
            caption.pack(anchor="w", pady=(10, 4))
            built_in = model.built_in_rules(pid)[kind]
            if built_in:
                label(body, RULES_BUILT_IN.format(rules=", ".join(built_in)), 9, TERTIARY, wraplength=440,
                      justify="left", anchor="w").pack(anchor="w")
            box = tk.Frame(body, bg=BG)
            box.pack(fill="x")
            entry_row = tk.Frame(body, bg=BG)
            entry_row.pack(fill="x", pady=(4, 0))
            value = tk.StringVar()
            field = tk.Entry(entry_row, textvariable=value, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
                             font=(UI_FAMILY, 11), highlightthickness=1, highlightbackground=RULE, highlightcolor=TEXT)
            field.pack(side="left", fill="x", expand=True, ipady=4)
            add = button(entry_row, RULES_ADD, lambda kind=kind, value=value: add_rule(kind, value))
            add.configure(padx=10, pady=4)
            add.pack(side="left", padx=(8, 0))
            field.bind("<Return>", lambda _e, kind=kind, value=value: add_rule(kind, value))
            boxes[kind] = box

        def fill():
            for kind, box in boxes.items():
                for child in box.winfo_children():
                    child.destroy()
                values = model.rules(pid)[kind]
                if not values:
                    label(box, RULES_NONE, 10, TERTIARY, anchor="w").pack(anchor="w", pady=2)
                for item in values:
                    row = tk.Frame(box, bg=BG)
                    row.pack(fill="x", pady=2)
                    label(row, item, 11, TEXT, anchor="w").pack(side="left")
                    remove = button(row, RULES_REMOVE, lambda kind=kind, item=item: remove_rule(kind, item))
                    remove.configure(padx=10, pady=2)
                    remove.pack(side="right")

        def show(ok, text):
            outcome.configure(text=text, fg=SECONDARY if ok else NOTICE)
            if on_change is not None:
                on_change()

        def add_rule(kind, value):
            ok, text = model.add_rule(pid, kind, value.get())
            if ok:
                value.set("")
                fill()
            show(ok, text)

        def remove_rule(kind, item):
            ok, text = model.remove_rule(pid, kind, item)
            fill()
            show(ok, text)
        outcome.pack(anchor="w", fill="x", pady=(10, 0))
        button(body, RULES_DONE, dialog.destroy).pack(anchor="w", pady=(12, 0))
        fill()
        try:
            dialog.grab_set()
        except tk.TclError:
            pass
        return dialog

    def open_profiles_folder(self):
        """Open profiles\\user\\ (made if missing) in Explorer. True when asked to open. Never raises."""
        try:
            folder = paths.profiles_user_dir()
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
            return True
        except Exception as exc:
            _log.warning("The profiles folder could not be opened (%s)", type(exc).__name__)
            return False

    def _profile_updater(self):
        if self.profile_updater is None:
            self.profile_updater = profile_updates.ProfileUpdater(
                paths.profiles_updates_dir(), paths.bundled_profiles_dir(), app_version(),
                user_dir=paths.profiles_user_dir())
        return self.profile_updater

    def check_profile_updates(self):
        """Start one profile update check off the Tk thread (Settings' Check for updates, or the daily check).
        False when one is already running."""
        updater = self._profile_updater()
        library = self._app_library()
        updater.names = {profile.id: app_display_name(profile) for profile in library.profiles()} if library is not None else {}
        return updater.start()

    PROFILE_UPDATE_RETRY_S = 3600        # a failed daily check tries again after this long

    def _profile_updates_tick(self, now=None):
        """Every Tk tick: collect a finished check and, in the live app with the daily fetch on, start the day's
        check (profile_updates.due). Cheap: a time comparison and a queue poll."""
        updater = self.profile_updater
        if updater is not None:
            result = updater.poll()
            if result is not None:
                self._profile_update_finished(result)
        if not getattr(self, "live", False) or getattr(self, "smoke", False):
            return
        now = time.time() if now is None else now
        if now < getattr(self, "_profile_update_retry_at", 0):
            return
        config = self.config
        if profile_updates.due(config.get("profile_updates"), config.get("profile_updates_last"), now):
            if updater is None or not updater.busy:
                self._profile_update_retry_at = now + self.PROFILE_UPDATE_RETRY_S
                self.check_profile_updates()

    def _profile_update_finished(self, result):
        """On the Tk thread: remember when (a good check only), reload the profiles when files changed, and
        show the outcome on Settings > Apps."""
        if result.ok:
            self.config["profile_updates_last"] = profile_updates.normal_last(result.finished)
            try:
                write_settings(self.config)
            except OSError:
                _log.warning("The profile check time could not be written to settings.json")
        if result.updated:
            reload = getattr(self.runtime, "reload_profiles", None)
            try:
                if callable(reload):
                    reload()
                elif self.app_library is not None:
                    self.app_library.reload()
            except Exception:
                _log.warning("Profiles could not be reloaded after an update", exc_info=True)
        _log.info("Profile update check: ok=%s updated=%d kept=%d", result.ok, len(result.updated), len(result.kept))
        model = self.apps_model
        if model is not None:
            model.say(result.text, ok=result.ok and not result.kept)
        refresh = self._apps_refresh
        if refresh is not None:
            refresh()

    def _sim_ha_area(self, area_id):
        """Simulator: Save switches the simulated Home Assistant to the chosen area (as the live
        adapter is rebuilt for it)."""
        ha = getattr(getattr(self, "runtime", None), "ha", None)
        if ha is None or not hasattr(ha, "area_id") or not area_id or getattr(ha, "area_id", "") == area_id:
            return
        switch = getattr(ha, "switch_area", None)
        if callable(switch):
            switch(area_id)

    def status_strip(self):
        """The strip's model now (``strip_model`` over this app's runtime; K3 14.1)."""
        runtime = self.runtime
        live = getattr(runtime, "device", None) is self.device
        return strip_model(runtime, firmware=firmware_version(self.device) if live else None,
                           speaker_ip=self.config.get("speaker_ip", ""),
                           credentials_locked=bool(getattr(self, "credentials_locked", False)),
                           app=app_version())

    def _strip_columns(self):
        """How many columns the strip shows now (4 with the Home Assistant bridge); 3 on any error."""
        try:
            return len(self.status_strip())
        except Exception:
            return 3

    def _refresh_strip(self):
        strip = self.strip
        if strip is None:
            return False
        try:
            return strip.update(self.status_strip())
        except tk.TclError:
            self.strip = None               # Settings was closed
            return False
        except Exception:
            self._log_failure("strip", "Settings status strip could not be updated")
            return False

    def _schedule_strip(self, win):
        """Refresh the strip every STRIP_REFRESH_MS while this Settings window is open (K3 14.1)."""
        def tick():
            try:
                if self.closing or self.setup_window is not win or not win.winfo_exists():
                    return
            except Exception:
                return
            self._refresh_strip()
            refresh_recal = getattr(self, "_setup_refresh_recal", None)
            if refresh_recal is not None:
                refresh_recal()                 # DD-BUG-051: the Keep / Dismiss row follows the knob
            try:
                win.after(STRIP_REFRESH_MS, tick)
            except Exception:
                pass
        try:
            win.after(STRIP_REFRESH_MS, tick)
        except Exception:
            pass                               # a stand-in window without a timer (tests)

    def _present_setup(self, win):
        """chrome=False: bring Settings forward (the tray click grants foreground rights)."""
        for step in (win.deiconify, win.lift, win.focus_force):
            try:
                step()
            except tk.TclError:
                pass

    def _setup_action(self, name):
        action = (self.setup_actions or {}).get(name)
        if action is not None:
            action()

    # ----------------------------------------------------------------- loop
    def poll(self):
        if self.closing:
            return
        try:
            self._poll_once()
        finally:
            # A failing tick never stops the loop.
            if not self.closing:
                self._poll_id = self.root.after(POLL_MS, self.poll)

    def _persist_pinned_room(self):
        """DD-BUG-047: remember, once, the room the configured speaker reported (SonosAdapter pins
        it on its first read), so a later group change keeps following that room."""
        if not getattr(self, "live", False) or self.config.get("room_uid"):
            return
        sonos = getattr(getattr(self, "runtime", None), "sonos", None)
        uid = getattr(sonos, "room_uid", None)
        if not isinstance(uid, str) or not uid or getattr(sonos, "host", None) != self.config.get("speaker_ip"):
            return
        self.config["room_uid"] = uid
        self.config[ROOM_UID_SOURCE_KEY] = ROOM_UID_FROM_SPEAKER
        try:
            write_settings(self.config)
        except OSError:
            _log.warning("The Sonos room could not be saved to settings.json")

    def _poll_once(self):
        """One tick. Each stage is isolated: a failure is counted per stage
        (``failure_counts``, read by the smoke test), logged at a limited rate,
        and never stops the stages after it."""
        try:
            self.runtime.poll()
        except Exception:
            self._log_failure("runtime", "Runtime poll failed")
        try:
            self._watch_claim()
        except Exception:
            self._log_failure("claim", "Knob claim could not be tracked")
        try:
            self._recal_guard().observe(self.runtime)   # DD-BUG-051: a disconnect withdraws Keep new direction
        except Exception:
            self._log_failure("recalibration", "The recalibration result could not be followed")
        if self.auth:
            try:
                event = self.auth.events.get_nowait()
                authorized = event["event"] == "authorized"
                text = "Apple Music connected · Home, then Browse" if authorized else event.get("message", "Authorization incomplete")
                self.controller.screen.status = text
                if not self.chrome:
                    self._report_auth(text, authorized)
            except queue.Empty:
                pass
            except Exception:
                self._log_failure("auth", "Apple Music authorization event could not be read")
        try:
            self._persist_pinned_room()
        except Exception:
            self._log_failure("room", "The Sonos room could not be remembered")
        try:
            self._profile_updates_tick()
        except Exception:
            self._log_failure("profile-updates", "The profile update check could not be followed")
        try:
            self._sync_picker_icons()
        except Exception:
            self._log_failure("picker-icons", "Picker icons could not be updated")
        try:
            self._sync_presenters()
        except Exception:
            self._log_failure("presenters", "Presenter settings could not be updated")
        try:
            self.render()
        except Exception:
            self._log_failure("render", "Control center view could not be updated")

    def close(self):
        if self.closing:
            return
        self.closing = True
        if self._poll_id is not None:
            # No tick may fire into a destroyed root ("invalid command name ...poll").
            try:
                self.root.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        # DD-RES-014: release the knob first, so it never keeps the claimed screen behind the
        # overlay, stage and service joins below (each bounded, together several seconds).
        released = False
        if self.device is not None and not self.device.closed:
            try:
                self.device.submit("close")
                released = True
            except Exception:
                _log.exception("Knob could not be released")
        if self.overlay is not None:
            # Its thread tears the window down before the root is destroyed (joined <= 1 s).
            try:
                self.overlay.close()
            except Exception:
                _log.exception("Floating knob did not close cleanly")
        if self.stage is not None:
            # NanoD-stage and the art workers (K4 4.1): torn down on their own threads (<= 2 s).
            try:
                self.stage.close()
            except Exception:
                _log.exception("Stage did not close cleanly")
        try:
            if released and getattr(self.runtime, "device", None) is self.device:
                # Runtime.close() minus a second device close (the bridge may already refuse it).
                self.runtime.shutdown(close_device=False, join_timeout=SHUTDOWN_JOIN_S)
            else:
                self.runtime.close()
        except Exception:
            _log.exception("Runtime did not close cleanly")
        if self.auth:
            self.auth.stop()
        # Serial worker owns release/close; give it time without blocking Tk.
        deadline = time.monotonic() + 4
        def finish():
            if self.device and not self.device.closed and time.monotonic() < deadline:
                self.root.after(50, finish)
            else:
                self.root.destroy()
        finish()
