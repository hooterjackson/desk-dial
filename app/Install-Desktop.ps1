param(
    # Bundle folder under this directory. desktop-dist-v7 is the desktop half of the combined
    # release with firmware 1.0.0-cc5.4 (the alive floating knob, the NanoD-stage music overlays,
    # the Settings status strip and Motion) and the first bundle named Desk Dial
    # (DeskDial\DeskDial.exe; design-reference\ui-v2-analysis\rename-desk-dial.md). It also runs
    # against cc5.3 (presentation-4 frames). The pinned rollback bundles v2-v6 are the old name,
    # NanoD Control Center; installing one reverses the rename (the identity table below).
    # Desktop rollback to the floating knob with the Windows-switcher carousel (v6, exe SHA-256
    # 2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F; from a knob on cc5.4
    # only after the firmware rollback to cc5.3, rollback_nanod_cc5.py --to cc5.3, because
    # cc5.4's knob copy names Desk Dial; firmware\BUILD-cc5.4.md "Desktop rollback, v7 -> v6"):
    #   Install-Desktop.ps1 -Bundle desktop-dist-v6 -Mirror
    # Rollback to the floating knob with the grid picker (v5, exe SHA-256
    # 0BF15DB86F5376F763193474457DEDFCB04D8ECEBC401E396E966EB668C2D210):
    #   Install-Desktop.ps1 -Bundle desktop-dist-v5 -Mirror
    # Rollback to the cc5.3 window companion (v4, exe SHA-256
    # 63047D1C7C181C456B0AEE6E825B21326899538164E6AFFECB3800785C0C44A5):
    #   Install-Desktop.ps1 -Bundle desktop-dist-v4 -Mirror
    # Rollback to the cc5.2-era companion (v3, exe SHA-256
    # 90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19):
    #   Install-Desktop.ps1 -Bundle desktop-dist-v3 -Mirror
    # Rollback to the cc4-era companion (v2, exe SHA-256
    # 95909AAE4AA4852F5E4954EEED329E513FC474BC50E08B8DCD6655CE410A123D):
    #   Install-Desktop.ps1 -Bundle desktop-dist-v2 -Mirror
    # A rollback reads the old home as Desk Dial copied it; settings changed in Desk Dial since are
    # not carried back (no option does it; copy them by hand with the user if wanted), and
    # %LOCALAPPDATA%\DeskDial\ stays for a later return (no second migration).
    # Install (the desktop step of the cc5.4 window, or on its own): quit the app from the tray; run
    # the new bundle's frozen smoke test (desktop-dist-v7\DeskDial\DeskDial.exe --smoke-test, or
    # --smoke-test --headless, which never creates a window) and check that
    # %LOCALAPPDATA%\DeskDial\logs\smoke-test.json says passed: true;
    # back up the program folder and hash the user data; review the plan of
    # Install-Desktop.ps1 -Bundle desktop-dist-v7 -Mirror -DryRun (diagnostics\desktop-install-plan.json); run
    # Install-Desktop.ps1 -Bundle desktop-dist-v7 -Mirror; confirm the old home's hashes are
    # unchanged and the migrated copies equal them, then start the task and verify. A bundle that is not a recorded rollback is
    # refused unless that report is a pass of this bundle's exe, newer than the exe.
    [string]$Bundle = 'desktop-dist-v7',
    # Remove program files that are not part of the bundle (never touches user data). Recommended for
    # the forward install as well (Install-Desktop.ps1 -Mirror): it clears program files left over from
    # the previous bundle of the same name that this one no longer ships, so the installed folder
    # matches the bundle exactly. The other name's program folder is moved to backups\ as a whole
    # (never deleted). Copy the installed program folder to backups\ yourself first (the release
    # runbook's desktop step, firmware\BUILD-cc5.4.md step 9b).
    [switch]$Mirror,
    # Plan only (rename-desk-dial.md 14.2 step 4 and 14.4 item 2): runs every check and refusal, reads
    # the old home's file names and sizes, writes diagnostics\desktop-install-plan.json and changes
    # nothing else. Exit 0 when the install would go ahead, 1 when it would be refused.
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
# Rollback bundles are recorded: a desktop-dist-v2, -v3, -v4, -v5 or -v6 whose exe differs is refused before anything changes.
$pinnedBundles = @{ 'desktop-dist-v2' = '95909AAE4AA4852F5E4954EEED329E513FC474BC50E08B8DCD6655CE410A123D';
                    'desktop-dist-v3' = '90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19';
                    'desktop-dist-v4' = '63047D1C7C181C456B0AEE6E825B21326899538164E6AFFECB3800785C0C44A5';
                    'desktop-dist-v5' = '0BF15DB86F5376F763193474457DEDFCB04D8ECEBC401E396E966EB668C2D210';
                    'desktop-dist-v6' = '2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F' }
# The two identities (rename-desk-dial.md sections 1, 11.6 and 12). The pinned bundles v2-v6 hard-code
# NanoD Control Center: its exe, program folder, data home, sign-in task and Start-menu shortcut. Every
# other bundle is Desk Dial. The single-instance mutex and event names are shared (H9), so the two never
# run at once. Installing one retires the other only after the new install and its data step verified:
# its task is unregistered, its shortcut removed and its program folder moved to backups\ (never
# deleted). Neither data home is ever deleted.
$identities = @{
    'DeskDial' = @{ name = 'DeskDial'; exe = 'DeskDial.exe'; program = 'Programs\DeskDial'; home = 'DeskDial';
                    task = 'Desk Dial'; shortcut = 'Desk Dial.lnk';
                    taskDescription = 'Desk Dial: the knob''s Sonos, Apple Music and Windows companion. Runs in the signed-in user session.';
                    shortcutDescription = 'Open Desk Dial settings; the app keeps running in the tray, and the floating knob slides in when you touch the knob.' };
    'NanoDControlCenter' = @{ name = 'NanoDControlCenter'; exe = 'NanoDControlCenter.exe'; program = 'Programs\NanoDControlCenter';
                    home = 'NanoDControlCenter'; task = 'NanoD Control Center'; shortcut = 'Nano_D++ Control Center.lnk';
                    taskDescription = 'Standalone Nano_D++ Sonos and Windows control center. Runs in the signed-in user session.';
                    shortcutDescription = 'Open Nano_D++ Control Center settings; the app keeps running in the tray, and the floating knob slides in when you touch the knob.' }
}
$bundleIdentities = @{ 'desktop-dist-v2' = 'NanoDControlCenter'; 'desktop-dist-v3' = 'NanoDControlCenter';
                       'desktop-dist-v4' = 'NanoDControlCenter'; 'desktop-dist-v5' = 'NanoDControlCenter';
                       'desktop-dist-v6' = 'NanoDControlCenter' }   # any other bundle: DeskDial

function Get-SmokeReportProblem([string]$ReportPath, [string]$BundleExe) {
    # Why the frozen smoke test's report does not clear this bundle, or $null when it does:
    # it must be a pass, run by this bundle's exe (frozen), after the exe was built.
    if (-not (Test-Path -LiteralPath $ReportPath)) { return "there is no $ReportPath" }
    try { $report = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json } catch { return "$ReportPath is not readable JSON" }
    if ($report.passed -ne $true) { return 'the last smoke test did not pass' }
    if ($report.frozen -ne $true) { return 'the last smoke test did not run a frozen exe' }
    $expected = [IO.Path]::GetFullPath($BundleExe)
    if (-not [string]::Equals([string]$report.executable, $expected, [StringComparison]::OrdinalIgnoreCase)) {
        return "the last smoke test ran $($report.executable), not $expected"
    }
    $built = ([DateTimeOffset](Get-Item -LiteralPath $BundleExe).LastWriteTimeUtc).ToUnixTimeMilliseconds() / 1000.0
    if ($null -eq $report.timestamp -or [double]$report.timestamp -lt $built) { return 'the last smoke test is older than this exe' }
    return $null
}

$refusals = New-Object System.Collections.Generic.List[string]
function Stop-Install([string]$Message) {
    # A refusal stops a real install before anything changed; a dry run records it and plans on.
    if ($DryRun) { $refusals.Add($Message) } else { throw $Message }
}

$bundleName = Split-Path -Leaf ($Bundle.TrimEnd('\', '/'))
$pinned = $pinnedBundles.ContainsKey($bundleName)
$idName = 'DeskDial'
if ($bundleIdentities.ContainsKey($bundleName)) { $idName = $bundleIdentities[$bundleName] }
$id = $identities[$idName]
$other = $identities[@($identities.Keys | Where-Object { $_ -ne $idName })[0]]
$programsMenu = [Environment]::GetFolderPath('Programs')
$bundle = Join-Path $PSScriptRoot "$Bundle\$($id.name)"
$bundleExe = Join-Path $bundle $id.exe
$install = Join-Path $env:LOCALAPPDATA $id.program
$exe = Join-Path $install $id.exe
$homeDir = Join-Path $env:LOCALAPPDATA $id.home
$data = Join-Path $homeDir 'data'
$shortcutPath = Join-Path $programsMenu $id.shortcut
$otherInstall = Join-Path $env:LOCALAPPDATA $other.program
$otherShortcut = Join-Path $programsMenu $other.shortcut
# The forward migration (Desk Dial only; lead ruling on the rename, item 3): the whole old home is
# copied to the Desk Dial home once, hash verified, in the task-context step, and stays as the backup.
$migrateFrom = $null
if ($id.name -eq 'DeskDial') { $migrateFrom = Join-Path $env:LOCALAPPDATA $other.home }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$programBackup = Join-Path $PSScriptRoot "backups\desktop-program-$($other.name)-$stamp"
$diagnostics = Join-Path $PSScriptRoot 'diagnostics'
$staging = Join-Path $PSScriptRoot 'local\desktop-install-data'
$seedNames = @('settings.json', 'credentials.bin')

# Checks, in this order, before anything changes.
$bundleExeHash = $null
if (-not (Test-Path -LiteralPath $bundleExe)) {
    Stop-Install "Build the executable first: $bundleExe is missing; nothing was changed."
} else {
    $bundleExeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundleExe).Hash
    if ($pinned) {
        if ($bundleExeHash -ne $pinnedBundles[$bundleName]) { Stop-Install "$bundleName is not the recorded bundle (exe SHA-256 $bundleExeHash); nothing was changed." }
    } else {
        # A new bundle (Build-Desktop.ps1 -SkipSmoke defers its frozen smoke test): install only after it passed.
        # Its report lives in its own home's logs (standalone.py via control_center.paths; rename-desk-dial.md 11.9).
        $smokeProblem = Get-SmokeReportProblem (Join-Path $env:LOCALAPPDATA "$($id.home)\logs\smoke-test.json") $bundleExe
        if ($smokeProblem) {
            Stop-Install "$bundleName has no passing frozen smoke test: $smokeProblem. Quit the companion, run `"$bundleExe`" --smoke-test, check logs\smoke-test.json, then install again; nothing was changed."
        }
    }
}
# Either name holds the knob, its files and the shared mutex (rename-desk-dial.md 11.2): both are refused.
$running = @(Get-Process -Name 'DeskDial', 'NanoDControlCenter' -ErrorAction SilentlyContinue | ForEach-Object { $_.ProcessName } | Sort-Object -Unique)
if ($running.Count -gt 0) { Stop-Install "Quit Desk Dial (or the old Nano_D++ Control Center) from the tray before updating ($($running -join ', ') running); nothing was changed." }

if ($DryRun) {
    # Names and sizes only; nothing is created, copied, registered or removed.
    $stale = @()
    if ($Mirror -and (Test-Path -LiteralPath $install) -and (Test-Path -LiteralPath $bundle)) {
        foreach ($file in @(Get-ChildItem -LiteralPath $install -File -Recurse)) {
            $relative = $file.FullName.Substring($install.Length).TrimStart('\')
            if (-not (Test-Path -LiteralPath (Join-Path $bundle $relative))) { $stale += $relative }
        }
    }
    $migration = $null
    if ($migrateFrom) {
        $record = Join-Path $homeDir 'migration.json'
        $migration = [ordered]@{ source = $migrateFrom; destination = $homeDir; record = $record;
                                 alreadyMigrated = (Test-Path -LiteralPath $record); oldHomeExists = (Test-Path -LiteralPath $migrateFrom);
                                 files = @() }
        if ($migration.oldHomeExists -and -not $migration.alreadyMigrated) {
            $root = (Get-Item -LiteralPath $migrateFrom).FullName.TrimEnd('\')
            foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse -Force)) {
                $relative = $file.FullName.Substring($root.Length).TrimStart('\')
                $action = 'copy'
                if (Test-Path -LiteralPath (Join-Path $homeDir $relative)) { $action = 'keep the existing file' }
                $migration['files'] += [ordered]@{ name = $relative; bytes = $file.Length; action = $action }
            }
        }
    }
    $plan = [ordered]@{
        dryRun = $true; writtenUtc = (Get-Date).ToUniversalTime().ToString('o'); bundle = $bundleName; pinned = $pinned
        bundleExe = $bundleExe; bundleExeSha256 = $bundleExeHash; identity = $id.name; replaces = $other.name
        refusals = @($refusals); wouldInstall = ($refusals.Count -eq 0)
        program = [ordered]@{ install = $install; exe = $exe; mirror = [bool]$Mirror; staleFilesToRemove = $stale }
        tasks = [ordered]@{ register = $id.task; unregister = $other.task
                            unregisterPresent = [bool](Get-ScheduledTask -TaskName $other.task -ErrorAction SilentlyContinue) }
        shortcuts = [ordered]@{ create = $shortcutPath; remove = $otherShortcut; removePresent = (Test-Path -LiteralPath $otherShortcut) }
        otherProgram = [ordered]@{ folder = $otherInstall; present = (Test-Path -LiteralPath $otherInstall); moveTo = $programBackup }
        migration = $migration
        # 14.3: the seeds from local\ are staged only; the task-context step applies them after the
        # migration and only where a file is missing. Nothing is written into a data folder before.
        seeds = [ordered]@{ staged = @($seedNames | Where-Object { Test-Path -LiteralPath (Join-Path $PSScriptRoot "local\$_") });
                            appliedAfterMigration = $true; onlyWhereMissing = $true; writtenBeforeMigration = @() }
        userDataStep = 'Install-UserData.ps1 through a one-shot task (Desk Dial Data Setup <guid>), outside AppData virtualization'
    }
    $planPath = Join-Path $diagnostics 'desktop-install-plan.json'
    $plan | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $planPath -Encoding UTF8
    if ($refusals.Count -gt 0) {
        Write-Output "Dry run: the install would be refused (nothing was changed). Plan: $planPath"
        foreach ($refusal in $refusals) { Write-Output "  refused: $refusal" }
        exit 1
    }
    Write-Output "Dry run: nothing was changed. Plan: $planPath"
    exit 0
}

New-Item -ItemType Directory -Path $install -Force | Out-Null
if ($Mirror -and (Test-Path -LiteralPath $install)) {
    # Program folder only: user data lives in the home folder (%LOCALAPPDATA%\DeskDial or, for a rollback bundle, NanoDControlCenter).
    foreach ($stale in (Get-ChildItem -LiteralPath $install -File -Recurse)) {
        $relative = $stale.FullName.Substring($install.Length).TrimStart('\')
        if (-not (Test-Path -LiteralPath (Join-Path $bundle $relative))) { Remove-Item -LiteralPath $stale.FullName -Force }
    }
}
Get-ChildItem -LiteralPath $bundle | Copy-Item -Destination $install -Recurse -Force
foreach ($file in (Get-ChildItem -LiteralPath $bundle -File -Recurse)) {
    $relative = $file.FullName.Substring($bundle.Length).TrimStart('\')
    if ((Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath (Join-Path $install $relative)).Hash) {
        throw "Bundle verification failed: $relative"
    }
}
# A packaged launcher can redirect AppData into its own private LocalCache (rename-desk-dial.md 11.4).
# The seeds (14.3: local\settings.json and local\credentials.bin, already encrypted) are staged outside
# AppData only, never written into a data folder here; the per-user work (the program check as the
# user sees it, the migration, the seeds, the shortcuts) runs in the unvirtualized context of a
# one-shot task, like the startup task's.
New-Item -ItemType Directory -Path $staging -Force | Out-Null
foreach ($name in $seedNames) {
    $seed = Join-Path $PSScriptRoot "local\$name"
    $staged = Join-Path $staging $name
    if (Test-Path -LiteralPath $seed) { Copy-Item -LiteralPath $seed -Destination $staged -Force }
    elseif (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Force }   # never apply a stale seed
}
$stepPlan = Join-Path $staging 'install-step.json'
[ordered]@{ identity = $id.name; program = $install; exe = $exe; exeSha256 = $bundleExeHash; home = $homeDir; data = $data
            seeds = $staging; seedNames = $seedNames; migrateFrom = $migrateFrom
            shortcut = $shortcutPath; shortcutDescription = $id.shortcutDescription
            otherShortcut = $otherShortcut; otherProgram = $otherInstall; programBackup = $programBackup } |
    ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $stepPlan -Encoding UTF8
$userName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$dataScript = Join-Path $PSScriptRoot 'Install-UserData.ps1'

function Invoke-UserDataStep([string]$Step, [string]$ReportPath) {
    # Task Scheduler runs Install-UserData.ps1 as this user, outside a packaged parent's AppData
    # virtualization, so what it writes is what the app will see. Returns its report; throws on a failure.
    if (Test-Path -LiteralPath $ReportPath) { Remove-Item -LiteralPath $ReportPath }
    $taskName = 'Desk Dial Data Setup ' + [Guid]::NewGuid().ToString('N')
    $taskAction = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Plan "{1}" -Step {2} -Report "{3}"' -f $dataScript, $stepPlan, $Step, $ReportPath)
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $userName -LogonType Interactive -RunLevel Limited
    $result = $null
    try {
        Register-ScheduledTask -TaskName $taskName -Action $taskAction -Principal $taskPrincipal -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3)) | Out-Null
        Start-ScheduledTask -TaskName $taskName
        $deadline = (Get-Date).AddSeconds(150)
        while ($null -eq $result -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 250
            if (Test-Path -LiteralPath $ReportPath) {
                try { $result = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json } catch { $result = $null }   # still being written
            }
        }
    } finally {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    if ($null -eq $result) { throw "Standalone data setup ($Step) timed out." }
    if ($result.passed -ne $true) { throw "Standalone data setup ($Step) failed at $($result.stage): $($result.detail)" }
    return $result
}

# 1. The program as the user sees it, the migration, the seeds and the new shortcut. On a failure
#    nothing of the other name has been touched: its task, shortcut, program folder and home stay.
$userData = Invoke-UserDataStep 'install' (Join-Path $diagnostics 'desktop-user-data.json')
# 2. The sign-in task.
$action = New-ScheduledTaskAction -Execute $exe -Argument '--background' -WorkingDirectory $install
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userName
$trigger.Delay = 'PT10S'
$principal = New-ScheduledTaskPrincipal -UserId $userName -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval ([TimeSpan]::FromMinutes(1)) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $id.task -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $id.taskDescription -Force | Out-Null
Export-ScheduledTask -TaskName $id.task | Set-Content -LiteralPath (Join-Path $diagnostics 'desktop-startup-task.xml') -Encoding UTF8
# 3. Retire the other name, now that the new install verified: two sign-in tasks would start two
#    companions (rename-desk-dial.md 11.2). Its shortcut goes and its program folder moves to backups\.
$otherTaskFound = [bool](Get-ScheduledTask -TaskName $other.task -ErrorAction SilentlyContinue)
if ($otherTaskFound) { Unregister-ScheduledTask -TaskName $other.task -Confirm:$false }
$cleanupError = $null
$cleanup = $null
try { $cleanup = Invoke-UserDataStep 'cleanup' (Join-Path $diagnostics 'desktop-install-cleanup.json') } catch { $cleanupError = $_.Exception.Message }
$migrationSummary = $null
if ($userData.migration) {
    $migrated = @()
    if ($userData.migration.files) { $migrated = @($userData.migration.files) }
    $migrationSummary = [ordered]@{ source = $userData.migration.source; skipped = $userData.migration.skipped
                                    copied = @($migrated | Where-Object { $_.copied -eq $true }).Count
                                    kept = @($migrated | Where-Object { $_.copied -ne $true }).Count }
}
[ordered]@{ executable = $exe; shortcut = $shortcutPath; task = $id.task; data = $data; sha256 = (Get-FileHash -LiteralPath $exe).Hash
            identity = $id.name; home = $homeDir; migration = $migrationSummary
            replaced = [ordered]@{ identity = $other.name; task = $other.task; taskUnregistered = $otherTaskFound
                                   shortcutRemoved = $(if ($cleanup) { $cleanup.shortcutRemoved } else { $null })
                                   programMovedTo = $(if ($cleanup) { $cleanup.programMovedTo } else { $null }); error = $cleanupError } } |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $diagnostics 'desktop-installation.json') -Encoding UTF8
if ($cleanupError) { throw "Installed and verified: $exe, but the old name was not fully retired: $cleanupError" }
Write-Output "Installed and verified: $exe"
Write-Output "Startup task '$($id.task)' registered for sign-in. Use Start-ScheduledTask to launch it independently."
