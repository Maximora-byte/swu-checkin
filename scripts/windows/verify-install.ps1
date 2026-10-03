#requires -Version 7.0
[CmdletBinding()]
param([string]$Installer)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# This installs/uninstalls software in HKCU and must never run against a person's
# desktop or a persistent/self-hosted agent. Only disposable hosted CI is allowed.
if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or
    $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw 'Installer smoke requires a disposable GitHub-hosted Windows runner.'
}
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$BuildPython = Join-Path $Root 'build\windows\venv\Scripts\python.exe'
$BuildInfo = Get-Content -LiteralPath (Join-Path $Root 'dist\windows\BUILD-INFO.json') -Raw | ConvertFrom-Json
& $BuildPython (Join-Path $Root 'packaging\windows\task_scheduler_smoke.py')
if ($LASTEXITCODE -ne 0) { throw 'Harmless Task Scheduler registration smoke failed.' }
if ([string]::IsNullOrWhiteSpace($Installer)) {
    $Candidates = @(Get-ChildItem -LiteralPath (Join-Path $Root 'dist\windows') -Filter '*-win-x64-Setup.exe' -File)
    if ($Candidates.Count -ne 1) { throw 'Expected exactly one freshly built Windows installer.' }
    $Installer = $Candidates[0].FullName
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$TaskName = 'SWUCheckin-Desktop'
$RegistryKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C5B931AB-AF09-44E4-877C-4C60C4F1B419}_is1',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C5B931AB-AF09-44E4-877C-4C60C4F1B419}_is1',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{C5B931AB-AF09-44E4-877C-4C60C4F1B419}_is1'
)
$Shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'SWU Checkin.lnk'

function Assert-NoDesktopTask {
    # Enumerating the root folder distinguishes "absent" from scheduler failure.
    $Tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName })
    if ($Tasks.Count -ne 0) { throw 'SWUCheckin-Desktop task exists; refusing to touch an existing task.' }
}
function Assert-NoInstallation {
    foreach ($Key in $RegistryKeys) {
        if (Test-Path -LiteralPath $Key) { throw 'An existing SWU Checkin uninstall registration was found.' }
    }
    if (Test-Path -LiteralPath $Shortcut) { throw 'An existing SWU Checkin Start Menu shortcut was found.' }
}
Assert-NoDesktopTask
Assert-NoInstallation
if (@(Get-Process -Name 'SWUCheckin' -ErrorAction SilentlyContinue).Count -ne 0) {
    throw 'An existing SWUCheckin process was found; refusing to interact with it.'
}

$Sandbox = Join-Path (Resolve-Path -LiteralPath $env:RUNNER_TEMP).Path ('swu-install-smoke-' + [Guid]::NewGuid().ToString('N'))
$InstallDir = Join-Path $Sandbox 'Installed App'
$ProfileDir = Join-Path $Sandbox 'Isolated Profile'
$Uninstaller = Join-Path $InstallDir 'unins000.exe'
$OwnedProcesses = [Collections.Generic.List[Diagnostics.Process]]::new()
New-Item -ItemType Directory -Path $Sandbox, $ProfileDir | Out-Null

function Start-OwnedProcess([string]$Executable, [string[]]$Arguments = @()) {
    $StartInfo = [Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $Executable
    $StartInfo.UseShellExecute = $false
    $StartInfo.WorkingDirectory = $Sandbox
    $StartInfo.Environment['LOCALAPPDATA'] = $ProfileDir
    # No interpreter/toolchain discovery: the installed bundle must stand alone.
    $StartInfo.Environment['PATH'] = "$env:SystemRoot\System32;$env:SystemRoot"
    foreach ($Name in @('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT')) {
        $StartInfo.Environment.Remove($Name) | Out-Null
    }
    foreach ($Name in @($StartInfo.Environment.Keys)) {
        if ($Name -like 'SWUDK_*') { $StartInfo.Environment.Remove($Name) | Out-Null }
    }
    foreach ($Argument in $Arguments) { $StartInfo.ArgumentList.Add($Argument) }
    $Process = [Diagnostics.Process]::Start($StartInfo)
    $OwnedProcesses.Add($Process)
    return $Process
}
function Wait-OwnedProcess([Diagnostics.Process]$Process, [int]$Seconds, [string]$Label) {
    $Timer = [Diagnostics.Stopwatch]::StartNew()
    if (-not $Process.WaitForExit($Seconds * 1000)) {
        $Process.Kill($true)
        $Process.WaitForExit(10000) | Out-Null
        throw "$Label timed out."
    }
    $Process.Refresh()
    if ($Process.ExitCode -ne 0) { throw "$Label failed with exit code $($Process.ExitCode)." }
    Write-Host ("{0} passed in {1:N2} seconds." -f $Label, $Timer.Elapsed.TotalSeconds)
}
function Invoke-OwnedUninstall {
    if (Test-Path -LiteralPath $Uninstaller -PathType Leaf) {
        $Process = Start-OwnedProcess $Uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
        Wait-OwnedProcess $Process 120 'Uninstall'
    }
}

try {
    $Setup = Start-OwnedProcess $Installer @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', '/TASKS=', "/DIR=$InstallDir")
    Wait-OwnedProcess $Setup 180 'Installation'
    $App = Join-Path $InstallDir 'SWUCheckin.exe'
    if (-not (Test-Path -LiteralPath $App -PathType Leaf) -or
        -not (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) {
        throw 'Installer did not create the application and uninstaller at the isolated target.'
    }
    Assert-NoDesktopTask

    $Registration = Get-ItemProperty -LiteralPath $RegistryKeys[0]
    if ($Registration.Publisher -ne 'MatchAll' -or $Registration.DisplayVersion -ne $BuildInfo.application_version) {
        throw 'Installed publisher or version metadata mismatch.'
    }
    $SelfTest = Start-OwnedProcess $App @('--self-test')
    Wait-OwnedProcess $SelfTest 180 'Installed offline self-test including definite-absent local task query'

    # No arguments is the real double-click entry point. No controls are clicked,
    # no credentials are populated and --scheduled is never executed.
    foreach ($Launch in 1..2) {
        $Gui = Start-OwnedProcess $App
        $Deadline = [DateTime]::UtcNow.AddSeconds(60)
        $WindowReady = $false
        while ([DateTime]::UtcNow -lt $Deadline) {
            $Gui.Refresh()
            if ($Gui.HasExited) { throw 'The default GUI exited before presenting its window.' }
            if ($Gui.MainWindowHandle -ne [IntPtr]::Zero -and $Gui.Responding -and
                $Gui.MainWindowTitle -eq "SWU 查寝 $($BuildInfo.application_version) · MatchAll") {
                $WindowReady = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $WindowReady) { throw 'A responsive default application window was not observed.' }
        # The read-only task query has a 30-second subprocess bound. Wait past
        # that boundary plus the GUI queue poll; closing sooner deliberately
        # opens the busy-operation warning, which is not an app hang.
        Start-Sleep -Seconds 32
        $Gui.Refresh()
        if ($Gui.HasExited -or -not $Gui.Responding) { throw 'GUI stopped responding after startup.' }
        if (-not $Gui.CloseMainWindow()) { throw 'GUI did not accept a normal window close request.' }
        Wait-OwnedProcess $Gui 30 'Graceful GUI close'
    }
    if (Test-Path -LiteralPath (Join-Path $ProfileDir 'SWUCheckin\desktop-credentials.dpapi')) {
        throw 'Smoke test unexpectedly created saved credentials.'
    }
    Assert-NoDesktopTask
    Invoke-OwnedUninstall
    $RemovalDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while ((Test-Path -LiteralPath $Uninstaller) -and [DateTime]::UtcNow -lt $RemovalDeadline) {
        Start-Sleep -Milliseconds 250
    }
    if (Test-Path -LiteralPath $App) { throw 'Application executable remained after uninstall.' }
    if (Test-Path -LiteralPath $Uninstaller) { throw 'Uninstaller remained after uninstall.' }
    if (Test-Path -LiteralPath $InstallDir) {
        if (@(Get-ChildItem -LiteralPath $InstallDir -Recurse -Force -File).Count -ne 0) {
            throw 'Installed files remained after uninstall.'
        }
    }
    if (@(Get-ChildItem -LiteralPath $ProfileDir -Recurse -Force -File).Count -ne 0) {
        throw 'Default startup unexpectedly persisted user data.'
    }
    foreach ($Process in $OwnedProcesses) {
        $Process.Refresh()
        if (-not $Process.HasExited) { throw 'An owned application process remained after uninstall.' }
    }
    Assert-NoDesktopTask
    Assert-NoInstallation
    Write-Host 'Installer smoke passed: isolated install, offline self-test, responsive default GUI, close/reopen/close without Python or uv on PATH, uninstall, no application task or registration left behind.'
}
finally {
    # Never find/kill processes by name: only handles created in this invocation.
    foreach ($Process in $OwnedProcesses) {
        if (-not $Process.HasExited) {
            $Process.Kill($true)
            $Process.WaitForExit(10000) | Out-Null
        }
    }
    try { Invoke-OwnedUninstall }
    catch { Write-Warning "Isolated smoke cleanup failed: $($_.Exception.Message)" }
    # The UUID directory is owned by this invocation. Do not remove the original
    # LOCALAPPDATA, installation roots, registry keys, or any pre-existing files.
    if (-not (Test-Path -LiteralPath $Uninstaller)) {
        Remove-Item -LiteralPath $Sandbox -Recurse -Force
    }
    else { Write-Warning "Leaving failed isolated install for runner disposal: $Sandbox" }
}
