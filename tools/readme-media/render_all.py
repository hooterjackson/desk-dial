"""One command for the README media: build the headless renderers, run every scene, stamp the
manifest, run the gates, regenerate the docs/media/README.md table.

  python render_all.py --firmware <knob firmware> --harness <lcd-preview> --app <companion source>
                       --build <build dir> --work <scratch dir> --out <repo>/docs/media
                       [--scenes hero stills ...] [--skip-build] [--check] [--no-logo]

Steps, in order (each timed and logged):
  1. build      build_lcd.py configures tools/readme-media/lcd with CMake + MSVC and builds
                knob-anim (+ app-canvas-anim, haptic-trace, sound-dump when present). --skip-build reuses <build>.
  2. scenes     every entry of scenes_registry.SCENES (or the --scenes subset) renders into --out.
  3. manifest   manifest.write(--out): per-file bytes/sha256/dimensions/frames and the firmware /
                app / pipeline stamps (generated_at is read here, once, and passed in).
  4. gates      gates.budget (README page weight), gates.blocklist (fictional data), gates.sizes
                (the table between <!-- media-table --> ... <!-- /media-table --> in <out>/README.md).
                A failed gate exits non-zero after every step has run and printed.
  --check       renders into a temporary out dir instead, then manifest.check against the committed
                <out>/manifest.json (files added / removed / changed, stamp drift) and exits non-zero on
                any difference. Run it before a push; nothing under --out is touched.

Everything is headless and uses fictional data only (fixtures.py): no knob, no speakers, no network.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
PY = sys.executable
TABLE_START, TABLE_END = "<!-- media-table -->", "<!-- /media-table -->"


def step(name, started):
    print(f"== {name}: {time.time() - started:.1f}s", flush=True)


def build(a):
    cmd = [PY, str(HERE / "build_lcd.py"), "--firmware", str(a.firmware), "--harness", str(a.harness),
           "--build", str(a.build)] + (["--no-logo"] if a.no_logo else [])
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def run_scenes(ctx, wanted, registry):
    timings = {}
    for name in wanted:
        if name not in registry:
            raise SystemExit(f"unknown scene {name!r}; registered: {', '.join(registry)}")
    for name in wanted:
        ctx.scene = name
        t0 = time.time()
        print(f"-- scene {name}", flush=True)
        paths = registry[name](ctx)
        for p in paths:
            print(f"  [{name}] {Path(p).name}  {Path(p).stat().st_size / 1e6:.2f} MB", flush=True)
        timings[name] = time.time() - t0
        step(f"scene {name}", t0)
    return timings


def update_media_readme(out_dir: Path, table: str):
    """Replace the block between the media-table markers in <out>/README.md (created if missing)."""
    path = out_dir / "README.md"
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = ("# README media\n\nRendered by `tools/readme-media/render_all.py` from fictional data "
                "(see `tools/readme-media/README.md`). Do not edit the files by hand; re-render.\n\n"
                f"{TABLE_START}\n{TABLE_END}\n")
    if TABLE_START not in text or TABLE_END not in text:
        text = text.rstrip("\n") + f"\n\n{TABLE_START}\n{TABLE_END}\n"
    head, rest = text.split(TABLE_START, 1)
    _, tail = rest.split(TABLE_END, 1)
    path.write_text(f"{head}{TABLE_START}\n{table}\n{TABLE_END}{tail}", encoding="utf-8")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--firmware", required=True, type=Path)
    ap.add_argument("--harness", required=True, type=Path)
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path, help="docs/media of the publish repo")
    ap.add_argument("--readme", type=Path, help="the README that references the media (default <out>/../../README.md)")
    ap.add_argument("--scenes", nargs="+", metavar="NAME")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-logo", action="store_true")
    ap.add_argument("--list", action="store_true", help="print the registered scenes and exit")
    a = ap.parse_args(argv)
    a.firmware, a.harness, a.app, a.build, a.work = (p.resolve() for p in (a.firmware, a.harness, a.app, a.build, a.work))
    a.out = a.out.resolve()
    readme = (a.readme or a.out.parent.parent / "README.md").resolve()
    repo = readme.parent
    os.environ["DESK_DIAL_APP"] = str(a.app)

    import scenes_registry as R
    import manifest as M
    import gates as G
    if a.list:
        for k in R.SCENES:
            print(k)
        return 0

    t_all = time.time()
    a.work.mkdir(parents=True, exist_ok=True)
    if not a.skip_build:
        t0 = time.time()
        build(a)
        step("build", t0)

    tmp = None
    if a.check:
        tmp = Path(tempfile.mkdtemp(prefix="readme-media-check-", dir=str(a.work)))
        out = tmp
        # a partial --scenes check compares only what was rendered: seed the rest from the committed folder
        for p in M.media_files(a.out):
            shutil.copy2(p, out / p.name)
    else:
        out = a.out
        out.mkdir(parents=True, exist_ok=True)

    ctx = R.Context(firmware=a.firmware, harness=a.harness, app=a.app, build=a.build, work=a.work, out=out,
                    no_logo=a.no_logo)
    wanted = a.scenes or list(R.SCENES)
    timings = run_scenes(ctx, wanted, R.SCENES)

    context = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "firmware_dir": a.firmware, "app_dir": a.app, "pipeline_dir": HERE, "publish_repo": repo}
    failures = []

    if a.check:
        committed = a.out / "manifest.json"
        if not committed.exists():
            print(f"check: no committed manifest at {committed}", flush=True)
            failures.append("manifest missing")
        else:
            ok, report = M.check(out, committed, context)
            print(report, flush=True)
            if not ok:
                failures.append("manifest drift")
        ok, table = G.budget(out, readme) if readme.exists() else (True, "(no README to weigh)")
        print(table, flush=True)
        if not ok:
            failures.append("budget")
        ok, report = G.blocklist([readme, repo / "docs", HERE])
        print(report, flush=True)
        if not ok:
            failures.append("blocklist")
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        t0 = time.time()
        man = M.write(out, ctx.entries, context)
        print(f"manifest.json: {len(man['files'])} files, firmware {man['firmware']['version']} "
              f"({'dirty' if man['firmware']['dirty'] else 'clean'}), app {man['app']['version']}", flush=True)
        step("manifest", t0)

        t0 = time.time()
        if readme.exists():
            ok, table = G.budget(out, readme)
            print(table, flush=True)
            if not ok:
                failures.append("budget")
        else:
            print(f"(no README at {readme}: budget skipped)")
        ok, report = G.blocklist([readme, repo / "docs", HERE])
        print(report, flush=True)
        if not ok:
            failures.append("blocklist")
        path = update_media_readme(out, G.sizes(out))
        print(f"sizes table -> {path}", flush=True)
        step("gates", t0)

    print("timing per scene: " + ", ".join(f"{k} {v:.0f}s" for k, v in timings.items()), flush=True)
    step("total", t_all)
    if failures:
        print(f"FAILED: {', '.join(failures)}", flush=True)
        return 1
    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
