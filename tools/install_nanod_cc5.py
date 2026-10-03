"""Install one binary of the current release (nanod_cc5_tooling.CURRENT: 1.0.0-cc5.4 over the installed
1.0.0-cc5.3; --binary D (default) or E, the active fix binaries of the PRESENTATION_V5 12.6 ladder; the retired
A, B and C are refused by argparse, exit 2, nothing sent) into app0 only, verifying before and after; restore the
installed release in-session on failure. After A's 2026-09-26 rollback, D installs from the step-down base
(backup_nanod_cc5.py --step-down, prepare_nanod_cc5_install.py --binary D --step-down-base).

Runs only under tools/nanod-flash-venv with esptool 4.12.0, on the single MAC-matched ROM
port, after backup_nanod_cc5.py and prepare_nanod_cc5_install.py --binary <the same binary>. Sequence
(every step --before no_reset --after no_reset_stub, so the RAM stub session is kept):
  1. flash_id                        MAC 12:34:56:78:9A:BC and 4MB flash
  2. verify_flash 0x0 <base>         the device still equals the image the binary was prepared from: the
                                     fresh backup, or in a step-down the step-down base (so a binary is only
                                     ever written over the installed cc5.3: stepping down from a written
                                     binary is rollback_nanod_cc5.py --to cc5.3 first, then, when that rollback
                                     left drift in nvs, spiffs or coredump, backup_nanod_cc5.py --step-down and
                                     prepare_nanod_cc5_install.py --binary <next> --step-down-base, then this
                                     install)
  3. write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 <the binary's image>
  4. verify_flash 0x0 <expected>     the full 4 MB equals the binary's prepared expected image
  5. read_mac --after hard_reset     reset into the new release only after 4 passed
Never erase_flash, never a filesystem upload, never a full-image write.

The base is the preparation record's (baseKind / baseFile): the pre-install backup, or the release's current
step-down base (tooling.load_step_down_base: its record, its SHA-256 and every critical region byte-identical
to the locked backup, re-checked here before anything is sent).

If step 3 or 4 fails (or anything unexpected happens after the write started) the chip is
NOT reset. In the same stub session the script writes the pre-install app0
(backups/nanod-cc5.3-before-cc5.4-active-app.bin, which starts with the 1.0.0-cc5.3 image) at
0x10000, verifies app0 against it, verifies the full image against the base of step 2, and
only when all three pass resets into cc5.3. If step 1 or 2 fails nothing is written and
nothing is reset. Everything is recorded in the binary's flash record (diagnostics/cc5.4-D-flash-checks.json,
cc5.4-E-flash-checks.json; A's was cc5.4-flash-checks.json) and one log per esptool step
(diagnostics/cc5.4-<X>-<step>.log); the records of earlier releases (cc5-*, cc5.3-*) and of the other
binaries are never touched. After a fix binary's install, check_nanod_cc5_look.py --binary <X> runs the short
look session (two read-only diag reads: build, pipeline, lcdMosiSig 103, coredump, reset reason).

Exit codes (the "outcome" field in the flash record says the same):
  0  INSTALLED_VERIFIED_RESET                   the binary written, full 4 MB verified, reset confirmed.
  1  nothing was sent to the device: wrong environment, an input file's SHA-256, or no
     single matching ROM port (no evidence file is written).
  2  STOPPED_BEFORE_WRITE                       identity or pre-write verify failed (or a usage
                                                error); nothing written, no reset.
  3  RESTORED_CC5_3_RESET                       the write/verify failed; cc5.3 restored, verified
                                                (app0 and full image), then reset.
  4  RESTORE_FAILED_NO_RESET                    the cc5.3 restore did not verify; NOT reset. Do not
                                                power-cycle; firmware/BUILD-cc5.4.md (cc5.4 -> cc5.3 rollback).
  5  INSTALLED_VERIFIED_RESET_UNCONFIRMED       the binary verified in flash, the reset was not
                                                confirmed; the exact retry command is printed.
  6  RESTORED_CC5_3_VERIFIED_RESET_UNCONFIRMED  cc5.3 restored and verified, the reset was not
                                                confirmed; the exact retry command is printed.
(For the history profiles the restore outcomes were RESTORED_CC4_RESET / RESTORED_CC5_2_RESET and their
_VERIFIED_RESET_UNCONFIRMED forms: Release.restored_outcome names them per profile.)
"""
import argparse
import contextlib
from pathlib import Path
import signal
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402

WRITE_ARGS = ["write_flash", "--flash_mode", "keep", "--flash_freq", "keep", "--flash_size", "keep"]


def exit_codes(profile):
    return {"INSTALLED_VERIFIED_RESET": 0, "STOPPED_BEFORE_WRITE": 2, profile.restored_outcome: 3,
            "RESTORE_FAILED_NO_RESET": 4, "INSTALLED_VERIFIED_RESET_UNCONFIRMED": 5,
            profile.restored_unconfirmed_outcome: 6}


EXIT_CODES = exit_codes(t.CURRENT)


def rediscover_rom(report, timeout=10.0):
    """The ROM port again (it may re-enumerate after a failed step); exactly one or None."""
    port, observed = t.poll_ports(t.is_rom_port, timeout, settle=0.5)
    report.setdefault("portObservations", []).append(observed[-1:] if observed else [])
    return port


def prepared_base(prep, p):
    """(path, bytes) of the image `prep` built the expected image from: the pre-install backup, or the release's
    current step-down base (checked by tooling.load_step_down_base and against the recorded file and SHA-256)."""
    kind = prep.get("baseKind") or t.PRE_INSTALL_ROLE
    rerun = (f"re-run prepare_nanod_cc5_install.py{f' --binary {p.binary}' if p.binary else ''}"
             + (" --step-down-base" if kind == t.STEP_DOWN_ROLE else ""))
    if kind == t.PRE_INSTALL_ROLE:
        if prep.get("baseFile", p.before_full.name) != p.before_full.name:
            raise SystemExit(f"{p.preparation.name} names the base {prep.get('baseFile')}, not {p.before_full.name}; "
                             f"{rerun}; nothing was sent")
        return p.before_full, p.before_full.read_bytes()
    if kind != t.STEP_DOWN_ROLE:
        raise SystemExit(f"{p.preparation.name} names an unknown base ({kind}); {rerun}; nothing was sent")
    try:
        path, data, _ = t.load_step_down_base(p)
    except ValueError as exc:
        raise SystemExit(f"{exc}; nothing was sent") from None
    if path.name != prep.get("baseFile") or t.sha256_bytes(data) != prep.get("baseSha256"):
        raise SystemExit(f"{p.preparation.name} was prepared from another step-down base than "
                         f"{p.step_down_report.name} names ({path.name}); {rerun}; nothing was sent")
    return path, data


def verify_inputs(prep, manifest, p=None):
    """Every input against its record before anything is sent; returns the base the device must equal
    before the write (the pre-install backup, or in a step-down the step-down base)."""
    p = p or t.CURRENT
    if p.binary and (prep.get("binary") != p.binary or (manifest.get("binary") or {}).get("name") != p.binary):
        raise SystemExit(f"{p.preparation.name} or {p.manifest.name} is not for binary {p.binary}; run "
                         f"prepare_nanod_cc5_install.py --binary {p.binary}; nothing was sent")
    checks = ((p.image, manifest["artifacts"][p.image.name]["sha256"]),
              (p.before_full, prep["beforeSha256"]), (p.expected_full, prep["expectedSha256"]),
              (p.rollback_app, prep["rollbackSha256"]))
    for path, digest in checks:
        if t.sha256_file(path) != digest:
            raise SystemExit(f"{path.name} does not match its recorded SHA-256; nothing was sent")
    if prep.get("firmwareVersion") != p.version or manifest.get("firmwareVersion") != p.version:
        raise SystemExit(f"{p.preparation.name} or {p.manifest.name} is not for {p.version}; re-run prepare")
    if (prep["applicationOffset"], prep["applicationSize"]) != (t.APP_OFFSET, t.APP_SIZE):
        raise SystemExit("Preparation does not target app0 0x10000/0x140000")
    candidate, before = p.image.read_bytes(), p.before_full.read_bytes()
    if t.app_image_problems(candidate, p.version) or t.binary_image_problems(candidate, p.binary):
        raise SystemExit(f"The {p.version} image{f' (binary {p.binary})' if p.binary else ''} failed its checks")
    if prep.get("candidateFile", p.image.name) != p.image.name:
        raise SystemExit(f"{p.preparation.name} prepared {prep.get('candidateFile')}, not {p.image.name}; re-run prepare")
    base_path, base = prepared_base(prep, p)
    expected, _ = t.assemble_expected(base, candidate)
    if t.sha256_bytes(expected) != prep["expectedSha256"]:
        raise SystemExit(f"The expected image does not follow from {base_path.name} + {p.tag}; re-run prepare")
    rollback = p.rollback_app.read_bytes()
    if len(rollback) != t.APP_SIZE or rollback != before[t.APP_OFFSET:t.APP_OFFSET + t.APP_SIZE]:
        raise SystemExit("The rollback app0 is not the backup's app0")
    if rollback != base[t.APP_OFFSET:t.APP_OFFSET + t.APP_SIZE]:
        raise SystemExit(f"The rollback app0 is not the app0 of {base_path.name}")
    from_image = p.from_image.read_bytes()
    if t.sha256_bytes(from_image) != p.from_image_sha256 or rollback[:p.from_image_bytes] != from_image:
        raise SystemExit(f"The rollback app0 does not hold the {p.from_version} image")
    return base_path


def restore_previous(esptool, report, p, base=None):
    """Same stub session: the pre-install app0 back, verify app0, verify the full image against the base the
    device equalled before the write; reset only if all pass."""
    base = base or p.before_full
    report["restoreAttempted"] = True
    port = rediscover_rom(report)
    if port is None:
        report["restoreError"] = "ROM port not found for the restore"
        return
    esptool.port = port
    ok, _ = esptool("restore-write", [*WRITE_ARGS, hex(t.APP_OFFSET), str(p.rollback_app)])
    report["restoreWritten"] = ok
    if not ok:
        return
    ok, _ = esptool("restore-verify-app0", ["verify_flash", hex(t.APP_OFFSET), str(p.rollback_app)])
    report["restoreApp0Verified"] = ok
    if not ok:
        return
    ok, _ = esptool("restore-verify-full", ["verify_flash", "0x0", str(base)])
    report["restoreFullImageVerified"] = ok
    if not ok:
        return
    report["resetAttempted"] = True
    ok, output = esptool("restore-reset", ["read_mac"], after="hard_reset")
    report["reset"] = t.reset_confirmed(ok, output)


def restore_outcome(report, p):
    """Outcome after a restore attempt, from what was actually verified and confirmed."""
    if report.get("restoreFullImageVerified"):
        return p.restored_outcome if report.get("reset") else p.restored_unconfirmed_outcome
    return "RESTORE_FAILED_NO_RESET"


def recover_after_failed_write(esptool, report, p, base=None):
    """No reset: restore the installed release in this stub session (once), then report what was achieved."""
    if not report["restoreAttempted"]:
        print(f"{p.tag} write or verify FAILED. Not resetting; restoring {p.from_tag} in this stub session.", flush=True)
        try:
            restore_previous(esptool, report, p, base)
        except Exception as exc:  # recorded; the outcome below says what was verified
            report["restoreException"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
    report["outcome"] = restore_outcome(report, p)
    return report["outcome"]


def install(esptool, report, p, base=None):
    """Steps 1-5; returns the outcome. Exceptions are handled by main() from the report flags. `base` is the
    image the device must equal before the write (verify_inputs; the pre-install backup by default)."""
    base = base or p.before_full
    ok, output = esptool("identity", ["flash_id"])
    problems = t.identity_problems(output) if ok else ["flash_id failed"]
    if problems:
        report.update(outcome="STOPPED_BEFORE_WRITE", reason="; ".join(problems))
        return report["outcome"]
    report["identityVerified"] = True
    ok, _ = esptool("before-verify", ["verify_flash", "0x0", str(base)])
    if not ok:
        report.update(outcome="STOPPED_BEFORE_WRITE",
                      reason=f"device differs from {base.name}; nothing written, no reset")
        return report["outcome"]
    report["preWriteVerified"] = True
    report["writeAttempted"] = True
    ok, _ = esptool("write", [*WRITE_ARGS, hex(t.APP_OFFSET), str(p.image)])
    report["flashWritten"] = ok
    if ok:
        ok, _ = esptool("after-verify", ["verify_flash", "0x0", str(p.expected_full)])
        report["postWriteVerified"] = ok
    if not ok:
        with sigint_ignored():
            return recover_after_failed_write(esptool, report, p, base)
    report["resetAttempted"] = True
    ok, output = esptool("reset", ["read_mac"], after="hard_reset")
    report["reset"] = t.reset_confirmed(ok, output)
    report["outcome"] = "INSTALLED_VERIFIED_RESET" if report["reset"] else "INSTALLED_VERIFIED_RESET_UNCONFIRMED"
    return report["outcome"]


@contextlib.contextmanager
def sigint_ignored():
    """Ctrl+C is ignored while the restore runs (a second Ctrl+C must not cut the restore short); off the main
    thread signal handlers cannot be set, and nothing changes."""
    try:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    except ValueError:
        previous = None
    try:
        yield
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)


def outcome_after_exception(esptool, report, p, base=None):
    """Map an unexpected exception (Ctrl+C included) to what the flags prove; never resets unless verified."""
    if report["postWriteVerified"]:
        return "INSTALLED_VERIFIED_RESET" if report["reset"] else "INSTALLED_VERIFIED_RESET_UNCONFIRMED"
    if report["writeAttempted"]:
        print("Unexpected failure after the write started. Not resetting. Do not reset or power-cycle the knob "
              f"while {p.from_tag} is restored in this stub session.", flush=True)
        with sigint_ignored():
            return recover_after_failed_write(esptool, report, p, base)
    return "STOPPED_BEFORE_WRITE"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = t.binary_choices()
    if choices:
        parser.add_argument("--binary", choices=choices, default=choices[0],
                            help=f"the PRESENTATION_V5 12.6 binary to install (default {choices[0]}); it must be "
                                 "prepared (prepare_nanod_cc5_install.py --binary) and the knob must hold cc5.3")
    args = parser.parse_args(argv)
    t.console_utf8()
    environment = t.assert_flash_environment()  # before any command
    p = t.CURRENT.binary_profile(getattr(args, "binary", None))
    codes = exit_codes(p)
    prep = t.load_json(p.preparation)
    manifest = t.load_json(p.manifest)
    base = verify_inputs(prep, manifest, p) or p.before_full
    port = t.find_rom_port()  # exit 1 above this line: nothing was sent
    report = {"startedUtc": t.utc_stamp(), "firmwareVersion": p.version, "fromVersion": p.from_version,
              **({"binary": p.binary, "buildFlags": list(p.build_flags)} if p.binary else {}),
              "environment": environment, "port": port, "chipMac": t.CHIP_MAC,
              "candidate": p.image.name, "candidateSha256": prep["candidateSha256"],
              "rollbackFile": p.rollback_app.name, "backupFile": p.before_full.name,
              "baseKind": prep.get("baseKind") or t.PRE_INSTALL_ROLE, "baseFile": base.name,
              "identityVerified": False, "preWriteVerified": False, "writeAttempted": False, "flashWritten": False,
              "postWriteVerified": False, "resetAttempted": False, "reset": False, "restoreAttempted": False,
              "steps": [], "outcome": "STARTED"}
    esptool = t.Esptool(port, report, p.install_log_prefix)
    try:
        try:
            outcome = install(esptool, report, p, base)
        except BaseException as exc:  # Ctrl+C (KeyboardInterrupt) too: the child esptool is gone, app0 may be half written
            report["exception"] = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, KeyboardInterrupt):
                report["interrupted"] = True
            traceback.print_exc()
            outcome = outcome_after_exception(esptool, report, p, base)
        report["outcome"] = outcome
        code = codes[outcome]
        if outcome == "INSTALLED_VERIFIED_RESET":
            which = f" binary {p.binary}" if p.binary else ""
            if p.build_number is not None:
                # A fix binary (D, E): the look session, not the full 8b window (firmware/BUILD-cc5.4.md, TB-D11).
                print(f"{p.version}{which} written and the full 4 MB verified before reset. Next (the look session): "
                      "step 7 boot sanity (port only: 239A:8010 stable for 30 s), 8a inventory (device_inventory.py), "
                      f"then check_nanod_cc5_look.py --binary {p.binary}.", flush=True)
            else:
                print(f"{p.version}{which} written and the full 4 MB verified before reset. Next: boot sanity (>= 30 s "
                      "native screen, stable 239A:8010), then device_inventory.py and check_nanod_cc5.py"
                      + (f" --binary {p.binary}" if p.binary else "") + ".", flush=True)
        elif outcome == "STOPPED_BEFORE_WRITE":
            print(f"Stopped before writing: {report.get('reason') or report.get('exception')}. Nothing was "
                  f"written and the chip was not reset; {p.from_tag} is intact.", flush=True)
            if report["identityVerified"] and not report["preWriteVerified"] and t.backup_locks(p):
                print("In a step-down (a binary was written and rolled back), the data regions may have changed since "
                      f"{base.name}: take a step-down base (backup_nanod_cc5.py --step-down), prepare with "
                      f"--step-down-base, then install again (firmware/BUILD-{p.tag}.md, step-down).", flush=True)
        elif outcome == p.restored_outcome:
            print(f"{p.tag} was NOT installed. {p.from_tag} was restored, verified (app0 and full 4 MB) and reset.",
                  flush=True)
        elif outcome == "RESTORE_FAILED_NO_RESET":
            print("RESTORE DID NOT COMPLETE. Do not reset or power-cycle. The chip is left in the ROM bootloader.\n"
                  f"Re-run rollback_nanod_cc5.py --to {p.from_tag}"
                  + (f" --binary {p.binary}" if p.binary else "")
                  + f", or follow the '{p.tag} -> {p.from_tag} rollback' runbook (firmware/BUILD-{p.tag}.md, "
                  "firmware/RECOVERY.md).", flush=True)
        else:  # verified in flash, reset not confirmed
            what = p.tag if outcome.startswith("INSTALLED") else f"The restored {p.from_tag} ({p.tag} was NOT installed)"
            report["resetRetryCommand"] = t.print_reset_retry(esptool.port, what)
        return code
    finally:
        report["finishedUtc"] = t.utc_stamp()
        t.write_json_evidence(p.flash_checks, report)


if __name__ == "__main__":
    sys.exit(main())
