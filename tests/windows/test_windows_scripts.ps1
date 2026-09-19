$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scriptsRoot = Join-Path $repositoryRoot "scripts\windows"
$modulePath = Join-Path $scriptsRoot "SWUCheckin.Windows.psm1"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Equal {
    param($Expected, $Actual, [string]$Message)
    if ($Expected -ne $Actual) { throw "$Message Expected '$Expected', got '$Actual'." }
}

foreach ($path in Get-ChildItem -LiteralPath $scriptsRoot -File | Where-Object { $_.Extension -in @(".ps1", ".psm1") }) {
    $tokens = $null
    $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($path.FullName, [ref]$tokens, [ref]$errors)
    Assert-Equal 0 $errors.Count "PowerShell syntax errors in $($path.Name)."
}

Import-Module $modulePath -Force

if (-not (Test-SWUCheckinWindows)) {
    foreach ($entryPoint in @("install.ps1", "run.ps1", "uninstall.ps1")) {
        $failedFast = $false
        try {
            & (Join-Path $scriptsRoot $entryPoint)
        }
        catch {
            $failedFast = $_.Exception.Message -match "Windows only"
        }
        Assert-True $failedFast "$entryPoint must fail fast outside Windows."
    }
}

$specs = Get-SWUCheckinTaskSpecs -InstallRoot "/tmp/SWUCheckin" -PowerShellPath "powershell.exe"
Assert-Equal 2 $specs.Count "Exactly two task definitions are required."
Assert-Equal 2 (@($specs.Name | Sort-Object -Unique)).Count "Task names must be unique."
Assert-True ((($specs.Arguments -join " ") -notmatch "SWUDK_|password|secret|ticket|captcha")) "Task arguments must not contain credentials."
$taskXml = ConvertTo-SWUCheckinTaskXml -Spec $specs[0] -UserSid "S-1-5-21-1000" -WorkingDirectory "/tmp/SWUCheckin"
Assert-True ($taskXml.Contains("+08:00")) "The task XML must pin the daily start boundary to Beijing time."
Assert-True (-not ($taskXml -match "SWUDK_|password|secret|ticket|captcha")) "Task XML must not contain credentials."

$registered = @{}
$registerAction = {
    param($Spec)
    $registered[$Spec.Name] = $Spec.Arguments
}
Sync-SWUCheckinScheduledTasks -Specs $specs -RegisterAction $registerAction
Sync-SWUCheckinScheduledTasks -Specs $specs -RegisterAction $registerAction
Assert-Equal 2 $registered.Count "Repeated installation must update the same two tasks."

$gateState = @{ Installed = 0; Removed = 0 }
$doctorFailed = $false
try {
    Invoke-SWUCheckinDoctorGate `
        -DoctorAction { return 7 } `
        -InstallTasksAction { $gateState.Installed += 1 } `
        -RemoveTasksAction { $gateState.Removed += 1 }
}
catch {
    $doctorFailed = $true
}
Assert-True $doctorFailed "A failed doctor check must stop installation."
Assert-Equal 0 $gateState.Installed "A failed doctor check must not install tasks."
Assert-Equal 1 $gateState.Removed "A failed doctor check must remove project tasks."

$securePassword = ConvertTo-SecureString "sensitive-test-value" -AsPlainText -Force
$parentUsername = $env:SWUDK_USERNAME
$parentPassword = $env:SWUDK_PASSWORD
$observed = @{}
$runOutput = @(
    Invoke-SWUCheckinProcess `
        -ExecutablePath "C:\fake\swu-checkin.exe" `
        -Arguments @("run", "--json") `
        -Username "student-test-user" `
        -Password $securePassword `
        -StatusFile "C:\fake\status.json" `
        -ProcessRunner {
            param($Executable, $Arguments, $Environment)
            $observed.Clear()
            foreach ($name in $Environment.Keys) { $observed[$name] = $Environment[$name] }
            return 37
        }
)
Assert-Equal 37 $runOutput[-1] "The runner must preserve the child exit code."
Assert-Equal "student-test-user" $observed["SWUDK_USERNAME"] "The child must receive the username through its private environment."
Assert-Equal "sensitive-test-value" $observed["SWUDK_PASSWORD"] "The child must receive the decrypted DPAPI value only through its private environment."
Assert-Equal $parentUsername $env:SWUDK_USERNAME "The parent username environment must not be changed."
Assert-Equal $parentPassword $env:SWUDK_PASSWORD "The parent password environment must not be changed."
$renderedOutput = $runOutput -join "`n"
Assert-True (-not $renderedOutput.Contains("student-test-user")) "The username must not enter command output."
Assert-True (-not $renderedOutput.Contains("sensitive-test-value")) "The password must not enter command output."

$removed = [Collections.ArrayList]::new()
Remove-SWUCheckinScheduledTasks -RemoveAction { param($TaskName) [void]$removed.Add($TaskName) }
$expectedNames = @(Get-SWUCheckinTaskNames)
Assert-Equal 2 $removed.Count "Uninstall must remove exactly the two project tasks."
Assert-Equal (($expectedNames | Sort-Object) -join ",") (($removed | Sort-Object) -join ",") "Uninstall must only target project task names."
Assert-True (-not ($removed -contains "Unrelated-Task")) "Uninstall must not target unrelated tasks."

$oldLocalAppData = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = "/tmp/LocalAppData"
    Assert-Equal "/tmp/LocalAppData/SWUCheckin" (Get-SWUCheckinInstallRoot) "The install root must stay scoped to LocalAppData."
}
finally {
    $env:LOCALAPPDATA = $oldLocalAppData
}

$boundary = Get-SWUCheckinBeijingStartBoundary -Hour 21 -Minute 15 -Now ([DateTimeOffset]::Parse("2026-09-19T22:00:00+08:00"))
Assert-Equal "2026-09-20T21:15:00+08:00" $boundary "Task boundaries must use Beijing time."

$uninstallSource = Get-Content -LiteralPath (Join-Path $scriptsRoot "uninstall.ps1") -Raw
Assert-True ($uninstallSource.Contains('Remove-Item -LiteralPath $installRoot')) "Uninstall must remove only the resolved project root."
Assert-True (-not ($uninstallSource -match 'uv\s+(tool\s+)?uninstall|python\s+uninstall')) "Uninstall must leave uv and Python untouched."
$installSource = Get-Content -LiteralPath (Join-Path $scriptsRoot "install.ps1") -Raw
Assert-True (-not ($installSource -match 'Invoke-Expression|\biex\b')) "Install must not execute downloaded source."
Assert-True ($installSource.Contains("ConvertFrom-SecureString -SecureString `$password")) "Install must persist the password only as DPAPI ciphertext."
Assert-True (-not ($installSource -match 'SWUDK_PASSWORD\s*=|password\s*=\s*\$password')) "Install must not serialize the plaintext password."

Write-Host "Windows PowerShell checks passed."
