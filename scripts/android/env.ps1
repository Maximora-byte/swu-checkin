# Dot-source this script to use the project-local Android tools in this terminal.
param([Uri]$DownloadProxy)
$taskRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.local-tools'
$jdk = @(Get-ChildItem -Path "$taskRoot/jdk17*/jdk-*" -Directory -ErrorAction SilentlyContinue)
if ($jdk.Count -ne 1) { throw 'Install one project-local JDK 17 under .local-tools/jdk17 first.' }
$env:JAVA_HOME = $jdk[0].FullName
$env:ANDROID_HOME = Join-Path $taskRoot 'android-sdk'
if (-not (Test-Path -LiteralPath "$env:ANDROID_HOME/platform-tools/adb.exe")) { throw 'Android SDK platform-tools are missing.' }
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:GRADLE_USER_HOME = Join-Path $taskRoot 'gradle-cache'
$env:ANDROID_USER_HOME = Join-Path $taskRoot 'android-user'
$env:ANDROID_EMULATOR_HOME = $env:ANDROID_USER_HOME
$env:ANDROID_AVD_HOME = Join-Path $env:ANDROID_USER_HOME 'avd'
$env:PYTHONUTF8 = '1'
$env:PIP_CACHE_DIR = Join-Path $taskRoot 'pip-cache'
$python313 = Join-Path $env:LOCALAPPDATA 'Programs/Python/Python313'
$env:PATH = "$env:JAVA_HOME/bin;$env:ANDROID_HOME/platform-tools;$env:ANDROID_HOME/emulator;$python313;$env:PATH"
if ($DownloadProxy) {
    if ($DownloadProxy.Scheme -ne 'http' -or $DownloadProxy.UserInfo) { throw 'Use an HTTP proxy without embedded credentials.' }
    $env:HTTPS_PROXY = $DownloadProxy.AbsoluteUri
    $env:JAVA_TOOL_OPTIONS = "-Dhttps.proxyHost=$($DownloadProxy.Host) -Dhttps.proxyPort=$($DownloadProxy.Port) -Dhttp.proxyHost=$($DownloadProxy.Host) -Dhttp.proxyPort=$($DownloadProxy.Port) -Dhttp.nonProxyHosts=localhost|127.*"
}
Write-Output 'Project-local Android build environment is ready in this terminal.'
