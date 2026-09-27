"""Prepare the current release's app-only install of one binary (nanod_cc5_tooling.CURRENT: 1.0.0-cc5.3 ->
1.0.0-cc5.4; --binary D (default) or E, the active fix binaries of the PRESENTATION_V5 12.6 ladder; the retired
A, B and C are refused by argparse, exit 2, nothing written) from the fresh pre-install 4 MB backup or, after a
failed binary's rollback, from the step-down base; host-side only (no device).

Checks (any failure stops before anything is written):
  * the backup (backups/nanod-cc5.3-before-cc5.4-full.bin, one backup for every binary) is 4,194,304 B
    and matches diagnostics/cc5.4-backup.json (after a cc5.4 rollback that record is the backup step's
    confirmation that a fresh read is byte-identical to it);
  * the partition table (parsed, MD5 row checked) and OTA data equal the original backup;
    OTA still selects app0;
  * app0 (0x10000, 0x140000) holds the installed release's image (1.0.0-cc5.3, SHA-256
    f1cd05a2...) and, when its install record is available, is byte-identical to the app0 that
    install verified (backups/nanod-cc5.3-expected-full.bin, SHA-256 86759e50..., recorded in
    diagnostics/cc5.3-preparation.json);
  * firmware/manifest.json is the installed release's record (byte-identical to
    firmware/manifest-cc5.3.json, which package_nanod_cc5.py kept when it packaged cc5.4);
  * the binary's image matches its manifest (manifest-1.0.0-cc5.4-D.json and -E.json for D and E;
    manifest-1.0.0-cc5.4.json, -B.json and -C.json were A's, B's and C's; UNFLASHED, naming that binary), is an
    ESP image containing its version, fits app0 and carries the binary's R5 marker and, for D and E, its build
    marker "cc-build-binary:<n>" (tooling.binary_image_problems);
  * the before-inventory (argument) reports firmware 1.0.0-cc5.3 and presentation 4.
Then writes the rollback app0 (backups/nanod-cc5.3-before-cc5.4-active-app.bin, the same for every binary;
an identical existing file is kept), the binary's expected full image (backups/nanod-cc5.4-expected-full.bin,
nanod-cc5.4-B-expected-full.bin, nanod-cc5.4-C-expected-full.bin: the backup with the binary at app0 and the
rest of its last 4 KB sector erased) and its preparation record (diagnostics/cc5.4-D-preparation.json,
cc5.4-E-preparation.json; A's, B's and C's were cc5.4-preparation.json, cc5.4-B- and cc5.4-C-preparation.json;
an older one is kept as *.superseded-*). Every binary
can be prepared right after the backup, before any write. The record names the image the expected image
follows from ("baseKind", "baseFile", "baseSha256": the pre-install backup) next to the backup the rollback
restores ("beforeFile", "beforeSha256").

--step-down-base (a step-down, PRESENTATION_V5 12.6; firmware/BUILD-cc5.4.md): the failed binary's verified
rollback may leave drift in nvs, spiffs or coredump (a core dump written by a panic), so the device no longer
equals the locked backup. After backup_nanod_cc5.py --step-down, the next binary is prepared from the
release's step-down base instead (tooling.load_step_down_base: diagnostics/cc5.4-step-down-base.json passed,
the file's SHA-256, the locked backup still recorded by cc5.4-backup.json, and every critical region of the
base byte-identical to it). Every check above runs on the base; the rollback app0 is still the locked
backup's (the same bytes); the expected image is the base with the binary at app0; the record says
"baseKind": "step-down base" with the base's file and SHA-256 and the data regions that changed, while
"beforeFile" / "beforeSha256" stay the locked backup (the rollback's reference). install_nanod_cc5.py then
verifies the device against the base before it writes. The history files of earlier installs
(backups/nanod-cc4-before-cc5-*.bin, nanod-cc5.2-before-cc5.3-*.bin, their expected images,
diagnostics/cc5-*.json and cc5.3-*.json) are only read, never written.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402


def fail(message):
    raise SystemExit(f"STOP: {message}. Nothing was written.")


def write_artifact(path, data):
    """Write a derived artifact; an identical existing file is kept, a different one archived."""
    if path.exists():
        if path.read_bytes() == data:
            return None
        archived = t.archive_existing(path)
    else:
        archived = None
    t.write_new_bytes(path, data)
    return archived


def from_app0_record(p, before, offset, size):
    """The installed release's app0 against the image its install verified, when that record exists."""
    if not p.from_expected_full.is_file():
        return "not available"
    try:
        record = t.load_json(p.from_preparation)
    except (OSError, ValueError):
        fail(f"{p.from_preparation.name} is not readable")
    expected = p.from_expected_full.read_bytes()
    sha = t.sha256_bytes(expected)
    if sha != record.get("expectedSha256") or (p.from_expected_sha256 and sha != p.from_expected_sha256):
        fail(f"{p.from_expected_full.name} does not match {p.from_preparation.name}")
    if before[offset:offset + size] != expected[offset:offset + size]:
        fail(f"app0 differs from the app0 the {p.from_version} installation verified")
    return f"app0 byte-identical to {p.from_expected_full.name}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before-inventory", required=True,
                        help="inventory file name in backups/ recorded just before entering the bootloader")
    choices = t.binary_choices()
    if choices:
        parser.add_argument("--binary", choices=choices, default=choices[0],
                            help=f"the PRESENTATION_V5 12.6 binary to prepare (default {choices[0]})")
    parser.add_argument("--step-down-base", action="store_true",
                        help="prepare from the release's step-down base (backup_nanod_cc5.py --step-down) instead of "
                             "the pre-install backup, after a failed binary's verified rollback")
    args = parser.parse_args(argv)
    t.console_utf8()
    p = t.CURRENT.binary_profile(getattr(args, "binary", None))
    if {p.rollback_app.name, p.expected_full.name, p.before_full.name} & t.history_backup_names(p):
        fail("a file this step writes belongs to another release's history")

    inventory_path = t.BACKUPS / Path(args.before_inventory).name
    if not inventory_path.is_file():
        fail(f"{inventory_path.name} is not in backups/")
    inventory = t.load_json(inventory_path)
    if inventory.get("settings", {}).get("firmwareVersion") != p.from_version:
        fail(f"the before-inventory does not report firmware {p.from_version}")
    if inventory.get("capabilities", {}).get("presentation") != p.from_presentation:
        fail(f"the before-inventory does not report presentation {p.from_presentation}")

    locked = p.before_full.read_bytes()             # the pre-install backup: what every rollback verifies against
    if len(locked) != t.FLASH_BYTES:
        fail("the fresh full backup is incomplete")
    backup = t.load_json(p.backup_report)
    before_sha = t.sha256_bytes(locked)
    if not backup.get("passed") or backup.get("sha256") != before_sha:
        fail(f"the backup file does not match diagnostics/{p.backup_report.name}")
    # The image the expected image follows from and the install verifies the device against first.
    before, base_kind, base_name, step_down = locked, t.PRE_INSTALL_ROLE, p.before_full.name, None
    if args.step_down_base:
        try:
            base_path, before, record = t.load_step_down_base(p)
        except ValueError as exc:
            fail(str(exc))
        base_kind, base_name = t.STEP_DOWN_ROLE, base_path.name
        step_down = {"record": p.step_down_report.name, "recordSha256": t.sha256_file(p.step_down_report),
                     "readUtc": record.get("startedUtc"),
                     "dataRegionsChangedSinceBackup": record.get("dataRegionsChangedSinceBackup")}

    original_manifest = t.load_json(t.ORIGINAL_MANIFEST)
    original = (t.BACKUPS / original_manifest["full_flash_file"]).read_bytes()
    if t.sha256_bytes(original) != original_manifest["full_flash_sha256"]:
        fail("the original full backup changed")
    table = slice(t.PARTITION_TABLE_OFFSET, t.PARTITION_TABLE_OFFSET + t.PARTITION_TABLE_SIZE)
    otadata = slice(t.OTADATA_OFFSET, t.OTADATA_OFFSET + t.OTADATA_SIZE)
    if before[table] != original[table]:
        fail("the partition table changed")
    if before[otadata] != original[otadata]:
        fail("the OTA selection changed")
    partitions = t.parse_partition_table(before[table])
    if t.layout_key(partitions) != t.layout_key(original_manifest["partitions"]):
        fail("the parsed partition layout differs from the original manifest")
    apps = sorted((q for q in partitions if q["type"] == 0 and 0x10 <= q["subtype"] <= 0x1F),
                  key=lambda q: q["subtype"])
    selection = t.ota_selection(before[otadata], len(apps))
    active = apps[selection["appIndex"]] if selection["appIndex"] is not None else apps[0]
    offset, size = active["offset"], active["size"]
    if (active["name"], offset, size) != ("app0", t.APP_OFFSET, t.APP_SIZE):
        fail("OTA does not select app0 at 0x10000/0x140000")

    # The installed (from) release: its image, its record, and the app0 its install verified.
    from_image = p.from_image.read_bytes()
    if t.sha256_bytes(from_image) != p.from_image_sha256 or len(from_image) != p.from_image_bytes:
        fail(f"{p.from_image.name} does not have the installed SHA-256 {p.from_image_sha256}")
    from_record = t.load_json(p.from_record)
    if (from_record.get("firmwareVersion") != p.from_version
            or from_record.get("artifacts", {}).get(p.from_image.name, {}).get("sha256") != p.from_image_sha256):
        fail(f"{p.from_record.name} is not the {p.from_version} record")
    if not t.ACTIVE_MANIFEST.is_file() or t.sha256_file(t.ACTIVE_MANIFEST) != t.sha256_file(p.from_record):
        fail(f"manifest.json is not the installed {p.from_version} record ({p.from_record.name}); run "
             "package_nanod_cc5.py while manifest.json is that record")
    if before[offset:offset + len(from_image)] != from_image:
        fail(f"app0 does not hold the verified {p.from_version} image")
    from_app0 = from_app0_record(p, before, offset, size)

    manifest = t.load_json(p.manifest)
    if manifest.get("firmwareVersion") != p.version or manifest.get("installationStatus") != "UNFLASHED":
        fail(f"{p.manifest.name} is not an UNFLASHED {p.version} package")
    if p.binary and (manifest.get("binary") or {}).get("name") != p.binary:
        fail(f"{p.manifest.name} does not package binary {p.binary}; run package_nanod_cc5.py --binary {p.binary}")
    candidate = p.image.read_bytes()
    if t.sha256_bytes(candidate) != manifest["artifacts"][p.image.name]["sha256"]:
        fail(f"{p.image.name} does not match its manifest")
    problems = t.app_image_problems(candidate, p.version, size) + t.binary_image_problems(candidate, p.binary)
    if problems:
        fail("; ".join(problems))

    expected, end = t.assemble_expected(before, candidate, offset, size)
    span = t.differing_span(expected, before)
    if span is not None and not (offset <= span[0] and span[1] <= end):
        fail(f"the expected image differs outside the {p.tag} sectors")
    unchanged = {}
    for partition in partitions:
        start, length = partition["offset"], partition["size"]
        if partition["name"] != active["name"]:
            if expected[start:start + length] != before[start:start + length]:
                fail(f"partition {partition['name']} would change")
            unchanged[partition["name"]] = t.sha256_bytes(before[start:start + length])
    rollback = locked[offset:offset + size]         # one rollback app0 for every binary: the locked backup's
    if rollback != before[offset:offset + size]:
        fail(f"app0 of {base_name} differs from app0 of the locked {p.before_full.name}")
    archived = {"rollback": write_artifact(p.rollback_app, rollback),
                "expected": write_artifact(p.expected_full, bytes(expected))}
    if p.rollback_app.read_bytes() != rollback or p.expected_full.read_bytes() != expected:
        fail("written artifacts did not read back identically")

    report = dict(
        firmwareVersion=p.version, fromVersion=p.from_version, backupRole=backup.get("role"),
        beforeFile=p.before_full.name, beforeSha256=before_sha,
        baseKind=base_kind, baseFile=base_name, baseSha256=t.sha256_bytes(before), stepDown=step_down,
        rollbackFile=p.rollback_app.name, rollbackSha256=t.sha256_bytes(rollback), rollbackBytes=len(rollback),
        rollbackStartsWithFromImage=True, fromImageFile=p.from_image.name, fromImageSha256=p.from_image_sha256,
        fromApp0Check=from_app0, fromRecord=p.from_record.name, fromRecordSha256=t.sha256_file(p.from_record),
        applicationOffset=offset, applicationSize=size, candidateFile=p.image.name,
        candidateSha256=t.sha256_bytes(candidate), candidateBytes=len(candidate),
        binary=p.binary, buildFlags=list(p.build_flags) if p.binary else None, manifestFile=p.manifest.name,
        erasedStart=offset, erasedEndExclusive=end, expectedFile=p.expected_full.name,
        expectedSha256=t.sha256_bytes(expected), unchangedPartitionsSha256=unchanged,
        partitionTableUnchanged=True, partitionTableChecksumValid=True, otaSelectionUnchanged=True,
        otaEntries=selection["entries"], activeApp=active["name"],
        beforeInventory=inventory_path.name, beforeFirmware=p.from_version, beforePresentation=p.from_presentation,
        requiredPreWriteCheck=f"verify_flash 0x0 against {base_name} ({base_kind}) must pass before writing",
        archivedPrevious={k: v.name for k, v in archived.items() if v}, preparedUtc=t.utc_stamp(),
        flashWritten=False)
    t.write_json_evidence(p.preparation, report)
    which = f" binary {p.binary}" if p.binary else ""
    print(f"Prepared: {p.version}{which} {len(candidate)} B at 0x{offset:X}, erase to 0x{end:X}; "
          f"rollback {p.rollback_app.name} ({p.from_version}) sha256 {report['rollbackSha256']}")
    print(f"Expected image {p.expected_full.name} sha256 {report['expectedSha256']} (from the {base_kind} {base_name})")
    print("Next: install_nanod_cc5.py" + (f" --binary {p.binary}" if p.binary else "") + " (flash venv).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
