"""Package one accepted binary of the current release without touching the device or manifest.json.

The release is nanod_cc5_tooling.CURRENT (1.0.0-cc5.4, upgrading the installed 1.0.0-cc5.3). It stages the
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


def source_files():
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode("utf-8").split("\0")
    names, missing = set(), []
    for name in listed:
        if not name or name.startswith(EXCLUDED_PREFIXES):
            continue
        if "/" not in name and (name in EXCLUDED_ROOT_NAMES or name.endswith(EXCLUDED_ROOT_SUFFIXES)):
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
    """Source changes against the newest superseded cc5 release that recorded its sources."""
    p = p or t.CURRENT
    for version in reversed(p.superseded):
        path = t.release_manifest(version)
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
    release manifest is marked SUPERSEDED. Returns a line for the output; stops on a conflict."""
    p = p or t.CURRENT
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
            "active": list(t.binary_choices(p)), "retired": dict(t.RETIRED_BINARIES),
            "contract": ("PRESENTATION_V5.md 12.6 (P5-R23); lead ruling R-m; firmware/BUILD-cc5.4.md"
                         + (" (Fix binaries D and E)" if p.build_number is not None else ""))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = t.binary_choices()
    if choices:
        parser.add_argument("--binary", choices=choices, default=choices[0],
                            help=f"the PRESENTATION_V5 12.6 binary to package (default {choices[0]})")
    args = parser.parse_args(argv)
    t.console_utf8()
    p = t.CURRENT.binary_profile(getattr(args, "binary", None))
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
    problems = t.app_image_problems(image, p.version) + t.binary_image_problems(image, p.binary)
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
    if p.manifest.is_file() and t.load_json(p.manifest).get("installationStatus") == "INSTALLED":
        raise SystemExit(f"{p.version} is recorded as INSTALLED; its artifacts are not replaced")
    active_before = t.sha256_file(t.ACTIVE_MANIFEST) if t.ACTIVE_MANIFEST.is_file() else None

    base = t.load_json(t.CC4_MANIFEST)
    if base.get("firmwareVersion") != t.CC4_VERSION:
        raise SystemExit("manifest-cc4.json is not the cc4 record")
    if base["artifacts"][t.CC4_IMAGE.name]["sha256"] != t.CC4_IMAGE_SHA256:
        raise SystemExit("manifest-cc4.json does not describe the installed cc4 image")
    from_line = keep_from_record(p)          # before anything else is written
    manifest = deepcopy(base)
    files, missing = source_files()

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
            if hashlib.sha256(bundle.read(f"NanoD_RatchetH1/{name}")).hexdigest() != t.sha256_file(t.FIRMWARE_SOURCE / name):
                raise SystemExit(f"Archived {name} differs from the working tree")

    sources = {name: t.digest_record(t.FIRMWARE_SOURCE / name) for name in files}
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
    head = git("rev-parse", "HEAD").decode("ascii").strip()
    manifest.update(
        firmwareVersion=p.version, installationStatus="UNFLASHED", upgradesFrom=p.from_version,
        artifacts={p.image.name: t.digest_record(p.image), p.source_zip.name: t.digest_record(p.source_zip)},
        image={"file": p.image.name, "sha256": build["sha256"], "bytes": len(image), "slotBytes": t.APP_SIZE,
               "headroomBytes": t.APP_SIZE - len(image), "cc4Bytes": t.CC4_IMAGE_BYTES,
               "deltaFromCc4Bytes": len(image) - t.CC4_IMAGE_BYTES, "previousBytes": p.from_image_bytes,
               "deltaFromPreviousBytes": len(image) - p.from_image_bytes, "containsVersion": True},
        sourceFiles=sources,
        sourceListing=("git ls-files --cached --others --exclude-standard (minus .vscode/, and the generated "
                       "compile_commands.json and *.d in the firmware root)"),
        sourceFilesMissingFromWorkTree=missing, checkoutHead=head, changedFromCc4=changed,
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
                              ": flashed only when the hardware window steps down to it (firmware/BUILD-cc5.4.md).")
                           if p.binary else "")))
    if p.binary:
        manifest["binary"] = binary_record(p, build)
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
