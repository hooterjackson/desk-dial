# Building the Desk Dial app

This guide runs Desk Dial v2.0.0 from the source in the `app/` folder, runs its tests, and builds the same `DeskDial.exe` bundle the release ships. You only need it if you want to change the app or check the release yourself. To use Desk Dial, download `DeskDial-windows-x64.zip` from the [latest release](https://github.com/hooterjackson/desk-dial/releases/latest), unzip it and run `DeskDial.exe`.

Desk Dial is a Windows program. Everything here assumes Windows 10 or 11 and PowerShell.

## What you need

- **Python 3.14** (64-bit) from [python.org](https://www.python.org/downloads/windows/). The release is built with Python 3.14.5. Keep the installer's default options: they include **Tcl/Tk** (Desk Dial's Settings window) and the `py` launcher.
- **About 1 GB of free disk** for the virtual environment and a bundle build.
- For the parts that talk to a knob: a Nano_D++ with the Desk Dial firmware ([flashing guide](flashing.md)). Without one, the simulator below and the tests still work.

## Set up the environment

Open PowerShell in the `app` folder:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
```

`requirements-desktop.txt` includes `requirements.txt` and adds the tray library and PyInstaller. Every package is pinned to an exact version:

| File | Packages |
|---|---|
| `requirements.txt` (the app) | pyserial 3.5, soco 0.31.2, PyJWT[crypto] 2.15.0, Pillow 12.3.0, requests 2.34.2, websocket-client 1.8.0 |
| `requirements-desktop.txt` (adds) | pystray 0.19.5, pyinstaller 6.22.3 |

The repository has no hash-locked requirements file. pip checks each download against PyPI's own hashes, but the versions above are the only pin.

The `.venv` folder is ignored by git, and `Build-Desktop.ps1` expects it at exactly `app\.venv`.

## Run from source

Quit any running Desk Dial first (right-click its tray icon, **Quit**). Only one copy runs at a time, and only one program can hold the knob's port.

```powershell
.\.venv\Scripts\python.exe standalone.py
```

This is the real app, the same code as `DeskDial.exe`. It starts in the tray, opens Settings on the first run, connects to the knob, and reads and writes your data in `%LOCALAPPDATA%\DeskDial\`, exactly like the release build. Useful options:

| Option | What it does |
|---|---|
| `--show` | Opens Settings straight away. |
| `--background` | Starts in the tray only (the scheduled task uses this). |
| `--smoke-test` | Checks the bundled assets and the windows without opening a port, the network or any desktop action, then exits. The result goes to `%LOCALAPPDATA%\DeskDial\logs\smoke-test.json`. |
| `--smoke-test --headless` | The same check with no window at all. |

To try the screens without a knob, a speaker or any account, run the simulator:

```powershell
.\.venv\Scripts\python.exe app.py
```

It opens the control-center window driven by simulated speakers, music and windows, and never opens a serial port. `app.py --live` uses your configured Sonos, Apple Music and real Windows instead.

## Run the tests

The tests use Python's own `unittest` and need no extra packages. From the `app` folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

The guarded runner in `tools/` runs the same tests with Tk windows, serial ports, the browser and any hardware script blocked, so no test can open a window or touch a knob by accident. This is how the release is tested:

```powershell
.\.venv\Scripts\python.exe ..\tools\run_no_tk.py "test_*.py"
```

*You should see* a final line like `RESULT: ran 5431, failures 0, errors 0, skipped 77`. The exact counts change between versions. Skipped tests are live probes that only run when you set the environment variable named in their skip reason.

A few tests read the `firmware/`, `harness/` and `tools/` folders next to `app/`. Run them from a full clone of the repository.

The full suite takes several minutes. To run one module, name it: `..\tools\run_no_tk.py test_app_profiles.py`.

## Build the bundle

```powershell
.\Build-Desktop.ps1
```

The script:

1. installs `requirements-desktop.txt` into `app\.venv` (it refuses to run without that environment);
2. builds `DeskDial.exe` with PyInstaller as a one-folder, windowed program, with the app icon, the version resource from `desktop-version.txt` and the bundled assets and app profiles;
3. checks that the exe carries the Desk Dial version resource;
4. runs the frozen exe's `--smoke-test --headless` and stops if it fails.

The bundle goes into a versioned folder, `desktop-dist-<version>\DeskDial\`, holding `DeskDial.exe` and its `_internal\` folder. The script prints the folder name, and its `-Dist` parameter sets another one. The build refuses to overwrite the folders of earlier versions. `-SkipSmoke` builds without the smoke test, which is useful while Desk Dial is running (the smoke test refuses to start then). In that case, run `DeskDial.exe --smoke-test` yourself before installing.

Right-click the new `DeskDial.exe`, choose **Properties**, then **Details**. *You should see* product name Desk Dial and product version 2.0.0.

The release zip `DeskDial-windows-x64.zip` is this `DeskDial\` folder, zipped.

## Windows SmartScreen and unsigned builds

Neither the release `DeskDial.exe` nor your own build carries a code-signing certificate. The first time you start one, Windows SmartScreen may show **"Windows protected your PC"**:

1. Click **More info**.
2. Check that the app is `DeskDial.exe`, then click **Run anyway**.

If the zip came from the internet, Windows marks every file inside it as downloaded. You can clear the mark before you unzip, which also avoids the warning: right-click the zip, choose **Properties**, tick **Unblock** and click **OK**. In PowerShell:

```powershell
Unblock-File .\DeskDial-windows-x64.zip
```

A bundle you built yourself carries no download mark, so SmartScreen does not usually ask.

On Windows 11 with **Smart App Control** switched on, Windows may block the unsigned exe outright, with no "Run anyway". Read the [FAQ](faq.md) before you decide whether to change that setting.

## Install and uninstall a build (optional)

The release is portable: unzip it anywhere, run `DeskDial.exe`, and delete the folder to remove it. The two scripts below are for people who build from source and want Desk Dial to start with Windows like an installed program. They work in your own Windows account only; the sign-in task runs without administrator rights.

### Install-Desktop.ps1

From the `app` folder, with Desk Dial quit and after a passing smoke test of the new bundle:

```powershell
.\Install-Desktop.ps1 -DryRun -Mirror
.\Install-Desktop.ps1 -Mirror
```

- `-DryRun` runs every check and writes the plan to `diagnostics\desktop-install-plan.json`, without changing anything. Read it first.
- `-Mirror` makes the installed program folder match the bundle exactly. It removes program files that the bundle no longer ships. It never touches your data.
- `-Bundle <folder>` picks another bundle folder. By default the script installs the folder that `Build-Desktop.ps1` builds.

The script:

- copies the bundle to `%LOCALAPPDATA%\Programs\DeskDial\`, staged and verified, and puts the previous program back if the copy fails;
- registers a scheduled task **Desk Dial** that starts `DeskDial.exe --background` when you sign in;
- adds a **Desk Dial** shortcut to the Start menu.

It refuses a bundle whose frozen smoke test has not passed (`%LOCALAPPDATA%\DeskDial\logs\smoke-test.json`), and it never deletes `%LOCALAPPDATA%\DeskDial\`.

### Uninstall-Desktop.ps1

```powershell
.\Uninstall-Desktop.ps1 -DryRun
.\Uninstall-Desktop.ps1
```

The script removes what `Install-Desktop.ps1` added:

- the program folder `%LOCALAPPDATA%\Programs\DeskDial\`;
- the **Desk Dial** sign-in task;
- the Start-menu shortcut.

It keeps your data folder `%LOCALAPPDATA%\DeskDial\` (settings, encrypted credentials, logs, knob backups), so a later install finds everything again. Add `-RemoveData` to delete that folder as well. `-DryRun` prints the plan as JSON and changes nothing. While `DeskDial.exe` is running, the script changes nothing and asks you to quit Desk Dial from the tray first.

Removing the data folder does not revoke your tokens. To revoke them, see [privacy](privacy.md).

## Help

[Troubleshooting](troubleshooting.md) · [FAQ](faq.md) · [open an issue](https://github.com/hooterjackson/desk-dial/issues) · [Karl's Discord](https://discord.gg/mVTvppcfp6).
