"""apps-strip.png / .webp: the README's Apps picture, the bundled app profiles in a row, each as Karl Malota's own
48 px pixel-art icon (the profile's ``icon48``, RGB565 big-endian on black, as Settings › Apps decodes it) scaled up
with nearest-neighbour, its name, and its status from the Windows add-on (``<id>.windows.json`` "status").

Profiles are read from ``$DESK_DIAL_PROFILES`` or ``<app>/profiles`` (``karl/<id>.json`` and ``<id>.windows.json``).
1760 px wide (2x the README column). Registry contract: SCENES = {"apps-strip": (source, fn)}.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

SOURCE = "app profiles (Karl Malota's icons)"
ORDER = ("onshape", "figma", "plasticity", "blender", "autocad")
NAMES = {"onshape": "Onshape", "figma": "Figma", "plasticity": "Plasticity", "blender": "Blender", "autocad": "AutoCAD"}
STATUS = {"tested": "TESTED", "community": "NOT YET TESTED", "basic": "BASIC"}   # the Settings badges (user ruling 2026-10-03)
W, H = 1760, 520
BG = (13, 14, 17)
INK, QUIET = (245, 245, 247), (134, 134, 139)
ICON_PX = 192                         # 48 px icon x 4


def profiles_dir(app) -> Path:
    env = os.environ.get("DESK_DIAL_PROFILES")
    return Path(env) if env else Path(app) / "profiles"


def icon_image(b64, size=48):
    from PIL import Image
    raw = base64.b64decode(b64)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        for x in range(size):
            v = (raw[2 * (y * size + x)] << 8) | raw[2 * (y * size + x) + 1]
            if v:
                r5, g6, b5 = v >> 11, (v >> 5) & 0x3F, v & 0x1F
                px[x, y] = ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2), 255)
    return img


def render(app, work):
    from PIL import Image, ImageDraw
    import headlines as T
    root = profiles_dir(app)
    apps = []
    for pid in ORDER:
        karl = root / "karl" / f"{pid}.json"
        if not karl.exists():
            continue
        k = json.loads(karl.read_text(encoding="utf-8"))
        side = root / f"{pid}.windows.json"
        status = json.loads(side.read_text(encoding="utf-8")).get("status", "") if side.exists() else ""
        apps.append((NAMES.get(pid, k.get("name", pid)), STATUS.get(status, status.upper()),
                     icon_image(k["icon48"]) if k.get("icon48") else None))
    if not apps:
        raise FileNotFoundError(f"no app profiles under {root}")
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    col = W / len(apps)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    for i, (name, status, icon) in enumerate(apps):
        cx = col * i + col / 2
        if icon is not None:
            big = icon.resize((ICON_PX, ICON_PX), Image.Resampling.NEAREST)
            img.paste(big, (int(cx - ICON_PX / 2), 70), big)
        for text, px, weight, colour, y, track in ((name, 44, 650, INK, 70 + ICON_PX + 92, -0.01),
                                                    (status, 24, 600, QUIET, 70 + ICON_PX + 140, 0.08)):
            probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
            w = T.typeset(probe, app, work, text, px, weight, (0, 0), (0, 0, 0, 0), tracking=track)
            T.typeset(d, app, work, text, px, weight, (cx - w / 2, y), colour, tracking=track)
    return img


def scene(ctx) -> list[Path]:
    img = render(ctx.app, Path(ctx.work) / "apps-strip")
    out = Path(ctx.out)
    png, webp = out / "apps-strip.png", out / "apps-strip.webp"
    img.quantize(colors=256, method=2, dither=0).save(png, optimize=True)
    img.save(webp, quality=90, method=6)
    ctx.log(f"apps-strip: {img.size}, png {png.stat().st_size} B, webp {webp.stat().st_size} B")
    return [ctx.produced(webp, SOURCE), ctx.produced(png, SOURCE)]


SCENES = {"apps-strip": (SOURCE, scene)}
