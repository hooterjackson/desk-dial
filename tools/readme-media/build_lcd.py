"""Build knob-anim (lcd/): the knob firmware's LCD renderer driven by a fake tick, headless.

Usage: python build_lcd.py --firmware <firmware dir> --harness <LCD harness dir> --build <build dir>

Needs CMake and the MSVC Build Tools (Visual Studio 2022). Writes <build>/conf/lv_conf.h from the
firmware's include/lv_conf.h with the single host override the harness uses (LV_USE_TFT_ESPI 1 -> 0:
the host flushes into a framebuffer instead of the SPI panel), then configures and builds
<build>/Release/knob-anim.exe. Touches nothing outside <build>.
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firmware", required=True, type=Path)
    ap.add_argument("--harness", required=True, type=Path)
    ap.add_argument("--build", required=True, type=Path)
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
                    f"-DLV_CONF_DIR={conf.resolve().as_posix()}"], check=True, env=env)
    subprocess.run([cmake, "--build", str(a.build), "--config", "Release", "--parallel", "8",
                    "--target", "knob-anim"], check=True, env=env)


if __name__ == "__main__":
    main()
