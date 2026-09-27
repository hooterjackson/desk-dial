# Quiet Listening — selected Product Design option 3

The user selected the third displayed concept on 22 September 2026. The source
is ../previews/quiet-listening/selected-reference.png; actual native renders and
the normalized comparison are alongside it. See ../design-qa.md for evidence.

The first physical pass confirmed the navigation, but the user rejected both
the crowded LCD and the LED treatment. This pass treats the kit as a desk audio
instrument: one clear subject on black glass, with lighting that describes the
rotary control.

The LCD uses black #000000, warm white #F0EEE7, and readable grey #A19E94.
White is the default for the ring and all four buttons. Red #CE7474 appears only
when Back/Cancel is enabled; green #66C991 appears only for an enabled confirmation
(Play, More, Prev, Next, Switch). Browse, Home, Win, and Tracks remain white;
disabled affordances are subdued neutral. The existing Montserrat fonts keep
the rendering reproducible on the 240px display: 32px volume, 22px selected
titles, 14px metadata and text legends, 16px bundled icons, and 12px status.
Titles keep their type size and use two-line ellipsis.

Volume gives the song and artist priority, with a compact VOLUME / value row. Library and Windows
selectors get a generous title block and a compact position counter. Tracks
gets an explicit three-position diagram. Routine instructions move to the
companion; the LCD status area is reserved for actionable state such as pending,
loading, unavailable, and errors. The four short button legends remain visible
and aligned with the four physical buttons below the dial.

The ring uses a quiet warm-white proportional volume arc, discrete browser marks with a
three-pixel cursor, or three transport clusters. Empty segments stay dark.
No idle animation. Brief response fades, a restrained loading cue, and a pending
cursor pulse describe changes in state. Button brightness is treated separately
from ring brightness, respecting the device's brightness ceiling.

The final cc3 icon footer uses equal centers at x42, 94, 146, 198: a consistent
52px pitch. Browse/Home and Win remain 14px text at y155. Back/Cancel uses the
bundled LVGL CLOSE icon, and confirmations use the bundled OK icon, both at
16px and y153 for optical alignment. These are the library's actual symbols,
not an ASCII X, emoji, or a system-font approximation. Volume retains the word
Tracks because that button opens a selector. Each cell has 56px text capacity;
Browse measures 54px and Win 30px with the real font. The action context starts
with Play, More, or Switch so truncation cannot hide the operation. All four
affordances stay on one horizontal row. There is no second on-screen
volume gauge competing with the physical ring. No artwork or new interaction
paradigm is introduced; all installed haptic presets and button roles stay intact.

Sixteen native LVGL states at 240×240 pass visual and geometry checks. Common
Latin accents and punctuation are normalized only in the device frame to match
the stock font; unsupported remaining characters use ?. Original Unicode stays
in the companion and provider data. This does not alter playback identities.
Physical LED brightness and perceived appearance still need a desk-side check.

The cc2 layout and native evidence remain in ../previews/quiet-listening/.
Its 12px footer in 47px columns was nominally inside the circle, but physical
viewing revealed bezel occlusion. The intermediate cc3 text draft moved the
14px row to y160 and used unequal columns, increasing minimum clearance from
2.14px to 10.14px. That evidence remains in ../previews/cc3/native/; the user
rejected its spacing before installation.

The final icon footer moves text to y155, 29px above cc2, with matching icons
at y153. Its worst footer radius is 109.83px, leaving 10.17px radial clearance;
selector icons leave 23.93px. All 16 native states pass the circular bounds
check and were visually inspected. Current evidence is in
../previews/cc3-icons/native/. Software geometry passes; actual viewing-angle
acceptance remains a physical check. This document does not establish installation.

The user also observed reversed ring travel. The cc3 LED address mapping reflects
logical clockwise positions before retaining the existing mounting rotation:
`(60 - logicalIndex + orientation * 45) % 60`, with logicalIndex normalized
to 0..59. This corrects every host-controlled ring presentation through one
mapping; it leaves the top anchor, brightness, effects, input direction, and
haptics unchanged. The initial direction correction passed 7,227 software
lighting assertions. Subsequent white-default behavior uses the same conditional
role helper for the LCD and LEDs, with the controller's enabled flag authoritative.
The final white-default renderer passes 7,245 native assertions and 14
native/Python pixel-fixture comparisons.
Clockwise/counterclockwise agreement on the physical kit still needs confirmation.
