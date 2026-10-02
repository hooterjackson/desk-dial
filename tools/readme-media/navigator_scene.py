"""The r3 Navigator on the desktop (README "The Navigator"): navigator.webp / .gif, 1120 x 630.

The card is the companion's own Navigator: ``control_center.stage.scenes.navigator_render.HeadlessNavigator``
(the NavigatorEngine on the recording fake device, fake host, fake clock and a synchronous backdrop
capture), drawn by its PIL reference renderer. Its content is ``navigator_model.build_content(snap,
pressed)`` and its show / hide is ``navigator_model.Visibility`` (auto: 4 s after the last input at
Home and the space roots), so the words, the HOLD chips and the auto-hide are the app's own. The
Recently Added covers go through the app's cover path (``navigator_covers.NavigatorCovers`` over an
``ArtService``) with ``desktop_scene.FictionalCovers``: fixtures' procedural sleeves, never a download.

Sequence (fictional data, fixtures.py): Home with a song playing and the volume turning; 1 = Music;
2 = Recently Added, the covers land and the knob browses; hold 4 (the ``4 Queue`` chip fills over
the firmware's 1.0 s) and hold 1 (the ``1 Home`` chip fills over 0.6 s) back to Home; then nothing:
the card hides itself 4 s after the last input.

The backdrop is fixtures.desktop() at 2560 x 1440 (k = 2); the clip shows its left 1600 x 900
(where the card lives) resampled to 1120 x 630. Nothing reads the screen, no window is created.

Shared with hero_scene.py: ``NavRig`` (the engine plus the snapshot -> content -> post step),
``snapshot``, ``recent_items`` and the button sets.

Registry contract: SCENES = {"navigator": (STAGE, fn)}.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

STAGE = "app stage renderer"
FPS = 30
OUT_SIZE = (1120, 630)
MONITOR = (0, 0, 2560, 1440)                 # k = min(2560 / 1280, 1440 / 720) = 2
VIEW = (0, 270, 1600, 1170)                  # the part of the desktop the clip shows (16:9, card centred)
WEBP_CAP = 1_200_000                         # gates.CAPS["loop"]
GIF_CAP = 2_900_000

LAUNCHER_B = ["Music", "Win", "Lights", "Pause"]
MUSIC_B = ["Home", "Recent", "Tracks", "Pause"]
RECENT_B = ["Back", "Full screen", "Playlists", "Play"]
RECENT_COUNT = 26


def buttons(labels, disabled=()):
    return [{"label": l, "enabled": i not in disabled, "lit": None, "icon": ""} for i, l in enumerate(labels)]


def recent_items(count=RECENT_COUNT):
    """Recently Added as the controller's list items: fixtures' albums (cycled), each with a
    ``simulation://art/al<N>/...`` template that desktop_scene.FictionalCovers draws."""
    import fixtures as fx
    out = []
    for i in range(count):
        n = i % len(fx.ALBUMS)
        t, a, y, c, _s = fx.ALBUMS[n]
        out.append({"id": f"alb-{i}", "title": t, "artist": a, "year": y, "accent": fx.rgb_int(c), "kind": "album",
                    "art_template": f"simulation://art/al{n}/{{w}}x{{h}}bb.jpg", "art_max": 1400,
                    "art_bg": fx.rgb_int(c)})
    return out


def snapshot(mode, *, song=None, volume=48, volume_turning=False, art_key="", index=0, items=None,
             held=None, button_labels=None, position_s=0, duration_s=240, meta=None, frame_title=None,
             frame_subtitle=None):
    """A read_snapshot()-shaped dict for ``mode`` (launcher | home | recent). ``song``: (title, artist)."""
    from companion import APP_DIR  # noqa: F401  (the app on sys.path)
    hold4 = {"launcher": "Knob to lights", "recent": "Queue"}.get(mode, "")    # controller.hold_action
    title, artist = song or ("", "")
    snap = {"mode": mode, "spaces": True, "loaded": True, "home_domain": "volume", "hold4": hold4,
            "index": index, "volume": volume, "held": dict(held or {}),
            "state": {"title": title, "artist": artist, "playback": "PLAYING", "position_s": position_s,
                      "duration_s": duration_s, "volume": volume, "online": True, "playlist_position": 1,
                      "queue_length": 10},
            "frame": {"artKey": art_key}}
    if volume_turning:
        snap["frame"]["layout"] = "volume"
    if mode == "recent":
        items = items if items is not None else recent_items()
        cur = items[index] if items else {}
        snap["recent"] = items
        snap["list_source"] = "recent"
        snap["frame"].update({"title": frame_title or cur.get("title", ""),
                              "subtitle": frame_subtitle or cur.get("artist", ""),
                              "meta": meta or f"{index + 1} / {len(items)}"})
    labels = button_labels or {"launcher": LAUNCHER_B, "home": MUSIC_B, "recent": RECENT_B}[mode]
    snap["buttons"] = buttons(labels)
    return snap


class NavRig:
    """HeadlessNavigator over ``desk`` plus the app's visibility rule and the cover path.
    ``step(snap, pressed, inputs_now)`` posts what the controller would post at this frame;
    ``frame()`` renders the whole desktop with the card on it; ``tick()`` advances one frame."""

    def __init__(self, desk, monitor=MONITOR, art=None, fps=FPS):
        import desktop_scene as D
        from control_center import navigator_model as NM
        from control_center.stage.scenes import navigator_render as NR
        from control_center.stage.scenes.art import ArtService
        from control_center.stage.scenes.navigator_covers import NavigatorCovers
        self.NM, self.NR = NM, NR
        self.desk = desk
        self.nav = NR.HeadlessNavigator(desk, work=monitor, monitor=monitor)
        service = ArtService(sync=True, simulated=D.FictionalCovers(None))
        self.k = min((monitor[2] - monitor[0]) / 1280.0, (monitor[3] - monitor[1]) / 720.0)
        self.covers = (NavigatorCovers(service, k=self.k), service)
        self.art = dict(art or {})                # art key -> PIL image (the "now" card's cover)
        self.vis = NM.Visibility()
        self.now_ms = 0.0
        self.dt = 1000.0 / fps
        self._last = None
        self.posted = False

    def touch(self):
        self.vis.note_input(self.now_ms / 1000.0)

    def step(self, snap, pressed=None):
        content = self.NM.build_content(snap, pressed=pressed)
        art = {}
        if content is not None and content.kind == "covers":
            content, art = self.NR.with_recent_covers(content, snap, self.covers)
        if content is not None and content.art_key and content.art_key in self.art:
            art[content.art_key] = self.art[content.art_key]
        visible = self.vis.visible(self.now_ms / 1000.0, content)
        key = (content, visible, tuple(sorted(art)))
        if key != self._last:
            self.nav.post(content, visible=visible, art=art)
            self._last = key
            self.posted = True
        return content, visible

    def column(self):
        """The host column (RGB over the desktop) and its screen x, y; None before the first post."""
        if not self.posted or self.nav.engine.root is None:
            return None
        x, y, _w, _h = self.nav.engine.geometry.host
        return self.nav.render(), (x, y)

    def frame(self):
        img = self.desk.copy()
        col = self.column()
        if col is not None:
            img.paste(col[0], col[1])
        return img

    def tick(self):
        self.nav.advance(self.dt)
        self.now_ms += self.dt


# ------------------------------------------------------------------ the sequence
def timeline():
    """[(ms, action)] for the Navigator clip; actions mutate the state dict ``s``."""
    ev = []

    def at(ms, **change):
        ev.append((ms, change))

    at(300, mode="launcher", touch=True, turning=True)
    vol = 44
    for k in range(10):                                   # a turn: 44 -> 54 %
        vol += 1
        at(300 + k * 110, volume=vol, touch=True)
    at(2100, turning=False)
    at(2700, press=0, touch=True)                         # 1 = Music
    at(2780, mode="home")
    at(3900, press=1, touch=True)                         # 2 = Recent
    at(3980, mode="recent", index=0)
    for k, i in enumerate((1, 2, 3, 4, 5)):               # browse
        at(4800 + k * 330, index=i, touch=True)
    at(6800, hold=3, touch=True)                          # hold 4: the Queue chip fills over 1.0 s
    at(7800, hold=None, touch=True)
    at(8300, hold=0, touch=True)                          # hold 1: the Home chip fills over 0.6 s
    at(8900, hold=None, mode="launcher", index=0, touch=True)
    return ev, 8900 + 4000 + 900                          # auto-hide 4 s after the last input, then out


def navigator_frames(view=VIEW, out_size=OUT_SIZE):
    import fixtures as fx
    import desktop_scene as D
    desk = fx.desktop((MONITOR[2], MONITOR[3]))
    song = (fx.TRACKS[2][4], fx.ALBUMS[2][1])            # "Clearing" - North of June (fictional)
    art_key = "art:al2"
    rig = NavRig(desk, art={art_key: D.album_cover(2, 600)})
    items = recent_items()
    ev, end_ms = timeline()
    s = {"mode": None, "volume": 44, "turning": False, "index": 0, "hold": None, "hold_t0": 0.0,
         "press": None, "press_t0": -1e9}
    frames, ei = [], 0
    while rig.now_ms < end_ms:
        while ei < len(ev) and ev[ei][0] <= rig.now_ms:
            change = dict(ev[ei][1])
            if change.pop("touch", False):
                rig.touch()
            if "press" in change:
                s["press_t0"] = rig.now_ms
            if "hold" in change and change["hold"] is not None:
                s["hold_t0"] = rig.now_ms
            s.update(change)
            ei += 1
        if s["mode"] is not None:
            held = {}
            if s["hold"] is not None:
                held[s["hold"]] = (rig.now_ms - s["hold_t0"]) / 1000.0
                rig.touch()                               # a held key keeps the card up
            pressed = s["press"] if rig.now_ms - s["press_t0"] < 220 else None   # NM.PRESS_FLASH_S
            snap = snapshot(s["mode"], song=song, volume=s["volume"], volume_turning=s["turning"],
                            art_key=art_key, index=s["index"], items=items, held=held,
                            position_s=64 + int(rig.now_ms / 1000))
            rig.step(snap, pressed=pressed)
        img = rig.frame().crop(view)
        frames.append(img.resize(out_size, Image.Resampling.LANCZOS))
        rig.tick()
    return frames


def scene_navigator(ctx) -> list[Path]:
    import recording as R
    frames = navigator_frames()
    frames[len(frames) // 2].save(Path(ctx.work) / "navigator-peek.png")
    gif, webp = R.save_loop(frames, FPS, "navigator", ctx.out, webp_cap=WEBP_CAP, gif_cap=GIF_CAP)
    ctx.log(f"navigator: {len(frames)} frames at {FPS} fps, webp {webp.stat().st_size} B, gif {gif.stat().st_size} B")
    return [ctx.produced(webp, STAGE), ctx.produced(gif, STAGE)]


SCENES = {"navigator": (STAGE, scene_navigator)}
