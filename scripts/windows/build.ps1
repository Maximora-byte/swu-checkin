[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build on Windows x64; PyInstaller does not cross-compile.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Build = Join-Path $Root 'build\windows'
$Dist = Join-Path $Root 'dist\windows'
$Metadata = Join-Path $Build 'metadata'
$SavedEnvironment = @{}
foreach ($Name in @('UV_PROJECT_ENVIRONMENT', 'PYTHONHASHSEED', 'SOURCE_DATE_EPOCH')) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
}

function Assert-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}

Push-Location $Root
try {
    $UvVersion = (& uv --version)
    Assert-Exit 'uv version check'
    if ($UvVersion -notmatch '^uv 0\.12\.15(?:\s|$)') { throw 'Install uv 0.12.15 before building.' }
    $PythonPath = (& $Python -c 'import sys; print(sys.executable)')
    Assert-Exit 'Python resolution'
    & $PythonPath -c 'import struct, sys, tkinter; assert sys.version_info[:2] == (3, 13); assert struct.calcsize("P") == 8; tkinter.Tcl()'
    Assert-Exit 'Python 3.13 x64 / Tcl check'
    if (-not (Test-Path -LiteralPath $Iscc -PathType Leaf)) { throw 'Install Inno Setup 6.7.3, or pass -Iscc with its ISCC.exe path.' }
    $InnoVersion = (Get-Item -LiteralPath $Iscc).VersionInfo.FileVersion
    if ($InnoVersion -notmatch '^6\.7\.3(?:[.\s]|$)') { throw "Expected Inno Setup 6.7.3; found $InnoVersion." }
    $Epoch = (& git log -1 --format=%ct)
    Assert-Exit 'Source timestamp lookup'
    $env:SOURCE_DATE_EPOCH = $Epoch
    $env:PYTHONHASHSEED = '0'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $Build 'venv'
    New-Item -ItemType Directory -Force -Path $Build | Out-Null
    # uv validates uv.lock against pyproject.toml and never rewrites the lock.
    & uv sync --locked --no-dev --no-editable --python $PythonPath
    Assert-Exit 'Locked production dependency installation'
    $BuildPython = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\python.exe'
    # Build-only requirements are separate from the application's lock. packaging
    # is already installed from uv.lock; --no-deps prevents silently changing it.
    & uv pip install --python $BuildPython --no-deps `
        'pyinstaller==6.16.0' 'pyinstaller-hooks-contrib==2025.9' `
        'altgraph==0.17.4' 'pefile==2023.2.7' 'pywin32-ctypes==0.2.3' 'setuptools==80.9.0'
    Assert-Exit 'Pinned build tool installation'
    & uv pip check --python $BuildPython
    Assert-Exit 'Build environment dependency check'
    if (Test-Path -LiteralPath $Metadata) { Remove-Item -LiteralPath $Metadata -Recurse -Force }
    & $BuildPython packaging/windows/build_metadata.py metadata $Root $Metadata
    Assert-Exit 'Build provenance generation'
    [IO.File]::WriteAllText((Join-Path $Metadata 'TOOLCHAIN.txt'), "${UvVersion}`nInno Setup ${InnoVersion}`nSOURCE_DATE_EPOCH=${Epoch}`n", [Text.UTF8Encoding]::new($false))
    $Version = (& $BuildPython -c 'from importlib.metadata import version; print(version("swu-checkin"))')
    Assert-Exit 'Application version lookup'
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Installer requires a numeric major.minor.patch application version.' }
    # Remove old outputs so checksums cannot accidentally describe stale installers.
    if (Test-Path -LiteralPath $Dist) { Remove-Item -LiteralPath $Dist -Recurse -Force }
    & $BuildPython -m PyInstaller --noconfirm --clean --distpath $Dist `
        --workpath (Join-Path $Build 'pyinstaller') packaging/windows/swu-checkin.spec
    Assert-Exit 'PyInstaller build'
    $App = Join-Path $Dist 'SWUCheckin\SWUCheckin.exe'
    if (-not (Test-Path -LiteralPath $App -PathType Leaf)) { throw 'Frozen application was not produced.' }
    # Start-Process -PassThru avoids the windowed-executable asynchronous exit-code
    # behavior of PowerShell. This exercises only synthetic offline resources.
    $Smoke = Start-Process -FilePath $App -ArgumentList '--self-test' -PassThru
    if (-not $Smoke.WaitForExit(180000)) {
        $Smoke.Kill()
        throw 'Frozen offline self-test timed out.'
    }
    $Smoke.Refresh()
    if ($Smoke.ExitCode -ne 0) { throw "Frozen offline self-test failed (exit $($Smoke.ExitCode))." }
    & $BuildPython packaging/windows/build_metadata.py manifest `
        (Join-Path $Dist 'SWUCheckin') (Join-Path $Dist 'SWUCheckin\SHA256SUMS.txt')
    Assert-Exit 'Application checksum manifest'
    & $Iscc "/DAppVersion=$Version" "/DSourceRoot=$Root" "/DOutputRoot=$Dist" packaging/windows/installer.iss
    Assert-Exit 'Inno Setup compilation'
    $Installer = Join-Path $Dist "SWUCheckin-$Version-win-x64-Setup.exe"
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw 'Installer was not produced.' }
    Copy-Item -LiteralPath (Join-Path $Metadata 'BUILD-INFO.json') -Destination $Dist
    Copy-Item -LiteralPath (Join-Path $Metadata 'TOOLCHAIN.txt') -Destination $Dist
    & $BuildPython packaging/windows/build_metadata.py manifest $Dist (Join-Path $Dist 'SHA256SUMS.txt')
    Assert-Exit 'Distribution checksum manifest'
    Write-Host "Built and offline-smoke-tested: $Installer"
    Write-Host 'The installer is unsigned. No installation, account request, task registration or release was performed.'
}
finally {
    foreach ($Name in $SavedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], 'Process')
    }
    Pop-Location
}
