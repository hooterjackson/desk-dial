"""Hands-on LED tour for the current release (nanod_cc5_tooling.CURRENT; "Warm · alive" LEDs since
1.0.0-cc5.4, firmware/ALIVE.md revision 2 section 11.9; PRESENTATION_V5.md 7.3). For the one hardware window, with the user at the knob.

Quit the companion first (the tour claims the knob itself over raw serial, like check_nanod_cc5.py);
the knob must run the current release (CURRENT's capabilities presentation, and alive), or the tour refuses. Run with
the companion's interpreter:
  app\\.venv\\Scripts\\python.exe tools\\nanod_alive_tour.py

Type a command and Enter; heartbeats keep the claim while you look. `help` lists them:
  * screens (each a new control, so the knob plays its reveal): home (playing, song hand), paused
    (paused Play breathes GREEN, U1), nothing (idle view, Play/Tracks dim), volume (a sweep 40 -> 100
    -> 40 through amber and red), external (Changed on Sonos), recent, upnext (the Up next levels,
    now row 4), card (Sonos-shuffle card), liked (the liked heart, PINK 0.30, next to a dim Shuffle,
    WARM 0.14), seek (the Seek lap; turn it), explorer0 / explorer1 (the tab pair on/off), windows
    (the assigned snap side's colour), tracks. The ring follows your turns (value / index = position).
  * moments (a new feedback seq on the current screen): queued (sweep from 0), shuffle (scatter),
    like (pink bloom), unlike (nothing plays), snapleft / snapright (half-wash; on windows),
    started (wash in a colour), startedwarm (green bloom), err (Head shake), skipnext / skipprev
    (the skip sweep; on tracks).
  * Working comet: seekjump (a 5 s Seek jump, then a follow-up jump), playnext (an uncached Play
    next: pending 3 s, then queued).
  * motion and time: reduced on|off (reducedMotion), day, night (the latched clock).
  * tuning (latched until reboot; quit restores the defaults): pink 0|1|2|3 (ledPink: 0 the built-in,
    1 the design's 255,40,90 -> #FF051A, 2 softer 255,60,120 -> #FF0C30, 3 deeper 255,20,70 ->
    #FF0210; ALIVE.md 14 Q2), volfull on|off (ledVolFull: the amber/red body 1.0 instead of 0.62,
    U8), drive 1..255 (ledDrive), dither on|off (ledDither; off is the knob's default since the 2026-09-26
    user ruling, ALIVE.md 9: on re-enables the temporal dither to compare, without the brightness floor).
  * settling with the user (recorded in the evidence): pick pink 0|1|2|3, pick volfull on|off,
    confirm paused-green|headshake|wake|liked yes|no, note <text>.
  * quit: restores ledPink 0, ledVolFull off, the default drive, dither off (the default) and reducedMotion off,
    releases the knob and writes diagnostics/<CURRENT prefix>-led-tour.json (a new name, never overwriting).
No audible cues (only the turning test beeps), no Sonos, Apple Music, Windows or HID actions
(windowsHidEnabled is false in every control). Importing this module opens nothing.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import queue
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402

# The knob's stock profiles the check scripts claim with (inventory: ten profiles).
PROFILES = {"level": "BINARIS BEER", "list": "MIDI SKIPPER", "transport": "MIDI CLACK JONES"}
PINK_CANDIDATES = {0: ("built-in PINK", 0), 1: ("design 255,40,90", 0xFF051A),
                   2: ("softer, more magenta 255,60,120", 0xFF0C30), 3: ("deeper 255,20,70", 0xFF0210)}
CLOCK = {"day": 12 * 60, "night": 23 * 60}
SNAP_COLOR = 0x2B5A9A                 # an app accent (raw; the knob applies sat())
STARTED_COLOR = 0xE8452C              # a started album's accent (raw)
LIST_COLORS = [0x2B5A9A, 0xE8452C, 0x3AA655, 0xC9A227, 0x7A4FC2, 0x1C9DB5, 0xD23F7A, 0x8C8C8C]
SEEK_D = 210                          # the Seek song: 3:30
VOLUME_STEP_S = 0.08
EVIDENCE_NAME = "led-tour"
CONFIRMS = ("paused-green", "headshake", "wake", "liked")


def _button(label, icon, enabled=True, lit=None, color=None):
    button = {"label": label, "enabled": enabled, "icon": icon}
    if lit:
        button["lit"] = lit
    if color:
        button["color"] = color
    return button


def _base(layout, mode, title, subtitle="", **fields):
    frame = {"mode": mode, "target": "Hall", "value": "", "detail": "", "status": "", "layout": layout,
             "title": title, "subtitle": subtitle, "ledStyle": "color"}
    frame.update(fields)
    return frame


HOME_BUTTONS = [_button("Pause", "pause"), _button("Browse", "list"), _button("Tracks", "tracks"), _button("Win", "win")]


def screens():
    """name -> (frame, profile kind, max position, start position). Every frame is valid v5 content."""
    level = lambda v: {"style": "level", "value": v, "index": 0, "count": 101}  # noqa: E731
    paused = deepcopy(HOME_BUTTONS)
    paused[0] = _button("Play", "play")
    nothing = [_button("Play", "play", False), _button("Browse", "list"), _button("Tracks", "tracks", False),
               _button("Win", "win")]
    upnext_buttons = [_button("Back", "back"), _button("Shuffle", "shuffle", lit="off"), _button("Like", "heart"),
                      _button("Play", "play")]
    liked = [_button("Back", "back"), _button("Shuffle", "shuffle", False), _button("Like", "heart", lit="on"),
             _button("Play", "play")]
    selection = lambda index, count, **ring: {"style": "selection", "value": 0, "index": index, "count": count,  # noqa: E731
                                              "colors": [LIST_COLORS[i % len(LIST_COLORS)] for i in range(count)], **ring}
    out = {
        "home": (_base("nowPlaying", "HOME", "Tour: playing", "Nano_D++", value="54%", confirmedVolume=54,
                       buttons=HOME_BUTTONS, ring=level(54), playing=True, progress={"pos": 60000, "dur": 240000}),
                 "level", 100, 54),
        "paused": (_base("nowPlaying", "HOME", "Tour: paused", "Play breathes green", value="54%", status="Paused",
                         confirmedVolume=54, buttons=paused, ring=level(54), playing=False), "level", 100, 54),
        "nothing": (_base("idle", "HOME", "", "", value="54%", confirmedVolume=54, restLayout="idle", buttons=nothing,
                          ring=level(54)), "level", 100, 54),
        "volume": (_base("volume", "VOLUME", "Tour: volume", "", value="40%", volumeCaption="Tour: volume",
                         confirmedVolume=40, buttons=HOME_BUTTONS, ring=level(40), playing=True), "level", 100, 40),
        "external": (_base("volume", "VOLUME", "Tour: external", "", value="62%", volumeCaption="Changed on Sonos",
                           status="Changed on Sonos", confirmedVolume=62, buttons=HOME_BUTTONS,
                           ring={**level(62), "external": True}, playing=True), "level", 100, 62),
        "recent": (_base("recent", "RECENTLY ADDED", "Tour: Recently Added", "Artist", heading="RECENTLY ADDED",
                         meta="3 / 8", buttons=[_button("Back", "back"), _button("Up next", "expand"),
                                                _button("Play next", "playnext"), _button("Play", "play")],
                         ring=selection(2, 8)), "list", 7, 2),
        "upnext": (_base("upnext", "RECENTLY ADDED", "Tour: Up next", "Artist", heading="UP NEXT", meta="6 / 12",
                         buttons=upnext_buttons, ring=selection(5, 12, now=4)), "list", 11, 5),
        "card": (_base("upnext", "RECENTLY ADDED", "Shuffled by Sonos", "", heading="UP NEXT", meta="6 / 6",
                       buttons=upnext_buttons, ring={**selection(5, 6, now=4, card=True), "colors": LIST_COLORS[:5] + [0]}),
                 "list", 5, 5),
        "liked": (_base("upnext", "RECENTLY ADDED", "Tour: liked", "Liked heart vs dim Shuffle", heading="UP NEXT",
                        meta="6 / 12 · playing", buttons=liked, ring=selection(4, 12, now=4)), "list", 11, 4),
        "seek": (_base("seek", "TRACKS", "Tour: Seek", "", heading="SEEK", meta="of 3:30",
                       buttons=[_button("Back", "back"), _button("Up next", "expand"), _button("Seek", "seek", lit="on"),
                                _button("Next", "next", False)],
                       ring={"style": "lap", "value": 0, "index": 74, "count": SEEK_D}), "transport", SEEK_D - 3, 74),
        "explorer0": (_base("explorer", "RECENTLY ADDED", "Tour: explorer", "Recent tab", heading="RECENT", page=0,
                            meta="2 / 8", buttons=[_button("Back", "back"), _button("Recent", "clock", lit="on"),
                                                   _button("Favourites", "playlists", lit="off"), _button("Play", "play")],
                            ring=selection(1, 8)), "list", 7, 1),
        "explorer1": (_base("explorer", "RECENTLY ADDED", "Tour: explorer", "Favourites tab", heading="FAVOURITES",
                            page=1, meta="1 / 4", buttons=[_button("Back", "back"), _button("Recent", "clock", lit="off"),
                                                           _button("Favourites", "playlists", lit="on"),
                                                           _button("Play", "play")],
                            ring=selection(0, 4)), "list", 3, 0),
        "windows": (_base("windows", "WINDOWS", "Tour: windows", "Word", meta="Left: Word · pick right",
                          buttons=[_button("Back", "back"), _button("Left", "snapleft", lit="on", color=SNAP_COLOR),
                                   _button("Right", "snapright"), _button("Switch", "switch")],
                          ring={"style": "selection", "value": 0, "index": 1, "count": 3,
                                "colors": [SNAP_COLOR, 0x1C9DB5, 0xD23F7A]}), "list", 2, 1),
        "tracks": (_base("tracks", "TRACKS", "Tour: tracks", "Next: Tour", heading="TRACKS", meta="Press 4 to skip",
                         buttons=[_button("Back", "back"), _button("Up next", "expand"), _button("Seek", "seek"),
                                  _button("Next", "next")],
                         ring={"style": "transport", "value": 0, "index": 1, "count": 3}), "transport", 2, 1),
    }
    return out


MOMENTS = {   # name -> (screen it belongs on or None = the current one, feedback without seq)
    "queued": ("recent", {"kind": "ok", "moment": "queued"}),
    "shuffle": ("upnext", {"kind": "ok", "moment": "shuffle"}),
    "like": ("upnext", {"kind": "ok", "moment": "like"}),
    "unlike": ("liked", {"kind": "ok", "moment": "unlike"}),
    "snapleft": ("windows", {"kind": "ok", "moment": "snap", "side": -1, "color": SNAP_COLOR}),
    "snapright": ("windows", {"kind": "ok", "moment": "snap", "side": 1, "color": SNAP_COLOR}),
    "started": ("home", {"kind": "ok", "moment": "started", "color": STARTED_COLOR}),
    "startedwarm": ("home", {"kind": "ok", "moment": "started"}),
    "err": (None, {"kind": "err"}),
    "skipnext": ("tracks", {"kind": "ok", "skip": 1}),
    "skipprev": ("tracks", {"kind": "ok", "skip": -1}),
}
HELP = __doc__[__doc__.index("  * screens"):__doc__.index("No audible cues")]


class Tour:
    """One claimed tour session over a tooling.RawKnob (unpaced). `validate(frame)` returns the names
    of invalid values (the companion's device.v5_parse reading, empty = the knob accepts it)."""

    def __init__(self, knob, capabilities, validate, *, first_id=5001, clock=time.monotonic, out=print):
        self.knob, self.capabilities, self.validate, self.out, self.clock = knob, capabilities, validate, out, clock
        self.next_id, self.seq = first_id, 1
        alive = capabilities.get(t.presentation().ALIVE_CAPABILITY) or {}
        self.default_drive = alive.get("drive", t.ALIVE_DEFAULT_DRIVE)
        self.latched = {"clock": CLOCK["day"], "reducedMotion": False}
        self.screens = screens()
        self.name, self.frame, self.control_id, self.position = None, None, None, None
        self.timers = []                  # (due, action)
        self.log, self.settled = [], {"pink": None, "volFull": None, "confirm": {}, "notes": []}
        self.tuning = {"ledPink": None, "ledVolFull": None, "ledDrive": None, "ledDither": None}

    # --- frames ----------------------------------------------------------------------------
    def compose(self, frame):
        """The frame with the latched fields (ALIVE.md 3; PRESENTATION_V5 7): sent in every frame of the tour."""
        out = {**frame, **self.latched}
        for name, value in self.tuning.items():
            if value is not None:
                out[name] = value
        return out

    def send(self, frame):
        wire = self.compose(frame)
        invalid = self.validate(wire)
        if invalid:
            raise ValueError(f"tour frame invalid ({', '.join(invalid)}); nothing sent")
        self.knob.frame({**wire, "id": self.control_id})
        self.frame = frame
        return wire

    def enter(self, name):
        frame, kind, maximum, position = deepcopy(self.screens[name])
        cid, self.next_id = self.next_id, self.next_id + 1
        wire = self.compose(frame)
        invalid = self.validate(wire)
        if invalid:
            raise ValueError(f"tour screen {name} invalid ({', '.join(invalid)}); nothing sent")
        self.knob.enter(t.raw_control(cid, PROFILES[kind], maximum, position, wire))
        self.name, self.frame, self.control_id, self.position = name, frame, cid, position
        self.timers = []
        self.say(f"screen {name} (control {cid})")

    def moment(self, name):
        screen, feedback = MOMENTS[name]
        if screen and screen != self.name:
            self.enter(screen)
            self.knob.pump(1.0)                   # the reveal first; the moment on its own frame
        self.seq += 1
        frame = {**self.frame, "feedback": {**feedback, "seq": self.seq}}
        if name.startswith("started"):
            frame.pop("playing", None)            # M16: no playing on the frame carrying `started`
        self.send(frame)
        self.frame = {k: v for k, v in frame.items() if k != "feedback"}
        self.say(f"moment {name} (seq {self.seq})")

    # --- timed sequences ---------------------------------------------------------------------
    def after(self, seconds, action):
        self.timers.append((self.clock() + seconds, action))

    def volume_sweep(self):
        self.enter("volume")
        values = list(range(40, 101, 2)) + list(range(98, 39, -2))
        for n, value in enumerate(values, 1):
            self.after(n * VOLUME_STEP_S, lambda v=value: self.set_level(v))

    def set_level(self, value):
        ring = {**self.frame["ring"], "value": value}
        self.send({**self.frame, "ring": ring, "value": f"{value}%", "confirmedVolume": value})

    def seek_jump(self):
        """M33: the Working comet through a 5 s Seek jump, then a follow-up jump."""
        if self.name != "seek":
            self.enter("seek")
        self.send({**self.frame, "meta": "Jumping…", "activity": "pending"})
        self.after(2.0, lambda: self.send({**self.frame, "ring": {**self.frame["ring"], "index": 150}}))
        self.after(5.0, lambda: self.send({**self.frame, "meta": "of 3:30", "activity": "idle"}))
        self.after(6.0, lambda: self.send({**self.frame, "meta": "Jumping…", "activity": "pending",
                                           "ring": {**self.frame["ring"], "index": 30}}))
        self.after(8.0, lambda: self.send({**self.frame, "meta": "of 3:30", "activity": "idle"}))

    def play_next(self):
        """An uncached Play next: pending with `Queueing…` for 3 s, then the queued sweep."""
        if self.name != "recent":
            self.enter("recent")
        self.send({**self.frame, "meta": "Queueing…", "activity": "pending"})
        self.after(3.0, lambda: (self.send({**self.frame, "meta": "3 / 8", "activity": "idle"}), self.moment("queued")))

    def follow(self):
        """The ring follows the knob: level value, selection/transport/lap index = the claimed position."""
        position = None
        for _, message in self.knob.claimed_events[self._seen:]:
            if message.get("id") == self.control_id and "p" in message:
                position = message["p"]
        self._seen = len(self.knob.claimed_events)
        if position is None or position == self.position or self.frame is None:
            return
        self.position = position
        ring = dict(self.frame["ring"])
        if ring["style"] == "level":
            self.send({**self.frame, "ring": {**ring, "value": position}, "value": f"{position}%",
                       "confirmedVolume": position})
        elif ring["style"] in ("selection", "lap", "transport") and position < ring["count"]:
            fields = {"ring": {**ring, "index": position}}
            if ring.get("now", -1) >= 0 and ring.get("card") and position == ring["count"] - 1:
                fields["title"] = "Shuffled by Sonos"
            self.send({**self.frame, **fields})

    _seen = 0

    def tick(self):
        now = self.clock()
        due = [timer for timer in self.timers if timer[0] <= now]
        for timer in due:
            self.timers.remove(timer)
            timer[1]()
        self.follow()

    # --- commands ----------------------------------------------------------------------------
    def say(self, text):
        self.out(text)

    def dispatch(self, line):
        """Run one command line; False after quit."""
        words = line.strip().split()
        if not words:
            return True
        self.log.append({"t": round(self.knob.now(), 2), "command": " ".join(words)[:120]})
        cmd, args = words[0].lower(), words[1:]
        if cmd in ("quit", "exit", "q"):
            return False
        if cmd == "help":
            self.say(HELP)
        elif cmd == "volume":
            self.volume_sweep()
        elif cmd in self.screens:
            self.enter(cmd)
        elif cmd in MOMENTS:
            self.moment(cmd)
        elif cmd == "seekjump":
            self.seek_jump()
        elif cmd == "playnext":
            self.play_next()
        elif cmd == "reduced" and args and args[0] in ("on", "off"):
            self.latched["reducedMotion"] = args[0] == "on"
            self.resend(f"reducedMotion {self.latched['reducedMotion']}")
        elif cmd in CLOCK:
            self.latched["clock"] = CLOCK[cmd]
            self.resend(f"clock {cmd} ({CLOCK[cmd] // 60}:00)")
        elif cmd == "pink" and args and args[0].isdigit() and int(args[0]) in PINK_CANDIDATES:
            label, value = PINK_CANDIDATES[int(args[0])]
            self.tuning["ledPink"] = value
            self.resend(f"ledPink {value:#08x} ({label}); try: liked, like")
        elif cmd == "volfull" and args and args[0] in ("on", "off"):
            self.tuning["ledVolFull"] = args[0] == "on"
            self.resend(f"ledVolFull {self.tuning['ledVolFull']}; try: volume")
        elif cmd == "drive" and args and args[0].isdigit() and 1 <= int(args[0]) <= 255:
            self.tuning["ledDrive"] = int(args[0])
            self.resend(f"ledDrive {args[0]}")
        elif cmd == "dither" and args and args[0] in ("on", "off"):
            self.tuning["ledDither"] = args[0] == "on"
            self.resend(f"ledDither {self.tuning['ledDither']}")
        elif cmd == "pick" and len(args) == 2 and args[0] == "pink" and args[1].isdigit() \
                and int(args[1]) in PINK_CANDIDATES:
            label, value = PINK_CANDIDATES[int(args[1])]
            self.settled["pink"] = {"candidate": int(args[1]), "label": label, "ledPink": value}
            self.say(f"PINK picked: {label} ({value:#08x})")
        elif cmd == "pick" and len(args) == 2 and args[0] == "volfull" and args[1] in ("on", "off"):
            self.settled["volFull"] = args[1] == "on"
            self.say(f"volume body picked: {'1.0 (ledVolFull on, U8(b))' if args[1] == 'on' else '0.62 (U8(a))'}")
        elif cmd == "confirm" and len(args) == 2 and args[0] in CONFIRMS and args[1] in ("yes", "no"):
            self.settled["confirm"][args[0]] = args[1] == "yes"
            self.say(f"{args[0]}: {args[1]}")
        elif cmd == "note" and args:
            self.settled["notes"].append(" ".join(args)[:300])
            self.say("noted")
        else:
            self.say(f"unknown command {line.strip()!r}; type help")
        return True

    def resend(self, what):
        if self.frame is not None:
            self.send(self.frame)
        self.say(what)

    def restore_defaults(self):
        """quit: the latched tuning back to the knob's defaults (they would otherwise last until reboot)."""
        # ledDither False is the knob's default (ALIVE.md 9, user ruling 2026-09-26: dither off, brightness floor on).
        self.tuning = {"ledPink": 0, "ledVolFull": False, "ledDrive": self.default_drive, "ledDither": False}
        self.latched["reducedMotion"] = False
        if self.frame is not None and self.control_id is not None:
            self.send(self.frame)
            self.knob.pump(0.3)

    def record(self):
        return {"tool": "tools/nanod_alive_tour.py", "firmware": t.CURRENT.version,   # checked by open_session
                "contract": "ALIVE.md revision 2 section 11.9; PRESENTATION_V5.md 7.3",
                "capabilities": {k: self.capabilities.get(k) for k in ("presentation", t.presentation().ALIVE_CAPABILITY)},
                "settled": self.settled, "pinkCandidates": {str(k): {"label": v[0], "ledPink": v[1]}
                                                            for k, v in PINK_CANDIDATES.items()},
                "commands": self.log[-500:], "errors": self.knob.errors[-50:], "released": self.knob.released[-10:]}


def open_session(knob, out=print):
    """Release, read the capabilities; the tour needs the current release's presentation and alive."""
    knob.pump(0.3)
    knob.release()
    caps = knob.request({"capabilities": "?"}, lambda m: isinstance(m.get("capabilities"), dict),
                        what="capabilities")["capabilities"]
    problems = t.presentation_capability_problems(caps, t.CURRENT)
    if not isinstance(caps.get(t.presentation().ALIVE_CAPABILITY), dict):
        problems.append("no alive capability")
    if problems:
        raise RuntimeError(f"the knob does not run {t.CURRENT.version}: " + "; ".join(problems))
    return caps


def companion_validator():
    """device.v5_parse of the companion (the cc5.4 parser's reading): the invalid names of a frame."""
    if str(t.APP) not in sys.path:
        sys.path.insert(0, str(t.APP))
    from control_center import device
    return lambda frame: device.v5_parse(frame)[1] + device.alive_parse(frame)[1]


def stdin_lines():
    lines = queue.Queue()

    def reader():
        for line in sys.stdin:
            lines.put(line)
        lines.put(None)
    threading.Thread(target=reader, name="tour-stdin", daemon=True).start()
    return lines


def run(tour, lines, idle=0.05):
    """Command loop: heartbeats and timers run while waiting for the next line."""
    while True:
        try:
            line = lines.get_nowait()
        except queue.Empty:
            tour.knob.pump(idle)
            tour.tick()
            continue
        if line is None:
            return
        try:
            if not tour.dispatch(line):
                return
        except (ValueError, RuntimeError, TimeoutError) as exc:
            tour.say(f"! {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    t.console_utf8()
    t.require_companion_quit()
    port = t.find_app_port()
    knob = t.RawKnob(port, paced=False)
    tour = None
    try:
        caps = open_session(knob)
        tour = Tour(knob, caps, companion_validator())
        print(HELP, flush=True)
        tour.enter("home")
        run(tour, stdin_lines())
    finally:
        if tour is not None:
            try:
                tour.restore_defaults()
            except Exception as exc:          # the release below still runs
                print(f"! could not restore the tuning defaults: {exc}", flush=True)
        knob.release_quietly()
        knob.close()
        if tour is not None:
            path = t.write_new_json(t.DIAGNOSTICS / f"{t.CURRENT.prefix}-{EVIDENCE_NAME}.json", tour.record())
            print(f"evidence {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
