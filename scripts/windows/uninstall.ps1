[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "SWUCheckin.Windows.psm1") -Force
if (-not (Test-SWUCheckinWindows)) {
    throw "This uninstaller supports Windows only."
}

$installRoot = Get-SWUCheckinInstallRoot
Remove-SWUCheckinScheduledTasks
if (Test-Path -LiteralPath $installRoot) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force
}
Write-Host "SWUCheckin scheduled tasks and $installRoot were removed. uv and Python were left untouched."
