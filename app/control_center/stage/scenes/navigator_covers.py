"""The r3 Navigator's covers for Recently Added (README section 5 "vertical mini carousel"; DESKTOP_STAGE
section 24.3): the focused album and its neighbours +/-2, as real album art.

A small, bounded LRU of decoded covers (``CAPACITY`` images at the Navigator's 120-unit size, about
7 MB at k = 2) fed by the **existing art pipeline** of the explorer (``art.ArtService``,
the ``NanoD-art-*`` workers), handed to ``navigator.Navigator`` by
``standalone.start_navigator`` (the one wiring point):

- The art identity and source of an item are the explorer's own (``scene_music.cover_plan``): its
  Apple artwork template (``art_template`` / ``art_max``, already filtered by
  ``apple_music.apple_artwork_url``), else the row's Sonos ``/getaa`` URL, else the Generated
  sleeve. So the explorer and the Navigator share the art key, the ``CoverStore`` cache (C1) and
  the 30 s failure back-off.
- Fetches run as ``LANE_ART`` jobs on the art workers through ``ArtService.fetch_decoded``, i.e.
  ``artwork.CoverStore.fetch``: its host allowlist, size bounds, no credentials (Apple's CDN
  artwork needs none; a Sonos cover only from the configured speaker), chunked cancellation and
  C1. URLs are never logged. The Generated sleeve (``render_music.art_generated``, the explorer's
  ``art.generated``) is drawn on the fast lane (no network).
- ``want(items, focus)`` (Tk thread) is newest-wins: covers that left the window and have not
  started are cancelled; running ones finish into the LRU (a turn back finds them).
- ``get(key)`` never blocks. Until a cover is in, the scene shows the item's accent tile and fades
  the art in over it when it lands (``navigator``, 240 ms).

Without an ``ArtService`` (the stage could not start) every cover stays a tile.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from ... import render_music as RM
from ... import scene_music as SM

CAPACITY = 24                  # decoded covers kept (the window is 5; a quick spin back finds the rest)
NEED_UNITS = 120               # the Navigator's focused cover
OWNER = "navigator"
WINDOW = 2                     # neighbours each side
RETRY_S = 30.0                 # a failed cover is asked again after this long (the art service's back-off)


def plan_for(item, source="recent"):
    """(art key, ArtPlan) of a Recently Added item, the explorer's identity; (None, None) when the
    item has no art identity at all. r3.1: a Favourite playlist (``source`` "favourites") takes the
    explorer's playlist identity (``explorer_plan``: its mosaic, else the first cover, else Generated)."""
    if not isinstance(item, dict):
        return None, None
    try:
        plan = SM.explorer_plan(item, "favourites") if source == "favourites" else SM.cover_plan(item)
    except Exception:
        return None, None
    if plan is None:
        return None, None
    return plan.key, plan


class NavigatorCovers:
    """See the module docstring. ``art``: an ``ArtService`` (or None); ``k``: physical px per unit."""

    def __init__(self, art=None, *, k=2.0, capacity=CAPACITY, clock=time.monotonic):
        self.clock = clock
        self.art = art
        self.k = float(k)
        self.need_px = max(16, int(round(NEED_UNITS * self.k)))
        self.capacity = int(capacity)
        self._lock = threading.Lock()
        self._images = OrderedDict()        # art key -> RGB image at need_px
        self._inflight = {}                 # art key -> job key
        self._failed = {}                  # art key -> monotonic time of the failure
        self.ready_seq = 0                  # bumps when a cover lands (the Tk tick re-posts)
        self.stats = {"requests": 0, "landed": 0, "cancelled": 0, "failed": 0, "evicted": 0}

    # ------------------------------------------------------------------ Tk thread
    def get(self, key):
        if not key:
            return None
        with self._lock:
            img = self._images.get(key)
            if img is not None:
                self._images.move_to_end(key)
            return img

    def want(self, items, focus, source="recent"):
        """Ask for the covers of ``items[focus - 2 .. focus + 2]`` (nearest first). Returns
        {index: art key} for the window. ``source``: "recent" (albums) or r3.1's "favourites"."""
        keys = {}
        if not items:
            return keys
        order = sorted(range(max(0, focus - WINDOW), min(len(items), focus + WINDOW + 1)),
                       key=lambda j: (abs(j - focus), j))
        wanted = set()
        for j in order:
            key, plan = plan_for(items[j], source)
            if key is None:
                continue
            keys[j] = key
            wanted.add(key)
            self._request(key, plan, items[j], abs(j - focus))
        self._drop_unwanted(wanted)
        return keys

    def _request(self, key, plan, item, distance):
        art = self.art
        if art is None or plan.kind not in ("cover", "generated", "mosaic", "single"):
            return   # `pending` (a playlist before its playlist_meta) / `never`: the accent tile stays
        with self._lock:
            if key in self._images or key in self._inflight:
                return
            failed = self._failed.get(key)
            if failed is not None and self.clock() - failed < RETRY_S:
                return
            self._failed.pop(key, None)
        if plan.kind == "cover" and art.failed_recently(key):
            return
        from .art import LANE_ART, LANE_FAST, Job
        job_key = ("navigator-cover", key)
        with self._lock:
            self._inflight[key] = job_key
        self.stats["requests"] += 1
        if plan.kind == "generated":
            fn, lane = (lambda: self._generated(key, plan)), LANE_FAST
        elif plan.kind in ("mosaic", "single"):
            fn, lane = (lambda: self._element(key, plan)), LANE_ART
        else:
            fn, lane = (lambda: self._fetch(key, plan, dict(item))), LANE_ART
        art.add(Job(job_key, (1, distance), fn, owner=OWNER, lane=lane))

    def _drop_unwanted(self, wanted):
        art = self.art
        with self._lock:
            gone = [(k, jk) for k, jk in self._inflight.items() if k not in wanted]
        for key, job_key in gone:
            if art is not None and art.cancel(job_key):         # not started yet: dropped
                with self._lock:
                    self._inflight.pop(key, None)
                self.stats["cancelled"] += 1

    # ------------------------------------------------------------------ art workers
    def _fetch(self, key, plan, item):
        try:
            img, _edge = self.art.fetch_decoded(key, plan.sources[0], self.need_px, self.k, item)
            self._land(key, RM.fit_square(img, self.need_px))
        except BaseException:
            self._fail(key)
            raise
        return None                                            # no upload: the Navigator takes the image

    def _element(self, key, plan):
        """A playlist's mosaic / single cover through the explorer's own element builder (its
        tiles fetched like any cover: same store, allowlist and C1)."""
        try:
            img = self.art.element(plan, self.need_px, units=NEED_UNITS, need0=self.need_px, k=self.k)
            if img is None:
                raise RuntimeError("no playlist art")
            self._land(key, RM.fit_square(img, self.need_px))
        except BaseException:
            self._fail(key)
            raise
        return None

    def _generated(self, key, plan):
        try:
            self._land(key, RM.art_generated(plan.title, plan.artist, self.need_px))
        except BaseException:
            self._fail(key)
            raise
        return None

    def _fail(self, key):
        with self._lock:
            self._inflight.pop(key, None)
            self._failed[key] = self.clock()
            while len(self._failed) > 256:
                self._failed.pop(next(iter(self._failed)))
        self.stats["failed"] += 1

    def _land(self, key, img):
        with self._lock:
            self._inflight.pop(key, None)
            self._images[key] = img
            self._images.move_to_end(key)
            while len(self._images) > self.capacity:
                self._images.popitem(last=False)
                self.stats["evicted"] += 1
            self.ready_seq += 1
        self.stats["landed"] += 1

    def close(self):
        if self.art is not None:
            try:
                self.art.forget(OWNER)
            except Exception:
                pass
