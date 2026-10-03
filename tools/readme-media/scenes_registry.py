"""The scene registry: name -> callable(ctx) -> list[Path] of the files it wrote into ctx.out.

render_all.py runs every entry (or the --scenes subset) in order. A scene receives a Context and
returns the paths it produced; it tags each with (scene name, source) for the manifest through
ctx.produced(path, source). Sources are the strings in manifest.SOURCES.

Adding a scene: write `def scene_x(ctx) -> list[Path]` in your own module, then register it here:
    SCENES["x"] = ("source label", scene_x)
Keep the module import inside the function (lazy) so a broken scene does not break the others, and
use only fixtures.py data (fictional). Nothing here opens a device, a window or a network connection.

Context fields: firmware, harness, app, build, work, out (Paths), knob_anim (Path to knob-anim.exe),
exe(name) (Path to <build>/Release/<name>.exe, raising if missing), no_logo (bool), log(msg).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

LCD = "firmware LCD renderer"
LED = "LED twin (alive_lights.py)"
STAGE = "app stage renderer"
CAROUSEL = "app carousel"
APP_CANVAS = "firmware app canvas"
FEEL = "firmware feel laws + knob model"
SOUND = "firmware sound bank"
FOOTAGE = "real footage"


@dataclass
class Context:
    firmware: Path
    harness: Path
    app: Path
    build: Path
    work: Path
    out: Path
    no_logo: bool = False
    entries: dict = field(default_factory=dict)   # file name -> (scene, source)
    scene: str = ""

    @property
    def knob_anim(self) -> Path:
        return self.exe("knob-anim")

    def exe(self, name: str) -> Path:
        p = self.build / "Release" / f"{name}.exe"
        if not p.exists():
            raise FileNotFoundError(f"{p} is missing: run build_lcd.py (or render_all.py without --skip-build)")
        return p

    def produced(self, path: Path, source: str) -> Path:
        self.entries[Path(path).name] = (self.scene, source)
        return Path(path)

    def log(self, msg: str):
        print(f"  [{self.scene}] {msg}", flush=True)


# ------------------------------------------------------------------ the knob loops (knob_scenes.py)
def _knob_loop(name):
    def run(ctx: Context) -> list[Path]:
        import knob_scenes as K
        F = K.Frames()
        tl = K.SCENES[name](F)
        lcd = K.render_lcd(tl, ctx.knob_anim, ctx.work)
        leds = K.render_leds(tl)
        n = min(len(lcd), len(leds))
        dev = K.KnobDevice(scale=1.3, crop_ring=True) if name == "volume" else K.KnobDevice(scale=1.4)
        frames = [dev.compose(lcd[k], *leds[k]) for k in range(n)]
        gif, webp = K.save_animation(frames, tl.fps, f"knob-{name}", ctx.out)
        frames[len(frames) // 3].save(ctx.work / f"{name}-peek.png")
        ctx.log(f"{n} frames at {tl.fps} fps")
        return [ctx.produced(webp, LCD), ctx.produced(gif, LCD)]
    return run


# ------------------------------------------------------------------ the desktop (desktop_scene.py, desktop_fullscreen.py)
def _desktop(which):
    def run(ctx: Context) -> list[Path]:
        import desktop_scene as D
        gif, webp = D.render(ctx.knob_anim, ctx.work, ctx.out, which)
        return [ctx.produced(webp, STAGE), ctx.produced(gif, STAGE)]
    return run


def _fullscreen(which, source):
    def run(ctx: Context) -> list[Path]:
        import desktop_fullscreen as FS
        out = []
        for stem, n, webp, gif in FS.render(ctx.out, ctx.work, [which]):
            ctx.log(f"{stem}: {n} frames")
            out += [ctx.produced(webp, source), ctx.produced(gif, source)]
        return out
    return run


# ------------------------------------------------------------------ stills (stills.py)
def scene_stills(ctx: Context) -> list[Path]:
    import stills as S
    S.render(ctx.knob_anim, ctx.work, ctx.out)
    S.overlay_stills(ctx.out)
    S.picker_stills(ctx.out)
    names = [("knob-screens.png", LCD), ("music-explorer-16x9.png", STAGE),
             ("music-explorer-playlists-16x9.png", STAGE), ("up-next-16x9.png", STAGE),
             ("window-picker-16x9.png", CAROUSEL), ("window-picker-snap-16x9.png", CAROUSEL)]
    return [ctx.produced(ctx.out / n, src) for n, src in names if (ctx.out / n).exists()]


# The scene modules, in render order. Each exposes SCENES = {name: (source, fn)}; fn(ctx) tags its own files.
# A module that is missing or fails to import is reported and skipped, so one broken scene never blocks the rest.
SCENE_MODULES = ("hero_scene", "rec_scenes", "desktop_fullscreen", "navigator_scene", "app_screens", "panel_scenes",
                 "gallery_scenes", "social_preview", "headlines", "feel_wide", "apps_strip")
IMPORT_ERRORS: dict[str, str] = {}


def _discover():
    import importlib
    out = {}
    for mod in SCENE_MODULES:
        try:
            m = importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001  (reported by render_all --list and at render time)
            IMPORT_ERRORS[mod] = f"{type(e).__name__}: {e}"
            continue
        for name, entry in getattr(m, "SCENES", {}).items():
            fn = entry[1] if isinstance(entry, tuple) else entry
            out[name] = fn
    return out


# name -> callable(ctx) -> list[Path]; insertion order is the render order.
SCENES = _discover()
