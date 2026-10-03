"""Gates the README media must pass before a push: page weight, the fictional-data blocklist and the
sizes table for docs/media/README.md.

budget(out_dir, readme_path, caps)   the README's WebP-path weight against CAPS -> (ok, table)
blocklist(paths, allow)              blocked words in text files, media metadata and file names -> (ok, report)
sizes(out_dir)                       markdown table: name, bytes, dimensions, frames, fps

Page weight: a browser that supports WebP downloads, for each <picture>, only the <source> it
picks (the WebP) and never the <img> GIF. So the README's weight is the sum over every <picture>
block of its WebP source (the <img src> when a block has no <source>), plus every bare <img> and
every Markdown image (PNG / SVG / GIF). The GIF fallbacks are capped on their own but do not count
toward the total.

Blocklist: the rendered media uses fictional data only (fixtures.py). BLOCKLIST holds the real
names that must never appear: the owner's room and device names, the owner's and family names,
network identifiers, real artists, real app and product names (the window picker's fixtures are
fictional apps), and an assistant signature. Short words match on word boundaries ("Steam" but not
"Steamed"); the rest match as plain, case-sensitive substrings. Scanned: *.md *.json *.py text,
PNG/WebP/GIF metadata (PNG text chunks, EXIF, XMP, ICC description; never the pixel data) and
every file name under README.md, docs/ and tools/readme-media.

ALLOWLIST (explicit, per file, documented here) is the only way around a hit. Each entry maps a
repo-relative posix path to the terms that file may legitimately contain:
  tools/readme-media/gates.py           the blocklist itself
  tools/readme-media/README.md          documents the blocklist (prose, not media)
  README.md                             the FAQ question about Spotify (a product named in prose
                                        because readers ask about it; not a logo, not in media)
  docs/setup/onshape.md                 names the browsers the Onshape bridge recognises (prose)
  docs/faq.md                           "Does it work with Spotify?" and Home Assistant's default
                                        hostname homeassistant.local in troubleshooting prose
  docs/setup/home-assistant.md          the same default hostname, as the address field's example
  tools/readme-media/fiction.py         the fixtures module's own copy of the blocklist (code)
  docs/media/README.md                  nothing (generated table; must stay clean)
  docs/features/apps.md, apps_strip.py, the FAQ, Settings and Onshape setup pages
                                        "Figma": a supported app since v2.0.0 (app profiles), named in
                                        prose and as a label under Karl's icon; never a logo or fixture
A new legitimate mention (for example a FAQ about another product) is added here, in ALLOWLIST,
with the file and the exact term; the gate still fails for the same term in any other file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

KB, MB = 1_000, 1_000_000
CAPS = {
    "hero": 1.7 * MB,       # the hero loop's WebP (file stem "hero" or "<prefix>-hero"), a 2x render since 2026-10-03
    "loop": 1.2 * MB,       # every other animated WebP that is not a desktop-* clip
    "desktop": 2.0 * MB,    # desktop-*.webp full-screen clips
    "story": 1.6 * MB,      # story-*.webp, the 18 s "A day with Desk Dial" sequence
    "still": 300 * KB,      # PNG / SVG stills
    "gif": 2.9 * MB,        # every GIF fallback (not counted in the total)
    "total": 12.0 * MB,     # the README's WebP-path weight
}

# Generic terms only. The owner's private terms (room, household, names, device and account identifiers) live in a
# file OUTSIDE the repo, so this public file never lists them: $DESK_DIAL_PRIVATE_BLOCKLIST, or
# ../readme-work/private-blocklist.txt next to the repo (one term per line, # for comments). Without that file the
# gate still runs on the generic terms and says so.
BLOCKLIST = (
    "192.168.", "RINCON",
    "Kate Bush", "Massive Attack", "Floating Points", "Chromatics", "Miles Davis", "Jobim", "Tropic",
    "Danny Lewis", "Bambu", "Claude ·", "Slack", "ChatGPT", "Google Chrome", "Figma", "Spotify",
    "Steam", "homeassistant.local",
)
ALLOWLIST = {
    "tools/readme-media/gates.py": set(BLOCKLIST),
    "tools/readme-media/README.md": set(BLOCKLIST),
    "docs/setup/onshape.md": {"Google Chrome", "Figma"},
    "docs/faq.md": {"Spotify", "homeassistant.local", "Figma"},
    "docs/features/apps.md": {"Figma"},               # a supported app (app profiles, v2.0.0)
    # the release package's guides (deep-dive owned): Figma as a supported app, Home Assistant's default host
    "docs/compatibility.md": {"Figma"},
    "docs/recovery.md": {"Figma"},
    "docs/troubleshooting.md": {"Figma", "homeassistant.local"},
    "tools/readme-media/apps_strip.py": {"Figma"},     # the label under Karl's Figma icon
    "tools/readme-media/headlines.py": {"Figma"},      # the Apps chapter headline
    "README.md": {"Spotify", "Figma"},
    "docs/setup/home-assistant.md": {"homeassistant.local"},
    "docs/features/settings.md": {"homeassistant.local", "Figma"},   # the Address field's hint; the Apps list
    "tools/readme-media/app_screens.py": {"homeassistant.local", "Figma"},   # its own allow rules (HA hint, Apps page)
    "tools/readme-media/fiction.py": set(BLOCKLIST),   # the fixtures' own self-check copy of the blocklist
}
TEXT_SUFFIXES = {".md", ".json", ".py"}
IMAGE_SUFFIXES = {".png", ".webp", ".gif"}
SKIP_DIRS = {"__pycache__", ".git", "work", "build"}
DEFAULT_ROOTS = [REPO / "README.md", REPO / "docs", HERE]   # the public page, its media, this pipeline


def _pattern(term: str) -> re.Pattern:
    if re.fullmatch(r"[A-Za-z]+", term):
        return re.compile(rf"\b{re.escape(term)}\b")
    return re.compile(re.escape(term))


def _private_terms():
    import os
    path = Path(os.environ.get("DESK_DIAL_PRIVATE_BLOCKLIST") or (REPO.parent / "readme-work" / "private-blocklist.txt"))
    if not path.exists():
        print(f"blocklist: no private term list at {path} (generic terms only)", flush=True)
        return ()
    return tuple(line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#"))


PRIVATE_TERMS = _private_terms()
BLOCKLIST = BLOCKLIST + PRIVATE_TERMS
PATTERNS = {t: _pattern(t) for t in BLOCKLIST}


# ------------------------------------------------------------------ page weight
def _fmt(n: float) -> str:
    return f"{n / MB:.2f} MB" if n >= 100 * KB else f"{n / KB:.0f} KB"


def category(name: str) -> str:
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    if suffix == ".gif":
        return "gif"
    if suffix in (".png", ".svg", ".jpg", ".jpeg"):
        return "still"
    if stem == "hero" or stem.endswith("-hero"):
        return "hero"
    if stem.startswith("desktop-"):
        return "desktop"
    if stem.startswith("story-"):
        return "story"
    return "loop"


def readme_images(readme_path: Path):
    """[(path as written, counted toward total, how referenced)] for every image the README shows."""
    text = readme_path.read_text(encoding="utf-8")
    refs = []
    rest = []
    pos = 0
    for m in re.finditer(r"<picture>(.*?)</picture>", text, flags=re.S):
        rest.append(text[pos:m.start()])
        pos = m.end()
        block = m.group(1)
        src = re.search(r'<source[^>]*srcset="([^"\s]+)', block)
        img = re.search(r'<img[^>]*src="([^"]+)"', block)
        if src:
            refs.append((src.group(1), True, "<picture> source"))
            if img:
                refs.append((img.group(1), False, "<picture> img fallback"))
        elif img:
            refs.append((img.group(1), True, "<picture> img (no source)"))
    rest.append(text[pos:])
    outside = "".join(rest)
    for m in re.finditer(r'<img[^>]*src="([^"]+)"', outside):
        refs.append((m.group(1), True, "<img>"))
    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", outside):
        refs.append((m.group(1), True, "markdown"))
    return refs


def budget(out_dir: Path, readme_path: Path, caps: dict = CAPS) -> tuple[bool, str]:
    """Weigh every image README.md references. A referenced name that exists in out_dir is weighed
    there (so --check weighs the fresh render); otherwise paths resolve against the README's folder.
    Missing files fail too. Returns (ok, markdown table + totals)."""
    rows, total, failures = [], 0, []
    base = readme_path.parent
    seen = set()
    for ref, counted, how in readme_images(readme_path):
        if ref.startswith(("http://", "https://")):
            continue   # external badges (shields.io): a few KB each, not ours to size
        path = (base / ref).resolve()
        if (out_dir / Path(ref).name).exists():      # weigh the folder being rendered (or checked)
            path = (out_dir / Path(ref).name).resolve()
        if path in seen:
            continue
        seen.add(path)
        cat = category(path.name)
        if not path.exists():
            rows.append((path.name, cat, "missing", "", how, "FAIL"))
            failures.append(f"{ref}: missing")
            continue
        size = path.stat().st_size
        cap = caps[cat]
        ok = size <= cap
        if counted:
            total += size
        if not ok:
            failures.append(f"{path.name}: {_fmt(size)} > {_fmt(cap)} ({cat})")
        rows.append((path.name, cat, _fmt(size), _fmt(cap), how + ("" if counted else ", not in total"),
                     "ok" if ok else "FAIL"))
    ok_total = total <= caps["total"]
    if not ok_total:
        failures.append(f"README total {_fmt(total)} > {_fmt(caps['total'])}")
    lines = ["| file | class | size | cap | referenced as | gate |", "|---|---|---|---|---|---|"]
    lines += [f"| {n} | {c} | {s} | {cp} | {h} | {g} |" for n, c, s, cp, h, g in rows]
    lines.append("")
    lines.append(f"README WebP-path total: {_fmt(total)} of {_fmt(caps['total'])} "
                 f"-> {'ok' if ok_total else 'OVER BUDGET'}")
    if failures:
        lines.append("")
        lines.append("Over budget:")
        lines += [f"  - {f}" for f in failures]
    return not failures, "\n".join(lines)


# ------------------------------------------------------------------ blocklist
def _image_metadata(path: Path) -> str:
    """Every text-bearing metadata field of a PNG / WebP / GIF, never the pixels."""
    parts = []
    try:
        from PIL import Image
        with Image.open(path) as im:
            for key, val in im.info.items():
                if key in ("transparency", "duration", "loop", "background", "dpi", "gamma", "version",
                           "extension", "timestamp", "chromaticity", "srgb", "interlace", "aspect", "palette"):
                    continue
                if isinstance(val, bytes):
                    parts.append(f"{key}: " + val.decode("utf-8", "ignore") + " " +
                                 val.decode("utf-16-le", "ignore"))
                else:
                    parts.append(f"{key}: {val}")
            text = getattr(im, "text", None)
            if isinstance(text, dict):
                parts += [f"{k}: {v}" for k, v in text.items()]
            try:
                exif = im.getexif()
                parts += [f"exif {k}: {v}" for k, v in exif.items() if isinstance(v, (str, bytes))]
            except Exception:
                pass
    except Exception as e:  # unreadable image: say so, do not pass silently
        parts.append(f"<unreadable: {e}>")
    return "\n".join(str(p) for p in parts)


def _scan_text(text: str, allowed: set) -> list[tuple[str, int]]:
    hits = []
    for term, pat in PATTERNS.items():
        if term in allowed:
            continue
        for m in pat.finditer(text):
            hits.append((term, text.count("\n", 0, m.start()) + 1))
    return hits


def iter_files(roots):
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP_DIRS):
                yield p


def blocklist(paths, allow: dict = ALLOWLIST, repo: Path = REPO) -> tuple[bool, str]:
    """Scan every text file, image metadata set and file name under `paths`. Returns (ok, report)."""
    report = []
    n_files = 0
    for p in iter_files(paths):
        try:
            rel = p.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            rel = p.as_posix()
        allowed = allow.get(rel, set())
        n_files += 1
        for term, _ in _scan_text(p.name, allowed):
            report.append(f"{rel}: file name contains {term!r}")
        suffix = p.suffix.lower()
        if suffix in TEXT_SUFFIXES:
            for term, line in _scan_text(p.read_text(encoding="utf-8", errors="replace"), allowed):
                report.append(f"{rel}:{line}: {term!r}")
        elif suffix in IMAGE_SUFFIXES:
            meta = _image_metadata(p)
            for term, _ in _scan_text(meta, allowed):
                report.append(f"{rel}: image metadata contains {term!r}")
            if meta.startswith("<unreadable"):
                report.append(f"{rel}: {meta}")
    head = f"blocklist: {'clean' if not report else f'{len(report)} hit(s)'} ({n_files} files scanned)"
    return not report, "\n".join([head, *report])


# ------------------------------------------------------------------ sizes table
def sizes(out_dir: Path) -> str:
    """Markdown table of every media file in out_dir for docs/media/README.md."""
    import manifest as M
    lines = ["| file | bytes | dimensions | frames | fps |", "|---|---:|---|---:|---:|"]
    for p in M.media_files(out_dir):
        i = M.probe(p)
        dims = f"{i['width']}x{i['height']}" if i["width"] else ""
        fps = f"{i['fps']:g}" if i["fps"] else ""
        lines.append(f"| {p.name} | {p.stat().st_size:,} | {dims} | {i['frames']} | {fps} |")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="README media gates: budget, blocklist, sizes")
    ap.add_argument("command", choices=("budget", "blocklist", "sizes"))
    ap.add_argument("--media", type=Path, default=REPO / "docs" / "media")
    ap.add_argument("--readme", type=Path, default=REPO / "README.md")
    ap.add_argument("paths", nargs="*", type=Path, help="blocklist roots (default README.md, docs/, tools/readme-media)")
    a = ap.parse_args(argv)
    if a.command == "budget":
        ok, table = budget(a.media, a.readme)
        print(table)
        return 0 if ok else 1
    if a.command == "blocklist":
        ok, report = blocklist(a.paths or DEFAULT_ROOTS)
        print(report)
        return 0 if ok else 1
    print(sizes(a.media))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
