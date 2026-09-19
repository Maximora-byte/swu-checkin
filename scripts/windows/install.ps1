[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "SWUCheckin.Windows.psm1") -Force
if (-not (Test-SWUCheckinWindows)) {
    throw "This installer supports Windows only."
}

$installRoot = Get-SWUCheckinInstallRoot
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venvRoot = Join-Path $installRoot ".venv"
$swuCheckinExe = Join-Path $venvRoot "Scripts\swu-checkin.exe"
$configPath = Join-Path $installRoot "config.json"
$passwordPath = Join-Path $installRoot "password.dpapi"
$statusPath = Join-Path $installRoot "status.json"
$uvVersion = "0.12.15"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$CommandArguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )
    & $Executable @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Get-UvExecutable {
    $existing = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        return $existing.Source
    }

    $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    switch ($architecture) {
        "X64" { $target = "x86_64-pc-windows-msvc" }
        "Arm64" { $target = "aarch64-pc-windows-msvc" }
        default { throw "Unsupported Windows architecture for uv: $architecture" }
    }

    $binRoot = Join-Path $installRoot "bin"
    $downloadRoot = Join-Path $installRoot ".download"
    New-Item -ItemType Directory -Force -Path $binRoot, $downloadRoot | Out-Null
    $archiveName = "uv-$target.zip"
    $archivePath = Join-Path $downloadRoot $archiveName
    $checksumPath = "$archivePath.sha256"
    $releaseBase = "https://github.com/astral-sh/uv/releases/download/$uvVersion"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$releaseBase/$archiveName" -OutFile $archivePath
        Invoke-WebRequest -UseBasicParsing -Uri "$releaseBase/$archiveName.sha256" -OutFile $checksumPath
    }
    catch {
        throw "Failed to download uv $uvVersion from the official Astral GitHub release: $($_.Exception.Message)"
    }

    $expectedLine = (Get-Content -LiteralPath $checksumPath -Raw).Trim()
    if ($expectedLine -notmatch '^(?<hash>[0-9a-fA-F]{64})(?:\s+.+)?$') {
        throw "The official uv checksum file has an unexpected format."
    }
    $expectedHash = $Matches.hash.ToUpperInvariant()
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToUpperInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "uv archive checksum verification failed."
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $binRoot -Force
    $uvExecutable = Join-Path $binRoot "uv.exe"
    if (-not (Test-Path -LiteralPath $uvExecutable -PathType Leaf)) {
        throw "The verified uv archive did not contain uv.exe."
    }
    return $uvExecutable
}

New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
$uvExecutable = Get-UvExecutable
Invoke-CheckedCommand -Executable $uvExecutable -CommandArguments @("python", "install", "3.13") -FailureMessage "Python 3.13 installation failed"
$previousProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = $venvRoot
    $syncArguments = Get-SWUCheckinLockedSyncArguments -RepositoryRoot $repositoryRoot
    Invoke-CheckedCommand -Executable $uvExecutable -CommandArguments $syncArguments -FailureMessage "Locked swu-checkin installation failed"
}
finally {
    if ($null -eq $previousProjectEnvironment) {
        Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    }
    else {
        $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
    }
}

Copy-Item -Force -LiteralPath (Join-Path $PSScriptRoot "SWUCheckin.Windows.psm1") -Destination $installRoot
Copy-Item -Force -LiteralPath (Join-Path $PSScriptRoot "run.ps1") -Destination $installRoot
Copy-Item -Force -LiteralPath (Join-Path $PSScriptRoot "uninstall.ps1") -Destination $installRoot

$username = (Read-Host "SWU campus username").Trim()
if ([string]::IsNullOrWhiteSpace($username)) {
    throw "Username cannot be empty."
}
$password = Read-Host "SWU campus password" -AsSecureString
if ($password.Length -eq 0) {
    throw "Password cannot be empty."
}

@{
    schema_version = 1
    username = $username
    status_file = $statusPath
} | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
ConvertFrom-SecureString -SecureString $password | Set-Content -LiteralPath $passwordPath -Encoding ASCII

$powerShellPath = (Get-Process -Id $PID).Path
$taskSpecs = Get-SWUCheckinTaskSpecs -InstallRoot $installRoot -PowerShellPath $powerShellPath
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value

$removeTasks = { Remove-SWUCheckinScheduledTasks }
$installTasks = {
    Sync-SWUCheckinScheduledTasks -Specs $taskSpecs -RegisterAction {
        param($Spec)
        $xml = ConvertTo-SWUCheckinTaskXml -Spec $Spec -UserSid $currentSid -WorkingDirectory $installRoot
        Register-ScheduledTask -TaskName $Spec.Name -Xml $xml -Force | Out-Null
    }
}
$doctor = {
    return Invoke-SWUCheckinProcess -ExecutablePath $swuCheckinExe -Arguments @("doctor") -Username $username -Password $password
}

try {
    Invoke-SWUCheckinDoctorGate -DoctorAction $doctor -InstallTasksAction $installTasks -RemoveTasksAction $removeTasks
}
finally {
    if ($null -ne $password) {
        $password.Dispose()
    }
    $password = $null
}

Write-Host "Installation completed. Scheduled tasks run daily at 21:15 and 21:45 Beijing time."
Write-Host "DPAPI credentials can only be decrypted by the same Windows user on this machine."
