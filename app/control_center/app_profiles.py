"""App profiles (plan sections 1a-1b, 2, 3a, 4, 5a; S1 lane DD-A): load, validate, overlay, compile.

The profile model, its JSON form, its limits and its refusals are Karl Malota's (katbinaris), adapted
with his permission from ``feat/firmware-esp-idf-quadra`` ``NanoDepsidf/src/app_profiles/``:
``app_profile.h`` (the structs), ``profile_json.c`` (``parse()``, the length caps and enum names) and
``app_profiles.c`` (``app_profiles_valid()``). ``validate_karl`` refuses everything his reader refuses,
with the same limits, and a little more (below).

Two files per app:

* ``<id>.json``: Karl's profile JSON, ``"format": 1``, byte for byte as his firmware writes it
  (``profiles/karl/``). Never edited here.
* ``<id>.windows.json``: the Windows sidecar, ``"overlay": 1`` (``validate_overlay``). It holds what only
  Windows needs: ``status``, ``detect``, ``keys``, ``slots``, ``params``, ``legend``, ``notes``.
  Unknown keys are refused, and so is a reference to a command, slot or macro that doesn't exist.

``load_pair`` merges the two into an ``AppProfile`` (the effective model the engine, lane DD-B, and
Settings, lane DD-C, read). ``AppProfile.wire()`` compiles the display part to the ``DDAP`` v1 blob of
``APP_PROFILES.md`` (the knob's frozen contract); ``decode_wire`` is the strict reference decoder the tests
hold it to. ``Library`` finds profiles in three folders, by id, user > updates > bundled.

API (frozen for S1)::

    STATUS = ('tested', 'community', 'basic')
    SOURCES = ('bundled', 'updates', 'user')
    ProfileError(ValueError).problems: list[str]
    read_json(path_or_bytes, name) -> dict              size, nesting, ASCII, NaN / huge-number checks
    validate_karl(doc) -> list[str]
    validate_overlay(doc, karl) -> list[str]
    load_pair(karl_path, overlay_path=None, source='bundled', rules=None) -> AppProfile
    Detect, Chord (= keymap.Chord), Slot, Param, Command, Ring, MacroStep, ParamKeys, AppProfile
    AppProfile.wire() -> bytes, .wire_crc, .features
    decode_wire(blob) -> dict                            raises WireError(code, offset)
    Library(bundled_dir, updates_dir=None, user_dir=None, rules=None)
        .reload() -> problems, .profiles(), .get(id), .import_file(path)
    host_matches(pattern, host), Detect.matches_exe(exe), Detect.matches_host(host), BROWSER_EXES

Additions to the S1 contract (additive only): ``Slot.haptic`` (Karl's feel enum: saw / sine / viscose),
``AppProfile.scenes`` (the de-duplicated scene table ``Command.scene`` indexes), ``AppProfile.legend``,
``AppProfile.warnings`` (keys Windows can't send, modifier collisions: the importer's summary), the
sidecar key ``legend`` (Onshape's buttons are TILT / ORBIT / WHEEL / PAN, not Karl's ZOOM first), and
the sidecar ``keys`` names ``@search`` and ``@param_keys.<field>``.

Stricter than Karl's reader, on purpose (hostile files): a file over 128 KB, nesting deeper than 32,
any byte outside printable ASCII + whitespace, a duplicate key, NaN / Infinity, a number beyond
+-1e7 where a float is read, a fraction where a whole number is read (cJSON's ``valueint`` truncates;
we refuse), a slot / scene / step that isn't an object, and any text outside 0x20..0x7E (legend too).

Privacy: detection rules are program names and bare hosts only (``validate_overlay`` refuses a scheme,
path, port or query). Nothing here reads or logs a window title or URL.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import struct
import tempfile
import zlib
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from . import keymap
from .keymap import Chord, KeySpec  # noqa: F401  (re-exported: app_profiles.Chord is the contract's name)

STATUS = ("tested", "community", "basic")
SOURCES = ("bundled", "updates", "user")            # precedence: user > updates > bundled, by id
ORDER = ("onshape", "figma", "plasticity", "blender", "autocad")
BROWSER_EXES = ("chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe")   # plan 3a, Chromium only

# --- Karl's limits (profile_json.c lines 20-31, profile_json.h, app_profile.h, haptic_params.h)
FORMAT = 1
MAX_ID = 11
MAX_NAME = 15
MAX_LEGEND = 7
MAX_LABEL = 23
MAX_TAB = 6
MAX_PHRASE = 60
MAX_RINGS = 8
MAX_CMDS = 32
MAX_FRAMES = 16
MAX_ELEMENTS = 48
MAX_MACRO_TEXT = 120
MAX_WAIT_MS = 10000
MACROS_MAX = 16
MACRO_STEPS_MAX = 64
DETENTS_MAX = 36                    # HAPTIC_NUM_DETENTS_MAX
ICON48_BYTES = 48 * 48 * 2
ICON24_BYTES = 24 * 24 * 2

# --- file hygiene (ours)
FILE_MAX = 128 * 1024
DEPTH_MAX = 32
FLOAT_MAX = 1e7

KIND = ("none", "drag", "wheel", "keys", "tap", "commands")
FEEL = ("saw", "sine", "viscose")
VISUAL = ("label", "shape")
SHAPE = ("cube", "pyramid", "octa")
STYLE = ("face", "grips", "thick")
FX = ("none", "zoom", "orbit", "pan", "flash")
SLOTS = ("knob", "f1", "f2", "f3", "f4")
CMD_KIND = ("keys", "actions", "macro")
PVISUAL = ("none", "fillet", "extrude", "offset", "hollow", "move", "rotate", "scale", "chamfer", "slide")
EL_LO = (0, 0, -128, -128, 0, 0, 0, 0, 0)
EL_HI = (14, 4, 127, 127, 255, 255, 255, 255, 255)     # APP_EL_ROLLBACK, APP_C_AMBER
MOUSE = {1: "left", 2: "right", 4: "middle"}

# --- the wire (APP_PROFILES.md)
WIRE_MAGIC = b"DDAP"
WIRE_VERSION = 1
WIRE_MAX = 32768
WIRE_PARAMS_MAX = 32
WIRE_SCENES_MAX = 128
F_SHAPE, F_SHAPE_EXT, F_LABEL_VISUAL, F_PARAM_CONSTRAINTS, F_DISABLED_CMDS = 1, 2, 4, 8, 16
FEATURES_ALL = 31
CMD_SEARCH, CMD_DISABLED, CMD_MACRO = 1, 2, 4

_ID = re.compile(r"[a-z0-9_-]{1,11}")
# S3 review DD-7: Windows device names. A file "<id>.json" with one of these as its name opens the device, whatever
# the case or the extension, so they are never a profile id.
_RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])", re.I)
RESERVED_ID_PROBLEM = "id: a Windows device name (con, prn, aux, nul, com0-9, lpt0-9) can't be a profile id"


def reserved_id(name):
    """True when ``name`` (an id or a file name) is a Windows device name: case-insensitive, any extension."""
    return isinstance(name, str) and bool(_RESERVED.fullmatch(name.split(".", 1)[0].strip()))


def valid_id(pid):
    """A profile id: 1-11 of a-z 0-9 _ -, and never a Windows device name (DD-7)."""
    return isinstance(pid, str) and bool(_ID.fullmatch(pid)) and not reserved_id(pid)
_EXE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.()+-]{0,62}\.exe", re.I)
_HOST_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_CLASS = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class ProfileError(ValueError):
    """A profile that can't be used, with every problem in plain words."""

    def __init__(self, problems):
        self.problems = list(problems) if not isinstance(problems, str) else [problems]
        super().__init__("; ".join(self.problems))


# ======================================================================================== reading JSON
def _refuse_constant(name):
    raise ValueError(f"{name} is not a number")


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text} is too large")
    return value


def _parse_int(text):
    if len(text.lstrip("-")) > 18:
        raise ValueError(f"{text[:20]}... is too large")
    return int(text)


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f'the key "{key}" appears twice')
        out[key] = value
    return out


def _depth(text):
    depth = deepest = 0
    in_string = escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            deepest = max(deepest, depth)
            if deepest > DEPTH_MAX:
                return deepest
        elif ch in "]}":
            depth -= 1
    return deepest


def read_json(source, name="profile"):
    """Bytes or a path -> a dict, refusing hostile input. Raises ProfileError ("<name>: ...")."""
    try:
        if isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        else:
            path = Path(source)
            if path.stat().st_size > FILE_MAX:
                raise ProfileError(f"{name}: bigger than {FILE_MAX // 1024} KB")
            with open(path, "rb") as handle:
                data = handle.read(FILE_MAX + 1)
    except OSError as exc:
        raise ProfileError(f"{name}: can't read it ({exc.strerror or exc})") from None
    if len(data) > FILE_MAX:
        raise ProfileError(f"{name}: bigger than {FILE_MAX // 1024} KB")
    bad = next((i for i, b in enumerate(data) if b > 0x7E or (b < 0x20 and b not in (9, 10, 13))), None)
    if bad is not None:
        raise ProfileError(f"{name}: byte {bad} is not plain ASCII")
    text = data.decode("ascii")
    if _depth(text) > DEPTH_MAX:
        raise ProfileError(f"{name}: nested deeper than {DEPTH_MAX} levels")
    try:
        doc = json.loads(text, parse_constant=_refuse_constant, parse_float=_parse_float, parse_int=_parse_int,
                         object_pairs_hook=_pairs)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{name}: not valid JSON (line {exc.lineno}, column {exc.colno})") from None
    except (ValueError, RecursionError) as exc:
        raise ProfileError(f"{name}: {exc}") from None
    if not isinstance(doc, dict):
        raise ProfileError(f"{name}: not a JSON object")
    return doc


# ======================================================================================== checking helpers
def _is_num(v):
    return type(v) in (int, float)


def _whole(v):
    """An int for a whole JSON number (24 or 24.0), else None."""
    if type(v) is int:
        return v
    if type(v) is float and v.is_integer():
        return int(v)
    return None


class _Check:
    def __init__(self):
        self.problems = []

    def bad(self, path, message):
        self.problems.append(f"{path}: {message}")
        return None

    def obj(self, o, key, path):
        v = o.get(key)
        if v is not None and not isinstance(v, dict):
            return self.bad(path, "an object")
        return v

    def int(self, o, key, path, lo, hi):
        if key not in o:
            return 0
        n = _whole(o[key])
        if n is None or not lo <= n <= hi:
            return self.bad(path, f"a whole number {lo}..{hi}") or 0
        return n

    def float(self, o, key, path, lo=-FLOAT_MAX, hi=FLOAT_MAX):
        if key not in o:
            return 0.0
        v = o[key]
        if not _is_num(v) or not lo <= v <= hi:
            return self.bad(path, f"a number {lo:g}..{hi:g}") or 0.0
        return float(v)

    def bool(self, o, key, path):
        if key not in o:
            return False
        if type(o[key]) is not bool:
            return self.bad(path, "true or false") or False
        return o[key]

    def text(self, value, path, limit, required=False, lo=None):
        if value is None:
            if required:
                self.bad(path, "missing")
            return None
        if not isinstance(value, str):
            return self.bad(path, "text")
        low = 1 if required else 0 if lo is None else lo
        if not low <= len(value) <= limit:
            return self.bad(path, f"{low}..{limit} characters" if low else f"up to {limit} characters")
        if any(not 0x20 <= ord(c) <= 0x7E for c in value):
            return self.bad(path, "plain ASCII only")
        return value

    def str(self, o, key, path, limit, required=False):
        return self.text(o.get(key), path, limit, required)

    def enum(self, o, key, path, names):
        if key not in o:
            return 0
        v = o[key]
        if isinstance(v, str) and v in names:
            return names.index(v)
        return self.bad(path, f"unknown value (one of {', '.join(names)})") or 0

    def key(self, v, path):
        """A Karl key [modifier, keycode] -> (mod, code), or (0, 0)."""
        if v is None:
            return 0, 0
        if not isinstance(v, list) or len(v) != 2:
            return self.bad(path, "[modifier, keycode]") or (0, 0)
        m, c = _whole(v[0]), _whole(v[1])
        if m is None or c is None or not 0 <= m <= 255 or not 0 <= c <= 255:
            return self.bad(path, "[modifier, keycode] 0..255") or (0, 0)
        return m, c

    def array(self, v, path, limit):
        if v is None:
            return []
        if not isinstance(v, list) or len(v) > limit:
            return self.bad(path, f"a list of up to {limit}") or []
        return v


# ======================================================================================== Karl's file
def _check_elements(ck, v, path):
    for i, e in enumerate(ck.array(v, path, MAX_ELEMENTS)):
        if not isinstance(e, list) or len(e) != 9:
            ck.bad(f"{path}[{i}]", "elements are 9 numbers")
            continue
        for j, x in enumerate(e):
            n = _whole(x)
            if n is None or not EL_LO[j] <= n <= EL_HI[j]:
                ck.bad(f"{path}[{i}][{j}]", f"a whole number {EL_LO[j]}..{EL_HI[j]}")


def _check_scene(ck, s, path):
    if not isinstance(s, dict):
        return ck.bad(path, "an object")
    _check_elements(ck, s.get("base"), f"{path}.base")
    for i, f in enumerate(ck.array(s.get("frames"), f"{path}.frames", MAX_FRAMES)):
        if not isinstance(f, dict):
            ck.bad(f"{path}.frames[{i}]", "an object")
            continue
        ck.int(f, "ms", f"{path}.frames[{i}].ms", 0, 60000)
        _check_elements(ck, f.get("el"), f"{path}.frames[{i}].el")


def _check_param(ck, p, path):
    if not isinstance(p, dict):
        return ck.bad(path, "an object")
    ck.str(p, "label", f"{path}.label", MAX_LABEL, True)
    ck.str(p, "label_neg", f"{path}.label_neg", MAX_LABEL)
    steps = p.get("steps")
    if steps is not None and (not isinstance(steps, list) or len(steps) != 3
                              or not all(_is_num(x) and abs(x) <= FLOAT_MAX for x in steps)):
        ck.bad(f"{path}.steps", "3 numbers")
    for k in ("free_step", "px_per_step", "start", "min", "max"):
        ck.float(p, k, f"{path}.{k}")
    lo, hi = p.get("min", 0), p.get("max", 0)
    if _is_num(lo) and _is_num(hi) and lo > hi:
        ck.bad(path, "min above max")
    ck.int(p, "decimals", f"{path}.decimals", 0, 4)
    for k in ("deg", "axes", "planes", "uniform"):
        ck.bool(p, k, f"{path}.{k}")
    ck.enum(p, "visual", f"{path}.visual", PVISUAL)
    ck.int(p, "modes", f"{path}.modes", 0, 15)
    ck.key(p.get("enter"), f"{path}.enter")
    ck.int(p, "axis_default", f"{path}.axis_default", 0, 3)


def _check_macro_ref(ck, o, key, path, macros):
    if key not in o:
        return 0
    v = o[key]
    if isinstance(v, str) and v in macros:
        return macros.index(v) + 1
    return ck.bad(path, "no macro called that") or 0


def _check_action(ck, a, path, macros, *, overlay=False):
    """Karl's r_action (profile_json.c 619-637); the sidecar reuses it for its partial slots."""
    if not isinstance(a, dict):
        return ck.bad(path, "an object")
    kind = ck.enum(a, "kind", f"{path}.kind", KIND)
    ck.str(a, "label", f"{path}.label", MAX_LABEL)
    ck.int(a, "buttons", f"{path}.buttons", 0, 31)
    if not (overlay and isinstance(a.get("modifier"), str)):
        ck.int(a, "modifier", f"{path}.modifier", 0, 255)
    ck.bool(a, "axis_y", f"{path}.axis_y")
    ck.float(a, "px_per_rad", f"{path}.px_per_rad", 0, 2000)
    ck.int(a, "sign", f"{path}.sign", -1, 1)
    for k in ("cw", "ccw", "tap"):
        if not (overlay and (isinstance(a.get(k), str) or (k in a and a[k] is None))):
            ck.key(a.get(k), f"{path}.{k}")
    for k in ("macro", "tap_macro"):
        if not (overlay and k in a and a[k] is None):
            _check_macro_ref(ck, a, k, f"{path}.{k}", macros)
    if not overlay:
        ck.enum(a, "feel", f"{path}.feel", FEEL)
        ck.int(a, "detents", f"{path}.detents", 0, DETENTS_MAX)
    ck.enum(a, "fx", f"{path}.fx", FX)
    return kind


def validate_karl(doc):
    """Every rule of Karl's profile_json.c parse() and app_profiles.c app_profiles_valid(), same limits,
    same refusals (plus the stricter checks in the module docstring). [] = valid."""
    ck = _Check()
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    nulls = list(_nulls(doc, ""))
    if nulls:
        return [f"{path}: null is not a value here" for path in nulls[:20]]
    fmt = ck.int(doc, "format", "format", 0, 1000)
    if fmt != FORMAT and not ck.problems:
        ck.bad("format", f"{fmt}: this reader reads {FORMAT}")
    pid = ck.str(doc, "id", "id", MAX_ID, True)
    if pid is not None and not _ID.fullmatch(pid):
        ck.bad("id", "a-z, 0-9, _ and - only")
    elif pid is not None and reserved_id(pid):
        ck.problems.append(RESERVED_ID_PROBLEM)
    ck.str(doc, "name", "name", MAX_NAME, True)
    legend = doc.get("legend")
    if not isinstance(legend, list) or len(legend) != 4:
        ck.bad("legend", "4 texts")
    else:
        for i, s in enumerate(legend):
            ck.text(s, f"legend[{i}]", MAX_LEGEND, lo=0) if isinstance(s, str) else ck.bad(f"legend[{i}]", "text")
    for k, n in (("icon48", ICON48_BYTES), ("icon24", ICON24_BYTES)):
        if k in doc and _icon(doc[k], n) is None:
            ck.bad(k, f"base64 of {n} bytes")
    ck.enum(doc, "visual", "visual", VISUAL)
    ck.enum(doc, "shape", "shape", SHAPE)
    ck.enum(doc, "shape_style", "shape_style", STYLE)
    ck.bool(doc, "shape_stepped", "shape_stepped")
    if "plasma" in doc:
        heat = doc["plasma"]
        if not isinstance(heat, list) or len(heat) != 3:
            ck.bad("plasma", "3 colours")
        else:
            for i, c in enumerate(heat):
                n = _whole(c)
                if n is None or not 0 <= n <= 0xFFFFFF:
                    ck.bad(f"plasma[{i}]", "a 0xRRGGBB number")

    macros = []
    for m, mo in enumerate(ck.array(doc.get("macros"), "macros", MACROS_MAX)):
        path = f"macros[{m}]"
        if not isinstance(mo, dict):
            ck.bad(path, "an object")
            macros.append(None)
            continue
        name = ck.str(mo, "name", f"{path}.name", MAX_NAME, True)
        if name is not None and name in macros:
            ck.bad(f"{path}.name", f"two macros called {name}")
        macros.append(name)
        for i, st in enumerate(ck.array(mo.get("steps"), f"{path}.steps", MACRO_STEPS_MAX)):
            sp = f"{path}.steps[{i}]"
            if not isinstance(st, dict):
                ck.bad(sp, "each is a key, a text or a wait")
            elif "key" in st:
                ck.key(st["key"], f"{sp}.key")
            elif "text" in st:
                if not isinstance(st["text"], str):
                    ck.bad(f"{sp}.text", f"up to {MAX_MACRO_TEXT} plain ASCII characters")
                else:
                    ck.text(st["text"], f"{sp}.text", MAX_MACRO_TEXT, lo=0)
            elif "wait" in st:
                ck.int(st, "wait", f"{sp}.wait", 0, MAX_WAIT_MS)
            else:
                ck.bad(sp, "each is a key, a text or a wait")

    wheel = False
    slots = ck.obj(doc, "slots", "slots")
    for name in SLOTS:
        if slots and name in slots:
            if _check_action(ck, slots[name], f"slots.{name}", macros) == KIND.index("commands"):
                wheel = True

    search = ck.obj(doc, "search", "search") or {}
    open_key = ck.key(search.get("open"), "search.open")
    ck.int(search, "open_wait", "search.open_wait", 0, 255)
    ck.int(search, "result_wait", "search.result_wait", 0, 255)

    rings = ck.array(doc.get("rings"), "rings", MAX_RINGS)
    for r, ro in enumerate(rings):
        path = f"rings[{r}]"
        if not isinstance(ro, dict):
            ck.bad(path, "an object")
            continue
        ck.str(ro, "name", f"{path}.name", MAX_LABEL, True)
        ck.str(ro, "tab", f"{path}.tab", MAX_TAB, True)
        ck.enum(ro, "slot", f"{path}.slot", SLOTS)
        cmds = ck.array(ro.get("cmds"), f"{path}.cmds", MAX_CMDS)
        if not cmds and isinstance(ro.get("cmds", []), list):
            ck.bad(f"{path}.cmds", "each ring needs at least one command")
        for c, co in enumerate(cmds):
            cp = f"{path}.cmds[{c}]"
            if not isinstance(co, dict):
                ck.bad(cp, "an object")
                continue
            ck.str(co, "name", f"{cp}.name", MAX_LABEL, True)
            kind = ck.enum(co, "kind", f"{cp}.kind", CMD_KIND)
            ck.key(co.get("key"), f"{cp}.key")
            phrase = ck.str(co, "phrase", f"{cp}.phrase", MAX_PHRASE)
            ref = _check_macro_ref(ck, co, "macro", f"{cp}.macro", macros)
            if kind == CMD_KIND.index("macro") and ref == 0 and "macro" not in co:
                ck.bad(cp, "a macro command: pick a macro")
            if kind == CMD_KIND.index("actions"):
                if not phrase:
                    ck.bad(f"{cp}.phrase", "a search command needs its phrase")
                if open_key[1] == 0:
                    ck.bad(cp, "a search command, but the profile has no search.open key")
            if "scene" in co:
                _check_scene(ck, co["scene"], f"{cp}.scene")
            if "param" in co:
                _check_param(ck, co["param"], f"{cp}.param")
    if wheel and not rings:
        ck.bad("slots", "a commands slot (the wheel) needs rings")

    pk = ck.obj(doc, "param_keys", "param_keys") or {}
    for k in ("numeric", "confirm", "cancel", "uniform", "select_all"):
        ck.key(pk.get(k), f"param_keys.{k}")
    ax = pk.get("axis")
    if ax is not None:
        if not isinstance(ax, list) or len(ax) != 3:
            ck.bad("param_keys.axis", "3 keys")
        else:
            for i, k in enumerate(ax):
                ck.key(k, f"param_keys.axis[{i}]")
    ck.bool(pk, "field", "param_keys.field")
    sm = pk.get("step_mod")
    if sm is not None:
        if not isinstance(sm, list) or len(sm) != 3:
            ck.bad("param_keys.step_mod", "3 modifiers")
        else:
            for i, x in enumerate(sm):
                n = _whole(x)
                if n is None or not 0 <= n <= 255:
                    ck.bad(f"param_keys.step_mod[{i}]", "0..255")
    ck.int(pk, "scroll_sign", "param_keys.scroll_sign", -1, 1)
    return ck.problems


def _nulls(node, path):
    """Karl's reader refuses a JSON null wherever it reads one; we refuse it anywhere."""
    if node is None:
        yield path or "(top)"
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _nulls(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _nulls(v, f"{path}[{i}]")


def _icon(value, n):
    if not isinstance(value, str) or len(value) != 4 * ((n + 2) // 3):
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    return raw if len(raw) == n else None


# ======================================================================================== the sidecar
OVERLAY_KEYS = ("overlay", "status", "detect", "keys", "slots", "params", "legend", "notes")
# S3 decision: the sidecar's "gui" option (what Karl's Cmd becomes) is gone; Cmd is always Ctrl.
GUI_REMOVED = "gui: this option was removed. Karl's Cmd is always Ctrl on Windows; use \"keys\" to change a single shortcut."
DETECT_KEYS = ("exe", "host", "exclude_host", "content_class")
SLOT_EXTRA = ("feel", "haptic", "notches_per_turn", "button")
SLOT_KARL = ("kind", "label", "buttons", "modifier", "axis_y", "px_per_rad", "sign", "cw", "ccw", "tap", "macro",
             "tap_macro", "detents", "fx")
PARAM_KEY_FIELDS = ("numeric", "confirm", "cancel", "uniform", "select_all", "axis0", "axis1", "axis2")
FEEL_NAME_MAX = 31
UNIT_MAX = 7
NOTE_MAX = 400


def host_rule_ok(rule):
    """A bare host, optionally '*.' + host: no scheme, path, port, query or user."""
    if not isinstance(rule, str) or not 1 <= len(rule) <= 253:
        return False
    host = rule[2:] if rule.startswith("*.") else rule
    labels = host.split(".")
    return len(labels) >= 2 and all(_HOST_LABEL.fullmatch(label) for label in labels)


# S3 review DD-2: programs no profile may drive. In a shell or terminal a macro's text is a command and its Enter runs
# it; Explorer, Start, Search and the system tools are Windows itself. Refused as detection rules (sidecar and
# Settings) and by the cursor gate (app_detect.gate_target), whatever a profile says.
SHELL_EXES = frozenset((
    "cmd.exe", "powershell.exe", "powershell_ise.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe", "conhost.exe",
    "openconsole.exe", "wsl.exe", "wslhost.exe", "bash.exe", "sh.exe", "git-bash.exe", "mintty.exe", "ubuntu.exe",
    "explorer.exe", "startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe", "searchui.exe",
    "shellexperiencehost.exe", "lockapp.exe", "consent.exe", "logonui.exe", "systemsettings.exe", "control.exe",
    "mmc.exe", "regedit.exe", "taskmgr.exe", "mshta.exe", "wscript.exe", "cscript.exe", "rundll32.exe",
    "msiexec.exe", "runas.exe", "sudo.exe"))


def is_shell_exe(exe):
    """True for a program in SHELL_EXES (any folder, any case)."""
    return os.path.basename(str(exe or "")).lower() in SHELL_EXES


def exe_rule_ok(rule):
    """A bare program file name ending in .exe: no folder, drive or wildcard, and never a shell (SHELL_EXES)."""
    return isinstance(rule, str) and bool(_EXE.fullmatch(rule)) and not is_shell_exe(rule)


def host_matches(pattern, host):
    """'*.figma.com' matches any subdomain (not figma.com itself); anything else matches exactly."""
    pattern, host = str(pattern).lower(), str(host or "").lower().rstrip(".")
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and len(host) > len(pattern) - 1
    return host == pattern


def _check_rules(ck, d, path, keys=DETECT_KEYS):
    if not isinstance(d, dict):
        return ck.bad(path, "an object")
    for k in d:
        if k not in keys:
            ck.bad(f"{path}.{k}", f"unknown key (one of {', '.join(keys)})")
    for k in keys:
        if k not in d:
            continue
        v = d[k]
        if not isinstance(v, list) or len(v) > 32:
            ck.bad(f"{path}.{k}", "a list of up to 32")
            continue
        for i, item in enumerate(v):
            where = f"{path}.{k}[{i}]"
            if k == "exe" and not exe_rule_ok(item):
                ck.bad(where, "a program file name like Figma.exe (no folder, never a shell or Windows itself)")
            elif k in ("host", "exclude_host") and not host_rule_ok(item):
                ck.bad(where, "a bare host like www.figma.com or *.figma.com (no https://, path or port)")
            elif k == "content_class" and not (isinstance(item, str) and _CLASS.fullmatch(item)):
                ck.bad(where, "a window class name")


def _commands(karl):
    for r, ring in enumerate(karl.get("rings") or ()):
        for c, cmd in enumerate(ring.get("cmds") or ()):
            yield r, c, ring.get("name"), cmd


def _matches(ref, karl):
    """Command positions a "RING/COMMAND" or "*/COMMAND" reference names."""
    out = []
    for r, c, ring_name, cmd in _commands(karl):
        name = cmd.get("name")
        if ref == f"{ring_name}/{name}" or ref == f"*/{name}":
            out.append((r, c))
    return out


def _check_chord(ck, v, path):
    try:
        return keymap.parse_chord(v)
    except ValueError as exc:
        return ck.bad(path, str(exc))


def _check_mods_text(ck, v, path):
    names = [p for p in v.lower().split("+") if p] if v else []
    if any(n not in keymap.MODS for n in names) or len(set(names)) != len(names):
        return ck.bad(path, "modifiers like ctrl+shift (ctrl, shift, alt, win)")
    return frozenset(names)


def validate_overlay(doc, karl):
    """The sidecar against its Karl file. [] = valid."""
    ck = _Check()
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    for k in doc:
        if k == "gui":
            ck.problems.append(GUI_REMOVED)
        elif k not in OVERLAY_KEYS:
            ck.bad(k, f"unknown key (one of {', '.join(OVERLAY_KEYS)})")
    if doc.get("overlay") != 1 or type(doc.get("overlay")) is not int:
        ck.bad("overlay", "must be 1 (the sidecar version)")
    if "status" in doc and doc["status"] not in STATUS:
        ck.bad("status", f"one of {', '.join(STATUS)}")
    if "detect" in doc:
        _check_rules(ck, doc["detect"], "detect")
    if "notes" in doc:
        notes = doc["notes"]
        items = notes if isinstance(notes, list) else [notes]
        if len(items) > 64:
            ck.bad("notes", "up to 64 lines")
        for i, n in enumerate(items):
            ck.text(n, f"notes[{i}]" if isinstance(notes, list) else "notes", NOTE_MAX, lo=0)
    if "legend" in doc:
        legend = doc["legend"]
        if not isinstance(legend, list) or len(legend) != 4:
            ck.bad("legend", "4 texts (null keeps Karl's)")
        else:
            for i, s in enumerate(legend):
                if s is not None:
                    ck.text(s, f"legend[{i}]", MAX_LEGEND, lo=0)
    macros = [m.get("name") for m in karl.get("macros") or () if isinstance(m, dict)]

    keys = doc.get("keys")
    if keys is not None:
        if not isinstance(keys, dict):
            ck.bad("keys", "an object")
            keys = {}
        for ref, value in keys.items():
            path = f'keys."{ref}"'
            if ref.startswith("@"):
                field_name = ref[1:]
                if field_name not in ("search", *(f"param_keys.{f}" for f in PARAM_KEY_FIELDS)):
                    ck.bad(path, "unknown name (@search or @param_keys.numeric / confirm / cancel / uniform / "
                                 "select_all / axis0..2)")
                if value is not None and not isinstance(value, str):
                    ck.bad(path, 'a chord like "ctrl+k", or null')
                elif value is not None:
                    _check_chord(ck, value, path)
                continue
            if not _matches(ref, karl):
                ck.bad(path, "no command called that (RING/COMMAND or */COMMAND)")
            if isinstance(value, dict):
                for k in value:
                    if k not in ("chord", "disabled_reason"):
                        ck.bad(f"{path}.{k}", "unknown key (chord, disabled_reason)")
                reason = ck.text(value.get("disabled_reason"), f"{path}.disabled_reason", 60)
                value = value.get("chord")
                if reason is not None and value is not None:
                    ck.bad(path, "a disabled_reason only goes with chord null")
            if value is not None and not isinstance(value, str):
                ck.bad(path, 'a chord like "ctrl+alt+t", or null (disabled on Windows)')
            elif value is not None:
                _check_chord(ck, value, path)

    slots = doc.get("slots")
    if slots is not None:
        if not isinstance(slots, dict):
            ck.bad("slots", "an object")
            slots = {}
        for name, s in slots.items():
            path = f"slots.{name}"
            if name not in SLOTS:
                ck.bad(path, f"unknown slot (one of {', '.join(SLOTS)})")
                continue
            if not isinstance(s, dict):
                ck.bad(path, "an object")
                continue
            for k in s:
                if k not in SLOT_KARL and k not in SLOT_EXTRA:
                    ck.bad(f"{path}.{k}", "unknown key")
            _check_action(ck, s, path, macros, overlay=True)
            if isinstance(s.get("modifier"), str):
                _check_mods_text(ck, s["modifier"], f"{path}.modifier")
            for k in ("cw", "ccw", "tap"):
                if isinstance(s.get(k), str):
                    _check_chord(ck, s[k], f"{path}.{k}")
            ck.int(s, "detents", f"{path}.detents", 0, 1000)
            if "feel" in s and s["feel"] is not None:
                ck.text(s["feel"], f"{path}.feel", FEEL_NAME_MAX, True)
            if "haptic" in s:
                ck.enum(s, "haptic", f"{path}.haptic", FEEL)
            if "notches_per_turn" in s and s["notches_per_turn"] is not None:
                ck.float(s, "notches_per_turn", f"{path}.notches_per_turn", 1, 240)
            if "button" in s:
                if name == "knob":
                    ck.bad(f"{path}.button", "the knob slot has no button")
                elif s["button"] is not None:
                    ck.int(s, "button", f"{path}.button", 0, 3)

    params = doc.get("params")
    if params is not None:
        if not isinstance(params, dict):
            ck.bad("params", "an object")
            params = {}
        for ref, p in params.items():
            path = f'params."{ref}"'
            hits = _matches(ref, karl)
            if not hits:
                ck.bad(path, "no command called that (RING/COMMAND or */COMMAND)")
            elif not all("param" in karl["rings"][r]["cmds"][c] for r, c in hits):
                ck.bad(path, "that command has no param")
            if not isinstance(p, dict):
                ck.bad(path, "an object")
                continue
            for k in p:
                if k != "unit":
                    ck.bad(f"{path}.{k}", "unknown key (unit)")
            if "unit" in p and p["unit"] is not None:
                ck.text(p["unit"], f"{path}.unit", UNIT_MAX, True)

    if not ck.problems:
        if validate_karl(karl):
            ck.bad("overlay", "its Karl file has problems of its own")
        else:
            try:
                _build(karl, doc, source="bundled", karl_sha256="", rules=None)
            except ProfileError as exc:
                ck.problems.extend(exc.problems)
    return ck.problems


# ======================================================================================== the effective model
@dataclass(frozen=True)
class Detect:
    exe: tuple = ()
    host: tuple = ()
    exclude_host: tuple = ()
    content_class: tuple = ()

    def matches_exe(self, exe):
        name = os.path.basename(str(exe or "")).lower()
        return bool(name) and any(name == rule.lower() for rule in self.exe)

    def matches_host(self, host):
        if any(host_matches(rule, host) for rule in self.exclude_host):
            return False
        return any(host_matches(rule, host) for rule in self.host)


@dataclass(frozen=True)
class Slot:
    name: str                    # 'knob', 'f1'..'f4'
    kind: str                    # none | drag | wheel | keys | tap | commands
    label: str
    button: int | None           # physical button 0-3 selecting it; None for the knob
    drag_buttons: frozenset
    drag_mods: frozenset
    axis_y: bool
    px_per_rad: float
    sign: int
    wheel_mods: frozenset
    notches_per_turn: float | None
    cw: Chord | None
    ccw: Chord | None
    tap: Chord | None
    macro: str | None
    tap_macro: str | None
    fx: str
    feel: str | None             # Desk Dial knob profile name ('BINARIS BEER'); None = the kind's default
    detents: int | None
    haptic: str = "saw"          # Karl's feel enum (addition): saw | sine | viscose


@dataclass(frozen=True)
class Param:
    label: str
    label_neg: str | None
    steps: tuple
    free_step: float
    px_per_step: float
    start: float
    min: float
    max: float
    decimals: int
    deg: bool
    axes: bool
    planes: bool
    uniform: bool
    visual: str
    modes: int
    enter: Chord | None
    axis_default: int
    unit: str | None


@dataclass(frozen=True)
class Command:
    name: str
    kind: str                    # keys | actions | macro
    chord: Chord | None
    phrase: str | None
    macro: str | None
    scene: int | None            # index into AppProfile.scenes
    param: Param | None
    disabled: bool
    disabled_reason: str | None


@dataclass(frozen=True)
class Ring:
    name: str
    tab: str
    slot: str
    commands: tuple


@dataclass(frozen=True)
class MacroStep:
    kind: str                    # key | text | wait
    chord: Chord | None
    text: str | None
    ms: int


@dataclass(frozen=True)
class ParamKeys:
    numeric: Chord | None
    confirm: Chord | None
    cancel: Chord | None
    axis: tuple
    uniform: Chord | None
    field: bool
    step_mods: tuple
    scroll_sign: int
    select_all: Chord | None


@dataclass(frozen=True)
class AppProfile:
    id: str
    name: str
    status: str
    source: str
    karl_sha256: str
    detect: Detect
    slots: dict
    rings: tuple
    macros: dict
    search: Chord | None
    search_open_ms: int
    search_result_ms: int
    param_keys: ParamKeys
    home_chord: bool
    raw_karl: dict = field(repr=False)
    raw_overlay: dict = field(repr=False)
    legend: tuple = ("", "", "", "")
    scenes: tuple = field(default=(), repr=False)
    warnings: tuple = ()

    __hash__ = None

    def wire(self):
        """The DDAP v1 blob (APP_PROFILES.md). Raises ProfileError past 32768 bytes."""
        return self._wire

    @cached_property
    def _wire(self):
        return compile_wire(self)

    @property
    def wire_crc(self):
        return struct.unpack_from("<I", self._wire, len(self._wire) - 4)[0]

    @property
    def features(self):
        return struct.unpack_from("<I", self._wire, 12)[0]


def _chord(karl_key, gui, warnings, where):
    mod, code = karl_key
    if code == 0:
        return None
    try:
        spec = keymap.from_hid(code)
    except ValueError:
        warnings.append(f"{where}: key code 0x{code:02X} has no Windows key")
        return None
    if keymap.karl_mods_collide(mod, gui):
        warnings.append(f"{where}: Karl's modifiers {mod} collapse on Windows")
    return Chord(keymap.map_mods(mod, gui), spec)


def _key_of(v):
    return (int(v[0]), int(v[1])) if isinstance(v, list) and len(v) == 2 else (0, 0)


def _num(v, default=0.0):
    return float(v) if _is_num(v) else default


def _scene_key(scene):
    base = tuple(tuple(int(x) for x in e) for e in scene.get("base") or ())
    frames = tuple((int(f.get("ms", 0)), tuple(tuple(int(x) for x in e) for e in f.get("el") or ()))
                   for f in scene.get("frames") or ())
    return base, frames


def _build(karl, overlay, *, source, karl_sha256, rules):
    """Karl doc + sidecar doc (both already valid) -> AppProfile. Raises ProfileError for problems that
    only show once merged (a button used twice, a wheel slot without rings)."""
    overlay = overlay or {}
    problems, warnings = [], []
    gui = "ctrl"                                   # Karl's Cmd, always (S3 decision: no "gui" option)
    pid = karl["id"]

    detect_doc = overlay.get("detect") or {}
    detect = {k: list(detect_doc.get(k) or ()) for k in DETECT_KEYS}
    for k, values in ((rules or {}).get(pid) or {}).items():
        for v in values:
            if v not in detect[k]:
                detect[k].append(v)
    detect = Detect(*(tuple(detect[k]) for k in DETECT_KEYS))

    macros = {}
    for m in karl.get("macros") or ():
        steps = []
        for i, st in enumerate(m.get("steps") or ()):
            if "key" in st:
                steps.append(MacroStep("key", _chord(_key_of(st["key"]), gui, warnings,
                                                     f"macros.{m['name']}[{i}]"), None, 0))
            elif "text" in st:
                steps.append(MacroStep("text", None, st["text"], 0))
            else:
                steps.append(MacroStep("wait", None, None, int(st["wait"])))
        macros[m["name"]] = tuple(steps)

    karl_slots = karl.get("slots") or {}
    over_slots = overlay.get("slots") or {}
    slots = {}
    for index, name in enumerate(SLOTS):
        a = dict(karl_slots.get(name) or {})
        o = over_slots.get(name) or {}
        a.update({k: v for k, v in o.items() if k in SLOT_KARL})
        kind = a.get("kind", "none")
        if isinstance(a.get("modifier"), str):
            mods = _check_mods_text(_Check(), a["modifier"], "") or frozenset()
        else:
            mods = keymap.map_mods(_whole(a.get("modifier", 0)) or 0, gui)

        def slot_chord(k, a=a, name=name):
            v = a.get(k)
            if isinstance(v, str):
                return keymap.parse_chord(v)
            if v is None:
                return None
            return _chord(_key_of(v), gui, warnings, f"slots.{name}.{k}")

        button = None if name == "knob" else o["button"] if "button" in o else index - 1
        detents = _whole(a.get("detents", 0)) or 0
        notches = o.get("notches_per_turn")
        slots[name] = Slot(
            name=name, kind=kind, label=a.get("label") or "", button=button,
            drag_buttons=frozenset(MOUSE[b] for b in MOUSE if (_whole(a.get("buttons", 0)) or 0) & b),
            drag_mods=mods if kind == "drag" else frozenset(), axis_y=bool(a.get("axis_y", False)),
            px_per_rad=_num(a.get("px_per_rad")), sign=_whole(a.get("sign", 0)) or 0,
            wheel_mods=mods if kind == "wheel" else frozenset(),
            notches_per_turn=float(notches) if notches is not None else None,
            cw=slot_chord("cw"), ccw=slot_chord("ccw"), tap=slot_chord("tap"),
            macro=a.get("macro"), tap_macro=a.get("tap_macro"), fx=a.get("fx", "none"),
            feel=o.get("feel"), detents=detents or None,
            haptic=o.get("haptic") or (karl_slots.get(name) or {}).get("feel", "saw"))
    used = {}
    for s in slots.values():
        if s.button is None or s.kind == "none":
            continue
        if s.button in used:
            problems.append(f"slots.{s.name}.button: button {s.button + 1} already selects {used[s.button]}")
        used[s.button] = s.name
    if any(s.kind == "commands" for s in slots.values()) and not karl.get("rings"):
        problems.append("slots: a commands slot (the wheel) needs rings")

    keys = overlay.get("keys") or {}
    params_over = overlay.get("params") or {}
    scene_index, scenes = {}, []
    rings = []
    for r, ring in enumerate(karl.get("rings") or ()):
        commands = []
        for c, cmd in enumerate(ring["cmds"]):
            name = cmd["name"]
            where = f"{ring['name']}/{name}"
            kind = cmd.get("kind", "keys")
            chord = _chord(_key_of(cmd.get("key")), gui, warnings, where) if kind == "keys" else None
            phrase = cmd.get("phrase")
            disabled, reason = False, None
            if kind == "keys" and cmd.get("key") and _key_of(cmd["key"])[1] and chord is None:
                disabled, reason = True, "No Windows key"
            override = keys.get(where, keys.get(f"*/{name}", ...))
            if override is not ...:
                if isinstance(override, dict):
                    reason = override.get("disabled_reason")
                    override = override.get("chord")
                if override is None:
                    disabled, chord = True, None
                    reason = reason or "Not on Windows"
                else:
                    kind, chord, phrase, disabled, reason = "keys", keymap.parse_chord(override), None, False, None
            scene = None
            if isinstance(cmd.get("scene"), dict):
                sk = _scene_key(cmd["scene"])
                if sk not in scene_index:
                    scene_index[sk] = len(scenes)
                    scenes.append(sk)
                scene = scene_index[sk]
            param = None
            if isinstance(cmd.get("param"), dict):
                p = cmd["param"]
                unit = (params_over.get(where) or params_over.get(f"*/{name}") or {}).get("unit")
                steps = tuple(float(x) for x in p.get("steps") or (0.0, 0.0, 0.0))
                param = Param(
                    label=p["label"], label_neg=p.get("label_neg"), steps=steps,
                    free_step=_num(p.get("free_step")), px_per_step=_num(p.get("px_per_step")),
                    start=_num(p.get("start")), min=_num(p.get("min")), max=_num(p.get("max")),
                    decimals=_whole(p.get("decimals", 0)) or 0, deg=bool(p.get("deg")), axes=bool(p.get("axes")),
                    planes=bool(p.get("planes")), uniform=bool(p.get("uniform")), visual=p.get("visual", "none"),
                    modes=_whole(p.get("modes", 0)) or 0,
                    enter=_chord(_key_of(p.get("enter")), gui, warnings, f"{where}.param.enter"),
                    axis_default=_whole(p.get("axis_default", 0)) or 0, unit=unit)
            commands.append(Command(name, kind, chord, phrase, cmd.get("macro") if kind == "macro" else None,
                                    scene, param, disabled, reason))
        rings.append(Ring(ring["name"], ring["tab"], ring.get("slot", "knob"), tuple(commands)))

    def special(name, karl_key, where):
        ref = f"@{name}"
        if ref in keys:
            return keymap.parse_chord(keys[ref]) if keys[ref] is not None else None
        return _chord(_key_of(karl_key), gui, warnings, where)

    search_doc = karl.get("search") or {}
    search = special("search", search_doc.get("open"), "search.open")
    pk = karl.get("param_keys") or {}
    axis = pk.get("axis") or [None, None, None]
    step_mod = pk.get("step_mod") or [0, 0, 0]
    param_keys = ParamKeys(
        numeric=special("param_keys.numeric", pk.get("numeric"), "param_keys.numeric"),
        confirm=special("param_keys.confirm", pk.get("confirm"), "param_keys.confirm"),
        cancel=special("param_keys.cancel", pk.get("cancel"), "param_keys.cancel"),
        axis=tuple(special(f"param_keys.axis{i}", axis[i], f"param_keys.axis[{i}]") for i in range(3)),
        uniform=special("param_keys.uniform", pk.get("uniform"), "param_keys.uniform"),
        field=bool(pk.get("field", False)),
        step_mods=tuple(keymap.map_mods(_whole(x) or 0, gui) for x in step_mod),
        scroll_sign=_whole(pk.get("scroll_sign", 0)) or 0,
        select_all=special("param_keys.select_all", pk.get("select_all"), "param_keys.select_all"))
    if search is None and any(c.kind == "actions" and not c.disabled for ring in rings for c in ring.commands):
        problems.append("keys.\"@search\": search commands need a search key")

    legend = list(karl.get("legend") or ("", "", "", ""))
    for i, s in enumerate(overlay.get("legend") or (None,) * 4):
        if s is not None:
            legend[i] = s
    problems.extend(_blocked_chords(slots, rings, macros, search, param_keys, browser=bool(detect.host)))
    if problems:
        raise ProfileError(problems)
    rings_t = tuple(rings)
    status = overlay.get("status") or ("community" if rings_t else "basic")
    return AppProfile(
        id=pid, name=karl["name"], status=status, source=source, karl_sha256=karl_sha256, detect=detect,
        slots=slots, rings=rings_t, macros=macros, search=search,
        search_open_ms=(_whole(search_doc.get("open_wait", 0)) or 0) * 10,
        search_result_ms=(_whole(search_doc.get("result_wait", 0)) or 0) * 10,
        param_keys=param_keys, home_chord=True, raw_karl=karl, raw_overlay=overlay, legend=tuple(legend),
        scenes=tuple(scenes), warnings=tuple(dict.fromkeys(warnings)))


def _blocked_chords(slots, rings, macros, search, param_keys, browser):
    """Problems for every chord the profile could send that ``keymap.blocked`` refuses (S3 review DD-1): the profile
    is refused, so an import says why and nothing of it is ever bound."""
    found = []
    for name, slot in slots.items():
        found += [(f"slots.{name}.{k}", getattr(slot, k)) for k in ("cw", "ccw", "tap")]
    for macro, steps in macros.items():
        found += [(f"macros.{macro}[{i}]", step.chord) for i, step in enumerate(steps)]
    for ring in rings:
        for cmd in ring.commands:
            if not cmd.disabled:
                found.append((f"{ring.name}/{cmd.name}", cmd.chord))
            if cmd.param is not None:
                found.append((f"{ring.name}/{cmd.name}.param.enter", cmd.param.enter))
    found.append(("search.open", search))
    for k in ("numeric", "confirm", "cancel", "uniform", "select_all"):
        found.append((f"param_keys.{k}", getattr(param_keys, k)))
    for i, chord in enumerate(param_keys.axis):             # the axis key, and with Shift its plane
        found.append((f"param_keys.axis[{i}]", chord))
        if chord is not None:
            found.append((f"param_keys.axis[{i}] (plane)", Chord(chord.mods | {"shift"}, chord.key)))
    out = []
    for where, chord in found:
        reason = keymap.blocked(chord, browser) if chord is not None else None
        if reason is not None:
            out.append(f"{where}: {keymap.chord_text(chord)} is blocked ({reason})")
    return out


def _check_rules_arg(rules):
    problems = []
    if rules is None:
        return problems
    if not isinstance(rules, dict):
        return ["rules: an object {id: {exe: [...], host: [...]}}"]
    for pid, d in rules.items():
        ck = _Check()
        _check_rules(ck, d, f"rules.{pid}", keys=("exe", "host"))
        problems.extend(ck.problems)
    return problems


def load_pair(karl_path, overlay_path=None, source="bundled", rules=None):
    """Read, check and merge one Karl file and its sidecar. Raises ProfileError ("figma.json: ...")."""
    karl_path = Path(karl_path)
    try:
        raw = karl_path.read_bytes() if karl_path.stat().st_size <= FILE_MAX else None
    except OSError as exc:
        raise ProfileError(f"{karl_path.name}: can't read it ({exc.strerror or exc})") from None
    if raw is None:
        raise ProfileError(f"{karl_path.name}: bigger than {FILE_MAX // 1024} KB")
    return _load_docs(raw, karl_path.name, overlay_path, source, rules)


def _read_bounded(path):
    """A file's bytes, at most FILE_MAX: the size is checked before reading and the read is capped (DD-5)."""
    try:
        if path.stat().st_size > FILE_MAX:
            raise ProfileError(f"{path.name}: bigger than {FILE_MAX // 1024} KB")
        with open(path, "rb") as handle:
            data = handle.read(FILE_MAX + 1)
    except OSError as exc:
        raise ProfileError(f"{path.name}: can't read it ({exc.strerror or exc})") from None
    if len(data) > FILE_MAX:
        raise ProfileError(f"{path.name}: bigger than {FILE_MAX // 1024} KB")
    return data


def _load_docs(raw, karl_name, overlay_path, source, rules, overlay_raw=None):
    """``overlay_raw``: the sidecar's bytes, already read (an import validates exactly what it writes)."""
    karl = read_json(raw, karl_name)
    problems = [f"{karl_name}: {p}" for p in validate_karl(karl)]
    if problems:
        raise ProfileError(problems)
    overlay = {}
    if overlay_path is not None:
        overlay_path = Path(overlay_path)
        overlay = read_json(overlay_raw if overlay_raw is not None else overlay_path, overlay_path.name)
        problems = [f"{overlay_path.name}: {p}" for p in validate_overlay(overlay, karl)]
        if problems:
            raise ProfileError(problems)
    rule_problems = _check_rules_arg(rules)
    if rule_problems:
        raise ProfileError(rule_problems)
    if source not in SOURCES:
        raise ProfileError(f"source {source!r}: one of {', '.join(SOURCES)}")
    try:
        profile = _build(karl, overlay, source=source, karl_sha256=hashlib.sha256(raw).hexdigest(), rules=rules)
    except ProfileError as exc:
        name = overlay_path.name if overlay_path is not None else karl_name
        raise ProfileError([f"{name}: {p}" for p in exc.problems]) from None
    profile.wire()          # a profile too big for the knob is refused here, not at upload time
    return profile


# ======================================================================================== the wire compiler
class _W:
    def __init__(self):
        self.buf = bytearray()

    def u8(self, v):
        if not 0 <= v <= 0xFF:
            raise ProfileError(f"wire: {v} doesn't fit a byte")
        self.buf.append(v)

    def i8(self, v):
        self.buf += struct.pack("<b", v)

    def u16(self, v):
        self.buf += struct.pack("<H", v)

    def u32(self, v):
        self.buf += struct.pack("<I", v)

    def f32(self, v):
        packed = struct.pack("<f", v)
        back = struct.unpack("<f", packed)[0]
        if not math.isfinite(back) or abs(back) > FLOAT_MAX:
            raise ProfileError(f"wire: {v} is out of range for the knob")
        self.buf += packed

    def str(self, s, lo, hi, what):
        data = (s or "").encode("ascii")
        if not lo <= len(data) <= hi or any(not 0x20 <= b <= 0x7E for b in data):
            raise ProfileError(f"wire: {what} \"{s}\": {lo}..{hi} plain ASCII characters")
        self.u8(len(data))
        self.buf += data


def _display(chord):
    if chord is None:
        return 0, ""
    return keymap.display_mods(chord.mods), chord.key.label


def compile_wire(p):
    """AppProfile -> DDAP v1 bytes (APP_PROFILES.md section 3), deterministic."""
    karl = p.raw_karl
    w = _W()
    w.buf += WIRE_MAGIC
    w.u8(WIRE_VERSION)
    w.u8(0)
    w.u16(0)
    w.u32(0)                                  # total, patched below
    w.u32(0)                                  # features, patched below
    features = 0
    w.str(p.id, 1, MAX_ID, "id")
    w.str(p.name, 1, MAX_NAME, "name")
    for i, s in enumerate(p.legend):
        w.str(s, 0, MAX_LEGEND, f"legend[{i}]")
    visual = VISUAL.index(karl.get("visual", "label"))
    shape = SHAPE.index(karl.get("shape", "cube")) if visual == 1 else 0
    style = STYLE.index(karl.get("shape_style", "face"))
    features |= F_SHAPE if visual == 1 else F_LABEL_VISUAL
    if shape or style:
        features |= F_SHAPE_EXT
    for v in (visual, shape, style, 1 if karl.get("shape_stepped") else 0):
        w.u8(v)
    for c in karl.get("plasma") or (0, 0, 0):
        w.u32(int(c))
    icon24 = _icon(karl["icon24"], ICON24_BYTES) if "icon24" in karl else None
    icon48 = _icon(karl["icon48"], ICON48_BYTES) if "icon48" in karl else None
    w.u8((1 if icon24 else 0) | (2 if icon48 else 0))
    if icon24:
        w.buf += icon24
    if icon48:
        w.buf += icon48
    for name in SLOTS:
        s = p.slots[name]
        w.u8(KIND.index(s.kind))
        w.u8(FX.index(s.fx))
        w.u8(0xFF if s.button is None or s.kind == "none" else s.button)
        w.str(s.label, 0, MAX_LABEL, f"slots.{name}.label")
    mod, key = _display(p.search)
    w.u8(mod)
    w.str(key, 0, keymap.LABEL_MAX, "search key")

    params, param_index = [], {}
    field_mode = 1 if p.param_keys.field else 0
    for ring in p.rings:
        for cmd in ring.commands:
            if cmd.param is not None:
                k = _param_key(cmd.param, field_mode)
                if k not in param_index:
                    param_index[k] = len(params)
                    params.append(cmd.param)
    if len(params) > WIRE_PARAMS_MAX:
        raise ProfileError(f"wire: {len(params)} different params, the knob takes {WIRE_PARAMS_MAX}")
    w.u8(len(params))
    for prm in params:
        w.str(prm.label, 1, MAX_LABEL, "param label")
        w.str(prm.label_neg or "", 0, MAX_LABEL, "param label_neg")
        for v in prm.steps:
            w.f32(v)
        w.f32(prm.free_step)
        lo, hi = _f32(prm.min), _f32(prm.max)
        w.f32(min(max(_f32(prm.start), lo), hi))
        w.f32(prm.min)
        w.f32(prm.max)
        w.u8(prm.decimals)
        flags = (1 if prm.deg else 0) | (2 if prm.axes else 0) | (4 if prm.planes else 0) | (8 if prm.uniform else 0)
        if flags & 14:
            features |= F_PARAM_CONSTRAINTS
        w.u8(flags)
        w.u8(PVISUAL.index(prm.visual))
        w.u8(prm.modes)
        w.u8(prm.axis_default)
        w.u8(field_mode)

    if len(p.scenes) > WIRE_SCENES_MAX:
        raise ProfileError(f"wire: {len(p.scenes)} scenes, the knob takes {WIRE_SCENES_MAX}")
    w.u8(len(p.scenes))
    for base, frames in p.scenes:
        w.u8(len(base))
        for e in base:
            _el(w, e)
        w.u8(len(frames))
        for ms, els in frames:
            w.u16(ms)
            w.u8(len(els))
            for e in els:
                _el(w, e)

    w.u8(len(p.rings))
    for ring in p.rings:
        w.str(ring.name, 1, MAX_LABEL, "ring name")
        w.str(ring.tab, 1, MAX_TAB, "ring tab")
        w.u8(SLOTS.index(ring.slot))
        w.u8(len(ring.commands))
        for cmd in ring.commands:
            w.str(cmd.name, 1, MAX_LABEL, "command name")
            flags = ((CMD_SEARCH if cmd.kind == "actions" else 0) | (CMD_DISABLED if cmd.disabled else 0)
                     | (CMD_MACRO if cmd.kind == "macro" else 0))
            if cmd.disabled:
                features |= F_DISABLED_CMDS
            mod, key = _display(cmd.chord) if cmd.kind == "keys" else (0, "")
            w.u8(flags)
            w.u8(mod)
            w.str(key, 0, keymap.LABEL_MAX, f"{ring.name}/{cmd.name} key")
            w.u8(0xFF if cmd.scene is None else cmd.scene)
            w.u8(0xFF if cmd.param is None else param_index[_param_key(cmd.param, field_mode)])
    total = len(w.buf) + 4
    if total > WIRE_MAX:
        raise ProfileError(f"wire: {total} bytes, the knob takes {WIRE_MAX}")
    struct.pack_into("<I", w.buf, 8, total)
    struct.pack_into("<I", w.buf, 12, features)
    w.u32(zlib.crc32(bytes(w.buf)) & 0xFFFFFFFF)
    return bytes(w.buf)


def _f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def _param_key(p, field_mode):
    return (p.label, p.label_neg or "", tuple(_f32(v) for v in p.steps), _f32(p.free_step), _f32(p.start),
            _f32(p.min), _f32(p.max), p.decimals, p.deg, p.axes, p.planes, p.uniform, p.visual, p.modes,
            p.axis_default, field_mode)


def _el(w, e):
    op, color, x, y, ww, h, arg, d, flags = e
    for v in (op, color):
        w.u8(v)
    w.i8(x)
    w.i8(y)
    for v in (ww, h, arg, d, flags):
        w.u8(v)


# ======================================================================================== reference decoder
class WireError(ValueError):
    """decode_wire's refusal: APP_PROFILES.md section 6 code and the byte offset."""

    def __init__(self, code, offset):
        self.code, self.offset = code, offset
        super().__init__(f"decode:{code}@{offset}")


W_SHORT, W_MAGIC, W_VERSION, W_TOTAL, W_CRC, W_FEATURE, W_STRING, W_RANGE, W_COUNT, W_INDEX, W_ID, W_TRAILING, \
    W_FLOAT = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14


class _R:
    def __init__(self, data, end):
        self.data, self.pos, self.end = data, 0, end

    def take(self, n):
        if self.pos + n > self.end:
            raise WireError(W_SHORT, self.pos)
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self, hi=255, code=W_RANGE):
        at = self.pos
        v = self.take(1)[0]
        if v > hi:
            raise WireError(code, at)
        return v

    def i8(self):
        return struct.unpack("<b", self.take(1))[0]

    def u16(self, hi=0xFFFF):
        at = self.pos
        v = struct.unpack("<H", self.take(2))[0]
        if v > hi:
            raise WireError(W_RANGE, at)
        return v

    def u32(self, hi=0xFFFFFFFF):
        at = self.pos
        v = struct.unpack("<I", self.take(4))[0]
        if v > hi:
            raise WireError(W_RANGE, at)
        return v

    def f32(self):
        at = self.pos
        v = struct.unpack("<f", self.take(4))[0]
        if not math.isfinite(v) or abs(v) > FLOAT_MAX:
            raise WireError(W_FLOAT, at)
        return v

    def str(self, lo, hi):
        at = self.pos
        n = self.take(1)[0]
        if not lo <= n <= hi:
            raise WireError(W_STRING, at)
        data = self.take(n)
        if any(not 0x20 <= b <= 0x7E for b in data):
            raise WireError(W_STRING, at)
        return data.decode("ascii")

    def el(self):
        op, color = self.u8(14), self.u8(4)
        x, y = self.i8(), self.i8()
        return (op, color, x, y, *(self.u8() for _ in range(5)))


def decode_wire(blob, features_allowed=FEATURES_ALL):
    """Strict reference decoder of APP_PROFILES.md (the knob's rules): a dict, or WireError(code, off)."""
    data = bytes(blob)
    if len(data) < 20:
        raise WireError(W_SHORT, len(data))
    if data[:4] != WIRE_MAGIC:
        raise WireError(W_MAGIC, 0)
    if data[4] != WIRE_VERSION or data[5] or data[6:8] != b"\0\0":
        raise WireError(W_VERSION, 4)
    total, features = struct.unpack_from("<II", data, 8)
    if total != len(data) or total > WIRE_MAX:
        raise WireError(W_TOTAL, 8)
    if zlib.crc32(data[:-4]) & 0xFFFFFFFF != struct.unpack_from("<I", data, total - 4)[0]:
        raise WireError(W_CRC, total - 4)
    if features & ~features_allowed:
        raise WireError(W_FEATURE, 12)
    r = _R(data, total - 4)
    r.pos = 16
    at = r.pos
    out = {"features": features, "id": r.str(1, MAX_ID)}
    if not _ID.fullmatch(out["id"]):
        raise WireError(W_ID, at)
    out["name"] = r.str(1, MAX_NAME)
    out["legend"] = [r.str(0, MAX_LEGEND) for _ in range(4)]
    out["visual"], out["shape"], out["shape_style"], out["stepped"] = r.u8(1), r.u8(2), r.u8(2), r.u8(1)
    if out["visual"] == 0 and out["shape"]:
        raise WireError(W_RANGE, r.pos - 3)
    out["plasma"] = [r.u32(0xFFFFFF) for _ in range(3)]
    icons = r.u8(3)
    out["icon24"] = r.take(ICON24_BYTES) if icons & 1 else None
    out["icon48"] = r.take(ICON48_BYTES) if icons & 2 else None
    out["slots"] = []
    for _ in SLOTS:
        kind, fx = r.u8(5), r.u8(4)
        at = r.pos
        button = r.u8()
        if button != 0xFF and button > 3:
            raise WireError(W_RANGE, at)
        out["slots"].append({"kind": kind, "fx": fx, "button": button, "label": r.str(0, MAX_LABEL)})
    out["search"] = {"mod": r.u8(15), "key": r.str(0, keymap.LABEL_MAX)}
    n = r.u8(WIRE_PARAMS_MAX, W_COUNT)
    out["params"] = []
    for _ in range(n):
        prm = {"label": r.str(1, MAX_LABEL), "label_neg": r.str(0, MAX_LABEL),
               "steps": [r.f32() for _ in range(3)], "free_step": r.f32()}
        at = r.pos
        prm["start"], prm["min"], prm["max"] = r.f32(), r.f32(), r.f32()
        if not prm["min"] <= prm["start"] <= prm["max"]:
            raise WireError(W_RANGE, at)
        prm.update(decimals=r.u8(4), flags=r.u8(15), visual=r.u8(9), modes=r.u8(15), axis_default=r.u8(3),
                   field=r.u8(1))
        out["params"].append(prm)
    n = r.u8(WIRE_SCENES_MAX, W_COUNT)
    out["scenes"] = []
    for _ in range(n):
        base = [r.el() for _ in range(r.u8(MAX_ELEMENTS, W_COUNT))]
        frames = []
        for _ in range(r.u8(MAX_FRAMES, W_COUNT)):
            ms = r.u16(60000)
            frames.append((ms, [r.el() for _ in range(r.u8(MAX_ELEMENTS, W_COUNT))]))
        out["scenes"].append((base, frames))
    n = r.u8(MAX_RINGS, W_COUNT)
    out["rings"] = []
    for _ in range(n):
        ring = {"name": r.str(1, MAX_LABEL), "tab": r.str(1, MAX_TAB), "slot": r.u8(4)}
        at = r.pos
        count = r.u8(MAX_CMDS, W_COUNT)
        if count == 0:
            raise WireError(W_COUNT, at)
        ring["cmds"] = []
        for _ in range(count):
            cmd = {"name": r.str(1, MAX_LABEL), "flags": r.u8(7), "mod": r.u8(15), "key": r.str(0, keymap.LABEL_MAX)}
            at = r.pos
            cmd["scene"], cmd["param"] = r.u8(), r.u8()
            if cmd["scene"] != 0xFF and cmd["scene"] >= len(out["scenes"]):
                raise WireError(W_INDEX, at)
            if cmd["param"] != 0xFF and cmd["param"] >= len(out["params"]):
                raise WireError(W_INDEX, at + 1)
            ring["cmds"].append(cmd)
        out["rings"].append(ring)
    if r.pos != total - 4:
        raise WireError(W_TRAILING, r.pos)
    out["crc"] = struct.unpack_from("<I", data, total - 4)[0]
    return out


# ======================================================================================== the library
def _sidecar_name(pid):
    return f"{pid}.windows.json"


def _karl_files(folder):
    """Karl files of a profile folder: karl/*.json (the bundled layout) and *.json beside the sidecars."""
    if folder is None or not Path(folder).is_dir():
        return []
    folder = Path(folder)
    files = sorted((folder / "karl").glob("*.json")) if (folder / "karl").is_dir() else []
    files += [f for f in sorted(folder.glob("*.json")) if not f.name.endswith(".windows.json")]
    return [f for f in files if f.name != "SOURCE.json" and f.name != "index.json"]


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Library:
    """The profiles Desk Dial knows, by id: user > updates > bundled. Per id, the Karl file comes from the
    highest source that has a good one, and the sidecar from the highest source that has one that fits
    it (an updated Karl file keeps the bundled Onshape layout). A bad file is skipped with a problem; an
    id whose every candidate is bad keeps the profile it had before (last good)."""

    def __init__(self, bundled_dir, updates_dir=None, user_dir=None, rules=None):
        self.dirs = {"bundled": Path(bundled_dir) if bundled_dir else None,
                     "updates": Path(updates_dir) if updates_dir else None,
                     "user": Path(user_dir) if user_dir else None}
        self.rules = rules or {}
        self._profiles = {}
        self.problems = []
        self.reload()

    def _sidecars(self, pid):
        out = []
        for source in reversed(SOURCES):
            folder = self.dirs[source]
            if folder is not None and (folder / _sidecar_name(pid)).is_file():
                out.append(folder / _sidecar_name(pid))
        return out

    def reload(self):
        problems = _check_rules_arg(self.rules)
        rules = self.rules if not problems else {}
        candidates = {}
        for source in reversed(SOURCES):
            for path in _karl_files(self.dirs[source]):
                candidates.setdefault(path.stem, []).append((source, path))
        loaded = {}
        for pid, options in candidates.items():
            for source, path in options:
                if reserved_id(pid):
                    problems.append(f"{path.name}: {RESERVED_ID_PROBLEM}")     # DD-7: never opened
                    continue
                if not _ID.fullmatch(pid):
                    problems.append(f"{path.name}: the file name must be the profile id (a-z, 0-9, _, -)")
                    continue
                sidecars = self._sidecars(pid) or [None]
                errors = []
                for sidecar in sidecars:
                    try:
                        profile = load_pair(path, sidecar, source=source, rules=rules)
                    except ProfileError as exc:
                        errors.extend(exc.problems)
                        continue
                    if profile.id != pid:
                        errors.append(f"{path.name}: says it is \"{profile.id}\"")
                        continue
                    loaded[pid] = profile
                    break
                problems.extend(f"{source}: {e}" for e in errors)
                if pid in loaded:
                    break
            if pid not in loaded and pid in self._profiles:
                loaded[pid] = self._profiles[pid]
                problems.append(f"{pid}: kept the last good version")
        self._profiles = loaded
        self.problems = problems
        return problems

    def profiles(self):
        def key(p):
            return (ORDER.index(p.id), "") if p.id in ORDER else (len(ORDER), p.name.lower(), p.id)
        return sorted(self._profiles.values(), key=key)

    def get(self, pid):
        return self._profiles.get(pid)

    def import_file(self, path):
        """Check a Karl file (and its sibling .windows.json, if any) fully, then copy it into user/.
        Data only: nothing in it is ever run. Raises ProfileError with the problems in plain words."""
        user = self.dirs["user"]
        if user is None:
            raise ProfileError("import: no user profiles folder")
        path = Path(path)
        if reserved_id(path.name):
            raise ProfileError(f"{path.name}: {RESERVED_ID_PROBLEM}")          # DD-7: a device, never opened
        try:
            if path.stat().st_size > FILE_MAX:
                raise ProfileError(f"{path.name}: bigger than {FILE_MAX // 1024} KB")
            raw = path.read_bytes()
        except OSError as exc:
            raise ProfileError(f"{path.name}: can't read it ({exc.strerror or exc})") from None
        karl = read_json(raw, path.name)
        problems = [f"{path.name}: {p}" for p in validate_karl(karl)]
        if problems:
            raise ProfileError(problems)
        pid = karl["id"]
        stem = path.name[:-5] if path.name.endswith(".json") else path.stem
        sibling = path.with_name(f"{stem}.windows.json")
        sidecar_raw = None
        if sibling.is_file():
            sidecar = sibling
            sidecar_raw = _read_bounded(sibling)                       # DD-5: size first, one read, capped
        else:
            existing = self._sidecars(pid)
            sidecar = existing[0] if existing else None
        # Raises with the problems. The sibling is validated from the very bytes written below (never re-read).
        _load_docs(raw, path.name, sidecar, "user", self.rules, overlay_raw=sidecar_raw)
        _atomic_write(user / f"{pid}.json", raw)
        if sidecar_raw is not None:
            _atomic_write(user / _sidecar_name(pid), sidecar_raw)
        self.reload()
        profile = self.get(pid)
        if profile is None or profile.source != "user":
            raise ProfileError(f"{path.name}: copied, but it didn't load ({'; '.join(self.problems)})")
        return profile
