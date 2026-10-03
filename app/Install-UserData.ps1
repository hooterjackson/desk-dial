param([Parameter(Mandatory=$true)][string]$Plan,
      [Parameter(Mandatory=$true)][string]$Report,
      [ValidateSet('install', 'cleanup')][string]$Step = 'install')
$ErrorActionPreference = 'Stop'
# Run by Task Scheduler as the signed-in user for Install-Desktop.ps1 (which writes $Plan), outside a
# packaged parent's AppData virtualization (rename-desk-dial.md 11.4), so what it writes is what the
# app and the sign-in task see.
#   install: 1. the installed exe is the bundle's, as this user sees it (else nothing else happens);
#            2. the migration (Desk Dial only; lead ruling on the rename, item 3): the whole old home
#               %LOCALAPPDATA%\NanoDControlCenter\ (data\, logs\, backups\, queue-recovery.bin,
#               shuffle-restore.bin) is copied to %LOCALAPPDATA%\DeskDial\ once, each file checked by
#               SHA-256 before it takes its name, a file already there kept, the old home only read;
#            3. the staged seeds (local\settings.json, local\credentials.bin), only where a file is
#               missing, after the migration (14.3: the user's live files win over the seeds);
#            4. the Start-menu shortcut.
#   cleanup: after the new sign-in task is registered: the other name's program folder is moved to the
#            backups\ of the new home, on its own volume (moved, never deleted), then its shortcut removed.
# Records names, sizes and whether hashes matched; never file contents or hashes.

function Copy-OldHome([string]$Source, [string]$Destination) {
    # Once: migration.json marks it done, so a later install never copies again (it would bring back
    # queue-recovery.bin or shuffle-restore.bin the app has since removed, or older settings).
    $record = Join-Path $Destination 'migration.json'
    if (Test-Path -LiteralPath $record) { return [ordered]@{ source = $Source; destination = $Destination; skipped = 'already migrated'; files = @() } }
    if (-not (Test-Path -LiteralPath $Source)) { return [ordered]@{ source = $Source; destination = $Destination; skipped = 'no old home'; files = @() } }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $root = (Get-Item -LiteralPath $Source).FullName.TrimEnd('\')
    $created = New-Object System.Collections.Generic.List[string]
    $files = @()
    try {
        foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse -Force)) {
            $relative = $file.FullName.Substring($root.Length).TrimStart('\')
            $target = Join-Path $Destination $relative
            if (Test-Path -LiteralPath $target) {
                $files += [ordered]@{ name = $relative; bytes = $file.Length; copied = $false; kept = 'exists' }
                continue
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            $partial = "$target.migrating"
            $created.Add($partial)
            Copy-Item -LiteralPath $file.FullName -Destination $partial
            $match = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash -eq (Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash
            if (-not $match) { throw "the copy of $relative differs from the old home" }
            Move-Item -LiteralPath $partial -Destination $target
            $created.Add($target)
            $files += [ordered]@{ name = $relative; bytes = $file.Length; copied = $true; hashMatch = $true }
        }
    } catch {
        # Nothing half-done stays: only the files this run created are removed; the old home was only read.
        foreach ($path in $created) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } }
        throw
    }
    $result = [ordered]@{ source = $Source; destination = $Destination; skipped = $null
                          timeUtc = (Get-Date).ToUniversalTime().ToString('o'); files = $files }
    $result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $record -Encoding UTF8
    return $result
}

# The report's folder may not exist yet (diagnostics\ is not in the repository): created before the first write,
# so a failure is still reported.
$reportFolder = Split-Path -Parent $Report
if ($reportFolder) { New-Item -ItemType Directory -Path $reportFolder -Force | Out-Null }
$stage = 'plan'
try {
    $p = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
    if ($Step -eq 'cleanup') {
        # The program folder first, then the shortcut: if the move fails the other install stays whole
        # (folder and shortcut). The backup is on the program's volume, so the move is a rename.
        $stage = 'program'
        $moved = $null
        if (Test-Path -LiteralPath $p.otherProgram) {
            if (Test-Path -LiteralPath $p.programBackup) { throw "$($p.programBackup) already exists" }
            $programRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($p.otherProgram))
            $backupRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($p.programBackup))
            if (-not [string]::Equals($programRoot, $backupRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "$($p.programBackup) is not on the same volume as $($p.otherProgram)"
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $p.programBackup) -Force | Out-Null
            Move-Item -LiteralPath $p.otherProgram -Destination $p.programBackup
            $moved = $p.programBackup
        }
        $stage = 'shortcut'
        $removed = $false
        if (Test-Path -LiteralPath $p.otherShortcut) { Remove-Item -LiteralPath $p.otherShortcut -Force; $removed = $true }
        [ordered]@{ passed = $true; step = 'cleanup'; shortcutRemoved = $removed; programMovedTo = $moved } |
            ConvertTo-Json | Set-Content -LiteralPath $Report -Encoding UTF8
        exit 0
    }
    $stage = 'program'
    if (-not (Test-Path -LiteralPath $p.exe) -or (Get-FileHash -Algorithm SHA256 -LiteralPath $p.exe).Hash -ne $p.exeSha256) {
        throw "$($p.exe) is not the bundle's exe as the signed-in user sees it; run Install-Desktop.ps1 from a normal PowerShell window"
    }
    $stage = 'migration'
    $migration = $null
    if ($p.migrateFrom) { $migration = Copy-OldHome $p.migrateFrom $p.home }
    $stage = 'seeds'
    New-Item -ItemType Directory -Path $p.data -Force | Out-Null
    $files = @()
    foreach ($name in @($p.seedNames)) {
        $inputFile = Join-Path $p.seeds $name
        $outputFile = Join-Path $p.data $name
        $copied = $false
        if ((Test-Path -LiteralPath $inputFile) -and -not (Test-Path -LiteralPath $outputFile)) {
            Copy-Item -LiteralPath $inputFile -Destination $outputFile
            if ((Get-FileHash -LiteralPath $inputFile).Hash -ne (Get-FileHash -LiteralPath $outputFile).Hash) {
                throw "Data verification failed: $name"
            }
            $copied = $true
        }
        $files += [ordered]@{ name = $name; copied = $copied; exists = (Test-Path -LiteralPath $outputFile) }
    }
    $stage = 'shortcut'
    $install = Split-Path -Parent $p.exe
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($p.shortcut)
    $shortcut.TargetPath = $p.exe
    # APP_ICON.md item 2: the shortcut shows the installed exe's embedded app icon (index 0).
    $shortcut.IconLocation = $p.exe + ',0'
    $shortcut.Arguments = '--show'
    $shortcut.WorkingDirectory = $install
    $shortcut.Description = $p.shortcutDescription
    $shortcut.Save()
    [ordered]@{ passed = $true; step = 'install'; identity = $p.identity; destination = $p.data; files = $files
                migration = $migration; shortcut = $p.shortcut } |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Report -Encoding UTF8
} catch {
    [ordered]@{ passed = $false; step = $Step; stage = $stage; error = $_.Exception.GetType().Name; detail = $_.Exception.Message } |
        ConvertTo-Json | Set-Content -LiteralPath $Report -Encoding UTF8
    exit 1
}
