"""Record true-to-app knob sessions: the real Desk Dial Controller, headless, over fictional data.

The real ``Controller`` + ``Runtime`` + ``DeviceBridge`` of the companion (control_center/) run against
an in-memory fake Nano_D++ knob that answers like the 1.0.0-cc5.7 firmware (presentation 6, appCanvas,
feel, hapticFx, knobSound, offlineVolume, recalibration, knobVolume, alive, artwork, artwork2), the
companion's own simulator fakes (Sonos, Apple Music, Home Assistant, the window picker) filled with the
fictional library of fixtures.py through fiction.py, and one fake clock. Every ``{"frame":…}`` and
``{"control":…}`` line the bridge writes is kept exactly as written, with the fake-clock time, together
with every input the script injects (detents, button edges, holds, end-stop pushes). Nothing here opens
a serial port, a window or a network connection, and no .pyc lands in the app tree.

The machinery is tests/tools/capture_session_frames.py (the Session, the FakeKnob with the artwork2
media store and CDC model, the recorder) and capture_r3_session.py (the F24 foreground rule of the
picker), imported from the app's tests/tools, not copied.

Output: one ``desk-dial-recording/1`` JSON per scene (see RECORDING FORMAT in the lead's brief), plus
``covers/<artKey>.jpg`` (240 px baseline JPEG, the bytes the knob's media store committed) and
``icons/<iconKey>.bin`` (2048 B RGB565 LE 32x32) next to it; the JSON's ``covers`` / ``icons`` maps
hold paths relative to the JSON file (no user path reaches a recording), and ``stills.json`` /
``button-maps.json`` for the stills and the cheat sheet.

Usage (from this folder, with the app's venv):
  set DESK_DIAL_APP=<companion source dir>
  python capture.py --out <dir> [--jsonl] [scene ...]
Scenes: music-volume music-lists music-tracks-seek music-playpause music-hold-queue lights-brightness
lights-temperature lights-scenes lights-power windows-knob hero-knob story-day stills
--jsonl also writes records.jsonl (capture_session_frames.py's format) for
``work/lcd-preview/parse_tests.py --frames``.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import random
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fiction as FI  # noqa: E402  (first: the simulator is overridden in place before anything builds one)
import fixtures as fx  # noqa: E402
from companion import APP_DIR, prepare_artwork2  # noqa: E402

TOOLS = Path(APP_DIR) / "tests" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import capture_session_frames as csf  # noqa: E402
from control_center import artwork as ART  # noqa: E402
from control_center import navigator_model as NAV  # noqa: E402
from control_center import presentation  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import (SimulatedAppleMusic, SimulatedHomeAssistant,  # noqa: E402
                                       SimulatedSonos, SimulatedWindows)

SCHEMA = "desk-dial-recording/1"
FPS = 30
PREROLL_MS = 3000

# The 1.0.0-cc5.7 capabilities reply, key for key as control_center.cpp:185-231 builds it (cc_handle_command):
# the common keys, presentation 6, glyphs, appCanvas (cc5.6), the r4 feel/sound keys (cc5.7), knobVolume
# (2026-09-30), alive (drive = CCAliveSpec::defaultDrive 150 with no latched ledDrive, cc_alive.h:201), the
# v1 artwork object, the artwork2 object (cc_media_store.h:367-388; rxBytes 8192 = the receive queue in
# internal RAM), diag.
CC57_CAPABILITIES = {
    "controlCenter": 1, "leaseMs": 2000, "hostFrame": 1, "runtimeProfileBounds": 1, "taggedInput": 1,
    "windowsHidKey": "F24", "buttonOrder": 1, "windowsHidControl": 1,
    "presentation": 6, "glyphs": "latin-ext-a",
    "appCanvas": 1,
    "feel": 1, "hapticFx": 1, "knobSound": 1, "offlineVolume": 1, "recalibration": 1,
    "knobVolume": 1,
    "alive": {"version": 1, "fps": 60, "drive": 150},
    "artwork": {"version": 1, "width": 120, "height": 120, "format": "RGB565_LE", "chunkBytes": 384,
                "cacheEntries": 8, "available": True, "composited": "scrim80"},
    "artwork2": deepcopy(presentation.ARTWORK2_CAPABILITY),
    "diag": 1,
}
NOW_ALBUM, NOW_ROW = 2, 5     # "Clearing" (Glass Weather, North of June): row 5 of the album queue


class CaptureError(RuntimeError):
    pass


# ---------------------------------------------------------------- covers: fixtures' sleeves through the artwork pipeline
_PREPARED = {}
KEY_URL = {}      # FakeArtwork cache key -> the simulator URL it stands for


def prepared(album):
    """fixtures.cover(album) prepared as the host prepares a downloaded cover (240 px baseline JPEG, v1 RGB565,
    dominant accent): what ArtworkService would deliver."""
    if album not in _PREPARED:
        buf = BytesIO()
        fx.cover(album, 1200).save(buf, "PNG")
        _PREPARED[album] = prepare_artwork2(buf.getvalue())
    return _PREPARED[album]


_csf_cover_jpeg, _csf_cover_pixels, _csf_accent_for = csf.cover_jpeg, csf.cover_pixels, csf.accent_for


def _album_for_key(key):
    return FI.album_of(KEY_URL.get(key))


def fiction_cover_jpeg(key):
    album = _album_for_key(key)
    return prepared(album).jpeg if album is not None else _csf_cover_jpeg(key)


def fiction_cover_pixels(key):
    album = _album_for_key(key)
    return prepared(album).raw if album is not None else _csf_cover_pixels(key)


def fiction_accent_for(url):
    album = FI.album_of(url)
    return prepared(album).dominant if album is not None else _csf_accent_for(url)


class FictionArtwork(csf.FakeArtwork):
    """capture_session_frames.FakeArtwork delivering fixtures' procedural covers for the simulator's URLs."""

    def _store(self, url):
        key = super()._store(url)
        KEY_URL[key] = url
        return key


_real_artwork_url = ART.artwork_url


def _fiction_artwork_url(value, speaker_hosts=()):
    """The artwork allowlist, letting the simulator's never-fetched ``simulation://art/...`` templates through
    to the FakeArtwork (the live allowlist rejects them so the real service never downloads one)."""
    if isinstance(value, str) and value.startswith("simulation://"):
        return value
    return _real_artwork_url(value, speaker_hosts)


# ---------------------------------------------------------------- the fakes
class FictionSonos(SimulatedSonos):
    """The simulator's Sonos on the fake clock, playing fixtures' album 2 at row 5, with a cover per song."""

    def __init__(self, controls, clock):
        super().__init__(controls, clock=clock, sleep=clock.advance)
        self.load_album(NOW_ALBUM, position=NOW_ROW)

    def read_state(self):
        state = super().read_state()
        song = state.get("song_id")
        if song:
            state["artwork_url"] = f"simulation://art/s{song}/600x600bb.jpg"
        return state


class FictionWindows(SimulatedWindows):
    """The simulator's picker (fixtures' invented apps) under the Windows foreground rule (capture_r3_session):
    show() succeeds only inside the grant of the knob's F24 press, else OSError like WindowsAdapter.show."""
    supports_hotkey = True

    def __init__(self, controls):
        super().__init__(controls)
        self.grant = False
        self.opened = self.refused = 0

    def snapshot(self):
        """The simulator's set without its fixed accents: like a live picker, the icon worker (FakeIcons with
        images) supplies each window's icon and accent, so the knob gets iconKey media (runtime.py:1000)."""
        snapshot = super().snapshot()
        for item in snapshot["items"]:
            item.pop("accent", None)
        return snapshot

    def show(self, snapshot):
        granted, self.grant = self.grant, False
        if not granted:
            self.refused += 1
            raise OSError("Windows did not grant focus to the picker. Open it with the registered F24 key.")
        self.opened += 1
        super().show(snapshot)


# ---------------------------------------------------------------- the recording
class Recording:
    """Events on the fake clock; ``start()`` fixes output time 0 = now + preroll."""

    def __init__(self, name, clock, fps=FPS, preroll_ms=PREROLL_MS):
        self.name, self.clock, self.fps, self.preroll_ms = name, clock, fps, preroll_ms
        self.t0 = None
        self.events = []          # (absolute seconds, event dict)
        self.screens = []
        self.last_haptic = None
        self.duration_ms = None
        self.frozen = False       # set before the release: nothing after the scene body is recorded

    def start(self):
        self.t0 = self.clock() + self.preroll_ms / 1000.0

    def add(self, event, at=None):
        self.events.append((self.clock() if at is None else at, event))

    def line(self, message):
        """A frame or control line as the bridge wrote it (after device._frame)."""
        if self.frozen:
            return
        if "control" in message:
            control = message["control"]
            self.add({"kind": "control", "control": deepcopy(control)})
            frame = control.get("frame")
        else:
            frame = message["frame"]
        if isinstance(frame, dict):
            self.add({"kind": "frame", "frame": deepcopy(frame)})
            haptic = frame.get("haptic")
            if isinstance(haptic, dict) and haptic.get("seq") != self.last_haptic:
                self.last_haptic = haptic.get("seq")
                self.add({"kind": "haptic", "token": haptic.get("token"), "seq": haptic.get("seq")})

    def ms(self, seconds):
        return round((seconds - self.t0) * 1000)

    def finish(self, tail_ms=1500, duration_ms=None):
        last = max((t for t, _e in self.events), default=self.t0)
        wanted = duration_ms if duration_ms is not None else self.ms(last) + tail_ms
        self.duration_ms = max(100, int(math.ceil(wanted / 100.0) * 100))

    def to_json(self, covers, icons, capabilities):
        events = [dict(t=self.ms(t), **e) for t, e in self.events]
        order = {"frame": 2, "control": 1, "haptic": 3}
        events.sort(key=lambda e: (e["t"], order.get(e["kind"], 0)))
        return {"schema": SCHEMA, "name": self.name, "firmware": FI.FIRMWARE, "app": FI.APP_VERSION,
                "fps": self.fps, "duration_ms": self.duration_ms, "preroll_ms": self.preroll_ms,
                "capabilities": deepcopy(capabilities), "events": events,
                "screens": [dict(t=self.ms(t), **s) for t, s in self.screens],
                "covers": covers, "icons": icons}


class RecordingRecorder(csf.Recorder):
    """capture_session_frames.Recorder that also hands every frame / control line to the Recording."""

    def __init__(self, clock):
        super().__init__(clock)
        self.recording = None

    def record(self, raw, message):
        record = super().record(raw, message)
        if self.recording is not None and record["kind"] in ("frame", "control"):
            self.recording.line(message)
        return record


# ---------------------------------------------------------------- the session
LANES = ("audio", "library", "lookahead", "home_lane")
# How long a queued I/O job waits on the fake clock before it completes (a Sonos read, an Apple Music page, a
# Home Assistant write): the simulator answers instantly, a live service does not, and an instant answer makes
# the bridge re-enter the knob twice within one pass (an in-flight media `have` is then lost and the bridge
# waits its 1.5 s ack timeout: a 1.4 s button press on the recording).
LANE_LATENCY = {"audio": 0.12, "library": 0.30, "lookahead": 0.30, "home_lane": 0.20}
LANE_CLOCK = [None]


class StampedLane(csf.Lane):
    """capture_session_frames.Lane that remembers when each job was queued (run_lanes runs it after its latency)."""

    def __init__(self, **options):
        super().__init__(**options)
        self.when = []

    def submit(self, function, *args):
        future = super().submit(function, *args)
        self.when.append(LANE_CLOCK[0]() if LANE_CLOCK[0] else 0.0)
        return future

    def run_next(self):
        if self.when:
            self.when.pop(0)
        super().run_next()

    def shutdown(self, wait=True, cancel_futures=False):
        super().shutdown(wait, cancel_futures)
        if cancel_futures:
            self.when.clear()


class FictionSession(csf.Session):
    """capture_session_frames.Session against the cc5.7 fake knob, the fiction fakes and a Home Assistant area."""

    def __init__(self, recorder, backup_dir):
        clock = recorder.clock
        self.ha = SimulatedHomeAssistant(csf.SimControls(), clock=clock, sleep=clock.advance, area=FI.AREA)
        csf.FIRMWARE["cc57"] = FI.FIRMWARE
        with patch.object(csf, "ScriptedWindows", FictionWindows), \
                patch.object(csf, "ScriptedSonos", FictionSonos), \
                patch.object(csf, "ScriptedAppleMusic", SimulatedAppleMusic), \
                patch.object(csf, "FakeArtwork", FictionArtwork), \
                patch.object(csf, "Runtime", lambda *a, **k: Runtime(*a, ha=self.ha, **k)):
            super().__init__("cc57", CC57_CAPABILITIES, recorder, backup_dir)
        self.rec = None
        self.media_bytes = {"cover": {}, "icon": {}}
        self._hook_media()
        self._last_screen = None

    def _hook_media(self):
        """Keep the bytes of every media upload the knob's store commits (covers and icons by key)."""
        model = self.knob.media
        original = model._commit

        def commit(store, kind, key, reply, _original=original, _model=model):
            upload = _model.upload
            data = None
            if upload is not None and not upload.hit and upload.kind == kind and upload.key == key:
                data = bytes(store.slots[upload.slot].data[:upload.bytes])
            ack = _original(store, kind, key, reply)
            if data is not None and "error" not in ack:
                self.media_bytes[kind][key] = data
            return ack

        model._commit = commit

    # -- time and settling
    def settle(self):
        super().settle()
        if self.rec is not None and not self.rec.frozen:
            mode = self.controller.screen.mode
            frame = self.knob.frame or {}
            key = (mode, frame.get("layout"))
            if key != self._last_screen:
                self._last_screen = key
                self.rec.screens.append((self.clock(), {"mode": mode, "layout": frame.get("layout"),
                                                        "heading": frame.get("heading", ""),
                                                        "title": frame.get("title", "")}))

    def run_lanes(self):
        """Every queued I/O job whose latency (LANE_LATENCY) has passed completes now, in queue order."""
        for _ in range(64):
            ran = False
            for lane in LANES:
                executor = getattr(self.runtime, lane)
                while executor.jobs and self.clock() - (executor.when[0] if executor.when else 0.0) >= LANE_LATENCY[lane]:
                    executor.run_next()
                    ran = True
                    self.settle()
            if not ran:
                return
        raise CaptureError(f"{self.recorder.step}: the lanes never emptied")

    def advance(self, seconds, step=0.05):
        end = self.clock() + seconds
        while self.clock() < end - 1e-9:
            self.clock.advance(min(step, end - self.clock()))
            self.settle()
            self.run_lanes()

    # -- the knob's inputs
    def note(self, text):
        self.rec.add({"kind": "note", "text": text})

    def detent(self, delta=1):
        knob = self.knob
        before = knob.position
        knob.turn_to(before + delta)
        if knob.position == before:
            raise CaptureError(f"{self.recorder.step}: detent {delta:+d} at the bound {before} (use lim)")
        self.rec.add({"kind": "detent", "delta": delta})
        self.settle()

    def turn(self, detents, every=0.08, jitter=0.0):
        """`detents` detents (sign = direction), one every `every` seconds (+- jitter, seeded)."""
        rng = random.Random(f"{self.rec.name}:{self.clock():.3f}")
        step = 1 if detents > 0 else -1
        for _ in range(abs(detents)):
            self.detent(step)
            self.advance(max(0.02, every + (rng.uniform(-jitter, jitter) if jitter else 0.0)))

    def lim(self, direction=1):
        self.knob.limit(direction)
        self.rec.add({"kind": "lim", "dir": direction})
        self.settle()

    def _down(self, raw):
        knob = self.knob
        down = {"id": knob.control_id, "kd": raw, "ks": knob.held | 1 << raw}
        hid = knob._f24(raw)
        if hid:
            down["hid"] = 1
            knob.sent["hid"] += 1
        knob.held |= 1 << raw
        knob.inject(down)
        knob.sent["kd"] += 1
        self.rec.add({"kind": "kd", "slot": raw})
        if hid:
            # The same press reaches Windows as F24: the WM_HOTKEY path opens the picker inside its focus grant.
            self.windows.grant = True
            self.runtime.hotkey()
        self.settle()

    def _up(self, raw):
        self.knob.up(raw)
        self.rec.add({"kind": "ku", "slot": raw})
        self.settle()

    def press(self, raw, down_ms=90):
        """A tap of physical slot `raw` (0..3): kd, `down_ms` later ku."""
        self._down(raw)
        self.advance(down_ms / 1000.0)
        self._up(raw)

    def hold(self, raw, hold_ms):
        """A held button: kd, the firmware's kh at `hold_ms` (600 ms slot 0, 1000 ms slot 3), ku 120 ms later."""
        self._down(raw)
        self.advance(hold_ms / 1000.0)
        self.knob.long_press(raw)
        self.rec.add({"kind": "kh", "slot": raw})
        self.settle()
        self.advance(0.12)
        self._up(raw)

    # -- state
    def expect(self, mode):
        if self.controller.screen.mode != mode:
            raise CaptureError(f"{self.recorder.step}: in {self.controller.screen.mode}, expected {mode}")

    def snapshot(self, name):
        """What the knob shows now plus the Navigator's content for the same snapshot."""
        frame = deepcopy(self.knob.frame) or {}
        control = deepcopy(self.knob.control) or {}
        control.pop("frame", None)
        nav = None
        try:
            snap = NAV.read_snapshot(self.controller, self.runtime.frame())
            content = NAV.build_content(snap, None)
            nav = dataclasses.asdict(content) if dataclasses.is_dataclass(content) else content
        except Exception as exc:  # the Navigator is a read-only extra
            nav = {"error": f"{type(exc).__name__}: {exc}"}
        return {"name": name, "mode": self.controller.screen.mode, "layout": frame.get("layout"),
                "buttons": [(b.get("icon"), b.get("label"), bool(b.get("enabled")), b.get("lit"))
                            for b in frame.get("buttons") or ()],
                "holdAction": self.controller.hold_action(), "feel": control.get("feel"),
                "profile": control.get("profile"), "frame": frame, "control": control, "navigator": nav}


# ---------------------------------------------------------------- scene vocabulary
def boot(s, *, volume=62, bri=62, kelvin=3200):
    """Connect the knob (output time -preroll), let the launcher settle, run the preroll."""
    s.step("boot")
    s.sonos.state["volume"] = volume
    for entity in s.ha.members():
        s.ha.lights[entity].update(bri=bri, kelvin=kelvin, on=True)
    # The controller's default target label before the first Sonos read is the author's own room name (controller.py:819, 4938):
    # the fiction room goes in first, and the first Sonos read runs before the knob connects.
    s.controller.state["group_label"] = FI.ROOM
    s.settle()
    s.advance(0.5)                 # the first Sonos read lands (LANE_LATENCY) before the knob connects
    s.rec.start()
    s.bridge.submit("connect", "COM-FICTION")
    s.settle()
    s.run_lanes()
    s.expect("launcher")
    s.advance(s.rec.preroll_ms / 1000.0)


def music(s):
    """Home tap 1 -> Music (the overshoot guard needs 0.7 s on Home first: boot waits longer)."""
    s.step("music")
    s.press(0)
    s.expect("home")


def recent(s):
    """Music tap 2 -> Recently Added (the library's first page lands on the next tick)."""
    s.step("recent")
    s.press(1)
    s.expect("recent")
    s.advance(0.3)


def lights(s):
    s.step("lights")
    s.press(2)
    s.expect("lights")
    s.advance(0.3)


# ---------------------------------------------------------------- the scenes
def scene_music_volume(s):
    boot(s, volume=62)
    s.step("volume/up")
    s.note("Turn: volume 62 -> 97")
    s.turn(35, every=0.08, jitter=0.01)
    s.advance(0.4)
    s.note("Three slower detents reach the wall at 100")
    s.turn(3, every=0.16)
    s.note("Two detents past the wall are refused (lim +1)")
    s.lim(1)
    s.advance(0.25)
    s.lim(1)
    s.advance(1.3)
    s.step("volume/down")
    s.note("Back to 62")
    s.turn(-38, every=0.06, jitter=0.008)
    s.advance(1.8)
    s.expect("launcher")


def scene_music_lists(s):
    boot(s)
    music(s)
    s.advance(0.8)
    recent(s)
    s.note("Recently Added: turn browses the library")
    s.turn(6, every=0.55, jitter=0.08)
    s.advance(0.5)
    s.step("playlists")
    s.press(2)
    s.note("3 = Playlists: the list's source toggles")
    s.advance(0.5)
    s.turn(3, every=0.6)
    s.advance(0.6)
    s.press(2)
    s.note("3 again = Recent")
    s.advance(0.9)
    s.press(0)
    s.note("1 = Back to Music")
    s.expect("home")
    s.advance(1.2)


def scene_music_tracks_seek(s):
    boot(s)
    music(s)
    s.advance(0.8)
    s.step("tracks")
    s.press(2)
    s.expect("tracks")
    s.note("Tracks: the whole queue, one row per detent")
    s.advance(0.5)
    s.turn(3, every=0.5)
    s.advance(0.6)
    s.press(3)
    s.note("4 = Play the focused row (the jump nudges)")
    s.advance(1.2)
    s.expect("tracks")
    s.step("seek")
    s.press(2)
    s.expect("seek")
    s.note("3 = Seek: fluid scrub, 5 s per detent")
    s.advance(0.5)
    s.turn(6, every=0.22)
    s.advance(0.7)
    s.press(2)
    s.note("3 = Set")
    s.advance(1.6)


def scene_music_playpause(s):
    boot(s)
    s.step("pause")
    s.press(3)
    s.note("4 = Pause (acts on release)")
    s.advance(2.0)
    s.step("play")
    s.press(3)
    s.note("4 = Play")
    s.advance(1.6)


def scene_music_hold_queue(s):
    boot(s)
    music(s)
    s.advance(0.8)
    recent(s)
    s.turn(2, every=0.5)
    s.advance(0.6)
    s.step("hold4")
    s.note("Hold 4 (1.0 s): Queue = Play next")
    s.hold(3, 1000)
    s.advance(2.2)


def scene_lights_brightness(s):
    boot(s, bri=30)
    lights(s)
    s.note("Lights: knob = brightness, 30 -> 75 (dimmer feel)")
    s.turn(45, every=0.075, jitter=0.01)
    s.advance(3.2)
    s.expect("lights")


def scene_lights_temperature(s):
    boot(s)
    lights(s)
    s.step("temperature")
    s.press(2)
    s.note("3 = Temp: knob = colour temperature, 100 K per detent")
    s.advance(0.5)
    s.turn(8, every=0.18)
    s.advance(3.0)
    s.press(2)
    s.note("3 again = brightness")
    s.advance(1.6)


def scene_lights_scenes(s):
    boot(s)
    lights(s)
    s.step("scenes")
    s.press(1)
    s.expect("scenes")
    s.note("2 = Scenes list")
    s.advance(0.6)
    s.turn(2, every=0.6)
    s.advance(0.6)
    s.press(3)
    s.note("4 = Run")
    s.expect("lights")
    s.advance(2.6)


def scene_lights_power(s):
    boot(s)
    lights(s)
    s.step("alloff")
    s.press(3)
    s.note("4 = All off")
    s.advance(2.0)
    s.press(3)
    s.note("4 = Turn on (restores the snapshot)")
    s.advance(1.6)
    s.step("home")
    s.press(0)
    s.expect("launcher")
    s.advance(1.0)
    s.step("hold4")
    s.hold(3, 1000)
    s.note("Home hold 4: Knob to lights")
    s.advance(0.8)
    s.turn(3, every=0.3)
    s.advance(1.4)
    s.hold(3, 1000)
    s.note("Hold 4 again: Knob to music")
    s.advance(1.8)


def scene_windows_knob(s):
    boot(s)
    s.step("picker")
    s.press(1)
    s.note("Home 2 = Win: F24 opens the picker on screen, the knob lists the windows")
    s.expect("windows")
    s.advance(0.6)
    s.turn(3, every=0.45)
    s.advance(0.4)
    s.press(1)
    s.note("2 = Snap left")
    s.advance(0.7)
    s.turn(2, every=0.45)
    s.advance(0.3)
    s.press(2)
    s.note("3 = Snap right: the pair closes")
    s.advance(1.4)
    s.expect("launcher")
    s.advance(0.8)
    s.step("switch")
    s.press(1)
    s.expect("windows")
    s.advance(0.6)
    s.turn(2, every=0.45)
    s.advance(0.4)
    s.press(3)
    s.note("4 = Switch")
    s.advance(0.8)
    s.expect("launcher")
    s.advance(1.0)


def scene_hero_knob(s):
    boot(s, volume=48)
    s.step("volume")
    s.turn(14, every=0.075, jitter=0.01)
    s.advance(1.6)
    music(s)
    s.advance(0.9)
    recent(s)
    s.turn(3, every=0.6)
    s.advance(0.5)
    s.step("play")
    s.press(3)
    s.note("4 = Play: the album starts (thump)")
    s.advance(2.4)
    s.step("hold1")
    s.hold(0, 600)
    s.note("Hold 1: Home")
    s.expect("launcher")
    s.advance(1.6)


def scene_story_day(s):
    boot(s, volume=40)
    s.step("morning")
    s.note("Morning: volume up")
    s.turn(12, every=0.08, jitter=0.01)
    s.advance(1.5)
    music(s)
    s.advance(0.8)
    recent(s)
    s.turn(2, every=0.6)
    s.advance(0.4)
    s.press(3)
    s.note("Play")
    s.advance(2.2)
    s.hold(0, 600)
    s.expect("launcher")
    s.advance(1.2)
    s.step("evening")
    s.note("Evening: Lights, brightness down")
    lights(s)
    s.turn(-20, every=0.08, jitter=0.01)
    s.advance(1.4)
    s.press(1)
    s.expect("scenes")
    s.turn(1, every=0.6)      # Focus -> Evening
    s.advance(0.6)
    s.press(3)
    s.note("Run: Evening")
    s.expect("lights")
    s.advance(2.0)
    s.step("later")
    s.press(0)
    s.note("Later: Home")
    s.expect("launcher")
    s.advance(1.5)


SCENES = {
    "music-volume": scene_music_volume, "music-lists": scene_music_lists, "music-tracks-seek": scene_music_tracks_seek,
    "music-playpause": scene_music_playpause, "music-hold-queue": scene_music_hold_queue,
    "lights-brightness": scene_lights_brightness, "lights-temperature": scene_lights_temperature,
    "lights-scenes": scene_lights_scenes, "lights-power": scene_lights_power, "windows-knob": scene_windows_knob,
    "hero-knob": scene_hero_knob, "story-day": scene_story_day,
}

# The button legends per screen, as controller.py builds them (the stills check them):
# _buttons_launcher 2255, _buttons_home 2243, _buttons_recent_r3 2322, _buttons_tracks 2373 (queue), _buttons_seek 2423,
# _buttons_windows 2485, _buttons_lights 2271, _buttons_scenes 2280.
LEGENDS = {
    "Home": ["Music", "Win", "Lights", "Pause"],
    "Music": ["Home", "Recent", "Tracks", "Pause"],
    "Recently Added": ["Back", "Full screen", "Playlists", "Play"],
    "Playlists": ["Back", "Full screen", "Recent", "Play"],
    "Tracks": ["Back", "Up next", "Seek", "Play"],
    "Seek": ["Cancel", "Up next", "Set", "Play"],
    "Windows": ["Home", "Snap left", "Snap right", "Switch"],
    "Lights": ["Home", "Scenes", "Temp", "All off"],
    "Colour temperature": ["Home", "Scenes", "Temp", "All off"],
    "Scenes": ["Back", "", "", "Run"],
}


def stills(s):
    """One settled frame per screen; returns [snapshot], in the order shown."""
    out = []
    boot(s)

    def take(name, expect_mode=None):
        s.advance(0.4)
        if expect_mode:
            s.expect(expect_mode)
        snap = s.snapshot(name)
        labels = [b[1] for b in snap["buttons"]]
        if name in LEGENDS and labels != LEGENDS[name]:
            raise CaptureError(f"{name}: legends {labels} != controller.py {LEGENDS[name]}")
        out.append(snap)

    take("Home", "launcher")
    music(s)
    take("Music", "home")
    recent(s)
    s.turn(2, every=0.3)
    take("Recently Added", "recent")
    s.press(2)
    s.advance(0.5)
    take("Playlists", "recent")
    s.press(2)
    s.advance(0.3)
    s.press(0)
    s.expect("home")
    s.press(2)
    take("Tracks", "tracks")
    s.press(2)
    s.turn(2, every=0.2)
    take("Seek", "seek")
    s.press(0)                      # Cancel -> Tracks
    s.expect("tracks")
    s.press(1)                      # Up next (the stage opens on screen; the knob mirrors it)
    s.advance(0.5)
    take("Up next", "upnext")
    s.press(0)
    s.expect("tracks")
    s.hold(0, 600)
    s.expect("launcher")
    s.advance(0.9)
    s.press(1)                      # Windows (F24)
    s.turn(2, every=0.3)
    take("Windows", "windows")
    s.press(0)
    s.expect("launcher")
    s.advance(0.9)
    lights(s)
    take("Lights", "lights")
    s.press(2)
    take("Colour temperature", "lights")
    s.press(2)
    s.press(1)
    s.turn(1, every=0.3)
    take("Scenes", "scenes")
    s.press(0)
    s.expect("lights")
    s.press(0)
    s.expect("launcher")
    s.advance(0.9)
    s.step("onshape")
    if s.controller.enter_onshape("manual"):
        s.settle()
        take("Onshape", "onshape")
        s.controller.exit_onshape("capture")
        s.settle()
        s.expect("launcher")
    else:
        out.append({"name": "Onshape", "skipped": "controller.enter_onshape refused"})
    return out


# ---------------------------------------------------------------- running
def run_scene(name, out_dir, write_jsonl=False):
    clock = csf.Clock()
    LANE_CLOCK[0] = clock
    recorder = RecordingRecorder(clock)
    rec = Recording(name, clock)
    recorder.recording = rec
    result = {"name": name}
    with tempfile.TemporaryDirectory(prefix="desk-dial-rm-") as backups, \
            patch("control_center.runtime.ThreadPoolExecutor", StampedLane), \
            patch("control_center.runtime.time", csf.RuntimeTime(clock)), \
            patch.object(csf, "cover_jpeg", fiction_cover_jpeg), \
            patch.object(csf, "cover_pixels", fiction_cover_pixels), \
            patch.object(csf, "accent_for", fiction_accent_for), \
            patch.object(ART, "artwork_url", _fiction_artwork_url):
        session = FictionSession(recorder, Path(backups) / name)
        session.rec = rec
        error = None
        snaps = None
        try:
            if name == "stills":
                snaps = stills(session)
            else:
                SCENES[name](session)
            rec.frozen = True
            session.step("release")
            session.bridge.submit("disconnect")
            session.settle()
        except (CaptureError, csf.CaptureError) as exc:
            error = str(exc)
        finally:
            session.close()
        # A frame the runtime still posts while the bridge releases the knob ("Frame must match the ready
        # control", after the scene body) is the shutdown race of capture_session_frames too: reported apart.
        release_errors = [e for e in session.bridge_errors if e.get("step") == "release"]
        info = {"error": error, "refusals": session.knob.refusals,
                "bridgeErrors": [e for e in session.bridge_errors if e.get("step") != "release"],
                "releaseErrors": release_errors,
                "knobInput": dict(session.knob.sent), "media": session.media_summary(),
                "picker": {"opened": session.windows.opened, "refused": session.windows.refused}}
        covers, icons = write_media(session, out_dir)
        if name == "stills":
            payload = {"schema": SCHEMA, "name": "stills", "firmware": FI.FIRMWARE, "app": FI.APP_VERSION,
                       "capabilities": deepcopy(CC57_CAPABILITIES), "stills": snaps or [], "covers": covers, "icons": icons}
            used = {s_.get("frame", {}).get("artKey") for s_ in payload["stills"]} - {None, ""}
            used_icons = {s_.get("frame", {}).get("iconKey") for s_ in payload["stills"]} - {None, ""}
            maps = {"schema": "desk-dial-button-maps/1", "firmware": FI.FIRMWARE, "app": FI.APP_VERSION,
                    "screens": [{k: s_.get(k) for k in ("name", "mode", "layout", "buttons", "holdAction", "feel",
                                                        "profile", "navigator", "skipped")} for s_ in payload["stills"]]}
            write_json(out_dir / "button-maps.json", maps)
        else:
            rec.finish(duration_ms=18000 if name == "story-day" else None)
            payload = rec.to_json(covers, icons, CC57_CAPABILITIES)
            frames = [e["frame"] for e in payload["events"] if e["kind"] == "frame"]
            used = {f.get("artKey") for f in frames} - {None, ""}
            used_icons = {f.get("iconKey") for f in frames} - {None, ""}
        missing = sorted(used - set(covers)) + sorted(used_icons - set(icons))
        info["mediaMissing"] = missing
        write_json(out_dir / f"{name}.json", payload)
        if write_jsonl:
            with (out_dir / f"{name}.records.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
                for record in recorder.records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        result.update(info)
        result["screens"] = payload.get("screens") if name != "stills" else [s_["name"] for s_ in payload["stills"]]
        result["durationMs"] = payload.get("duration_ms")
        result["events"] = dict(Counter(e["kind"] for e in payload.get("events", [])))
        result["covers"], result["icons"] = len(covers), len(icons)
    return result


def write_media(session, out_dir):
    covers, icons = {}, {}
    (out_dir / "covers").mkdir(parents=True, exist_ok=True)
    (out_dir / "icons").mkdir(parents=True, exist_ok=True)
    for key, data in session.media_bytes["cover"].items():
        path = out_dir / "covers" / f"{key}.jpg"
        if not path.exists():
            path.write_bytes(data)
        covers[key] = f"covers/{key}.jpg"
    for key, data in session.media_bytes["icon"].items():
        path = out_dir / "icons" / f"{key}.bin"
        if not path.exists():
            path.write_bytes(data)
        icons[key] = f"icons/{key}.bin"
    return covers, icons


def write_json(path, payload):
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    FI.check(text, path.name)
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--jsonl", action="store_true", help="also write <scene>.records.jsonl for parse_tests.py --frames")
    ap.add_argument("scenes", nargs="*")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    wanted = a.scenes or [*SCENES, "stills"]
    broken = False
    for name in wanted:
        if name not in SCENES and name != "stills":
            raise SystemExit(f"unknown scene {name}")
        result = run_scene(name, a.out, a.jsonl)
        shown = result["screens"]
        if name != "stills":
            shown = [f"{s['t']}:{s['mode']}/{s['layout']}" for s in shown]
        print(f"{name}: {result['durationMs']} ms, events {result['events']}, covers {result['covers']}, icons "
              f"{result['icons']}, missing {result['mediaMissing']}, refusals {len(result['refusals'])}, "
              f"bridgeErrors {len(result['bridgeErrors'])}, picker {result['picker']}"
              + (f", ERROR {result['error']}" if result["error"] else ""), flush=True)
        print("   screens: " + " -> ".join(map(str, shown)), flush=True)
        broken = broken or bool(result["error"] or result["refusals"] or result["bridgeErrors"] or result["mediaMissing"])
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
