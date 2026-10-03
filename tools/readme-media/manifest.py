"""docs/media/manifest.json: what every README media file was rendered from, stamped with the
firmware, app and pipeline versions, so a reviewer can tell stale media from current media.

Schema (manifest.json, version 1)
---------------------------------
{
  "schema": 1,
  "generated_at": "<ISO 8601, passed in by the caller: this module never reads the clock>",
  "firmware": {
    "version": "1.0.0-cc5.7",      # NANO_FIRMWARE_VERSION in <firmware>/platformio.ini
    "git": "<40-hex HEAD SHA or null>",   # git -C <firmware> rev-parse HEAD
    "dirty": false                 # git -C <firmware> status --porcelain is non-empty
  },
  "app": {
    "version": "7.3.2.0",          # filevers=(a, b, c, d) in <app>/desktop-version.txt
    "tree": "<sha256>"             # sha256 over the sorted (relative path, sha256) lines of
                                   # <app>/control_center/*.py and <app>/standalone.py
  },
  "pipeline": {
    "git": "<40-hex HEAD SHA or null>",   # git -C <publish repo> rev-parse HEAD
    "tree": "<sha256>"             # sha256 over the sorted (relative path, sha256) lines of
                                   # tools/readme-media/**/*.py and tools/readme-media/lcd/*
  },
  "files": [                       # sorted by name; one entry per media file in docs/media
    {
      "name": "knob-hero.webp",
      "scene": "hero",             # the scenes_registry entry that produced it
      "source": "firmware LCD renderer",   # one of SOURCES below
      "bytes": 578664,
      "sha256": "<64 hex>",
      "width": 420, "height": 420,
      "frames": 240,               # 1 for a still
      "fps": 30.0,                 # null for a still
      "duration_ms": 8000,         # 0 for a still
      "data": "fictional"          # every rendered file; "real footage" files say "real"
    }
  ]
}

The stamps are the same inputs as the render: if the manifest's stamps differ from what a fresh
`check` computes, the committed media was rendered from other firmware / app / pipeline sources.
Library functions take explicit paths and return data; only `main` prints and exits.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCHEMA = 1
MEDIA_SUFFIXES = {".webp", ".gif", ".png", ".svg", ".jpg", ".jpeg", ".mp4", ".wav"}

SOURCES = (
    "firmware LCD renderer",
    "LED twin (alive_lights.py)",
    "app stage renderer",
    "app carousel",
    "firmware app canvas",
    "firmware feel laws + knob model",
    "firmware sound bank",
    "real footage",
    "typography (Archivo, headlines.py)",
    "app profiles (Karl Malota's icons)",
)

# Fallback (scene, source) by file stem for files already in docs/media that no registry entry
# claimed in this run (a partial --scenes render, or a check against the committed folder).
# The registry's own entries win when a scene ran.
KNOWN_FILES = {
    "knob-hero": ("hero", "firmware LCD renderer"),
    "knob-volume": ("volume", "firmware LCD renderer"),
    "knob-browse": ("browse", "firmware LCD renderer"),
    "knob-wake": ("wake", "firmware LCD renderer"),
    "knob-screens": ("stills", "firmware LCD renderer"),
    "led-ring": ("committed", "LED twin (alive_lights.py)"),      # not produced by this pipeline yet
    "desktop-floating-knob": ("floating", "app stage renderer"),
    "desktop-explorer": ("explorer", "app stage renderer"),
    "desktop-explorer-16x9": ("explorer-16x9", "app stage renderer"),
    "desktop-explorer-32x9": ("explorer-32x9", "app stage renderer"),
    "desktop-upnext-16x9": ("upnext-16x9", "app stage renderer"),
    "desktop-picker-16x9": ("picker-16x9", "app carousel"),
    "desktop-picker-32x9": ("picker-32x9", "app carousel"),
    "music-explorer-16x9": ("stills", "app stage renderer"),
    "music-explorer-playlists-16x9": ("stills", "app stage renderer"),
    "up-next-16x9": ("stills", "app stage renderer"),
    "window-picker-16x9": ("stills", "app carousel"),
    "window-picker-snap-16x9": ("stills", "app carousel"),
    "app-icons": ("committed", "app stage renderer"),             # not produced by this pipeline yet
}


# ------------------------------------------------------------------ hashing and stamps
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(root: Path, files) -> str:
    """sha256 over the sorted '<relative posix path>\\n<sha256>\\n' lines of `files`."""
    lines = sorted(f"{p.resolve().relative_to(root.resolve()).as_posix()}\n{sha256_file(p)}\n"
                   for p in files if p.is_file())
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def _git(repo: Path, *args) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def firmware_stamp(firmware_dir: Path) -> dict:
    ini = (firmware_dir / "platformio.ini").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'NANO_FIRMWARE_VERSION=\\?"([^"\\]+)\\?"', ini)
    status = _git(firmware_dir, "status", "--porcelain")
    return {"version": m.group(1) if m else None,
            "git": _git(firmware_dir, "rev-parse", "HEAD"),
            "dirty": bool(status) if status is not None else None}


def app_stamp(app_dir: Path) -> dict:
    text = (app_dir / "desktop-version.txt").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"filevers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", text)
    files = sorted((app_dir / "control_center").glob("*.py")) + [app_dir / "standalone.py"]
    return {"version": ".".join(m.groups()) if m else None, "tree": tree_hash(app_dir, files)}


def pipeline_stamp(pipeline_dir: Path = HERE, publish_repo: Path | None = None) -> dict:
    files = [p for p in pipeline_dir.rglob("*.py") if "__pycache__" not in p.parts]
    files += [p for p in (pipeline_dir / "lcd").glob("*") if p.is_file()]
    repo = publish_repo or pipeline_dir
    return {"git": _git(repo, "rev-parse", "HEAD"), "tree": tree_hash(pipeline_dir, files)}


# ------------------------------------------------------------------ media probing
def probe(path: Path) -> dict:
    """width, height, frames, fps, duration_ms for a PNG / WebP / GIF (SVG and others: nulls)."""
    out = {"width": None, "height": None, "frames": 1, "fps": None, "duration_ms": 0}
    if path.suffix.lower() == ".svg":
        m = re.search(rb'viewBox="[\d.\s-]*?([\d.]+)\s+([\d.]+)"', path.read_bytes()[:4096])
        if m:
            out["width"], out["height"] = int(float(m.group(1))), int(float(m.group(2)))
        return out
    try:
        from PIL import Image
        with Image.open(path) as im:
            out["width"], out["height"] = im.size
            n = getattr(im, "n_frames", 1)
            total = 0
            for k in range(n):
                im.seek(k)
                im.load()          # WebP fills info["duration"] only on load
                total += int(im.info.get("duration", 0) or 0)
            out["frames"] = n
            out["duration_ms"] = total
            out["fps"] = round(1000 * n / total, 2) if n > 1 and total > 0 else None
    except Exception:
        pass
    return out


def describe(name: str, entries: dict | None = None) -> tuple[str, str]:
    """(scene, source) for a media file: the registry's claim first, KNOWN_FILES next."""
    if entries and name in entries:
        return entries[name]
    stem = Path(name).stem
    return KNOWN_FILES.get(stem, ("unknown", "unknown"))


def media_files(out_dir: Path):
    return sorted(p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES)


def file_entry(path: Path, scene: str, source: str) -> dict:
    e = {"name": path.name, "scene": scene, "source": source, "bytes": path.stat().st_size,
         "sha256": sha256_file(path)}
    e.update(probe(path))
    e["data"] = "real" if source == "real footage" else "fictional"
    return e


# ------------------------------------------------------------------ write / check
def build(out_dir: Path, entries: dict, context: dict) -> dict:
    """The manifest dict for every media file in out_dir.

    entries: {file name: (scene, source)} as reported by the scenes that ran.
    context: generated_at (str), firmware_dir, app_dir, pipeline_dir (Path), publish_repo (Path, optional).
    """
    return {
        "schema": SCHEMA,
        "generated_at": context["generated_at"],
        "firmware": firmware_stamp(Path(context["firmware_dir"])),
        "app": app_stamp(Path(context["app_dir"])),
        "pipeline": pipeline_stamp(Path(context.get("pipeline_dir", HERE)), context.get("publish_repo")),
        "files": [file_entry(p, *describe(p.name, entries)) for p in media_files(out_dir)],
    }


def write(out_dir: Path, entries: dict, context: dict) -> dict:
    man = build(out_dir, entries, context)
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return man


def load(manifest) -> dict:
    if isinstance(manifest, dict):
        return manifest
    return json.loads(Path(manifest).read_text(encoding="utf-8"))


# Scenes whose bytes differ from run to run although nothing changed: the app's stage engine and Navigator
# renderer (hero, Navigator, the full-screen desktop clips) and real Tk windows (Settings screenshots) carry
# small timing / antialiasing differences (check of 2026-10-03: 75 of 91 files byte-identical, these 16 not).
# For them --check compares what the reader sees (dimensions, and duration within 5 %), not bytes.
LOOSE = ("desktop-*", "hero.*", "navigator.*", "navigator-cards.*", "settings-*.png")


def _loose(name: str) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(name, pat) for pat in LOOSE)


def check(out_dir: Path, manifest, context: dict | None = None) -> tuple[bool, str]:
    """Compare the media in out_dir (hashed now) with a manifest (dict or path, usually the committed
    docs/media/manifest.json). With `context`, also compare the firmware/app/pipeline stamps computed
    now against the manifest's. Returns (ok, report); ok is False on any difference."""
    old = load(manifest)
    old_files = {e["name"]: e for e in old.get("files", [])}
    new_files = {p.name: p for p in media_files(out_dir)}
    lines = []
    for name in sorted(set(old_files) - set(new_files)):
        lines.append(f"removed   {name}  ({old_files[name]['bytes']} bytes)")
    for name in sorted(set(new_files) - set(old_files)):
        lines.append(f"added     {name}  ({new_files[name].stat().st_size} bytes)")
    for name in sorted(set(old_files) & set(new_files)):
        o, p = old_files[name], new_files[name]
        nb, ns = p.stat().st_size, sha256_file(p)
        if nb != o["bytes"] or ns != o["sha256"]:
            if _loose(name):
                pr = probe(p)
                d0, d1 = o.get("duration_ms") or 0, pr["duration_ms"] or 0
                if (pr["width"], pr["height"]) == (o.get("width"), o.get("height")) and abs(d1 - d0) <= 0.05 * max(d0, 1):
                    continue                       # same size and length; run-to-run noise (LOOSE above). Frame
                                                   # counts vary too: the encoders merge frames that come out equal
            lines.append(f"changed   {name}  {o['bytes']} -> {nb} bytes, sha256 {o['sha256'][:12]} -> {ns[:12]}")
    if context is not None:
        now = {"firmware": firmware_stamp(Path(context["firmware_dir"])),
               "app": app_stamp(Path(context["app_dir"])),
               "pipeline": pipeline_stamp(Path(context.get("pipeline_dir", HERE)), context.get("publish_repo"))}
        for section, stamp in now.items():
            for key, val in stamp.items():
                if section == "pipeline" and key == "git" and stamp.get("tree") == old.get(section, {}).get("tree"):
                    continue                       # the commit that recorded the pipeline, same pipeline files
                was = old.get(section, {}).get(key)
                if was != val:
                    lines.append(f"drift     {section}.{key}: manifest {was!r} -> now {val!r}")
    ok = not lines
    head = f"manifest check: {'OK' if ok else f'{len(lines)} difference(s)'}  (media {out_dir}, " \
           f"{len(new_files)} files; manifest generated_at {old.get('generated_at')})"
    return ok, "\n".join([head, *lines])


def main(argv=None):
    import argparse
    import datetime as dt
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("write", "check"))
    ap.add_argument("--media", required=True, type=Path, help="docs/media folder")
    ap.add_argument("--firmware", required=True, type=Path)
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--publish-repo", type=Path, default=HERE.parent.parent)
    ap.add_argument("--manifest", type=Path, help="write: where to put manifest.json (default <media>); "
                                                 "check: the manifest to compare against (default <media>/manifest.json)")
    a = ap.parse_args(argv)
    ctx = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "firmware_dir": a.firmware, "app_dir": a.app, "pipeline_dir": HERE, "publish_repo": a.publish_repo}
    if a.command == "write":
        man = build(a.media, {}, ctx)
        target = (a.manifest or a.media) / "manifest.json" if (a.manifest or a.media).is_dir() or not (a.manifest or a.media).suffix else a.manifest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {target}: {len(man['files'])} files, firmware {man['firmware']['version']}, "
              f"app {man['app']['version']}")
        return 0
    ok, report = check(a.media, a.manifest or a.media / "manifest.json", ctx)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
