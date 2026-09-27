param(
    # Output folder names. v7 is the desktop half of the combined release with firmware
    # 1.0.0-cc5.4 ("Warm alive" LEDs, presentation 5): the floating knob rendered from the alive
    # lights, the NanoD-stage music overlays (Explorer and Up next), the Settings status strip and
    # the Motion setting. desktop-dist-v6 (the floating knob with the Windows-switcher carousel,
    # the desktop rollback of v7), desktop-dist-v5 (the floating knob with the grid picker),
    # desktop-dist-v4 (the cc5.3 window companion), desktop-dist-v3 (the cc5.2-era companion) and
    # desktop-dist-v2 (the cc4-era companion) are rollback bundles and must never be rebuilt in
    # place, nor their work folders reused. From v7 the app is Desk Dial (rename-desk-dial.md): the
    # bundle is $Dist\DeskDial\DeskDial.exe with a version resource naming Desk Dial
    # (desktop-version.txt); the rollback bundles keep NanoDControlCenter\NanoDControlCenter.exe.
    [string]$Dist = 'desktop-dist-v7',
    [string]$Work = 'desktop-build-v7',
    # Build only; the frozen smoke test runs later. Without -SkipSmoke the build refuses to run
    # it while the companion is running, as a precaution (the smoke test itself runs before the
    # single-instance mutex and never signals the running instance). Install-Desktop.ps1 installs
    # a new bundle only after %LOCALAPPDATA%\DeskDial\logs\smoke-test.json records a
    # pass of that bundle's exe. The build's own smoke test is --smoke-test --headless: it never
    # creates a Tk window or shows anything (the knob, stage and carousel windows are created
    # hidden and destroyed).
    [switch]$SkipSmoke
)
$ErrorActionPreference = 'Stop'
$rollbackFolders = @('desktop-dist-v2', 'desktop-build-v2', 'desktop-dist-v3', 'desktop-build-v3', 'desktop-dist-v4', 'desktop-build-v4', 'desktop-dist-v5', 'desktop-build-v5', 'desktop-dist-v6', 'desktop-build-v6')
foreach ($folder in @($Dist, $Work)) {
    $leaf = Split-Path -Leaf ($folder.TrimEnd('\', '/'))
    if ($rollbackFolders -contains $leaf) { throw "$leaf belongs to a rollback bundle (v2 is the cc4-era companion, v3 the cc5.2-era one, v4 the cc5.3 window companion, v5 the floating knob with the grid picker, v6 the floating knob with the Windows-switcher carousel); build into a new folder." }
}
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $base = & $python -c 'import sys; print(sys.base_prefix)'
    if ($LASTEXITCODE -ne 0) { throw 'Python build environment unavailable.' }
    & $python -m pip install -r requirements-desktop.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $assets = (Join-Path $PSScriptRoot 'assets') + ';assets'
    # APP_ICON.md item 1: the exe (and so the Start-menu shortcut) carries the designer's app icon,
    # all 8 frames (16-256 px). assets\app-icon ships with the other assets.
    $appIcon = Join-Path $PSScriptRoot 'assets\app-icon\ico\nano-d-app.ico'
    if (-not (Test-Path -LiteralPath $appIcon)) { throw "App icon missing: $appIcon" }
    # rename-desk-dial.md 3.1: FileDescription and ProductName 'Desk Dial', so Task Manager, the
    # notification source and Settings > Taskbar name the app, not the exe.
    $versionFile = Join-Path $PSScriptRoot 'desktop-version.txt'
    if (-not (Test-Path -LiteralPath $versionFile)) { throw "Version resource missing: $versionFile" }
    # rename-desk-dial.md 11.10: PyInstaller replaces only its own --name folder, so an older build of
    # this dist folder under the old name (never installed, never pinned) is moved into the work
    # folder first (never deleted); the dist folder then holds the one Desk Dial bundle.
    $oldNameBuild = Join-Path $Dist 'NanoDControlCenter'
    if (Test-Path -LiteralPath $oldNameBuild) {
        New-Item -ItemType Directory -Path $Work -Force | Out-Null
        $superseded = Join-Path $Work ('superseded-NanoDControlCenter-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
        Move-Item -LiteralPath $oldNameBuild -Destination $superseded
        Write-Output "Moved the old-name build out of the dist folder: $superseded"
    }
    # The tray app imports most of its modules inside functions (the floating knob, the carousel,
    # the stage and its music scenes start after the tray): they are listed explicitly so the
    # bundle always has them. v7 adds the alive lights (the floating knob's LED engine), the
    # pre-alive preview lights, the music overlay and its scene/render modules, the simulator and
    # every module of the NanoD-stage package (--collect-submodules control_center.stage: the
    # stage thread, its presenter and the Explorer / Up next scenes).
    & $python -m PyInstaller --noconfirm --windowed --onedir --name DeskDial --icon $appIcon --version-file $versionFile --distpath $Dist --workpath $Work --specpath $Work --paths (Join-Path $base 'Lib') --paths (Join-Path $base 'DLLs') --add-data $assets --hidden-import tkinter --hidden-import _tkinter --hidden-import tkinter.font --hidden-import tkinter.filedialog --hidden-import tkinter.messagebox --hidden-import pystray._win32 --hidden-import PIL.ImageTk --hidden-import PIL._tkinter_finder --hidden-import control_center.overlay --hidden-import control_center.knob_face --hidden-import control_center.carousel --hidden-import control_center.carousel_render --hidden-import control_center.window_labels --hidden-import control_center.window_facts --hidden-import control_center.alive_lights --hidden-import control_center.preview_lights --hidden-import control_center.music_overlay --hidden-import control_center.scene_music --hidden-import control_center.render_music --hidden-import control_center.queue_context --hidden-import control_center.simulation --hidden-import control_center.presentation --hidden-import control_center.stage --hidden-import control_center.stage.scenes --collect-submodules control_center.stage --collect-all soco standalone.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    # PyInstaller can report success even when a restricted build cannot read Tk.
    $distRoot = $Dist
    if (-not [IO.Path]::IsPathRooted($Dist)) { $distRoot = Join-Path $PSScriptRoot $Dist }
    $builtExe = Join-Path $distRoot 'DeskDial\DeskDial.exe'
    if ((Get-Item -LiteralPath $builtExe).VersionInfo.FileDescription -ne 'Desk Dial') { throw 'The built exe does not carry the Desk Dial version resource.' }
    if ($SkipSmoke) {
        Write-Output "Build created (smoke test skipped): $builtExe"
        return
    }
    if (Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue) {
        throw 'Build created. Quit the running companion (Desk Dial or the old NanoD Control Center) and run --smoke-test --headless on the new executable before installation.'
    }
    # The headless smoke test also creates the floating knob's layered window, the stage's surfaces
    # and the carousel's windows hidden (never shown), presents frames and destroys them, checking
    # the GDI/USER object counts; it never creates a Tk root.
    $smoke = Start-Process -FilePath $builtExe -ArgumentList '--smoke-test', '--headless' -WindowStyle Hidden -PassThru -Wait
    if ($smoke.ExitCode -ne 0) { throw 'Packaged smoke test failed. Do not install this bundle.' }
} finally { Pop-Location }
