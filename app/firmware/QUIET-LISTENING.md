# Quiet Listening — firmware 1.0.0-cc2

Implements selected Product Design option 3 across Volume, Recently Added, Tracks,
and Windows. The LCD prioritizes the current song/selection, uses a compact volume
readout, and keeps four readable legends aligned with the physical button row.
The ring uses warm-white volume fill, selector positions, or three transport
clusters. Disabled actions are dim; available navigation remains lit if Sonos
goes offline. Haptics and all installed profile parameters are unchanged.

Read [VISUAL-DESIGN.md](VISUAL-DESIGN.md) and [design QA](../design-qa.md).
The source and image are `nanod-control-center-1.0.0-cc2-source.zip` and
`nanod-control-center-1.0.0-cc2.bin`; hashes are in `manifest-1.0.0-cc2.json`.
Build with the same pinned PlatformIO environment described in BUILD.md.
This revision requires no new dependencies.

The host protocol retains controlCenter=1 and adds presentation=2. Frames accept
optional title, subtitle, counter, and activity fields. Activity is one of idle,
loading, pending, error, unavailable, offline. These fields only affect display
and LEDs; they never reload the profile or motor state. Old frame senders remain
accepted. Use the updated companion for the complete layout and status behavior.

To try it, launch `../Launch.cmd` and connect the knob. This is the simulator.
Browse opens the sample library; Tracks opens the three-position selector; Win
opens the simulated window list. The same controller drives the live adapters.
For real Den/Windows control, disconnect the knob before changing environment
to LIVE · DEN, then reconnect. Real Play replaces the Sonos queue.

The packaged cc1 image and original stock firmware remain available for recovery.
Before cc2 installation, the entire current flash is saved as
`../backups/nanod-cc1-before-cc2-full.bin`, with the current application slot in
`nanod-cc1-before-cc2-active-app.bin`. Preparation and installation evidence is
recorded in `../diagnostics/quiet-update-preparation.json` and
`../diagnostics/quiet-update-installation.json`. Application-only recovery follows
RECOVERY.md, substituting this newer application backup when returning to cc1.
Do not write an entire flash image merely to roll back the interface.

Physical brightness and viewing-angle acceptance still need a desk-side check.
The installed font is ASCII-only: common accents/punctuation are normalized on
the device, and unsupported glyphs use ?. Original Unicode and full error text
remain in the companion. Full live integration acceptance stays in ACCEPTANCE.md.

## cc3 correction candidate

Historical text draft, superseded by the final icon footer below before installation.

The cc2 information and evidence above remain the installation history. The cc3
source correction responds to the user's desk-side report: ring travel was
opposite to knob rotation, and the outer bottom labels were hidden by the bezel
at an angle. This section records software validation; it does not establish
that cc3 has been installed or accepted on the hardware.

All four footer legends move 24px upward, from y184 to y160, and grow from 12px
to 14px. Unequal columns at x24/74/134/167 with widths 50/54/32/52 preserve complete
labels. The real LVGL font measures Browse 54px, Cancel 49px, Switch 50px, Win 30px.
Titles, metadata, and the volume row move slightly upward to maintain separation.

The worst rendered footer radius decreases from 117.86px to 109.86px, leaving at
least 10.14px of radial bezel clearance instead of 2.14px. Volume clearance grows
from 3.55px to 12.38px. All 16 native states pass the circular bounds check and were
visually inspected. `../previews/cc3/native/cc2-cc3-comparison.png` contains the
native before/after comparison; the same directory contains all-state renders
and typography/clearance reports. The original cc2 previews are preserved.

The LED renderer reverses logical ring indices before applying the existing
orientation offset, correcting volume fill, list position, transport, and loading
travel through a single address mapping. The lighting harness passes 7,227
assertions. Haptic profiles, control positions, button roles, brightness, and
normal effect timing remain unchanged.

Software geometry and mapping: PASS. Physical acceptance is still pending for
direction agreement and legibility at the user's normal viewing angle. Native
renders cannot prove either behavior on the installed kit.

## Final cc3 icon footer

The user rejected the text draft's uneven spacing and requested close/confirm
icons. Four equal centers at x42/94/146/198 now form a 52px pitch. Browse/Home
and Win use 14px text at y155. The installed LVGL CLOSE and OK symbols use 16px
type at y153 for aligned glyphs. Volume keeps Tracks as text because it opens
the selector. Action cues start with Play, More, or Switch in the existing
context row, keeping their meaning visible on long titles or room names.

White is the default for the ring and all buttons. Red marks an enabled
Back/Cancel action; green marks an enabled Play/More/Prev/Next/Switch confirmation.
Home, Browse, Win, and Tracks remain white. Disabled affordances are subdued
neutral. LCD and LED role colors share one helper and the controller's enabled
flag remains authoritative. The ring direction correction is unchanged.
Final light validation passes 7,245 native assertions and 14 native/Python
pixel-fixture comparisons.

The final footer has at least 10.17px radial bezel clearance in all 16 native
states; selector icon rows leave 23.93px. All states passed the circular bounds
check and visual review. Native evidence, exported glyphs, and before/after
comparison are in `../previews/cc3-icons/native/`. The previous text draft is
retained as history in `../previews/cc3/native/` and its firmware draft package.

This section records source and software validation, not installation. Physical
viewing-angle and appearance acceptance still require checking the actual knob.
