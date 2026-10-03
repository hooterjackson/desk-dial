"""COM plumbing for the stage (DESKTOP_STAGE §4.2-§4.7): structs, GUIDs, vtable slots, call styles.

Pure ctypes: importing this module loads no DLL, so the slot table, the structs and the error
classification are importable (and testable) anywhere. ``win32.py`` loads the DLLs.

Call styles (§4.7.1 as amended by [G1] G1-1 and G1-5):
  PY = ``ctypes.PYFUNCTYPE``, keeps the GIL: pure, non-blocking setters (offsets, opacity,
       modes, content, transforms, children, animation programs), and the statistics reads
       (``IDCompositionDevice::GetFrameStatistics`` on the input path, G1-1 / G1-5: the input
       path keeps the GIL through everything before ``Commit``).
  WF = ``ctypes.WINFUNCTYPE``, releases the GIL: anything that may wait on DWM, the GPU, a TDR,
       the lock screen or another thread (Commit, creation, draws, uploads, device state).
On x64 there is one calling convention, so a COM method can be called through a PYFUNCTYPE
prototype (RF2 §2.3).

Slots come from the Windows SDK headers. MSVC places the later-declared overload of an
overloaded virtual first (RF2 §2.3): dcomp.h declares the value overload first and the object
overload second, so ``SetOffsetX(animation)`` is 3 and ``SetOffsetX(float)`` is 4. The G1 spike
proved 3/4, 5/6, 7/8 (``SetTransform(object)`` / ``(matrix)``), 11 and 12 (interpolation and
border, on screen pixels), 15-18, 20, 29/30 and the animation slots; ``UpdateSubresource`` (48)
and ``CopySubresourceRegion`` (46) are proven by the upload readback (``selftest.py``);
``SetClip(object)`` (13) is proven by the NULL discriminator (it accepts NULL; the rect overload
would fault) before ``SetClip(rect)`` (14) is ever called.
"""
from __future__ import annotations

import ctypes as C
import uuid

VP = C.c_void_p
HRESULT = C.c_long
PY, WF = "PY", "WF"

# --------------------------------------------------------------------------- errors
S_OK = 0
DXGI_ERROR_DEVICE_REMOVED = C.c_long(0x887A0005).value
DXGI_ERROR_DEVICE_HUNG = C.c_long(0x887A0006).value
DXGI_ERROR_DEVICE_RESET = C.c_long(0x887A0007).value
D2DERR_RECREATE_TARGET = C.c_long(0x8899000C).value
DEVICE_LOST_HR = frozenset({DXGI_ERROR_DEVICE_REMOVED, DXGI_ERROR_DEVICE_RESET, DXGI_ERROR_DEVICE_HUNG,
                            D2DERR_RECREATE_TARGET})
STATUS_GRAPHICS_PRESENT_OCCLUDED = 0xC01E0006     # DCompositionWaitForCompositorClock while the display sleeps (G1-2)


def hx(hr) -> str:
    return "0x%08X" % ((hr or 0) & 0xFFFFFFFF)


class ComError(OSError):
    def __init__(self, where: str, hr: int):
        super().__init__(f"{where} failed {hx(hr)}")
        self.where = where
        self.hr = hr


class DeviceLost(ComError):
    """DXGI_ERROR_DEVICE_REMOVED / _RESET / _HUNG, or CheckDeviceState reporting invalid (§4.3)."""


def check(hr, where: str) -> int:
    if hr is None:
        return 0
    if hr < 0:
        if hr in DEVICE_LOST_HR:
            raise DeviceLost(where, hr)
        raise ComError(where, hr)
    return hr


def is_device_lost(hr) -> bool:
    return hr is not None and hr in DEVICE_LOST_HR


# --------------------------------------------------------------------------- GUIDs
class GUID(C.Structure):
    _fields_ = [("Data1", C.c_uint32), ("Data2", C.c_uint16), ("Data3", C.c_uint16), ("Data4", C.c_ubyte * 8)]


def guid(s: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


IID_IDCompositionDesktopDevice = guid("5F4633FE-1E08-4CB8-8C75-CE24333F5602")
IID_IDCompositionDevice = guid("C37EA93A-E7AA-450D-B16F-9746CB0407F3")
IID_IDCompositionVisual3 = guid("2775F462-B6C1-4015-B0BE-B3E7D6A4976D")
IID_IDXGIDevice = guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_IDXGIFactory1 = guid("770aae78-f26f-4dba-a829-253c83d1b387")
IID_ID3D11Texture2D = guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")
GUID_CONSOLE_DISPLAY_STATE = guid("6FE69556-704A-47A0-8F24-C28D936FDA47")


# --------------------------------------------------------------------------- structs
class POINT(C.Structure):
    _fields_ = [("x", C.c_long), ("y", C.c_long)]


class RECT(C.Structure):
    _fields_ = [("left", C.c_long), ("top", C.c_long), ("right", C.c_long), ("bottom", C.c_long)]


class LUID(C.Structure):
    _fields_ = [("LowPart", C.c_uint32), ("HighPart", C.c_long)]

    def key(self) -> int:
        return (self.HighPart << 32) | self.LowPart


class D2D_MATRIX_3X2_F(C.Structure):
    _fields_ = [("_11", C.c_float), ("_12", C.c_float), ("_21", C.c_float), ("_22", C.c_float),
                ("_31", C.c_float), ("_32", C.c_float)]


class D2D_RECT_F(C.Structure):
    _fields_ = [("left", C.c_float), ("top", C.c_float), ("right", C.c_float), ("bottom", C.c_float)]


class D3D11_BOX(C.Structure):
    _fields_ = [("left", C.c_uint), ("top", C.c_uint), ("front", C.c_uint), ("right", C.c_uint),
                ("bottom", C.c_uint), ("back", C.c_uint)]


class DXGI_SAMPLE_DESC(C.Structure):
    _fields_ = [("Count", C.c_uint), ("Quality", C.c_uint)]


class D3D11_TEXTURE2D_DESC(C.Structure):
    _fields_ = [("Width", C.c_uint), ("Height", C.c_uint), ("MipLevels", C.c_uint), ("ArraySize", C.c_uint),
                ("Format", C.c_uint), ("SampleDesc", DXGI_SAMPLE_DESC), ("Usage", C.c_uint),
                ("BindFlags", C.c_uint), ("CPUAccessFlags", C.c_uint), ("MiscFlags", C.c_uint)]


class D3D11_MAPPED_SUBRESOURCE(C.Structure):
    _fields_ = [("pData", C.c_void_p), ("RowPitch", C.c_uint), ("DepthPitch", C.c_uint)]


class DXGI_ADAPTER_DESC1(C.Structure):
    _fields_ = [("Description", C.c_wchar * 128), ("VendorId", C.c_uint), ("DeviceId", C.c_uint),
                ("SubSysId", C.c_uint), ("Revision", C.c_uint), ("DedicatedVideoMemory", C.c_size_t),
                ("DedicatedSystemMemory", C.c_size_t), ("SharedSystemMemory", C.c_size_t),
                ("AdapterLuid", LUID), ("Flags", C.c_uint)]


class DXGI_OUTPUT_DESC(C.Structure):
    _fields_ = [("DeviceName", C.c_wchar * 32), ("DesktopCoordinates", RECT), ("AttachedToDesktop", C.c_int),
                ("Rotation", C.c_uint), ("Monitor", C.c_void_p)]


class DCOMPOSITION_FRAME_STATISTICS(C.Structure):
    _fields_ = [("lastFrameTime", C.c_int64), ("rateNum", C.c_uint), ("rateDen", C.c_uint),
                ("currentTime", C.c_int64), ("timeFrequency", C.c_int64), ("nextEstimatedFrameTime", C.c_int64)]


class COMPOSITION_FRAME_STATS(C.Structure):
    _fields_ = [("startTime", C.c_uint64), ("targetTime", C.c_uint64), ("framePeriod", C.c_uint64)]


class COMPOSITION_TARGET_ID(C.Structure):
    _fields_ = [("displayAdapterLuid", LUID), ("renderAdapterLuid", LUID), ("vidPnSourceId", C.c_uint),
                ("vidPnTargetId", C.c_uint), ("uniqueId", C.c_uint)]

    def key(self):
        return (self.displayAdapterLuid.key(), self.vidPnSourceId)


class COMPOSITION_STATS(C.Structure):
    _fields_ = [("presentCount", C.c_uint), ("refreshCount", C.c_uint), ("virtualRefreshCount", C.c_uint),
                ("time", C.c_uint64)]


class COMPOSITION_TARGET_STATS(C.Structure):
    _fields_ = [("outstandingPresents", C.c_uint), ("presentTime", C.c_uint64), ("vblankDuration", C.c_uint64),
                ("presentedStats", COMPOSITION_STATS), ("completedStats", COMPOSITION_STATS)]


STRUCT_SIZES_X64 = {POINT: 8, RECT: 16, LUID: 8, D2D_MATRIX_3X2_F: 24, D2D_RECT_F: 16, D3D11_BOX: 24,
                    D3D11_TEXTURE2D_DESC: 44, DCOMPOSITION_FRAME_STATISTICS: 40, COMPOSITION_FRAME_STATS: 24,
                    COMPOSITION_TARGET_ID: 28, COMPOSITION_STATS: 24, COMPOSITION_TARGET_STATS: 72}

# --------------------------------------------------------------------------- constants
DXGI_FORMAT_B8G8R8A8_UNORM = 87
DXGI_ALPHA_MODE_PREMULTIPLIED, DXGI_ALPHA_MODE_IGNORE = 1, 3
DCOMPOSITION_BITMAP_INTERPOLATION_MODE_NEAREST_NEIGHBOR = 0     # forbidden (AR-8, H6)
DCOMPOSITION_BITMAP_INTERPOLATION_MODE_LINEAR = 1
DCOMPOSITION_BITMAP_INTERPOLATION_MODE_INHERIT = 0xFFFFFFFF
DCOMPOSITION_BORDER_MODE_SOFT = 0
DCOMPOSITION_BORDER_MODE_HARD = 1                               # forbidden (AR-8, H6)
DCOMPOSITION_BORDER_MODE_INHERIT = 0xFFFFFFFF
DCOMPOSITION_OPACITY_MODE_LAYER = 0
DCOMPOSITION_OPACITY_MODE_MULTIPLY = 1
DCOMPOSITION_OPACITY_MODE_INHERIT = 0xFFFFFFFF
COMPOSITION_FRAME_ID_CREATED, COMPOSITION_FRAME_ID_CONFIRMED, COMPOSITION_FRAME_ID_COMPLETED = 0, 1, 2
D3D_DRIVER_TYPE_UNKNOWN, D3D_DRIVER_TYPE_HARDWARE, D3D_DRIVER_TYPE_WARP = 0, 1, 5
D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20
D3D11_SDK_VERSION = 7
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1
FEATURE_LEVELS = (0xB100, 0xB000, 0xA100, 0xA000)               # 11_1, 11_0, 10_1, 10_0 (§4.2)

# --------------------------------------------------------------------------- vtable slots
P_ = C.POINTER
H = HRESULT

# name -> (slot, style, restype, argtypes after `this`)
SLOTS = {
    # IUnknown
    "Unknown.QueryInterface": (0, WF, H, (P_(GUID), P_(VP))),
    "Unknown.AddRef": (1, PY, C.c_ulong, ()),
    "Unknown.Release": (2, WF, C.c_ulong, ()),
    # IDCompositionDesktopDevice (IDCompositionDevice2 base)
    "Device.Commit": (3, WF, H, ()),
    "Device.WaitForCommitCompletion": (4, WF, H, ()),
    "Device.GetFrameStatistics": (5, PY, H, (P_(DCOMPOSITION_FRAME_STATISTICS),)),       # G1-1 / G1-5
    "Device.CreateVisual": (6, WF, H, (P_(VP),)),
    "Device.CreateSurface": (8, WF, H, (C.c_uint, C.c_uint, C.c_int, C.c_int, P_(VP))),
    "Device.CreateScaleTransform": (11, WF, H, (P_(VP),)),
    "Device.CreateTransformGroup": (15, WF, H, (P_(VP), C.c_uint, P_(VP))),
    "Device.CreateEffectGroup": (21, WF, H, (P_(VP),)),
    "Device.CreateRectangleClip": (22, WF, H, (P_(VP),)),
    "Device.CreateAnimation": (23, WF, H, (P_(VP),)),
    "Device.CreateTargetForHwnd": (24, WF, H, (VP, C.c_int, P_(VP))),
    # IDCompositionDevice (v1): CheckDeviceState
    "Device1.CheckDeviceState": (26, WF, H, (P_(C.c_int),)),
    # IDCompositionTarget
    "Target.SetRoot": (3, WF, H, (VP,)),
    # IDCompositionVisual / Visual2 / Visual3
    "Visual.SetOffsetX.anim": (3, PY, H, (VP,)),
    "Visual.SetOffsetX": (4, PY, H, (C.c_float,)),
    "Visual.SetOffsetY.anim": (5, PY, H, (VP,)),
    "Visual.SetOffsetY": (6, PY, H, (C.c_float,)),
    "Visual.SetTransform.object": (7, PY, H, (VP,)),
    "Visual.SetTransform.matrix": (8, PY, H, (P_(D2D_MATRIX_3X2_F),)),
    "Visual.SetEffect": (10, PY, H, (VP,)),
    "Visual.SetBitmapInterpolationMode": (11, PY, H, (C.c_uint,)),
    "Visual.SetBorderMode": (12, PY, H, (C.c_uint,)),
    "Visual.SetClip.object": (13, PY, H, (VP,)),
    "Visual.SetClip.rect": (14, PY, H, (P_(D2D_RECT_F),)),
    "Visual.SetContent": (15, PY, H, (VP,)),
    "Visual.AddVisual": (16, PY, H, (VP, C.c_int, VP)),
    "Visual.RemoveVisual": (17, PY, H, (VP,)),
    "Visual.RemoveAllVisuals": (18, PY, H, ()),
    "Visual2.SetOpacityMode": (20, PY, H, (C.c_uint,)),
    "Visual3.SetOpacity.anim": (29, PY, H, (VP,)),
    "Visual3.SetOpacity": (30, PY, H, (C.c_float,)),
    # IDCompositionScaleTransform
    "Scale.SetScaleX.anim": (3, PY, H, (VP,)),
    "Scale.SetScaleX": (4, PY, H, (C.c_float,)),
    "Scale.SetScaleY.anim": (5, PY, H, (VP,)),
    "Scale.SetScaleY": (6, PY, H, (C.c_float,)),
    "Scale.SetCenterX": (8, PY, H, (C.c_float,)),
    "Scale.SetCenterY": (10, PY, H, (C.c_float,)),
    # IDCompositionEffectGroup (the G1 spike's proven opacity path, the G1-10 fallback)
    "EffectGroup.SetOpacity.anim": (3, PY, H, (VP,)),
    "EffectGroup.SetOpacity": (4, PY, H, (C.c_float,)),
    # IDCompositionAnimation
    "Animation.Reset": (3, PY, H, ()),
    "Animation.SetAbsoluteBeginTime": (4, PY, H, (C.c_int64,)),
    "Animation.AddCubic": (5, PY, H, (C.c_double, C.c_float, C.c_float, C.c_float, C.c_float)),
    "Animation.End": (8, PY, H, (C.c_double, C.c_float)),
    # IDCompositionSurface
    "Surface.BeginDraw": (3, WF, H, (VP, P_(GUID), P_(VP), P_(POINT))),
    "Surface.EndDraw": (4, WF, H, ()),
    # ID3D11Device / DeviceContext / Texture2D
    "D3D11.CreateTexture2D": (5, WF, H, (P_(D3D11_TEXTURE2D_DESC), VP, P_(VP))),
    "D3D11.GetDeviceRemovedReason": (39, WF, H, ()),
    "Context.Map": (14, WF, H, (VP, C.c_uint, C.c_uint, C.c_uint, P_(D3D11_MAPPED_SUBRESOURCE))),
    "Context.Unmap": (15, WF, None, (VP, C.c_uint)),
    "Context.CopySubresourceRegion": (46, WF, None, (VP, C.c_uint, C.c_uint, C.c_uint, C.c_uint, VP, C.c_uint,
                                                     P_(D3D11_BOX))),
    "Context.UpdateSubresource": (48, WF, None, (VP, C.c_uint, P_(D3D11_BOX), VP, C.c_uint, C.c_uint)),
    "Texture2D.GetDesc": (10, WF, None, (P_(D3D11_TEXTURE2D_DESC),)),
    # DXGI
    "Factory1.EnumAdapters1": (12, WF, H, (C.c_uint, P_(VP))),
    "Adapter.EnumOutputs": (7, WF, H, (C.c_uint, P_(VP))),
    "Adapter1.GetDesc1": (10, WF, H, (P_(DXGI_ADAPTER_DESC1),)),
    "Output.GetDesc": (7, WF, H, (P_(DXGI_OUTPUT_DESC),)),
}

# The setters a detent's build may call (PY) and the only calls that may take the GIL away
# (WF). The static and unit tests read these sets.
HOT_PATH_SLOTS = frozenset(k for k, v in SLOTS.items() if v[1] == PY)
FORBIDDEN_INTERPOLATION = DCOMPOSITION_BITMAP_INTERPOLATION_MODE_NEAREST_NEIGHBOR
FORBIDDEN_BORDER = DCOMPOSITION_BORDER_MODE_HARD

_PROTOS: dict = {}
_FNS: dict = {}


def _proto(style, restype, argtypes):
    key = (style, restype, argtypes)
    p = _PROTOS.get(key)
    if p is None:
        factory = C.PYFUNCTYPE if style == PY else C.WINFUNCTYPE
        p = _PROTOS[key] = factory(restype, C.c_void_p, *argtypes)
    return p


def vfn(obj: int, name: str):
    """The raw function for slot ``name`` of COM object ``obj``; call it as ``f(obj, *args)``.
    Cached by (vtable address, name): vtables are static code in the DLL."""
    if not obj:
        raise ValueError(f"{name}: null COM pointer")
    vtbl = C.c_void_p.from_address(obj).value
    key = (vtbl, name)
    f = _FNS.get(key)
    if f is None:
        slot, style, restype, argtypes = SLOTS[name]
        addr = C.c_void_p.from_address(vtbl + 8 * slot).value
        f = _FNS[key] = _proto(style, restype, argtypes)(addr)
    return f


def call(obj: int, name: str, *args):
    """Call a slot and raise on a failed HRESULT (DeviceLost for the device-lost codes)."""
    hr = vfn(obj, name)(obj, *args)
    if SLOTS[name][2] is H:
        check(hr, name)
    return hr


def qi(obj: int, iid: GUID):
    out = C.c_void_p()
    hr = vfn(obj, "Unknown.QueryInterface")(obj, C.byref(iid), C.byref(out))
    return hr, out.value


def release(obj) -> int:
    return vfn(obj, "Unknown.Release")(obj) if obj else 0

