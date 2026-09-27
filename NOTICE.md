# Notice and credits

Desk Dial is released under the MIT License (see [LICENSE](LICENSE)), except for
the parts listed below, which keep their own authors and terms.

## Knob firmware: Nano_D++ by katbinaris

The `firmware/` folder is based on the **Nano_D++ / Ratchet_H1 firmware** by
**katbinaris**: <https://github.com/katbinaris/NanoD_RatchetH1>, shipped
release **v1.0.0** (commit `79ca593f228aed353fe5bd427190d19b4d15578d`).
It is used and published here with the author's blessing. The original
portions remain the work of their author; thank you for building a hackable,
open haptic knob.

The history shows the boundary: the commit "firmware: import upstream
NanoD_RatchetH1 v1.0.0" is the unmodified upstream tree. The Desk Dial
control-center changes come after it (the `cc_*` sources, the edits to the
threads, audio and haptic code, and the contracts `ALIVE.md`,
`PRESENTATION_V5.md`, `V5_VOCABULARY.md`, `CONTROL_CENTER.md` and friends).
MIT applies to those changes; for the upstream portions, follow the upstream
author's terms.

Libraries the firmware pulls in at build time (`firmware/platformio.ini`
`lib_deps`: LVGL, FastLED, TFT_eSPI, ArduinoJson, Simple FOC, Adafruit TinyUSB
and others) are not included here and keep their own licences. The vendored
`firmware/lib/XTI2S` audio library is part of the upstream tree.

## Other third-party material

- `app/assets/fonts/`: Archivo and Montserrat, SIL Open Font License 1.1 (the
  `OFL-*.txt` files beside them).
- `app/design-reference/`: design handoffs made for this project. Their sample
  album covers and the app logos in the window-carousel mock-ups belong to
  their respective owners and are used only as test and design fixtures.
- Python dependencies (`app/requirements*.txt`) are installed from PyPI and
  keep their own licences.

## Not affiliated

Desk Dial is a personal project. It is not affiliated with or endorsed by
Apple, Sonos or Microsoft. Apple Music, Sonos and Windows are trademarks of
their owners.
