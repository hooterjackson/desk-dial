"""The repository's social preview (1280 x 640, under 1 MB): the knob rendered from the hero recording
through the firmware's LCD renderer and the LED twin, beside the name and one line. Fictional data.

SCENES["social-preview"] writes docs/media/social-preview.png. A real photo can replace the knob
later by passing photo=<path> to render()."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from scenes_registry import LCD

W, H = 1280, 640
BG = (13, 14, 17)


def _font(app, name, size, weight=None):
    f = ImageFont.truetype(str(Path(app) / "assets" / "fonts" / name), size)
    if weight:
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
    return f


def render(ctx, recording_path, photo=None, at_ms=5800):
    import recording as R
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # soft warm glow behind the knob
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((60, 40, 620, 600), fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    img.paste(Image.new("RGB", (W, H), (255, 132, 36)), (0, 0), glow.point(lambda v: v * 50 // 255))
    if photo:
        knob = Image.open(photo).convert("RGB")
        knob.thumbnail((560, 600), Image.Resampling.LANCZOS)
    else:
        rec = R.load(recording_path)
        fps = rec["fps"]
        k = max(0, int(at_ms * fps / 1000))
        frames = R.knob_frames(rec, ctx.knob_anim, ctx.work / "social", scale=1.25,
                               t_start=at_ms, t_end=at_ms + 1000 // fps + 1, tag="-social")
        knob = frames[0]
    kx, ky = 70 + (560 - knob.width) // 2, (H - knob.height) // 2
    img.paste(knob, (kx, ky))
    title = _font(ctx.app, "Archivo.ttf", 92, "Bold")
    body = _font(ctx.app, "Archivo.ttf", 34, "Regular")
    small = _font(ctx.app, "Archivo.ttf", 26, "Regular")
    x = 690
    d.text((x, 150), "Desk Dial", font=title, fill=(245, 245, 247))
    lines = ["A haptic knob for your desk:", "speakers, music, lights, windows", "and Onshape under one dial."]
    for i, line in enumerate(lines):
        d.text((x, 275 + i * 46), line, font=body, fill=(200, 204, 214))
    d.text((x, 445), "Windows app + firmware for the Nano_D++", font=small, fill=(255, 132, 36))
    d.text((x, 482), "github.com/hooterjackson/desk-dial", font=small, fill=(120, 124, 134))
    out = ctx.out / "social-preview.png"
    q = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    q.save(out, optimize=True)
    if out.stat().st_size > 1_000_000:
        img.save(out, optimize=True)
    ctx.log(f"social-preview.png {out.stat().st_size // 1024} KB")
    return [ctx.produced(out, LCD)]


def scene(ctx):
    from rec_scenes import recording_path   # the same recordings (captured on demand) as the knob loops
    return render(ctx, recording_path(ctx.work, "hero-knob", ctx.log))


SCENES = {"social-preview": (LCD, scene)}
