"""The stage engine: the ``NanoD-stage`` thread and its core (DESKTOP_STAGE §2.2, §4.1-§4.3, §4.6.7,
§4.9, §6.1, §15; [G1] G1-1 ... G1-8).

Three layers, so everything is testable headlessly:

- ``StageCore`` - device-bound, not threaded: the clock and P, t1 (G1-6), one ``Batch`` per
  event with its one Commit (a Commit over 2 ms is logged, rate-limited), the episode tracker
  (boost the compositor clock at an episode's start, unboost after its last animation), the
  250 ms statistics harvest while an episode runs and the display is on (G1-1, G1-3), and the
  FrameStats record with the §6.3 verdict per episode. The bench, the self-test and the
  supervised check drive it directly.
- ``StageEngine`` - the stage thread's logic, single-threaded and driven by ``process()``:
  the mailbox, the §4.9 open sequence (the capture with exclusions submitted first, a cold
  device created while it runs -> frost at 1/8 -> tree in its hidden pose -> commit the root
  fade, the scene's entries and every update that arrived while capturing at t1 -> show without
  activating -> ``opened``), turns and the fast path (§5.3), the animated and instant closes
  (§4.9, §15; S5-26), the host's system notifications (§4.1), device loss (§4.3) and the
  device lifetime (§4.2); the curve tables are warmed in idle wakes (``curves.Prewarmer``),
  every episode records the stage threads' CPU share, and ``NANOD_FPS_HUD=1`` draws the newest
  FrameStats record on the stage 4 times a second (§6.2). Tests run it with the fake device, a
  fake host and a synchronous capture.
- ``StageThread`` - the Win32 loop: per-thread PMv2 DPI awareness, ``ABOVE_NORMAL`` priority,
  ``PeekMessageW`` at the top of every turn, then ``MsgWaitForMultipleObjectsEx`` on the
  mailbox's auto-reset event with the engine's next wake as the timeout (no polling timer:
  wakes are for input, content that became ready, clean-up and the 250 ms harvest only).

Python does no per-frame work for the stage: DWM runs every curve (§1 item 1).

**The 2026-09-26 frame-drop fixes** (the on-screen tours' diagnosis; ``device`` and ``surfaces``
module docstrings for the measurements):

- **S1, uploads a frame ahead.** An upload wake commits its uploads at once in their own Commit,
  paced two frames and 1 ms apart (an upload-carrying Commit sooner than that blocks until then),
  so no input or reveal Commit ever carries an upload; the scene's reveal (``uploads_ready``: the
  content swap with the animation that shows it, §4.4) comes in a later wake, once the surfaces
  are ``READY_S`` (a frame) old, as a bind-only Commit. ``StageCore`` counts the Commits that
  carried uploads per batch kind (``commits_with_uploads``; 0 for ``turn`` and ``art`` by design).
- **S2, the open.** The device pays its first upload-carrying Commit at creation (``prime``: about
  10 ms that the cold open's Commit carried, 45 ms with its uploads on screen, after t1: the lost
  leading vblanks); the open flushes its uploads (the frost, the build's prepared sprites) before
  its batch; the batch's t1 keeps G1-6's largest adaptive margin (P: the open's batch and its
  Commit take 1.4-5 ms, past the fixed 1.5 ms), from the moment that upload-carrying Commit can
  return (two frames after the previous one, ``_open_not_before``), so the first frame is on time.
- **S3, holds are not missed frames.** Each episode keeps its batches' motion spans (plain legs as
  one span from t1; delayed, multi-leg and step motions exactly), and ``frames.ChangeModel`` tells,
  for the vblanks the compositor did not present, whether anything changed there (§4.6.4's designed
  holds: the heart's 40 ms, a switch's 170 -> 190 ms). The ``*_in_motion`` fields exclude them and
  §6.3's judge reads those ("Displayed frames/s in motion"); the raw fields are unchanged.
"""
from __future__ import annotations

import os
import threading
import time

from . import animation as AN
from . import blur as B
from . import clock as CK
from . import com
from . import curves as CV
from . import frames as FR
from .device import DevicePolicy
from .host import HostInput, ROLE_CLICK_EATING
from .layout import StageLayout
from .presenter import (ANIMATED_CLOSES, CALL_SURFACE, Mailbox, REFUSE_BUSY, REFUSE_DEVICE, merge_highlight)
from .surfaces import (UPLOAD_GAP_FRAMES, UPLOAD_GAP_MARGIN_S, SolidCache, SurfaceLRU, UploadQueue, opaque_bytes,
                       sprite_bytes)
from .tree import OPACITY_VISUAL3, Tree

ROOT_FADE_MS = 340
COMMIT_LOG_EVERY_S = 30.0
PREWARM_STEP_S = 0.002        # one idle wake's share of the curve-table warm-up (at least one table)
HUD_PERIOD_S = 0.25           # NANOD_FPS_HUD: 4 updates a second, never per frame (§6.2)
_HUD_FONTS = {}


def hud_enabled(environ=None) -> bool:
    """``NANOD_FPS_HUD=1`` (§6.2): off by default."""
    return (os.environ if environ is None else environ).get("NANOD_FPS_HUD", "").strip() == "1"


def _hud_font(size: int):
    f = _HUD_FONTS.get(size)
    if f is None:
        from PIL import ImageFont
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:                      # pragma: no cover - Pillow < 10.1
            f = ImageFont.load_default()
        _HUD_FONTS[size] = f
    return f


class StageCore:
    """See the module docstring. ``harvest`` is a ``frames.CompositorHarvest`` or None; ``cpu``
    returns the CPU seconds of every stage thread so far (``win32.ThreadCpu.seconds``) or is None.
    The episode record goes to ``stats`` (FrameStats) only; the core keeps no history of its own."""

    def __init__(self, device, clock: CK.StageClock, *, log=None, stats=None, harvest=None,
                 monotonic=time.monotonic, cpu=None):
        self.device = device
        self.clock = clock
        self.log = log
        self.stats = stats or FR.FrameStats(log=log, clock=monotonic)
        self.harvest = harvest
        self.monotonic = monotonic
        self.cpu = cpu
        self.period = clock.freq / 60.0
        self.rate_hz = None
        self.episodes = AN.Episodes()
        self.display_on = True
        self.last_harvest_s = None
        self.slow_commits = 0
        self._slow_logged = None
        self._fns = None
        self.last_fs = None
        self._ep_cpu0 = self._ep_wall0 = None
        self.reduced_motion = False
        self.surface = None
        self.commits_with_uploads = {}      # batch kind -> Commits that carried uploads (S1: 0 for turn, art)
        self.upload_commit_waits = 0        # upload-carrying Commits sooner than the spacing (they block)

    def _cpu_now(self):
        if self.cpu is None:
            return None
        try:
            return float(self.cpu())
        except Exception:
            return None

    def animation_fns(self):
        if self._fns is None:
            self._fns = self.device.animation_fns()
        return self._fns

    def read_stats(self):
        """GetFrameStatistics (GIL-keeping, G1-1/G1-5); keeps P and the rate current."""
        fs = self.device.frame_statistics()
        if fs.rateNum and fs.rateDen:
            self.period = CK.period_ticks(fs.rateNum, fs.rateDen, self.clock.freq)
            self.rate_hz = fs.rateNum / fs.rateDen
        self.last_fs = fs
        return fs

    def t1(self, not_before=None, margin_s=None):
        """(t1, predicted commit frame) for an event now (G1-6; §4.6.5 item 7). ``not_before``
        (stage ticks): the batch's Commit cannot return before then (S2: an open's upload Commit
        waiting for the spacing), so t1 keeps its margin from that instead of now. ``margin_s``:
        G1-6's adaptive margin (build time, never more than P; the open's, S2), else the fixed one."""
        fs = self.read_stats()
        now = self.clock.now()
        base = now if not_before is None else max(now, int(not_before))
        margin = CK.T1_MARGIN_S if margin_s is None else CK.adaptive_margin(margin_s, self.period / self.clock.freq)
        t1 = CK.t1_for(fs.nextEstimatedFrameTime, base, self.period, margin * self.clock.freq)
        return t1, CK.next_frame_after(fs.lastFrameTime, base, self.period)

    def batch(self, t_wake: float | None = None, not_before=None, margin_s=None) -> AN.Batch:
        t_wake = time.perf_counter() if t_wake is None else t_wake
        t1, fc = self.t1(not_before, margin_s)
        return AN.Batch(self, t1, t_wake=t_wake, predicted_commit=fc)

    def upload_gap_s(self) -> float:
        """S1: the spacing of upload-carrying Commits, two frames of the current P and 1 ms."""
        return UPLOAD_GAP_FRAMES * self.period / self.clock.freq + UPLOAD_GAP_MARGIN_S

    def commit(self, batch: AN.Batch):
        dev = self.device
        pending = getattr(dev, "uploads_pending", 0)
        if pending:
            last = getattr(dev, "last_upload_commit", None)
            now_fn = getattr(dev, "now", None)
            if last is not None and now_fn is not None and now_fn() < last + self.upload_gap_s() - UPLOAD_GAP_MARGIN_S:
                self.upload_commit_waits += 1
        if batch is not None:
            batch.carried = pending
        t0 = time.perf_counter()
        dev.commit()
        ms = (time.perf_counter() - t0) * 1000.0
        if ms > AN.COMMIT_LOG_MS:
            self.slow_commits += 1
            now = self.monotonic()
            if self.log is not None and (self._slow_logged is None or now - self._slow_logged >= COMMIT_LOG_EVERY_S):
                self._slow_logged = now
                try:
                    self.log(f"stage: Commit took {ms:.2f} ms ({self.slow_commits} over 2 ms so far)")
                except Exception:
                    pass

    def finish(self, batch: AN.Batch, kind: str):
        """After a committed batch: episode bookkeeping, the boost and the harvest start."""
        if getattr(batch, "carried", 0):
            self.commits_with_uploads[kind] = self.commits_with_uploads.get(kind, 0) + 1
        started = self.episodes.note(batch, kind)
        if started:
            self._ep_cpu0, self._ep_wall0 = self._cpu_now(), self.monotonic()     # §6.2 cpu_pct_one_core
            try:
                self.episodes.boosted = self.device.boost(True) == 0
            except Exception:
                self.episodes.boosted = False
            if self.harvest is not None and self.display_on:
                try:
                    self.harvest.start()
                except Exception:
                    pass
            self.last_harvest_s = self.monotonic()
        return started

    def next_wake_s(self):
        """Seconds until this core needs a wake (harvest or episode end), or None."""
        if not self.episodes.active:
            return None
        now_t = self.clock.now()
        until_end = (self.episodes.end + self.period - now_t) / self.clock.freq
        until_harvest = FR.HARVEST_PERIOD_S
        if self.last_harvest_s is not None:
            until_harvest = self.last_harvest_s + FR.HARVEST_PERIOD_S - self.monotonic()
        return max(0.0, min(until_end, until_harvest))

    def tick(self):
        """A low-rate wake: harvest every 250 ms of an episode; at its end, the final harvest,
        the unboost and the FrameStats record. Returns the record when an episode ended."""
        if not self.episodes.active:
            return None
        now_s = self.monotonic()
        if self.harvest is not None and (self.last_harvest_s is None or
                                         now_s - self.last_harvest_s >= FR.HARVEST_PERIOD_S):
            try:
                self.harvest.harvest(self.display_on)
            except Exception:
                pass
            self.last_harvest_s = now_s
        if self.episodes.due_end(self.clock.now(), self.period):
            return self.end_episode()
        return None

    def end_episode(self):
        if not self.episodes.active:
            return None
        if self.harvest is not None:
            try:
                self.harvest.harvest(self.display_on)
            except Exception:
                pass
        try:
            self.device.boost(False)
        except Exception:
            pass
        ep = self.episodes.finish()
        rec = {"events": ep["events"], "boosted": ep["boosted"], "rm": self.reduced_motion,
               "work_ms": FR.summary(ep["work_ms"]), "calls": FR.summary(ep["calls"], 1),
               "rate_hz": self.rate_hz, "cpu_pct_one_core": None, "cpu_ms": None,
               "t_start": ep["start"], "t_end": ep["end"]}         # stage ticks: a check places its frames
        cpu0, wall0 = self._ep_cpu0, self._ep_wall0
        self._ep_cpu0 = self._ep_wall0 = None
        cpu1 = self._cpu_now()
        if cpu0 is not None and cpu1 is not None and wall0 is not None:
            wall = max(1e-3, self.monotonic() - wall0)
            used = max(0.0, cpu1 - cpu0)
            rec["cpu_ms"] = round(used * 1000.0, 2)
            rec["cpu_pct_one_core"] = round(100.0 * used / wall, 2)
        verdict = None
        if self.harvest is not None:
            frames, unknown = self.harvest.take()
            changes = FR.ChangeModel(ep.get("batches") or (), self.period)      # S3: the designed holds
            rec.update(FR.episode_from_frames(frames, unknown, ep["start"], ep["end"], self.period,
                                              self.clock.freq, rate_hz=self.rate_hz, changes=changes))
            verdict = FR.judge_stage(rec, self.rate_hz, ep["work_ms"])
        else:
            rec.update({"method": "none", "frames": None})
        return self.stats.record(self.surface or "stage", ep["kind"], rec, verdict)


class SceneContext:
    """What a scene gets: the core (device, clock, batches), its own ``Tree``, the layout, the
    upload queue and the caches, and the open payload's latched flags."""

    def __init__(self, engine, core, tree, layout, surface, payload):
        self.engine = engine
        self.core = core
        self.device = core.device
        self.clock = core.clock
        self.tree = tree
        self.layout = layout
        self.surface = surface
        self.uploads = engine.uploads
        self.solids = engine.solids
        self.lru = engine.lru
        self.reduced_motion = bool(payload.get("reduced_motion", False))     # latched at open (§16)
        self.control_id = payload.get("control_id")
        self.control_min = int(payload.get("control_min") or 0)

    def t0_ticks(self, payload) -> int:
        t0 = payload.get("t0")
        return self.clock.now() if t0 is None else self.clock.from_perf(t0)


class StageEngine:
    """The stage thread's logic (see the module docstring)."""

    def __init__(self, mailbox: Mailbox, scenes: dict, *, device_factory, host_factory, clock_factory,
                 monitor_for, capture_factory=None, stats_reader_factory=None, log=None,
                 monotonic=time.monotonic, opacity_path: str = OPACITY_VISUAL3, role: str = ROLE_CLICK_EATING,
                 policy: DevicePolicy | None = None, frames: FR.FrameStats | None = None, target_key_for=None,
                 prewarmer=None, fps_hud: bool = False, cpu_seconds=None):
        self.mailbox = mailbox
        self.scenes = dict(scenes)
        self.device_factory = device_factory
        self.host_factory = host_factory
        self.clock_factory = clock_factory
        self.monitor_for = monitor_for
        self.capture_factory = capture_factory
        self.stats_reader_factory = stats_reader_factory
        self.target_key_for = target_key_for
        self.log = log
        self.monotonic = monotonic
        self.opacity_path = opacity_path
        self.role = role
        self.policy = policy or DevicePolicy()
        self.frames = frames or FR.FrameStats(log=log, clock=monotonic)
        self.lock = threading.Lock()
        self.device = self.core = self.target = None
        self.uploads = self.solids = self.lru = None
        self.host = None
        self.input = None
        self.capture = None
        self.notices = []
        self.capture_results = []
        self.capture_gen = 0
        self.pending = None           # the open waiting for its frost
        self.scene = None
        self.surface = None
        self.phase = None             # None | 'capturing' | 'open' | 'closing'
        self.ctx = None
        self.tree = None
        self.root = self.root_op = None
        self.frost_surface = None
        self.ambient_image = None
        self.closing = None           # (reason, end_tick)
        self.control_id = None
        self.stopped = False
        self.removed_reason_logged = False
        self.counters = {"opens": 0, "refused_busy": 0, "refused_device": 0, "closes": {}, "device_lost": 0,
                         "com_errors": 0, "capture_timeouts": 0, "positions_applied": 0,
                         "positions_discarded": 0, "clicks": 0, "device_creates": 0, "device_releases": 0,
                         "buffered_calls": 0, "hud_updates": 0}
        self.last_open = None
        self.opening = None
        self._metrics = {}
        self.prewarmer = prewarmer                  # curves.Prewarmer: idle chunks from thread start (R4)
        self.cpu_seconds = cpu_seconds              # win32.ThreadCpu.seconds of every stage thread (§6.2)
        self.fps_hud = bool(fps_hud)                # NANOD_FPS_HUD=1 (§6.2)
        self.hud = None                             # {"visual", "surface", "size", "font", "next"} while open
        self.prime_ms = None                        # S2: the device's first upload Commit, at creation

    def set_cpu_seconds(self, fn):
        """The stage threads' CPU clock (the thread wrapper sets it once both threads exist)."""
        self.cpu_seconds = fn
        if self.core is not None:
            self.core.cpu = fn

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        """Create the host (hidden) and register the system notifications (§4.1)."""
        self.input = HostInput(self.role, self._notice)
        self.host = self.host_factory(self.input)
        try:
            self.host.register_notifications()
        except Exception as exc:
            self._log(f"stage: notification registration failed: {exc!r}")
        if self.capture_factory is not None:
            self.capture = self.capture_factory(self._on_capture)
        self._publish()

    def teardown(self):
        if self.phase is not None:
            self._close_now("sleep", post=False)
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
        self._publish()

    def _log(self, msg):
        if self.log is not None:
            try:
                self.log(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------ inputs from other threads
    def _notice(self, kind):
        self.notices.append((kind, time.perf_counter()))

    def _on_capture(self, result):
        with self.lock:
            self.capture_results.append(result)
        w = self.mailbox.wake
        if w is not None:
            try:
                w()
            except Exception:
                pass

    def _event(self, event, t0=None, **payload):
        """Every event carries ``t0``: the QPC seconds (``time.perf_counter``, VOC-R25) at which
        the stage observed it (a click: when its button-up was handled), so K3 can anchor what
        it triggers (a click's Play legs) to it."""
        payload["t0"] = time.perf_counter() if t0 is None else t0
        self.mailbox.push_event(event, payload)

    # ------------------------------------------------------------------ the loop body
    def process(self):
        """Handle everything pending; return seconds until the next needed wake (None = none)."""
        try:
            self._handle_notices()
            items, positions, touch = self.mailbox.take()
            if touch:
                self._warm("touch")
            for call, payload, _t_post in items:
                self._handle_call(call, payload)
            if positions:
                self._handle_positions(positions)
            with self.lock:
                results, self.capture_results = self.capture_results, []
            for r in results:
                self._handle_capture(r)
            self._handle_timers()
            if self.uploads is not None and self.uploads.busy():
                self._run_uploads()
            if self.hud is not None and self.phase == "open" and self.monotonic() >= self.hud["next"]:
                self._hud_update(commit=True)
        except com.ComError as exc:
            self._com_error(exc)
        except Exception as exc:                          # a scene bug must not kill the stage thread
            self.counters["errors"] = self.counters.get("errors", 0) + 1
            self._log(f"stage: error {exc!r}")
            if self.phase is not None or self.pending is not None or self.opening:
                self._close_now("device")
        self._publish()                                   # the state first: events already went out
        if self._prewarm_now():
            try:
                if not self.prewarmer.step(PREWARM_STEP_S):
                    self._publish()                       # the last table: show it done
            except Exception as exc:
                self._log(f"stage: curve prewarm stopped: {exc!r}")
                self.prewarmer = None
        return self._next_wake()

    def _prewarm_now(self) -> bool:
        """The curve tables are built in idle wakes (WP7a-R4): never while an open waits for its
        frost or an animation episode runs, so neither an open nor a detent waits behind one."""
        if self.prewarmer is None or self.prewarmer.done:
            return False
        if self.pending is not None or self.opening is not None:
            return False
        return self.core is None or not self.core.episodes.active

    def _handle_notices(self):
        notices, self.notices = self.notices, []
        for kind, t_seen in notices:
            if kind == "click_action":
                if self.phase == "open" and self.surface:
                    self.counters["clicks"] += 1
                    self._event("click_action", t0=t_seen, surface=self.surface)
            elif kind in ("lock", "sleep", "motion"):
                self._event("system", t0=t_seen, kind=kind)
            elif kind == "display_off":
                if self.core is not None:
                    self.core.display_on = False
            elif kind == "display_on":
                if self.core is not None:
                    self.core.display_on = True
            elif kind == "display":
                self._event("system", t0=t_seen, kind="display")
                if self.phase is not None or self.pending is not None:
                    self._close_now("display")
                if self.device is not None:
                    self._check_device()
                    if self.core is not None:
                        try:
                            self.core.read_stats()
                        except com.ComError as exc:
                            self._com_error(exc)
            elif kind == "endsession":
                if self.phase is not None or self.pending is not None:
                    self._close_now("sleep", post=False)
                self.stopped = True

    # ------------------------------------------------------------------ device
    def _warm(self, why) -> bool:
        now = self.monotonic()
        if self.device is not None:
            return True
        if not self.policy.want_warm(now):
            return False
        return self._create_device(now, why)

    def _create_device(self, now, why) -> bool:
        try:
            dev = self.device_factory()
        except Exception as exc:
            self.policy.create_failed(now)
            self._log(f"stage: device creation failed ({why}): {exc!r}")
            return False
        self.device = dev
        clock = self.clock_factory(dev)
        reader = None
        if self.stats_reader_factory is not None:
            try:
                reader = self.stats_reader_factory()
            except Exception:
                reader = None
        core = self.core = StageCore(dev, clock, log=self.log, stats=self.frames,
                                     harvest=FR.CompositorHarvest(reader) if reader is not None else None,
                                     monotonic=self.monotonic, cpu=self.cpu_seconds)
        self.uploads = UploadQueue(dev, wake=self.mailbox.wake, gap_s=core.upload_gap_s,
                                   commit=lambda: core.commit(None))            # S1: the upload Commit
        self.solids = SolidCache(dev)
        self.lru = SurfaceLRU(dev)
        self.target = None
        self.policy.created(now)
        self.removed_reason_logged = False              # each loss logs GetDeviceRemovedReason once (§4.3)
        self.counters["device_creates"] += 1
        if clock.begin_mode != CK.BEGIN_ABSOLUTE:
            self._log("stage: timeFrequency != QPF: begin times use the hold fallback (G1-8)")
        try:
            # No curve prewarm here (WP7a-R4): it cost about 0.27 s of pure Python at the first
            # touch or inside a cold open; ``Prewarmer`` builds the tables in idle wakes instead.
            self.core.read_stats()
            self.core.animation_fns()
            prime = getattr(dev, "prime", None)
            if prime is not None:                       # S2: the first upload Commit's ~10 ms, now
                t = time.perf_counter()
                prime()
                self.prime_ms = round((time.perf_counter() - t) * 1000.0, 2)
        except com.ComError as exc:
            self._com_error(exc)
            return False
        return True

    def _check_device(self) -> bool:
        try:
            ok = self.device.check_device_state()
        except Exception:
            ok = False
        if not ok:
            self._device_lost("check_device_state")
        return ok

    def _com_error(self, exc):
        self.counters["com_errors"] += 1
        lost = isinstance(exc, com.DeviceLost)
        if not lost and self.device is not None:
            try:
                lost = not self.device.check_device_state()
            except Exception:
                lost = True
        self._log(f"stage: {exc!r} (device {'lost' if lost else 'ok'})")
        if self.phase is not None or self.pending is not None or self.opening is not None:
            self._close_now("device", release=not lost)
        if lost:
            self._device_lost(repr(exc))

    def _device_lost(self, why):
        """§4.3: close (done by the caller), release in reverse order, log the reason once,
        recreate at most twice 1 s apart (the policy's wakes)."""
        self.counters["device_lost"] += 1
        if self.phase is not None or self.pending is not None or self.opening is not None:
            self._close_now("device", release=False)
        if self.device is not None and not self.removed_reason_logged:
            try:
                self._log(f"stage: device lost ({why}); GetDeviceRemovedReason "
                          f"{com.hx(self.device.removed_reason())}")
            except Exception:
                pass
            self.removed_reason_logged = True
        self._release_device()
        self.policy.lost(self.monotonic())

    def _release_device(self):
        if self.device is None:
            return
        for cache in (self.solids, self.lru):
            try:
                if cache is not None:
                    cache.release()
            except Exception:
                pass
        try:
            self.device.teardown()
        except Exception:
            pass
        self.counters["device_releases"] += 1
        self.device = self.core = self.target = None
        self.uploads = self.solids = self.lru = None

    # ------------------------------------------------------------------ calls
    def _handle_call(self, call, payload):
        surface = CALL_SURFACE.get(call)
        capturing = self.pending is not None and surface == self.pending["surface"]
        if "control_id" in payload:
            if self.phase is not None and surface == self.surface:
                self.control_id = payload["control_id"]
            elif capturing and not call.endswith("_open"):
                self.pending["control_id"] = payload["control_id"]
        if call.endswith("_open"):
            self._open(call, payload)
        elif call.endswith("_close"):
            self._close(call, payload)
        elif capturing:
            self._buffer(call, payload)
        else:
            self._update(call, payload)

    def _buffer(self, call, payload):
        """WP7a-R1: an update for the surface whose open is still capturing (≈ 50 ms warm, up to
        the 500 ms timeout) is kept, not dropped: K3 re-enters the knob at once (K3 §5.3.1) and
        sends ``state`` / ``count`` / ``items`` only when they change (K3 §11.1), so a dropped
        patch is never re-sent. Highlights coalesce at the tail (``merge_highlight``); sources and
        row patches stay in order. ``_finish_open`` applies them in the open's own batch."""
        ups = self.pending["updates"]
        if call.endswith("_highlight") and ups and ups[-1][0] == call:
            ups[-1] = (call, merge_highlight(ups[-1][1], payload))
        else:
            ups.append((call, dict(payload)))
        self.counters["buffered_calls"] += 1

    def _refuse(self, surface, reason, why):
        self.counters["refused_" + reason] += 1
        self._log(f"stage: {surface} refused ({reason}): {why}")
        self._event("refused", surface=surface, reason=reason)

    def _open(self, call, payload):
        """§4.9 t = 0: the capture is submitted **first**, so a cold device (≈ 134 ms, GIL
        released) is created in parallel with it (WP7a-R4); a failed device drops the capture by
        generation and refuses the open."""
        t_open = time.perf_counter()
        surface = CALL_SURFACE[call]
        if self.phase is not None or self.pending is not None:
            return self._refuse(surface, REFUSE_BUSY, f"{self.surface or self.pending['surface']} is open")
        factory = self.scenes.get(surface)
        if factory is None:
            return self._refuse(surface, REFUSE_DEVICE, "no scene registered")
        mon = self.monitor_for(payload.get("foreground_hwnd"))
        if not mon:
            return self._refuse(surface, REFUSE_DEVICE, "no monitor")
        if isinstance(mon, dict):
            rect, device_name, dpi = mon["rect"], mon.get("device"), mon.get("dpi")
        else:
            rect, device_name, dpi = mon, None, None
        layout = StageLayout(rect)
        recipe = B.RECIPES[B.SURFACE_RECIPE[surface]]
        amb = None
        try:
            amb = factory.ambient_source(payload) if hasattr(factory, "ambient_source") else None
        except Exception:
            amb = None
        self.capture_gen += 1
        gen = self.capture_gen
        submitted = False
        if self.capture is not None:
            from .capture import CaptureJob
            job = CaptureJob(gen, layout.monitor, recipe, layout.k, self.mailbox.exclusions, amb)
            submitted = bool(self.capture.submit(job))
        deadline = self.monotonic() + B.CAPTURE_TIMEOUT_S           # from the submit (§4.9 t = 0)
        cold = self.device is None
        t_dev = time.perf_counter()
        why = None
        if not self._warm("open"):
            why = "no device"
        elif not self._check_device():
            why = "device lost"
        if why is not None:
            self.capture_gen += 1                                     # its result is dropped
            return self._refuse(surface, REFUSE_DEVICE, why)
        device_ms = round((time.perf_counter() - t_dev) * 1000, 2) if cold else 0.0
        self.pending = {"surface": surface, "call": call, "payload": payload, "layout": layout, "recipe": recipe,
                        "device_name": device_name, "dpi": dpi, "gen": gen, "deadline": deadline,
                        "factory": factory, "t_open": t_open, "ambient_source": amb, "cold": cold,
                        "device_ms": device_ms, "control_id": payload.get("control_id"),
                        "updates": [], "positions": {}}
        self.counters["opens"] += 1
        self.policy.scene_opened(self.monotonic())
        if not submitted:
            self._finish_open(None)

    def _handle_capture(self, result):
        if self.pending is None or result.gen != self.pending["gen"]:
            return
        self._finish_open(result)

    def _finish_open(self, result):
        p, self.pending = self.pending, None
        layout, recipe, surface, payload = p["layout"], p["recipe"], p["surface"], p["payload"]
        self.opening = surface
        if self.core.harvest is not None and self.target_key_for is not None and p.get("device_name"):
            try:
                self.core.harvest.reader.target_key = self.target_key_for(p["device_name"])
            except Exception:
                pass
        frost_img = result.frost if result is not None and result.frost is not None else None
        if frost_img is None:
            frost_img, _src = B.frost(None, recipe, layout.k, (layout.W, layout.H))
        dev = self.device
        w, h, data = opaque_bytes(frost_img)
        self.frost_surface = dev.create_surface(w, h, True, "frost")
        dev.upload(self.frost_surface, w, h, data, "frost")
        self.ambient_image = result.ambient if result is not None else None
        tree = Tree(dev, self.opacity_path)
        root = tree.root("root")
        root_op = tree.opacity(root, 0.0)
        frost_v = tree.visual("frost", content=self.frost_surface)
        sc, dx, dy = B.frost_placement(recipe)
        tree.matrix(frost_v, sc, sc, dx, dy)
        tree.add(root, frost_v)
        container = tree.visual("scene")
        tree.add(root, container)
        self.tree, self.root, self.root_op = tree, root, root_op
        ctx = SceneContext(self, self.core, tree, layout, surface, payload)
        ctx.ambient_image = self.ambient_image
        ctx.recipe = recipe
        cid = p.get("control_id", payload.get("control_id"))          # the newest, if one came while capturing
        ctx.control_id = cid
        self.ctx = ctx
        self.core.surface = surface
        self.core.reduced_motion = ctx.reduced_motion
        scene = p["factory"](ctx, payload)
        scene.build(payload, container)
        if self.fps_hud:
            self._hud_build(tree, root, layout, dev)
        if self.target is None:
            self.target = dev.create_target(self.host.hwnd)
        dev.set_root(self.target, root.ptr)
        up_n, up_bytes = getattr(dev, "uploads_pending", 0), getattr(dev, "upload_bytes_pending", 0)
        not_before = self._open_not_before(dev)
        # S2: the open's batch (about 600 calls, its Commit carrying the frost and the build's
        # sprites) takes 1.4-5 ms from here to its Commit's return (hidden-host probe; 3.2-4.8 ms p50
        # on screen), past G1-6's fixed 1.5 ms: its t1 keeps G1-6's largest adaptive margin, P, so
        # the first frame that can show the open is its t1 (no lost leading vblanks)
        batch = self.core.batch(not_before=not_before, margin_s=self.core.period / self.core.clock.freq)
        t1_lead_ms = round(self.core.clock.ms(batch.t1 - self.core.clock.now()), 3)
        batch.to(root_op, 1.0, ROOT_FADE_MS, "OUT", v_from=0.0, force=True)
        scene.open(batch, payload)
        applied = self._replay_capture_window(scene, batch, p, cid, ctx)       # WP7a-R1
        batch.commit()
        self.core.finish(batch, "open")
        self.scene, self.surface, self.phase = scene, surface, "open"
        self.control_id = cid
        self.input.expected_dpi = p.get("dpi")                       # WP7a-R5: our own move is no display change
        self.host.show(layout.monitor)
        self.input.set_hit_rect(scene.hit_rect())
        self.opening = None
        t0 = payload.get("t0")
        self.last_open = {"surface": surface, "frost": (result.source if result is not None and result.frost
                                                        is not None else "tint_only"),
                          "capture_ms": getattr(result, "capture_ms", None),
                          "build_ms": getattr(result, "build_ms", None),
                          "cold": p.get("cold", False), "device_ms": p.get("device_ms"),
                          "open_ms": round((time.perf_counter() - p["t_open"]) * 1000, 2),
                          "t0_to_commit_ms": round((time.perf_counter() - t0) * 1000, 2) if t0 else None,
                          "buffered": applied, "calls": batch.calls,
                          # S2: what the open's Commit carried, its cost, and t1's lead when the batch
                          # was opened (pushed past the upload Commit's spacing and copies: not_before)
                          "uploads": up_n, "upload_bytes": up_bytes,
                          "commit_ms": round(batch.commit_ms, 3) if batch.commit_ms is not None else None,
                          "t1_lead_ms": t1_lead_ms, "t1_pushed": not_before is not None,
                          "t1_after_commit_ms": (round(self.core.clock.ms(batch.t1 - self.core.clock.from_perf(
                              batch.t_done)), 3) if batch.t_done is not None else None)}
        self._event("opened", surface=surface)

    def _open_not_before(self, dev):
        """S2: flush the open's uploads (the frost, the ambient layer, the build's prepared sprites:
        their copies start now, not at the Commit) and return the stage tick before which the open's
        upload-carrying Commit cannot return, so t1 keeps its margin from then: two frames after the
        device's previous upload Commit (it blocks until then; a cold open right after ``prime``, or
        a queue upload just before the capture landed). None: it will not wait. (The on-screen tours
        showed no leading gap on warm opens whose Commit carried the build's uploads, so t1 is not
        pushed for the copies themselves.)"""
        if not getattr(dev, "uploads_pending", 0):
            return None
        flush = getattr(dev, "flush", None)
        if flush is not None:
            flush()
        last = getattr(dev, "last_upload_commit", None)
        now_fn = getattr(dev, "now", None)
        if last is None or now_fn is None:
            return None
        at = last + self.core.upload_gap_s() - UPLOAD_GAP_MARGIN_S
        if at <= now_fn():
            return None
        return self.core.clock.from_perf(at)

    def _replay_capture_window(self, scene, batch, p, cid, ctx) -> dict:
        """Apply what arrived while the open captured, in the open's batch before its Commit:
        the buffered calls in order, then the newest fast-path position of the current control
        (older control ids are discarded, §5.3; a swapping scene records, not presents)."""
        n_calls = 0
        for call, up in p.get("updates") or ():
            scene.update(batch, call, up)
            n_calls += 1
        applied = discarded = 0
        positions = p.get("positions") or {}
        if positions:
            now = self.core.clock.now()
            for pcid, (pos, _t_read) in positions.items():
                if pcid != cid or scene.swapping(now):
                    discarded += 1
                    continue
                scene.position(batch, int(pos) - ctx.control_min)
                applied += 1
        self.counters["positions_applied"] += applied
        self.counters["positions_discarded"] += discarded
        return {"calls": n_calls, "positions": applied, "positions_discarded": discarded}

    def _update(self, call, payload):
        surface = CALL_SURFACE.get(call)
        if self.phase != "open" or surface != self.surface:
            return
        batch = self.core.batch()
        self.scene.update(batch, call, payload)
        if batch.calls:
            batch.commit()
            kind = ("switch" if call == "explorer_source" else
                    "shuffle" if payload.get("reason") == "shuffle" else "turn")
            self.core.finish(batch, kind)
        self.input.set_hit_rect(self.scene.hit_rect())

    def _handle_positions(self, positions):
        """§5.3: index = p − control_min for the current control; older control ids discarded;
        recorded, not presented, while the scene swaps (a switch, a shuffle) or plays. While an
        open is capturing, the newest position per control id waits for it (WP7a-R1)."""
        if self.phase is None and self.pending is not None:
            self.pending["positions"].update(positions)
            return
        if self.phase != "open" or self.scene is None:
            self.counters["positions_discarded"] += len(positions)
            return
        now = self.core.clock.now()
        for cid, (p, _t_read) in positions.items():
            if cid != self.control_id or self.scene.swapping(now):
                self.counters["positions_discarded"] += 1
                continue
            batch = self.core.batch()
            self.scene.position(batch, int(p) - self.ctx.control_min)
            if batch.calls:
                batch.commit()
                self.core.finish(batch, "turn")
            self.counters["positions_applied"] += 1

    def _close(self, call, payload):
        surface = CALL_SURFACE[call]
        reason = payload.get("reason")
        if self.pending is not None and self.pending["surface"] == surface:
            self.pending = None
            self.policy.scene_closed(self.monotonic())
            self._count_close(reason)
            self._event("closed", surface=surface, reason=reason)
            return
        if self.phase is None or surface != self.surface:
            return
        if self.phase == "closing":
            if reason not in ANIMATED_CLOSES:
                self._close_now(reason)
            return
        if reason not in ANIMATED_CLOSES:
            return self._close_now(reason)
        batch = self.core.batch()
        if reason == "play":
            self.scene.close(batch, payload)
            t0 = self.ctx.t0_ticks(payload)
            batch.to(self.root_op, 0.0, ROOT_FADE_MS, "OUT", anchor=t0, delay_ms=float(payload.get("close_at_ms") or 0),
                     force=True)
        else:
            batch.to(self.root_op, 0.0, ROOT_FADE_MS, "OUT", force=True)
        batch.commit()
        self.core.finish(batch, "play" if reason == "play" else "close")
        self.phase = "closing"
        self.closing = (reason, self.root_op.func.end_tick or batch.t1)
        self.input.set_hit_rect(None)

    def _count_close(self, reason):
        self.counters["closes"][reason] = self.counters["closes"].get(reason, 0) + 1

    def _close_now(self, reason, *, post: bool = True, release: bool = True):
        """Instant close (§15; S5-26): hide in this wake, release, post ``closed``. An open that
        failed while it was being built is answered with ``refused(device)`` instead."""
        failed_open, self.opening = self.opening, None
        surface = self.surface or (self.pending["surface"] if self.pending else None) or failed_open
        self.pending = None
        if self.host is not None:
            try:
                self.host.hide()
            except Exception:
                pass
        if self.input is not None:
            self.input.set_hit_rect(None)
            self.input.expected_dpi = None
        if release and self.device is not None:
            try:
                if self.target is not None:
                    self.device.set_root(self.target, None)
                self.device.commit()
            except com.ComError:
                release = False
        if self.core is not None:
            try:
                self.core.end_episode()
            except Exception:
                pass
        if self.scene is not None:
            try:
                self.scene.release()
            except Exception:
                pass
        if release and self.tree is not None:
            try:
                self.tree.release_all()
                if self.frost_surface:
                    self.device.release(self.frost_surface)
                if self.hud is not None and self.hud.get("surface"):
                    self.device.release(self.hud["surface"])
            except Exception:
                pass
        self.scene = self.tree = self.root = self.root_op = self.ctx = None
        self.frost_surface = None
        self.hud = None
        was_open = self.phase is not None or surface is not None
        self.phase = None
        self.closing = None
        self.surface = None
        self.policy.scene_closed(self.monotonic())
        if failed_open is not None and self.phase is None:
            self.counters["refused_device"] += 1
            if post:
                self._event("refused", surface=failed_open, reason=REFUSE_DEVICE)
        elif surface is not None and was_open:
            self._count_close(reason)
            if post:
                self._event("closed", surface=surface, reason=reason)

    # ------------------------------------------------------------------ timers
    def _handle_timers(self):
        now_s = self.monotonic()
        if self.pending is not None and now_s >= self.pending["deadline"]:
            self.counters["capture_timeouts"] += 1
            self.capture_gen += 1                          # a late result is dropped
            self._finish_open(None)
        if self.phase == "closing" and self.closing is not None and self.core is not None:
            reason, end = self.closing
            if self.core.clock.now() >= end + self.core.period:          # one frame after the twin reaches 0
                self._close_now(reason)
        if self.core is not None:
            self.core.tick()
        if self.device is None and self.policy.recreate_due(now_s):
            self._create_device(now_s, "recreate")
        if self.device is not None and self.policy.release_due(now_s):
            self._log("stage: device released after 600 s without a scene")
            self._release_device()
            self.policy.released(now_s)

    def _run_uploads(self):
        """S1 (the module docstring): first the reveal of what ripened (the scene swaps the content
        in with the animation that reveals it, §4.4, in one bind-only batch), then, when the pacing
        allows, one upload wake (at most 4 ms and 2.5 MB, §4.5) with its own upload Commit."""
        up = self.uploads
        landed = up.ripen()
        if landed and self.phase == "open" and hasattr(self.scene, "uploads_ready"):
            batch = self.core.batch()
            self.scene.uploads_ready(batch, list(landed))
            if batch.calls:
                batch.commit()
                self.core.finish(batch, "art")
        if up.due():
            up.upload()

    def _next_wake(self):
        waits = []
        now_s = self.monotonic()
        if self.pending is not None:
            waits.append(self.pending["deadline"] - now_s)
        if self.core is not None:
            w = self.core.next_wake_s()
            if w is not None:
                waits.append(w)
            if self.phase == "closing" and self.closing is not None:
                waits.append((self.closing[1] + self.core.period - self.core.clock.now()) / self.core.clock.freq)
        if self.uploads is not None:
            w = self.uploads.next_wake_s()                # ticks at once; ripening; the paced upload wake
            if w is not None:
                waits.append(w)
        if self.hud is not None and self.phase == "open":
            waits.append(self.hud["next"] - now_s)
        if self._prewarm_now():
            waits.append(0.0)                   # the next table at once, after a message pump
        pw = self.policy.next_wake()
        if pw is not None:
            waits.append(pw - now_s)
        return max(0.0, min(waits)) if waits else None

    # ------------------------------------------------------------------ the FPS HUD (§6.2)
    def _hud_build(self, tree, root, layout, dev):
        """``NANOD_FPS_HUD=1``: a small text sprite at the stage's top-left, above the scene and
        under the root fade; drawn now so it opens with the scene, then 4 times a second."""
        w, h = layout.u(440), layout.u(44)
        font = _hud_font(max(10, layout.u(13)))
        surf = dev.create_surface(w, h, False, "hud")
        v = tree.visual("hud", content=surf)
        tree.offset(v, layout.sx0 + layout.u(16), layout.sy0 + layout.u(16))
        tree.add(root, v)
        self.hud = {"visual": v, "surface": surf, "size": (w, h), "font": font, "line": layout.u(18),
                    "pad": layout.u(6), "next": 0.0}
        self._hud_update(commit=False)

    def _hud_text(self):
        surface = self.surface or (self.pending or {}).get("surface") or self.opening or "stage"
        rate = self.core.rate_hz if self.core is not None else None
        last = (self.frames.metrics().get(surface) or {}).get("last") or {}
        head = f"{surface} · {rate:.0f} Hz" if rate else f"{surface}"
        if not last:
            return head + " · no episode yet", ""
        iv = last.get("interval_P") or {}
        wk = last.get("work_ms") or {}
        verdict = {True: "pass", False: "MISS", None: "n/a"}[last.get("pass")]
        line1 = (f"{head} · {last.get('kind')} · {last.get('fps')} fps · p95 {iv.get('p95')} P · "
                 f"max {iv.get('max')} P · missed {last.get('missed')}")
        line2 = (f"work p95 {wk.get('p95')} ms · cpu {last.get('cpu_pct_one_core')} % · "
                 f"unknown {last.get('unknown')} · {verdict}")
        return line1, line2

    def _hud_update(self, *, commit: bool):
        from PIL import Image, ImageDraw
        hud = self.hud
        if commit and self.uploads is not None:
            left = self.uploads.gap_left()
            if left > 0.0:                                 # S1: its upload Commit waits for the spacing
                hud["next"] = self.monotonic() + left
                return
        w, h = hud["size"]
        img = Image.new("RGBA", (w, h), (0, 0, 0, 150))
        d = ImageDraw.Draw(img)
        pad = hud["pad"]
        for i, text in enumerate(self._hud_text()):
            if text:
                d.text((pad, pad // 2 + i * hud["line"]), text, fill=(255, 255, 255, 255), font=hud["font"])
        sw, sh, data = sprite_bytes(img)
        self.device.upload(hud["surface"], sw, sh, data, "hud")
        if commit:
            self.core.commit(None)
        hud["next"] = self.monotonic() + HUD_PERIOD_S
        self.counters["hud_updates"] += 1

    # ------------------------------------------------------------------ metrics
    def _publish(self):
        m = {"state": self.phase or ("capturing" if self.pending else "idle"), "surface": self.surface,
             "device": dict(getattr(self.device, "info", {}) or {}) if self.device is not None else None,
             "policy": self.policy.state, "counters": {k: (dict(v) if isinstance(v, dict) else v)
                                                       for k, v in self.counters.items()},
             "last_open": self.last_open,
             "prewarm": ({"done": self.prewarmer.done, "built": self.prewarmer.built, "steps": self.prewarmer.steps}
                         if self.prewarmer is not None else None),
             "uploads": dict(self.uploads.stats) if self.uploads is not None else None,
             "slow_commits": self.core.slow_commits if self.core is not None else 0,
             "begin_mode": self.core.clock.begin_mode if self.core is not None else None,
             # S1/S2: Commits that carried uploads, by batch kind (0 for turn and art), upload-carrying
             # Commits sooner than the spacing (they block on the native device), the device's prime
             "commits_with_uploads": dict(self.core.commits_with_uploads) if self.core is not None else {},
             "upload_commit_waits": self.core.upload_commit_waits if self.core is not None else 0,
             "prime_ms": self.prime_ms}
        with self.lock:
            self._metrics = m

    def metrics(self):
        with self.lock:
            m = dict(self._metrics)
        m["frames"] = self.frames.metrics()
        return m


# =========================================================================== the thread
def _default_monitor_for(hwnd):
    """§0.3: the monitor of the foreground window at the press (K3 sends ``foreground_hwnd``)."""
    from . import win32 as W
    return W.monitor_info(W.MonitorFromWindow(hwnd, W.MONITOR_DEFAULTTOPRIMARY)) if hwnd else W.foreground_monitor()


class StageThread:
    """``NanoD-stage``: the engine on its own Win32 thread (Windows). If the thread cannot start,
    the stage is disabled, the reason is logged and every open is refused with ``device`` (§4.1).

    ``host_hidden_only`` and ``capture_grab`` exist for headless tests: the host then refuses to
    show (an open ends in ``refused(device)`` after its whole build, commit included) and the
    capture never reads the screen."""

    def __init__(self, scenes: dict, *, log=None, role=ROLE_CLICK_EATING, opacity_path=OPACITY_VISUAL3,
                 start: bool = True, name: str = "NanoD-stage", host_hidden_only: bool = False, capture_grab=None,
                 _fail_start: bool = False):
        self.scenes = dict(scenes)
        self.log = log
        self.role = role
        self.opacity_path = opacity_path
        self.host_hidden_only = host_hidden_only
        self.capture_grab = capture_grab
        self._fail_start = _fail_start
        self.mailbox = Mailbox(wake=self._set_event)
        self.engine = None
        self.disabled = None
        self._event = None
        self._cpu = None
        self._stop = False
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        if start:
            self._thread.start()
            self._ready.wait(5.0)

    def _set_event(self):
        ev = self._event
        if ev:
            from . import win32 as W
            W.SetEvent(ev)

    def _run(self):
        import ctypes as C
        try:
            from . import win32 as W
            from .capture import StageCaptureWorker
            from .device import NativeDevice
            from .host import HostWindow, pump_messages
            if self._fail_start:
                raise RuntimeError("start failure (test)")
            W.SetThreadDpiAwarenessContext(W.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            W.SetThreadPriority(W.GetCurrentThread(), W.THREAD_PRIORITY_ABOVE_NORMAL)
            self._event = W.CreateEventW(None, False, False, None)
            engine = StageEngine(
                self.mailbox, self.scenes,
                device_factory=lambda: NativeDevice(W.foreground_monitor()["hmonitor"]),
                host_factory=lambda handler: HostWindow(handler, hidden_only=self.host_hidden_only),
                clock_factory=lambda dev: CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc),
                monitor_for=_default_monitor_for,
                capture_factory=lambda cb: StageCaptureWorker(cb, grab=self.capture_grab),
                stats_reader_factory=lambda: FR.NativeStatsReader(_target_key()),
                target_key_for=W.adapter_for_display,
                log=self.log, opacity_path=self.opacity_path, role=self.role,
                prewarmer=CV.Prewarmer(), fps_hud=hud_enabled())
            engine.start()
            try:                                                   # §6.2 cpu_pct_one_core: both stage threads
                self._cpu = W.ThreadCpu([threading.get_native_id(), getattr(engine.capture, "native_id", None)])
                engine.set_cpu_seconds(self._cpu.seconds)
            except Exception as exc:
                self._cpu = None
                if self.log is not None:
                    self.log(f"stage: no thread CPU times: {exc!r}")
            self.engine = engine
        except Exception as exc:
            self.disabled = repr(exc)
            if self.log is not None:
                try:
                    self.log(f"stage: disabled: {exc!r}")
                except Exception:
                    pass
            self._ready.set()
            self._refuse_forever()
            return
        self._ready.set()
        handles = (C.c_void_p * 1)(self._event)
        try:
            while not self._stop and not engine.stopped:
                if pump_messages(W) < 0:
                    break
                timeout = engine.process()
                if self._stop or engine.stopped:
                    break
                ms = W.INFINITE if timeout is None else max(0, int(timeout * 1000.0 + 0.999))
                if ms == 0:
                    continue
                W.MsgWaitForMultipleObjectsEx(1, handles, ms, W.QS_ALLINPUT, W.MWMO_INPUTAVAILABLE)
        finally:
            try:
                engine.teardown()
            finally:
                if self._cpu is not None:
                    self._cpu.close()
                    engine.set_cpu_seconds(None)
                W.CloseHandle(self._event)
                self._event = None

    def _refuse_forever(self):
        """A disabled stage answers every open with ``refused(device)`` from the Tk thread."""
        mb = self.mailbox
        original = mb.post

        def post(call, payload):
            if call.endswith("_open"):
                mb.push_event("refused", {"surface": CALL_SURFACE.get(call), "reason": REFUSE_DEVICE,
                                          "t0": time.perf_counter()})
                return False
            return original(call, payload)
        mb.post = post

    def metrics(self):
        if self.engine is None:
            return {"state": "disabled" if self.disabled else "starting", "disabled": self.disabled}
        return self.engine.metrics()

    def close(self, timeout: float = 2.0) -> bool:
        self._stop = True
        with self.mailbox.lock:
            self.mailbox.closed = True
        self._set_event()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread.is_alive()


def _target_key():
    from . import win32 as W
    mon = W.foreground_monitor()
    return W.adapter_for_display(mon["device"]) if mon else None
