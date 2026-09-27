"""Supervised on-screen check of desktop v7 (DESKTOP_STAGE.md 6.4 / 6.5 S1 subset; ALIVE.md K2 floating knob).

Run it from the main session only, with the user's go-ahead, while the v7 companion runs (installed with
Install-Desktop.ps1, or desktop-dist-v7 started by the user) and the user is at the knob. It is read-only:
  * it never starts, stops or signals the companion, never opens a serial port, never touches the knob,
    Sonos or Apple Music, and never shows anything itself;
  * it only reads %LOCALAPPDATA%\\DeskDial\\logs\\status.json (written by the app every second; v7 is Desk Dial)
    and counts ERROR lines in logs\\app.log (their text is never copied);
  * it records whitelisted numbers only (frame episodes, overlay counters, the process timing self-check,
    open surfaces), never a window title, profile name or settings value, in
    app/diagnostics/desktop-v7-supervised-check.json (an earlier record is kept as
    desktop-v7-supervised-check.superseded-<UTC>.json).

Without --go it only prints the plan and whether status.json is fresh. With --go it walks the steps; each
waits (up to --step-seconds) for its own evidence in status.json, so nothing has to be typed:
  knob_slow   turn slowly ~5 s, let go            -> a new frames.knob ring episode (alive at every vblank)
  knob_spin   spin fast ~5 s, let go              -> another ring episode (work p95, cadence switches)
  end_stop    Volume at 0 %, keep turning 2 s     -> a ring episode summoned by limit input (cc5.4 only)
  explorer    Recently Added, button 2, ~20 detents, Back -> frames.explorer episode; the knob stays hidden
  upnext      Tracks, button 2, turn, Back        -> frames.upnext episode; the knob stays hidden
  idle_close  (--with-idle) open the explorer, leave the knob 60 s -> it closes by itself (reason idle)
The turning steps beep on the PC only when NANOD_AUDIBLE_CUES=1 (the knob-hands-on rule).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

APP = Path(__file__).resolve().parents[1] / "app"
DIAGNOSTICS = APP / "diagnostics"
EVIDENCE = DIAGNOSTICS / "desktop-v7-supervised-check.json"
BUILD_RECORD = DIAGNOSTICS / "desktop-v7-build.json"
# Desktop v7 is Desk Dial (rename-desk-dial.md): its home and program folder. The old NanoDControlCenter home
# stays as the migration's backup and is never read here (its status.json is stale).
LOGS = Path(os.environ.get("LOCALAPPDATA", "")) / "DeskDial" / "logs"
INSTALLED_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DeskDial" / "DeskDial.exe"
FRESH_SECONDS = 5.0
POLL_SECONDS = 0.25
OVERLAY_FIELDS = ("state", "alive", "dpi", "frames_presented", "engine_renders", "hidden_renders", "catchup_renders",
                  "frames_skipped", "alive_failures", "inputs_posted", "inputs_dropped", "reduced_motion",
                  "looks_build_ms", "frames_composed", "compose_ms", "ulw_failures", "suppressed", "pacing",
                  "gdi_objects", "user_objects")
EPISODE_FIELDS = ("kind", "method", "frames", "vblanks", "fps", "interval_ms", "missed", "double_missed", "work_ms",
                  "present_ms", "cadence_switches", "rate_hz", "rm", "duration_ms", "changed", "late_changed",
                  "late_2P", "on_target")
STEPS = (
    ("knob_slow", "Turn the knob slowly for about 5 s, then let go (the knob slides out 2.5 s later).", "knob", True),
    ("knob_spin", "Spin the knob fast for about 5 s, then let go.", "knob", True),
    ("end_stop", "On Volume, turn down to 0 % and keep turning against the end stop for 2 s, then let go.",
     "knob", True),
    ("explorer", "Go to Recently Added, press button 2 (Open on screen), turn about 20 detents, then press Back.",
     "explorer", False),
    ("upnext", "Go to Tracks, press button 2 (Open Up next), turn through the queue, then press Back.",
     "upnext", False),
)
IDLE_STEP = ("idle_close", "Open the explorer again (Recently Added, button 2), then leave the knob alone for 60 s.",
             "explorer", False)


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_status(path=None, tries=8):
    """status.json as a dict, or None (the app rewrites it every second, so a read can be partial)."""
    path = Path(path or LOGS / "status.json")
    for _ in range(tries):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            time.sleep(0.05)
    return None


def fresh(status, now=None):
    now = time.time() if now is None else now
    return isinstance(status, dict) and isinstance(status.get("time"), (int, float)) \
        and abs(now - status["time"]) <= FRESH_SECONDS


def episodes(node):
    """Every ``totals`` episode count under one ``frames.<surface>`` (knob: slide + ring; stage: per kind)."""
    total = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "episodes" and isinstance(value, int):
                total += value
            elif isinstance(value, dict):
                total += episodes(value)
    return total


def ring_episodes(status):
    ring = (((status or {}).get("frames") or {}).get("knob") or {}).get("ring") or {}
    return int(((ring.get("totals") or {}).get("episodes")) or 0)


def surface_episodes(status, surface):
    if surface == "knob":
        return ring_episodes(status)
    return episodes(((status or {}).get("frames") or {}).get(surface))


def last_episode(status, surface):
    frames = ((status or {}).get("frames") or {}).get(surface) or {}
    last = (frames.get("ring") or {}).get("last") if surface == "knob" else frames.get("last")
    return {k: last.get(k) for k in EPISODE_FIELDS if k in last} if isinstance(last, dict) else None


def overlay_summary(status):
    overlay = (status or {}).get("overlay") or {}
    return {k: overlay.get(k) for k in OVERLAY_FIELDS if k in overlay}


def error_lines(since_offset):
    """(ERROR line count after byte offset, new offset) of logs/app.log; the text is never kept."""
    path = LOGS / "app.log"
    try:
        with open(path, "rb") as handle:
            handle.seek(since_offset)
            data = handle.read()
    except OSError:
        return 0, since_offset
    return data.count(b" ERROR "), since_offset + len(data)


def cue(frequency=880, milliseconds=180):
    """PC beep for the turning steps, only with NANOD_AUDIBLE_CUES=1; never fails."""
    if os.environ.get("NANOD_AUDIBLE_CUES") != "1":
        return
    try:
        import winsound
        winsound.Beep(frequency, milliseconds)
    except Exception:
        pass


def run_step(name, prompt, surface, turning, step_seconds, *, read=read_status, clock=time.monotonic,
             sleep=time.sleep, out=print):
    """Wait for the step's evidence. Knob steps: a new ring episode. Stage steps: the surface seen open,
    then closed, and a new frames.<surface> episode; the knob's overlay state is sampled while it is open."""
    start = read()
    base = surface_episodes(start, surface)
    base_inputs = (start or {}).get("overlay", {}).get("inputs_posted") if isinstance(start, dict) else None
    out(f"\n[{name}] {prompt}")
    if turning:
        cue()
    t0 = clock()
    seen_open = closed_after = None
    knob_states = set()
    status = start
    while clock() - t0 < step_seconds:
        sleep(POLL_SECONDS)
        status = read()
        if not fresh(status):
            continue
        if surface != "knob":
            open_now = surface in (status.get("openSurfaces") or [])
            if open_now:
                seen_open = seen_open if seen_open is not None else clock() - t0
                knob_states.add(str(overlay_summary(status).get("state")))
            elif seen_open is not None and closed_after is None:
                closed_after = clock() - t0
        if surface_episodes(status, surface) > base and (surface == "knob" or closed_after is not None):
            break
    record = {"step": name, "surface": surface, "seconds": round(clock() - t0, 1),
              "episodes": surface_episodes(status, surface) - base, "last": last_episode(status, surface),
              "overlay": overlay_summary(status)}
    if surface == "knob":
        inputs = (status or {}).get("overlay", {}).get("inputs_posted") if isinstance(status, dict) else None
        record["inputsPosted"] = (inputs - base_inputs) if isinstance(inputs, int) and isinstance(base_inputs, int) \
            else None
        record["passed"] = record["episodes"] >= 1
    else:
        record.update(openedAfterSeconds=seen_open, closedAfterSeconds=closed_after,
                      knobStatesWhileOpen=sorted(knob_states))
        record["passed"] = bool(record["episodes"] >= 1 and seen_open is not None and closed_after is not None
                                and not (knob_states - {"hidden", "out", "None"}))   # never "in" or "shown"
    out(f"[{name}] {'ok' if record['passed'] else 'NOT SEEN'} ({record['seconds']} s)")
    return record


def keep_previous(path):
    if path.exists():
        kept = path.with_name(f"{path.stem}.superseded-{utc_stamp()}{path.suffix}")
        path.rename(kept)
        return kept.name
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--go", action="store_true", help="the user gave the go-ahead and is at the knob")
    parser.add_argument("--step-seconds", type=float, default=90.0)
    parser.add_argument("--with-idle", action="store_true", help="also the 60 s idle close of the explorer")
    parser.add_argument("--verdict", default="", help="the user's one-line verdict, recorded as given")
    args = parser.parse_args(argv)
    status = read_status()
    print(f"status.json: {'fresh' if fresh(status) else 'NOT fresh (is the v7 companion running?)'}")
    steps = list(STEPS) + ([IDLE_STEP] if args.with_idle else [])
    if not args.go:
        print("Plan (nothing is checked without --go):")
        for name, prompt, _surface, _turning in steps:
            print(f"  {name}: {prompt}")
        return 0
    if not fresh(status):
        print("STOP: status.json is not being written; start the v7 companion first. Nothing was recorded.")
        return 2
    built = json.loads(BUILD_RECORD.read_text(encoding="utf-8")) if BUILD_RECORD.is_file() else {}
    installed = sha256_file(INSTALLED_EXE) if INSTALLED_EXE.is_file() else None
    _, offset = error_lines(0)
    started = utc_stamp()
    records = [run_step(name, prompt, surface, turning, args.step_seconds + (60.0 if name == "idle_close" else 0.0))
               for name, prompt, surface, turning in steps]
    errors, _ = error_lines(offset)
    final = read_status()
    report = {
        "check": "desktop v7 supervised on-screen check (DESKTOP_STAGE.md 6.4 / 6.5 S1 subset; ALIVE.md floating knob)",
        "startedUtc": started, "finishedUtc": utc_stamp(),
        "installedExeSha256": installed, "bundleExeSha256": (built.get("exe") or {}).get("sha256"),
        "installedIsBundle": bool(installed and installed == (built.get("exe") or {}).get("sha256")),
        "frozen": (final or {}).get("frozen"), "connected": (final or {}).get("connected"),
        "firmwarePresentation": (final or {}).get("firmwarePresentation"),
        "reducedMotion": (final or {}).get("reducedMotion"), "process": (final or {}).get("process"),
        "steps": records, "errorsLogged": errors, "verdict": args.verdict,
        "passed": all(r["passed"] for r in records) and errors == 0,
    }
    kept = keep_previous(EVIDENCE)
    EVIDENCE.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\n{'PASSED' if report['passed'] else 'NOT PASSED'}: {sum(r['passed'] for r in records)}/{len(records)} "
          f"steps, {errors} error lines. Record: {EVIDENCE.name}" + (f" (previous kept as {kept})" if kept else ""))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
