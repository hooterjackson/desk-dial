# Quiet Listening design QA

The first sections record the cc2 implementation and its preserved evidence.
The cc3 text draft and final cc3 icon correction below record subsequent user
feedback. The final icon section is the current design; earlier sections are history.

Selected target: option 3, the third displayed Product Design image.
Source visual truth: `previews/quiet-listening/selected-reference.png` (1254x1254).
Implementation: `previews/quiet-listening/volume.png`, the actual firmware
cc_display.cpp rendered with the same LVGL9 library at native 240x240 RGB565.
CSS dimensions/density: not applicable to this embedded display.

Comparison: `previews/quiet-listening/quiet-reference-comparison.png`. The source
LCD crop (x300,y171,655x655) is normalized to240x240 and circularly masked beside
the unscaled implementation. Both show Den, Colombina, Mari Froes,54%, and the
same four actions. The illustrative enclosure is outside implementation scope.
The native comparison makes the number and footer readable without further zoom.

## Findings and fixes

- P2: inherited crowded/clipped footer. All twelve legends were measured using
  the actual font. New47px columns fit Browse45px, Cancel/Switch41px. Neutral
  uses the short disabled label Skip. Verified in typography-checks.json and
  the final four-control sheet.
- P2: missing glyph in the context separator. Replaced it with ASCII | and
  regenerated the sheet. Common Latin accents and punctuation are normalized
  only in the copied device frame. Original Unicode remains in the companion
  and playback data. Unsupported remaining glyphs use ?. Native normalized
  examples are in the final all-state sheet; full Unicode remains a limitation.
- P2: obsolete connection notices hid the ring after recovery. Matching ready
  events and Sonos refreshes now clear only obsolete connection notices, while
  preserving playback errors. Regression passed.
- P2: rotating during a pending skip or Play hid its progress. Activity now
  follows the outstanding request's view identity, independent of status text.
  A suspended audio operation cannot animate Windows. Regression passed.
- P2: provider-offline state extinguished available navigation. The ring goes
  dark but enabled navigation retains its role lights. Actual host lease expiry
  still restores native controls through the unchanged lifecycle.

## Required fidelity surfaces

- Typography: real installed Montserrat12/14/22/32. Fixed22px titles wrap to two
  lines;100% fits32px in104px. Generated font weight is approximate, so using the
  real font is an accepted implementation constraint. Content-first hierarchy
  matches the selected reference.
- Spacing/layout: true black, quiet target, one title area, compact volume row,
  four aligned legends. The reference divider is present for one-line volume
  titles and hidden for two lines to preserve metadata space. All16 native
  samples contain zero pixels outside the circular aperture.
- Colors: warm whiteF0EEE7, secondaryA19E94, muted555650; redCE7474 and green66C991
  retain action semantics. Native RGB565 quantization is expected.
- Images/assets: the chosen LCD contains no artwork or custom icons. Text,
  separators, state dots, and LED values are native UI primitives. The concept
  housing is not an asset sent to the device.
- Copy/content: normal instructions stay in the companion. Pending volume shows
  confirmed level; loading, unavailable, failure, and offline state replace
  secondary metadata without covering the controlled value or button legends.

## Evidence and comparison history

`quiet-four-controls.png` and `quiet-all-states.png` in the same preview directory
show all modes and16 normal/long-title/100%/pending/loading/unavailable/More/error/
closed-window/normalized-text states. `geometry-checks.json` and
`typography-checks.json` record raster bounds and font metrics. The first pass
identified a missing divider and the separator glyph; both were fixed, followed
by fresh source/native comparison and all-state captures inspected together.
No actionable P0/P1/P2 differences remain in the final comparison.

Companion canvas: `previews/quiet-listening.png`. Its eight hidden Tk state checks,
60LED count, text bounds, and overlap checks passed. It uses SegoeUI; native LVGL
captures are authoritative for LCD type. Firmware lighting passed476 assertions;
actual RGB fixtures are `previews/quiet-listening/light-pixels.json`. Preview LED
display encoding illustrates relative intensity, not calibrated physical light.

Implementation checklist: native layout, four-mode presentation, semantic lights,
compact exception states, display-only text fallback, companion preview, regression
tests, and exact native visual comparison complete.

P3 / physical follow-up: real LED brightness, viewing angle, and preference need
desk-side inspection after installation. Source renders and ready acknowledgments
do not establish physical acceptance. Full live feature acceptance stays separate.

cc2 software design result: passed. Subsequent physical feedback identified
reversed ring travel and insufficient footer clearance; both are addressed by
the cc3 correction below.

## cc3: ring direction and viewing-angle clearance

Historical text draft: its unequal footer spacing was subsequently rejected.
The final icon correction below supersedes this layout before installation.

Status: software geometry PASS; physical viewing-angle and ring-direction
acceptance pending. This report does not establish installation.

The user observed ring animation moving opposite to shaft rotation, and outer
footer labels becoming occluded when viewed at an angle. Staying inside the
nominal 120 px circular aperture was therefore insufficient. This correction
preserves the selected design while reserving a larger margin from the bezel.

- All four legends move from y184 to y160, a 24 px upward shift, and increase
  from Montserrat12 to Montserrat14. They remain a single horizontal row in
  physical button order. Columns start at x24, x74, x134, x167, with widths
  50, 54, 32, 52 px. Real LVGL advances are Browse54, Cancel49, Switch50, and
  Win30 px, so complete labels fit without a smaller type size.
- Content reflows upward to retain separation: title y60 for one line or y52
  for two; subtitle y96/y108; context y140; volume label y133 and value y123;
  divider y119. Tracks uses title y63, dots y107, and position labels y119.
- Across 16 native 240x240 RGB565 states, the maximum lit footer radius falls
  from 117.86 to 109.86 px. Minimum radial bezel clearance increases from
  2.14 to 10.14 px. Volume improves from 3.55 to 12.38 px. No rendered pixels
  fall outside the circular aperture. Long titles, 100%, pending, loading,
  unavailable, More, transport, error, offline, and closed-window states were
  visually inspected after the change.
- Ring logical positions are reflected into the physical wiring direction
  before the existing mounting rotation: `(60 - logicalIndex + orientation * 45)
  % 60`, with the logical index normalized to 0..59. The correction applies
  to volume, browser cursors, transport clusters, and loading travel. It keeps
  the top anchor, brightness, colors, and fades, and does not change input,
  haptic profiles, control bounds, or button roles. The lighting harness passes
  7,227 assertions; this establishes software mapping, not physical direction.

Native evidence is isolated in `previews/cc3/native/`:

- `cc2-cc3-comparison.png`: unscaled before/after Volume and Windows renders.
- `quiet-four-controls.png` and `quiet-all-states.png`: four controls and all
  16 scenarios, using the actual firmware renderer and LVGL font rasterizer.
- `typography-checks.json`, `geometry-checks.json`, and
  `cc2-cc3-clearance.json`: font advances, lit-pixel bounds, and direct cc2/cc3
  clearance measurements. The cc2 evidence remains in `previews/quiet-listening/`.

Required physical follow-up: confirm that clockwise/counterclockwise turns and
the ring agree on the actual kit, and that Back/Tracks plus Cancel/Switch remain
readable at the user's normal desk viewing angle. The raster measurements cannot
model bezel occlusion or establish the user's acceptance of the installed result.

## Final cc3 icon footer and conditional white lights

The user found the text draft's footer spacing unattractive and requested red
close and green confirmation icons. All four centers now sit at x42, 94, 146,
198, equally spaced by 52px. Browse/Home and Win retain readable 14px text at
y155; a 16px bundled LVGL CLOSE icon replaces Back/Cancel, and a bundled OK
icon replaces confirmation labels. Both icon labels sit at y153 to align their
actual glyphs with the text. Volume retains Tracks as text so it clearly opens
a control rather than immediately confirming playback.

The symbols come from the installed Montserrat symbol set: CLOSE's actual ink
is 11x12px and OK's is 16x12px. The companion receives native glyph PNGs exported
through the LVGL renderer, avoiding fallback fonts or platform-dependent emoji.
The existing context row starts with the operation: `Play | Den | 1/10`,
`Switch | 2/7`, or `More | Den | Page 1`. Placing the verb first retains its
meaning even if a longer target is truncated. No extra information row was added.

Final geometry: title y60/y52 and subtitle y96/y108 remain; context moves to
y137, volume label to y130, and volume value to y120. Text legends at y155 are
29px above the original cc2 row. All 16 native states were visually reviewed;
the maximum lit footer radius is 109.83px, leaving at least 10.17px from the
bezel. Selector icon rows have a 96.07px radius, leaving 23.93px. No pixels fall
outside the physical circular aperture. This preserves equal spacing without
crowding the action text against the edge.

White is the default for all four buttons and the ring. Enabled Back/Cancel
uses red; enabled Play/More/Prev/Next/Switch uses green. Tracks remains white,
as do Browse, Home, and Win. Disabled buttons remain subdued neutral. The LCD
uses the same `cc_button_ink` role helper as the LEDs, while the controller's
enabled flag alone determines availability. Error text may use a state color,
but the ring remains white. The corrected ring direction is unchanged.
The final lighting harness passes 7,245 native assertions and 14 native/Python
pixel-fixture comparisons; its focused presentation suite passes 14 tests.

Current native evidence: `previews/cc3-icons/native/`. `footer-comparison.png`
shows the text draft beside the final icon version; `quiet-four-controls.png`
and `quiet-all-states.png` show native controls and all 16 scenarios.
`typography-checks.json`, `icon-raster-metrics.json`, `geometry-checks.json`,
and `footer-clearance.json` record exact font, icon, and lit-pixel measurements.
Previous cc2 and cc3 text evidence remains in its original directories.

Final icon revision software geometry: PASS. Installation and physical
viewing-angle/appearance acceptance are separate; this report makes no
installation claim. Haptic profiles, controller behavior, and button actions
are unchanged by this presentation correction.

The final companion preview also passes 15 hidden Tk cases for legible action
labels, text/icon separation, and unchanged physical button positions. Its eight
exports and `companion-four-controls.png` are in `previews/cc3-icons/`; the icons
use the exact native glyph rasters. The full Python suite passes 205 tests.

Final result: passed (software visual QA). The cc3 firmware is now installed,
with full-flash verification and four-mode protocol checks passing. Physical
viewing-angle and ring-direction acceptance remain pending.
