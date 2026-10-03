"""Package one accepted binary of the current release without touching the device or manifest.json.

The release is nanod_cc5_tooling.CURRENT: 1.0.0-cc5.5 (plan F1; firmware/BUILD-cc5.5.md), upgrading the installed
1.0.0-cc5.4 binary D, with its own ladder: --binary D (default, 16 ms) or F (12 ms), each from its own accepted build
record, written as nanod-control-center-1.0.0-cc5.5-D.bin / -F.bin, -source.zip and manifest-1.0.0-cc5.5-D.json /
-F.json (UNFLASHED). cc5.4 D was installed but never finalized (manifest.json is still the cc5.3 record), so the
from-release record kept here is cc5.4 D's package manifest: firmware/manifest-cc5.4-D.json, a byte copy of
manifest-1.0.0-cc5.4-D.json (written once; an identical file is kept, a different one stops packaging). The
manifest also records the build's flash size gate (image.sizeGate).

1.0.0-cc5.4 (history; the text below is that release's, upgrading the installed 1.0.0-cc5.3). It staged the
PRESENTATION_V5 12.6 build ladder (lead ruling R-m): --binary D (default, the release candidate: A + fixes) or E
(the fallback: C + fixes), each from its own accepted build record (build_nanod_cc5.py --binary <name>). The first
ladder's A, B and C are retired (tooling.RETIRED_BINARIES; A was rolled back with a dark LCD): --binary A|B|C is
refused by argparse (exit 2) and their packages are never touched. Writes, under
app/firmware/ (A kept the release's names; every other binary carries its letter):
  * nanod-control-center-<version>-D.bin        (copy of the binary's accepted firmware.bin)
  * nanod-control-center-<version>-D-source.zip (git ls-files --cached --others --exclude-standard,
                                               minus .vscode/ and the generated compile_commands.json
                                               and *.d files in the firmware root; the same tree for
                                               every binary, only the build flags differ)
  * manifest-<version>-D.json                 (status UNFLASHED, with a "binary" object: name, role,
                                               build flags, pipeline, timing targets, the 12.4 heap
                                               projection and sizes, the pipeline evidence, the LCD
                                               data-line gate (lcdMosiGate), the diag build letter
                                               (diagBuild), the build record, the retired binaries
                                               and the manifests of all five binaries)
  * the from-release record (manifest-cc5.3.json for cc5.4): the installed record, a byte copy of
                                               manifest.json (written once; an identical file is kept,
                                               a different one stops packaging). prepare, finalize and
                                               the cc5.4 -> cc5.3 rollback use it as that record.
Earlier cc5 releases stay as history: their image and source archive are never touched, and
an earlier release manifest that is not INSTALLED is marked SUPERSEDED here (the previous
manifest file is kept as manifest-<version>.superseded-<UTC>.json, never overwritten). An
INSTALLED manifest is never changed by packaging: the installed from-release keeps its INSTALLED
release manifest until finalize_nanod_cc5.py records the current release as installed, which is when
it becomes SUPERSEDED (so an aborted or rolled-back release leaves the from-release records as they
were). manifest.json (the installed record) is never modified. Packaging a binary again (after a fix)
keeps its previous manifest, source archive and a different image as <name>.superseded-<UTC>.<ext>; the
other binaries' packages are never touched. Requires the binary's accepted build record from
build_nanod_cc5.py (diagnostics/<prefix>-build.json: cc5.4-D-build.json, cc5.4-E-build.json) whose SHA-256
still matches its firmware.bin and whose logSha256 still matches its build log (the gates pin that log; the
build script keeps an earlier log as *.superseded-<UTC>.log), for a presentation 5 release with the
PRESENTATION_V5 12.4 sizes (heapProjection ccFrameBytes and aliveInstanceBytes), for a ladder binary with a
passed LCD data-line gate (lcdMosiGate: a DMA build with TFT_MISO == TFT_MOSI links cc_lcd_mosi_reattach and
LcdThread::run() calls it right after tft.initDMA(), recorded as callOrder), and
re-checks the image (version, size, the binary's R5 marker and build marker "cc-build-binary:<n>"). A record
written before these fields existed is refused: build that binary again. The gates the manifest pins include the
stage9b gate runs (cc5.4-stage*) and the ALIVE floor report (cc5.4-alive-floor-report.json, a cc5.4-*-report).
Git is only read (ls-files / rev-parse with a safe.directory override).

An installed but never finalized binary (TL-BUG-013): when the records say this binary was written to the knob
(tooling.binary_write_evidence: a flash-checks record with a write attempt) and no rollback record of it is newer
than its newest write, a package whose image would differ from the one in firmware/ is refused before anything is
written: the knob runs that image and its flash and look evidence point at it. --replace-installed packages it
anyway and records why in the manifest (replacedInstalledImage).
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402

EXCLUDED_PREFIXES = (".vscode/",)
# Generated next to the sources, never sources: PlatformIO's compilation database (-t compiledb,
# about 20 MB of this PC's absolute paths) and the dependency files a -MMD syntax check leaves
# in the firmware root.
EXCLUDED_ROOT_NAMES = ("compile_commands.json",)
EXCLUDED_ROOT_SUFFIXES = (".d",)
# What happened to each superseded cc5 release (recorded in its manifest when it is superseded).
SUPERSEDED_HISTORY = {
    "1.0.0-cc5": (
        "Flashed app-only on 2026-09-23 and verified (full 4 MB); boot sanity and inventory passed. "
        "check_nanod_cc5.py run 1 ended with a device reset in the stress section, with no core dump "
        "written. The knob was NOT turned in that run: '--turn-seconds 10' only added three cold art "
        "transfers before the stress. Run 2 passed the stress and failed only the diag stack margin "
        "(stackHmi 628 B free of 4608). Rolled back to cc4 (full 4 MB verified identical to "
        "backups/nanod-cc4-before-cc5-full.bin; diagnostics/cc5-rollback.json). Never finalized."),
    "1.0.0-cc5.1": (
        "Flashed app-only on 2026-09-23 (image SHA-256 f75ac481...) and verified; no reboot in four "
        "check_nanod_cc5.py runs (bootCount and uptime continuous, coredump blank), stacks healthy, the "
        "untouched stress passed three times. In the third run (13:37 local) the HMI task hung inside "
        "FastLED.show() about 9 s into the untouched stress (breadcrumb hmi.step 'show' at uptime "
        "700,236 ms while COM and LCD ran on to ~3,784,782 ms): ring and button LEDs frozen, buttons dead, "
        "and releases never acknowledged, so every new control was refused. Cause: a task/interrupt race in "
        "FastLED 3.6.0's ESP32 RMT driver (unlocked gNext/gNumDone, portMAX_DELAY wait), exposed by cc5's "
        "heavier core-0 load. Rolled back to cc4 (full 4 MB verified identical to "
        "backups/nanod-cc4-before-cc5-full.bin; diagnostics/cc5-rollback.json). Never finalized."),
    # 1.0.0-cc5.2 and 1.0.0-cc5.3 were installed: finalize_nanod_cc5.py supersedes the from-release
    # (FROM_RELEASE_HISTORY there).
}
# What each release changes against the release it upgrades from (changedFromPreviousCc5.summary).
RELEASE_SUMMARIES = {
    "1.0.0-cc5.3": (
        "1.0.0-cc5.3 adds artwork2 on 1.0.0-cc5.2 (firmware/ARTWORK2.md): the sibling capability "
        "artwork2 (presentation stays 4; the v1 artwork object, the art command, its 120 px store, error strings "
        "and binding rule are byte-identical), the media command (have/begin/data/commit, one mediaAck per line) "
        "with two PSRAM stores (24 baseline 240x240 JPEG covers of at most 32768 B, 48 32x32 RGB565 icons) and "
        "knob-side prefetch with pinning of the frame's and the displayed key, JPEG decode on the LCD thread "
        "(ROM TJpgDec) into front/back 240x240 buffers, the optional frame field iconKey and the Windows tile "
        "icon, an 8192-byte internal CDC receive queue with a 1-tick COM idle while a line or upload is pending "
        "(unpaced whole-line transport when negotiated), and the diag fields rxQueueBytes, mediaCommits, "
        "mediaErrors, mediaEvictions, jpegDecodes, jpegDecodeErrors, jpegDecodeMsMax and jpegDecodeMsLast."),
    "1.0.0-cc5.5": (
        "1.0.0-cc5.5 (plan F1, safety and measurement, no change to feel) on 1.0.0-cc5.4 binary D: HID reports "
        "marked sent only when TinyUSB accepts them (one per pass, actual key codes compared), the USB interface "
        "results reported instead of assumed, the motor output capped at 2.2 V before motor.init() with no register "
        "command able to raise it (phase resistance 5.3 kept), haptic profiles validated (detentCount >= 1, vernier "
        ">= 1, endPos >= startPos) and the brace-less else in haptic_target made explicit (behaviour unchanged), no "
        "String or Serial.println on the FOC thread, a clear-only ks on position lines with a 16-event key queue, "
        "and the diag fields focLoopHz, focLoopUsMax, uqAbsMax, uqCapMs, uqCapMv, pdRead, pdPdo, pdVolts, pdRdo, "
        "usbMidiOk, usbHidOk and hidRetries; binaries D (16 ms) and F (12 ms, diag build F)."),
    "1.0.0-cc5.6": (
        "1.0.0-cc5.6 (plan A2) on 1.0.0-cc5.5 binary D: the app canvas. A frame's optional app object (capability "
        "appCanvas 1, presentation 6) makes the LCD thread pause LVGL and draw Karl Malota's Onshape UI (adapted with "
        "permission) into a PSRAM 240x240 RGB565 buffer pushed by DMA through LVGL's idle draw buffers: the "
        "isometric cube following the knob's own sensor angle (stepped poses, 220 ms settle), the command wheel "
        "with its animated cards (rings MODEL / MODIFY / SKETCH / VIEW), parameter mode A / B, the echo and the "
        "idle plasma. LVGL resumes and redraws in full on exit. Everything else is 1.0.0-cc5.5 D."),
    "1.0.0-cc5.4": (
        "1.0.0-cc5.4 (Warm alive) on 1.0.0-cc5.3 (firmware/ALIVE.md, PRESENTATION_V5.md): "
        "presentation 5 with the alive LED renderer (the ring and button LEDs rendered by the knob at its own "
        "frame rate from the frame's lights object; six glow looks, breathing idle, press and claim "
        "feedback, limit flares; drive min(150, ledMaxBrightness), reported as the alive capability), limit "
        "events at the travel ends, the ready key state and hold/deferred handling of the presentation 5 "
        "protocol, text during the volume reveals and the offline native line; artwork2, the v1 art path and "
        "the presentation 2/4 frames are unchanged; the build record carries the PRESENTATION_V5 12.4 heap "
        "projection."),
}
# What each release's manifest says about the companions it works with (compatibility).
COMPATIBILITY = {
    "1.0.0-cc5.6": ("presentation 6, every 1.0.0-cc5.5 capability unchanged, plus appCanvas 1. A host that never "
                    "sends the frame's app object (the installed Desk Dial, anything before 7.2.0.0) sees 1.0.0-cc5.5 D "
                    "exactly. Desk Dial 7.2.0.0 sends app only to an appCanvas knob; on 1.0.0-cc5.5 / cc5.4 it keeps "
                    "A0's text frames and tap 3 = Undo (no wheel, no parameter mode)."),
    "1.0.0-cc5.5": ("presentation 6 and every capability exactly as 1.0.0-cc5.4 D reports them (nothing new is "
                    "advertised). Position lines of the ready control now carry ks, the last reported key mask AND "
                    "the live one: it can only clear bits, so the installed Desk Dial v7 (which copies any ks into its "
                    "pressed mask) never loses a kd or a ku to it, and a newer Desk Dial clears lost key-ups from it. "
                    "The new diag fields are ignored by v7 and read by the newer device.py; a newer Desk Dial on "
                    "cc5.4 simply sees no ks on position lines and no F1 diag fields."),
    "1.0.0-cc5.3": ("presentation stays 4. A cc5.2-era companion (desktop v3) gets v1 art, paced, exactly as on "
                    "cc5.2: the v1 art path is byte-identical. The v4 companion uses artwork2 (240 px JPEG covers, "
                    "app icons, prefetch, unpaced whole-line writes) only when the artwork2 capability matches "
                    "exactly; against cc5.2 it falls back to v1 art with pacing, against cc4 to text only. cc5.3 "
                    "still accepts presentation-2 frames from the cc4-era companion."),
    "1.0.0-cc5.4": ("presentation 5 (PRESENTATION_V5.md 2.1). The v7 companion sends full v5 frames with the "
                    "alive fields (hold, ready key state, limit events) when presentation 5 and the alive "
                    "capability match; against cc5.3 it downgrades to presentation-4 frames (no hold, the V4 LED "
                    "model, artwork2), against cc5.2 / cc5 the same with v1 art, against cc4 the legacy rules. "
                    "Desktop v6 on cc5.4 keeps sending presentation-4 frames: the knob's alive engine renders the "
                    "LEDs from them and local input and the v5 renderer draws them; artwork2 and the v1 art path "
                    "are unchanged."),
}
RELEASE_SUMMARY = RELEASE_SUMMARIES.get(t.CURRENT.version, f"{t.CURRENT.version} on {t.CURRENT.from_version}.")


def git(*args):
    safe = t.FIRMWARE_SOURCE.as_posix()
    return subprocess.check_output(["git", "-c", f"safe.directory={safe}", "-C", str(t.FIRMWARE_SOURCE), *args],
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _excluded(name):
    """Not part of the source listing: .vscode/ and the generated compile_commands.json and *.d in the root."""
    if not name or name.startswith(EXCLUDED_PREFIXES):
        return True
    return "/" not in name and (name in EXCLUDED_ROOT_NAMES or name.endswith(EXCLUDED_ROOT_SUFFIXES))


def source_files(git_run=None):
    """(names, missing) of the firmware tree's sources (git ls-files --cached --others --exclude-standard, minus
    _excluded). `git_run`: the caller's git (build_nanod_cc5.py passes its own)."""
    listed = (git_run or git)("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode("utf-8").split("\0")
    names, missing = set(), []
    for name in listed:
        if _excluded(name):
            continue
        if not (t.FIRMWARE_SOURCE / name).is_file():
            missing.append(name)  # tracked but deleted in the working tree
            continue
        names.add(name)
    for name in names:
        parts = PurePosixPath(name).parts
        if any(part in (".git", ".pio", "__pycache__") for part in parts) or name.startswith("/") or ".." in parts:
            raise SystemExit(f"Refusing to package {name}")
    return sorted(names), sorted(missing)


def source_snapshot(git_run=None):
    """The firmware tree as a build saw it (TL-BUG-005; build_nanod_cc5.py records it at build start as
    sourceSnapshot): the digests of every source_files() name (platformio.ini, include/, boards/ and src/ among
    them), the names tracked but missing, HEAD, and whether git status --porcelain showed changes (dirty)."""
    run = git_run or git
    files, missing = source_files(run)
    status = []
    for line in run("status", "--porcelain").decode("utf-8", errors="replace").splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if line.strip() and not _excluded(path):
            status.append(line)
    return {"sourceFiles": {name: t.digest_record(t.FIRMWARE_SOURCE / name) for name in files},
            "sourceFilesMissingFromWorkTree": missing,
            "checkoutHead": run("rev-parse", "HEAD").decode("ascii").strip(),
            "dirty": bool(status), "status": status[:200]}


def source_drift(recorded, current):
    """Names whose digest differs between the build's sourceFiles and the tree now: {added, removed, modified}
    (empty lists: the tree is the one the image was built from)."""
    return {"added": sorted(set(current) - set(recorded)),
            "removed": sorted(set(recorded) - set(current)),
            "modified": sorted(name for name in set(current) & set(recorded)
                               if (recorded[name] or {}).get("sha256") != current[name]["sha256"])}


def gates(p=None):
    p = p or t.CURRENT
    found = {}
    for pattern in p.gate_patterns:
        for path in sorted(t.DIAGNOSTICS.glob(pattern)):
            if ".superseded" in path.name:
                continue
            found[f"diagnostics/{path.name}"] = t.digest_record(path)
    if p.build_log.is_file():
        found[f"work/{p.build_log.name}"] = t.digest_record(p.build_log)
    return found


def previous_release_changes(sources, p=None):
    """Source changes against the release this one upgrades from (its package manifest: cc5.4 D's for
    1.0.0-cc5.5), else the newest superseded cc5 release that recorded its sources."""
    p = p or t.CURRENT
    candidates = [(p.from_artifact_version, p.from_manifest)]
    candidates += [(version, t.release_manifest(version)) for version in reversed(p.superseded)]
    for version, path in candidates:
        if not path.is_file():
            continue
        before = t.load_json(path).get("sourceFiles") or {}
        changed = {"from": version,
                   "added": sorted(set(sources) - set(before)),
                   "removed": sorted(set(before) - set(sources)),
                   "modified": sorted(n for n in set(sources) & set(before)
                                      if sources[n]["sha256"] != before[n]["sha256"])}
        changed["counts"] = {k: len(changed[k]) for k in ("added", "removed", "modified")}
        changed["summary"] = RELEASE_SUMMARIES.get(p.version, RELEASE_SUMMARY)
        return changed
    return None


def keep_from_record(p=None):
    """firmware/<from record>: the installed from-release record, kept byte-identical before its
    release manifest is marked SUPERSEDED. Returns a line for the output; stops on a conflict.

    A from-release that was installed but never finalized (p.from_finalized False: 1.0.0-cc5.4 D under cc5.5) has
    no installed record in manifest.json: its record is its package manifest (p.from_manifest), kept as a byte copy
    (firmware/manifest-cc5.4-D.json) once it names the from image with its SHA-256."""
    p = p or t.CURRENT
    if not p.from_finalized:
        source = p.from_manifest
        if p.from_record.is_file():
            problems = t.from_record_problems(p)
            if problems:
                raise SystemExit(f"{p.from_record.name} exists but is not the {p.from_version} record ({problems[0]})")
            if source.is_file() and t.sha256_file(source) != t.sha256_file(p.from_record):
                raise SystemExit(f"{p.from_record.name} differs from {source.name}; decide with the user which record "
                                 f"describes the installed {p.from_artifact_version}")
            return f"{p.from_record.name} kept (the installed, never finalized {p.from_artifact_version} record)"
        problems = t.from_record_problems(p, source)
        if problems:
            raise SystemExit(f"{source.name} cannot be kept as {p.from_record.name}: {problems[0]}")
        t.write_new_bytes(p.from_record, source.read_bytes())
        if t.sha256_file(p.from_record) != t.sha256_file(source):
            raise SystemExit(f"{p.from_record.name} copy did not verify")
        return (f"{p.from_record.name} written: byte copy of {source.name} (the installed {p.from_artifact_version}, "
                "never finalized; manifest.json stays the record it left in force, "
                f"{p.restore_record.name})")
    if p.from_record.is_file():
        record = t.load_json(p.from_record)
        if (record.get("firmwareVersion") != p.from_version
                or record.get("artifacts", {}).get(p.from_image.name, {}).get("sha256") != p.from_image_sha256):
            raise SystemExit(f"{p.from_record.name} exists but is not the {p.from_version} record")
        if t.ACTIVE_MANIFEST.is_file() and t.load_json(t.ACTIVE_MANIFEST).get("firmwareVersion") == p.from_version \
                and t.sha256_file(t.ACTIVE_MANIFEST) != t.sha256_file(p.from_record):
            raise SystemExit(f"{p.from_record.name} differs from manifest.json, which is the {p.from_version} record; "
                             "decide with the user which record is the installed one")
        return f"{p.from_record.name} kept (the installed {p.from_version} record)"
    if not t.ACTIVE_MANIFEST.is_file():
        raise SystemExit("firmware/manifest.json is missing")
    active = t.load_json(t.ACTIVE_MANIFEST)
    if (active.get("firmwareVersion") != p.from_version or active.get("installationStatus") != "INSTALLED"
            or active.get("artifacts", {}).get(p.from_image.name, {}).get("sha256") != p.from_image_sha256):
        raise SystemExit(f"manifest.json is not the INSTALLED {p.from_version} record ({p.from_image.name}, "
                         f"SHA-256 {p.from_image_sha256}); {p.version} upgrades from it")
    t.write_new_bytes(p.from_record, t.ACTIVE_MANIFEST.read_bytes())
    if t.sha256_file(p.from_record) != t.sha256_file(t.ACTIVE_MANIFEST):
        raise SystemExit(f"{p.from_record.name} copy did not verify")
    return f"{p.from_record.name} written: byte copy of manifest.json (the installed {p.from_version} record)"


def supersede_earlier_releases(p=None):
    """Mark each earlier cc5 manifest SUPERSEDED; its previous file is kept, never overwritten.

    Images and source archives are not touched. An INSTALLED manifest is always left alone:
    only finalize and rollback change an installed record. The release this one upgrades from
    is superseded by finalize_nanod_cc5.py once this release is recorded as installed.
    """
    p = p or t.CURRENT
    lines = []
    for version in p.superseded:
        path = t.release_manifest(version)
        if not path.is_file():
            continue
        record = t.load_json(path)
        status = record.get("installationStatus")
        if status == "SUPERSEDED":
            continue
        if status == "INSTALLED":
            lines.append(f"{path.name} is INSTALLED; not marked SUPERSEDED"
                         + (f" (finalize_nanod_cc5.py does that once {p.version} is recorded as installed)"
                            if version == p.from_version else ""))
            continue
        kept = t.archive_existing(path)
        record.update(installationStatus="SUPERSEDED", statusBeforeSupersede=status,
                      supersededBy=p.version, supersededUtc=t.utc_stamp(),
                      history=SUPERSEDED_HISTORY.get(version, "Superseded before it was finalized."),
                      hardwareStatus=f"Superseded by {p.version}; kept as history. Never installed as final.")
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(record, indent=2) + "\n")
        lines.append(f"{path.name}: {status} -> SUPERSEDED (previous file kept as {kept.name})")
    return lines


def binary_record(p, build):
    """The manifest's "binary" object for a ladder binary (None for a release without the ladder)."""
    if not p.binary:
        return None
    return {"name": p.binary, "role": t.BINARY_ROLES[p.binary], "buildFlags": list(p.build_flags),
            "buildNumber": p.build_number, "diagBuild": p.binary if p.build_number is not None else None,
            "parent": t.BINARY_PARENTS.get(p.binary), "fixes": t.BINARY_FIXES.get(p.binary),
            "pipeline": p.pipeline, "timingTargets": {"lcdFpsAnimMin": t.LCD_FPS_TARGETS[p.binary],
                                                      "lcdLateRefrs": "0 outside cover arrivals"},
            "stepDownRemoves": t.BINARY_STEP_DOWN.get(p.binary),
            "buildRecord": f"diagnostics/{p.build_report.name}", "buildLog": f"work/{p.build_log.name}",
            "buildLogSha256": build.get("logSha256"),
            "heapProjection": build.get("heapProjection"), "pipelineEvidence": build.get("pipelineEvidence"),
            "lcdMosiGate": build.get("lcdMosiGate"),
            "ladder": {v.binary: v.manifest.name for v in p.variants()},
            "active": list(t.binary_choices(p)),
            "retired": {k: v for k, v in t.RETIRED_BINARIES.items() if k in p.pipeline_binaries()},
            "contract": ("PRESENTATION_V5.md 12.6 (P5-R23); lead ruling R-m; firmware/BUILD-cc5.4.md"
                         + (" (Fix binaries D and E)" if p.build_number is not None else "")
                         if p.tag == "cc5.4" else f"plan stage {'A2' if p.tag == 'cc5.6' else 'F1'}; "
                         f"firmware/BUILD-{p.tag}.md (binaries D and F)")}


ROLLED_BACK_OUTCOMES = ("ROLLED_BACK_VERIFIED_RESET", "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED", "RECORDS_ONLY")


def _record_stamps(paths, keep):
    """startedUtc (tooling.utc_stamp, sortable) of every readable record in `paths` that `keep` accepts."""
    stamps = []
    for path in paths:
        try:
            record = t.load_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and keep(record) and isinstance(record.get("startedUtc"), str):
            stamps.append(record["startedUtc"])
    return stamps


def installed_unfinalized(p, diagnostics=None):
    """Why p.image must not be replaced (empty: it may): the records say this binary was written to the knob
    (tooling.binary_write_evidence) and no rollback record of it (current or superseded, a rolled-back outcome)
    started after its newest write. finalize is not required for that state, so packaging must notice it."""
    diagnostics = Path(t.DIAGNOSTICS if diagnostics is None else diagnostics)
    reasons = t.binary_write_evidence(p, diagnostics)
    if not reasons:
        return []
    writes = _record_stamps(sorted(diagnostics.glob(f"{p.prefix}-flash-checks*.json")),
                            lambda r: r.get("writeAttempted") or r.get("flashWritten"))
    rollbacks = _record_stamps(sorted(diagnostics.glob(f"{p.prefix}-rollback*.json")),
                               lambda r: r.get("outcome") in ROLLED_BACK_OUTCOMES)
    if rollbacks and (not writes or max(rollbacks) > max(writes)):
        return []
    return reasons


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = t.binary_choices()
    if choices:
        parser.add_argument("--binary", choices=choices, default=choices[0],
                            help=f"the PRESENTATION_V5 12.6 binary to package (default {choices[0]})")
    parser.add_argument("--replace-installed", action="store_true",
                        help="replace the image of a binary the records show installed and not rolled back "
                             "(recorded in the manifest as replacedInstalledImage)")
    # 1.0.0-cc5.6 (A2): as build_nanod_cc5.py --release.
    releases = [tag for tag, profile in t.PROFILES.items() if profile.pipeline_binaries() == t.CURRENT.pipeline_binaries()]
    parser.add_argument("--release", choices=releases, default=t.CURRENT.tag,
                        help=f"the release profile (default {t.CURRENT.tag}, CURRENT)")
    args = parser.parse_args(argv)
    t.console_utf8()
    p = t.PROFILES[args.release].binary_profile(getattr(args, "binary", None))
    build = t.load_json(p.build_report)
    if not build.get("accepted") or build.get("version") != p.version:
        raise SystemExit(f"{p.build_report.name} does not record an accepted {p.version} build; run build_nanod_cc5.py"
                         + (f" --binary {p.binary}" if p.binary else ""))
    if p.binary and build.get("binary") != p.binary:
        raise SystemExit(f"{p.build_report.name} records binary {build.get('binary')}, not {p.binary}; "
                         f"run build_nanod_cc5.py --binary {p.binary}")
    image = p.built_image.read_bytes()
    if t.sha256_bytes(image) != build["sha256"]:
        raise SystemExit("firmware.bin changed since the accepted build; rebuild first")
    problems = (t.app_image_problems(image, p.version) + t.binary_image_problems(image, p.binary)
                + t.release_image_problems(image))
    if problems:
        raise SystemExit("; ".join(problems))
    log = p.build_log.read_text(encoding="utf-8-sig", errors="replace")
    if "[SUCCESS]" not in log:
        raise SystemExit("The build log does not record [SUCCESS]")
    rebuild = f"run build_nanod_cc5.py{f' --binary {p.binary}' if p.binary else ''} again"
    # The gates pin the log's SHA-256: it must be the log of this accepted build (build_nanod_cc5.py keeps an
    # earlier log as nanod-<tag>-build.superseded-<UTC>.log, so every superseded manifest's log stays resolvable).
    if not build.get("logSha256"):
        raise SystemExit(f"{p.build_report.name} does not record its build log's SHA-256 (logSha256); {rebuild}")
    if t.sha256_file(p.build_log) != build["logSha256"]:
        raise SystemExit(f"{p.build_log.name} is not the log of the accepted build ({p.build_report.name} logSha256); "
                         f"{rebuild}")
    if getattr(p, "presentation", 4) >= 5:
        projection = build.get("heapProjection") or {}
        if not all(isinstance(projection.get(key), int) for key in t.V5_SIZE_FIELDS):
            raise SystemExit(f"{p.build_report.name} does not record sizeof(CCFrame) and the ALIVE instance size "
                             f"(heapProjection {', '.join(t.V5_SIZE_FIELDS)}; PRESENTATION_V5 12.4); {rebuild}")
    if p.binary:
        # The LCD data line (binary A's dark LCD): only a build whose record passed the gate is ever packaged.
        gate = build.get("lcdMosiGate")
        if not (isinstance(gate, dict) and gate.get("passed") is True and "callOrder" in gate):
            raise SystemExit(f"{p.build_report.name} does not record a passed LCD data-line gate (lcdMosiGate: a DMA "
                             f"build with TFT_MISO == TFT_MOSI must link {t.LCD_MOSI_REATTACH_SYMBOL} and call it right "
                             f"after tft.initDMA(), callOrder); {rebuild}")
    # TL-BUG-005: the sources archived next to the image must be the ones it was built from. The build records the
    # tree's digests at its start; any file added, removed or changed since refuses (nothing is written).
    snapshot = build.get("sourceSnapshot")
    if not (isinstance(snapshot, dict) and isinstance(snapshot.get("sourceFiles"), dict) and snapshot["sourceFiles"]):
        raise SystemExit(f"{p.build_report.name} does not record the sources it was built from (sourceSnapshot); "
                         f"{rebuild}. Nothing was written")
    files, missing = source_files()
    sources = {name: t.digest_record(t.FIRMWARE_SOURCE / name) for name in files}
    drift = source_drift(snapshot["sourceFiles"], sources)
    if any(drift.values()):
        names = [f"{name} ({kind})" for kind in ("modified", "added", "removed") for name in drift[kind]]
        raise SystemExit(f"the firmware tree changed since the accepted build: {', '.join(names[:6])}"
                         f"{' ...' if len(names) > 6 else ''}; the archive would not hold the sources of this image. "
                         f"Restore the tree or {rebuild}. Nothing was written")
    if p.manifest.is_file() and t.load_json(p.manifest).get("installationStatus") == "INSTALLED":
        raise SystemExit(f"{p.version} is recorded as INSTALLED; its artifacts are not replaced")
    replaced_installed = None
    if p.image.is_file() and t.sha256_file(p.image) != build["sha256"]:
        installed = installed_unfinalized(p)
        if installed and not args.replace_installed:
            raise SystemExit(f"{p.image.name} is the image the records show on the knob ({'; '.join(installed)}) and no "
                             f"rollback of it is newer; packaging would replace it with an image the knob never ran. "
                             f"Finalize or roll it back first, or pass --replace-installed. Nothing was written")
        if installed:
            replaced_installed = {"reasons": installed, "previousImageSha256": t.sha256_file(p.image),
                                  "flag": "--replace-installed"}
    active_before = t.sha256_file(t.ACTIVE_MANIFEST) if t.ACTIVE_MANIFEST.is_file() else None

    base = t.load_json(t.CC4_MANIFEST)
    if base.get("firmwareVersion") != t.CC4_VERSION:
        raise SystemExit("manifest-cc4.json is not the cc4 record")
    if base["artifacts"][t.CC4_IMAGE.name]["sha256"] != t.CC4_IMAGE_SHA256:
        raise SystemExit("manifest-cc4.json does not describe the installed cc4 image")
    from_line = keep_from_record(p)          # before anything else is written
    manifest = deepcopy(base)

    # Re-packaging this release (for example after review fixes) keeps the previous package as
    # history, never overwritten: <name>.superseded-<UTC>.<ext> (an identical image is not copied).
    kept = []
    if p.image.is_file() and t.sha256_file(p.image) != build["sha256"]:
        kept.append(t.archive_existing(p.image).name)
    for path in (p.source_zip, p.manifest):
        if path.is_file():
            kept.append(t.archive_existing(path).name)
    p.image.write_bytes(image)
    if t.sha256_file(p.image) != build["sha256"]:
        raise SystemExit("Copied image does not match the accepted build")
    with zipfile.ZipFile(p.source_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in files:
            bundle.writestr(f"NanoD_RatchetH1/{name}", (t.FIRMWARE_SOURCE / name).read_bytes())
    with zipfile.ZipFile(p.source_zip) as bundle:
        if bundle.testzip() is not None or len(bundle.namelist()) != len(files):
            raise SystemExit("Source archive failed its integrity check")
        for name in files:
            # Against the build's own digests (sourceSnapshot): the archive holds the sources of this image.
            if hashlib.sha256(bundle.read(f"NanoD_RatchetH1/{name}")).hexdigest() != snapshot["sourceFiles"][name]["sha256"]:
                raise SystemExit(f"Archived {name} differs from the sources of the accepted build")

    before = base.get("sourceFiles", {})
    changed = {"added": sorted(set(sources) - set(before)),
               "removed": sorted(set(before) - set(sources)),
               "modified": sorted(n for n in set(sources) & set(before) if sources[n]["sha256"] != before[n]["sha256"])}
    changed["counts"] = {k: len(v) for k, v in changed.items()}
    changed["summary"] = ("Album artwork (120x120 RGB565 cache, PSRAM), presentation contract v4 frame parser, "
                          "targeted-colour LED model, latin-ext-a LCD fonts, retained LVGL renderer with semantic diffing, "
                          "non-blocking serial line assembly, diag reply, host-lost notice restyle, bounded LED "
                          "transport, task watchdog and release acknowledgement timeout, artwork2 (240 px JPEG "
                          "covers, app icons, prefetch, unpaced transport)"
                          + ("; presentation 5 with the alive LED renderer, limit events and the ready/hold "
                             "protocol" if getattr(p, "alive", False) else "")
                          + f"; version {p.version}.")
    previous = previous_release_changes(sources, p)
    head = snapshot.get("checkoutHead") or git("rev-parse", "HEAD").decode("ascii").strip()
    manifest.update(
        firmwareVersion=p.version, installationStatus="UNFLASHED", upgradesFrom=p.from_version,
        artifacts={p.image.name: t.digest_record(p.image), p.source_zip.name: t.digest_record(p.source_zip)},
        image={"file": p.image.name, "sha256": build["sha256"], "bytes": len(image), "slotBytes": t.APP_SIZE,
               "headroomBytes": t.APP_SIZE - len(image), "cc4Bytes": t.CC4_IMAGE_BYTES,
               "deltaFromCc4Bytes": len(image) - t.CC4_IMAGE_BYTES, "previousBytes": p.from_image_bytes,
               "deltaFromPreviousBytes": len(image) - p.from_image_bytes, "containsVersion": True,
               **({"sizeGate": build.get("sizeGate")} if build.get("sizeGate") is not None else {})},
        sourceFiles=sources,
        sourceListing=("git ls-files --cached --others --exclude-standard (minus .vscode/, and the generated "
                       "compile_commands.json and *.d in the firmware root)"),
        sourceFilesMissingFromWorkTree=missing, checkoutHead=head, dirty=bool(snapshot.get("dirty")),
        sourcesFromBuild={"record": p.build_report.name, "files": len(files), "matched": True}, changedFromCc4=changed,
        changedFromPreviousCc5=previous, supersedes=list(p.superseded),
        previousPackagingKept=kept, installedRecordBeforeUpgrade=p.from_record.name,
        expectedCapabilities=p.expected_capabilities(),
        compatibility=COMPATIBILITY.get(p.version, f"presentation {p.presentation}."),
        gates=gates(p),
        validation={"firmwareBuild": "PASS", "physicalValidation": "PENDING", "flashWriteIssued": False},
        hardwareStatus=(f"{p.from_version} remains installed until the verified application-only {p.version} "
                        "update completes."
                        + (f" Binary {p.binary} ({t.BINARY_ROLES[p.binary]}) of the PRESENTATION_V5 12.6 ladder"
                           + ("." if p.binary == (t.binary_choices(p) or (None,))[0] else
                              f": flashed only when the hardware window steps down to it (firmware/BUILD-{p.tag}.md)."
                              if p.tag == "cc5.4" else
                              f": flashed only when the hardware window moves to it (firmware/BUILD-{p.tag}.md).")
                           if p.binary else "")))
    # FW-PUB-004: the public version (platformio.ini NANO_FIRMWARE_PUBLIC) and the string this image reports.
    manifest.update(t.public_version_fields(p, p.binary))
    if p.binary:
        manifest["binary"] = binary_record(p, build)
    if replaced_installed:
        manifest["replacedInstalledImage"] = replaced_installed
    manifest["build"].update(flashUsedBytes=build.get("flashUsedBytes"), ramUsedBytes=build.get("ramUsedBytes"),
                             buildRecord=f"diagnostics/{p.build_report.name}")
    for key in ("installation", "hardwareValidation", "changedFromCc3"):
        manifest.pop(key, None)
    p.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    superseded = supersede_earlier_releases(p)
    active_after = t.sha256_file(t.ACTIVE_MANIFEST) if t.ACTIVE_MANIFEST.is_file() else None
    if active_after != active_before:
        raise SystemExit("manifest.json changed during packaging; that must never happen. Restore it from "
                         f"{p.from_record.name} and investigate")
    if t.load_json(t.ACTIVE_MANIFEST).get("firmwareVersion") == p.version:
        print(f"Note: manifest.json already names {p.version} (left unchanged by this script).")
    if p.binary:
        print(f"Binary {p.binary} ({t.BINARY_ROLES[p.binary]}): flags {' '.join(p.build_flags) or '(source defaults)'}; "
              f"pipeline {p.pipeline}")
    print(f"Packaged {len(files)} source files; image {len(image)} B (headroom {t.APP_SIZE - len(image)} B, "
          f"{len(image) - p.from_image_bytes:+d} B vs {p.from_version}, {len(image) - t.CC4_IMAGE_BYTES:+d} B vs cc4)")
    for name, value in manifest["artifacts"].items():
        print(f"  {name}: {value['bytes']} B sha256 {value['sha256']}")
    print(f"  changedFromCc4: {changed['counts']}; changedFromPreviousCc5: "
          f"{(previous or {}).get('counts')}; gates recorded: {len(manifest['gates'])}")
    print(f"  {from_line}")
    for line in superseded:
        print(f"  {line}")
    for name in kept:
        print(f"  previous packaging of {p.version} kept as {name}")
    print(f"Wrote {p.manifest.name} (UNFLASHED); manifest.json untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
