$ErrorActionPreference = 'Stop'
# The installed companion is Desk Dial (desktop v7 on) or, after a desktop rollback to a pinned v2-v6
# bundle, the old NanoD Control Center (rename-desk-dial.md 11.12). The installer moves the other
# name's program folder to backups\, so the installed one is the one whose exe exists; when both
# exist, the installer's record (desktop-installation.json) decides.
$identities = @(
    @{ exe = Join-Path $env:LOCALAPPDATA 'Programs\DeskDial\DeskDial.exe'; logs = Join-Path $env:LOCALAPPDATA 'DeskDial\logs' },
    @{ exe = Join-Path $env:LOCALAPPDATA 'Programs\NanoDControlCenter\NanoDControlCenter.exe'; logs = Join-Path $env:LOCALAPPDATA 'NanoDControlCenter\logs' })
$installed = @($identities | Where-Object { Test-Path -LiteralPath $_.exe })
if ($installed.Count -eq 0) { throw 'No installed companion (DeskDial.exe or NanoDControlCenter.exe) was found.' }
$chosen = $installed[0]
if ($installed.Count -gt 1) {
    $record = Join-Path $PSScriptRoot 'desktop-installation.json'
    if (Test-Path -LiteralPath $record) {
        $recorded = [string](Get-Content -LiteralPath $record -Raw | ConvertFrom-Json).executable
        $match = @($installed | Where-Object { [string]::Equals($_.exe, $recorded, [StringComparison]::OrdinalIgnoreCase) })
        if ($match.Count -eq 1) { $chosen = $match[0] }
    }
}
$logs = $chosen.logs
$exe = $chosen.exe
$process = Start-Process -FilePath $exe -ArgumentList '--check-music' -WindowStyle Hidden -Wait -PassThru
$result = @{
    checkedAt=(Get-Date).ToString('o')
    executable=$exe
    music=(Get-Content -LiteralPath (Join-Path $logs 'music-check.json') -Raw | ConvertFrom-Json)
    app=(Get-Content -LiteralPath (Join-Path $logs 'status.json') -Raw | ConvertFrom-Json)
    diagnosticExitCode=$process.ExitCode
}
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'native-desktop-verification.json') -Encoding UTF8
