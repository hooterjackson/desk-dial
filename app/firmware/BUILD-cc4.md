# cc4 home playback affordance - installed

`nanod-control-center-1.0.0-cc4.bin` is 927088 bytes; `manifest-cc4.json` records
its SHA-256, source archive, source hashes, and validation. Installation is recorded by `manifest.json` and
`../diagnostics/cc4-installation.json`: the full4MBexpected image verified before
reboot; ten saved profiles remain identical and only firmwareVersion changed.

This release changes only `src/cc_display.cpp` and the version in `platformio.ini`
relative to the cc3 source manifest. On the volume home screen, a left-button
label of `Play` or `Pause` now renders the bundled transport icon. Back/Cancel
retain the close icon. The action stays recognizable when temporarily disabled.
There are no motor, haptic profile, calibration, LED renderer, or protocol changes.

Build with the existing PlatformIO environment and documented short core path:

```powershell
$env:PLATFORMIO_CORE_DIR = '<pio-core>'
& '.\tools\nanod-pio-venv\Scripts\python.exe' -m platformio run -d '.\firmware'
```

RAM use is 204324 bytes; application flash use is 926729 bytes. Build output is
`firmware/.pio/build/nanofoc_d/firmware.bin`. Building does not flash.
Read [RECOVERY.md](RECOVERY.md) before an application-only installation; use a fresh
device backup and verify the current partition layout and identity first.

The actual LVGL renderer produced four new home playback states under
`harness/cc4-play-pause`: playing (Pause action), paused (Play action),
pause pending, and play unavailable/offline. All 32 existing old/product reference
rasters remain byte-identical. The four new states have no aperture clipping and
retain at least 10.17 pixels of radial footer clearance. Physical viewing-angle
acceptance remains separate. Run `harness/cc4_report.py` after the host
build to reproduce those checks. `light_tests.py` passes 7249 assertions and 17
native/Python pixel comparisons including white and disabled home playback LEDs.

After deployment, verify the device reports `1.0.0-cc4`, the displayed home action
matches confirmed Sonos state, and a single left-button press pauses/resumes once.
Also check that unavailable/pending playback is disabled, Browse Back still shows
the red close icon, and the other controls retain their existing footer spacing.
