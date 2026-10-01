"""Build the headless renderers in lcd/ (knob-anim, app-canvas-anim, haptic-trace, sound-dump): the knob
firmware's own drawing, feel and sound code driven by a fake tick, headless.

Usage: python build_lcd.py --firmware <firmware dir> --harness <LCD harness dir> --build <build dir> [--no-logo]

Needs CMake and the MSVC Build Tools (Visual Studio 2022). Writes <build>/conf/lv_conf.h from the
firmware's include/lv_conf.h with the single host override the harness uses (LV_USE_TFT_ESPI 1 -> 0:
the host flushes into a framebuffer instead of the SPI panel), then configures and builds
<build>/Release/*.exe. --no-logo makes app-canvas-anim draw a text badge where the knob draws the
Onshape icon (the public media default). Touches nothing outside <build>.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
VS_CMAKE = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/Common7/IDE/CommonExtensions/"
                "Microsoft/CMake/CMake/bin/cmake.exe")
TARGETS = ("knob-anim", "app-canvas-anim", "haptic-trace", "sound-dump")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firmware", required=True, type=Path)
    ap.add_argument("--harness", required=True, type=Path)
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--no-logo", action="store_true")
    a = ap.parse_args()
    conf = a.build / "conf"
    conf.mkdir(parents=True, exist_ok=True)
    src = (a.firmware / "include" / "lv_conf.h").read_bytes()
    out, n = re.subn(rb"^([ \t]*#define[ \t]+LV_USE_TFT_ESPI[ \t]+)1\b", rb"\g<1>0", src, flags=re.M)
    if n != 1:
        raise SystemExit("expected exactly one '#define LV_USE_TFT_ESPI 1' in the firmware lv_conf.h")
    (conf / "lv_conf.h").write_bytes(out)
    cmake = shutil.which("cmake") or str(VS_CMAKE)
    env = {k.upper(): v for k, v in os.environ.items()}   # MSBuild rejects both Path and PATH
    gen = ["-G", "Visual Studio 17 2022", "-A", "x64"] if os.name == "nt" else []
    subprocess.run([cmake, "-S", str(HERE / "lcd"), "-B", str(a.build), *gen,
                    f"-DFIRMWARE_DIR={a.firmware.resolve().as_posix()}",
                    f"-DHARNESS_DIR={a.harness.resolve().as_posix()}",
                    f"-DLV_CONF_DIR={conf.resolve().as_posix()}",
                    f"-DREADME_NO_LOGO={'ON' if a.no_logo else 'OFF'}"], check=True, env=env)
    present = [t for t in TARGETS if t == "knob-anim" or (HERE / "lcd" / (t.replace("-", "_") + ".cpp")).exists()]
    subprocess.run([cmake, "--build", str(a.build), "--config", "Release", "--parallel", "8",
                    "--target", *present], check=True, env=env)
    for t in present:
        exe = a.build / "Release" / f"{t}.exe"
        print(f"{t}: {'ok' if exe.exists() else 'MISSING'} {exe}")


if __name__ == "__main__":
    main()
