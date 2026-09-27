"""cc5 hardware-window tooling (tools/nanod_cc5_tooling.py and the work/*cc5* scripts).

Three kinds of test, none of which touches hardware:
  * Helper tests: port matching on fake port lists, flash-environment rules, esptool
    argument guards, partition/OTA parsing, app-only image assembly, art packets against
    a fake art store, diag margins, evidence naming and the raw serial client on a fake
    port object.
  * Static tests (only these are parse-only; they never run what they read): every
    script is parsed (AST) for guarded mains, no COM literals, no module-level
    serial/esptool imports and no erase. RECOVERY.md section 5 and BUILD-cc5.md are read
    as text: the rollback interlocks (the Quit, scripted and manual blocks clear them
    before their first command; block 1 requires esptool 4.12.0 first; block 4 and both
    leave-the-bootloader resets verify app0 themselves before resetting), every native
    command armed with $global:LASTEXITCODE = -1, interpreters set in each block,
    absolute existing paths, the NO-GO/NOT RUN signals and companion guards, profile
    counts that match the real inventory shape (one object, name -> profile) and the
    Stage 10 step order.
  * 1.0.0-cc5.1 tests: release naming (cc5.1 parameterized, 1.0.0-cc5 superseded history),
    the firmware fixes read from source (stacks, out-of-line HMI config receivers, internal
    receive queue, diag reboot fields, bounded replies), the reboot-detection helpers,
    check_nanod_cc5.RebootWatch with fake diag/PnP/port watch, and check_nanod_cc5.raw_checks()
    end to end against FakeFirmware (an in-memory port answering like the firmware): both
    stress passes, the turning gate and a reboot between checkpoints.
  * 1.0.0-cc5.2 tests: release naming (cc5.2 parameterized; 1.0.0-cc5 and 1.0.0-cc5.1
    superseded history), the firmware fixes read from source (the bounded LED transport that
    replaces FastLED's RMT driver, the task watchdog and its save/load exclusion, the forced
    release, the liveness and LED diag fields), the liveness helpers, liveness at every
    RebootWatch checkpoint, and the unattended soak end to end against FakeFirmware (a clean
    soak, a forced release, a stalled HMI, an LED transmit timeout, a soak shorter than the
    gate).
  * Flow tests, which RUN the scripts rather than parse them: install_, rollback_,
    backup_, prepare_ and finalize_nanod_cc5.py are imported and their main() is CALLED. Before
    each call every process, port and esptool entry point is replaced by a fake:
    subprocess.Popen and port enumeration fail the test if reached; the flash-environment
    check, ROM port discovery, port polling and the Esptool runner are fakes that return
    scripted results. Every file a flow reads or writes is in a temporary folder or
    replaced by an in-memory fake (evidence writes are captured). So each flow runs its
    real decision logic (exit codes, outcomes, which steps run, when a reset may happen,
    what gets recorded) against fake esptool results, and finalize runs against fake
    Stage 10 evidence in the shapes the real tools write, including rollbacks that left
    no rollback record.
  * 1.0.0-cc5.3 tests (the cc5.2 -> cc5.3 profile, artwork2): release profiles and their
    distinct evidence and backup names; the backup lock rules of the new pre-cc5.3 backup
    (the cc5.2 history pair is never touched); backup, prepare, install (every exit), rollback
    to cc5.2 and to cc4, package (the cc5.2 manifest SUPERSEDED only with its installed record
    kept) and finalize (every artwork2 gate, rollback traces of both profiles) flows; rollback's
    refusal of a missing --to once cc5.3 was written, and its --help, through the same fakes; the
    section 5 cover and icon payloads (the companion's own encoders; the host validator's
    subsampling, precision, EOI and full-decode checks); the unpaced RawKnob and media packets;
    FakeMedia, an ARTWORK2.md 4.3/4.4 store whose commit check models cc_jpeg_validate and that
    replays harness/media_store_traces.json exactly; check_nanod_cc5.raw_checks() end to
    end with artwork2 (each new gate passing, and each gate condition failing on its own: a firmware
    that evicts the pinned key, keeps the two oldest, drops prefetched covers or icons, misses icons
    in have or claims covers never sent, sends a bare error, answers a wrong error string (offset,
    checksum, decode) or reply shape, keeps an undecodable cover, serves media after a release,
    miscounts mediaErrors, never counts mediaEvictions or mediaCommits, draws only late arrivals,
    fails the named prefetch's decode, re-uploads a named prefetched cover, already holds the round
    trip's, the prefetch's or a pinning cover, acks slowly, uploads covers slowly, reports another
    receive queue, forgets recent covers under stress or in the soak, decodes slowly or reports no
    artwork2; a soak without paced v1 art; an icon store without begin-hits, an icon already held
    before the round trip or the prefetch, a round-trip cover uploaded again; artwork2 traffic failing
    inside the soak (a refused icon, cover or prefetch begin, a data ack at the wrong offset, a failed
    paced v1 commit, a commit of each slot kind acknowledged short without an error, a stray media
    error) and late in each stress pass (a refused upload, an uncommitted upload without a media
    error, a stray media error)), bridge_media() against a fake v4 bridge (including a
    media-error for the preempted key), check_nanod_cc5_lease.main() against a leased FakeFirmware
    (media lines that renew, refused case 2b lines, a release inside case 3b, a frame that ends the
    open upload, no frame inside an upload, a run shorter than two lease periods), build_ and
    package_nanod_cc5.main() with PlatformIO and git faked (UNFLASHED manifest, manifest.json
    unchanged, version string required), and BUILD-cc5.3.md and RECOVERY.md section 6 read as text.
  * 1.0.0-cc5.4 tests (the cc5.3 -> cc5.4 profile, NEWEST and CURRENT since the release tooling
    moved; the cc5.3-era flow tests run pinned to the cc5.3 profile with their cc5.2 -> cc5.3
    evidence, pin_current): the profile (presentation 5, alive, the ALIVE and presentation-5 gates, the
    12.2 memory gates, the 12.4 build-only heap projection); the pure checks (LED idle, load and
    render, LCD binary and timings, ready ks, hold and deferred hold, lim spacing and per push);
    check_nanod_cc5.raw_checks(profile=cc5.4) end to end against FakeFirmware54, which answers like
    cc5.4 and plays the operator of the hands-on section from the LCD step titles, passing every
    raw gate and failing each on its own (idle and gap LED rates, render time, LCD timings per
    binary, heap and stackArtDec, double / other-button / never-deferred holds, ready without ks,
    chattering or missed pushes, no lim at 0:00 or while turning, F24 outside the Home win slot,
    presentation 4 or no alive, an error reply in a stress pass), with every frame it sends
    accepted by device.v5_parse; and tools/nanod_alive_tour.py (every screen, moment and tuning
    frame valid v5, a scripted session, timed sequences, refusal of a pre-cc5.4 knob, static
    safety). The firmware static tests follow the cc5.4 sources (the ALIVE LED output).
  * 1.0.0-cc5.4 build ladder (PRESENTATION_V5 12.6, lead ruling R-m) and the Desk Dial flash interlock:
    binary A is the cc5.4 profile, B and C its variants with their own names and the release's shared
    backup and check records (LadderProfileTests); the build-only pipeline markers (a synthetic ELF);
    backup locks, write evidence and the newest written binary across A, B and C; build_ and
    package_nanod_cc5.py --binary with a fake PlatformIO that honours PLATFORMIO_BUILD_FLAGS and
    PLATFORMIO_BUILD_DIR (flags that did not take effect, a missing ELF, a record of another binary);
    prepare, install, rollback (--binary, the newest written binary, usage errors) and finalize
    (--binary B after A's rollback) per binary; check_nanod_cc5.py --binary against FakeFirmware54;
    running_companions / require_companion_quit for DeskDial.exe and NanoDControlCenter.exe; and
    firmware/BUILD-cc5.4.md read as text (Cc54RunbookTests: the step-down table, the dual-name guards,
    the cc5.4 -> cc5.3 rollback and the recorded build figures).
  * Review fixes TOOLBC-1..3: a step-down A -> B through the real backup, prepare, install and rollback
    scripts against an in-memory flash (DeviceEsptool) where A's panic left a core dump that its verified
    rollback kept (StepDownFlowTests: the step-down base read, prepare --step-down-base, the install and its
    restore verified against the base, the refusals), finalize with a step-down base, the build log kept as
    *.superseded-<UTC>.log with its SHA-256 in the record and checked by packaging, and sizeof(CCFrame) and
    the ALIVE instance size read from firmware.elf into every binary's record and manifest.
  * The fix binaries D and E (after A's 2026-09-26 rollback: a dark LCD from tft.initDMA() with MOSI = MISO, and
    the LED dither on at rest): their names, flags, pipelines and targets, A, B and C retired (refused by build,
    package, prepare, install, finalize and the look check; still taken by rollback and check); the LCD data-line
    gate (tft_spi_config, lcd_mosi_gate; A's real ELF fails it when present), diag lcdMosiSig and build
    (lcd_mosi_problems, lcd_binary), the build marker; build and package of D and E with the fake PlatformIO; the
    step-down A -> D through the real backup, prepare, install and rollback scripts on the in-memory flash;
    check_nanod_cc5_look.py (GO / NO-GO, NOT RUN, evidence, the user's answers); the rollback's closing line
    per outcome; and the runbook's "Fix binaries D and E" section. The flow tests of the 2026-09-26 window
    (A, B, C) run with those binaries as the active ones (HardwareFreeScriptTest.active_binaries).
Nothing here opens a serial port, runs esptool, starts a process or writes outside a
temporary folder. Skips when the firmware workspace is not next to the companion.
"""
import ast
import base64
import contextlib
import fnmatch
import hashlib
import importlib.util
import io
import itertools
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent / "tools"
if (WORK / "nanod_cc5_tooling.py").is_file():
    sys.path.insert(0, str(WORK))
    import nanod_cc5_tooling as t
else:  # pragma: no cover - companion copied without the firmware workspace
    t = None

SCRIPTS = ("build_nanod_cc5.py", "package_nanod_cc5.py", "nanod_enter_bootloader_v2.py", "backup_nanod_cc5.py",
           "prepare_nanod_cc5_install.py", "install_nanod_cc5.py", "rollback_nanod_cc5.py", "check_nanod_cc5.py",
           "check_nanod_cc5_lease.py", "finalize_nanod_cc5.py", "nanod_alive_tour.py", "check_nanod_cc5_look.py")
FLASHING = ("backup_nanod_cc5.py", "install_nanod_cc5.py", "rollback_nanod_cc5.py")
BACKUPS = ROOT / "backups"
needs_tooling = unittest.skipIf(t is None, "tools/nanod_cc5_tooling.py is not present")
# The flashing runbooks (firmware/*.md) name absolute paths, virtualenvs and release images of the
# author's workspace; the public tree writes those roots as <repo>, so these runbook checks only run
# in a full workspace with NANOD_RUNBOOK_CHECKS=1.
machine_runbook = unittest.skipUnless(os.environ.get("NANOD_RUNBOOK_CHECKS") == "1",
                                      "runbook paths are <repo> placeholders here (set NANOD_RUNBOOK_CHECKS=1)")
# The 2026-09-26 window's ladder (PRESENTATION_V5 12.6), retired since A's rollback (tooling.RETIRED_BINARIES). The
# flow tests of that window run their scripts with these as the active binaries (HardwareFreeScriptTest
# .active_binaries), so the mechanism they pin stays tested; the fix-binary tests use the real ACTIVE_BINARIES (D, E).
LEGACY_BINARIES = ("A", "B", "C")


def port(device, vid, pid, serial):
    return SimpleNamespace(device=device, vid=vid, pid=pid, serial_number=serial, description="", location=None, hwid="")


APP = lambda serial="NANO_D", device="COMA": port(device, 0x239A, 0x8010, serial)  # noqa: E731
ROM = lambda serial="12:34:56:78:9A:BC", device="COMB": port(device, 0x303A, 0x1001, serial)  # noqa: E731


def partition_table(entries, md5=True, corrupt=False):
    rows = b"".join(struct.pack("<2sBBII16sI", b"\xaa\x50", ty, st, off, size, name.encode().ljust(16, b"\0"), 0)
                    for name, ty, st, off, size in entries)
    if md5:
        digest = bytes(16) if corrupt else hashlib.md5(rows).digest()
        rows += b"\xeb\xeb" + b"\xff" * 14 + digest
    return rows + b"\xff" * (0x1000 - len(rows))


def ota_slot(seq, crc=None):
    crc = zlib.crc32(struct.pack("<I", seq), 0xFFFFFFFF) & 0xFFFFFFFF if crc is None else crc
    return struct.pack("<I20sII", seq, b"\xff" * 20, 0xFFFFFFFF, crc) + b"\xff" * (0x1000 - 32)


def fake_elf(symbols):
    """A minimal ELF32 little-endian file with one symbol table naming `symbols` (what the build's
    tooling.elf_symbols reads from firmware.elf): header, .symtab, .strtab, three section headers. Each
    symbol is a name (size 0), a (name, st_size) pair or a (name, st_size, st_value) triple; every entry is a
    global data object (STT_OBJECT)."""
    names, entries = b"\0", []
    for symbol in symbols:
        name, size, value = (symbol, 0, 0) if isinstance(symbol, str) else (tuple(symbol) + (0,))[:3]
        entries.append((len(names), size, value))
        names += name.encode("ascii") + b"\0"
    symtab = bytes(16) + b"".join(struct.pack("<IIIBBH", offset, value, size, 0x11, 0, 1)
                                  for offset, size, value in entries)
    header = bytearray(52)
    header[:6] = b"\x7fELF\x01\x01"
    symtab_at, strtab_at = 52, 52 + len(symtab)
    shoff = (strtab_at + len(names) + 3) & ~3
    struct.pack_into("<I", header, 0x20, shoff)
    struct.pack_into("<HHH", header, 0x2E, 40, 3, 0)
    sections = [(0,) * 10, (0, 2, 0, 0, symtab_at, len(symtab), 2, 1, 4, 16), (0, 3, 0, 0, strtab_at, len(names), 0, 0, 1, 0)]
    body = bytes(header) + symtab + names
    return body + bytes(shoff - len(body)) + b"".join(struct.pack("<10I", *row) for row in sections)


LAYOUT = [("nvs", 1, 2, 0x9000, 0x5000), ("otadata", 1, 0, 0xE000, 0x2000), ("app0", 0, 0x10, 0x10000, 0x140000),
          ("app1", 0, 0x11, 0x150000, 0x140000), ("spiffs", 1, 0x82, 0x290000, 0x160000),
          ("coredump", 1, 3, 0x3F0000, 0x10000)]
# The PRESENTATION_V5 12.4 size symbols of a cc5.4 firmware.elf (hmi_thread.cpp cc_hmi_frame and alive), with the
# sizes the 2026-09-26 builds have (nm -S: 0x464 and 0x2c14).
CCFRAME_BYTES, ALIVE_INSTANCE_BYTES = 1124, 11284
V5_SIZE_SYMBOLS = ([(t.CCFRAME_SYMBOLS[0], CCFRAME_BYTES), (t.ALIVE_INSTANCE_SYMBOLS[0], ALIVE_INSTANCE_BYTES)]
                   if t is not None else [])


@needs_tooling
class PortMatchingTests(unittest.TestCase):
    def test_application_serial_is_case_insensitive(self):
        for serial in ("NANO_D", "Nano_D", "nano_d"):
            self.assertTrue(t.is_app_port(APP(serial)), serial)
        for bad in (APP("NANO_D2"), APP(None), APP(""), port("X", 0x239A, 0x8011, "NANO_D"),
                    port("X", 0x303A, 0x8010, "NANO_D")):
            self.assertFalse(t.is_app_port(bad))

    def test_rom_port_requires_this_chip_mac(self):
        for serial in ("12:34:56:78:9A:BC", "12:34:56:78:9a:bc", "123456789ABC", "12-34-56-78-9a-bc"):
            self.assertTrue(t.is_rom_port(ROM(serial)), serial)
        for bad in (ROM("12:34:56:78:9A:BD"), ROM(None), ROM(""), port("X", 0x239A, 0x8010, "12:34:56:78:9A:BC")):
            self.assertFalse(t.is_rom_port(bad))
        self.assertFalse(t.is_rom_port(ROM("12:34:56:78:9A:BC"), mac=""))

    def test_exactly_one_match_or_abort(self):
        other_rom = ROM("12:34:56:78:00:01", "COMC")
        self.assertEqual(t.find_app_port([APP(device="COMX"), other_rom]), "COMX")
        self.assertEqual(t.find_rom_port([APP(), other_rom, ROM(device="COMY")]), "COMY")
        for ports in ([], [other_rom], [APP(device="C1"), APP("nano_d", device="C2")]):
            with self.assertRaises(t.PortError) as caught:
                t.find_app_port(ports)
            self.assertIn("Nothing was opened or sent", str(caught.exception))
        with self.assertRaises(t.PortError):
            t.find_rom_port([ROM(device="C1"), ROM("123456789abc", device="C2")])

    def test_poll_waits_for_a_stable_single_match(self):
        now = itertools.count(0, 0.25)
        clock = lambda: next(now) / 1.0  # noqa: E731
        snapshots = iter([[APP()], [], [ROM(device="COMZ")], [ROM(device="COMZ")], [ROM(device="COMZ")],
                          [ROM(device="COMZ")], [ROM(device="COMZ")], [ROM(device="COMZ")]])
        device, observed = t.poll_ports(t.is_rom_port, 10, lister=lambda: next(snapshots), clock=clock,
                                        sleep=lambda s: None, settle=0.5)
        self.assertEqual(device, "COMZ")
        self.assertEqual([len(o["ports"]) for o in observed], [1, 0, 1])
        device, _ = t.poll_ports(t.is_rom_port, 1, lister=lambda: [APP()], clock=itertools.count(0, 0.5).__next__,
                                 sleep=lambda s: None)
        self.assertIsNone(device)


@needs_tooling
class FlashEnvironmentTests(unittest.TestCase):
    def test_only_the_flash_venv_with_esptool_4_12_0(self):
        python = t.FLASH_VENV / "Scripts" / "python.exe"
        self.assertEqual(t.flash_environment_problems(python, t.FLASH_VENV, "4.12.0"), [])
        self.assertEqual(len(t.flash_environment_problems(python, t.FLASH_VENV, "4.5.1")), 1)
        self.assertEqual(len(t.flash_environment_problems(python, t.FLASH_VENV, None)), 1)
        other = ROOT / ".venv"
        self.assertEqual(len(t.flash_environment_problems(other / "Scripts" / "python.exe", other, "4.12.0")), 2)


@needs_tooling
class EsptoolGuardTests(unittest.TestCase):
    KEEP = ["--flash_mode", "keep", "--flash_freq", "keep", "--flash_size", "keep"]

    def test_only_reads_verifies_identity_and_app0_writes(self):
        for args in (["flash_id"], ["read_mac"], ["read_flash", "0x0", "0x400000", "f.bin", "--no-progress"],
                     ["verify_flash", "0x0", "f.bin"], ["write_flash", *self.KEEP, "0x10000", "cc5.bin"],
                     ["write_flash", *self.KEEP, "0x10000", r"C:\x\backups\nanod-cc4-before-cc5-active-app.bin"]):
            self.assertEqual(t.validate_esptool_args(args), args)
        for args in (["erase_flash"], ["erase_region", "0x0", "0x1000"], ["write_flash", "-e", *self.KEEP, "0x10000", "a"],
                     ["write_flash", "--erase-all", *self.KEEP, "0x10000", "a"], ["write_flash", *self.KEEP, "0x0", "full.bin"],
                     ["write_flash", *self.KEEP, "0x10000", "a", "0x290000", "fs.bin"], ["write_flash", "0x10000", "a"],
                     ["write_flash", "--flash_mode", "dio", "--flash_freq", "keep", "--flash_size", "keep", "0x10000", "a"],
                     ["run"], ["merge_bin", "-o", "x"], ["load_ram", "x"], []):
            with self.assertRaises(ValueError, msg=args):
                t.validate_esptool_args(args)

    def test_write_shape_is_exact_whatever_the_number_format(self):
        """A second image at any address, in any spelling, or any extra option is refused."""
        for args in (["write_flash", *self.KEEP, "0x10000", "a.bin", "2686976", "spiffs.bin"],   # decimal address
                     ["write_flash", *self.KEEP, "0x10000", "a.bin", "0X290000", "spiffs.bin"],  # upper-case 0X
                     ["write_flash", *self.KEEP, "0X10000", "a.bin"], ["write_flash", *self.KEEP, "65536", "a.bin"],
                     ["write_flash", *self.KEEP, "0x010000", "a.bin"], ["write_flash", *self.KEEP, "0x10000"],
                     ["write_flash", *self.KEEP, "0x10000", "a.bin", "extra"], ["write_flash", *self.KEEP, "a.bin", "0x10000"],
                     ["write_flash", *self.KEEP, "0x10000", "--compress"], ["write_flash", *self.KEEP, "0x10000", "a.txt"],
                     ["write_flash", "--compress", *self.KEEP, "0x10000", "a.bin"],
                     ["write_flash", *self.KEEP, "--no-compress", "0x10000", "a.bin"],
                     ["write_flash", "--flash_freq", "keep", "--flash_mode", "keep", "--flash_size", "keep", "0x10000", "a.bin"],
                     ["write_flash", *self.KEEP, *self.KEEP, "0x10000", "a.bin"]):
            with self.assertRaises(ValueError, msg=args):
                t.validate_esptool_args(args)

    def test_reset_confirmation_and_retry_command(self):
        good = "MAC: 12:34:56:78:9a:bc\nHard resetting via RTS pin...\n"
        self.assertTrue(t.reset_confirmed(True, good))
        self.assertFalse(t.reset_confirmed(False, good))
        self.assertFalse(t.reset_confirmed(True, "MAC: 12:34:56:78:9a:bc\n"))            # no reset line
        self.assertFalse(t.reset_confirmed(True, "MAC: aa:bb:cc:dd:ee:ff\nHard resetting via RTS pin...\n"))
        self.assertFalse(t.reset_confirmed(True, None))
        command = t.reset_retry_command("COMQ")
        self.assertIn("--port COMQ --before no_reset --after hard_reset read_mac", command)
        self.assertIn(str(t.FLASH_VENV / "Scripts" / "python.exe"), command)
        self.assertNotIn("write_flash", command)

    def test_runner_keeps_the_stub_session_and_logs_each_step(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout="MAC: 12:34:56:78:9a:bc\nDetected flash size: 4MB\n", stderr="")

        with tempfile.TemporaryDirectory() as folder:
            report = {}
            runner = t.Esptool("COMQ", report, "cc5", python="py", run=fake_run, diagnostics=folder, echo=False)
            ok, output = runner("identity", ["flash_id"])
            self.assertTrue(ok)
            self.assertEqual(t.identity_problems(output), [])
            command = calls[0][0]
            self.assertEqual(command[:4], ["py", "-u", "-m", "esptool"])
            self.assertEqual(command[command.index("--before") + 1], "no_reset")
            self.assertEqual(command[command.index("--after") + 1], "no_reset_stub")
            self.assertEqual(command[command.index("--port") + 1], "COMQ")
            runner("identity", ["flash_id"])  # second log with the same name archives the first
            self.assertEqual(len(list(Path(folder).glob("cc5-identity*.log"))), 2)
            self.assertEqual([s["step"] for s in report["steps"]], ["identity", "identity"])
            with self.assertRaises(ValueError):
                runner("x", ["flash_id"], after="soft_reset")
            with self.assertRaises(ValueError):
                runner("x", ["erase_flash"])
            self.assertEqual(len(calls), 2)

    def test_runner_reports_timeouts_as_failures(self):
        def slow(command, **kwargs):
            raise t.subprocess.TimeoutExpired(command, 1)

        with tempfile.TemporaryDirectory() as folder:
            report = {}
            ok, output = t.Esptool("P", report, "cc5", run=slow, diagnostics=folder, echo=False)("verify", ["verify_flash", "0x0", "f"])
            self.assertFalse(ok)
            self.assertEqual(report["steps"][0]["exitCode"], "timeout")

    def test_identity_problems(self):
        self.assertEqual(len(t.identity_problems("MAC: aa:bb:cc:dd:ee:ff\nDetected flash size: 8MB")), 2)
        self.assertEqual(t.identity_problems(None), ["chip MAC does not match", "flash size is not 4MB"])


@needs_tooling
class PartitionAndOtaTests(unittest.TestCase):
    def test_synthetic_table_round_trip_and_rejections(self):
        parsed = t.parse_partition_table(partition_table(LAYOUT))
        self.assertEqual(t.layout_key(parsed), LAYOUT)
        with self.assertRaises(ValueError):
            t.parse_partition_table(partition_table(LAYOUT, corrupt=True))
        with self.assertRaises(ValueError):
            t.parse_partition_table(partition_table(LAYOUT, md5=False))
        with self.assertRaises(ValueError):
            t.parse_partition_table(partition_table([("a", 0, 0x10, 0x10000, 0x20000), ("b", 0, 0x11, 0x20000, 0x10000)]))
        with self.assertRaises(ValueError):
            t.parse_partition_table(b"\x12" * 32 + b"\xff" * 0xFE0)
        with self.assertRaises(ValueError):
            t.parse_partition_table(b"\xff" * 0x1000)

    def test_real_partition_table_matches_the_original_manifest(self):
        table, manifest = BACKUPS / "nanod-original-partitions.bin", BACKUPS / "nanod-original-manifest.json"
        if not (table.is_file() and manifest.is_file()):
            self.skipTest("original backup not present")
        parsed = t.parse_partition_table(table.read_bytes())
        self.assertEqual(t.layout_key(parsed), t.layout_key(json.loads(manifest.read_text(encoding="utf-8"))["partitions"]))
        self.assertEqual(t.layout_key(parsed), LAYOUT)

    def test_ota_selection(self):
        self.assertEqual(t.ota_selection(ota_slot(1) + ota_slot(0), 2)["appIndex"], 0)
        self.assertEqual(t.ota_selection(ota_slot(1) + ota_slot(2), 2)["appIndex"], 1)
        self.assertEqual(t.ota_selection(ota_slot(3) + ota_slot(2, crc=5), 2)["appIndex"], 0)
        self.assertIsNone(t.ota_selection(b"\xff" * 0x2000, 2)["appIndex"])
        with self.assertRaises(ValueError):
            t.ota_selection(ota_slot(7, crc=1) + b"\xff" * 0x1000, 2)

    def test_real_ota_data_selects_app0(self):
        full, manifest = BACKUPS / "nanod-original-full-20260922.bin", BACKUPS / "nanod-original-manifest.json"
        if not (full.is_file() and manifest.is_file()):
            self.skipTest("original backup not present")
        data = full.read_bytes()[t.OTADATA_OFFSET:t.OTADATA_OFFSET + t.OTADATA_SIZE]
        selection = t.ota_selection(data, 2)
        self.assertEqual(selection["appIndex"], 0)
        expected = json.loads(manifest.read_text(encoding="utf-8"))["ota_entries"]
        self.assertEqual(selection["entries"], expected)

    def test_flash_regions_cover_the_flash(self):
        entries = [dict(zip(("name", "type", "subtype", "offset", "size"), row)) for row in LAYOUT]
        regions = t.flash_regions(entries)
        self.assertEqual([r[0] for r in regions], ["bootloader", "partition-table", "nvs", "otadata", "app0", "app1",
                                                   "spiffs", "coredump"])
        self.assertEqual(regions[0][1], 0)
        self.assertEqual(regions[-1][2], t.FLASH_BYTES)
        self.assertTrue(all(a[2] == b[1] for a, b in zip(regions, regions[1:])))
        gappy = t.flash_regions([e for e in entries if e["name"] != "app1"])
        self.assertIn(("gap-0x150000", 0x150000, 0x290000), gappy)
        self.assertTrue({"bootloader", "partition-table", "otadata", "app0", "app1"} <= t.CRITICAL_REGIONS)
        self.assertFalse({"nvs", "spiffs", "coredump"} & t.CRITICAL_REGIONS)


@needs_tooling
class ImageAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.before = bytes((i * 7 + 3) & 0xFF for i in range(256)) * (t.FLASH_BYTES // 256)

    def test_app_only_image_erases_to_the_last_sector(self):
        candidate = b"\xe9" + bytes(range(256)) * 3 + b"cc5"
        expected, end = t.assemble_expected(self.before, candidate)
        self.assertEqual(end, t.APP_OFFSET + 0x1000)
        self.assertEqual(expected[t.APP_OFFSET:t.APP_OFFSET + len(candidate)], candidate)
        self.assertEqual(set(expected[t.APP_OFFSET + len(candidate):end]), {0xFF})
        self.assertEqual(expected[:t.APP_OFFSET], self.before[:t.APP_OFFSET])
        self.assertEqual(expected[end:], self.before[end:])
        first, last = t.differing_span(expected, self.before)
        self.assertTrue(t.APP_OFFSET <= first and last <= end)

    def test_sector_boundaries_and_limits(self):
        expected, end = t.assemble_expected(self.before, b"\xe9" * 0x2000)
        self.assertEqual(end, t.APP_OFFSET + 0x2000)
        self.assertEqual(t.sector_end(0x10000, 1), 0x11000)
        self.assertEqual(t.sector_end(0x10000, 0x1000), 0x11000)
        for bad in (b"", b"\xe9" * (t.APP_SIZE + 1)):
            with self.assertRaises(ValueError):
                t.assemble_expected(self.before, bad)
        self.assertIsNone(t.differing_span(self.before, self.before))
        with self.assertRaises(ValueError):
            t.differing_span(b"ab", b"abc")
        self.assertEqual(t.differing_span(b"aaaa" * 2000, b"aaaa" * 1000 + b"b" + b"aaaa" * 999 + b"aaa"), (4000, 4001))

    def test_app_image_problems(self):
        self.assertEqual(t.app_image_problems(b"\xe9 1.0.0-cc5 ", "1.0.0-cc5"), [])
        self.assertEqual(len(t.app_image_problems(b"\x00 1.0.0-cc4", "1.0.0-cc5")), 2)
        self.assertEqual(len(t.app_image_problems(b"\xe9" * 16, None, limit=16)), 1)

    def test_reproduces_the_verified_cc4_expected_image(self):
        before = BACKUPS / "nanod-cc3-before-cc4-full.bin"
        prep = ROOT / "diagnostics" / "cc4-preparation.json"
        image = ROOT / "firmware" / "nanod-control-center-1.0.0-cc4.bin"
        if not (before.is_file() and prep.is_file() and image.is_file()):
            self.skipTest("cc4 installation evidence not present")
        record = json.loads(prep.read_text(encoding="utf-8"))
        cc4 = image.read_bytes()
        self.assertEqual(hashlib.sha256(cc4).hexdigest(), t.CC4_IMAGE_SHA256)
        self.assertEqual(len(cc4), t.CC4_IMAGE_BYTES)
        expected, end = t.assemble_expected(before.read_bytes(), cc4)
        self.assertEqual(end, record["erasedEndExclusive"])
        self.assertEqual(hashlib.sha256(expected).hexdigest(), record["expectedSha256"])


class FakeArtKnob:
    """Answers art lines like src/cc_art_store.h and cc_artwork.cpp for one control and frame key."""

    def __init__(self, ident, key):
        self.ident, self.key, self.cache, self.upload, self.ops = ident, key, {}, None, []

    def art(self, body):
        self.ops.append(body["op"])
        ack = {"id": body["id"], "key": body["key"], "op": body["op"], "offset": 0}
        if body["id"] != self.ident or body["key"] != self.key:
            ack["error"] = "Stale artwork selection"
        elif body["op"] == "begin":
            cached = self.cache.get(body["key"]) == body["crc32"]
            self.upload = {"crc": body["crc32"], "data": bytearray(), "done": cached}
            ack["offset"] = t.ART_BYTES if cached else 0
        elif body["op"] == "data":
            chunk = base64.b64decode(body["data"])
            if self.upload is None or self.upload["done"] or body["offset"] != len(self.upload["data"]):
                ack["error"] = "Artwork offset mismatch"
            else:
                self.upload["data"] += chunk
                ack["offset"] = len(self.upload["data"])
        else:
            up = self.upload
            ack["offset"] = t.ART_BYTES if up and (up["done"] or len(up["data"]) == t.ART_BYTES) else len(up["data"])
            if not up["done"] and len(up["data"]) != t.ART_BYTES:
                ack["error"] = "Artwork upload incomplete"
            elif not up["done"] and zlib.crc32(bytes(up["data"])) & 0xFFFFFFFF != up["crc"]:
                ack["error"] = "Artwork checksum mismatch"
            else:
                self.cache[body["key"]] = up["crc"]
        return ack, 0.004


@needs_tooling
class ArtworkPacketTests(unittest.TestCase):
    def test_pixels_and_packets(self):
        pixels = t.art_pixels("cc5a")
        self.assertEqual(len(pixels), t.ART_BYTES)
        self.assertEqual(pixels, t.art_pixels("cc5a"))
        self.assertNotEqual(pixels, t.art_pixels("cc5b"))
        messages = t.art_messages(7, "cc5a", pixels)
        self.assertEqual(len(messages), 2 + t.ART_BYTES // t.ART_CHUNK)
        self.assertEqual(messages[0], {"id": 7, "key": "cc5a", "op": "begin", "bytes": t.ART_BYTES,
                                       "crc32": zlib.crc32(pixels) & 0xFFFFFFFF})
        self.assertEqual(messages[-1], {"id": 7, "key": "cc5a", "op": "commit"})
        data = messages[1:-1]
        self.assertEqual([m["offset"] for m in data], list(range(0, t.ART_BYTES, t.ART_CHUNK)))
        self.assertEqual(b"".join(base64.b64decode(m["data"]) for m in data), pixels)
        self.assertEqual([t.expected_ack_offset(m) for m in (messages[0], data[0], messages[-1])],
                         [0, t.ART_CHUNK, t.ART_BYTES])
        self.assertTrue(all(len(json.dumps({"art": m}, separators=(",", ":"))) < 4096 for m in messages))

    def test_transfer_cold_cached_crc_mismatch_partial_and_stale(self):
        knob, pixels, between = FakeArtKnob(9, "k"), t.art_pixels("k"), []
        cold = t.art_transfer(knob, 9, "k", pixels, between=lambda: between.append(1))
        self.assertEqual((cold["beginOffset"], cold["chunks"], cold["committed"], cold["error"]), (0, 75, True, None))
        self.assertEqual(len(between), 77)
        self.assertEqual(len(cold["chunkSeconds"]), 75)
        cached = t.art_transfer(knob, 9, "k", pixels)
        self.assertTrue(cached["cached"] and cached["committed"])
        self.assertEqual(knob.ops[-2:], ["begin", "commit"])
        knob.key = "x"
        bad = t.art_transfer(knob, 9, "x", t.art_pixels("x"), crc=1)
        self.assertEqual((bad["errorOp"], bad["error"]), ("commit", "Artwork checksum mismatch"))
        self.assertNotIn("x", knob.cache)
        partial = t.art_transfer(knob, 9, "x", t.art_pixels("x"), stop_after_chunks=5)
        self.assertEqual((partial["chunks"], partial["committed"], knob.ops[-1]), (5, False, "data"))
        stale = t.art_transfer(knob, 8, "x", t.art_pixels("x"))
        self.assertEqual((stale["errorOp"], stale["error"]), ("begin", "Stale artwork selection"))


@needs_tooling
class MarginsTimingEvidenceTests(unittest.TestCase):
    def test_diag_margins(self):
        good = {"lvglFree": 40000, "lvglMinFree": 16384, "heapMinFree": 90000, "stackLcd": 1025, "stackCom": 3000,
                "stackHmi": 2048, "stackFoc": 5000}
        self.assertTrue(t.diag_margins(good)["passed"])
        for change in ({"lvglMinFree": 16383}, {"stackLcd": 1024}, {"stackHmi": None}, {"stackCom": True},
                       {"stackFoc": None}, {"stackFoc": 1024}):
            self.assertFalse(t.diag_margins({**good, **change})["passed"], change)
        self.assertFalse(t.diag_margins({})["passed"])
        # 1.0.0-cc5.3: the internal heap's minimum since boot has a floor (it was recorded only).
        self.assertEqual(t.HEAP_MIN_FREE_BYTES, 40000)
        for value, passed in ((40000, True), (39999, False), (0, False), (None, False), ("90000", False), (True, False)):
            self.assertEqual(t.diag_margins({**good, "heapMinFree": value})["passed"], passed, value)
        self.assertFalse(t.diag_margins({k: v for k, v in good.items() if k != "heapMinFree"})["passed"])
        heap = t.diag_margins({**good, "heapMinFree": 57000})["checks"]["heapMinFree"]
        self.assertEqual(heap, {"bytes": 57000, "required": 40000, "passed": True, "previousReleaseBytes": 79692,
                                "deltaFromPreviousBytes": 57000 - 79692})
        # The cc5 reply (no stackFoc) no longer passes: 1.0.0-cc5.1 reports the FOC stack too.
        self.assertFalse(t.diag_margins({k: v for k, v in good.items() if k != "stackFoc"})["passed"])
        recorded = t.diag_margins({**good, "stackUsbd": 12, "txStalls": 3, "psramFree": 0})
        self.assertTrue(recorded["passed"])
        self.assertEqual(recorded["checks"]["stackUsbd"], {"bytes": 12, "recordedOnly": True})

    def test_timing_summaries(self):
        self.assertEqual(t.summarize_ms([]), {"count": 0})
        summary = t.summarize_ms([0.010, 0.020, 0.030, 0.040])
        self.assertEqual((summary["minMs"], summary["medianMs"], summary["maxMs"]), (10.0, 25.0, 40.0))
        self.assertAlmostEqual(t.max_gap([3.0, 1.0, 1.5]), 1.5)
        self.assertIsNone(t.max_gap([1.0]))

    def test_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cc5-x.json"
            self.assertEqual(t.unique_path(path), path)
            self.assertIsNone(t.write_json_evidence(path, {"n": 1}))
            archived = t.write_json_evidence(path, {"n": 2})
            self.assertEqual(json.loads(archived.read_text(encoding="utf-8")), {"n": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"n": 2})
            self.assertIn(".superseded-", archived.name)
            second = t.write_new_json(path, {"n": 3})
            self.assertNotEqual(second, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"n": 2})
            with self.assertRaises(FileExistsError):
                t.write_new_bytes(path, b"x")


class FakeSerial:
    def __init__(self, incoming=b""):
        self.incoming, self.writes, self.closed = bytearray(incoming), [], False

    @property
    def in_waiting(self):
        return len(self.incoming)

    def read(self, size):
        out = bytes(self.incoming[:size])
        del self.incoming[:size]
        return out

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def close(self):
        self.closed = True


@needs_tooling
class RawKnobTests(unittest.TestCase):
    def knob(self, incoming=b"", step=0.01):
        self.serial, self.sleeps = FakeSerial(incoming), []
        return t.RawKnob("COMF", serial_factory=lambda name: self.serial, clock=itertools.count(0, step).__next__,
                         sleep=self.sleeps.append)

    def test_paced_writes_and_line_limit(self):
        knob = self.knob()
        knob.send({"frame": {"title": "x" * 200}})
        self.assertTrue(all(len(w) <= 64 for w in self.serial.writes))
        self.assertEqual(len(self.sleeps), len(self.serial.writes) - 1)
        self.assertTrue(all(s == 0.005 for s in self.sleeps))
        with self.assertRaises(ValueError):
            knob.send({"x": "y" * 5000})
        self.assertEqual(knob.lines_written, {"paced": 1, "whole": 0})

    def test_unpaced_writes_whole_lines_and_waits_for_one_media_ack(self):
        """artwork2 transport (ARTWORK2.md section 3): one write() per line, no sleeps, stop-and-wait."""
        ack = {"mediaAck": {"id": 4, "op": "begin", "kind": "cover", "key": "k1", "offset": 0}}
        knob = self.knob((json.dumps(ack) + "\n").encode())
        with t.pacing(knob, False):
            body = {"id": 4, "op": "begin", "kind": "cover", "key": "k1", "bytes": 10, "crc32": 1}
            reply, seconds = knob.media(body)
            knob.send({"frame": {"title": "x" * 200}})
        self.assertTrue(knob.paced)                                  # restored after the block
        self.assertEqual(reply, ack["mediaAck"])
        self.assertEqual(len(self.serial.writes), 2)                 # one write per line
        self.assertEqual(json.loads(self.serial.writes[0])["media"], body)
        self.assertTrue(all(w.endswith(b"\n") for w in self.serial.writes))
        self.assertEqual(self.sleeps, [])
        self.assertEqual(knob.lines_written, {"paced": 0, "whole": 2})
        with self.assertRaises(ValueError):
            knob.media({"id": 4, "op": "data", "kind": "cover", "key": "k1", "offset": 0, "data": "A" * 5000})

    def test_media_errors_are_collected(self):
        lines = [{"mediaAck": {"id": 4, "op": "data", "kind": "icon", "key": "k", "offset": 0,
                               "error": "No matching media upload"}},
                 {"mediaAck": {"op": "parse", "error": "parse"}}, {"mediaAck": {"id": 4, "op": "have", "have": [True]}}]
        knob = self.knob(b"".join(json.dumps(m).encode() + b"\n" for m in lines))
        knob.pump()
        self.assertEqual([a["error"] for _, a in knob.media_errors], ["No matching media upload", "parse"])
        self.assertEqual(knob.errors, [])

    def test_classification(self):
        lines = [{"error": "Stale control frame"}, {"artAck": {"id": 1, "key": "k", "op": "data", "offset": 0, "error": "Stale artwork selection"}},
                 {"id": 3, "p": 4}, {"p": 5}, {"ks": 1, "kd": 0}, {"ready": 3, "p": 4}, {"released": True, "reason": "lease-expired"}]
        knob = self.knob(b"COM thread started\n" + b"".join(json.dumps(m).encode() + b"\n" for m in lines))
        knob.control_id = 3
        knob.pump()
        self.assertEqual([e for _, e in knob.errors], ["Stale control frame"])
        self.assertEqual(len(knob.art_errors), 1)
        self.assertEqual([m for _, m in knob.claimed_events], [{"id": 3, "p": 4}])
        self.assertEqual([m for _, m in knob.native_events], [{"p": 5}, {"ks": 1, "kd": 0}])
        self.assertEqual([r for _, r in knob.released], ["lease-expired"])
        self.assertIsNone(knob.control_id)

    def test_enter_heartbeat_and_errors(self):
        knob = self.knob(b'{"ready":5,"p":1}\n', step=0.2)
        frame = {"mode": "VOLUME"}
        knob.enter(t.raw_control(5, "BINARIS BEER", 2, 1, frame))
        control = json.loads(b"".join(self.serial.writes))["control"]
        self.assertEqual((control["id"], control["frame"]["id"], control["windowsHidEnabled"]), (5, 5, False))
        self.serial.writes.clear()
        knob.pump(1.0)
        self.assertTrue(any(b'"frame"' in w for w in self.serial.writes))  # heartbeat resent the frame
        knob.heartbeat_seconds, knob.last_frame_at = 0, 0
        self.serial.writes.clear()
        knob.pump(1.0)
        self.assertEqual(self.serial.writes, [])
        bad = self.knob(b'{"error":"Invalid control or unknown existing profile"}\n')
        with self.assertRaises(RuntimeError):
            bad.enter(t.raw_control(6, "NOPE", 2, 1, frame))

    def test_release_is_always_sent_and_cleanup_never_raises(self):
        idle = self.knob(b'{"released":true}\n')
        self.assertIsNone(idle.control_id)
        self.assertEqual(idle.release(), {"released": True})           # sent although nothing is claimed
        self.assertEqual(b"".join(self.serial.writes), b'{"release":true}\n')
        quiet = self.knob()                                             # no reply at all
        quiet.control_id, quiet.latest_frame, quiet.last_frame_at = 7, {"mode": "VOLUME", "id": 7}, 0
        self.assertIsNone(quiet.release_quietly(timeout=0.5))
        self.assertEqual(b"".join(self.serial.writes), b'{"release":true}\n')  # heartbeats stopped first
        self.assertIsNone(quiet.control_id)

        class Dead(FakeSerial):
            def write(self, data):
                raise OSError("port gone")

        dead = t.RawKnob("COMF", serial_factory=lambda name: Dead(), clock=itertools.count(0, 0.01).__next__,
                         sleep=lambda s: None)
        dead.control_id = 3
        self.assertIsNone(dead.release_quietly())
        self.assertIsNone(dead.control_id)

    def test_fixture_frames_cover_the_checks(self):
        v4, v2 = t.fixture_frames()
        self.assertGreaterEqual(len(v2), 10)
        for name in ("v4-home-now-playing", "v4-recent-item-colour", "v4-tracks-no-previous",
                     "v4-home-volume-external-over-idle"):
            self.assertIn(name, v4)
        for name, frame in v2.items():
            self.assertTrue(isinstance(frame.get("mode"), str) and len(frame.get("buttons", [])) == 4, name)
            self.assertNotIn("heading", frame, name)  # recorded v2 frames carry no v4-only field


HEALTHY_LIVENESS = {"hmiAgeMs": 4, "lcdAgeMs": 2, "comAgeMs": 0, "focAgeMs": 0, "hmiStep": "wait",
                    "lcdStep": "wait", "comOp": "diag", "comStage": "line", "taskWdtS": 10,
                    "wdtTasks": ["hmi", "lcd", "com"], "sessionPhase": "idle", "releasePendingMs": 0,
                    "forcedReleases": 0, "lastForced": [], "ledTxTimeouts": 0, "ledWriteErrors": 0,
                    "led": {name: {"frames": 100, "txTimeouts": 0, "writeErrors": 0, "recoveries": 0, "skipped": 0,
                                   "maxWaitUs": 0, "lastErr": "none", "installed": True}
                            for name in ("ring", "buttons")}}


def boot_diag(boot=3, uptime=5000, reason="poweron", **extra):
    """A 1.0.0-cc5.2 diag reply (the fields the reboot and liveness checks read), healthy by default."""
    return {"resetReason": reason, "uptimeMs": uptime, "bootCount": boot, "rxQueue": "internal",
            "coredump": {"blank": True, "present": False, "status": "ESP_ERR_INVALID_SIZE", "bytes": 0},
            **deepcopy_json(HEALTHY_LIVENESS), **extra}


def deepcopy_json(value):
    return json.loads(json.dumps(value))


@needs_tooling
class ReleaseNamingTests(unittest.TestCase):
    """1.0.0-cc5.4 (the cc5.3 -> cc5.4 profile) is the current release everywhere; the cc5.2 -> cc5.3
    and cc4 -> cc5.2 profiles, 1.0.0-cc5 and 1.0.0-cc5.1 stay as history under their own names."""

    def test_release_names(self):
        self.assertEqual(t.CC5_VERSION, "1.0.0-cc5.4")
        self.assertEqual(t.CC5_TAG, "cc5.4")
        self.assertIs(t.CURRENT, t.PROFILES["cc5.4"])
        self.assertEqual(t.CC5_IMAGE.name, "nanod-control-center-1.0.0-cc5.4.bin")
        self.assertEqual(t.CC5_SOURCE_ZIP.name, "nanod-control-center-1.0.0-cc5.4-source.zip")
        self.assertEqual(t.CC5_MANIFEST.name, "manifest-1.0.0-cc5.4.json")
        self.assertEqual(t.EXPECTED_FULL.name, "nanod-cc5.4-expected-full.bin")
        self.assertEqual(t.BUILD_LOG.name, "nanod-cc5.4-build.log")
        self.assertEqual(t.CC4_IMAGE.name, "nanod-control-center-1.0.0-cc4.bin")
        # cc5.4 installs from its own fresh pre-install backup pair.
        self.assertEqual((t.BEFORE_FULL.name, t.ROLLBACK_APP.name),
                         ("nanod-cc5.3-before-cc5.4-full.bin", "nanod-cc5.3-before-cc5.4-active-app.bin"))
        self.assertEqual((t.FROM_VERSION, t.FROM_IMAGE.name, t.FROM_RECORD.name),
                         ("1.0.0-cc5.3", "nanod-control-center-1.0.0-cc5.3.bin", "manifest-cc5.3.json"))
        self.assertEqual([p.name for p in (t.BUILD_REPORT, t.BACKUP_REPORT, t.PREPARATION, t.FLASH_CHECKS,
                                           t.DEVICE_CHECKS, t.LEASE_CHECKS, t.ROLLBACK_REPORT, t.INSTALLATION)],
                         ["cc5.4-build.json", "cc5.4-backup.json", "cc5.4-preparation.json", "cc5.4-flash-checks.json",
                          "cc5.4-device-checks.json", "cc5.4-lease-checks.json", "cc5.4-rollback.json",
                          "cc5.4-installation.json"])
        self.assertEqual(t.SUPERSEDED_CC5_VERSIONS, ("1.0.0-cc5", "1.0.0-cc5.1", "1.0.0-cc5.2", "1.0.0-cc5.3"))
        self.assertEqual(t.release_manifest("1.0.0-cc5.3").name, "manifest-1.0.0-cc5.3.json")
        self.assertEqual(t.release_manifest("1.0.0-cc5").name, "manifest-1.0.0-cc5.json")
        self.assertEqual(t.release_manifest("1.0.0-cc5.1").name, "manifest-1.0.0-cc5.1.json")
        # Old artefacts keep their own names, so nothing of an earlier release is overwritten.
        for version in t.SUPERSEDED_CC5_VERSIONS:
            self.assertNotEqual(t.release_image(version), t.CC5_IMAGE)
            self.assertNotEqual(t.release_source_zip(version), t.CC5_SOURCE_ZIP)
            self.assertNotEqual(t.release_manifest(version), t.CC5_MANIFEST)

    def test_the_cc5_2_profile_keeps_its_history_names(self):
        old = t.PROFILES["cc5.2"]
        self.assertEqual((old.version, old.from_version), ("1.0.0-cc5.2", "1.0.0-cc4"))
        self.assertEqual((old.before_full.name, old.rollback_app.name),
                         ("nanod-cc4-before-cc5-full.bin", "nanod-cc4-before-cc5-active-app.bin"))
        self.assertEqual(old.expected_full.name, "nanod-cc5.2-expected-full.bin")
        self.assertEqual([p.name for p in (old.build_report, old.backup_report, old.preparation, old.flash_checks,
                                           old.device_checks, old.lease_checks, old.rollback_report, old.installation)],
                         ["cc5-build.json", "cc5-backup.json", "cc5-preparation.json", "cc5-flash-checks.json",
                          "cc5-device-checks.json", "cc5-lease-checks.json", "cc5-rollback.json",
                          "cc5-installation.json"])
        self.assertEqual((old.from_record.name, old.restored_outcome), ("manifest-cc4.json", "RESTORED_CC4_RESET"))
        self.assertEqual(old.gates, t.CC52_DEVICE_GATES)
        self.assertEqual(t.PROFILES["cc5.3"].gates, t.CC52_DEVICE_GATES + t.ARTWORK2_DEVICE_GATES)
        self.assertEqual(t.CURRENT.gates, t.CC52_DEVICE_GATES + t.ARTWORK2_DEVICE_GATES + t.ALIVE_DEVICE_GATES
                         + t.PRESENTATION5_DEVICE_GATES)

    def test_the_cc5_3_profile_keeps_its_names_as_history(self):
        """1.0.0-cc5.3 (installed 2026-09-24) is the release cc5.4 upgrades from and rolls back to."""
        old = t.PROFILES["cc5.3"]
        self.assertEqual((old.version, old.from_version, old.tag), ("1.0.0-cc5.3", "1.0.0-cc5.2", "cc5.3"))
        self.assertEqual((old.before_full.name, old.rollback_app.name),
                         ("nanod-cc5.2-before-cc5.3-full.bin", "nanod-cc5.2-before-cc5.3-active-app.bin"))
        self.assertEqual([p.name for p in (old.build_report, old.backup_report, old.preparation, old.flash_checks,
                                           old.device_checks, old.lease_checks, old.rollback_report, old.installation)],
                         ["cc5.3-build.json", "cc5.3-backup.json", "cc5.3-preparation.json", "cc5.3-flash-checks.json",
                          "cc5.3-device-checks.json", "cc5.3-lease-checks.json", "cc5.3-rollback.json",
                          "cc5.3-installation.json"])
        self.assertEqual((old.from_record.name, old.restored_outcome), ("manifest-cc5.2.json", "RESTORED_CC5_2_RESET"))
        self.assertEqual((t.CURRENT.from_version, t.CURRENT.from_record.name, t.CURRENT.restored_outcome),
                         ("1.0.0-cc5.3", "manifest-cc5.3.json", "RESTORED_CC5_3_RESET"))
        self.assertIs(t.ROLLBACK_TARGETS["cc5.3"], t.CURRENT)
        self.assertIs(t.ROLLBACK_TARGETS["cc5.2"], old)

    @machine_runbook
    def test_superseded_release_files_are_kept(self):
        """The cc5, cc5.1 and cc5.2 artefacts in firmware/ are history: present and never renamed away."""
        for version in t.SUPERSEDED_CC5_VERSIONS:
            for path in (t.release_image(version), t.release_source_zip(version), t.release_manifest(version)):
                if t.FIRMWARE_OUT.is_dir():
                    self.assertTrue(path.is_file(), path)

    def test_firmware_version_string_matches_the_tooling(self):
        """The firmware tree builds the newest profile (1.0.0-cc5.4, NEWEST); CURRENT is that profile or the
        one before it, which the release tooling moves on when the newest release's window opens."""
        ini = t.FIRMWARE_SOURCE / "platformio.ini"
        if not ini.is_file():
            self.skipTest("firmware checkout not present")
        self.assertIs(t.NEWEST, list(t.PROFILES.values())[-1])
        self.assertEqual(t.NEWEST.version, "1.0.0-cc5.4")
        self.assertIn(f'-DNANO_FIRMWARE_VERSION=\\"{t.NEWEST.version}\\"', ini.read_text(encoding="utf-8"))
        profiles = list(t.PROFILES.values())
        self.assertIn(profiles.index(t.CURRENT), (len(profiles) - 1, len(profiles) - 2))

    def test_every_script_names_the_release_through_the_tooling(self):
        """No script hard-codes a superseded version where the release is meant."""
        for name in ("build_nanod_cc5.py", "package_nanod_cc5.py", "prepare_nanod_cc5_install.py",
                     "install_nanod_cc5.py", "rollback_nanod_cc5.py", "check_nanod_cc5.py", "finalize_nanod_cc5.py",
                     "backup_nanod_cc5.py", "check_nanod_cc5_lease.py"):
            code = [n.value for n in ast.walk(ast.parse((WORK / name).read_text(encoding="utf-8")))
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            bad = [s for s in code if re.search(r"(manifest-|control-center-)1\.0\.0-cc5(?:\.[12])?(?![.\d])", s)]
            self.assertEqual(bad, [], name)
            # The release itself is always t.CURRENT.version, never a literal of a superseded one.
            literal = [s for s in code if s in t.SUPERSEDED_CC5_VERSIONS and name != "package_nanod_cc5.py"]
            self.assertEqual(literal, [], name)


@needs_tooling
class FirmwareFixStaticTests(unittest.TestCase):
    """The 1.0.0-cc5.1 firmware fixes, read (never built or run) from the firmware sources."""

    def setUp(self):
        self.src = t.FIRMWARE_SOURCE / "src"
        if not (self.src / "hmi_thread.cpp").is_file():
            self.skipTest("firmware checkout not present")

    def read(self, name):
        return (self.src / name).read_text(encoding="utf-8")

    def test_task_stacks_have_at_least_twice_the_measured_worst_case(self):
        hmi, lcd = self.read("hmi_thread.cpp"), self.read("lcd_thread.cpp")
        self.assertRegex(hmi, r"constexpr uint32_t kHmiStackBytes = 9216;")
        self.assertIn('Thread("HMI", kHmiStackBytes, 1, task_core)', hmi)
        self.assertGreaterEqual(9216, 2 * 4252)            # static worst case with overheads
        self.assertRegex(lcd, r"kLcdStackBytes = 12288;")
        self.assertIn('Thread("LCD", kLcdStackBytes, 1, task_core)', lcd)
        self.assertGreaterEqual(12288, 2 * 5588)           # measured after the cc5 stress

    def test_hmi_config_receivers_are_out_of_line(self):
        hmi, header = self.read("hmi_thread.cpp"), self.read("hmi_thread.h")
        body = hmi[hmi.index("void HmiThread::handleConfig() {"):hmi.index("void HmiThread::receiveLedConfig() {")]
        self.assertNotIn("hmiConfig newHmiConfig", body)
        self.assertNotIn("ledConfig newConfig", body)
        self.assertIn("if (_hmi_config_pending) receiveHmiConfig();", body)
        self.assertIn("__attribute__((noinline)) void receiveHmiConfig();", header)
        self.assertIn("__attribute__((noinline)) void receiveLedConfig();", header)

    def test_hmi_config_never_crosses_a_queue(self):
        """hmiConfig holds Strings (keyAction::profile). A queue's bitwise copy let the receiving
        local's destructor free the profile's buffers (names of 11+ chars), so COM hands it over
        through one slot under a mutex, copied as Strings on both sides."""
        hmi, header = self.code(self.read("hmi_thread.cpp")), self.code(self.read("hmi_thread.h"))
        self.assertIsNone(re.search(r"sizeof\(\s*hmiConfig\s*\)", hmi))
        self.assertNotIn("_q_hmi_config_in", hmi + header)
        self.assertNotIn("hmiConfig newHmiConfig", hmi)
        self.assertIn("hmiConfig _pending_hmi_config;", header)
        put = hmi[hmi.index("void HmiThread::put_hmi_config("):hmi.index("void HmiThread::put_settings(")]
        take = hmi[hmi.index("void HmiThread::receiveHmiConfig() {"):hmi.index("void HmiThread::handleSettings() {")]
        self.assertIn("_pending_hmi_config = new_config;", put)
        self.assertIn("hmi_config = _pending_hmi_config;", take)
        for body in (put, take):
            self.assertLess(body.index("xSemaphoreTake(_hmi_config_mutex"), body.index("_pending_hmi_config"))
            self.assertLess(body.rindex("_pending_hmi_config"), body.index("xSemaphoreGive(_hmi_config_mutex);"))

    def rx_queue_size(self, main):
        """The CDC receive queue main.cpp asks for: a literal, or cc_media.h's CC_MEDIA_RX_BYTES (1.0.0-cc5.3)."""
        size = re.search(r"Serial\.setRxBufferSize\((\w+)\)", main).group(1)
        if size.isdigit():
            return int(size)
        media = self.read("cc_media.h")
        return int(re.search(rf"constexpr uint32_t {size} = (\d+);", media).group(1))

    def test_receive_queue_is_allocated_internal(self):
        main = self.code(self.read("main.cpp"))
        raised = main.index("heap_caps_malloc_extmem_enable(")
        rx = main.index("Serial.setRxBufferSize(")
        restored = main.index("heap_caps_malloc_extmem_enable(CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL)")
        self.assertLess(raised, rx)
        self.assertLess(rx, restored)
        self.assertLess(rx, main.index("Serial.begin("))
        self.assertLess(main.index("cc_boot_begin();"), main.index("TinyUSBDevice.begin();"))
        # 1.0.0-cc5.3 (ARTWORK2.md section 3): an 8192-byte queue, the artwork2 rxBytes, and the
        # internal-allocation limit raised above it (the storage and the Queue_t are one allocation).
        size = self.rx_queue_size(main)
        self.assertEqual(size, t.artwork2_capability()["rxBytes"])
        limit = re.search(r"if \(psramMallocPolicy\) heap_caps_malloc_extmem_enable\(([^)]*)\);", main).group(1)
        factors = [int(f) if f.strip().isdigit() else size for f in limit.split("*")]   # "16384" or "2 * CC_MEDIA_RX_BYTES"
        self.assertGreater(factors[0] if len(factors) == 1 else factors[0] * factors[1], size)

    def test_malloc_policy_is_touched_only_when_psram_initialised(self):
        """A failed PSRAM init never changes the global malloc policy (psramInit() did not set it)."""
        main = self.code(self.read("main.cpp"))
        guard = main.index("const bool psramMallocPolicy = psramFound() && esp_spiram_is_initialized();")
        self.assertLess(guard, main.index("if (psramMallocPolicy) heap_caps_malloc_extmem_enable("))
        self.assertIn("if (psramMallocPolicy) heap_caps_malloc_extmem_enable(CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL);", main)
        self.assertEqual(main.count("heap_caps_malloc_extmem_enable("), 2)       # both calls guarded
        self.assertEqual(main.count("if (psramMallocPolicy) heap_caps_malloc_extmem_enable("), 2)

    @staticmethod
    def code(text):
        """Source without // comments (the checks read code, not the explanations)."""
        return "\n".join(line.split("//", 1)[0] for line in text.splitlines())

    def test_a_cut_reply_line_is_ended_so_the_next_reply_survives(self):
        out = self.read("cc_serial_out.cpp")
        body = out[out.index("void send_reply("):out.index("void cc_send_json(")]
        self.assertIn("if (lineOpen) {", body)                                 # end the open line first
        self.assertIn("fifo_write(&kNewline, 1, done)", body)
        self.assertIn("if (written) end_cut_line();", body)
        self.assertIn("++stalls; dropped += static_cast<uint32_t>(total - written);", body)   # still counted
        self.assertIn("++stalls; dropped += static_cast<uint32_t>(total);", body)
        cut = out[out.index("void end_cut_line() {"):out.index("void send_reply(")]
        self.assertIn("Serial.availableForWrite() > 0 && Serial.write(&kNewline, 1) == 1", cut)
        self.assertIn("lineOpen = true;", cut)
        self.assertNotIn("bounded_write(", out)                                 # every reply goes through send_reply

    def test_diag_reports_reboot_fields_and_replies_are_bounded(self):
        diag, cc = self.read("cc_diag.cpp"), self.read("control_center.cpp")
        for field in ("resetReason", "uptimeMs", "bootCount", "rtcReset", "previous", "coredump", "rxQueue"):
            self.assertIn(f'"{field}"', diag, field)
        self.assertIn("RTC_NOINIT_ATTR", diag)
        self.assertNotIn("esp_core_dump_image_erase", diag)        # read-only
        for field in ("stackFoc", "stackUsbd", "txStalls"):
            self.assertIn(f'd["{field}"]', cc, field)
        self.assertNotIn("serializeJson(out, Serial)", cc)
        self.assertNotIn("serializeJson(out, Serial)", self.read("cc_artwork.cpp"))


@needs_tooling
class HangFixStaticTests(unittest.TestCase):
    """The 1.0.0-cc5.2 firmware fixes, read (never built or run) from the firmware sources."""

    def setUp(self):
        self.src = t.FIRMWARE_SOURCE / "src"
        if not (self.src / "cc_led_rmt.cpp").is_file():
            self.skipTest("firmware checkout not present")

    def read(self, name):
        return (self.src / name).read_text(encoding="utf-8")

    @staticmethod
    def code(text):
        """Source without // comments (enough for these single-line checks)."""
        return "\n".join(line.split("//", 1)[0] for line in text.splitlines())

    def test_fastled_clockless_controllers_are_gone(self):
        """FastLED's ESP32 RMT driver (the hang) is never instantiated; FastLED.show() is kept."""
        for path in sorted(self.src.rglob("*.[ch]*")):
            self.assertNotRegex(self.code(path.read_text(encoding="utf-8", errors="replace")), r"addLeds\s*<",
                                path.name)
        hmi = self.code(self.read("hmi_thread.cpp"))
        self.assertIn("FastLED.addLeds(&ringLeds, leds, NANO_LED_A_NUM);", hmi)
        self.assertIn("FastLED.addLeds(&buttonLeds, ledsp, NANO_LED_B_NUM);", hmi)
        self.assertIn('CCRmtStrip ringStrip("ring", RMT_CHANNEL_0, static_cast<gpio_num_t>(PIN_LED_A), '
                      "CC_HMI_STEP_SHOW_RING);", hmi)
        self.assertIn('CCRmtStrip buttonStrip("buttons", RMT_CHANNEL_2, static_cast<gpio_num_t>(PIN_LED_B), '
                      "CC_HMI_STEP_SHOW_BUTTONS);", hmi)
        self.assertIn("CCLedController<RGB, NANO_LED_A_NUM> ringLeds(ringStrip);", hmi)
        self.assertIn("CCLedController<LED_COL_ORDER, NANO_LED_B_NUM> buttonLeds(buttonStrip);", hmi)
        self.assertEqual(hmi.count("FastLED.show();"), 1)
        # The physical mapping is untouched. 1.0.0-cc5.4 (ALIVE.md 9, 10.1): while the engine owns the LEDs
        # its bytes go out at FastLED brightness 255 without FastLED's dither (the engine applies its drive
        # and temporal dither itself), which replaces cc5.3's 51 cap on the claimed path.
        self.assertIn("leds[cc_ring_address(i, orientation)] = CRGB(cc_light_ring[i]);", hmi)
        self.assertIn("FastLED.setBrightness(255);", hmi)
        self.assertIn("FastLED.setDither(DISABLE_DITHER);", hmi)
        self.assertIn("cc_alive_drive(", hmi)

    def test_controller_produces_bytes_like_fastled(self):
        header = self.code(self.read("cc_led_rmt.h"))
        body = header[header.index("void showPixels(PixelController<ORDER>& pixels) override {"):]
        order = [body.index(s) for s in ("pixels.has(1)", "pixels.loadAndScale0()", "pixels.loadAndScale1()",
                                         "pixels.loadAndScale2()", "pixels.advanceData()", "pixels.stepDithering()",
                                         "strip_.send(")]
        self.assertEqual(order, sorted(order))
        self.assertIn("uint16_t getMaxRefreshRate() const override { return 400; }", header)
        self.assertIn("uint32_t items_[LEDS * 3 * CC_LED_ITEMS_PER_BYTE];", header)
        wire = self.read("cc_led_wire.h")
        for text in ("CC_LED_RMT_CLK_DIV = 2", "CC_LED_ONE_HIGH_TICKS = 25", "CC_LED_ONE_LOW_TICKS = 25",
                     "CC_LED_ZERO_HIGH_TICKS = 12", "CC_LED_ZERO_LOW_TICKS = 38"):
            self.assertIn(text, wire)

    def test_every_rmt_wait_is_bounded(self):
        rmt = self.code(self.read("cc_led_rmt.cpp"))
        self.assertNotIn("portMAX_DELAY", rmt)
        self.assertEqual(re.findall(r"rmt_wait_tx_done\(([^)]*)\)", rmt), ["channel_, 0", "channel_, 0"])
        [write] = re.findall(r"rmt_write_items\((.*?)\);", rmt, re.S)
        self.assertTrue(write.replace("\n", " ").strip().endswith("false"), write)       # never wait_tx_done
        self.assertIn("constexpr uint32_t kIdleGraceUs = 5000;", rmt)
        self.assertIn("ESP_INTR_FLAG_IRAM | ESP_INTR_FLAG_LEVEL3", rmt)
        self.assertIn("constexpr uint8_t kMemBlocks = 2;", rmt)
        recover = rmt[rmt.index("void CCRmtStrip::recover() {"):rmt.index("void CCRmtStrip::failed() {")]
        order = [recover.index(s) for s in ("CC_HMI_STEP_LED_RECOVER", "rmt_tx_stop(channel_)",
                                            "rmt_driver_uninstall(channel_)", "install();")]
        self.assertEqual(order, sorted(order))
        send = rmt[rmt.index("void CCRmtStrip::send("):rmt.index("void cc_led_diag(")]
        order = [send.index(s) for s in ("cc_crumb_hmi(crumb_)", "waitIdle()", "cc_led_encode(", "rmt_write_items(")]
        self.assertEqual(order, sorted(order))
        self.assertIn("++stats_.txTimeouts;", send)

    def test_task_watchdog_covers_hmi_lcd_and_com(self):
        diag = self.read("cc_diag.h")
        self.assertIn("constexpr uint32_t CC_TASK_WDT_SECONDS = 10;", diag)
        main = self.code(self.read("main.cpp"))
        self.assertLess(main.index("cc_boot_begin();"), main.index("cc_wdt_begin();"))
        self.assertLess(main.index("cc_wdt_begin();"), main.index("hmi_thread.begin();"))
        self.assertIn("esp_task_wdt_init(CC_TASK_WDT_SECONDS, true)", self.read("cc_diag.cpp"))
        for name, task in (("hmi_thread.cpp", "CC_LIVE_HMI"), ("lcd_thread.cpp", "CC_LIVE_LCD"),
                           ("com_thread.cpp", "CC_LIVE_COM")):
            code = self.code(self.read(name))
            self.assertIn(f"cc_wdt_watch({task});", code, name)
            self.assertIn("cc_wdt_feed();", code, name)
        self.assertNotIn("cc_wdt", self.read("foc_thread.cpp"))                 # FOC: focAgeMs only
        com = self.code(self.read("com_thread.cpp"))
        for flash in ("DeviceSettings::getInstance().toSPIFFS();", "DeviceSettings::getInstance().fromSPIFFS();"):
            at = com.index(flash)
            self.assertLess(com.rindex("cc_wdt_unwatch(CC_LIVE_COM);", 0, at), at, flash)
            self.assertGreater(com.index("cc_wdt_watch(CC_LIVE_COM);", at), at, flash)
        hmi = self.code(self.read("hmi_thread.cpp"))
        run = hmi[hmi.index("void HmiThread::run() {"):hmi.index("HmiThreadButtonHandler::HmiThreadButtonHandler")]
        self.assertNotIn("Serial.", run)
        self.assertEqual(hmi.count('hmi_note("'), 2)                            # the two HMI debug lines

    def test_release_is_forced_only_past_presentation_acks(self):
        cc = self.code(self.read("control_center.cpp"))
        self.assertIn("constexpr uint32_t kReleaseAckMs = 1000;", cc)
        service = cc[cc.index("void cc_service() {"):cc.index("void cc_diag_lcd(")]
        self.assertIn("if (phase == 3 && !requestPending && motorId == 0) {", service)
        self.assertIn("static_cast<uint32_t>(millis() - releaseAt) >= kReleaseAckMs", service)
        self.assertIn('out["reason"] = "forced";', service)
        self.assertIn('add_forced(out["unacked"].to<JsonArray>(), forced);', service)
        self.assertIn('out["reason"] = "lease-expired";', service)
        self.assertIn("++forcedReleases;", service)
        self.assertIn("releaseAt = millis();", cc[cc.index("void release_locked("):cc.index("void add_forced(")])
        self.assertIn("cc_live_foc();", cc[cc.index("bool cc_take_request("):cc.index("void cc_motor_applied(")])

    def test_diag_reports_liveness_led_and_release_fields(self):
        cc, diag, led = self.read("control_center.cpp"), self.read("cc_diag.cpp"), self.read("cc_led_rmt.cpp")
        for field in ("hmiAgeMs", "lcdAgeMs", "comAgeMs", "focAgeMs", "hmiStep", "lcdStep", "comStage",
                      "taskWdtS", "wdtTasks", "lastAliveMs", "aliveMs"):
            self.assertIn(f'"{field}"', diag, field)
        for field in ("sessionPhase", "releasePendingMs", "forcedReleases", "lastForced"):
            self.assertIn(f'd["{field}"]', cc, field)
        for field in ("ledTxTimeouts", "ledWriteErrors", "txTimeouts", "writeErrors", "recoveries", "skipped",
                      "maxWaitUs", "lastErr", "installed"):
            self.assertIn(f'"{field}"', led, field)
        self.assertLess(cc.index("cc_diag_boot(d);"), cc.index("cc_diag_live(d);"))   # additive, after cc5.1
        self.assertIn('"show-ring", "show-buttons", "led-recover"', diag)
        # The RTC breadcrumb layout: 0x4E44B008 in 1.0.0-cc5.2, 0x4E44B009 in the 1.0.0-cc5.3 source this
        # reads (its wider COM op field). A layout change must change this pin with it.
        magic = int(re.search(r"constexpr uint32_t kMagic = (0x[0-9A-Fa-f]+)u;", diag).group(1), 16)
        self.assertEqual(magic, 0x4E44B009)
        header = self.read("cc_diag.h")
        self.assertIn("CC_HMI_STEP_SHOW, CC_HMI_STEP_SHOW_RING, CC_HMI_STEP_SHOW_BUTTONS, CC_HMI_STEP_LED_RECOVER",
                      header)

    def test_hmi_copies_the_host_frame_only_when_the_presentation_changed(self):
        hmi = self.code(self.read("hmi_thread.cpp"))
        snapshot = hmi[hmi.index("bool hmi_snapshot(uint32_t& id) {"):hmi.index("CCRmtStrip ringStrip(")]
        self.assertLess(snapshot.index("cc_presentation_state()"), snapshot.index("cc_snapshot("))
        self.assertIn("if (!primed || state != seen) {", snapshot)
        self.assertEqual(hmi.count("cc_snapshot("), 1)
        self.assertEqual(hmi.count("hmi_snapshot(id)"), 2)                        # updateLeds, updateKeyLeds


@needs_tooling
class LivenessHelperTests(unittest.TestCase):
    def test_healthy_reply_passes(self):
        self.assertEqual(t.liveness_problems(boot_diag()), [])
        summary = t.liveness_summary(boot_diag())
        self.assertEqual((summary["hmiAgeMs"], summary["ledTxTimeouts"], summary["forcedReleases"]), (4, 0, 0))
        self.assertEqual(t.LIVENESS_MAX_AGE_MS, 1000)

    def test_any_age_over_a_second_is_a_stall(self):
        self.assertEqual(t.liveness_problems(boot_diag(hmiAgeMs=1000)), [])          # at the limit: fine
        [stall] = t.liveness_problems(boot_diag(hmiAgeMs=1001, hmiStep="show-buttons"))
        self.assertIn("TASK STALLED: hmiAgeMs 1001 ms > 1000 ms at step 'show-buttons'", stall)
        for name in t.LIVENESS_AGE_FIELDS:
            self.assertEqual(len(t.liveness_problems(boot_diag(**{name: 60000}))), 1, name)
        self.assertIn("not an integer", t.liveness_problems(boot_diag(focAgeMs="3"))[0])

    def test_led_failures_and_forced_releases_fail(self):
        self.assertIn("LED TRANSMIT TIMEOUT", t.liveness_problems(boot_diag(ledTxTimeouts=1))[0])
        self.assertIn("LED DRIVER ERROR", t.liveness_problems(boot_diag(ledWriteErrors=2))[0])
        down = boot_diag()
        down["led"]["buttons"]["installed"] = False
        self.assertEqual(t.liveness_problems(down), ["LED strip(s) not installed: buttons"])
        forced = t.liveness_problems(boot_diag(forcedReleases=1, lastForced=["hmi"]))
        self.assertEqual(len(forced), 1)
        self.assertIn("FORCED RELEASE", forced[0])
        self.assertIn("['hmi']", forced[0])
        self.assertEqual(t.forced_release_problems({"released": True}), [])
        self.assertEqual(t.forced_release_problems({"released": True, "reason": "lease-expired"}), [])
        self.assertIn("['lcd']", t.forced_release_problems({"released": True, "reason": "forced",
                                                              "unacked": ["lcd"]})[0])

    def test_a_cc5_1_reply_fails(self):
        old = {k: v for k, v in boot_diag().items() if k not in HEALTHY_LIVENESS}
        [problem] = t.liveness_problems(old)
        self.assertIn("diag lacks hmiAgeMs, lcdAgeMs, comAgeMs, focAgeMs, ledTxTimeouts, forcedReleases", problem)
        self.assertEqual(t.liveness_problems(None), ["no diag reply"])

    def test_soak_defaults(self):
        self.assertEqual((t.SOAK_DEFAULT_MINUTES, t.SOAK_GATE_MINUTES), (20.0, 20.0))
        self.assertEqual((t.SOAK_CHECKPOINT_SECONDS, t.SOAK_CYCLE_SECONDS), (10.0, 30.0))


@needs_tooling
class RebootDetectionTests(unittest.TestCase):
    def test_boot_fields_and_reboot_problems(self):
        self.assertEqual(t.boot_fields_problems(boot_diag()), [])
        self.assertIn("older than", t.boot_fields_problems({"lvglFree": 1})[0])     # a 1.0.0-cc5 reply
        self.assertEqual(t.boot_fields_problems(None), ["no diag reply"])
        self.assertTrue(t.boot_fields_problems(boot_diag(uptime="5")))
        self.assertEqual(t.reboot_problems(boot_diag(), boot_diag(uptime=9000)), [])
        again = t.reboot_problems(boot_diag(), boot_diag(boot=4, uptime=900, reason="brownout"))
        self.assertEqual(len(again), 2)
        self.assertTrue(all("REBOOT" in p and "brownout" in p for p in again))
        self.assertEqual(len(t.reboot_problems(boot_diag(), boot_diag(uptime=10))), 1)    # uptime back, same count
        self.assertEqual(len(t.reboot_problems(boot_diag(), boot_diag(boot=4, uptime=99999))), 1)
        self.assertTrue(t.reboot_problems({"lvglFree": 1}, boot_diag()))

    def test_coredump_must_be_blank(self):
        self.assertEqual(t.coredump_problems(boot_diag()), [])
        present = boot_diag(coredump={"blank": False, "present": True, "status": "ESP_OK", "bytes": 12000})
        self.assertIn("Do not erase it", t.coredump_problems(present)[0])
        partial = boot_diag(coredump={"blank": False, "present": False, "status": "ESP_ERR_INVALID_CRC", "bytes": 0})
        self.assertIn("not blank", t.coredump_problems(partial)[0])
        self.assertTrue(t.coredump_problems({"coredump": {"status": "unchecked"}}))
        self.assertTrue(t.coredump_problems({}))

    def test_turning_needs_twenty_claimed_position_events(self):
        events = [(0.1 * n, {"id": 7, "p": n}) for n in range(30)] + [(1.0, {"id": 7, "kd": 1, "ks": 1}),
                                                                     (1.1, {"p": 3}), (1.2, {"id": 8, "p": 1})]
        times = t.claimed_positions(events, 7, 0.0, 1.95)
        self.assertEqual(len(times), 20)            # presses, native and other-control events never count
        self.assertEqual(t.turning_problems(times, (0.0, 1.95)), [])
        short = t.turning_problems(times[:19], (0.0, 1.95))
        self.assertIn("turning not detected during stress; rerun", short[0])
        self.assertIn("19 claimed position event(s) inside the stress-frame window", short[0])
        self.assertIn("FAIL to rerun", short[0])
        self.assertEqual((t.TURN_MIN_EVENTS, t.TURN_MAX_GAP_S), (20, 3.0))

    def test_arrival_problems(self):
        self.assertEqual(t.arrival_problems(None, "x"), [])
        self.assertEqual(t.arrival_problems("a", "a"), [])
        self.assertIn("RE-ENUMERATION", t.arrival_problems("a", "b")[0])
        self.assertIn("not present", t.arrival_problems("a", None)[0])

    def test_pnp_arrival_is_a_hidden_read_only_query(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout="2026-09-23T16:16:37.1234567Z\r\n", stderr="")

        self.assertEqual(t.pnp_last_arrival(run=fake_run), "2026-09-23T16:16:37.1234567Z")
        command, kwargs = calls[0]
        self.assertEqual(command[:3], ["powershell.exe", "-NoProfile", "-NonInteractive"])
        self.assertIn("DEVPKEY_Device_LastArrivalDate", command[-1])
        self.assertIn(r"USB\VID_239A&PID_8010\*", command[-1])
        self.assertEqual(kwargs.get("creationflags"), getattr(t.subprocess, "CREATE_NO_WINDOW", 0))
        for text in ("Set-", "Remove-", "Enable-", "Disable-", "Restart-"):
            self.assertNotIn(text, command[-1])
        self.assertIsNone(t.pnp_last_arrival(run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr="")))
        self.assertIsNone(t.pnp_last_arrival(run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="x", stderr="")))

        def broken(*a, **k):
            raise OSError("no powershell")
        self.assertIsNone(t.pnp_last_arrival(run=broken))

    def test_port_watch_records_every_absence(self):
        present, clock = [True], itertools.count(0, 0.2).__next__
        watch = t.PortWatch(lister=lambda: [APP()] if present[0] else [ROM()], clock=clock)
        watch.poll_once()
        self.assertEqual(watch.take(), [])
        present[0] = False
        watch.poll_once()
        ongoing = watch.take()
        self.assertEqual(len(ongoing), 1)
        self.assertTrue(ongoing[0]["ongoing"])
        present[0] = True
        watch.poll_once()
        [back] = watch.take()
        self.assertGreater(back["seconds"], 0)
        self.assertEqual(watch.take(), [])

        def flaky():
            raise OSError("enumeration hiccup")
        quiet = t.PortWatch(lister=flaky, clock=clock)
        quiet.poll_once()
        self.assertEqual(quiet.take(), [])        # an enumeration error is not a knob event

    def test_raw_diag_and_probe(self):
        line = (json.dumps({"diag": boot_diag()}) + "\n").encode()
        serial = FakeSerial(line)
        knob = t.RawKnob("COMF", serial_factory=lambda name: serial, clock=itertools.count(0, 0.01).__next__,
                         sleep=lambda s: None)
        self.assertEqual(knob.diag()["bootCount"], 3)
        self.assertEqual(b"".join(serial.writes), b'{"diag":"?"}\n')
        closed = []

        class Knob:
            def __init__(self, device):
                self.device = device

            def pump(self, seconds):
                pass

            def diag(self):
                return boot_diag(uptime=1)

            def close(self):
                closed.append(self.device)

        self.assertEqual(t.probe_diag("FAKEAPP", knob_factory=Knob)["uptimeMs"], 1)
        self.assertEqual(closed, ["FAKEAPP"])


@needs_tooling
class TurningTimelineTests(unittest.TestCase):
    """The stress+turn gate over fake event timelines: only events inside the stress-frame window
    count, at least 20 of them, and no pause over 3 s from the window's start to its end."""

    STRESS = (10.0, 40.0)          # the stress-frame window; cold transfers run in 0..10 s before it

    @staticmethod
    def ticks(start, end, step):
        """Event times from `start` up to `end` (inclusive), every `step` seconds."""
        count = int(round((end - start) / step))
        return [round(start + n * step, 6) for n in range(count + 1)]

    def problems(self, times):
        return t.turning_problems(times, self.STRESS)

    def test_continuous_turning_through_the_stress_passes(self):
        times = self.ticks(2.0, 41.0, 0.25)                  # from the prompt until after the window
        self.assertEqual(self.problems(times), [])
        inside, gap = t.turning_in_window(times, self.STRESS)
        self.assertEqual(len(inside), 121)
        self.assertAlmostEqual(gap, 0.25)

    def test_turning_only_during_the_replay_transfers_fails(self):
        """The loophole this closes: 79 events, all during the cold transfers before the stress."""
        times = self.ticks(0.1, 9.9, 0.125)
        self.assertGreaterEqual(len(times), 20)              # the old whole-section count passed this
        [problem] = self.problems(times)
        self.assertTrue(problem.startswith("turning not detected during stress; rerun"))
        self.assertIn("0 claimed position event(s) inside the stress-frame window", problem)
        self.assertIn("a 30.0 s pause", problem)
        self.assertIn("FAIL to rerun", problem)

    def test_too_few_events_inside_the_window_fails_even_with_many_outside(self):
        times = self.ticks(0.0, 9.9, 0.1) + self.ticks(10.0, 40.0, 1.6)   # 19 inside, all < 3 s apart
        inside, gap = t.turning_in_window(times, self.STRESS)
        self.assertEqual(len(inside), 19)
        self.assertLessEqual(gap, t.TURN_MAX_GAP_S)
        [problem] = self.problems(times)
        self.assertIn("19 claimed position event(s)", problem)
        self.assertNotIn("pause", problem)
        self.assertEqual(self.problems(times + [40.0 - 0.8]), [])        # the 20th event passes

    def test_a_pause_over_three_seconds_inside_the_window_fails(self):
        times = self.ticks(10.0, 20.0, 0.2) + self.ticks(23.5, 40.0, 0.2)   # 3.5 s without an event
        [problem] = self.problems(times)
        self.assertIn("a 3.5 s pause without a claimed position event inside the stress-frame window", problem)
        self.assertIn("(at most 3 s)", problem)
        self.assertNotIn("event(s) inside", problem)                     # the count itself is fine

    def test_a_pause_of_exactly_three_seconds_passes(self):
        times = self.ticks(10.0, 20.0, 0.25) + self.ticks(23.0, 40.0, 0.25)
        self.assertAlmostEqual(t.turning_in_window(times, self.STRESS)[1], 3.0)
        self.assertEqual(self.problems(times), [])

    def test_turning_that_stops_before_the_stress_ends_fails(self):
        times = self.ticks(2.0, 25.0, 0.1)                   # 151 events inside, then 15 s of nothing
        inside, gap = t.turning_in_window(times, self.STRESS)
        self.assertEqual(len(inside), 151)
        self.assertAlmostEqual(gap, 15.0)
        self.assertIn("a 15.0 s pause", self.problems(times)[0])

    def test_turning_that_starts_late_in_the_stress_fails(self):
        times = self.ticks(0.5, 5.0, 0.1) + self.ticks(14.0, 41.0, 0.1)   # replay turned, stress start not
        [problem] = self.problems(times)
        self.assertIn("a 4.0 s pause", problem)

    def test_events_on_the_window_edges_count_and_order_does_not_matter(self):
        times = list(reversed(self.ticks(10.0, 40.0, 1.5)))              # 21 events, first and last on the edges
        inside, gap = t.turning_in_window(times, self.STRESS)
        self.assertEqual((len(inside), inside[0], inside[-1]), (21, 10.0, 40.0))
        self.assertAlmostEqual(gap, 1.5)
        self.assertEqual(self.problems(times), [])

    def test_no_events_at_all_names_both_reasons(self):
        [problem] = self.problems([])
        self.assertIn("0 claimed position event(s)", problem)
        self.assertIn("a 30.0 s pause", problem)
        self.assertEqual(t.turning_in_window([], self.STRESS), ([], 30.0))


def load_check_script():
    return load_script("check_nanod_cc5.py")


class FakeWatchReport:
    def __init__(self):
        self.data, self.results = {"failures": []}, []
        self.gates = {}

    def check(self, name, ok, detail=None):
        self.results.append((name, bool(ok), detail))
        if not ok:
            self.data["failures"].append(name)
        return ok


class FakePortWatch:
    def __init__(self):
        self.pending, self.started, self.stopped = [], False, False

    def start(self):
        self.started = True

    def take(self):
        out, self.pending = self.pending, []
        return out

    def stop(self):
        self.stopped = True


MEDIA_KEY = re.compile(r"[A-Za-z0-9_-]{1,24}")


def media_key_ok(value):
    return isinstance(value, str) and MEDIA_KEY.fullmatch(value) is not None


# A JSON integer as the firmware's ArduinoJson 7 stores one: no fraction or exponent, within
# int64 or uint64 (-2^63 .. 2^64-1; a longer integer parses as a float there), never a bool.
JSON_INT_MIN, JSON_INT_MAX = -2 ** 63, 2 ** 64 - 1


def json_int(value):
    return type(value) is int and JSON_INT_MIN <= value <= JSON_INT_MAX


# SOF types other than baseline SOF0 (progressive, extended, lossless, arithmetic) and EOI: before SOS
# each of them rejects the cover.
TJPGD_REJECTS = frozenset((0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF, 0xD9))


def tjpgd_accepts(data):
    """The firmware's commit-time cover check, cc_jpeg_validate (src/cc_jpeg.cpp), which "Media decode
    failed" answers (ARTWORK2.md 4.3).

    Its marker pre-scan: at most COVER_MAX_BYTES, SOI first and EOI (FF D9) as the LAST two bytes (a
    cover cut short, or followed by trailing bytes, is refused), every segment 0xFF + marker + a length
    > 2 inside the data, one SOF0 with 8-bit samples and three components before SOS, no other SOF type
    and no EOI before SOS. Then what the ROM TJpgDec's prepare reads from that SOF0 (luma sampling 1x1,
    2x1 or 2x2, chroma 1x1, quantisation table ids 0..3) and exactly COVER_SIZE x COVER_SIZE. The scan
    itself is not decoded at commit: a scan damaged in the middle that still ends with EOI passes here
    and shows later as an LCD decode error (jpegDecodeErrors), as on the knob.
    """
    contract = t.presentation()
    size = len(data)
    if (not 4 <= size <= contract.COVER_MAX_BYTES or data[:2] != b"\xff\xd8"
            or data[-2:] != b"\xff\xd9"):
        return False
    at, frame = 2, None
    while True:
        if size - at < 4 or data[at] != 0xFF:
            return False
        marker, length = data[at + 1], int.from_bytes(data[at + 2:at + 4], "big")
        if length <= 2 or length > size - at - 2:
            return False
        body = data[at + 4:at + 2 + length]
        if marker == 0xC0:
            if frame is not None or length < 8 or body[0] != 8 or body[5] != 3:
                return False
            frame = body
        elif marker == 0xDA:
            break
        elif marker in TJPGD_REJECTS:
            return False
        at += 2 + length
    if frame is None or len(frame) < 6 + 3 * 3:
        return False
    sampling, tables = [frame[7 + 3 * i] for i in range(3)], [frame[8 + 3 * i] for i in range(3)]
    if sampling[0] not in (0x11, 0x21, 0x22) or sampling[1:] != [0x11, 0x11] or max(tables) > 3:
        return False
    height, width = int.from_bytes(frame[1:3], "big"), int.from_bytes(frame[3:5], "big")
    return (width, height) == (contract.COVER_SIZE, contract.COVER_SIZE)


class FakeMediaStore:
    """One kind's ARTWORK2.md 4.4 store: S = entries + 1 slots [valid, key, stamp], a clock,
    `displayed` and `frame_key`. Invalidating a slot changes only `valid` (src/cc_media_store.h)."""

    def __init__(self, entries, available=True):
        self.available = available      # False: a store that was never allocated (no slots)
        self.slots = [{"valid": False, "key": "", "stamp": 0, "bytes": 0, "crc": 0, "data": b""}
                      for _ in range(entries + 1)] if available else []
        self.clock, self.displayed, self.frame_key = 0, -1, ""

    def find(self, key):
        return next((i for i, s in enumerate(self.slots) if s["valid"] and s["key"] == key), None)

    def touch(self, index):
        self.clock += 1
        self.slots[index]["stamp"] = self.clock

    def pinned(self, index):
        slot = self.slots[index]
        return index == self.displayed or (slot["valid"] and bool(self.frame_key) and slot["key"] == self.frame_key)

    def victim(self):
        free = [i for i, s in enumerate(self.slots) if not s["valid"] and not self.pinned(i)]
        if free:
            return free[0]
        used = [i for i, s in enumerate(self.slots) if s["valid"] and not self.pinned(i)]
        return min(used, key=lambda i: (self.slots[i]["stamp"], i)) if used else None

    def adopt(self, key):
        """The LCD draws `key` (adoption touches only when `displayed` changes); None: nothing drawn."""
        index = self.find(key) if key else None
        if index is None:
            self.displayed = -1
        elif self.displayed != index:
            self.displayed = index
            self.touch(index)
            return True
        return False

    def table(self):
        return [[s["valid"], s["key"], s["stamp"]] for s in self.slots]


class FakeMedia:
    """The `media` command of ARTWORK2.md 4.3/4.4 (one global upload context over both kinds).

    `config` has the shape of media_store_traces.json configs; with `validateJpeg` a committed
    cover must pass tjpgd_accepts (the firmware's cc_jpeg_validate). `bytes` and `crc32` must be
    integers 0..0xFFFFFFFF, else "Media size and CRC required" (ARTWORK2.md 4.3, lead ruling of
    2026-09-24); a size in that range but outside the store's range is "Invalid media size".
    `offset` is an integer when json_int (int64 or uint64), and a chunk is out of bounds when
    offset + decoded length > bytes (signed), else a wrong offset is "Media offset mismatch". Counters mirror the diag fields mediaCommits, mediaErrors and
    mediaEvictions.
    """
    OPS = ("begin", "data", "commit", "have")

    def __init__(self, config):
        self.config = config
        self.stores = {kind: FakeMediaStore(config[kind]["entries"], config[kind].get("available", True))
                       for kind in ("cover", "icon")}
        self.upload = None
        self.active = None
        self.commits = self.errors = self.evictions = 0
        self.committed = []            # (kind, key) of every successful miss-commit, in order

    def cancel(self):
        self.upload = None

    def receiving(self):
        return self.upload is not None and not self.upload["hit"]

    def set_active(self, ident):
        """A new control (or None: a release): the control ID changed, any upload ends."""
        self.active = ident
        self.cancel()

    def set_frame(self, art_key, icon_key):
        for kind, key in (("cover", art_key), ("icon", icon_key)):
            self.stores[kind].frame_key = key if media_key_ok(key) else ""

    def size_ok(self, kind, size):
        slot = self.config[kind]["slotBytes"]
        if kind == "cover":
            return 1 <= size <= min(self.config["cover"]["maxBytes"], slot)
        return size == self.config["icon"]["bytes"] <= slot

    def decodable(self, kind, data):
        return kind != "cover" or not self.config.get("validateJpeg") or tjpgd_accepts(data)

    def handle(self, body):
        request = body if isinstance(body, dict) else {}
        op, kind, key, ident = request.get("op"), request.get("kind"), request.get("key"), request.get("id")
        ack = {}
        if type(ident) is int and 1 <= ident <= 0x7FFFFFFF:
            ack["id"] = ident
        if op in self.OPS:
            ack["op"] = op
        if kind in ("cover", "icon"):
            ack["kind"] = kind
        if op != "have":
            if media_key_ok(key):
                ack["key"] = key
            ack["offset"] = 0

        def error(message, offset=None):
            self.errors += 1
            if offset is not None:
                ack["offset"] = offset
            return {**ack, "error": message}

        if op not in self.OPS:
            return error("Unknown media operation")
        if kind not in ("cover", "icon"):
            return error("Unknown media kind")
        if not self.stores[kind].available:
            return error("Media unavailable")           # 4.3 step 4, before the control check
        if self.active is None or ident != self.active or type(ident) is not int:
            return error("Stale media control")
        store = self.stores[kind]
        if op == "have":
            keys = request.get("keys")
            if (not isinstance(keys, list) or not 1 <= len(keys) <= self.config["haveKeys"]
                    or not all(media_key_ok(k) for k in keys)):
                return error("Invalid media keys")
            answers = []
            for k in keys:
                index = store.find(k)
                if index is not None:
                    store.touch(index)
                answers.append(index is not None)
            return {**ack, "have": answers}
        if not media_key_ok(key):
            return error("Invalid media key")
        if op == "begin":
            size, crc = request.get("bytes"), request.get("crc32")
            if (type(size) is not int or not 0 <= size <= 0xFFFFFFFF or type(crc) is not int
                    or not 0 <= crc <= 0xFFFFFFFF):
                return error("Media size and CRC required")
            if not self.size_ok(kind, size):
                return error("Invalid media size")
            index = store.find(key)
            if index is not None and store.slots[index]["bytes"] == size and store.slots[index]["crc"] == crc:
                self.cancel()
                self.upload = {"kind": kind, "key": key, "bytes": size, "crc": crc, "slot": index, "received": size,
                               "hit": True}
                store.touch(index)
                return {**ack, "offset": size}
            self.cancel()
            victim = store.victim()
            if victim is None:
                return error("Media unavailable")
            if store.slots[victim]["valid"]:
                self.evictions += 1
            store.slots[victim]["valid"] = False
            self.upload = {"kind": kind, "key": key, "bytes": size, "crc": crc, "slot": victim, "received": 0,
                           "hit": False, "data": bytearray(), "last": None}
            return {**ack, "offset": 0}
        up = self.upload
        if not up or up["kind"] != kind or up["key"] != key or (op == "data" and up["hit"]):
            return error("No matching media upload")
        received = up["received"]
        if op == "data":
            raw = request.get("data")
            try:
                chunk = base64.b64decode(raw, validate=True) if isinstance(raw, str) else None
            except (ValueError, TypeError):
                chunk = None
            if not chunk or len(chunk) > self.config["chunkBytes"]:
                return error("Invalid media data", received)
            offset = request.get("offset")
            if not json_int(offset) or offset + len(chunk) > up["bytes"]:
                return error("Media chunk bounds", received)
            if offset == received:
                up["data"] += chunk
                up["received"] += len(chunk)
                up["last"] = (offset, len(chunk))
                return {**ack, "offset": up["received"]}
            if (up["last"] and offset == up["last"][0] and offset + len(chunk) == received
                    and bytes(up["data"][offset:offset + len(chunk)]) == chunk):
                return {**ack, "offset": received}
            return error("Media offset mismatch", received)
        if up["hit"]:
            self.upload = None
            return {**ack, "offset": up["bytes"]}
        if received != up["bytes"]:
            return error("Media upload incomplete", received)
        data = bytes(up["data"])
        if zlib.crc32(data) & 0xFFFFFFFF != up["crc"]:
            self.upload = None
            return error("Media checksum mismatch", received)
        if not self.decodable(kind, data):
            self.upload = None
            return error("Media decode failed", received)
        for other in store.slots:
            if other["valid"] and other["key"] == key:
                other["valid"] = False
        slot = store.slots[up["slot"]]
        slot.update(valid=True, key=key, bytes=up["bytes"], crc=up["crc"], data=data)
        store.touch(up["slot"])
        self.commits += 1
        self.upload = None
        self.committed.append((kind, key))
        return {**ack, "offset": up["bytes"]}


MEDIA_TRACES = WORK.parent / "harness" / "media_store_traces.json"


def replay_trace(case, media_factory=FakeMedia):
    """Run one media_store_traces.json case through FakeMedia with the reference-runner rules;
    returns a list of (step index, expected, got) mismatches."""
    media, mismatches = media_factory(case["config"]), []
    frame_keys = {"cover": "", "icon": ""}
    for n, step in enumerate(case["steps"]):
        kind = step["do"]
        if kind == "control":
            media.set_active(step["id"])
        elif kind == "release":
            media.set_active(None)
        elif kind == "frame":
            media.set_frame(step.get("artKey", ""), step.get("iconKey", ""))
            frame_keys = {"cover": media.stores["cover"].frame_key, "icon": media.stores["icon"].frame_key}
            if not step.get("noAdopt"):
                for k, store in media.stores.items():
                    store.adopt(frame_keys[k])
        elif kind == "adopt":
            media.stores[step["kind"]].adopt(step["key"])
        elif kind == "media":
            before = len(media.committed)
            got = media.handle(step["req"])
            if got != step["ack"]:
                mismatches.append((n, step["ack"], got))
            if len(media.committed) > before:
                k, key = media.committed[-1]
                if key == media.stores[k].frame_key:
                    media.stores[k].adopt(key)
        elif kind == "check":
            got = {"slots": {k: s.table() for k, s in media.stores.items()},
                   "displayed": {k: s.displayed for k, s in media.stores.items()},
                   "clock": {k: s.clock for k, s in media.stores.items()},
                   "receiving": media.receiving()}
            parts = [k for k in ("slots", "displayed", "clock", "receiving") if k in step]
            expected = {k: step[k] for k in parts}
            got = {k: got[k] for k in parts}
            if got != expected:
                mismatches.append((n, expected, got))
    return mismatches


DRAWN_FIELDS = ("heading", "title", "subtitle", "volumeCaption", "meta", "status")


def drawn(frame):
    """Every text line a frame can draw, joined: where a prompt overlay (tooling.overlay) puts the per-frame tag
    ("Stress 12 ab3f", "Soak recent 7") the tests find it, whatever the layout."""
    return " | ".join(str(frame.get(name, "")) for name in DRAWN_FIELDS if frame.get(name))


def tagged(frame, prefix):
    """The frame carries a per-frame tag that starts with `prefix` ("Stress", "Stress 5 ", "Soak")."""
    text = drawn(frame)
    return any(part.startswith(prefix) for chunk in text.split(" | ") for part in chunk.split(" · "))


class FakeFirmware:
    """An in-memory serial port that answers like the 1.0.0-cc5.3 firmware (control center subset).

    Sessions, stale frames and controls, the v1 art protocol bound to the current frame's artKey,
    parse replies for malformed and oversize art and media lines, the artwork2 `media` command
    (FakeMedia, with the real capability config), LCD adoption of the frame's cover and icon
    (a cover adoption counts a JPEG decode of `decode_ms`), diag with the reboot, liveness and
    media fields. `soaking` is set by the first control whose frame carries a soak tag ("Soak <control> <n>",
    in the title or, overlaid, the note line: drawn()); subclasses change diag_extra(), release_reply(),
    capabilities() and the media store from there. With `clock` and `lease` it also expires the 2 s host lease
    (only frames renew it) with {"released":true,"reason":"lease-expired"}.
    Every line's write shape is recorded in `shapes`: (first key, "whole" or "paced").

    The knob's physical side (user ruling 2026-09-26: the tests play the person from the knob's screen): every
    frame it shows goes to `operator.on_frame` (a FakeOperator, when one is attached), which schedules the key
    presses (key_down / key_up), the turning (sweep_step, while `turning`), the End stop pushes (end_push) and the
    turn to 0:00 (turn_to_zero); scheduled actions run when the host reads. Events carry the claimed control's id,
    or none while nothing is claimed (native events).
    """
    sweep_lims = False               # lim events at the range ends while turning (1.0.0-cc5.4: FakeFirmware54)
    decode_ms = 42

    def __init__(self, turn=True, clock=None, lease=False):
        self.out, self.pending = bytearray(), bytearray()
        self.active, self.last_id, self.frame_key = None, 0, ""
        self.cache, self.upload, self.boot, self.lines = {}, None, 7, 0
        self.turn, self.turning, self.position = turn, False, 0
        self.closed = False
        self.soaking, self.diags, self.releases, self.controls = False, 0, 0, []
        cap = t.artwork2_capability()
        self.media = FakeMedia({"cover": {"entries": cap["cover"]["entries"], "slotBytes": cap["cover"]["maxBytes"],
                                          "maxBytes": cap["cover"]["maxBytes"]},
                                "icon": {"entries": cap["icon"]["entries"], "slotBytes": cap["icon"]["bytes"],
                                         "bytes": cap["icon"]["bytes"]},
                                "chunkBytes": cap["chunkBytes"], "haveKeys": cap["haveKeys"], "validateJpeg": True})
        self.decodes, self.decode_errors, self.decode_max, self.decode_last = 0, 0, 0, 0
        self.clock, self.lease, self.renewed = clock, lease, 0.0
        self.shapes, self.writes, self.parts, self.frame_times = [], 0, 0, []
        self.operator, self.scheduled, self.keys, self.control_doc = None, [], 0, None
        self.sweep_dir, self.pushes = 1, 0

    def diag_extra(self):
        """Fields merged into every diag reply (healthy: none)."""
        return {}

    def release_reply(self):
        return {"released": True}

    def capabilities(self):
        return {"controlCenter": 1, "leaseMs": 2000, "presentation": 4, "diag": 1, "glyphs": "latin-ext-a",
                "artwork": dict(t.EXPECTED_ARTWORK_CAPABILITY), "artwork2": t.artwork2_capability()}

    # serial.Serial surface used by RawKnob
    @property
    def in_waiting(self):
        return len(self.out)

    def now(self):
        return self.clock() if self.clock else 0.0

    def schedule(self, delay, action):
        self.scheduled.append((self.now() + delay, action))

    def run_due(self):
        due = sorted((item for item in self.scheduled if item[0] <= self.now()), key=lambda item: item[0])
        for item in due:
            self.scheduled.remove(item)
            item[1]()

    def read(self, size):
        self.run_due()
        self.check_lease()
        data = bytes(self.out[:size])
        del self.out[:size]
        return data

    def write(self, data):
        """Lines never share a write (RawKnob writes one line at a time), so the writes that made a
        line tell its transport: several (<= 64 B each) is paced, one longer than 64 B is a whole-line
        write, and one of at most 64 B ("short") could be either."""
        self.writes += 1
        self.parts = 1 if not self.pending else self.parts + 1
        self.pending += data
        while b"\n" in self.pending:
            line, _, rest = bytes(self.pending).partition(b"\n")
            self.pending = bytearray(rest)
            head = re.match(rb'\{"(\w+)"', line)
            shape = "paced" if self.parts > 1 else ("whole" if len(line) + 1 > 64 else "short")
            self.shapes.append((head.group(1).decode() if head else "?", shape))
            self.line(line.decode("utf-8"))
        return len(data)

    def close(self):
        self.closed = True

    def reply(self, message):
        self.out += (json.dumps(message, separators=(",", ":")) + "\r\n").encode()

    def check_lease(self):
        if self.lease and self.clock and self.active and self.clock() - self.renewed > 2.0:
            self.set_active(None)
            self.reply({"released": True, "reason": "lease-expired"})

    def set_active(self, ident):
        self.active = ident
        self.media.set_active(ident)

    def scan(self, line, reply_key):
        head = line[:192]
        ident, key = re.search(r'"id":(\d+)', head), re.search(r'"key":"([A-Za-z0-9_-]{1,64})"', head)
        ack = {"op": "parse", "error": "parse"}
        if ident:
            ack["id"] = int(ident.group(1))
        if key:
            ack["key"] = key.group(1)
        if reply_key == "mediaAck":
            self.media.errors += 1
        self.reply({reply_key: ack})

    def art_scan(self, line):
        self.scan(line, "artAck")

    def show(self, frame):
        """Frame keys, then what the LCD draws: the cover and (Windows tile) the icon it names; then the person at
        the knob sees it (operator.on_frame)."""
        if self.clock:
            self.frame_times.append((self.clock(), drawn(frame)))
        self.frame_key = frame.get("artKey", "")
        self.media.set_frame(frame.get("artKey", ""), frame.get("iconKey", ""))
        self.adopt_frame()
        if self.operator is not None:
            self.operator.on_frame(frame)

    # --- the person's hands (scheduled by FakeOperator) -----------------------------------------
    def emit(self, message):
        self.reply(message)

    def event(self, **fields):
        """A knob event: with the claimed control's id, or native (no id) while nothing is claimed."""
        return {"id": self.active, **fields} if self.active else dict(fields)

    def key_down(self, raw):
        self.keys |= 1 << raw
        self.emit(self.event(kd=raw))

    def key_up(self, raw):
        self.keys &= ~(1 << raw)
        self.emit(self.event(ku=raw))

    def sweep_step(self):
        """One detent of turning back and forth across the claimed range (0..max), with a lim at each end when
        the firmware sends them (sweep_lims)."""
        maximum = (self.control_doc or {}).get("max", 8) if self.active else 8
        self.position = max(0, min(maximum, self.position + self.sweep_dir))
        self.emit(self.event(p=self.position))
        if self.position in (0, maximum):
            end = 1 if self.position == maximum else -1
            if self.sweep_lims and self.active:
                self.emit({"id": self.active, "lim": end})
            self.sweep_dir = -end

    def end_push(self, direction=1):
        """One push past the end of the range (1.0.0-cc5.4 answers it with lim events: FakeFirmware54)."""
        self.pushes += 1

    def turn_to_zero(self):
        """Turn left detent by detent to 0 (0:00 on the Seek control)."""
        for n, position in enumerate(range(self.position - 1, -1, -1)):
            self.schedule(0.05 * n, lambda position=position: self._at(position))

    def _at(self, position):
        self.position = position
        self.emit(self.event(p=position))

    def adopt_frame(self):
        cover, icon = self.media.stores["cover"], self.media.stores["icon"]
        if cover.adopt(cover.frame_key):
            self.decoded()
        icon.adopt(icon.frame_key)

    def decoded(self):
        self.decodes += 1
        self.decode_last = self.decode_ms
        self.decode_max = max(self.decode_max, self.decode_ms)

    def media_diag(self):
        return {"rxQueueBytes": 8192, "mediaCommits": self.media.commits, "mediaErrors": self.media.errors,
                "mediaEvictions": self.media.evictions, "jpegDecodes": self.decodes,
                "jpegDecodeErrors": self.decode_errors, "jpegDecodeMsMax": self.decode_max,
                "jpegDecodeMsLast": self.decode_last}

    def line(self, text):
        self.lines += 1
        self.check_lease()
        if len(text) > 4096:
            if text.startswith('{"media"'):
                return self.scan(text, "mediaAck")
            return self.art_scan(text) if text.startswith('{"art"') else self.reply({"error": "Command too large"})
        try:
            doc = json.loads(text)
        except ValueError:
            if text.startswith('{"media"'):
                return self.scan(text, "mediaAck")
            return self.art_scan(text) if text.startswith('{"art"') else self.reply({"error": "JSON parse error"})
        if doc.get("capabilities") == "?":
            return self.reply({"capabilities": self.capabilities()})
        if doc.get("diag") == "?":
            self.diags += 1
            return self.reply({"diag": {"lvglFree": 38000, "lvglMinFree": 30000, "heapMinFree": 86000, "stackLcd": 6700,
                                        "stackCom": 9000, "stackHmi": 7900, "stackFoc": 5800, "stackUsbd": 1600,
                                        "txStalls": 0, "txDroppedBytes": 0, **boot_diag(boot=self.boot, uptime=self.lines),
                                        **self.media_diag(), **self.diag_extra()}})
        if "art" in doc:
            return self.art(doc["art"])
        if "media" in doc:
            return self.media_command(doc["media"])
        if doc.get("release") is True:
            self.set_active(None)
            self.releases += 1
            return self.reply(self.release_reply())
        if "control" in doc:
            control = doc["control"]
            if control["id"] <= self.last_id:       # stricter than the firmware: every run's IDs advance
                return self.reply({"error": "Control ID must advance; wait for release before reconnecting"})
            self.set_active(control["id"])
            self.last_id = control["id"]
            self.renewed = self.clock() if self.clock else 0.0
            self.control_doc, self.position = control, control["position"]
            self.soaking = self.soaking or "Soak " in drawn(control["frame"])
            self.controls.append((control["id"], control["profile"]))
            self.show(control["frame"])
            return self.reply({"ready": control["id"], "p": control["position"]})
        if "frame" in doc:
            if doc["frame"].get("id") != self.active:
                return self.reply({"error": "Stale control frame"})
            self.renewed = self.clock() if self.clock else 0.0
            self.show(doc["frame"])

    def media_command(self, body):
        before = len(self.media.committed)
        ack = self.media.handle(body)
        if len(self.media.committed) > before:
            kind, key = self.media.committed[-1]
            if key == self.media.stores[kind].frame_key:     # a late arrival: the LCD draws it now
                self.adopt_frame()
        self.reply({"mediaAck": ack})

    def art(self, body):
        ack = {"id": body.get("id"), "key": body.get("key"), "op": body.get("op"), "offset": 0}
        key = body.get("key", "")
        if body.get("id") != self.active or key != self.frame_key:
            ack["error"] = "Stale artwork selection"
        elif body["op"] == "begin":
            cached = self.cache.get(key) == body["crc32"]
            self.upload = {"key": key, "crc": body["crc32"], "data": bytearray(), "done": cached}
            ack["offset"] = t.ART_BYTES if cached else 0
        elif body["op"] == "data":
            up = self.upload
            if up is None or up["key"] != key or body["offset"] != len(up["data"]):
                ack["error"] = "No matching artwork upload"
            else:
                up["data"] += base64.b64decode(body["data"])
                ack["offset"] = len(up["data"])
        else:
            up = self.upload
            ack["offset"] = t.ART_BYTES
            if not up["done"] and zlib.crc32(bytes(up["data"])) & 0xFFFFFFFF != up["crc"]:
                ack["error"] = "Artwork checksum mismatch"
            else:
                self.cache[key] = up["crc"]
        self.reply({"artAck": ack})


class FakeOperator:
    """The person at the knob, for the knob-guided flows (user ruling 2026-09-26): it reacts only to what the fake
    knob's screen shows. FakeFirmware.show hands it every frame; it reads the instruction through
    tooling.read_overlay (any layout) and schedules what a person does after `react_s`:

    * "Can you see this?" -> Button 4 (never, when `blind`);
    * a Yes/No screen (cancel + switch live, the Yes/No legend on the note line) -> Button 4, or Button 1 when
      `answers[instruction]` is False;
    * "Hold Button N" -> press and hold until the screen says "Let go" (`short_first`: the first hold of that
      instruction lets go after 0.3 s instead);
    * "Press Button N" in the instruction or the progress line -> one press (`wrong_first` {instruction: raw}:
      that button first, the right one after the "That was Button" retry);
    * "Turn back and forth" / "Keep turning" -> turn back and forth across the range (FakeFirmware.sweep_step
      every TURN_TICK_S) until the instruction changes; `pause_s` stops once for that long when the live
      progress ("Turned ...") first shows on a stress frame;
    * "Push past the end", "Push and hold" -> one push (FakeFirmware.end_push: its lims); "Turn to 0:00" -> turn
      down to 0; "Now push past 0:00" -> a push past 0:00;
    * `absent`: instructions it never follows; `actions` {instruction: fn(operator, view)}: custom behaviour.
    A retry note ("That was Button", "Too short") repeats the action."""
    TURN_SAYS = ("Turn back and forth", "Keep turning")
    TURN_TICK_S = 0.05

    def __init__(self, firmware, answers=None, react_s=0.3, blind=False, absent=(), wrong_first=None, actions=None,
                 pause_s=0.0, press_s=0.2, short_first=()):
        self.fw = firmware
        firmware.operator = self
        self.answers, self.react_s, self.blind, self.absent = dict(answers or {}), react_s, blind, set(absent)
        self.wrong_first, self.actions = dict(wrong_first or {}), dict(actions or {})
        self.pause_s, self.paused, self.press_s, self.short_first = pause_s, False, press_s, set(short_first)
        self.view, self.holding, self.turning = None, None, False
        self.seen, self.presses, self.pushes = [], [], []

    # -- what the person sees ---------------------------------------------------------------------
    def on_frame(self, frame):
        view = t.read_overlay(frame)
        say = view["say"]
        turn = say in self.TURN_SAYS and say not in self.absent
        if turn and not self.turning:
            self.start_turning()
        elif not turn and self.turning:
            self.stop_turning()
        if (self.pause_s and not self.paused and self.turning and view["progress"].startswith("Turned ")
                and "Stress " in view["note"]):                  # the stress frames run: the counted window
            self.paused = True
            self.fw.turning = False
            self.fw.schedule(self.pause_s, self.resume_turning)
        if self.holding is not None and say == "Let go":
            self.let_go()
        key = (view["heading"], say, view["progress"], view["note"])
        if key != self.view:
            previous, self.view = self.view, key
            if previous is None or key[:3] != previous[:3]:
                self.seen.append(key[:3])
            self.react(view, previous or ("", "", "", ""))

    def react(self, view, previous):
        """Act on a changed screen: a new instruction (heading, instruction or progress changed; for the End stop,
        the note line too) or a retry note."""
        heading, say, progress, note = view["heading"], view["say"], view["progress"], view["note"]
        new = (heading, say, progress) != previous[:3]
        retry = note != previous[3] and ("That was Button" in note or "Too short" in note)
        if say in self.actions:
            if new:
                self.actions[say](self, view)
            return
        if say in self.absent or not (new or retry or say in ("Push past the end", "Push and hold")):
            return
        yes_no = t.is_yes_no(view["buttons"]) and ("Yes: Button 4" in note or "Yes 4 · No 1" in note)
        pressed = re.search(r"Press Button (\d)", f"{say} {progress}")
        held = re.search(r"Hold Button (\d)", say)
        if say == t.PROMPT_SEE:
            if not self.blind:
                self.press(t.YES_RAW, say)
        elif yes_no:
            self.press(t.YES_RAW if self.answers.get(say, True) else t.NO_RAW, say)
        elif held:
            if self.holding is None:
                self.hold(int(held.group(1)) - 1, say)
        elif pressed:
            self.press(int(pressed.group(1)) - 1, say)
        elif say in ("Push past the end", "Push and hold"):
            fresh = new or note != previous[3]
            if fresh and (note.split(" · ")[-1].startswith("Push ") or note == "Hold it against the end"):
                self.push(1)
        elif say == "Now push past 0:00":
            self.push(-1)
        elif say == "Turn to 0:00":
            self.fw.schedule(self.react_s, self.fw.turn_to_zero)

    # -- what the person does ---------------------------------------------------------------------
    def press(self, raw, say):
        wrong = self.wrong_first.pop(say, None)
        pressed = raw if wrong is None else wrong
        self.presses.append((pressed, say))
        self.fw.schedule(self.react_s, lambda: self.fw.key_down(pressed))
        self.fw.schedule(self.react_s + self.press_s, lambda: self.fw.key_up(pressed))

    def hold(self, raw, say):
        self.presses.append((raw, say))
        if say in self.short_first:
            self.short_first.discard(say)
            self.fw.schedule(self.react_s, lambda: self.fw.key_down(raw))
            self.fw.schedule(self.react_s + 0.3, lambda: self.fw.key_up(raw))
            return
        self.holding = raw
        self.fw.schedule(self.react_s, lambda: self.fw.key_down(raw))

    def let_go(self):
        raw, self.holding = self.holding, None
        self.fw.schedule(self.react_s / 3, lambda: self.fw.key_up(raw))

    def push(self, direction):
        self.pushes.append(direction)
        self.fw.schedule(self.react_s, lambda: self.fw.end_push(direction))

    def start_turning(self):
        self.turning = self.fw.turning = True
        self.fw.schedule(self.react_s, self.tick)

    def stop_turning(self):
        self.turning = self.fw.turning = False

    def resume_turning(self):
        self.fw.turning = self.turning

    def tick(self):
        if not self.turning:
            return
        if self.fw.turning:
            self.fw.sweep_step()
        self.fw.schedule(self.TURN_TICK_S, self.tick)


class FakeCheckpoints:
    """Stands in for RebootWatch inside raw_checks: records every checkpoint and compares diag
    (reboot and, from 1.0.0-cc5.2, liveness); `quiet` checkpoints report only a failure."""

    def __init__(self, report):
        self.report, self.calls, self.last, self.pnp = report, [], None, []

    def checkpoint(self, where, diag=None, pnp=True, quiet=False):
        problems = t.reboot_problems(self.last, diag) if (diag is not None and self.last is not None) else []
        if diag is not None:
            problems += t.liveness_problems(diag)
        self.last = diag if diag is not None else self.last
        self.calls.append((where, problems))
        self.pnp.append((where, pnp))
        if problems or not quiet:
            return self.report.check(f"no reboot or USB re-enumeration: {where}", not problems, problems or None)
        return True

    def main(self):
        """The section checkpoints, without the soak's own 10 s and after-release checkpoints."""
        return [(where, problems) for where, problems in self.calls if not where.startswith("soak ")]


@needs_tooling
class CheckScriptRawFlowTests(unittest.TestCase):
    """check_nanod_cc5.raw_checks() end to end against FakeFirmware: no port, no device, fake clock.

    FakeFirmware answers like 1.0.0-cc5.3, so these runs name its profile (CURRENT is cc5.4 since the
    release tooling moved; Cc54CheckFlowTests runs the cc5.4 profile against FakeFirmware54)."""

    PROFILE = t.PROFILES["cc5.3"] if t else None

    def setUp(self):
        self.module = load_script("check_nanod_cc5.py")
        self.out = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))

    RAW_SECTIONS = ["displayCheck", "legacyV2Frames", "staleFrameAndControl", "rawArtwork", "mediaRoundTrip",
                    "mediaPrefetch",
                    "mediaPinning", "mediaErrors", "mediaTiming", "coldTransferTiming", "stress", "stressTurn", "soak",
                    "diag"]
    RAW_GATES = ("artwork2Capability", "v1ArtCompatible", "mediaRoundTrip", "mediaPrefetch", "mediaPinning",
                 "mediaErrorStrings", "unpacedTransferTiming", "jpegDecode", "stressUntouched", "stressTurn",
                 "turningDetected", "diagMargins", "unattendedSoak")

    def raw(self, firmware, stress_frames=40, soak_minutes=1.0, gate_minutes=1.0, stress_seconds=2.0, operator=None,
            **extra):
        """raw_checks against `firmware` with a FakeOperator at the knob (the default one follows every prompt).
        Extra keyword arguments become args (step_timeout, turn_attempts, ...)."""
        real = t.RawKnob
        clock = itertools.count(0, 0.001).__next__
        factory = lambda port: real(port, serial_factory=lambda name: firmware, clock=clock, sleep=lambda s: None)  # noqa: E731
        firmware.clock = firmware.clock or clock        # frame arrival times (no lease expiry without lease=True)
        if firmware.operator is None:
            FakeOperator(firmware, **(operator or {}))
        report = self.last_report = self.module.Report("FAKEAPP", self.PROFILE)
        watch = FakeCheckpoints(report)
        args = SimpleNamespace(**{"turn_seconds": 1.0, "stress_frames": stress_frames, "replay_transfers": 3,
                                  "soak_minutes": soak_minutes, "stress_seconds": stress_seconds, "step_timeout": 30.0,
                                  **extra})
        with mock.patch.object(t, "RawKnob", factory), mock.patch.object(t, "SOAK_GATE_MINUTES", gate_minutes):
            self.module.raw_checks("FAKEAPP", report, {}, args, watch, self.PROFILE)
        return report, watch

    def test_a_clean_run_passes_both_stress_passes_and_every_checkpoint(self):
        firmware = FakeFirmware()
        report, watch = self.raw(firmware)
        self.assertEqual(report.data["failures"], [])
        gates = report.gates
        self.assertEqual({name: gates[name] for name in self.RAW_GATES}, {name: True for name in self.RAW_GATES})
        self.assertEqual(report.data["firmwareVersion"], self.PROFILE.version)
        sections = report.data["sections"]
        self.assertEqual(sections["coldTransferTiming"]["extraTransfers"], 3)
        # With artwork2 the untouched pass replays the cc5.2 stress first (paced v1 art, the
        # 1.0.0-cc5 run-1 sequence), then runs the unpaced media stress.
        v1 = sections["stress"]["v1"]
        self.assertTrue(v1["run1Replay"] and v1["passed"])
        self.assertFalse(sections["stress"]["run1Replay"])
        self.assertNotIn("unpaced", v1)
        self.assertGreaterEqual(v1["framesSent"], 40)
        self.assertEqual(v1["committed"], v1["transfers"])
        self.assertGreater(v1["transfers"], 0)
        self.assertEqual((v1["knobEvents"], sections["stress"]["knobEvents"]), (0, 0))
        self.assertLessEqual(v1["window"][1], sections["stress"]["window"][0], "v1 first, then the media stress")
        self.assertIn(f"stress (untouched, paced v1 art: the 1.0.0-cc5 run-1 sequence as the cc5.2-era companion "
                      f"sends it): {v1['framesSent']} frame updates interleaved with {v1['transfers']} art transfers, "
                      "zero error replies, no release", [c["check"] for c in report.data["checks"] if c["passed"]])
        self.assertGreaterEqual(sections["stressTurn"]["knobEvents"]["count"], t.TURN_MIN_EVENTS)
        turn = sections["stressTurn"]["knobEvents"]
        self.assertGreaterEqual(turn["duringStress"], t.TURN_MIN_EVENTS)
        self.assertLessEqual(turn["maxGapDuringStressMs"], turn["maxGapAllowedMs"])
        self.assertEqual(turn["stressWindow"], sections["stressTurn"]["window"])
        self.assertEqual(sections["stressTurn"]["extraTransfers"], 3)
        main = [w for w, _ in watch.main()]
        self.assertEqual(main[0], "DeviceBridge part (uptime and bootCount across it)")
        self.assertEqual(main[1:], self.RAW_SECTIONS)
        # PowerShell (the PnP read) only while no control is claimed: before the first control and
        # right after each soak release; never on a live lease.
        pnp = [(w, p) for w, p in watch.pnp]
        self.assertEqual([p for w, p in pnp if not w.startswith("soak ")], [True] + [False] * len(self.RAW_SECTIONS))
        soak_pnp = [w for w, p in pnp if w.startswith("soak ") and p]
        self.assertTrue(soak_pnp and all("after release" in w for w in soak_pnp), soak_pnp)
        # The soak: two 30 s cycles, each released without "forced", 10 s checkpoints, cold and cached covers.
        soak = sections["soak"]
        self.assertTrue(soak["passed"] and soak["completed"] and soak["failure"] is None)
        self.assertEqual(soak["cycles"], 2)
        self.assertEqual([r["reason"] for r in soak["releases"]], [None, None])
        self.assertGreaterEqual(soak["checkpoints"], 6)
        self.assertEqual([c["control"] for c in soak["controls"]], ["volume", "recent"])
        self.assertGreater(soak["transfers"]["cold"], 0)
        self.assertGreater(soak["transfers"]["cached"], 0)
        self.assertEqual(soak["transfers"]["cacheHits"], soak["transfers"]["cached"])
        self.assertGreater(soak["changedFrames"], 50)
        self.assertGreater(soak["flashes"], 0)
        self.assertEqual(soak["stressReleased"], {"released": True})
        ids = [cid for cid, _ in firmware.controls]
        self.assertEqual(ids, sorted(ids))                           # every control ID advanced
        text = self.out.getvalue()
        # The console is a log; the knob's screen carried every instruction (the display check first).
        self.assertLess(text.index("[knob] step 1/2 display: shown 'Can you see this?'"),
                        text.index("[log] stress pass 1 of 2"))
        self.assertLess(text.index("[log] stress pass 2 of 2"), text.index("[knob] step 2/2 turn: shown 'Ready to turn?'"))
        self.assertLess(text.index("[knob] step 2/2 turn: done"), text.index("[log] unattended soak: 1 min"))
        for phrase in ("do NOT touch", "Turn the knob continuously", "Stop turning", "you may leave"):
            self.assertNotIn(phrase, text)
        self.assertIn("checkpoint 1 ok (hmi 4 ms, lcd 2 ms, com 0 ms, foc 0 ms;", text)
        self.assertTrue(firmware.closed and report.data["finalRelease"] == {"released": True})
        prompts = report.data["prompts"]
        self.assertEqual(prompts["plan"], ["display", "turn"])
        self.assertTrue(prompts["displayCheck"]["confirmed"] and report.data["displayCheck"]["confirmed"])
        self.assertEqual([(step["name"], step["outcome"]) for step in prompts["steps"]], [("display", "done"), ("turn", "done")])
        self.assertIsNone(prompts["stopped"])
        self.assertNotIn("operatorStop", report.data)
        turn = sections["stressTurn"]
        self.assertEqual([a["stopped"] for a in turn["turnAttempts"]], [None])
        self.assertGreaterEqual(turn["turnAttempts"][0]["meter"]["turnedS"], 1.0)
        self.assertEqual(turn["turnAttempts"][0]["meter"]["ends"], [-1, 1])
        self.assertEqual([a["attempt"] for a in sections["stress"]["attempts"]], [1])

    def test_artwork2_sections_run_unpaced_and_v1_art_stays_paced(self):
        firmware = FakeFirmware()
        report, _ = self.raw(firmware)
        sections = report.data["sections"]
        # Transport: every media line in one write(); every v1 art line paced like the cc5.2-era companion.
        shapes = {}
        for key, shape in firmware.shapes:
            shapes.setdefault(key, set()).add(shape)
        self.assertTrue("whole" in shapes["media"] and shapes["media"] <= {"whole", "short"}, shapes["media"])
        self.assertTrue("paced" in shapes["art"] and shapes["art"] <= {"paced", "short"}, shapes["art"])
        self.assertTrue({"whole", "paced"} <= shapes["frame"], shapes["frame"])
        self.assertTrue(report.data["raw"]["linesWritten"]["whole"] and report.data["raw"]["linesWritten"]["paced"])
        # Round trips, have and prefetch.
        trip = sections["mediaRoundTrip"]
        self.assertEqual((trip["cover"]["beginOffset"], trip["coverHit"]["hit"], trip["iconHit"]["hit"]), (0, True, True))
        self.assertEqual(trip["have"]["cover"]["have"], [True, False])
        prefetch = sections["mediaPrefetch"]
        self.assertEqual(prefetch["have"]["have"], [True, True, True])
        self.assertTrue(prefetch["named"]["hit"] and prefetch["shownSeconds"] is not None)
        # Pinning: 26 more covers and 50 more icons; the pinned key and the newest stay, the two oldest go.
        pinning = sections["mediaPinning"]
        self.assertEqual((pinning["cover"]["uploads"], pinning["icon"]["uploads"]), (26, 50))
        self.assertEqual(pinning["cover"]["haveKept"]["have"], [True] * 24)
        self.assertEqual(pinning["icon"]["haveEvicted"]["have"], [False, False])
        self.assertGreaterEqual(pinning["evictions"]["after"] - pinning["evictions"]["before"], 4)
        # Every reachable 4.3 error string, and diag mediaErrors counted exactly those replies.
        errors = sections["mediaErrors"]
        wanted = {"parse", "Unknown media operation", "Unknown media kind", "Stale media control", "Invalid media keys",
                  "Invalid media key", "Media size and CRC required", "Invalid media size", "No matching media upload",
                  "Invalid media data", "Media chunk bounds", "Media offset mismatch", "Media upload incomplete"}
        self.assertEqual({c["expected"] for c in errors["cases"] if not c["expected"].startswith("offset")}, wanted)
        self.assertTrue(all(c["passed"] for c in errors["cases"]))
        self.assertEqual({v["error"] for v in errors["transfers"].values()},
                         {"Media checksum mismatch", "Media decode failed"})
        self.assertEqual(errors["mediaErrors"]["after"] - errors["mediaErrors"]["before"], errors["errorReplies"])
        self.assertIn("Media unavailable", errors["notReachable"])
        # Timing, the unpaced stress and the soak's media traffic.
        timing = sections["mediaTiming"]
        self.assertEqual((len(timing["coverSeconds"]), len(timing["iconSeconds"])), (5, 5))
        self.assertEqual(timing["ackLimitSeconds"], t.presentation().MEDIA_ACK_TIMEOUT_SECONDS)
        for name in ("stress", "stressTurn"):
            stress = sections[name]
            self.assertTrue(stress["unpaced"])
            self.assertEqual(stress["media"]["haveMisses"], 0)
            self.assertTrue(stress["media"]["covers"] and stress["media"]["icons"] and stress["media"]["have"])
            self.assertGreaterEqual(stress["window"][1] - stress["window"][0], 2.0)     # --stress-seconds
        # Unpaced stress frames keep the v4 companion's rate: at most one per 25 ms UI tick (the
        # paced v1 stress before the unpaced one is the cc5.2 pattern, a frame after every ack).
        windows = [sections[name]["window"] for name in ("stress", "stressTurn")]
        stress_times = [at for at, text in firmware.frame_times if re.search(r"Stress \d+ ", text)
                        and any(a <= at <= b for a, b in windows)]
        self.assertGreater(len(stress_times), 80)
        self.assertGreaterEqual(min(b - a for a, b in zip(stress_times, stress_times[1:])), t.FRAME_TICK_SECONDS - 1e-9)
        soak = sections["soak"]["media"]
        self.assertTrue(soak["unpaced"] and soak["v1Art"] and soak["v1Committed"] == soak["v1Art"])
        self.assertTrue(soak["icons"] and soak["have"] and soak["prefetch"] and soak["haveMisses"] == 0)
        self.assertEqual(sections["diag"]["media"]["jpegDecodeErrors"], 0)
        self.assertGreater(sections["diag"]["media"]["jpegDecodes"], 0)
        self.assertTrue(sections["rawArtwork"]["v1Compatible"] and sections["rawArtwork"]["paced"])

    def test_a_second_run_on_the_same_boot_still_passes(self):
        """The knob keeps committed covers until it reboots: a rerun (for example after "turning not
        detected") must upload cold again, so each run salts its payloads."""
        firmware = FakeFirmware()
        self.raw(firmware)
        kept = {s["key"] for s in firmware.media.stores["cover"].slots if s["valid"]}
        self.assertTrue(kept)
        firmware.last_id = 0              # the firmware accepts any control ID once released
        firmware.turning = False          # nobody turns the knob until the second stress+turn prompt
        report, _ = self.raw(firmware)
        self.assertEqual(report.data["failures"], [])
        self.assertTrue(report.gates["mediaRoundTrip"] and report.gates["mediaPinning"]
                        and report.gates["unpacedTransferTiming"])
        self.assertNotIn(report.data["sections"]["mediaRoundTrip"]["cover"]["key"], kept)

    def gate_failure(self, firmware, gate, **kwargs):
        report, _ = self.raw(firmware, **kwargs)
        self.assertFalse(report.gates[gate], gate)
        self.assertTrue(report.data["failures"])
        self.assertTrue(report.gates["stressUntouched"] and report.gates["unattendedSoak"])   # the rest still runs
        return report

    def test_a_firmware_that_evicts_the_pinned_cover_fails_mediaPinning(self):
        class EvictsPinned(FakeFirmware):
            def __init__(self):
                super().__init__()
                for store in self.media.stores.values():
                    store.pinned = lambda index: False

        report = self.gate_failure(EvictsPinned(), "mediaPinning")
        self.assertIn("pinning (covers): the frame's cover stays while 26 more fill the 25-slot store; the newest 23 "
                      "stay and the two oldest are evicted", report.data["failures"])
        self.assertTrue(report.gates["mediaRoundTrip"] and report.gates["mediaErrorStrings"])

    def test_a_firmware_that_drops_prefetched_covers_fails_mediaPrefetch(self):
        class DropsPrefetch(FakeMedia):
            def handle(self, body):
                ack = super().handle(body)
                if isinstance(body, dict) and body.get("op") == "commit" and "error" not in ack:
                    store = self.stores[body["kind"]]
                    if body["key"] != store.frame_key:            # only the current key is kept
                        index = store.find(body["key"])
                        if index is not None:
                            store.slots[index]["valid"] = False
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = DropsPrefetch
        report, _ = self.raw(firmware)
        self.assertFalse(report.gates["mediaPrefetch"])
        self.assertIn("prefetch: have answers true for all three (kept)", report.data["failures"])

    def test_a_wrong_error_string_fails_mediaErrorStrings(self):
        class Renamed(FakeMedia):
            def handle(self, body):
                ack = super().handle(body)
                if ack.get("error") == "Media offset mismatch":
                    ack["error"] = "Media offset error"
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = Renamed
        report = self.gate_failure(firmware, "mediaErrorStrings")
        failed = [c for c in report.data["sections"]["mediaErrors"]["cases"] if not c["passed"]]
        self.assertEqual({c["ack"]["error"] for c in failed}, {"Media offset error"})

    def test_slow_cover_decodes_fail_jpegDecode_and_prefetch(self):
        class SlowDecode(FakeFirmware):
            decode_ms = 201

        report = self.gate_failure(SlowDecode(), "jpegDecode")
        self.assertFalse(report.gates["mediaPrefetch"])
        detail = next(c["detail"] for c in report.data["checks"] if c["check"].startswith("diag: JPEG covers decoded"))
        self.assertIn("SLOW JPEG DECODE: jpegDecodeMsMax 201 ms > 200 ms", detail[0])

    def test_decode_errors_fail_jpegDecode(self):
        class DecodeErrors(FakeFirmware):
            def decoded(self):
                super().decoded()
                self.decode_errors = 1

        report = self.gate_failure(DecodeErrors(), "jpegDecode")
        detail = next(c["detail"] for c in report.data["checks"] if c["check"].startswith("diag: JPEG covers decoded"))
        self.assertIn("JPEG DECODE ERRORS: jpegDecodeErrors 1", detail[0])

    # Each gate condition below fails on its own: every other check of that section still passes, so
    # dropping the condition from check_nanod_cc5.py turns the gate true and the test red.

    def failing(self, report):
        return set(report.data["failures"])

    def section_failures(self, report, prefix):
        return {name for name in report.data["failures"] if name.startswith(prefix)}

    def test_a_store_that_keeps_the_two_oldest_fails_mediaPinning(self):
        """Two slots more per store than advertised: the store evicts (older sections' keys), but never the
        batch's two oldest, so only the have-evicted condition catches it."""
        class Roomy(FakeFirmware):
            def __init__(self):
                super().__init__()
                for store in self.media.stores.values():
                    store.slots += [{"valid": False, "key": "", "stamp": 0, "bytes": 0, "crc": 0, "data": b""}
                                    for _ in range(2)]

        report = self.gate_failure(Roomy(), "mediaPinning")
        detail = report.data["sections"]["mediaPinning"]
        self.assertEqual((detail["cover"]["haveEvicted"]["have"], detail["icon"]["haveEvicted"]["have"]),
                         ([True, True], [True, True]))
        self.assertEqual(detail["cover"]["haveKept"]["have"], [True] * 24)
        self.assertGreaterEqual(detail["evictions"]["after"] - detail["evictions"]["before"], 4)
        self.assertEqual(self.section_failures(report, "pinning"),
                         {"pinning (covers): the frame's cover stays while 26 more fill the 25-slot store; the newest "
                          "23 stay and the two oldest are evicted",
                          "pinning (icons): the frame's icon stays while 50 more fill the 49-slot store; the newest "
                          "23 stay and the two oldest are evicted"})

    def test_a_firmware_that_does_not_count_parse_replies_fails_mediaErrorStrings(self):
        class UncountedParse(FakeFirmware):
            def scan(self, line, reply_key):
                errors = self.media.errors
                super().scan(line, reply_key)
                self.media.errors = errors                    # diag mediaErrors misses the parse replies

        report = self.gate_failure(UncountedParse(), "mediaErrorStrings")
        section = report.data["sections"]["mediaErrors"]
        self.assertTrue(all(c["passed"] for c in section["cases"]))
        self.assertEqual(section["mediaErrors"]["after"] - section["mediaErrors"]["before"], section["errorReplies"] - 2)
        self.assertEqual(self.section_failures(report, "media errors"),
                         {f"media errors: diag mediaErrors counted exactly the {section['errorReplies']} error replies"})

    def test_error_replies_must_echo_what_parsed_and_carry_the_received_offset(self):
        class Shapeless(FakeMedia):
            def handle(self, body):
                ack = super().handle(body)
                if ack.get("error") in ("Media offset mismatch", "Invalid media data"):
                    ack["offset"] = 0                          # the received count is lost
                if ack.get("error") == "Media size and CRC required":
                    ack.pop("key", None)                       # a valid key is not echoed
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = Shapeless
        report = self.gate_failure(firmware, "mediaErrorStrings")
        failed = {c["case"] for c in report.data["sections"]["mediaErrors"]["cases"] if not c["passed"]}
        self.assertEqual(failed, {"changed retry of that chunk", "data not base64 during the upload",
                                  "begin without crc32", "begin with a text size", "begin with a negative size"})
        cases = {c["case"]: c for c in report.data["sections"]["mediaErrors"]["cases"]}
        self.assertEqual(cases["kind unknown"]["reply"], {"id": cases["kind unknown"]["ack"]["id"], "op": "have",
                                                          "error": "Unknown media kind"})
        self.assertEqual(set(cases["begin with a malformed key"]["reply"]), {"id", "op", "kind", "offset", "error"})
        self.assertEqual(set(cases["malformed line"]["reply"]), {"op", "error", "id", "key"})

    def test_an_lcd_that_draws_only_late_arrivals_fails_mediaPrefetch(self):
        """A cover already in the store when a frame names it is never drawn: only a named cover that
        arrives after its frame is. The named prefetched cover is then not shown at once."""
        class LateOnly(FakeFirmware):
            def adopt_frame(self):
                if getattr(self, "arriving", False):
                    return super().adopt_frame()
                self.media.stores["icon"].adopt(self.media.stores["icon"].frame_key)

            def media_command(self, body):
                self.arriving = True
                try:
                    return super().media_command(body)
                finally:
                    self.arriving = False

        report = self.gate_failure(LateOnly(), "mediaPrefetch")
        self.assertIsNone(report.data["sections"]["mediaPrefetch"]["shownSeconds"])
        self.assertEqual(self.section_failures(report, "prefetch"),
                         {"prefetch: the LCD decoded it at once (jpegDecodes +1 within 1.5 s, no decode error, "
                          "jpegDecodeMsLast <= 200 ms)"})

    def test_a_firmware_that_drops_prefetched_icons_fails_mediaPrefetch(self):
        class DropsPrefetchedIcons(FakeMedia):
            def handle(self, body):
                ack = super().handle(body)
                if isinstance(body, dict) and body.get("op") == "commit" and body.get("kind") == "icon" \
                        and "error" not in ack and body["key"] != self.stores["icon"].frame_key:
                    index = self.stores["icon"].find(body["key"])
                    if index is not None:
                        self.stores["icon"].slots[index]["valid"] = False
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = DropsPrefetchedIcons
        report = self.gate_failure(firmware, "mediaPrefetch")
        self.assertEqual(self.section_failures(report, "prefetch"),
                         {"prefetch: an icon the frame does not name is accepted, kept (have) and a begin-hit once a "
                          "Windows frame names it"})
        self.assertEqual(report.data["sections"]["mediaPrefetch"]["icon"]["have"]["have"], [False])

    def test_a_firmware_whose_icon_have_misses_fails_mediaRoundTrip_and_mediaPrefetch(self):
        """Icon have answers false for every key, although the store keeps the icons: the prefetched icon
        is still a begin-hit once a Windows frame names it, so in the prefetch only its have condition
        catches it."""
        class BlindIconHave(FakeMedia):
            def handle(self, body):
                ack = super().handle(body)
                if isinstance(body, dict) and body.get("op") == "have" and body.get("kind") == "icon" and "have" in ack:
                    ack["have"] = [False] * len(ack["have"])
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = BlindIconHave
        report = self.gate_failure(firmware, "mediaRoundTrip")
        self.assertEqual(self.section_failures(report, "media have"),
                         {"media have: true for the committed cover and icon, false for a key never sent"})
        self.assertEqual(report.data["sections"]["mediaRoundTrip"]["have"]["cover"]["have"], [True, False])
        self.assertFalse(report.gates["mediaPrefetch"])
        icon = report.data["sections"]["mediaPrefetch"]["icon"]
        self.assertEqual((icon["prefetch"]["hit"], icon["prefetch"]["committed"], icon["have"]["have"],
                          icon["named"]["hit"], icon["named"]["committed"]), (False, True, [False], True, True))
        self.assertEqual(self.section_failures(report, "prefetch"), {self.PREFETCH_ICON})

    def test_an_error_reply_during_the_round_trips_fails_mediaRoundTrip(self):
        class ComplainsOnce(FakeFirmware):
            def show(self, frame):
                super().show(frame)
                if frame.get("iconKey") and not getattr(self, "complained", False):   # the first Windows icon frame
                    self.complained = True
                    self.reply({"error": "Invalid control frame"})

        report = self.gate_failure(ComplainsOnce(), "mediaRoundTrip")
        self.assertEqual(self.section_failures(report, "media round trip"),
                         {"media round trips: no error reply, media error or release"})

    REFUSED_CHECK = ("media errors: Media checksum mismatch, and Media decode failed for a progressive, a 120 px and a "
                     "non-JPEG payload, each at commit; none of them is kept (have false)")

    def renamed_error(self, old, new):
        """A FakeFirmware whose media store answers `new` where ARTWORK2.md 4.3 says `old`."""
        class Renamed(FakeMedia):
            def handle(self, body):
                ack = super().handle(body)
                if ack.get("error") == old:
                    ack["error"] = new
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = Renamed
        return firmware

    def test_a_renamed_decode_failure_fails_mediaErrorStrings(self):
        report = self.gate_failure(self.renamed_error("Media decode failed", "Media decode error"), "mediaErrorStrings")
        section = report.data["sections"]["mediaErrors"]
        self.assertEqual({v["error"] for v in section["transfers"].values()},
                         {"Media checksum mismatch", "Media decode error"})
        self.assertTrue(all(v["errorOp"] == "commit" for v in section["transfers"].values()))
        self.assertEqual(section["have"]["have"], [False] * 4)                  # nothing kept: only the string is wrong
        self.assertEqual(self.failing(report), {self.REFUSED_CHECK})

    def test_a_renamed_checksum_failure_fails_mediaErrorStrings(self):
        report = self.gate_failure(self.renamed_error("Media checksum mismatch", "Media CRC mismatch"),
                                   "mediaErrorStrings")
        section = report.data["sections"]["mediaErrors"]
        self.assertEqual((section["transfers"]["checksum"]["error"], section["transfers"]["checksum"]["errorOp"]),
                         ("Media CRC mismatch", "commit"))
        self.assertEqual(section["have"]["have"], [False] * 4)
        self.assertEqual(self.failing(report), {self.REFUSED_CHECK})

    def test_a_store_that_keeps_an_undecodable_cover_fails_mediaErrorStrings(self):
        """Every refused cover is answered "Media decode failed" at commit, but the store keeps it:
        only the have query after them shows it."""
        class KeepsUndecodable(FakeMedia):
            def handle(self, body):
                upload = self.upload
                ack = super().handle(body)
                if ack.get("error") == "Media decode failed":                 # stored as if it had committed
                    store = self.stores[upload["kind"]]
                    store.slots[upload["slot"]].update(valid=True, key=upload["key"], bytes=upload["bytes"],
                                                       crc=upload["crc"], data=bytes(upload["data"]))
                    store.touch(upload["slot"])
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = KeepsUndecodable
        report = self.gate_failure(firmware, "mediaErrorStrings")
        section = report.data["sections"]["mediaErrors"]
        self.assertEqual({v["error"] for v in section["transfers"].values()},
                         {"Media checksum mismatch", "Media decode failed"})
        self.assertEqual(section["have"]["have"], [False, True, True, True])     # the checksum one, then the three
        self.assertEqual(self.failing(report), {self.REFUSED_CHECK})

    def test_a_firmware_that_serves_media_after_a_release_fails_mediaErrorStrings(self):
        """With no control claimed the store skips the session check: a have after the release is
        answered instead of "Stale media control"."""
        class ServesWithoutASession(FakeMedia):
            def handle(self, body):
                if self.active is None and isinstance(body, dict) and type(body.get("id")) is int:
                    self.active = body["id"]
                    try:
                        return super().handle(body)
                    finally:
                        self.active = None
                return super().handle(body)

        firmware = FakeFirmware()
        firmware.media.__class__ = ServesWithoutASession
        report = self.gate_failure(firmware, "mediaErrorStrings")
        after = report.data["sections"]["mediaErrors"]["cases"][-1]
        self.assertEqual((after["case"], after["passed"], after["ack"].get("have")),
                         ("after the release (no session)", False, [False]))
        self.assertEqual(self.failing(report), {"media errors: after a release every media line is Stale media control"})

    def test_a_bare_error_reply_during_the_error_cases_fails_mediaErrorStrings(self):
        """Every media line gets its exact mediaAck, but one also draws a bare {"error"}."""
        class BareError(FakeFirmware):
            complained = False

            def media_command(self, body):
                super().media_command(body)
                if isinstance(body, dict) and "op" not in body and not self.complained:     # the "op missing" case
                    self.complained = True
                    self.reply({"error": "Invalid control frame"})

        report = self.gate_failure(BareError(), "mediaErrorStrings")
        self.assertTrue(all(c["passed"] for c in report.data["sections"]["mediaErrors"]["cases"]))
        self.assertEqual(self.failing(report), {"media errors: no bare error reply (every media line got a mediaAck) "
                                                "and only the intended release"})

    def test_a_firmware_that_never_counts_evictions_fails_mediaPinning(self):
        class UncountedEvictions(FakeMedia):
            def handle(self, body):
                evictions = self.evictions
                ack = super().handle(body)
                self.evictions = evictions
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = UncountedEvictions
        report = self.gate_failure(firmware, "mediaPinning")
        detail = report.data["sections"]["mediaPinning"]
        self.assertEqual(detail["evictions"]["after"], detail["evictions"]["before"])
        self.assertEqual((detail["cover"]["haveEvicted"]["have"], detail["icon"]["haveEvicted"]["have"]),
                         ([False, False], [False, False]))                     # the store did evict
        self.assertEqual(self.failing(report), {"pinning: diag mediaEvictions grew by at least 4 (two covers, two icons)"})

    def test_a_diag_without_counted_commits_fails_jpegDecode(self):
        class NoCommitsField(FakeFirmware):
            def media_diag(self):
                fields = super().media_diag()
                del fields["mediaCommits"]
                return fields

        class CommitsNeverCounted(FakeFirmware):
            def media_diag(self):
                return {**super().media_diag(), "mediaCommits": 0}

        for firmware in (NoCommitsField(), CommitsNeverCounted()):
            with self.subTest(type(firmware).__name__):
                report = self.gate_failure(firmware, "jpegDecode")
                self.assertEqual(report.data["sections"]["diag"]["media"]["jpegDecodeErrors"], 0)
                self.assertEqual(self.failing(report), {"diag: media commits counted (mediaCommits > 0)"})

    class RemembersPrefetch(FakeFirmware):
        """Records the covers committed while no frame named them (prefetched)."""

        def __init__(self):
            super().__init__()
            self.prefetched = set()

        def media_command(self, body):
            before = len(self.media.committed)
            super().media_command(body)
            if len(self.media.committed) > before:
                kind, key = self.media.committed[-1]
                if kind == "cover" and key != self.media.stores["cover"].frame_key:
                    self.prefetched.add(key)

    def test_a_decode_error_on_the_named_prefetched_cover_fails_mediaPrefetch(self):
        """The LCD draws the named prefetched cover at once, but that decode fails: jpegDecodes moves
        within 1.5 s, only jpegDecodeErrors shows it."""
        class DecodeErrorOnPrefetch(self.RemembersPrefetch):
            failed = False

            def decoded(self):
                super().decoded()
                if not self.failed and self.media.stores["cover"].frame_key in self.prefetched:
                    self.failed = True
                    self.decode_errors += 1

        report = self.gate_failure(DecodeErrorOnPrefetch(), "mediaPrefetch")
        section = report.data["sections"]["mediaPrefetch"]
        self.assertIsNotNone(section["shownSeconds"])
        self.assertTrue(section["named"]["hit"])
        self.assertEqual(section["decodes"]["after"]["jpegDecodeErrors"], 1)
        self.assertEqual(self.section_failures(report, "prefetch"),
                         {"prefetch: the LCD decoded it at once (jpegDecodes +1 within 1.5 s, no decode error, "
                          "jpegDecodeMsLast <= 200 ms)"})
        self.assertFalse(report.gates["jpegDecode"])                            # the end-of-run diag sees it too

    def test_a_named_prefetched_cover_uploaded_again_fails_mediaPrefetch(self):
        """begin misses for a prefetched cover once a frame names it: it is uploaded again, commits and is
        still drawn within 1.5 s; only the begin-hit condition catches it."""
        class MissesNamedPrefetch(FakeMedia):
            def handle(self, body):
                request = body if isinstance(body, dict) else {}
                store, index = self.stores["cover"], None
                if (request.get("op") == "begin" and request.get("kind") == "cover"
                        and request.get("key") in self.prefetched and request.get("key") == store.frame_key):
                    index = store.find(request["key"])
                if index is not None:
                    crc = store.slots[index]["crc"]
                    store.slots[index]["crc"] = crc ^ 1                     # the begin misses
                try:
                    return super().handle(body)
                finally:
                    if index is not None:
                        store.slots[index]["crc"] = crc

        firmware = self.RemembersPrefetch()
        firmware.media.__class__ = MissesNamedPrefetch
        firmware.media.prefetched = firmware.prefetched
        report = self.gate_failure(firmware, "mediaPrefetch")
        section = report.data["sections"]["mediaPrefetch"]
        self.assertEqual((section["named"]["hit"], section["named"]["committed"], section["named"]["beginOffset"]),
                         (False, True, 0))
        self.assertIsNotNone(section["shownSeconds"])
        self.assertTrue(report.gates["mediaErrorStrings"] and report.gates["mediaRoundTrip"])
        self.assertEqual(self.failing(report), {"prefetch: the named prefetched cover is a begin-hit (no upload needed)"})

    def holding_already(self, wanted, kind="cover"):
        """A FakeFirmware whose `kind` store already holds the covers (or icons) `wanted(begin, named,
        unnamed_run)` picks, as if they were kept from an unsalted earlier run on the same boot: their first
        begin is a hit and no data line is sent. `named` is whether the frame names that key; `unnamed_run`
        counts the keys begun without being named since the frame's key last changed (this one included)."""
        class HoldsAlready(FakeMedia):
            state = None

            def handle(self, body):
                state = self.state = self.state or {"frameKey": None, "unnamed": 0, "seeded": 0}
                store = self.stores[kind]
                if isinstance(body, dict) and body.get("op") == "begin" and body.get("kind") == kind:
                    if store.frame_key != state["frameKey"]:
                        state["frameKey"], state["unnamed"] = store.frame_key, 0
                    named = body.get("key") == store.frame_key
                    state["unnamed"] += 0 if named else 1
                    if store.find(body.get("key")) is None and wanted(state, named):
                        state["seeded"] += 1
                        index = store.victim()
                        store.slots[index].update(valid=True, key=body["key"], bytes=body["bytes"], crc=body["crc32"],
                                                  data=b"")
                        store.touch(index)
                return super().handle(body)

        firmware = FakeFirmware()
        firmware.media.__class__ = HoldsAlready
        return firmware

    def test_a_cover_already_held_fails_the_cold_round_trip(self):
        """The round trip's cover is on the knob before its first line: begin is a hit, nothing is uploaded,
        and the round trip shows no cold transfer (every later check of the section still passes)."""
        firmware = self.holding_already(lambda state, named: named and state["seeded"] == 0)
        report = self.gate_failure(firmware, "mediaRoundTrip")
        trip = report.data["sections"]["mediaRoundTrip"]
        self.assertEqual((trip["cover"]["hit"], trip["cover"]["chunks"], trip["cover"]["committed"]), (True, 0, True))
        self.assertEqual(trip["have"]["cover"]["have"], [True, False])
        [failed] = self.failing(report)
        self.assertTrue(failed.startswith("media cover round trip: begin at 0, every data offset acknowledged"), failed)

    def test_a_have_that_claims_a_cover_never_sent_fails_mediaRoundTrip(self):
        """Cover have answers true for a key the knob never received a line for (icons stay right)."""
        class ClaimsUnknownCovers(FakeMedia):
            def handle(self, body):
                seen = self.__dict__.setdefault("seen", set())
                if isinstance(body, dict) and body.get("op") in ("begin", "data", "commit"):
                    seen.add(body.get("key"))
                ack = super().handle(body)
                if isinstance(body, dict) and body.get("op") == "have" and body.get("kind") == "cover" and "have" in ack:
                    ack["have"] = [v or k not in seen for v, k in zip(ack["have"], body["keys"])]
                return ack

        firmware = FakeFirmware()
        firmware.media.__class__ = ClaimsUnknownCovers
        report = self.gate_failure(firmware, "mediaRoundTrip")
        have = report.data["sections"]["mediaRoundTrip"]["have"]
        self.assertEqual((have["cover"]["have"], have["icon"]["have"]), ([True, True], [True, False]))
        self.assertEqual(self.failing(report),
                         {"media have: true for the committed cover and icon, false for a key never sent"})

    def test_prefetched_covers_already_held_fail_mediaPrefetch(self):
        """The three prefetch covers are on the knob already: kept (have) and the named one a begin-hit, but
        none of them was accepted as a new upload."""
        firmware = self.holding_already(lambda state, named: not named and state["seeded"] < 3)
        report = self.gate_failure(firmware, "mediaPrefetch")
        section = report.data["sections"]["mediaPrefetch"]
        self.assertTrue(all(r["hit"] and r["committed"] for r in section["prefetch"]))
        self.assertEqual(section["have"]["have"], [True, True, True])
        self.assertTrue(section["named"]["hit"] and section["shownSeconds"] is not None)
        self.assertEqual(self.failing(report),
                         {"prefetch: three covers the frame does not name are accepted (cold, committed, no error)"})

    def test_a_pinning_cover_already_held_fails_mediaPinning(self):
        """One of the 26 covers that fill the store is on the knob already (a begin-hit): the store still
        keeps the pinned and the newest covers and evicts the two oldest, but not every upload was cold."""
        firmware = self.holding_already(lambda state, named: not named and state["unnamed"] == 5 and not state["seeded"])
        report = self.gate_failure(firmware, "mediaPinning")
        detail = report.data["sections"]["mediaPinning"]
        self.assertFalse(detail["cover"]["allCommittedCold"])
        self.assertEqual((detail["cover"]["haveKept"]["have"], detail["cover"]["haveEvicted"]["have"]),
                         ([True] * 24, [False, False]))
        self.assertEqual(self.failing(report),
                         {"pinning (covers): the frame's cover stays while 26 more fill the 25-slot store; the newest "
                          "23 stay and the two oldest are evicted"})

    def test_a_soak_without_paced_v1_art_is_not_the_gate(self):
        """The soak must keep some paced v1 art (the cc5.2-era companion) among its artwork2 traffic."""
        with mock.patch.object(t, "SOAK_V1_ART_EVERY", 10 ** 6):
            report, _ = self.raw(FakeFirmware())
        soak = report.data["sections"]["soak"]
        self.assertTrue(soak["completed"] and soak["failure"] is None and soak["media"]["icons"] > 0)
        self.assertEqual(soak["media"]["v1Art"], 0)
        self.assertFalse(soak["passed"] or report.gates["unattendedSoak"])
        self.assertEqual(self.failing(report), {"unattended soak: 1 min completed with no hang, reboot, re-enumeration, "
                                                "error, forced release or LED transmit failure"})

    def slow_timing(self, firmware):
        """Patch check_nanod_cc5.media_timing so `firmware.slow` is set during that section only."""
        original = self.module.media_timing

        def timed(ctx, out):
            firmware.slow = True
            try:
                return original(ctx, out)
            finally:
                firmware.slow = False
        return mock.patch.object(self.module, "media_timing", timed)

    class SlowMedia(FakeFirmware):
        """While `slow`, each media line of `kinds` takes `delay` s of the shared fake clock to answer."""
        slow, delay, kinds = False, 0.0, ()

        def media_command(self, body):
            if self.slow and body.get("kind") in self.kinds:
                end = self.clock() + self.delay
                while self.clock() < end:
                    pass
            return super().media_command(body)

    def test_one_slow_media_ack_fails_unpacedTransferTiming(self):
        firmware = self.SlowMedia()
        firmware.kinds, firmware.delay = ("icon",), t.presentation().MEDIA_ACK_TIMEOUT_SECONDS + 0.1
        with self.slow_timing(firmware):
            report = self.gate_failure(firmware, "unpacedTransferTiming")
        timing = report.data["sections"]["mediaTiming"]
        self.assertGreater(timing["perLine"]["maxMs"], 1500)
        self.assertLessEqual(max(timing["coverSeconds"]), t.COVER_TRANSFER_MAX_SECONDS)
        self.assertEqual(self.section_failures(report, "unpaced timing"),
                         {"unpaced timing: every media ack within 1.5 s (the host's ack timeout)"})

    def test_a_slow_cover_fails_unpacedTransferTiming(self):
        firmware = self.SlowMedia()
        firmware.kinds, firmware.delay = ("cover",), 0.6          # every line in time, every cover too slow
        with self.slow_timing(firmware):
            report = self.gate_failure(firmware, "unpacedTransferTiming")
        timing = report.data["sections"]["mediaTiming"]
        self.assertLessEqual(timing["perLine"]["maxMs"], 1500)
        self.assertGreater(min(timing["coverSeconds"]), t.COVER_TRANSFER_MAX_SECONDS)
        self.assertEqual(self.section_failures(report, "unpaced timing"),
                         {"unpaced timing: every cover (begin to commit) within 1.5 s (a paced 120 px v1 cover took "
                          "about 5 s)"})

    def test_a_receive_queue_other_than_8192_fails_artwork2Capability(self):
        class SmallQueue(FakeFirmware):
            def diag_extra(self):
                return {"rxQueueBytes": 4096}

        report = self.gate_failure(SmallQueue(), "artwork2Capability")
        self.assertEqual(self.failing(report), {"diag: receive queue 8192 B in internal RAM (rxQueueBytes, rxQueue)"})
        self.assertTrue(report.gates["mediaRoundTrip"] and report.gates["unpacedTransferTiming"])

    class ForgetsUnderLoad(FakeFirmware):
        """Under the load of the frames tagged `prefix`, every cover commit drops the older covers the LCD
        does not pin: every upload still commits, but `have` misses the recent covers."""
        prefix = "Stress"

        def show(self, frame):
            self.loaded = tagged(frame, self.prefix)
            return super().show(frame)

        def media_command(self, body):
            super().media_command(body)
            if (body.get("op") == "commit" and body.get("kind") == "cover"
                    and getattr(self, "loaded", False)):
                store = self.media.stores["cover"]
                for index, slot in enumerate(store.slots):
                    if slot["valid"] and not store.pinned(index):
                        slot["valid"] = False

    def test_a_store_that_forgets_recent_covers_under_stress_fails_both_stress_gates(self):
        report, _ = self.raw(self.ForgetsUnderLoad())
        for name in ("stress", "stressTurn"):
            section = report.data["sections"][name]
            self.assertGreater(section["media"]["haveMisses"], 0, name)
            self.assertEqual(section["committed"], section["transfers"], name)
            self.assertFalse(section["errors"] or section["released"] or section["mediaErrors"], name)
        self.assertFalse(report.gates["stressUntouched"] or report.gates["stressTurn"])
        self.assertTrue(report.gates["unattendedSoak"] and report.gates["turningDetected"])

    def test_a_store_that_forgets_recent_covers_in_the_soak_stops_it(self):
        firmware = self.ForgetsUnderLoad()
        firmware.prefix = "Soak"
        report, _ = self.soak_failure(firmware, "have lost a recent cover")
        self.assertGreater(report.data["sections"]["soak"]["media"]["haveMisses"], 0)

    def test_a_v1_art_failure_in_the_untouched_pass_fails_stressUntouched(self):
        """With artwork2 negotiated the untouched pass still runs the paced v1 art stress first: a
        knob whose v1 art breaks only under that load fails stressUntouched, although the unpaced
        media stress after it passes."""
        class V1BreaksUnderStress(FakeFirmware):
            def art(self, body):
                if str(body.get("key", "")).startswith("cc5p") and body.get("op") == "commit":
                    self.reply({"artAck": {"id": body.get("id"), "key": body.get("key"), "op": "commit",
                                           "offset": t.ART_BYTES, "error": "Artwork checksum mismatch"}})
                    return
                super().art(body)

        report, _ = self.raw(V1BreaksUnderStress())
        stress = report.data["sections"]["stress"]
        self.assertFalse(stress["v1"]["passed"])
        self.assertTrue(stress["passed"], "the unpaced media stress itself passed")
        self.assertFalse(report.gates["stressUntouched"])
        self.assertTrue(report.gates["stressTurn"] and report.gates["v1ArtCompatible"])
        self.assertTrue(any(name.startswith("stress (untouched, paced v1 art: the 1.0.0-cc5 run-1 sequence")
                            for name in report.data["failures"]))

    def test_without_artwork2_the_media_sections_fail_fast_and_the_stress_stays_v1(self):
        """A cc5.2 knob (no artwork2): every artwork2 gate fails, nothing hangs, v1 art and the stress still run."""
        class Cc52(FakeFirmware):
            def capabilities(self):
                caps = super().capabilities()
                del caps["artwork2"]
                return caps

        firmware = Cc52()
        report, _ = self.raw(firmware)
        for gate in ("artwork2Capability", "mediaRoundTrip", "mediaPrefetch", "mediaPinning", "mediaErrorStrings",
                     "unpacedTransferTiming", "jpegDecode"):
            self.assertFalse(report.gates[gate], gate)
        for name in ("mediaRoundTrip", "mediaPrefetch", "mediaPinning", "mediaErrors", "mediaTiming"):
            detail = next(c["detail"] for c in report.data["checks"] if c["check"] == f"{name}: completed")
            self.assertIn("artwork2 is not negotiated", detail)
        self.assertTrue(report.gates["v1ArtCompatible"] and report.gates["stressUntouched"] and report.gates["stressTurn"])
        self.assertNotIn("unpaced", report.data["sections"]["stress"])
        self.assertTrue(report.data["sections"]["stress"]["run1Replay"])     # the pass itself is the replay
        self.assertNotIn("v1", report.data["sections"]["stress"])
        self.assertNotIn(("media", "whole"), set(firmware.shapes))

    def soak_failure(self, firmware, fragment):
        report, watch = self.raw(firmware)
        soak = report.data["sections"]["soak"]
        self.assertFalse(soak["passed"])
        self.assertIn(fragment, soak["failure"])
        self.assertFalse(report.gates["unattendedSoak"])
        self.assertIn("unattended soak: 1 min completed with no hang, reboot, re-enumeration, error, forced release "
                      "or LED transmit failure", report.data["failures"])
        self.assertIn("!!! SOAK STOPPED", self.out.getvalue())
        self.assertTrue(report.gates["stressUntouched"] and report.gates["stressTurn"])   # earlier gates unaffected
        return report, watch

    def test_a_forced_release_stops_the_soak(self):
        class ForcedRelease(FakeFirmware):
            def release_reply(self):
                if self.soaking:
                    return {"released": True, "reason": "forced", "unacked": ["hmi"]}
                return super().release_reply()

        report, _ = self.soak_failure(ForcedRelease(), "FORCED RELEASE")
        self.assertEqual(len(report.data["sections"]["soak"]["releases"]), 1)       # stopped at the first

    def test_a_stalled_hmi_stops_the_soak_at_its_checkpoint(self):
        """1.0.0-cc5.1's hang: COM, LCD and FOC answer, HMI stopped; only its age shows it."""
        class HmiHang(FakeFirmware):
            def diag_extra(self):
                return {"hmiAgeMs": 24000, "hmiStep": "show"} if self.soaking else {}

        report, watch = self.soak_failure(HmiHang(), "checkpoint 1 failed")
        failing = [(w, p) for w, p in watch.calls if p]
        self.assertTrue(failing[0][0].startswith("soak 1"))
        self.assertIn("TASK STALLED: hmiAgeMs 24000 ms > 1000 ms at step 'show'", failing[0][1][0])
        self.assertIn("no reboot or USB re-enumeration: soak", report.data["failures"])   # the section checkpoint
        self.assertIn("no reboot or USB re-enumeration: diag", report.data["failures"])

    def test_an_led_transmit_timeout_stops_the_soak(self):
        class LedTimeout(FakeFirmware):
            def diag_extra(self):
                return {"ledTxTimeouts": 1} if self.soaking else {}

        _, watch = self.soak_failure(LedTimeout(), "checkpoint 1 failed")
        self.assertIn("LED TRANSMIT TIMEOUT", next(p for _, p in watch.calls if p)[0])

    def test_an_error_reply_stops_the_soak(self):
        class Rejects(FakeFirmware):
            def line(self, text):
                if self.soaking and text.startswith('{"frame"') and self.lines % 40 == 0:
                    self.lines += 1
                    return self.reply({"error": "Invalid control frame"})
                return super().line(text)

        self.soak_failure(Rejects(), "error reply during the soak")

    def test_a_soak_shorter_than_the_gate_passes_but_is_not_the_gate(self):
        report, _ = self.raw(FakeFirmware(), soak_minutes=0.6, gate_minutes=20.0)
        self.assertTrue(report.data["sections"]["soak"]["passed"])
        self.assertEqual(report.data["failures"], [])
        self.assertFalse(report.gates["unattendedSoak"])
        self.assertIn("the unattendedSoak gate needs 20 min", self.out.getvalue())

    def test_a_skipped_soak_fails(self):
        report, _ = self.raw(FakeFirmware(), soak_minutes=0.0)
        self.assertIn("unattended soak: skipped (--soak-minutes 0); the unattendedSoak gate needs at least 1 min",
                      report.data["failures"])
        self.assertFalse(report.gates["unattendedSoak"])

    def test_an_operator_who_never_turns_stops_the_run_not_the_firmware(self):
        """Nobody turns on "Turn back and forth": the step's safety timeout ends the run as an operator stop (exit 4
        in main), recorded as such; no firmware failure is added and the skipped gates stay false."""
        self.assertEqual(self.module.TURN_CHECK,
                         f"stress+turn: turning detected during the stress (>= {t.TURN_MIN_EVENTS} claimed position "
                         "events inside its frame window, no pause > 3 s)")
        firmware = FakeFirmware()
        with self.assertRaises(t.OperatorTimeout) as caught:
            self.raw(firmware, operator={"absent": ("Turn back and forth",)}, step_timeout=5.0)
        stop = caught.exception
        self.assertEqual((stop.step, stop.of, stop.name, stop.exit_code), (2, 2, "turn", t.OPERATOR_EXIT))
        report = self.last_report
        self.assertEqual(report.data["operatorStop"]["reason"], "operator did not complete step 2")
        self.assertFalse(report.data["operatorStop"]["firmwareFailure"])
        self.assertEqual(report.data["failures"], [])
        self.assertFalse(report.gates["turningDetected"] or report.gates["stressTurn"] or report.gates["unattendedSoak"])
        self.assertTrue(report.gates["stressUntouched"])
        self.assertNotIn("soak", report.data["sections"])
        self.assertEqual(report.data["prompts"]["stopped"]["waitingFor"], "turning (3 position events within 1.5 s)")
        self.assertEqual(report.data["finalRelease"], {"released": True})
        self.assertTrue(firmware.closed)

    def test_a_knob_whose_position_events_stop_under_the_stress_fails_to_rerun(self):
        """The knob sends positions while the operator turns before the stress, and none once the stress frames
        run (an input stall under load): every attempt stops at the 3 s pause, the last one runs the stress to its
        minimum, and turningDetected fails as before (a firmware result, never a pass)."""

        class StallsUnderStress(FakeFirmware):
            def show(self, frame):
                self.stressed = tagged(frame, "Stress")
                return super().show(frame)

            def sweep_step(self):
                if not getattr(self, "stressed", False):
                    super().sweep_step()

        report, _ = self.raw(StallsUnderStress())
        self.assertEqual(report.data["failures"], [self.module.TURN_CHECK])
        self.assertFalse(report.gates["turningDetected"])
        self.assertTrue(report.gates["stressTurn"] and report.gates["stressUntouched"])
        turn = report.data["sections"]["stressTurn"]
        self.assertEqual([(a["stopped"], a["gap"]) for a in turn["turnAttempts"]],
                         [("gap", True), ("gap", True), (None, True)])
        self.assertEqual([r["reason"] for r in report.data["prompts"]["steps"][1]["retries"]],
                         ["You stopped for 3 s"] * 2)
        events = turn["knobEvents"]
        self.assertGreater(events["duringTransfers"], 0)
        self.assertLess(events["duringStress"], t.TURN_MIN_EVENTS)
        detail = next(c["detail"] for c in report.data["checks"] if c["check"] == self.module.TURN_CHECK)
        self.assertIn("turning not detected during stress; rerun", detail[0])
        self.assertIn("inside the stress-frame window", detail[0])

    def test_a_turning_pause_aborts_the_attempt_and_the_next_one_passes(self):
        """The operator stops for 4 s once the live progress shows: that attempt ends at the 3 s pause ("You
        stopped for 3 s" on the knob), the next passes; the gates are judged on it."""
        report, _ = self.raw(FakeFirmware(), operator={"pause_s": 4.0})
        self.assertEqual(report.data["failures"], [])
        self.assertTrue(report.gates["turningDetected"] and report.gates["stressTurn"])
        attempts = report.data["sections"]["stressTurn"]["turnAttempts"]
        self.assertEqual([(a["stopped"], a["passed"]) for a in attempts], [("gap", False), (None, True)])
        self.assertEqual(report.data["sections"]["stressTurn"]["window"], attempts[-1]["window"])
        self.assertEqual([r["reason"] for r in report.data["prompts"]["steps"][1]["retries"]], ["You stopped for 3 s"])

    def test_a_touched_untouched_pass_is_rerun(self):
        """A knob event during the untouched pass aborts it ("You touched the knob" on the knob), 3 s of quiet
        follow, and the pass runs again from its cold transfers; the gate is the last attempt's."""
        def touch(operator, view):
            if view["progress"] == self.module.UNTOUCHED and not getattr(operator, "touched", False):
                operator.touched = True
                operator.fw.schedule(4.0, lambda: operator.fw.emit(operator.fw.event(p=3)))
        report, _ = self.raw(FakeFirmware(), operator={"actions": {self.module.AUTOMATIC: touch}})
        self.assertEqual(report.data["failures"], [])
        stress = report.data["sections"]["stress"]
        self.assertEqual([a["attempt"] for a in stress["attempts"]], [1, 2])
        self.assertTrue(stress["attempts"][0]["v1Aborted"])
        self.assertEqual(stress["attempts"][1]["replayCommitted"], 3)
        self.assertEqual((stress["knobEvents"], stress["v1"]["knobEvents"]), (0, 0))
        self.assertTrue(report.gates["stressUntouched"])

    def test_a_screen_never_confirmed_stops_before_anything_else(self):
        """Nobody presses Button 4 on "Can you see this?" (a dark screen, or nobody there): the run stops as "screen
        not confirmed" (exit 5 in main), no other instruction is ever shown and no section after it runs."""
        firmware = FakeFirmware()
        with self.assertRaises(t.ScreenNotConfirmed) as caught:
            self.raw(firmware, operator={"blind": True}, step_timeout=3.0)
        self.assertEqual((caught.exception.reason, caught.exception.exit_code), ("screen not confirmed", t.SCREEN_EXIT))
        report = self.last_report
        self.assertEqual(report.data["operatorStop"]["kind"], "screen-not-confirmed")
        self.assertEqual(report.data["failures"], [])
        self.assertEqual(list(report.data["sections"]), ["displayCheck"])
        sent = [json.loads(line) for line in firmware.received if line.startswith(('{"frame"', '{"control"'))] \
            if hasattr(firmware, "received") else []
        titles = {d.get("frame", d.get("control", {}).get("frame", {})).get("title") for d in sent}
        self.assertLessEqual(titles, {t.PROMPT_SEE})
        self.assertEqual(len(firmware.controls), 1)                       # only the display check's control
        self.assertFalse(report.data["prompts"]["displayCheck"]["confirmed"])
        self.assertEqual(report.data["finalRelease"], {"released": True})

    def test_a_reboot_during_the_stress_fails_that_checkpoint(self):
        """A reset right after the untouched stress's first cover: bootCount moves, that checkpoint fails."""
        run = {}

        class Rebooting(FakeFirmware):
            def show(self, frame):
                self.stressed = tagged(frame, "Stress")
                return super().show(frame)

            def media_command(self, body):
                if body.get("op") == "commit" and getattr(self, "stressed", False) and not run:
                    run["done"] = True
                    self.boot += 1
                return super().media_command(body)

        report, watch = self.raw(Rebooting())
        self.assertIn("no reboot or USB re-enumeration: stress", report.data["failures"])
        [(where, problems)] = [(w, p) for w, p in watch.calls if p]
        self.assertEqual(where, "stress")
        self.assertIn("bootCount 7 -> 8", problems[0])

    # 1.0.0-cc5.3 integration: the icon half of the round trip and prefetch, the capability gate's v1
    # and presentation conditions, the timing section's cold rule, and failing artwork2 traffic inside
    # the soak and the two stress passes. Each fake breaks one condition; the test names the check (or
    # the soak's failure text) that must catch it, so dropping that condition turns the test red.

    PREFETCH_ICON = ("prefetch: an icon the frame does not name is accepted, kept (have) and a begin-hit once a "
                     "Windows frame names it")

    def with_media(self, media_class, firmware=None):
        firmware = firmware or FakeFirmware()
        firmware.media.__class__ = media_class
        firmware.media.firmware = firmware
        return firmware

    def test_an_icon_store_without_begin_hits_fails_the_round_trip_and_prefetch(self):
        """Every icon begin is a miss (the store forgets the key at begin): each re-sent icon uploads again
        and commits, so only the icon begin-hit conditions catch it."""
        class NeverIconHit(FakeMedia):
            def handle(self, body):
                if isinstance(body, dict) and body.get("kind") == "icon" and body.get("op") == "begin":
                    index = self.stores["icon"].find(body.get("key"))
                    if index is not None:
                        self.stores["icon"].slots[index]["valid"] = False
                return super().handle(body)

        report = self.gate_failure(self.with_media(NeverIconHit), "mediaRoundTrip")
        self.assertFalse(report.gates["mediaPrefetch"])
        trip = report.data["sections"]["mediaRoundTrip"]
        self.assertEqual((trip["iconHit"]["hit"], trip["iconHit"]["committed"], trip["iconHit"]["beginOffset"]),
                         (False, True, 0))
        self.assertTrue(trip["coverHit"]["hit"])
        named = report.data["sections"]["mediaPrefetch"]["icon"]["named"]
        self.assertEqual((named["hit"], named["committed"]), (False, True))
        self.assertEqual(self.section_failures(report, "media icon") | self.section_failures(report, "prefetch"),
                         {"media icon begin-hit", self.PREFETCH_ICON})

    def test_an_icon_already_held_fails_the_cold_icon_round_trip(self):
        firmware = self.holding_already(lambda state, named: named and state["seeded"] == 0, kind="icon")
        report = self.gate_failure(firmware, "mediaRoundTrip")
        icon = report.data["sections"]["mediaRoundTrip"]["icon"]
        self.assertEqual((icon["hit"], icon["chunks"], icon["committed"]), (True, 0, True))
        self.assertEqual(self.failing(report),
                         {"media icon round trip: begin at 0, one 2048 B data line, commit"})

    def test_a_prefetched_icon_already_held_fails_mediaPrefetch(self):
        firmware = self.holding_already(lambda state, named: not named and state["seeded"] == 0, kind="icon")
        report = self.gate_failure(firmware, "mediaPrefetch")
        section = report.data["sections"]["mediaPrefetch"]["icon"]
        self.assertEqual((section["prefetch"]["hit"], section["have"]["have"], section["named"]["hit"]),
                         (True, [True], True))
        self.assertEqual(self.failing(report), {self.PREFETCH_ICON})

    def test_a_round_trip_cover_that_uploads_again_fails_its_begin_hit(self):
        """The first re-begin of a committed cover (the round trip's second transfer) is a miss: the cover
        uploads and commits again. Later hits (the named prefetched cover) still work."""
        class ForgetsOnce(FakeMedia):
            forgot = False

            def handle(self, body):
                if (not self.forgot and isinstance(body, dict) and body.get("kind") == "cover"
                        and body.get("op") == "begin"):
                    index = self.stores["cover"].find(body.get("key"))
                    if index is not None:
                        self.forgot = True
                        self.stores["cover"].slots[index]["valid"] = False
                return super().handle(body)

        report = self.gate_failure(self.with_media(ForgetsOnce), "mediaRoundTrip")
        hit = report.data["sections"]["mediaRoundTrip"]["coverHit"]
        self.assertEqual((hit["hit"], hit["committed"]), (False, True))
        self.assertTrue(report.gates["mediaPrefetch"])
        self.assertEqual(self.failing(report),
                         {"media cover begin-hit: begin answers the full size, no data line, commit succeeds"})

    # A commit acknowledged short (offset 0) with no error, once, inside the round trip or the prefetch.
    # The knob did store the key (or ended the begin-hit), so the begin-hits after it, have and the
    # section's error watch all pass: only that transfer's own "committed" condition can catch it.

    def in_section(self, firmware, name):
        """Patch check_nanod_cc5.<name> (a media section) so `firmware.section` names it while it runs."""
        original = getattr(self.module, name)

        def run(ctx, out):
            firmware.section = name
            try:
                return original(ctx, out)
            finally:
                firmware.section = None
        return mock.patch.object(self.module, name, run)

    class ShortCommitIn(FakeMedia):
        """The first commit matching `target` = (section, kind, hit, named) is acknowledged with offset 0
        and no error; `shorted` is its key. `section` is the media section running (in_section), `hit`
        whether the upload was a begin-hit, `named` whether the frame names its key."""
        target, shorted = None, None

        def handle(self, body):
            up = self.upload
            ack = super().handle(body)
            if (self.shorted is None and up and isinstance(body, dict) and body.get("op") == "commit"
                    and "error" not in ack and (up["kind"], up["key"]) == (body.get("kind"), body.get("key"))
                    and (getattr(self.firmware, "section", None), up["kind"], up["hit"],
                         up["key"] == self.stores[up["kind"]].frame_key) == self.target):
                self.shorted = up["key"]
                ack = {**ack, "offset": 0}
            return ack

    def short_commit_in(self, section, kind, hit, named, gate):
        media = type("Short", (self.ShortCommitIn,), {"target": (section, kind, hit, named)})
        firmware = self.with_media(media)
        with self.in_section(firmware, section):
            report = self.gate_failure(firmware, gate)
        self.assertIsNotNone(firmware.media.shorted, "the fake shorted one commit")
        self.assertTrue(report.gates["mediaPrefetch" if gate == "mediaRoundTrip" else "mediaRoundTrip"])
        return report, firmware.media.shorted

    def test_a_round_trip_commit_acknowledged_short_fails_only_its_own_check(self):
        cases = {   # the round trip's brief: (kind, begin-hit), its check, and (hit, data lines) in the brief
            "icon": (("icon", False), "media icon round trip: begin at 0, one 2048 B data line, commit", (False, 1)),
            "iconHit": (("icon", True), "media icon begin-hit", (True, 0)),
            "coverHit": (("cover", True), "media cover begin-hit: begin answers the full size, no data line, commit "
                                          "succeeds", (True, 0)),
        }
        for field, ((kind, hit), check, (brief_hit, chunks)) in cases.items():
            with self.subTest(field):
                report, key = self.short_commit_in("media_round_trip", kind, hit, True, "mediaRoundTrip")
                trip = report.data["sections"]["mediaRoundTrip"]
                self.assertEqual(tuple(trip[field][k] for k in ("key", "hit", "chunks", "committed", "error")),
                                 (key, brief_hit, chunks, False, None))
                self.assertEqual((trip["have"]["cover"]["have"], trip["have"]["icon"]["have"]),
                                 ([True, False], [True, False]))
                self.assertEqual(self.failing(report), {check})

    def test_a_prefetch_icon_commit_acknowledged_short_fails_mediaPrefetch(self):
        """The prefetch's three icon transfers: the one a Windows frame names, the one no frame names, and
        that one again once a frame names it (a begin-hit)."""
        cases = {"named icon": ("now", False, True), "unnamed icon": ("prefetch", False, False),
                 "named-again icon": ("named", True, True)}
        for what, (which, hit, named) in cases.items():
            with self.subTest(what):
                report, key = self.short_commit_in("media_prefetch", "icon", hit, named, "mediaPrefetch")
                icon = report.data["sections"]["mediaPrefetch"]["icon"]
                self.assertEqual(icon["have"]["have"], [True])
                self.assertEqual((icon["prefetch"]["hit"], icon["named"]["hit"]), (False, True))
                self.assertEqual(icon["prefetch"]["key"], icon["named"]["key"])
                self.assertEqual(icon["prefetch"]["key"] == key, which != "now")
                for field in ("prefetch", "named"):
                    self.assertEqual((icon[field]["committed"], icon[field]["error"]), (field != which, None), field)
                self.assertEqual(self.failing(report), {self.PREFETCH_ICON})

    def test_a_timing_cover_already_held_fails_unpacedTransferTiming(self):
        """One of the five timed covers is on the knob already: its transfer is a begin-hit, fast and
        committed, but the section times cold transfers only."""
        class HoldsATimedCover(FakeMedia):
            seeded = False

            def handle(self, body):
                if (getattr(self.firmware, "slow", False) and not self.seeded and isinstance(body, dict)
                        and body.get("kind") == "cover" and body.get("op") == "begin"):
                    self.seeded = True
                    store = self.stores["cover"]
                    index = store.victim()
                    store.slots[index].update(valid=True, key=body["key"], bytes=body["bytes"], crc=body["crc32"],
                                              data=b"")
                    store.touch(index)
                return super().handle(body)

        firmware = self.with_media(HoldsATimedCover)
        with self.slow_timing(firmware):              # sets firmware.slow during media_timing only
            report = self.gate_failure(firmware, "unpacedTransferTiming")
        self.assertEqual(self.section_failures(report, "unpaced timing"),
                         {"unpaced timing: five cold covers and five cold icons committed"})
        self.assertEqual(self.failing(report), {"unpaced timing: five cold covers and five cold icons committed"})

    def test_a_changed_v1_artwork_capability_fails_artwork2Capability(self):
        class V1Changed(FakeFirmware):
            def capabilities(self):
                caps = super().capabilities()
                caps["artwork"] = {**caps["artwork"], "cacheEntries": caps["artwork"]["cacheEntries"] + 1}
                return caps

        report = self.gate_failure(V1Changed(), "artwork2Capability")
        self.assertIn("raw capabilities: artwork (v1) byte-identical to cc5.2's", self.failing(report))
        self.assertNotIn("raw capabilities: artwork2 equals presentation.ARTWORK2_CAPABILITY, presentation 4",
                         self.failing(report))

    def test_presentation_3_with_artwork2_fails_artwork2Capability(self):
        """artwork2 exactly as the contract, but presentation 3: the host must not negotiate it."""
        class Presentation3(FakeFirmware):
            def capabilities(self):
                return {**super().capabilities(), "presentation": 3}

        report, _ = self.raw(Presentation3())
        self.assertFalse(report.gates["artwork2Capability"])
        self.assertIn("raw capabilities: artwork2 equals presentation.ARTWORK2_CAPABILITY, presentation 4",
                      self.failing(report))

    # The soak: each kind of artwork2 traffic failing on its own stops it with its own failure text.

    def media_soak_failure(self, firmware):
        report, _ = self.raw(firmware)
        soak = report.data["sections"]["soak"]
        self.assertFalse(report.gates["unattendedSoak"])
        self.assertFalse(soak["passed"] or soak["completed"])
        self.assertTrue(report.gates["stressUntouched"] and report.gates["stressTurn"] and report.gates["mediaRoundTrip"])
        self.assertIn("unattended soak: 1 min completed with no hang, reboot, re-enumeration, error, forced release or "
                      "LED transmit failure", self.failing(report))
        return soak["failure"]

    class SoakRefusal(FakeMedia):
        """While soaking, a begin that `refuses(body, store)` picks is answered "Media unavailable"."""
        refuses = staticmethod(lambda body, store: False)

        def handle(self, body):
            if (self.firmware.soaking and isinstance(body, dict) and body.get("op") == "begin"
                    and body.get("kind") in self.stores and self.refuses(body, self.stores[body["kind"]])):
                self.errors += 1
                return {"id": body.get("id"), "op": "begin", "kind": body["kind"], "key": body.get("key"),
                        "offset": 0, "error": "Media unavailable"}
            return super().handle(body)

    def refusing_in_soak(self, refuses):
        media = type("Refusal", (self.SoakRefusal,), {"refuses": staticmethod(refuses)})
        return self.with_media(media)

    def test_a_refused_soak_icon_stops_the_soak(self):
        failure = self.media_soak_failure(self.refusing_in_soak(lambda body, store: body["kind"] == "icon"))
        self.assertRegex(failure, r"^SoakFailure: media icon \S+ failed at begin: Media unavailable$")

    def test_a_refused_soak_cover_stops_the_soak(self):
        failure = self.media_soak_failure(self.refusing_in_soak(
            lambda body, store: body["kind"] == "cover" and body.get("key") == store.frame_key))
        self.assertRegex(failure, r"^SoakFailure: media cover \S+ failed at begin: Media unavailable$")

    def test_a_refused_soak_prefetch_stops_the_soak(self):
        failure = self.media_soak_failure(self.refusing_in_soak(
            lambda body, store: body["kind"] == "cover" and body.get("key") != store.frame_key))
        self.assertRegex(failure, r"^SoakFailure: prefetch cover \S+ failed at begin: Media unavailable$")

    def test_a_short_data_ack_in_the_soak_stops_it_without_a_media_error(self):
        """A data ack with the wrong offset and no error: a failed transfer that is not a mediaAck error."""
        class ShortDataAck(FakeMedia):
            shorted, soak_errors = False, 0

            def handle(self, body):
                ack = super().handle(body)
                if self.firmware.soaking and "error" in ack:
                    self.soak_errors += 1
                if (self.firmware.soaking and not self.shorted and isinstance(body, dict) and body.get("op") == "data"
                        and "error" not in ack):
                    self.shorted = True
                    ack = {**ack, "offset": ack["offset"] - 1}
                return ack

        firmware = self.with_media(ShortDataAck)
        failure = self.media_soak_failure(firmware)
        self.assertRegex(failure, r"^SoakFailure: media cover \S+ failed at data: offset \d+ != \d+$")
        self.assertTrue(firmware.media.shorted)
        self.assertEqual(firmware.media.soak_errors, 0, "no mediaAck error during the soak")

    def test_an_uncommitted_soak_transfer_without_an_error_stops_the_soak(self):
        """A commit acknowledged short (offset 0) with no error, once, for each kind of soak slot. The
        knob did store it, so no later have query or error watch notices: only that slot's own
        "committed" condition stops the soak, and its failure text says why (the transfer has no error
        to name, so "failed at None: None" would tell the operator nothing after a 20 min soak)."""
        class ShortCommit(FakeMedia):
            picks = staticmethod(lambda body, store: False)
            shorted = False

            def handle(self, body):
                ack = super().handle(body)
                if (self.firmware.soaking and not self.shorted and isinstance(body, dict) and body.get("op") == "commit"
                        and body.get("kind") in self.stores and "error" not in ack
                        and self.picks(body, self.stores[body["kind"]])):
                    self.shorted = True
                    ack = {**ack, "offset": 0}
                return ack

        class ShortV1Commit(FakeFirmware):
            shorted = False

            def art(self, body):
                if self.soaking and not self.shorted and body.get("op") == "commit":
                    self.shorted = True
                    return self.reply({"artAck": {"id": body.get("id"), "key": body.get("key"), "op": "commit",
                                                  "offset": 0}})
                return super().art(body)

        def short_commit(picks):
            return self.with_media(type("Short", (ShortCommit,), {"picks": staticmethod(picks)}))

        cases = {
            "media cover": lambda: short_commit(lambda body, store: body["kind"] == "cover"
                                                and body.get("key") == store.frame_key),
            "media icon": lambda: short_commit(lambda body, store: body["kind"] == "icon"),
            "prefetch cover": lambda: short_commit(lambda body, store: body["kind"] == "cover"
                                                   and body.get("key") != store.frame_key),
            "v1 art transfer": ShortV1Commit,
        }
        for what, make in cases.items():
            with self.subTest(what):
                firmware = make()
                failure = self.media_soak_failure(firmware)
                self.assertRegex(failure, rf"^SoakFailure: {what} \S+ failed at commit: not committed \(the commit "
                                          r"ack carries no error but its offset is not the full size; beginOffset 0, "
                                          r"[1-9]\d* data lines\)$")
                shorted = firmware.shorted if isinstance(firmware, ShortV1Commit) else firmware.media.shorted
                self.assertTrue(shorted)

    def test_a_failed_paced_v1_commit_stops_the_soak(self):
        class SoakV1CommitFails(FakeFirmware):
            def art(self, body):
                if self.soaking and body.get("op") == "commit":
                    return self.reply({"artAck": {"id": body.get("id"), "key": body.get("key"), "op": "commit",
                                                  "offset": t.ART_BYTES, "error": "Artwork checksum mismatch"}})
                return super().art(body)

        failure = self.media_soak_failure(SoakV1CommitFails())
        self.assertRegex(failure, r"^SoakFailure: v1 art transfer \S+ failed at commit: Artwork checksum mismatch$")

    def test_a_stray_media_error_in_the_soak_stops_it(self):
        """A mediaAck error that no transfer waits for (it arrives just ahead of a diag reply): only the
        soak's error watch sees it."""
        class StrayMediaError(FakeFirmware):
            strayed = False

            def line(self, text):
                if self.soaking and not self.strayed and text.startswith('{"diag"'):
                    self.strayed = True
                    self.reply({"mediaAck": {"op": "parse", "error": "parse"}})
                return super().line(text)

        failure = self.media_soak_failure(StrayMediaError())
        self.assertTrue(failure.startswith("SoakFailure: media error during the soak: "), failure)

    def test_a_stray_art_error_in_the_soak_stops_it(self):
        """The same for an artAck error (the soak carries paced v1 art): only the watch's art condition sees it."""
        class StrayArtError(FakeFirmware):
            strayed = False

            def line(self, text):
                if self.soaking and not self.strayed and text.startswith('{"diag"'):
                    self.strayed = True
                    self.reply({"artAck": {"op": "parse", "error": "parse"}})
                return super().line(text)

        firmware = StrayArtError()
        failure = self.media_soak_failure(firmware)
        self.assertTrue(firmware.strayed)
        self.assertRegex(failure,
                         r"^SoakFailure: art error during the soak: \[\(\S+, \{'op': 'parse', 'error': 'parse'\}\)\]$")

    # The stress passes: one failing media line late in each pass, after its frames were sent.

    class LateStressFailure(FakeFirmware):
        """In each stress pass (untouched, then turning), once more than 40 stress frames arrived, one
        media line fails: the frame's cover `op` refused ("error"), the frame's cover commit acknowledged
        short with no error ("short"), or no line but a stray mediaAck error after a heartbeat of the last
        stress frame ("stray"). Every other line is answered normally. `after` counts each pass's media
        lines after its failure (none: the pass stopped there)."""

        def __init__(self, mode, op="begin"):
            super().__init__()
            self.mode, self.op = mode, op
            self.seen, self.failed, self.previous = {False: 0, True: 0}, set(), None
            self.after = {False: 0, True: 0}

        def show(self, frame):
            # Unpaced stress frames only: the paced v1 art stress that opens the untouched pass
            # names its v1 covers (cc5p...) and never carries media lines.
            if tagged(frame, "Stress") and not str(frame.get("artKey", "")).startswith("cc5p"):
                self.seen[self.turning] += 1
            super().show(frame)

        def late(self):
            return self.seen[self.turning] > 40 and self.turning not in self.failed

        def line(self, text):
            heartbeat = text.startswith('{"frame"') and text == self.previous
            if text.startswith('{"frame"'):
                self.previous = text
            super().line(text)
            if self.mode == "stray" and heartbeat and re.search(r"Stress \d+ ", text) and self.late():
                self.failed.add(self.turning)
                self.reply({"mediaAck": {"op": "parse", "error": "parse"}})

        def media_command(self, body):
            if self.turning in self.failed and not self.soaking:
                self.after[self.turning] += 1
            if (self.mode != "stray" and self.late() and isinstance(body, dict) and body.get("kind") == "cover"
                    and body.get("op") == self.op and body.get("key") == self.media.stores["cover"].frame_key):
                self.failed.add(self.turning)
                if self.mode == "error":
                    self.media.errors += 1
                    return self.reply({"mediaAck": {"id": body.get("id"), "op": body["op"], "kind": "cover",
                                                    "key": body.get("key"), "offset": 0, "error": "Media unavailable"}})
                return self.reply({"mediaAck": {**self.media.handle(body), "offset": 0}})
            return super().media_command(body)

    def stress_failure(self, firmware):
        report, _ = self.raw(firmware)
        self.assertEqual(firmware.failed, {False, True}, "one failure in each stress pass")
        sections = [report.data["sections"][name] for name in ("stress", "stressTurn")]
        for section in sections:
            self.assertGreaterEqual(section["framesSent"], 40, "every stress frame was sent first")
            self.assertFalse(section["passed"])
            self.assertFalse(section["errors"] or section["released"] or section["artErrors"])
        self.assertFalse(report.gates["stressUntouched"] or report.gates["stressTurn"])
        self.assertTrue(report.gates["unattendedSoak"] and report.gates["turningDetected"])
        return sections

    def test_a_refused_upload_late_in_each_stress_pass_fails_both_stress_gates(self):
        firmware = self.LateStressFailure("error")
        for section in self.stress_failure(firmware):
            self.assertEqual({ack["error"] for _, ack in section["mediaErrors"]}, {"Media unavailable"})
            self.assertEqual(section["committed"], section["transfers"] - 1)
        self.assertEqual(firmware.after, {False: 0, True: 0}, "each pass stops at its refused cover")

    def test_an_uncommitted_upload_without_a_media_error_fails_both_stress_gates(self):
        firmware = self.LateStressFailure("short", op="commit")
        for section in self.stress_failure(firmware):
            self.assertEqual(section["mediaErrors"], [])
            self.assertEqual(section["committed"], section["transfers"] - 1)
        self.assertEqual(firmware.after, {False: 0, True: 0}, "each pass stops at its uncommitted cover")

    def test_a_stray_media_error_in_each_stress_pass_fails_both_stress_gates(self):
        for section in self.stress_failure(self.LateStressFailure("stray")):
            self.assertEqual([ack for _, ack in section["mediaErrors"]], [{"op": "parse", "error": "parse"}])
            self.assertEqual(section["committed"], section["transfers"])


@needs_tooling
class PackageSupersedeTests(unittest.TestCase):
    """package_nanod_cc5.py marks earlier cc5 releases SUPERSEDED and never overwrites their files.

    The scenarios are the cc5.3 packaging (cc5.2 installed), pinned to cc5.3; Cc54PackageTests packages
    cc5.4 over the installed cc5.3."""
    pinned = "cc5.3"

    def setUp(self):
        if self.pinned:
            pin_current(self.enterContext, self.pinned)
        self.module = load_script("package_nanod_cc5.py")
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(t, "FIRMWARE_OUT", self.folder))
        self.enterContext(mock.patch.object(t, "ACTIVE_MANIFEST", self.folder / "manifest.json"))
        self.old = self.folder / "manifest-1.0.0-cc5.json"
        self.image = self.folder / "nanod-control-center-1.0.0-cc5.bin"
        self.image.write_bytes(b"\xe9 old cc5 image")

    def test_an_unflashed_earlier_release_is_marked_superseded_once(self):
        self.old.write_text(json.dumps({"firmwareVersion": "1.0.0-cc5", "installationStatus": "UNFLASHED",
                                        "sourceFiles": {"src/a.cpp": {"sha256": "1"}, "src/b.cpp": {"sha256": "2"}}}),
                            encoding="utf-8")
        original = self.old.read_bytes()
        [line] = self.module.supersede_earlier_releases()
        self.assertIn("UNFLASHED -> SUPERSEDED", line)
        record = t.load_json(self.old)
        self.assertEqual((record["installationStatus"], record["statusBeforeSupersede"], record["supersededBy"]),
                         ("SUPERSEDED", "UNFLASHED", t.CC5_VERSION))
        self.assertIn("NOT turned", record["history"])
        [kept] = self.folder.glob("manifest-1.0.0-cc5.superseded-*.json")
        self.assertEqual(kept.read_bytes(), original)                       # the previous file is kept
        self.assertEqual(self.image.read_bytes(), b"\xe9 old cc5 image")    # images are never touched
        self.assertEqual(self.module.supersede_earlier_releases(), [])     # idempotent
        changes = self.module.previous_release_changes({"src/a.cpp": {"sha256": "1"}, "src/b.cpp": {"sha256": "9"},
                                                        "src/c.cpp": {"sha256": "3"}})
        self.assertEqual((changes["from"], changes["added"], changes["modified"], changes["removed"]),
                         ("1.0.0-cc5", ["src/c.cpp"], ["src/b.cpp"], []))

    def test_an_installed_earlier_release_is_left_alone(self):
        self.old.write_text(json.dumps({"installationStatus": "INSTALLED"}), encoding="utf-8")
        before = self.old.read_bytes()
        [line] = self.module.supersede_earlier_releases()
        self.assertIn("INSTALLED; not marked SUPERSEDED", line)
        self.assertEqual(self.old.read_bytes(), before)
        self.assertEqual(list(self.folder.glob("*.superseded-*")), [])

    def test_nothing_to_supersede(self):
        self.assertEqual(self.module.supersede_earlier_releases(), [])
        self.assertIsNone(self.module.previous_release_changes({}))

    def test_the_cc5_3_gate_evidence_includes_the_led_hue_report(self):
        """The LED hue report keeps its cc5 name (tests/tools/led_hue_report.py); the cc5.3 manifest records
        it with the cc5.3 gate files, never the cc5.2-era stage evidence or superseded copies."""
        self.enterContext(mock.patch.object(t, "DIAGNOSTICS", self.folder))
        for name in ("cc5-led-hue-report.json", "cc5.3-stage9-gates.json", "cc5.3-build.json", "cc5.3-media-report.json",
                     "cc5-stage9-cc5.3-gates.log", "cc5-stage9-cc5.2-prebuild-gates.log", "cc5-stage0.json",
                     "cc5-build.json", "cc5-flash-report.json", "cc5.3-stage9-gates.superseded-20260924T000000Z.json"):
            (self.folder / name).write_text("{}", encoding="utf-8")
        found = {name.split("/", 1)[1] for name in self.module.gates(t.PROFILES["cc5.3"]) if name.startswith("diagnostics/")}
        self.assertEqual(found, {"cc5-led-hue-report.json", "cc5.3-stage9-gates.json", "cc5.3-build.json",
                                 "cc5.3-media-report.json", "cc5-stage9-cc5.3-gates.log"})
        cc52 = {name.split("/", 1)[1] for name in self.module.gates(t.PROFILES["cc5.2"]) if name.startswith("diagnostics/")}
        self.assertIn("cc5-led-hue-report.json", cc52)

    def test_cc5_1_is_superseded_with_its_hang_history(self):
        """1.0.0-cc5.1 (flashed, HMI hang, rolled back; its manifest stayed UNFLASHED) becomes history."""
        cc51 = self.folder / "manifest-1.0.0-cc5.1.json"
        cc51.write_text(json.dumps({"firmwareVersion": "1.0.0-cc5.1", "installationStatus": "UNFLASHED",
                                    "sourceFiles": {"src/a.cpp": {"sha256": "1"}}}), encoding="utf-8")
        original = cc51.read_bytes()
        [line] = self.module.supersede_earlier_releases()
        self.assertIn("manifest-1.0.0-cc5.1.json: UNFLASHED -> SUPERSEDED", line)
        record = t.load_json(cc51)
        self.assertEqual((record["installationStatus"], record["supersededBy"]), ("SUPERSEDED", t.CC5_VERSION))
        self.assertIn("hung inside FastLED.show()", record["history"])
        [kept] = self.folder.glob("manifest-1.0.0-cc5.1.superseded-*.json")
        self.assertEqual(kept.read_bytes(), original)
        changes = self.module.previous_release_changes({"src/a.cpp": {"sha256": "2"}})
        self.assertEqual((changes["from"], changes["modified"]), ("1.0.0-cc5.1", ["src/a.cpp"]))
        self.assertIn("1.0.0-cc5.3 adds artwork2 on 1.0.0-cc5.2", changes["summary"])

    def installed_cc5_2(self):
        """firmware/ as it is before the cc5.3 packaging: cc5.2 INSTALLED, manifest.json its byte copy."""
        record = {"firmwareVersion": "1.0.0-cc5.2", "installationStatus": "INSTALLED",
                  "artifacts": {t.CURRENT.from_image.name: {"sha256": t.CURRENT.from_image_sha256}},
                  "sourceFiles": {"src/a.cpp": {"sha256": "1"}}, "installation": {"date": "2026-09-23"}}
        path = self.folder / "manifest-1.0.0-cc5.2.json"
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        shutil.copyfile(path, self.folder / "manifest.json")
        return path, path.read_bytes()

    def test_packaging_never_supersedes_the_installed_cc5_2_manifest(self):
        """Packaging runs before any cc5.3 write: the installed cc5.2 release manifest stays INSTALLED
        (so an aborted or rolled-back cc5.3 leaves the cc5.2 records as they were), with or without
        its kept record. finalize_nanod_cc5.py supersedes it once cc5.3 is recorded as installed."""
        path, original = self.installed_cc5_2()
        left = ["manifest-1.0.0-cc5.2.json is INSTALLED; not marked SUPERSEDED (finalize_nanod_cc5.py does that once "
                          f"{t.CC5_VERSION} is recorded as installed)"]
        self.assertEqual(self.module.supersede_earlier_releases(), left)                       # no record kept yet
        self.assertEqual(path.read_bytes(), original)
        line = self.module.keep_from_record()
        self.assertIn("manifest-cc5.2.json written: byte copy of manifest.json", line)
        self.assertEqual((self.folder / "manifest-cc5.2.json").read_bytes(), original)
        self.assertIn("kept", self.module.keep_from_record())                                  # idempotent
        self.assertEqual(self.module.supersede_earlier_releases(), left)                       # record kept: still left
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.folder.glob("*.superseded-*")), [])
        self.assertEqual((self.folder / "manifest.json").read_bytes(), original)              # manifest.json untouched
        self.assertEqual((self.folder / "manifest-cc5.2.json").read_bytes(), original)

    def test_an_installed_cc5_2_manifest_that_is_not_the_kept_record_stays_installed(self):
        """manifest-cc5.2.json holds manifest.json's bytes, but the INSTALLED release manifest differs from
        them: it is not the record that was kept, so it is never marked SUPERSEDED."""
        path, original = self.installed_cc5_2()
        self.module.keep_from_record()
        self.assertEqual((self.folder / "manifest-cc5.2.json").read_bytes(), original)
        changed = original.replace(b"2026-09-23", b"2026-09-22")
        path.write_bytes(changed)
        self.assertEqual(t.load_json(path)["installationStatus"], "INSTALLED")
        self.assertEqual(self.module.supersede_earlier_releases(),
                         ["manifest-1.0.0-cc5.2.json is INSTALLED; not marked SUPERSEDED (finalize_nanod_cc5.py does that once "
                          f"{t.CC5_VERSION} is recorded as installed)"])
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual(list(self.folder.glob("*.superseded-*")), [])
        self.assertEqual((self.folder / "manifest.json").read_bytes(), original)

    def test_the_from_record_is_never_guessed(self):
        path, original = self.installed_cc5_2()
        (self.folder / "manifest.json").write_text(json.dumps({"firmwareVersion": t.CC4_VERSION,
                                                               "installationStatus": "INSTALLED"}), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.module.keep_from_record()
        self.assertIn("manifest.json is not the INSTALLED 1.0.0-cc5.2 record", str(caught.exception))
        self.assertFalse((self.folder / "manifest-cc5.2.json").exists())
        shutil.copyfile(path, self.folder / "manifest.json")
        (self.folder / "manifest-cc5.2.json").write_bytes(original.replace(b"2026-09-23", b"2026-09-24"))
        with self.assertRaises(SystemExit) as caught:
            self.module.keep_from_record()
        self.assertIn("differs from manifest.json", str(caught.exception))

    def test_repackaging_the_release_keeps_the_previous_package(self):
        """Packaging the same release again (after a fix) archives its manifest and source archive
        (and a different image) before writing, instead of overwriting them; manifest.json is checked
        unchanged at the end."""
        source = (WORK / "package_nanod_cc5.py").read_text(encoding="utf-8")
        main = source[source.index("def main("):]
        keep = main.index("for path in (p.source_zip, p.manifest):")
        self.assertLess(main.index("if p.image.is_file() and t.sha256_file(p.image) != build[\"sha256\"]:"), keep)
        self.assertLess(main.index("from_line = keep_from_record(p)"), keep)
        self.assertLess(keep, main.index("p.image.write_bytes(image)"))
        self.assertLess(keep, main.index("zipfile.ZipFile(p.source_zip, \"w\""))
        self.assertLess(keep, main.index("p.manifest.write_text("))
        self.assertLess(main.index("p.manifest.write_text("), main.index("superseded = supersede_earlier_releases(p)"))
        self.assertLess(main.index("superseded = supersede_earlier_releases(p)"), main.index("if active_after != active_before:"))
        self.assertIn("previousPackagingKept=kept,", main)
        self.assertIn("expectedCapabilities=p.expected_capabilities(),", main)


@needs_tooling
class Cc54PackageTests(unittest.TestCase):
    """package_nanod_cc5.py for CURRENT (1.0.0-cc5.4 over the installed cc5.3): the cc5.3 record is kept
    byte-exact as manifest-cc5.3.json and its release manifest stays INSTALLED until finalize."""

    def setUp(self):
        self.module = load_script("package_nanod_cc5.py")
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(t, "FIRMWARE_OUT", self.folder))
        self.enterContext(mock.patch.object(t, "ACTIVE_MANIFEST", self.folder / "manifest.json"))

    def installed_cc5_3(self):
        record = {"firmwareVersion": "1.0.0-cc5.3", "installationStatus": "INSTALLED",
                  "artifacts": {t.CURRENT.from_image.name: {"sha256": t.CURRENT.from_image_sha256}},
                  "sourceFiles": {"src/a.cpp": {"sha256": "1"}}, "installation": {"date": "2026-09-24"}}
        path = self.folder / "manifest-1.0.0-cc5.3.json"
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        shutil.copyfile(path, self.folder / "manifest.json")
        return path, path.read_bytes()

    def test_packaging_cc5_4_keeps_the_installed_cc5_3_record(self):
        path, original = self.installed_cc5_3()
        left = ["manifest-1.0.0-cc5.3.json is INSTALLED; not marked SUPERSEDED (finalize_nanod_cc5.py does that once "
                "1.0.0-cc5.4 is recorded as installed)"]
        self.assertEqual(self.module.supersede_earlier_releases(), left)
        self.assertIn("manifest-cc5.3.json written: byte copy of manifest.json", self.module.keep_from_record())
        self.assertEqual((self.folder / "manifest-cc5.3.json").read_bytes(), original)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((self.folder / "manifest.json").read_bytes(), original)

    def test_the_cc5_4_summary_and_compatibility(self):
        self.assertIn("1.0.0-cc5.4 (Warm alive) on 1.0.0-cc5.3", self.module.RELEASE_SUMMARIES[t.CC5_VERSION])
        self.assertEqual(self.module.RELEASE_SUMMARY, self.module.RELEASE_SUMMARIES["1.0.0-cc5.4"])
        self.assertIn("1.0.0-cc5.3 adds artwork2 on 1.0.0-cc5.2", self.module.RELEASE_SUMMARIES["1.0.0-cc5.3"])
        compat = self.module.COMPATIBILITY["1.0.0-cc5.4"]
        for phrase in ("presentation 5", "presentation-4 frames", "Desktop v6 on cc5.4"):
            self.assertIn(phrase, compat)
        cc53 = self.folder / "manifest-1.0.0-cc5.3.json"
        cc53.write_text(json.dumps({"firmwareVersion": "1.0.0-cc5.3", "installationStatus": "SUPERSEDED",
                                    "sourceFiles": {"src/a.cpp": {"sha256": "1"}}}), encoding="utf-8")
        changed = self.module.previous_release_changes({"src/a.cpp": {"sha256": "2"}})
        self.assertEqual((changed["from"], changed["modified"]), ("1.0.0-cc5.3", ["src/a.cpp"]))
        self.assertIn("1.0.0-cc5.4 (Warm alive)", changed["summary"])


@needs_tooling
class RebootWatchTests(unittest.TestCase):
    """check_nanod_cc5.RebootWatch with fake diag, PnP and port watch (nothing is opened)."""

    def setUp(self):
        self.module = load_check_script()
        self.report, self.ports = FakeWatchReport(), FakePortWatch()
        self.arrival = ["2026-09-23T16:00:00Z"]
        self.diags, self.polls = [boot_diag(uptime=1000)], []
        self.out = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))

    def watch(self):
        def probe(device):
            return self.diags.pop(0)

        def poll(predicate, timeout, **kwargs):
            self.polls.append(timeout)
            return "FAKEAPP2", []
        return self.module.RebootWatch(self.report, "FAKEAPP", arrival=lambda: self.arrival[0],
                                       port_watch=self.ports, probe=probe, poll=poll)

    def failures(self):
        return [name for name, ok, _ in self.report.results if not ok]

    def test_a_clean_run_passes_every_checkpoint(self):
        watch = self.watch()
        watch.start()
        self.assertEqual(self.report.gates, {"rebootFieldsReported": True, "coredumpBlank": True, "rxQueueInternal": True})
        self.assertTrue(watch.checkpoint("fourControls"))
        self.assertTrue(watch.checkpoint("legacyV2Frames", boot_diag(uptime=2000)))
        self.diags.append(boot_diag(uptime=3000))
        watch.finish()
        self.assertEqual(self.failures(), [])
        self.assertTrue(self.report.gates["noRebootOrReenumeration"])
        self.assertTrue(self.report.gates["taskLiveness"])
        self.assertEqual(watch.live["checked"], 3)          # start, legacyV2Frames, end (fourControls has no diag)
        self.assertEqual([e["after"] for e in watch.data["timeline"]], ["start", "fourControls", "legacyV2Frames", "end"])
        self.assertEqual(watch.data["timeline"][0]["liveness"]["hmiAgeMs"], 4)
        self.assertEqual(self.polls, [])                     # nothing to recover
        self.assertTrue(self.ports.started and self.ports.stopped)

    def test_after_a_step_down_only_the_inherited_core_dump_passes(self):
        """TB-D9 (review TOOLBC-1): a binary installed from a step-down base starts with the failed binary's dump;
        coredumpBlank accepts exactly that one (same size, no crash reset) and records it, and nothing else."""
        inherited = {"base": "nanod-cc5.3-step-down-base-X.bin", "partitionOffset": 0x3F0000, "bytes": 11852,
                     "partitionSha256": "d" * 64}
        dump = {"blank": False, "present": True, "status": "ESP_OK", "bytes": 11852}
        for diag, passed in ((boot_diag(uptime=1000, coredump=dump), True),
                             (boot_diag(uptime=1000), True),
                             (boot_diag(uptime=1000, reason="panic", coredump=dump), False),
                             (boot_diag(uptime=1000, coredump={**dump, "bytes": 4096}), False)):
            with self.subTest(diag["resetReason"], bytes=diag["coredump"]["bytes"]):
                self.report = FakeWatchReport()
                self.diags = [diag]
                watch = self.watch()
                watch.inherited_coredump = inherited
                watch.start()
                self.assertEqual(self.report.gates["coredumpBlank"], passed)
                name, ok, detail = next(r for r in self.report.results if r[0].startswith("no core dump stored"))
                self.assertEqual(name, "no core dump stored in flash (coredump partition blank), or only the failed "
                                       "binary's dump its step-down base holds")
                kept = passed and diag["coredump"]["present"]
                self.assertEqual(self.report.data["coredumpInherited"], inherited if kept else None)
                if kept:
                    self.assertEqual(detail["inheritedFromStepDownBase"], inherited)
        self.report = FakeWatchReport()                                          # no step-down: strict as before
        self.diags = [boot_diag(uptime=1000, coredump=dump)]
        self.watch().start()
        self.assertFalse(self.report.gates["coredumpBlank"])
        self.assertIn("no core dump stored in flash (coredump partition blank)", self.failures())
        source = (WORK / "check_nanod_cc5.py").read_text(encoding="utf-8")
        self.assertIn("inherited_coredump=t.step_down_coredump(profile, args.binary) if args.binary else None", source)

    def test_every_diag_checkpoint_is_a_liveness_checkpoint(self):
        """1.0.0-cc5.1's hang passed every reboot check; its HMI age would have failed here."""
        watch = self.watch()
        watch.start()
        self.assertTrue(watch.checkpoint("legacyV2Frames", boot_diag(uptime=2000)))
        self.assertFalse(watch.checkpoint("stress", boot_diag(uptime=3000, hmiAgeMs=24000, hmiStep="show")))
        self.assertIn("!!! TASK STALL, LED TRANSMIT FAILURE OR FORCED RELEASE (after stress)", self.out.getvalue())
        self.assertIn("TASK STALLED: hmiAgeMs 24000 ms > 1000 ms at step 'show'", self.out.getvalue())
        self.diags.append(boot_diag(uptime=4000))
        watch.finish()
        self.assertEqual(self.failures(), [f"{self.module.LIVENESS_CHECK}: stress"])
        self.assertTrue(self.report.gates["noRebootOrReenumeration"])
        self.assertFalse(self.report.gates["taskLiveness"])
        self.assertEqual(watch.live["failures"][0]["after"], "stress")
        self.assertEqual(watch.live["failures"][0]["diag"]["hmiStep"], "show")

    def test_quiet_checkpoints_record_healthy_replies_and_report_failures(self):
        watch = self.watch()
        watch.start()
        before = len(self.report.results)
        self.assertTrue(watch.checkpoint("soak 1", boot_diag(uptime=2000), pnp=False, quiet=True))
        self.assertEqual(len(self.report.results), before)                          # no check line
        self.assertEqual(watch.data["timeline"][-1]["after"], "soak 1")
        self.assertFalse(watch.checkpoint("soak 2", boot_diag(uptime=3000, forcedReleases=1, lastForced=["lcd"]),
                                          pnp=False, quiet=True))
        self.assertEqual([n for n, ok, _ in self.report.results[before:]], [f"{self.module.LIVENESS_CHECK}: soak 2"])
        self.assertFalse(watch.checkpoint("soak 3", boot_diag(boot=4, uptime=10), pnp=False, quiet=True))
        self.assertIn("no reboot or USB re-enumeration: soak 3", self.failures())

    def test_the_start_diag_must_report_liveness(self):
        self.diags = [{k: v for k, v in boot_diag(uptime=1000).items() if k not in HEALTHY_LIVENESS}]
        self.watch().start()
        self.assertIn(f"{self.module.LIVENESS_CHECK}: start", self.failures())

    def test_a_reboot_fails_loudly_and_records_the_reset_reason(self):
        watch = self.watch()
        watch.start()
        self.assertFalse(watch.checkpoint("stress", boot_diag(boot=4, uptime=1200, reason="brownout")))
        self.assertIn("!!! REBOOT OR USB RE-ENUMERATION DETECTED (after stress)", self.out.getvalue())
        after = boot_diag(boot=4, uptime=5000, reason="brownout",
                          previous={"uptimeMs": 81234, "com": {"op": "art-data", "stage": "line"}})
        self.diags.append(after)
        watch.finish()
        self.assertFalse(self.report.gates["noRebootOrReenumeration"])
        self.assertEqual(self.polls, [20.0])
        self.assertEqual(watch.data["postDropDiag"]["diag"], after)
        names = self.failures()
        self.assertIn("no reboot or USB re-enumeration: stress", names)
        self.assertTrue(any(n.startswith("after the drop: the knob reset; reset reason recorded") for n in names))
        self.assertIn("!!! The knob RESET. Reset reason: brownout", self.out.getvalue())
        detail = next(d for n, ok, d in self.report.results if n.startswith("after the drop"))
        self.assertEqual(detail["resetReason"], "brownout")
        self.assertEqual(detail["previous"]["com"]["op"], "art-data")

    def test_uptime_going_back_and_windows_side_signals_count(self):
        watch = self.watch()
        watch.start()
        self.assertFalse(watch.checkpoint("a", boot_diag(uptime=10)))           # uptime went back
        self.arrival[0] = "2026-09-23T16:16:37Z"
        self.assertFalse(watch.checkpoint("bridgeArtwork"))                     # PnP arrival changed
        self.arrival[0] = "2026-09-23T16:00:00Z"
        watch.arrival = self.arrival[0]
        self.ports.pending = [{"from": 12.4, "seconds": 0.6}]
        self.assertFalse(watch.checkpoint("fourControls"))                      # port gone briefly
        self.assertEqual(len(watch.data["detected"]), 3)

    def test_pnp_is_skipped_on_request(self):
        watch = self.watch()
        watch.start()
        self.arrival[0] = "changed, but not read"
        self.assertTrue(watch.checkpoint("stress", boot_diag(uptime=2000), pnp=False))
        self.assertFalse(watch.checkpoint("DeviceBridge part", boot_diag(uptime=3000)))

    def test_a_port_error_is_treated_as_a_drop(self):
        watch = self.watch()
        watch.start()
        self.diags.append(boot_diag(boot=4, uptime=700, reason="int_wdt"))
        watch.finish(OSError("Write timeout"))
        self.assertFalse(self.report.gates["noRebootOrReenumeration"])
        self.assertEqual(watch.data["postDropDiag"]["diag"]["resetReason"], "int_wdt")

    def test_a_port_error_without_a_reset_is_still_a_failed_gate(self):
        watch = self.watch()
        watch.start()
        self.diags.append(boot_diag(uptime=9000))              # same bootCount, later uptime
        watch.finish(OSError("Write timeout"))
        self.assertFalse(self.report.gates["noRebootOrReenumeration"])
        self.assertEqual(watch.data["postDropDiag"]["rebootProblems"], [])
        self.assertIn("did not reset", self.out.getvalue())
        self.assertEqual(self.failures(), [])                   # the run's own exception check fails it

    def test_start_flags_a_stored_core_dump_and_a_psram_queue(self):
        self.diags = [boot_diag(rxQueue="psram", coredump={"blank": False, "present": True, "status": "ESP_OK",
                                                           "bytes": 9000})]
        self.module.RebootWatch.start(self.watch())
        self.assertEqual(self.report.gates, {"rebootFieldsReported": True, "coredumpBlank": False, "rxQueueInternal": False})
        self.assertIn("no core dump stored in flash (coredump partition blank)", self.failures())

    def test_the_script_runs_both_stress_passes_and_names_its_gates(self):
        source = (WORK / "check_nanod_cc5.py").read_text(encoding="utf-8")
        self.assertIn('report.section("stress")', source)
        self.assertIn('report.section("stressTurn")', source)
        self.assertIn('Turn the knob continuously now for {args.turn_seconds:.0f} s', source)
        self.assertLess(source.index('report.section("coldTransferTiming")'), source.index('report.section("stress")'))
        self.assertLess(source.index('report.section("stress")'), source.index('report.section("stressTurn")'))
        # 1.0.0-cc5.2: the unattended soak runs after stress+turn and before the final diag margins.
        self.assertLess(source.index('report.section("stressTurn")'), source.index('report.section("soak")'))
        self.assertLess(source.index('report.section("soak")'), source.index('report.section("diag")'))
        self.assertIn('parser.add_argument("--soak-minutes", type=float, default=t.SOAK_DEFAULT_MINUTES,', source)
        soak = source[source.index("def run_soak("):source.index("def raw_checks(")]
        self.assertNotIn("audible_cue", soak)                                  # no audible cue in the soak
        self.assertIn("audible_cue", source[source.index('report.section("stressTurn")'):
                                            source.index('report.section("soak")')])
        self.assertIn("GATES = t.CURRENT.gates", source)            # the profile's gates, never a copied list
        self.assertEqual(self.module.REPLAY_TRANSFERS, 3)
        finalize = load_script("finalize_nanod_cc5.py")
        self.assertEqual(set(self.module.GATES), set(finalize.REQUIRED_GATES))
        # 1.0.0-cc5.3: the artwork2 gates are recorded and required, and match the profile.
        self.assertEqual(tuple(self.module.GATES), t.CURRENT.gates)
        self.assertEqual(tuple(finalize.REQUIRED_GATES), t.CURRENT.gates)
        # The artwork2 sections run after the v1 art cases and before the cc5.2 run-1 sequence.
        order = [source.index(f'report.section("{name}")') for name in
                 ("rawArtwork", "mediaRoundTrip", "mediaPrefetch", "mediaPinning", "mediaErrors", "mediaTiming",
                  "coldTransferTiming", "stress")]
        self.assertEqual(order, sorted(order))
        # The audible cues are unchanged: opt-in, only around stress+turn.
        # The definition, its three stress+turn calls and the 1.0.0-cc5.4 hands-on wrapper cue().
        self.assertEqual(source.count("audible_cue("), 5)
        self.assertEqual(source.count("def cue("), 1)
        self.assertIn('if os.environ.get("NANOD_AUDIBLE_CUES") != "1":', source)
        # Every raw section is followed by a diag checkpoint.
        tree = ast.parse(source)
        raw = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "raw_checks")
        sections = [ast.unparse(w.items[0].context_expr) for w in ast.walk(raw) if isinstance(w, ast.With)]
        checkpoints = [ast.unparse(c) for c in ast.walk(raw) if isinstance(c, ast.Call)
                       and getattr(c.func, "attr", "") == "checkpoint"]
        # A checkpoint's diag is read right there, or just before it into a variable (1.0.0-cc5.4 also
        # checks ledRenderUsMax of the stress passes on that same read).
        read_first = {n.targets[0].id for n in ast.walk(raw) if isinstance(n, ast.Assign) and len(n.targets) == 1
                      and isinstance(n.targets[0], ast.Name) and ast.unparse(n.value) == "knob.diag()"}
        for call in sections:
            name = re.search(r"section\('(\w+)'\)", call).group(1)
            self.assertTrue(any(f"'{name}'" in c and ("knob.diag()" in c or any(v in c for v in read_first))
                                for c in checkpoints), name)


def assert_quit_block_names_the_companions(case, text):
    """A quit block run before a flash disables the startup task before it checks the process, and checks the
    old companion's task and image. Once it names Desk Dial (the rename, rename-desk-dial.md 11.1 / 11.12) it
    must check both images, DeskDial and NanoDControlCenter, in one Get-Process line or two."""
    case.assertIn("Disable-ScheduledTask", text)
    case.assertIn("NanoD Control Center", text)
    case.assertRegex(text, r"\.State -ne 'Disabled'")
    process = [line for line in text.splitlines() if "Get-Process -Name" in line]
    case.assertTrue(process and any("NanoDControlCenter" in line for line in process), text)
    case.assertLess(text.index("Disable-ScheduledTask"), text.index("Get-Process -Name"))
    if "DeskDial" in text or "Desk Dial" in text:
        case.assertTrue(any("DeskDial" in line for line in process), "a Desk Dial quit block must check DeskDial too")


@needs_tooling
class ScriptStaticTests(unittest.TestCase):
    """The hardware-window scripts are parsed, never executed."""

    def source(self, name):
        return (WORK / name).read_text(encoding="utf-8")

    def tree(self, name):
        return ast.parse(self.source(name), filename=name)

    def test_scripts_parse_with_guarded_mains_and_no_port_literals(self):
        for name in (*SCRIPTS, "nanod_cc5_tooling.py"):
            source = self.source(name)
            compile(source, name, "exec")
            self.assertIsNone(re.search(r"\bCOM\d+\b", source), name)
            if name in SCRIPTS:
                self.assertIn('if __name__ == "__main__":', source, name)

    def test_no_hardware_module_is_imported_at_module_level(self):
        for name in (*SCRIPTS, "nanod_cc5_tooling.py"):
            for node in self.tree(name).body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    self.assertFalse(any(m.split(".")[0] in ("serial", "esptool") for m in modules), (name, modules))

    def test_flashing_scripts_never_erase_and_check_the_environment_first(self):
        for name in FLASHING:
            tree = self.tree(name)
            docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                          if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(n)}
            strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and id(n) not in docstrings]
            self.assertFalse([s for s in strings if "erase" in s.lower() or s in ("merge_bin", "-e")], name)
            main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
            calls = [(c.lineno, getattr(c.func, "attr", getattr(c.func, "id", ""))) for c in ast.walk(main)
                     if isinstance(c, ast.Call)]
            guard = min(line for line, fn in calls if fn == "assert_flash_environment")
            device = [line for line, fn in calls if fn in ("find_rom_port", "Esptool", "device_rollback", "verify_inputs")]
            self.assertTrue(device and guard < min(device), name)

    def test_install_writes_only_app0_with_keep_flags_and_resets_last(self):
        source = self.source("install_nanod_cc5.py")
        self.assertIn('WRITE_ARGS = ["write_flash", "--flash_mode", "keep", "--flash_freq", "keep", "--flash_size", "keep"]', source)
        self.assertEqual(source.count('after="hard_reset"'), 2)  # after the verified install, or after a verified restore
        self.assertLess(source.index('"after-verify"'), source.index('esptool("reset"'))

    def test_check_scripts_always_release_in_finally(self):
        for name in ("check_nanod_cc5.py", "check_nanod_cc5_lease.py"):
            finals = [ast.unparse(stmt) for node in ast.walk(self.tree(name)) if isinstance(node, ast.Try)
                      for stmt in node.finalbody]
            self.assertTrue(any("knob.release_quietly()" in s for s in finals), name)
            self.assertFalse(any("control_id" in s for s in finals), name)  # unconditional

    def test_finalize_checks_everything_before_recording(self):
        main = next(n for n in self.tree("finalize_nanod_cc5.py").body if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = [(c.lineno, getattr(c.func, "attr", getattr(c.func, "id", ""))) for c in ast.walk(main)
                 if isinstance(c, ast.Call)]
        writes = [line for line, fn in calls if fn in ("write_json_evidence", "write_text", "copyfile")]
        requires = [line for line, fn in calls if fn == "require"]
        self.assertTrue(writes and requires)
        self.assertLess(max(requires), min(writes))

    SECTION6 = "## 6. cc5.3 -> cc5.2 rollback"

    def recovery_blocks(self, heading, end, count, within=None):
        """The stripped lines of each PowerShell block in RECOVERY.md between two headings
        (searched from `within`, a section heading, when given)."""
        text = (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8")
        if within:
            text = text[text.index(within):]
        section = text[text.index(heading):text.index(end)]
        blocks = re.findall(r"```powershell\n(.*?)```", section, re.S)
        self.assertEqual(len(blocks), count, heading)
        return [[line.strip() for line in block.strip().splitlines()] for block in blocks]

    def manual_rollback_blocks(self):
        self.assertIn('.casefold() == "nano_d"', (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8"))
        return self.recovery_blocks("### Firmware, manual esptool fallback", "### Leave the bootloader without writing", 4)

    def test_recovery_manual_rollback_stops_on_failure_and_resets_last(self):
        blocks = self.manual_rollback_blocks()
        for lines in blocks:
            self.assertEqual((lines[0], lines[-1]), (". {", "}"))  # one unit: the first throw stops the block
            for i, line in enumerate(lines):
                if "-m esptool" in line or "rollback_nanod_cc5.py" in line or line.startswith("'@ | & $flashPython"):
                    self.assertRegex(lines[i + 1], r"^if \(\$LASTEXITCODE -ne 0\) \{ throw ", line)
        checks, write, regions, reset = ("\n".join(lines) for lines in blocks)
        self.assertIn("read_flash 0x8000 0x1000", checks)
        self.assertIn("read_flash 0xE000 0x2000", checks)
        self.assertIn("if ($current -ne $saved) { throw", checks)
        self.assertIn('"bootloader": (0x0, 0x8000), "partition-table": (0x8000, 0x1000)', checks)
        self.assertIn('"otadata": (0xE000, 0x2000), "app0": (0x10000, 0x140000), "app1": (0x150000, 0x140000)', checks)
        self.assertIn("(0x303A,0x1001)", checks)
        self.assertIn("'123456789abc'", checks)
        self.assertNotIn("write_flash", checks + regions + reset)
        self.assertEqual(write.count("--baud 460800 --before no_reset --after no_reset_stub write_flash --flash_mode keep "
                                     "--flash_freq keep --flash_size keep 0x10000 $rollbackApp"), 1)
        self.assertIn("verify_flash 0x10000 $rollbackApp", write)
        self.assertIn("verify_flash 0x0 $backupFull", write)
        for offset in ("'0x0'", "'0x8000'", "'0xE000'", "'0x10000'", "'0x150000'"):
            self.assertIn(offset, regions)
        self.assertEqual([b for b in (checks, write, regions, reset) if "hard_reset" in b], [reset])
        self.assertEqual([b for b in (checks, write, regions, reset) if "--records-only" in b], [reset])
        for block in (checks, write, regions):
            self.assertEqual(block.count("--before no_reset --after no_reset_stub"), block.count("-m esptool"), block[:40])
        self.assertIn("--before no_reset --after hard_reset read_mac", reset)
        self.assertTrue(blocks[3][1].startswith("if (-not $rollbackVerified) { throw"), blocks[3][1])
        self.assertTrue(blocks[1][1].startswith("if (-not $layoutVerified) { throw"), blocks[1][1])
        self.assertTrue(blocks[2][1].startswith("if (-not $app0Verified) { throw"), blocks[2][1])

    def test_recovery_interlocks_are_cleared_before_any_esptool_command(self):
        """A 'verified' left from an earlier run can never let block 4 reset after a failed write or verify."""
        blocks = self.manual_rollback_blocks()

        def cleared_before_esptool(lines):
            first = next(i for i, line in enumerate(lines) if "-m esptool" in line)
            return {flag for line in lines[:first] for flag in re.findall(r"\$(\w+Verified) = \$false", line)}

        checks, write, regions, reset = blocks
        self.assertEqual(cleared_before_esptool(checks), {"layoutVerified", "app0Verified", "rollbackVerified"})
        self.assertEqual(cleared_before_esptool(write), {"layoutVerified", "app0Verified", "rollbackVerified"})
        self.assertEqual(cleared_before_esptool(regions), {"rollbackVerified"})
        self.assertNotRegex("\n".join(reset), r"Verified = \$true")

        def set_true(lines, flag):
            return [i for i, line in enumerate(lines) if line == f"${flag} = $true"]

        # Each flag becomes true only after the last esptool check it vouches for, never inside a loop body.
        [layout] = set_true(checks, "layoutVerified")
        self.assertGreater(layout, max(i for i, line in enumerate(checks) if "if ($current -ne $saved)" in line))
        [app0] = set_true(write, "app0Verified")
        self.assertIn("verify_flash 0x10000 $rollbackApp", write[app0 - 2])
        self.assertRegex(write[app0 - 1], r"^if \(\$LASTEXITCODE -ne 0\) \{ throw ")
        [rollback_write] = set_true(write, "rollbackVerified")
        self.assertIn("verify_flash 0x0 $backupFull", write[rollback_write - 2])
        self.assertRegex(write[rollback_write - 1], r"^if \(\$LASTEXITCODE -ne 0\) \{ throw ")
        [rollback_regions] = set_true(regions, "rollbackVerified")
        self.assertEqual(regions[rollback_regions - 1], "}")                    # after the region loop closes
        self.assertEqual(set_true(regions, "app0Verified") + set_true(reset, "rollbackVerified"), [])

    def test_scripted_and_quit_blocks_clear_every_interlock_first(self):
        """The scripted rollback writes app0 too: after it, block 4 must not trust an earlier block 2."""
        flags = {"layoutVerified", "app0Verified", "rollbackVerified"}
        [quit_block] = self.recovery_blocks("### Quit the companion", "### Firmware, scripted", 1)
        scripted = self.recovery_blocks("### Firmware, scripted", "### Firmware, manual esptool fallback", 2)[0]
        for lines in (quit_block, scripted):
            first = next((i for i, line in enumerate(lines) if "& $flashPython" in line), len(lines))
            cleared = {flag for line in lines[:first] for flag in re.findall(r"\$(\w+Verified) = \$false", line)}
            self.assertEqual(cleared, flags, lines[1])
            self.assertNotRegex("\n".join(lines), r"Verified = \$true")
        self.assertIn("rollback_nanod_cc5.py", "\n".join(scripted))
        quit_text = "\n".join(quit_block)
        assert_quit_block_names_the_companions(self, quit_text)

    def test_block_4_verifies_app0_itself_right_before_the_reset(self):
        reset = self.manual_rollback_blocks()[3]
        text = "\n".join(reset)
        find_port = next(i for i, line in enumerate(reset) if line.startswith("$romPort = & $flashPython -c"))
        verify = next(i for i, line in enumerate(reset) if "verify_flash 0x10000 $rollbackApp" in line)
        hard_reset = next(i for i, line in enumerate(reset) if "--after hard_reset read_mac" in line)
        records = next(i for i, line in enumerate(reset) if "--records-only" in line)
        self.assertLess(0, find_port)
        self.assertLess(find_port, verify)
        self.assertLess(verify, hard_reset)
        self.assertLess(hard_reset, records)
        self.assertIn("--before no_reset --after no_reset_stub verify_flash 0x10000 $rollbackApp", reset[verify])
        self.assertRegex(reset[verify + 1], r"^if \(\$LASTEXITCODE -ne 0\) \{ throw '.*Nothing was reset")
        self.assertIn("(0x303A,0x1001)", reset[find_port])
        self.assertIn("'123456789abc'", reset[find_port])
        self.assertNotIn("write_flash", text)

    @machine_runbook
    def test_leaving_the_bootloader_verifies_app0_before_its_reset(self):
        """Neither read-only reset trusts memory: app0 must verify against the expected image first.

        RECOVERY.md's leave-the-bootloader block expects the installed cc5 image, BUILD-cc5.md's abort
        the cc4 image. A partly written app0 fails that verify, and the block throws before its reset.
        """
        [leave] = self.recovery_blocks("### Leave the bootloader without writing", "### After the rollback", 1)
        build = (ROOT / "firmware" / "BUILD-cc5.md").read_text(encoding="utf-8")
        abort_section = build[build.index("### Abort before any write"):build.index("### Firmware rollback, cc5 -> cc4")]
        [abort] = [[line.strip() for line in block.strip().splitlines()]
                   for block in re.findall(r"```powershell\n(.*?)```", abort_section, re.S)]
        # 1.0.0-cc5.3: RECOVERY.md section 6 leaves on the installed cc5.3 image, BUILD-cc5.3.md aborts on cc5.2.
        [leave6] = self.recovery_blocks("### cc5.3: Leave the bootloader without writing", "### cc5.3: After the rollback",
                                        1, within=self.SECTION6)
        build53 = (ROOT / "firmware" / "BUILD-cc5.3.md").read_text(encoding="utf-8")
        abort53 = build53[build53.index("### Abort before any write"):build53.index("### Firmware rollback, cc5.3 -> cc5.2")]
        [abort6] = [[line.strip() for line in block.strip().splitlines()]
                    for block in re.findall(r"```powershell\n(.*?)```", abort53, re.S)]
        cc53 = t.PROFILES["cc5.3"]
        for lines, image in ((leave, t.PROFILES["cc5.2"].image.name), (abort, t.CC4_IMAGE.name),
                             (leave6, cc53.image.name), (abort6, cc53.from_image.name)):
            with self.subTest(image):
                find_port = next(i for i, line in enumerate(lines) if line.startswith("$romPort = & "))
                verify = next(i for i, line in enumerate(lines) if "verify_flash 0x10000" in line)
                hard_reset = next(i for i, line in enumerate(lines) if "--after hard_reset read_mac" in line)
                self.assertLess(find_port, verify)
                self.assertLess(verify, hard_reset)
                self.assertEqual(lines[verify - 1], "$global:LASTEXITCODE = -1")
                documented = re.search(r"--before no_reset --after no_reset_stub verify_flash 0x10000 '([^']+)'$",
                                       lines[verify])
                self.assertIsNotNone(documented, lines[verify])
                self.assertEqual(Path(documented.group(1)).name, image)
                self.assertEqual(Path(documented.group(1)).parent, t.FIRMWARE_OUT)
                # The cc5 release image exists once package_nanod_cc5.py has packaged it, which is
                # before any hardware step (prepare refuses without its UNFLASHED manifest).
                if image != cc53.image.name or cc53.manifest.is_file():
                    self.assertTrue(Path(documented.group(1)).is_file(), documented.group(1))
                self.assertRegex(lines[verify + 1],
                                 r"^if \(\$LASTEXITCODE -ne 0\) \{ throw '.*Nothing was reset\. Do NOT reset")
                self.assertEqual(sum("hard_reset" in line for line in lines), 1)
                self.assertNotIn("write_flash", "\n".join(lines))

    def test_block_1_requires_esptool_4_12_0_before_anything_else(self):
        """The manual fallback never runs an esptool that rollback_nanod_cc5.py would refuse."""
        checks = self.manual_rollback_blocks()[0]
        version = next(i for i, line in enumerate(checks) if "import esptool; print(esptool.__version__)" in line)
        self.assertEqual(checks[version - 1], "$global:LASTEXITCODE = -1")
        self.assertTrue(checks[version + 1].startswith(
            f"if ($LASTEXITCODE -ne 0 -or $esptoolVersion -ne '{t.ESPTOOL_VERSION}') {{ throw "), checks[version + 1])
        first_other = next(i for i, line in enumerate(checks)
                           if "-m esptool" in line or "$romPort" in line or "Get-FileHash" in line or "@'" == line)
        self.assertLess(version, first_other)
        flags = next(i for i, line in enumerate(checks) if "$rollbackVerified = $false" in line)
        self.assertLess(flags, version)                                 # the flags are cleared even when it throws
        # The same check the script makes (nanod_cc5_tooling.assert_flash_environment).
        self.assertIn('getattr(esptool, "__version__", None)', self.source("nanod_cc5_tooling.py"))
        section = " ".join((ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8").split())
        self.assertIn("A wrong Python or esptool, a file hash or the ROM port is never a reason for the manual "
                      "blocks", section)

    def test_profile_counts_match_the_inventory_shape(self):
        """device_inventory.py (DeviceBridge) writes profiles as one JSON object, name -> profile.

        Windows PowerShell 5.1 turns that object into one PSCustomObject, so @($x.profiles).Count (or
        $x.profiles.Count) is always 1 and a check built on it is NO-GO on every run.
        """
        for doc in ("BUILD-cc5.md", "BUILD-cc5.3.md", "RECOVERY.md"):
            text = (ROOT / "firmware" / doc).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\.profiles\)?\.Count\b", text), doc)
        for doc in ("BUILD-cc5.md", "BUILD-cc5.3.md"):
            build = (ROOT / "firmware" / doc).read_text(encoding="utf-8")
            self.assertEqual(build.count("@($inventory.profiles.PSObject.Properties).Count -ne 10"), 1, doc)   # step 2
            self.assertEqual(build.count("@($after.profiles.PSObject.Properties).Count -ne 10"), 1, doc)       # step 8a
        device = (ROOT / "control_center" / "device.py").read_text(encoding="utf-8")
        self.assertIn('self.profiles[name] = deepcopy(result["profile"])', device)
        self.assertIn('"profiles": self.profiles', device)
        inventories = sorted(BACKUPS.glob("control-center-inventory-*.json"))
        if inventories:  # the newest real inventory has that shape (read only)
            profiles = json.loads(inventories[-1].read_text(encoding="utf-8"))["profiles"]
            self.assertIsInstance(profiles, dict)
            self.assertTrue(all(isinstance(p, dict) and p.get("name") == name for name, p in profiles.items()))

    NATIVE =re.compile(r"&\s+(?:\$(?:flashPython|flash|app)\b|')|^powershell\.exe ")

    def assert_exit_codes_are_armed(self, blocks, where):
        """Every native command is preceded by $global:LASTEXITCODE = -1 (a command that did not run fails)."""
        for lines in blocks:
            armed = False
            for line in lines:
                if line == "$global:LASTEXITCODE = -1":
                    armed = True
                elif self.NATIVE.search(line):
                    self.assertTrue(armed, f"{where}: {line[:90]}")
                    armed = False

    def test_recovery_sets_its_interpreter_and_arms_every_exit_code_check(self):
        blocks = (self.recovery_blocks("## 5. cc5 -> cc4 rollback", self.SECTION6, 11)
                  + self.recovery_blocks(self.SECTION6, "## Reference", 11))
        self.assert_exit_codes_are_armed(blocks, "RECOVERY.md")
        interpreter = r"$flashPython = '<repo>\tools\nanod-flash-venv\Scripts\python.exe'"
        for lines in blocks:
            if any("& $flashPython" in line for line in lines):
                first = next(i for i, line in enumerate(lines) if "& $flashPython" in line)
                self.assertIn(interpreter, lines[:first], lines[1])   # set in this block, never inherited

    @machine_runbook
    def test_build_cc5_blocks_set_their_interpreter_and_arm_every_exit_code_check(self):
        text = (ROOT / "firmware" / "BUILD-cc5.md").read_text(encoding="utf-8")
        tail = text[text.index("## Hardware window (Stage 10)"):]
        blocks = [[line.strip() for line in block.strip().splitlines()]
                  for block in re.findall(r"```powershell\n(.*?)```", tail, re.S)]
        self.assert_exit_codes_are_armed(blocks, "BUILD-cc5.md")
        for lines in blocks:
            for name in ("flash", "app", "flashPython"):
                uses = [i for i, line in enumerate(lines) if re.search(rf"&\s+\${name}\b", line)]
                if uses:
                    self.assertTrue(any(line.startswith(f"${name} = 'C:\\") for line in lines[:uses[0]]), (name, lines[1]))

    @machine_runbook
    def test_build_cc5_signals_guards_and_rollback_block(self):
        text = (ROOT / "firmware" / "BUILD-cc5.md").read_text(encoding="utf-8")
        window = text[text.index("## Hardware window (Stage 10)"):text.index("## Rollback and abort")]
        steps = re.split(r"^### Step \d+\. ", window, flags=re.M)[1:]
        self.assertEqual(len(steps), 10)
        for number, step in enumerate(steps, 1):
            for block in re.findall(r"```powershell\n(.*?)```", step, re.S):
                for message in re.findall(r"""throw ['"]([^'"]*)""", block):
                    self.assertRegex(message, r"^(?:NO-GO|NOT RUN): ", (number, message))
            self.assertRegex(step, r"(?m)^No-go|Go / no-go", number)   # every step says what a NO-GO means
        step7, step8, step9, step10 = steps[6], steps[7], steps[8], steps[9]
        block7 = re.findall(r"```powershell\n(.*?)```", step7, re.S)[0]
        self.assertRegex(block7, r"Get-Process -Name NanoDControlCenter[^\n]*throw 'NOT RUN: ")
        self.assertIn("is a `NOT RUN`, never a reason for a firmware rollback", step7)
        # A relaunched companion owns the port: every block that opens or touches it first says NOT RUN,
        # so a busy port is never reported as a NO-GO that leads to a rollback.
        guard = ("if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the "
                 "companion is running; quit it from the tray, disable the startup task again (step 1, first two "
                 "lines), then run this block again' }")
        blocks8 = [[line.strip() for line in block.strip().splitlines()]
                   for block in re.findall(r"```powershell\n(.*?)```", step8, re.S)]
        self.assertEqual(len(blocks8), 3)                              # 8a, 8b, 8c
        for lines in blocks8:
            self.assertEqual(lines[1], guard)                          # the first line inside `. {`
        for number in (2, 3):
            lines = [line.strip() for line in re.findall(r"```powershell\n(.*?)```", steps[number - 1], re.S)[0]
                     .strip().splitlines()]
            first_native = next(i for i, line in enumerate(lines) if self.NATIVE.search(line))
            self.assertIn(guard, lines[:first_native], number)
        for lines, again in ((blocks8[1], "run 8b again"), (blocks8[2], "run 8c again")):
            failure = next(line for line in lines if line.startswith("if ($LASTEXITCODE -ne 0) { throw 'NO-GO: "))
            self.assertIn("NanoDControlCenter is running, it is NOT RUN instead", failure)   # the scripts' own refusal
            self.assertIn(again, failure)
        flat8 = " ".join(step8.split())
        self.assertIn("A running companion is a `NOT RUN`, never a reason for a firmware rollback", flat8)
        self.assertIn("If you stay on cc5 without finalizing, [re-enable the companion](#re-enable-the-companion)",
                      flat8)
        blocks9 = re.findall(r"```powershell\n(.*?)```", step9, re.S)
        self.assertEqual(len(blocks9), 3)
        self.assertEqual(blocks9[1].strip().splitlines()[1].strip(),
                         "if (-not ($demo -and $dataDir -and $stamp -and $dataHashesBefore)) "
                         "{ throw 'NOT RUN: run 9a in this window first; nothing was installed' }")
        for name in ("$demo = 'C:\\", "$dataDir = Join-Path $env:LOCALAPPDATA"):
            self.assertIn(name, blocks9[2])                          # 9c needs nothing from 9a
        self.assertIn("--light-assertions 2174149", step10)
        self.assertNotIn("2,174,149", text)
        # The BUILD firmware rollback is the RECOVERY scripted block, character for character.
        rollback = text[text.index("### Firmware rollback, cc5 -> cc4"):text.index("### Desktop rollback")]
        recovery = (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8")
        scripted = recovery[recovery.index("### Firmware, scripted"):recovery.index("`nanod_enter_bootloader_v2.py` finds")]
        self.assertEqual(re.findall(r"```powershell\n(.*?)```", rollback, re.S),
                         re.findall(r"```powershell\n(.*?)```", scripted, re.S))
        # Its bootloader-step failure gives one path per cause, the companion first: a refusal because the
        # companion runs sent nothing, so it is quit and retried even when app0 is partly written.
        message = re.search(r"throw '([^']*)'", re.findall(r"```powershell\n(.*?)```", scripted, re.S)[0]).group(1)
        clauses = ("this block sent and wrote nothing",
                   "If the message above says the companion is running: quit it from the tray and run this block again",
                   "After install exit 4 or a failed rollback write, if no MAC-matched ROM port remains: stop (reset rule)",
                   "Otherwise fix the cause (section 2) and run this block again")
        order = [message.index(clause) for clause in clauses]
        self.assertEqual(order, sorted(order))

    def test_finalize_looks_for_the_traces_the_rollback_paths_leave(self):
        """Every trace either rollback path (cc5 -> cc4 and cc5.3 -> cc5.2) leaves is what finalize looks for."""
        finalize_source = self.source("finalize_nanod_cc5.py")
        finalize = load_script("finalize_nanod_cc5.py")
        recovery = (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8")
        rollback = self.source("rollback_nanod_cc5.py")
        for prefix in ("cc5", "cc5.3"):                                       # manual block 1's folders
            self.assertIn(rf"backups\{prefix}-manual-rollback-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')",
                          recovery)
        self.assertIn("p.rollback_workdir(t.utc_stamp())", rollback)          # the script's work folder
        self.assertIn("t.Esptool(port, report, p.rollback_log_prefix)", rollback)   # its logs: <prefix>-rollback-<step>.log
        self.assertIn("kept = t.unique_path(p.manifest_before_rollback(t.utc_stamp()))", rollback)
        for p in t.all_profiles():
            self.assertEqual(p.rollback_workdir("X").name, f"{p.prefix}-rollback-X")
            self.assertEqual(p.manifest_before_rollback("X").name, f"manifest-at-{p.prefix}-rollback-X.json")
        patterns = {pattern for _, pattern, _ in finalize.rollback_traces()}
        self.assertEqual(patterns, {"cc5-manual-rollback-*", "cc5-rollback-*", "cc5-rollback-*.log",
                                    "manifest-at-cc5-rollback-*.json", "cc5.3-manual-rollback-*", "cc5.3-rollback-*",
                                    "cc5.3-rollback-*.log", "manifest-at-cc5.3-rollback-*.json",
                                    # the 1.0.0-cc5.4 profile's (finalize reads every profile's traces) and
                                    # those of its binaries B and C (the 12.6 ladder)
                                    "cc5.4-manual-rollback-*", "cc5.4-rollback-*", "cc5.4-rollback-*.log",
                                    "manifest-at-cc5.4-rollback-*.json",
                                    "cc5.4-B-manual-rollback-*", "cc5.4-B-rollback-*", "cc5.4-B-rollback-*.log",
                                    "manifest-at-cc5.4-B-rollback-*.json",
                                    "cc5.4-C-manual-rollback-*", "cc5.4-C-rollback-*", "cc5.4-C-rollback-*.log",
                                    "manifest-at-cc5.4-C-rollback-*.json",
                                    # and those of the fix binaries D and E
                                    "cc5.4-D-manual-rollback-*", "cc5.4-D-rollback-*", "cc5.4-D-rollback-*.log",
                                    "manifest-at-cc5.4-D-rollback-*.json",
                                    "cc5.4-E-manual-rollback-*", "cc5.4-E-rollback-*", "cc5.4-E-rollback-*.log",
                                    "manifest-at-cc5.4-E-rollback-*.json",
                                    "nanod-current-partitions.bin"})
        self.assertIn("t.BOOT_ENTRY.stem", finalize_source)
        self.assertIn("for profile in t.all_profiles():", finalize_source)    # every profile's and binary's records
        self.assertIn(r"'.\backups\nanod-current-partitions.bin'", recovery)  # section 3's read

    @machine_runbook
    def test_recovery_section5_paths_and_commands(self):
        text = (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8")
        section = text[text.index("## 5. cc5 -> cc4 rollback"):text.index(self.SECTION6)]
        self.assert_absolute_existing_paths(section)
        self.assertIn(r"<repo>\tools\nanod-flash-venv\Scripts\python.exe", section)
        self.assertIn("-Bundle desktop-dist-v2 -Mirror", section)
        self.assertNotIn("Stop-Process -", section)
        for sentence in ("Never reset, unplug or power-cycle the knob yourself",
                         "Count every failed rollback write or verify",
                         "After the first, retry once. After the second, stop",
                         "and only after it has verified app0 once more itself",
                         "Any write outside block 2 invalidates that interlock"):
            self.assertIn(sentence, " ".join(section.split()))     # line wrapping does not matter
        # Script exit 4, block 2, block 3 and block 4's own app0 verify.
        self.assertEqual(section.count("Second: stop (retry rule)"), 4)
        for code in ("0", "1", "2", "4", "5", "6", "-1"):  # EXIT_CODES values, 1, 6 and the not-run marker
            self.assertRegex(section, rf"\n\| {code} \| ")
        # The nothing-written branch: a read-only reset, then the companion is re-enabled.
        flat = " ".join(section.split())
        self.assertIn("[leave the bootloader without writing](#leave-the-bootloader-without-writing), "
                      "[re-enable the companion](#re-enable-the-companion)", flat)
        self.assertIn("This table replaces the script's own last line", flat)

    def assert_absolute_existing_paths(self, text, pending=()):
        """Every quoted script, interpreter or program path is absolute and exists; no relative invocations.

        `pending` names path fragments built later in the release (the desktop v4 bundle): those
        paths must be absolute but may not exist yet."""
        blocks = "\n".join(re.findall(r"```powershell\n(.*?)```", text, re.S))
        paths = re.findall(r"'([A-Za-z]:\\[^']+?\.(?:py|ps1|exe))'", blocks)
        self.assertTrue(paths)
        for path in paths:
            if any(fragment in path for fragment in pending):
                continue
            self.assertTrue(Path(path).is_file(), path)
        self.assertIsNone(re.search(r"(?:^|[\s'\"])\.\.?\\", blocks, re.M), "relative path in a command")
        # What an interpreter or powershell.exe -File runs is an absolute quoted path, or a flag (-c, -m, -u, - for stdin).
        for target in re.findall(r"(?:&\s+\$(?:flash|app|flashPython)|powershell\.exe [^\n]*?-File)\s+(\S+)", blocks):
            self.assertRegex(target, r"^(?:'[A-Za-z]:\\|-[cmu]?$)", target)

    @machine_runbook
    def test_build_cc5_runbook_follows_stage_10(self):
        text = (ROOT / "firmware" / "BUILD-cc5.md").read_text(encoding="utf-8")
        self.assert_absolute_existing_paths(text)
        window = text[text.index("## Hardware window (Stage 10)"):text.index("## Rollback and abort")]
        starts = [m.start() for m in re.finditer(r"^### Step (\d+)\. ", window, re.M)]
        self.assertEqual(re.findall(r"^### Step (\d+)\. ", window, re.M), [str(n) for n in range(1, 11)])
        steps = [window[a:b] for a, b in zip(starts, starts[1:] + [len(window)])]
        flash, app = "$flash '", "$app '"
        expected = {3: (flash, "nanod_enter_bootloader_v2.py"), 4: (flash, "backup_nanod_cc5.py"),
                    5: (flash, "prepare_nanod_cc5_install.py"), 6: (flash, "install_nanod_cc5.py"),
                    2: (app, "device_inventory.py"), 10: (app, "finalize_nanod_cc5.py")}
        for number, (interpreter, script) in expected.items():
            self.assertIn(f"{interpreter}C:\\", steps[number - 1], number)
            self.assertIn(f"\\{script}'", steps[number - 1], number)
        self.assertIn("\\check_nanod_cc5.py' --turn-seconds", steps[7])
        self.assertIn("\\check_nanod_cc5_lease.py' --observe-native-seconds", steps[7])
        # 1.0.0-cc5.2: 8b runs the 20-minute unattended soak, and the go-ahead request says so.
        self.assertIn("\\check_nanod_cc5.py' --turn-seconds 60 --soak-minutes 20", steps[7])
        go = " ".join(text[text.index("### Go-ahead first"):text.index("### Ports, interpreters and evidence")].split())
        for phrase in ("**unattended soak gate** of step 8b", "It needs nobody at the knob", "no audible cue",
                       "never a rerun", "a completed soak of at least 20 minutes",
                       "1.0.0-cc5.1 did not reset but its HMI task hung inside `FastLED.show()`"):
            self.assertIn(phrase, go)
        for gate in ("`taskLiveness`", "`unattendedSoak`"):
            self.assertIn(gate, steps[7])
        step1, step9 = steps[0], steps[8]
        self.assertIn("Do not use `Stop-Process`", step1)
        order = [step1.index(s) for s in ("Disable-ScheduledTask", "Get-Process -Name NanoDControlCenter",
                                          "'--smoke-test'", "$smoke.ExitCode -ne 0", "$report.pid -ne $smoke.Id")]
        self.assertEqual(order, sorted(order))  # exit code first, then pid and time of smoke-test.json
        order = [step9.index(s) for s in ("Copy-Item -LiteralPath $programs", "$dataHashesBefore = $hashes",
                                          "Install-Desktop.ps1' -Bundle desktop-dist-v3 -Mirror", "$dataHashesAfter =",
                                          "Enable-ScheduledTask", "Start-ScheduledTask", "Verify-NativeDesktop.ps1'")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("Get-Content -Raw -LiteralPath \"$dataDir", step9)  # hashes only, never contents
        self.assertIn("Install-Desktop.ps1' -Bundle desktop-dist-v2 -Mirror", text[text.index("## Rollback and abort"):])
        self.assertIn("\\rollback_nanod_cc5.py'", text[text.index("## Rollback and abort"):])
        self.assertIn("--accept-unconfirmed-reset", steps[5] + steps[9])

    # -- 1.0.0-cc5.3: BUILD-cc5.3.md and RECOVERY.md section 6 ----------------------------------

    V4_PENDING = ("\\desktop-dist-v4\\",)

    def build53(self):
        text = (ROOT / "firmware" / "BUILD-cc5.3.md").read_text(encoding="utf-8")
        window = text[text.index("## Hardware window (Stage 10)"):text.index("## Rollback and abort")]
        starts = [m.start() for m in re.finditer(r"^### Step (\d+)\. ", window, re.M)]
        self.assertEqual(re.findall(r"^### Step (\d+)\. ", window, re.M), [str(n) for n in range(1, 11)])
        return text, [window[a:b] for a, b in zip(starts, starts[1:] + [len(window)])]

    @staticmethod
    def lines(block):
        return [line.strip() for line in block.strip().splitlines()]

    @machine_runbook
    def test_build_cc5_3_runbook_follows_stage_10(self):
        text, steps = self.build53()
        cc53 = t.PROFILES["cc5.3"]          # the runbook of the cc5.2 -> cc5.3 install (history since cc5.4)
        self.assert_absolute_existing_paths(text, pending=self.V4_PENDING)
        flash, app = "$flash '", "$app '"
        expected = {3: (flash, "nanod_enter_bootloader_v2.py"), 4: (flash, "backup_nanod_cc5.py"),
                    5: (flash, "prepare_nanod_cc5_install.py"), 6: (flash, "install_nanod_cc5.py"),
                    2: (app, "device_inventory.py"), 10: (app, "finalize_nanod_cc5.py")}
        for number, (interpreter, script) in expected.items():
            self.assertIn(f"{interpreter}C:\\", steps[number - 1], number)
            self.assertIn(f"\\{script}'", steps[number - 1], number)
        self.assertIn("\\check_nanod_cc5.py' --turn-seconds 60 --soak-minutes 20", steps[7])
        self.assertIn("\\check_nanod_cc5_lease.py' --observe-native-seconds", steps[7])
        # The cc5.3 evidence names, the new backup pair and the cc5.2 checks of the pre-flash state.
        self.assertIn("'1.0.0-cc5.2' -or $inventory.capabilities.presentation -ne 4", steps[1])
        self.assertIn("diagnostics\\cc5.3-backup.json'", steps[3])
        self.assertIn(f"$backup.file -ne '{cc53.before_full.name}'", steps[3])
        self.assertIn(f"$backup.fromImageSha256 -ne '{cc53.from_image_sha256}'", steps[3])
        self.assertIn(f"backups\\{cc53.rollback_app.name}'", steps[4])
        self.assertIn(f"$prep.fromImageSha256 -ne '{cc53.from_image_sha256}'", steps[4])
        self.assertIn("'1.0.0-cc5.3' -or $after.capabilities.presentation -ne 4 -or $after.capabilities.artwork2.version -ne 1",
                      steps[7])
        for outcome in (cc53.restored_outcome, cc53.restored_unconfirmed_outcome):
            self.assertIn(f"`{outcome}`", steps[5])
        # Every gate finalize requires is named where 8b says what must pass; so are the lease cases.
        finalize = load_script("finalize_nanod_cc5.py")
        for gate in cc53.gates:
            self.assertIn(f"`{gate}`", steps[7], gate)
        for case in finalize.REQUIRED_LEASE_CASES:
            self.assertIn(f"`{case}`", steps[7], case)
        go = " ".join(text[text.index("### Go-ahead first"):text.index("### Ports, interpreters and evidence")].split())
        for phrase in ("**stress+turn hard gate** of step 8b", "**unattended soak gate** of step 8b",
                       "**artwork2 gates** of step 8b", "never a rerun", "step 4 makes a new full backup"):
            self.assertIn(phrase, go)
        step1, step9 = steps[0], steps[8]
        self.assertIn("Do not use `Stop-Process`", step1)
        self.assertIn("desktop-dist-v4\\NanoDControlCenter\\NanoDControlCenter.exe'", step1)
        order = [step1.index(s) for s in ("Disable-ScheduledTask", "Get-Process -Name NanoDControlCenter",
                                          "'--smoke-test'", "$smoke.ExitCode -ne 0", "$report.pid -ne $smoke.Id")]
        self.assertEqual(order, sorted(order))
        order = [step9.index(s) for s in ("Copy-Item -LiteralPath $programs", "$dataHashesBefore = $hashes",
                                          "Install-Desktop.ps1' -Bundle desktop-dist-v4 -Mirror", "$dataHashesAfter =",
                                          "Enable-ScheduledTask", "Start-ScheduledTask", "Verify-NativeDesktop.ps1'")]
        self.assertEqual(order, sorted(order))
        self.assertIn("-ne '90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19') { throw 'NO-GO: the "
                      "installed exe is not the recorded v3 companion' }", step9)
        self.assertIn("$status.artwork2 -ne $true", step9)
        self.assertNotIn("Get-Content -Raw -LiteralPath \"$dataDir", step9)  # hashes only, never contents
        rollback = text[text.index("## Rollback and abort"):]
        self.assertIn("Install-Desktop.ps1' -Bundle desktop-dist-v3 -Mirror", rollback)
        self.assertIn("\\rollback_nanod_cc5.py' --to cc5.2", rollback)
        self.assertIn("--accept-unconfirmed-reset", steps[5] + steps[9])
        self.assertIn("--light-assertions 2174149", steps[9])
        self.assertIn("manifest-1.0.0-cc5.3.json\").Hash) { throw 'NO-GO: manifest.json is not the cc5.3 record' }", steps[9])

    @machine_runbook
    def test_build_cc5_3_signals_guards_and_blocks(self):
        text, steps = self.build53()
        tail = text[text.index("## Hardware window (Stage 10)"):]
        blocks = [self.lines(block) for block in re.findall(r"```powershell\n(.*?)```", tail, re.S)]
        self.assert_exit_codes_are_armed(blocks, "BUILD-cc5.3.md")
        for lines in blocks:
            for name in ("flash", "app", "flashPython"):
                uses = [i for i, line in enumerate(lines) if re.search(rf"&\s+\${name}\b", line)]
                if uses:
                    self.assertTrue(any(line.startswith(f"${name} = 'C:\\") for line in lines[:uses[0]]), (name, lines[1]))
        for number, step in enumerate(steps, 1):
            for block in re.findall(r"```powershell\n(.*?)```", step, re.S):
                for message in re.findall(r"""throw ['"]([^'"]*)""", block):
                    self.assertRegex(message, r"^(?:NO-GO|NOT RUN): ", (number, message))
            self.assertRegex(step, r"(?m)^No-go|Go / no-go", number)
        guard = ("if (Get-Process -Name NanoDControlCenter -ErrorAction SilentlyContinue) { throw 'NOT RUN: the "
                 "companion is running; quit it from the tray, disable the startup task again (step 1, first two "
                 "lines), then run this block again' }")
        blocks8 = [self.lines(block) for block in re.findall(r"```powershell\n(.*?)```", steps[7], re.S)]
        self.assertEqual(len(blocks8), 3)
        for lines in blocks8:
            self.assertEqual(lines[1], guard)
        for number in (2, 3):
            lines = self.lines(re.findall(r"```powershell\n(.*?)```", steps[number - 1], re.S)[0])
            first_native = next(i for i, line in enumerate(lines) if self.NATIVE.search(line))
            self.assertIn(guard, lines[:first_native], number)
        block7 = re.findall(r"```powershell\n(.*?)```", steps[6], re.S)[0]
        self.assertRegex(block7, r"Get-Process -Name NanoDControlCenter[^\n]*throw 'NOT RUN: ")
        for lines, again in ((blocks8[1], "run 8b again"), (blocks8[2], "run 8c again")):
            failure = next(line for line in lines if line.startswith("if ($LASTEXITCODE -ne 0) { throw 'NO-GO: "))
            self.assertIn("NanoDControlCenter is running, it is NOT RUN instead", failure)
            self.assertIn(again, failure)
        # 8b arms the opt-in turn beeps right before the check and clears them right after it.
        check = next(i for i, line in enumerate(blocks8[1]) if "check_nanod_cc5.py'" in line)
        self.assertEqual(blocks8[1][check - 2], "$env:NANOD_AUDIBLE_CUES = '1'")
        self.assertEqual(blocks8[1][check + 1], "Remove-Item Env:NANOD_AUDIBLE_CUES -ErrorAction SilentlyContinue")
        blocks9 = re.findall(r"```powershell\n(.*?)```", steps[8], re.S)
        self.assertEqual(len(blocks9), 3)
        self.assertEqual(self.lines(blocks9[1])[1], "if (-not ($demo -and $dataDir -and $stamp -and $dataHashesBefore)) "
                                                    "{ throw 'NOT RUN: run 9a in this window first; nothing was installed' }")
        # The BUILD firmware rollback is the RECOVERY.md section 6 scripted block, character for character.
        rollback = text[text.index("### Firmware rollback, cc5.3 -> cc5.2"):text.index("### Desktop rollback, v4 -> v3")]
        recovery = (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8")
        section6 = recovery[recovery.index(self.SECTION6):]
        scripted = section6[section6.index("### cc5.3: Firmware, scripted"):section6.index("`nanod_enter_bootloader_v2.py` behaves")]
        self.assertEqual(re.findall(r"```powershell\n(.*?)```", rollback, re.S),
                         re.findall(r"```powershell\n(.*?)```", scripted, re.S))
        self.assertIn("rollback_nanod_cc5.py' --to cc5.2", scripted)

    def test_recovery_section6_rolls_back_to_cc5_2_with_the_same_interlocks(self):
        within = self.SECTION6
        [quit_block] = self.recovery_blocks("### cc5.3: Quit the companion", "### cc5.3: Firmware, scripted", 1, within)
        scripted, records = self.recovery_blocks("### cc5.3: Firmware, scripted", "### cc5.3: Firmware, manual", 2, within)
        blocks = self.recovery_blocks("### cc5.3: Firmware, manual esptool fallback",
                                      "### cc5.3: Leave the bootloader without writing", 4, within)
        flags = {"layoutVerified", "app0Verified", "rollbackVerified"}
        for lines in (quit_block, scripted):
            first = next((i for i, line in enumerate(lines) if "& $flashPython" in line), len(lines))
            self.assertEqual({f for line in lines[:first] for f in re.findall(r"\$(\w+Verified) = \$false", line)}, flags)
        self.assertIn("rollback_nanod_cc5.py' --to cc5.2", "\n".join(scripted))
        self.assertIn("rollback_nanod_cc5.py' --to cc5.2 --records-only", "\n".join(records))
        for lines in blocks:
            self.assertEqual((lines[0], lines[-1]), (". {", "}"))
            for i, line in enumerate(lines):
                if "-m esptool" in line or "rollback_nanod_cc5.py" in line or line.startswith("'@ | & $flashPython"):
                    self.assertRegex(lines[i + 1], r"^if \(\$LASTEXITCODE -ne 0\) \{ throw ", line)
        checks, write, regions, reset = ("\n".join(lines) for lines in blocks)
        # The cc5.3 inputs only; the cc5.2 history pair is never named here.
        cc53 = t.PROFILES["cc5.3"]
        for block in (checks,):
            self.assertIn(f"backups\\{cc53.before_full.name}'", block)
            self.assertIn(f"backups\\{cc53.rollback_app.name}'", block)
            self.assertIn("diagnostics\\cc5.3-preparation.json'", block)
            self.assertIn(r"backups\cc5.3-manual-rollback-' + (Get-Date)", block)
        section6 = (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8")
        section6 = section6[section6.index(self.SECTION6):section6.index("## Reference")]
        code6 = "\n".join(re.findall(r"```powershell\n(.*?)```", section6, re.S))
        self.assertNotIn("nanod-cc4-before-cc5", code6)                    # the cc5.2 history pair is never used
        self.assertNotIn("diagnostics\\cc5-preparation.json", code6)
        self.assertNotRegex(code6, r"rollback_nanod_cc5\.py'(?! --to cc5\.2)")   # always --to cc5.2
        self.assertEqual(write.count("--baud 460800 --before no_reset --after no_reset_stub write_flash --flash_mode keep "
                                     "--flash_freq keep --flash_size keep 0x10000 $rollbackApp"), 1)
        self.assertNotIn("write_flash", checks + regions + reset)
        self.assertEqual([b for b in (checks, write, regions, reset) if "hard_reset" in b], [reset])
        self.assertEqual([b for b in (checks, write, regions, reset) if "--records-only" in b], [reset])
        self.assertIn("rollback_nanod_cc5.py' --to cc5.2 --records-only", reset)
        version = next(i for i, line in enumerate(blocks[0]) if "import esptool; print(esptool.__version__)" in line)
        first_other = next(i for i, line in enumerate(blocks[0])
                           if "-m esptool" in line or "$romPort" in line or "Get-FileHash" in line or "@'" == line)
        self.assertLess(version, first_other)
        verify = next(i for i, line in enumerate(blocks[3]) if "verify_flash 0x10000 $rollbackApp" in line)
        hard_reset = next(i for i, line in enumerate(blocks[3]) if "--after hard_reset read_mac" in line)
        self.assertLess(verify, hard_reset)
        self.assertTrue(blocks[3][1].startswith("if (-not $rollbackVerified) { throw"))
        self.assertTrue(blocks[1][1].startswith("if (-not $layoutVerified) { throw"))
        self.assertTrue(blocks[2][1].startswith("if (-not $app0Verified) { throw"))

    @machine_runbook
    def test_recovery_section6_paths_and_commands(self):
        text = (ROOT / "firmware" / "RECOVERY.md").read_text(encoding="utf-8")
        section = text[text.index(self.SECTION6):text.index("## Reference")]
        self.assert_absolute_existing_paths(section)
        self.assertIn("-Bundle desktop-dist-v3 -Mirror", section)
        self.assertIn("90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19", section)
        self.assertNotIn("Stop-Process -", section)
        flat = " ".join(section.split())
        for sentence in ("Never reset, unplug or power-cycle the knob yourself", "Count every failed rollback write or verify",
                         "After the first, retry once. After the second, stop",
                         "and only after it has verified app0 once more itself",
                         "Any write outside block 2 invalidates that interlock", "`1.0.0-cc5.2`, `presentation` 4"):
            self.assertIn(sentence, flat)
        for code in ("0", "1", "2", "4", "5", "6", "-1"):
            self.assertRegex(section, rf"\n\| {code} \| ")
        # Every anchor the section links to exists in it.
        slugs = {re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
                 for heading in re.findall(r"^#{2,3} (.+)$", text, re.M)}
        for anchor in re.findall(r"\]\(#([^)]+)\)", section):
            self.assertIn(anchor, slugs)
        five = text[text.index("## 5. cc5 -> cc4 rollback"):text.index(self.SECTION6)]
        self.assertIn("[section 6](#6-cc53---cc52-rollback)", five)          # section 5 points to it

    def test_desktop_scripts_build_v7_and_roll_back_to_v6(self):
        # Desktop v7 is the desktop half of the combined cc5.4 release (ALIVE.md, DESKTOP_STAGE.md):
        # the scripts build and install desktop-dist-v7 and roll back to the pinned v6 (the floating
        # knob with the Windows-switcher carousel, installed 2026-09-25), v6 joins the rollback folders
        # that are never rebuilt, and the older v5/v4/v3/v2 rollbacks stay pinned.
        build = (ROOT / "Build-Desktop.ps1").read_text(encoding="utf-8")
        install = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("[string]$Dist = 'desktop-dist-v7',", build)
        self.assertIn("[string]$Work = 'desktop-build-v7',", build)
        self.assertIn("$rollbackFolders = @('desktop-dist-v2', 'desktop-build-v2', 'desktop-dist-v3', 'desktop-build-v3', "
                      "'desktop-dist-v4', 'desktop-build-v4', 'desktop-dist-v5', 'desktop-build-v5', 'desktop-dist-v6', "
                      "'desktop-build-v6')", build)
        refusal = build.index("if ($rollbackFolders -contains $leaf) { throw")
        self.assertLess(refusal, build.index("-m PyInstaller"))                  # before anything is built
        self.assertIn("[string]$Bundle = 'desktop-dist-v7',", install)
        for older in ("v6", "v5", "v4", "v3"):
            self.assertIn(f"Install-Desktop.ps1 -Bundle desktop-dist-{older} -Mirror", install)
        pins = {"desktop-dist-v3": "90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19",
                "desktop-dist-v4": "63047D1C7C181C456B0AEE6E825B21326899538164E6AFFECB3800785C0C44A5",
                "desktop-dist-v5": "0BF15DB86F5376F763193474457DEDFCB04D8ECEBC401E396E966EB668C2D210",
                "desktop-dist-v6": "2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F"}
        for folder, digest in pins.items():
            self.assertIn(f"'{folder}' = '{digest}'", install)
        # A refusal throws in a real install (a -DryRun records it instead; Stop-Install), before any change.
        pinned = install.index("if ($bundleExeHash -ne $pinnedBundles[$bundleName]) { Stop-Install")
        self.assertIn("if ($DryRun) { $refusals.Add($Message) } else { throw $Message }", install)
        self.assertLess(pinned, install.index("New-Item -ItemType Directory -Path $install -Force"))   # nothing changed yet
        self.assertLess(pinned, install.index("Remove-Item -LiteralPath $stale.FullName"))
        # The release records: cc5.4 ships desktop v7 and rolls back to v6; cc5.3 keeps v4 -> v3.
        self.assertEqual((t.CURRENT.desktop_bundle, t.CURRENT.desktop_rollback_bundle), ("desktop-dist-v7", "desktop-dist-v6"))
        self.assertEqual((t.PROFILES["cc5.3"].desktop_bundle, t.PROFILES["cc5.3"].desktop_rollback_bundle),
                         ("desktop-dist-v4", "desktop-dist-v3"))
        self.assertEqual(t.PROFILES["cc5.2"].desktop_rollback_bundle, "desktop-dist-v2")
        for folder, digest in pins.items():
            exe = t.desktop_bundle_exe(folder, ROOT)   # NanoDControlCenter\... for these old-name bundles
            if exe is not None:   # the pinned hash is that rollback bundle's (read only)
                self.assertEqual(t.sha256_file(exe).upper(), digest, folder)


# ---------------------------------------------------------------------------
# Script flows with a fake esptool: exit codes, outcomes, and that no reset follows a failure.

MAC_OUTPUT = "MAC: 12:34:56:78:9a:bc\nDetected flash size: 4MB\n"
RESET_OUTPUT = "MAC: 12:34:56:78:9a:bc\nHard resetting via RTS pin...\n"


class FakeEsptool:
    """Stands in for t.Esptool: per-step results (True, False or an exception); nothing is executed."""

    def __init__(self, results=None, on_read=None):
        self.results, self.on_read, self.calls, self.prefix = dict(results or {}), on_read, [], None

    def factory(self, port, report, prefix, **kwargs):
        self.port, self.report, self.prefix = port, report, prefix
        report.setdefault("steps", [])
        return self

    def __call__(self, name, args, *, after="no_reset_stub", timeout=240):
        args = t.validate_esptool_args(args)
        self.calls.append((name, args, after))
        self.report["steps"].append({"step": name, "after": after})
        result = self.results.get(name, True)
        if isinstance(result, BaseException):
            raise result
        if result and args[0] == "read_flash" and self.on_read:
            self.on_read(args)
        return bool(result), (RESET_OUTPUT if args[0] == "read_mac" else MAC_OUTPUT) if result else "A fatal error occurred"

    def names(self):
        return [name for name, _, _ in self.calls]

    def resets(self):
        return [name for name, _, after in self.calls if after == "hard_reset"]

    def args(self, name):
        return next(args for step, args, _ in self.calls if step == name)


def load_script(name):
    spec = importlib.util.spec_from_file_location(f"cc5_script_{Path(name).stem}", WORK / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # module level only imports and defines; main() is never run here
    return module


def current_names(profile):
    """The tooling's CURRENT and every module-level name derived from it (nanod_cc5_tooling, below
    PROFILES), as they read when `profile` is CURRENT."""
    return {"CURRENT": profile, "CC5_VERSION": profile.version, "CC5_TAG": profile.tag,
            "SUPERSEDED_CC5_VERSIONS": profile.superseded, "CC5_IMAGE": profile.image,
            "CC5_SOURCE_ZIP": profile.source_zip, "CC5_MANIFEST": profile.manifest, "BUILD_LOG": profile.build_log,
            "FROM_VERSION": profile.from_version, "FROM_IMAGE": profile.from_image, "FROM_RECORD": profile.from_record,
            "BEFORE_FULL": profile.before_full, "ROLLBACK_APP": profile.rollback_app,
            "EXPECTED_FULL": profile.expected_full, "BUILD_REPORT": profile.build_report,
            "BACKUP_REPORT": profile.backup_report, "PREPARATION": profile.preparation,
            "FLASH_CHECKS": profile.flash_checks, "DEVICE_CHECKS": profile.device_checks,
            "LEASE_CHECKS": profile.lease_checks, "ROLLBACK_REPORT": profile.rollback_report,
            "INSTALLATION": profile.installation}


def pin_current(enter, key):
    """Run a test as if PROFILES[key] were CURRENT: the flows of an earlier release (its fixtures are
    that release's evidence) still run through the same profile-driven code once CURRENT moves on.
    `enter` is an ExitStack's enter_context or a TestCase's enterContext. Scripts must be loaded after
    this (module-level names such as REQUIRED_GATES follow CURRENT)."""
    for name, value in current_names(t.PROFILES[key]).items():
        enter(mock.patch.object(t, name, value))


class HardwareFreeScriptTest(unittest.TestCase):
    """Runs a script's main() with every device, process and port entry point replaced.

    `pinned` names the profile a class's fixtures describe (None: CURRENT). The cc5.3-era flow classes
    keep their cc5.2 -> cc5.3 evidence and run pinned to "cc5.3" since CURRENT moved to cc5.4; the
    Cc54* flow classes run the same scripts against cc5.4 evidence. `active_binaries` is what
    tooling.ACTIVE_BINARIES reads during the test: the 2026-09-26 window's A, B and C by default (those flows
    were written for them), None for the real fix binaries D and E."""
    script, capture_evidence, pinned, active_binaries = None, True, None, LEGACY_BINARIES

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        if self.pinned:
            pin_current(self.stack.enter_context, self.pinned)
        if self.active_binaries is not None:
            self.stack.enter_context(mock.patch.object(t, "ACTIVE_BINARIES", tuple(self.active_binaries)))
        # Anything that would start a process or enumerate ports fails the test instead of running.
        self.stack.enter_context(mock.patch("subprocess.Popen", side_effect=AssertionError("no process in tests")))
        self.patch(t, "list_ports", mock.Mock(side_effect=AssertionError("no port enumeration in tests")))
        self.patch(t, "assert_flash_environment", lambda: {"python": "fake", "esptool": t.ESPTOOL_VERSION})
        self.patch(t, "console_utf8", lambda: None)
        self.patch(t, "find_rom_port", lambda *a, **k: "FAKEROM")
        self.patch(t, "poll_ports", lambda *a, **k: ("FAKEROM", []))
        self.evidence = []
        if self.capture_evidence:
            self.patch(t, "write_json_evidence", lambda path, data, **k: self.evidence.append(
                (Path(path).name, json.loads(json.dumps(data, default=str)))))
        self.out = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.out))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.module = load_script(self.script)

    def patch(self, target, name, value):
        self.stack.enter_context(mock.patch.object(target, name, value))


@needs_tooling
class InstallFlowTests(HardwareFreeScriptTest):
    """install_nanod_cc5.main() for the cc5.3 profile (pinned: its cc5.2 -> cc5.3 names and outcomes)."""
    script, pinned = "install_nanod_cc5.py", "cc5.3"

    def run_install(self, **results):
        fake = FakeEsptool(results)
        self.patch(t, "Esptool", fake.factory)
        self.patch(t, "load_json", lambda path: {"candidateSha256": "c" * 64})
        self.patch(self.module, "verify_inputs", lambda prep, manifest, p=None: None)
        code = self.module.main([])
        name, report = self.evidence[-1]
        self.assertEqual(name, t.FLASH_CHECKS.name)
        self.assertEqual(self.module.EXIT_CODES[report["outcome"]], code)
        return code, report, fake

    def test_verified_install_resets_once_at_the_end(self):
        code, report, fake = self.run_install()
        self.assertEqual((code, report["outcome"], report["reset"]), (0, "INSTALLED_VERIFIED_RESET", True))
        self.assertEqual(fake.names(), ["identity", "before-verify", "write", "after-verify", "reset"])
        self.assertEqual(fake.resets(), ["reset"])
        self.assertEqual(fake.args("write")[-2:], ["0x10000", str(t.CC5_IMAGE)])

    def test_stops_before_writing_on_identity_or_device_mismatch(self):
        for step in ("identity", "before-verify"):
            with self.subTest(step):
                code, report, fake = self.run_install(**{step: False})
                self.assertEqual((code, report["outcome"]), (2, "STOPPED_BEFORE_WRITE"))
                self.assertNotIn("write", fake.names())
                self.assertEqual(fake.resets(), [])

    def test_failed_write_or_verify_restores_cc5_2_before_any_reset(self):
        for step in ("write", "after-verify"):
            with self.subTest(step):
                code, report, fake = self.run_install(**{step: False})
                self.assertEqual((code, report["outcome"]), (3, "RESTORED_CC5_2_RESET"))
                self.assertEqual(fake.names()[-4:], ["restore-write", "restore-verify-app0", "restore-verify-full",
                                                     "restore-reset"])
                self.assertEqual(fake.resets(), ["restore-reset"])
                self.assertEqual(fake.args("restore-write")[-2:], ["0x10000", str(t.ROLLBACK_APP)])

    def test_failed_restore_never_resets(self):
        for step in ("restore-write", "restore-verify-app0", "restore-verify-full"):
            with self.subTest(step):
                code, report, fake = self.run_install(**{"after-verify": False, step: False})
                self.assertEqual((code, report["outcome"]), (4, "RESTORE_FAILED_NO_RESET"))
                self.assertEqual(fake.resets(), [])
                self.assertIn("Do not reset or power-cycle", self.out.getvalue())

    def test_unexpected_exceptions_follow_the_same_rules(self):
        code, report, fake = self.run_install(**{"after-verify": RuntimeError("usb glitch")})
        self.assertEqual((code, report["outcome"]), (3, "RESTORED_CC5_2_RESET"))
        self.assertIn("usb glitch", report["exception"])
        self.assertEqual(fake.resets(), ["restore-reset"])
        code, report, fake = self.run_install(**{"after-verify": RuntimeError("x"), "restore-verify-full": OSError("y")})
        self.assertEqual((code, report["outcome"], fake.resets()), (4, "RESTORE_FAILED_NO_RESET", []))
        code, report, fake = self.run_install(**{"before-verify": RuntimeError("usb glitch")})
        self.assertEqual((code, report["outcome"], fake.resets()), (2, "STOPPED_BEFORE_WRITE", []))
        self.assertNotIn("write", fake.names())

    def test_unconfirmed_reset_has_its_own_code_and_retry_command(self):
        code, report, fake = self.run_install(reset=False)
        self.assertEqual((code, report["outcome"]), (5, "INSTALLED_VERIFIED_RESET_UNCONFIRMED"))
        self.assertIn("--port FAKEROM --before no_reset --after hard_reset read_mac", report["resetRetryCommand"])
        self.assertIn(report["resetRetryCommand"], self.out.getvalue())
        self.assertNotIn("Next: boot sanity", self.out.getvalue())
        code, report, fake = self.run_install(write=False, **{"restore-reset": False})
        self.assertEqual((code, report["outcome"]), (6, "RESTORED_CC5_2_VERIFIED_RESET_UNCONFIRMED"))
        self.assertIn("resetRetryCommand", report)

    def test_no_port_means_nothing_sent_and_exit_1(self):
        fake = FakeEsptool()
        self.patch(t, "Esptool", fake.factory)
        self.patch(t, "load_json", lambda path: {"candidateSha256": "c" * 64})
        self.patch(self.module, "verify_inputs", lambda prep, manifest, p=None: None)
        self.patch(t, "find_rom_port", mock.Mock(side_effect=t.PortError("none")))
        with self.assertRaises(t.PortError):  # uncaught: Python exits 1
            self.module.main([])
        self.assertEqual((fake.calls, self.evidence), ([], []))

    def test_cc5_3_profile_names_its_evidence_and_outcomes(self):
        code, report, fake = self.run_install()
        self.assertEqual((fake.prefix, report["firmwareVersion"], report["fromVersion"]),
                         ("cc5.3", t.CC5_VERSION, "1.0.0-cc5.2"))
        self.assertEqual((report["rollbackFile"], report["backupFile"]), (t.ROLLBACK_APP.name, t.BEFORE_FULL.name))
        self.assertEqual(self.module.EXIT_CODES, {"INSTALLED_VERIFIED_RESET": 0, "STOPPED_BEFORE_WRITE": 2,
                                                  "RESTORED_CC5_2_RESET": 3, "RESTORE_FAILED_NO_RESET": 4,
                                                  "INSTALLED_VERIFIED_RESET_UNCONFIRMED": 5,
                                                  "RESTORED_CC5_2_VERIFIED_RESET_UNCONFIRMED": 6})
        self.assertEqual(self.module.exit_codes(t.PROFILES["cc5.2"])["RESTORED_CC4_RESET"], 3)   # the history names
        self.assertEqual({name: code for name, code in self.module.exit_codes(t.PROFILES["cc5.4"]).items()
                          if name.startswith("RESTORED_CC5_3")},
                         {"RESTORED_CC5_3_RESET": 3, "RESTORED_CC5_3_VERIFIED_RESET_UNCONFIRMED": 6})   # CURRENT's
        code, report, fake = self.run_install(**{"after-verify": False})
        self.assertIn("cc5.2 was restored, verified (app0 and full 4 MB) and reset", self.out.getvalue())
        for name, args, after in fake.calls:           # only app0 writes, keep flags; never another address
            if args[0] == "write_flash":
                self.assertEqual(args[:-1], [*self.module.WRITE_ARGS, "0x10000"], name)


@needs_tooling
class VerifyInputsTests(unittest.TestCase):
    """install_nanod_cc5.verify_inputs() with real files: every input must match its record, the
    expected image must follow from backup + release, and the rollback app0 must start with cc5.2
    (the cc5.3 profile, pinned)."""

    def setUp(self):
        pin_current(self.enterContext, "cc5.3")
        self.module = load_script("install_nanod_cc5.py")
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "backups").mkdir()
        (root / "firmware").mkdir()
        self.enterContext(mock.patch.object(t, "BACKUPS", root / "backups"))
        self.enterContext(mock.patch.object(t, "FIRMWARE_OUT", root / "firmware"))
        self.p = t.CURRENT
        self.from_image = b"\xe9" + b"cc5.2-image" * 90
        self.enterContext(mock.patch.object(self.p, "from_image_sha256", t.sha256_bytes(self.from_image)))
        self.enterContext(mock.patch.object(self.p, "from_image_bytes", len(self.from_image)))
        self.p.from_image.write_bytes(self.from_image)
        before = bytearray(b"\x5a" * t.FLASH_BYTES)
        before[t.APP_OFFSET:t.APP_OFFSET + len(self.from_image)] = self.from_image
        self.before = bytes(before)
        self.candidate = b"\xe9" + b"cc5.3-image" * 120 + t.CC5_VERSION.encode()
        expected, _ = t.assemble_expected(self.before, self.candidate)
        self.p.before_full.write_bytes(self.before)
        self.p.rollback_app.write_bytes(self.before[t.APP_OFFSET:t.APP_OFFSET + t.APP_SIZE])
        self.p.expected_full.write_bytes(bytes(expected))
        self.p.image.write_bytes(self.candidate)
        self.prep = {"firmwareVersion": t.CC5_VERSION, "applicationOffset": t.APP_OFFSET, "applicationSize": t.APP_SIZE,
                     "beforeSha256": t.sha256_bytes(self.before), "expectedSha256": t.sha256_bytes(bytes(expected)),
                     "rollbackSha256": t.sha256_file(self.p.rollback_app), "candidateFile": self.p.image.name}
        self.manifest = {"firmwareVersion": t.CC5_VERSION,
                         "artifacts": {self.p.image.name: {"sha256": t.sha256_bytes(self.candidate)}}}

    def refused(self, fragment, prep=None, manifest=None):
        with self.assertRaises(SystemExit) as caught:
            self.module.verify_inputs(prep or self.prep, manifest or self.manifest)
        self.assertIn(fragment, str(caught.exception))

    def test_consistent_inputs_pass(self):
        # The base the device must equal before the write: the pre-install backup (TOOLBC-1: or a step-down base).
        self.assertEqual(self.module.verify_inputs(self.prep, self.manifest), self.p.before_full)
        self.assertEqual(self.module.verify_inputs({**self.prep, "baseKind": "pre-install backup",
                                                    "baseFile": self.p.before_full.name}, self.manifest), self.p.before_full)

    def test_every_mismatch_stops_before_anything_is_sent(self):
        self.refused("is not for 1.0.0-cc5.3", prep={**self.prep, "firmwareVersion": "1.0.0-cc5.2"})
        self.refused("is not for 1.0.0-cc5.3", manifest={**self.manifest, "firmwareVersion": "1.0.0-cc5.2"})
        self.refused(f"{self.p.expected_full.name} does not match", prep={**self.prep, "expectedSha256": "0" * 64})
        self.refused("prepared other.bin", prep={**self.prep, "candidateFile": "other.bin"})
        self.refused("not target app0", prep={**self.prep, "applicationOffset": 0x150000})
        self.refused("names the base other.bin, not nanod-cc5.2-before-cc5.3-full.bin",
                     prep={**self.prep, "baseFile": "other.bin"})
        self.refused("names an unknown base (guess)", prep={**self.prep, "baseKind": "guess"})
        # A rollback app0 that is the backup's app0 but does not start with the cc5.2 image.
        with mock.patch.object(self.p, "from_image_sha256", "0" * 64):
            self.refused("does not hold the 1.0.0-cc5.2 image")
        # A rollback file for another backup.
        self.p.rollback_app.write_bytes(b"\xff" * t.APP_SIZE)
        self.refused("is not the backup's app0", prep={**self.prep, "rollbackSha256": t.sha256_file(self.p.rollback_app)})


@needs_tooling
class RollbackFlowTests(HardwareFreeScriptTest):
    """rollback_nanod_cc5.py --to cc5.2 (RECOVERY.md section 6). RollbackToCc4FlowTests runs every
    case again for the default cc4 history path (RECOVERY.md section 5, BUILD-cc5.md)."""
    script = "rollback_nanod_cc5.py"
    TARGET, ARGV = "cc5.2", ("--to", "cc5.2")

    def setUp(self):
        super().setUp()
        folder = self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        before = bytearray(b"\x5a" * t.FLASH_BYTES)
        before[0x8000:0x9000] = partition_table(LAYOUT)
        before[0xE000:0x10000] = ota_slot(1) + ota_slot(0)
        self.before = bytes(before)
        for name in ("BACKUPS", "DIAGNOSTICS", "FIRMWARE_OUT"):      # records the flow reads: this folder only
            self.patch(t, name, folder)
        self.profile = t.ROLLBACK_TARGETS[self.TARGET]
        self.profile.before_full.write_bytes(self.before)          # only the target's own backup exists
        self.prepared = []
        real_load = t.load_json
        # Records written into the folder by a test are read for real; the preparation record is faked.
        self.patch(t, "load_json", lambda path: real_load(path) if Path(path).is_file() else
                   (self.prepared.append(Path(path).name) or {"rollbackSha256": "r" * 64, "beforeSha256": "b" * 64}))
        self.patch(self.module, "check_files", lambda prep, p=None: None)
        self.patch(self.module, "check_record_inputs", lambda p=None: None)
        self.records = []
        self.patch(self.module, "restore_records",
                   lambda report, p=None: self.records.append((report["outcome"], p.version)))

    def fake_read(self, args, corrupt):
        offset, size, path = int(args[1], 16), int(args[2], 16), Path(args[3])
        data = self.before[offset:offset + size]
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:] if path.stem[len("current-"):] in corrupt else data)

    def run_rollback(self, *argv, corrupt=(), **results):
        fake = FakeEsptool(results, on_read=lambda args: self.fake_read(args, corrupt))
        self.patch(t, "Esptool", fake.factory)
        self.records.clear()
        code = self.module.main([*self.ARGV, *argv])
        name, report = self.evidence[-1]
        self.assertEqual(name, self.profile.rollback_report.name)
        self.assertEqual({version for _, version in self.records} - {self.profile.version}, set())   # the target's records
        self.records = [outcome for outcome, _ in self.records]
        return code, report, fake

    def test_verified_rollback_resets_last_and_restores_records(self):
        code, report, fake = self.run_rollback()
        self.assertEqual((code, report["outcome"]), (0, "ROLLED_BACK_VERIFIED_RESET"))
        self.assertEqual(fake.names(), ["identity", "read-partitions", "read-otadata", "write", "verify-app0",
                                        "verify-full", "reset"])
        self.assertEqual(fake.resets(), ["reset"])
        self.assertEqual(self.records, ["ROLLED_BACK_VERIFIED_RESET"])
        # The target's own files, evidence and names.
        p = self.profile
        self.assertEqual(fake.prefix, p.rollback_log_prefix)
        self.assertEqual(fake.args("write")[-2:], ["0x10000", str(p.rollback_app)])
        self.assertEqual(fake.args("verify-full")[-1], str(p.before_full))
        self.assertEqual(self.prepared, [p.preparation.name])
        self.assertTrue(report["workdir"].startswith(f"{p.prefix}-rollback-"))
        self.assertEqual((report["target"], report["toVersion"]), (self.TARGET, p.from_version))
        self.assertIn(f"-Bundle {p.desktop_rollback_bundle} -Mirror", report["desktopRollback"])

    def test_changed_layout_or_identity_stops_before_writing(self):
        for corrupt, results in ((("partitions",), {}), (("otadata",), {}), ((), {"identity": False})):
            with self.subTest(corrupt=corrupt, results=results):
                code, report, fake = self.run_rollback(corrupt=corrupt, **results)
                self.assertEqual((code, report["outcome"]), (2, "STOPPED_BEFORE_WRITE"))
                self.assertNotIn("write", fake.names())
                self.assertEqual((fake.resets(), self.records), ([], []))

    def test_failures_after_the_write_never_reset_or_touch_records(self):
        for results, outcome in (({"write": False}, "WRITE_FAILED_NO_RESET"),
                                 ({"verify-app0": False}, "APP0_VERIFY_FAILED_NO_RESET"),
                                 ({"verify-full": False, "verify-app1": False}, "CRITICAL_REGION_MISMATCH_NO_RESET"),
                                 ({"verify-full": False, "verify-bootloader": False}, "CRITICAL_REGION_MISMATCH_NO_RESET"),
                                 ({"verify-app0": RuntimeError("usb glitch")}, "FAILED_AFTER_WRITE_NO_RESET")):
            with self.subTest(outcome=outcome, results=list(results)):
                code, report, fake = self.run_rollback(**results)
                self.assertEqual((code, report["outcome"]), (4, outcome))
                self.assertEqual((fake.resets(), self.records), ([], []))
                self.assertIn("Do not reset or power-cycle", self.out.getvalue())

    def test_data_region_drift_alone_still_resets(self):
        code, report, fake = self.run_rollback(**{"verify-full": False, "verify-nvs": False, "verify-spiffs": False})
        self.assertEqual((code, report["outcome"]), (0, "ROLLED_BACK_VERIFIED_RESET"))
        self.assertEqual(report["dataRegionsChangedSinceBackup"], ["nvs", "spiffs"])
        self.assertEqual(fake.resets(), ["reset"])
        self.assertLess(fake.names().index("verify-app1"), fake.names().index("reset"))

    def test_unconfirmed_reset_and_record_failure_have_their_own_codes(self):
        code, report, fake = self.run_rollback(reset=False)
        self.assertEqual((code, report["outcome"]), (5, "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED"))
        self.assertIn("--port FAKEROM --before no_reset --after hard_reset read_mac", report["resetRetryCommand"])
        self.assertEqual(self.records, ["ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED"])  # flash verified: records follow it
        self.patch(self.module, "restore_records", mock.Mock(side_effect=SystemExit("manifest-cc4.json unreadable")))
        code, report, fake = self.run_rollback()
        self.assertEqual((code, report["outcome"]), (6, "ROLLED_BACK_VERIFIED_RESET"))
        self.assertIn("manifest-cc4.json unreadable", report["recordsError"])

    def test_records_only_never_touches_the_device(self):
        code, report, fake = self.run_rollback("--records-only")
        self.assertEqual((code, report["outcome"], fake.calls), (0, "RECORDS_ONLY", []))
        self.assertEqual(self.records, ["RECORDS_ONLY"])

    def closing(self, *argv, **results):
        """run_rollback, and what it printed."""
        start = len(self.out.getvalue())
        code, report, _ = self.run_rollback(*argv, **results)
        return code, report, self.out.getvalue()[start:]

    def test_the_closing_line_follows_the_outcome(self):
        """2026-09-26 (binary A's rollback): a clean ROLLED_BACK_VERIFIED_RESET ended with the false 'Rollback did NOT
        complete; the chip was NOT reset'. Each outcome now prints one closing line, and the data-region note follows it
        on its own, so an unconfirmed reset with drift keeps its retry command."""
        failed = "Rollback did NOT complete"
        code, report, out = self.closing()
        self.assertEqual((code, report["outcome"]), (0, "ROLLED_BACK_VERIFIED_RESET"))
        self.assertIn("restored in app0, verified and reset", out)
        self.assertNotIn(failed, out)
        self.assertNotIn("Data regions changed", out)
        code, report, out = self.closing(**{"verify-full": False, "verify-nvs": False})             # drift, still exit 0
        self.assertEqual(code, 0)
        self.assertLess(out.index("restored in app0, verified and reset"), out.index("Data regions changed since"))
        self.assertNotIn(failed, out)
        code, report, out = self.closing("--records-only")
        self.assertEqual(code, 0)
        self.assertIn("Records only: the device was not touched by this run.", out)
        self.assertNotIn(failed, out)
        code, report, out = self.closing(reset=False, **{"verify-full": False, "verify-coredump": False})   # exit 5 + drift
        self.assertEqual((code, report["outcome"]), (5, "ROLLED_BACK_VERIFIED_RESET_UNCONFIRMED"))
        self.assertIn(report["resetRetryCommand"], out)
        self.assertLess(out.index(report["resetRetryCommand"]), out.index("Data regions changed since"))
        self.assertNotIn(failed, out)
        code, report, out = self.closing(identity=False)                                             # exit 2
        self.assertEqual(code, 2)
        self.assertIn("Stopped before writing", out)
        self.assertNotIn(failed, out)
        code, report, out = self.closing(write=False)                                                # exit 4
        self.assertEqual((code, report["outcome"]), (4, "WRITE_FAILED_NO_RESET"))
        self.assertIn(f"{failed}; the chip was NOT reset. Do not reset or power-cycle.", out)
        self.patch(self.module, "restore_records", mock.Mock(side_effect=SystemExit("manifest-cc4.json unreadable")))
        code, report, out = self.closing()                                                            # exit 6
        self.assertEqual((code, report["outcome"]), (6, "ROLLED_BACK_VERIFIED_RESET"))
        self.assertIn("manifest.json was NOT restored", out)
        self.assertIn("restored in app0, verified and reset", out)
        self.assertNotIn(failed, out)


@needs_tooling
class RollbackToCc4FlowTests(RollbackFlowTests):
    """The same cases through the history path: no --to is the cc5 -> cc4 rollback of RECOVERY.md section 5."""
    TARGET, ARGV = "cc4", ()

    def test_the_default_is_the_documented_history_path(self):
        self.assertEqual(t.DEFAULT_ROLLBACK_TARGET, "cc4")
        self.assertIs(t.ROLLBACK_TARGETS["cc4"], t.PROFILES["cc5.2"])
        self.assertEqual(self.profile.before_full.name, "nanod-cc4-before-cc5-full.bin")
        self.assertEqual(self.profile.rollback_report.name, "cc5-rollback.json")
        code, report, _ = self.run_rollback()
        self.assertEqual((code, report["target"], report["fromVersion"], report["writeEvidence"]),
                         (0, "cc4", "1.0.0-cc5.2", {}))

    def cc5_3_written(self, how):
        cc53 = t.PROFILES["cc5.3"]
        if how == "flash-checks":
            cc53.flash_checks.write_text(json.dumps({"writeAttempted": True, "outcome": "INSTALLED_VERIFIED_RESET"}),
                                         encoding="utf-8")
        else:
            cc53.manifest.write_text(json.dumps({"installationStatus": how}), encoding="utf-8")

    def test_without_to_it_refuses_once_cc5_3_was_written(self):
        """On a knob that got cc5.3, the history default would silently go two releases back: the
        target must be named. Nothing is sent and no evidence is written."""
        for how in ("flash-checks", "INSTALLED", "ROLLED_BACK"):
            with self.subTest(how=how):
                for stale in self.folder.glob("*.json"):
                    stale.unlink()
                self.cc5_3_written(how)
                fake = FakeEsptool()
                self.patch(t, "Esptool", fake.factory)
                environment = mock.Mock()
                self.patch(t, "assert_flash_environment", environment)
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                    self.module.main([])
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("--to is required: the records show 1.0.0-cc5.3 written to the knob", stderr.getvalue())
                self.assertIn("Pass --to cc5.3 to restore 1.0.0-cc5.3 from cc5.4, --to cc5.2 to restore 1.0.0-cc5.2",
                              stderr.getvalue())
                self.assertEqual((fake.calls, self.evidence, environment.call_count), ([], [], 0))
        # An UNFLASHED (packaged, never written) cc5.3 keeps the documented default.
        for stale in self.folder.glob("*.json"):
            stale.unlink()
        self.cc5_3_written("UNFLASHED")
        code, report, _ = self.run_rollback()
        self.assertEqual((code, report["target"]), (0, "cc4"))

    def test_an_explicit_cc4_rollback_from_cc5_3_records_what_was_written(self):
        self.cc5_3_written("flash-checks")
        self.ARGV = ("--to", "cc4")
        code, report, fake = self.run_rollback()
        self.assertEqual((code, report["outcome"], report["target"]), (0, "ROLLED_BACK_VERIFIED_RESET", "cc4"))
        self.assertEqual((report["fromVersion"], report["toVersion"]), ("1.0.0-cc5.3", "1.0.0-cc4"))
        self.assertEqual(report["writeEvidence"], {"1.0.0-cc5.3": ["cc5.3-flash-checks.json records a cc5.3 write attempt"]})
        self.assertEqual(report["undoesInstallsOf"], ["1.0.0-cc5.2", "1.0.0-cc5.3", "1.0.0-cc5.4"])
        self.assertEqual(fake.args("write")[-2:], ["0x10000", str(self.profile.rollback_app)])

    def test_help_is_printed_without_touching_anything(self):
        """--help through the same fakes as every flow: argparse exits 0 before the environment check."""
        fake = FakeEsptool()
        self.patch(t, "Esptool", fake.factory)
        environment = mock.Mock()
        self.patch(t, "assert_flash_environment", environment)
        with self.assertRaises(SystemExit) as caught:
            self.module.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        text = self.out.getvalue()
        for fragment in ("--to {cc4,cc5.2,cc5.3}", "--records-only",
                         "only while the records never show 1.0.0-cc5.3 written", "RECOVERY.md section 6",
                         "--to cc5.3 cc5.4 -> cc5.3", "-Bundle desktop-dist-v6 -Mirror"):
            self.assertIn(fragment, " ".join(text.split()))
        self.assertEqual((fake.calls, self.evidence, environment.call_count), ([], [], 0))


@needs_tooling
class RollbackToCc53FlowTests(RollbackFlowTests):
    """The same cases for rollback_nanod_cc5.py --to cc5.3: cc5.4 -> cc5.3 from the pre-cc5.4 backup
    (backups/nanod-cc5.3-before-cc5.4-*.bin, diagnostics/cc5.4-preparation.json), desktop back to v6."""
    TARGET, ARGV = "cc5.3", ("--to", "cc5.3")

    def test_the_cc5_3_target_is_the_cc5_4_profile(self):
        self.assertIs(self.profile, t.PROFILES["cc5.4"])
        self.assertEqual((self.profile.before_full.name, self.profile.rollback_app.name),
                         ("nanod-cc5.3-before-cc5.4-full.bin", "nanod-cc5.3-before-cc5.4-active-app.bin"))
        self.assertEqual((self.profile.rollback_report.name, self.profile.desktop_rollback_bundle),
                         ("cc5.4-rollback.json", "desktop-dist-v6"))
        code, report, _ = self.run_rollback()
        self.assertEqual((code, report["target"], report["toVersion"]), (0, "cc5.3", "1.0.0-cc5.3"))
        self.assertEqual(self.module.removed_releases(self.profile), ["1.0.0-cc5.4"])


@needs_tooling
class RollbackRecordTests(unittest.TestCase):
    """rollback_nanod_cc5.restore_records / check_files / check_record_inputs on real files in a temporary folder
    (a knob with cc5.3 installed: pinned to cc5.3; a cc5.4 manifest is not present)."""

    def setUp(self):
        pin_current(self.enterContext, "cc5.3")
        self.module = load_script("rollback_nanod_cc5.py")
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fw = self.root / "firmware"
        self.fw.mkdir()
        for name, value in (("FIRMWARE_OUT", self.fw), ("ACTIVE_MANIFEST", self.fw / "manifest.json"),
                            ("BACKUPS", self.root), ("DIAGNOSTICS", self.root)):
            self.enterContext(mock.patch.object(t, name, value))
        self.images = {"1.0.0-cc4": b"\xe9 cc4 image" * 30, "1.0.0-cc5.2": b"\xe9 cc5.2 image" * 40,
                       "1.0.0-cc5.3": b"\xe9 cc5.3 image" * 50}
        for p in t.PROFILES.values():
            image = self.images[p.from_version]
            self.enterContext(mock.patch.object(p, "from_image_sha256", t.sha256_bytes(image)))
            self.enterContext(mock.patch.object(p, "from_image_bytes", len(image)))
            p.from_image.write_bytes(image)
            p.from_record.write_text(json.dumps({"firmwareVersion": p.from_version, "installationStatus": "INSTALLED",
                                                 "artifacts": {p.from_image.name: {"sha256": t.sha256_bytes(image)}}}),
                                     encoding="utf-8")
        self.cc53 = {"firmwareVersion": t.CC5_VERSION, "installationStatus": "INSTALLED"}
        t.CURRENT.manifest.write_text(json.dumps(self.cc53), encoding="utf-8")
        t.ACTIVE_MANIFEST.write_text(json.dumps(self.cc53), encoding="utf-8")
        t.PROFILES["cc5.2"].manifest.write_text(json.dumps({"installationStatus": "SUPERSEDED"}), encoding="utf-8")

    def test_cc5_3_to_cc5_2_restores_the_kept_cc5_2_record(self):
        report, p = {}, t.ROLLBACK_TARGETS["cc5.2"]
        self.module.restore_records(report, p)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), p.from_record.read_bytes())
        [kept] = self.fw.glob("manifest-at-cc5.3-rollback-*.json")
        self.assertEqual(json.loads(kept.read_text(encoding="utf-8")), self.cc53)
        self.assertEqual(report["manifestRestored"], {"from": "manifest-cc5.2.json", "previousKeptAs": kept.name})
        self.assertEqual(t.load_json(t.CURRENT.manifest)["installationStatus"], "ROLLED_BACK")
        self.assertEqual(t.load_json(t.CURRENT.manifest)["rollback"], "diagnostics/cc5.3-rollback.json")
        self.assertEqual(t.load_json(t.CURRENT.manifest)["hardwareStatus"],
                         "Rolled back to cc5.2 (app0 restored from the pre-cc5.3 backup).")
        self.assertEqual(report["manifestsMarkedRolledBack"], ["manifest-1.0.0-cc5.3.json"])
        self.assertEqual(t.load_json(t.PROFILES["cc5.2"].manifest), {"installationStatus": "SUPERSEDED"})

    def test_the_cc4_history_path_undoes_every_installed_cc5_release(self):
        report, p = {}, t.ROLLBACK_TARGETS["cc4"]
        self.module.restore_records(report, p)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), (self.fw / "manifest-cc4.json").read_bytes())
        self.assertEqual(len(list(self.fw.glob("manifest-at-cc5-rollback-*.json"))), 1)
        self.assertEqual(t.load_json(t.CURRENT.manifest)["installationStatus"], "ROLLED_BACK")   # cc5.3 was installed
        # The cc4 path restores the pair every cc5.x install from cc4 shared: the pre-cc5 backup.
        self.assertEqual(t.load_json(t.CURRENT.manifest)["hardwareStatus"],
                         "Rolled back to cc4 (app0 restored from the pre-cc5 backup).")
        self.assertEqual(t.load_json(t.PROFILES["cc5.2"].manifest), {"installationStatus": "SUPERSEDED"})
        self.assertEqual(self.module.removed_releases(p), ["1.0.0-cc5.2", "1.0.0-cc5.3", "1.0.0-cc5.4"])
        self.assertEqual((t.PROFILES["cc5.2"].backup_role, t.PROFILES["cc5.3"].backup_role),
                         ("pre-cc5 backup", "pre-cc5.3 backup"))

    def test_write_evidence_of_a_release(self):
        cc53 = t.PROFILES["cc5.3"]
        self.assertEqual(t.release_write_evidence(cc53), ["manifest-1.0.0-cc5.3.json status is INSTALLED"])
        cc53.manifest.write_text(json.dumps({"installationStatus": "UNFLASHED"}), encoding="utf-8")
        self.assertEqual(t.release_write_evidence(cc53), [])
        (self.root / "cc5.3-flash-checks.superseded-20260924T000000Z.json").write_text(
            json.dumps({"writeAttempted": False, "outcome": "STOPPED_BEFORE_WRITE"}), encoding="utf-8")
        self.assertEqual(t.release_write_evidence(cc53), [])
        cc53.flash_checks.write_text("{not json", encoding="utf-8")
        self.assertEqual(t.release_write_evidence(cc53), ["cc5.3-flash-checks.json is unreadable"])
        cc53.flash_checks.write_text(json.dumps({"flashWritten": True}), encoding="utf-8")
        self.assertEqual(t.release_write_evidence(cc53), ["cc5.3-flash-checks.json records a cc5.3 write attempt"])
        # The cc5.2 profile's own records (prefix cc5) never count for cc5.3, nor the other way round.
        (self.root / "cc5-flash-checks.json").write_text(json.dumps({"writeAttempted": True}), encoding="utf-8")
        self.assertEqual(t.release_write_evidence(cc53), ["cc5.3-flash-checks.json records a cc5.3 write attempt"])
        self.assertEqual(t.later_profiles(t.PROFILES["cc5.2"]), [cc53, t.PROFILES["cc5.4"]])
        self.assertEqual(t.later_profiles(cc53), [t.PROFILES["cc5.4"]])
        self.assertEqual(t.later_profiles(t.PROFILES["cc5.4"]), [])

    def test_inputs_are_checked_before_anything_is_sent(self):
        p = t.ROLLBACK_TARGETS["cc5.2"]
        before = bytearray(b"\x5a" * t.FLASH_BYTES)
        before[t.APP_OFFSET:t.APP_OFFSET + len(self.images["1.0.0-cc5.2"])] = self.images["1.0.0-cc5.2"]
        p.before_full.write_bytes(bytes(before))
        p.rollback_app.write_bytes(bytes(before[t.APP_OFFSET:t.APP_OFFSET + t.APP_SIZE]))
        prep = {"rollbackSha256": t.sha256_file(p.rollback_app), "beforeSha256": t.sha256_file(p.before_full)}
        self.assertIsNone(self.module.check_files(prep, p))
        self.assertIsNone(self.module.check_record_inputs(p))
        with self.assertRaises(SystemExit) as caught:
            self.module.check_files({**prep, "rollbackSha256": "0" * 64}, p)
        self.assertIn("does not match cc5.3-preparation.json", str(caught.exception))
        p.rollback_app.write_bytes(b"\xe9" + bytes(t.APP_SIZE - 1))       # not the cc5.2 app0
        with self.assertRaises(SystemExit) as caught:
            self.module.check_files({**prep, "rollbackSha256": t.sha256_file(p.rollback_app)}, p)
        self.assertIn("does not hold the 1.0.0-cc5.2 image", str(caught.exception))
        p.from_record.write_text(json.dumps({"firmwareVersion": "1.0.0-cc5.3"}), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.module.check_record_inputs(p)
        self.assertIn("manifest-cc5.2.json is not the 1.0.0-cc5.2 record", str(caught.exception))


@needs_tooling
class BackupFlowTests(HardwareFreeScriptTest):
    """backup_nanod_cc5.main() for the cc5.3 profile: a fresh 4 MB read with cc5.2 at app0 becomes the
    pre-cc5.3 backup, and once a cc5.3 write happened it is locked. The cc5.2 history pair and records
    (backups/nanod-cc4-before-cc5-*.bin, diagnostics/cc5-*.json) are never touched. Pinned to cc5.3."""
    script, capture_evidence, pinned = "backup_nanod_cc5.py", False, "cc5.3"

    def setUp(self):
        super().setUp()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.backups, self.diag, self.fw = root / "backups", root / "diagnostics", root / "firmware"
        for folder in (self.backups, self.diag, self.fw):
            folder.mkdir()
        for name, value in (("BACKUPS", self.backups), ("DIAGNOSTICS", self.diag), ("FIRMWARE_OUT", self.fw),
                            ("ORIGINAL_PARTITIONS", root / "none.bin")):
            self.patch(t, name, value)
        self.p = t.CURRENT
        self.cc52 = b"\xe9" + b"cc5.2-image" * 100
        self.patch(self.p, "from_image_sha256", hashlib.sha256(self.cc52).hexdigest())
        self.patch(self.p, "from_image_bytes", len(self.cc52))
        self.p.from_image.write_bytes(self.cc52)
        self.p.before_full.write_bytes(b"pre-cc5.3 backup")
        self.p.backup_report.write_text(json.dumps({"passed": True, "sha256": "pre-cc5.3"}), encoding="utf-8")
        # The cc5.2 history: its locked pair and records, a cc5.2 write and rollback, an INSTALLED manifest.
        old = t.PROFILES["cc5.2"]
        self.history = {old.before_full: b"cc4 before cc5 (locked history)", old.rollback_app: b"cc4 app0 (history)",
                        old.backup_report: b'{"passed": true, "sha256": "history"}',
                        old.flash_checks: b'{"writeAttempted": true, "outcome": "INSTALLED_VERIFIED_RESET"}',
                        old.rollback_report: b'{"outcome": "ROLLED_BACK_VERIFIED_RESET"}',
                        old.manifest: b'{"installationStatus": "INSTALLED"}'}
        for path, data in self.history.items():
            path.write_bytes(data)

    def tearDown(self):
        for path, data in self.history.items():            # never written, renamed or replaced
            self.assertEqual(path.read_bytes(), data, path.name)
        self.assertEqual(list(self.backups.glob("nanod-cc4-before-cc5*.superseded-*")), [])
        self.assertEqual(list(self.diag.glob("cc5-*.superseded-*")), [])

    def read_image(self, with_cc52=True):
        image = bytearray(b"\x33" * t.FLASH_BYTES)
        if with_cc52:
            image[t.APP_OFFSET:t.APP_OFFSET + len(self.cc52)] = self.cc52
        return bytes(image)

    def run_backup(self, with_cc52=True, **results):
        image = self.read_image(with_cc52)
        fake = FakeEsptool(results, on_read=lambda args: Path(args[3]).write_bytes(image))
        self.patch(t, "Esptool", fake.factory)
        return self.module.main([]), fake, image

    def assert_pre_cc53_pair_untouched(self):
        self.assertEqual(self.p.before_full.read_bytes(), b"pre-cc5.3 backup")
        self.assertEqual(t.load_json(self.p.backup_report), {"passed": True, "sha256": "pre-cc5.3"})
        self.assertEqual(list(self.backups.glob("nanod-cc5.2-before-cc5.3*.superseded-*"))
                         + list(self.diag.glob("cc5.3-*.superseded-*")), [])

    def test_before_any_cc5_3_write_the_backup_and_record_are_replaced_together(self):
        """The cc5.2 records (a write, a rollback, an INSTALLED manifest) never lock the cc5.3 backup."""
        self.assertEqual(t.backup_locks(), [])
        self.assertTrue(t.pre_cc5_backup_locks())                        # while the cc5.2 pair stays locked
        code, fake, image = self.run_backup()
        self.assertEqual((code, fake.prefix), (0, "cc5.3-backup"))
        self.assertEqual(fake.names(), ["identity", "read", "verify"])   # read-only on the device
        self.assertTrue(fake.args("read")[3].endswith(".bin.partial"))
        self.assertIn("cc5.3-backup-read-", fake.args("read")[3])
        self.assertEqual(self.p.before_full.read_bytes(), image)
        report = t.load_json(self.p.backup_report)
        self.assertEqual((report["sha256"], report["fromImageAtApp0"], report["passed"], report["role"], report["file"]),
                         (hashlib.sha256(image).hexdigest(), True, True, "pre-cc5.3 backup", t.BEFORE_FULL.name))
        self.assertEqual((report["firmwareVersion"], report["fromVersion"]), (t.CC5_VERSION, "1.0.0-cc5.2"))
        self.assertEqual([p.read_bytes() for p in self.backups.glob("nanod-cc5.2-before-cc5.3*.superseded-*")],
                         [b"pre-cc5.3 backup"])
        self.assertEqual(len(list(self.diag.glob("cc5.3-backup.superseded-*.json"))), 1)

    def test_after_a_cc5_3_write_attempt_the_pre_cc5_3_backup_is_kept(self):
        (self.diag / "cc5.3-flash-checks-20260101T000000Z.json").write_text(
            json.dumps({"writeAttempted": True, "outcome": self.p.restored_outcome}), encoding="utf-8")
        (self.diag / "cc5.3-flash-checks.json").write_text(json.dumps({"writeAttempted": False}), encoding="utf-8")
        code, fake, image = self.run_backup()
        self.assertEqual((code, fake.prefix), (3, "cc5.3-backup"))
        self.assert_pre_cc53_pair_untouched()
        [kept] = self.backups.glob("nanod-diagnostic-full-*.bin")
        self.assertEqual(kept.read_bytes(), image)
        [evidence] = self.diag.glob("cc5.3-backup-diagnostic-read-*.json")
        record = t.load_json(evidence)
        self.assertEqual(record["role"], "diagnostic read")
        self.assertFalse(record["identicalToLockedBackup"])
        self.assertTrue(any("differs" in r for r in record["notConfirmedBecause"]))

    def lock_like_a_cc5_3_rollback(self, before):
        """After a cc5.3 install and its verified rollback to exactly `before`."""
        self.p.before_full.write_bytes(before)
        self.p.backup_report.write_text(json.dumps({"passed": True, "sha256": hashlib.sha256(before).hexdigest(),
                                                    "role": "pre-cc5.3 backup", "file": self.p.before_full.name}),
                                        encoding="utf-8")
        (self.diag / "cc5.3-flash-checks.superseded-20260924T163000Z.json").write_text(
            json.dumps({"writeAttempted": True, "outcome": "INSTALLED_VERIFIED_RESET"}), encoding="utf-8")
        (self.diag / "cc5.3-rollback.json").write_text(json.dumps({"outcome": "ROLLED_BACK_VERIFIED_RESET"}),
                                                       encoding="utf-8")
        self.assertTrue(t.backup_locks())

    def test_after_a_rollback_an_identical_read_is_a_valid_current_backup(self):
        before = self.read_image()
        self.lock_like_a_cc5_3_rollback(before)
        record_before = self.p.backup_report.read_bytes()
        code, fake, image = self.run_backup()
        self.assertEqual((code, image), (0, before))
        self.assertEqual(self.p.before_full.read_bytes(), before)                  # never replaced
        self.assertEqual(list(self.backups.glob("nanod-cc5.2-before-cc5.3*.superseded-*")), [])
        [kept] = self.backups.glob("nanod-cc5.2-confirm-read-*.bin")
        self.assertEqual(kept.read_bytes(), before)
        report = t.load_json(self.p.backup_report)
        self.assertEqual(report["role"], "current backup (identical to the locked pre-cc5.3 backup)")
        self.assertEqual((report["file"], report["sha256"], report["confirmingRead"], report["passed"]),
                         (self.p.before_full.name, hashlib.sha256(before).hexdigest(), kept.name, True))
        self.assertTrue(report["identicalToLockedBackup"] and report["fromImageAtApp0"] and report["verifiedAgainstDevice"])
        self.assertTrue(report["backupLocks"])
        [old] = self.diag.glob("cc5.3-backup.superseded-*.json")                    # the earlier record is kept
        self.assertEqual(old.read_bytes(), record_before)

    def test_after_a_rollback_a_different_read_is_refused(self):
        before = bytearray(self.read_image())
        before[0x3F0000] ^= 0xFF                                                    # e.g. a core dump written since
        self.lock_like_a_cc5_3_rollback(bytes(before))
        record_before = self.p.backup_report.read_bytes()
        code, fake, image = self.run_backup()
        self.assertEqual(code, 3)
        self.assertEqual(self.p.before_full.read_bytes(), bytes(before))
        self.assertEqual(self.p.backup_report.read_bytes(), record_before)
        self.assertEqual(list(self.backups.glob("nanod-cc5.2-confirm-read-*.bin")), [])
        [evidence] = self.diag.glob("cc5.3-backup-diagnostic-read-*.json")
        self.assertIn(f"the read differs from the locked {self.p.before_full.name}",
                      t.load_json(evidence)["notConfirmedBecause"])

    def test_an_identical_read_needs_a_matching_backup_record(self):
        before = self.read_image()
        self.lock_like_a_cc5_3_rollback(before)
        self.p.backup_report.write_text(json.dumps({"passed": True, "sha256": "0" * 64}), encoding="utf-8")
        code, _, _ = self.run_backup()
        self.assertEqual(code, 3)
        [evidence] = self.diag.glob("cc5.3-backup-diagnostic-read-*.json")
        self.assertTrue(any("does not record" in r for r in t.load_json(evidence)["notConfirmedBecause"]))
        self.assertEqual(self.p.before_full.read_bytes(), before)

    def test_a_locked_backup_without_cc5_2_at_app0_is_never_confirmed(self):
        """A read byte-identical to a locked pair whose backup does not hold cc5.2 at app0 (a pair not made
        by this step): identical, recorded, but still not a valid current backup."""
        before = self.read_image(with_cc52=False)
        self.lock_like_a_cc5_3_rollback(before)
        record_before = self.p.backup_report.read_bytes()
        code, _, image = self.run_backup(with_cc52=False)
        self.assertEqual((code, image), (3, before))
        self.assertEqual((self.p.before_full.read_bytes(), self.p.backup_report.read_bytes()), (before, record_before))
        self.assertEqual(list(self.backups.glob("nanod-cc5.2-confirm-read-*.bin")), [])
        [evidence] = self.diag.glob("cc5.3-backup-diagnostic-read-*.json")
        record = t.load_json(evidence)
        self.assertTrue(record["identicalToLockedBackup"])
        self.assertEqual(record["notConfirmedBecause"], ["app0 of this read does not hold the 1.0.0-cc5.2 image"])

    def test_a_read_without_cc5_2_at_app0_never_replaces_the_backup(self):
        code, fake, image = self.run_backup(with_cc52=False)
        self.assertEqual(code, 3)
        self.assert_pre_cc53_pair_untouched()
        [evidence] = self.diag.glob("cc5.3-backup-diagnostic-read-*.json")
        self.assertIn("app0 of this read does not hold the 1.0.0-cc5.2 image", t.load_json(evidence)["backupLocks"])

    def test_a_failed_run_never_replaces_the_record(self):
        with self.assertRaises(SystemExit):
            self.run_backup(identity=False)
        self.assert_pre_cc53_pair_untouched()
        self.assertEqual(len(list(self.diag.glob("cc5.3-backup-failed-*.json"))), 1)
        with self.assertRaises(SystemExit):
            self.run_backup(verify=False)
        self.assert_pre_cc53_pair_untouched()

    def test_locks(self):
        """cc5.3: its own flash records, rollback records and manifest; never the cc5.2 ones."""
        manifest = self.p.manifest
        self.assertEqual(t.backup_locks(), [])
        manifest.write_text(json.dumps({"installationStatus": "UNFLASHED"}), encoding="utf-8")
        (self.diag / "cc5.3-flash-checks.json").write_text(json.dumps({"writeAttempted": False}), encoding="utf-8")
        self.assertEqual(t.backup_locks(), [])
        for version in t.SUPERSEDED_CC5_VERSIONS:           # earlier releases' manifests do not lock cc5.3
            t.release_manifest(version).write_text(json.dumps({"installationStatus": "SUPERSEDED"}), encoding="utf-8")
        self.assertEqual(t.backup_locks(), [])
        manifest.write_text(json.dumps({"installationStatus": "INSTALLED"}), encoding="utf-8")
        self.assertEqual(t.backup_locks(), ["manifest-1.0.0-cc5.3.json status is INSTALLED"])
        (self.diag / "cc5.3-rollback.json").write_text("{}", encoding="utf-8")
        (self.diag / "cc5.3-flash-checks.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(len(t.backup_locks()), 3)
        self.assertEqual(len(t.backup_locks(diagnostics=self.diag / "elsewhere", manifest=self.diag / "none.json")), 0)
        t.PROFILES["cc5.2"].manifest.write_bytes(self.history[t.PROFILES["cc5.2"].manifest])

    def test_the_cc5_2_locks_are_unchanged(self):
        """pre_cc5_backup_locks: the cc5.2 profile's rules (its records and the 1.0.0-cc5 family)."""
        self.assertEqual(t.pre_cc5_backup_locks(), [
            "cc5-flash-checks.json records a cc5.2 write attempt", "cc5-rollback.json records a cc5.2 rollback",
            "manifest-1.0.0-cc5.2.json status is INSTALLED"])
        family = t.release_manifest("1.0.0-cc5")
        family.write_text(json.dumps({"installationStatus": "SUPERSEDED"}), encoding="utf-8")
        self.assertIn("manifest-1.0.0-cc5.json status is SUPERSEDED", t.pre_cc5_backup_locks())
        self.assertEqual(t.pre_cc5_backup_locks(self.diag / "elsewhere", self.diag / "none.json"), [])
        # cc5.3 records never lock the cc5.2 pair either way (it stays locked by its own history).
        (self.diag / "cc5.3-rollback.json").write_text("{}", encoding="utf-8")
        self.assertNotIn("cc5.3-rollback.json", " ".join(t.pre_cc5_backup_locks()))

    def test_the_history_pair_is_never_this_steps_output(self):
        self.assertNotIn(self.p.before_full.name, t.history_backup_names())
        self.assertIn(t.PROFILES["cc5.2"].before_full.name, t.history_backup_names())
        with mock.patch.object(self.p, "backup_stem", "nanod-cc4-before-cc5"):
            with self.assertRaises(SystemExit) as caught:
                self.run_backup()
        self.assertIn("another release's locked history backup", str(caught.exception))


@needs_tooling
class PrepareFlowTests(HardwareFreeScriptTest):
    """prepare_nanod_cc5_install.main() for the cc5.3 profile from the fresh pre-cc5.3 backup (host files only;
    pinned to cc5.3)."""
    script, capture_evidence, pinned = "prepare_nanod_cc5_install.py", False, "cc5.3"

    def setUp(self):
        super().setUp()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        backups, diag, fw = root / "backups", root / "diagnostics", root / "firmware"
        for folder in (backups, diag, fw):
            folder.mkdir()
        self.backups, self.diag, self.fw = backups, diag, fw
        for name, value in (("BACKUPS", backups), ("DIAGNOSTICS", diag), ("FIRMWARE_OUT", fw),
                            ("ACTIVE_MANIFEST", fw / "manifest.json"),
                            ("ORIGINAL_MANIFEST", backups / t.ORIGINAL_MANIFEST.name)):
            self.patch(t, name, value)
        self.p = t.CURRENT
        self.cc52 = b"\xe9" + b"cc5.2-image" * 300
        self.patch(self.p, "from_image_sha256", hashlib.sha256(self.cc52).hexdigest())
        self.patch(self.p, "from_image_bytes", len(self.cc52))
        self.patch(self.p, "from_expected_sha256", None)
        before = bytearray(b"\x5a" * t.FLASH_BYTES)
        before[0x8000:0x9000] = partition_table(LAYOUT)
        before[0xE000:0x10000] = ota_slot(1) + ota_slot(0)
        original = bytes(before)
        before[t.APP_OFFSET:t.APP_OFFSET + len(self.cc52)] = self.cc52
        before[0x9000:0x9010] = b"nvs changed now!"                 # NVS drifted since the cc5.2 install
        self.before = bytes(before)
        self.candidate = b"\xe9" + b"cc5.3-image" * 400 + t.CC5_VERSION.encode()
        self.p.before_full.write_bytes(self.before)
        self.p.backup_report.write_text(json.dumps({"passed": True, "sha256": hashlib.sha256(self.before).hexdigest(),
                                                    "role": "pre-cc5.3 backup", "file": self.p.before_full.name}),
                                        encoding="utf-8")
        (backups / "original-full.bin").write_bytes(original)
        t.ORIGINAL_MANIFEST.write_text(json.dumps({
            "full_flash_file": "original-full.bin", "full_flash_sha256": hashlib.sha256(original).hexdigest(),
            "partitions": [dict(zip(("name", "type", "subtype", "offset", "size"), row)) for row in LAYOUT]}),
            encoding="utf-8")
        self.p.from_image.write_bytes(self.cc52)
        record = {"firmwareVersion": "1.0.0-cc5.2", "installationStatus": "INSTALLED",
                  "artifacts": {self.p.from_image.name: {"sha256": self.p.from_image_sha256}}}
        self.p.from_record.write_text(json.dumps(record), encoding="utf-8")
        shutil.copyfile(self.p.from_record, t.ACTIVE_MANIFEST)
        self.p.image.write_bytes(self.candidate)
        self.p.manifest.write_text(json.dumps({"firmwareVersion": t.CC5_VERSION, "installationStatus": "UNFLASHED",
                                               "artifacts": {self.p.image.name: {"sha256": t.sha256_bytes(self.candidate)}}}),
                                   encoding="utf-8")
        (backups / "inventory-before.json").write_text(json.dumps({"settings": {"firmwareVersion": "1.0.0-cc5.2"},
                                                                   "capabilities": {"presentation": 4}}), encoding="utf-8")
        # The cc5.2 history pair and records: read-only here.
        old = t.PROFILES["cc5.2"]
        self.history = {old.before_full: b"locked cc4 backup", old.rollback_app: b"cc4 app0"}
        for path, data in self.history.items():
            path.write_bytes(data)

    def tearDown(self):
        for path, data in self.history.items():
            self.assertEqual(path.read_bytes(), data, path.name)

    def prepare(self):
        return self.module.main(["--before-inventory", "inventory-before.json"])

    def refused(self, fragment):
        with self.assertRaises(SystemExit) as caught:
            self.prepare()
        self.assertIn(fragment, str(caught.exception))
        self.assertFalse(self.p.expected_full.exists())
        self.assertFalse(self.p.preparation.exists())

    def test_cc5_3_is_prepared_from_the_fresh_backup(self):
        self.assertEqual(self.prepare(), 0)
        rollback = self.before[t.APP_OFFSET:t.APP_OFFSET + t.APP_SIZE]
        self.assertEqual(self.p.rollback_app.read_bytes(), rollback)
        self.assertTrue(rollback.startswith(self.cc52))
        expected, end = t.assemble_expected(self.before, self.candidate)
        self.assertEqual(self.p.expected_full.read_bytes(), bytes(expected))
        prep = t.load_json(self.p.preparation)
        self.assertEqual((prep["firmwareVersion"], prep["fromVersion"], prep["candidateFile"], prep["beforeFile"]),
                         (t.CC5_VERSION, "1.0.0-cc5.2", "nanod-control-center-1.0.0-cc5.3.bin",
                          "nanod-cc5.2-before-cc5.3-full.bin"))
        self.assertEqual((prep["rollbackFile"], prep["rollbackSha256"], prep["rollbackStartsWithFromImage"]),
                         ("nanod-cc5.2-before-cc5.3-active-app.bin", t.sha256_bytes(rollback), True))
        self.assertEqual((prep["fromImageSha256"], prep["fromRecord"], prep["fromApp0Check"]),
                         (self.p.from_image_sha256, "manifest-cc5.2.json", "not available"))
        self.assertEqual((prep["beforeFirmware"], prep["beforePresentation"], prep["erasedEndExclusive"]),
                         ("1.0.0-cc5.2", 4, end))
        self.assertIn("nvs", prep["unchangedPartitionsSha256"])      # the drifted NVS is kept as read, not rewritten

    def test_the_app0_the_cc5_2_install_verified_is_checked_when_present(self):
        expected = bytearray(self.before)
        self.p.from_expected_full.write_bytes(bytes(expected))
        self.p.from_preparation.write_text(json.dumps({"expectedSha256": t.sha256_bytes(bytes(expected))}),
                                           encoding="utf-8")
        self.assertEqual(self.prepare(), 0)
        self.assertEqual(t.load_json(self.p.preparation)["fromApp0Check"],
                         "app0 byte-identical to nanod-cc5.2-expected-full.bin")
        self.p.preparation.unlink()
        self.p.expected_full.unlink()
        expected[t.APP_OFFSET + 5] ^= 1
        self.p.from_expected_full.write_bytes(bytes(expected))
        self.p.from_preparation.write_text(json.dumps({"expectedSha256": t.sha256_bytes(bytes(expected))}),
                                           encoding="utf-8")
        self.refused("app0 differs from the app0 the 1.0.0-cc5.2 installation verified")

    def test_each_precondition_stops_prepare(self):
        cases = {
            "the before-inventory does not report firmware 1.0.0-cc5.2": lambda: (self.backups / "inventory-before.json")
            .write_text(json.dumps({"settings": {"firmwareVersion": t.CC4_VERSION}, "capabilities": {"presentation": 2}}),
                        encoding="utf-8"),
            "does not match diagnostics/cc5.3-backup.json": lambda: self.p.backup_report.write_text(
                json.dumps({"passed": True, "sha256": "0" * 64}), encoding="utf-8"),
            "manifest.json is not the installed 1.0.0-cc5.2 record": lambda: t.ACTIVE_MANIFEST.write_text(
                json.dumps({"firmwareVersion": t.CC4_VERSION}), encoding="utf-8"),
            "does not have the installed SHA-256": lambda: self.p.from_image.write_bytes(b"\xe9 other"),
            f"is not an UNFLASHED {t.CC5_VERSION} package": lambda: self.p.manifest.write_text(
                json.dumps({"firmwareVersion": t.CC5_VERSION, "installationStatus": "INSTALLED"}), encoding="utf-8"),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment):
                self.setUp_again()
                change()
                self.refused(fragment)

    def setUp_again(self):
        """Rewrite the inputs a previous subtest changed (the history files stay as they were)."""
        self.p.before_full.write_bytes(self.before)
        self.p.backup_report.write_text(json.dumps({"passed": True, "sha256": hashlib.sha256(self.before).hexdigest()}),
                                        encoding="utf-8")
        self.p.from_image.write_bytes(self.cc52)
        shutil.copyfile(self.p.from_record, t.ACTIVE_MANIFEST)
        self.p.manifest.write_text(json.dumps({"firmwareVersion": t.CC5_VERSION, "installationStatus": "UNFLASHED",
                                               "artifacts": {self.p.image.name: {"sha256": t.sha256_bytes(self.candidate)}}}),
                                   encoding="utf-8")
        (self.backups / "inventory-before.json").write_text(json.dumps({"settings": {"firmwareVersion": "1.0.0-cc5.2"},
                                                                        "capabilities": {"presentation": 4}}),
                                                            encoding="utf-8")

    def test_app0_must_hold_cc5_2(self):
        before = bytearray(self.before)
        before[t.APP_OFFSET + 3] ^= 0xFF
        self.p.before_full.write_bytes(bytes(before))
        self.p.backup_report.write_text(json.dumps({"passed": True, "sha256": hashlib.sha256(before).hexdigest()}),
                                        encoding="utf-8")
        self.refused("app0 does not hold the verified 1.0.0-cc5.2 image")

    def test_a_superseded_release_is_never_prepared(self):
        for version in t.SUPERSEDED_CC5_VERSIONS:
            with self.subTest(version):
                self.p.manifest.write_text(json.dumps({"firmwareVersion": version, "installationStatus": "UNFLASHED",
                                                       "artifacts": {}}), encoding="utf-8")
                self.refused(f"not an UNFLASHED {t.CC5_VERSION} package")

    def test_a_profile_that_would_write_another_releases_history_is_refused_first(self):
        """A profile whose backup pair (backup_stem) or expected image (file_tag) is named like the cc5.2
        history stops before anything is read or written; the history files stay as they were."""
        cc52 = t.PROFILES["cc5.2"]
        for name, value in (("backup_stem", cc52.backup_stem), ("file_tag", cc52.tag)):
            with self.subTest(name), mock.patch.object(self.p, name, value):
                self.assertTrue({self.p.rollback_app.name, self.p.expected_full.name, self.p.before_full.name}
                                & t.history_backup_names(self.p))
                self.refused("a file this step writes belongs to another release's history")
                if self.p.rollback_app.name not in t.history_backup_names(self.p):
                    self.assertFalse(self.p.rollback_app.exists())
        # tearDown: the cc5.2 history pair still holds exactly what setUp wrote


@needs_tooling
class BuildAndPackageFixture(HardwareFreeScriptTest):
    """build_nanod_cc5.main() then package_nanod_cc5.main() in a temporary tree. Each script's
    `subprocess` is replaced by a namespace whose run (PlatformIO) and check_output (git) record the
    command and answer like the tools: nothing is built, uploaded or read from git."""
    script, capture_evidence = "package_nanod_cc5.py", False
    PIO_LOG = ("Processing nanofoc_d (platform: espressif32)\n"
               "RAM:   [==        ]  20.1% (used 65848 bytes from 327680 bytes)\n"
               "Flash: [========  ]  77.1% (used 1010000 bytes from 1310720 bytes)\n"
               "========================= [SUCCESS] Took 61.80 seconds =========================\n")
    LS_FILES = ("ls-files", "-z", "--cached", "--others", "--exclude-standard")

    def setUp(self):
        super().setUp()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        work, fw, diag, source = root / "work", root / "firmware", root / "diagnostics", root / "NanoD_RatchetH1"
        for folder in (work, fw, diag, source / "src", source / ".vscode"):
            folder.mkdir(parents=True)
        for name, value in (("WORK", work), ("FIRMWARE_OUT", fw), ("DIAGNOSTICS", diag), ("FIRMWARE_SOURCE", source),
                            ("ACTIVE_MANIFEST", fw / "manifest.json"), ("CC4_MANIFEST", fw / "manifest-cc4.json"),
                            ("BUILT_IMAGE", source / ".pio" / "build" / t.PIO_ENV / "firmware.bin"),
                            ("PIO_VENV", root / "pio-venv"), ("PIO_CORE", root / "pio-core")):
            self.patch(t, name, value)
        self.p = t.CURRENT
        (source / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
        # The TFT pins of the real platformio.ini (the LCD data-line gate reads them; TFT_MISO -1 becomes MOSI).
        (source / "platformio.ini").write_text("[env:nanofoc_d]\nbuild_flags =\n\t-DTFT_MOSI=4\n\t-DTFT_MISO=-1\n"
                                               "\t-DTFT_SCLK=3\n", encoding="utf-8")
        (source / ".vscode" / "settings.json").write_text("{}\n", encoding="utf-8")
        (source / "compile_commands.json").write_text("[]\n", encoding="utf-8")   # generated: never packaged
        (source / "cc_media.d").write_text("cc_media.o: src/cc_media.cpp\n", encoding="utf-8")
        t.CC4_MANIFEST.write_text(json.dumps({
            "firmwareVersion": t.CC4_VERSION, "installationStatus": "INSTALLED",
            "artifacts": {t.CC4_IMAGE.name: {"sha256": t.CC4_IMAGE_SHA256, "bytes": t.CC4_IMAGE_BYTES}},
            "build": {"environment": t.PIO_ENV}, "sourceFiles": {"src/main.cpp": {"sha256": "0" * 64, "bytes": 1}},
            "installation": {"date": "2026-09-21"}}, indent=2) + "\n", encoding="utf-8")
        record = {"firmwareVersion": self.p.from_version, "installationStatus": "INSTALLED",
                  "artifacts": {self.p.from_image.name: {"sha256": self.p.from_image_sha256}},
                  "sourceFiles": {"src/main.cpp": {"sha256": "1" * 64, "bytes": 1}},
                  "installation": {"date": "2026-09-23"}}
        self.cc52_manifest = t.release_manifest(self.p.from_version)
        self.cc52_manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        shutil.copyfile(self.cc52_manifest, t.ACTIVE_MANIFEST)
        self.active = t.ACTIVE_MANIFEST.read_bytes()
        self.image = b"\xe9" + b"cc5.3 firmware " * 2000 + self.p.version.encode("ascii") + b"\0"
        self.commands, self.git_calls, self.envs, self.ignore_flags, self.write_elf = [], [], [], False, True
        self.reattach = True                         # a DMA build links cc_lcd_mosi_reattach (the fix binaries' source)
        self.elf_sizes = list(V5_SIZE_SYMBOLS)       # the 12.4 size symbols firmware.elf carries
        self.log_note = ""                           # extra text the fake PlatformIO writes into the log
        self.build = load_script("build_nanod_cc5.py")
        self.patch(self.build, "subprocess", SimpleNamespace(run=self.fake_platformio, STDOUT="STDOUT", CREATE_NO_WINDOW=0))
        self.call_order = None                       # None: LcdThread::run()'s calls follow the fake ELF (below)
        self.patch(t, "lcd_run_call_order", self.fake_call_order)
        self.patch(self.module, "subprocess", SimpleNamespace(check_output=self.fake_git, CREATE_NO_WINDOW=0))

    def fake_platformio(self, command, env=None, stdout=None, stderr=None, creationflags=0):
        """Answers like PlatformIO: PLATFORMIO_BUILD_FLAGS reach the compiler (R5 compiled out: no ArtDecode
        task name in the image; R3 compiled out: no draw_buf2 in the ELF; CC_BUILD_BINARY n: the marker
        "cc-build-binary:<n>" in the image) and PLATFORMIO_BUILD_DIR moves the output. A DMA build links
        cc_lcd_mosi_reattach while `reattach` is true. `ignore_flags` models flags that never took effect."""
        self.commands.append(list(command))
        self.envs.append(dict(env or {}))
        self.assertEqual(stderr, "STDOUT")
        stdout.write(self.log_note + self.PIO_LOG)
        flags = "" if self.ignore_flags else (env or {}).get("PLATFORMIO_BUILD_FLAGS", "")
        folder = Path(env["PLATFORMIO_BUILD_DIR"]) / t.PIO_ENV if (env or {}).get("PLATFORMIO_BUILD_DIR") \
            else t.BUILT_IMAGE.parent
        folder.mkdir(parents=True, exist_ok=True)
        image = self.image + (b"" if "-DCC_ART_ASYNC=0" in flags else t.R5_IMAGE_MARKER + b"\0") + flags.encode()
        number = re.search(r"-DCC_BUILD_BINARY=(\d+)", flags)
        if number:
            image += t.BUILD_MARKER_PREFIX + number.group(1).encode("ascii") + b"\0"
        (folder / "firmware.bin").write_bytes(image)
        dma = "-DCC_LCD_DMA=0" not in flags
        if self.write_elf:
            (folder / "firmware.elf").write_bytes(fake_elf(["setup", "loop"] + self.elf_sizes
                                                           + ([t.R3_ELF_SYMBOL] if dma else [])
                                                           + ([t.LCD_MOSI_REATTACH_SYMBOL] if dma and self.reattach else [])))
        return SimpleNamespace(returncode=0)

    def fake_call_order(self, elf_path):
        """tooling.lcd_run_call_order on the fake ELF (no objdump): begin, then initDMA in a DMA build (draw_buf2
        linked), the re-attach when it links, startWrite after initDMA. `call_order` replaces it (a list, or an
        exception to raise)."""
        if isinstance(self.call_order, BaseException):
            raise self.call_order
        if self.call_order is not None:
            return list(self.call_order)
        names = t.elf_symbol_names(elf_path)
        dma = t.R3_ELF_SYMBOL in names
        return (["begin"] + (["initDMA"] if dma else []) + (["reattach"] if t.LCD_MOSI_REATTACH_SYMBOL in names else [])
                + (["startWrite"] if dma else []))

    def fake_git(self, command, creationflags=0):
        self.git_calls.append(list(command))
        self.assertEqual(command[:5], ["git", "-c", f"safe.directory={t.FIRMWARE_SOURCE.as_posix()}", "-C",
                                       str(t.FIRMWARE_SOURCE)])
        if tuple(command[5:]) == self.LS_FILES:
            return b"src/main.cpp\0platformio.ini\0.vscode/settings.json\0compile_commands.json\0cc_media.d\0"
        if command[5:] == ["rev-parse", "HEAD"]:
            return b"0123456789abcdef0123456789abcdef01234567\n"
        raise AssertionError(f"git {command[5:]} is not a read")



@needs_tooling
class BuildAndPackageFlowTests(BuildAndPackageFixture):
    """Binary A (the default --binary): the release's own names, the project's own build folder."""

    def test_build_and_package_write_an_unflashed_release_and_leave_manifest_json(self):
        self.assertEqual(self.build.main([]), 0)
        [command] = self.commands
        self.assertEqual(command[1:], ["-m", "platformio", "run", "-d", str(t.FIRMWARE_SOURCE), "-e", t.PIO_ENV])
        build = t.load_json(self.p.build_report)
        self.assertEqual((build["version"], build["accepted"], build["problems"], build["containsVersion"]),
                         (self.p.version, True, [], True))
        image = t.BUILT_IMAGE.read_bytes()
        self.assertEqual((build["sha256"], build["bytes"], build["ramUsedBytes"], build["flashUsedBytes"]),
                         (t.sha256_bytes(image), len(image), 65848, 1010000))
        # Binary A of the 12.6 ladder: the plain project build, no flags, the project's own build folder.
        self.assertEqual((build["binary"], build["buildFlags"], build["buildDir"], build["pipeline"]),
                         ("A", [], None, t.LCD_BINARIES["A"]))
        self.assertEqual(build["pipelineEvidence"]["imageHoldsR5Task"], True)
        self.assertEqual(build["pipelineEvidence"]["elfLinksR3Buffer"], True)
        self.assertNotIn("PLATFORMIO_BUILD_FLAGS", self.envs[0])
        self.assertNotIn("PLATFORMIO_BUILD_DIR", self.envs[0])
        self.assertIn("[SUCCESS]", self.p.build_log.read_text(encoding="utf-8"))

        self.assertEqual(self.module.main([]), 0)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), self.active)                   # manifest.json untouched
        record = t.load_json(self.p.manifest)
        self.assertEqual((record["firmwareVersion"], record["installationStatus"], record["upgradesFrom"],
                          record["installedRecordBeforeUpgrade"]),
                         (self.p.version, "UNFLASHED", self.p.from_version, self.p.from_record.name))
        self.assertEqual(record["artifacts"][self.p.image.name]["sha256"], build["sha256"])
        self.assertFalse(record["validation"]["flashWriteIssued"])
        self.assertEqual(record["expectedCapabilities"]["artwork2"], t.artwork2_capability())
        # .vscode/, the compilation database and root dependency files are left out
        self.assertEqual(sorted(record["sourceFiles"]), ["platformio.ini", "src/main.cpp"])
        self.assertEqual((record["changedFromPreviousCc5"]["from"], record["changedFromPreviousCc5"]["added"],
                          record["changedFromPreviousCc5"]["modified"]),
                         (self.p.from_version, ["platformio.ini"], ["src/main.cpp"]))
        self.assertIn(f"diagnostics/{self.p.build_report.name}", record["gates"])
        self.assertEqual(self.p.image.read_bytes(), image)
        self.assertEqual((record["binary"]["name"], record["binary"]["role"], record["binary"]["buildFlags"]),
                         ("A", "release candidate", []))
        self.assertEqual(record["binary"]["ladder"], {"A": "manifest-1.0.0-cc5.4.json", "B": "manifest-1.0.0-cc5.4-B.json",
                                                      "C": "manifest-1.0.0-cc5.4-C.json", "D": "manifest-1.0.0-cc5.4-D.json",
                                                      "E": "manifest-1.0.0-cc5.4-E.json"})
        self.assertTrue(build["lcdMosiGate"]["passed"])                               # A's pipeline with the re-attach
        with zipfile.ZipFile(self.p.source_zip) as bundle:
            self.assertEqual(sorted(bundle.namelist()), ["NanoD_RatchetH1/platformio.ini", "NanoD_RatchetH1/src/main.cpp"])
        self.assertEqual(self.p.from_record.read_bytes(), self.active)                  # the kept cc5.2 record
        # Packaging never changes an installed record: cc5.2 stays INSTALLED, byte for byte, until
        # finalize_nanod_cc5.py records cc5.3 (FinalizeFlowTests).
        self.assertEqual(self.cc52_manifest.read_bytes(), self.active)
        self.assertEqual(list(self.cc52_manifest.parent.glob("manifest-1.0.0-cc5.2.superseded-*")), [])
        self.assertEqual({tuple(c[5:]) for c in self.git_calls}, {self.LS_FILES, ("rev-parse", "HEAD")})

    def test_an_image_without_the_version_string_is_rejected_by_build_and_package(self):
        self.image = self.image.replace(self.p.version.encode("ascii"), self.p.from_version.encode("ascii"))
        self.assertEqual(self.build.main([]), 1)
        build = t.load_json(self.p.build_report)
        self.assertFalse(build["accepted"] or build["containsVersion"])
        self.assertEqual(build["problems"], [f"version string {self.p.version} not found in the image"])
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn(f"does not record an accepted {self.p.version} build", str(caught.exception))
        # Even a record that accepts exactly these bytes does not get them packaged: package checks the image too.
        t.write_json_evidence(self.p.build_report, {**build, "accepted": True, "problems": []})
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn(f"version string {self.p.version} not found in the image", str(caught.exception))
        self.assertFalse(self.p.manifest.exists() or self.p.image.exists() or self.p.from_record.exists())
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), self.active)
        self.assertEqual(t.load_json(self.cc52_manifest)["installationStatus"], "INSTALLED")

    def test_a_manifest_json_changed_during_packaging_stops_it(self):
        self.assertEqual(self.build.main([]), 0)
        supersede = self.module.supersede_earlier_releases

        def supersede_then_touch(p=None):
            lines = supersede(p)
            t.ACTIVE_MANIFEST.write_bytes(self.active + b"\n")          # something rewrote manifest.json meanwhile
            return lines

        self.patch(self.module, "supersede_earlier_releases", supersede_then_touch)
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn("manifest.json changed during packaging; that must never happen", str(caught.exception))


@needs_tooling
class FinalizeFlowBase(HardwareFreeScriptTest):
    """finalize_nanod_cc5.main() against fake Stage 10 evidence in a temporary folder: the folders, the
    helpers and (records) the cc5.2 -> cc5.3 evidence, pinned to cc5.3. FinalizeFlowTests runs the cc5.3
    cases; Cc54FinalizeFlowTests overrides records with the cc5.3 -> cc5.4 evidence (CURRENT)."""
    script, capture_evidence, pinned = "finalize_nanod_cc5.py", False, "cc5.3"
    BASE = 1_700_000_000.0          # file times: preparation < flash < post-flash evidence
    FLASH_STARTED, FLASH_FINISHED = "20260923T070000Z", "20260923T070200Z"

    def setUp(self):
        super().setUp()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        app = self.root / "nanod-desktop-demo"
        self.backups, self.diag, self.fw = app / "backups", app / "diagnostics", app / "firmware"
        paths = {"APP": app, "BACKUPS": self.backups, "DIAGNOSTICS": self.diag, "FIRMWARE_OUT": self.fw}
        paths.update({name: self.fw / getattr(t, name).name
                      for name in ("CC5_IMAGE", "CC5_MANIFEST", "CC4_MANIFEST", "ACTIVE_MANIFEST")})
        paths.update({name: self.diag / getattr(t, name).name
                      for name in ("BACKUP_REPORT", "PREPARATION", "FLASH_CHECKS", "DEVICE_CHECKS", "LEASE_CHECKS",
                                   "ROLLBACK_REPORT", "INSTALLATION", "BOOT_ENTRY")})
        for name, value in paths.items():
            self.patch(t, name, value)
        for name in paths:  # nothing the script reads or writes can be outside the temporary folder
            self.assertTrue(Path(getattr(t, name)).is_relative_to(self.root), name)
        self.image, self.source = b"\xe9" + b"cc5" * 400 + t.CC5_VERSION.encode(), b"PK fake source archive"
        self.build()

    def write(self, path, data, at=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        at = self.BASE if at is None else at
        os.utime(path, (at, at))
        return path

    def folder(self, path, files, at, folder_at=None):
        """A work folder like a rollback leaves: `files` inside at time `at`, the folder itself at `folder_at`."""
        for name in files:
            self.write(Path(path) / name, b"\x5a" * 16, at)
        at = at if folder_at is None else folder_at
        os.utime(path, (at, at))     # after the files: adding them moved the folder's own time
        return path

    @staticmethod
    def profiles():
        """The shape DeviceBridge._connect writes: one object mapping each name to its full profile."""
        return {f"PROFILE {n}": {"version": 2, "name": f"PROFILE {n}", "desc": "", "ledEnable": True,
                                 "ledBrightness": 100 - n, "pointer": 16777215} for n in range(10)}

    def records(self):
        sha = t.sha256_bytes
        profiles = self.profiles()
        before_name, after_name = "control-center-inventory-before.json", "control-center-inventory-after.json"
        cc4_manifest = {"firmwareVersion": t.CC4_VERSION, "installationStatus": "INSTALLED",
                        "artifacts": {t.CC4_IMAGE.name: {"sha256": t.CC4_IMAGE_SHA256}}}
        # The installed cc5.2 record, kept by package_nanod_cc5.py as manifest-cc5.2.json (== manifest.json).
        cc52_record = {"firmwareVersion": "1.0.0-cc5.2", "installationStatus": "INSTALLED",
                       "artifacts": {t.CURRENT.from_image.name: {"sha256": t.CURRENT.from_image_sha256}}}
        B = self.BASE
        return {
            "image": (t.CC5_IMAGE, self.image, B),
            "source": (self.fw / t.CC5_SOURCE_ZIP.name, self.source, B),
            "cc5_manifest": (t.CC5_MANIFEST, {"firmwareVersion": t.CC5_VERSION, "installationStatus": "UNFLASHED",
                                              "artifacts": {t.CC5_IMAGE.name: {"sha256": sha(self.image)},
                                                            t.CC5_SOURCE_ZIP.name: {"sha256": sha(self.source)}},
                                              "sourceFiles": {"src/main.cpp": "x"}, "validation": {"flashWriteIssued": False}}, B),
            "cc4_manifest": (t.CC4_MANIFEST, cc4_manifest, B),
            "cc52_record": (self.fw / "manifest-cc5.2.json", cc52_record, B),
            "active_manifest": (t.ACTIVE_MANIFEST, dict(cc52_record), B),
            # The installed cc5.2 release manifest: packaging leaves it INSTALLED (== manifest-cc5.2.json).
            "cc52_release": (self.fw / "manifest-1.0.0-cc5.2.json", dict(cc52_record), B),
            # Step 3's ROM bootloader entry, before the backup and the install.
            "boot_entry": (t.BOOT_ENTRY, {"startedUtc": "20260923T064000Z", "touchSent": True, "passed": True,
                                          "romPort": "FAKEROM"}, B),
            "backup": (t.BACKUP_REPORT, {"passed": True, "sha256": "b" * 64}, B),
            "prep": (t.PREPARATION, {"firmwareVersion": t.CC5_VERSION, "fromVersion": "1.0.0-cc5.2",
                                     "beforeSha256": "b" * 64, "candidateSha256": sha(self.image),
                                     "rollbackSha256": "r" * 64, "beforeInventory": before_name,
                                     "preparedUtc": "20260923T065500Z", "flashWritten": False}, B),
            "before": (self.backups / before_name, {"settings": {"firmwareVersion": "1.0.0-cc5.2", "brightness": 3},
                                                    "profiles": profiles, "current": "PROFILE 0",
                                                    "capabilities": {"presentation": 4,
                                                                     "artwork": dict(t.EXPECTED_ARTWORK_CAPABILITY)}}, B),
            "flash": (t.FLASH_CHECKS, {"startedUtc": self.FLASH_STARTED, "finishedUtc": self.FLASH_FINISHED,
                                       "port": "FAKEROM", "candidateSha256": sha(self.image),
                                       "identityVerified": True, "preWriteVerified": True, "writeAttempted": True,
                                       "flashWritten": True, "postWriteVerified": True, "resetAttempted": True,
                                       "reset": True, "restoreAttempted": False,
                                       "outcome": "INSTALLED_VERIFIED_RESET"}, B + 100),
            "after": (self.backups / after_name, {"settings": {"firmwareVersion": t.CC5_VERSION, "brightness": 3},
                                                  "profiles": profiles, "current": "PROFILE 0",
                                                  "capabilities": {"presentation": 4,
                                                                   "artwork": dict(t.EXPECTED_ARTWORK_CAPABILITY),
                                                                   "artwork2": t.artwork2_capability()}}, B + 200),
            "device": (t.DEVICE_CHECKS, {"startedUtc": "20260923T071000Z", "finishedUtc": "20260923T071500Z",
                                         "port": "FAKEAPP", "passed": True, "portClosed": True, "failures": [],
                                         "inventory": str(self.backups / after_name),
                                         "capabilities": {"presentation": 4},
                                         "checks": [{"check": f"inventory: firmware {t.CC5_VERSION}", "passed": True,
                                                     "detail": t.CC5_VERSION}],
                                         "gates": {name: True for name in self.module.REQUIRED_GATES},
                                         "sections": {}, "fourControls": []}, B + 210),
            "lease": (t.LEASE_CHECKS, {"startedUtc": "20260923T072000Z", "passed": True, "failures": [],
                                       "artwork2": {"mediaOnlyDoesNotRenew": True, "framesDuringMediaTransfers": True}},
                      B + 300),
            "validation": (self.diag / "validation.json", {"hardware_acceptance": "cc4 accepted."}, B),
        }

    def build(self, drop=(), times=None, **changes):
        """Fresh evidence; `changes` merge into one record each, `drop` omits files, `times` moves them."""
        shutil.rmtree(self.root / "nanod-desktop-demo", ignore_errors=True)
        for key, (path, data, at) in self.records().items():
            if key in drop:
                continue
            if isinstance(data, dict):
                data = {**data, **changes.get(key, {})}
            self.write(path, data, (times or {}).get(key, at))

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime)
                for p in sorted(self.root.rglob("*")) if p.is_file()}

    def assert_refused(self, fragment, *argv):
        before = self.snapshot()
        with self.assertRaises(SystemExit) as caught:
            self.module.main(list(argv))
        message = str(caught.exception)
        self.assertIn("Nothing was recorded", message)
        self.assertIn(fragment, message)
        self.assertEqual(self.snapshot(), before)  # not a byte and not a file time changed
        return message


@needs_tooling
class FinalizeFlowTests(FinalizeFlowBase):
    """finalize_nanod_cc5.main() for the cc5.2 -> cc5.3 evidence (pinned to cc5.3)."""

    def test_verified_install_is_recorded_with_evidence_hashes(self):
        evidence_files = (t.BACKUP_REPORT, t.PREPARATION, t.FLASH_CHECKS, t.DEVICE_CHECKS, t.LEASE_CHECKS,
                          self.backups / "control-center-inventory-before.json",
                          self.backups / "control-center-inventory-after.json")
        expected = {p.name: t.sha256_file(p) for p in evidence_files}
        old_validation = (self.diag / "validation.json").read_bytes()
        self.assertEqual(self.module.main(["--companion-tests", "900", "--light-assertions", "12"]), 0)
        report = t.load_json(t.INSTALLATION)
        self.assertEqual(report["evidenceSha256"], expected)
        self.assertEqual((report["flashOutcome"], report["resetConfirmation"]),
                         ("INSTALLED_VERIFIED_RESET", "read_mac --after hard_reset confirmed"))
        self.assertEqual((report["beforeInventory"], report["afterInventory"], report["settingsChanged"]),
                         ("control-center-inventory-before.json", "control-center-inventory-after.json", ["firmwareVersion"]))
        self.assertEqual(report["bootEntryEvidence"], [t.BOOT_ENTRY.name])   # step 3's entry is not a rollback
        manifest = t.load_json(t.CC5_MANIFEST)
        self.assertEqual(manifest["installationStatus"], "INSTALLED")
        self.assertEqual(manifest["validation"]["evidenceSha256"], expected)
        self.assertEqual(manifest["validation"]["companionTestsPassed"], 900)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), t.CC5_MANIFEST.read_bytes())
        self.assertEqual((self.diag / "validation-before-cc5.3.json").read_bytes(), old_validation)
        validation = t.load_json(self.diag / "validation.json")
        self.assertEqual(validation["cc5.3"]["evidenceSha256"], expected)
        self.assertEqual((validation["cc5.3"]["firmwareVersion"], validation["cc5.3"]["fromVersion"]),
                         (t.CC5_VERSION, "1.0.0-cc5.2"))
        self.assertNotIn("cc5", validation)                  # the cc5.2 key is never written by cc5.3
        self.assertEqual(validation["automated_tests"]["count"], 900)
        self.assertEqual((report["firmwareVersion"], report["fromVersion"], report["desktop"]["bundle"]),
                         (t.CC5_VERSION, "1.0.0-cc5.2", "desktop-dist-v4"))
        self.assertEqual(t.load_json(self.fw / "manifest-cc5.2.json")["installationStatus"], "INSTALLED")  # untouched
        # Last, the installed cc5.2 release manifest became SUPERSEDED; its INSTALLED file is kept byte-exact.
        installed_bytes = (self.fw / "manifest-cc5.2.json").read_bytes()
        cc52 = t.load_json(self.fw / "manifest-1.0.0-cc5.2.json")
        self.assertEqual((cc52["installationStatus"], cc52["statusBeforeSupersede"], cc52["supersededBy"],
                          cc52["installedRecord"], cc52["installedRecordSha256"]),
                         ("SUPERSEDED", "INSTALLED", t.CC5_VERSION, "manifest-cc5.2.json",
                          t.sha256_bytes(installed_bytes)))
        self.assertIn("installed and finalized", cc52["history"])
        [kept] = self.fw.glob("manifest-1.0.0-cc5.2.superseded-*.json")
        self.assertEqual(kept.read_bytes(), installed_bytes)
        self.assertIn("manifest-1.0.0-cc5.2.json: INSTALLED -> SUPERSEDED", self.out.getvalue())
        # A re-run finds manifest.json == the INSTALLED cc5.3 record and records again.
        self.assertEqual(self.module.main([]), 0)
        self.assertEqual(len(list(self.fw.glob("manifest-1.0.0-cc5.2.superseded-*.json"))), 1)   # superseded once
        self.assertEqual(len(list(self.diag.glob("cc5.3-installation.superseded-*.json"))), 1)
        self.assertEqual((self.diag / "validation-before-cc5.3.json").read_bytes(), old_validation)

    def test_a_cc5_2_manifest_that_is_not_the_kept_record_is_left_as_it_is(self):
        """finalize supersedes the upgraded-from manifest only while it is INSTALLED and byte-identical
        to the kept record (manifest-cc5.2.json); otherwise it records cc5.3 and leaves that file alone."""
        self.build(cc52_release={"installation": {"date": "2026-09-22"}})
        path = self.fw / "manifest-1.0.0-cc5.2.json"
        before = path.read_bytes()
        self.assertEqual(self.module.main([]), 0)
        self.assertEqual(t.load_json(t.CC5_MANIFEST)["installationStatus"], "INSTALLED")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.fw.glob("manifest-1.0.0-cc5.2.superseded-*")), [])
        self.assertIn("manifest-1.0.0-cc5.2.json left INSTALLED (not the INSTALLED record kept as manifest-cc5.2.json)",
                      self.out.getvalue())
        for drop in (("cc52_release",), ("cc52_release", "cc52_record")):
            with self.subTest(drop=drop):
                self.build(drop=drop, **({"active_manifest": {}} if "cc52_record" in drop else {}))
                if "cc52_record" in drop:
                    self.assert_refused("manifest.json is not the installed 1.0.0-cc5.2 record")
                    continue
                self.assertEqual(self.module.main([]), 0)
                self.assertIn("manifest-1.0.0-cc5.2.json not present; nothing to supersede", self.out.getvalue())

    def test_a_rollback_after_the_install_is_refused(self):
        """Either path's record: cc5.3-rollback*.json (cc5.3 -> cc5.2) or cc5-rollback*.json (cc5 -> cc4)."""
        late, B = "20260923T073000Z", self.BASE
        cases = (("cc5.3-rollback.json", {"startedUtc": late, "outcome": "ROLLED_BACK_VERIFIED_RESET"}, B + 400),
                 ("cc5.3-rollback.superseded-20260923T073500Z.json", {"startedUtc": late, "outcome": "RECORDS_ONLY"}, B + 400),
                 ("cc5.3-rollback.json", {"startedUtc": late, "outcome": "STOPPED_BEFORE_WRITE"}, B + 50),
                 ("cc5.3-rollback.json", b"{not json", B + 50),
                 ("cc5-rollback.json", {"startedUtc": late, "outcome": "ROLLED_BACK_VERIFIED_RESET"}, B + 400),
                 ("cc5-rollback.superseded-20260923T073500Z.json", {"startedUtc": late, "outcome": "RECORDS_ONLY"}, B + 400),
                 ("cc5-rollback.json", {"startedUtc": late, "outcome": "STOPPED_BEFORE_WRITE"}, B + 50),  # stamp only
                 ("cc5-rollback.json", {"outcome": "ROLLED_BACK_VERIFIED_RESET"}, B + 100),               # same file time
                 ("cc5-rollback.json", b"{not json", B + 50))
        for name, data, at in cases:
            with self.subTest(name=name, at=at - B):
                self.build()
                self.write(self.diag / name, data, at)
                self.assert_refused(name)
        for at in (B + 400, B + 50):                       # by file time, or by the stamp in its name
            for prefix in ("cc5", "cc5.3"):
                with self.subTest("manifest.json restored by a rollback", at=at - B, prefix=prefix):
                    self.build()
                    self.write(self.fw / f"manifest-at-{prefix}-rollback-20260923T073000Z.json", {"firmwareVersion": "x"}, at)
                    self.assert_refused(f"manifest-at-{prefix}-rollback-20260923T073000Z.json")

    def test_a_rollback_without_a_rollback_record_is_refused(self):
        """The manual path (and a stopped script run) can leave no cc5-rollback.json at all.

        In each case the post-flash checks from before the rollback are still passed and newer
        than cc5-flash-checks.json, and manifest.json is still the cc4 record, so only the traces
        the rollback left can stop finalize from recording cc5 over a knob running cc4 or a
        partly written app0.
        """
        B, late = self.BASE, "20260923T073000Z"
        manual = self.backups / f"cc5-manual-rollback-{late}"
        region_files = ("region-app0.bin", "region-otadata.bin", "current-partition-table.bin", "current-otadata.bin")
        cases = {
            # Manual blocks 1-2, then the retry rule stopped after a second failed write: knob left in ROM.
            "manual rollback stopped after a failed write": lambda: self.folder(manual, region_files, B + 400),
            # Manual blocks 1-4 reset into cc4, but --records-only exited 1: no cc5-rollback.json.
            "manual rollback reset, records not restored": lambda: (
                self.write(self.diag / f"cc5-usb-boot-entry-{late}.json",
                           {"startedUtc": late, "alreadyInBootloader": False, "touchSent": True}, B + 390),
                self.folder(manual, region_files, B + 400)),
            # Folder and files carry old times, but the folder's name says when block 1 ran.
            "manual rollback folder named after the install": lambda: self.folder(manual, region_files, B + 50),
            # Folder time old, a file inside new (block 1 re-run into an existing folder).
            "manual rollback folder with a new file": lambda: self.folder(
                self.backups / "cc5-manual-rollback-x", region_files, B + 400, folder_at=B + 50),
            # rollback_nanod_cc5.py work folder and esptool logs, its record missing.
            "rollback script work folder": lambda: self.folder(self.backups / f"cc5-rollback-{late}",
                                                               ("current-partitions.bin",), B + 400),
            "rollback script esptool log": lambda: self.write(self.diag / "cc5-rollback-write.log", b"fatal", B + 400),
            "section 3 partition read": lambda: self.write(self.backups / "nanod-current-partitions.bin", b"\xaa" * 16,
                                                           B + 400),
            # The same traces of the cc5.3 -> cc5.2 path (RECOVERY.md section 6).
            "cc5.3 manual rollback stopped after a failed write": lambda: self.folder(
                self.backups / f"cc5.3-manual-rollback-{late}", region_files, B + 400),
            "cc5.3 manual rollback folder named after the install": lambda: self.folder(
                self.backups / f"cc5.3-manual-rollback-{late}", region_files, B + 50),
            "cc5.3 rollback script work folder": lambda: self.folder(self.backups / f"cc5.3-rollback-{late}",
                                                                     ("current-partitions.bin",), B + 400),
            "cc5.3 rollback script esptool log": lambda: self.write(self.diag / "cc5.3-rollback-write.log", b"fatal",
                                                                    B + 400),
        }
        for label, make in cases.items():
            with self.subTest(label):
                self.build()
                make()
                self.assertFalse(list(self.diag.glob("cc5-rollback*.json")) + list(self.diag.glob("cc5.3-rollback*.json")))
                message = self.assert_refused("a rollback was made or started after the install")
                self.assertIn("cc5.3 cannot be recorded from this evidence", message)
        with self.subTest("both traces are named"):
            self.build()
            cases["manual rollback reset, records not restored"]()
            message = self.assert_refused(f"cc5-manual-rollback-{late}")
            self.assertIn(f"cc5-usb-boot-entry-{late}.json", message)

    def test_a_bootloader_entry_after_the_install_is_refused(self):
        """Only a rollback puts the knob back into the ROM bootloader after the install."""
        B, late = self.BASE, "20260923T073000Z"
        cases = (
            (f"cc5-usb-boot-entry-{late}.json", {"startedUtc": late, "touchSent": True}, B + 400),
            ("cc5-usb-boot-entry-copy.json", {"startedUtc": late, "touchSent": True}, B + 50),   # recorded stamp only
            (f"cc5-usb-boot-entry-{late}.json", {"alreadyInBootloader": True}, B + 50),         # name stamp only
            ("cc5-usb-boot-entry-copy.json", {"touchSent": False}, B + 100),                    # same file time
            ("cc5-usb-boot-entry-copy.json", b"{not json", B + 400),                            # unreadable, new
        )
        for name, data, at in cases:
            with self.subTest(name=name, at=at - B):
                self.build()
                self.write(self.diag / name, data, at)
                self.assertFalse(list(self.diag.glob("cc5-rollback*.json")))
                self.assert_refused(f"{name} records a ROM bootloader entry after the install")

    def test_rollback_manifest_states_are_refused(self):
        self.build(cc5_manifest={"installationStatus": "ROLLED_BACK"})
        self.assert_refused("status is ROLLED_BACK")
        self.build(cc5_manifest={"installationStatus": "INSTALLED"})       # manifest.json is the cc5.2 record again
        self.assert_refused("manifest.json is not the installed cc5.3 record although manifest-1.0.0-cc5.3.json is "
                            "INSTALLED (a rollback restores the cc5.2 record)")
        self.build(active_manifest={"firmwareVersion": t.CC5_VERSION})
        self.assert_refused("manifest.json is not the installed 1.0.0-cc5.2 record (manifest-cc5.2.json)")
        self.build(active_manifest={"firmwareVersion": t.CC4_VERSION, "installationStatus": "INSTALLED",
                                    "artifacts": {t.CC4_IMAGE.name: {"sha256": t.CC4_IMAGE_SHA256}}})   # a cc4 rollback
        self.assert_refused("manifest.json is not the installed 1.0.0-cc5.2 record")
        self.build(drop=("active_manifest",))
        self.assert_refused("manifest.json is not the installed 1.0.0-cc5.2 record")
        self.build(drop=("cc52_record",))                                 # never packaged: no cc5.2 record kept
        self.assert_refused("manifest.json is not the installed 1.0.0-cc5.2 record")

    def test_a_rollback_before_this_install_is_allowed(self):
        B, early = self.BASE, "20260923T064500Z"
        self.build()
        self.write(self.diag / "cc5-rollback.superseded-20260923T065000Z.json",
                   {"startedUtc": early, "finishedUtc": "20260923T065000Z",
                    "outcome": "ROLLED_BACK_VERIFIED_RESET"}, B + 50)
        self.write(self.fw / "manifest-at-cc5-rollback-20260923T064900Z.json", {"firmwareVersion": "x"}, B + 50)
        self.folder(self.backups / f"cc5-manual-rollback-{early}", ("region-app0.bin",), B + 50)
        self.folder(self.backups / f"cc5-rollback-{early}", ("current-partitions.bin",), B + 50)
        self.write(self.diag / "cc5-rollback-identity.log", b"ok", B + 50)
        self.write(self.diag / f"cc5-usb-boot-entry-{early}.json", {"startedUtc": early}, B + 50)
        self.write(self.backups / "nanod-current-partitions.bin", b"\xaa" * 16, B + 50)
        # An earlier cc5.3 attempt, restored to cc5.2 before this install, is history too.
        self.write(self.diag / "cc5.3-rollback.superseded-20260923T065000Z.json",
                   {"startedUtc": early, "finishedUtc": "20260923T065000Z", "outcome": "ROLLED_BACK_VERIFIED_RESET"}, B + 50)
        self.write(self.fw / "manifest-at-cc5.3-rollback-20260923T064900Z.json", {"firmwareVersion": "x"}, B + 50)
        self.folder(self.backups / f"cc5.3-manual-rollback-{early}", ("region-app0.bin",), B + 50)
        self.folder(self.backups / f"cc5.3-rollback-{early}", ("current-partitions.bin",), B + 50)
        self.write(self.diag / "cc5.3-rollback-identity.log", b"ok", B + 50)
        self.assertEqual(self.module.main([]), 0)
        self.assertEqual(t.load_json(t.CC5_MANIFEST)["installationStatus"], "INSTALLED")
        self.assertEqual(t.load_json(t.INSTALLATION)["bootEntryEvidence"],
                         sorted([t.BOOT_ENTRY.name, f"cc5-usb-boot-entry-{early}.json"]))

    def test_the_1_0_0_cc5_install_and_rollback_before_this_install_are_history(self):
        """The real sequence of 2026-09-23: 1.0.0-cc5 installed, reset in the stress, rolled back to cc4.

        Every trace of that earlier install and its rollback predates this 1.0.0-cc5.1 install
        (by file time and by UTC stamp), so finalize records cc5.1. The same traces written
        after this install would refuse it (test_a_rollback_after_the_install_is_refused).
        """
        B, early = self.BASE, "20260923T063000Z"       # the 1.0.0-cc5 window, before FLASH_STARTED
        self.build()
        self.write(self.diag / f"cc5-flash-checks.superseded-{early}.json",
                   {"startedUtc": "20260923T061300Z", "writeAttempted": True, "flashWritten": True,
                    "outcome": "INSTALLED_VERIFIED_RESET", "candidateSha256": "c123f9dc" + "0" * 56}, B + 20)
        self.write(self.diag / f"cc5-device-checks.superseded-{early}.json",
                   {"passed": False, "failures": ["run completed"]}, B + 21)
        self.write(self.diag / "cc5-rollback.json", {"startedUtc": "20260923T063500Z", "finishedUtc": "20260923T063620Z",
                                                     "outcome": "ROLLED_BACK_VERIFIED_RESET"}, B + 30)
        self.write(self.diag / "cc5-usb-boot-entry-20260923T063553Z.json", {"startedUtc": "20260923T063553Z"}, B + 25)
        self.write(self.fw / "manifest-at-cc5-rollback-20260923T063620Z.json", {"firmwareVersion": t.CC4_VERSION}, B + 30)
        self.folder(self.backups / "cc5-rollback-20260923T063555Z", ("current-partitions.bin",), B + 28)
        for step in ("identity", "write", "verify-app0", "verify-full", "reset"):
            self.write(self.diag / f"cc5-rollback-{step}.log", b"ok", B + 29)
        self.write(self.fw / "manifest-1.0.0-cc5.json", {"firmwareVersion": "1.0.0-cc5", "installationStatus": "SUPERSEDED",
                                                          "supersededBy": t.CC5_VERSION}, B + 40)
        # Then 1.0.0-cc5.1: installed, its HMI hung in the stress, rolled back; also before this install.
        cc51 = "20260923T064800Z"
        self.write(self.diag / f"cc5-flash-checks.superseded-{cc51}.json",
                   {"startedUtc": "20260923T064000Z", "writeAttempted": True, "flashWritten": True,
                    "outcome": "INSTALLED_VERIFIED_RESET", "candidateSha256": "f75ac481" + "0" * 56}, B + 41)
        self.write(self.diag / f"cc5-device-checks.superseded-{cc51}.json",
                   {"passed": False, "failures": ["run completed"]}, B + 42)
        self.write(self.diag / "cc5-usb-boot-entry-20260923T064650Z.json", {"startedUtc": "20260923T064650Z"}, B + 42)
        self.write(self.diag / f"cc5-rollback.superseded-{cc51}.json",
                   {"startedUtc": "20260923T064700Z", "finishedUtc": cc51, "outcome": "ROLLED_BACK_VERIFIED_RESET"},
                   B + 43)
        self.write(self.fw / "manifest-1.0.0-cc5.1.json", {"firmwareVersion": "1.0.0-cc5.1",
                                                            "installationStatus": "SUPERSEDED",
                                                            "supersededBy": t.CC5_VERSION}, B + 44)
        # Then 1.0.0-cc5.2: installed, checked and finalized under its own names (cc5-*.json), all before.
        cc52 = "20260923T065000Z"
        for name, record in (("cc5-flash-checks.json", {"startedUtc": "20260923T064900Z", "writeAttempted": True,
                                                        "outcome": "INSTALLED_VERIFIED_RESET"}),
                             ("cc5-device-checks.json", {"passed": True, "gates": {}}),
                             ("cc5-lease-checks.json", {"passed": True}),
                             ("cc5-installation.json", {"firmwareVersion": "1.0.0-cc5.2"}),
                             (f"cc5-usb-boot-entry-{cc52}.json", {"startedUtc": cc52})):
            self.write(self.diag / name, record, B + 45)
        self.write(self.fw / "manifest-1.0.0-cc5.2.json", {"firmwareVersion": "1.0.0-cc5.2", "installationStatus": "SUPERSEDED",
                                                            "statusBeforeSupersede": "INSTALLED"}, B + 46)
        history = {p.name: p.read_bytes() for p in self.diag.glob("cc5-*.json")}
        self.assertEqual(self.module.main([]), 0)
        self.assertEqual({p.name: p.read_bytes() for p in self.diag.glob("cc5-*.json")}, history)   # untouched
        self.assertEqual(t.load_json(t.CC5_MANIFEST)["installationStatus"], "INSTALLED")
        self.assertEqual(t.load_json(t.INSTALLATION)["firmwareVersion"], t.CC5_VERSION)
        self.assertEqual(t.load_json(self.fw / "manifest-1.0.0-cc5.json")["installationStatus"], "SUPERSEDED")
        self.assertEqual(t.load_json(self.fw / "manifest-1.0.0-cc5.1.json")["installationStatus"], "SUPERSEDED")

    def test_post_flash_evidence_is_required(self):
        B = self.BASE
        cases = {
            "flash evidence (cc5.3-flash-checks.json) is missing": dict(drop=("flash",)),
            "post-flash device checks (cc5.3-device-checks.json) is missing": dict(drop=("device",)),
            "post-flash lease checks (cc5.3-lease-checks.json) is missing": dict(drop=("lease",)),
            "cc5.3-preparation.json does not prepare 1.0.0-cc5.2 -> 1.0.0-cc5.3": dict(prep={"firmwareVersion": "1.0.0-cc5.2"}),
            "outcome is RESTORED_CC5_2_RESET": dict(flash={"outcome": "RESTORED_CC5_2_RESET", "restoreAttempted": True}),
            "outcome is INSTALLED_VERIFIED_RESET_UNCONFIRMED": dict(flash={"outcome": "INSTALLED_VERIFIED_RESET_UNCONFIRMED",
                                                                           "reset": False}),
            "not a verified install": dict(flash={"postWriteVerified": False}),
            "installed image differs": dict(flash={"candidateSha256": "0" * 64}),
            "cc5.3-device-checks.json did not pass": dict(device={"passed": False, "failures": ["stress"]}),
            "does not show presentation 4": dict(device={"capabilities": {"presentation": 2}}),
            f"does not show firmware {t.CC5_VERSION}": dict(device={"checks": [{"check": f"inventory: firmware {t.CC5_VERSION}",
                                                                          "passed": False, "detail": t.CC4_VERSION}]}),
            # A run that stopped before the turning pass, or where the knob was not turned: never recorded.
            "hard gates ['stressTurn', 'turningDetected']": dict(device={"gates": {
                **{name: True for name in self.module.REQUIRED_GATES}, "stressTurn": False, "turningDetected": False}}),
            "hard gates ['noRebootOrReenumeration']": dict(device={"gates": {
                **{name: True for name in self.module.REQUIRED_GATES}, "noRebootOrReenumeration": False}}),
            f"does not pass the {t.CC5_VERSION} hard gates": dict(device={"gates": {}}),     # a 1.0.0-cc5-era record
            # A 1.0.0-cc5.1-era record: every old gate true, but no liveness or soak gate.
            "hard gates ['taskLiveness', 'unattendedSoak']": dict(device={"gates": {
                name: True for name in self.module.REQUIRED_GATES if name not in ("taskLiveness", "unattendedSoak")}}),
            "hard gates ['unattendedSoak']": dict(device={"gates": {
                **{name: True for name in self.module.REQUIRED_GATES}, "unattendedSoak": False}}),
            # A cc5.2-era record: every cc5.2 gate true, but none of the artwork2 gates.
            f"hard gates {list(t.ARTWORK2_DEVICE_GATES)}": dict(device={"gates": {
                name: True for name in t.CC52_DEVICE_GATES}}),
            "hard gates ['mediaPinning', 'jpegDecode']": dict(device={"gates": {
                **{name: True for name in self.module.REQUIRED_GATES}, "mediaPinning": False, "jpegDecode": False}}),
            "cc5.3-lease-checks.json did not pass": dict(lease={"passed": False, "failures": ["expiry"]}),
            "does not pass the artwork2 lease cases": dict(lease={"artwork2": {"mediaOnlyDoesNotRenew": True}}),
            "does not pass the artwork2 lease cases ": dict(lease={"artwork2": None}),        # a cc5.2-era lease record
            "cc5.3-device-checks.json is not newer": dict(times={"device": B + 50}),
            "cc5.3-lease-checks.json is not newer": dict(lease={"startedUtc": "20260923T070100Z"}),  # before the install ended
            "control-center-inventory-after.json is not newer": dict(times={"after": B + 50}),
            "unexpected settings change": dict(after={"settings": {"firmwareVersion": t.CC4_VERSION, "brightness": 3}}),
            "unexpected settings change ": dict(before={"settings": {"firmwareVersion": t.CC4_VERSION, "brightness": 3}}),
            "after-inventory capabilities are not cc5.3": dict(after={"capabilities": {"presentation": 2}}),
            "after-inventory capabilities are not cc5.3 ": dict(after={"capabilities": {
                "presentation": 4, "artwork": dict(t.EXPECTED_ARTWORK_CAPABILITY)}}),              # no artwork2
            "after-inventory capabilities are not cc5.3  ": dict(after={"capabilities": {
                "presentation": 4, "artwork": dict(t.EXPECTED_ARTWORK_CAPABILITY),
                "artwork2": {**t.artwork2_capability(), "paced": True}}}),                         # not the contract
            "saved profiles changed": dict(after={"profiles": {"PROFILE 0": self.profiles()["PROFILE 0"]}}),
            "backup evidence does not match": dict(backup={"sha256": "c" * 64}),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment):
                self.build(**change)
                self.assert_refused(fragment.strip())

    def test_saved_profiles_must_be_the_same_ten_named_profiles(self):
        changed = self.profiles()
        changed["PROFILE 3"] = {**changed["PROFILE 3"], "ledBrightness": 7}
        names = sorted(self.profiles())
        cases = {
            "one profile's content changed": dict(after={"profiles": changed}),
            "a profile missing": dict(after={"profiles": {k: v for k, v in self.profiles().items() if k != "PROFILE 9"}}),
            # Ten names as a list in both inventories: equal and ten long, but not what DeviceBridge writes.
            "a list instead of name -> profile": dict(before={"profiles": names}, after={"profiles": names}),
            "no profiles at all": dict(before={"profiles": {}}, after={"profiles": {}}),
        }
        for label, change in cases.items():
            with self.subTest(label):
                self.build(**change)
                self.assert_refused("saved profiles changed")
        self.build()
        self.assertEqual(self.module.main([]), 0)
        self.assertEqual(t.load_json(t.INSTALLATION)["savedProfileCount"], 10)

    def test_unconfirmed_reset_needs_the_explicit_flag(self):
        self.build(flash={"outcome": "INSTALLED_VERIFIED_RESET_UNCONFIRMED", "reset": False})
        message = self.assert_refused("outcome is INSTALLED_VERIFIED_RESET_UNCONFIRMED")
        self.assertIn("--accept-unconfirmed-reset", message)
        self.assertEqual(self.module.main(["--accept-unconfirmed-reset"]), 0)
        report = t.load_json(t.INSTALLATION)
        self.assertEqual(report["flashOutcome"], "INSTALLED_VERIFIED_RESET_UNCONFIRMED")
        self.assertIn("reset reply unconfirmed", report["resetConfirmation"])
        self.build(flash={"outcome": "RESTORED_CC5_2_VERIFIED_RESET_UNCONFIRMED", "reset": False})
        self.assert_refused("outcome is RESTORED_CC5_2_VERIFIED_RESET_UNCONFIRMED", "--accept-unconfirmed-reset")


class Cc54FinalizeFlowBase(FinalizeFlowBase):
    """The cc5.3 -> cc5.4 evidence (CURRENT) for finalize_nanod_cc5.main(): presentation 5, the alive capability
    of this knob's ledMaxBrightness, every cc5.4 gate true. Cc54FinalizeFlowTests (and the ladder classes after
    it) and Cc54FinalizeWaiverTests run on it."""
    pinned = None
    LED_MAX = 120                       # a knob whose LED maximum is below the alive drive cap (150)

    def records(self):
        records = super().records()
        sha = t.sha256_bytes
        p = t.CURRENT
        cc53_record = {"firmwareVersion": "1.0.0-cc5.3", "installationStatus": "INSTALLED",
                       "artifacts": {p.from_image.name: {"sha256": p.from_image_sha256}}}
        for key in ("cc52_record", "cc52_release"):
            del records[key]
        B = self.BASE
        records.update({
            "cc53_record": (self.fw / "manifest-cc5.3.json", cc53_record, B),
            "active_manifest": (t.ACTIVE_MANIFEST, dict(cc53_record), B),
            "cc53_release": (self.fw / "manifest-1.0.0-cc5.3.json", dict(cc53_record), B),
        })
        path, prep, at = records["prep"]
        records["prep"] = (path, {**prep, "fromVersion": "1.0.0-cc5.3", "candidateSha256": sha(self.image)}, at)
        caps4 = {"presentation": 4, "artwork": dict(t.EXPECTED_ARTWORK_CAPABILITY), "artwork2": t.artwork2_capability()}
        path, before, at = records["before"]
        records["before"] = (path, {**before, "settings": {"firmwareVersion": "1.0.0-cc5.3", "brightness": 3,
                                                           "ledMaxBrightness": self.LED_MAX},
                                    "capabilities": caps4}, at)
        path, after, at = records["after"]
        records["after"] = (path, {**after, "settings": {"firmwareVersion": t.CC5_VERSION, "brightness": 3,
                                                         "ledMaxBrightness": self.LED_MAX},
                                   "capabilities": self.after_capabilities()}, at)
        path, device, at = records["device"]
        records["device"] = (path, {**device, "capabilities": {"presentation": 5},
                                    "sections": {"diag": {"binary": "A"}}}, at)
        path, prep, at = records["prep"]
        records["prep"] = (path, {**prep, "binary": "A"}, at)
        return records

    def after_capabilities(self, **changes):
        caps = {"presentation": 5, "artwork": dict(t.EXPECTED_ARTWORK_CAPABILITY), "artwork2": t.artwork2_capability(),
                t.presentation().ALIVE_CAPABILITY: t.alive_capability(self.LED_MAX)}
        return {**caps, **changes}


@needs_tooling
class Cc54FinalizeFlowTests(Cc54FinalizeFlowBase):
    """finalize_nanod_cc5.main() for CURRENT, 1.0.0-cc5.3 -> 1.0.0-cc5.4: presentation 5, the alive
    capability of this knob's ledMaxBrightness, every cc5.4 gate, the cc5.3 record kept and superseded."""

    def test_the_fixture_is_the_cc5_4_release(self):
        self.assertIs(t.CURRENT, t.PROFILES["cc5.4"])
        self.assertEqual(tuple(self.module.REQUIRED_GATES), t.CURRENT.gates)
        self.assertEqual(t.alive_capability(self.LED_MAX)["drive"], self.LED_MAX)

    def test_verified_cc5_4_install_is_recorded_and_supersedes_cc5_3(self):
        self.assertEqual(self.module.main(["--companion-tests", "1500"]), 0)
        report = t.load_json(t.INSTALLATION)
        self.assertEqual(t.INSTALLATION.name, "cc5.4-installation.json")
        self.assertEqual((report["firmwareVersion"], report["fromVersion"], report["desktop"]["bundle"],
                          report["desktop"]["rollbackBundle"]),
                         ("1.0.0-cc5.4", "1.0.0-cc5.3", "desktop-dist-v7", "desktop-dist-v6"))
        self.assertEqual(report["capabilities"]["presentation"], 5)
        self.assertEqual(report["capabilities"]["alive"], {"version": 1, "fps": 60, "drive": self.LED_MAX})
        self.assertIn("Warm alive LEDs", report["physicalVisualAcceptance"])
        manifest = t.load_json(t.CC5_MANIFEST)
        self.assertEqual(manifest["installationStatus"], "INSTALLED")
        self.assertIn("presentation 5 with the alive LED renderer", manifest["hardwareStatus"])
        self.assertIn("alive LEDs", manifest["validation"]["physicalValidation"])
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), t.CC5_MANIFEST.read_bytes())
        validation = t.load_json(self.diag / "validation.json")
        self.assertEqual((validation["cc5.4"]["firmwareVersion"], validation["cc5.4"]["fromVersion"]),
                         ("1.0.0-cc5.4", "1.0.0-cc5.3"))
        self.assertIn("1.0.0-cc5.4 protocol/alive/presentation5", validation["hardware_acceptance"])
        self.assertTrue((self.diag / "validation-before-cc5.4.json").is_file())
        # Last, the installed cc5.3 release manifest became SUPERSEDED with its history; the kept record is unchanged.
        installed = (self.fw / "manifest-cc5.3.json").read_bytes()
        cc53 = t.load_json(self.fw / "manifest-1.0.0-cc5.3.json")
        self.assertEqual((cc53["installationStatus"], cc53["supersededBy"], cc53["installedRecord"],
                          cc53["installedRecordSha256"]),
                         ("SUPERSEDED", "1.0.0-cc5.4", "manifest-cc5.3.json", t.sha256_bytes(installed)))
        self.assertIn("Installed app-only on 2026-09-24", cc53["history"])
        self.assertEqual(t.load_json(self.fw / "manifest-cc5.3.json")["installationStatus"], "INSTALLED")

    def test_cc5_4_evidence_is_required(self):
        gates = {name: True for name in self.module.REQUIRED_GATES}
        cases = {
            "cc5.4-preparation.json does not prepare 1.0.0-cc5.3 -> 1.0.0-cc5.4": dict(prep={"fromVersion": "1.0.0-cc5.2"}),
            "does not show presentation 5": dict(device={"capabilities": {"presentation": 4}}),
            # A cc5.3-era record: every cc5.3 gate true, none of the alive or presentation 5 gates.
            f"hard gates {list(t.ALIVE_DEVICE_GATES + t.PRESENTATION5_DEVICE_GATES)}": dict(device={"gates": {
                name: True for name in t.PROFILES["cc5.3"].gates}}),
            "hard gates ['ledFrameRate', 'holdDeferred']": dict(device={"gates": {
                **gates, "ledFrameRate": False, "holdDeferred": False}}),
            "after-inventory capabilities are not cc5.4": dict(after={"capabilities": self.after_capabilities(
                presentation=4)}),
            # The alive drive must follow this knob's ledMaxBrightness (min(150, 120) = 120).
            "after-inventory capability alive is not": dict(after={"capabilities": self.after_capabilities(
                alive=t.alive_capability(150))}),
            "after-inventory capability alive is not ": dict(after={"capabilities": {
                k: v for k, v in self.after_capabilities().items() if k != "alive"}}),
            "manifest.json is not the installed 1.0.0-cc5.3 record": dict(active_manifest={"firmwareVersion": "1.0.0-cc5.2"}),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment):
                self.build(**change)
                self.assert_refused(fragment.strip())


@needs_tooling
class Cc54FinalizeWaiverTests(Cc54FinalizeFlowBase):
    """finalize --waive-gate NAME --waiver-note TEXT: the 2026-09-26 binary A run (stable; LCD animation 12 fps
    against 55 / 45, LED render 16-17 ms under the extreme stress, one 222 ms JPEG decode) recorded as INSTALLED
    with those performance gates waived, what was measured and the note; the targets stay as they are, and any
    other gate, name or failure still refuses with nothing written."""
    NOTE = "User sign-off 2026-09-26: ship binary A with the LCD/LED/JPEG timing misses as a known issue; A2 later."
    WAIVED = ("lcdTimings", "ledRenderTime", "jpegDecode")
    WAIVE = ("--waive-gate", "lcdTimings", "--waive-gate", "ledRenderTime", "--waive-gate", "jpegDecode")
    # The check names check_nanod_cc5.py writes (from the 2026-09-26 evidence).
    LCD_OPAQUE = "LCD opaque pass (binary A): lcdFpsAnimMin >= 55, no late refresh during the pass (lcdLateRefrs)"
    LCD_BLENDED = "LCD blended pass (binary A): lcdFpsAnimMin >= 45"
    LED_STRESS = "LED render during the untouched stress: ledRenderUsMax <= 3000 us"
    LED_TURN = "LED render during stress+turn: ledRenderUsMax <= 3000 us"
    JPEG = "diag: JPEG covers decoded (jpegDecodes > 0), jpegDecodeErrors 0, jpegDecodeMsMax <= 200 ms"
    HOLD = "hold Button 1: exactly one kh (its raw, Button 1's bit in ks, 0.45-1.2 s after the kd)"
    MEDIA = {"jpegDecodes": 124, "jpegDecodeErrors": 0, "jpegDecodeMsMax": 222, "jpegDecodeMsLast": 126, "mediaCommits": 517}
    # The 2026-09-26 run 3 additions: the LED idle gap (21 ms against 20, ledFps 60) and the End stop test, whose
    # pushes landed after the test's push windows while the knob sent lim +1 at T_end and lim -1 at 0:00.
    PERFORMANCE = ("lcdTimings", "ledRenderTime", "jpegDecode", "ledFrameRate")
    OPERATOR = ("limitPerPush", "limitEvents")
    ALL_SIX = PERFORMANCE + OPERATOR
    LED_IDLE = "LED at idle: ledFps >= 58, ledShowGapMsMax <= 20 ms (ALIVE.md 11.9)"
    LED_LOAD = "LED under cover transfers: ledFps >= 45 in every sample (target 55, recorded)"
    LED_LIVENESS = "tasks alive (every age <= 1000 ms), no LED transmit failure, no forced release: ledIdle"
    PER_PUSH = "End stop per push (ruling Q1): exactly one lim +1 per push, one while held, none outside"
    SEEK_ENDS = "Seek End stop: lim +1 at T_end and lim -1 at 0:00"
    STRESS_LIMS = "stress+turn: lim events at both ends of the range (-1 and +1), >= 150 ms apart"
    IDLE_DIAG = {"ledFps": 60, "ledRenderUsMax": 5229, "ledRenderUsAvg": 1229, "ledMode": "alive",
                 "ledShowGapMsMax": 21, "ledLateShows": 1382}
    # check_nanod_cc5.py push_test's timeline (seconds from the control's entry): five 1.4 s push windows 0.2 s
    # apart, the 3 s hold, and the end of the push phase (1 s after the hold) that limit_push_problems judges up to.
    PUSH_WINDOWS = tuple((0.2 + 1.6 * n, 1.6 + 1.6 * n) for n in range(5))
    HOLD_WINDOW, PUSH_END = (8.3, 11.3), 12.3
    # Each attempt's lims [(time, dir)]: late pushes (after the windows), lim +1 at T_end and lim -1 at 0:00.
    LATE_PUSHES = ([(10.0, 1), (12.0, 1), (14.0, 1), (21.0, -1)], [(15.9, -1)], [(3.4, -1), (7.3, -1), (14.8, -1)])

    def end_stop_runs(self, attempts=LATE_PUSHES):
        """sections.handsOn.endStop.runs as check_nanod_cc5.py push_test writes them (tooling's problem texts). After
        the push phase the operator turns to 0:00 (reachedZero) and push_test then waits for lim -1 (limAtZero: a
        lim -1 after the push phase)."""
        runs = []
        for number, lims in enumerate(attempts, 1):
            pushed = t.limit_push_problems([x for x in lims if x[0] <= self.PUSH_END], self.PUSH_WINDOWS,
                                           self.HOLD_WINDOW)
            runs.append({"attempt": number, "controlId": 116 + number, "tEnd": 17,
                         **{k: pushed[k] for k in ("perPush", "held", "stray", "problems")},
                         "reachedZero": True, "limAtZero": any(d == -1 and ts > self.PUSH_END for ts, d in lims),
                         "seekEnds": t.limit_problems(lims), "lims": [list(x) for x in lims]})
        return runs

    def device(self, failing=WAIVED, extra=(), end_stop=LATE_PUSHES):
        """Device checks with the gates `failing` false and their failed checks as check_nanod_cc5.py writes them
        (the problem texts from tooling), plus `extra` failed checks [(name, detail)]. The End stop checks are
        judged on the last of the `end_stop` attempts, as push_test does."""
        opaque, blended = {"lcdFpsAnimMin": 12, "lcdLateRefrs": 164}, {"lcdFpsAnimMin": 12}
        lcd = {"opaque": t.lcd_timing_problems(opaque, "A", "opaque", late=77),
               "blended": t.lcd_timing_problems(blended, "A", "blended")}
        render = {"stress": {"ledRenderUsMax": 17001}, "stressTurn": {"ledRenderUsMax": 16328}}
        runs = self.end_stop_runs(end_stop)
        last = runs[-1]
        failed = {"lcdTimings": [(self.LCD_OPAQUE, lcd["opaque"]), (self.LCD_BLENDED, lcd["blended"])],
                  "ledRenderTime": [(self.LED_STRESS, t.led_render_problems(render["stress"])),
                                    (self.LED_TURN, t.led_render_problems(render["stressTurn"]))],
                  "jpegDecode": [(self.JPEG, t.jpeg_decode_problems(self.MEDIA))],
                  "ledFrameRate": [(self.LED_IDLE, t.led_idle_problems(self.IDLE_DIAG))],
                  "limitPerPush": [(self.PER_PUSH, last["problems"])] if last["problems"] else [],
                  "limitEvents": [(self.SEEK_ENDS, last["seekEnds"])] if last["seekEnds"] else []}
        fails = [pair for gate in failing for pair in failed.get(gate, [])] + list(extra)
        load = t.led_load_summary([{"ledFps": 60, "ledShowGapMsMax": 26, "ledLateShows": 4 * n} for n in range(6)])
        stress_lims = [(127.073, -1), (128.047, -1), (141.916, 1), (143.121, 1)]
        render["stressTurn"]["lims"] = {"events": [list(x) for x in stress_lims], "problems": t.limit_problems(stress_lims)}
        return {"passed": not fails, "failures": [name for name, _ in fails],
                "checks": [{"check": f"inventory: firmware {t.CC5_VERSION}", "passed": True, "detail": t.CC5_VERSION},
                           *({"check": name, "passed": False, "detail": detail} for name, detail in fails)],
                "gates": {name: name not in failing for name in self.module.REQUIRED_GATES},
                "sections": {"diag": {"binary": "A", "media": dict(self.MEDIA)},
                             "lcdAnimation": {"binary": "A", "opaque": opaque, "blended": blended, "problems": lcd,
                                              "targets": dict(t.LCD_FPS_TARGETS["A"]), "coverCommitted": True},
                             "ledIdle": {"diag": dict(self.IDLE_DIAG), "problems": t.led_idle_problems(self.IDLE_DIAG)},
                             "ledUnderLoad": {**load, "transfers": 6, "committed": 6},
                             "handsOn": {"endStop": {"runs": runs}},
                             **render}}

    def waiver(self, *gates, note=NOTE):
        return [arg for gate in gates for arg in ("--waive-gate", gate)] + ["--waiver-note", note]

    def test_the_waived_checks_are_the_check_script_s_and_the_targets_are_unchanged(self):
        source = (WORK / "check_nanod_cc5.py").read_text(encoding="utf-8")
        for stem in ('f"LCD {kind} pass (binary {binary}): lcdFpsAnimMin >= "',
                     'f"LED render during the untouched stress: ledRenderUsMax <= ',
                     'f"LED render during stress+turn: ledRenderUsMax <= ',
                     'f"diag: JPEG covers decoded (jpegDecodes > 0), jpegDecodeErrors 0, jpegDecodeMsMax <= "'):
            self.assertIn(stem, source)
        # ledFrameRate (idle and under load) and the End stop gates (limitPerPush; limitEvents with the stress lims).
        for stem in ('f"LED at idle: ledFps >= {t.ALIVE_LED_FPS_IDLE_MIN}, ledShowGapMsMax <= "',
                     'f"LED under cover transfers: ledFps >= {t.ALIVE_LED_FPS_TRANSFER_MIN} in every sample (target "',
                     f'"{self.PER_PUSH}"', f'"{self.SEEK_ENDS}"', f'"{self.STRESS_LIMS}"',
                     'limitPerPush=results["limitPerPush"]', 'limitEvents=results["seekEnds"] and bool(stress_lims)'):
            self.assertIn(stem, source)
        for gate in self.PERFORMANCE:
            self.assertIn(f'report.gates["{gate}"] = ', source)
        self.assertEqual((self.module.PERFORMANCE_GATES, self.module.OPERATOR_TIMING_GATES),
                         (self.PERFORMANCE, self.OPERATOR))
        self.assertEqual(self.module.WAIVABLE_GATES, self.ALL_SIX)
        self.assertEqual(set(self.module.WAIVER_CHECKS), set(self.ALL_SIX))
        self.assertEqual(self.module.WAIVER_CATEGORIES, {**dict.fromkeys(self.PERFORMANCE, "performance"),
                                                         **dict.fromkeys(self.OPERATOR, "operator timing")})
        self.assertLessEqual(set(self.ALL_SIX), set(self.module.REQUIRED_GATES))
        self.assertEqual((t.LCD_FPS_TARGETS["A"], t.ALIVE_LED_RENDER_US_MAX, t.JPEG_DECODE_MAX_MS),
                         ({"opaque": 55, "blended": 45}, 3000, 200))
        self.assertEqual((t.ALIVE_LED_FPS_IDLE_MIN, t.ALIVE_LED_SHOW_GAP_IDLE_MAX_MS, t.ALIVE_LED_FPS_TRANSFER_MIN,
                          t.ALIVE_LIM_GAP_S), (58, 20, 45, 0.15))
        self.assertAlmostEqual(self.module.LIM_SPACING_MIN_S, 0.1)       # limit_problems' 150 ms less 50 ms jitter
        # One lim per physical push: same-direction lims closer than 0.5 s are chatter (above the firmware's re-fire
        # spacing of 150 ms + lim_rearm_ms <= 150 ms, below the test's 1.6 s push cadence).
        self.assertEqual(self.module.LIM_SAME_DIRECTION_MIN_S, 0.5)
        # A ledFrameRate waiver covers a running renderer only: half the frame-rate targets, twice the idle gap.
        self.assertEqual(self.module.LED_WAIVER_LIMITS,
                         {"idleLedFpsMin": 29, "idleLedShowGapMsMax": 40, "underLoadLedFpsMin": 22.5})

    def test_waived_performance_gates_are_recorded_with_what_was_measured(self):
        self.build(device=self.device())
        argv = ["--binary", "A", "--companion-tests", "1500", "--light-assertions", "2174210", *self.WAIVE,
                "--waiver-note", f"  {self.NOTE}  "]
        self.assertEqual(self.module.main(argv), 0)
        report = t.load_json(t.INSTALLATION)
        self.assertEqual((report["waiverNote"], report["waiverNotNeeded"]), (self.NOTE, []))
        self.assertEqual([w["gate"] for w in report["waivedGates"]], list(self.WAIVED))
        self.assertEqual({w["note"] for w in report["waivedGates"]}, {self.NOTE})
        measured = {w["gate"]: w["measured"] for w in report["waivedGates"]}
        lcd = measured["lcdTimings"]
        self.assertEqual((lcd["binary"], lcd["targets"], lcd["lcdFpsAnimMin"], lcd["coverCommitted"]),
                         ("A", {"opaque": 55, "blended": 45}, {"opaque": 12, "blended": 12}, True))
        self.assertIn("LCD FRAME RATE (opaque, binary A): lcdFpsAnimMin 12 < 55", lcd["problems"]["opaque"])
        self.assertEqual([c["check"] for c in lcd["failedChecks"]], [self.LCD_OPAQUE, self.LCD_BLENDED])
        led = measured["ledRenderTime"]
        self.assertEqual((led["ledRenderUsMax"], led["maxUs"]), ({"stress": 17001, "stressTurn": 16328}, 3000))
        self.assertEqual(led["failedChecks"][0], {"check": self.LED_STRESS, "detail": [
            "LED RENDER TOO SLOW: ledRenderUsMax 17001 us > 3000 us"]})
        self.assertEqual(measured["jpegDecode"], {"jpegDecodeMsMax": 222, "maxMs": 200, "failedChecks": [
            {"check": self.JPEG, "detail": ["SLOW JPEG DECODE: jpegDecodeMsMax 222 ms > 200 ms"]}]})
        self.assertFalse(report["deviceChecks"]["gates"]["lcdTimings"])          # the gates as measured
        # The manifest stays INSTALLED, and it and validation.json name the waived gates.
        manifest = t.load_json(t.CC5_MANIFEST)
        self.assertEqual(manifest["installationStatus"], "INSTALLED")
        self.assertEqual((manifest["waivedGates"], manifest["validation"]["waivedGates"]),
                         (list(self.WAIVED), list(self.WAIVED)))
        self.assertEqual(manifest["installation"]["waivedGates"], report["waivedGates"])
        waived_text = "waived gates lcdTimings, ledRenderTime, jpegDecode"
        self.assertIn(f"every hard gate passes (the alive and presentation 5 gates included) except the {waived_text}",
                      manifest["hardwareStatus"])
        # The diag JPEG check failed (222 ms): the status does not say every diag check passed.
        self.assertIn("lease checks and every other diag check pass", manifest["hardwareStatus"])
        self.assertNotIn("diag and lease checks pass", manifest["hardwareStatus"])
        self.assertIn(waived_text, manifest["validation"]["physicalValidation"])
        self.assertEqual(manifest["validation"]["lightAssertionsPassed"], 2174210)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), t.CC5_MANIFEST.read_bytes())
        validation = t.load_json(self.diag / "validation.json")
        self.assertEqual((validation["cc5.4"]["waivedGates"], validation["cc5.4"]["waiverNote"]),
                         (list(self.WAIVED), self.NOTE))
        self.assertIn(waived_text, validation["hardware_acceptance"])
        self.assertIn("manifest-1.0.0-cc5.4.json INSTALLED with waived gates: lcdTimings, ledRenderTime, jpegDecode",
                      self.out.getvalue())
        self.assertEqual(t.load_json(self.fw / "manifest-1.0.0-cc5.3.json")["installationStatus"], "SUPERSEDED")
        # Without the waiver the same evidence is refused as before, and nothing changes.
        self.assert_refused("cc5.4-device-checks.json did not pass", "--binary", "A")

    def test_only_the_performance_gates_can_be_waived(self):
        self.build(device=self.device())
        for name in ("holdEvents", "unattendedSoak", "noRebootOrReenumeration", "taskLiveness", "diagMargins",
                     "holdDeferred", "noErrorReplies", "aliveCapability", "stressTurn", "lcdtimings", "limitperpush",
                     "noSuchGate"):
            with self.subTest(name):
                self.assert_refused(f"--waive-gate {name} refused: only the performance gates lcdTimings, "
                                    "ledRenderTime, jpegDecode, ledFrameRate and the End stop operator-timing gates "
                                    "limitPerPush, limitEvents can be waived", *self.waiver(*self.WAIVED, name))
        self.assertFalse(t.INSTALLATION.exists())
        # Refused before any evidence is read.
        self.build(drop=("backup", "device"))
        self.assert_refused("--waive-gate holdEvents refused", *self.waiver("holdEvents"))

    def test_a_waiver_needs_its_note(self):
        self.build(device=self.device())
        for note in ([], ["--waiver-note", ""], ["--waiver-note", "   "], ["--waiver-note", "<text>"]):
            with self.subTest(note=note):
                self.assert_refused("--waive-gate needs --waiver-note TEXT", *self.WAIVE, *note)
        self.assert_refused("--waiver-note applies only with --waive-gate", "--waiver-note", self.NOTE)
        self.assertFalse(t.INSTALLATION.exists())

    def test_a_waived_gate_that_passed_is_not_waived(self):
        self.build(device=self.device(failing=("lcdTimings",)))
        self.assertEqual(self.module.main(self.waiver(*self.WAIVED)), 0)
        report = t.load_json(t.INSTALLATION)
        self.assertEqual([w["gate"] for w in report["waivedGates"]], ["lcdTimings"])
        self.assertEqual(report["waiverNotNeeded"], ["ledRenderTime", "jpegDecode"])
        manifest = t.load_json(t.CC5_MANIFEST)
        self.assertEqual((manifest["waivedGates"], manifest["validation"]["waivedGates"]), (["lcdTimings"], ["lcdTimings"]))
        self.assertEqual(t.load_json(self.diag / "validation.json")["cc5.4"]["waiverNotNeeded"], ["ledRenderTime", "jpegDecode"])
        line = self.out.getvalue().splitlines()[-1]
        self.assertIn("INSTALLED with waived gates: lcdTimings (", line)
        self.assertIn("waiver not needed (the gate passed): ledRenderTime, jpegDecode", line)
        # Every named gate passed: a clean record that says so, and no "waived" in its status lines.
        self.build()
        self.assertEqual(self.module.main(self.waiver("jpegDecode")), 0)
        report, manifest = t.load_json(t.INSTALLATION), t.load_json(t.CC5_MANIFEST)
        self.assertEqual((report["waivedGates"], report["waiverNotNeeded"]), ([], ["jpegDecode"]))
        self.assertEqual(manifest["waivedGates"], [])
        self.assertNotIn("waived", manifest["hardwareStatus"])
        self.assertIn("INSTALLED and copied to manifest.json", self.out.getvalue().splitlines()[-1])

    def test_a_gate_named_twice_is_waived_once(self):
        self.build(device=self.device(failing=("lcdTimings",)))
        self.assertEqual(self.module.main(self.waiver("lcdTimings", "lcdTimings", "jpegDecode", "jpegDecode")), 0)
        report, manifest = t.load_json(t.INSTALLATION), t.load_json(t.CC5_MANIFEST)
        self.assertEqual(([w["gate"] for w in report["waivedGates"]], report["waiverNotNeeded"]),
                         (["lcdTimings"], ["jpegDecode"]))
        self.assertEqual((manifest["waivedGates"], manifest["validation"]["waivedGates"],
                          t.load_json(self.diag / "validation.json")["cc5.4"]["waivedGates"]),
                         (["lcdTimings"], ["lcdTimings"], ["lcdTimings"]))
        line = self.out.getvalue().splitlines()[-1]
        self.assertIn("INSTALLED with waived gates: lcdTimings (", line)
        self.assertIn("waiver not needed (the gate passed): jpegDecode;", line)

    WAIVER_KEYS = ("waivedGates", "waiverNotNeeded", "waiverNote")

    def waiver_keys(self):
        """The waiver keys present in each record finalize writes (none: an empty list per record)."""
        manifest = t.load_json(t.CC5_MANIFEST)
        records = {"installation": t.load_json(t.INSTALLATION), "manifest": manifest,
                   "manifest.validation": manifest["validation"], "manifest.installation": manifest["installation"],
                   "validation.json cc5.4": t.load_json(self.diag / "validation.json")["cc5.4"]}
        return {where: [key for key in self.WAIVER_KEYS if key in record] for where, record in records.items()}

    def test_without_a_waiver_no_record_names_one(self):
        clean = {where: [] for where in ("installation", "manifest", "manifest.validation", "manifest.installation",
                                         "validation.json cc5.4")}
        # A clean run writes no waiver keys at all (not even empty ones): the records are as before the waiver.
        self.assertEqual(self.module.main(["--binary", "A"]), 0)
        self.assertEqual(self.waiver_keys(), clean)
        # A clean re-run after a waived one (the manifest INSTALLED with waivedGates) drops the names it recorded.
        self.build(device=self.device(failing=("lcdTimings",)))
        self.assertEqual(self.module.main(self.waiver("lcdTimings")), 0)
        self.assertEqual(t.load_json(t.CC5_MANIFEST)["waivedGates"], ["lcdTimings"])
        path, device, at = self.records()["device"]
        self.write(path, {**device, **self.device(failing=())}, at)       # the device checks re-run and passed
        self.assertEqual(self.module.main([]), 0)
        self.assertEqual(self.waiver_keys(), clean)
        manifest = t.load_json(t.CC5_MANIFEST)
        self.assertEqual(manifest["installationStatus"], "INSTALLED")
        self.assertNotIn("waived", manifest["hardwareStatus"] + manifest["validation"]["physicalValidation"])
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), t.CC5_MANIFEST.read_bytes())
        self.assertIn("INSTALLED and copied to manifest.json", self.out.getvalue().splitlines()[-1])

    def test_a_gate_not_waived_still_refuses(self):
        # The 2026-09-26 run also failed the hold test: holdEvents cannot be waived, so its failure is not covered.
        self.build(device=self.device(failing=(*self.WAIVED, "holdEvents"), extra=[(self.HOLD, ["no press"])]))
        self.assert_refused(f"the waiver of {list(self.WAIVED)} does not cover: {self.HOLD} (not a check of a waived "
                            "gate)", "--binary", "A", *self.waiver(*self.WAIVED))
        # A false gate that is not waived is a missing hard gate; the waived one is not listed.
        self.build(device=self.device(failing=("lcdTimings", "holdEvents")))
        self.assert_refused("does not pass the 1.0.0-cc5.4 hard gates ['holdEvents']", *self.waiver("lcdTimings"))
        # Waiving one performance gate does not cover another that failed.
        self.build(device=self.device())
        self.assert_refused(f"{self.LED_STRESS} (not a check of a waived gate)", *self.waiver("lcdTimings"))
        self.assertFalse(t.INSTALLATION.exists())

    def test_a_waiver_covers_only_the_measured_miss(self):
        def changed(detail=None, drop_check=False, gate="jpegDecode", name=None):
            device, name = self.device(failing=(gate,)), name or self.JPEG
            if drop_check:
                device["checks"] = [c for c in device["checks"] if c["check"] != name]
            else:
                next(c for c in device["checks"] if c["check"] == name)["detail"] = detail
            return device
        def cover(committed):
            # check_nanod_cc5.py's lcdTimings is also false when the LCD pass's cover did not commit; no check says so.
            device = self.device(failing=("lcdTimings",))
            device["sections"]["lcdAnimation"].pop("coverCommitted")
            if committed is not None:
                device["sections"]["lcdAnimation"]["coverCommitted"] = committed
            return device
        errors = t.jpeg_decode_problems({**self.MEDIA, "jpegDecodeErrors": 2})
        no_field = t.led_render_problems({})
        passed_gate = self.device(failing=())
        passed_gate["gates"]["lcdTimings"] = False
        cases = (("decode errors", changed(errors), ("jpegDecode",), "(not only the measured jpegDecode miss)"),
                 ("missing field", changed(no_field, gate="ledRenderTime", name=self.LED_STRESS), ("ledRenderTime",),
                  "(not only the measured ledRenderTime miss)"),
                 ("no failed check", changed(drop_check=True), ("jpegDecode",), "(in failures without its failed check)"),
                 ("gate only", passed_gate, ("lcdTimings",),
                  "lcdTimings is false without a failed lcdTimings check (a waiver covers only a measured miss)"),
                 ("cover not committed", cover(False), ("lcdTimings",),
                  "lcdTimings is false with the LCD pass cover not committed (sections.lcdAnimation.coverCommitted "
                  "False: a media failure, not the measured miss)"),
                 ("cover commit not recorded", cover(None), ("lcdTimings",),
                  "LCD pass cover not committed (sections.lcdAnimation.coverCommitted None"),
                 ("port not closed", {**self.device(), "portClosed": False}, self.WAIVED,
                  f"the waiver of {list(self.WAIVED)} does not cover: the port was not closed"))
        for label, device, gates, fragment in cases:
            with self.subTest(label):
                self.build(device=device)
                self.assert_refused(fragment, *self.waiver(*gates))
        self.assertFalse(t.INSTALLATION.exists())

    def test_the_measured_summary_tolerates_missing_fields(self):
        device = self.device()
        # Only the cover commit is kept: without it lcdTimings is not covered (test_a_waiver_covers_only_the_measured_miss).
        device["sections"] = {"diag": {"binary": "A"}, "lcdAnimation": {"coverCommitted": True}}
        self.build(device=device)
        self.assertEqual(self.module.main(self.waiver(*self.WAIVED)), 0)
        measured = {w["gate"]: w["measured"] for w in t.load_json(t.INSTALLATION)["waivedGates"]}
        self.assertEqual((measured["lcdTimings"]["lcdFpsAnimMin"], measured["lcdTimings"]["targets"]),
                         ({"opaque": None, "blended": None}, t.LCD_FPS_TARGETS["A"]))
        self.assertEqual(measured["ledRenderTime"]["ledRenderUsMax"], {"stress": None, "stressTurn": None})
        self.assertIsNone(measured["jpegDecode"]["jpegDecodeMsMax"])
        self.assertEqual(len(measured["jpegDecode"]["failedChecks"]), 1)

    # --- ledFrameRate (performance) and the End stop operator-timing gates (2026-09-26 run 3 sign-off) ---

    def failed_detail(self, device, name, detail):
        """Replace the detail of the failed check `name` in `device` (returned)."""
        next(c for c in device["checks"] if c["check"] == name)["detail"] = detail
        return device

    def test_led_frame_rate_is_waived_for_its_measured_miss(self):
        self.build(device=self.device(failing=("ledFrameRate",)))
        self.assertEqual(self.module.main(self.waiver("ledFrameRate")), 0)
        [record] = t.load_json(t.INSTALLATION)["waivedGates"]
        self.assertEqual((record["gate"], record["category"], record["note"]), ("ledFrameRate", "performance", self.NOTE))
        self.assertEqual(record["measured"], {
            "idle": {"ledFps": 60, "ledShowGapMsMax": 21, "ledMode": "alive"},
            "underLoad": {"ledFpsMin": 60, "ledShowGapMsMax": 26, "committed": 6, "transfers": 6},
            "targets": {"idleLedFpsMin": 58, "idleLedShowGapMsMax": 20, "underLoadLedFpsMin": 45},
            "waiverLimits": {"idleLedFpsMin": 29, "idleLedShowGapMsMax": 40, "underLoadLedFpsMin": 22.5},
            "failedChecks": [{"check": self.LED_IDLE, "detail": ["LED SHOW GAP AT IDLE: ledShowGapMsMax 21 ms > 20 ms"]}]})
        self.assertIn("INSTALLED with waived gates: ledFrameRate (", self.out.getvalue().splitlines()[-1])
        # The other measured misses of the gate: the idle frame rate, and ledFps below 45 under cover transfers
        # (that check's detail is its summary object; only its problems are judged).
        slow = self.device(failing=("ledFrameRate",))
        self.failed_detail(slow, self.LED_IDLE, t.led_idle_problems({**self.IDLE_DIAG, "ledFps": 55}))
        low = t.led_load_summary([{"ledFps": 40, "ledShowGapMsMax": 30, "ledLateShows": 0}])
        slow["checks"].append({"check": self.LED_LOAD, "passed": False,
                               "detail": {k: low[k] for k in ("ledFpsMin", "targetMet", "ledShowGapMsMax", "ledLateShows",
                                                              "problems")}})
        slow["failures"].append(self.LED_LOAD)
        self.build(device=slow)
        self.assertEqual(self.module.main(self.waiver("ledFrameRate")), 0)
        [record] = t.load_json(t.INSTALLATION)["waivedGates"]
        self.assertEqual([c["check"] for c in record["measured"]["failedChecks"]], [self.LED_IDLE, self.LED_LOAD])
        self.assertEqual(record["measured"]["failedChecks"][1]["detail"]["problems"],
                         ["LED FRAME RATE UNDER LOAD: ledFps 40 < 45"])
        # At the waiver's limits (a running renderer: 29 fps idle, a 40 ms idle gap, 23 fps under load) still covered.
        edge = self.device(failing=("ledFrameRate",))
        edge_idle = {**self.IDLE_DIAG, "ledFps": 29, "ledShowGapMsMax": 40}
        edge["sections"]["ledIdle"]["diag"] = edge_idle
        edge["sections"]["ledUnderLoad"]["ledFpsMin"] = 23
        self.failed_detail(edge, self.LED_IDLE, t.led_idle_problems(edge_idle))
        self.build(device=edge)
        self.assertEqual(self.module.main(self.waiver("ledFrameRate")), 0)

    def test_led_frame_rate_refuses_any_other_led_problem(self):
        def device(**sections):
            device = self.device(failing=("ledFrameRate",))
            for name, changes in sections.items():
                device["sections"][name].update(changes)
            return device
        no_diag = self.failed_detail(self.device(failing=("ledFrameRate",)), self.LED_IDLE, t.led_idle_problems({}))
        transmit = self.device(failing=("ledFrameRate",), extra=[(self.LED_LIVENESS, t.liveness_problems(
            {"hmiAgeMs": 5, "lcdAgeMs": 4, "comAgeMs": 3, "focAgeMs": 0, "ledTxTimeouts": 2, "forcedReleases": 0}))])
        uncommitted = self.device(failing=("ledFrameRate",), extra=[(self.LED_LOAD, {
            "ledFpsMin": 60, "targetMet": True, "ledShowGapMsMax": 26, "ledLateShows": 16, "problems": []})])
        uncommitted["sections"]["ledUnderLoad"]["committed"] = 5
        # A stalled alive renderer: its texts are the helpers' own misses (prefix-matched), but not a timing miss.
        def stalled(idle=None, load_min=None):
            evidence = self.device(failing=("ledFrameRate",))
            if idle is not None:
                evidence["sections"]["ledIdle"]["diag"] = {**self.IDLE_DIAG, **idle}
                self.failed_detail(evidence, self.LED_IDLE, t.led_idle_problems({**self.IDLE_DIAG, **idle}))
            if load_min is not None:
                low = t.led_load_summary([{"ledFps": load_min, "ledShowGapMsMax": 30, "ledLateShows": 0}])
                evidence["sections"]["ledUnderLoad"]["ledFpsMin"] = load_min
                evidence["checks"].append({"check": self.LED_LOAD, "passed": False, "detail": {
                    k: low[k] for k in ("ledFpsMin", "targetMet", "ledShowGapMsMax", "ledLateShows", "problems")}})
                evidence["failures"].append(self.LED_LOAD)
            return evidence
        stall = "a stalled renderer, not the measured miss"
        cases = (("idle ledFps 0, a 5 s gap", stalled({"ledFps": 0, "ledShowGapMsMax": 5000}),
                  f"LED renderer far off its targets (idle ledFps 0, ledShowGapMsMax 5000 ms, under load ledFpsMin 60; "
                  f"a waiver covers at least 29 fps at idle, 22.5 under load and a gap of at most 40 ms): {stall}"),
                 ("idle ledFps below half its target", stalled({"ledFps": 28}), stall),
                 ("idle gap over twice its target", stalled({"ledShowGapMsMax": 41}), stall),
                 ("ledFps 0 under load", stalled(load_min=0), stall),
                 ("under load below half its target", stalled(load_min=22), stall),
                 ("missing diag field", no_diag, "(not only the measured ledFrameRate miss)"),
                 ("LED transmit failure", transmit, f"{self.LED_LIVENESS} (not a check of a waived gate)"),
                 ("ledMode not alive", device(ledIdle={"diag": {**self.IDLE_DIAG, "ledMode": "native"}}),
                  "ledFrameRate is false with the idle LED measurement not of the alive renderer "
                  "(sections.ledIdle.diag.ledMode 'native', not 'alive')"),
                 ("ledMode not recorded", device(ledIdle={"diag": None}), "(sections.ledIdle.diag.ledMode None"),
                 ("load covers not committed", uncommitted, f"{self.LED_LOAD} failed with"),
                 ("load commits short without its check", device(ledUnderLoad={"committed": 5}),
                  "LED load pass's covers not all committed (sections.ledUnderLoad committed 5 of 6"),
                 ("load pass not recorded", device(ledUnderLoad={"committed": None, "transfers": None}),
                  "committed None of None"))
        for label, evidence, fragment in cases:
            with self.subTest(label):
                self.build(device=evidence)
                self.assert_refused(fragment, *self.waiver("ledFrameRate"))
        self.assertIn("LED TRANSMIT TIMEOUT: ledTxTimeouts 2", str(transmit["checks"][-1]["detail"]))
        self.assertFalse(t.INSTALLATION.exists())

    def test_end_stop_late_pushes_are_waived_as_operator_timing(self):
        self.build(device=self.device(failing=self.OPERATOR))
        self.assertEqual(self.module.main(self.waiver(*self.OPERATOR)), 0)
        report = t.load_json(t.INSTALLATION)
        records = {w["gate"]: w for w in report["waivedGates"]}
        self.assertEqual(list(records), list(self.OPERATOR))
        self.assertEqual({w["category"] for w in records.values()}, {"operator timing"})
        zero = {"reachedZero": True, "limAtZero": True}
        runs = [{"attempt": 1, "perPush": [0] * 5, "held": 1, "stray": [[12.0, 1]], **zero,
                 "lims": [[10.0, 1], [12.0, 1], [14.0, 1], [21.0, -1]]},
                {"attempt": 2, "perPush": [0] * 5, "held": 0, "stray": [], **zero, "lims": [[15.9, -1]]},
                {"attempt": 3, "perPush": [0] * 5, "held": 0, "stray": [], **zero,
                 "lims": [[3.4, -1], [7.3, -1], [14.8, -1]]}]
        # The direction at each end: attempt 1's lim +1 while held and outside the windows (both in the push phase, at
        # T_end), and every attempt's lim -1 after the knob reported 0:00; no two lims of one direction within 0.5 s.
        proof = {"limPlus": 3, "limMinus": 5, "limPlusInPushPhase": 2, "runsWithLimMinusAtZero": 3,
                 "minSpacingS": 2.0, "minSpacingAllowedS": 0.1, "firmwareSpacingS": 0.15,
                 "minSameDirectionSpacingS": 2.0, "minSameDirectionAllowedS": 0.5}
        per_push, seek = records["limitPerPush"]["measured"], records["limitEvents"]["measured"]
        self.assertEqual((per_push["runs"], per_push["proof"]), (runs, proof))
        self.assertEqual(per_push["failedChecks"], [{"check": self.PER_PUSH, "detail": [
            "lim per push [0, 0, 0, 0, 0] (each must be exactly 1: none is a missed End stop, two is attractor chatter "
            "or a short lim_rearm_ms)", "0 lim while held against the bound (must be exactly 1)"]}])
        self.assertEqual((seek["runs"], seek["proof"], seek["stressTurnLims"]), (runs, proof, {"events": 4, "problems": []}))
        self.assertEqual(seek["failedChecks"], [{"check": self.SEEK_ENDS, "detail": ["no lim +1 seen"]}])
        self.assertEqual(report["waiverNote"], self.NOTE)
        manifest = t.load_json(t.CC5_MANIFEST)
        self.assertEqual((manifest["installationStatus"], manifest["waivedGates"]), ("INSTALLED", list(self.OPERATOR)))
        self.assertIn("except the waived gates limitPerPush, limitEvents (operator timing the user signed off: the End "
                      "stop test's push windows were missed while the knob's lim +1 at T_end and lim -1 at 0:00 were "
                      "recorded)", manifest["hardwareStatus"])
        self.assertIn("diag and lease checks pass", manifest["hardwareStatus"])       # jpegDecode passed
        self.assertEqual(t.load_json(self.diag / "validation.json")["cc5.4"]["waivedGates"], list(self.OPERATOR))
        self.assertIn("INSTALLED with waived gates: limitPerPush, limitEvents (", self.out.getvalue().splitlines()[-1])
        # The first attempt's stray lim, the per-push misses of every attempt: all End stop timing.
        self.assertIn("lim outside the push windows: [(12.0, 1)]", self.end_stop_runs()[0]["problems"])

    def test_end_stop_waiver_needs_the_knob_s_lim_events_and_refuses_chatter(self):
        def seek_detail(detail):
            return self.failed_detail(self.device(failing=self.OPERATOR), self.SEEK_ENDS, detail)
        def per_push_detail(detail):
            return self.failed_detail(self.device(failing=self.OPERATOR), self.PER_PUSH, detail)
        def run_changed(attempt=0, **changes):
            """The late-push evidence with one recorded run changed (its checks' details as written)."""
            evidence = self.device(failing=self.OPERATOR)
            evidence["sections"]["handsOn"]["endStop"]["runs"][attempt].update(changes)
            return evidence
        stress_failed = self.device(failing=self.OPERATOR, extra=[(self.STRESS_LIMS, ["no lim +1 seen"])])
        stress_failed["sections"]["stressTurn"]["lims"] = {"events": [[127.073, -1]], "problems": ["no lim +1 seen"]}
        no_runs = self.device(failing=self.OPERATOR)
        del no_runs["sections"]["handsOn"]
        miss = ("lim per push [0, 0, 0, 0, 0] (each must be exactly 1: none is a missed End stop, two is attractor "
                "chatter or a short lim_rearm_ms)")
        # Chatter outside the windows: three lim +1 160 ms apart (each >= 150 ms, the firmware's re-fire spacing) for
        # one push after the hold, before the push phase ended (stray) or after it (judged by spacing alone).
        stray_chatter = [(11.8, 1), (11.96, 1), (12.12, 1), (21.0, -1)]
        late_chatter = [(13.0, 1), (13.16, 1), (13.32, 1), (13.48, 1), (21.0, -1)]
        self.assertEqual(self.end_stop_runs((stray_chatter,))[0]["problems"],
                         [miss, "0 lim while held against the bound (must be exactly 1)",
                          "lim outside the push windows: [(11.8, 1), (11.96, 1), (12.12, 1)]"])
        # Attempt 1 of the late pushes alone (its lim -1 after the push phase) without the knob reporting 0:00.
        not_reached = self.device(failing=("limitPerPush",), end_stop=self.LATE_PUSHES[:1])
        not_reached["sections"]["handsOn"]["endStop"]["runs"][0]["reachedZero"] = False
        cases = (
            ("no lim +1 ever", self.device(failing=self.OPERATOR, end_stop=([(15.9, -1)], [(3.4, -1), (14.8, -1)])),
             self.OPERATOR, "no lim +1 in any End stop run: the knob never reported the End stop at T_end"),
            ("no lim -1 ever", self.device(failing=self.OPERATOR, end_stop=([(10.0, 1), (12.0, 1)],)),
             self.OPERATOR, "no lim -1 in any End stop run: the knob never reported the End stop at 0:00"),
            # Two lims 50 ms apart in an earlier attempt: the judged (last) attempt alone would look like timing.
            ("chatter 50 ms apart", self.device(failing=self.OPERATOR,
                                                end_stop=([(10.0, 1), (10.05, 1), (21.0, -1)], [(15.9, -1)])),
             self.OPERATOR, "End stop attempt 1: lim events closer than 150 ms: gaps [0.05] s (chatter"),
            ("chatter in the judged attempt", self.device(failing=self.OPERATOR,
                                                          end_stop=([(15.9, -1)], [(10.0, 1), (10.05, 1), (21.0, -1)])),
             self.OPERATOR, f"{self.SEEK_ENDS} failed with ['lim events closer than 150 ms: gaps [0.05] s'] (not only "
                            "the End stop timing miss limitEvents may waive"),
            ("held twice", self.device(failing=("limitPerPush",), end_stop=([(8.5, 1), (10.5, 1), (21.0, -1)],)),
             ("limitPerPush",), "'2 lim while held against the bound (must be exactly 1)'"),
            ("two lims for one push", self.device(failing=("limitPerPush",), end_stop=([(1.0, 1), (1.5, 1), (21.0, -1)],)),
             ("limitPerPush",), "End stop attempt 1: perPush [2, 0, 0, 0, 0], held 0 (two lims for one push"),
            ("a non-timing detail", seek_detail(["no lim +1 seen", "TimeoutError: no lim -1 within 60 s"]),
             self.OPERATOR, "(not only the End stop timing miss limitEvents may waive"),
            ("the passed per-push summary", self.failed_detail(self.device(failing=self.OPERATOR), self.PER_PUSH,
                                                               {"perPush": [1] * 5, "held": 1}),
             self.OPERATOR, "(not only the End stop timing miss limitPerPush may waive"),
            ("stress+turn lims failed", stress_failed, self.OPERATOR, f"{self.STRESS_LIMS} (not a check of a waived gate)"),
            ("stress+turn lims failed ", stress_failed, self.OPERATOR,
             "limitEvents is false with the stress+turn lims not passed (sections.stressTurn.lims: 1 events, problems "
             "['no lim +1 seen'])"),
            ("no End stop runs", no_runs, self.OPERATOR, "no End stop runs recorded (sections.handsOn.endStop.runs)"),
            ("a gate not waived still refuses", self.device(failing=("limitPerPush", "holdEvents"),
                                                                 extra=[(self.HOLD, ["no press"])]),
             ("limitPerPush",), f"{self.HOLD} (not a check of a waived gate)"),
            # Chatter the counts cannot see: several lim +1 for one push outside the windows (the Seek check passes).
            ("chatter outside the windows", self.device(failing=("limitPerPush",), end_stop=(stray_chatter,)),
             ("limitPerPush",), "End stop attempt 1: lim +1 repeated within 0.5 s (gaps [0.16, 0.16] s), closer than "
                                "one physical push can repeat"),
            ("chatter after the push phase", self.device(failing=("limitPerPush",),
                                                         end_stop=(self.LATE_PUSHES[0], late_chatter)),
             ("limitPerPush",), "End stop attempt 2: lim +1 repeated within 0.5 s (gaps [0.16, 0.16, 0.16] s)"),
            # The direction at each end, tied to where each lim happened: a lim -1 only inside the push windows (never
            # after 0:00 was reached) proves no End stop at 0:00; a lim +1 only after the push phase none at T_end.
            ("lim -1 only before 0:00", self.device(failing=("limitPerPush",), end_stop=([(4.1, -1), (9.0, 1)],)),
             ("limitPerPush",), "no End stop run saw lim -1 after the knob reported 0:00 (reachedZero and limAtZero)"),
            ("lim +1 only after the push phase", self.device(failing=("limitPerPush",),
                                                             end_stop=([(21.0, 1), (25.0, -1)],)),
             ("limitPerPush",), "no lim +1 in the push phase of any End stop run (perPush, held and stray all without "
                                "a +1)"),
            ("0:00 not reached", not_reached, ("limitPerPush",),
             "no End stop run saw lim -1 after the knob reported 0:00 (reachedZero and limAtZero)"),
            # Whole-text matching and malformed runs (reviewer mutations: .match, any direction, the counts guard).
            ("a Seek End text with a suffix", seek_detail(["no lim +1 seen (late)"]), self.OPERATOR,
             "(not only the End stop timing miss limitEvents may waive"),
            ("a per-push count of 3 in the detail", per_push_detail([miss.replace("[0, 0, 0, 0, 0]", "[0, 0, 3, 0, 0]")]),
             self.OPERATOR, "(not only the End stop timing miss limitPerPush may waive"),
            ("a stray text with a suffix", per_push_detail([miss, "lim outside the push windows: [(12.0, 1)] twice"]),
             self.OPERATOR, "(not only the End stop timing miss limitPerPush may waive"),
            ("perPush not recorded", run_changed(0, perPush=None), self.OPERATOR,
             "End stop attempt 1: per-push and held counts not recorded (None, 1)"),
            ("held as text", run_changed(1, held="0"), self.OPERATOR,
             "End stop attempt 2: per-push and held counts not recorded ([0, 0, 0, 0, 0], '0')"),
            ("a lim of direction 2", run_changed(0, lims=[[10.0, 2]]), self.OPERATOR,
             "End stop attempt 1: lims [[10.0, 2]] are not [time, +1|-1] pairs"),
            ("a stray of direction 3", run_changed(0, stray=[[12.0, 3]]), self.OPERATOR,
             "End stop attempt 1: stray [[12.0, 3]] are not [time, +1|-1] pairs"),
            ("an earlier attempt's other problem", run_changed(0, problems=["something else"]), self.OPERATOR,
             "End stop attempt 1 recorded ['something else'] (not only End stop timing)"),
            ("an earlier attempt's other Seek problem", run_changed(1, seekEnds=["something else"]), self.OPERATOR,
             "End stop attempt 2 recorded ['something else'] (not only End stop timing)"),
        )
        for label, evidence, gates, fragment in cases:
            with self.subTest(label):
                self.build(device=evidence)
                self.assert_refused(fragment, *self.waiver(*gates))
        self.assertFalse(t.INSTALLATION.exists())
        # Each End stop gate needs its own failed check; one waived alone does not cover the other.
        self.build(device=self.device(failing=self.OPERATOR))
        self.assert_refused(f"{self.SEEK_ENDS} (not a check of a waived gate)", *self.waiver("limitPerPush"))
        self.assert_refused(f"{self.PER_PUSH} (not a check of a waived gate)", *self.waiver("limitEvents"))
        self.assertFalse(t.INSTALLATION.exists())

    def test_end_stop_waiver_refuses_a_wrong_direction_at_either_end(self):
        # Firmware sending lim -1 at T_end (in every push window and the hold) and lim +1 at 0:00 (after the push
        # phase): the per-push check then fails with timing-only texts, the Seek check passes (both directions seen)
        # and lim +1 and -1 are both present, so a count of each alone would read it as late pushes.
        inverted = [(0.9, -1), (2.5, -1), (4.1, -1), (5.7, -1), (7.3, -1), (9.0, -1), (21.0, 1)]
        [run] = self.end_stop_runs((inverted,))
        self.assertEqual((run["perPush"], run["held"], run["stray"], run["seekEnds"], run["limAtZero"]),
                         ([0] * 5, 0, [], [], False))
        self.assertEqual(run["problems"], [
            "lim per push [0, 0, 0, 0, 0] (each must be exactly 1: none is a missed End stop, two is attractor chatter "
            "or a short lim_rearm_ms)", "0 lim while held against the bound (must be exactly 1)"])
        evidence, reasons = self.module.end_stop_evidence({"sections": {"handsOn": {"endStop": {"runs": [run]}}}})
        self.assertEqual((evidence["proof"]["limPlus"], evidence["proof"]["limMinus"],
                          evidence["proof"]["limPlusInPushPhase"], evidence["proof"]["runsWithLimMinusAtZero"]),
                         (1, 6, 0, 0))
        self.assertEqual(len(reasons), 2)
        for gates, failing in ((("limitPerPush",), ("limitPerPush",)),
                               (self.ALL_SIX, (*self.PERFORMANCE, "limitPerPush"))):   # limitEvents passed
            with self.subTest(gates=gates):
                self.build(device=self.device(failing=failing, end_stop=(inverted,)))
                message = self.assert_refused("no lim +1 in the push phase of any End stop run", *self.waiver(*gates))
                self.assertIn("no End stop run saw lim -1 after the knob reported 0:00", message)
        self.assertFalse(t.INSTALLATION.exists())

    # sections.handsOn.endStop.runs of diagnostics/cc5.4-device-checks.json (2026-09-26 run 3), as recorded (stray
    # holds the push phase's absolute times, lims the times from the control's entry).
    MISS = ("lim per push [0, 0, 0, 0, 0] (each must be exactly 1: none is a missed End stop, two is attractor chatter "
            "or a short lim_rearm_ms)")
    RUN3_END_STOP = [
        {"attempt": 1, "controlId": 117, "tEnd": 17, "perPush": [0, 0, 0, 0, 0], "held": 1, "stray": [[195.45, 1]],
         "problems": [MISS, "lim outside the push windows: [(195.45, 1)]"], "reachedZero": True, "limAtZero": True,
         "seekEnds": [], "lims": [[11.03, 1], [13.106, 1], [14.853, 1], [21.655, -1]]},
        {"attempt": 2, "controlId": 118, "tEnd": 17, "perPush": [0, 0, 0, 0, 0], "held": 0, "stray": [],
         "problems": [MISS, "0 lim while held against the bound (must be exactly 1)"], "reachedZero": True,
         "limAtZero": True, "seekEnds": ["no lim +1 seen"], "lims": [[15.927, -1]]},
        {"attempt": 3, "controlId": 119, "tEnd": 17, "perPush": [0, 0, 0, 0, 0], "held": 0, "stray": [],
         "problems": [MISS, "0 lim while held against the bound (must be exactly 1)"], "reachedZero": True,
         "limAtZero": True, "seekEnds": ["no lim +1 seen"], "lims": [[3.454, -1], [7.3, -1], [14.793, -1]]}]

    def test_the_2026_09_26_run_3_is_recorded_with_all_six_gates_waived(self):
        device = self.device(failing=self.ALL_SIX)
        device["sections"]["handsOn"]["endStop"]["runs"] = json.loads(json.dumps(self.RUN3_END_STOP))
        self.build(device=device)
        # Without the three added gates the same evidence is refused, and nothing is written.
        self.assert_refused(f"{self.LED_IDLE} (not a check of a waived gate)", *self.waiver(*self.WAIVED))
        self.assertEqual(self.module.main(["--binary", "A", *self.waiver(*self.ALL_SIX)]), 0)
        report = t.load_json(t.INSTALLATION)
        self.assertEqual([(w["gate"], w["category"]) for w in report["waivedGates"]],
                         [(g, "performance") for g in self.PERFORMANCE] + [(g, "operator timing") for g in self.OPERATOR])
        self.assertEqual({w["note"] for w in report["waivedGates"]}, {self.NOTE})
        self.assertEqual(report["waiverNotNeeded"], [])
        self.assertEqual({w["gate"]: len(w["measured"]["failedChecks"]) for w in report["waivedGates"]},
                         {"lcdTimings": 2, "ledRenderTime": 2, "jpegDecode": 1, "ledFrameRate": 1, "limitPerPush": 1,
                          "limitEvents": 1})
        manifest = t.load_json(t.CC5_MANIFEST)
        self.assertEqual((manifest["waivedGates"], manifest["validation"]["waivedGates"],
                          t.load_json(self.diag / "validation.json")["cc5.4"]["waivedGates"]), (list(self.ALL_SIX),) * 3)
        self.assertIn("waived gates lcdTimings, ledRenderTime, jpegDecode, ledFrameRate (a known issue the user signed "
                      "off; the targets are unchanged) and limitPerPush, limitEvents (operator timing",
                      manifest["hardwareStatus"])
        self.assertIn("INSTALLED with waived gates: lcdTimings, ledRenderTime, jpegDecode, ledFrameRate, limitPerPush, "
                      "limitEvents (", self.out.getvalue().splitlines()[-1])
        # The recorded End stop proof of run 3: lim +1 at T_end in attempt 1's push phase (while held and outside the
        # windows), lim -1 after 0:00 in every attempt, the closest two lims (one direction) 1.747 s apart.
        records = {w["gate"]: w["measured"] for w in report["waivedGates"]}
        self.assertEqual(records["limitPerPush"]["proof"], {
            "limPlus": 3, "limMinus": 5, "limPlusInPushPhase": 2, "runsWithLimMinusAtZero": 3, "minSpacingS": 1.747,
            "minSpacingAllowedS": 0.1, "firmwareSpacingS": 0.15, "minSameDirectionSpacingS": 1.747,
            "minSameDirectionAllowedS": 0.5})
        self.assertEqual([run["stray"] for run in records["limitEvents"]["runs"]], [[[195.45, 1]], [], []])


# ---------------------------------------------------------------------------
# 1.0.0-cc5.3: profiles, artwork2 payloads and helpers, store parity, bridge and lease flows.

@needs_tooling
class ProfileTests(unittest.TestCase):
    """Release profiles: their files never collide, and the artwork2 contract comes from presentation.py."""

    FILES = ("image", "source_zip", "manifest", "build_log", "before_full", "rollback_app", "expected_full",
             "build_report", "backup_report", "preparation", "flash_checks", "device_checks", "lease_checks",
             "rollback_report", "installation")

    def test_profiles_never_share_a_file_name(self):
        names = [getattr(p, attr).name for p in t.PROFILES.values() for attr in self.FILES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(t.ROLLBACK_TARGETS), {"cc4", "cc5.2", "cc5.3"})
        self.assertEqual([p.version for p in t.PROFILES.values()],
                         ["1.0.0-cc5.2", "1.0.0-cc5.3", "1.0.0-cc5.4"])   # oldest first
        for cc5x, before, image_bytes, token in ((t.PROFILES["cc5.3"], t.PROFILES["cc5.2"], 1010656, "CC5_2"),
                                                 (t.CURRENT, t.PROFILES["cc5.3"], 1023648, "CC5_3")):
            with self.subTest(cc5x.tag):
                self.assertEqual((cc5x.from_image_bytes, cc5x.from_image.name),
                                 (image_bytes, f"nanod-control-center-{before.version}.bin"))
                self.assertEqual(cc5x.from_expected_full.name, before.expected_full.name)
                self.assertEqual(cc5x.from_preparation.name, before.preparation.name)
                self.assertEqual(cc5x.backup_family, (cc5x.version,))
                self.assertEqual((cc5x.restored_outcome, cc5x.restored_unconfirmed_outcome),
                                 (f"RESTORED_{token}_RESET", f"RESTORED_{token}_VERIFIED_RESET_UNCONFIRMED"))

    def test_the_real_installed_artefacts_match_the_profile(self):
        """Read only: the installed cc5.3 image (CURRENT upgrades from it) and its verified install image
        have the recorded hashes; the pre-cc5.4 backup is CURRENT's, the earlier pairs are history."""
        cc54 = t.CURRENT
        if not cc54.from_image.is_file():
            self.skipTest("firmware folder not present")
        self.assertEqual(t.sha256_file(cc54.from_image), cc54.from_image_sha256)
        self.assertEqual(cc54.from_image.stat().st_size, cc54.from_image_bytes)
        if cc54.from_expected_full.is_file():
            self.assertEqual(t.sha256_file(cc54.from_expected_full), cc54.from_expected_sha256)
        self.assertNotIn(cc54.before_full.name, t.history_backup_names())
        self.assertTrue({"nanod-cc4-before-cc5-full.bin", "nanod-cc4-before-cc5-active-app.bin",
                         "nanod-cc5.2-before-cc5.3-full.bin", "nanod-cc5.2-before-cc5.3-active-app.bin"}
                        <= t.history_backup_names())

    def test_artwork2_capability_is_loaded_from_the_companion_by_path(self):
        self.assertEqual(t.PRESENTATION_SOURCE, ROOT / "control_center" / "presentation.py")
        spec = importlib.util.spec_from_file_location("contract_under_test", t.PRESENTATION_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(t.artwork2_capability(), module.ARTWORK2_CAPABILITY)
        copy = t.artwork2_capability()
        copy["cover"]["entries"] = 0
        self.assertEqual(t.artwork2_capability()["cover"]["entries"], module.ARTWORK2_CAPABILITY["cover"]["entries"])
        caps = t.PROFILES["cc5.3"].expected_capabilities()
        self.assertEqual((caps["artwork"], caps["artwork2"], caps["presentation"]),
                         (t.EXPECTED_ARTWORK_CAPABILITY, module.ARTWORK2_CAPABILITY, 4))
        caps = t.CURRENT.expected_capabilities()           # cc5.4: presentation 5, artwork2 unchanged, alive
        self.assertEqual((caps["artwork"], caps["artwork2"], caps["presentation"], caps[module.ALIVE_CAPABILITY]),
                         (t.EXPECTED_ARTWORK_CAPABILITY, module.ARTWORK2_CAPABILITY, 5, t.alive_capability()))
        self.assertNotIn("artwork2", t.PROFILES["cc5.2"].expected_capabilities())
        # The contract values are never copied into the tooling (no duplicated literals).
        for name in ("nanod_cc5_tooling.py", "check_nanod_cc5.py", "check_nanod_cc5_lease.py", "finalize_nanod_cc5.py",
                     "package_nanod_cc5.py"):
            source = (WORK / name).read_text(encoding="utf-8")
            for literal in ('"haveKeys": 24', '"chunkBytes": 2048', '"rxBytes": 8192', '"maxBytes": 32768',
                            "(85, 80, 75, 70, 65, 60)"):
                self.assertNotIn(literal, source, (name, literal))

    def test_scripts_read_their_profile_not_the_static_names(self):
        """Every script takes its files from a profile (t.CURRENT or a rollback target), whose paths follow
        the folders; the module-level names are only the current profile's names for reference."""
        aliases = re.compile(r"\bt\.(CC5_VERSION|CC5_TAG|CC5_IMAGE|CC5_MANIFEST|CC5_SOURCE_ZIP|BUILD_LOG|BEFORE_FULL|"
                             r"ROLLBACK_APP|EXPECTED_FULL|BUILD_REPORT|BACKUP_REPORT|PREPARATION|FLASH_CHECKS|"
                             r"DEVICE_CHECKS|LEASE_CHECKS|ROLLBACK_REPORT|INSTALLATION|SUPERSEDED_CC5_VERSIONS|FROM_\w+)\b")
        for name in ("build_nanod_cc5.py", "package_nanod_cc5.py", "backup_nanod_cc5.py", "prepare_nanod_cc5_install.py",
                     "install_nanod_cc5.py", "rollback_nanod_cc5.py", "check_nanod_cc5.py", "check_nanod_cc5_lease.py",
                     "finalize_nanod_cc5.py"):
            self.assertEqual(aliases.findall((WORK / name).read_text(encoding="utf-8")), [], name)

    def test_jpeg_decode_gate(self):
        good = {"jpegDecodes": 12, "jpegDecodeErrors": 0, "jpegDecodeMsMax": 200, "jpegDecodeMsLast": 90}
        self.assertEqual(t.jpeg_decode_problems(good), [])
        self.assertEqual(t.JPEG_DECODE_MAX_MS, 200)
        self.assertIn("SLOW JPEG DECODE: jpegDecodeMsMax 201 ms > 200 ms",
                      t.jpeg_decode_problems({**good, "jpegDecodeMsMax": 201})[0])
        self.assertIn("JPEG DECODE ERRORS", t.jpeg_decode_problems({**good, "jpegDecodeErrors": 2})[0])
        self.assertIn("no cover was decoded", t.jpeg_decode_problems({**good, "jpegDecodes": 0})[0])
        self.assertIn("diag lacks integer jpegDecodeMsMax", t.jpeg_decode_problems({**good, "jpegDecodeMsMax": None})[0])
        self.assertEqual(t.jpeg_decode_problems(None), ["no diag reply"])
        summary = t.media_diag_summary({**good, "rxQueueBytes": 8192, "other": 1})
        self.assertEqual(set(summary), set(t.MEDIA_DIAG_FIELDS))
        self.assertEqual((t.media_counter(good, "jpegDecodes"), t.media_counter(good, "missing"),
                          t.media_counter({"x": True}, "x")), (12, None, None))


class MediaAdapter:
    """knob.media(body) over a FakeMedia store (for the tooling helpers)."""

    def __init__(self, media):
        self.media_store, self.sent = media, []

    def media(self, body):
        self.sent.append(body)
        return self.media_store.handle(body), 0.002


@needs_tooling
class Artwork2PayloadTests(unittest.TestCase):
    """Section 5 payloads from the design reference, and the media packets that carry them."""

    def test_the_cover_pool_is_real_section_5_covers(self):
        contract = t.presentation()
        covers = t.cover_pool()
        self.assertGreaterEqual(len(covers), 60)
        self.assertEqual(len({key for key, _ in covers}), len(covers))
        for key, jpeg in covers:
            self.assertEqual(t.cover_payload_problems(jpeg), [], key)
            self.assertEqual(key, hashlib.sha256(jpeg).hexdigest()[:contract.COVER_KEY_CHARS])
            self.assertTrue(media_key_ok(key))
        self.assertGreater(max(len(j) for _, j in covers), contract.MEDIA_CHUNK_BYTES * 3)   # multi-line covers
        self.assertEqual(t.cover_pool(10), covers[:10])

    def test_each_run_salts_its_payloads(self):
        """Committed covers and icons survive until the knob reboots, so a second check run on the same
        boot must not find the first run's keys (its cold uploads would be begin-hits)."""
        first, second = t.cover_pool(24, salt="run001"), t.cover_pool(24, salt="run002")
        self.assertFalse({k for k, _ in first} & {k for k, _ in second})
        self.assertFalse({k for k, _ in first} & {k for k, _ in t.cover_pool(24)})
        self.assertEqual(t.cover_pool(24, salt="run001"), first)                   # deterministic per salt
        self.assertEqual([t.cover_payload_problems(j) for _, j in first], [[]] * 24)
        icons = t.icon_pool(salt="run001")
        self.assertEqual(len({k for k, _ in icons}), 64)
        self.assertFalse({k for k, _ in icons} & {k for k, _ in t.icon_pool(salt="run002")})
        for name in ("check_nanod_cc5.py", "check_nanod_cc5_lease.py"):
            source = (WORK / name).read_text(encoding="utf-8")
            self.assertIn("t.MediaCursor(t.cover_pool(salt=run), t.icon_pool(salt=run))", source, name)
        self.assertIn('salt = f"bridge{uuid.uuid4().hex[:6]}"', (WORK / "check_nanod_cc5.py").read_text(encoding="utf-8"))

    def test_the_encoder_ladder_and_its_limit(self):
        from PIL import Image
        artwork, _ = t._companion_modules()
        preview = Image.new("RGB", (240, 240), (40, 90, 160))
        key, jpeg = t.cover_jpeg(preview)
        self.assertEqual(t.cover_payload_problems(jpeg), [])
        self.assertEqual((key, jpeg), artwork.cover_jpeg(preview))
        with mock.patch.object(artwork, "COVER_MAX_BYTES", 100):
            self.assertIsNone(t.cover_jpeg(preview))             # no ladder quality fits: no artwork2 cover

    def test_payloads_come_from_the_companion_encoders(self):
        """The covers and icons the checks send are the v4 companion's own section 5 payloads
        (artwork.prepare_artwork2 / cover_jpeg / icon_payload), never a copy of its encoder."""
        from PIL import Image
        artwork, windows = t._companion_modules()
        covers = sorted(p for p in (t.DESIGN_ASSETS / "covers").iterdir() if p.suffix.lower() in (".jpg", ".png"))
        pool = t.cover_pool(len(covers), salt="delegation")
        for (key, jpeg), path in zip(pool, covers):
            prepared = artwork.prepare_artwork2(t._cover_source(path, 0, "delegation"))
            self.assertEqual((key, jpeg), (prepared.jpeg_key, prepared.jpeg), path.name)
        icon = Image.new("RGBA", (32, 32), (200, 40, 90, 170))
        with mock.patch.object(artwork, "icon_payload", return_value=("sentinel", b"")) as encoder:
            self.assertEqual(t.icon_payload(icon), ("sentinel", b""))
        encoder.assert_called_once_with(icon)
        with mock.patch.object(artwork, "cover_jpeg", return_value=("k", b"jpeg")) as encoder:
            self.assertEqual(t.cover_jpeg(icon), ("k", b"jpeg"))
        encoder.assert_called_once_with(icon)
        apps = sorted(p for p in (t.DESIGN_ASSETS / "apps").iterdir() if p.suffix.lower() == ".png")
        with Image.open(apps[0]) as source:
            thumbnail = windows.icon_thumbnail(source.convert("RGBA"))
        self.assertEqual(t.icon_pool(1)[0], artwork.icon_payload(thumbnail))
        source = (WORK / "nanod_cc5_tooling.py").read_text(encoding="utf-8")
        for copied in ("subsampling=2, optimize=True", "(r * 31 + 127) // 255", "COVER_JPEG_QUALITIES:"):
            self.assertNotIn(copied, source)

    def test_the_validator_rejects_what_the_knob_must_reject(self):
        bad = t.bad_cover_payloads()
        self.assertIn("not baseline (SOF 0xC2)", t.cover_payload_problems(bad["progressive"]))
        self.assertIn("120x120, not 240x240", t.cover_payload_problems(bad["size120"]))
        self.assertEqual(t.cover_payload_problems(bad["notJpeg"]), ["not a JPEG (no SOI)"])
        key, good = t.cover_pool(1)[0]
        with_comment = good[:2] + b"\xff\xfe\x00\x04hi" + good[2:]
        self.assertIn("EXIF/ICC/comment segments ['0xFE']", t.cover_payload_problems(with_comment))
        self.assertIn("40000 B > 32768", t.cover_payload_problems(good + bytes(40000 - len(good))))
        # 4.3: a cover cut short (EOI missing, or the scan cut in half) or followed by a trailing byte.
        eoi = "does not end with EOI (FF D9): cut short or followed by trailing bytes"
        for name, cut in (("no EOI", good[:-2]), ("half", good[:len(good) // 2]), ("trailing byte", good + b"\x00")):
            problems = t.cover_payload_problems(cut)
            self.assertIn(eoi, problems, name)
        self.assertTrue(any(p.startswith("not decodable (") for p in t.cover_payload_problems(good[:len(good) // 2])))
        # Section 5: 8-bit samples, 4:2:0 or 4:4:4 (4:2:2 is refused although TJpgDec could decode it).
        from PIL import Image
        preview = Image.new("RGB", (240, 240), (40, 90, 160))
        shapes = {}
        for subsampling in (0, 1, 2):
            buffer = io.BytesIO()
            preview.save(buffer, format="JPEG", quality=80, subsampling=subsampling)
            shapes[subsampling] = t.cover_payload_problems(buffer.getvalue())
        self.assertEqual((shapes[0], shapes[2]), ([], []))
        self.assertEqual(shapes[1], ["sampling factors 2x1, 1x1, 1x1: not 4:2:0 or 4:4:4"])
        deep = bytearray(good)
        deep[deep.index(b"\xff\xc0") + 4] = 12
        self.assertIn("12-bit samples, not 8-bit", t.cover_payload_problems(bytes(deep)))

    def test_the_fake_firmware_check_follows_cc_jpeg_validate(self):
        """tjpgd_accepts, FakeMedia's commit check, models src/cc_jpeg.cpp: real covers pass; a cover cut
        short, followed by a trailing byte, progressive, 120 px or not a JPEG fails; 4:2:2 passes (the
        ROM decoder takes it; the host never sends it)."""
        key, good = t.cover_pool(1)[0]
        self.assertTrue(all(tjpgd_accepts(jpeg) for _, jpeg in t.cover_pool(12)))
        twelve = good.replace(b"\xff\xc0\x00\x11\x08", b"\xff\xc0\x00\x11\x0c", 1)
        self.assertNotEqual(twelve, good)
        for name, bad in {**t.bad_cover_payloads(), "no EOI": good[:-2], "half": good[:len(good) // 2],
                          "trailing byte": good + b"\x00", "12-bit": twelve,
                          "too large": good[:-2] + bytes(40000) + b"\xff\xd9"}.items():
            self.assertFalse(tjpgd_accepts(bad), name)
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (240, 240), (40, 90, 160)).save(buffer, format="JPEG", quality=80, subsampling=1)
        self.assertTrue(tjpgd_accepts(buffer.getvalue()))

    def test_icon_payload_rounding_and_the_pool(self):
        from PIL import Image
        icon = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        icon.putpixel((0, 0), (255, 255, 255, 255))
        icon.putpixel((1, 0), (255, 0, 0, 128))                  # 255*128/255 = 128 -> r5 (128*31+127)//255 = 16
        icon.putpixel((2, 0), (10, 200, 30, 255))
        key, raw = t.icon_payload(icon)
        self.assertEqual(len(raw), 2048)
        self.assertEqual(key, hashlib.sha256(raw).hexdigest()[:16])
        values = struct.unpack("<3H", raw[:6])
        self.assertEqual(values[0], 0xFFFF)
        self.assertEqual(values[1], 16 << 11)
        self.assertEqual(values[2], ((10 * 31 + 127) // 255) << 11 | ((200 * 63 + 127) // 255) << 5 | (30 * 31 + 127) // 255)
        self.assertEqual(raw[6:], bytes(2042))                    # transparent over black
        with self.assertRaises(ValueError):
            t.icon_payload(Image.new("RGBA", (16, 16)))
        icons = t.icon_pool()
        self.assertEqual(len(icons), 64)
        self.assertEqual(len({k for k, _ in icons}), 64)
        self.assertTrue(all(len(r) == 2048 and media_key_ok(k) for k, r in icons))
        self.assertEqual(t.synthetic_icon(3), t.synthetic_icon(3))
        cursor = t.MediaCursor(t.cover_pool(3), icons[:2])
        self.assertEqual([cursor.icon()[0] for _ in range(3)], [icons[0][0], icons[1][0], icons[0][0]])

    def test_media_messages_and_transfer(self):
        contract = t.presentation()
        key, jpeg = t.cover_pool(1)[0]
        messages = t.media_messages(7, "cover", key, jpeg)
        self.assertEqual(messages[0], {"id": 7, "op": "begin", "kind": "cover", "key": key, "bytes": len(jpeg),
                                       "crc32": zlib.crc32(jpeg) & 0xFFFFFFFF})
        data = messages[1:-1]
        self.assertEqual([m["offset"] for m in data], list(range(0, len(jpeg), contract.MEDIA_CHUNK_BYTES)))
        self.assertEqual(b"".join(base64.b64decode(m["data"]) for m in data), jpeg)
        self.assertEqual(messages[-1], {"id": 7, "op": "commit", "kind": "cover", "key": key})
        self.assertTrue(all(len(json.dumps({"media": m}, separators=(",", ":"))) < 4096 for m in messages))
        cap = t.artwork2_capability()
        store = FakeMedia({"cover": {"entries": 24, "slotBytes": 32768, "maxBytes": 32768},
                           "icon": {"entries": 48, "slotBytes": 2048, "bytes": 2048},
                           "chunkBytes": cap["chunkBytes"], "haveKeys": cap["haveKeys"], "validateJpeg": True})
        store.set_active(7)
        knob, between = MediaAdapter(store), []
        cold = t.media_transfer(knob, 7, "cover", key, jpeg, between=lambda: between.append(1))
        self.assertEqual((cold["beginOffset"], cold["hit"], cold["committed"], cold["chunks"]), (0, False, True, len(data)))
        self.assertEqual(len(between), len(messages))
        hit = t.media_transfer(knob, 7, "cover", key, jpeg)
        self.assertEqual((hit["hit"], hit["committed"], hit["chunks"], [m["op"] for m in knob.sent[-2:]]),
                         (True, True, 0, ["begin", "commit"]))
        self.assertEqual(t.media_have(knob, 7, "cover", [key, "zz"])["have"], [True, False])
        other, other_jpeg = t.cover_pool(2)[1]
        bad = t.media_transfer(knob, 7, "cover", other, other_jpeg, crc=1)
        self.assertEqual((bad["errorOp"], bad["error"], bad["committed"]), ("commit", "Media checksum mismatch", False))
        partial = t.media_transfer(knob, 7, "cover", other, other_jpeg, stop_after_chunks=1)
        self.assertEqual((partial["chunks"], partial["committed"]), (1, False))
        stale = t.media_transfer(knob, 6, "cover", key, jpeg)
        self.assertEqual((stale["errorOp"], stale["error"]), ("begin", "Stale media control"))


@needs_tooling
class MediaTraceParityTests(unittest.TestCase):
    """FakeMedia (the store the check tests run against) replays harness/media_store_traces.json
    exactly: every reply and every slot table, like the C++ store and the companion's FakeKnob."""

    def test_every_trace_replays_exactly(self):
        if not MEDIA_TRACES.is_file():
            self.skipTest("media_store_traces.json not present")
        data = json.loads(MEDIA_TRACES.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        cap = t.artwork2_capability()
        real = [c for c in data["cases"] if c["config"]["cover"]["entries"] == cap["cover"]["entries"]
                and c["config"]["icon"]["entries"] == cap["icon"]["entries"]]
        self.assertTrue(real, "at least one case with the real capability config")
        for case in data["cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(replay_trace(case), [])

    def test_a_wrong_store_is_caught_by_the_traces(self):
        if not MEDIA_TRACES.is_file():
            self.skipTest("media_store_traces.json not present")

        class NoPins(FakeMedia):
            def __init__(self, config):
                super().__init__(config)
                for store in self.stores.values():
                    store.pinned = lambda index: False

        data = json.loads(MEDIA_TRACES.read_text(encoding="utf-8"))
        self.assertTrue(any(replay_trace(case, NoPins) for case in data["cases"]))


class FakeBridge:
    """The v4 DeviceBridge surface bridge_media() uses (ARTWORK2.md section 9)."""

    def __init__(self, capability=None, fail_key=None, preempted_error=False):
        self.media_capability, self.fail_key, self.preempted_error = capability, fail_key, preempted_error
        self.events, self.calls = queue.Queue(), []

    def submit(self, command, value=None):
        self.calls.append((command, value))
        if command == "enter":
            self.events.put({"kind": "ready", "id": value["id"], "position": value["position"], "p": value["position"]})

    def set_media_wanted(self, kind, items):
        self.calls.append(("wanted", (kind, [key for key, _ in items])))
        if self.preempted_error and len(items) > 1:
            # A bridge that reports the preempted (demoted) key as failed instead of just moving on.
            self.events.put({"kind": "media-error", "key": items[1][0], "media": kind, "error": "preempted"})
        if items:
            key = items[0][0]
            event = "media-error" if key == self.fail_key else "media-ready"
            self.events.put({"kind": event, "key": key, "media": kind, **({"error": "timeout"} if key == self.fail_key else {})})


@needs_tooling
class BridgeMediaTests(unittest.TestCase):
    """check_nanod_cc5.bridge_media() against a fake v4 bridge (no port)."""

    def setUp(self):
        self.module = load_script("check_nanod_cc5.py")
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.controller, _, _, self.simulation = self.module.companion()

    def run_bridge(self, bridge):
        c = self.controller.Controller()
        c.state.update(self.simulation.SimulatedSonos().read_state())
        c.state_known, c.windows_hid_enabled = True, False
        report, out = self.module.Report("FAKEAPP"), {}
        cursor = t.MediaCursor(t.cover_pool(8), t.icon_pool(4))
        with mock.patch.object(self.module.Events, "quiet", lambda self, seconds, fail=None: []):
            ok = self.module.bridge_media(bridge, self.module.Events(bridge), c, self.controller, self.simulation,
                                          report, out, cursor)
        return ok, report, out

    def test_a_v4_bridge_that_delivers_passes(self):
        bridge = FakeBridge(t.artwork2_capability())
        ok, report, out = self.run_bridge(bridge)
        self.assertTrue(ok)
        self.assertEqual(report.data["failures"], [])
        self.assertTrue(all(out[k] is not None for k in ("coverSeconds", "iconSeconds", "preemptSeconds")))
        # Every selection's frame is written before its media is wanted (the knob pins it first).
        calls = bridge.calls
        for at, (command, value) in enumerate(calls):
            if command == "wanted" and value[1]:
                kind, keys = value
                field = "artKey" if kind == "cover" else "iconKey"
                frames = [i for i, (c, v) in enumerate(calls) if c == "frame" and v.get(field) == keys[0]]
                self.assertTrue(frames and frames[0] < at, (kind, keys))
        order = [(c, v) for c, v in calls if c == "wanted"]
        self.assertEqual(order[-2:], [("wanted", ("cover", [])), ("wanted", ("icon", []))])   # cleared at the end

    def test_no_negotiation_or_a_media_error_fails(self):
        with self.assertRaises(RuntimeError):
            self.run_bridge(FakeBridge(None))
        key = t.cover_pool(8)[0][0]
        with self.assertRaises(RuntimeError) as caught:
            self.run_bridge(FakeBridge(t.artwork2_capability(), fail_key=key))
        self.assertIn("media-error", str(caught.exception))
        capability = {**t.artwork2_capability(), "paced": True}
        ok, report, _ = self.run_bridge(FakeBridge(capability))
        self.assertFalse(ok)
        self.assertIn("bridge artwork2: DeviceBridge negotiated artwork2 (media_capability equals "
                      "presentation.ARTWORK2_CAPABILITY)", report.data["failures"])

    def test_a_media_error_for_another_key_fails_only_the_no_error_check(self):
        """The new selection still becomes ready, but the bridge reported the cover it preempted as a
        media-error: only the final no-media-error check catches it."""
        bridge = FakeBridge(t.artwork2_capability(), preempted_error=True)
        ok, report, out = self.run_bridge(bridge)
        self.assertFalse(ok)
        self.assertEqual(report.data["failures"], ["bridge artwork2: no media-error event and no error or release"])
        self.assertTrue(all(out[k] is not None for k in ("coverSeconds", "iconSeconds", "preemptSeconds")))
        wanted = [value[1] for command, value in bridge.calls if command == "wanted"]
        [preempting] = [keys for keys in wanted if len(keys) > 1]          # [new selection, the one it preempts]
        self.assertEqual([e["key"] for e in out["mediaErrors"]], [preempting[1]])


@needs_tooling
class LeaseFlowTests(HardwareFreeScriptTest):
    """check_nanod_cc5_lease.main() against a FakeFirmware that expires its 2 s lease (fake clock)."""
    script = "check_nanod_cc5_lease.py"

    def run_lease(self, firmware_class=FakeFirmware):
        clock = itertools.count(0, 0.001).__next__
        firmware = firmware_class(clock=clock, lease=True)
        real = t.RawKnob
        self.patch(t, "RawKnob", lambda port: real(port, serial_factory=lambda name: firmware, clock=clock,
                                                   sleep=lambda s: None))
        self.patch(t, "require_companion_quit", lambda: False)
        self.patch(t, "find_app_port", lambda *a, **k: "FAKEAPP")
        self.patch(self.module, "time", SimpleNamespace(monotonic=clock))
        code = self.module.main([])
        name, report = self.evidence[-1]
        self.assertEqual(name, t.LEASE_CHECKS.name)
        return code, report, firmware

    CASE_3B = ("frames continue during unpaced media transfers (frames before and inside the uploads, claimed > 2 "
               "lease periods, covers and icons all committed, no error or media error)")

    class CountsFramesInsideUploads(FakeFirmware):
        """Counts the frame lines of case 3b (control 207) that arrive while a cold upload is open."""
        inside = 0

        def line(self, text):
            upload = self.media.upload
            if text.startswith('{"frame"') and self.active == 207 and upload and not upload["hit"]:
                self.inside += 1
            return super().line(text)

    def test_media_lines_never_renew_and_frames_carry_unpaced_transfers(self):
        code, report, firmware = self.run_lease(self.CountsFramesInsideUploads)
        self.assertEqual((code, report["failures"]), (0, []))
        self.assertEqual(report["artwork2"], {"mediaOnlyDoesNotRenew": True, "framesDuringMediaTransfers": True})
        media_only = report["mediaOnly"]
        self.assertEqual(media_only["reason"], "lease-expired")
        self.assertTrue(1.5 <= media_only["secondsAfterReady"] <= 3.0 and media_only["okAcksBeforeRelease"] >= 3)
        self.assertTrue(media_only["unpaced"])
        during = report["framesDuringMediaTransfer"]
        self.assertTrue(during["passed"] and during["unpaced"] and during["transfers"] >= 2)
        # Every 3b upload is cold (new keys), so each gets at least one frame while it is open, and the
        # knob really received them inside the uploads (not only between them).
        self.assertGreaterEqual(during["framesInsideUploads"], during["transfers"])
        self.assertGreaterEqual(firmware.inside, during["framesInsideUploads"])
        self.assertEqual(during["committed"], during["transfers"])
        self.assertEqual(report["firmwareVersion"], t.CC5_VERSION)
        media = {shape for key, shape in firmware.shapes if key == "media"}
        art = {shape for key, shape in firmware.shapes if key == "art"}
        self.assertTrue("whole" in media and media <= {"whole", "short"}, media)
        self.assertTrue("paced" in art and art <= {"paced", "short"}, art)

    def test_a_firmware_whose_media_lines_renew_the_lease_fails(self):
        class Renews(FakeFirmware):
            def media_command(self, body):
                self.renewed = self.clock()
                return super().media_command(body)

        code, report, _ = self.run_lease(Renews)
        self.assertEqual(code, 1)
        self.assertFalse(report["artwork2"]["mediaOnlyDoesNotRenew"])
        self.assertIn("media lines alone do not renew the lease (have/begin/data/commit every ~150 ms, unpaced)",
                      report["failures"])

    def test_case_2b_needs_acknowledged_media_lines_before_the_expiry(self):
        """The lease expires on time, but no media line of case 2b was accepted: nothing showed that
        accepted media lines leave the lease alone."""
        class RefusesCase2b(FakeFirmware):
            def media_command(self, body):
                if self.active == 205:
                    self.media.errors += 1
                    return self.reply({"mediaAck": {"id": body.get("id"), "op": body.get("op"),
                                                    "kind": body.get("kind"), "error": "Media unavailable"}})
                return super().media_command(body)

        code, report, _ = self.run_lease(RefusesCase2b)
        self.assertEqual(code, 1)
        media_only = report["mediaOnly"]
        self.assertEqual((media_only["reason"], media_only["okAcksBeforeRelease"]), ("lease-expired", 0))
        self.assertTrue(1.5 <= media_only["secondsAfterReady"] <= 3.0)
        self.assertEqual(report["failures"],
                         ["media lines alone do not renew the lease (have/begin/data/commit every ~150 ms, unpaced)"])
        self.assertEqual(report["artwork2"], {"mediaOnlyDoesNotRenew": False, "framesDuringMediaTransfers": True})

    def test_a_release_during_case_3b_fails_it(self):
        """A release notice in the middle of the unpaced transfers (the knob keeps serving): every upload
        still commits with no error, only the release shows it."""
        class ReleasesIn3b(FakeFirmware):
            def line(self, text):
                super().line(text)
                if text.startswith('{"frame"') and self.active == 207 and not getattr(self, "notified", False):
                    self.notified = True
                    self.reply({"released": True, "reason": "lease-expired"})

        code, report, _ = self.run_lease(ReleasesIn3b)
        self.assertEqual(code, 1)
        during = report["framesDuringMediaTransfer"]
        self.assertEqual(len(during["released"]), 1)
        self.assertFalse(during["errors"] or during["mediaErrors"] or during["passed"])
        self.assertEqual(during["committed"], during["transfers"])
        self.assertEqual(report["failures"], [self.CASE_3B])
        self.assertEqual(report["artwork2"], {"mediaOnlyDoesNotRenew": True, "framesDuringMediaTransfers": False})

    def test_a_frame_that_ends_the_open_upload_fails_case_3b(self):
        """A knob that drops the open upload whenever a frame arrives: the frames written before each
        begin change nothing, only the frames inside the uploads show it (the next data line or the
        commit is answered "No matching media upload")."""
        class EndsUploadOnFrame(FakeFirmware):
            def show(self, frame):
                super().show(frame)
                if self.active == 207:
                    self.media.cancel()

        code, report, _ = self.run_lease(EndsUploadOnFrame)
        self.assertEqual(code, 1)
        during = report["framesDuringMediaTransfer"]
        self.assertGreater(during["framesInsideUploads"], 0)
        self.assertFalse(during["passed"] or during["errors"] or during["released"])
        self.assertEqual({ack["error"] for _, ack in during["mediaErrors"]}, {"No matching media upload"})
        self.assertLess(during["committed"], during["transfers"])
        self.assertEqual(report["failures"], [self.CASE_3B])
        self.assertEqual(report["artwork2"], {"mediaOnlyDoesNotRenew": True, "framesDuringMediaTransfers": False})

    def test_case_3b_without_a_frame_inside_an_upload_does_not_pass(self):
        """If no frame reached the knob while an upload was open (here: the mid-upload frames never
        fire), every upload still commits cleanly, but 3b did not show what it claims."""
        self.patch(self.module, "last_media_ack", lambda knob: {})
        code, report, firmware = self.run_lease(self.CountsFramesInsideUploads)
        self.assertEqual(code, 1)
        during = report["framesDuringMediaTransfer"]
        self.assertEqual((during["framesInsideUploads"], firmware.inside), (0, 0))
        self.assertFalse(during["passed"] or during["errors"] or during["released"] or during["mediaErrors"])
        self.assertEqual(during["committed"], during["transfers"])
        self.assertEqual(report["failures"], [self.CASE_3B])

    def test_case_3b_shorter_than_two_lease_periods_does_not_pass(self):
        """Only a transfer run longer than two lease periods (>= 4 s) shows that frames keep the control
        claimed: a 2 s run, clean in every other way, does not pass."""
        seconds, *rest = self.module.frames_during_media.__defaults__
        self.assertEqual(seconds, 5.0)
        self.patch(self.module.frames_during_media, "__defaults__", (2.0, *rest))
        code, report, _ = self.run_lease()
        self.assertEqual(code, 1)
        during = report["framesDuringMediaTransfer"]
        self.assertLess(during["seconds"], 4.0)
        self.assertGreater(during["framesInsideUploads"], 0)
        self.assertFalse(during["passed"] or during["errors"] or during["released"] or during["mediaErrors"])
        self.assertEqual(report["failures"], [self.CASE_3B])

    def test_a_frame_refused_inside_an_open_upload_fails_case_3b(self):
        """The knob keeps the upload and the lease but answers each frame written while a cold upload is
        open with a bare error: the frames before each begin still renew the lease and every upload
        commits, so only the errors condition shows it."""
        class RefusesFramesInsideUploads(FakeFirmware):
            refused = 0

            def line(self, text):
                upload = self.media.upload
                if text.startswith('{"frame"') and self.active == 207 and upload and not upload["hit"]:
                    self.refused += 1
                    return self.reply({"error": "Stale control frame"})
                return super().line(text)

        code, report, firmware = self.run_lease(RefusesFramesInsideUploads)
        self.assertEqual(code, 1)
        during = report["framesDuringMediaTransfer"]
        self.assertGreater(firmware.refused, 0)
        self.assertEqual({error for _, error in during["errors"]}, {"Stale control frame"})
        self.assertFalse(during["passed"] or during["released"] or during["mediaErrors"])
        self.assertEqual(during["committed"], during["transfers"])
        self.assertEqual(report["failures"], [self.CASE_3B])

    def test_an_upload_acknowledged_short_fails_case_3b(self):
        """One case 3b commit is acknowledged with the wrong offset and no error: no error reply, media
        error or release anywhere, and the run goes on, so only the committed condition shows it."""
        class ShortCommitIn3b(FakeFirmware):
            shorted = False

            def media_command(self, body):
                if self.active == 207 and not self.shorted and isinstance(body, dict) and body.get("op") == "commit":
                    self.shorted = True
                    return self.reply({"mediaAck": {**self.media.handle(body), "offset": 0}})
                return super().media_command(body)

        code, report, firmware = self.run_lease(ShortCommitIn3b)
        self.assertEqual(code, 1)
        during = report["framesDuringMediaTransfer"]
        self.assertTrue(firmware.shorted)
        self.assertFalse(during["errors"] or during["released"] or during["mediaErrors"])
        self.assertGreaterEqual(during["seconds"], 4.0)
        self.assertEqual(during["committed"], during["transfers"] - 1)
        self.assertEqual(report["failures"], [self.CASE_3B])

    def test_case_2b_needs_the_lease_expired_reason(self):
        """The media-only control is released on time but with another reason: not a lease expiry."""
        class OtherReason(FakeFirmware):
            def check_lease(self):
                if self.lease and self.clock and self.active == 205 and self.clock() - self.renewed > 2.0:
                    self.set_active(None)
                    self.reply({"released": True, "reason": "other"})
                    return
                super().check_lease()

        code, report, _ = self.run_lease(OtherReason)
        self.assertEqual(code, 1)
        media_only = report["mediaOnly"]
        self.assertEqual(media_only["reason"], "other")
        self.assertTrue(1.5 <= media_only["secondsAfterReady"] <= 3.0 and media_only["okAcksBeforeRelease"] >= 3)
        self.assertEqual(report["failures"],
                         ["media lines alone do not renew the lease (have/begin/data/commit every ~150 ms, unpaced)"])


@needs_tooling
class Cc54ProfileTests(unittest.TestCase):
    """The 1.0.0-cc5.4 profile (ALIVE.md revision 2, PRESENTATION_V5.md): presentation 5, the alive
    capability, its gates and memory gates. CURRENT since the release tooling moved to the combined
    cc5.4 + desktop v7 release."""

    def test_the_cc5_4_profile(self):
        cc54 = t.PROFILES["cc5.4"]
        self.assertIs(t.NEWEST, cc54)
        self.assertIs(t.CURRENT, cc54)
        self.assertTrue(cc54.alive and cc54.artwork2)
        self.assertFalse(t.PROFILES["cc5.3"].alive)
        self.assertEqual((cc54.presentation, t.PROFILES["cc5.3"].presentation, t.PROFILES["cc5.2"].presentation), (5, 4, 4))
        self.assertEqual(cc54.gates, t.CC52_DEVICE_GATES + t.ARTWORK2_DEVICE_GATES + t.ALIVE_DEVICE_GATES
                         + t.PRESENTATION5_DEVICE_GATES)
        self.assertEqual(len(set(cc54.gates)), len(cc54.gates))
        self.assertEqual(t.ALIVE_DEVICE_GATES, ("aliveCapability", "ledFrameRate", "ledRenderTime", "limitEvents",
                                                "limitPerPush", "noErrorReplies"))
        self.assertEqual(t.PRESENTATION5_DEVICE_GATES, ("presentation5Capability", "readyKeyState", "holdEvents",
                                                        "holdDeferred", "hidIconGate", "lcdTimings"))
        caps = cc54.expected_capabilities()
        self.assertEqual(caps["presentation"], 5)
        self.assertEqual(caps[t.presentation().ALIVE_CAPABILITY], {"version": 1, "fps": 60, "drive": 150})
        self.assertEqual(caps["artwork2"], t.artwork2_capability())
        self.assertEqual((cc54.heap_min_free, cc54.lvgl_min_free), (40960, 30720))
        self.assertEqual((t.PROFILES["cc5.3"].heap_min_free, t.PROFILES["cc5.3"].lvgl_min_free), (None, None))
        self.assertEqual(cc54.device_checks.name, "cc5.4-device-checks.json")
        # ALIVE.md 11.9 numbers.
        self.assertEqual((t.ALIVE_LED_FPS_IDLE_MIN, t.ALIVE_LED_SHOW_GAP_IDLE_MAX_MS, t.ALIVE_LED_FPS_TRANSFER_MIN,
                          t.ALIVE_LED_FPS_TRANSFER_TARGET, t.ALIVE_LED_RENDER_US_MAX, t.ALIVE_LIM_REARM_MS),
                         (58, 20, 45, 55, 3000, 75))

    def test_alive_capability_follows_led_max_brightness(self):
        self.assertEqual(t.alive_capability(80)["drive"], 80)
        self.assertEqual(t.alive_capability(255)["drive"], 150)
        caps = {"alive": {"version": 1, "fps": 60, "drive": 80}, "presentation": 5}
        self.assertEqual(t.alive_capability_problems(caps, 80), [])
        self.assertIn("expected", t.alive_capability_problems(caps, 200)[0])
        self.assertEqual(t.alive_capability_problems({"alive": {"version": 1, "fps": 60, "drive": 150}}, None), [])
        self.assertTrue(t.alive_capability_problems({}, 150))
        self.assertEqual(t.presentation_capability_problems(caps, t.PROFILES["cc5.4"]), [])
        self.assertTrue(t.presentation_capability_problems({"presentation": 4}, t.PROFILES["cc5.4"]))

    def test_the_build_only_heap_projection(self):
        """PRESENTATION_V5 12.4: 57,072 - (ramUsedBytes - 245,056) - 1,024 - H >= 45,056."""
        round2 = t.heap_projection(259328)                   # the round-2 ALIVE build, DMA descriptors counted
        self.assertEqual((round2["ramDeltaVsCc53"], round2["heapMinFreeProjected"]), (14272, 41264))
        self.assertFalse(round2["passed"])
        funded = t.heap_projection(259328 + 180 + 12032 + 4446 - 53964)   # + v5 state, R3, R5; F1 funds it
        self.assertTrue(funded["passed"])
        self.assertEqual(t.heap_projection(245056, dma=False)["heapMinFreeProjected"], 57072 - 1024)


@needs_tooling
class Cc54HelperTests(unittest.TestCase):
    """The pure 1.0.0-cc5.4 device-check helpers (LED, LCD, hold, End stop, ready ks)."""

    def test_led_idle(self):
        self.assertEqual(t.led_idle_problems({"ledFps": 60, "ledShowGapMsMax": 17}), [])
        self.assertEqual(t.led_idle_problems({"ledFps": 58, "ledShowGapMsMax": 20}), [])
        self.assertIn("LED FRAME RATE AT IDLE: ledFps 57 < 58", t.led_idle_problems({"ledFps": 57, "ledShowGapMsMax": 17}))
        self.assertIn("LED SHOW GAP AT IDLE: ledShowGapMsMax 21 ms > 20 ms",
                      t.led_idle_problems({"ledFps": 60, "ledShowGapMsMax": 21}))
        self.assertIn("older than 1.0.0-cc5.4", t.led_idle_problems({"ledFps": 60})[0])

    def test_led_under_load(self):
        samples = [{"ledFps": 60, "ledShowGapMsMax": 17, "ledLateShows": 3},
                   {"ledFps": 50, "ledShowGapMsMax": 31, "ledLateShows": 7}]
        summary = t.led_load_summary(samples)
        self.assertTrue(summary["passed"])
        self.assertFalse(summary["targetMet"])                    # 50: passes, below the 55 target (recorded)
        self.assertEqual((summary["ledFpsMin"], summary["ledShowGapMsMax"], summary["ledLateShows"]), (50, 31, 4))
        low = t.led_load_summary(samples + [{"ledFps": 44}])
        self.assertFalse(low["passed"])
        self.assertIn("LED FRAME RATE UNDER LOAD: ledFps 44 < 45", low["problems"])
        self.assertFalse(t.led_load_summary([])["passed"])
        self.assertTrue(t.led_load_summary([{"ledFps": 59}] * 3)["targetMet"])

    def test_led_render(self):
        self.assertEqual(t.led_render_problems({"ledRenderUsMax": 3000}), [])
        self.assertIn("ledRenderUsMax 3001 us > 3000 us", t.led_render_problems({"ledRenderUsMax": 3001})[0])
        self.assertTrue(t.led_render_problems({}))

    def test_lcd_binary_and_targets(self):
        a = {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True}
        self.assertEqual(t.lcd_binary(a), "A")
        self.assertEqual(t.lcd_binary({**a, "lcdPeriodMs": 20}), "A")          # the measured scan period (P5-R12)
        self.assertEqual(t.lcd_binary({"lcdDma": True, "lcdPeriodMs": 33, "artAsync": False}), "B")
        self.assertEqual(t.lcd_binary({"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False}), "C")
        self.assertIsNone(t.lcd_binary({}))
        self.assertIsNone(t.lcd_binary({"lcdDma": False, "lcdPeriodMs": 16, "artAsync": True}))
        self.assertEqual(t.lcd_timing_problems({"lcdFpsAnimMin": 55, "lcdLateRefrs": 0}, "A", "opaque", 0), [])
        self.assertIn("lcdFpsAnimMin 54 < 55", t.lcd_timing_problems({"lcdFpsAnimMin": 54, "lcdLateRefrs": 0},
                                                                      "A", "opaque", 0)[0])
        self.assertEqual(t.lcd_timing_problems({"lcdFpsAnimMin": 45, "lcdLateRefrs": 3}, "A", "blended"), [])
        self.assertIn("2 during the pass", t.lcd_timing_problems({"lcdFpsAnimMin": 60, "lcdLateRefrs": 2}, "A", "opaque",
                                                                 2)[0])
        self.assertEqual(t.lcd_timing_problems({"lcdFpsAnimMin": 28, "lcdLateRefrs": 0}, "C", "opaque", 0), [])
        self.assertTrue(t.lcd_timing_problems({"lcdFpsAnimMin": 27}, "B", "blended"))
        self.assertIn("does not identify binary", t.lcd_timing_problems({"lcdFpsAnimMin": 60}, None, "opaque")[0])
        self.assertIn("no lcdLateRefrs count", t.lcd_timing_problems({"lcdFpsAnimMin": 60}, "A", "opaque")[0])
        self.assertEqual(set(t.lcd_diag_summary({"lcdFps": 60, "other": 1, "stackArtDec": 3000})), {"lcdFps", "stackArtDec"})

    def test_late_refreshes_are_counted_over_the_pass_only(self):
        """WP9a-R3: 12.3 does not say whether lcdLateRefrs resets on read; B and C count late refreshes at the
        earlier sections' cover arrivals (12.2, 12.6), so the opaque gate takes the pass's own count."""
        late = lambda n: {"lcdLateRefrs": n}                            # noqa: E731
        since, reset = t.LATE_SINCE_BOOT, t.LATE_RESET_ON_READ
        # Two reads back to back at rest tell the two readings apart when anything was counted before.
        self.assertEqual(t.late_refresh_semantics(late(4), late(4)), since)
        self.assertEqual(t.late_refresh_semantics(late(4), late(0)), reset)
        self.assertIsNone(t.late_refresh_semantics(late(0), late(0)))
        self.assertIsNone(t.late_refresh_semantics({}, late(0)))
        # Since boot with a non-zero baseline (4 from cover arrivals): no late refresh in the pass passes...
        count = t.lcd_late_refreshes(since, late(4), late(4), late(4))
        self.assertEqual(count, 0)
        self.assertEqual(t.lcd_timing_problems({**late(4), "lcdFpsAnimMin": 30}, "B", "opaque", count), [])
        # ...the old absolute gate would have failed it; two new ones fail.
        self.assertEqual(t.lcd_late_refreshes(since, late(4), late(5), late(6)), 2)
        self.assertIn("2 during the pass", t.lcd_timing_problems({**late(6), "lcdFpsAnimMin": 30}, "B", "opaque", 2)[0])
        # Reset on read: the lead read resets it, so the pass is lead + end, whatever the rest reads were.
        self.assertEqual(t.lcd_late_refreshes(reset, late(0), late(0), late(0)), 0)
        self.assertEqual(t.lcd_late_refreshes(reset, late(0), late(1), late(2)), 3)
        self.assertEqual(t.lcd_late_refreshes(reset, late(4), late(0), late(3)), 3)       # never end - before
        # Unknown (both rest reads 0): lead + end is 0 exactly when neither reading saw a late refresh.
        self.assertEqual(t.lcd_late_refreshes(None, late(0), late(0), late(0)), 0)
        self.assertEqual(t.lcd_late_refreshes(None, late(0), late(1), late(1)), 2)          # since boot: 1 (non-zero)
        self.assertEqual(t.lcd_late_refreshes(None, late(0), late(2), late(1)), 3)          # went down: reset on read
        self.assertIsNone(t.lcd_late_refreshes(since, late(0), {}, late(0)))

    def test_ready_key_state(self):
        self.assertEqual(t.ready_key_state_problems([{"ready": 3, "p": 0, "ks": 0}, {"ready": 4, "p": 0, "ks": 15}]), [])
        self.assertTrue(t.ready_key_state_problems([{"ready": 3, "p": 0}]))
        self.assertTrue(t.ready_key_state_problems([{"ready": 3, "p": 0, "ks": 16}]))
        self.assertTrue(t.ready_key_state_problems([{"ready": 3, "p": 0, "ks": True}]))
        self.assertEqual(t.ready_key_state_problems([]), ["no ready line seen"])

    def test_limit_events_and_spacing(self):
        messages = [(1.0, {"id": 7, "lim": 1}), (1.3, {"id": 7, "lim": -1}), (1.35, {"id": 8, "lim": 1}),
                    (2.0, {"id": 7, "p": 3}), (2.5, {"id": 7, "lim": 2})]
        lims = t.limit_events(messages, 7)
        self.assertEqual(lims, [(1.0, 1), (1.3, -1)])
        self.assertEqual(t.limit_problems(lims), [])
        self.assertEqual(t.limit_problems([(1.0, 1)]), ["no lim -1 seen"])
        self.assertIn("closer than 150 ms", t.limit_problems([(1.0, 1), (1.05, -1)])[0])
        self.assertEqual(t.limit_events(messages, 7, start=1.1), [(1.3, -1)])

    def test_limit_per_push(self):
        pushes = [(0.0, 1.4), (1.6, 3.0), (3.2, 4.6)]
        hold = (5.0, 8.0)
        good = [(0.3, 1), (1.9, 1), (3.5, 1), (5.3, 1)]
        self.assertTrue(t.limit_push_problems(good, pushes, hold)["passed"])
        chatter = t.limit_push_problems(good + [(0.5, 1)], pushes, hold)
        self.assertEqual(chatter["perPush"], [2, 1, 1])
        self.assertFalse(chatter["passed"])
        missed = t.limit_push_problems([(0.3, 1), (3.5, 1), (5.3, 1)], pushes, hold)
        self.assertEqual(missed["perPush"], [1, 0, 1])
        held_twice = t.limit_push_problems(good + [(6.5, 1)], pushes, hold)
        self.assertEqual(held_twice["held"], 2)
        stray = t.limit_push_problems(good + [(9.5, 1)], pushes, hold)
        self.assertEqual(stray["stray"], [(9.5, 1)])
        self.assertFalse(stray["passed"])
        # A lim arriving just after its window (line latency) still counts for it.
        self.assertTrue(t.limit_push_problems([(0.3, 1), (3.1, 1), (3.5, 1), (5.3, 1)], pushes, hold)["passed"])

    def test_hold_check(self):
        messages = [(1.0, {"id": 9, "ks": 1, "kd": 0}), (1.64, {"id": 9, "ks": 1, "kh": 0}),
                    (3.0, {"id": 9, "ks": 0, "ku": 0})]
        problems, khs = t.hold_check(messages, 9, 0, 0, 1.0, 3.6)
        self.assertEqual((problems, len(khs)), ([], 1))
        twice = messages + [(2.0, {"id": 9, "ks": 1, "kh": 0})]
        self.assertIn("2 kh for one hold", t.hold_check(twice, 9, 0, 0, 1.0, 3.6)[0][0])
        early = [(1.0, {"id": 9, "ks": 1, "kd": 0}), (1.2, {"id": 9, "ks": 1, "kh": 0})]
        self.assertIn("200 ms after the kd", t.hold_check(early, 9, 0, 0, 1.0, 3.0)[0][0])
        no_bit = [(1.0, {"id": 9, "ks": 1, "kd": 0}), (1.64, {"id": 9, "ks": 2, "kh": 0})]
        self.assertIn("does not have Button 1's bit", t.hold_check(no_bit, 9, 0, 0, 1.0, 3.0)[0][0])
        other = [(1.0, {"id": 9, "ks": 2, "kd": 1}), (1.64, {"id": 9, "ks": 2, "kh": 1})]
        self.assertIn("only raw 0", t.hold_check(other, 9, 1, 0, 1.0, 3.0)[0][0])
        self.assertEqual(t.hold_check([(1.0, {"id": 9, "ks": 2, "kd": 1})], 9, 1, 0, 1.0, 3.0)[0], [])
        self.assertEqual(t.kh_events(twice, 1.9, 2.1), [(2.0, {"id": 9, "ks": 1, "kh": 0})])
        # WP9a-R5: `until` is the end of the listening after the key-up; a kh after the ku is counted.
        released = messages + [(3.02, {"id": 9, "ks": 0, "kh": 0})]
        self.assertIn("2 kh for one hold", t.hold_check(released, 9, 0, 0, 1.0, 3.0 + 0.6)[0][0])
        other_late = [(1.0, {"id": 9, "ks": 2, "kd": 1}), (3.0, {"id": 9, "ks": 0, "ku": 1}),
                      (3.02, {"id": 9, "ks": 0, "kh": 1})]
        self.assertIn("only raw 0", t.hold_check(other_late, 9, 1, 0, 1.0, 3.0 + 0.6)[0][0])

    def test_knob_events_raw_control_and_margins(self):
        self.assertTrue(t.is_knob_event({"id": 3, "ks": 1, "kh": 0}))
        self.assertTrue(t.is_knob_event({"id": 3, "lim": 1}))
        self.assertFalse(t.is_knob_event({"ready": 3, "p": 0, "ks": 0}))
        control = t.raw_control(5, "P", 10, 2, {"title": "x"}, windows_button=3, windows_hid=True)
        self.assertEqual((control["windowsButton"], control["windowsHidEnabled"]), (3, True))
        self.assertFalse(t.raw_control(5, "P", 10, 2, {"title": "x"})["windowsHidEnabled"])
        cc54 = t.PROFILES["cc5.4"]
        good = {"heapMinFree": 41000, "lvglMinFree": 31000, "stackLcd": 5000, "stackCom": 5000, "stackHmi": 5000,
                "stackFoc": 5000, "artAsync": True, "stackArtDec": 1500}
        self.assertTrue(t.diag_margins(good, profile=cc54)["passed"])
        self.assertTrue(t.diag_margins({**good, "heapMinFree": 40500})["passed"])          # cc5.3's 40,000 gate
        self.assertFalse(t.diag_margins({**good, "heapMinFree": 40500}, profile=cc54)["passed"])
        self.assertFalse(t.diag_margins({**good, "lvglMinFree": 30000}, profile=cc54)["passed"])
        self.assertTrue(t.diag_margins({**good, "lvglMinFree": 30000})["passed"])            # 25 % of 64 KB
        self.assertFalse(t.diag_margins({**good, "stackArtDec": 1000}, profile=cc54)["passed"])
        self.assertTrue(t.diag_margins({**good, "artAsync": False, "stackArtDec": 0}, profile=cc54)["passed"])
        self.assertFalse(t.diag_margins({k: v for k, v in good.items() if k != "stackArtDec"}, profile=cc54)["passed"])
        self.assertNotIn("stackArtDec", t.diag_margins(good)["checks"])

    def test_raw_knob_records_ready_lines_and_hold_or_limit_as_touch(self):
        port = FakeSerial(b'{"ready":4,"p":2,"ks":1}\n{"id":4,"lim":1}\n{"id":4,"ks":1,"kh":0}\n')
        knob = t.RawKnob("COMA", serial_factory=lambda name: port, clock=itertools.count(0, 0.01).__next__,
                         sleep=lambda s: None)
        reply = knob.enter({"id": 4, "frame": {"id": 4}})
        self.assertEqual(reply["ks"], 1)
        self.assertEqual([r for _, r in knob.ready_replies], [{"ready": 4, "p": 2, "ks": 1}])
        knob.pump(0.1)
        self.assertEqual([m for _, m in knob.claimed_events], [{"id": 4, "lim": 1}, {"id": 4, "ks": 1, "kh": 0}])


class FakeFirmware54(FakeFirmware):
    """FakeFirmware answering like 1.0.0-cc5.4 (presentation 5, alive); the person at the knob is a FakeOperator
    reading its screen. Key events carry ks (and hid on Button 4 where the F24 gate allows it); a long press of raw
    0 (LONG_PRESS_S, or `long_press_s`, one value per press of raw 0, the last repeating) sends kh; a long press
    that matures while a control enters is deferred to right after its ready line (diag holdDeferred), as
    PRESENTATION_V5 11.2 step 5. A ready line follows a control after ENTER_S (the entry) and carries ks.
    End stop pushes send `push_lims` lim events each (an int, or one count per push); turning sends a lim at each
    end of the range (stress_lims).

    Its LCD refreshes only while something animates, as LVGL does: a layout change runs a 380 ms slide
    (contentTx), an art show/hide a 240 ms fade (artOpa); an identical frame (heartbeat) is inert. diag
    lcdFpsAnimMin is the lowest whole-second refresh count among the seconds since the previous read that
    had any animation (reset on read), at lcd["lcdFpsAnimMin"] refreshes per animated second, so a pass that
    leaves the panel idle for part of a second reads low (PRESENTATION_V5 12.3). lcdLateRefrs counts since
    boot (late_on_cover per cover decode, late_per_change per screen change) or, with late_reset_on_read,
    resets on read."""
    ENTER_S = 0.25                   # an entry with a cover decode (binaries B and C), 250 ms
    LONG_PRESS_S = 0.62
    SLIDE_S, ART_FADE_S = 0.38, 0.24 # contentTx, artOpa (PRESENTATION_V5 8.8)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.long_press_s, self.long_presses = None, 0     # per press of raw 0: None = LONG_PRESS_S
        self.hold_events, self.hold_deferred = 0, 0
        self.pending_hold, self.ready_due = False, None
        self.control_doc, self.frame_doc = None, {}
        self.kh_extra = False            # a second kh after the first (a firmware bug)
        self.kh_other_buttons = False    # kh for Button 2 too
        self.kh_on_release = ()          # raws that send a stray kh 20 ms after their ku (a firmware bug)
        self.defer = True                # False: long presses never defer
        self.ready_ks = True
        self.push_lims = 1               # lim per push (an int, or a list: one count per push, the last repeating)
        self.zero_lim = True
        self.hid_everywhere = False
        self.stress_lims = True
        self.led = {"ledFps": 60, "ledShowGapMsMax": 17, "ledLateShows": 0, "ledRenderUsMax": 1800,
                    "ledRenderUsAvg": 900, "ledMode": "alive"}
        # lcdFpsAnimMin here is the refresh rate of a WHOLE animated second; diag reports the duty-cycle model.
        self.lcd = {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True, "lcdFpsAnimMin": 58,
                    "enterMsMax": 120, "enterMsLast": 90, "stackArtDec": 2500, "lcdFps": 60}
        self.anims, self.lcd_screen, self.lcd_read_at = [], None, 0.0
        self.late_refrs = 0              # lcdLateRefrs
        self.late_on_cover = 0           # late refreshes per cover decode (B and C: a decode on the render path)
        self.late_per_change = 0         # late refreshes per screen change (jank)
        self.late_reset_on_read = False
        self.memory = {"heapMinFree": 46000, "lvglMinFree": 31500}
        self.received = []               # every line the host wrote, in order

    def capabilities(self):
        return {**super().capabilities(), "presentation": 5, "alive": t.alive_capability(150)}

    def diag_extra(self):
        late = self.late_refrs
        if self.late_reset_on_read:
            self.late_refrs = 0
        return {**self.led, **self.lcd, **self.memory, "holdEvents": self.hold_events,
                "holdDeferred": self.hold_deferred, "lcdFpsAnimMin": self.fps_anim_min(), "lcdLateRefrs": late}

    def fps_anim_min(self):
        """Lowest refresh count of the whole seconds [k, k + 1) since the previous read with any animation
        in them (0 when there is none); reset on read."""
        start, end = self.lcd_read_at, self.now()
        self.lcd_read_at = end
        spans = []
        for a, b in sorted(self.anims):                     # merge overlapping tweens
            if spans and a <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
        counts = []
        for k in range(math.ceil(start), math.floor(end)):
            animated = sum(max(0.0, min(b, k + 1) - max(a, k)) for a, b in spans)
            if animated > 0:
                counts.append(round(self.lcd["lcdFpsAnimMin"] * min(1.0, animated)))
        self.anims = [(a, b) for a, b in self.anims if b > end]
        return min(counts) if counts else 0

    def decoded(self):
        super().decoded()
        self.late_refrs += self.late_on_cover

    @property
    def sweep_lims(self):
        return self.stress_lims

    # --- key events, long presses and End stop lims (the firmware side of the person's hands) -----
    def key_down(self, raw):
        self.keys |= 1 << raw
        message = self.event(ks=self.keys, kd=raw)
        if raw == 3 and self.hid_allowed():
            message["hid"] = 1
        self.emit(message)
        if raw == 0 or self.kh_other_buttons:
            delay = self.LONG_PRESS_S
            if raw == 0 and self.long_press_s:
                delay = self.long_press_s[min(self.long_presses, len(self.long_press_s) - 1)]
                self.long_presses += 1
            self.schedule(delay, lambda: self.long_press(raw))

    def key_up(self, raw):
        self.keys &= ~(1 << raw)
        self.pending_hold = False
        self.emit(self.event(ks=self.keys, ku=raw))
        if raw in self.kh_on_release:
            self.schedule(0.02, lambda: self.emit(self.event(ks=self.keys, kh=raw)))

    def end_push(self, direction=1):
        counts = self.push_lims if isinstance(self.push_lims, (list, tuple)) else [self.push_lims]
        count = counts[min(self.pushes, len(counts) - 1)]
        self.pushes += 1
        if direction == -1 and not self.zero_lim:
            return
        for n in range(count):
            self.schedule(0.2 * n, lambda: self.emit(self.event(lim=direction)))

    def hid_allowed(self):
        control, frame = self.control_doc or {}, self.frame_doc or {}
        buttons = frame.get("buttons") or [{}] * 4
        return bool(control.get("windowsHidEnabled")) and control.get("windowsButton") == 3 and (
            self.hid_everywhere or (buttons[3].get("icon") == "win" and buttons[3].get("enabled") is True))

    def long_press(self, raw):
        if not self.keys & (1 << raw):
            return
        if self.ready_due is not None and self.defer:           # entering: latch, send after ready
            self.pending_hold = True
            return
        self.send_kh(raw)

    def send_kh(self, raw):
        self.hold_events += 1
        self.emit({"id": self.active, "ks": self.keys, "kh": raw})
        if self.kh_extra:
            self.emit({"id": self.active, "ks": self.keys, "kh": raw})

    def show(self, frame):
        self.frame_doc = frame
        super().show(frame)
        if self.clock:                                      # the LCD animates on a change only (8.1 rule 6)
            now, layout = self.now(), frame.get("layout")
            art = layout not in ("windows", "idle", "notice") and bool(frame.get("artKey"))
            if self.lcd_screen is not None and layout != self.lcd_screen[0]:
                self.anims.append((now, now + self.SLIDE_S))
                self.late_refrs += self.late_per_change
            if self.lcd_screen is not None and art != self.lcd_screen[1]:
                self.anims.append((now, now + self.ART_FADE_S))
            self.lcd_screen = (layout, art)

    def line(self, text):
        self.received.append(text)
        try:
            doc = json.loads(text) if len(text) <= 4096 else None
        except ValueError:
            doc = None
        if isinstance(doc, dict) and "control" in doc:
            control = doc["control"]
            self.lines += 1
            if control["id"] <= self.last_id:
                return self.reply({"error": "Control ID must advance; wait for release before reconnecting"})
            self.set_active(control["id"])
            self.last_id = control["id"]
            self.renewed = self.clock() if self.clock else 0.0
            self.control_doc, self.position = control, control["position"]
            self.controls.append((control["id"], control["profile"]))
            self.soaking = self.soaking or "Soak " in drawn(control["frame"])
            self.ready_due = self.now() + self.ENTER_S
            ident, position = control["id"], control["position"]

            def ready():
                if self.active != ident:
                    return
                self.ready_due = None
                message = {"ready": ident, "p": position}
                if self.ready_ks:
                    message["ks"] = self.keys
                self.emit(message)
                if self.pending_hold and self.keys & 1:
                    self.pending_hold = False
                    self.hold_deferred += 1
                    self.send_kh(0)
            self.schedule(self.ENTER_S, ready)
            self.show(control["frame"])
            return None
        return super().line(text)


@needs_tooling
class Cc54CheckFlowTests(unittest.TestCase):
    """check_nanod_cc5.raw_checks() for the 1.0.0-cc5.4 profile against FakeFirmware54 (no port, no device,
    fake clock): the cc5.3 sections plus ledIdle, lcdAnimation, ledUnderLoad and the hands-on section."""

    V5_SECTIONS = ["displayCheck", "legacyV2Frames", "staleFrameAndControl", "ledIdle", "rawArtwork", "mediaRoundTrip",
                   "mediaPrefetch", "mediaPinning", "mediaErrors", "mediaTiming", "lcdAnimation", "ledUnderLoad",
                   "coldTransferTiming", "stress", "stressTurn", "handsOn", "soak", "diag"]
    RAW_GATES = CheckScriptRawFlowTests.RAW_GATES
    V5_GATES = ("presentation5Capability", "aliveCapability", "ledFrameRate", "ledRenderTime", "limitEvents",
                "limitPerPush", "noErrorReplies", "readyKeyState", "holdEvents", "holdDeferred", "lcdTimings")

    def setUp(self):
        self.module = load_script("check_nanod_cc5.py")
        self.out = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))

    def raw54(self, firmware, hid_check=False, push_retries=1, binary=None, operator=None, **extra):
        """raw_checks (cc5.4) against `firmware` with a FakeOperator at the knob (FakeOperator keyword arguments in
        `operator`); extra keyword arguments become args (step_timeout, deferred_attempts, turn_attempts, ...)."""
        real = t.RawKnob
        clock = itertools.count(0, 0.001).__next__
        factory = lambda port: real(port, serial_factory=lambda name: firmware, clock=clock, sleep=lambda s: None)  # noqa: E731
        firmware.clock = firmware.clock or clock
        if firmware.operator is None:
            FakeOperator(firmware, **(operator or {}))
        profile = t.PROFILES["cc5.4"]
        report = self.last_report = self.module.Report("FAKEAPP", profile)
        report.led_max_brightness = 150                    # bridge_checks reads it from the inventory
        watch = FakeCheckpoints(report)
        args = SimpleNamespace(**{"turn_seconds": 1.0, "stress_frames": 40, "replay_transfers": 3, "soak_minutes": 1.0,
                                  "stress_seconds": 2.0, "hid_check": hid_check, "push_retries": push_retries,
                                  "binary": binary, "step_timeout": 30.0, **extra})
        with mock.patch.object(t, "RawKnob", factory), mock.patch.object(t, "SOAK_GATE_MINUTES", 1.0):
            self.module.raw_checks("FAKEAPP", report, {}, args, watch, profile)
        return report, watch

    def test_a_clean_cc5_4_run_passes_every_raw_gate(self):
        firmware = FakeFirmware54()
        report, watch = self.raw54(firmware, hid_check=True)
        self.assertEqual(report.data["failures"], [])
        gates = report.gates
        wanted = self.RAW_GATES + self.V5_GATES + ("hidIconGate",)
        self.assertEqual({name: gates[name] for name in wanted}, {name: True for name in wanted})
        self.assertEqual(set(gates), set(t.PROFILES["cc5.4"].gates))
        self.assertEqual(report.data["firmwareVersion"], "1.0.0-cc5.4")
        main = [w for w, _ in watch.main()]
        self.assertEqual(main[1:], self.V5_SECTIONS)
        sections = report.data["sections"]
        self.assertEqual(sections["lcdAnimation"]["binary"], "A")
        self.assertEqual(sections["ledUnderLoad"]["samples"], self.module.LED_LOAD_TRANSFERS)
        hands = sections["handsOn"]
        self.assertEqual(hands["hold"]["button1"]["problems"], [])
        self.assertEqual(len(hands["hold"]["button1"]["kh"]), 1)
        deferred = hands["deferred"]["attempts"][-1]
        self.assertTrue(deferred["deferred"])
        self.assertEqual(deferred["readyKs"] & 1, 1)
        self.assertEqual(deferred["holdDeferred"][1], deferred["holdDeferred"][0] + 1)
        stop = hands["endStop"]["runs"][-1]
        self.assertEqual((stop["perPush"], stop["held"], stop["stray"]), ([1] * self.module.PUSHES, 1, []))
        self.assertTrue(stop["reachedZero"] and stop["limAtZero"])
        self.assertEqual(hands["endStop"]["limRearmMs"]["advice"], "keep lim_rearm_ms")
        self.assertEqual({k: v["passed"] for k, v in hands["f24"].items()}, {"home": True, "tracks": True})
        self.assertIn("F24", report.data["externalActions"])
        self.assertEqual(sections["stressTurn"]["lims"]["problems"], [])
        self.assertEqual(sections["diag"]["binary"], "A")
        self.assertEqual(sections["diag"]["byEye"], list(self.module.BY_EYE))
        text = self.out.getvalue()
        self.assertLess(text.index("[knob] step 2/10 turn: done"), text.index("[log] hands-on:"))
        self.assertLess(text.index("[log] hands-on done"), text.index("[log] unattended soak"))
        # Every frame and control frame the check sent is one the cc5.4 parser accepts (device.v5_parse).
        device = companion_device()
        frames = sent_frames(firmware)
        rejected = [(f.get("layout"), f.get("title"), device.v5_parse(f)[1]) for f in frames if device.v5_parse(f)[1]]
        self.assertEqual(rejected, [])
        layouts = {f.get("layout") for f in frames}
        self.assertTrue({"seek", "recent", "tracks", "windows", "nowPlaying", "notice"} <= layouts, layouts)
        # The knob showed every step, in the plan's order, each done after its events; nothing was a stop.
        prompts = report.data["prompts"]
        self.assertEqual(prompts["plan"], ["display", "turn", "hold1", "hold2", "deferred", "pushes", "pushhold", "zero",
                                           "f24home", "f24tracks"])
        self.assertEqual([(s["name"], s["outcome"], s["retries"]) for s in prompts["steps"]],
                         [(name, "done", []) for name in prompts["plan"]])
        self.assertEqual(report.data["displayCheck"]["button"], 4)
        headings = [f.get("heading") for f in frames if str(f.get("heading", "")).startswith("STEP ")]
        self.assertEqual(sorted({h for h in headings}, key=lambda h: int(h.split()[1])),
                         [f"STEP {n} OF 10" for n in range(1, 11)])
        # Only the F24 controls enable HID; every prompt control keeps it off.
        controls = [json.loads(line)["control"] for line in firmware.received if line.startswith('{"control"')]
        self.assertEqual({c["frame"].get("title") for c in controls if c["windowsHidEnabled"]}, {"Press Button 4"})
        self.assertEqual(sum(1 for c in controls if c["windowsHidEnabled"]), 2)
        # The untouched passes and the soak kept their frames' tags (a drawn label changes on each frame).
        self.assertTrue(any(tagged(f, "Stress") and f.get("heading") == "HANDS OFF" for f in frames))
        self.assertTrue(any(tagged(f, "Stress") and str(f.get("heading", "")).startswith("STEP 2 ") for f in frames))
        self.assertTrue(any(tagged(f, "Soak") and f.get("heading") == "YOU CAN LEAVE" for f in frames))
        run = hands["endStop"]["runs"][-1]
        pushes = run["windows"]["pushes"]
        self.assertEqual(len(pushes), self.module.PUSHES)
        self.assertTrue(all(a < b <= c for (a, b), (c, _) in zip(pushes, pushes[1:])))     # contiguous, in order
        self.assertEqual((run["windows"]["doubles"], run["windows"]["missed"], run["nudges"]), ([], [], []))

    def test_without_hid_check_the_f24_gate_is_not_run_and_fails(self):
        report, _ = self.raw54(FakeFirmware54())
        self.assertFalse(report.gates["hidIconGate"])
        self.assertEqual(report.data["failures"], ["F24 icon gate: not run (pass --hid-check; the gate needs it)"])
        self.assertFalse(report.data["externalActions"])
        self.assertTrue(all(report.gates[name] for name in self.V5_GATES))

    def v5_gate_failure(self, firmware, gate, hid_check=True, push_retries=1):
        report, _ = self.raw54(firmware, hid_check=hid_check, push_retries=push_retries)
        self.assertFalse(report.gates[gate], gate)
        self.assertTrue(report.data["failures"])
        self.assertTrue(report.gates["unattendedSoak"] and report.gates["stressUntouched"])   # the rest still runs
        return report

    def test_led_frame_rate_idle_and_load(self):
        slow = FakeFirmware54()
        slow.led["ledFps"] = 56                                 # below 58 at idle, above 45 under load
        report = self.v5_gate_failure(slow, "ledFrameRate")
        self.assertTrue(report.data["sections"]["ledUnderLoad"]["passed"])
        gap = FakeFirmware54()
        gap.led["ledShowGapMsMax"] = 24
        self.v5_gate_failure(gap, "ledFrameRate")

    def test_led_render_time(self):
        firmware = FakeFirmware54()
        firmware.led["ledRenderUsMax"] = 3200
        self.v5_gate_failure(firmware, "ledRenderTime")

    def test_lcd_timings_follow_the_binary(self):
        slow_a = FakeFirmware54()
        slow_a.lcd["lcdFpsAnimMin"] = 50                         # < 55 on A
        self.v5_gate_failure(slow_a, "lcdTimings")
        c = FakeFirmware54()
        c.lcd.update(lcdDma=False, lcdPeriodMs=33, artAsync=False, lcdFpsAnimMin=30)
        del c.lcd["stackArtDec"]
        report, _ = self.raw54(c, hid_check=True)
        self.assertTrue(report.gates["lcdTimings"] and report.gates["diagMargins"])
        self.assertEqual(report.data["sections"]["lcdAnimation"]["binary"], "C")
        unknown = FakeFirmware54()
        unknown.lcd.update(lcdDma=False, artAsync=True)
        self.v5_gate_failure(unknown, "lcdTimings")

    def test_lcd_passes_keep_the_panel_animating(self):
        """WP9a-R2: lcdFpsAnimMin is a whole-second count and the LCD refreshes only while something animates
        (12.3; 8.1 rule 6), so each pass must animate without a gap through every second it measures."""
        report, _ = self.raw54(FakeFirmware54(), hid_check=True)
        section = report.data["sections"]["lcdAnimation"]
        self.assertTrue(report.gates["lcdTimings"], section["problems"])
        self.assertEqual((section["opaque"]["lcdFpsAnimMin"], section["blended"]["lcdFpsAnimMin"]), (58, 58))
        self.assertLess(self.module.SLIDE_PERIOD_S, FakeFirmware54.SLIDE_S)      # each change restarts the slide
        self.assertLess(self.module.FADE_PERIOD_S, FakeFirmware54.ART_FADE_S)    # ... and retargets the art fade
        self.assertGreaterEqual(self.module.ANIM_LEAD_S, 1.0)
        self.assertGreaterEqual(self.module.ANIM_PASS_S, 3.0)
        # The first cadence (a slide every 0.6 s, a fade every 0.8 s: the panel idle 37 % / 52 % of each second)
        # reads about 37 / 28 on the same correct binary A; a 0.45 s slide period still leaves gaps (about 49).
        for slide, fade, opaque_low, blended_low in ((0.6, 0.8, True, True), (0.45, 0.2, True, False),
                                                     (0.25, 0.6, False, True)):
            with self.subTest(slide=slide, fade=fade), mock.patch.multiple(self.module, SLIDE_PERIOD_S=slide,
                                                                           FADE_PERIOD_S=fade):
                report = self.v5_gate_failure(FakeFirmware54(), "lcdTimings")
                problems = report.data["sections"]["lcdAnimation"]["problems"]
                self.assertEqual((any("lcdFpsAnimMin" in p for p in problems["opaque"]),
                                  any("lcdFpsAnimMin" in p for p in problems["blended"])), (opaque_low, blended_low))

    def test_lcd_late_refreshes_count_the_pass_not_the_run(self):
        """WP9a-R3: on B the earlier sections' cover arrivals leave lcdLateRefrs above 0 (12.2 and 12.6 allow
        them), so the opaque gate counts only the pass, whether the firmware counts since boot or resets on read."""
        for reset in (False, True):
            with self.subTest(reset_on_read=reset):
                b = FakeFirmware54()
                b.lcd.update(lcdPeriodMs=33, artAsync=False, lcdFpsAnimMin=30)
                del b.lcd["stackArtDec"]
                b.late_on_cover, b.late_reset_on_read = 2, reset
                report, _ = self.raw54(b, hid_check=True)
                section = report.data["sections"]["lcdAnimation"]
                self.assertEqual(section["binary"], "B")
                self.assertTrue(report.gates["lcdTimings"], section["problems"])
                late = section["lateRefreshes"]
                self.assertEqual(late["semantics"], t.LATE_RESET_ON_READ if reset else t.LATE_SINCE_BOOT)
                self.assertEqual(late["opaquePass"], 0)
                if not reset:                                   # the absolute value the old gate failed on
                    self.assertGreater(section["opaque"]["lcdLateRefrs"], 0)
        for reset in (False, True):
            with self.subTest(jank=True, reset_on_read=reset):
                jank = FakeFirmware54()
                jank.late_on_cover, jank.late_per_change, jank.late_reset_on_read = 2, 1, reset
                report = self.v5_gate_failure(jank, "lcdTimings")
                section = report.data["sections"]["lcdAnimation"]
                self.assertGreater(section["lateRefreshes"]["opaquePass"], 0)
                self.assertTrue(any("during the pass" in p for p in section["problems"]["opaque"]))

    def test_a_kh_at_or_after_the_release_fails_hold_events(self):
        """WP9a-R5 (11.2: at most one kh per physical press; long presses of the other raws are ignored): a
        stray kh 20 ms after the key-up falls in the window both hold tests count."""
        one = FakeFirmware54()
        one.kh_on_release = (0,)
        report = self.v5_gate_failure(one, "holdEvents")
        hold = report.data["sections"]["handsOn"]["hold"]
        self.assertIn("2 kh for one hold of Button 1 (exactly one)", hold["button1"]["problems"])
        self.assertEqual(hold["button2"]["problems"], [])
        self.assertFalse(report.gates["holdDeferred"])             # its press gets the stray kh too
        two = FakeFirmware54()
        two.kh_on_release = (1,)
        report = self.v5_gate_failure(two, "holdEvents")
        hold = report.data["sections"]["handsOn"]["hold"]
        self.assertEqual(hold["button1"]["problems"], [])
        self.assertTrue(any("kh for a press of raw 1" in p for p in hold["button2"]["problems"]), hold["button2"])
        self.assertTrue(report.gates["holdDeferred"])              # only Button 2 misbehaves

    def test_memory_gates_of_cc5_4(self):
        firmware = FakeFirmware54()
        firmware.memory["heapMinFree"] = 40500                  # passes cc5.3's 40,000, fails 40,960
        self.v5_gate_failure(firmware, "diagMargins")
        art = FakeFirmware54()
        art.lcd["stackArtDec"] = 800
        self.v5_gate_failure(art, "diagMargins")

    def test_hold_gates(self):
        twice = FakeFirmware54()
        twice.kh_extra = True
        report = self.v5_gate_failure(twice, "holdEvents")
        self.assertFalse(report.gates["holdDeferred"])             # two kh for the deferred press too
        others = FakeFirmware54()
        others.kh_other_buttons = True
        self.v5_gate_failure(others, "holdEvents")
        never = FakeFirmware54()
        never.defer = False
        report = self.v5_gate_failure(never, "holdDeferred")
        self.assertEqual(len(report.data["sections"]["handsOn"]["deferred"]["attempts"]), self.module.DEFERRED_ATTEMPTS)
        self.assertTrue(report.gates["holdEvents"])

    def test_ready_key_state(self):
        firmware = FakeFirmware54()
        firmware.ready_ks = False
        report = self.v5_gate_failure(firmware, "readyKeyState")
        self.assertFalse(report.gates["holdDeferred"])             # the held bit is missing at ready too

    def test_end_stop_gates(self):
        chatter = FakeFirmware54()
        chatter.push_lims = 2
        report = self.v5_gate_failure(chatter, "limitPerPush")
        stop = report.data["sections"]["handsOn"]["endStop"]
        self.assertEqual(len(stop["runs"]), 2)                     # --push-retries 1: one repeat
        self.assertEqual(stop["limRearmMs"]["advice"], "raise lim_rearm_ms (a push fired twice)")
        missed = FakeFirmware54()
        missed.push_lims = 0
        report = self.v5_gate_failure(missed, "limitPerPush", push_retries=0)
        self.assertEqual(len(report.data["sections"]["handsOn"]["endStop"]["runs"]), 1)
        no_zero = FakeFirmware54()
        no_zero.zero_lim = False
        report = self.v5_gate_failure(no_zero, "limitEvents")
        self.assertTrue(report.gates["limitPerPush"])
        no_turn_lims = FakeFirmware54()
        no_turn_lims.stress_lims = False
        self.v5_gate_failure(no_turn_lims, "limitEvents")

    def test_f24_only_from_the_home_win_slot(self):
        firmware = FakeFirmware54()
        firmware.hid_everywhere = True
        report = self.v5_gate_failure(firmware, "hidIconGate")
        self.assertEqual({k: v["hid"] for k, v in report.data["sections"]["handsOn"]["f24"].items()},
                         {"home": True, "tracks": True})

    def test_capabilities_of_cc5_4(self):
        class Presentation4(FakeFirmware54):
            def capabilities(self):
                return {**super().capabilities(), "presentation": 4}
        report = self.v5_gate_failure(Presentation4(), "presentation5Capability")
        self.assertFalse(report.gates["artwork2Capability"])        # artwork2 negotiates on presentation 5

        class NoAlive(FakeFirmware54):
            def capabilities(self):
                caps = super().capabilities()
                del caps["alive"]
                return caps
        self.v5_gate_failure(NoAlive(), "aliveCapability")

    def test_an_error_reply_in_a_stress_pass_fails_no_error_replies(self):
        class ErrorInStress(FakeFirmware54):
            def show(self, frame):
                super().show(frame)
                if tagged(frame, "Stress 5 "):
                    self.reply({"error": "Invalid frame"})
        report, _ = self.raw54(ErrorInStress(), hid_check=True)
        self.assertFalse(report.gates["noErrorReplies"])
        self.assertFalse(report.gates["stressUntouched"] and report.gates["stressTurn"])
        self.assertTrue(report.gates["unattendedSoak"] and report.gates["holdEvents"])      # the rest still runs

    # --- the knob-guided steps (user ruling 2026-09-26) ------------------------------------------------------
    def test_wrong_buttons_are_retried_on_the_knob(self):
        """A wrong button repeats the step with the reason on the knob (and an err flash); the right one then
        completes it. The wrong Button 3 on the F24 Home step sends no F24."""
        firmware = FakeFirmware54()
        report, _ = self.raw54(firmware, hid_check=True,
                               operator={"wrong_first": {t.PROMPT_SEE: 1, "Press Button 4": 2, "Ready to turn?": 0}})
        self.assertEqual(report.data["failures"], [])
        steps = {step["name"]: step for step in report.data["prompts"]["steps"]}
        self.assertEqual([r["reason"] for r in steps["display"]["retries"]], ["That was Button 2"])
        self.assertEqual([r["reason"] for r in report.data["displayCheck"]["retries"]], ["That was Button 2"])
        self.assertEqual([r["reason"] for r in steps["turn"]["retries"]], ["That was Button 1"])
        self.assertEqual([r["reason"] for r in steps["f24home"]["retries"]], ["That was Button 3"])
        self.assertTrue(report.gates["hidIconGate"])
        flashes = [f["feedback"]["kind"] for f in sent_frames(firmware)
                   if f.get("layout") == "notice" and f.get("feedback", {}).get("seq", 0) > t.PROMPT_SEQ_START]
        self.assertIn("err", flashes)
        self.assertIn("ok", flashes)

    def test_a_hold_released_too_soon_is_repeated(self):
        report, _ = self.raw54(FakeFirmware54(), hid_check=True,
                               operator={"short_first": ("Hold Button 1", "Hold Button 2")})
        self.assertEqual(report.data["failures"], [])
        hold = report.data["sections"]["handsOn"]["hold"]
        self.assertEqual((hold["button1"]["attempts"], hold["button1"]["problems"], len(hold["button1"]["kh"])),
                         (2, [], 1))
        self.assertEqual((hold["button2"]["attempts"], hold["button2"]["problems"]), (2, []))
        steps = {step["name"]: step for step in report.data["prompts"]["steps"]}
        self.assertEqual([r["reason"] for r in steps["hold1"]["retries"]], ["Too short · hold longer"])
        self.assertEqual([r["reason"] for r in steps["hold2"]["retries"]], ["Too short · hold until Let go"])
        self.assertTrue(report.gates["holdEvents"] and report.gates["holdDeferred"])

    def test_a_step_never_done_is_an_operator_stop_not_a_firmware_failure(self):
        firmware = FakeFirmware54()
        with self.assertRaises(t.OperatorTimeout) as caught:
            self.raw54(firmware, hid_check=True, operator={"absent": ("Hold Button 1",)}, step_timeout=5.0)
        stop = caught.exception
        self.assertEqual((stop.step, stop.of, stop.name, stop.reason, stop.exit_code),
                         (3, 10, "hold1", "operator did not complete step 3", 4))
        report = self.last_report
        self.assertEqual(report.data["failures"], [])
        self.assertEqual(report.data["operatorStop"], {**stop.record()})
        self.assertFalse(report.data["operatorStop"]["firmwareFailure"])
        for gate in ("holdEvents", "holdDeferred", "limitPerPush", "limitEvents", "hidIconGate", "readyKeyState",
                     "unattendedSoak", "diagMargins"):
            self.assertFalse(report.gates[gate], gate)
        self.assertTrue(report.gates["turningDetected"] and report.gates["stressTurn"])
        self.assertNotIn("soak", report.data["sections"])
        self.assertEqual([(s["name"], s["outcome"]) for s in report.data["prompts"]["steps"]],
                         [("display", "done"), ("turn", "done"), ("hold1", "operator-timeout")])
        self.assertEqual(report.data["finalRelease"], {"released": True})
        self.assertTrue(firmware.closed)

    def test_a_second_lim_inside_the_quiet_period_is_chatter(self):
        """Push 2 fires twice 0.2 s apart: the second lim arrives inside its 1 s quiet period, so it is counted in
        push 2's window (a double), and the End stop gate fails exactly as the ruling intends."""
        firmware = FakeFirmware54()
        firmware.push_lims = [1, 2, 1, 1, 1]
        report = self.v5_gate_failure(firmware, "limitPerPush", push_retries=0)
        stop = report.data["sections"]["handsOn"]["endStop"]
        [run] = stop["runs"]
        self.assertEqual((run["perPush"], run["held"], run["stray"]), ([1, 2, 1, 1, 1], 1, []))
        self.assertEqual([d["window"] for d in run["windows"]["doubles"]], [2])
        self.assertEqual(stop["limRearmMs"]["advice"], "raise lim_rearm_ms (a push fired twice)")
        pushes = run["windows"]["pushes"]
        double = run["windows"]["doubles"][0]["at"]
        self.assertGreaterEqual(pushes[1][1] - double, t.PROMPT_QUIET_S)          # the quiet restarted from it

    def test_a_push_the_knob_did_not_see_is_asked_on_the_knob(self):
        """No lim for 10 s: "Did you push?" on the knob. Yes records a missed End stop (0 in that window); No goes
        back to the push, which then counts."""
        missed = FakeFirmware54()
        missed.push_lims = [1, 1, 0, 1, 1]
        report = self.v5_gate_failure(missed, "limitPerPush", push_retries=0)
        [run] = report.data["sections"]["handsOn"]["endStop"]["runs"]
        self.assertEqual((run["perPush"], run["windows"]["missed"]), ([1, 1, 0, 1, 1], [3]))
        self.assertEqual([(n["question"], n["pushed"]) for n in run["nudges"]], [("Did you push?", True)])
        self.assertEqual(report.data["sections"]["handsOn"]["endStop"]["limRearmMs"]["advice"],
                         "lower lim_rearm_ms or push more slowly (a push was missed)")
        again = FakeFirmware54()
        again.push_lims = [1, 1, 0, 1]
        report, _ = self.raw54(again, hid_check=True, push_retries=0, operator={"answers": {"Did you push?": False}})
        self.assertEqual(report.data["failures"], [])
        [run] = report.data["sections"]["handsOn"]["endStop"]["runs"]
        self.assertEqual((run["perPush"], run["windows"]["missed"]), ([1, 1, 1, 1, 1], []))
        self.assertEqual([(n["question"], n["pushed"]) for n in run["nudges"]], [("Did you push?", False)])

    def test_the_deferred_hold_retries_with_the_planner(self):
        """Attempt 1's long press matures after the new control is ready (0.75 s after the kd): not deferred, and
        the planner takes the measured kd -> kh; attempt 2 enters later and the press defers."""
        firmware = FakeFirmware54()
        firmware.long_press_s = [0.62, 0.75, 0.75]
        report, _ = self.raw54(firmware, hid_check=True)
        self.assertEqual(report.data["failures"], [])
        deferred = report.data["sections"]["handsOn"]["deferred"]
        attempts = deferred["attempts"]
        self.assertEqual([a["deferred"] for a in attempts], [False, True])
        self.assertGreater(attempts[1]["delayS"], attempts[0]["delayS"] + 0.2)
        self.assertEqual(len(deferred["planner"]["observedS"]), 1)
        self.assertAlmostEqual(deferred["planner"]["observedS"][0], 0.75, delta=0.06)
        self.assertEqual(attempts[1]["holdDeferred"][1], attempts[1]["holdDeferred"][0] + 1)
        self.assertTrue(report.gates["holdDeferred"] and report.gates["readyKeyState"])

    def test_every_instruction_fits_the_glass(self):
        """The copy of every prompt and overlaid frame of a full run, and the longest dynamic values, fit the
        knob's labels (lcd_preview): headings keep their 1 px tracking, no instruction line is cut with an
        ellipsis. A line carrying a per-frame tag (Stress, Soak) is exempt."""
        firmware = FakeFirmware54()
        self.raw54(firmware, hid_check=True, operator={"wrong_first": {t.PROMPT_SEE: 1},
                                                       "short_first": ("Hold Button 1", "Hold Button 2")})
        frames = [f for f in sent_frames(firmware)
                  if str(f.get("heading", "")).startswith("STEP ") or f.get("heading") in ("HANDS OFF", "YOU CAN LEAVE")]
        self.assertGreater(len(frames), 50)
        problems = [(f.get("layout"), f.get("heading"), cut) for f in frames for cut in prompt_fit_problems(f)]
        self.assertEqual(problems, [])
        # The longest dynamic values on every overlaid layout.
        device, module = companion_device(), self.module
        caps = {**FakeFirmware54().capabilities(), "glyphs": "latin-ext-a"}
        v4, _ = t.fixture_frames()
        bases = [device._frame(copy_json(v4[name]), caps) for name in module.MEDIA_STRESS_BASES]
        bases.append(device._frame({**copy_json(v4["v4-tracks-no-previous"]), "layout": "seek",
                                    "ring": {"style": "lap", "value": 0, "index": 17, "count": 20}}, caps))
        meter = t.TurnMeter(10, 30)
        notes = ["Don’t stop turning", "Left end done · right next", "Right end done · left next", "Push past each end",
                 "Reach both ends", "Both ends done", "You stopped for 3 s", "You touched the knob",
                 "Push 5 of 5, then let go", "Again · Push 1 of 5, then let go", "Hold it against the end",
                 "Keep holding · 3", "Then push past it once", t.PROMPT_YES_NO, "That was Button 4 · Yes 4 · No 1"]
        says = [module.TURN_KEEP, module.AUTOMATIC, "Push past the end", "Let it spring back", "Push and hold",
                "Turn to 0:00", "Now push past 0:00", "Did you push?", "Pushed past 0:00?", "Let go", "Press Button 4"]
        for base in bases:
            for say in says:
                for note in notes:
                    frame = device._frame(t.overlay({**base, "id": 5}, "STEP 10 OF 10", say, meter.progress()
                                                    .replace("Turned 0", "Turned 30"), note, "error"), caps)
                    self.assertEqual(prompt_fit_problems(frame), [], (base.get("layout"), say, note))
        for n in range(1, 11):
            for text in (f"Attempt {n} of 10", f"Once more · attempt {n} of 10", f"{n}:59 left"):
                frame = device._frame({**t.prompt_frame(f"STEP {n} OF 10", "Hold Button 1", "Hold until it says Let go",
                                                        text), "id": 5}, caps)
                self.assertEqual(prompt_fit_problems(frame), [], text)



@needs_tooling
class Cc54CheckScriptStaticTests(unittest.TestCase):
    """check_nanod_cc5.py --release, --hid-check and the hands-on cues (parsed, never run)."""

    def setUp(self):
        self.module = load_script("check_nanod_cc5.py")
        self.source = (WORK / "check_nanod_cc5.py").read_text(encoding="utf-8")

    def test_release_selection_and_evidence(self):
        self.assertIn('parser.add_argument("--release", choices=sorted(t.PROFILES), default=current,', self.source)
        self.assertIn('parser.add_argument("--hid-check", action="store_true",', self.source)
        self.assertIn("t.write_json_evidence(profile.device_checks, report.data)", self.source)
        report = self.module.Report("COMX", t.PROFILES["cc5.4"])
        self.assertEqual(set(report.gates), set(t.PROFILES["cc5.4"].gates))
        self.assertEqual(report.data["firmwareVersion"], "1.0.0-cc5.4")
        self.assertEqual(self.module.Report("COMX").data["firmwareVersion"], t.CURRENT.version)

    def test_by_eye_records_the_panel_image_and_the_panel_scan(self):
        """WP9a-R6: 12.6 check 1 (panel image) decides A -> C and has no gate; filming the scan is A's check 3."""
        by_eye = self.module.BY_EYE
        panel = by_eye[0]
        self.assertIn("12.6 check 1, panel image", panel)
        for words in ("colours", "byte order", "no offset", "torn or stale bands", "slide", "volume reveal",
                      "cover swap", "setRotation", "goes straight to C", "binary under test"):
            self.assertIn(words, panel)
        self.assertEqual([item for item in by_eye if "film the panel scan" in item and "binaries A and D only" in item],
                         [by_eye[1]])                                      # D is A's pipeline with the fixes
        # The binary under test sits next to byEye in the evidence.
        self.assertIn("binary=t.lcd_binary(diag), byEye=list(BY_EYE)", self.source)

    def test_hands_on_cues_stay_opt_in_and_hid_stays_off_by_default(self):
        hands = self.source[self.source.index("def cue("):self.source.index("def run_stress(")]
        self.assertNotIn("winsound", hands)                          # every beep goes through audible_cue
        self.assertIn("windows_hid=True", hands)                     # only the F24 test enables HID
        self.assertEqual(self.source.count("windows_hid=True"), 1)
        self.assertIn('if getattr(args, "hid_check", False):', hands)
        # The hands-on runs after stress+turn (the operator is at the knob) and before the unattended soak.
        self.assertLess(self.source.index('report.section("stressTurn")'), self.source.index('report.section("handsOn")'))
        self.assertLess(self.source.index('report.section("handsOn")'), self.source.index('report.section("soak")'))


def load_tour():
    return load_script("nanod_alive_tour.py")


def companion_device():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from control_center import device
    return device


@needs_tooling
class AliveTourTests(unittest.TestCase):
    """tools/nanod_alive_tour.py (ALIVE.md 11.9 hands-on tour): every frame it can send is one the cc5.4
    parser accepts (the companion's device.v5_parse / alive_parse reading), and a session against
    FakeFirmware54 (fake clock, no port) claims, plays, tunes, restores the defaults and records."""

    def setUp(self):
        self.tour_module = load_tour()
        self.device = companion_device()
        self.validate = lambda frame: self.device.v5_parse(frame)[1] + self.device.alive_parse(frame)[1]

    def session(self, firmware=None):
        firmware = firmware or FakeFirmware54()
        clock = itertools.count(0, 0.001).__next__
        firmware.clock = clock
        knob = t.RawKnob("FAKEAPP", serial_factory=lambda name: firmware, clock=clock, sleep=lambda s: None,
                         paced=False)
        caps = self.tour_module.open_session(knob)
        lines = []
        tour = self.tour_module.Tour(knob, caps, self.validate, clock=knob.now, out=lines.append)
        return tour, knob, firmware, lines

    def test_every_screen_moment_and_tuning_frame_is_valid_v5(self):
        m = self.tour_module
        tunings = [{}, {"ledPink": 0xFF0C30, "ledVolFull": True, "ledDrive": 90, "ledDither": False},
                   {"ledPink": 0, "ledVolFull": False, "ledDrive": 150, "ledDither": True}]
        for name, (frame, kind, maximum, position) in m.screens().items():
            self.assertIn(kind, m.PROFILES)
            self.assertLessEqual(position, maximum, name)
            for tuning in tunings:
                with self.subTest(screen=name, tuning=tuning):
                    wire = {**frame, "id": 5, "clock": 720, "reducedMotion": True, **tuning}
                    self.assertEqual(self.validate(wire), [])
        screens = m.screens()
        for name, (screen, feedback) in m.MOMENTS.items():
            base = screens[screen or "home"][0]
            with self.subTest(moment=name):
                self.assertEqual(self.validate({**base, "id": 5, "feedback": {**feedback, "seq": 9}}), [])
        self.assertEqual({k: v[1] for k, v in m.PINK_CANDIDATES.items()}, {0: 0, 1: 0xFF051A, 2: 0xFF0C30, 3: 0xFF0210})
        # The paused Home: slot 0 is play (the green breath, U1); the liked heart is lit next to a dim button.
        paused = screens["paused"][0]
        self.assertEqual((paused["buttons"][0]["icon"], paused["playing"]), ("play", False))
        liked = screens["liked"][0]["buttons"]
        self.assertEqual((liked[2]["icon"], liked[2]["lit"], liked[1]["enabled"]), ("heart", "on", False))
        card = screens["card"][0]["ring"]
        self.assertEqual((card["card"], card["now"], card["count"]), (True, card["count"] - 2, 6))
        self.assertEqual(screens["seek"][0]["ring"]["style"], "lap")

    def test_a_session_plays_tunes_settles_and_restores_the_defaults(self):
        tour, knob, firmware, lines = self.session()
        tour.enter("home")
        for command in ("paused", "pink 2", "liked", "like", "volfull on", "reduced on", "night", "err",
                        "skipnext", "snapleft", "started", "unlike", "drive 90", "dither off",
                        "pick pink 2", "pick volfull off", "confirm paused-green yes", "confirm headshake yes",
                        "note the bloom reads well", "bogus"):
            self.assertTrue(tour.dispatch(command), command)
            knob.pump(0.05)
        self.assertFalse(tour.dispatch("quit"))
        self.assertEqual(knob.errors, [])
        frames = [json.loads(line) for line in firmware_lines(firmware)]
        sent = [d["frame"] for d in frames if "frame" in d]
        controls = [d["control"] for d in frames if "control" in d]
        self.assertTrue(all(not c["windowsHidEnabled"] for c in controls))
        self.assertEqual([c["frame"]["layout"] for c in controls][:3], ["nowPlaying", "nowPlaying", "upnext"])
        moments = [f["feedback"] for f in sent if "feedback" in f]
        seqs = [f["seq"] for f in moments]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))
        self.assertIn({"kind": "ok", "moment": "like", "seq": seqs[0]}, moments)
        self.assertIn("err", [f["kind"] for f in moments])
        started = next(f for f in sent if f.get("feedback", {}).get("moment") == "started")
        self.assertNotIn("playing", started)                        # M16
        self.assertEqual(started["feedback"]["color"], self.tour_module.STARTED_COLOR)
        self.assertTrue(any(f.get("ledPink") == 0xFF0C30 for f in sent))
        self.assertTrue(any(f.get("ledVolFull") is True for f in sent))
        self.assertTrue(any(f.get("reducedMotion") is True and f.get("clock") == 23 * 60 for f in sent))
        tour.restore_defaults()
        last = json.loads(firmware_lines(firmware)[-1])["frame"]
        # ledDither False is the knob's default since the 2026-09-26 user ruling (ALIVE.md 9: dither off, floor on).
        self.assertEqual((last["ledPink"], last["ledVolFull"], last["ledDrive"], last["ledDither"], last["reducedMotion"]),
                         (0, False, 150, False, False))
        record = tour.record()
        self.assertEqual(record["settled"]["pink"], {"candidate": 2, "label": "softer, more magenta 255,60,120",
                                                     "ledPink": 0xFF0C30})
        self.assertEqual((record["settled"]["volFull"], record["settled"]["confirm"]),
                         (False, {"paused-green": True, "headshake": True}))
        self.assertEqual(record["settled"]["notes"], ["the bloom reads well"])
        self.assertIn("unknown command 'bogus'; type help", lines)
        json.dumps(record)                                          # evidence is plain JSON

    def test_timed_sequences_and_the_ring_follows_the_knob(self):
        tour, knob, firmware, _ = self.session()
        tour.volume_sweep()
        end = knob.now() + 10.0
        while knob.now() < end:
            knob.pump(0.05)
            tour.tick()
        sent = [json.loads(line)["frame"] for line in firmware_lines(firmware) if line.startswith('{"frame"')]
        values = [f["ring"]["value"] for f in sent if f.get("layout") == "volume"]
        self.assertEqual((max(values), values[-1]), (100, 40))
        tour.seek_jump()
        end = knob.now() + 9.0
        while knob.now() < end:
            knob.pump(0.05)
            tour.tick()
        seek = [json.loads(line)["frame"] for line in firmware_lines(firmware) if line.startswith('{"frame"')]
        activity = [f.get("activity", "idle") for f in seek if f.get("layout") == "seek"]
        self.assertEqual([a for i, a in enumerate(activity) if i == 0 or a != activity[i - 1]],
                         ["pending", "idle", "pending", "idle"])
        firmware.emit({"id": tour.control_id, "p": 12})              # the user turns the Seek lap
        knob.pump(0.05)
        tour.tick()
        last = json.loads(firmware_lines(firmware)[-1])["frame"]
        self.assertEqual(last["ring"]["index"], 12)

    def test_it_refuses_a_knob_without_presentation_5_and_alive(self):
        class Cc53(FakeFirmware):
            pass
        firmware = Cc53()
        clock = itertools.count(0, 0.001).__next__
        firmware.clock = clock
        knob = t.RawKnob("FAKEAPP", serial_factory=lambda name: firmware, clock=clock, sleep=lambda s: None)
        with self.assertRaises(RuntimeError) as caught:
            self.tour_module.open_session(knob)
        self.assertIn("does not run 1.0.0-cc5.4", str(caught.exception))
        self.assertIn("no alive capability", str(caught.exception))

    def test_static_safety(self):
        source = (WORK / "nanod_alive_tour.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":', source)
        self.assertNotIn("winsound", source)
        self.assertNotIn("audible_cue", source)                     # beeps only in the turning test
        self.assertNotIn("windows_hid=True", source)
        self.assertNotIn("esptool", source.lower().replace("no esptool", ""))
        self.assertIn("t.require_companion_quit()", source)
        self.assertLess(source.index("t.require_companion_quit()"), source.index("t.find_app_port()"))
        self.assertIn("t.write_new_json(", source)                  # never overwrites earlier evidence
        self.assertIn("tour.restore_defaults()", source[source.index("def main("):])


# ---------------------------------------------------------------------------
# PRESENTATION_V5 12.6 build ladder (lead ruling R-m): binaries A, B and C of 1.0.0-cc5.4 staged with their
# own build, package, prepare, install, rollback and finalize records; the dual-name flash interlock.

LADDER_FLAGS = {"A": (), "B": ("-DCC_LCD_PERIOD_MS=33", "-DCC_ART_ASYNC=0"),
                "C": ("-DCC_LCD_DMA=0", "-DCC_LCD_PERIOD_MS=33", "-DCC_ART_ASYNC=0"),    # the phase-2b gatekeeper's
                "D": ("-DCC_BUILD_BINARY=4",),                                              # the fix binaries: A + fixes
                "E": ("-DCC_LCD_DMA=0", "-DCC_LCD_PERIOD_MS=33", "-DCC_ART_ASYNC=0", "-DCC_BUILD_BINARY=5")}   # C + fixes


@needs_tooling
class LadderProfileTests(unittest.TestCase):
    """Binary A is the cc5.4 profile itself; B and C are variants with their own names that share the
    release's backup pair, backup record and check records."""

    OWN = ("image", "source_zip", "manifest", "build_log", "expected_full", "build_report", "preparation",
           "flash_checks", "rollback_report", "installation", "look_checks")
    SHARED = ("before_full", "rollback_app", "backup_report", "device_checks", "lease_checks", "from_record",
              "from_image")

    def test_binary_a_is_the_release_profile(self):
        a = t.CURRENT.binary_profile("A")
        self.assertIs(a, t.CURRENT)
        self.assertIs(t.CURRENT.binary_profile(None), t.CURRENT)
        self.assertEqual((a.binary, a.label, a.prefix, a.artifact_version, a.file_tag), ("A", "cc5.4", "cc5.4",
                                                                                          "1.0.0-cc5.4", "cc5.4"))
        self.assertEqual((a.build_flags, a.build_dir, a.built_image), ((), None, t.BUILT_IMAGE))
        self.assertEqual(a.pipeline, {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True})
        self.assertEqual(t.binary_choices(), ("D", "E"))                 # A, B and C are retired (A's rollback)

    def test_b_and_c_carry_their_letter_in_every_own_name(self):
        for name in ("B", "C", "D", "E"):
            with self.subTest(name):
                v = t.CURRENT.binary_profile(name)
                self.assertIs(v, t.CURRENT.binary_profile(name))                   # created once
                self.assertIs(v.base, t.CURRENT)
                self.assertIs(v.binary_profile("A"), t.CURRENT)
                self.assertEqual((v.version, v.tag, v.binary, v.label), ("1.0.0-cc5.4", "cc5.4", name, f"cc5.4 binary {name}"))
                self.assertEqual([getattr(v, attr).name for attr in self.OWN],
                                 [f"nanod-control-center-1.0.0-cc5.4-{name}.bin",
                                  f"nanod-control-center-1.0.0-cc5.4-{name}-source.zip",
                                  f"manifest-1.0.0-cc5.4-{name}.json", f"nanod-cc5.4-{name}-build.log",
                                  f"nanod-cc5.4-{name}-expected-full.bin", f"cc5.4-{name}-build.json",
                                  f"cc5.4-{name}-preparation.json", f"cc5.4-{name}-flash-checks.json",
                                  f"cc5.4-{name}-rollback.json", f"cc5.4-{name}-installation.json",
                                  f"cc5.4-{name}-look-checks.json"])
                for attr in self.SHARED:
                    self.assertEqual(getattr(v, attr), getattr(t.CURRENT, attr), attr)
                self.assertEqual((v.install_log_prefix, v.rollback_log_prefix, v.backup_log_prefix),
                                 (f"cc5.4-{name}", f"cc5.4-{name}-rollback", "cc5.4-backup"))
                self.assertEqual(v.rollback_workdir("X").name, f"cc5.4-{name}-rollback-X")
                self.assertEqual(v.build_dir, t.FIRMWARE_SOURCE / ".pio" / f"build-cc5.4-{name}")
                self.assertEqual(v.built_image, v.build_dir / t.PIO_ENV / "firmware.bin")
                self.assertEqual(v.built_elf, v.build_dir / t.PIO_ENV / "firmware.elf")
                self.assertEqual(v.build_flags, LADDER_FLAGS[name])
                self.assertEqual(v.pipeline, t.LCD_BINARIES[name])
                self.assertIn(f"cc5.4-{name}-build.json", v.gate_patterns)
                self.assertNotIn("cc5.4-build.json", v.gate_patterns)
                # Everything else is the release's: gates, capabilities, from-release, outcomes, desktop.
                for attr in ("gates", "from_version", "from_image_sha256", "restored_outcome", "desktop_bundle",
                             "desktop_rollback_bundle", "validation_key", "superseded", "presentation"):
                    self.assertEqual(getattr(v, attr), getattr(t.CURRENT, attr), attr)
                self.assertEqual(v.expected_capabilities(), t.CURRENT.expected_capabilities())
                self.assertIn(f"binary {name}", repr(v))

    def test_no_two_binaries_or_profiles_share_an_own_file(self):
        names = [getattr(p, attr).name for p in t.all_profiles() for attr in self.OWN]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual([p.label for p in t.all_profiles()],
                         ["cc5.2", "cc5.3", "cc5.4", "cc5.4 binary B", "cc5.4 binary C", "cc5.4 binary D",
                          "cc5.4 binary E"])

    def test_the_flags_are_the_contract_and_a_is_the_source_default(self):
        """12.6: the binaries differ only in CC_LCD_DMA, CC_LCD_PERIOD_MS and CC_ART_ASYNC; A is the source
        default (lcd_thread.cpp), and each binary's flags produce its diag pipeline (LCD_BINARIES)."""
        self.assertEqual(t.PIPELINE_BINARIES, ("A", "B", "C", "D", "E"))
        self.assertEqual({k: tuple(v) for k, v in t.BINARY_BUILD_FLAGS.items()}, LADDER_FLAGS)
        source = t.FIRMWARE_SOURCE / "src" / "lcd_thread.cpp"
        if not source.is_file():
            self.skipTest("firmware checkout not present")
        text = source.read_text(encoding="utf-8")
        defaults = {name: int(re.search(rf"#ifndef {name}\s+#define {name} (\d+)", text).group(1))
                    for name in ("CC_LCD_DMA", "CC_LCD_PERIOD_MS", "CC_ART_ASYNC")}
        for binary, flags in LADDER_FLAGS.items():
            values = dict(defaults, **{f[2:].split("=")[0]: int(f.split("=")[1]) for f in flags
                                       if not f.startswith("-DCC_BUILD_BINARY=")})   # the build id, not the pipeline
            self.assertEqual({"lcdDma": bool(values["CC_LCD_DMA"]), "lcdPeriodMs": values["CC_LCD_PERIOD_MS"],
                              "artAsync": bool(values["CC_ART_ASYNC"])}, t.LCD_BINARIES[binary], binary)
        # The build-only markers exist in the sources they name.
        self.assertIn('"ArtDecode"', (t.FIRMWARE_SOURCE / "src" / "cc_art_decode.cpp").read_text(encoding="utf-8"))
        self.assertRegex(text, r"#if CC_LCD_DMA\s+//[^\n]*\n\s*uint32_t draw_buf2\[")

    def test_a_release_without_the_ladder_has_no_binaries(self):
        cc53 = t.PROFILES["cc5.3"]
        self.assertIsNone(cc53.binary)
        self.assertEqual((cc53.pipeline_binaries(), cc53.variants(), cc53.label), ((), [cc53], "cc5.3"))
        self.assertIs(cc53.binary_profile(None), cc53)
        for name in ("A", "B"):
            with self.assertRaises(ValueError):
                cc53.binary_profile(name)
        with self.assertRaises(ValueError):
            t.CURRENT.binary_profile("F")
        self.assertEqual(t.binary_image_problems(b"anything", None), [])
        self.assertEqual(t.binary_elf_problems(None, None), [])

    def test_pipeline_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            elf = Path(folder) / "firmware.elf"
            elf.write_bytes(fake_elf(["setup", t.R3_ELF_SYMBOL, "_Z19cc_art_decode_startv"]))
            symbols = t.elf_symbol_names(elf)
            self.assertEqual(symbols, {"setup", "draw_buf2", "_Z19cc_art_decode_startv"})
            (Path(folder) / "bad.elf").write_bytes(b"MZ not an elf")
            with self.assertRaises(ValueError):
                t.elf_symbol_names(Path(folder) / "bad.elf")
        self.assertEqual(t.binary_elf_problems(symbols, "A"), [])
        self.assertEqual(t.binary_elf_problems(symbols, "B"), [])
        self.assertIn("binary C must not link the R3 draw buffer", t.binary_elf_problems(symbols, "C")[0])
        self.assertIn("binary A must link", t.binary_elf_problems({"setup"}, "A")[0])
        self.assertIn("firmware.elf is missing", t.binary_elf_problems(None, "B")[0])
        image = b"\xe9 1.0.0-cc5.4 " + t.R5_IMAGE_MARKER
        self.assertEqual(t.binary_image_problems(image, "A"), [])
        self.assertIn("binary B must not contain the R5 decode task", t.binary_image_problems(image, "B")[0])
        self.assertIn("binary A must contain the R5 decode task", t.binary_image_problems(b"\xe9 plain", "A")[0])
        self.assertEqual(t.binary_image_problems(b"\xe9 plain", "C"), [])

    def test_real_builds_match_their_binary_when_present(self):
        """Read only: any accepted build record of a binary names its flags and pipeline."""
        for v in t.CURRENT.variants():
            if not v.build_report.is_file():
                continue
            with self.subTest(v.binary):
                record = t.load_json(v.build_report)
                if record.get("accepted"):
                    self.assertEqual((record["binary"], record["buildFlags"], record["pipeline"]),
                                     (v.binary, list(v.build_flags), v.pipeline))
                    self.assertEqual(record["heapProjection"]["hBytes"], 512 if v.pipeline["lcdDma"] else 0)

    def test_desktop_bundle_exe_knows_both_identities(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            (app / "desktop-dist-v6" / "NanoDControlCenter").mkdir(parents=True)
            (app / "desktop-dist-v6" / "NanoDControlCenter" / "NanoDControlCenter.exe").write_bytes(b"MZ v6")
            (app / "desktop-dist-v7" / "DeskDial").mkdir(parents=True)
            (app / "desktop-dist-v7" / "DeskDial" / "DeskDial.exe").write_bytes(b"MZ v7")
            self.assertEqual(t.desktop_bundle_exe("desktop-dist-v6", app).name, "NanoDControlCenter.exe")
            self.assertEqual(t.desktop_bundle_exe("desktop-dist-v7", app).name, "DeskDial.exe")
            self.assertIsNone(t.desktop_bundle_exe("desktop-dist-v9", app))


class CompanionInterlockTests(unittest.TestCase):
    """The flash-safety interlock (rename-desk-dial.md 11.1): a running DeskDial.exe or NanoDControlCenter.exe
    both block every hardware step; tasklist is queried per image, read-only, no window."""

    def fake_run(self, running=(), fail=()):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            image = command[2].split("eq ", 1)[1]
            if image in fail:
                return SimpleNamespace(returncode=1, stdout="")
            if image in running:
                return SimpleNamespace(returncode=0, stdout=f'"{image}","4242","Console","1","80,000 K"\n')
            return SimpleNamespace(returncode=0, stdout="INFO: No tasks are running which match the specified criteria.\n")
        return run, calls

    def test_both_images_are_checked(self):
        self.assertEqual(t.COMPANION_IMAGES, ("DeskDial.exe", "NanoDControlCenter.exe"))
        self.assertEqual(t.COMPANION_TASKS, ("Desk Dial", "NanoD Control Center"))
        for running in ((), ("DeskDial.exe",), ("NanoDControlCenter.exe",), t.COMPANION_IMAGES):
            with self.subTest(running=running):
                run, _ = self.fake_run(running)
                self.assertEqual(t.companion_running(run), bool(running))
                run, calls = self.fake_run(running)
                self.assertEqual(t.running_companions(run), list(running))
                self.assertEqual([c[0][:2] + c[0][3:] for c in calls], [["tasklist", "/FI", "/FO", "CSV", "/NH"]] * 2)
                self.assertEqual([c[0][2] for c in calls], [f"IMAGENAME eq {i}" for i in t.COMPANION_IMAGES])
                self.assertTrue(all(c[1]["creationflags"] == t._NO_WINDOW for c in calls))
                self.assertNotIn("/V", [part for c in calls for part in c[0]])      # never window titles

    def test_an_unknown_answer_never_counts_as_quit(self):
        run, _ = self.fake_run(fail=("DeskDial.exe",))
        self.assertIsNone(t.running_companions(run))
        self.assertIsNone(t.companion_running(run))
        run, _ = self.fake_run(running=("NanoDControlCenter.exe",), fail=("DeskDial.exe",))
        self.assertTrue(t.companion_running(run))                          # one seen running is enough

        def broken(command, **kwargs):
            raise OSError("no tasklist")
        self.assertIsNone(t.companion_running(broken))
        self.assertIsNone(t.require_companion_quit(broken))

    def test_require_companion_quit_names_what_runs_and_both_tasks(self):
        for running in (("DeskDial.exe",), ("NanoDControlCenter.exe",)):
            run, _ = self.fake_run(running)
            with self.assertRaises(SystemExit) as caught:
                t.require_companion_quit(run)
            message = str(caught.exception)
            self.assertIn(f"{running[0]} is running and owns the knob", message)
            self.assertIn("'Desk Dial' or 'NanoD Control Center'", message)
        run, _ = self.fake_run()
        self.assertIs(t.require_companion_quit(run), False)
        # nanod_enter_bootloader_v2.py names COMPANION_IMAGE in its refusal: both images.
        self.assertEqual(t.COMPANION_IMAGE, "DeskDial.exe or NanoDControlCenter.exe")


@needs_tooling
class LadderRecordTests(unittest.TestCase):
    """Backup locks, write evidence and the newest written binary across A, B and C (real files in a
    temporary folder)."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("DIAGNOSTICS", "FIRMWARE_OUT", "BACKUPS"):
            self.enterContext(mock.patch.object(t, name, self.root))
        self.b, self.c = t.CURRENT.binary_profile("B"), t.CURRENT.binary_profile("C")

    def write(self, path, data, at=None):
        path.write_text(json.dumps(data) if isinstance(data, dict) else data, encoding="utf-8")
        if at is not None:
            os.utime(path, (at, at))
        return path

    def test_any_binary_locks_the_shared_backup(self):
        self.assertEqual(t.backup_locks(), [])
        self.write(self.b.flash_checks, {"writeAttempted": True})
        self.assertEqual(t.backup_locks(), ["cc5.4-B-flash-checks.json records a cc5.4 binary B write attempt"])
        self.assertEqual(t.backup_locks(self.c), t.backup_locks())          # one pair, one answer for every binary
        self.write(self.c.rollback_report, {"outcome": "ROLLED_BACK_VERIFIED_RESET"})
        self.write(self.c.manifest, {"installationStatus": "INSTALLED"})
        self.assertEqual(t.backup_locks(), ["cc5.4-B-flash-checks.json records a cc5.4 binary B write attempt",
                                            "cc5.4-C-rollback.json records a cc5.4 binary C rollback",
                                            "manifest-1.0.0-cc5.4-C.json status is INSTALLED"])
        self.assertEqual(t.backup_locks(t.PROFILES["cc5.3"]), [])            # another release's evidence never counts

    def test_write_evidence_covers_every_binary(self):
        self.assertEqual(t.release_write_evidence(t.CURRENT), [])
        self.write(self.c.flash_checks, {"flashWritten": True})
        self.write(t.CURRENT.manifest, {"installationStatus": "UNFLASHED"})
        self.write(self.b.manifest, {"installationStatus": "ROLLED_BACK"})
        self.assertEqual(t.release_write_evidence(t.CURRENT),
                         ["manifest-1.0.0-cc5.4-B.json status is ROLLED_BACK",
                          "cc5.4-C-flash-checks.json records a cc5.4 binary C write attempt"])
        self.assertEqual(t.binary_write_evidence(t.CURRENT), [])
        self.assertEqual(t.binary_write_evidence(self.c), ["cc5.4-C-flash-checks.json records a cc5.4 binary C write attempt"])
        # The history default of rollback_nanod_cc5.py (--to cc4) must see a written B or C too.
        rollback = load_script("rollback_nanod_cc5.py")
        self.assertIn("1.0.0-cc5.4", rollback.later_write_evidence(t.ROLLBACK_TARGETS["cc4"]))

    def test_newest_written_binary(self):
        self.assertEqual(t.newest_written_binary(t.CURRENT), (None, None, []))
        self.write(t.CURRENT.flash_checks, {"writeAttempted": True, "startedUtc": "20260927T100000Z"}, 1_700_000_000)
        self.write(self.b.flash_checks, {"writeAttempted": False, "startedUtc": "20260927T120000Z"}, 1_700_000_200)
        self.assertEqual(t.newest_written_binary(self.b), ("A", "cc5.4-flash-checks.json", []))
        self.write(self.c.flash_checks, {"writeAttempted": True, "startedUtc": "20260927T110000Z"}, 1_700_000_100)
        self.assertEqual(t.newest_written_binary(t.CURRENT), ("C", "cc5.4-C-flash-checks.json", []))
        self.write(self.b.flash_checks, "{not json")
        self.assertEqual(t.newest_written_binary(t.CURRENT)[2], ["cc5.4-B-flash-checks.json is unreadable"])

    def test_history_names_and_later_profiles(self):
        history = t.history_backup_names(self.b)
        self.assertNotIn(self.b.before_full.name, history)
        self.assertNotIn(self.b.expected_full.name, history)
        self.assertEqual(history, t.history_backup_names(t.CURRENT))
        self.assertIn(t.PROFILES["cc5.3"].before_full.name, history)
        # A later release's history holds every binary's expected image of this one.
        self.assertTrue({v.expected_full.name for v in t.CURRENT.variants()} <= t.history_backup_names(t.PROFILES["cc5.3"]))
        self.assertEqual(t.later_profiles(self.b), [])
        self.assertEqual(t.later_profiles(t.PROFILES["cc5.3"]), [t.CURRENT])


@needs_tooling
class LadderBuildAndPackageTests(BuildAndPackageFixture):
    """build_ and package_nanod_cc5.py --binary B and C: their flags and folder reach PlatformIO, each binary
    gets its own log, record, image, source archive and UNFLASHED manifest, and a build whose flags did not
    take effect is rejected."""

    def build_all(self):
        for name in ("A", "B", "C"):
            self.assertEqual(self.build.main(["--binary", name]), 0, name)

    def test_b_and_c_build_into_their_own_folders_with_their_flags(self):
        with mock.patch.dict(os.environ, {"PLATFORMIO_BUILD_FLAGS": "-DLEAKED=1", "PLATFORMIO_BUILD_DIR": "elsewhere"}):
            self.build_all()
        self.assertEqual(len(self.commands), 3)
        self.assertTrue(all(c[1:] == ["-m", "platformio", "run", "-d", str(t.FIRMWARE_SOURCE), "-e", t.PIO_ENV]
                            for c in self.commands))                          # never an upload target
        self.assertNotIn("PLATFORMIO_BUILD_FLAGS", self.envs[0])                # the caller's variables never leak
        self.assertNotIn("PLATFORMIO_BUILD_DIR", self.envs[0])
        records = {}
        for env, name in zip(self.envs, "ABC"):
            v = t.CURRENT.binary_profile(name)
            records[name] = record = t.load_json(v.build_report)
            if name != "A":
                self.assertEqual(env["PLATFORMIO_BUILD_FLAGS"], " ".join(LADDER_FLAGS[name]))
                self.assertEqual(env["PLATFORMIO_BUILD_DIR"], str(v.build_dir))
            self.assertEqual(env["PLATFORMIO_CORE_DIR"], str(t.PIO_CORE))
            self.assertEqual((record["accepted"], record["binary"], record["buildFlags"], record["pipeline"]),
                             (True, name, list(LADDER_FLAGS[name]), t.LCD_BINARIES[name]))
            self.assertEqual(record["sha256"], t.sha256_file(v.built_image))
            self.assertEqual(record["heapProjection"]["hBytes"], 512 if name != "C" else 0)   # 12.4: H in A and B only
            self.assertEqual(record["pipelineEvidence"]["imageHoldsR5Task"], name == "A")
            self.assertEqual(record["pipelineEvidence"]["elfLinksR3Buffer"], name != "C")
            self.assertIn(f"binary {name}", v.build_log.read_text(encoding="utf-8"))
        self.assertEqual(len({r["sha256"] for r in records.values()}), 3)
        self.assertTrue(t.BUILT_IMAGE.is_file())                                 # A's output was never replaced
        self.assertEqual(t.sha256_file(t.BUILT_IMAGE), records["A"]["sha256"])

    def test_each_binary_is_packaged_under_its_own_names(self):
        self.build_all()
        for name in ("A", "B", "C"):
            self.assertEqual(self.module.main(["--binary", name]), 0, name)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), self.active)          # manifest.json untouched
        images = set()
        for name in ("A", "B", "C"):
            with self.subTest(name):
                v = t.CURRENT.binary_profile(name)
                manifest = t.load_json(v.manifest)
                self.assertEqual((manifest["firmwareVersion"], manifest["installationStatus"]), ("1.0.0-cc5.4", "UNFLASHED"))
                self.assertEqual(set(manifest["artifacts"]), {v.image.name, v.source_zip.name})
                self.assertEqual(manifest["artifacts"][v.image.name]["sha256"], t.load_json(v.build_report)["sha256"])
                self.assertEqual(v.image.read_bytes(), v.built_image.read_bytes())
                binary = manifest["binary"]
                self.assertEqual((binary["name"], binary["buildFlags"], binary["pipeline"], binary["buildRecord"]),
                                 (name, list(LADDER_FLAGS[name]), t.LCD_BINARIES[name], f"diagnostics/{v.build_report.name}"))
                self.assertEqual(binary["timingTargets"]["lcdFpsAnimMin"], t.LCD_FPS_TARGETS[name])
                self.assertIn(f"diagnostics/{v.build_report.name}", manifest["gates"])
                self.assertIn(f"Binary {name}", manifest["hardwareStatus"])
                images.add(manifest["image"]["sha256"])
        self.assertEqual(len(images), 3)
        # Packaging B again keeps its previous package; A's and C's are never touched.
        a_before = t.CURRENT.manifest.read_bytes()
        self.assertEqual(self.module.main(["--binary", "B"]), 0)
        self.assertEqual(t.CURRENT.manifest.read_bytes(), a_before)
        self.assertEqual(len(list(t.FIRMWARE_OUT.glob("manifest-1.0.0-cc5.4-B.superseded-*.json"))), 1)
        self.assertEqual(list(t.FIRMWARE_OUT.glob("manifest-1.0.0-cc5.4.superseded-*.json")), [])

    def test_flags_that_did_not_take_effect_are_rejected(self):
        self.assertEqual(self.build.main(["--binary", "A"]), 0)
        self.ignore_flags = True                                               # PlatformIO built A's pipeline again
        for name in ("B", "C"):
            with self.subTest(name):
                self.assertEqual(self.build.main(["--binary", name]), 1)
                record = t.load_json(t.CURRENT.binary_profile(name).build_report)
                self.assertFalse(record["accepted"])
                text = " ".join(record["problems"])
                self.assertIn(f"binary {name} must not contain the R5 decode task", text)
                self.assertIn("identical to binary A's accepted image", text)
                if name == "C":
                    self.assertIn("binary C must not link the R3 draw buffer", text)
                with self.assertRaises(SystemExit) as caught:
                    self.module.main(["--binary", name])
                self.assertIn(f"does not record an accepted 1.0.0-cc5.4 build; run build_nanod_cc5.py --binary {name}",
                              str(caught.exception))

    def test_a_build_without_its_elf_is_rejected_and_records_must_name_their_binary(self):
        self.assertEqual(self.build.main(["--binary", "B"]), 0)
        b = t.CURRENT.binary_profile("B")
        b.built_elf.unlink()
        self.write_elf = False                                                   # a build that left no ELF
        self.assertEqual(self.build.main(["--binary", "B"]), 1)
        self.assertIn("firmware.elf is missing", " ".join(t.load_json(b.build_report)["problems"]))
        self.assertEqual(len(list(t.DIAGNOSTICS.glob("cc5.4-B-build.superseded-*.json"))), 1)   # the first record kept
        self.write_elf = True
        self.assertEqual(self.build.main(["--binary", "B"]), 0)
        record = t.load_json(b.build_report)
        t.write_json_evidence(b.build_report, {**record, "binary": "C"})          # a record of another binary
        with self.assertRaises(SystemExit) as caught:
            self.module.main(["--binary", "B"])
        self.assertIn("records binary C, not B", str(caught.exception))
        self.assertFalse(b.manifest.exists())


def cc54_prepare_fixture(case, root, binary):
    """The files prepare_nanod_cc5_install.py --binary <binary> reads for 1.0.0-cc5.3 -> 1.0.0-cc5.4, in `root`
    (the PrepareFlowTests shape with cc5.3 as the installed release). Returns (profile, before, candidate)."""
    backups, diag, fw = root / "backups", root / "diagnostics", root / "firmware"
    for folder in (backups, diag, fw):
        folder.mkdir()
    for name, value in (("BACKUPS", backups), ("DIAGNOSTICS", diag), ("FIRMWARE_OUT", fw),
                        ("ACTIVE_MANIFEST", fw / "manifest.json"),
                        ("ORIGINAL_MANIFEST", backups / t.ORIGINAL_MANIFEST.name)):
        case.patch(t, name, value)
    p = t.CURRENT.binary_profile(binary)
    installed = b"\xe9" + b"cc5.3-image" * 300
    case.patch(t.CURRENT, "from_image_sha256", hashlib.sha256(installed).hexdigest())
    case.patch(t.CURRENT, "from_image_bytes", len(installed))
    case.patch(t.CURRENT, "from_expected_sha256", None)
    for variant in t.CURRENT.variants():
        if variant is not t.CURRENT:     # variants copied the release's values when created
            case.patch(variant, "from_image_sha256", hashlib.sha256(installed).hexdigest())
            case.patch(variant, "from_image_bytes", len(installed))
            case.patch(variant, "from_expected_sha256", None)
    before = bytearray(b"\x5a" * t.FLASH_BYTES)
    before[0x8000:0x9000] = partition_table(LAYOUT)
    before[0xE000:0x10000] = ota_slot(1) + ota_slot(0)
    original = bytes(before)
    before[t.APP_OFFSET:t.APP_OFFSET + len(installed)] = installed
    before = bytes(before)
    p.before_full.write_bytes(before)
    p.backup_report.write_text(json.dumps({"passed": True, "sha256": hashlib.sha256(before).hexdigest(),
                                           "role": "pre-cc5.4 backup", "file": p.before_full.name}), encoding="utf-8")
    (backups / "original-full.bin").write_bytes(original)
    t.ORIGINAL_MANIFEST.write_text(json.dumps({
        "full_flash_file": "original-full.bin", "full_flash_sha256": hashlib.sha256(original).hexdigest(),
        "partitions": [dict(zip(("name", "type", "subtype", "offset", "size"), row)) for row in LAYOUT]}),
        encoding="utf-8")
    p.from_image.write_bytes(installed)
    record = {"firmwareVersion": "1.0.0-cc5.3", "installationStatus": "INSTALLED",
              "artifacts": {p.from_image.name: {"sha256": p.from_image_sha256}}}
    p.from_record.write_text(json.dumps(record), encoding="utf-8")
    shutil.copyfile(p.from_record, t.ACTIVE_MANIFEST)
    candidates = {}
    for variant in t.CURRENT.variants():
        image = (b"\xe9" + f"cc5.4-{variant.binary}-image".encode() * 400 + b"1.0.0-cc5.4\0"
                 + (t.R5_IMAGE_MARKER if variant.pipeline["artAsync"] else b"")
                 + (t.BUILD_MARKER_PREFIX + str(variant.build_number).encode("ascii") + b"\0"
                    if variant.build_number is not None else b""))
        candidates[variant.binary] = image
        variant.image.write_bytes(image)
        variant.manifest.write_text(json.dumps({"firmwareVersion": "1.0.0-cc5.4", "installationStatus": "UNFLASHED",
                                                "binary": {"name": variant.binary},
                                                "artifacts": {variant.image.name: {"sha256": t.sha256_bytes(image)}}}),
                                    encoding="utf-8")
    (backups / "inventory-before.json").write_text(json.dumps({"settings": {"firmwareVersion": "1.0.0-cc5.3"},
                                                               "capabilities": {"presentation": 4}}), encoding="utf-8")
    return p, before, candidates


@needs_tooling
class LadderPrepareFlowTests(HardwareFreeScriptTest):
    """prepare_nanod_cc5_install.py --binary for cc5.4: every binary is prepared from the one pre-cc5.4 backup,
    each with its own expected image and preparation record; the rollback app0 is shared."""
    script, capture_evidence = "prepare_nanod_cc5_install.py", False

    def setUp(self):
        super().setUp()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.p, self.before, self.candidates = cc54_prepare_fixture(self, self.root, "B")

    def prepare(self, binary):
        return self.module.main(["--before-inventory", "inventory-before.json", "--binary", binary])

    def test_every_binary_is_prepared_from_the_same_backup(self):
        for name in ("A", "B", "C"):
            self.assertEqual(self.prepare(name), 0, name)
        rollback = self.before[t.APP_OFFSET:t.APP_OFFSET + t.APP_SIZE]
        self.assertEqual(t.CURRENT.rollback_app.read_bytes(), rollback)
        self.assertEqual(list(t.BACKUPS.glob("*.superseded-*")), [])             # the identical rollback app0 was kept
        for name in ("A", "B", "C"):
            with self.subTest(name):
                v = t.CURRENT.binary_profile(name)
                expected, _ = t.assemble_expected(self.before, self.candidates[name])
                self.assertEqual(v.expected_full.read_bytes(), bytes(expected))
                prep = t.load_json(v.preparation)
                self.assertEqual((prep["binary"], prep["candidateFile"], prep["expectedFile"], prep["manifestFile"],
                                  prep["buildFlags"], prep["rollbackFile"]),
                                 (name, v.image.name, v.expected_full.name, v.manifest.name, list(LADDER_FLAGS[name]),
                                  t.CURRENT.rollback_app.name))
                self.assertEqual(prep["candidateSha256"], t.sha256_bytes(self.candidates[name]))
                self.assertEqual(prep["rollbackSha256"], t.sha256_bytes(rollback))
        self.assertIn("Next: install_nanod_cc5.py --binary C", self.out.getvalue())

    def test_a_package_of_another_binary_or_pipeline_is_refused(self):
        b = t.CURRENT.binary_profile("B")
        manifest = t.load_json(b.manifest)
        b.manifest.write_text(json.dumps({**manifest, "binary": {"name": "C"}}), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.prepare("B")
        self.assertIn("does not package binary B; run package_nanod_cc5.py --binary B", str(caught.exception))
        # B's image holding the R5 task (A's pipeline) is refused, whatever its manifest says.
        image = self.candidates["B"] + t.R5_IMAGE_MARKER
        b.image.write_bytes(image)
        b.manifest.write_text(json.dumps({**manifest, "artifacts": {b.image.name: {"sha256": t.sha256_bytes(image)}}}),
                              encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.prepare("B")
        self.assertIn("binary B must not contain the R5 decode task", str(caught.exception))
        self.assertFalse(b.expected_full.exists() or b.preparation.exists())


@needs_tooling
class LadderInstallFlowTests(HardwareFreeScriptTest):
    """install_nanod_cc5.py --binary B|C: the binary's image, expected image, flash record and logs; the
    restore path writes the shared cc5.3 rollback app0."""
    script = "install_nanod_cc5.py"

    def run_install(self, binary, **results):
        fake = FakeEsptool(results)
        self.patch(t, "Esptool", fake.factory)
        self.patch(t, "load_json", lambda path: {"candidateSha256": "c" * 64})
        self.patch(self.module, "verify_inputs", lambda prep, manifest, p=None: self.verified.append(p))
        self.verified = []
        code = self.module.main(["--binary", binary])
        name, report = self.evidence[-1]
        return code, name, report, fake

    def test_each_binary_writes_its_own_image_and_records(self):
        for binary in ("B", "C"):
            with self.subTest(binary):
                v = t.CURRENT.binary_profile(binary)
                code, name, report, fake = self.run_install(binary)
                self.assertEqual((code, name, report["outcome"]), (0, v.flash_checks.name, "INSTALLED_VERIFIED_RESET"))
                self.assertEqual((report["binary"], report["buildFlags"], report["candidate"]),
                                 (binary, list(LADDER_FLAGS[binary]), v.image.name))
                self.assertEqual(fake.prefix, f"cc5.4-{binary}")
                self.assertEqual(fake.args("write")[-2:], ["0x10000", str(v.image)])
                self.assertEqual(fake.args("after-verify")[-1], str(v.expected_full))
                self.assertEqual(fake.args("before-verify")[-1], str(t.CURRENT.before_full))
                self.assertIs(self.verified[-1], v)
                self.assertIn(f"check_nanod_cc5.py --binary {binary}", self.out.getvalue())

    def test_a_failed_binary_restores_cc5_3(self):
        code, name, report, fake = self.run_install("C", **{"after-verify": False})
        self.assertEqual((code, report["outcome"]), (3, "RESTORED_CC5_3_RESET"))
        self.assertEqual(fake.args("restore-write")[-2:], ["0x10000", str(t.CURRENT.rollback_app)])
        self.assertEqual(fake.args("restore-verify-full")[-1], str(t.CURRENT.before_full))

    def test_verify_inputs_refuses_another_binarys_preparation(self):
        module = load_script("install_nanod_cc5.py")
        b = t.CURRENT.binary_profile("B")
        for prep, manifest in (({"binary": "A"}, {"binary": {"name": "B"}}), ({"binary": "B"}, {"binary": {"name": "C"}}),
                               ({}, {})):
            with self.assertRaises(SystemExit) as caught:
                module.verify_inputs(prep, manifest, b)
            self.assertIn("is not for binary B; run prepare_nanod_cc5_install.py --binary B; nothing was sent",
                          str(caught.exception))


@needs_tooling
class RollbackToCc53BinaryBFlowTests(RollbackFlowTests):
    """Every rollback case again for rollback_nanod_cc5.py --to cc5.3 --binary B: B's preparation hashes,
    evidence, work folder and logs, and the shared pre-cc5.4 backup pair."""
    TARGET, ARGV = "cc5.3", ("--to", "cc5.3", "--binary", "B")

    def setUp(self):
        super().setUp()
        self.profile = t.ROLLBACK_TARGETS["cc5.3"].binary_profile("B")

    def test_binary_b_names(self):
        code, report, fake = self.run_rollback()
        self.assertEqual((code, report["binary"], report["binarySource"], report["target"]), (0, "B", "--binary", "cc5.3"))
        self.assertEqual((report["rollbackFile"], report["backupFile"]),
                         ("nanod-cc5.3-before-cc5.4-active-app.bin", "nanod-cc5.3-before-cc5.4-full.bin"))
        self.assertEqual(self.prepared, ["cc5.4-B-preparation.json"])
        self.assertEqual(fake.prefix, "cc5.4-B-rollback")


@needs_tooling
class LadderRollbackChoiceTests(RollbackFlowTests):
    """Without --binary, --to cc5.3 rolls back the binary the records show written last (else A); unknowable
    or misplaced choices are usage errors that send nothing."""
    TARGET, ARGV = "cc5.3", ("--to", "cc5.3")

    def test_the_newest_written_binary_is_chosen(self):
        c = t.CURRENT.binary_profile("C")
        c.flash_checks.write_text(json.dumps({"writeAttempted": True, "startedUtc": "20260927T110000Z"}), encoding="utf-8")
        self.profile = c
        code, report, _ = self.run_rollback()
        self.assertEqual((code, report["binary"]), (0, "C"))
        self.assertEqual(report["binarySource"], "records (newest write: cc5.4-C-flash-checks.json)")
        self.assertEqual(self.prepared, ["cc5.4-C-preparation.json"])

    def test_no_write_means_binary_a(self):
        code, report, _ = self.run_rollback()
        self.assertEqual((code, report["binary"]), (0, "A"))
        self.assertIn("default", report["binarySource"])

    def usage_error(self, argv):
        fake = FakeEsptool()
        self.patch(t, "Esptool", fake.factory)
        environment = mock.Mock()
        self.patch(t, "assert_flash_environment", environment)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            self.module.main(argv)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual((fake.calls, self.evidence, environment.call_count), ([], [], 0))
        return stderr.getvalue()

    def test_unreadable_records_or_a_binary_elsewhere_are_usage_errors(self):
        t.CURRENT.binary_profile("B").flash_checks.write_text("{not json", encoding="utf-8")
        text = self.usage_error(["--to", "cc5.3"])
        self.assertIn("--binary is required: cc5.4-B-flash-checks.json is unreadable", text)
        text = self.usage_error(["--to", "cc5.2", "--binary", "B"])
        self.assertIn("--binary applies only to a release built as the PRESENTATION_V5 12.6 ladder (--to cc5.3)", text)

    def test_a_binary_never_prepared_sends_nothing(self):
        self.patch(t, "load_json", mock.Mock(side_effect=FileNotFoundError("cc5.4-C-preparation.json")))
        fake = FakeEsptool()
        self.patch(t, "Esptool", fake.factory)
        with self.assertRaises(SystemExit) as caught:
            self.module.main(["--to", "cc5.3", "--binary", "C"])
        self.assertIn("cc5.4-C-preparation.json is missing: cc5.4 binary C was never prepared", str(caught.exception))
        self.assertEqual((fake.calls, self.evidence), ([], []))


@needs_tooling
class LadderRollbackRecordTests(unittest.TestCase):
    """restore_records for binary B: manifest.json from the cc5.3 record, B's INSTALLED manifest (and any
    other binary's) ROLLED_BACK, pointing at B's rollback record."""

    def setUp(self):
        self.module = load_script("rollback_nanod_cc5.py")
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name, value in (("FIRMWARE_OUT", self.root), ("ACTIVE_MANIFEST", self.root / "manifest.json"),
                            ("BACKUPS", self.root), ("DIAGNOSTICS", self.root)):
            self.enterContext(mock.patch.object(t, name, value))
        image = b"\xe9 cc5.3 image" * 50
        for v in t.CURRENT.variants():
            self.enterContext(mock.patch.object(v, "from_image_sha256", t.sha256_bytes(image)))
        t.CURRENT.from_record.write_text(json.dumps({"firmwareVersion": "1.0.0-cc5.3", "installationStatus": "INSTALLED",
                                                     "artifacts": {t.CURRENT.from_image.name: {"sha256": t.sha256_bytes(image)}}}),
                                         encoding="utf-8")

    def test_binary_b_rollback_marks_its_manifest(self):
        b = t.CURRENT.binary_profile("B")
        installed = {"firmwareVersion": "1.0.0-cc5.4", "installationStatus": "INSTALLED", "binary": {"name": "B"}}
        b.manifest.write_text(json.dumps(installed), encoding="utf-8")
        t.ACTIVE_MANIFEST.write_text(json.dumps(installed), encoding="utf-8")
        t.CURRENT.manifest.write_text(json.dumps({"installationStatus": "UNFLASHED"}), encoding="utf-8")
        report = {}
        self.module.restore_records(report, b)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), t.CURRENT.from_record.read_bytes())
        [kept] = self.root.glob("manifest-at-cc5.4-B-rollback-*.json")
        self.assertEqual(report["manifestRestored"]["previousKeptAs"], kept.name)
        self.assertEqual(report["manifestsMarkedRolledBack"], ["manifest-1.0.0-cc5.4-B.json"])
        marked = t.load_json(b.manifest)
        self.assertEqual((marked["installationStatus"], marked["rollback"]), ("ROLLED_BACK", "diagnostics/cc5.4-B-rollback.json"))
        self.assertEqual(t.load_json(t.CURRENT.manifest), {"installationStatus": "UNFLASHED"})   # A untouched
        self.assertEqual(self.module.removed_releases(b), ["1.0.0-cc5.4"])
        self.assertEqual([m.name for m in self.module.removed_manifests(t.ROLLBACK_TARGETS["cc5.2"])],
                         ["manifest-1.0.0-cc5.3.json", "manifest-1.0.0-cc5.4.json", "manifest-1.0.0-cc5.4-B.json",
                          "manifest-1.0.0-cc5.4-C.json", "manifest-1.0.0-cc5.4-D.json", "manifest-1.0.0-cc5.4-E.json"])


@needs_tooling
class LadderFinalizeFlowTests(Cc54FinalizeFlowTests):
    """finalize_nanod_cc5.py --binary B after a step-down: B's own preparation, flash record, manifest and
    installation record; the device checks must report B; a rollback of A before B's install is history."""
    BINARY = "B"

    def records(self):
        records = super().records()
        sha = t.sha256_bytes
        v = t.CURRENT.binary_profile(self.BINARY)
        B = self.BASE
        records["image"] = (v.image, self.image, B)
        records["source"] = (v.source_zip, self.source, B)
        _, manifest, _ = records["cc5_manifest"]
        records["cc5_manifest"] = (v.manifest, {**manifest, "binary": {"name": self.BINARY},
                                                "artifacts": {v.image.name: {"sha256": sha(self.image)},
                                                              v.source_zip.name: {"sha256": sha(self.source)}}}, B)
        # Binary A's package stays UNFLASHED next to it (it was written and rolled back before B's install).
        records["a_manifest"] = (t.CURRENT.manifest, {"firmwareVersion": "1.0.0-cc5.4", "installationStatus": "UNFLASHED",
                                                      "binary": {"name": "A"}}, B)
        _, prep, at = records["prep"]                   # A was prepared too (every binary is, right after the backup)
        records["prep_b"] = (v.preparation, {**prep, "binary": self.BINARY}, at)
        _, flash, at = records["flash"]
        del records["flash"]
        records["flash_b"] = (v.flash_checks, flash, at)
        path, device, at = records["device"]
        records["device"] = (path, {**device, "sections": {"diag": {"binary": self.BINARY}},
                                    "binary": {"expected": self.BINARY, "reported": self.BINARY}}, at)
        # A's install and rollback, both before B's install (file times and stamps).
        records["a_flash"] = (t.CURRENT.flash_checks, {**flash, "startedUtc": "20260923T060000Z",
                                                       "finishedUtc": "20260923T060200Z"}, B - 400)
        records["a_rollback"] = (t.CURRENT.rollback_report, {"startedUtc": "20260923T063000Z",
                                                             "finishedUtc": "20260923T063300Z",
                                                             "outcome": "ROLLED_BACK_VERIFIED_RESET"}, B - 300)
        return records

    def test_verified_cc5_4_install_is_recorded_and_supersedes_cc5_3(self):
        v = t.CURRENT.binary_profile(self.BINARY)
        a_manifest = t.CURRENT.manifest.read_bytes()
        self.assertEqual(self.module.main(["--companion-tests", "1500", "--binary", self.BINARY]), 0)
        report = t.load_json(v.installation)
        self.assertEqual(v.installation.name, f"cc5.4-{self.BINARY}-installation.json")
        self.assertEqual((report["firmwareVersion"], report["binary"], report["buildFlags"], report["manifestFile"]),
                         ("1.0.0-cc5.4", self.BINARY, list(LADDER_FLAGS[self.BINARY]), v.manifest.name))
        self.assertEqual(report["ladder"]["A"]["manifestStatus"], "UNFLASHED")
        self.assertTrue(report["ladder"]["A"]["writeEvidence"])                   # A was written, then rolled back
        self.assertTrue(report["ladder"][self.BINARY]["recorded"])
        manifest = t.load_json(v.manifest)
        self.assertEqual(manifest["installationStatus"], "INSTALLED")
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), v.manifest.read_bytes())
        self.assertEqual(t.CURRENT.manifest.read_bytes(), a_manifest)             # A's package is left as it was
        self.assertFalse(t.CURRENT.installation.exists())
        validation = t.load_json(self.diag / "validation.json")
        self.assertEqual((validation["cc5.4"]["binary"], validation["cc5.4"]["manifest"]), (self.BINARY, v.manifest.name))
        self.assertEqual(t.load_json(self.fw / "manifest-1.0.0-cc5.3.json")["installationStatus"], "SUPERSEDED")

    def test_cc5_4_evidence_is_required(self):
        v = t.CURRENT.binary_profile(self.BINARY)
        cases = {
            f"shows binary A on the knob (diag lcdDma / lcdPeriodMs / artAsync), not binary {self.BINARY}; if binary A "
            "was installed, run with --binary A": dict(device={"sections": {"diag": {"binary": "A"}}}),
            f"shows binary None on the knob": dict(device={"sections": {}}),
            f"{v.preparation.name} does not prepare binary {self.BINARY}": dict(prep_b={"binary": "A"}),
            "does not show presentation 5": dict(device={"capabilities": {"presentation": 4}}),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment):
                self.build(**change)
                self.assert_refused(fragment, "--binary", self.BINARY)

    def test_without_binary_the_rolled_back_a_is_refused(self):
        self.assert_refused("cc5.4-rollback.json records a cc5.4 -> cc5.3 rollback", "--companion-tests", "1")

    def test_a_rollback_of_any_binary_after_the_install_is_refused(self):
        v = t.CURRENT.binary_profile(self.BINARY)
        for key, path in (("b_rollback", v.rollback_report), ("a_rollback_late", t.CURRENT.rollback_report)):
            with self.subTest(key):
                self.build()
                self.write(path, {"startedUtc": "20260923T080000Z", "outcome": "ROLLED_BACK_VERIFIED_RESET"},
                           self.BASE + 400)
                label = "cc5.4 binary B" if path == v.rollback_report else "cc5.4"
                self.assert_refused(f"{path.name} records a {label} -> cc5.3 rollback", "--binary", self.BINARY)
        self.build()
        self.folder(self.backups / "cc5.4-B-rollback-20260923T080000Z", ["current-partitions.bin"], self.BASE + 400)
        self.assert_refused("backups/cc5.4-B-rollback-20260923T080000Z shows rollback_nanod_cc5.py ran against the device",
                            "--binary", self.BINARY)


# ---------------------------------------------------------------------------
# Review fixes TOOLBC-1..3: the step-down base (A panicked, its rollback kept the core dump, B installs), the
# build log kept instead of overwritten, and the PRESENTATION_V5 12.4 sizes in every binary's record.

class DeviceEsptool(FakeEsptool):
    """A FakeEsptool with the knob's 4 MB flash in memory (`device`): read_flash copies bytes out of it,
    verify_flash compares a file with it, and write_flash (only the app0 shape validate_esptool_args allows)
    erases the 4 KB sectors it covers and writes the file there, as esptool does. `results` still force a
    step's result (False, or an exception) before the flash is touched."""

    def __init__(self, device, results=None):
        super().__init__(results)
        self.device = bytearray(device)

    def __call__(self, name, args, *, after="no_reset_stub", timeout=240):
        args = t.validate_esptool_args(args)
        self.calls.append((name, args, after))
        self.report["steps"].append({"step": name, "after": after})
        forced = self.results.get(name, True)
        if isinstance(forced, BaseException):
            raise forced
        if forced is False:
            return False, "A fatal error occurred"
        ok = True
        if args[0] == "read_flash":
            offset, size = int(args[1], 16), int(args[2], 16)
            Path(args[3]).write_bytes(bytes(self.device[offset:offset + size]))
        elif args[0] == "verify_flash":
            offset, data = int(args[1], 16), Path(args[2]).read_bytes()
            ok = bytes(self.device[offset:offset + len(data)]) == data
        elif args[0] == "write_flash":
            offset, data = int(args[-2], 16), Path(args[-1]).read_bytes()
            end = t.sector_end(offset, len(data))
            self.device[offset:end] = b"\xff" * (end - offset)
            self.device[offset:offset + len(data)] = data
        if not ok:
            return False, "A fatal error occurred: verify failed"
        return True, RESET_OUTPUT if args[0] == "read_mac" else MAC_OUTPUT


@needs_tooling
class StepDownFlowTests(HardwareFreeScriptTest):
    """TOOLBC-1: the 12.6 step-down A -> B through the real backup, prepare, install and rollback scripts against
    a knob modelled in memory (DeviceEsptool). A is installed, panics (its core dump lands in the coredump
    partition) and is rolled back verified with that drift; B then installs from a step-down base while the
    locked pre-cc5.4 backup and its record stay exactly as they were, and B's rollback still verifies against
    that locked backup."""
    script, capture_evidence = "install_nanod_cc5.py", False
    # What A's panic leaves at coredump (0x3F0000): its first word is the image size esp_core_dump_image_get reports.
    CORE_DUMP_BYTES = 11852
    CORE_DUMP = struct.pack("<I", CORE_DUMP_BYTES) + b"core dump of binary A: task_wdt"
    INVENTORY = ("--before-inventory", "inventory-before.json")

    def setUp(self):
        super().setUp()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.p, self.before, self.candidates = cc54_prepare_fixture(self, root, "B")
        self.patch(t, "ORIGINAL_PARTITIONS", root / "no-original-partitions.bin")
        self.b = t.CURRENT.binary_profile("B")
        self.fake = DeviceEsptool(self.before)
        self.patch(t, "Esptool", self.fake.factory)
        self.backup = load_script("backup_nanod_cc5.py")
        self.prepare = load_script("prepare_nanod_cc5_install.py")
        self.rollback = load_script("rollback_nanod_cc5.py")
        self.locked = (t.CURRENT.before_full.read_bytes(), t.CURRENT.backup_report.read_bytes())

    def tearDown(self):
        # Whatever ran, the locked pre-cc5.4 backup and its record were never replaced or rewritten.
        self.assertEqual((t.CURRENT.before_full.read_bytes(), t.CURRENT.backup_report.read_bytes()), self.locked)
        self.assertEqual(list(t.BACKUPS.glob("nanod-cc5.3-before-cc5.4-full.superseded-*"))
                         + list(t.DIAGNOSTICS.glob("cc5.4-backup.superseded-*")), [])

    def run_script(self, module, *argv):
        self.fake.calls = []
        return module.main(list(argv))

    def install_a_then_roll_it_back_after_a_panic(self):
        """Steps 5, 6 (A), A's panic, and A's verified rollback; returns the flash as the rollback left it."""
        for name in ("A", "B", "C"):
            self.assertEqual(self.run_script(self.prepare, *self.INVENTORY, "--binary", name), 0, name)
        self.assertEqual(self.run_script(self.module, "--binary", "A"), 0)
        self.assertEqual(t.load_json(t.CURRENT.flash_checks)["outcome"], "INSTALLED_VERIFIED_RESET")
        self.fake.device[0x3F0000:0x3F0000 + len(self.CORE_DUMP)] = self.CORE_DUMP
        self.assertEqual(self.run_script(self.rollback, "--to", "cc5.3", "--binary", "A"), 0)
        record = t.load_json(t.CURRENT.rollback_report)
        self.assertEqual((record["outcome"], record["fullImageMatchesBackup"], record["dataRegionsChangedSinceBackup"]),
                         ("ROLLED_BACK_VERIFIED_RESET", False, ["coredump"]))
        self.assertIn("backup_nanod_cc5.py --step-down", self.out.getvalue())
        return bytes(self.fake.device)

    def step_down_to_b(self):
        device = self.install_a_then_roll_it_back_after_a_panic()
        self.assertEqual(self.run_script(self.backup, "--step-down"), 0)
        self.assertEqual(self.run_script(self.prepare, *self.INVENTORY, "--binary", "B", "--step-down-base"), 0)
        return device, t.BACKUPS / t.load_json(t.CURRENT.step_down_report)["file"]

    def test_a_rolled_back_with_coredump_drift_then_b_installs(self):
        device = self.install_a_then_roll_it_back_after_a_panic()
        app0 = slice(t.APP_OFFSET, t.APP_OFFSET + t.APP_SIZE)
        self.assertEqual(device[app0], self.before[app0])                       # cc5.3 is back in app0
        # The finding: B's step-5 preparation stops before writing, and the locked backup cannot be refreshed.
        self.assertEqual(self.run_script(self.module, "--binary", "B"), 2)
        self.assertNotIn("write", self.fake.names())
        self.assertEqual(t.load_json(self.b.flash_checks)["outcome"], "STOPPED_BEFORE_WRITE")
        self.assertIn("take a step-down base (backup_nanod_cc5.py --step-down)", self.out.getvalue())
        self.assertEqual(self.run_script(self.backup), 3)                      # kept as a diagnostic read
        # The step-down base: a verified read whose critical regions equal the locked backup.
        self.assertEqual(self.run_script(self.backup, "--step-down"), 0)
        self.assertEqual(self.fake.names(), ["identity", "read", "verify"])    # read-only on the device
        record = t.load_json(t.CURRENT.step_down_report)
        base = t.BACKUPS / record["file"]
        self.assertTrue(base.name.startswith("nanod-cc5.3-step-down-base-"), base.name)
        self.assertEqual(base.read_bytes(), device)
        self.assertEqual((record["role"], record["passed"], record["mode"], record["sha256"], record["lockedBackupSha256"],
                          record["criticalRegionsIdenticalToLockedBackup"], record["dataRegionsChangedSinceBackup"],
                          record["identicalToLockedBackup"], record["deviceWritten"]),
                         ("step-down base", True, "step-down", t.sha256_bytes(device), t.sha256_bytes(self.before), True,
                          ["coredump"], False, False))
        # B is prepared from it: the expected image keeps the core dump; the rollback reference stays the backup.
        self.assertEqual(self.run_script(self.prepare, *self.INVENTORY, "--binary", "B", "--step-down-base"), 0)
        prep = t.load_json(self.b.preparation)
        expected, _ = t.assemble_expected(device, self.candidates["B"])
        self.assertEqual(self.b.expected_full.read_bytes(), bytes(expected))
        self.assertEqual((prep["baseKind"], prep["baseFile"], prep["baseSha256"], prep["beforeFile"], prep["beforeSha256"],
                          prep["rollbackSha256"]),
                         ("step-down base", base.name, t.sha256_bytes(device), t.CURRENT.before_full.name,
                          t.sha256_bytes(self.before), t.sha256_bytes(self.before[app0])))
        self.assertEqual(prep["stepDown"]["dataRegionsChangedSinceBackup"], ["coredump"])
        self.assertEqual(len(list(t.DIAGNOSTICS.glob("cc5.4-B-preparation.superseded-*.json"))), 1)   # step 5's, kept
        # B installs: verified against the base before the write, and the full 4 MB after it.
        self.assertEqual(self.run_script(self.module, "--binary", "B"), 0)
        self.assertEqual(self.fake.names(), ["identity", "before-verify", "write", "after-verify", "reset"])
        self.assertEqual(self.fake.args("before-verify")[-1], str(base))
        self.assertEqual(self.fake.args("after-verify")[-1], str(self.b.expected_full))
        flash = t.load_json(self.b.flash_checks)
        self.assertEqual((flash["outcome"], flash["baseKind"], flash["baseFile"], flash["backupFile"]),
                         ("INSTALLED_VERIFIED_RESET", "step-down base", base.name, t.CURRENT.before_full.name))
        self.assertEqual(bytes(self.fake.device), bytes(expected))
        self.assertEqual(bytes(self.fake.device[0x3F0000:0x3F0000 + len(self.CORE_DUMP)]), self.CORE_DUMP)
        # B boots with A's core dump: check_nanod_cc5.py --binary B accepts exactly that dump (TB-D9), nothing else.
        inherited = t.step_down_coredump(t.CURRENT, "B")
        self.assertEqual(inherited, {"base": base.name, "partitionOffset": 0x3F0000, "bytes": self.CORE_DUMP_BYTES,
                                     "partitionSha256": t.sha256_bytes(device[0x3F0000:0x400000])})
        self.assertIsNone(t.step_down_coredump(t.CURRENT, "A"))                 # A was installed from the backup
        a_dump = boot_diag(coredump={"blank": False, "present": True, "status": "ESP_OK", "bytes": self.CORE_DUMP_BYTES})
        self.assertEqual(t.coredump_problems(a_dump, inherited), [])
        self.assertTrue(t.coredump_problems(a_dump))                             # strict without the step-down base
        self.assertIn(f"not the {self.CORE_DUMP_BYTES} B dump the step-down base {base.name} holds",
                      t.coredump_problems({**a_dump, "resetReason": "task_wdt"}, inherited)[0])   # B panicked
        self.assertTrue(t.coredump_problems({**a_dump, "coredump": {**a_dump["coredump"], "bytes": 9000}}, inherited))
        # B's rollback is unchanged: app0 back, verified against the locked backup, the drift reported again.
        self.assertEqual(self.run_script(self.rollback, "--to", "cc5.3", "--binary", "B"), 0)
        self.assertEqual(self.fake.args("verify-full")[-1], str(t.CURRENT.before_full))
        self.assertEqual(t.load_json(self.b.rollback_report)["dataRegionsChangedSinceBackup"], ["coredump"])
        self.assertEqual(bytes(self.fake.device), device)

    def test_a_failed_write_after_a_step_down_restores_cc5_3_against_the_base(self):
        device, base = self.step_down_to_b()
        self.fake.results["after-verify"] = False
        self.assertEqual(self.run_script(self.module, "--binary", "B"), 3)
        flash = t.load_json(self.b.flash_checks)
        self.assertEqual((flash["outcome"], flash["restoreFullImageVerified"], flash["reset"]),
                         ("RESTORED_CC5_3_RESET", True, True))
        self.assertEqual(self.fake.args("restore-verify-full")[-1], str(base))
        self.assertEqual(self.fake.resets(), ["restore-reset"])
        self.assertEqual(bytes(self.fake.device), device)                      # cc5.3 back, the core dump kept

    def test_the_step_down_read_needs_a_locked_backup_and_equal_critical_regions(self):
        with self.assertRaises(SystemExit) as caught:                          # no write attempted yet
            self.run_script(self.backup, "--step-down")
        self.assertIn("Refusing --step-down: no write of any cc5.4 binary was attempted", str(caught.exception))
        self.assertEqual(self.fake.calls, [])                                  # nothing was read
        self.install_a_then_roll_it_back_after_a_panic()
        self.fake.device[0x150000 + 7] ^= 0xFF                                # app1 changed: a critical region
        self.assertEqual(self.run_script(self.backup, "--step-down"), 3)
        self.assertFalse(t.CURRENT.step_down_report.exists())
        self.assertEqual(list(t.BACKUPS.glob("nanod-cc5.3-step-down-base-*")), [])
        [evidence] = t.DIAGNOSTICS.glob("cc5.4-backup-diagnostic-read-*.json")
        record = t.load_json(evidence)
        self.assertEqual((record["mode"], record["role"], record["criticalRegionsDiffering"],
                          record["dataRegionsChangedSinceBackup"]),
                         ("step-down", "diagnostic read", ["app1"], ["coredump"]))
        self.assertIn(f"the critical region(s) app1 differ from the locked {t.CURRENT.before_full.name}",
                      record["notConfirmedBecause"])

    def test_prepare_and_install_refuse_a_base_that_is_not_the_recorded_one(self):
        self.assertEqual(self.run_script(self.prepare, *self.INVENTORY, "--binary", "B"), 0)
        with self.assertRaises(SystemExit) as caught:                          # no step-down base read yet
            self.run_script(self.prepare, *self.INVENTORY, "--binary", "B", "--step-down-base")
        self.assertIn("cc5.4-step-down-base.json is missing or unreadable", str(caught.exception))
        device, base = self.step_down_to_b()
        record = t.load_json(t.CURRENT.step_down_report)
        # A base whose bootloader differs from the locked backup, even with a record rewritten to match it.
        tampered = bytearray(device)
        tampered[0x100] ^= 0xFF
        base.write_bytes(bytes(tampered))
        t.CURRENT.step_down_report.write_text(json.dumps({**record, "sha256": t.sha256_bytes(bytes(tampered))}),
                                              encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.run_script(self.prepare, *self.INVENTORY, "--binary", "C", "--step-down-base")
        self.assertIn("in the critical region(s) bootloader", str(caught.exception))
        with self.assertRaises(SystemExit) as caught:
            self.run_script(self.module, "--binary", "B")
        self.assertIn("in the critical region(s) bootloader", str(caught.exception))
        self.assertEqual(self.fake.calls, [])                                  # nothing was sent
        # A newer step-down base than the one B was prepared from: prepare again first.
        other = t.BACKUPS / "nanod-cc5.3-step-down-base-20990101T000000Z.bin"
        other.write_bytes(device)
        t.CURRENT.step_down_report.write_text(json.dumps({**record, "file": other.name}), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.run_script(self.module, "--binary", "B")
        self.assertIn("was prepared from another step-down base than cc5.4-step-down-base.json names", str(caught.exception))
        self.assertIn("--binary B --step-down-base; nothing was sent", str(caught.exception))
        self.assertEqual(self.fake.calls, [])
        # A step-down record read against another backup than the locked one.
        base.write_bytes(device)
        t.CURRENT.step_down_report.write_text(json.dumps({**record, "lockedBackupSha256": "0" * 64}), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.run_script(self.prepare, *self.INVENTORY, "--binary", "C", "--step-down-base")
        self.assertIn("was not read against the locked nanod-cc5.3-before-cc5.4-full.bin", str(caught.exception))

    def test_region_differences(self):
        changed = bytearray(self.before)
        changed[0x9000] ^= 1                                                   # nvs: data
        changed[0xE004] ^= 1                                                   # otadata: critical
        self.assertEqual(t.region_differences(self.before, bytes(changed)), (["otadata"], ["nvs"]))
        self.assertEqual(t.region_differences(self.before, self.before), ([], []))
        with self.assertRaises(ValueError):
            t.region_differences(self.before, self.before[:-1])
        self.assertTrue(t.is_critical_region("gap-0x1000") and t.is_critical_region("app1"))
        self.assertFalse(any(t.is_critical_region(name) for name in ("nvs", "spiffs", "coredump")))
        self.assertEqual((t.PRE_INSTALL_ROLE, t.STEP_DOWN_ROLE), ("pre-install backup", "step-down base"))
        self.assertEqual(t.CURRENT.step_down_base("X").name, "nanod-cc5.3-step-down-base-X.bin")
        self.assertEqual(self.b.step_down_report, t.CURRENT.step_down_report)  # one record for every binary


@needs_tooling
class LadderStepDownFinalizeFlowTests(LadderFinalizeFlowTests):
    """TOOLBC-1: finalize --binary B when B was prepared from the step-down base (A's rollback kept its core dump):
    the step-down record must name that base, read against the backup cc5.4-backup.json records, and B's flash
    record must name the same base. Every LadderFinalizeFlowTests case runs again on this evidence."""
    BASE_FILE = "nanod-cc5.3-step-down-base-20260923T064500Z.bin"

    def records(self):
        records = super().records()
        path, prep, at = records["prep_b"]
        records["prep_b"] = (path, {**prep, "baseKind": "step-down base", "baseFile": self.BASE_FILE,
                                    "baseSha256": "s" * 64}, at)
        path, flash, at = records["flash_b"]
        records["flash_b"] = (path, {**flash, "baseKind": "step-down base", "baseFile": self.BASE_FILE}, at)
        records["step_down"] = (t.CURRENT.step_down_report,
                                {"startedUtc": "20260923T064500Z", "mode": "step-down", "role": "step-down base",
                                 "passed": True, "file": self.BASE_FILE, "sha256": "s" * 64,
                                 "lockedBackupSha256": "b" * 64, "criticalRegionsIdenticalToLockedBackup": True,
                                 "dataRegionsChangedSinceBackup": ["coredump"]}, self.BASE - 250)
        return records

    def test_the_step_down_base_is_recorded_with_its_evidence(self):
        v = t.CURRENT.binary_profile(self.BINARY)
        self.assertEqual(self.module.main(["--companion-tests", "1500", "--binary", self.BINARY]), 0)
        report = t.load_json(v.installation)
        self.assertEqual(report["preWriteBase"], {"kind": "step-down base", "file": self.BASE_FILE,
                                                  "evidence": "cc5.4-step-down-base.json"})
        self.assertEqual(report["evidenceSha256"]["cc5.4-step-down-base.json"], t.sha256_file(t.CURRENT.step_down_report))

    def test_a_step_down_base_must_match_its_records(self):
        refused = "cc5.4-step-down-base.json does not record the step-down base cc5.4-B-preparation.json was prepared"
        cases = (("sha256", dict(step_down={"sha256": "0" * 64}), refused),
                 ("locked", dict(step_down={"lockedBackupSha256": "0" * 64}), refused),
                 ("passed", dict(step_down={"passed": False}), refused),
                 ("file", dict(step_down={"file": "nanod-cc5.3-step-down-base-other.bin"}), refused),
                 ("flash", dict(flash_b={"baseFile": "nanod-cc5.3-before-cc5.4-full.bin"}),
                  "cc5.4-B-flash-checks.json verified the device against nanod-cc5.3-before-cc5.4-full.bin, not the base"),
                 ("kind", dict(prep_b={"baseKind": "guess"}), "cc5.4-B-preparation.json names an unknown base (guess)"))
        for label, change, fragment in cases:
            with self.subTest(label):
                self.build(**change)
                self.assert_refused(fragment, "--binary", self.BINARY)
        self.build(drop=("step_down",))
        self.assert_refused("step-down base evidence (cc5.4-step-down-base.json) is missing", "--binary", self.BINARY)


@needs_tooling
class ElfSizeTests(unittest.TestCase):
    """TOOLBC-3: tooling.elf_symbols reads st_size and the symbol type; v5_size_record takes sizeof(CCFrame) and the
    ALIVE instance from the data objects hmi_thread.cpp defines, and the real ELFs have both when present."""

    def test_sizes_come_from_single_sized_data_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            elf = Path(folder) / "firmware.elf"
            elf.write_bytes(fake_elf(["setup", *V5_SIZE_SYMBOLS]))
            symbols = t.elf_symbols(elf)
            self.assertEqual(t.elf_symbol_names(elf), {"setup", t.CCFRAME_SYMBOLS[0], t.ALIVE_INSTANCE_SYMBOLS[0]})
        self.assertIn((t.CCFRAME_SYMBOLS[0], CCFRAME_BYTES, t.STT_OBJECT), symbols)
        record = t.v5_size_record(symbols)
        self.assertEqual((record["ccFrameBytes"], record["ccFrameSymbol"], record["aliveInstanceBytes"],
                          record["aliveInstanceSymbol"]),
                         (CCFRAME_BYTES, t.CCFRAME_SYMBOLS[0], ALIVE_INSTANCE_BYTES, t.ALIVE_INSTANCE_SYMBOLS[0]))
        self.assertEqual(t.v5_size_record(None)["ccFrameBytes"], None)
        self.assertEqual(t.elf_object_size([("alive", 40, 2)], t.ALIVE_INSTANCE_SYMBOLS), (None, None))   # a function
        ambiguous = [(t.ALIVE_INSTANCE_SYMBOLS[0], 11284, 1), (t.ALIVE_INSTANCE_SYMBOLS[0], 64, 1), ("alive", 900, 1)]
        self.assertEqual(t.elf_object_size(ambiguous, t.ALIVE_INSTANCE_SYMBOLS), ("alive", 900))
        self.assertEqual(t.V5_SIZE_FIELDS, ("ccFrameBytes", "aliveInstanceBytes"))

    def test_the_named_symbols_are_the_firmware_globals(self):
        """hmi_thread.cpp defines both in its anonymous namespace (the mangled names the tooling reads first)."""
        source = t.FIRMWARE_SOURCE / "src" / "hmi_thread.cpp"
        if not source.is_file():
            self.skipTest("firmware checkout not present")
        text = source.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^CCFrame cc_hmi_frame;")
        self.assertRegex(text, r"(?m)^CCAlive alive;")

    def test_the_real_elfs_give_both_sizes_when_present(self):
        """Read only: every built firmware.elf has both data objects with one size each."""
        for v in t.CURRENT.variants():
            if not v.built_elf.is_file():
                continue
            with self.subTest(v.binary):
                record = t.v5_size_record(t.elf_symbols(v.built_elf))
                self.assertIsInstance(record["ccFrameBytes"], int)
                self.assertIsInstance(record["aliveInstanceBytes"], int)
                self.assertGreater(record["aliveInstanceBytes"], record["ccFrameBytes"])


@needs_tooling
class BuildLogAndSizeTests(BuildAndPackageFixture):
    """TOOLBC-2: a rebuild keeps the earlier build log (every packaged manifest's gate hash stays resolvable), the
    build record carries the log's SHA-256, and packaging refuses a log that is not the accepted build's.
    TOOLBC-3: every binary's record carries sizeof(CCFrame) and the ALIVE instance size (PRESENTATION_V5 12.4)
    from firmware.elf, and so does its manifest; a record without them is never packaged."""

    def test_a_rebuild_keeps_the_log_every_packaged_manifest_pins(self):
        b = t.CURRENT.binary_profile("B")
        self.log_note = "first build\n"
        self.assertEqual(self.build.main(["--binary", "B"]), 0)
        first = b.build_log.read_bytes()
        record = t.load_json(b.build_report)
        self.assertEqual((record["logSha256"], record["logBytes"], record["previousLogKeptAs"]),
                         (t.sha256_bytes(first), len(first), None))
        self.assertEqual(self.module.main(["--binary", "B"]), 0)
        manifest = t.load_json(b.manifest)
        pinned = manifest["gates"][f"work/{b.build_log.name}"]["sha256"]
        self.assertEqual((pinned, manifest["binary"]["buildLogSha256"]), (t.sha256_bytes(first), t.sha256_bytes(first)))
        self.log_note = "second build\n"
        self.assertEqual(self.build.main(["--binary", "B"]), 0)
        self.assertEqual(self.module.main(["--binary", "B"]), 0)
        record = t.load_json(b.build_report)
        [kept] = t.WORK.glob("nanod-cc5.4-B-build.superseded-*.log")
        self.assertEqual((kept.read_bytes(), record["previousLogKeptAs"]), (first, kept.name))
        self.assertEqual(record["logSha256"], t.sha256_file(b.build_log))
        self.assertNotEqual(record["logSha256"], pinned)
        self.assertIn(f"previous kept as {kept.name}", self.out.getvalue())
        # Every manifest ever packaged, current or superseded, pins a log that still exists in work/.
        logs = {t.sha256_file(path) for path in t.WORK.glob("nanod-cc5.4-B-build*.log")}
        manifests = [b.manifest, *t.FIRMWARE_OUT.glob("manifest-1.0.0-cc5.4-B.superseded-*.json")]
        self.assertEqual(len(manifests), 2)
        for path in manifests:
            self.assertIn(t.load_json(path)["gates"][f"work/{b.build_log.name}"]["sha256"], logs, path.name)
        self.assertEqual(list(t.WORK.glob("nanod-cc5.4-build*.log")), [])     # the other binaries' logs untouched

    def test_packaging_needs_the_log_of_the_accepted_build(self):
        self.assertEqual(self.build.main([]), 0)
        with self.p.build_log.open("a", encoding="utf-8") as log:
            log.write("edited after the build\n")
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn("nanod-cc5.4-build.log is not the log of the accepted build (cc5.4-build.json logSha256); "
                      "run build_nanod_cc5.py --binary A again", str(caught.exception))
        record = t.load_json(self.p.build_report)
        del record["logSha256"]                                                # a record written before the fix
        t.write_json_evidence(self.p.build_report, record)
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn("does not record its build log's SHA-256 (logSha256)", str(caught.exception))
        self.assertFalse(self.p.manifest.exists() or self.p.image.exists())
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), self.active)

    def test_every_binary_records_the_12_4_sizes(self):
        for name in ("A", "B", "C"):
            self.assertEqual(self.build.main(["--binary", name]), 0, name)
            self.assertEqual(self.module.main(["--binary", name]), 0, name)
            v = t.CURRENT.binary_profile(name)
            for projection in (t.load_json(v.build_report)["heapProjection"],
                               t.load_json(v.manifest)["binary"]["heapProjection"]):
                self.assertEqual((projection["ccFrameBytes"], projection["ccFrameSymbol"], projection["aliveInstanceBytes"],
                                  projection["aliveInstanceSymbol"], projection["passed"]),
                                 (CCFRAME_BYTES, t.CCFRAME_SYMBOLS[0], ALIVE_INSTANCE_BYTES, t.ALIVE_INSTANCE_SYMBOLS[0],
                                  True))
        self.assertIn(f"sizeof(CCFrame) {CCFRAME_BYTES} B, ALIVE instance {ALIVE_INSTANCE_BYTES} B", self.out.getvalue())

    def test_a_build_without_the_sizes_is_rejected_and_never_packaged(self):
        c = t.CURRENT.binary_profile("C")
        self.elf_sizes = [(t.ALIVE_INSTANCE_SYMBOLS[0], ALIVE_INSTANCE_BYTES), (t.ALIVE_INSTANCE_SYMBOLS[0], 64)]
        self.assertEqual(self.build.main(["--binary", "C"]), 1)              # no CCFrame, an ambiguous alive
        record = t.load_json(c.build_report)
        self.assertEqual((record["heapProjection"]["ccFrameBytes"], record["heapProjection"]["aliveInstanceBytes"]),
                         (None, None))
        self.assertIn("sizeof(CCFrame) and the ALIVE instance size not recorded", " ".join(record["problems"]))
        t.write_json_evidence(c.build_report, {**record, "accepted": True, "problems": []})   # accepted by hand anyway
        with self.assertRaises(SystemExit) as caught:
            self.module.main(["--binary", "C"])
        self.assertIn("does not record sizeof(CCFrame) and the ALIVE instance size", str(caught.exception))
        self.assertFalse(c.manifest.exists())
        self.elf_sizes = [("cc_hmi_frame", CCFRAME_BYTES), ("alive", ALIVE_INSTANCE_BYTES)]   # outside the namespace
        self.assertEqual(self.build.main(["--binary", "C"]), 0)
        projection = t.load_json(c.build_report)["heapProjection"]
        self.assertEqual((projection["ccFrameSymbol"], projection["aliveInstanceBytes"]), ("cc_hmi_frame", ALIVE_INSTANCE_BYTES))
        self.write_elf = False
        c.built_elf.unlink()
        self.assertEqual(self.build.main(["--binary", "C"]), 1)
        self.assertIn("(firmware.elf is missing or unreadable)", " ".join(t.load_json(c.build_report)["problems"]))


@needs_tooling
class LadderCheckFlowTests(unittest.TestCase):
    """check_nanod_cc5.py --binary: the run checks that diag reports the binary just installed (the
    Cc54CheckFlowTests fixture, without running its cases again)."""
    setUp = Cc54CheckFlowTests.setUp
    raw54 = Cc54CheckFlowTests.raw54

    def test_the_expected_binary_must_be_the_reported_one(self):
        firmware = FakeFirmware54()
        firmware.lcd.update(lcdPeriodMs=33, artAsync=False, lcdFpsAnimMin=30)       # binary B on the knob
        report, _ = self.raw54(firmware, binary="B")
        self.assertEqual(report.data["binary"]["reported"], "B")
        self.assertNotIn("diag identifies binary B (lcdDma, lcdPeriodMs, artAsync; PRESENTATION_V5 12.6)",
                         report.data["failures"])
        self.assertEqual(report.data["sections"]["diag"]["binary"], "B")
        firmware = FakeFirmware54()                                                   # binary A on the knob
        report, _ = self.raw54(firmware, binary="C")
        self.assertIn("diag identifies binary C (lcdDma, lcdPeriodMs, artAsync; PRESENTATION_V5 12.6)",
                      report.data["failures"])
        self.assertEqual(report.data["binary"], {"expected": "C", "reported": "A",
                                                 "pipeline": {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True}})

    def test_the_binary_option(self):
        source = (WORK / "check_nanod_cc5.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--binary"', source)
        self.assertLess(source.index('expected, reported = getattr(args, "binary", None), t.lcd_binary(diag_before)'),
                        source.index("ctx = RawContext("))


@needs_tooling
class Cc54RunbookTests(unittest.TestCase):
    """firmware/BUILD-cc5.4.md read as text (never run): the ladder's build and package commands, the
    Stage 10 steps with the binary under test, the 12.6 step-down table, the dual-name companion guards,
    the cc5.4 -> cc5.3 rollback (scripted and manual) and the recorded build figures."""

    DOC = ROOT / "firmware" / "BUILD-cc5.4.md"
    PENDING = ("\\desktop-dist-v7\\DeskDial\\",)      # the Desk Dial bundle, built by the rename package
    NATIVE = ScriptStaticTests.NATIVE

    def setUp(self):
        if not self.DOC.is_file():
            self.skipTest("BUILD-cc5.4.md not present")
        self.text = self.DOC.read_text(encoding="utf-8")

    def window(self):
        return self.text[self.text.index("## Hardware window (Stage 10)"):self.text.index("## Rollback and abort")]

    def steps(self):
        window = self.window()
        starts = [m.start() for m in re.finditer(r"^### Step (\d+)\. ", window, re.M)]
        self.assertEqual(re.findall(r"^### Step (\d+)\. ", window, re.M), [str(n) for n in range(1, 11)])
        return [window[a:b] for a, b in zip(starts, starts[1:] + [len(window)])]

    @staticmethod
    def blocks(text):
        return [[line.strip() for line in block.strip().splitlines()] for block in re.findall(r"```powershell\n(.*?)```", text, re.S)]

    @machine_runbook
    def test_paths_interpreters_and_armed_exit_codes(self):
        ScriptStaticTests.assert_absolute_existing_paths(self, self.text, pending=self.PENDING)
        tail = self.text[self.text.index("## Hardware window (Stage 10)"):]
        blocks = self.blocks(tail)
        ScriptStaticTests.assert_exit_codes_are_armed(self, blocks, "BUILD-cc5.4.md")
        for lines in blocks:
            self.assertEqual((lines[0], lines[-1]), (". {", "}"))        # one unit: the first throw stops the block
            for name in ("flash", "app", "flashPython"):
                uses = [i for i, line in enumerate(lines) if re.search(rf"&\s+\${name}\b", line)]
                if uses:
                    self.assertTrue(any(line.startswith(f"${name} = 'C:\\") for line in lines[:uses[0]]), (name, lines[1]))
        self.assertNotIn("Stop-Process -", tail)
        self.assertIsNone(re.search(r"\.profiles\)?\.Count\b", self.text))

    def test_build_and_package_every_binary(self):
        build = self.text[self.text.index("## Build (never uploads)"):self.text.index("## Package")]
        package = self.text[self.text.index("## Package"):self.text.index("## Gate evidence")]
        for name in ("A", "B", "C"):
            self.assertIn("nanod-pio-venv\\Scripts\\python.exe' '<repo>\\tools"
                          f"\\build_nanod_cc5.py' --binary {name}", build)
            self.assertIn(".venv\\Scripts\\python.exe' '<repo>\\tools"
                          f"\\package_nanod_cc5.py' --binary {name}", package)
        for flags in LADDER_FLAGS.values():
            if flags:
                self.assertIn(f"`{' '.join(flags)}`", self.text)
        self.assertNotIn(" upload", " ".join(re.findall(r"```powershell\n(.*?)```", build, re.S)))

    def test_recorded_figures_are_the_packaged_binaries(self):
        """The status line and tables name each binary's packaged image; a rebuild must update them."""
        for v in t.CURRENT.variants():
            if not v.manifest.is_file():
                continue
            with self.subTest(v.binary):
                manifest = t.load_json(v.manifest)
                sha = manifest["image"]["sha256"]
                self.assertIn(f"`{sha}`", self.text.split("## What 1.0.0-cc5.4 changes")[0],
                              f"BUILD-cc5.4.md names another image for binary {v.binary}: update its status and tables")
                self.assertIn(f"{manifest['image']['bytes']:,} B", self.text)
                self.assertIn(f"`{t.sha256_file(v.manifest)}`", self.text)
                record = t.load_json(v.build_report)
                self.assertIn(f"{record['heapProjection']['heapMinFreeProjected']:,} B", self.text)

    @machine_runbook
    def test_stage_10_steps_follow_the_ladder(self):
        steps = self.steps()
        p = t.CURRENT
        flash, app = "$flash '", "$app '"
        expected = {3: (flash, "nanod_enter_bootloader_v2.py"), 4: (flash, "backup_nanod_cc5.py"),
                    5: (flash, "prepare_nanod_cc5_install.py"), 6: (flash, "install_nanod_cc5.py"),
                    2: (app, "device_inventory.py"), 10: (app, "finalize_nanod_cc5.py")}
        for number, (interpreter, script) in expected.items():
            self.assertIn(f"{interpreter}C:\\", steps[number - 1], number)
            self.assertIn(f"\\{script}'", steps[number - 1], number)
        self.assertIn("'1.0.0-cc5.3' -or $inventory.capabilities.presentation -ne 4", steps[1])
        self.assertIn(f"$backup.file -ne '{p.before_full.name}'", steps[3])
        self.assertIn(f"$backup.fromImageSha256 -ne '{p.from_image_sha256}'", steps[3])
        self.assertIn("diagnostics\\cc5.4-backup.json'", steps[3])
        self.assertIn("prepare_nanod_cc5_install.py' --before-inventory $beforeInventory --binary $name", steps[4])
        self.assertIn("foreach ($name in 'A', 'B', 'C')", steps[4])
        for v in p.variants():                     # step 5 prepared the 2026-09-26 window's ladder from the fresh backup
            if v.binary in LEGACY_BINARIES:
                self.assertIn(f"'{v.preparation.name}'", steps[4])
        self.assertIn(f"backups\\{p.rollback_app.name}'", steps[4])
        self.assertIn("install_nanod_cc5.py' --binary $binary", steps[5])
        for outcome in (p.restored_outcome, p.restored_unconfirmed_outcome):
            self.assertIn(f"`{outcome}`", steps[5])
        self.assertIn("check_nanod_cc5.py' --turn-seconds 60 --soak-minutes 20 --hid-check --binary $binary", steps[7])
        self.assertIn("\\check_nanod_cc5_lease.py' --observe-native-seconds", steps[7])
        self.assertIn("'1.0.0-cc5.4' -or $after.capabilities.presentation -ne 5", steps[7])
        self.assertEqual(steps[1].count("@($inventory.profiles.PSObject.Properties).Count -ne 10"), 1)
        self.assertEqual(steps[7].count("@($after.profiles.PSObject.Properties).Count -ne 10"), 1)
        finalize = load_script("finalize_nanod_cc5.py")
        for gate in p.gates:
            self.assertIn(f"`{gate}`", steps[7], gate)
        for case in finalize.REQUIRED_LEASE_CASES:
            self.assertIn(f"`{case}`", steps[7], case)
        blocks8 = self.blocks(steps[7])
        check = next(lines for lines in blocks8 if any("check_nanod_cc5.py'" in line for line in lines))
        at = next(i for i, line in enumerate(check) if "check_nanod_cc5.py'" in line)
        self.assertEqual(check[at - 2], "$env:NANOD_AUDIBLE_CUES = '1'")
        self.assertEqual(check[at + 1], "Remove-Item Env:NANOD_AUDIBLE_CUES -ErrorAction SilentlyContinue")
        self.assertIn("finalize_nanod_cc5.py' --binary $binary --companion-tests <suite-tests> --light-assertions 2174210",
                      steps[9])
        self.assertIn("--accept-unconfirmed-reset", steps[5] + steps[9])
        # Every step names its signals, and every throw inside a step is NO-GO or NOT RUN.
        for number, step in enumerate(steps, 1):
            for block in re.findall(r"```powershell\n(.*?)```", step, re.S):
                for message in re.findall(r"""throw ['"]([^'"]*)""", block):
                    self.assertRegex(message, r"^(?:NO-GO|NOT RUN): ", (number, message))
            self.assertRegex(step, r"(?m)^No-go|Go / no-go", number)

    def test_step_10_documents_the_recorded_waiver(self):
        """The 2026-09-26 sign-off for binary A: the exact waiver command, only the whitelisted gates, targets kept."""
        step = self.steps()[9]
        self.assertIn("finalize_nanod_cc5.py' --binary A --companion-tests <suite-tests> --light-assertions 2174210 "
                      "--waive-gate lcdTimings --waive-gate ledRenderTime --waive-gate jpegDecode --waive-gate ledFrameRate "
                      "--waive-gate limitPerPush --waive-gate limitEvents --waiver-note \"<text>\"", step)
        finalize = load_script("finalize_nanod_cc5.py")
        for gate in finalize.WAIVABLE_GATES:
            self.assertIn(f"`{gate}`", step)
        self.assertRegex(step, r"the targets are not\s+lowered")
        self.assertRegex(step, r"signed off in\s+this\s+window")
        self.assertEqual(step.count("--waive-gate"), 7)       # the option and the six gates of the binary A command
        # Both categories and their conditions: the performance misses, and the End stop timing with its proof.
        text = " ".join(step.split())
        performance = text[text.index("- Performance: "):text.index("- Operator timing: ")]
        operator = text[text.index("- Operator timing: "):text.index("Any other gate name")]
        for gate in finalize.PERFORMANCE_GATES:
            self.assertIn(f"`{gate}`", performance)
        for gate in finalize.OPERATOR_TIMING_GATES:
            self.assertIn(f"`{gate}`", operator)
        for fragment in ("an LED transmit failure", "(`ledMode`)", "LED load pass", "a stalled LED renderer (idle ledFps "
                         "below 29 or ledShowGapMsMax above 40 ms, ledFps below 22.5 under load"):
            self.assertIn(fragment, performance)
        limits = finalize.LED_WAIVER_LIMITS
        self.assertEqual((limits["idleLedFpsMin"], limits["idleLedShowGapMsMax"], limits["underLoadLedFpsMin"]),
                         (29, 40, 22.5))
        for fragment in ("`no lim +1 seen` / `no lim -1 seen`", "a lim +1 during the push phase at T_end",
                         "a lim -1 after the knob reported 0:00 (`reachedZero` and `limAtZero`), each in at least one run",
                         "Chatter is a firmware fault and always refuses", "closer than 100 ms",
                         "two lims of one direction in a run closer than 0.5 s",
                         "`limitEvents` also needs the stress+turn lims passed"):
            self.assertIn(fragment, operator)
        self.assertAlmostEqual(finalize.LIM_SPACING_MIN_S * 1000, 100)
        self.assertEqual(finalize.LIM_SAME_DIRECTION_MIN_S, 0.5)

    def test_every_guard_knows_both_companions(self):
        window = self.window()
        guards = [line.strip() for line in window.splitlines() if "Get-Process -Name" in line and "throw 'NOT RUN" in line]
        self.assertGreaterEqual(len(guards), 8)
        for line in guards:
            self.assertIn("-Name DeskDial, NanoDControlCenter", line)
        step1 = self.steps()[0]
        [quit_block] = [block for block in re.findall(r"```powershell\n(.*?)```", step1, re.S)]
        assert_quit_block_names_the_companions(self, quit_block)
        self.assertIn("foreach ($task in 'Desk Dial', 'NanoD Control Center')", quit_block)
        order = [step1.index(s) for s in ("Disable-ScheduledTask", "Get-Process -Name DeskDial, NanoDControlCenter",
                                          "VersionInfo.FileDescription -ne 'Desk Dial'", "'--smoke-test'",
                                          "$smoke.ExitCode -ne 0", "$report.pid -ne $smoke.Id")]
        self.assertEqual(order, sorted(order))
        self.assertIn("desktop-dist-v7\\DeskDial\\DeskDial.exe'", step1)
        self.assertIn("'DeskDial\\logs\\smoke-test.json'", step1)
        reenable = self.text[self.text.index("### Re-enable the companion"):self.text.index("## Deviations")]
        self.assertIn("if ($tasks.Count -ne 1) { throw", reenable)

    def test_step_down_table_is_12_6(self):
        section = self.text[self.text.index("### Step-down between binaries (PRESENTATION_V5 12.6)"):
                            self.text.index("### Step 9.")]
        rows = {tuple(cell.strip() for cell in row.strip("|").split("|")[:2]): row
                for row in re.findall(r"^\|(?: A | B | C ).*$", section, re.M)}
        self.assertIn("roll back A; set `$binary = 'C'` (B carries the same DMA driver)", rows[("A", "fails check 1 (panel image)")])
        self.assertIn("roll back A; set `$binary = 'B'`", rows[("A", "fails only checks 2-4")])
        self.assertIn("roll back B; set `$binary = 'C'`", rows[("B", "fails any check")])
        self.assertIn("roll back C to cc5.3 and stop", rows[("C", "fails any check")])
        for name in ("A", "B", "C"):
            self.assertIn(f"**ship {name}**", rows[(name, "passes 1-4")])
        flat = " ".join(section.split())
        for phrase in ("3. Run step 3 (enter the ROM bootloader).", "each flash with the user's go-ahead",
                       "4. Read the step-down base", "The full backup of step 4 is not repeated",
                       "5. Prepare the next binary from the step-down base", "6. Run step 6 (install `--binary $binary`)",
                       "the locked backup and `cc5.4-backup.json` are never replaced or rewritten"):
            self.assertIn(phrase, flat)
        go = " ".join(self.text[self.text.index("### Go-ahead first"):self.text.index("### Ports, interpreters")].split())
        for phrase in ("**each flash needs its own go-ahead**", "**stress+turn hard gate**", "**unattended soak gate**",
                       "**F24 test**", "one backup serves all three binaries",
                       "is reported and kept, never rewritten; so a step-down reads a step-down base"):
            self.assertIn(phrase, go)
        # Review TOOLBC-1: the rollback does not return every byte, so nothing may promise it does.
        self.assertNotIn("every rollback returns exactly those bytes", " ".join(self.text.split()))

    def test_the_step_down_reads_a_base_and_prepares_the_next_binary_from_it(self):
        """Review TOOLBC-1: after the failed binary's rollback, step 3, the step-down base read (backup --step-down,
        its record checked), the next binary prepared from it (--step-down-base, its record checked), then step 6;
        install exit 2 in a step-down sends the operator back to these two blocks once."""
        section = self.text[self.text.index("### Step-down between binaries (PRESENTATION_V5 12.6)"):
                            self.text.index("### Step 9.")]
        blocks = [lines for lines in self.blocks(section)]
        read = next(lines for lines in blocks if any("backup_nanod_cc5.py' --step-down" in line for line in lines))
        prep = next(lines for lines in blocks if any("--step-down-base" in line and "& $flash" in line for line in lines))
        self.assertLess(section.index("backup_nanod_cc5.py' --step-down"), section.index("--binary $binary --step-down-base"))
        self.assertIn("& $flash '<repo>\\tools\\prepare_nanod_cc5_install.py' "
                      "--before-inventory $beforeInventory --binary $binary --step-down-base", prep)
        p = t.CURRENT
        read_text, prep_text = "\n".join(read), "\n".join(prep)
        self.assertIn(f"diagnostics\\{p.step_down_report.name}'", read_text)
        for check in ("$stepDown.role -ne 'step-down base'", "$stepDown.criticalRegionsIdenticalToLockedBackup -ne $true",
                      "$stepDown.verifiedAgainstDevice -ne $true", "$stepDown.bytes -ne 4194304",
                      "$stepDown.fromImageAtApp0 -ne $true", f"$stepDown.lockedBackupFile -ne '{p.before_full.name}'"):
            self.assertIn(check, read_text)
        for check in ("$prep.baseKind -ne 'step-down base'", "$prep.baseFile -ne $stepDown.file",
                      "$prep.baseSha256 -ne $stepDown.sha256", f"$prep.beforeFile -ne '{p.before_full.name}'"):
            self.assertIn(check, prep_text)
        self.assertEqual(t.STEP_DOWN_ROLE, "step-down base")
        self.assertEqual(p.step_down_report.name, "cc5.4-step-down-base.json")
        self.assertNotIn("write_flash", read_text + prep_text)
        exit2 = next(row for row in self.steps()[5].splitlines() if row.startswith("| 2 | `STOPPED_BEFORE_WRITE`"))
        self.assertIn("run the step-down base and prepare blocks of the [step-down]", exit2)
        self.assertIn("A second exit 2: [Abort before any write]", exit2)
        self.assertIn("`backup_nanod_cc5.py --step-down`", " ".join(self.steps()[3].split()))   # step 4 names it
        deviations = self.text[self.text.index("## Deviations recorded by the tooling package (TOOL-bc)"):]
        self.assertIn("step-down base read (`backup_nanod_cc5.py --step-down`)", deviations)

    def test_build_logs_and_the_12_4_sizes_are_documented(self):
        """Review TOOLBC-2 / TOOLBC-3: the build section says how a log is kept and which sizes are recorded, and
        the recorded sizes are the ones the built ELFs give (when present)."""
        build = " ".join(self.text[self.text.index("## Build (never uploads)"):self.text.index("## Package")].split())
        for phrase in ("`nanod-cc5.4[-B|-C]-build.superseded-<UTC>.log`", "`logSha256`", "`heapProjection.ccFrameBytes`",
                       "`aliveInstanceBytes`", "| 1,124 B, 11,284 B | 1,124 B, 11,284 B | 1,124 B, 11,284 B |"):
            self.assertIn(phrase, build)
        for v in t.CURRENT.variants():
            if v.built_elf.is_file():
                record = t.v5_size_record(t.elf_symbols(v.built_elf))
                self.assertEqual((record["ccFrameBytes"], record["aliveInstanceBytes"]), (CCFRAME_BYTES, ALIVE_INSTANCE_BYTES),
                                 f"binary {v.binary}: update the size row of the build table")
        deviations = self.text[self.text.index("## Deviations recorded by the tooling package (TOOL-bc)"):]
        self.assertIn("review fix TOOLBC-2", deviations)

    def test_rollback_to_cc5_3_scripted_and_manual(self):
        rollback = self.text[self.text.index("### Firmware rollback, cc5.4 -> cc5.3"):self.text.index("### Firmware, manual esptool fallback")]
        scripted, records = self.blocks(rollback)
        first = next(i for i, line in enumerate(scripted) if "& $flashPython" in line)
        self.assertEqual({f for line in scripted[:first] for f in re.findall(r"\$(\w+Verified) = \$false", line)},
                         {"layoutVerified", "app0Verified", "rollbackVerified"})
        self.assertIn("rollback_nanod_cc5.py' --to cc5.3 --binary $binary", "\n".join(scripted))
        self.assertIn("rollback_nanod_cc5.py' --to cc5.3 --binary $binary --records-only", "\n".join(records))
        for code in ("0", "1", "2", "4", "5", "6", "-1"):
            self.assertRegex(rollback, rf"\n\| {code} \| ")
        manual = self.text[self.text.index("### Firmware, manual esptool fallback"):self.text.index("### After the rollback")]
        blocks = self.blocks(manual)
        self.assertEqual(len(blocks), 4)
        for lines in blocks:
            for i, line in enumerate(lines):
                if "-m esptool" in line or "rollback_nanod_cc5.py" in line or line.startswith("'@ | & $flashPython"):
                    self.assertRegex(lines[i + 1], r"^if \(\$LASTEXITCODE -ne 0\) \{ throw ", line)
        checks, write, regions, reset = ("\n".join(lines) for lines in blocks)
        p = t.CURRENT
        self.assertIn(f"backups\\{p.before_full.name}'", checks)
        self.assertIn(f"backups\\{p.rollback_app.name}'", checks)
        self.assertIn(r"backups\cc5.4-manual-rollback-' + (Get-Date)", checks)
        self.assertIn("'cc5.4-preparation.json' } else { \"cc5.4-$binary-preparation.json\" }", checks)
        code = "\n".join(re.findall(r"```powershell\n(.*?)```", self.text, re.S))
        for history in ("nanod-cc5.2-before-cc5.3", "nanod-cc4-before-cc5", "cc5.3-preparation.json", "cc5-preparation.json"):
            self.assertNotIn(history, code)
        self.assertNotRegex(code, r"rollback_nanod_cc5\.py'(?! --to cc5\.3 --binary \$binary)")
        self.assertEqual(write.count("--baud 460800 --before no_reset --after no_reset_stub write_flash --flash_mode keep "
                                     "--flash_freq keep --flash_size keep 0x10000 $rollbackApp"), 1)
        self.assertNotIn("write_flash", checks + regions + reset)
        self.assertEqual([b for b in (checks, write, regions, reset) if "hard_reset" in b], [reset])
        self.assertTrue(blocks[1][1].startswith("if (-not $layoutVerified) { throw"))
        self.assertTrue(blocks[2][1].startswith("if (-not $app0Verified) { throw"))
        self.assertTrue(blocks[3][1].startswith("if (-not $rollbackVerified) { throw"))
        verify = next(i for i, line in enumerate(blocks[3]) if "verify_flash 0x10000 $rollbackApp" in line)
        hard_reset = next(i for i, line in enumerate(blocks[3]) if "--after hard_reset read_mac" in line)
        self.assertLess(verify, hard_reset)
        version = next(i for i, line in enumerate(blocks[0]) if "import esptool; print(esptool.__version__)" in line)
        first_other = next(i for i, line in enumerate(blocks[0]) if "-m esptool" in line or "$romPort" in line
                           or "Get-FileHash" in line or "@'" == line)
        self.assertLess(version, first_other)

    def test_read_only_resets_verify_app0_first(self):
        for heading, end, image in (("### Abort before any write", "### Leave the bootloader without writing",
                                     "nanod-control-center-1.0.0-cc5.3.bin'"),
                                    ("### Leave the bootloader without writing", "### Firmware rollback, cc5.4 -> cc5.3",
                                     "$image")):
            with self.subTest(heading):
                [lines] = self.blocks(self.text[self.text.index(heading):self.text.index(end)])
                verify = next(i for i, line in enumerate(lines) if "verify_flash 0x10000" in line)
                hard_reset = next(i for i, line in enumerate(lines) if "--after hard_reset read_mac" in line)
                self.assertLess(verify, hard_reset)
                self.assertTrue(lines[verify].endswith(image), lines[verify])
                self.assertRegex(lines[verify + 1], r"^if \(\$LASTEXITCODE -ne 0\) \{ throw '.*Nothing was reset\. Do NOT reset")
                self.assertNotIn("write_flash", "\n".join(lines))
                self.assertEqual(sum("hard_reset" in line for line in lines), 1)

    def test_desktop_steps_migrate_by_hash_and_roll_back_to_v6(self):
        step9 = self.steps()[8]
        order = [step9.index(s) for s in ("-Bundle desktop-dist-v7 -Mirror -DryRun", "Copy-Item -LiteralPath $programs",
                                          "$dataHashesBefore = $hashes", "-Bundle desktop-dist-v7 -Mirror\n",
                                          "Compare-Object $dataHashesBefore $oldAfter", "Compare-Object $dataHashesBefore $newAfter",
                                          "Enable-ScheduledTask -TaskName 'Desk Dial'", "Verify-NativeDesktop.ps1'")]
        self.assertEqual(order, sorted(order))
        self.assertIn("-ne '2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F') { throw 'NO-GO: the "
                      "installed exe is not the recorded v6 companion' }", step9)
        for name in ("data\\credentials.bin", "data\\settings.json", "queue-recovery.bin", "shuffle-restore.bin"):
            self.assertIn(f"'{name}'", step9)
        self.assertNotRegex(step9, r"Get-Content[^\n]*(?:\$oldHome|\$newHome|\$dataDir)")   # hashes only, never contents
        self.assertIn("$status.firmwarePresentation -ne 5", step9)
        self.assertIn("if (Get-ScheduledTask -TaskName 'NanoD Control Center' -ErrorAction SilentlyContinue) { throw", step9)
        rollback = self.text[self.text.index("### Desktop rollback, v7 -> v6"):self.text.index("### Re-enable the companion")]
        self.assertIn("Install-Desktop.ps1' -Bundle desktop-dist-v6 -Mirror", rollback)
        self.assertEqual((t.CURRENT.desktop_bundle, t.CURRENT.desktop_rollback_bundle), ("desktop-dist-v7", "desktop-dist-v6"))

    def test_the_desktop_rollback_names_no_installer_option_that_does_not_exist(self):
        """Review finding RN-R2: nothing is carried back to v6, and the runbook never points at an installer
        option Install-Desktop.ps1 does not declare (the rename plan's -CarryDataBack, RN-6, was not built)."""
        install = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        declared = set(re.findall(r"\[(?:string|switch)\]\$(\w+)", install[:install.index("$ErrorActionPreference")]))
        self.assertEqual(declared, {"Bundle", "Mirror", "DryRun"})
        rollback = self.text[self.text.index("### Desktop rollback, v7 -> v6"):self.text.index("### Re-enable the companion")]
        flat = " ".join(rollback.split())
        self.assertNotIn("unless the installer is asked", flat)
        self.assertIn("Nothing is carried back, and the installer has no option for it", flat)
        self.assertIn("stay only in `%LOCALAPPDATA%\\DeskDial\\`", flat)
        self.assertIn("copy those files back into the old home by hand, together with the user", flat)
        # Every option passed to the installer anywhere in this runbook exists.
        for options in re.findall(r"Install-Desktop\.ps1'((?: -\w+(?: [\w.-]+)?)+)", self.text):
            for option in re.findall(r" -(\w+)", options):
                self.assertIn(option, declared, options)
        # The installer's own header and DESKTOP.md say the same, and name a carry-back option only once it exists.
        desktop = (ROOT / "DESKTOP.md").read_text(encoding="utf-8")
        self.assertIn("not carried back (no option does it", install)
        self.assertIn("not carried back (the installer has no option", " ".join(desktop.split()))
        for name, text in (("BUILD-cc5.4.md", self.text), ("Install-Desktop.ps1", install), ("DESKTOP.md", desktop)):
            if "CarryDataBack" in text and "CarryDataBack" not in declared:
                self.assertIn("was not built", " ".join(text.split()), name)

    def test_a_desktop_rollback_from_cc5_4_follows_the_firmware_rollback(self):
        """Review finding RN-R3: cc5.4 names Desk Dial on the knob (rename plan 14.2 step 3), so every step-9 NO-GO
        rolls the firmware back to cc5.3 first and the desktop to v6 second, and the desktop rollback block
        refuses until the binary's rollback record is newer than its install record and verified cc5.3."""
        step9 = self.steps()[8]
        nogo = [line for line in step9.split("\n\n") if line.startswith("No-go (9")]
        self.assertEqual(len(nogo), 2, nogo)
        for paragraph in nogo:
            with self.subTest(paragraph[:12]):
                firmware = paragraph.index("(#firmware-rollback-cc54---cc53)")
                self.assertLess(firmware, paragraph.index("(#desktop-rollback-v7---v6)"))
        rollback = self.text[self.text.index("### Desktop rollback, v7 -> v6"):self.text.index("### Re-enable the companion")]
        flat = " ".join(rollback.split())
        self.assertIn("Use this for a NO-GO in step 9, and only once the knob is back on cc5.3.", flat)
        self.assertIn("rename-desk-dial.md 14.2 step 3", flat)
        order = [rollback.index(s) for s in ("1. Quit the companion", "2. The [firmware rollback](#firmware-rollback-cc54---cc53)",
                                             "[after the rollback](#after-the-rollback)", "3. This desktop rollback.",
                                             "4. [Re-enable the companion](#re-enable-the-companion)")]
        self.assertEqual(order, sorted(order))
        [lines] = self.blocks(rollback)
        block = "\n".join(lines)
        install = next(i for i, line in enumerate(lines) if "Install-Desktop.ps1' -Bundle desktop-dist-v6 -Mirror" in line)
        guards = [i for i, line in enumerate(lines) if line.startswith("if (") and "throw 'NOT RUN: " in line]
        self.assertGreaterEqual(len(guards), 5)
        self.assertTrue(all(i < install for i in guards), "every guard runs before the installer")
        self.assertIn("if ($binary -notin 'A', 'B', 'C', 'D', 'E') { throw 'NOT RUN: ", block)
        self.assertIn("$prefix = if ($binary -eq 'A') { 'cc5.4' } else { \"cc5.4-$binary\" }", block)
        for variant in t.CURRENT.variants():     # the names the block builds are the tooling's records
            prefix = "cc5.4" if variant.binary == "A" else f"cc5.4-{variant.binary}"
            self.assertEqual((variant.flash_checks.name, variant.rollback_report.name),
                             (f"{prefix}-flash-checks.json", f"{prefix}-rollback.json"))
        self.assertIn('"$diagnostics\\$prefix-flash-checks.json"', block)
        self.assertIn('"$diagnostics\\$prefix-rollback.json"', block)
        self.assertIn("$rollbackRecord.LastWriteTimeUtc -le $installRecord.LastWriteTimeUtc) { throw 'NOT RUN: the knob "
                      "still runs cc5.4, which names Desk Dial; run the firmware rollback to cc5.3 first", block)
        accepted = re.search(r"\$rollbackOutcome -notin ((?:'\w+'(?:, )?)+)\) \{ throw", block).group(1)
        rollback_script = load_script("rollback_nanod_cc5.py")
        self.assertEqual(tuple(re.findall(r"'(\w+)'", accepted)), rollback_script.RECORD_OUTCOMES)
        self.assertNotRegex(block, r"Get-Content[^\n]*(?:DeskDial|NanoDControlCenter|\$oldHome|\$newHome)")
        # The firmware rollback, After the rollback, the release summary, the go-ahead and K1 16.8 E-r agree.
        firmware = " ".join(self.text[self.text.index("### Firmware rollback, cc5.4 -> cc5.3"):
                                      self.text.index("```powershell", self.text.index("### Firmware rollback, cc5.4 -> cc5.3"))].split())
        self.assertIn("after a NO-GO in step 9 before the [desktop rollback](#desktop-rollback-v7---v6)", firmware)
        after = " ".join(self.text[self.text.index("### After the rollback"):self.text.index("### Desktop rollback, v7 -> v6")].split())
        self.assertIn("after a NO-GO in step 9, go on with the [desktop rollback](#desktop-rollback-v7---v6)", after)
        summary = " ".join(self.text[self.text.index("## What 1.0.0-cc5.4 changes"):self.text.index("## The build ladder")].split())
        self.assertIn("The window still never ends with cc5.4 next to desktop v6", summary)
        go = " ".join(self.text[self.text.index("### Go-ahead first"):self.text.index("### Ports, interpreters")].split())
        self.assertIn("A NO-GO in step 9 rolls back both halves, the firmware to cc5.3 first and then the desktop to v6", go)
        k1 = (WORK.parent / "firmware" / "PRESENTATION_V5.md")
        if k1.is_file():
            [row] = [line for line in k1.read_text(encoding="utf-8").splitlines() if line.startswith("| E-r |")]
            self.assertIn("a desktop rollback to v6 (still NanoD Control Center) from a cc5.4 knob always goes with the "
                          "firmware rollback to cc5.3, firmware first", row)

    def test_anchors_and_deviations(self):
        slugs = {re.sub(r"[^a-z0-9 _-]", "", heading.lower()).replace(" ", "-")
                 for heading in re.findall(r"^#{2,3} (.+)$", self.text, re.M)}
        for anchor in re.findall(r"\]\(#([^)]+)\)", self.text):
            self.assertIn(anchor, slugs)
        deviations = self.text[self.text.index("## Deviations recorded by the tooling package (TOOL-bc)"):]
        self.assertEqual(re.findall(r"^\| (TB-D\d+) \|", deviations, re.M), [f"TB-D{n}" for n in range(1, 13)])
        self.assertIn("`LCD_DIAG_FIELDS + LCD_FIX_DIAG_FIELDS`", deviations)     # TB-D12 (the integrator's)
        # TB-D9 (review TOOLBC-1): the step-down's coredumpBlank exception is stated where 8b is read.
        section = " ".join(self.text[self.text.index("### Step-down between binaries (PRESENTATION_V5 12.6)"):
                                     self.text.index("### Step 9.")].split())
        self.assertIn("accepts exactly that dump in the `coredumpBlank` gate", section)
        self.assertIn("recorded as `coredumpInherited`", section)
        for reason in sorted(t.CRASH_RESET_REASONS):
            self.assertIn(f"`{reason}`", section)


# ---------------------------------------------------------------------------
# The fix binaries D and E (2026-09-26, after binary A's rollback): A's LCD stayed dark because tft.initDMA() runs
# with TFT_MISO == TFT_MOSI == GPIO4 on the S3 and leaves the pin on FSPIQ_OUT, and the LEDs flickered (the dither on
# at rest). D is A's pipeline + the fixes, E is C's; A, B and C are retired.

@needs_tooling
class FixBinaryProfileTests(unittest.TestCase):
    """D and E: their names, flags, pipelines and targets; A, B and C retired, refused by every script that builds,
    packages, prepares, installs, finalizes or looks, and still taken by rollback and check."""

    def test_d_and_e_are_the_active_binaries(self):
        self.assertEqual((t.ACTIVE_BINARIES, t.binary_choices(), t.binary_choices(t.PROFILES["cc5.3"])),
                         (("D", "E"), ("D", "E"), ()))
        self.assertEqual(set(t.RETIRED_BINARIES), set(LEGACY_BINARIES))
        self.assertEqual(set(t.PIPELINE_BINARIES), set(t.ACTIVE_BINARIES) | set(t.RETIRED_BINARIES))
        for words in ("rolled back 2026-09-26", "initDMA", "FSPIQ_OUT (102)", "Superseded by D"):
            self.assertIn(words, t.RETIRED_BINARIES["A"])
        self.assertIn("never flashed", t.RETIRED_BINARIES["B"])
        self.assertIn("superseded by E", t.RETIRED_BINARIES["C"])
        self.assertEqual(t.BINARY_BUILD_NUMBERS, {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5})
        for name in t.PIPELINE_BINARIES:
            v = t.CURRENT.binary_profile(name)
            self.assertEqual((v.build_number, t.binary_build_number(name)), ({"D": 4, "E": 5}.get(name),) * 2, name)
        self.assertIsNone(t.binary_build_number(None))
        self.assertIsNone(t.PROFILES["cc5.3"].build_number)

    def test_names_folders_flags_pipelines_and_targets(self):
        for name, parent in (("D", "A"), ("E", "C")):
            with self.subTest(name):
                v = t.CURRENT.binary_profile(name)
                self.assertEqual(t.BINARY_PARENTS[name], parent)
                self.assertEqual((v.version, v.label, v.pipeline, t.LCD_FPS_TARGETS[name]),
                                 ("1.0.0-cc5.4", f"cc5.4 binary {name}", t.LCD_BINARIES[parent], t.LCD_FPS_TARGETS[parent]))
                self.assertEqual(v.build_flags, LADDER_FLAGS[name])
                self.assertEqual(tuple(f for f in v.build_flags if not f.startswith("-DCC_BUILD_BINARY=")),
                                 LADDER_FLAGS[parent])                       # the parent's pipeline flags, plus the id
                self.assertEqual(v.build_dir, t.FIRMWARE_SOURCE / ".pio" / f"build-cc5.4-{name}")
                self.assertEqual((v.image.name, v.manifest.name, v.build_report.name, v.look_checks.name),
                                 (f"nanod-control-center-1.0.0-cc5.4-{name}.bin", f"manifest-1.0.0-cc5.4-{name}.json",
                                  f"cc5.4-{name}-build.json", f"cc5.4-{name}-look-checks.json"))
                for attr in ("before_full", "rollback_app", "backup_report", "step_down_report", "device_checks",
                             "lease_checks", "from_record"):
                    self.assertEqual(getattr(v, attr), getattr(t.CURRENT, attr), attr)
                # The manifest pins the stage9b / stage9c gate runs and the ALIVE floor report through the release's
                # patterns.
                for evidence in ("cc5.4-stage9b-firmware-gates.log", "cc5.4-stage9b-companion-suite.json",
                                 "cc5.4-stage9c-firmware-gates.log", "cc5.4-stage9c-lcd-mosi-elf.json",
                                 "cc5.4-alive-floor-report.json", f"cc5.4-{name}-build.json"):
                    self.assertTrue(any(fnmatch.fnmatch(evidence, pattern) for pattern in v.gate_patterns), evidence)
                self.assertIn("fixes", t.BINARY_ROLES[name])
                self.assertIn("MOSI re-attach", t.BINARY_FIXES[name])
        self.assertIn("the DMA driver (R3)", t.BINARY_STEP_DOWN["E"])
        self.assertNotIn("D", t.BINARY_STEP_DOWN)                          # D is the first of the fix binaries

    def argparse_exit(self, module, argv):
        """(exit code, stdout, stderr) of module.main(argv) when argparse ends it; the run must stop there."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(t, "console_utf8", mock.Mock(side_effect=AssertionError("ran past argparse"))), \
                mock.patch.object(t, "list_ports", mock.Mock(side_effect=AssertionError("no port enumeration"))), \
                self.assertRaises(SystemExit) as caught:
            module.main(list(argv))
        return caught.exception.code, out.getvalue(), err.getvalue()

    def test_retired_binaries_are_refused_by_every_writing_script(self):
        for script, argv in (("build_nanod_cc5.py", ()), ("package_nanod_cc5.py", ()),
                             ("prepare_nanod_cc5_install.py", ("--before-inventory", "inventory.json")),
                             ("install_nanod_cc5.py", ()), ("finalize_nanod_cc5.py", ()),
                             ("check_nanod_cc5_look.py", ())):
            module = load_script(script)
            for name in t.RETIRED_BINARIES:
                with self.subTest(script=script, binary=name):
                    code, _, err = self.argparse_exit(module, (*argv, "--binary", name))
                    self.assertEqual(code, 2)
                    self.assertIn(f"invalid choice: '{name}'", err)
            with self.subTest(script=script, binary="help"):
                code, out, _ = self.argparse_exit(module, (*argv, "--binary", "E", "--help"))
                self.assertEqual(code, 0)
                self.assertIn("{D,E}", out)

    def test_rollback_and_check_take_every_binary(self):
        for script, argv in (("rollback_nanod_cc5.py", ("--to", "cc5.3")), ("check_nanod_cc5.py", ())):
            module = load_script(script)
            for name in t.PIPELINE_BINARIES:                 # --binary is validated before --help ends the run
                with self.subTest(script=script, binary=name):
                    self.assertEqual(self.argparse_exit(module, (*argv, "--binary", name, "--help"))[0], 0)
            self.assertEqual(self.argparse_exit(module, (*argv, "--binary", "F", "--help"))[0], 2)


@needs_tooling
class LcdDataLineTests(unittest.TestCase):
    """The LCD data-line gate (build-only) and diag lcdMosiSig / build (on the knob)."""
    INI = ("; PlatformIO Project Configuration File\n[platformio]\ndefault_envs = nanofoc_d\n\n[env:nanofoc_d]\n"
           "platform = espressif32@6.5.0\nbuild_flags = \n\t-DNANO_FIRMWARE_VERSION=\\\"1.0.0-cc5.4\\\"\n\t-DTFT_MOSI=4\n"
           "\t-DTFT_MISO=-1\n\t-DTFT_SCLK=3\n\t-DUSB_PRODUCT=\"\\\"Nano_D++ (Beta)\\\"\"\n\t; -DTFT_MISO=13\n\n"
           "monitor_speed = 115200\n\n[env:other]\nbuild_flags = -DTFT_MOSI=9\n")

    def test_the_s3_rule_puts_miso_on_mosi(self):
        config = t.tft_spi_config(self.INI)
        self.assertEqual((config["mosi"], config["miso"], config["effectiveMiso"], config["sclk"], config["port"],
                          config["misoEqualsMosi"], config["problems"]), (4, -1, 4, 3, "FSPI (SPI2_HOST)", True, []))
        self.assertEqual(t.tft_spi_config(self.INI.replace("\t-DTFT_MISO=-1\n", ""))["effectiveMiso"], 4)   # unset: the same
        separate = t.tft_spi_config(self.INI, ("-DTFT_MISO=13",))           # PLATFORMIO_BUILD_FLAGS come last and win
        self.assertEqual((separate["effectiveMiso"], separate["misoEqualsMosi"]), (13, False))
        self.assertIn("the encoder owns HSPI", t.tft_spi_config(self.INI, ("-DUSE_HSPI_PORT",))["problems"][0])
        missing = t.tft_spi_config("[env:nanofoc_d]\nbuild_flags = -DTFT_SCLK=3\n")
        self.assertIn("TFT_MOSI is not set", missing["problems"][0])
        self.assertFalse(missing["misoEqualsMosi"])
        self.assertIsNone(t.tft_spi_config("[env:other]\nbuild_flags = -DTFT_MOSI=4\n")["mosi"])   # another env's flags
        self.assertIn("-DTFT_MOSI=4", t.platformio_build_flags(self.INI))
        self.assertNotIn("-DTFT_MOSI=9", t.platformio_build_flags(self.INI))
        self.assertNotIn("-DTFT_MISO=13", t.platformio_build_flags(self.INI))  # a commented-out line

    def test_the_real_platformio_ini_is_the_defect_configuration(self):
        ini = t.FIRMWARE_SOURCE / "platformio.ini"
        if not ini.is_file():
            self.skipTest("firmware checkout not present")
        config = t.tft_spi_config(ini.read_text(encoding="utf-8"), t.CURRENT.binary_profile("D").build_flags)
        self.assertEqual((config["mosi"], config["effectiveMiso"], config["misoEqualsMosi"], config["problems"]),
                         (4, 4, True, []))

    GOOD = ["begin", "initDMA", "reattach", "startWrite"]

    def test_a_dma_build_must_link_the_reattach(self):
        config = t.tft_spi_config(self.INI)
        for binary, names, passed in (("D", {"setup", t.LCD_MOSI_REATTACH_SYMBOL}, True), ("D", {"setup"}, False),
                                      ("D", {"_Z20cc_lcd_mosi_reattachv"}, True), ("E", {"setup"}, True),
                                      ("A", {"setup", t.R3_ELF_SYMBOL}, False), ("B", {"setup"}, False),
                                      ("C", set(), True)):
            with self.subTest(binary=binary, names=sorted(names)):
                dma = t.LCD_BINARIES[binary]["lcdDma"]
                order = (self.GOOD if t.LCD_MOSI_REATTACH_SYMBOL in " ".join(names) else ["begin", "initDMA", "startWrite"]) \
                    if dma else ["begin"]
                gate = t.lcd_mosi_gate(config, names, binary, order)
                self.assertEqual((gate["passed"], gate["reattachRequired"], gate["dma"], gate["expectedMosiSignal"]),
                                 (passed, t.LCD_BINARIES[binary]["lcdDma"], t.LCD_BINARIES[binary]["lcdDma"], 103))
                self.assertEqual(gate["pins"], {"mosi": 4, "miso": -1, "effectiveMiso": 4, "sclk": 3})
        failed = t.lcd_mosi_gate_problems(config, {"setup"}, "D", ["begin", "initDMA", "startWrite"])
        self.assertEqual(len(failed), 1)                                          # the missing symbol, reported once
        for words in ("TFT_MISO = TFT_MOSI = GPIO4", "FSPIQ_OUT (102)", "binary A's dark LCD", "cc_lcd_mosi_reattach",
                      "do not flash it"):
            self.assertIn(words, failed[0])
        self.assertIn("firmware.elf is missing", t.lcd_mosi_gate_problems(config, None, "D")[0])
        self.assertEqual(t.lcd_mosi_gate_problems(config, None, "E"), [])         # no DMA: nothing to re-attach
        separate = t.tft_spi_config(self.INI, ("-DTFT_MISO=13",))
        self.assertTrue(t.lcd_mosi_gate(separate, {"setup"}, "D", ["begin", "initDMA", "startWrite"])["passed"])
        self.assertTrue(t.lcd_mosi_gate(separate, {"setup"}, "D")["passed"])      # MISO on its own pin: order not needed
        hspi = t.tft_spi_config(self.INI, ("-DUSE_HSPI_PORT",))
        self.assertFalse(t.lcd_mosi_gate(hspi, {t.LCD_MOSI_REATTACH_SYMBOL}, "E", ["begin"])["passed"])

    def test_the_reattach_must_directly_follow_init_dma(self):
        """Linking the re-attach is not enough: LcdThread::run() must call it right after every initDMA and before
        startWrite; an order that was not read fails a build that needs it; a no-DMA binary never calls initDMA."""
        config, names = t.tft_spi_config(self.INI), {"setup", t.LCD_MOSI_REATTACH_SYMBOL}
        self.assertEqual(t.lcd_mosi_gate_problems(config, names, "D", self.GOOD), [])
        for order, words in ((["begin", "reattach", "initDMA", "startWrite"], "is not directly followed by"),
                             (["begin", "initDMA", "startWrite", "reattach"], "is not directly followed by"),
                             (["begin", "initDMA", "reattach"], "is not directly followed by"),
                             (["begin", "initDMA", "reattach", "startWrite", "initDMA", "startWrite"],
                              "is not directly followed by"),
                             (["begin", "reattach", "startWrite"], "shows no direct call to TFT_eSPI::initDMA"),
                             ([], "shows no direct call to TFT_eSPI::initDMA (calls: none)")):
            with self.subTest(order=order):
                problems = t.lcd_mosi_gate_problems(config, names, "D", order)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(words, problems[0])
        gate = t.lcd_mosi_gate(config, names, "D", None, "OSError: no objdump")
        self.assertFalse(gate["passed"])
        self.assertIn("was not read (OSError: no objdump), so the re-attach right after tft.initDMA() cannot be "
                      "confirmed", gate["problems"][0])
        self.assertEqual((gate["callOrder"], gate["callOrderError"], gate["callOrderRule"]),
                         (None, "OSError: no objdump", t.LCD_CALL_ORDER_RULE))
        self.assertIn("the build flags did not take effect",
                      t.lcd_mosi_gate_problems(config, {"setup"}, "E", ["begin", "initDMA", "startWrite"])[0])
        self.assertEqual(t.lcd_call_order_problems(["begin", "initDMA", "startWrite"], "D", False), [])

    def test_lcd_run_call_order_reads_one_function(self):
        """The call order comes from a read-only disassembly of LcdThread::run()'s own address range; direct calls
        are matched against the symbol table (mangled TFT_eSPI methods by prefix, the extern "C" re-attach by name)."""
        with tempfile.TemporaryDirectory() as folder:
            elf = Path(folder) / "firmware.elf"
            elf.write_bytes(fake_elf([(t.LCD_RUN_SYMBOL, 0x200, 0x42052B3C), ("_ZN8TFT_eSPI5beginEh", 8, 0x42005010),
                                      ("_ZN8TFT_eSPI7initDMAEb", 8, 0x42004624), (t.LCD_MOSI_REATTACH_SYMBOL, 8, 0x4205294C),
                                      ("_ZN8TFT_eSPI10startWriteEv", 8, 0x42005404),
                                      ("_ZN8TFT_eSPI11setRotationEh", 8, 0x42005500)]))
            listing = ("\n42052b3c <_ZN9LcdThread3runEv>:\n"
                       "42052b3f:\t000025        \tcall8\t42005010 <_ZN8TFT_eSPI5beginEh>\n"
                       "42052b45:\t000025        \tcall8\t42005500 <_ZN8TFT_eSPI11setRotationEh>\n"
                       "42052b50:\t000025        \tcall8\t42004624 <_ZN8TFT_eSPI7initDMAEb>\n"
                       "42052b53:\t000025        \tcall8\t4205294c <cc_lcd_mosi_reattach>\n"
                       "42052b56:\t000825        \tcallx8\ta8\n"
                       "42052b59:\t000025        \tcall8\t42005404 <_ZN8TFT_eSPI10startWriteEv>\n")
            seen = []

            def run(command, **kwargs):
                seen.append((command, kwargs))
                return SimpleNamespace(stdout=listing, returncode=0)
            order = t.lcd_run_call_order(elf, objdump="objdump.exe", run=run)
            self.assertEqual(order, self.GOOD)
            [(command, kwargs)] = seen
            self.assertEqual(command, ["objdump.exe", "-d", "--start-address=0x42052b3c", "--stop-address=0x42052d3c",
                                       str(elf)])
            self.assertTrue(kwargs["check"])
            elf.write_bytes(fake_elf(["setup"]))
            with self.assertRaises(ValueError):
                t.lcd_run_call_order(elf, objdump="objdump.exe", run=run)
        self.assertTrue(issubclass(ValueError, t.CALL_ORDER_ERRORS) and issubclass(OSError, t.CALL_ORDER_ERRORS))

    def test_the_real_elfs_call_order(self):
        """Read only, when the builds and the toolchain's objdump are present: A's LcdThread::run() calls begin,
        initDMA, startWrite (no re-attach: the dark LCD) and fails the gate; D's calls the re-attach right after
        initDMA; E's calls begin only."""
        if not t.XTENSA_OBJDUMP.is_file():
            self.skipTest("the xtensa objdump is not installed")
        ini = t.FIRMWARE_SOURCE / "platformio.ini"
        expected = {"A": ["begin", "initDMA", "startWrite"], "D": self.GOOD, "E": ["begin"]}
        checked = 0
        for binary, order in expected.items():
            v = t.CURRENT.binary_profile(binary)
            elf = v.built_image.with_name("firmware.elf")
            if not (elf.is_file() and ini.is_file()):
                continue
            with self.subTest(binary):
                got = t.lcd_run_call_order(elf)
                self.assertEqual(got, order)
                gate = t.lcd_mosi_gate(t.tft_spi_config(ini.read_text(encoding="utf-8"), v.build_flags),
                                       t.elf_symbol_names(elf), binary, got)
                self.assertEqual(gate["passed"], binary != "A", gate["problems"])
                checked += 1
        if not checked:
            self.skipTest("no built firmware.elf of A, D or E")

    def test_the_source_calls_the_reattach_right_after_init_dma(self):
        """lcd_thread.cpp: in LcdThread::run(), `tft.initDMA();` is followed directly by `cc_lcd_mosi_reattach();` and
        then `tft.startWrite();` (comments aside), and the re-attach is called nowhere else."""
        source = t.FIRMWARE_SOURCE / "src" / "lcd_thread.cpp"
        if not source.is_file():
            self.skipTest("firmware checkout not present")
        text = source.read_text(encoding="utf-8")
        run = text[text.index("void LcdThread::run()"):]
        statements = [line.split("//")[0].strip() for line in run.splitlines()]
        statements = [line for line in statements if line]
        at = statements.index("tft.initDMA();")
        self.assertEqual(statements[at:at + 3], ["tft.initDMA();", "cc_lcd_mosi_reattach();", "tft.startWrite();"])
        code = "\n".join(line.split("//")[0] for line in text.splitlines())
        self.assertEqual(code.count("cc_lcd_mosi_reattach();"), 1)
        self.assertEqual(code.count("tft.initDMA("), 1)

    def test_binary_a_real_elf_fails_the_gate(self):
        """Read only: while .pio/build/nanofoc_d holds binary A's accepted image, its ELF fails the gate (A's LCD)."""
        elf, ini = t.BUILT_IMAGE.with_name("firmware.elf"), t.FIRMWARE_SOURCE / "platformio.ini"
        if not (elf.is_file() and t.BUILT_IMAGE.is_file() and t.CURRENT.build_report.is_file() and ini.is_file()):
            self.skipTest("binary A's build is not present")
        if t.load_json(t.CURRENT.build_report).get("sha256") != t.sha256_file(t.BUILT_IMAGE):
            self.skipTest(".pio/build/nanofoc_d no longer holds binary A's accepted image")
        gate = t.lcd_mosi_gate(t.tft_spi_config(ini.read_text(encoding="utf-8")), t.elf_symbol_names(elf), "A")
        self.assertEqual((gate["reattachRequired"], gate["reattachLinked"], gate["passed"]), (True, False, False))

    def test_lcd_mosi_problems(self):
        self.assertEqual(t.lcd_mosi_problems({"lcdMosiSig": 103}), [])
        self.assertIn("binary A's defect", t.lcd_mosi_problems({"lcdMosiSig": 102})[0])
        self.assertIn("expected 103 (FSPID)", t.lcd_mosi_problems({"lcdMosiSig": 7})[0])
        self.assertIn("lacks integer lcdMosiSig", t.lcd_mosi_problems({})[0])
        self.assertIn("lacks integer lcdMosiSig", t.lcd_mosi_problems({"lcdMosiSig": "103"})[0])
        self.assertIn("lacks integer lcdMosiSig", t.lcd_mosi_problems(None)[0])
        self.assertEqual((t.LCD_MOSI_SIGNAL, t.LCD_MOSI_BROKEN_SIGNAL), (103, 102))

    def test_lcd_binary_prefers_the_build_field(self):
        a = {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True}
        c = {"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False}
        self.assertEqual((t.lcd_binary(a), t.lcd_binary(c)), ("A", "C"))       # no build field: the pipeline alone
        self.assertEqual(t.lcd_binary({"lcdDma": True, "lcdPeriodMs": 33, "artAsync": False}), "B")
        self.assertEqual(t.lcd_binary({**a, "lcdPeriodMs": 14}), "A")           # the measured-period allowance
        self.assertEqual(t.lcd_binary({**a, "build": "D"}), "D")
        self.assertEqual(t.lcd_binary({**a, "lcdPeriodMs": 14, "build": "D"}), "D")   # D keeps it
        self.assertEqual(t.lcd_binary({**c, "build": "E"}), "E")
        for bad in ({**a, "build": "E"}, {**c, "build": "D"}, {**a, "build": "X"}, {**a, "build": None},
                    {**c, "lcdPeriodMs": 16, "build": "E"}):
            self.assertIsNone(t.lcd_binary(bad), bad)                           # a letter with another pipeline
        self.assertEqual(t.lcd_timing_problems({"lcdFpsAnimMin": 30}, "E", "blended"), [])
        self.assertIn("lcdFpsAnimMin 14 < 45", t.lcd_timing_problems({"lcdFpsAnimMin": 14}, "D", "blended")[0])
        self.assertIn("does not identify binary A, B, C, D or E", t.lcd_timing_problems({}, None, "opaque")[0])
        summary = t.lcd_diag_summary({**a, "build": "D", "lcdMosiSig": 103})
        self.assertEqual((summary["build"], summary["lcdMosiSig"]), ("D", 103))
        # Kept apart from LCD_DIAG_FIELDS, which the companion's device.DIAG_LCD_FIELDS mirrors (test_cc_device_diag).
        self.assertEqual(t.LCD_FIX_DIAG_FIELDS, ("lcdMosiSig", "build"))
        self.assertFalse(set(t.LCD_FIX_DIAG_FIELDS) & set(t.LCD_DIAG_FIELDS))

    def test_the_build_marker(self):
        d_image = b"\xe9 1.0.0-cc5.4 " + t.R5_IMAGE_MARKER + b"\0cc-build-binary:4\0"
        e_image = b"\xe9 1.0.0-cc5.4 cc-build-binary:5\0"
        self.assertEqual((t.binary_image_problems(d_image, "D"), t.binary_image_problems(e_image, "E")), ([], []))
        self.assertEqual((t.build_markers(d_image), t.build_markers(b"\xe9"), t.build_markers(None)), ([4], [], []))
        self.assertIn("must carry the build marker 'cc-build-binary:4'",
                      t.binary_image_problems(d_image.replace(b":4", b":0"), "D")[0])   # a build without the flag
        self.assertIn("holds none", t.binary_image_problems(b"\xe9" + t.R5_IMAGE_MARKER, "D")[0])
        self.assertIn("holds 4, 5", t.binary_image_problems(d_image + b"cc-build-binary:5\0", "D")[0])
        problems = t.binary_image_problems(d_image, "E")                          # D's image packaged as E
        self.assertEqual(len(problems), 2)
        self.assertIn("binary E must not contain the R5 decode task", problems[0])
        self.assertIn("'cc-build-binary:5'", problems[1])
        # A, B and C carry no build number: a rebuilt source default ("cc-build-binary:0") is no problem.
        self.assertEqual(t.binary_image_problems(b"\xe9 cc-build-binary:0\0" + t.R5_IMAGE_MARKER, "A"), [])


@needs_tooling
class FixBinaryBuildAndPackageTests(BuildAndPackageFixture):
    """build_ and package_nanod_cc5.py --binary D and E with the real ACTIVE_BINARIES: flags and folders, the LCD
    data-line gate and the build marker in the record, the manifest's binary object; a DMA build without the MOSI
    re-attach is rejected and never packaged; A, B and C are refused before anything runs."""
    active_binaries = None

    def test_d_and_e_build_and_package(self):
        for argv in (["--binary", "D"], ["--binary", "E"], []):                 # no --binary: D, the default
            self.assertEqual(self.build.main(argv), 0, argv)
        for env, name in zip(self.envs, ("D", "E", "D")):
            v = t.CURRENT.binary_profile(name)
            self.assertEqual((env["PLATFORMIO_BUILD_FLAGS"], env["PLATFORMIO_BUILD_DIR"]),
                             (" ".join(LADDER_FLAGS[name]), str(v.build_dir)))
        self.assertTrue(all(c[1:] == ["-m", "platformio", "run", "-d", str(t.FIRMWARE_SOURCE), "-e", t.PIO_ENV]
                            for c in self.commands))                             # never an upload target
        self.assertFalse(t.BUILT_IMAGE.exists())                                 # A's own folder is never built
        for name, parent in (("D", "A"), ("E", "C")):
            v = t.CURRENT.binary_profile(name)
            record = t.load_json(v.build_report)
            dma = name == "D"
            self.assertEqual((record["accepted"], record["binary"], record["buildNumber"], record["diagBuild"],
                              record["pipeline"], record["role"]),
                             (True, name, t.BINARY_BUILD_NUMBERS[name], name, t.LCD_BINARIES[parent], t.BINARY_ROLES[name]))
            gate = record["lcdMosiGate"]
            self.assertEqual((gate["passed"], gate["pins"]["mosi"], gate["pins"]["effectiveMiso"], gate["dma"],
                              gate["reattachRequired"], gate["reattachLinked"]), (True, 4, 4, dma, dma, dma))
            self.assertEqual(gate["callOrder"], ["begin", "initDMA", "reattach", "startWrite"] if dma else ["begin"])
            self.assertEqual((gate["callOrderRule"], gate["callOrderError"]), (t.LCD_CALL_ORDER_RULE, None))
            self.assertIn("TFT_eSPI_ESP32_S3.h 340-342", gate["source"])
            evidence = record["pipelineEvidence"]
            self.assertEqual((evidence["buildMarkers"], evidence["buildMarkerExpected"], evidence["imageHoldsR5Task"],
                              evidence["elfLinksR3Buffer"], evidence["elfLinksMosiReattach"]),
                             ([t.BINARY_BUILD_NUMBERS[name]], f"cc-build-binary:{t.BINARY_BUILD_NUMBERS[name]}", dma, dma, dma))
            self.assertEqual(record["heapProjection"]["hBytes"], 512 if dma else 0)
        self.assertEqual(len(list(t.DIAGNOSTICS.glob("cc5.4-D-build.superseded-*.json"))), 1)   # D built twice
        self.assertIn("LCD data line: MOSI GPIO4, effective MISO 4 (FSPI (SPI2_HOST)), DMA True; re-attach required "
                      "True, linked True; LcdThread::run() calls begin, initDMA, reattach, startWrite: passed",
                      self.out.getvalue())
        for argv in (["--binary", "D"], ["--binary", "E"]):
            self.assertEqual(self.module.main(argv), 0, argv)
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), self.active)            # manifest.json untouched
        self.assertFalse(t.CURRENT.manifest.exists() or t.CURRENT.image.exists())   # A's package is never written
        for name, parent in (("D", "A"), ("E", "C")):
            v = t.CURRENT.binary_profile(name)
            manifest = t.load_json(v.manifest)
            self.assertEqual((manifest["firmwareVersion"], manifest["installationStatus"]), ("1.0.0-cc5.4", "UNFLASHED"))
            self.assertEqual(manifest["image"]["sha256"], t.load_json(v.build_report)["sha256"])
            binary = manifest["binary"]
            self.assertEqual((binary["name"], binary["buildNumber"], binary["diagBuild"], binary["parent"],
                              binary["active"], sorted(binary["retired"])),
                             (name, t.BINARY_BUILD_NUMBERS[name], name, parent, ["D", "E"], ["A", "B", "C"]))
            self.assertTrue(binary["lcdMosiGate"]["passed"])
            self.assertIn("MOSI re-attach", binary["fixes"])
            self.assertEqual(binary["ladder"], {b: t.CURRENT.binary_profile(b).manifest.name for b in t.PIPELINE_BINARIES})
            self.assertEqual(binary["timingTargets"]["lcdFpsAnimMin"], t.LCD_FPS_TARGETS[parent])
            self.assertIn("(Fix binaries D and E)", binary["contract"])
            self.assertIn(f"diagnostics/{v.build_report.name}", manifest["gates"])
        d, e = (t.load_json(t.CURRENT.binary_profile(n).manifest)["hardwareStatus"] for n in ("D", "E"))
        self.assertTrue(d.endswith("Binary D (release candidate (A + fixes)) of the PRESENTATION_V5 12.6 ladder."), d)
        self.assertIn("Binary E (fallback (C + fixes)) of the PRESENTATION_V5 12.6 ladder: flashed only when the "
                      "hardware window steps down to it", e)

    def test_a_dma_build_without_the_reattach_is_rejected_and_never_packaged(self):
        self.reattach = False                                                   # binary A's source
        self.assertEqual(self.build.main(["--binary", "D"]), 1)
        d = t.CURRENT.binary_profile("D")
        record = t.load_json(d.build_report)
        self.assertFalse(record["accepted"] or record["lcdMosiGate"]["passed"])
        self.assertIn("does not link cc_lcd_mosi_reattach: do not flash it", " ".join(record["problems"]))
        self.assertIn("LCD data line: MOSI GPIO4, effective MISO 4", self.out.getvalue())
        self.assertEqual(self.build.main(["--binary", "E"]), 0)                  # E has no DMA: nothing to re-attach
        t.write_json_evidence(d.build_report, {**record, "accepted": True, "problems": []})   # accepted by hand anyway
        with self.assertRaises(SystemExit) as caught:
            self.module.main(["--binary", "D"])
        self.assertIn("does not record a passed LCD data-line gate (lcdMosiGate", str(caught.exception))
        del record["lcdMosiGate"]                                                # a record from before the gate
        t.write_json_evidence(d.build_report, {**record, "accepted": True, "problems": []})
        with self.assertRaises(SystemExit):
            self.module.main(["--binary", "D"])
        self.assertFalse(d.manifest.exists() or d.image.exists())

    def test_a_reattach_called_anywhere_but_right_after_init_dma_is_rejected(self):
        """The symbol links, but LcdThread::run() calls it before initDMA (or never after it): A's routing again."""
        d = t.CURRENT.binary_profile("D")
        for order, words in ((["begin", "reattach", "initDMA", "startWrite"], "is not directly followed by "
                              "cc_lcd_mosi_reattach and then startWrite"),
                             (["begin", "initDMA", "startWrite", "reattach"], "is not directly followed by"),
                             (["begin", "reattach", "startWrite"], "shows no direct call to TFT_eSPI::initDMA"),
                             (OSError("objdump is missing"), "was not read (OSError: objdump is missing)")):
            with self.subTest(order=order):
                self.call_order = order
                self.assertEqual(self.build.main(["--binary", "D"]), 1)
                record = t.load_json(d.build_report)
                self.assertFalse(record["accepted"] or record["lcdMosiGate"]["passed"])
                self.assertTrue(record["lcdMosiGate"]["reattachLinked"])
                self.assertIn(words, " ".join(record["problems"]))
        self.call_order = None
        self.assertEqual(self.build.main(["--binary", "D"]), 0)
        record = t.load_json(d.build_report)
        del record["lcdMosiGate"]["callOrder"]                                  # a record from before the order check
        t.write_json_evidence(d.build_report, record)
        with self.assertRaises(SystemExit) as caught:
            self.module.main(["--binary", "D"])
        self.assertIn("call it right after tft.initDMA(), callOrder", str(caught.exception))
        self.assertFalse(d.manifest.exists() or d.image.exists())

    def test_hspi_or_unknown_pins_are_refused(self):
        ini = t.FIRMWARE_SOURCE / "platformio.ini"
        ini.write_text("[env:nanofoc_d]\nbuild_flags =\n\t-DTFT_MOSI=4\n\t-DUSE_HSPI_PORT\n", encoding="utf-8")
        self.assertEqual(self.build.main(["--binary", "E"]), 1)
        self.assertIn("the encoder owns HSPI", " ".join(t.load_json(t.CURRENT.binary_profile("E").build_report)["problems"]))
        ini.write_text("[env:nanofoc_d]\n", encoding="utf-8")
        self.assertEqual(self.build.main(["--binary", "D"]), 1)
        self.assertIn("TFT_MOSI is not set", " ".join(t.load_json(t.CURRENT.binary_profile("D").build_report)["problems"]))

    def test_flags_that_did_not_take_effect_are_rejected(self):
        self.ignore_flags = True                                                # PlatformIO built the source defaults
        self.assertEqual(self.build.main(["--binary", "D"]), 1)
        text = " ".join(t.load_json(t.CURRENT.binary_profile("D").build_report)["problems"])
        self.assertIn("binary D must carry the build marker 'cc-build-binary:4'", text)
        self.assertEqual(self.build.main(["--binary", "E"]), 1)
        text = " ".join(t.load_json(t.CURRENT.binary_profile("E").build_report)["problems"])
        for words in ("binary E must not contain the R5 decode task", "'cc-build-binary:5'",
                      "binary E must not link the R3 draw buffer"):
            self.assertIn(words, text)

    def test_retired_binaries_are_refused_before_anything_runs(self):
        for module in (self.build, self.module):
            for name in t.RETIRED_BINARIES:
                with self.subTest(module=module.__name__, binary=name), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as caught:
                    module.main(["--binary", name])
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual((self.commands, sorted(t.DIAGNOSTICS.iterdir()), sorted(t.WORK.iterdir())), ([], [], []))


@needs_tooling
class FixBinaryStepDownTests(HardwareFreeScriptTest):
    """The 2026-09-26 path on the in-memory flash (DeviceEsptool): A installed from the pre-cc5.4 backup in the
    window's ladder and rolled back verified with no drift; then, with the real ACTIVE_BINARIES, D through a step-down
    base read, prepare --step-down-base, the install and its rollback. A's records are never rewritten."""
    script, capture_evidence, active_binaries = "install_nanod_cc5.py", False, None
    INVENTORY = ("--before-inventory", "inventory-before.json")

    def setUp(self):
        super().setUp()
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.p, self.before, self.candidates = cc54_prepare_fixture(self, root, "D")
        self.patch(t, "ORIGINAL_PARTITIONS", root / "no-original-partitions.bin")
        self.fake = DeviceEsptool(self.before)
        self.patch(t, "Esptool", self.fake.factory)
        self.backup = load_script("backup_nanod_cc5.py")
        self.prepare = load_script("prepare_nanod_cc5_install.py")
        self.rollback = load_script("rollback_nanod_cc5.py")
        self.locked = (t.CURRENT.before_full.read_bytes(), t.CURRENT.backup_report.read_bytes())

    def tearDown(self):
        self.assertEqual((t.CURRENT.before_full.read_bytes(), t.CURRENT.backup_report.read_bytes()), self.locked)

    def run_script(self, module, *argv):
        self.fake.calls = []
        return module.main(list(argv))

    def refused(self, module, *argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.run_script(module, *argv)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.fake.calls, [])

    def test_a_rolled_back_then_d_installs_from_a_step_down_base(self):
        with mock.patch.object(t, "ACTIVE_BINARIES", LEGACY_BINARIES):          # the 2026-09-26 window
            self.assertEqual(self.run_script(self.prepare, *self.INVENTORY, "--binary", "A"), 0)
            self.assertEqual(self.run_script(self.module, "--binary", "A"), 0)
        start = len(self.out.getvalue())
        self.assertEqual(self.run_script(self.rollback, "--to", "cc5.3", "--binary", "A"), 0)
        rollback = t.load_json(t.CURRENT.rollback_report)
        self.assertEqual((rollback["outcome"], rollback["fullImageMatchesBackup"]), ("ROLLED_BACK_VERIFIED_RESET", True))
        self.assertIn("cc5.3 restored in app0, verified and reset", self.out.getvalue()[start:])
        self.assertNotIn("did NOT complete", self.out.getvalue()[start:])       # the false line of 2026-09-26
        self.assertEqual(bytes(self.fake.device), self.before)                  # cc5.3 back, no drift
        a_records = {path.name: path.read_bytes() for path in t.DIAGNOSTICS.glob("cc5.4-*.json")}
        self.assertIn("cc5.4-flash-checks.json", a_records)
        # A, B and C are retired: prepare and install refuse them before anything is read or sent.
        self.refused(self.prepare, *self.INVENTORY, "--binary", "A")
        self.refused(self.module, "--binary", "B")
        # D: the step-down base read (allowed because A's write locked the backup), prepare, install.
        self.assertEqual(self.run_script(self.backup, "--step-down"), 0)
        record = t.load_json(t.CURRENT.step_down_report)
        base = t.BACKUPS / record["file"]
        self.assertEqual((record["role"], record["dataRegionsChangedSinceBackup"], record["identicalToLockedBackup"]),
                         ("step-down base", [], True))
        self.assertEqual(base.read_bytes(), self.before)
        d = t.CURRENT.binary_profile("D")
        self.assertEqual(self.run_script(self.prepare, *self.INVENTORY, "--step-down-base"), 0)   # --binary D, the default
        prep = t.load_json(d.preparation)
        self.assertEqual((prep["binary"], prep["baseKind"], prep["baseFile"], prep["beforeFile"]),
                         ("D", "step-down base", base.name, t.CURRENT.before_full.name))
        start = len(self.out.getvalue())
        self.assertEqual(self.run_script(self.module), 0)                        # install --binary D, the default
        said = self.out.getvalue()[start:]
        self.assertIn("Next (the look session): step 7 boot sanity (port only: 239A:8010 stable for 30 s), 8a inventory "
                      "(device_inventory.py), then check_nanod_cc5_look.py --binary D.", said)
        self.assertNotIn("check_nanod_cc5.py", said)                             # not the 8b window (TB-D11)
        self.assertEqual(self.fake.names(), ["identity", "before-verify", "write", "after-verify", "reset"])
        self.assertEqual(self.fake.args("write")[-2:], ["0x10000", str(d.image)])
        flash = t.load_json(d.flash_checks)
        self.assertEqual((flash["outcome"], flash["binary"], flash["baseKind"], flash["baseFile"]),
                         ("INSTALLED_VERIFIED_RESET", "D", "step-down base", base.name))
        expected, _ = t.assemble_expected(self.before, self.candidates["D"])
        self.assertEqual(bytes(self.fake.device), bytes(expected))
        self.assertEqual(t.newest_written_binary(t.CURRENT)[:2], ("D", d.flash_checks.name))
        # D was installed from that base, so check_nanod_cc5.py / the look check read its coredump partition (TB-D9).
        self.assertEqual(t.step_down_coredump(t.CURRENT, "D")["base"], base.name)
        # D's rollback: without --binary it is the newest written binary.
        start = len(self.out.getvalue())
        self.assertEqual(self.run_script(self.rollback, "--to", "cc5.3"), 0)
        record = t.load_json(d.rollback_report)
        self.assertEqual((record["binary"], record["binarySource"], record["outcome"]),
                         ("D", "records (newest write: cc5.4-D-flash-checks.json)", "ROLLED_BACK_VERIFIED_RESET"))
        self.assertNotIn("did NOT complete", self.out.getvalue()[start:])
        self.assertEqual(bytes(self.fake.device), self.before)
        # A's records (preparation, flash, rollback) were never rewritten by D's steps.
        for name, data in a_records.items():
            self.assertEqual((t.DIAGNOSTICS / name).read_bytes(), data, name)
        self.assertEqual(sorted(p.name for p in t.DIAGNOSTICS.glob("cc5.4-*.superseded-*")), [])


@needs_tooling
class LookCheckTests(unittest.TestCase):
    """check_nanod_cc5_look.py and tooling.look_check_problems: two read-only diag reads of a fix binary (build and
    pipeline, lcdMosiSig 103, coredump, reset reason, no reboot), GO / NO-GO / NOT RUN, the evidence under the
    binary's name, and the user's answers recorded without a port."""

    class Clock:
        def __init__(self):
            self.now = 100.0

        def __call__(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("DIAGNOSTICS", "BACKUPS", "FIRMWARE_OUT"):
            self.enterContext(mock.patch.object(t, name, self.root))
        self.enterContext(mock.patch.object(t, "console_utf8", lambda: None))
        self.enterContext(mock.patch.object(t, "list_ports", mock.Mock(side_effect=AssertionError("no enumeration"))))
        self.module = load_script("check_nanod_cc5_look.py")

    def diag(self, binary="D", uptime=60000, **extra):
        return boot_diag(uptime=uptime, **{"build": binary, "lcdMosiSig": 103, **t.LCD_BINARIES[binary], "ledFps": 60,
                                           "ledShowGapMsMax": 17, "ledMode": "alive", "lcdFps": 0, "lcdFullRefrs": 12,
                                           **extra})

    def run_look(self, *argv, reads=(), quit_error=None, port_error=None, running=()):
        self.probes, answers = [], iter(reads)

        def probe(port):
            self.probes.append(port)
            value = next(answers)
            if isinstance(value, BaseException):
                raise value
            return value

        clock, out = self.Clock(), io.StringIO()
        with mock.patch.object(t, "probe_diag", probe), \
                mock.patch.object(t, "require_companion_quit", mock.Mock(side_effect=quit_error, return_value=False)), \
                mock.patch.object(t, "find_app_port", mock.Mock(side_effect=port_error, return_value="FAKEAPP")), \
                mock.patch.object(t, "running_companions", lambda: list(running)), contextlib.redirect_stdout(out):
            code = self.module.main(list(argv), sleep=clock.sleep, clock=clock)
        return code, out.getvalue()

    def evidence(self, binary="D"):
        return t.load_json(t.CURRENT.binary_profile(binary).look_checks)

    def test_look_check_problems(self):
        first, second = self.diag(), self.diag(uptime=62100)
        self.assertEqual(t.look_check_problems(first, second, "D"), [])
        self.assertEqual(t.look_check_problems(self.diag("E"), self.diag("E", uptime=62100), "E"), [])
        no_build = {k: v for k, v in first.items() if k != "build"}
        cases = {
            "LCD DATA LINE ON THE MISO OUTPUT: lcdMosiSig 102": (self.diag(lcdMosiSig=102), second),
            "second read: diag lacks integer lcdMosiSig": (first, {k: v for k, v in second.items() if k != "lcdMosiSig"}),
            "first read: diag does not identify binary D (build None": (no_build, second),
            "diag does not identify binary D (build 'E'": (self.diag(build="E"), second),
            "identified None": (self.diag(lcdPeriodMs=33, artAsync=False), second),     # D's letter, B's pipeline
            "CRASH RESET: resetReason task_wdt": (self.diag(reason="task_wdt"), self.diag(reason="task_wdt", uptime=62100)),
            "a core dump is stored (9000 B)": (self.diag(coredump={"blank": False, "present": True, "status": "ESP_OK",
                                                                    "bytes": 9000}), second),
            "REBOOT: bootCount 3 -> 4": (first, self.diag(boot=4, uptime=900)),
            "uptime did not advance between the reads": (first, self.diag()),
            "no diag reply (second read)": (first, None),
        }
        for fragment, (a, b) in cases.items():
            with self.subTest(fragment):
                self.assertIn(fragment, " | ".join(t.look_check_problems(a, b, "D")))
        # Binary A's image (no build, no lcdMosiSig) is not D, whatever its pipeline.
        a = {k: v for k, v in first.items() if k not in ("build", "lcdMosiSig")}
        text = " | ".join(t.look_check_problems(a, {**a, "uptimeMs": 62100}, "D"))
        self.assertIn("identified 'A'", text)
        self.assertIn("lacks integer lcdMosiSig", text)
        # After a step-down, only the dump the step-down base holds, with a non-crash reset (TB-D9).
        dump = {"blank": False, "present": True, "status": "ESP_OK", "bytes": 11852}
        inherited = {"base": "nanod-cc5.3-step-down-base-X.bin", "bytes": 11852}
        self.assertEqual(t.look_check_problems(self.diag(coredump=dump), self.diag(coredump=dump, uptime=62100), "D",
                                               inherited), [])

    def test_go_writes_the_evidence_and_a_rerun_keeps_the_previous(self):
        code, out = self.run_look("--binary", "D", reads=(self.diag(), self.diag(uptime=62100)))
        self.assertEqual(code, 0)
        self.assertEqual(self.probes, ["FAKEAPP", "FAKEAPP"])
        record = self.evidence()
        self.assertEqual((record["binary"], record["go"], record["verdict"], record["problems"], record["readGapS"],
                          record["byEye"]), ("D", True, "GO", [], 2.0, None))
        self.assertEqual(record["expected"], {"build": "D", "pipeline": t.LCD_BINARIES["D"], "lcdMosiSig": 103})
        self.assertEqual(record["recorded"]["second"], {"ledFps": 60, "ledShowGapMsMax": 17, "ledMode": "alive",
                                                        "lcdFps": 0, "lcdFullRefrs": 12})
        self.assertEqual([r["diag"]["uptimeMs"] for r in record["reads"]], [60000, 62100])
        self.assertIn("Look check, binary D (release candidate (A + fixes)): GO", out)
        self.assertIn("--record-by-eye leds=pass|fail hue=pass|fail screen=pass|fail screen_host=pass|fail "
                      "screen_after_quit=pass|fail", out)
        code, out = self.run_look(reads=(self.diag(lcdMosiSig=102), self.diag(lcdMosiSig=102, uptime=62100)))   # default D
        self.assertEqual(code, 1)
        record = self.evidence()
        self.assertEqual((record["verdict"], record["go"]), ("NO-GO", False))
        self.assertIn("lcdMosiSig 102 (FSPIQ_OUT), binary A's defect", " ".join(record["problems"]))
        self.assertIn("NO-GO: do not ask the user to look; roll binary D back (rollback_nanod_cc5.py --to cc5.3 "
                      "--binary D", out)
        [kept] = self.root.glob("cc5.4-D-look-checks.superseded-*.json")       # the GO record is kept
        self.assertTrue(t.load_json(kept)["go"])
        self.assertIn(f"previous kept as {kept.name}", out)

    def test_no_go_cases(self):
        for label, reads, fragment in (
                ("missing build", ({k: v for k, v in self.diag().items() if k != "build"}, self.diag(uptime=62100)),
                 "does not identify binary D"),
                ("crash reset", (self.diag(reason="panic"), self.diag(reason="panic", uptime=62100)), "CRASH RESET"),
                ("reboot", (self.diag(), self.diag(boot=4, uptime=700)), "REBOOT"),
                ("E on the knob", (self.diag("E"), self.diag("E", uptime=62100)), "(build 'E'"),
                ("read failed", (self.diag(), TimeoutError("No diag within 2.0 s")), "diag read failed (TimeoutError")):
            with self.subTest(label):
                code, _ = self.run_look("--binary", "D", reads=reads)
                self.assertEqual(code, 1)
                self.assertIn(fragment, " ".join(self.evidence()["problems"]))
        code, _ = self.run_look("--binary", "E", reads=(self.diag("E"), self.diag("E", uptime=62100)))
        self.assertEqual((code, self.evidence("E")["verdict"]), (0, "GO"))

    def test_not_run_writes_nothing(self):
        for kwargs in ({"quit_error": SystemExit("DeskDial.exe is running and owns the knob.")},
                       {"port_error": t.PortError("no port")},
                       {"reads": (self.diag(), OSError("could not open port")), "running": ("DeskDial.exe",)}):
            with self.subTest(sorted(kwargs)):
                code, out = self.run_look("--binary", "D", **kwargs)
                self.assertEqual(code, 3)
                self.assertIn("NOT RUN", out)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_the_users_answers_need_no_port(self):
        code, out = self.run_look("--binary", "D", "--record-by-eye", "screen=pass", "leds=pass")
        self.assertEqual(code, 2)                                                # no look-check record yet
        self.assertIn("run check_nanod_cc5_look.py --binary D first", out)
        self.assertEqual(self.run_look("--binary", "D", reads=(self.diag(), self.diag(uptime=62100)))[0], 0)
        blocked = {"quit_error": AssertionError("the answers never check the companion"),
                   "port_error": AssertionError("the answers never open a port")}
        code, out = self.run_look("--binary", "D", "--record-by-eye", "screen=pass", **blocked)
        self.assertEqual(code, 0)
        self.assertIn("(still to answer: hue, leds, screen_after_quit, screen_host)", out)
        code, out = self.run_look("--binary", "D", "--record-by-eye", "leds=fail", "--note", "one mark shimmers", **blocked)
        self.assertEqual(code, 1)
        self.assertEqual(self.probes, [])
        eye = self.evidence()["byEye"]
        self.assertEqual((eye["answers"], eye["passed"], eye["complete"], eye["notes"]),
                         ({"screen": "pass", "leds": "fail"}, False, False, ["one mark shimmers"]))
        self.assertIn("steady (no shimmer, sparkle or flip at the dim point)", eye["questions"]["leds"])
        self.assertEqual(self.evidence()["verdict"], "GO")                       # the diag reads stay as they were
        self.assertEqual(len(list(self.root.glob("cc5.4-D-look-checks.superseded-*.json"))), 2)
        self.assertIn("By eye, binary D: screen pass, leds fail -> FAIL (still to answer: hue, screen_after_quit, "
                      "screen_host); the diag reads were GO.", out)
        # The rest after the long host run and the release (#010000 at the dim point is the expected hue).
        code, out = self.run_look("--binary", "D", "--record-by-eye", "hue=pass", "screen_host=pass",
                                  "screen_after_quit=fail", **blocked)
        self.assertEqual(code, 1)
        eye = self.evidence()["byEye"]
        self.assertEqual((eye["complete"], eye["passed"], sorted(eye["questions"])),
                         (True, False, sorted(self.module.BY_EYE_QUESTIONS)))
        self.assertIn("#010000", eye["questions"]["hue"])
        self.assertIn("about 5 minutes", eye["questions"]["screen_host"])
        self.assertIn("quits Desk Dial from its tray", eye["questions"]["screen_after_quit"])
        self.assertEqual(list(self.module.BY_EYE_QUESTIONS),
                         ["leds", "hue", "screen", "screen_host", "screen_after_quit"])
        code, _ = self.run_look("--binary", "E", "--record-by-eye", "screen=pass", **blocked)   # E has no record
        self.assertEqual(code, 2)

    def test_usage_errors(self):
        for argv in (["--binary", "A"], ["--gap", "1.0"], ["--record-by-eye", "screen=ok"],
                     ["--record-by-eye", "screen=pass", "screen=fail"], ["--record-by-eye", "colour=pass"]):
            with self.subTest(argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                self.run_look(*argv)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.probes, [])

    def test_static_safety(self):
        source = (WORK / "check_nanod_cc5_look.py").read_text(encoding="utf-8")
        code = source[source.index('"""', 3) + 3:]                              # without the module docstring
        for forbidden in ("winsound", "audible_cue", "esptool", "RawKnob(", ".enter(", ".frame(", "release",
                          "write_flash"):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertIn("t.probe_diag(port)", code)                               # read-only: open, diag, close
        self.assertIn("t.write_json_evidence(p.look_checks, record)", code)     # an earlier record is archived
        look = code[code.index("def look("):code.index("def record_by_eye(")]
        self.assertLess(look.index("t.require_companion_quit()"), look.index("t.find_app_port()"))
        self.assertNotIn("require_companion_quit", code[code.index("def record_by_eye("):code.index("def main(")])


@needs_tooling
class FixBinaryRunbookTests(unittest.TestCase):
    """firmware/BUILD-cc5.4.md "Fix binaries D and E" read as text: the root causes, the retired binaries, the D and
    E build and package commands, the look session's blocks, the step-down rows and the guards that take D and E."""
    DOC = Cc54RunbookTests.DOC
    NATIVE = ScriptStaticTests.NATIVE
    setUp = Cc54RunbookTests.setUp
    blocks = staticmethod(Cc54RunbookTests.blocks)

    def section(self):
        return self.text[self.text.index("## Fix binaries D and E"):self.text.index("## Hardware window (Stage 10)")]

    def test_status_causes_and_retired_binaries(self):
        status = " ".join(self.text.split("## What 1.0.0-cc5.4 changes")[0].split())
        for phrase in ("binary A was installed (18:35 UTC) and rolled back (21:12 UTC, `ROLLED_BACK_VERIFIED_RESET`",
                       "The knob runs 1.0.0-cc5.3 with Desk Dial v7.", "[Fix binaries D and E](#fix-binaries-d-and-e)"):
            self.assertIn(phrase, status)
        flat = " ".join(self.section().split())
        for phrase in ("MOSI = MISO = GPIO4", "FSPID (signal 103)", "FSPIQ_OUT (102)", "`TFT_eSPI_ESP32_S3.h` 340-342",
                       "the dither is off by default, with a minimum brightness floor", "`did NOT complete` (exit 4 only)",
                       "`cc_lcd_mosi_reattach()`", "`USE_HSPI_PORT` is refused because the encoder owns HSPI",
                       "They refuse A, B and C in argparse (exit 2, nothing written)",
                       "still take every binary from A to E", "D cannot pass `lcdTimings` yet"):
            self.assertIn(phrase, flat)
        for name in t.RETIRED_BINARIES:
            self.assertRegex(self.section(), rf"(?m)^\| {name} \| ")

    def test_the_d_and_e_names_and_commands(self):
        section = self.section()
        for name in ("D", "E"):
            v = t.CURRENT.binary_profile(name)
            self.assertIn(f"`{' '.join(v.build_flags)}`", section)
            self.assertIn("nanod-pio-venv\\Scripts\\python.exe' '<repo>\\tools"
                          f"\\build_nanod_cc5.py' --binary {name}", section)
            self.assertIn(".venv\\Scripts\\python.exe' '<repo>\\tools"
                          f"\\package_nanod_cc5.py' --binary {name}", section)
            for attr in ("image", "manifest", "build_report"):
                self.assertIn(getattr(v, attr).name, section, (name, attr))
        d = t.CURRENT.binary_profile("D")
        for attr in ("expected_full", "preparation", "flash_checks", "rollback_report", "installation", "look_checks"):
            self.assertIn(getattr(d, attr).name, section, attr)
        self.assertIn("the same with `cc5.4-E-`", section)
        for phrase in ("`lcdMosiGate`", "`cc-build-binary:4`", "`cc-build-binary:5`", "`pipelineEvidence.buildMarkers`",
                       "`diagnostics\\cc5.4-stage9b-*.log`", "`diagnostics\\cc5.4-alive-floor-report.json`"):
            self.assertIn(phrase, section)
        build = section[section.index("### Build and package D and E"):section.index("### Gate evidence for D and E")]
        self.assertNotIn(" upload", "\n".join("\n".join(lines) for lines in self.blocks(build)))

    @machine_runbook
    def test_the_look_session_blocks(self):
        section = self.section()
        look = section[section.index("### The look session (hardware, D first)"):]
        blocks = self.blocks(look)
        ScriptStaticTests.assert_absolute_existing_paths(self, look)
        ScriptStaticTests.assert_exit_codes_are_armed(self, blocks, "BUILD-cc5.4.md look session")
        for lines in blocks:
            self.assertEqual((lines[0], lines[-1]), (". {", "}"))
            for message in re.findall(r"""throw ['"]([^'"]*)""", "\n".join(lines)):
                self.assertRegex(message, r"^(?:NO-GO|NOT RUN): ", message)
        texts = ["\n".join(lines) for lines in blocks]
        quit_block = texts[0]
        self.assertIn("Disable-ScheduledTask", quit_block)
        self.assertNotIn("--smoke-test", quit_block)
        self.assertIn("$binary = 'D'", look)
        read = next(b for b in texts if "check_nanod_cc5_look.py' --binary $binary" in b and "--record-by-eye" not in b)
        eye = next(b for b in texts if "--record-by-eye" in b)
        self.assertLess(read.index("Get-Process -Name DeskDial, NanoDControlCenter"), read.index("& $app"))
        self.assertIn("if ($binary -notin 'D', 'E')", read)
        self.assertIn("if ($lookExit -eq 3) { throw 'NOT RUN: ", read)
        self.assertIn("$look.reads[1].diag.lcdMosiSig -ne 103", read)
        self.assertIn("--record-by-eye leds=<pass|fail> hue=<pass|fail> screen=<pass|fail> screen_host=<pass|fail> "
                      "screen_after_quit=<pass|fail>", eye)                      # the placeholders stop PowerShell
        keys = re.findall(r"(\w+)=<pass\|fail>", eye)
        self.assertEqual(keys, list(load_script("check_nanod_cc5_look.py").BY_EYE_QUESTIONS))
        self.assertNotIn("Get-Process", eye)                                     # it runs while Desk Dial runs
        for anchor in ("#step-2-pre-flash-inventory-cc53-presentation-4", "#step-3-enter-the-rom-bootloader-one-1200-bps-touch",
                       "#step-down-between-binaries-presentation_v5-126", "#step-6-app-only-install-of-the-binary-under-test",
                       "#step-7-boot-sanity-no-companion", "#firmware-rollback-cc54---cc53", "#re-enable-the-companion"):
            self.assertIn(f"]({anchor})", look)
        flat = " ".join(look.split())
        for phrase in ("D's rollback and E's install each need their own go-ahead", "The Desk Dial task is never left "
                       "disabled", "keep D installed and not finalized", "E does not help here, because it has the same "
                       "LED code", "No existing `diagnostics\\cc5.4-*.json` run record is modified",
                       # review fixes: who quits Desk Dial, step 7's port block only, the dim-point hue, the long host
                       # run and the quit check, every rollback branch quits Desk Dial first and re-enables it after
                       "asks the user to quit Desk Dial from its tray icon", "Run only the port-stability block of",
                       "a screen seen now proves nothing", "Do not ask the user to look yet",
                       "one count of red (`#010000`, amber's dominant channel", "That red is expected",
                       "For about 5 minutes the user uses Home", "`screen_host`: the knob's screen keeps updating",
                       "D holds the panel's chip select low for its whole uptime",
                       "`screen_after_quit`: the native dial comes back",
                       "every branch that rolls a binary back starts by quitting Desk Dial",
                       "if D's screen later goes dark or freezes", "should land before D is kept for the long term",
                       "a mark is not visible or the hue is wrong"):
            self.assertIn(phrase, flat)
        decide = look[look.index("12. **Decide**"):look.index("13. **End state.**")]
        branches = re.split(r"\n    - ", decide)[1:]
        self.assertEqual(len(branches), 4)
        for branch in branches:                                                   # every rollback path is complete
            flat_branch = " ".join(branch.split())
            if "roll" in flat_branch and "back" in flat_branch:
                self.assertIn("(#after-the-rollback)", flat_branch)
                self.assertIn("(#re-enable-the-companion)", flat_branch)
                self.assertRegex(flat_branch, r"[Qq]uit Desk Dial")

    def test_the_step_down_rows_and_the_guards(self):
        table = self.text[self.text.index("### Step-down between binaries (PRESENTATION_V5 12.6)"):self.text.index("### Step 9.")]
        self.assertEqual([row[0] for row in re.findall(r"^\| ([DE]) \| (.*)$", table, re.M)],
                         ["D", "D", "D", "D", "E", "E"])
        for phrase in ("**keep D** installed, not finalized", "roll back D; set `$binary = 'E'`", "E has the same LED code",
                       "**keep E** installed, not finalized", "roll back E to cc5.3 and stop",
                       "`screen`, `screen_host` or `screen_after_quit` fails",
                       "a mark is not visible or the hue is wrong"):
            self.assertIn(phrase, table)
        guards = re.findall(r"if \(\$binary -notin ([^)]*)\)", self.text)
        self.assertGreaterEqual(len(guards), 10)
        self.assertTrue(all("'D', 'E'" in guard for guard in guards), guards)
        for heading in ("### Step 6. ", "### Step 10. "):              # install and finalize take D and E only
            step = self.text[self.text.index(heading):]
            self.assertIn("if ($binary -notin 'D', 'E')", step[:step.index("\n### ", 1)])



def firmware_lines(firmware):
    """Every line FakeFirmware received, in order (from the RawKnob writes it recorded)."""
    return firmware.received


def sent_frames(firmware):
    """Every distinct frame (frame lines and control frames) a FakeFirmware54 received, in order."""
    seen, frames = set(), []
    for line in firmware.received:
        if line.startswith(('{"frame"', '{"control"')) and line not in seen:
            seen.add(line)
            doc = json.loads(line)
            frames.append(doc["frame"] if "frame" in doc else doc["control"]["frame"])
    return frames


def copy_json(value):
    return json.loads(json.dumps(value))


def prompt_fit_problems(frame):
    """Why the instruction on `frame` does not fit the knob's glass (control_center.lcd_preview, the firmware's
    fitting): the heading loses its 1 px tracking or is cut, or an instruction line ends in an ellipsis. The line
    that carries a per-frame tag ("Stress 12 ab3f", "Soak recent 7") is exempt (the tag only keeps a label
    changing)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from control_center import lcd_preview
    problems = []
    heading = frame.get("heading", "")
    if heading:
        fitted, tracking, _ = lcd_preview.fit_heading(heading)
        if fitted != heading or tracking != 1:
            problems.append(f"heading {heading!r} -> {fitted!r} at {tracking} px tracking")
    tag_line = tagged(frame, "Stress") or tagged(frame, "Soak")
    for run in lcd_preview.compose(frame).items:
        text = getattr(run, "text", None)
        if not isinstance(text, str) or not text.endswith(lcd_preview.ELLIPSIS) or run.role == "heading":
            continue
        if tag_line and run.role in ("meta", "status", "line"):
            continue
        problems.append(f"{run.role} cut: {text!r}")
    return problems


if __name__ == "__main__":
    unittest.main()
