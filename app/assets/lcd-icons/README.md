These PNGs are exports of the device's actual LVGL 9.0.0 symbol renderer.

- Font: `lv_font_montserrat_16`, 16px, 4bpp.
- Symbol source recorded in that font's generated header:
  `FontAwesome5-Solid+Brands+Regular.woff`.
- Close: `LV_SYMBOL_CLOSE`, U+F00D.
- Confirm: `LV_SYMBOL_OK`, U+F00C.
- Source font data: vendor LVGL `src/font/lv_font_montserrat_16.c`.

The 24×24 transparent canvases were exported through the actual LVGL renderer,
not drawn or approximated by hand. Four palette variants preserve native
antialiasing: warm white, red, green, and muted white. The companion scales them
by19/12 to match its380px preview of the240px LCD. Place each canvas at its
button center minus12px horizontally and y153 vertically in native coordinates;
the canvas is not vertically centered on the footer baseline.

Original controller action names remain unchanged and appear in the exported
SVG accessibility labels. These files only change visual presentation.
