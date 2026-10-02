"""Screenshots of the Desk Dial app's own windows for the docs: every Settings page, from the real app code.

The app runs in its simulator (no knob, no speaker, no Home Assistant, no Apple Music), pointed at a throwaway
data folder holding fictional settings, so neither the author's settings.json nor credentials.bin is read. Each
window is captured with PrintWindow, so only that window's own pixels are read, never the rest of the screen.
Before a screenshot is saved, every widget's text is checked against the blocklist (gates.BLOCKLIST); a hit
stops the scene. Field values the app pre-fills from its own code (FIELD_OVERRIDES) are replaced with fictional
placeholders first.

The windows appear on screen for a few seconds while this runs (Tk cannot lay out an unmapped window).

SCENES["app-settings"] writes docs/media/settings-<page>.png for every page of SETTINGS_PAGES.
"""
from __future__ import annotations

import ctypes
import json
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

from scenes_registry import STAGE

# Entry fields whose default comes from the app's code, replaced before capture (label -> fictional value).
FIELD_OVERRIDES = {"Apple Team ID": "A1B2C3D4E5", "MusicKit Key ID": "K9L8M7N6P5", "Speaker IP": "192.0.2.20"}
# Blocklist terms allowed in these screenshots: Home Assistant's own default host, shown as the Address hint.
SCREEN_ALLOW = {"homeassistant.local"}
FICTIONAL_SETTINGS = {
    "speaker_ip": "192.0.2.20", "room_uid": "", "port": "",
    "ha_base_url": "https://homeassistant.example:8123", "ha_area": "living_room",
}


def _printwindow(hwnd):
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)                       # PW_RENDERFULLCONTENT
    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(mem); user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def _texts(widget):
    """Every text a widget tree shows: labels, buttons, entries."""
    out = []
    stack = [widget]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        for opt in ("text",):
            try:
                v = w.cget(opt)
                if v:
                    out.append(str(v))
            except Exception:
                pass
        try:
            if w.winfo_class() in ("Entry", "TEntry"):
                out.append(w.get())
        except Exception:
            pass
    return out


def _override_fields(app, root):
    """Replace code-provided defaults in entry fields, found by the label packed just before each entry."""
    import tkinter as tk
    stack = [app.setup_window]
    while stack:
        w = stack.pop()
        kids = w.winfo_children()
        stack.extend(kids)
        for a, b in zip(kids, kids[1:]):
            try:
                name = a.cget("text")
            except Exception:
                continue
            if name in FIELD_OVERRIDES and b.winfo_class() == "Entry":
                b.delete(0, tk.END)
                b.insert(0, FIELD_OVERRIDES[name])


def _press(win, text, root, settle=40):
    """Invoke the button labelled ``text`` (the simulator answers it; nothing leaves the PC), then let it settle."""
    stack = [win]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        try:
            if w.cget("text") == text:
                w.invoke() if hasattr(w, "invoke") else w.event_generate("<Button-1>")
                break
        except Exception:
            continue
    import time
    for _ in range(settle):
        root.update()
        time.sleep(0.05)


def capture(out_dir: Path, log=print):
    import os
    os.environ.setdefault("DESK_DIAL_APP", str(Path(__file__).resolve().parents[0]))
    import fiction  # noqa: F401  (fictional simulator data, before the app builds anything)
    import gates
    from control_center import ui
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
    tmp = Path(tempfile.mkdtemp(prefix="deskdial-shots-"))
    ui.DATA_DIR = tmp                                     # never the author's local\ settings or credentials
    (tmp / "settings.json").write_text(json.dumps(FICTIONAL_SETTINGS), encoding="utf-8")
    import tkinter as tk
    root = tk.Tk()
    ui.apply_app_icon(root)
    app = ui.ControlCenterApp(root)
    root.update()
    written = []
    try:
        for key, title in ui.SETTINGS_PAGES:
            app.setup(page=key)
            for _ in range(20):
                root.update()
            _override_fields(app, root)
            if key == "home_assistant":
                _press(app.setup_window, "Test connection", root)
            root.update()
            hits = [t for t in _texts(app.setup_window) for term, pat in gates.PATTERNS.items()
                    if term not in SCREEN_ALLOW and pat.search(t)]
            if hits:
                raise SystemExit(f"settings-{key}: blocklisted text in the window, not saved: {hits[:5]}")
            hwnd = int(app.setup_window.wm_frame(), 16)
            img = _printwindow(hwnd)
            path = out_dir / f"settings-{key.replace('_', '-')}.png"
            q = img.quantize(colors=256, dither=0)
            q.save(path, optimize=True)
            if path.stat().st_size > 300_000:
                img.save(path, optimize=True)
            log(f"{path.name}: {img.size} {path.stat().st_size // 1024} KB")
            written.append(path)
    finally:
        try:
            app.close()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
    return written


def scene(ctx):
    return [ctx.produced(p, STAGE) for p in capture(Path(ctx.out), ctx.log)]


SCENES = {"app-settings": (STAGE, scene)}


if __name__ == "__main__":
    capture(Path(sys.argv[1]))
