"""Shared fixtures for the desktop v7 controller and runtime suites (CONTROL_CENTER_V5.md section 17).

Headless: a fake clock, a seeded RNG, a manual executor for the lanes and the section 16
simulator fakes. No device, port, network, window or Tk is ever touched.
"""
from concurrent.futures import Future
from pathlib import Path
from queue import Queue
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.controller import COPY, Controller, copy_text  # noqa: E402
from control_center.runtime import OperationFailure, Runtime  # noqa: E402
from control_center.simulation import (FakeStagePresenter, SimControls, SimulatedAppleMusic,  # noqa: E402
                                       SimulatedSonos, SimulatedToasts, SimulatedWindows)


class Clock:
    """A fake clock; `sleep` advances it (the simulator's slow options run synchronously)."""

    def __init__(self, now=10.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    sleep = advance


def state(volume=28, group="group-a", **extra):
    """A v6-shaped Sonos state (no section 9.1 queue fields)."""
    result = dict(online=True, volume=volume, group_revision=group, group_label="Hall",
                  title="Current track", artist="Artist", can_next=True,
                  can_previous=True, track_id="track-1")
    result.update(extra)
    return result


def queue_state(P=5, T=12, volume=28, group="group-a", **extra):
    """A full K3 section 9.1 state: the Sonos queue, PLAYING row P of T."""
    result = dict(online=True, volume=volume, group_revision=group, group_label="Hall", room_label="Hall",
                  title="Pressure Front", artist="Mira Vale", can_next=True, can_previous=True,
                  can_play=False, can_pause=True, playback="PLAYING", track_id=f"track-{P}",
                  queue_revision="rev-1", queue_length=T, playlist_position=P, source="queue",
                  position_s=74, duration_s=210, can_seek=True, shuffle=False, repeat="off",
                  play_mode="NORMAL", companion_shuffle=False, song_id=str(1000 + P))
    result.update(extra)
    return result


def item(index, **extra):
    value = {"id": f"album-{index}", "title": f"Album {index}", "artist": "Artist", "kind": "album",
             "available": True, "accent": 0x102030 + index, "art_template": "", "track_count": 10,
             "_resource": {"id": f"album-{index}", "type": "library-albums"}}
    value.update(extra)
    return value


def recent_page(offset=0, total=60, visit=1, count=25, complete=None, overrides=None):
    """A section 9.8.6 page result (`overrides`: {index: item fields})."""
    last = offset + count if total is None else min(offset + count, total)
    overrides = overrides or {}
    items = [item(i, **overrides.get(i, {})) for i in range(offset, last)]
    return {"items": items, "offset": offset, "limit": 25, "total": total,
            "complete": (total is not None and last >= total) if complete is None else complete, "visit": visit}


def page(first=0, more=True):
    """The v6 page shape (kept for older suites)."""
    return {"items": [{"id": f"album-{i}", "title": f"Album {i}",
                       "kind": "library-albums", "artist": "Artist", "available": True}
                      for i in range(first, first + 10)],
            "next": f"cursor-{first + 10}" if more else None}


def windows_snapshot(count=4):
    return {"items": [{"id": str(i), "hwnd": i + 1, "pid": i + 100,
                       "title": f"Window {i}", "app": f"App{i}", "available": True, "accent": 0x204060 + i}
                      for i in range(count)], "index": 1, "origin": {"hwnd": 1, "pid": 100}}


def rows(first, last, T=None, prefix="Song", catalog=True):
    """Queue rows first..last (1-based) as `queue_window` returns them."""
    return [{"row": n, "title": f"{prefix} {n}", "artist": "Artist", "album": "Album",
             "sonos_art": "", "song_id": str(1000 + n) if catalog else None, "duration_s": 200,
             "signature": f"sig-{n}", "service": "apple"} for n in range(first, last + 1)]


def window_result(start, count, T, revision="rev-1", **kw):
    last = min(T, start + count)
    return {"start": start, "rows": rows(start + 1, last, **kw), "update_id": revision, "total": T}


def fail(message="failed", outcome=None, **attrs):
    return OperationFailure(message, outcome=outcome, **attrs)


class ManualExecutor:
    """A controllable queue modelling a busy, single-worker I/O lane."""

    def __init__(self, **kwargs):
        self.jobs = []
        self.closed = False

    def submit(self, function, *args):
        future = Future()
        self.jobs.append((future, function, args))
        return future

    def run_next(self):
        future, function, args = self.jobs.pop(0)
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(function(*args))
        except BaseException as exc:
            future.set_exception(exc)

    def run_all(self, limit=500):
        ran = 0
        while self.jobs and ran < limit:
            self.run_next()
            ran += 1
        return ran

    def shutdown(self, wait=True, cancel_futures=False):
        self.closed = True
        if cancel_futures:
            for future, _, _ in self.jobs:
                future.cancel()


class FakeDevice:
    def __init__(self):
        self.events = Queue()
        self.commands = []

    def submit(self, *command):
        self.commands.append(command)


class Fixture(unittest.TestCase):
    """A controller on a fake clock with a published queue state (Home, PLAYING row 5 of 12)."""

    initial = None

    def setUp(self):
        self.clock = Clock()
        self.c = Controller(clock=self.clock, rng=random.Random(7))
        self.publish(self.initial if self.initial is not None else queue_state())
        self.c.last_poll = self.clock()
        self.c.drain()

    # -------------------------------------------------------------- helpers
    def publish(self, value):
        request = self.c.request("state")
        self.c.complete(request, value)

    def effects(self, kind=None):
        effects = self.c.drain()
        return [e for e in effects if kind is None or e["kind"] == kind]

    def one(self, kind, effects=None):
        found = [e for e in (effects if effects is not None else self.effects()) if e["kind"] == kind]
        self.assertEqual(len(found), 1, [e["kind"] for e in found])
        return found[0]

    def pending(self, kind):
        found = [e for e in self.c.pending.values() if e["kind"] == kind]
        self.assertTrue(found, f"no pending {kind}")
        return found[-1]

    def complete(self, kind, result=None, error=None):
        effect = self.pending(kind)
        self.c.complete(effect["request"], result, error)
        return effect

    def frame(self):
        return self.c.frame()

    def press(self, logical, hid=False):
        self.c.button(logical, self.c.control_id, hid)

    def turn_to(self, position):
        self.c.position(position, self.c.control_id)

    def hold(self):
        self.c.hold(0, self.c.control_id)

    def tick(self, seconds=0.0):
        self.clock.advance(seconds)
        self.c.tick()

    def labels(self):
        return [(b["icon"], b["label"], b["enabled"]) for b in self.frame()["buttons"]]

    def transient(self):
        return self.c._transient().text if self.c._transient() else None

    def err_count(self):
        return self.c.feedback_seq if self.c.feedback and self.c.feedback["kind"] == "err" else None

    # -------------------------------------------------------------- mode entries
    def browse(self, total=60, count=25, complete=None, overrides=None):
        self.press(1)
        self.complete("recent", recent_page(0, total, count=count, complete=complete, overrides=overrides))
        self.c.drain()

    def tracks(self, index=1):
        self.press(2)
        if index != 1:
            self.turn_to(index)
        self.c.drain()

    def seek(self):
        self.tracks()
        self.press(2)
        self.c.drain()

    def upnext(self, loaded=True, T=None):
        """Tracks → Up next with the first window (and the upcoming rows) loaded."""
        self.tracks()
        self.press(1)
        P, T = self.c._position()
        if loaded:
            while any(e["kind"] == "queue_window" for e in self.c.pending.values()):
                effect = self.pending("queue_window")
                self.c.complete(effect["request"], window_result(effect["start"], effect["count"], T,
                                                                 revision=self.c.state.get("queue_revision", "rev-1")))
        self.c.drain()

    def ratings(self, liked=()):
        for effect in list(self.c.pending.values()):
            if effect["kind"] == "ratings":
                self.c.complete(effect["request"], {song: 1 for song in effect["ids"] if song in liked})
            elif effect["kind"] == "catalog_songs":
                self.c.complete(effect["request"], {song: {"catalog": True, "album": "Album", "accent": 0x445566}
                                                    for song in effect["ids"]})
        self.c.drain()

    def open_windows(self, count=4):
        self.press(3)
        effect = self.one("windows_open")
        snapshot = windows_snapshot(count)
        self.c.complete(effect["request"], snapshot)
        self.c.drain()
        return snapshot


class Harness:
    """Controller + Runtime + the section 16 simulator fakes, lanes run by hand."""

    def __init__(self, testcase, controls=None, *, album=True, stage=True, **runtime_kwargs):
        patcher = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        patcher.start()
        testcase.addCleanup(patcher.stop)
        self.clock = Clock(100.0)
        self.controls = controls or SimControls()
        self.sonos = SimulatedSonos(self.controls, clock=self.clock, sleep=self.clock.sleep)
        if album:
            self.sonos.load_album()
        self.apple = SimulatedAppleMusic(self.controls, clock=self.clock, sleep=self.clock.sleep)
        self.windows = SimulatedWindows(self.controls)
        self.stage = FakeStagePresenter(self.controls) if stage else None
        self.toasts = SimulatedToasts()
        self.c = Controller(clock=self.clock, rng=random.Random(7))
        self.device = FakeDevice()
        self.runtime = Runtime(self.c, self.sonos, self.apple, self.windows, self.device, stage=self.stage,
                               toasts=self.toasts, **runtime_kwargs)
        testcase.addCleanup(self.runtime.close)

    def lanes(self):
        return self.runtime.audio, self.runtime.library, self.runtime.lookahead

    def run(self, rounds=4):
        for _ in range(rounds):
            self.runtime.poll()
            for lane in self.lanes():
                lane.run_all()
        self.runtime.poll()

    def press(self, logical):
        self.c.button(logical, self.c.control_id)
        self.runtime.dispatch()

    def frame(self):
        return self.c.frame()


__all__ = ["COPY", "Clock", "Controller", "FakeDevice", "Fixture", "Harness", "ManualExecutor", "copy_text",
           "fail", "item", "page", "queue_state", "recent_page", "rows", "state", "window_result",
           "windows_snapshot"]
