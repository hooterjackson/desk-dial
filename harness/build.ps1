param([string]$OutputDirectory = "$PSScriptRoot/rendered")
$ErrorActionPreference = 'Stop'
$python = "$PSScriptRoot/../../app/.venv/Scripts/python.exe"
& $python "$PSScriptRoot/build.py" $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'LVGL host build/render failed.' }
