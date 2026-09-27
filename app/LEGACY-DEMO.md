# Nano_D++ desktop demo

A local Windows demo for the Nano_D++ evaluation kit. Turn the knob for Windows volume or scrolling; use its four buttons for media controls. This uses the kit's USB serial interface and existing firmware. It is the basic connection demo; the broader display and LED design is a separate concept.

## Start

1. Double-click **Launch.cmd** (Python 3.10+ with Tkinter must be installed).
2. Choose the knob's COM port and click **Connect**. Close ZeroOne or another app using that port first.
3. The app starts in preview. Turn the knob and watch the event log.
4. Check **Enable desktop controls**. The app backs up the current profile, temporarily disables its native input mappings, and verifies the readback before enabling Windows output.

| Control | Action |
|---|---|
| Clockwise / counterclockwise | Volume up/down, or scroll down/up |
| A | Mute / unmute |
| B | Play / pause |
| C | Next track |
| D | Switch Volume / Scroll |

Simulation buttons always affect the preview only. The preview meter is an illustration of incoming steps, not a measurement of Windows volume. Mouse-wheel input goes to the window Windows selects for scrolling, usually the window under the pointer. Media support depends on the active media application. Elevated applications may reject input from this app.

Windows volume keys target Windows audio. With SteelSeries Sonar, this can be a virtual playback channel rather than Sonar's master mix. This baseline does not yet control Sonar's individual sliders or read their values.

## Restore and disconnect

Uncheck **Enable desktop controls**, click **Disconnect**, or close the window to restore and verify the original input mappings. Wait for restoration before unplugging. Profile backups are retained in **backups/** beside the app.

The demo sends no save command and changes no calibration, motor, lighting, or global settings. It preserves the existing knob haptic configuration. If USB disconnects or the app crashes, desktop output stops; reconnect the same knob in the same app to attempt restoration. Power-cycling the knob reloads its last saved device configuration. Unsaved edits made in another configuration app are not guaranteed to survive a power cycle; the original full profile is retained in the backup file.

Preview mode does not change the device mappings. The knob may still perform actions already assigned by its firmware while in preview. Enabling the demo clears those native actions temporarily to avoid duplicate input.

## Dependency

The app uses the Python standard library plus **pyserial 3.5**. If the `vendor/serial` package is absent, open a terminal in this folder and run:

```powershell
python -m pip install --target vendor pyserial==3.5
```

No network connection is required during use. Only pressing Connect opens a serial device; nothing auto-connects or auto-enables desktop output.

## Checks

```powershell
python -m unittest discover -s tests -v
python app.py --smoke-test
python app.py --list-ports
```

Tests use fake serial and fake Windows input. The UI smoke test opens no devices and sends no desktop input. Listing ports does not open them.

## Protocol basis

This demo follows [NanoD_RatchetH1](https://github.com/katbinaris/NanoD_RatchetH1), particularly `src/com_thread.cpp` and `src/HapticProfileManager.cpp`. It reads newline-delimited JSON at 115200 baud. Current firmware emits position `p` and numeric `kd`/`ku` button indices; legacy documented angle and letter events are also accepted. The first position establishes a baseline and large discontinuities are ignored. Each desktop update is bounded to eight steps.

An unexpected firmware/profile format prevents desktop controls from enabling. The demo does not flash firmware. On September 22, 2026, the app's read-only connection was verified against the kit on COM8, which reported firmware 1.0.0. The 39 automated tests and hidden UI smoke test passed. Physical knob-to-Windows output and temporary profile restoration have not yet been tested on the kit; their tests use simulated devices.
