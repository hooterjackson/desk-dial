"""The r3 Navigator's engine on the desktop (r3 README section 5; DESKTOP_STAGE section 24): the
``NanoD-navigator`` thread and its logic, and the ``NanoD-navigator-capture`` backdrop worker.

This module is the stage side of ``control_center.navigator`` (the Tk facade, which never imports the
stage package): ``standalone.start_navigator`` (the one wiring point, K4 4.1; WP8-R11) builds a
``NavigatorThread`` here and hands it to ``navigator.Navigator`` as its backend.

- ``NavigatorEngine`` (driven by ``process()``): the DirectComposition device (``device.NativeDevice``,
  created at the first show, released after 600 s hidden, ``device.DevicePolicy``), a click-through
  host (``host.ROLE_CLICK_THROUGH``: 0x082800A8, never activates, never takes a click) sized to the
  card's column, the backdrop capture (the column behind the card with our windows excluded,
  ``WDA_EXCLUDEFROMCAPTURE``; blurred / saturated / brightened on the capture thread) and
  ``scenes.navigator.NavigatorScene``. Every motion is a compositor-run animation
  (``animation.Batch``: one Commit per event, sampled by DWM at the display rate, 240 Hz here);
  Python does no per-frame work.
- ``NavigatorThread``: the Win32 loop (PMv2 DPI awareness, ``ABOVE_NORMAL``, ``PeekMessageW`` then
  ``MsgWaitForMultipleObjectsEx`` on the mailbox event with the engine's next wake).

The backdrop is a snapshot, refreshed while the card is shown (every ``FROST_REFRESH_S``; a changed
desktop crossfades in over 250 ms, an unchanged one costs no upload). A live system backdrop
(Windows.UI.Composition's HostBackdropBrush) is not available through DirectComposition.
"""
from __future__ import annotations

from collections import OrderedDict
import threading
import time

FROST_STALE_S = 1.5          # a show re-captures the backdrop when the last one is older than this
FROST_REFRESH_S = 2.0        # while shown
SHOW_CAPTURE_WAIT_S = 0.12   # a show waits this long at most for a fresh backdrop
FROST_DIFF_MIN = 1.5         # mean 8-bit difference (1/16 scale) below which a refresh is skipped
ART_CACHE_MAX = 64           # covers the thread keeps (> navigator.ART_SENT_MAX: Tk hands each over once)
HIDE_GRACE_S = 0.02          # the host hides one frame or so after the hide motion ends
CAPTURE_REDUCE = 4


# --------------------------------------------------------------------------- the backdrop worker
class CaptureWorker:
    """``NanoD-navigator-capture``: one job at a time, newest wins. A job grabs the host column
    (our own windows excluded from the capture for the grab only) and builds the frost (blur,
    saturate, brightness at 1/4, all GIL-releasing PIL calls). ``grab`` / ``affinity`` are
    injectable; ``sync=True`` runs jobs inline (tests)."""

    def __init__(self, on_result, *, grab=None, affinity=None, sync=False, name="NanoD-navigator-capture"):
        self._on_result = on_result
        self._grab = grab
        self._affinity = affinity
        self.sync = sync
        self._cond = threading.Condition()
        self._job = None
        self._closed = False
        self.jobs_done = 0
        self._thread = None
        if not sync:
            self._thread = threading.Thread(target=self._run, name=name, daemon=True)
            self._thread.start()

    def submit(self, job) -> bool:
        if self.sync:
            self._on_result(self.run_job(job))
            return True
        with self._cond:
            if self._closed:
                return False
            self._job = job
            self._cond.notify()
            return True

    def close(self, timeout=1.0):
        with self._cond:
            self._closed = True
            self._job = None
            self._cond.notify()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)

    def _run(self):
        try:
            from .. import win32 as W
            W.SetThreadDpiAwarenessContext(W.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception:
            pass
        while True:
            with self._cond:
                while not self._closed and self._job is None:
                    self._cond.wait()
                if self._closed:
                    return
                job, self._job = self._job, None
            result = self.run_job(job)
            with self._cond:
                if self._closed:
                    return
            try:
                self._on_result(result)
            except Exception:
                pass

    def run_job(self, job):
        """job = (gen, rect (x, y, w, h), k, exclude hwnds) -> (gen, frost or None, info)."""
        from .navigator import build_frost
        gen, rect, k, exclude = job
        info = {"capture_ms": None, "build_ms": None, "error": None}
        grab = self._grab
        affinity = self._affinity
        if grab is None:
            from ..capture import screen_grab as grab
        if affinity is None:
            from ..capture import set_affinity as affinity
        raw = None
        try:
            t0 = time.perf_counter()
            if exclude:
                affinity(exclude, True)
            try:
                raw = grab(rect)
            finally:
                if exclude:
                    affinity(exclude, False)
            info["capture_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        except Exception as exc:
            info["error"] = repr(exc)
        frost = None
        try:
            t0 = time.perf_counter()
            frost = build_frost(raw, k, CAPTURE_REDUCE)
            info["build_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        except Exception as exc:
            info["error"] = repr(exc)
        self.jobs_done += 1
        return gen, frost, info


def frost_changed(a, b) -> bool:
    """Whether two frosts differ enough to be worth a new glass (mean abs difference at 1/16)."""
    if a is None or b is None:
        return a is not b
    if a.size != b.size:
        return True
    from PIL import ImageChops, ImageStat
    sa, sb = a.reduce(4), b.reduce(4)
    diff = ImageStat.Stat(ImageChops.difference(sa, sb)).mean
    return sum(diff) / len(diff) >= FROST_DIFF_MIN


# --------------------------------------------------------------------------- the engine
class NavigatorEngine:
    """See the module docstring. Factories: ``device_factory(monitor) -> device``,
    ``host_factory(handler) -> host``, ``clock_factory(device) -> StageClock``, ``monitor_for() ->
    {"rect", "work", ...}`` (the primary monitor), ``capture_factory(on_result) -> CaptureWorker``."""

    def __init__(self, *, device_factory, host_factory, clock_factory, monitor_for, capture_factory=None, log=None,
                 monotonic=time.monotonic, policy=None, wake=None):
        from ..device import DevicePolicy
        self.device_factory = device_factory
        self.host_factory = host_factory
        self.clock_factory = clock_factory
        self.monitor_for = monitor_for
        self.capture_factory = capture_factory
        self.log = log
        self.monotonic = monotonic
        self.policy = policy or DevicePolicy()
        self.wake = wake
        self.lock = threading.Lock()
        self.pending = None              # the newest state from Tk
        self.art_cache = OrderedDict()   # every cover Tk handed over (it sends each once), bounded
        self.touch = False               # a fast-path turn since the last process()
        self.notices = []
        self.captures = []
        self.state = {"content": None, "visible": False, "eligible": False, "reduced": False}
        self.device = self.core = self.target = None
        self.tree = self.root = self.scene = None
        self.geometry = None
        self.host = self.input = None
        self.capture = None
        self.shown = False               # the host is shown (the card may be sliding out)
        self.hide_at = None              # stage tick after which the host hides
        self.waiting_show = None         # monotonic deadline of a show waiting for its backdrop
        self.frost = None
        self.frost_at = None             # monotonic time of the frost's capture
        self.capture_gen = 0
        self.capture_pending = None      # gen in flight
        self.next_refresh = None
        self.exclusions = ()
        self.stopped = False
        self.counters = {"shows": 0, "hides": 0, "swaps": 0, "updates": 0, "captures": 0, "frost_applied": 0,
                         "frost_skipped": 0, "device_creates": 0, "device_releases": 0, "errors": 0,
                         "touch_shows": 0, "commits": 0, "device_lost": 0}
        self.last_error = None
        self.removed_reason_logged = False   # each loss logs GetDeviceRemovedReason once (as the stage engine)
        self.fresh = False               # a device created but not yet through its first show Commit
        self.gave_up = False             # recreate cap reached after losses: wait for the card's next open
        # DD-BUG-036: while any of these is set the card stays hidden whatever state arrives (no
        # show, no backdrop capture); when the last one clears a pinned card shows again.
        self.locked = False              # lock -> unlock (WTS_SESSION_UNLOCK only)
        self.disconnected = False        # session_disconnect -> session_connect
        self.display_dark = False        # display_off -> display_on
        self.suspended = False           # sleep -> resume (user-attended) or display_on

    # ------------------------------------------------------------------ inputs (any thread)
    def post(self, state: dict):
        state = dict(state)
        with self.lock:
            # A newer state replaces a pending one, but never drops the covers it carried (Tk hands
            # each cover over once).
            older = (self.pending or {}).get("art") or {}
            if older:
                state["art"] = {**older, **(state.get("art") or {})}
            self.pending = state
        self._wake()

    def post_touch(self):
        with self.lock:
            self.touch = True
        self._wake()

    def set_exclusions(self, hwnds):
        with self.lock:
            self.exclusions = tuple(int(h) for h in (hwnds or ()) if h)

    def _wake(self):
        w = self.wake
        if w is not None:
            try:
                w()
            except Exception:
                pass

    def _notice(self, kind):
        self.notices.append(kind)

    def _on_capture(self, result):
        with self.lock:
            self.captures.append(result)
        self._wake()

    def _log(self, msg):
        if self.log is not None:
            try:
                self.log(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        from ..host import HostInput, ROLE_CLICK_THROUGH
        self.input = HostInput(ROLE_CLICK_THROUGH, self._notice)
        self.host = self.host_factory(self.input)
        try:
            self.host.register_notifications()
        except Exception as exc:
            self._log(f"navigator: notification registration failed: {exc!r}")
        if self.capture_factory is not None:
            self.capture = self.capture_factory(self._on_capture)

    def teardown(self):
        self._hide_now()
        self._release_device()
        if self.capture is not None:
            try:
                self.capture.close(1.0)
            except Exception:
                pass
        if self.host is not None:
            try:
                self.host.destroy()
            except Exception:
                pass

    @property
    def hwnd(self):
        return getattr(self.host, "hwnd", None)

    # ------------------------------------------------------------------ device and scene
    def _geometry(self):
        from ..layout import StageLayout
        from .navigator import NavGeometry
        mon = self.monitor_for()
        if not mon:
            return None
        rect = mon["rect"] if isinstance(mon, dict) else mon
        work = mon.get("work", rect) if isinstance(mon, dict) else rect
        return NavGeometry(work, StageLayout(rect).k), mon

    def _ensure_scene(self) -> bool:
        from .. import com
        from .. import engine as E
        from .navigator import NavigatorScene
        from ..tree import Tree
        from ..device import COLD, LOST
        if self.device is not None and not self._device_ok():
            self._device_lost("check_device_state", creating=self.fresh)   # never reuse a dead warm device
        if self.scene is not None:
            return True
        if self.device is None and self.gave_up:
            return False                                # the cap holds until the card is hidden and reopened
        got = self._geometry()
        if got is None:
            return False
        self.geometry, mon = got
        now = self.monotonic()
        if self.device is None:
            if not self.policy.want_warm(now):
                return False
            try:
                self.device = self.device_factory(mon)
            except Exception as exc:
                was_lost = self.policy.state == LOST
                self.policy.create_failed(now)
                if was_lost and self.policy.state == COLD:
                    self.gave_up = True
                self.last_error = f"device: {exc!r}"
                self._log(f"navigator: device creation failed: {exc!r}")
                return False
            self.policy.created(now)
            self.fresh = True                           # a loss before the first show Commit is a failed attempt
            self.counters["device_creates"] += 1
            clock = self.clock_factory(self.device)
            self.core = E.StageCore(self.device, clock, log=self.log, monotonic=self.monotonic)
            self.core.surface = "navigator"
            try:
                self.core.read_stats()
                self.core.animation_fns()
                prime = getattr(self.device, "prime", None)
                if prime is not None:
                    prime()
            except com.ComError as exc:
                self.last_error = f"device: {exc!r}"
                if isinstance(exc, com.DeviceLost) or not self._device_ok():
                    self._device_lost(repr(exc), creating=True)   # a failed attempt: the cap holds
                else:
                    self._release_device()
                    self.policy.create_failed(now)
                return False
        self.tree = Tree(self.device)
        self.root = self.tree.root("navigator")
        self.scene = NavigatorScene(self.device, self.tree, self.geometry, reduced_motion=self.state["reduced"])
        self.scene.build(self.root)
        if self.frost is not None:
            self.scene.frost, self.scene.frost_gen = self.frost, 1
        if self.target is None:
            self.target = self.device.create_target(self.host.hwnd)
        self.device.set_root(self.target, self.root.ptr)
        self.policy.scene_opened(now)
        return True

    def _release_scene(self):
        if self.scene is None and self.tree is None:
            return
        try:
            if self.scene is not None:
                self.scene.release()
        except Exception:
            pass
        try:
            if self.target is not None:
                self.device.set_root(self.target, None)
            if self.tree is not None:
                self.tree.release_all()
            self.device.commit()
        except Exception:
            pass
        self.scene = self.tree = self.root = None
        self.policy.scene_closed(self.monotonic())

    def _device_ok(self) -> bool:
        try:
            return bool(self.device.check_device_state())
        except Exception:
            return False

    def _device_lost(self, why, *, creating: bool = False):
        """Mirror of ``StageEngine._device_lost`` (DESKTOP_STAGE 4.3): hide, release the scene and the
        device, log the removed reason once, and let the policy recreate at most twice 1 s apart."""
        self.counters["device_lost"] += 1
        self._hide_now()
        if self.device is not None and not self.removed_reason_logged:
            try:
                from .. import com
                self._log(f"navigator: device lost ({why}); GetDeviceRemovedReason "
                          f"{com.hx(self.device.removed_reason())}")
            except Exception:
                pass
            self.removed_reason_logged = True
        self._release_device()
        from ..device import COLD
        if creating:
            self.policy.lost_while_creating(self.monotonic())
            if self.policy.state == COLD:
                self.gave_up = True                     # no new device until the card's next open
        else:
            self.policy.lost(self.monotonic())

    def _release_device(self):
        self._release_scene()
        if self.device is not None:
            try:
                self.device.teardown()
            except Exception:
                pass
            self.counters["device_releases"] += 1
        self.device = self.core = self.target = None
        self.fresh = False

    # ------------------------------------------------------------------ the loop body
    def process(self):
        """Handle everything pending; return seconds until the next wake (None = none)."""
        try:
            self._handle_notices()
            with self.lock:
                pending, self.pending = self.pending, None
                touch, self.touch = self.touch, False
                captures, self.captures = self.captures, []
            for result in captures:
                self._handle_capture(result)
            if pending is not None:
                self._handle_state(pending)
            if touch:
                self._handle_touch()
            self._timers()
        except Exception as exc:
            self._recover(exc, retry=True)
        return self._next_wake()

    def _recover(self, exc, *, retry):
        """An error in the loop body: release what it touched. A device loss releases the device too
        (as a failed creation attempt while the device is fresh, so the cap holds) and, once, tries
        the recreate at once; that recreate's own error is handled the same way, without a retry."""
        from .. import com
        self.counters["errors"] += 1
        self.last_error = repr(exc)
        self._log(f"navigator: error {exc!r}")
        lost = isinstance(exc, com.DeviceLost) or (self.device is not None and not self._device_ok())
        try:
            self._hide_now()
            if lost:
                self._device_lost(repr(exc), creating=self.fresh)
            else:
                self._release_scene()
        except Exception:
            pass
        if lost and retry:
            try:
                self._timers()                          # recreate at once while the card is wanted
            except Exception as exc2:
                self._recover(exc2, retry=False)

    @property
    def suppressed(self) -> bool:
        return self.locked or self.disconnected or self.display_dark or self.suspended

    def _user_wants(self):
        return bool(self.state["visible"] and self.state["content"] is not None)

    def _want_visible(self):
        return self._user_wants() and not self.suppressed

    def _handle_notices(self):
        notes, self.notices = self.notices, []
        for kind in notes:
            if kind in ("lock", "session_disconnect", "sleep", "display_off", "endsession"):
                if kind == "lock":
                    self.locked = True
                elif kind == "session_disconnect":
                    self.disconnected = True
                elif kind == "sleep":
                    self.suspended = True
                elif kind == "display_off":
                    self.display_dark = True
                self.next_refresh = None
                self._hide_now()
            elif kind in ("unlock", "session_connect", "display_on", "resume"):
                was = self.suppressed
                if kind == "unlock":
                    self.locked = False
                elif kind == "session_connect":
                    self.disconnected = False
                elif kind == "resume":
                    self.suspended = False
                else:                                   # display_on: the screen is visibly back
                    self.display_dark = False
                    self.suspended = False
                if was and not self.suppressed and self._want_visible() and not (
                        self.shown and self.scene is not None and self.scene.visible):
                    self._begin_show()                  # a pinned card comes back with the screen
            elif kind == "display":
                self._hide_now()
                self._release_scene()          # rebuilt for the new geometry at the next show
                self.frost = None

    def _art_for(self, content):
        """The cached covers ``content`` shows (the scene may have been rebuilt or pruned its own)."""
        if content is None:
            return {}
        keys = {getattr(content, "art_key", "")} | {cv.art_key for cv in getattr(content, "covers", ()) or ()}
        return {key: self.art_cache[key] for key in keys if key and key in self.art_cache}

    def _handle_state(self, st):
        prev = self.state
        incoming = st.get("art") or {}
        for key, image in incoming.items():
            self.art_cache[key] = image
            self.art_cache.move_to_end(key)
        while len(self.art_cache) > ART_CACHE_MAX:
            self.art_cache.popitem(last=False)
        content = st.get("content")
        self.state = {"content": content, "visible": bool(st.get("visible")),
                      "eligible": bool(st.get("eligible")), "reduced": bool(st.get("reduced")),
                      "art": self._art_for(content), "new_art": bool(incoming)}
        if self.scene is not None:
            self.scene.reduced = self.state["reduced"]
        want = self._want_visible()
        content = self.state["content"]
        if not self._user_wants():
            self.gave_up = False                        # the card's next open may try a new device
        if self.suppressed:
            if self.scene is not None and self.scene.visible:
                self._hide_now()
            return                                      # nothing drawn until the screen is back
        if want and not (self.shown and self.scene is not None and self.scene.visible):
            self._begin_show()
            return
        if self.scene is not None and content is not None and (content != prev.get("content")
                                                               or self.state["new_art"]):
            self._apply(content, prev.get("content"))
        if not want and self.scene is not None and self.scene.visible:
            self._begin_hide()

    def _handle_touch(self):
        """A fast-path turn: show the last eligible content now (the Tk tick confirms it)."""
        if self.suppressed:
            return
        if self.state.get("eligible") and self.state.get("content") is not None and not (
                self.scene is not None and self.scene.visible):
            self.state["visible"] = True
            self.counters["touch_shows"] += 1
            self._begin_show()

    def _direction(self, new, old):
        if old is None or new is None:
            return 0
        if old.mode == new.mode:
            # Home's hold-4 domain swap (music <-> lights, mode stays launcher) slides laterally like
            # the knob (M12/M14): towards Lights from the right, back to music from the left.
            if old.kind != new.kind and {old.kind, new.kind} == {"now", "lights"}:
                return 1 if new.kind == "lights" else -1
            return 0
        return 1 if new.depth >= old.depth else -1

    def _apply(self, content, prev):
        batch = self.core.batch()
        self.scene.apply(batch, content, art=self.state.get("art"), direction=self._direction(content, prev))
        self._commit(batch, "update")

    def _commit(self, batch, kind):
        batch.commit()
        self.core.finish(batch, kind)
        self.counters["commits"] += 1

    # ---- show
    def _begin_show(self):
        """Show now, or first wait (at most ``SHOW_CAPTURE_WAIT_S``) for a fresh backdrop when the
        card is not on screen and the last one is stale."""
        if self.waiting_show is not None:
            return
        now = self.monotonic()
        stale = self.frost_at is None or now - self.frost_at > FROST_STALE_S
        if stale and self.capture is not None and not self.shown:
            self.waiting_show = now + SHOW_CAPTURE_WAIT_S
            if self._request_capture():
                return                          # _handle_capture (or the deadline) shows it
            self.waiting_show = None
        self._show_now()

    def _show_now(self):
        self.waiting_show = None
        if not self._want_visible():
            return
        if not self._ensure_scene():
            return
        content = self.state["content"]
        batch = self.core.batch()
        if self.frost is not None and self.scene.frost_gen == 0:
            self.scene.frost, self.scene.frost_gen = self.frost, 1
        self.scene.apply(batch, content, art=self.state.get("art"), direction=0)
        self.scene.show(batch, True)
        self._commit(batch, "show")
        if self.fresh:
            self.fresh = False                          # the new device made it to the screen
            self.removed_reason_logged = False          # its own loss may log the reason again
        self.policy.scene_opened(self.monotonic())   # every show, also of a warm scene: no idle release
        self.hide_at = None
        if not self.shown:
            self.host.show(self.geometry.host)
            self.shown = True
        self.counters["shows"] += 1
        self.next_refresh = self.monotonic() + FROST_REFRESH_S

    # ---- hide
    def _begin_hide(self):
        batch = self.core.batch()
        self.scene.show(batch, False)
        self._commit(batch, "hide")
        end = self.scene.settle_end()
        self.hide_at = end if end is not None else self.core.clock.now()
        self.counters["hides"] += 1
        self.next_refresh = None

    def _hide_now(self):
        if self.host is not None and self.shown:
            try:
                self.host.hide()
            except Exception:
                pass
        self.shown = False
        self.hide_at = None
        self.waiting_show = None
        if self.scene is not None and self.scene.visible and self.core is not None:
            try:
                batch = self.core.batch()
                self.scene.reduced, was = True, self.scene.reduced
                self.scene.show(batch, False)
                self.scene.reduced = was
                batch.jump(self.scene.card_op, 0.0)
                self._commit(batch, "hide")
            except Exception:
                pass

    # ---- backdrop
    def _request_capture(self) -> bool:
        """Grab the host column behind the card (our window excluded while it is shown)."""
        if self.capture is None:
            return False
        if self.capture_pending is not None:
            return True
        if self.geometry is None:
            got = self._geometry()
            if got is None:
                return False
            self.geometry = got[0]
        geo = self.geometry
        self.capture_gen += 1
        self.capture_pending = gen = self.capture_gen
        with self.lock:
            exclude = tuple(self.exclusions)
        own = self.hwnd if self.shown else None
        if own:
            exclude = exclude + (own,)
        self.counters["captures"] += 1
        if not self.capture.submit((gen, geo.host, geo.k, exclude)):
            self.capture_pending = None
            return False
        with self.lock:                         # a synchronous worker has delivered already
            landed, self.captures = self.captures, []
        for r in landed:
            self._handle_capture(r)
        return True

    def _handle_capture(self, result):
        gen, frost, info = result
        if gen != self.capture_pending:
            return
        self.capture_pending = None
        if info.get("error"):
            self.last_error = f"capture: {info['error']}"
        if frost is not None:
            changed = frost_changed(self.frost, frost)
            self.frost, self.frost_at = frost, self.monotonic()
            if self.scene is not None and self.scene.visible and self.shown:
                if changed:
                    batch = self.core.batch()
                    self.scene.set_frost(batch, frost)
                    self._commit(batch, "frost")
                    self.counters["frost_applied"] += 1
                else:
                    self.counters["frost_skipped"] += 1
            elif self.scene is not None:
                self.scene.frost, self.scene.frost_gen = frost, self.scene.frost_gen + 1
        if self.waiting_show is not None:
            self._show_now()

    # ---- timers
    def _timers(self):
        now = self.monotonic()
        if self.waiting_show is not None and now >= self.waiting_show:
            self._show_now()                    # the backdrop was late: show with the one we have
        if self.hide_at is not None and self.core is not None and \
                self.core.clock.now() >= self.hide_at + self.core.period:
            if self.host is not None and self.shown:
                self.host.hide()
            self.shown = False
            self.hide_at = None
        if self.core is not None:
            self.core.tick()
        if self.device is None and self.waiting_show is None and self._want_visible()                 and self.policy.recreate_due(now):
            self._show_now()                    # after a device loss: recreate (at most twice, 1 s apart)
        if self.next_refresh is not None and now >= self.next_refresh:
            self.next_refresh = now + FROST_REFRESH_S
            if self.scene is not None and self.scene.visible:
                self._request_capture()
        if self.device is not None and self.scene is not None and not self.shown and not self._want_visible():
            # hidden: the scene is kept warm; the device goes after 600 s without a show
            if self.policy.idle_since is None:
                self.policy.scene_closed(now)
        if self.device is not None and not self.shown and not self._want_visible() and self.policy.release_due(now):
            self._log("navigator: device released after 600 s hidden")
            self._release_device()
            self.policy.released(now)

    def _next_wake(self):
        now = self.monotonic()
        waits = []
        if self.waiting_show is not None:
            waits.append(self.waiting_show - now)
        if self.hide_at is not None and self.core is not None:
            waits.append((self.hide_at + self.core.period - self.core.clock.now()) / self.core.clock.freq
                         + HIDE_GRACE_S)
        if self.core is not None:
            w = self.core.next_wake_s()
            if w is not None:
                waits.append(w)
        if self.next_refresh is not None:
            waits.append(self.next_refresh - now)
        nw = self.policy.next_wake()
        if nw is not None and (self.device is not None or self._want_visible()):
            waits.append(nw - now)              # a lost device is recreated only for a wanted card
        return max(0.0, min(waits)) if waits else None

    def metrics(self):
        return {"shown": self.shown, "visible": bool(self.scene is not None and self.scene.visible),
                "device": getattr(self.device, "kind", None), "counters": dict(self.counters),
                "scene": dict(self.scene.stats) if self.scene is not None else None,
                "frost_age_s": (round(self.monotonic() - self.frost_at, 2) if self.frost_at is not None else None),
                "host": getattr(self.geometry, "host", None), "last_error": self.last_error,
                "suppressed": self.suppressed}


# --------------------------------------------------------------------------- the Win32 thread
class NavigatorThread:
    """``NanoD-navigator``: the engine on its own Win32 thread (Windows). A thread that cannot start
    leaves the Navigator disabled (``disabled`` says why); the Tk side then keeps the floating knob.
    ``host_hidden_only`` (tests, the self-check) creates the host but never shows it."""

    def __init__(self, *, log=None, start=True, host_hidden_only=False, name="NanoD-navigator"):
        self.log = log
        self.host_hidden_only = host_hidden_only
        self.engine = None
        self.disabled = None
        self._event = None
        self._stop = False
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        if start:
            self._thread.start()
            self._ready.wait(5.0)

    def _set_event(self):
        ev = self._event
        if ev:
            from .. import win32 as W
            W.SetEvent(ev)

    def _run(self):
        import ctypes as C
        try:
            from .. import clock as CK
            from .. import win32 as W
            from ..device import NativeDevice
            from ..host import HostWindow, pump_messages
            W.SetThreadDpiAwarenessContext(W.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            W.SetThreadPriority(W.GetCurrentThread(), W.THREAD_PRIORITY_ABOVE_NORMAL)
            self._event = W.CreateEventW(None, False, False, None)
            engine = NavigatorEngine(
                device_factory=lambda mon: NativeDevice(mon.get("hmonitor") if isinstance(mon, dict) else None),
                host_factory=lambda handler: HostWindow(handler, hidden_only=self.host_hidden_only),
                clock_factory=lambda dev: CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc),
                monitor_for=W.primary_monitor,
                capture_factory=lambda cb: CaptureWorker(cb),
                log=self.log, wake=self._set_event)
            engine.start()
            self.engine = engine
        except Exception as exc:
            self.disabled = repr(exc)
            if self.log is not None:
                try:
                    self.log(f"navigator: disabled: {exc!r}")
                except Exception:
                    pass
            self._ready.set()
            return
        self._ready.set()
        handles = (C.c_void_p * 1)(self._event)
        try:
            while not self._stop and not engine.stopped:
                if pump_messages(W) < 0:
                    break
                timeout = engine.process()
                if self._stop:
                    break
                ms = W.INFINITE if timeout is None else max(0, int(timeout * 1000.0 + 0.999))
                if ms == 0:
                    continue
                W.MsgWaitForMultipleObjectsEx(1, handles, ms, W.QS_ALLINPUT, W.MWMO_INPUTAVAILABLE)
        finally:
            try:
                engine.teardown()
            finally:
                W.CloseHandle(self._event)
                self._event = None

    def post(self, state):
        if self.engine is not None:
            self.engine.post(state)

    def post_touch(self):
        if self.engine is not None:
            self.engine.post_touch()

    def set_exclusions(self, hwnds):
        if self.engine is not None:
            self.engine.set_exclusions(hwnds)

    @property
    def hwnd(self):
        return self.engine.hwnd if self.engine is not None else None

    def metrics(self):
        if self.engine is None:
            return {"state": "disabled" if self.disabled else "starting", "disabled": self.disabled}
        return self.engine.metrics()

    def close(self, timeout=2.0) -> bool:
        self._stop = True
        self._set_event()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread.is_alive()
