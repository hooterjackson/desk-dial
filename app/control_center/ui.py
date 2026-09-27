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
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, font
import webbrowser

from .controller import Controller, PROFILES
# The Knob Face LED colour model lives in knob_face (Tk-free, shared with the floating
# knob); these names stay importable from here for the mirror and existing callers.
from .knob_face import (
    BUTTON_FACE, LED_FLOOR, LED_MATCH_TOLERANCE, LED_PALETTE, OPTICAL_ALPHA, STRIP_MIN_ALPHA,
    led_source, optical_alpha, ring_display, ring_palette, strip_display,
)
from .presentation import LED_STYLES, RING_SEGMENTS
from .preview_lights import PreviewLights
from .simulation import (FakeStagePresenter, SimControls, SimulatedAppleMusic, SimulatedDevice, SimulatedSonos,
                         SimulatedToasts, SimulatedWindows)
from . import paths
from .runtime import Runtime
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
SETUP_SUBTITLE = ("Artwork, LEDs, Motion and the switcher background apply when saved. "
                  "Other changes need a reconnect or a restart.")
SETTINGS_TITLE = "Desk Dial Settings"
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
}
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
)
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


def fit_height(window, width, height, margin=SCREEN_MARGIN):
    """Grow a top-level ``window`` of ``width`` x ``height`` until its packed
    content fits, capped to the screen. Never shrinks it.

    Returns the new height, or None when nothing changed (content fits, the
    window is not a real Tk window, or Tk refused).
    """
    if not isinstance(window, tk.Wm):
        return None
    try:
        window.update_idletasks()
        needed = min(window.winfo_reqheight(), window.winfo_screenheight() - margin)
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


def refit_height(window, size):
    """Grow ``window`` again after its content grew (a longer message), never shrinking.

    ``size`` is the [width, height] the window was last given (updated in
    place); once the window is mapped its real size is used instead, so a size
    the user chose is kept unless the content no longer fits it.
    """
    if not isinstance(window, tk.Wm):
        return None
    try:
        if window.winfo_ismapped():
            size[:] = [window.winfo_width(), window.winfo_height()]
    except tk.TclError:
        return None
    grown = fit_height(window, *size)
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
    current. Never raises into the reader."""

    def __init__(self, overlay=None, stage=None, clock=time.perf_counter, windows=None):
        self.overlay = overlay
        self.stage = stage
        self.windows = windows          # WindowsAdapter (note_touch: the picker's GPU chrome, CAROUSEL.md 12.4)
        self.clock = clock
        self.button_order = [0, 1, 2, 3]
        self.stage_open = False
        self.posted = 0
        self.failures = 0
        self._touched = None

    def handle(self, kind, values, t=None):
        t = self.clock() if t is None else t
        try:
            control_id = values.get("id")
            overlay = self.overlay
            if kind == "position":
                position = values.get("position", values.get("p"))
                delta = values.get("delta")
                if overlay is not None and type(position) is int:
                    overlay.post_input("position", (position, delta if type(delta) is int else 0), control_id, t)
                stage = self.stage
                if stage is not None and self.stage_open and type(position) is int:
                    stage.position(control_id, position, t)
            elif kind == "limit":
                direction = values.get("dir")
                if overlay is not None and direction in (-1, 1):
                    overlay.post_input("limit", direction, control_id, t)
            elif kind == "button":
                raw = values.get("button", values.get("index"))
                order = self.button_order
                if overlay is not None and raw in order:
                    overlay.post_input("press", order.index(raw), control_id, t)
            else:
                return False
            self.posted += 1
            self._warm(t)
            return True
        except Exception:
            self.failures += 1
            return False

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
                    self.failures += 1


def install_fast_path(device, fast):
    """Wrap the DeviceBridge's ``_emit`` (reader thread) so every input event reaches ``fast``
    first, stamped at the read; everything else, and the event itself, is queued as before."""
    emit = getattr(device, "_emit", None)
    if not callable(emit) or getattr(emit, "_nanod_fast_path", False):
        return False

    def fast_emit(kind, **values):
        if kind in ("position", "limit", "button"):
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


def strip_model(runtime, *, firmware=None, speaker_ip=""):
    """The Settings status strip (K3 14.1; VOC settings.knob/sonos/apple copy; BS:1373-1378): three
    columns, each {name, ok, state, detail, action, key, primary}. ``key`` names the action for the
    window (knob_settings, troubleshoot, manual_ip, renew_signin, sign_in)."""
    connected = bool(getattr(runtime, "device_connected", False) and getattr(runtime, "device_supported", False))
    if connected:
        knob = {"name": "Knob", "ok": True, "state": "Connected",
                "detail": f"USB · firmware {firmware}" if firmware else "USB",
                "action": "Knob settings…", "key": "knob_settings", "primary": False}
    else:
        knob = {"name": "Knob", "ok": False, "state": "Not connected",
                "detail": "Waiting for the knob on USB. The knob’s own controls still work.",
                "action": "Troubleshoot…", "key": "troubleshoot", "primary": False}
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
    else:
        apple = {"name": "Apple Music", "ok": True, "state": "Signed in", "detail": "Library and likes available",
                 "action": "Renew sign-in…", "key": "renew_signin", "primary": False}
    return [knob, sonos, apple]


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


class SettingsStrip:
    """The status strip at the top of Settings (K3 14.1; S01 12; BS:435-446): three columns, each
    an 11 px uppercase name, an 8 px square mark (#6ED996 OK, #FF7A66 problem), the state, the
    detail and one action button (a primary light button for an expired or missing sign-in), with a
    2 px rule under the strip. ``update(model)`` repaints from ``strip_model``; ``actions`` maps an
    action key to a callable. Tk thread only."""

    def __init__(self, parent, actions):
        self.actions = dict(actions)
        self.frame = tk.Frame(parent, bg=BG)
        row_of_columns = tk.Frame(self.frame, bg=BG)
        row_of_columns.pack(fill="x")
        tk.Frame(self.frame, bg=RULE, height=RULE_WIDTH).pack(fill="x")      # the 2 px rule under the strip
        self.detail = label(self.frame, "", 10, SECONDARY, wraplength=SETUP_NOTE_WRAP, justify="left", anchor="w")
        self._detail_shown = False
        self.columns = []
        self.model = None
        for index in range(3):
            if index:
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
            detail = label(column, "", 9, STRIP_DETAIL_COLOR, anchor="w", justify="left", wraplength=160)
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
    fast_path = None
    sim_controls = None
    sim_device = None
    sim_knob = False            # the simulator's runtime uses sim_device (the picker's PC connection)
    sim_window = None
    strip = None
    mirror_lights = None

    def __init__(self, root, smoke=False, live=False, chrome=True, overlay=None, stage=None):
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
        self.fast_path = FastPath(overlay=overlay if hasattr(overlay, "post_input") else None, stage=stage)
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
        if self.controller.screen.mode != "home":
            self.controller.button(0)

    # ------------------------------------------------------------ settings
    @staticmethod
    def load_config():
        default = {"speaker_ip": "192.168.1.50", "room_uid": "",
                   "port": "COM8", "button_order": [0, 1, 2, 3], "button_order_verified": False,
                   "led_style": DEFAULT_LED_STYLE, "artwork": True,
                   "picker_background": DEFAULT_PICKER_BACKGROUND, "motion": DEFAULT_MOTION}
        try:
            value = json.loads((DATA_DIR / "settings.json").read_text(encoding="utf-8"))
            default.update({k: value[k] for k in default if k in value})
            # alive LED tuning (ALIVE.md sections 3 and 10.2): optional, no UI, kept only when
            # present so Save writes back exactly what the user put there (never a null).
            # Validated where it is applied (runtime.led_tuning); never logged by value.
            for key in LED_TUNING_KEYS:
                if key in value:
                    default[key] = value[key]
        except (OSError, ValueError, TypeError):
            pass
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
        store = CredentialStore(DATA_DIR / "credentials.bin")
        credentials = store.load()
        return (SonosAdapter(self.config["speaker_ip"], room_uid=self.config.get("room_uid") or None),
                AppleMusicClient(credentials, credential_loader=store.load), WindowsAdapter(self.root,
                    on_hotkey=lambda: self.runtime.hotkey(),
                    on_cancel=lambda: self.controller.button(0),
                    on_focus_lost=lambda: self.controller.dismiss_windows(),
                    on_closed=lambda: self.render(force=True),
                    # The carousel's own input (CAROUSEL.md section 1): Enter or a centre-card
                    # click is the green button, Esc the red one (on_cancel), arrows/wheel turn.
                    on_switch=lambda: self.controller.button(3),
                    on_turn=self._picker_turn))

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
                hosts = (self.config["speaker_ip"],)
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
            runtime = Runtime(controller, sonos, apple, windows, device,
                              artwork=artwork, accents=accents, icons=icons, stage=stage, toasts=toasts)
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
        self.env_button = button(header, "LIVE · DEN" if self.live else "SIMULATOR", self.toggle_environment)
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
        self.target_label = label(right, "Den", 22, anchor="w")
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
        self._suppressed = {reason: True for reason in ("explorer", "upnext") if previous.get(reason)}
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
        if overlay is None or getattr(overlay, "state", None) == "disabled":
            return   # no floating knob (its window could not be created): nothing to draw
        connected = bool(runtime.device_connected)
        self._update_suppression(connected)
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
        """Tray "Show knob": the overlay's peek (a touch with its own duration)."""
        if self.overlay is not None:
            self.overlay.peek(seconds)

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
            try:
                refit_height(self.setup_window, self.setup_size)   # a long notice grows, never clips
            except Exception:
                _log.exception("Setup window could not be refitted")

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
            self.env_button.configure(text="LIVE · DEN" if self.live else "SIMULATOR")
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
            order = list(getattr(runtime, "button_order", fast.button_order))
            if order != fast.button_order:
                fast.button_order = order
            mode = runtime.controller.screen.mode
            surfaces = getattr(runtime, "open_surfaces", None) or ()
            fast.stage_open = mode in ("explorer", "upnext") or "explorer" in surfaces or "upnext" in surfaces
            warmer = self._picker_warmer(runtime)
            if getattr(fast, "windows", None) is not warmer:
                fast.windows = warmer
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
    def setup(self):
        """The Setup window. chrome=False (tray Settings…): not transient for the withdrawn
        root (Tk never maps a transient of an unmapped master) and brought forward with
        deiconify/lift/focus_force; with ``setup_actions`` (tray failure) it also offers
        Connect/Disconnect and Quit. Its settings content is the same in both modes."""
        existing = self.setup_window
        if existing and existing.winfo_exists():
            if self.chrome:
                existing.lift()
                return
            if self._setup_has_actions or not self.setup_actions:
                self._present_setup(existing)
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

        def focus_field(name):
            widget = entry_widgets.get(name)
            if widget is not None:
                try:
                    widget.focus_set()
                    widget.select_range(0, "end")
                except tk.TclError:
                    pass

        def troubleshoot():
            self.strip.show_detail(self.runtime.device_status)
            focus_field("Knob USB port")
        # K3 14.1: the status strip at the top of Settings, where recovery lives.
        self.strip = SettingsStrip(win, {
            "knob_settings": lambda: focus_field("Knob USB port"),
            "troubleshoot": troubleshoot,
            "manual_ip": lambda: focus_field("Den speaker IP"),
            "renew_signin": lambda: authorize(),
            "sign_in": lambda: authorize(),
        }).pack(fill="x")
        self._refresh_strip()
        body = tk.Frame(win, bg=BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        heading = label(body, "Connect your desk", 23)
        heading.pack(anchor="w")
        label(body, SETUP_SUBTITLE, 10, SECONDARY, wraplength=SETUP_NOTE_WRAP,
              justify="left").pack(anchor="w", pady=(2, 15))

        def entry(name, default=""):
            label(body, name, 10, SECONDARY).pack(anchor="w", pady=(9, 3))
            value = tk.StringVar(value=default)
            widget = tk.Entry(body, textvariable=value, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=(UI_FAMILY, 11), highlightthickness=RULE_WIDTH, highlightbackground=HAIRLINE,
                              highlightcolor=RULE)
            widget.pack(fill="x", ipady=6)
            fields[name] = value
            entry_widgets[name] = widget
            return value
        ip = entry("Den speaker IP", self.config["speaker_ip"])
        port = entry("Knob USB port", self.config["port"])
        order = entry("Raw button indices, physical left to right", ",".join(map(str, self.config["button_order"])))
        label(body, "Press each physical button during setup and note its raw index below.", 9, TERTIARY).pack(anchor="w", pady=5)
        probe_label = label(body, "Button order still needs physical verification", 10, SECONDARY)
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
        button(body, "Verify physical button order", calibrate).pack(anchor="w", pady=4)
        team = entry("Apple Team ID")
        key = entry("MusicKit Key ID")
        key_path = tk.StringVar()
        key_row = tk.Frame(body, bg=BG)
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
        presentation_row = tk.Frame(body, bg=BG)
        presentation_row.pack(fill="x", pady=(4, 10))
        def segmented(title, variable, options, parent=presentation_row, disabled=()):
            group = tk.Frame(parent, bg=BG)
            group.pack(side="left", padx=(0, 28))
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
            for text, value in options:
                widgets[value] = button(row, text, lambda v=value: choose(v))
                if value in disabled:
                    widgets[value].configure(state="disabled", disabledforeground=TERTIARY, cursor="")
                widgets[value].pack(side="left")
            paint()
            return group
        segmented("Album artwork", artwork_choice, (("On", "on"), ("Off", "off")))
        segmented("LEDs", led_choice, LED_STYLE_CHOICES)
        # The Windows switcher's backdrop, on a row of its own.
        switcher_row = tk.Frame(body, bg=BG)
        switcher_row.pack(fill="x", pady=(0, 10))
        unavailable = tuple(value for _, value in PICKER_BACKGROUND_CHOICES if value not in backgrounds)
        switcher_group = segmented("Switcher background", background_choice, PICKER_BACKGROUND_CHOICES,
                                   switcher_row, disabled=unavailable)
        if unavailable:
            label(switcher_group, PICKER_BACKGROUND_FALLBACK_NOTE, 9, TERTIARY, wraplength=SETUP_NOTE_WRAP,
                  justify="left").pack(anchor="w", pady=(4, 0))
        # K3 14.3 (settings.motion): Match Windows (the Animation effects setting) / Full / Reduced.
        stored_motion = self.config.get("motion", DEFAULT_MOTION)
        motion_choice = tk.StringVar(value=stored_motion if stored_motion in MOTION_VALUES else DEFAULT_MOTION)
        segmented("Motion", motion_choice, MOTION_CHOICES, switcher_row)
        # Space for the Save confirmation is reserved up front (the fitted window
        # already includes it); a longer message grows the window (refit_height).
        saved_note = SETUP_SAVED_NOTES[bool(getattr(self, "live", False))]
        try:
            reserved = max(SETUP_NOTE_LINES, wrapped_lines(win, saved_note, 10, SETUP_NOTE_WRAP))
        except Exception:
            reserved = SETUP_NOTE_LINES   # measuring is best effort; refit_height still applies
        note = self.setup_note = label(body, "", 10, SECONDARY, wraplength=SETUP_NOTE_WRAP,
                                       justify="left", anchor="nw", height=reserved)
        note.pack(fill="x")
        fitted = self.setup_size = list(SETUP_SIZE)

        def set_note(text):
            # Natural height from now on: within the reservation nothing moves;
            # beyond it (a long error) the window grows instead of clipping.
            note.configure(text=text, height=0)
            try:
                refit_height(win, fitted)
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
                ipaddress.ip_address(ip.get().strip())
            except ValueError:
                set_note("Enter a valid speaker IP and each index 0, 1, 2, 3 once.")
                return
            led = led_choice.get() if led_choice.get() in LED_STYLES else DEFAULT_LED_STYLE
            # A stored choice the fallback cannot show was never offered here: it is kept.
            background = stored_background if background_locked else background_choice.get()
            background = background if background in PICKER_BACKGROUNDS else DEFAULT_PICKER_BACKGROUND
            motion = motion_choice.get() if motion_choice.get() in MOTION_VALUES else DEFAULT_MOTION
            self.config.update(speaker_ip=ip.get().strip(), port=port.get().strip(), button_order=mapping,
                               led_style=led, artwork=artwork_choice.get() != "off",
                               picker_background=background, motion=motion)
            self.config["button_order_verified"] = len(captured) == 4 and mapping == captured
            self._apply_presentation()
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                (DATA_DIR / "settings.json").write_text(json.dumps(self.config, indent=2), encoding="utf-8")
            except OSError:
                set_note("Artwork, LEDs, the switcher background and Motion applied, but the settings file "
                         "could not be written.")
                return
            set_note(saved_note)
            self._refresh_strip()
        def authorize():
            try:
                from .credentials import CredentialStore, MusicKitCredentials, AuthServer
                store = CredentialStore(DATA_DIR / "credentials.bin")
                credentials = MusicKitCredentials.from_key_file(team.get(), key.get(), key_path.get()) if key_path.get() else store.load()
                # Keep the working grant until the replacement consent succeeds.
                # Saving a freshly chosen key here would erase its user token.
                if self.auth:
                    self.auth.stop()
                self.auth = AuthServer(credentials, on_token=store.save)
                url = self.auth.start()
                webbrowser.open(url)
                set_note("Complete Apple Music authorization in your browser.")
            except Exception as exc:
                set_note(str(exc) if isinstance(exc, RuntimeError) else "Could not start MusicKit authorization")
        # Created last (keyboard order), packed first at the bottom: a short
        # window squeezes the rows above, never Save or Authorize.
        actions = tk.Frame(body, bg=BG)
        actions.pack(side="bottom", fill="x", pady=(15, 0), before=heading)
        button(actions, "Save settings", save).pack(side="left")
        button(actions, "Authorize Apple Music", authorize).pack(side="right")
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
        def done():
            self.runtime.on_button_probe = None
            if self._setup_set_note is set_note:
                self._setup_set_note = None
            self.strip = None
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

    def status_strip(self):
        """The strip's model now (``strip_model`` over this app's runtime; K3 14.1)."""
        runtime = self.runtime
        live = getattr(runtime, "device", None) is self.device
        return strip_model(runtime, firmware=firmware_version(self.device) if live else None,
                           speaker_ip=self.config.get("speaker_ip", ""))

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
