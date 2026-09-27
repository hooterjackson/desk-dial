"""Roll the knob back (app0 only) to the release a cc5.x install replaced, and restore its record.

--to cc5.3   cc5.4 -> cc5.3 (firmware/BUILD-cc5.4.md, "Firmware rollback, cc5.4 -> cc5.3"): app0 from
             backups/nanod-cc5.3-before-cc5.4-active-app.bin, full image against
             backups/nanod-cc5.3-before-cc5.4-full.bin, record firmware/manifest-cc5.3.json. cc5.4 is
             staged as the PRESENTATION_V5 12.6 ladder, and every binary installs from that same backup:
             --binary A|B|C|D|E names the binary being rolled back (every binary of the ladder, the retired
             A, B and C included, so any binary ever written can be rolled back), whose preparation record
             gives the hashes (diagnostics/cc5.4-preparation.json for A, cc5.4-<X>-preparation.json for the
             others) and whose evidence it writes (diagnostics/cc5.4-rollback.json, cc5.4-<X>-rollback.json).
             Without --binary it is the binary whose flash record with a write attempt is the newest
             (tooling.newest_written_binary), else A; an unreadable cc5.4 flash record makes --binary
             required (nothing sent). This is also the first half of the step-down between binaries (A -> B,
             A -> C, B -> C, and after A's 2026-09-26 rollback A -> D, D -> E): roll the failed binary back
             to cc5.3, then take a
             step-down base (backup_nanod_cc5.py --step-down: the rollback returns the critical regions
             exactly, but a failing binary may have written nvs, spiffs or coredump, which it reports as
             dataRegionsChangedSinceBackup and never rewrites), prepare the next binary from it
             (--step-down-base) and install it. A binary installed from a step-down base is rolled back the
             same way, against the same locked pre-cc5.4 backup.
--to cc5.2   cc5.3 -> cc5.2 (firmware/RECOVERY.md section 6): app0 from
             backups/nanod-cc5.2-before-cc5.3-active-app.bin, full image against
             backups/nanod-cc5.2-before-cc5.3-full.bin, hashes from diagnostics/cc5.3-preparation.json,
             record firmware/manifest-cc5.2.json, evidence diagnostics/cc5.3-rollback.json.
--to cc4     cc5 -> cc4, the history path (RECOVERY.md section 5, BUILD-cc5.md): app0 from
             backups/nanod-cc4-before-cc5-active-app.bin, full image against
             backups/nanod-cc4-before-cc5-full.bin, hashes from diagnostics/cc5-preparation.json,
             record firmware/manifest-cc4.json, evidence diagnostics/cc5-rollback.json. It restores
             cc4 after any cc5.x (1.0.0-cc5, cc5.1, cc5.2, cc5.3 or cc5.4), whose installs all started from
             it.
Without --to it is --to cc4, exactly as those history documents run it, but only while the records
never show 1.0.0-cc5.3 written to the knob (tooling.release_write_evidence: a cc5.3-flash-checks record
with a write attempt, or manifest-1.0.0-cc5.3.json INSTALLED or ROLLED_BACK). From then on a missing
--to is refused before anything is sent (exit 2, usage error): pass --to cc5.3 (from cc5.4), --to cc5.2
(from cc5.3, RECOVERY.md section 6) or --to cc4 explicitly. The evidence's "fromVersion" is the newest
release the records show written since the restored backup was read ("writeEvidence" lists why), so a
cc4 rollback from a cc5.3 knob never claims to start from cc5.2.

Runs only under tools/nanod-flash-venv with esptool 4.12.0, on the single MAC-matched ROM
port (enter it first with nanod_enter_bootloader_v2.py). Every step uses
--before no_reset --after no_reset_stub until the final reset:
  1. flash_id                         MAC 12:34:56:78:9A:BC and 4MB flash
  2. read_flash of the partition table and OTA data; both must equal the pre-install backup
  3. write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 <rollback app0>
  4. verify_flash 0x10000 <that file>              (app0)
  5. verify_flash 0x0 <pre-install backup>          (full image)
     If 5 fails, each region is verified on its own: the bootloader, partition table,
     OTA data, app0 and app1 must match; nvs/spiffs/coredump drift (settings saved or a
     crash dump written since the backup) is reported, not rewritten.
  6. read_mac --after hard_reset      only when 3, 4 and the critical regions passed
Never erase_flash, never a filesystem upload, never a full-image write.

Records: once the flash is verified (or with --records-only), firmware/manifest.json is
restored from the target's record (the previous manifest.json is kept as
manifest-at-<cc5.4[-X]|cc5.3|cc5>-rollback-<UTC>.json), every INSTALLED manifest of a release this
rollback removes (for cc5.4: of any of its binaries) is marked ROLLED_BACK, and the rollback evidence
is written.
--records-only skips the device (use it only after the manual esptool rollback in
firmware/RECOVERY.md has verified app0 and the full image). Desktop rollback is separate:
  --to cc5.3: .\\Install-Desktop.ps1 -Bundle desktop-dist-v6 -Mirror   (companion quit first)
  --to cc5.2: .\\Install-Desktop.ps1 -Bundle desktop-dist-v3 -Mirror
  --to cc4:   .\\Install-Desktop.ps1 -Bundle desktop-dist-v2 -Mirror

Exit codes (the "outcome" field in the rollback evidence says the same). The script's closing line follows the
outcome (one message each: restored and reset, records only, the reset retry command, stopped before writing, or
"did NOT complete" for exit 4 alone), and a note on changed data regions follows it whenever the records were
restored:
  0  ROLLED_BACK_VERIFIED_RESET (or RECORDS_ONLY): verified, reset confirmed, records restored.
  1  Nothing was sent to the device: wrong environment, a file hash, the target record, or no
     single matching ROM port.
  2  STOPPED_BEFORE_WRITE: identity, partition table or OTA data did not match (or a usage
     error). Nothing was written, no reset; the installed release is still in app0.
  4  *_NO_RESET: a write or verify failed after the write started. The chip was NOT reset.
     Do not reset or power-cycle; follow RECOVERY.md (manual commands).
  5  ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED: the target verified in flash, records restored, but
     the reset was not confirmed; the exact retry command is printed.
  6  The device rollback verified and reset, but manifest.json was NOT restored
     (recordsError); fix the cause and run --records-only.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402

WRITE_ARGS = ["write_flash", "--flash_mode", "keep", "--flash_freq", "keep", "--flash_size", "keep"]
EXIT_CODES = {"ROLLED_BACK_VERIFIED_RESET": 0, "RECORDS_ONLY": 0, "STOPPED_NOTHING_SENT": 1,
              "STOPPED_BEFORE_WRITE": 2, "WRITE_FAILED_NO_RESET": 4, "APP0_VERIFY_FAILED_NO_RESET": 4,
              "CRITICAL_REGION_MISMATCH_NO_RESET": 4, "FAILED_AFTER_WRITE_NO_RESET": 4,
              "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED": 5}
RECORD_OUTCOMES = ("ROLLED_BACK_VERIFIED_RESET", "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED", "RECORDS_ONLY")


def removed_releases(p):
    """Releases whose install this rollback undoes (their INSTALLED manifests become ROLLED_BACK):
    the profile's release and every later cc5.x profile (a cc4 rollback also undoes cc5.3 and cc5.4)."""
    return [q.version for q in [p.base, *t.later_profiles(p)]]


def removed_manifests(p):
    """The release manifests this rollback may mark ROLLED_BACK: every binary of every removed release."""
    return [variant.manifest for q in [p.base, *t.later_profiles(p)] for variant in q.variants()]


def choose_binary(parser, target, binary):
    """(profile, how it was chosen) for the rollback target `target`: its binary `binary` (--binary), else
    the newest written binary from the records, else A. Only a ladder release has binaries; --binary
    anywhere else, or an unknown newest binary, is a usage error (exit 2, nothing sent)."""
    p = t.ROLLBACK_TARGETS[target]
    if not p.pipeline_binaries():
        if binary is not None:
            parser.error(f"--binary applies only to a release built as the PRESENTATION_V5 12.6 ladder "
                         f"(--to {next(k for k, v in t.ROLLBACK_TARGETS.items() if v.pipeline_binaries())}); "
                         "nothing was sent")
        return p, None
    if binary is not None:
        return p.binary_profile(binary), "--binary"
    newest, record, problems = t.newest_written_binary(p)
    if problems:
        parser.error(f"--binary is required: {'; '.join(problems)}, so the records cannot tell which {p.tag} binary "
                     f"was written last. Pass --binary {'|'.join(p.pipeline_binaries())}. Nothing was sent.")
    if newest is None:
        return p.binary_profile(None), f"default (no {p.tag} flash record shows a write)"
    return p.binary_profile(newest), f"records (newest write: {record})"


def later_write_evidence(p):
    """{version: reasons} for every later release whose records show it written to the knob."""
    found = {q.version: t.release_write_evidence(q) for q in t.later_profiles(p)}
    return {version: reasons for version, reasons in found.items() if reasons}


def default_target(parser):
    """--to omitted: the history default (cc4) while no later release than cc5.2 was ever written;
    afterwards the rollback target must be named (nothing is sent; argparse exits 2)."""
    later = later_write_evidence(t.ROLLBACK_TARGETS[t.DEFAULT_ROLLBACK_TARGET])
    if later:
        why = "; ".join(reason for reasons in later.values() for reason in reasons)
        parser.error(f"--to is required: the records show {', '.join(later)} written to the knob ({why}). "
                     "Pass --to cc5.3 to restore 1.0.0-cc5.3 from cc5.4, --to cc5.2 to restore 1.0.0-cc5.2 "
                     "(RECOVERY.md section 6), or --to cc4 to go back to 1.0.0-cc4 (RECOVERY.md section 5). "
                     "Nothing was sent.")
    return t.DEFAULT_ROLLBACK_TARGET


def check_files(prep, p=None):
    p = p or t.CURRENT
    if t.sha256_file(p.rollback_app) != prep["rollbackSha256"]:
        raise SystemExit(f"{p.rollback_app.name} does not match {p.preparation.name}; nothing was sent")
    if t.sha256_file(p.before_full) != prep["beforeSha256"]:
        raise SystemExit(f"{p.before_full.name} does not match {p.preparation.name}; nothing was sent")
    image = p.from_image.read_bytes()
    if t.sha256_bytes(image) != p.from_image_sha256 or len(image) != p.from_image_bytes:
        raise SystemExit(f"The {p.from_version} image changed; nothing was sent")
    rollback = p.rollback_app.read_bytes()
    if len(rollback) != t.APP_SIZE or rollback[:p.from_image_bytes] != image:
        raise SystemExit(f"The rollback app0 does not hold the {p.from_version} image; nothing was sent")


def check_record_inputs(p=None):
    """The records restored after the device rollback must be restorable before anything is sent."""
    p = p or t.CURRENT
    record = t.load_json(p.from_record)
    if (record.get("firmwareVersion") != p.from_version
            or record.get("artifacts", {}).get(p.from_image.name, {}).get("sha256") != p.from_image_sha256):
        raise SystemExit(f"{p.from_record.name} is not the {p.from_version} record; nothing was sent")
    if not t.ACTIVE_MANIFEST.is_file():
        raise SystemExit("firmware/manifest.json is missing; nothing was sent")


def read_compare(esptool, name, offset, size, expected, workdir):
    target = workdir / f"current-{name}.bin"
    ok, _ = esptool(f"read-{name}", ["read_flash", hex(offset), hex(size), str(target), "--no-progress"])
    return ok and target.is_file() and target.read_bytes() == expected


def verify_regions(esptool, before, workdir, report):
    """Verify each flash region separately; returns True when every critical region matches."""
    partitions = t.parse_partition_table(before[t.PARTITION_TABLE_OFFSET:t.PARTITION_TABLE_OFFSET + t.PARTITION_TABLE_SIZE])
    results, critical_ok = [], True
    for name, start, end in t.flash_regions(partitions):
        piece = workdir / f"region-{name}.bin"
        piece.write_bytes(before[start:end])
        ok, _ = esptool(f"verify-{name}", ["verify_flash", hex(start), str(piece)])
        critical = t.is_critical_region(name)
        results.append({"region": name, "offset": start, "size": end - start, "matches": ok, "critical": critical})
        critical_ok &= ok or not critical
    report["regions"] = results
    report["dataRegionsChangedSinceBackup"] = [r["region"] for r in results if not r["matches"] and not r["critical"]]
    return critical_ok


def restore_records(report, p=None):
    p = p or t.CURRENT
    check_record_inputs(p)
    kept = t.unique_path(p.manifest_before_rollback(t.utc_stamp()))
    shutil.copyfile(t.ACTIVE_MANIFEST, kept)
    shutil.copyfile(p.from_record, t.ACTIVE_MANIFEST)
    if t.sha256_file(t.ACTIVE_MANIFEST) != t.sha256_file(p.from_record):
        raise SystemExit("manifest.json restore did not verify")
    report["manifestRestored"] = {"from": p.from_record.name, "previousKeptAs": kept.name}
    marked = []
    for path in removed_manifests(p):
        if not path.is_file():
            continue
        manifest = t.load_json(path)
        if manifest.get("installationStatus") == "INSTALLED":
            manifest.update(installationStatus="ROLLED_BACK", rollback=f"diagnostics/{p.rollback_report.name}",
                            hardwareStatus=f"Rolled back to {p.from_tag} (app0 restored from the {p.backup_role}).")
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            marked.append(path.name)
    if marked:
        report["manifestsMarkedRolledBack"] = marked


def device_rollback(esptool, report, before, workdir, p=None):
    """Steps 1-6; returns the outcome. Resets only after the write and every verify passed."""
    p = p or t.CURRENT
    ok, output = esptool("identity", ["flash_id"])
    problems = t.identity_problems(output) if ok else ["flash_id failed"]
    if problems:
        report["reason"] = "; ".join(problems)
        return "STOPPED_BEFORE_WRITE"
    table = before[t.PARTITION_TABLE_OFFSET:t.PARTITION_TABLE_OFFSET + t.PARTITION_TABLE_SIZE]
    otadata = before[t.OTADATA_OFFSET:t.OTADATA_OFFSET + t.OTADATA_SIZE]
    report["partitionTableUnchanged"] = read_compare(esptool, "partitions", t.PARTITION_TABLE_OFFSET,
                                                     t.PARTITION_TABLE_SIZE, table, workdir)
    report["otaSelectionUnchanged"] = read_compare(esptool, "otadata", t.OTADATA_OFFSET, t.OTADATA_SIZE, otadata, workdir)
    if not (report["partitionTableUnchanged"] and report["otaSelectionUnchanged"]):
        report["reason"] = "partition table or OTA data differs from the pre-install backup; inspect manually"
        return "STOPPED_BEFORE_WRITE"
    report["writeAttempted"] = True
    ok, _ = esptool("write", [*WRITE_ARGS, hex(t.APP_OFFSET), str(p.rollback_app)])
    report["flashWritten"] = ok
    if not ok:
        return "WRITE_FAILED_NO_RESET"
    ok, _ = esptool("verify-app0", ["verify_flash", hex(t.APP_OFFSET), str(p.rollback_app)])
    report["app0Verified"] = ok
    if not ok:
        return "APP0_VERIFY_FAILED_NO_RESET"
    ok, _ = esptool("verify-full", ["verify_flash", "0x0", str(p.before_full)])
    report["fullImageMatchesBackup"] = ok
    if not ok and not verify_regions(esptool, before, workdir, report):
        return "CRITICAL_REGION_MISMATCH_NO_RESET"
    report["verified"] = True
    report["resetAttempted"] = True
    ok, output = esptool("reset", ["read_mac"], after="hard_reset")
    report["reset"] = t.reset_confirmed(ok, output)
    return "ROLLED_BACK_VERIFIED_RESET" if report["reset"] else "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED"


def outcome_after_exception(report):
    """What an unexpected exception leaves, from the flags; nothing here resets."""
    if report.get("verified"):
        return "ROLLED_BACK_VERIFIED_RESET" if report["reset"] else "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED"
    if report["writeAttempted"]:
        return "FAILED_AFTER_WRITE_NO_RESET"
    return "STOPPED_BEFORE_WRITE" if report["steps"] else "STOPPED_NOTHING_SENT"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", choices=sorted(t.ROLLBACK_TARGETS), default=None,
                        help="the release to restore: cc5.3 (from cc5.4), cc5.2 (from cc5.3, RECOVERY.md "
                             "section 6) or cc4 "
                             f"(history, RECOVERY.md section 5; the default ({t.DEFAULT_ROLLBACK_TARGET}) only "
                             "while the records never show 1.0.0-cc5.3 written)")
    parser.add_argument("--records-only", action="store_true",
                        help="skip the device; only restore manifest.json and write the rollback evidence "
                             "(after a verified manual rollback)")
    ladder = sorted({b for q in t.ROLLBACK_TARGETS.values() for b in q.pipeline_binaries()})
    parser.add_argument("--binary", choices=ladder or None, default=None,
                        help="with --to cc5.3: the cc5.4 binary (PRESENTATION_V5 12.6 ladder, A..E, the retired "
                             "ones included) being rolled back, whose preparation and evidence names are used "
                             "(default: the binary the records show written last, else A)")
    args = parser.parse_args(argv)
    if args.to is None:
        args.to = default_target(parser)
    p, binary_source = choose_binary(parser, args.to, args.binary)
    t.console_utf8()
    environment = t.assert_flash_environment()  # before any command
    written = later_write_evidence(p)
    try:
        prep = t.load_json(p.preparation)
    except FileNotFoundError:
        raise SystemExit(f"{p.preparation.name} is missing: {p.label} was never prepared, so it cannot have been "
                         "installed. Pass the --binary that was installed. Nothing was sent") from None
    check_files(prep, p)
    check_record_inputs(p)
    before = p.before_full.read_bytes()
    port = workdir = None
    if not args.records_only:
        port = t.find_rom_port()
        base = workdir = p.rollback_workdir(t.utc_stamp())
        for n in range(1, 1000):
            if not workdir.exists():
                break
            workdir = base.with_name(f"{base.name}-{n}")
        workdir.mkdir(parents=True, exist_ok=False)  # exit 1 above this line: nothing was sent
    report = {"startedUtc": t.utc_stamp(), "fromVersion": ([p.version, *written])[-1], "toVersion": p.from_version,
              "target": args.to, "undoesInstallsOf": removed_releases(p), "writeEvidence": written,
              **({"binary": p.binary, "binarySource": binary_source} if p.binary else {}),
              "environment": environment, "chipMac": t.CHIP_MAC, "port": port,
              "workdir": workdir.name if workdir else None,
              "rollbackFile": p.rollback_app.name, "rollbackSha256": prep["rollbackSha256"],
              "backupFile": p.before_full.name, "backupSha256": prep["beforeSha256"],
              "deviceRollbackPerformedByThisScript": not args.records_only, "writeAttempted": False,
              "flashWritten": False, "verified": False, "resetAttempted": False, "reset": False, "steps": [],
              "outcome": "STARTED"}
    try:
        esptool = None
        if args.records_only:
            outcome = "RECORDS_ONLY"
            report["note"] = ("Device rollback performed manually (RECOVERY.md, manual blocks); its esptool output "
                              "is not captured here.")
        else:
            esptool = t.Esptool(port, report, p.rollback_log_prefix)
            try:
                outcome = device_rollback(esptool, report, before, workdir, p)
            except Exception as exc:
                report["exception"] = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
                outcome = outcome_after_exception(report)
        report["outcome"] = outcome
        code = EXIT_CODES[outcome]
        if outcome in RECORD_OUTCOMES:
            try:
                restore_records(report, p)
            except (Exception, SystemExit) as exc:
                report["recordsError"] = f"{type(exc).__name__}: {exc}"
                code = 6 if code == 0 else code
                print(f"manifest.json was NOT restored ({report['recordsError']}). Fix the cause, then run "
                      f"rollback_nanod_cc5.py --to {args.to}" + (f" --binary {p.binary}" if p.binary else "")
                      + " --records-only.", flush=True)
        # One closing message per outcome (a clean ROLLED_BACK_VERIFIED_RESET never falls through to the failure
        # line, exit 6 included); the data-region note is printed on its own, after it, whatever the outcome was.
        if outcome == "ROLLED_BACK_VERIFIED_RESET":
            print(f"{p.from_tag} restored in app0, verified and reset. Next: boot sanity, device_inventory.py "
                  f"(expects {p.from_version}, presentation {p.from_presentation}), then optionally the desktop "
                  "rollback shown below.", flush=True)
        elif outcome == "RECORDS_ONLY":
            print("Records only: the device was not touched by this run.", flush=True)
        elif outcome == "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED":
            report["resetRetryCommand"] = t.print_reset_retry(esptool.port, p.from_tag)
        elif code == 2 or code == 1:
            print(f"Stopped before writing: {report.get('reason') or report.get('exception')}. Nothing was "
                  "written and the chip was not reset; the installed release is still in app0.", flush=True)
        else:
            print("Rollback did NOT complete; the chip was NOT reset. Do not reset or power-cycle. "
                  "Follow firmware/RECOVERY.md (manual commands).", flush=True)
        if outcome in RECORD_OUTCOMES and report.get("dataRegionsChangedSinceBackup"):
            print(f"Data regions changed since {p.before_full.name}, kept as they are: "
                  f"{', '.join(report['dataRegionsChangedSinceBackup'])}. A step-down to another binary reads a "
                  "step-down base first (backup_nanod_cc5.py --step-down, then prepare --step-down-base).", flush=True)
        return code
    finally:
        report["finishedUtc"] = t.utc_stamp()
        report["desktopRollback"] = (rf".\Install-Desktop.ps1 -Bundle {p.desktop_rollback_bundle} -Mirror "
                                     "(quit the companion first)")
        t.write_json_evidence(p.rollback_report, report)
        print(f"Evidence: {p.rollback_report}")


if __name__ == "__main__":
    sys.exit(main())
