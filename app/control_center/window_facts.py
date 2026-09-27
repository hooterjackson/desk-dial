"""Window facts for the carousel labels and icons (CAROUSEL.md sections 6 and 7).

Win32/COM helpers the adapter calls on the IconWorker's STA thread (never on the Tk
thread for the COM ones: AppsFolder lookups take 9-77 ms and Core Audio 15-25 ms):

- ``version_strings(path)``: FileDescription and ProductName from the exe's version
  resource, trying the UI-language translation first, then the listed ones, then
  common fallbacks. Cached per path for the process lifetime; network (UNC or
  mapped-drive) and non-absolute paths are never read.
- ``process_aumid(hwnd)``: the packaged app's AUMID (GetApplicationUserModelId), also
  for UWP frames (the hosted CoreWindow's process, else the frame's property store).
- ``window_property_store(hwnd)``: {aumid, relaunch_display_name, relaunch_icon} from
  SHGetPropertyStoreForWindow (PKEY_AppUserModel_ID / RelaunchDisplayNameResource /
  RelaunchIconResource). Chrome's per-profile names live there.
- ``package_display_name(aumid)`` / ``package_logo(aumid, px)``: the shell's
  ``shell:AppsFolder\\<AUMID>`` item (IShellItem::GetDisplayName and
  IShellItemImageFactory::GetImage, whose icon-only bitmap carries straight alpha).
  Answers are cached per AUMID for the process lifetime; failures for 60 s only, so a
  package that registers late or a transient shell failure is retried.
- ``relaunch_icon(resource, px)``: a RelaunchIconResource (.ico file, or a module
  icon by index) as an RGBA image.
- ``monitor_friendly_name(hwnd)``: the EDID name of the window's monitor
  (QueryDisplayConfig + DisplayConfigGetDeviceInfo), "Built-in display" for internal
  panels, with a position word when two monitors share a model.
- ``audible_pids()``: processes with an active Core Audio session on any active
  render or capture endpoint, plus their same-exe ancestors (Toolhelp parent walk),
  so a browser window's pid matches its audio-service child.
- ``letter_tile(name, px, radius=0)``: the missing-icon tile (section 7).

Rules every function follows:
- Exception-safe: a failure returns None, {}, set() or a plain tile, never raises.
- Every COM interface obtained is released on every path; CoTaskMem strings,
  PROPVARIANTs, HBITMAPs, HICONs, process and snapshot handles are freed.
- COM is initialised per call (apartment-threaded; on the IconWorker thread that is
  only a reference-count bump) and balanced.
- Nothing is logged. Titles, profile names, monitor names, icon paths and AUMIDs are
  personal or identifying and never leave the return values.
- Win32 entry points come from a private declaration table on private WinDLL
  instances (``FactsApi``), never ``ctypes.windll``; tests inject a fake ``api``.
"""
from __future__ import annotations

import ctypes as C
import os
import re
import struct
import sys
import threading
import time
import unicodedata
import zlib
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

__all__ = [
    "FactsApi", "version_strings", "process_aumid", "window_property_store", "package_display_name",
    "package_logo", "relaunch_icon", "monitor_friendly_name", "audible_pids", "letter_tile",
    "tile_colour", "tile_letter", "white_contrast", "font_covers", "clear_caches",
    "BRAND_TILE_COLOURS", "TILE_PALETTE", "MIN_TILE_CONTRAST",
]

# ------------------------------------------------------------------ Win32 types
DWORD = C.c_uint32
LONG = C.c_int32
BOOL = C.c_int32
UINT = C.c_uint32
WORD = C.c_uint16
HRESULT = C.c_int32
HANDLE = C.c_void_p
LPARAM = C.c_ssize_t
WINFUNCTYPE = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)
ENUMPROC = WINFUNCTYPE(BOOL, HANDLE, LPARAM)


class GUID(C.Structure):
    _fields_ = [("Data1", C.c_uint32), ("Data2", C.c_uint16), ("Data3", C.c_uint16),
                ("Data4", C.c_ubyte * 8)]


def _guid(text):
    raw = bytes.fromhex(text.strip("{}").replace("-", ""))
    return GUID(int.from_bytes(raw[0:4], "big"), int.from_bytes(raw[4:6], "big"),
                int.from_bytes(raw[6:8], "big"), (C.c_ubyte * 8)(*raw[8:]))


class PROPERTYKEY(C.Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(C.Structure):
    # vt, three reserved WORDs, then a union whose largest members are two pointers wide.
    _fields_ = [("vt", C.c_ushort), ("wReserved1", C.c_ushort), ("wReserved2", C.c_ushort),
                ("wReserved3", C.c_ushort), ("p", C.c_void_p), ("p2", C.c_void_p)]


class SIZE(C.Structure):
    _fields_ = [("cx", LONG), ("cy", LONG)]


class RECT(C.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class MONITORINFOEXW(C.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD),
                ("szDevice", C.c_wchar * 32)]


class LUID(C.Structure):
    _fields_ = [("LowPart", DWORD), ("HighPart", LONG)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(C.Structure):
    _fields_ = [("adapterId", LUID), ("id", C.c_uint32), ("modeInfoIdx", C.c_uint32),
                ("statusFlags", C.c_uint32)]


class DISPLAYCONFIG_RATIONAL(C.Structure):
    _fields_ = [("Numerator", C.c_uint32), ("Denominator", C.c_uint32)]


class DISPLAYCONFIG_PATH_TARGET_INFO(C.Structure):
    _fields_ = [("adapterId", LUID), ("id", C.c_uint32), ("modeInfoIdx", C.c_uint32),
                ("outputTechnology", C.c_uint32), ("rotation", C.c_uint32), ("scaling", C.c_uint32),
                ("refreshRate", DISPLAYCONFIG_RATIONAL), ("scanLineOrdering", C.c_uint32),
                ("targetAvailable", BOOL), ("statusFlags", C.c_uint32)]


class DISPLAYCONFIG_PATH_INFO(C.Structure):
    _fields_ = [("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
                ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO), ("flags", C.c_uint32)]


class DISPLAYCONFIG_MODE_INFO(C.Structure):
    # The union (target mode 48 bytes, source mode 20, desktop image 40) is kept raw.
    _fields_ = [("infoType", C.c_uint32), ("id", C.c_uint32), ("adapterId", LUID),
                ("mode", C.c_ubyte * 48)]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(C.Structure):
    _fields_ = [("type", C.c_uint32), ("size", C.c_uint32), ("adapterId", LUID), ("id", C.c_uint32)]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(C.Structure):
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER), ("viewGdiDeviceName", C.c_wchar * 32)]


class DISPLAYCONFIG_TARGET_DEVICE_NAME(C.Structure):
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER), ("flags", C.c_uint32),
                ("outputTechnology", C.c_uint32), ("edidManufactureId", C.c_uint16),
                ("edidProductCodeId", C.c_uint16), ("connectorInstance", C.c_uint32),
                ("monitorFriendlyDeviceName", C.c_wchar * 64), ("monitorDevicePath", C.c_wchar * 128)]


class ICONINFO(C.Structure):
    _fields_ = [("fIcon", BOOL), ("xHotspot", DWORD), ("yHotspot", DWORD),
                ("hbmMask", HANDLE), ("hbmColor", HANDLE)]


class BITMAP(C.Structure):
    _fields_ = [("bmType", LONG), ("bmWidth", LONG), ("bmHeight", LONG), ("bmWidthBytes", LONG),
                ("bmPlanes", C.c_uint16), ("bmBitsPixel", C.c_uint16), ("bmBits", C.c_void_p)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG), ("biPlanes", WORD),
                ("biBitCount", WORD), ("biCompression", DWORD), ("biSizeImage", DWORD),
                ("biXPelsPerMeter", LONG), ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD),
                ("biClrImportant", DWORD)]


class BITMAPINFO(C.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 1)]


class PROCESSENTRY32W(C.Structure):
    _fields_ = [("dwSize", DWORD), ("cntUsage", DWORD), ("th32ProcessID", DWORD),
                ("th32DefaultHeapID", C.c_size_t), ("th32ModuleID", DWORD), ("cntThreads", DWORD),
                ("th32ParentProcessID", DWORD), ("pcPriClassBase", LONG), ("dwFlags", DWORD),
                ("szExeFile", C.c_wchar * 260)]


STRUCTURE_SIZES_X64 = {
    GUID: 16, PROPERTYKEY: 20, PROPVARIANT: 24, SIZE: 8, MONITORINFOEXW: 104, LUID: 8,
    DISPLAYCONFIG_PATH_INFO: 72, DISPLAYCONFIG_MODE_INFO: 64, DISPLAYCONFIG_DEVICE_INFO_HEADER: 20,
    DISPLAYCONFIG_SOURCE_DEVICE_NAME: 84, DISPLAYCONFIG_TARGET_DEVICE_NAME: 420, ICONINFO: 32,
    BITMAP: 32, BITMAPINFOHEADER: 40, PROCESSENTRY32W: 568,
}

# ------------------------------------------------------------------ Win32 constants
S_OK, S_FALSE = 0, 1
COINIT_APARTMENTTHREADED = 0x2
CLSCTX_ALL = 0x17
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_INSUFFICIENT_BUFFER = 122
APPLICATION_USER_MODEL_ID_MAX_LENGTH = 130
FILE_VER_GET_LOCALISED = 0x01
DRIVE_NO_ROOT_DIR, DRIVE_REMOTE = 1, 4
VT_EMPTY, VT_BSTR, VT_LPWSTR = 0, 8, 31
SIGDN_NORMALDISPLAY = 0
SIIGBF_BIGGERSIZEOK, SIIGBF_ICONONLY = 0x01, 0x04
BI_RGB, DIB_RGB_COLORS = 0, 0
MONITOR_DEFAULTTONEAREST = 2
QDC_ONLY_ACTIVE_PATHS = 2
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME, DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 1, 2
DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE = 1
# Output technologies of built-in panels: LVDS, DisplayPort embedded, UDI embedded, internal.
INTERNAL_OUTPUT_TECHNOLOGIES = frozenset({6, 11, 13, 0x80000000})
TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE_VALUE = C.c_void_p(-1).value
E_DATAFLOW_ALL, DEVICE_STATE_ACTIVE = 2, 0x1
AUDIO_SESSION_STATE_ACTIVE = 1

IID_IPropertyStore = _guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
IID_IShellItem = _guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")
IID_IShellItemImageFactory = _guid("bcc18b79-ba16-442f-80c4-8a59c30c463b")
CLSID_MMDeviceEnumerator = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioSessionManager2 = _guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = _guid("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d")
_APPUSERMODEL = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"
PKEY_AppUserModel_RelaunchIconResource = PROPERTYKEY(_guid(_APPUSERMODEL), 3)
PKEY_AppUserModel_RelaunchDisplayNameResource = PROPERTYKEY(_guid(_APPUSERMODEL), 4)
PKEY_AppUserModel_ID = PROPERTYKEY(_guid(_APPUSERMODEL), 5)

# COM vtable slots (IUnknown: 0 QueryInterface, 1 AddRef, 2 Release).
SLOT_QUERY_INTERFACE, SLOT_RELEASE = 0, 2
SLOT_PROPERTYSTORE_GETVALUE = 5            # GetCount 3, GetAt 4, GetValue 5
SLOT_SHELLITEM_GETDISPLAYNAME = 5          # BindToHandler 3, GetParent 4, GetDisplayName 5
SLOT_IMAGEFACTORY_GETIMAGE = 3
SLOT_ENUMERATOR_ENUMAUDIOENDPOINTS = 3
SLOT_COLLECTION_GETCOUNT, SLOT_COLLECTION_ITEM = 3, 4
SLOT_DEVICE_ACTIVATE = 3
SLOT_MANAGER2_GETSESSIONENUMERATOR = 5     # GetAudioSessionControl 3, GetSimpleAudioVolume 4
SLOT_SESSIONENUM_GETCOUNT, SLOT_SESSIONENUM_GETSESSION = 3, 4
SLOT_SESSIONCONTROL_GETSTATE = 3
SLOT_SESSIONCONTROL2_GETPROCESSID = 14     # IAudioSessionControl 3..11, GetSessionIdentifier 12, ...

_QUERY_INTERFACE = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(GUID), C.POINTER(C.c_void_p))
_RELEASE = WINFUNCTYPE(C.c_ulong, C.c_void_p)
_PROPERTYSTORE_GETVALUE = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(PROPERTYKEY), C.POINTER(PROPVARIANT))
_SHELLITEM_GETDISPLAYNAME = WINFUNCTYPE(HRESULT, C.c_void_p, C.c_int, C.POINTER(C.c_void_p))
_IMAGEFACTORY_GETIMAGE = WINFUNCTYPE(HRESULT, C.c_void_p, SIZE, C.c_int, C.POINTER(HANDLE))
_ENUMAUDIOENDPOINTS = WINFUNCTYPE(HRESULT, C.c_void_p, C.c_int, DWORD, C.POINTER(C.c_void_p))
_COLLECTION_GETCOUNT = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(UINT))
_COLLECTION_ITEM = WINFUNCTYPE(HRESULT, C.c_void_p, UINT, C.POINTER(C.c_void_p))
_DEVICE_ACTIVATE = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(GUID), DWORD, C.c_void_p, C.POINTER(C.c_void_p))
_GETSESSIONENUMERATOR = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(C.c_void_p))
_SESSIONENUM_GETCOUNT = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(C.c_int))
_SESSIONENUM_GETSESSION = WINFUNCTYPE(HRESULT, C.c_void_p, C.c_int, C.POINTER(C.c_void_p))
_SESSIONCONTROL_GETSTATE = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(C.c_int))
_SESSIONCONTROL2_GETPROCESSID = WINFUNCTYPE(HRESULT, C.c_void_p, C.POINTER(DWORD))

# ------------------------------------------------------------------ declarations
_DLLS = (("u", "user32"), ("k", "kernel32"), ("v", "version"), ("s", "shell32"), ("o", "ole32"),
         ("g", "gdi32"))
# (dll, export, restype, argtypes). Private WinDLL instances only, never ctypes.windll.
_DECLARATIONS = (
    ("u", "GetWindowThreadProcessId", DWORD, (HANDLE, C.POINTER(DWORD))),
    ("u", "GetClassNameW", C.c_int, (HANDLE, C.c_wchar_p, C.c_int)),
    ("u", "EnumChildWindows", BOOL, (HANDLE, ENUMPROC, LPARAM)),
    ("u", "MonitorFromWindow", HANDLE, (HANDLE, DWORD)),
    ("u", "GetMonitorInfoW", BOOL, (HANDLE, C.POINTER(MONITORINFOEXW))),
    ("u", "GetDisplayConfigBufferSizes", LONG, (UINT, C.POINTER(UINT), C.POINTER(UINT))),
    ("u", "QueryDisplayConfig", LONG, (UINT, C.POINTER(UINT), C.POINTER(DISPLAYCONFIG_PATH_INFO),
                                       C.POINTER(UINT), C.POINTER(DISPLAYCONFIG_MODE_INFO), C.c_void_p)),
    ("u", "DisplayConfigGetDeviceInfo", LONG, (C.c_void_p,)),
    ("u", "GetIconInfo", BOOL, (HANDLE, C.POINTER(ICONINFO))),
    ("u", "DestroyIcon", BOOL, (HANDLE,)),
    ("k", "OpenProcess", HANDLE, (DWORD, BOOL, DWORD)),
    ("k", "CloseHandle", BOOL, (HANDLE,)),
    ("k", "GetApplicationUserModelId", LONG, (HANDLE, C.POINTER(UINT), C.c_wchar_p)),
    ("k", "GetUserDefaultUILanguage", WORD, ()),
    ("k", "GetDriveTypeW", UINT, (C.c_wchar_p,)),
    ("k", "CreateToolhelp32Snapshot", HANDLE, (DWORD, DWORD)),
    ("k", "Process32FirstW", BOOL, (HANDLE, C.POINTER(PROCESSENTRY32W))),
    ("k", "Process32NextW", BOOL, (HANDLE, C.POINTER(PROCESSENTRY32W))),
    ("v", "GetFileVersionInfoSizeExW", DWORD, (DWORD, C.c_wchar_p, C.POINTER(DWORD))),
    ("v", "GetFileVersionInfoExW", BOOL, (DWORD, C.c_wchar_p, DWORD, DWORD, C.c_void_p)),
    ("v", "VerQueryValueW", BOOL, (C.c_void_p, C.c_wchar_p, C.POINTER(C.c_void_p), C.POINTER(UINT))),
    ("s", "SHGetPropertyStoreForWindow", HRESULT, (HANDLE, C.POINTER(GUID), C.POINTER(C.c_void_p))),
    ("s", "SHCreateItemFromParsingName", HRESULT, (C.c_wchar_p, C.c_void_p, C.POINTER(GUID),
                                                   C.POINTER(C.c_void_p))),
    ("s", "SHDefExtractIconW", HRESULT, (C.c_wchar_p, C.c_int, UINT, C.POINTER(HANDLE), C.POINTER(HANDLE), UINT)),
    ("o", "CoInitializeEx", HRESULT, (C.c_void_p, DWORD)),
    ("o", "CoUninitialize", None, ()),
    ("o", "CoCreateInstance", HRESULT, (C.POINTER(GUID), C.c_void_p, DWORD, C.POINTER(GUID),
                                        C.POINTER(C.c_void_p))),
    ("o", "CoTaskMemFree", None, (C.c_void_p,)),
    ("o", "PropVariantClear", HRESULT, (C.POINTER(PROPVARIANT),)),
    ("g", "GetObjectW", C.c_int, (HANDLE, C.c_int, C.c_void_p)),
    ("g", "CreateCompatibleDC", HANDLE, (HANDLE,)),
    ("g", "DeleteDC", BOOL, (HANDLE,)),
    ("g", "GetDIBits", C.c_int, (HANDLE, HANDLE, UINT, UINT, C.c_void_p, C.POINTER(BITMAPINFO), UINT)),
    ("g", "DeleteObject", BOOL, (HANDLE,)),
)
DECLARED_NAMES = tuple(name for _dll, name, _res, _args in _DECLARATIONS)


class FactsApi:
    """Win32 declarations only; constructing it resolves exports and calls nothing.
    An export this Windows lacks is None (its helper then answers None/{}/set())."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("window facts need Windows")
        dlls = {attribute: C.WinDLL(name, use_last_error=True) for attribute, name in _DLLS}
        for attribute, name, result, args in _DECLARATIONS:
            try:
                function = getattr(dlls[attribute], name)
                function.restype, function.argtypes = result, args
            except AttributeError:
                function = None
            setattr(self, name, function)


_API = None
_API_LOCK = threading.Lock()


def _default_api():
    global _API
    with _API_LOCK:
        if _API is None:
            _API = FactsApi()
        return _API


# ------------------------------------------------------------------ caches
_CACHE_LOCK = threading.Lock()
_VERSION_CACHE = OrderedDict()          # normalised path -> {FileDescription, ProductName}
_PACKAGE_NAME_CACHE = OrderedDict()     # AUMID -> display name or _Failure
_PACKAGE_LOGO_CACHE = OrderedDict()     # (AUMID, px) -> RGBA or _Failure
_RELAUNCH_ICON_CACHE = OrderedDict()    # (path, index, px, mtime, size) -> RGBA or None
_TILE_CACHE = OrderedDict()             # (name, px, radius) -> RGBA
_DISPLAY_CACHE = {"at": None, "names": {}}
VERSION_CACHE_SIZE = 256
PACKAGE_CACHE_SIZE = 128
ICON_CACHE_SIZE = 64
TILE_CACHE_SIZE = 128
DISPLAY_NAMES_TTL_SECONDS = 2.0
FAILURE_TTL_SECONDS = 60.0              # package name/logo failures are retried after this
MAX_VERSION_BLOCK_BYTES = 16 * 1024 * 1024
MAX_ICON_FILE_BYTES = 8 * 1024 * 1024
MAX_BITMAP_EDGE = 1024
MAX_PX = 512
_MISSING = object()
_clock = time.monotonic                 # tests patch it


class _Failure:
    """A cached failed lookup and when it happened (``_clock`` seconds)."""
    __slots__ = ("at",)

    def __init__(self, at):
        self.at = at


def _cache_get(cache, key):
    with _CACHE_LOCK:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
    return _MISSING


def _cache_put(cache, key, value, limit):
    with _CACHE_LOCK:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)


def _cache_get_expiring(cache, key):
    """Like _cache_get for a cache written by _cache_put_expiring: a failure answers None
    for FAILURE_TTL_SECONDS, then _MISSING so the caller looks again."""
    value = _cache_get(cache, key)
    if isinstance(value, _Failure):
        return None if _clock() - value.at < FAILURE_TTL_SECONDS else _MISSING
    return value


def _cache_put_expiring(cache, key, value, limit):
    """Answers are kept for the process lifetime (LRU); a failure (None) expires."""
    _cache_put(cache, key, _Failure(_clock()) if value is None else value, limit)


def clear_caches():
    """Forget every cached fact (tests; a display or package change)."""
    with _CACHE_LOCK:
        for cache in (_VERSION_CACHE, _PACKAGE_NAME_CACHE, _PACKAGE_LOGO_CACHE, _RELAUNCH_ICON_CACHE,
                      _TILE_CACHE):
            cache.clear()
        _DISPLAY_CACHE["at"], _DISPLAY_CACHE["names"] = None, {}


def _copy(image):
    return image.copy() if image is not None else None


# ------------------------------------------------------------------ COM plumbing
@contextmanager
def _com(api):
    """Apartment-threaded COM for one call, balanced. On a thread that already has an
    STA (the IconWorker) this only bumps its count; on an MTA thread
    (RPC_E_CHANGED_MODE) the call proceeds in the existing apartment."""
    result = api.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        yield
    finally:
        if result in (S_OK, S_FALSE):
            api.CoUninitialize()


def _method(pointer, slot, prototype):
    """The interface's ``slot``-th vtable entry as a callable (the object's first field
    is its vtable pointer)."""
    table = C.cast(C.cast(pointer, C.POINTER(C.c_void_p))[0], C.POINTER(C.c_void_p))
    return prototype(table[slot])


def _release(pointer):
    if pointer:
        try:
            _method(pointer, SLOT_RELEASE, _RELEASE)(pointer)
        except Exception:
            pass


def _query_interface(pointer, iid):
    out = C.c_void_p()
    hr = _method(pointer, SLOT_QUERY_INTERFACE, _QUERY_INTERFACE)(pointer, C.byref(iid), C.byref(out))
    return out.value if hr >= 0 and out.value else None


def _clean(value, limit=512):
    """NFC, format characters (zero-width, bidi) removed, control characters and runs
    of whitespace collapsed to one space; None if empty."""
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value)
    text = "".join("" if unicodedata.category(ch) == "Cf" else " " if unicodedata.category(ch) == "Cc" else ch
                   for ch in text)
    text = " ".join(text.split())
    return text[:limit] if text else None


def _clean_id(value):
    """An AUMID: printable, no spaces around, at most 512 characters, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 512 or any(unicodedata.category(ch) in ("Cc", "Cf") for ch in value):
        return None
    return value


# ------------------------------------------------------------------ paths
def _readable_local_path(api, path) -> bool:
    """True for an absolute path on a local drive letter. UNC, \\\\?\\UNC, device and
    relative paths, and mapped network drives, are never read (they can stall)."""
    if not isinstance(path, str):
        return False
    text = path.strip().strip('"')
    if text.startswith("\\\\?\\") or text.startswith("\\\\.\\"):
        text = text[4:]
        if text[:4].upper() == "UNC\\":
            return False
    if text.startswith("\\\\") or text.startswith("//"):
        return False
    match = re.match(r"([A-Za-z]):[\\/]", text)
    if not match:
        return False
    drive_type = getattr(api, "GetDriveTypeW", None)
    if drive_type is not None:
        kind = drive_type(f"{match.group(1)}:\\")
        if kind in (DRIVE_NO_ROOT_DIR, DRIVE_REMOTE):
            return False
    return True


# ------------------------------------------------------------------ version strings
FALLBACK_TRANSLATIONS = ((0x0409, 0x04B0), (0x0409, 0x04E4), (0x0409, 0x0000), (0x0000, 0x04B0))
VERSION_KEYS = ("FileDescription", "ProductName")


def _translation_candidates(pairs, ui_language):
    """(language, codepage) pairs to try: the UI language's, then the same primary
    language's, then the listed ones in order, then the UI language with the Unicode
    and Western code pages, then the US-English and neutral fallbacks."""
    ordered = []

    def add(pair):
        if pair not in ordered:
            ordered.append(pair)

    ui = int(ui_language or 0) & 0xFFFF
    for pair in pairs:
        if ui and pair[0] == ui:
            add(pair)
    for pair in pairs:
        if ui and (pair[0] & 0x3FF) == (ui & 0x3FF):
            add(pair)
    for pair in pairs:
        add(pair)
    if ui:
        add((ui, 0x04B0))
        add((ui, 0x04E4))
    for pair in FALLBACK_TRANSLATIONS:
        add(pair)
    return ordered


def _query_block(api, block, sub_block):
    """(address, byte length) of a value inside ``block``, or None when it is missing
    or does not lie inside the block."""
    pointer, length = C.c_void_p(), UINT()
    if not api.VerQueryValueW(block, sub_block, C.byref(pointer), C.byref(length)) or not pointer.value:
        return None
    return pointer.value, int(length.value)


def _query_string(api, block, sub_block):
    found = _query_block(api, block, sub_block)
    if found is None:
        return None
    address, characters = found
    start, end = C.addressof(block), C.addressof(block) + C.sizeof(block)
    if not characters or not start <= address < end:
        return None
    characters = min(characters, (end - address) // 2)
    return _clean(C.wstring_at(address, characters).split("\x00", 1)[0], limit=256)


def _translations(api, block):
    found = _query_block(api, block, "\\VarFileInfo\\Translation")
    if found is None:
        return []
    address, size = found
    start, end = C.addressof(block), C.addressof(block) + C.sizeof(block)
    if not start <= address < end:
        return []
    size = min(size, end - address) // 4 * 4
    words = struct.unpack(f"<{size // 2}H", C.string_at(address, size)) if size else ()
    return [(words[i], words[i + 1]) for i in range(0, len(words) - 1, 2)]


def _read_version_strings(api, path):
    handle = DWORD()
    size = api.GetFileVersionInfoSizeExW(FILE_VER_GET_LOCALISED, path, C.byref(handle))
    if not size or size > MAX_VERSION_BLOCK_BYTES:
        return None
    block = C.create_string_buffer(int(size))
    if not api.GetFileVersionInfoExW(FILE_VER_GET_LOCALISED, path, 0, size, block):
        return None
    ui_language = api.GetUserDefaultUILanguage() if getattr(api, "GetUserDefaultUILanguage", None) else 0
    found = {}
    for language, codepage in _translation_candidates(_translations(api, block), ui_language):
        base = f"\\StringFileInfo\\{language:04X}{codepage:04X}\\"
        for key in VERSION_KEYS:
            if not found.get(key):
                value = _query_string(api, block, base + key)
                if value:
                    found[key] = value
        if all(found.get(key) for key in VERSION_KEYS):
            break
    return {key: found.get(key, "") for key in VERSION_KEYS}


def version_strings(path, *, api=None) -> dict:
    """{"FileDescription": str, "ProductName": str} ("" when missing) for an exe.

    Cached per case-insensitive path for the process lifetime (failures too). Only
    absolute local paths are read: UNC, device, relative and mapped-network paths
    answer both "" without touching the file. Never raises."""
    empty = {key: "" for key in VERSION_KEYS}
    try:
        if not isinstance(path, str) or not path.strip():
            return empty
        key = path.strip().strip('"').replace("/", "\\").lower()
        cached = _cache_get(_VERSION_CACHE, key)
        if cached is not _MISSING:
            return dict(cached)
        api = api or _default_api()
        result = empty
        if _readable_local_path(api, path) and api.GetFileVersionInfoSizeExW is not None:
            try:
                result = _read_version_strings(api, path.strip().strip('"')) or empty
            except Exception:
                result = empty
        _cache_put(_VERSION_CACHE, key, dict(result), VERSION_CACHE_SIZE)
        return dict(result)
    except Exception:
        return empty


# ------------------------------------------------------------------ AUMIDs
def _window_pid(api, hwnd):
    pid = DWORD()
    api.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return int(pid.value)


def _class_name(api, hwnd):
    buffer = C.create_unicode_buffer(256)
    return buffer.value if api.GetClassNameW(hwnd, buffer, len(buffer)) else ""


def _pid_aumid(api, pid):
    """The packaged process's AUMID (GetApplicationUserModelId), or None."""
    if not pid or api.GetApplicationUserModelId is None:
        return None
    process = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    try:
        length = UINT(APPLICATION_USER_MODEL_ID_MAX_LENGTH)
        buffer = C.create_unicode_buffer(length.value)
        result = api.GetApplicationUserModelId(process, C.byref(length), buffer)
        if result == ERROR_INSUFFICIENT_BUFFER and 0 < length.value <= 4096:
            buffer = C.create_unicode_buffer(length.value)
            result = api.GetApplicationUserModelId(process, C.byref(length), buffer)
        return _clean_id(buffer.value) if result == 0 else None
    finally:
        api.CloseHandle(process)


def _core_window_pid(api, hwnd, frame_pid):
    """The process of a UWP frame's hosted Windows.UI.Core.CoreWindow child, or 0."""
    found = []

    @ENUMPROC
    def visit(child, _lparam):
        try:
            if _class_name(api, child) == "Windows.UI.Core.CoreWindow":
                pid = _window_pid(api, child)
                if pid and pid != frame_pid:
                    found.append(pid)
                    return False
        except Exception:
            pass
        return True

    api.EnumChildWindows(hwnd, visit, 0)
    return found[0] if found else 0


def process_aumid(hwnd, *, api=None):
    """The packaged app's AUMID for a window, or None (an unpackaged app).

    GetApplicationUserModelId on the window's process; for a UWP frame
    (ApplicationFrameWindow), the hosted CoreWindow's process, else the frame's
    property-store AUMID when it names a package ("<family>!<app>"). Never raises."""
    try:
        hwnd = int(hwnd or 0)
        if not hwnd:
            return None
        api = api or _default_api()
        pid = _window_pid(api, hwnd)
        aumid = _pid_aumid(api, pid)
        if aumid:
            return aumid
        if _class_name(api, hwnd) != "ApplicationFrameWindow":
            return None
        aumid = _pid_aumid(api, _core_window_pid(api, hwnd, pid))
        if aumid:
            return aumid
        aumid = window_property_store(hwnd, api=api).get("aumid")
        return aumid if aumid and "!" in aumid else None
    except Exception:
        return None


def _property_string(api, store, key):
    """A string property (VT_LPWSTR / VT_BSTR) from an IPropertyStore, or None. The
    PROPVARIANT is always cleared after a successful GetValue."""
    value = PROPVARIANT()
    hr = _method(store, SLOT_PROPERTYSTORE_GETVALUE, _PROPERTYSTORE_GETVALUE)(store, C.byref(key), C.byref(value))
    if hr < 0:
        return None
    try:
        if value.vt in (VT_LPWSTR, VT_BSTR) and value.p:
            return C.wstring_at(value.p)
        return None
    finally:
        api.PropVariantClear(C.byref(value))


def window_property_store(hwnd, *, api=None) -> dict:
    """{"aumid", "relaunch_display_name", "relaunch_icon"} from the window's property
    store (each a string or None). Indirect "@..." display names are dropped. Personal
    (a browser profile name, an icon path): shown or used, never logged. Never raises."""
    out = {"aumid": None, "relaunch_display_name": None, "relaunch_icon": None}
    try:
        hwnd = int(hwnd or 0)
        api = api or _default_api()
        if not hwnd or api.SHGetPropertyStoreForWindow is None:
            return out
        with _com(api):
            store = C.c_void_p()
            hr = api.SHGetPropertyStoreForWindow(hwnd, C.byref(IID_IPropertyStore), C.byref(store))
            if hr < 0 or not store.value:
                return out
            try:
                for name, key in (("aumid", PKEY_AppUserModel_ID),
                                  ("relaunch_display_name", PKEY_AppUserModel_RelaunchDisplayNameResource),
                                  ("relaunch_icon", PKEY_AppUserModel_RelaunchIconResource)):
                    try:
                        value = _property_string(api, store.value, key)
                    except Exception:
                        value = None
                    if name == "aumid":
                        out[name] = _clean_id(value)
                    elif name == "relaunch_display_name":
                        text = _clean(value, limit=256)
                        out[name] = None if not text or text.startswith("@") else text
                    else:
                        out[name] = _clean(value, limit=1024)
            finally:
                _release(store.value)
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ bitmaps and icons
def _px(px, default=128):
    """A pixel size clamped to 1..MAX_PX; ``default`` for a non-number, a bool, NaN or
    an infinity. Never raises."""
    try:
        if isinstance(px, bool):
            return default
        value = float(px)
        if value != value or value in (float("inf"), float("-inf")):
            return default
        return max(1, min(MAX_PX, int(round(value))))
    except Exception:
        return default


def _fit(image, px):
    """A px x px RGBA copy: aspect kept, centred on transparency, LANCZOS."""
    from PIL import Image, ImageOps
    image = image.convert("RGBA")
    if image.size == (px, px):
        return image
    fitted = ImageOps.contain(image, (px, px), Image.Resampling.LANCZOS)
    if fitted.size == (px, px):
        return fitted
    tile = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    tile.paste(fitted, ((px - fitted.width) // 2, (px - fitted.height) // 2))
    return tile


def _bitmap_size(api, bitmap):
    info = BITMAP()
    if not api.GetObjectW(bitmap, C.sizeof(BITMAP), C.byref(info)):
        return None
    width, height = int(info.bmWidth), abs(int(info.bmHeight))
    if not (0 < width <= MAX_BITMAP_EDGE and 0 < height <= 2 * MAX_BITMAP_EDGE):
        return None
    return width, height


def _bitmap_bits(api, bitmap, width, height):
    """32bpp top-down BGRA rows of a bitmap (a copy), or None."""
    header = BITMAPINFO()
    header.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
    header.bmiHeader.biWidth, header.bmiHeader.biHeight = width, -height
    header.bmiHeader.biPlanes, header.bmiHeader.biBitCount = 1, 32
    header.bmiHeader.biCompression = BI_RGB
    buffer = (C.c_ubyte * (width * height * 4))()
    dc = api.CreateCompatibleDC(None)
    if not dc:
        return None
    try:
        lines = api.GetDIBits(dc, bitmap, 0, height, buffer, C.byref(header), DIB_RGB_COLORS)
    finally:
        api.DeleteDC(dc)
    return bytes(buffer) if lines == height else None


def _hbitmap_image(api, bitmap):
    """A straight-alpha 32bpp HBITMAP -> RGBA (the caller keeps ownership of the bitmap).

    IShellItemImageFactory::GetImage with SIIGBF_ICONONLY returns STRAIGHT alpha: measured
    on Windows 11 26200 at 32 and 128 px, the semi-transparent pixels of system package
    logos have colour channels above their alpha (impossible for premultiplied data), and
    un-premultiplying them again brightens every anti-aliased edge. So no un-premultiply."""
    from PIL import Image
    size = _bitmap_size(api, bitmap)
    if size is None or size[1] > MAX_BITMAP_EDGE:
        return None
    bits = _bitmap_bits(api, bitmap, *size)
    if bits is None:
        return None
    if not any(bits[3::4]):          # no alpha channel: an opaque bitmap, unless it is empty
        if not any(bits):
            return None
        return Image.frombytes("RGB", size, bits, "raw", "BGRX").convert("RGBA")
    return Image.frombytes("RGBA", size, bits, "raw", "BGRA")


_INVERT = bytes(255 - value for value in range(256))


def _icon_image(api, icon):
    """HICON -> RGBA (straight alpha), or None. Both GetIconInfo bitmaps are deleted."""
    from PIL import Image
    info = ICONINFO()
    if not icon or not api.GetIconInfo(icon, C.byref(info)):
        return None
    try:
        if not info.hbmColor:
            return None              # monochrome icons: not worth a master
        size = _bitmap_size(api, info.hbmColor)
        if size is None or size[1] > MAX_BITMAP_EDGE:
            return None
        bits = _bitmap_bits(api, info.hbmColor, *size)
        if bits is None:
            return None
        image = Image.frombytes("RGBA", size, bits, "raw", "BGRA")
        if not any(bits[3::4]):      # legacy icon: alpha from the AND mask
            mask_size = _bitmap_size(api, info.hbmMask) if info.hbmMask else None
            mask = _bitmap_bits(api, info.hbmMask, *mask_size) if mask_size and mask_size[0] == size[0] \
                and mask_size[1] >= size[1] else None
            if mask is not None:
                alpha = mask[0:size[0] * size[1] * 4:4].translate(_INVERT)
                image.putalpha(Image.frombytes("L", size, alpha))
            else:
                image.putalpha(255)
        return image
    finally:
        for bitmap in (info.hbmColor, info.hbmMask):
            if bitmap:
                api.DeleteObject(bitmap)


# ------------------------------------------------------------------ packaged apps
def _apps_folder_item(aumid):
    return "shell:AppsFolder\\" + aumid


def _shell_display_name(api, aumid):
    item = C.c_void_p()
    hr = api.SHCreateItemFromParsingName(_apps_folder_item(aumid), None, C.byref(IID_IShellItem), C.byref(item))
    if hr < 0 or not item.value:
        return None
    try:
        text = C.c_void_p()
        hr = _method(item.value, SLOT_SHELLITEM_GETDISPLAYNAME, _SHELLITEM_GETDISPLAYNAME)(
            item.value, SIGDN_NORMALDISPLAY, C.byref(text))
        if hr < 0 or not text.value:
            return None
        try:
            return C.wstring_at(text.value)
        finally:
            api.CoTaskMemFree(text.value)
    finally:
        _release(item.value)


def package_display_name(aumid, *, api=None, cached_only=False):
    """The packaged app's AppsFolder display name ("ChatGPT" for OpenAI.Codex), or None.

    Cached per AUMID for the process lifetime; a failure is cached for
    FAILURE_TTL_SECONDS, then looked up again. Pre-warm it on the IconWorker thread.
    ``cached_only=True`` answers from the cache without any COM call (None when
    unknown), for the Tk thread. Never raises."""
    try:
        aumid = _clean_id(aumid)
        if not aumid:
            return None
        cached = _cache_get_expiring(_PACKAGE_NAME_CACHE, aumid)
        if cached is not _MISSING:
            return cached
        if cached_only:
            return None
        api = api or _default_api()
        if api.SHCreateItemFromParsingName is None:
            return None
        try:
            with _com(api):
                name = _clean(_shell_display_name(api, aumid), limit=256)
        except Exception:
            name = None
        if name and (name == aumid or name.startswith("shell:") or "\\" in name):
            name = None                 # the shell echoed the parsing name back
        _cache_put_expiring(_PACKAGE_NAME_CACHE, aumid, name or None, PACKAGE_CACHE_SIZE)
        return name
    except Exception:
        return None


def _shell_logo(api, aumid, px):
    item = C.c_void_p()
    hr = api.SHCreateItemFromParsingName(_apps_folder_item(aumid), None, C.byref(IID_IShellItemImageFactory),
                                         C.byref(item))
    if hr < 0 or not item.value:
        return None
    try:
        bitmap = HANDLE()
        hr = _method(item.value, SLOT_IMAGEFACTORY_GETIMAGE, _IMAGEFACTORY_GETIMAGE)(
            item.value, SIZE(px, px), SIIGBF_ICONONLY | SIIGBF_BIGGERSIZEOK, C.byref(bitmap))
        if hr < 0 or not bitmap.value:
            return None
        try:
            return _hbitmap_image(api, bitmap.value)      # straight alpha (see _hbitmap_image)
        finally:
            api.DeleteObject(bitmap.value)
    finally:
        _release(item.value)


def package_logo(aumid, px=128, *, api=None):
    """The packaged app's logo (IShellItemImageFactory on shell:AppsFolder\\<AUMID>,
    icon only, straight alpha) as a px x px RGBA image, or None. Cached per (AUMID, px)
    for the process lifetime; a failure for FAILURE_TTL_SECONDS. Each call returns a
    fresh copy. Never raises."""
    try:
        aumid = _clean_id(aumid)
        if not aumid:
            return None
        px = _px(px)
        cached = _cache_get_expiring(_PACKAGE_LOGO_CACHE, (aumid, px))
        if cached is not _MISSING:
            return _copy(cached)
        api = api or _default_api()
        if api.SHCreateItemFromParsingName is None:
            return None
        try:
            with _com(api):
                image = _shell_logo(api, aumid, px)
            image = _fit(image, px) if image is not None and image.getchannel("A").getbbox() else None
        except Exception:
            image = None
        _cache_put_expiring(_PACKAGE_LOGO_CACHE, (aumid, px), image, ICON_CACHE_SIZE)
        return _copy(image)
    except Exception:
        return None


# ------------------------------------------------------------------ relaunch icons
def _parse_icon_resource(resource):
    """"<path>[,<index>]" (quotes and %VARIABLES% allowed) -> (path, index), or None.
    Indirect "@..." strings are not icon resources."""
    if not isinstance(resource, str):
        return None
    text = resource.strip()
    if not text or text.startswith("@"):
        return None
    index = 0
    match = re.fullmatch(r"(.*?)\s*,\s*(-?\d{1,9})", text)
    if match:
        text, index = match.group(1), int(match.group(2))
    text = text.strip().strip('"').strip()
    if "%" in text:
        text = os.path.expandvars(text)
    return (text, index) if text else None


def _ico_image(path, px):
    """The best frame of an .ico: the smallest at least px wide, else the largest."""
    from PIL import Image
    with Image.open(path) as image:
        if image.format != "ICO":
            return None
        sizes = sorted(image.ico.sizes(), key=lambda s: (s[0] * s[1], s))
        if not sizes:
            return None
        best = next((s for s in sizes if min(s) >= px), sizes[-1])
        return image.ico.getimage(best).convert("RGBA")


def _module_icon(api, path, index, px):
    """Icon ``index`` (negative: a resource id) of an exe/dll at ``px``, via
    SHDefExtractIconW. Both returned icons are destroyed."""
    if api.SHDefExtractIconW is None:
        return None
    large, small = HANDLE(), HANDLE()
    hr = api.SHDefExtractIconW(path, index, 0, C.byref(large), C.byref(small), (16 << 16) | px)
    try:
        if hr < 0 or not large.value:
            return None
        return _icon_image(api, large.value)
    finally:
        for icon in (large.value, small.value):
            if icon:
                api.DestroyIcon(icon)


def relaunch_icon(resource, px=128, *, api=None):
    """A window's RelaunchIconResource (Chrome's per-profile "Google Profile.ico") as a
    px x px RGBA image, or None. .ico files are read with PIL (best frame); other files
    by icon index. Network paths and files over 8 MB are refused. Cached per
    (path, index, px, mtime, size). The path is personal: never logged. Never raises."""
    try:
        parsed = _parse_icon_resource(resource)
        if parsed is None:
            return None
        path, index = parsed
        px = _px(px)
        api = api or _default_api()
        if not _readable_local_path(api, path):
            return None
        try:
            status = os.stat(path)
        except OSError:
            return None
        if not status.st_size or status.st_size > MAX_ICON_FILE_BYTES:
            return None
        key = (path.lower(), index, px, status.st_mtime_ns, status.st_size)
        cached = _cache_get(_RELAUNCH_ICON_CACHE, key)
        if cached is not _MISSING:
            return _copy(cached)
        try:
            if PureWindowsPath(path).suffix.lower() == ".ico":
                image = _ico_image(path, px)
            else:
                image = _module_icon(api, path, index, px)
            image = _fit(image, px) if image is not None and image.getchannel("A").getbbox() else None
        except Exception:
            image = None
        _cache_put(_RELAUNCH_ICON_CACHE, key, image, ICON_CACHE_SIZE)
        return _copy(image)
    except Exception:
        return None


# ------------------------------------------------------------------ monitors
POSITION_WORDS = {2: ("Left", "Right"), 3: ("Left", "Middle", "Right")}
VERTICAL_WORDS = {2: ("Top", "Bottom")}


def _name_monitors(entries):
    """{GDI device name (upper case): display name} from (gdi, friendly, technology,
    (x, y) or None) entries. Internal panels without an EDID name read
    "Built-in display"; other nameless monitors "Display". Monitors that share a
    name get a position word (Left/Middle/Right, else Top/Bottom, else 1, 2, ...)."""
    names, positions = {}, {}
    for gdi, friendly, technology, position in entries:
        key = str(gdi or "").upper()
        if not key or key in names:
            continue                                  # clone mode: the first target names it
        name = _clean(friendly, limit=64)
        if not name:
            name = "Built-in display" if technology in INTERNAL_OUTPUT_TECHNOLOGIES else "Display"
        names[key], positions[key] = name, position
    by_name = {}
    for key, name in names.items():
        by_name.setdefault(name, []).append(key)
    for name, keys in by_name.items():
        if len(keys) < 2:
            continue
        points = [positions.get(k) or (0, 0) for k in keys]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        if len(set(xs)) == len(keys) and len(keys) in POSITION_WORDS:
            words = POSITION_WORDS[len(keys)]
            order = sorted(range(len(keys)), key=lambda i: xs[i])
        elif len(set(ys)) == len(keys) and len(keys) in VERTICAL_WORDS:
            words = VERTICAL_WORDS[len(keys)]
            order = sorted(range(len(keys)), key=lambda i: ys[i])
        else:
            words = tuple(str(i + 1) for i in range(len(keys)))
            order = sorted(range(len(keys)), key=lambda i: (xs[i], ys[i]))
        for word, i in zip(words, order):
            names[keys[i]] = f"{name} ({word})"
    return names


def _display_entries(api):
    """(gdi, friendly, technology, position) per active display path, or None."""
    for _attempt in range(3):
        path_count, mode_count = UINT(), UINT()
        if api.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, C.byref(path_count), C.byref(mode_count)) != 0:
            return None
        if not path_count.value:
            return []
        paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * max(1, mode_count.value))()
        result = api.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, C.byref(path_count), paths,
                                        C.byref(mode_count), modes, None)
        if result == ERROR_INSUFFICIENT_BUFFER:
            continue                                  # the topology changed in between
        if result != 0:
            return None
        entries = []
        for path in paths[:path_count.value]:
            source = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
            source.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
            source.header.size = C.sizeof(source)
            source.header.adapterId, source.header.id = path.sourceInfo.adapterId, path.sourceInfo.id
            if api.DisplayConfigGetDeviceInfo(C.byref(source)) != 0:
                continue
            target = DISPLAYCONFIG_TARGET_DEVICE_NAME()
            target.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
            target.header.size = C.sizeof(target)
            target.header.adapterId, target.header.id = path.targetInfo.adapterId, path.targetInfo.id
            friendly, technology = "", path.targetInfo.outputTechnology
            if api.DisplayConfigGetDeviceInfo(C.byref(target)) == 0:
                friendly, technology = target.monitorFriendlyDeviceName, target.outputTechnology
            position, index = None, path.sourceInfo.modeInfoIdx
            if index < mode_count.value and modes[index].infoType == DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE:
                position = struct.unpack_from("<ii", bytes(modes[index].mode), 12)   # POINTL after w, h, format
            entries.append((source.viewGdiDeviceName, friendly, technology, position))
        return entries
    return None


def _display_names(api):
    now = time.monotonic()
    with _CACHE_LOCK:
        at = _DISPLAY_CACHE["at"]
        if at is not None and 0 <= now - at < DISPLAY_NAMES_TTL_SECONDS:
            return _DISPLAY_CACHE["names"]
    entries = _display_entries(api)
    names = _name_monitors(entries) if entries else {}
    with _CACHE_LOCK:
        _DISPLAY_CACHE["at"], _DISPLAY_CACHE["names"] = now, names
    return names


def monitor_friendly_name(hwnd, *, api=None):
    """The friendly name of the monitor nearest to the window (its EDID name, e.g. a
    model; "Built-in display"; a position word when two monitors share a model), or
    None. Shown on screen only, never logged. Display names are cached for 2 s.
    Never raises."""
    try:
        hwnd = int(hwnd or 0)
        if not hwnd:
            return None
        api = api or _default_api()
        if api.QueryDisplayConfig is None or api.DisplayConfigGetDeviceInfo is None:
            return None
        monitor = api.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFOEXW()
        info.cbSize = C.sizeof(MONITORINFOEXW)
        if not monitor or not api.GetMonitorInfoW(monitor, C.byref(info)):
            return None
        return _display_names(api).get(info.szDevice.upper())
    except Exception:
        return None


# ------------------------------------------------------------------ Core Audio
def _active_session_pids(api):
    """Process ids of every AudioSessionStateActive session on every active render and
    capture endpoint. Every interface is released on every path."""
    pids = set()
    enumerator = C.c_void_p()
    hr = api.CoCreateInstance(C.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                              C.byref(IID_IMMDeviceEnumerator), C.byref(enumerator))
    if hr < 0 or not enumerator.value:
        return pids
    try:
        devices = C.c_void_p()
        hr = _method(enumerator.value, SLOT_ENUMERATOR_ENUMAUDIOENDPOINTS, _ENUMAUDIOENDPOINTS)(
            enumerator.value, E_DATAFLOW_ALL, DEVICE_STATE_ACTIVE, C.byref(devices))
        if hr < 0 or not devices.value:
            return pids
        try:
            count = UINT()
            if _method(devices.value, SLOT_COLLECTION_GETCOUNT, _COLLECTION_GETCOUNT)(
                    devices.value, C.byref(count)) < 0:
                return pids
            for index in range(min(int(count.value), 64)):
                device = C.c_void_p()
                if _method(devices.value, SLOT_COLLECTION_ITEM, _COLLECTION_ITEM)(
                        devices.value, index, C.byref(device)) < 0 or not device.value:
                    continue
                try:
                    pids |= _device_session_pids(device.value)
                except Exception:
                    pass
                finally:
                    _release(device.value)
        finally:
            _release(devices.value)
    finally:
        _release(enumerator.value)
    return pids


def _device_session_pids(device):
    pids = set()
    manager = C.c_void_p()
    if _method(device, SLOT_DEVICE_ACTIVATE, _DEVICE_ACTIVATE)(
            device, C.byref(IID_IAudioSessionManager2), CLSCTX_ALL, None, C.byref(manager)) < 0 \
            or not manager.value:
        return pids
    try:
        sessions = C.c_void_p()
        if _method(manager.value, SLOT_MANAGER2_GETSESSIONENUMERATOR, _GETSESSIONENUMERATOR)(
                manager.value, C.byref(sessions)) < 0 or not sessions.value:
            return pids
        try:
            count = C.c_int()
            if _method(sessions.value, SLOT_SESSIONENUM_GETCOUNT, _SESSIONENUM_GETCOUNT)(
                    sessions.value, C.byref(count)) < 0:
                return pids
            for index in range(max(0, min(int(count.value), 512))):
                control = C.c_void_p()
                if _method(sessions.value, SLOT_SESSIONENUM_GETSESSION, _SESSIONENUM_GETSESSION)(
                        sessions.value, index, C.byref(control)) < 0 or not control.value:
                    continue
                try:
                    pid = _active_session_pid(control.value)
                    if pid:
                        pids.add(pid)
                except Exception:
                    pass
                finally:
                    _release(control.value)
        finally:
            _release(sessions.value)
    finally:
        _release(manager.value)
    return pids


def _active_session_pid(control):
    state = C.c_int(-1)
    if _method(control, SLOT_SESSIONCONTROL_GETSTATE, _SESSIONCONTROL_GETSTATE)(control, C.byref(state)) < 0 \
            or state.value != AUDIO_SESSION_STATE_ACTIVE:
        return 0
    control2 = _query_interface(control, IID_IAudioSessionControl2)
    if not control2:
        return 0
    try:
        pid = DWORD()
        # AUDCLNT_S_NO_SINGLE_PROCESS is a success code: the pid is still the creator's.
        if _method(control2, SLOT_SESSIONCONTROL2_GETPROCESSID, _SESSIONCONTROL2_GETPROCESSID)(
                control2, C.byref(pid)) < 0:
            return 0
        return int(pid.value)
    finally:
        _release(control2)


def _process_table(api):
    """{pid: (parent pid, exe name lower case)} from a Toolhelp snapshot."""
    table = {}
    snapshot = api.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return table
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = C.sizeof(PROCESSENTRY32W)
        ok = api.Process32FirstW(snapshot, C.byref(entry))
        while ok and len(table) < 65536:
            table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile.lower())
            ok = api.Process32NextW(snapshot, C.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    return table


MAX_PARENT_WALK = 8


def _with_same_exe_ancestors(pids, table):
    """``pids`` plus each one's ancestors while the parent runs the same exe (a
    browser's audio-service child -> the browser process that owns the window). A
    parent with another exe name stops the walk, which also guards against reused
    parent pids."""
    out = set()
    for pid in pids:
        if not pid:
            continue
        out.add(pid)
        entry = table.get(pid)
        if entry is None:
            continue
        exe, current, seen = entry[1], pid, {pid}
        for _step in range(MAX_PARENT_WALK):
            parent = table.get(current, (0, ""))[0]
            if not parent or parent in seen or parent not in table or table[parent][1] != exe:
                break
            out.add(parent)
            seen.add(parent)
            current = parent
    return out


def audible_pids(*, api=None) -> set:
    """Process ids with an active audio session (render or capture, every active
    endpoint: virtual devices make the default endpoint alone wrong), plus their
    same-exe ancestors. A process-level proxy for "this browser is in a call".

    Call it lazily and off the Tk thread (about 15-25 ms), only when a Meet window
    is in the snapshot (window_labels.meet_window). Never raises."""
    try:
        api = api or _default_api()
        if api.CoCreateInstance is None:
            return set()
        with _com(api):
            pids = _active_session_pids(api)
        if not pids:
            return set()
        return _with_same_exe_ancestors(pids, _process_table(api))
    except Exception:
        return set()


# ------------------------------------------------------------------ letter tiles
BRAND_TILE_COLOURS = {          # display name (lower case) -> 0xRRGGBB, before the contrast rule
    "bambu studio": 0x00AE42,
    "file explorer": 0xE8B64A,
    "steam": 0x1B2838,
    "slack": 0x4A154B,
    "discord": 0x5865F2,
    "spotify": 0x1DB954,
    "google chrome": 0x1A73E8,
    "microsoft edge": 0x0C59A4,
    "firefox": 0xE66000,
    "visual studio code": 0x0065A9,
    "claude": 0xC15F3C,
    "chatgpt": 0x10A37F,
    "whatsapp": 0x25D366,
    "telegram": 0x229ED9,
}
TILE_PALETTE = (                # mid-dark, indexed by zlib.crc32(name.lower())
    0x3C6ED8, 0x7B4FD6, 0xC2410C, 0x0F766E, 0xB42318, 0x4D7C0F,
    0x9D174D, 0x0369A1, 0x6D28D9, 0xA16207, 0x15803D, 0x475569,
)
MIN_TILE_CONTRAST = 3.0
TILE_LETTER_RATIO = 17 / 32     # the letter's font size relative to the tile
TILE_LETTER_WEIGHT = 700
ARCHIVO_ASCENT, ARCHIVO_DESCENT = 0.878, 0.210   # OS/2 typo metrics (USE_TYPO_METRICS) == hhea
FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
ARCHIVO = FONT_DIR / "Archivo.ttf"
SYSTEM_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
# Bold faces for letters Archivo lacks: Latin/Greek/Cyrillic, CJK, Hangul, Japanese, symbols.
TILE_FALLBACK_FONTS = ("segoeuib.ttf", "msyhbd.ttc", "malgunbd.ttf", "YuGothB.ttc", "seguisym.ttf")


def _name_key(name) -> str:
    text = unicodedata.normalize("NFC", name) if isinstance(name, str) else ""
    return " ".join(re.sub(r"[\u00ae\u2122\u00a9]", "", text).split()).lower()


def _linear(channel):
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def white_contrast(rgb) -> float:
    """WCAG contrast ratio of white text on ``rgb``."""
    r, g, b = rgb
    luminance = 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)
    return 1.05 / (luminance + 0.05)


def _rgb(value):
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def tile_colour(name) -> tuple:
    """(r, g, b) of a letter tile: the brand table, else the crc32-indexed palette
    (deterministic across runs, unlike hash()), darkened until white text reaches at
    least 3:1."""
    key = _name_key(name)
    base = BRAND_TILE_COLOURS.get(key)
    if base is None:
        base = TILE_PALETTE[zlib.crc32(key.encode("utf-8")) % len(TILE_PALETTE)]
    rgb = _rgb(base)
    while white_contrast(rgb) < MIN_TILE_CONTRAST:
        rgb = tuple(int(c * 0.92) for c in rgb)
    return rgb


def tile_letter(name) -> str:
    """The first letter or digit of the display name, upper-cased ("" when none)."""
    text = unicodedata.normalize("NFC", str(name or "")) if isinstance(name, str) else ""
    for ch in text:
        if ch.isalnum():
            return ch.upper()[:1]
    for ch in text:
        if not ch.isspace() and unicodedata.category(ch)[0] in "LNS":
            return ch.upper()[:1]
    return ""


class _Cmap:
    """Codepoint coverage from a font's cmap (formats 12 and 4), read once."""

    def __init__(self, path):
        self.groups = None          # format 12: (starts, ends, start glyphs)
        self.format4 = None         # (data, segment count)
        with open(path, "rb") as handle:
            header = handle.read(12)
            base = 0
            if header[:4] == b"ttcf":
                handle.seek(12)
                base = struct.unpack(">I", handle.read(4))[0]
                handle.seek(base)
                header = handle.read(12)
            tables = struct.unpack(">H", header[4:6])[0]
            directory = handle.read(16 * tables)
            for i in range(tables):
                tag, _checksum, offset, length = struct.unpack_from(">4sIII", directory, 16 * i)
                if tag == b"cmap":
                    handle.seek(offset)
                    self._parse(handle.read(min(length, 16 * 1024 * 1024)))
                    break

    def _parse(self, data):
        count = struct.unpack_from(">H", data, 2)[0]
        best = None
        for i in range(count):
            platform, encoding, offset = struct.unpack_from(">HHI", data, 4 + 8 * i)
            fmt = struct.unpack_from(">H", data, offset)[0]
            rank = 0 if fmt == 12 and (platform, encoding) in ((3, 10), (0, 4), (0, 6)) else \
                1 if fmt == 4 and (platform == 0 or (platform, encoding) in ((3, 1), (3, 0))) else None
            if rank is not None and (best is None or rank < best[0]):
                best = (rank, fmt, offset)
        if best is None:
            return
        _rank, fmt, offset = best
        if fmt == 12:
            groups = struct.unpack_from(">I", data, offset + 12)[0]
            starts, ends, glyphs = [], [], []
            for i in range(groups):
                start, end, glyph = struct.unpack_from(">III", data, offset + 16 + 12 * i)
                starts.append(start)
                ends.append(end)
                glyphs.append(glyph)
            self.groups = (starts, ends, glyphs)
        else:
            length = struct.unpack_from(">H", data, offset + 2)[0]
            self.format4 = (data[offset:offset + length], struct.unpack_from(">H", data, offset + 6)[0] // 2)

    def covers(self, codepoint):
        import bisect
        if self.groups is not None:
            starts, ends, glyphs = self.groups
            i = bisect.bisect_right(starts, codepoint) - 1
            return i >= 0 and codepoint <= ends[i] and glyphs[i] + (codepoint - starts[i]) != 0
        if self.format4 is None or codepoint > 0xFFFF:
            return False
        data, segments = self.format4
        ends_at, starts_at = 14, 16 + 2 * segments
        deltas_at, ranges_at = starts_at + 2 * segments, starts_at + 4 * segments
        lo, hi = 0, segments
        while lo < hi:                               # first segment whose end >= codepoint
            mid = (lo + hi) // 2
            if struct.unpack_from(">H", data, ends_at + 2 * mid)[0] < codepoint:
                lo = mid + 1
            else:
                hi = mid
        if lo >= segments:
            return False
        start = struct.unpack_from(">H", data, starts_at + 2 * lo)[0]
        if codepoint < start:
            return False
        delta = struct.unpack_from(">h", data, deltas_at + 2 * lo)[0]
        range_offset = struct.unpack_from(">H", data, ranges_at + 2 * lo)[0]
        if range_offset == 0:
            return (codepoint + delta) & 0xFFFF != 0
        at = ranges_at + 2 * lo + range_offset + 2 * (codepoint - start)
        if at + 2 > len(data):
            return False
        glyph = struct.unpack_from(">H", data, at)[0]
        return glyph != 0 and (glyph + delta) & 0xFFFF != 0


_CMAPS = {}
_CMAPS_LOCK = threading.Lock()


def font_covers(path, codepoint) -> bool:
    """Whether the font file (TTF/OTF, or the first face of a TTC) maps ``codepoint``
    (an int or a one-character string) to a real glyph. The cmap is parsed once per
    path. Never raises."""
    try:
        codepoint = ord(codepoint) if isinstance(codepoint, str) else int(codepoint)
        key = str(path)
        with _CMAPS_LOCK:
            cmap = _CMAPS.get(key, _MISSING)
        if cmap is _MISSING:
            try:
                cmap = _Cmap(key)
            except Exception:
                cmap = None
            with _CMAPS_LOCK:
                _CMAPS[key] = cmap
        return bool(cmap is not None and cmap.covers(codepoint))
    except Exception:
        return False


_FONTS = threading.local()      # one face per (path, size) per thread: variations mutate faces


def _font(path, size, variable):
    from PIL import ImageFont
    cache = getattr(_FONTS, "faces", None)
    if cache is None:
        cache = _FONTS.faces = {}
    key = (str(path), round(size, 3))
    font = cache.get(key)
    if font is None:
        font = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
        if variable:
            font.set_variation_by_axes([TILE_LETTER_WEIGHT, 100])     # wght, wdth
        if len(cache) > 32:
            cache.clear()
        cache[key] = font
    return font


def _letter_font(letter, size):
    """The face for the tile letter: Archivo 700 when it has the glyph, else the first
    bold system face whose cmap covers it, else None."""
    codepoint = ord(letter)
    if ARCHIVO.is_file() and font_covers(ARCHIVO, codepoint):
        return _font(ARCHIVO, size, True)
    for name in TILE_FALLBACK_FONTS:
        path = SYSTEM_FONT_DIR / name
        if path.is_file() and font_covers(path, codepoint):
            return _font(path, size, False)
    return None


def _render_tile(name, px, radius):
    from PIL import Image, ImageDraw
    rgb = tile_colour(name)
    tile = Image.new("RGBA", (px, px), rgb + (255,))
    letter = tile_letter(name)
    if letter:
        try:
            size = px * TILE_LETTER_RATIO
            font = _letter_font(letter, size)
            if font is not None:
                x = (px - font.getlength(letter)) / 2          # centred on the advance, as CSS does
                # The flex-centred line box is Archivo's (1.088 em) even when the glyph
                # comes from a fallback face: CSS keeps the first font's baseline.
                baseline = (px - (ARCHIVO_ASCENT + ARCHIVO_DESCENT) * size) / 2 + ARCHIVO_ASCENT * size
                ImageDraw.Draw(tile).text((x, baseline), letter, font=font, fill=(255, 255, 255, 255),
                                          anchor="ls")
        except Exception:
            pass                                               # a plain tile beats no tile
    if radius > 0:
        scale = 4
        mask = Image.new("L", (px * scale, px * scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, px * scale - 1, px * scale - 1),
                                               radius=radius * scale, fill=255)
        tile.putalpha(mask.resize((px, px), Image.Resampling.LANCZOS))
    return tile


def letter_tile(name, px, radius=0):
    """The missing-icon tile (section 7): the display name's first letter, upper-cased,
    white, in Archivo wght 700 at 17/32 of the tile, centred, on the tile colour
    (tile_colour: brand table, else crc32 palette, contrast >= 3:1). Square corners
    unless ``radius`` > 0. A px x px RGBA image, cached per (name, px, radius); each
    call returns a fresh copy. Never raises."""
    from PIL import Image
    px = _px(px, 32) if isinstance(px, (int, float)) else 32     # NaN / inf / bool -> 32 too
    try:
        radius = max(0.0, min(float(radius or 0), px / 2))
    except Exception:
        radius = 0.0
    key = (str(name) if isinstance(name, str) else "", px, radius)
    try:
        cached = _cache_get(_TILE_CACHE, key)
        if cached is not _MISSING:
            return cached.copy()
        tile = _render_tile(key[0], px, radius)
        _cache_put(_TILE_CACHE, key, tile, TILE_CACHE_SIZE)
        return tile.copy()
    except Exception:
        return Image.new("RGBA", (px, px), _rgb(TILE_PALETTE[-1]) + (255,))
