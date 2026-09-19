[CmdletBinding()]
param([switch]$WindowsIntegration)

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

$testRoot = Join-Path ([IO.Path]::GetTempPath()) "SWUCheckin-Test"
$specs = @(Get-SWUCheckinTaskSpecs -InstallRoot $testRoot -PowerShellPath "powershell.exe")
Assert-Equal 1 $specs.Count "Exactly one task definition is required."
Assert-Equal "SWUCheckin-Daily" $specs[0].Name "The task must use the fixed project task name."
Assert-Equal 2 @($specs[0].Triggers).Count "The task must contain exactly two triggers."
Assert-True ((($specs[0].Arguments -join " ") -notmatch "SWUDK_|password|secret|ticket|captcha")) "Task arguments must not contain credentials."
$taskXml = ConvertTo-SWUCheckinTaskXml `
    -Spec $specs[0] `
    -UserSid "S-1-5-21-1000" `
    -WorkingDirectory $testRoot `
    -Now ([DateTimeOffset]::Parse("2026-09-19T20:00:00+08:00"))
[xml]$taskDocument = $taskXml
$namespaceManager = New-Object Xml.XmlNamespaceManager($taskDocument.NameTable)
$namespaceManager.AddNamespace("task", "http://schemas.microsoft.com/windows/2004/02/mit/task")
$triggerNodes = $taskDocument.SelectNodes("//task:CalendarTrigger", $namespaceManager)
$startBoundaries = @($triggerNodes | ForEach-Object { $_.StartBoundary })
Assert-Equal 2 $triggerNodes.Count "Task XML must contain exactly two daily triggers."
Assert-True ($startBoundaries -contains "2026-09-19T21:15:00+08:00") "Task XML must contain the 21:15 Beijing trigger."
Assert-True ($startBoundaries -contains "2026-09-19T21:45:00+08:00") "Task XML must contain the 21:45 Beijing trigger."
Assert-Equal "IgnoreNew" $taskDocument.Task.Settings.MultipleInstancesPolicy "The single task must reject overlapping runs."
Assert-True (-not ($taskXml -match "SWUDK_|password|secret|ticket|captcha")) "Task XML must not contain credentials."

$registered = @{}
$registerAction = {
    param($Spec)
    $registered[$Spec.Name] = $Spec.Arguments
}
Sync-SWUCheckinScheduledTasks -Specs $specs -RegisterAction $registerAction
Sync-SWUCheckinScheduledTasks -Specs $specs -RegisterAction $registerAction
Assert-Equal 1 $registered.Count "Repeated installation must update the same task."

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
Assert-Equal "1" $observed["PYTHONUTF8"] "Windows child processes must use UTF-8 output."
Assert-Equal $parentUsername $env:SWUDK_USERNAME "The parent username environment must not be changed."
Assert-Equal $parentPassword $env:SWUDK_PASSWORD "The parent password environment must not be changed."
$renderedOutput = $runOutput -join "`n"
Assert-True (-not $renderedOutput.Contains("student-test-user")) "The username must not enter command output."
Assert-True (-not $renderedOutput.Contains("sensitive-test-value")) "The password must not enter command output."

$removed = New-Object Collections.ArrayList
Remove-SWUCheckinScheduledTasks -RemoveAction { param($TaskName) [void]$removed.Add($TaskName) }
$expectedNames = @(Get-SWUCheckinTaskNames)
Assert-Equal 1 $removed.Count "Uninstall must remove exactly the project task."
Assert-Equal (($expectedNames | Sort-Object) -join ",") (($removed | Sort-Object) -join ",") "Uninstall must only target project task names."
Assert-True (-not ($removed -contains "Unrelated-Task")) "Uninstall must not target unrelated tasks."

$oldLocalAppData = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = Join-Path ([IO.Path]::GetTempPath()) "LocalAppData-Test"
    Assert-Equal (Join-Path $env:LOCALAPPDATA "SWUCheckin") (Get-SWUCheckinInstallRoot) "The install root must stay scoped to LocalAppData."
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
Assert-True (-not ($installSource -match 'uvExecutable.+pip.+install')) "Install must not use an unlocked uv pip install."
$syncArguments = @(Get-SWUCheckinLockedSyncArguments -RepositoryRoot $repositoryRoot)
Assert-Equal "sync" $syncArguments[0] "Installation must use uv project sync."
foreach ($requiredArgument in @("--locked", "--no-dev", "--no-editable", "--project", "--python", "3.13")) {
    Assert-True ($syncArguments -contains $requiredArgument) "Locked installation is missing $requiredArgument."
}
Assert-True ($installSource.Contains('UV_PROJECT_ENVIRONMENT = $venvRoot')) "Locked sync must target the standalone install environment."

if ($WindowsIntegration) {
    Assert-True (Test-SWUCheckinWindows) "Windows integration checks must run on Windows."
    $integrationRoot = Join-Path ([IO.Path]::GetTempPath()) ("swu-checkin-windows-" + [Guid]::NewGuid().ToString("N"))
    $dpapiPath = Join-Path $integrationRoot "credential.dpapi"
    $smokeTaskName = "SWUCheckin-CI-" + [Guid]::NewGuid().ToString("N")
    $secretValue = "dpapi-smoke-" + [Guid]::NewGuid().ToString("N")
    $restoredValue = $null
    $restoredCiphertext = $null
    $secureValue = $null
    $restoredSecureValue = $null
    $passwordPointer = [IntPtr]::Zero
    New-Item -ItemType Directory -Path $integrationRoot | Out-Null
    try {
        $secureValue = ConvertTo-SecureString $secretValue -AsPlainText -Force
        ConvertFrom-SecureString -SecureString $secureValue | Set-Content -LiteralPath $dpapiPath -Encoding ASCII
        $restoredCiphertext = (Get-Content -LiteralPath $dpapiPath -Raw).Trim()
        $restoredSecureValue = ConvertTo-SecureString $restoredCiphertext
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($restoredSecureValue)
        $restoredValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        Assert-True ($secretValue -ceq $restoredValue) "DPAPI must round-trip for the current Windows user."

        $smokeSpec = [pscustomobject]@{
            Name = $smokeTaskName
            Command = (Get-Process -Id $PID).Path
            Arguments = '-NoProfile -NonInteractive -Command "exit 0"'
            Triggers = @(
                [pscustomobject]@{ Hour = 21; Minute = 15 },
                [pscustomobject]@{ Hour = 21; Minute = 45 }
            )
        }
        $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $smokeXml = ConvertTo-SWUCheckinTaskXml -Spec $smokeSpec -UserSid $currentSid -WorkingDirectory $integrationRoot
        Register-ScheduledTask -TaskName $smokeTaskName -Xml $smokeXml -Force | Out-Null
        $registeredTask = Get-ScheduledTask -TaskName $smokeTaskName -ErrorAction Stop
        Assert-Equal $smokeTaskName $registeredTask.TaskName "Task Scheduler must register and query the smoke task."
        [xml]$registeredXml = Export-ScheduledTask -TaskName $smokeTaskName
        $registeredNamespace = New-Object Xml.XmlNamespaceManager($registeredXml.NameTable)
        $registeredNamespace.AddNamespace("task", "http://schemas.microsoft.com/windows/2004/02/mit/task")
        Assert-Equal 2 $registeredXml.SelectNodes("//task:CalendarTrigger", $registeredNamespace).Count "Windows Task Scheduler must preserve both triggers."
        Assert-Equal "IgnoreNew" $registeredXml.Task.Settings.MultipleInstancesPolicy "Windows Task Scheduler must preserve IgnoreNew."
    }
    finally {
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        }
        $restoredValue = $null
        $restoredCiphertext = $null
        $secretValue = $null
        if ($null -ne $restoredSecureValue) { $restoredSecureValue.Dispose() }
        if ($null -ne $secureValue) { $secureValue.Dispose() }
        if ($null -ne (Get-ScheduledTask -TaskName $smokeTaskName -ErrorAction SilentlyContinue)) {
            Unregister-ScheduledTask -TaskName $smokeTaskName -Confirm:$false
        }
        if (Test-Path -LiteralPath $integrationRoot) {
            Remove-Item -LiteralPath $integrationRoot -Recurse -Force
        }
    }
}

Write-Host "Windows PowerShell checks passed."
