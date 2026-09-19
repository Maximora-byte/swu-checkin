Set-StrictMode -Version Latest

$script:TaskName = "SWUCheckin-Daily"

function Test-SWUCheckinWindows {
    return [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
}

function Get-SWUCheckinInstallRoot {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is not available."
    }
    return Join-Path $env:LOCALAPPDATA "SWUCheckin"
}

function Get-SWUCheckinTaskNames {
    return @($script:TaskName)
}

function Get-SWUCheckinTaskSpecs {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$PowerShellPath
    )

    $runScript = Join-Path $InstallRoot "run.ps1"
    $argument = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $runScript.Replace('"', '""')
    return [pscustomobject]@{
        Name = $script:TaskName
        Command = $PowerShellPath
        Arguments = $argument
        Triggers = @(
            [pscustomobject]@{ Hour = 21; Minute = 15 },
            [pscustomobject]@{ Hour = 21; Minute = 45 }
        )
    }
}

function Get-SWUCheckinLockedSyncArguments {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    return @(
        "sync",
        "--locked",
        "--no-dev",
        "--no-editable",
        "--project",
        $RepositoryRoot,
        "--python",
        "3.13"
    )
}

function Get-SWUCheckinBeijingStartBoundary {
    param(
        [Parameter(Mandatory = $true)][int]$Hour,
        [Parameter(Mandatory = $true)][int]$Minute,
        [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow
    )

    $offset = [TimeSpan]::FromHours(8)
    $beijingNow = $Now.ToOffset($offset)
    $start = [DateTimeOffset]::new(
        $beijingNow.Year,
        $beijingNow.Month,
        $beijingNow.Day,
        $Hour,
        $Minute,
        0,
        $offset
    )
    if ($start -le $beijingNow) {
        $start = $start.AddDays(1)
    }
    return $start.ToString("yyyy-MM-ddTHH:mm:sszzz", [Globalization.CultureInfo]::InvariantCulture)
}

function ConvertTo-SWUCheckinTaskXml {
    param(
        [Parameter(Mandatory = $true)]$Spec,
        [Parameter(Mandatory = $true)][string]$UserSid,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow
    )

    if (@($Spec.Triggers).Count -ne 2) {
        throw "The scheduled task must contain exactly two triggers."
    }
    $triggerXml = foreach ($trigger in $Spec.Triggers) {
        $startBoundary = Get-SWUCheckinBeijingStartBoundary -Hour $trigger.Hour -Minute $trigger.Minute -Now $Now
        @"
    <CalendarTrigger>
      <StartBoundary>$startBoundary</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
"@
    }
    $escapedCommand = [Security.SecurityElement]::Escape([string]$Spec.Command)
    $escapedArguments = [Security.SecurityElement]::Escape([string]$Spec.Arguments)
    $escapedDirectory = [Security.SecurityElement]::Escape($WorkingDirectory)
    $escapedSid = [Security.SecurityElement]::Escape($UserSid)
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>SWU Check-in scheduled run (Beijing time).</Description></RegistrationInfo>
  <Triggers>
$($triggerXml -join "`n")
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$escapedSid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$escapedCommand</Command>
      <Arguments>$escapedArguments</Arguments>
      <WorkingDirectory>$escapedDirectory</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

function Sync-SWUCheckinScheduledTasks {
    param(
        [Parameter(Mandatory = $true)][object[]]$Specs,
        [Parameter(Mandatory = $true)][scriptblock]$RegisterAction
    )

    $seen = @{}
    foreach ($spec in $Specs) {
        if ($seen.ContainsKey($spec.Name)) {
            throw "Duplicate task definition: $($spec.Name)"
        }
        $seen[$spec.Name] = $true
        & $RegisterAction $spec
    }
}

function Remove-SWUCheckinScheduledTasks {
    param([scriptblock]$RemoveAction)

    if ($null -eq $RemoveAction) {
        $RemoveAction = {
            param($TaskName)
            $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            if ($null -ne $existing) {
                Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            }
        }
    }
    & $RemoveAction $script:TaskName
}

function Invoke-SWUCheckinDoctorGate {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$DoctorAction,
        [Parameter(Mandatory = $true)][scriptblock]$InstallTasksAction,
        [Parameter(Mandatory = $true)][scriptblock]$RemoveTasksAction
    )

    $doctorExitCode = [int](& $DoctorAction)
    if ($doctorExitCode -ne 0) {
        & $RemoveTasksAction
        throw "swu-checkin doctor failed with exit code $doctorExitCode; scheduled tasks were not installed."
    }
    & $InstallTasksAction
}

function Invoke-SWUCheckinProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][System.Security.SecureString]$Password,
        [string]$StatusFile,
        [scriptblock]$ProcessRunner
    )

    $passwordPointer = [IntPtr]::Zero
    $plainPassword = $null
    $childEnvironment = @{}
    $startInfo = $null
    $process = $null
    try {
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        $childEnvironment["SWUDK_USERNAME"] = $Username
        $childEnvironment["SWUDK_PASSWORD"] = $plainPassword
        $childEnvironment["PYTHONUTF8"] = "1"
        if (-not [string]::IsNullOrWhiteSpace($StatusFile)) {
            $childEnvironment["SWUDK_STATUS_FILE"] = $StatusFile
        }

        if ($null -ne $ProcessRunner) {
            return [int](& $ProcessRunner $ExecutablePath $Arguments $childEnvironment)
        }

        $startInfo = New-Object Diagnostics.ProcessStartInfo
        $startInfo.FileName = $ExecutablePath
        $startInfo.Arguments = [string]::Join(" ", $Arguments)
        $startInfo.UseShellExecute = $false
        foreach ($name in $childEnvironment.Keys) {
            $startInfo.EnvironmentVariables[$name] = [string]$childEnvironment[$name]
        }
        $process = New-Object Diagnostics.Process
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            throw "Failed to start swu-checkin."
        }
        $process.WaitForExit()
        return $process.ExitCode
    }
    finally {
        if ($null -ne $startInfo) {
            $startInfo.EnvironmentVariables.Remove("SWUDK_PASSWORD")
            $startInfo.EnvironmentVariables.Remove("SWUDK_USERNAME")
            $startInfo.EnvironmentVariables.Remove("SWUDK_STATUS_FILE")
            $startInfo.EnvironmentVariables.Remove("PYTHONUTF8")
        }
        $childEnvironment.Remove("SWUDK_PASSWORD")
        $childEnvironment.Remove("SWUDK_USERNAME")
        $childEnvironment.Remove("SWUDK_STATUS_FILE")
        $childEnvironment.Remove("PYTHONUTF8")
        $plainPassword = $null
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        }
        if ($null -ne $process) {
            $process.Dispose()
        }
        $startInfo = $null
    }
}

Export-ModuleMember -Function @(
    "Test-SWUCheckinWindows",
    "Get-SWUCheckinInstallRoot",
    "Get-SWUCheckinTaskNames",
    "Get-SWUCheckinTaskSpecs",
    "Get-SWUCheckinLockedSyncArguments",
    "Get-SWUCheckinBeijingStartBoundary",
    "ConvertTo-SWUCheckinTaskXml",
    "Sync-SWUCheckinScheduledTasks",
    "Remove-SWUCheckinScheduledTasks",
    "Invoke-SWUCheckinDoctorGate",
    "Invoke-SWUCheckinProcess"
)
