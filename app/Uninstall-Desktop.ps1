param(
    # Uninstalls Desk Dial for the signed-in user: the program folder %LOCALAPPDATA%\Programs\DeskDial, the
    # sign-in task 'Desk Dial' and the Start-menu shortcut 'Desk Dial.lnk'. The names are Install-Desktop.ps1's
    # DeskDial identity ($identities['DeskDial']: program, task, shortcut, home).
    # The data folder %LOCALAPPDATA%\DeskDial (settings, credentials, logs, backups) stays, so a later install
    # finds it again, unless -RemoveData is given.
    # Quit Desk Dial from the tray first: while DeskDial.exe runs, nothing is changed.
    # Review first:   Uninstall-Desktop.ps1 -DryRun
    # Then:           Uninstall-Desktop.ps1            (or -RemoveData to delete the data folder as well)
    [switch]$RemoveData,
    # Plan only: runs every check, prints the plan as JSON (what would be removed and what stays) and changes
    # nothing. Exit 0 when the uninstall would go ahead, 1 when it would be refused.
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'

# Install-Desktop.ps1's DeskDial identity, the same names and paths.
$id = @{ name = 'DeskDial'; exe = 'DeskDial.exe'; program = 'Programs\DeskDial'; home = 'DeskDial';
         task = 'Desk Dial'; shortcut = 'Desk Dial.lnk' }
$programsMenu = [Environment]::GetFolderPath('Programs')
$install = Join-Path $env:LOCALAPPDATA $id.program
$homeDir = Join-Path $env:LOCALAPPDATA $id.home
$shortcutPath = Join-Path $programsMenu $id.shortcut

$refusals = New-Object System.Collections.Generic.List[string]
$running = @(Get-Process -Name 'DeskDial' -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    $refusals.Add('Quit Desk Dial from the tray before uninstalling (DeskDial.exe is running); nothing was changed.')
}

# What would go. The staged-install leftovers (<program>.new / .old, Install-Desktop.ps1's DD-BUG-043) are
# program files too and go with the program folder when present.
$folders = @()
foreach ($folder in @($install, "$install.new", "$install.old")) {
    if (Test-Path -LiteralPath $folder) { $folders += $folder }
}
$taskPresent = [bool](Get-ScheduledTask -TaskName $id.task -ErrorAction SilentlyContinue)
$shortcutPresent = Test-Path -LiteralPath $shortcutPath
$dataPresent = Test-Path -LiteralPath $homeDir

$plan = [ordered]@{
    dryRun = [bool]$DryRun; refusals = @($refusals); wouldUninstall = ($refusals.Count -eq 0)
    program = [ordered]@{ folder = $install; present = (Test-Path -LiteralPath $install); remove = @($folders) }
    task = [ordered]@{ name = $id.task; present = $taskPresent; unregister = $taskPresent }
    shortcut = [ordered]@{ path = $shortcutPath; present = $shortcutPresent; remove = $shortcutPresent }
    data = [ordered]@{ folder = $homeDir; present = $dataPresent; remove = ([bool]$RemoveData -and $dataPresent)
                       kept = (-not [bool]$RemoveData) }
}

if ($DryRun) {
    $plan | ConvertTo-Json -Depth 4
    exit $(if ($refusals.Count -gt 0) { 1 } else { 0 })
}
if ($refusals.Count -gt 0) { throw $refusals[0] }

# The task first, so a sign-in cannot start the program while its folder goes.
if ($taskPresent) { Unregister-ScheduledTask -TaskName $id.task -Confirm:$false }
foreach ($folder in $folders) { Remove-Item -LiteralPath $folder -Recurse -Force }
if ($shortcutPresent) { Remove-Item -LiteralPath $shortcutPath -Force }
if ($RemoveData -and $dataPresent) { Remove-Item -LiteralPath $homeDir -Recurse -Force }

Write-Output "Desk Dial uninstalled: $install"
if ($RemoveData) { Write-Output "Data folder removed: $homeDir" }
else { Write-Output "Data folder kept (settings, credentials, logs): $homeDir. Run again with -RemoveData to delete it." }
