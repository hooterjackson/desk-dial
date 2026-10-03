"""The runtime's presenter for the Music explorer and Up next (CONTROL_CENTER_V5 K3 §11;
DESKTOP_STAGE K4 §2.3, §5.3; VOC §7.4).

``MusicOverlay`` is what ``runtime.ControlCenterRuntime`` gets as its ``stage`` presenter: it
takes K3's pushed effects (``post(effect)``, or the eight VOC §7.4 methods one-to-one), keeps
only the K4 §2.3 payload (``kind``, ``request`` and ``view_id`` stay with the runtime; every other
field goes through), and posts them to the stage presenter's newest-wins mailbox without waiting.
Events come back with ``take_events()`` (K4's ``(kind, payload)`` tuples; the runtime normalises
them and hands each to ``controller.presenter_event``, VOC-R22).

It is dependency-injected: the stage (``stage.scenes.start_music_stage``: the ``NanoD-stage``
thread, both scenes and the art workers) is created by the shell (WP10) and handed in, so no
module outside the stage package imports the stage until that wiring exists (the WP7a "no
behaviour change" gate). Without a presenter every call is a no-op and every open is refused
with ``device`` (K3 §13.5: the explorer and Up next then run on the knob alone).

Fast path (K4 §5.3, §22 Q3): ``position(control_id, p, t_read)`` from the serial reader goes
straight to the stage; ``note_touch()`` warms the stage device at the first knob touch (§4.2).
"""
from __future__ import annotations

import logging
import time

EFFECTS = ("explorer_open", "explorer_highlight", "explorer_source", "explorer_close",
           "upnext_open", "upnext_highlight", "upnext_rows", "upnext_close")
OPENS = {"explorer_open": "explorer", "upnext_open": "upnext"}
RUNTIME_ONLY = ("kind", "request", "view_id")

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())


def stage_payload(effect: dict) -> dict:
    """The K4 §2.3 payload of a K3 effect (the runtime's bookkeeping fields dropped)."""
    return {k: v for k, v in effect.items() if k not in RUNTIME_ONLY}


class MusicOverlay:
    """See the module docstring. ``presenter`` is a ``stage.presenter.StagePresenter`` (or any
    object with its methods); ``art`` the scenes' ``ArtService`` (closed with the overlay)."""

    def __init__(self, presenter=None, *, art=None, thread=None, clock=time.perf_counter):
        self.presenter = presenter
        self.art = art
        self.thread = thread
        self.clock = clock
        self._events = []
        self.posted = 0
        self.failed = 0
        self._warned = False
        self._closed = None  # the first close()'s result; set once closed

    # ------------------------------------------------------------------ effects (Tk thread)
    def post(self, effect) -> bool:
        kind = effect.get("kind") if isinstance(effect, dict) else None
        if kind not in EFFECTS:
            return False
        return self._call(kind, stage_payload(effect))

    def _call(self, kind, payload) -> bool:
        if self.presenter is None:
            if kind in OPENS:
                self._events.append(("refused", {"surface": OPENS[kind], "reason": "device", "t0": self.clock()}))
            return False
        try:
            ok = getattr(self.presenter, kind)(payload)
        except Exception as exc:
            self.failed += 1
            if not self._warned:
                self._warned = True
                _log.warning("Music overlay call %s failed (%s)", kind, type(exc).__name__)
            if kind in OPENS:
                self._events.append(("refused", {"surface": OPENS[kind], "reason": "device", "t0": self.clock()}))
            return False
        self.posted += 1
        return ok is not False

    def explorer_open(self, payload):
        return self._call("explorer_open", stage_payload(payload))

    def explorer_highlight(self, payload):
        return self._call("explorer_highlight", stage_payload(payload))

    def explorer_source(self, payload):
        return self._call("explorer_source", stage_payload(payload))

    def explorer_close(self, payload):
        return self._call("explorer_close", stage_payload(payload))

    def upnext_open(self, payload):
        return self._call("upnext_open", stage_payload(payload))

    def upnext_highlight(self, payload):
        return self._call("upnext_highlight", stage_payload(payload))

    def upnext_rows(self, payload):
        return self._call("upnext_rows", stage_payload(payload))

    def upnext_close(self, payload):
        return self._call("upnext_close", stage_payload(payload))

    # ------------------------------------------------------------------ fast path, warm-up, capture
    def position(self, control_id, p, t_read=None):
        if self.presenter is None:
            return False
        return self.presenter.position(control_id, p, t_read)

    def note_touch(self):
        if self.presenter is not None:
            self.presenter.note_touch()

    def set_capture_exclusions(self, hwnds):
        if self.presenter is not None:
            self.presenter.set_capture_exclusions(hwnds)

    # ------------------------------------------------------------------ events, metrics, lifetime
    def take_events(self):
        out, self._events = self._events, []
        if self.presenter is not None:
            try:
                out.extend(self.presenter.take_events())
            except Exception:
                pass
        return out

    def metrics(self):
        m = {"posted": self.posted, "failed": self.failed}
        if self.presenter is not None:
            try:
                m["stage"] = self.presenter.metrics()
            except Exception:
                pass
        if self.art is not None:
            m["art"] = dict(self.art.stats)
        return m

    def close(self, timeout: float = 2.0) -> bool:
        """Close the stage, then the art workers, within ONE ``timeout`` budget. Idempotent: a
        second call returns the first call's result at once and never waits again."""
        if self._closed is not None:
            return self._closed
        deadline = self.clock() + max(0.0, float(timeout))
        ok = True
        if self.presenter is not None:
            try:
                ok = bool(self.presenter.close(timeout))
            except Exception:
                ok = False
        if self.art is not None:
            try:
                self.art.close(max(0.0, deadline - self.clock()))
            except Exception:
                pass
        self._closed = ok
        return ok
