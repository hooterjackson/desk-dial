"""Desk Dial r3 release 1 (+ r3.1) audit capture: every r3 path at presentation 6 through the real companion stack.

r3.1 (2026-09-29 feedback round): button 4 acts on its release and its 1.0 s hold (`kh` of slot 3) is
the secondary action: Home's knob domain swap (volume <-> the demo area's brightness, 4 = All off / Turn
on there), Play next in Recently Added / Playlists and Up next; Recently Added 3 toggles the list's
source to Favourite playlists (MUSIC › PLAYLISTS, the explorer opens on that tab); Tracks browses the
whole queue and 4 jumps to the focused row. The Home Assistant simulator runs the area bridge (three
demo lights) when the simulator offers it.

The real ``Controller`` + ``Runtime`` + ``DeviceBridge`` (capture_session_frames.py's Session: an in-memory
fake knob, the section 16 simulator fakes, a FakeStagePresenter) against a presentation-6 knob with a
SimulatedHomeAssistant, driven through every path of the r3 README section 1.2 button maps (options 1a +
1e) and the r2.2 maps release 1 keeps (Recently Added, explorer, Tracks, Seek, Up next, the picker).

The picker models the Windows foreground rule the live adapter meets (``WindowsAdapter.show`` raises
OSError when SetForegroundWindow is not granted): a show succeeds only inside the grant of the knob's
F24 key press (the WM_HOTKEY path), never from a serial ``kd`` alone.

Each step keeps (``audit``): the controller mode, the frame on the knob (as the bridge sent it), the
presenter effects posted and whether the picker opened. Every ``{"frame":…}`` / ``{"control":…}`` line
is recorded like capture_session_frames.py, so the capture replays through the firmware parser
(``harness/parse_tests.py --frames``) and the LVGL harness.

Usage: .venv\\Scripts\\python.exe tests\\tools\\capture_r3_session.py [--out capture.jsonl]
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import capture_session_frames as csf  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import SimulatedHomeAssistant  # noqa: E402

CC54D_CAPABILITIES = {**deepcopy(csf.CC54_CAPABILITIES), "presentation": 6}
DEFAULT_OUTPUT = csf.ROOT.parent / "harness" / "build" / "r3-capture" / "session.jsonl"


class ForegroundWindows(csf.ScriptedWindows):
    """The picker under the Windows foreground rule: show() needs the F24 grant (else OSError, as
    WindowsAdapter.show when SetForegroundWindow is refused)."""

    def __init__(self, controls):
        super().__init__(controls)
        self.grant = False
        self.opened = 0
        self.refused = 0

    def show(self, snapshot):
        granted, self.grant = self.grant, False
        if not granted:
            self.refused += 1
            raise OSError("Windows did not grant focus to the picker. Open it with the registered F24 key.")
        self.opened += 1
        super().show(snapshot)


class R3Session(csf.Session):
    def __init__(self, recorder, backup_dir):
        try:
            self.ha = SimulatedHomeAssistant(csf.SimControls(), area="demo")  # r3.1: the simulator's demo area
        except TypeError:
            self.ha = SimulatedHomeAssistant(csf.SimControls())               # a release-1 simulator
        with patch.object(csf, "ScriptedWindows", ForegroundWindows), \
                patch.object(csf, "Runtime", lambda *a, **k: Runtime(*a, ha=self.ha, **k)):
            csf.FIRMWARE.setdefault("p6", "1.0.0-cc5.4")
            super().__init__("p6", CC54D_CAPABILITIES, recorder, backup_dir)
        self.audit = []

    def press(self, raw):
        """A short press; when the knob also sends F24 (hid:1) the WM_HOTKEY path runs first."""
        before = self.knob.sent["hid"]
        self.knob.press(raw)
        if self.knob.sent["hid"] != before:
            self.windows.grant = True
            self.runtime.hotkey()
        self.settle()

    def lights_lane(self):
        self.drain("home_lane")

    def hold(self, raw):
        """A held button: `kd`, the firmware's `kh` (button 1 600 ms, r3.1 button 4 1.0 s), `ku`."""
        self.knob.down(raw)
        self.settle()
        self.knob.long_press(raw)
        self.settle()
        self.knob.up(raw)
        self.settle()

    def note(self, path, expected):
        """One audit row: what the knob shows now and which surfaces opened."""
        frame = deepcopy(self.knob.frame) or {}
        self.audit.append({
            "path": path, "expected": expected, "mode": self.controller.screen.mode,
            "layout": frame.get("layout"), "heading": frame.get("heading", ""), "title": frame.get("title", ""),
            "subtitle": frame.get("subtitle", ""), "meta": frame.get("meta", ""), "status": frame.get("status", ""),
            "value": frame.get("value", ""),
            "buttons": [(b.get("icon"), b.get("label"), b.get("enabled")) for b in frame.get("buttons") or ()],
            "windowsButton": (self.knob.control or {}).get("windowsButton"),
            "windowsHid": (self.knob.control or {}).get("windowsHidEnabled"),
            "stage": [p["kind"] for p in self.stage.posted if p["kind"].endswith(("_open", "_close"))],
            "pickerOpened": self.windows.opened, "pickerRefused": self.windows.refused,
            "notice": self.controller.notice, "n": len(self.recorder.records),
        })


def script(s):
    s.step("startup/connect")
    s.bridge.submit("connect", "COM-CAPTURE")
    s.settle()
    s.run("audio", "state")
    s.settle()
    s.expect("launcher")
    s.note("Home", "launcher, knob = volume, 1 Music · 2 Win · 3 Lights · 4 Play/Pause")

    # Home (1a): turn = volume, 4 = Play/Pause.
    s.step("home/turn")
    s.turn_to(s.knob.position + 3)
    s.note("Home · turn", "volume reveal")
    s.run("audio", "volume")
    s.wait(1.6)
    s.step("home/4")
    s.press(3)
    s.run("audio", "transport")
    s.note("Home · 4", "pause (button 4 = Play)")
    s.press(3)
    s.run("audio", "transport")
    s.note("Home · 4 again", "playing")

    # r3.1 Home hold 4: the knob sets the Hall area's brightness; 4 = All off / Turn on; hold 4 back.
    s.step("home/hold4")
    s.hold(3)
    s.lights_lane()
    s.note("Home · hold 4", "knob = Hall brightness: LIGHTS, `Hall · bri% · K`, `Knob sets brightness`")
    s.expect("launcher")
    s.turn_to(s.knob.position + 4)
    s.lights_lane()
    s.note("Home (lights) · turn", "Brightness big reveal")
    s.wait(2.8)
    s.lights_lane()
    s.press(3)
    s.lights_lane()
    s.note("Home (lights) · 4", "All off → Lights off / Tap 4 to turn on")
    s.wait(1.6)
    s.press(3)
    s.lights_lane()
    s.note("Home (lights) · 4 again", "Turn on")
    s.wait(1.6)
    s.hold(3)
    s.note("Home · hold 4 again", "knob = volume, `Knob sets volume`")
    s.expect("launcher")
    s.wait(1.6)

    # Home 2: Windows opens the picker directly (F24 on the Win slot); picker map; Switch → Home.
    s.step("windows/open")
    s.press(1)
    s.note("Home · 2", "picker opens on screen; knob Windows list")
    s.expect("windows")
    s.step("windows/turn")
    for position in (2, 3):
        s.turn_to(position)
    s.note("Windows · turn", "highlight moves")
    s.step("windows/1")
    s.press(0)
    s.wait(0.5)
    s.note("Windows · 1", "Home (restores focus)")
    s.expect("launcher")
    s.step("windows/snap")
    s.press(1)
    s.expect("windows")
    s.turn_to(1)
    s.wait(0.2)
    s.press(1)
    s.wait(0.5)
    s.note("Windows · 2", "snap left")
    s.press(2)
    s.wait(1.0)
    s.note("Windows · 3", "snap right, the pair closes → Home")
    s.expect("launcher")
    s.step("windows/switch")
    s.press(1)
    s.turn_to(4)
    s.press(3)
    s.wait(0.5)
    s.note("Windows · 4", "Switch → Home")
    s.expect("launcher")
    s.step("windows/hold")
    s.press(1)
    s.knob.down(0)
    s.settle()
    s.knob.long_press(0)
    s.settle()
    s.knob.up(0)
    s.settle()
    s.note("Windows · hold 1", "Home")
    s.expect("launcher")

    # Home 1: Music.
    s.step("music/enter")
    s.wait(0.8)            # README 1 overshoot guard: a 1 within 700 ms of arriving Home is ignored
    s.press(0)
    s.note("Home · 1", "Music: 1 Home · 2 Recent · 3 Tracks · 4 Play/Pause, knob = volume")
    s.expect("home")
    s.turn_to(s.knob.position - 2)
    s.run("audio", "volume")
    s.note("Music · turn", "volume")
    s.wait(1.6)
    s.press(3)
    s.run("audio", "transport")
    s.note("Music · 4", "Play/Pause")
    s.press(3)
    s.run("audio", "transport")

    # Music 2: Recently Added (r2.2 map).
    s.step("recent/enter")
    s.press(1)
    s.note("Music · 2 (loading)", "Recently Added list, Loading…")
    s.run("library", "recent")
    s.note("Music · 2", "Recently Added list: title / artist / n of N")
    s.expect("recent")
    for position in (1, 2, 3):
        s.turn_to(position)
    s.note("Recent · turn", "list scrolls")
    s.step("recent/1")
    s.press(0)
    s.note("Recent · 1", "Back → Music")
    s.expect("home")
    s.step("explorer/open")
    s.press(1)
    s.run("library", "recent")
    s.turn_to(2)
    s.press(1)
    s.drain("lookahead")
    s.note("Recent · 2", "explorer opens full screen (same album)")
    s.expect("explorer")
    s.turn_to(3)
    s.note("Explorer · turn", "covers scroll")
    s.press(2)
    s.wait(0.25)
    s.run("library", "favourite_playlists", optional=True)
    s.drain("lookahead")
    s.note("Explorer · 3", "Favourite playlists tab")
    s.press(1)
    s.wait(0.25)
    s.note("Explorer · 2", "Recently Added tab")
    s.press(0)
    s.wait(0.5)
    s.note("Explorer · 1", "Back → knob list, same album")
    s.expect("recent")
    s.press(1)
    s.drain("lookahead")
    s.press(3)
    s.wait(0.4)
    s.run("library", "resolve", optional=True)
    s.run("audio", "play_items", optional=True)
    s.wait(0.5)
    s.note("Explorer · 4", "Play → Music now playing")
    s.step("recent/playlists")
    if s.controller.screen.mode != "home":
        s.press(0)
    s.press(1)
    s.run("library", "recent")
    s.turn_to(2)
    s.press(2)
    s.run("library", "favourite_playlists", optional=True)
    s.drain("lookahead")
    s.note("Recent · 3", "Favourite playlists: MUSIC › PLAYLISTS, n songs, 3 = Recent")
    s.expect("recent")
    s.turn_to(1)
    s.drain("lookahead")
    s.note("Playlists · turn", "next playlist")
    s.step("playlists/hold4")
    s.hold(3)
    s.run("library", "resolve", optional=True)
    s.run("audio", "play_next", optional=True)
    s.wait(1.6)
    s.note("Playlists · hold 4", "Play next (the playlist queued after the playing song)")
    s.press(1)
    s.drain("lookahead")
    s.note("Playlists · 2", "the explorer opens on the Favourites tab, same playlist")
    s.expect("explorer")
    s.press(0)
    s.wait(0.5)
    s.note("Explorer · 1 (Playlists)", "Back → the knob list on Playlists")
    s.expect("recent")
    s.press(2)
    s.note("Playlists · 3", "back to Recently Added, same album")
    s.step("recent/playnext")
    s.hold(3)
    s.run("library", "resolve", optional=True)
    s.run("audio", "play_next", optional=True)
    s.wait(1.6)
    s.note("Recent · hold 4", "Play next (queued)")
    s.step("recent/play")
    s.turn_to(3)
    s.press(3)
    s.run("library", "resolve", optional=True)
    s.run("audio", "play_items", optional=True)
    s.wait(0.5)
    s.note("Recent · 4", "Play (replaces queue) → Music")

    # Music 3: Tracks (r2.2 map), Seek, Up next.
    s.step("tracks/enter")
    if s.controller.screen.mode != "home":
        s.press(0)
    s.press(2)
    s.run("audio", "queue_window", optional=True)
    s.note("Music · 3", "Tracks on the playing row: `Turn to browse the queue`")
    s.expect("tracks")
    s.turn_to(s.knob.position + 2)
    s.run("audio", "queue_window", optional=True)
    s.note("Tracks · turn", "the whole queue: `Skip to · n / T`, `Press 4 to play`")
    s.press(3)
    s.run("audio", "jump")
    s.run("audio", "queue_window", optional=True)
    s.wait(0.6)
    s.note("Tracks · 4", "jumps there; Tracks re-centres on the new playing row")
    s.expect("tracks")
    s.press(2)
    s.note("Tracks · 3", "Seek")
    s.expect("seek")
    s.turn_to(s.knob.position + 4)
    s.note("Seek · turn", "scrub")
    s.run("audio", "seek", optional=True)
    s.press(0)
    s.note("Seek · 1", "Back → Tracks")
    s.step("upnext/open")
    if s.controller.screen.mode != "tracks":
        s.press(2) if s.controller.screen.mode == "home" else None
    s.press(1)
    s.flush_audio()
    s.drain("lookahead")
    s.drain("library")
    s.note("Tracks · 2", "Up next opens full screen")
    s.expect("upnext")
    s.turn_to(s.knob.position + 1)
    s.drain("lookahead")
    s.note("Up next · turn", "rows scroll")
    s.press(2)
    s.run("library", "like", optional=True)
    s.wait(1.0)
    s.note("Up next · 3", "Like")
    s.hold(3)
    s.run("audio", "move_next", optional=True)
    s.wait(0.6)
    s.flush_audio()
    s.drain("lookahead")
    s.note("Up next · hold 4", "Play next: the focused row moves after the playing one")
    s.expect("upnext")
    s.press(1)
    s.run("audio", "shuffle_reorder", optional=True)
    s.wait(0.3)
    s.flush_audio()
    s.drain("lookahead")
    s.note("Up next · 2", "Shuffle")
    s.press(0)
    s.wait(0.5)
    s.note("Up next · 1", "Back → Tracks")
    s.expect("tracks")
    s.press(1)
    s.flush_audio()
    s.drain("lookahead")
    s.turn_to(s.knob.position + 1)
    s.press(3)
    s.run("audio", "jump", optional=True)
    s.wait(0.6)
    s.note("Up next · 4", "Play this track → Music")
    s.step("music/hold")
    s.knob.down(0)
    s.settle()
    s.knob.long_press(0)
    s.settle()
    s.knob.up(0)
    s.settle()
    s.note("hold 1 (from Music)", "Home")
    s.expect("launcher")

    # Home 3: Lights (1e).
    s.step("lights/enter")
    s.press(2)
    s.lights_lane()
    s.note("Home · 3", "Lights: scene / bri% · K, knob = brightness")
    s.expect("lights")
    s.turn_to(s.knob.position + 5)
    s.lights_lane()
    s.note("Lights · turn", "Brightness big reveal")
    s.wait(2.8)
    s.lights_lane()
    s.note("Lights · settle", "text screen, `· adjusted`")
    s.press(2)
    s.note("Lights · 3", "temperature mode, 3 lit, meta Knob: temperature")
    s.turn_to(s.knob.position + 3)
    s.lights_lane()
    s.note("Lights · turn (temp)", "Colour temperature big reveal (K)")
    s.wait(2.8)
    s.press(2)
    s.note("Lights · 3 again", "back to brightness")
    s.press(3)
    s.lights_lane()
    s.note("Lights · 4", "All off → Lights off / Tap 4 to turn on")
    s.turn_to(s.knob.position + 1)
    s.lights_lane()
    s.note("Lights · turn while off", "turns on at 1 %")
    s.wait(2.8)
    s.press(3)
    s.lights_lane()
    s.press(3)
    s.lights_lane()
    s.note("Lights · 4 (Turn on)", "restores the snapshot")
    s.wait(2.8)
    s.press(1)
    s.note("Lights · 2", "Scenes list: prev / current / next, n / N · bri · K")
    s.expect("scenes")
    s.turn_to(2)
    s.note("Scenes · turn", "next scene")
    s.press(1)
    s.note("Scenes · 2", "refused: Turn to choose · 4 runs it")
    s.press(2)
    s.note("Scenes · 3", "refused: Turn to choose · 4 runs it")
    s.wait(2.5)
    s.press(3)
    s.lights_lane()
    s.note("Scenes · 4", "Run → Lights, `Scene running`")
    s.expect("lights")
    s.wait(2.5)
    s.press(1)
    s.note("Lights · 2 (after a run)", "Scenes list, `n / N · running now`")
    s.press(0)
    s.note("Scenes · 1", "Back → Lights")
    s.expect("lights")
    s.turn_to(s.knob.position + 2)
    s.lights_lane()
    s.wait(2.8)
    s.lights_lane()
    s.note("Lights · turn after a scene", "title `{Scene} · adjusted`")
    s.press(0)
    s.note("Lights · 1", "Home")
    s.expect("launcher")
    s.press(2)
    s.lights_lane()
    s.press(1)
    s.knob.down(0)
    s.settle()
    s.knob.long_press(0)
    s.settle()
    s.knob.up(0)
    s.settle()
    s.note("Scenes · hold 1", "Home")
    s.expect("launcher")

    s.step("release")
    s.bridge.submit("disconnect")
    s.settle()


def capture(out_path=None):
    """Run the r3 script; return (records, audit, info)."""
    clock = csf.Clock()
    recorder = csf.Recorder(clock)
    with tempfile.TemporaryDirectory(prefix="nanod-r3-capture-") as backups, \
            patch("control_center.runtime.ThreadPoolExecutor", csf.Lane), \
            patch("control_center.runtime.time", csf.RuntimeTime(clock)):
        session = R3Session(recorder, Path(backups) / "p6")
        error = None
        try:
            script(session)
        except csf.CaptureError as exc:
            error = str(exc)
            session.note("SCRIPT STOPPED", error)
        finally:
            session.close()
        info = {"error": error, "refusals": session.knob.refusals, "bridgeErrors": session.bridge_errors,
                "knobInput": dict(session.knob.sent), "stagePosted": dict(Counter(p["kind"] for p in session.stage.posted)),
                "picker": {"opened": session.windows.opened, "refused": session.windows.refused}}
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in recorder.records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        out_path.with_suffix(".audit.json").write_text(json.dumps({"audit": session.audit, "info": info},
                                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return recorder.records, session.audit, info


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    records, audit, info = capture(args.out)
    print(f"{len(records)} line(s) -> {args.out}")
    for row in audit:
        print(f"{row['path']:<26} {row['mode']:<9} {str(row['layout']):<10} {row['heading']!r} {row['title']!r} "
              f"{row['subtitle']!r} {row['meta']!r} {row['status']!r} stage={row['stage'][-1:] } "
              f"picker={row['pickerOpened']}/{row['pickerRefused']} notice={row['notice']!r}")
    print(json.dumps(info, ensure_ascii=False))
    return 1 if info["error"] or info["refusals"] or info["bridgeErrors"] else 0


if __name__ == "__main__":
    sys.exit(main())
