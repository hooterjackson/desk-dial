"""Render the prototype's own Navigator markup (Knob IA Prototype.dc.html L79-170, values filled from
our NavContent for each design state) with headless Chrome at device scale 2, over the same synthetic
desktop, into design-reference/r3-navigator-prototype/<state>.png. Offscreen only (--headless=new),
a throwaway profile in a scratch folder."""
import html
import subprocess
import sys
from pathlib import Path

APP = Path(r"<repo>\app")
sys.path.insert(0, str(APP))
from control_center import navigator_model as NM  # noqa: E402
from control_center.stage.scenes import navigator_render as R  # noqa: E402

SCRATCH = Path(__import__("tempfile").gettempdir()) / "nanod-navigator-prototype"   # throwaway HTML and Chrome profile
OUT = APP / "design-reference" / "r3-navigator-prototype"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
COVERS = R.covers_dir()
FONT = (APP / "assets" / "fonts" / "Archivo.ttf").as_uri()


def rgba(rgb, a=1.0):
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a})"


def art_url(key, accent):
    if key and key.startswith("art:"):
        name = key.split(":", 1)[1]
        for ext in (".png", ".jpg"):
            p = COVERS / (name + ext)
            if p.exists():
                return f"url('{p.as_uri()}') center / cover"
    r, g, b = RM_rgb(accent)
    return f"rgb({r},{g},{b})"


def RM_rgb(v):
    v = int(v) & 0xFFFFFF
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def e(s):
    return html.escape(str(s or ""))


CAPS = "font-size:11px;letter-spacing:0.12em;text-transform:uppercase;font-weight:600;color:rgba(255,255,255,0.75)"


def body(c):
    st = f'<div style="font-size:11px;line-height:15px;color:{rgba(c.status_rgb, c.status_a)};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(c.status)}</div>'
    if c.kind == "now":
        art = art_url(c.art_key, c.accent)
        return f'''<div style="display:flex;flex-direction:column;gap:12px">
<div style="display:flex;gap:12px;align-items:center;min-width:0">
<div style="width:64px;height:64px;flex:none;border-radius:8px;background:{art};box-shadow:0 8px 20px rgba(0,0,0,0.35), inset 0 0 0 1px rgba(255,255,255,0.2)"></div>
<div style="display:flex;flex-direction:column;gap:2px;min-width:0">
<div style="font-size:15px;line-height:19px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(c.title)}</div>
<div style="font-size:12px;line-height:16px;color:rgba(255,255,255,0.85);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(c.artist)}</div>
{st}</div></div>
<div style="display:flex;flex-direction:column;gap:6px;opacity:{1 if c.volume_active else 0.6}">
<div style="display:flex;justify-content:space-between;{CAPS}"><span>Volume</span><span style="font-variant-numeric:tabular-nums">{c.volume}%</span></div>
<div style="height:4px;border-radius:2px;background:rgba(255,255,255,0.2);position:relative;overflow:hidden"><div style="position:absolute;left:0;top:0;bottom:0;width:{c.volume}%;background:#fff"></div></div>
</div></div>'''
    if c.kind == "lights":
        kel = "rgb(%d,%d,%d)" % c.kelvin_rgb
        grad = "linear-gradient(90deg, rgb(%d,%d,%d), rgb(%d,%d,%d), rgb(%d,%d,%d))" % (
            NM.kelvin_rgb(2200) + NM.kelvin_rgb(3400) + NM.kelvin_rgb(6500))
        return f'''<div style="display:flex;flex-direction:column;gap:12px">
<div style="display:flex;flex-direction:column;gap:2px"><div style="{CAPS}">{e(c.caption)}</div>
<div style="display:flex;align-items:baseline;gap:4px"><span style="font-size:44px;line-height:46px;font-weight:600;letter-spacing:-0.03em;font-variant-numeric:tabular-nums">{e(c.big)}</span><span style="font-size:16px;color:rgba(255,255,255,0.8)">{e(c.unit)}</span></div></div>
<div style="display:flex;flex-direction:column;gap:6px;opacity:{c.bri_a}"><div style="display:flex;justify-content:space-between;{CAPS}"><span>Brightness</span><span style="font-variant-numeric:tabular-nums">{c.bri}%</span></div>
<div style="height:4px;border-radius:2px;background:rgba(255,255,255,0.18);position:relative;overflow:hidden"><div style="position:absolute;left:0;top:0;bottom:0;width:{c.bri_frac*100}%;background:{kel}"></div></div></div>
<div style="display:flex;flex-direction:column;gap:6px;opacity:{c.temp_a}"><div style="display:flex;justify-content:space-between;{CAPS}"><span>Temperature</span><span style="font-variant-numeric:tabular-nums">{c.kelvin} K</span></div>
<div style="height:4px;border-radius:2px;background:{grad};position:relative"><div style="position:absolute;top:-4px;width:4px;height:12px;border-radius:2px;margin-left:-2px;left:{c.temp_frac*100}%;background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,0.4)"></div></div></div>
<div style="display:flex;justify-content:space-between;align-items:baseline;border-top:1px solid rgba(255,255,255,0.2);padding-top:10px"><span style="{CAPS}">Scene</span><span style="font-size:14px;font-weight:600">{e(c.scene)}</span></div>
</div>'''
    if c.kind == "covers":
        covs = []
        for cv in c.covers:
            a = min(3, abs(cv.offset))
            sg = (cv.offset > 0) - (cv.offset < 0)
            off, scl = [0, 86, 132, 170][a], [1, 0.55, 0.38, 0.3][a]
            op = 0 if a > 2 else [1, 0.55, 0.25][a]
            covs.append(f'<div style="position:absolute;left:50%;top:50%;width:120px;height:120px;border-radius:8px;transform:translate(-50%,-50%) translateY({sg*off}px) scale({scl});opacity:{op};z-index:{10-a};background:{art_url(cv.art_key, cv.accent)};box-shadow:0 10px 24px rgba(0,0,0,0.4), inset 0 0 0 1px rgba(255,255,255,0.2)"></div>')
        return f'''<div style="display:flex;flex-direction:column;gap:10px"><div style="position:relative;height:196px;overflow:hidden">{''.join(covs)}</div>
<div style="display:flex;flex-direction:column;gap:2px;min-width:0"><div style="font-size:15px;line-height:19px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(c.title)}</div>
<div style="font-size:12px;line-height:16px;color:rgba(255,255,255,0.85);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(c.artist)}</div>{st}</div></div>'''
    if c.kind in ("rows", "scenes"):
        rows = []
        for r in c.rows:
            a = abs(r.offset)
            op = 0 if a > 2 else 1 if a == 0 else 0.8 - a * 0.15
            rows.append(f'<div style="position:absolute;left:0;right:0;top:76px;height:38px;transform:translateY({r.offset*38}px);opacity:{op};display:flex;align-items:center;gap:10px;padding:0 10px;box-sizing:border-box"><div style="width:16px;font-size:11px;color:rgba(255,255,255,0.7);font-variant-numeric:tabular-nums">{e(r.number)}</div><div style="flex:1;min-width:0;font-size:13px;line-height:17px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:{rgba(r.title_rgb)}">{e(r.title)}</div><div style="font-size:10px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:{rgba(r.tag_rgb, r.tag_a)};white-space:nowrap">{e(r.tag)}</div></div>')
        return f'''<div style="display:flex;flex-direction:column;gap:10px"><div style="position:relative;height:190px;overflow:hidden">
<div style="position:absolute;left:0;right:0;top:76px;height:38px;border-radius:10px;background:rgba(255,255,255,0.16);box-shadow:inset 0 1px 0 rgba(255,255,255,0.35);transform:translateY({c.plate*38}px)"></div>{''.join(rows)}</div>
<div style="font-size:11px;line-height:15px;color:{rgba(c.status_rgb, c.status_a)}">{e(c.status)}</div></div>'''
    if c.kind == "seek":
        return f'''<div style="display:flex;flex-direction:column;gap:10px"><div style="display:flex;gap:12px;align-items:center;min-width:0">
<div style="width:44px;height:44px;flex:none;border-radius:6px;background:{art_url(c.art_key, c.accent)}"></div>
<div style="font-size:14px;line-height:18px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(c.title)}</div></div>
<div style="display:flex;align-items:baseline;gap:6px"><span style="font-size:36px;line-height:40px;font-weight:600;letter-spacing:-0.02em;font-variant-numeric:tabular-nums">{e(c.big)}</span><span style="font-size:12px;color:rgba(255,255,255,0.8)">{e(c.unit)}</span></div>
<div style="height:4px;border-radius:2px;background:rgba(255,255,255,0.2);position:relative;overflow:hidden"><div style="position:absolute;left:0;top:0;bottom:0;width:{c.seek_frac*100}%;background:#FFBE69"></div></div></div>'''
    return ""


def page(c, bg_uri, host_css):
    keys = []
    for k in c.keys:
        op = 1 if k.enabled else 0.4
        bgc, fg = ("#fff", "#000") if k.pressed else ("transparent", "#fff")
        keys.append(f'<div style="display:flex;align-items:center;gap:6px;opacity:{op};min-width:0"><span style="width:16px;height:16px;flex:none;border-radius:4px;border:1px solid rgba(255,255,255,0.55);font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center;background:{bgc};color:{fg};text-shadow:none;box-sizing:border-box">{e(k.digit)}</span><span style="font-size:11px;color:rgba(255,255,255,0.9);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(k.label)}</span></div>')
    hold = '<div style="font-size:11px;line-height:14px;color:rgba(255,255,255,0.7);margin-top:-4px">Hold 1 for Home</div>' if c.hold_hint else ""
    w, h = host_css
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Archivo; src: url('{FONT}'); font-weight: 100 900; }}
html,body {{ margin:0; width:{w}px; height:{h}px; overflow:hidden; background:url('{bg_uri}') 0 0 / {w}px {h}px no-repeat; }}
</style></head><body>
<div style="position:absolute;left:20px;top:0;bottom:0;display:flex;align-items:center;pointer-events:none">
<div style="position:relative;width:250px">
<div style="position:absolute;inset:0;border-radius:26px;overflow:hidden;backdrop-filter:blur(14px) saturate(1.8) brightness(1.06);background:linear-gradient(160deg, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0.05) 42%, rgba(255,255,255,0.09) 100%), rgba(18,18,22,0.3);box-shadow:inset 0 1px 0 rgba(255,255,255,0.6), inset 0 -1px 0 rgba(255,255,255,0.14), inset 1px 0 0 rgba(255,255,255,0.22), inset -1px 0 0 rgba(255,255,255,0.1), 0 18px 50px rgba(0,0,0,0.35)">
<div style="position:absolute;left:-40px;top:-60px;width:220px;height:160px;background:radial-gradient(closest-side, rgba(255,255,255,0.22), transparent);"></div></div>
<div style="position:relative;padding:16px;display:flex;flex-direction:column;gap:14px;color:#fff;font-family:Archivo, sans-serif;text-shadow:0 1px 2px rgba(0,0,0,0.35)">
<div style="{CAPS};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{e(c.path)}</div>
<div style="display:flex;flex-direction:column">{body(c)}</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 10px;border-top:1px solid rgba(255,255,255,0.18);padding-top:12px;position:relative">{''.join(keys)}</div>
{hold}</div></div></div></body></html>'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    work = SCRATCH / "proto"
    work.mkdir(parents=True, exist_ok=True)
    desk = R.desktop_image()
    bg = work / "desktop.png"
    desk.save(bg)
    host_css = (desk.size[0] // 2, desk.size[1] // 2)
    import dataclasses
    for name, snap, pressed in R.design_states():
        c = NM.build_content(snap, pressed=pressed)
        if c.kind == "covers":
            covers = []
            for cv in c.covers:
                j = snap.get("index", 0) + cv.offset
                covers.append(dataclasses.replace(cv, art_key=f"art:{R.RECENT_ART[j]}"))
            c = dataclasses.replace(c, covers=tuple(covers))
        f = work / f"{name}.html"
        f.write_text(page(c, bg.as_uri(), host_css), encoding="utf-8")
        png = OUT / f"{name}.full.png"
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={SCRATCH / 'chrome-profile'}",
               "--force-device-scale-factor=2", f"--window-size={host_css[0]},{host_css[1]}",
               "--run-all-compositor-stages-before-draw", "--virtual-time-budget=2000",
               f"--screenshot={png}", f.as_uri()]
        subprocess.run(cmd, check=True, timeout=60, capture_output=True)
        # crop like crop_card (same host geometry): take our rig's card box
        img, rig = R.render_state(name, snap, pressed, desktop=desk)
        from PIL import Image
        with Image.open(png) as im:
            full = im.convert("RGB")
        R.crop_card(full, rig).save(OUT / f"{name}.png")
        png.unlink()
        print(name)


if __name__ == "__main__":
    main()
