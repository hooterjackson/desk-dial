"""The short look session after a fix binary's install (1.0.0-cc5.4 binary D or E, the PRESENTATION_V5 12.6
ladder's fix binaries after A's rollback; firmware/BUILD-cc5.4.md "Fix binaries D and E"): two read-only diag
reads before the user looks at the knob, then the user's answers.

Read mode (the default). It refuses while Desk Dial (DeskDial.exe) or the older NanoDControlCenter.exe runs
(tooling.require_companion_quit: NOT RUN, exit 3, nothing opened), finds the one application port (239A:8010,
serial NANO_D; tooling.find_app_port), reads {"diag":"?"} twice (tooling.probe_diag: open, read, close; no claim,
no release, no frame), at least 1.5 s apart (--gap, default 2 s), and applies tooling.look_check_problems for
--binary (default D, the first of tooling.ACTIVE_BINARIES):
  * build: diag "build" is the binary's letter, and lcdDma / lcdPeriodMs / artAsync are its pipeline (D: true /
    16 / true, A's; E: false / 33 / false, C's), in both reads;
  * lcdMosiSig 103 in both reads: the LCD data line on FSPID (102, FSPIQ_OUT, is binary A's dark-LCD defect; a
    missing field is an image without the fix);
  * the coredump partition blank (after a step-down, only the dump this binary's step-down base holds,
    tooling.step_down_coredump) and a reset reason that is not a crash (panic, int_wdt, task_wdt, wdt,
    brownout);
  * no reboot between the reads (bootCount unchanged, uptime advanced).
It records, without gating them, ledFps, ledShowGapMsMax, ledMode, lcdFps and lcdFullRefrs of both reads (the LED
and LCD timings are the later performance task's; the full 8b / 8c checks, check_nanod_cc5.py and
check_nanod_cc5_lease.py, are not part of the look session). Evidence: diagnostics/cc5.4-<X>-look-checks.json
(tooling Release.look_checks; a previous one is kept as *.superseded-<UTC>.json, never overwritten). Prints GO
(exit 0) or NO-GO (exit 1) with the reasons. NO-GO: do not ask the user to look; roll the binary back
(rollback_nanod_cc5.py --to cc5.3 --binary <X>, BUILD-cc5.4.md). A diag read that fails while a companion has
started meanwhile is NOT RUN (exit 3, no evidence), never a NO-GO.

--record-by-eye KEY=pass|fail ... [--note TEXT]: adds the user's answers (any of the five; a later call adds to
the earlier answers) to the binary's look-check record, whose previous file is kept as *.superseded-<UTC>.json. It
opens no port, so it runs while Desk Dial runs. Exit 0 when every answer recorded is pass, 1 when one is fail, 2
when there is no look-check record of this binary (run the read first). The record is complete once all five are
answered:
  leds:   at rest and offline the ring and button LEDs are steady (no shimmer, sparkle or flip at the dim point)
          and every dim mark stays visible at the low point of the breath;
  hue:    the marks read in their colour while bright (amber offline); at the dim point a mark shows one count of
          red (#010000, amber's dominant channel), which is expected (ALIVE.md 9 step 4, 12.7);
  screen: the native dial is drawn (not dark, not the old image) and a few detents move the value (live pixels:
          the GC9A01 keeps cc5.3's last frame across a reset, so a static image proves nothing);
  screen_host: with Desk Dial driving Home for about 5 minutes (cover changes, volume turns) the knob's screen
          keeps updating, never dark, frozen or garbled (a DMA build holds the panel's CS low for its whole uptime,
          so one SPI framing slip would misframe every later command until a reboot);
  screen_after_quit: after the user quits Desk Dial from its tray (an intentional release: it hands the knob
          back), the native dial comes back and a few detents move its value.

No beeps (audible cues are only for the turning test), no esptool, nothing written to the knob. Run with the
companion's interpreter:
  app\\.venv\\Scripts\\python.exe tools\\check_nanod_cc5_look.py --binary D
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402  (no side effects on import)

EXIT_GO, EXIT_NO_GO, EXIT_USAGE, EXIT_NOT_RUN = 0, 1, 2, 3
DEFAULT_GAP_S = 2.0
BY_EYE_QUESTIONS = {
    "leds": ("at rest and offline the ring and button LEDs are steady (no shimmer, sparkle or flip at the dim point) "
             "and every dim mark stays visible at the low point of the breath"),
    "hue": ("the marks read in their colour while bright (amber offline); at the dim point a mark shows one count of "
            "red (#010000, amber's dominant channel), which is expected (ALIVE.md 9 step 4, 12.7)"),
    "screen": ("the native dial is drawn (not dark, not the old image) and a few detents move the value (live pixels: "
               "the GC9A01 keeps cc5.3's last frame across a reset, so a static image proves nothing)"),
    "screen_host": ("with Desk Dial driving Home for about 5 minutes (cover changes, volume turns) the knob's screen keeps "
                    "updating, never dark, frozen or garbled"),
    "screen_after_quit": ("after the user quits Desk Dial from its tray (it hands the knob back), the native dial "
                          "comes back and a few detents move its value"),
}
RECORD_HINT = " ".join(f"{key}=pass|fail" for key in BY_EYE_QUESTIONS)
CONTRACT = ("firmware/BUILD-cc5.4.md (Fix binaries D and E, the look session); PRESENTATION_V5.md 12.6; ALIVE.md 9 "
            "(dither off by default and the brightness floor, user ruling 2026-09-26)")


def parse_by_eye(items):
    """{"leds": "pass"|"fail", "screen": ...} from `key=value` items; ValueError names the first bad one."""
    answers = {}
    for item in items:
        key, sep, value = str(item).partition("=")
        if not sep or key not in BY_EYE_QUESTIONS or value not in ("pass", "fail") or key in answers:
            raise ValueError(f"{item!r} is not one of {', '.join(f'{k}=pass|fail' for k in BY_EYE_QUESTIONS)} "
                             "(each at most once)")
        answers[key] = value
    return answers


def recorded(diag):
    """The fields recorded, not gated (tooling.LOOK_RECORDED_FIELDS), of one diag reply."""
    return {k: diag.get(k) for k in t.LOOK_RECORDED_FIELDS} if isinstance(diag, dict) else None


def read_diags(port, gap, *, sleep=time.sleep, clock=time.monotonic):
    """(first diag, second diag, seconds between the two replies): tooling.probe_diag twice, `gap` s apart."""
    started = clock()
    first = t.probe_diag(port)
    first_at = clock() - started
    sleep(gap)
    second = t.probe_diag(port)
    return first, second, round(clock() - started - first_at, 3)


def look(p, args, *, sleep, clock):
    """Read mode: the evidence record and the exit code (NOT RUN returns (None, 3) and writes nothing)."""
    try:
        t.require_companion_quit()
        port = t.find_app_port()
    except (SystemExit, t.PortError) as exc:
        print(f"NOT RUN: {exc}", flush=True)
        return None, EXIT_NOT_RUN
    started = t.utc_stamp()
    record = {"tool": "tools/check_nanod_cc5_look.py", "firmwareVersion": p.version, "binary": p.binary,
              "role": t.BINARY_ROLES[p.binary], "startedUtc": started, "port": port,
              "expected": {"build": p.binary, "pipeline": p.pipeline, "lcdMosiSig": t.LCD_MOSI_SIGNAL},
              "requiredGapS": t.LOOK_READ_GAP_MIN_S, "readGapS": None, "reads": [], "recorded": None,
              "recordedOnly": list(t.LOOK_RECORDED_FIELDS), "inheritedCoredump": None, "problems": [],
              "go": False, "verdict": "NO-GO", "byEye": None, "note": args.note, "contract": CONTRACT,
              "notRun": ("the full 8b / 8c device checks (check_nanod_cc5.py, check_nanod_cc5_lease.py) and "
                         "finalize are not part of the look session")}
    try:
        first, second, gap = read_diags(port, args.gap, sleep=sleep, clock=clock)
    except Exception as exc:                       # a timeout, a busy or vanished port: nothing was written to the knob
        running = t.running_companions()
        if running:
            print(f"NOT RUN: {' and '.join(running)} started during the reads and owns the port ({type(exc).__name__}: "
                  f"{exc}); quit it and run this again", flush=True)
            return None, EXIT_NOT_RUN
        record["problems"] = [f"diag read failed ({type(exc).__name__}: {exc})"]
    else:
        inherited = t.step_down_coredump(t.CURRENT, p.binary)
        record.update(readGapS=gap, reads=[{"read": 1, "diag": first}, {"read": 2, "diag": second}],
                      recorded={"first": recorded(first), "second": recorded(second)}, inheritedCoredump=inherited)
        problems = t.look_check_problems(first, second, p.binary, inherited)
        if gap < t.LOOK_READ_GAP_MIN_S:
            problems.append(f"the two diag reads were {gap} s apart, less than {t.LOOK_READ_GAP_MIN_S} s")
        record["problems"] = problems
    record["go"] = not record["problems"]
    record["verdict"] = "GO" if record["go"] else "NO-GO"
    record["finishedUtc"] = t.utc_stamp()
    return record, EXIT_GO if record["go"] else EXIT_NO_GO


def record_by_eye(p, answers, note):
    """--record-by-eye: the user's answers added to the binary's look-check record (no port); (record, exit code)."""
    try:
        record = t.load_json(p.look_checks)
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict) or record.get("binary") != p.binary:
        print(f"No look-check record of binary {p.binary} ({p.look_checks.name}): run check_nanod_cc5_look.py "
              f"--binary {p.binary} first. Nothing was recorded.", flush=True)
        return None, EXIT_USAGE
    previous = record.get("byEye") if isinstance(record.get("byEye"), dict) else {}
    merged = {**(previous.get("answers") or {}), **answers}
    notes = list(previous.get("notes") or []) + ([note] if note else [])
    record["byEye"] = {"answers": merged, "questions": {k: BY_EYE_QUESTIONS[k] for k in merged},
                       "notes": notes, "recordedUtc": t.utc_stamp(),
                       "passed": all(value == "pass" for value in merged.values()),
                       "complete": set(merged) == set(BY_EYE_QUESTIONS)}
    return record, EXIT_GO if record["byEye"]["passed"] else EXIT_NO_GO


def main(argv=None, *, sleep=time.sleep, clock=time.monotonic):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = t.binary_choices()
    parser.add_argument("--binary", choices=choices, default=choices[0] if choices else None,
                        help=f"the fix binary just installed (default {choices[0] if choices else 'none'})")
    parser.add_argument("--gap", type=float, default=DEFAULT_GAP_S,
                        help=f"seconds between the two diag reads (at least {t.LOOK_READ_GAP_MIN_S:g}; default "
                             f"{DEFAULT_GAP_S:g})")
    parser.add_argument("--record-by-eye", nargs="+", metavar="KEY=pass|fail",
                        help=f"record the user's answers ({RECORD_HINT}; any of them) without opening a port")
    parser.add_argument("--note", help="a short note recorded with the read or the answers")
    args = parser.parse_args(argv)
    if not choices:
        parser.error(f"{t.CURRENT.version} has no fix binaries to look at")
    if args.gap < t.LOOK_READ_GAP_MIN_S:
        parser.error(f"--gap must be at least {t.LOOK_READ_GAP_MIN_S:g} s")
    answers = None
    if args.record_by_eye:
        try:
            answers = parse_by_eye(args.record_by_eye)
        except ValueError as exc:
            parser.error(str(exc))
    t.console_utf8()
    p = t.CURRENT.binary_profile(args.binary)
    if answers is not None:
        record, code = record_by_eye(p, answers, args.note)
    else:
        record, code = look(p, args, sleep=sleep, clock=clock)
    if record is None:
        return code
    archived = t.write_json_evidence(p.look_checks, record)
    kept = f" (previous kept as {archived.name})" if archived else ""
    if answers is not None:
        eye = record["byEye"]
        print(f"By eye, binary {p.binary}: " + ", ".join(f"{k} {v}" for k, v in eye["answers"].items())
              + f" -> {'PASS' if eye['passed'] else 'FAIL'}"
              + ("" if eye["complete"] else f" (still to answer: {', '.join(sorted(set(BY_EYE_QUESTIONS) - set(eye['answers'])))})")
              + f"; the diag reads were {record.get('verdict')}.", flush=True)
    else:
        print(f"Look check, binary {p.binary} ({t.BINARY_ROLES[p.binary]}): {record['verdict']}", flush=True)
        for problem in record["problems"]:
            print(f" - {problem}", flush=True)
        for label, values in (record.get("recorded") or {}).items():
            print(f"   recorded ({label} read): {values}", flush=True)
        if record["go"]:
            print("GO: ask the user to look (the offline LED marks at rest, the screen with a few detents, then Desk Dial "
                  "on Home for about 5 minutes and the native dial after quitting it), then record the answers: "
                  f"check_nanod_cc5_look.py --binary {p.binary} --record-by-eye {RECORD_HINT}", flush=True)
        else:
            print(f"NO-GO: do not ask the user to look; roll binary {p.binary} back (rollback_nanod_cc5.py --to cc5.3 "
                  f"--binary {p.binary}; firmware/BUILD-cc5.4.md).", flush=True)
    print(f"Evidence: {p.look_checks}{kept}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
