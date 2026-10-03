"""Keys by intent for app profiles (plan section 4a/4b, S1 lane DD-A): HID usages -> Windows keys.

Karl Malota's profiles (katbinaris/NanoD_RatchetH1 ``feat/firmware-esp-idf-quadra``,
``NanoDepsidf/src/app_profiles/app_profile.h``; adapted with his permission) name keys as USB HID
usages: key *positions* on a US keyboard. Desk Dial reads each usage as the US character or key it
means and sends that on whatever layout the foreground window uses:

* letters and digits -> VK_A..VK_Z / VK_0..VK_9 (every Windows layout keeps those virtual keys on
  the letter or digit, wherever it sits: on German QWERTZ Z and Y swap places, VK_Z is still Z);
* punctuation (``- = [ ] \\ ; ' ` , . /``) -> the character, resolved at send time with
  ``VkKeyScanExW(char, foreground HKL)``. A character the layout reaches only with modifiers the
  chord doesn't already hold (AltGr, or a Shift the chord lacks), or doesn't have at all, is refused:
  ``None``, the knob says "Not on this keyboard". The wrong key is never sent;
* F1-F24, Enter, Esc, Backspace, Tab, Space, Insert / Delete / Home / End / PgUp / PgDn, the arrows,
  the keypad and the modifier keys themselves -> fixed virtual keys. ``EXTENDED_VKS`` (and
  ``KeySpec.extended``) mark the ones that need ``KEYEVENTF_EXTENDEDKEY``.

Modifiers: Karl's ``KEYBOARD_MODIFIER_*`` bits map Cmd (GUI) -> Ctrl (or ``gui_to``), Option -> Alt,
Ctrl -> Ctrl, Shift -> Shift, left and right alike (``map_mods``). The sidecar writes Windows chords as
text, ``"ctrl+alt+t"`` (``parse_chord``; key tokens in ``from_text``).

API (lanes DD-B and DD-C build on it)::

    KeySpec(hid, vk, char, extended, label)   vk for layout-independent keys, char for punctuation
    Chord(mods, key)                           mods subset of {'ctrl','shift','alt','win'}
    from_hid(usage) -> KeySpec                 ValueError for unsupported usages
    from_text(token) -> KeySpec                "z", "F5", "/", "num1", "delete"
    map_mods(karl_bits, gui_to='ctrl') -> frozenset[str]
    parse_chord(text) -> Chord                 ValueError in plain words
    resolve(spec, hkl, vk_key_scan=None) -> (vk, extra mods) | None
    resolve_chord(chord, hkl, vk_key_scan=None) -> (vk, mods) | None
    chord_text(chord) -> str                   "ctrl+alt+t" (round trips through parse_chord)
    display_mods(mods) -> int                  wire keycap bits CTRL 1, SHIFT 2, ALT 4, WIN 8
    blocked(chord, browser=False) -> str|None  why a chord is never sent (S3 review DD-1), else None
    EXTENDED_VKS, MOD_VK

Pure apart from the default ``vk_key_scan`` (``user32.VkKeyScanExW``, loaded on first use).
"""
from __future__ import annotations

from dataclasses import dataclass

MODS = ("ctrl", "shift", "alt", "win")
MOD_ORDER = {name: index for index, name in enumerate(MODS)}
MOD_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
DISPLAY_BITS = {"ctrl": 0x01, "shift": 0x02, "alt": 0x04, "win": 0x08}   # APP_PROFILES.md section 5
LABEL_MAX = 7                                                            # the wire's keycap label

# Karl's KEYBOARD_MODIFIER_* bits (TinyUSB class/hid/hid.h)
_KARL_MOD = {0: "ctrl", 1: "shift", 2: "alt", 3: "gui", 4: "ctrl", 5: "shift", 6: "alt", 7: "gui"}

VK_RETURN, VK_ESCAPE, VK_BACK, VK_TAB, VK_SPACE = 0x0D, 0x1B, 0x08, 0x09, 0x20
VK_PRIOR, VK_NEXT, VK_END, VK_HOME = 0x21, 0x22, 0x23, 0x24
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28
VK_INSERT, VK_DELETE = 0x2D, 0x2E
VK_NUMPAD0 = 0x60
VK_MULTIPLY, VK_ADD, VK_SUBTRACT, VK_DECIMAL, VK_DIVIDE = 0x6A, 0x6B, 0x6D, 0x6E, 0x6F
VK_F1, VK_F13 = 0x70, 0x7C
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
VK_LWIN, VK_RWIN = 0x5B, 0x5C

# Keys whose scan code is an E0 (extended) one: KEYEVENTF_EXTENDEDKEY. The numpad Enter shares
# VK_RETURN with the main Enter, so it is extended through KeySpec.extended, not by its VK.
EXTENDED_VKS = frozenset({VK_PRIOR, VK_NEXT, VK_END, VK_HOME, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_INSERT,
                          VK_DELETE, VK_DIVIDE, VK_RCONTROL, VK_RMENU, VK_LWIN, VK_RWIN})


@dataclass(frozen=True)
class KeySpec:
    hid: int               # Karl's HID usage
    vk: int | None         # a layout-independent virtual key, or None (punctuation: `char`)
    char: str | None       # the US character the usage types, resolved per layout at send time
    extended: bool         # KEYEVENTF_EXTENDEDKEY
    label: str             # keycap text for the knob (<= 7 chars): "E", "F5", "/", "NUM1", "DEL"


@dataclass(frozen=True)
class Chord:
    mods: frozenset        # subset of {'ctrl', 'shift', 'alt', 'win'}; already Windows-mapped
    key: KeySpec


def _table():
    """{hid: KeySpec} and {text token: hid}: the one table both directions read."""
    specs, names = {}, {}

    def add(hid, vk, char, label, *tokens, extended=False):
        specs[hid] = KeySpec(hid, vk, char, extended or (vk in EXTENDED_VKS), label)
        for token in (label.lower(), *tokens):
            names.setdefault(token, hid)

    for i in range(26):
        letter = chr(ord("A") + i)
        add(0x04 + i, ord(letter), None, letter)
    for i, digit in enumerate("1234567890"):
        add(0x1E + i, ord(digit), None, digit)
    add(0x28, VK_RETURN, None, "ENTER", "return")
    add(0x29, VK_ESCAPE, None, "ESC", "escape")
    add(0x2A, VK_BACK, None, "BKSP", "backspace")
    add(0x2B, VK_TAB, None, "TAB")
    add(0x2C, VK_SPACE, None, "SPACE")
    for hid, char in zip((0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38),
                         "-=[]\\;'`,./"):
        add(hid, None, char, char)
    for i in range(12):
        add(0x3A + i, VK_F1 + i, None, f"F{i + 1}")
        add(0x68 + i, VK_F13 + i, None, f"F{i + 13}")
    add(0x49, VK_INSERT, None, "INS", "insert")
    add(0x4A, VK_HOME, None, "HOME")
    add(0x4B, VK_PRIOR, None, "PGUP", "pageup")
    add(0x4C, VK_DELETE, None, "DEL", "delete")
    add(0x4D, VK_END, None, "END")
    add(0x4E, VK_NEXT, None, "PGDN", "pagedown")
    add(0x4F, VK_RIGHT, None, "RIGHT")
    add(0x50, VK_LEFT, None, "LEFT")
    add(0x51, VK_DOWN, None, "DOWN")
    add(0x52, VK_UP, None, "UP")
    add(0x54, VK_DIVIDE, None, "NUM/")
    add(0x55, VK_MULTIPLY, None, "NUM*")
    add(0x56, VK_SUBTRACT, None, "NUM-")
    add(0x57, VK_ADD, None, "NUM+")
    add(0x58, VK_RETURN, None, "NUMENT", "numenter", extended=True)
    for i in range(9):
        add(0x59 + i, VK_NUMPAD0 + 1 + i, None, f"NUM{i + 1}")
    add(0x62, VK_NUMPAD0, None, "NUM0")
    add(0x63, VK_DECIMAL, None, "NUM.")
    add(0xE0, VK_LCONTROL, None, "LCTRL")
    add(0xE1, VK_LSHIFT, None, "LSHIFT")
    add(0xE2, VK_LMENU, None, "LALT")
    add(0xE3, VK_LWIN, None, "LWIN")
    add(0xE4, VK_RCONTROL, None, "RCTRL")
    add(0xE5, VK_RSHIFT, None, "RSHIFT")
    add(0xE6, VK_RMENU, None, "RALT")
    add(0xE7, VK_RWIN, None, "RWIN")
    return specs, names


_SPECS, _NAMES = _table()


def from_hid(usage):
    """The KeySpec for Karl's HID usage. ValueError for usages Desk Dial doesn't send (none, the
    ISO-only Europe 1 / 2 keys, media keys, locks...)."""
    if type(usage) is not int or usage not in _SPECS:
        raise ValueError(f"key code {usage!r} is not a key Desk Dial can send")
    return _SPECS[usage]


def from_text(token):
    """A sidecar key token, case-insensitive: "z", "7", "F5", "/", "enter", "esc", "tab", "space",
    "delete"/"del", "insert"/"ins", "home", "end", "pgup", "pgdn", "up", "left", "num1", "num/",
    "numenter"..."""
    if not isinstance(token, str) or not token:
        raise ValueError("a key name is missing")
    text = token if len(token) == 1 else token.strip()
    hid = _NAMES.get(text.lower())
    if hid is None:
        raise ValueError(f'"{token}" is not a key name Desk Dial knows')
    return _SPECS[hid]


def map_mods(karl_bits, gui_to="ctrl"):
    """Karl's modifier bits as Windows modifiers: Cmd (GUI) -> `gui_to`, Option -> Alt."""
    if type(karl_bits) is not int or not 0 <= karl_bits <= 255:
        raise ValueError(f"modifier {karl_bits!r}: 0..255")
    if gui_to not in MODS:
        raise ValueError(f"gui_to {gui_to!r}: one of {', '.join(MODS)}")
    out = set()
    for bit, name in _KARL_MOD.items():
        if karl_bits & (1 << bit):
            out.add(gui_to if name == "gui" else name)
    return frozenset(out)


def karl_mods_collide(karl_bits, gui_to="ctrl"):
    """True when two of Karl's modifiers land on one Windows modifier (Cmd+Ctrl with gui -> ctrl):
    the Windows chord would lose one of them."""
    kinds = {name for bit, name in _KARL_MOD.items() if karl_bits & (1 << bit)}   # left and right alike
    mapped = [gui_to if kind == "gui" else kind for kind in kinds]
    return len(mapped) != len(set(mapped))


def parse_chord(text):
    """'ctrl+alt+t' -> Chord. Modifiers first (ctrl, shift, alt, win; each once), then one key
    token (from_text). 'ctrl+num+' and 'shift+=' work: only known modifier prefixes are split off."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a chord is missing")
    rest = text.strip()
    mods = []
    while True:
        low = rest.lower()
        for name in MODS:
            if low.startswith(name + "+") and len(rest) > len(name) + 1:
                if name in mods:
                    raise ValueError(f'"{text}": {name} twice')
                mods.append(name)
                rest = rest[len(name) + 1:]
                break
        else:
            break
    try:
        key = from_text(rest)
    except ValueError as exc:
        raise ValueError(f'"{text}": {exc}') from None
    return Chord(frozenset(mods), key)


def chord_text(chord):
    """The sidecar spelling of a chord ("ctrl+shift+z"): parse_chord(chord_text(c)) == c."""
    names = sorted(chord.mods, key=MOD_ORDER.__getitem__)
    token = chord.key.char if chord.key.char is not None else chord.key.label.lower()
    return "+".join((*names, token))


def display_mods(mods):
    """Wire keycap modifier bits (APP_PROFILES.md section 5)."""
    bits = 0
    for name in mods:
        bits |= DISPLAY_BITS[name]
    return bits


_VK_KEY_SCAN = None


def _default_vk_key_scan(char, hkl):
    global _VK_KEY_SCAN
    if _VK_KEY_SCAN is None:
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        fn = user32.VkKeyScanExW
        fn.restype = ctypes.c_short
        fn.argtypes = (ctypes.c_wchar, ctypes.c_void_p)
        _VK_KEY_SCAN = fn
    return _VK_KEY_SCAN(char, hkl)


_SCAN_SHIFT, _SCAN_CTRL, _SCAN_ALT = 0x01, 0x02, 0x04


def resolve(spec, hkl, vk_key_scan=None):
    """Send time: (vk, extra modifiers the layout needs for `spec`) or None = "Not on this keyboard".

    Layout-independent keys come back as (spec.vk, {}). A punctuation character goes through
    ``VkKeyScanExW(char, hkl)`` (`vk_key_scan(char, hkl) -> short`, injectable for tests): -1 (not on
    the layout), AltGr (Ctrl+Alt) or any of the Hankaku / reserved shift states refuse."""
    if spec.vk is not None:
        return spec.vk, frozenset()
    scan = (vk_key_scan or _default_vk_key_scan)(spec.char, hkl)
    if scan is None:
        return None
    scan &= 0xFFFF
    if scan == 0xFFFF:
        return None
    vk, state = scan & 0xFF, scan >> 8
    if state & ~(_SCAN_SHIFT | _SCAN_CTRL | _SCAN_ALT) or state & (_SCAN_CTRL | _SCAN_ALT):
        return None                         # AltGr (or Ctrl / Alt alone): a shortcut would never fire
    if vk in (0, 0xFF):
        return None
    return vk, frozenset({"shift"} if state & _SCAN_SHIFT else ())


_VK_F4, _VK_F6, _VK_F12 = VK_F1 + 3, VK_F1 + 5, VK_F1 + 11
_BLOCK_WIN = "the Windows key opens Windows' own menus"
_BLOCK_SWITCH = "it switches to another window"
_BLOCK_START = "it opens Start or Task Manager"
_BLOCK_CLOSE = "it closes the window"
_BLOCK_MENU = "it opens the window menu"
_BLOCK_SECURE = "it opens the Windows security screen"
_BLOCK_TAB = "the browser keeps it: it leaves the page"
_BLOCK_DEVTOOLS = "it opens the browser's developer tools"
# Browser accelerators a page can't take over (new / close / reopen / switch tab or window) and the developer tools:
# exact chords (Figma's Ctrl+Alt+T or Alt+D stay the page's).
_BROWSER_BLOCKED = {
    (frozenset({"ctrl"}), ord("T")): _BLOCK_TAB, (frozenset({"ctrl", "shift"}), ord("T")): _BLOCK_TAB,
    (frozenset({"ctrl"}), ord("N")): _BLOCK_TAB, (frozenset({"ctrl", "shift"}), ord("N")): _BLOCK_TAB,
    (frozenset({"ctrl"}), ord("W")): _BLOCK_TAB, (frozenset({"ctrl", "shift"}), ord("W")): _BLOCK_TAB,
    (frozenset({"ctrl"}), _VK_F4): _BLOCK_TAB,
    (frozenset({"ctrl"}), VK_TAB): _BLOCK_TAB, (frozenset({"ctrl", "shift"}), VK_TAB): _BLOCK_TAB,
    (frozenset({"ctrl"}), VK_PRIOR): _BLOCK_TAB, (frozenset({"ctrl"}), VK_NEXT): _BLOCK_TAB,
    (frozenset(), _VK_F12): _BLOCK_DEVTOOLS,
    (frozenset({"ctrl", "shift"}), ord("I")): _BLOCK_DEVTOOLS, (frozenset({"ctrl", "shift"}), ord("J")): _BLOCK_DEVTOOLS,
}


def blocked(chord, browser=False):
    """Why Desk Dial never sends ``chord`` for an app profile, or None (S3 review DD-1). The gates are checked before
    every SendInput, but these chords move the foreground or the keyboard focus out of the app asynchronously, so the
    keys a profile sends next would land elsewhere (a Win press opens Start, and Windows types what follows into its
    search box): anything with the Windows key, Alt+Tab / Alt+Esc, Ctrl+Esc / Ctrl+Shift+Esc, Alt+F4, Alt+Space,
    Ctrl+Alt+Del / End, and, for a profile that runs in a browser (``browser``), the tab and window keys the browser
    keeps for itself and its developer tools."""
    mods, vk = chord.mods, chord.key.vk
    if "win" in mods or vk in (VK_LWIN, VK_RWIN):
        return _BLOCK_WIN
    if "alt" in mods and vk in (VK_TAB, VK_ESCAPE):
        return _BLOCK_SWITCH
    if "ctrl" in mods and vk == VK_ESCAPE:
        return _BLOCK_START
    if "alt" in mods and vk == _VK_F4:
        return _BLOCK_CLOSE
    if "alt" in mods and vk == VK_SPACE:
        return _BLOCK_MENU
    if {"ctrl", "alt"} <= mods and vk in (VK_DELETE, VK_END):
        return _BLOCK_SECURE
    if browser:
        return _BROWSER_BLOCKED.get((frozenset(mods), vk))
    return None


def resolve_chord(chord, hkl, vk_key_scan=None):
    """(vk, mods to hold) for a whole chord, or None when the layout needs a modifier the chord
    doesn't already have (e.g. '/' on German QWERTZ is Shift+7: a plain '/' shortcut is refused)."""
    hit = resolve(chord.key, hkl, vk_key_scan)
    if hit is None:
        return None
    vk, extra = hit
    if not extra <= chord.mods:
        return None
    return vk, chord.mods
