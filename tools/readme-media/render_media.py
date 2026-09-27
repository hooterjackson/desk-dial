"""Render the README animations and stills into docs/media/.

Two steps, from this folder, with the app's Python environment (Pillow 12 with WebP):

  1. python build_lcd.py --firmware <firmware dir> --harness <LCD harness dir> --build <build dir>
     (CMake + MSVC Build Tools; builds knob-anim, the firmware's LCD renderer on a fake tick)
  2. python render_media.py --app <app dir> --knob-anim <build dir>/Release/knob-anim.exe
                            --work <scratch dir> --out ../../docs/media

Each animation is written as an animated WebP (full size, 30 fps: what the README shows) and a GIF
fallback, reduced in frame rate and size until it is under 2.9 MB.

Usage:
  python render_media.py --app <companion source dir> --knob-anim <knob-anim.exe> --work <scratch dir>
                         --out <docs/media dir> [scene ...]

Scenes: hero, volume, browse, wake (the knob, knob_scenes.py), explorer, floating (the desktop,
desktop_scene.py), stills (stills.py).
Build knob-anim first with build_lcd.py. Everything is headless and uses fictional data only
(fixtures.py): no knob, no speakers, no Apple Music account, no screen capture.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--knob-anim", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("scenes", nargs="*")
    a = ap.parse_args()
    os.environ["DESK_DIAL_APP"] = str(a.app.resolve())
    a.work.mkdir(parents=True, exist_ok=True)
    a.out.mkdir(parents=True, exist_ok=True)
    import knob_scenes as K

    wanted = a.scenes or ["hero", "volume", "browse", "wake", "explorer", "floating", "stills"]
    for name in wanted:
        started = time.time()
        if name in K.SCENES:
            F = K.Frames()
            tl = K.SCENES[name](F)
            lcd = K.render_lcd(tl, a.knob_anim, a.work)
            leds = K.render_leds(tl)
            n = min(len(lcd), len(leds))
            if name == "volume":
                dev = K.KnobDevice(scale=1.3, crop_ring=True)
            else:
                dev = K.KnobDevice(scale=1.4)
            frames = [dev.compose(lcd[k], *leds[k]) for k in range(n)]
            gif, webp = K.save_animation(frames, tl.fps, f"knob-{name}", a.out)
            frames[len(frames) // 3].save(a.work / f"{name}-peek.png")
        elif name in ("explorer", "floating"):
            import desktop_scene as D
            gif, webp = D.render(a.knob_anim, a.work, a.out, name)
        elif name == "stills":
            import stills as S
            S.render(a.knob_anim, a.work, a.out)
            S.overlay_stills(a.out)
            S.picker_stills(a.out)
            print("stills", f"{time.time() - started:.0f}s", flush=True)
            continue
        else:
            raise SystemExit(f"unknown scene {name}")
        print(f"{name}: {gif.name} {gif.stat().st_size / 1e6:.2f} MB, {webp.name} {webp.stat().st_size / 1e6:.2f} MB, "
              f"{time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
