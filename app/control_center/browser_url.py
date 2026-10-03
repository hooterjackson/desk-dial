"""The host shown in a Chromium browser's address bar, through Windows UI Automation (A0 Auto).

Onshape's tab titles carry the document and tab names only ("Bracket | Part Studio 1"), never
"Onshape", so Auto asks the browser window's address bar instead: the first Edit descendant of the
top-level window (Chrome: "Address and search bar"; Edge: the same Chromium omnibox) and its UIA
Value. DD-SEC-002: that Edit must be the toolbar omnibox (class ``OmniboxViewViews``, or at least not inside a
web Document): a window without an address bar (an app / popup window) would otherwise hand over a text field
of the page itself, whose value the page controls. Only the host is returned and compared; the address itself
is never logged or kept.

Plain ctypes COM (no comtypes): IUIAutomation from CUIAutomation, ElementFromHandle,
CreatePropertyCondition(ControlType == Edit), FindFirst(TreeScope_Descendants),
GetCurrentPropertyValue(Value). Each calling thread gets its own apartment-initialised instance, held in
a thread-local ``_Automation``: when the thread ends (the Onshape injector is replaced on every
simulator / live toggle), the instance is Released and COM uninitialised again on that thread
(only when this module's CoInitializeEx succeeded there). Every public call is best-effort: any
failure answers ``None``.
"""
from __future__ import annotations

import ctypes
import re
import threading
from ctypes import wintypes as W

__all__ = ["address_host", "focus_in_page", "host_of", "set_timeouts"]

CLSID_CUIAutomation = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"
CLSID_CUIAutomation8 = "{E22AD333-B25F-460C-83D0-0581107395C9}"   # Windows 8+: also IUIAutomation2
IID_IUIAutomation = "{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}"
IID_IUIAutomation2 = "{34723AFF-0C9D-49D0-9896-7AB52DF8CD8A}"   # Windows 8+: connection / transaction timeouts
UIA_ControlTypePropertyId = 30003
UIA_ValueValuePropertyId = 30045
UIA_ClassNamePropertyId = 30012
OMNIBOX_CLASSES = ("OmniboxViewViews",)   # Chromium's address bar (Chrome and Edge)
UIA_EditControlTypeId = 50004
UIA_DocumentControlTypeId = 50030
MAX_TREE_DEPTH = 64          # ancestors followed from an element to the desktop root (a deep page DOM)
TreeScope_Descendants = 4
VT_I4, VT_BSTR = 3, 8
CLSCTX_INPROC_SERVER = 1
COINIT_MULTITHREADED = 0

# vtable slots (IUnknown 0-2)
_QUERY_INTERFACE = 0
_RELEASE = 2
_UIA2_PUT_CONNECTION_TIMEOUT = 61
_UIA2_PUT_TRANSACTION_TIMEOUT = 63
_UIA_COMPARE_ELEMENTS = 3
_UIA_ELEMENT_FROM_HANDLE = 6
_UIA_ELEMENT_FROM_POINT = 7
_UIA_GET_FOCUSED_ELEMENT = 8
_UIA_CONTROL_VIEW_WALKER = 14
_WALKER_GET_PARENT = 3
_UIA_CREATE_PROPERTY_CONDITION = 23
_ELEMENT_FIND_FIRST = 5
_ELEMENT_GET_CURRENT_PROPERTY_VALUE = 10

_HOST = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?([^/?#:\s]+)", re.IGNORECASE)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class VARIANT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("lVal", ctypes.c_long), ("bstrVal", ctypes.c_void_p), ("pad", ctypes.c_byte * 16)]
    _anonymous_ = ("u",)
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("u", _U)]


def host_of(address):
    """The lower-case host of an address-bar string ("cad.onshape.com/documents/..."), or ""."""
    match = _HOST.match(str(address or "").strip())
    return match.group(1).lower() if match else ""


def _guid(text):
    guid = GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
    return guid


def _method(ptr, slot, *argtypes):
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[slot])


def _release(ptr):
    if ptr:
        try:
            vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_RELEASE])(ptr)
        except Exception:
            pass


_local = threading.local()


def _co_initialize():
    """CoInitializeEx on this thread: True when it succeeded (S_OK or S_FALSE: one CoUninitialize is owed).
    RPC_E_CHANGED_MODE (the thread already has its own apartment) is used as it is, and owes nothing."""
    hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    return hr in (0, 1)


def _co_uninitialize():
    ctypes.windll.ole32.CoUninitialize()


def _co_create(clsid=CLSID_CUIAutomation):
    """A new IUIAutomation pointer (int), or None."""
    ptr = ctypes.c_void_p()
    hr = ctypes.windll.ole32.CoCreateInstance(ctypes.byref(_guid(clsid)), None, CLSCTX_INPROC_SERVER,
                                              ctypes.byref(_guid(IID_IUIAutomation)), ctypes.byref(ptr))
    return ptr.value if hr == 0 and ptr.value else None


class _Automation:
    """One thread's IUIAutomation and its COM initialisation. Kept only in ``_local``: when the thread ends,
    CPython drops the thread's locals on that thread and ``close()`` Releases the instance and, when this
    holder's CoInitializeEx succeeded, uninitialises COM there."""

    def __init__(self, timeouts=False):
        self.thread = threading.get_ident()
        self.ptr = None
        self.initialized = False
        try:
            self.initialized = bool(_co_initialize())
            # DD-BUG-012: a thread that bounds its calls (set_timeouts) needs CUIAutomation8 (IUIAutomation2).
            self.ptr = (_co_create(CLSID_CUIAutomation8) if timeouts else None) or _co_create()
        except Exception:
            self.ptr = None

    def close(self):
        ptr, self.ptr = self.ptr, None
        if ptr:
            _release(ptr)
        initialized, self.initialized = self.initialized, False
        if initialized and threading.get_ident() == self.thread:   # CoUninitialize only on its own thread
            try:
                _co_uninitialize()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _automation(timeouts=False):
    """This thread's IUIAutomation (COM initialised here once), or None. ``timeouts``: a first call creates the
    Windows 8 instance (CUIAutomation8) whose calls ``set_timeouts`` can bound."""
    holder = getattr(_local, "holder", None)
    if holder is None:
        holder = _local.holder = _Automation(timeouts)
    return holder.ptr or None


def set_timeouts(milliseconds):
    """DD-BUG-012: bound this thread's UI Automation calls (IUIAutomation2 connection and transaction timeouts),
    so a browser slow to build its accessibility tree answers None (unreadable) instead of holding the caller.
    True when both were set; False on Windows without IUIAutomation2 or any failure (the defaults stay). Call it
    first on the thread, so its instance is created as CUIAutomation8."""
    uia = _automation(timeouts=True)
    if not uia:
        return False
    second = ctypes.c_void_p()
    try:
        if _method(uia, _QUERY_INTERFACE, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                uia, ctypes.byref(_guid(IID_IUIAutomation2)), ctypes.byref(second)) != 0 or not second.value:
            return False
        ms = W.DWORD(max(1, int(milliseconds)))
        ok = _method(second.value, _UIA2_PUT_CONNECTION_TIMEOUT, W.DWORD)(second.value, ms) == 0
        return _method(second.value, _UIA2_PUT_TRANSACTION_TIMEOUT, W.DWORD)(second.value, ms) == 0 and ok
    except Exception:
        return False
    finally:
        _release(second.value)


def address_host(hwnd):
    """The host in ``hwnd``'s (a top-level Chromium window) address bar, or None when it can't be read."""
    uia = _automation()
    if not uia or not hwnd:
        return None
    element = condition = edit = None
    try:
        element = ctypes.c_void_p()
        if _method(uia, _UIA_ELEMENT_FROM_HANDLE, W.HWND, ctypes.POINTER(ctypes.c_void_p))(
                uia, hwnd, ctypes.byref(element)) != 0 or not element.value:
            return None
        value = VARIANT()
        value.vt, value.lVal = VT_I4, UIA_EditControlTypeId
        condition = ctypes.c_void_p()
        if _method(uia, _UIA_CREATE_PROPERTY_CONDITION, ctypes.c_int, VARIANT, ctypes.POINTER(ctypes.c_void_p))(
                uia, UIA_ControlTypePropertyId, value, ctypes.byref(condition)) != 0 or not condition.value:
            return None
        edit = ctypes.c_void_p()
        if _method(element.value, _ELEMENT_FIND_FIRST, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                element.value, TreeScope_Descendants, condition.value, ctypes.byref(edit)) != 0 or not edit.value:
            return None
        tree = _UiaTree(uia)
        try:
            if not is_address_bar(tree, edit.value):
                return None                       # a field of the page, not the toolbar's omnibox
        finally:
            tree.close()
        result = VARIANT()
        if _method(edit.value, _ELEMENT_GET_CURRENT_PROPERTY_VALUE, ctypes.c_int, ctypes.POINTER(VARIANT))(
                edit.value, UIA_ValueValuePropertyId, ctypes.byref(result)) != 0:
            return None
        try:
            if result.vt != VT_BSTR or not result.bstrVal:
                return None
            return host_of(ctypes.wstring_at(result.bstrVal))
        finally:
            ctypes.windll.oleaut32.VariantClear(ctypes.byref(result))
    except Exception:
        return None
    finally:
        for ptr in (edit, condition, element):
            _release(ptr.value if isinstance(ptr, ctypes.c_void_p) else ptr)


class _UiaTree:
    """The few UI Automation calls ``focus_in_page`` needs, over one IUIAutomation pointer. Elements are plain
    ints (COM pointers) owned by the caller, who releases them (``release``)."""

    def __init__(self, uia):
        self.uia = uia
        self._walker = None

    def _out(self, call, *args):
        out = ctypes.c_void_p()
        if call(*args, ctypes.byref(out)) != 0 or not out.value:
            _release(out.value)
            return None
        return out.value

    def focused(self):
        return self._out(_method(self.uia, _UIA_GET_FOCUSED_ELEMENT, ctypes.POINTER(ctypes.c_void_p)), self.uia)

    def at(self, point):
        return self._out(_method(self.uia, _UIA_ELEMENT_FROM_POINT, W.POINT, ctypes.POINTER(ctypes.c_void_p)),
                         self.uia, W.POINT(int(point[0]), int(point[1])))

    def parent(self, element):
        if self._walker is None:
            self._walker = self._out(_method(self.uia, _UIA_CONTROL_VIEW_WALKER, ctypes.POINTER(ctypes.c_void_p)),
                                     self.uia) or 0
        if not self._walker:
            raise OSError("no control view walker")
        return self._out(_method(self._walker, _WALKER_GET_PARENT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
                         self._walker, element)

    def is_document(self, element):
        result = VARIANT()
        if _method(element, _ELEMENT_GET_CURRENT_PROPERTY_VALUE, ctypes.c_int, ctypes.POINTER(VARIANT))(
                element, UIA_ControlTypePropertyId, ctypes.byref(result)) != 0:
            raise OSError("control type unavailable")
        return result.vt == VT_I4 and result.lVal == UIA_DocumentControlTypeId

    def class_name(self, element):
        result = VARIANT()
        if _method(element, _ELEMENT_GET_CURRENT_PROPERTY_VALUE, ctypes.c_int, ctypes.POINTER(VARIANT))(
                element, UIA_ClassNamePropertyId, ctypes.byref(result)) != 0:
            raise OSError("class name unavailable")
        try:
            if result.vt != VT_BSTR or not result.bstrVal:
                return ""
            return ctypes.wstring_at(result.bstrVal)
        finally:
            ctypes.windll.oleaut32.VariantClear(ctypes.byref(result))

    def same(self, first, second):
        same = W.BOOL()
        if _method(self.uia, _UIA_COMPARE_ELEMENTS, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(W.BOOL))(
                self.uia, first, second, ctypes.byref(same)) != 0:
            raise OSError("compare failed")
        return bool(same.value)

    def release(self, element):
        _release(element)

    def close(self):
        walker, self._walker = self._walker, None
        _release(walker)


def is_address_bar(tree, edit):
    """DD-SEC-002: ``edit`` (the window's first Edit) is the browser toolbar's omnibox: its class is
    OMNIBOX_CLASSES, or, for a class not recorded here, no ancestor of it is a web Document (a page's own text
    field never qualifies). Any UI Automation failure answers False (the host is then unreadable). ``tree`` is a
    ``_UiaTree`` (tests: a fake with the same methods); ``edit`` stays the caller's."""
    held = []
    try:
        if tree.class_name(edit) in OMNIBOX_CLASSES:
            return True
        node = tree.parent(edit)
        for _ in range(MAX_TREE_DEPTH):
            if not node:
                return True
            held.append(node)
            if tree.is_document(node):
                return False
            node = tree.parent(node)
        return False
    except Exception:
        return False
    finally:
        for element in held:
            tree.release(element)


def page_holds_focus(tree, point):
    """True when keyboard focus is inside the outermost web Document that holds ``point`` (the page under the
    cursor), False when it is elsewhere (the address bar, the find bar, docked DevTools, another window), None
    when UI Automation can't tell (no focus, no Document under the point). ``tree`` is a ``_UiaTree`` (tests: a
    fake with the same methods)."""
    held = []

    def keep(element):
        if element:
            held.append(element)
        return element

    try:
        node = keep(tree.at(point))
        document = None
        for _ in range(MAX_TREE_DEPTH):
            if not node:
                break
            if tree.is_document(node):
                document = node                 # the outermost one wins (frames sit inside the page's Document)
            node = keep(tree.parent(node))
        if not document:
            return None
        node = keep(tree.focused())
        if not node:
            return None
        for _ in range(MAX_TREE_DEPTH):
            if not node:
                return False
            if tree.same(node, document):
                return True
            node = keep(tree.parent(node))
        return False
    finally:
        for element in held:
            tree.release(element)


def focus_in_page(point):
    """Whether the keyboard focus is inside the web page under ``point`` (screen pixels): True / False, or None
    when it can't be read (any failure). Nothing is logged or kept."""
    uia = _automation()
    if not uia:
        return None
    tree = _UiaTree(uia)
    try:
        return page_holds_focus(tree, point)
    except Exception:
        return None
    finally:
        tree.close()
