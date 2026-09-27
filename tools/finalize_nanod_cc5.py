"""Record the verified installation of the current release (nanod_cc5_tooling.CURRENT: 1.0.0-cc5.4
over 1.0.0-cc5.3); no device, network or desktop actions.

Stage 10 step 10 (firmware/BUILD-<tag>.md), run with the companion interpreter:
  & '<repo>\\app\\.venv\\Scripts\\python.exe'
      '<repo>\\tools\\finalize_nanod_cc5.py'
      --companion-tests N --light-assertions N [--binary D|E]
      [--waive-gate NAME ... --waiver-note TEXT]

Every check runs before anything is written; if one fails, nothing is recorded.

1.0.0-cc5.4 is staged as the PRESENTATION_V5 12.6 ladder: --binary (default D) names the binary that
passed the hardware window and is recorded as installed: an active fix binary, D or E (the retired A, B and C
are refused by argparse, exit 2, nothing recorded). Its own records are the evidence below under
the binary's names (cc5.4-D-*.json, cc5.4-E-*.json for the preparation, flash record and installation record;
A's were cc5.4-*.json; the backup record, the step-down base record and the device and lease check records are
the release's, cc5.4-*.json, shared by every binary and tied to this binary's install by their times), and
the device checks must report that binary (tooling.lcd_binary: diag build on D and E with its pipeline, lcdDma /
lcdPeriodMs / artAsync; sections.diag.binary). The manifest recorded as installed is the binary's
(manifest-1.0.0-cc5.4-D.json or -E.json); the other binaries' manifests are left as they are and named in the
installation record ("ladder"). D keeps A's LCD timing targets (lcdTimings), so D cannot pass that gate before
the later performance task.

Required evidence (diagnostics/ and backups/), all of this release (<prefix>-*.json: cc5.4-*.json;
the records of earlier releases, cc5-*.json and cc5.3-*.json, are history and never read as this
release's evidence):
  * <prefix>-backup.json and <prefix>-preparation.json, agreeing with each other and with the flash record.
    A binary prepared after a step-down from the release's step-down base (preparation "baseKind" "step-down
    base") also needs <prefix>-step-down-base.json: passed, naming that base file and SHA-256, read against the
    backup <prefix>-backup.json records; and the flash record must name the same base ("baseFile").
  * <prefix>-flash-checks.json with outcome INSTALLED_VERIFIED_RESET: identity, the pre-write
    verify, the app0 write and the full 4 MB post-write verify all passed, the reset was
    confirmed, and no restore was attempted. INSTALLED_VERIFIED_RESET_UNCONFIRMED (install
    exit 5) is accepted only with --accept-unconfirmed-reset, after the printed reset command
    was run once; the checks below are then the proof of the reboot into the release.
  * <prefix>-device-checks.json, newer than the flash record: passed, port closed, capabilities
    presentation = the profile's (5 for 1.0.0-cc5.4), its inventory check reporting the release's
    firmware and, for a ladder release, sections.diag.binary equal to the binary being recorded. Its hard gates (the "gates" object) must all be true: REQUIRED_GATES = the profile's
    gates (tooling.CURRENT.gates: the cc5.2 gates, the artwork2 gates of 1.0.0-cc5.3 and, for
    1.0.0-cc5.4, the ALIVE.md 11.9 and PRESENTATION_V5.md 15.4 gates). The after-inventory it names
    (backups/, also newer than the flash record) reports the release, the profile's presentation, the
    v1 artwork capability unchanged, artwork2 equal to presentation.ARTWORK2_CAPABILITY and, for an
    alive release, alive equal to tooling.alive_capability(the knob's ledMaxBrightness); against the
    before-inventory (the from-release), the ten saved profiles (an object mapping each name to its
    profile, as DeviceBridge writes it) are identical and only firmwareVersion changed.
  * <prefix>-lease-checks.json, newer than the flash record: passed (which includes no reboot
    between its first and last diag), with both artwork2 cases passed (media lines alone do
    not renew the lease; frames continue during unpaced media transfers).
The SHA-256 of each of these files is recorded in <prefix>-installation.json.

A gate can be waived, never lowered: --waive-gate NAME (repeatable) with --waiver-note TEXT, only with the
user's explicit sign-off in the hardware window, and only for WAIVABLE_GATES, in two categories; any other
name, or a waiver without a note, is refused before any evidence is read. A waived gate that is false is
accepted only when every failed device check is one of the waived gates' own checks and failed for its miss
alone, and each waived gate has such a failed check; every gate not waived must still be true.
  * performance (PERFORMANCE_GATES: lcdTimings, ledRenderTime, jpegDecode, ledFrameRate): the measured miss of
    a timing target (tooling.lcd_timing_problems: LCD FRAME RATE, LCD LATE REFRESHES; led_render_problems: LED
    RENDER TOO SLOW; jpeg_decode_problems: SLOW JPEG DECODE; led_idle_problems: LED FRAME RATE AT IDLE, LED SHOW
    GAP AT IDLE; led_load_summary: LED FRAME RATE UNDER LOAD). lcdTimings also needs
    sections.lcdAnimation.coverCommitted true, and ledFrameRate the idle measurement of the alive renderer
    (sections.ledIdle.diag.ledMode "alive"), every LED load cover committed (sections.ledUnderLoad; a cover
    upload that did not commit is a media failure no check reports) and a running renderer (LED_WAIVER_LIMITS:
    idle and load ledFps at least half their targets, the idle show gap at most twice its target).
  * operator timing (OPERATOR_TIMING_GATES: limitPerPush, limitEvents): the End stop test's push windows were
    missed. Its failed checks may name only a missed push (per-push count 0), nothing while held (0), a lim
    outside the windows, or an end not seen on the judged attempt (no lim +1 / -1 seen); a per-push or held
    count of 2 or more, two lims closer than the firmware's spacing, or two lims of one direction closer than
    one physical push can repeat (LIM_SAME_DIRECTION_MIN_S) is chatter (a firmware fault) and always refuses.
    The End stop runs (sections.handsOn.endStop.runs) must prove the firmware emitted its events in the right
    direction at the right end: a lim +1 during the push phase at T_end (perPush, held or a +1 in stray) and a
    lim -1 after the knob reported 0:00 (reachedZero and limAtZero), each in at least one run; never two lims of
    a run closer than tooling.ALIVE_LIM_GAP_S less the 50 ms jitter limit_problems allows; and every run's own
    problems End stop timing only. limitEvents also needs the stress+turn lims (sections.stressTurn.lims) passed.
A waived gate that is true is recorded under "waiverNotNeeded", not as waived. The installation record lists
each waived gate with its category, what was measured and the note ("waivedGates", "waiverNote"); the
manifest (still INSTALLED) and validation.json name the waived gates, and the summary line reads "INSTALLED
with waived gates: ...".

A rollback BEFORE this install (for example the 1.0.0-cc5 and 1.0.0-cc5.1 -> cc4 rollbacks of
2026-09-23, or the rollback of binary A before binary D was installed in a step-down on 2026-09-26) is history
and does not block it. Refused because a rollback happened or was started at or after this install (nothing is
recorded), by ANY profile's or binary's path (cc5.4 [A..E] -> cc5.3, cc5.3 -> cc5.2 or cc5 -> cc4). "At or after the install" means a file time at or after <prefix>-flash-checks.json, or a
UTC stamp (in the record or in the name) at or after the install's startedUtc; for a folder, the
newest file inside counts:
  * any <prefix>-rollback*.json of any profile (current or superseded) from at or after the
    install, or any that cannot be read;
  * any firmware/manifest-at-<prefix>-rollback-*.json of any profile written at or after the
    install (a rollback's copy of manifest.json from just before it restored the previous record);
  * any backups/<prefix>-manual-rollback-* folder (RECOVERY.md manual block 1),
    backups/<prefix>-rollback-* folder (rollback_nanod_cc5.py's work folder), or
    diagnostics/<prefix>-rollback-*.log (its esptool logs) of any profile, from at or after the
    install;
  * any diagnostics/cc5-usb-boot-entry*.json from at or after the install: the knob was put
    back into the ROM bootloader after the install, which only a rollback does (step 3's
    entry precedes the install);
  * backups/nanod-current-partitions.bin from at or after the install (RECOVERY.md section 3,
    read before a rollback to the original firmware);
  * the release manifest neither UNFLASHED nor INSTALLED (a rollback marks it ROLLED_BACK);
  * manifest.json not matching that status: UNFLASHED (first finalize) needs manifest.json to
    be byte-identical to the from-release record package_nanod_cc5.py kept (manifest-cc5.3.json);
    INSTALLED (a finalize re-run) needs it to be byte-identical to the release manifest, so an
    earlier manifest.json next to an INSTALLED release manifest (records restored by a rollback)
    is refused.

Then it writes:
  * diagnostics/<prefix>-installation.json (an older one is kept as *.superseded-*);
  * firmware/manifest-<version>.json -> INSTALLED, copied byte-identically to manifest.json;
  * diagnostics/validation.json updated under the profile's validation key, the previous one kept
    once as validation-before-<prefix>.json;
  * last, the from-release manifest (manifest-1.0.0-cc5.3.json) -> SUPERSEDED (its previous file
    kept as <name>.superseded-<UTC>.json), only while it is INSTALLED and byte-identical to the
    kept from-record. Packaging never changes an installed record, so until this point the
    from-release records stay as installed.
Physical (Stage 11) acceptance stays pending; nothing here claims it.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402

STAMP = re.compile(r"^\d{8}T\d{6}Z$")          # t.utc_stamp() format; compares as text
NAME_STAMP = re.compile(r"\d{8}T\d{6}Z")        # the same stamp inside a file or folder name
CONFIRMED, UNCONFIRMED = "INSTALLED_VERIFIED_RESET", "INSTALLED_VERIFIED_RESET_UNCONFIRMED"
# check_nanod_cc5.py hard gates (its "gates" object); every one must be true. The profile's own list:
# the cc5.2 gates, the artwork2 gates of 1.0.0-cc5.3 and, for 1.0.0-cc5.4, the ALIVE.md 11.9 and
# PRESENTATION_V5.md 15.4 gates (tooling.ALIVE_DEVICE_GATES, PRESENTATION5_DEVICE_GATES).
REQUIRED_GATES = t.CURRENT.gates
# The gates a recorded waiver may accept (--waive-gate with --waiver-note, only with the user's explicit sign-off
# in the hardware window; the targets are never lowered), in two categories:
#  * performance: the measured miss of a timing target (tooling.lcd_timing_problems, led_render_problems,
#    jpeg_decode_problems, led_idle_problems and led_load_summary);
#  * operator timing: the End stop test's push windows were missed (tooling.limit_push_problems and limit_problems
#    on the judged, last attempt) while its runs prove the knob emitted its lim events, +1 at T_end and -1 at 0:00
#    (end_stop_evidence). Narrower: chatter (a count of 2 or more, lims closer than the firmware spacing, lims of
#    one direction closer than one physical push can repeat) and a wrong direction at either end refuse.
PERFORMANCE_GATES = ("lcdTimings", "ledRenderTime", "jpegDecode", "ledFrameRate")
OPERATOR_TIMING_GATES = ("limitPerPush", "limitEvents")
WAIVABLE_GATES = PERFORMANCE_GATES + OPERATOR_TIMING_GATES
WAIVER_CATEGORIES = {**dict.fromkeys(PERFORMANCE_GATES, "performance"),
                     **dict.fromkeys(OPERATOR_TIMING_GATES, "operator timing")}
# The End stop test's timing-only problems (tooling.limit_push_problems, limit_problems), each matched whole: a
# per-push count of 0 or 1 (never 2+), nothing while held (never 2+), a lim outside the windows, an end not seen.
END_STOP_TIMING = (
    re.compile(r"lim per push \[[01](?:, [01])*\] \(each must be exactly 1: none is a missed End stop, two is "
               r"attractor chatter or a short lim_rearm_ms\)"),
    re.compile(r"0 lim while held against the bound \(must be exactly 1\)"),
    re.compile(r"lim outside the push windows: \[\(-?\d+(?:\.\d+)?, -?1\)(?:, \(-?\d+(?:\.\d+)?, -?1\))*\]"),
)
SEEK_END_TIMING = (re.compile(r"no lim [+-]1 seen"),)
# Two lims of one run closer than this are chatter (tooling.limit_problems: the firmware's 150 ms less 50 ms jitter).
LIM_SPACING_MIN_S = t.ALIVE_LIM_GAP_S - 0.05
# Two lims of ONE direction in one run closer than this are not two physical End stop pushes (push, spring back, push
# again) but more than one lim for one push (ruling Q1: attractor chatter or a short lim_rearm_ms). The firmware's own
# re-fire spacing is at most ALIVE_LIM_GAP_S + lim_rearm_ms (150 ms at the top of its tuning range 40..150) = 0.3 s;
# the test's pushes are 1.6 s apart, and the 2026-09-26 run 3's closest same-direction lims 1.747 s.
LIM_SAME_DIRECTION_MIN_S = 0.5
LED_MODE_ALIVE = "alive"                        # diag ledMode of a claimed control (ALIVE.md 11.9 measures it)
# A ledFrameRate waiver covers a timing miss of a RUNNING alive renderer, never a stalled one: the idle and load frame
# rates at least half their targets and the idle show gap at most twice its target (run 3: 60 fps idle and under
# load, a 21 ms idle gap). Anything beyond these is not the measured miss the user signed off.
LED_WAIVER_LIMITS = {"idleLedFpsMin": t.ALIVE_LED_FPS_IDLE_MIN / 2,
                     "idleLedShowGapMsMax": 2 * t.ALIVE_LED_SHOW_GAP_IDLE_MAX_MS,
                     "underLoadLedFpsMin": t.ALIVE_LED_FPS_TRANSFER_MIN / 2}
# For each waivable gate: the check_nanod_cc5.py checks it stands for (by name) and the problems that are its miss
# (a text prefix for a performance miss, a whole-text pattern for an End stop timing miss). Any other failure, a
# missing diag field, an LED transmit failure or chatter included, still refuses.
WAIVER_CHECKS = {
    "lcdTimings": (re.compile(r"LCD (?:opaque|blended) pass \(binary "), ("LCD FRAME RATE (", "LCD LATE REFRESHES ")),
    "ledRenderTime": (re.compile(r"LED render during (?:the untouched stress|stress\+turn): "), ("LED RENDER TOO SLOW: ",)),
    "jpegDecode": (re.compile(r"diag: JPEG covers decoded "), ("SLOW JPEG DECODE: ",)),
    "ledFrameRate": (re.compile(r"LED (?:at idle|under cover transfers): ledFps >= "),
                     ("LED FRAME RATE AT IDLE: ", "LED SHOW GAP AT IDLE: ", "LED FRAME RATE UNDER LOAD: ")),
    "limitPerPush": (re.compile(r"End stop per push \(ruling Q1\): "), END_STOP_TIMING),
    "limitEvents": (re.compile(r"Seek End stop: lim \+1 at T_end and lim -1 at 0:00"), SEEK_END_TIMING),
}
PLACEHOLDER = re.compile(r"<[^<>]*>")           # a runbook placeholder such as "<text>" left in place
# check_nanod_cc5_lease.py artwork2 cases (its "artwork2" object); every one must be true.
REQUIRED_LEASE_CASES = ("mediaOnlyDoesNotRenew", "framesDuringMediaTransfers")
PARTITION_READ = ("BACKUPS", "nanod-current-partitions.bin",
                  "RECOVERY.md section 3 read the partition table for a rollback")
# The history of the release this one upgrades from, recorded when it is superseded here.
FROM_RELEASE_HISTORY = {
    t.PROFILES["cc5.2"].version: (
        "Installed app-only on 2026-09-23 (image SHA-256 45c629bb..., full 4 MB verified against "
        "backups/nanod-cc5.2-expected-full.bin, SHA-256 19cd67b2...) and finalized "
        "(diagnostics/cc5-installation.json): stress untouched and while turning, no reboot, task liveness "
        "at every checkpoint and a 20-minute unattended soak passed. Superseded when the artwork2 release "
        "was installed and finalized; the installed record is kept byte-identical as "
        "firmware/manifest-cc5.2.json (the cc5.3 -> cc5.2 rollback restores manifest.json from it). Its "
        "install, rollback and finalize evidence (diagnostics/cc5-*.json) are history and unchanged."),
    t.PROFILES["cc5.3"].version: (
        "Installed app-only on 2026-09-24 (image SHA-256 f1cd05a2..., full 4 MB verified against "
        "backups/nanod-cc5.3-expected-full.bin, SHA-256 86759e50...) and finalized "
        "(diagnostics/cc5.3-installation.json): presentation 4 with artwork2 (240 px JPEG covers, app icons, "
        "prefetch, unpaced transport), stress untouched and while turning, no reboot, task liveness at every "
        "checkpoint and a 20-minute unattended soak passed. Superseded when the Warm-alive release "
        "(presentation 5 with desktop v7) was installed and finalized; the installed record is kept "
        "byte-identical as firmware/manifest-cc5.3.json (the cc5.4 -> cc5.3 rollback restores manifest.json "
        "from it). Its install and finalize evidence (diagnostics/cc5.3-*.json) are history and unchanged."),
}


def supersede_from_release(p):
    """The upgraded-from release manifest becomes SUPERSEDED once this release is recorded INSTALLED.

    Only while it is INSTALLED and byte-identical to the kept from-record (manifest-cc5.2.json):
    anything else is left as it is and named in the returned line. Its previous file is kept as
    <name>.superseded-<UTC>.json, never overwritten. Runs after every record of this release is
    written, so a failure here never leaves this release unrecorded.
    """
    path = t.release_manifest(p.from_version)
    if not path.is_file():
        return f"{path.name} not present; nothing to supersede"
    record = t.load_json(path)
    status = record.get("installationStatus")
    if status == "SUPERSEDED":
        return f"{path.name} already SUPERSEDED"
    if status != "INSTALLED" or not p.from_record.is_file() or t.sha256_file(path) != t.sha256_file(p.from_record):
        return f"{path.name} left {status} (not the INSTALLED record kept as {p.from_record.name})"
    kept_sha = t.sha256_file(p.from_record)
    kept = t.archive_existing(path)
    record.update(installationStatus="SUPERSEDED", statusBeforeSupersede=status, supersededBy=p.version,
                  supersededUtc=t.utc_stamp(),
                  history=FROM_RELEASE_HISTORY.get(p.from_version, f"Installed; superseded when {p.version} was "
                                                                   "installed and finalized."),
                  hardwareStatus=(f"Superseded by {p.version} (installed and finalized); kept as history. "
                                  f"Installed record: {p.from_record.name}."),
                  installedRecord=p.from_record.name, installedRecordSha256=kept_sha)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(record, indent=2) + "\n")
    return f"{path.name}: INSTALLED -> SUPERSEDED (previous file kept as {kept.name})"


def release_texts(p, waived=()):
    """The human-readable status lines of this release's records (installation report, manifest and
    validation.json): what was verified and which hands-on acceptance is still pending. `waived`: the gates
    accepted by a recorded waiver, named in every line so none reads as a clean pass (empty: the lines as
    before the waiver existed)."""
    jpeg = "JPEG decode within 150 ms" if "jpegDecode" not in waived else "JPEG decode without error"
    # With jpegDecode waived its diag check (jpegDecodeMsMax <= 200 ms) failed; only the other diag checks passed.
    diag = "diag and lease checks pass" if "jpegDecode" not in waived else "lease checks and every other diag check pass"
    common = ("ten saved profiles identical; four controls, v2 frames, v1 and artwork2 media, unpaced stress "
              f"(untouched and while turning), no reboot, tasks alive at every checkpoint, {jpeg}, a 20-minute "
              f"unattended soak with media traffic, {diag}")
    performance = [g for g in waived if WAIVER_CATEGORIES.get(g) != "operator timing"]
    operator = [g for g in waived if WAIVER_CATEGORIES.get(g) == "operator timing"]
    parts = ([f"{', '.join(performance)} (a known issue the user signed off; the targets are unchanged)"]
             if performance else [])
    if operator:
        parts.append(f"{', '.join(operator)} (operator timing the user signed off: the End stop test's push windows "
                     "were missed while the knob's lim +1 at T_end and lim -1 at 0:00 were recorded)")
    known = "waived gates " + " and ".join(parts)
    # The exception closes the whole list: a waived gate may be of any release's gates (jpegDecode is artwork2's).
    if getattr(p, "alive", False):
        return {
            "physical": ("Pending hands-on acceptance (Warm alive LEDs: the six glow looks, breathing idle, limit "
                         "flares, press and claim feedback, the floating knob mirror, text during the volume "
                         "reveals, the offline native line)"),
            "hardware": (f"Installed {p.version} over {p.from_version}; presentation {p.presentation} with the "
                         "alive LED renderer (drive min(150, ledMaxBrightness)), the ready/hold presentation "
                         f"protocol and artwork2 unchanged; {common}; "
                         + (f"every hard gate passes (the alive and presentation 5 gates included) except the {known}"
                            if waived else "the alive and presentation 5 gates pass")
                         + ". Hands-on acceptance pending."),
            "validation": ("Protocol, alive LEDs, artwork2 and preservation verified"
                           + (f" with the {known}" if waived else "") + "; hands-on acceptance pending"),
            "note": (f"{p.version} protocol/alive/presentation5/artwork2/stress+turn/soak/liveness/lease/"
                     "preservation checks pass" + (f" with the {known}" if waived else "")
                     + "; hands-on acceptance pending."),
        }
    return {
        "physical": ("Pending Stage 11 hands-on acceptance (240 px covers, app icons, instant prefetched covers, "
                     "targeted-colour LEDs, host-lost notice)"),
        "hardware": (f"Installed {p.version} over {p.from_version}; presentation {p.presentation} with artwork2 "
                     f"(240 px JPEG covers, app icons, prefetch, unpaced transport) and the v1 art path unchanged; "
                     f"{common}" + (f"; every hard gate passes except the {known}" if waived else "")
                     + ". Stage 11 physical acceptance pending."),
        "validation": ("Protocol, artwork2 and preservation verified" + (f" with the {known}" if waived else "")
                       + "; Stage 11 hands-on pending"),
        "note": (f"{p.version} protocol/artwork2/stress+turn/soak/liveness/lease/preservation checks pass"
                 + (f" with the {known}" if waived else "") + "; Stage 11 physical acceptance pending."),
    }


def section_of(checks, name):
    """sections.<name> of the device checks, or {} when the evidence lacks it."""
    sections = checks.get("sections") if isinstance(checks.get("sections"), dict) else {}
    return sections.get(name) if isinstance(sections.get(name), dict) else {}


def miss_lines(gate, detail):
    """A failed check's problem texts: its detail list, or for ledFrameRate the "problems" of the LED load
    check's summary (the one waivable check whose detail is an object); None for anything else."""
    if isinstance(detail, list):
        return detail
    if gate == "ledFrameRate" and isinstance(detail, dict) and isinstance(detail.get("problems"), list):
        return detail["problems"]
    return None


def is_miss(line, allowed):
    """`line` is one of the `allowed` misses: a text prefix (performance) or a whole-text pattern (End stop timing)."""
    return isinstance(line, str) and any(line.startswith(a) if isinstance(a, str) else a.fullmatch(line) is not None
                                         for a in allowed)


def texts_of(value):
    """A recorded problem list as a list (None or absent: none; anything else is one entry to judge)."""
    return value if isinstance(value, list) else [] if value is None else [value]


def lim_pairs(lims):
    """[(time, dir)] of a run's recorded lims ([time, +1|-1] pairs), or None when they are not such pairs."""
    if not isinstance(lims, list):
        return None
    pairs = []
    for item in lims:
        if not (isinstance(item, (list, tuple)) and len(item) == 2 and type(item[0]) in (int, float)
                and type(item[1]) is int and item[1] in (-1, 1)):
            return None
        pairs.append((item[0], item[1]))
    return pairs


def end_stop_evidence(checks):
    """What the End stop runs (sections.handsOn.endStop.runs) prove for an operator-timing waiver.

    Returns ({"runs": [{attempt, perPush, held, stray, reachedZero, limAtZero, lims}], "proof": {lim +1 / -1 counts,
    the lim +1 of the push phase, the runs with lim -1 at 0:00, the smallest spacing of two lims and of two lims of
    one direction within a run, the allowed and the firmware spacing}}, reasons not proven). Proven means:
      * the direction at each end: a lim +1 during the push phase, while the control sits at T_end (perPush, held
        or a +1 in stray: every lim up to push_end), and a lim -1 after the knob reported 0:00 (reachedZero and
        limAtZero: check_nanod_cc5.py waits for p == 0, then for lim -1), each in at least one run. A lim +1 only
        after the push phase or a lim -1 only before 0:00 was reached proves neither end (a firmware sending the
        wrong direction at T_end would otherwise read as late pushes); a lim -1 inside a push window is not refused
        (run 3's attempt 3: the operator was already at 0:00);
      * no chatter: no run with a per-push or held count of 2 or more, two lims closer than LIM_SPACING_MIN_S
        (tooling.limit_problems) or two lims of one direction closer than LIM_SAME_DIRECTION_MIN_S (more than one
        lim for one push outside the windows): attractor chatter or a short lim_rearm_ms, a firmware fault;
      * every run's own problems End stop timing only."""
    end_stop = section_of(checks, "handsOn").get("endStop")
    runs = end_stop.get("runs") if isinstance(end_stop, dict) else None
    if not isinstance(runs, list) or not runs or not all(isinstance(run, dict) for run in runs):
        return {"runs": [], "proof": None}, ["no End stop runs recorded (sections.handsOn.endStop.runs), so nothing "
                                             "proves the knob emitted its lim events"]
    reasons, recorded, every, spacings, same_spacings = [], [], [], [], []
    plus_at_end = runs_minus_at_zero = 0
    for number, run in enumerate(runs, 1):
        attempt = run.get("attempt", number)
        lims, stray = lim_pairs(run.get("lims")), lim_pairs(run.get("stray"))
        per_push, held = run.get("perPush"), run.get("held")
        recorded.append({"attempt": attempt, "perPush": per_push, "held": held, "stray": run.get("stray"),
                         "reachedZero": run.get("reachedZero"), "limAtZero": run.get("limAtZero"),
                         "lims": run.get("lims")})
        if lims is None:
            reasons.append(f"End stop attempt {attempt}: lims {run.get('lims')!r} are not [time, +1|-1] pairs")
            lims = []
        if stray is None:
            reasons.append(f"End stop attempt {attempt}: stray {run.get('stray')!r} are not [time, +1|-1] pairs")
            stray = []
        every += lims
        times = sorted(ts for ts, _ in lims)
        spacings += [b - a for a, b in zip(times, times[1:])]
        counts_known = (isinstance(per_push, list) and per_push and all(type(c) is int and c >= 0 for c in per_push)
                        and type(held) is int and held >= 0)
        if not counts_known:
            reasons.append(f"End stop attempt {attempt}: per-push and held counts not recorded ({per_push!r}, {held!r})")
        elif any(c >= 2 for c in per_push) or held >= 2:
            reasons.append(f"End stop attempt {attempt}: perPush {per_push}, held {held} (two lims for one push is "
                           "attractor chatter or a short lim_rearm_ms: a firmware fault, never waived)")
        else:   # the lim +1 the push phase saw at T_end: in a push window, in the hold window, or outside them
            plus_at_end += sum(per_push) + held + sum(1 for _, d in stray if d == 1)
        if run.get("reachedZero") is True and run.get("limAtZero") is True:
            runs_minus_at_zero += 1
        reasons += [f"End stop attempt {attempt}: {problem} (chatter: a firmware fault, never waived)"
                    for problem in t.limit_problems(lims, need=())]
        for direction in (1, -1):
            same = sorted(ts for ts, d in lims if d == direction)
            gaps = [b - a for a, b in zip(same, same[1:])]
            same_spacings += gaps
            close = [round(g, 3) for g in gaps if g < LIM_SAME_DIRECTION_MIN_S]
            if close:
                reasons.append(f"End stop attempt {attempt}: lim {direction:+d} repeated within "
                               f"{LIM_SAME_DIRECTION_MIN_S:g} s (gaps {close[:5]} s), closer than one physical push "
                               "can repeat: more than one lim for one push is attractor chatter or a short "
                               "lim_rearm_ms, a firmware fault, never waived")
        other = ([p for p in texts_of(run.get("problems")) if not is_miss(p, END_STOP_TIMING)]
                 + [p for p in texts_of(run.get("seekEnds")) if not is_miss(p, SEEK_END_TIMING)])
        if other:
            reasons.append(f"End stop attempt {attempt} recorded {other} (not only End stop timing)")
    plus, minus = sum(1 for _, d in every if d == 1), sum(1 for _, d in every if d == -1)
    if not plus:
        reasons.append("no lim +1 in any End stop run: the knob never reported the End stop at T_end, so the miss "
                       "is not the operator's timing alone")
    elif not plus_at_end:
        reasons.append("no lim +1 in the push phase of any End stop run (perPush, held and stray all without a +1): "
                       "the knob's lim +1 came only after it, away from T_end, so the End stop at T_end is not "
                       "proven (a wrong direction at T_end is a firmware fault, never waived)")
    if not minus:
        reasons.append("no lim -1 in any End stop run: the knob never reported the End stop at 0:00, so the miss "
                       "is not the operator's timing alone")
    elif not runs_minus_at_zero:
        reasons.append("no End stop run saw lim -1 after the knob reported 0:00 (reachedZero and limAtZero), so the "
                       "End stop at 0:00 is not proven (a wrong direction at 0:00 is a firmware fault, never waived)")
    proof = {"limPlus": plus, "limMinus": minus, "limPlusInPushPhase": plus_at_end,
             "runsWithLimMinusAtZero": runs_minus_at_zero,
             "minSpacingS": round(min(spacings), 3) if spacings else None,
             "minSpacingAllowedS": round(LIM_SPACING_MIN_S, 3), "firmwareSpacingS": t.ALIVE_LIM_GAP_S,
             "minSameDirectionSpacingS": round(min(same_spacings), 3) if same_spacings else None,
             "minSameDirectionAllowedS": LIM_SAME_DIRECTION_MIN_S}
    return {"runs": recorded, "proof": proof}, reasons


def stress_lims_summary(checks):
    """sections.stressTurn.lims (the other half of limitEvents) as {"events": count, "problems": [...]}."""
    lims = section_of(checks, "stressTurn").get("lims")
    lims = lims if isinstance(lims, dict) else {}
    events = lims.get("events")
    return {"events": len(events) if isinstance(events, list) else None, "problems": lims.get("problems")}


def waiver_coverage(checks, waived):
    """Whether the waiver of the false gates `waived` covers every failure of the device checks.

    Returns ({gate: its failed checks [{"check", "detail"}]}, reasons not covered). Covered means: every
    failed check (the "failures" names and the failed entries of "checks") is a check of a waived gate
    (WAIVER_CHECKS) whose detail lists only that gate's miss, and each waived gate has at least one such
    check. Anything else (another check, a missing diag field, a failure without its check) is a reason, so
    the waiver never accepts more than the measured performance misses and the End stop timing misses.
    What no check reports is required too: lcdTimings is also false when the LCD pass's cover upload did not
    commit (sections.lcdAnimation.coverCommitted must be true); ledFrameRate needs the idle measurement of the
    alive renderer, every LED load cover committed and a running renderer (LED_WAIVER_LIMITS); an operator-timing
    gate needs the End stop runs to prove the knob emitted its lim events, +1 at T_end and -1 at 0:00, without
    chatter (end_stop_evidence), and limitEvents the stress+turn lims passed."""
    entries = [c for c in checks.get("checks") or [] if isinstance(c, dict) and c.get("passed") is not True]
    listed = checks.get("failures") if isinstance(checks.get("failures"), list) else [checks.get("failures")]
    names = list(dict.fromkeys([n for n in listed if n] + [c.get("check") for c in entries]))
    own, reasons = {gate: [] for gate in waived}, []
    for name in names:
        gate = next((g for g in waived if isinstance(name, str) and WAIVER_CHECKS[g][0].match(name)), None)
        failed = [c for c in entries if c.get("check") == name]
        if gate is None:
            reasons.append(f"{name} (not a check of a waived gate)")
        elif not failed:
            reasons.append(f"{name} (in failures without its failed check)")
        for entry in failed if gate else ():
            detail = entry.get("detail")
            lines = miss_lines(gate, detail)
            if lines and all(is_miss(line, WAIVER_CHECKS[gate][1]) for line in lines):
                own[gate].append({"check": name, "detail": detail})
            elif gate in OPERATOR_TIMING_GATES:
                reasons.append(f"{name} failed with {detail} (not only the End stop timing miss {gate} may waive: "
                               "chatter or any other problem is a firmware fault)")
            else:
                reasons.append(f"{name} failed with {detail} (not only the measured {gate} miss)")
    reasons += [f"{gate} is false without a failed {gate} check (a waiver covers only a measured miss)"
                for gate, failed in own.items() if not failed]
    committed = section_of(checks, "lcdAnimation").get("coverCommitted")
    if "lcdTimings" in own and committed is not True:
        reasons.append(f"lcdTimings is false with the LCD pass cover not committed (sections.lcdAnimation."
                       f"coverCommitted {committed}: a media failure, not the measured miss)")
    if "ledFrameRate" in own:
        idle, load = section_of(checks, "ledIdle"), section_of(checks, "ledUnderLoad")
        diag = idle.get("diag") if isinstance(idle.get("diag"), dict) else {}
        mode = diag.get("ledMode")
        if mode != LED_MODE_ALIVE:
            reasons.append(f"ledFrameRate is false with the idle LED measurement not of the alive renderer "
                           f"(sections.ledIdle.diag.ledMode {mode!r}, not {LED_MODE_ALIVE!r}): not the measured miss")
        done, transfers = load.get("committed"), load.get("transfers")
        if not (type(transfers) is int and transfers > 0 and done == transfers):
            reasons.append(f"ledFrameRate is false with the LED load pass's covers not all committed (sections."
                           f"ledUnderLoad committed {done} of {transfers}: a media failure, not the measured miss)")
        fps, gap, low = t.diag_int(diag, "ledFps"), t.diag_int(diag, "ledShowGapMsMax"), t.diag_int(load, "ledFpsMin")
        limits = LED_WAIVER_LIMITS
        if not (fps is not None and fps >= limits["idleLedFpsMin"] and gap is not None
                and gap <= limits["idleLedShowGapMsMax"] and low is not None and low >= limits["underLoadLedFpsMin"]):
            reasons.append(f"ledFrameRate is false with the LED renderer far off its targets (idle ledFps {fps!r}, "
                           f"ledShowGapMsMax {gap!r} ms, under load ledFpsMin {low!r}; a waiver covers at least "
                           f"{limits['idleLedFpsMin']:g} fps at idle, {limits['underLoadLedFpsMin']:g} under load and "
                           f"a gap of at most {limits['idleLedShowGapMsMax']:g} ms): a stalled renderer, not the "
                           "measured miss")
    if any(gate in own for gate in OPERATOR_TIMING_GATES):
        reasons += end_stop_evidence(checks)[1]
    stress = stress_lims_summary(checks)
    if "limitEvents" in own and not (stress["events"] and stress["problems"] == []):
        reasons.append(f"limitEvents is false with the stress+turn lims not passed (sections.stressTurn.lims: "
                       f"{stress['events']} events, problems {stress['problems']}): only the End stop test's timing "
                       "can be waived")
    return own, reasons


def waiver_record(gate, checks, failed, note):
    """One "waivedGates" entry: the gate, its category (performance or operator timing), a compact summary of
    what the device checks measured (a field the evidence lacks is None) with the targets, which stay as they
    are, and the waiver note."""
    if gate == "lcdTimings":
        lcd = section_of(checks, "lcdAnimation")
        binary = lcd.get("binary") or section_of(checks, "diag").get("binary")
        measured = {"binary": binary, "targets": lcd.get("targets") or t.LCD_FPS_TARGETS.get(binary),
                    "lcdFpsAnimMin": {kind: (lcd.get(kind) if isinstance(lcd.get(kind), dict) else {}).get("lcdFpsAnimMin")
                                      for kind in ("opaque", "blended")},
                    "problems": lcd.get("problems"), "coverCommitted": lcd.get("coverCommitted")}
    elif gate == "ledRenderTime":
        measured = {"ledRenderUsMax": {name: section_of(checks, name).get("ledRenderUsMax")
                                       for name in ("stress", "stressTurn")},
                    "maxUs": t.ALIVE_LED_RENDER_US_MAX}
    elif gate == "ledFrameRate":
        idle, load = section_of(checks, "ledIdle"), section_of(checks, "ledUnderLoad")
        diag = idle.get("diag") if isinstance(idle.get("diag"), dict) else {}
        measured = {"idle": {k: diag.get(k) for k in ("ledFps", "ledShowGapMsMax", "ledMode")},
                    "underLoad": {k: load.get(k) for k in ("ledFpsMin", "ledShowGapMsMax", "committed", "transfers")},
                    "targets": {"idleLedFpsMin": t.ALIVE_LED_FPS_IDLE_MIN,
                                "idleLedShowGapMsMax": t.ALIVE_LED_SHOW_GAP_IDLE_MAX_MS,
                                "underLoadLedFpsMin": t.ALIVE_LED_FPS_TRANSFER_MIN},
                    "waiverLimits": dict(LED_WAIVER_LIMITS)}
    elif gate in OPERATOR_TIMING_GATES:
        measured = end_stop_evidence(checks)[0]
        if gate == "limitEvents":
            measured["stressTurnLims"] = stress_lims_summary(checks)
    else:  # jpegDecode
        media = section_of(checks, "diag").get("media")
        measured = {"jpegDecodeMsMax": media.get("jpegDecodeMsMax") if isinstance(media, dict) else None,
                    "maxMs": t.JPEG_DECODE_MAX_MS}
    return {"gate": gate, "category": WAIVER_CATEGORIES[gate], "measured": {**measured, "failedChecks": failed},
            "note": note}


def require(condition, message):
    if not condition:
        raise SystemExit(f"STOP: {message}. Nothing was recorded.")


def read_evidence(path, what):
    """(parsed JSON object, SHA-256 of the exact bytes parsed)."""
    path = Path(path)
    require(path.is_file(), f"{what} ({path.name}) is missing")
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        data = None
    require(isinstance(data, dict), f"{path.name} is not a readable JSON object")
    return data, t.sha256_bytes(raw)


def stamp_of(record, *keys):
    """The first valid UTC stamp among `keys`, or None."""
    for key in keys:
        value = record.get(key) if isinstance(record, dict) else None
        if isinstance(value, str) and STAMP.match(value):
            return value
    return None


def written_after(path, record, flash_path, flash):
    """`path` was produced after the install: newer file time, and (when both runs recorded
    stamps) started no earlier than the install finished."""
    if Path(path).stat().st_mtime <= Path(flash_path).stat().st_mtime:
        return False
    started, finished = stamp_of(record, "startedUtc"), stamp_of(flash, "finishedUtc", "startedUtc")
    return started is None or finished is None or started >= finished


def newest_time(path):
    """File time of `path`; for a folder, the newest of the folder and everything inside it."""
    path = Path(path)
    times = [path.stat().st_mtime]
    if path.is_dir():
        times += [p.stat().st_mtime for p in path.rglob("*")]
    return max(times)


def at_or_after_install(path, flash_time, install_started, *stamps):
    """`path` (by file time) or any of its UTC stamps (given, or in its name) is from the install on."""
    stamps = [s for s in (*stamps, *NAME_STAMP.findall(Path(path).name)) if s]
    return newest_time(path) >= flash_time or bool(install_started and any(s >= install_started for s in stamps))


def rollback_traces():
    """(folder attribute, glob, meaning) for every trace any profile's rollback path leaves
    besides its record, plus the RECOVERY.md section 3 partition read."""
    traces = []
    for profile in t.all_profiles():
        traces += [trace for trace in profile.rollback_trace_patterns() if trace not in traces]
    return traces + [PARTITION_READ]


def rollbacks_since_install(flash_path, flash):
    """Reasons why a rollback happened, or was started, at or after the install (empty: none was)."""
    flash_time = Path(flash_path).stat().st_mtime
    install_started = stamp_of(flash, "startedUtc", "finishedUtc")
    reasons = []
    for profile in t.all_profiles():
        folder, stem = profile.rollback_report.parent, profile.rollback_report.stem
        for path in sorted(folder.glob(f"{stem}*.json")):
            try:
                record = t.load_json(path)
            except (OSError, ValueError):
                reasons.append(f"{path.name} cannot be read, so it may record a rollback after the install")
                continue
            if at_or_after_install(path, flash_time, install_started,
                                   stamp_of(record, "startedUtc"), stamp_of(record, "finishedUtc")):
                outcome = record.get("outcome") if isinstance(record, dict) else None
                reasons.append(f"{path.name} records a {profile.label} -> {profile.from_tag} rollback ({outcome}) "
                               "after the install")
    for where, pattern, meaning in rollback_traces():
        base = getattr(t, where)
        for path in sorted(base.glob(pattern)):
            if at_or_after_install(path, flash_time, install_started):
                reasons.append(f"{base.name}/{path.name} shows {meaning} after the install")
    for path in sorted(t.BOOT_ENTRY.parent.glob(f"{t.BOOT_ENTRY.stem}*.json")):
        try:
            started = stamp_of(t.load_json(path), "startedUtc")
        except (OSError, ValueError):
            started = None   # unreadable: its file time and name still count
        if at_or_after_install(path, flash_time, install_started, started):
            reasons.append(f"{t.BOOT_ENTRY.parent.name}/{path.name} records a ROM bootloader entry after the "
                           "install, which only a rollback makes")
    return reasons


def desktop_record(p):
    """Installed companion vs the release's desktop bundle and its rollback bundle (hashes only)."""
    installed = t.DIAGNOSTICS / "desktop-installation.json"
    record = {"installationRecord": installed.name if installed.is_file() else None,
              "bundle": p.desktop_bundle, "rollbackBundle": p.desktop_rollback_bundle}
    if installed.is_file():
        record["installedSha256"] = (t.load_json(installed).get("sha256") or "").lower()
    for key, name in (("bundleSha256", p.desktop_bundle), ("rollbackBundleSha256", p.desktop_rollback_bundle)):
        exe = t.desktop_bundle_exe(name)       # DeskDial\DeskDial.exe (v7 on) or NanoDControlCenter\... (v2-v6)
        if exe is not None:
            record[key] = t.sha256_file(exe)
            record[key.replace("Sha256", "Exe")] = f"{name}/{exe.parent.name}/{exe.name}"
    if "bundleSha256" in record:
        record["installedIsBundle"] = record.get("installedSha256") == record["bundleSha256"]
    return record


def ladder_record(p):
    """For a ladder release: what the records say about each binary (manifest status, and whether its
    flash record shows a write), so the installation record names the binary shipped and the others."""
    if not p.binary:
        return None
    ladder = {}
    for variant in p.variants():
        try:
            status = t.load_json(variant.manifest).get("installationStatus") if variant.manifest.is_file() else None
        except (OSError, ValueError):
            status = "unreadable"
        ladder[variant.binary] = {"manifest": variant.manifest.name, "manifestStatus": status,
                                  "writeEvidence": t.binary_write_evidence(variant), "recorded": variant is p}
    return ladder


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--companion-tests", type=int, help="passing companion unit tests in the final suite run")
    parser.add_argument("--light-assertions", type=int, help="light_tests.py assertions in the final gate run")
    parser.add_argument("--accept-unconfirmed-reset", action="store_true",
                        help="accept install exit 5 (INSTALLED_VERIFIED_RESET_UNCONFIRMED) after the printed reset "
                             "command was run once; the after-inventory and passed checks prove the reboot")
    choices = t.binary_choices()
    if choices:
        parser.add_argument("--binary", choices=choices, default=choices[0],
                            help=f"the PRESENTATION_V5 12.6 binary that passed the hardware window (default "
                                 f"{choices[0]})")
    parser.add_argument("--waive-gate", action="append", metavar="NAME",
                        help=f"accept this failed gate as a known issue the user signed off in the window (repeatable; "
                             f"only the performance gates {', '.join(PERFORMANCE_GATES)} and the End stop "
                             f"operator-timing gates {', '.join(OPERATOR_TIMING_GATES)}; needs --waiver-note; the "
                             "targets are not lowered and the records name every waived gate)")
    parser.add_argument("--waiver-note", metavar="TEXT",
                        help="the user's sign-off, recorded with every waived gate (required with --waive-gate)")
    args = parser.parse_args(argv)
    t.console_utf8()
    p = t.CURRENT.binary_profile(getattr(args, "binary", None))
    # A recorded waiver: only the whitelisted performance and operator-timing gates of this profile, only with a note.
    waive = list(dict.fromkeys(args.waive_gate or ()))       # a name given twice counts once, in the order given
    waiver_note = (args.waiver_note or "").strip()
    refused = [name for name in waive if name not in WAIVABLE_GATES]
    require(not refused, f"--waive-gate {', '.join(refused)} refused: only the performance gates "
                         f"{', '.join(PERFORMANCE_GATES)} and the End stop operator-timing gates "
                         f"{', '.join(OPERATOR_TIMING_GATES)} can be waived (their targets are not lowered); every "
                         "other gate must pass")
    require(all(name in REQUIRED_GATES for name in waive),
            f"--waive-gate {', '.join(n for n in waive if n not in REQUIRED_GATES)} is not a hard gate of {p.version}")
    require(not waive or (waiver_note and not PLACEHOLDER.fullmatch(waiver_note)),
            "--waive-gate needs --waiver-note TEXT (not empty, not a placeholder): the user's sign-off of the known "
            "issue, recorded with every waived gate")
    require(args.waiver_note is None or waive, "--waiver-note applies only with --waive-gate")
    backup, backup_sha = read_evidence(p.backup_report, "backup evidence")
    prep, prep_sha = read_evidence(p.preparation, "preparation evidence")
    flash, flash_sha = read_evidence(p.flash_checks, "flash evidence")
    checks, checks_sha = read_evidence(p.device_checks, "post-flash device checks")
    lease, lease_sha = read_evidence(p.lease_checks, "post-flash lease checks")
    require(backup.get("passed") is True and backup.get("sha256") == prep.get("beforeSha256"),
            "backup evidence does not match the preparation")
    require(prep.get("firmwareVersion") == p.version and prep.get("fromVersion") == p.from_version,
            f"{p.preparation.name} does not prepare {p.from_version} -> {p.version}")
    # The image the expected image followed from and the install verified the device against before writing:
    # the pre-install backup, or after a step-down the step-down base (its record names the same locked backup).
    base_kind = prep.get("baseKind") or t.PRE_INSTALL_ROLE
    base_file = prep.get("baseFile") or p.before_full.name
    step_down = step_down_sha = None
    require(base_kind in (t.PRE_INSTALL_ROLE, t.STEP_DOWN_ROLE), f"{p.preparation.name} names an unknown base ({base_kind})")
    if base_kind == t.PRE_INSTALL_ROLE:
        require(base_file == p.before_full.name, f"{p.preparation.name} names the base {base_file}, not {p.before_full.name}")
    else:
        step_down, step_down_sha = read_evidence(p.step_down_report, "step-down base evidence")
        require(step_down.get("passed") is True and step_down.get("role") == t.STEP_DOWN_ROLE
                and step_down.get("sha256") == prep.get("baseSha256")
                and Path(str(step_down.get("file") or "")).name == base_file
                and step_down.get("lockedBackupSha256") == backup.get("sha256"),
                f"{p.step_down_report.name} does not record the step-down base {p.preparation.name} was prepared "
                f"from ({base_file}) against the backup {p.backup_report.name} records")

    # A rollback made or started at or after the install means this release is not (or may no
    # longer be) the installed firmware, even when the post-flash checks from before it passed.
    rollbacks = rollbacks_since_install(p.flash_checks, flash)
    require(not rollbacks, "a rollback was made or started after the install, so this install's evidence no "
                           "longer shows what app0 holds (" + "; ".join(rollbacks) + "). Decide with the user; "
                           f"{p.tag} cannot be recorded from this evidence")

    outcome = flash.get("outcome")
    confirmed = outcome == CONFIRMED and flash.get("reset") is True
    unconfirmed = outcome == UNCONFIRMED and flash.get("resetAttempted") is True
    require(confirmed or (unconfirmed and args.accept_unconfirmed_reset),
            f"{p.flash_checks.name} outcome is {outcome}, not {CONFIRMED}"
            + (" (after install exit 5, run the printed reset command once, then pass "
               "--accept-unconfirmed-reset)" if unconfirmed else ""))
    require(flash.get("identityVerified") is True and flash.get("preWriteVerified") is True
            and flash.get("writeAttempted") is True and flash.get("flashWritten") is True
            and flash.get("postWriteVerified") is True and not flash.get("restoreAttempted"),
            "flash evidence is not a verified install")
    require(flash.get("candidateSha256") == prep.get("candidateSha256"), "installed image differs from the prepared one")
    require((flash.get("baseFile") or p.before_full.name) == base_file,
            f"{p.flash_checks.name} verified the device against {flash.get('baseFile')}, not the base "
            f"{p.preparation.name} prepared from ({base_file})")

    # Post-flash evidence: produced after the install, passed, and showing this release with its presentation.
    for path, record in ((p.device_checks, checks), (p.lease_checks, lease)):
        require(written_after(path, record, p.flash_checks, flash),
                f"{path.name} is not newer than {p.flash_checks.name}; run it after the install")
    gates = checks.get("gates") if isinstance(checks.get("gates"), dict) else {}
    waived = [name for name in waive if gates.get(name) is not True]       # the measured misses the waiver accepts
    not_needed = [name for name in waive if gates.get(name) is True]      # waived by name, but the gate passed
    waived_checks, uncovered = waiver_coverage(checks, waived) if waived else ({}, [])
    if waived:
        # The run failed; only the waived gates' own checks, failed for their measured miss alone, may be why.
        require(checks.get("portClosed") is True and not uncovered,
                f"{p.device_checks.name} did not pass, and the waiver of {waived} does not cover: "
                + ("; ".join(uncovered) if uncovered else "the port was not closed"))
    else:
        require(checks.get("passed") is True and checks.get("portClosed") is True and not checks.get("failures"),
                f"{p.device_checks.name} did not pass")
    require((checks.get("capabilities") or {}).get("presentation") == p.presentation,
            f"{p.device_checks.name} does not show presentation {p.presentation}")
    firmware_check = next((c for c in checks.get("checks") or [] if isinstance(c, dict)
                           and c.get("check") == f"inventory: firmware {p.version}"), None)
    require(firmware_check is not None and firmware_check.get("passed") is True
            and firmware_check.get("detail") == p.version,
            f"{p.device_checks.name} does not show firmware {p.version}")
    if p.binary:
        reported = ((checks.get("sections") or {}).get("diag") or {}).get("binary")
        require(reported == p.binary,
                f"{p.device_checks.name} shows binary {reported} on the knob (diag lcdDma / lcdPeriodMs / artAsync), "
                f"not binary {p.binary}" + (f"; if binary {reported} was installed, run with --binary {reported}"
                                            if reported in t.PIPELINE_BINARIES else ""))
    require(prep.get("binary") == p.binary if p.binary else True,
            f"{p.preparation.name} does not prepare binary {p.binary}")
    missing = [name for name in REQUIRED_GATES if gates.get(name) is not True and name not in waived]
    require(not missing, f"{p.device_checks.name} does not pass the {p.version} hard gates {missing} "
                         "(stress+turn needs the knob turned continuously when prompted; any reboot or "
                         "re-enumeration, stalled task, LED transmit failure or forced release fails, the "
                         "unattended soak must complete at least 20 minutes, and every artwork2 check must pass)")
    require(lease.get("passed") is True and not lease.get("failures"), f"{p.lease_checks.name} did not pass")
    lease_cases = lease.get("artwork2") if isinstance(lease.get("artwork2"), dict) else {}
    require(all(lease_cases.get(name) is True for name in REQUIRED_LEASE_CASES),
            f"{p.lease_checks.name} does not pass the artwork2 lease cases {list(REQUIRED_LEASE_CASES)}")

    before_name = Path(prep.get("beforeInventory") or "").name
    after_name = Path(checks.get("inventory") or "").name
    require(before_name and after_name, "the before- or after-inventory is not named in the evidence")
    before, before_sha = read_evidence(t.BACKUPS / before_name, "before-inventory")
    after, after_sha = read_evidence(t.BACKUPS / after_name, "after-inventory")
    require((t.BACKUPS / after_name).stat().st_mtime > p.flash_checks.stat().st_mtime,
            f"{after_name} is not newer than {p.flash_checks.name}")
    # DeviceBridge writes "profiles" as one object mapping each name to its profile.
    profiles = after.get("profiles")
    require(isinstance(profiles, dict) and len(profiles) == 10 and before.get("profiles") == profiles,
            "saved profiles changed (the after-inventory must hold the same ten named profiles, name -> "
            "profile, as the before-inventory)")
    before_settings, after_settings = before.get("settings") or {}, after.get("settings") or {}
    changed = sorted(k for k in set(before_settings) | set(after_settings)
                     if before_settings.get(k) != after_settings.get(k))
    require(changed == ["firmwareVersion"] and after_settings.get("firmwareVersion") == p.version
            and before_settings.get("firmwareVersion") == p.from_version,
            f"unexpected settings change {changed}")
    caps = after.get("capabilities") or {}
    expected_caps = p.expected_capabilities()
    require(caps.get("presentation") == p.presentation and caps.get("artwork") == expected_caps["artwork"]
            and caps.get("artwork2") == expected_caps.get("artwork2"),
            f"after-inventory capabilities are not {p.tag} (presentation {p.presentation}, artwork unchanged"
            + (", artwork2 equal to presentation.ARTWORK2_CAPABILITY)" if p.artwork2 else ")"))
    if p.alive:
        # ALIVE.md 1: drive = min(150, ledMaxBrightness) of this knob (its settings are unchanged).
        max_brightness = after_settings.get("ledMaxBrightness", t.ALIVE_DEFAULT_DRIVE)
        alive_key = t.presentation().ALIVE_CAPABILITY
        require(caps.get(alive_key) == t.alive_capability(max_brightness),
                f"after-inventory capability {alive_key} is not {t.alive_capability(max_brightness)}")

    manifest = t.load_json(p.manifest)
    for name, value in manifest["artifacts"].items():
        require(t.sha256_file(t.FIRMWARE_OUT / name) == value["sha256"], f"{name} changed since packaging")
    require(manifest["artifacts"][p.image.name]["sha256"] == prep.get("candidateSha256"),
            "manifest names another image")
    status = manifest.get("installationStatus")
    require(status in ("UNFLASHED", "INSTALLED"),
            f"{p.manifest.name} status is {status} (a rollback marks it ROLLED_BACK)")
    active_sha = t.sha256_file(t.ACTIVE_MANIFEST) if t.ACTIVE_MANIFEST.is_file() else None
    if status == "UNFLASHED":
        require(p.from_record.is_file() and active_sha == t.sha256_file(p.from_record),
                f"manifest.json is not the installed {p.from_version} record ({p.from_record.name})")
    else:  # INSTALLED: a re-run; manifest.json must still be this release's record
        require(active_sha == t.sha256_file(p.manifest),
                f"manifest.json is not the installed {p.tag} record although {p.manifest.name} is INSTALLED "
                f"(a rollback restores the {p.from_tag} record)")
    validation_path = t.DIAGNOSTICS / "validation.json"
    kept = t.DIAGNOSTICS / f"validation-before-{p.prefix}.json"
    require(validation_path.is_file(), "diagnostics/validation.json is missing")
    validation = t.load_json(validation_path)
    # Every require() is above this line: from here on the records are written.

    evidence = {p.backup_report.name: backup_sha, p.preparation.name: prep_sha, p.flash_checks.name: flash_sha,
                p.device_checks.name: checks_sha, p.lease_checks.name: lease_sha,
                before_name: before_sha, after_name: after_sha}
    if step_down is not None:
        evidence[p.step_down_report.name] = step_down_sha
    texts = release_texts(p, waived)
    # The recorded waiver (only with --waive-gate): each waived gate with its measured miss, and the note.
    waiver = ({"waivedGates": [waiver_record(gate, checks, waived_checks[gate], waiver_note) for gate in waived],
               "waiverNotNeeded": not_needed, "waiverNote": waiver_note} if waive else {})
    sections = checks.get("sections") or {}
    boot_entries = sorted(q.name for q in t.BOOT_ENTRY.parent.glob(f"{t.BOOT_ENTRY.stem}*.json"))
    stamp = t.utc_stamp()
    media_sections = ("mediaRoundTrip", "mediaPrefetch", "mediaPinning", "mediaErrors", "mediaTiming", "bridgeArtwork2")
    report = {**prep, "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}", "firmwareVersion": p.version,
              "fromVersion": p.from_version,
              **({"binary": p.binary, "buildFlags": list(p.build_flags), "pipeline": p.pipeline,
                  "manifestFile": p.manifest.name, "ladder": ladder_record(p)} if p.binary else {}),
              "flashTool": f"esptool {t.ESPTOOL_VERSION}", "chipMac": t.CHIP_MAC.lower(),
              "flashWritten": True, "currentBackupVerifiedAgainstDevice": True,
              "postWriteEntireFlashVerifiedBeforeReboot": True,
              "verification": "esptool verify_flash 0x0 matched the prepared 4 MB image before hard_reset",
              "flashOutcome": outcome,
              "resetConfirmation": ("read_mac --after hard_reset confirmed" if confirmed else
                                    "reset reply unconfirmed (install exit 5, accepted with --accept-unconfirmed-reset); "
                                    f"the reboot into {p.tag} is proven by the after-inventory and the passed device "
                                    "checks on the application port"),
              "rollbackCheck": ("since the install: no rollback record, rollback folder or log, restored "
                                "manifest.json or ROM bootloader entry of any profile"),
              "onlyApplicationSectorsChanged": True, "romPort": flash.get("port"),
              "applicationPort": checks.get("port"), "bootEntryEvidence": boot_entries,
              "backupEvidence": p.backup_report.name, "flashEvidence": p.flash_checks.name,
              "preWriteBase": {"kind": base_kind, "file": base_file,
                               "evidence": p.step_down_report.name if step_down is not None else p.backup_report.name},
              "evidenceSha256": evidence,
              "beforeInventory": before_name, "afterInventory": after_name,
              "savedProfilesIdentical": True, "savedProfileCount": len(after["profiles"]),
              "settingsChanged": changed, "nativeStartupPreset": after.get("current"), "capabilities": caps,
              "fourControls": checks.get("fourControls"),
              "deviceChecks": {"evidence": p.device_checks.name,
                               "stress": {k: (sections.get("stress") or {}).get(k) for k in ("framesSent", "transfers", "committed", "frameWrite", "perChunk", "perLine", "media", "v1")},
                               "stressTurn": {k: (sections.get("stressTurn") or {}).get(k) for k in ("framesSent", "transfers", "committed", "knobEvents", "media")},
                               "soak": {k: (sections.get("soak") or {}).get(k) for k in ("minutes", "seconds", "cycles", "checkpoints", "framesSent", "transfers", "releases", "failure")},
                               "artwork2": {name: sections.get(name) for name in media_sections},
                               "liveness": checks.get("liveness"),
                               "gates": gates, "rebootWatch": (checks.get("rebootWatch") or {}).get("timeline"),
                               "coldTransfer": sections.get("coldTransferTiming"),
                               "diag": (sections.get("diag") or {}).get("margins"),
                               "media": (sections.get("diag") or {}).get("media")},
              "lease": {"evidence": p.lease_checks.name,
                        **{k: lease.get(k) for k in ("expiry", "artOnly", "framesDuringTransfer", "hostLost",
                                                     "mediaOnly", "framesDuringMediaTransfer", "artwork2")}},
              "desktop": desktop_record(p),
              "physicalVisualAcceptance": texts["physical"],
              "liveActionsInThisValidation": False, **waiver}
    t.write_json_evidence(p.installation, report)

    manifest.update(installationStatus="INSTALLED", installation=report,
                    hardwareStatus=texts["hardware"])
    manifest["validation"].update(flashWriteIssued=True, physicalValidation=texts["validation"],
                                  deviceChecks=p.device_checks.name, leaseChecks=p.lease_checks.name,
                                  evidenceSha256=evidence)
    if waive:   # still INSTALLED, but never read as a clean pass: the waived gates are named next to the status
        manifest["waivedGates"] = manifest["validation"]["waivedGates"] = list(waived)
    else:       # a clean re-run drops the names an earlier waived run recorded (absent: nothing changes)
        manifest.pop("waivedGates", None)
        manifest["validation"].pop("waivedGates", None)
    if args.companion_tests is not None:
        manifest["validation"]["companionTestsPassed"] = args.companion_tests
    if args.light_assertions is not None:
        manifest["validation"]["lightAssertionsPassed"] = args.light_assertions
    text = json.dumps(manifest, indent=2) + "\n"
    p.manifest.write_text(text, encoding="utf-8")
    shutil.copyfile(p.manifest, t.ACTIVE_MANIFEST)
    if t.sha256_file(t.ACTIVE_MANIFEST) != t.sha256_file(p.manifest):  # post-write check, not a gate
        raise SystemExit(f"STOP: manifest.json copy did not verify. {p.installation.name} and "
                         f"{p.manifest.name} were written; copy {p.manifest.name} to manifest.json by hand.")

    if not kept.exists():
        shutil.copyfile(validation_path, kept)
    validation.update(
        date=report["date"], firmware_image_sha256=prep["candidateSha256"],
        firmware_source_files_verified=len(manifest.get("sourceFiles", {})),
        firmware_installation=(f"{p.version} installed; fresh backup and expected entire 4 MB flash verified "
                               "before reboot"))
    validation[p.validation_key] = {"firmwareVersion": p.version, "fromVersion": p.from_version,
                                    **({"binary": p.binary, "manifest": p.manifest.name} if p.binary else {}),
                                    "installationEvidence": p.installation.name,
                                    "deviceChecks": p.device_checks.name, "leaseChecks": p.lease_checks.name,
                                    "flashChecks": p.flash_checks.name, "evidenceSha256": evidence,
                                    "physicalAcceptance": "pending Stage 11",
                                    **({"waivedGates": list(waived), "waiverNotNeeded": not_needed,
                                        "waiverNote": waiver_note} if waive else {})}
    if args.companion_tests is not None:
        validation["automated_tests"] = {"count": args.companion_tests, "failures": 0, "errors": 0}
    note = texts["note"]
    if note not in validation.get("hardware_acceptance", ""):
        validation["hardware_acceptance"] = (validation.get("hardware_acceptance", "") + " " + note).strip()
    validation_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    superseded = supersede_from_release(p)   # last: this release is fully recorded before it
    recorded_as = (f"INSTALLED with waived gates: {', '.join(waived)} (known issue signed off; see waivedGates in "
                   f"{p.installation.name}); copied to" if waived else "INSTALLED and copied to")
    unneeded = f"; waiver not needed (the gate passed): {', '.join(not_needed)}" if not_needed else ""
    print(f"Recorded {p.installation.name} ({p.version}{f' binary {p.binary}' if p.binary else ''}); "
          f"{p.manifest.name} {recorded_as} "
          "manifest.json; "
          f"validation.json updated ({kept.name} kept){unneeded}; {superseded}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
