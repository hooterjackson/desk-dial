"""Knob loops from the true-to-app recordings (capture.py -> recording.py seam), plus the stills and
the cheat sheet built from the same recordings.

Every loop here is one recording (`<recordings>/<name>.json`, schema desk-dial-recording/1) cut to its
best 6-9 s window with `t_start` / `t_end` on the output clock (the recording's `screens` list and its
`note` events say where the screens change), rendered by recording.knob_frames: the LCD from the
firmware's own renderer (knob-anim), the ring and the four button lights from the LED twin, composited on
knob_scenes.KnobDevice at scale 1.1 (418 x 484 px, or 396 x 396 with crop_ring). The WebP is the README's
<picture> source, the GIF its fallback, both within gates.py's caps.

Recordings are looked up in, in order: `$DESK_DIAL_RECORDINGS`, `<ctx.work>/recordings`; a missing scene
is re-captured there with capture.run_scene (headless, fictional data, no device, no network).

Registry contract: SCENES = {name: (source label, fn)}; fn(ctx) returns the Paths it wrote, each tagged
with ctx.produced(path, source). All imports stay inside the functions.
"""
from __future__ import annotations

import os
from pathlib import Path

LCD = "firmware LCD renderer"

# name -> (t_start, t_end, crop_ring, webp_cap)   times in ms on the recording's output clock
#   music-volume     62 -> 97, three slow detents to 100, the two refused pushes at 3914 / 4164 (lim +1), then
#                    back down; the nowPlaying rest at 9520 is left out.
#   music-lists      Music at 118, Recently Added at 926 (6 detents), 3 = Playlists at 5185 (3 detents), 3 again
#                    = Recent at 10527 is left out (loops back to the Music tap).
#   music-tracks-seek  Tracks at 926, 4 = Play the focused row (nudge) at 3732, Seek at 4943, 3 = Set at 7673.
#   music-playpause  4.9 s recording held to 6.0 s: 4 = Pause at 117 (acts on release), 4 = Play at 2212.
#   music-hold-queue Recently Added at 926, hold 4 from 2929, the fill matures at 3929 (thump), the landing.
#   lights-brightness  Lights at 27, lightsbig 418 .. 5426 (30 -> 75 %, dimmer feel).
#   lights-temperature 3 = Temp at 509 (Temp lit, ctemp ring), lightsbig 1016 .. 3732, 3 again at 5577.
#   lights-scenes    2 = Scenes at 509, two detents Focus -> Movie, 4 = Run at 3018, "Scene running".
#   lights-power     4 = All off at 514 (confirm.off), 4 = Turn on at 2609, 1 = Home at 4300, hold 4 = Knob to
#                    lights 5303 .. 6433, three detents on the Home lights domain 7243 .. 9262.
#   story-day        the whole 18 s day (volume, Music, Recently Added, Play, hold 1 Home, Lights, Scenes, Home).
#   windows-knob     2 = Win opens the picker at 142, Snap left 2610, Snap right 4622, Home, Win again 6914,
#                    4 = Switch at 8923 (docs pages only).
CUTS = {
    "music-volume":       (0,    9000,  True,  1_200_000),
    "music-lists":        (600,  9600,  False, 1_200_000),
    "music-tracks-seek":  (600,  9600,  False, 1_200_000),
    "music-playpause":    (0,    6000,  False, 1_200_000),
    "music-hold-queue":   (400,  7600,  False, 1_200_000),
    "lights-brightness":  (0,    8500,  True,  1_200_000),
    "lights-temperature": (0,    8400,  False, 1_200_000),
    "lights-scenes":      (0,    7000,  False, 1_200_000),
    "lights-power":       (0,    9000,  False, 1_200_000),
    "story-day":          (0,    18000, False, 1_600_000),
    "windows-knob":       (300,  9300,  False, 1_200_000),
}
STILLS_CAPTIONS = ["Home", "Music", "Recently Added", "Playlists", "Tracks", "Seek", "Up next", "Windows",
                   "Lights", "Colour temperature", "Scenes", "Onshape"]


# ------------------------------------------------------------------ where the recordings live
def recordings_dir(work) -> Path:
    env = os.environ.get("DESK_DIAL_RECORDINGS")
    return Path(env) if env else Path(work) / "recordings"


def recording_path(work, name: str, log=print) -> Path:
    """`<recordings>/<name>.json`, captured on demand (capture.run_scene) when missing."""
    d = recordings_dir(work)
    p = d / f"{name}.json"
    if not p.exists():
        d.mkdir(parents=True, exist_ok=True)
        log(f"{p.name} is missing: capturing it headlessly into {d}")
        import capture
        capture.run_scene(name, d)
    if not p.exists():
        raise FileNotFoundError(f"{p} was not produced by capture.run_scene")
    return p


def cut_frames(rec, knob_anim, work, t_start, t_end, crop_ring, tag=""):
    import recording
    return recording.knob_frames(rec, knob_anim, work, scale=1.1, crop_ring=crop_ring, t_start=t_start,
                                 t_end=t_end, tag=tag)


# ------------------------------------------------------------------ the loops
def _loop(name):
    def run(ctx) -> list[Path]:
        import recording
        t0, t1, crop, cap = CUTS[name]
        rec = recording.load(recording_path(ctx.work, name, ctx.log))
        # t1 may exceed the recording (music-playpause, 4.9 s held to 6 s): the renderer and the twin simply
        # keep the last state, so the loop ends on a rest.
        frames = cut_frames(rec, ctx.knob_anim, ctx.work, t0, t1, crop, tag=f"-{t0}-{t1}")
        gif, webp = recording.save_loop(frames, rec["fps"], name, ctx.out, webp_cap=cap)
        ctx.log(f"{len(frames)} frames at {rec['fps']} fps, window {t0}..{t1} ms, {frames[0].size[0]} px wide: "
                f"webp {webp.stat().st_size} B, gif {gif.stat().st_size} B")
        return [ctx.produced(webp, LCD), ctx.produced(gif, LCD)]
    return run


def _story_day(ctx) -> list[Path]:
    """The whole recording; the GIF ladder of recording.save_loop (fewer frames, then smaller) lands it
    under the 2.9 MB GIF cap, the WebP under 1.6 MB."""
    return _loop("story-day")(ctx)


# ------------------------------------------------------------------ stills, button maps, cheat sheet
def _knob_screens(ctx) -> list[Path]:
    import stills as S
    paths = S.render(ctx.knob_anim, ctx.work, ctx.out, stills_json=recording_path(ctx.work, "stills", ctx.log))
    return [ctx.produced(p, LCD) for p in paths]


def _button_maps(ctx) -> list[Path]:
    import stills as S
    rd = recordings_dir(ctx.work)
    paths = S.button_maps(ctx.knob_anim, ctx.work, ctx.out, stills_json=recording_path(ctx.work, "stills", ctx.log),
                          button_maps_json=rd / "button-maps.json")
    return [ctx.produced(p, LCD) for p in paths]


def _cheat_sheet(ctx) -> list[Path]:
    import cheat_sheet as C
    rd = recordings_dir(ctx.work)
    paths = C.render(ctx.knob_anim, ctx.work, ctx.out, stills_json=recording_path(ctx.work, "stills", ctx.log),
                     button_maps_json=rd / "button-maps.json")
    return [ctx.produced(p, LCD) for p in paths]


SCENES = {
    "music-volume": (LCD, _loop("music-volume")),
    "music-lists": (LCD, _loop("music-lists")),
    "music-tracks-seek": (LCD, _loop("music-tracks-seek")),
    "music-playpause": (LCD, _loop("music-playpause")),
    "music-hold-queue": (LCD, _loop("music-hold-queue")),
    "lights-brightness": (LCD, _loop("lights-brightness")),
    "lights-temperature": (LCD, _loop("lights-temperature")),
    "lights-scenes": (LCD, _loop("lights-scenes")),
    "lights-power": (LCD, _loop("lights-power")),
    "story-day": (LCD, _story_day),
    "windows-knob": (LCD, _loop("windows-knob")),
    "knob-screens": (LCD, _knob_screens),
    "button-maps": (LCD, _button_maps),
    "cheat-sheet": (LCD, _cheat_sheet),
}
