"""The desktop art pipeline for the music scenes (DESKTOP_STAGE §13; §4.5, §4.7.3, §7.5, §7.7, §8.4,
§8.6, §12; [G1] G1-5).

``ArtService`` owns the workers ``NanoD-art-1``, ``NanoD-art-2`` and ``NanoD-art-fast`` (all
``THREAD_PRIORITY_BELOW_NORMAL``; the lanes below).
The stage thread never waits on it: a scene hands over a **snapshot** of what it shows (its focus,
the preload window, the items) with ``plan(owner, planner, snapshot)`` (a dict assignment and a
notify), and a worker turns the newest snapshot into jobs (newest wins; jobs of items that left
the window are dropped, §13.4 item 1). Each job produces premultiplied BGRA bytes that go to the
stage's ``UploadQueue`` (the stage uploads them within its 4 ms per-wake budget, §4.5) and land in
the device's surface LRU; the engine then calls the scene's ``uploads_ready`` with the keys.

Delayed work is a job with ``not_before`` (a worker waits for it): the ambient's 200 ms debounce
(§7.5), the Up next big cover's 120 ms debounce (§8.4, a 1 x 1 "tick" upload that wakes the
scene), the sharpen pass 150 ms after the rows settle (§8.6). No timer runs on the stage thread.

**Two lanes (WP8-R1).** A running job is never interrupted, and a cover fetch blocks its worker
for as long as ``CoverStore`` allows (seconds on a slow CDN, 8 s at most). So the jobs that must
land on time never share a worker with network I/O: every job carries a ``lane``.

- ``LANE_ART``: the art elements (L1, L0, the big cover, the row leads): C2, fetch, decode,
  sleeves. ``NanoD-art-1`` and ``NanoD-art-2`` run them; when neither has an art job due, they
  also help with the fast lane.
- ``LANE_FAST`` (the default): the ticks, the ambient builds, the labels, row and column text,
  the loading tiles, the sharpen sprites and the statics. ``NanoD-art-fast`` (same priority,
  ``BELOW_NORMAL``) runs only this lane and the plans, and never does network I/O, so a tick lands
  within one fast-lane job (<= ~7 ms, the sharpen sprite) of its ``not_before`` whatever the
  fetches do.
- **CPU slots.** At most ``workers`` (2) jobs compute at once, the two art workers' budget of
  §2.2, so the input path meets no more GIL traffic than with two threads: a job takes a slot when
  a worker picks it and holds it while it runs, except a tick (a 1 x 1 sprite, no slot) and
  except while a fetch waits on the network (the slot is given back around ``CoverStore.fetch``
  and taken again, ahead of new jobs, for the decode). A worker never blocks on a slot: without
  one it takes only ticks, so a tick is never late behind a slot, and a label waits at most one art
  job's CPU phase (<= 20 ms, §13.4), never a download.

A running art job is cancelled (``CoverStore.fetch(cancelled=...)``, polled per 16 KB chunk and
while waiting for another worker's download of the same rung) when its owner's next plan no
longer wants it (the item left the window, §13.4 item 1) or its scene closed; a cancelled fetch is
not a failure (no 30 s back-off).

Caches (§13.3): C1 is WP6's ``artwork.CoverStore`` (encoded rungs, 24 MB); C2 here keeps the
prepared element images as JPEG q 92 (32 MB) so a re-show costs a ~1 ms decode; the 64 px
thumbnails the ambient is built from (§12) and the dominant colours (for ``art.extended``) are
kept per art key. No decoded bitmaps are kept beyond that.

Sources: ``https`` Apple templates and Sonos ``/getaa`` through ``CoverStore`` (its allowlist,
bounds and cancellation); ``simulation://art/...`` templates are drawn by ``SimulatedCovers``
(the simulator's covers load, so scenes do not sit in ``loading``); ``simulation://loading/...``
never arrives (the simulator's ``art = loading`` state). URLs are never logged.

GIL (§4.7.3, G1-5): decode (with ``draft``), ``reduce``, ``resize``, ``GaussianBlur``,
``transform``, masked ``paste``, JPEG encode and ``tobytes`` release the GIL; text is drawn one
glyph at a time; nothing here calls ``alpha_composite``.
"""
from __future__ import annotations

import hashlib
import io
import itertools
import threading
import time
from collections import OrderedDict

from PIL import Image

from ... import render_music as RM
from ... import scene_music as SM

C2_BYTES = 32 * 1024 * 1024
C2_QUALITY = 92
THUMBS_MAX = 512
WORKERS = 2
LANE_ART, LANE_FAST = "art", "fast"
SIZES_MAX = 4096
_PRIO_TICK, _PRIO_FOCUS, _PRIO_NEAR, _PRIO_FAR = 0, 1, 2, 3


def rank(prio) -> int:
    """An upload priority (an int for ``UploadQueue``) from a job priority tuple."""
    if isinstance(prio, tuple):
        out = 0
        for j, v in enumerate(prio[:4]):
            out = out * 100 + min(99, max(0, int(v)))
        return out * (100 ** (4 - min(4, len(prio))))
    return int(prio)


def _log_safe(log, msg):
    if log is not None:
        try:
            log(msg)
        except Exception:
            pass


class Never(Exception):
    """A source that never arrives (``simulation://loading/``)."""


class _Dropped(Exception):
    """A job cancelled before it ran."""


def _is_tick(job) -> bool:
    return isinstance(job.key, tuple) and bool(job.key) and job.key[0] == "tick"


def _is_cancel(exc) -> bool:
    """A fetch stopped by its job's cancellation (``artwork.ArtworkCancelled``): not a failure."""
    try:
        from ...artwork import ArtworkCancelled
    except Exception:                                   # pragma: no cover - artwork always imports
        return False
    return isinstance(exc, ArtworkCancelled)


class SimulatedCovers:
    """Covers for ``simulation://art/<id>/{w}x{h}bb.jpg`` templates: a deterministic drawn cover
    at the requested rung (capped at ``art_max``), so the simulator's art states resolve
    (full, and 400 / 300 px sources that draw ``art.extended``). With the prototype's covers on
    disk (a dev checkout) the item's album cover is used instead, by title."""

    def __init__(self, covers_dir=None):
        self.covers_dir = covers_dir
        self._files = None

    def _prototype(self, title):
        import os
        if self.covers_dir is None:
            return None
        if self._files is None:
            try:
                self._files = {f.lower(): os.path.join(self.covers_dir, f) for f in os.listdir(self.covers_dir)}
            except OSError:
                self._files = {}
        want = "".join(c for c in (title or "").lower() if c.isalnum())[:8]
        if not want:
            return None
        for name, path in self._files.items():
            if "".join(c for c in name if c.isalnum()).startswith(want):
                try:
                    return Image.open(path).convert("RGB")
                except Exception:
                    return None
        return None

    def draw(self, template: str, rung: int, art_max: int, item: dict):
        edge = max(16, min(int(rung), int(art_max or rung)))
        img = self._prototype(item.get("album") or item.get("title"))
        if img is not None:
            return RM.fit_square(img, edge)
        ident = template.split("/")[3] if template.count("/") >= 3 else template
        h = hashlib.sha1(ident.encode("utf-8")).digest()
        bg = RM.rgb_of(item.get("art_bg") or ((h[0] << 16) | (h[1] << 8) | h[2]))
        c2 = tuple(min(255, int(v * 0.35 + 150 * (j == h[3] % 3))) for j, v in enumerate(bg))
        img = RM.linear_gradient_160(edge, (bg[0] << 16) | (bg[1] << 8) | bg[2], (c2[0] << 16) | (c2[1] << 8) | c2[2])
        r = edge * (0.18 + (h[4] % 20) / 100.0)
        cx, cy = edge * (0.3 + (h[5] % 40) / 100.0), edge * (0.3 + (h[6] % 40) / 100.0)
        small = max(8, edge // 8)                        # a disc drawn small, then resized (GIL)
        mask = Image.new("L", (small, small), 0)
        from PIL import ImageDraw
        f = small / float(edge)
        ImageDraw.Draw(mask).ellipse(((cx - r) * f, (cy - r) * f, (cx + r) * f, (cy + r) * f), fill=64)
        RM.over_mask(img, mask.resize((edge, edge), Image.Resampling.BILINEAR), (255, 255, 255))
        return img


class Job:
    """One unit of worker work. ``lane``: ``LANE_FAST`` (default; never network I/O) or
    ``LANE_ART`` (may fetch). ``cancelled`` is set by the service when the job, already running,
    is no longer wanted; a fetch inside it polls that flag."""
    __slots__ = ("key", "prio", "fn", "owner", "not_before", "seq", "opaque", "uploads", "done", "tag", "lane",
                 "cancelled", "slot")

    def __init__(self, key, prio, fn, *, owner=None, not_before=0.0, opaque=True, uploads=None, done=None, tag=None,
                 lane=LANE_FAST):
        self.key, self.fn, self.owner = key, fn, owner
        self.prio = prio if isinstance(prio, tuple) else (int(prio),)
        self.not_before, self.opaque, self.uploads, self.done, self.tag = not_before, opaque, uploads, done, tag
        self.lane = lane
        self.cancelled = False
        self.slot = False
        self.seq = 0


class ArtService:
    """See the module docstring. ``sync=True`` (tests) runs nothing on its own: ``run_pending``
    processes due jobs on the caller's thread, and ``clock`` may be a fake."""

    def __init__(self, *, cover_store=None, speaker_hosts=None, simulated=None, workers=WORKERS, sync=False,
                 log=None, clock=time.perf_counter, keep_images=False, fast_worker=True):
        self.cover_store = cover_store
        self.speaker_hosts = speaker_hosts
        self.simulated = simulated if simulated is not None else SimulatedCovers()
        self.log = log
        self.clock = clock
        self.sync = bool(sync)
        self.keep_images = keep_images
        lock = threading.Lock()
        self._cond = threading.Condition(lock)
        self._slot_cond = threading.Condition(lock)     # fetches taking their CPU slot back
        self._tls = threading.local()   # .job: the job this worker runs (its cancellation flag); .slot
        self._free = max(1, int(workers))             # CPU slots (see the docstring), under the lock
        self._reacquiring = 0
        self._jobs = {}                 # key -> Job (wanted, not started)
        self._owned = {}                # owner -> set(keys) added with ``add`` (ticks, debounced builds)
        self._planned = {}              # owner -> set(keys) of its newest plan
        self._plans = {}                # owner -> (planner, snapshot)
        self._running = set()           # Jobs a worker runs now
        self._sleepers = {}             # worker ident -> (the time it wakes by or None, its lanes), under the lock
        self._seq = itertools.count()
        self._closed = False
        self._c2 = OrderedDict()
        self._c2_bytes = 0
        self._thumbs = OrderedDict()    # art key -> 64 px RGB
        self._dominant = {}
        self._failed = {}               # art key -> time of the failure (re-tried after 30 s)
        self._sizes = OrderedDict()     # upload key -> bytes of its newest upload (the scenes' VRAM accounting)
        self.images = {}                # keep_images: upload key -> PIL image (reference renderer tests)
        self.stats = {"jobs": 0, "uploads": 0, "c2_hits": 0, "fetches": 0, "failures": 0, "plans": 0,
                      "dropped": 0, "cancelled": 0, "ms_max": 0.0}
        self._threads = []
        self._art_threads = 0
        self._fast = False
        if not self.sync:
            for n in range(max(1, int(workers))):
                t = threading.Thread(target=self._run, args=(None,), name=f"NanoD-art-{n + 1}", daemon=True)
                t.start()
                self._threads.append(t)
            self._art_threads = len(self._threads)
            if fast_worker:
                t = threading.Thread(target=self._run, args=((LANE_FAST,),), name="NanoD-art-fast", daemon=True)
                t.start()
                self._threads.append(t)
                self._fast = True

    # ------------------------------------------------------------------ the stage thread's calls
    def plan(self, owner, planner, snapshot):
        """Newest wins: the worker turns ``snapshot`` into jobs with ``planner(service, snapshot)``."""
        with self._cond:
            self._plans[owner] = (planner, snapshot)
            self._cond.notify()                         # one waiter (the input path wakes no crowd)

    def add(self, job: Job):
        """One job (not replaced by a plan); a job with the same key is replaced (newest wins)."""
        with self._cond:
            job.seq = next(self._seq)
            self._jobs[job.key] = job
            if job.owner is not None:
                self._owned.setdefault(job.owner, set()).add(job.key)
            self._cond.notify()                         # one waiter; one that cannot take it passes it on

    def debounce(self, job: Job, replace=None) -> bool:
        """A debounce restart (newest wins, §7.5, §8.4): ``cancel(replace)`` and ``add(job)`` under
        one lock; True when ``replace`` was still wanted (``cancel``'s answer). A worker is woken
        only when none that runs ``job``'s lane is asleep with a wake-up time at or before
        ``job.not_before``. During a spin each detent moves the deadline later, and the worker
        already waiting for the earlier one finds the new job when it wakes (and waits again for
        it), so the input path wakes no thread that would take the GIL around its Commit (G1-5;
        R-k). A worker that is not asleep scans the jobs before it next waits."""
        with self._cond:
            old = None
            if replace is not None:
                old = self._jobs.pop(replace, None)
                if old is not None and old.owner is not None:
                    self._owned.get(old.owner, set()).discard(replace)
            job.seq = next(self._seq)
            self._jobs[job.key] = job
            if job.owner is not None:
                self._owned.setdefault(job.owner, set()).add(job.key)
            due = job.not_before
            for wake_by, lanes in self._sleepers.values():
                if wake_by is not None and wake_by <= due and (lanes is None or job.lane in lanes):
                    return old is not None
            self._cond.notify()
            return old is not None

    def cancel(self, key) -> bool:
        """Drop a wanted job that has not started (a debounce restarted: newest wins)."""
        with self._cond:
            job = self._jobs.pop(key, None)
            if job is not None and job.owner is not None:
                self._owned.get(job.owner, set()).discard(key)
            return job is not None

    def forget(self, owner, *, running=True):
        """A scene closed: drop its plan and every job it still wanted; with ``running``, the jobs
        of ``owner`` that already run are cancelled too (their fetches stop at the next chunk)."""
        with self._cond:
            self._plans.pop(owner, None)
            for key in self._owned.pop(owner, set()) | self._planned.pop(owner, set()):
                self._jobs.pop(key, None)
            if running:
                for job in self._running:
                    if job.owner == owner:
                        job.cancelled = True

    def warm(self, k):
        """Load the text faces the scenes use at ``k`` on every worker, once per k (a face load
        holds the GIL about 1-2 ms; done at an open's t = 0, while the capture runs and before
        the overlay can take input, instead of inside a spin, G1-5)."""
        k = round(float(k), 4)
        done = getattr(self, "_warmed", set())
        if k in done:
            return
        done.add(k)
        self._warmed = done
        for n in range(max(1, self._art_threads)):
            self.add(Job(("warm", k, n), (4,), lambda k=k: _warm_faces(k), owner=None, lane=LANE_ART))
        if self._fast:
            self.add(Job(("warm", k, "fast"), (4,), lambda k=k: _warm_faces(k), owner=None, lane=LANE_FAST))

    def close(self, timeout=1.0):
        with self._cond:
            self._closed = True
            self._jobs.clear()
            self._plans.clear()
            for job in self._running:
                job.cancelled = True
            self._cond.notify_all()
            self._slot_cond.notify_all()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout)

    # ------------------------------------------------------------------ sizes (the scenes' VRAM accounting)
    def note_size(self, key, w, h):
        """The bytes of the upload posted for ``key`` (read back by the scene when it lands)."""
        with self._cond:
            self._sizes[key] = int(w) * int(h) * 4
            self._sizes.move_to_end(key)
            while len(self._sizes) > SIZES_MAX:
                self._sizes.popitem(last=False)

    def upload_bytes(self, key):
        with self._cond:
            return self._sizes.get(key)

    def cancel_check(self):
        """``cancelled()`` for the job this worker runs: its flag, or the service closing."""
        job = getattr(self._tls, "job", None)

        def cancelled():
            return self._closed or (job is not None and job.cancelled)
        return cancelled

    # ------------------------------------------------------------------ planner helpers (workers)
    def replace(self, owner, jobs):
        """A plan's result: ``owner``'s wanted jobs are exactly ``jobs``. Keys already wanted keep
        their place; a key that one of ``owner``'s jobs is running now stays with that job (no
        second copy); every other job of ``owner`` is dropped, and a running one that the plan no
        longer wants is cancelled (the item left the window, §13.4 item 1)."""
        with self._cond:
            old = self._planned.get(owner, set())
            running = {j.key: j for j in self._running if j.owner == owner}
            new = set()
            for job in jobs:
                job.owner = owner
                run = running.get(job.key)
                if run is not None and not run.cancelled:
                    new.add(job.key)
                    continue
                cur = self._jobs.get(job.key)
                if cur is not None:
                    cur.prio = job.prio if isinstance(job.prio, tuple) else (int(job.prio),)
                else:
                    job.seq = next(self._seq)
                    self._jobs[job.key] = job
                new.add(job.key)
            for key in old - new:
                if self._jobs.pop(key, None) is not None:
                    self.stats["dropped"] += 1
            for key, job in running.items():
                if key not in new:
                    job.cancelled = True
            self._planned[owner] = new
            self._cond.notify_all()

    def busy(self, key) -> bool:
        with self._cond:
            return key in self._jobs or any(j.key == key for j in self._running)

    # ------------------------------------------------------------------ worker loop
    def _next(self, block=True, lanes=None):
        """The next plan or due job for a worker taking ``lanes`` (None = every lane), by
        (priority, age)."""
        with self._cond:
            while True:
                if self._closed:
                    return None, None
                if self._plans:
                    owner = next(iter(self._plans))
                    return "plan", (owner,) + self._plans.pop(owner)
                now = self.clock()
                best = None
                tick = None
                wait = None
                other = False
                for job in self._jobs.values():
                    if lanes is not None and job.lane not in lanes:
                        other = other or job.not_before <= now
                        continue
                    if job.not_before > now:
                        w = job.not_before - now
                        wait = w if wait is None else min(wait, w)
                        continue
                    if best is None or (job.prio, job.seq) < (best.prio, best.seq):
                        best = job
                    if _is_tick(job) and (tick is None or (job.prio, job.seq) < (tick.prio, tick.seq)):
                        tick = job
                if best is not None and not _is_tick(best):
                    if self._free > self._reacquiring:          # a slot (fetches taking theirs back first)
                        self._free -= 1
                        best.slot = True
                    else:
                        best = tick                             # no slot: only a tick
                if best is not None:
                    del self._jobs[best.key]
                    if best.owner is not None:
                        self._owned.get(best.owner, set()).discard(best.key)
                        self._planned.get(best.owner, set()).discard(best.key)
                    self._running.add(best)
                    return "job", best
                if not block:
                    return None, None
                if other:
                    self._cond.notify()                 # a due job of another lane: wake a worker for it
                me = threading.get_ident()
                self._sleepers[me] = (None if wait is None else now + wait, lanes)    # read by ``debounce``
                try:
                    self._cond.wait(wait)
                finally:
                    self._sleepers.pop(me, None)

    def _run(self, lanes=None):
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetThreadPriority(k32.GetCurrentThread(), -1)          # THREAD_PRIORITY_BELOW_NORMAL
        except Exception:
            pass
        while True:
            kind, item = self._next(block=True, lanes=lanes)
            if kind is None:
                return
            self._handle(kind, item)

    def run_pending(self, max_items=1000) -> int:
        """Sync mode (tests): run due plans and jobs on the caller's thread."""
        n = 0
        while n < max_items:
            kind, item = self._next(block=False)
            if kind is None:
                break
            self._handle(kind, item)
            n += 1
        return n

    def _handle(self, kind, item):
        if kind == "plan":
            owner, planner, snapshot = item
            self.stats["plans"] += 1
            try:
                jobs = planner(self, snapshot) or []
            except Exception as exc:
                _log_safe(self.log, f"art: plan failed {type(exc).__name__}")
                jobs = []
            self.replace(owner, jobs)
            return
        job = item
        try:
            self._run_job(job)
        finally:
            if job.slot:
                job.slot = False
                self._release_slot()

    def _release_slot(self):
        with self._cond:
            self._free += 1
            if self._reacquiring:
                self._slot_cond.notify()
            else:
                self._cond.notify()                     # a job that waited for a slot

    def _take_slot_back(self):
        with self._cond:
            self._reacquiring += 1
            try:
                while self._free <= 0 and not self._closed:
                    self._slot_cond.wait()
            finally:
                self._reacquiring -= 1
            self._free -= 1

    def _run_job(self, job):
        t0 = time.perf_counter()
        self._tls.job = job
        try:
            if job.cancelled:
                raise _Dropped()
            out = job.fn()
        except Never:
            out = None
        except Exception as exc:
            if isinstance(exc, _Dropped) or _is_cancel(exc) or job.cancelled:
                self.stats["cancelled"] += 1
            else:
                self.stats["failures"] += 1
                _log_safe(self.log, f"art: job failed {type(exc).__name__}")
            out = None
        finally:
            self._tls.job = None
            with self._cond:
                self._running.discard(job)
        self.stats["jobs"] += 1
        self.stats["ms_max"] = max(self.stats["ms_max"], (time.perf_counter() - t0) * 1000.0)
        if out is None or job.uploads is None or job.cancelled:
            return
        if isinstance(out, RM.Sprite):
            w, h = out.size
            data, opaque = out.bgra(), False
            if self.keep_images:
                self.images[job.key] = out
        else:
            w, h = out.size
            data, opaque = RM.opaque_bgra(out), True
            if self.keep_images:
                self.images[job.key] = out
        self.note_size(job.key, w, h)
        try:
            if _is_tick(job):                           # a wake-up: no surface, no upload (surfaces.UploadQueue)
                job.uploads.put(job.key, w, h, data, opaque=opaque, done=job.done, priority=rank(job.prio),
                                tick=True)
            else:
                job.uploads.put(job.key, w, h, data, opaque=opaque, done=job.done, priority=rank(job.prio))
            self.stats["uploads"] += 1
        except Exception as exc:
            _log_safe(self.log, f"art: upload post failed {type(exc).__name__}")

    # ------------------------------------------------------------------ sources and caches
    def failed_recently(self, art_key) -> bool:
        t = self._failed.get(art_key)
        return t is not None and self.clock() - t < 30.0

    def c2_get(self, key):
        with self._cond:
            data = self._c2.get(key)
            if data is not None:
                self._c2.move_to_end(key)
            return data

    def c2_put(self, key, img):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=C2_QUALITY)
        data = buf.getvalue()
        with self._cond:
            old = self._c2.pop(key, None)
            if old is not None:
                self._c2_bytes -= len(old)
            self._c2[key] = data
            self._c2_bytes += len(data)
            while self._c2_bytes > C2_BYTES and len(self._c2) > 1:
                _k, dropped = self._c2.popitem(last=False)
                self._c2_bytes -= len(dropped)

    def thumb(self, art_key):
        with self._cond:
            t = self._thumbs.get(art_key)
            if t is not None:
                self._thumbs.move_to_end(art_key)
            return t

    def _keep_thumb(self, art_key, img):
        with self._cond:
            self._thumbs[art_key] = img
            self._thumbs.move_to_end(art_key)
            while len(self._thumbs) > THUMBS_MAX:
                self._thumbs.popitem(last=False)

    def fetch_decoded(self, art_key, src, need_px, k=2.0, item=None):
        """(RGB image, source edge) for one source at the rung for ``need_px`` (§13.1, §13.4
        steps 2-3); also keeps the 64 px thumbnail and the dominant colour."""
        item = item or {}
        if src[0] == "sonos":
            url = src[1]
            if self.cover_store is None:
                raise Never()
            host = None
            try:
                from urllib.parse import urlsplit as _us
                host = _us(url).hostname
            except Exception:
                host = None
            hosts = tuple(self.speaker_hosts() if callable(self.speaker_hosts) else (self.speaker_hosts or ()))
            data = self._store_fetch(sonos_url=url, speaker_host=host if host in hosts else None)
            self.stats["fetches"] += 1
            img = _decode(data, need_px)
        else:
            template, art_max = src
            rung = SM.art_rung(need_px, art_max, k)
            if template.startswith("simulation://loading/"):
                raise Never()
            if template.startswith("simulation://"):
                img = self.simulated.draw(template, rung, art_max, item)
            else:
                if self.cover_store is None:
                    raise Never()
                data = self._store_fetch(template, rung)
                self.stats["fetches"] += 1
                img = _decode(data, need_px)
        edge = min(img.size)
        if self.thumb(art_key) is None:
            self._keep_thumb(art_key, RM.thumb64(img))
        if art_key not in self._dominant:
            try:
                from ...artwork import dominant_rgb, sleeve_colour
                self._dominant[art_key] = sleeve_colour(img, dominant_rgb(img))
            except Exception:
                self._dominant[art_key] = (0x40, 0x40, 0x40)
        return img, edge

    def _store_fetch(self, *args, **kw):
        """``CoverStore.fetch`` (bounds, allowlist, C1) with this job's cancellation, outside the
        job's CPU slot: a download waits on the network, not on the GIL."""
        job = getattr(self._tls, "job", None)
        if job is not None and job.lane != LANE_ART and not getattr(self, "_lane_warned", False):
            self._lane_warned = True                    # a programming error: the fast lane never fetches
            _log_safe(self.log, "art: a fast-lane job fetched a cover")
        slot = job is not None and job.slot
        if slot:
            job.slot = False
            self._release_slot()
        try:
            return self.cover_store.fetch(*args, cancelled=self.cancel_check(), **kw)
        finally:
            if slot:
                self._take_slot_back()
                job.slot = True

    def dominant(self, art_key):
        return self._dominant.get(art_key)

    # ------------------------------------------------------------------ element builders (workers)
    def element(self, plan: SM.ArtPlan, px: int, *, units: int, need0: int, k: float = 2.0, variant="card",
                src_need=None):
        """The final art state of an element at ``px`` (an opaque RGB image), or None when it never
        arrives. ``need0`` is the element's largest need in px (the §13.5 decision is per item);
        ``src_need`` (default ``need0``) is the need the rung is requested for (§13.1: an explorer
        L1-only job asks for its own 340, i.e. the 600 rung, WP8-R3)."""
        c2key = (plan.key, variant, px)
        data = self.c2_get(c2key)
        if data is not None:
            self.stats["c2_hits"] += 1
            img = Image.open(io.BytesIO(data))
            img.load()
            return img.convert("RGB")
        unit_px = px / float(units)
        if plan.kind in ("never", "pending"):
            return None
        if plan.kind == "generated":
            img = RM.art_generated(plan.title, plan.artist, px, variant=variant, unit_px=unit_px)
            if self.thumb(plan.key) is None:
                self._keep_thumb(plan.key, RM.thumb64(img))
        elif plan.kind == "mosaic":
            tiles = []
            for src in plan.sources:
                tkey = SM.source_key(src)
                img, _edge = self.fetch_decoded(tkey, src, need0 / 2.0, k)
                tiles.append(img)
            img = RM.art_mosaic(tiles, px)
            if self.thumb(plan.key) is None and tiles:
                self._keep_thumb(plan.key, RM.thumb64(tiles[0]))      # §7.5: a playlist's first mosaic cover
        else:
            src = plan.sources[0]
            want = need0 if src_need is None else src_need
            if self.failed_recently(plan.key):
                return None
            try:
                img, edge = self.fetch_decoded(plan.key, src, want, k,
                                               {"title": plan.title, "album": plan.title, "art_bg": plan.bg})
            except Never:
                raise
            except Exception as exc:
                if not _is_cancel(exc):
                    self._failed[plan.key] = self.clock()         # a cancelled fetch is not a failure
                raise
            art_max = src[1] if src[0] != "sonos" else 0
            src_edge = min(edge, art_max) if art_max else edge
            if plan.kind == "single" or not SM.is_extended(need0, src_edge):
                img = RM.fit_square(img, px)
            else:
                colour = self.dominant(plan.key) or RM.rgb_of(plan.bg)
                img = RM.art_extended(img, px, colour, SM.extended_fraction(need0, src_edge), unit_px)
        self.c2_put(c2key, img)
        return img

    def loading(self, plan: SM.ArtPlan, px: int, *, units: int):
        """``art.loading`` (bgColor + title / artist in textColor1) at ``px``."""
        return RM.art_loading(plan.title, plan.artist, px, plan.bg, plan.ink, units=units)


_WARM_SIZES = ((30, 600), (17, 400), (14, 400), (17, 600), (13, 500), (13, 400), (13, 600), (22, 600),
                (14, 400), (12, 600), (20, 500), (24, 600), (15, 400), (34, 800), (16, 500), (38, 800),
                (28, 600), (16, 400), (11, 700), (10, 700))


def _warm_faces(k):
    """Every (size, weight) the scene sprites draw, at k (``TextEngine`` caches faces per thread)."""
    eng = RM.text_engine()
    for px, wght in _WARM_SIZES:
        eng.width("Aa", px * k, wght)
        eng.face(eng.font_for("A", wght), px * k)
    return None


def _decode(data: bytes, need_px):
    """Decode (``draft`` for JPEG DCT scaling when the target is <= 1/2 of the source), RGB (§13.4)."""
    img = Image.open(io.BytesIO(data))
    try:
        target = max(1, int(need_px))
        if img.format == "JPEG" and min(img.size) >= 2 * target:
            img.draft("RGB", (target, target))
    except Exception:
        pass
    img.load()
    return img.convert("RGB") if img.mode != "RGB" else img


def upload_key(kind, *parts):
    return (kind,) + tuple(parts)
