"""Read the complete 4 MB flash before the current release's install; read-only on the device.

The release is nanod_cc5_tooling.CURRENT: 1.0.0-cc5.3 installed -> 1.0.0-cc5.4. One backup serves every
binary of its PRESENTATION_V5 12.6 ladder (A, B and C install from the same cc5.3 bytes), so this script
has no --binary. Steps, all with --before no_reset --after no_reset_stub (the RAM stub stays loaded for
prepare/install; the chip stays in the ROM bootloader):
  1. flash_id: the MAC must be 12:34:56:78:9A:BC and the flash 4MB;
  2. read_flash 0x0 0x400000 -> a new backups/cc5.4-backup-read-<UTC>.bin.partial (4,194,304 B);
  3. verify_flash 0x0 against that file (device digest).
Runs only under tools/nanod-flash-venv with esptool 4.12.0, on the single MAC-matched
ROM port (enter it with nanod_enter_bootloader_v2.py).

What the verified read becomes depends on whether the pre-install backup of this release
(backups/nanod-cc5.3-before-cc5.4-full.bin) is still replaceable:

  * Unlocked (no write of any binary of this release was ever attempted: no cc5.4-flash-checks*.json,
    cc5.4-B-flash-checks*.json or cc5.4-C-flash-checks*.json with writeAttempted, no cc5.4[-B|-C]-rollback*.json,
    and manifest-1.0.0-cc5.4.json, -B.json and -C.json still UNFLASHED or absent; tooling.backup_locks) and
    app0 of the read holds the installed release's image (1.0.0-cc5.3, SHA-256 f1cd05a2...): the read
    becomes the pre-install backup (an existing one is renamed *.superseded-<UTC>.bin, never overwritten)
    and diagnostics/cc5.4-backup.json is written. Exit 0. NVS and the filesystem may have changed since
    the cc5.3 install, so this is always a fresh read, never a copy of an older image.
  * Locked, and the read is byte-identical to the locked backup, whose SHA-256
    diagnostics/cc5.4-backup.json records (the knob returned to exactly those bytes, as a
    verified cc5.4 -> cc5.3 rollback of any binary leaves it when no data region changed): the read is a
    valid CURRENT backup. The locked backup is never replaced; the read is kept as
    backups/nanod-cc5.3-confirm-read-<UTC>.bin and cc5.4-backup.json is superseded by a record with role
    "current backup (identical to the locked pre-install backup)" naming the same backup file and SHA-256.
    Exit 0.
  * Otherwise (locked and the read differs in any byte, or the read's app0 does not hold the
    installed release, or the backup record does not match the backup file): the locked backup
    stays in place and nothing is accepted. The read is kept as
    backups/nanod-diagnostic-full-<UTC>.bin with diagnostics/cc5.4-backup-diagnostic-read-<UTC>.json,
    and the script exits 3.

--step-down (the PRESENTATION_V5 12.6 step-down, lead ruling R-m; firmware/BUILD-cc5.4.md): after the failed
binary's verified rollback to cc5.3 the data regions (nvs, spiffs, coredump) may differ from the locked
backup, for example by the core dump a panic or task_wdt reset wrote; the rollback reports that drift and
never rewrites it. This mode is only for a locked backup (a binary's write was attempted; otherwise it refuses
before reading: run without --step-down) whose record still matches it. The same three steps read the knob;
then the read becomes the release's step-down base when every critical region (bootloader, partition table,
OTA data, app0, app1 and the gaps between partitions; tooling.region_differences) is byte-identical to the
locked backup and app0 holds the installed release. It is kept under its own name,
backups/nanod-cc5.3-step-down-base-<UTC>.bin, and recorded in diagnostics/cc5.4-step-down-base.json (role
"step-down base", its SHA-256, the locked backup's SHA-256 and the data regions that changed; an older record
is kept as *.superseded-*). Exit 0. The locked backup and cc5.4-backup.json are never replaced or rewritten.
prepare_nanod_cc5_install.py --binary <next> --step-down-base then builds the next binary's expected image
from the base, and install_nanod_cc5.py verifies the device against the base before it writes. A read whose
critical regions differ, or whose app0 does not hold the installed release, is kept as a diagnostic read as
above (exit 3).

The history backups of the other profiles (backups/nanod-cc4-before-cc5-*.bin and
nanod-cc5.2-before-cc5.3-*.bin, locked since their first write) are never written, renamed or replaced by
this script, and the records of earlier releases (diagnostics/cc5-backup*.json, cc5.3-backup*.json) are
never touched.

A failed run never replaces cc5.4-backup.json (nor cc5.4-step-down-base.json); its evidence goes to
diagnostics/cc5.4-backup-failed-<UTC>.json.

Exit codes: 0 a valid current backup (new pre-install backup, or a read identical to the
locked one) or, with --step-down, a step-down base; 1 failed or nothing sent (see the evidence);
3 read kept as a diagnostic read, the backup unchanged, do not prepare.
"""
import argparse
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402


def from_image_at_app0(profile, data):
    """True when app0 of `data` starts with the verified image of the installed (from) release."""
    image = profile.from_image
    if not image.is_file():
        return False
    raw = image.read_bytes()
    return (t.sha256_bytes(raw) == profile.from_image_sha256 and len(raw) == profile.from_image_bytes
            and data[t.APP_OFFSET:t.APP_OFFSET + len(raw)] == raw)


def locked_backup_state(profile):
    """(SHA-256 of the locked pre-install backup, list of problems that forbid confirming against it)."""
    problems = []
    if not profile.before_full.is_file():
        return None, [f"{profile.before_full.name} is missing"]
    sha = t.sha256_file(profile.before_full)
    try:
        record = t.load_json(profile.backup_report)
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict) or record.get("passed") is not True or record.get("sha256") != sha:
        problems.append(f"{profile.backup_report.name} does not record {profile.before_full.name} (SHA-256 {sha})")
    return sha, problems


def step_down_reference(profile, locks):
    """The locked pre-install backup's bytes for a --step-down read, or SystemExit before anything is sent:
    the backup must be locked (a binary's write was attempted), present, recorded and 4 MB with a readable
    partition table (the regions of the comparison come from it)."""
    if not locks:
        raise SystemExit(f"Refusing --step-down: no write of any {profile.tag} binary was attempted, so the pre-"
                         f"{profile.tag} backup is not locked; run backup_nanod_cc5.py without --step-down. "
                         "Nothing was read.")
    _, problems = locked_backup_state(profile)
    if problems:
        raise SystemExit("Refusing --step-down: " + "; ".join(problems) + ". Nothing was read.")
    locked = profile.before_full.read_bytes()
    try:
        t.region_differences(locked, locked)
    except ValueError as exc:
        raise SystemExit(f"Refusing --step-down: {profile.before_full.name} cannot be split into regions ({exc}). "
                         "Nothing was read.") from None
    return locked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--read-timeout", type=int, default=900, help="seconds allowed for the 4 MB read")
    parser.add_argument("--step-down", action="store_true",
                        help="after a failed binary's verified rollback (PRESENTATION_V5 12.6): keep a read whose "
                             "critical regions equal the locked backup as the step-down base for the next binary")
    args = parser.parse_args(argv)
    t.console_utf8()
    environment = t.assert_flash_environment()  # before any command
    p = t.CURRENT
    if p.before_full.name in t.history_backup_names(p):
        raise SystemExit(f"Refusing: {p.before_full.name} is another release's locked history backup")
    locks = t.backup_locks(p)
    locked = step_down_reference(p, locks) if args.step_down else None   # nothing sent above this line
    port = t.find_rom_port()
    stamp = t.utc_stamp()
    partial = t.unique_path(p.backup_read_partial(stamp))
    locked_role = f"current backup (identical to the locked pre-{p.tag} backup)"
    report = {"startedUtc": stamp, "firmwareVersion": p.version, "fromVersion": p.from_version,
              "mode": "step-down" if args.step_down else "backup",
              "environment": environment, "port": port, "chipMac": t.CHIP_MAC, "backupLocks": list(locks),
              "role": "pending" if locks else f"pre-{p.tag} backup",
              "partialFile": partial.name, "file": None, "passed": False, "steps": []}
    if args.step_down:
        print(f"Step-down read. The pre-{p.tag} backup is locked (" + "; ".join(locks) + ") and is never replaced: "
              f"this read becomes the step-down base only if its critical regions are byte-identical to "
              f"{p.before_full.name}; otherwise it is kept as a diagnostic read.", flush=True)
    elif locks:
        print(f"The pre-{p.tag} backup is locked (" + "; ".join(locks) + "). It is never replaced: this read is "
              f"accepted only if it is byte-identical to {p.before_full.name}; otherwise it is kept as a "
              "diagnostic read.", flush=True)
    esptool = t.Esptool(port, report, p.backup_log_prefix)
    code = 1
    try:
        ok, output = esptool("identity", ["flash_id"])
        problems = t.identity_problems(output) if ok else ["flash_id failed"]
        if problems:
            raise SystemExit("Identity check failed: " + "; ".join(problems) + ". Nothing was read.")
        report["identityVerified"] = True
        t.BACKUPS.mkdir(parents=True, exist_ok=True)
        ok, _ = esptool("read", ["read_flash", "0x0", hex(t.FLASH_BYTES), str(partial), "--no-progress"],
                        timeout=args.read_timeout)
        if not ok or not partial.is_file():
            raise SystemExit("read_flash failed; see the log. The device was not written.")
        data = partial.read_bytes()
        if len(data) != t.FLASH_BYTES:
            raise SystemExit(f"Backup is {len(data)} B, expected {t.FLASH_BYTES}")
        ok, _ = esptool("verify", ["verify_flash", "0x0", str(partial)])
        if not ok:
            raise SystemExit("verify_flash of the fresh backup failed; do not continue.")
        read_sha = hashlib.sha256(data).hexdigest()
        report.update(bytes=len(data), sha256=read_sha, md5=hashlib.md5(data).hexdigest(),
                      verifiedAgainstDevice=True,
                      partitionTableMatchesOriginal=(t.ORIGINAL_PARTITIONS.is_file() and data[
                          t.PARTITION_TABLE_OFFSET:t.PARTITION_TABLE_OFFSET + t.PARTITION_TABLE_SIZE]
                          == t.ORIGINAL_PARTITIONS.read_bytes()),
                      fromImageAtApp0=from_image_at_app0(p, data), fromImageSha256=p.from_image_sha256)
        confirmed = step_down_base = False
        if args.step_down:
            # Compared region by region with the locked backup: only the data regions may differ.
            critical, drift = t.region_differences(locked, data)
            report.update(lockedBackupFile=p.before_full.name, lockedBackupSha256=t.sha256_bytes(locked),
                          identicalToLockedBackup=data == locked, criticalRegionsIdenticalToLockedBackup=not critical,
                          criticalRegionsDiffering=critical, dataRegionsChangedSinceBackup=drift)
            step_down_base = not critical and report["fromImageAtApp0"]
            if not step_down_base:
                reasons = [f"the critical region(s) {', '.join(critical)} differ from the locked {p.before_full.name}"
                           ] if critical else []
                if not report["fromImageAtApp0"]:
                    reasons.append(f"app0 of this read does not hold the {p.from_version} image")
                report["notConfirmedBecause"] = reasons
        elif locks:
            locked_sha, locked_problems = locked_backup_state(p)
            identical = locked_sha is not None and read_sha == locked_sha and data == p.before_full.read_bytes()
            report["identicalToLockedBackup"] = identical
            report["lockedBackupSha256"] = locked_sha
            confirmed = identical and report["fromImageAtApp0"] and not locked_problems
            if not confirmed:
                reasons = list(locked_problems)
                if not identical:
                    reasons.append(f"the read differs from the locked {p.before_full.name}")
                if not report["fromImageAtApp0"]:
                    reasons.append(f"app0 of this read does not hold the {p.from_version} image")
                report["notConfirmedBecause"] = reasons
        elif not report["fromImageAtApp0"]:
            locks.append(f"app0 of this read does not hold the {p.from_version} image")
            report["backupLocks"] = list(locks)
        if step_down_base:
            # The locked backup and its record stay exactly as they are; the read is the next install's base.
            base = t.unique_path(p.step_down_base(stamp))
            partial.rename(base)
            report.update(role=t.STEP_DOWN_ROLE, file=base.name, passed=True)
            code = 0
            print(f"Step-down base {base.name}: {len(data)} B sha256 {read_sha}; every critical region equals the "
                  f"locked {p.before_full.name}, which stays the backup"
                  + (f"; data regions changed since it: {', '.join(drift)} (kept as read)" if drift else "") + ".")
            print("The chip stays in the ROM bootloader with the stub loaded. Next: prepare_nanod_cc5_install.py "
                  "--binary <next> --step-down-base")
        elif confirmed:
            # The locked backup stays exactly as it is; this read only proves the knob still
            # holds those bytes. Keep it under its own name and supersede the backup record.
            kept = t.unique_path(p.confirm_read(stamp))
            partial.rename(kept)
            report.update(role=locked_role, file=p.before_full.name, confirmingRead=kept.name, passed=True)
            code = 0
            print(f"Current backup confirmed: the fresh 4 MB read is byte-identical to the locked {p.before_full.name} "
                  f"(sha256 {read_sha}). It stays the backup; the read is kept as {kept.name}.")
            print("The chip stays in the ROM bootloader with the stub loaded. Next: prepare_nanod_cc5_install.py")
        elif locks:
            target = t.unique_path(t.BACKUPS / f"nanod-diagnostic-full-{stamp}.bin")
            partial.rename(target)
            report.update(role="diagnostic read", file=target.name, passed=True)
            code = 3
            print(f"Diagnostic read {target.name}: {len(data)} B sha256 {read_sha}")
            print(f"Not a valid current {'step-down base' if args.step_down else 'backup'}: {p.before_full.name} is "
                  "unchanged. Do not run prepare on this read" + (": " + "; ".join(report["notConfirmedBecause"])
                                                                  if report.get("notConfirmedBecause") else "") + ".")
        else:
            report["archivedPrevious"] = str(t.archive_existing(p.before_full) or "") or None
            partial.rename(p.before_full)
            report.update(file=p.before_full.name, passed=True)
            code = 0
            print(f"Backup {p.before_full.name}: {len(data)} B sha256 {read_sha} ({p.from_version} at app0)")
            print("The chip stays in the ROM bootloader with the stub loaded. Next: prepare_nanod_cc5_install.py")
    finally:
        report["deviceWritten"] = False
        if code == 0 and args.step_down:
            t.write_json_evidence(p.step_down_report, report)   # the backup record is never touched in a step-down
        elif code == 0:
            t.write_json_evidence(p.backup_report, report)   # the backup record changes only with a valid backup
        else:
            kind = "diagnostic-read" if code == 3 else "failed"
            report["evidence"] = t.write_new_json(t.DIAGNOSTICS / f"{p.prefix}-backup-{kind}-{stamp}.json", report).name
            print(f"Evidence: {report['evidence']} ({p.backup_report.name} unchanged)")
    return code


if __name__ == "__main__":
    sys.exit(main())
