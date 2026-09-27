# Build and recovery notes — installed, acceptance pending

This package contains the built application image and complete vendor source plus
the targeted control-center extension. It contains no installed-device settings,
profile inventory, account credentials, toolchain cache, `.pio`, or Git history.
The manifest records source/image hashes, the upstream commit, pinned direct
dependencies, and the tool/package/library versions that produced this build.

The supplied application was installed on this kit on 22 September 2026. The
original full firmware is backed up, and complete flash verification confirmed
that only the intended application sectors changed. Physical acceptance remains
pending; see `../ACCEPTANCE.md` and [RECOVERY.md](RECOVERY.md).

Extract `nanod-control-center-1.0.0-cc1-source.zip`, install PlatformIO Core 6.2.0
in a Python virtual environment, and run the following from the extracted source
directory. Dependency downloads require internet access. On Windows use a short
PlatformIO core path if GCC reports an internal CreateProcess/command-length error.

```powershell
python -m platformio run -e nanofoc_d
```

This is a build command only. The archive's declared partition layout was checked
against this kit's actual partition table before installation. Generic PlatformIO
upload commands can also replace bootloader/partition images and are not the
application-only procedure used here. Exact binary hashes can vary with build
paths/timestamps; the supplied image hash is in `manifest.json`.

Read the existing-profile preservation, runtime contract, and recovery notes below.

# Control-center extension (1.0.0-cc1)

This build retains the vendor's regular-detent motor implementation and copies an
existing named profile into runtime-only state. Only logical bounds, initial index,
and the detent coordinate origin change. It never saves a profile or calibration.

Build with PlatformIO, environment `nanofoc_d`. Dependencies are pinned to the
base versions declared by this vendor checkout. On Windows, a short
`PLATFORMIO_CORE_DIR` avoids GCC's internal command-line length limit.

```powershell
$env:PLATFORMIO_CORE_DIR='<pio-core>'
& '<repo>\tools\nanod-pio-venv\Scripts\python.exe' -m platformio run -d '<repo>\firmware'
```

The `pio-knob` junction points at the task's `work/platformio-core` directory.
Build output is `.pio/build/nanofoc_d/firmware.bin`. Building does not flash.

Before flashing, retain the original full flash image, partition table, complete
installed-profile inventory, and filtered settings backup. The application image
must be written only to the verified application partition; do not erase flash,
upload the filesystem, replace the partition table, or write calibration/NVS.
Rollback means restoring the original application bytes at that same verified
offset. Never infer that offset from a generic ESP32 example.

## Runtime protocol

USB CDC is newline-delimited JSON at 115200. Normal DTR/RTS assertion was required
to receive replies from the connected native-USB kit. One host owns the port.

- `{"capabilities":"?"}` returns `capabilities.controlCenter=1`, a 2000 ms lease,
  host-frame/tagged-input/runtime-bounds support, and the Windows F24 key.
- `control` contains positive monotonically increasing id, an existing profile
  name, min=0, max, position, raw windowsButton index 0..3, and a complete frame.
  Unknown names and unsupported progressive/non-regular profiles are rejected.
  Optional buttonOrder is a permutation of 0..3 describing physical left-to-right
  buttons as raw indices. It defaults to identity. Frame legends remain in
  physical order; LED pairs are remapped, while serial button events remain raw.
  Optional windowsHidEnabled is a boolean, default true. Simulated desktop
  sessions set it false to suppress F24 while retaining tagged serial buttons.
- After motor and both renderers agree, `{"ready":id,"p":position}` acknowledges
  readiness. Physical motion during setup is rebased, not emitted as a turn.
- Position events are absolute `{"id":id,"p":position}`. Button events retain
  kd/ku/ks and add id. Old or unready events must not drive host actions.
- `frame` contains the active id plus all presentation fields. It changes only
  presentation and renews the lease. Send a current frame at least every 500 ms.
- `{"release":true}` restores the pre-session runtime profile and native input
  behavior, then returns `{"released":true}`. After two seconds without a valid
  frame/control, the FOC-side lease requests restoration independently of COM;
  the reply additionally carries `reason:"lease-expired"`.
  Once native control has been restored, the display shows "HOST DISCONNECTED",
  "Native controls active", and "Reconnect companion", with no host button
  legends. This notice persists until a valid new control or explicit release;
  it does not claim the device or prevent reconnecting. Intentional release
  restores the original native screen without a timeout notice.

Frame fields: mode,target,value,detail,status strings; four buttons with label,
enabled,color(integer RGB); ring with style off/level/selection/transport,
value 0..100, index, count. Strings are bounded and truncated only at valid UTF-8
boundaries. Use concise button labels; the four legends follow physical left-to-
right indices once that mapping has been calibrated. Unsupported font glyphs are
not a claim of full Unicode typography.

Native MIDI and configured button/knob actions are suppressed during ownership.
When windowsHidEnabled is true, the configured Windows button emits one HID F24
pulse and a tagged button event;
the host must deduplicate those two entry paths. Ordinary button colors and
profile mappings are retained for release. Input events are not replayed after a
lease loss or reconnect. No LLM or network service participates in force control.

## Validation boundaries

The Python bridge tests exercise read-only inventory, complete profile backups,
secret-filtered settings, unknown-profile rejection, capability fallback, stale
IDs, initial baselines, rapid/reversed deltas, press deduplication, independent
frame heartbeats, release, and UTF-8 boundaries. Firmware build success establishes
compilation only. Physical feel, orientation, LED order, focus handoff, lease
restoration, and the rendered 240px layout require testing on the actual device.

The existing force curve and motor gains are retained. A narrowly scoped boundary
bookkeeping fix records which endpoint was hit before stepping inward; compile-
time regressions cover one/two/three-position ranges and nonzero native bounds.
Boundary recovery yields back to the main loop within 2 ms so it cannot starve the
lease. Readiness follows LED transmission and display refresh on every control
change. Native idle LED writes now respect the separate 60/8-element arrays.
The native ring renderer also handles a single-position range during release
without dividing by zero. The four legend columns are 45 px wide at Montserrat 12;
the shipped font metrics fit Browse (45 px), Cancel (41 px), Switch (41 px), and
Win (24 px).

## Current hardware status

Installed on 22 September 2026. Application USB COM8 returned after installation,
and the post-install inventory reports `controlCenter=1` and all ten profiles.
Before/after profile JSON is identical, filtered settings differ only in
`firmwareVersion`, and the native GRASSY HOPPER selection was restored.
All four profile/control entries acknowledged readiness through the actual
DeviceBridge; separate presentation updates ran for one second per control
without reported errors. No Sonos commands or Windows HID actions were sent.
The vendor 1200-bps touch followed by port rediscovery successfully entered the
bootloader as COM9; the actual application offset is `0x10000`, size `0x140000`.

The original 4MB image was backed up and checked against the device. Only the
922,384-byte packaged application was written; its affected sectors end at
`0xF1FFF`. The entire 4MB then matched the expected image assembled from the
original plus that application and its final erased-sector tail. All flash bytes
outside those sectors were preserved by installation. Read [RECOVERY.md](RECOVERY.md)
for exact backup identities and application-only rollback.

The flash operations used a separate `tools/nanod-flash-venv` with esptool 4.12.0
and its newer RAM stub, which resolved very slow native-USB reads with 4.5.1.
The pinned PlatformIO build environment and its esptool 4.5.1 package were not
upgraded. A compiled image, boot, and successful capability query do not establish
physical feel, button order, display legibility, or end-to-end feature acceptance.
The same boundary applies to readiness and presentation-update acknowledgments:
they verify protocol behavior, not human observation of the display or motor.
