# Implementation and acceptance record

Date: 22 September 2026. **Firmware installed and partly verified; not hardware-complete.**

## Current installation: standalone app and cc3 firmware

The independent executable is installed under LocalAppData/Programs and launched
by Windows Task Scheduler, with a sign-in trigger and Start-menu shortcut. It
bundles Python and Tk, stays in the tray when closed, prevents duplicate instances,
and reconnects using fresh controller and Sonos state. The frozen UI smoke test,
212 Python tests, actual scheduler launch, live knob/Den connection, and duplicate
launch handoff pass. An actual reboot and packaged-app cable reconnection have not
yet been observed. See DESKTOP.md.

Firmware cc3 is installed. Its full pre-write backup matched the device; only
application sectors were written, and the entire expected 4MB image verified
before reboot. All ten profiles and settings except firmwareVersion are unchanged.
Four device modes, independent presentation updates, lease expiry, reentry, and
explicit release pass. Evidence: diagnostics/cc3-installation.json.

The final display has equal 52px spacing, bundled cancel/confirm symbols, and 14px
text raised 29px. Native minimum bezel clearance is 10.17px. The physical LED address
mapping is reversed to match rotation. White is the LED default, with red/green
only for available cancel/confirm actions. 7,245 native LED assertions and 14 pixel
comparisons pass. Viewing angle, physical direction/color, and complete live
music/Windows acceptance still require hands-on confirmation.

## Delivered

- Shared four-control interaction controller, complete simulator, and Python/Tk
  companion with the correct four-button row below the round display.
- Real Sonos, MusicKit, and Windows adapters, encrypted credentials and queue
  recovery, guided physical button-order setup, and a single serial owner.
- Minimal firmware extension, compiled application image, full source archive,
  hashes, pinned build dependencies, and recovery instructions in `firmware/`.
- Existing profile mappings: BINARIS BEER for volume; MIDI SKIPPER for library and
  windows; MIDI CLACK JONES for the three-position transport control.

## Evidence

Final regression run: **191 tests passed**, followed by a successful hidden Tk
smoke test and fresh exports of all four actual canvas layouts. The firmware
image and source archive match their manifest hashes; the ZIP passes CRC checks
and all 91 archived source files match their recorded hashes and sizes.

| Area | What was actually verified | Remaining boundary |
|---|---|---|
| Controller and integrations | Automated navigation, race, error, adapter, serial, and Win32-fake tests pass | Mocked tests do not establish physical behavior |
| Tk companion | Hidden simulator smoke test passed; hidden live app read Den and enumerated 12 eligible windows, without USB or focus actions | Visible native overlay/focus acceptance remains manual |
| Visual layout | Actual Tk canvas exports inspected for all four screens, correct button geometry and stable text size | Exports do not prove the kit's LCD rendering |
| Sonos identity | Actual Den UID and group confirmed from `.50`; stereo pair/Sub resolved as one visible room | Regroup races tested with fakes; live regrouping was not performed |
| Sonos volume | Same-level write and confirmed readback at 54 on actual Den | No physical rotary adjustment has been tested |
| MusicKit | Dedicated app/key configured by the user; browser authorization complete; protected local storage verified | Future token expiry requires reconnecting in Setup |
| Apple library | Live ten-item Recently Added page, continuation, and exact saved-item/catalog resolution verified | Not every library content type/account entitlement can be assumed playable |
| Apple-to-Sonos route | one single-track album staged and verified PLAYING while muted, with playback position advancing by one second | Full production queue replacement and all item types still need live acceptance |
| Quiet-test cleanup | Original one-item queue and stopped source/position restored; original mute restored; volume unchanged at 54 | Queue revision necessarily advanced through append/remove operations |
| Transport | Strict preceding-track behavior, capability checks, repeat bounds and stale track guards tested with fakes | Live Previous/Next and repeated physical confirmation remain untested |
| Windows | 34 adapter tests plus controller/modal tests; real read-only enumeration found distinct eligible window identities | Actual DWM display, foreground switching, multiple monitors and physical F24 remain untested |
| Knob inventory and preservation | Post-install COM8 inventory reports host-control capability; all ten profile JSON values match the original exactly; filtered settings differ only in firmwareVersion; GRASSY HOPPER restored as the native selection | Ring direction, LED-role alignment and haptic feel need physical verification |
| Physical button capture and calibration display | All four physical buttons captured left to right as raw indices `0, 1, 2, 3`; verified mapping saved locally; user reported calibration display "Upright and readable" | This verifies the calibration screen only, not every control's text, ring or button LED alignment, or haptics |
| Basic physical simulator volume check | User replied "did it" after instructions to connect the knob in Simulator and turn three detents right, then three left, expecting one volume point per detent, ring feedback and no sudden motor pull; no issue reported | User-reported completion only; no recorded position trace, rapid-motion accuracy, full haptic acceptance or live Sonos adjustment established |
| Firmware installation | Original full 4MB backup and device digest verified; actual partition table and OTA selection checked; candidate written only at app0 `0x10000`; complete flash matches expected post-install image; application re-enumerates on COM8 | Boot and capability are verified; the complete four-feature physical experience remains open |
| Real device control entry | All four controls acknowledged ready through DeviceBridge at their requested positions/bounds; separate presentation updates sustained each for one second without errors; no Sonos or HID actions sent | Acknowledgments do not prove felt detents, physical motion fidelity, readable pixels, or visible LED alignment |
| Device host lease | Firmware acknowledged lease expiry about 1.97 seconds after readiness with heartbeats withheld; a fresh entry and explicit release both succeeded | The disconnected notice and native feel still require visual/tactile confirmation |

The initial physical button-order capture received no taps during its five-minute
window, saved no mapping, and restored native control. A subsequent capture with
the user at the knob received all four button presses in physical left-to-right
order: `0, 1, 2, 3`. The capture completed and `local/settings.json` now saves that
order with `button_order_verified: true`. The user confirmed the calibration
display was "Upright and readable". Full control-screen readability, ring direction,
button LED-role alignment and haptic feel remain open.
Machine-observable results are in `diagnostics/device-entry-checks.json` and
`diagnostics/device-lease-check.json`.

The user subsequently reported completing the basic simulator volume exercise
(three detents right, then three left) with "did it" and no issue reported.
This is a user-reported check, not a measured motion trace. Hands-on checks of
Recently Added, Tracks and Windows remain pending, along with live volume and
the broader rotary, display and LED acceptance below.

The quiet probe initially aborted before playback because mute had not propagated
at the immediate readback. It restored and verified the original state. A bounded
confirmation window was added, without repeating writes. The subsequent guarded
attempt passed and restored the original state. Details are in
`diagnostics/quiet-sonos-probe.json`; recovery data is encrypted in `local/`.

## Installation and preservation evidence

The earlier USB blocker is resolved. After the user reconnected USB, the vendor's
1200-bps touch procedure changed application COM8 (VID `239A`, PID `8010`) into
bootloader COM9 (VID `303A`, PID `1001`). The identified chip is ESP32-S3 revision
0.1, with 4MB flash and MAC `12:34:56:78:9A:BC`.

The original complete flash was read and independently verified against the
device with `verify_flash`. Its SHA-256 is
`fc131f9366b276cf4bf10cdd8c61d32840f9a61b6ff966a1c323cdf2789d509c`.
The partition table at `0x8000` has a valid checksum and matches the vendor layout.
OTA sequence 1 selects app0 at `0x10000`, size `0x140000`. Both original and
candidate application images have valid checksums/hashes and compatible
ESP32-S3 revision, 4MB/DIO/80MHz headers and ESP-IDF 4.4.6 metadata.

Only the packaged 922,384-byte application was written at `0x10000`. Erase sectors
were confined to `0x10000` through `0xF1FFF`. An expected full-flash image was
constructed from the original, substituting the candidate and the erased tail of
its final sector; the full 4MB device digest matched it before reboot. Expected
image SHA-256:
`cb2343ee22eb31e9e9fa13f1c4d8093c27b1aebb8b9c75204d94d618c7f56081`.
This verifies preservation of all other flash bytes during installation,
including calibration/NVS, saved profiles/filesystem, and the boot metadata.
Subsequent normal firmware operation can update its own saved state.

After reboot, COM8 returned and inventory
`control-center-inventory-20260922T164420Z-ce1e0d80.json` reported the new capability
and all ten profiles. Before/after installed-profile JSON matched exactly; the
only filtered settings difference was `firmwareVersion`. GRASSY HOPPER was
restored as the native selection. These preservation results are recorded in
`diagnostics/install-profile-preservation.json`; installation evidence is in
`diagnostics/firmware-installation.json`. Rollback files and partition hashes are recorded in
`backups/nanod-original-manifest.json`; [firmware/RECOVERY.md](firmware/RECOVERY.md)
provides the concrete application-only recovery procedure. Backup/installation
used an isolated esptool 4.12.0 environment because the old stub read extremely
slowly over native USB. The firmware build toolchain remains unchanged.

The real serial bridge also entered these four controls successfully, receiving
the device readiness acknowledgment before presentation updates. Each was held
for one second with separate frames and no reported error:

| Control | Existing profile | Entry position | Temporary range |
|---|---|---:|---|
| Volume | BINARIS BEER | 28 | 0–100 |
| Recently Added | MIDI SKIPPER | 0 | 0–10 |
| Windows | MIDI SKIPPER | 1 | 0–3 |
| Tracks | MIDI CLACK JONES | 1, Neutral | 0–2 |

These were bounded protocol checks with simulated presentation values. They did
not send speaker commands or Windows HID events. The values above do not claim
current Sonos volume or a real window selection. The later physical button capture
and user confirmation establish the saved button order and readable, upright
calibration display only; the remaining tactile and visual checks are still open.

## Adversarial changes made before hardware installation

- Preserved current haptic entry on a matching local volume acknowledgment.
- Published latest absolute volume intent atomically, coalesced queued turns, and
  enforced the volume limit in the actual I/O lane.
- Invalidated unsent actions on release/disconnect and rejected old-group targets.
- Prevented an old-group failure from erasing a new-group adjustment.
- Split library resolution from Sonos I/O and skipped obsolete queued page work.
- Made Apple continuation pages idempotent across Windows interruption/cancel.
- Separated asynchronous screen identity from hardware control IDs, so commands
  complete correctly during or after a temporary Windows picker.
- Preserved late command errors in a visible companion notice without navigating
  away from the current control.
- Disabled an unresolvable item for its current browsing visit, including when
  Windows temporarily interrupts that screen; authorization failures stay retryable.
- Made physical button/LED mapping apply together on reconnect; calibration
  intercepts the Win hotkey; simulator hardware suppresses HID F24 entirely.
- Fixed inherited two-position boundary recovery and bounded its settling loop.
- Delayed readiness until actual LED transmission and LCD refresh; protected
  single-position ring rendering and native LED array bounds.
- Added an explicit disconnected display after host lease expiry releases control.

## Quiet Listening update and user feedback

The user reported that all four simulator controls worked, then rejected both the
crowded screen and LED treatment. They selected Product Design option3. Firmware
1.0.0-cc2 now implements that design and the companion matches it. All201 Python
tests,476 native lighting assertions,16 exact LVGL screen states, and the design
comparison pass. Fresh before/after whole-flash verification proves only the
application sectors changed. All ten saved profiles are identical; filtered
settings changed only in firmwareVersion. All four entries and presentation
updates acknowledged on hardware; lease expiry, reentry, and release pass.

These results are in diagnostics/quiet-update-installation.json and design-qa.md.
The updated companion is connected in Simulator for desk-side visual inspection.
The user's earlier functional report is not a claim of physical acceptance of
the new LEDs/screen or completed live Sonos/Windows integration tests.

## Physical acceptance still required

1. **Setup/recovery:** USB identity, original full backup, application-only install,
   and preservation verification are complete. Runtime entry acknowledgments
   and native profile restoration are verified.
   Keep the rollback files and finish physical recovery and feel/display checks.
2. **Four buttons:** physical left-to-right raw indices `0, 1, 2, 3` are captured
   and saved. Verify red Back, Browse/Home, Win and green action labels match all
   four RGB button lights in each control.
3. **Rotary fidelity:** the basic simulator volume exercise was reported complete
   by the user without an issue reported. Still verify one crossed detent per
   logical step with recorded evidence; rapid turns and
   reversals preserve distance; mode changes and external rebases cause no phantom
   selection, volume jump or unexpected motor pull.
4. **Volume:** real live adjustments and confirmed readback; external volume and
   grouping changes discard obsolete adjustments and show current scope.
5. **Library:** ten-item pages, explicit More, stable Back selections, whole-item
   Play, exact library membership and visible unavailable/auth/error states.
   Exercise production queue replacement plus an injected partial failure without
   silently destroying external edits.
6. **Tracks:** each green press dispatches one supported Previous/Next; return to
   Neutral; repeat conveniently; held buttons never repeat; Previous never merely
   restarts the current track.
7. **Windows:** frozen preview list, duplicate application names, minimized and
   closed windows, actual thumbnails/fallback, multiple monitors, verified focus,
   Escape/red cancel, Home cancel, repeated Win, and external focus dismissal.
8. **Recovery:** unplug/reconnect device and network during each pending action;
   no replayed gesture; timeout disables host input and restores native behavior;
   late responses do not replace the new screen.
9. **Readability:** inspect physical 240px titles, target scope, pending/confirmed
   status, disabled actions, and the four button legends. Font coverage is limited
   to the shipped LVGL fonts; full Unicode typography is not claimed.

Completion means all four stories work through the physical knob with matching
haptics, display, ring and button feedback. This record deliberately leaves that
completion criterion open.
