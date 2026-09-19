[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "SWUCheckin.Windows.psm1") -Force
if (-not (Test-SWUCheckinWindows)) {
    throw "This runner supports Windows only."
}

$configPath = Join-Path $PSScriptRoot "config.json"
$passwordPath = Join-Path $PSScriptRoot "password.dpapi"
$executablePath = Join-Path $PSScriptRoot ".venv\Scripts\swu-checkin.exe"
foreach ($requiredPath in @($configPath, $passwordPath, $executablePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required installation file is missing: $requiredPath"
    }
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($config.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace([string]$config.username)) {
    throw "The local configuration file is invalid."
}
$password = Get-Content -LiteralPath $passwordPath -Raw | ConvertTo-SecureString
$exitCode = 1
try {
    $exitCode = Invoke-SWUCheckinProcess `
        -ExecutablePath $executablePath `
        -Arguments @("run", "--json") `
        -Username ([string]$config.username) `
        -Password $password `
        -StatusFile ([string]$config.status_file)
}
finally {
    if ($null -ne $password) {
        $password.Dispose()
    }
    $password = $null
}
exit $exitCode
