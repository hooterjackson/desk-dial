"""Shared helpers for the cc5 hardware window (Stages 9-10 of the cc5 plan).

Importing this module never opens a serial port, never runs esptool and never
touches the network. Everything that talks to hardware is behind an explicit
call (``list_ports``, ``RawKnob``, ``Esptool``) and is only reached from the
hardware-window scripts (``nanod_enter_bootloader_v2.py``, ``backup_``,
``install_``, ``rollback_`` and ``check_nanod_cc5*.py``).

Release profiles (``Release``, ``PROFILES``, ``CURRENT``): each upgrade is one
profile naming the release it installs, the release it upgrades from, its locked
pre-install backup pair, its expected image and its own evidence names. ``CURRENT``
is the 1.0.0-cc5.4 D -> 1.0.0-cc5.5 upgrade (F1, safety and measurement; see below); the
1.0.0-cc4 -> 1.0.0-cc5.2, 1.0.0-cc5.2 -> 1.0.0-cc5.3 and 1.0.0-cc5.3 -> 1.0.0-cc5.4 profiles stay
defined for their history and their rollbacks (``ROLLBACK_TARGETS``: cc4, cc5.2, cc5.3 and
cc5.4). Their evidence never shares a file name (``diagnostics/cc5-*.json`` is cc5.2's,
``diagnostics/cc5.3-*.json`` cc5.3's, ``diagnostics/cc5.4-*.json`` cc5.4's, ``diagnostics/cc5.5-*.json``
cc5.5's), so an earlier install, rollback and finalize record is never renamed or rewritten by a later run.

1.0.0-cc5.5 (profile ``PROFILES["cc5.5"]`` = ``NEWEST`` = ``CURRENT``; firmware/BUILD-cc5.5.md; plan stage F1,
no change to feel): the HID send fix, the USB init check, the 2.2 V motor output cap (no register command
raises it), haptic profile validation, no String / Serial.println on the FOC thread, the clear-only ``ks`` of
position lines with a 16-event key queue, and the diag fields F1_DIAG_FIELDS (FOC loop rate and gaps, |Uq|
against the cap, the PD contract, USB and HID). It upgrades binary D of 1.0.0-cc5.4 (``from_binary`` "D":
its image firmware/nanod-control-center-1.0.0-cc5.4-D.bin, 1,142,448 B, SHA-256 dcff9c95...), which was
installed (diagnostics/cc5.4-D-flash-checks.json) but never finalized: manifest.json still holds the cc5.3
record. The profile says so (``from_finalized=False``): the from-release's record is its package manifest,
kept byte-identical as firmware/manifest-cc5.4-D.json when cc5.5 is packaged; prepare requires manifest.json
to be the record that install left in force (``restore_record``: firmware/manifest-cc5.3.json) and the D
install record to be the newest cc5.4 write (``from_install_problems``); ``rollback_nanod_cc5.py --to cc5.4
--binary D|F`` restores app0 from the pre-cc5.5 backup (backups/nanod-cc5.4-before-cc5.5-*.bin, cc5.4 D at
app0) and manifest.json to that same record. cc5.5 has its own ladder (``Release(ladder=("D", "F"))``): D is
the release candidate with the 16 ms LCD period (CC_BUILD_BINARY 4, cc5.4 D's pipeline) and F the same with a
12 ms period (CC_LCD_PERIOD_MS 12, CC_BUILD_BINARY 6; diag build "F"), built into .pio/build-cc5.5-D and -F,
packaged as manifest-1.0.0-cc5.5-D.json and -F.json. Its build acceptance adds the flash size gate
(``image_size_gate``: IMAGE_SIZE_GATE_BYTES, 1,245,184 B = 95 % of app0).
1.0.0-cc5.6 (profile ``PROFILES["cc5.6"]`` = ``NEWEST``; firmware/BUILD-cc5.6.md; plan stage A2, Karl Malota's
Onshape UI on the knob): the app canvas (the frame's ``app`` object, capability ``appCanvas`` 1) on 1.0.0-cc5.5 binary
D, with the same ladder (D 16 ms, F 12 ms) and size gate. ``CURRENT`` stays 1.0.0-cc5.5 until F1 is installed (the
F1 hardware session's prepare / install / check / rollback run against it); build_nanod_cc5.py and
package_nanod_cc5.py take ``--release cc5.6`` meanwhile. ``rollback_nanod_cc5.py --to cc5.5 --binary D|F`` restores
cc5.5 D from the pre-cc5.6 backup (backups/nanod-cc5.5-before-cc5.6-*). The from-release fields that only the cc5.5
install can settle (its verified full image, whether it was finalized) are provisional in the profile and must be
set after that install (firmware/BUILD-cc5.6.md "Before the hardware session").
1.0.0-cc5.7 (profile ``PROFILES["cc5.7"]``; firmware/BUILD-cc5.7.md, HAPTICS.md; plan stages F2 and F3,
the r4 FEEL + SOUND job): the haptic token engine (control ``feel``, frame ``haptic``), the r4 walls, fold-back and self-spin trip,
the supply from the PD contract, the uint16 range fix, recalibration, the click sounds (control ``sound``) and the offline
system volume (HID Consumer report 4); capabilities feel, hapticFx, knobSound, offlineVolume and recalibration 1
(``Release(r4_feel=True)``). It upgrades cc5.6 binary F (installed 2026-09-30, never finalized: manifest.json stays the cc5.3
record), with the same ladder (D 16 ms, F 12 ms) and size gate; ``rollback_nanod_cc5.py --to cc5.6 --binary D|F`` restores
cc5.6 F from the pre-cc5.7 backup (backups/nanod-cc5.6-before-cc5.7-*). The desktop bundle is desktop-dist-v7-j (Desk Dial
7.3.2.0, every press ticks; rollback desktop-dist-v7-i, 7.3.1.0).
1.0.0-cc5.8 (profile ``PROFILES["cc5.8"]`` = ``NEWEST`` = ``CURRENT``; firmware/BUILD-cc5.8.md; the public v2.0.0 release
candidate, reported as 2.0.0+cc5.8.<binary>): the Phase 2 audit fixes and app profiles (the ``appProfile`` upload into a
RAM-only store; capabilities appProfiles 1, appProfileSlots 4, appProfileMaxBytes 32768, appProfileFeatures 31,
``Release(app_profiles=True)``). It upgrades cc5.7 binary F (image 93ff0d50..., 1,128,128 B, installed 2026-09-30, never
finalized: manifest.json stays the cc5.3 record), with the same ladder (D 16 ms, F 12 ms) and size gate;
``rollback_nanod_cc5.py --to cc5.7 --binary D|F`` restores cc5.7 F from the pre-cc5.8 backup
(backups/nanod-cc5.7-before-cc5.8-*). The desktop bundle is desktop-dist-v7-l (Desk Dial 7.4.1.0, ProductVersion 2.0.0;
rollback desktop-dist-v7-k, 7.4.0.0).
Profile paths are resolved from ``BACKUPS``, ``DIAGNOSTICS``, ``FIRMWARE_OUT`` and ``WORK``
when they are read.

Pure helpers (port matching, partition/OTA parsing, image assembly, art and media
packets, section 5 cover and icon payloads, diag margins, JPEG decode gates, reboot and
task-liveness checks, soak constants, evidence naming) are unit-tested in
``app/tests/test_cc5_tooling.py`` with fake inputs.

1.0.0-cc5.4 (profile ``PROFILES["cc5.4"]`` = ``NEWEST`` = ``CURRENT``, the combined cc5.4 +
desktop v7 release): presentation 5 and the alive capability, the ALIVE.md revision 2
section 11.9 and PRESENTATION_V5.md 12 / 15.4 device gates (ALIVE_DEVICE_GATES,
PRESENTATION5_DEVICE_GATES), their pure checks (LED idle / load / render, the LCD binary A..E and its
timings, ready ks, hold and deferred hold, lim per push, the memory gates of diag_margins(profile=)),
and the 12.4 build-only heap projection (heap_projection; build_nanod_cc5.py records it in the build
report and rejects a build below the 45,056 B projection). check_nanod_cc5.py runs them (its default
release is CURRENT); tools/nanod_alive_tour.py is the hands-on LED tour. The desktop bundle of this
release is desktop-dist-v7 (Desk Dial; rollback desktop-dist-v6, the last NanoD Control Center bundle).

The PRESENTATION_V5 12.6 build ladder (lead ruling R-m): 1.0.0-cc5.4 staged three binaries of the same
release for the one hardware window, A (the release candidate: the platformio.ini / lcd_thread.cpp
defaults), B (R5 off, 33 ms period) and C (no DMA, R5 off, 33 ms period); they differ only in
CC_LCD_DMA, CC_LCD_PERIOD_MS and CC_ART_ASYNC (BINARY_BUILD_FLAGS, passed as PLATFORMIO_BUILD_FLAGS
into their own build folder, never .pio/build). A was installed on 2026-09-26 and rolled back (a dark LCD:
tft.initDMA() with MOSI = MISO; flickering LEDs: the dither on at rest), so the ladder gained the fix binaries
D (A's pipeline + the fixes, the release candidate) and E (C's pipeline + the fixes, the fallback), each built
with CC_BUILD_BINARY (diag "build", image marker "cc-build-binary:<n>"). A, B and C are retired
(RETIRED_BINARIES): binary_choices() offers only ACTIVE_BINARIES (D, E) to build, package, prepare, install and
finalize, while rollback and check keep every binary. ``Release.binary_profile(name)`` returns binary A (the
profile itself: every cc5.4 name above is A's) or a variant for B .. E with its own image, source
archive, manifest (``firmware/nanod-control-center-1.0.0-cc5.4-D.bin``, ``manifest-1.0.0-cc5.4-D.json``),
build log and record, expected image, preparation, flash, rollback, installation and look-check evidence
(``diagnostics/cc5.4-D-*.json``). All share the release's pre-install backup pair and its backup
record, the step-down base record, and the release's device and lease check records (check_nanod_cc5.py records
the binary diag reports; finalize_nanod_cc5.py --binary requires it). The build-only LCD data-line gate
(tft_spi_config, lcd_mosi_gate) refuses a DMA build whose effective TFT_MISO equals TFT_MOSI without the MOSI
re-attach, or whose LcdThread::run() does not call it right after tft.initDMA() and before startWrite
(lcd_run_call_order, a read-only objdump of firmware.elf); lcd_mosi_problems and look_check_problems read diag lcdMosiSig (103 good, 102 A's defect) on the knob.
``all_profiles()`` lists every profile and binary
for the scans that must see all of them (backup locks, write evidence, rollback traces). A step-down whose
rollback left data-region drift (a core dump, settings) installs the next binary from the release's step-down
base (``load_step_down_base``: a later verified read whose critical regions equal the locked backup, kept under
its own name; the locked backup is never replaced). Every binary's build record carries the 12.4 heap
projection with sizeof(CCFrame) and the ALIVE instance size from firmware.elf (``v5_size_record``).

The flash interlock (``companion_running``, ``require_companion_quit``) knows both companion images,
DeskDial.exe (Desk Dial, desktop v7 on) and NanoDControlCenter.exe (v2-v6, the rollback bundles), and
both startup tasks.

Knob prompts (user ruling 2026-09-26: no audio cues, no chat prompts; the knob's own screen tells the operator what
to do and moves on only once the device events show it was done): ``KnobPrompter`` drives a RawKnob the caller
opened with host frames (``prompt_frame``, a notice screen; ``overlay``, the same instruction on any other layout),
starts every flow with the display check ("Can you see this? Press Button 4"), gates each step on its events with a
long safety timeout only (``OperatorTimeout`` exit 4, ``ScreenNotConfirmed`` exit 5, never a firmware failure), and
answers Yes/No on knob buttons. ``TurnMeter``, ``EndStopWindows`` and ``DeferredPlanner`` are the pure helpers of the
turning, End stop and deferred-hold steps; the gate functions they feed are unchanged. Nothing here beeps.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import re
import statistics
import struct
import subprocess
import sys
import threading
import time
import zlib

# ---------------------------------------------------------------------------
# Paths

WORK = Path(__file__).resolve().parent
ROOT = WORK.parent
APP = ROOT / "app"
BACKUPS = APP / "backups"
DIAGNOSTICS = APP / "diagnostics"
FIRMWARE_OUT = APP / "firmware"
FIXTURES = APP / "tests" / "fixtures"
FIRMWARE_SOURCE = ROOT / "firmware"
FLASH_VENV = WORK / "nanod-flash-venv"
PIO_VENV = WORK / "nanod-pio-venv"
# PlatformIO core dir (toolchains, packages): NANOD_PIO_CORE, else PLATFORMIO_CORE_DIR, else PlatformIO's
# default ~/.platformio (same order as harness/cpp11_gate.py).
PIO_CORE = Path(os.environ.get("NANOD_PIO_CORE") or os.environ.get("PLATFORMIO_CORE_DIR")
                or Path.home() / ".platformio")
PIO_ENV = "nanofoc_d"
BUILT_IMAGE = FIRMWARE_SOURCE / ".pio" / "build" / PIO_ENV / "firmware.bin"

# ---------------------------------------------------------------------------
# Device identity (RECOVERY.md). Ports are always discovered, never assumed.

APP_VID, APP_PID, APP_SERIAL = 0x239A, 0x8010, "NANO_D"   # serial compared case-insensitively
ROM_VID, ROM_PID = 0x303A, 0x1001                          # ESP32-S3 ROM USB-Serial/JTAG
# The ROM port reports the chip MAC as its USB serial number. Set NANOD_CHIP_MAC to your knob's MAC
# (esptool flash_id prints it); the placeholder never matches a real chip, so nothing is flashed.
CHIP_MAC_PLACEHOLDER = "12:34:56:78:9A:BC"
CHIP_MAC = os.environ.get("NANOD_CHIP_MAC", "").strip() or CHIP_MAC_PLACEHOLDER
ESPTOOL_VERSION = "4.12.0"
# The companion owns the knob's application port while it runs. Desk Dial (desktop v7 on) runs as
# DeskDial.exe from the task 'Desk Dial'; the v2-v6 bundles (the rollback targets) as
# NanoDControlCenter.exe from the task 'NanoD Control Center'. The interlock checks both images, since
# either one may be installed (a desktop rollback, or the rename not yet installed).
COMPANION_IMAGES = ("DeskDial.exe", "NanoDControlCenter.exe")
COMPANION_TASKS = ("Desk Dial", "NanoD Control Center")
COMPANION_IMAGE = " or ".join(COMPANION_IMAGES)       # for messages only (nanod_enter_bootloader_v2.py)

# ---------------------------------------------------------------------------
# Flash layout (backups/nanod-original-manifest.json)

FLASH_BYTES = 0x400000
SECTOR = 0x1000
PARTITION_TABLE_OFFSET, PARTITION_TABLE_SIZE = 0x8000, 0x1000
OTADATA_OFFSET, OTADATA_SIZE = 0xE000, 0x2000
APP_OFFSET, APP_SIZE = 0x10000, 0x140000
ESP_IMAGE_MAGIC = 0xE9

# ---------------------------------------------------------------------------
# Releases and files

CC4_VERSION = "1.0.0-cc4"


def release_image(version):
    return FIRMWARE_OUT / f"nanod-control-center-{version}.bin"


def release_source_zip(version):
    return FIRMWARE_OUT / f"nanod-control-center-{version}-source.zip"


def release_manifest(version):
    return FIRMWARE_OUT / f"manifest-{version}.json"


CC4_IMAGE = release_image(CC4_VERSION)
CC4_IMAGE_SHA256 = "89ddf172ffa43bf3e3721868ab5a0d502f906460b5caaa72b15ba67c793be737"
CC4_IMAGE_BYTES = 927088
CC4_MANIFEST = FIRMWARE_OUT / "manifest-cc4.json"
ACTIVE_MANIFEST = FIRMWARE_OUT / "manifest.json"
ORIGINAL_MANIFEST = BACKUPS / "nanod-original-manifest.json"
ORIGINAL_PARTITIONS = BACKUPS / "nanod-original-partitions.bin"
CC4_EXPECTED_FULL = BACKUPS / "nanod-cc4-expected-full.bin"      # what the cc4 install verified
# Every ROM bootloader entry (nanod_enter_bootloader_v2.py) of every cc5.x window: one shared
# name, timestamped when taken, so finalize sees an entry after any install.
BOOT_ENTRY = DIAGNOSTICS / "cc5-usb-boot-entry.json"

# The check_nanod_cc5.py "gates" object. cc5.2's ten, then the artwork2 gates of 1.0.0-cc5.3
# (ARTWORK2.md section 10). finalize_nanod_cc5.py requires every gate of its profile.
CC52_DEVICE_GATES = ("stressUntouched", "stressTurn", "turningDetected", "noRebootOrReenumeration",
                     "rebootFieldsReported", "coredumpBlank", "rxQueueInternal", "diagMargins",
                     "taskLiveness", "unattendedSoak")
ARTWORK2_DEVICE_GATES = ("artwork2Capability", "bridgeArtwork2", "v1ArtCompatible", "mediaRoundTrip",
                         "mediaPrefetch", "mediaPinning", "mediaErrorStrings", "unpacedTransferTiming",
                         "jpegDecode")


class Release:
    """One upgrade profile: the release installed, the release it replaces, and every file
    the build, package, backup, prepare, install, check, rollback and finalize steps use.

    Paths are properties resolved from the module's BACKUPS, DIAGNOSTICS, FIRMWARE_OUT and WORK
    at the moment they are read. Two profiles never share an evidence or backup file name.

    A release built as the PRESENTATION_V5 12.6 ladder (``ladder=True``: 1.0.0-cc5.4) is binary A
    itself (``binary`` "A"); ``binary_profile("B")`` .. ``("E")`` are its variants (``binary_variant``),
    which keep the release's version, backup pair, backup record and device / lease check records
    and name everything else after the binary (``artifact_version`` 1.0.0-cc5.4-D, ``prefix``
    cc5.4-D, ``file_tag`` cc5.4-D). A release without the ladder has ``binary`` None. A release with its
    own ladder (``ladder=("D", "F")``: 1.0.0-cc5.5) is none of its binaries itself (``binary`` None, the
    release's names are never built or written); every binary is a variant with the binary's names.

    ``from_binary`` names the binary of a ladder from-release that is installed (cc5.5: "D"), so the from
    image and manifest are that binary's (``from_artifact_version`` 1.0.0-cc5.4-D). ``from_finalized=False``
    marks a from-release that was installed but never finalized: manifest.json still holds the record its
    install left in force (``from_active_record``, which ``restore_record`` names and a rollback restores),
    and its install record (``from_install_record``, the binary's flash-checks record) is the evidence that
    it runs on the knob (tooling.from_install_problems).
    """

    alive = False                   # the release reports the ALIVE capability (AliveRelease)

    def __init__(self, version, *, from_version, from_image_sha256, from_image_bytes, from_presentation,
                 prefix, backup_stem, from_record, from_expected, from_expected_sha256, from_preparation,
                 backup_family, superseded, gates, from_token, desktop_bundle, desktop_rollback_bundle,
                 gate_patterns, validation_key, artwork2, presentation=4, heap_min_free=None, lvgl_min_free=None,
                 ladder=False, from_binary=None, from_finalized=True, from_active_record=None,
                 from_install_record=None, image_size_gate=None, app_canvas=False, r4_feel=False,
                 app_profiles=False):
        self.version, self.tag = version, version.split("-", 2)[-1]           # "1.0.0-cc5.3", "cc5.3"
        # The build ladder (PRESENTATION_V5 12.6): ladder=True (1.0.0-cc5.4) stages PIPELINE_BINARIES and this
        # profile is binary A; a tuple (1.0.0-cc5.5: ("D", "F")) stages those, and this profile is none of them.
        self.ladder = tuple(PIPELINE_BINARIES) if ladder is True else tuple(ladder or ())
        self.binary = PIPELINE_BINARIES[0] if ladder is True else None
        self.base, self._variants = self, {}
        # Names: A (and a release without the ladder) use the release's own; a variant replaces these.
        self.artifact_version, self.file_tag = version, self.tag
        self.release_prefix = prefix                        # names shared by every binary (backup, checks)
        self.presentation = presentation                    # capabilities.presentation this release reports
        # diag gates (check_nanod_cc5.py "diag"): None keeps the module defaults (HEAP_MIN_FREE_BYTES,
        # LVGL_MIN_FREE_FRACTION of PRE_V5_LVGL_HEAP_BYTES); 1.0.0-cc5.4 sets its own (PRESENTATION_V5 12.2).
        self.heap_min_free, self.lvgl_min_free = heap_min_free, lvgl_min_free
        self.from_version, self.from_tag = from_version, from_version.split("-", 2)[-1]
        # The installed binary of a ladder from-release (1.0.0-cc5.5 upgrades cc5.4's binary D), else None.
        self.from_binary = from_binary
        self.from_artifact_version = f"{from_version}-{from_binary}" if from_binary else from_version
        # False: the from-release was installed but never finalized (tooling.from_install_problems).
        self.from_finalized = from_finalized
        self.from_active_record_name = from_active_record     # firmware/: manifest.json while it runs
        self.from_install_record_name = from_install_record   # diagnostics/: its install (flash-checks) record
        self.image_size_gate = image_size_gate                # build acceptance: image bytes at most this
        self.from_image_sha256, self.from_image_bytes = from_image_sha256, from_image_bytes
        self.from_presentation = from_presentation          # presentation the before-inventory reports
        self.prefix = prefix                                # evidence names: diagnostics/<prefix>-*.json
        self.backup_stem = backup_stem                      # backups/<stem>-full.bin, <stem>-active-app.bin
        self.from_record_name = from_record                 # firmware/: the installed record of the from-release
        self.from_expected_name = from_expected             # backups/: the image the from-release install verified
        self.from_expected_sha256 = from_expected_sha256
        self.from_preparation_name = from_preparation       # diagnostics/: that install's preparation record
        self.backup_family = tuple(backup_family)           # manifests whose installs share this backup pair
        self.superseded = tuple(superseded)                 # earlier releases package marks SUPERSEDED
        self.gates = tuple(gates)                           # check_nanod_cc5.py gates finalize requires
        self.from_token = from_token                        # install outcomes RESTORED_<token>_...
        self.desktop_bundle, self.desktop_rollback_bundle = desktop_bundle, desktop_rollback_bundle
        self.gate_patterns = tuple(gate_patterns)           # diagnostics/ gate evidence recorded at packaging
        self.validation_key = validation_key                # key in diagnostics/validation.json
        self.artwork2 = artwork2                            # the release reports the artwork2 capability
        self.app_canvas = app_canvas                        # the release reports appCanvas 1 (A2, 1.0.0-cc5.6)
        self.r4_feel = r4_feel                              # feel, hapticFx, knobSound, offlineVolume, recalibration 1 (cc5.7)
        self.app_profiles = app_profiles                    # appProfiles 1 and its three sizes (cc5.8, APP_PROFILES.md 7)

    def __repr__(self):
        which = "" if self.is_base else f" binary {self.binary}"
        return f"Release({self.from_version} -> {self.version}{which})"

    # The profile carries the release's own names (binary A of 1.0.0-cc5.4, a release without the ladder,
    # and the never-built release profile of 1.0.0-cc5.5); every variant carries its binary's.
    is_base = property(lambda self: self is self.base)

    # The build ladder (PRESENTATION_V5 12.6)
    def pipeline_binaries(self):
        """Every binary this release ever staged (1.0.0-cc5.4: "A" .. "E", PIPELINE_BINARIES, the retired ones
        included; 1.0.0-cc5.5: "D", "F"), or () without the build ladder. binary_choices() gives the ones a
        script may still build or install."""
        return self.base.ladder

    def binary_profile(self, name=None):
        """This release as binary `name`: A (or None) is the release profile itself, B .. E are its
        variants (created once). Raises ValueError for a binary the release does not stage."""
        base = self.base
        if name is None or name == base.binary:
            return base
        if name not in base.pipeline_binaries():
            raise ValueError(f"{base.version} stages no binary {name!r} (binaries: {base.pipeline_binaries() or 'none'})")
        if name not in base._variants:
            base._variants[name] = binary_variant(base, name)
        return base._variants[name]

    def variants(self):
        """Every binary of this release (A .. E), or [the release] without the ladder."""
        return [self.base.binary_profile(name) for name in self.base.pipeline_binaries()] or [self.base]

    label = property(lambda self: self.tag if self.is_base else f"{self.tag} binary {self.binary}")
    build_flags = property(lambda self: BINARY_BUILD_FLAGS.get(self.binary, ()))
    pipeline = property(lambda self: dict(LCD_BINARIES[self.binary]) if self.binary else None)
    # CC_BUILD_BINARY of this binary's flags (D 4, E 5), None for a binary built without it (A, B, C): diag reports
    # build <letter> and the image holds "cc-build-binary:<n>" exactly when it is set.
    build_number = property(lambda self: binary_build_number(self.binary))
    # PlatformIO build folder: None is the project's own .pio/build (binary A and earlier releases);
    # B .. E build into .pio/build-<file tag> (PLATFORMIO_BUILD_DIR), never over binary A.
    build_dir = property(lambda self: None if self.is_base else FIRMWARE_SOURCE / ".pio" / f"build-{self.file_tag}")
    built_image = property(lambda self: BUILT_IMAGE if self.build_dir is None
                           else self.build_dir / PIO_ENV / "firmware.bin")
    built_elf = property(lambda self: self.built_image.with_name("firmware.elf"))

    # Release files (firmware/, work/)
    image = property(lambda self: release_image(self.artifact_version))
    source_zip = property(lambda self: release_source_zip(self.artifact_version))
    manifest = property(lambda self: release_manifest(self.artifact_version))
    build_log = property(lambda self: WORK / f"nanod-{self.file_tag}-build.log")
    from_image = property(lambda self: release_image(self.from_artifact_version))
    from_manifest = property(lambda self: release_manifest(self.from_artifact_version))
    from_record = property(lambda self: FIRMWARE_OUT / self.from_record_name)
    # The record manifest.json holds while the from-release runs, which a rollback to it restores: its
    # installed record, or for a from-release never finalized the record its install left in force.
    restore_record = property(lambda self: self.from_record if self.from_finalized
                              else FIRMWARE_OUT / self.from_active_record_name)
    from_install_record = property(lambda self: None if self.from_install_record_name is None
                                   else DIAGNOSTICS / self.from_install_record_name)
    # Locked pre-install backup pair and the prepared image (backups/)
    before_full = property(lambda self: BACKUPS / f"{self.backup_stem}-full.bin")
    rollback_app = property(lambda self: BACKUPS / f"{self.backup_stem}-active-app.bin")
    # What the pair is called: "pre-cc5 backup" (nanod-cc4-before-cc5, shared by every cc5.x install
    # from cc4), "pre-cc5.3 backup" (nanod-cc5.2-before-cc5.3).
    backup_role = property(lambda self: f"pre-{self.backup_stem.split('-before-', 1)[-1]} backup")
    expected_full = property(lambda self: BACKUPS / f"nanod-{self.file_tag}-expected-full.bin")
    from_expected_full = property(lambda self: BACKUPS / self.from_expected_name)
    from_preparation = property(lambda self: DIAGNOSTICS / self.from_preparation_name)

    def evidence(self, name):
        return DIAGNOSTICS / f"{self.prefix}-{name}.json"

    build_report = property(lambda self: self.evidence("build"))
    # One pre-install backup serves every binary of a release: its record keeps the release's name.
    backup_report = property(lambda self: DIAGNOSTICS / f"{self.release_prefix}-backup.json")
    preparation = property(lambda self: self.evidence("preparation"))
    flash_checks = property(lambda self: self.evidence("flash-checks"))
    # check_nanod_cc5.py and check_nanod_cc5_lease.py write the release's names; the device checks record
    # the binary diag reports, and finalize ties both to the binary's install by time.
    device_checks = property(lambda self: DIAGNOSTICS / f"{self.release_prefix}-device-checks.json")
    lease_checks = property(lambda self: DIAGNOSTICS / f"{self.release_prefix}-lease-checks.json")
    rollback_report = property(lambda self: self.evidence("rollback"))
    installation = property(lambda self: self.evidence("installation"))
    # check_nanod_cc5_look.py (the short look session after a fix binary's install): diagnostics/<prefix>-look-checks.json.
    look_checks = property(lambda self: self.evidence("look-checks"))

    # Esptool log prefixes (diagnostics/<prefix>-<step>.log) and work folders
    install_log_prefix = property(lambda self: self.prefix)
    backup_log_prefix = property(lambda self: f"{self.release_prefix}-backup")
    rollback_log_prefix = property(lambda self: f"{self.prefix}-rollback")

    def rollback_workdir(self, stamp):
        return BACKUPS / f"{self.prefix}-rollback-{stamp}"

    def manifest_before_rollback(self, stamp):
        return FIRMWARE_OUT / f"manifest-at-{self.prefix}-rollback-{stamp}.json"

    def backup_read_partial(self, stamp):
        return BACKUPS / f"{self.release_prefix}-backup-read-{stamp}.bin.partial"

    def confirm_read(self, stamp):
        return BACKUPS / f"nanod-{self.from_tag}-confirm-read-{stamp}.bin"

    # A step-down (PRESENTATION_V5 12.6) after a verified rollback whose data regions drifted (a core dump,
    # settings): backup_nanod_cc5.py --step-down keeps a fresh read whose critical regions equal the locked
    # backup under its own name, with one record for the release (every binary installs from it); the locked
    # pre-install backup and its record are never replaced (load_step_down_base).
    def step_down_base(self, stamp):
        return BACKUPS / f"nanod-{self.from_tag}-step-down-base-{stamp}.bin"

    step_down_report = property(lambda self: DIAGNOSTICS / f"{self.release_prefix}-step-down-base.json")

    def rollback_trace_patterns(self):
        """(folder name, glob, meaning) of what a rollback of this profile leaves besides its record."""
        return (("FIRMWARE_OUT", f"manifest-at-{self.prefix}-rollback-*.json",
                 "a rollback restored manifest.json"),
                ("BACKUPS", f"{self.prefix}-manual-rollback-*",
                 "a manual rollback (RECOVERY.md, manual block 1) was started"),
                ("BACKUPS", f"{self.prefix}-rollback-*", "rollback_nanod_cc5.py ran against the device"),
                ("DIAGNOSTICS", f"{self.prefix}-rollback-*.log", "rollback_nanod_cc5.py ran esptool"))

    # Outcomes of install_nanod_cc5.py (exit codes 3 and 6 restore the from-release)
    restored_outcome = property(lambda self: f"RESTORED_{self.from_token}_RESET")
    restored_unconfirmed_outcome = property(lambda self: f"RESTORED_{self.from_token}_VERIFIED_RESET_UNCONFIRMED")

    def expected_capabilities(self):
        caps = {"controlCenter": 1, "presentation": self.presentation, "glyphs": "latin-ext-a", "diag": 1,
                "artwork": dict(EXPECTED_ARTWORK_CAPABILITY)}
        if self.artwork2:
            caps["artwork2"] = artwork2_capability()
        if self.app_canvas:
            caps["appCanvas"] = 1
        if self.r4_feel:
            caps.update({name: 1 for name in R4_FEEL_CAPABILITIES})
        if self.app_profiles:
            caps.update(APP_PROFILE_CAPABILITIES)
        return caps


# "Warm · alive" LEDs (1.0.0-cc5.4, firmware/ALIVE.md). The capability key and version
# are the companion's own constants (presentation.ALIVE_CAPABILITY, ALIVE_VERSION), loaded by path
# like ARTWORK2_CAPABILITY; fps is the knob's render cadence and drive its effective default drive,
# min(150, ledMaxBrightness) (ALIVE.md sections 1 and 9): 150 with the default ledMaxBrightness.
ALIVE_FPS = 60
ALIVE_DEFAULT_DRIVE = 150
# The hardware checks of ALIVE.md (revision 2) section 11.9, as check_nanod_cc5.py reports them for
# 1.0.0-cc5.4 (finalize_nanod_cc5.py requires every gate of the profile): the alive capability;
# diag ledFps >= 58 and ledShowGapMsMax <= 20 at idle; ledFps >= 45 during cover transfers (55 is
# recorded as the target, not gated: it needs R7, not in cc5.4); ledRenderUsMax <= 3000; lim events
# in the turning test, at both ends of the stress control and at 0:00 / T_end of a Seek control;
# ruling Q1 (12.5): one lim per push into a bound, repeated pushes included, one while held against
# it, none from attractor chatter (lim_rearm_ms is tuned by hand in this test and recorded); and no
# error replies in the stress test.
ALIVE_DEVICE_GATES = ("aliveCapability", "ledFrameRate", "ledRenderTime", "limitEvents", "limitPerPush",
                      "noErrorReplies")
ALIVE_LED_FPS_IDLE_MIN = 58
ALIVE_LED_SHOW_GAP_IDLE_MAX_MS = 20
ALIVE_LED_FPS_TRANSFER_MIN = 45
ALIVE_LED_FPS_TRANSFER_TARGET = 55          # recorded, not gated (ALIVE.md 11.9)
ALIVE_LED_RENDER_US_MAX = 3000
ALIVE_LIM_GAP_S = 0.15                      # the firmware spaces lim events >= 150 ms (ALIVE.md 3)
ALIVE_LIM_REARM_MS = 75                     # Q1 starting value; tuned in the hardware turning test (40..150)
ALIVE_DIAG_FIELDS = ("ledFps", "ledRenderUsMax", "ledRenderUsAvg", "ledMode", "ledShowGapMsMax", "ledLateShows")
# PRESENTATION_V5.md (1.0.0-cc5.4) device gates (15.4, 12.2, 12.6, 11): capabilities presentation 5;
# `ks` in every ready line; one `kh` per hold of Button 1 (none for the others) and one deferred `kh`
# after a ready; F24 only from the Home `win` slot (`hid:1`), never from Button 4 outside Home; the LCD
# timings of the binary in use (lcd_binary: diag build on D and E, else lcdDma / lcdPeriodMs / artAsync).
PRESENTATION5_DEVICE_GATES = ("presentation5Capability", "readyKeyState", "holdEvents", "holdDeferred",
                              "hidIconGate", "lcdTimings")
# PRESENTATION_V5 12.2 / 12.4 memory gates (the device figures are the release gates).
V5_HEAP_MIN_FREE_BYTES = 40960              # heapMinFree >= 40 KB
V5_LVGL_MIN_FREE_BYTES = 30 * 1024          # lvglMinFree >= 30 KB with the text-shadow twins
V5_STACK_ART_DEC_MIN_BYTES = 1024           # stackArtDec (the binaries with artAsync: A, D)
V5_ENTER_MS_MAX = 250                       # enterMsMax: reported; above it, investigate before release
# 12.4 build-only projection (before the hardware window): 57,072 B measured on cc5.3 minus the static
# growth over cc5.3's 245,056 B, the 1,400 B frame's JSON document (1,024 B) and the run-time heap H of
# new cc5.4 code outside .bss (the SPI DMA descriptors, ~512 B, the DMA binaries A, B and D).
CC53_RAM_USED_BYTES = 245056
CC53_HEAP_MIN_FREE_BYTES = 57072
V5_JSON_DOC_BYTES = 1024
V5_DMA_DESCRIPTOR_BYTES = 512
V5_HEAP_PROJECTION_MIN_BYTES = 45056        # 40 KB + 4 KB for estimate error
# LCD timing targets per binary (12.2, 12.6): lcdFpsAnimMin on opaque-cover slides / on blended frames
# (art show/hide). B and C: >= 28 on both; lcdLateRefrs 0 outside cover arrivals on every binary. The fix
# binaries run their parent's pipeline and keep its targets: D is A's (55 / 45; it cannot pass them before the
# later performance task, lcdFpsAnimMin measured 12-16 on A's pipeline), E is C's (28 / 28).
# 1.0.0-cc5.5 adds F: D's pipeline with CC_LCD_PERIOD_MS 12 (the speed candidate; its targets are D's).
LCD_BINARIES = {"A": {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True},
                "B": {"lcdDma": True, "lcdPeriodMs": 33, "artAsync": False},
                "C": {"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False},
                "D": {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True},
                "E": {"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False},
                "F": {"lcdDma": True, "lcdPeriodMs": 12, "artAsync": True}}
LCD_FPS_TARGETS = {"A": {"opaque": 55, "blended": 45}, "B": {"opaque": 28, "blended": 28},
                   "C": {"opaque": 28, "blended": 28}, "D": {"opaque": 55, "blended": 45},
                   "E": {"opaque": 28, "blended": 28}, "F": {"opaque": 55, "blended": 45}}
LCD_DIAG_FIELDS = ("lcdFps", "lcdFpsAnimMin", "lcdRefrUsMax", "lcdRefrUsAvg", "lcdRenderUsMax", "lcdFlushUs",
                   "lcdPxPerRefr", "lcdFullRefrs", "lcdLateRefrs", "lcdMaxGapMs", "lcdBusyPct", "core0IdlePct",
                   "lcdSpiHz", "enterMsLast", "enterMsMax", "holdEvents", "holdDeferred", "lcdDma", "lcdPeriodMs",
                   "artAsync", "artDecodeRequests", "artDecodeAborts", "artDecodeStale", "stackArtDec")
# The fix binaries' diag fields (D and E: the LCD data line's output signal and the binary's letter). Kept apart from
# LCD_DIAG_FIELDS, which the companion's control_center/device.py DIAG_LCD_FIELDS mirrors (tests/test_cc_device_diag.py);
# the companion ignores unknown diag fields, so Desk Dial v7 needs no change. lcd_diag_summary records both tuples.
LCD_FIX_DIAG_FIELDS = ("lcdMosiSig", "build")
# 1.0.0-cc5.5 (F1, cc_diag.h): the FOC loop (focLoopHz; focLoopUsMax, the longest pass-to-pass gap in us, reset
# on read), the q-axis voltage (uqAbsMax, the largest |Uq| in mV, reset on read; uqCapMs, ms at the motor cap since
# boot; uqCapMv, that cap: 2200), the PD contract read once at boot (pdRead; pdPdo, the requested source PDO's
# position, 0 = none or unknown; pdVolts, its voltage from the knob's sink PDO table, 0 = unknown; pdRdo, the raw
# RDO), the USB interfaces TinyUSB accepted (usbMidiOk, usbHidOk) and the HID reports retried (hidRetries). The
# companion's control_center/device.py DIAG_F1_FIELDS is the same tuple (tests/test_cc_device_f1.py).
F1_DIAG_FIELDS = ("focLoopHz", "focLoopUsMax", "uqAbsMax", "uqCapMs", "uqCapMv", "pdRead", "pdPdo", "pdVolts",
                  "pdRdo", "usbMidiOk", "usbHidOk", "hidRetries")
# The Step 0 / F1 comparison read (plan "Step 0: measure"): reset attribution and the LCD, LED, LVGL and core 0
# figures recorded next to the F1 fields (f1_diag_summary; check_nanod_cc5_look.py prints them).
STEP0_DIAG_FIELDS = ("resetReason", "rtcReset", "lcdRefrUsAvg", "lcdRefrUsMax", "lcdFps", "ledLateShows",
                     "lvglMinFree", "core0IdlePct")
HOLD_MS = 600                               # kh: long press of Button 1 (PRESENTATION_V5 11.2)
HOLD_ARRIVAL_S = (0.45, 1.2)                # kd -> kh as the host sees it (600 ms + debounce + 10 ms pass + USB)
# PRESENTATION_V5 12.6 build ladder (P5-R23; lead ruling R-m): the binaries of 1.0.0-cc5.4, oldest-risk first. A is
# the first release candidate and builds with the source defaults (lcd_thread.cpp: CC_LCD_DMA 1, CC_LCD_PERIOD_MS
# 16, CC_ART_ASYNC 1); every other binary adds its flags (PLATFORMIO_BUILD_FLAGS, which PlatformIO appends to
# platformio.ini's build_flags) and builds into its own folder. B and C carry the flags the phase-2b gatekeeper
# built them with.
#
# The fix binaries D and E (2026-09-26, after A's rollback; firmware/BUILD-cc5.4.md "Fix binaries D and E"): A's
# LCD stayed dark in every mode. platformio.ini sets TFT_MOSI 4 and TFT_MISO -1, TFT_eSPI_ESP32_S3.h 340-342 turns
# that into TFT_MISO = TFT_MOSI = 4 on the S3's FSPI port, and tft.initDMA() (lcd_thread.cpp) then initializes the
# SPI bus with mosi = miso = 4: IDF routes GPIO4 out to FSPID (103) and the MISO step re-routes it to FSPIQ_OUT
# (102), so no command or pixel reaches the GC9A01. The LEDs flickered: the ALIVE output stage's temporal dither was
# on by default at the 0-3 count levels of rest and offline. D is A's pipeline (the source defaults) and E is C's
# (no DMA, 33 ms, no ArtDecode), both with the fixes: the MOSI re-attach after initDMA (cc_lcd_mosi_reattach, in
# every DMA build), diag lcdMosiSig (GPIO4's output signal: 103 good, 102 A's defect) and diag build (the binary's
# letter), and the LED dither off by default with the minimum brightness floor (ALIVE.md 9, user ruling
# 2026-09-26). Each carries CC_BUILD_BINARY = its ladder index (A..E = 1..5; BINARY_BUILD_NUMBERS), numeric so no
# quoting is needed in PLATFORMIO_BUILD_FLAGS; the image holds the marker "cc-build-binary:<n>" and diag reports
# "build": "<letter>". The version string stays 1.0.0-cc5.4: D and E are told apart by their artifact names, the
# diag build field and the image marker.
PIPELINE_BINARIES = ("A", "B", "C", "D", "E")
# 1.0.0-cc5.5's own ladder (F1): D (the release candidate, cc5.4 D's pipeline at 16 ms) and F (the same at 12 ms,
# CC_BUILD_BINARY 6). Every letter of every ladder, in CC_BUILD_BINARY order (A..F = 1..6).
CC55_LADDER = ("D", "F")
ALL_BINARIES = ("A", "B", "C", "D", "E", "F")
# The binaries build, package, prepare, install and finalize accept (binary_choices; the first of the current
# release's ladder that is active is the default). rollback_nanod_cc5.py and check_nanod_cc5.py keep every binary
# of the ladder, so any binary ever written can be rolled back and checked.
ACTIVE_BINARIES = ("D", "E", "F")
RETIRED_BINARIES = {
    "A": ("rolled back 2026-09-26 (diagnostics/cc5.4-rollback.json): the LCD stayed dark in every mode because "
          "tft.initDMA() initializes the SPI bus with MOSI = MISO = GPIO4 and re-routes GPIO4 to FSPIQ_OUT (102); "
          "the LEDs flickered (temporal dither on by default at rest). Superseded by D"),
    "B": "the same DMA defect as A (initDMA with MOSI = MISO); never flashed. Superseded by D and E",
    "C": "superseded by E (C's pipeline with the fixes); never flashed",
}
BINARY_BUILD_FLAGS = {"A": (),
                      "B": ("-DCC_LCD_PERIOD_MS=33", "-DCC_ART_ASYNC=0"),
                      "C": ("-DCC_LCD_DMA=0", "-DCC_LCD_PERIOD_MS=33", "-DCC_ART_ASYNC=0"),
                      "D": ("-DCC_BUILD_BINARY=4",),
                      "E": ("-DCC_LCD_DMA=0", "-DCC_LCD_PERIOD_MS=33", "-DCC_ART_ASYNC=0", "-DCC_BUILD_BINARY=5"),
                      "F": ("-DCC_LCD_PERIOD_MS=12", "-DCC_BUILD_BINARY=6")}
# CC_BUILD_BINARY (the firmware's #error outside 0..6; 0, the default, omits diag "build"): the ladder index.
BINARY_BUILD_NUMBERS = {name: index for index, name in enumerate(ALL_BINARIES, 1)}
BINARY_ROLES = {"A": "release candidate", "B": "middle", "C": "fallback",
                "D": "release candidate (A + fixes)", "E": "fallback (C + fixes)",
                "F": "speed candidate (D at a 12 ms LCD period)"}
# What each binary removes against the one above it (12.6 "Stepping down removes one risk class at a time").
BINARY_STEP_DOWN = {"B": "the scheduling changes: the 16 ms period (R4) and the ArtDecode task (R5)",
                    "C": "the DMA driver (R3): cc5.3's single blocking 11,520 B draw buffer",
                    "E": ("the DMA driver (R3), the 16 ms period (R4) and the ArtDecode task (R5): C's pipeline, "
                          "cc5.3's single blocking 11,520 B draw buffer")}
# What the fix binaries change against their parent (manifest binary.fixes; the render path is otherwise unchanged).
BINARY_FIXES = {
    name: ("the LCD MOSI re-attach after tft.initDMA() (cc_lcd_mosi_reattach, DMA builds), diag lcdMosiSig and "
           "build, the perfWindow stack scan outside the perfLock critical section, and the ALIVE LED output with "
           "the temporal dither off by default plus the minimum brightness floor (ALIVE.md 9; user ruling "
           "2026-09-26)")
    for name in ("D", "E")}
BINARY_FIXES["F"] = ("D's pipeline and fixes with the LVGL refresh and animation period at 12 ms instead of 16 ms "
                     "(CC_LCD_PERIOD_MS 12; plan F1: D and F are compared on diag lcdFps, F4 adopts F if healthy)")
BINARY_PARENTS = {"D": "A", "E": "C", "F": "D"}
# Build-only evidence of the compiled pipeline (the period, R4, is not visible in the image; diag lcdPeriodMs
# reports it on the device): R5 is in the image exactly when it holds the decode task's name (VOC-K1f,
# cc_art_decode.cpp xTaskCreateStaticPinnedToCore(run, "ArtDecode", ...)); R3 exactly when the ELF links the
# second draw buffer (lcd_thread.cpp `draw_buf2`, under #if CC_LCD_DMA).
# The flash size gate (plan "Cross-cutting rules"; 1.0.0-cc5.5 build acceptance, Release.image_size_gate): the
# image may use at most 95 % of app0 (1,310,720 B), in bytes.
IMAGE_SIZE_GATE_BYTES = 1245184
# 1.0.0-cc5.7 (r4 FEEL + SOUND, plan F2 / F3): the capabilities the release adds (each an int 1; firmware HAPTICS.md).
# knobVolume (control soundVolume 0..100) joined cc5.7 on 2026-09-30, before the release was finalized.
R4_FEEL_CAPABILITIES = ("feel", "hapticFx", "knobSound", "offlineVolume", "recalibration", "knobVolume")
# 1.0.0-cc5.8 (app profiles, APP_PROFILES.md section 7; control_center.cpp, after knobVolume): the appProfile upload into
# the RAM-only store. Slots CC_APP_STORE_SLOTS (cc_app_store.h), wire bytes CC_APP_WIRE_MAX_BYTES (cc_app_store.h),
# features CC_APP_FEATURES_SUPPORTED (cc_app_profile.h: the five feature bits, 0x1F).
APP_PROFILE_CAPABILITIES = {"appProfiles": 1, "appProfileSlots": 4, "appProfileMaxBytes": 32768,
                            "appProfileFeatures": 0x1F}
R5_IMAGE_MARKER = b"ArtDecode"
R3_ELF_SYMBOL = "draw_buf2"
# A numbered binary (CC_BUILD_BINARY n, D and E) carries "cc-build-binary:<n>" in its image (the firmware reads the
# string to fill diag build, so --gc-sections keeps it); binary_image_problems requires exactly its own number.
BUILD_MARKER_PREFIX = b"cc-build-binary:"
# The LCD data line (PRESENTATION_V5 12.6 fix binaries). diag lcdMosiSig is GPIO<TFT_MOSI>'s output signal select
# (GPIO_FUNCn_OUT_SEL_CFG[8:0]): FSPID_OUT_IDX 103 drives the panel; FSPIQ_OUT_IDX 102 is binary A's defect (initDMA
# with MOSI = MISO re-routed the pin to the MISO output). Every DMA build whose effective TFT_MISO equals TFT_MOSI must
# link the re-attach (lcd_mosi_gate); the encoder owns HSPI (foc_thread.cpp:43), so USE_HSPI_PORT is refused.
LCD_MOSI_SIGNAL = 103
LCD_MOSI_BROKEN_SIGNAL = 102
LCD_MOSI_REATTACH_SYMBOL = "cc_lcd_mosi_reattach"
# Where the re-attach is called matters as much as that it links: an earlier call, or one on a path that never runs,
# leaves binary A's FSPIQ_OUT routing. lcd_run_call_order reads the LCD setup calls LcdThread::run() makes, in address
# order, from firmware.elf (the toolchain's objdump over that one function, read only); a DMA build that needs the
# re-attach must call it right after every TFT_eSPI::initDMA and before TFT_eSPI::startWrite (lcd_mosi_gate).
LCD_RUN_SYMBOL = "_ZN9LcdThread3runEv"
LCD_SETUP_CALLS = (("begin", "_ZN8TFT_eSPI5begin"), ("initDMA", "_ZN8TFT_eSPI7initDMA"),
                   ("reattach", LCD_MOSI_REATTACH_SYMBOL), ("startWrite", "_ZN8TFT_eSPI10startWriteEv"))
LCD_CALL_ORDER_RULE = ("every TFT_eSPI::initDMA call in LcdThread::run() is directly followed by cc_lcd_mosi_reattach, "
                       "then TFT_eSPI::startWrite (xtensa-esp32s3-elf-objdump of firmware.elf, read only)")
XTENSA_OBJDUMP = PIO_CORE / "packages" / "toolchain-xtensa-esp32s3" / "bin" / "xtensa-esp32s3-elf-objdump.exe"
# What lcd_run_call_order raises for an ELF or an objdump it cannot read (build_nanod_cc5.py records it as the reason).
CALL_ORDER_ERRORS = (OSError, ValueError, IndexError, struct.error, subprocess.SubprocessError)


def alive_capability(led_max_brightness=ALIVE_DEFAULT_DRIVE):
    """What 1.0.0-cc5.4 reports as capabilities[presentation.ALIVE_CAPABILITY] on a knob whose
    settings have `led_max_brightness` (ALIVE.md section 1; drive = min(150, ledMaxBrightness))."""
    return {"version": presentation().ALIVE_VERSION, "fps": ALIVE_FPS,
            "drive": min(ALIVE_DEFAULT_DRIVE, int(led_max_brightness))}


class AliveRelease(Release):
    """A release that also reports the `alive` capability (1.0.0-cc5.4 and later). Its expected
    capabilities assume the default ledMaxBrightness (150); a check on a knob with another value
    compares against alive_capability(<that value>)."""
    alive = True

    def expected_capabilities(self):
        caps = super().expected_capabilities()
        caps[presentation().ALIVE_CAPABILITY] = alive_capability()
        return caps


def binary_variant(base, name):
    """Binary `name` (B .. E) of the ladder release `base` (use base.binary_profile(name), which creates it
    once): a copy of the release profile, same class, version, gates, capabilities, from-release, backup pair,
    backup record, step-down base record and device / lease check records, whose own files carry the binary in
    their names: firmware/nanod-control-center-<version>-<name>.bin (and -source.zip), manifest-<version>-<name>.json,
    work/nanod-<tag>-<name>-build.log, .pio/build-<tag>-<name>, backups/nanod-<tag>-<name>-expected-full.bin and
    diagnostics/<prefix>-<name>-{build,preparation,flash-checks,rollback,installation,look-checks}.json."""
    variant = copy.copy(base)
    variant.binary = name
    variant.artifact_version = f"{base.version}-{name}"
    variant.file_tag = f"{base.tag}-{name}"
    variant.prefix = f"{base.prefix}-{name}"
    build_record = f"{base.prefix}-build.json"
    variant.gate_patterns = tuple(f"{variant.prefix}-build.json" if pattern == build_record else pattern
                                  for pattern in base.gate_patterns)
    return variant


PROFILES = {
    # 1.0.0-cc4 -> 1.0.0-cc5.2, installed and finalized on 2026-09-23 (history; its rollback path,
    # rollback_nanod_cc5.py --to cc4, stays usable). 1.0.0-cc5 (SHA-256 c123f9dc...) reset once in
    # its stress check and 1.0.0-cc5.1 (SHA-256 f75ac481...) hung its HMI task inside
    # FastLED.show(); both were rolled back to cc4, never finalized, and share this backup pair.
    "cc5.2": Release(
        "1.0.0-cc5.2", from_version=CC4_VERSION, from_image_sha256=CC4_IMAGE_SHA256,
        from_image_bytes=CC4_IMAGE_BYTES, from_presentation=2, prefix="cc5", backup_stem="nanod-cc4-before-cc5",
        from_record="manifest-cc4.json", from_expected="nanod-cc4-expected-full.bin", from_expected_sha256=None,
        from_preparation="cc4-preparation.json", backup_family=("1.0.0-cc5.2", "1.0.0-cc5", "1.0.0-cc5.1"),
        superseded=("1.0.0-cc5", "1.0.0-cc5.1"), gates=CC52_DEVICE_GATES, from_token="CC4",
        desktop_bundle="desktop-dist-v3", desktop_rollback_bundle="desktop-dist-v2",
        gate_patterns=("cc5-stage*.json", "cc5-stage*.log", "cc5-*-report.json", "cc5-build.json"),
        validation_key="cc5", artwork2=False),
    # 1.0.0-cc5.2 -> 1.0.0-cc5.3 (artwork2: 240 px JPEG covers, app icons, prefetch, unpaced lines).
    # The knob runs cc5.2 (image SHA-256 45c629bb..., verified install image 19cd67b2...); NVS and
    # the filesystem may have changed since, so the backup step reads the whole flash again.
    "cc5.3": Release(
        "1.0.0-cc5.3", from_version="1.0.0-cc5.2",
        from_image_sha256="45c629bb175ee07d3cb7a83453f4176019da66711391108d200215df64531572",
        from_image_bytes=1010656, from_presentation=4, prefix="cc5.3", backup_stem="nanod-cc5.2-before-cc5.3",
        from_record="manifest-cc5.2.json", from_expected="nanod-cc5.2-expected-full.bin",
        from_expected_sha256="19cd67b2f91b97bcee942c9dbb2fa4662c337f1d23bd64282d5c852894c1ed12",
        from_preparation="cc5-preparation.json", backup_family=("1.0.0-cc5.3",),
        superseded=("1.0.0-cc5", "1.0.0-cc5.1", "1.0.0-cc5.2"), gates=CC52_DEVICE_GATES + ARTWORK2_DEVICE_GATES,
        from_token="CC5_2", desktop_bundle="desktop-dist-v4", desktop_rollback_bundle="desktop-dist-v3",
        # cc5-led-hue-report.json keeps its cc5 name (tests/tools/led_hue_report.py writes it on every
        # gate run, the LED model is unchanged in cc5.3), so it is named here; the other cc5-* files
        # are cc5.2-era evidence.
        gate_patterns=("cc5-stage*cc5.3*.json", "cc5-stage*cc5.3*.log", "cc5.3-stage*.json", "cc5.3-stage*.log",
                       "cc5.3-*-report.json", "cc5.3-build.json", "cc5-led-hue-report.json"),
        validation_key="cc5.3", artwork2=True),
    # 1.0.0-cc5.3 -> 1.0.0-cc5.4 ("Warm · alive" LEDs, ALIVE.md; presentation 5, PRESENTATION_V5.md;
    # desktop v7). The knob runs cc5.3 (image SHA-256 f1cd05a2..., verified install image 86759e50...);
    # the backup step reads the whole flash again. CURRENT (the combined cc5.4 + desktop v7 release):
    # build_nanod_cc5.py records its heap projection, package_nanod_cc5.py and finalize_nanod_cc5.py
    # read its gates, presentation and alive capability from the profile. It is binary A of the 12.6
    # build ladder; binary_profile("B") and ("C") were the fallbacks staged for the same window, and
    # ("D") / ("E") are the fix binaries staged after A's rollback (A, B and C are retired).
    "cc5.4": AliveRelease(
        "1.0.0-cc5.4", from_version="1.0.0-cc5.3",
        from_image_sha256="f1cd05a2cd43e0298ff9b10e4bf05ea77590e5d8e31a68623540f752fdd40541",
        from_image_bytes=1023648, from_presentation=4, prefix="cc5.4", backup_stem="nanod-cc5.3-before-cc5.4",
        from_record="manifest-cc5.3.json", from_expected="nanod-cc5.3-expected-full.bin",
        from_expected_sha256="86759e5053988e890517b0849498eea1dd02872a8f69e61d01d003d7c88d8781",
        from_preparation="cc5.3-preparation.json", backup_family=("1.0.0-cc5.4",),
        superseded=("1.0.0-cc5", "1.0.0-cc5.1", "1.0.0-cc5.2", "1.0.0-cc5.3"),
        gates=CC52_DEVICE_GATES + ARTWORK2_DEVICE_GATES + ALIVE_DEVICE_GATES + PRESENTATION5_DEVICE_GATES,
        from_token="CC5_3", desktop_bundle="desktop-dist-v7", desktop_rollback_bundle="desktop-dist-v6",
        gate_patterns=("cc5-stage*cc5.4*.json", "cc5-stage*cc5.4*.log", "cc5.4-stage*.json", "cc5.4-stage*.log",
                       "cc5.4-*-report.json", "cc5.4-build.json", "cc5-led-hue-report.json"),
        validation_key="cc5.4", artwork2=True, presentation=5,
        heap_min_free=V5_HEAP_MIN_FREE_BYTES, lvgl_min_free=V5_LVGL_MIN_FREE_BYTES, ladder=True),
    # 1.0.0-cc5.4 binary D -> 1.0.0-cc5.5 (plan F1: safety and measurement, no change to feel; firmware/
    # BUILD-cc5.5.md). The knob runs cc5.4 D (image SHA-256 dcff9c95..., 1,142,448 B; its PlatformIO "Flash used"
    # line said 1,142,077 B), installed 2026-09-29 from a step-down base (verified image ed4f364b...,
    # diagnostics/cc5.4-D-preparation.json) and never finalized: manifest.json is still the cc5.3 record
    # (from_finalized=False, from_active_record). Presentation 6 (Desk Dial r3). The backup step reads the whole
    # flash again (backups/nanod-cc5.4-before-cc5.5-*). Its own ladder: D (16 ms) and F (12 ms).
    "cc5.5": AliveRelease(
        "1.0.0-cc5.5", from_version="1.0.0-cc5.4", from_binary="D",
        from_image_sha256="dcff9c9525c250419851177774f00882a8837d19b7ad15ecad23377a3928eee2",
        from_image_bytes=1142448, from_presentation=6, prefix="cc5.5", backup_stem="nanod-cc5.4-before-cc5.5",
        from_record="manifest-cc5.4-D.json", from_expected="nanod-cc5.4-D-expected-full.bin",
        from_expected_sha256="ed4f364bd24b045530d5b893725579967cc584f17af32c06ab40ba471bd88242",
        from_preparation="cc5.4-D-preparation.json", backup_family=("1.0.0-cc5.5",),
        superseded=("1.0.0-cc5", "1.0.0-cc5.1", "1.0.0-cc5.2", "1.0.0-cc5.3"),
        gates=CC52_DEVICE_GATES + ARTWORK2_DEVICE_GATES + ALIVE_DEVICE_GATES + PRESENTATION5_DEVICE_GATES,
        from_token="CC5_4", desktop_bundle="desktop-dist-v7-d", desktop_rollback_bundle="desktop-dist-v7-c",
        gate_patterns=("cc5.5-stage*.json", "cc5.5-stage*.log", "cc5.5-*-report.json", "cc5.5-build.json"),
        validation_key="cc5.5", artwork2=True, presentation=6,
        heap_min_free=V5_HEAP_MIN_FREE_BYTES, lvgl_min_free=V5_LVGL_MIN_FREE_BYTES, ladder=CC55_LADDER,
        from_finalized=False, from_active_record="manifest-cc5.3.json",
        from_install_record="cc5.4-D-flash-checks.json", image_size_gate=IMAGE_SIZE_GATE_BYTES),
    # 1.0.0-cc5.5 binary F (installed 2026-09-30; was D when written) -> 1.0.0-cc5.6 (plan A2: Karl Malota's Onshape UI on the knob, the app canvas;
    # firmware/BUILD-cc5.6.md). cc5.5 D (image SHA-256 dd9dafbb..., 1,144,112 B) is packaged UNFLASHED at the time
    # of writing: from_expected_sha256 is None and the from-release is taken as installed but not finalized (as
    # cc5.4 D was), so manifest.json stays the cc5.3 record; both are settled after the cc5.5 D install
    # (BUILD-cc5.6.md). Presentation 6 plus appCanvas 1. Same ladder and size gate as cc5.5.
    "cc5.6": AliveRelease(
        "1.0.0-cc5.6", from_version="1.0.0-cc5.5", from_binary="F",
        from_image_sha256="5c926d2721d26b4e71789828c2571fe537c8c235973702726441f9d6878ad1f8",
        from_image_bytes=1144112, from_presentation=6, prefix="cc5.6", backup_stem="nanod-cc5.5-before-cc5.6",
        from_record="manifest-cc5.5-F.json", from_expected="nanod-cc5.5-F-expected-full.bin",
        from_expected_sha256="c5056fa52cf0b3970727da92a272fa20ce35dd01ea1a4e61945eba2a3d863fd4",
        from_preparation="cc5.5-F-preparation.json", backup_family=("1.0.0-cc5.6",),
        superseded=("1.0.0-cc5", "1.0.0-cc5.1", "1.0.0-cc5.2", "1.0.0-cc5.3"),
        gates=CC52_DEVICE_GATES + ARTWORK2_DEVICE_GATES + ALIVE_DEVICE_GATES + PRESENTATION5_DEVICE_GATES,
        from_token="CC5_5", desktop_bundle="desktop-dist-v7-g", desktop_rollback_bundle="desktop-dist-v7-f",
        gate_patterns=("cc5.6-stage*.json", "cc5.6-stage*.log", "cc5.6-*-report.json", "cc5.6-build.json"),
        validation_key="cc5.6", artwork2=True, presentation=6,
        heap_min_free=V5_HEAP_MIN_FREE_BYTES, lvgl_min_free=V5_LVGL_MIN_FREE_BYTES, ladder=CC55_LADDER,
        from_finalized=False, from_active_record="manifest-cc5.3.json",
        from_install_record="cc5.5-F-flash-checks.json", image_size_gate=IMAGE_SIZE_GATE_BYTES, app_canvas=True),
    # 1.0.0-cc5.6 binary F (installed 2026-09-30, the tilt rebuild: image SHA-256 81ee99fc..., 1,177,424 B; verified install
    # image 0f877393..., diagnostics/cc5.6-F-preparation.json) -> 1.0.0-cc5.7 (plan F2 + F3, the r4 FEEL + SOUND job;
    # firmware/BUILD-cc5.7.md, HAPTICS.md). cc5.6 F was never finalized (manifest.json stays the cc5.3 record), like cc5.5 F
    # and cc5.4 D before it. Presentation 6, appCanvas 1 and the r4 capabilities. Same ladder and size gate.
    "cc5.7": AliveRelease(
        "1.0.0-cc5.7", from_version="1.0.0-cc5.6", from_binary="F",
        from_image_sha256="81ee99fca7f1b4bc42e7ed7ddc1313e9198704356533e770d3e8bfbdbf1ed888",
        from_image_bytes=1177424, from_presentation=6, prefix="cc5.7", backup_stem="nanod-cc5.6-before-cc5.7",
        from_record="manifest-cc5.6-F.json", from_expected="nanod-cc5.6-F-expected-full.bin",
        from_expected_sha256="0f8773931487deefe7a0dd91c31be17ea532969a0c2c77aaf9a1974adcb9a2f1",
        from_preparation="cc5.6-F-preparation.json", backup_family=("1.0.0-cc5.7",),
        superseded=("1.0.0-cc5", "1.0.0-cc5.1", "1.0.0-cc5.2", "1.0.0-cc5.3"),
        gates=CC52_DEVICE_GATES + ARTWORK2_DEVICE_GATES + ALIVE_DEVICE_GATES + PRESENTATION5_DEVICE_GATES,
        from_token="CC5_6", desktop_bundle="desktop-dist-v7-j", desktop_rollback_bundle="desktop-dist-v7-i",
        gate_patterns=("cc5.7-stage*.json", "cc5.7-stage*.log", "cc5.7-*-report.json", "cc5.7-build.json"),
        validation_key="cc5.7", artwork2=True, presentation=6,
        heap_min_free=V5_HEAP_MIN_FREE_BYTES, lvgl_min_free=V5_LVGL_MIN_FREE_BYTES, ladder=CC55_LADDER,
        from_finalized=False, from_active_record="manifest-cc5.3.json",
        from_install_record="cc5.6-F-flash-checks.json", image_size_gate=IMAGE_SIZE_GATE_BYTES, app_canvas=True,
        r4_feel=True),
    # 1.0.0-cc5.7 binary F (installed 2026-09-30: image SHA-256 93ff0d50..., 1,128,128 B; verified install image
    # aa64fef5..., diagnostics/cc5.7-F-preparation.json) -> 1.0.0-cc5.8 (the public v2.0.0 release candidate: the Phase 2
    # audit fixes and app profiles; firmware/BUILD-cc5.8.md). cc5.7 F was never finalized (manifest.json stays the cc5.3
    # record), like cc5.6 F, cc5.5 F and cc5.4 D before it. Presentation 6, appCanvas 1, the r4 capabilities and the app
    # profile capabilities. Same ladder and size gate.
    "cc5.8": AliveRelease(
        "1.0.0-cc5.8", from_version="1.0.0-cc5.7", from_binary="F",
        from_image_sha256="93ff0d50fcb39dfa81e9b70249a653aab8aa4374ee267ac9a3b7eec016ae6f05",
        from_image_bytes=1128128, from_presentation=6, prefix="cc5.8", backup_stem="nanod-cc5.7-before-cc5.8",
        from_record="manifest-cc5.7-F.json", from_expected="nanod-cc5.7-F-expected-full.bin",
        from_expected_sha256="aa64fef511f9f33cf661307e2bc636442b820b198c4db2ebb71dc4b5fbcf53dd",
        from_preparation="cc5.7-F-preparation.json", backup_family=("1.0.0-cc5.8",),
        superseded=("1.0.0-cc5", "1.0.0-cc5.1", "1.0.0-cc5.2", "1.0.0-cc5.3"),
        gates=CC52_DEVICE_GATES + ARTWORK2_DEVICE_GATES + ALIVE_DEVICE_GATES + PRESENTATION5_DEVICE_GATES,
        from_token="CC5_7", desktop_bundle="desktop-dist-v7-l", desktop_rollback_bundle="desktop-dist-v7-k",
        gate_patterns=("cc5.8-stage*.json", "cc5.8-stage*.log", "cc5.8-*-report.json", "cc5.8-build.json"),
        validation_key="cc5.8", artwork2=True, presentation=6,
        heap_min_free=V5_HEAP_MIN_FREE_BYTES, lvgl_min_free=V5_LVGL_MIN_FREE_BYTES, ladder=CC55_LADDER,
        from_finalized=False, from_active_record="manifest-cc5.3.json",
        from_install_record="cc5.7-F-flash-checks.json", image_size_gate=IMAGE_SIZE_GATE_BYTES, app_canvas=True,
        r4_feel=True, app_profiles=True),
}
CURRENT = PROFILES["cc5.8"]         # the release these scripts build, package, install, check and finalize
# (2026-10-03: cc5.7 F (rest sleep, 93ff0d50...) is on the knob; cc5.8 upgrades from F.)
NEWEST = list(PROFILES.values())[-1]   # the release the firmware tree builds (1.0.0-cc5.8)


def all_profiles():
    """Every profile and, for a ladder release, each of its binaries (A is the profile itself), oldest
    first: the scans that must see every record name (rollback traces, write evidence) use this."""
    return [variant for profile in PROFILES.values() for variant in profile.variants()]


def binary_choices(profile=None):
    """The --binary choices of build, package, prepare, install and finalize for `profile` (CURRENT): the active
    binaries of its ladder in ladder order (ACTIVE_BINARIES; cc5.4: ("D", "E"), cc5.5: ("D", "F"); the first is the
    default), or () without the ladder. The retired binaries (RETIRED_BINARIES: A, B, C) are refused by argparse
    there (exit 2, nothing written); rollback_nanod_cc5.py and check_nanod_cc5.py take every binary of the ladder
    (pipeline_binaries)."""
    staged = (profile or CURRENT).pipeline_binaries()
    return tuple(name for name in staged if name in ACTIVE_BINARIES)


def binary_build_number(binary):
    """CC_BUILD_BINARY in `binary`'s build flags (D 4, E 5), None when its flags do not set it (A, B, C, None)."""
    for flag in BINARY_BUILD_FLAGS.get(binary, ()):
        if flag.startswith("-DCC_BUILD_BINARY="):
            return int(flag.split("=", 1)[1])
    return None
# rollback_nanod_cc5.py --to <release>: the profile whose locked pre-install backup it restores.
ROLLBACK_TARGETS = {"cc4": PROFILES["cc5.2"], "cc5.2": PROFILES["cc5.3"], "cc5.3": PROFILES["cc5.4"],
                    "cc5.4": PROFILES["cc5.5"], "cc5.5": PROFILES["cc5.6"], "cc5.6": PROFILES["cc5.7"],
                    "cc5.7": PROFILES["cc5.8"]}
DEFAULT_ROLLBACK_TARGET = "cc4"     # RECOVERY.md section 5 and BUILD-cc5.md run it without --to

# The current profile's names, for reference, messages and the runbooks. Scripts read the profile
# (CURRENT or a rollback target) so its paths follow the folders above.
CC5_VERSION = CURRENT.version
CC5_TAG = CURRENT.tag
SUPERSEDED_CC5_VERSIONS = CURRENT.superseded        # oldest first
CC5_IMAGE = CURRENT.image
CC5_SOURCE_ZIP = CURRENT.source_zip
CC5_MANIFEST = CURRENT.manifest
BUILD_LOG = CURRENT.build_log
FROM_VERSION = CURRENT.from_version
FROM_IMAGE = CURRENT.from_image
FROM_RECORD = CURRENT.from_record
BEFORE_FULL = CURRENT.before_full                   # 4 MB read before the first write of CURRENT
ROLLBACK_APP = CURRENT.rollback_app                 # app0 bytes of that read (step 5)
EXPECTED_FULL = CURRENT.expected_full               # before + this release at app0 (step 5)
BUILD_REPORT = CURRENT.build_report
BACKUP_REPORT = CURRENT.backup_report
PREPARATION = CURRENT.preparation
FLASH_CHECKS = CURRENT.flash_checks
DEVICE_CHECKS = CURRENT.device_checks
LEASE_CHECKS = CURRENT.lease_checks
ROLLBACK_REPORT = CURRENT.rollback_report
INSTALLATION = CURRENT.installation


def history_backup_names(profile=None):
    """Backup files of the other profiles: never written, renamed or replaced by `profile`'s steps."""
    profile = (profile or CURRENT).base
    names = {"nanod-original-full-20260922.bin", "nanod-original-active-app.bin"}
    for other in PROFILES.values():
        if other is not profile:
            names |= {other.before_full.name, other.rollback_app.name}
            names |= {variant.expected_full.name for variant in other.variants()}
    return names

# ---------------------------------------------------------------------------
# Presentation-side limits checked on the device (PRESENTATION_V4.md sections 1, 3)

ART_WIDTH = 120
ART_BYTES = ART_WIDTH * ART_WIDTH * 2                     # 28,800 B RGB565_LE
ART_CHUNK = 384
LVGL_HEAP_BYTES = 80 * 1024                               # include/lv_conf.h LV_MEM_SIZE (FW-RES-001: was 64 KB)
# The pool of the releases before 1.0.0-cc5.4 (64 KB): their diag gate is a fraction of it
# (diag_margins without a profile lvgl_min_free); 1.0.0-cc5.4 on gate lvglMinFree in bytes.
PRE_V5_LVGL_HEAP_BYTES = 64 * 1024
LVGL_MIN_FREE_FRACTION = 0.25
STACK_MIN_BYTES = 1024
# Internal heap (diag heapMinFree: the lowest free MALLOC_CAP_INTERNAL since boot, so the final
# diag after the soak covers the whole run). 1.0.0-cc5.2 measured 79,692 B
# (diagnostics/cc5-device-checks.json); cc5.3 adds about 16 KB of static RAM, an 8192-byte receive
# queue (4096 before) and ~2.9 KB media lines parsed in internal RAM, so the floor keeps a clear
# margin for transient JSON documents and the USB stack without failing a healthy cc5.3.
HEAP_MIN_FREE_BYTES = 40000
PREVIOUS_HEAP_MIN_FREE_BYTES = 79692   # 1.0.0-cc5.2, for the evidence's delta
EXPECTED_ARTWORK_CAPABILITY = {"version": 1, "width": 120, "height": 120, "format": "RGB565_LE",
                               "chunkBytes": 384, "cacheEntries": 8, "available": True,
                               "composited": "scrim80"}

# artwork2 (1.0.0-cc5.3, firmware/ARTWORK2.md). The contract values are the
# companion's own constants (control_center/presentation.py), loaded from that file by path:
# never copied here.
PRESENTATION_SOURCE = APP / "control_center" / "presentation.py"
JPEG_DECODE_MAX_MS = 200            # ARTWORK2.md section 10 / 12.11: diag jpegDecodeMsMax at most this (was 150; the 2026-09-24 hardware run measured 151 max, user approved hands-on)
COVER_TRANSFER_MAX_SECONDS = 1.5    # one unpaced cover, begin to commit ack (a paced 120 px v1 cover took ~5 s)
MEDIA_DIAG_FIELDS = ("rxQueueBytes", "mediaCommits", "mediaErrors", "mediaEvictions", "jpegDecodes",
                     "jpegDecodeErrors", "jpegDecodeMsMax", "jpegDecodeMsLast")
DESIGN_ASSETS = APP / "design-reference" / "design_handoff_nano_d_artwork_color" / "assets"
_presentation_module = None


def presentation():
    """control_center/presentation.py, loaded by path once (pure constants and helpers, no I/O)."""
    global _presentation_module
    if _presentation_module is None:
        spec = importlib.util.spec_from_file_location("nanod_contract_presentation", PRESENTATION_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _presentation_module = module
    return _presentation_module


def artwork2_capability():
    """A fresh copy of presentation.ARTWORK2_CAPABILITY (what cc5.3 must report)."""
    return copy.deepcopy(presentation().ARTWORK2_CAPABILITY)


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# Small utilities

def console_utf8():
    """Keep prints of device text (· … é) from failing on a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def utc_stamp(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def digest_record(path):
    path = Path(path)
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def unique_path(path, stamp=None):
    """`path` if free, else a timestamped sibling that does not exist yet (never overwrites)."""
    path = Path(path)
    if not path.exists():
        return path
    stamp = stamp or utc_stamp()
    for n in range(1000):
        suffix = "" if n == 0 else f"-{n}"
        candidate = path.with_name(f"{path.stem}-{stamp}{suffix}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"No free evidence name next to {path.name}")


def archive_existing(path, stamp=None):
    """Rename an existing file to `<stem>.superseded-<UTC><suffix>` so it is never overwritten."""
    path = Path(path)
    if not path.exists():
        return None
    base = path.with_name(f"{path.stem}.superseded-{stamp or utc_stamp()}{path.suffix}")
    target, n = base, 1
    while target.exists():
        target, n = base.with_name(f"{base.stem}-{n}{base.suffix}"), n + 1
    path.rename(target)
    return target


def write_new_bytes(path, data):
    """Create `path` exclusively (fails rather than overwrite)."""
    with Path(path).open("xb") as handle:
        handle.write(data)


def write_json_evidence(path, data, *, keep_previous=True):
    """Write evidence JSON at `path`; an existing file is archived first, never overwritten.

    Returns the archived name (or None) so reports can reference what they superseded.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    archived = archive_existing(path) if keep_previous else None
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    return archived


def write_new_json(path, data):
    """Write evidence under a name that never replaces older evidence (timestamped if taken)."""
    target = unique_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return target


# ---------------------------------------------------------------------------
# Port discovery (VID/PID plus identity; no COM literals; exactly one or abort)

class PortError(RuntimeError):
    """No unique matching port: nothing was opened or sent."""


def normalize_mac(value):
    return re.sub(r"[^0-9a-f]", "", (value or "").lower())


def port_info(port):
    return {name: getattr(port, attr, None) for name, attr in (
        ("port", "device"), ("vid", "vid"), ("pid", "pid"), ("serial_number", "serial_number"),
        ("description", "description"), ("location", "location"), ("hwid", "hwid"))}


def is_app_port(port):
    """The Nano_D++ application CDC port: 239A:8010 with serial NANO_D (any case)."""
    serial_number = getattr(port, "serial_number", None) or ""
    return ((getattr(port, "vid", None), getattr(port, "pid", None)) == (APP_VID, APP_PID)
            and serial_number.casefold() == APP_SERIAL.casefold())


def is_rom_port(port, mac=CHIP_MAC):
    """The ESP32-S3 ROM USB-Serial/JTAG port of this exact chip (serial == MAC)."""
    wanted = normalize_mac(mac)
    return ((getattr(port, "vid", None), getattr(port, "pid", None)) == (ROM_VID, ROM_PID)
            and len(wanted) == 12 and normalize_mac(getattr(port, "serial_number", None)) == wanted)


def select_one(ports, predicate, what):
    """Return the single port matching `predicate`, or raise PortError listing what was seen."""
    ports = list(ports)
    matches = [p for p in ports if predicate(p)]
    if len(matches) != 1:
        seen = ", ".join(f"{i['port']} {i['vid'] and hex(i['vid'])}:{i['pid'] and hex(i['pid'])} "
                         f"serial={i['serial_number']!r}" for i in map(port_info, ports)) or "no ports"
        raise PortError(f"{what}: expected exactly one matching port, found {len(matches)} "
                        f"(seen: {seen}). Nothing was opened or sent.")
    return matches[0]


def list_ports():
    """Enumerate serial ports (Windows device metadata only; no port is opened)."""
    from serial.tools.list_ports import comports
    return list(comports())


def find_app_port(ports=None):
    return select_one(list_ports() if ports is None else ports, is_app_port,
                      "Nano_D++ application port (239A:8010, serial NANO_D)").device


def find_rom_port(ports=None, mac=CHIP_MAC):
    return select_one(list_ports() if ports is None else ports, lambda p: is_rom_port(p, mac),
                      f"ESP32-S3 ROM bootloader port (303A:1001, serial {mac})").device


def poll_ports(predicate, timeout, *, lister=list_ports, clock=time.monotonic, sleep=time.sleep,
               interval=0.25, settle=1.0):
    """Watch enumeration until exactly one port matches and stays for `settle` seconds.

    Returns (device or None, list of observed port snapshots). Never opens a port.
    """
    observed, last = [], None
    started = clock()
    deadline = started + timeout
    stable_since = None
    while True:
        ports = lister()
        snapshot = [port_info(p) for p in ports]
        if snapshot != last:
            observed.append({"t": round(clock() - started, 3), "ports": snapshot})
            last = snapshot
        matches = [p for p in ports if predicate(p)]
        if len(matches) == 1:
            stable_since = clock() if stable_since is None else stable_since
            if clock() - stable_since >= settle:
                return matches[0].device, observed
        else:
            stable_since = None
        if clock() >= deadline:
            return None, observed
        sleep(interval)


def running_companions(run=subprocess.run, images=None):
    """The companion images (COMPANION_IMAGES: DeskDial.exe, NanoDControlCenter.exe) that run now, or None
    when tasklist cannot tell for one of them and none was seen running.

    One read-only tasklist query per image (image names only, never window titles); no window is created.
    """
    found, unknown = [], False
    for image in images or COMPANION_IMAGES:
        try:
            result = run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            unknown = True
            continue
        if result.returncode != 0:
            unknown = True
            continue
        if image.lower() in (result.stdout or "").lower():      # else "INFO: No tasks are running ..."
            found.append(image)
    if found:
        return found
    return None if unknown else []


def companion_running(run=subprocess.run):
    """True/False when tasklist can tell whether an installed companion runs (Desk Dial or the old
    NanoD Control Center image; either owns the knob); None if unknown."""
    found = running_companions(run)
    return None if found is None else bool(found)


def require_companion_quit(run=subprocess.run):
    found = running_companions(run)
    if found:
        raise SystemExit(f"{' and '.join(found)} {'is' if len(found) == 1 else 'are'} running and owns the knob. "
                         "Quit it from the tray (and disable its startup task, "
                         + " or ".join(f"'{task}'" for task in COMPANION_TASKS)
                         + ", for this window) first.")
    return None if found is None else False


# ---------------------------------------------------------------------------
# Flash environment (install, rollback and backup refuse to run anywhere else)

def _norm(path):
    return os.path.normcase(os.path.realpath(str(path)))


def flash_environment_problems(executable, prefix, esptool_version, venv=FLASH_VENV):
    problems = []
    scripts = Path(venv) / "Scripts"
    if _norm(Path(executable).parent) != _norm(scripts):
        problems.append(f"interpreter {executable} is not the flash venv ({scripts})")
    if _norm(prefix) != _norm(venv):
        problems.append(f"sys.prefix {prefix} is not the flash venv ({venv})")
    if esptool_version != ESPTOOL_VERSION:
        problems.append(f"esptool {esptool_version!r} is not the verified {ESPTOOL_VERSION}")
    return problems


def assert_flash_environment():
    """Abort unless running under tools/nanod-flash-venv with esptool 4.12.0. Opens nothing."""
    try:
        import esptool
        version = getattr(esptool, "__version__", None)
    except ImportError:
        version = None
    problems = flash_environment_problems(sys.executable, sys.prefix, version)
    if problems:
        raise SystemExit("Refusing to continue: " + "; ".join(problems)
                         + f". Run with {FLASH_VENV / 'Scripts' / 'python.exe'}.")
    return {"python": sys.executable, "prefix": sys.prefix, "esptool": version}


# ---------------------------------------------------------------------------
# esptool (subprocess per step; the RAM stub stays loaded between steps via
# --before no_reset --after no_reset_stub, which is the "same stub session")

FORBIDDEN_ESPTOOL = frozenset(("erase_flash", "erase_region", "--erase-all", "-e", "merge_bin",
                               "write_flash_status", "load_ram", "run", "burn_efuse"))
# The one write shape allowed: the three keep flags in this order, then exactly one
# (address, file) pair at app0. Any other token, in any number format, is refused.
WRITE_FLASH_PREFIX = ("write_flash", "--flash_mode", "keep", "--flash_freq", "keep", "--flash_size", "keep")


def validate_esptool_args(args):
    """Only identity, reads, verifies and app0 writes; never an erase or a full-image write."""
    args = [str(a) for a in args]
    if not args:
        raise ValueError("No esptool command")
    bad = [a for a in args if a in FORBIDDEN_ESPTOOL]
    if bad:
        raise ValueError(f"Forbidden esptool argument(s): {bad}")
    command = args[0]
    if command not in ("flash_id", "read_mac", "read_flash", "verify_flash", "write_flash"):
        raise ValueError(f"esptool command {command!r} is not allowed here")
    if command == "write_flash":
        prefix, rest = tuple(args[:len(WRITE_FLASH_PREFIX)]), args[len(WRITE_FLASH_PREFIX):]
        if prefix != WRITE_FLASH_PREFIX:
            raise ValueError("write_flash must be exactly: write_flash --flash_mode keep --flash_freq keep "
                             "--flash_size keep 0x10000 <file.bin>")
        if (len(rest) != 2 or rest[0] != hex(APP_OFFSET) or rest[1].startswith("-")
                or not rest[1].lower().endswith(".bin")):
            raise ValueError("write_flash is only allowed as one .bin image at app0 (0x10000), nothing else")
    return args


class Esptool:
    """Run one esptool step at a time, logging each to diagnostics and into `report["steps"]`."""

    def __init__(self, port, report, prefix, *, python=None, run=subprocess.run,
                 diagnostics=DIAGNOSTICS, baud="460800", echo=True):
        self.port, self.report, self.prefix = port, report, prefix
        self.python = python or sys.executable
        self.run_process, self.diagnostics, self.baud, self.echo = run, Path(diagnostics), baud, echo
        report.setdefault("steps", [])

    def command(self, args, after):
        if after not in ("no_reset_stub", "hard_reset"):
            raise ValueError("Only --after no_reset_stub or hard_reset are used")
        return [self.python, "-u", "-m", "esptool", "--chip", "esp32s3", "--port", self.port,
                "--baud", self.baud, "--before", "no_reset", "--after", after,
                *validate_esptool_args(args)]

    def __call__(self, name, args, *, after="no_reset_stub", timeout=240):
        command = self.command(args, after)
        started = time.monotonic()
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            result = self.run_process(command, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=timeout, env=env,
                                      creationflags=_NO_WINDOW)
            code, output = result.returncode, (result.stdout or "") + (result.stderr or "")
        except subprocess.TimeoutExpired as exc:
            code = "timeout"
            output = f"{exc.stdout or ''}{exc.stderr or ''}\nTIMEOUT after {timeout} s"
        except OSError as exc:
            code, output = "oserror", f"{type(exc).__name__}: {exc}"
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        log = self.diagnostics / f"{self.prefix}-{name}.log"
        archive_existing(log)
        log.write_text(output if isinstance(output, str) else str(output), encoding="utf-8")
        shown = [Path(a).name if os.sep in str(a) or "/" in str(a) else str(a) for a in command[3:]]
        self.report["steps"].append({"step": name, "command": ["esptool", *shown[1:]], "after": after,
                                     "exitCode": code, "seconds": round(time.monotonic() - started, 2),
                                     "log": log.name})
        if self.echo:
            print(f"[{name}] exit {code}; log {log.name}", flush=True)
            print(output[-1500:], flush=True)
        return code == 0, output


def identity_problems(flash_id_output, mac=CHIP_MAC):
    text = (flash_id_output or "").lower()
    problems = []
    if mac.lower() not in text:
        problems.append("chip MAC does not match")
    if "detected flash size: 4mb" not in text:
        problems.append("flash size is not 4MB")
    return problems


def reset_confirmed(ok, output, mac=CHIP_MAC):
    """`read_mac --after hard_reset` exited 0, named this chip and printed esptool's reset line."""
    text = (output or "").lower()
    return bool(ok) and mac.lower() in text and "hard resetting" in text


def reset_retry_command(port, python=None):
    """The exact PowerShell line that retries only the final reset (read-only, then hard_reset)."""
    python = python or str(FLASH_VENV / "Scripts" / "python.exe")
    return (f"& '{python}' -u -m esptool --chip esp32s3 --port {port} "
            "--before no_reset --after hard_reset read_mac")


def print_reset_retry(port, what):
    command = reset_retry_command(port)
    print(f"{what} is verified in flash, but the final reset was NOT confirmed. Do not write anything.\n"
          f"Retry only the reset, once:\n  {command}\n"
          "If that port is gone, list ports first: when 239A:8010 (serial NANO_D) is present the chip has "
          "already restarted; when a 303A:1001 port with the chip MAC is present, use it in the command.",
          flush=True)
    return command


# ---------------------------------------------------------------------------
# A pre-install backup is a rollback input: once its release's write was attempted it is
# never replaced

def _write_attempts(variant, diagnostics, verb="write attempt"):
    """Reasons from `variant`'s flash-checks records (current or superseded) with a write attempt; an
    unreadable one counts, since it cannot rule a write out."""
    reasons = []
    for path in sorted(diagnostics.glob(f"{variant.prefix}-flash-checks*.json")):
        try:
            record = load_json(path)
        except (OSError, ValueError):
            reasons.append(f"{path.name} is unreadable")
            continue
        if record.get("writeAttempted") or record.get("flashWritten"):
            reasons.append(f"{path.name} records a {variant.label} {verb}")
    return reasons


def _manifest_status(path):
    try:
        return load_json(path).get("installationStatus")
    except (OSError, ValueError):
        return "unreadable"


def backup_locks(profile=None, diagnostics=None, manifest=None):
    """Reasons why `profile`'s pre-install backup must not be replaced (empty: it may be).

    Any flash record of the profile (current or superseded) with a write attempt, any of its
    rollback records, or a manifest of its backup family (the release, and for cc5.2 the
    earlier cc5 builds that installed from the same pair) that is not UNFLASHED locks it.
    Every binary of a ladder release (A .. E) installs from the same pair, so the records and
    manifests of each of them lock it. Unreadable records lock it too. Evidence of another profile
    never counts: the cc5.3 backup is not locked by the cc5.2 records, nor the other way round.
    """
    profile = profile or CURRENT
    diagnostics = Path(DIAGNOSTICS if diagnostics is None else diagnostics)
    manifest = Path(profile.manifest if manifest is None else manifest)
    manifests = [manifest] + [manifest.with_name(release_manifest(v).name) for v in profile.backup_family
                              if release_manifest(v).name != manifest.name]
    manifests += [manifest.with_name(v.manifest.name) for v in profile.variants()
                  if v is not profile and manifest.with_name(v.manifest.name) not in manifests]
    reasons = []
    for variant in profile.variants():
        reasons += _write_attempts(variant, diagnostics)
        reasons += [f"{p.name} records a {variant.label} rollback"
                    for p in sorted(diagnostics.glob(f"{variant.prefix}-rollback*.json"))]
    for path in manifests:
        if path.is_file():
            status = _manifest_status(path)
            if status != "UNFLASHED":
                reasons.append(f"{path.name} status is {status}")
    return reasons


def pre_cc5_backup_locks(diagnostics=None, cc5_manifest=None):
    """The cc5.2 profile's locks on backups/nanod-cc4-before-cc5-full.bin (history: locked for good)."""
    return backup_locks(PROFILES["cc5.2"], diagnostics, cc5_manifest)


def later_profiles(profile):
    """The profiles after `profile`'s release (their installs started from its release or a later one)."""
    ordered = list(PROFILES.values())
    return ordered[ordered.index(profile.base) + 1:]


def binary_write_evidence(profile, diagnostics=None, manifest=None):
    """Why the records say this one binary (or release without the ladder) was written to the knob (empty:
    they never say so): a flash-checks record of its install with a write attempt, or its manifest
    INSTALLED or ROLLED_BACK. An unreadable record counts (it cannot rule a write out)."""
    diagnostics = Path(DIAGNOSTICS if diagnostics is None else diagnostics)
    manifest = Path(profile.manifest if manifest is None else manifest)
    reasons = _write_attempts(profile, diagnostics)
    if manifest.is_file():
        status = _manifest_status(manifest)
        if status in ("INSTALLED", "ROLLED_BACK", "unreadable"):
            reasons.append(f"{manifest.name} status is {status}")
    return reasons


def release_write_evidence(profile, diagnostics=None, manifest=None):
    """Why the records say `profile`'s release was written to the knob (empty: they never say so): the
    binary_write_evidence of every binary of the release (A .. E of a ladder release; `manifest`, when
    given, is `profile`'s own and the other binaries' manifests are read next to it)."""
    manifest = Path(profile.manifest if manifest is None else manifest)
    reasons = []
    for variant in profile.variants():
        own = manifest if variant is profile else manifest.with_name(variant.manifest.name)
        reasons += binary_write_evidence(variant, diagnostics, own)
    return reasons


def newest_written_binary(profile, diagnostics=None):
    """(binary, record name, problems) for a ladder release: the binary whose flash-checks record with a
    write attempt is the newest (by its startedUtc stamp, then file time), i.e. the binary app0 may hold
    now. (None, None, []) when no binary was ever written; problems name unreadable records, which make
    the answer unknown (rollback_nanod_cc5.py then requires --binary)."""
    diagnostics = Path(DIAGNOSTICS if diagnostics is None else diagnostics)
    newest, problems = None, []
    for variant in profile.variants():
        for path in sorted(diagnostics.glob(f"{variant.prefix}-flash-checks*.json")):
            try:
                record = load_json(path)
            except (OSError, ValueError):
                problems.append(f"{path.name} is unreadable")
                continue
            if not (isinstance(record, dict) and (record.get("writeAttempted") or record.get("flashWritten"))):
                continue
            stamp = record.get("startedUtc") if isinstance(record.get("startedUtc"), str) else ""
            key = (stamp, path.stat().st_mtime)
            if newest is None or key > newest[0]:
                newest = (key, variant.binary, path.name)
    if newest is None:
        return None, None, problems
    return newest[1], newest[2], problems


# ---------------------------------------------------------------------------
# The installed from-release (1.0.0-cc5.5: cc5.4 binary D, installed but never finalized)

def from_profile(profile):
    """The profile whose release `profile` upgrades from (its from_version), or None (cc4)."""
    return next((q for q in PROFILES.values() if q.version == profile.from_version), None)


def from_record_problems(profile, path=None):
    """Why `path` (profile.from_record) is not the from-release's record: its firmwareVersion must be the
    from_version and its artifacts must name the from image (the installed binary's, for from_binary) with
    its SHA-256."""
    path = Path(profile.from_record if path is None else path)
    try:
        record = load_json(path)
    except (OSError, ValueError):
        return [f"{path.name} is missing or unreadable"]
    if (not isinstance(record, dict) or record.get("firmwareVersion") != profile.from_version
            or (record.get("artifacts") or {}).get(profile.from_image.name, {}).get("sha256") != profile.from_image_sha256):
        return [f"{path.name} is not the {profile.from_version} record ({profile.from_image.name}, SHA-256 "
                f"{profile.from_image_sha256})"]
    return []


def from_install_problems(profile, diagnostics=None):
    """Why the records do not show `profile`'s from-release running on the knob (empty: they do), for a
    from-release that was installed but never finalized (profile.from_finalized False; always [] otherwise, where
    manifest.json is the evidence). Its install record (profile.from_install_record: 1.0.0-cc5.5 reads
    diagnostics/cc5.4-D-flash-checks.json) must record a verified, reset install (outcome INSTALLED_VERIFIED_RESET or
    its _UNCONFIRMED form) of the from image (candidate file and SHA-256, firmwareVersion, binary), be the newest
    write of that release (newest_written_binary of its profile), and no rollback of that release may be recorded
    after it (a later rollback left the knob on the release before it)."""
    if profile.from_finalized:
        return []
    diagnostics = Path(DIAGNOSTICS if diagnostics is None else diagnostics)
    path = diagnostics / profile.from_install_record_name
    try:
        record = load_json(path)
    except (OSError, ValueError):
        return [f"{path.name} (the {profile.from_version} install record) is missing or unreadable"]
    if not isinstance(record, dict):
        return [f"{path.name} is not an install record"]
    problems = []
    outcome = str(record.get("outcome") or "")
    if not outcome.startswith("INSTALLED_VERIFIED_RESET"):
        problems.append(f"{path.name} records outcome {outcome or 'none'}, not a verified install")
    if (record.get("candidate") != profile.from_image.name or record.get("candidateSha256") != profile.from_image_sha256
            or record.get("firmwareVersion") != profile.from_version
            or (profile.from_binary and record.get("binary") != profile.from_binary)):
        problems.append(f"{path.name} does not record {profile.from_image.name} (SHA-256 {profile.from_image_sha256})")
    source = from_profile(profile)
    stamp = record.get("startedUtc") if isinstance(record.get("startedUtc"), str) else ""
    if source is not None:
        _, newest, unreadable = newest_written_binary(source, diagnostics)
        problems += unreadable
        if newest != path.name:
            problems.append(f"the newest {source.tag} write is {newest or 'none'}, not {path.name}")
        for variant in source.variants():
            for rollback in sorted(diagnostics.glob(f"{variant.prefix}-rollback*.json")):
                try:
                    started = load_json(rollback).get("startedUtc")
                except (OSError, ValueError, AttributeError):
                    problems.append(f"{rollback.name} is unreadable")
                    continue
                if isinstance(started, str) and started > stamp:
                    problems.append(f"{rollback.name} records a {variant.label} rollback after {path.name}")
    return problems


def active_record_problems(profile):
    """Why manifest.json is not the record `profile`'s install must start from (empty: it is): the installed
    from-release's record (profile.from_record), or for a from-release never finalized the record its install left
    in force (profile.restore_record) together with its install evidence (from_install_problems)."""
    record = profile.restore_record
    if not ACTIVE_MANIFEST.is_file() or not record.is_file() or sha256_file(ACTIVE_MANIFEST) != sha256_file(record):
        what = (f"the installed {profile.from_version} record" if profile.from_finalized else
                f"the record in force while the never-finalized {profile.from_version} runs")
        return [f"manifest.json is not {what} ({record.name})"]
    return from_install_problems(profile)


def restore_record_problems(profile):
    """Why profile.restore_record is not the record a rollback to the from-release puts back into manifest.json:
    the from-release's record (from_record_problems), or for a from-release never finalized the record of the
    release before it (its own from_version and from image, e.g. manifest-cc5.3.json for 1.0.0-cc5.5). A chain of
    never-finalized releases that leave the same record in force (1.0.0-cc5.6 from cc5.5 F from cc5.4 D, all with
    manifest-cc5.3.json) is followed back to the release that record belongs to."""
    if profile.from_finalized:
        return from_record_problems(profile)
    source = from_profile(profile)
    if source is None:
        return []
    if not source.from_finalized and source.restore_record.name == profile.restore_record.name:
        return restore_record_problems(source)
    return from_record_problems(source, profile.restore_record)


# ---------------------------------------------------------------------------
# Partition table and OTA selection (same rules as analyze_nanod_backup.py)

_PART_ROW = struct.Struct("<2sBBII16sI")
_MD5_ROW = b"\xeb\xeb" + b"\xff" * 14


def parse_partition_table(table):
    """Parse an ESP-IDF partition table; the MD5 row must be present and correct."""
    entries, md5_ok = [], None
    for pos in range(0, len(table) - 31, 32):
        row = table[pos:pos + 32]
        if row[:2] == b"\xaa\x50":
            _, ptype, subtype, offset, size, name, flags = _PART_ROW.unpack(row)
            entries.append({"name": name.rstrip(b"\x00").decode("ascii"), "type": ptype,
                            "subtype": subtype, "offset": offset, "size": size, "flags": flags})
        elif row[:16] == _MD5_ROW:
            md5_ok = hashlib.md5(table[:pos]).digest() == row[16:]
        elif row == b"\xff" * 32:
            break
        else:
            raise ValueError(f"Unrecognised partition table row at +0x{pos:x}")
    if not entries:
        raise ValueError("Partition table is empty")
    if md5_ok is not True:
        raise ValueError("Partition table checksum row is missing or wrong")
    ordered = sorted(entries, key=lambda e: e["offset"])
    for a, b in zip(ordered, ordered[1:]):
        if a["offset"] + a["size"] > b["offset"]:
            raise ValueError(f"Partitions {a['name']} and {b['name']} overlap")
    return entries


def layout_key(entries):
    return [(e["name"], e["type"], e["subtype"], e["offset"], e["size"]) for e in entries]


# Regions whose drift after a rollback means the rollback itself is wrong. Data
# partitions (nvs, spiffs, coredump) may legitimately change while cc5 runs.
CRITICAL_REGIONS = frozenset(("bootloader", "partition-table", "otadata", "app0", "app1"))


def is_critical_region(name):
    """A flash_regions() region a rollback must return byte for byte (CRITICAL_REGIONS and the gaps between
    partitions); the data partitions (nvs, spiffs, coredump) may drift and are never rewritten."""
    return name in CRITICAL_REGIONS or name.startswith("gap-")


def flash_regions(partitions, flash_bytes=FLASH_BYTES):
    """Contiguous named regions covering [0, flash_bytes): bootloader, table, partitions, gaps."""
    spans = [("bootloader", 0, PARTITION_TABLE_OFFSET),
             ("partition-table", PARTITION_TABLE_OFFSET, PARTITION_TABLE_OFFSET + PARTITION_TABLE_SIZE)]
    spans += [(p["name"], p["offset"], p["offset"] + p["size"]) for p in partitions]
    spans.sort(key=lambda s: s[1])
    regions, cursor = [], 0
    for name, start, end in spans:
        if start < cursor or end > flash_bytes:
            raise ValueError(f"Region {name} overlaps or exceeds the flash")
        if start > cursor:
            regions.append((f"gap-0x{cursor:X}", cursor, start))
        regions.append((name, start, end))
        cursor = end
    if cursor < flash_bytes:
        regions.append((f"gap-0x{cursor:X}", cursor, flash_bytes))
    return regions


def region_differences(reference, image):
    """(critical, data): the flash_regions() of `reference`'s partition table in which `image` differs from
    `reference`, split by is_critical_region(). Both must be full 4 MB images; raises ValueError otherwise,
    or when `reference` has no valid partition table."""
    if len(reference) != FLASH_BYTES or len(image) != FLASH_BYTES:
        raise ValueError("a region comparison needs two full 4 MB images")
    partitions = parse_partition_table(reference[PARTITION_TABLE_OFFSET:PARTITION_TABLE_OFFSET + PARTITION_TABLE_SIZE])
    critical, data = [], []
    for name, start, end in flash_regions(partitions):
        if reference[start:end] != image[start:end]:
            (critical if is_critical_region(name) else data).append(name)
    return critical, data


# ---------------------------------------------------------------------------
# Step-down base (PRESENTATION_V5 12.6, lead ruling R-m). A failing binary may write a data partition before
# its verified rollback (a panic or task_wdt reset writes the core dump; settings go to nvs), and the rollback
# reports that drift without rewriting it (rollback_nanod_cc5.py verify_regions). The next binary then cannot be
# verified against the locked pre-install backup, which is never replaced. backup_nanod_cc5.py --step-down reads
# the whole flash again and keeps a verified read whose critical regions are byte-identical to the locked backup
# as the step-down base (Release.step_down_base, record Release.step_down_report); prepare_nanod_cc5_install.py
# --step-down-base builds the next binary's expected image from it, and install_nanod_cc5.py verifies the device
# against it before writing (and restores to it). The rollback still verifies against the locked backup.

PRE_INSTALL_ROLE = "pre-install backup"      # preparation "baseKind": the expected image follows from the backup
STEP_DOWN_ROLE = "step-down base"            # ... or from the release's current step-down base


def load_step_down_base(profile):
    """(path, bytes, record) of `profile`'s current step-down base, checked: its record passed with the step-down
    role and names a 4 MB backups/ file with the recorded SHA-256; the locked pre-install backup still matches its
    own record and the step-down record's lockedBackupSha256; and every critical region of the base (bootloader,
    partition table, OTA data, app0, app1, the gaps) is byte-identical to the locked backup. Raises ValueError
    naming the first problem (the callers stop before anything is written or sent)."""
    base = profile.base
    record_path, locked = base.step_down_report, base.before_full
    try:
        record = load_json(record_path)
    except (OSError, ValueError):
        raise ValueError(f"{record_path.name} is missing or unreadable (take the step-down base read first: "
                         "backup_nanod_cc5.py --step-down)") from None
    if not isinstance(record, dict) or record.get("passed") is not True or record.get("role") != STEP_DOWN_ROLE:
        raise ValueError(f"{record_path.name} does not record a passed {STEP_DOWN_ROLE}")
    name = Path(str(record.get("file") or "")).name
    path = BACKUPS / name
    if not name or name in (locked.name, base.rollback_app.name) or not path.is_file():
        raise ValueError(f"{record_path.name} names no step-down base file in backups/ ({name or 'none'})")
    data = path.read_bytes()
    if len(data) != FLASH_BYTES or sha256_bytes(data) != record.get("sha256"):
        raise ValueError(f"{name} does not match {record_path.name} (SHA-256 or size)")
    if not locked.is_file():
        raise ValueError(f"the locked {locked.name} is missing")
    locked_bytes = locked.read_bytes()
    locked_sha = sha256_bytes(locked_bytes)
    try:
        backup = load_json(base.backup_report)
    except (OSError, ValueError):
        backup = None
    if not isinstance(backup, dict) or backup.get("passed") is not True or backup.get("sha256") != locked_sha:
        raise ValueError(f"{base.backup_report.name} does not record {locked.name} (SHA-256 {locked_sha})")
    if record.get("lockedBackupSha256") != locked_sha:
        raise ValueError(f"{record_path.name} was not read against the locked {locked.name} (SHA-256 {locked_sha})")
    critical, _ = region_differences(locked_bytes, data)
    if critical:
        raise ValueError(f"{name} differs from the locked {locked.name} in the critical region(s) {', '.join(critical)}")
    return path, data, record


def ota_selection(otadata, app_count):
    """Which OTA app the bootloader selects (highest valid sequence, CRC checked)."""
    entries = []
    for slot in range(2):
        start = slot * SECTOR
        seq, _label, state, crc = struct.unpack("<I20sII", otadata[start:start + 32])
        expected = zlib.crc32(struct.pack("<I", seq), 0xFFFFFFFF) & 0xFFFFFFFF
        entries.append({"slot": slot, "sequence": seq, "state": state, "crc": crc,
                        "valid": seq != 0xFFFFFFFF and state not in (3, 4) and crc == expected})
    valid = [e for e in entries if e["valid"]]
    if valid:
        best = max(valid, key=lambda e: e["sequence"])
        if best["sequence"] >= 0xFFFFFF00:
            raise ValueError("OTA sequence wraparound needs manual review")
        return {"entries": entries, "appIndex": (best["sequence"] - 1) % app_count}
    if any(otadata[i * SECTOR:i * SECTOR + 32] != b"\xff" * 32 for i in range(2)):
        raise ValueError("OTA data is neither valid nor empty")
    return {"entries": entries, "appIndex": None}


# ---------------------------------------------------------------------------
# Image assembly (app-only install: erase to the candidate's last 4 KB sector)

def sector_end(offset, length, sector=SECTOR):
    return offset + (length + sector - 1) // sector * sector


def assemble_expected(before, candidate, offset=APP_OFFSET, size=APP_SIZE):
    """The full flash image after writing `candidate` at `offset` (returns image, erased end).

    esptool erases whole 4 KB sectors covering the written bytes; everything
    else is untouched, so only [offset, end) may differ from `before`.
    """
    if not candidate:
        raise ValueError("Candidate image is empty")
    if len(candidate) > size:
        raise ValueError("Candidate exceeds the application partition")
    end = sector_end(offset, len(candidate))
    if end > offset + size or end > len(before):
        raise ValueError("Candidate sectors exceed the application partition")
    expected = bytearray(before)
    expected[offset:end] = b"\xff" * (end - offset)
    expected[offset:offset + len(candidate)] = candidate
    return expected, end


def differing_span(a, b):
    """(first, last+1) of differing bytes between equal-length images, or None when identical."""
    if len(a) != len(b):
        raise ValueError("Images differ in length")
    n = len(a)
    first = None
    for start in range(0, n, SECTOR):
        stop = min(start + SECTOR, n)
        if a[start:stop] != b[start:stop]:
            first = start + next(j for j in range(stop - start) if a[start + j] != b[start + j])
            break
    if first is None:
        return None
    for start in range((n - 1) // SECTOR * SECTOR, -1, -SECTOR):
        stop = min(start + SECTOR, n)
        if a[start:stop] != b[start:stop]:
            return first, start + max(j for j in range(stop - start) if a[start + j] != b[start + j]) + 1
    return None  # unreachable: a difference was found above


def app_image_problems(image, version=None, limit=APP_SIZE):
    problems = []
    if not image or image[0] != ESP_IMAGE_MAGIC:
        problems.append("not an ESP application image (magic 0xE9 missing)")
    if len(image) >= limit:
        problems.append(f"{len(image)} B does not fit below 0x{limit:X}")
    if version and version.encode("ascii") not in image:
        problems.append(f"version string {version} not found in the image")
    return problems


def home_path_hits(image, home=None):
    """FW-PUB-003: occurrences of the build host's home directory (both slash forms, any case) in `image`.
    GCC __FILE__ strings put it there before platformio.ini mapped the build roots (-fmacro-prefix-map);
    a root-like prefix (a drive or "/") counts nothing."""
    home = (str(Path.home()) if home is None else str(home)).rstrip("\\/")
    if len(home.replace("\\", "/").strip("/")) < 4:
        return 0
    lowered = bytes(image or b"").lower()
    forms = {home.replace("\\", "/").lower().encode("utf-8"), home.replace("/", "\\").lower().encode("utf-8")}
    return sum(lowered.count(form) for form in forms)


def release_image_problems(image, home=None):
    """What keeps an accepted image from being staged as a release asset (package_nanod_cc5.py): it must not
    carry the build host's home directory (FW-PUB-003). Installs and rollbacks of older images do not use it."""
    hits = home_path_hits(image, home)
    if hits:
        return [f"the image holds the build host's home directory {hits} time(s) (__FILE__ paths; FW-PUB-003): "
                "build with platformio.ini's path_prefix_map.py pre-script from a clean build folder"]
    return []


def build_markers(image):
    """The CC_BUILD_BINARY numbers whose marker "cc-build-binary:<n>" the image holds, sorted."""
    return sorted({int(n) for n in re.findall(re.escape(BUILD_MARKER_PREFIX) + rb"(\d+)", bytes(image or b""))})


def binary_image_problems(image, binary):
    """The image of ladder binary `binary` carries R5 (the ArtDecode task name) exactly when the binary
    compiles R5 in (A and D: CC_ART_ASYNC 1; B, C and E: 0), and a numbered binary (D, E: CC_BUILD_BINARY n)
    carries exactly its own build marker "cc-build-binary:<n>". Empty for None (a release without the ladder)."""
    if binary is None:
        return []
    problems = []
    want = LCD_BINARIES[binary]["artAsync"]
    has = R5_IMAGE_MARKER in (image or b"")
    if has != want:
        problems.append(f"binary {binary} must {'' if want else 'not '}contain the R5 decode task "
                        f"({R5_IMAGE_MARKER.decode('ascii')!r}), but the image {'does' if has else 'does not'}: "
                        "the build flags did not take effect")
    number = binary_build_number(binary)
    if number is not None:
        found = build_markers(image)
        if found != [number]:
            problems.append(f"binary {binary} must carry the build marker "
                            f"'{BUILD_MARKER_PREFIX.decode('ascii')}{number}' (CC_BUILD_BINARY={number}, diag build "
                            f"{binary!r}), but the image holds {', '.join(map(str, found)) or 'none'}: the build "
                            "flags did not take effect")
    return problems


STT_OBJECT = 1                              # ELF symbol type of a data object (st_info & 0xF)


def elf_symbols(path):
    """[(name, st_size, st_type)] of every named entry in an ELF32 little-endian file's symbol tables, what
    `nm -S` lists (read only; no toolchain). Raises ValueError (or struct.error) for a file that is not one."""
    return [(name, size, kind) for name, _value, size, kind in elf_symbol_entries(path)]


def elf_symbol_entries(path):
    """[(name, st_value, st_size, st_type)] of every named entry in an ELF32 little-endian file's symbol tables
    (read only; no toolchain). Raises ValueError (or struct.error) for a file that is not one."""
    data = Path(path).read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError(f"{Path(path).name} is not an ELF32 little-endian file")
    shoff, = struct.unpack_from("<I", data, 0x20)
    shentsize, shnum = struct.unpack_from("<HH", data, 0x2E)
    sections = [struct.unpack_from("<IIIIIIIIII", data, shoff + i * shentsize) for i in range(shnum)]
    symbols = []
    for section in sections:
        if section[1] != 2 or not section[9]:          # SHT_SYMTAB with a nonzero entry size
            continue
        strtab = sections[section[6]]
        base, table_end = strtab[4], strtab[4] + strtab[5]
        for i in range(section[5] // section[9]):
            # Elf32_Sym: st_name, st_value, st_size (offset 8), st_info (offset 12), st_other, st_shndx
            name_offset, value, size, info = struct.unpack_from("<IIIB", data, section[4] + i * section[9])
            if name_offset and base + name_offset < table_end:
                end = data.index(b"\0", base + name_offset)
                symbols.append((data[base + name_offset:end].decode("ascii", "replace"), value, size, info & 0xF))
    return symbols


def elf_symbol_names(path):
    """The symbol names in an ELF32 little-endian file's symbol tables (read only; no toolchain)."""
    return {name for name, _, _ in elf_symbols(path)}


# PRESENTATION_V5 12.4: the build-only check of every binary also records sizeof(CCFrame) and the size of the
# ALIVE instance (`nm`). Both are read as st_size of a data object in firmware.elf's symbol table: the first
# candidate name that has exactly one object size. The ALIVE instance is hmi_thread.cpp's `CCAlive alive;` and the
# CCFrame-typed global is hmi_thread.cpp's `CCFrame cc_hmi_frame;`, both in an anonymous namespace (hence the
# mangled names; the plain names cover a move out of it). The 2026-09-26 builds: 1,124 B and 11,284 B in A, B, C.
CCFRAME_SYMBOLS = ("_ZN12_GLOBAL__N_112cc_hmi_frameE", "cc_hmi_frame")
ALIVE_INSTANCE_SYMBOLS = ("_ZN12_GLOBAL__N_15aliveE", "alive")
V5_SIZE_FIELDS = ("ccFrameBytes", "aliveInstanceBytes")


def elf_object_size(symbols, candidates):
    """(name, st_size) of the first of `candidates` naming data objects of exactly one nonzero size in
    `symbols` (elf_symbols output); (None, None) when none does (missing, or two objects of that name that
    differ in size)."""
    for candidate in candidates:
        sizes = {size for name, size, kind in symbols if name == candidate and kind == STT_OBJECT and size}
        if len(sizes) == 1:
            return candidate, sizes.pop()
    return None, None


def v5_size_record(symbols):
    """The PRESENTATION_V5 12.4 size fields of a build record's heapProjection, from elf_symbols output (None:
    no readable firmware.elf): ccFrameBytes and aliveInstanceBytes (None when not found) and the symbols read."""
    frame_symbol, frame_bytes = elf_object_size(symbols or [], CCFRAME_SYMBOLS)
    alive_symbol, alive_bytes = elf_object_size(symbols or [], ALIVE_INSTANCE_SYMBOLS)
    return {"ccFrameBytes": frame_bytes, "ccFrameSymbol": frame_symbol,
            "aliveInstanceBytes": alive_bytes, "aliveInstanceSymbol": alive_symbol,
            "sizesSource": "firmware.elf symbol table (st_size, as nm -S lists it)"}


def binary_elf_problems(symbols, binary):
    """The ELF of ladder binary `binary` links the R3 second draw buffer exactly when the binary compiles
    DMA in (A, B and D: CC_LCD_DMA 1; C and E: 0). `symbols` from elf_symbol_names; None means the ELF is missing."""
    if binary is None:
        return []
    if symbols is None:
        return [f"firmware.elf is missing, so the R3 (DMA) pipeline of binary {binary} cannot be confirmed"]
    want = LCD_BINARIES[binary]["lcdDma"]
    has = R3_ELF_SYMBOL in symbols
    if has == want:
        return []
    return [f"binary {binary} must {'' if want else 'not '}link the R3 draw buffer {R3_ELF_SYMBOL!r}, but the ELF "
            f"{'does' if has else 'does not'}: the build flags did not take effect"]


# ---------------------------------------------------------------------------
# The LCD data-line gate (build-only; binary A's dark LCD). TFT_eSPI 2.5.43 on the ESP32-S3 (Processors/
# TFT_eSPI_ESP32_S3.h 340-342, the FSPI branch): an unset or -1 TFT_MISO becomes TFT_MOSI. tft.initDMA() then calls
# spi_bus_initialize with mosi == miso, which leaves the pin driven by FSPIQ_OUT (102) instead of FSPID (103).

def platformio_build_flags(ini_text, env=PIO_ENV):
    """The build_flags tokens of [env:<env>] in platformio.ini text, in order (continuation lines included; ';'
    and '#' comment lines and inline ' ;' comments dropped). Tokens are whitespace-split: enough for -D names."""
    flags, section, in_flags = [], None, False
    for raw in (ini_text or "").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        line = re.split(r"\s;", raw, maxsplit=1)[0].rstrip()
        if not raw[:1].isspace():
            in_flags = False
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip()
                continue
            if section == f"env:{env}" and "=" in line:
                key, _, value = line.partition("=")
                in_flags = key.strip() == "build_flags"
                if in_flags:
                    flags += value.split()
            continue
        if in_flags and section == f"env:{env}":
            flags += line.split()
    return flags


def _defines(tokens):
    """{name: value (str) or True} of the -D tokens, a later definition winning (GCC redefines in order)."""
    values = {}
    for token in tokens:
        match = re.fullmatch(r"-D([A-Za-z_]\w*)(?:=(.*))?", str(token).strip())
        if match:
            values[match.group(1)] = True if match.group(2) is None else match.group(2)
    return values


def _ini_string_define(value):
    """A -D string value as platformio.ini writes it (\\"1.0.0\\" or "1.0.0") without its quotes, or None."""
    if not isinstance(value, str):
        return None
    text = value.replace('\\"', '"').strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return text or None


def firmware_version_defines(ini_text=None):
    """(NANO_FIRMWARE_PUBLIC, NANO_FIRMWARE_VERSION) of platformio.ini's [env:nanofoc_d] build_flags (None for a
    name it does not set). `ini_text` None reads FIRMWARE_SOURCE/platformio.ini (None, None when unreadable)."""
    if ini_text is None:
        try:
            ini_text = (FIRMWARE_SOURCE / "platformio.ini").read_text(encoding="utf-8")
        except OSError:
            return None, None
    values = _defines(platformio_build_flags(ini_text))
    return (_ini_string_define(values.get("NANO_FIRMWARE_PUBLIC")),
            _ini_string_define(values.get("NANO_FIRMWARE_VERSION")))


def reported_firmware_versions(profile, binary=None, ini_text=None):
    """The settings "firmwareVersion" strings a knob running `profile` may report, as a tuple (FW-PUB-004).

    A source that sets NANO_FIRMWARE_PUBLIC for this profile's internal id (platformio.ini NANO_FIRMWARE_VERSION ==
    profile.version) reports "<public>+<internal after its first '-'>.<binary letter>" (src/cc_fw_version.h, e.g.
    1.0.0+cc5.7.F); without a letter (CC_BUILD_BINARY unset) it ends at the build id. The letter is `binary`, else
    the profile's own binary, else any binary of its ladder that the build gives a CC_BUILD_BINARY number. Any
    other profile (an earlier release, or a source without the public define) reports profile.version itself."""
    public, internal = firmware_version_defines(ini_text)
    if not public or internal != profile.version:
        return (profile.version,)
    build = internal.split("-", 1)[1] if "-" in internal else ""
    if not build:
        return (public,)
    letter = binary or getattr(profile, "binary", None)
    letters = [letter] if letter else list(profile.pipeline_binaries())
    numbered = [name for name in letters if binary_build_number(name)]
    if not numbered:
        return (f"{public}+{build}",)
    return tuple(f"{public}+{build}.{name}" for name in numbered)


def knob_reported_version(profile, binary=None, public=None, ini_text=None):
    """The one settings "firmwareVersion" string a knob running `profile` reports (FW-PUB-004), mirroring
    src/cc_fw_version.h: "<public>+<profile.version after its first '-'>" plus ".<letter>" when the binary's build
    flags carry -DCC_BUILD_BINARY=n with n in 1..6 (letter chr(ord('A') + n - 1): D 4, E 5, F 6), nothing otherwise.
    The binary is `binary`, else profile.binary. `public` None takes the profile's public_version field (set by the
    release stage), else platformio.ini's NANO_FIRMWARE_PUBLIC when its NANO_FIRMWARE_VERSION is profile.version.
    Without a public version the knob reports profile.version itself (an image built before FW-PUB-004)."""
    if public is None:
        public = getattr(profile, "public_version", None)
    if public is None:
        defined, internal = firmware_version_defines(ini_text)
        public = defined if internal == profile.version else None
    if not public:
        return profile.version
    build = profile.version.split("-", 1)[1] if "-" in profile.version else ""
    if not build:
        return public
    number = binary_build_number(binary or getattr(profile, "binary", None))
    letter = f".{chr(ord('A') + number - 1)}" if number and 1 <= number <= 6 else ""
    return f"{public}+{build}{letter}"


def reports_version(value, profile, binary=None, public=None, ini_text=None):
    """True when a knob's reported "firmwareVersion" `value` names `profile`: the internal id itself (an image built
    before FW-PUB-004) or knob_reported_version(profile, binary, public, ini_text) (the public form)."""
    if not isinstance(value, str) or not value:
        return False
    return value == profile.version or value == knob_reported_version(profile, binary, public, ini_text)


# FW-PUB-004: the public release record of the Desk Dial + knob pair. One public version names one firmware image:
# release.json maps each public version to the image's SHA-256, the string the knob reports and the internal
# manifest; Desk Dial's ProductVersion is the public version (FileVersion keeps its own series).
RELEASE_RECORD = FIRMWARE_OUT / "release.json"
DESKTOP_VERSION_FILE = APP / "desktop-version.txt"
INTERNAL_ID = re.compile(r"cc\d+(?:\.\d+)?", re.IGNORECASE)     # an internal build id (cc5, cc5.7)
PUBLIC_VERSION = re.compile(r"\d+\.\d+\.\d+")                      # semver core, no pre-release or build part


def public_version_fields(profile, binary=None, ini_text=None):
    """The manifest fields of FW-PUB-004: {"publicVersion": NANO_FIRMWARE_PUBLIC or None, "reportedVersion": the one
    settings "firmwareVersion" string this image reports, or None when it is not one string (no public define for
    this profile, or no binary letter to pick)}."""
    public, internal = firmware_version_defines(ini_text)
    if not public or internal != profile.version:
        return {"publicVersion": None, "reportedVersion": None}
    reported = reported_firmware_versions(profile, binary, ini_text)
    return {"publicVersion": public, "reportedVersion": reported[0] if len(reported) == 1 else None}


def desktop_product_version(text=None):
    """Desk Dial's ProductVersion string from desktop-version.txt (`text` None reads the file; None when absent)."""
    if text is None:
        try:
            text = DESKTOP_VERSION_FILE.read_text(encoding="utf-8")
        except OSError:
            return None
    match = re.search(r"StringStruct\(\s*'ProductVersion'\s*,\s*'([^']*)'\s*\)", text)
    return match.group(1) if match else None


def release_entry(manifest, product_version):
    """One release.json entry from a packaged firmware manifest (FW-PUB-004 fields present) and Desk Dial's
    ProductVersion. Stops when the manifest has no public version or no single reported string."""
    public, reported = manifest.get("publicVersion"), manifest.get("reportedVersion")
    if not public or not reported:
        raise SystemExit("the manifest records no public version or reported string; package the binary again")
    image = manifest.get("image") or {}
    binary = (manifest.get("binary") or {}).get("name")
    return {"version": public,
            "firmware": {"reportedVersion": reported, "internalVersion": manifest.get("firmwareVersion"),
                         "binary": binary, "image": image.get("file"), "sha256": image.get("sha256"),
                         "manifest": f"manifest-{manifest.get('firmwareVersion')}{'-' + binary if binary else ''}.json"},
            "desktop": {"productVersion": product_version}}


def add_release(record, entry):
    """release.json content with `entry` added (a new dict). A public version is never reused for another image:
    an existing version with a different firmware SHA-256 stops; the same image again replaces its entry."""
    releases = [dict(r) for r in (record or {}).get("releases", [])]
    for index, old in enumerate(releases):
        if old.get("version") == entry["version"]:
            if old["firmware"].get("sha256") != entry["firmware"]["sha256"]:
                raise SystemExit(f"public version {entry['version']} already names image "
                                 f"{str(old['firmware'].get('sha256'))[:8]}; a changed image needs a new public version")
            releases[index] = entry
            break
    else:
        releases.append(entry)
    return {"schema": 1, "current": entry["version"], "releases": releases}


def release_version_problems(record, product_version):
    """What breaks the FW-PUB-004 rules in a release.json record (empty list = good): the current version is Desk
    Dial's ProductVersion; each version is a public semver core with no internal cc id; its reported firmware string
    starts with "<version>+" and ends with ".<binary letter>"; each version maps to one SHA-256."""
    problems = []
    releases = (record or {}).get("releases") or []
    if not releases:
        return ["release.json lists no release"]
    current = record.get("current")
    if current != product_version:
        problems.append(f"ProductVersion {product_version} is not the current release {current}")
    shas = {}
    for entry in releases:
        version, fw = entry.get("version") or "", entry.get("firmware") or {}
        reported, binary = fw.get("reportedVersion") or "", fw.get("binary") or ""
        if not PUBLIC_VERSION.fullmatch(version) or INTERNAL_ID.search(version):
            problems.append(f"{version!r} is not a public version")
        desktop = (entry.get("desktop") or {}).get("productVersion") or ""
        if desktop != version or INTERNAL_ID.search(desktop):
            problems.append(f"{version}: Desk Dial ProductVersion {desktop!r} is not the public version")
        if not reported.startswith(f"{version}+"):
            problems.append(f"{version}: reported firmware {reported!r} does not start with it")
        if binary not in ALL_BINARIES or not reported.endswith(f".{binary}"):
            problems.append(f"{version}: reported firmware {reported!r} does not end with the binary letter {binary!r}")
        sha = fw.get("sha256")
        if not sha or not re.fullmatch(r"[0-9a-f]{64}", sha):
            problems.append(f"{version}: no firmware SHA-256")
        shas.setdefault(version, set()).add(sha)
    problems += [f"{version} maps to {len(s)} images" for version, s in shas.items() if len(s) > 1]
    return problems


def tft_spi_config(ini_text, flags=()):
    """The LCD SPI pins a build compiles with: platformio.ini's [env:nanofoc_d] build_flags, then `flags` (the
    binary's PLATFORMIO_BUILD_FLAGS, which PlatformIO appends), with TFT_eSPI's S3 rule applied (FSPI: an unset or
    -1 TFT_MISO becomes TFT_MOSI). {"mosi", "miso" (as declared), "effectiveMiso", "sclk", "port", "misoEqualsMosi",
    "problems"}: a missing TFT_MOSI, or USE_HSPI_PORT (the encoder owns HSPI, foc_thread.cpp:43), is a problem."""
    values = _defines(list(platformio_build_flags(ini_text)) + list(flags))

    def pin(name):
        try:
            return int(str(values[name]).strip())
        except (KeyError, ValueError):
            return None

    mosi, miso, sclk = pin("TFT_MOSI"), pin("TFT_MISO"), pin("TFT_SCLK")
    hspi = "USE_HSPI_PORT" in values
    problems = []
    if mosi is None:
        problems.append(f"TFT_MOSI is not set (an integer) in platformio.ini [env:{PIO_ENV}] build_flags, so the LCD "
                        "data line cannot be checked")
    if hspi:
        problems.append("USE_HSPI_PORT is set: the encoder owns HSPI (foc_thread.cpp:43); the LCD must stay on FSPI "
                        "(SPI2_HOST)")
    effective = miso if miso not in (None, -1) else (-1 if hspi else mosi)
    return {"mosi": mosi, "miso": miso, "effectiveMiso": effective, "sclk": sclk,
            "port": "HSPI (SPI3_HOST)" if hspi else "FSPI (SPI2_HOST)",
            "misoEqualsMosi": mosi is not None and effective == mosi,
            "rule": "TFT_eSPI_ESP32_S3.h 340-342: on the S3's FSPI port an unset or -1 TFT_MISO becomes TFT_MOSI",
            "problems": problems}


def mosi_reattach_linked(symbols):
    """True when `symbols` (elf_symbol_names) hold cc_lcd_mosi_reattach (extern "C", or a C++ mangled form)."""
    return any(name == LCD_MOSI_REATTACH_SYMBOL or (name.startswith("_Z") and LCD_MOSI_REATTACH_SYMBOL in name)
               for name in symbols)


def _lcd_setup_call_label(name):
    """The LCD_SETUP_CALLS label of symbol `name` (a mangled TFT_eSPI method by prefix; the extern "C" re-attach by
    name, or a C++ mangled form of it), else None."""
    for label, pattern in LCD_SETUP_CALLS:
        if pattern.startswith("_Z"):
            if name.startswith(pattern):
                return label
        elif name == pattern or (name.startswith("_Z") and pattern in name):
            return label
    return None


def lcd_run_call_order(elf_path, objdump=None, run=None):
    """The LCD setup calls LcdThread::run() makes, in address order, as labels of LCD_SETUP_CALLS ("begin",
    "initDMA", "reattach", "startWrite"): a read-only disassembly (`objdump -d`, default XTENSA_OBJDUMP) of that one
    function's address range in firmware.elf, whose direct calls (call0/4/8/12 <address>) are matched against the
    symbol table. `run` replaces subprocess.run (tests). Raises ValueError when the ELF has no LcdThread::run, and
    OSError or subprocess.CalledProcessError when objdump cannot run."""
    entries = elf_symbol_entries(elf_path)
    run_symbol = next(((value, size) for name, value, size, _ in entries if name == LCD_RUN_SYMBOL and size), None)
    if run_symbol is None:
        raise ValueError(f"{Path(elf_path).name} has no {LCD_RUN_SYMBOL} (LcdThread::run) in its symbol table")
    targets = {}
    for name, value, _size, _kind in entries:
        label = _lcd_setup_call_label(name)
        if label:
            targets[value] = label
    start, size = run_symbol
    done = (run or subprocess.run)(
        [str(objdump or XTENSA_OBJDUMP), "-d", f"--start-address=0x{start:x}", f"--stop-address=0x{start + size:x}",
         str(elf_path)], capture_output=True, text=True, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    order = []
    for line in (done.stdout or "").splitlines():
        match = re.match(r"\s*[0-9a-f]+:\s+[0-9a-f]+\s+call(?:0|4|8|12)\s+([0-9a-f]+)\b", line)
        if match and int(match.group(1), 16) in targets:
            order.append(targets[int(match.group(1), 16)])
    return order


def lcd_call_order_problems(order, binary, required):
    """The problems of LcdThread::run()'s LCD setup call order `order` (lcd_run_call_order) for ladder binary
    `binary`; `required`: the build needs the MOSI re-attach (DMA with MISO == MOSI). Then every initDMA call must be
    directly followed by the re-attach and startWrite (LCD_CALL_ORDER_RULE). A binary without DMA must not call
    initDMA (its flags did not take effect)."""
    dma = bool((LCD_BINARIES.get(binary) or {}).get("lcdDma"))
    if not dma:
        return ([f"binary {binary} compiles no DMA, but LcdThread::run() calls TFT_eSPI::initDMA: the build flags did "
                 "not take effect"] if "initDMA" in order else [])
    if not required:
        return []
    if "initDMA" not in order:
        return [f"LcdThread::run() of binary {binary} shows no direct call to TFT_eSPI::initDMA "
                f"(calls: {', '.join(order) or 'none'}), so the MOSI re-attach after it cannot be confirmed"]
    problems = []
    for i, label in enumerate(order):
        if label == "initDMA" and order[i + 1:i + 3] != ["reattach", "startWrite"]:
            problems.append(f"LcdThread::run() of binary {binary} calls {', '.join(order)}: TFT_eSPI::initDMA is not "
                            f"directly followed by {LCD_MOSI_REATTACH_SYMBOL} and then startWrite, so the pin may stay "
                            f"on FSPIQ_OUT ({LCD_MOSI_BROKEN_SIGNAL}, binary A's dark LCD) although the re-attach "
                            "links: do not flash it")
    return problems


def lcd_mosi_gate(config, symbols, binary, call_order=None, call_order_error=None):
    """The build-only LCD data-line gate of ladder binary `binary`: `config` from tft_spi_config, `symbols` from
    elf_symbol_names (None: no readable ELF), `call_order` from lcd_run_call_order (None: not read, with
    `call_order_error` saying why). A binary that compiles DMA in (tft.initDMA()) with the effective TFT_MISO equal to
    TFT_MOSI must link cc_lcd_mosi_reattach, which puts FSPID back on the pin after spi_bus_initialize, and call it
    right after every initDMA and before startWrite (LCD_CALL_ORDER_RULE); without it the build is binary A's dark
    LCD. The record build_nanod_cc5.py stores as "lcdMosiGate": pins, port, dma, reattachRequired, reattachLinked,
    callOrder, callOrderRule, expectedMosiSignal, problems, passed."""
    dma = bool((LCD_BINARIES.get(binary) or {}).get("lcdDma"))
    linked = None if symbols is None else mosi_reattach_linked(symbols)
    required = dma and bool(config.get("misoEqualsMosi"))
    problems = list(config.get("problems") or [])
    if required and symbols is None:
        problems.append(f"firmware.elf is missing or unreadable, so binary {binary}'s LCD MOSI re-attach "
                        f"({LCD_MOSI_REATTACH_SYMBOL}) cannot be confirmed")
    elif required and not linked:
        problems.append(f"binary {binary} calls tft.initDMA() with TFT_MISO = TFT_MOSI = GPIO{config.get('mosi')} "
                        f"(TFT_eSPI's S3 rule), which re-routes the pin to FSPIQ_OUT ({LCD_MOSI_BROKEN_SIGNAL}) so no "
                        f"pixel reaches the GC9A01 (binary A's dark LCD), and its ELF does not link "
                        f"{LCD_MOSI_REATTACH_SYMBOL}: do not flash it")
    elif required and call_order is None:
        problems.append(f"the LCD setup call order in LcdThread::run() of binary {binary} was not read"
                        + (f" ({call_order_error})" if call_order_error else "")
                        + f", so the re-attach right after tft.initDMA() cannot be confirmed")
    if call_order is not None and (linked or not required):     # an unlinked re-attach is reported above
        problems += lcd_call_order_problems(call_order, binary, required)
    return {"pins": {k: config.get(k) for k in ("mosi", "miso", "effectiveMiso", "sclk")}, "port": config.get("port"),
            "misoEqualsMosi": config.get("misoEqualsMosi"), "dma": dma, "reattachRequired": required,
            "reattachSymbol": LCD_MOSI_REATTACH_SYMBOL, "reattachLinked": linked,
            "callOrder": None if call_order is None else list(call_order), "callOrderRule": LCD_CALL_ORDER_RULE,
            "callOrderError": call_order_error,
            "expectedMosiSignal": LCD_MOSI_SIGNAL, "problems": problems, "passed": not problems}


def lcd_mosi_gate_problems(config, symbols, binary, call_order=None, call_order_error=None):
    """lcd_mosi_gate's problems only (empty: the build may be flashed as far as the LCD data line goes)."""
    return lcd_mosi_gate(config, symbols, binary, call_order, call_order_error)["problems"]


def desktop_bundle_exe(bundle, app=None):
    """The companion executable of desktop bundle folder `bundle` (app/<bundle>):
    Desk Dial bundles hold DeskDial\\DeskDial.exe, the v2-v6 ones NanoDControlCenter\\NanoDControlCenter.exe.
    The first that exists, else None."""
    root = Path(APP if app is None else app) / bundle
    for image in COMPANION_IMAGES:
        exe = root / Path(image).stem / image
        if exe.is_file():
            return exe
    return None


# ---------------------------------------------------------------------------
# Artwork packets (contract section 1: 120x120 RGB565_LE, 384 B chunks, CRC-32)

def art_pixels(key):
    """Deterministic, visibly patterned 120x120 RGB565_LE test cover for `key`."""
    seed = zlib.crc32(key.encode("utf-8"))
    r0, g0, b0 = seed & 31, (seed >> 5) & 63, (seed >> 11) & 31
    out = bytearray()
    for y in range(ART_WIDTH):
        for x in range(ART_WIDTH):
            r = (r0 + x * 31 // ART_WIDTH) & 31
            g = (g0 + y * 63 // ART_WIDTH) & 63
            b = (b0 + ((x ^ y) >> 3)) & 31
            out += struct.pack("<H", (r << 11) | (g << 5) | b)
    return bytes(out)


def art_crc(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def art_messages(ident, key, data, *, chunk=ART_CHUNK, crc=None):
    """The begin/data.../commit art bodies the companion's DeviceBridge would send."""
    messages = [{"id": ident, "key": key, "op": "begin", "bytes": len(data),
                 "crc32": art_crc(data) if crc is None else crc}]
    for offset in range(0, len(data), chunk):
        messages.append({"id": ident, "key": key, "op": "data", "offset": offset,
                         "data": base64.b64encode(data[offset:offset + chunk]).decode("ascii")})
    messages.append({"id": ident, "key": key, "op": "commit"})
    return messages


def expected_ack_offset(message):
    if message["op"] == "begin":
        return 0
    if message["op"] == "data":
        return message["offset"] + len(base64.b64decode(message["data"]))
    return message.get("bytes", ART_BYTES)


def art_transfer(knob, ident, key, data, *, crc=None, between=None, stop_after_chunks=None,
                 clock=time.monotonic):
    """begin/data.../commit over `knob.art(body) -> (artAck, seconds)`, one line outstanding.

    Like DeviceBridge: a begin answered with offset == size is a cache hit and goes
    straight to commit. Stops at the first error (recorded with its op). `between` runs
    after every acknowledged line (the stress run sends a frame there).
    """
    result = {"key": key, "beginOffset": None, "cached": False, "committed": False, "error": None,
              "errorOp": None, "chunkSeconds": [], "chunks": 0}
    started = clock()
    for body in art_messages(ident, key, data, crc=crc):
        if body["op"] == "data" and result["cached"]:
            continue
        if stop_after_chunks is not None and body["op"] != "begin" and result["chunks"] >= stop_after_chunks:
            break
        ack, seconds = knob.art(body)
        if "error" in ack:
            result["error"], result["errorOp"] = ack["error"], body["op"]
            break
        if body["op"] == "begin":
            result["beginOffset"] = ack.get("offset")
            result["cached"] = ack.get("offset") == len(data)
        elif body["op"] == "data":
            result["chunkSeconds"].append(seconds)
            result["chunks"] += 1
            if ack.get("offset") != expected_ack_offset(body):
                result["error"], result["errorOp"] = f"offset {ack.get('offset')} != {expected_ack_offset(body)}", "data"
                break
        else:
            result["committed"] = ack.get("offset") == len(data)
        if between:
            between()
    result["seconds"] = round(clock() - started, 3)
    return result


# ---------------------------------------------------------------------------
# artwork2 media packets (ARTWORK2.md section 4: begin/data.../commit and have, one line
# outstanding, answered by exactly one mediaAck each)

def media_messages(ident, kind, key, data, *, chunk=None, crc=None):
    """The begin/data.../commit media bodies the v4 companion's push engine sends."""
    chunk = chunk or presentation().MEDIA_CHUNK_BYTES
    messages = [{"id": ident, "op": "begin", "kind": kind, "key": key, "bytes": len(data),
                 "crc32": art_crc(data) if crc is None else crc}]
    for offset in range(0, len(data), chunk):
        messages.append({"id": ident, "op": "data", "kind": kind, "key": key, "offset": offset,
                         "data": base64.b64encode(data[offset:offset + chunk]).decode("ascii")})
    messages.append({"id": ident, "op": "commit", "kind": kind, "key": key})
    return messages


def media_transfer(knob, ident, kind, key, data, *, crc=None, between=None, stop_after_chunks=None,
                   clock=None):
    """begin/data.../commit over `knob.media(body) -> (mediaAck, seconds)`, stop-and-wait.

    A begin answered with offset == size is a begin-hit: no data follows, and the commit
    ends the hit context (4.4). Stops at the first error (recorded with its op). `between`
    runs after every acknowledged line (the stress runs send a frame there). `seconds` (begin
    to the last ack) is measured on `clock`, by default the knob's own clock (RawKnob: the
    monotonic clock its per-line seconds use), else time.monotonic.
    """
    clock = clock or getattr(knob, "clock", None) or time.monotonic
    result = {"kind": kind, "key": key, "bytes": len(data), "beginOffset": None, "hit": False,
              "committed": False, "error": None, "errorOp": None, "lineSeconds": [], "chunks": 0}
    started = clock()
    for body in media_messages(ident, kind, key, data, crc=crc):
        if body["op"] == "data" and result["hit"]:
            continue
        if stop_after_chunks is not None and body["op"] != "begin" and result["chunks"] >= stop_after_chunks:
            break
        ack, seconds = knob.media(body)
        result["lineSeconds"].append(seconds)
        if "error" in ack:
            result["error"], result["errorOp"] = ack["error"], body["op"]
            break
        if body["op"] == "begin":
            result["beginOffset"] = ack.get("offset")
            result["hit"] = ack.get("offset") == len(data)
            if not result["hit"] and ack.get("offset") != 0:
                result["error"], result["errorOp"] = f"begin offset {ack.get('offset')}", "begin"
                break
        elif body["op"] == "data":
            result["chunks"] += 1
            expected = body["offset"] + len(base64.b64decode(body["data"]))
            if ack.get("offset") != expected:
                result["error"], result["errorOp"] = f"offset {ack.get('offset')} != {expected}", "data"
                break
        else:
            result["committed"] = ack.get("offset") == len(data)
        if between:
            between()
    result["seconds"] = round(clock() - started, 3)
    return result


def media_have(knob, ident, kind, keys):
    """One `have` query; returns the mediaAck (its "have" list answers `keys` in order)."""
    ack, _ = knob.media({"id": ident, "op": "have", "kind": kind, "keys": list(keys)})
    return ack


# ---------------------------------------------------------------------------
# artwork2 payloads (ARTWORK2.md section 5), built from the design reference assets with the
# companion's own v1 pipeline (artwork.prepare_artwork) and constants. Pillow and the companion
# package are imported only when a payload is built (the companion venv has both).

_TRANSPOSES = (None, "FLIP_LEFT_RIGHT", "FLIP_TOP_BOTTOM", "ROTATE_90", "ROTATE_180", "ROTATE_270",
               "TRANSPOSE", "TRANSVERSE")
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _companion_modules():
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from control_center import artwork, windows
    return artwork, windows


def jpeg_layout(data):
    """Markers of a JPEG up to its first scan: {"sof", "precision", "width", "height", "components",
    "sampling" (each component's H/V byte, 0x22 = 2x2), "segments"}."""
    if not isinstance(data, (bytes, bytearray)) or data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG (no SOI)")
    layout = {"sof": None, "precision": None, "width": None, "height": None, "components": None,
              "sampling": [], "segments": []}
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ValueError(f"marker expected at {pos}")
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        layout["segments"].append(marker)
        if marker in _SOF_MARKERS:
            if pos + 10 > len(data):
                raise ValueError("truncated frame header")
            layout["sof"] = marker
            layout["precision"] = data[pos + 4]
            layout["height"], layout["width"] = struct.unpack(">HH", data[pos + 5:pos + 9])
            layout["components"] = data[pos + 9]
            layout["sampling"] = [data[pos + 11 + 3 * i] for i in range(layout["components"])
                                  if pos + 11 + 3 * i < min(len(data), pos + 2 + length)]
        if marker == 0xDA:
            return layout
        pos += 2 + length
    raise ValueError("no scan")


# Section 5 chroma subsampling, as each component's H/V sampling byte (Y, Cb, Cr).
_COVER_SAMPLING = {(0x22, 0x11, 0x11): "4:2:0", (0x11, 0x11, 0x11): "4:4:4"}


def _decode_problem(data):
    """None when Pillow decodes the whole image (a truncated image is an error), else why not."""
    from PIL import Image, ImageFile
    truncated = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        with Image.open(io.BytesIO(bytes(data))) as image:
            image.load()
    except Exception as exc:
        return f"not decodable ({type(exc).__name__}: {exc})"
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = truncated
    return None


def cover_payload_problems(data):
    """Why `data` is not an artwork2 cover (empty list: it is one).

    Section 5: a baseline (SOF0) JFIF JPEG of exactly 240x240 with three components of 8-bit
    samples, 4:2:0 or 4:4:4 chroma subsampling, at most COVER_MAX_BYTES, without EXIF (APP1), ICC
    (APP2) or comment segments. Section 4.3: it ends with EOI as its last two bytes (the knob's
    commit check refuses a cover cut short or followed by trailing bytes) and decodes completely.
    """
    contract = presentation()
    try:
        layout = jpeg_layout(data)
    except ValueError as exc:
        return [str(exc)]
    problems = []
    if layout["sof"] != 0xC0:
        problems.append(f"not baseline (SOF 0x{layout['sof'] or 0:02X})")
    if (layout["width"], layout["height"]) != (contract.COVER_SIZE, contract.COVER_SIZE):
        problems.append(f"{layout['width']}x{layout['height']}, not {contract.COVER_SIZE}x{contract.COVER_SIZE}")
    if layout["components"] != 3:
        problems.append(f"{layout['components']} components")
    if layout["precision"] != 8:
        problems.append(f"{layout['precision']}-bit samples, not 8-bit")
    if layout["components"] == 3 and tuple(layout["sampling"]) not in _COVER_SAMPLING:
        factors = ", ".join(f"{s >> 4}x{s & 15}" for s in layout["sampling"])
        problems.append(f"sampling factors {factors}: not 4:2:0 or 4:4:4")
    if len(data) > contract.COVER_MAX_BYTES:
        problems.append(f"{len(data)} B > {contract.COVER_MAX_BYTES}")
    if 0xE0 not in layout["segments"]:
        problems.append("no JFIF APP0")
    extra = [f"0x{m:02X}" for m in layout["segments"] if m in (0xE1, 0xE2, 0xFE)]
    if extra:
        problems.append(f"EXIF/ICC/comment segments {extra}")
    if bytes(data[-2:]) != b"\xff\xd9":
        problems.append("does not end with EOI (FF D9): cut short or followed by trailing bytes")
    decode = _decode_problem(data)
    if decode:
        problems.append(decode)
    return problems


def cover_jpeg(preview):
    """(key, jpeg) of a 240x240 composited RGB image, or None when no ladder quality fits.

    The companion's own section 5 encoder (control_center/artwork.cover_jpeg: the quality ladder
    COVER_JPEG_QUALITIES, the first result of at most COVER_MAX_BYTES, key =
    sha256(jpeg)[:COVER_KEY_CHARS]), so the checks send exactly the covers the v4 companion sends.
    """
    artwork, _ = _companion_modules()
    key, data = artwork.cover_jpeg(preview)
    return None if data is None else (key, data)


def _textured(image, seed):
    """A deterministic high-detail version of `image` (larger JPEGs: more data lines per cover)."""
    from PIL import Image
    noise = Image.frombytes("L", image.size, random.Random(seed).randbytes(image.width * image.height))
    return Image.blend(image, Image.merge("RGB", (noise, noise.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                                                  noise.transpose(Image.Transpose.FLIP_TOP_BOTTOM))), 0.85)


def _salt_stamp(image, seed):
    """A 12x12 block of a `seed`-derived colour at (6, 6): a run-specific but real cover (the top-left
    corner is drawn at 0.8 opacity, above the scrim's solid part)."""
    from PIL import Image
    rng = random.Random(seed)
    image.paste(Image.new("RGB", (12, 12), (rng.randrange(256), rng.randrange(256), rng.randrange(256))), (6, 6))
    return image


def _cover_source(path, variant, salt=""):
    """Encoded source bytes for cover variant `variant` of a design cover (at most 600 px)."""
    from PIL import Image
    with Image.open(path) as source:
        image = source.convert("RGB")
    transpose = _TRANSPOSES[variant % len(_TRANSPOSES)]
    if transpose:
        image = image.transpose(getattr(Image.Transpose, transpose))
    image.thumbnail((600, 600), Image.Resampling.LANCZOS)
    if variant % 3 == 2:
        image = _textured(image, f"{path.name}:{variant}")
    if salt:
        image = _salt_stamp(image, f"{salt}:{path.name}:{variant}")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


_cover_pools = {}      # salt -> (asked size, pool)
_icon_pools = {}       # salt -> pool


def cover_pool(size=72, salt=""):
    """Distinct real covers [(key, jpeg)]: the design covers, each in up to eight orientations,
    two orientations in three textured, through the companion's artwork.prepare_artwork2 (crop-fit
    240 LANCZOS, 0.8 opacity and the scrim, then its section 5 encoder: `jpeg` and `jpeg_key`
    exactly as the v4 companion builds them). Each also passes cover_payload_problems. A variant
    that no ladder quality fits is left out, so the pool may hold a few fewer than `size`.

    Keys are content hashes and the knob keeps committed covers until it reboots, so a check run
    passes its own `salt` (a small run-specific stamp in each source image): a second run on the
    same boot then uploads cold covers again instead of finding the first run's. Built once per
    salt and process."""
    asked, pool = _cover_pools.get(salt, (0, None))
    if pool is None or size > asked:
        artwork, _ = _companion_modules()
        sources = sorted(q for q in (DESIGN_ASSETS / "covers").iterdir() if q.suffix.lower() in (".jpg", ".png"))
        if not sources:
            raise FileNotFoundError("no design covers")
        pool, seen = [], set()
        for n in range(len(sources) * len(_TRANSPOSES)):
            if len(pool) >= size:
                break
            path, variant = sources[n % len(sources)], n // len(sources)
            prepared = artwork.prepare_artwork2(_cover_source(path, variant, salt))
            if prepared.jpeg is None or prepared.jpeg_key in seen:
                continue
            made = (prepared.jpeg_key, prepared.jpeg)
            problems = cover_payload_problems(made[1])
            if problems:
                raise ValueError(f"cover {path.name}/{variant} is not a section 5 cover: {problems}")
            seen.add(made[0])
            pool.append(made)
        _cover_pools[salt] = (size, pool)
    return list(pool[:size])


def bad_cover_payloads():
    """Payloads that fit a cover upload but must fail "Media decode failed" at commit:
    {"progressive": 240 progressive JPEG, "size120": 120x120 baseline JPEG, "notJpeg": bytes}."""
    from PIL import Image
    artwork, _ = _companion_modules()
    sources = sorted(p for p in (DESIGN_ASSETS / "covers").iterdir() if p.suffix.lower() in (".jpg", ".png"))
    preview, _raw, _dominant = artwork.prepare_artwork(_cover_source(sources[0], 0))
    progressive, small = io.BytesIO(), io.BytesIO()
    preview.save(progressive, format="JPEG", quality=80, subsampling=2, progressive=True)
    preview.resize((120, 120), Image.Resampling.LANCZOS).save(small, format="JPEG", quality=85, subsampling=2)
    return {"progressive": progressive.getvalue(), "size120": small.getvalue(),
            "notJpeg": random.Random("nanod-not-a-jpeg").randbytes(3000)}


def icon_payload(rgba):
    """(key, raw) of a 32x32 RGBA image (section 5) by the companion's own encoder
    (control_center/artwork.icon_payload: alpha-composited onto black, c' = round(c*a/255),
    RGB565 little-endian with rounding, row-major; key = sha256(raw)[:ICON_KEY_CHARS]), so the
    checks send exactly the icons the v4 companion sends. Only 32x32 images (icon_thumbnail's
    output) are taken: another size raises ValueError here instead of being fitted."""
    contract = presentation()
    artwork, _ = _companion_modules()
    if rgba.size != (contract.ICON_SIZE, contract.ICON_SIZE):
        raise ValueError(f"icon is {rgba.size}, not {contract.ICON_SIZE}x{contract.ICON_SIZE}")
    return artwork.icon_payload(rgba)


def synthetic_icon(n, salt=""):
    """(key, raw): a deterministic 2048-byte RGB565 icon pattern (content is not validated); a
    `salt` changes its first pixel."""
    contract = presentation()
    size, out = contract.ICON_SIZE, bytearray()
    for y in range(size):
        for x in range(size):
            r, g, b = (x * 31 // size + n) & 31, (y * 63 // size + 3 * n) & 63, ((x ^ y) + 7 * n) & 31
            out += struct.pack("<H", (r << 11) | (g << 5) | b)
    if salt:
        out[0:2] = struct.pack("<H", zlib.crc32(f"{salt}:{n}".encode("utf-8")) & 0xFFFF)
    raw = bytes(out)
    return hashlib.sha256(raw).hexdigest()[:contract.ICON_KEY_CHARS], raw


def icon_pool(size=64, salt=""):
    """Distinct icons [(key, raw)]: the design app icons in up to eight orientations through
    windows.icon_thumbnail (IconWorker's 32x32 LANCZOS) and icon_payload, then synthetic
    patterns up to `size`. With a `salt` (see cover_pool) each design icon's top-left pixel gets
    a run-specific opaque colour. Built once per salt and process."""
    pool = _icon_pools.get(salt)
    if pool is None or len(pool) < size:
        from PIL import Image
        _, windows = _companion_modules()
        pool, seen = [], set()
        sources = sorted(q for q in (DESIGN_ASSETS / "apps").iterdir() if q.suffix.lower() == ".png")
        for transpose in _TRANSPOSES:
            for path in sources:
                with Image.open(path) as source:
                    image = source.convert("RGBA")
                if transpose:
                    image = image.transpose(getattr(Image.Transpose, transpose))
                thumbnail = windows.icon_thumbnail(image)
                if salt:
                    rng = random.Random(f"{salt}:{path.name}:{transpose}")
                    thumbnail.putpixel((0, 0), (rng.randrange(256), rng.randrange(256), rng.randrange(256), 255))
                made = icon_payload(thumbnail)
                if made[0] not in seen:
                    seen.add(made[0])
                    pool.append(made)
        n = 0
        while len(pool) < size:
            made = synthetic_icon(n, salt)
            n += 1
            if made[0] not in seen:
                seen.add(made[0])
                pool.append(made)
        _icon_pools[salt] = pool
    return list(pool[:size])


class MediaCursor:
    """Hands out pool entries in order, wrapping around: a key comes back only after every
    other pool entry was handed out (the pools are larger than the knob's stores)."""

    def __init__(self, covers, icons):
        self.covers, self.icons, self.at = list(covers), list(icons), {"cover": 0, "icon": 0}

    def next(self, kind):
        pool = self.covers if kind == "cover" else self.icons
        item = pool[self.at[kind] % len(pool)]
        self.at[kind] += 1
        return item

    def cover(self):
        return self.next("cover")

    def icon(self):
        return self.next("icon")


# ---------------------------------------------------------------------------
# Timing statistics and diag margins

def summarize_ms(seconds):
    values = sorted(s * 1000.0 for s in seconds)
    if not values:
        return {"count": 0}
    p95 = values[min(len(values) - 1, max(0, round(0.95 * len(values)) - 1))]
    return {"count": len(values), "minMs": round(values[0], 1), "medianMs": round(statistics.median(values), 1),
            "p95Ms": round(p95, 1), "maxMs": round(values[-1], 1)}


def max_gap(times):
    times = sorted(times)
    return max((b - a for a, b in zip(times, times[1:])), default=None)


REQUIRED_STACKS = ("stackLcd", "stackCom", "stackHmi", "stackFoc")   # stackFoc from 1.0.0-cc5.1
RECORDED_ONLY = ("heapFree", "psramFree", "stackUsbd", "txStalls", "txDroppedBytes")


def diag_margins(diag, heap_bytes=PRE_V5_LVGL_HEAP_BYTES, profile=None):
    """LVGL heap >= 25 % free at its minimum; internal heap minimum (heapMinFree) >=
    HEAP_MIN_FREE_BYTES (1.0.0-cc5.3); every task stack high-water mark > 1 KB.

    A profile with its own memory gates (1.0.0-cc5.4, PRESENTATION_V5 12.2) uses them instead:
    heapMinFree >= 40,960 B and lvglMinFree >= 30 KB; with the R5 decode task compiled in (diag
    artAsync true, binaries A and D) its stack high-water mark stackArtDec must keep >= 1,024 B free."""
    checks = {}
    required_heap = (profile.heap_min_free if profile is not None and profile.heap_min_free else HEAP_MIN_FREE_BYTES)
    heap = diag.get("heapMinFree") if isinstance(diag, dict) else None
    checks["heapMinFree"] = ({"bytes": heap, "required": required_heap, "passed": heap >= required_heap,
                              "previousReleaseBytes": PREVIOUS_HEAP_MIN_FREE_BYTES,
                              "deltaFromPreviousBytes": heap - PREVIOUS_HEAP_MIN_FREE_BYTES}
                             if type(heap) is int else {"passed": False, "reason": "missing"})
    minimum = diag.get("lvglMinFree") if isinstance(diag, dict) else None
    lvgl_bytes = profile.lvgl_min_free if profile is not None else None
    if type(minimum) is int and lvgl_bytes:
        checks["lvglMinFree"] = {"bytes": minimum, "requiredBytes": lvgl_bytes, "passed": minimum >= lvgl_bytes}
    elif type(minimum) is int:
        fraction = minimum / heap_bytes
        checks["lvglMinFree"] = {"bytes": minimum, "fraction": round(fraction, 4),
                                 "required": LVGL_MIN_FREE_FRACTION,
                                 "passed": fraction >= LVGL_MIN_FREE_FRACTION}
    else:
        checks["lvglMinFree"] = {"passed": False, "reason": "missing"}
    for name in REQUIRED_STACKS:
        value = diag.get(name) if isinstance(diag, dict) else None
        checks[name] = ({"bytes": value, "requiredAbove": STACK_MIN_BYTES, "passed": value > STACK_MIN_BYTES}
                        if type(value) is int else {"passed": False, "reason": "missing"})
    if profile is not None and profile.presentation >= 5 and isinstance(diag, dict) and diag.get("artAsync") is True:
        value = diag.get("stackArtDec")
        checks["stackArtDec"] = ({"bytes": value, "required": V5_STACK_ART_DEC_MIN_BYTES,
                                  "passed": value >= V5_STACK_ART_DEC_MIN_BYTES}
                                 if type(value) is int else {"passed": False, "reason": "missing (artAsync is true)"})
    for name in RECORDED_ONLY:
        checks[name] = {"bytes": diag.get(name) if isinstance(diag, dict) else None, "recordedOnly": True}
    return {"checks": checks, "passed": all(c.get("passed", True) for c in checks.values())}


def media_diag_summary(diag):
    """The artwork2 diag fields (ARTWORK2.md section 8) of one reply, for the evidence."""
    return {name: diag.get(name) for name in MEDIA_DIAG_FIELDS} if isinstance(diag, dict) else None


def media_counter(diag, name):
    value = diag.get(name) if isinstance(diag, dict) else None
    return value if type(value) is int else None


def jpeg_decode_problems(diag, max_ms=JPEG_DECODE_MAX_MS):
    """Why the LCD's cover decodes fail the jpegDecode gate (empty list: they pass).

    At least one decode ran (jpegDecodes > 0), none failed (jpegDecodeErrors 0) and the
    longest took at most `max_ms` (jpegDecodeMsMax), all counted since boot.
    """
    if not isinstance(diag, dict):
        return ["no diag reply"]
    names = ("jpegDecodes", "jpegDecodeErrors", "jpegDecodeMsMax", "jpegDecodeMsLast")
    missing = [name for name in names if type(diag.get(name)) is not int]
    if missing:
        return [f"diag lacks integer {', '.join(missing)} (firmware older than {CURRENT.version}?)"]
    problems = []
    if diag["jpegDecodes"] < 1:
        problems.append("no cover was decoded (jpegDecodes 0), so the decode time proves nothing")
    if diag["jpegDecodeErrors"] != 0:
        problems.append(f"JPEG DECODE ERRORS: jpegDecodeErrors {diag['jpegDecodeErrors']}")
    if diag["jpegDecodeMsMax"] > max_ms:
        problems.append(f"SLOW JPEG DECODE: jpegDecodeMsMax {diag['jpegDecodeMsMax']} ms > {max_ms} ms")
    return problems


# ---------------------------------------------------------------------------
# 1.0.0-cc5.4: ALIVE LED and presentation-5 device checks (pure; check_nanod_cc5.py --release cc5.4)

def diag_int(diag, name):
    value = diag.get(name) if isinstance(diag, dict) else None
    return value if type(value) is int else None


def alive_capability_problems(caps, led_max_brightness=ALIVE_DEFAULT_DRIVE):
    """The `alive` capability equals alive_capability(<the knob's ledMaxBrightness>) (ALIVE.md 1)."""
    key = presentation().ALIVE_CAPABILITY
    got = caps.get(key) if isinstance(caps, dict) else None
    want = alive_capability(led_max_brightness if type(led_max_brightness) is int else ALIVE_DEFAULT_DRIVE)
    return [] if got == want else [f"capability {key} is {got!r}, expected {want!r}"]


def presentation_capability_problems(caps, profile):
    """capabilities.presentation is the profile's (5 for 1.0.0-cc5.4; PRESENTATION_V5 1)."""
    got = caps.get("presentation") if isinstance(caps, dict) else None
    return [] if got == profile.presentation else [f"capability presentation is {got!r}, expected {profile.presentation}"]


def led_idle_problems(diag):
    """ALIVE.md 11.9 at idle: ledFps >= 58 (the 16/17/17 ms deadline cadence) and the longest gap
    between two shows since the previous diag read (ledShowGapMsMax, reset on read) <= 20 ms."""
    fps, gap = diag_int(diag, "ledFps"), diag_int(diag, "ledShowGapMsMax")
    if fps is None or gap is None:
        return [f"diag lacks integer ledFps / ledShowGapMsMax ({fps!r}, {gap!r}): firmware older than 1.0.0-cc5.4?"]
    problems = []
    if fps < ALIVE_LED_FPS_IDLE_MIN:
        problems.append(f"LED FRAME RATE AT IDLE: ledFps {fps} < {ALIVE_LED_FPS_IDLE_MIN}")
    if gap > ALIVE_LED_SHOW_GAP_IDLE_MAX_MS:
        problems.append(f"LED SHOW GAP AT IDLE: ledShowGapMsMax {gap} ms > {ALIVE_LED_SHOW_GAP_IDLE_MAX_MS} ms")
    return problems


def led_load_summary(samples):
    """diag replies read about 1 s apart during cover transfers (ALIVE.md 11.9): the pass rule is
    ledFps >= 45 in every sample; >= 55, ledShowGapMsMax and ledLateShows are recorded (targets)."""
    fps = [diag_int(d, "ledFps") for d in samples]
    gaps = [diag_int(d, "ledShowGapMsMax") for d in samples]
    late = [diag_int(d, "ledLateShows") for d in samples]
    problems = []
    if not samples or any(v is None for v in fps):
        problems.append("no diag ledFps under load (firmware older than 1.0.0-cc5.4, or no sample taken)")
    low = min((v for v in fps if v is not None), default=None)
    if low is not None and low < ALIVE_LED_FPS_TRANSFER_MIN:
        problems.append(f"LED FRAME RATE UNDER LOAD: ledFps {low} < {ALIVE_LED_FPS_TRANSFER_MIN}")
    known = [v for v in late if v is not None]
    return {"samples": len(samples), "ledFps": fps, "ledFpsMin": low, "required": ALIVE_LED_FPS_TRANSFER_MIN,
            "target": ALIVE_LED_FPS_TRANSFER_TARGET, "targetMet": low is not None and low >= ALIVE_LED_FPS_TRANSFER_TARGET,
            "ledShowGapMsMax": max((v for v in gaps if v is not None), default=None),
            "ledLateShows": (known[-1] - known[0]) if len(known) >= 2 else None,
            "problems": problems, "passed": not problems}


def led_render_problems(diag):
    """ALIVE.md 11.9: ledRenderUsMax (engine + output, max since the previous diag read) <= 3000 us."""
    value = diag_int(diag, "ledRenderUsMax")
    if value is None:
        return ["diag lacks integer ledRenderUsMax (firmware older than 1.0.0-cc5.4?)"]
    return [] if value <= ALIVE_LED_RENDER_US_MAX else [
        f"LED RENDER TOO SLOW: ledRenderUsMax {value} us > {ALIVE_LED_RENDER_US_MAX} us"]


def _pipeline_matches(diag, name):
    """diag reports binary `name`'s pipeline (lcdDma / lcdPeriodMs / artAsync). R4 may run at the measured scan
    period instead of 16 ms (P5-R12): a DMA + R5 pipeline (A, D) matches at any integer period."""
    flags = LCD_BINARIES[name]
    if all(diag.get(k) == v for k, v in flags.items()):
        return True
    return (flags["lcdDma"] and flags["artAsync"] and diag.get("lcdDma") is True and diag.get("artAsync") is True
            and type(diag.get("lcdPeriodMs")) is int)


def lcd_binary(diag):
    """The PRESENTATION_V5 12.6 binary a diag reply identifies, else None. A numbered image (D, E) names itself in
    diag "build": that letter, accepted only with its own pipeline (lcdDma / lcdPeriodMs / artAsync; D keeps A's
    measured-period allowance), else None. An image without the field (A, B, C) is told by its pipeline alone."""
    if not isinstance(diag, dict):
        return None
    if "build" in diag:
        build = diag.get("build")
        return build if build in LCD_BINARIES and _pipeline_matches(diag, build) else None
    legacy = [name for name in PIPELINE_BINARIES if binary_build_number(name) is None]
    for name in legacy:
        if all(diag.get(k) == v for k, v in LCD_BINARIES[name].items()):
            return name
    return next((name for name in legacy if _pipeline_matches(diag, name)), None)


def lcd_mosi_problems(diag):
    """The LCD data line on the knob (fix binaries D and E): diag lcdMosiSig, GPIO<TFT_MOSI>'s output signal, must be
    FSPID (103). 102 (FSPIQ_OUT) is binary A's dark LCD; a missing field is an image older than the fix."""
    value = diag.get("lcdMosiSig") if isinstance(diag, dict) else None
    if type(value) is not int:
        return [f"diag lacks integer lcdMosiSig ({value!r}): an image without the LCD data-line fix (binaries A, B, C)"]
    if value == LCD_MOSI_BROKEN_SIGNAL:
        return [f"LCD DATA LINE ON THE MISO OUTPUT: lcdMosiSig {value} (FSPIQ_OUT), binary A's defect: no command or "
                "pixel reaches the GC9A01"]
    if value != LCD_MOSI_SIGNAL:
        return [f"LCD DATA LINE: lcdMosiSig {value}, expected {LCD_MOSI_SIGNAL} (FSPID)"]
    return []


def lcd_diag_summary(diag):
    return {k: diag.get(k) for k in LCD_DIAG_FIELDS + LCD_FIX_DIAG_FIELDS if isinstance(diag, dict) and k in diag}


def f1_diag_summary(diag):
    """The 1.0.0-cc5.5 F1 fields (F1_DIAG_FIELDS) and the Step 0 comparison figures (STEP0_DIAG_FIELDS, plus the
    binary's build letter) of one diag reply, as read; absent fields are left out (a cc5.4 knob has no F1 ones)."""
    if not isinstance(diag, dict):
        return {}
    return {k: diag[k] for k in ("build",) + STEP0_DIAG_FIELDS + F1_DIAG_FIELDS if k in diag}


def f1_diag_lines(diag):
    """Readable lines of f1_diag_summary for the console (units spelled out; nothing gated)."""
    s = f1_diag_summary(diag)
    if not s:
        return []
    lines = []
    if any(k in s for k in ("focLoopHz", "focLoopUsMax", "uqAbsMax", "uqCapMs")):
        lines.append(f"FOC loop {s.get('focLoopHz', '?')} Hz, longest gap {s.get('focLoopUsMax', '?')} us; |Uq| max "
                     f"{s.get('uqAbsMax', '?')} mV of the {s.get('uqCapMv', '?')} mV cap, {s.get('uqCapMs', '?')} ms at "
                     "the cap since boot")
    if "pdRead" in s:
        lines.append(f"PD contract: read {'ok' if s.get('pdRead') else 'FAILED'}, PDO {s.get('pdPdo', '?')}, "
                     f"{s.get('pdVolts', '?')} V (0 = none or unknown)"
                     + (f", RDO 0x{s['pdRdo']:08X}" if isinstance(s.get("pdRdo"), int) else ""))
    if "usbHidOk" in s or "hidRetries" in s:
        lines.append(f"USB MIDI {s.get('usbMidiOk', '?')}, HID {s.get('usbHidOk', '?')}; HID retries {s.get('hidRetries', '?')}")
    step0 = {k: s[k] for k in ("build",) + STEP0_DIAG_FIELDS if k in s}
    if step0:
        lines.append("Step 0: " + ", ".join(f"{k} {v}" for k, v in step0.items()))
    return lines


LATE_SINCE_BOOT, LATE_RESET_ON_READ = "since boot", "reset on read"


def late_refresh_semantics(at_rest, again):
    """How this firmware's lcdLateRefrs counts, from two diag reads back to back at rest (nothing animates
    between them, so no late refresh can be counted in between). PRESENTATION_V5 12.3 marks only
    lcdFpsAnimMin "reset on read"; an unannotated count is since boot by the contracts' convention, but the
    check must not depend on that: a since-boot count repeats (again >= at_rest > 0), a reset-on-read one
    drops (again < at_rest). None when both reads are 0 (either reading fits)."""
    a, b = diag_int(at_rest, "lcdLateRefrs"), diag_int(again, "lcdLateRefrs")
    if a is None or b is None or a == 0:
        return None
    return LATE_RESET_ON_READ if b < a else LATE_SINCE_BOOT


def lcd_late_refreshes(semantics, before, lead, end):
    """lcdLateRefrs counted during one animation pass, or None when a read lacks the integer field.
    `before`: the last diag read before the pass; `lead`: the read that opens its measured window (it
    resets lcdFpsAnimMin); `end`: the pass's measured read. Since boot: end - before (the earlier cover
    arrivals of the run, which 12.2 and 12.6 allow on B and C, stay out of it). Reset on read: lead + end.
    Unknown (both rest reads 0): lead + end, which is 0 exactly when the pass had no late refresh under
    either reading (a since-boot count from 0 never exceeds end there); a count that went down proves
    reset on read."""
    b, l, e = (diag_int(d, "lcdLateRefrs") for d in (before, lead, end))
    if l is None or e is None:
        return None
    if semantics is None and b is not None and (l < b or e < l):
        semantics = LATE_RESET_ON_READ
    if semantics == LATE_SINCE_BOOT:
        return None if b is None else e - b
    return l + e


def lcd_timing_problems(diag, binary, kind, late=None):
    """lcdFpsAnimMin (lowest 1 s lcdFps while animating, reset on read) of one animation pass against
    the binary's target (12.2 / 12.6): kind "opaque" (slides over a shown cover; no cover arrives, so the
    pass's late refreshes, `late` from lcd_late_refreshes, must be 0: never the absolute diag value, which
    since boot includes the run's earlier cover arrivals) or "blended" (art show/hide; `late` recorded only)."""
    if binary not in LCD_FPS_TARGETS:
        return [f"diag does not identify binary {', '.join(PIPELINE_BINARIES[:-1])} or {PIPELINE_BINARIES[-1]} "
                f"({lcd_diag_summary(diag)})"]
    fps = diag_int(diag, "lcdFpsAnimMin")
    if fps is None:
        return ["diag lacks integer lcdFpsAnimMin (firmware older than 1.0.0-cc5.4?)"]
    problems = []
    target = LCD_FPS_TARGETS[binary][kind]
    if fps < target:
        problems.append(f"LCD FRAME RATE ({kind}, binary {binary}): lcdFpsAnimMin {fps} < {target}")
    if kind == "opaque":
        if late is None:
            problems.append("no lcdLateRefrs count for the pass (diag lacks integer lcdLateRefrs)")
        elif late != 0:
            problems.append(f"LCD LATE REFRESHES without a cover arrival: {late} during the pass (lcdLateRefrs)")
    return problems


def ready_key_state_problems(replies):
    """Every ready line of a presentation-5 knob carries `ks`, the raw mask 0..15 (PRESENTATION_V5 11.3)."""
    bad = [r for r in replies if not (type(r.get("ks")) is int and 0 <= r["ks"] <= 15)]
    if not replies:
        return ["no ready line seen"]
    return [f"{len(bad)} of {len(replies)} ready line(s) without a valid ks: {bad[:3]}"] if bad else []


def limit_events(messages, control_id, start=None, end=None):
    """[(time, dir)] of {"id": control_id, "lim": -1|1} in [start, end] (ALIVE.md 3)."""
    return [(ts, m["lim"]) for ts, m in messages if m.get("id") == control_id and m.get("lim") in (-1, 1)
            and (start is None or ts >= start) and (end is None or ts <= end)]


def limit_problems(lims, need=(-1, 1)):
    """At least one lim in each direction of `need`; two lims never closer than the firmware's 150 ms
    (less 50 ms of host receive jitter)."""
    problems = [f"no lim {d:+d} seen" for d in need if not any(v == d for _, v in lims)]
    times = sorted(ts for ts, _ in lims)
    close = [round(b - a, 3) for a, b in zip(times, times[1:]) if b - a < ALIVE_LIM_GAP_S - 0.05]
    if close:
        problems.append(f"lim events closer than {ALIVE_LIM_GAP_S * 1000:.0f} ms: gaps {close[:5]} s")
    return problems


def limit_push_problems(lims, pushes, hold, direction=1, grace=0.3):
    """Ruling Q1 (ALIVE.md 12.5): exactly one lim `direction` inside each push window (start, end), exactly
    one inside the hold window, and none outside them (a window is extended by `grace` s for the line's
    arrival). `lims` are (time, dir) of the push control."""
    windows = [(a, b + grace) for a, b in pushes]
    counts = [sum(1 for ts, d in lims if d == direction and a <= ts <= b) for a, b in windows]
    held = sum(1 for ts, d in lims if d == direction and hold[0] <= ts <= hold[1] + grace)
    inside = windows + [(hold[0], hold[1] + grace)]
    stray = [(round(ts, 3), d) for ts, d in lims if not any(a <= ts <= b for a, b in inside)]
    problems = []
    if any(c != 1 for c in counts):
        problems.append(f"lim per push {counts} (each must be exactly 1: none is a missed End stop, "
                        "two is attractor chatter or a short lim_rearm_ms)")
    if held != 1:
        problems.append(f"{held} lim while held against the bound (must be exactly 1)")
    if stray:
        problems.append(f"lim outside the push windows: {stray[:5]}")
    return {"perPush": counts, "held": held, "stray": stray, "problems": problems, "passed": not problems}


def kh_events(messages, start, end):
    """[(time, message)] of every kh line in [start, end], whatever its id."""
    return [(ts, m) for ts, m in messages if "kh" in m and start <= ts <= end]


def hold_check(messages, control_id, raw, hold_raw, kd_at, until):
    """One press of `raw` (its kd seen at `kd_at`; `until` is the END OF THE LISTENING AFTER ITS KEY-UP, not
    the key-up itself, so a kh sent at or after the release is counted): for the hold button (`hold_raw`,
    buttonOrder[0]) exactly one kh of `control_id` with that raw and its bit set in ks, 0.45-1.2 s after
    the kd (600 ms after contact, PRESENTATION_V5 11.2: at most one kh per physical press); for any other
    button none (long presses of the other raws are ignored). (problems, khs)."""
    khs = kh_events(messages, kd_at, until)
    problems = []
    if raw != hold_raw:
        if khs:
            problems.append(f"kh for a press of raw {raw} (only raw {hold_raw}, Button 1, holds): {[m for _, m in khs]}")
        return problems, khs
    if len(khs) != 1:
        problems.append(f"{len(khs)} kh for one hold of Button 1 (exactly one)")
    for ts, m in khs[:1]:
        if m.get("id") != control_id or m.get("kh") != raw:
            problems.append(f"kh {m} does not name control {control_id} and raw {raw}")
        if not (type(m.get("ks")) is int and m["ks"] & (1 << raw)):
            problems.append(f"kh ks {m.get('ks')!r} does not have Button 1's bit")
        delay = ts - kd_at
        if not HOLD_ARRIVAL_S[0] <= delay <= HOLD_ARRIVAL_S[1]:
            problems.append(f"kh {delay * 1000:.0f} ms after the kd (expected {HOLD_ARRIVAL_S[0] * 1000:.0f}-"
                            f"{HOLD_ARRIVAL_S[1] * 1000:.0f} ms)")
    return problems, khs


def heap_projection(ram_used_bytes, dma=True):
    """PRESENTATION_V5 12.4 build-only check: heapMinFreeProjected = 57,072 - (ramUsedBytes - 245,056)
    - 1,024 - H, with H the SPI DMA descriptors (512 B) in the DMA binaries (A, B and D; 0 in C and E); gate
    >= 45,056 B."""
    delta = ram_used_bytes - CC53_RAM_USED_BYTES
    h = V5_DMA_DESCRIPTOR_BYTES if dma else 0
    projected = CC53_HEAP_MIN_FREE_BYTES - delta - V5_JSON_DOC_BYTES - h
    return {"ramUsedBytes": ram_used_bytes, "ramDeltaVsCc53": delta, "jsonDocBytes": V5_JSON_DOC_BYTES, "hBytes": h,
            "heapMinFreeProjected": projected, "required": V5_HEAP_PROJECTION_MIN_BYTES,
            "passed": projected >= V5_HEAP_PROJECTION_MIN_BYTES}


# ---------------------------------------------------------------------------
# Reboot detection (1.0.0-cc5.1 diag fields; CONTROL_CENTER.md "Diagnostics")

BOOT_FIELDS = ("resetReason", "uptimeMs", "bootCount")
TURN_MIN_EVENTS = 20            # claimed position events required inside the stress+turn frame window
TURN_MAX_GAP_S = 3.0            # longest pause without one allowed inside that window


def boot_fields_problems(diag):
    """The diag reply must carry the reboot-detection fields (firmware 1.0.0-cc5.1 or later)."""
    if not isinstance(diag, dict):
        return ["no diag reply"]
    missing = [name for name in BOOT_FIELDS if name not in diag]
    problems = [f"diag lacks {', '.join(missing)} (firmware older than 1.0.0-cc5.1?)"] if missing else []
    if not missing and not (type(diag["uptimeMs"]) is int and type(diag["bootCount"]) is int
                            and isinstance(diag["resetReason"], str)):
        problems.append("diag reboot fields have the wrong types")
    return problems


def reboot_problems(before, after):
    """Why `after` is not the same boot as `before` (empty: same boot, uptime moved forward)."""
    problems = boot_fields_problems(before) + boot_fields_problems(after)
    if problems:
        return problems
    if after["bootCount"] != before["bootCount"]:
        problems.append(f"REBOOT: bootCount {before['bootCount']} -> {after['bootCount']} "
                        f"(reset reason {after['resetReason']})")
    if after["uptimeMs"] < before["uptimeMs"]:
        problems.append(f"REBOOT: uptime went back from {before['uptimeMs']} ms to {after['uptimeMs']} ms "
                        f"(reset reason {after['resetReason']})")
    return problems


# ---------------------------------------------------------------------------
# Task liveness (1.0.0-cc5.2 diag fields; CONTROL_CENTER.md "Diagnostics")

LIVENESS_AGE_FIELDS = ("hmiAgeMs", "lcdAgeMs", "comAgeMs", "focAgeMs")
LIVENESS_STEP_FIELDS = {"hmiAgeMs": "hmiStep", "lcdAgeMs": "lcdStep", "comAgeMs": "comStage", "focAgeMs": None}
LIVENESS_COUNTERS = ("ledTxTimeouts", "forcedReleases")
LIVENESS_MAX_AGE_MS = 1000       # a task whose last pass is older than this at a checkpoint is stalled


def liveness_summary(diag):
    """The liveness fields of one diag reply, for the evidence timeline."""
    if not isinstance(diag, dict):
        return None
    keys = LIVENESS_AGE_FIELDS + LIVENESS_COUNTERS + ("ledWriteErrors", "hmiStep", "lcdStep", "comStage",
                                                      "sessionPhase", "releasePendingMs", "wdtTasks")
    return {k: diag.get(k) for k in keys if k in diag}


def liveness_problems(diag, max_age_ms=None):
    """Why this diag shows a stalled task or a transport/release failure (empty list: healthy).

    Every task age (hmiAgeMs, lcdAgeMs, comAgeMs, focAgeMs) must be at most
    LIVENESS_MAX_AGE_MS, and ledTxTimeouts, ledWriteErrors and forcedReleases (counted since
    boot) must be 0; each LED strip must be installed. A reply without these fields is older
    than 1.0.0-cc5.2 and fails.
    """
    limit = LIVENESS_MAX_AGE_MS if max_age_ms is None else max_age_ms
    if not isinstance(diag, dict):
        return ["no diag reply"]
    missing = [name for name in LIVENESS_AGE_FIELDS + LIVENESS_COUNTERS if name not in diag]
    if missing:
        return [f"diag lacks {', '.join(missing)} (firmware older than {PROFILES['cc5.2'].version}?)"]
    problems = []
    for name in LIVENESS_AGE_FIELDS:
        value = diag[name]
        if type(value) is not int:
            problems.append(f"{name} is not an integer ({value!r})")
        elif value > limit:
            step = LIVENESS_STEP_FIELDS[name]
            where = f" at step {diag.get(step)!r}" if step and diag.get(step) is not None else ""
            problems.append(f"TASK STALLED: {name} {value} ms > {limit} ms{where}")
    if diag["ledTxTimeouts"] != 0:
        problems.append(f"LED TRANSMIT TIMEOUT: ledTxTimeouts {diag['ledTxTimeouts']} (led {diag.get('led')})")
    if diag.get("ledWriteErrors", 0) != 0:
        problems.append(f"LED DRIVER ERROR: ledWriteErrors {diag['ledWriteErrors']} (led {diag.get('led')})")
    led = diag.get("led")
    if isinstance(led, dict):
        down = sorted(name for name, strip in led.items() if isinstance(strip, dict) and strip.get("installed") is False)
        if down:
            problems.append(f"LED strip(s) not installed: {', '.join(down)}")
    if diag["forcedReleases"] != 0:
        problems.append(f"FORCED RELEASE: forcedReleases {diag['forcedReleases']} "
                        f"(last unacknowledged: {diag.get('lastForced')})")
    return problems


def forced_release_problems(reply):
    """A {"released":true} reply that completed without every acknowledgement (reason "forced")."""
    if isinstance(reply, dict) and reply.get("reason") == "forced":
        return [f"FORCED RELEASE: the knob released without the acknowledgement of {reply.get('unacked')}"]
    return []


# ---------------------------------------------------------------------------
# Unattended soak (check_nanod_cc5.py "soak" section, 1.0.0-cc5.2)

SOAK_DEFAULT_MINUTES = 20.0
SOAK_GATE_MINUTES = 20.0         # the unattendedSoak gate needs a completed soak at least this long
SOAK_CHECKPOINT_SECONDS = 10.0   # diag checkpoint interval
SOAK_CYCLE_SECONDS = 30.0        # release + re-enter a new control this often
SOAK_FRAME_SECONDS = 1.0         # a changed frame this often (heartbeats fill in at 0.5 s)
SOAK_ART_SECONDS = 10.0          # an artwork transfer this often, alternately cold and cached
SOAK_V1_ART_EVERY = 4            # 1.0.0-cc5.3: every 4th artwork slot is a paced v1 art transfer
STRESS_MIN_SECONDS = 20.0        # an unpaced media stress pass lasts at least this long
FRAME_TICK_SECONDS = 0.025       # ARTWORK2.md section 3: at most one frame per 25 ms UI tick (plus heartbeats)


# A step-down after a panic (PRESENTATION_V5 12.6; TOOL-bc TB-D9): the failed binary's core dump stays in the
# coredump partition (its verified rollback keeps it, and the step-down base holds it byte for byte), so the next
# binary boots with it. check_nanod_cc5.py --binary then accepts exactly that dump for the binary installed from
# that base (step_down_coredump): diag reports a present dump of the size the base's partition names (its first
# word, what esp_core_dump_image_get returns) and a reset reason that is not a crash. Any other dump fails the
# coredumpBlank gate as before.
CRASH_RESET_REASONS = frozenset(("panic", "int_wdt", "task_wdt", "wdt", "brownout"))


def step_down_coredump(profile, binary=None):
    """The core dump binary `binary` of `profile` inherited from its step-down base, as {"base", "partitionOffset",
    "bytes", "partitionSha256"}; None when its current preparation is not from a step-down base, its flash record
    did not verify an install from that base, the base file does not match the preparation, or the base's coredump
    partition is blank. Reads the records and the base file only."""
    try:
        p = profile.binary_profile(binary)
        prep, flash = load_json(p.preparation), load_json(p.flash_checks)
    except (OSError, ValueError):
        return None
    if not (isinstance(prep, dict) and isinstance(flash, dict)) or prep.get("baseKind") != STEP_DOWN_ROLE:
        return None
    name = Path(str(prep.get("baseFile") or "")).name
    if not name or flash.get("baseFile") != name or flash.get("postWriteVerified") is not True:
        return None
    try:
        data = (BACKUPS / name).read_bytes()
        partitions = parse_partition_table(data[PARTITION_TABLE_OFFSET:PARTITION_TABLE_OFFSET + PARTITION_TABLE_SIZE])
    except (OSError, ValueError):
        return None
    core = next((q for q in partitions if q["type"] == 1 and q["subtype"] == 3), None)   # data / coredump
    if sha256_bytes(data) != prep.get("baseSha256") or core is None:
        return None
    region = data[core["offset"]:core["offset"] + core["size"]]
    if len(region) < 4 or region[:4] == b"\xff" * 4:
        return None
    return {"base": name, "partitionOffset": core["offset"], "bytes": int.from_bytes(region[:4], "little"),
            "partitionSha256": sha256_bytes(region)}


def coredump_problems(diag, inherited=None):
    """The coredump partition must be blank (all 0xFF): anything else is a crash to read out first. The one
    exception is `inherited` (step_down_coredump): after a step-down, the failed binary's dump the step-down base
    holds, reported with the same size and no crash reset reason."""
    core = diag.get("coredump") if isinstance(diag, dict) else None
    if not isinstance(core, dict) or "blank" not in core:
        return ["diag has no coredump status"]
    if core.get("present"):
        reason = diag.get("resetReason")
        if (inherited and core.get("bytes") == inherited.get("bytes") and isinstance(reason, str)
                and reason not in CRASH_RESET_REASONS):
            return []
        kept = (f"; it is not the {inherited.get('bytes')} B dump the step-down base {inherited.get('base')} holds "
                f"with a non-crash reset (reset reason {reason})") if inherited else ""
        return [f"a core dump is stored ({core.get('bytes')} B): the firmware panicked since the partition was "
                "last blank. Do not erase it; read 0x3F0000 0x10000 with esptool read_flash for analysis" + kept]
    if core.get("blank") is not True:
        return [f"the coredump partition is not blank ({core.get('status')}): a dump may have been cut short"]
    return []


# ---------------------------------------------------------------------------
# The short look session after a fix binary's install (check_nanod_cc5_look.py; firmware/BUILD-cc5.4.md "Fix
# binaries D and E"): two read-only diag reads before the user looks. The full 8b / 8c checks are not run there.

LOOK_READ_GAP_MIN_S = 1.5                   # the two reads are at least this far apart
LOOK_RECORDED_FIELDS = ("ledFps", "ledShowGapMsMax", "ledMode", "lcdFps", "lcdFullRefrs")   # recorded, not gated


def look_check_problems(first, second, binary, inherited=None):
    """Why the knob does not run a healthy binary `binary` (empty: GO for the user to look), from two diag reads
    taken apart on the same port with no claim: both identify the binary (diag build and its pipeline,
    lcd_binary), both have the LCD data line on FSPID (lcdMosiSig 103, lcd_mosi_problems), the coredump partition
    is blank (or holds only `inherited`, the step-down base's dump, step_down_coredump), the reset reason is not a
    crash (CRASH_RESET_REASONS), and the knob did not reboot between the reads (same bootCount, uptime advanced)."""
    reads = (("first read", first), ("second read", second))
    missing = [label for label, diag in reads if not isinstance(diag, dict)]
    if missing:
        return [f"no diag reply ({', '.join(missing)})"]
    problems = []
    for label, diag in reads:
        reported = lcd_binary(diag)
        if diag.get("build") != binary or reported != binary:
            pipeline = {k: diag.get(k) for k in ("lcdDma", "lcdPeriodMs", "artAsync")}
            problems.append(f"{label}: diag does not identify binary {binary} (build {diag.get('build')!r}, pipeline "
                            f"{pipeline}, identified {reported!r}): the knob runs another image")
        problems += [f"{label}: {problem}" for problem in lcd_mosi_problems(diag)]
    for problem in coredump_problems(first, inherited) + coredump_problems(second, inherited):
        if problem not in problems:
            problems.append(problem)
    reason = first.get("resetReason")
    if not isinstance(reason, str):
        problems.append(f"diag has no resetReason ({reason!r})")
    elif reason in CRASH_RESET_REASONS:
        problems.append(f"CRASH RESET: resetReason {reason} (the binary crashed at or right after its boot)")
    reboot = reboot_problems(first, second)
    problems += [problem for problem in reboot if problem not in problems]
    if not reboot and second["uptimeMs"] <= first["uptimeMs"]:
        problems.append(f"uptime did not advance between the reads ({first['uptimeMs']} ms -> {second['uptimeMs']} ms)")
    return problems


def claimed_positions(events, control_id, start, end):
    """Times of claimed position events ({"id": control_id, "p": n}) within [start, end]."""
    return [ts for ts, e in events if e.get("id") == control_id and "p" in e and start <= ts <= end]


def turning_in_window(times, window):
    """The event times inside `window` = (start, end), sorted, and the longest pause in it.

    The pause runs from the window's start through each event to the window's end, so a
    window with no events has one pause, the whole window, and turning that stops before
    the end (or starts late) shows as a long pause too.
    """
    start, end = window
    inside = sorted(ts for ts in times if start <= ts <= end)
    edges = [start] + inside + [end]
    return inside, max(b - a for a, b in zip(edges, edges[1:]))


def turning_problems(times, window, minimum=TURN_MIN_EVENTS, max_gap_s=TURN_MAX_GAP_S):
    """Why the knob was not turned throughout the stress frames (empty list: it was).

    `times` are claimed position event times (claimed_positions) and `window` is the
    stress-frame window (run_stress "window"). Only events inside it count: turning only
    during the cold transfers before the stress, or only for part of the stress, is a FAIL.
    It needs at least `minimum` events and no pause longer than `max_gap_s` (turning_in_window).
    """
    inside, gap = turning_in_window(times, window)
    reasons = []
    if len(inside) < minimum:
        reasons.append(f"{len(inside)} claimed position event(s) inside the stress-frame window, "
                       f"at least {minimum} required")
    if gap > max_gap_s:
        reasons.append(f"a {gap:.1f} s pause without a claimed position event inside the stress-frame window "
                       f"(at most {max_gap_s:g} s)")
    if not reasons:
        return []
    return ["turning not detected during stress; rerun: " + "; ".join(reasons)
            + ". Events during the cold transfers before the stress do not count. This is a FAIL to rerun "
              "(turn the knob continuously from the prompt until 'Stop turning'), not a pass"]


def pnp_last_arrival(run=subprocess.run, instance=r"USB\VID_239A&PID_8010\*"):
    """LastArrivalDate (UTC, ISO) of the knob's USB device from Windows PnP metadata, or None.

    Read-only; no port is opened and no window is shown. A change between two reads means
    Windows saw the device leave and arrive again (a reset or a USB drop).
    """
    script = ("$d = Get-PnpDevice -PresentOnly -InstanceId '" + instance + "' -ErrorAction SilentlyContinue | "
              "Select-Object -First 1; if ($d) { $p = Get-PnpDeviceProperty -InstanceId $d.InstanceId "
              "-KeyName DEVPKEY_Device_LastArrivalDate -ErrorAction SilentlyContinue; "
              "if ($p -and $p.Data) { $p.Data.ToUniversalTime().ToString('o') } }")
    try:
        result = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                     capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or "").strip()
    return (value or None) if result.returncode == 0 else None


def arrival_problems(before, after):
    if before is None:
        return []           # not available at the start: only the diag and the port watch count
    if after is None:
        return ["the knob's USB device is not present (Windows PnP)"]
    if after != before:
        return [f"USB RE-ENUMERATION: Windows LastArrivalDate changed {before} -> {after}"]
    return []


class PortWatch:
    """Polls the port list (metadata only, no port opened) and records when the knob's
    application port disappears, however briefly it is gone."""

    def __init__(self, interval=0.2, lister=None, clock=time.monotonic):
        self.interval, self.lister, self.clock = interval, lister or list_ports, clock
        self.absences, self._lock, self._stop = [], threading.Lock(), threading.Event()
        self._thread = threading.Thread(target=self._run, name="knob-port-watch", daemon=True)
        self._taken, self.started, self.gone_since = 0, clock(), None

    def poll_once(self):
        """One enumeration; records an absence when the port comes back."""
        try:
            present = any(is_app_port(p) for p in self.lister())
        except Exception:
            present = True              # an enumeration hiccup is not a knob event
        now = self.clock()
        with self._lock:
            if not present and self.gone_since is None:
                self.gone_since = now
            elif present and self.gone_since is not None:
                self.absences.append({"from": round(self.gone_since - self.started, 3),
                                      "seconds": round(now - self.gone_since, 3)})
                self.gone_since = None

    def _run(self):
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.interval)

    def start(self):
        self.started = self.clock()
        self._thread.start()
        return self

    def take(self):
        """Absences recorded since the previous call, plus one still going on."""
        with self._lock:
            new, self._taken = self.absences[self._taken:], len(self.absences)
            if self.gone_since is not None:
                new = new + [{"from": round(self.gone_since - self.started, 3), "seconds": None, "ongoing": True}]
        return new

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Raw serial session (used for stale-frame/stale-control/lease cases, never DeviceBridge)

def is_knob_event(message):
    """A turn, press, release, hold (kh, 1.0.0-cc5.4) or End stop (lim, 1.0.0-cc5.4): the knob was touched."""
    return "ready" not in message and any(k in message for k in ("p", "kd", "ku", "ks", "kh", "lim"))


class RawKnob:
    """Minimal line client for the application port.

    Paced (the default) it writes like the cc5.2-era companion's PacedSerial: 64 B slices with
    5 ms gaps. With `paced` False it writes like the v4 companion once artwork2 is negotiated
    (ARTWORK2.md section 3): every complete line in one write() call, no slicing, no sleeps.
    Every message is time-stamped and classified; errors are collected, never raised by the
    reader, so each check decides what counts as expected.
    """
    CHUNK_BYTES, GAP_SECONDS = 64, 0.005

    def __init__(self, device, *, serial_factory=None, clock=time.monotonic, sleep=time.sleep, paced=True):
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from protocol import LineDecoder
        if serial_factory is None:
            import serial
            serial_factory = lambda name: serial.Serial(name, 115200, timeout=0.05, write_timeout=1.0)
        self.clock, self.sleep = clock, sleep
        self.paced = paced
        self.port = serial_factory(device)
        self.decoder = LineDecoder()
        self.t0 = clock()
        self.messages, self.errors, self.art_errors, self.media_errors, self.released = [], [], [], [], []
        self.claimed_events, self.native_events = [], []
        self.ready_replies = []         # (time, ready line): 1.0.0-cc5.4 carries ks in each
        self.control_id = None
        self.latest_frame = None
        self.last_frame_at = 0.0
        self.ready_at = None
        self.heartbeat_seconds = 0.5   # 0 disables heartbeats (lease-expiry cases)
        self.frame_write_seconds = []
        self.frames_sent = 0
        self.lines_written = {"paced": 0, "whole": 0}

    def now(self):
        return self.clock() - self.t0

    def close(self):
        try:
            self.port.close()
        except Exception:
            pass

    def send_line(self, data):
        started = self.clock()
        if not self.paced:
            self.port.write(data)               # one write() per line: artwork2 transport
            self.lines_written["whole"] += 1
            return self.clock() - started
        for start in range(0, len(data), self.CHUNK_BYTES):
            self.port.write(data[start:start + self.CHUNK_BYTES])
            if start + self.CHUNK_BYTES < len(data):
                self.sleep(self.GAP_SECONDS)
        self.lines_written["paced"] += 1
        return self.clock() - started

    def send(self, payload):
        data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > 4096:
            raise ValueError("Line exceeds the firmware's 4096 B command limit")
        return self.send_line(data)

    def frame(self, frame):
        seconds = self.send({"frame": frame})
        self.latest_frame, self.last_frame_at = frame, self.clock()
        self.frame_write_seconds.append(seconds)
        self.frames_sent += 1
        return seconds

    def _classify(self, message):
        t = round(self.now(), 4)
        self.messages.append((t, message))
        if "error" in message:
            self.errors.append((t, message.get("error")))
        ack = message.get("artAck")
        if isinstance(ack, dict) and "error" in ack:
            self.art_errors.append((t, ack))
        ack = message.get("mediaAck")
        if isinstance(ack, dict) and "error" in ack:
            self.media_errors.append((t, ack))
        if message.get("released") is True:
            self.released.append((t, message.get("reason")))
            self.control_id = None
        if is_knob_event(message):
            (self.claimed_events if "id" in message else self.native_events).append((t, message))

    def pump(self, duration=0.0):
        """Read (and heartbeat the latest frame) for `duration` seconds; returns new messages."""
        out = []
        end = self.clock() + duration
        while True:
            if (self.heartbeat_seconds and self.control_id is not None and self.latest_frame is not None
                    and self.clock() - self.last_frame_at >= self.heartbeat_seconds):
                self.frame(self.latest_frame)
            waiting = getattr(self.port, "in_waiting", 0) or 0
            for message in self.decoder.feed(self.port.read(max(1, min(waiting, 4096)))):
                self._classify(message)
                out.append(message)
            if self.clock() >= end:
                return out

    def wait(self, predicate, timeout, what):
        end = self.clock() + timeout
        while self.clock() < end:
            for message in self.pump():
                if predicate(message):
                    return message
        raise TimeoutError(f"No {what} within {timeout} s")

    def request(self, payload, predicate, timeout=2.0, what="reply"):
        self.send(payload)
        return self.wait(predicate, timeout, what)

    def release(self, timeout=3.0):
        """Send {"release": true} and wait for {"released": true}. Heartbeats stop first.

        Always sent, whatever `control_id` says: when idle the firmware clears the
        host-lost notice and answers at once (control_center.cpp).
        """
        self.control_id = self.latest_frame = None
        self.send({"release": True})
        return self.wait(lambda m: m.get("released") is True, timeout, "release acknowledgement")

    def release_quietly(self, timeout=2.0):
        """Cleanup form of `release` for `finally` blocks: never raises; returns the reply or None."""
        try:
            return self.release(timeout)
        except Exception:
            self.control_id = self.latest_frame = None
            return None

    def enter(self, control, timeout=3.0):
        # A new control supersedes the claimed one (1.0.0-cc5.4 hands-on enters while claimed): no heartbeat
        # of the old id while this one enters, or the knob would answer it "Stale control frame".
        self.control_id = self.latest_frame = None
        self.send({"control": control})
        reply = self.wait(lambda m: m.get("ready") == control["id"] or "error" in m, timeout,
                          f"ready {control['id']}")
        if "error" in reply:
            raise RuntimeError(f"Control {control['id']} rejected: {reply['error']}")
        # The ready line's own arrival time (lines read in the same batch after it are later).
        self.ready_at = next((ts for ts, m in reversed(self.messages) if m is reply), self.now())
        self.ready_replies.append((self.ready_at, reply))
        self.control_id, self.latest_frame, self.last_frame_at = control["id"], control["frame"], self.clock()
        return reply

    def diag(self, timeout=2.0):
        """{"diag":"?"} (read-only; never renews the lease): the diag object."""
        return self.request({"diag": "?"}, lambda m: isinstance(m.get("diag"), dict), timeout, "diag")["diag"]

    def art(self, body, timeout=2.0):
        """Send one art line and return (artAck, round-trip seconds)."""
        started = self.clock()
        self.send({"art": body})
        ack = self.wait(lambda m: isinstance(m.get("artAck"), dict) and m["artAck"].get("op") == body["op"]
                        and m["artAck"].get("key") == body["key"], timeout, f"artAck {body['op']}")
        return ack["artAck"], self.clock() - started

    def media(self, body, timeout=2.0):
        """Send one media line and return (mediaAck, round-trip seconds).

        Stop-and-wait: every media line is answered by exactly one mediaAck, in order (ARTWORK2.md
        section 4), so the first mediaAck after the send is its answer, whatever it echoes.
        """
        data = (json.dumps({"media": body}, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > 4096:
            raise ValueError("Line exceeds the firmware's 4096 B command limit")
        return self.media_line(data, timeout, body.get("op"))

    def media_line(self, data, timeout=2.0, what="line"):
        """Send raw bytes as one media line (malformed and oversize cases too); (mediaAck, seconds)."""
        started = self.clock()
        self.send_line(data)
        ack = self.wait(lambda m: isinstance(m.get("mediaAck"), dict), timeout, f"mediaAck {what}")
        return ack["mediaAck"], self.clock() - started


@contextmanager
def pacing(knob, paced):
    """Temporarily switch a RawKnob between paced (cc5.2-era companion) and whole-line writes."""
    before = knob.paced
    knob.paced = paced
    try:
        yield knob
    finally:
        knob.paced = before


def probe_diag(device, *, knob_factory=None, settle=0.3):
    """Open the application port, read {"diag":"?"} once, close. Read-only: no release, no claim."""
    knob = (knob_factory or RawKnob)(device)
    try:
        knob.pump(settle)
        return knob.diag()
    finally:
        knob.close()


# The r4 control fields a check may add to a control (CONTROL_CENTER.md): without them the knob runs the cc5.6 haptic
# loop exactly and silent, and the r4 wall law runs only with a `feel` token. Built by feel_fields() (Desk Dial's own
# DeviceBridge._feel_fields for the live capabilities) and checked by control_extra_problems() before anything is sent.
CONTROL_EXTRA_FIELDS = ("feel", "reducedHaptics", "sound", "soundVolume")
CONTROL_SOUND_MAX = 3
CONTROL_SOUND_VOLUME_MAX = 100


def control_extra_problems(extra):
    """What a control parser would reject in the extra control fields `extra` (empty: valid)."""
    if not isinstance(extra, dict):
        return [f"extra control fields must be a dict, not {type(extra).__name__}"]
    problems = [f"unknown control field {key!r}" for key in extra if key not in CONTROL_EXTRA_FIELDS]
    if "feel" in extra and not (isinstance(extra["feel"], str) and extra["feel"]):
        problems.append("feel must be a non-empty token")
    if "reducedHaptics" in extra and not isinstance(extra["reducedHaptics"], bool):
        problems.append("reducedHaptics must be true or false")
    for key, top in (("sound", CONTROL_SOUND_MAX), ("soundVolume", CONTROL_SOUND_VOLUME_MAX)):
        if key in extra and not (type(extra[key]) is int and 0 <= extra[key] <= top):
            problems.append(f"{key} must be an integer 0..{top}")
    return problems


def feel_fields(device, capabilities, feel=None, *, reduced_haptics=False, volume=0):
    """The r4 control fields Desk Dial would send to a knob with these live `capabilities` (`device`: the companion's
    control_center.device module): `feel` (when given and the knob has the feel capability) with reducedHaptics, and
    sound/soundVolume for `volume` (0: silent). Empty for an older knob, so its control line stays byte-identical."""
    from types import SimpleNamespace
    bridge = SimpleNamespace(capabilities=capabilities, _knob_volume=int(volume),
                             _reduced_haptics=bool(reduced_haptics))
    value = {} if feel is None else {"feel": feel}
    device.DeviceBridge._feel_fields(bridge, value)
    return value


def raw_control(ident, profile, maximum, position, frame, *, windows_button=2, windows_hid=False, extra=None):
    """A control command as the companion builds it (HID off for checks, except the opt-in 1.0.0-cc5.4
    F24 icon-gate check, which enables it on one Home and one Tracks control). `extra`: r4 control fields
    (CONTROL_EXTRA_FIELDS, from feel_fields), validated first (ValueError); without it the line is unchanged."""
    control = {"id": ident, "profile": profile, "min": 0, "max": maximum, "position": position,
               "windowsButton": windows_button, "buttonOrder": [0, 1, 2, 3], "windowsHidEnabled": bool(windows_hid)}
    if extra:
        problems = control_extra_problems(extra)
        if problems:
            raise ValueError(f"control fields the knob would reject: {problems}")
        control.update(extra)
    control["frame"] = {**frame, "id": ident}
    return control


def fixture_frames():
    """(v4 host outputs by case name, v2 recorded inputs by case name) from frames_v4.json."""
    data = load_json(FIXTURES / "frames_v4.json")
    v4, v2 = {}, {}
    for case in data["cases"]:
        name, expect = case["name"], case["expect"]
        if not expect.get("accept"):
            continue
        if name.startswith("v4-") and case["capabilities"].get("presentation") == 4:
            v4[name] = expect["output"]
        elif name.startswith("v2-") and name.endswith("-to-cc5") and case.get("rawParity"):
            v2[name] = case["input"]
    return v4, v2


# ---------------------------------------------------------------------------
# Knob prompts (user ruling 2026-09-26): "any tests shouldn't use audio cues or chat prompts -- it should leverage
# the native display of the knob to tell me what to do. and the knob display should only move onto the next
# instruction once it captures that i properly did the presented instruction."
#
# One engine for every hands-on flow (check_nanod_cc5.py, check_nanod_cc5_lease.py, check_nanod_cc5_look.py,
# nanod_alive_tour.py). It only drives a RawKnob the caller opened, so importing it opens nothing. The knob's own
# screen carries every instruction (host frames); each step advances only on the device events that prove it was
# done, and a wrong or incomplete action repeats the step with the reason on screen. The only timeout is a long
# safety timeout per wait (PROMPT_STEP_TIMEOUT_S), which stops the run as "operator did not complete step N"
# (OperatorTimeout, exit OPERATOR_EXIT) or, on the first step, "screen not confirmed" (ScreenNotConfirmed, exit
# SCREEN_EXIT): never a firmware failure. Console output is a log only ("[knob] step n/m <name>: ...").

PROMPT_STEP_TIMEOUT_S = 600.0       # safety timeout of each wait for the operator (scripts: --step-timeout)
PROMPT_DONE_S = 1.0                 # a step's "Done" (ok flash + success line) stays this long
PROMPT_QUIET_S = 1.0                # End stop: no further lim for this long ends a push
PROMPT_PUMP_S = 0.02                # read granularity of the waits (heartbeats continue)
PROMPT_PROFILE = "BINARIS BEER"     # the prompter's own controls: the regular level preset the hold tests use
PROMPT_MAX, PROMPT_POSITION = 100, 50
YES_RAW, NO_RAW = 3, 0              # Yes = Button 4 (switch, go tone: green), No = Button 1 (cancel, stop tone: red)
DISPLAY_STEP = "display"            # every plan starts with the display check
OPERATOR_EXIT, SCREEN_EXIT = 4, 5   # exit codes of an operator stop (never a firmware failure)
PROMPT_ICONS = ("home", "more", "more", "switch")   # the one lit icon of a press prompt, per raw (20 px masks)
PROMPT_SEP = " · "
PROMPT_SEE = "Can you see this?"
PROMPT_SEE_SUB = "Press Button 4"
PROMPT_SEE_NOTE = "It lights green"
PROMPT_LET_GO_KEYS = "Let go of the buttons"
# Both fit the one note line of the Seek overlay (TL-TST-002: "Yes: Button 4 · No: Button 1" and "That was Button 2 ·
# Yes 4 · No 1" were cut there with an ellipsis).
PROMPT_YES_NO = "Yes Button 4 · No Button 1"
PROMPT_YES_NO_RETRY = "Not Button {n} · Yes 4 · No 1"   # ask(): a button that is neither answer
PROMPT_DONE = "Done"
PROMPT_SEED_KIND = "ok"
PROMPT_SEQ_START = 50000            # feedback seq of prompt flashes (P4 5.8: any new value plays one moment)

# Where an instruction goes on each layout the prompts and overlays use (PRESENTATION_V5 3.4, 8.5.1; lcd_preview):
# (instruction field, progress field or None when the layout has one line for progress and note, the line field,
# its tone field). The heading row is drawn on every layout; `value` (the volume digits) is never touched.
OVERLAY_FIELDS = {
    "notice": ("title", "subtitle", "meta", "metaTone"),
    "recent": ("title", "subtitle", "meta", "metaTone"),
    "explorer": ("title", "subtitle", "meta", "metaTone"),
    "upnext": ("title", "subtitle", "meta", "metaTone"),
    "tracks": ("title", "subtitle", "meta", "metaTone"),        # title: ONE 22 px line (keep it short)
    "nowPlaying": ("title", "subtitle", "status", "statusTone"),
    "volume": ("volumeCaption", None, "status", "statusTone"),
    "seek": ("title", None, "meta", "metaTone"),                # title: the 14 px caption
    "windows": ("title", None, "meta", "metaTone"),             # subtitle (app, tile initial) untouched
}
_OVERLAY_LEGACY = {"VOLUME": "nowPlaying", "RECENTLY ADDED": "recent", "TRACKS": "tracks", "WINDOWS": "windows"}


def overlay_layout(frame):
    """The layout a parser gives `frame` (its `layout`, else the legacy one derived from `mode`)."""
    layout = frame.get("layout")
    if isinstance(layout, str) and layout:
        return layout
    return _OVERLAY_LEGACY.get(frame.get("mode"), "nowPlaying")


def overlay(frame, heading, say, progress="", note="", tone=None, tag=""):
    """A copy of `frame` carrying a prompt in the fields its layout draws (OVERLAY_FIELDS): the step label in the
    heading, the instruction `say`, the `progress` line and the `note` line (tone "error" / "success", else the
    default), with `tag` (a per-frame label that keeps a drawn line changing, e.g. the stress frame number) after
    the note. On a layout with one line for both, the note wins over the progress. Buttons, ring, art and `value`
    are kept; the instruction is drawn in the regular ink."""
    out = copy.deepcopy(frame)
    layout = overlay_layout(out)
    if layout not in OVERLAY_FIELDS:
        raise ValueError(f"no prompt overlay for layout {layout!r}")
    say_field, progress_field, line_field, tone_field = OVERLAY_FIELDS[layout]
    out["heading"] = heading
    out[say_field] = say
    if say_field == "title":
        out["titleTone"] = "ink"
    elif layout == "volume":
        out["title"] = say
    line = note if (note or progress_field) else progress
    if progress_field:
        out[progress_field] = progress
    if tag:
        line = f"{line}{PROMPT_SEP}{tag}" if line else tag
    out[line_field] = line
    out[tone_field] = tone if (note and tone) else "meta"
    return out


def read_overlay(frame):
    """What a prompt or an overlaid frame asks, read back from the fields its layout draws (the inverse of overlay;
    the tests' FakeOperator reads the knob with it): {layout, heading, say, progress, note, tone, buttons}."""
    frame = frame if isinstance(frame, dict) else {}
    layout = overlay_layout(frame)
    say_field, progress_field, line_field, tone_field = OVERLAY_FIELDS.get(layout, OVERLAY_FIELDS["notice"])
    say = frame.get(say_field) or (frame.get("title", "") if layout == "volume" else "")
    return {"layout": layout, "heading": str(frame.get("heading", "")), "say": str(say or ""),
            "progress": str(frame.get(progress_field, "")) if progress_field else "",
            "note": str(frame.get(line_field, "")), "tone": frame.get(tone_field, "meta"),
            "buttons": frame.get("buttons") if isinstance(frame.get("buttons"), list) else []}


def blank_button():
    """A slot with no icon and not enabled: tone none (glyph hidden, LED off)."""
    return {"label": "", "enabled": False, "icon": ""}


def blank_buttons():
    return [blank_button() for _ in range(4)]


def press_buttons(raw, icon=None, label="Press"):
    """Only Button raw+1 live, with an icon the firmware draws at 20 px (PROMPT_ICONS)."""
    buttons = blank_buttons()
    buttons[raw] = {"label": label, "enabled": True, "icon": icon or PROMPT_ICONS[raw]}
    return buttons


def yes_no_buttons():
    """Button 4 = Yes (switch: go tone, green) and Button 1 = No (cancel: stop tone, red); the others off."""
    buttons = blank_buttons()
    buttons[NO_RAW] = {"label": "No", "enabled": True, "icon": "cancel"}
    buttons[YES_RAW] = {"label": "Yes", "enabled": True, "icon": "switch"}
    return buttons


def is_yes_no(buttons):
    """True for the Yes/No legend (slot 0 cancel, slot 3 switch, both live)."""
    try:
        return (buttons[NO_RAW].get("icon") == "cancel" and buttons[NO_RAW].get("enabled") is True
                and buttons[YES_RAW].get("icon") == "switch" and buttons[YES_RAW].get("enabled") is True)
    except (IndexError, AttributeError, TypeError):
        return False


def prompt_frame(heading, say, progress="", note="", tone=None, buttons=None, attention=False):
    """The prompter's own screen: a `notice` layout frame (Home family, list geometry: heading 12 px caps, a 22 px
    title on two balanced lines, a 14 px subtitle, a 12 px meta line in its tone, the footer; no art, no decode).
    `attention` sets activity "pending" (the Working comet) to draw the eye after a long automatic stretch."""
    return {"mode": "HOME", "target": "", "value": "", "detail": "", "status": "", "layout": "notice",
            "heading": heading, "title": say, "subtitle": progress, "meta": note,
            "metaTone": tone if (note and tone) else "meta", "activity": "pending" if attention else "idle",
            "ledStyle": "color", "ring": {"style": "off", "value": 0, "index": 0, "count": 0},
            "buttons": copy.deepcopy(buttons) if buttons is not None else blank_buttons()}


class OperatorStop(RuntimeError):
    """The operator did not complete a step (never a firmware failure). `exit_code` is the script's exit code."""
    exit_code = OPERATOR_EXIT
    kind = "operator"

    def __init__(self, step, of, name, title, reason, waited_s):
        super().__init__(reason)
        self.step, self.of, self.name, self.title, self.reason = step, of, name, title, reason
        self.waited_s = round(float(waited_s), 1)

    def record(self):
        return {"kind": self.kind, "step": self.step, "of": self.of, "name": self.name, "title": self.title,
                "reason": self.reason, "waitedS": self.waited_s, "exitCode": self.exit_code,
                "firmwareFailure": False}


class OperatorTimeout(OperatorStop):
    """A step's wait reached the safety timeout: "operator did not complete step N"."""
    kind = "operator-timeout"


class ScreenNotConfirmed(OperatorStop):
    """The display check (always step 1) was never confirmed: "screen not confirmed" (a dark screen or nobody there)."""
    exit_code = SCREEN_EXIT
    kind = "screen-not-confirmed"


def _events_of(batch, cid):
    return [(ts, m) for ts, m in batch if m.get("id") == cid]


class KnobPrompter:
    """Shows each instruction on the knob and advances only on the device events that prove it was done.

    `plan` names the steps in order; plan[0] must be DISPLAY_STEP, and until confirm_display() succeeds every other
    call raises RuntimeError("the display check comes first"). `next_id` hands out control ids (shared with the
    caller, so ids always advance). `finish(frame)` turns a frame into its wire form (check_nanod_cc5 passes the
    companion's device._frame with the live capabilities) and `validate(frame)` names what a parser would reject
    (a non-empty result raises before anything is sent). `timeout` bounds each wait for the operator.

    Screens: with base=None the prompter's own notice control (entered on first use, after a release, or when
    another control took the knob); with a base frame, an overlay (overlay()) sent on the control the knob holds now
    (the caller entered it, or enter() did). Events count only after the screen was sent, and claimed events only
    with the current control id; a press is complete at its ku. Console lines are a log only."""

    def __init__(self, knob, next_id, *, plan, finish=None, validate=None, timeout=PROMPT_STEP_TIMEOUT_S, log=print,
                 label="STEP", profile=PROMPT_PROFILE):
        plan = list(plan)
        if not plan or plan[0] != DISPLAY_STEP:
            raise ValueError(f"the display check comes first: plan[0] must be {DISPLAY_STEP!r}, not {plan[:1]}")
        if len(set(plan)) != len(plan):
            raise ValueError(f"step names repeat in the plan {plan}")
        self.knob, self.next_id, self.plan = knob, next_id, plan
        self.finish = finish or (lambda frame: frame)
        self.validate, self.timeout, self.log, self.label, self.profile = validate, float(timeout), log, label, profile
        self.confirmed = False
        self.cid, self.own = None, False           # the control shown on; own: a notice control the prompter entered
        self.view = None                           # the last screen (heading, say, progress, note, tone, buttons, ...)
        self.seq = PROMPT_SEQ_START
        self.steps, self.answers, self.current = [], {}, None
        self.display = {"confirmed": False, "button": YES_RAW + 1, "afterS": None, "retries": []}
        self.stopped = None
        self.keys = 0                              # buttons held (from kd/ku and every ks)
        self._mark = 0                             # knob.messages index when the current screen was sent
        self._scanned = 0                          # knob.messages index up to which the key state is known

    # -- bookkeeping -----------------------------------------------------------------------------
    def _require_confirmed(self):
        if not self.confirmed and not (self.current and self.current["name"] == DISPLAY_STEP):
            raise RuntimeError("the display check comes first")

    def _knob(self):
        if self.knob is None:
            raise RuntimeError("the prompter is detached (attach() a knob first)")
        return self.knob

    def heading(self, name=None):
        """The step label: "STEP n OF m" of `name` (default: the current step)."""
        name = name or (self.current or {}).get("name") or DISPLAY_STEP
        return f"{self.label} {self.plan.index(name) + 1} OF {len(self.plan)}"

    def _log(self, text):
        rec = self.current
        where = f"step {rec['n']}/{rec['of']} {rec['name']}" if rec else "screen"
        self.log(f"[knob] {where}: {text}")

    def mark(self):
        """A position in the knob's message list: wait(since=mark) counts only what arrives after it."""
        return len(self._knob().messages)

    def _sync_keys(self):
        knob = self._knob()
        for _, m in knob.messages[self._scanned:]:
            if isinstance(m.get("kd"), int):
                self.keys |= 1 << m["kd"]
            if isinstance(m.get("ku"), int):
                self.keys &= ~(1 << m["ku"])
            if type(m.get("ks")) is int:
                self.keys = m["ks"]
        self._scanned = len(knob.messages)
        return self.keys

    def begin(self, name):
        """Start step `name` (its record: n, of, name, title, shownAt, retries, doneAt, outcome). If a button is still
        held, "Let go of the buttons" comes first and the step starts after the key-ups."""
        if name != DISPLAY_STEP and not self.confirmed:
            raise RuntimeError("the display check comes first")
        if name not in self.plan:
            raise ValueError(f"step {name!r} is not in the plan {self.plan}")
        rec = {"n": self.plan.index(name) + 1, "of": len(self.plan), "name": name, "title": None, "shownAt": None,
               "retries": [], "doneAt": None, "outcome": None}
        self.steps.append(rec)
        self.current = rec
        self._log("begin")
        if self.knob is not None:
            self._let_go()
        return rec

    def _let_go(self):
        if not self._sync_keys():
            return
        self.screen(PROMPT_LET_GO_KEYS, "", "", buttons=blank_buttons())
        self.wait(lambda batch, now: True if not self.keys else None, what="the buttons released")

    # -- screens ---------------------------------------------------------------------------------
    @staticmethod
    def _view(heading, say, progress, note, tone, buttons, base, attention):
        return {"heading": heading, "say": say, "progress": progress, "note": note, "tone": tone,
                "buttons": copy.deepcopy(buttons) if buttons is not None else None, "base": base,
                "attention": attention}

    def _render(self, view):
        if view["base"] is None:
            frame = prompt_frame(view["heading"], view["say"], view["progress"], view["note"], view["tone"],
                                 view["buttons"], view["attention"])
        else:
            frame = overlay(view["base"], view["heading"], view["say"], view["progress"], view["note"], view["tone"])
            frame.pop("feedback", None)
            if view["buttons"] is not None:
                frame["buttons"] = copy.deepcopy(view["buttons"])
            if view["attention"]:
                frame["activity"] = "pending"
        return frame

    def dressed(self, frame):
        """`frame` in its wire form (finish), checked by `validate`: raises ValueError before anything is sent."""
        wire = self.finish(frame)
        if self.validate is not None:
            invalid = self.validate(wire)
            if invalid:
                raise ValueError(f"a prompt frame the knob would reject ({invalid}): {frame.get('title')!r}")
        return wire

    def _send(self, frame, *, new_screen=True):
        knob = self._knob()
        wire = self.dressed({**frame, "id": self.cid})
        knob.frame(wire)
        if new_screen:
            self._mark = len(knob.messages)
        return wire

    def _enter(self, frame, profile, maximum, position, windows_button=2, windows_hid=False, extra=None):
        knob = self._knob()
        if extra:
            problems = control_extra_problems(extra)
            if problems:
                raise ValueError(f"control fields the knob would reject: {problems}")
        cid = self.next_id()
        self.seq += 1
        wire = self.dressed({**frame, "id": cid, "feedback": {"kind": PROMPT_SEED_KIND, "seq": self.seq}})
        knob.enter(raw_control(cid, profile, maximum, position, wire, windows_button=windows_button,
                               windows_hid=windows_hid, extra=extra))
        self.cid = cid
        # The feedback seq is seeded by the first frame after a claim (P4 5.8): the control frame and this line
        # carry the same seq, so whichever the firmware takes as the first frame, the next flash plays once.
        knob.frame(wire)
        self._mark = len(knob.messages)
        return cid

    def _claimed_here(self):
        return self.cid is not None and self._knob().control_id == self.cid

    def _shown(self, say):
        rec = self.current
        if rec is not None and rec["shownAt"] is None:
            rec["title"], rec["shownAt"] = say, round(self._knob().now(), 3)

    def screen(self, say, progress="", note="", tone=None, buttons=None, base=None, attention=False, heading=None):
        """Show one instruction (a new screen: events count from here). base=None: the prompter's notice control;
        a base frame: its overlay on the control the knob holds now. Returns the control id."""
        self._require_confirmed()
        knob = self._knob()
        view = self._view(heading or self.heading(), say, progress, note, tone, buttons, base, attention)
        frame = self._render(view)
        if base is None:
            if self.own and self._claimed_here():
                self._send(frame)
            else:
                self._enter(frame, self.profile, PROMPT_MAX, PROMPT_POSITION)
                self.own = True
        else:
            if knob.control_id is None:
                raise RuntimeError("an overlay needs a claimed control (enter() one first)")
            self.cid, self.own = knob.control_id, False
            self._send(frame)
        self.view = view
        self._shown(say)
        self._log(f"shown {say!r}" + (f" / {progress!r}" if progress else "") + (f" / {note!r}" if note else ""))
        return self.cid

    def update(self, **changes):
        """Redraw the current screen with some of its parts changed (say, progress, note, tone, buttons, base,
        attention): live progress. Not a new screen: events already counted still count."""
        if self.view is None:
            raise RuntimeError("nothing shown yet")
        self.view = {**self.view, **changes}
        return self._send(self._render(self.view), new_screen=False)

    def enter(self, base=None, profile=PROMPT_PROFILE, maximum=PROMPT_MAX, position=PROMPT_POSITION, *,
              windows_button=2, windows_hid=False, say="", progress="", note="", tone=None, buttons=None,
              attention=False, heading=None, extra=None):
        """Enter a new control (it supersedes the claimed one) whose frame is overlay(base) (base None: the notice
        screen). Ready ks keeps being recorded (knob.ready_replies). `extra`: r4 control fields (feel_fields: feel,
        reducedHaptics, sound, soundVolume), validated before anything is sent. Returns its id; it is the current
        screen."""
        self._require_confirmed()
        view = self._view(heading or self.heading(), say, progress, note, tone, buttons, base, attention)
        cid = self._enter(self._render(view), profile, maximum, position, windows_button, windows_hid, extra)
        self.own = base is None
        self.view = view
        self._shown(say)
        self._log(f"entered control {cid}: {say!r}")
        return cid

    def flash(self, kind):
        """The ok (target flash) or err (Head shake) LED moment on the current screen."""
        if self.view is None:
            raise RuntimeError("nothing shown yet")
        self.seq += 1
        frame = {**self._render(self.view), "feedback": {"kind": kind, "seq": self.seq}}
        return self._send(frame, new_screen=False)

    def done(self, say=PROMPT_DONE, note=""):
        """The step is complete: an ok flash, `say` on the note line in the success tone (and `note`, when given, on
        the progress line) for PROMPT_DONE_S; the step record gets doneAt and outcome "done"."""
        knob = self._knob()
        changes = {"note": say, "tone": "success"}
        if note:
            changes["progress"] = note
        self.view = {**self.view, **changes}
        self.flash("ok")
        knob.pump(PROMPT_DONE_S)
        rec = self.current
        if rec is not None:
            rec["doneAt"], rec["outcome"] = round(knob.now(), 3), "done"
            self._log(f"done after {knob.now() - (rec['shownAt'] or knob.now()):.1f} s")

    def retry(self, reason):
        """A wrong or incomplete action: an err flash and `reason` on the note line (error tone); the step stays."""
        knob = self._knob()
        rec = self.current
        if rec is not None:
            rec["retries"].append({"at": round(knob.now(), 3), "reason": reason})
        self.view = {**self.view, "note": reason, "tone": "error"}
        self.flash("err")
        self._log(f"retry {reason}")

    def acknowledge(self, text):
        """A short ok flash with `text` in the success tone for PROMPT_DONE_S (an answer taken), not ending a step."""
        self.view = {**self.view, "note": text, "tone": "success"}
        self.flash("ok")
        self._knob().pump(PROMPT_DONE_S)

    # -- waiting ---------------------------------------------------------------------------------
    def _stop(self, what, waited):
        rec = self.current or {"n": 0, "of": len(self.plan), "name": None, "title": None}
        if rec.get("name") == DISPLAY_STEP and not self.confirmed:
            exc = ScreenNotConfirmed(rec["n"], rec["of"], rec["name"], rec.get("title"), "screen not confirmed", waited)
        else:
            exc = OperatorTimeout(rec["n"], rec["of"], rec["name"], rec.get("title"),
                                  f"operator did not complete step {rec['n']}", waited)
        if self.current is not None:
            self.current["outcome"] = exc.kind
        self.stopped = {**exc.record(), "waitingFor": what}
        self._log(f"STOPPED: {exc.reason} (waited {waited:.0f} s for {what})")
        return exc

    def stop(self, what, waited):
        """The OperatorStop (OperatorTimeout, or ScreenNotConfirmed during the display check) for a wait the caller
        ran itself (e.g. inside a stress pass), recorded like wait()'s own; the caller raises it."""
        return self._stop(what, waited)

    def wait(self, check, *, what, since=None, tick=None, timeout=None):
        """Pump (heartbeats continue) until check(batch, now) returns something other than None; `batch` is the
        (time, message) list that arrived since the previous call, starting at the current screen (or `since`, a
        mark()). tick(now) may redraw progress. After `timeout` (default: the prompter's) the run stops:
        OperatorTimeout, or ScreenNotConfirmed during the display check."""
        knob = self._knob()
        cursor = self._mark if since is None else since
        limit = self.timeout if timeout is None else float(timeout)
        started = knob.now()
        while True:
            batch = knob.messages[cursor:]
            cursor += len(batch)
            self._sync_keys()
            now = knob.now()
            result = check(batch, now)
            if result is not None:
                return result
            if tick is not None:
                tick(now)
            if now - started >= limit:
                raise self._stop(what, now - started)
            knob.pump(PROMPT_PUMP_S)

    def press_events(self, raw, *, wrong="That was Button {n}", what=None, ids=None):
        """Wait for one complete press of Button raw+1 on the current control (or any of `ids`): its kd, then its
        ku. A kd of another button is a retry with `wrong` (formatted with n, that button's number). Returns
        {"kd": (time, msg), "ku": (time, msg)}."""
        ids = set(ids) if ids else {self.cid}
        state = {"kd": None}

        def check(batch, now):
            for ts, m in batch:
                if m.get("id") not in ids:
                    continue
                if isinstance(m.get("kd"), int) and state["kd"] is None:
                    if m["kd"] == raw:
                        state["kd"] = (ts, m)
                        self._log(f"event kd {raw}")
                    else:
                        self.retry(wrong.format(n=m["kd"] + 1))
                if m.get("ku") == raw and state["kd"] is not None:
                    self._log(f"event ku {raw}")
                    return {"kd": state["kd"], "ku": (ts, m)}
            return None
        return self.wait(check, what=what or f"a press of Button {raw + 1}")

    def press(self, raw, say, progress="", note="", base=None, buttons=None, attention=False):
        """Show `say` (only Button raw+1 lit on the notice screen; a base keeps its own buttons unless `buttons`)
        and wait for one complete press of it (press_events)."""
        self._require_confirmed()
        if base is None and buttons is None:
            buttons = press_buttons(raw)
        self.screen(say, progress, note, buttons=buttons, base=base, attention=attention)
        return self.press_events(raw)

    def confirm_display(self):
        """Step 1 of every flow: "Can you see this? Press Button 4". Needs kd and ku of Button 4 on this screen's
        control, both after it was sent; another button is a retry. Never confirmed within the timeout:
        ScreenNotConfirmed. Nothing else can be shown before it succeeds."""
        knob = self._knob()
        rec = self.begin(DISPLAY_STEP)
        self.screen(PROMPT_SEE, PROMPT_SEE_SUB, PROMPT_SEE_NOTE, buttons=press_buttons(YES_RAW))
        shown = knob.now()
        self.press_events(YES_RAW, what="Button 4 on the display check")
        self.confirmed = True
        self.display.update(confirmed=True, afterS=round(knob.now() - shown, 3), retries=list(rec["retries"]),
                            controlId=self.cid)
        self.done()
        return self.display

    def ask(self, key, question, detail="", base=None):
        """A Yes/No question answered on the knob (Button 4 = Yes, Button 1 = No; any other button is a retry).
        When `key` is a step of the plan it is begun here and completed by the answer; otherwise the question
        belongs to the current step. Records answers[key]; returns the answer."""
        self._require_confirmed()
        began = key in self.plan and (self.current is None or self.current["name"] != key)
        if began:
            self.begin(key)
        if base is None:
            self.screen(question, detail, PROMPT_YES_NO, buttons=yes_no_buttons())
        else:
            self.screen(question, "", PROMPT_YES_NO, buttons=yes_no_buttons(), base=base)
        cid, state = self.cid, {"kd": None}

        def check(batch, now):
            for ts, m in _events_of(batch, cid):
                if isinstance(m.get("kd"), int) and state["kd"] is None:
                    if m["kd"] in (YES_RAW, NO_RAW):
                        state["kd"] = m["kd"]
                    else:
                        self.retry(PROMPT_YES_NO_RETRY.format(n=m['kd'] + 1))
                if state["kd"] is not None and m.get("ku") == state["kd"]:
                    return state["kd"] == YES_RAW
            return None
        answer = self.wait(check, what=f"an answer to {question!r}")
        self.answers[key] = answer
        self._log(f"answer {key}: {'yes' if answer else 'no'}")
        if began:
            self.done("Yes" if answer else "No")
        else:
            self.acknowledge("Yes" if answer else "No")
        return answer

    def hands_off(self, heading, say, progress="", note="", dwell=0.0):
        """A screen that is not a step (the automatic parts): "HANDS OFF", "YOU CAN LEAVE", ... on the notice
        control, shown for `dwell` s."""
        self._require_confirmed()
        self.current = None
        self.screen(say, progress, note, buttons=blank_buttons(), heading=heading)
        if dwell:
            self._knob().pump(dwell)

    def quiet(self, seconds, *, what="no knob events", timeout=None):
        """Wait until `seconds` pass with no knob event at all (claimed of any control, or native). Returns how many
        events arrived before the quiet began."""
        self._require_confirmed()
        knob = self._knob()
        state = {"last": knob.now(), "events": 0}

        def check(batch, now):
            touched = [ts for ts, m in batch if is_knob_event(m)]
            if touched:
                state["last"], state["events"] = max(touched), state["events"] + len(touched)
            return state["events"] if now - state["last"] >= seconds else None
        return self.wait(check, what=what, since=self.mark(), timeout=timeout)

    # -- unclaimed observation (the knob's own screen) and handing the port over --------------------
    def release(self):
        """Release the claimed control (intentional release: the knob shows its native screen)."""
        knob = self._knob()
        reply = knob.release()
        self.cid, self.own = None, False
        self._log("released")
        return reply

    def unclaimed(self, seconds=None, until=None, touch=None):
        """With nothing claimed (after release()), pump without heartbeats and collect the native events (no id).
        Returns {"touched", "events", "seconds"} when until(events, now) is true, when `seconds` passed, or (touch
        "restart") at the first native event, which is then in "touched". Without `seconds`, the safety timeout
        applies (OperatorTimeout)."""
        self._require_confirmed()
        knob = self._knob()
        first, started = len(knob.native_events), knob.now()

        def check(batch, now):
            events = list(knob.native_events[first:])
            if touch == "restart" and events:
                return {"touched": events, "events": events, "seconds": round(now - started, 3)}
            if until is not None and until(events, now):
                return {"touched": [], "events": events, "seconds": round(now - started, 3)}
            if seconds is not None and now - started >= seconds:
                return {"touched": [], "events": events, "seconds": round(now - started, 3)}
            return None
        limit = None if seconds is None else max(self.timeout, float(seconds) + 5.0)
        return self.wait(check, what="the knob's own screen", since=self.mark(), timeout=limit)

    def resume(self):
        """Claim again after release()/attach(): a new notice control showing the last notice screen."""
        self._require_confirmed()
        view = self.view if (self.view and self.view["base"] is None) else None
        if view is None:
            view = self._view(self.heading(), "One moment", "", "", None, blank_buttons(), None, False)
        self.own = False
        return self.screen(view["say"], view["progress"], view["note"], view["tone"], view["buttons"],
                           heading=view["heading"])

    def detach(self):
        """Release and close the port (another program, e.g. Desk Dial, can then open it). Stays confirmed."""
        knob = self._knob()
        knob.release_quietly()
        knob.close()
        self.knob, self.cid, self.own = None, None, False
        self.log("[knob] detached: the port is closed")

    def attach(self, knob):
        """Take a newly opened RawKnob: pump, release (which also clears a host-lost notice), then resume()."""
        self.knob, self._scanned, self._mark, self.cid, self.own, self.keys = knob, 0, 0, None, False, 0
        knob.pump(0.3)
        knob.release_quietly()
        self.log("[knob] attached")
        return self.resume()

    def evidence(self):
        return {"plan": list(self.plan), "displayCheck": dict(self.display), "steps": copy.deepcopy(self.steps),
                "answers": dict(self.answers), "stopped": self.stopped}


# Pure helpers of the hands-on flows (unit-tested; the gate functions above are unchanged).

class TurnMeter:
    """Live measure of the turning test. update() takes the stress control's claimed positions [(time, p)] and lims
    [(time, dir)]; inside the window (begin_window) turned_s accumulates only while position events arrive: the sum
    of the gaps between consecutive events, each capped at GAP_CAP_S. It tracks the ends (p == 0: -1, p == maximum:
    +1), the lims seen, the stall (now minus the last position, at most since the window start) and broken (a stall
    over TURN_MAX_GAP_S). complete(): turned_s >= target, both ends, and both lims (with `need_lims`; when a knob
    sends none, `lim_wait_s` of turning after both ends completes it anyway and limit_problems fails the gate)."""
    GAP_CAP_S = 0.5
    START_EVENTS, START_WITHIN_S = 3, 1.5
    NUDGE_S = 1.5

    def __init__(self, maximum, target_s, *, need_lims=True, lim_wait_s=10.0):
        self.maximum, self.target_s, self.need_lims, self.lim_wait_s = maximum, float(target_s), need_lims, lim_wait_s
        self.window_start, self.last_p, self.recent = None, None, []
        self.turned_s, self.events, self.ends, self.lims, self.ends_at, self.now = 0.0, 0, set(), set(), None, 0.0

    def begin_window(self, now):
        self.window_start, self.turned_s, self.events = now, 0.0, 0
        self.ends, self.lims, self.ends_at = set(), set(), None
        self.now = max(self.now, now)

    def update(self, positions, lims, now):
        for ts, p in sorted(positions, key=lambda item: item[0]):
            if self.window_start is not None and ts >= self.window_start:
                previous = self.last_p if self.last_p is not None else self.window_start
                self.turned_s += min(self.GAP_CAP_S, max(0.0, ts - max(previous, self.window_start)))
                self.events += 1
                if p == 0:
                    self.ends.add(-1)
                if p == self.maximum:
                    self.ends.add(1)
            self.last_p = ts if self.last_p is None else max(self.last_p, ts)
            self.recent = [x for x in self.recent if ts - x <= self.START_WITHIN_S] + [ts]
        for ts, d in lims:
            if self.window_start is not None and ts >= self.window_start and d in (-1, 1):
                self.lims.add(d)
        self.now = max(self.now, now)
        if self.ends == {-1, 1} and self.ends_at is None:
            self.ends_at = self.now

    def started(self, now=None):
        """At least START_EVENTS positions within START_WITHIN_S: the operator is turning."""
        now = self.now if now is None else now
        return sum(1 for ts in self.recent if now - ts <= self.START_WITHIN_S) >= self.START_EVENTS

    def stalled_s(self, now=None):
        now = self.now if now is None else now
        refs = [x for x in (self.last_p, self.window_start) if x is not None]
        return max(0.0, now - max(refs)) if refs else 0.0

    def broken(self, now=None):
        return self.window_start is not None and self.stalled_s(now) > TURN_MAX_GAP_S

    def lims_ok(self):
        return not self.need_lims or self.lims >= {-1, 1}

    def end_done(self, direction):
        return direction in self.ends and (not self.need_lims or direction in self.lims)

    def complete(self, now=None):
        now = self.now if now is None else now
        if self.window_start is None or self.turned_s < self.target_s or self.ends != {-1, 1}:
            return False
        return self.lims_ok() or (self.ends_at is not None and now - self.ends_at >= self.lim_wait_s)

    def progress(self):
        return f"Turned {min(int(self.turned_s), int(self.target_s))} of {int(self.target_s)} s"

    def note(self, now=None):
        """(text, tone) for the note line: a stall first, then what is still missing at the ends."""
        if self.stalled_s(now) > self.NUDGE_S:
            return "Don’t stop turning", "error"
        left, right = self.end_done(-1), self.end_done(1)
        if left and right:
            return "Both ends done", None
        if left:
            return "Left end done · right next", None
        if right:
            return "Right end done · left next", None
        if self.ends == {-1, 1}:
            return "Push past each end", None
        return "Reach both ends", None

    def record(self):
        return {"turnedS": round(self.turned_s, 2), "targetS": self.target_s, "events": self.events,
                "ends": sorted(self.ends), "lims": sorted(self.lims), "limsNeeded": self.need_lims,
                "windowStart": None if self.window_start is None else round(self.window_start, 3)}


class EndStopWindows:
    """The End stop windows of one run, from the prompts (ALIVE.md 12.5 ruling Q1): each push window runs from the
    moment its prompt frame was sent to the end of its quiet period (PROMPT_QUIET_S without a lim after the last
    one), so consecutive windows touch and each already includes the line's arrival; evaluate() feeds them to
    limit_push_problems with grace 0. A second lim inside a quiet period is recorded as a double (chatter)."""

    def __init__(self):
        self.pushes, self.hold, self.doubles, self.missed = [], None, [], []

    def push(self, start, end, missed=False):
        self.pushes.append((start, end))
        if missed:
            self.missed.append(len(self.pushes))

    def held(self, start, end):
        self.hold = (start, end)

    def double(self, window, at):
        self.doubles.append({"window": window, "at": round(at, 3)})

    def end(self):
        """The end of the push phase (the hold window's end, else the last push's)."""
        if self.hold is not None:
            return self.hold[1]
        return self.pushes[-1][1] if self.pushes else None

    def evaluate(self, lims, direction=1):
        """limit_push_problems over the lims up to the end of the push phase."""
        end = self.end()
        hold = self.hold if self.hold is not None else (0.0, -1.0)
        use = [x for x in lims if end is None or x[0] <= end]
        return limit_push_problems(use, self.pushes, hold, direction=direction, grace=0.0)

    def record(self, origin=0.0):
        def span(window):
            return [round(window[0] - origin, 3), round(window[1] - origin, 3)]
        return {"pushes": [span(w) for w in self.pushes], "hold": span(self.hold) if self.hold else None,
                "doubles": [{**d, "at": round(d["at"] - origin, 3)} for d in self.doubles], "missed": list(self.missed),
                "graceS": 0.0, "quietS": PROMPT_QUIET_S}


DEFERRED_KH_ESTIMATE_S = 0.476      # hardware (1.0.0-cc5.4 A, 2026-09-26): kh 0.444-0.506 s after the host saw the kd
DEFERRED_ENTRY_S = 0.022            # an entry takes ~22 ms (diag enterMsLast when the knob reports it)
DEFERRED_OFFSETS_S = (0.0, -0.02, 0.02, -0.04, 0.04, -0.01, 0.01, -0.03)
DEFERRED_MIN_DELAY_S = 0.2


class DeferredPlanner:
    """When to enter the new control of the deferred-hold test: next_delay() = max(0.2, estimate - entry/2 + offset k)
    after the host sees the kd, so the long press matures in the middle of the entry; observe(kh - kd) of an attempt
    that did not defer refines the estimate (the running mean of the delays measured, within HOLD_ARRIVAL_S)."""

    def __init__(self, entry_s=None, estimate=DEFERRED_KH_ESTIMATE_S, offsets=DEFERRED_OFFSETS_S):
        self.entry_s = entry_s if entry_s else DEFERRED_ENTRY_S
        self.estimate, self.offsets, self.observed, self.k = estimate, tuple(offsets), [], 0

    def entry(self, enter_ms):
        """Take diag enterMsLast (ms) when the knob reports it."""
        if type(enter_ms) is int and enter_ms > 0:
            self.entry_s = enter_ms / 1000.0
        return self.entry_s

    def next_delay(self):
        offset = self.offsets[self.k % len(self.offsets)]
        self.k += 1
        return max(DEFERRED_MIN_DELAY_S, self.estimate - self.entry_s / 2 + offset)

    def repeat(self):
        """The last delay was not tried (the button came up too soon): the next attempt uses it again."""
        self.k = max(0, self.k - 1)

    def observe(self, kh_after_kd_s):
        if kh_after_kd_s is not None and HOLD_ARRIVAL_S[0] <= kh_after_kd_s <= HOLD_ARRIVAL_S[1]:
            self.observed.append(kh_after_kd_s)
            self.estimate = statistics.mean(self.observed)
        return self.estimate

    def record(self):
        return {"estimateS": round(self.estimate, 4), "entryS": self.entry_s,
                "observedS": [round(x, 4) for x in self.observed], "delays": self.k}



# ---------------------------------------------------------------------------
# Consistent builds and a redraw check (added 2026-09-30 after the cc5.7 failure).
#
# What happened: include/lv_conf.h (LV_OBJ_STYLE_CACHE 0 -> 1) changed after LVGL's objects were compiled, and the
# incremental build recompiled only part of src/. platformio.ini includes lv_conf.h through
# -DLV_CONF_PATH=..., a macro include that the build system's dependency scan cannot see. The image mixed two
# lv_obj_t layouts: an inline lv_obj_set_user_data in cc_display.cpp wrote into LVGL's coords.y1. The host screen
# became zero-size, so it was never drawn, and the knob kept showing its native screen.
#
# The guards:
#   * build_nanod_cc5.py empties the binary's build folder before every build (clean_build_folder);
#   * every object file must have been compiled by that run and be newer than the config headers
#     (stale_object_problems);
#   * the host harness (harness) must have been built with the firmware's lv_conf.h
#     (harness_conf_problems);
#   * after a flash, check_nanod_cc5_look.py claims the knob, changes frames and requires flushes
#     (redraw_check / redraw_problems).

BUILD_CONFIG_HEADERS = ("include/lv_conf.h", "include/nanofoc_d.h")   # relative to FIRMWARE_SOURCE
OBJECT_SUFFIXES = (".o", ".a")
BUILD_CLOCK_SLACK_S = 2.0                   # file-system timestamp granularity
HARNESS_HOST_OVERRIDES = {"LV_USE_TFT_ESPI": ("1", "0")}   # harness/build.py HOST_OVERRIDES
REDRAW_SETTLE_S = 1.2                       # after the claim, so its own full refresh leaves the diag window
REDRAW_SECONDS = 3.4                        # frames alternate this long
REDRAW_FRAME_EVERY_S = 0.4
REDRAW_DIAG_EVERY_S = 1.0
REDRAW_MIN_LIVE_SAMPLES = 2                 # diag windows that must show flushes (lcdFps >= 1, lcdFlushUs > 0)
REDRAW_CONTROL_ID = 907
REDRAW_FIELDS = ("lcdFps", "lcdFlushUs", "lcdFullRefrs", "lcdStep", "sessionPhase", "ledMode")


def build_folder(p):
    """The folder PlatformIO builds binary `p` into (its PLATFORMIO_BUILD_DIR, else the project's .pio/build)."""
    return p.build_dir if p.build_dir is not None else FIRMWARE_SOURCE / ".pio" / "build"


def clean_build_folder(folder):
    """Delete `folder` (a build folder directly inside FIRMWARE_SOURCE/.pio, named build or build-*) so the next
    build compiles every file. Returns how many files were removed. Anything else is refused (ValueError)."""
    import shutil
    folder = Path(folder)
    pio = (FIRMWARE_SOURCE / ".pio").resolve()
    resolved = folder.resolve()
    if resolved.parent != pio or not (resolved.name == "build" or resolved.name.startswith("build-")):
        raise ValueError(f"{folder} is not a build folder inside {pio}; not deleting it")
    if not resolved.exists():
        return 0
    removed = sum(1 for path in resolved.rglob("*") if path.is_file())
    shutil.rmtree(resolved)
    return removed


def stale_object_problems(folder, started_epoch, config_files=None):
    """(record, problems) for the object files under `folder` after a build that started at `started_epoch` (Unix
    seconds): every one must be compiled by that build and be newer than every config header that exists
    (BUILD_CONFIG_HEADERS). An object older than a header was compiled with a config that no longer exists."""
    folder = Path(folder)
    if config_files is None:
        config_files = [FIRMWARE_SOURCE / name for name in BUILD_CONFIG_HEADERS]
    headers = {Path(path).name: Path(path).stat().st_mtime for path in config_files if Path(path).is_file()}
    objects = [path for path in folder.rglob("*") if path.suffix in OBJECT_SUFFIXES and path.is_file()] \
        if folder.is_dir() else []
    before_build, before_header = [], {}
    for path in objects:
        mtime = path.stat().st_mtime
        rel = path.relative_to(folder).as_posix()
        if mtime < started_epoch - BUILD_CLOCK_SLACK_S:
            before_build.append(rel)
        for name, header_mtime in headers.items():
            if mtime < header_mtime:
                before_header.setdefault(name, []).append(rel)
    record = {"folder": str(folder), "objects": len(objects), "configHeaders": sorted(headers),
              "compiledBeforeThisBuild": len(before_build),
              "olderThanConfig": {k: len(v) for k, v in before_header.items()},
              "examples": sorted(before_build)[:5], "passed": False}
    problems = []
    if not objects:
        problems.append(f"no object files under {folder}: the build cannot be shown to be complete")
    if before_build:
        problems.append(f"{len(before_build)} of {len(objects)} object files were not compiled by this build "
                        f"(for example {', '.join(sorted(before_build)[:3])}): a partial rebuild can mix configs")
    for name, rels in sorted(before_header.items()):
        problems.append(f"{len(rels)} object files are older than {name} (for example {', '.join(sorted(rels)[:3])}): "
                        "they were compiled with a config that has since changed")
    record["passed"] = not problems
    return record, problems


def lv_conf_defines(text):
    """The `#define NAME VALUE` lines of an lv_conf.h, in order, as (NAME, VALUE) with comments and extra
    whitespace removed."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    out = []
    for line in text.splitlines():
        line = line.split("//", 1)[0].strip()
        match = re.match(r"#\s*define\s+([A-Za-z_]\w*)(?:\s+(.*))?$", line)
        if match:
            out.append((match.group(1), " ".join((match.group(2) or "").split())))
    return out


def harness_firmware_units(cmakelists, firmware_src):
    """The firmware files the harness compiles: every "${NANOD_FIRMWARE_SRC}/<name>" source named in its
    CMakeLists.txt (firmware_shared, firmware_shared_full, jpeg_glue), the header next to each, the generated
    fonts (src/fonts/cc_font_*.c, the CMakeLists glob), and every local header those files reach through
    #include "..." lines, followed transitively (cc_presentation.h, cc_lcd_logic.h, cc_sleep.h, fonts/cc_fonts.h,
    ...). An include resolves against the including file's folder, then firmware_src, then firmware_src/fonts; only
    files inside firmware_src count. Only files that exist; empty without a CMakeLists."""
    cmakelists, firmware_src = Path(cmakelists), Path(firmware_src)
    if not cmakelists.is_file():
        return []
    text = cmakelists.read_text(encoding="utf-8", errors="replace")
    names = sorted(set(re.findall(r'"\$\{NANOD_FIRMWARE_SRC\}/([^"$*{}]+\.(?:cpp|c))"', text)))
    units = []
    for name in names:
        source = firmware_src / name
        units += [source, source.with_suffix(".h")]
    units += sorted((firmware_src / "fonts").glob("cc_font_*.c"))
    seen, out = set(), []
    queue = list(units)
    while queue:
        path = queue.pop(0)
        key = os.path.normcase(str(_resolved(path) or path))
        if not path.is_file() or key in seen:
            continue
        seen.add(key)
        out.append(path)
        queue += _local_includes(path, firmware_src)
    return out


_INCLUDE_LINE = re.compile(r'^[ 	]*#[ 	]*include[ 	]*"([^"]+)"', re.M)


def _local_includes(path, firmware_src):
    """The files a source's #include "..." lines name that exist inside firmware_src (resolved against the
    including file's folder, then firmware_src, then firmware_src/fonts)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    root = _resolved(firmware_src)
    found = []
    for name in _INCLUDE_LINE.findall(text):
        for base in (Path(path).parent, firmware_src, firmware_src / "fonts"):
            candidate = base / name
            resolved = _resolved(candidate)
            if resolved is None or not candidate.is_file():
                continue
            if root is not None and root in resolved.parents:
                found.append(Path(firmware_src) / resolved.relative_to(root))
                break
    return found


def _resolved(path):
    try:
        return Path(path).resolve()
    except OSError:
        return None


def cmake_cache_value(cache, name):
    """The value of `name` in a CMakeCache.txt (NAME:TYPE=value), or None."""
    cache = Path(cache)
    if not cache.is_file():
        return None
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.split(":", 1)[0] == name:
            return value.strip()
    return None


def _same_dir(a, b):
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def harness_conf_problems(firmware_conf=None, harness_conf=None, harness_exe=None, *, cmake_cache=None,
                          firmware_src=None, cmakelists=None):
    """(record, problems): the host harness (harness) was built with the firmware's lv_conf.h and its
    current sources. Every #define of the harness copy must equal the firmware's, apart from HARNESS_HOST_OVERRIDES;
    the harness renderer must be newer than its copy and than every firmware unit the harness compiles
    (harness_firmware_units: a renderer older than src/cc_display.cpp renders the old code); and the build's
    CMakeCache NANOD_LV_CONF_DIR must be the harness folder (a cached scratch lv_conf.h, as perf.py's
    build-perf-conf uses, would keep compiling). Without a firmware lv_conf.h there is nothing to compare (passed)."""
    firmware_conf = Path(firmware_conf or FIRMWARE_SOURCE / "include" / "lv_conf.h")
    harness_conf = Path(harness_conf or ROOT / "harness" / "lv_conf.h")
    harness_exe = Path(harness_exe or ROOT / "harness" / "build" / "Release" / "lcd-preview.exe")
    harness_dir = harness_conf.parent
    cmake_cache = Path(cmake_cache or harness_dir / "build" / "CMakeCache.txt")
    firmware_src = Path(firmware_src or firmware_conf.parent.parent / "src")
    cmakelists = Path(cmakelists or harness_dir / "CMakeLists.txt")
    record = {"firmwareConf": str(firmware_conf), "harnessConf": str(harness_conf), "harnessExe": str(harness_exe),
              "differences": [], "newerSources": [], "lvConfDir": None, "applicable": firmware_conf.is_file(),
              "passed": True}
    if not firmware_conf.is_file():
        return record, []
    problems = []
    rebuild = "run harness/build.py and re-check the renders"
    if not harness_conf.is_file():
        problems.append(f"the harness has no lv_conf.h ({harness_conf}): {rebuild}")
    else:
        expected = [(name, HARNESS_HOST_OVERRIDES[name][1] if name in HARNESS_HOST_OVERRIDES
                     and value == HARNESS_HOST_OVERRIDES[name][0] else value)
                    for name, value in lv_conf_defines(firmware_conf.read_text(encoding="utf-8", errors="replace"))]
        actual = lv_conf_defines(harness_conf.read_text(encoding="utf-8", errors="replace"))
        if expected != actual:
            want, have = dict(expected), dict(actual)
            diffs = [f"{name}: firmware {want.get(name)!r}, harness {have.get(name)!r}"
                     for name in sorted(set(want) | set(have)) if want.get(name) != have.get(name)]
            record["differences"] = diffs or ["the #define order differs"]
            problems.append(f"the harness's lv_conf.h differs from the firmware's ({'; '.join(record['differences'][:3])}): "
                            f"its renders are not evidence for this build; {rebuild}")
        elif not harness_exe.is_file() or harness_exe.stat().st_mtime < harness_conf.stat().st_mtime:
            problems.append(f"the harness renderer is missing or older than its lv_conf.h: {rebuild}")
        else:
            built = harness_exe.stat().st_mtime
            newer = [path for path in harness_firmware_units(cmakelists, firmware_src) if path.stat().st_mtime > built]
            record["newerSources"] = [path.relative_to(firmware_src).as_posix() for path in newer]
            if newer:
                listed = ", ".join(record["newerSources"][:4]) + (" ..." if len(newer) > 4 else "")
                problems.append(f"the harness renderer is older than firmware sources it compiles ({listed}): its "
                                f"renders show the old code; {rebuild}")
    conf_dir = cmake_cache_value(cmake_cache, "NANOD_LV_CONF_DIR")
    record["lvConfDir"] = conf_dir
    if conf_dir is not None and not _same_dir(conf_dir, harness_dir):
        problems.append(f"the harness build compiles the lv_conf.h in {conf_dir} (CMakeCache NANOD_LV_CONF_DIR), not "
                        f"the harness copy in {harness_dir}: {rebuild}")
    record["passed"] = not problems
    return record, problems


def redraw_problems(samples):
    """Why the knob did not redraw while claimed with changing frames (empty: it did). `samples` are the diag
    fields read once a second while the frames alternated; a live one shows lcdFps >= 1 and lcdFlushUs > 0."""
    live = [s for s in samples if isinstance(s, dict) and (diag_int(s, "lcdFps") or 0) >= 1
            and (diag_int(s, "lcdFlushUs") or 0) > 0]
    if len(live) >= REDRAW_MIN_LIVE_SAMPLES:
        return []
    figures = ", ".join(f"fps {s.get('lcdFps')} / flush {s.get('lcdFlushUs')} us" for s in samples if isinstance(s, dict))
    return [f"the screen did not redraw while the frames changed: {len(live)} of {len(samples)} one-second windows "
            f"flushed pixels (at least {REDRAW_MIN_LIVE_SAMPLES} needed; {figures or 'no diag replies'}); the knob "
            "is not drawing the Desk Dial screens"]


def redraw_frames(path=None):
    """(control, [frame A, frame B]) for the redraw check: work/lcd_bench_frames.json with its own control id and
    neither feedback nor artwork (only the text and layout change)."""
    data = load_json(Path(path or WORK / "lcd_bench_frames.json"))
    frames = []
    for frame in data["frames"][:2]:
        frame = copy.deepcopy(frame)
        frame["id"] = REDRAW_CONTROL_ID
        frame.pop("feedback", None)
        frame.pop("artKey", None)
        frames.append(frame)
    control = copy.deepcopy(data["control"])
    control["id"] = REDRAW_CONTROL_ID
    control["frame"] = frames[0]
    return control, frames


def redraw_check(port, *, knob_factory=None, clock=time.monotonic, sleep=time.sleep, frames_path=None):
    """Claim the knob on `port`, alternate two frames for REDRAW_SECONDS while reading diag once a second, then
    release it (the knob returns to its native screen). Returns {"samples", "claimErrors", "problems", "passed"};
    the knob is released even when a step fails."""
    control, frames = redraw_frames(frames_path)
    factory = knob_factory or (lambda device: RawKnob(device, paced=False))
    samples, problems, errors = [], [], []
    knob = None
    try:
        # Opened inside the try (TL-BUG-011): a port that cannot be reopened (the companion grabbed it, Windows still
        # holds the handle, the knob re-enumerated) is a recorded problem, never an uncaught exception.
        knob = factory(port)
        knob.enter(control)
        knob.pump(REDRAW_SETTLE_S)
        start = clock()
        last_frame = last_diag = start
        index = 0
        while clock() - start < REDRAW_SECONDS:
            now = clock()
            if now - last_frame >= REDRAW_FRAME_EVERY_S:
                index += 1
                knob.frame(frames[index % 2])
                last_frame = now
            if now - last_diag >= REDRAW_DIAG_EVERY_S:
                diag = knob.diag()
                last_diag = clock()
                samples.append({k: diag.get(k) for k in REDRAW_FIELDS})
            knob.pump(0.01)
            sleep(0)
    except Exception as exc:
        problems.append(f"the redraw check could not run ({type(exc).__name__}: {exc})")
    finally:
        if knob is not None:
            knob.release_quietly()
            errors = [str(e) for _, e in getattr(knob, "errors", [])]
            knob.close()
    if not problems:
        problems = redraw_problems(samples)
    if errors:
        problems.append(f"the knob answered errors during the redraw check: {'; '.join(errors[:3])}")
    return {"controlId": REDRAW_CONTROL_ID, "seconds": REDRAW_SECONDS, "samples": samples, "claimErrors": errors,
            "problems": problems, "passed": not problems}
