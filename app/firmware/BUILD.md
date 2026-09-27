# Build and recovery notes - cc4 installed

cc4 adds home Play/Pause display icons. A fresh4MBbackup and complete post-write
verification passed; only application sectors changed. Ten saved profiles and
calibration/settings partitions are preserved. Four control entries, presentation
updates, and lease recovery pass. Physical Play/Pause acceptance remains pending.
See [cc4 build notes](BUILD-cc4.md) and ../diagnostics/cc4-installation.json.

## Previous cc3 build record

## Installed cc3 update

The current application is nanod-control-center-1.0.0-cc3.bin, 927024 bytes.
Flash use is 926661 bytes; RAM 204324 bytes. Its source archive and hashes are
recorded in manifest.json. The current 4MB backup matched the device before
writing; only application sectors 0x10000 through 0xF2FFF changed. The full expected
post-write image verified before reboot, and all ten saved profiles were preserved.
See ../diagnostics/cc3-installation.json. Four device modes and lease recovery
pass. Physical visual/behavioral acceptance remains separate.

## Installed cc2 history

The current Quiet Listening package is firmware1.0.0-cc2, installed on22September2026.
Use nanod-control-center-1.0.0-cc2-source.zip to rebuild the current interface;
the matching application binary and source hashes are in manifest.json.
The original cc1 artifacts and [build record](BUILD-cc1.md) are preserved.

Extract the source archive and run from its NanoD_RatchetH1 directory:

    python -m platformio run -e nanofoc_d

PlatformIO Core6.2.0 and the existing pinned dependencies are used. On Windows,
a short PLATFORMIO_CORE_DIR avoids the toolchain command-length limit.
Building does not install firmware. Generic PlatformIO upload is not the
application-only installation procedure used here.

The actual application partition is0x10000, size0x140000. The926512-byte image
changed only application sectors0x10000 through0xF2FFF. A fresh4MB backup and
complete expected-image verification passed before reboot. Saved profiles and
calibration/settings partitions remain intact. Detailed hashes and evidence are
in ../diagnostics/quiet-update-installation.json and manifest.json.

See [Quiet Listening release notes](QUIET-LISTENING.md),
[visual design](VISUAL-DESIGN.md), and [recovery procedure](RECOVERY.md).
The protocol remains controlCenter=1 and advertises presentation=2; optional
presentation fields are described in the release notes. No motor gains, force
curves, saved profiles, calibration, or detent counts changed from cc1.

Software checks, real-device readiness, independent frame updates and lease
recovery pass. Physical appearance and full live-feature acceptance remain
tracked in ../ACCEPTANCE.md.
