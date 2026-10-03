"""The r3 Navigator's Tk side (r3 README section 5; DESKTOP_STAGE section 24): the compact liquid-glass
card on the primary monitor's left edge that replaces the floating knob mirror for an r3 knob
(presentation >= 6).

``Navigator`` is the facade ``ui.ControlCenterApp`` calls on each tick. It derives the content from
the controller (``navigator_model.read_snapshot`` / ``build_content``: read only), applies the
visibility rules (``navigator_model.Visibility``: Auto-hide / Pinned / Off, 4 s, sticky modes, hidden
while a full-screen overlay is open or the knob is away), hands the cover images over (the playing
cover from the runtime; the Recently Added covers from ``covers``) and posts one newest-wins state
to its backend when anything changed. It never waits. ``note_press`` / ``note_turn`` come from the
serial reader's fast path (any thread): a turn shows an eligible Navigator at once, a press fills its
key.

This module never imports the stage package (the one-wiring-point rule, K4 4.1; WP8-R11): the
backend (``stage.scenes.navigator_engine.NavigatorThread``) and the covers source
(``stage.scenes.navigator_covers.NavigatorCovers``, over the explorer's art workers) are built by
``standalone.start_navigator`` and handed in.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from . import navigator_model as NM

ART_SENT_MAX = 32            # cover images the Tk side remembers having handed over


# --------------------------------------------------------------------------- the Tk facade
class Navigator:
    """The Tk side (see the module docstring). ``backend``: a ``NavigatorThread`` (or anything with
    ``post(state)``, ``post_touch()``, ``hwnd``, ``metrics()``, ``close()``), None = no Navigator."""

    def __init__(self, backend=None, *, mode=NM.DEFAULT_MODE, clock=time.monotonic, covers=None):
        self.backend = backend
        self.covers = covers             # navigator_covers.NavigatorCovers (Recently Added art), or None
        self.clock = clock
        self.visibility = NM.Visibility(mode=NM.normal_mode(mode))
        self._lock = threading.Lock()
        self._press = None               # (slot, t) of the newest press (fast path, any thread)
        self._turn_t = None
        self._touch_seen = None
        self._last = None                # the state last posted
        self._art_sent = OrderedDict()   # art_key -> image already handed over (bounded, ART_SENT_MAX)
        self._covers_seq = None
        self.active = False              # the Navigator replaced the floating knob on the last tick
        self.eligible = False
        self.posts = 0

    @property
    def available(self) -> bool:
        if self.backend is None:
            return False
        return not getattr(self.backend, "disabled", None)

    @property
    def mode(self):
        return self.visibility.mode

    def set_mode(self, mode):
        self.visibility.set_mode(mode)

    @property
    def hwnd(self):
        try:
            return getattr(self.backend, "hwnd", None)
        except Exception:
            return None

    # ------------------------------------------------------------------ fast path (any thread)
    def note_press(self, slot, t=None):
        with self._lock:
            self._press = (slot, self.clock() if t is None else self.clock())
            self._turn_t = self.clock()

    def note_turn(self, t=None):
        with self._lock:
            self._turn_t = self.clock()
        if self.eligible and self.backend is not None:
            try:
                self.backend.post_touch()
            except Exception:
                pass

    # ------------------------------------------------------------------ the Tk tick
    def update(self, runtime, frame, *, overlay_open=False, now=None) -> bool:
        """One tick: returns True when the Navigator stands in for the floating knob (an r3 knob and
        a working Navigator), False to keep the floating knob. Navigator Off, and a mode without a
        Navigator card of its own (Onshape, A0), hand the desktop back to the floating knob
        (DD-DES-004: Off means no Navigator, not no desktop knob)."""
        now = self.clock() if now is None else now
        if not self.available or not NM.applies(runtime):
            if self.active:
                self._post({"content": None, "visible": False, "eligible": False, "reduced": False, "art": {}})
            self.active = False
            return False
        if self.visibility.mode == "off":
            return self._hand_back(runtime)
        self.active = True
        seq = getattr(runtime, "touch_seq", 0)
        if self._touch_seen is None:
            self._touch_seen = seq
        if seq != self._touch_seen:
            self.visibility.note_input(now)
            self._touch_seen = seq
        with self._lock:
            press, turn_t = self._press, self._turn_t
        if turn_t is not None and (self.visibility.last_input is None or turn_t > self.visibility.last_input):
            self.visibility.note_input(turn_t)
        pressed = press[0] if press is not None and now - press[1] < NM.PRESS_FLASH_S else None
        controller = getattr(runtime, "controller", None)
        snap = NM.read_snapshot(controller, frame)
        held_for = getattr(runtime, "held_for", None)     # r3.1: the HOLD chips' progress (buttons 1 and 4)
        if callable(held_for):
            try:
                snap["held"] = dict(held_for())
            except Exception:
                pass
        content = NM.build_content(snap, pressed=pressed)
        mode = snap.get("mode")
        if content is None and mode and mode not in NM.OVERLAY_MODES:
            return self._hand_back(runtime)            # no card for this mode: the floating knob covers it
        overlay = bool(overlay_open or mode in NM.OVERLAY_MODES or (getattr(runtime, "open_surfaces", None) or ()))
        connected = bool(getattr(runtime, "device_connected", False))
        visible = self.visibility.visible(now, content, overlay_open=overlay, connected=connected)
        self.eligible = bool(content is not None and self.visibility.mode != "off" and not overlay and connected)
        art = {}
        if content is not None and content.art_key and content.art_key not in self._art_sent:
            image = _cover_image(runtime, frame)
            if image is not None:
                art[content.art_key] = image
        if content is not None and content.kind == "covers" and self.covers is not None:
            content = self._with_covers(content, snap, art)
        for key, image in art.items():
            self._art_sent[key] = image
            self._art_sent.move_to_end(key)
        while len(self._art_sent) > ART_SENT_MAX:
            self._art_sent.popitem(last=False)
        state = {"content": content, "visible": visible, "eligible": self.eligible,
                 "reduced": bool(getattr(runtime, "reduced_motion", False)), "art": art}
        last = self._last
        if last is None or art or any(last.get(k) != state[k] for k in ("content", "visible", "eligible", "reduced")):
            self._post(state)
        return True

    def _hand_back(self, runtime) -> bool:
        """Hide the card (posted once) and keep the floating knob: returns False."""
        seq = getattr(runtime, "touch_seq", 0)      # the floating knob took these touches: noted, not
        if self._touch_seen is not None and seq != self._touch_seen:   # replayed later as a fresh show
            self.visibility.note_input(self.clock())
        self._touch_seen = seq
        with self._lock:
            turn_t = self._turn_t
        if turn_t is not None and (self.visibility.last_input is None or turn_t > self.visibility.last_input):
            self.visibility.note_input(turn_t)
        last = self._last
        if last is None or last.get("visible") or last.get("eligible"):
            self._post({"content": None, "visible": False, "eligible": False,
                        "reduced": bool(getattr(runtime, "reduced_motion", False)), "art": {}})
        self.active = False
        self.eligible = False
        return False

    def _with_covers(self, content, snap, art):
        """Recently Added (r3.1: or Favourite playlists): the covers' art keys from the explorer's
        identity (``NavigatorCovers``), the covers asked for (+/-2, off the Tk thread) and every one
        that landed handed over once."""
        import dataclasses
        items = snap.get("recent") or []
        if not items:
            return content
        focus = max(0, min(len(items) - 1, int(snap.get("index") or 0)))
        source = snap.get("list_source") or "recent"
        try:
            # r3.1: Favourite playlists take the explorer's playlist identity (mosaic / first cover).
            keys = self.covers.want(items, focus, source) if source != "recent" else self.covers.want(items, focus)
        except Exception:
            return content
        covers = []
        for cv in content.covers:
            key = keys.get(focus + cv.offset, "")
            covers.append(dataclasses.replace(cv, art_key=key))
            if key and key not in self._art_sent and key not in art:
                image = self.covers.get(key)
                if image is not None:
                    art[key] = image
        return dataclasses.replace(content, covers=tuple(covers))

    def next_change(self, now=None):
        """Seconds until the auto-hide (the Tk tick runs anyway; informational)."""
        now = self.clock() if now is None else now
        last = self._last or {}
        return self.visibility.next_change(now, last.get("content"))

    def _post(self, state):
        self._last = state
        self.posts += 1
        if self.backend is not None:
            try:
                self.backend.post(state)
            except Exception:
                pass

    def set_exclusions(self, hwnds):
        setter = getattr(self.backend, "set_exclusions", None)
        if callable(setter):
            try:
                setter(hwnds)
            except Exception:
                pass

    def metrics(self):
        base = {"mode": self.visibility.mode, "active": self.active, "eligible": self.eligible, "posts": self.posts}
        try:
            base["engine"] = self.backend.metrics() if self.backend is not None else None
        except Exception as exc:
            base["engine"] = {"error": repr(exc)}
        return base

    def close(self, timeout=2.0):
        if self.covers is not None:
            self.covers.close()
        if self.backend is not None:
            try:
                return self.backend.close(timeout)
            except Exception:
                return False
        return True


def _cover_image(runtime, frame):
    """The playing / focused cover as a PIL image: r3.1 the unscrimmed hi-res cover (the knob's copies
    carry its text scrim, which read as a dark veil on the glass card), else the hi-res / 240 px one."""
    clean = getattr(runtime, "clean_cover", None)
    if callable(clean):
        try:
            image = clean(frame)
        except Exception:
            image = None
        if image is not None and hasattr(image, "size"):
            return image
    try:
        media = runtime.lcd_media(frame, None, hires=True)
    except Exception:
        return None
    try:
        art, _icon, _a2, _identity, cover, _big = media
    except Exception:
        return None
    for image in (cover, art):
        if image is not None and hasattr(image, "size") and hasattr(image, "convert"):
            return image
    return None


def start_navigator(backend=None, *, mode=NM.DEFAULT_MODE, covers=None):
    """The facade over a started backend (``standalone.start_navigator`` builds it). A None or
    disabled backend keeps the floating knob for every knob."""
    return Navigator(backend, mode=mode, covers=covers)
