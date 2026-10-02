#requires -Version 7.0
[CmdletBinding()]
param([string]$Archive)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Never run acceptance against a person's desktop or persistent/self-hosted CI.
if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or
    $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:ImageOS -ne 'win22' -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw 'Portable smoke requires a disposable GitHub-hosted windows-2022 runner.'
}
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($Archive)) {
    $Candidates = @(Get-ChildItem -LiteralPath (Join-Path $Root 'dist\windows') -Filter '*-win-x64-Portable.zip' -File)
    if ($Candidates.Count -ne 1) { throw 'Expected exactly one freshly built portable ZIP.' }
    $Archive = $Candidates[0].FullName
}
$Archive = (Resolve-Path -LiteralPath $Archive).Path
$ArchiveName = [IO.Path]::GetFileName($Archive)
if ($ArchiveName -notmatch '^SWUCheckin-\d+\.\d+\.\d+-win-x64-Portable\.zip$') {
    throw 'Unexpected portable archive filename.'
}

function Assert-SafeRelativePath([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name.Contains('\') -or $Name.Contains(':') -or
        [IO.Path]::IsPathRooted($Name) -or $Name.IndexOf([char]0) -ge 0) {
        throw "Unsafe relative payload path: $Name"
    }
    foreach ($Part in $Name.Split('/')) {
        if ($Part -in @('', '.', '..') -or $Part.EndsWith('.') -or $Part.EndsWith(' ')) {
            throw "Unsafe relative payload path: $Name"
        }
    }
}
function Read-ChecksumManifest([string]$Path) {
    $Hashes = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($Line in [IO.File]::ReadAllLines($Path)) {
        if ($Line -notmatch '^([a-fA-F0-9]{64})  (.+)$') { throw 'Malformed SHA256 manifest entry.' }
        $Hash = $Matches[1]
        $Name = $Matches[2]
        Assert-SafeRelativePath $Name
        if (-not $Hashes.TryAdd($Name, $Hash)) { throw "Duplicate manifest path: $Name" }
    }
    if ($Hashes.Count -eq 0) { throw 'Checksum manifest is empty.' }
    return ,$Hashes
}
function Assert-PayloadChecksums([string]$Directory) {
    $Manifest = Join-Path $Directory 'SHA256SUMS.txt'
    $Hashes = Read-ChecksumManifest $Manifest
    if ($Hashes.ContainsKey('SHA256SUMS.txt')) { throw 'Payload manifest must not hash itself.' }
    $Files = @(Get-ChildItem -LiteralPath $Directory -Recurse -Force -File |
        Where-Object { $_.FullName -ne $Manifest })
    if ($Files.Count -ne $Hashes.Count) { throw 'Payload file count differs from its manifest.' }
    foreach ($File in $Files) {
        $Name = [IO.Path]::GetRelativePath($Directory, $File.FullName).Replace('\', '/')
        if (-not $Hashes.ContainsKey($Name) -or
            (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash -ne $Hashes[$Name]) {
            throw "Missing or incorrect payload checksum: $Name"
        }
    }
}
function Get-PayloadSnapshot([string]$Directory) {
    # Include empty directories, metadata and the manifest itself, which cannot
    # be included in its own checksum list. No extracted payload may mutate.
    $Snapshot = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($Entry in @((Get-Item -LiteralPath $Directory)) + @(Get-ChildItem -LiteralPath $Directory -Recurse -Force)) {
        if (($Entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse point in extracted payload.' }
        $Name = [IO.Path]::GetRelativePath($Directory, $Entry.FullName)
        $Hash = if ($Entry.PSIsContainer) { 'directory' } else { (Get-FileHash -LiteralPath $Entry.FullName -Algorithm SHA256).Hash }
        $Snapshot.Add($Name, "$Hash|$($Entry.LastWriteTimeUtc.Ticks)|$($Entry.Attributes)")
    }
    return ,$Snapshot
}
function Assert-UnchangedPayload($Before, [string]$Directory) {
    $After = Get-PayloadSnapshot $Directory
    if ($Before.Count -ne $After.Count) { throw 'Portable application added or removed a payload entry.' }
    foreach ($Name in $Before.Keys) {
        if (-not $After.ContainsKey($Name) -or $Before[$Name] -ne $After[$Name]) {
            throw "Portable application mutated its own directory: $Name"
        }
    }
}
function Assert-NoDesktopTasks {
    # Read-only enumeration distinguishes definite absence from query failure.
    $Tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
        Where-Object { $_.TaskName -like 'SWUCheckin*' })
    if ($Tasks.Count -ne 0) { throw 'An SWUCheckin task exists; refusing to alter or rely on an existing task.' }
}
function Assert-NoInstallation {
    foreach ($Key in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C5B931AB-AF09-44E4-877C-4C60C4F1B419}_is1',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C5B931AB-AF09-44E4-877C-4C60C4F1B419}_is1',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{C5B931AB-AF09-44E4-877C-4C60C4F1B419}_is1'
    )) {
        if (Test-Path -LiteralPath $Key) { throw 'An SWU Checkin uninstall registration exists.' }
    }
    foreach ($Folder in @('Programs', 'CommonPrograms', 'DesktopDirectory', 'CommonDesktopDirectory')) {
        $Location = [Environment]::GetFolderPath([Environment+SpecialFolder]$Folder)
        if ($Location -and (Test-Path -LiteralPath (Join-Path $Location 'SWU Checkin.lnk'))) {
            throw 'An SWU Checkin shortcut exists.'
        }
    }
    if (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\SWUCheckin')) {
        throw 'An installed SWU Checkin application directory exists.'
    }
}
Assert-NoDesktopTasks
Assert-NoInstallation
if (@(Get-Process -Name 'SWUCheckin' -ErrorAction SilentlyContinue).Count -ne 0) {
    throw 'An existing SWUCheckin process was found; refusing to interact with it.'
}

# The distribution manifest authenticates the ZIP against this build's output,
# not against a trusted publisher. The preview binaries remain unsigned.
$DistributionHashes = Read-ChecksumManifest (Join-Path ([IO.Path]::GetDirectoryName($Archive)) 'SHA256SUMS.txt')
if (-not $DistributionHashes.ContainsKey($ArchiveName) -or
    (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $DistributionHashes[$ArchiveName]) {
    throw 'Portable archive SHA256 does not match the distribution manifest.'
}
$Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
try {
    $Entries = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($Entry in $Zip.Entries) {
        $Name = $Entry.FullName.TrimEnd('/')
        Assert-SafeRelativePath $Name
        if (($Name -cne 'SWUCheckin' -and -not $Name.StartsWith('SWUCheckin/', [StringComparison]::Ordinal)) -or
            -not $Entries.Add($Name) -or (($Entry.ExternalAttributes -shr 16) -band 0xf000) -eq 0xa000) {
            throw 'ZIP must contain exactly one SWUCheckin root, safe unique paths and no symlinks.'
        }
        if ($Name -ceq 'SWUCheckin' -and -not $Entry.FullName.EndsWith('/')) { throw 'ZIP root is not a directory.' }
    }
    if ($Entries.Count -eq 0) { throw 'Portable ZIP is empty.' }
}
finally { $Zip.Dispose() }

$Sandbox = Join-Path (Resolve-Path -LiteralPath $env:RUNNER_TEMP).Path ('swu-portable-' + [Guid]::NewGuid().ToString('N'))
$ExtractDir = Join-Path $Sandbox 'Portable 中文路径 with spaces'
$AppDir = Join-Path $ExtractDir 'SWUCheckin'
$ProfileDir = Join-Path $Sandbox 'Isolated Profile'
$LocalData = Join-Path $ProfileDir 'Local'
$RoamingData = Join-Path $ProfileDir 'Roaming'
$TempDir = Join-Path $Sandbox 'Temporary files'
$WorkingDir = Join-Path $Sandbox 'Unrelated working directory'
$OwnedProcesses = [Collections.Generic.List[Diagnostics.Process]]::new()
$Launcher = $null
New-Item -ItemType Directory -Path $Sandbox, $ExtractDir, $ProfileDir, $LocalData, $RoamingData, $TempDir, $WorkingDir | Out-Null

function Start-OwnedProcess([string]$Argument = '') {
    $Environment = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($Entry in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) {
        # Erase interpreter/venv, package manager and app configuration hints.
        if ($Entry.Key -match '^(PYTHON|UV_|VIRTUAL_ENV|CONDA|SWUDK_|_PYI_|PYINSTALLER)') { continue }
        $Environment[$Entry.Key] = $Entry.Value
    }
    $Environment['PATH'] = "$env:SystemRoot\System32;$env:SystemRoot"
    $Environment['LOCALAPPDATA'] = $LocalData
    $Environment['APPDATA'] = $RoamingData
    $Environment['USERPROFILE'] = $ProfileDir
    $Environment['HOME'] = $ProfileDir
    $Environment['HOMEDRIVE'] = [IO.Path]::GetPathRoot($ProfileDir).TrimEnd('\')
    $Environment['HOMEPATH'] = $ProfileDir.Substring($Environment['HOMEDRIVE'].Length)
    $Environment['TEMP'] = $TempDir
    $Environment['TMP'] = $TempDir
    $Process = $Launcher.Start((Join-Path $AppDir 'SWUCheckin.exe'), $Argument, $WorkingDir, $Environment)
    $OwnedProcesses.Add($Process)
    return $Process
}
function Wait-OwnedProcess([Diagnostics.Process]$Process, [int]$Seconds, [string]$Label) {
    if (-not $Process.WaitForExit($Seconds * 1000)) { throw "$Label timed out." }
    $Process.Refresh()
    if ($Process.ExitCode -ne 0) { throw "$Label failed with exit code $($Process.ExitCode)." }
    # The job sees all descendants, including subprocesses whose parent exited.
    $Deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ($Launcher.ActiveProcesses -ne 0 -and [DateTime]::UtcNow -lt $Deadline) { Start-Sleep -Milliseconds 100 }
    if ($Launcher.ActiveProcesses -ne 0) { throw "$Label left an owned descendant running." }
    Write-Host "$Label passed under a verified restricted token."
}

try {
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $ExtractDir)
    foreach ($Name in @('SWUCheckin.exe', 'README-PORTABLE.txt', 'BUILD-INFO.json', 'TOOLCHAIN.txt', 'SHA256SUMS.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $AppDir $Name) -PathType Leaf)) { throw "Portable ZIP is missing $Name." }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $AppDir '_internal') -PathType Container)) { throw 'Portable runtime is missing.' }
    Assert-PayloadChecksums $AppDir
    $Before = Get-PayloadSnapshot $AppDir
    Add-Type -Path (Join-Path $Root 'packaging\windows\portable_smoke_launcher.cs')
    $Launcher = [PortableSmokeLauncher]::new()
    Write-Host 'Restricted-token verification: same CI user, Administrators SID deny-only/absent, all non-traversal privileges removed.'
    Write-Host 'This does not substitute for a separate standard-user account or Windows 10/11 release qualification.'

    $SelfTest = Start-OwnedProcess '--self-test'
    Wait-OwnedProcess $SelfTest 180 'Extracted portable offline self-test'
    foreach ($Launch in 1..2) {
        # No arguments is the real double-click entry point. Never click controls,
        # populate credentials, invoke scheduled mode or contact school services.
        $Gui = Start-OwnedProcess
        $Deadline = [DateTime]::UtcNow.AddSeconds(60)
        $WindowReady = $false
        while ([DateTime]::UtcNow -lt $Deadline) {
            $Gui.Refresh()
            if ($Gui.HasExited) { throw 'Default portable GUI exited before presenting its window.' }
            if ($Gui.MainWindowHandle -ne [IntPtr]::Zero -and $Gui.Responding -and
                $Gui.MainWindowTitle -eq '西南大学寝室签到助手') {
                $WindowReady = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $WindowReady) { throw 'Responsive portable application window was not observed.' }
        # The startup read-only scheduler query can take 30 seconds; waiting
        # past its bound avoids deliberately triggering the busy-close dialog.
        Start-Sleep -Seconds 32
        $Gui.Refresh()
        if ($Gui.HasExited -or -not $Gui.Responding) { throw 'Portable GUI stopped responding after startup.' }
        if (-not $Gui.CloseMainWindow()) { throw 'Portable GUI did not accept a normal close request.' }
        Wait-OwnedProcess $Gui 30 "Portable GUI launch $Launch graceful close"
        Assert-NoDesktopTasks
        Assert-NoInstallation
        Assert-UnchangedPayload $Before $AppDir
    }
    if (@(Get-ChildItem -LiteralPath $ProfileDir -Recurse -Force -File).Count -ne 0) {
        throw 'Portable startup unexpectedly persisted user data or saved credentials.'
    }
    if (@(Get-ChildItem -LiteralPath $WorkingDir -Recurse -Force).Count -ne 0) {
        throw 'Portable startup unexpectedly wrote into the unrelated working directory.'
    }
    foreach ($Process in $OwnedProcesses) {
        $Process.Refresh()
        if (-not $Process.HasExited) { throw 'An owned portable process remained running.' }
    }
    if ($Launcher.ActiveProcesses -ne 0) { throw 'An owned portable descendant remained running.' }
    Assert-PayloadChecksums $AppDir
    Assert-UnchangedPayload $Before $AppDir
    Assert-NoDesktopTasks
    Assert-NoInstallation
    Write-Host 'Portable smoke passed: archive and complete payload hashes, Unicode/spaces extraction, restricted-token offline self-test, GUI close/relaunch/close, system-only PATH, no installed dependency, saved data, application tasks, registrations, payload changes or owned processes.'
}
finally {
    # The private kill-on-close job contains only this invocation's processes.
    # Never kill by process name, remove tasks, uninstall software or edit HKCU.
    if ($null -ne $Launcher) { $Launcher.Dispose() }
    foreach ($Process in $OwnedProcesses) {
        try { $Process.WaitForExit(10000) | Out-Null }
        finally { $Process.Dispose() }
    }
    Remove-Item -LiteralPath $Sandbox -Recurse -Force
}
